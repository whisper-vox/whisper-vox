# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Whisper Vox — application orchestrator (Qt-free, pywebview + pystray).

Wires the Qt-free backend to the new UI shell:
  • pywebview (WebView2) renders the Settings window from local HTML.
  • pystray provides the tray icon (left-click opens Settings; menu: Settings/Donate/Quit).
  • the recording flow (hotkey → ResultThread → text injection) mirrors the original
    main.py but uses plain callbacks instead of Qt signals.

Hard-won constraints on this stack (see WEBUI_MIGRATION_PLAN.md):
  • The js_api object must hold NO reference to App/windows — pywebview introspects it
    and would recurse forever through window.native.AccessibilityObject (~20 s GUI hang).
    The App back-reference lives in api.py at module level (set_app), never on the object.
  • pynput's global hooks run in a SEPARATE process (hotkey_proc.py); in-process they
    fight the WebView2 (.NET) message loop and lag input desktop-wide.
  • Never call the bridge during page load — only on user action.

Deferred: full Settings UI + save/restart + update check (Phase 3); status overlay via
lazy creation (Phase 4); PyInstaller specs + launcher events (Phase 5).

Run from source:  .venv\Scripts\python.exe src\main.py
"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import webbrowser
import winreg
import winsound

_src = os.path.dirname(os.path.abspath(__file__))
if _src not in sys.path:
    sys.path.insert(0, _src)

from config_manager import ConfigManager
ConfigManager.initialize()

import webview
import pystray
from PIL import Image

from input_simulation import InputSimulator
from result_thread import ResultThread, refresh_device_cache
from version import get_version
from settings_data import RELEASES_URL
from api import Api, set_app
import system_integration as sysint
from splash import Splash

DONATE_URL = 'https://nowpayments.io/donation/PekelniBoroshnaLab'
OVERLAY_W, OVERLAY_H = 320, 150
_MUTEX_NAME = 'WhisperVoxApp_Mutex_v1'
_ERROR_ALREADY_EXISTS = 183
_WEBVIEW2_GUID = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'


def _root(*parts):
    """Path that works in dev (project root = parent of src) and frozen (_MEIPASS)."""
    base = getattr(sys, '_MEIPASS',
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


def _center_xy(win_w, win_h):
    """Return (x, y) to centre a window in pywebview's logical coordinate space.

    webview.screens[0].width/height are physical pixels; window.move() and
    create_window(width/height) use logical (DIP) pixels.  Dividing by the
    DPI scale factor converts correctly on scaled displays (e.g. 125% → /1.25).
    """
    try:
        import webview as _wv
        s = _wv.screens[0]
        user32 = ctypes.windll.user32
        user32.GetDpiForSystem.restype = ctypes.c_uint
        dpi = user32.GetDpiForSystem() or 96
        scale = dpi / 96.0
        w_log = round(s.width / scale)
        h_log = round(s.height / scale)
        return (w_log - win_w) // 2, (h_log - win_h) // 2
    except Exception:
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        return (sw - win_w) // 2, (sh - win_h) // 2


def _single_instance():
    """True if we are the first instance; False if one is already running."""
    ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() != _ERROR_ALREADY_EXISTS


def _webview2_present():
    for hive, path in (
        (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}'),
        (winreg.HKEY_CURRENT_USER,  rf'Software\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}'),
        (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}'),
    ):
        try:
            with winreg.OpenKey(hive, path) as key:
                pv, _ = winreg.QueryValueEx(key, 'pv')
                if pv and pv != '0.0.0.0':
                    return True
        except OSError:
            continue
    return False


class App:
    def __init__(self):
        self.settings_window = None
        self.overlay_window = None
        self.tray = None
        self.result_thread = None
        self.input_simulator = InputSimulator()
        self._hotkey_proc = None
        self._api = None
        self._overlay_ready = False
        self._overlay_taskbar_fixed = False
        self._update_version = ''   # latest newer version (shown in the tray menu)
        self._splash = None
        self._first_run = False
        self._autostart = False   # set in run(): True only for the boot autostart

    # ── windows ────────────────────────────────────────────────────────────────
    def show_settings(self, goto_api=False):
        if self.settings_window:
            try:
                cx, cy = _center_xy(860, 720)
                self.settings_window.move(cx, cy)
            except Exception:
                pass
            try:
                self.settings_window.show()
            except Exception:
                pass
            # When surfaced because no API key is set, jump straight to the
            # API & Model tab so the user lands on the field they must fill in.
            if goto_api:
                try:
                    self.settings_window.evaluate_js("gotoTab('api')")
                except Exception:
                    pass

    def hide_settings(self):
        if self.settings_window:
            try:
                self.settings_window.hide()
            except Exception:
                pass

    def _on_settings_closing(self):
        # Hide to tray instead of letting the close quit the app. Returning False
        # cancels the native close; do the hide off the event thread.
        threading.Thread(target=self.hide_settings, daemon=True).start()
        return False

    def _on_overlay_loaded(self):
        self._overlay_ready = True

    def _on_settings_loaded(self):
        # Page is up — the slow WebView2 init is done; drop the startup splash and
        # show the settings window (it starts hidden when a splash is used or when
        # start_minimized is set, to avoid the brief flash of an unloaded window).
        if self._splash:
            self._splash.close()
            self._splash = None
        # Show the window unless this is an autostart that wants a minimized start.
        if not (self._autostart and ConfigManager.get('start_minimized')):
            threading.Thread(target=self.show_settings, daemon=True).start()

    def _hide_overlay_taskbar(self):
        # Remove the overlay's taskbar button: add WS_EX_TOOLWINDOW, drop
        # WS_EX_APPWINDOW. The window is created hidden at startup, so find it by
        # title once it exists, then re-apply the frame so the change sticks.
        import time
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        SWP = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
        u = ctypes.windll.user32
        for _ in range(20):
            hwnd = u.FindWindowW(None, 'WhisperVoxOverlay')
            if hwnd:
                ex = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
                u.SetWindowLongW(hwnd, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
                u.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP)
                self._overlay_taskbar_fixed = True
                return
            time.sleep(0.25)

    def _eval_overlay(self, js):
        # Only touch JS once the overlay page is loaded — evaluate_js on an
        # unloaded WebView2 window can block the calling (recording) thread.
        if self.overlay_window and self._overlay_ready:
            try:
                self.overlay_window.evaluate_js(js)
            except Exception:
                pass

    def _set_overlay(self, state):
        # Mirrors status_window.updateStatus. Respects the Hide-Status-Window option.
        if ConfigManager.get('hide_status_window') or not self.overlay_window:
            return
        if state in ('preparing', 'recording', 'transcribing'):
            try:
                self.overlay_window.show()
            except Exception:
                pass
            # Fallback: if startup taming didn't catch it, strip the taskbar button.
            if not self._overlay_taskbar_fixed:
                threading.Thread(target=self._hide_overlay_taskbar, daemon=True).start()
            self._eval_overlay(f"window.setState('{state}')")
        else:
            self._eval_overlay("window.setState('idle')")
            try:
                self.overlay_window.hide()
            except Exception:
                pass

    def _show_overlay_error(self, msg):
        # Layer 2 — show the red error cue in the status overlay with a reason,
        # then auto-hide after a few seconds. Respects Hide-Status-Window. Used by
        # the transcription-failure callback AND the no-key pre-flight guard.
        if (ConfigManager.get('hide_status_window') or not self.overlay_window
                or not self._overlay_ready):
            return
        try:
            self.overlay_window.show()
        except Exception:
            pass
        if not self._overlay_taskbar_fixed:
            threading.Thread(target=self._hide_overlay_taskbar, daemon=True).start()
        self._eval_overlay(f"window.setError({json.dumps(msg)})")
        threading.Thread(target=self._auto_hide_overlay, args=(4.5,), daemon=True).start()

    def _auto_hide_overlay(self, delay):
        import time
        time.sleep(delay)
        # A new recording may have started meanwhile — don't yank its overlay.
        if self.result_thread and self.result_thread.is_alive():
            return
        self._eval_overlay("window.setState('idle')")
        try:
            self.overlay_window.hide()
        except Exception:
            pass

    # ── recording callbacks (run on the ResultThread) ───────────────────────────
    def _on_status(self, state):
        self._set_overlay(state)

    def _on_level(self, level):
        self._eval_overlay(f"window.setLevel({level:.3f})")

    def _on_error(self, reason):
        # A recording produced no text (bad/missing key, no connection, server
        # error). Show the reason in the overlay instead of vanishing silently.
        self._show_overlay_error(reason)

    def _on_result(self, text):
        if text:
            self.input_simulator.typewrite(text)
        if ConfigManager.get('noise_on_completion'):
            beep = _root('assets', 'beep.wav')
            threading.Thread(
                target=winsound.PlaySound,
                args=(beep, winsound.SND_FILENAME | winsound.SND_ASYNC),
                daemon=True,
            ).start()

    # ── hotkey flow (mirrors original main.py) ──────────────────────────────────
    def _on_activate(self):
        # Layer 1 — pre-flight guard: with no API key, recording would go into the
        # void (no server contact). Skip it; show the reason and surface Settings
        # so the user can paste a key instead of dictating to nothing.
        if not str(ConfigManager.get('api_key') or '').strip():
            self._show_overlay_error('No API key set — add it in Settings to start dictation.')
            threading.Thread(target=self.show_settings, kwargs={'goto_api': True},
                             daemon=True).start()
            return
        if self.result_thread and self.result_thread.is_alive():
            if ConfigManager.get('recording_mode', 'hold_to_record') == 'press_to_toggle':
                self.result_thread.stop_recording()
            return
        self._start_recording()

    def _on_deactivate(self):
        if ConfigManager.get('recording_mode', 'hold_to_record') == 'hold_to_record':
            if self.result_thread and self.result_thread.is_alive():
                self.result_thread.stop_recording()

    def stop_current_recording(self):
        if self.result_thread and self.result_thread.is_alive():
            self.result_thread.stop_recording()

    def apply_settings(self):
        # Live-apply after a Save. Most settings are read fresh from config at use
        # time (recording mode, transcription params, input method…). The activation
        # key is read by the hotkey subprocess at ITS startup, so restart it; and
        # refresh the device cache in case the microphone changed.
        try:
            if self._hotkey_proc:
                self._hotkey_proc.terminate()
        except Exception:
            pass
        self._start_hotkey_listener()
        try:
            refresh_device_cache(reinit=False)
        except Exception:
            pass
        # Desktop shortcut + autostart toggles take effect immediately on Save.
        sysint.sync_desktop_shortcut()
        sysint.sync_run_on_startup()

    def _start_recording(self):
        if self.result_thread and self.result_thread.is_alive():
            return
        self.result_thread = ResultThread(
            on_status=self._on_status,
            on_result=self._on_result,
            on_level=self._on_level,
            on_error=self._on_error,
        )
        self.result_thread.start()

    # ── tray ─────────────────────────────────────────────────────────────────--
    def _build_tray(self):
        try:
            img = Image.open(_root('assets', 'wv-logo.png'))
        except Exception:
            img = Image.new('RGBA', (64, 64), (74, 144, 217, 255))
        key = str(ConfigManager.get('activation_key', 'f2')).upper()
        menu = pystray.Menu(
            # default=True -> plain LEFT-click opens Settings (intuitive)
            pystray.MenuItem('Settings', self._tray_settings, default=True),
            # Appears only when an update is available (mirrors the old build).
            pystray.MenuItem(lambda item: f'⬆  Update available  ({self._update_version})',
                             self._tray_update,
                             visible=lambda item: bool(self._update_version)),
            pystray.MenuItem('Donate', self._tray_donate),
            pystray.MenuItem('Quit', self._quit),
        )
        self.tray = pystray.Icon(
            'whispervox', img,
            f'Whisper Vox v{get_version()}\nActivation key: {key}', menu)
        self.tray.run()

    def _tray_settings(self, icon, item):
        self.show_settings()

    def _tray_donate(self, icon, item):
        webbrowser.open(DONATE_URL)

    def _tray_update(self, icon, item):
        self.start_update()

    def start_update(self):
        """One-click update: download the official setup and run it. The setup
        asks us to quit (our quit-listener handles that), swaps the files, and
        relaunches. Falls back to opening the releases page in the browser."""
        threading.Thread(target=self._run_update, daemon=True).start()
        return True

    def _run_update(self):
        from updater import latest_installer_url, download_installer
        if not getattr(sys, 'frozen', False):
            # From source there's nothing to swap — just open the releases page.
            webbrowser.open(RELEASES_URL)
            return
        url = latest_installer_url()
        path = download_installer(url) if url else None
        if not path:
            webbrowser.open(RELEASES_URL)   # let the user grab it manually
            return
        try:
            subprocess.Popen([path], cwd=os.path.dirname(path))
        except Exception:
            webbrowser.open(RELEASES_URL)

    def set_update_version(self, version):
        """Called by the update check (background or from Settings) — refresh the
        tray menu so the 'Update available' item shows/hides."""
        self._update_version = version or ''
        try:
            if self.tray:
                self.tray.update_menu()
        except Exception:
            pass

    def _startup_update_check(self):
        import time
        from updater import check_latest, is_newer
        # Reflect the stored result immediately (so the tray shows it at once).
        stored = str(ConfigManager.get('update_available_version') or '')
        if stored and is_newer(stored, get_version()):
            self.set_update_version(stored)
        if not ConfigManager.get('auto_check_updates'):
            return
        time.sleep(4)   # don't compete with startup
        latest = check_latest()
        if latest and is_newer(latest, get_version()):
            ConfigManager.set('update_available_version', latest)
            ConfigManager.save()
            self.set_update_version(latest)

    # ── hotkey listener (separate process — see hotkey_proc.py) ─────────────────
    def _start_hotkey_listener(self):
        CREATE_NO_WINDOW = 0x08000000
        if getattr(sys, 'frozen', False):
            # Frozen: sys.executable IS our exe — re-invoke it with --hotkey so the
            # same binary runs the listener (pynput) in a separate process.
            cmd = [sys.executable, '--hotkey']
        else:
            # Source: pythonw.exe so the subprocess has NO console window.
            pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
            exe = pyw if os.path.exists(pyw) else sys.executable
            cmd = [exe, _root('src', 'hotkey_proc.py')]
        self._hotkey_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, creationflags=CREATE_NO_WINDOW)
        threading.Thread(target=self._read_hotkey_events, daemon=True).start()

    def _read_hotkey_events(self):
        for line in self._hotkey_proc.stdout:
            ev = line.strip()
            if ev == 'ACT':
                self._on_activate()
            elif ev == 'DEACT':
                self._on_deactivate()

    def _shutdown(self):
        """Clean exit: stop the hotkey subprocess and the tray, then leave."""
        try:
            if self._hotkey_proc:
                self._hotkey_proc.terminate()
        except Exception:
            pass
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        os._exit(0)

    def _quit(self, icon, item):
        self._shutdown()

    # ── lifecycle ────────────────────────────────────────────────────────────--
    def _on_start(self):
        # Runs DURING the WebView2 (.NET) GUI loop — only loop-safe work here.
        threading.Thread(target=self._build_tray, daemon=True).start()
        threading.Thread(target=self._startup_update_check, daemon=True).start()
        threading.Thread(target=self._tame_overlay, daemon=True).start()
        # System integration: publish version, sync per-user shortcut/autostart,
        # let a newer installer ask us to quit, and tell the installer's splash
        # we're up (so it can close).
        sysint.write_registry_version()
        sysint.sync_desktop_shortcut()
        sysint.sync_run_on_startup()
        sysint.start_quit_listener(self._shutdown)
        sysint.start_show_listener(self.show_settings)
        sysint.signal_ready()

    def _tame_overlay(self):
        # The overlay leaks visible when webview.start() shows the master window.
        # Once it has realized, strip its taskbar button and force it hidden so it
        # only ever appears during recording.
        import time
        time.sleep(0.4)
        self._hide_overlay_taskbar()
        for _ in range(8):
            try:
                self.overlay_window.hide()
            except Exception:
                pass
            time.sleep(0.12)

    def run(self):
        if not _single_instance():
            # Already running (e.g. launched again via the Desktop shortcut while
            # in the tray): tell that instance to surface its window, then exit.
            sysint.signal_show()
            sys.exit(0)
        if not _webview2_present():
            ctypes.windll.user32.MessageBoxW(
                0,
                'Microsoft Edge WebView2 Runtime is required but not installed.\n\n'
                'Install it from:\n'
                'https://developer.microsoft.com/microsoft-edge/webview2/',
                'Whisper Vox', 0x10)
            sys.exit(1)

        # WebView2 only ever renders LOCAL files — it needs no network. Disabling
        # proxy auto-detection / background networking avoids any corporate-network
        # startup stalls. (Transcription is unaffected — it uses the Python OpenAI
        # client, not WebView2.) Must be set before the WebView2 environment exists.
        os.environ.setdefault(
            'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS',
            '--no-proxy-server --disable-background-networking '
            '--disable-component-update --no-first-run '
            '--disable-features=msSmartScreenProtection,OptimizationHints')

        api = Api()
        self._api = api   # reused as js_api for the lazily-created overlay window
        set_app(self)   # module-level back-ref — NEVER an attribute on the api object

        # Determine first-run and splash state BEFORE creating windows so we can
        # set the correct initial hidden flag. "First run" = not yet configured (no
        # API key): forces splash + visible window so a brand-new user sees progress
        # and the setup screen. Once configured, it's the Misc 'Show splash' toggle
        # (off by default). Suppressed when the installer launched us — it already
        # shows its own splash.
        self._first_run = not ConfigManager.config_exists()
        from_installer = bool(os.environ.get('WHISPERVOX_FROM_INSTALLER'))
        _show_splash = (not from_installer) and (self._first_run or ConfigManager.get('show_splash'))

        # 'Start minimized to tray' applies ONLY to a Windows-boot autostart — the
        # Run-key entry passes --autostart. A MANUAL launch (Desktop / Start-Menu
        # icon) and the installer's first post-install launch always show the
        # window: clicking the app icon should open the app, not vanish to the tray.
        self._autostart = ('--autostart' in sys.argv)

        # Start hidden when splash is active (prevents flash behind it) or when an
        # autostart honours 'start minimized'. Otherwise start visible so the OS can
        # paint the window immediately; show_settings() re-centres it on load.
        _start_hidden = _show_splash or (self._autostart and ConfigManager.get('start_minimized'))
        self.settings_window = webview.create_window(
            'Whisper Vox', url=_root('web', 'settings.html'),
            width=860, height=720, min_size=(800, 700),
            hidden=_start_hidden, js_api=api)
        # Closing the window hides it to the tray instead of quitting the app.
        self.settings_window.events.closing += self._on_settings_closing
        # Once the page is up: dismiss the splash and show the window if appropriate.
        self.settings_window.events.loaded += self._on_settings_loaded

        # Status overlay: created NOW (before webview.start, like the validated
        # spike) but hidden. Creating it dynamically after start() produced a
        # taskbar stub that rendered in its thumbnail yet never painted on screen.
        user32 = ctypes.windll.user32
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        try:
            user32.GetDpiForSystem.restype = ctypes.c_uint
            _dpi = user32.GetDpiForSystem() or 96
            _scale = _dpi / 96.0
        except Exception:
            _scale = 1.0
        sw_l, sh_l = round(sw / _scale), round(sh / _scale)
        ox, oy = (sw_l - OVERLAY_W) // 2, sh_l - OVERLAY_H - 80
        self.overlay_window = webview.create_window(
            'WhisperVoxOverlay', url=_root('web', 'overlay.html'),
            width=OVERLAY_W, height=OVERLAY_H, x=ox, y=oy,
            frameless=True, on_top=True, transparent=True,
            easy_drag=False, hidden=True, js_api=api)
        self.overlay_window.events.loaded += self._on_overlay_loaded

        # pynput runs in a SEPARATE process (hotkey_proc.py): its global low-level
        # hooks cannot share a process with the WebView2 (.NET) message loop without
        # lagging input desktop-wide. The old Qt build didn't hit this.
        self._start_hotkey_listener()
        refresh_device_cache()

        # Show the splash NOW (before webview.start blocks the main thread) and wait
        # until its Win32 window is actually visible. This guarantees the user sees
        # something on screen before WebView2 takes over, and prevents the race where
        # _on_settings_loaded fires and calls close() before ShowWindow has run.
        if _show_splash:
            key = str(ConfigManager.get('activation_key', 'f2')).upper()
            self._splash = Splash('Preparing Whisper Vox...', activation_key=key,
                                  version=get_version())
            self._splash.wait_ready(timeout=1.5)

        webview.start(self._on_start, gui='edgechromium', debug=False)


if __name__ == '__main__':
    # When re-invoked with --hotkey (frozen build), this same binary runs ONLY the
    # global-hotkey listener in a separate process — never the GUI app.
    if '--hotkey' in sys.argv:
        import hotkey_proc
        hotkey_proc.main()
    else:
        App().run()
