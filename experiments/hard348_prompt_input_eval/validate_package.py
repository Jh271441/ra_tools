#!/usr/bin/env python3
"""Run cheap safety checks for the committed prompt/input package."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RUNTIME_FILES = (
    ROOT / "compact_business_probe.py",
    ROOT / "compact_business_batch.py",
    ROOT / "project_role_observer_facts.py",
)


def _load_probe():
    spec = importlib.util.spec_from_file_location("hard348_eval_probe", RUNTIME_FILES[0])
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import compact_business_probe.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    required = (
        *RUNTIME_FILES,
        ROOT / "PROMPT_SPEC.md",
        ROOT / "README.md",
        ROOT / "MANIFEST.md",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing package files: {missing}")

    forbidden_runtime_fragments = (
        "/tmp/",
        "Authorization",
        "qwen38-27b-v33-lubannew",
    )
    for path in RUNTIME_FILES:
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
        for fragment in forbidden_runtime_fragments:
            if fragment in source:
                raise SystemExit(f"forbidden runtime fragment {fragment!r} in {path}")

    probe = _load_probe()
    facts = {"safe_observation": {"speed": 0.0}}
    reports = {"non_authoritative_business_report_ledger": "none"}
    probe._assert_model_safe(facts)
    probe._assert_model_safe(reports)
    try:
        probe._assert_raw_evidence_artifact(
            {
                "results": [
                    {
                        "issue_id": "sentinel",
                        "evidence": {"safe_observation": {"speed": 0.0}},
                    }
                ]
            }
        )
    except ValueError as exc:
        raise SystemExit(f"valid raw-artifact sentinel was rejected: {exc}") from exc
    try:
        probe._assert_raw_evidence_artifact(
            {
                "stats": {},
                "results": [
                    {
                        "issue_id": "sentinel",
                        "evidence": {"safe_observation": {"speed": 0.0}},
                    }
                ],
            }
        )
    except ValueError:
        pass
    else:
        raise SystemExit("derived artifact guard did not fail closed")
    for prompt_variant, report_mode in (
        ("causal_role_first_v1", "observation_v1"),
        ("causal_role_first_v2", "observation_v1"),
        ("causal_role_first_v3", "observation_v2"),
    ):
        prompt = probe._prompt(
            facts,
            reports,
            output_mode="short",
            prompt_variant=prompt_variant,
            visual_mode="paired10",
        )
        if "package-safety-sentinel" in prompt:
            raise SystemExit("sentinel leaked into prompt")
    with tempfile.TemporaryDirectory(prefix="hard348_image_layout_") as temp_dir:
        root = Path(temp_dir)
        direct = root / "cn_direct"
        direct.mkdir()
        (direct / "0.jpg").write_bytes(b"camera")
        (direct / "bev_0.jpg").write_bytes(b"bev")
        if probe._find_image_directory(root, "cn_direct") != direct.resolve():
            raise SystemExit("direct image layout resolver failed")
        wrapped = root / "cn_wrapped_frozen" / "after_compress"
        wrapped.mkdir(parents=True)
        (wrapped / "0.jpg").write_bytes(b"camera")
        (wrapped / "bev_0.jpg").write_bytes(b"bev")
        if probe._find_image_directory(root, "cn_wrapped") != wrapped.resolve():
            raise SystemExit("after_compress image layout resolver failed")
    try:
        probe._assert_model_safe({"label": "A"})
    except ValueError:
        pass
    else:
        raise SystemExit("label safety guard did not fail closed")

    print(f"validated {len(RUNTIME_FILES)} runtime files and prompt safety")


if __name__ == "__main__":
    main()
