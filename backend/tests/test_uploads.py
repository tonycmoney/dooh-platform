"""Uploads and the screen format: every image, video and text slide becomes a
1080x1920 file with a white border, Fit (whole, over a blurred background) or
Fill (cropped). Originals from a Mac Photos library (HEIC, MOV incl. 10-bit
HEVC HDR) are kept untouched; errors are clear."""

import io
import json
import subprocess
import uuid
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
    # The recommended ad format: 1080x1920 portrait H.264 with 48 kHz AAC.
    ready_mp4 = d / "ready.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "2", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(ready_mp4)],
        check=True,
    )
    # Like the ElevenLabs export that hung the KB10's decoder: odd size,
    # Constrained Baseline, 32 kHz audio.
    odd_mp4 = d / "odd.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=834x1112:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=32000", "-t", "2", "-c:v", "libx264",
         "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-c:a", "aac", str(odd_mp4)],
        check=True,
    )
    return {
        "heic": heic.getvalue(),
        "rotated_jpg": rotated.getvalue(),
        "plain_jpg": plain.getvalue(),
        "hevc_mov": mov.read_bytes(),
        "h264_mov": mov_h264.read_bytes(),
        "ready_mp4": ready_mp4.read_bytes(),
        "odd_mp4": odd_mp4.read_bytes(),
    }


# --- Helpers for checking the formatted frame ---------------------------------


def _formatted(body: dict) -> Path:
    return media_dir() / Path(body["url"]).name


def _frame_png(path: Path, tmp: Path, at: float = 0.5) -> Image.Image:
    """Decoded frame of a formatted video (or the formatted image itself)."""
    if path.suffix == ".jpg":
        return Image.open(path).convert("RGB")
    out = tmp / f"{path.stem}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1", str(out)],
                   check=True)
    return Image.open(out).convert("RGB")


def _is_white(px, tolerance=20) -> bool:
    return all(c >= 255 - tolerance for c in px)


def _close(px, expected, tolerance=24) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(px, expected))


def assert_framed(img: Image.Image) -> None:
    """1080x1920 with a white border on all four edges (sampled 6 px in)."""
    assert img.size == (1080, 1920)
    for x, y in [(6, 6), (540, 6), (1073, 6), (6, 960), (1073, 960), (6, 1913), (540, 1913), (1073, 1913)]:
        assert _is_white(img.getpixel((x, y))), (x, y, img.getpixel((x, y)))


def _original(body: dict) -> bytes:
    """The kept original for this item (looked up by the recorded hash)."""
    from app.db import SessionLocal
    from app.media_files import originals_dir
    from app.models import Media

    with SessionLocal() as db:
        media = db.get(Media, uuid.UUID(body["id"]))
        return (originals_dir() / media.source_filename).read_bytes()


# --- Images -------------------------------------------------------------------


def test_heic_is_formatted_and_original_kept(admin, samples, tmp_path):
    res = raw_upload(admin, "IMG_4521.HEIC", samples["heic"], "image/heic")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == "image" and body["url"].endswith(".jpg")
    assert (body["width"], body["height"]) == (1080, 1920)
    assert (body["source_width"], body["source_height"]) == (640, 480)
    assert body["fit_mode"] == "fit" and "blurred background" in body["format_note"]
    assert body["thumbnail_url"]
    assert _original(body) == samples["heic"]  # untouched, kept privately
    assert_framed(_frame_png(_formatted(body), tmp_path))


def test_landscape_image_fits_whole_over_blurred_background(admin, tmp_path):
    # Bright red 1600x900 picture: shown whole in the middle, with a darkened
    # blurred copy above and below it.
    buf = io.BytesIO()
    Image.new("RGB", (1600, 900), (230, 20, 20)).save(buf, "JPEG", quality=95)
    body = raw_upload(admin, "wide.jpg", buf.getvalue()).json()
    img = _frame_png(_formatted(body), tmp_path)
    assert_framed(img)
    # Content scaled to the inner width: 1056 x 594, centered.
    assert _close(img.getpixel((540, 960)), (230, 20, 20))
    assert _close(img.getpixel((20, 960)), (230, 20, 20))  # whole width, not cropped
    top = img.getpixel((540, 200))
    assert top[0] < 160 and _close(top, (230 * 0.55, 20 * 0.55, 20 * 0.55), 30)  # blurred + darkened


def test_square_image_fit_and_fill(admin, tmp_path):
    # Square with a green center and a blue outer ring that Fill would crop.
    img = Image.new("RGB", (1200, 1200), (20, 40, 220))
    img.paste((40, 200, 40), (300, 300, 900, 900))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    body = raw_upload(admin, "square.png", buf.getvalue()).json()
    assert body["format_note"].startswith("Square 1200×1200")
    fit = _frame_png(_formatted(body), tmp_path)
    assert_framed(fit)
    assert _close(fit.getpixel((20, 960)), (20, 40, 220))  # ring visible at the sides: nothing cut
    assert fit.getpixel((540, 150))[2] < 150  # dark blurred band above

    old_file = _formatted(body)
    filled = admin.patch(f"/api/admin/media/{body['id']}", json={"fit_mode": "fill"}).json()
    assert filled["fit_mode"] == "fill" and filled["url"] != body["url"]
    assert not old_file.exists()  # old formatted version removed
    assert _original(filled) == buf.getvalue()  # original untouched
    fill = _frame_png(_formatted(filled), tmp_path)
    assert_framed(fill)
    assert _close(fill.getpixel((540, 150)), (20, 40, 220))  # covers top to bottom
    assert _close(fill.getpixel((540, 960)), (40, 200, 40))


def test_vertical_image_fills_the_screen(admin, tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (1080, 1920), (250, 200, 0)).save(buf, "PNG")
    body = raw_upload(admin, "flyer.png", buf.getvalue()).json()
    assert "fills the screen" in body["format_note"]
    img = _frame_png(_formatted(body), tmp_path)
    assert_framed(img)
    for x, y in [(20, 20), (1059, 20), (20, 1899), (540, 960)]:
        assert _close(img.getpixel((x, y)), (250, 200, 0)), (x, y)


def test_transparent_png_is_flattened_onto_white(admin, tmp_path):
    buf = io.BytesIO()
    Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)).save(buf, "PNG")
    body = raw_upload(admin, "logo.png", buf.getvalue()).json()
    assert _is_white(_frame_png(_formatted(body), tmp_path).getpixel((540, 960)))


def test_rotated_jpeg_is_uprighted_and_gps_stripped(admin, samples):
    body = raw_upload(admin, "portrait.jpg", samples["rotated_jpg"], "image/jpeg").json()
    assert (body["source_width"], body["source_height"]) == (200, 400)  # rotation applied
    with Image.open(_formatted(body)) as img:
        assert 0x8825 not in img.getexif()


# --- Videos -------------------------------------------------------------------


def test_hevc_hdr_mov_becomes_framed_h264(admin, samples, tmp_path):
    res = raw_upload(admin, "IMG_0001.MOV", samples["hevc_mov"], "video/quicktime")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == "video" and body["url"].endswith(".mp4")
    assert 1.5 < body["duration_seconds"] < 2.6
    assert "Landscape 1280×720" in body["format_note"]
    path = _formatted(body)
    stream = _video(path)
    assert stream["codec_name"] == "h264" and stream["pix_fmt"] == "yuv420p"
    assert (stream["width"], stream["height"]) == (1080, 1920)
    assert stream.get("color_transfer") not in ("arib-std-b67", "smpte2084")
    audio = next(s for s in _probe(path)["streams"] if s["codec_type"] == "audio")
    assert audio["sample_rate"] == "48000"
    assert_framed(_frame_png(path, tmp_path))
    assert _original(body) == samples["hevc_mov"]


def test_vertical_video_fills_inside_the_border(admin, samples, tmp_path):
    body = raw_upload(admin, "ready.mp4", samples["ready_mp4"], "video/mp4").json()
    assert "Vertical 1080×1920: fills the screen" == body["format_note"]
    frame = _frame_png(_formatted(body), tmp_path)
    assert_framed(frame)
    # testsrc2 fills the frame edge to edge: no dark blurred bands inside the border.
    assert sum(frame.getpixel((540, 20))) > 60 and sum(frame.getpixel((540, 1899))) > 60


def test_odd_sized_video_becomes_1080x1920(admin, samples):
    body = raw_upload(admin, "ElevenLabs_video.mp4", samples["odd_mp4"], "video/mp4").json()
    path = _formatted(body)
    assert (_video(path)["width"], _video(path)["height"]) == (1080, 1920)
    audio = next(s for s in _probe(path)["streams"] if s["codec_type"] == "audio")
    assert audio["sample_rate"] == "48000"


def test_portrait_4k_60fps_is_capped_at_30fps(admin, tmp_path):
    src = tmp_path / "IMG_0003.MOV"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=2160x3840:rate=60",
         "-t", "1", "-c:v", "libx265", "-tag:v", "hvc1", "-x265-params", "log-level=error", str(src)],
        check=True,
    )
    body = raw_upload(admin, "IMG_0003.MOV", src.read_bytes(), "video/quicktime").json()
    stream = _video(_formatted(body))
    assert (stream["width"], stream["height"]) == (1080, 1920)
    num, den = stream["avg_frame_rate"].split("/")
    assert abs(int(num) / int(den) - 30) < 0.5


def test_h264_mov_is_rewrapped_as_mp4(admin, samples):
    body = raw_upload(admin, "clip.mov", samples["h264_mov"], "video/quicktime").json()
    assert body["url"].endswith(".mp4")
    assert "mp4" in _probe(_formatted(body))["format"]["format_name"]


# --- Text slides --------------------------------------------------------------


def test_text_slide_is_rendered_framed_and_auto_sized(admin, tmp_path):
    short = admin.post("/api/admin/text-slides", json={
        "title": "Sale", "text": "SALE", "text_color": "#FFFFFF", "background_color": "#0000FF"}).json()
    img = _frame_png(_formatted(short), tmp_path)
    assert_framed(img)
    assert _close(img.getpixel((40, 40)), (0, 0, 255))
    # One short word is set big: its white strokes span a wide part of the middle row.
    row = [img.getpixel((x, 960)) for x in range(12, 1068)]
    white = [i for i, px in enumerate(row) if _is_white(px, 60)]
    assert white and white[-1] - white[0] > 600

    long_text = " ".join(["Fresh bread and pastries every morning"] * 12)
    long = admin.post("/api/admin/text-slides", json={
        "title": "Long", "text": long_text, "text_color": "#000000", "background_color": "#FFFFAA"}).json()
    assert_framed(_frame_png(_formatted(long), tmp_path))

    updated = admin.put(f"/api/admin/text-slides/{short['id']}", json={
        "title": "Sale", "text": "SALE\nToday only", "text_color": "#FFFFFF", "background_color": "#008000"}).json()
    assert updated["url"] != short["url"] and not _formatted(short).exists()

    preview = admin.post("/api/admin/text-slides/preview", json={
        "title": "x", "text": "Hello", "text_color": "#FFFFFF", "background_color": "#000000"})
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(preview.content)) as p:
        assert p.size == (1080, 1920)

    assert admin.patch(f"/api/admin/media/{short['id']}", json={"fit_mode": "fill"}).status_code == 400


def test_delete_removes_formatted_and_original(admin, samples):
    body = raw_upload(admin, "plain.jpg", samples["plain_jpg"], "image/jpeg").json()
    from app.media_files import originals_dir

    before = {p.name for p in originals_dir().iterdir() if p.is_file()}
    formatted = _formatted(body)
    assert admin.delete(f"/api/admin/media/{body['id']}").status_code == 204
    after = {p.name for p in originals_dir().iterdir() if p.is_file()}
    assert not formatted.exists() and len(before - after) == 1


def test_reformat_command_upgrades_old_items(admin, samples, monkeypatch, capsys):
    """Items stored before formatting existed adopt their file as the original."""
    import sys

    from app import reformat
    from app.db import SessionLocal
    from app.models import Media, MediaKind

    legacy = media_dir() / "legacy.jpg"
    legacy.write_bytes(samples["plain_jpg"])
    with SessionLocal() as db:
        db.add(Media(kind=MediaKind.image, title="Old ad", status="approved", filename="legacy.jpg",
                     sha256="x", width=320, height=200))
        db.add(Media(kind=MediaKind.text, title="Old slide", status="approved", text="Hi",
                     text_color="#FFFFFF", background_color="#000000"))
        db.commit()
    monkeypatch.setattr(sys, "argv", ["reformat"])
    assert reformat.main() == 0
    with SessionLocal() as db:
        for media in db.query(Media).all():
            assert media.format_version is not None and (media.width, media.height) == (1080, 1920)
            assert (media_dir() / media.filename).is_file()
    assert not legacy.exists()  # old stored file replaced by the formatted one
    assert "2 of 2 items to format" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["reformat"])
    assert reformat.main() == 0 and "0 of 2" in capsys.readouterr().out


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
    from app.media_files import incoming_dir

    assert not list(incoming_dir().iterdir())  # temp files cleaned up
