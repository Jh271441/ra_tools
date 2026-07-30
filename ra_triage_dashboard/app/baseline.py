from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl

from .db import LABELS


@dataclass(frozen=True)
class BaselineLoad:
    rows: list[dict[str, Any]]
    source_rows: int
    skipped_rows: int
    message: str


def load_label_baseline(path: Path, dataset: str) -> BaselineLoad:
    """Load the immutable Trail-label snapshot without consulting live Trail.

    The workbook is deliberately the GT authority for this dashboard.  It is
    filtered by its ``dataset`` column so the 0508 working set remains the
    1071-case snapshot even when the workbook also contains 0206 and other
    releases.
    """

    if not path.is_file():
        return BaselineLoad([], 0, 0, f"基线文件不存在: {path}")
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if "labels" not in workbook.sheetnames:
        return BaselineLoad([], 0, 0, "基线 Excel 缺少 labels sheet。")
    sheet = workbook["labels"]
    values = sheet.iter_rows(values_only=True)
    headers = next(values, None)
    if not headers:
        return BaselineLoad([], 0, 0, "基线 Excel 缺少表头。")
    index = {str(value).strip(): position for position, value in enumerate(headers) if value}
    required = {"dataset", "issue_id", "Final Label"}
    missing = sorted(required - set(index))
    if missing:
        return BaselineLoad([], 0, 0, f"基线 Excel 缺少列: {', '.join(missing)}")

    rows: list[dict[str, Any]] = []
    source_rows = skipped_rows = 0
    for raw in values:
        if not raw or not any(value not in (None, "") for value in raw):
            continue
        if str(raw[index["dataset"]] or "").strip() != dataset:
            continue
        source_rows += 1
        issue_id = str(raw[index["issue_id"]] or "").strip()
        label = str(raw[index["Final Label"]] or "").strip()
        if not issue_id or label not in LABELS:
            skipped_rows += 1
            continue
        extra = {
            key: raw[position]
            for key, position in index.items()
            if position < len(raw) and raw[position] not in (None, "")
        }
        rows.append(
            {
                "issue_id": issue_id,
                "gt_label": label,
                "gt_source": f"{path.name}:labels.dataset={dataset}",
                "scenario": str(extra.get("source_dataset_label") or "").strip(),
                "extra": {"baseline": extra},
            }
        )
    message = f"已读取 {dataset} 基线 {len(rows)} 条"
    if skipped_rows:
        message += f"，跳过 {skipped_rows} 条无效记录"
    return BaselineLoad(rows, source_rows, skipped_rows, message)
