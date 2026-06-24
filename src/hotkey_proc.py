# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Global-hotkey listener — runs in a SEPARATE PROCESS.

pynput installs global low-level Windows hooks (WH_KEYBOARD_LL). Those hooks
serialise input desktop-wide and require their owning process to pump messages
promptly. In the SAME process as pywebview's WebView2 (.NET/pythonnet) message
loop they fight: the app lags and hangs system-wide input. The old PyQt5 build
didn't hit this (Qt's loop isn't .NET). Isolating pynput in its own process —
with no WebView2/.NET — removes the conflict entirely.

Protocol: this process writes one event per line to stdout, flushed:
    ACT     activation chord pressed   (start / toggle recording)
    DEACT   activation chord released  (stop, in hold-to-record)
The parent (main.py) reads these and drives the recording flow.
"""
import os
import sys
import threading

_src = os.path.dirname(os.path.abspath(__file__))
if _src not in sys.path:
    sys.path.insert(0, _src)

from config_manager import ConfigManager
ConfigManager.initialize()

from key_listener import KeyListener


def _emit(tag):
    # Write straight to fd 1 (the pipe the parent gave us). A windowed PyInstaller
    # exe has sys.stdout == None, so os.write is the robust path in both source and
    # frozen builds. os.write is unbuffered, so no flush is needed.
    try:
        os.write(1, (tag + '\n').encode('utf-8'))
    except Exception:
        os._exit(0)   # parent gone / pipe closed -> exit quietly


def main():
    kl = KeyListener()
    kl.add_callback('on_activate', lambda: _emit('ACT'))
    kl.add_callback('on_deactivate', lambda: _emit('DEACT'))
    kl.start()
    threading.Event().wait()   # keep alive; parent terminates us on exit


if __name__ == '__main__':
    main()
