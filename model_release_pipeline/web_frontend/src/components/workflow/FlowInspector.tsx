import { useState, useCallback } from 'react';
import type { ActionSpec, BranchInfo, GetRunResponse, StageConfig, StageKey, StageValues } from '../../types/api';
import type { FlowItem } from './flowItems';
import { startAction, patchRunStageConfig, patchStageDefaults } from '../../api/client';
import styles from './FlowInspector.module.css';

const DEFAULT_ROOT = 'device:/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/ego_stuck_data/scenario_dnn_26q1/';

function fmtEpoch(val: number | null | undefined): string {
  if (val == null) return '';
  return Number.isInteger(val) ? String(val).padStart(3, '0') : Number(val).toFixed(1);
}

// ─── Shared sub-components ───────────────────────────────────────────────────

function BranchSelect({ id, value, onChange, branches, allLabel = 'all configured branches' }: {
  id: string; value: string; onChange: (v: string) => void;
  branches: BranchInfo[]; allLabel?: string;
}) {
  return (
    <select id={id} className={styles.branchSelect} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{allLabel}</option>
      {branches.map((b) => <option key={b.name} value={b.name}>{b.name}</option>)}
    </select>
  );
}

function HelperText({ children }: { children: React.ReactNode }) {
  return <p className={styles.helperText}>{children}</p>;
}

// ─── Step forms ──────────────────────────────────────────────────────────────

function PickForm({ run, lubanHost, onLubanHostChange }: {
  run: GetRunResponse | null;
  lubanHost: string;
  onLubanHostChange: (h: string) => void;
}) {
  const expPath = run?.record.experiment_path ?? '';
  return (
    <div className={styles.form}>
      <div className={styles.experimentPicker} data-root={DEFAULT_ROOT}>
        <input id="pickExperiment" placeholder="experiment path" defaultValue={expPath} />
      </div>
      <div className={styles.row}>
        <input id="pickRemote" className={styles.lubanInput} placeholder="remote" value={lubanHost}
          onChange={(e) => onLubanHostChange(e.target.value)} />
        <input id="pickDesc" placeholder="description / release note" />
      </div>
      <div className={styles.row}>
        <button id="pickPreviewBtn" className={styles.actionBtn} type="button">Preview epoch ↗</button>
        <span id="pickPreviewResult" className={styles.helperText} />
      </div>
      <HelperText>Pick runs on Luban and creates a new release. Use Preview to check the recommendation without saving.</HelperText>
    </div>
  );
}

function ExportForm({ run, lubanHost, onLubanHostChange }: {
  run: GetRunResponse | null; lubanHost: string; onLubanHostChange: (h: string) => void;
}) {
  const expPath = run?.record.experiment_path ?? '';
  return (
    <div className={styles.form}>
      <div className={styles.experimentPicker}>
        <input id="exportExperiment" placeholder="experiment path" defaultValue={expPath} />
      </div>
      <div className={styles.row}>
        <input id="exportEpoch" placeholder="epoch, e.g. 007" />
        <input id="exportRemote" className={styles.lubanInput} placeholder="remote" value={lubanHost}
          onChange={(e) => onLubanHostChange(e.target.value)} />
      </div>
      <input id="exportDesc" placeholder="description / release note" />
      <HelperText>Real export confirmation text is <b>EXPORT</b>.</HelperText>
    </div>
  );
}

function UploadForm() {
  return (
    <div className={styles.form}>
      <div className={styles.row}>
        <input id="uploadVersion" placeholder="optional ONNX version, e.g. 67" />
        <label className={styles.inlineCheck}>
          <input id="uploadReplace" type="checkbox" />
          replace existing binding
        </label>
      </div>
      <input id="uploadDesc" placeholder="fileserver description / release note" />
      <HelperText>Real upload confirmation text is the current <b>release_id</b>.</HelperText>
    </div>
  );
}

function IfxForm({ run }: { run: GetRunResponse | null }) {
  const buildUrl = (run?.record.ifx?.jenkins?.build_url) ?? '';
  return (
    <div className={styles.form}>
      <input id="ifxBuildUrl" placeholder="optional Jenkins build URL" defaultValue={buildUrl} />
      <HelperText>Use this when the saved Jenkins queue item has expired but the build URL is known.</HelperText>
    </div>
  );
}

function HandoffForm({ branches, stageConfig }: { branches: BranchInfo[]; stageConfig: StageValues }) {
  const [branch, setBranch] = useState(stageConfig.branch ?? '');
  return (
    <div className={styles.form}>
      <div className={styles.row}>
        <BranchSelect id="handoffBranch" value={branch} onChange={setBranch} branches={branches} />
        <input id="handoffDesc" placeholder="description (optional)" />
      </div>
      <HelperText>Leave branch empty to apply all branches.</HelperText>
    </div>
  );
}

function DclForm({ branches, stageConfig }: { branches: BranchInfo[]; stageConfig: StageValues }) {
  const [branch, setBranch] = useState(stageConfig.branch ?? '');
  return (
    <div className={styles.form}>
      <BranchSelect id="dclBranch" value={branch} onChange={setBranch} branches={branches} />
      <HelperText>Leave empty to run DCL diff for all branches, or select one to supplement a specific CR.</HelperText>
    </div>
  );
}

function OffboardForm({ run, lubanHost, onLubanHostChange, offboardYamls, releaseId }: {
  run: GetRunResponse | null; lubanHost: string; onLubanHostChange: (h: string) => void;
  offboardYamls: string[]; releaseId: string | null;
}) {
  const expPath = run?.record.experiment_path ?? '';
  const selectedEpoch = run?.record.selection?.selected_epoch;
  const hasRun = Boolean(releaseId);
  const [mode, setMode] = useState<'selected' | 'explicit'>(hasRun ? 'selected' : 'explicit');
  const yamls = offboardYamls.length ? offboardYamls : ['scenario_dnn_finetune_test.yaml'];
  return (
    <div className={styles.form}>
      <div className={styles.row}>
        <label className={styles.inlineCheck}>
          <input type="radio" name="offboardMode" value="selected" checked={mode === 'selected'}
            disabled={!hasRun} onChange={() => setMode('selected')} />
          Use selected pick
        </label>
        <label className={styles.inlineCheck}>
          <input type="radio" name="offboardMode" value="explicit" checked={mode === 'explicit'}
            onChange={() => setMode('explicit')} />
          Run explicit experiment/epoch
        </label>
      </div>
      <div className={styles.helperText}>Selected pick: {releaseId ?? 'none'}</div>
      <div className={styles.experimentPicker}>
        <input id="offboardExperiment" placeholder="experiment path" defaultValue={expPath} />
      </div>
      <div className={styles.row}>
        <input id="offboardEpoch" placeholder="epoch, e.g. 007"
          defaultValue={selectedEpoch != null ? fmtEpoch(selectedEpoch) : ''} />
        <input id="offboardRemote" className={styles.lubanInput} placeholder="remote" value={lubanHost}
          onChange={(e) => onLubanHostChange(e.target.value)} />
      </div>
      <div className={styles.yamlList}>
        {yamls.map((name, i) => (
          <label key={name} className={styles.inlineCheck}>
            <input className="offboard-yaml-check" type="checkbox" value={name} defaultChecked={i === 0} />
            {name}
          </label>
        ))}
      </div>
      <input id="offboardDesc" placeholder="description / release note" />
      <HelperText>Explicit offboard confirmation text is <b>OFFBOARD</b>; selected-pick offboard uses the current <b>release_id</b>.</HelperText>
    </div>
  );
}

function SimPlanForm({ branches, stageConfig, run }: {
  branches: BranchInfo[]; stageConfig: StageValues; run: GetRunResponse | null;
}) {
  const [branch, setBranch] = useState(stageConfig.branch ?? '');
  const simPlanOut = (run?.record.sim_plan as Record<string, unknown>)?.stdout;
  const lastLine = typeof simPlanOut === 'string'
    ? simPlanOut.split('\n').filter(Boolean).slice(-1)[0] : null;
  return (
    <div className={styles.form}>
      <div className={styles.row}>
        <BranchSelect id="simPlanBranch" value={branch} onChange={setBranch}
          branches={branches} allLabel="all enabled branches" />
        <input id="simPlanRevision" placeholder="optional revision id, defaults to DCL result"
          defaultValue={String(stageConfig.revision_id ?? '')} />
      </div>
      <div className={styles.row}>
        <input id="simPlanPriority" placeholder="priority override"
          defaultValue={String(stageConfig.priority ?? '')} />
        <input id="simPlanSensitiveHour" placeholder="time sensitive hour"
          defaultValue={String(stageConfig.time_sensitive_hour ?? '')} />
      </div>
      <input id="simPlanCancelRecord" placeholder="record id for cancel, e.g. o123456" />
      <HelperText>{lastLine ?? 'No Sim Plan result recorded yet.'}</HelperText>
    </div>
  );
}

// ─── Stage config panel ───────────────────────────────────────────────────────

function StageConfigPanel({ stepKey, branches, stageConfig, releaseId, onSaved }: {
  stepKey: StageKey; branches: BranchInfo[]; stageConfig: StageValues;
  releaseId: string | null; onSaved: (msg: string) => void;
}) {
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);

  const collect = (): StageValues => {
    const v = (id: string) => (document.getElementById(id) as HTMLInputElement)?.value ?? '';
    const checked = (id: string) => (document.getElementById(id) as HTMLInputElement)?.checked ?? false;
    if (stepKey === 'sim_plan') {
      return {
        branch: v('stageConfigBranch') || undefined,
        revision_id: Number(v('stageConfigRevision')) || undefined,
        plans: v('stageConfigPlanNames').split(',').map((s) => s.trim()).filter(Boolean),
        priority: Number(v('stageConfigPriority')) || undefined,
        time_sensitive_hour: Number(v('stageConfigSensitiveHour')) || undefined,
      };
    }
    return {
      branch: v('stageConfigBranch') || undefined,
      checkout_branch: v('stageConfigCheckout') || undefined,
      update_diff_ids: v('stageConfigDiffIds').split(',').map(Number).filter(Boolean),
      sim_plan: v('stageConfigSimPlan') || undefined,
      lint: checked('stageConfigLint'),
      allow_dirty: checked('stageConfigAllowDirty'),
    };
  };

  const saveRun = useCallback(async () => {
    if (!releaseId) return;
    setBusy(true); setStatus('Saving…');
    try {
      await patchRunStageConfig(releaseId, { [stepKey]: collect() });
      setStatus('Saved to run.');
      onSaved('run');
    } catch (e) { setStatus(String(e)); }
    finally { setBusy(false); }
  }, [releaseId, stepKey]);

  const saveDefault = useCallback(async () => {
    setBusy(true); setStatus('Saving…');
    try {
      await patchStageDefaults({ [stepKey]: collect() });
      setStatus('Saved as default.');
      onSaved('default');
    } catch (e) { setStatus(String(e)); }
    finally { setBusy(false); }
  }, [stepKey]);

  const [scBranch, setScBranch] = useState(stageConfig.branch ?? '');

  return (
    <div className={styles.stageConfigPanel}>
      {stepKey === 'sim_plan' ? (
        <div className={styles.stageGrid}>
          <label className={styles.stageLabel}>
            <span>Branch</span>
            <BranchSelect id="stageConfigBranch" value={scBranch} onChange={setScBranch}
              branches={branches} allLabel="all enabled branches" />
          </label>
          <label className={styles.stageLabel}>
            <span>Revision id</span>
            <input id="stageConfigRevision" defaultValue={String(stageConfig.revision_id ?? '')} placeholder="from DCL result" />
          </label>
          <label className={styles.stageLabel}>
            <span>Plans</span>
            <input id="stageConfigPlanNames"
              defaultValue={Array.isArray(stageConfig.plans) ? stageConfig.plans.join(',') : ''} placeholder="comma-separated plan names" />
          </label>
          <label className={styles.stageLabel}>
            <span>Priority</span>
            <input id="stageConfigPriority" defaultValue={String(stageConfig.priority ?? '')} placeholder="optional" />
          </label>
          <label className={styles.stageLabel}>
            <span>Time sensitive hour</span>
            <input id="stageConfigSensitiveHour" defaultValue={String(stageConfig.time_sensitive_hour ?? '')} placeholder="optional" />
          </label>
        </div>
      ) : (
        <>
          <div className={styles.stageGrid}>
            <label className={styles.stageLabel}>
              <span>Branch</span>
              <BranchSelect id="stageConfigBranch" value={scBranch} onChange={setScBranch} branches={branches} />
            </label>
            <label className={styles.stageLabel}>
              <span>Checkout branch</span>
              <input id="stageConfigCheckout" defaultValue={stageConfig.checkout_branch ?? ''} placeholder="temporary checkout branch" />
            </label>
            <label className={styles.stageLabel}>
              <span>CR / update diff ids</span>
              <input id="stageConfigDiffIds"
                defaultValue={Array.isArray(stageConfig.update_diff_ids) ? stageConfig.update_diff_ids.join(',') : ''} placeholder="5716859,6115905" />
            </label>
            <label className={styles.stageLabel}>
              <span>Sim plan</span>
              <input id="stageConfigSimPlan" defaultValue={stageConfig.sim_plan ?? ''} placeholder="sim plan" />
            </label>
          </div>
          <div className={styles.stageChecks}>
            <label className={styles.inlineCheck}>
              <input id="stageConfigLint" type="checkbox" defaultChecked={stageConfig.lint} />
              lint
            </label>
            <label className={styles.inlineCheck}>
              <input id="stageConfigAllowDirty" type="checkbox" defaultChecked={stageConfig.allow_dirty} />
              allow dirty
            </label>
          </div>
        </>
      )}
      <div className={styles.stageActions}>
        <button className={styles.actionBtn} type="button" disabled={busy || !releaseId} onClick={saveRun}>Save to current run</button>
        <button className={styles.actionBtn} type="button" disabled={busy} onClick={saveDefault}>Save as global default</button>
        <span className={styles.helperText}>{status}</span>
      </div>
    </div>
  );
}

// ─── FlowInspector ───────────────────────────────────────────────────────────

interface FlowInspectorProps {
  item: FlowItem;
  status: string;
  actions: ActionSpec[];
  run: GetRunResponse | null;
  releaseId: string | null;
  branches: BranchInfo[];
  stageDefaults: StageConfig;
  offboardYamls: string[];
  lubanHost: string;
  onLubanHostChange: (h: string) => void;
  onJobStarted: (jobId: string) => void;
  confirmText: string;
  onConfirmChange: (v: string) => void;
  onStatusChange: (s: string) => void;
}

export default function FlowInspector({
  item, status, actions, run, releaseId, branches, stageDefaults,
  offboardYamls, lubanHost, onLubanHostChange, onJobStarted,
  confirmText, onConfirmChange: _onConfirmChange, onStatusChange,
}: FlowInspectorProps) {
  const STAGE_CONFIG_STEPS: StageKey[] = ['handoff', 'dcl', 'sim_plan'];
  const supportsStageConfig = STAGE_CONFIG_STEPS.includes(item.key as StageKey);
  const [stageConfigOpen, setStageConfigOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const itemActions = item.actionKeys
    .map((key) => actions.find((a) => a.key === key))
    .filter(Boolean) as ActionSpec[];

  const mergedConfig = (stepKey: string): StageValues => ({
    ...(stageDefaults[stepKey as StageKey] ?? {}),
    ...(run?.record.web_stage_config?.[stepKey as StageKey] ?? {}),
  });

  const collectPayload = (action: ActionSpec, dryRun: boolean) => {
    const g = (id: string) => (document.getElementById(id) as HTMLInputElement)?.value ?? '';
    const gc = (id: string) => (document.getElementById(id) as HTMLInputElement)?.checked ?? false;
    const gcls = (cls: string) => [...document.querySelectorAll<HTMLInputElement>(`.${cls}:checked`)].map((el) => el.value);
    const payload: Record<string, unknown> = { dry_run: dryRun, confirm_text: confirmText };
    const key = action.key;
    if (key === 'pick') {
      payload.experiment = g('pickExperiment');
      payload.remote = g('pickRemote');
      payload.description = g('pickDesc');
    } else if (key === 'export') {
      payload.experiment = g('exportExperiment');
      payload.epoch = g('exportEpoch');
      payload.remote = g('exportRemote');
      payload.description = g('exportDesc');
    } else if (key === 'upload') {
      payload.version = g('uploadVersion');
      payload.replace = gc('uploadReplace');
      payload.description = g('uploadDesc');
    } else if (key === 'ifx-convert') {
      payload.build_url = g('ifxBuildUrl');
    } else if (key === 'handoff') {
      payload.branch = g('handoffBranch');
      payload.description = g('handoffDesc');
    } else if (key === 'apply-handoff') {
      payload.branch = g('handoffBranch');
    } else if (key === 'dcl') {
      payload.branch = g('dclBranch');
    } else if (key === 'sim-plan') {
      payload.branch = g('simPlanBranch');
      payload.revision_id = g('simPlanRevision');
      payload.priority = g('simPlanPriority');
      payload.time_sensitive_hour = g('simPlanSensitiveHour');
      payload.plans = gcls('sim-plan-check');
    } else if (key === 'sim-plan-cancel') {
      payload.record_id = g('simPlanCancelRecord');
    } else if (key === 'offboard') {
      const modeEl = document.querySelector<HTMLInputElement>('input[name="offboardMode"]:checked');
      payload.mode = modeEl?.value ?? 'explicit';
      payload.experiment = g('offboardExperiment');
      payload.epoch = g('offboardEpoch');
      payload.remote = g('offboardRemote');
      payload.yamls = gcls('offboard-yaml-check');
      payload.description = g('offboardDesc');
    }
    return payload;
  };

  const runAction = useCallback(async (action: ActionSpec, dryRun: boolean) => {
    const target = action.needs_run_id ? releaseId : (releaseId ?? '__new__');
    if (action.needs_run_id && !releaseId) { onStatusChange('Select a release run first.'); return; }
    setBusy(true);
    onStatusChange('Starting…');
    try {
      const payload = collectPayload(action, dryRun);
      const res = await startAction(target!, action.key, payload);
      onStatusChange(`Job started: ${res.job_id}`);
      onJobStarted(res.job_id);
    } catch (e) { onStatusChange(String(e)); }
    finally { setBusy(false); }
  }, [releaseId, confirmText, onStatusChange, onJobStarted]);

  return (
    <div className={styles.inspector}>
      <div className={styles.inspectorHead}>
        <div>
          <p className="eyebrow">Selected Step</p>
          <h3>{item.title}</h3>
          <p className={styles.helperText}>{item.detail}</p>
        </div>
        <div className={styles.inspectorTools}>
          {supportsStageConfig && (
            <button
              className={styles.iconButton}
              type="button"
              title="Stage settings"
              onClick={() => setStageConfigOpen((v) => !v)}
            >⚙</button>
          )}
          <span className={`chip ${status}`}>{status}</span>
        </div>
      </div>

      {item.key === 'pick' && <PickForm run={run} lubanHost={lubanHost} onLubanHostChange={onLubanHostChange} />}
      {item.key === 'export' && <ExportForm run={run} lubanHost={lubanHost} onLubanHostChange={onLubanHostChange} />}
      {item.key === 'upload' && <UploadForm />}
      {item.key === 'ifx' && <IfxForm run={run} />}
      {item.key === 'handoff' && <HandoffForm branches={branches} stageConfig={mergedConfig('handoff')} />}
      {item.key === 'dcl' && <DclForm branches={branches} stageConfig={mergedConfig('dcl')} />}
      {item.key === 'offboard' && (
        <OffboardForm run={run} lubanHost={lubanHost} onLubanHostChange={onLubanHostChange}
          offboardYamls={offboardYamls} releaseId={releaseId} />
      )}
      {item.key === 'sim_plan' && (
        <SimPlanForm branches={branches} stageConfig={mergedConfig('sim_plan')} run={run} />
      )}

      {supportsStageConfig && stageConfigOpen && (
        <StageConfigPanel
          stepKey={item.key as StageKey}
          branches={branches}
          stageConfig={mergedConfig(item.key)}
          releaseId={releaseId}
          onSaved={(msg) => onStatusChange(`Stage config saved (${msg}).`)}
        />
      )}

      <div className={styles.flowActions}>
        {itemActions.map((action) => (
          <div key={action.key} className={styles.actionGroup}>
            {action.supports_dry_run && (
              <button
                className={`${styles.actionBtn} ${styles.actionBtnPrimary} ${styles.actionBtnFull}`}
                type="button" disabled={busy}
                onClick={() => runAction(action, true)}>
                {action.label} Dry-run
              </button>
            )}
            <button
              className={`${styles.actionBtn} ${action.requires_confirm ? styles.actionBtnDanger : styles.actionBtnPrimary} ${styles.actionBtnFull}`}
              type="button" disabled={busy || (action.needs_run_id && !releaseId)}
              onClick={() => runAction(action, false)}>
              {action.label}
            </button>
          </div>
        ))}
      </div>

    </div>
  );
}
