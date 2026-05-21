import { useEffect, useState, useMemo } from 'react';
import type { GetRunResponse, Job, LogKey } from '../../types/api';
import { LOG_LABELS } from '../workflow/flowItems';
import styles from './LogDrawer.module.css';

const ExpandIcon = () => (
  <svg width="15" height="15" viewBox="0 0 15 15" fill="none" aria-hidden>
    <path d="M1 5.5V1h4.5M9.5 1H14v4.5M14 9.5V14H9.5M5.5 14H1V9.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const CollapseIcon = () => (
  <svg width="15" height="15" viewBox="0 0 15 15" fill="none" aria-hidden>
    <path d="M5.5 1v4.5H1M14 5.5H9.5V1M9.5 14V9.5H14M1 9.5h4.5V14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const ChevronDown = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
    <path d="M2 4.5l5 5 5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const ChevronUp = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
    <path d="M2 9.5l5-5 5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

const SPECIAL_LABELS: Record<string, string> = {
  __job__: 'Backend job',
  __pick_preview__: 'Pick preview',
};

interface LogDrawerProps {
  run: GetRunResponse | null;
  releaseId: string | null;
  activeJob?: Job | null;
  pickPreviewLines?: string[] | null;
  defaultLogKey?: string;
}

export default function LogDrawer({
  run,
  releaseId: _releaseId,
  activeJob,
  pickPreviewLines,
  defaultLogKey,
}: LogDrawerProps) {
  const [open, setOpen] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const [selectedLog, setSelectedLog] = useState('');

  const logs = run?.logs;

  const logKeys = useMemo(() => {
    if (!logs) return [] as LogKey[];
    return (Object.keys(logs) as LogKey[]).filter((k) => logs[k].length > 0);
  }, [logs]);

  // special channels prepended
  const allKeys = useMemo(() => [
    ...(activeJob ? ['__job__'] : []),
    ...(pickPreviewLines?.length ? ['__pick_preview__'] : []),
    ...logKeys,
  ], [activeJob, pickPreviewLines, logKeys]);

  // auto-switch to __job__ when a new job starts
  useEffect(() => {
    if (activeJob?.job_id) {
      setSelectedLog('__job__');
      setOpen(true);
    }
  }, [activeJob?.job_id]);

  // auto-switch to relevant log when step changes (only if not watching a job)
  useEffect(() => {
    if (!defaultLogKey || activeJob) return;
    if (allKeys.includes(defaultLogKey)) setSelectedLog(defaultLogKey);
  }, [defaultLogKey]); // intentionally omit allKeys/activeJob to avoid over-firing

  const effectiveKey = allKeys.includes(selectedLog) ? selectedLog : (allKeys[0] ?? '');

  const content = useMemo(() => {
    if (effectiveKey === '__job__') return activeJob?.log.join('\n') ?? '';
    if (effectiveKey === '__pick_preview__') return pickPreviewLines?.join('\n') ?? '';
    if (!logs || !effectiveKey) return '';
    return logs[effectiveKey as LogKey]?.join('\n') ?? '';
  }, [effectiveKey, activeJob, pickPreviewLines, logs]);

  const labelFor = (k: string) =>
    SPECIAL_LABELS[k] ?? LOG_LABELS[k] ?? k;

  const drawerClass = [
    'panel',
    styles.logDrawer,
    open ? styles.logDrawerOpen : '',
    fullscreen ? styles.logDrawerFullscreen : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={drawerClass}>
      <div className={`${styles.logSummary} ${open ? styles.logSummaryBorder : ''}`}>
        {/* Left: title — clicking toggles the drawer */}
        <div
          className={styles.logTitleArea}
          role="button"
          tabIndex={0}
          onClick={() => setOpen((v) => !v)}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setOpen((v) => !v); }}
        >
          <p className="eyebrow">Execution Console</p>
          <h3 className={styles.logHeading}>Live Backend Logs</h3>
          {activeJob && (
            <span className={`chip ${activeJob.status} ${styles.jobChip}`}>
              {activeJob.label} · {activeJob.status}
              {activeJob.dry_run ? ' / dry-run' : ''}
              {activeJob.returncode != null ? ` · rc=${activeJob.returncode}` : ''}
            </span>
          )}
        </div>

        {/* Right: controls */}
        <div className={styles.logActions}>
          {open && allKeys.length > 0 && (
            <select
              className={styles.logSelect}
              value={effectiveKey}
              onChange={(e) => setSelectedLog(e.target.value)}
              onClick={(e) => e.stopPropagation()}
            >
              {allKeys.map((k) => (
                <option key={k} value={k}>{labelFor(k)}</option>
              ))}
            </select>
          )}
          <button
            className={styles.logIconBtn}
            type="button"
            title={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
            onClick={(e) => { e.stopPropagation(); setFullscreen((v) => !v); }}
          >
            {fullscreen ? <CollapseIcon /> : <ExpandIcon />}
          </button>
          <button
            className={styles.logIconBtn}
            type="button"
            title={open ? 'Collapse' : 'Expand'}
            onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
          >
            {open ? <ChevronUp /> : <ChevronDown />}
          </button>
        </div>
      </div>

      {open && (
        <pre className={styles.logOutput}>
          {content || '(no log content)'}
        </pre>
      )}
    </div>
  );
}
