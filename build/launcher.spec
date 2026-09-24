# -*- mode: python ; coding: utf-8 -*-
# Whisper Vox setup/updater — onefile, bundles app.zip + a native Win32 splash.
import os
import re
import sys
import time

build_dir = SPECPATH
sys.path.insert(0, build_dir)
from _versioninfo import make_version_file
from version_for_build import version_for_build

# The version this build carries. The build script has already decided it and
# put it in the environment; version_for_build reads that, and only falls back
# to the local counter when the spec is run by hand.
version = version_for_build(bump=False)
version_file = make_version_file(build_dir, version, 'WhisperVox-Setup.exe')

# launcher.py carries the version and build date as literals, because the
# installed app has no git and no build script to ask. Stamping them into the
# tracked file would leave it permanently modified and make a local build
# number look like a change worth committing - so stamp a generated copy and
# build that instead. build/_launcher_build.py is disposable.
stamped = os.path.join(build_dir, '_launcher_build.py')
with open(os.path.join(build_dir, 'launcher.py'), encoding='utf-8') as f:
    source = f.read()
source = re.sub(r"^APP_VERSION\s*=\s*'[^']*'",
                f"APP_VERSION = '{version}'", source, count=1, flags=re.M)
source = re.sub(r"^BUILD_DATE\s*=\s*'[^']*'",
                f"BUILD_DATE  = '{time.strftime('%Y-%m-%d')}'", source, count=1, flags=re.M)
with open(stamped, 'w', encoding='utf-8') as f:
    f.write(source)

dist_zip = os.path.join(build_dir, 'app.zip')

a = Analysis(
    [stamped],
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
