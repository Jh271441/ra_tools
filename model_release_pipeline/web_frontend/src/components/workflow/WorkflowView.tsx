import { useState, useEffect, useMemo, useCallback } from 'react';
import type { ReactNode } from 'react';
import type { GetRunResponse, ActionSpec, BranchInfo, OffboardTestYamlEntry, StageConfig, StepStatus } from '../../types/api';
import {
  getConfigBranches,
  getLubanHosts,
  getOffboardTestYamls,
  getStageDefaults,
} from '../../api/client';
import { getFlowItems, NEXT_STEP_BY_ACTION, STEP_LOG_MAP } from './flowItems';
import { useJobPoller } from '../../hooks/useJobPoller';
import FlowControls from './FlowControls';
import FlowInspector from './FlowInspector';
import LogDrawer from '../logs/LogDrawer';
import styles from './WorkflowView.module.css';

interface WorkflowViewProps {
  selectedId: string | null;
  run: GetRunResponse | null;
  draftRun?: boolean;
  onRunRefresh: (newReleaseId?: string) => void;
}

export default function WorkflowView({ selectedId, run, draftRun = false, onRunRefresh }: WorkflowViewProps) {
  const [activeStep, setActiveStep] = useState('pick');
  const [lubanHost, setLubanHost] = useState('');
  const [branches, setBranches] = useState<BranchInfo[]>([]);
  const [stageDefaults, setStageDefaults] = useState<StageConfig>({});
  const [offboardYamls, setOffboardYamls] = useState<OffboardTestYamlEntry[]>([]);
  const [lubanHosts, setLubanHosts] = useState<string[]>([]);
  const [pickPreviewLines, setPickPreviewLines] = useState<string[] | null>(null);
  const [confirmText, setConfirmText] = useState('');
  const [confirmStatus, setConfirmStatus] = useState('');

  const { activeJob, trackJob } = useJobPoller();

  useEffect(() => {
    getConfigBranches().then((r) => setBranches(r.branches)).catch(() => {});
    getStageDefaults().then((r) => setStageDefaults(r.stage_defaults)).catch(() => {});
    getOffboardTestYamls().then((r) => setOffboardYamls(r.yamls)).catch(() => {});
    getLubanHosts().then((r) => { setLubanHost(r.default_host); setLubanHosts(r.hosts); }).catch(() => {});
  }, []);

  // When job finishes: refresh run data and optionally auto-advance step
  useEffect(() => {
    if (!activeJob || activeJob.status === 'running') return;
    // In draft mode with a real completed job, pass the new release_id so App can auto-select it
    const newId =
      !selectedId && activeJob.status === 'completed' && !activeJob.dry_run
        ? activeJob.release_id
        : undefined;
    onRunRefresh(newId);
    if (activeJob.status === 'completed' && !activeJob.dry_run) {
      const next = NEXT_STEP_BY_ACTION[activeJob.action];
      if (next) setActiveStep(next);
    }
  }, [activeJob?.status, activeJob?.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleJobStarted = useCallback((jobId: string) => {
    trackJob(jobId);
  }, [trackJob]);

  const handleSelectStep = useCallback((step: string) => {
    setActiveStep(step);
    setConfirmText('');
    setConfirmStatus('');
  }, []);

  // Auto-switch LogDrawer log channel when step changes
  const defaultLogKey = useMemo(() => STEP_LOG_MAP[activeStep] ?? '', [activeStep]);

  const groups = useMemo(() => getFlowItems(run?.summary ?? null), [run]);

  const statusByStep = useMemo<Record<string, StepStatus>>(() => {
    if (!run?.timeline) return {};
    return Object.fromEntries(run.timeline.map((s) => [s.key, s.status]));
  }, [run]);

  const activeItem = useMemo(() => {
    const all = [...groups.shared, ...groups.onboard, ...groups.offboard];
    return all.find((i) => i.key === activeStep) ?? all[0];
  }, [groups, activeStep]);

  const actions = run?.actions ?? [];

  const itemActions = useMemo(() => {
    if (!activeItem) return [];
    return activeItem.actionKeys
      .map((key) => actions.find((a) => a.key === key))
      .filter(Boolean) as ActionSpec[];
  }, [activeItem, actions]);

  const confirmPlaceholder = useMemo(() => {
    if (!itemActions.some((a) => a.requires_confirm)) return 'no confirmation required';
    if (itemActions.every((a) => a.key === 'export')) return 'EXPORT';
    if (itemActions.every((a) => a.key === 'offboard')) return 'OFFBOARD';
    return selectedId ?? 'release_id';
  }, [itemActions, selectedId]);

  const confirmDescription = useMemo((): ReactNode => {
    if (!itemActions.some((a) => a.requires_confirm)) return 'No backend job for selected release.';
    if (itemActions.every((a) => a.key === 'export')) return <>Real export requires <b>EXPORT</b>.</>;
    return <>Real actions require current <b>release_id</b>.</>;
  }, [itemActions]);

  if (!selectedId && !draftRun) {
    return (
      <div className={styles.workflowView}>
        <div className={`panel ${styles.flowCard}`}>
          <p className="eyebrow">Operator Workflow</p>
          <h3>Release Flow Controls</h3>
          <p className="muted" style={{ marginTop: 8 }}>
            Select a release run or click "+ New Release" to start.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.workflowView}>
      <div className={`panel ${styles.flowCard}`}>
        <div className={styles.flowHeader}>
          <div>
            <p className="eyebrow">Operator Workflow</p>
            <h3>Release Flow Controls</h3>
          </div>
          <p className={styles.flowHint}>click a step to inspect<br />actions and logs</p>
        </div>
        <FlowControls
          groups={groups}
          statusByStep={statusByStep}
          activeStep={activeStep}
          onSelectStep={handleSelectStep}
        />
        <div className={styles.detailGrid}>
          {activeItem && (
            <FlowInspector
              item={activeItem}
              status={statusByStep[activeStep] ?? 'pending'}
              actions={actions}
              run={run}
              releaseId={selectedId}
              branches={branches}
              stageDefaults={stageDefaults}
              offboardYamls={offboardYamls}
              lubanHost={lubanHost}
              lubanHosts={lubanHosts}
              onLubanHostChange={setLubanHost}
              onPickPreview={setPickPreviewLines}
              onJobStarted={handleJobStarted}
              confirmText={confirmText}
              onConfirmChange={setConfirmText}
              onStatusChange={setConfirmStatus}
            />
          )}
          <div className={styles.confirmCard}>
            <h4 className={styles.confirmTitle}>Action Confirmation</h4>
            <p className={styles.confirmHelperText}>{confirmDescription}</p>
            <input
              className={styles.confirmInput}
              placeholder={confirmPlaceholder}
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
            />
            {confirmStatus && (
              <p className={styles.confirmHelperText} style={{ marginTop: 6 }}>{confirmStatus}</p>
            )}
          </div>
        </div>
      </div>

      <LogDrawer
        run={run}
        releaseId={selectedId}
        activeJob={activeJob}
        pickPreviewLines={pickPreviewLines}
        defaultLogKey={defaultLogKey}
      />
    </div>
  );
}
