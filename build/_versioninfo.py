# Whisper Vox - voice dictation for Windows.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generates the Win32 VERSIONINFO resource (the Details-tab fields of the exe)
from APP_VERSION in launcher.py, so both the setup and the app exe carry the
same product/company/version metadata. Plain, unverified metadata - NOT a
signature - purely cosmetic/legitimacy (brand name only)."""
import os
import re

COMPANY   = 'Pekelni Boroshna Lab'
PRODUCT   = 'WhisperVox'              # identifier form (InternalName / OriginalFilename)
PRODUCT_DISPLAY = 'Whisper Vox'       # human-readable brand (ProductName)
DESC      = 'Whisper Vox voice dictation'
COPYRIGHT = '© Pekelni Boroshna Lab'


def _read_app_version(build_dir):
    try:
        with open(os.path.join(build_dir, 'launcher.py'), encoding='utf-8') as f:
            m = re.search(r"APP_VERSION\s*=\s*'([^']+)'", f.read())
            if m:
                return m.group(1)
    except Exception:
        pass
    return '0.0.0'


def make_version_file(build_dir, out_name='_version_info.txt'):
    """Write a PyInstaller version-info file and return its path."""
    ver = _read_app_version(build_dir)                       # e.g. '1.2.0'
    parts = [int(p) for p in re.findall(r'\d+', ver)][:4]
    while len(parts) < 4:
        parts.append(0)
    t = tuple(parts)                                         # (1, 2, 0, 0)

    content = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={t},
    prodvers={t},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', '{COMPANY}'),
         StringStruct('FileDescription', '{DESC}'),
         StringStruct('FileVersion', '{ver}'),
         StringStruct('InternalName', '{PRODUCT}'),
         StringStruct('LegalCopyright', '{COPYRIGHT}'),
         StringStruct('OriginalFilename', '{PRODUCT}.exe'),
         StringStruct('ProductName', '{PRODUCT_DISPLAY}'),
         StringStruct('ProductVersion', '{ver}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    path = os.path.join(build_dir, out_name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path
