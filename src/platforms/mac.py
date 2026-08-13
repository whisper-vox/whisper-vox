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
  * The app needs TWO permissions: Microphone (declared in Info.plist, prompted
    for normally) and Accessibility (to send the paste, granted by hand). It
    used to need Input Monitoring as well, for the hotkey; registering the
    chord with Carbon instead removed that - see the hotkey section below.

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
    'center_xy', 'overlay_xy', 'center_window', 'place_overlay',
    'show_overlay', 'hide_overlay',
    'webview_gui', 'show_error', 'subprocess_flags',
    'finish_launch', 'bring_to_front',
    'tray_kwargs', 'tray_image', 'tray_start', 'tray_update_menu',
    'play_beep', 'open_path',
    'clipboard_get', 'clipboard_set', 'send_paste', 'type_unicode',
    'type_keystrokes',
    'default_activation_key', 'default_paste_shortcut', 'preferred_hostapis',
    'native_hotkey', 'native_hotkey_stop', 'normalize_activation_key',
    'permissions_status', 'request_permission', 'open_privacy_pane',
    'reset_permissions', 'signing_note', 'permissions_report', 'ui_flags',
    'install_warning',
]

BUNDLE_ID = 'com.pekelniboroshna.whispervox'

# Privacy panes we can deep-link to, by the key permissions_status() reports.
_PRIVACY_PANES = {
    'accessibility': 'Privacy_Accessibility',
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
# Windows are placed through AppKit rather than pywebview's move(), which maps
# the coordinates onto whichever screen it considers the window's own:
#
#     flipped_y = self.screen.size.height - y
#     setFrameTopLeftPoint_(screen.origin.x + x, screen.origin.y + flipped_y)
#
# With a second display that is not the one we measured, the result lands
# somewhere else entirely. On a 1440x900 main screen with a 1920x1080 display
# above it, a perfectly reasonable centre of (290, 73) came out at (30, -1007) -
# a thousand points above the top of the main screen. The window was shown, and
# invisible, and every click on Settings threw it back there.
#
# Windows go to the primary display, inside its visibleFrame, which already
# excludes the menu bar and the Dock.


def _target_screen():
    """The display with the menu bar, always.

    Following the mouse instead sounds friendlier and is not: a window that
    lands on whichever display the pointer happened to be over is a window the
    user has to go looking for. screens()[0] is the primary display - the one
    carrying the menu bar and the Dock, and therefore the one the user is
    looking at when they click the app.
    """
    import AppKit
    return AppKit.NSScreen.screens()[0]


def _nswindow(window):
    import webview.platforms.cocoa as cocoa
    return cocoa.BrowserView.instances[window.uid].window


def _set_frame(window, x, y, win_w, win_h):
    def place():
        try:
            import AppKit
            _nswindow(window).setFrame_display_(
                AppKit.NSMakeRect(x, y, win_w, win_h), True)
        except Exception:
            pass
    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(place)
    except Exception:
        place()


def center_window(window, win_w, win_h):
    screen = _target_screen()
    vf = screen.visibleFrame()
    _set_frame(window,
               vf.origin.x + (vf.size.width - win_w) / 2,
               vf.origin.y + (vf.size.height - win_h) / 2,
               win_w, win_h)


def show_overlay(window):
    """Put the overlay on screen WITHOUT activating the app.

    pywebview's show() ends with activateIgnoringOtherApps_, which pulls the
    whole application to the front. The overlay appears the moment recording
    starts, so that quietly stole focus from whatever the user was typing into -
    and the paste a few seconds later had nowhere to land. focus=False was not
    enough on its own: it stops the WINDOW becoming key, not the APP becoming
    active. orderFrontRegardless shows the window and leaves the front app alone.
    """
    def order_in():
        try:
            _nswindow(window).orderFrontRegardless()
        except Exception:
            pass
    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(order_in)
    except Exception:
        order_in()


def hide_overlay(window):
    def order_out():
        try:
            _nswindow(window).orderOut_(None)
        except Exception:
            pass
    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(order_out)
    except Exception:
        order_out()


def place_overlay(window, win_w, win_h):
    screen = _target_screen()
    vf = screen.visibleFrame()
    _set_frame(window,
               vf.origin.x + (vf.size.width - win_w) / 2,
               vf.origin.y + 24,          # just above the Dock
               win_w, win_h)


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
        # Setting NSApp's delegate is not enough on its own. pywebview installs
        # its own delegate from BrowserView.__init__ - every time a window is
        # created - and the status overlay is created after this runs, so ours
        # was quietly replaced within a second of being set. That is why Quit
        # and reopen kept dying: pywebview's delegate answers terminate by
        # asking each window whether it may close, and ours says no by design.
        # It only ever builds that delegate when the shared one is None, so
        # handing it ours means every future window reinstalls ours.
        try:
            import webview.platforms.cocoa as cocoa
            cocoa.BrowserView._shared_app_delegate = _delegate
        except Exception:
            pass

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


# Virtual key codes (Carbon kVK_*). Fixed numbers, deliberately: looking a key
# up by character asks macOS which keyboard layout is current, and that is the
# call that used to kill the app - see the comment on _post_key below.
_VK_V = 9
_VK_COMMAND = 55
_VK_CONTROL = 59


def _event_source():
    import Quartz
    return Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)


def send_paste(shortcut):
    """Send the paste chord straight through Quartz.

    NOT through pynput. pynput's keyboard Controller resolves characters against
    the current keyboard layout, which goes into HIToolbox's Text Input Source
    APIs - and those may only be called on the main thread. This runs on the
    worker thread that just finished transcribing, so macOS killed the whole
    process with SIGILL (dispatch_assert_queue) every single time: the text was
    already on the clipboard, and the app died on the paste.

    Posting a key code with a modifier flag needs no layout lookup at all, so it
    is safe from any thread. Pasting into a window that has no text field does
    nothing, which is the right behaviour - the text stays on the clipboard.
    """
    import Quartz
    if shortcut == 'ctrl+v':
        flag = Quartz.kCGEventFlagMaskControl
    else:
        flag = Quartz.kCGEventFlagMaskCommand
    source = _event_source()
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(source, _VK_V, down)
        Quartz.CGEventSetFlags(event, flag)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def type_unicode(text):
    """Type real characters, layout-independent - the Windows SendInput UNICODE
    path, done the macOS way. Also thread-safe for the reason above: the
    characters ride along with the event instead of being looked up."""
    import time

    import Quartz
    from config_manager import ConfigManager
    delay = float(ConfigManager.get('writing_key_press_delay', 0.005) or 0)
    source = _event_source()
    for char in text:
        for down in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(source, 0, down)
            Quartz.CGEventKeyboardSetUnicodeString(event, len(char), char)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        if delay:
            time.sleep(delay)


def type_keystrokes(text):
    """The legacy per-key method. On macOS it is the same as type_unicode: the
    alternative would be asking for the current layout, which is exactly what
    must not happen off the main thread."""
    type_unicode(text)


# ── global hotkey (Carbon, and therefore free of permissions) ─────────────────
#
# RegisterEventHotKey asks the window server to watch for one chord and tell us
# when it happens. It needs NO permission at all - not Input Monitoring, not
# Accessibility - because the app never sees any other key. That is the whole
# reason this path exists: Input Monitoring turned out to be ungrantable from
# inside an app (see MACOS_PORT_JOURNAL.md 5.11), while this has been the way
# VS Code, Slack and every Electron app take a global shortcut for years.
#
# What it costs: the chord must be a real key plus modifiers. A lone Right
# Option cannot be registered, and left is not distinguishable from right.
#
# Called through ctypes: pyobjc has no Carbon bindings any more.

_EVENT_CLASS_KEYBOARD = 0x6b657962   # 'keyb'
_EVENT_HOTKEY_PRESSED = 5
_EVENT_HOTKEY_RELEASED = 6
_HOTKEY_SIGNATURE = 0x57565831       # 'WVX1'

# Carbon modifier bits (Events.h). Not the same numbers as NSEvent's flags.
_CARBON_MODS = {'CMD': 0x0100, 'SHIFT': 0x0200, 'ALT': 0x0800, 'CTRL': 0x1000}

# Chord spellings that reach us from the config and the capture field, mapped to
# the four modifiers Carbon knows. Sides collapse: the OS registers "a Control",
# not "the left Control".
_MOD_ALIASES = {
    'CTRL': 'CTRL', 'CONTROL': 'CTRL', 'CTRL_L': 'CTRL', 'CTRL_R': 'CTRL',
    'CTRL_LEFT': 'CTRL', 'CTRL_RIGHT': 'CTRL',
    'ALT': 'ALT', 'OPTION': 'ALT', 'OPT': 'ALT', 'ALT_L': 'ALT', 'ALT_R': 'ALT',
    'ALT_LEFT': 'ALT', 'ALT_RIGHT': 'ALT', 'OPTION_L': 'ALT', 'OPTION_R': 'ALT',
    'SHIFT': 'SHIFT', 'SHIFT_L': 'SHIFT', 'SHIFT_R': 'SHIFT',
    'SHIFT_LEFT': 'SHIFT', 'SHIFT_RIGHT': 'SHIFT',
    'CMD': 'CMD', 'COMMAND': 'CMD', 'META': 'CMD', 'WIN': 'CMD',
    'CMD_L': 'CMD', 'CMD_R': 'CMD', 'META_L': 'CMD', 'META_R': 'CMD',
    'META_LEFT': 'CMD', 'META_RIGHT': 'CMD',
}

# Key name (as the config and the Settings page spell it) -> Carbon virtual key
# code. These are positions on the keyboard, not characters, so they hold for
# every layout - the same property that makes them safe to use off the main
# thread.
_VK_BY_NAME = {
    'A': 0, 'S': 1, 'D': 2, 'F': 3, 'H': 4, 'G': 5, 'Z': 6, 'X': 7, 'C': 8,
    'V': 9, 'B': 11, 'Q': 12, 'W': 13, 'E': 14, 'R': 15, 'Y': 16, 'T': 17,
    'ONE': 18, 'TWO': 19, 'THREE': 20, 'FOUR': 21, 'SIX': 22, 'FIVE': 23,
    'NINE': 25, 'SEVEN': 26, 'EIGHT': 28, 'ZERO': 29,
    'EQUALS': 24, 'MINUS': 27, 'RIGHT_BRACKET': 30, 'LEFT_BRACKET': 33,
    'O': 31, 'U': 32, 'I': 34, 'P': 35, 'L': 37, 'J': 38, 'K': 40, 'N': 45,
    'M': 46, 'QUOTE': 39, 'SEMICOLON': 41, 'BACKSLASH': 42, 'COMMA': 43,
    'SLASH': 44, 'PERIOD': 47, 'BACKQUOTE': 50,
    'ENTER': 36, 'TAB': 48, 'SPACE': 49, 'BACKSPACE': 51, 'ESC': 53,
    'DELETE': 117, 'HOME': 115, 'END': 119, 'PAGE_UP': 116, 'PAGE_DOWN': 121,
    'LEFT': 123, 'RIGHT': 124, 'DOWN': 125, 'UP': 126,
    'F1': 122, 'F2': 120, 'F3': 99, 'F4': 118, 'F5': 96, 'F6': 97, 'F7': 98,
    'F8': 100, 'F9': 101, 'F10': 109, 'F11': 103, 'F12': 111, 'F13': 105,
    'F14': 107, 'F15': 113, 'F16': 106, 'F17': 64, 'F18': 79, 'F19': 80,
    'NUMPAD_0': 82, 'NUMPAD_1': 83, 'NUMPAD_2': 84, 'NUMPAD_3': 85,
    'NUMPAD_4': 86, 'NUMPAD_5': 87, 'NUMPAD_6': 88, 'NUMPAD_7': 89,
    'NUMPAD_8': 91, 'NUMPAD_9': 92, 'NUMPAD_ADD': 69, 'NUMPAD_SUBTRACT': 78,
    'NUMPAD_MULTIPLY': 67, 'NUMPAD_DIVIDE': 75, 'NUMPAD_DECIMAL': 65,
    'NUMPAD_ENTER': 76,
}


def parse_chord(chord):
    """'CTRL+ALT+D' -> (2, 0x1800), or None when macOS could not register it.

    None means one of: nothing but modifiers (a lone Right Option - the old
    default), two ordinary keys at once, or a name from the Windows side that
    has no key here (a mouse button).
    """
    key_code = None
    mask = 0
    for part in str(chord or '').upper().split('+'):
        part = part.strip()
        if not part:
            continue
        modifier = _MOD_ALIASES.get(part)
        if modifier:
            mask |= _CARBON_MODS[modifier]
            continue
        if part in ('ESCAPE',):
            part = 'ESC'
        elif part in ('RETURN',):
            part = 'ENTER'
        code = _VK_BY_NAME.get(part)
        if code is None or key_code is not None:
            return None
        key_code = code
    if key_code is None:
        return None
    return key_code, mask


def normalize_activation_key(value):
    """Swap a chord macOS cannot register for the one it starts with.

    Configs carried over from an earlier build hold 'alt_right', which was the
    default while the app listened through an event tap. Registering that is
    impossible, and silently having no hotkey is the worst of the outcomes -
    so it becomes the default chord, visibly, in the field the user can see.
    """
    return value if parse_chord(value) else default_activation_key()


_carbon_lib = None
_hotkey_ref = None            # EventHotKeyRef, needed to unregister
_handler_ref = None           # EventHandlerRef
_handler_upp = None           # the ctypes callback object: must outlive Carbon
_hotkey_queue = None
_hotkey_callbacks = (None, None)


def _carbon():
    global _carbon_lib
    if _carbon_lib is None:
        import ctypes
        lib = ctypes.cdll.LoadLibrary(
            '/System/Library/Frameworks/Carbon.framework/Carbon')

        class EventTypeSpec(ctypes.Structure):
            _fields_ = [('eventClass', ctypes.c_uint32),
                        ('eventKind', ctypes.c_uint32)]

        class EventHotKeyID(ctypes.Structure):
            _fields_ = [('signature', ctypes.c_uint32), ('id', ctypes.c_uint32)]

        lib.GetApplicationEventTarget.restype = ctypes.c_void_p
        lib.GetEventKind.argtypes = [ctypes.c_void_p]
        lib.GetEventKind.restype = ctypes.c_uint32
        lib.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        lib.RegisterEventHotKey.restype = ctypes.c_int32
        lib.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        lib.UnregisterEventHotKey.restype = ctypes.c_int32
        lib.InstallEventHandler.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(EventTypeSpec), ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p)]
        lib.InstallEventHandler.restype = ctypes.c_int32
        lib.RemoveEventHandler.argtypes = [ctypes.c_void_p]
        lib.RemoveEventHandler.restype = ctypes.c_int32
        lib._EventTypeSpec = EventTypeSpec
        lib._EventHotKeyID = EventHotKeyID
        _carbon_lib = lib
    return _carbon_lib


def _on_main(func):
    """Run func on the main thread. Carbon's hotkey calls belong there, and the
    app registers from two places: startup (already the main thread) and a Save
    from the page (a bridge thread)."""
    if threading.current_thread() is threading.main_thread():
        func()
        return
    from PyObjCTools import AppHelper
    AppHelper.callAfter(func)


def _hotkey_pump():
    """Deliver hotkey events off the main thread, one at a time.

    Carbon calls the handler on the main thread, and everything the app does in
    response - showing the overlay, starting the recorder - goes through
    pywebview, which marshals BACK to the main thread and waits. Doing that from
    the main thread is a deadlock. One worker, and a queue, also keeps a press
    strictly ahead of its release.
    """
    while True:
        kind = _hotkey_queue.get()
        if kind is None:
            return
        on_press, on_release = _hotkey_callbacks
        callback = on_press if kind == _EVENT_HOTKEY_PRESSED else on_release
        if callback is None:
            continue
        try:
            callback()
        except Exception as e:
            from config_manager import ConfigManager
            ConfigManager.console_print(f'Hotkey callback failed: {type(e).__name__}: {e}')


def _install_handler():
    """Install the Carbon event handler once, for both press and release."""
    global _handler_ref, _handler_upp, _hotkey_queue
    if _handler_ref is not None:
        return True
    import ctypes
    import queue
    lib = _carbon()
    _hotkey_queue = queue.Queue()
    threading.Thread(target=_hotkey_pump, name='hotkey-pump', daemon=True).start()

    proto = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p)

    def handler(_caller, event, _user_data):
        try:
            _hotkey_queue.put(lib.GetEventKind(event))
        except Exception:
            pass
        return 0            # noErr: handled, so the key never reaches anyone else

    _handler_upp = proto(handler)   # module-level: a local would be collected
    spec = (lib._EventTypeSpec * 2)(
        lib._EventTypeSpec(_EVENT_CLASS_KEYBOARD, _EVENT_HOTKEY_PRESSED),
        lib._EventTypeSpec(_EVENT_CLASS_KEYBOARD, _EVENT_HOTKEY_RELEASED))
    ref = ctypes.c_void_p()
    status = lib.InstallEventHandler(
        lib.GetApplicationEventTarget(),
        ctypes.cast(_handler_upp, ctypes.c_void_p),
        2, spec, None, ctypes.byref(ref))
    if status != 0:
        _handler_upp = None
        return False
    _handler_ref = ref
    return True


def native_hotkey(chord, on_press, on_release):
    """Let macOS itself watch for the activation chord.

    True regardless of whether this particular chord took, because the answer
    the caller needs is "does this platform do hotkeys natively" - falling back
    to an event tap would only reintroduce the permission we came here to lose.
    A chord that cannot be registered is reported and left to the user to change
    in Settings; normalize_activation_key() has already replaced the ones we
    know about.
    """
    global _hotkey_callbacks
    _hotkey_callbacks = (on_press, on_release)
    parsed = parse_chord(chord)

    def register():
        import ctypes
        from config_manager import ConfigManager
        _unregister()
        if not parsed:
            ConfigManager.console_print(
                f'Activation key {chord!r} cannot be registered on macOS - it '
                f'needs an ordinary key with at least one modifier.')
            return
        if not _install_handler():
            ConfigManager.console_print('Could not install the hotkey handler.')
            return
        global _hotkey_ref
        lib = _carbon()
        key_code, mask = parsed
        ref = ctypes.c_void_p()
        status = lib.RegisterEventHotKey(
            key_code, mask, lib._EventHotKeyID(_HOTKEY_SIGNATURE, 1),
            lib.GetApplicationEventTarget(), 0, ctypes.byref(ref))
        if status != 0:
            # -9878 is eventHotKeyExistsErr. Carbon only reports a clash with a
            # chord THIS app already holds, so this is nearly always a leftover.
            ConfigManager.console_print(
                f'Could not register {chord!r} as a hotkey (status {status}).')
            return
        _hotkey_ref = ref

    _on_main(register)
    return True


def _unregister():
    global _hotkey_ref
    if _hotkey_ref is None:
        return
    try:
        _carbon().UnregisterEventHotKey(_hotkey_ref)
    except Exception:
        pass
    _hotkey_ref = None


def native_hotkey_stop():
    _on_main(_unregister)


# ── permissions (the part users actually trip over) ───────────────────────────

def permissions_status():
    """{'microphone', 'accessibility'} -> True / False / None.

    None means "could not tell" - never report a permission as missing on a
    check that itself failed, or the onboarding would nag about nothing.

    Input Monitoring is deliberately absent. The hotkey is registered with the
    OS now, which needs no permission, so asking the user for one they cannot
    grant would be asking for nothing.
    """
    status = {'microphone': None, 'accessibility': None}
    try:
        import ApplicationServices
        status['accessibility'] = bool(ApplicationServices.AXIsProcessTrusted())
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


# IOKit is what actually backs Input Monitoring; CGRequestListenEventAccess is a
# wrapper over it. Called through ctypes because pyobjc ships no IOKit bindings.
_IOHID_LISTEN = 1          # kIOHIDRequestTypeListenEvent
_IOHID_GRANTED = 0         # kIOHIDAccessTypeGranted


def _iokit():
    import ctypes
    lib = ctypes.CDLL('/System/Library/Frameworks/IOKit.framework/IOKit')
    lib.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
    lib.IOHIDCheckAccess.restype = ctypes.c_uint32
    lib.IOHIDRequestAccess.argtypes = [ctypes.c_uint32]
    lib.IOHIDRequestAccess.restype = ctypes.c_bool
    return lib


def permissions_report():
    """What every relevant API says, and what asking does to it.

    A diagnostic, reachable as `WhisperVox --permissions`, for the recurring
    question of why this app is not listed under Input Monitoring.
    """
    lines = [f'bundle:     {BUNDLE_ID}',
             f'executable: {sys.executable}',
             f'frozen:     {getattr(sys, "frozen", False)}']
    try:
        import ApplicationServices
        lines.append(f'AXIsProcessTrusted (Accessibility): {bool(ApplicationServices.AXIsProcessTrusted())}')
    except Exception as e:
        lines.append(f'AXIsProcessTrusted failed: {e}')
    try:
        import Quartz
        lines.append(f'CGPreflightListenEventAccess: {bool(Quartz.CGPreflightListenEventAccess())}')
        lines.append(f'CGPreflightPostEventAccess:   {bool(Quartz.CGPreflightPostEventAccess())}')
    except Exception as e:
        lines.append(f'CG preflight failed: {e}')
    try:
        access = _iokit().IOHIDCheckAccess(_IOHID_LISTEN)
        names = {0: 'granted', 1: 'denied', 2: 'unknown'}
        lines.append(f'IOHIDCheckAccess(listen): {access} ({names.get(access, "?")})')
    except Exception as e:
        lines.append(f'IOHIDCheckAccess failed: {e}')
    lines.append('--- now asking ---')
    try:
        import Quartz
        lines.append(f'CGRequestListenEventAccess -> {bool(Quartz.CGRequestListenEventAccess())}')
    except Exception as e:
        lines.append(f'CGRequestListenEventAccess failed: {e}')
    try:
        lines.append(f'IOHIDRequestAccess(listen) -> {bool(_iokit().IOHIDRequestAccess(_IOHID_LISTEN))}')
    except Exception as e:
        lines.append(f'IOHIDRequestAccess failed: {e}')
    try:
        import Quartz
        lines.append(f'CGPreflightListenEventAccess after asking: {bool(Quartz.CGPreflightListenEventAccess())}')
    except Exception as e:
        lines.append(f'preflight after asking failed: {e}')
    return lines


def request_permission(which):
    """Ask the OS to show its own permission prompt.

    Fired and not waited on, so the answer arrives through permissions_status()
    polling instead. Accessibility never grants itself from the prompt - the
    prompt only offers a way to the settings pane - so the caller opens that
    pane as well.
    """
    def ask():
        try:
            if which == 'accessibility':
                import ApplicationServices
                import Quartz
                ApplicationServices.AXIsProcessTrustedWithOptions(
                    {Quartz.kAXTrustedCheckOptionPrompt: True})
            elif which == 'microphone':
                import AVFoundation
                AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    'soun', lambda granted: None)
        except Exception:
            pass

    # On the main thread, and not waited on. These are HIToolbox/TCC calls, and
    # this codebase has already paid once for calling that family off the main
    # thread: the paste path died with SIGILL inside dispatch_assert_queue. Off
    # the main thread they do not crash here, they simply do nothing - which is
    # how the app kept failing to appear in the Input Monitoring list.
    try:
        from PyObjCTools import AppHelper
        AppHelper.callAfter(ask)
    except Exception:
        ask()
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
        return ('Quit, move Whisper Vox to your Applications folder, and open it '
                'from there - macOS is running a temporary copy and will not keep '
                'any permission you grant it.')
    if path.startswith('/Volumes/'):
        return ('Quit, drag Whisper Vox onto the Applications folder, eject the '
                'disk image, and open it from Applications - permissions are not '
                'kept for an app running off an image.')
    return ''


def reset_permissions():
    """Make macOS forget every permission it has recorded for this app.

    The cure for the state where Privacy & Security lists Whisper Vox with its
    box ticked while the app is told it has nothing. macOS does not remember
    "the app named Whisper Vox" - it remembers a designated requirement, and for
    a build signed ad-hoc that requirement is the hash of the binary. A rebuild
    is therefore a different application, the old tick applies to a binary that
    no longer exists, and re-ticking it changes nothing. Clearing the entries and
    granting once more is the way out, and this saves doing it by hand.

    Only this app's entries are touched; tccutil takes a bundle id.
    """
    cleared = []
    for service in ('Accessibility', 'ListenEvent', 'Microphone', 'PostEvent'):
        try:
            result = subprocess.run(['tccutil', 'reset', service, BUNDLE_ID],
                                    capture_output=True, timeout=20)
            if result.returncode == 0:
                cleared.append(service)
        except Exception:
            pass
    return cleared


def signing_note():
    """Explain, when it applies, why granted permissions will not survive.

    Empty for a build signed with a real identity - there is nothing to warn
    about then.
    """
    if not getattr(sys, 'frozen', False):
        return ''
    app = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
    if not app.endswith('.app'):
        return ''
    try:
        result = subprocess.run(['codesign', '-dv', app],
                                capture_output=True, timeout=15)
        details = (result.stdout + result.stderr).decode('utf-8', 'replace')
    except Exception:
        return ''
    if 'adhoc' not in details:
        return ''
    return 'Allowed it before, but still asked here? Press Start over, then allow again.'


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
    """Control+Escape.

    A lone Right Option would be nicer still, and was the default while the app
    watched the keyboard through an event tap - but the OS will not register a
    bare modifier as a hotkey, and the tap needed a permission macOS would not
    give (MACOS_PORT_JOURNAL.md 5.11).

    Escape is the best key to give up: whatever a hotkey takes, it takes from
    every other app, and Escape types nothing. Ctrl+letter is claimed
    system-wide by the text editing bindings, Option+letter types a character,
    and macOS itself holds Cmd+Option+D, Ctrl+Space and Ctrl+Option+Space.
    Ctrl+Escape belongs to nobody, and both keys sit under the left hand.
    """
    return 'CTRL+ESC'


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
        # The OS registers the chord for us, and it will only take an ordinary
        # key with at least one modifier - so the capture field must refuse a
        # bare Shift or a lone Right Option instead of storing a dead hotkey.
        'chord_needs_key': True,
        # There is no Dock icon to right-click, so offer the way out here too.
        'show_quit': True,
    }
