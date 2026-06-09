import { useState, useEffect, useMemo, useCallback } from 'react';
import type { ReactNode } from 'react';
import type { GetRunResponse, ActionSpec, BranchInfo, OffboardTestYamlEntry, StageConfig, StepStatus } from '../../types/api';
import {
  getConfigBranches,
  getLubanHosts,
  getOffboardTestYamls,
  getStageDefaults,
} from '../../api/client';
import { getFlowItems, filterFlowGroups, NEXT_STEP_BY_ACTION, STEP_LOG_MAP } from './flowItems';
import { getTemplate } from './workflowTemplates';
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
  workflowType: string;
}

export default function WorkflowView({ selectedId, run, draftRun = false, onRunRefresh, workflowType }: WorkflowViewProps) {
  const [activeStep, setActiveStep] = useState('export');
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
    // Draft action completed — signal App to refresh and auto-select the newest run
    const isDraftCreate = !selectedId && activeJob.status === 'completed' && !activeJob.dry_run
      && ['pick', 'export', 'offboard'].includes(activeJob.action);
    onRunRefresh(isDraftCreate ? '__draft__' : undefined);
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
    setConfirmStatus('');
  }, []);

  // Auto-switch LogDrawer log channel when step changes
  const defaultLogKey = useMemo(() => STEP_LOG_MAP[activeStep] ?? '', [activeStep]);

  const template = useMemo(() => getTemplate(workflowType), [workflowType]);
  const allGroups = useMemo(() => getFlowItems(run?.summary ?? null), [run]);
  const groups = useMemo(() => filterFlowGroups(allGroups, template.includedSteps), [allGroups, template]);

  // Clamp activeStep to the current template's included steps
  useEffect(() => {
    if (!template.includedSteps.includes(activeStep)) {
      setActiveStep(template.includedSteps[0] ?? 'export');
    }
  }, [template, activeStep]);

  const statusByStep = useMemo<Record<string, StepStatus>>(() => {
    if (!run?.timeline) return {};
    return Object.fromEntries(run.timeline.map((s) => [s.key, s.status]));
  }, [run]);

  const activeItem = useMemo(() => {
    const all = [...groups.shared, ...groups.onboard, ...groups.offboard];
    return all.find((i) => i.key === activeStep) ?? all[0];
  }, [groups, activeStep]);

  const DEFAULT_ACTIONS: ActionSpec[] = [
    { key: 'branch-prep',     label: 'Branch Prep',         supports_dry_run: true,  requires_confirm: true,  needs_run_id: true  },
    { key: 'dcl-patch',       label: 'DCL Patch Apply',     supports_dry_run: true,  requires_confirm: true,  needs_run_id: true  },
    { key: 'pick',            label: 'Pick Epoch',          supports_dry_run: false, requires_confirm: false, needs_run_id: false },
    { key: 'export',          label: 'Model Export',        supports_dry_run: true,  requires_confirm: true,  needs_run_id: false },
    { key: 'upload',          label: 'Upload ONNX',         supports_dry_run: true,  requires_confirm: true,  needs_run_id: true  },
    { key: 'ifx-convert',     label: 'Trigger IFX Convert', supports_dry_run: true,  requires_confirm: true,  needs_run_id: true  },
    { key: 'ifx-poll',        label: 'Poll IFX Result',     supports_dry_run: false, requires_confirm: false, needs_run_id: true  },
    { key: 'handoff',         label: 'Generate Handoff',    supports_dry_run: false, requires_confirm: false, needs_run_id: true  },
    { key: 'apply-handoff',   label: 'Apply Handoff',       supports_dry_run: true,  requires_confirm: true,  needs_run_id: true  },
    { key: 'dcl',             label: 'Run DCL Diff',        supports_dry_run: true,  requires_confirm: true,  needs_run_id: true  },
    { key: 'sim-plan',        label: 'Trigger Sim Plan',    supports_dry_run: true,  requires_confirm: true,  needs_run_id: true  },
    { key: 'sim-plan-status', label: 'Refresh Sim Plan',    supports_dry_run: false, requires_confirm: false, needs_run_id: true  },
    { key: 'sim-plan-cancel', label: 'Cancel Sim Plan',     supports_dry_run: false, requires_confirm: true,  needs_run_id: true  },
    { key: 'offboard',        label: 'Run Offboard',        supports_dry_run: true,  requires_confirm: true,  needs_run_id: false },
  ];
  const actions = run?.actions ?? (draftRun ? DEFAULT_ACTIONS : []);

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
          <div className={styles.flowHeaderRight}>
            <p className={styles.flowHint}>click a step to inspect<br />actions and logs</p>
          </div>
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
