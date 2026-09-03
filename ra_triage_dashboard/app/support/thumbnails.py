"""Thumbnails HTTP helpers."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from ..contracts import MAX_REVIEW_ATTACHMENT_PIXELS
from ..runtime import settings


def _thumbnail_cache_path(issue_id: str, source: Path) -> Path:
    stat = source.stat()
    fingerprint = (
        f"{issue_id}\0{source}\0{stat.st_mtime_ns}\0{stat.st_size}"
    ).encode("utf-8")
    digest = hashlib.sha256(fingerprint).hexdigest()
    return settings.case_thumbnails_dir / f"{digest}.jpg"

def _render_case_thumbnail(source: Path, destination: Path) -> None:
    """Generate a small gallery JPEG quickly.

    Homepage loads many thumbs at once; prefer BILINEAR + modest size over
    LANCZOS on full 2K BEV frames so cold cache misses stay interactive.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    thumb_size = (480, 270)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.width * image.height > MAX_REVIEW_ATTACHMENT_PIXELS:
            raise ValueError("BEV 图片像素数过大。")
        if image.mode != "RGB":
            image = image.convert("RGB")
        # Draft first for very large sources, then final contain — much faster
        # than LANCZOS on 2560x1440 for gallery cards.
        if image.width > 1280 or image.height > 720:
            image.thumbnail((1280, 720), resample=Image.Resampling.BILINEAR)
        contained = ImageOps.contain(
            image,
            thumb_size,
            method=Image.Resampling.BILINEAR,
        )
        canvas = Image.new("RGB", thumb_size, color=(11, 18, 32))
        canvas.paste(
            contained,
            ((thumb_size[0] - contained.width) // 2, (thumb_size[1] - contained.height) // 2),
        )
        temp_path = destination.with_name(
            f".{destination.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            canvas.save(
                temp_path,
                format="JPEG",
                quality=72,
                optimize=True,
                progressive=True,
            )
            temp_path.replace(destination)
        finally:
            temp_path.unlink(missing_ok=True)
