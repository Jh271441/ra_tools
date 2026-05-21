import type { TimelineStep } from '../../types/api';
import styles from './Timeline.module.css';

function statusClass(status: string): string {
  if (['done', 'completed', 'dry_run'].includes(status)) return styles.done;
  if (status === 'failed') return styles.failed;
  if (status === 'running') return styles.running;
  if (status === 'pending') return styles.pending;
  return '';
}

interface TimelineProps {
  timeline: TimelineStep[];
}

export default function Timeline({ timeline }: TimelineProps) {
  if (timeline.length === 0) {
    return <p className={styles.empty}>No timeline steps.</p>;
  }

  let prevGroup: string | null = null;

  return (
    <div className={styles.timeline}>
      {timeline.map((step, index) => {
        const showSep = step.group && step.group !== prevGroup && prevGroup !== null;
        prevGroup = step.group ?? prevGroup;

        return (
          <div key={step.key}>
            {showSep && (
              <div className={styles.groupSep}>
                <span>Offboard Validation</span>
              </div>
            )}
            <div className={`${styles.step} ${statusClass(step.status)}`}>
              <div className={styles.stepIndex}>{index + 1}</div>
              <div className={styles.stepCard}>
                <div className={styles.stepText}>
                  <h4>{step.title}</h4>
                  <p>{step.description}</p>
                </div>
                <span className={`chip ${step.status} ${styles.stepState}`}>
                  {step.status}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
