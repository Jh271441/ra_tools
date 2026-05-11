"""Generate handoff artifacts for Voyager/Kunpeng steps."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from model_release_pipeline.config import VoyagerConfig


class VoyagerHandoffService:
    """Renders manifest snippets and shell commands for downstream steps."""

    def __init__(self, config: VoyagerConfig) -> None:
        self.config = config

    def _render_manifest_lines(
        self, ifx_mapping: Dict[str, Dict[str, Any]]
    ) -> List[str]:
        lines = []
        for entry in self.config.manifest_entries:
            file_info = ifx_mapping.get(entry.platform)
            if not file_info:
                lines.append(
                    f"# Missing platform {entry.platform}: "
                    f"expected target {entry.target_path}"
                )
                continue
            description = f" {entry.description}" if entry.description else ""
            lines.append(
                f"planner.model-files {file_info['name']} {file_info['version']} "
                f"{entry.target_path}{description}"
            )
        return lines

    def _render_branch_commands(
        self,
        onnx_version: Any,
        description: str,
        experiment_name: str,
        selected_epoch: Any,
    ) -> List[str]:
        version_text = onnx_version if onnx_version is not None else "<onnx_version>"
        commit_message = (
            f"{self.config.commit_prefix}{version_text}. "
            f"{experiment_name}, epoch={selected_epoch}. {description}"
        ).strip()
        commands: List[str] = [
            "# Generated handoff commands.",
            f"# MANIFEST target: {self.config.manifest_path}",
            "",
        ]
        for branch in self.config.branches:
            commands.extend(
                [
                    f"# [{branch.name}]",
                    f"git checkout {branch.checkout_branch}",
                    f"# Replace the relevant scenario dnn lines in {self.config.manifest_path}",
                    "git add onboard/model_files/MANIFEST.txt",
                    f'git commit -m "{commit_message}"',
                    "dcl lint",
                    f"dcl diff -n -u {branch.update_diff_id}",
                    f"# Sim plan: {branch.sim_plan}",
                    "",
                ]
            )
        return commands

    def generate(
        self,
        run_dir: Path,
        ifx_mapping: Dict[str, Dict[str, Any]],
        description: str,
        experiment_name: str,
        selected_epoch: Any,
    ) -> Dict[str, str]:
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest_lines = self._render_manifest_lines(ifx_mapping)
        onnx_version = ifx_mapping.get("onnx", {}).get("version")
        commands = self._render_branch_commands(
            onnx_version=onnx_version,
            description=description,
            experiment_name=experiment_name,
            selected_epoch=selected_epoch,
        )
        manifest_path = run_dir / "handoff_manifest_snippet.txt"
        commands_path = run_dir / "handoff_commands.sh"
        summary_path = run_dir / "handoff_summary.txt"
        manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
        commands_path.write_text("\n".join(commands) + "\n", encoding="utf-8")
        summary_path.write_text(
            "\n".join(
                [
                    f"experiment: {experiment_name}",
                    f"selected_epoch: {selected_epoch}",
                    f"onnx_version: {onnx_version}",
                    f"manifest_snippet: {manifest_path}",
                    f"commands: {commands_path}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "manifest_snippet": str(manifest_path),
            "commands_file": str(commands_path),
            "summary_file": str(summary_path),
        }
