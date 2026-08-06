# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Text injection into the focused window.

Three methods, selected by the 'input_method' config key:
- clipboard  - put text into the clipboard and send a paste shortcut.
               Layout-independent, instant for long text. (default)
- unicode    - per-character typing of real unicode codepoints, ignoring the
               keyboard layout (SendInput on Windows, CGEvent on macOS).
- keystrokes - legacy pynput per-character simulation. Maps characters through
               the CURRENT keyboard layout, so Cyrillic text typed while an
               English layout is active comes out as Latin gibberish. Kept for
               apps that reject synthetic unicode input.

The OS-specific half (clipboard access, the paste chord, unicode typing) lives
in the platform backend; what stays here is the method selection and the
clipboard save/restore dance, which is the same everywhere.
"""
import time

from pynput.keyboard import Controller

import platforms
from config_manager import ConfigManager

# Kept as module-level names because api.py and other callers import them.
get_clipboard_text = platforms.clipboard_get
set_clipboard_text = platforms.clipboard_set


class InputSimulator:
    def __init__(self):
        self._kb = Controller()  # used only by the legacy keystrokes method

    def typewrite(self, text):
        method = ConfigManager.get('input_method', 'clipboard')
        if method == 'clipboard':
            self._type_clipboard(text)
        elif method == 'unicode':
            platforms.type_unicode(text)
        else:
            self._type_keystrokes(text)

    # clipboard: set text -> paste shortcut -> optionally restore old content
    def _type_clipboard(self, text):
        restore = bool(ConfigManager.get('clipboard_restore', True))
        backup = platforms.clipboard_get() if restore else None

        if not platforms.clipboard_set(text):
            ConfigManager.console_print('Clipboard unavailable - falling back to unicode input.')
            platforms.type_unicode(text)
            return

        time.sleep(max(0, int(ConfigManager.get('paste_delay_ms', 100))) / 1000)
        platforms.send_paste(ConfigManager.get('paste_shortcut', 'ctrl+v'))

        if restore and backup is not None:
            # Give the target app time to read the clipboard before swapping back
            time.sleep(0.3)
            platforms.clipboard_set(backup)

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
