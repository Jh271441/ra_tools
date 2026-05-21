import { useState, useEffect, useMemo, useCallback } from 'react';
import type { ReactNode } from 'react';
import type { GetRunResponse, ActionSpec, BranchInfo, StageConfig, StepStatus } from '../../types/api';
import {
  getConfigBranches,
  getLubanHosts,
  getOffboardTestYamls,
  getStageDefaults,
} from '../../api/client';
import { getFlowItems } from './flowItems';
import FlowControls from './FlowControls';
import FlowInspector from './FlowInspector';
import LogDrawer from '../logs/LogDrawer';
import styles from './WorkflowView.module.css';

interface WorkflowViewProps {
  selectedId: string | null;
  run: GetRunResponse | null;
  onJobStarted: (jobId: string) => void;
}

export default function WorkflowView({ selectedId, run, onJobStarted }: WorkflowViewProps) {
  const [activeStep, setActiveStep] = useState('pick');
  const [lubanHost, setLubanHost] = useState('');
  const [branches, setBranches] = useState<BranchInfo[]>([]);
  const [stageDefaults, setStageDefaults] = useState<StageConfig>({});
  const [offboardYamls, setOffboardYamls] = useState<string[]>([]);
  const [confirmText, setConfirmText] = useState('');
  const [confirmStatus, setConfirmStatus] = useState('');

  useEffect(() => {
    getConfigBranches().then((r) => setBranches(r.branches)).catch(() => {});
    getStageDefaults().then((r) => setStageDefaults(r.stage_defaults)).catch(() => {});
    getOffboardTestYamls().then((r) => setOffboardYamls(r.yamls.map((y) => y.name))).catch(() => {});
    getLubanHosts().then((r) => setLubanHost(r.default_host)).catch(() => {});
  }, []);

  const handleSelectStep = useCallback((step: string) => {
    setActiveStep(step);
    setConfirmText('');
    setConfirmStatus('');
  }, []);

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

  if (!selectedId) {
    return (
      <div className={styles.workflowView}>
        <div className={`panel ${styles.flowCard}`}>
          <p className="eyebrow">Operator Workflow</p>
          <h3>Release Flow Controls</h3>
          <p className="muted" style={{ marginTop: 8 }}>
            Select a release run from the sidebar to start.
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
              onLubanHostChange={setLubanHost}
              onJobStarted={onJobStarted}
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

      <LogDrawer run={run} releaseId={selectedId} />
    </div>
  );
}
