import { useCallback, useState } from 'react';
import TopBar from './components/layout/TopBar';
import SideRail from './components/layout/SideRail';
import type { ViewName } from './components/layout/SideRail';
import Workspace from './components/layout/Workspace';
import Timeline from './components/details/Timeline';
import ReleaseDetails from './components/details/ReleaseDetails';
import WorkflowView from './components/workflow/WorkflowView';
import { useRuns, useRun } from './hooks/useRuns';
import { useResponsive } from './hooks/useResponsive';
import styles from './App.module.css';

export default function App() {
  const { data: runsData, refresh } = useRuns();
  const { isMobileOrTablet } = useResponsive();

  const [activeView, setActiveView] = useState<ViewName>('workflow');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const runs = runsData?.runs ?? [];
  const selectedRun = runs.find((r) => r.release_id === selectedId) ?? null;
  const { data: runDetail, loading: runLoading, refresh: refreshRun } = useRun(selectedId);

  const handleToggleDrawer = useCallback(() => {
    if (isMobileOrTablet) {
      setDrawerOpen((v) => !v);
    } else {
      setRailCollapsed((v) => !v);
    }
  }, [isMobileOrTablet]);

  const handleSelectRun = useCallback(
    (id: string) => {
      setSelectedId(id);
      if (isMobileOrTablet) setDrawerOpen(false);
    },
    [isMobileOrTablet],
  );

  const handleViewChange = useCallback(
    (view: ViewName) => {
      setActiveView(view);
      if (isMobileOrTablet) setDrawerOpen(false);
    },
    [isMobileOrTablet],
  );

  const handleJobStarted = useCallback(
    (_jobId: string) => {
      setTimeout(() => { refreshRun(); }, 3000);
    },
    [refreshRun],
  );

  return (
    <div className={styles.shell}>
      <TopBar
        runsDir={runsData?.runs_dir ?? ''}
        drawerOpen={drawerOpen}
        onToggleDrawer={handleToggleDrawer}
        onRefresh={refresh}
      />

      <main style={{ flex: '1 1 auto', display: 'flex', minHeight: 0, overflow: 'hidden' }}>
        <SideRail
          activeView={activeView}
          onViewChange={handleViewChange}
          runs={runs}
          selectedId={selectedId}
          onSelectRun={handleSelectRun}
          onNewRelease={() => {}}
          railCollapsed={railCollapsed}
          onToggleRail={() => setRailCollapsed((v) => !v)}
          sidebarCollapsed={sidebarCollapsed}
          onToggleSidebar={() => setSidebarCollapsed((v) => !v)}
          drawerOpen={drawerOpen}
        />

        <Workspace
          activeView={activeView}
          selectedRun={selectedRun}
          drawerOpen={drawerOpen}
          onCloseDrawer={() => setDrawerOpen(false)}
          workflowContent={
            <WorkflowView
              selectedId={selectedId}
              run={runDetail}
              onJobStarted={handleJobStarted}
            />
          }
          releaseContent={
            selectedRun ? (
              runLoading ? (
                <div className="panel" style={{ padding: 20 }}>
                  <p className="muted">Loading details…</p>
                </div>
              ) : runDetail ? (
                <div className={styles.releaseView}>
                  <section className={`panel ${styles.timelineCard}`}>
                    <div className={styles.sectionHeading}>
                      <h3>Agent Timeline</h3>
                      <span>read-only release history</span>
                    </div>
                    <div className={styles.timelineScroll}>
                      <Timeline timeline={runDetail.timeline} />
                    </div>
                  </section>
                  <aside className={`panel ${styles.detailPanel}`}>
                    <div className={styles.panelTitle}>
                      <span>Decision Panel</span>
                      <button
                        className="ghost compact"
                        onClick={() => {
                          navigator.clipboard.writeText(
                            JSON.stringify(runDetail.record, null, 2),
                          );
                        }}
                      >
                        Copy JSON
                      </button>
                    </div>
                    <div className={styles.detailScroll}>
                      <ReleaseDetails data={runDetail} />
                    </div>
                  </aside>
                </div>
              ) : (
                <div className="panel" style={{ padding: 20 }}>
                  <p className="muted">Failed to load run details.</p>
                </div>
              )
            ) : (
              <div className="panel" style={{ padding: 20 }}>
                <h3>Agent Timeline</h3>
                <p className="muted" style={{ marginTop: 8 }}>
                  Select a release run to see details.
                </p>
              </div>
            )
          }
        />
      </main>
    </div>
  );
}
