# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Windows system integration for Whisper Vox (Qt-free).

Bridges the running app to the installer/updater and to per-user OS integration:

  • Registry version  — publish our version to HKCU so the installer (dropped
    anywhere) can tell what's installed and whether it should take over.
  • Ready event       — set the named event the installer's splash waits on
    before it closes (so the splash only disappears once the tray is really up).
  • Quit event        — a newer installer asks the running version to exit so it
    can swap in new files; we poll it and quit cleanly.
  • Desktop shortcut   — create/remove a Desktop .lnk per the 'desktop_icon'
    option, targeting the installed exe (the daily entry point).
  • Run on startup     — register/unregister per-user autostart via the HKCU Run
    key (no admin), pointing DIRECTLY at the installed exe so a background boot
    launches the app silently — never the installer, never a splash.

All names here MUST match build/launcher.py.
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
import winreg

from config_manager import ConfigManager
from version import get_version

# ── Shared identifiers (keep in sync with build/launcher.py) ──────────────────
REG_PATH         = r'Software\WhisperVox'              # HKCU; we publish 'Version'
READY_EVENT_NAME = 'WhisperVoxApp_Ready_v1'            # set once our tray is up
QUIT_EVENT_NAME  = 'WhisperVoxApp_Quit_v1'             # a newer installer asks us to exit
SHOW_EVENT_NAME  = 'WhisperVoxApp_Show_v1'             # a 2nd launch asks us to surface
_RUN_KEY         = r'Software\Microsoft\Windows\CurrentVersion\Run'
_RUN_VALUE       = 'WhisperVox'
_WAIT_OBJECT_0   = 0x00000000
_EVENT_MODIFY_STATE = 0x0002
_CREATE_NO_WINDOW = 0x08000000


def _app_exe_path():
    """Path of the running (installed) exe; None when running from source."""
    return sys.executable if getattr(sys, 'frozen', False) else None


def write_registry_version():
    """Publish the running version to HKCU so an installer dropped anywhere can
    tell what's installed and decide whether to take over with an update."""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
            winreg.SetValueEx(key, 'Version', 0, winreg.REG_SZ, get_version())
    except Exception:
        pass


def signal_ready():
    """Set the named event the installer's splash waits on before closing."""
    try:
        kernel32 = ctypes.windll.kernel32
        h = kernel32.CreateEventW(None, True, False, READY_EVENT_NAME)
        if h:
            kernel32.SetEvent(h)
            kernel32.CloseHandle(h)
    except Exception:
        pass


def signal_show():
    """Ask an already-running instance to surface its window. Used when a second
    instance is launched (e.g. double-clicking the Desktop shortcut while the app
    is in the tray) — the second instance signals, then exits."""
    try:
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenEventW(_EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
        if not h:
            h = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
        if h:
            kernel32.SetEvent(h)
            kernel32.CloseHandle(h)
    except Exception:
        pass


def start_show_listener(on_show):
    """Watch the show-event (auto-reset, so it re-fires) and surface the window
    each time a second instance pings us."""
    def _poll():
        kernel32 = ctypes.windll.kernel32
        h = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)  # auto-reset
        if not h:
            return
        while True:
            if kernel32.WaitForSingleObject(h, 0) == _WAIT_OBJECT_0:
                try:
                    on_show()
                except Exception:
                    pass
            time.sleep(0.3)

    threading.Thread(target=_poll, daemon=True).start()


def start_quit_listener(on_quit):
    """A newer installer sets a named event to ask us to exit so it can swap in
    new files. Poll it on a background thread and call on_quit() when signalled."""
    def _poll():
        kernel32 = ctypes.windll.kernel32
        h = kernel32.CreateEventW(None, True, False, QUIT_EVENT_NAME)
        if not h:
            return
        while True:
            if kernel32.WaitForSingleObject(h, 0) == _WAIT_OBJECT_0:
                on_quit()
                return
            import time
            time.sleep(0.3)

    threading.Thread(target=_poll, daemon=True).start()


def sync_desktop_shortcut():
    """Create/remove the Desktop shortcut per the 'desktop_icon' option. Targets
    the installed exe (this process). Removal only touches a shortcut pointing at
    this exe — never a user's unrelated .lnk."""
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
    silently — never the installer."""
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
