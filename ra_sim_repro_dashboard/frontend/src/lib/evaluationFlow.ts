import type { EvaluationBoard, EvaluationExecution, EvaluationMetrics } from '../types/evaluation';

export type EvaluationStep = 'sync' | 'rules' | 'plan' | 'manual' | 'evaluate';
export interface EvaluationStage {
  step: EvaluationStep;
  value?: number | string;
  total?: number;
  state: 'complete' | 'active' | 'warning' | 'blocked' | 'waiting';
  status: string;
  params?: Record<string, string | number>;
}
export const activeExecution = (value: EvaluationExecution) =>
  ['preparing', 'submitting', 'submission_uncertain', 'running', 'verifying'].includes(
    value.status,
  );
export function completeMetrics(metrics: EvaluationMetrics, stale = false) {
  return (
    !stale &&
    metrics.available &&
    Number.isInteger(metrics.eligible) &&
    metrics.eligible > 0 &&
    metrics.covered === metrics.eligible &&
    metrics.coverage === 1
  );
}
const stamp = (value: string | undefined) => (value ? Date.parse(value) || 0 : 0);
export function evaluationActivity(data: EvaluationBoard) {
  const executions = data.executions
    .filter(
      (execution) =>
        !execution.context ||
        (['release', 'profile_id', 'date_start', 'date_end'] as const).every(
          (key) => execution.context?.[key] === data.context[key],
        ),
    )
    .sort(
      (a, b) =>
        stamp(b.progress?.started_at || b.created_at) -
        stamp(a.progress?.started_at || a.created_at),
    );
  const active = executions.find(activeExecution);
  const latest = active || executions[0];
  const starts = [...data.starts].sort((a, b) => stamp(b.created_at) - stamp(a.created_at));
  const failed = starts.filter((start) => start.status === 'failed');
  const currentFailure =
    starts[0]?.status === 'failed' &&
    !active &&
    (!latest ||
      stamp(starts[0].created_at) >= stamp(latest.progress?.started_at || latest.created_at))
      ? starts[0]
      : undefined;
  return { latest, active, failed, currentFailure };
}

/** Slow motion means an enabled scheduled check; fast motion needs an active receipt. */
export function evaluationMotion(data: EvaluationBoard | null | undefined) {
  const still = { check: false, refreshing: false, dispatch: false, evaluating: false };
  if (
    !data ||
    data.stale ||
    data.sample_source.status !== 'ready' ||
    data.refresh.status === 'failed'
  )
    return still;
  const { active } = evaluationActivity(data);
  const uncertain = active?.status === 'submission_uncertain';
  const refreshing = ['queued', 'running'].includes(data.refresh.status || '');
  return {
    check:
      !refreshing &&
      !!data.revision &&
      (data.cron.effective ?? (data.cron.enabled && data.cron.processing_enabled !== false)),
    refreshing,
    dispatch: !uncertain && (!!active || data.starts.some((start) => start.status === 'preparing')),
    evaluating:
      !uncertain &&
      (refreshing ||
        active?.status === 'verifying' ||
        data.executions.some(
          (execution) =>
            (!execution.context ||
              (['release', 'profile_id', 'date_start', 'date_end'] as const).every(
                (key) => execution.context?.[key] === data.context[key],
              )) &&
            execution.metrics_status === 'pending',
        )),
  };
}

/** One receipt-derived state model for desktop React Flow and the mobile list. */
export function evaluationFlow(data: EvaluationBoard | null | undefined): EvaluationStage[] {
  if (!data)
    return (['sync', 'rules', 'plan', 'manual', 'evaluate'] as const).map((step) => ({
      step,
      state: 'waiting',
      status: 'flow_waiting',
    }));
  const revision = data?.revision,
    plan = data?.plan,
    metrics = revision?.metrics;
  const working = ['queued', 'running'].includes(data?.refresh.status || '');
  const runnable = plan?.runnable_count ?? plan?.gap_count ?? 0;
  const blocked = plan?.blocked_count || 0;
  const { latest, active, currentFailure } = data ? evaluationActivity(data) : {};
  const pendingStart = data?.starts.some((start) => start.status === 'preparing');
  const ready = Boolean(plan?.id && !data?.stale && !working);
  const manual: EvaluationStage = {
    step: 'manual',
    value: runnable,
    state: 'waiting',
    status: 'await_manual',
  };
  if (active) {
    const uncertain = active.status === 'submission_uncertain';
    Object.assign(manual, {
      value: active.progress?.completed ?? 0,
      total: active.progress?.total,
      state: uncertain ? 'blocked' : 'active',
      status: uncertain
        ? 'flow_receipt_pending'
        : active.status === 'verifying'
          ? 'flow_verifying'
          : active.job_id
            ? 'flow_job_running'
            : 'flow_preparing',
      params: active.job_id ? { job: active.job_id } : undefined,
    });
  } else if (pendingStart) Object.assign(manual, { state: 'active', status: 'flow_preparing' });
  else if (currentFailure) Object.assign(manual, { state: 'blocked', status: 'flow_start_failed' });
  else if (plan?.review_count)
    Object.assign(manual, {
      state: 'blocked',
      status: 'flow_review',
      params: { amount: plan.review_count },
    });
  else if (latest?.status === 'complete' && latest.metrics_status === 'pending')
    Object.assign(manual, {
      value: latest.progress?.completed,
      total: latest.progress?.total,
      state: 'complete',
      status: 'flow_job_complete',
      params: { job: latest.job_id || '—' },
    });
  else if (!ready)
    Object.assign(manual, { status: data?.stale ? 'flow_recalculate' : 'await_manual' });
  else if (runnable > 0) Object.assign(manual, { status: 'await_manual' });
  else if (latest?.status === 'complete')
    Object.assign(manual, {
      value: latest.progress?.completed,
      total: latest.progress?.total,
      state: 'complete',
      status: 'flow_job_complete',
      params: { job: latest.job_id || '—' },
    });
  else if (latest?.status === 'quality_failed' || latest?.status === 'cancelled')
    Object.assign(manual, {
      state: 'warning',
      status: latest.status === 'cancelled' ? 'flow_cancelled' : 'flow_quality_failed',
    });
  else
    Object.assign(manual, {
      value: 0,
      state: blocked ? 'waiting' : 'complete',
      status: blocked ? 'flow_wait_source' : 'flow_no_simulation',
    });
  const projectionPending = latest?.metrics_status === 'pending';
  const full = Boolean(metrics && completeMetrics(metrics, Boolean(data?.stale)));
  return [
    {
      step: 'sync',
      value: revision?.source_count ?? data?.sample_source.row_count,
      state: working
        ? 'active'
        : data?.sample_source.status === 'missing'
          ? 'waiting'
          : data?.stale || data?.refresh.status === 'failed'
            ? 'warning'
            : revision
              ? 'complete'
              : 'waiting',
      status: working
        ? 'syncing'
        : data?.sample_source.status === 'missing'
          ? 'flow_no_snapshot'
          : data?.refresh.status === 'failed'
            ? 'flow_refresh_failed'
            : data?.stale
              ? 'flow_recalculate'
              : revision
                ? 'reconciled'
                : 'flow_ready_recalculate',
    },
    {
      step: 'rules',
      value: data?.profile.name,
      state: revision ? 'complete' : 'waiting',
      status: 'flow_profile_saved',
    },
    {
      step: 'plan',
      value: projectionPending ? undefined : runnable,
      state:
        projectionPending || working
          ? 'active'
          : !ready
            ? 'waiting'
            : plan?.review_count
              ? 'blocked'
              : blocked && !runnable
                ? 'warning'
                : 'complete',
      status: projectionPending
        ? 'flow_updating_metrics'
        : working
          ? 'syncing'
          : data?.stale
            ? 'flow_recalculate'
            : plan?.review_count
              ? 'flow_review'
              : blocked && !runnable
                ? 'flow_deferred'
                : runnable
                  ? 'flow_ready_manual'
                  : 'flow_no_gaps',
      params: plan?.review_count
        ? { amount: plan.review_count }
        : blocked
          ? { amount: blocked }
          : undefined,
    },
    manual,
    {
      step: 'evaluate',
      value: metrics?.covered,
      total: metrics?.eligible,
      state: projectionPending ? 'active' : full ? 'complete' : revision ? 'warning' : 'waiting',
      status: projectionPending
        ? 'flow_updating_metrics'
        : data?.stale
          ? 'flow_recalculate'
          : full
            ? 'flow_metrics_complete'
            : metrics?.eligible === 0
              ? 'flow_no_eligible'
              : 'flow_metrics_partial',
    },
  ];
}
