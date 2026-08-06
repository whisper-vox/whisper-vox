# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""macOS backend - Cocoa, WKWebView and the three permissions the app needs.

Notes that cost time to find out, kept here so they are not rediscovered:

  * The tray cannot use pystray's Icon.run(): that wants the main thread, and
    pywebview's Cocoa loop already owns it. pystray has run_detached() for
    exactly this, and its darwin backend accepts the NSApplication to attach to.
    The icon must therefore be built on the main thread BEFORE webview.start().
  * pywebview marshals show/hide/move/evaluate_js onto the main thread itself
    (AppHelper.callAfter plus a semaphore), so worker threads may call them -
    but they block until the main loop gets round to it, so never call them
    from the main thread and never while it is busy.
  * Anything that touches AppKit from a worker thread (rebuilding the tray menu)
    must go through AppHelper.callAfter.
  * The app needs THREE separate permissions: Microphone, Input Monitoring (to
    hear the hotkey) and Accessibility (to send the paste). Only the first can
    be declared in Info.plist; the other two are granted by the user by hand.

Nothing at module level may import config_manager or version - they import this
package back, and the cycle would break the import.
"""
import os
import subprocess
import sys
import threading

__all__ = [
    'config_dir',
    'center_xy', 'overlay_xy',
    'webview_gui', 'show_error', 'subprocess_flags',
    'tray_kwargs', 'tray_start', 'tray_update_menu',
    'play_beep', 'open_path',
    'clipboard_get', 'clipboard_set', 'send_paste', 'type_unicode',
    'default_activation_key', 'default_paste_shortcut', 'preferred_hostapis',
    'permissions_status', 'request_permission', 'open_privacy_pane', 'ui_flags',
]

BUNDLE_ID = 'com.pekelniboroshna.whispervox'

# Privacy panes we can deep-link to, by the key permissions_status() reports.
_PRIVACY_PANES = {
    'accessibility': 'Privacy_Accessibility',
    'input_monitoring': 'Privacy_ListenEvent',
    'microphone': 'Privacy_Microphone',
}


# ── storage ───────────────────────────────────────────────────────────────────

def config_dir():
    path = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support',
                        'WhisperVox')
    os.makedirs(path, exist_ok=True)
    return path


# ── window geometry ───────────────────────────────────────────────────────────
# pywebview's move(x, y) places the window's TOP-LEFT corner, measured from the
# top-left of its screen - the same convention as Windows, so callers do not
# care. Sizes are logical points and already account for Retina, so unlike
# Windows there is no DPI division. What does need care is the Dock and the menu
# bar: NSScreen.visibleFrame() excludes both, and it uses bottom-left origin.

def _screen_boxes():
    """(frame, visibleFrame) of the main screen, or None if AppKit is unusable."""
    try:
        import AppKit
        screens = AppKit.NSScreen.screens()
        if not screens:
            return None
        s = screens[0]
        return s.frame(), s.visibleFrame()
    except Exception:
        return None


def center_xy(win_w, win_h):
    boxes = _screen_boxes()
    if not boxes:
        return 100, 100
    frame, vis = boxes
    x = vis.origin.x - frame.origin.x + (vis.size.width - win_w) / 2
    top_y = vis.origin.y + (vis.size.height + win_h) / 2
    y = frame.origin.y + frame.size.height - top_y
    return int(x), int(max(0, y))


def overlay_xy(win_w, win_h):
    """Bottom centre of the usable area - just above the Dock, wherever it is."""
    boxes = _screen_boxes()
    if not boxes:
        return 100, 100
    frame, vis = boxes
    margin = 24
    x = vis.origin.x - frame.origin.x + (vis.size.width - win_w) / 2
    top_y = vis.origin.y + win_h + margin        # top edge of the overlay
    y = frame.origin.y + frame.size.height - top_y
    return int(x), int(max(0, y))


# ── process + GUI plumbing ────────────────────────────────────────────────────

def webview_gui():
    """None - pywebview picks its Cocoa/WKWebView backend."""
    return None


def show_error(title, message):
    """No window exists yet at this point, so borrow the system's own dialog."""
    try:
        script = (f'display alert {_as_applescript(title)} '
                  f'message {_as_applescript(message)} as critical')
        subprocess.run(['osascript', '-e', script], capture_output=True, timeout=120)
    except Exception:
        print(f'{title}: {message}', file=sys.stderr)


def _as_applescript(text):
    return '"' + str(text).replace('\\', '\\\\').replace('"', '\\"') + '"'


def subprocess_flags():
    return 0


# ── tray ──────────────────────────────────────────────────────────────────────

def tray_kwargs():
    """Hand pystray the NSApplication that pywebview will run, so its status
    item lives in our loop instead of wanting one of its own."""
    try:
        import AppKit
        return {'darwin_nsapplication': AppKit.NSApplication.sharedApplication()}
    except Exception:
        return {}


def tray_start(icon):
    """No thread and no loop of our own: the Cocoa loop pywebview starts drives
    the status item. Must be called before webview.start()."""
    icon.run_detached()


def tray_update_menu(icon):
    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(icon.update_menu)
    except Exception:
        try:
            icon.update_menu()
        except Exception:
            pass


# ── odds and ends ─────────────────────────────────────────────────────────────

_sounds = []   # NSSound is async; a garbage-collected sound stops mid-play


def play_beep(path):
    try:
        from AppKit import NSSound
        sound = NSSound.alloc().initWithContentsOfFile_byReference_(path, True)
        if sound:
            _sounds.append(sound)
            del _sounds[:-4]
            sound.play()
    except Exception:
        try:
            subprocess.Popen(['afplay', path])
        except Exception:
            pass


def open_path(path):
    subprocess.Popen(['open', path])


# ── text injection ────────────────────────────────────────────────────────────

def clipboard_get():
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString
        return NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString)
    except Exception:
        return None


def clipboard_set(text):
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        return bool(pb.setString_forType_(text, NSPasteboardTypeString))
    except Exception:
        return False


def send_paste(shortcut):
    """Cmd+V. macOS has no Shift+Insert convention, so the Windows alternative
    maps to Ctrl+V here - the shortcut a few X11-minded terminals still take."""
    from pynput.keyboard import Controller, Key
    kb = Controller()
    modifier = Key.ctrl if shortcut == 'ctrl+v' else Key.cmd
    with kb.pressed(modifier):
        kb.press('v')
        kb.release('v')


def type_unicode(text):
    """pynput's type() posts real unicode on macOS (CGEventKeyboardSetUnicodeString),
    so it is layout-independent just like the Windows SendInput path."""
    import time
    from pynput.keyboard import Controller
    from config_manager import ConfigManager
    delay = float(ConfigManager.get('writing_key_press_delay', 0.005) or 0)
    kb = Controller()
    for ch in text:
        kb.type(ch)
        if delay:
            time.sleep(delay)


# ── permissions (the part users actually trip over) ───────────────────────────

def permissions_status():
    """{'microphone', 'input_monitoring', 'accessibility'} -> True / False / None.

    None means "could not tell" - never report a permission as missing on a
    check that itself failed, or the onboarding would nag about nothing.
    """
    status = {'microphone': None, 'input_monitoring': None, 'accessibility': None}
    try:
        import ApplicationServices
        status['accessibility'] = bool(ApplicationServices.AXIsProcessTrusted())
    except Exception:
        pass
    try:
        import Quartz
        status['input_monitoring'] = bool(Quartz.CGPreflightListenEventAccess())
    except Exception:
        pass
    try:
        import AVFoundation
        # 3 = AVAuthorizationStatusAuthorized
        state = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_('soun')
        status['microphone'] = (state == 3)
    except Exception:
        pass
    return status


def request_permission(which):
    """Ask the OS to show its own permission prompt, where one exists.

    Accessibility and Input Monitoring can only be prompted for once per app;
    afterwards the user has to toggle them in System Settings, which is what
    open_privacy_pane() is for.
    """
    try:
        if which == 'accessibility':
            import ApplicationServices
            import Quartz
            opts = {Quartz.kAXTrustedCheckOptionPrompt: True}
            return bool(ApplicationServices.AXIsProcessTrustedWithOptions(opts))
        if which == 'input_monitoring':
            import Quartz
            return bool(Quartz.CGRequestListenEventAccess())
        if which == 'microphone':
            import AVFoundation
            done = threading.Event()
            result = {'granted': False}

            def handler(granted):
                result['granted'] = bool(granted)
                done.set()

            AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                'soun', handler)
            done.wait(timeout=60)
            return result['granted']
    except Exception:
        pass
    return False


def open_privacy_pane(which):
    pane = _PRIVACY_PANES.get(which)
    if not pane:
        return False
    try:
        subprocess.Popen(
            ['open', f'x-apple.systempreferences:com.apple.preference.security?{pane}'])
        return True
    except Exception:
        return False


# ── platform-shaped defaults and capabilities ─────────────────────────────────

def default_activation_key():
    """Right Option. The F-key row is media keys unless the user opted into
    'Use F1, F2, etc. as standard function keys', so F2 would do nothing on a
    stock Mac; a bare modifier is also comfortable to hold down."""
    return 'alt_right'


def default_paste_shortcut():
    return 'cmd+v'


def preferred_hostapis():
    """Core Audio is the only host API on macOS - nothing to prefer."""
    return ()


def ui_flags():
    return {
        'platform': 'darwin',
        'os_name': 'macOS',
        'paste_shortcuts': [('cmd+v', 'Cmd+V'), ('ctrl+v', 'Ctrl+V')],
        # No Desktop shortcuts on macOS (the app lives in /Applications), and the
        # splash is pointless when WKWebView starts this fast.
        'hidden_options': ['desktop_icon', 'show_splash'],
        'startup_label': 'Start at Login',
    }
