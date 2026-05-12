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

Long-running commands print progress to stderr using wide terminal-width separators, a task title, `step: current/total`, and `tasks_remaining: N`. Remote export streams raw stdout/stderr live while the SSH command is running, and still emits a heartbeat every 30 seconds if no log line is produced. The default Luban Python command includes `conda run --no-capture-output` so export logs are not buffered by conda. JSON output remains on stdout when `--json` is used.

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
- `ifx`: push ONNX through `truck.py`, trigger the Jenkins IFX job, and collect fileserver versions by label.
- `handoff`: generate `handoff_manifest_snippet.txt` and `handoff_commands.sh`.
- `release`: run `export -> ifx -> handoff`. If `--epoch` is provided, model picking is skipped.
- `resume`: continue from the last incomplete stage in `release_record.json`.
- `offboard`: create a temporary offboard test yaml on Luban and run the configured test entrypoint.

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
