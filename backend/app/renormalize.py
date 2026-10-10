"""Re-process stored videos that aren't screen-ready under the current rules.

    uv run python -m app.renormalize            # fix what needs fixing
    uv run python -m app.renormalize --dry-run  # only list it

Loops keep pointing at the same media; the file, checksum and size change, so
the manifest version changes and screens download the new file automatically.
"""

import argparse
import shutil
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from .db import SessionLocal
from .media_files import _is_screen_ready, _probe, delete_files, incoming_dir, media_dir, process_upload
from .models import Media, MediaKind


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        videos = db.scalars(select(Media).where(Media.kind == MediaKind.video)).all()
        for media in videos:
            path = media_dir() / (media.filename or "")
            if not path.is_file():
                print(f"missing file: {media.title}")
                continue
            if _is_screen_ready(path, _probe(path)):
                continue
            print(f"needs re-encoding: {media.title} ({media.width}x{media.height})")
            if args.dry_run:
                continue
            incoming = incoming_dir() / f"{uuid.uuid4().hex}{path.suffix}"
            shutil.copyfile(path, incoming)
            try:
                stored = process_upload(incoming, f"{media.title}{path.suffix}")
            except HTTPException as e:
                print(f"  failed: {e.detail}")
                continue
            old_files = (media.filename, media.thumbnail_filename)
            media.filename = stored.filename
            media.size_bytes = stored.size_bytes
            media.sha256 = stored.sha256
            media.width, media.height = stored.width, stored.height
            media.duration_seconds = stored.duration_seconds
            media.thumbnail_filename = stored.thumbnail_filename
            db.commit()
            delete_files(*old_files)
            print(f"  done: now {stored.width}x{stored.height} ({stored.converted_from})")


if __name__ == "__main__":
    main()
