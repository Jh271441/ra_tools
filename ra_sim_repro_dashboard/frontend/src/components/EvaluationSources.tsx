import { useTranslation } from 'react-i18next';
import { ArrowDown } from 'lucide-react';
import type { EvaluationRevision, EvaluationSourceGroup } from '../types/evaluation';
import { releaseName } from '../lib/releaseName';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Select } from './ui/select';

const classes = ['correct', 'false', 'no_assist'] as const;
const sourceColor: Record<string, string> = {
  review: '#7c3aed',
  te_prime: '#a855f7',
  te: '#14b8a6',
  rd: '#0ea5e9',
  auto: 'hsl(var(--chart-blue))',
  to: 'hsl(var(--chart-orange))',
  no_result: 'hsl(var(--muted-foreground))',
  model: 'hsl(var(--chart-blue))',
  ra_result: 'hsl(var(--chart-orange))',
  unverified: 'hsl(var(--muted-foreground))',
};
const classColor = {
  correct: 'hsl(var(--chart-green))',
  false: 'hsl(var(--chart-red))',
  no_assist: 'hsl(var(--chart-blue))',
};
const fraction = (numerator: number, denominator: number) =>
  denominator > 0 ? `${((numerator / denominator) * 100).toFixed(2)}%` : '—';

function Bar({
  parts,
  label,
}: {
  parts: { amount: number; total: number; color: string; label: string }[];
  label: string;
}) {
  return (
    <div
      role="img"
      aria-label={label}
      className="flex h-3 w-full overflow-hidden rounded-full bg-muted"
    >
      {parts
        .filter((part) => part.amount > 0)
        .map((part) => (
          <span
            key={part.label}
            title={part.label}
            style={{
              width: `${part.total ? (part.amount / part.total) * 100 : 0}%`,
              backgroundColor: part.color,
            }}
          />
        ))}
    </div>
  );
}

export function EvaluationSources({
  revision,
  revisions,
  stale,
  busy,
  onRelease,
}: {
  revision: EvaluationRevision;
  revisions: EvaluationRevision[];
  stale: boolean;
  busy: boolean;
  onRelease?: (release: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const data = revision.source_distribution;
  const options = [
    ...new Set([revision.context.release, ...revisions.map((value) => value.context.release)]),
  ]
    .sort()
    .map((value) => ({ value, label: releaseName(value) }));
  const ready = Boolean(!stale && data?.available && data.revision_key === revision.revision_key);
  const groups = data?.groups || [],
    total = data?.total || 0;
  const visibleGroups = groups.filter((group) => group.count > 0);
  const number = (value: number) => value.toLocaleString(i18n.language);
  const sourceName = (group: EvaluationSourceGroup) => t(`evaluation.sources_${group.id}`);
  const label = (value: string | null) =>
    value === null
      ? t('autoTriage.result_none')
      : value === ''
        ? t('autoTriage.result_empty')
        : t(`autoTriage.result_${value}`, { defaultValue: value });
  const color = (id: string) => sourceColor[id] || 'hsl(var(--muted-foreground))';
  const parts = groups.map((group) => ({
    amount: group.count,
    total,
    color: color(group.id),
    label: `${sourceName(group)} ${number(group.count)} · ${fraction(group.count, total)}`,
  }));
  const time = data?.observed_at
    ? new Date(data.observed_at).toLocaleString(
        i18n.language.startsWith('zh') ? 'zh-CN' : 'en-GB',
        { timeZone: 'Asia/Shanghai', hour12: false },
      )
    : '—';
  const groupPanel = (group: EvaluationSourceGroup) => (
    <div key={group.id} className="min-w-0 space-y-3 rounded-lg bg-muted/25 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <strong className="inline-flex items-center gap-2 font-medium">
          <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color(group.id) }} />
          {sourceName(group)}
        </strong>
        <span className="font-mono tabular-nums">{number(group.count)}</span>
      </div>
      <Bar
        parts={classes.map((key) => ({
          amount: group.classes[key],
          total: group.classified_count,
          color: classColor[key],
          label: `${t(`evaluation.sources_class_${key}`)} ${number(group.classes[key])} · ${fraction(group.classes[key], group.classified_count)}`,
        }))}
        label={t('evaluation.sources_class_bar', {
          source: sourceName(group),
          amount: number(group.classified_count),
        })}
      />
      <dl className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto_auto] items-baseline gap-x-3 gap-y-2 text-sm">
        {classes.map((key) => (
          <div key={key} className="contents">
            <dt className="flex min-w-0 items-center gap-2 break-words">
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: classColor[key] }}
              />
              {t(`evaluation.sources_class_${key}`)}
            </dt>
            <dd className="font-mono tabular-nums">{number(group.classes[key])}</dd>
            <dd className="font-mono text-muted-foreground tabular-nums">
              {fraction(group.classes[key], group.classified_count)}
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-muted-foreground">
        {t('evaluation.sources_classified', { amount: number(group.classified_count) })}
        {group.classes.other > 0 &&
          ` · ${t('evaluation.sources_other', { amount: number(group.classes.other) })}`}
      </p>
    </div>
  );
  return (
    <Card className="min-w-0" data-evaluation-sources>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 space-y-0">
        <CardTitle>{t('evaluation.sources_title')}</CardTitle>
        {onRelease && (
          <Select
            value={revision.context.release}
            options={options}
            label={t('evaluation.sources_version')}
            disabled={busy}
            onChange={onRelease}
          />
        )}
      </CardHeader>
      <CardContent className="min-w-0 space-y-4">
        {!ready ? (
          <p role="status" className="py-3 text-sm text-muted-foreground">
            {t(stale ? 'evaluation.sources_stale' : 'evaluation.sources_unavailable')}
          </p>
        ) : (
          <>
            <div className="space-y-3">
              <p className="text-sm font-medium">
                {t('evaluation.sources_total', { amount: number(total) })}
              </p>
              <Bar parts={parts} label={parts.map((part) => part.label).join('; ')} />
              <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
                {parts
                  .filter((part) => part.amount > 0)
                  .map((part) => (
                    <span key={part.label} className="inline-flex items-center gap-2">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: part.color }}
                      />
                      {part.label}
                    </span>
                  ))}
              </div>
            </div>
            <div className="grid min-w-0 grid-cols-1 gap-x-4 gap-y-2 lg:grid-cols-2">
              {visibleGroups.map((group) => (
                <div key={group.id} className="min-w-0">
                  <ArrowDown
                    size={16}
                    className="mx-auto mb-2 hidden text-muted-foreground lg:block"
                    aria-hidden="true"
                  />
                  {groupPanel(group)}
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">{t('evaluation.sources_class_basis')}</p>
            {!!data?.correct_not_precision && (
              <p role="note" className="break-words text-xs text-amber-800 dark:text-amber-300">
                {t('evaluation.sources_literal_note', {
                  amount: number(data.correct_not_precision),
                })}
              </p>
            )}
            {!!groups.find((group) => group.id === 'unverified')?.count && (
              <p role="status" className="text-sm text-amber-800 dark:text-amber-300">
                {t('evaluation.sources_unverified_note')}
              </p>
            )}
            <details className="min-w-0 border-t pt-1">
              <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">
                {t('evaluation.sources_details')}
              </summary>
              <div className="min-w-0 space-y-4 pb-2 text-xs">
                <p className="leading-5 text-muted-foreground">
                  {data?.label_source === 'coalesce'
                    ? t('evaluation.sources_priority_note', {
                        priority: data.label_priority
                          ?.map((source) => t(`evaluation.sources_${source}`))
                          .join(' → '),
                      })
                    : t('evaluation.sources_route_note')}
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[460px] text-left tabular-nums">
                    <thead>
                      <tr>
                        {[
                          'evaluation.sources_source',
                          'evaluation.sources_precision',
                          'evaluation.sources_recall',
                        ].map((key) => (
                          <th key={key} className="p-2 font-medium">
                            {t(key)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        ...groups.filter((group) => group.id !== 'unverified' || group.count > 0),
                        { id: 'all', memberships: data?.counts || {} },
                      ].map((group) => (
                        <tr key={group.id} className="border-t">
                          <th className="p-2 font-medium">{t(`evaluation.sources_${group.id}`)}</th>
                          {['precision', 'recall'].map((metric) => (
                            <td key={metric} className="p-2">
                              <span className="whitespace-nowrap">
                                {number(group.memberships[`${metric}_numerator`])} /{' '}
                                {number(group.memberships[`${metric}_denominator`])}
                              </span>
                              <span className="ml-2 text-muted-foreground">
                                {fraction(
                                  group.memberships[`${metric}_numerator`],
                                  group.memberships[`${metric}_denominator`],
                                )}
                              </span>
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-muted-foreground">{t('evaluation.sources_full_scope_note')}</p>
                <dl className="grid min-w-0 gap-3">
                  {Object.entries(data?.rules || {}).map(([key, rule]) => (
                    <div key={key} className="min-w-0 space-y-1">
                      <dt className="font-medium">{t(`evaluation.sources_${key}`)}</dt>
                      <dd className="break-words leading-5 text-muted-foreground">
                        {rule.triggers
                          .map((trigger) =>
                            t(
                              trigger === 2 ? 'autoTriage.autoTrigger' : 'autoTriage.manualTrigger',
                            ),
                          )
                          .join(' / ')}{' '}
                        ·{' '}
                        {t(
                          rule.include
                            ? 'evaluation.sources_include'
                            : 'evaluation.sources_exclude',
                        )}{' '}
                        {('include' in rule ? rule.include : rule.exclude)
                          ?.map((value) => label(value))
                          .join(' / ')}
                      </dd>
                    </div>
                  ))}
                </dl>
                <div className="grid min-w-0 gap-3 lg:grid-cols-2">
                  {groups
                    .filter((group) => group.count > 0)
                    .map((group) => (
                      <div key={group.id} className="min-w-0 space-y-1">
                        <p className="font-medium">
                          {sourceName(group)} · {t('evaluation.sources_raw_labels')}
                        </p>
                        <p className="break-words leading-5 text-muted-foreground">
                          {group.raw_labels
                            .map((item) => `${label(item.label)} ${number(item.count)}`)
                            .join(' · ')}
                        </p>
                      </div>
                    ))}
                </div>
                <p className="break-words leading-5 text-muted-foreground">
                  {t('evaluation.sources_scope', {
                    start: revision.context.date_start,
                    end: revision.context.date_end,
                  })}{' '}
                  · {t('evaluation.sources_observed', { time })}
                </p>
              </div>
            </details>
          </>
        )}
      </CardContent>
    </Card>
  );
}
