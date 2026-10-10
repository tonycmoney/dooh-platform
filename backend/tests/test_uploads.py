"""Uploads from a Mac Photos library: HEIC, MOV (incl. 10-bit HEVC HDR-style),
rotated JPEGs with GPS, both upload transports, and clear errors."""

import io
import json
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest
from PIL import Image
from pillow_heif import register_heif_opener

from app.media_files import media_dir

register_heif_opener()


def _probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def _video(path: Path) -> dict:
    return next(s for s in _probe(path)["streams"] if s["codec_type"] == "video")


def raw_upload(client, name: str, data: bytes, content_type: str = "application/octet-stream"):
    return client.post(
        "/api/admin/media",
        content=data,
        headers={"Content-Type": content_type, "X-Filename": quote(name)},
    )


@pytest.fixture(scope="session")
def samples(tmp_path_factory) -> dict[str, bytes]:
    d = tmp_path_factory.mktemp("samples")

    heic = io.BytesIO()
    Image.new("RGB", (640, 480), (200, 40, 40)).save(heic, format="HEIF", quality=80)

    # Phone-style JPEG: stored landscape, EXIF says rotate 90°, has GPS.
    rotated = io.BytesIO()
    img = Image.new("RGB", (400, 200), (0, 120, 255))
    exif = img.getexif()
    exif[0x0112] = 6
    exif[0x8825] = {1: "N", 2: (41.0, 33.0, 30.0)}
    img.save(rotated, format="JPEG", exif=exif)

    plain = io.BytesIO()
    Image.new("RGB", (320, 200), (10, 200, 10)).save(plain, format="JPEG")

    # iPhone-like MOV: HEVC 10-bit, HLG transfer, with audio.
    mov = d / "IMG_0001.MOV"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx265", "-tag:v", "hvc1",
         "-pix_fmt", "yuv420p10le", "-color_trc", "arib-std-b67", "-color_primaries", "bt2020",
         "-colorspace", "bt2020nc", "-x265-params", "log-level=error", "-c:a", "aac", str(mov)],
        check=True,
    )
    # A MOV that's already H.264 (e.g. a screen recording export).
    mov_h264 = d / "clip.mov"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
         "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mov_h264)],
        check=True,
    )
    ready_mp4 = d / "ready.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
         "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(ready_mp4)],
        check=True,
    )
    return {
        "heic": heic.getvalue(),
        "rotated_jpg": rotated.getvalue(),
        "plain_jpg": plain.getvalue(),
        "hevc_mov": mov.read_bytes(),
        "h264_mov": mov_h264.read_bytes(),
        "ready_mp4": ready_mp4.read_bytes(),
    }


def test_heic_becomes_jpg(admin, samples):
    res = raw_upload(admin, "IMG_4521.HEIC", samples["heic"], "image/heic")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == "image" and body["url"].endswith(".jpg")
    assert (body["width"], body["height"]) == (640, 480)
    assert body["converted_from"] == "HEIF → JPG"
    assert body["thumbnail_url"]
    with Image.open(media_dir() / Path(body["url"]).name) as img:
        assert img.format == "JPEG"


def test_rotated_jpeg_is_uprighted_and_gps_stripped(admin, samples):
    body = raw_upload(admin, "portrait.jpg", samples["rotated_jpg"], "image/jpeg").json()
    assert (body["width"], body["height"]) == (200, 400)  # rotation baked in
    with Image.open(media_dir() / Path(body["url"]).name) as img:
        exif = img.getexif()
        assert 0x8825 not in exif and exif.get(0x0112, 1) == 1


def test_plain_jpeg_is_stored_untouched(admin, samples):
    body = raw_upload(admin, "plain.jpg", samples["plain_jpg"], "image/jpeg").json()
    assert body["converted_from"] is None
    assert (media_dir() / Path(body["url"]).name).read_bytes() == samples["plain_jpg"]


def test_hevc_hdr_mov_becomes_h264_mp4(admin, samples):
    res = raw_upload(admin, "IMG_0001.MOV", samples["hevc_mov"], "video/quicktime")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == "video" and body["url"].endswith(".mp4")
    assert body["converted_from"].startswith("MOV (hevc) → MP4")
    assert 1.5 < body["duration_seconds"] < 2.6
    stream = _video(media_dir() / Path(body["url"]).name)
    assert stream["codec_name"] == "h264" and stream["pix_fmt"] in ("yuv420p", "yuvj420p")
    assert stream.get("color_transfer") not in ("arib-std-b67", "smpte2084")


def test_h264_mov_is_rewrapped_as_mp4(admin, samples):
    body = raw_upload(admin, "clip.mov", samples["h264_mov"], "video/quicktime").json()
    assert body["url"].endswith(".mp4") and body["converted_from"]
    assert "mp4" in _probe(media_dir() / Path(body["url"]).name)["format"]["format_name"]


def test_screen_ready_mp4_is_not_reencoded(admin, samples):
    body = raw_upload(admin, "ready.mp4", samples["ready_mp4"], "video/mp4").json()
    assert body["converted_from"] is None
    assert (media_dir() / Path(body["url"]).name).read_bytes() == samples["ready_mp4"]


def test_multipart_accepts_any_field_name(admin, samples):
    for field in ("file", "files", "upload"):
        res = admin.post("/api/admin/media", files={field: ("IMG_1.heic", samples["heic"], "image/heic")})
        assert res.status_code == 201, (field, res.text)


def test_multipart_without_file_explains_itself(admin):
    res = admin.post("/api/admin/media", data={"title": "x"}, files={"note": (None, "not a file")})
    assert res.status_code == 400
    assert "No file was received" in res.json()["detail"]


@pytest.mark.parametrize("name", ["anim.gif", "movie.webm", "doc.pdf", "noextension"])
def test_unsupported_types_get_a_clear_error(admin, name):
    res = raw_upload(admin, name, b"some bytes")
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "isn't supported" in detail and "HEIC" in detail and "MOV" in detail


def test_broken_and_empty_files_are_rejected(admin):
    fake = raw_upload(admin, "fake.jpg", b"\xff\xd8\xff\xe0not really a jpeg")
    assert fake.status_code == 400 and "couldn't be read" in fake.json()["detail"]
    empty = raw_upload(admin, "IMG_9.HEIC", b"")
    assert empty.status_code == 400 and "iCloud" in empty.json()["detail"]
    junk_video = raw_upload(admin, "broken.mov", b"\x00" * 1000)
    assert junk_video.status_code == 400
    assert not list((media_dir() / ".incoming").iterdir())  # temp files cleaned up
