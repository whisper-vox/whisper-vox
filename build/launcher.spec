# -*- mode: python ; coding: utf-8 -*-
# Whisper Vox setup/updater — onefile, bundles app.zip + a native Win32 splash.
import os
import sys

build_dir = SPECPATH
sys.path.insert(0, build_dir)
from _versioninfo import make_version_file
version_file = make_version_file(build_dir)

dist_zip = os.path.join(build_dir, 'app.zip')

a = Analysis(
    [os.path.join(build_dir, 'launcher.py')],
    pathex=[],
    binaries=[],
    datas=[(dist_zip, '.')],
    hiddenimports=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WhisperVox-Setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    icon=os.path.join(os.path.dirname(build_dir), 'assets', 'wv-logo.ico'),
    version=version_file,
)
