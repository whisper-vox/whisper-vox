#!/bin/bash
# Whisper Vox - forget every permission macOS has recorded for this app.
#
# Useful when the Privacy & Security list shows Whisper Vox with its box ticked
# while the app insists it has no permission. That means the entry belongs to an
# older build: an ad-hoc signature identifies an app by the hash of its binary,
# so a rebuild no longer matches what was allowed. Clearing the entries and
# granting once more fixes it. The Settings window has a "Start over" button
# that does the same thing without the Terminal.
#
# This only touches Whisper Vox. Other apps keep their permissions.
set -euo pipefail

BUNDLE_ID='com.pekelniboroshna.whispervox'

echo "Clearing macOS permissions for $BUNDLE_ID"
for service in Accessibility ListenEvent Microphone PostEvent; do
    if tccutil reset "$service" "$BUNDLE_ID" >/dev/null 2>&1; then
        echo "  cleared: $service"
    else
        echo "  nothing to clear: $service"
    fi
done

echo ""
echo "Done. Quit Whisper Vox if it is running, start it again, and grant the"
echo "permissions once more - this time to the build you are actually running."
