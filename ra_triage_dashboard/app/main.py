from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import ipaddress
import json
import math
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import openpyxl
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .assets import AssetIndex, CameraIndex
from .auth import request_identity
from .baseline import load_label_baseline
from .db import LABELS, REVIEW_STATUSES, Database
from .runner import InferenceRunner
from .settings import Settings
from .trail_sync import TRAIL_INFO_FIELD, TRAIL_RESULT_FIELD, read_trail_model_fields


settings = Settings.from_env()
database = Database(settings.db_path)
asset_index = AssetIndex(
    ra_root=settings.ra_auto_triage_root,
    manifest_path=settings.ares_manifest,
)
camera_index = CameraIndex(settings.camera_root)
inference_runner = InferenceRunner(settings, database)
trail_sync_lock = threading.Lock()

ISSUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,128}$")
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

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

runtime_state: dict[str, Any] = {
    "baseline": {"status": "not_loaded", "message": "等待加载 0508 baseline。", "count": 0},
    "trail_sync": {"status": "not_started", "message": "尚未同步 Trail 模型字段。", "run_id": ""},
}


EXAMPLE_CASES: tuple[dict[str, str], ...] = (
    {
        "issue_id": "cn32171803",
        "title": "左转待转，等灯场景",
        "scenario": "红绿灯周期性等待",
        "summary": "多个路口红灯持续亮起，有停止线；前方摩自停在停止线后方，自车同步等待。",
        "review_note": "当前模型说明为“正确判断为等灯”；用于核验等灯识别与标注流程。",
        "trail_url": "http://auto-triage.intra.xiaojukeji.com/ra/model_triage/records/757?tab=results",
    },
    {
        "issue_id": "cn31954847",
        "title": "排队等灯，前方大车遮挡",
        "scenario": "红绿灯周期性等待",
        "summary": "红灯、停止线/斑马线明确；白色厢式货车停在停止线后，红灯转绿后车流通行。",
        "review_note": "当前模型说明为“正确判断排队等灯”；可用于检验大车遮挡下的等灯识别。",
        "trail_url": "http://auto-triage.intra.xiaojukeji.com/ra/model_triage/records/759?tab=results",
    },
    {
        "issue_id": "cn32000543",
        "title": "自车右转，前方双闪临停车",
        "scenario": "绕行/异常停车",
        "summary": "模型判为排队，未覆盖 RA 协助下绕行通行；案例关注双闪特征。",
        "review_note": "问题假设：双闪缺失导致“排队”FP。请重点标注异常车辆与可绕行性。",
        "trail_url": "http://auto-triage.intra.xiaojukeji.com/ra/model_triage/records/761?tab=results",
    },
    {
        "issue_id": "cn32044177",
        "title": "自车右转，摩自直行且有绕行空间",
        "scenario": "routing 方向 / 绕行空间",
        "summary": "模型判为等灯，但未判断 routing 方向和可绕行空间。",
        "review_note": "问题假设：routing 方向缺失导致“等灯”FP。",
        "trail_url": "http://auto-triage.intra.xiaojukeji.com/ra/model_triage/records/760?tab=results",
    },
    {
        "issue_id": "cn32000563",
        "title": "自车右转，在直行车道排队",
        "scenario": "routing 方向 / 右侧通行空间",
        "summary": "模型判为排队，未识别右侧可右转通行空间；SWAG 右变道后又左加塞回原车道，需复核。",
        "review_note": "问题假设：routing 方向缺失导致“排队”FP；需再 review SWAG 操作链。",
        "trail_url": "http://auto-triage.intra.xiaojukeji.com/ra/model_triage/records/764?tab=results",
    },
    {
        "issue_id": "cn31983487",
        "title": "自车右转，前车直行等灯且无绕行空间",
        "scenario": "routing 方向 / 无绕行空间",
        "summary": "模型判为等灯，但没有判断 routing 方向。",
        "review_note": "问题假设：routing 方向缺失导致“等灯”FP。",
        "trail_url": "http://auto-triage.intra.xiaojukeji.com/ra/model_triage/records/765?tab=results",
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
        "extra": row,
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
        return [row for row in rows if isinstance(row, dict)], metadata

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


def valid_model_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    if host in settings.allowed_model_hosts:
        return True
    if host.endswith(".intra.xiaojukeji.com"):
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_private or address.is_loopback or address.is_link_local
    except ValueError:
        return False


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


def sync_trail_model_fields() -> dict[str, Any]:
    """Create/reuse an immutable default model snapshot from the Trail view."""

    if not trail_sync_lock.acquire(blocking=False):
        return {
            **runtime_state["trail_sync"],
            "status": "running",
            "message": "已有 Trail 同步任务在运行。",
        }
    runtime_state["trail_sync"] = {
        "status": "running",
        "message": f"正在读取 Trail view {settings.trail_view_id}。",
        "run_id": "",
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
        }
        if TRAIL_RESULT_FIELD not in result.fields_visible:
            runtime_state["trail_sync"] = state
            return state
        normalized = [row for raw in result.rows if (row := normalize_model_row(raw))]
        usable = [row for row in normalized if row["model_label"]]
        if not usable:
            state.update(
                {
                    "status": "empty",
                    "message": result.message + " 字段已出现，但当前 1071 范围没有非空模型结果。",
                }
            )
            runtime_state["trail_sync"] = state
            return state
        snapshot_rows = sorted(usable, key=lambda row: row["issue_id"])
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
            },
            rows=snapshot_rows,
            kind="trail_snapshot",
            make_default=True,
        )
        state.update(
            {
                "status": "ready",
                "run_id": run["id"],
                "usable_predictions": len(usable),
                "duplicate": duplicate,
                "message": result.message + f" 已设为默认比较 run（{len(usable)} 条）。",
            }
        )
        runtime_state["trail_sync"] = state
        return state
    except Exception as exc:
        state = {
            "status": "failed",
            "message": f"Trail 模型字段同步失败: {exc}",
            "run_id": "",
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
        await asyncio.to_thread(sync_trail_model_fields)
    yield


app = FastAPI(
    title="RA Triage Workbench",
    version="0.2.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")


@app.get("/", include_in_schema=False)
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
        "default_failure_only": bool(database.default_model_run_id()),
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
        "storage": "SQLite MVP / PostgreSQL migration prepared",
        "allowed_model_endpoint_policy": "内网 IP、localhost、*.intra.xiaojukeji.com 或显式白名单",
    }


@app.get("/api/cases")
async def list_cases(
    search: str = "",
    gt_label: str = "",
    annotation_label: str = "",
    model_run_id: str = "",
    failure_only: bool = False,
    missing_evidence: str = "",
    page: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    return database.list_cases(
        baseline_scope=settings.baseline_scope,
        search=search,
        gt_label=gt_label,
        annotation_label=annotation_label,
        model_run_id=model_run_id,
        failure_only=failure_only,
        missing_evidence=missing_evidence,
        page=page,
        page_size=page_size,
    )


@app.get("/api/cases/{issue_id}")
async def get_case(issue_id: str) -> dict[str, Any]:
    case = database.get_case(issue_id)
    if case is None:
        raise _detail(404, "Issue 不存在。")
    case["assets"] = asset_index.get_assets(issue_id)
    case["camera"] = camera_index.get_assets(
        issue_id, (case["assets"].get("capture") or {}).get("timestamp_ms")
    )
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


@app.post("/api/cases/{issue_id}/annotations")
async def create_annotation(issue_id: str, request: Request) -> dict[str, Any]:
    if database.get_case(issue_id) is None:
        raise _detail(404, "Issue 不存在。")
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "标注请求必须是 JSON。")
    label = _as_text(body.get("label"))
    review_status = _as_text(body.get("review_status") or "pending")
    tags = body.get("tags") or []
    missing_evidence = body.get("missing_evidence") or []
    if not isinstance(tags, list):
        raise _detail(400, "tags 必须是数组。")
    if not isinstance(missing_evidence, list):
        raise _detail(400, "missing_evidence 必须是数组。")
    identity = request_identity(request, settings)
    try:
        annotation = database.create_annotation(
            issue_id=issue_id,
            label=label,
            review_status=review_status,
            tags=tags,
            missing_evidence=missing_evidence,
            note=_as_text(body.get("note")),
            author=(
                identity.username
                if identity.authenticated
                else _as_text(body.get("author"))
            ),
        )
    except ValueError as exc:
        raise _detail(400, str(exc))
    return {"annotation": annotation}


@app.get("/api/model-runs")
async def model_runs() -> dict[str, Any]:
    return {
        "items": database.list_model_runs(settings.baseline_scope),
        "default_model_run_id": database.default_model_run_id(),
    }


@app.post("/api/model-runs/{run_id}/default")
async def set_default_model_run(run_id: str) -> dict[str, Any]:
    run = database.set_default_model_run(run_id)
    if run is None:
        raise _detail(404, "模型 run 不存在。")
    return {"run": run, "default_model_run_id": run_id}


@app.get("/api/review-clusters")
async def review_clusters(model_run_id: str = "", failure_only: bool = True) -> dict[str, Any]:
    return {
        "items": database.review_clusters(
            baseline_scope=settings.baseline_scope,
            model_run_id=model_run_id,
            failure_only=failure_only,
        )
    }


@app.post("/api/trail-model-sync")
async def trail_model_sync() -> dict[str, Any]:
    return await asyncio.to_thread(sync_trail_model_fields)


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
    target = settings.uploads_dir / f"{source_hash[:12]}_{filename}"
    if not target.exists():
        target.write_bytes(content)
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
    file: UploadFile = File(...),
    run_name: str = Form(""),
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
    run, duplicate = database.import_model_run(
        name=_as_text(run_name) or default_name,
        source_name=filename,
        source_sha256=source_hash,
        metadata=metadata,
        rows=rows,
    )
    return {
        "run": run,
        "duplicate": duplicate,
        "filename": filename,
        "parsed_rows": len(source_rows),
        "accepted_rows": len(rows),
        "rejected_rows": len(source_rows) - len(rows),
    }


@app.post("/api/inference/jobs")
async def create_inference_job(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (TypeError, ValueError):
        raise _detail(400, "推理请求必须是 JSON。")
    issue_id = _as_text(body.get("issue_id"))
    if not ISSUE_ID_RE.fullmatch(issue_id) or database.get_case(issue_id) is None:
        raise _detail(404, "Issue 不存在或格式非法。")

    dry_run = bool(body.get("dry_run"))
    base_url = _as_text(body.get("base_url"))
    api_key = _as_text(body.get("api_key"))
    model_name = _as_text(body.get("model_name"))
    if not dry_run:
        if not valid_model_url(base_url):
            raise _detail(400, "模型 base URL 不在允许范围，或 URL 格式非法。")
        if not model_name or len(model_name) > 256:
            raise _detail(400, "模型名称为空或过长。")
        if not api_key or len(api_key) > 4096:
            raise _detail(400, "API key 为空或过长。")

    prompt_version = _as_text(body.get("prompt_version") or "stuck_triage_v1")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", prompt_version):
        raise _detail(400, "prompt_version 格式非法。")
    max_tokens = body.get("max_tokens", 512)
    try:
        max_tokens = int(max_tokens)
    except (TypeError, ValueError):
        raise _detail(400, "max_tokens 必须是整数。")
    if not 32 <= max_tokens <= 4096:
        raise _detail(400, "max_tokens 需在 32 到 4096 之间。")

    safe_request = {
        "issue_id": issue_id,
        "base_url": base_url,
        "model_name": model_name,
        "provider": _as_text(body.get("provider")),
        "prompt_version": prompt_version,
        "max_tokens": max_tokens,
        "temperature": body.get("temperature", 0.6),
        "use_bev_animation": bool(body.get("use_bev_animation", True)),
        "use_ra_options": bool(body.get("use_ra_options", True)),
        "dry_run": dry_run,
    }
    identity = request_identity(request, settings)
    job = database.create_job(
        issue_id=issue_id,
        requested_by=(
            identity.username
            if identity.authenticated
            else _as_text(body.get("requested_by"))
        ),
        model_name=model_name or "preflight",
        base_url=base_url,
        config={key: value for key, value in safe_request.items() if key != "base_url"},
    )
    inference_runner.launch(job, {**safe_request, "api_key": api_key})
    return {
        "job": job,
        "safety": {
            "trail_write_enabled": False,
            "api_key_persisted": False,
            "api_key_in_argv": False,
            "bag_cache_read_only": True,
        },
    }


@app.get("/api/inference/jobs/{job_id}")
async def get_inference_job(job_id: str) -> dict[str, Any]:
    job = database.get_job(job_id)
    if job is None:
        raise _detail(404, "任务不存在。")
    return {"job": job}
