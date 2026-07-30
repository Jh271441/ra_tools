from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


PROMPT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
MAX_PROMPT_BYTES = 128 * 1024
MIN_PROMPT_CHARS = 32
DEFAULT_PROMPT_ID = "stuck_triage_auto_opt_api"
DEFAULT_FRAME_OFFSETS_MS = (-3000, -2000, -1000, 0, 1000, 2000, 3000)
MAX_FRAME_COUNT = 18
MIN_FRAME_OFFSET_MS = -30_000
MAX_FRAME_OFFSET_MS = 30_000
TRIAGE_LABELS = ("误触发", "正确触发", "无需协助")
FORBIDDEN_TRIAGE_LABELS = ("无法判断",)
ALLOWED_TEMPLATE_VARIABLES = frozenset(
    {
        "n_frames",
        "modality",
        "prompt_version",
        "frame_labels",
        "visual_timeline",
        "time_windows_json",
        "time_windows_table",
        "time_window_desc",
        "ra_info_structured",
        "ra_event_json",
        "trajectory_info",
        "rag_context",
        "bev_summary",
        "bev_raw_frame_guide",
        "version",
        "description",
    }
)

INPUT_PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "camera_ra_event",
        "display_name": "Camera 7 帧 + RA Events",
        "description": "当前 RA 三分类基线输入；保留触发后恢复与协助时序。",
        "frame_offsets_ms": list(DEFAULT_FRAME_OFFSETS_MS),
        "use_ra_event": True,
        "use_ra_options": False,
    },
    {
        "id": "camera_ra_options",
        "display_name": "Camera 7 帧 + RA Events + RA/SWAG Options",
        "description": "额外注入 RA 操作集合，适合分析 SWAG/人工协助链。",
        "frame_offsets_ms": list(DEFAULT_FRAME_OFFSETS_MS),
        "use_ra_event": True,
        "use_ra_options": True,
    },
    {
        "id": "camera_only",
        "display_name": "Camera 7 帧",
        "description": "只保留视觉与基础时序表，用于视觉输入消融。",
        "frame_offsets_ms": list(DEFAULT_FRAME_OFFSETS_MS),
        "use_ra_event": False,
        "use_ra_options": False,
    },
)


class PromptCatalogError(RuntimeError):
    pass


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalise_prompt_text(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) < MIN_PROMPT_CHARS:
        raise PromptCatalogError(f"Prompt 至少需要 {MIN_PROMPT_CHARS} 个字符。")
    if len(text.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise PromptCatalogError(
            f"Prompt 最大允许 {MAX_PROMPT_BYTES // 1024} KiB。"
        )
    if "\x00" in text or any(
        ord(char) < 32 and char not in {"\n", "\t"} for char in text
    ):
        raise PromptCatalogError("Prompt 含非法控制字符。")
    if "{%" in text or "{#" in text or text.count("{{") != text.count("}}"):
        raise PromptCatalogError("Prompt 只支持成对的 {{variable}} 占位符。")
    variables: set[str] = set()
    for raw in re.findall(r"{{(.*?)}}", text, flags=re.DOTALL):
        variable = raw.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable):
            raise PromptCatalogError(
                f"Prompt 占位符不受支持：{{{{{variable}}}}}。"
            )
        variables.add(variable)
    unknown = sorted(variables - ALLOWED_TEMPLATE_VARIABLES)
    if unknown:
        raise PromptCatalogError(
            f"Prompt 含当前三分类构建器不会提供的变量：{', '.join(unknown)}。"
        )
    missing_labels = [label for label in TRIAGE_LABELS if label not in text]
    if missing_labels:
        raise PromptCatalogError(
            "Prompt 必须保留三分类输出契约：误触发、正确触发、无需协助。"
        )
    forbidden_labels = [
        label for label in FORBIDDEN_TRIAGE_LABELS if label in text
    ]
    if forbidden_labels:
        raise PromptCatalogError(
            "Prompt 不能引入三分类以外的输出标签："
            f"{', '.join(forbidden_labels)}。"
        )
    return text


class PromptCatalog:
    """Read-only prompt templates from the deployed ra_auto_triage checkout."""

    def __init__(self, ra_root: Path):
        self.root = (ra_root / "vlm" / "prompts" / "versions").resolve()

    def list_prompts(self, *, include_template: bool = True) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        if self.root.is_dir():
            for directory in sorted(self.root.iterdir(), key=lambda path: path.name):
                if not directory.is_dir() or not PROMPT_ID_RE.fullmatch(directory.name):
                    continue
                template_path = (directory / "template.md").resolve()
                if self.root not in template_path.parents or not template_path.is_file():
                    continue
                try:
                    if template_path.stat().st_size > MAX_PROMPT_BYTES:
                        continue
                    template = _normalise_prompt_text(
                        template_path.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeDecodeError, PromptCatalogError):
                    continue
                item: dict[str, Any] = {
                    "id": directory.name,
                    "display_name": directory.name.replace("_", " "),
                    "sha256": _sha256(template),
                    "size_bytes": len(template.encode("utf-8")),
                    "is_default": directory.name == DEFAULT_PROMPT_ID,
                }
                if include_template:
                    item["template"] = template
                items.append(item)
        if not items:
            raise PromptCatalogError("ra_auto_triage 当前没有可读取的 Prompt 模板。")
        default_id = (
            DEFAULT_PROMPT_ID
            if any(item["id"] == DEFAULT_PROMPT_ID for item in items)
            else items[0]["id"]
        )
        return {
            "default_prompt_id": default_id,
            "items": items,
            "max_prompt_bytes": MAX_PROMPT_BYTES,
        }

    def resolve(self, prompt_id: Any, prompt_template: Any) -> dict[str, Any]:
        catalog = self.list_prompts(include_template=True)
        requested_id = (
            str(prompt_id or "").strip()
            or str(catalog["default_prompt_id"])
        )
        if not PROMPT_ID_RE.fullmatch(requested_id):
            raise PromptCatalogError("prompt_id 格式非法。")
        selected = next(
            (item for item in catalog["items"] if item["id"] == requested_id),
            None,
        )
        if selected is None:
            raise PromptCatalogError("所选 Prompt 不在当前服务器模板目录中。")
        supplied = str(prompt_template or "")
        template = (
            _normalise_prompt_text(supplied)
            if supplied.strip()
            else str(selected["template"])
        )
        return {
            "prompt_version": requested_id,
            "prompt_template": template,
            "prompt_template_sha256": _sha256(template),
            "prompt_mode": (
                "catalog"
                if template == str(selected["template"])
                else "custom"
            ),
            "prompt_source_sha256": str(selected["sha256"]),
        }


def normalise_input_config(value: Any) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise PromptCatalogError("input_config 必须是 JSON 对象。")
    allowed = {
        "profile_id",
        "frame_offsets_ms",
        "use_ra_event",
        "use_ra_options",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PromptCatalogError(
            f"input_config 包含不支持字段: {', '.join(unknown)}"
        )

    requested_profile = str(value.get("profile_id") or "camera_ra_event").strip()
    preset = next(
        (item for item in INPUT_PRESETS if item["id"] == requested_profile),
        None,
    )
    if preset is None and requested_profile != "custom":
        raise PromptCatalogError("input_config.profile_id 不受支持。")
    base = preset or INPUT_PRESETS[0]
    raw_offsets = value.get("frame_offsets_ms", base["frame_offsets_ms"])
    if not isinstance(raw_offsets, list) or not raw_offsets:
        raise PromptCatalogError("frame_offsets_ms 必须是非空整数数组。")
    if len(raw_offsets) > MAX_FRAME_COUNT:
        raise PromptCatalogError(f"Camera 帧最多允许 {MAX_FRAME_COUNT} 张。")
    offsets: list[int] = []
    for raw in raw_offsets:
        if isinstance(raw, bool):
            raise PromptCatalogError("frame_offsets_ms 只能包含整数。")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise PromptCatalogError("frame_offsets_ms 只能包含整数。")
        if not MIN_FRAME_OFFSET_MS <= offset <= MAX_FRAME_OFFSET_MS:
            raise PromptCatalogError(
                f"Camera 帧偏移必须在 {MIN_FRAME_OFFSET_MS}..{MAX_FRAME_OFFSET_MS} ms。"
            )
        offsets.append(offset)
    if offsets != sorted(set(offsets)):
        raise PromptCatalogError("frame_offsets_ms 必须严格递增且不能重复。")
    if 0 not in offsets:
        raise PromptCatalogError("Camera 帧偏移必须包含触发时刻 0 ms。")

    use_ra_event = value.get("use_ra_event", base["use_ra_event"])
    use_ra_options = value.get("use_ra_options", base["use_ra_options"])
    if type(use_ra_event) is not bool or type(use_ra_options) is not bool:
        raise PromptCatalogError("RA Events / RA Options 开关必须是布尔值。")
    if use_ra_options and not use_ra_event:
        raise PromptCatalogError("启用 RA/SWAG Options 时必须同时启用 RA Events。")

    matching_profile = next(
        (
            item["id"]
            for item in INPUT_PRESETS
            if list(item["frame_offsets_ms"]) == offsets
            and item["use_ra_event"] is use_ra_event
            and item["use_ra_options"] is use_ra_options
        ),
        "custom",
    )
    return {
        "profile_id": matching_profile,
        "frame_offsets_ms": offsets,
        "use_ra_event": use_ra_event,
        "use_ra_options": use_ra_options,
        "use_trajectory_summary": False,
        "use_ares_capture": False,
        "use_bev_animation": False,
    }
