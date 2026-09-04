from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DATASET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CASE_ID_RE = re.compile(r"^cn[0-9]+_[0-9]+$")
BEV_FRAME_RE = re.compile(r"^bev_default_t(?P<sign>[+-])(?P<value>[0-9]+)ms\.(?:png|jpe?g|webp)$", re.I)
CAMERA_FRAME_RE = re.compile(r"^(?P<index>[0-9]+)\.(?:png|jpe?g|webp)$", re.I)
DEFAULT_CAMERA_OFFSETS_MS = (-19000, -15000, -10000, -5000, 0, 5000, 10000, 15000, 19000)


def _root_confined(root: Path, candidate: Path) -> Path:
    resolved_root = root.expanduser().resolve()
    resolved = candidate.expanduser().resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("媒体文件超出已注册数据集根目录。") from exc
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _sha256_lines(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


@dataclass(frozen=True)
class IntentDatasetSpec:
    dataset_id: str
    display_name: str
    scene_set: str
    expected_case_count: int
    source_sha256: str
    bev_root: Path
    camera_root: Path | None
    camera_manifest: Path | None
    camera_manifest_frame_subdir: str
    membership_file: Path | None
    membership_format: str
    membership_file_sha256: str
    camera_offsets_ms: tuple[int, ...]
    camera_subdir: str
    max_pair_delta_ms: int
    excluded_bev_offsets_ms: tuple[int, ...]
    excluded_bev_offsets_by_case: dict[str, tuple[int, ...]]


class IntentDatasetIndex:
    """Immutable, root-confined Camera/BEV timeline index for intent labeling."""

    def __init__(self, specs: Iterable[IntentDatasetSpec], *, base_path: str = ""):
        self._specs = {spec.dataset_id: spec for spec in specs}
        self._base_path = base_path.rstrip("/")
        self._lock = threading.RLock()
        self._cases: dict[str, tuple[str, ...]] = {}
        self._camera_by_issue: dict[str, dict[str, tuple[str, ...]]] = {}
        self._camera_manifest_frames: dict[
            str, dict[str, dict[int, tuple[Path, int | None]]]
        ] = {}

    @classmethod
    def from_file(cls, path: Path, *, base_path: str = "") -> "IntentDatasetIndex":
        if not path.is_file():
            return cls((), base_path=base_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("datasets") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("intent dataset registry 必须包含 datasets 数组。")
        specs: list[IntentDatasetSpec] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("intent dataset registry 行必须是对象。")
            dataset_id = str(row.get("id") or "").strip()
            if not DATASET_ID_RE.fullmatch(dataset_id):
                raise ValueError(f"intent dataset id 不合法: {dataset_id}")
            bev_root = cls._configured_path(row, "bev_root", "bev_root_env")
            camera_root = cls._configured_path(
                row, "camera_root", "camera_root_env", optional=True
            )
            camera_manifest = cls._configured_path(
                row, "camera_manifest", "camera_manifest_env", optional=True
            )
            membership = str(row.get("membership_file") or "").strip()
            membership_file = (bev_root / membership).resolve() if membership else None
            if membership_file is not None:
                try:
                    membership_file.relative_to(bev_root)
                except ValueError as exc:
                    raise ValueError(
                        f"{dataset_id}: membership_file 必须位于 BEV 根目录内。"
                    ) from exc
            offsets = row.get("camera_offsets_ms") or DEFAULT_CAMERA_OFFSETS_MS
            camera_offsets = tuple(int(value) for value in offsets)
            if len(set(camera_offsets)) != len(camera_offsets):
                raise ValueError(f"{dataset_id}: Camera offset 不能重复。")
            specs.append(
                IntentDatasetSpec(
                    dataset_id=dataset_id,
                    display_name=str(row.get("display_name") or dataset_id).strip(),
                    scene_set=str(row.get("scene_set") or "").strip(),
                    expected_case_count=max(0, int(row.get("expected_case_count") or 0)),
                    source_sha256=str(row.get("source_sha256") or "").strip(),
                    bev_root=bev_root,
                    camera_root=camera_root,
                    camera_manifest=camera_manifest,
                    camera_manifest_frame_subdir=str(
                        row.get("camera_manifest_frame_subdir") or "frames"
                    ).strip(),
                    membership_file=membership_file,
                    membership_format=str(
                        row.get("membership_format") or "sha256sum-v1"
                    ).strip(),
                    membership_file_sha256=str(
                        row.get("membership_file_sha256") or ""
                    ).strip().lower(),
                    camera_offsets_ms=tuple(sorted(camera_offsets)),
                    camera_subdir=str(row.get("camera_subdir") or "after_compress").strip(),
                    max_pair_delta_ms=max(0, int(row.get("max_pair_delta_ms") or 500)),
                    excluded_bev_offsets_ms=tuple(
                        sorted({int(value) for value in row.get("excluded_bev_offsets_ms") or []})
                    ),
                    excluded_bev_offsets_by_case={
                        str(case_id): tuple(sorted({int(value) for value in values}))
                        for case_id, values in (row.get("excluded_bev_offsets_by_case") or {}).items()
                        if isinstance(values, list)
                    },
                )
            )
        return cls(specs, base_path=base_path)

    @staticmethod
    def _configured_path(
        row: dict[str, Any],
        value_key: str,
        env_key: str,
        *,
        optional: bool = False,
    ) -> Path | None:
        env_name = str(row.get(env_key) or "").strip()
        raw = os.getenv(env_name, "").strip() if env_name else ""
        raw = raw or str(row.get(value_key) or "").strip()
        if not raw:
            if optional:
                return None
            # A deliberately unavailable dataset is still listed in the UI.
            return Path("/__intent_dataset_unavailable__").resolve()
        return Path(raw).expanduser().resolve()

    def refresh(self) -> None:
        cases: dict[str, tuple[str, ...]] = {}
        camera_by_issue: dict[str, dict[str, tuple[str, ...]]] = {}
        camera_manifest_frames: dict[
            str, dict[str, dict[int, tuple[Path, int | None]]]
        ] = {}
        manifest_cache: dict[
            tuple[Path, Path, str], dict[str, dict[int, tuple[Path, int | None]]]
        ] = {}
        for dataset_id, spec in self._specs.items():
            case_ids = self._membership_cases(spec)
            cases[dataset_id] = tuple(case_ids)
            camera_map: dict[str, list[str]] = {}
            if spec.camera_root and spec.camera_root.is_dir():
                for path in spec.camera_root.iterdir():
                    if not path.is_dir() or not CASE_ID_RE.fullmatch(path.name):
                        continue
                    issue_id = path.name.rsplit("_", 1)[0]
                    camera_map.setdefault(issue_id, []).append(path.name)
            camera_by_issue[dataset_id] = {
                issue_id: tuple(sorted(names)) for issue_id, names in camera_map.items()
            }
            camera_manifest_frames[dataset_id] = self._load_camera_manifest(
                spec, frozenset(case_ids), manifest_cache
            )
        with self._lock:
            self._cases = cases
            self._camera_by_issue = camera_by_issue
            self._camera_manifest_frames = camera_manifest_frames

    @staticmethod
    def _load_camera_manifest(
        spec: IntentDatasetSpec,
        case_ids: frozenset[str],
        cache: dict[
            tuple[Path, Path, str], dict[str, dict[int, tuple[Path, int | None]]]
        ],
    ) -> dict[str, dict[int, tuple[Path, int | None]]]:
        manifest = spec.camera_manifest
        if (
            spec.camera_root is None
            or manifest is None
            or not manifest.is_file()
            or not spec.camera_root.is_dir()
        ):
            return {}
        root = spec.camera_root.resolve()
        frame_root = (root / spec.camera_manifest_frame_subdir).resolve()
        try:
            frame_root.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"{spec.dataset_id}: Camera manifest frame 子目录越界。"
            ) from exc
        cache_key = (root, manifest.resolve(), spec.camera_manifest_frame_subdir)
        if cache_key in cache:
            return {
                case_id: frames
                for case_id, frames in cache[cache_key].items()
                if case_id in case_ids
            }
        result: dict[str, dict[int, tuple[Path, int | None]]] = {}
        with manifest.open(encoding="utf-8", errors="strict") as handle:
            for line_number, raw in enumerate(handle, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                    case_id = str(row.get("episode") or "").strip()
                    offset_ms = int(row["frame_offset_ms"])
                    source_suffix = Path(str(row.get("image_path") or "")).suffix.lower()
                except (
                    AttributeError,
                    KeyError,
                    TypeError,
                    ValueError,
                    json.JSONDecodeError,
                ) as exc:
                    raise ValueError(
                        f"{spec.dataset_id}: Camera manifest 第 {line_number} 行不合法。"
                    ) from exc
                if row.get("schema") != "routing_camera41_frame_asset_v1":
                    raise ValueError(
                        f"{spec.dataset_id}: Camera manifest 第 {line_number} 行 "
                        "schema 不合法。"
                    )
                if source_suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                    raise ValueError(
                        f"{spec.dataset_id}: Camera manifest 第 {line_number} 行"
                        "图片格式不合法。"
                    )
                candidate = (
                    frame_root
                    / case_id
                    / f"camera_t{offset_ms:+d}ms{source_suffix}"
                )
                if not candidate.is_file():
                    continue
                by_offset = result.setdefault(case_id, {})
                if offset_ms in by_offset:
                    raise ValueError(
                        f"{case_id}: Camera manifest offset 重复: {offset_ms}"
                    )
                raw_delta = row.get("selection_diff_ms")
                delta_ms = int(raw_delta) if raw_delta is not None else None
                by_offset[offset_ms] = (candidate, delta_ms)
        cache[cache_key] = result
        return {
            case_id: frames
            for case_id, frames in result.items()
            if case_id in case_ids
        }

    def _membership_cases(self, spec: IntentDatasetSpec) -> list[str]:
        if not spec.bev_root.is_dir():
            return []
        case_ids: set[str] = set()
        membership = spec.membership_file
        if membership is not None and not membership.is_file():
            return []
        if membership and membership.is_file():
            root = spec.bev_root.resolve()
            raw_bytes = membership.read_bytes()
            if spec.membership_file_sha256:
                actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
                if actual_sha256 != spec.membership_file_sha256:
                    raise ValueError(
                        f"{spec.dataset_id}: membership_file SHA256 不匹配。"
                    )
            if spec.membership_format == "source-rows-json-v1":
                try:
                    rows = json.loads(raw_bytes.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"{spec.dataset_id}: source rows JSON 不合法。"
                    ) from exc
                if not isinstance(rows, list):
                    raise ValueError(f"{spec.dataset_id}: source rows 必须是数组。")
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError(f"{spec.dataset_id}: source row 必须是对象。")
                    if spec.scene_set and row.get("dataset_release") != spec.scene_set:
                        raise ValueError(
                            f"{spec.dataset_id}: source row 的 dataset_release 不匹配。"
                        )
                    issue_id = str(row.get("issue_id") or "").strip()
                    timestamp_ms = row.get("capture_timestamp_ms")
                    try:
                        case_id = f"{issue_id}_{int(timestamp_ms)}"
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            f"{spec.dataset_id}: source row 缺少合法时间戳。"
                        ) from exc
                    if not CASE_ID_RE.fullmatch(case_id):
                        raise ValueError(f"{spec.dataset_id}: source row Case ID 不合法。")
                    if not (root / case_id).is_dir():
                        raise ValueError(f"{spec.dataset_id}: source row 缺少 Case 目录。")
                    case_ids.add(case_id)
                if len(case_ids) != len(rows):
                    raise ValueError(f"{spec.dataset_id}: source rows 含重复 Case。")
            elif spec.membership_format == "sha256sum-v1":
                for raw in raw_bytes.decode("utf-8", errors="replace").splitlines():
                    parts = raw.strip().split(maxsplit=1)
                    if len(parts) != 2:
                        continue
                    relative = parts[1].lstrip("*./")
                    case_id = relative.split("/", 1)[0]
                    if CASE_ID_RE.fullmatch(case_id) and (root / case_id).is_dir():
                        case_ids.add(case_id)
            else:
                raise ValueError(
                    f"{spec.dataset_id}: membership_format 不受支持。"
                )
        else:
            case_ids = {
                path.name
                for path in spec.bev_root.iterdir()
                if path.is_dir() and CASE_ID_RE.fullmatch(path.name)
            }
        return sorted(case_ids)

    def dataset(self, dataset_id: str) -> IntentDatasetSpec:
        try:
            return self._specs[dataset_id]
        except KeyError as exc:
            raise KeyError("意图标注数据集不存在。") from exc

    def public_datasets(self) -> list[dict[str, Any]]:
        with self._lock:
            indexed = dict(self._cases)
            manifest_frames = dict(self._camera_manifest_frames)
        items = []
        for dataset_id, spec in self._specs.items():
            case_ids = indexed.get(dataset_id, ())
            camera_cases = manifest_frames.get(dataset_id, {})
            coverage_ok = bool(case_ids) and (
                not spec.expected_case_count or len(case_ids) == spec.expected_case_count
            )
            items.append(
                {
                    "id": dataset_id,
                    "display_name": spec.display_name,
                    "scene_set": spec.scene_set,
                    "case_count": len(case_ids),
                    "expected_case_count": spec.expected_case_count,
                    "source_sha256": spec.source_sha256,
                    "available": coverage_ok,
                    "coverage_ok": coverage_ok,
                    "camera_case_count": len(camera_cases),
                    "camera_frame_count": sum(len(items) for items in camera_cases.values()),
                }
            )
        return items

    def case_ids(self, dataset_id: str) -> tuple[str, ...]:
        self.dataset(dataset_id)
        with self._lock:
            return self._cases.get(dataset_id, ())

    def has_case(self, dataset_id: str, case_id: str) -> bool:
        return case_id in set(self.case_ids(dataset_id))

    def membership_sha256(self, dataset_id: str) -> str:
        return _sha256_lines(self.case_ids(dataset_id))

    @staticmethod
    def _issue_id(case_id: str) -> str:
        return case_id.rsplit("_", 1)[0]

    def _camera_case_id(self, dataset_id: str, case_id: str) -> str | None:
        spec = self.dataset(dataset_id)
        if spec.camera_root is None:
            return None
        exact = spec.camera_root / case_id
        if exact.is_dir():
            return case_id
        issue_id = self._issue_id(case_id)
        with self._lock:
            candidates = self._camera_by_issue.get(dataset_id, {}).get(issue_id, ())
        if not candidates:
            return None
        try:
            target = int(case_id.rsplit("_", 1)[1])
            return min(candidates, key=lambda value: abs(int(value.rsplit("_", 1)[1]) - target))
        except (ValueError, IndexError):
            return candidates[0]

    def timeline(self, dataset_id: str, case_id: str) -> list[dict[str, Any]]:
        spec = self.dataset(dataset_id)
        if not self.has_case(dataset_id, case_id):
            raise KeyError("Case 不在该意图标注数据集中。")
        bev_dir = spec.bev_root / case_id / "frames"
        bev_frames: dict[int, Path] = {}
        excluded_bev_offsets = set(spec.excluded_bev_offsets_ms)
        excluded_bev_offsets.update(spec.excluded_bev_offsets_by_case.get(case_id, ()))
        if bev_dir.is_dir():
            for path in bev_dir.iterdir():
                match = BEV_FRAME_RE.fullmatch(path.name)
                if not match or not path.is_file():
                    continue
                value = int(match.group("value"))
                offset_ms = -value if match.group("sign") == "-" else value
                if offset_ms in excluded_bev_offsets:
                    continue
                if offset_ms in bev_frames:
                    raise ValueError(f"{case_id}: BEV offset 重复: {offset_ms}")
                bev_frames[offset_ms] = path
        camera_frames: dict[int, Path] = {}
        camera_deltas: dict[int, int | None] = {}
        with self._lock:
            manifest_camera = dict(
                self._camera_manifest_frames.get(dataset_id, {}).get(case_id, {})
            )
        for offset_ms, (path, delta_ms) in manifest_camera.items():
            camera_frames[offset_ms] = path
            camera_deltas[offset_ms] = delta_ms
        camera_case_id = self._camera_case_id(dataset_id, case_id)
        camera_trigger_delta_ms: int | None = None
        if not camera_frames and spec.camera_root and camera_case_id:
            try:
                camera_trigger_delta_ms = int(camera_case_id.rsplit("_", 1)[1]) - int(
                    case_id.rsplit("_", 1)[1]
                )
            except (ValueError, IndexError):
                camera_trigger_delta_ms = None
            camera_dir = spec.camera_root / camera_case_id / spec.camera_subdir
            if camera_dir.is_dir() and (
                camera_trigger_delta_ms is None
                or abs(camera_trigger_delta_ms) <= spec.max_pair_delta_ms
            ):
                numbered: list[tuple[int, Path]] = []
                for path in camera_dir.iterdir():
                    match = CAMERA_FRAME_RE.fullmatch(path.name)
                    if match and path.is_file():
                        numbered.append((int(match.group("index")), path))
                numbered.sort()
                for position, (_, path) in enumerate(numbered):
                    if position >= len(spec.camera_offsets_ms):
                        break
                    camera_frames[spec.camera_offsets_ms[position]] = path
        offsets = sorted(set(bev_frames) | set(camera_frames))
        result: list[dict[str, Any]] = []
        for offset_ms in offsets:
            bev = bev_frames.get(offset_ms)
            camera = camera_frames.get(offset_ms)
            timepoint_id = f"t:{offset_ms:+d}"
            result.append(
                {
                    "id": timepoint_id,
                    "offset_ms": offset_ms,
                    "bev": self._descriptor(dataset_id, case_id, "bev", offset_ms, bev),
                    "camera": self._descriptor(dataset_id, case_id, "camera", offset_ms, camera),
                    "camera_delta_ms": (
                        camera_deltas.get(offset_ms)
                        if offset_ms in camera_deltas
                        else camera_trigger_delta_ms if camera is not None else None
                    ),
                }
            )
        return result

    def _descriptor(
        self,
        dataset_id: str,
        case_id: str,
        kind: str,
        offset_ms: int,
        path: Path | None,
    ) -> dict[str, Any] | None:
        if path is None:
            return None
        asset_id = f"{kind}_{offset_ms:+d}"
        prefix = self._base_path
        url = (
            f"{prefix}/api/intent-datasets/{dataset_id}/cases/{case_id}/assets/{asset_id}"
        )
        return {"asset_id": asset_id, "url": url, "thumbnail_url": url}

    def resolve_asset(
        self, dataset_id: str, case_id: str, asset_id: str
    ) -> tuple[Path, str]:
        spec = self.dataset(dataset_id)
        match = re.fullmatch(r"(bev|camera)_([+-][0-9]+)", asset_id)
        if match is None:
            raise KeyError("媒体 asset id 不合法。")
        kind, raw_offset = match.groups()
        offset_ms = int(raw_offset)
        timepoint = next(
            (item for item in self.timeline(dataset_id, case_id) if item["offset_ms"] == offset_ms),
            None,
        )
        descriptor = timepoint.get(kind) if timepoint else None
        if not descriptor:
            raise KeyError("媒体文件不存在。")
        if kind == "bev":
            root = spec.bev_root
            path = root / case_id / "frames"
            candidates = [item for item in path.iterdir() if item.is_file() and BEV_FRAME_RE.fullmatch(item.name)]
            for candidate in candidates:
                frame_match = BEV_FRAME_RE.fullmatch(candidate.name)
                assert frame_match is not None
                value = int(frame_match.group("value"))
                candidate_offset = -value if frame_match.group("sign") == "-" else value
                if candidate_offset == offset_ms:
                    resolved = _root_confined(root, candidate)
                    media_type = {
                        ".png": "image/png",
                        ".webp": "image/webp",
                    }.get(resolved.suffix.lower(), "image/jpeg")
                    return resolved, media_type
        else:
            if spec.camera_root is None:
                raise KeyError("Camera 根目录不可用。")
            with self._lock:
                manifest_frame = self._camera_manifest_frames.get(dataset_id, {}).get(
                    case_id, {}
                ).get(offset_ms)
            if manifest_frame is not None:
                resolved = _root_confined(spec.camera_root, manifest_frame[0])
                media_type = {
                    ".png": "image/png",
                    ".webp": "image/webp",
                }.get(resolved.suffix.lower(), "image/jpeg")
                return resolved, media_type
            camera_case_id = self._camera_case_id(dataset_id, case_id)
            if camera_case_id is None:
                raise KeyError("Camera Case 不存在。")
            try:
                position = spec.camera_offsets_ms.index(offset_ms)
            except ValueError as exc:
                raise KeyError("Camera 时间点不存在。") from exc
            camera_dir = spec.camera_root / camera_case_id / spec.camera_subdir
            numbered = sorted(
                (
                    (int(match.group("index")), path)
                    for path in camera_dir.iterdir()
                    if path.is_file() and (match := CAMERA_FRAME_RE.fullmatch(path.name))
                ),
                key=lambda item: item[0],
            )
            if position < len(numbered):
                resolved = _root_confined(spec.camera_root, numbered[position][1])
                media_type = {
                    ".png": "image/png",
                    ".webp": "image/webp",
                }.get(resolved.suffix.lower(), "image/jpeg")
                return resolved, media_type
        raise KeyError("媒体文件不存在。")
