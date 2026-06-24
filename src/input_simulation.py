# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Text injection into the focused window.

Three methods, selected by the 'input_method' config key:
- clipboard  — put text into the clipboard and send a paste shortcut.
               Layout-independent, instant for long text. (default)
- unicode    — SendInput with KEYEVENTF_UNICODE: per-character typing of real
               unicode codepoints, ignores the keyboard layout.
- keystrokes — legacy pynput per-character simulation. Maps characters through
               the CURRENT keyboard layout, so Cyrillic text typed while an
               English layout is active comes out as Latin gibberish. Kept for
               apps that reject synthetic unicode input.
"""
import ctypes
import time
from ctypes import wintypes

from pynput.keyboard import Controller

from config_manager import ConfigManager

_user32   = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

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


# ── Clipboard helpers ─────────────────────────────────────────────────────────

def _open_clipboard(retries=10, delay=0.02):
    for _ in range(retries):
        if _user32.OpenClipboard(None):
            return True
        time.sleep(delay)  # another app may hold the clipboard briefly
    return False


def get_clipboard_text():
    """Current clipboard text, or None if empty/non-text/unavailable."""
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


def set_clipboard_text(text):
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
        # On success the system owns the handle — do not free it ourselves
        return bool(_user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        _user32.CloseClipboard()


# ── Input simulator ───────────────────────────────────────────────────────────

class InputSimulator:
    def __init__(self):
        self._kb = Controller()  # used only by the legacy keystrokes method

    def typewrite(self, text):
        method = ConfigManager.get('input_method', 'clipboard')
        if method == 'clipboard':
            self._type_clipboard(text)
        elif method == 'unicode':
            self._type_unicode(text)
        else:
            self._type_keystrokes(text)

    # clipboard: set text → paste shortcut → optionally restore old content
    def _type_clipboard(self, text):
        restore = bool(ConfigManager.get('clipboard_restore', True))
        backup = get_clipboard_text() if restore else None

        if not set_clipboard_text(text):
            ConfigManager.console_print('Clipboard unavailable — falling back to unicode input.')
            self._type_unicode(text)
            return

        time.sleep(max(0, int(ConfigManager.get('paste_delay_ms', 100))) / 1000)

        if ConfigManager.get('paste_shortcut', 'ctrl+v') == 'shift+insert':
            mod, key = VK_SHIFT, VK_INSERT
        else:
            mod, key = VK_CONTROL, VK_V
        _send_inputs([
            (mod, 0, 0),
            (key, 0, 0),
            (key, 0, KEYEVENTF_KEYUP),
            (mod, 0, KEYEVENTF_KEYUP),
        ])

        if restore and backup is not None:
            # Give the target app time to read the clipboard before swapping back
            time.sleep(0.3)
            set_clipboard_text(backup)

    # unicode: per-character SendInput, keyboard layout is irrelevant
    def _type_unicode(self, text):
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

    # keystrokes: legacy pynput simulation (depends on the active layout)
    def _type_keystrokes(self, text):
        delay = float(ConfigManager.get('writing_key_press_delay', 0.005) or 0)
        for ch in text:
            self._kb.press(ch)
            self._kb.release(ch)
            if delay:
                time.sleep(delay)

    def cleanup(self):
        pass
