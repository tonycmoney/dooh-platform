"""Storing uploads and reading their metadata with ffprobe/ffmpeg."""

import hashlib
import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from .config import settings
from .models import MediaKind

ALLOWED = {
    ".mp4": (MediaKind.video, "video/mp4"),
    ".jpg": (MediaKind.image, "image/jpeg"),
    ".jpeg": (MediaKind.image, "image/jpeg"),
    ".png": (MediaKind.image, "image/png"),
}
# Codecs Android's hardware decoders play reliably.
PLAYABLE_VIDEO_CODECS = {"h264", "hevc"}
CHUNK = 1024 * 1024


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


def media_dir() -> Path:
    return settings.resolved_media_dir()


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, message)


def _probe(path: Path) -> dict:
    if shutil.which("ffprobe") is None:
        return {}
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip()}
    return json.loads(result.stdout)


def _make_thumbnail(source: Path, kind: MediaKind) -> str | None:
    if shutil.which("ffmpeg") is None:
        return None
    thumb_name = f"{source.stem}.thumb.jpg"
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if kind is MediaKind.video:
        cmd += ["-ss", "1"]  # skip a possible black first frame
    cmd += ["-i", str(source), "-frames:v", "1", "-vf", "scale=480:-2", str(source.parent / thumb_name)]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    if result.returncode != 0 and kind is MediaKind.video:
        # Very short clip: take the first frame instead.
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-frames:v", "1",
               "-vf", "scale=480:-2", str(source.parent / thumb_name)]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
    return thumb_name if result.returncode == 0 else None


async def store_upload(upload: UploadFile) -> StoredFile:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise _bad_request("Only MP4 videos and JPG/PNG images are supported.")
    kind, mime = ALLOWED[suffix]

    filename = f"{uuid.uuid4().hex}{'.jpg' if suffix == '.jpeg' else suffix}"
    path = media_dir() / filename
    digest = hashlib.sha256()
    size = 0
    with path.open("wb") as out:
        while chunk := await upload.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
            out.write(chunk)
    if size == 0:
        path.unlink(missing_ok=True)
        raise _bad_request("The file is empty.")

    info = _probe(path)
    if "error" in info:
        path.unlink(missing_ok=True)
        raise _bad_request("This file could not be read. Is it a valid image or video?")

    video_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), None
    )
    width = video_stream.get("width") if video_stream else None
    height = video_stream.get("height") if video_stream else None
    duration = None
    if kind is MediaKind.video:
        if info and video_stream is None:
            path.unlink(missing_ok=True)
            raise _bad_request("This MP4 has no video track.")
        codec = (video_stream or {}).get("codec_name")
        if info and codec not in PLAYABLE_VIDEO_CODECS:
            path.unlink(missing_ok=True)
            raise _bad_request(
                f"This MP4 uses the '{codec}' codec. Please export it as H.264 (or H.265) MP4."
            )
        try:
            duration = float(info.get("format", {}).get("duration"))
        except (TypeError, ValueError):
            duration = None

    return StoredFile(
        kind=kind,
        filename=filename,
        mime_type=mime,
        size_bytes=size,
        sha256=digest.hexdigest(),
        width=width,
        height=height,
        duration_seconds=duration,
        thumbnail_filename=_make_thumbnail(path, kind),
    )


def delete_files(*filenames: str | None) -> None:
    for name in filenames:
        if name:
            (media_dir() / name).unlink(missing_ok=True)
