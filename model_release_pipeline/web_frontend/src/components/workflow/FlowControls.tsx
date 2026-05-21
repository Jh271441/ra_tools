import type { FlowGroups, FlowItem } from './flowItems';
import type { StepStatus } from '../../types/api';
import styles from './FlowControls.module.css';

function statusClass(status: StepStatus | undefined): string {
  if (!status || status === 'pending' || status === 'missing') return styles.pending;
  if (status === 'done' || status === 'dry_run' || status === 'skipped') return styles.done;
  if (status === 'failed') return styles.failed;
  if (status === 'running' || status === 'ready') return styles.running;
  return '';
}

interface FlowNodeProps {
  item: FlowItem;
  status: StepStatus | undefined;
  selected: boolean;
  onClick: () => void;
}

function FlowNode({ item, status, selected, onClick }: FlowNodeProps) {
  return (
    <button
      type="button"
      className={`${styles.flowNode} ${statusClass(status)} ${selected ? styles.selected : ''}`}
      onClick={onClick}
    >
      <div className={styles.flowTop}>
        <div className={`${styles.flowNumber} ${statusClass(status)}`}>{item.badge}</div>
        <div className={styles.flowText}>
          <h4>{item.shortTitle}</h4>
          <p>{item.note}</p>
        </div>
        <span className={`chip ${status ?? 'pending'} ${styles.flowState}`}>{status ?? 'pending'}</span>
      </div>
    </button>
  );
}

interface FlowControlsProps {
  groups: FlowGroups;
  statusByStep: Record<string, StepStatus>;
  activeStep: string;
  onSelectStep: (key: string) => void;
}

export default function FlowControls({ groups, statusByStep, activeStep, onSelectStep }: FlowControlsProps) {
  return (
    <div className={styles.flowControls}>
      <div className={styles.flowEntryRow}>
        <div className={styles.flowGroup}>
          <div className={styles.flowGroupTitle}>Luban Inspect / Pick</div>
          <div className={styles.flowLane}>
            {groups.shared.map((item) => (
              <FlowNode
                key={item.key}
                item={item}
                status={statusByStep[item.key]}
                selected={activeStep === item.key}
                onClick={() => onSelectStep(item.key)}
              />
            ))}
          </div>
        </div>
        <div className={styles.flowGroup}>
          <div className={styles.flowGroupTitle}>Standalone Offboard</div>
          <div className={styles.flowLane}>
            {groups.offboard.map((item) => (
              <FlowNode
                key={item.key}
                item={item}
                status={statusByStep[item.key]}
                selected={activeStep === item.key}
                onClick={() => onSelectStep(item.key)}
              />
            ))}
          </div>
        </div>
      </div>
      <div className={styles.flowGroupOnboard}>
        <div className={styles.flowGroupTitle}>Onboard</div>
        <div className={styles.flowLaneOnboard}>
          {groups.onboard.map((item) => (
            <FlowNode
              key={item.key}
              item={item}
              status={statusByStep[item.key]}
              selected={activeStep === item.key}
              onClick={() => onSelectStep(item.key)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
