# -*- mode: python ; coding: utf-8 -*-
# Whisper Vox (macOS build) - onedir inside a .app bundle, no Qt, no .NET.
# Bundles web/ + assets/ and the pyobjc glue pywebview needs for WKWebView.
#
# Kept separate from WhisperVox.spec on purpose: the Windows build is shipping
# and stable, and it has no business carrying macOS switches. The two specs
# share nothing but the source tree.
import os
import re

from PyInstaller.utils.hooks import collect_all

root   = os.path.dirname(SPECPATH)
src    = os.path.join(root, 'src')
web    = os.path.join(root, 'web')
assets = os.path.join(root, 'assets')

# Single-sourced from launcher.py, the same value build_all.ps1 uses on Windows,
# so one release cannot ship two different version numbers.
with open(os.path.join(root, 'build', 'launcher.py'), encoding='utf-8') as f:
    VERSION = re.search(r"APP_VERSION\s*=\s*'(.+)'", f.read()).group(1)

datas = [(web, 'web'), (assets, 'assets')]
binaries = []
hiddenimports = [
    'pynput.keyboard._darwin', 'pynput.mouse._darwin',
    'sounddevice', 'soundfile', 'yaml', 'openai',
    # Imported inside functions in platforms/mac.py, so the analysis cannot see
    # them: menu bar, clipboard, screen geometry, sound and the permission APIs.
    'AppKit', 'Foundation', 'Quartz', 'ApplicationServices', 'AVFoundation',
    'PyObjCTools.AppHelper',
]

for pkg in ('webview', 'pystray', 'PIL', 'objc'):
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
        # Windows-only: winsound and the WebView2/.NET stack.
        'winsound', 'winreg', 'clr', 'clr_loader', 'pythonnet',
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='WhisperVox',
    debug=False, strip=False, upx=False, console=False,
    icon=os.path.join(assets, 'wv-logo.icns'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='WhisperVox')

app = BUNDLE(
    coll,
    name='WhisperVox.app',
    icon=os.path.join(assets, 'wv-logo.icns'),
    bundle_identifier='com.pekelniboroshna.whispervox',
    version=VERSION,
    info_plist={
        'CFBundleName': 'Whisper Vox',
        'CFBundleDisplayName': 'Whisper Vox',
        'CFBundleShortVersionString': VERSION,
        'CFBundleVersion': VERSION,
        # The app keeps its Dock icon: it is how you see that Whisper Vox is
        # running, how you get the window back, and where Quit lives. It also
        # puts an icon in the menu bar, so either route works.
        'LSUIElement': False,
        'NSHighResolutionCapable': True,
        # Shown verbatim in the macOS microphone prompt, so it says what we do
        # and nothing more. The other two permissions cannot be declared here -
        # the user grants them in System Settings (see platforms/mac.py).
        'NSMicrophoneUsageDescription':
            'Whisper Vox records your voice while you hold the activation key '
            'and sends that recording to the transcription service you chose.',
        # The build machine decides what actually runs: a binary built on a
        # newer macOS will not start on an older one, whatever this says.
        'LSMinimumSystemVersion': '13.0',
    },
)
