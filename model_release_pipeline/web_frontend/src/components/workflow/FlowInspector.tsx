import { useState, useCallback, useEffect } from 'react';
import type {
  ActionSpec, BranchInfo, ExperimentFolder, GetRunResponse,
  OffboardTestYamlEntry, PickPreviewResponse, StageConfig, StageKey, StageValues,
} from '../../types/api';
import type { FlowItem } from './flowItems';
import {
  copyVersionedOnnx, listExperimentFolders, previewPick,
  startAction, patchRunStageConfig, patchStageDefaults,
} from '../../api/client';
import styles from './FlowInspector.module.css';

const DEFAULT_ROOT = 'device:/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/ego_stuck_data/scenario_dnn_26q1/';

function fmtEpoch(val: number | null | undefined): string {
  if (val == null) return '';
  return Number.isInteger(val) ? String(val).padStart(3, '0') : Number(val).toFixed(1);
}

function fmt(val: unknown, digits = 3): string {
  return val != null ? Number(val).toFixed(digits) : 'N/A';
}

function formatPickLog(data: PickPreviewResponse): string[] {
  const pick = (data.pick ?? {}) as Record<string, unknown>;
  const lines: string[] = [];
  const epoch = pick.recommended_epoch as number | null | undefined;
  lines.push('=== Pick Preview ===');
  lines.push(`Recommended epoch: ${epoch != null ? fmtEpoch(epoch) : 'none'}`);
  lines.push(`Policy: ${pick.policy ?? '?'} | top_n: ${pick.top_n ?? '?'} | loss_tolerance_pct: ${pick.loss_tolerance_pct ?? '?'}`);
  lines.push('');
  const notes = (pick.notes as string[] | undefined) ?? [];
  if (notes.length) {
    lines.push('Notes:');
    for (const note of notes) lines.push(`  - ${note}`);
    lines.push('');
  }
  const candidates = (pick.candidates as Record<string, unknown>[] | undefined) ?? [];
  if (candidates.length) {
    lines.push('Top candidates:');
    for (const [i, c] of candidates.entries()) {
      const marker = c.epoch === epoch ? ' ◀ recommended' : '';
      const mbt = (c.metrics_by_task as Record<string, Record<string, unknown>> | undefined) ?? {};
      const taskKeys = Object.keys(mbt);
      if (taskKeys.length) {
        lines.push(`  ${String(i + 1).padStart(2)}.  epoch ${fmtEpoch(c.epoch as number)}${marker}`);
        for (const task of taskKeys) {
          const m = mbt[task];
          lines.push(
            `        [${task}]  precision=${fmt(m.precision)}  recall=${fmt(m.recall)}` +
            `  loss=${fmt(m.loss)}  pr_auc=${fmt(m.pr_auc)}  roc_auc=${fmt(m.roc_auc)}`,
          );
        }
      } else {
        const task = c.task ? ` [${c.task as string}]` : '';
        lines.push(
          `  ${String(i + 1).padStart(2)}.  epoch ${fmtEpoch(c.epoch as number)}${task}` +
          `  precision=${fmt(c.precision)}  recall=${fmt(c.recall)}  loss=${fmt(c.loss)}` +
          `  pr_auc=${fmt(c.pr_auc)}  roc_auc=${fmt(c.roc_auc)}${marker}`,
        );
        for (const note of (c.notes as string[] | undefined) ?? []) lines.push(`        note: ${note}`);
      }
    }
    lines.push('');
  }
  const perTask = (pick.per_task as Record<string, Record<string, unknown>> | undefined) ?? {};
  const perTaskKeys = Object.keys(perTask);
  if (perTaskKeys.length > 1) {
    lines.push('Per-task recommendations:');
    for (const task of perTaskKeys) {
      const tr = perTask[task];
      const ep = tr.recommended_epoch as number | null | undefined;
      lines.push(`  ${task}: recommended epoch ${ep != null ? fmtEpoch(ep) : 'none'}`);
    }
  }
  return lines;
}

// ─── Shared sub-components ───────────────────────────────────────────────────

const _folderCache = new Map<string, ExperimentFolder[]>();

function ExperimentPicker({ id, defaultValue, lubanHost }: {
  id: string; defaultValue?: string; lubanHost: string;
}) {
  const [value, setValue] = useState(defaultValue ?? '');
  const [folders, setFolders] = useState<ExperimentFolder[]>(() => _folderCache.get(lubanHost) ?? []);
  const [loading, setLoading] = useState(false);

  useEffect(() => { setValue(defaultValue ?? ''); }, [defaultValue]);

  const fetch = useCallback(async (force = false) => {
    if (!force && _folderCache.has(lubanHost)) {
      setFolders(_folderCache.get(lubanHost)!);
      return;
    }
    setLoading(true);
    try {
      const data = await listExperimentFolders(DEFAULT_ROOT, 100, lubanHost);
      _folderCache.set(lubanHost, data.folders);
      setFolders(data.folders);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [lubanHost]);

  useEffect(() => { void fetch(); }, [fetch]);

  return (
    <div className={styles.experimentPicker}>
      <input id={id} placeholder="experiment path" value={value} onChange={(e) => setValue(e.target.value)} />
      <div className={styles.row}>
        <select
          className={styles.experimentSelect}
          value={value}
          onChange={(e) => { if (e.target.value) setValue(e.target.value); }}
        >
          <option value="">{loading ? 'Loading…' : folders.length ? 'Select folder…' : 'No folders found'}</option>
          {folders.map((f) => <option key={f.path} value={f.path}>{f.name}</option>)}
        </select>
        <button className={styles.iconButton} type="button" title="Refresh folders" disabled={loading} onClick={() => fetch(true)}>↻</button>
      </div>
    </div>
  );
}

function LubanRemoteControl({ id, value, hosts, onChange }: {
  id: string; value: string; hosts: string[]; onChange: (v: string) => void;
}) {
  const idx = hosts.indexOf(value);
  const next = hosts.length > 0 ? (hosts[(idx >= 0 ? idx + 1 : 0) % hosts.length] ?? value) : value;
  return (
    <div className={styles.lubanRemoteControl}>
      <input id={id} className={styles.lubanInput} placeholder="remote" value={value}
        onChange={(e) => onChange(e.target.value)} />
      <button className={styles.iconButton} type="button" title={`Switch to ${next}`}
        onClick={() => onChange(next)}>⇄</button>
    </div>
  );
}

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

function BranchPrepForm({ branches }: { branches: BranchInfo[] }) {
  const [base, setBase] = useState('');
  const [newBranch, setNewBranch] = useState('');
  const [touched, setTouched] = useState(false);

  // Auto-suggest a working branch name from the chosen base branch until the
  // operator types their own.
  const handleBaseChange = (v: string) => {
    setBase(v);
    if (!touched) setNewBranch(v ? `rule_patch/${v}` : '');
  };

  return (
    <div className={styles.form}>
      <div className={styles.row}>
        <label className={styles.stageLabel}>
          <span>Base release branch</span>
          <BranchSelect id="branchPrepBase" value={base} onChange={handleBaseChange}
            branches={branches} allLabel="select release branch" />
        </label>
        <label className={styles.stageLabel}>
          <span>New working branch</span>
          <input id="branchPrepNew" placeholder="e.g. rule_patch/gen4_release_20260508"
            value={newBranch}
            onChange={(e) => { setTouched(true); setNewBranch(e.target.value); }} />
        </label>
      </div>
      <HelperText>
        Runs inside the Voyager docker: <code>git checkout &lt;base&gt;</code> then <code>git checkout -b &lt;new&gt;</code>.
        Creates a new Rule Patch run — no <b>release_id</b> needed.
      </HelperText>
    </div>
  );
}

function DclPatchForm({ branches, run, draftPrefill }: {
  branches: BranchInfo[]; run: GetRunResponse | null; draftPrefill?: { revision_id?: string };
}) {
  const [branch, setBranch] = useState('');
  const history = run?.record.dcl_patch_history ?? [];
  return (
    <div className={styles.form}>
      <div className={styles.row}>
        <label className={styles.stageLabel}>
          <span>DCL Revision ID</span>
          <input id="dclPatchRevision" placeholder="e.g. 6231959"
            defaultValue={draftPrefill?.revision_id ?? ''} />
        </label>
        <label className={styles.stageLabel}>
          <span>Branch (optional)</span>
          <BranchSelect id="dclPatchBranch" value={branch} onChange={setBranch} branches={branches} allLabel="all branches" />
        </label>
      </div>
      <label className={styles.inlineCheck}>
        <input id="dclPatchNobranch" type="checkbox" defaultChecked />
        <code>--nobranch</code> (patch without creating a branch)
      </label>
      {history.length > 0 && (
        <div className={styles.runMeta} style={{ marginTop: 4 }}>
          <span className={styles.helperText} style={{ marginRight: 6 }}>Applied CRs:</span>
          {history.map((h, i) => (
            <span key={i} className={`chip ${h.returncode === 0 || h.dry_run ? 'done' : 'failed'}`}>
              {h.revision_id}{h.dry_run ? ' (dry)' : ''}
            </span>
          ))}
        </div>
      )}
      <HelperText>
        Runs inside the Voyager docker: <code>dcl patch --revision &lt;id&gt; [--nobranch] [--branch &lt;branch&gt;]</code>.
        Repeatable — each CR is appended, not overwritten. Confirmation text is the current <b>release_id</b>.
      </HelperText>
    </div>
  );
}

function PickForm({ run, lubanHost, lubanHosts, onLubanHostChange, onPickPreview }: {
  run: GetRunResponse | null;
  lubanHost: string; lubanHosts: string[];
  onLubanHostChange: (h: string) => void;
  onPickPreview: (lines: string[]) => void;
}) {
  const expPath = run?.record.experiment_path ?? '';
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewResult, setPreviewResult] = useState('');

  const handlePreview = async () => {
    const exp = (document.getElementById('pickExperiment') as HTMLInputElement | null)?.value ?? '';
    if (!exp) return;
    setPreviewLoading(true);
    try {
      const data = await previewPick(exp, lubanHost);
      const epoch = (data.pick as Record<string, unknown> | undefined)?.recommended_epoch;
      setPreviewResult(epoch != null ? `Recommended: epoch ${fmtEpoch(epoch as number)}` : data.error ?? 'No recommendation');
      onPickPreview(formatPickLog(data));
    } catch (e) {
      setPreviewResult(String(e));
      onPickPreview([String(e)]);
    } finally {
      setPreviewLoading(false);
    }
  };

  return (
    <div className={styles.form}>
      <ExperimentPicker id="pickExperiment" defaultValue={expPath} lubanHost={lubanHost} />
      <div className={styles.row}>
        <LubanRemoteControl id="pickRemote" value={lubanHost} hosts={lubanHosts} onChange={onLubanHostChange} />
        <input id="pickDesc" placeholder="description / release note" />
      </div>
      <div className={styles.row}>
        <button className={styles.actionBtn} type="button" disabled={previewLoading} onClick={handlePreview}>
          {previewLoading ? 'Loading…' : 'Preview epoch ↗'}
        </button>
        {previewResult && <span className={styles.helperText} style={{ margin: 0 }}>{previewResult}</span>}
      </div>
      <HelperText>Pick runs on Luban and creates a new release.</HelperText>
    </div>
  );
}

function ExportForm({ run, lubanHost, lubanHosts, onLubanHostChange }: {
  run: GetRunResponse | null; lubanHost: string; lubanHosts: string[]; onLubanHostChange: (h: string) => void;
}) {
  const expPath = run?.record.experiment_path ?? '';
  return (
    <div className={styles.form}>
      <ExperimentPicker id="exportExperiment" defaultValue={expPath} lubanHost={lubanHost} />
      <div className={styles.row}>
        <input id="exportEpoch" placeholder="epoch, e.g. 007" />
        <LubanRemoteControl id="exportRemote" value={lubanHost} hosts={lubanHosts} onChange={onLubanHostChange} />
      </div>
      <input id="exportDesc" placeholder="description / release note" />
      <HelperText>Real export confirmation text is <b>EXPORT</b>.</HelperText>
    </div>
  );
}

function UploadForm({ run, releaseId }: { run: GetRunResponse | null; releaseId: string | null }) {
  const copyInfo = run?.versioned_onnx as Record<string, unknown> | undefined;
  const [copyStatus, setCopyStatus] = useState('');

  const handleCopy = async () => {
    if (!releaseId) return;
    setCopyStatus('Copying…');
    try {
      const r = await copyVersionedOnnx(releaseId);
      setCopyStatus(String(r.message ?? r.target_path ?? 'Done'));
    } catch (e) {
      setCopyStatus(String(e));
    }
  };

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
      {!!copyInfo?.available && (
        <div className={styles.row}>
          <button className={styles.actionBtn} type="button" onClick={handleCopy}>Copy versioned ONNX</button>
          <span className={styles.helperText}>{copyStatus || String(copyInfo.target_path ?? '')}</span>
        </div>
      )}
      <HelperText>Real upload confirmation text is the current <b>release_id</b>.</HelperText>
    </div>
  );
}

function IfxForm({ run }: { run: GetRunResponse | null }) {
  const buildUrl = run?.record.ifx?.jenkins?.build_url ?? '';
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

interface DclBranchConfig {
  id: number;
  branchName: string;
  checkoutBranch: string;
  updateDiffIds: string;
  simPlan: string;
  lint: boolean;
  allowDirty: boolean;
}

function DclForm({ branches, stageConfig }: { branches: BranchInfo[]; stageConfig: StageValues }) {
  const [activeBranchName, setActiveBranchName] = useState(stageConfig.branch ?? '');
  const [configs, setConfigs] = useState<DclBranchConfig[]>(() =>
    branches.length
      ? branches.map((b, i) => ({
          id: i,
          branchName: b.name,
          checkoutBranch: b.checkout_branch ?? '',
          updateDiffIds: (b.update_diff_ids ?? []).join(', '),
          simPlan: '',
          lint: false,
          allowDirty: false,
        }))
      : [{
          id: 0,
          branchName: stageConfig.branch ?? '',
          checkoutBranch: stageConfig.checkout_branch ?? '',
          updateDiffIds: (stageConfig.update_diff_ids ?? []).join(', '),
          simPlan: stageConfig.sim_plan ?? '',
          lint: stageConfig.lint ?? false,
          allowDirty: stageConfig.allow_dirty ?? false,
        }]
  );
  const [nextId, setNextId] = useState(branches.length || 1);
  const [expandedId, setExpandedId] = useState<number | null>(configs[0]?.id ?? null);

  const updateConfig = (id: number, patch: Partial<DclBranchConfig>) =>
    setConfigs((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)));

  const addConfig = () => {
    const newCfg: DclBranchConfig = { id: nextId, branchName: '', checkoutBranch: '', updateDiffIds: '', simPlan: '', lint: false, allowDirty: false };
    setConfigs((prev) => [...prev, newCfg]);
    setExpandedId(nextId);
    setNextId((n) => n + 1);
  };

  const removeConfig = (id: number) => {
    setConfigs((prev) => {
      const next = prev.filter((c) => c.id !== id);
      if (expandedId === id) setExpandedId(next[0]?.id ?? null);
      return next;
    });
  };

  // Sync activeBranchName hidden input so collectPayload can read it
  const activeConfig = configs.find((c) => c.branchName === activeBranchName) ?? configs[0];

  return (
    <div className={styles.form}>
      <div className={styles.dclBranchHeader}>
        <span className={styles.dclBranchLabel}>DCL branch configs</span>
        <button className={styles.iconButton} type="button" onClick={addConfig} title="Add branch config">+ Add</button>
      </div>

      <div className={styles.dclConfigList}>
        {configs.map((cfg) => {
          const isExpanded = expandedId === cfg.id;
          return (
            <div key={cfg.id} className={`${styles.dclConfigCard} ${activeBranchName === cfg.branchName ? styles.dclConfigCardActive : ''}`}>
              <div className={styles.dclConfigCardHeader}>
                <button
                  className={styles.dclConfigCardTitle}
                  type="button"
                  onClick={() => { setExpandedId(isExpanded ? null : cfg.id); setActiveBranchName(cfg.branchName); }}
                >
                  <span className={styles.dclConfigCardChevron}>{isExpanded ? '▾' : '▸'}</span>
                  <span>{cfg.branchName || <em className={styles.muted}>new branch</em>}</span>
                </button>
                <div className={styles.dclConfigCardActions}>
                  <label className={styles.inlineCheck} title="Set as active branch for DCL run">
                    <input
                      type="radio"
                      name="dclActiveBranch"
                      checked={activeBranchName === cfg.branchName}
                      onChange={() => setActiveBranchName(cfg.branchName)}
                    />
                    run this
                  </label>
                  {configs.length > 1 && (
                    <button className={styles.iconButton} type="button" title="Remove" onClick={() => removeConfig(cfg.id)}>×</button>
                  )}
                </div>
              </div>
              {isExpanded && (
                <div className={styles.dclConfigCardBody}>
                  <div className={styles.row}>
                    <label className={styles.stageLabel}>
                      <span>Branch</span>
                      <BranchSelect id="dclBranch" value={cfg.branchName} onChange={(v) => { updateConfig(cfg.id, { branchName: v }); if (activeBranchName === cfg.branchName) setActiveBranchName(v); }} branches={branches} allLabel="all branches" />
                    </label>
                    <label className={styles.stageLabel}>
                      <span>Checkout branch</span>
                      <input placeholder="temporary checkout" value={cfg.checkoutBranch} onChange={(e) => updateConfig(cfg.id, { checkoutBranch: e.target.value })} />
                    </label>
                  </div>
                  <div className={styles.row}>
                    <label className={styles.stageLabel}>
                      <span>Update diff IDs</span>
                      <input placeholder="e.g. 5716859, 6115905" value={cfg.updateDiffIds} onChange={(e) => updateConfig(cfg.id, { updateDiffIds: e.target.value })} />
                    </label>
                    <label className={styles.stageLabel}>
                      <span>Sim plan</span>
                      <input placeholder="sim plan name" value={cfg.simPlan} onChange={(e) => updateConfig(cfg.id, { simPlan: e.target.value })} />
                    </label>
                  </div>
                  <div className={styles.stageChecks}>
                    <label className={styles.inlineCheck}>
                      <input type="checkbox" checked={cfg.lint} onChange={(e) => updateConfig(cfg.id, { lint: e.target.checked })} />
                      lint
                    </label>
                    <label className={styles.inlineCheck}>
                      <input type="checkbox" checked={cfg.allowDirty} onChange={(e) => updateConfig(cfg.id, { allowDirty: e.target.checked })} />
                      allow dirty
                    </label>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Hidden inputs for collectPayload compatibility */}
      <input id="dclBranchActive" type="hidden" value={activeConfig?.branchName ?? ''} />
      <input id="dclCheckoutBranch" type="hidden" value={activeConfig?.checkoutBranch ?? ''} />
      <input id="dclUpdateDiffIds" type="hidden" value={activeConfig?.updateDiffIds ?? ''} />
      <input id="dclSimPlan" type="hidden" value={activeConfig?.simPlan ?? ''} />
      <input id="dclLint" type="hidden" value={activeConfig?.lint ? 'true' : ''} />
      <input id="dclAllowDirty" type="hidden" value={activeConfig?.allowDirty ? 'true' : ''} />

      <HelperText>Select "run this" on a branch to target that config; leave branch empty to run for all branches.</HelperText>
    </div>
  );
}

function SimPlanForm({ branches, stageConfig, run }: {
  branches: BranchInfo[]; stageConfig: StageValues; run: GetRunResponse | null;
}) {
  const [branch, setBranch] = useState(stageConfig.branch ?? '');
  const selectedPlans = Array.isArray(stageConfig.plans) ? new Set(stageConfig.plans) : null;
  const [customPlans, setCustomPlans] = useState<string[]>([]);
  const [customInput, setCustomInput] = useState('');
  const simPlanOut = (run?.record.sim_plan as Record<string, unknown> | undefined)?.stdout;
  const lastLine = typeof simPlanOut === 'string'
    ? simPlanOut.split('\n').filter(Boolean).slice(-1)[0] : null;

  const addCustomPlan = () => {
    const name = customInput.trim();
    if (!name || customPlans.includes(name)) return;
    setCustomPlans((prev) => [...prev, name]);
    setCustomInput('');
  };

  return (
    <div className={styles.form}>
      <div className={styles.row}>
        <BranchSelect id="simPlanBranch" value={branch} onChange={setBranch}
          branches={branches} allLabel="all enabled branches" />
        <input id="simPlanRevision" placeholder="optional revision id, defaults to DCL result"
          defaultValue={String(stageConfig.revision_id ?? '')} />
      </div>
      <div className={styles.simPlanList}>
        {branches.map((b) => {
          const plans = b.sim_plans ?? (b.sim_plan ? [{
            name: b.sim_plan,
            enabled_by_default: b.name !== 'master' && b.sim_plan !== 'topic_ra_auto_trigger',
          }] : []);
          if (!plans.length) return null;
          const hidden = branch !== '' && branch !== b.name;
          return (
            <div key={b.name} className={styles.simPlanBranchPlans} style={hidden ? { display: 'none' } : undefined}>
              <div className={styles.simPlanBranchTitle}>
                {b.name} <span>CR {(b.update_diff_ids ?? []).join(',') || 'from DCL'}</span>
              </div>
              <div className={styles.simPlanChecks}>
                {plans.map((plan) => {
                  const enabledByDefault = plan.enabled_by_default === true || plan.enabled_by_default === 'true';
                  const checked = selectedPlans ? selectedPlans.has(plan.name) : enabledByDefault;
                  return (
                    <label key={plan.name} className={styles.inlineCheck}>
                      <input className="sim-plan-check" type="checkbox" value={plan.name} defaultChecked={checked} />
                      {plan.name}
                    </label>
                  );
                })}
              </div>
            </div>
          );
        })}
        {customPlans.length > 0 && (
          <div className={styles.simPlanBranchPlans}>
            <div className={styles.simPlanBranchTitle}>Custom plans</div>
            <div className={styles.simPlanChecks}>
              {customPlans.map((name) => (
                <label key={name} className={styles.inlineCheck}>
                  <input className="sim-plan-check" type="checkbox" value={name} defaultChecked />
                  {name}
                  <button
                    className={styles.planRemoveBtn}
                    type="button"
                    title="Remove"
                    onClick={() => setCustomPlans((prev) => prev.filter((p) => p !== name))}
                  >×</button>
                </label>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className={styles.simPlanAddRow}>
        <input
          className={styles.simPlanAddInput}
          placeholder="custom plan name"
          value={customInput}
          onChange={(e) => setCustomInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addCustomPlan(); } }}
        />
        <button className={styles.actionBtn} type="button" onClick={addCustomPlan}>+ Add Plan</button>
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

function OffboardForm({ run, lubanHost, lubanHosts, onLubanHostChange, offboardYamls, releaseId }: {
  run: GetRunResponse | null; lubanHost: string; lubanHosts: string[]; onLubanHostChange: (h: string) => void;
  offboardYamls: OffboardTestYamlEntry[]; releaseId: string | null;
}) {
  const expPath = run?.record.experiment_path ?? '';
  const selectedEpoch = run?.record.selection?.selected_epoch;
  const hasRun = Boolean(releaseId);
  const [mode, setMode] = useState<'selected' | 'explicit'>(hasRun ? 'selected' : 'explicit');
  const yamls = offboardYamls.length
    ? offboardYamls
    : [{ name: 'scenario_dnn_finetune_test.yaml', path: 'configs/scenario_dnn_finetune_test.yaml' }];
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
      <ExperimentPicker id="offboardExperiment" defaultValue={expPath} lubanHost={lubanHost} />
      <div className={styles.row}>
        <input id="offboardEpoch" placeholder="epoch, e.g. 007"
          defaultValue={selectedEpoch != null ? fmtEpoch(selectedEpoch) : ''} />
        <LubanRemoteControl id="offboardRemote" value={lubanHost} hosts={lubanHosts} onChange={onLubanHostChange} />
      </div>
      <div className={styles.yamlList}>
        {yamls.map((yaml, i) => (
          <label key={yaml.name} className={styles.inlineCheck}>
            <input className="offboard-yaml-check" type="checkbox" value={yaml.path ?? yaml.name} defaultChecked={i === 0} />
            {yaml.name}
          </label>
        ))}
      </div>
      <input id="offboardDesc" placeholder="description / release note" />
      <HelperText>Explicit offboard confirmation text is <b>OFFBOARD</b>; selected-pick offboard uses the current <b>release_id</b>.</HelperText>
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
  offboardYamls: OffboardTestYamlEntry[];
  lubanHost: string;
  lubanHosts: string[];
  onLubanHostChange: (h: string) => void;
  onPickPreview: (lines: string[]) => void;
  onJobStarted: (jobId: string) => void;
  confirmText: string;
  onConfirmChange: (v: string) => void;
  onStatusChange: (s: string) => void;
  workflowType: string;
  draftPrefill?: { revision_id?: string };
}

export default function FlowInspector({
  item, status, actions, run, releaseId, branches, stageDefaults,
  offboardYamls, lubanHost, lubanHosts, onLubanHostChange, onPickPreview,
  onJobStarted, confirmText, onConfirmChange: _onConfirmChange, onStatusChange,
  workflowType, draftPrefill,
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
    // Run-creating actions tag the new record with the active workflow type.
    if (['branch-prep', 'pick', 'export', 'offboard'].includes(key)) {
      payload.workflow_type = workflowType;
    }
    if (key === 'branch-prep') {
      payload.base_branch = g('branchPrepBase');
      payload.new_branch = g('branchPrepNew');
    } else if (key === 'dcl-patch') {
      payload.revision_id = g('dclPatchRevision');
      payload.branch = g('dclPatchBranch');
      payload.nobranch = (document.getElementById('dclPatchNobranch') as HTMLInputElement)?.checked ?? true;
    } else if (key === 'pick') {
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
      payload.branch = g('dclBranchActive') || g('dclBranch');
      payload.checkout_branch = g('dclCheckoutBranch');
      payload.update_diff_ids = g('dclUpdateDiffIds').split(',').map((s) => s.trim()).filter(Boolean);
      payload.sim_plan = g('dclSimPlan');
      payload.lint = g('dclLint') === 'true';
      payload.allow_dirty = g('dclAllowDirty') === 'true';
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
    const target = action.needs_run_id ? releaseId : (releaseId ?? '__draft__');
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
  }, [releaseId, confirmText, workflowType, onStatusChange, onJobStarted]);

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

      {item.key === 'branch_prep' && <BranchPrepForm branches={branches} />}
      {item.key === 'dcl_patch' && <DclPatchForm branches={branches} run={run} draftPrefill={draftPrefill} />}
      {item.key === 'pick' && (
        <PickForm run={run} lubanHost={lubanHost} lubanHosts={lubanHosts}
          onLubanHostChange={onLubanHostChange} onPickPreview={onPickPreview} />
      )}
      {item.key === 'export' && (
        <ExportForm run={run} lubanHost={lubanHost} lubanHosts={lubanHosts} onLubanHostChange={onLubanHostChange} />
      )}
      {item.key === 'upload' && <UploadForm run={run} releaseId={releaseId} />}
      {item.key === 'ifx' && <IfxForm run={run} />}
      {item.key === 'handoff' && <HandoffForm branches={branches} stageConfig={mergedConfig('handoff')} />}
      {item.key === 'dcl' && <DclForm branches={branches} stageConfig={mergedConfig('dcl')} />}
      {item.key === 'offboard' && (
        <OffboardForm run={run} lubanHost={lubanHost} lubanHosts={lubanHosts}
          onLubanHostChange={onLubanHostChange} offboardYamls={offboardYamls} releaseId={releaseId} />
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
            {action.supports_dry_run && action.key !== 'pick' && (
              <button
                className={`${styles.actionBtn} ${styles.actionBtnPrimary} ${styles.actionBtnFull}`}
                type="button" disabled={busy || (action.needs_run_id && !releaseId)}
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
