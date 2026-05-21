import { useState } from 'react';
import type { RunSummary } from '../../types/api';
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

export type ViewName = 'workflow' | 'release';

interface SideRailProps {
  activeView: ViewName;
  onViewChange: (view: ViewName) => void;
  runs: RunSummary[];
  selectedId: string | null;
  onSelectRun: (id: string) => void;
  onNewRelease: () => void;
  railCollapsed: boolean;
  onToggleRail: () => void;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  drawerOpen: boolean;
}

export default function SideRail({
  activeView,
  onViewChange,
  runs,
  selectedId,
  onSelectRun,
  onNewRelease,
  railCollapsed,
  onToggleRail,
  sidebarCollapsed,
  onToggleSidebar,
  drawerOpen,
}: SideRailProps) {
  const [filter, setFilter] = useState('');

  const filteredRuns = filter
    ? runs.filter(
        (r) =>
          r.release_id.includes(filter) ||
          (r.experiment_name ?? '').toLowerCase().includes(filter.toLowerCase()),
      )
    : runs;

  const railCls = [
    styles.rail,
    railCollapsed ? styles.collapsed : '',
    sidebarCollapsed ? styles.sidebarCollapsed : '',
    drawerOpen ? styles.drawerOpen : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <aside className={railCls} aria-label="Primary navigation">
      <button
        className={styles.railToggle}
        onClick={onToggleRail}
        title={railCollapsed ? 'Expand toolbar' : 'Collapse toolbar'}
      >
        {railCollapsed ? '›' : '‹'}
      </button>

      <button
        className={`${styles.navItem} ${activeView === 'workflow' ? styles.navItemActive : ''}`}
        onClick={() => onViewChange('workflow')}
        title="Workflow"
      >
        <span className={styles.navIcon}>W</span>
        <span className={styles.navLabel}>Workflow</span>
      </button>

      <button
        className={`${styles.navItem} ${activeView === 'release' ? styles.navItemActive : ''}`}
        onClick={() => onViewChange('release')}
        title="Release Details"
      >
        <span className={styles.navIcon}>D</span>
        <span className={styles.navLabel}>Release Details</span>
        <span
          className={styles.disclosure}
          onClick={(e) => {
            e.stopPropagation();
            onToggleSidebar();
          }}
          title={sidebarCollapsed ? 'Show Release Runs' : 'Hide Release Runs'}
        >
          {sidebarCollapsed ? '›' : '⌄'}
        </span>
      </button>

      <div className={styles.runListSection}>
        <div className={styles.runListHeader}>
          <span>Release Runs</span>
          <button className="ghost compact" onClick={onNewRelease}>
            + New Release
          </button>
        </div>
        <input
          className={styles.filterInput}
          placeholder="Filter run / experiment"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <div className={styles.runsList}>
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
          {filteredRuns.length === 0 && (
            <p className="muted" style={{ fontSize: '0.85rem', padding: 8 }}>
              {filter ? 'No matching runs.' : 'No release runs yet.'}
            </p>
          )}
        </div>
      </div>
    </aside>
  );
}
