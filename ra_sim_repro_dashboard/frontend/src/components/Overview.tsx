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
import { Fragment, useState, type CSSProperties, type KeyboardEvent } from 'react';
import { Activity, ArrowDownRight, ArrowUpRight, Gauge, ShieldCheck, Target } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { KpiSummary, SummaryResponse } from '../types';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { cn } from '../lib/utils';
import { PrComparison } from './PrComparison';
import { releaseChartRows, releaseTooltip, releaseXAxis, releaseGrid, releaseChartMargin, releaseLeftAxisWidth, releaseRightAxisWidth, releaseTooltipStyle } from '../lib/releaseChart';

interface OverviewProps {
  summary: SummaryResponse | null;
  comparison: KpiSummary[];
  onOpenCurrent: () => void;
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

export function Overview({ summary, comparison, onOpenIssues, onOpenCurrent }: OverviewProps) {
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

  const current = summary.business_metrics || summary.current || summary.legacy_current;
  if (!current) return <Card><CardContent className="p-5 text-sm">{summary.business_current_version ? releaseName(summary.business_current_version) : '当前版本'} · 待完整仿真。<button className="ml-3 text-primary" onClick={onOpenCurrent}>查看周期 Issue</button></CardContent></Card>;
  const businessPending = Boolean(summary.business_current_version && !summary.business_metrics);
  const kpis = [
    { label: t('simReproRate'), value: pct(current.sim_repro_rate), delta: summary.deltas.sim_repro_rate, icon: Activity, filters: { version: current.version_key, precisionLabel: 'FN' } },
    { label: t('precision'), value: pct(current.precision), delta: summary.deltas.precision, icon: Target, filters: { version: current.version_key, precisionLabel: 'FP' } },
    { label: t('recall'), value: pct(current.recall), delta: summary.deltas.recall, icon: Gauge, filters: { version: current.version_key, precisionLabel: 'FN' } },
    { label: t('f1'), value: pct(current.f1), delta: summary.deltas.f1, icon: ShieldCheck, filters: { version: current.version_key } },
  ];

  const trend = comparison.map((item) => ({
    version_key: item.version_key,
    version: releaseName(item.version_key),
    precision: item.precision == null ? undefined : Math.round(item.precision * 1000) / 10,
    recall: item.recall == null ? undefined : Math.round(item.recall * 1000) / 10,
    f1: item.f1 == null ? undefined : Math.round(item.f1 * 1000) / 10,
    repro: Math.round(item.sim_repro_rate * 1000) / 10,
    tp: optionalNumber(item.sim_estimate?.estimated_tp) ?? optionalNumber(item.sim_estimate?.tp),
    fn: optionalNumber(item.sim_estimate?.estimated_fn) ?? optionalNumber(item.sim_estimate?.fn),
    fp: optionalNumber(item.sim_estimate?.estimated_fp) ?? optionalNumber(item.sim_estimate?.fp),
    roadTp: optionalNumber(item.source_gt?.auto_trigger_tp),
    roadFn: optionalNumber(item.source_gt?.manual_trigger_fn),
    roadFp: optionalNumber(item.source_gt?.auto_trigger_fp),
    excluded: item.publication?.excluded_scenario_ids.length ?? optionalNumber(item.sim_estimate?.terminal_failed),
  }));
  const sameVersionTrend = comparison.map((item) => {
    const projection = item.sim_estimate?.same_version_projection;
    const metrics = projection && typeof projection === 'object'
      ? projection as Record<string, unknown>
      : {};
    const available = metrics.available === true;
    return {
      version_key: item.version_key,
      actualPrecision: optionalNumber(item.source_gt?.online_precision) != null
        ? numberValue(item.source_gt?.online_precision) * 100 : undefined,
      actualRecall: optionalNumber(item.source_gt?.online_recall) != null
        ? numberValue(item.source_gt?.online_recall) * 100 : undefined,
      simPrecision: available && optionalNumber(metrics.sim_precision) != null
        ? numberValue(metrics.sim_precision) * 100 : undefined,
      simRecall: available && optionalNumber(metrics.sim_business_recall) != null
        ? numberValue(metrics.sim_business_recall) * 100 : undefined,
      simAllCohortRecall: available && optionalNumber(metrics.sim_all_cohort_trigger_recall) != null
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
    { key: 'tp', label: 'TP', color: chartColors.model },
    { key: 'fn', label: 'FN', color: chartColors.fn },
    { key: 'fp', label: 'FP', color: chartColors.fp },
  ];

  function toggleReproMetric(key: ReproMetric) {
    setVisibleReproMetrics((current) => {
      const activeCount = reproMetricKeys.filter((item) => current[item]).length;
      if (current[key] && activeCount === 1) return current;
      return { ...current, [key]: !current[key] };
    });
  }

  const countSeries = [
    { key: 'tp' as const, roadKey: 'roadTp' as const, label: 'TP', color: chartColors.model },
    { key: 'fn' as const, roadKey: 'roadFn' as const, label: 'FN', color: chartColors.fn },
    { key: 'fp' as const, roadKey: 'roadFp' as const, label: 'FP', color: chartColors.fp },
  ];
  const countText = (value: number | undefined) => value == null ? '—' : formatCount(value);
  function comparisonTooltip({ active, label }: { active?: boolean; label?: string | number }) {
    const row = trend[Number(label)];
    if (!active || !row) return null;
    return (
      <div className="max-w-[300px] p-3 text-xs" style={releaseTooltipStyle}>
        <div className="mb-2 font-semibold">{row.version_key}</div>
        <div className="mb-2">{t('simReproRate')} · {formatChartLabel(row.repro)}</div>
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
        <p className="mt-2 max-w-[260px] text-muted-foreground">{t('countBaselineNote')}</p>
        {row.excluded != null && row.excluded > 0 ? <p className="mt-1 text-muted-foreground">{t('countExcludedNote', { count: row.excluded })}</p> : null}
      </div>
    );
  }

  const aggregateRows = comparison.filter((item) => item.source_gt || item.sim_estimate);

  return (
    <div className="grid gap-4">
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
                <div className="font-mono text-[22px] font-semibold leading-7">{businessPending ? "—" : item.value}</div>
                <div className="mt-2 flex items-center gap-1 text-[12px] leading-4 text-muted-foreground">
                  {businessPending ? <span>{releaseName(summary.business_current_version)} · 待完整仿真</span> : <>
                  <TrendIcon className={cn('h-3.5 w-3.5', healthy ? 'text-emerald-500 dark:text-primary' : 'text-red-500')} />
                  <span>{delta(item.delta) || '0%'}</span>
                  <span>{t('vsPrevious')}</span>
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
            <PrComparison rows={sameVersionTrend} comparison={comparison} />
          </CardContent>
        </Card>
      </div>

      {summary ? (
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
                    const source = item.source_gt || {};
                    const sim = item.sim_estimate || {};
                    const projectionValue = sim.same_version_projection;
                    const projection = projectionValue && typeof projectionValue === 'object'
                      ? projectionValue as Record<string, unknown>
                      : {};
                    const projectionAvailable = projection.available === true;
                    return (
                      <tr
                        key={item.version_key}
                        className="cursor-pointer border-t border-border/60 transition hover:bg-accent/35"
                        {...interactiveProps(() => onOpenIssues({ version: item.version_key }))}
                      >
                        <td className="px-4 py-3 text-center align-middle">
                          <div className="font-semibold leading-5">{releaseName(item.version_key)}</div>
                          <div className="font-mono text-xs text-muted-foreground">{item.version_key}</div>
                        </td>
                        <td className="px-4 py-3 text-center align-middle">
                          <div className="flex flex-col items-center justify-center gap-1 text-center">
                            <Badge variant={sim.data_source === 'query_report' ? 'success' : 'secondary'}>
                              {String(sim.data_source || 'config_fallback')}
                            </Badge>
                            <span className="text-xs text-muted-foreground">
                              {String(source.data_source || '-')}
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
                              <div>{maybePct(projection.sim_precision)} / {maybePct(projection.sim_business_recall)}</div>
                              <div className="mt-1 text-[11px] text-muted-foreground">
                                Gap {delta(optionalNumber(projection.precision_gap))} / {delta(optionalNumber(projection.business_recall_gap))}
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
                          <Badge variant={item.publication ? 'success' : item.quality_gate_passed ? 'success' : 'destructive'}>
                            {item.publication ? '已发布' : item.quality_gate_passed ? t('qualityPassed') : t('qualityFailed')}
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

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>{t('rootCause')}</CardTitle>
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{businessPending ? '历史已完成版本的诊断分布' : t('rootCauseSubtitle')}</p>
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
      </Card>
    </div>
  );
}
