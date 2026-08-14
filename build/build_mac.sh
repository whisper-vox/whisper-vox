#!/bin/bash
# Whisper Vox - macOS build: .app -> ad-hoc signature -> .dmg.
# Run from the project root:  bash build/build_mac.sh
#
# The .dmg is UNSIGNED and un-notarized: Gatekeeper will complain on another
# machine, and because an ad-hoc signature changes with every rebuild, macOS
# also forgets the Microphone and Accessibility grants after each update. Both
# go away with an Apple Developer ID; until then they are the honest cost of a
# free build, and the release notes say so.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYINSTALLER="$ROOT/.venv/bin/pyinstaller"
[ -x "$PYINSTALLER" ] || PYINSTALLER="pyinstaller"

# Single-sourced from launcher.py, exactly like the Windows build.
VERSION=$(sed -n "s/^APP_VERSION *= *'\(.*\)'/\1/p" build/launcher.py)

# The spec sets no target_arch, so PyInstaller builds for THIS machine. The name
# has to say which that was: an arm64 build will not start on an Intel Mac, and
# a file that does not say so is a support question waiting to happen.
ARCH=$(uname -m)
case "$ARCH" in
    arm64)  LABEL='AppleSilicon' ;;
    x86_64) LABEL='Intel' ;;
    *)      LABEL="$ARCH" ;;
esac

APP="dist/WhisperVox.app"
DMG="release/WhisperVox-v${VERSION}-${LABEL}.dmg"

echo ""
echo "Building Whisper Vox v${VERSION} for macOS ${LABEL} (${ARCH})"

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
# Ad-hoc by default. Set WHISPERVOX_SIGN_IDENTITY to a real signing identity
# (an Apple Developer ID, when the project has one) and it will be used instead.
#
# What the difference buys: TCC records a "designated requirement" when the user
# allows something, and for an ad-hoc signature that requirement is the hash of
# the binary. Every new version is therefore a different app to macOS, and the
# permissions granted to the previous one no longer apply - the entry is still
# listed with its box ticked, and the app is still told it has nothing. Users
# have to allow it again after an update, which the release notes say plainly.
# A Developer ID makes the requirement the team identifier, and it holds.
echo ""
echo "=== [3/5] Signing ==="
IDENTITY_HASH=""
if [ -n "${WHISPERVOX_SIGN_IDENTITY:-}" ]; then
    IDENTITY_HASH=$(security find-identity -v -p codesigning 2>/dev/null \
        | grep -F "$WHISPERVOX_SIGN_IDENTITY" | head -1 | awk '{print $2}')
fi
if [ -n "$IDENTITY_HASH" ] && codesign --force --deep --sign "$IDENTITY_HASH" "$APP" 2>/dev/null; then
    echo "  signed with $WHISPERVOX_SIGN_IDENTITY - permissions survive updates"
else
    [ -n "${WHISPERVOX_SIGN_IDENTITY:-}" ] && echo "  could not use $WHISPERVOX_SIGN_IDENTITY; falling back"
    codesign --force --deep --sign - "$APP"
    echo "  ad-hoc: users must re-allow permissions after an update"
fi
codesign --verify --verbose=1 "$APP" 2>&1 | sed 's/^/  /'

# ── [4/5] Package the .dmg ───────────────────────────────────────────────────
echo ""
echo "=== [4/5] Packaging ${DMG} ==="
mkdir -p release
STAGE="build/dmg_stage"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/README.txt" <<EOF
Whisper Vox v${VERSION} for macOS - ${LABEL} build

Needs macOS 13 (Ventura) or newer.

Wrong build? Apple menu > About This Mac. A line saying "Chip" means Apple
Silicon; one saying "Processor" means Intel. The Intel build runs on both (macOS
translates it through Rosetta, which it offers to install on the first launch);
the Apple Silicon build runs only on Apple Silicon.

1. Drag WhisperVox.app onto the Applications folder shown here.
2. The first launch is blocked because this build is not signed by Apple:
   open System Settings > Privacy & Security, scroll down, and click
   "Open Anyway" next to the Whisper Vox message.
3. Whisper Vox sits in the menu bar and keeps a Dock icon - either will do.
4. It needs two permissions, and it will ask for them in Settings > Misc:
     Microphone     to hear you
     Accessibility  to type the text into other apps
   Grant them in System Settings > Privacy & Security.
   The activation key needs no permission - macOS registers it for the app.
5. Open Settings, paste an API key on the API & Model tab (a free one:
   https://console.groq.com/keys), press Save, then hold Ctrl+Escape and speak.
   To use a different combination, change it on the Recording tab; the Test
   button there says whether the one you picked is free, which macOS will not.

Note: because this build is not signed with an Apple Developer ID, macOS
forgets both permissions after every update and you have to switch them on
again.
EOF
rm -f "$DMG"
hdiutil create -volname "Whisper Vox ${VERSION} ${LABEL}" -srcfolder "$STAGE" \
    -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

# ── [5/5] Report ─────────────────────────────────────────────────────────────
echo ""
echo "=== Done ==="
echo "  $APP"
echo "  $DMG  ($(du -h "$DMG" | cut -f1))"
echo "  SHA-256: $(shasum -a 256 "$DMG" | cut -d' ' -f1)"
