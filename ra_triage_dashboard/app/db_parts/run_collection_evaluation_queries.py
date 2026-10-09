"""Run collection workflow: evaluation_queries. Transaction ownership remains in methods."""
from __future__ import annotations
import math
from typing import Any
from .shared import LABELS, MODEL_LABELS, _json_load, model_label_matches_gt, utc_now


class RunEvaluationQueriesMixin:
    def _run_evaluation_payload_conn(
        self,
        conn: Any,
        context_id: str,
        *,
        page: int,
        page_size: int,
        search: str,
        include_items: bool = True,
        include_all_items: bool = False,
    ) -> dict[str, Any] | None:
        context = conn.execute(
            "SELECT * FROM run_evaluation_contexts WHERE id = ?", (context_id,)
        ).fetchone()
        if context is None:
            return None
        members_rows = conn.execute(
            """
            SELECT member.*, live.id AS live_run_id
            FROM run_collection_members member
            LEFT JOIN model_runs live ON live.id = member.run_id
            WHERE member.collection_id = ? AND member.revision_no = ?
            ORDER BY member.ordinal
            """,
            (str(context["collection_id"]), int(context["collection_revision"])),
        ).fetchall()
        members = [
            {
                "ordinal": int(row["ordinal"]), "run_id": str(row["run_id"]),
                "role": str(row["role"] or ""), "is_reference": bool(row["is_reference"]),
                "available_now": row["live_run_id"] is not None,
                "run": _json_load(row["run_snapshot_json"], {}),
            }
            for row in members_rows
        ]
        all_items = conn.execute(
            "SELECT * FROM run_evaluation_items WHERE context_id = ? ORDER BY ordinal",
            (context_id,),
        ).fetchall()
        policy = _json_load(context["scoring_policy_json"], {})
        reference_labels = list(MODEL_LABELS if context["reference_type"] == "run" else LABELS)
        prediction_columns = [*MODEL_LABELS, "NONE", "UNKNOWN"]
        matrix: dict[str, dict[str, dict[str, int]]] = {
            item["run_id"]: {
                label: {prediction: 0 for prediction in prediction_columns}
                for label in reference_labels
            }
            for item in members
        }
        metrics: dict[str, dict[str, Any]] = {
            item["run_id"]: {
                "run_id": item["run_id"], "run": item["run"],
                "available_now": item["available_now"],
                "reference_denominator": 0, "valid_reference_count": 0,
                "pairwise_union_denominator": 0,
                "prediction_count": 0, "supported_count": 0,
                "missing_count": 0,
                "absent_prediction_count": 0, "unknown_count": 0, "correct_count": 0,
                "accuracy": 0.0, "coverage": 0.0, "workset_coverage": 0.0,
                "supported_coverage": 0.0, "absent_count": 0,
                "confusion": [], "transitions_vs_reference": None,
            }
            for item in members
        }
        valid_non_excluded_count = 0
        scorable_issue_ids: set[str] = set()
        workset_missing_count = 0
        workset_unknown_count = 0
        for row in all_items:
            if not bool(row["reference_valid"]) or bool(row["excluded"]):
                continue
            valid_non_excluded_count += 1
            predictions = _json_load(row["predictions_json"], {})
            if not isinstance(predictions, dict):
                predictions = {}
            if any(
                bool((predictions.get(member["run_id"]) or {}).get("present"))
                and str((predictions.get(member["run_id"]) or {}).get("label") or "") in MODEL_LABELS
                for member in members
            ):
                scorable_issue_ids.add(str(row["issue_id"]))
            else:
                predictions = _json_load(row["predictions_json"], {})
                if not isinstance(predictions, dict):
                    predictions = {}
                present_values = [
                    bool((predictions.get(member["run_id"]) or {}).get("present"))
                    for member in members
                ]
                supported_values = [
                    present and str((predictions.get(member["run_id"]) or {}).get("label") or "") in MODEL_LABELS
                    for present, member in zip(present_values, members)
                ]
                if not any(present_values):
                    workset_missing_count += 1
                elif not any(supported_values):
                    workset_unknown_count += 1
        reference_run_id = str(context["comparison_reference_run_id"] or "")
        transition_counts = (
            {
                run_id: {"P2P": 0, "P2F": 0, "F2P": 0, "F2F": 0}
                for run_id in metrics if run_id != reference_run_id
            }
            if reference_run_id else {}
        )
        filtered_items = []
        normalized_search = str(search or "").strip().lower()[:128]
        for row in all_items:
            issue_id = str(row["issue_id"])
            reference_label = str(row["reference_label"] or "")
            valid = bool(row["reference_valid"])
            excluded = bool(row["excluded"])
            predictions = _json_load(row["predictions_json"], {})
            if not isinstance(predictions, dict):
                predictions = {}
            model_reviews = _json_load(row["model_review_json"], {})
            if not isinstance(model_reviews, dict):
                model_reviews = {}
            if valid and not excluded:
                ref_metric_label = reference_label if reference_label in reference_labels else ""
                if ref_metric_label:
                    for member in members:
                        run_id = member["run_id"]
                        metric = metrics[run_id]
                        metric["valid_reference_count"] += 1
                        prediction = predictions.get(run_id) or {}
                        present = bool(prediction.get("present"))
                        label = str(prediction.get("label") or "") if present else ""
                        if not present:
                            bucket = "NONE"
                            metric["missing_count"] += 1
                            metric["absent_prediction_count"] += 1
                            metric["absent_count"] += 1
                        elif label not in MODEL_LABELS:
                            bucket = "UNKNOWN"
                            metric["unknown_count"] += 1
                            metric["missing_count"] += 1
                        else:
                            bucket = label
                            metric["prediction_count"] += 1
                            metric["supported_count"] += 1
                        if issue_id not in scorable_issue_ids:
                            continue
                        metric["reference_denominator"] += 1
                        metric["pairwise_union_denominator"] += 1
                        if label in MODEL_LABELS and model_label_matches_gt(label, reference_label):
                            metric["correct_count"] += 1
                        if ref_metric_label in matrix[run_id]:
                            matrix[run_id][ref_metric_label][bucket] += 1
                if issue_id in scorable_issue_ids and reference_run_id in metrics:
                    ref_prediction = predictions.get(reference_run_id) or {}
                    ref_label = str(ref_prediction.get("label") or "") if ref_prediction.get("present") else ""
                    ref_correct = bool(ref_label in MODEL_LABELS and model_label_matches_gt(ref_label, reference_label))
                    for run_id in metrics:
                        if run_id == reference_run_id or run_id not in transition_counts:
                            continue
                        prediction = predictions.get(run_id) or {}
                        label = str((prediction or {}).get("label") or "") if (prediction or {}).get("present") else ""
                        candidate_correct = bool(label in MODEL_LABELS and model_label_matches_gt(label, reference_label))
                        transition = ("P" if ref_correct else "F") + "2" + ("P" if candidate_correct else "F")
                        transition_counts[run_id][transition] += 1
            enriched_predictions = {}
            for member in members:
                run_id = member["run_id"]
                prediction = predictions.get(run_id) or {"present": False, "label": ""}
                label = str(prediction.get("label") or "")
                known = bool(prediction.get("present")) and label in MODEL_LABELS
                enriched_predictions[run_id] = {
                    "present": bool(prediction.get("present")),
                    "label": label if known else ("UNKNOWN" if prediction.get("present") else "NONE"),
                    "reason": str(prediction.get("reason") or ""),
                    "confidence": prediction.get("confidence"),
                    "correct": bool(valid and known and model_label_matches_gt(label, reference_label)),
                    "model_reviews": model_reviews.get(run_id, []),
                }
            if normalized_search and normalized_search not in issue_id.lower():
                continue
            filtered_items.append({
                "ordinal": int(row["ordinal"]), "issue_id": issue_id,
                "baseline_scope": str(row["baseline_scope"] or ""),
                "reference_label": reference_label,
                "reference_valid": valid, "excluded": excluded,
                "shared_label": {
                    "state": str(row["shared_label_state"] or "none"),
                    "expected_output": str(row["shared_label_expected_output"] or ""),
                    "gt_relation": str(row["shared_label_gt_relation"] or "unknown"),
                    "method": str(row["shared_label_method"] or ""),
                    "source": _json_load(row["shared_label_source_json"], {}),
                    "sha256": str(row["shared_label_sha256"] or ""),
                },
                "predictions": enriched_predictions,
            })
        for run_id, metric in metrics.items():
            denominator = int(metric["reference_denominator"])
            metric["accuracy"] = metric["correct_count"] / denominator if denominator else 0.0
            metric["coverage"] = metric["prediction_count"] / denominator if denominator else 0.0
            metric["workset_coverage"] = (
                metric["prediction_count"] / metric["valid_reference_count"]
                if metric["valid_reference_count"] else 0.0
            )
            metric["supported_coverage"] = (
                metric["supported_count"] / metric["valid_reference_count"]
                if metric["valid_reference_count"] else 0.0
            )
            metric["coverage_semantics"] = "pairwise_union" if denominator else "no_supported_output"
            metric["confusion"] = [
                {"reference_label": label, "cells": matrix[run_id][label], "total": sum(matrix[run_id][label].values())}
                for label in reference_labels
            ]
            if run_id in transition_counts:
                metric["transitions_vs_reference"] = transition_counts[run_id]
        page_size = min(max(int(page_size), 1), self.MAX_EVALUATION_ITEMS if include_all_items else 100)
        page = max(int(page), 1)
        total = len(filtered_items)
        page_count = max(1, math.ceil(total / page_size))
        page = min(page, page_count)
        offset = (page - 1) * page_size
        stored_workset = _json_load(context["workset_json"], {})
        stored_reference = _json_load(context["reference_json"], {})
        if include_all_items:
            public_workset = stored_workset
            public_reference_snapshot = stored_reference
        else:
            scope_items = stored_workset.get("scope_items") if isinstance(stored_workset, dict) else []
            public_workset = {
                "version": int(stored_workset.get("version") or 1) if isinstance(stored_workset, dict) else 1,
                "workset_id": str(stored_workset.get("workset_id") or context["workset_id"]) if isinstance(stored_workset, dict) else str(context["workset_id"] or ""),
                "baseline_scopes": list(stored_workset.get("baseline_scopes") or []) if isinstance(stored_workset, dict) else [],
                "scope_count": len(scope_items or (stored_workset.get("baseline_scopes") if isinstance(stored_workset, dict) else [])),
                "member_count": len(all_items),
                "selection_source_run_id": str(context["selection_source_run_id"] or ""),
                "members_sha256": str(stored_workset.get("members_sha256") or context["workset_sha256"] or ""),
                "scope_items": [
                    {
                        "baseline_scope": str(item.get("baseline_scope") or ""),
                        "member_count": int(item.get("member_count") or len(item.get("issue_ids") or [])),
                        "members_sha256": str(item.get("members_sha256") or ""),
                    }
                    for item in (scope_items or [])
                    if isinstance(item, dict)
                ],
            }
            public_reference_snapshot = {
                "version": int(stored_reference.get("version") or 1) if isinstance(stored_reference, dict) else 1,
                "type": str(stored_reference.get("type") or context["reference_type"]) if isinstance(stored_reference, dict) else str(context["reference_type"]),
                "id": str(stored_reference.get("id") or context["reference_id"] or "") if isinstance(stored_reference, dict) else str(context["reference_id"] or ""),
                "scope_snapshots": [
                    {
                        "baseline_scope": str(item.get("baseline_scope") or ""),
                        "id": str(item.get("id") or ""),
                        "content_sha256": str(item.get("content_sha256") or ""),
                        "membership_sha256": str(item.get("membership_sha256") or ""),
                        "member_count": int(item.get("member_count") or 0),
                    }
                    for item in (stored_reference.get("scope_snapshots") or [])
                    if isinstance(item, dict)
                ],
                "item_count": len(all_items),
            }
        result = {
            "id": str(context["id"]),
            "collection_id": str(context["collection_id"]),
            "collection_revision": int(context["collection_revision"]),
            "collection_sha256": str(context["collection_sha256"] or ""),
            "workset": public_workset,
            "workset_sha256": str(context["workset_sha256"] or ""),
            "reference": {
                "type": str(context["reference_type"]),
                "id": str(context["reference_id"] or ""),
                "snapshot": public_reference_snapshot,
                "sha256": str(context["reference_sha256"] or ""),
            },
            "scoring_policy": policy,
            "scoring_policy_version": str(context["scoring_policy_version"]),
            "scoring_policy_sha256": str(context["scoring_policy_sha256"] or ""),
            "exclusion": {
                "version": int(context["exclusion_version"] or 1),
                "sha256": str(context["exclusion_sha256"] or ""),
            },
            "selection_source_run_id": str(context["selection_source_run_id"] or ""),
            "selection_bias_warning": (
                f"Workset 由 Run {context['selection_source_run_id']} 的输出筛选，存在来源 Run 选择偏差。"
                if context["selection_source_run_id"] else ""
            ),
            "comparison_reference_run_id": reference_run_id,
            "reference_official": str(context["reference_type"] or "") in {"gt", "label_result"},
            "metric_semantics": (
                "official_snapshot_accuracy_with_pairwise_union_coverage"
                if str(context["reference_type"] or "") in {"gt", "label_result"}
                else "legacy_prediction_agreement_non_official"
            ),
            "context_sha256": str(context["context_sha256"] or ""),
            "created_by": str(context["created_by"] or ""),
            "created_by_source": str(context["created_by_source"] or "legacy"),
            "created_by_verified": bool(context["created_by_verified"]),
            "created_at": str(context["created_at"] or ""),
            "members": members,
            "summary": {
                "workset_count": len(all_items),
                "valid_reference_count": sum(1 for row in all_items if bool(row["reference_valid"]) and not bool(row["excluded"])),
                "excluded_count": sum(1 for row in all_items if bool(row["excluded"])),
                "reference_denominator": next(iter(metrics.values()))["reference_denominator"] if metrics else 0,
                "pairwise_union_denominator": (
                    next(iter(metrics.values()))["pairwise_union_denominator"] if metrics else 0
                ),
                "workset_missing_count": workset_missing_count,
                "workset_unknown_count": workset_unknown_count,
                "coverage_note": "准确率/旧版 Pairwise coverage 使用至少一个 Run 有 supported output 的 union denominator；每 Run supported_coverage 使用全部 valid reference。",
                "runs": list(metrics.values()),
            },
            "items": filtered_items[offset : offset + page_size] if include_items else [],
            "total": total,
            "page": page,
            "page_size": page_size,
            "page_count": page_count,
        }
        return result

    def get_run_evaluation(
        self,
        context_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
        search: str = "",
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._run_evaluation_payload_conn(
                conn, str(context_id or "").strip(), page=page,
                page_size=page_size, search=search,
            )

    def get_run_evaluation_task_context(self, context_id: str) -> dict[str, Any] | None:
        """Return the complete frozen context for internal Campaign adapters.

        The public detail endpoint deliberately returns compact Workset and
        reference summaries. Campaign creation still needs the frozen member
        set, so it uses this internal service method inside the same database
        boundary instead of trusting a client supplied full JSON payload.
        """
        with self.connect() as conn:
            return self._run_evaluation_payload_conn(
                conn, str(context_id or "").strip(), page=1,
                page_size=self.MAX_EVALUATION_ITEMS, search="",
                include_all_items=True,
            )

    def list_run_evaluations(
        self,
        *,
        collection_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        normalized_collection_id = str(collection_id or "").strip()
        safe_limit = min(max(int(limit), 1), 500)
        where = "WHERE collection_id = ?" if normalized_collection_id else ""
        params: tuple[Any, ...] = (normalized_collection_id, safe_limit) if where else (safe_limit,)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, collection_id, collection_revision, collection_sha256,
                       workset_id, workset_sha256, reference_type, reference_id,
                       reference_sha256, scoring_policy_version, scoring_policy_sha256,
                       exclusion_sha256, comparison_reference_run_id, context_sha256,
                       created_by, created_at
                FROM run_evaluation_contexts
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            {
                "id": str(row["id"]), "collection_id": str(row["collection_id"]),
                "collection_revision": int(row["collection_revision"]),
                "collection_sha256": str(row["collection_sha256"] or ""),
                "workset_id": str(row["workset_id"] or ""),
                "workset_sha256": str(row["workset_sha256"] or ""),
                "reference_type": str(row["reference_type"] or ""),
                "reference_id": str(row["reference_id"] or ""),
                "reference_sha256": str(row["reference_sha256"] or ""),
                "scoring_policy_version": str(row["scoring_policy_version"] or ""),
                "scoring_policy_sha256": str(row["scoring_policy_sha256"] or ""),
                "exclusion_sha256": str(row["exclusion_sha256"] or ""),
                "comparison_reference_run_id": str(row["comparison_reference_run_id"] or ""),
                "context_sha256": str(row["context_sha256"] or ""),
                "created_by": str(row["created_by"] or ""),
                "created_at": str(row["created_at"] or ""),
            }
            for row in rows
        ]

    def export_run_evaluation(self, context_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            payload = self._run_evaluation_payload_conn(
                conn, str(context_id or "").strip(), page=1,
                page_size=self.MAX_EVALUATION_ITEMS, search="", include_all_items=True,
            )
        if payload is not None:
            payload["generated_at"] = utc_now()
            payload["export_provenance"] = {
                "collection_id": payload["collection_id"],
                "collection_revision": payload["collection_revision"],
                "collection_sha256": payload["collection_sha256"],
                "workset_id": str(payload["workset"].get("workset_id") or ""),
                "workset_member_count": int(payload["workset"].get("member_count") or len(payload.get("items") or [])),
                "workset_sha256": payload["workset_sha256"],
                "workset_scope_items": payload["workset"].get("scope_items") or [],
                "reference_type": payload["reference"]["type"],
                "reference_id": payload["reference"]["id"],
                "reference_scope_snapshots": payload["reference"].get("snapshot", {}).get("scope_snapshots") or [],
                "reference_sha256": payload["reference"]["sha256"],
                "scoring_policy_version": payload["scoring_policy_version"],
                "scoring_policy_sha256": payload["scoring_policy_sha256"],
                "exclusion_sha256": payload["exclusion"]["sha256"],
                "context_sha256": payload["context_sha256"],
            }
        return payload
