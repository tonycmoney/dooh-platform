"""Receiving uploads, keeping the original, and producing the formatted file
screens play (see formatting.py for the 1080 x 1920 framed format).

In: JPG, PNG, HEIC/HEIF images and MP4, MOV videos (HEVC, HDR, 4K all fine).
The upload is kept untouched in ORIGINALS_DIR, which is never served, so the
item can be reformatted later. The formatted JPEG or H.264 MP4 goes to
MEDIA_DIR, which tablets download from at /files. It carries no camera
metadata (no GPS).

HDR video is tone-mapped by ffmpeg's zscale where available (the Linux server
image); on a Mac without it, macOS avconvert makes an SDR copy first.
"""

import functools
import hashlib
import json
import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, status
from PIL import UnidentifiedImageError
from pillow_heif import register_heif_opener

from . import formatting
from .config import settings
from .models import FitMode, Media, MediaKind

register_heif_opener()
log = logging.getLogger("dooh.media")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}
SUPPORTED_LABEL = "JPG, PNG, HEIC, MP4 or MOV"
PROBE_TIMEOUT = 60
AVCONVERT_TIMEOUT = 60 * 60


@dataclass
class FormattedFile:
    """The file screens play, plus its thumbnail."""

    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    width: int
    height: int
    duration_seconds: float | None
    thumbnail_filename: str | None


@dataclass
class StoredUpload:
    kind: MediaKind
    formatted: FormattedFile
    source_filename: str
    source_sha256: str
    source_size_bytes: int
    source_width: int
    source_height: int


def media_dir() -> Path:
    return settings.resolved_media_dir()


def originals_dir() -> Path:
    return settings.resolved_originals_dir()


def incoming_dir() -> Path:
    # Next to the originals (private, same disk) so keeping one is a rename.
    path = originals_dir() / ".incoming"
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


# --- Probing ------------------------------------------------------------------


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


def _fps(stream: dict) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        num, _, den = (stream.get(key) or "0/0").partition("/")
        try:
            if float(den or 1):
                return float(num) / float(den or 1)
        except ValueError:
            pass
    return 30.0


def _is_hdr(stream: dict) -> bool:
    return stream.get("color_transfer") in ("smpte2084", "arib-std-b67")


@functools.cache
def _ffmpeg_can_tonemap() -> bool:
    try:
        filters = _run(["ffmpeg", "-hide_banner", "-filters"], PROBE_TIMEOUT).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return all(f" {name} " in filters for name in ("zscale", "tonemap"))


def _source_size(path: Path, kind: MediaKind, original_name: str) -> tuple[int, int]:
    """Upright size of the original; raises a readable 400 if it can't be read."""
    if kind is MediaKind.image:
        try:
            return formatting.open_upright(path).size
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
            log.info("Unreadable image %s: %s", original_name, e)
            raise bad_request(f"“{original_name}” couldn't be read as an image. Is the file complete?")
    stream = _video_stream(_probe(path))
    if stream is None or not all(_display_size(stream)):
        raise bad_request(f"“{original_name}” has no readable video. Is the file complete?")
    return _display_size(stream)


# --- Formatting ---------------------------------------------------------------


def _avconvert_sdr(source: Path) -> Path | None:
    """macOS only: an SDR H.264 copy of an HDR video, for Macs whose ffmpeg
    can't tone-map. None if avconvert is missing or fails."""
    if not shutil.which("avconvert"):
        return None
    target = incoming_dir() / f"{uuid.uuid4().hex}.sdr.mp4"
    try:
        result = _run(["avconvert", "--preset", "Preset1920x1080", "--source", str(source),
                       "--output", str(target), "--replace"], AVCONVERT_TIMEOUT)
        if result.returncode == 0 and target.exists():
            return target
        log.warning("avconvert failed: %s", result.stderr[-500:])
    except subprocess.TimeoutExpired:
        log.warning("avconvert timed out on %s", source.name)
    target.unlink(missing_ok=True)
    return None


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


def _finish(path: Path, kind: MediaKind, duration: float | None) -> FormattedFile:
    return FormattedFile(
        filename=path.name,
        mime_type="video/mp4" if kind is MediaKind.video else "image/jpeg",
        size_bytes=path.stat().st_size,
        sha256=_sha256(path),
        width=formatting.CANVAS_W,
        height=formatting.CANVAS_H,
        duration_seconds=duration,
        thumbnail_filename=_make_thumbnail(path, kind),
    )


def format_file(source: Path, kind: MediaKind, mode: FitMode, title: str) -> FormattedFile:
    """Writes a new formatted file (and thumbnail) for `source` into MEDIA_DIR.
    Raises a readable 400 if the content can't be converted."""
    stem = uuid.uuid4().hex
    if kind is MediaKind.image:
        target = media_dir() / f"{stem}.jpg"
        try:
            formatting.format_image(source, target, mode)
        except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
            target.unlink(missing_ok=True)
            log.info("Unreadable image %s: %s", title, e)
            raise bad_request(f"“{title}” couldn't be read as an image. Is the file complete?")
        return _finish(target, kind, None)

    target = media_dir() / f"{stem}.mp4"
    stream = _video_stream(_probe(source)) or {}
    work, sdr_copy = source, None
    hdr = _is_hdr(stream)
    if hdr and not _ffmpeg_can_tonemap():
        sdr_copy = _avconvert_sdr(source)
        if sdr_copy is not None:
            work, hdr = sdr_copy, False
            stream = _video_stream(_probe(sdr_copy)) or stream
        else:
            hdr = False  # colors will look flat, but it plays
    try:
        width, height = _display_size(stream)
        result = formatting.format_video(work, target, width, height, mode, hdr=hdr, fps=_fps(stream))
    finally:
        if sdr_copy is not None:
            sdr_copy.unlink(missing_ok=True)
    if result is None or result.returncode != 0 or not target.exists():
        log.warning("ffmpeg failed for %s: %s", title, (result.stderr if result else "timeout")[-500:])
        target.unlink(missing_ok=True)
        raise bad_request(f"“{title}” couldn't be converted to a playable video. Is the video complete?")
    try:
        duration = float(_probe(target).get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None
    return _finish(target, kind, duration)


def render_text_file(text: str, text_color: str | None, background_color: str | None) -> FormattedFile:
    target = media_dir() / f"{uuid.uuid4().hex}.jpg"
    formatting.render_text(text, text_color, background_color, target)
    return _finish(target, MediaKind.image, None)


# --- Entry points (run in a worker thread) ------------------------------------


def process_upload(incoming: Path, original_name: str, mode: FitMode = FitMode.fit) -> StoredUpload:
    """Keeps the upload as the original and makes its formatted file. Always
    consumes `incoming`; raises HTTPException(400) on bad input."""
    kind = kind_for(original_name)
    kept: Path | None = None
    try:
        if incoming.stat().st_size == 0:
            raise bad_request(
                f"“{original_name}” is empty. If it's stored in iCloud, open it in Photos "
                "to download it first, or use File → Export in Photos."
            )
        width, height = _source_size(incoming, kind, original_name)
        kept = originals_dir() / f"{uuid.uuid4().hex}{Path(original_name).suffix.lower()}"
        shutil.move(incoming, kept)
        formatted = format_file(kept, kind, mode, original_name)
        return StoredUpload(
            kind=kind,
            formatted=formatted,
            source_filename=kept.name,
            source_sha256=_sha256(kept),
            source_size_bytes=kept.stat().st_size,
            source_width=width,
            source_height=height,
        )
    except BaseException:
        if kept is not None:
            kept.unlink(missing_ok=True)
        raise
    finally:
        incoming.unlink(missing_ok=True)


def apply_formatted(media: Media, formatted: FormattedFile, format_version: int) -> list[str | None]:
    """Points `media` at a new formatted file. Returns the replaced file names,
    to delete once the change is committed."""
    old = [media.filename, media.thumbnail_filename]
    media.filename = formatted.filename
    media.mime_type = formatted.mime_type
    media.size_bytes = formatted.size_bytes
    media.sha256 = formatted.sha256
    media.width = formatted.width
    media.height = formatted.height
    media.duration_seconds = formatted.duration_seconds
    media.thumbnail_filename = formatted.thumbnail_filename
    media.format_version = format_version
    return [name for name in old if name not in (formatted.filename, formatted.thumbnail_filename)]


def reformat(media: Media) -> list[str | None]:
    """Remakes the formatted file from the kept original (or the text). Returns
    the old file names to delete after commit. Raises HTTPException(400)."""
    if media.kind is MediaKind.text:
        formatted = render_text_file(media.text or "", media.text_color, media.background_color)
    else:
        source = originals_dir() / (media.source_filename or "")
        if not media.source_filename or not source.is_file():
            raise bad_request(f"The original of “{media.title}” is missing, so it can't be reformatted.")
        formatted = format_file(source, media.kind, media.fit_mode, media.title)
    return apply_formatted(media, formatted, formatting.FORMAT_VERSION)


def restore_file(source: Path, media: Media, *, original: bool) -> None:
    """Puts back the formatted file (or the original) of `media` if `source`
    is byte-for-byte the recorded file. Raises HTTPException(400) otherwise."""
    filename, sha256 = (media.source_filename, media.source_sha256) if original else (media.filename, media.sha256)
    if not filename or not sha256:
        raise bad_request("This item has no such file.")
    if Path(filename).name != filename or filename.startswith("."):
        raise bad_request("Invalid stored file name.")
    if _sha256(source) != sha256:
        raise bad_request("This isn't the same file: its SHA-256 doesn't match the one recorded.")
    folder = originals_dir() if original else media_dir()
    shutil.move(source, folder / filename)
    if not original:
        _make_thumbnail(folder / filename, media.kind if media.kind is MediaKind.video else MediaKind.image)


def delete_files(*filenames: str | None) -> None:
    for name in filenames:
        if name:
            (media_dir() / name).unlink(missing_ok=True)


def delete_originals(*filenames: str | None) -> None:
    for name in filenames:
        if name:
            (originals_dir() / name).unlink(missing_ok=True)
