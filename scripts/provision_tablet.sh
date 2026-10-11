#!/usr/bin/env bash
# Turn a tablet plugged in over USB into a locked-down screen: install the
# player and make it the tablet's device owner, which enables kiosk mode.
#
#   scripts/build_player.sh https://your-server     # once per player version
#   scripts/provision_tablet.sh                     # once per tablet
#
# Android only allows a device owner on a tablet with no accounts (remove the
# Google account first) and a single user. See docs/tablet-setup.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APK="${1:-$ROOT/player/build/app/outputs/flutter-apk/app-release.apk}"
PKG=com.dooh.dooh_player
ADMIN=$PKG/.AdminReceiver
export PATH="$PATH:$HOME/Library/Android/sdk/platform-tools:/opt/homebrew/share/android-commandlinetools/platform-tools"

die() { echo "✗ $*" >&2; exit 1; }
ok() { echo "✓ $*"; }

command -v adb >/dev/null || die "adb not found. Install the Android platform tools."
[ -f "$APK" ] || die "No player APK at $APK. Run scripts/build_player.sh https://your-server first."
[ "$(adb get-state 2>/dev/null)" = device ] || die "No tablet found. Plug it in over USB, unlock it and tap Allow on the USB debugging prompt."
SERIAL=$(adb get-serialno)
ok "Tablet $(adb shell getprop ro.product.model | tr -d '\r') (Android $(adb shell getprop ro.build.version.release | tr -d '\r'))"

OWNER=$(adb shell dpm list-owners 2>/dev/null | tr -d '\r')
if echo "$OWNER" | grep -q "$PKG"; then
  ok "Already a kiosk (device owner): updating the player only"
  adb install -r "$APK" >/dev/null || die "Update failed. Is the APK signed with the key in ~/dooh-keys?"
  adb shell am start -n "$PKG/.MainActivity" >/dev/null
  ok "Player updated and restarted"
  exit 0
fi
echo "$OWNER" | grep -qi "device owner" && die "Another app is device owner. Factory reset the tablet first."

ACCOUNTS=$(adb shell dumpsys account | grep -c "Account {" || true)
[ "$ACCOUNTS" -eq 0 ] || die "The tablet has $ACCOUNTS account(s) signed in (e.g. Google). Remove them in Settings → Passwords & accounts, then run this again."
USERS=$(adb shell pm list users | grep -c "UserInfo{" || true)
[ "$USERS" -le 1 ] || die "The tablet has $USERS users. Remove the extra users (Settings → System → Multiple users), then run this again."
ok "No accounts, one user"

if adb shell pm path "$PKG" >/dev/null 2>&1; then
  if ! out=$(adb install -r "$APK" 2>&1); then
    if echo "$out" | grep -q "INSTALL_FAILED_UPDATE_INCOMPATIBLE"; then
      echo "The installed player was signed with a different key. Replacing it removes its pairing:"
      echo "you'll pair the tablet again (choose \"Replaces an existing screen\" to keep its history)."
      read -r -p "Uninstall the old player and continue? [y/N] " answer
      [ "$answer" = y ] || die "Stopped. Nothing was changed."
      adb uninstall "$PKG" >/dev/null
      adb install "$APK" >/dev/null
    else
      die "Install failed: $out"
    fi
  fi
else
  adb install "$APK" >/dev/null
fi
ok "Player installed"

adb shell dpm set-device-owner "$ADMIN" >/dev/null || die "Android refused the device owner. Check the accounts and users above, or factory reset the tablet."
ok "Player is the device owner: kiosk mode enabled"

adb shell am start -n "$PKG/.MainActivity" >/dev/null
sleep 3
adb shell dumpsys activity activities | grep -q "mLockTaskModeState=LOCKED" && ok "Kiosk locked" ||
  echo "… kiosk locks as soon as the player is on screen"

cat <<EOF

Done ($SERIAL). Next:
  1. Dashboard → Screens → Pair new screen, and enter the code on the tablet.
  2. Set a maintenance PIN on the Screens page if you haven't (tablets get it within a minute).
  3. Optional: turn off USB debugging in Developer options; you'll need it again for updates.
EOF
