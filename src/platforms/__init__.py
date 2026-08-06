# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Picks the platform backend and presents it as one flat namespace.

The defaults from base.py are imported first, then the backend for this OS
overrides whatever it implements - so a backend only has to define what it can
actually do, and a caller can never hit a missing name.

The package is deliberately NOT called `platform`: src/ sits first on sys.path,
so that name would shadow the standard library module of the same name for
every dependency in the process (pyinstaller, pywebview, sounddevice all import
it), and the failure would be silent and bizarre.
"""
import sys

from .base import *   # noqa: F401,F403 - defaults for anything a backend skips

if sys.platform == 'win32':
    from .win import *   # noqa: F401,F403
elif sys.platform == 'darwin':
    from .mac import *   # noqa: F401,F403
