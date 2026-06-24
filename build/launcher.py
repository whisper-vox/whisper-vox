# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Whisper Vox installer / updater (single-file, self-extracting).

Per-user install - no admin rights, no system-wide changes:
  - First run / version change: show a splash with progress, extract the bundled
    app into %LOCALAPPDATA%\\Programs\\WhisperVox, create a Start-Menu shortcut,
    launch the app, and keep the splash up until the app signals it is ready.
  - Already up to date: launch the installed app SILENTLY (no splash). This is the
    everyday / autostart path - the splash never flashes on a normal boot, because
    autostart and shortcuts point straight at the installed exe, not at this setup.
  - Update over a running version: ask it to exit, swap the files atomically,
    relaunch. This is the engine the in-app "Update now" uses (it downloads this
    setup and runs it).

To uninstall: Settings > Apps > Whisper Vox > Uninstall (it registers a per-user
Apps & Features entry whose UninstallString runs uninstall.exe --uninstall, which
removes the app files, shortcuts, autostart and registry, and optionally the
personal settings). Running this setup with --uninstall does the same.

NOTE: keep this file ASCII-only. build_all.ps1 rewrites the BUILD_DATE line, and
a non-ASCII char would be mangled by the read/write round-trip on Windows.
"""
import os
import sys
import time
import tempfile
import zipfile
import shutil
import subprocess
import ctypes
import ctypes.wintypes as wintypes
import threading
import winreg

APP_VERSION = '1.2.0'
BUILD_DATE  = '2026-06-24'  # stamped by build_all.ps1

# These names MUST match src/system_integration.py and src/main.py.
MUTEX_NAME       = 'WhisperVoxApp_Mutex_v1'   # the app holds this while running
READY_EVENT_NAME = 'WhisperVoxApp_Ready_v1'   # app sets it once its tray is up
QUIT_EVENT_NAME  = 'WhisperVoxApp_Quit_v1'    # we set it to ask a running app to exit
REG_PATH         = r'Software\WhisperVox'     # HKCU; the app writes 'Version' here
READY_TIMEOUT_S  = 35    # give up waiting for the app after this long

# Uninstall integration (all per-user / HKCU, no admin). Apps & Features reads the
# Uninstall key; the others mirror what the app/installer create so uninstall can
# remove every trace. Keep RUN_* in sync with src/system_integration.py.
UNINSTALL_KEY    = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\WhisperVox'
RUN_KEY          = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_VALUE        = 'WhisperVox'
LINGER_S         = 1.0   # keep splash visible briefly after the app is ready
QUIT_WAIT_S      = 10    # how long to wait for an old version to release the mutex
_EVENT_MODIFY_STATE = 0x0002
_SYNCHRONIZE      = 0x00100000
_WAIT_OBJECT_0    = 0x00000000

# Per-user install location (no admin, like VS Code / Slack).
_local = os.environ.get('LOCALAPPDATA') or os.path.expanduser(r'~\AppData\Local')
INSTALL_DIR   = os.path.join(_local, 'Programs', 'WhisperVox')
MAIN_EXE      = os.path.join(INSTALL_DIR, 'WhisperVox.exe')
VERSION_FILE  = os.path.join(INSTALL_DIR, '.version')
UNINSTALL_EXE = os.path.join(INSTALL_DIR, 'uninstall.exe')   # a copy of this setup

# Personal data + shortcuts the uninstall must also clear.
_appdata     = os.environ.get('APPDATA', '')
CONFIG_DIR   = os.path.join(_appdata, 'WhisperVox')           # config.yaml, .bak, log
START_MENU_LNK = os.path.join(
    _appdata, r'Microsoft\Windows\Start Menu\Programs', 'Whisper Vox.lnk')

_CREATE_NO_WINDOW = 0x08000000

# -- Win32 constants for the native splash ------------------------------------
_WS_OVERLAPPED    = 0x00000000
_WS_CAPTION       = 0x00C00000
_WS_VISIBLE       = 0x10000000
_WS_CHILD         = 0x40000000
_WS_CLIPSIBLINGS  = 0x04000000
_WS_EX_TOPMOST    = 0x00000008
_WS_EX_DLGMODALFRAME = 0x00000001
_SS_CENTER        = 0x01
_PBS_MARQUEE      = 0x08
_PBM_SETMARQUEE   = 0x0400 + 10   # WM_USER + 10
_WM_DESTROY       = 0x0002
_CS_HREDRAW       = 0x0002
_CS_VREDRAW       = 0x0001
_IDC_ARROW        = 32512
_COLOR_BTNFACE    = 15
_SW_SHOW          = 5
_PM_REMOVE        = 0x0001

# Proper 64-bit signatures - without these, ctypes truncates pointer-sized
# wparam/lparam to 32 bits and window creation fails (WM_NCCREATE returns 0).
_LRESULT = ctypes.c_ssize_t
_user32 = ctypes.windll.user32
_user32.DefWindowProcW.argtypes = (wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
_user32.DefWindowProcW.restype  = _LRESULT
_user32.CreateWindowExW.argtypes = (
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
)
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.SendMessageW.argtypes = (wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
_user32.SendMessageW.restype  = _LRESULT

_WM_SETFONT       = 0x0030
_DEFAULT_CHARSET  = 1
_CLEARTYPE_QUALITY = 5
_gdi32 = ctypes.windll.gdi32
_gdi32.CreateFontW.argtypes = (ctypes.c_int,) * 13 + (wintypes.LPCWSTR,)
_gdi32.CreateFontW.restype  = ctypes.c_void_p
_gdi32.DeleteObject.argtypes = (ctypes.c_void_p,)
_gdi32.DeleteObject.restype  = wintypes.BOOL


def _make_font(point_size, weight=400):
    h = -round(point_size * 96 / 72)
    return _gdi32.CreateFontW(h, 0, 0, 0, weight, 0, 0, 0,
                              _DEFAULT_CHARSET, 0, 0, _CLEARTYPE_QUALITY, 0, 'Segoe UI')


def _dbg(msg):
    """Diagnostics: set WV_SETUP_DEBUG=1 to log next to the setup exe."""
    if not os.environ.get('WV_SETUP_DEBUG'):
        return
    try:
        log = os.path.join(os.path.dirname(os.path.abspath(
            sys.executable if getattr(sys, 'frozen', False) else __file__)), 'setup-debug.log')
        with open(log, 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%H:%M:%S")} {msg}\n')
    except Exception:
        pass


def _installed_version():
    try:
        with open(VERSION_FILE, 'r') as f:
            return f.read().strip()
    except Exception:
        return None


def _needs_work():
    """True if we must install (no exe) or update (version differs)."""
    return not os.path.isfile(MAIN_EXE) or _installed_version() != APP_VERSION


def _is_fresh_install():
    return not os.path.isfile(MAIN_EXE)


def _app_already_running():
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenMutexW(_SYNCHRONIZE, False, MUTEX_NAME)
    if h:
        kernel32.CloseHandle(h)
        return True
    return False


def _signal_quit_and_wait():
    """Tell a running version to exit, then wait for it to release the mutex so
    we can safely re-extract over its files."""
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenEventW(_EVENT_MODIFY_STATE, False, QUIT_EVENT_NAME)
    if not h:
        h = kernel32.CreateEventW(None, True, False, QUIT_EVENT_NAME)
    if h:
        kernel32.SetEvent(h)
        kernel32.CloseHandle(h)
    deadline = time.time() + QUIT_WAIT_S
    while time.time() < deadline:
        if not _app_already_running():
            return True
        time.sleep(0.1)
    return not _app_already_running()


def _read_activation_key():
    """Crude config.yaml parse - avoids bundling PyYAML into the setup."""
    try:
        path = os.path.join(os.environ.get('APPDATA', ''), 'WhisperVox', 'config.yaml')
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip().startswith('activation_key:'):
                    val = line.split(':', 1)[1].strip().strip('\'"')
                    if val:
                        return val.upper()
    except Exception:
        pass
    return 'F2'


class _MSG(ctypes.Structure):
    _fields_ = [
        ('hwnd',    wintypes.HWND),
        ('message', ctypes.c_uint),
        ('wParam',  wintypes.WPARAM),
        ('lParam',  wintypes.LPARAM),
        ('time',    ctypes.c_uint),
        ('pt',      ctypes.c_long * 2),
    ]


class Splash:
    """Native Win32 splash: status line, activation key, version, marquee bar.
    Shown ONLY while installing/updating - never on a normal launch."""

    W, H = 380, 158

    def __init__(self, status_text):
        user32   = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        comctl32 = ctypes.windll.comctl32
        self._user32 = user32

        class _INITCOMMONCONTROLSEX(ctypes.Structure):
            _fields_ = [('dwSize', ctypes.c_ulong), ('dwICC', ctypes.c_ulong)]
        icc = _INITCOMMONCONTROLSEX(ctypes.sizeof(_INITCOMMONCONTROLSEX), 0x20)  # ICC_PROGRESS_CLASS
        comctl32.InitCommonControlsEx(ctypes.byref(icc))

        _WNDPROCTYPE = ctypes.WINFUNCTYPE(
            _LRESULT, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM
        )

        def _wnd_proc(hwnd, msg, wparam, lparam):
            if msg == _WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wnd_proc_cb = _WNDPROCTYPE(_wnd_proc)  # keep a ref - GC would crash the wndproc

        class _WNDCLASSEX(ctypes.Structure):
            _fields_ = [
                ('cbSize',        ctypes.c_uint),
                ('style',         ctypes.c_uint),
                ('lpfnWndProc',   _WNDPROCTYPE),
                ('cbClsExtra',    ctypes.c_int),
                ('cbWndExtra',    ctypes.c_int),
                ('hInstance',     wintypes.HANDLE),
                ('hIcon',         wintypes.HANDLE),
                ('hCursor',       wintypes.HANDLE),
                ('hbrBackground', wintypes.HANDLE),
                ('lpszMenuName',  ctypes.c_wchar_p),
                ('lpszClassName', ctypes.c_wchar_p),
                ('hIconSm',       wintypes.HANDLE),
            ]

        self._hinstance = kernel32.GetModuleHandleW(None)
        self._class_name = 'WVSetupSplash'

        wc = _WNDCLASSEX()
        wc.cbSize        = ctypes.sizeof(_WNDCLASSEX)
        wc.style         = _CS_HREDRAW | _CS_VREDRAW
        wc.lpfnWndProc   = self._wnd_proc_cb
        wc.hInstance     = self._hinstance
        wc.hCursor       = user32.LoadCursorW(None, ctypes.cast(_IDC_ARROW, ctypes.c_wchar_p))
        wc.hbrBackground = ctypes.cast(_COLOR_BTNFACE + 1, wintypes.HANDLE)
        wc.lpszClassName = self._class_name
        kernel32.SetLastError(0)
        user32.RegisterClassExW(ctypes.byref(wc))

        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        x  = (sw - self.W) // 2
        y  = (sh - self.H) // 2

        self.hwnd = user32.CreateWindowExW(
            _WS_EX_TOPMOST | _WS_EX_DLGMODALFRAME,
            self._class_name, 'Whisper Vox',
            _WS_OVERLAPPED | _WS_CAPTION,
            x, y, self.W, self.H,
            None, None, self._hinstance, None,
        )

        def _static(text, y_pos, height):
            return user32.CreateWindowExW(
                0, 'STATIC', text,
                _WS_VISIBLE | _WS_CHILD | _SS_CENTER,
                10, y_pos, 355, height,
                self.hwnd, None, self._hinstance, None,
            )

        self._status = _static(status_text, 12, 24)
        key_lbl = _static(f'Activation key:  {_read_activation_key()}', 40, 20)
        ver_lbl = _static(f'v{APP_VERSION}', 62, 20)

        self._fonts = [_make_font(13, weight=600), _make_font(10)]
        user32.SendMessageW(self._status, _WM_SETFONT, self._fonts[0], 1)
        for ctrl in (key_lbl, ver_lbl):
            user32.SendMessageW(ctrl, _WM_SETFONT, self._fonts[1], 1)

        pb = user32.CreateWindowExW(
            0, 'msctls_progress32', None,
            _WS_VISIBLE | _WS_CHILD | _PBS_MARQUEE | _WS_CLIPSIBLINGS,
            10, 84, 355, 22,
            self.hwnd, None, self._hinstance, None,
        )
        user32.SendMessageW(pb, _PBM_SETMARQUEE, 1, 40)  # start, 40 ms interval

        user32.ShowWindow(self.hwnd, _SW_SHOW)
        user32.UpdateWindow(self.hwnd)
        user32.SetForegroundWindow(self.hwnd)
        user32.BringWindowToTop(self.hwnd)
        self.pump()

    def set_status(self, text):
        self._user32.SetWindowTextW(self._status, text)
        self.pump()

    def pump(self):
        msg = _MSG()
        while self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, _PM_REMOVE):
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

    def wait(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.pump()
            time.sleep(0.05)

    def close(self):
        self._user32.DestroyWindow(self.hwnd)
        self.pump()
        self._user32.UnregisterClassW(self._class_name, self._hinstance)
        for hf in getattr(self, '_fonts', []):
            _gdi32.DeleteObject(hf)


def _retry_rename(src, dst, attempts=10, delay=0.3):
    """Rename with retries - handles from a just-closed old version can linger
    briefly even after the mutex is released."""
    last = None
    for _ in range(attempts):
        try:
            os.rename(src, dst)
            return
        except OSError as e:
            last = e
            time.sleep(delay)
    raise last


def _install(splash):
    """Extract app.zip into a temp dir and SWAP it in (atomic-ish), so a partial
    extract can never corrupt a working install and the lock window is minimal."""
    zip_src = os.path.join(
        getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))),
        'app.zip',
    )
    new_dir = INSTALL_DIR + '.new'
    old_dir = INSTALL_DIR + '.old'

    done = threading.Event()
    error = [None]

    def _do_extract():
        try:
            os.makedirs(os.path.dirname(INSTALL_DIR), exist_ok=True)
            shutil.rmtree(new_dir, ignore_errors=True)
            shutil.rmtree(old_dir, ignore_errors=True)
            os.makedirs(new_dir, exist_ok=True)
            with zipfile.ZipFile(zip_src, 'r') as z:
                z.extractall(new_dir)
            if os.path.isdir(INSTALL_DIR):
                _retry_rename(INSTALL_DIR, old_dir)
            _retry_rename(new_dir, INSTALL_DIR)
            shutil.rmtree(old_dir, ignore_errors=True)
            with open(VERSION_FILE, 'w') as f:
                f.write(APP_VERSION)
        except Exception as e:
            error[0] = e
        finally:
            done.set()

    threading.Thread(target=_do_extract, daemon=True).start()
    while not done.is_set():
        splash.pump()
        time.sleep(0.05)

    if error[0]:
        raise error[0]


def _create_start_menu_shortcut():
    """Per-user Start-Menu shortcut pointing at the installed exe. The Desktop
    shortcut and autostart are the app's own job (Misc options)."""
    appdata = os.environ.get('APPDATA')
    if not appdata:
        return
    programs = os.path.join(appdata, r'Microsoft\Windows\Start Menu\Programs')
    lnk = os.path.join(programs, 'Whisper Vox.lnk').replace("'", "''")
    exe_ps = MAIN_EXE.replace("'", "''")
    wd_ps = INSTALL_DIR.replace("'", "''")
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{lnk}'); "
        f"$s.TargetPath = '{exe_ps}'; "
        f"$s.WorkingDirectory = '{wd_ps}'; "
        "$s.Description = 'Whisper Vox voice dictation'; "
        "$s.Save()"
    )
    try:
        subprocess.run(
            ['powershell', '-WindowStyle', 'Hidden', '-NoProfile', '-Command', ps],
            capture_output=True, timeout=15, creationflags=_CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def _dir_size_kb(path):
    """Total size of a folder in KB (for the Apps & Features 'Size' column)."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return max(1, total // 1024)


class _GUID(ctypes.Structure):
    _fields_ = [('Data1', ctypes.c_ulong), ('Data2', ctypes.c_ushort),
                ('Data3', ctypes.c_ushort), ('Data4', ctypes.c_ubyte * 8)]


def _desktop_dirs():
    """All plausible Desktop folders, so uninstall removes the shortcut wherever
    it was created. OneDrive's 'Known Folder Move' redirects the Desktop, so the
    .lnk may live under OneDrive, not %USERPROFILE%\\Desktop. We collect:
      1. FOLDERID_Desktop via SHGetKnownFolderPath (the modern, redirect-aware API
         the app's WScript 'Desktop' resolves to), and
      2. the legacy %USERPROFILE%\\Desktop, as a fallback."""
    dirs = []
    # 1. SHGetKnownFolderPath(FOLDERID_Desktop) — {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
    try:
        fid = _GUID(0xB4BFCC3A, 0xDB2C, 0x424C,
                    (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0 and out.value:
            dirs.append(out.value)
            ctypes.windll.ole32.CoTaskMemFree(out)
    except Exception:
        pass
    # 2. Legacy profile Desktop.
    try:
        legacy = os.path.join(os.path.expanduser('~'), 'Desktop')
        if legacy not in dirs:
            dirs.append(legacy)
    except Exception:
        pass
    return dirs


def _register_uninstall():
    """Drop a copy of this setup as uninstall.exe in the install dir and register
    the app in 'Apps & Features' (per-user, HKCU) so it can be removed the standard
    way: Settings > Apps > Whisper Vox > Uninstall. Idempotent; re-run on update to
    refresh the version and the uninstaller copy."""
    try:
        src = sys.executable if getattr(sys, 'frozen', False) else __file__
        if os.path.abspath(src) != os.path.abspath(UNINSTALL_EXE):
            shutil.copy2(src, UNINSTALL_EXE)
    except Exception:
        pass
    try:
        size_kb = _dir_size_kb(INSTALL_DIR)
    except Exception:
        size_kb = 0
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            winreg.SetValueEx(k, 'DisplayName',     0, winreg.REG_SZ, 'Whisper Vox')
            winreg.SetValueEx(k, 'DisplayVersion',  0, winreg.REG_SZ, APP_VERSION)
            winreg.SetValueEx(k, 'Publisher',       0, winreg.REG_SZ, 'Whisper Vox')
            winreg.SetValueEx(k, 'DisplayIcon',     0, winreg.REG_SZ, MAIN_EXE)
            winreg.SetValueEx(k, 'InstallLocation', 0, winreg.REG_SZ, INSTALL_DIR)
            winreg.SetValueEx(k, 'UninstallString', 0, winreg.REG_SZ,
                              f'"{UNINSTALL_EXE}" --uninstall')
            winreg.SetValueEx(k, 'QuietUninstallString', 0, winreg.REG_SZ,
                              f'"{UNINSTALL_EXE}" --uninstall')
            winreg.SetValueEx(k, 'NoModify', 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, 'NoRepair', 0, winreg.REG_DWORD, 1)
            if size_kb:
                winreg.SetValueEx(k, 'EstimatedSize', 0, winreg.REG_DWORD, size_kb)
    except Exception:
        pass


def _schedule_self_delete():
    """Remove the install folder after we exit. It holds the running uninstall.exe,
    so a detached cmd loops until that handle frees, then deletes the folder and
    finally itself. ping (not timeout) is used for the delay - it works with no
    console/stdin."""
    bat = os.path.join(tempfile.gettempdir(), 'wv_uninstall_cleanup.bat')
    content = (
        "@echo off\r\n"
        ":loop\r\n"
        f'rmdir /s /q "{INSTALL_DIR}" 2>nul\r\n'
        f'if exist "{UNINSTALL_EXE}" (ping -n 2 127.0.0.1 >nul & goto loop)\r\n'
        'del "%~f0"\r\n'
    )
    try:
        with open(bat, 'w', encoding='ascii') as f:
            f.write(content)
        subprocess.Popen(['cmd', '/c', bat], creationflags=_CREATE_NO_WINDOW)
    except Exception:
        pass


def _uninstall():
    """--uninstall: remove every trace - app files, shortcuts, autostart, registry,
    and (optionally) the personal settings. Run from Apps & Features."""
    user32 = ctypes.windll.user32
    MB_YESNO = 0x04; MB_YESNOCANCEL = 0x03
    MB_ICONQUESTION = 0x20; MB_ICONINFO = 0x40
    IDYES = 6; IDCANCEL = 2

    if user32.MessageBoxW(
            0, 'Remove Whisper Vox from your computer?',
            'Uninstall Whisper Vox', MB_YESNO | MB_ICONQUESTION) != IDYES:
        return
    keep = user32.MessageBoxW(
        0,
        'Keep your personal settings (API key and preferences)?\n\n'
        'Yes      -  keep them, in case you reinstall later\n'
        'No        -  delete everything\n'
        'Cancel  -  stop, do not uninstall',
        'Uninstall Whisper Vox', MB_YESNOCANCEL | MB_ICONQUESTION)
    if keep == IDCANCEL:
        return
    keep_settings = (keep == IDYES)

    # 1. Ask a running instance to exit so its files unlock.
    _signal_quit_and_wait()

    # 2. Autostart (HKCU Run value).
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except FileNotFoundError:
                pass
    except Exception:
        pass

    # 3. Shortcuts (Start Menu + Desktop, every plausible Desktop location).
    #    After removing each one, notify the shell (SHChangeNotify) so Explorer
    #    refreshes its view immediately. Without this, a OneDrive desktop icon that
    #    was still 'sync pending' can linger as a dead ("file not found") ghost.
    SHCNE_DELETE = 0x00000004
    SHCNF_PATHW  = 0x0005
    lnks = [START_MENU_LNK]
    lnks += [os.path.join(d, 'Whisper Vox.lnk') for d in _desktop_dirs()]
    for lnk in lnks:
        try:
            if lnk and os.path.isfile(lnk):
                os.remove(lnk)
                try:
                    ctypes.windll.shell32.SHChangeNotify(
                        SHCNE_DELETE, SHCNF_PATHW, ctypes.c_wchar_p(lnk), None)
                except Exception:
                    pass
        except Exception:
            pass

    # 4. Registry: the app's version key AND the Apps & Features entry.
    for key in (REG_PATH, UNINSTALL_KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass
        except Exception:
            pass

    # 5. Personal settings (config + log), unless the user chose to keep them.
    if not keep_settings:
        shutil.rmtree(CONFIG_DIR, ignore_errors=True)

    # 6. The install folder itself - deferred (it holds this running exe).
    _schedule_self_delete()

    user32.MessageBoxW(
        0, 'Whisper Vox has been removed.',
        'Uninstall Whisper Vox', MB_ICONINFO)


def _launch_app():
    # Flag the launch so the app suppresses ITS own startup splash - the setup
    # splash already covers this run.
    env = dict(os.environ)
    env['WHISPERVOX_FROM_INSTALLER'] = '1'
    return subprocess.Popen([MAIN_EXE], cwd=INSTALL_DIR, env=env)


def _launch_and_wait(splash):
    """Launch the freshly-installed app and keep the splash up until it signals
    ready (its tray is in place), then linger briefly so the user can read it."""
    kernel32 = ctypes.windll.kernel32
    ready = kernel32.CreateEventW(None, True, False, READY_EVENT_NAME)
    _launch_app()
    deadline = time.time() + READY_TIMEOUT_S
    while time.time() < deadline:
        splash.pump()
        if ready and kernel32.WaitForSingleObject(ready, 0) == _WAIT_OBJECT_0:
            splash.wait(LINGER_S)
            break
        time.sleep(0.05)
    if ready:
        kernel32.CloseHandle(ready)


def main():
    if '--uninstall' in sys.argv:
        _dbg('uninstall requested')
        _uninstall()
        return

    _dbg(f'main() frozen={getattr(sys, "frozen", False)} install_dir={INSTALL_DIR} '
         f'installed={_installed_version()} mine={APP_VERSION}')

    if not _needs_work():
        # Up to date. Everyday path: if it's already in the tray, nothing to do;
        # otherwise launch it SILENTLY - no splash on a normal/autostart boot.
        # Self-heal: register the uninstaller if an older install never did (cheap,
        # runs at most once - guarded on the uninstall.exe being present).
        if not os.path.isfile(UNINSTALL_EXE):
            _register_uninstall()
        if not _app_already_running():
            _dbg('up to date - launching silently')
            _launch_app()
        else:
            _dbg('up to date and already running - nothing to do')
        return

    fresh = _is_fresh_install()

    # Updating over a running version: ask it to exit so we can swap files.
    if _app_already_running():
        _dbg('app running - signalling it to quit before update')
        if not _signal_quit_and_wait():
            ctypes.windll.user32.MessageBoxW(
                0,
                'Whisper Vox is still running and could not be closed '
                'automatically.\n\nPlease exit it from the tray (right-click the '
                'icon -> Quit), then run this update again.',
                'Whisper Vox Update', 0x30)
            return

    splash = Splash(
        'Installing Whisper Vox...  (first run, ~15 sec)' if fresh
        else 'Updating Whisper Vox...')
    try:
        _install(splash)
        splash.set_status('Finishing up...' if not fresh else 'Preparing Whisper Vox...')

        if not os.path.isfile(MAIN_EXE):
            splash.close()
            ctypes.windll.user32.MessageBoxW(
                0,
                f'Could not find:\n{MAIN_EXE}\n\nThe install folder may be '
                f'corrupted - delete it and run setup again.',
                'Whisper Vox Error', 0x10)
            sys.exit(1)

        _create_start_menu_shortcut()
        _register_uninstall()   # drop uninstall.exe + register in Apps & Features
        _launch_and_wait(splash)
    finally:
        splash.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        import traceback
        ctypes.windll.user32.MessageBoxW(
            0,
            f'Unexpected error:\n\n{e}\n\n{traceback.format_exc()[:600]}',
            'Whisper Vox Error', 0x10)
        sys.exit(1)
