"""Receiving uploads and normalizing them into files every screen can play.

Images: JPG, PNG, HEIC/HEIF in; JPG or PNG out. HEIC is converted to JPG,
the camera's rotation is applied to the pixels, and location metadata is
stripped from anything that gets re-encoded.

Videos: MP4 and MOV in; H.264 MP4 (max 1920x1080, SDR) out. Files that are
already in that form are stored untouched; anything else (MOV, HEVC, 10-bit
HDR from iPhones, 4K, ...) is converted with macOS avconvert when available,
otherwise with ffmpeg.
"""

import hashlib
import json
import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, status
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from .config import settings
from .models import MediaKind

register_heif_opener()
log = logging.getLogger("dooh.media")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}
SUPPORTED_LABEL = "JPG, PNG, HEIC, MP4 or MOV"

MAX_IMAGE_SIDE = 3840  # larger photos are scaled down (tablets don't need 48 MP)
MAX_VIDEO_W, MAX_VIDEO_H = 1920, 1080
PROBE_TIMEOUT = 60
CONVERT_TIMEOUT = 60 * 60  # long 4K videos can take a while


@dataclass
class StoredFile:
    kind: MediaKind
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    width: int | None
    height: int | None
    duration_seconds: float | None
    thumbnail_filename: str | None
    converted_from: str | None = None


def media_dir() -> Path:
    return settings.resolved_media_dir()


def incoming_dir() -> Path:
    path = media_dir() / ".incoming"
    path.mkdir(exist_ok=True)
    return path


def bad_request(message: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, message)


def kind_for(filename: str) -> MediaKind:
    """Validates the extension; raises a readable 400 for anything else."""
    suffix = Path(filename).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return MediaKind.image
    if suffix in VIDEO_EXTENSIONS:
        return MediaKind.video
    shown = suffix.lstrip(".").upper() or "files without an extension"
    raise bad_request(f"“{filename}”: {shown} isn't supported. Upload {SUPPORTED_LABEL}.")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# --- Images -------------------------------------------------------------------


def _process_image(source: Path, original_name: str) -> tuple[Path, str, int, int, str | None]:
    suffix = Path(original_name).suffix.lower()
    try:
        with Image.open(source) as img:
            img.load()  # fully decode: rejects truncated or fake files
            exif = img.getexif()
            orientation = exif.get(0x0112, 1)
            has_gps = 0x8825 in exif
            too_big = max(img.size) > MAX_IMAGE_SIDE
            is_heif = img.format in ("HEIF", "HEIC") or suffix in (".heic", ".heif")

            if not (is_heif or orientation != 1 or has_gps or too_big):
                ext = ".png" if img.format == "PNG" else ".jpg"
                mime = "image/png" if ext == ".png" else "image/jpeg"
                return source, mime, img.width, img.height, None

            out = ImageOps.exif_transpose(img)  # bake rotation into pixels
            if too_big:
                out.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.Resampling.LANCZOS)
            keep_png = img.format == "PNG"
            target = source.with_suffix(".png" if keep_png else ".jpg")
            if keep_png:
                out.save(target, "PNG", optimize=True)
            else:
                if out.mode not in ("RGB", "L"):
                    out = out.convert("RGB")
                # No exif passed: drops GPS and other camera metadata.
                out.save(target, "JPEG", quality=90, optimize=True, progressive=True)
            converted = f"{img.format or suffix.lstrip('.').upper()} → {'PNG' if keep_png else 'JPG'}"
            return target, "image/png" if keep_png else "image/jpeg", out.width, out.height, converted
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        log.info("Unreadable image %s: %s", original_name, e)
        raise bad_request(f"“{original_name}” couldn't be read as an image. Is the file complete?")


# --- Videos -------------------------------------------------------------------


def _probe(path: Path) -> dict:
    result = _run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        PROBE_TIMEOUT,
    )
    if result.returncode != 0:
        return {}
    return json.loads(result.stdout)


def _video_stream(info: dict) -> dict | None:
    return next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)


def _display_size(stream: dict) -> tuple[int, int]:
    w, h = stream.get("width") or 0, stream.get("height") or 0
    rotation = 0
    for side in stream.get("side_data_list", []):
        rotation = int(side.get("rotation", rotation) or 0)
    return (h, w) if abs(rotation) % 180 == 90 else (w, h)


def _is_screen_ready(path: Path, info: dict) -> bool:
    """H.264, 8-bit 4:2:0, SDR, MP4 container, within 1080p."""
    stream = _video_stream(info)
    if stream is None:
        return False
    w, h = _display_size(stream)
    return (
        path.suffix.lower() == ".mp4"
        and "mp4" in info.get("format", {}).get("format_name", "")
        and stream.get("codec_name") == "h264"
        and stream.get("pix_fmt") in ("yuv420p", "yuvj420p")
        and stream.get("color_transfer") not in ("smpte2084", "arib-std-b67")
        and max(w, h) <= MAX_VIDEO_W
        and min(w, h) <= MAX_VIDEO_H
    )


def _convert_video(source: Path, original_name: str) -> Path:
    target = source.with_name(f"{source.stem}.converted.mp4")
    attempts: list[list[str]] = []
    if shutil.which("avconvert"):
        # Apple's exporter: H.264, fits 1920x1080, HDR tone-mapped to SDR,
        # rotation applied, location metadata removed.
        attempts.append(["avconvert", "--preset", "Preset1920x1080", "--source", str(source),
                         "--output", str(target), "--replace"])
    scale = (f"scale='min({MAX_VIDEO_W},iw)':'min({MAX_VIDEO_H},ih)':"
             "force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p")
    attempts.append(["ffmpeg", "-y", "-v", "error", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
                     "-vf", scale, "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                     "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                     "-map_metadata", "-1", str(target)])

    for cmd in attempts:
        target.unlink(missing_ok=True)
        try:
            result = _run(cmd, CONVERT_TIMEOUT)
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0 and target.exists():
            stream = _video_stream(_probe(target))
            if stream and stream.get("codec_name") == "h264":
                return target
        log.warning("%s failed for %s: %s", cmd[0], original_name, (result.stderr or "")[-500:])
    target.unlink(missing_ok=True)
    raise bad_request(f"“{original_name}” couldn't be converted to a playable MP4. Is the video complete?")


def _process_video(source: Path, original_name: str) -> tuple[Path, float | None, int, int, str | None]:
    info = _probe(source)
    if _video_stream(info) is None:
        raise bad_request(f"“{original_name}” has no readable video. Is the file complete?")
    converted = None
    if not _is_screen_ready(source, info):
        stream = _video_stream(info) or {}
        before = f"{Path(original_name).suffix.lstrip('.').upper()} ({stream.get('codec_name', '?')})"
        source = _convert_video(source, original_name)
        info = _probe(source)
        converted = f"{before} → MP4 (H.264)"
    stream = _video_stream(info) or {}
    w, h = _display_size(stream)
    try:
        duration = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    return source, duration, w, h, converted


def _make_thumbnail(source: Path, kind: MediaKind) -> str | None:
    thumb_name = f"{source.stem}.thumb.jpg"
    out = str(source.parent / thumb_name)
    base = ["ffmpeg", "-y", "-v", "error"]
    tail = ["-frames:v", "1", "-vf", "scale=480:-2", out]
    if kind is MediaKind.video:
        # Skip a possible black first frame; fall back to frame 0 for short clips.
        for seek in (["-ss", "1"], []):
            if _run(base + seek + ["-i", str(source)] + tail, PROBE_TIMEOUT).returncode == 0:
                return thumb_name
        return None
    return thumb_name if _run(base + ["-i", str(source)] + tail, PROBE_TIMEOUT).returncode == 0 else None


# --- Entry point (runs in a worker thread) ------------------------------------


def process_upload(incoming: Path, original_name: str) -> StoredFile:
    """Turns a received file into a stored, screen-ready media file. Always
    removes the incoming file; raises HTTPException(400) on bad input."""
    kind = kind_for(original_name)
    produced: list[Path] = []
    try:
        if incoming.stat().st_size == 0:
            raise bad_request(
                f"“{original_name}” is empty. If it's stored in iCloud, open it in Photos "
                "to download it first, or use File → Export in Photos."
            )
        if kind is MediaKind.image:
            result, mime, width, height, converted = _process_image(incoming, original_name)
            duration = None
        else:
            result, duration, width, height, converted = _process_video(incoming, original_name)
            mime = "video/mp4"
        produced.append(result)

        final_name = f"{uuid.uuid4().hex}{result.suffix.lower()}"
        final = media_dir() / final_name
        shutil.move(result, final)
        produced.append(final)
        return StoredFile(
            kind=kind,
            filename=final_name,
            mime_type=mime,
            size_bytes=final.stat().st_size,
            sha256=_sha256(final),
            width=width or None,
            height=height or None,
            duration_seconds=duration,
            thumbnail_filename=_make_thumbnail(final, kind),
            converted_from=converted,
        )
    except BaseException:
        for path in produced:
            path.unlink(missing_ok=True)
        raise
    finally:
        for path in incoming.parent.glob(f"{incoming.stem}*"):
            path.unlink(missing_ok=True)


def delete_files(*filenames: str | None) -> None:
    for name in filenames:
        if name:
            (media_dir() / name).unlink(missing_ok=True)
