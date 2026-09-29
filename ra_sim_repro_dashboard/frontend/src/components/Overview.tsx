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
import { useState, type CSSProperties, type KeyboardEvent } from 'react';
import { Activity, ArrowDownRight, ArrowUpRight, Gauge, ShieldCheck, Target } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { KpiSummary, SummaryResponse } from '../types';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { cn } from '../lib/utils';
import { PrComparison } from './PrComparison';
import { poststratifyBacktestWindow } from '../lib/backtest';
import { releaseChartRows, releaseTooltip, releaseXAxis } from '../lib/releaseChart';

interface OverviewProps {
  summary: SummaryResponse | null;
  comparison: KpiSummary[];
  onOpenIssues: (filters: {
    version?: string;
    rootCause?: string;
    triggerType?: string;
    precisionLabel?: string;
    query?: string;
  }) => void;
}

function pct(value: number | undefined) {
  return `${Math.round((value ?? 0) * 1000) / 10}%`;
}

function delta(value: number | undefined) {
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
  contentStyle: {
    background: 'hsl(var(--card))',
    border: '1px solid hsl(var(--border))',
    borderRadius: 8,
    color: 'hsl(var(--foreground))',
    boxShadow: '0 18px 40px hsl(0 0% 0% / 0.16)',
  },
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

function shortVersionLabel(value: string) {
  const dated = value.match(/(?:^|[-_])(\d{4})[-_](\d{2})[-_](\d{2})/);
  if (dated) return `${dated[2]}-${dated[3]}`;
  const compact = value.match(/(\d{8})/);
  if (compact) return `${compact[1].slice(4, 6)}-${compact[1].slice(6, 8)}`;
  return value.length > 10 ? value.slice(-10) : value;
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

export function Overview({ summary, comparison, onOpenIssues }: OverviewProps) {
  const { t } = useTranslation();
  const [visibleReproMetrics, setVisibleReproMetrics] = useState<Record<ReproMetric, boolean>>({
    repro: true,
    tp: true,
    fn: true,
    fp: true,
  });
  const [showTrendLabels, setShowTrendLabels] = useState(true);
  const [backtestWindowSize, setBacktestWindowSize] = useState(4);
  const [prMode, setPrMode] = useState<'same-version' | 'rolling'>('same-version');

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

  const current = summary.current;
  const kpis = [
    { label: t('simReproRate'), value: pct(current.sim_repro_rate), delta: summary.deltas.sim_repro_rate, icon: Activity, filters: { version: current.version_key, precisionLabel: 'FN' } },
    { label: t('precision'), value: pct(current.precision), delta: summary.deltas.precision, icon: Target, filters: { version: current.version_key, precisionLabel: 'FP' } },
    { label: t('recall'), value: pct(current.recall), delta: summary.deltas.recall, icon: Gauge, filters: { version: current.version_key, precisionLabel: 'FN' } },
    { label: t('f1'), value: pct(current.f1), delta: summary.deltas.f1, icon: ShieldCheck, filters: { version: current.version_key } },
  ];

  const trend = comparison.map((item) => ({
    version_key: item.version_key,
    version: shortVersionLabel(item.version_key),
    precision: Math.round(item.precision * 1000) / 10,
    recall: Math.round(item.recall * 1000) / 10,
    f1: Math.round(item.f1 * 1000) / 10,
    repro: Math.round(item.sim_repro_rate * 1000) / 10,
    tp: firstNumber(item.sim_estimate?.estimated_tp, item.sim_estimate?.tp, item.reproduced_cases),
    fn: firstNumber(item.sim_estimate?.estimated_fn, item.sim_estimate?.fn, item.road_positive_cases - item.reproduced_cases),
    fp: firstNumber(item.sim_estimate?.estimated_fp, item.sim_estimate?.fp, item.sim_positive_cases - item.reproduced_cases),
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
  const backtestTrend = comparison.flatMap((item, index) => {
    if (index + 1 < backtestWindowSize) return [];
    const window = comparison.slice(index + 1 - backtestWindowSize, index + 1);
    const sourcePrecisionTp = window.reduce((sum, row) => sum + firstNumber(
      row.source_gt?.precision_auto_tp, row.source_gt?.auto_trigger_tp,
    ), 0);
    const sourcePrecisionFp = window.reduce((sum, row) => sum + firstNumber(
      row.source_gt?.precision_auto_fp, row.source_gt?.auto_trigger_fp,
    ), 0);
    const sourceRecallTp = window.reduce((sum, row) => sum + firstNumber(
      row.source_gt?.recall_auto_tp, row.source_gt?.auto_trigger_tp,
    ), 0);
    const sourceRecallFn = window.reduce((sum, row) => sum + firstNumber(
      row.source_gt?.recall_manual_fn, row.source_gt?.manual_trigger_fn,
    ), 0);
    const sourcePrecision = sourcePrecisionTp + sourcePrecisionFp
      ? sourcePrecisionTp / (sourcePrecisionTp + sourcePrecisionFp) : 0;
    const sourceRecall = sourceRecallTp + sourceRecallFn
      ? sourceRecallTp / (sourceRecallTp + sourceRecallFn) : 0;

    const matrix = item.sim_estimate?.binary_backtest_sources;
    const matrixRows = matrix && typeof matrix === 'object'
      ? window.map((row) => (matrix as Record<string, Record<string, unknown>>)[row.version_key])
      : [];
    const projected = poststratifyBacktestWindow(
      window.map((row) => row.source_gt || {}), matrixRows,
    );
    const matrixComplete = projected.complete;
    return [{
      version_key: item.version_key,
      actualPrecision: Math.round(sourcePrecision * 1000) / 10,
      actualRecall: Math.round(sourceRecall * 1000) / 10,
      simPrecision: matrixComplete && projected.precisionTp + projected.precisionFp
        ? Math.round(projected.precisionTp / (projected.precisionTp + projected.precisionFp) * 1000) / 10 : undefined,
      simRecall: matrixComplete && projected.recallTp + projected.triggerReproFn
        ? Math.round(projected.recallTp / (projected.recallTp + projected.triggerReproFn) * 1000) / 10 : undefined,
      simBusinessRecall: matrixComplete && projected.recallTp + projected.businessRecallFn
        ? Math.round(projected.recallTp / (projected.recallTp + projected.businessRecallFn) * 1000) / 10 : undefined,
      positiveAutoNotTriggered: projected.positiveAutoNotTriggered,
      positiveManualNotTriggered: projected.positiveManualNotTriggered,
      negativeAutoNotTriggered: projected.negativeAutoNotTriggered,
    }];
  });
  const reproDomain: [number, number] = [60, 100];
  const prTrend = prMode === 'same-version' ? sameVersionTrend : backtestTrend;
  const countAxis = countScale(trend.flatMap((item) => [item.tp, item.fn, item.fp]));
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
              {...interactiveProps(() => onOpenIssues(item.filters))}
            >
              <div className="absolute inset-x-0 top-0 h-0.5 bg-primary/60" />
              <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-[13px] font-medium leading-4 text-muted-foreground">{item.label}</CardTitle>
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-accent text-accent-foreground">
                  <item.icon className="h-4 w-4" />
                </div>
              </CardHeader>
              <CardContent>
                <div className="font-mono text-[22px] font-semibold leading-7">{item.value}</div>
                <div className="mt-2 flex items-center gap-1 text-[12px] leading-4 text-muted-foreground">
                  <TrendIcon className={cn('h-3.5 w-3.5', healthy ? 'text-emerald-500 dark:text-primary' : 'text-red-500')} />
                  <span>{delta(item.delta) || '0%'}</span>
                  <span>{t('vsPrevious')}</span>
                  <span className="ml-auto opacity-0 transition group-hover:opacity-100">{t('drillDown')}</span>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="grid grid-cols-1 gap-4">
        <Card>
          <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 px-5 pb-1 pt-3">
            <div className="min-w-0">
              <CardTitle>{t('continuousReproTrend')}</CardTitle>
            </div>
            <div className="flex max-w-[390px] shrink-0 flex-wrap items-center justify-end gap-1">
              {reproControls.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  aria-pressed={visibleReproMetrics[item.key]}
                  style={{ '--toggle-color': item.color } as CSSProperties}
                  className={cn(
                    'chart-toggle inline-flex h-8 items-center gap-1 rounded-md border border-border/80 px-2 text-[11px] font-semibold focus:outline-none focus:ring-1 focus:ring-ring',
                  )}
                  onClick={() => toggleReproMetric(item.key)}
                >
                  <LegendDot color={item.color} />
                  {item.label}
                </button>
              ))}
              <button
                type="button"
                aria-pressed={showTrendLabels}
                style={{ '--toggle-color': 'hsl(var(--primary))' } as CSSProperties}
                className={cn(
                  'chart-toggle inline-flex h-8 items-center rounded-md border border-border/80 px-2 text-[11px] font-semibold focus:outline-none focus:ring-1 focus:ring-ring',
                )}
                onClick={() => setShowTrendLabels((value) => !value)}
              >
                {showTrendLabels ? t('hideValueLabels') : t('showValueLabels')}
              </button>
            </div>
          </CardHeader>
          <CardContent className="h-72 px-5 pb-5 pt-0">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={trendChartRows}
                margin={{ top: 28, right: 18, left: 0, bottom: 4 }}
                barCategoryGap="18%"
                barGap={2}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border) / 0.68)" vertical={false} />
                <XAxis {...releaseXAxis(trend)} />
                <YAxis yAxisId="rate" domain={reproDomain} ticks={percentageTicks} tickFormatter={(value: number) => `${value}%`} tickLine={false} axisLine={false} width={52} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11, textAnchor: 'end', dx: 8 }} />
                <YAxis
                  yAxisId="count"
                  orientation="right"
                  domain={countAxis.domain}
                  ticks={countAxis.ticks}
                  tickFormatter={(value: number) => formatCount(value)}
                  width={58}
                  tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11, textAnchor: 'start', dx: 16 }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip {...tooltipProps} {...releaseTooltip} labelFormatter={(index: number) => trend[index]?.version_key ?? ''} />
                {visibleReproMetrics.tp ? (
                  <Bar yAxisId="count" dataKey="tp" fill={chartColors.model} fillOpacity={0.78} radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false}>
                    <LabelList dataKey="tp" position="top" formatter={(value: number) => formatCount(value)} fill="hsl(var(--foreground))" stroke="hsl(var(--card))" strokeWidth={3} paintOrder="stroke" fontSize={11} fontWeight={600} />
                  </Bar>
                ) : null}
                {visibleReproMetrics.fn ? (
                  <Bar yAxisId="count" dataKey="fn" fill={chartColors.fn} fillOpacity={0.78} radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false}>
                    <LabelList dataKey="fn" position="top" formatter={(value: number) => formatCount(value)} fill="hsl(var(--foreground))" stroke="hsl(var(--card))" strokeWidth={3} paintOrder="stroke" fontSize={11} fontWeight={600} />
                  </Bar>
                ) : null}
                {visibleReproMetrics.fp ? (
                  <Bar yAxisId="count" dataKey="fp" fill={chartColors.fp} fillOpacity={0.78} radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false}>
                    <LabelList dataKey="fp" position="top" formatter={(value: number) => formatCount(value)} fill="hsl(var(--foreground))" stroke="hsl(var(--card))" strokeWidth={3} paintOrder="stroke" fontSize={11} fontWeight={600} />
                  </Bar>
                ) : null}
                {visibleReproMetrics.repro ? (
                  <Line yAxisId="rate" type="linear" dataKey="repro" stroke={chartColors.repro} strokeWidth={2.5} dot={hollowDot(chartColors.repro, 3.5)} activeDot={hollowDot(chartColors.repro, 5)} isAnimationActive={false}>
                    {showTrendLabels ? <LabelList dataKey="repro" content={renderTrendLabel(chartColors.repro, -8, -14)} /> : null}
                  </Line>
                ) : null}
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 px-5 pb-1 pt-3">
            <div className="min-w-0">
              <CardTitle>{prMode === 'same-version' ? t('sameVersionPr') : t('binaryBacktestPr')}</CardTitle>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="pr-mode">
                {t('prMode')}
              </label>
              <select
                id="pr-mode"
                className="h-8 rounded-md border border-border bg-background px-2 text-xs font-semibold text-foreground"
                value={prMode}
                onChange={(event) => setPrMode(event.target.value as 'same-version' | 'rolling')}
              >
                <option value="same-version">{t('sameVersionFull')}</option>
                <option value="rolling">{t('rollingCanary')}</option>
              </select>
              {prMode === 'rolling' ? (
                <>
                  <label className="text-xs font-medium text-muted-foreground" htmlFor="backtest-window-size">
                    {t('backtestWindow')}
                  </label>
                  <select
                    id="backtest-window-size"
                    className="h-8 rounded-md border border-border bg-background px-2 text-xs font-semibold text-foreground"
                    value={backtestWindowSize}
                    onChange={(event) => setBacktestWindowSize(Number(event.target.value))}
                  >
                    {[2, 3, 4].map((value) => (
                      <option key={value} value={value}>{value} {t('versionsUnit')}</option>
                    ))}
                  </select>
                </>
              ) : null}
              <Badge variant="secondary">{current.version_key}</Badge>
            </div>
          </CardHeader>
          <CardContent className="px-5 pb-5 pt-0">
            <PrComparison rows={prTrend} comparison={comparison} mode={prMode} />
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
                          <div className="font-semibold leading-5">{item.label || item.version_key}</div>
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
                          <Badge variant={item.quality_gate_passed ? 'success' : 'destructive'}>
                            {item.quality_gate_passed ? t('qualityPassed') : t('qualityFailed')}
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
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{t('rootCauseSubtitle')}</p>
          </div>
          <Badge variant="outline">{current.version_key}</Badge>
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
