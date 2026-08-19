#!/usr/bin/env python3
"""Run cheap safety checks for the committed prompt/input package."""

from __future__ import annotations

import importlib.util
import sys
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
    prompt = probe._prompt(
        facts,
        reports,
        output_mode="short",
        prompt_variant="causal_role_first_v1",
        visual_mode="paired10",
    )
    probe._assert_model_safe(facts)
    probe._assert_model_safe(reports)
    if "package-safety-sentinel" in prompt:
        raise SystemExit("sentinel leaked into prompt")
    try:
        probe._assert_model_safe({"label": "A"})
    except ValueError:
        pass
    else:
        raise SystemExit("label safety guard did not fail closed")

    print(f"validated {len(RUNTIME_FILES)} runtime files and prompt safety")


if __name__ == "__main__":
    main()
