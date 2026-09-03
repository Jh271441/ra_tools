"""Trail attribute update imports domain."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from ...contracts import ISSUE_ID_RE
from ...support.common import _as_text
from ...issue_tag_sources import HISTORICAL_EXCLUSION_SOURCE_KIND
from ...runtime import issue_tag_sources
from ...trail_exclusion_contracts import TRAIL_ISSUE_IMPORT_PREVIEW_SCHEMA


_HISTORICAL_EXCLUSION_SOURCE_FIELDS = (
    "kind",
    "source_id",
    "label",
    "baseline_id",
    "filename",
    "sha256",
    "row_number",
    "issue_id",
    "column",
    "value",
)

_TRAIL_ISSUE_IMPORT_MAX_SOURCE_ROWS = 5_000

_TRAIL_ISSUE_IMPORT_MAX_ENTRIES = 200

_TRAIL_ISSUE_IMPORT_ISSUE_ALIASES = (
    "issue_id",
    "issue id",
    "issueid",
    "issue",
    "问题id",
    "问题编号",
    "问题号",
)

_TRAIL_ISSUE_IMPORT_EXCLUDE_ALIASES = (
    "是否排除",
    "should_exclude",
    "should exclude",
    "isexcluded",
    "is_excluded",
    "exclude",
    "excluded",
    "排除",
    "需要排除",
)

_TRAIL_ISSUE_IMPORT_COMMENT_ALIASES = (
    "comment",
    "note",
    "exclusion_note",
    "exclusion comment",
    "排除说明",
    "备注",
    "说明",
    "原因",
    "reason",
    "should_exclude_comment",
)

_TRAIL_ISSUE_IMPORT_TRUE_VALUES = frozenset(
    {"1", "true", "yes", "y", "是", "排除", "需要排除", "需排除"}
)

_TRAIL_ISSUE_IMPORT_FALSE_VALUES = frozenset(
    {"0", "false", "no", "n", "否", "不排除", "无需排除", "不需要排除"}
)

def _append_historical_source_note(note: str, source_note: str) -> str:
    """Keep an existing Review note while making historical provenance visible."""

    current = _as_text(note).strip()
    source = _as_text(source_note).strip()
    if not source:
        return current[:4000]
    if source in current:
        return current[:4000]
    if not current:
        return source[:4000]
    # Preserve the provenance even for a previously max-length note.  The
    # original human note stays first and is clipped only as much as needed.
    available = max(0, 4000 - len(source) - 2)
    return f"{current[:available].rstrip()}\n\n{source}"[:4000]

def _historical_source_payload(value: Any) -> dict[str, Any] | None:
    """Copy the bounded, server-verified provenance shape into public drafts."""

    if not isinstance(value, Mapping):
        return None
    if _as_text(value.get("kind")) != HISTORICAL_EXCLUSION_SOURCE_KIND:
        return None
    source: dict[str, Any] = {}
    for key in _HISTORICAL_EXCLUSION_SOURCE_FIELDS:
        raw = value.get(key)
        if key == "row_number":
            try:
                number = int(raw)
            except (TypeError, ValueError):
                return None
            if number < 1:
                return None
            source[key] = number
            continue
        text = _as_text(raw).strip()
        if not text:
            return None
        source[key] = text[:512]
    return source

def _resolve_historical_exclusion_entries(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Replace browser hints with the exact loaded-XLSX source and comment."""

    resolved: list[dict[str, Any]] = []
    invalid: list[str] = []
    for entry in entries:
        issue_id = _as_text(entry.get("issue_id")).strip()
        source = entry.get("source")
        if source is None:
            resolved.append(
                {"issue_id": issue_id, "comment": _as_text(entry.get("comment")).strip()[:4000]}
            )
            continue
        if not isinstance(source, Mapping):
            invalid.append(f"{issue_id}（历史抽检来源格式无效）")
            continue
        candidate = issue_tag_sources.resolve_exclusion_candidate(
            issue_id=issue_id,
            source=source,
        )
        if candidate is None:
            invalid.append(f"{issue_id}（历史抽检来源无效或已变化）")
            continue
        resolved_source = _historical_source_payload(candidate.get("source"))
        if resolved_source is None:
            # This is an internal contract failure.  Do not accept a source
            # record that cannot be represented in the signed preview.
            invalid.append(f"{issue_id}（历史抽检来源不可用）")
            continue
        resolved.append(
            {
                "issue_id": issue_id,
                "comment": _as_text(candidate.get("comment")).strip()[:4000],
                "source": resolved_source,
            }
        )
    resolved.sort(key=lambda item: item["issue_id"])
    return resolved, invalid

def _issue_import_header_key(value: Any) -> str:
    """Normalize a user-facing upload header without changing its value."""

    return re.sub(r"[\s_\-./（）()\[\]{}]+", "", _as_text(value)).casefold()

def _issue_import_normalized_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        normalized_key = _issue_import_header_key(key)
        if normalized_key and normalized_key not in normalized:
            normalized[normalized_key] = value
    return normalized

def _issue_import_field(
    row: Mapping[str, Any],
    aliases: tuple[str, ...],
) -> tuple[bool, Any]:
    """Return whether an aliased column exists, keeping False/0 values intact."""

    normalized = _issue_import_normalized_row(row)
    found = False
    for alias in aliases:
        key = _issue_import_header_key(alias)
        if key not in normalized:
            continue
        found = True
        value = normalized[key]
        # If duplicate equivalent columns exist, prefer a non-empty one while
        # still reporting that the field itself was present.
        if _as_text(value):
            return True, value
    return found, ""

def _issue_import_has_column(
    rows: list[Any],
    aliases: tuple[str, ...],
) -> bool:
    return any(
        isinstance(row, Mapping) and _issue_import_field(row, aliases)[0]
        for row in rows
    )

def _issue_import_exclusion_value(value: Any) -> bool | None:
    """Parse a deliberate yes/no cell; never use generic truthiness here."""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
    text = re.sub(r"\s+", "", _as_text(value)).casefold()
    if text in _TRAIL_ISSUE_IMPORT_TRUE_VALUES:
        return True
    if text in _TRAIL_ISSUE_IMPORT_FALSE_VALUES:
        return False
    return None

def _issue_import_issue_ids(value: Any) -> list[str]:
    """Accept one ID per cell, plus comma/newline-separated legacy JSON IDs."""

    if isinstance(value, (list, tuple)):
        ids: list[str] = []
        for item in value:
            ids.extend(_issue_import_issue_ids(item))
        return ids
    text = _as_text(value).strip()
    if not text:
        return []
    return [
        item.strip()
        for item in re.split(r"[\n\r,，、;；|]+", text)
        if item.strip()
    ]

def _issue_import_display_filename(value: Any) -> str:
    """Expose a bounded basename only; upload paths must never reach the UI."""

    raw = _as_text(value).replace("\\", "/")
    filename = Path(raw).name
    filename = re.sub(r"[\x00-\x1f\x7f]+", "", filename).strip()
    return filename[:120] or "issue-exclusions.xlsx"

def _issue_import_excel_source_note(
    *,
    filename: str,
    sheet: str,
    row_number: int,
    source_sha256: str,
) -> str:
    """Persist enough file provenance in the comment for later Trail audit."""

    return (
        f"Excel 上传来源：{filename}（工作表「{sheet}」第 {row_number} 行；"
        f"SHA-256: {source_sha256}；“是否排除”=“是”）。"
    )

def _issue_import_json_rows(value: Any) -> tuple[list[Any], dict[str, Any]]:
    """Extract legacy/exported Issue drafts into ordinary import rows.

    A downloaded Issue preview contains a nested ``draft`` and may carry a
    per-Issue comment map.  This extraction deliberately mirrors the old
    browser-only importer while moving validation and source handling to the
    server-side preview contract.
    """

    if isinstance(value, list):
        return list(value), {"fallback_comment": "", "comment_by_issue": {}}
    if not isinstance(value, Mapping):
        raise ValueError("JSON 顶层必须是对象或数组。")

    current: Any = value
    fallback_comment = ""
    comment_by_issue: dict[str, str] = {}
    for _ in range(4):
        if not isinstance(current, Mapping):
            break
        candidate_comment = _as_text(current.get("comment")).strip()[:4000]
        if candidate_comment:
            fallback_comment = candidate_comment
        candidate_comments = current.get("comment_by_issue")
        if isinstance(candidate_comments, Mapping):
            for issue_id, note in candidate_comments.items():
                normalized_issue_id = _as_text(issue_id).strip()
                if normalized_issue_id:
                    comment_by_issue[normalized_issue_id] = _as_text(note).strip()[:4000]
        nested = next(
            (
                current.get(key)
                for key in ("draft", "payload", "data")
                if isinstance(current.get(key), (Mapping, list))
            ),
            None,
        )
        if nested is None:
            break
        current = nested

    if isinstance(current, list):
        return list(current), {
            "fallback_comment": fallback_comment,
            "comment_by_issue": comment_by_issue,
        }
    if not isinstance(current, Mapping):
        raise ValueError("JSON 顶层必须是对象或数组。")

    for key in (
        "requested_entries",
        "entries",
        "items",
        "rows",
        "results",
        "issue_ids",
        "requested_issue_ids",
    ):
        if key not in current:
            continue
        raw_rows = current.get(key)
        if isinstance(raw_rows, (list, tuple)):
            rows = list(raw_rows)
        elif raw_rows is None:
            rows = []
        else:
            rows = [raw_rows]
        return rows, {
            "fallback_comment": fallback_comment or _as_text(current.get("comment")).strip()[:4000],
            "comment_by_issue": comment_by_issue,
        }
    if any(_issue_import_header_key(key) in {
        _issue_import_header_key(alias) for alias in _TRAIL_ISSUE_IMPORT_ISSUE_ALIASES
    } for key in current):
        return [dict(current)], {
            "fallback_comment": fallback_comment,
            "comment_by_issue": comment_by_issue,
        }
    raise ValueError("未找到 Issue ID 列表；请提供 entries、requested_entries 或 issue_ids。")

def build_trail_issue_import_preview(
    raw_rows: list[Any],
    *,
    import_format: str,
    filename: str = "",
    source_sha256: str = "",
    metadata: Mapping[str, Any] | None = None,
    fallback_comment: str = "",
    comment_by_issue: Mapping[str, Any] | None = None,
    require_exclusion_column: bool = False,
    row_number_offset: int = 1,
) -> dict[str, Any]:
    """Build a pure, non-writing preview for JSON/XLSX Issue shielding.

    Only rows whose explicit ``是否排除`` value is true become editor entries.
    False rows remain visible as skipped, and malformed IDs/flags/duplicates
    keep the preview non-applicable so no row is silently discarded.
    """

    mode = "excel" if import_format == "excel" else "json"
    all_rows = list(raw_rows)
    rows = all_rows[:_TRAIL_ISSUE_IMPORT_MAX_SOURCE_ROWS]
    sheet = _as_text((metadata or {}).get("sheet")).strip()[:120] or "Sheet1"
    normalized_filename = _issue_import_display_filename(filename) if filename else ""
    normalized_hash = _as_text(source_sha256).strip()[:128]
    normalized_fallback_comment = _as_text(fallback_comment).strip()[:4000]
    normalized_comment_by_issue = {
        _as_text(issue_id).strip(): _as_text(note).strip()[:4000]
        for issue_id, note in (comment_by_issue or {}).items()
        if _as_text(issue_id).strip()
    }
    global_errors: list[str] = []
    warnings: list[str] = []
    if len(all_rows) > _TRAIL_ISSUE_IMPORT_MAX_SOURCE_ROWS:
        global_errors.append(
            f"导入最多预览 {_TRAIL_ISSUE_IMPORT_MAX_SOURCE_ROWS} 行；当前文件有 {len(all_rows)} 行。"
        )
    if not all_rows:
        global_errors.append("未找到可解析的数据行。")
    if require_exclusion_column and all_rows and not _issue_import_has_column(
        rows, _TRAIL_ISSUE_IMPORT_EXCLUDE_ALIASES
    ):
        global_errors.append("缺少必填列「是否排除」（也支持 should_exclude / is_excluded）。")

    items: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    seen_selected: set[str] = set()
    defaulted_exclusion_count = 0
    invalid_count = 0
    skipped_count = 0
    for index, raw_row in enumerate(rows):
        row_number = index + row_number_offset
        if isinstance(raw_row, Mapping):
            row = raw_row
        elif mode == "json":
            row = {"issue_id": raw_row}
        else:
            invalid_count += 1
            items.append(
                {
                    "row_number": row_number,
                    "issue_id": "",
                    "should_exclude": None,
                    "comment": "",
                    "status": "invalid",
                    "message": "该行不是可识别的对象。",
                }
            )
            continue

        has_issue_column, raw_issue_ids = _issue_import_field(
            row, _TRAIL_ISSUE_IMPORT_ISSUE_ALIASES
        )
        issue_ids = _issue_import_issue_ids(raw_issue_ids) if has_issue_column else []
        has_exclusion_column, raw_exclusion = _issue_import_field(
            row, _TRAIL_ISSUE_IMPORT_EXCLUDE_ALIASES
        )
        should_exclude = _issue_import_exclusion_value(raw_exclusion)
        blank_exclusion = has_exclusion_column and not _as_text(raw_exclusion)
        used_legacy_default = mode == "json" and not has_exclusion_column
        if used_legacy_default:
            should_exclude = True
            defaulted_exclusion_count += 1
        _, raw_comment = _issue_import_field(row, _TRAIL_ISSUE_IMPORT_COMMENT_ALIASES)
        provided_comment = _as_text(raw_comment).strip()[:4000]
        raw_source = row.get("source") if isinstance(row, Mapping) else None
        source: dict[str, Any] | None = None
        source_error = ""
        if raw_source is not None:
            source = _historical_source_payload(raw_source)
            if source is None:
                source_error = "标注来源格式无效。"

        if not issue_ids:
            invalid_count += 1
            items.append(
                {
                    "row_number": row_number,
                    "issue_id": "",
                    "should_exclude": should_exclude,
                    "comment": provided_comment,
                    "status": "invalid",
                    "message": "缺少 Issue ID。",
                }
            )
            continue

        for issue_id in issue_ids:
            item: dict[str, Any] = {
                "row_number": row_number,
                "issue_id": issue_id[:128],
                "should_exclude": should_exclude,
                "comment": provided_comment,
                "status": "invalid",
                "message": "",
            }
            if not ISSUE_ID_RE.fullmatch(issue_id):
                invalid_count += 1
                item["message"] = "Issue ID 格式无效。"
                items.append(item)
                continue
            # Historical spot-check files leave ordinary rows blank instead
            # of explicitly writing “否”.  That is a clear non-selection,
            # not an invalid exclusion request: keep it visible as skipped so
            # the true rows can still be reviewed and imported together.
            if mode == "excel" and blank_exclusion:
                skipped_count += 1
                item["status"] = "skipped"
                item["message"] = "未填写是否排除；不会进入屏蔽草稿。"
                item["source_label"] = (
                    f"上传 Excel · {normalized_filename} · {sheet} 第 {row_number} 行"
                )
                items.append(item)
                continue
            if should_exclude is None:
                invalid_count += 1
                item["message"] = (
                    "「是否排除」仅支持 是/否、true/false、1/0。"
                    if has_exclusion_column
                    else "缺少必填列「是否排除」。"
                )
                items.append(item)
                continue
            if should_exclude is False:
                skipped_count += 1
                item["status"] = "skipped"
                item["message"] = "是否排除=否；不会进入屏蔽草稿。"
                if mode == "excel":
                    item["source_label"] = (
                        f"上传 Excel · {normalized_filename} · {sheet} 第 {row_number} 行"
                    )
                items.append(item)
                continue
            if source_error:
                invalid_count += 1
                item["message"] = source_error
                items.append(item)
                continue
            if source is not None and _as_text(source.get("issue_id")) != issue_id:
                invalid_count += 1
                item["message"] = "标注来源中的 Issue ID 与当前行不一致。"
                items.append(item)
                continue
            if issue_id in seen_selected:
                invalid_count += 1
                item["message"] = "该 Issue ID 与另一条“是否排除=是”的行重复。"
                items.append(item)
                continue

            seen_selected.add(issue_id)
            effective_comment = (
                normalized_comment_by_issue.get(issue_id)
                or provided_comment
                or normalized_fallback_comment
            )[:4000]
            if mode == "excel":
                source_note = _issue_import_excel_source_note(
                    filename=normalized_filename,
                    sheet=sheet,
                    row_number=row_number,
                    source_sha256=normalized_hash,
                )
                effective_comment = _append_historical_source_note(
                    effective_comment, source_note
                )
                item["source_label"] = (
                    f"上传 Excel · {normalized_filename} · {sheet} 第 {row_number} 行"
                )
            elif source is not None:
                item["source"] = source
            item["comment"] = effective_comment
            item["status"] = "ready"
            item["message"] = "将替换到屏蔽草稿；尚未写入 Trail。"
            entry: dict[str, Any] = {
                "issue_id": issue_id,
                "comment": effective_comment,
            }
            if source is not None:
                entry["source"] = source
            entries.append(entry)
            items.append(item)

    if defaulted_exclusion_count:
        warnings.append(
            f"{defaulted_exclusion_count} 行 JSON 未提供「是否排除」，已按“是”兼容旧草稿。"
        )
    if len(entries) > _TRAIL_ISSUE_IMPORT_MAX_ENTRIES:
        global_errors.append(
            f"单次按 Issue ID 屏蔽最多支持 {_TRAIL_ISSUE_IMPORT_MAX_ENTRIES} 条；当前有 {len(entries)} 条“是”。"
        )
    ready_count = len(entries)
    if global_errors:
        message = global_errors[0]
    elif invalid_count:
        message = f"发现 {invalid_count} 条需修正的行；修正后才能替换草稿。"
    elif not ready_count:
        message = "没有“是否排除=是”的行可导入。"
    else:
        message = f"预览就绪：{ready_count} 条将进入屏蔽草稿；尚未写入 Trail。"
    return {
        "schema_version": TRAIL_ISSUE_IMPORT_PREVIEW_SCHEMA,
        "mode": mode,
        "filename": normalized_filename,
        "source_sha256": normalized_hash,
        "metadata": {"sheet": sheet} if mode == "excel" else {},
        "contract": {
            "required": ["issue_id", "是否排除"] if mode == "excel" else ["issue_id"],
            "optional": ["comment"],
            "exclude_aliases": ["是否排除", "should_exclude", "is_excluded"],
        },
        "summary": {
            "source_row_count": len(all_rows),
            "previewed_row_count": len(rows),
            "ready_count": ready_count,
            "skipped_count": skipped_count,
            "invalid_count": invalid_count,
            "message": message,
        },
        "global_errors": global_errors,
        "warnings": warnings,
        "items": items,
        "entries": entries,
        "can_apply": bool(entries) and not invalid_count and not global_errors,
    }
