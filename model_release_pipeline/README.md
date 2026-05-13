# model_release_pipeline

Scenario DNN release tooling for model pick, ONNX export, IFX conversion, and Voyager handoff.

The tool runs from the normal local machine by default. It does not require the current shell to be inside the Voyager docker environment; Voyager/Kunpeng operations are generated as handoff files.

## Quick Start

```bash
cd ~/workspace/ra_tools
python -m model_release_pipeline.cli inspect --experiment <experiment_path>
python -m model_release_pipeline.cli export --experiment <experiment_path> --epoch <epoch> --dry-run
python -m model_release_pipeline.cli release --experiment <experiment_path> --epoch <epoch> --desc "release note" --dry-run
```

For experiments that only exist on Luban/OFS, keep the command on your local machine and add `--remote`:

```bash
python -m model_release_pipeline.cli inspect --remote luban_2_card --experiment /nfs/.../experiment
python -m model_release_pipeline.cli export --remote luban_2_card --experiment /nfs/.../experiment --epoch <epoch> --dry-run
python -m model_release_pipeline.cli release --remote luban_2_card --experiment /nfs/.../experiment --epoch <epoch> --desc "release note" --dry-run
```

For multi-head experiments, `pick` reads `activated_tasks` from `hparams.yaml`, writes separate recommendations under `per_task`, and also emits a combined checkpoint recommendation at top-level `recommended_epoch` when enough metrics are available. The combined recommendation prefers the primary head `stuck_detect` and is precision-oriented.

```bash
python -m model_release_pipeline.cli pick --remote luban_2_card --experiment /nfs/.../experiment --top-n 3
python -m model_release_pipeline.cli export --remote luban_2_card --experiment /nfs/.../experiment --dry-run
python -m model_release_pipeline.cli release --remote luban_2_card --experiment /nfs/.../experiment --desc "release note" --dry-run
```

By default, `pick` prints a compact report similar to the legacy pick scripts: per-task Top-N by `roc_auc`, `pr_auc`, precision/recall, selected combined epochs, and the final `Recommended epoch`. Use `--json` only when you need the full machine-readable payload.

`inspect`, `export`, `release`, `resume`, `ifx`, `handoff`, and `offboard` also default to a compact human-readable summary. Use `--json` only for debugging or automation that needs the full `release_record.json` payload.

Long-running commands print progress to stderr using wide terminal-width separators, a task title, `step: current/total`, and `tasks_remaining: N`. Standalone commands use their own step count, while `release` uses a combined 9-step flow: inspect, remote export, scp, select truck runner, upload ONNX, prepare precision test, trigger Jenkins IFX, poll IFX artifacts, handoff. Remote export streams raw stdout/stderr live while the SSH command is running, and still emits a heartbeat every 30 seconds if no log line is produced. IFX conversion also reports Jenkins queue wait, assigned build URL, build running status, console download, parsed platforms, missing platforms, and failed uploads during the `Poll IFX Artifacts` step. The default Luban Python command includes `conda run --no-capture-output` so export logs are not buffered by conda. JSON output remains on stdout when `--json` is used.

The IFX stage needs `truck.py`. `ifx.truck_runner` controls where it runs:

- `auto`: try local `truck.py`, then Voyager docker, then SSH.
- `docker`: run `truck.py` via `docker exec`; configure `truck_docker_container` or export `CONTAINER_NAME_GEN4`, plus `truck_docker_workdir` and `truck_docker_setup`.
- `ssh`: run `truck.py` after SSH to a cloud server; configure `truck_ssh_host`, `truck_ssh_workdir` such as `~/workspace/voyager` or `~/workspace/voyager2`, and `truck_ssh_setup`.

When `truck.py` runs in docker or SSH, local ONNX/precision-test files are staged into the configured `/tmp/model_release_pipeline_artifacts` directory before upload.

### IFX Truck Runner Use Cases

Use `local` when the current shell is already inside a Voyager environment and `truck.py --help` works directly:

```yaml
ifx:
  truck_runner: local
  truck_local_shell: /bin/zsh
  truck_local_workdir: /home/didi/workspace/voyager
  truck_local_setup: source /home/didi/workspace/voyager/bazel/scripts/setup.sh
```

Use `docker` when the current shell is the local `assist_stuck` conda environment, while `truck.py` only exists inside a local Voyager docker:

```yaml
ifx:
  truck_runner: docker
  truck_docker_container: <container_name>
  truck_docker_shell: /bin/zsh
  truck_docker_workdir: /home/didi/workspace/voyager
  truck_docker_setup: git checkout master-Release_CN-a6d66b30c89 && source /home/didi/workspace/voyager/bazel/scripts/setup.sh
```

You can also leave `truck_docker_container` empty and export:

```bash
export CONTAINER_NAME_GEN4=<container_name>
```

Use `ssh` when `truck.py` is available on a cloud/server machine after SSH, without local docker. Pick the correct Voyager root on that machine:

```yaml
ifx:
  truck_runner: ssh
  truck_ssh_host: cloud_server
  truck_ssh_shell: /bin/zsh
  truck_ssh_workdir: /home/didi/workspace/voyager2
  truck_ssh_setup: source /home/didi/workspace/voyager2/bazel/scripts/setup.sh
```

Use `auto` for the common mixed setup. It tries local first, then docker, then SSH if configured:

```yaml
ifx:
  truck_runner: auto
```

The ONNX upload description passed to `truck.py push --desc` is generated from the experiment and selected epoch. Passing `--desc` appends release-specific notes:

```bash
python -m model_release_pipeline.cli ifx \
  --run-id <release_id> \
  --desc "loss_min, alpha=0.75, top4 + randn4, old data"
```

This produces a truck description like:

```text
<experiment_name>, epoch=007, loss_min, alpha=0.75, top4 + randn4, old data.
```

The upload and IFX conversion can be run separately:

```bash
python -m model_release_pipeline.cli upload \
  --run-id <release_id> \
  --onnx-version 64 \
  --desc "loss_min, alpha=0.75, top4 + randn4, old data"

python -m model_release_pipeline.cli ifx-convert \
  --run-id <release_id>
```

`upload` stores `ifx.onnx`, `ifx.precision_test_arg`, `ifx.truck_runner`, and `ifx.upload_description` in the run record. `ifx-convert` reuses those fields to trigger Jenkins, records the Jenkins queue/build URL, and parses the Jenkins console output for generated IFX artifact versions. The existing `ifx` command remains a shortcut that runs both commands in sequence.

Jenkins IFX triggering uses `POST` by default because some Jenkins deployments reject `GET /buildWithParameters` with HTTP 405. The default token is the same `ONNX2IFX_DEV` token used by the existing Voyager IFX trigger scripts. For Jenkins instances with CSRF protection, the tool fetches `/crumbIssuer/api/json` and sends the returned crumb header before triggering the job. Override `ifx.jenkins_http_method`, `ifx.jenkins_token`, or `ifx.jenkins_use_crumb` only if your Jenkins job explicitly requires different values.

By default the IFX trigger matches the legacy flow: `max_batch=0` and no fileserver label is passed to Jenkins. The run is tracked by Jenkins queue/build URL instead of an injected label. If any expected platform, including `fp16_thor`, is missing or appears as `upload failed` in the Jenkins console, the conversion is treated as failed even if Jenkins itself reports `SUCCESS`.

A release run is expected to bind to exactly one ONNX fileserver version. Re-running `upload` after a successful upload is blocked by default; run `ifx-convert` next. If you intentionally need to replace the binding, pass `--replace-upload` and an explicit `--onnx-version`.

After `truck.py push`, `upload` verifies the requested ONNX version with `truck.py list`. If the version is not visible, the upload fails instead of writing a misleading version into `release_record.json`.

If `truck.py` reports `code: 60` / `The file is already exist` with the same md5, the fileserver is deduplicating by file content/name and will not create a new version for the same ONNX. Reuse the existing version shown in the error, or change the fileserver filename if a distinct version is required.

## Apply Voyager Handoff

`handoff` only generates files. To apply the MANIFEST change and create a commit inside the Voyager docker checkout, use `apply-handoff`:

```bash
python -m model_release_pipeline.cli apply-handoff \
  --run-id <release_id> \
  --branch gen4_release_20260327 \
  --docker "$CONTAINER_NAME_GEN4" \
  --dry-run

python -m model_release_pipeline.cli apply-handoff \
  --run-id <release_id> \
  --branch gen4_release_20260327 \
  --docker "$CONTAINER_NAME_GEN4"
```

The command runs in docker, checks out the configured branch, replaces the configured Scenario DNN lines in `onboard/model_files/MANIFEST.txt`, prints the diff, and creates a local git commit. It refuses to run on a dirty Voyager worktree unless `--allow-dirty` is provided. Use `--no-commit` if you want the file edit but not the commit.

If `--branch` is omitted, `apply-handoff` loops over every configured `voyager.branches` entry in order and creates one local commit per branch. Pass `--branch <name>` to restrict the operation to a single branch.

`dcl` is intentionally not executed automatically. After `apply-handoff` succeeds, the default follow-up is no-lint diff update:

```bash
dcl diff -n -u <update_diff_id> --nolint
```

Run `dcl lint` only when explicitly needed.

To use an explicit fileserver version for the ONNX upload, pass `--onnx-version` (`--version` is kept as an alias):

```bash
python -m model_release_pipeline.cli ifx \
  --run-id <release_id> \
  --onnx-version 64 \
  --desc "loss_min, alpha=0.75, top4 + randn4, old data"
```

This maps to:

```bash
truck.py push planner.model-files <onnx_path> -v 64 --desc "<generated description>"
```

If you accidentally uploaded a bad version, prefer using a new fileserver version or a new filename. The fileserver delete path is currently deprecated in common `truck.py` deployments:

```bash
truck.py delete planner.model-files vectorized_scenario_remote_assist_model.onnx 65 -f
```

The raw fileserver delete API usually requires internal auth/signing and is easier to misuse. Treat deletion as unavailable unless the current `truck.py delete` command succeeds in your configured truck runner environment.

If the training log is incomplete, the report also prints a `TensorBoard Val-Loss Tolerance Fallback` section. In that case the final `Recommended epoch` comes from the primary head's TensorBoard validation-loss fallback, not from the incomplete log ranking. The default tolerance is 5%, meaning epochs with `val_loss <= min_val_loss * 1.05` are considered and the highest-precision epoch in that band is selected.

If you intentionally want to use one head's standalone recommendation instead of the combined recommendation, pass `--task`. If you have already decided an epoch manually, pass `--epoch`.

```bash
python -m model_release_pipeline.cli export --remote luban_2_card --experiment /nfs/.../experiment --task stuck_detect --dry-run
python -m model_release_pipeline.cli export --remote luban_2_card --experiment /nfs/.../experiment --epoch 5 --dry-run
python -m model_release_pipeline.cli pick --remote luban_2_card --experiment /nfs/.../experiment --loss-tolerance-pct 0.10
```

## Manual Epoch Flow

Model selection is intentionally optional. If you already have a chosen checkpoint, pass `--epoch` to `export` or `release`; the tool will skip `ModelPicker` entirely and move directly to export/IFX/handoff.

```bash
EXP=/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/ego_stuck_data/scenario_dnn_26q1/<experiment>

python -m model_release_pipeline.cli export \
  --remote luban_2_card \
  --experiment "$EXP" \
  --epoch 5 \
  --dry-run

python -m model_release_pipeline.cli release \
  --remote luban_2_card \
  --experiment "$EXP" \
  --epoch 5 \
  --desc "scenario dnn release" \
  --dry-run
```

Use `--dry-run` first. Removing `--dry-run` allows the tool to create the temporary remote hparams file, export ONNX on Luban, run IFX conversion, and generate the Voyager handoff files.

The remote export command runs from `stuck_assist_model`, sets `PYTHONPATH` to that repo root, and then invokes the configured export script. This is required because `scenario_dnn/export/export_scenario_dnn.py` imports top-level modules such as `utils.random_util`.

If the remote host needs a specific conda environment, set it in config or override it per command:

```bash
python -m model_release_pipeline.cli inspect --remote luban_2_card --remote-python "/home/luban/miniconda3/bin/conda run --no-capture-output -n scen_dnn python" --experiment /nfs/.../experiment
```

Copy the editable config template:

```bash
python -m model_release_pipeline.cli print-config --copy
```

## Commands

- `inspect`: discover checkpoints, logs, hparams, TensorBoard files, and existing exports.
- `pick`: rank candidate epochs from `train_scenario_dnn.log`; TensorBoard is used if installed.
- `export`: ssh to Luban, create a temporary hparams yaml, export ONNX, and scp it back to the run directory. If `--epoch` is provided, model picking is skipped.
- `upload`: push ONNX through `truck.py` and prepare the precision-test truck argument.
- `ifx-convert`: trigger the Jenkins IFX job from a previous `upload` and collect fileserver versions from the Jenkins build/console output.
- `ifx`: shortcut for `upload -> ifx-convert`.
- `handoff`: generate `handoff_manifest_snippet.txt` and `handoff_commands.sh`.
- `apply-handoff`: apply the MANIFEST replacement in Voyager docker and create a local git commit. `dcl` remains manual/confirmed.
- `release`: run `export -> ifx -> handoff`. If `--epoch` is provided, model picking is skipped.
- `resume`: continue from the last incomplete stage in `release_record.json`.
- `offboard`: create a temporary offboard test yaml on Luban and run the configured test entrypoint.
- `web`: start a read-only browser console for existing release records.

## Web Console

Start the local read-only release agent console:

```bash
python -m model_release_pipeline.cli web --host 127.0.0.1 --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

The first version is intentionally read-only. It scans `runs_dir`, lists release
runs, renders an agent-style timeline, summarizes epoch/ONNX/IFX/handoff/offboard
state, shows captured log tails, and prints the next CLI commands. Keep actual
mutating operations in the CLI until the web confirmation model is explicit.

Offboard can run from a release run or an explicit experiment epoch.
Prefer passing `--run-id`; it reads the experiment path and selected epoch from
the release record, then records the result as an `offboard` branch of the same
`release_record.json`. Repeated runs are appended to `offboard_branches`.
The command never edits
`configs/scenario_dnn_finetune_test.yaml` directly. It creates
`configs/scenario_dnn_finetune_test.release_offboard_<epoch>.yaml` on Luban,
rewrites only `load_partial_checkpoint`, streams the remote test log as-is, and runs:

```bash
python scenario_dnn/train_test/ra_model_pipeline.py \
  --config-yaml configs/scenario_dnn_finetune_test.release_offboard_epoch=019.yaml
```

Validate the selected checkpoint from a release run:

```bash
python -m model_release_pipeline.cli offboard \
  --run-id <release_id> \
  --remote luban_2_card
```

## Run State

Runs are stored under `runs_dir/<release_id>/release_record.json`. The default is `model_release_pipeline/.runs`, while the example config uses `~/.ra_tools_runs`.

## Environment Notes

- `truck.py` must be available for the `ifx` stage.
- The IFX precision test can be configured as either an existing truck arg or a local zip path.
- TensorBoard event parsing requires the optional `tensorboard` Python package. Without it, the picker falls back to log parsing.
- If both `log/version_*` and exported `log/epoch=*` directories exist, inspect prefers `version_*` as the training log directory.

## Picker Policy

The default `precision_first` policy is modeled after the historical `pick_model_util.py` and `pick_dual_haed_model_util.py` scripts:

- Single-head logs rank epochs that appear in the top window for `roc_auc`, `pr_auc`, and `precision`; ties are weighted toward precision.
- Multi-head logs build a combined epoch recommendation because export uses one checkpoint for all heads. The primary head is `stuck_detect`; its precision rank has the highest weight, followed by `pr_auc`, `roc_auc`, and recall guardrail. Secondary heads, including `stuck_detect_neg_no_assist`, are treated as delay-gate heads and are ranked by precision, `pr_auc`, and `roc_auc`.
- If task-scoped log metrics are missing or incomplete, TensorBoard validation scalars are used as fallback. The fallback reads only `val/` tags, finds the minimum validation loss, keeps every epoch within the configured relative loss tolerance, and recommends the highest-precision epoch in that loss band. Training loss tags are intentionally ignored because they usually keep decreasing and are not suitable for model selection. When `--remote` is used, TensorBoard is read on the remote `scen_dnn` Python only when the log fallback is needed, so normal log-based picks stay lightweight.
