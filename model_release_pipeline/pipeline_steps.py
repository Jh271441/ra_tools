"""Shared release pipeline step definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineStep:
    key: str
    title: str
    description: str


MAIN_PIPELINE_STEPS = [
    PipelineStep("inspect", "Inspect", "Inspect experiment metadata and checkpoints"),
    PipelineStep("pick", "Pick", "Recommend epoch from log/TensorBoard metrics"),
    PipelineStep("export", "Export", "Export and copy ONNX from Luban"),
    PipelineStep("upload", "Upload", "Upload ONNX with truck.py"),
    PipelineStep("ifx", "IFX Convert", "Trigger Jenkins and collect IFX versions"),
    PipelineStep("handoff", "Handoff", "Generate or apply Voyager MANIFEST updates"),
    PipelineStep("dcl", "DCL", "Update review diffs manually"),
]


OFFBOARD_STEP = PipelineStep(
    "offboard",
    "Offboard",
    "Run release checkpoint validation",
)


# The core release path is 1-7. Web still exposes offboard next to the release
# path as an independent validation branch.
WEB_PIPELINE_STEPS = [*MAIN_PIPELINE_STEPS, OFFBOARD_STEP]
