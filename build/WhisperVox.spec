# -*- mode: python ; coding: utf-8 -*-
# Whisper Vox (WebUI build) — onedir, no Qt. Bundles web/ + assets/ and the
# pywebview/pythonnet WebView2 runtime glue.
import os
from PyInstaller.utils.hooks import collect_all

root   = os.path.dirname(SPECPATH)
src    = os.path.join(root, 'src')
web    = os.path.join(root, 'web')
assets = os.path.join(root, 'assets')

datas = [(web, 'web'), (assets, 'assets')]
binaries = []
hiddenimports = [
    'pynput.keyboard._win32', 'pynput.mouse._win32',
    'sounddevice', 'soundfile', 'yaml', 'openai', 'winsound', 'clr',
]

# pywebview ships the WebView2 .NET glue under webview/lib; pythonnet/clr_loader
# carry the CLR. collect_all grabs their data files + dynamic libs + submodules.
for pkg in ('webview', 'clr_loader', 'pythonnet', 'pystray', 'PIL'):
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
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='WhisperVox')
