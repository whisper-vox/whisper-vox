# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bridge exposed to the WebView JS as `window.pywebview.api.*`.

The page PULLS init data once (deferred, after load) and pushes user actions on
click. CRITICAL: the Api instance holds NO reference to App/windows — pywebview
introspects the js_api object and would recurse forever through the .NET window
graph (window.native.AccessibilityObject…), pegging the GUI ~20 s. The App
back-reference lives at MODULE level (set_app); the class has only bridge methods.
"""
import threading
import webbrowser

from config_manager import ConfigManager, DEFAULTS
from version import get_version
import settings_data as SD

_app = None   # module-level back-reference to main.App (never an instance attr)


def set_app(app):
    global _app
    _app = app


def _update_available():
    """Stored 'newer' version (if any) — from the last background check."""
    from updater import is_newer
    stored = str(ConfigManager.get('update_available_version') or '')
    return stored if (stored and is_newer(stored, get_version())) else ''


class Api:
    # ── init data (one pull, deferred after page load) ──────────────────────────
    def get_init_data(self):
        from result_thread import list_input_devices, default_input_name
        try:
            mics = list_input_devices(refresh=False)
            default_mic = default_input_name(refresh=False)
        except Exception:
            mics, default_mic = [], None
        return {
            'config': dict(ConfigManager._config),
            'defaults': dict(DEFAULTS),
            'version': get_version(),
            'mics': mics,
            'default_mic': default_mic,
            'languages': SD.LANGUAGES,
            'providers': SD.PROVIDERS,
            'provider_links': SD.PROVIDER_LINKS,
            'help': SD.HELP,
            'links': {'repo': SD.REPO_URL, 'releases': SD.RELEASES_URL, 'issues': SD.ISSUES_URL},
            'update_available': _update_available(),
        }

    def default_prompt_for(self, code):
        name = SD._LANG_CODE_TO_NAME.get(code) if code else None
        return SD.default_prompt(name)

    # ── save (write + apply live, no full restart) ──────────────────────────────
    def save_config(self, data):
        if not isinstance(data, dict):
            return {'ok': False, 'error': 'Bad data.'}
        # NOTE: saving WITHOUT an API key is allowed on purpose — the user may
        # configure everything else first, or Reset to defaults. Recording without
        # a key is already guarded (pre-flight) and the overlay explains it; there
        # is no reason to block Save here.

        # Coerce numeric fields, but ONLY those actually present in the payload
        # (a missing key would KeyError and abort the ENTIRE save).
        for k in ('writing_key_press_delay',):
            if k in data:
                try:
                    data[k] = float(data[k])
                except (ValueError, TypeError):
                    data[k] = ConfigManager.get(k)
        for k in ('silence_duration', 'min_duration', 'paste_delay_ms'):
            if k in data:
                try:
                    data[k] = int(data[k])
                except (ValueError, TypeError):
                    data[k] = ConfigManager.get(k)
        if 'activation_key' in data:
            data['activation_key'] = str(data['activation_key']).lower()

        for k, v in data.items():
            ConfigManager.set(k, v)
        ConfigManager.save()
        if _app:
            _app.apply_settings()
        return {'ok': True}

    # ── model refresh (live /v1/models) ─────────────────────────────────────────
    def refresh_models(self, url, key):
        if not str(key).strip():
            return {'ok': False, 'error': 'Enter your API key first, then refresh.'}
        try:
            from transcription import fetch_models
            models = fetch_models(url, key)
            return {'ok': True, 'models': models}
        except Exception as e:
            return {'ok': False, 'error': str(e)[:200]}

    # ── microphone rescan (reinit PortAudio) ────────────────────────────────────
    def rescan_mics(self):
        from result_thread import list_input_devices, default_input_name, refresh_device_cache
        try:
            default_mic = default_input_name(refresh=True)
            mics = list_input_devices(refresh=False)
            refresh_device_cache(reinit=False)
            return {'mics': mics, 'default_mic': default_mic}
        except Exception:
            return {'mics': [], 'default_mic': None}

    # ── immediate-apply toggles (independent of Save) ───────────────────────────
    def set_start_minimized(self, value):
        ConfigManager.set('start_minimized', bool(value))
        ConfigManager.save()
        return True

    def set_show_splash(self, value):
        ConfigManager.set('show_splash', bool(value))
        ConfigManager.save()
        return True

    def set_enable_logging(self, value):
        ConfigManager.set('enable_logging', bool(value))
        ConfigManager.save()
        return True

    def set_donated_hidden(self, value):
        ConfigManager.set('donated_hidden', bool(value))
        ConfigManager.save()
        return True

    # ── updates ─────────────────────────────────────────────────────────────────
    def check_update(self):
        from updater import check_latest, is_newer
        latest = check_latest()
        if latest is None:
            return {'ok': False}
        newer = latest if is_newer(latest, get_version()) else ''
        ConfigManager.set('update_available_version', newer)
        ConfigManager.save()
        if _app:
            _app.set_update_version(newer)   # refresh the tray 'Update available' item
        return {'ok': True, 'latest': newer, 'current': get_version()}

    def start_update(self):
        """Download the official setup and run it (clean takeover). Returns
        immediately; the window closes when the setup asks the app to quit."""
        if _app:
            _app.start_update()
        return True

    # ── misc actions ─────────────────────────────────────────────────────────---
    def open_log(self):
        path = ConfigManager.log_file_path()
        import os
        if os.path.isfile(path):
            os.startfile(path)
            return {'ok': True}
        return {'ok': False}

    def copy_repo_link(self):
        try:
            from input_simulation import set_clipboard_text
            set_clipboard_text(SD.REPO_URL)
            return True
        except Exception:
            return False

    def open_url(self, url):
        if isinstance(url, str) and url.startswith(('http://', 'https://')):
            webbrowser.open(url)
            return True
        return False

    def hide_settings(self):
        if _app:
            threading.Thread(target=_app.hide_settings, daemon=True).start()
        return True

    def stop_recording(self):
        if _app:
            _app.stop_current_recording()
        return True
