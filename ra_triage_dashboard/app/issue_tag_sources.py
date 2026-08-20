from __future__ import annotations

"""Read-only, auditable Issue-tag suggestions from historical spot checks.

Historical workbooks are useful reviewer hints, but they are not baseline GT and
must never create or overwrite Review annotations at startup.  This module
keeps those two roles separate: it maps stable worksheet tag columns into the
Dashboard catalog and exposes an ephemeral suggestion with source provenance.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import threading
from typing import Any, Iterable, Mapping

from .contracts import ISSUE_ID_RE, MAX_UPLOAD_BYTES
from .import_parsing import parse_source_bytes


_LABEL_ALIASES = {
    "误触发": "误触发",
    "false_positive": "误触发",
    "fp": "误触发",
    "正确触发": "正确触发",
    "成功": "正确触发",
    "失败": "正确触发",
    "true_positive": "正确触发",
    "tp": "正确触发",
    "无需协助": "无需协助",
    "不需要协助": "无需协助",
    "不需协助": "无需协助",
}
_EXCLUDED_VALUES = frozenset({"1", "true", "yes", "y", "是", "排除"})
_TAG_SPLIT_RE = re.compile(r"\s*(?:&&|/|／|、|,|，)\s*")

# The source workbooks use these four columns.  Keys intentionally point only
# to the source-controlled Dashboard catalog; source-only wording stays in the
# provenance payload rather than becoming arbitrary user-created Tags.
_SOURCE_TAG_COLUMNS: tuple[tuple[str, str, Mapping[str, str]], ...] = (
    (
        "误触发Tag",
        "false_trigger",
        {
            "等灯": "traffic_light",
            "排队": "queue",
            "让行": "yielding",
            "掉头": "u_turn",
            "泊入": "park_in",
            "泊出": "park_out",
            "人工误触发": "scene_false_other",
            "其他": "scene_false_other",
        },
    ),
    (
        "应该触发Tag",
        "true_trigger",
        {
            "未避障": "obstacle_not_avoided",
            "距离近": "close_distance",
            "感知fp": "perception_fp",
            "eol": "true_eol",
            "地图变更": "true_map_change",
            "红绿灯无灯坏": "true_traffic_light_unavailable",
            "多余变道": "true_unnecessary_lane_change",
            "其他": "scene_true_other",
        },
    ),
    (
        "如何驶离Tag",
        "ra",
        {
            "swag": "egress_swag",
            "左右绕行": "egress_detour",
            "waypoint": "egress_waypoint",
            "倒车": "egress_reverse",
            "红绿灯通行": "egress_traffic_light",
            "接管": "egress_takeover",
            "其他": "egress_ra_other",
        },
    ),
    (
        "无需协助Tag",
        "no_assist",
        {
            "前车驶离": "lead_vehicle_departed",
            "主系统决策变化": "system_decision_change",
            "感知fp变化": "perception_fp_change",
            "其他": "egress_no_assist_other",
        },
    ),
)
_EXPECTED_OUTPUT_BY_SOURCE_GROUP = {
    "false_trigger": "误触发",
    "ra": "正确触发",
    "no_assist": "无需协助",
}


@dataclass(frozen=True)
class IssueTagSourceSpec:
    source_id: str
    label: str
    baseline_id: str
    path: Path


@dataclass(frozen=True)
class IssueTagSuggestion:
    source_id: str
    source_label: str
    baseline_id: str
    source_filename: str
    source_sha256: str
    row_number: int
    issue_id: str
    expected_output: str
    is_excluded: bool
    tags: tuple[str, ...]
    raw_tags: tuple[dict[str, str], ...]
    unmapped_tags: tuple[dict[str, str], ...]

    def public(self) -> dict[str, Any]:
        return {
            "status": "partial" if self.unmapped_tags else "ready",
            "source": {
                "id": self.source_id,
                "label": self.source_label,
                "baseline_id": self.baseline_id,
                "filename": self.source_filename,
                "sha256": self.source_sha256,
                "row_number": self.row_number,
            },
            # This object deliberately has the same stable fields as a Review
            # draft but no id/author/timestamp: it is never a persisted Review.
            "annotation": {
                "expected_output": self.expected_output,
                "label": self.expected_output,
                "is_excluded": self.is_excluded,
                "tags": list(self.tags),
            },
            "unmapped_tags": [dict(item) for item in self.unmapped_tags],
        }


@dataclass(frozen=True)
class IssueTagSourceLoad:
    spec: IssueTagSourceSpec
    source_sha256: str
    suggestions: Mapping[str, IssueTagSuggestion]
    parsed_rows: int
    skipped_rows: int
    duplicate_issue_ids: tuple[str, ...]
    conflicted_issue_ids: tuple[str, ...]
    unmapped_tag_count: int

    def public_status(self) -> dict[str, Any]:
        return {
            "source_id": self.spec.source_id,
            "label": self.spec.label,
            "baseline_id": self.spec.baseline_id,
            "filename": self.spec.path.name,
            "available": True,
            "parsed_rows": self.parsed_rows,
            "suggestion_count": len(self.suggestions),
            "skipped_rows": self.skipped_rows,
            "duplicate_issue_count": len(self.duplicate_issue_ids),
            "conflicted_issue_count": len(self.conflicted_issue_ids),
            "unmapped_tag_count": self.unmapped_tag_count,
            "sha256": self.source_sha256,
        }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _header_key(value: Any) -> str:
    return _text(value).casefold().replace(" ", "")


def _normalized_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        key_text = _header_key(key)
        if key_text and key_text not in normalized:
            normalized[key_text] = value
    return normalized


def _row_value(row: Mapping[str, Any], *aliases: str) -> str:
    for alias in aliases:
        value = row.get(_header_key(alias))
        text = _text(value)
        if text:
            return text
    return ""


def _canonical_label(value: Any) -> str:
    text = _text(value)
    return _LABEL_ALIASES.get(text.casefold(), "")


def _is_excluded(value: Any) -> bool:
    return _text(value).casefold() in _EXCLUDED_VALUES


def _split_tags(value: str) -> tuple[str, ...]:
    return tuple(
        part.strip()
        for part in _TAG_SPLIT_RE.split(value)
        if part and part.strip()
    )


def _source_row_to_suggestion(
    *,
    spec: IssueTagSourceSpec,
    source_sha256: str,
    row_number: int,
    raw_row: Mapping[str, Any],
) -> IssueTagSuggestion | None:
    row = _normalized_row(raw_row)
    issue_id = _row_value(row, "issue_id", "issue id", "问题id", "问题 id")
    if not ISSUE_ID_RE.fullmatch(issue_id):
        return None
    source_label = _canonical_label(_row_value(row, "label", "合并标注"))
    tags: list[str] = []
    raw_tags: list[dict[str, str]] = []
    unmapped_tags: list[dict[str, str]] = []
    inferred_outputs: set[str] = set()
    for column, group, mapping in _SOURCE_TAG_COLUMNS:
        raw_value = _row_value(row, column)
        if not raw_value:
            continue
        raw_tags.append({"column": column, "value": raw_value})
        normalized_mapping = {
            key.casefold(): value for key, value in mapping.items()
        }
        for source_tag in _split_tags(raw_value):
            target = normalized_mapping.get(source_tag.casefold())
            if not target:
                unmapped_tags.append({"column": column, "value": source_tag})
                continue
            if target not in tags:
                tags.append(target)
            output = _EXPECTED_OUTPUT_BY_SOURCE_GROUP.get(group)
            if output:
                inferred_outputs.add(output)
    # Do not use a contradictory source row to pre-fill a human Review.  It
    # remains visible in loader diagnostics, but the reviewer has to decide.
    if len(inferred_outputs) > 1:
        return None
    inferred_output = next(iter(inferred_outputs), "")
    if source_label and inferred_output and source_label != inferred_output:
        return None
    expected_output = source_label or inferred_output
    if not tags and not expected_output and not _is_excluded(_row_value(row, "是否排除")):
        return None
    return IssueTagSuggestion(
        source_id=spec.source_id,
        source_label=spec.label,
        baseline_id=spec.baseline_id,
        source_filename=spec.path.name,
        source_sha256=source_sha256,
        row_number=row_number,
        issue_id=issue_id,
        expected_output=expected_output,
        is_excluded=_is_excluded(_row_value(row, "是否排除")),
        tags=tuple(tags),
        raw_tags=tuple(raw_tags),
        unmapped_tags=tuple(unmapped_tags),
    )


def load_issue_tag_source(spec: IssueTagSourceSpec) -> IssueTagSourceLoad:
    """Load one bounded, read-only historical worksheet into suggestion rows."""

    path = spec.path
    try:
        stat_result = path.stat()
    except OSError as exc:
        raise ValueError("Issue 标签来源文件不可用。") from exc
    if not path.is_file():
        raise ValueError("Issue 标签来源必须是普通文件。")
    if stat_result.st_size > MAX_UPLOAD_BYTES:
        raise ValueError("Issue 标签来源文件超过 64 MB 限制。")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ValueError("Issue 标签来源文件不可读。") from exc
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Issue 标签来源文件超过 64 MB 限制。")
    rows, _ = parse_source_bytes(path.name, content)
    digest = sha256(content).hexdigest()
    suggestions: dict[str, IssueTagSuggestion] = {}
    duplicate_ids: set[str] = set()
    conflicted_ids: set[str] = set()
    skipped_rows = 0
    unmapped_tag_count = 0
    for row_number, row in enumerate(rows, start=2):
        suggestion = _source_row_to_suggestion(
            spec=spec,
            source_sha256=digest,
            row_number=row_number,
            raw_row=row,
        )
        if suggestion is None:
            skipped_rows += 1
            continue
        if suggestion.issue_id in suggestions:
            duplicate_ids.add(suggestion.issue_id)
            suggestions.pop(suggestion.issue_id, None)
            continue
        if suggestion.issue_id in duplicate_ids:
            continue
        suggestions[suggestion.issue_id] = suggestion
        unmapped_tag_count += len(suggestion.unmapped_tags)
    # A source row can be valid structurally but disagree with its own
    # direction tags. Re-read only its identity to report it as a conflict
    # instead of a generic skipped row.
    for row in rows:
        normalized = _normalized_row(row)
        issue_id = _row_value(normalized, "issue_id", "issue id", "问题id", "问题 id")
        source_label = _canonical_label(_row_value(normalized, "label", "合并标注"))
        if not ISSUE_ID_RE.fullmatch(issue_id) or not source_label:
            continue
        source_outputs: set[str] = set()
        for column, group, _ in _SOURCE_TAG_COLUMNS:
            if _row_value(normalized, column) and group in _EXPECTED_OUTPUT_BY_SOURCE_GROUP:
                source_outputs.add(_EXPECTED_OUTPUT_BY_SOURCE_GROUP[group])
        if len(source_outputs) > 1 or (
            len(source_outputs) == 1 and source_label not in source_outputs
        ):
            conflicted_ids.add(issue_id)
            suggestions.pop(issue_id, None)
    return IssueTagSourceLoad(
        spec=spec,
        source_sha256=digest,
        suggestions=suggestions,
        parsed_rows=len(rows),
        skipped_rows=skipped_rows,
        duplicate_issue_ids=tuple(sorted(duplicate_ids)),
        conflicted_issue_ids=tuple(sorted(conflicted_ids)),
        unmapped_tag_count=unmapped_tag_count,
    )


class IssueTagSourceIndex:
    """Atomically swaps read-only source suggestions after local startup load."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._suggestions: dict[tuple[str, str], IssueTagSuggestion] = {}
        self._statuses: tuple[dict[str, Any], ...] = ()

    def reload(self, specs: Iterable[IssueTagSourceSpec]) -> tuple[dict[str, Any], ...]:
        suggestions: dict[tuple[str, str], IssueTagSuggestion] = {}
        statuses: list[dict[str, Any]] = []
        for spec in specs:
            try:
                loaded = load_issue_tag_source(spec)
            except Exception:
                # These files are optional historical hints.  A missing or
                # malformed source must never prevent the Dashboard from
                # serving its immutable baseline or existing Reviews.
                statuses.append(
                    {
                        "source_id": spec.source_id,
                        "label": spec.label,
                        "baseline_id": spec.baseline_id,
                        "filename": spec.path.name,
                        "available": False,
                        "suggestion_count": 0,
                    }
                )
                continue
            statuses.append(loaded.public_status())
            for issue_id, suggestion in loaded.suggestions.items():
                key = (spec.baseline_id, issue_id)
                if key not in suggestions:
                    suggestions[key] = suggestion
        frozen_statuses = tuple(statuses)
        with self._lock:
            self._suggestions = suggestions
            self._statuses = frozen_statuses
        return frozen_statuses

    def lookup(self, *, baseline_id: str, issue_id: str) -> dict[str, Any] | None:
        with self._lock:
            suggestion = self._suggestions.get(
                (str(baseline_id or "").strip(), str(issue_id or "").strip())
            )
        return suggestion.public() if suggestion is not None else None

    def statuses(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(dict(status) for status in self._statuses)
