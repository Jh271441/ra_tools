import { useCallback, useEffect, useMemo, useState } from 'react';
import type { BranchInfo, GetRunResponse, ReleaseMatrixEntry } from '../../types/api';
import { startAction } from '../../api/client';
import { useJobPoller } from '../../hooks/useJobPoller';
import LogDrawer from '../logs/LogDrawer';
import styles from './RuleMatrixView.module.css';

interface RuleMatrixViewProps {
  selectedId: string | null;
  run: GetRunResponse | null;
  draftRun: boolean;
  branches: BranchInfo[];
  onRunRefresh: (newReleaseId?: string) => void;
}

function statusChipClass(status: string | undefined): string {
  if (!status) return '';
  if (status === 'failed') return 'failed';
  if (status === 'completed') return 'done';
  if (status === 'dry_run') return 'dry_run';
  return '';
}

function stepState(step: { returncode?: number | null; dry_run?: boolean } | undefined): string {
  if (!step || Object.keys(step).length === 0) return '·';
  if (step.returncode === 0) return '✓';
  if (step.dry_run) return '◐';
  if (step.returncode == null) return '◐';
  return '✗';
}

export default function RuleMatrixView({
  selectedId,
  run,
  draftRun,
  branches,
  onRunRefresh,
}: RuleMatrixViewProps) {
  const { activeJob, trackJob } = useJobPoller();

  const spec = run?.record.rule_patch;
  const releases: ReleaseMatrixEntry[] = run?.record.releases ?? [];

  // Draft setup-form state
  const [revisionId, setRevisionId] = useState('');
  const [ruleName, setRuleName] = useState('');
  const [branchPrefix, setBranchPrefix] = useState('jasperchen');
  const [selectedReleases, setSelectedReleases] = useState<string[]>([]);
  const [adhoc, setAdhoc] = useState('');
  const [extraReleases, setExtraReleases] = useState<string[]>([]);

  const [confirmText, setConfirmText] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);

  // Refresh run data / select new run when a job finishes.
  useEffect(() => {
    if (!activeJob || activeJob.status === 'running') return;
    const isSetupCreate =
      !selectedId && activeJob.status === 'completed' && activeJob.action === 'rule-setup';
    onRunRefresh(isSetupCreate ? '__draft__' : undefined);
  }, [activeJob?.status, activeJob?.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const branchNames = useMemo(
    () => Array.from(new Set([...branches.map((b) => b.name), ...extraReleases])),
    [branches, extraReleases],
  );

  const toggleRelease = useCallback((name: string) => {
    setSelectedReleases((prev) =>
      prev.includes(name) ? prev.filter((r) => r !== name) : [...prev, name],
    );
  }, []);

  const addAdhoc = useCallback(() => {
    const name = adhoc.trim();
    if (!name) return;
    setExtraReleases((prev) => (prev.includes(name) ? prev : [...prev, name]));
    setSelectedReleases((prev) => (prev.includes(name) ? prev : [...prev, name]));
    setAdhoc('');
  }, [adhoc]);

  const runAction = useCallback(
    async (action: string, payload: Record<string, unknown>, target: string) => {
      setBusy(true);
      setStatus('Starting…');
      try {
        const res = await startAction(target, action, payload);
        setStatus(`Job started: ${res.job_id}`);
        trackJob(res.job_id);
      } catch (e) {
        setStatus(String(e));
      } finally {
        setBusy(false);
      }
    },
    [trackJob],
  );

  // --- Draft: Rule Setup form ---------------------------------------------
  if (!selectedId && draftRun) {
    const canCreate = revisionId.trim() && ruleName.trim() && selectedReleases.length > 0;
    return (
      <div className={styles.view}>
        <div className={`panel ${styles.ruleCard}`}>
          <p className="eyebrow">Rule Patch</p>
          <h3>New Rule Validation</h3>
          <p className={styles.help}>
            Validate one rule CR across a set of release branches. Each release gets its own
            working branch <code>&lt;prefix&gt;/&lt;release&gt;/&lt;rule&gt;</code>; <code>dcl diff</code>{' '}
            creates or updates that release's persistent test CR.
          </p>
          <div className={styles.formGrid}>
            <label className={styles.field}>
              <span>Rule CR revision id</span>
              <input value={revisionId} placeholder="e.g. 6231959"
                onChange={(e) => setRevisionId(e.target.value)} />
            </label>
            <label className={styles.field}>
              <span>Rule name</span>
              <input value={ruleName} placeholder="e.g. FN_forcing_recall"
                onChange={(e) => setRuleName(e.target.value)} />
            </label>
            <label className={styles.field}>
              <span>Working branch prefix</span>
              <input value={branchPrefix} placeholder="e.g. jasperchen"
                onChange={(e) => setBranchPrefix(e.target.value)} />
            </label>
          </div>

          <div className={styles.releasePicker}>
            <div className={styles.releasePickerHead}>
              <span>Target releases ({selectedReleases.length})</span>
            </div>
            <div className={styles.releaseChecks}>
              {branchNames.map((name) => (
                <label key={name} className={styles.releaseCheck}>
                  <input type="checkbox" checked={selectedReleases.includes(name)}
                    onChange={() => toggleRelease(name)} />
                  {name}
                </label>
              ))}
            </div>
            <div className={styles.adhocRow}>
              <input value={adhoc} placeholder="add release branch not in config…"
                onChange={(e) => setAdhoc(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addAdhoc(); } }} />
              <button className="ghost compact" type="button" onClick={addAdhoc}>+ Add</button>
            </div>
          </div>

          {selectedReleases.length > 0 && ruleName.trim() && (
            <p className={styles.help}>
              Working branches:{' '}
              {selectedReleases.map((r) => (
                <code key={r} className={styles.previewBranch}>
                  {[branchPrefix.trim(), r, ruleName.trim()].filter(Boolean).join('/')}
                </code>
              ))}
            </p>
          )}

          <div className={styles.actionsRow}>
            <button
              className={styles.primaryBtn}
              type="button"
              disabled={busy || !canCreate}
              onClick={() => runAction('rule-setup', {
                revision_id: revisionId.trim(),
                rule_name: ruleName.trim(),
                branch_prefix: branchPrefix.trim(),
                releases: selectedReleases,
                workflow_type: 'rule_patch',
              }, '__draft__')}
            >
              Create Rule Run
            </button>
            {status && <span className={styles.help}>{status}</span>}
          </div>
        </div>
        {activeJob && (
          <LogDrawer run={run} releaseId={selectedId} activeJob={activeJob} defaultLogKey="" />
        )}
      </div>
    );
  }

  // --- No selection -------------------------------------------------------
  if (!selectedId || !run) {
    return (
      <div className={styles.view}>
        <div className={`panel ${styles.ruleCard}`}>
          <p className="eyebrow">Rule Patch</p>
          <h3>Rule Validation Matrix</h3>
          <p className={styles.help} style={{ marginTop: 8 }}>
            Select a rule run or click “+ New” to validate a rule CR across releases.
          </p>
        </div>
      </div>
    );
  }

  // --- Existing run: matrix ------------------------------------------------
  const passed = releases.filter((e) => e.status === 'completed').length;
  const anyFailed = releases.some((e) => e.status === 'failed');
  const verdict = anyFailed
    ? `${releases.length - passed} failed`
    : passed === releases.length && releases.length > 0
      ? 'all releases validated'
      : `${passed}/${releases.length} validated`;

  const runValidate = (entry: ReleaseMatrixEntry, dry: boolean) =>
    runAction('rule-release', {
      release: entry.release_branch,
      dry_run: dry,
      confirm_text: confirmText,
    }, selectedId);

  const triggerSim = (entry: ReleaseMatrixEntry, dry: boolean) =>
    runAction('rule-sim', {
      release: entry.release_branch,
      dry_run: dry,
      confirm_text: confirmText,
    }, selectedId);

  const runAll = async () => {
    for (const entry of releases) {
      // eslint-disable-next-line no-await-in-loop
      await runValidate(entry, false);
    }
  };

  const removeRelease = (entry: ReleaseMatrixEntry) => {
    if (!spec) return;
    const remaining = releases.map((e) => e.release_branch).filter((r) => r !== entry.release_branch);
    if (remaining.length === 0) { setStatus('A run needs at least one release.'); return; }
    runAction('rule-setup', {
      revision_id: spec.revision_id,
      rule_name: spec.rule_name,
      branch_prefix: spec.branch_prefix ?? '',
      releases: remaining,
      workflow_type: 'rule_patch',
    }, selectedId);
  };

  const addReleaseToRun = () => {
    if (!spec) return;
    const name = adhoc.trim();
    if (!name) return;
    const next = Array.from(new Set([...releases.map((e) => e.release_branch), name]));
    setAdhoc('');
    runAction('rule-setup', {
      revision_id: spec.revision_id,
      rule_name: spec.rule_name,
      branch_prefix: spec.branch_prefix ?? '',
      releases: next,
      workflow_type: 'rule_patch',
    }, selectedId);
  };

  return (
    <div className={styles.view}>
      <div className={`panel ${styles.ruleCard}`}>
        <div className={styles.headerRow}>
          <div>
            <p className="eyebrow">Rule Patch</p>
            <h3>{spec?.rule_name ?? '(rule)'} <span className={styles.rev}>CR{spec?.revision_id}</span></h3>
          </div>
          <span className={`chip ${anyFailed ? 'failed' : passed === releases.length ? 'done' : ''}`}>
            {verdict}
          </span>
        </div>

        <div className={styles.tableWrap}>
          <table className={styles.matrix}>
            <thead>
              <tr>
                <th>Release</th>
                <th>Working branch</th>
                <th>Test CR</th>
                <th title="branch prep / dcl patch / dcl diff">B · P · D</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {releases.map((entry) => (
                <tr key={entry.release_branch}>
                  <td>{entry.release_branch}</td>
                  <td><code className={styles.branchCell}>{entry.working_branch}</code></td>
                  <td>{entry.test_cr_revision
                    ? <span className="chip">CR{entry.test_cr_revision}</span>
                    : <span className={styles.muted}>—</span>}</td>
                  <td className={styles.steps}>
                    {stepState(entry.branch_prep)} {stepState(entry.dcl_patch)} {stepState(entry.dcl)}
                  </td>
                  <td><span className={`chip ${statusChipClass(entry.status)}`}>{entry.status ?? 'pending'}</span></td>
                  <td className={styles.rowActions}>
                    <button className="ghost compact" type="button" disabled={busy}
                      onClick={() => runValidate(entry, true)}>Dry</button>
                    <button className={styles.smallDanger} type="button" disabled={busy}
                      onClick={() => runValidate(entry, false)}>Validate</button>
                    <button className="ghost compact" type="button" disabled={busy || !entry.test_cr_revision}
                      onClick={() => triggerSim(entry, false)}>Sim</button>
                    <button className={styles.removeBtn} type="button" disabled={busy}
                      title="Remove release" onClick={() => removeRelease(entry)}>×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className={styles.footerRow}>
          <button className={styles.primaryBtn} type="button" disabled={busy} onClick={runAll}>
            Run all validate
          </button>
          <div className={styles.adhocRow}>
            <input value={adhoc} placeholder="add a release to this run…"
              onChange={(e) => setAdhoc(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addReleaseToRun(); } }} />
            <button className="ghost compact" type="button" disabled={busy} onClick={addReleaseToRun}>+ Add</button>
          </div>
        </div>

        <div className={styles.confirmCard}>
          <span className={styles.help}>Real actions require confirm text = <b>{selectedId}</b></span>
          <input className={styles.confirmInput} placeholder={selectedId ?? 'release_id'}
            value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
          {status && <span className={styles.help}>{status}</span>}
        </div>
      </div>

      {activeJob && (
        <LogDrawer run={run} releaseId={selectedId} activeJob={activeJob} defaultLogKey="" />
      )}
    </div>
  );
}
