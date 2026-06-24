# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sys
import yaml
from datetime import datetime

DEFAULTS = {
    'provider': 'groq',
    'api_url': 'https://api.groq.com/openai/v1',
    'api_key': '',          # key of the ACTIVE provider (what transcription uses)
    'api_key_groq': '',     # per-provider storage (each provider keeps its own key)
    'api_key_openai': '',
    'api_key_manual': '',   # blank "Manual Settings" profile (user-supplied endpoint)
    'api_url_manual': '',   # manual profile remembers its own API URL too
    'model': 'whisper-large-v3',
    'language': '',         # '' = Auto-detect (Whisper detects the spoken language)
    'activation_key': 'f2',
    'initial_prompt': (
        'Verbatim dictation. Transcribe exactly what is spoken, in the original '
        'language and its native script. Do not translate. Do not transliterate. '
        'Keep English words, names, brands, products, acronyms and technical terms '
        'in Latin script as spoken.'
    ),
    'recording_mode': 'hold_to_record',
    'silence_duration': 2000,   # Continuous: ms of silence before auto-stop
    'min_duration': 250,        # discard recordings shorter than this (stray taps)
    'add_trailing_space': True,
    'input_method': 'clipboard',   # clipboard | unicode | keystrokes
    'paste_shortcut': 'ctrl+v',    # ctrl+v | shift+insert
    'clipboard_restore': False,
    'paste_delay_ms': 100,
    'writing_key_press_delay': 0.005,
    'remove_trailing_period': False,
    'remove_capitalization': False,
    'sound_device': None,
    'hide_status_window': False,
    'noise_on_completion': False,
    'desktop_icon': True,   # shortcut targets the extracted exe (daily entry point)
    'run_on_startup': True,   # autostart with Windows by default (HKCU Run key)
    'donated_hidden': False,  # user clicked "I've donated" -> hide the donation reminder
    'start_minimized': True,  # boot autostart goes straight to tray. ONLY the
                              # --autostart (Windows-boot) launch honours this; a
                              # manual icon click and the installer's first run
                              # always show the window regardless.
    'show_splash': False,     # show a startup splash on daily launch (off by default)
    'enable_logging': False,  # write system events + errors to a daily log file (off by default)
    # ── Updates ───────────────────────────────────────────────────────────────
    'auto_check_updates': True,        # check GitHub once a day for a newer version
    'last_update_check': 0.0,          # epoch seconds of the last check (time.time())
    'update_available_version': '',    # last known NEWER version ('' = none / up to date)
    'update_notified_version': '',     # version we already showed a tray balloon for
}


def _config_dir():
    appdata = os.environ.get('APPDATA', os.path.expanduser('~'))
    config_dir = os.path.join(appdata, 'WhisperVox')
    os.makedirs(config_dir, exist_ok=True)
    return config_dir


def _config_path():
    return os.path.join(_config_dir(), 'config.yaml')


def _log_path():
    return os.path.join(_config_dir(), 'whisper-vox.log')


class ConfigManager:
    _config: dict = {}
    _log_day = None     # date the log file currently holds (for daily rotation)

    @classmethod
    def initialize(cls):
        path = _config_path()
        cls._config = dict(DEFAULTS)
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    user = yaml.safe_load(f) or {}
                cls._config.update(user)
            except Exception:
                pass
        # Migration: old preset provider ids -> plain provider id.
        if cls._config.get('provider') in ('groq-v3', 'groq-turbo'):
            cls._config['provider'] = 'groq'
        cls._sync_active_key()

    @classmethod
    def _sync_active_key(cls):
        """Keep the active 'api_key' (the ONLY key transcription reads) and the
        active provider's stored slot consistent, in BOTH directions:
          (a) seed an empty slot from a legacy/standalone api_key (old configs);
          (b) restore an empty active api_key from the provider slot.
        This makes the stored key impossible to silently "lose": it can't vanish
        on startup, and — because save() runs this too — no write (not even a
        background save() from a stale second instance that still shares this
        file) can persist an empty active key while the slot still holds one.
        An intentional "clear the key" empties the slot as well, so a genuine
        clear is never blocked. Called from initialize() and before every save()."""
        prov = cls._config.get('provider')
        slot = 'api_key_' + (prov if prov in ('groq', 'openai', 'manual') else 'groq')
        if cls._config.get('api_key') and not cls._config.get(slot):
            cls._config[slot] = cls._config['api_key']
        elif cls._config.get(slot) and not cls._config.get('api_key'):
            cls._config['api_key'] = cls._config[slot]

    @classmethod
    def get(cls, key, default=None):
        return cls._config.get(key, DEFAULTS.get(key, default))

    @classmethod
    def set(cls, key, value):
        cls._config[key] = value

    @classmethod
    def save(cls):
        cls._sync_active_key()   # never write away a key the slot still holds
        with open(_config_path(), 'w', encoding='utf-8') as f:
            yaml.dump(cls._config, f, allow_unicode=True, default_flow_style=False)

    @classmethod
    def config_exists(cls):
        return os.path.isfile(_config_path()) and bool(cls._config.get('api_key'))

    @classmethod
    def log_file_path(cls):
        """Path of the (optional) daily log file."""
        return _log_path()

    @classmethod
    def _write_log(cls, line):
        """Append a line to the daily log, rotating (truncating) when the day
        changes so the file never holds more than one day of events."""
        try:
            path = _log_path()
            today = datetime.now().strftime('%Y-%m-%d')
            existed = os.path.isfile(path)
            mode = 'a'
            if cls._log_day != today:
                # First write this session, or a new day. Rotate only if the
                # existing file is from a PREVIOUS day (so same-day restarts keep
                # appending rather than wiping today's log).
                if existed:
                    file_day = datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d')
                    if file_day != today:
                        mode = 'w'
                cls._log_day = today
            fresh = (mode == 'w') or not existed  # write a header on a brand-new/rotated file
            with open(path, mode, encoding='utf-8') as f:
                if fresh:
                    f.write(f"=== Whisper Vox log - {today} ===\n")
                f.write(line + '\n')
        except Exception:
            pass

    @classmethod
    def console_print(cls, message, to_file=True):
        # Always to stdout (visible only when run from a console / dev). Also to
        # the daily log file when the user enabled logging - EXCEPT lines marked
        # to_file=False (e.g. transcription text, which we never log).
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        try:
            print(line, flush=True)
        except Exception:
            pass
        if to_file:
            try:
                if cls._config.get('enable_logging'):
                    cls._write_log(line)
            except Exception:
                pass
