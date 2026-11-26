"""Stream-exporter for Release 1030 road scenarios to Enhanced Onboard Road NPZs.

Key guarantees:
  - Downloads ONLY the 5 lightweight Onboard Stuck topics via ``voy-bag`` (never cameras/lidar).
  - Includes a configurable pre-window warmup (default ``5000ms``, matching EzSim warmup) before
    ``scenario_start_timestamp`` and stores ``formal_window_ms = [scenario_start_timestamp,
    scenario_end_timestamp]`` inside every ``.npz``.
  - Deletes each temporary ``.bag`` in a ``finally:`` block immediately after ``.npz`` + ``.EXPORT.json``
    are written, keeping ``.staging/`` near zero bytes at all times.
  - Enforces a minimum free-disk guard (default ``50 GB``) before every download.
  - Resume-safe and idempotent across restarts.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .bag_exporter import LIGHTWEIGHT_DOWNLOAD_TOPICS, download_road_scenario_bag, export_road_bag_to_npz


DEFAULT_1030_SCENARIOS = Path(
    "reports/stuck_source_business_weight_20261115_v1/sim1030_blueprint_v5/full_population_scenarios.private.jsonl"
)
DEFAULT_1030_ISSUES = Path(
    "reports/stuck_source_business_weight_20261115_v1/sim1030_blueprint_v5/issues.private.jsonl"
)


@dataclass(frozen=True)
class ScenarioExportTask:
    issue_id: str
    scenario_id: str
    trip_id: str
    download_start_ms: int
    download_end_ms: int
    formal_start_ms: int
    formal_end_ms: int
    ra_start_ms: int


def build_1030_export_tasks(
    scenarios_jsonl: Path,
    issues_jsonl: Path,
    *,
    warmup_ms: int = 5000,
) -> List[ScenarioExportTask]:
    """Build the 1,561 scenario export tasks from the frozen 1030 blueprint JSONLs."""
    issues_by_id: Dict[str, Dict[str, Any]] = {}
    for line in Path(issues_jsonl).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            issues_by_id[row["issue_id"]] = row

    tasks: List[ScenarioExportTask] = []
    seen = set()
    for line in Path(scenarios_jsonl).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        sc = json.loads(line)
        issue_id = str(sc["issue_id"])
        if issue_id in seen:
            raise ValueError(f"Duplicate issue_id in scenarios manifest: {issue_id}")
        seen.add(issue_id)
        issue = issues_by_id.get(issue_id)
        if issue is None:
            raise KeyError(f"Scenario issue_id {issue_id} missing from issues manifest")
        phys = issue.get("physical") or {}
        trip_id = str(phys.get("trip_id") or "")
        if not trip_id:
            raise ValueError(f"Missing physical.trip_id for {issue_id}")

        formal_start = int(sc["scenario_start_timestamp"])
        formal_end = int(sc["scenario_end_timestamp"])
        ra_start = int(sc.get("ra_start_timestamp", formal_start))
        # Request [formal_start - warmup_ms, formal_end] from Tempest (Tempest clips to available trip range)
        dl_start = max(0, formal_start - int(warmup_ms))
        dl_end = formal_end
        tasks.append(
            ScenarioExportTask(
                issue_id=issue_id,
                scenario_id=str(sc["scenario_id"]),
                trip_id=trip_id,
                download_start_ms=dl_start,
                download_end_ms=dl_end,
                formal_start_ms=formal_start,
                formal_end_ms=formal_end,
                ra_start_ms=ra_start,
            )
        )
    return tasks


def _safe_dir_bytes(root: Path) -> int:
    total_b = 0
    try:
        for dirpath, _, filenames in os.walk(root):
            for fname in filenames:
                try:
                    total_b += os.path.getsize(os.path.join(dirpath, fname))
                except OSError:
                    pass
    except OSError:
        pass
    return total_b


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}.json")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _export_one_task(
    task: ScenarioExportTask,
    npz_dir_str: str,
    staging_root_str: str,
    overwrite: bool,
    min_free_gb: float,
    max_retries: int,
) -> Dict[str, Any]:
    npz_dir = Path(npz_dir_str)
    staging_root = Path(staging_root_str)
    out_npz = npz_dir / f"{task.issue_id}.npz"
    out_receipt = npz_dir / f"{task.issue_id}.EXPORT.json"

    if not overwrite and out_npz.is_file() and out_receipt.is_file():
        try:
            existing = json.loads(out_receipt.read_text(encoding="utf-8"))
            return {
                "issue_id": task.issue_id,
                "scenario_id": task.scenario_id,
                "status": "reused",
                "npz_bytes": out_npz.stat().st_size,
                "tensor_dict_frames": int(existing.get("tensor_dict_frames", 0)),
                "speed_cycles_10hz": int(existing.get("speed_cycles_10hz", 0)),
                "unmatched_score_cycles": len(existing.get("unmatched_score_cycles", [])),
                "elapsed_sec": 0.0,
            }
        except Exception:
            pass

    free_bytes = shutil.disk_usage(npz_dir).free
    min_bytes = int(min_free_gb * (1024**3))
    if free_bytes < min_bytes:
        return {
            "issue_id": task.issue_id,
            "scenario_id": task.scenario_id,
            "status": "failed",
            "error": f"Disk free space {free_bytes / (1024**3):.2f} GB < guard {min_free_gb:.1f} GB",
            "elapsed_sec": 0.0,
        }

    t0 = time.perf_counter()
    last_err = ""
    worker_tmp = staging_root / f"w_{os.getpid()}_{task.issue_id}"

    for attempt in range(1, max_retries + 1):
        bag_file: Optional[Path] = None
        try:
            worker_tmp.mkdir(parents=True, exist_ok=True)
            bag_file = download_road_scenario_bag(
                task.scenario_id,
                worker_tmp,
                trip_id=task.trip_id,
                start_ms=task.download_start_ms,
                end_ms=task.download_end_ms,
                topics=LIGHTWEIGHT_DOWNLOAD_TOPICS,
            )
            receipt = export_road_bag_to_npz(
                bag_file,
                out_npz,
                case_id=task.issue_id,
                trip_id=task.trip_id,
                source_kind="road",
                formal_window_ms=(task.formal_start_ms, task.formal_end_ms),
                overwrite=True,
            )
            return {
                "issue_id": task.issue_id,
                "scenario_id": task.scenario_id,
                "status": "exported",
                "attempts": attempt,
                "bag_bytes": int(receipt["source_bag_bytes"]),
                "npz_bytes": int(receipt["npz_bytes"]),
                "tensor_dict_frames": int(receipt["tensor_dict_frames"]),
                "speed_cycles_10hz": int(receipt["speed_cycles_10hz"]),
                "unmatched_score_cycles": len(receipt["unmatched_score_cycles"]),
                "elapsed_sec": round(time.perf_counter() - t0, 3),
            }
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < max_retries:
                time.sleep(1.5 * attempt)
        finally:
            if bag_file is not None:
                bag_file.unlink(missing_ok=True)
            if worker_tmp.is_dir():
                for child in worker_tmp.rglob("*"):
                    if child.is_file():
                        child.unlink(missing_ok=True)
                for child in sorted(worker_tmp.rglob("*"), reverse=True):
                    if child.is_dir():
                        try:
                            child.rmdir()
                        except OSError:
                            pass
                try:
                    worker_tmp.rmdir()
                except OSError:
                    pass

    return {
        "issue_id": task.issue_id,
        "scenario_id": task.scenario_id,
        "status": "failed",
        "attempts": max_retries,
        "error": last_err,
        "elapsed_sec": round(time.perf_counter() - t0, 3),
    }


def stream_export_1030_dataset(
    out_root: Path,
    *,
    scenarios_jsonl: Path = DEFAULT_1030_SCENARIOS,
    issues_jsonl: Path = DEFAULT_1030_ISSUES,
    warmup_ms: int = 5000,
    workers: int = 12,
    limit: Optional[int] = None,
    overwrite: bool = False,
    min_free_gb: float = 50.0,
    max_retries: int = 3,
) -> Dict[str, Any]:
    """Stream-export all 1,561 Release 1030 scenarios to ``<out_root>/npz/<issue_id>.npz``."""
    out_root = Path(out_root).expanduser().resolve()
    npz_dir = out_root / "npz"
    staging_root = out_root / ".staging"
    npz_dir.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)

    tasks = build_1030_export_tasks(scenarios_jsonl, issues_jsonl, warmup_ms=warmup_ms)
    if limit is not None and limit > 0:
        tasks = tasks[: int(limit)]

    total = len(tasks)
    started_at = time.time()
    t0 = time.perf_counter()
    progress_path = out_root / "EXPORT_PROGRESS.json"
    summary_path = out_root / "EXPORT_SUMMARY.json"

    results: List[Dict[str, Any]] = []
    exported_cnt = 0
    reused_cnt = 0
    failed_cnt = 0
    total_npz_bytes = 0
    zero_td_cases: List[str] = []

    def write_progress(done_now: int, final: bool = False) -> Dict[str, Any]:
        staging_leftover = _safe_dir_bytes(staging_root)
        free_gb = round(shutil.disk_usage(out_root).free / (1024**3), 2)
        payload = {
            "status": "completed" if (final and failed_cnt == 0) else ("completed_with_failures" if final else "running"),
            "started_at": started_at,
            "updated_at": time.time(),
            "elapsed_sec": round(time.perf_counter() - t0, 2),
            "total_scenarios": total,
            "completed": done_now,
            "exported": exported_cnt,
            "reused": reused_cnt,
            "failed": failed_cnt,
            "zero_tensor_dict_cases": sorted(zero_td_cases),
            "total_npz_bytes": total_npz_bytes,
            "total_npz_gb": round(total_npz_bytes / (1024**3), 3),
            "staging_bytes": staging_leftover,
            "disk_free_gb": free_gb,
            "warmup_ms": warmup_ms,
            "workers": workers,
        }
        _atomic_write_json(progress_path, payload)
        return payload

    write_progress(0, final=False)

    with ProcessPoolExecutor(max_workers=max(1, int(workers))) as pool:
        fut_map = {
            pool.submit(
                _export_one_task,
                t,
                str(npz_dir),
                str(staging_root),
                overwrite,
                min_free_gb,
                max_retries,
            ): t
            for t in tasks
        }
        for idx, fut in enumerate(as_completed(fut_map), start=1):
            row = fut.result()
            results.append(row)
            st = row["status"]
            if st == "exported":
                exported_cnt += 1
                total_npz_bytes += int(row.get("npz_bytes", 0))
                if int(row.get("tensor_dict_frames", 0)) == 0:
                    zero_td_cases.append(row["issue_id"])
            elif st == "reused":
                reused_cnt += 1
                total_npz_bytes += int(row.get("npz_bytes", 0))
                if int(row.get("tensor_dict_frames", 0)) == 0:
                    zero_td_cases.append(row["issue_id"])
            else:
                failed_cnt += 1

            if idx % 25 == 0 or idx == total:
                prog = write_progress(idx, final=False)
                print(
                    f"[export-1030] {idx}/{total} (exported={exported_cnt}, reused={reused_cnt}, "
                    f"failed={failed_cnt}, npz={prog['total_npz_gb']:.2f} GB, "
                    f"staging={prog['staging_bytes']} B, free={prog['disk_free_gb']:.1f} GB, "
                    f"elapsed={prog['elapsed_sec']:.1f}s)",
                    flush=True,
                )

    # Final cleanup of empty staging directories
    for child in sorted(staging_root.rglob("*"), reverse=True):
        if child.is_dir():
            try:
                child.rmdir()
            except OSError:
                pass

    final_prog = write_progress(len(results), final=True)
    failures = [r for r in sorted(results, key=lambda x: x["issue_id"]) if r["status"] == "failed"]
    summary = {
        **final_prog,
        "npz_dir": str(npz_dir),
        "failures": failures,
    }
    _atomic_write_json(summary_path, summary)
    return summary
