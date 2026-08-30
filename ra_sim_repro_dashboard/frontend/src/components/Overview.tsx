import {
  Bar,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Line,
  LineChart,
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

function ChartHoverCursor(props: {
  points?: Array<{ x?: number; y?: number }>;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
}) {
  const pointX = optionalNumber(props.points?.[0]?.x);
  const rectX = optionalNumber(props.x);
  const rectWidth = optionalNumber(props.width);
  const x = pointX ?? (rectX != null && rectWidth != null ? rectX + rectWidth / 2 : undefined);
  const y = optionalNumber(props.y) ?? optionalNumber(props.points?.[0]?.y) ?? 0;
  const height = optionalNumber(props.height);
  if (x == null || height == null) return null;
  return (
    <line
      className="chart-hover-cursor"
      x1={x}
      x2={x}
      y1={y}
      y2={y + height}
      stroke="hsl(var(--primary) / 0.3)"
      strokeWidth={1.5}
      strokeDasharray="4 6"
      strokeLinecap="round"
      pointerEvents="none"
    />
  );
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

function cohortTriggerRate(row: Record<string, unknown>, cohortName: string) {
  const cohorts = row.cohorts;
  if (!cohorts || typeof cohorts !== 'object') return undefined;
  const cohort = (cohorts as Record<string, unknown>)[cohortName];
  if (!cohort || typeof cohort !== 'object') return undefined;
  const metrics = cohort as Record<string, unknown>;
  const expected = optionalNumber(metrics.expected);
  const evaluated = optionalNumber(metrics.evaluated);
  const triggerRate = optionalNumber(metrics.trigger_rate);
  if (
    expected == null || expected <= 0 || evaluated !== expected
    || triggerRate == null || triggerRate < 0 || triggerRate > 1
  ) return undefined;
  return triggerRate;
}

function maybePct(value: unknown) {
  const numeric = numberValue(value);
  return numeric ? pct(numeric) : '-';
}

function firstNumber(...values: unknown[]) {
  for (const value of values) {
    const numeric = numberValue(value);
    if (Number.isFinite(numeric) && numeric !== 0) return numeric;
  }
  return 0;
}

function formatCount(value: number | undefined) {
  return new Intl.NumberFormat().format(Math.max(0, Math.round(value ?? 0)));
}

function formatChartLabel(value: unknown) {
  const numeric = numberValue(value);
  return `${Math.round(numeric * 10) / 10}%`;
}

function shortVersionLabel(value: string) {
  const match = value.match(/(\d{8})$/);
  return match ? `${match[1].slice(4, 6)}-${match[1].slice(6, 8)}` : value;
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
      fill={color}
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

function VersionTick(props: { x?: number; y?: number; payload?: { value?: unknown; index?: number } }) {
  const x = numberValue(props.x);
  const y = numberValue(props.y);
  const fullValue = String(props.payload?.value ?? '');
  const value = shortVersionLabel(fullValue);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  return (
    <text
      x={x}
      y={y + 14}
      fill="hsl(var(--muted-foreground))"
      fontSize={11}
      fontWeight={600}
      textAnchor="middle"
    >
      {value}
    </text>
  );
}

function pctDomain(rows: Array<Record<string, unknown>>, keys: string[]): [number, number] {
  const values = rows
    .flatMap((item) => keys.map((key) => optionalNumber(item[key])))
    .filter((value): value is number => value != null);
  if (!values.length) return [0, 100];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const lower = Math.max(0, Math.floor((min - 6) / 5) * 5);
  const upper = Math.min(100, Math.ceil((max + 6) / 5) * 5);
  if (upper - lower >= 12) return [lower, upper];
  const center = (min + max) / 2;
  return [
    Math.max(0, Math.floor((center - 8) / 5) * 5),
    Math.min(100, Math.ceil((center + 8) / 5) * 5),
  ];
}

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
  const backtestTrend = comparison.flatMap((item, index) => {
    if (index + 1 < backtestWindowSize) return [];
    const window = comparison.slice(index + 1 - backtestWindowSize, index + 1);
    const sourceTp = window.reduce((sum, row) => sum + numberValue(row.source_gt?.auto_trigger_tp), 0);
    const sourceFp = window.reduce((sum, row) => sum + numberValue(row.source_gt?.auto_trigger_fp), 0);
    const sourceFn = window.reduce((sum, row) => sum + numberValue(row.source_gt?.manual_trigger_fn), 0);
    const sourcePrecision = sourceTp + sourceFp ? sourceTp / (sourceTp + sourceFp) : 0;
    const sourceRecall = sourceTp + sourceFn ? sourceTp / (sourceTp + sourceFn) : 0;

    const matrix = item.sim_estimate?.binary_backtest_sources;
    const matrixRows = matrix && typeof matrix === 'object'
      ? window.map((row) => (matrix as Record<string, Record<string, unknown>>)[row.version_key])
      : [];
    const matrixComplete = matrixRows.length === backtestWindowSize && matrixRows.every((row) => {
      if (!row) return false;
      const expected = numberValue(row.expected);
      const evaluated = numberValue(row.evaluated);
      const dpeCoverage = numberValue(row.dpe_coverage);
      return expected > 0 && evaluated === expected && dpeCoverage >= 1
        && cohortTriggerRate(row, 'positive_auto') != null
        && cohortTriggerRate(row, 'negative_auto') != null
        && cohortTriggerRate(row, 'positive_manual') != null;
    });
    let simTp = 0;
    let simFp = 0;
    let simFn = 0;
    if (matrixComplete) {
      matrixRows.forEach((row, rowIndex) => {
        const source = window[rowIndex].source_gt || {};
        const autoTp = numberValue(source.auto_trigger_tp);
        const autoFp = numberValue(source.auto_trigger_fp);
        const manualFn = numberValue(source.manual_trigger_fn);
        const positiveAutoRate = cohortTriggerRate(row, 'positive_auto') ?? 0;
        const negativeAutoRate = cohortTriggerRate(row, 'negative_auto') ?? 0;
        const positiveManualRate = cohortTriggerRate(row, 'positive_manual') ?? 0;
        simTp += autoTp * positiveAutoRate + manualFn * positiveManualRate;
        simFp += autoFp * negativeAutoRate;
        simFn += autoTp * (1 - positiveAutoRate) + manualFn * (1 - positiveManualRate);
      });
    }
    return [{
      version_key: item.version_key,
      actualPrecision: Math.round(sourcePrecision * 1000) / 10,
      actualRecall: Math.round(sourceRecall * 1000) / 10,
      simPrecision: matrixComplete && simTp + simFp ? Math.round(simTp / (simTp + simFp) * 1000) / 10 : undefined,
      simRecall: matrixComplete && simTp + simFn ? Math.round(simTp / (simTp + simFn) * 1000) / 10 : undefined,
    }];
  });
  const reproDomain = pctDomain(trend, ['repro']);
  const prDomain = pctDomain(backtestTrend, ['actualPrecision', 'actualRecall', 'simPrecision', 'simRecall']);
  const reproControls: Array<{ key: ReproMetric; label: string; color: string }> = [
    { key: 'repro', label: t('simReproRate'), color: chartColors.repro },
    { key: 'tp', label: 'TP', color: chartColors.model },
    { key: 'fn', label: 'FN', color: chartColors.fn },
    { key: 'fp', label: 'FP', color: chartColors.fp },
  ];
  const hasBinaryMatrix = backtestTrend.some((item) => item.simPrecision != null || item.simRecall != null);

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
          <CardHeader className="min-h-[86px] flex-row items-start justify-between gap-2 px-5 pb-2 pt-4">
            <div className="min-w-0">
              <CardTitle>{t('continuousReproTrend')}</CardTitle>
              <p className="mt-0.5 text-[12px] leading-4 text-muted-foreground">{t('continuousReproTrendSubtitle')}</p>
            </div>
            <div className="flex max-w-[390px] shrink-0 flex-wrap items-center justify-end gap-1">
              {reproControls.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  aria-pressed={visibleReproMetrics[item.key]}
                  style={{ '--toggle-color': item.color } as CSSProperties}
                  className={cn(
                    'chart-toggle inline-flex h-7 items-center gap-1 rounded-md border border-border/80 px-2 text-[11px] font-semibold focus:outline-none focus:ring-1 focus:ring-ring',
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
                  'chart-toggle inline-flex h-7 items-center rounded-md border border-border/80 px-2 text-[11px] font-semibold focus:outline-none focus:ring-1 focus:ring-ring',
                )}
                onClick={() => setShowTrendLabels((value) => !value)}
              >
                {showTrendLabels ? t('hideValueLabels') : t('showValueLabels')}
              </button>
            </div>
          </CardHeader>
          <CardContent className="h-80 px-4 pb-4 pt-0">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={trend}
                margin={{ top: 18, right: 20, left: 0, bottom: 8 }}
                barCategoryGap="18%"
                barGap={2}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border) / 0.68)" vertical={false} />
                <XAxis
                  dataKey="version_key"
                  scale="point"
                  tickLine={false}
                  axisLine={false}
                  interval={0}
                  minTickGap={0}
                  height={40}
                  tickMargin={10}
                  padding={{ left: 44, right: 44 }}
                  tick={<VersionTick />}
                />
                <YAxis yAxisId="rate" domain={reproDomain} tickLine={false} axisLine={false} width={38} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                <YAxis yAxisId="count" hide width={0} />
                <Tooltip {...tooltipProps} cursor={<ChartHoverCursor />} />
                {visibleReproMetrics.tp ? (
                  <Bar yAxisId="count" dataKey="tp" fill={chartColors.model} fillOpacity={0.78} radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false} />
                ) : null}
                {visibleReproMetrics.fn ? (
                  <Bar yAxisId="count" dataKey="fn" fill={chartColors.fn} fillOpacity={0.78} radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false} />
                ) : null}
                {visibleReproMetrics.fp ? (
                  <Bar yAxisId="count" dataKey="fp" fill={chartColors.fp} fillOpacity={0.78} radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false} />
                ) : null}
                {visibleReproMetrics.repro ? (
                  <Line yAxisId="rate" type="linear" dataKey="repro" stroke={chartColors.repro} strokeWidth={3} dot={hollowDot(chartColors.repro, 4)} activeDot={hollowDot(chartColors.repro, 5.5)} isAnimationActive={false}>
                    {showTrendLabels ? <LabelList dataKey="repro" content={renderTrendLabel(chartColors.repro, -8, -14)} /> : null}
                  </Line>
                ) : null}
              </ComposedChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="min-h-[86px] flex-row items-start justify-between gap-2 px-5 pb-2 pt-4">
            <div className="min-w-0">
              <CardTitle>{t('binaryBacktestPr')}</CardTitle>
              <p className="mt-0.5 text-[12px] leading-4 text-muted-foreground">{t('binaryBacktestPrSubtitle')}</p>
              <div className="mt-2 flex flex-wrap gap-3 text-[11px] font-semibold text-muted-foreground">
                <span className="inline-flex items-center gap-1.5"><LegendDot color={chartColors.precision} />{t('actualPrecision')}</span>
                <span className="inline-flex items-center gap-1.5"><LegendDot color={chartColors.recall} />{t('actualRecall')}</span>
                {hasBinaryMatrix ? <span className="inline-flex items-center gap-1.5"><LegendDot color={chartColors.repro} />{t('simPR')}</span> : null}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
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
              <Badge variant="secondary">{current.version_key}</Badge>
            </div>
          </CardHeader>
          <CardContent className="relative h-80 px-4 pb-4 pt-0">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={backtestTrend} margin={{ top: 18, right: 42, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border) / 0.68)" vertical={false} />
                <XAxis dataKey="version_key" scale="point" tickLine={false} axisLine={false} interval={0} minTickGap={0} height={40} tickMargin={10} padding={{ left: 44, right: 44 }} tick={<VersionTick />} />
                <YAxis domain={prDomain} tickLine={false} axisLine={false} width={40} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                <Tooltip {...tooltipProps} cursor={<ChartHoverCursor />} />
                <Line type="linear" dataKey="actualPrecision" name={t('actualPrecision')} stroke={chartColors.precision} strokeWidth={2.2} dot={hollowDot(chartColors.precision)} activeDot={hollowDot(chartColors.precision, 5)} isAnimationActive={false}>
                  {showTrendLabels ? <LabelList dataKey="actualPrecision" content={renderTrendLabel(chartColors.precision, 8, -12)} /> : null}
                </Line>
                <Line type="linear" dataKey="actualRecall" name={t('actualRecall')} stroke={chartColors.recall} strokeWidth={2.2} dot={hollowDot(chartColors.recall)} activeDot={hollowDot(chartColors.recall, 5)} isAnimationActive={false}>
                  {showTrendLabels ? <LabelList dataKey="actualRecall" content={renderTrendLabel(chartColors.recall, -8, 12)} /> : null}
                </Line>
                {hasBinaryMatrix ? (
                  <>
                    <Line type="linear" dataKey="simPrecision" name={t('simPrecisionEstimate')} stroke={chartColors.fp} strokeDasharray="5 4" strokeWidth={2.2} dot={hollowDot(chartColors.fp)} activeDot={hollowDot(chartColors.fp, 5)} isAnimationActive={false} />
                    <Line type="linear" dataKey="simRecall" name={t('simRecallEstimate')} stroke={chartColors.repro} strokeDasharray="5 4" strokeWidth={2.2} dot={hollowDot(chartColors.repro)} activeDot={hollowDot(chartColors.repro, 5)} isAnimationActive={false} />
                  </>
                ) : null}
              </LineChart>
            </ResponsiveContainer>
            {!hasBinaryMatrix ? (
              <div className="pointer-events-none absolute right-4 top-4 rounded-md border border-border/80 bg-card/90 px-3 py-2 text-xs text-muted-foreground shadow-sm">
                {t('binaryMatrixPending')}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      {aggregateRows.length ? (
        <Card className="overflow-hidden">
          <CardHeader className="border-b border-border/70">
            <div>
              <CardTitle>{t('sourceVsSim')}</CardTitle>
              <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{t('sourceVsSimSubtitle')}</p>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="max-w-full overflow-x-auto">
              <table className="w-full min-w-[1160px] text-left text-[13px]">
                <thead className="bg-muted/45 dark:bg-white/[0.025]">
                  <tr>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('version')}</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('dataSource')}</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">Pos-auto / Neg-auto / Pos-manual</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('onlinePR')}</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('offlinePR')}</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('simPR')}</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('simJobs')}</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">Auto + / FP / Manual</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">P / R / Spec / Acc</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('evaluatedCases')}</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('dpeCoverage')}</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('qualityGate')}</th>
                  </tr>
                </thead>
                <tbody>
                  {aggregateRows.map((item) => {
                    const source = item.source_gt || {};
                    const sim = item.sim_estimate || {};
                    return (
                      <tr
                        key={item.version_key}
                        className="cursor-pointer border-t border-border/60 transition hover:bg-accent/35"
                        {...interactiveProps(() => onOpenIssues({ version: item.version_key }))}
                      >
                        <td className="px-4 py-3 align-middle">
                          <div className="font-semibold leading-5">{item.label || item.version_key}</div>
                          <div className="font-mono text-xs text-muted-foreground">{item.version_key}</div>
                        </td>
                        <td className="px-4 py-3 align-middle">
                          <div className="flex flex-col items-start gap-1">
                            <Badge variant={sim.data_source === 'query_report' ? 'success' : 'secondary'}>
                              {String(sim.data_source || 'config_fallback')}
                            </Badge>
                            <span className="text-xs text-muted-foreground">
                              {String(source.data_source || '-')}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 align-middle font-mono text-xs">
                          {numberValue(source.auto_trigger_tp)} / {numberValue(source.auto_trigger_fp)} / {numberValue(source.manual_trigger_fn)}
                        </td>
                        <td className="px-4 py-3 align-middle font-mono text-xs">
                          {maybePct(source.online_precision)} / {maybePct(source.online_recall)}
                        </td>
                        <td className="px-4 py-3 align-middle font-mono text-xs">
                          {maybePct(source.calculated_precision)} / {maybePct(source.calculated_recall)}
                        </td>
                        <td className="px-4 py-3 align-middle font-mono text-xs">
                          {pct(item.precision)} / {pct(item.recall)}
                        </td>
                        <td className="px-4 py-3 align-middle font-mono text-xs">
                          {sim.job_id ? String(sim.job_id) : `${String(sim.pos_job_id || '-')} / ${String(sim.neg_job_id || '-')}`}
                        </td>
                        <td className="px-4 py-3 align-middle font-mono text-xs">
                          {pct(item.positive_auto_repro_rate)} / {pct(item.negative_auto_repro_rate)} / {pct(item.positive_manual_repro_rate)}
                        </td>
                        <td className="px-4 py-3 align-middle font-mono text-xs">
                          {pct(item.precision)} / {pct(item.recall)} / {pct(item.specificity)} / {pct(item.accuracy)}
                        </td>
                        <td className="px-4 py-3 align-middle font-mono text-xs">
                          {formatCount(item.evaluated_cases)} / {formatCount(numberValue(source.total_scenarios))}
                        </td>
                        <td className="px-4 py-3 align-middle font-mono text-xs">
                          {pct(item.dpe_coverage)}
                        </td>
                        <td className="px-4 py-3 align-middle">
                          <Badge variant={item.quality_gate_passed ? 'success' : 'destructive'}>
                            {item.quality_gate_passed ? t('qualityPassed') : t('qualityFailed')}
                          </Badge>
                        </td>
                      </tr>
                    );
                  })}
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
