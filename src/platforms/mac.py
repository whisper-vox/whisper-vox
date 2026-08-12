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
    'single_instance', 'signal_show', 'start_show_listener', 'sync_run_on_startup',
    'center_xy', 'overlay_xy',
    'webview_gui', 'show_error', 'subprocess_flags',
    'finish_launch', 'bring_to_front',
    'tray_kwargs', 'tray_image', 'tray_start', 'tray_update_menu',
    'play_beep', 'open_path',
    'clipboard_get', 'clipboard_set', 'send_paste', 'type_unicode',
    'default_activation_key', 'default_paste_shortcut', 'preferred_hostapis',
    'permissions_status', 'request_permission', 'open_privacy_pane', 'ui_flags',
    'install_warning',
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


# ── single instance + "surface the window" ────────────────────────────────────
# Windows uses a named mutex and named events. The equivalents here are a lock
# file and a Unix socket, both in the config directory: one process holds an
# exclusive flock for as long as it lives (the kernel releases it even on a
# crash or a kill -9, so no stale-lock cleanup is needed), and it listens on the
# socket so a second launch can ask it to show its window and then exit.
#
# The lock file descriptor must NOT reach the hotkey subprocess, or the lock
# would outlive the app. Python marks descriptors non-inheritable by default
# (PEP 446), which is exactly what we need - do not "fix" that with pass_fds.

_LOCK_NAME = 'instance.lock'
_SOCK_NAME = 'instance.sock'
_lock_handle = None   # kept for the process lifetime; closing it drops the lock


def single_instance():
    global _lock_handle
    import fcntl
    try:
        handle = open(os.path.join(config_dir(), _LOCK_NAME), 'w')
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    except Exception:
        return True   # never let a lock problem stop the app from starting
    _lock_handle = handle
    try:
        handle.write(str(os.getpid()))
        handle.flush()
    except Exception:
        pass
    return True


def signal_show():
    """False when nothing is listening - the socket file outlives a crash, so
    its presence proves nothing and only a delivered message does."""
    import socket
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect(os.path.join(config_dir(), _SOCK_NAME))
        sock.sendall(b'SHOW')
        sock.close()
        return True
    except Exception:
        return False


def start_show_listener(on_show):
    import socket
    path = os.path.join(config_dir(), _SOCK_NAME)
    try:
        os.unlink(path)      # left behind by a previous run; the flock says we own it
    except FileNotFoundError:
        pass
    except Exception:
        return
    try:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(4)
    except Exception:
        return

    def _serve():
        while True:
            try:
                conn, _ = server.accept()
                with conn:
                    data = conn.recv(16)
            except Exception:
                return
            if data.strip() == b'SHOW':
                try:
                    on_show()
                except Exception:
                    pass

    threading.Thread(target=_serve, daemon=True).start()


# ── autostart ─────────────────────────────────────────────────────────────────

def _launch_agent_path():
    return os.path.join(os.path.expanduser('~'), 'Library', 'LaunchAgents',
                        f'{BUNDLE_ID}.plist')


def sync_run_on_startup():
    """Per-user autostart via a LaunchAgent, the macOS answer to the HKCU Run key.

    The plist is only WRITTEN, never bootstrapped: RunAtLoad would make launchd
    start a second copy the moment we load it, while this one is already running.
    Written now, honoured at the next login - which is what the option promises.
    Turning it off removes the plist and boots out anything a previous session
    left loaded.
    """
    import plistlib
    from config_manager import ConfigManager
    exe = sys.executable if getattr(sys, 'frozen', False) else None
    path = _launch_agent_path()
    if not ConfigManager.get('run_on_startup'):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except Exception:
            return
        _launchctl('bootout', f'gui/{os.getuid()}/{BUNDLE_ID}')
        return
    if not exe:
        return   # running from source: there is no app to launch at login
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            plistlib.dump({
                'Label': BUNDLE_ID,
                # --autostart marks the login launch so the app honours 'start
                # minimized' ONLY here; a manual click always shows the window.
                'ProgramArguments': [exe, '--autostart'],
                'RunAtLoad': True,
                'ProcessType': 'Interactive',
            }, f)
    except Exception:
        pass


def _launchctl(*args):
    try:
        subprocess.run(['launchctl', *args], capture_output=True, timeout=10)
    except Exception:
        pass


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


# ── app lifecycle ─────────────────────────────────────────────────────────────
# The app keeps its Dock icon. A menu-bar-only app was tidier on paper and much
# worse to live with: with no Dock icon and a small monochrome glyph among a row
# of others, a window closed by mistake was genuinely hard to get back. The Dock
# icon shows at a glance that Whisper Vox is running, right-click gives Quit,
# and clicking it brings the window back.
#
# What did have to be fixed is what those two do. pywebview's delegate answers
# applicationShouldTerminate_ by asking every window whether it may close, and
# ours deliberately says no so that closing the window hides it instead - so
# Quit was refused, and nothing handled a click on the Dock icon at all.
_delegate = None   # kept alive: NSApp does not retain its delegate


def finish_launch(on_quit=None, on_reopen=None):
    """Make Quit quit and a Dock click reopen the window."""
    def apply():
        global _delegate
        import AppKit
        app = AppKit.NSApplication.sharedApplication()
        if _delegate is None:
            class WhisperVoxDelegate(AppKit.NSObject):
                def applicationShouldTerminate_(self, sender):
                    # Quit from the Dock menu, Cmd+Q, log out: actually go.
                    # Closing the window still only hides it - different intent.
                    if on_quit:
                        on_quit()
                    return AppKit.NSTerminateNow

                def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, flag):
                    # Clicking the Dock icon brings the window back, which is
                    # what everyone expects it to do.
                    if on_reopen:
                        on_reopen()
                    return True

                def applicationSupportsSecureRestorableState_(self, sender):
                    return True

            _delegate = WhisperVoxDelegate.alloc().init()
        app.setDelegate_(_delegate)

    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(apply)
    except Exception:
        pass


def bring_to_front():
    """An accessory app has to ask for focus; otherwise the window is shown
    behind whatever the user is looking at."""
    def raise_app():
        try:
            import AppKit
            AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            pass
    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(raise_app)
    except Exception:
        pass


# ── tray ──────────────────────────────────────────────────────────────────────

def tray_kwargs():
    """Hand pystray the NSApplication that pywebview will run, so its status
    item lives in our loop instead of wanting one of its own."""
    try:
        import AppKit
        return {'darwin_nsapplication': AppKit.NSApplication.sharedApplication()}
    except Exception:
        return {}


def tray_image(fallback):
    """A menu-bar glyph, not the app logo.

    The logo is a detailed 256px square; squeezed into the 22 points a status
    item gets, it turns into an unreadable smudge that nobody picks out of a
    busy menu bar. macOS convention is a simple monochrome silhouette marked as
    a template image, which the system then draws black on a light menu bar and
    white on a dark one. So: draw a microphone.
    """
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return fallback
    size = 44                      # 2x of 22 points, for Retina
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    black = (0, 0, 0, 255)
    d.rounded_rectangle((16, 6, 28, 26), radius=6, fill=black)          # capsule
    d.arc((10, 14, 34, 34), start=0, end=180, fill=black, width=3)      # cradle
    d.line((22, 32, 22, 38), fill=black, width=3)                       # stem
    d.line((15, 38, 29, 38), fill=black, width=3)                       # base
    return img


def tray_start(icon):
    """No thread and no loop of our own: the Cocoa loop pywebview starts drives
    the status item. Must be called before webview.start()."""
    _keep_icon_as_template(icon)
    icon.run_detached()


def _keep_icon_as_template(icon):
    """Make every image pystray installs a template image.

    Setting the flag once does not hold: pystray builds the NSImage lazily in
    _assert_image, from a setup thread and again whenever the menu bar changes
    thickness, and each new image arrives untagged. Without the flag AppKit
    blits our pixels as they are - and a black glyph on a dark menu bar is the
    grey smudge this was meant to cure. Wrapping the method covers every future
    image as well as the first.
    """
    original = icon._assert_image

    def assert_image():
        original()
        try:
            image = icon._status_item.button().image()
            if image is not None and not image.isTemplate():
                image.setTemplate_(True)
        except Exception:
            pass

    icon._assert_image = assert_image


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
    """Ask the OS to show its own permission prompt.

    Fired on a worker thread and not waited on, so the answer arrives through
    permissions_status() polling instead. What actually gets the app listed
    under Input Monitoring is the hotkey process asking for its event tap over
    and over (see hotkey_proc.main) - this call only brings up the prompt.
    """
    def ask():
        try:
            if which == 'accessibility':
                import ApplicationServices
                import Quartz
                ApplicationServices.AXIsProcessTrustedWithOptions(
                    {Quartz.kAXTrustedCheckOptionPrompt: True})
            elif which == 'input_monitoring':
                import Quartz
                Quartz.CGRequestListenEventAccess()
            elif which == 'microphone':
                import AVFoundation
                AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    'soun', lambda granted: None)
        except Exception:
            pass

    # On a worker thread, never the main one. These calls can block until the
    # user answers, and blocking the main thread would freeze the window, the
    # menu bar item and every way out of the app at once.
    threading.Thread(target=ask, daemon=True).start()
    return True


def install_warning():
    """Why permissions will not stick, when they cannot.

    macOS ties a permission to the app's identity and location. An app run
    straight from a mounted .dmg lives on a read-only volume that disappears on
    eject, and Gatekeeper may additionally run it from a randomised, throwaway
    path (App Translocation). Grants made in that state apply to a copy that is
    already gone - which looks exactly like "I ticked the box and nothing
    happened". The only cure is to run it from /Applications, so say so.
    """
    if not getattr(sys, 'frozen', False):
        return ''
    path = sys.executable
    if '/AppTranslocation/' in path:
        return ('macOS is running Whisper Vox from a temporary copy, so it cannot keep '
                'any permission you grant. Quit it, drag Whisper Vox to your '
                'Applications folder, and open it from there.')
    if path.startswith('/Volumes/'):
        return ('Whisper Vox is running from the disk image. macOS will not remember '
                'permissions for an app on a mounted image. Quit it, drag Whisper Vox '
                'onto the Applications folder, eject the image, and open it from '
                'Applications.')
    return ''


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
        'minimized_label': 'Start Minimized to the Menu Bar',
        # There is no Dock icon to right-click, so offer the way out here too.
        'show_quit': True,
    }
