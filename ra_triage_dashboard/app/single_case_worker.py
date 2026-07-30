"""Controlled one-issue runner for the dashboard.

The request is read from stdin.  In particular, the API key is never passed in
argv, environment variables, a config file, or the dashboard database.
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any


RESULT_PREFIX = "__RA_TRIAGE_DASHBOARD_RESULT__"
ISSUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,128}$")


def emit(payload: dict[str, Any]) -> None:
    print(RESULT_PREFIX + json.dumps(payload, ensure_ascii=False), flush=True)


def fail(message: str) -> int:
    emit({"success": False, "error": message})
    return 1


def load_issue(issue_id: str):
    from utils.get_ra_issue_utils import get_self_issue

    frame = get_self_issue(
        additional_conditions=[
            {"attr_id": "issue_id", "val": [issue_id], "operator": "like"}
        ]
    )
    if frame.empty:
        raise ValueError(f"Trail 未找到 issue_id={issue_id}")
    exact = frame[frame["issue_id"].astype(str) == issue_id]
    row = exact.iloc[0] if not exact.empty else frame.iloc[0]
    if str(row.get("issue_id") or "") != issue_id:
        raise ValueError(f"Trail 查询未得到精确 issue_id={issue_id}")
    return row


def capture_present(manifest_path: str, issue_id: str) -> bool:
    path = Path(manifest_path)
    if not path.is_file():
        return False
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if row.get("issue_id") == issue_id and row.get("status") == "captured":
                return True
    return False


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
    except (TypeError, ValueError):
        return fail("请求格式非法：worker 需要 JSON stdin。")

    issue_id = str(request.get("issue_id") or "").strip()
    if not ISSUE_ID_RE.fullmatch(issue_id):
        return fail("issue_id 格式非法。")

    ra_root = Path(os.environ.get("RA_AUTO_TRIAGE_ROOT", "")).expanduser().resolve()
    if not (ra_root / "vlm").is_dir():
        return fail("RA_AUTO_TRIAGE_ROOT 无效或未配置。")

    # Must be applied before importing ra_auto_triage modules.
    os.environ["RA_TOOLS_ENABLED"] = "false"
    os.environ["BAG_CACHE_READ_ONLY"] = "true"
    if str(ra_root) not in sys.path:
        sys.path.insert(0, str(ra_root))

    try:
        row = load_issue(issue_id)
        timestamp_column = (
            "ra_start_timestamp"
            if "ra_start_timestamp" in row.index
            else "ra_start_time"
        )
        request_timestamp = int(row[timestamp_column])
        trip_id = str(row["trip_id"])
    except Exception as exc:
        return fail(f"读取 Trail issue 失败: {exc}")

    manifest = str(request.get("bev_animation_manifest") or "").strip()
    use_bev = bool(request.get("use_bev_animation", True))
    if use_bev and not capture_present(manifest, issue_id):
        return fail("此 issue 没有可用 Ares Capture BEV 资产；请先补捕获或关闭 BEV 输入。")

    if bool(request.get("dry_run")):
        emit(
            {
                "success": True,
                "dry_run": True,
                "issue_id": issue_id,
                "trip_id": trip_id,
                "request_timestamp": request_timestamp,
                "ra_tools_enabled": os.environ["RA_TOOLS_ENABLED"],
                "bag_cache_read_only": os.environ["BAG_CACHE_READ_ONLY"],
                "bev_asset_available": bool(use_bev),
            }
        )
        return 0

    model_name = str(request.get("model_name") or "").strip()
    base_url = str(request.get("base_url") or "").strip()
    api_key = str(request.get("api_key") or "").strip()
    if not model_name or not base_url or not api_key:
        return fail("模型名、base URL 与 API key 均为必填。")

    try:
        from vlm import Experiment
        from vlm.scripts.internal.experiment_cli import experiment_to_worker_dict
        from vlm.scripts.internal.models import ProcessingTask
        from vlm.scripts.internal.worker import process_single_issue

        experiment = Experiment(
            prompt_version=str(request.get("prompt_version") or "stuck_triage_v1"),
            frame_offsets_ms=[-3000, -2000, -1000, 0, 1000, 2000, 3000],
            time_window_offsets_ms=[
                -15000,
                -10000,
                -5000,
                0,
                5000,
                10000,
                15000,
                20000,
            ],
            camera_topic="/camera_video_frame_102",
            camera_topics=["/camera_video_frame_102"],
            use_ra_event=True,
            use_ra_options=bool(request.get("use_ra_options", True)),
            use_trajectory_summary=False,
            use_bev_animation=use_bev,
            bev_mode="raw_frames" if use_bev else "disabled",
            bev_animation_manifest=manifest if use_bev else "",
            bev_frame_offsets_ms=[-19000, -15000, -10000, -5000, 0, 5000, 10000, 15000, 19000],
            bev_fail_open=False,
            model_name=model_name,
            provider=str(request.get("provider") or ""),
            base_url=base_url,
            api_key=api_key,
            max_tokens=int(request.get("max_tokens") or 512),
            temperature=float(request.get("temperature") or 0.6),
            config_merge_mode="none",
            author="ra_triage_dashboard",
            description="dashboard single-case inference",
        )
        task = ProcessingTask(
            idx=0,
            issue_id=issue_id,
            trip_id=trip_id,
            request_ts=request_timestamp,
            row_data=row.to_dict(),
        )
        result = process_single_issue(task, experiment_to_worker_dict(experiment))
        emit({"success": bool(result.result_data.get("success")), "result": result.result_data})
        return 0 if result.result_data.get("success") else 1
    except Exception as exc:
        traceback.print_exc()
        return fail(f"单 case 推理失败: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
