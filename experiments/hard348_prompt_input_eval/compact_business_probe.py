#!/usr/bin/env python3
"""One-case prompt/input probe with compact, label-free business facts.

This evaluation-only runner deliberately keeps the model-visible request
small. It uses only a caller-provided evidence artifact and cached Camera/BEV
images. Expected labels, when present in the outer artifact for scoring, are
never included in the prompt.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests


OFFSETS_MS = [-19000, -15000, -10000, -5000, 0]
POST5_OFFSETS_MS = [-19000, -15000, -10000, -5000, 0, 5000]
FULL_OFFSETS_MS = [-19000, -15000, -10000, -5000, 0, 5000, 10000, 15000, 19000]

_FORBIDDEN_MODEL_KEYS = {
    "gt",
    "ground_truth",
    "expected_label",
    "expected_label_for_scoring_only",
    "gold_for_qc_only",
    "gt_for_scoring_only",
    "gold_label",
    "ground_truth_label",
    "label",
    "prediction",
    "predicted_code",
    "final_pred",
    "issue_id",
}

_FORBIDDEN_MODEL_TEXT = (
    re.compile(
        r"\b(?:gt|ground[ _-]*truth|gold(?:[ _-]*(?:label|class))?|"
        r"expected[ _-]*(?:label|class)|target[ _-]*(?:label|class)|"
        r"pred(?:icted)?[ _-]*(?:label|class)|final[ _-]*(?:label|class)|"
        r"prediction|label)\s*(?:is|=|:|：|->|为)?\s*[ABC]\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bcn\d{6,}\b", re.IGNORECASE),
    re.compile(r"\b(?:issue|case|scenario)[ _-]*(?:id)?\s*[:=：]", re.IGNORECASE),
)

_DERIVED_ARTIFACT_KEYS = {
    "model_yaml",
    "prompt_sha256",
    "stats",
    "training_used",
    "holdout_used",
    "elapsed_sec",
    "business_state_index",
    "business_state_index_provenance",
}
_DERIVED_ROW_KEYS = {
    "parsed",
    "raw_response",
    "model_output",
    "predicted_code",
    "prediction",
    "final_pred",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "duration_sec",
    "input_audit",
    "fusion",
    "final_code",
    "previous_best_code",
}


def _assert_model_safe(value: Any, *, path: str = "root") -> None:
    """Fail closed if a derived label/identity field reaches the prompt."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_MODEL_KEYS:
                raise ValueError(f"forbidden model-visible field at {path}.{key}")
            _assert_model_safe(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_model_safe(child, path=f"{path}[{index}]")
    elif isinstance(value, str):
        for pattern in _FORBIDDEN_MODEL_TEXT:
            if pattern.search(value):
                raise ValueError(f"forbidden model-visible text at {path}")


def _assert_raw_evidence_artifact(payload: Any) -> list[dict[str, Any]]:
    """Reject model summaries accidentally supplied as the raw evidence input."""
    if not isinstance(payload, dict):
        raise ValueError("artifact must be a JSON object with a results list")
    derived = sorted(_DERIVED_ARTIFACT_KEYS.intersection(payload))
    if derived:
        raise ValueError(
            "artifact contains derived/model-run fields; provide the original evidence artifact: "
            + ", ".join(derived)
        )
    rows = payload.get("results")
    if not isinstance(rows, list) or not rows:
        raise ValueError("artifact must be a non-empty evidence artifact with results")
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("evidence"), dict):
            raise ValueError(f"artifact row {index} has no evidence object")
        row_derived = sorted(_DERIVED_ROW_KEYS.intersection(row))
        if row_derived:
            raise ValueError(
                f"artifact row {index} contains derived/model-run fields: "
                + ", ".join(row_derived)
            )
    return rows


def _compact_time_windows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    wanted = {-19000, -10000, -5000, 0, 5000, 10000, 19000}
    selected = []
    for row in rows:
        if not isinstance(row, dict) or row.get("t_offset_ms") not in wanted:
            continue
        selected.append(
            {
                "t_ms": row.get("t_offset_ms"),
                "speed": row.get("speed"),
                "acc": row.get("acc"),
                "gear": row.get("gear"),
                "angle": row.get("angle"),
                "yielding_observation": row.get("yielding"),
                "yielding_object_id": row.get("yielding_object_id"),
            }
        )
    return selected


def _compact_remote_features(remote: Any) -> dict[str, Any]:
    if not isinstance(remote, dict):
        return {}
    stage1 = remote.get("stage1") or {}
    stage2 = remote.get("stage2") or {}
    selected = stage1.get("selected_constraint_object_history") or {}
    path_change = stage2.get("first_significant_decoupled_path_change")
    motion = stage2.get("ego_actual_motion_trigger_frame") or {}
    return {
        "stage1_decoupled_path": stage1.get("decoupled_path"),
        "selected_object_history_observation": {
            "selected_object_id": selected.get("selected_object_id"),
            "selected_object_observed": selected.get("selected_object_observed"),
            "coverage_t_ms": selected.get("coverage_t_offset_ms"),
            "max_speed_mps": selected.get("max_speed_mps"),
            "moving_ratio": selected.get("moving_speed_observation_ratio"),
            "first_motion_t_ms": selected.get("first_motion_evidence_t_offset_ms"),
            "note": selected.get("note"),
        },
        "driving_mode_transitions": stage2.get("driving_mode_transitions"),
        "first_remote_assist_mode_t_ms": stage2.get("first_remote_assist_mode_t_offset_ms"),
        "path_change_observation": path_change,
        "ego_motion_summary": {
            "observation_count": motion.get("observation_count"),
            "snapshots": motion.get("snapshots"),
        },
        "non_autonomous_mode_before_recovery": stage2.get(
            "non_autonomous_mode_observed_before_recovery"
        ),
    }


def _compact_reports(
    neutral: Any, recovery: Any, *, report_mode: str = "compact"
) -> dict[str, Any]:
    """Keep only auditable fields; remove duplicated raw model text."""
    n = neutral if isinstance(neutral, dict) else {}
    r = recovery if isinstance(recovery, dict) else {}
    if report_mode in {"observation_v1", "observation_v2"}:
        trigger_fields = (
            "intended_maneuver",
            "ego_trigger_observation",
            "evidence_anchors",
            "normal_mechanism_evidence",
            "abnormal_constraint_evidence",
            "required_corridor",
            "critical_unknowns",
        )
        recovery_fields = (
            "trigger_constraint_candidates",
            "constraint_identity_continuity",
            "constraint_persistence",
            "same_constraint_release_time_ms",
            "candidate_action",
            "action_execution_status",
            "preexisting_executable_path",
            "distinct_post_action_response",
            "executable_path_after_action",
            "executable_path_time_ms",
            "ego_recovery",
            "ego_sustained_motion_time_ms",
            "temporal_audit",
            "evidence_conflict",
        )
        if report_mode == "observation_v2":
            recovery_fields += ("strongest_counter_evidence",)
        return {
            "trigger_observations_non_authoritative": {
                key: n.get(key)
                for key in trigger_fields
                if n.get(key) not in (None, "", [], {})
            },
            "recovery_observations_non_authoritative": {
                key: r.get(key)
                for key in recovery_fields
                if r.get(key) not in (None, "", [], {})
            },
        }
    if report_mode in {"audit_v2", "audit_v3_business_state"}:
        # Do not expose the observer's already-compressed state conclusion to
        # the final adjudicator.  Keep only hypotheses, anchors, and the
        # time/identity observations needed to recompute the causal state.
        if report_mode == "audit_v3_business_state":
            trigger_fields = (
                "intended_maneuver",
                "ego_trigger_observation",
                "trigger_evidence_state",
                "critical_unknowns",
                "evidence_anchors",
                "normal_mechanism_evidence",
                "abnormal_constraint_evidence",
                "required_corridor",
            )
        else:
            trigger_fields = (
                "intended_maneuver",
                "normal_wait_mechanism",
                "causal_constraint",
                "state_anchor",
                "critical_unknowns",
            )
        recovery_fields = (
            "trigger_constraint_candidates",
            "constraint_identity_continuity",
            "constraint_persistence",
            "same_constraint_release_time_ms",
            "candidate_action",
            "action_execution_status",
            "preexisting_executable_path",
            "distinct_post_action_response",
            "executable_path_after_action",
            "executable_path_time_ms",
            "ego_recovery",
            "ego_sustained_motion_time_ms",
            "temporal_audit",
            "strongest_counter_evidence",
            "evidence_conflict",
        )
        trigger = {key: n.get(key) for key in trigger_fields if key in n}
        recovery_observations = {
            key: r.get(key) for key in recovery_fields if key in r
        }
        result = {
            "trigger_report_hypotheses_non_authoritative": trigger,
            "recovery_report_observations_non_authoritative": recovery_observations,
        }
        # These optional visual fields are observations, not state labels.  Do
        # not add empty placeholders to the multimodal prompt.
        visual = {
            key: n.get(key)
            for key in (
                "actor_observations",
                "candidate_constraint_observations",
                "observation_conflicts",
                "visibility_limitations",
                "semantic_limitations",
                "observation_summary",
            )
            if n.get(key)
        }
        if visual:
            result["visual_observations_non_authoritative"] = visual
        return result
    trigger_fields = (
        "state_update",
        "updated_trigger_state",
        "intended_maneuver",
        # v29 observer reports use these neutral observation names.  Keep
        # them in the compact projection instead of silently dropping the
        # positive normal/stuck evidence when schemas differ.
        "primary_constraint_candidate",
        "normal_mechanism",
        "normal_evidence",
        "stuck_mechanism",
        "stuck_evidence",
        "constraint_identity_conflict",
        "traffic_role_evidence",
        "abnormal_role_evidence",
        "normal_wait_mechanism",
        "causal_constraint",
        "constraint_blocks_required_maneuver",
        "autonomous_solution_available",
        "trigger_state",
        "constraint_release_mechanism",
        "ra_changed_executability",
        "strongest_counter_evidence",
        "evidence_conflict",
        "state_anchor",
        "critical_unknowns",
    )
    recovery_fields = (
        "trigger_constraint_candidates",
        "constraint_identity_continuity",
        "constraint_persistence",
        "same_constraint_release_time_ms",
        "candidate_action",
        "action_execution_status",
        "preexisting_executable_path",
        "distinct_post_action_response",
        "executable_path_after_action",
        "executable_path_time_ms",
        "ego_recovery",
        "ego_sustained_motion_time_ms",
        "temporal_audit",
        "recovery_hypothesis",
        "strongest_counter_evidence",
        "evidence_conflict",
        "reason",
    )
    return {
        "trigger_state_report_non_authoritative": {
            key: n.get(key) for key in trigger_fields if key in n
        },
        "visual_observer_non_authoritative": {
            "actor_observations": n.get("actor_observations"),
            "candidate_constraint_observations": n.get(
                "candidate_constraint_observations"
            ),
            "observation_conflicts": n.get("observation_conflicts"),
            "visibility_limitations": n.get("visibility_limitations"),
            "semantic_limitations": n.get("semantic_limitations"),
            "observation_summary": n.get("observation_summary"),
        },
        "recovery_observer_non_authoritative": {
            key: r.get(key) for key in recovery_fields if key in r
        },
    }


def _narrative_reports(reports: dict[str, Any]) -> dict[str, str]:
    """Render the same report observations as an auditable role ledger."""
    trigger = reports.get("trigger_state_report_non_authoritative") or {}
    recovery = reports.get("recovery_observer_non_authoritative") or {}
    lines = ["Trigger 观察（非权威，字段均需复核）："]
    for key in (
        "intended_maneuver",
        "normal_wait_mechanism",
        "causal_constraint",
        "updated_trigger_state",
        "constraint_blocks_required_maneuver",
        "autonomous_solution_available",
        "constraint_release_mechanism",
        "ra_changed_executability",
        "state_anchor",
        "critical_unknowns",
    ):
        if key in trigger:
            lines.append(f"- {key}: {trigger[key]}")
    lines.append("Recovery 观察（非权威，必须与机械账本交叉核对）：")
    for key in (
        "trigger_constraint_candidates",
        "constraint_identity_continuity",
        "constraint_persistence",
        "same_constraint_release_time_ms",
        "candidate_action",
        "action_execution_status",
        "preexisting_executable_path",
        "distinct_post_action_response",
        "executable_path_after_action",
        "executable_path_time_ms",
        "ego_recovery",
        "ego_sustained_motion_time_ms",
        "temporal_audit",
        "recovery_hypothesis",
        "strongest_counter_evidence",
        "evidence_conflict",
    ):
        if key in recovery:
            lines.append(f"- {key}: {recovery[key]}")
    return {"non_authoritative_business_report_ledger": "\n".join(lines)}


def _compact_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    trajectory = evidence.get("trajectory_summary") or {}
    return {
        "time_windows_selected": _compact_time_windows(evidence.get("time_windows")),
        "planning_constraints": evidence.get("planning_constraints") or {},
        "remote_assist_observations": _compact_remote_features(
            evidence.get("remote_assist_features")
        ),
        "causal_mechanical_facts": {
            "deterministic_timeline": evidence.get("deterministic_timeline") or {},
            "ra_action_timeline": evidence.get("ra_action_timeline") or {},
            "causal_milestone_order": evidence.get("causal_milestone_order") or {},
            "trajectory_causal_facts": trajectory.get("causal_evidence_facts") or {},
        },
    }


def _minimal_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Keep only facts needed for a short trigger/recovery causal check."""
    rows = _compact_time_windows(evidence.get("time_windows"))
    for row in rows:
        row.pop("yielding_object_id", None)
    deterministic = evidence.get("deterministic_timeline") or {}
    causal = evidence.get("causal_milestone_order") or {}
    trajectory = (evidence.get("trajectory_summary") or {}).get(
        "causal_evidence_facts"
    ) or {}
    remote = evidence.get("remote_assist_features") or {}
    stage2 = remote.get("stage2") or {}
    path_change = stage2.get("first_significant_decoupled_path_change") or {}
    selected = (remote.get("stage1") or {}).get(
        "selected_constraint_object_history"
    ) or {}
    return {
        "trigger_and_recovery_time_facts": rows,
        "mechanical_order": {
            "first_candidate_action_ms": deterministic.get(
                "first_candidate_ra_action_time_ms"
            ),
            "ego_sustained_motion_ms": deterministic.get(
                "first_post_trigger_sustained_motion_time_ms"
            ),
            "recovery_before_action": deterministic.get(
                "recovery_before_first_candidate_ra_action"
            ),
            "action_timeline": (evidence.get("ra_action_timeline") or {}).get(
                "events"
            ),
            "ordered_milestones": causal.get("ordered_milestones"),
            "first_same_object_motion_ms": trajectory.get(
                "first_same_object_motion_time_ms"
            ),
            "first_path_change_ms": trajectory.get(
                "first_significant_path_change_time_ms"
            ),
        },
        "mode_and_path_facts": {
            "driving_mode_transitions": stage2.get("driving_mode_transitions"),
            "first_remote_assist_mode_ms": stage2.get(
                "first_remote_assist_mode_t_offset_ms"
            ),
            "first_path_change": {
                "t_ms": path_change.get("t_offset_ms"),
                "kind": path_change.get("change_kind"),
                "changed_fields": path_change.get("changed_fields"),
                "note": path_change.get("note"),
            },
            "selected_object_motion_fact": {
                "coverage_t_ms": selected.get("coverage_t_offset_ms"),
                "first_motion_t_ms": selected.get(
                    "first_motion_evidence_t_offset_ms"
                ),
                "motion_observed_pre_trigger": selected.get(
                    "motion_observed_pre_trigger"
                ),
            },
        },
        "planning_observation": evidence.get("planning_constraints") or {},
    }


def _narrative_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Render the same mechanical projection as a short causal ledger.

    This is only a presentation change: values still come from the frozen
    source artifact and no label-bearing field is introduced.
    """
    facts = _minimal_evidence(evidence)
    lines = ["触发前后机械账本（t=0 为 trigger）："]
    for row in facts.get("trigger_and_recovery_time_facts", []):
        lines.append(
            "t={t}ms: Ego speed={speed}, acc={acc}, gear={gear}; "
            "yielding_observation={yielding}".format(
                t=row.get("t_ms"),
                speed=row.get("speed"),
                acc=row.get("acc"),
                gear=row.get("gear"),
                yielding=row.get("yielding_observation"),
            )
        )
    mechanical = facts.get("mechanical_order") or {}
    lines.append(
        "候选动作时间={action}ms；Ego持续运动时间={motion}ms；"
        "恢复是否早于动作={before_action}.".format(
            action=mechanical.get("first_candidate_action_ms"),
            motion=mechanical.get("ego_sustained_motion_ms"),
            before_action=mechanical.get("recovery_before_action"),
        )
    )
    lines.append(
        "同一对象首次运动时间={object_motion}ms；首次显著路径变化时间="
        "{path_change}ms.".format(
            object_motion=mechanical.get("first_same_object_motion_ms"),
            path_change=mechanical.get("first_path_change_ms"),
        )
    )
    milestones = mechanical.get("ordered_milestones") or []
    if milestones:
        lines.append(
            "里程碑顺序："
            + " → ".join(
                f"{item.get('milestone')}@{item.get('t_offset_ms')}ms"
                for item in milestones
                if isinstance(item, dict)
            )
        )
    mode = facts.get("mode_and_path_facts") or {}
    lines.append(
        "RA mode 首次出现={mode_ms}ms；路径变化事实={path}.".format(
            mode_ms=mode.get("first_remote_assist_mode_ms"),
            path=mode.get("first_path_change"),
        )
    )
    return {
        "causal_timeline_in_plain_language": "\n".join(lines),
        "planning_observation": facts.get("planning_observation") or {},
        "selected_object_motion_facts": mode.get("selected_object_motion_fact") or {},
    }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _find_image_directory(image_root: Path, issue_id: str) -> Path:
    """Accept the two frozen cache layouts used by source and Fresh artifacts."""
    candidates: list[Path] = []
    exact = image_root / issue_id
    if (exact / "after_compress").is_dir():
        candidates.append(exact / "after_compress")
    if exact.is_dir() and (exact / "0.jpg").is_file():
        candidates.append(exact)
    candidates.extend(image_root.glob(f"{issue_id}_*/after_compress"))
    candidates.extend(
        path
        for path in image_root.glob(f"{issue_id}_*")
        if path.is_dir() and (path / "0.jpg").is_file()
    )
    unique = list(dict.fromkeys(path.resolve() for path in candidates))
    if len(unique) != 1:
        raise RuntimeError(f"expected one image directory, got {unique}")
    return unique[0]


def _prompt(
    facts: dict[str, Any],
    reports: dict[str, Any],
    *,
    output_mode: str,
    prompt_variant: str = "base",
    visual_mode: str = "paired10",
) -> str:
    examples_enabled = prompt_variant == "causal_examples_v1"
    if examples_enabled:
        prompt_variant = "causal_compare_v1"
    compare_enabled = prompt_variant in {
        "causal_compare_v1",
        "causal_role_first_v1",
        "causal_role_first_v2",
        "causal_role_first_v3",
        "causal_effect_gate_v1",
    }
    if output_mode == "short":
        output_schema = (
            '最后只输出一行合法 JSON：'
            '{"label":"A|B|C","reason":"不超过90字，先写触发时正向角色/机制，'
            '再写同一约束的释放或有效协助先后"}'
        )
    else:
        output_schema = (
            '最后只输出一行合法 JSON，label 必须是 A、B 或 C：'
            '{"label":"A|B|C","trigger_state":"normal_wait|true_stuck",'
            '"intended_maneuver":"straight|lane_change|turn_left|turn_right|u_turn|'
            'pull_out|pull_over|nudge|other|unknown","primary_constraint":"不超过35字",'
            '"normal_mechanism":"不超过55字或none","abnormal_mechanism":"不超过55字或none",'
            '"recovery_cause":"normal_traffic_progression|effective_manual_control|'
            'effective_ra_planning|external_constraint_released|autonomous_recovery|'
            'no_recovery|uncertain","causal_order_audit":"valid_intervention_chain|'
            'constraint_released_first|no_recovery|insufficient","reason":"不超过180字，'
            '先写触发时角色/机制，再写恢复因果顺序"}'
        )
    audit_v2 = """
额外的因果审计要求（这是业务定义的解释顺序，不是字段到标签的硬编码映射）：
1. 先审计触发时的 normal mechanism。普通同向跟随、连续同向 stop-go、停止线/信号、让行、合理安全间隙或施工引导造成的有序车流，即使具体信号不可见，也可构成 B 的正向解释；“没有看到信号”本身不是异常证据。
2. 只有看到异常实体/行为确实截断 intended maneuver 的 required corridor，才进入 A/C 候选。前车单独静止、speed=0、刹车灯、yielding、planner selected、dwell、后续移动和“看起来挡路”本身都不能完成这一步。
3. 进入 A 候选后，必须核对同一约束在有效协助改变可执行性时仍存在；RA pickup、SWAG/waypoint 名称、candidate action、mode 切换或任意路径变化单独都不是有效协助证据。candidate_only、动作与可执行路径的矛盾、约束已先释放时，不能据此判 A。
4. C 只适用于“触发时确有异常阻断”且同一约束在有效协助前自然释放，随后 Ego 自主持续恢复；若触发时是正常队列/跟随，则是 B，不是 C。
5. 报告里的 normal/abnormal/state/recovery 字段只是另一位观察者的假设；优先用图片、机械时间顺序和实体角色重算。若实体身份或因果链互相冲突，不得把冲突字段拼成确定的 A。
    """ if prompt_variant == "audit_v2" else ""
    causal_compare_v1 = """
内部先做三种因果故事比较（不要输出中间过程，也不要机械投票）：
- N：触发时是正常交通等待，所见的同向跟随/排队/信号/路权/安全间隙足以解释 Ego 没有通过；后续自然移动就是正常交通进展。
- E：触发时存在异常 blocker 截断 required corridor，但 blocker 在任何有效协助改变可执行性之前自然释放，Ego 随后自主持续恢复。
- P：触发时存在异常 blocker，且它在有效协助改变可执行性时仍持续；或有可信的动作→可执行路径→Ego恢复链。只有 P 才支持 A。
先确认 T 阶段到底是 N 还是异常 blocker；只有异常 blocker 成立时才在 E/P 之间比较。C 的 E 故事必须有同一约束“先释放”的正向证据；release time 缺失、identity 不连续或只有 Ego 后续移动，不能完成 E。单个停止前车、RA 事件、路径变化、对象后来移动都不能单独决定故事。报告中的 N/E/P 或 state 字段只是待证假设；用同一实体、同一走廊和机械时间顺序逐项寻找反证。""" if compare_enabled else ""
    causal_role_first_v1 = """
【角色先行与恢复隔离】
把判断分成两个相互独立的账本，禁止后一个账本倒灌前一个账本：
1. T 账本只回答“触发时 Ego 的 intended maneuver 是否被正常交通职责解释”。先给每个关键参与者分配 ordinary-duty/gap-duty 或 abnormal-blocker 角色，并检查它是否正向占据 required corridor。动态让行、横穿/汇入造成的安全间隙、连续同向交通、适用控制锚点是 normal 机制的正向观察；planner selected、hard-block 名称、单辆静止车、无可见信号或后续恢复不是角色证明。
2. 只有 T 账本已经证明异常 blocker，R 账本才区分自然释放与有效协助。RA pickup/mode、candidate action、生成 trajectory、单独 path change、对象后来移动都不能单独决定 R。要比较同一约束的 release、动作前是否已有可执行路径、动作后的独立路径/走廊增量以及 Ego 持续运动的顺序。
3. 若 T 账本有正向 normal-duty/gap-duty 机制，后续 Ego 恢复或 RA workflow 不把它升级为 A/C；若 T 账本没有正向异常角色，也不能仅因静止/占道字段或“没有看到正常机制”补成 A/C。若两个观察者报告冲突，保留冲突并回到图片和 raw timeline，不做报告投票。
""" if prompt_variant == "causal_role_first_v1" else ""
    causal_role_first_v2 = """
【直接因果角色与背景交通隔离】
在角色账本中再加一层“谁直接解释 Ego 的停止”核验，避免把场景背景当成触发原因：
1. normal-duty/gap-duty 必须同时满足：它实际约束当前 intended maneuver，且与 Ego 在触发前后的减速/停止空间和时间相符。邻道车辆、横穿后已清空的参与者、施工/锥桶/停靠物的可见性，或一个不适用于当前 maneuver 的红绿灯，不能单独成为 normal 机制；同样，“有多个车”也不自动等于同走廊 stop-go。
2. 异常 blocker 必须直接占据 required corridor，并能解释 Ego 为什么不能沿 intended maneuver 通过。一个异常物体出现在画面中，或靠近走廊但 Ego 实际是在跟随同向交通等待，不能单独把 T 账本改成异常。正常背景与异常主体可以同时存在，必须按直接时空因果区分，而不是按“正常/异常字段”投票。
3. 适用信号、停止线、路权、让行或施工引导只有在确认它约束 Ego 当前 intended maneuver 时，才是 normal 的正向证据；可见但不适用或作用对象不明的控制元素保持未知。
4. R 账本仍只接受同一 blocker 的释放或有效协助链；其他车辆移动、RA workflow 事件或 Ego 后续运动不能替代同一约束的因果核验。
""" if prompt_variant == "causal_role_first_v2" else ""
    causal_role_first_v3 = """
【T/R 账本冲突时的直接因果复核】
恢复账本中的 `strongest_counter_evidence` 只表示可审计的身份/时间反证，不是标签或结论：
1. 如果它显示同一候选约束在 Ego 运动或有效动作前释放，先回到图像和 required corridor 判断该候选是否确实是异常 blocker；不能因为触发观察者写了 normal，也不能因为 recovery 写了 release，就跳过直接因果核验。
2. 若图像/BEV显示正常同流、信号、路权或安全间隙直接解释 Ego 停止，保持 B；若一个独立实体确实截断 required corridor 且它先释放、随后 Ego 自主恢复，才支持 C。释放时间本身不能把 B 机械改成 C。
3. 若同一约束持续到有效动作并在动作后产生新的可执行路径/持续运动，才支持 A；`candidate_only`、RA workflow 或单独路径变化仍不足。
""" if prompt_variant == "causal_role_first_v3" else ""
    corridor_mechanism_v1 = """
【同流队列与单一占道主体的区分】
在触发时单独重建 normal mechanism 与 abnormal blocker，不要把同一辆车在多个时间点出现自动升级为“连续同向队列”：
1. 正常队列/stop-go 需要正向的交通机制证据，例如至少两个不同参与者在同一走廊形成协调的同向减速/排队，或适用的信号、停止线、路权、让行/施工引导；“一辆 lead vehicle 从运动变成静止”本身不是队列证据。
2. 一个实体若持续占据 Ego 的 required corridor、没有可见控制锚点或协调队列、并且确实使 Ego 不能沿 intended maneuver 通过，应作为异常 blocker 候选；不能仅因为它是普通车辆、刹车灯亮或看起来像跟车就抹掉占道事实。
3. 反过来，若图像显示多个车辆组成 coherent same-flow traffic、适用控制锚点或有序施工引导，单个 lead 的静止应解释为背景交通机制，不能只凭“占据 corridor”判 A/C。
4. 对异常 blocker 候选，若触发后 Ego 在该主体释放前已自主持续运动、绕行或重新获得可执行性，而没有有效协助链，检查 C；不能因为 Ego 后来动了就把触发时的占道事实改写成 B。若触发时既没有正向正常机制，也没有正向占道阻断证据，保持不确定并选择最有直接证据的故事，不用缺失字段补全。
""" if prompt_variant == "corridor_mechanism_v1" else ""
    causal_guard_v1 = """
两个细节必须保持：同一约束没有可靠 release time 或身份连续性时，不能仅凭 Ego 后续移动臆造 external release；但也不能仅凭缺失 release 就判 A，仍需动作→路径→运动等有效协助证据。路口/停止线/刹车灯只有在确实控制当前 intended maneuver 和 required corridor 时才是 normal mechanism；信号不适用或状态未知应保持未知。""" if compare_enabled else ""
    compatibility_v1 = """
正常机制兼容性核验：称为同向队列/同向汇入前，应在至少两个触发前时点看到参与者沿 Ego 当前 intended maneuver 的同一走廊同向接近、减速或排队；侧方横向进入、横穿后清空或仅 t=0 位于前方，不足以改写成 same-flow。称为信号/路权等待前，必须确认控制锚点实际约束当前 intended maneuver；可见直行红灯不能单独证明右转等待。Ego 后续没有恢复也不能反向证明 T 是 normal。""" if compare_enabled else ""
    causal_effect_gate_v1 = """
恢复因果的正向证据门（用于区分 A 与 C，不是字段到标签的机械映射）：
1. A 的“有效协助”必须是实际执行的动作，并且要看到动作改变了 required corridor/可执行路径，随后 Ego 持续运动。RA pickup、remote-assist mode、candidate action、candidate-only、仅有 path 字段变化、仅生成 executable trajectory，都不是实际执行或效果证据。
2. 若报告写 candidate_only、not_observed、无 action，或 Ego 已在动作前开始持续运动，则该动作不能解释恢复。若动作前已经存在 executable path，且动作后没有独立的 path/执行响应，也不能把动作当作原因。
3. 若同一 blocker 的正向运动/离开在 Ego 运动前发生，恢复原因优先是外部约束释放；若 blocker 仍在但 Ego 在任何实际协助前已自主通过/恢复，属于自主恢复。触发时确有异常 blocker 时，这两种情况都支持 C，而不是 A。
4. “对象未移动”不等于“必须 A”：还要检查 Ego 是否在动作前自主运动、是否已有可执行路径、以及是否存在实际执行链。反之，只有没有正向自然释放且存在完整实际动作→新路径→Ego运动链时，才支持 A。
    5. 先判触发时 normal traffic 还是异常 blocker；正常队列/让行/信号等待不能因 planner hard-block 字段或后续 RA 状态被升级为 A/C。冲突时优先保留可审计的正向因果证据，不用状态名补齐因果链。""" if prompt_variant == "causal_effect_gate_v1" else ""
    causal_effect_gate_v2 = """
恢复因果的正向证据门（candidate-only 不是充分证据，也不是自动否定）：
1. A 需要一个可审计的有效协助链：实际执行或有明确执行状态的动作 → 动作之后出现新的可执行路径/走廊变化 → 其后 Ego 持续运动；同一异常 blocker 在这条链成立前不能已有正向释放证据。RA pickup、remote-assist mode、单独的 candidate action、单独的 path 字段变化或单独生成 executable trajectory 都不够。
2. `candidate_only`/动作状态不完整时，不能单独判 A，也不能单独判 C：如果动作后紧接着出现新的路径/几何响应、随后 Ego 运动、动作前没有已知可执行路径、且没有 blocker 先释放，这个完整时间链仍是 A 的正向证据。若动作前已有 executable path，或动作后没有独立响应，则动作不能解释恢复。
3. 若同一 blocker 的正向运动/离开在 Ego 运动前发生，恢复原因优先是外部约束释放；若 blocker 仍在但 Ego 在任何有效协助前已自主通过/恢复，属于自主恢复。触发时确有异常 blocker 时，这两种情况支持 C，而不是 A。
4. “对象未移动”不等于“必须 A”：检查 Ego 是否先运动、是否已有可执行路径、动作后的路径是否真正新增，以及是否存在实际执行链。只有没有正向自然释放且存在完整动作→新路径→Ego运动链时，才支持 A。
    5. 先判触发时 normal traffic 还是异常 blocker；正常队列/让行/信号等待不能因 planner hard-block 字段或后续 RA 状态被升级为 A/C。冲突时优先保留可审计的正向因果证据，不用状态名补齐因果链。""" if prompt_variant == "causal_effect_gate_v2" else ""
    causal_effect_gate_v3 = """
A/C 恢复因果时间表（只使用正向观察，不允许臆造 release）：
- 支持 A：触发时异常 blocker 确实截断 required corridor；同一 blocker 在 Ego运动前没有正向释放；并且存在动作/执行事件 t_a、其后的新路径或走廊几何响应 t_p、再其后的 Ego持续运动 t_m（t_a < t_p < t_m），且动作前没有已知可执行路径。即使动作字段写 candidate-only，只要这条完整链存在，也不能因为 candidate-only 三个字改判 C；需结合是否真的有动作后的新响应。
- 支持 C：触发时确有异常 blocker，但 (a) blocker释放 t_r 早于任何动作和 Ego运动，或 (b) Ego在任何动作前已自主持续运动，或 (c) 动作前已有可执行路径且动作后没有独立的新响应。C 不能仅由“对象后来移动”“RA退出”“路径字段变化”或“没有看到 action”补出。
- 决胜顺序：先找同一 blocker 的 release，再找动作前 Ego运动/既有路径，最后核对动作→新路径→Ego运动；若没有 release，不能把它写成“自然释放”。若 A 链的时间和空间证据完整，优先 A；若只有状态名或单个里程碑，没有完整链，则不要升级为 A。
- 触发时若有明确正常队列/让行/信号机制，先判 B；A/C 恢复表只在异常 blocker 已成立后使用。""" if prompt_variant == "causal_effect_gate_v3" else ""
    business_examples_v1 = """
三个抽象对照例只用于澄清业务定义，不是相似度模板，也不能替代本 case 的图像核验：
例 N（B）：Ego 要直行，当前走廊前有连续同向车辆形成 stop-go，或适用的停止线/信号/路权正向约束该 maneuver；没有独立异常 blocker 截断走廊。等待后交通自然推进，属于正常交通机制。
例 E（C）：Ego 的 required corridor 确实被一个异常实体截断；在任何有效 RA/人工动作改变可执行性之前，同一实体从该走廊自行驶离或消失，随后 Ego 自主恢复通过。这里必须能把释放前后的实体和时间连起来。
例 P（A）：Ego 的 required corridor 确实被异常实体持续截断；直到有效动作改变路径/方向/可执行性前约束仍在，且动作→可执行路径→Ego运动形成连续因果链，属于正确触发。
不要把这三个例子当作“看到某个物体就套标签”；先独立重建 intended maneuver、required corridor、实体身份和时间顺序。""" if examples_enabled else ""
    visual_binding = (
        "图像固定绑定：共 9 对，顺序为 t=-19s、-15s、-10s、-5s、0s、+5s、+10s、+15s、+19s；每对先 Camera，再同一时刻 BEV。"
        if visual_mode == "paired18"
        else (
            "图像固定绑定：共 6 对，顺序为 t=-19s、-15s、-10s、-5s、0s、+5s；每对先 Camera，再同一时刻 BEV。"
            if visual_mode == "paired12"
            else "图像固定绑定：共 5 对，顺序为 t=-19s、-15s、-10s、-5s、0s；每对先 Camera，再同一时刻 BEV。"
        )
    )
    return f"""
你是熟悉 Remote Assist Stuck 业务的最终 adjudicator。只判断当前 case，不能使用任何标签、issue 名称、历史模型结论或 case-specific 规则。下面的报告是非权威观察，必须回看图片和机械事实；不能投票，也不能把字段直接映射为 A/B/C。

业务因果定义：
- B：触发时 Ego intended maneuver 的 required corridor 由当前有效且正向可见的正常交通机制解释等待，例如适用信号/停止线/路权/安全间隙，或同一走廊中多个参与者形成连续同向 stop-go。单个前车、yielding、speed=0、planner selected、对象后来移动都不够。
- A：触发时有直接证据表明异常约束实际截断 required corridor，且约束持续，或有效 RA/人工动作先改变了可执行性。
- C：触发时同样先证明异常约束和 corridor 阻断；但同一约束在有效协助前自然释放，随后 Ego 自主持续恢复。

{audit_v2}

{causal_compare_v1}

{causal_role_first_v1}

{causal_role_first_v2}

{causal_role_first_v3}

{corridor_mechanism_v1}

{causal_guard_v1}

{compatibility_v1}

{causal_effect_gate_v1}

{causal_effect_gate_v2}

{causal_effect_gate_v3}

{business_examples_v1}


严格顺序：先从 Camera/BEV 判断 intended maneuver、required corridor、每个关键实体是同走廊/横跨/相邻/不确定，以及 normal-duty 或异常 blocker；再核对同一约束的自然释放、RA/人工动作、可执行路径和 Ego 持续运动的先后。缺少正向 normal 机制不能自动判 B；缺少正向异常阻断不能自动判 A/C。报告中的对象 ID 不等于 Camera-ID lineage，禁止猜测关联。

{visual_binding} BEV 只辅助 maneuver/corridor/空间关系。下面事实只描述 observations，不包含最终标签：
{_json(facts)}

以下两段是非权威报告，可能错，不能直接照抄：
{_json(reports)}

{output_schema}
""".strip()


def _extract_label(text: str) -> str:
    matches = re.findall(r'"label"\s*:\s*"([ABC])"', text or "")
    return matches[-1] if matches else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--issue-id", required=True)
    parser.add_argument(
        "--trigger-artifact",
        type=Path,
        help="optional label-free Trigger report keyed by issue_id",
    )
    parser.add_argument(
        "--recovery-artifact",
        type=Path,
        help="optional label-free Recovery report keyed by issue_id",
    )
    parser.add_argument("--image-cache-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=150.0)
    parser.add_argument(
        "--visual-mode",
        choices=("paired10", "paired12", "paired18", "camera5", "t0pair", "t0camera"),
        default="paired10",
        help="fixed visual ablation; does not inspect labels",
    )
    parser.add_argument(
        "--facts-mode",
        choices=("compact", "minimal", "narrative"),
        default="compact",
        help="label-free factual projection size",
    )
    parser.add_argument(
        "--output-mode",
        choices=("full", "short"),
        default="full",
        help="final JSON size; both modes leave label selection to the model",
    )
    parser.add_argument(
        "--report-mode",
        choices=(
            "compact",
            "narrative_v1",
            "observation_v1",
            "observation_v2",
            "audit_v2",
            "audit_v3_business_state",
        ),
        default="compact",
        help="label-free report projection; audit_v2 hides report state conclusions",
    )
    parser.add_argument(
        "--prompt-variant",
        choices=(
            "base",
            "audit_v2",
            "causal_compare_v1",
            "causal_role_first_v1",
            "causal_role_first_v2",
            "causal_role_first_v3",
            "causal_effect_gate_v1",
            "causal_effect_gate_v2",
            "causal_effect_gate_v3",
            "corridor_mechanism_v1",
            "causal_examples_v1",
        ),
        default="base",
        help="business reasoning prompt variant",
    )
    parser.add_argument(
        "--text-layout",
        choices=("before_images", "after_images"),
        default="before_images",
        help="place the same factual prompt before or after the visual sequence",
    )
    parser.add_argument(
        "--endpoint",
        required=True,
        help="OpenAI-compatible chat-completions endpoint",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="base model identifier, e.g. Qwen3.8-27B/Qwen3.8-27B",
    )
    parser.add_argument(
        "--api-key-env",
        default="RA_TRIAGE_GATEWAY_APIKEY",
        help="environment variable containing the gateway key",
    )
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    rows = _assert_raw_evidence_artifact(payload)
    row = next(item for item in rows if str(item.get("issue_id")) == args.issue_id)
    evidence = row.get("evidence") or {}
    neutral = row.get("trigger_expert") or {}
    recovery = row.get("recovery_expert") or {}
    if args.trigger_artifact:
        trigger_payload = json.loads(args.trigger_artifact.read_text(encoding="utf-8"))
        trigger_row = next(
            item for item in trigger_payload.get("results", [])
            if str(item.get("issue_id")) == args.issue_id
        )
        neutral = trigger_row.get("trigger_expert") or {}
    if args.recovery_artifact:
        recovery_payload = json.loads(args.recovery_artifact.read_text(encoding="utf-8"))
        recovery_row = next(
            item for item in recovery_payload.get("results", [])
            if str(item.get("issue_id")) == args.issue_id
        )
        recovery = recovery_row.get("recovery_expert") or {}
    if args.facts_mode == "minimal":
        facts = _minimal_evidence(evidence)
    elif args.facts_mode == "narrative":
        facts = _narrative_evidence(evidence)
    else:
        facts = _compact_evidence(evidence)
    if args.report_mode == "narrative_v1":
        reports = _narrative_reports(
            _compact_reports(neutral, recovery, report_mode="compact")
        )
    else:
        reports = _compact_reports(neutral, recovery, report_mode=args.report_mode)
    prompt = _prompt(
        facts,
        reports,
        output_mode=args.output_mode,
        prompt_variant=args.prompt_variant,
        visual_mode=args.visual_mode,
    )
    if args.issue_id in prompt:
        raise RuntimeError("issue id leaked into model prompt")
    _assert_model_safe(facts, path="facts")
    _assert_model_safe(reports, path="reports")

    directory = _find_image_directory(args.image_cache_root, args.issue_id)
    paths = []
    image_count = 9 if args.visual_mode == "paired18" else (6 if args.visual_mode == "paired12" else 5)
    for index in range(image_count):
        paths.extend([directory / f"{index}.jpg", directory / f"bev_{index}.jpg"])
    if any(not path.is_file() for path in paths):
        raise FileNotFoundError([str(path) for path in paths if not path.is_file()])

    if args.text_layout == "after_images":
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": "先按标记顺序查看全部 Camera/BEV 图像；暂不输出判断。",
            }
        ]
    else:
        content = [{"type": "text", "text": prompt}]
    visual_items = []
    offsets = (
        FULL_OFFSETS_MS
        if args.visual_mode == "paired18"
        else (POST5_OFFSETS_MS if args.visual_mode == "paired12" else OFFSETS_MS)
    )
    for pair_index, (offset_ms, camera, bev) in enumerate(
        zip(offsets, paths[::2], paths[1::2]), start=1
    ):
        label = "t=0" if offset_ms == 0 else f"t={offset_ms / 1000:g}s"
        if args.visual_mode == "camera5":
            visual_items.append((pair_index, label, "Camera", camera))
        elif args.visual_mode in {"t0pair", "t0camera"} and offset_ms == 0:
            visual_items.extend(
                [(pair_index, label, "Camera", camera)]
            )
            if args.visual_mode == "t0pair":
                visual_items.append((pair_index, label, "BEV", bev))
        elif args.visual_mode in {"paired10", "paired12", "paired18"}:
            visual_items.extend(
                [(pair_index, label, "Camera", camera), (pair_index, label, "BEV", bev)]
            )
    for pair_index, label, modality, path in visual_items:
        content.append(
            {"type": "text", "text": f"[第{pair_index}对，{label}，{modality}] 仅为图像绑定索引。"}
        )
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}
        )
    if args.text_layout == "after_images":
        content.append(
            {
                "type": "text",
                "text": prompt + "\n\n视觉核对结束。现在只输出规定 JSON。",
            }
        )
    else:
        content.append({"type": "text", "text": "视觉核对结束。现在只输出规定 JSON。"})

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"missing gateway key environment variable: {args.api_key_env}")
    started = time.time()
    response = requests.post(
        args.endpoint,
        headers={"apikey": api_key, "Content-Type": "application/json"},
        json={
            "model": args.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": args.max_tokens,
            "temperature": 0.0,
            "top_p": 0.8,
            "top_k": 50,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        timeout=args.timeout,
    )
    elapsed = time.time() - started
    data = response.json()
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    output = {
        "issue_id": args.issue_id,
        "gt_for_scoring_only": row.get("expected_label_for_scoring_only"),
        "label": _extract_label(text),
        "elapsed_sec": round(elapsed, 3),
        "prompt_chars": len(prompt),
        "prompt_tokens": (data.get("usage") or {}).get("prompt_tokens"),
        "completion_tokens": (data.get("usage") or {}).get("completion_tokens"),
        "raw_text": text,
        "status_code": response.status_code,
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
