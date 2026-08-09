from __future__ import annotations

"""Pure, bounded parsers for imported Issue and model-result artifacts."""

import csv
import io
import json
import math
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

import openpyxl

from .contracts import (
    ISSUE_ID_RE,
    MAX_SPREADSHEET_ARCHIVE_ENTRIES,
    MAX_SPREADSHEET_COMPRESSION_RATIO,
    MAX_SPREADSHEET_UNCOMPRESSED_BYTES,
)
from .db import LABELS
from .sanitization import redact_sensitive_fields


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
    label = (
        _canonical_gt_label(raw_label)
        or _label_from_structured(result_info)
        or _label_from_structured(info)
    )
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


def _validate_spreadsheet_archive(content: bytes) -> None:
    """Reject malformed or excessively expanding Office ZIP containers."""

    try:
        with ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_SPREADSHEET_ARCHIVE_ENTRIES:
                raise ValueError("Excel 压缩包文件项过多。")
            total_uncompressed = 0
            total_compressed = 0
            for entry in entries:
                total_uncompressed += max(int(entry.file_size), 0)
                total_compressed += max(int(entry.compress_size), 0)
                if total_uncompressed > MAX_SPREADSHEET_UNCOMPRESSED_BYTES:
                    raise ValueError("Excel 解压后内容超过 256 MiB。")
            if total_uncompressed and total_compressed == 0:
                raise ValueError("Excel 压缩包结构异常。")
            if (
                total_compressed
                and total_uncompressed / total_compressed
                > MAX_SPREADSHEET_COMPRESSION_RATIO
            ):
                raise ValueError("Excel 压缩比异常，已拒绝解析。")
    except BadZipFile as exc:
        raise ValueError("Excel 文件不是有效的 Office 压缩包。") from exc


def parse_source_bytes(
    filename: str, content: bytes
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
        return [row for row in rows if isinstance(row, dict)], redact_sensitive_fields(metadata)

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
        _validate_spreadsheet_archive(content)
        workbook = openpyxl.load_workbook(
            io.BytesIO(content), read_only=True, data_only=True
        )
        try:
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
        finally:
            workbook.close()

    raise ValueError("仅支持 .json、.csv、.xlsx 或 .xlsm。")
