# Preparing a new tablet

About 15 minutes per tablet. You need the Mac with this repo, the tablet, a USB cable, and the tablet's charger.

## Once per player version (on the Mac)

```sh
scripts/build_player.sh https://dooh-production.up.railway.app
```

This builds the player signed with the key in `~/dooh-keys`. **Back that folder up.** Kiosk tablets only accept updates signed with the same key.

## For each tablet

**1. Start clean**
- [ ] New tablet: power on and skip everything you can. Don't sign in to a Google account. Choose "Set up offline" or "Skip".
- [ ] Used tablet: **Settings → System → Reset → Factory reset** first, then set up as above.
- [ ] If a Google account is signed in, remove it: **Settings → Passwords & accounts** (or **Accounts**) → the account → **Remove account**. Android won't allow kiosk mode while any account is present. Removing it also stops Play Store auto-updates.
- [ ] Connect to the venue's WiFi (Settings → Network & internet).
- [ ] Set the time zone (Settings → System → Date & time). Updates are only allowed between 2:00 and 5:00 am local time.

**2. Turn on USB debugging**
- [ ] **Settings → About tablet** → tap **Build number** 7 times ("You are now a developer").
- [ ] **Settings → System → Developer options → USB debugging** on.
- [ ] Plug into the Mac and tap **Allow** on the tablet (tick "Always allow from this computer").

**3. Install and lock down (on the Mac)**
```sh
scripts/provision_tablet.sh
```
- [ ] If it asks to replace a player "signed with a different key", answer **y**. The tablet then needs pairing again.
- [ ] It ends with "✓ Player is the device owner: kiosk mode enabled". If it stops, it tells you what to fix (usually an account still signed in).

**4. Pair**
- [ ] The tablet shows a 6-character code.
- [ ] Dashboard → **Screens → Pair new screen**: enter the code, screen name, venue, address, and loop.
   - Replacing a broken tablet? Choose it under **Replaces an existing screen**. The new tablet takes over its loop and play history.
- [ ] Within a minute the tablet downloads the loop and starts playing.

**5. Check it**
- [ ] Press **Home**, swipe up, swipe down from the top, and long-press **power**. Nothing should happen.
- [ ] Press **power** once. The screen turns off, then comes back on its own within about 3 seconds.
- [ ] Hidden exit: tap the corners **top-left → top-right → bottom-right → bottom-left**, enter the maintenance PIN, and the panel opens. Tap **Back to playing**.
- [ ] In the panel, tap **Test crash recovery**. The player closes and is back, locked, within a few seconds.
- [ ] Unplug the USB cable, plug in the wall charger, and check the dashboard shows the screen **online** with the battery charging.
- [ ] Optional, for extra safety: turn **USB debugging** off (corner pattern → PIN → **Exit kiosk for 15 min** → Developer options). Turn it back on when you update the player.

## Maintenance on site

- **Open the panel:** tap the corners clockwise from top-left, then enter the PIN. If no PIN is set yet on the dashboard's Screens page, the panel opens without one. **Set a PIN before the tablet goes public.**
- **Exit kiosk for 15 min:** opens Android Settings (WiFi, brightness, volume…). After 15 minutes the player comes back and locks itself, or tap **Back to kiosk mode now** in the panel.
- **Five wrong PINs** lock the PIN pad for 5 minutes.
- **Update the player:** plug in over USB and run `scripts/provision_tablet.sh`. It sees the tablet is already a kiosk and just updates the app. The tablet keeps its pairing.
- **Retire the tablet:** panel → **Remove kiosk control**. The tablet goes back to normal and the app can be uninstalled.

## What kiosk mode does

| | |
|---|---|
| Can't leave the app | Home, Recents, notification shade, status bar and the power menu are disabled (Android lock task mode) |
| Starts by itself | After boot or a power cut, and after a crash (within a few seconds) |
| Screen always on | No sleep while powered and no lock screen. A power-button press is undone after 3 s. |
| No popups | System "app not responding" dialogs off; other apps' notifications can't show |
| No surprise updates | System updates install only from 2:00 to 5:00 am. No Google account means no Play Store auto-updates. |
| Can't be tampered with from Settings | Safe mode and adding users are blocked |
