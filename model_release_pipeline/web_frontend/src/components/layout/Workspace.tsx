import type { ReactNode } from 'react';
import type { ViewName } from './SideRail';
import type { RunSummary } from '../../types/api';
import styles from './Workspace.module.css';

interface WorkspaceProps {
  activeView: ViewName;
  selectedRun: RunSummary | null;
  workflowContent: ReactNode;
  releaseContent: ReactNode;
  drawerOpen: boolean;
  onCloseDrawer: () => void;
}

export default function Workspace({
  activeView,
  selectedRun,
  workflowContent,
  releaseContent,
  drawerOpen,
  onCloseDrawer,
}: WorkspaceProps) {
  return (
    <>
      <div
        className={`${styles.backdrop} ${drawerOpen ? styles.backdropVisible : ''}`}
        onClick={onCloseDrawer}
      />
      <section className={styles.board}>
        <section className={styles.header} aria-hidden="true">
          <div>
            <p className="eyebrow">Current Agent State</p>
            <h2>{selectedRun ? selectedRun.release_id : 'Select a run'}</h2>
            <p className="muted">
              {selectedRun
                ? selectedRun.experiment_name
                : 'Timeline, artifacts, and logs will appear here.'}
            </p>
          </div>
          {selectedRun && (
            <div className={styles.headerBadges}>
              <span className={`chip ${selectedRun.status}`}>{selectedRun.stage}</span>
              {selectedRun.selected_epoch != null && (
                <span className="chip">epoch {selectedRun.selected_epoch}</span>
              )}
            </div>
          )}
        </section>

        <div
          className={`${styles.viewPane} ${activeView === 'workflow' ? styles.viewPaneActive : ''}`}
        >
          {workflowContent}
        </div>

        <div
          className={`${styles.viewPane} ${activeView === 'release' ? styles.viewPaneActive : ''}`}
        >
          {releaseContent}
        </div>
      </section>
    </>
  );
}
