# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""The platform contract - every OS-specific thing the app needs, in one place.

The rest of the code never asks which OS it runs on; it calls `platforms.x()`
and the right backend answers. `win.py` and `mac.py` override what they can do
natively, and whatever a platform does not implement falls back to the harmless
default defined here (see `platforms/__init__.py` for how the two are stacked).

That fallback is deliberate. Several of these exist only because Windows ships
an in-place installer: the registry version handshake, the ready/quit events it
waits on, the Desktop shortcut. macOS has no equivalent - an app is a bundle you
drag - so those are no-ops there rather than `if sys.platform` scattered through
the callers.
"""
import os
import sys

__all__ = [
    'config_dir', 'single_instance', 'signal_show', 'start_show_listener',
    'signal_ready', 'start_quit_listener', 'write_app_version',
    'sync_desktop_shortcut', 'sync_run_on_startup',
    'center_xy', 'overlay_xy', 'tame_overlay', 'ensure_overlay_tamed',
    'webview_gui', 'runtime_ok', 'prepare_runtime', 'show_error',
    'subprocess_flags', 'hotkey_cmd',
    'finish_launch', 'bring_to_front',
    'tray_kwargs', 'tray_start', 'tray_update_menu',
    'play_beep', 'open_path', 'show_splash',
    'clipboard_get', 'clipboard_set', 'send_paste', 'type_unicode',
    'default_activation_key', 'default_paste_shortcut', 'preferred_hostapis',
    'permissions_status', 'request_permission', 'open_privacy_pane', 'ui_flags',
]


# ── storage ───────────────────────────────────────────────────────────────────

def config_dir():
    """Directory holding config.yaml and the optional log. Created on demand."""
    path = os.path.join(os.path.expanduser('~'), '.whispervox')
    os.makedirs(path, exist_ok=True)
    return path


# ── single instance + installer handshake ─────────────────────────────────────

def single_instance():
    """True if we are the first instance, False if one is already running."""
    return True


def signal_show():
    """Ask the running instance to surface its window.

    Returns True only if the request was actually delivered. A False means
    nobody answered, and the caller should start up rather than exit into
    silence - see main.run().
    """
    return False


def start_show_listener(on_show):
    """Watch for that request and call on_show() each time it arrives."""


def signal_ready():
    """Tell the installer's splash that our tray is up, so it can close."""


def start_quit_listener(on_quit):
    """A newer installer asks us to exit so it can swap in new files."""


def write_app_version():
    """Publish the running version where an installer can find it."""


def sync_desktop_shortcut():
    """Create or remove the Desktop shortcut per the 'desktop_icon' option."""


def sync_run_on_startup():
    """Register or unregister autostart per the 'run_on_startup' option."""


# ── window geometry ───────────────────────────────────────────────────────────

def center_xy(win_w, win_h):
    """(x, y) that centres a window, in pywebview's logical coordinate space."""
    try:
        import webview
        s = webview.screens[0]
        return (s.width - win_w) // 2, (s.height - win_h) // 2
    except Exception:
        return 100, 100


def overlay_xy(win_w, win_h):
    """(x, y) placing the status overlay at the bottom centre of the work area."""
    try:
        import webview
        s = webview.screens[0]
        return (s.width - win_w) // 2, s.height - win_h - 80
    except Exception:
        return 100, 100


def tame_overlay(window):
    """Keep the overlay out of the window list / taskbar, if the OS needs help.

    Called once on a background thread at startup; may sleep.
    """


def ensure_overlay_tamed(window):
    """Same, from the show path, in case the startup pass missed the window."""


# ── process + GUI plumbing ────────────────────────────────────────────────────

def webview_gui():
    """Value for webview.start(gui=...); None lets pywebview choose."""
    return None


def runtime_ok():
    """(ok, message) - whether the GUI runtime this backend needs is installed."""
    return True, ''


def prepare_runtime():
    """Last chance to set environment the GUI runtime reads at startup."""


def show_error(title, message):
    """Show a blocking error to a user who has no app window yet."""
    print(f'{title}: {message}', file=sys.stderr)


def subprocess_flags():
    """Extra creationflags for subprocess.Popen (hiding console windows)."""
    return 0


def hotkey_cmd(script_path):
    """Command that runs the global-hotkey listener in a SEPARATE process.

    Frozen builds re-invoke the app binary with --hotkey; from source we run
    hotkey_proc.py with the current interpreter.
    """
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--hotkey']
    return [sys.executable, script_path]


def finish_launch(on_quit=None, on_reopen=None):
    """Last-mile GUI setup once the toolkit's loop is running."""


def bring_to_front():
    """Raise the app above other windows when showing a window."""


# ── tray ──────────────────────────────────────────────────────────────────────

def tray_kwargs():
    """Backend-specific keyword arguments for the pystray Icon constructor."""
    return {}


def tray_start(icon):
    """Start the tray icon's event handling. Must not block the caller."""
    import threading
    threading.Thread(target=icon.run, daemon=True).start()


def tray_update_menu(icon):
    """Rebuild the tray menu (the 'Update available' item appears/disappears)."""
    try:
        icon.update_menu()
    except Exception:
        pass


# ── odds and ends ─────────────────────────────────────────────────────────────

def play_beep(path):
    """Play the completion sound, without blocking the caller."""


def open_path(path):
    """Open a file with whatever the OS considers its default application."""


def show_splash(text, activation_key, version):
    """Show the startup splash and return an object with .close(), or None."""
    return None


# ── text injection ────────────────────────────────────────────────────────────

def clipboard_get():
    """Current clipboard text, or None if empty / not text / unavailable."""
    return None


def clipboard_set(text):
    """Put text on the clipboard. True on success."""
    return False


def send_paste(shortcut):
    """Send the paste shortcut to the focused window."""


def type_unicode(text):
    """Type text as real unicode codepoints, ignoring the keyboard layout."""


# ── platform-shaped defaults and capabilities ─────────────────────────────────

def default_activation_key():
    """Activation key a fresh install starts with on this platform."""
    return 'f2'


def default_paste_shortcut():
    """Paste chord a fresh install starts with on this platform."""
    return 'ctrl+v'


def preferred_hostapis():
    """PortAudio host APIs to enumerate through, best first. () = no preference."""
    return ()


def permissions_status():
    """OS permissions the app needs: {key: True/False/None}. None = not applicable."""
    return {}


def request_permission(which):
    """Trigger the OS's own permission prompt, where one exists. True if granted."""
    return False


def open_privacy_pane(which):
    """Open the OS privacy settings for `which` permission. True if opened."""
    return False


def install_warning():
    """Message explaining why the app cannot work from where it is running,
    or '' when there is nothing wrong with the location."""
    return ''


def ui_flags():
    """Platform facts the Settings page needs to render itself correctly."""
    return {
        'platform': sys.platform,
        'os_name': 'this system',
        'paste_shortcuts': [('ctrl+v', 'Ctrl+V')],
        'hidden_options': [],
        'startup_label': 'Run on Startup',
    }
