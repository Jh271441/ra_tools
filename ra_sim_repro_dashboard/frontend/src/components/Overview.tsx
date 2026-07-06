import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type LabelProps,
} from 'recharts';
import { useState, type KeyboardEvent } from 'react';
import { Activity, ArrowDownRight, ArrowUpRight, CircleAlert, Gauge, ShieldCheck, Target } from 'lucide-react';
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

type TrendMetric = 'precision' | 'recall' | 'f1';

type TrendRow = {
  version_key: string;
  version: string;
  precision: number;
  recall: number;
  f1: number;
};

const trendMetricKeys: TrendMetric[] = ['precision', 'recall', 'f1'];

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

function maybePct(value: unknown) {
  const numeric = numberValue(value);
  return numeric ? pct(numeric) : '-';
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

function trendDomain(rows: TrendRow[], keys: TrendMetric[]): [number, number] {
  const values = rows.flatMap((item) => keys.map((key) => item[key])).filter(Number.isFinite);
  if (!values.length) return [0, 100];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const paddedMin = Math.max(0, Math.floor((min - 5) / 5) * 5);
  const paddedMax = Math.min(100, Math.ceil((max + 5) / 5) * 5);
  if (paddedMax - paddedMin >= 15) return [paddedMin, paddedMax];
  const center = (min + max) / 2;
  return [Math.max(0, Math.floor((center - 8) / 5) * 5), Math.min(100, Math.ceil((center + 8) / 5) * 5)];
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
  const [visibleTrendMetrics, setVisibleTrendMetrics] = useState<Record<TrendMetric, boolean>>({
    precision: true,
    recall: true,
    f1: true,
  });
  const [showTrendLabels, setShowTrendLabels] = useState(true);

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
    { label: t('fpSuppressRate'), value: pct(current.fp_suppress_rate), delta: summary.deltas.fp_suppress_rate, icon: CircleAlert, inverse: true, filters: { version: current.version_key, precisionLabel: 'FP' } },
  ];

  const trend = comparison.map((item) => ({
    version_key: item.version_key,
    version: item.label || item.version_key,
    precision: Math.round(item.precision * 1000) / 10,
    recall: Math.round(item.recall * 1000) / 10,
    f1: Math.round(item.f1 * 1000) / 10,
  }));
  const activeTrendMetrics = trendMetricKeys.filter((key) => visibleTrendMetrics[key]);
  const precisionRecallDomain = trendDomain(trend, activeTrendMetrics.length ? activeTrendMetrics : trendMetricKeys);
  const trendControls: Array<{ key: TrendMetric; label: string; color: string }> = [
    { key: 'precision', label: t('precision'), color: chartColors.precision },
    { key: 'recall', label: t('recall'), color: chartColors.recall },
    { key: 'f1', label: t('f1'), color: chartColors.f1 },
  ];

  function toggleTrendMetric(key: TrendMetric) {
    setVisibleTrendMetrics((current) => {
      const activeCount = trendMetricKeys.filter((item) => current[item]).length;
      if (current[key] && activeCount === 1) return current;
      return { ...current, [key]: !current[key] };
    });
  }

  const breakdown = comparison.map((item) => ({
    version_key: item.version_key,
    version: item.label || item.version_key,
    model: Math.round(item.model_repro_rate * 1000) / 10,
    fn: Math.round(item.fn_fallback_rate * 1000) / 10,
    fp: Math.round(item.fp_suppress_rate * 1000) / 10,
    repro: Math.round(item.sim_repro_rate * 1000) / 10,
  }));
  const aggregateRows = comparison.filter((item) => item.source_gt || item.sim_estimate);

  return (
    <div className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {kpis.map((item) => {
          const deltaValue = item.delta ?? 0;
          const healthy = item.inverse ? deltaValue <= 0 : deltaValue >= 0;
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

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-3">
            <div>
              <CardTitle>{t('versionTrend')}</CardTitle>
              <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{t('versionTrendSubtitle')}</p>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-1.5">
              {trendControls.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  aria-pressed={visibleTrendMetrics[item.key]}
                  className={cn(
                    'inline-flex h-8 items-center gap-1 rounded-md border border-border/80 bg-card/60 px-2.5 text-xs font-semibold transition hover:border-primary/40 hover:bg-accent focus:outline-none focus:ring-1 focus:ring-ring',
                    !visibleTrendMetrics[item.key] && 'opacity-45 grayscale',
                  )}
                  onClick={() => toggleTrendMetric(item.key)}
                >
                  <LegendDot color={item.color} />
                  {item.label}
                </button>
              ))}
              <button
                type="button"
                aria-pressed={showTrendLabels}
                className={cn(
                  'inline-flex h-8 items-center rounded-md border border-border/80 bg-card/60 px-2.5 text-xs font-semibold transition hover:border-primary/40 hover:bg-accent focus:outline-none focus:ring-1 focus:ring-ring',
                  showTrendLabels && 'border-primary/30 bg-accent text-accent-foreground',
                )}
                onClick={() => setShowTrendLabels((value) => !value)}
              >
                {showTrendLabels ? t('hideValueLabels') : t('showValueLabels')}
              </button>
            </div>
          </CardHeader>
          <CardContent className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={trend}
                margin={{ top: 28, right: 48, left: 2, bottom: 12 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border) / 0.68)" vertical={false} />
                <XAxis
                  dataKey="version"
                  tickLine={false}
                  axisLine={false}
                  interval={0}
                  minTickGap={0}
                  height={44}
                  tickMargin={12}
                  padding={{ left: 28, right: 28 }}
                  tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }}
                />
                <YAxis domain={precisionRecallDomain} tickLine={false} axisLine={false} width={40} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                <Tooltip {...tooltipProps} />
                {visibleTrendMetrics.precision ? (
                  <Line type="linear" dataKey="precision" stroke={chartColors.precision} strokeWidth={2.4} dot={hollowDot(chartColors.precision)} activeDot={hollowDot(chartColors.precision, 5)} isAnimationActive={false}>
                    {showTrendLabels ? <LabelList dataKey="precision" content={renderTrendLabel(chartColors.precision, 8, -12)} /> : null}
                  </Line>
                ) : null}
                {visibleTrendMetrics.recall ? (
                  <Line type="linear" dataKey="recall" stroke={chartColors.recall} strokeWidth={2.4} dot={hollowDot(chartColors.recall)} activeDot={hollowDot(chartColors.recall, 5)} isAnimationActive={false}>
                    {showTrendLabels ? <LabelList dataKey="recall" content={renderTrendLabel(chartColors.recall, -8, 12)} /> : null}
                  </Line>
                ) : null}
                {visibleTrendMetrics.f1 ? (
                  <Line type="linear" dataKey="f1" stroke={chartColors.f1} strokeWidth={2.4} dot={hollowDot(chartColors.f1)} activeDot={hollowDot(chartColors.f1, 5)} isAnimationActive={false}>
                    {showTrendLabels ? <LabelList dataKey="f1" content={renderTrendLabel(chartColors.f1, 8, 12)} /> : null}
                  </Line>
                ) : null}
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-start justify-between gap-3">
            <div>
              <CardTitle>{t('reproBreakdown')}</CardTitle>
              <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{t('reproBreakdownSubtitle')}</p>
            </div>
            <Badge variant="secondary">{current.total_cases} {t('cases')}</Badge>
          </CardHeader>
          <CardContent className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={breakdown} margin={{ top: 16, right: 20, left: 2, bottom: 12 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border) / 0.68)" vertical={false} />
                <XAxis dataKey="version" tickLine={false} axisLine={false} interval={0} minTickGap={0} height={44} tickMargin={12} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                <YAxis domain={[0, 100]} tickLine={false} axisLine={false} width={40} tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }} />
                <Tooltip {...tooltipProps} />
                <Bar dataKey="repro" fill={chartColors.repro} radius={[4, 4, 0, 0]} />
                <Bar dataKey="model" fill={chartColors.model} radius={[4, 4, 0, 0]} />
                <Bar dataKey="fn" fill={chartColors.fn} radius={[4, 4, 0, 0]} />
                <Bar dataKey="fp" fill={chartColors.fp} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
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
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">TP/FP/FN</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('onlinePR')}</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('offlinePR')}</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('simPR')}</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('simJobs')}</th>
                    <th className="h-10 px-4 text-xs font-medium uppercase text-muted-foreground">{t('scenarioTotal')}</th>
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
                          {String(sim.pos_job_id || '-')} / {String(sim.neg_job_id || '-')}
                        </td>
                        <td className="px-4 py-3 align-middle font-mono text-xs">
                          {numberValue(source.total_scenarios)}
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
