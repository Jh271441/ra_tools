import styles from './TopBar.module.css';

interface TopBarProps {
  runsDir: string;
  drawerOpen: boolean;
  onToggleDrawer: () => void;
  onRefresh: () => void;
}

export default function TopBar({ runsDir, drawerOpen, onToggleDrawer, onRefresh }: TopBarProps) {
  return (
    <header className={styles.topbar}>
      <button
        className={`${styles.mobileToggle} ${drawerOpen ? styles.open : ''}`}
        aria-label={drawerOpen ? 'Close navigation' : 'Open navigation'}
        aria-expanded={drawerOpen}
        onClick={onToggleDrawer}
      >
        <span className={styles.hamburger} aria-hidden="true" />
      </button>

      <div className={styles.brand}>
        <div className={styles.brandMark}>RA</div>
        <div>
          <p className="eyebrow">Model Release Pipeline</p>
          <h1>Scenario DNN Release Agent</h1>
        </div>
      </div>

      <div className={styles.actions}>
        <button className={`ghost ${styles.refreshBtn}`} onClick={onRefresh}>
          Refresh
        </button>
        <div className="status-pill" title={runsDir}>
          runs_dir: {runsDir || 'loading'}
        </div>
      </div>
    </header>
  );
}
