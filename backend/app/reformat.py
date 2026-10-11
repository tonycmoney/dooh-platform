"""Brings every media item to the current screen format.

    uv run python -m app.reformat            # items not yet in the current format
    uv run python -m app.reformat --all      # every item
    uv run python -m app.reformat --dry-run  # list what would change

Items uploaded before originals were kept adopt their stored file as the
original. Each item is committed on its own, and its old formatted file is
deleted only after that, so screens keep playing throughout and pick up the
new versions on their next sync.
"""

import argparse
import shutil
import sys
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select

from .db import SessionLocal
from .formatting import FORMAT_VERSION
from .media_files import _sha256, _source_size, delete_files, media_dir, originals_dir, reformat
from .models import Media, MediaKind


def adopt_stored_file_as_original(media: Media) -> None:
    stored = media_dir() / (media.filename or "")
    if not media.filename or not stored.is_file():
        raise HTTPException(400, "its stored file is missing")
    kept = originals_dir() / f"{uuid.uuid4().hex}{stored.suffix.lower()}"
    shutil.copy2(stored, kept)
    media.source_filename = kept.name
    media.source_sha256 = _sha256(kept)
    media.source_size_bytes = kept.stat().st_size
    media.source_width, media.source_height = _source_size(kept, media.kind, media.title)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="reformat every item, not just outdated ones")
    parser.add_argument("--dry-run", action="store_true", help="only list the items")
    args = parser.parse_args()

    failed = 0
    with SessionLocal() as db:
        items = db.scalars(select(Media).order_by(Media.created_at)).all()
        todo = [m for m in items if args.all or m.format_version != FORMAT_VERSION]
        print(f"{len(todo)} of {len(items)} items to format")
        for media in todo:
            print(f"- {media.kind.value:5} {media.title}", end="", flush=True)
            if args.dry_run:
                print()
                continue
            try:
                if media.kind is not MediaKind.text and not media.source_filename:
                    adopt_stored_file_as_original(media)
                old_files = reformat(media)
                db.commit()
            except HTTPException as e:
                db.rollback()
                failed += 1
                print(f"  FAILED: {e.detail}")
                continue
            delete_files(*old_files)
            print(f"  -> {media.filename} ({media.size_bytes / 1e6:.1f} MB)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
