"""Model selection helpers."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from model_release_pipeline.models import ExperimentInfo, MetricCandidate


_EPOCH_PATTERNS = [
    re.compile(r"\bepoch[=\s:]+(\d+)\b", re.IGNORECASE),
    re.compile(r"\bEpoch[\s\[]+(\d+)\b"),
]
_METRIC_PATTERNS = {
    "loss": [
        re.compile(r"\b(?:val[_/\s-]*)?loss[=\s:]+([0-9.eE+-]+)\b", re.IGNORECASE),
    ],
    "precision": [
        re.compile(
            r"\b(?:val[_/\s-]*)?(?:precision|prec)[=\s:]+([0-9.eE+-]+)\b",
            re.IGNORECASE,
        ),
    ],
    "recall": [
        re.compile(r"\b(?:val[_/\s-]*)?recall[=\s:]+([0-9.eE+-]+)\b", re.IGNORECASE),
    ],
    "pr_auc": [
        re.compile(r"\b(?:val[_/\s-]*)?pr[_/\s-]*auc[=\s:]+([0-9.eE+-]+)\b", re.IGNORECASE),
    ],
    "roc_auc": [
        re.compile(r"\b(?:val[_/\s-]*)?roc[_/\s-]*auc[=\s:]+([0-9.eE+-]+)\b", re.IGNORECASE),
    ],
    "accuracy": [
        re.compile(r"\b(?:val[_/\s-]*)?(?:accuracy|acc)[=\s:]+([0-9.eE+-]+)\b", re.IGNORECASE),
    ],
    "f1_score": [
        re.compile(r"\b(?:val[_/\s-]*)?(?:f1_score|f1)[=\s:]+([0-9.eE+-]+)\b", re.IGNORECASE),
    ],
}
_TABLE_EPOCH_RE = re.compile(
    r"Validation Metrics \(Epoch\s+(\d+),", re.IGNORECASE
)
_TABLE_TASK_RE = re.compile(r"Task\s+([^:]+):\s+Validation Metrics", re.IGNORECASE)
_METRIC_FIELDS = {
    "loss",
    "accuracy",
    "f1_score",
    "pr_auc",
    "roc_auc",
    "precision",
    "recall",
    "tn",
    "fp",
    "fn",
    "tp",
}
_COUNT_FIELDS = {"tn", "fp", "fn", "tp"}
_PRIMARY_TASK_NAME = "stuck_detect"
_SECONDARY_TASK_NAME = "stuck_detect_neg_no_assist"
_RANK_WINDOW = 30
_LOSS_TOLERANCE_PCT = 0.05
_LOG_COMPLETENESS_RATIO = 0.8


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_epoch(line: str) -> Optional[int]:
    for pattern in _EPOCH_PATTERNS:
        match = pattern.search(line)
        if match:
            return int(match.group(1))
    return None


def _normalize_metric_name(raw_name: str) -> str:
    name = raw_name.strip().lower().replace(" ", "_").replace("-", "_")
    if name in {"f1", "f1score"}:
        return "f1_score"
    if name in {"prauc", "pr_auc"}:
        return "pr_auc"
    if name in {"rocauc", "roc_auc"}:
        return "roc_auc"
    return name


def _extract_metrics(line: str) -> Dict[str, float]:
    metrics = {}
    for metric_name, patterns in _METRIC_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                value = _to_float(match.group(1))
                if value is not None:
                    metrics[metric_name] = value
                    break
    return metrics


def _split_table_row(line: str) -> List[str]:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return []
    return [item.strip() for item in stripped.strip("|").split("|")]


def _parse_metric_tables(lines: List[str]) -> Dict[str, Dict[int, Dict[str, float]]]:
    metrics_by_task: Dict[str, Dict[int, Dict[str, float]]] = defaultdict(dict)
    current_task = "default"
    current_epoch: Optional[int] = None
    current_header: List[str] = []
    for line in lines:
        task_match = _TABLE_TASK_RE.search(line)
        if task_match:
            current_task = task_match.group(1).strip()
        epoch_match = _TABLE_EPOCH_RE.search(line)
        if epoch_match:
            current_epoch = int(epoch_match.group(1))
            current_header = []
            continue

        columns = _split_table_row(line)
        if not columns or current_epoch is None:
            continue
        normalized = [_normalize_metric_name(column) for column in columns]
        if "precision" in normalized and "recall" in normalized:
            current_header = normalized
            continue
        if not current_header:
            continue

        parsed = {}
        for name, raw_value in zip(current_header, columns):
            if name in _METRIC_FIELDS:
                value = _to_float(raw_value)
                if value is not None:
                    parsed[name] = int(value) if name in _COUNT_FIELDS else value
        if parsed:
            metrics_by_task[current_task][current_epoch] = parsed
            current_header = []
    return dict(metrics_by_task)


def _merge_metric(target: MetricCandidate, source: Dict[str, float], tag: str) -> None:
    for metric_name in _METRIC_FIELDS:
        if source.get(metric_name) is not None:
            setattr(target, metric_name, source[metric_name])
    if tag not in target.sources:
        target.sources.append(tag)


def _has_any_metric(candidate: MetricCandidate) -> bool:
    return any(getattr(candidate, metric_name) is not None for metric_name in _METRIC_FIELDS)


def _score(candidate: MetricCandidate, policy: str) -> float:
    precision = candidate.precision if candidate.precision is not None else -1.0
    recall = candidate.recall if candidate.recall is not None else -1.0
    pr_auc = candidate.pr_auc if candidate.pr_auc is not None else -1.0
    roc_auc = candidate.roc_auc if candidate.roc_auc is not None else -1.0
    loss = candidate.loss if candidate.loss is not None else 999999.0
    if policy == "recall_first":
        return recall * 1_000_000_000 + precision * 1_000_000 + pr_auc * 1_000 + roc_auc - loss
    return precision * 1_000_000_000 + pr_auc * 1_000_000 + roc_auc * 1_000 + recall - loss


def _rank_candidates(candidates: Iterable[MetricCandidate], policy: str) -> List[MetricCandidate]:
    ranked = []
    for candidate in candidates:
        candidate.score = _score(candidate, policy)
        ranked.append(candidate)
    return sorted(ranked, key=lambda item: item.score or -math.inf, reverse=True)


def _rank_map(
    candidates: Iterable[MetricCandidate], metric_name: str, rank_window: int
) -> Dict[int, int]:
    ranked = sorted(
        [candidate for candidate in candidates if getattr(candidate, metric_name) is not None],
        key=lambda candidate: getattr(candidate, metric_name),
        reverse=True,
    )[:rank_window]
    return {candidate.epoch: index + 1 for index, candidate in enumerate(ranked)}


def _rank_task_candidates(
    candidates: Iterable[MetricCandidate],
    policy: str,
    top_n: int,
) -> List[MetricCandidate]:
    candidate_list = list(candidates)
    third_metric = "recall" if policy == "recall_first" else "precision"
    rank_window = max(_RANK_WINDOW, top_n)
    rank_maps = {
        "roc_auc": _rank_map(candidate_list, "roc_auc", rank_window),
        "pr_auc": _rank_map(candidate_list, "pr_auc", rank_window),
        third_metric: _rank_map(candidate_list, third_metric, rank_window),
    }
    common_epochs = set(rank_maps["roc_auc"]) & set(rank_maps["pr_auc"]) & set(
        rank_maps[third_metric]
    )
    if not common_epochs:
        return _rank_candidates(candidate_list, policy)

    def weighted_rank(candidate: MetricCandidate) -> Tuple[int, int]:
        total = (
            rank_maps["roc_auc"][candidate.epoch]
            + rank_maps["pr_auc"][candidate.epoch]
            + 2 * rank_maps[third_metric][candidate.epoch]
        )
        candidate.score = -float(total)
        return total, candidate.epoch

    in_common = [candidate for candidate in candidate_list if candidate.epoch in common_epochs]
    ranked_common = sorted(in_common, key=weighted_rank)
    remaining = [candidate for candidate in candidate_list if candidate.epoch not in common_epochs]
    return ranked_common + _rank_candidates(remaining, policy)


def _new_candidates(
    experiment: ExperimentInfo, task: Optional[str] = None
) -> Dict[int, MetricCandidate]:
    candidates: Dict[int, MetricCandidate] = {}
    for checkpoint in experiment.checkpoints:
        epoch = int(checkpoint.stem.split("=")[1])
        candidates[epoch] = MetricCandidate(
            epoch=epoch, task=task, checkpoint_path=checkpoint
        )
    return candidates


def _metric_from_tag(tag: str) -> Optional[str]:
    lower = tag.lower()
    if not lower.startswith("val/"):
        return None
    if "roc_auc" in lower or "auc/roc" in lower or "roc-auc" in lower:
        return "roc_auc"
    if "pr_auc" in lower or "auc/pr" in lower or "prauc" in lower:
        return "pr_auc"
    if "precision" in lower or lower.endswith("/prec") or "prec" in lower:
        return "precision"
    if "recall" in lower:
        return "recall"
    if "loss" in lower:
        return "loss"
    if "accuracy" in lower or lower.endswith("/acc") or "acc" in lower:
        return "accuracy"
    if "f1_score" in lower or lower.endswith("/f1") or "f1" in lower:
        return "f1_score"
    return None


def _task_from_tag(tag: str, tasks: List[str]) -> str:
    lower = tag.lower()
    for task in sorted(tasks, key=len, reverse=True):
        if task.lower() in lower:
            return task
    return tasks[0] if len(tasks) == 1 else "default"


def _load_tensorboard_scalars(
    event_files: List[Path], tasks: List[str]
) -> Dict[str, Dict[int, Dict[str, float]]]:
    try:
        from tensorboard.backend.event_processing import event_accumulator
    except ImportError:
        return {}

    metrics_by_task: Dict[str, Dict[int, Dict[str, float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for event_file in event_files:
        accumulator = event_accumulator.EventAccumulator(
            str(event_file), size_guidance={"scalars": 0}
        )
        try:
            accumulator.Reload()
        except Exception:
            continue
        tags = accumulator.Tags().get("scalars", [])
        step_to_epoch = {}
        if "epoch" in tags:
            for scalar in accumulator.Scalars("epoch"):
                step_to_epoch[int(scalar.step)] = int(round(float(scalar.value)))
        for tag in tags:
            if tag == "epoch":
                continue
            metric = _metric_from_tag(tag)
            if not metric:
                continue
            task = _task_from_tag(tag, tasks)
            for scalar in accumulator.Scalars(tag):
                epoch = step_to_epoch.get(int(scalar.step), int(scalar.step))
                metrics_by_task[task][epoch][metric] = float(scalar.value)
    return {
        task: dict(metrics_by_epoch)
        for task, metrics_by_epoch in metrics_by_task.items()
    }


def _normalize_tensorboard_scalars(
    scalars: Dict[str, Dict[Any, Dict[str, float]]]
) -> Dict[str, Dict[int, Dict[str, float]]]:
    normalized: Dict[str, Dict[int, Dict[str, float]]] = {}
    for task, metrics_by_epoch in scalars.items():
        normalized[task] = {
            int(epoch): metrics
            for epoch, metrics in metrics_by_epoch.items()
        }
    return normalized


def _tensorboard_loss_tolerance_pick(
    candidates: Iterable[MetricCandidate],
    loss_tolerance_pct: float = _LOSS_TOLERANCE_PCT,
) -> Optional[Dict[str, Any]]:
    tb_candidates = [
        candidate
        for candidate in candidates
        if "tensorboard" in candidate.sources
        and candidate.loss is not None
        and candidate.precision is not None
    ]
    if not tb_candidates:
        return None
    min_loss_candidate = min(tb_candidates, key=lambda item: item.loss or math.inf)
    max_allowed_loss = (min_loss_candidate.loss or 0.0) * (1 + loss_tolerance_pct)
    loss_band_candidates = [
        candidate
        for candidate in tb_candidates
        if candidate.loss is not None and candidate.loss <= max_allowed_loss
    ]
    selected = max(
        loss_band_candidates,
        key=lambda item: (
            item.precision if item.precision is not None else -math.inf,
            -(item.loss if item.loss is not None else math.inf),
        ),
    )
    return {
        "min_loss_epoch": min_loss_candidate.epoch,
        "min_loss": min_loss_candidate.loss,
        "loss_tolerance_pct": loss_tolerance_pct,
        "max_allowed_loss": max_allowed_loss,
        "candidate_count": len(loss_band_candidates),
        "recommended_epoch": selected.epoch,
        "candidate": selected.to_dict(),
    }


def _minimum_complete_metric_count(checkpoint_count: int) -> int:
    if checkpoint_count <= 0:
        return 1
    return max(1, math.ceil(checkpoint_count * _LOG_COMPLETENESS_RATIO))


def _dual_head_recommendations(
    candidates_by_task: Dict[str, Dict[int, MetricCandidate]],
    task_order: List[str],
    policy: str,
    top_n: int,
) -> List[Dict[str, Any]]:
    if len(task_order) < 2:
        return []

    primary_task = _PRIMARY_TASK_NAME if _PRIMARY_TASK_NAME in task_order else task_order[0]
    secondary_tasks = [task for task in task_order if task != primary_task]
    rank_window = max(_RANK_WINDOW, top_n)
    third_metric = "recall" if policy == "recall_first" else "precision"
    primary_weights = {
        "precision": 6,
        "pr_auc": 3,
        "roc_auc": 2,
        "recall": 1,
    }
    if policy == "recall_first":
        primary_weights = {
            "recall": 5,
            "precision": 3,
            "pr_auc": 2,
            "roc_auc": 2,
        }
    secondary_weights = {"precision": 2, "pr_auc": 1, "roc_auc": 1}

    rank_by_task: Dict[str, Dict[str, Dict[int, int]]] = {}
    required_metrics_by_task: Dict[str, List[str]] = {}
    for task in task_order:
        candidates = list(candidates_by_task[task].values())
        if task == primary_task:
            required_metrics = ["roc_auc", "pr_auc", third_metric]
            weights = primary_weights
        else:
            required_metrics = ["roc_auc", "pr_auc", "precision"]
            weights = secondary_weights
        required_metrics_by_task[task] = required_metrics
        rank_by_task[task] = {
            metric: _rank_map(candidates, metric, rank_window)
            for metric in weights
        }

    eligible_epochs: Optional[set[int]] = None
    for task in task_order:
        task_epochs = set(candidates_by_task[task])
        for metric in required_metrics_by_task[task]:
            task_epochs &= set(rank_by_task[task].get(metric, {}))
        eligible_epochs = task_epochs if eligible_epochs is None else eligible_epochs & task_epochs
    if not eligible_epochs:
        return []

    filtered_epochs = []
    for epoch in sorted(eligible_epochs):
        primary_candidate = candidates_by_task[primary_task][epoch]
        if (
            primary_task == _PRIMARY_TASK_NAME
            and primary_candidate.recall is not None
            and primary_candidate.recall < 0.82
        ):
            continue
        keep = True
        for task in secondary_tasks:
            candidate = candidates_by_task[task][epoch]
            if (
                task == _SECONDARY_TASK_NAME
                and candidate.recall is not None
                and candidate.recall < 0.50
            ):
                keep = False
                break
        if keep:
            filtered_epochs.append(epoch)
    if not filtered_epochs:
        filtered_epochs = sorted(eligible_epochs)

    recommendations = []
    for epoch in filtered_epochs:
        total_rank = 0
        rank_details: Dict[str, Dict[str, int]] = {}
        metrics_by_task: Dict[str, Dict[str, Any]] = {}
        for task in task_order:
            weights = primary_weights if task == primary_task else secondary_weights
            task_rank_details = {}
            for metric, weight in weights.items():
                rank = rank_by_task[task].get(metric, {}).get(epoch)
                if rank is None:
                    continue
                task_rank_details[metric] = rank
                total_rank += weight * rank
            rank_details[task] = task_rank_details
            metrics_by_task[task] = candidates_by_task[task][epoch].to_dict()
        recommendations.append(
            {
                "epoch": epoch,
                "score": -float(total_rank),
                "total_rank": total_rank,
                "primary_task": primary_task,
                "rank_details": rank_details,
                "metrics_by_task": metrics_by_task,
                "checkpoint_path": metrics_by_task[primary_task].get("checkpoint_path"),
                "sources": ["combined_rank"],
                "task": None,
            }
        )
    return sorted(
        recommendations,
        key=lambda item: (item["total_rank"], item["epoch"]),
    )


class ModelPicker:
    """Builds candidate epochs from logs and tensorboard scalars."""

    def pick(
        self,
        experiment: ExperimentInfo,
        policy: str = "precision_first",
        top_n: int = 3,
        loss_tolerance_pct: float = _LOSS_TOLERANCE_PCT,
    ) -> Dict[str, object]:
        explicit_tasks = list(experiment.tasks)
        default_task = explicit_tasks[0] if len(explicit_tasks) == 1 else "default"
        has_multiple_explicit_tasks = len(explicit_tasks) > 1
        candidates_by_task: Dict[str, Dict[int, MetricCandidate]] = {
            task: _new_candidates(experiment, task)
            for task in (explicit_tasks or [default_task])
        }

        metric_from_log = False
        metric_from_task_log: Dict[str, bool] = defaultdict(bool)
        log_lines: List[str] = []
        log_text = experiment.log_text
        if log_text is None and experiment.log_file and experiment.log_file.exists():
            log_text = experiment.log_file.read_text(
                encoding="utf-8", errors="ignore"
            )
        log_metric_counts: Dict[str, int] = {}
        if log_text:
            log_lines = log_text.splitlines()
            parsed_metric_tables = _parse_metric_tables(log_lines)
            log_metric_counts = {
                task: len(metrics_by_epoch)
                for task, metrics_by_epoch in parsed_metric_tables.items()
            }
            for task, metrics_by_epoch in parsed_metric_tables.items():
                if explicit_tasks and task not in explicit_tasks:
                    continue
                if task not in candidates_by_task:
                    candidates_by_task[task] = _new_candidates(experiment, task)
                for epoch, metrics in metrics_by_epoch.items():
                    if epoch not in candidates_by_task[task]:
                        continue
                    metric_from_log = True
                    metric_from_task_log[task] = True
                    _merge_metric(candidates_by_task[task][epoch], metrics, "log_table")
            for line in log_lines:
                epoch = _extract_epoch(line)
                if epoch is None:
                    continue
                metrics = _extract_metrics(line)
                if not metrics:
                    continue
                if has_multiple_explicit_tasks:
                    continue
                metric_from_log = True
                task = default_task
                if task not in candidates_by_task:
                    candidates_by_task[task] = _new_candidates(experiment, task)
                if epoch in candidates_by_task[task]:
                    metric_from_task_log[task] = True
                    _merge_metric(candidates_by_task[task][epoch], metrics, "log")

        metric_from_tensorboard = False
        preliminary_task_order = explicit_tasks or [default_task]
        minimum_complete_count = _minimum_complete_metric_count(
            len(experiment.checkpoints)
        )
        incomplete_log_tasks = [
            task
            for task in preliminary_task_order
            if log_metric_counts.get(task, 0) < minimum_complete_count
        ]
        needs_tensorboard_fallback = (
            not metric_from_log
            or bool(incomplete_log_tasks)
            or any(not metric_from_task_log.get(task) for task in preliminary_task_order)
        )
        tb_metrics = (
            _normalize_tensorboard_scalars(experiment.tensorboard_scalars)
            if needs_tensorboard_fallback
            else {}
        )
        if not tb_metrics and experiment.tensorboard_files and needs_tensorboard_fallback:
            tb_metrics = _load_tensorboard_scalars(experiment.tensorboard_files, explicit_tasks)
        for task, metrics_by_epoch in tb_metrics.items():
            target_task = task
            if explicit_tasks and task == "default":
                if len(explicit_tasks) != 1:
                    continue
                target_task = explicit_tasks[0]
            if explicit_tasks and target_task not in explicit_tasks:
                continue
            if target_task not in candidates_by_task:
                candidates_by_task[target_task] = _new_candidates(experiment, target_task)
            for epoch, metrics in metrics_by_epoch.items():
                if epoch not in candidates_by_task[target_task] or not metrics:
                    continue
                metric_from_tensorboard = True
                _merge_metric(
                    candidates_by_task[target_task][epoch], metrics, "tensorboard"
                )

        per_task = {}
        task_order = explicit_tasks or list(candidates_by_task.keys())
        for task in task_order:
            candidates = candidates_by_task[task]
            for candidate in candidates.values():
                if not _has_any_metric(candidate):
                    candidate.notes.append("No metrics found for this epoch.")

            ranked = _rank_task_candidates(candidates.values(), policy, top_n)
            tb_loss_window = _tensorboard_loss_tolerance_pick(
                candidates.values(), loss_tolerance_pct=loss_tolerance_pct
            )
            recommended = None
            if tb_loss_window and (
                not metric_from_task_log.get(task) or task in incomplete_log_tasks
            ):
                recommended_epoch = tb_loss_window["recommended_epoch"]
                recommended = candidates.get(recommended_epoch)
            if recommended is None:
                for candidate in ranked:
                    if _has_any_metric(candidate):
                        recommended = candidate
                        break
            per_task[task] = {
                "recommended_epoch": recommended.epoch if recommended else None,
                "candidates": [candidate.to_dict() for candidate in ranked[:top_n]],
                "all_candidates": [candidate.to_dict() for candidate in ranked],
                "tensorboard_loss_window": tb_loss_window,
            }

        combined_recommendations = _dual_head_recommendations(
            candidates_by_task, task_order, policy, top_n
        )
        notes = []
        if not metric_from_log:
            notes.append("No usable metrics parsed from train_scenario_dnn.log.")
        if incomplete_log_tasks:
            details = ", ".join(
                f"{task}={log_metric_counts.get(task, 0)}/{len(experiment.checkpoints)}"
                for task in incomplete_log_tasks
            )
            notes.append(
                "Log metrics are incomplete; TensorBoard metrics are preferred when available. "
                f"Counts: {details}."
            )
        if (
            experiment.tensorboard_files
            and needs_tensorboard_fallback
            and not metric_from_tensorboard
        ):
            notes.append(
                "TensorBoard event files found but scalar parsing was unavailable or empty."
            )
        if experiment.tensorboard_files and needs_tensorboard_fallback and not tb_metrics:
            notes.append(
                "Install tensorboard locally if you want this tool to backfill metrics from event files."
            )
        if has_multiple_explicit_tasks and combined_recommendations:
            notes.append(
                "Multi-task recommendation uses combined rank: primary stuck_detect is precision-weighted, secondary heads are delay-gate precision weighted."
            )

        if len(explicit_tasks) == 1 and explicit_tasks[0] in per_task:
            primary_task = explicit_tasks[0]
        elif has_multiple_explicit_tasks:
            primary_task = explicit_tasks[0]
        else:
            primary_task = next(
                (
                    task
                    for task, task_result in per_task.items()
                    if task_result["recommended_epoch"] is not None
                ),
                next(iter(per_task)),
            )
        primary = per_task[primary_task]
        recommended_epoch = primary["recommended_epoch"]
        candidates = primary["candidates"]
        all_candidates = primary["all_candidates"]
        primary_tensorboard_fallback = (
            primary.get("tensorboard_loss_window")
            if primary_task in incomplete_log_tasks
            else None
        )
        if primary_tensorboard_fallback:
            recommended_epoch = primary_tensorboard_fallback["recommended_epoch"]
            candidates = [primary_tensorboard_fallback["candidate"]]
            all_candidates = primary["all_candidates"]
            notes.append(
                f"Final recommendation uses TensorBoard validation-loss tolerance fallback for {primary_task}."
            )
        elif has_multiple_explicit_tasks and combined_recommendations:
            recommended_epoch = combined_recommendations[0]["epoch"]
            candidates = combined_recommendations[:top_n]
            all_candidates = combined_recommendations
        elif has_multiple_explicit_tasks:
            recommended_epoch = None
        return {
            "policy": policy,
            "top_n": top_n,
            "loss_tolerance_pct": loss_tolerance_pct,
            "tasks": task_order,
            "per_task": per_task,
            "combined_recommendations": combined_recommendations[:top_n],
            "all_combined_recommendations": combined_recommendations,
            "recommended_epoch": recommended_epoch,
            "candidates": candidates,
            "all_candidates": all_candidates,
            "notes": notes,
        }
