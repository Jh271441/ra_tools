from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import math
import re
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

import openpyxl
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError

from .assets import AssetIndex, CameraIndex
from .auth import normalise_username, request_identity
from .baseline import load_label_baseline
from .batch_prediction_runner import BatchPredictionRunner
from .db import LABELS, REVIEW_STATUSES, Database
from .sanitization import redact_sensitive_fields
from .settings import Settings
from .trail_sync import TRAIL_INFO_FIELD, TRAIL_RESULT_FIELD, read_trail_model_fields


settings = Settings.from_env()
database = Database(settings.db_path)
asset_index = AssetIndex(
    ra_root=settings.ra_auto_triage_root,
    manifest_path=settings.ares_manifest,
)
camera_index = CameraIndex(settings.camera_root)
batch_prediction_runner = BatchPredictionRunner(settings, database)
trail_sync_lock = threading.Lock()
review_image_semaphore = asyncio.Semaphore(2)

ISSUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,128}$")
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_REVIEW_ATTACHMENTS = 4
MAX_REVIEW_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_REVIEW_ATTACHMENTS_TOTAL_BYTES = 24 * 1024 * 1024
MAX_REVIEW_MULTIPART_REQUEST_BYTES = 26 * 1024 * 1024
MAX_REVIEW_ATTACHMENT_PIXELS = 40_000_000
MAX_REVIEW_ATTACHMENT_STORAGE_BYTES = 20 * 1024 * 1024 * 1024
MIN_REVIEW_ATTACHMENT_DISK_FREE = 256 * 1024 * 1024

MISSING_EVIDENCE_CATALOG: tuple[dict[str, str], ...] = (
    {"key": "routing_direction", "label": "routing 方向", "hint": "未理解自车目标转向 / 车道任务"},
    {"key": "passable_space", "label": "可绕行空间", "hint": "未判断右侧/相邻车道是否可安全通过"},
    {"key": "hazard_signal", "label": "异常停车信号", "hint": "双闪、故障或临停迹象缺失"},
    {"key": "traffic_light_state", "label": "灯态与周期", "hint": "红绿灯当前状态或后续放行证据缺失"},
    {"key": "stop_line_crosswalk", "label": "停止线 / 路口结构", "hint": "停止线、斑马线和路口语义缺失"},
    {"key": "queue_vs_blocking", "label": "排队 vs 实质阻塞", "hint": "未区分正常车流等待与异常物理阻塞"},
    {"key": "yielding_target", "label": "yielding 目标", "hint": "前方关键车辆 / 摩自关系识别不足"},
    {"key": "post_trigger_recovery", "label": "触发后恢复", "hint": "未利用触发后的移动、通行或绕行结果"},
    {"key": "ra_swag_action", "label": "RA / SWAG 操作链", "hint": "未核验 RA 协助后实际动作与效果"},
    {"key": "temporal_evidence", "label": "时序证据", "hint": "单帧判断，缺少前后帧变化"},
    {"key": "camera_view", "label": "Camera 证据", "hint": "需要相机视角确认交通灯、双闪或可通行性"},
    {"key": "bev_topology", "label": "BEV 拓扑", "hint": "需要 BEV 复核车道、障碍物和绕行关系"},
    {"key": "gt_needs_review", "label": "GT 需复核", "hint": "模型并非明显错，真值或边界定义待确认"},
)

REVIEW_TAG_CATALOG: tuple[dict[str, str], ...] = (
    {"key": "left_turn", "label": "左转"},
    {"key": "right_turn", "label": "右转"},
    {"key": "straight", "label": "直行"},
    {"key": "traffic_light", "label": "信号灯"},
    {"key": "queue", "label": "排队"},
    {"key": "temporary_stop", "label": "双闪 / 临停 / 故障车"},
    {"key": "occlusion", "label": "遮挡"},
    {"key": "vulnerable_road_user", "label": "摩自 / 行人"},
    {"key": "passable_space", "label": "可绕行空间"},
    {"key": "swag", "label": "SWAG / RA 操作"},
    {"key": "gt_boundary", "label": "GT 边界"},
)
REVIEW_TAG_KEYS = frozenset(item["key"] for item in REVIEW_TAG_CATALOG)
REVIEW_TAG_ALIASES = {
    "左转": "left_turn",
    "右转": "right_turn",
    "直行": "straight",
    "信号灯": "traffic_light",
    "红绿灯": "traffic_light",
    "等灯": "traffic_light",
    "排队": "queue",
    "双闪": "temporary_stop",
    "临停": "temporary_stop",
    "故障车": "temporary_stop",
    "遮挡": "occlusion",
    "摩自": "vulnerable_road_user",
    "行人": "vulnerable_road_user",
    "可绕行": "passable_space",
    "绕行空间": "passable_space",
    "SWAG": "swag",
    "RA": "swag",
    "GT": "gt_boundary",
    "GT待复核": "gt_boundary",
}

runtime_state: dict[str, Any] = {
    "baseline": {"status": "not_loaded", "message": "等待加载 0508 baseline。", "count": 0},
    "trail_sync": {
        "status": "not_started",
        "message": "尚未检查 Trail 模型字段。",
        "run_id": "",
        "can_create": False,
        "default_changed": False,
    },
}


EXAMPLE_CASES: tuple[dict[str, str], ...] = (
    {
        "issue_id": "cn32171803",
        "title": "左转待转，等灯场景",
        "scenario": "红绿灯周期性等待",
        "summary": "多个路口红灯持续亮起，有停止线；前方摩自停在停止线后方，自车同步等待。",
        "review_note": "当前模型说明为“正确判断为等灯”；用于核验等灯识别与标注流程。",
        "trail_url": "https://voyager.intra.xiaojukeji.com/static/management/#/issue/cn32171803?view_id=2410",
    },
    {
        "issue_id": "cn31954847",
        "title": "排队等灯，前方大车遮挡",
        "scenario": "红绿灯周期性等待",
        "summary": "红灯、停止线/斑马线明确；白色厢式货车停在停止线后，红灯转绿后车流通行。",
        "review_note": "当前模型说明为“正确判断排队等灯”；可用于检验大车遮挡下的等灯识别。",
        "trail_url": "https://voyager.intra.xiaojukeji.com/static/management/#/issue/cn31954847?view_id=2410",
    },
    {
        "issue_id": "cn32000543",
        "title": "自车右转，前方双闪临停车",
        "scenario": "绕行/异常停车",
        "summary": "模型判为排队，未覆盖 RA 协助下绕行通行；案例关注双闪特征。",
        "review_note": "问题假设：双闪缺失导致“排队”FP。请重点标注异常车辆与可绕行性。",
        "trail_url": "https://voyager.intra.xiaojukeji.com/static/management/#/issue/cn32000543?view_id=2410",
    },
    {
        "issue_id": "cn32044177",
        "title": "自车右转，摩自直行且有绕行空间",
        "scenario": "routing 方向 / 绕行空间",
        "summary": "模型判为等灯，但未判断 routing 方向和可绕行空间。",
        "review_note": "问题假设：routing 方向缺失导致“等灯”FP。",
        "trail_url": "https://voyager.intra.xiaojukeji.com/static/management/#/issue/cn32044177?view_id=2410",
    },
    {
        "issue_id": "cn32000563",
        "title": "自车右转，在直行车道排队",
        "scenario": "routing 方向 / 右侧通行空间",
        "summary": "模型判为排队，未识别右侧可右转通行空间；SWAG 右变道后又左加塞回原车道，需复核。",
        "review_note": "问题假设：routing 方向缺失导致“排队”FP；需再 review SWAG 操作链。",
        "trail_url": "https://voyager.intra.xiaojukeji.com/static/management/#/issue/cn32000563?view_id=2410",
    },
    {
        "issue_id": "cn31983487",
        "title": "自车右转，前车直行等灯且无绕行空间",
        "scenario": "routing 方向 / 无绕行空间",
        "summary": "模型判为等灯，但没有判断 routing 方向。",
        "review_note": "问题假设：routing 方向缺失导致“等灯”FP。",
        "trail_url": "https://voyager.intra.xiaojukeji.com/static/management/#/issue/cn31983487?view_id=2410",
    },
)


def _detail(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


def _safe_filename(name: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "upload")
    return result.strip("._")[:120] or "upload"


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _voyager_issue_url(issue_id: str) -> str:
    return (
        f"{settings.voyager_issue_base_url.rstrip('/')}/"
        f"{quote(issue_id, safe='')}?view_id={settings.voyager_issue_view_id}"
    )


def _autotriage_record_url(batch_id: str) -> str:
    if not batch_id:
        return ""
    return (
        f"{settings.auto_triage_record_base_url.rstrip('/')}/"
        f"{quote(batch_id, safe='')}?tab=results"
    )


def _public_batch_job(job: dict[str, Any]) -> dict[str, Any]:
    public = dict(job)
    public["record_url"] = _autotriage_record_url(
        _as_text(job.get("autotriage_batch_id"))
    )
    if "items" in job:
        public["items"] = [
            {
                **item,
                "voyager_issue_url": _voyager_issue_url(
                    _as_text(item.get("issue_id"))
                ),
            }
            for item in job.get("items", [])
        ]
    return public


def _action_actor(request: Request, submitted_name: Any = "") -> tuple[str, str, bool]:
    """Resolve an audit/display actor without trusting direct-IP client claims."""

    identity = request_identity(request, settings)
    if identity.verified and identity.username:
        return identity.username, identity.source, True
    username = normalise_username(_as_text(submitted_name))
    if username:
        return username, "client_claim_unverified", False
    return "", "anonymous", False


def _can_manage_team_default(request: Request) -> bool:
    identity = request_identity(request, settings)
    return bool(
        identity.verified
        and identity.username
        and identity.username in settings.team_default_managers
    )


def _value(row: dict[str, Any], *names: str) -> Any:
    lower = {str(key).strip().lower(): value for key, value in row.items()}
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
        value = lower.get(name.lower())
        if value not in (None, ""):
            return value
    return ""


def _parse_structured(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {"items": value}
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
    except (TypeError, ValueError):
        pass
    return {"text": value.strip()}


def _number_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _canonical_gt_label(value: Any) -> str:
    text = _as_text(value)
    mapping = {
        "false_positive": "误触发",
        "fp": "误触发",
        "false positive": "误触发",
        "true_positive": "正确触发",
        "tp": "正确触发",
        "true positive": "正确触发",
        "no_assist": "无需协助",
        "no_assistance": "无需协助",
        "不需要协助": "无需协助",
        "不需协助": "无需协助",
        "无需远程协助": "无需协助",
        "无需远程辅助": "无需协助",
        "无需人工协助": "无需协助",
    }
    text = mapping.get(text.lower(), text)
    return text if text in LABELS else ""


def _label_from_structured(value: dict[str, Any]) -> str:
    for key in ("label", "model_label", "result", "prediction", "triage_result", "class"):
        candidate = _canonical_gt_label(value.get(key))
        if candidate:
            return candidate
    return ""


def _first_text(value: dict[str, Any], *keys: str) -> str:
    for key in keys:
        text = _as_text(value.get(key))
        if text:
            return text
    return ""


def normalize_model_row(row: dict[str, Any]) -> dict[str, Any] | None:
    issue_id = _as_text(
        _value(row, "issue_id", "issueId", "issue", "问题id", "问题ID")
    )
    if not ISSUE_ID_RE.fullmatch(issue_id):
        return None
    raw_result = _value(
        row,
        "model_label",
        "ra_stuck_auto_result",
        "prediction",
        "pred_label",
        "预测标签",
    )
    result_info = _parse_structured(raw_result)
    info = _parse_structured(_value(row, "ra_stuck_auto_result_info", "result_info"))
    raw_label = _as_text(raw_result)
    label = _canonical_gt_label(raw_label) or _label_from_structured(result_info) or _label_from_structured(info)
    # Preserve a nonstandard class for audit/debugging.  It will be visibly
    # marked as non-comparable rather than being silently coerced to a GT label.
    if not label and raw_label and not isinstance(raw_result, (dict, list)):
        label = raw_label
    reason = _as_text(
        _value(
            row,
            "model_reason",
            "reason",
            "预测理由",
            "ra_stuck_auto_reason",
        )
    ) or _first_text(info, "reason", "model_reason", "analysis", "explanation", "text")
    confidence = _number_or_none(
        _value(row, "model_confidence", "confidence", "置信度")
        or info.get("confidence")
        or info.get("model_confidence")
    )
    extra = _value(row, "model_extra")
    if not isinstance(extra, dict):
        extra = {}
    if info:
        extra = {**extra, "ra_stuck_auto_result_info": info}
    if result_info and result_info != info:
        extra["ra_stuck_auto_result_payload"] = result_info
    return {
        "issue_id": issue_id,
        "trip_id": _as_text(_value(row, "trip_id", "tripId")),
        "model_label": label,
        "model_reason": reason,
        "model_confidence": confidence,
        "model_extra": extra,
        "raw": row,
    }


def normalize_issue_row(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    issue_id = _as_text(
        _value(row, "issue_id", "issueId", "issue", "问题id", "问题ID")
    )
    if not ISSUE_ID_RE.fullmatch(issue_id):
        return None
    gt_label = _canonical_gt_label(
        _value(
            row,
            "gt_label",
            "ra_merge_result",
            "期望输出",
            "真实标签",
            "ground_truth",
        )
    )
    return {
        "issue_id": issue_id,
        "trip_id": _as_text(_value(row, "trip_id", "tripId")),
        "title": _as_text(_value(row, "title", "标题", "名称")),
        "scenario": _as_text(_value(row, "scenario", "场景")),
        "summary": _as_text(_value(row, "summary", "描述", "description")),
        "review_note": _as_text(_value(row, "review_note", "备注", "note")),
        "trail_url": _as_text(_value(row, "trail_url", "url", "链接")),
        "gt_label": gt_label,
        "gt_source": source if gt_label else "",
        "extra": redact_sensitive_fields(row),
    }


def parse_source_bytes(filename: str, content: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        parsed = json.loads(content.decode("utf-8-sig"))
        if isinstance(parsed, dict):
            rows = parsed.get("results") or parsed.get("data") or parsed.get("rows") or []
            metadata = {
                key: value
                for key, value in parsed.items()
                if key not in {"results", "data", "rows"}
            }
        elif isinstance(parsed, list):
            rows, metadata = parsed, {}
        else:
            raise ValueError("JSON 顶层必须是对象或数组。")
        if not isinstance(rows, list):
            raise ValueError("JSON 的 results/data/rows 必须是数组。")
        return [
            row for row in rows if isinstance(row, dict)
        ], redact_sensitive_fields(metadata)

    if suffix == ".csv":
        text = ""
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if not text:
            raise ValueError("CSV 编码无法识别，请使用 UTF-8 或 GB18030。")
        return list(csv.DictReader(io.StringIO(text))), {}

    if suffix in {".xlsx", ".xlsm"}:
        workbook = openpyxl.load_workbook(
            io.BytesIO(content), read_only=True, data_only=True
        )
        sheet = workbook.active
        values = sheet.iter_rows(values_only=True)
        headers = next(values, None)
        if not headers:
            raise ValueError("Excel 缺少表头。")
        columns = [str(value).strip() if value is not None else "" for value in headers]
        rows: list[dict[str, Any]] = []
        for values_row in values:
            if not any(value is not None and str(value).strip() for value in values_row):
                continue
            rows.append(
                {
                    columns[index]: value
                    for index, value in enumerate(values_row)
                    if index < len(columns) and columns[index]
                }
            )
        return rows, {"sheet": sheet.title}

    raise ValueError("仅支持 .json、.csv、.xlsx 或 .xlsm。")


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
    if len(uploads) > MAX_REVIEW_ATTACHMENTS:
        raise _detail(400, f"每次最多粘贴 {MAX_REVIEW_ATTACHMENTS} 张截图。")
    prepared: list[tuple[dict[str, Any], bytes]] = []
    raw_total_bytes = 0
    total_bytes = 0
    for upload in uploads:
        content = await upload.read(MAX_REVIEW_ATTACHMENT_BYTES + 1)
        if not content:
            raise _detail(400, "截图文件为空。")
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

    root = settings.review_attachments_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (
        prepared
        and database.review_attachment_storage_bytes() + total_bytes
        > MAX_REVIEW_ATTACHMENT_STORAGE_BYTES
    ):
        raise _detail(507, "Review 截图已达到 20 GB 存储配额，请联系管理员清理或扩容。")
    if prepared and shutil.disk_usage(root).free < total_bytes + MIN_REVIEW_ATTACHMENT_DISK_FREE:
        raise _detail(507, "截图存储空间不足，请联系管理员。")
    temp_paths: list[Path] = []
    final_paths: list[Path] = []
    try:
        for record, content in prepared:
            stored_name = str(record["stored_name"])
            path = (settings.review_attachments_dir / stored_name).resolve()
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
        "url": f"/api/review-attachments/{attachment['id']}",
    }


def _normalise_review_tags(values: list[Any]) -> list[str]:
    if len(values) > 12:
        raise _detail(400, "每条 review 最多选择 12 个 tags。")
    normalized: set[str] = set()
    legacy: set[str] = set()
    for value in values:
        raw = str(value).strip()
        if not raw:
            continue
        if len(raw) > 48 or re.search(r"[\x00-\x1f\x7f]", raw):
            raise _detail(400, "tag 长度或字符不合法。")
        key = REVIEW_TAG_ALIASES.get(raw, raw)
        if key in REVIEW_TAG_KEYS:
            normalized.add(key)
        else:
            # Existing JSON clients historically supplied free-form tags.
            # Preserve safe legacy values while the UI only offers the catalog.
            legacy.add(raw)
    return [
        *[item["key"] for item in REVIEW_TAG_CATALOG if item["key"] in normalized],
        *sorted(legacy),
    ]


def _create_annotation_record(
    *,
    issue_id: str,
    request: Request,
    body: dict[str, Any],
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    label = _as_text(body.get("label"))
    review_status = _as_text(body.get("review_status") or "pending")
    tags = body.get("tags") or []
    missing_evidence = body.get("missing_evidence") or []
    if not isinstance(tags, list):
        raise _detail(400, "tags 必须是数组。")
    if not isinstance(missing_evidence, list):
        raise _detail(400, "missing_evidence 必须是数组。")
    tags = _normalise_review_tags(tags)
    author, author_source, author_verified = _action_actor(request, body.get("author"))
    try:
        return database.create_annotation(
            issue_id=issue_id,
            label=label,
            review_status=review_status,
            tags=tags,
            missing_evidence=missing_evidence,
            note=_as_text(body.get("note")),
            author=author,
            author_source=author_source,
            author_verified=author_verified,
            attachments=attachments,
        )
    except ValueError as exc:
        raise _detail(400, str(exc))


def bootstrap_model_result() -> None:
    path = settings.bootstrap_model_json
    if not path or not path.is_file():
        return
    content = path.read_bytes()
    try:
        source_rows, metadata = parse_source_bytes(path.name, content)
        rows = [normalized for row in source_rows if (normalized := normalize_model_row(row))]
        if not rows:
            return
        experiment = metadata.get("experiment") if isinstance(metadata.get("experiment"), dict) else {}
        name = _as_text(experiment.get("model_name")) or path.stem
        database.import_model_run(
            name=name,
            source_name=str(path),
            source_sha256=hashlib.sha256(content).hexdigest(),
            metadata=metadata,
            rows=rows,
            created_by="system",
            created_by_source="service_bootstrap",
            created_by_verified=False,
        )
    except Exception as exc:
        print(f"[ra_triage_dashboard] bootstrap model result skipped: {exc}", flush=True)


def bootstrap_baseline() -> dict[str, Any]:
    loaded = load_label_baseline(settings.baseline_label_xlsx, settings.baseline_dataset)
    state = {
        "scope": settings.baseline_scope,
        "dataset": settings.baseline_dataset,
        "path": str(settings.baseline_label_xlsx),
        "source_rows": loaded.source_rows,
        "count": len(loaded.rows),
        "skipped_rows": loaded.skipped_rows,
        "message": loaded.message,
        "status": "ready" if loaded.rows else "unavailable",
    }
    if loaded.rows:
        state["upsert"] = database.replace_baseline_scope(
            scope=settings.baseline_scope,
            rows=loaded.rows,
            source="trail_label_baseline",
        )
    runtime_state["baseline"] = state
    return state


def sync_trail_model_fields(
    *,
    create_run: bool = False,
    requested_by: str = "",
    identity_source: str = "anonymous",
    identity_verified: bool = False,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Inspect Trail fields and optionally create/reuse an immutable local snapshot.

    This function only calls the Trail query client.  Creating a snapshot writes
    local SQLite rows, but never writes Trail and never changes the shared
    default model run.
    """

    if not trail_sync_lock.acquire(blocking=False):
        return {
            **runtime_state["trail_sync"],
            "status": "running",
            "message": "已有 Trail 字段检查或快照任务在运行。",
        }
    action = "创建只读快照" if create_run else "检查字段"
    runtime_state["trail_sync"] = {
        "status": "running",
        "message": f"正在从 Trail view {settings.trail_view_id} 只读{action}。",
        "run_id": "",
        "can_create": False,
        "default_changed": False,
        "action": "create" if create_run else "preview",
    }
    try:
        issue_ids = database.baseline_issue_ids(settings.baseline_scope)
        result = read_trail_model_fields(
            ra_root=settings.ra_auto_triage_root,
            issue_ids=issue_ids,
            view_id=settings.trail_view_id,
            chunk_size=settings.trail_sync_chunk_size,
        )
        state: dict[str, Any] = {
            "status": "unavailable",
            "message": result.message,
            "view_id": result.view_id,
            "queried_issues": result.queried_issues,
            "returned_issues": result.returned_issues,
            "fields_visible": list(result.fields_visible),
            "run_id": "",
            "complete": result.complete,
            "can_create": False,
            "default_changed": False,
            "action": "create" if create_run else "preview",
        }
        if not result.complete or result.returned_issues < result.queried_issues:
            state.update(
                {
                    "status": "failed",
                    "message": (
                        result.message
                        + (
                            f" 仅返回 {result.returned_issues} / {result.queried_issues} 个 baseline issue；"
                            if result.complete
                            else " "
                        )
                        + "为避免部分快照，未创建 Run，团队默认 Run 未变化。"
                    ),
                }
            )
            runtime_state["trail_sync"] = state
            return state
        if TRAIL_RESULT_FIELD not in result.fields_visible:
            state["message"] = result.message + " 未创建 Run，团队默认 Run 未变化。"
            runtime_state["trail_sync"] = state
            return state
        normalized = [row for raw in result.rows if (row := normalize_model_row(raw))]
        # Trail snapshots participate in three-class evaluation, so only the
        # canonical labels are usable. Keep non-standard values out of the
        # snapshot rather than treating placeholders such as "nan" as labels.
        usable = [row for row in normalized if row["model_label"] in LABELS]
        if not usable:
            state.update(
                {
                    "status": "empty",
                    "message": (
                        result.message
                        + " 字段已出现，但当前 baseline 没有非空模型结果；未创建 Run。"
                    ),
                }
            )
            runtime_state["trail_sync"] = state
            return state
        snapshot_rows = sorted(usable, key=lambda row: row["issue_id"])
        state.update(
            {
                "can_create": True,
                "usable_predictions": len(usable),
                "missing_predictions": max(result.queried_issues - len(usable), 0),
            }
        )
        if not create_run:
            state.update(
                {
                    "status": "preview_ready",
                    "message": (
                        result.message
                        + f" 检查完成：{len(usable)} / {result.queried_issues} 条可生成快照。"
                        + " 尚未创建 Run，团队默认 Run 未变化。"
                    ),
                }
            )
            runtime_state["trail_sync"] = state
            return state
        payload = {
            "scope": settings.baseline_scope,
            "view_id": settings.trail_view_id,
            "fields": [TRAIL_RESULT_FIELD, TRAIL_INFO_FIELD],
            "rows": snapshot_rows,
        }
        source_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        run, duplicate = database.import_model_run(
            name=f"Trail view {settings.trail_view_id} · {TRAIL_RESULT_FIELD}",
            source_name=f"Trail view {settings.trail_view_id}",
            source_sha256=source_hash,
            metadata={
                "schema_version": "trail-fields-v1",
                "origin": "trail_readonly_snapshot",
                "baseline_scope": settings.baseline_scope,
                "view_id": settings.trail_view_id,
                "fields_visible": list(result.fields_visible),
                "queried_issues": result.queried_issues,
                "returned_issues": result.returned_issues,
                "usable_predictions": len(usable),
                "trigger": trigger,
            },
            rows=snapshot_rows,
            kind="trail_snapshot",
            make_default=False,
            created_by=requested_by,
            created_by_source=identity_source,
            created_by_verified=identity_verified,
        )
        state.update(
            {
                "status": "ready",
                "run_id": run["id"],
                "usable_predictions": len(usable),
                "duplicate": duplicate,
                "message": (
                    result.message
                    + (
                        f" 内容未变化，已复用现有只读快照（{len(usable)} 条）。"
                        if duplicate
                        else f" 已创建只读快照（{len(usable)} 条）。"
                    )
                    + " Trail、GT、人工复核和团队默认 Run 均未修改。"
                ),
            }
        )
        runtime_state["trail_sync"] = state
        return state
    except Exception as exc:
        state = {
            "status": "failed",
            "message": f"Trail 只读{action}失败: {exc}；未创建 Run，团队默认 Run 未变化。",
            "run_id": "",
            "can_create": False,
            "default_changed": False,
            "action": "create" if create_run else "preview",
        }
        runtime_state["trail_sync"] = state
        return state
    finally:
        trail_sync_lock.release()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_directories()
    database.init()
    database.seed_examples(EXAMPLE_CASES)
    bootstrap_baseline()
    asset_index.refresh(force=True)
    bootstrap_model_result()
    if settings.trail_sync_on_start:
        await asyncio.to_thread(
            sync_trail_model_fields,
            create_run=False,
            requested_by="system",
            identity_source="service_startup",
            identity_verified=False,
            trigger="startup",
        )
    try:
        yield
    finally:
        await asyncio.to_thread(batch_prediction_runner.shutdown)


app = FastAPI(
    title="RA Triage Workbench",
    version="1.4.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def review_attachment_request_size_guard(request: Request, call_next):
    if (
        request.method == "POST"
        and request.url.path.startswith("/api/cases/")
        and request.url.path.endswith("/annotations-with-attachments")
    ):
        if request.headers.get("x-ra-triage-request") != "review-v1":
            return JSONResponse(
                status_code=403,
                content={"detail": "缺少 Review 截图请求标记。"},
            )
        content_length = request.headers.get("content-length", "").strip()
        if not content_length:
            return JSONResponse(
                status_code=411,
                content={"detail": "Review 截图请求必须提供 Content-Length。"},
            )
        try:
            request_bytes = int(content_length)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Content-Length 非法。"},
            )
        if request_bytes > MAX_REVIEW_MULTIPART_REQUEST_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "截图上传请求不能超过 26 MB。"},
            )
    return await call_next(request)


app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")


@app.get("/", include_in_schema=False)
@app.get("/review", include_in_schema=False)
@app.get("/runs", include_in_schema=False)
@app.get("/inference", include_in_schema=False)
@app.get("/batch-prediction", include_in_schema=False)
@app.get("/import", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(settings.static_dir / "index.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "ra_auto_triage_root_available": (settings.ra_auto_triage_root / "vlm").is_dir(),
        "ares_manifest_available": settings.ares_manifest.is_file(),
        "ares_indexed_issues": asset_index.refresh(),
        "camera_cache_root_available": settings.camera_root.is_dir(),
        "baseline": runtime_state["baseline"],
        "trail_sync": runtime_state["trail_sync"],
        "trail_write_enabled": False,
        "batch_prediction_enabled": settings.batch_prediction_enabled,
        "autotriage_push_enabled": settings.autotriage_push_enabled,
        "storage": "sqlite-mvp",
    }


@app.get("/api/overview")
async def overview(model_run_id: str = "") -> dict[str, Any]:
    selected = model_run_id or database.default_model_run_id()
    return database.overview(baseline_scope=settings.baseline_scope, model_run_id=selected)


@app.get("/api/dashboard-config")
async def dashboard_config() -> dict[str, Any]:
    return {
        "baseline": runtime_state["baseline"],
        "default_model_run_id": database.default_model_run_id(),
        "trail_sync": runtime_state["trail_sync"],
        "missing_evidence_catalog": MISSING_EVIDENCE_CATALOG,
        "review_tag_catalog": REVIEW_TAG_CATALOG,
        "review_attachment_limits": {
            "max_count": MAX_REVIEW_ATTACHMENTS,
            "max_bytes_each": MAX_REVIEW_ATTACHMENT_BYTES,
            "max_bytes_total": MAX_REVIEW_ATTACHMENTS_TOTAL_BYTES,
            "media_types": ["image/png", "image/jpeg", "image/webp"],
        },
        "default_failure_only": bool(database.default_model_run_id()),
        "batch_prediction": {
            "enabled": settings.batch_prediction_enabled,
            "autotriage_push_enabled": settings.autotriage_push_enabled,
            "max_issues": settings.batch_max_issues,
            "input_policy": "server_default_model",
            "ares_bev_input": False,
            "trail_write_enabled": False,
        },
    }


@app.get("/api/session")
async def session(request: Request) -> dict[str, object]:
    identity = request_identity(request, settings)
    return identity.as_dict(
        trust_proxy_headers=settings.trust_proxy_identity_headers
    ) | {
        "browser_lca_fallback": not identity.authenticated,
        "identity_header": (
            settings.identity_header
            if settings.trust_proxy_identity_headers
            else ""
        ),
        "can_manage_team_default": _can_manage_team_default(request),
    }


@app.get("/api/status")
async def status() -> dict[str, Any]:
    return {
        "trail_write_enabled": False,
        "ra_auto_triage_root_available": (settings.ra_auto_triage_root / "vlm").is_dir(),
        "ares_manifest_available": settings.ares_manifest.is_file(),
        "ares_indexed_issues": asset_index.refresh(),
        "camera_cache_root_available": settings.camera_root.is_dir(),
        "baseline": runtime_state["baseline"],
        "trail_sync": runtime_state["trail_sync"],
        "batch_prediction_enabled": settings.batch_prediction_enabled,
        "autotriage_push_enabled": settings.autotriage_push_enabled,
        "batch_max_issues": settings.batch_max_issues,
        "storage": "SQLite MVP / PostgreSQL migration prepared",
        "model_endpoint_policy": "仅使用 cloud_server ra_auto_triage 默认配置；浏览器不可覆盖",
    }


@app.get("/api/cases")
async def list_cases(
    search: str = "",
    gt_label: str = "",
    annotation_label: str = "",
    annotation_author: str = "",
    model_run_id: str = "",
    failure_only: bool = False,
    missing_evidence: str = "",
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    result = database.list_cases(
        baseline_scope=settings.baseline_scope,
        search=search,
        gt_label=gt_label,
        annotation_label=annotation_label,
        annotation_author=annotation_author,
        model_run_id=model_run_id,
        failure_only=failure_only,
        missing_evidence=missing_evidence,
        page=page,
        page_size=page_size,
    )
    result["items"] = [
        {**item, "voyager_issue_url": _voyager_issue_url(item["issue_id"])}
        for item in result.get("items", [])
    ]
    return result


@app.get("/api/reviewers")
async def reviewers() -> dict[str, Any]:
    return {"items": database.list_reviewers(settings.baseline_scope)}


@app.get("/api/cases/{issue_id}")
async def get_case(issue_id: str) -> dict[str, Any]:
    case = database.get_case(issue_id)
    if case is None:
        raise _detail(404, "Issue 不存在。")
    for annotation in case.get("annotations", []):
        annotation["attachments"] = [
            _public_review_attachment(attachment)
            for attachment in annotation.get("attachments", [])
        ]
    case["assets"] = asset_index.get_assets(issue_id)
    case["camera"] = camera_index.get_assets(
        issue_id, (case["assets"].get("capture") or {}).get("timestamp_ms")
    )
    case["voyager_issue_url"] = _voyager_issue_url(issue_id)
    case["batch_jobs"] = [
        _public_batch_job(job) for job in case.get("batch_jobs", [])
    ]
    return case


@app.get("/api/assets/{issue_id}/{asset_id}")
async def get_asset(issue_id: str, asset_id: str) -> FileResponse:
    path = asset_index.get_asset_path(issue_id, asset_id) or camera_index.get_asset_path(
        issue_id, asset_id
    )
    if path is None:
        raise _detail(404, "Ares / Camera 资产不存在。")
    suffix = path.suffix.lower()
    media_type = (
        "video/mp4"
        if suffix == ".mp4"
        else "image/jpeg"
        if suffix in {".jpg", ".jpeg"}
        else "image/png"
    )
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/api/review-attachments/{attachment_id}")
async def get_review_attachment(attachment_id: str) -> FileResponse:
    attachment = database.get_review_attachment(attachment_id)
    if attachment is None:
        raise _detail(404, "Review 截图不存在。")
    root = settings.review_attachments_dir.resolve()
    path = (root / attachment["stored_name"]).resolve()
    if root not in path.parents or not path.is_file():
        raise _detail(404, "Review 截图文件不存在。")
    return FileResponse(
        path,
        media_type=attachment["media_type"],
        headers={
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=31536000, immutable",
        },
    )


@app.post("/api/cases/{issue_id}/annotations")
async def create_annotation(issue_id: str, request: Request) -> dict[str, Any]:
    if database.get_case(issue_id) is None:
        raise _detail(404, "Issue 不存在。")
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "标注请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "标注请求必须是 JSON 对象。")
    annotation = _create_annotation_record(
        issue_id=issue_id,
        request=request,
        body=body,
    )
    return {"annotation": annotation}


@app.post("/api/cases/{issue_id}/annotations-with-attachments")
async def create_annotation_with_attachments(
    issue_id: str,
    request: Request,
    payload: str = Form(...),
    attachments: list[UploadFile] | None = File(None),
) -> dict[str, Any]:
    if database.get_case(issue_id) is None:
        raise _detail(404, "Issue 不存在。")
    try:
        body = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise _detail(400, "payload 必须是 JSON 对象。")
    if not isinstance(body, dict):
        raise _detail(400, "payload 必须是 JSON 对象。")
    records, paths = await _store_review_attachments(attachments or [])
    try:
        annotation = _create_annotation_record(
            issue_id=issue_id,
            request=request,
            body=body,
            attachments=records,
        )
    except Exception:
        for path in paths:
            path.unlink(missing_ok=True)
        raise
    annotation["attachments"] = [
        _public_review_attachment(attachment)
        for attachment in annotation.get("attachments", [])
    ]
    return {"annotation": annotation}


@app.get("/api/model-runs")
async def model_runs() -> dict[str, Any]:
    return {
        "items": database.list_model_runs(settings.baseline_scope),
        "default_model_run_id": database.default_model_run_id(),
    }


@app.post("/api/model-runs/{run_id}/default")
async def set_default_model_run(run_id: str, request: Request) -> dict[str, Any]:
    if not _can_manage_team_default(request):
        raise _detail(
            403,
            "设置团队默认 Run 需要可信 SSO 且用户名位于 "
            "DASHBOARD_TEAM_DEFAULT_MANAGERS；当前仍可在 Review 中选择任意 Run。",
        )
    run = database.set_default_model_run(run_id)
    if run is None:
        raise _detail(404, "模型 run 不存在。")
    return {"run": run, "default_model_run_id": run_id}


@app.get("/api/review-clusters")
async def review_clusters(
    model_run_id: str = "",
    failure_only: bool = True,
    annotation_author: str = "",
) -> dict[str, Any]:
    return {
        "items": database.review_clusters(
            baseline_scope=settings.baseline_scope,
            model_run_id=model_run_id,
            failure_only=failure_only,
            annotation_author=annotation_author,
        )
    }


@app.post("/api/trail-model-sync")
async def trail_model_sync(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        body = {}
    mode = _as_text(body.get("mode") or "preview")
    if mode not in {"preview", "create"}:
        raise _detail(400, "mode 仅支持 preview 或 create。")
    actor, actor_source, actor_verified = _action_actor(
        request, body.get("requested_by")
    )
    return await asyncio.to_thread(
        sync_trail_model_fields,
        create_run=mode == "create",
        requested_by=actor,
        identity_source=actor_source,
        identity_verified=actor_verified,
        trigger="manual",
    )


@app.get("/api/import-contract")
async def import_contract() -> dict[str, Any]:
    return {
        "formats": [".json", ".csv", ".xlsx", ".xlsm"],
        "issues": {
            "required": ["issue_id"],
            "optional": [
                "trip_id",
                "gt_label / ra_merge_result / 期望输出",
                "title",
                "scenario",
                "summary",
                "trail_url",
            ],
        },
        "model_results": {
            "required": ["issue_id", "model_label 或 ra_stuck_auto_result"],
            "optional": [
                "trip_id",
                "model_reason / reason",
                "model_confidence / confidence",
                "model_extra",
                "ra_stuck_auto_result_info",
            ],
            "native_json_envelope": {"experiment": {}, "results": []},
        },
        "notes": [
            "每次导入会创建不可变 model run，并按 SHA-256 去重。",
            "Trail 真值不因模型导入而覆盖；只有 issues 导入且显式 replace_gt 才会覆盖已有 GT。",
        ],
    }


async def _read_upload(upload: UploadFile) -> tuple[bytes, str, str]:
    filename = _safe_filename(upload.filename or "upload")
    content = await upload.read()
    if not content:
        raise _detail(400, "上传文件为空。")
    if len(content) > MAX_UPLOAD_BYTES:
        raise _detail(413, "上传文件超过 64 MB 限制。")
    source_hash = hashlib.sha256(content).hexdigest()
    return content, filename, source_hash


@app.post("/api/import/issues")
async def import_issues(
    file: UploadFile = File(...),
    source: str = Form("manual_upload"),
    replace_gt: str = Form("false"),
) -> dict[str, Any]:
    content, filename, _ = await _read_upload(file)
    try:
        source_rows, metadata = parse_source_bytes(filename, content)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise _detail(400, f"解析文件失败: {exc}")
    rows = [normalized for row in source_rows if (normalized := normalize_issue_row(row, source))]
    if not rows:
        raise _detail(400, "未找到有效 issue_id；请检查表头或导入契约。")
    outcome = database.upsert_issues(
        rows,
        source=source,
        replace_gt=replace_gt.lower() in {"1", "true", "yes", "on"},
    )
    return {
        "filename": filename,
        "parsed_rows": len(source_rows),
        "accepted_rows": len(rows),
        "metadata": metadata,
        **outcome,
    }


@app.post("/api/import/model-results")
async def import_model_results(
    request: Request,
    file: UploadFile = File(...),
    run_name: str = Form(""),
    created_by: str = Form(""),
) -> dict[str, Any]:
    content, filename, source_hash = await _read_upload(file)
    try:
        source_rows, metadata = parse_source_bytes(filename, content)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise _detail(400, f"解析文件失败: {exc}")
    rows = [normalized for row in source_rows if (normalized := normalize_model_row(row))]
    if not rows:
        raise _detail(
            400,
            "未找到有效结果；需要 issue_id 和 model_label（或 ra_stuck_auto_result）。",
        )
    experiment = metadata.get("experiment") if isinstance(metadata.get("experiment"), dict) else {}
    default_name = _as_text(experiment.get("model_name")) or Path(filename).stem
    actor, actor_source, actor_verified = _action_actor(request, created_by)
    run, duplicate = database.import_model_run(
        name=_as_text(run_name) or default_name,
        source_name=filename,
        source_sha256=source_hash,
        metadata=metadata,
        rows=rows,
        created_by=actor,
        created_by_source=actor_source,
        created_by_verified=actor_verified,
    )
    return {
        "run": run,
        "duplicate": duplicate,
        "filename": filename,
        "parsed_rows": len(source_rows),
        "accepted_rows": len(rows),
        "rejected_rows": len(source_rows) - len(rows),
    }


@app.get("/api/prediction-batches/config")
async def batch_prediction_config() -> dict[str, Any]:
    latest = database.list_batch_prediction_jobs(page_size=1).get("items", [])
    latest_job = latest[0] if latest else {}
    return {
        "enabled": settings.batch_prediction_enabled,
        "autotriage_push_enabled": settings.autotriage_push_enabled,
        "max_issues": settings.batch_max_issues,
        "model": {
            "source": "cloud_server ra_auto_triage 默认 Experiment",
            "name": _as_text(latest_job.get("model_name"))
            or "任务启动时解析服务器默认模型",
            "prompt_version": _as_text(latest_job.get("prompt_version"))
            or "任务启动时解析服务器默认 Prompt",
        },
        "input_policy": {
            "issue_source": "Voyager Issue + dashboard isolated bag cache",
            "ares_bev_input": False,
            "browser_model_credentials": False,
            "bag_cache_read_only": False,
            "bag_cache_scope": "dashboard_isolated",
            "trail_write_enabled": False,
        },
        "publish_policy": {
            "explicit_confirmation": True,
            "destination": settings.auto_triage_record_base_url,
            "writer": "cloud_server 固定服务身份",
            "requester_is_writer": False,
        },
    }


@app.post("/api/prediction-batches", status_code=202)
async def create_batch_prediction(request: Request) -> dict[str, Any]:
    if not settings.batch_prediction_enabled:
        raise _detail(503, "当前部署未启用 Batch 预测。")
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "Batch 请求必须是 JSON。")
    if not isinstance(body, dict):
        raise _detail(400, "Batch 请求必须是 JSON 对象。")
    raw_issue_ids = body.get("issue_ids")
    if not isinstance(raw_issue_ids, list):
        raise _detail(400, "issue_ids 必须是数组。")
    issue_ids: list[str] = []
    seen: set[str] = set()
    for value in raw_issue_ids:
        issue_id = _as_text(value)
        if not ISSUE_ID_RE.fullmatch(issue_id):
            raise _detail(400, f"Issue ID 格式非法: {issue_id or '<空>'}")
        if issue_id not in seen:
            seen.add(issue_id)
            issue_ids.append(issue_id)
    if not issue_ids:
        raise _detail(400, "至少需要一个 Issue ID。")
    if len(issue_ids) > settings.batch_max_issues:
        raise _detail(
            400,
            f"单批最多 {settings.batch_max_issues} 个 Issue；当前 {len(issue_ids)} 个。",
        )
    missing = [
        issue_id
        for issue_id in issue_ids
        if database.get_case(issue_id) is None
    ]
    if missing:
        preview = "、".join(missing[:8])
        suffix = "…" if len(missing) > 8 else ""
        raise _detail(
            404,
            f"以下 Issue 不在当前 Workbench 数据集中: {preview}{suffix}",
        )
    name = _as_text(body.get("name"))
    if len(name) > 120:
        raise _detail(400, "Batch 名称不能超过 120 个字符。")
    actor, actor_source, actor_verified = _action_actor(
        request, body.get("requested_by")
    )
    job = database.create_batch_prediction_job(
        name=name,
        issue_ids=issue_ids,
        requested_by=actor,
        requested_by_source=actor_source,
        requested_by_verified=actor_verified,
    )
    if not batch_prediction_runner.launch_prediction(job):
        error = "已有 Batch 预测或 AutoTriage 推送正在执行，请稍后重试。"
        database.update_batch_prediction_items(
            job["id"],
            [
                {"issue_id": issue_id, "success": False, "error": error}
                for issue_id in issue_ids
            ],
        )
        database.update_batch_prediction_job(
            job["id"],
            status="failed",
            completed_count=len(issue_ids),
            failed_count=len(issue_ids),
            error_text=error,
        )
        raise _detail(409, error)
    return {
        "job": _public_batch_job(
            database.get_batch_prediction_job(job["id"]) or job
        ),
        "safety": {
            "server_default_model": True,
            "browser_model_credentials": False,
            "ares_bev_input": False,
            "bag_cache_read_only": False,
            "bag_cache_scope": "dashboard_isolated",
            "trail_write_enabled": False,
            "autotriage_publish_automatic": False,
        },
        "poll_url": f"/api/prediction-batches/{job['id']}",
    }


@app.get("/api/prediction-batches")
async def list_batch_predictions(
    requested_by: str = "",
    status: str = "",
    page_size: int = 100,
) -> dict[str, Any]:
    result = database.list_batch_prediction_jobs(
        requested_by=requested_by,
        status=status,
        page_size=page_size,
    )
    result["items"] = [
        _public_batch_job(job) for job in result.get("items", [])
    ]
    return result


@app.get("/api/prediction-batches/{job_id}")
async def get_batch_prediction(job_id: str) -> dict[str, Any]:
    job = database.get_batch_prediction_job(job_id)
    if job is None:
        raise _detail(404, "Batch 任务不存在。")
    return {"job": _public_batch_job(job)}


@app.post(
    "/api/prediction-batches/{job_id}/publish-autotriage",
    status_code=202,
)
async def publish_batch_prediction(job_id: str, request: Request) -> dict[str, Any]:
    if request.headers.get("x-ra-triage-request") != "publish-v1":
        raise _detail(403, "缺少 AutoTriage 推送请求标记。")
    if not settings.autotriage_push_enabled:
        raise _detail(503, "当前部署未启用 AutoTriage 推送。")
    publisher = request_identity(request, settings)
    if not publisher.verified or not publisher.username:
        raise _detail(
            403,
            "AutoTriage 是生产写操作，仅允许可信 SSO 会话；"
            "直接 IP / 本机 LCA 用户不能触发。",
        )
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "推送请求必须是 JSON。")
    if not isinstance(body, dict) or body.get("confirm") not in {
        True,
        "publish-autotriage",
    }:
        raise _detail(400, "必须显式确认创建生产 AutoTriage Batch。")
    job = database.get_batch_prediction_job(job_id)
    if job is None:
        raise _detail(404, "Batch 任务不存在。")
    if job.get("autotriage_batch_id"):
        return {"job": _public_batch_job(job), "idempotent": True}
    if job.get("publish_status") == "running":
        raise _detail(409, "该 Batch 正在推送 AutoTriage。")
    if (
        job.get("status") not in {"succeeded", "partial"}
        or int(job.get("success_count") or 0) <= 0
        or not job.get("model_run_id")
        or not job.get("config_sha256")
    ):
        raise _detail(409, "Batch 尚无可推送的成功预测。")
    job = (
        database.update_batch_prediction_job(
            job_id,
            summary={
                **dict(job.get("summary") or {}),
                "autotriage_publish_request": {
                    "requested_by": publisher.username,
                    "identity_source": publisher.source,
                    "verified": True,
                },
            },
        )
        or job
    )
    if not batch_prediction_runner.launch_publish(job):
        raise _detail(409, "已有 Batch 预测或 AutoTriage 推送正在执行，请稍后重试。")
    return {
        "job": _public_batch_job(
            database.get_batch_prediction_job(job_id) or job
        ),
        "accepted": True,
        "destination": settings.auto_triage_record_base_url,
        "poll_url": f"/api/prediction-batches/{job_id}",
    }


@app.post("/api/inference/jobs")
async def create_inference_job(request: Request) -> dict[str, Any]:
    raise _detail(
        410,
        "浏览器单 Case 自定义模型推理已停用；请使用 /api/prediction-batches，"
        "由 cloud_server 的 ra_auto_triage 默认模型执行。",
    )


@app.get("/api/inference/jobs")
async def list_inference_jobs(
    requested_by: str = "",
    status: str = "",
    page_size: int = 100,
) -> dict[str, Any]:
    return database.list_inference_jobs(
        requested_by=requested_by,
        status=status,
        page_size=page_size,
    )


@app.get("/api/inference/jobs/{job_id}")
async def get_inference_job(job_id: str) -> dict[str, Any]:
    job = database.get_job(job_id)
    if job is None:
        raise _detail(404, "任务不存在。")
    return {"job": job}
