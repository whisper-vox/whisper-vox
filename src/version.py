# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sys


def get_version() -> str:
    try:
        p = os.path.join(
            os.path.dirname(sys.executable if getattr(sys, 'frozen', False)
                            else os.path.dirname(os.path.abspath(__file__))),
            '.version',
        )
        with open(p) as f:
            return f.read().strip()
    except Exception:
        return 'dev'
