"""Externalized dataset display labels and logical union rules for task naming."""
from __future__ import annotations

from typing import Mapping, Sequence

from ..dataset_partitions import PARTITION_IDS, SOURCE_IDS

PARTITION_DISPLAY_LABELS: dict[str, str] = {
    PARTITION_IDS[0]: "0821 · ODD2",
    PARTITION_IDS[1]: "0821 · 非ODD2",
}

LOGICAL_DATASET_UNIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("0821", tuple(SOURCE_IDS)),
    ("1009 2026-10-15", ("1009-2026-10-15", "review-2026-10-15-extra")),
    ("1009 2026-10-16", ("1009-2026-10-16", "review-2026-10-16-extra")),
    ("1009 2026-10-18", ("review-2026-10-18", "review-2026-10-18-extra")),
)


def collapse_dataset_labels(
    baseline_ids: Sequence[str],
    raw_labels_by_id: Mapping[str, str],
    *,
    logical_unions: Sequence[tuple[str, Sequence[str]]] = LOGICAL_DATASET_UNIONS,
) -> list[str]:
    """Collapse sibling dataset partitions/extras into canonical display names."""
    remaining_ids = set(baseline_ids)
    dataset_labels: list[str] = []
    for value in baseline_ids:
        if value not in remaining_ids:
            continue
        matched_entry = next(
            (
                (label, members)
                for label, members in logical_unions
                if value in members and set(members).issubset(remaining_ids)
            ),
            None,
        )
        if matched_entry is not None:
            label, members = matched_entry
            remaining_ids.difference_update(members)
            dataset_labels.append(label)
        else:
            remaining_ids.discard(value)
            dataset_labels.append(raw_labels_by_id[value])
    return dataset_labels
