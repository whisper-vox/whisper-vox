# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

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

    def _parse(self, combo: str) -> set:
        key_map = {
            'CTRL': frozenset({KeyCode.CTRL_LEFT, KeyCode.CTRL_RIGHT}),
            'SHIFT': frozenset({KeyCode.SHIFT_LEFT, KeyCode.SHIFT_RIGHT}),
            'ALT': frozenset({KeyCode.ALT_LEFT, KeyCode.ALT_RIGHT}),
            'META': frozenset({KeyCode.META_LEFT, KeyCode.META_RIGHT}),
        }
        keys = set()
        for k in combo.upper().split('+'):
            k = k.strip()
            if k in key_map:
                keys.add(key_map[k])
            else:
                try:
                    keys.add(KeyCode[k])
                except KeyError:
                    print(f'Unknown key: {k}')
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

    def _ensure_key_map(self):
        if self._key_map is not None:
            return
        from pynput import keyboard, mouse
        self.keyboard = keyboard
        self.mouse = mouse
        kb = keyboard
        ms = mouse
        self._key_map = {
            kb.Key.ctrl_l: KeyCode.CTRL_LEFT, kb.Key.ctrl_r: KeyCode.CTRL_RIGHT,
            kb.Key.shift_l: KeyCode.SHIFT_LEFT, kb.Key.shift_r: KeyCode.SHIFT_RIGHT,
            kb.Key.alt_l: KeyCode.ALT_LEFT, kb.Key.alt_r: KeyCode.ALT_RIGHT,
            kb.Key.cmd_l: KeyCode.META_LEFT, kb.Key.cmd_r: KeyCode.META_RIGHT,
            kb.Key.f1: KeyCode.F1, kb.Key.f2: KeyCode.F2,
            kb.Key.f3: KeyCode.F3, kb.Key.f4: KeyCode.F4,
            kb.Key.f5: KeyCode.F5, kb.Key.f6: KeyCode.F6,
            kb.Key.f7: KeyCode.F7, kb.Key.f8: KeyCode.F8,
            kb.Key.f9: KeyCode.F9, kb.Key.f10: KeyCode.F10,
            kb.Key.f11: KeyCode.F11, kb.Key.f12: KeyCode.F12,
            kb.Key.f13: KeyCode.F13, kb.Key.f14: KeyCode.F14,
            kb.Key.f15: KeyCode.F15, kb.Key.f16: KeyCode.F16,
            kb.Key.f17: KeyCode.F17, kb.Key.f18: KeyCode.F18,
            kb.Key.f19: KeyCode.F19, kb.Key.f20: KeyCode.F20,
            kb.Key.space: KeyCode.SPACE, kb.Key.enter: KeyCode.ENTER,
            kb.Key.tab: KeyCode.TAB, kb.Key.backspace: KeyCode.BACKSPACE,
            kb.Key.esc: KeyCode.ESC, kb.Key.insert: KeyCode.INSERT,
            kb.Key.delete: KeyCode.DELETE, kb.Key.home: KeyCode.HOME,
            kb.Key.end: KeyCode.END, kb.Key.page_up: KeyCode.PAGE_UP,
            kb.Key.page_down: KeyCode.PAGE_DOWN, kb.Key.caps_lock: KeyCode.CAPS_LOCK,
            kb.Key.num_lock: KeyCode.NUM_LOCK, kb.Key.scroll_lock: KeyCode.SCROLL_LOCK,
            kb.Key.pause: KeyCode.PAUSE, kb.Key.print_screen: KeyCode.PRINT_SCREEN,
            kb.Key.up: KeyCode.UP, kb.Key.down: KeyCode.DOWN,
            kb.Key.left: KeyCode.LEFT, kb.Key.right: KeyCode.RIGHT,
            kb.Key.media_volume_mute: KeyCode.AUDIO_MUTE,
            kb.Key.media_volume_down: KeyCode.AUDIO_VOLUME_DOWN,
            kb.Key.media_volume_up: KeyCode.AUDIO_VOLUME_UP,
            kb.Key.media_play_pause: KeyCode.MEDIA_PLAY_PAUSE,
            kb.Key.media_next: KeyCode.MEDIA_NEXT,
            kb.Key.media_previous: KeyCode.MEDIA_PREVIOUS,
            ms.Button.left: KeyCode.MOUSE_LEFT,
            ms.Button.right: KeyCode.MOUSE_RIGHT,
            ms.Button.middle: KeyCode.MOUSE_MIDDLE,
        }
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
        for vk, kc in [
            (96, KeyCode.NUMPAD_0), (97, KeyCode.NUMPAD_1), (98, KeyCode.NUMPAD_2),
            (99, KeyCode.NUMPAD_3), (100, KeyCode.NUMPAD_4), (101, KeyCode.NUMPAD_5),
            (102, KeyCode.NUMPAD_6), (103, KeyCode.NUMPAD_7), (104, KeyCode.NUMPAD_8),
            (105, KeyCode.NUMPAD_9), (107, KeyCode.NUMPAD_ADD),
            (109, KeyCode.NUMPAD_SUBTRACT), (106, KeyCode.NUMPAD_MULTIPLY),
            (111, KeyCode.NUMPAD_DIVIDE), (110, KeyCode.NUMPAD_DECIMAL),
        ]:
            self._key_map[kb.KeyCode.from_vk(vk)] = kc

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
