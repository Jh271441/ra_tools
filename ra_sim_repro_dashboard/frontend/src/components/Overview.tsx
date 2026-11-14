import { releaseName } from '../lib/releaseName';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type LabelProps,
} from 'recharts';
import { Fragment, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react';
import { Activity, ArrowDownRight, ArrowUpRight, Gauge, ShieldCheck, Target } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { CollectionScope, KpiSummary, SummaryResponse } from '../types';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { cn } from '../lib/utils';
import { PrComparison } from './PrComparison';
import { releaseChartRows, releaseTooltip, releaseXAxis, releaseGrid, releaseChartMargin, releaseLeftAxisWidth, releaseRightAxisWidth, releaseTooltipStyle } from '../lib/releaseChart';

interface OverviewProps {
  sourceAnalysis?: ReactNode;
  evaluationBasis?: boolean;
  summary: SummaryResponse | null;
  comparison: KpiSummary[];
  onOpenCurrent: () => void;
  onOpenCollection?: (version: string) => void;
  onOpenIssues: (filters: {
    version?: string;
    rootCause?: string;
    triggerType?: string;
    precisionLabel?: string;
    query?: string;
  }) => void;
}

function pct(value: number | null | undefined) {
  if (value == null) return '—';
  return `${Math.round((value ?? 0) * 1000) / 10}%`;
}

function delta(value: number | null | undefined) {
  if (value == null) return '';
  const sign = value > 0 ? '+' : '';
  return `${sign}${pct(value)}`;
}

const chartColors = {
  precision: 'hsl(var(--chart-blue))',
  recall: 'hsl(var(--chart-green))',
  f1: 'hsl(var(--chart-orange))',
  repro: 'hsl(var(--chart-blue))',
  model: 'hsl(var(--chart-green))',
  fn: 'hsl(var(--chart-orange))',
  fp: 'hsl(var(--chart-red))',
};

type ReproMetric = 'repro' | 'tp' | 'fn' | 'fp';
const reproMetricKeys: ReproMetric[] = ['repro', 'tp', 'fn', 'fp'];

const tooltipProps = {
  contentStyle: releaseTooltipStyle,
  labelStyle: { color: 'hsl(var(--foreground))' },
  itemStyle: { color: 'hsl(var(--foreground))' },
};

function LegendDot({ color }: { color: string }) {
  return <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />;
}

function hollowDot(color: string, radius = 3.5) {
  return {
    r: radius,
    fill: 'hsl(var(--card))',
    stroke: color,
    strokeWidth: 2,
  };
}

function numberValue(value: unknown) {
  if (typeof value === 'number') return value;
  if (typeof value === 'string' && value.trim()) return Number(value);
  return 0;
}

function optionalNumber(value: unknown) {
  if (value == null || value === '') return undefined;
  const numeric = numberValue(value);
  return Number.isFinite(numeric) ? numeric : undefined;
}

function maybePct(value: unknown) {
  const numeric = optionalNumber(value);
  return numeric == null ? '-' : pct(numeric);
}

function firstNumber(...values: unknown[]) {
  for (const value of values) {
    const numeric = optionalNumber(value);
    if (numeric != null) return numeric;
  }
  return 0;
}

function formatCount(value: number | undefined) {
  return new Intl.NumberFormat().format(Math.max(0, Math.round(value ?? 0)));
}

function collectionState(scope: CollectionScope) {
  return scope.collection_status === 'collecting' || scope.reason_code === 'collecting' ? 'collecting' : scope.reason_code === 'population_changed' ? 'populationChanged' : 'needsReview';
}

function CollectionProgress({ scope, version, onOpen }: { scope: CollectionScope; version?: string | null; onOpen: () => void }) {
  const { t } = useTranslation();
  return <Card role="status" className="min-w-0">
    <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0 pb-3">
      <div className="min-w-0 space-y-1">
        <CardTitle className="break-words">{version ? releaseName(version) : t('businessCollection.current')}</CardTitle>
        <p className="text-sm leading-5 text-muted-foreground">{t(`businessCollection.${collectionState(scope)}`)} · {t('businessCollection.pendingMetrics')}</p>
      </div>
      <button className="min-h-11 rounded-md border px-3 py-2 text-sm text-primary focus:outline-none focus:ring-2 focus:ring-ring" onClick={onOpen}>{t('businessCollection.openIssues')}</button>
    </CardHeader>
    <CardContent>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 md:grid-cols-4">
        {(['collected_issue_count', 'auto_count', 'manual_count', 'evaluated_issue_count'] as const).map(key => <div key={key} className="min-w-0">
          <dt className="break-words text-xs leading-5 text-muted-foreground">{t(`businessCollection.${key}`)}</dt>
          <dd className="mt-1 font-mono text-lg font-semibold">{scope[key] == null ? '—' : formatCount(scope[key])}</dd>
        </div>)}
      </dl>
      <p className="mt-3 text-xs leading-5 text-muted-foreground">{t('businessCollection.frozenNote')}</p>
    </CardContent>
  </Card>;
}

function countScale(values: number[]) {
  const maxValue = Math.max(...values.filter(Number.isFinite), 0);
  if (maxValue <= 0) return { domain: [0, 1] as [number, number], ticks: [0, 1] };
  const roughStep = maxValue / 5;
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const normalized = roughStep / magnitude;
  const niceStep = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10;
  const step = niceStep * magnitude;
  const upper = Math.ceil(maxValue / step) * step;
  return {
    domain: [0, upper] as [number, number],
    ticks: Array.from({ length: Math.round(upper / step) + 1 }, (_, index) => index * step),
  };
}

function formatChartLabel(value: unknown) {
  const numeric = numberValue(value);
  return `${Math.round(numeric * 10) / 10}%`;
}


function TrendValueLabel({
  color,
  dx,
  dy,
  props,
}: {
  color: string;
  dx: number;
  dy: number;
  props: Pick<LabelProps, 'value' | 'x' | 'y'>;
}) {
  const x = numberValue(props.x);
  const y = numberValue(props.y);
  if (!Number.isFinite(x) || !Number.isFinite(y) || props.value == null) return null;
  return (
    <text
      className="chart-value-label"
      x={x + dx}
      y={y + dy}
      fill="hsl(var(--foreground))"
      stroke="hsl(var(--card))"
      strokeWidth={3}
      fontSize={11}
      fontWeight={700}
      paintOrder="stroke"
      textAnchor={dx < 0 ? 'end' : 'start'}
      dominantBaseline="central"
    >
      {formatChartLabel(props.value)}
    </text>
  );
}

function renderTrendLabel(color: string, dx: number, dy: number) {
  return (props: LabelProps) => (
    <TrendValueLabel color={color} dx={dx} dy={dy} props={props} />
  );
}

const percentageTicks = [60, 70, 80, 90, 100];

function interactiveProps(onClick: () => void) {
  return {
    role: 'button',
    tabIndex: 0,
    onClick,
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onClick();
      }
    },
  };
}

export function Overview({ summary, comparison, onOpenIssues, onOpenCurrent, onOpenCollection, evaluationBasis = false, sourceAnalysis }: OverviewProps) {
  const { t } = useTranslation();
  const [visibleReproMetrics, setVisibleReproMetrics] = useState<Record<ReproMetric, boolean>>({
    repro: true,
    tp: true,
    fn: true,
    fp: true,
  });
  const [showTrendLabels, setShowTrendLabels] = useState(true);
  const [showRoadCounts, setShowRoadCounts] = useState(true);

  if (!summary) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t('overview')}</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {t('noDashboardData')}
        </CardContent>
      </Card>
    );
  }

  const collection = !evaluationBasis ? summary.business_collection : null;
  const collectionPending = collection?.available === false;
  const openCollection = (version?: string | null) => version && onOpenCollection ? onOpenCollection(version) : onOpenCurrent();
  const current = summary.business_metrics
    || (collectionPending ? comparison.find(item => item.version_key === summary.business_current_version) : null)
    || summary.current || summary.legacy_current;
  if (!current) return collectionPending ? <CollectionProgress scope={collection} version={summary.business_current_version} onOpen={() => openCollection(summary.business_current_version)} />
    : <Card><CardContent className="p-5 text-sm">{summary.business_current_version ? releaseName(summary.business_current_version) : t('businessCollection.current')} · {t('businessCollection.pendingSimulation')}<button className="ml-3 min-h-11 text-primary" onClick={() => openCollection(summary.business_current_version)}>{t('businessCollection.openIssues')}</button></CardContent></Card>;
  const businessPending = collectionPending || Boolean(summary.business_current_version && !summary.business_metrics);
  const historicalFrozen = (item: KpiSummary) => Boolean(item.collection_scope?.historical_frozen
    && item.version_key !== summary.business_current_version);
  const populationPending = (item: KpiSummary) => item.collection_scope?.available === false && !historicalFrozen(item);
  const coveredScope = current.evaluation_scope;
  const kpis = [
    { label: t('simReproRate'), value: pct(coveredScope ? coveredScope.repro_rate : current.sim_repro_rate), delta: summary.deltas.sim_repro_rate, icon: Activity, filters: { version: current.version_key, precisionLabel: 'FN' } },
    { label: t('precision'), value: pct(coveredScope ? coveredScope.precision : current.precision), delta: summary.deltas.precision, icon: Target, filters: { version: current.version_key, precisionLabel: 'FP' } },
    { label: t('recall'), value: pct(coveredScope ? coveredScope.recall : current.recall), delta: summary.deltas.recall, icon: Gauge, filters: { version: current.version_key, precisionLabel: 'FN' } },
    { label: t(evaluationBasis ? 'evaluation.coverage' : 'f1'), value: pct(evaluationBasis ? current.dpe_coverage : current.f1), delta: evaluationBasis ? undefined : summary.deltas.f1, icon: ShieldCheck, filters: { version: current.version_key } },
  ];

  const trend = comparison.map((item) => {
    const pending = populationPending(item);
    const display = item.evaluation_scope;
    const road = display?.road_counts;
    const repro = display ? display.repro_rate : item.sim_repro_rate;
    return ({
    version_key: item.version_key,
    version: releaseName(item.version_key),
    collection: item.collection_scope,
    historicalFrozen: historicalFrozen(item),
    precision: pending || item.precision == null ? undefined : Math.round(item.precision * 1000) / 10,
    recall: pending || item.recall == null ? undefined : Math.round(item.recall * 1000) / 10,
    f1: pending || item.f1 == null ? undefined : Math.round(item.f1 * 1000) / 10,
    repro: pending || repro == null ? undefined : Math.round(repro * 1000) / 10,
    tp: pending ? undefined : optionalNumber(item.sim_estimate?.estimated_tp) ?? optionalNumber(item.sim_estimate?.tp),
    fn: pending ? undefined : optionalNumber(item.sim_estimate?.estimated_fn) ?? optionalNumber(item.sim_estimate?.fn),
    fp: pending ? undefined : optionalNumber(item.sim_estimate?.estimated_fp) ?? optionalNumber(item.sim_estimate?.fp),
    roadTp: pending ? undefined : optionalNumber(display ? road?.precision_numerator : item.source_gt?.auto_trigger_tp),
    roadFn: pending ? undefined : optionalNumber(display ? road && road.recall_denominator-road.recall_numerator : item.source_gt?.manual_trigger_fn),
    roadFp: pending ? undefined : optionalNumber(display ? road && road.precision_denominator-road.precision_numerator : item.source_gt?.auto_trigger_fp),
    excluded: item.publication?.excluded_scenario_ids.length ?? optionalNumber(item.sim_estimate?.terminal_failed),
  }); });
  const sameVersionTrend = comparison.map((item) => {
    const pending = populationPending(item);
    const projection = item.sim_estimate?.same_version_projection;
    const metrics = projection && typeof projection === 'object'
      ? projection as Record<string, unknown>
      : {};
    const display = item.evaluation_scope;
    const available = display ? display.covered > 0 : metrics.available === true;
    const actualPrecision = display ? display.road_precision : optionalNumber(item.source_gt?.online_precision);
    const actualRecall = display ? display.road_recall : optionalNumber(item.source_gt?.online_recall);
    const simPrecision = display ? display.precision : optionalNumber(metrics.sim_precision);
    const simRecall = display ? display.recall : optionalNumber(metrics.sim_business_recall);
    return {
      version_key: item.version_key,
      actualPrecision: !pending && actualPrecision != null ? actualPrecision*100 : undefined,
      actualRecall: !pending && actualRecall != null ? actualRecall*100 : undefined,
      simPrecision: !pending && available && simPrecision != null ? simPrecision*100 : undefined,
      simRecall: !pending && available && simRecall != null ? simRecall*100 : undefined,
      simAllCohortRecall: !pending && available && optionalNumber(metrics.sim_all_cohort_trigger_recall) != null
        ? numberValue(metrics.sim_all_cohort_trigger_recall) * 100 : undefined,
      populationCoverage: optionalNumber(metrics.population_coverage) != null
        ? numberValue(metrics.population_coverage) * 100 : undefined,
      projectionAvailable: available,
      projectionReason: String(metrics.reason || ''),
    };
  });
  const reproDomain: [number, number] = [60, 100];
  const countAxis = countScale(trend.flatMap((item) => [item.tp, item.fn, item.fp, item.roadTp, item.roadFn, item.roadFp]).filter((v): v is number => v != null));
  const trendChartRows = releaseChartRows(trend);
  const reproControls: Array<{ key: ReproMetric; label: string; color: string }> = [
    { key: 'repro', label: t('simReproRate'), color: chartColors.repro },
    { key: 'tp', label: evaluationBasis ? t('evaluation.precision_numerator') : 'TP', color: chartColors.model },
    { key: 'fn', label: evaluationBasis ? t('evaluation.recall_missed') : 'FN', color: chartColors.fn },
    { key: 'fp', label: evaluationBasis ? t('evaluation.precision_remaining') : 'FP', color: chartColors.fp },
  ];

  function toggleReproMetric(key: ReproMetric) {
    setVisibleReproMetrics((current) => {
      const activeCount = reproMetricKeys.filter((item) => current[item]).length;
      if (current[key] && activeCount === 1) return current;
      return { ...current, [key]: !current[key] };
    });
  }

  const countSeries = [
    { key: 'tp' as const, roadKey: 'roadTp' as const, label: evaluationBasis ? t('evaluation.precision_numerator') : 'TP', color: chartColors.model },
    { key: 'fn' as const, roadKey: 'roadFn' as const, label: evaluationBasis ? t('evaluation.recall_missed') : 'FN', color: chartColors.fn },
    { key: 'fp' as const, roadKey: 'roadFp' as const, label: evaluationBasis ? t('evaluation.precision_remaining') : 'FP', color: chartColors.fp },
  ];
  const countText = (value: number | undefined) => value == null ? '—' : formatCount(value);
  function comparisonTooltip({ active, label }: { active?: boolean; label?: string | number }) {
    const row = trend[Number(label)];
    if (!active || !row) return null;
    return (
      <div className="max-w-[300px] p-3 text-xs" style={releaseTooltipStyle}>
        <div className="mb-2 font-semibold">{row.version_key}</div>
        <div className="mb-2">{t('simReproRate')} · {row.repro == null ? '—' : formatChartLabel(row.repro)}</div>
        {row.historicalFrozen && row.collection && <p className="mb-2 leading-5 text-muted-foreground"><strong>{t('businessCollection.historicalFrozen')}</strong><br />{t('businessCollection.frozenPopulationCounts', { frozen: countText(row.collection.frozen_issue_count ?? undefined), collected: countText(row.collection.collected_issue_count ?? undefined) })}</p>}
        {!row.historicalFrozen && row.collection?.available === false && <p className="mb-2 leading-5 text-muted-foreground">{t(`businessCollection.${collectionState(row.collection)}`)}<br />{t('businessCollection.collectedSummary', { collected: countText(row.collection.collected_issue_count ?? undefined), auto: countText(row.collection.auto_count ?? undefined), manual: countText(row.collection.manual_count ?? undefined) })}</p>}
        <table className="w-full tabular-nums">
          <thead><tr className="text-muted-foreground">
            <th className="pr-3 text-left">{t('metric')}</th>
            <th className="px-2 text-right">{t('roadBaseline')}</th>
            <th className="px-2 text-right">{t('simCalcShort')}</th>
            <th className="pl-2 text-right">{t('simMinusRoad')}</th>
          </tr></thead>
          <tbody>{countSeries.map(({ key, roadKey, label: metric, color }) => {
            const road = row[roadKey];
            const sim = row[key];
            const gap = road == null || sim == null ? undefined : sim - road;
            return <tr key={key}>
              <th className="py-1 pr-3 text-left"><span style={{ color }}>●</span> {metric}</th>
              <td className="px-2 text-right">{countText(road)}</td>
              <td className="px-2 text-right">{countText(sim)}</td>
              <td className="pl-2 text-right">{gap == null ? '—' : `${gap > 0 ? '+' : gap < 0 ? '−' : ''}${formatCount(Math.abs(gap))}`}</td>
            </tr>;
          })}</tbody>
        </table>
        <p className="mt-2 max-w-[260px] text-muted-foreground">{t(evaluationBasis?'evaluation.paired_counts_note':'countBaselineNote')}</p>
        {row.excluded != null && row.excluded > 0 ? <p className="mt-1 text-muted-foreground">{t('countExcludedNote', { count: row.excluded })}</p> : null}
      </div>
    );
  }

  const aggregateRows = comparison.filter((item) => item.collection_scope || item.source_gt || item.sim_estimate);

  return (
    <div className="grid gap-4">
      {collectionPending && <CollectionProgress scope={collection} version={summary.business_current_version} onOpen={() => openCollection(summary.business_current_version)} />}
      {evaluationBasis && <p role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground"><strong className="text-foreground">{t('evaluation.covered_scope_title')}</strong><span>{releaseName(current.version_key)}</span>{coveredScope && <span>{t('evaluation.covered_scope',{covered:formatCount(coveredScope.covered),eligible:formatCount(coveredScope.eligible)})}</span>}{!coveredScope?.complete && <span>{t('evaluation.full_pending_short')}</span>}</p>}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {kpis.map((item) => {
          const deltaValue = item.delta ?? 0;
          const healthy = deltaValue >= 0;
          const TrendIcon = deltaValue >= 0 ? ArrowUpRight : ArrowDownRight;
          return (
            <Card
              key={item.label}
              className="metric-surface group relative cursor-pointer overflow-hidden transition hover:-translate-y-0.5 hover:border-primary/35 hover:shadow-lg hover:shadow-primary/10 focus:outline-none focus:ring-2 focus:ring-ring"
              {...interactiveProps(() => summary.business_current_version ? onOpenCurrent() : onOpenIssues(item.filters))}
            >
              <div className="absolute inset-x-0 top-0 h-0.5 bg-primary/60" />
              <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-[13px] font-medium leading-4 text-muted-foreground">{item.label}</CardTitle>
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent text-accent-foreground">
                  <item.icon className="h-4 w-4" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="font-mono text-[22px] font-semibold leading-7">{businessPending ? "—" : item.value}</div>{!businessPending && item.label === t('simReproRate') && current.reproduction && <p className="mt-1 text-xs text-muted-foreground" title={t('reproduction.policy')}>{t('reproduction.verified', { matched: formatCount(current.reproduction.matched), evaluated: formatCount(current.reproduction.evaluated) })}{!!current.reproduction.pending && ` · ${t('reproduction.pending_count', { amount: formatCount(current.reproduction.pending) })}`}</p>}
                <div className="mt-2 flex items-center gap-1 text-[12px] leading-4 text-muted-foreground">
                  {businessPending ? <span>{releaseName(summary.business_current_version)} · {t('businessCollection.pendingSimulation')}</span> : <>
                  {!evaluationBasis && <><TrendIcon className={cn('h-3.5 w-3.5', healthy ? 'text-emerald-500 dark:text-primary' : 'text-red-500')} />
                  <span>{delta(item.delta) || '0%'}</span>
                  <span>{t('vsPrevious')}</span></>}
                  <span className="ml-auto opacity-0 transition group-hover:opacity-100">{t('drillDown')}</span></>}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="grid grid-cols-1 gap-4">
        <Card>
          <CardHeader className="gap-3 px-5 pb-3 pt-4">
            <div className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2">
              <CardTitle>{t('continuousReproTrend')}</CardTitle>
              <div className="ml-auto flex shrink-0 items-center gap-2" role="group" aria-label={t('chartDisplayTools')}>
              <button
                type="button"
                aria-pressed={showRoadCounts}
                title={t('roadBaselineCompare')}
                className="chart-toggle chart-tool inline-flex h-8 items-center gap-1.5 rounded-md border border-border/80 px-2.5 text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-ring"
                onClick={() => setShowRoadCounts((value) => !value)}
              >
                <span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm border border-dashed border-current bg-current/10" />
                {t('roadComparisonToggle')}
              </button>
              <button
                type="button"
                aria-pressed={showTrendLabels}
                className={cn(
                  'chart-toggle chart-tool inline-flex h-8 items-center rounded-md border border-border/80 px-2.5 text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-ring',
                )}
                onClick={() => setShowTrendLabels((value) => !value)}
              >
                {showTrendLabels ? t('hideValueLabels') : t('showValueLabels')}
              </button>
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-border/60 pt-3">
              <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t('chartMetricTools')}>
              {reproControls.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  aria-pressed={visibleReproMetrics[item.key]}
                  style={{ '--toggle-color': item.color } as CSSProperties}
                  className={cn(
                    'chart-toggle chart-metric inline-flex h-8 items-center gap-1.5 rounded-md border border-border/80 px-2.5 text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-ring',
                  )}
                  onClick={() => toggleReproMetric(item.key)}
                >
                  <LegendDot color={item.color} />
                  {item.label}
                </button>
              ))}
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                {showRoadCounts ? <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm border border-dashed border-current bg-muted" />{t('roadBaselineCompare')}</span> : null}
                <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm bg-muted-foreground/70" />{t('simCountLegend')}</span>
              </div>
            </div>
          </CardHeader>
          <CardContent className="px-5 pb-4 pt-0">
            <div className="overflow-x-auto">
              <div className="h-72 min-w-[680px]">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={trendChartRows}
                margin={releaseChartMargin}
                barCategoryGap="18%"
                barGap={2}
              >
                <CartesianGrid {...releaseGrid} />
                <XAxis {...releaseXAxis(trend)} />
                <YAxis yAxisId="rate" domain={reproDomain} ticks={percentageTicks} tickFormatter={(value: number) => `${value}%`} tickLine={false} axisLine={false} width={releaseLeftAxisWidth} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11, textAnchor: 'end', dx: 0 }} />
                <YAxis
                  yAxisId="count"
                  orientation="right"
                  domain={countAxis.domain}
                  ticks={countAxis.ticks}
                  tickFormatter={(value: number) => formatCount(value)}
                  width={releaseRightAxisWidth}
                  tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11, textAnchor: 'start', dx: 16 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip {...tooltipProps} {...releaseTooltip} content={comparisonTooltip} />
                {countSeries.map(({ key, roadKey, label, color }) => visibleReproMetrics[key] ? (
                  <Fragment key={key}>
                    {showRoadCounts ? <Bar yAxisId="count" dataKey={roadKey} name={`${t('roadBaseline')} ${label}`} fill={color} fillOpacity={0.18} stroke={color} strokeDasharray="3 2" radius={[3, 3, 0, 0]} maxBarSize={16} isAnimationActive={false} /> : null}
                    <Bar yAxisId="count" dataKey={key} name={`${t('simCalcShort')} ${label}`} fill={color} fillOpacity={0.78} radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false}>
                      {showTrendLabels ? <LabelList dataKey={key} position="top" formatter={(value: number) => value == null ? '' : formatCount(value)} fill="hsl(var(--foreground))" stroke="hsl(var(--card))" strokeWidth={3} paintOrder="stroke" fontSize={11} fontWeight={600} /> : null}
                    </Bar>
                  </Fragment>
                ) : null)}
                {visibleReproMetrics.repro ? (
                  <Line yAxisId="rate" type="linear" dataKey="repro" stroke={chartColors.repro} strokeWidth={2.5} dot={hollowDot(chartColors.repro, 3.5)} activeDot={hollowDot(chartColors.repro, 5)} isAnimationActive={false}>
                    {showTrendLabels ? <LabelList dataKey="repro" content={renderTrendLabel(chartColors.repro, -8, -14)} /> : null}
                  </Line>
                ) : null}
              </ComposedChart>
            </ResponsiveContainer>
              </div>
            </div>
            <p className="mt-2 text-right text-[11px] leading-4 text-muted-foreground">{t('countHoverHint')}</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="px-5 pb-5 pt-3">
            <PrComparison rows={sameVersionTrend} comparison={comparison} evaluationBasis={evaluationBasis} businessVersion={summary.business_current_version} />
          </CardContent>
        </Card>
      </div>

      {summary && !evaluationBasis ? (
        <Card className="overflow-hidden">
          <CardHeader className="border-b border-border/70">
            <div>
              <CardTitle>{t('sourceVsSim')}</CardTitle>
              <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{t('sourceVsSimSubtitle')}</p>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="max-w-full overflow-x-auto">
              <table className="w-full min-w-[1750px] table-fixed text-left text-[13px]">
                <colgroup>
                  {[180, 240, 180, 120, 120, 150, 160, 150, 130, 120, 100, 100].map((width, index) => (
                    <col key={index} style={{ width }} />
                  ))}
                </colgroup>
                <thead className="bg-muted/45 dark:bg-white/[0.025]">
                  <tr>
                    <th className="h-10 whitespace-nowrap px-4 text-center text-xs font-medium uppercase text-muted-foreground align-middle">{t('version')}</th>
                    <th className="h-10 whitespace-nowrap px-4 text-center text-xs font-medium uppercase text-muted-foreground align-middle">{t('dataSource')}</th>
                    <th className="h-10 whitespace-nowrap px-4 text-center text-xs font-medium uppercase text-muted-foreground align-middle">样本分层</th>
                    <th className="h-10 whitespace-nowrap px-4 text-center text-xs font-medium uppercase text-muted-foreground align-middle">线上 P/R</th>
                    <th className="h-10 whitespace-nowrap px-4 text-center text-xs font-medium uppercase text-muted-foreground align-middle">离线 P/R</th>
                    <th className="h-10 whitespace-nowrap px-4 text-center text-xs font-medium uppercase text-muted-foreground align-middle">仿真 P/R</th>
                    <th className="h-10 whitespace-nowrap px-4 text-center text-xs font-medium uppercase text-muted-foreground align-middle">Job</th>
                    <th className="h-10 whitespace-nowrap px-4 text-center text-xs font-medium uppercase text-muted-foreground align-middle">自动 / FP / 人工</th>
                    <th className="h-10 px-4 text-center text-xs font-medium uppercase leading-5 text-muted-foreground align-middle">评测 P/R /<br />特异度 / 准确率</th>
                    <th className="h-10 whitespace-nowrap px-4 text-center text-xs font-medium uppercase text-muted-foreground align-middle">评测数</th>
                    <th className="h-10 whitespace-nowrap px-4 text-center text-xs font-medium uppercase text-muted-foreground align-middle">DPE 覆盖</th>
                    <th className="h-10 whitespace-nowrap px-4 text-center text-xs font-medium uppercase text-muted-foreground align-middle">质量门禁</th>
                  </tr>
                </thead>
                <tbody>
                  {aggregateRows.length ? aggregateRows.map((item) => {
                    const collection = item.collection_scope;
                    if (collection && populationPending(item)) return <tr key={item.version_key} className="cursor-pointer border-t border-border/60 transition hover:bg-accent/35" {...interactiveProps(() => openCollection(item.version_key))}>
                      <td className="px-4 py-3 text-center align-middle"><div className="font-semibold leading-5">{releaseName(item.version_key)}</div><div className="font-mono text-xs text-muted-foreground">{item.version_key}</div></td>
                      <td colSpan={11} className="px-4 py-3 align-middle"><div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-sm"><Badge variant="warning">{t(`businessCollection.${collectionState(collection)}`)}</Badge><span>{t('businessCollection.collectedSummary',{collected:collection.collected_issue_count == null ? '—' : formatCount(collection.collected_issue_count),auto:collection.auto_count == null ? '—' : formatCount(collection.auto_count),manual:collection.manual_count == null ? '—' : formatCount(collection.manual_count)})}</span><span>{t('businessCollection.evaluatedSummary',{formattedCount:collection.evaluated_issue_count == null ? '—' : formatCount(collection.evaluated_issue_count)})}</span><span className="text-muted-foreground">{t('businessCollection.pendingMetrics')}</span></div></td>
                    </tr>;
                    const source = item.source_gt || {};
                    const sim = item.sim_estimate || {};
                    const projectionValue = sim.same_version_projection;
                    const projection = projectionValue && typeof projectionValue === 'object'
                      ? projectionValue as Record<string, unknown>
                      : {};
                    const scope = item.evaluation_scope;
                    const projectionAvailable = scope ? scope.covered > 0 : projection.available === true;
                    return (
                      <tr
                        key={item.version_key}
                        className="cursor-pointer border-t border-border/60 transition hover:bg-accent/35"
                        {...interactiveProps(() => onOpenIssues({ version: item.version_key }))}
                      >
                        <td className="px-4 py-3 text-center align-middle">
                          <div className="font-semibold leading-5">{releaseName(item.version_key)}</div>
                          <div className="font-mono text-xs text-muted-foreground">{item.version_key}</div>
                          {historicalFrozen(item) && collection && <div className="mt-2 space-y-1 text-xs leading-5 text-muted-foreground"><Badge variant="outline" className="max-w-full whitespace-normal">{t('businessCollection.historicalFrozen')}</Badge><p>{t('businessCollection.frozenPopulationCounts',{frozen:collection.frozen_issue_count == null ? '—' : formatCount(collection.frozen_issue_count),collected:collection.collected_issue_count == null ? '—' : formatCount(collection.collected_issue_count)})}</p></div>}
                        </td>
                        <td className="px-4 py-3 text-center align-middle">
                          <div className="flex flex-col items-center justify-center gap-1 text-center">
                            <Badge variant={sim.data_source === 'query_report' ? 'success' : 'secondary'}>
                              {sim.data_source==='shared_execution' ? t('evaluation.shared_simulation') : String(sim.data_source || 'config_fallback')}
                            </Badge>
                            <span className="text-xs text-muted-foreground">
                              {source.data_source==='shuyi_current_report' ? t('evaluation.source_shuyi') : String(source.data_source || '-')}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-center align-middle font-mono text-xs">
                          {numberValue(source.auto_trigger_tp)} / {numberValue(source.auto_trigger_fp)} / {numberValue(source.manual_trigger_fn)}
                        </td>
                        <td className="px-4 py-3 text-center align-middle font-mono text-xs">
                          {maybePct(source.online_precision)} / {maybePct(source.online_recall)}
                        </td>
                        <td className="px-4 py-3 text-center align-middle font-mono text-xs">
                          {maybePct(source.calculated_precision)} / {maybePct(source.calculated_recall)}
                        </td>
                        <td className="px-4 py-3 text-center align-middle font-mono text-xs">
                          {projectionAvailable ? (
                            <>
                              <div>{maybePct(scope ? scope.precision : projection.sim_precision)} / {maybePct(scope ? scope.recall : projection.sim_business_recall)}</div>
                              <div className="mt-1 text-[11px] text-muted-foreground">
                                {scope ? t('evaluation.covered_scope',{covered:formatCount(scope.covered),eligible:formatCount(scope.eligible)}) : <>Gap {delta(optionalNumber(projection.precision_gap))} / {delta(optionalNumber(projection.business_recall_gap))}</>}
                              </div>
                            </>
                          ) : (
                            <span className="text-muted-foreground">
                              {t('projectionUnavailable')} ({maybePct(projection.population_coverage)})
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-center align-middle font-mono text-xs">
                          {sim.job_id ? String(sim.job_id) : `${String(sim.pos_job_id || '-')} / ${String(sim.neg_job_id || '-')}`}
                        </td>
                        <td className="px-4 py-3 text-center align-middle font-mono text-xs">
                          {pct(item.positive_auto_repro_rate)} / {pct(item.negative_auto_repro_rate)} / {pct(item.positive_manual_repro_rate)}
                        </td>
                        <td className="px-4 py-3 text-center align-middle font-mono text-xs">
                          {pct(item.precision)} / {pct(item.recall)} / {pct(item.specificity)} / {pct(item.accuracy)}
                        </td>
                        <td className="px-4 py-3 text-center align-middle font-mono text-xs">
                          {formatCount(item.evaluated_cases)} / {formatCount(numberValue(source.total_scenarios))}
                        </td>
                        <td className="px-4 py-3 text-center align-middle font-mono text-xs">
                          {pct(item.dpe_coverage)}
                        </td>
                        <td className="px-4 py-3 text-center align-middle">
                          <Badge variant={scope && !scope.complete ? 'warning' : item.publication ? 'success' : item.quality_gate_passed ? 'success' : 'destructive'}>
                            {scope && !scope.complete ? t('evaluation.partial_short') : item.publication ? t('evaluation.result_published') : item.quality_gate_passed ? t('qualityPassed') : t('qualityFailed')}
                          </Badge>
                        </td>
                      </tr>
                    );
                  }) : (
                    <tr>
                      <td colSpan={12} className="px-4 py-10 text-center text-sm text-muted-foreground">
                        {t('noVersionsInRange')}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {evaluationBasis && <Card><CardHeader><CardTitle>{t('sourceVsSim')}</CardTitle><p className="text-xs text-muted-foreground">{t('evaluation.paired_counts_note')}</p></CardHeader><CardContent><div className="max-w-full overflow-x-auto"><table className="w-full min-w-[1050px] table-fixed text-sm"><thead><tr>{['version','evaluation.paired_road_precision','evaluation.paired_road_recall','evaluation.partial_precision','evaluation.partial_recall','simReproRate','evaluation.coverage'].map(key=><th key={key} className="p-3 text-center">{t(key)}</th>)}</tr></thead><tbody>{comparison.map(item=>{
        const scope=item.evaluation_scope, source=item.source_gt || {};
        return <tr key={item.version_key} className="border-t"><td className="p-3 text-center"><button className="min-h-11 text-primary" onClick={()=>onOpenIssues({version:item.version_key})}>{releaseName(item.version_key)}</button><details className="text-xs text-muted-foreground"><summary className="min-h-11 cursor-pointer py-3">{t('evaluation.full_road')}</summary><p>{t('precision')} {pct(optionalNumber(source.online_precision))}<br/>{formatCount(numberValue(source.precision_numerator))} / {formatCount(numberValue(source.precision_denominator))}</p><p className="mt-2">{t('recall')} {pct(optionalNumber(source.online_recall))}<br/>{formatCount(numberValue(source.recall_numerator))} / {formatCount(numberValue(source.recall_denominator))}</p></details></td>{[scope?.road_counts,scope?.sim_counts].flatMap((counts,index)=>['precision','recall'].map(metric=><td key={`${index}-${metric}`} className="p-3 text-center tabular-nums"><strong>{pct(scope ? scope[`${index===0?'road_':''}${metric}` as 'precision'|'recall'|'road_precision'|'road_recall'] : null)}</strong><p className="mt-1 text-xs text-muted-foreground">{counts?`${formatCount(counts[`${metric}_numerator`])} / ${formatCount(counts[`${metric}_denominator`])}`:'—'}</p></td>))}<td className="p-3 text-center tabular-nums"><strong>{pct(scope?.repro_rate)}</strong><p className="mt-1 text-xs text-muted-foreground">{scope?`${formatCount(item.reproduced_cases)} / ${formatCount(item.reproduction?.evaluated ?? scope.covered)}`:'—'}</p></td><td className="p-3 text-center tabular-nums">{pct(item.dpe_coverage)}<p className="mt-1 text-xs text-muted-foreground">{formatCount(item.evaluated_cases)} / {formatCount(item.road_positive_cases)}</p></td></tr>;
      })}</tbody></table></div></CardContent></Card>}
      {!evaluationBasis && <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>{t('rootCause')}</CardTitle>
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{businessPending ? t('businessCollection.historicalDiagnosis') : t('rootCauseSubtitle')}</p>
          </div>
          <Badge variant="outline" title={current.version_key}>{releaseName(current.version_key)}</Badge>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-4">
            {Object.entries(current.root_causes).map(([name, count]) => (
              <div
                key={name}
                className="metric-surface cursor-pointer rounded-md border p-4 transition hover:-translate-y-0.5 hover:border-primary/35 hover:shadow-md hover:shadow-primary/10 focus:outline-none focus:ring-2 focus:ring-ring"
                {...interactiveProps(() => onOpenIssues({ version: current.version_key, rootCause: name }))}
              >
                <div className="text-[12px] font-medium leading-4 text-muted-foreground">{name}</div>
                <div className="mt-3 flex items-end justify-between">
                  <div className="font-mono text-[22px] font-semibold leading-7">{count}</div>
                  <div className="text-xs text-muted-foreground">{pct(count / Math.max(current.total_cases, 1))}</div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>}
      {sourceAnalysis}
    </div>
  );
}
