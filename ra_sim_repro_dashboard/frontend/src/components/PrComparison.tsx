import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CartesianGrid, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, type LabelProps } from 'recharts';
import type { KpiSummary } from '../types';
import { releaseChartRows, releaseTooltip, releaseXAxis } from '../lib/releaseChart';

export interface PrPoint {
  version_key: string;
  actualPrecision?: number;
  actualRecall?: number;
  simPrecision?: number;
  simRecall?: number;
}

type MetricMode = 'precision' | 'recall' | 'all';
type SeriesKey = keyof Pick<PrPoint, 'actualPrecision' | 'actualRecall' | 'simPrecision' | 'simRecall'>;

const seriesColors: Record<SeriesKey, string> = {
  actualPrecision: 'hsl(var(--chart-blue))',
  simPrecision: 'hsl(var(--chart-blue-soft))',
  actualRecall: 'hsl(var(--chart-orange))',
  simRecall: 'hsl(var(--chart-orange-soft))',
};
const percent = (value?: number) => value == null ? '—' : `${value.toFixed(1)}%`;
const gap = (actual?: number, sim?: number) => actual == null || sim == null
  ? '—' : `${sim - actual > 0 ? '+' : ''}${(sim - actual).toFixed(1)} pp`;
function percentageScale(rows: PrPoint[], keys: SeriesKey[]): { domain: [number, number]; ticks: number[] } {
  const values = rows.flatMap((row) => keys.map((key) => row[key])).filter((value): value is number => value != null);
  if (!values.length) return { domain: [0, 100], ticks: [0, 25, 50, 75, 100] };
  const minValue = Math.max(0, Math.floor(Math.min(...values)));
  const maxValue = Math.min(100, Math.ceil(Math.max(...values)));
  if (minValue === maxValue) {
    const lower = Math.max(0, minValue - 3);
    const upper = Math.min(100, maxValue + 3);
    return { domain: [lower, upper], ticks: [lower, upper] };
  }

  // Keep percentage labels readable: integer ticks with an adaptive 3–5 pp
  // interval. The bounds are expanded to the selected step so every data
  // point remains inside the plot and the tick spacing stays uniform.
  const candidates = [3, 4, 5].map((step) => {
    const lower = Math.floor(minValue / step) * step;
    const upper = Math.ceil(maxValue / step) * step;
    const intervals = Math.max(1, Math.round((upper - lower) / step));
    return { step, lower, upper, intervals };
  });
  const selected = candidates
    .filter((candidate) => candidate.upper <= 100 && candidate.lower >= 0)
    .sort((a, b) => {
      const intervalDistance = Math.abs(a.intervals - 5) - Math.abs(b.intervals - 5);
      if (intervalDistance !== 0) return intervalDistance;
      const spanDistance = (a.upper - a.lower) - (b.upper - b.lower);
      if (spanDistance !== 0) return spanDistance;
      return a.step - b.step;
    })[0] ?? candidates[0];
  const ticks = Array.from(
    { length: selected.intervals + 1 },
    (_, index) => selected.lower + index * selected.step,
  );
  return { domain: [selected.lower, selected.upper], ticks };
}

export function PrComparison({ rows, comparison, mode }: {
  rows: PrPoint[];
  comparison: KpiSummary[];
  mode: 'same-version' | 'rolling';
}) {
  const { t } = useTranslation();
  const [metricMode, setMetricMode] = useState<MetricMode>('all');
  const bothMetrics = metricMode === 'all';
  const visibleMetrics = {
    precision: metricMode === 'precision' || bothMetrics,
    recall: metricMode === 'recall' || bothMetrics,
  };
  const renderLineLabel = (key: SeriesKey) => (props: LabelProps) => {
    const x = Number(props.x);
    const y = Number(props.y);
    if (!Number.isFinite(x) || !Number.isFinite(y) || props.value == null) return null;
    const index = Number((props as LabelProps & { index?: number }).index);
    const value = Number(props.value);
    const ordered = Number.isFinite(index) ? series
      .map((item) => ({ key: item.key, value: rows[index]?.[item.key] }))
      .filter((item): item is { key: SeriesKey; value: number } => item.value != null)
      .sort((a, b) => b.value - a.value || a.key.localeCompare(b.key)) : [];
    const rank = ordered.findIndex((item) => item.key === key);
    const collisionThreshold = 1.5;
    let groupStart = rank;
    let groupEnd = rank;
    while (groupStart > 0 && ordered[groupStart - 1].value - ordered[groupStart].value < collisionThreshold) groupStart -= 1;
    while (groupEnd >= 0 && groupEnd < ordered.length - 1 && ordered[groupEnd].value - ordered[groupEnd + 1].value < collisionThreshold) groupEnd += 1;
    // Keep the lower label close to its point; move only higher labels farther
    // upward when their rendered text would collide.
    const dy = -12 - Math.max(0, groupEnd - rank) * 14;
    return <text x={x} y={y + dy} textAnchor="middle" fill="hsl(var(--foreground))" stroke="hsl(var(--card))" strokeWidth={3} paintOrder="stroke" fontSize={11} fontWeight={600}>
      {percent(value)}
    </text>;
  };

  const reason = (row: PrPoint) => {
    if (mode === 'rolling') return t('prRollingMissing');
    const item = comparison.find((value) => value.version_key === row.version_key);
    const raw = item?.sim_estimate?.same_version_projection;
    const projection = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
    const coverage = projection.population_coverage;
    const reasons: string[] = [];
    if (row.actualPrecision == null || row.actualRecall == null || projection.reason === 'missing_online_population') {
      reasons.push(t('prOnlineMissing'));
    } else if (projection.reason === 'population_coverage_out_of_range') {
      reasons.push(t('prPopulationMismatch', {
        coverage: typeof coverage === 'number' ? (coverage * 100).toFixed(1) : '—',
        min: typeof projection.minimum_population_coverage === 'number' ? projection.minimum_population_coverage * 100 : 95,
        max: typeof projection.maximum_population_coverage === 'number' ? projection.maximum_population_coverage * 100 : 105,
      }));
    } else if (row.simPrecision == null || row.simRecall == null) {
      reasons.push(t('prSimulationMissing'));
    }
    const failed = Number(item?.sim_estimate?.terminal_failed || 0);
    if (failed > 0) reasons.push(t('prFailedCases', { count: failed }));
    return reasons.join('；');
  };

  const series = (Object.entries({
    actualPrecision: visibleMetrics.precision,
    simPrecision: visibleMetrics.precision,
    actualRecall: visibleMetrics.recall,
    simRecall: visibleMetrics.recall,
  }) as Array<[SeriesKey, boolean]>)
    .filter(([, enabled]) => enabled)
    .map(([key]) => ({
      key,
      label: `${key.startsWith('actual') ? t('prOnline') : t('prSimulation')} ${t(key.includes('Precision') ? 'precision' : 'recall')}`,
      color: seriesColors[key],
    }));
  const scale = percentageScale(rows, series.map((item) => item.key));
  const chartMargin = { top: 28, right: 18, bottom: 4, left: 0 };
  const chartRows = releaseChartRows(rows);

  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
        {series.map((item) => <span key={item.key} className="inline-flex items-center gap-2">
          <span className="w-7 border-t-[3px]" style={{ borderColor: item.color }} />
          {item.label}
        </span>)}
      </div>
      <div className="inline-flex rounded-md border border-border bg-muted/30 p-0.5" role="group" aria-label={t('prMetricSwitch')}>
        {(['precision', 'recall', 'all'] as const).map((value) => (
          <button
            key={value}
            type="button"
            className={`rounded px-3 py-1.5 text-xs font-semibold transition ${metricMode === value ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
            aria-pressed={metricMode === value}
            onClick={() => setMetricMode(value)}
          >
            {value === 'all' ? t('all') : t(value)}
          </button>
        ))}
      </div>
    </div>
    <div className="min-w-0" aria-label={bothMetrics ? `${t('precision')} / ${t('recall')}` : t(metricMode)}>
      <div className="overflow-x-auto">
        <div className="h-72 min-w-[680px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartRows} margin={chartMargin}>
              <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 5" />
              <XAxis {...releaseXAxis(rows)} />
              <YAxis domain={scale.domain} ticks={scale.ticks} tickFormatter={(value: number) => `${value.toFixed(0)}%`} width={52} tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))', textAnchor: 'end', dx: 0 }} axisLine={false} tickLine={false} />
              <Tooltip {...releaseTooltip} content={({ active, payload }) => {
                const row = payload?.[0]?.payload as PrPoint | undefined;
                if (!active || !row) return null;
                return <div className="max-w-xs rounded-lg border border-border bg-card p-3 text-xs text-foreground shadow-lg">
                  <p className="mb-2 font-semibold">{row.version_key}</p>
                  {series.map((item) => <p key={item.key} style={{ color: item.color }}>{item.label}: <strong>{percent(row[item.key])}</strong></p>)}
                  {bothMetrics ? <p className="mt-2 text-muted-foreground">{t('prGap')}: P {gap(row.actualPrecision, row.simPrecision)} · R {gap(row.actualRecall, row.simRecall)}</p> : null}
                  {series.some((item) => row[item.key] == null) ? <p className="mt-2 text-muted-foreground">{reason(row)}</p> : null}
                </div>;
              }} />
              {series.map((item) => <Line key={item.key} type="linear" dataKey={item.key} name={item.label} stroke={item.color} strokeWidth={2.5} dot={{ r: 3, fill: 'hsl(var(--card))', strokeWidth: 2 }} activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false} />)}
              {series.map((item) => <Line key={`${item.key}-labels`} type="linear" dataKey={item.key} stroke="transparent" strokeWidth={0} dot={false} activeDot={false} connectNulls={false} isAnimationActive={false} legendType="none">
                <LabelList dataKey={item.key} content={renderLineLabel(item.key)} />
              </Line>)}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  </div>;
}
