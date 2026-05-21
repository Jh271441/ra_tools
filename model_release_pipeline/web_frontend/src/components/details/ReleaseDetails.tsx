import { useState } from 'react';
import type { GetRunResponse } from '../../types/api';
import { copyVersionedOnnx } from '../../api/client';
import styles from './ReleaseDetails.module.css';

function formatEpoch(val: number | null | undefined): string {
  if (val == null) return 'N/A';
  return Number.isInteger(val) ? String(val) : Number(val).toFixed(1);
}

interface ReleaseDetailsProps {
  data: GetRunResponse;
}

export default function ReleaseDetails({ data }: ReleaseDetailsProps) {
  const { record, summary, commands, metric_table, versioned_onnx } = data;
  const ifx = record.ifx ?? {};
  const mapping = ifx.ifx_mapping ?? {};
  const apply = record.apply_handoff ?? {};
  const errors = record.errors ?? [];
  const copyInfo = versioned_onnx as Record<string, unknown> | undefined;

  return (
    <div className={styles.details}>
      <DetailBlock title="Release">
        <KV label="stage" value={`${summary.stage ?? 'NA'} / ${summary.status ?? 'NA'}`} />
        <KV label="experiment" value={summary.experiment_name || 'NA'} />
        <KV
          label="epoch"
          value={`${formatEpoch(summary.selected_epoch)} (${summary.selection_source || 'unknown'})`}
        />
        <KV label="updated" value={summary.updated_at || 'NA'} />
      </DetailBlock>

      <DetailBlock title="IFX Artifacts">
        {Object.keys(mapping).length > 0 ? (
          Object.entries(mapping).map(([platform, item]) =>
            item ? (
              <KV
                key={platform}
                label={platform}
                value={`${item.name || 'NA'} -v ${item.version ?? 'NA'}`}
              />
            ) : null,
          )
        ) : (
          <EmptyState>No IFX mapping yet.</EmptyState>
        )}
      </DetailBlock>

      <DetailBlock title="Local ONNX">
        {copyInfo?.available ? (
          <CopyOnnxPanel releaseId={summary.release_id} targetPath={String(copyInfo.target_path ?? '')} />
        ) : (
          <EmptyState>Available after ONNX upload succeeds.</EmptyState>
        )}
      </DetailBlock>

      <DetailBlock title="Handoff Branches">
        {(apply.results as Array<Record<string, unknown>> | undefined)?.length ? (
          (apply.results as Array<Record<string, unknown>>).map((item, i) => (
            <KV
              key={i}
              label={String(item.branch ?? '')}
              value={`${item.checkout_branch}: ${item.returncode === 0 ? 'OK' : `FAILED(${item.returncode})`}`}
            />
          ))
        ) : (
          <EmptyState>No applied handoff branches yet.</EmptyState>
        )}
        {(commands.dcl_commands as string[] | undefined)?.length ? (
          (commands.dcl_commands as string[]).map((cmd, i) => (
            <div key={i} className={styles.codeLine}>{cmd}</div>
          ))
        ) : (
          <EmptyState>DCL commands are not ready.</EmptyState>
        )}
      </DetailBlock>

      <DetailBlock title="Offboard Metrics">
        {metric_table?.length ? (
          <pre className={styles.metricTable}>{metric_table.join('\n')}</pre>
        ) : (
          <EmptyState>No offboard metrics captured yet.</EmptyState>
        )}
      </DetailBlock>

      <DetailBlock title="Next CLI Commands">
        {['ifx_convert', 'apply_handoff', 'dcl', 'offboard'].map((key) => {
          const val = commands[key];
          if (!val) return null;
          return (
            <div key={key} className={styles.codeLine}>
              {typeof val === 'string' ? val : (val as string[]).join(' ')}
            </div>
          );
        })}
      </DetailBlock>

      <DetailBlock title="Errors">
        {errors.length ? (
          errors.slice(-6).map((item, i) => (
            <div key={i} className={styles.codeLine}>{item.message || String(item)}</div>
          ))
        ) : (
          <EmptyState>No recorded errors.</EmptyState>
        )}
      </DetailBlock>
    </div>
  );
}

function DetailBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className={styles.detailBlock}>
      <h4>{title}</h4>
      {children}
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.kv}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className={styles.emptyState}>{children}</div>;
}

function CopyOnnxPanel({ releaseId, targetPath }: { releaseId: string; targetPath: string }) {
  const [status, setStatus] = useState(targetPath);
  const [busy, setBusy] = useState(false);

  const handleCopy = async () => {
    setBusy(true);
    setStatus('Copying...');
    try {
      const res = await copyVersionedOnnx(releaseId);
      setStatus(`Copied to ${(res as Record<string, unknown>).target ?? 'done'}`);
    } catch (e) {
      setStatus(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.copyOnnxPanel}>
      <button className={styles.actionButtonMini} type="button" disabled={busy} onClick={handleCopy}>
        Copy ONNX
      </button>
      <span className={styles.helperText}>{status}</span>
    </div>
  );
}
