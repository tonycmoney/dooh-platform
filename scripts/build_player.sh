#!/usr/bin/env bash
# Build the player APK for a server, and install it on a tablet plugged in
# over USB (if one is connected).
#
#   scripts/build_player.sh https://your-app.up.railway.app
#
# The address is compiled in as the default for new tablets; a tablet keeps
# its pairing when it's updated. The URL is passed in rather than written in
# the code so the public repo doesn't list your server.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
URL="${1:?Usage: scripts/build_player.sh https://your-server}"
case "$URL" in https://*) ;; *) echo "Use an https:// address" >&2; exit 1 ;; esac

cd "$ROOT/player"
flutter build apk --release --dart-define=SERVER_URL="${URL%/}"
APK="$ROOT/player/build/app/outputs/flutter-apk/app-release.apk"
echo "Built $APK"

export PATH="$PATH:$HOME/Library/Android/sdk/platform-tools:/opt/homebrew/share/android-commandlinetools/platform-tools"
if command -v adb >/dev/null && adb get-state >/dev/null 2>&1; then
  adb install -r "$APK"
  adb shell am start -n com.dooh.dooh_player/.MainActivity >/dev/null
  echo "Installed and started on $(adb get-serialno)"
fi
