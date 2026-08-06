# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows backend - the Win32 half of the app, unchanged, behind the contract.

Everything here was previously inlined in main.py, system_integration.py and
input_simulation.py. The logic is the same; only its address changed.

Nothing at module level may import config_manager or version: those import this
package back, and the cycle would break the import. Import them inside the
functions instead.
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
import winreg
import winsound
from ctypes import wintypes

__all__ = [
    'config_dir', 'single_instance', 'signal_show', 'start_show_listener',
    'signal_ready', 'start_quit_listener', 'write_app_version',
    'sync_desktop_shortcut', 'sync_run_on_startup',
    'center_xy', 'overlay_xy', 'tame_overlay', 'ensure_overlay_tamed',
    'webview_gui', 'runtime_ok', 'prepare_runtime', 'show_error',
    'subprocess_flags', 'hotkey_cmd',
    'play_beep', 'open_path', 'show_splash',
    'clipboard_get', 'clipboard_set', 'send_paste', 'type_unicode',
    'default_activation_key', 'default_paste_shortcut', 'preferred_hostapis',
    'ui_flags',
]

# ── Shared identifiers (keep in sync with build/launcher.py) ──────────────────
REG_PATH         = r'Software\WhisperVox'              # HKCU; we publish 'Version'
READY_EVENT_NAME = 'WhisperVoxApp_Ready_v1'            # set once our tray is up
QUIT_EVENT_NAME  = 'WhisperVoxApp_Quit_v1'             # a newer installer asks us to exit
SHOW_EVENT_NAME  = 'WhisperVoxApp_Show_v1'             # a 2nd launch asks us to surface
_RUN_KEY         = r'Software\Microsoft\Windows\CurrentVersion\Run'
_RUN_VALUE       = 'WhisperVox'
_MUTEX_NAME      = 'WhisperVoxApp_Mutex_v1'
_WAIT_OBJECT_0   = 0x00000000
_EVENT_MODIFY_STATE = 0x0002
_CREATE_NO_WINDOW = 0x08000000
_ERROR_ALREADY_EXISTS = 183
_WEBVIEW2_GUID = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'

_user32   = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def _app_exe_path():
    """Path of the running (installed) exe; None when running from source."""
    return sys.executable if getattr(sys, 'frozen', False) else None


# ── storage ───────────────────────────────────────────────────────────────────

def config_dir():
    appdata = os.environ.get('APPDATA', os.path.expanduser('~'))
    path = os.path.join(appdata, 'WhisperVox')
    os.makedirs(path, exist_ok=True)
    return path


# ── single instance + installer handshake ─────────────────────────────────────

def single_instance():
    _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    return _kernel32.GetLastError() != _ERROR_ALREADY_EXISTS


def signal_show():
    """Used when a second instance is launched (e.g. double-clicking the Desktop
    shortcut while the app is in the tray) - it signals, then exits."""
    try:
        h = _kernel32.OpenEventW(_EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
        if not h:
            h = _kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
        if h:
            _kernel32.SetEvent(h)
            _kernel32.CloseHandle(h)
            return True
    except Exception:
        pass
    return False


def start_show_listener(on_show):
    """Watch the show-event (auto-reset, so it re-fires) and surface the window
    each time a second instance pings us."""
    def _poll():
        h = _kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)  # auto-reset
        if not h:
            return
        while True:
            if _kernel32.WaitForSingleObject(h, 0) == _WAIT_OBJECT_0:
                try:
                    on_show()
                except Exception:
                    pass
            time.sleep(0.3)

    threading.Thread(target=_poll, daemon=True).start()


def signal_ready():
    """Set the named event the installer's splash waits on before closing."""
    try:
        h = _kernel32.CreateEventW(None, True, False, READY_EVENT_NAME)
        if h:
            _kernel32.SetEvent(h)
            _kernel32.CloseHandle(h)
    except Exception:
        pass


def start_quit_listener(on_quit):
    """A newer installer sets a named event to ask us to exit so it can swap in
    new files. Poll it on a background thread and call on_quit() when signalled."""
    def _poll():
        h = _kernel32.CreateEventW(None, True, False, QUIT_EVENT_NAME)
        if not h:
            return
        while True:
            if _kernel32.WaitForSingleObject(h, 0) == _WAIT_OBJECT_0:
                on_quit()
                return
            time.sleep(0.3)

    threading.Thread(target=_poll, daemon=True).start()


def write_app_version():
    """Publish the running version to HKCU so an installer dropped anywhere can
    tell what's installed and decide whether to take over with an update."""
    from version import get_version
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
            winreg.SetValueEx(key, 'Version', 0, winreg.REG_SZ, get_version())
    except Exception:
        pass


def sync_desktop_shortcut():
    """Create/remove the Desktop shortcut per the 'desktop_icon' option. Targets
    the installed exe (this process). Removal only touches a shortcut pointing at
    this exe - never a user's unrelated .lnk."""
    from config_manager import ConfigManager
    exe = _app_exe_path()
    if not exe:
        return
    exe_ps = exe.replace("'", "''")
    wd_ps = os.path.dirname(exe).replace("'", "''")
    if ConfigManager.get('desktop_icon'):
        ps = (
            "$ws = New-Object -ComObject WScript.Shell; "
            "$desk = $ws.SpecialFolders('Desktop'); "
            "$s = $ws.CreateShortcut(\"$desk\\Whisper Vox.lnk\"); "
            f"$s.TargetPath = '{exe_ps}'; "
            f"$s.WorkingDirectory = '{wd_ps}'; "
            "$s.Description = 'Whisper Vox voice dictation'; "
            "$s.Save()"
        )
    else:
        ps = (
            "$ws = New-Object -ComObject WScript.Shell; "
            "$desk = $ws.SpecialFolders('Desktop'); "
            "$p = \"$desk\\Whisper Vox.lnk\"; "
            "if (Test-Path $p) { "
            "$s = $ws.CreateShortcut($p); "
            f"if ($s.TargetPath -eq '{exe_ps}') {{ Remove-Item $p -Force }} "
            "}"
        )

    def _run():
        try:
            subprocess.run(
                ['powershell', '-WindowStyle', 'Hidden', '-NoProfile', '-Command', ps],
                capture_output=True, timeout=15, creationflags=_CREATE_NO_WINDOW,
            )
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def sync_run_on_startup():
    """Register/unregister per-user autostart via the HKCU Run key (no admin).
    Points at the installed exe directly, so a background boot launches the app
    silently - never the installer."""
    from config_manager import ConfigManager
    exe = _app_exe_path()
    if not exe:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if ConfigManager.get('run_on_startup'):
                # --autostart marks the boot launch so the app honours 'start
                # minimized' ONLY here; a manual icon click (no flag) always shows.
                winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, f'"{exe}" --autostart')
            else:
                try:
                    winreg.DeleteValue(key, _RUN_VALUE)
                except FileNotFoundError:
                    pass
    except Exception:
        pass


# ── window geometry ───────────────────────────────────────────────────────────

def _dpi_scale():
    try:
        _user32.GetDpiForSystem.restype = ctypes.c_uint
        return (_user32.GetDpiForSystem() or 96) / 96.0
    except Exception:
        return 1.0


def center_xy(win_w, win_h):
    """Return (x, y) to centre a window in pywebview's logical coordinate space.

    webview.screens[0].width/height are physical pixels; window.move() and
    create_window(width/height) use logical (DIP) pixels.  Dividing by the
    DPI scale factor converts correctly on scaled displays (e.g. 125% -> /1.25).
    """
    try:
        import webview as _wv
        s = _wv.screens[0]
        scale = _dpi_scale()
        w_log = round(s.width / scale)
        h_log = round(s.height / scale)
        return (w_log - win_w) // 2, (h_log - win_h) // 2
    except Exception:
        sw = _user32.GetSystemMetrics(0)
        sh = _user32.GetSystemMetrics(1)
        return (sw - win_w) // 2, (sh - win_h) // 2


def overlay_xy(win_w, win_h):
    """Bottom-centre (x, y) for the status overlay, in logical (DIP) pixels.

    Computed from the CURRENT primary-monitor WORK AREA (which already excludes
    the taskbar) rather than full-screen-height-minus-a-guess. Recomputed on
    every show, so a monitor hot-plug / resolution / DPI change since startup
    can no longer strand the window under the taskbar. Clamped to the work area
    as a final safety net. Falls back to full-screen metrics on any failure.
    """
    scale = _dpi_scale()
    try:
        class _RECT(ctypes.Structure):
            _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                        ('right', ctypes.c_long), ('bottom', ctypes.c_long)]
        r = _RECT()
        SPI_GETWORKAREA = 0x0030
        if not _user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
            raise OSError
        wa_left, wa_top, wa_right, wa_bottom = r.left, r.top, r.right, r.bottom
    except Exception:
        wa_left, wa_top = 0, 0
        wa_right, wa_bottom = _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)
    left_l, top_l = round(wa_left / scale), round(wa_top / scale)
    right_l, bottom_l = round(wa_right / scale), round(wa_bottom / scale)
    margin = 24  # gap above the work-area bottom (i.e. just above the taskbar)
    x = left_l + ((right_l - left_l) - win_w) // 2
    y = bottom_l - win_h - margin
    # Clamp so the overlay can never land off the visible work area.
    x = max(left_l, min(x, right_l - win_w))
    y = max(top_l, min(y, bottom_l - win_h))
    return x, y


_overlay_taskbar_fixed = False


def _hide_overlay_taskbar():
    # Remove the overlay's taskbar button: add WS_EX_TOOLWINDOW, drop
    # WS_EX_APPWINDOW. The window is created hidden at startup, so find it by
    # title once it exists, then re-apply the frame so the change sticks.
    global _overlay_taskbar_fixed
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_APPWINDOW = 0x00040000
    SWP = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
    for _ in range(20):
        hwnd = _user32.FindWindowW(None, 'WhisperVoxOverlay')
        if hwnd:
            ex = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            _user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                   (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
            _user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP)
            _overlay_taskbar_fixed = True
            return
        time.sleep(0.25)


def tame_overlay(window):
    """The overlay leaks visible when webview.start() shows the master window.
    Once it has realized, strip its taskbar button and force it hidden so it
    only ever appears during recording."""
    time.sleep(0.4)
    _hide_overlay_taskbar()
    for _ in range(8):
        try:
            window.hide()
        except Exception:
            pass
        time.sleep(0.12)


def ensure_overlay_tamed(window):
    """Fallback for the show path: if startup taming didn't catch the window,
    strip the taskbar button now."""
    if not _overlay_taskbar_fixed:
        threading.Thread(target=_hide_overlay_taskbar, daemon=True).start()


# ── process + GUI plumbing ────────────────────────────────────────────────────

def webview_gui():
    return 'edgechromium'


def runtime_ok():
    for hive, path in (
        (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}'),
        (winreg.HKEY_CURRENT_USER,  rf'Software\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}'),
        (winreg.HKEY_LOCAL_MACHINE, rf'SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}'),
    ):
        try:
            with winreg.OpenKey(hive, path) as key:
                pv, _ = winreg.QueryValueEx(key, 'pv')
                if pv and pv != '0.0.0.0':
                    return True, ''
        except OSError:
            continue
    return False, ('Microsoft Edge WebView2 Runtime is required but not installed.\n\n'
                   'Install it from:\n'
                   'https://developer.microsoft.com/microsoft-edge/webview2/')


def prepare_runtime():
    """WebView2 only ever renders LOCAL files - it needs no network. Disabling
    proxy auto-detection / background networking avoids any corporate-network
    startup stalls. (Transcription is unaffected - it uses the Python OpenAI
    client, not WebView2.) Must be set before the WebView2 environment exists."""
    os.environ.setdefault(
        'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS',
        '--no-proxy-server --disable-background-networking '
        '--disable-component-update --no-first-run '
        '--disable-features=msSmartScreenProtection,OptimizationHints')


def show_error(title, message):
    _user32.MessageBoxW(0, message, title, 0x10)


def subprocess_flags():
    return _CREATE_NO_WINDOW


def hotkey_cmd(script_path):
    if getattr(sys, 'frozen', False):
        # Frozen: sys.executable IS our exe - re-invoke it with --hotkey so the
        # same binary runs the listener (pynput) in a separate process.
        return [sys.executable, '--hotkey']
    # Source: pythonw.exe so the subprocess has NO console window.
    pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    exe = pyw if os.path.exists(pyw) else sys.executable
    return [exe, script_path]


# ── odds and ends ─────────────────────────────────────────────────────────────

def play_beep(path):
    threading.Thread(
        target=winsound.PlaySound,
        args=(path, winsound.SND_FILENAME | winsound.SND_ASYNC),
        daemon=True,
    ).start()


def open_path(path):
    os.startfile(path)


def show_splash(text, activation_key, version):
    from splash import Splash
    splash = Splash(text, activation_key=activation_key, version=version)
    splash.wait_ready(timeout=1.5)
    return splash


# ── text injection ────────────────────────────────────────────────────────────
# 64-bit-safe signatures (handles/pointers must not be truncated to c_int)
_kernel32.GlobalAlloc.restype  = ctypes.c_void_p
_kernel32.GlobalAlloc.argtypes = (wintypes.UINT, ctypes.c_size_t)
_kernel32.GlobalLock.restype   = ctypes.c_void_p
_kernel32.GlobalLock.argtypes  = (ctypes.c_void_p,)
_kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
_user32.GetClipboardData.restype  = ctypes.c_void_p
_user32.GetClipboardData.argtypes = (wintypes.UINT,)
_user32.SetClipboardData.restype  = ctypes.c_void_p
_user32.SetClipboardData.argtypes = (wintypes.UINT, ctypes.c_void_p)

CF_UNICODETEXT  = 13
GMEM_MOVEABLE   = 0x0002

INPUT_KEYBOARD    = 1
KEYEVENTF_KEYUP   = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_RETURN  = 0x0D
VK_SHIFT   = 0x10
VK_CONTROL = 0x11
VK_INSERT  = 0x2D
VK_V       = 0x56

_ULONG_PTR = ctypes.c_size_t


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ('wVk',         wintypes.WORD),
        ('wScan',       wintypes.WORD),
        ('dwFlags',     wintypes.DWORD),
        ('time',        wintypes.DWORD),
        ('dwExtraInfo', _ULONG_PTR),
    )


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = (('ki', _KEYBDINPUT),
                    ('pad', ctypes.c_byte * 32))  # MOUSEINPUT is the largest member
    _anonymous_ = ('u',)
    _fields_ = (('type', wintypes.DWORD), ('u', _U))


def _send_inputs(events):
    """events: list of (wVk, wScan, dwFlags) tuples sent as one SendInput batch."""
    n = len(events)
    arr = (_INPUT * n)()
    for i, (vk, scan, flags) in enumerate(events):
        arr[i].type = INPUT_KEYBOARD
        arr[i].ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
    _user32.SendInput(n, arr, ctypes.sizeof(_INPUT))


def _open_clipboard(retries=10, delay=0.02):
    for _ in range(retries):
        if _user32.OpenClipboard(None):
            return True
        time.sleep(delay)  # another app may hold the clipboard briefly
    return False


def clipboard_get():
    if not _open_clipboard():
        return None
    try:
        if not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = _kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.c_wchar_p(ptr).value
        finally:
            _kernel32.GlobalUnlock(handle)
    finally:
        _user32.CloseClipboard()


def clipboard_set(text):
    buf = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(buf)
    handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not handle:
        return False
    ptr = _kernel32.GlobalLock(handle)
    ctypes.memmove(ptr, buf, size)
    _kernel32.GlobalUnlock(handle)
    if not _open_clipboard():
        _kernel32.GlobalFree(handle)
        return False
    try:
        _user32.EmptyClipboard()
        # On success the system owns the handle - do not free it ourselves
        return bool(_user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        _user32.CloseClipboard()


def send_paste(shortcut):
    if shortcut == 'shift+insert':
        mod, key = VK_SHIFT, VK_INSERT
    else:
        mod, key = VK_CONTROL, VK_V
    _send_inputs([
        (mod, 0, 0),
        (key, 0, 0),
        (key, 0, KEYEVENTF_KEYUP),
        (mod, 0, KEYEVENTF_KEYUP),
    ])


def type_unicode(text):
    """Per-character SendInput; the keyboard layout is irrelevant."""
    from config_manager import ConfigManager
    delay = float(ConfigManager.get('writing_key_press_delay', 0.005) or 0)
    for ch in text:
        if ch in ('\n', '\r'):
            _send_inputs([(VK_RETURN, 0, 0), (VK_RETURN, 0, KEYEVENTF_KEYUP)])
        else:
            # UTF-16 code units (handles emoji/surrogate pairs)
            raw = ch.encode('utf-16-le')
            units = [int.from_bytes(raw[i:i + 2], 'little')
                     for i in range(0, len(raw), 2)]
            events = []
            for u in units:
                events.append((0, u, KEYEVENTF_UNICODE))
                events.append((0, u, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
            _send_inputs(events)
        if delay:
            time.sleep(delay)


# ── platform-shaped defaults and capabilities ─────────────────────────────────

def default_activation_key():
    return 'f2'


def default_paste_shortcut():
    return 'ctrl+v'


def preferred_hostapis():
    """WASAPI gives clean, full, de-duplicated names that match Windows Sound
    settings (MME truncates to 31 chars; WDM-KS emits raw driver strings like
    '@System32\\drivers\\...'). Fall back to MME if WASAPI is unavailable."""
    return ('WASAPI', 'MME')


def ui_flags():
    return {
        'platform': 'win32',
        'os_name': 'Windows',
        'paste_shortcuts': [('ctrl+v', 'Ctrl+V'), ('shift+insert', 'Shift+Insert')],
        'hidden_options': [],
        'startup_label': 'Run on Startup',
    }
