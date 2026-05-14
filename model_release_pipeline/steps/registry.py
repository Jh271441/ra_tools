"""Registry for the seven-step release pipeline."""

from __future__ import annotations

from model_release_pipeline.pipeline_steps import MAIN_PIPELINE_STEPS, PipelineStep


STEP_COMMANDS = {
    "inspect": "inspect",
    "pick": "pick",
    "export": "export",
    "upload": "upload",
    "ifx": "ifx-convert",
    "handoff": "apply-handoff",
    "dcl": "dcl",
}


def main_steps() -> list[PipelineStep]:
    return list(MAIN_PIPELINE_STEPS)


def command_for_step(step_key: str) -> str:
    try:
        return STEP_COMMANDS[step_key]
    except KeyError as exc:
        raise ValueError(f"Unknown release pipeline step: {step_key}") from exc


def step_keys() -> list[str]:
    return [step.key for step in MAIN_PIPELINE_STEPS]
