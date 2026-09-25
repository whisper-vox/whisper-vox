# Whisper Vox - voice dictation.
# Copyright (C) 2026 Pekelni Boroshna Lab.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License v3.0 as published by the Free
# Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generates the Win32 VERSIONINFO resource (the Details-tab fields of the exe),
so both the setup and the app exe carry the same product/company/version
metadata. Plain, unverified metadata - NOT a signature - purely
cosmetic/legitimacy (brand name only).

The version is the one this build carries (build/version_for_build.py), passed
in by the spec that calls this; asking version_for_build directly is only the
fallback for a spec run by hand."""
import os
import re

COMPANY   = 'Pekelni Boroshna Lab'
PRODUCT   = 'WhisperVox'              # identifier form (InternalName / OriginalFilename)
PRODUCT_DISPLAY = 'Whisper Vox'       # human-readable brand (ProductName)
DESC      = 'Whisper Vox voice dictation'
COPYRIGHT = '© Pekelni Boroshna Lab'


def _read_app_version(build_dir):
    """What this build carries, for a spec run by hand without a version."""
    try:
        import sys
        sys.path.insert(0, build_dir)
        from version_for_build import version_for_build
        return version_for_build(bump=False)
    except Exception:
        return '0.0.0'


def make_version_file(build_dir, version=None, exe_name=None,
                      out_name='_version_info.txt'):
    """Write a PyInstaller version-info file and return its path.

    `version` is what this build carries; `exe_name` is the file the resource
    describes, because OriginalFilename naming the wrong executable is exactly
    the sort of detail that makes a binary look forged.
    """
    ver = version or _read_app_version(build_dir)            # e.g. '1.3.17'
    exe_name = exe_name or f'{PRODUCT}.exe'
    out_name = out_name if out_name != '_version_info.txt' else         f'_version_info_{os.path.splitext(exe_name)[0]}.txt'
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
         StringStruct('OriginalFilename', '{exe_name}'),
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
