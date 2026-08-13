# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Global-hotkey listener - runs in a SEPARATE PROCESS.

pynput installs global low-level keyboard hooks (WH_KEYBOARD_LL on Windows, a
CGEventTap on macOS). Those hooks serialise input system-wide and require their
owning process to pump messages promptly. In the SAME process as pywebview's
message loop they fight: the app lags and hangs input system-wide. The old PyQt5
build didn't hit this. Isolating pynput in its own process removes the conflict.

This is the Windows path. macOS used it too - and it worked, but only once the
user had added the app to Input Monitoring by hand, which is a permission an app
cannot ask for (see MACOS_PORT_JOURNAL.md 5.11). There the chord is registered
with the OS instead, through platforms.native_hotkey().

Protocol: one event per line to stdout, unbuffered:
    ACT     activation chord pressed   (start / toggle recording)
    DEACT   activation chord released  (stop, in hold-to-record)
    NOKEYS  the listener could not start
    LISTEN  the listener came up after a NOKEYS, so the app knows it healed
The parent (main.py) reads these and drives the recording flow.
"""
import os
import sys
import threading
import time

_src = os.path.dirname(os.path.abspath(__file__))
if _src not in sys.path:
    sys.path.insert(0, _src)

from config_manager import ConfigManager
ConfigManager.initialize()

from key_listener import KeyListener

RETRY_SECONDS = 3


def _emit(tag):
    # Write straight to fd 1 (the pipe the parent gave us). A windowed PyInstaller
    # exe has sys.stdout == None, so os.write is the robust path in both source and
    # frozen builds. os.write is unbuffered, so no flush is needed.
    try:
        os.write(1, (tag + '\n').encode('utf-8'))
    except Exception:
        os._exit(0)   # parent gone / pipe closed -> exit quietly


def _new_listener():
    kl = KeyListener()
    kl.add_callback('on_activate', lambda: _emit('ACT'))
    kl.add_callback('on_deactivate', lambda: _emit('DEACT'))
    return kl


def _is_listening(kl):
    """True only if the keyboard hook is really installed.

    A refused hook does NOT raise. pynput asks the OS for its hook, and when it
    is refused the call simply returns nothing - whereupon pynput marks itself
    ready and returns from its thread without a word. start() succeeds, wait()
    returns, and nothing at all is listening. The one honest signal is whether
    that thread is still alive.
    """
    listener = getattr(kl.active_backend, 'keyboard_listener', None)
    if listener is None:
        return False
    try:
        listener.wait()          # returns either way; ready is set on failure too
    except Exception:
        return False
    time.sleep(0.2)              # let a thread that is about to give up do so
    return listener.is_alive()


def main():
    """Keep trying to listen, and say so while we cannot.

    A refused hook used to leave this process sitting there believing it had a
    hotkey: the app ran on with no way to start dictation and said nothing about
    it. Now the failure is reported and retried, so the listener comes up by
    itself once whatever refused it stops refusing.
    """
    failed_before = False
    while True:
        kl = _new_listener()
        try:
            kl.start()
            listening = _is_listening(kl)
        except Exception as e:
            ConfigManager.console_print(
                f'Hotkey listener error: {type(e).__name__}: {e}')
            listening = False
        if listening:
            if failed_before:
                _emit('LISTEN')
                ConfigManager.console_print('Hotkey listener is up.')
            break
        if not failed_before:
            failed_before = True
            _emit('NOKEYS')
            ConfigManager.console_print(
                'Hotkey listener has no keyboard access yet - retrying.')
        try:
            kl.stop()            # a pynput listener is a thread: one use each
        except Exception:
            pass
        time.sleep(RETRY_SECONDS)

    threading.Event().wait()   # keep alive; parent terminates us on exit


if __name__ == '__main__':
    main()
