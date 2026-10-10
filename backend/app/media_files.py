"""Receiving uploads and normalizing them into files every screen can play.

Images: JPG, PNG, HEIC/HEIF in; JPG or PNG out. HEIC is converted to JPG,
the camera's rotation is applied to the pixels, and location metadata is
stripped from anything that gets re-encoded.

Videos: MP4 and MOV in; H.264 MP4 out, at most 1080 px on the short side and
1920 on the long side (portrait or landscape), SDR, with dimensions that budget
tablet decoders accept. Files already in that form are stored untouched.
HDR/HEVC sources go through macOS avconvert (proper tone mapping) when
available; anything still not screen-ready is re-encoded by ffmpeg at an exact,
decoder-friendly size.
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
MAX_VIDEO_LONG, MAX_VIDEO_SHORT = 1920, 1080
SAFE_AUDIO_RATES = {44100, 48000}
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


def _decoder_friendly(n: int) -> bool:
    # Allwinner-class hardware decoders hang on frame sizes that aren't a
    # multiple of 16 (1080 is the common, well-supported exception).
    return n % 16 == 0 or n == 1080


def _is_hdr(stream: dict) -> bool:
    return stream.get("color_transfer") in ("smpte2084", "arib-std-b67")


def _is_screen_ready(path: Path, info: dict) -> bool:
    """H.264 8-bit 4:2:0 SDR in MP4, within 1080x1920 either way round, with
    decoder-friendly dimensions and a standard audio sample rate."""
    stream = _video_stream(info)
    if stream is None:
        return False
    w, h = stream.get("width") or 0, stream.get("height") or 0
    audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    return (
        path.suffix.lower() == ".mp4"
        and "mp4" in info.get("format", {}).get("format_name", "")
        and stream.get("codec_name") == "h264"
        and stream.get("pix_fmt") in ("yuv420p", "yuvj420p")
        and not _is_hdr(stream)
        and max(w, h) <= MAX_VIDEO_LONG
        and min(w, h) <= MAX_VIDEO_SHORT
        and _decoder_friendly(w)
        and _decoder_friendly(h)
        and all(int(a.get("sample_rate") or 0) in SAFE_AUDIO_RATES and a.get("codec_name") == "aac" for a in audio)
    )


def _target_size(w: int, h: int) -> tuple[int, int]:
    """Fit within 1920 (long) x 1080 (short), never upscale, multiples of 16."""
    scale = min(1.0, MAX_VIDEO_LONG / max(w, h), MAX_VIDEO_SHORT / min(w, h))
    tw, th = int(w * scale) // 16 * 16, int(h * scale) // 16 * 16
    return max(tw, 16), max(th, 16)


def _avconvert(source: Path, original_name: str) -> Path | None:
    """Apple's exporter: H.264 within 1920x1080 (keeps portrait), HDR
    tone-mapped to SDR, rotation applied, location metadata removed."""
    if not shutil.which("avconvert"):
        return None
    target = source.with_name(f"{source.stem}.av.mp4")
    try:
        result = _run(["avconvert", "--preset", "Preset1920x1080", "--source", str(source),
                       "--output", str(target), "--replace"], CONVERT_TIMEOUT)
    except subprocess.TimeoutExpired:
        result = None
    if result is not None and result.returncode == 0 and target.exists():
        return target
    log.warning("avconvert failed for %s: %s", original_name, (result.stderr if result else "timeout")[-500:])
    target.unlink(missing_ok=True)
    return None


def _ffmpeg_encode(source: Path, info: dict, original_name: str) -> Path:
    w, h = _display_size(_video_stream(info) or {})
    tw, th = _target_size(w, h)
    target = source.with_name(f"{source.stem}.ff.mp4")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
           "-vf", f"scale={tw}:{th}:flags=lanczos,setsar=1,format=yuv420p",
           "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-preset", "medium", "-crf", "20",
           "-c:a", "aac", "-ar", "48000", "-b:a", "160k", "-movflags", "+faststart",
           "-map_metadata", "-1", str(target)]
    try:
        result = _run(cmd, CONVERT_TIMEOUT)
        ok = result.returncode == 0 and target.exists()
    except subprocess.TimeoutExpired:
        result, ok = None, False
    if not ok:
        log.warning("ffmpeg failed for %s: %s", original_name, (result.stderr if result else "timeout")[-500:])
        target.unlink(missing_ok=True)
        raise bad_request(f"“{original_name}” couldn't be converted to a playable MP4. Is the video complete?")
    return target


def _convert_video(source: Path, info: dict, original_name: str) -> Path:
    stream = _video_stream(info) or {}
    current, current_info = source, info
    if _is_hdr(stream) or stream.get("codec_name") != "h264":
        converted = _avconvert(source, original_name)
        if converted is not None:
            current, current_info = converted, _probe(converted)
    if not _is_screen_ready(current, current_info):
        current = _ffmpeg_encode(current, current_info, original_name)
    return current


def _process_video(source: Path, original_name: str) -> tuple[Path, float | None, int, int, str | None]:
    info = _probe(source)
    if _video_stream(info) is None:
        raise bad_request(f"“{original_name}” has no readable video. Is the file complete?")
    converted = None
    if not _is_screen_ready(source, info):
        stream = _video_stream(info) or {}
        before = f"{Path(original_name).suffix.lstrip('.').upper()} ({stream.get('codec_name', '?')})"
        source = _convert_video(source, info, original_name)
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
