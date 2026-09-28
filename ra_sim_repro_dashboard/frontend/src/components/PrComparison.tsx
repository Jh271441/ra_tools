import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CartesianGrid, LabelList, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { KpiSummary } from '../types';

export interface PrPoint {
  version_key: string;
  actualPrecision?: number;
  actualRecall?: number;
  simPrecision?: number;
  simRecall?: number;
}

type Metric = 'precision' | 'recall';
type SeriesKey = keyof Pick<PrPoint, 'actualPrecision' | 'actualRecall' | 'simPrecision' | 'simRecall'>;

const seriesColors: Record<SeriesKey, string> = {
  actualPrecision: 'hsl(var(--chart-blue))',
  simPrecision: 'hsl(var(--chart-green))',
  actualRecall: 'hsl(var(--chart-orange))',
  simRecall: 'hsl(var(--chart-violet))',
};
const percent = (value?: number) => value == null ? '—' : `${value.toFixed(1)}%`;
const gap = (actual?: number, sim?: number) => actual == null || sim == null
  ? '—' : `${sim - actual > 0 ? '+' : ''}${(sim - actual).toFixed(1)} pp`;
const shortVersion = (key: string) => {
  const dated = key.match(/(?:^|[-_])(\d{4})[-_](\d{2})[-_](\d{2})/);
  if (dated) return `${dated[2]}-${dated[3]}`;
  const compact = key.match(/(\d{8})/);
  if (compact) return `${compact[1].slice(4, 6)}-${compact[1].slice(6, 8)}`;
  return key.length > 10 ? key.slice(-10) : key;
};

export function PrComparison({ rows, comparison, mode }: {
  rows: PrPoint[];
  comparison: KpiSummary[];
  mode: 'same-version' | 'rolling';
}) {
  const { t } = useTranslation();
  const [visibleMetrics, setVisibleMetrics] = useState<Record<Metric, boolean>>({ precision: true, recall: false });
  const bothMetrics = visibleMetrics.precision && visibleMetrics.recall;

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
      dashed: key.startsWith('sim'),
    }));

  return <div className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
        {series.map((item) => <span key={item.key} className="inline-flex items-center gap-2">
          <span className="w-7 border-t-[3px]" style={{ borderColor: item.color, borderStyle: item.dashed ? 'dashed' : 'solid' }} />
          {item.label}
        </span>)}
        <span>{t('prHoverHint')}</span>
      </div>
      <div className="inline-flex rounded-md border border-border bg-muted/30 p-0.5" role="group" aria-label={t('prMetricSwitch')}>
        {(['precision', 'recall'] as const).map((value) => (
          <button
            key={value}
            type="button"
            className={`rounded px-3 py-1.5 text-xs font-semibold transition ${visibleMetrics[value] ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
            aria-pressed={visibleMetrics[value]}
            onClick={() => setVisibleMetrics((current) => {
              if (current[value] && Object.values(current).filter(Boolean).length === 1) return current;
              return { ...current, [value]: !current[value] };
            })}
          >
            {t(value)}
          </button>
        ))}
      </div>
    </div>
    {mode === 'rolling' ? <p className="rounded-md bg-muted/50 px-3 py-2 text-xs text-muted-foreground">{t('prRecallDifferent')}</p> : null}
    <section className="min-w-0 rounded-lg border border-border/70 bg-muted/10 p-3" aria-label={bothMetrics ? `${t('precision')} / ${t('recall')}` : t(visibleMetrics.precision ? 'precision' : 'recall')}>
      <h3 className="mb-2 text-sm font-semibold">{bothMetrics ? `${t('precision')} / ${t('recall')}` : t(visibleMetrics.precision ? 'precision' : 'recall')}</h3>
      <div className="overflow-x-auto">
        <div className="h-72 min-w-[680px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 12, right: 18, bottom: 4, left: 0 }}>
              <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 5" />
              <XAxis dataKey="version_key" interval={Math.max(0, Math.ceil(rows.length / 12) - 1)} tickFormatter={shortVersion} tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} padding={{ left: 12, right: 12 }} height={30} />
              <YAxis domain={[60, 100]} ticks={[60, 70, 80, 90, 100]} tickFormatter={(value: number) => `${value}%`} width={46} tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} />
              <Tooltip content={({ active, payload }) => {
                const row = payload?.[0]?.payload as PrPoint | undefined;
                if (!active || !row) return null;
                return <div className="max-w-xs rounded-lg border border-border bg-card p-3 text-xs text-foreground shadow-lg">
                  <p className="mb-2 font-semibold">{row.version_key}</p>
                  {series.map((item) => <p key={item.key} style={{ color: item.color }}>{item.label}: <strong>{percent(row[item.key])}</strong></p>)}
                  {bothMetrics ? <p className="mt-2 text-muted-foreground">{t('prGap')}: P {gap(row.actualPrecision, row.simPrecision)} · R {gap(row.actualRecall, row.simRecall)}</p> : null}
                  {series.some((item) => row[item.key] == null) ? <p className="mt-2 text-muted-foreground">{reason(row)}</p> : null}
                </div>;
              }} />
              {series.map((item) => <Line key={item.key} type="linear" dataKey={item.key} name={item.label} stroke={item.color} strokeWidth={2.5} strokeDasharray={item.dashed ? '6 4' : undefined} dot={{ r: 3, fill: 'hsl(var(--card))', strokeWidth: 2 }} activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false}>
                {!bothMetrics ? <LabelList dataKey={item.key} position={item.dashed ? 'bottom' : 'top'} formatter={(value: number) => percent(value)} fill={item.color} fontSize={10} offset={8} /> : null}
              </Line>)}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  </div>;
}
