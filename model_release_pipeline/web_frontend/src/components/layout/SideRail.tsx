import { useState } from 'react';
import type { RunSummary } from '../../types/api';
import { WORKFLOW_TEMPLATES } from '../workflow/workflowTemplates';
import styles from './SideRail.module.css';

function statusClass(status: string | undefined): string {
  if (!status) return '';
  if (['failed', 'export_failed', 'offboard_failed'].includes(status)) return 'failed';
  if (['done', 'completed', 'ok'].includes(status)) return 'done';
  return status.replace(/[^a-z0-9_-]/gi, '');
}

function formatEpoch(val: number | null | undefined): string {
  if (val == null) return 'NA';
  return String(Number(val)).padStart(3, '0');
}

const TEMPLATE_BADGE: Record<string, string> = {
  full_release: 'MR',
  rule_patch: 'RP',
  offboard_only: 'OB',
};

interface SideRailProps {
  runs: RunSummary[];
  selectedId: string | null;
  onSelectRun: (id: string) => void;
  onNewRelease: (workflowType: string) => void;
  draftRun?: boolean;
  draftWorkflowType?: string;
  activeWorkflowType: string;
  onWorkflowTypeChange: (id: string) => void;
  railCollapsed: boolean;
  onToggleRail: () => void;
  drawerOpen: boolean;
}

interface WorkflowSectionProps {
  templateId: string;
  templateName: string;
  badge: string;
  runs: RunSummary[];
  selectedId: string | null;
  onSelectRun: (id: string) => void;
  onNewRelease: () => void;
  draftRun: boolean;
  draftActive: boolean;
  expanded: boolean;
  onToggle: () => void;
  railCollapsed: boolean;
}

function WorkflowSection({
  templateName,
  badge,
  runs,
  selectedId,
  onSelectRun,
  onNewRelease,
  draftRun,
  draftActive,
  expanded,
  onToggle,
  railCollapsed,
}: WorkflowSectionProps) {
  const [filter, setFilter] = useState('');

  const filteredRuns = filter
    ? runs.filter(
        (r) =>
          r.release_id.includes(filter) ||
          (r.experiment_name ?? '').toLowerCase().includes(filter.toLowerCase()),
      )
    : runs;

  return (
    <div className={`${styles.workflowSection} ${expanded ? styles.workflowSectionExpanded : ''}`}>
      <button
        className={`${styles.sectionHeader} ${expanded ? styles.sectionHeaderActive : ''}`}
        onClick={onToggle}
        title={templateName}
      >
        <span className={styles.navIcon}>{badge}</span>
        {!railCollapsed && (
          <>
            <span className={styles.navLabel}>{templateName}</span>
            <span className={`${styles.disclosure} ${expanded ? '' : styles.disclosureCollapsed}`} />
          </>
        )}
      </button>

      {expanded && !railCollapsed && (
        <div className={styles.sectionBody}>
          <div className={styles.runListHeader}>
            <button className="ghost compact" onClick={onNewRelease}>
              + New
            </button>
          </div>
          <input
            className={styles.filterInput}
            placeholder="Filter run / experiment"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <div className={styles.runsList}>
            {draftRun && draftActive && (
              <button
                className={[styles.runItem, styles.runItemDraft, !selectedId ? styles.runItemActive : ''].filter(Boolean).join(' ')}
                onClick={onNewRelease}
              >
                <div className={styles.runId}>New draft</div>
                <div className={styles.runName}>Waiting for pick…</div>
                <div className={styles.runMeta}>
                  <span className="chip">pending</span>
                </div>
              </button>
            )}
            {filteredRuns.map((run) => (
              <button
                key={run.release_id}
                className={`${styles.runItem} ${selectedId === run.release_id ? styles.runItemActive : ''}`}
                onClick={() => onSelectRun(run.release_id)}
              >
                <div className={styles.runId}>{run.release_id}</div>
                <div className={styles.runName}>{run.experiment_name || '(no experiment)'}</div>
                <div className={styles.runMeta}>
                  <span className={`chip ${statusClass(run.stage || run.status)}`}>{run.stage || 'created'}</span>
                  <span className="chip">epoch {formatEpoch(run.selected_epoch)}</span>
                  <span className="chip">onnx {run.onnx_version ?? 'NA'}</span>
                  <span className="chip">ifx {run.ifx_platforms ?? 0}</span>
                </div>
              </button>
            ))}
            {filteredRuns.length === 0 && !draftActive && (
              <p className="muted" style={{ fontSize: '0.85rem', padding: 8 }}>
                {filter ? 'No matching runs.' : 'No runs yet.'}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function SideRail({
  runs,
  selectedId,
  onSelectRun,
  onNewRelease,
  draftRun = false,
  draftWorkflowType = 'full_release',
  activeWorkflowType,
  onWorkflowTypeChange,
  railCollapsed,
  onToggleRail,
  drawerOpen,
}: SideRailProps) {
  const railCls = [
    styles.rail,
    railCollapsed ? styles.collapsed : '',
    drawerOpen ? styles.drawerOpen : '',
  ]
    .filter(Boolean)
    .join(' ');

  const handleSectionToggle = (templateId: string) => {
    if (activeWorkflowType === templateId) {
      // clicking the already-active section header just collapses
      // but we keep it active; just collapse visually by doing nothing special —
      // user can click again to re-expand
      return;
    }
    onWorkflowTypeChange(templateId);
  };

  return (
    <aside className={railCls} aria-label="Primary navigation">
      <button
        className={styles.railToggle}
        onClick={onToggleRail}
        title={railCollapsed ? 'Expand toolbar' : 'Collapse toolbar'}
      >
        {railCollapsed ? '›' : '‹'}
      </button>

      <div className={styles.workflowList}>
        {WORKFLOW_TEMPLATES.map((tmpl) => {
          const badge = TEMPLATE_BADGE[tmpl.id] ?? tmpl.id.slice(0, 2).toUpperCase();
          const sectionRuns = runs.filter(
            (r) => (r.workflow_type ?? 'full_release') === tmpl.id,
          );
          return (
            <WorkflowSection
              key={tmpl.id}
              templateId={tmpl.id}
              templateName={tmpl.name}
              badge={badge}
              runs={sectionRuns}
              selectedId={selectedId}
              onSelectRun={(id) => {
                onWorkflowTypeChange(tmpl.id);
                onSelectRun(id);
              }}
              onNewRelease={() => onNewRelease(tmpl.id)}
              draftRun={draftRun}
              draftActive={draftWorkflowType === tmpl.id}
              expanded={activeWorkflowType === tmpl.id}
              onToggle={() => handleSectionToggle(tmpl.id)}
              railCollapsed={railCollapsed}
            />
          );
        })}
      </div>
    </aside>
  );
}
