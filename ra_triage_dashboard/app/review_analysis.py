from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Iterable


TRIAGE_LABELS = ("误触发", "正确触发", "无需协助")

# Review notes remain free text.  These themes intentionally use a small,
# inspectable keyword contract so reviewers can understand why a case appears
# in a cluster.  A note can match more than one theme.
REASON_THEME_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "key": "routing_intent",
        "label": "Routing / 行驶意图",
        "description": "目标转向、规划方向或车道任务理解错误",
        "keywords": (
            "routing",
            "route",
            "规划方向",
            "路径方向",
            "目标方向",
            "目标车道",
            "车道任务",
            "左转",
            "右转",
            "直行",
            "转向",
        ),
    },
    {
        "key": "passable_space",
        "label": "可通行 / 绕行空间",
        "description": "没有判断相邻车道、借道或安全绕行空间",
        "keywords": (
            "绕行",
            "可通行",
            "通行空间",
            "绕行空间",
            "避让空间",
            "变道空间",
            "相邻车道",
            "空旷车道",
            "借道",
        ),
    },
    {
        "key": "normal_traffic",
        "label": "正常交通状态",
        "description": "等灯、排队、让行与正常拥堵的判断错误",
        "keywords": (
            "排队",
            "拥堵",
            "堵车",
            "等灯",
            "灯态",
            "信号灯",
            "红灯",
            "绿灯",
            "周期性放行",
            "正常等待",
            "让行",
        ),
    },
    {
        "key": "abnormal_obstacle",
        "label": "异常停车 / 障碍信号",
        "description": "双闪、临停、故障、施工或固定障碍证据遗漏",
        "keywords": (
            "双闪",
            "临停",
            "异常停车",
            "故障车",
            "车辆故障",
            "施工",
            "路障",
            "锥桶",
            "静止障碍",
            "固定障碍",
            "占道",
        ),
    },
    {
        "key": "target_relation",
        "label": "关键目标关系",
        "description": "前车、摩自、行人或 yielding 目标关系识别不足",
        "keywords": (
            "yielding",
            "关键目标",
            "阻塞目标",
            "目标关系",
            "前车",
            "摩自",
            "摩托",
            "电动车",
            "行人",
        ),
    },
    {
        "key": "temporal_recovery",
        "label": "时序 / 触发后恢复",
        "description": "没有利用前后帧、持续时间或触发后的恢复结果",
        "keywords": (
            "触发后",
            "后续帧",
            "前后帧",
            "恢复通行",
            "自行恢复",
            "自行解除",
            "开始移动",
            "恢复移动",
            "驶离",
            "时序",
            "单帧",
            "持续时间",
        ),
    },
    {
        "key": "ra_swag_outcome",
        "label": "RA / SWAG 操作效果",
        "description": "没有结合远程协助动作、路径和最终脱困效果",
        "keywords": (
            "ra",
            "swag",
            "waypoint",
            "vnode",
            "方向键",
            "倒车",
            "mrc",
            "远程协助",
            "协助后",
            "脱困",
        ),
    },
    {
        "key": "visibility_modality",
        "label": "可见性 / 视角",
        "description": "遮挡或 Camera、BEV 视角信息不足",
        "keywords": (
            "遮挡",
            "看不清",
            "不可见",
            "camera",
            "相机",
            "摄像头",
            "bev",
            "拓扑",
            "视角",
            "视觉证据",
        ),
    },
    {
        "key": "gt_boundary",
        "label": "GT / 口径边界",
        "description": "真值、标签定义或边界 case 需要复核",
        "keywords": (
            "gt",
            "ground truth",
            "真值",
            "标签错误",
            "标签边界",
            "口径",
            "边界case",
            "边界 case",
            "需复核",
        ),
    },
)

_ASCII_TOKEN_RE = re.compile(r"^[a-z0-9_-]+$")


def _normalise_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().lower()


def _contains_keyword(text: str, keyword: str) -> bool:
    keyword = _normalise_text(keyword)
    if not keyword:
        return False
    if _ASCII_TOKEN_RE.fullmatch(keyword):
        return bool(
            re.search(
                rf"(?<![a-z0-9_-]){re.escape(keyword)}(?![a-z0-9_-])",
                text,
            )
        )
    return keyword in text


def classify_review_reason(note: Any) -> list[dict[str, Any]]:
    """Return deterministic, multi-label themes for one free-text review note."""

    text = _normalise_text(note)
    if not text:
        return []
    matches: list[dict[str, Any]] = []
    for theme in REASON_THEME_CATALOG:
        matched = [
            str(keyword)
            for keyword in theme["keywords"]
            if _contains_keyword(text, str(keyword))
        ]
        if matched:
            matches.append(
                {
                    "key": str(theme["key"]),
                    "label": str(theme["label"]),
                    "matched_keywords": matched,
                }
            )
    return matches


def _safe_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item).strip() for item in value if str(item).strip()})


def _share(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def _cluster_items(
    counts: dict[str, int],
    *,
    total: int,
    catalog: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        definition = (catalog or {}).get(key, {})
        items.append(
            {
                "key": key,
                "label": str(definition.get("label") or key),
                "description": str(definition.get("description") or ""),
                "count": count,
                "share": _share(count, total),
            }
        )
    return items


def build_review_reason_analysis(
    rows: Iterable[dict[str, Any]],
    *,
    theme: str = "",
    evidence_catalog: dict[str, dict[str, str]] | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Aggregate latest-review rows and return one deterministic analysis page."""

    materialized: list[dict[str, Any]] = []
    for source in rows:
        item = dict(source)
        annotation = dict(item.get("annotation") or {})
        prediction = dict(item.get("prediction") or {})
        annotation["tags"] = _safe_list(annotation.get("tags"))
        annotation["missing_evidence"] = _safe_list(
            annotation.get("missing_evidence")
        )
        annotation["note"] = str(annotation.get("note") or "").strip()
        item["annotation"] = annotation
        item["prediction"] = prediction
        item["reason_themes"] = classify_review_reason(annotation["note"])
        materialized.append(item)

    selected_theme = theme.strip()
    if selected_theme:
        materialized = [
            item
            for item in materialized
            if any(
                match["key"] == selected_theme
                for match in item["reason_themes"]
            )
        ]

    total = len(materialized)
    evidence_counts: dict[str, int] = {}
    theme_counts: dict[str, int] = {}
    with_reason = 0
    with_structured_evidence = 0
    unclustered_reason = 0
    comparable = 0
    mismatches = 0
    missing_predictions = 0
    manual_gt_disagreements = 0
    confusion_counts: dict[str, dict[str, int]] = {
        gt_label: {model_label: 0 for model_label in TRIAGE_LABELS}
        for gt_label in TRIAGE_LABELS
    }

    for item in materialized:
        annotation = item["annotation"]
        prediction = item["prediction"]
        note = annotation["note"]
        evidences = annotation["missing_evidence"]
        themes = item["reason_themes"]
        if note:
            with_reason += 1
            if not themes:
                unclustered_reason += 1
        if evidences:
            with_structured_evidence += 1
        for key in evidences:
            evidence_counts[key] = evidence_counts.get(key, 0) + 1
        for match in themes:
            key = str(match["key"])
            theme_counts[key] = theme_counts.get(key, 0) + 1

        gt_label = str(item.get("gt_label") or "")
        model_label = str(prediction.get("label") or "")
        annotation_label = str(annotation.get("label") or "")
        if gt_label in TRIAGE_LABELS and annotation_label in TRIAGE_LABELS:
            manual_gt_disagreements += int(annotation_label != gt_label)
        if gt_label in TRIAGE_LABELS and model_label in TRIAGE_LABELS:
            comparable += 1
            confusion_counts[gt_label][model_label] += 1
            mismatches += int(gt_label != model_label)
        elif model_label not in TRIAGE_LABELS:
            missing_predictions += 1

    reason_catalog = {
        str(item["key"]): item for item in REASON_THEME_CATALOG
    }
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    page_count = max(1, math.ceil(total / page_size))
    page = min(page, page_count)
    offset = (page - 1) * page_size
    page_items = materialized[offset : offset + page_size]

    return {
        "method": {
            "id": "deterministic-keywords-v1",
            "label": "可解释关键词聚类 v1",
            "multi_label": True,
            "latest_annotation_only": True,
            "mutates_review": False,
            "catalog": [
                {
                    "key": str(item["key"]),
                    "label": str(item["label"]),
                    "description": str(item["description"]),
                    "keywords": list(item["keywords"]),
                }
                for item in REASON_THEME_CATALOG
            ],
        },
        "summary": {
            "latest_reviews": total,
            "with_reason": with_reason,
            "empty_reason": total - with_reason,
            "with_structured_evidence": with_structured_evidence,
            "unclustered_reason": unclustered_reason,
            "comparable_predictions": comparable,
            "model_mismatches": mismatches,
            "missing_predictions": missing_predictions,
            "manual_gt_disagreements": manual_gt_disagreements,
        },
        "evidence_clusters": _cluster_items(
            evidence_counts,
            total=total,
            catalog=evidence_catalog or {},
        ),
        "reason_clusters": _cluster_items(
            theme_counts,
            total=total,
            catalog=reason_catalog,
        ),
        "confusion": {
            "labels": list(TRIAGE_LABELS),
            "comparable": comparable,
            "mismatches": mismatches,
            "rows": [
                {
                    "gt_label": gt_label,
                    "total": sum(confusion_counts[gt_label].values()),
                    "cells": [
                        {
                            "model_label": model_label,
                            "count": confusion_counts[gt_label][model_label],
                        }
                        for model_label in TRIAGE_LABELS
                    ],
                }
                for gt_label in TRIAGE_LABELS
            ],
        },
        "items": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "page_count": page_count,
    }
