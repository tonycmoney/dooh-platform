"""Cloud deployment: login throttling, production checks, backups, restoring
media files and serving the dashboard."""

import io
import os
from pathlib import Path

from PIL import Image

from app import backups
from app.config import Settings


def test_wrong_passwords_are_throttled(client):
    for _ in range(10):
        assert client.post("/api/admin/login", json={"password": "guess"}).status_code == 401
    blocked = client.post("/api/admin/login", json={"password": "test-pass"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_successful_login_clears_failures(client):
    for _ in range(9):
        client.post("/api/admin/login", json={"password": "guess"})
    assert client.post("/api/admin/login", json={"password": "test-pass"}).status_code == 200
    for _ in range(9):
        assert client.post("/api/admin/login", json={"password": "guess"}).status_code == 401


def test_production_refuses_weak_settings():
    weak = Settings(environment="production", admin_password="short", secret_key="dev-secret-change-me")
    assert len(weak.production_problems()) == 2
    strong = Settings(environment="production", admin_password="a" * 12, secret_key="k" * 40)
    assert strong.production_problems() == []


def test_host_database_urls_use_psycopg3():
    for url in ("postgres://u:p@db:5432/x", "postgresql://u:p@db:5432/x"):
        s = Settings(database_url=url)
        assert s.database_url == "postgresql+psycopg://u:p@db:5432/x"
        assert s.libpq_database_url == "postgresql://u:p@db:5432/x"


def test_backup_create_list_download(admin):
    made = admin.post("/api/admin/backups")
    assert made.status_code == 201, made.text
    name = made.json()["name"]
    listing = admin.get("/api/admin/backups").json()
    assert [b["name"] for b in listing["backups"]] == [name]
    data = admin.get(f"/api/admin/backups/{name}")
    assert data.status_code == 200 and data.content.startswith(b"PGDMP")
    assert admin.get("/api/admin/backups/..%2F.env").status_code == 404
    assert admin.get("/api/admin/backups/other.dump").status_code == 404


def test_backups_need_login(client):
    assert client.get("/api/admin/backups").status_code == 401


def test_old_backups_are_pruned_but_a_few_kept():
    folder = backups.backup_dir()
    for f in folder.iterdir():
        f.unlink()
    old = 60 * 86400
    for day in range(1, 6):
        path = folder / f"dooh-2020010{day}-000000.dump"
        path.write_bytes(b"x")
        stamp = path.stat().st_mtime - old - day
        os.utime(path, (stamp, stamp))
    assert backups.backup_due()
    backups._prune()
    assert len(backups.list_backups()) == backups.MIN_KEPT


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "red").save(buf, "JPEG")
    return buf.getvalue()


def test_restore_media_file_checks_hash(admin):
    from app.media_files import originals_dir

    body = _jpeg()
    media = admin.post("/api/admin/media", content=body, headers={"X-Filename": "ad.jpg"}).json()
    stored = Path(os.environ["MEDIA_DIR"]) / media["url"].rsplit("/", 1)[1]
    thumb = Path(os.environ["MEDIA_DIR"]) / media["thumbnail_url"].rsplit("/", 1)[1]
    formatted = stored.read_bytes()
    stored.unlink()
    thumb.unlink()

    wrong = admin.put(f"/api/admin/media/{media['id']}/file", content=b"not the same file")
    assert wrong.status_code == 400 and "SHA-256" in wrong.json()["detail"]
    assert not stored.exists()

    ok = admin.put(f"/api/admin/media/{media['id']}/file", content=formatted)
    assert ok.status_code == 200, ok.text
    assert stored.exists() and thumb.exists()

    # The kept original (here, the uploaded JPEG itself) can be restored too.
    original = next(p for p in originals_dir().iterdir() if p.is_file() and p.read_bytes() == body)
    original.unlink()
    assert admin.put(f"/api/admin/media/{media['id']}/file?original=true", content=body).status_code == 200
    assert original.exists()


def test_dashboard_is_served_with_client_routes(client):
    page = client.get("/screens")
    assert page.status_code == 200 and "DOOH Control" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert page.headers["x-frame-options"] == "DENY"
    assert client.get("/api/nope").status_code == 404
    assert client.get("/api/nope").headers["content-type"] == "application/json"
    assert client.get("/files/nope.jpg").status_code == 404

