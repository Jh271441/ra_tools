"""Generate handoff artifacts for Voyager/Kunpeng steps."""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from model_release_pipeline.config import BranchConfig, IfxConfig, VoyagerConfig


APPLY_COMMIT_MARKER = "MODEL_RELEASE_APPLY_COMMIT="


def extract_apply_commit(stdout: str) -> str:
    """Return the commit created by apply-handoff stdout, including legacy logs."""
    marker_matches = re.findall(
        rf"^{re.escape(APPLY_COMMIT_MARKER)}([0-9a-f]{{7,40}})$",
        stdout or "",
        flags=re.MULTILINE,
    )
    if marker_matches:
        return marker_matches[-1]

    legacy_matches = re.findall(
        r"^\[[^\]\s]+\s+([0-9a-f]{7,40})\]\s+V\d+\.",
        stdout or "",
        flags=re.MULTILINE,
    )
    return legacy_matches[-1] if legacy_matches else ""


class VoyagerHandoffService:
    """Renders manifest snippets and shell commands for downstream steps."""

    def __init__(
        self,
        config: VoyagerConfig,
        command_runner: Optional[
            Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
        ] = None,
    ) -> None:
        self.config = config
        self.command_runner = command_runner or self._run_command

    @staticmethod
    def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(command),
            check=False,
            text=True,
            capture_output=True,
        )

    def _render_manifest_lines(
        self,
        ifx_mapping: Dict[str, Dict[str, Any]],
        manifest_entries: Optional[List[Any]] = None,
    ) -> List[str]:
        lines = []
        for entry in (manifest_entries or self.config.manifest_entries):
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
            diff_ids = branch.effective_diff_ids()
            dcl_lines = [f"dcl diff -n -u {did}" for did in diff_ids]
            commands.extend(
                [
                    f"# [{branch.name}]",
                    f"git checkout {branch.checkout_branch}",
                    f"# Replace the relevant scenario dnn lines in {self.config.manifest_path}",
                    "git add onboard/model_files/MANIFEST.txt",
                    f'git commit -m "{commit_message}"',
                    "dcl lint",
                    *dcl_lines,
                    f"# Sim plan: {branch.sim_plan}",
                    "",
                ]
            )
        return commands

    def _branch_by_name_or_checkout(self, branch_value: Optional[str]) -> BranchConfig:
        branches = self.config.branches
        if not branches:
            raise RuntimeError("No Voyager branches configured.")
        if not branch_value:
            return branches[0]
        for branch in branches:
            if branch_value in {branch.name, branch.checkout_branch}:
                return branch
        known = ", ".join(
            f"{branch.name}={branch.checkout_branch}" for branch in branches
        )
        raise RuntimeError(f"Unknown branch '{branch_value}'. Known branches: {known}")

    def _render_commit_message(
        self,
        onnx_version: Any,
        description: str,
        experiment_name: str,
        selected_epoch: Any,
    ) -> str:
        version_text = onnx_version if onnx_version is not None else "<onnx_version>"
        return (
            f"{self.config.commit_prefix}{version_text}. "
            f"{experiment_name}, epoch={selected_epoch}. {description}"
        ).strip()

    def _docker_container(self, ifx_config: IfxConfig, container: str = "") -> str:
        return container or ifx_config.truck_docker_container or os.environ.get(
            ifx_config.truck_docker_container_env, ""
        )

    def _return_branch_trap(self, cleanup_branch: str = "") -> str:
        branch = self.config.return_branch
        cleanup = f"echo '[cleanup] return to {branch}'; git checkout {shlex.quote(branch)} || true"
        if cleanup_branch:
            cleanup += (
                f"; git branch -D {shlex.quote(cleanup_branch)} "
                ">/dev/null 2>&1 || true"
            )
        return f"trap {shlex.quote(cleanup)} EXIT"

    def _apply_script(self) -> str:
        return r"""
import base64
import json
from pathlib import Path
import re
import sys

payload = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
manifest_path = Path(payload["manifest_path"])
manifest_lines = payload["manifest_lines"]
allow_append = payload["allow_append"]
dry_run = payload["dry_run"]
if not manifest_path.exists():
    raise SystemExit(f"MANIFEST not found: {manifest_path}")

replacement_by_target = {}
for line in manifest_lines:
    if line.lstrip().startswith("#"):
        continue
    parts = line.split(maxsplit=4)
    if len(parts) < 4:
        raise SystemExit(f"Invalid manifest replacement line: {line}")
    replacement_by_target[parts[3]] = {
        "module": parts[0],
        "name": parts[1],
        "version": parts[2],
        "target": parts[3],
        "description": parts[4] if len(parts) > 4 else "",
        "line": line,
    }

def render_replacement(old_line, replacement):
    match = re.match(r"^(\s*)(\S+)(\s+)(\S+)(\s+)(\S+)(\s+)(\S+)(.*)$", old_line)
    if not match:
        return replacement["line"]
    (
        prefix,
        _old_module,
        sep_module_name,
        _old_name,
        sep_name_version,
        _old_version,
        sep_version_target,
        _old_target,
        old_rest,
    ) = match.groups()
    description = replacement["description"]
    if description:
        rest_space = re.match(r"^\s*", old_rest).group(0)
        if not rest_space:
            rest_space = sep_version_target
        rest = f"{rest_space}{description}"
    else:
        rest = ""
    candidate = (
        f"{prefix}{replacement['module']}{sep_module_name}"
        f"{replacement['name']}{sep_name_version}"
        f"{replacement['version']}{sep_version_target}"
        f"{replacement['target']}{rest}"
    )
    old_parts = old_line.split(maxsplit=4)
    old_desc = old_parts[4] if len(old_parts) > 4 else ""
    if (
        len(old_parts) >= 4
        and old_parts[0] == replacement["module"]
        and old_parts[1] == replacement["name"]
        and old_parts[2] == replacement["version"]
        and old_parts[3] == replacement["target"]
        and old_desc == description
    ):
        return old_line
    return candidate

lines = manifest_path.read_text(encoding="utf-8").splitlines()
seen = set()
rewritten = []
for old_line in lines:
    stripped = old_line.strip()
    if stripped and not stripped.startswith("#"):
        parts = stripped.split()
        if len(parts) >= 4 and parts[0] == "planner.model-files":
            target = parts[3]
            if target in replacement_by_target:
                rewritten.append(render_replacement(old_line, replacement_by_target[target]))
                seen.add(target)
                continue
    rewritten.append(old_line)

missing = [
    target for target in replacement_by_target
    if target not in seen
]
if missing and not allow_append:
    raise SystemExit(
        "Missing MANIFEST target(s), not appending by default: "
        + ", ".join(missing)
    )
if missing:
    rewritten.append("")
    rewritten.append("# Added by model_release_pipeline apply-handoff")
    for target in missing:
        rewritten.append(replacement_by_target[target]["line"])

new_text = "\n".join(rewritten) + "\n"
old_text = manifest_path.read_text(encoding="utf-8")
if new_text == old_text:
    print(f"No MANIFEST changes needed: {manifest_path}")
elif dry_run:
    import difflib
    print(f"Would update MANIFEST: {manifest_path}")
    print("".join(difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=str(manifest_path),
        tofile=str(manifest_path) + ".new",
    )))
else:
    manifest_path.write_text(new_text, encoding="utf-8")
    print(f"Updated MANIFEST: {manifest_path}")
"""

    def _docker_apply_command(
        self,
        ifx_config: IfxConfig,
        container: str,
        branch: BranchConfig,
        manifest_lines: List[str],
        commit_message: str,
        dry_run: bool,
        no_commit: bool,
        allow_dirty: bool,
        allow_append: bool,
    ) -> List[str]:
        payload = {
            "manifest_path": self.config.manifest_path,
            "manifest_lines": manifest_lines,
            "allow_append": allow_append,
            "dry_run": dry_run,
        }
        payload_b64 = base64.b64encode(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        script = self._apply_script()
        shell_parts = [
            f"cd {shlex.quote(ifx_config.truck_docker_workdir)}",
            self._return_branch_trap(),
        ]
        if ifx_config.truck_docker_setup:
            shell_parts.append(f"{ifx_config.truck_docker_setup} >/tmp/model_release_handoff_setup.log 2>&1 || true")
        shell_parts.extend(
            [
                "set -e",
            ]
        )
        if not allow_dirty:
            shell_parts.append(
                "test -z \"$(git status --porcelain)\" || "
                "(echo 'Voyager worktree is dirty; commit/stash it or pass --allow-dirty.' >&2; git status --short >&2; exit 2)"
            )
        shell_parts.append(f"git checkout {shlex.quote(branch.checkout_branch)}")
        if not allow_dirty:
            shell_parts.append(
                "test -z \"$(git status --porcelain)\" || "
                "(echo 'Voyager worktree is dirty after checkout.' >&2; git status --short >&2; exit 2)"
            )
        shell_parts.append(
            f"python3 -c {shlex.quote(script)} {shlex.quote(payload_b64)}"
        )
        if not dry_run:
            shell_parts.append(
                f"git diff -- {shlex.quote(self.config.manifest_path)}"
            )
        if dry_run:
            shell_parts.append("echo '[dry-run] skip git add/commit'")
        elif no_commit:
            shell_parts.append("echo '[no-commit] MANIFEST updated; skip git add/commit'")
        else:
            shell_parts.extend(
                [
                    f"git add {shlex.quote(self.config.manifest_path)}",
                    "if git diff --cached --quiet; then echo 'No staged changes; skip commit'; "
                    f"else git commit -m {shlex.quote(commit_message)}; "
                    f"echo {APPLY_COMMIT_MARKER}$(git rev-parse HEAD); fi",
                ]
            )
        return [
            "docker",
            "exec",
            container,
            ifx_config.truck_docker_shell,
            "-lc",
            "; ".join(shell_parts),
        ]

    def _docker_dcl_command(
        self,
        ifx_config: IfxConfig,
        container: str,
        branch: BranchConfig,
        lint: bool,
        allow_dirty: bool,
        dry_run: bool,
        source_commit: str = "",
        temp_branch: str = "",
    ) -> List[str]:
        checkout_target = ""
        if source_commit:
            checkout_target = temp_branch or f"model_release_dcl_{source_commit[:12]}"
        shell_parts = [
            f"cd {shlex.quote(ifx_config.truck_docker_workdir)}",
            self._return_branch_trap(checkout_target),
        ]
        if ifx_config.truck_docker_setup:
            shell_parts.append(
                f"{ifx_config.truck_docker_setup} >/tmp/model_release_dcl_setup.log 2>&1 || true"
            )
        shell_parts.append("set -e")
        if not allow_dirty:
            shell_parts.append(
                "test -z \"$(git status --porcelain)\" || "
                "(echo 'Voyager worktree is dirty; commit/stash it or pass --allow-dirty.' >&2; git status --short >&2; exit 2)"
            )
        if source_commit:
            shell_parts.append(
                "git switch -C "
                f"{shlex.quote(checkout_target)} {shlex.quote(source_commit)}"
            )
        else:
            shell_parts.append(f"git checkout {shlex.quote(branch.checkout_branch)}")
        if not allow_dirty:
            shell_parts.append(
                "test -z \"$(git status --porcelain)\" || "
                "(echo 'Voyager worktree is dirty after checkout.' >&2; git status --short >&2; exit 2)"
            )
        diff_ids = branch.effective_diff_ids()
        if dry_run:
            for did in diff_ids:
                shell_parts.append(f"echo '[dry-run] dcl diff -n -u {did} --nolint'")
        else:
            if lint:
                shell_parts.append("dcl lint")
                for did in diff_ids:
                    shell_parts.append(f"dcl diff -n -u {did}")
            else:
                for did in diff_ids:
                    shell_parts.append(f"dcl diff -n -u {did} --nolint")
        return [
            "docker",
            "exec",
            container,
            ifx_config.truck_docker_shell,
            "-lc",
            "; ".join(shell_parts),
        ]

    def apply_to_docker(
        self,
        ifx_config: IfxConfig,
        ifx_mapping: Dict[str, Dict[str, Any]],
        description: str,
        experiment_name: str,
        selected_epoch: Any,
        branch: Optional[str] = None,
        container: str = "",
        dry_run: bool = False,
        no_commit: bool = False,
        allow_dirty: bool = False,
        allow_append: bool = False,
    ) -> Dict[str, Any]:
        """Apply MANIFEST replacements inside a Voyager docker checkout."""
        chosen_branch = self._branch_by_name_or_checkout(branch)
        docker_container = self._docker_container(ifx_config, container)
        if not docker_container:
            raise RuntimeError(
                "apply-handoff docker mode requires a container. Set "
                f"{ifx_config.truck_docker_container_env} or pass --docker."
            )
        branch_entries = chosen_branch.manifest_entries or None
        manifest_lines = self._render_manifest_lines(ifx_mapping, branch_entries)
        commit_message = self._render_commit_message(
            onnx_version=ifx_mapping.get("onnx", {}).get("version"),
            description=description,
            experiment_name=experiment_name,
            selected_epoch=selected_epoch,
        )
        command = self._docker_apply_command(
            ifx_config=ifx_config,
            container=docker_container,
            branch=chosen_branch,
            manifest_lines=manifest_lines,
            commit_message=commit_message,
            dry_run=dry_run,
            no_commit=no_commit,
            allow_dirty=allow_dirty,
            allow_append=allow_append,
        )
        result = self.command_runner(command)
        dcl_commands = []
        for did in chosen_branch.effective_diff_ids():
            dcl_commands.append(f"dcl diff -n -u {did} --nolint")
            dcl_commands.append(f"# optional explicit lint: dcl lint && dcl diff -n -u {did}")
        return {
            "mode": "docker",
            "container": docker_container,
            "workdir": ifx_config.truck_docker_workdir,
            "branch": chosen_branch.name,
            "checkout_branch": chosen_branch.checkout_branch,
            "manifest_path": self.config.manifest_path,
            "commit_message": commit_message,
            "command": " ".join(shlex.quote(part) for part in command),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "dry_run": dry_run,
            "no_commit": no_commit,
            "commit": extract_apply_commit(result.stdout)
            if result.returncode == 0 and not dry_run and not no_commit
            else "",
            "dcl_commands": dcl_commands,
            "sim_plan": chosen_branch.sim_plan,
        }

    def dcl_to_docker(
        self,
        ifx_config: IfxConfig,
        branch: Optional[str] = None,
        container: str = "",
        dry_run: bool = False,
        lint: bool = False,
        allow_dirty: bool = False,
        source_commit: str = "",
        temp_branch: str = "",
    ) -> Dict[str, Any]:
        """Run DCL diff inside a Voyager docker checkout and return to base branch."""
        chosen_branch = self._branch_by_name_or_checkout(branch)
        docker_container = self._docker_container(ifx_config, container)
        if not docker_container:
            raise RuntimeError(
                "dcl docker mode requires a container. Set "
                f"{ifx_config.truck_docker_container_env} or pass --docker."
            )
        command = self._docker_dcl_command(
            ifx_config=ifx_config,
            container=docker_container,
            branch=chosen_branch,
            lint=lint,
            allow_dirty=allow_dirty,
            dry_run=dry_run,
            source_commit=source_commit,
            temp_branch=temp_branch,
        )
        result = self.command_runner(command)
        return {
            "mode": "docker",
            "container": docker_container,
            "workdir": ifx_config.truck_docker_workdir,
            "branch": chosen_branch.name,
            "checkout_branch": chosen_branch.checkout_branch,
            "source_commit": source_commit,
            "temp_branch": temp_branch,
            "update_diff_ids": chosen_branch.effective_diff_ids(),
            "command": " ".join(shlex.quote(part) for part in command),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "dry_run": dry_run,
            "lint": lint,
            "sim_plan": chosen_branch.sim_plan,
        }

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
