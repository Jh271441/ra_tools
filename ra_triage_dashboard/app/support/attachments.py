"""Attachments HTTP helpers."""

from __future__ import annotations

import asyncio
import hashlib
import io
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from ..contracts import (
    MAX_REVIEW_ATTACHMENT_BYTES,
    MAX_REVIEW_ATTACHMENT_PIXELS,
    MAX_REVIEW_ATTACHMENT_STORAGE_BYTES,
    MAX_REVIEW_ATTACHMENTS,
    MAX_REVIEW_ATTACHMENTS_TOTAL_BYTES,
    MIN_REVIEW_ATTACHMENT_DISK_FREE,
)
from ..filenames import safe_filename as _safe_filename
from ..runtime import _public_path, database, review_image_semaphore, settings
from .common import _detail


def _normalise_review_image(content: bytes) -> tuple[bytes, str, str, int, int]:
    try:
        with Image.open(io.BytesIO(content)) as source:
            source.seek(0)
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_REVIEW_ATTACHMENT_PIXELS:
                raise _detail(400, "截图尺寸非法或像素数超过 4000 万。")
            image = ImageOps.exif_transpose(source)
            width, height = image.size
            image_format = (source.format or "").upper()
            output = io.BytesIO()
            if image_format == "PNG":
                if image.mode not in {"1", "L", "LA", "P", "RGB", "RGBA"}:
                    image = image.convert("RGBA")
                image.save(output, format="PNG", optimize=True)
                media_type, suffix = "image/png", ".png"
            elif image_format in {"JPEG", "JPG"}:
                if image.mode != "RGB":
                    image = image.convert("RGB")
                image.save(output, format="JPEG", quality=92, optimize=True)
                media_type, suffix = "image/jpeg", ".jpg"
            elif image_format == "WEBP":
                if image.mode not in {"RGB", "RGBA"}:
                    image = image.convert("RGBA")
                image.save(output, format="WEBP", quality=92, method=4)
                media_type, suffix = "image/webp", ".webp"
            else:
                raise _detail(400, "截图仅支持 PNG、JPEG 或 WebP。")
            normalized = output.getvalue()
    except HTTPException:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        raise _detail(400, "截图无法解码或文件已损坏。")
    if not normalized or len(normalized) > MAX_REVIEW_ATTACHMENT_BYTES:
        raise _detail(413, "规范化后的单张截图不能超过 8 MB。")
    return normalized, media_type, suffix, width, height

async def _store_review_attachments(
    uploads: list[UploadFile],
) -> tuple[list[dict[str, Any]], list[Path]]:
    return await _store_image_attachments(
        uploads,
        destination=settings.review_attachments_dir,
        noun="截图",
    )

async def _store_comment_attachments(
    uploads: list[UploadFile],
) -> tuple[list[dict[str, Any]], list[Path]]:
    return await _store_image_attachments(
        uploads,
        destination=settings.comment_attachments_dir,
        noun="评论图片",
    )

async def _store_image_attachments(
    uploads: list[UploadFile],
    *,
    destination: Path,
    noun: str,
) -> tuple[list[dict[str, Any]], list[Path]]:
    if len(uploads) > MAX_REVIEW_ATTACHMENTS:
        raise _detail(400, f"每次最多添加 {MAX_REVIEW_ATTACHMENTS} 张{noun}。")
    prepared: list[tuple[dict[str, Any], bytes]] = []
    raw_total_bytes = 0
    total_bytes = 0
    for upload in uploads:
        content = await upload.read(MAX_REVIEW_ATTACHMENT_BYTES + 1)
        if not content:
            raise _detail(400, f"{noun}文件为空。")
        if len(content) > MAX_REVIEW_ATTACHMENT_BYTES:
            raise _detail(413, "单张截图不能超过 8 MB。")
        raw_total_bytes += len(content)
        if raw_total_bytes > MAX_REVIEW_ATTACHMENTS_TOTAL_BYTES:
            raise _detail(413, "本次截图总大小不能超过 24 MB。")
        async with review_image_semaphore:
            normalized, media_type, suffix, width, height = await asyncio.to_thread(
                _normalise_review_image,
                content,
            )
        total_bytes += len(normalized)
        if total_bytes > MAX_REVIEW_ATTACHMENTS_TOTAL_BYTES:
            raise _detail(413, "本次截图总大小不能超过 24 MB。")
        attachment_id = str(uuid.uuid4())
        stored_name = f"{attachment_id[:2]}/{attachment_id}{suffix}"
        prepared.append(
            (
                {
                    "id": attachment_id,
                    "original_name": _safe_filename(
                        upload.filename or f"clipboard{suffix}"
                    ),
                    "stored_name": stored_name,
                    "media_type": media_type,
                    "size_bytes": len(normalized),
                    "width": width,
                    "height": height,
                    "sha256": hashlib.sha256(normalized).hexdigest(),
                },
                normalized,
            )
        )

    return await asyncio.to_thread(
        _persist_image_attachments,
        prepared,
        total_bytes,
        destination,
        noun,
    )

def _persist_image_attachments(
    prepared: list[tuple[dict[str, Any], bytes]],
    total_bytes: int,
    destination: Path,
    noun: str,
) -> tuple[list[dict[str, Any]], list[Path]]:
    """Persist normalized Review/comment images outside the asyncio event loop."""

    root = destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (
        prepared
        and database.image_attachment_storage_bytes() + total_bytes
        > MAX_REVIEW_ATTACHMENT_STORAGE_BYTES
    ):
        raise _detail(507, f"{noun}已达到 20 GB 存储配额，请联系管理员清理或扩容。")
    if prepared and shutil.disk_usage(root).free < total_bytes + MIN_REVIEW_ATTACHMENT_DISK_FREE:
        raise _detail(507, "截图存储空间不足，请联系管理员。")
    temp_paths: list[Path] = []
    final_paths: list[Path] = []
    try:
        for record, content in prepared:
            stored_name = str(record["stored_name"])
            path = (destination / stored_name).resolve()
            if root not in path.parents:
                raise _detail(400, "截图存储路径非法。")
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            temp_path.write_bytes(content)
            temp_paths.append(temp_path)
            final_paths.append(path)
        for temp_path, final_path in zip(temp_paths, final_paths):
            temp_path.replace(final_path)
    except Exception:
        for path in [*temp_paths, *final_paths]:
            path.unlink(missing_ok=True)
        raise
    return [record for record, _ in prepared], final_paths

def _public_review_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": attachment["id"],
        "media_type": attachment["media_type"],
        "size_bytes": int(attachment["size_bytes"]),
        "width": int(attachment["width"]),
        "height": int(attachment["height"]),
        "created_at": attachment.get("created_at"),
        "url": _public_path(f"/api/review-attachments/{attachment['id']}"),
    }

def _public_comment_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": attachment["id"],
        "media_type": attachment["media_type"],
        "size_bytes": int(attachment["size_bytes"]),
        "width": int(attachment["width"]),
        "height": int(attachment["height"]),
        "created_at": attachment.get("created_at"),
        "url": _public_path(f"/api/comment-attachments/{attachment['id']}"),
    }
