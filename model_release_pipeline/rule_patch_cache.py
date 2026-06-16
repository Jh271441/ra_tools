"""Persistent per-release state for the Rule Patch workflow.

Two small JSON sidecar files live next to the runs directory (mirroring the
``web/stage_config.py`` defaults-file pattern):

* ``<runs>_rule_patch_test_crs.json`` — maps a release branch to the kunpeng
  revision id of its persistent 测试CR. The first ``dcl diff`` on a release
  creates the CR; later runs (any rule CR) update that same revision with a new
  patchset, so we cache the id and reuse it via ``dcl diff -n -u <id>``.
* ``<runs>_rule_patch_releases.json`` — a remembered list of release branches
  (including ad-hoc ones typed in the UI) so the release picker can offer them
  again on the next run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _test_crs_path(runs_dir: Path) -> Path:
    runs_dir = Path(runs_dir).expanduser()
    return runs_dir.parent / f"{runs_dir.name}_rule_patch_test_crs.json"


def _releases_path(runs_dir: Path) -> Path:
    runs_dir = Path(runs_dir).expanduser()
    return runs_dir.parent / f"{runs_dir.name}_rule_patch_releases.json"


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


# --- test-CR cache ---------------------------------------------------------


def read_cached_crs(runs_dir: Path) -> Dict[str, str]:
    data = _read_json(_test_crs_path(runs_dir))
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v}


def get_cached_cr(runs_dir: Path, release_branch: str) -> str:
    return read_cached_crs(runs_dir).get(str(release_branch), "")


def set_cached_cr(runs_dir: Path, release_branch: str, revision_id: str) -> None:
    release_branch = str(release_branch or "").strip()
    revision_id = str(revision_id or "").strip()
    if not release_branch or not revision_id:
        return
    cache = read_cached_crs(runs_dir)
    cache[release_branch] = revision_id
    _write_json(_test_crs_path(runs_dir), cache)


# --- remembered releases ---------------------------------------------------


def remembered_releases(runs_dir: Path) -> List[str]:
    data = _read_json(_releases_path(runs_dir))
    if not isinstance(data, list):
        return []
    seen: List[str] = []
    for item in data:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def remember_release(runs_dir: Path, release_branch: str) -> None:
    release_branch = str(release_branch or "").strip()
    if not release_branch:
        return
    releases = remembered_releases(runs_dir)
    if release_branch in releases:
        return
    releases.append(release_branch)
    _write_json(_releases_path(runs_dir), releases)


def remember_releases(runs_dir: Path, release_branches: Optional[List[str]]) -> None:
    for branch in release_branches or []:
        remember_release(runs_dir, branch)
