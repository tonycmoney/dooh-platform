# DOOH Platform

A self-hosted **digital out-of-home (DOOH) screen ad network**. Upload ads (photos, videos, text slides) in a web dashboard, arrange them into loops, assign loops to screens, and inexpensive Android tablets play them fullscreen around the clock. The tablets report their location, battery and what they're playing, and log every play as proof of play.

It has three parts:

- **backend/**: FastAPI + PostgreSQL. Handles device pairing, media and text slides, loops, the player manifest, heartbeats, idempotent proof of play and an approval queue.
- **dashboard/**: React (Vite + TypeScript) control panel that runs on the Mac.
- **player/**: Flutter Android app for the screens, locked to portrait (tested on a KB10 tablet running Android 16). Recommended ad size: **1080 × 1920 px**.

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

### Kiosk mode (public screens)

For a tablet in a business, run `scripts/provision_tablet.sh`. It installs the player and makes it the tablet's **device owner**, which turns on kiosk mode:
- Android lock task mode, with no Home, Recents, notifications or power menu.
- Auto-start after boot, a power cut or a crash.
- The screen always on.
- System error dialogs off.
- System updates only between 2:00 and 5:00 am.

Android requires the tablet to have no accounts signed in. Step-by-step checklist: [docs/tablet-setup.md](docs/tablet-setup.md).

**Hidden exit:** tap the four corners clockwise from top-left, then enter the maintenance PIN you set on the dashboard's Screens page. Tablets store only a salted PBKDF2 hash and check it offline. The panel can pause kiosk mode for 15 minutes or remove it entirely.

Release builds are signed with the key in `~/dooh-keys` (override with `DOOH_KEY_PROPERTIES`). It's never in the repo. Back it up: kiosk tablets only accept updates signed with that key.

Without kiosk mode (e.g. a test tablet), the player still runs. Two settings, set once by hand, let it start after a reboot and restart after a crash: **Display over other apps**, and DOOH Player as the **Default Home app**. The settings panel shows both.

## Deploy to the cloud (Railway)

The `Dockerfile` builds one image: the backend serves the API, the uploaded media at `/files/…` and the built dashboard at `/`. `railway.json` tells Railway to use it, with `/api/health` as the health check.

1. Create a Railway project with a **PostgreSQL** database and a service built from this repo.
2. On the service, add a **volume** mounted at `/data`. Formatted media goes in `/data/media`, originals in `/data/originals` and database backups in `/data/backups`.
3. Set the service variables:
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
   - `SECRET_KEY`: a random string of 32+ characters
   - `ADMIN_PASSWORD`: your dashboard password, 12+ characters
   - `DAILY_BACKUPS` = `true`
4. Generate a public domain under the service's Settings → Networking. Railway provides HTTPS.
5. Build the player for that address: `scripts/build_player.sh https://<your-domain>`.

The image sets `ENVIRONMENT=production`, so the server refuses to start with a missing or weak password or key. Database migrations run on every start.

**Reformatting:** `uv run python -m app.reformat` brings every item to the current format. Items stored before originals were kept adopt their stored file as the original. Run it on the server after a format change (`--all` redoes everything; `--dry-run` only lists the items).

**Backups:** the server runs `pg_dump` once a day and keeps 14 days of dumps. They're listed on the dashboard's Backups page, where you can download them. Restore one with `pg_restore --clean --if-exists --no-owner -d <database-url> <file>.dump`. Turn on Railway's scheduled volume backups as well (on both the database and the `/data` volume), since they also cover the media files. If media files are ever lost, `PUT /api/admin/media/{id}/file` with the original file puts each one back. The server checks the file's SHA-256 against the one recorded at upload.

## How it works

| Requirement | Implementation |
| --- | --- |
| Pairing | Unpaired tablet calls `POST /api/player/register` and shows a 6-character code. You enter it under Screens → Pair new screen. The tablet then collects its device token. |
| Permanent ID | Android `ANDROID_ID`, which survives reinstalls |
| Updates reach the tablet within a minute | The tablet polls `GET /api/player/manifest` every 60 s, and a heartbeat that sees a new manifest version triggers a sync right away |
| Offline playback | Every file is downloaded and its SHA-256 checked before a new loop goes live; files are cached on the tablet |
| Heartbeat | `POST /api/player/heartbeat` every 60 s with battery, GPS, app version and what's playing now. The screen shows as offline after 180 s (3 missed heartbeats). |
| Proof of play | Each play gets a UUID on the tablet and is queued on disk. `POST /api/player/plays` inserts with `ON CONFLICT DO NOTHING`, so retries are never counted twice. |
| Kiosk mode | Device owner + lock task (see above). Fullscreen portrait, screen kept on, system bars hidden, Back button disabled, can be the Home launcher, starts on boot |
| Crash restart | `PlayerApplication.kt` catches crashes and relaunches the app through a separate restarter process, with an alarm as backup |
| Uploads from Photos | Accepts JPG, PNG, HEIC, MP4 and MOV, including HEVC, HDR and 4K. The upload is kept untouched as the original, in `ORIGINALS_DIR`, which is never served. The dashboard sends the raw file bytes with an `X-Filename` header; multipart uploads with any field name also work. |
| Screen format | Every image, video and text slide becomes a formatted file at exactly 1080 × 1920 with a 12 px white border, and that's all tablets download. **Fit** (the default): content that's already 9:16 (within 2%) fills the frame. Other shapes are shown whole, never stretched or cut, over a blurred, darkened copy of themselves. **Fill**: covers the frame and crops the edges. Switching an item between Fit and Fill reformats it from the original. Text slides are rendered on the server in Inter (SIL OFL, `backend/app/fonts/`), sized to fill the slide. Videos come out as H.264 MP4 at no more than 30 fps, with 48 kHz AAC audio and HDR tone-mapped to SDR. Tablets of another shape (the KB10 is 10:16) show the 9:16 frame whole, padded in white. |
| Approval queue | Only approved media is sent to screens. "Auto-approve my uploads" (on the Media page) controls whether new uploads skip the queue. |

Item timing: each loop item plays for its set seconds (default 10). A video either **loops** to fill that time, or plays **once and is cut** at that time (or ends when the video does, if that comes first).

## Customer website orders

The customer website posts screen ad orders to `POST /api/website/orders`, protected by `WEBSITE_API_KEY`. They appear on the dashboard's **Orders** page, and their ads wait for approval. See [docs/website-orders.md](docs/website-orders.md).

## Security notes

- `backend/.env` holds the admin password and the token-signing key. It is ignored by git; never commit it. If it leaks, change both values and restart the backend.
- On the cloud server, settings come from the host's environment variables, not from a file. The server won't start in production with a short password or the default signing key.
- After 10 wrong passwords from one address in 15 minutes, logins from that address are refused until the 15 minutes pass. After 100 wrong passwords in total, all logins are paused.
- The dashboard and API are served from the same HTTPS address, so no cross-origin access is allowed in production. The CORS list in `backend/app/main.py` only covers the local dev server.
- Uploaded files are served without authentication at `/files/…` so screens can download them. Don't upload anything private.
- Photos are re-encoded without GPS metadata when converted. Original JPG/PNG files without location or rotation data are stored unchanged.

## Tests

```sh
(cd backend && uv run pytest)
(cd player && flutter test)
```

## License

[MIT](LICENSE)
