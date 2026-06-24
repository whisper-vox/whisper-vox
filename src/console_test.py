# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Phase 1 console harness — verifies the Qt-free backend end to end WITHOUT any UI.

It reproduces main.py's recording flow (hotkey -> record -> transcribe -> inject)
using the refactored ResultThread (threading.Thread + callbacks instead of QThread
+ signals). No PyQt5 anywhere — if any backend module still imported Qt, this
would fail to start in the new venv (which has no PyQt5 installed).

Config is shared with the shipping app at %APPDATA%\WhisperVox\config.yaml, so it
picks up the existing provider/API key/activation key.

Run:
    ..\.venv\Scripts\python.exe src\console_test.py

Then focus a text field (e.g. Notepad), hold your activation key (F2 by default),
speak, and release. The transcription is printed AND typed into the focused field.
Press Ctrl+C in this console to quit.
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
from input_simulation import InputSimulator
from result_thread import ResultThread, refresh_device_cache, default_input_name, list_input_devices


class ConsoleApp:
    def __init__(self):
        self.result_thread = None
        self.input_simulator = InputSimulator()
        self.key_listener = KeyListener()
        self.key_listener.add_callback('on_activate', self._on_activate)
        self.key_listener.add_callback('on_deactivate', self._on_deactivate)

    # ── status / level / result callbacks (run on the ResultThread) ───────────
    def _on_status(self, state):
        print(f'  [status] {state}')

    def _on_level(self, level):
        bars = int(level * 20)
        print('\r  [level] |' + '#' * bars + '-' * (20 - bars) + f'| {level:0.2f}',
              end='', flush=True)

    def _on_result(self, text):
        print()  # break the level line
        print(f'  [RESULT] {text!r}')
        if text:
            self.input_simulator.typewrite(text)
            print('  [inject] typed into the focused window.')

    # ── hotkey flow (mirrors main.py) ─────────────────────────────────────────
    def _on_activate(self):
        if self.result_thread and self.result_thread.is_alive():
            mode = ConfigManager.get('recording_mode', 'hold_to_record')
            if mode == 'press_to_toggle':
                self.result_thread.stop_recording()
            return
        self._start_recording()

    def _on_deactivate(self):
        mode = ConfigManager.get('recording_mode', 'hold_to_record')
        if mode == 'hold_to_record':
            if self.result_thread and self.result_thread.is_alive():
                self.result_thread.stop_recording()

    def _start_recording(self):
        if self.result_thread and self.result_thread.is_alive():
            return
        self.result_thread = ResultThread(
            on_status=self._on_status,
            on_result=self._on_result,
            on_level=self._on_level,
        )
        self.result_thread.start()

    def run(self):
        if not ConfigManager.get('api_key'):
            print('!! No API key in config — configure the shipping app first '
                  '(%APPDATA%\\WhisperVox\\config.yaml). Transcription will fail.')
        refresh_device_cache()
        print('=== Whisper Vox — Phase 1 backend harness (no UI, no Qt) ===')
        print(f'Default mic   : {default_input_name()}')
        print(f'Mics found    : {list_input_devices(refresh=False)}')
        print(f'Provider/model: {ConfigManager.get("provider")} / {ConfigManager.get("model")}')
        print(f'Activation key: {str(ConfigManager.get("activation_key", "f2")).upper()}')
        print(f'Recording mode: {ConfigManager.get("recording_mode")}')
        print()
        print('Focus a text field, hold the activation key, speak, release.')
        print('Ctrl+C to quit.\n')
        self.key_listener.start()
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            print('\nStopping...')
            self.key_listener.stop()


if __name__ == '__main__':
    ConsoleApp().run()
