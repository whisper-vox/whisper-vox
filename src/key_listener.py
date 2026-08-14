# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Callable, Set

from config_manager import ConfigManager


class InputEvent(Enum):
    KEY_PRESS = auto()
    KEY_RELEASE = auto()
    MOUSE_PRESS = auto()
    MOUSE_RELEASE = auto()


class KeyCode(Enum):
    CTRL_LEFT = auto(); CTRL_RIGHT = auto()
    SHIFT_LEFT = auto(); SHIFT_RIGHT = auto()
    ALT_LEFT = auto(); ALT_RIGHT = auto()
    META_LEFT = auto(); META_RIGHT = auto()
    F1 = auto(); F2 = auto(); F3 = auto(); F4 = auto()
    F5 = auto(); F6 = auto(); F7 = auto(); F8 = auto()
    F9 = auto(); F10 = auto(); F11 = auto(); F12 = auto()
    F13 = auto(); F14 = auto(); F15 = auto(); F16 = auto()
    F17 = auto(); F18 = auto(); F19 = auto(); F20 = auto()
    ONE = auto(); TWO = auto(); THREE = auto(); FOUR = auto()
    FIVE = auto(); SIX = auto(); SEVEN = auto(); EIGHT = auto()
    NINE = auto(); ZERO = auto()
    A = auto(); B = auto(); C = auto(); D = auto(); E = auto()
    F = auto(); G = auto(); H = auto(); I = auto(); J = auto()
    K = auto(); L = auto(); M = auto(); N = auto(); O = auto()
    P = auto(); Q = auto(); R = auto(); S = auto(); T = auto()
    U = auto(); V = auto(); W = auto(); X = auto(); Y = auto()
    Z = auto()
    SPACE = auto(); ENTER = auto(); TAB = auto(); BACKSPACE = auto()
    ESC = auto(); INSERT = auto(); DELETE = auto(); HOME = auto()
    END = auto(); PAGE_UP = auto(); PAGE_DOWN = auto()
    CAPS_LOCK = auto(); NUM_LOCK = auto(); SCROLL_LOCK = auto()
    PAUSE = auto(); PRINT_SCREEN = auto()
    UP = auto(); DOWN = auto(); LEFT = auto(); RIGHT = auto()
    NUMPAD_0 = auto(); NUMPAD_1 = auto(); NUMPAD_2 = auto()
    NUMPAD_3 = auto(); NUMPAD_4 = auto(); NUMPAD_5 = auto()
    NUMPAD_6 = auto(); NUMPAD_7 = auto(); NUMPAD_8 = auto()
    NUMPAD_9 = auto(); NUMPAD_ADD = auto(); NUMPAD_SUBTRACT = auto()
    NUMPAD_MULTIPLY = auto(); NUMPAD_DIVIDE = auto()
    NUMPAD_DECIMAL = auto(); NUMPAD_ENTER = auto()
    MINUS = auto(); EQUALS = auto(); LEFT_BRACKET = auto()
    RIGHT_BRACKET = auto(); SEMICOLON = auto(); QUOTE = auto()
    BACKQUOTE = auto(); BACKSLASH = auto(); COMMA = auto()
    PERIOD = auto(); SLASH = auto()
    MUTE = auto(); VOLUME_DOWN = auto(); VOLUME_UP = auto()
    PLAY_PAUSE = auto(); NEXT_TRACK = auto(); PREV_TRACK = auto()
    MEDIA_PLAY_PAUSE = auto(); MEDIA_STOP = auto()
    MEDIA_PREVIOUS = auto(); MEDIA_NEXT = auto()
    AUDIO_MUTE = auto(); AUDIO_VOLUME_UP = auto(); AUDIO_VOLUME_DOWN = auto()
    MOUSE_LEFT = auto(); MOUSE_RIGHT = auto(); MOUSE_MIDDLE = auto()
    MOUSE_BACK = auto(); MOUSE_FORWARD = auto()


class InputBackend(ABC):
    @classmethod
    @abstractmethod
    def is_available(cls) -> bool: ...

    @abstractmethod
    def start(self): ...

    @abstractmethod
    def stop(self): ...

    @abstractmethod
    def on_input_event(self, event): ...


class KeyChord:
    def __init__(self, keys):
        self.keys = keys
        self.pressed_keys: Set[KeyCode] = set()

    def update(self, key, event_type) -> bool:
        if event_type == InputEvent.KEY_PRESS:
            self.pressed_keys.add(key)
        elif event_type == InputEvent.KEY_RELEASE:
            self.pressed_keys.discard(key)
        return self.is_active()

    def is_active(self) -> bool:
        for key in self.keys:
            if isinstance(key, frozenset):
                if not any(k in self.pressed_keys for k in key):
                    return False
            elif key not in self.pressed_keys:
                return False
        return True


class KeyListener:
    def __init__(self):
        self.active_backend = None
        self.key_chord = None
        self.callbacks = {'on_activate': [], 'on_deactivate': []}
        self._load_keys()
        self._init_backend()

    def _load_keys(self):
        combo = ConfigManager.get('activation_key', 'f2')
        self.key_chord = KeyChord(self._parse(combo))

    # Spellings that reach us from configs and from the Settings capture field but
    # are not KeyCode member names: the UI writes WIN for the meta key, and a
    # side-specific key is naturally written alt_r / ctrl_l. macOS users also
    # think in Command/Option. Resolved before the KeyCode lookup.
    _ALIASES = {
        'WIN': 'META', 'CMD': 'META', 'COMMAND': 'META', 'OPTION': 'ALT',
        'CTRL_L': 'CTRL_LEFT', 'CTRL_R': 'CTRL_RIGHT',
        'SHIFT_L': 'SHIFT_LEFT', 'SHIFT_R': 'SHIFT_RIGHT',
        'ALT_L': 'ALT_LEFT', 'ALT_R': 'ALT_RIGHT',
        'META_L': 'META_LEFT', 'META_R': 'META_RIGHT',
        'CMD_L': 'META_LEFT', 'CMD_R': 'META_RIGHT',
        'OPTION_L': 'ALT_LEFT', 'OPTION_R': 'ALT_RIGHT',
        'ESCAPE': 'ESC', 'RETURN': 'ENTER',
    }

    def _parse(self, combo: str) -> set:
        key_map = {
            'CTRL': frozenset({KeyCode.CTRL_LEFT, KeyCode.CTRL_RIGHT}),
            'SHIFT': frozenset({KeyCode.SHIFT_LEFT, KeyCode.SHIFT_RIGHT}),
            'ALT': frozenset({KeyCode.ALT_LEFT, KeyCode.ALT_RIGHT}),
            'META': frozenset({KeyCode.META_LEFT, KeyCode.META_RIGHT}),
        }
        keys = set()
        for k in combo.upper().split('+'):
            k = self._ALIASES.get(k.strip(), k.strip())
            if k in key_map:
                keys.add(key_map[k])
            else:
                try:
                    keys.add(KeyCode[k])
                except KeyError:
                    print(f'Unknown key: {k}')
        # An empty chord is "always active" (nothing to check), which silently
        # disables the hotkey. Fall back to the default so a typo in the config
        # can never leave the app deaf.
        if not keys:
            print('No usable activation key parsed - falling back to F2.')
            keys.add(KeyCode.F2)
        return keys

    _MOUSE_KEYS = frozenset({
        KeyCode.MOUSE_LEFT, KeyCode.MOUSE_RIGHT, KeyCode.MOUSE_MIDDLE,
        KeyCode.MOUSE_BACK, KeyCode.MOUSE_FORWARD,
    })

    def _needs_mouse(self):
        """Only a mouse-button activation key needs the global mouse hook.
        The hook fires on every cursor move, so for keyboard hotkeys (the common
        case) we skip it entirely — under the WebView2 (.NET) loop a per-move
        Python callback storm makes the whole app lag and hang."""
        for k in self.key_chord.keys:
            if isinstance(k, KeyCode) and k in self._MOUSE_KEYS:
                return True
        return False

    def _init_backend(self):
        self.active_backend = PynputBackend()
        self.active_backend.on_input_event = self.on_input_event

    def start(self):
        self.active_backend.start(needs_mouse=self._needs_mouse())

    def stop(self):
        self.active_backend.stop()

    def reload_keys(self):
        self._load_keys()

    def on_input_event(self, event):
        key, event_type = event
        was_active = self.key_chord.is_active()
        is_active = self.key_chord.update(key, event_type)
        if not was_active and is_active:
            self._trigger('on_activate')
        elif was_active and not is_active:
            self._trigger('on_deactivate')

    def add_callback(self, event: str, callback: Callable):
        if event in self.callbacks:
            self.callbacks[event].append(callback)

    def _trigger(self, event: str):
        for cb in self.callbacks.get(event, []):
            cb()


class PynputBackend(InputBackend):
    @classmethod
    def is_available(cls) -> bool:
        try:
            import pynput
            return True
        except ImportError:
            return False

    def __init__(self):
        self.keyboard_listener = None
        self.mouse_listener = None
        self.keyboard = None
        self.mouse = None
        self._key_map = None

    # pynput's Key enum is built per platform: the macOS build has no insert,
    # num_lock, scroll_lock, pause or print_screen. Looking those up as
    # attributes raised AttributeError and killed the whole listener process, so
    # the map is built by NAME and anything the platform lacks is skipped. On
    # Windows every name below exists, so the resulting map is unchanged.
    _KEY_NAMES = [
        ('ctrl_l', 'CTRL_LEFT'), ('ctrl_r', 'CTRL_RIGHT'),
        ('shift_l', 'SHIFT_LEFT'), ('shift_r', 'SHIFT_RIGHT'),
        ('alt_l', 'ALT_LEFT'), ('alt_r', 'ALT_RIGHT'),
        ('alt_gr', 'ALT_RIGHT'),
        ('cmd_l', 'META_LEFT'), ('cmd_r', 'META_RIGHT'),
        ('f1', 'F1'), ('f2', 'F2'), ('f3', 'F3'), ('f4', 'F4'),
        ('f5', 'F5'), ('f6', 'F6'), ('f7', 'F7'), ('f8', 'F8'),
        ('f9', 'F9'), ('f10', 'F10'), ('f11', 'F11'), ('f12', 'F12'),
        ('f13', 'F13'), ('f14', 'F14'), ('f15', 'F15'), ('f16', 'F16'),
        ('f17', 'F17'), ('f18', 'F18'), ('f19', 'F19'), ('f20', 'F20'),
        ('space', 'SPACE'), ('enter', 'ENTER'), ('tab', 'TAB'),
        ('backspace', 'BACKSPACE'), ('esc', 'ESC'), ('insert', 'INSERT'),
        ('delete', 'DELETE'), ('home', 'HOME'), ('end', 'END'),
        ('page_up', 'PAGE_UP'), ('page_down', 'PAGE_DOWN'),
        ('caps_lock', 'CAPS_LOCK'), ('num_lock', 'NUM_LOCK'),
        ('scroll_lock', 'SCROLL_LOCK'), ('pause', 'PAUSE'),
        ('print_screen', 'PRINT_SCREEN'),
        ('up', 'UP'), ('down', 'DOWN'), ('left', 'LEFT'), ('right', 'RIGHT'),
        ('media_volume_mute', 'AUDIO_MUTE'),
        ('media_volume_down', 'AUDIO_VOLUME_DOWN'),
        ('media_volume_up', 'AUDIO_VOLUME_UP'),
        ('media_play_pause', 'MEDIA_PLAY_PAUSE'),
        ('media_next', 'MEDIA_NEXT'), ('media_previous', 'MEDIA_PREVIOUS'),
    ]

    # Numpad keys arrive as raw virtual key codes, and those are OS-specific:
    # Windows VK_NUMPAD* vs the Carbon kVK_ANSI_Keypad* codes used on macOS.
    _NUMPAD_VK_WIN = [
        (96, 'NUMPAD_0'), (97, 'NUMPAD_1'), (98, 'NUMPAD_2'), (99, 'NUMPAD_3'),
        (100, 'NUMPAD_4'), (101, 'NUMPAD_5'), (102, 'NUMPAD_6'), (103, 'NUMPAD_7'),
        (104, 'NUMPAD_8'), (105, 'NUMPAD_9'), (107, 'NUMPAD_ADD'),
        (109, 'NUMPAD_SUBTRACT'), (106, 'NUMPAD_MULTIPLY'), (111, 'NUMPAD_DIVIDE'),
        (110, 'NUMPAD_DECIMAL'),
    ]
    _NUMPAD_VK_DARWIN = [
        (82, 'NUMPAD_0'), (83, 'NUMPAD_1'), (84, 'NUMPAD_2'), (85, 'NUMPAD_3'),
        (86, 'NUMPAD_4'), (87, 'NUMPAD_5'), (88, 'NUMPAD_6'), (89, 'NUMPAD_7'),
        (91, 'NUMPAD_8'), (92, 'NUMPAD_9'), (69, 'NUMPAD_ADD'),
        (78, 'NUMPAD_SUBTRACT'), (67, 'NUMPAD_MULTIPLY'), (75, 'NUMPAD_DIVIDE'),
        (65, 'NUMPAD_DECIMAL'), (76, 'NUMPAD_ENTER'),
    ]

    def _ensure_key_map(self):
        if self._key_map is not None:
            return
        from pynput import keyboard, mouse
        self.keyboard = keyboard
        self.mouse = mouse
        kb = keyboard
        ms = mouse
        self._key_map = {}
        for attr, code in self._KEY_NAMES:
            key = getattr(kb.Key, attr, None)
            if key is not None:
                self._key_map[key] = KeyCode[code]
        self._key_map.update({
            ms.Button.left: KeyCode.MOUSE_LEFT,
            ms.Button.right: KeyCode.MOUSE_RIGHT,
            ms.Button.middle: KeyCode.MOUSE_MIDDLE,
        })
        for ch, kc in [
            ('1', KeyCode.ONE), ('2', KeyCode.TWO), ('3', KeyCode.THREE),
            ('4', KeyCode.FOUR), ('5', KeyCode.FIVE), ('6', KeyCode.SIX),
            ('7', KeyCode.SEVEN), ('8', KeyCode.EIGHT), ('9', KeyCode.NINE),
            ('0', KeyCode.ZERO), ('a', KeyCode.A), ('b', KeyCode.B),
            ('c', KeyCode.C), ('d', KeyCode.D), ('e', KeyCode.E),
            ('f', KeyCode.F), ('g', KeyCode.G), ('h', KeyCode.H),
            ('i', KeyCode.I), ('j', KeyCode.J), ('k', KeyCode.K),
            ('l', KeyCode.L), ('m', KeyCode.M), ('n', KeyCode.N),
            ('o', KeyCode.O), ('p', KeyCode.P), ('q', KeyCode.Q),
            ('r', KeyCode.R), ('s', KeyCode.S), ('t', KeyCode.T),
            ('u', KeyCode.U), ('v', KeyCode.V), ('w', KeyCode.W),
            ('x', KeyCode.X), ('y', KeyCode.Y), ('z', KeyCode.Z),
            ('-', KeyCode.MINUS), ('=', KeyCode.EQUALS),
            ('[', KeyCode.LEFT_BRACKET), (']', KeyCode.RIGHT_BRACKET),
            (';', KeyCode.SEMICOLON), ("'", KeyCode.QUOTE),
            ('`', KeyCode.BACKQUOTE), ('\\', KeyCode.BACKSLASH),
            (',', KeyCode.COMMA), ('.', KeyCode.PERIOD), ('/', KeyCode.SLASH),
        ]:
            self._key_map[kb.KeyCode.from_char(ch)] = kc
        numpad = (self._NUMPAD_VK_DARWIN if sys.platform == 'darwin'
                  else self._NUMPAD_VK_WIN)
        for vk, code in numpad:
            self._key_map[kb.KeyCode.from_vk(vk)] = KeyCode[code]

    def start(self, needs_mouse=False):
        self._ensure_key_map()
        self.keyboard_listener = self.keyboard.Listener(
            on_press=lambda k: self.on_input_event((self._key_map.get(k, KeyCode.SPACE), InputEvent.KEY_PRESS)),
            on_release=lambda k: self.on_input_event((self._key_map.get(k, KeyCode.SPACE), InputEvent.KEY_RELEASE)),
        )
        self.keyboard_listener.start()
        # The global mouse hook fires on EVERY cursor move; only install it when a
        # mouse button is actually part of the activation combo (otherwise it
        # floods Python with callbacks and, under the WebView2 .NET loop, hangs).
        if needs_mouse:
            self.mouse_listener = self.mouse.Listener(
                on_click=lambda x, y, btn, pressed: self.on_input_event((
                    self._key_map.get(btn, KeyCode.MOUSE_LEFT),
                    InputEvent.KEY_PRESS if pressed else InputEvent.KEY_RELEASE,
                ))
            )
            self.mouse_listener.start()

    def stop(self):
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None
        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None

    def on_input_event(self, event):
        pass
