# DOOH Platform

A self-hosted **digital out-of-home (DOOH) screen ad network**. Upload ads (photos, videos, text slides) in a web dashboard, arrange them into loops, assign loops to screens, and inexpensive Android tablets play them fullscreen around the clock. The tablets report their location, battery and what they're playing, and log every play as proof of play.

It has three parts:

- **backend/**: FastAPI + PostgreSQL. Handles device pairing, media and text slides, loops, the player manifest, heartbeats, idempotent proof of play and an approval queue.
- **dashboard/**: React (Vite + TypeScript) control panel that runs on the Mac.
- **player/**: Flutter Android app for the screens (tested on a KB10 tablet running Android 16).

## Requirements

- macOS with [Homebrew](https://brew.sh). Linux works too, but uses ffmpeg instead of macOS `avconvert` to convert video.
- PostgreSQL 17, Python 3.13 (through [uv](https://docs.astral.sh/uv/)), Node.js, ffmpeg
- Flutter and the Android SDK, to build the player
- An Android tablet or phone running Android 8 or later (tested on Android 16)

## Run it locally

Install the tools and set up once:

```sh
brew install postgresql@17 uv node ffmpeg
brew services start postgresql@17
createdb dooh

cp backend/.env.example backend/.env
# Edit backend/.env: choose an ADMIN_PASSWORD and set SECRET_KEY to a long random value, e.g.
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

(cd dashboard && npm install)
```

Start everything:

```sh
scripts/dev.sh
```

- Dashboard: http://localhost:5173 (sign in with `ADMIN_PASSWORD` from `backend/.env`)
- API docs: http://localhost:8000/docs

When a tablet is plugged in over USB, `dev.sh` runs `adb reverse tcp:8000 tcp:8000`. That lets the tablet reach the backend at `http://127.0.0.1:8000`, which is the player's default server address.

## Install the player on the tablet

```sh
cd player
flutter devices                      # find your tablet's device id
flutter run --release -d <device-id>
# or: flutter build apk --release && adb install -r build/app/outputs/flutter-apk/app-release.apk
```

### One-time tablet setup (Android 10 and later)

Android doesn't let apps start themselves in the background. Two settings, done once by hand, let the player start after a reboot and restart after a crash. The pairing screen shows both as buttons:

1. **Display over other apps**: turn this on for DOOH Player.
2. **Default Home app**: choose DOOH Player. Android then brings it back after reboots, crashes and Home presses.

To get back into tablet settings after that, tap the **top-left corner 5 times** while content is playing. This opens the player's settings panel.

## How it works

| Requirement | Implementation |
| --- | --- |
| Pairing | Unpaired tablet calls `POST /api/player/register` and shows a 6-character code. You enter it under Screens → Pair new screen. The tablet then collects its device token. |
| Permanent ID | Android `ANDROID_ID`, which survives reinstalls |
| Updates reach the tablet within a minute | The tablet polls `GET /api/player/manifest` every 60 s, and a heartbeat that sees a new manifest version triggers a sync right away |
| Offline playback | Every file is downloaded and its SHA-256 checked before a new loop goes live; files are cached on the tablet |
| Heartbeat | `POST /api/player/heartbeat` every 60 s with battery, GPS, app version and what's playing now. The screen shows as offline after 180 s (3 missed heartbeats). |
| Proof of play | Each play gets a UUID on the tablet and is queued on disk. `POST /api/player/plays` inserts with `ON CONFLICT DO NOTHING`, so retries are never counted twice. |
| Kiosk mode | Fullscreen landscape, screen kept on, system bars hidden, Back button disabled, can be the Home launcher, starts on boot |
| Crash restart | `PlayerApplication.kt` catches crashes and relaunches the app through a separate restarter process, with an alarm as backup |
| Uploads from Photos | Accepts JPG, PNG, HEIC, MP4 and MOV. HEIC becomes JPG, with the camera's rotation applied and GPS metadata removed. MOV, HEVC, HDR and 4K video becomes 1080p H.264 MP4, using macOS `avconvert` or ffmpeg. The dashboard sends the raw file bytes with an `X-Filename` header; multipart uploads with any field name also work. |
| Approval queue | Only approved media is sent to screens. "Auto-approve my uploads" (on the Media page) controls whether new uploads skip the queue. |

Item timing: each loop item plays for its set seconds (default 10). A video either **loops** to fill that time, or plays **once and is cut** at that time (or ends when the video does, if that comes first).

## Security notes

- `backend/.env` holds the admin password and the token-signing key. It is ignored by git; never commit it. If it leaks, change both values and restart the backend.
- The dashboard is built for a trusted local network. Before putting it on the internet, put it behind HTTPS, use a strong password, and set the allowed CORS origins in `backend/app/main.py` to your real dashboard address.
- Uploaded files are served without authentication at `/files/…` so screens can download them. Don't upload anything private.
- Photos are re-encoded without GPS metadata when converted. Original JPG/PNG files without location or rotation data are stored unchanged.

## Tests

```sh
(cd backend && uv run pytest)
(cd player && flutter test)
```

## License

[MIT](LICENSE)
