#!/bin/bash
# Whisper Vox - macOS build: .app -> ad-hoc signature -> .dmg.
# Run from the project root:  bash build/build_mac.sh
#
# The .dmg is UNSIGNED and un-notarized: Gatekeeper will complain on another
# machine, and because an ad-hoc signature changes with every rebuild, macOS
# also forgets the Accessibility and Input Monitoring grants after each update.
# Both go away with an Apple Developer ID; until then they are the honest cost
# of a free build, and the release notes say so.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYINSTALLER="$ROOT/.venv/bin/pyinstaller"
[ -x "$PYINSTALLER" ] || PYINSTALLER="pyinstaller"

# Single-sourced from launcher.py, exactly like the Windows build.
VERSION=$(sed -n "s/^APP_VERSION *= *'\(.*\)'/\1/p" build/launcher.py)
ARCH=$(uname -m)
APP="dist/WhisperVox.app"
DMG="release/WhisperVox-v${VERSION}.dmg"

echo ""
echo "Building Whisper Vox v${VERSION} for macOS (built on ${ARCH})"

# ── [1/5] Icon: .png -> .iconset -> .icns ────────────────────────────────────
# The source logo is 256x256, so the 512 and 1024 slots are left out rather
# than filled with an upscale. Replace assets/wv-logo.png with a 1024x1024
# original and add them here.
echo ""
echo "=== [1/5] Icon ==="
ICONSET="build/wv-logo.iconset"
rm -rf "$ICONSET"; mkdir -p "$ICONSET"
for spec in "16 icon_16x16" "32 icon_16x16@2x" "32 icon_32x32" "64 icon_32x32@2x" \
            "128 icon_128x128" "256 icon_128x128@2x" "256 icon_256x256"; do
    set -- $spec
    sips -z "$1" "$1" assets/wv-logo.png --out "$ICONSET/$2.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o assets/wv-logo.icns
rm -rf "$ICONSET"
echo "  assets/wv-logo.icns"

# ── [2/5] Build the app bundle ───────────────────────────────────────────────
echo ""
echo "=== [2/5] PyInstaller ==="
"$PYINSTALLER" build/WhisperVox-mac.spec --distpath dist --workpath build/work --noconfirm --clean

# version.get_version() reads .version next to the executable.
printf '%s' "$VERSION" > "$APP/Contents/MacOS/.version"

# ── [3/5] Signature ──────────────────────────────────────────────────────────
# This decides whether macOS remembers the permissions you grant.
#
# TCC stores a "designated requirement" when you allow something. Ad-hoc signing
# produces a bare cdhash - the hash of the binary - so every rebuild is a
# different application as far as macOS is concerned: the entry in Privacy &
# Security still shows Whisper Vox with its box ticked, while the app you just
# built matches nothing and is told it has no permission. Granting it again does
# not help, because the tick belongs to the previous build.
#
# A signing identity fixes that: the requirement becomes the identifier plus the
# certificate, which does not change between builds. Run tools/setup-macos-signing.sh
# once to create a local one. Without it we fall back to ad-hoc and say so.
IDENTITY="${WHISPERVOX_SIGN_IDENTITY:-Whisper Vox Local Dev}"
echo ""
echo "=== [3/5] Signing ==="
if security find-identity -v -p codesigning 2>/dev/null | grep -qF "$IDENTITY"; then
    echo "  identity: $IDENTITY (permissions will survive rebuilds)"
    codesign --force --deep --sign "$IDENTITY" "$APP"
else
    echo "  identity: ad-hoc - no stable signing identity found."
    echo "  WARNING: macOS will forget every granted permission on the next build."
    echo "           Run tools/setup-macos-signing.sh once to stop that."
    codesign --force --deep --sign - "$APP"
fi
codesign --verify --verbose=1 "$APP" 2>&1 | sed 's/^/  /'
codesign -d -r- "$APP" 2>&1 | grep designated | sed 's/^/  /'

# ── [4/5] Package the .dmg ───────────────────────────────────────────────────
echo ""
echo "=== [4/5] Packaging ${DMG} ==="
mkdir -p release
STAGE="build/dmg_stage"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/README.txt" <<EOF
Whisper Vox v${VERSION} for macOS

Runs on every Mac. This build is Intel code; on Apple Silicon macOS runs it
through Rosetta and will offer to install that the first time, which takes a
click and about a minute.

1. Drag WhisperVox.app onto the Applications folder shown here.
2. The first launch is blocked because this build is not signed by Apple:
   open System Settings > Privacy & Security, scroll down, and click
   "Open Anyway" next to the Whisper Vox message.
3. Whisper Vox lives in the menu bar - it has no Dock icon.
4. It needs three permissions, and it will ask for them in Settings > Misc:
     Microphone        to hear you
     Input Monitoring  to notice the activation key
     Accessibility     to type the text into other apps
   Grant them in System Settings > Privacy & Security.
5. Open Settings from the menu bar icon, paste an API key on the
   API & Model tab (a free one: https://console.groq.com/keys), press Save,
   then hold Right Option and speak.

Note: because this build is not signed with an Apple Developer ID, macOS
forgets the Input Monitoring and Accessibility grants after every update and
you have to switch them on again.
EOF
rm -f "$DMG"
hdiutil create -volname "Whisper Vox ${VERSION}" -srcfolder "$STAGE" \
    -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

# ── [5/5] Report ─────────────────────────────────────────────────────────────
echo ""
echo "=== Done ==="
echo "  $APP"
echo "  $DMG  ($(du -h "$DMG" | cut -f1))"
echo "  SHA-256: $(shasum -a 256 "$DMG" | cut -d' ' -f1)"
