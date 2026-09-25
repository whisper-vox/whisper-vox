# -*- mode: python ; coding: utf-8 -*-
# Whisper Vox (WebUI build) — onedir, no Qt. Bundles web/ + assets/ and the
# pywebview/pythonnet WebView2 runtime glue.
import os
import sys
from PyInstaller.utils.hooks import collect_all

sys.path.insert(0, SPECPATH)
from _versioninfo import make_version_file
from version_for_build import version_for_build

root   = os.path.dirname(SPECPATH)
src    = os.path.join(root, 'src')
web    = os.path.join(root, 'web')
assets = os.path.join(root, 'assets')

# The Details tab of the exe: same version and publisher the setup carries.
# Without it Windows shows a blank publisher, which is the one thing a user CAN
# check about an unsigned binary.
version_file = make_version_file(SPECPATH, version_for_build(bump=False),
                                 'WhisperVox.exe')

datas = [(web, 'web'), (assets, 'assets')]
binaries = []
hiddenimports = [
    'pynput.keyboard._win32', 'pynput.mouse._win32',
    'sounddevice', 'soundfile', 'yaml', 'openai', 'winsound', 'clr',
    # The WinRT wrappers the update toast imports. collect_all('winrt') below
    # picks these up only as loose source files - winrt.windows is a namespace
    # package and it does not descend into it - so name them, and they are
    # compiled in with everything else instead of being found on disk by luck.
    'winrt.windows.foundation', 'winrt.windows.data.xml.dom',
    'winrt.windows.ui.notifications',
]

# pywebview ships the WebView2 .NET glue under webview/lib; pythonnet/clr_loader
# carry the CLR. collect_all grabs their data files + dynamic libs + submodules.
# winrt is imported inside a function (platforms/win.py notify_update), so the
# analysis cannot see it - and without it the update toast quietly falls back
# to the tray balloon. build_all.ps1 checks it really made it in.
for pkg in ('webview', 'clr_loader', 'pythonnet', 'pystray', 'PIL', 'winrt'):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

a = Analysis(
    [os.path.join(src, 'main.py')],
    pathex=[src],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'tkinter',
        'matplotlib', 'scipy', 'pandas',
        'faster_whisper', 'ctranslate2', 'onnxruntime', 'webrtcvad',
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='WhisperVox',
    debug=False, strip=False, upx=False, console=False,
    icon=os.path.join(assets, 'wv-logo.ico'),
    version=version_file,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='WhisperVox')
