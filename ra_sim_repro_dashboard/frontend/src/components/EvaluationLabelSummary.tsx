import { useEffect, useState } from 'react';
import { Check, Copy, ExternalLink } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { evaluationRequest } from '../api/evaluation';
import { evaluationParams } from '../lib/evaluationReads';
import { releaseName } from '../lib/releaseName';
import { writeClipboard } from '../lib/writeClipboard';
import type { EvaluationContext } from '../types/evaluation';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Select } from './ui/select';

const scopes = [
  'all_business',
  'nontraffic_business',
  'traffic_light',
  'EOL',
  'traffic_EOL',
] as const;
type Scope = (typeof scopes)[number];
type Counts = { scenario_count: number; published_issue_count: number };
type Outcome = Counts & {
  result: string;
  scenario_labels_all_of: string[];
  trail_issue_url: string | null;
};
type Summary =
  | { status: 'missing' }
  | {
      status: 'complete';
      workbench: {
        dataset: string;
        issue_total: number;
        published_issue_count: number;
        observed_at: string;
      };
      scopes: Record<Scope, Counts & { issue_count: number; outcomes: Outcome[] }>;
    };

function Label({ value }: { value: string }) {
  const { t } = useTranslation();
  const [state, setState] = useState<'copied' | 'error' | null>(null);
  useEffect(() => {
    if (!state) return;
    const timer = window.setTimeout(() => setState(null), 2000);
    return () => window.clearTimeout(timer);
  }, [state]);
  return (
    <div className="flex min-w-0 items-center gap-1">
      <code className="min-w-0 select-text break-all text-xs">{value}</code>
      <Button
        variant="ghost"
        size="icon"
        className="h-6 w-8 [@media(pointer:coarse)]:h-8 [@media(pointer:coarse)]:w-11"
        aria-label={t('evaluation.summary_copy', { label: value })}
        onClick={async () => {
          try {
            await writeClipboard(value);
            setState('copied');
          } catch {
            setState('error');
          }
        }}
      >
        {state === 'copied' ? <Check size={14} /> : <Copy size={14} />}
      </Button>
      {state && (
        <span role="status" className={state === 'copied' ? 'sr-only' : 'text-xs'}>
          {t(state === 'copied' ? 'simParameters.copied' : 'simParameters.manualCopy')}
        </span>
      )}
    </div>
  );
}

export function EvaluationLabelSummary({
  ctx,
  revision,
  loading,
}: {
  ctx: EvaluationContext;
  revision?: string;
  loading: boolean;
}) {
  const { t, i18n } = useTranslation();
  const [scope, setScope] = useState<Scope>('all_business');
  const [summary, setSummary] = useState<Summary | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const params = evaluationParams(ctx);
  if (revision) params.set('revision', revision);
  const query = params.toString();
  useEffect(() => {
    if (!revision) return;
    let active = true;
    setFailed(false);
    void evaluationRequest<Summary>(`/scenario-label-summary?${query}`)
      .then((value) => {
        if (active) setSummary(value);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [query, revision, attempt]);
  const format = (n: number) => n.toLocaleString(i18n.language);
  const title = t('evaluation.summary_title', { release: releaseName(ctx.release) });
  const ready = summary?.status === 'complete' ? summary : null;
  const selected = ready?.scopes[scope];
  return (
    <Card data-evaluation-labels={ctx.release}>
      <CardHeader className="text-center">
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {failed ? (
          <div role="alert" className="flex flex-wrap items-center justify-center gap-2 text-sm">
            {t('evaluation.scenario_labels_failed')}
            <Button variant="outline" className="min-h-11" onClick={() => setAttempt((n) => n + 1)}>
              {t('autoTriage.retry')}
            </Button>
          </div>
        ) : !ready || !selected ? (
          <p role="status" className="text-center text-sm text-muted-foreground">
            {t(
              loading || (revision && summary === null)
                ? 'loading'
                : 'evaluation.label_groups_pending',
            )}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-baseline justify-center gap-x-3 gap-y-1 break-words pb-3 text-sm">
              <span className="font-medium">Workbench · {ready.workbench.dataset}</span>
              <span>
                {t('evaluation.summary_wb_counts', {
                  total: format(ready.workbench.issue_total),
                  published: format(ready.workbench.published_issue_count),
                })}
              </span>
              <time
                className="text-xs text-muted-foreground"
                dateTime={ready.workbench.observed_at}
              >
                {t('evaluation.summary_observed', {
                  time: new Date(ready.workbench.observed_at).toLocaleString(i18n.language, {
                    timeZone: 'Asia/Shanghai',
                    hour12: false,
                  }),
                })}
              </time>
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t py-2 text-sm">
              <Select
                label={t('evaluation.summary_scope')}
                value={scope}
                options={scopes.map((value) => ({
                  value,
                  label: t(`evaluation.summary_scope_${value}`),
                }))}
                onChange={(value) => setScope(value as Scope)}
              />
              <span role="status">
                {t('evaluation.summary_counts', {
                  issues: format(selected.issue_count),
                  scenes: format(selected.scenario_count),
                  published: format(selected.published_issue_count),
                })}
              </span>
            </div>
            <table className="block w-full text-left text-sm md:table">
              <caption className="sr-only">{title}</caption>
              <thead className="sr-only text-xs text-muted-foreground md:not-sr-only md:table-header-group">
                <tr>
                  {[
                    'summary_result',
                    'label_groups_name',
                    'label_groups_count',
                    'summary_published',
                  ].map((key) => (
                    <th key={key} className="px-2 py-2" scope="col">
                      {t(`evaluation.${key}`)}
                    </th>
                  ))}
                  <th className="px-2" scope="col">
                    Trail
                  </th>
                </tr>
              </thead>
              <tbody className="block md:table-row-group">
                {selected.outcomes.map((row) => (
                  <tr
                    key={row.result}
                    className="grid min-w-0 grid-cols-2 items-center gap-1 border-t py-2 md:table-row"
                  >
                    <th scope="row" className="col-span-2 px-2 font-medium">
                      {t(`autoTriage.result_${row.result}`)}
                    </th>
                    <td className="col-span-2 min-w-0 px-2 py-0.5">
                      {row.scenario_labels_all_of.map((label) => (
                        <Label key={label} value={label} />
                      ))}
                    </td>
                    <td className="px-2 tabular-nums">
                      <span className="mr-1 text-xs text-muted-foreground md:hidden">
                        {t('evaluation.label_groups_count')}
                      </span>
                      {format(row.scenario_count)}
                    </td>
                    <td className="px-2 tabular-nums">
                      <span className="mr-1 text-xs text-muted-foreground md:hidden">
                        {t('evaluation.summary_published')}
                      </span>
                      {format(row.published_issue_count)}
                    </td>
                    <td className="col-span-2 px-2">
                      {row.trail_issue_url ? (
                        <a
                          className="inline-flex min-h-11 min-w-11 items-center gap-1 text-primary hover:underline"
                          href={row.trail_issue_url}
                          target="_blank"
                          rel="noreferrer"
                          aria-label={t('evaluation.summary_open', {
                            result: t(`autoTriage.result_${row.result}`),
                          })}
                        >
                          Trail
                          <ExternalLink size={13} />
                        </a>
                      ) : (
                        <span aria-label={t('evaluation.summary_empty')}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </CardContent>
    </Card>
  );
}
