#!/bin/bash
# Whisper Vox - create a local signing identity so macOS stops forgetting the
# permissions you grant.
#
# WHY THIS EXISTS
#
# When you allow an app under Privacy & Security, macOS does not remember "the
# app called Whisper Vox". It stores a designated requirement - a description of
# what counts as that app. For an ad-hoc signed build (codesign --sign -) that
# description is a bare cdhash: the hash of the binary itself.
#
# So every rebuild is a different application. The entry stays in the list with
# its box ticked, the app you just built matches nothing, and it is told it has
# no permission - which looks exactly like "I granted it and the app ignores me".
# Granting it again changes nothing, because the tick belongs to the old build.
#
# Signing with a certificate makes the requirement the bundle identifier plus
# that certificate, and neither changes when you rebuild. One grant, and it
# holds.
#
# This is for building and testing on your own Mac. A self-signed certificate
# means nothing on anyone else's machine - shipping to other people still wants
# an Apple Developer ID.
set -euo pipefail

NAME="${WHISPERVOX_SIGN_IDENTITY:-Whisper Vox Local Dev}"
DIR="$HOME/.whispervox-signing"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"

if security find-identity -v -p codesigning 2>/dev/null | grep -qF "$NAME"; then
    echo "Already set up: \"$NAME\" is a valid code-signing identity."
    echo "Builds will use it automatically. Nothing to do."
    exit 0
fi

echo ""
echo "This creates a code-signing certificate called \"$NAME\" in your login"
echo "keychain. macOS will ask for your password twice: once to trust the"
echo "certificate for code signing, once to let codesign use its key."
echo "Nothing leaves this Mac, and you can delete it any time in Keychain"
echo "Access by searching for its name."
echo ""

mkdir -p "$DIR"
cd "$DIR"

if [ ! -f dev.crt ]; then
    echo "1/4 creating the certificate..."
    openssl req -x509 -newkey rsa:2048 -days 3650 -keyout dev.key -out dev.crt -nodes \
        -subj "/CN=$NAME" \
        -addext "keyUsage=critical,digitalSignature" \
        -addext "extendedKeyUsage=codeSigning" 2>/dev/null
    openssl pkcs12 -export -legacy -in dev.crt -inkey dev.key -out dev.p12 \
        -password pass:whispervox 2>/dev/null
else
    echo "1/4 reusing the certificate already in $DIR"
fi

echo "2/4 importing it into your login keychain..."
security import dev.p12 -k "$KEYCHAIN" -P whispervox -T /usr/bin/codesign 2>/dev/null \
    || echo "    (already imported)"

echo "3/4 trusting it for code signing - macOS will ask for your password..."
security add-trusted-cert -r trustRoot -p codeSign -k "$KEYCHAIN" dev.crt

echo "4/4 letting codesign use the key without asking every time..."
echo "    macOS will ask for your login password once more."
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "" "$KEYCHAIN" >/dev/null 2>&1 \
    || security set-key-partition-list -S apple-tool:,apple:,codesign: -s "$KEYCHAIN" >/dev/null 2>&1 \
    || echo "    (skipped - if a keychain dialog appears during a build, click Always Allow)"

echo ""
if security find-identity -v -p codesigning 2>/dev/null | grep -qF "$NAME"; then
    echo "Done. \"$NAME\" is ready and build/build_mac.sh will use it."
    echo ""
    echo "One last time, clear out the permissions granted to the old builds -"
    echo "they point at binaries that no longer exist:"
    echo "    bash tools/reset-macos-permissions.sh"
else
    echo "The certificate is installed but not trusted yet."
    echo "Open Keychain Access, find \"$NAME\", double-click it, expand Trust,"
    echo "set Code Signing to Always Trust, then run this script again."
fi
