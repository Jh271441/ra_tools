#!/usr/bin/env python3
"""Sequential evaluation-only runner for the compact prompt/input probe.

The child probe keeps expected labels outside its model request. This file
only orchestrates one case at a time and computes an external diagnostic
summary; it does not alter predictions or apply a label rule.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = ("A", "B", "C")
    valid = [row for row in rows if row.get("label") in labels]
    confusion = {gt: {pred: 0 for pred in (*labels, "FAIL")} for gt in labels}
    for row in rows:
        gt = str(row.get("gt_for_scoring_only") or "")
        pred = row.get("label") if row.get("label") in labels else "FAIL"
        if gt in confusion:
            confusion[gt][pred] += 1
    per_class = {}
    for label in labels:
        gt_count = sum(1 for row in rows if row.get("gt_for_scoring_only") == label)
        correct = confusion[label][label]
        per_class[label] = {
            "gt_count": gt_count,
            "prediction_count": sum(1 for row in valid if row.get("label") == label),
            "correct_count": correct,
            "recall": correct / gt_count if gt_count else None,
        }
    correct = sum(row.get("label") == row.get("gt_for_scoring_only") for row in rows)
    return {
        "total": len(rows),
        "completed": sum(bool(row.get("status_code")) for row in rows),
        "success": len(valid),
        "correct": correct,
        "accuracy": correct / len(rows) if rows else 0.0,
        "per_class": per_class,
        "confusion_matrix": confusion,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--trigger-artifact", type=Path)
    parser.add_argument("--recovery-artifact", type=Path)
    parser.add_argument("--image-cache-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument(
        "--issue-id",
        action="append",
        dest="issue_ids",
        help="optional source-only subset; repeat for representative cases",
    )
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--visual-mode", default="paired10")
    parser.add_argument("--facts-mode", default="minimal")
    parser.add_argument("--output-mode", default="short")
    parser.add_argument("--report-mode", default="compact")
    parser.add_argument("--prompt-variant", default="base")
    parser.add_argument("--text-layout", default="before_images")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="RA_TRIAGE_GATEWAY_APIKEY")
    parser.add_argument(
        "--expected-count",
        type=int,
        help="fail closed unless the raw evidence artifact has this many rows",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="retry a missing-output case with the exact same configuration",
    )
    args = parser.parse_args()

    if args.summary.exists():
        raise FileExistsError(f"refusing to overwrite existing summary: {args.summary}")

    payload = json.loads(args.artifact.read_text(encoding="utf-8"))
    source_rows = payload.get("results") or []
    if not isinstance(source_rows, list) or not source_rows:
        raise ValueError("artifact must be a non-empty raw evidence artifact")
    if args.expected_count is not None and len(source_rows) != args.expected_count:
        raise ValueError(
            f"raw evidence coverage mismatch: expected {args.expected_count}, got {len(source_rows)}"
        )
    issue_ids = [str(row.get("issue_id")) for row in source_rows]
    if len(set(issue_ids)) != len(issue_ids):
        raise ValueError("raw evidence artifact contains duplicate issue_id values")
    if any(not isinstance(row.get("evidence"), dict) for row in source_rows):
        raise ValueError("artifact contains a row without evidence; refusing summary/metrics input")
    if args.issue_ids:
        wanted = set(args.issue_ids)
        source_rows = [row for row in source_rows if str(row.get("issue_id")) in wanted]
        if not source_rows:
            raise ValueError("requested issue subset is empty")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    model_slug = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in args.model
    )
    results: list[dict[str, Any]] = []
    for index, source_row in enumerate(source_rows, start=1):
        issue_id = str(source_row["issue_id"])
        output = args.out_dir / f"{issue_id}.json"
        command = [
            sys.executable,
            str(args.probe),
            "--artifact",
            str(args.artifact),
            "--issue-id",
            issue_id,
        ]
        if args.trigger_artifact:
            command.extend(["--trigger-artifact", str(args.trigger_artifact)])
        if args.recovery_artifact:
            command.extend(["--recovery-artifact", str(args.recovery_artifact)])
        command.extend([
            "--image-cache-root",
            str(args.image_cache_root),
            "--output",
            str(output),
            "--max-tokens",
            str(args.max_tokens),
            "--timeout",
            str(args.timeout),
            "--visual-mode",
            args.visual_mode,
            "--facts-mode",
            args.facts_mode,
            "--output-mode",
            args.output_mode,
            "--report-mode",
            args.report_mode,
            "--prompt-variant",
            args.prompt_variant,
            "--text-layout",
            args.text_layout,
            "--endpoint",
            args.endpoint,
            "--model",
            args.model,
            "--api-key-env",
            args.api_key_env,
        ])
        if output.exists():
            raise FileExistsError(f"refusing to overwrite existing case output: {output}")
        completed = None
        attempts = 0
        while attempts <= args.retries:
            completed = subprocess.run(command, check=False)
            attempts += 1
            if output.is_file():
                break
        if output.is_file():
            row = json.loads(output.read_text(encoding="utf-8"))
        else:
            row = {
                "issue_id": issue_id,
                "gt_for_scoring_only": source_row.get(
                    "expected_label_for_scoring_only"
                ),
                "label": "",
                "status_code": None,
                "child_exit_code": completed.returncode if completed else None,
            }
        row.setdefault(
            "gt_for_scoring_only", source_row.get("expected_label_for_scoring_only")
        )
        row["child_exit_code"] = completed.returncode if completed else None
        row["attempts"] = attempts
        results.append(row)
        print(
            json.dumps(
                {
                    "index": index,
                    "total": len(source_rows),
                    "issue_id": issue_id,
                    "gt": row.get("gt_for_scoring_only"),
                    "pred": row.get("label"),
                    "exit": completed.returncode,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    summary = {
        "model_only": True,
        "training_used": False,
        "holdout_used": False,
        "expected_count": args.expected_count,
        "model": args.model,
        "endpoint": args.endpoint,
        "retries": args.retries,
        "prompt_input_variant": (
            f"{args.facts_mode}_facts_{args.output_mode}_output_{args.visual_mode}_"
            f"{args.report_mode}_{args.prompt_variant}_{args.text_layout}_{model_slug}"
        ),
        "results": results,
        "metrics": _metrics(results),
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["metrics"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
