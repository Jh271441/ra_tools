import type { ReactNode } from 'react';
import type { ReproductionSummary } from '../types/reproduction';
import { ReproductionDetails } from './ReproductionStatus';
import { Activity, ExternalLink } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { SimulationJob } from '../types/simulation';
import { executionSeconds } from '../lib/simulationFlow';
import { Badge } from './ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

export const simulationResultsGrid =
  'grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,1fr)_280px]';

export function SimulationStat({
  title,
  value,
  detail,
  color = '',
}: {
  title: string;
  value: string;
  detail?: string;
  color?: string;
}) {
  return (
    <div className="min-w-0 rounded-lg border bg-card/70 p-4">
      <p className="break-words text-xs text-muted-foreground">{title}</p>
      <p className={`mt-2 font-mono text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
      {detail && <p className="mt-1 break-words text-xs text-muted-foreground">{detail}</p>}
    </div>
  );
}

export function SimulationJobCard({
  job,
  extraStatus,
}: {
  job: SimulationJob;
  extraStatus?: ReactNode;
}) {
  const { t, i18n } = useTranslation();
  const n = (v?: number | null) => (v == null ? '—' : v.toLocaleString(i18n.language));
  const p = job.progress;
  const parts = [
    { key: 'completed', color: 'bg-emerald-500', text: 'text-emerald-700 dark:text-emerald-400' },
    { key: 'running', color: 'bg-blue-500', text: 'text-blue-600 dark:text-blue-400' },
    { key: 'queued', color: 'bg-slate-300 dark:bg-slate-600', text: '' },
    { key: 'failed', color: 'bg-red-500', text: 'text-red-600 dark:text-red-400' },
    { key: 'cancelled', color: 'bg-amber-500', text: 'text-amber-700 dark:text-amber-400' },
    { key: 'unknown', color: 'bg-violet-400', text: 'text-violet-600 dark:text-violet-400' },
  ] as const;
  const active = p?.state
    ? ['RUNNING', 'STARTING'].includes(p.state)
    : ['preparing', 'running', 'queued', 'submitting', 'verifying'].includes(job.status);
  const seconds = executionSeconds(p?.started_at, p?.finished_at || p?.observed_at);
  const elapsed =
    seconds == null
      ? '—'
      : t('simFlow.duration', {
          hours: Math.floor(seconds / 3600),
          minutes: Math.floor((seconds % 3600) / 60),
          seconds: seconds % 60,
        });
  const percent = p?.percent;
  const jobState = p?.state || job.status;
  const subtitle = job.backfill
    ? 'incremental'
    : job.primary_execution
      ? 'primary'
      : job.evaluation_task_key
        ? 'rerun'
        : job.archived
          ? 'archived'
          : 'cycle';
  return (
    <Card className="min-w-0 overflow-hidden" data-simulation-job={job.job_id || ''}>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-2">
              <Activity className="h-5 w-5 text-primary" aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <CardTitle>Job {job.job_id || t('evaluation.job_unassigned')}</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                {t(`evaluation.job_kind_${subtitle}`)}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {p?.priority && (
              <Badge variant={p.priority === 'HIGH' ? 'warning' : 'outline'}>
                {t(`evaluation.job_priority_${p.priority}`, { defaultValue: p.priority })}
              </Badge>
            )}
            <Badge
              variant={
                active
                  ? 'secondary'
                  : p?.failed
                    ? 'warning'
                    : p?.state === 'COMPLETED' || job.status === 'complete'
                      ? 'success'
                      : 'outline'
              }
            >
              {t(`evaluation.job_state_${jobState}`, {
                defaultValue: t(`evaluation.execution_${jobState}`, { defaultValue: jobState }),
              })}
            </Badge>
            {extraStatus}
            {job.url && (
              <a
                href={job.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex min-h-11 items-center gap-1 text-sm font-medium text-primary"
              >
                {t('evaluation.job_orion')}
                <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
              </a>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {p ? (
          <>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="text-xs text-muted-foreground">{t('evaluation.job_progress')}</p>
                <p className="mt-1 font-mono text-3xl font-semibold tabular-nums">
                  {percent == null
                    ? '—'
                    : percent.toLocaleString(i18n.language, {
                        maximumFractionDigits:
                          (percent > 0 && percent < 1) || (percent > 99 && percent < 100) ? 2 : 1,
                        minimumFractionDigits: 1,
                      })}
                  {percent != null && <span className="ml-1 text-lg text-muted-foreground">%</span>}
                </p>
              </div>
              <div className="text-right">
                <p className="font-mono text-sm tabular-nums">
                  {t('evaluation.job_scene_progress', { done: n(p.finished), total: n(p.total) })}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t('evaluation.job_finished_basis')}
                </p>
              </div>
            </div>
            {p.total != null && p.total > 0 && p.finished != null && (
              <div
                role="progressbar"
                aria-label={t('evaluation.job_progress_label', { job: job.job_id || '—' })}
                aria-valuemin={0}
                aria-valuemax={p.total}
                aria-valuenow={p.finished}
                className="flex h-3 overflow-hidden rounded-full bg-muted"
              >
                {parts.map((part) => {
                  const value = p[part.key];
                  return value != null && value > 0 ? (
                    <div
                      key={part.key}
                      className={part.color}
                      title={`${t(`evaluation.job_${part.key}`)} ${n(value)}`}
                      style={{ width: `${(value / p.total!) * 100}%`, minWidth: 2 }}
                    />
                  ) : null;
                })}
              </div>
            )}
            <dl className="grid grid-cols-3 gap-x-5 gap-y-4 sm:grid-cols-5">
              {parts
                .filter((part) => part.key !== 'unknown' || !!p.unknown)
                .map((part) => (
                  <div key={part.key}>
                    <dt className="break-words text-xs text-muted-foreground">
                      {t(`evaluation.job_${part.key}`)}
                    </dt>
                    <dd
                      className={`mt-1 font-mono text-2xl font-semibold tabular-nums ${part.text}`}
                    >
                      {n(p[part.key])}
                    </dd>
                  </div>
                ))}
            </dl>
            <div className="flex flex-wrap justify-between gap-3 border-t pt-3 text-xs text-muted-foreground">
              <span>{t('evaluation.job_runtime', { limit: n(p.max_concurrency), elapsed })}</span>
              <span>
                {t('evaluation.job_observed', {
                  time: p.observed_at
                    ? new Date(p.observed_at).toLocaleString(
                        i18n.language.startsWith('zh') ? 'zh-CN' : 'en-GB',
                        { timeZone: 'Asia/Shanghai', hour12: false },
                      )
                    : '—',
                })}
              </span>
            </div>
            {(job.progress_error || job.error) && (
              <p
                role="alert"
                className="break-words rounded border border-amber-500/30 bg-amber-500/5 p-3 text-sm"
              >
                {t(
                  job.progress_error ? 'evaluation.job_read_error' : 'evaluation.job_quality_error',
                )}{' '}
                {job.progress_error || job.error}
              </p>
            )}
            {!!p.failures?.length && (
              <details className="border-t pt-3 text-sm">
                <summary className="min-h-11 cursor-pointer py-3 text-muted-foreground">
                  {t('evaluation.job_failures', { amount: p.failures.length })}
                </summary>
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr>
                        {['Task', 'Scenario', t('evaluation.job_task_status')].map((label) => (
                          <th key={label} className="p-2">
                            {label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {p.failures.map((task) => (
                        <tr key={task.task_id} className="border-t">
                          <td className="p-2 font-mono">{task.task_id}</td>
                          <td className="p-2 font-mono">{task.scenario_id}</td>
                          <td className="p-2">
                            {t(`evaluation.job_state_${task.status}`, {
                              defaultValue: task.status,
                            })}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </>
        ) : (
          <div
            role="status"
            className="rounded-lg bg-muted/40 p-6 text-center text-sm text-muted-foreground"
          >
            <p>
              {t(
                job.progress_error
                  ? 'evaluation.job_read_error'
                  : job.job_id
                    ? 'evaluation.job_loading'
                    : 'evaluation.flow_preparing',
              )}
            </p>
            <p className="mt-2">{t('evaluation.job_planned', { amount: n(job.scenario_count) })}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function SimulationMetricCard({
  status,
  variant = 'outline',
  summary,
  precision,
  recall,
  reproduction,
  reproductionScope,
  available = true,
  decimals = 1,
  children,
}: {
  status: string;
  variant?: 'success' | 'warning' | 'outline';
  summary?: ReactNode;
  precision?: number | null;
  recall?: number | null;
  reproduction?: number | null;
  reproductionScope?: ReproductionSummary;
  available?: boolean;
  decimals?: number;
  children?: ReactNode;
}) {
  const { t, i18n } = useTranslation();
  const rate = (v?: number | null) =>
    !available || v == null
      ? '—'
      : `${(v * 100).toLocaleString(i18n.language, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}%`;
  return (
    <Card className="min-w-0" data-simulation-metrics>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>{t('evaluation.results_title')}</CardTitle>
          <Badge variant={variant}>{status}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {summary && (
          <div className="break-words text-xs leading-5 text-muted-foreground">{summary}</div>
        )}
        <dl className="divide-y">
          {[
            ['evaluation.partial_precision', precision],
            ['evaluation.partial_recall', recall],
            ['simReproRate', reproduction],
          ].map(([key, value]) => (
            <div
              key={String(key)}
              className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0"
            >
              <dt className="text-sm text-muted-foreground">{t(String(key))}</dt>
              <dd className="font-mono text-xl">{rate(value as number | null | undefined)}</dd>
            </div>
          ))}
        </dl>
        {reproductionScope && available && <ReproductionDetails value={reproductionScope} />}{' '}
        {children}
      </CardContent>
    </Card>
  );
}
