"""Shared release pipeline step definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineStep:
    key: str
    title: str
    description: str
    group: str = "onboard"  # "shared" | "onboard" | "offboard"


SHARED_STEPS = [
    PipelineStep("pick", "Pick", "Inspect experiment and recommend epoch from metrics", group="shared"),
]

ONBOARD_STEPS = [
    PipelineStep("branch_prep", "Branch Prep", "Checkout release branch and create working branch", group="onboard"),
    PipelineStep("dcl_patch",   "DCL Patch",   "Apply a DCL patch revision in Voyager docker",     group="onboard"),
    PipelineStep("export",  "Export",      "Export and copy ONNX from Luban",               group="onboard"),
    PipelineStep("upload",  "Upload",      "Upload ONNX with truck.py",                     group="onboard"),
    PipelineStep("ifx",     "IFX Convert", "Trigger Jenkins and collect IFX versions",       group="onboard"),
    PipelineStep("handoff", "Handoff",     "Generate or apply Voyager MANIFEST updates",     group="onboard"),
    PipelineStep("dcl",     "DCL",         "Update review diffs manually",                   group="onboard"),
    PipelineStep("sim_plan", "Sim Plan",   "Trigger or manage Kunpeng SimOne plans",          group="onboard"),
]

OFFBOARD_STEP = PipelineStep(
    "offboard",
    "Offboard",
    "Run release checkpoint validation",
    group="offboard",
)

# inspect+pick are shared; onboard is the deploy path (steps 1-7);
# offboard is independent validation available after pick.
MAIN_PIPELINE_STEPS = [*SHARED_STEPS, *ONBOARD_STEPS]
WEB_PIPELINE_STEPS = [*MAIN_PIPELINE_STEPS, OFFBOARD_STEP]
