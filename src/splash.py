# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Optional app-side startup splash (native Win32, ASCII-only).

The everyday (already-installed) launch has nothing on screen while WebView2
initialises. This shows a small "Preparing Whisper Vox..." window with a marquee
bar so the user sees something immediately. It is OFF by default (Misc toggle);
the installer has its own splash, so the app suppresses this one when launched by
the installer.

Runs on its OWN thread with its OWN message pump, fully independent of the
WebView2 (.NET) loop on the main thread. close() is called from any thread once
the Settings page has loaded; a max-lifetime guard closes it even if that never
fires.
"""
import ctypes
import ctypes.wintypes as wintypes
import threading
import time

_WS_OVERLAPPED    = 0x00000000
_WS_CAPTION       = 0x00C00000
_WS_VISIBLE       = 0x10000000
_WS_CHILD         = 0x40000000
_WS_CLIPSIBLINGS  = 0x04000000
_WS_EX_TOPMOST    = 0x00000008
_WS_EX_DLGMODALFRAME = 0x00000001
_SS_CENTER        = 0x01
_PBS_MARQUEE      = 0x08
_PBM_SETMARQUEE   = 0x0400 + 10
_WM_DESTROY            = 0x0002
_WM_DPICHANGED         = 0x02E0   # sent when DPI changes (WebView2 triggers this)
_WM_WINDOWPOSCHANGING  = 0x0046   # sent before ANY size/position change
_WM_SETFONT            = 0x0030
_SWP_NOSIZE            = 0x0001
_SWP_NOMOVE            = 0x0002
_CS_HREDRAW       = 0x0002
_CS_VREDRAW       = 0x0001
_IDC_ARROW        = 32512
_COLOR_BTNFACE    = 15
_SW_SHOW          = 5
_PM_REMOVE        = 0x0001
_DEFAULT_CHARSET  = 1
_CLEARTYPE_QUALITY = 5

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

_gdi32 = ctypes.windll.gdi32
_gdi32.CreateFontW.argtypes = (ctypes.c_int,) * 13 + (wintypes.LPCWSTR,)
_gdi32.CreateFontW.restype  = ctypes.c_void_p
_gdi32.DeleteObject.argtypes = (ctypes.c_void_p,)
_gdi32.DeleteObject.restype  = wintypes.BOOL


class _WINDOWPOS(ctypes.Structure):
    _fields_ = [
        ('hwnd', wintypes.HWND), ('hwndInsertAfter', wintypes.HWND),
        ('x', ctypes.c_int), ('y', ctypes.c_int),
        ('cx', ctypes.c_int), ('cy', ctypes.c_int),
        ('flags', ctypes.c_uint),
    ]


def _make_font(point_size, weight=400):
    h = -round(point_size * 96 / 72)
    return _gdi32.CreateFontW(h, 0, 0, 0, weight, 0, 0, 0,
                              _DEFAULT_CHARSET, 0, 0, _CLEARTYPE_QUALITY, 0, 'Segoe UI')


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
    """Threaded native splash. Construct to show; call close() to dismiss."""

    W, H = 380, 158
    _MAX_LIFETIME_S = 40   # safety: never linger past this even if close() is missed
    _MIN_VISIBLE_S  = 1.0  # always stay visible at least this long once shown

    def __init__(self, status_text, activation_key='F2', version='', max_lifetime_s=None):
        self._status_text = status_text
        self._key = activation_key
        self._version = version
        self._stop = threading.Event()
        self._ready = threading.Event()   # set once ShowWindow has been called
        self._show_time = None
        if max_lifetime_s:
            self._MAX_LIFETIME_S = max_lifetime_s
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def close(self):
        """Request the splash to close. It will not disappear before _MIN_VISIBLE_S."""
        self._stop.set()

    def wait_ready(self, timeout=2.0):
        """Block until the Win32 window is visible (or timeout expires)."""
        self._ready.wait(timeout)

    # ── runs entirely on its own thread (Win32 windows have thread affinity) ──
    def _run(self):
        try:
            self._build()
            self._show_time = time.time()
            self._ready.set()
        except Exception:
            self._ready.set()   # unblock wait_ready even on failure
            return
        deadline = self._show_time + self._MAX_LIFETIME_S
        while time.time() < deadline:
            if self._stop.is_set():
                # Honour minimum visible time before closing
                if time.time() - self._show_time >= self._MIN_VISIBLE_S:
                    break
            self._pump()
            time.sleep(0.03)
        try:
            self._destroy()
        except Exception:
            pass

    def _build(self):
        user32 = _user32
        kernel32 = ctypes.windll.kernel32
        comctl32 = ctypes.windll.comctl32

        # Set per-monitor DPI awareness on this thread so the splash is in the
        # same DPI context as WebView2.  Without this the OS may send DPI-change
        # notifications that move/resize the window when WebView2 initialises.
        try:
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4 (pointer-sized handle)
            _set_dpi = user32.SetThreadDpiAwarenessContext
            _set_dpi.restype = ctypes.c_ssize_t
            _set_dpi.argtypes = (ctypes.c_ssize_t,)
            _set_dpi(ctypes.c_ssize_t(-4))
        except Exception:
            pass

        class _INITCOMMONCONTROLSEX(ctypes.Structure):
            _fields_ = [('dwSize', ctypes.c_ulong), ('dwICC', ctypes.c_ulong)]
        icc = _INITCOMMONCONTROLSEX(ctypes.sizeof(_INITCOMMONCONTROLSEX), 0x20)  # ICC_PROGRESS_CLASS
        comctl32.InitCommonControlsEx(ctypes.byref(icc))

        _WNDPROCTYPE = ctypes.WINFUNCTYPE(
            _LRESULT, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)

        # After initial ShowWindow this becomes True and we freeze any further
        # position/size changes (DPI events, focus changes, WebView2 side-effects).
        _placed = [False]

        def _wnd_proc(hwnd, msg, wparam, lparam):
            if msg == _WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            if msg == _WM_DPICHANGED:
                return 0
            if msg == _WM_WINDOWPOSCHANGING and _placed[0]:
                # Freeze position and size — prevent ANY external repositioning
                # (DPI change, SetForegroundWindow, WebView2 init side-effects …)
                wp = ctypes.cast(ctypes.c_void_p(lparam),
                                 ctypes.POINTER(_WINDOWPOS)).contents
                wp.flags |= _SWP_NOSIZE | _SWP_NOMOVE
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wnd_proc_cb = _WNDPROCTYPE(_wnd_proc)  # keep a ref - GC would crash the wndproc
        self._placed_flag = _placed   # keep closure alive

        class _WNDCLASSEX(ctypes.Structure):
            _fields_ = [
                ('cbSize', ctypes.c_uint), ('style', ctypes.c_uint),
                ('lpfnWndProc', _WNDPROCTYPE), ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int), ('hInstance', wintypes.HANDLE),
                ('hIcon', wintypes.HANDLE), ('hCursor', wintypes.HANDLE),
                ('hbrBackground', wintypes.HANDLE), ('lpszMenuName', ctypes.c_wchar_p),
                ('lpszClassName', ctypes.c_wchar_p), ('hIconSm', wintypes.HANDLE),
            ]

        self._hinstance = kernel32.GetModuleHandleW(None)
        self._class_name = 'WVAppSplash'
        wc = _WNDCLASSEX()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEX)
        wc.style = _CS_HREDRAW | _CS_VREDRAW
        wc.lpfnWndProc = self._wnd_proc_cb
        wc.hInstance = self._hinstance
        wc.hCursor = user32.LoadCursorW(None, ctypes.cast(_IDC_ARROW, ctypes.c_wchar_p))
        wc.hbrBackground = ctypes.cast(_COLOR_BTNFACE + 1, wintypes.HANDLE)
        wc.lpszClassName = self._class_name
        user32.RegisterClassExW(ctypes.byref(wc))

        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        x = (sw - self.W) // 2
        y = (sh - self.H) // 2
        self.hwnd = user32.CreateWindowExW(
            _WS_EX_TOPMOST | _WS_EX_DLGMODALFRAME,
            self._class_name, 'Whisper Vox',
            _WS_OVERLAPPED | _WS_CAPTION,
            x, y, self.W, self.H, None, None, self._hinstance, None)

        def _static(text, y_pos, height):
            return user32.CreateWindowExW(
                0, 'STATIC', text, _WS_VISIBLE | _WS_CHILD | _SS_CENTER,
                10, y_pos, 355, height, self.hwnd, None, self._hinstance, None)

        status = _static(self._status_text, 12, 24)
        key_lbl = _static(f'Activation key:  {self._key}', 40, 20)
        ver_lbl = _static(f'v{self._version}' if self._version else '', 62, 20)

        self._fonts = [_make_font(13, weight=600), _make_font(10)]
        user32.SendMessageW(status, _WM_SETFONT, self._fonts[0], 1)
        for ctrl in (key_lbl, ver_lbl):
            user32.SendMessageW(ctrl, _WM_SETFONT, self._fonts[1], 1)

        pb = user32.CreateWindowExW(
            0, 'msctls_progress32', None,
            _WS_VISIBLE | _WS_CHILD | _PBS_MARQUEE | _WS_CLIPSIBLINGS,
            10, 84, 355, 22, self.hwnd, None, self._hinstance, None)
        user32.SendMessageW(pb, _PBM_SETMARQUEE, 1, 40)

        user32.ShowWindow(self.hwnd, _SW_SHOW)
        user32.UpdateWindow(self.hwnd)
        user32.SetForegroundWindow(self.hwnd)
        user32.BringWindowToTop(self.hwnd)
        _placed[0] = True   # freeze position/size from this point on

    def _pump(self):
        msg = _MSG()
        while _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, _PM_REMOVE):
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def _destroy(self):
        _user32.DestroyWindow(self.hwnd)
        self._pump()
        _user32.UnregisterClassW(self._class_name, self._hinstance)
        for hf in getattr(self, '_fonts', []):
            _gdi32.DeleteObject(hf)
