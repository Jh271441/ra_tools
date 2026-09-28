import { useTranslation } from 'react-i18next';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { KpiSummary } from '../types';

export interface PrPoint {
  version_key: string;
  actualPrecision?: number;
  actualRecall?: number;
  simPrecision?: number;
  simRecall?: number;
}

const onlineColor = 'hsl(var(--chart-blue))';
const simColor = 'hsl(var(--chart-green))';
const percent = (value?: number) => value == null ? '—' : `${value.toFixed(1)}%`;
const gap = (actual?: number, sim?: number) => actual == null || sim == null
  ? '—' : `${sim - actual > 0 ? '+' : ''}${(sim - actual).toFixed(1)} pp`;
const shortVersion = (key: string) => key.replace(/^.*(\d{4})(\d{2})(\d{2})$/, '$2-$3');

export function PrComparison({ rows, comparison, mode, domain }: {
  rows: PrPoint[];
  comparison: KpiSummary[];
  mode: 'same-version' | 'rolling';
  domain: [number, number];
}) {
  const { t } = useTranslation();
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

  return <div className="space-y-4">
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-2"><span className="w-7 border-t-[3px]" style={{ borderColor: onlineColor }} />{t('prOnline')}</span>
      <span className="inline-flex items-center gap-2"><span className="w-7 border-t-[3px] border-dashed" style={{ borderColor: simColor }} />{t('prSimulation')}</span>
      <span>{t('prHoverHint')}</span>
    </div>
    {mode === 'rolling' ? <p className="rounded-md bg-muted/50 px-3 py-2 text-xs text-muted-foreground">{t('prRecallDifferent')}</p> : null}
    <div className="grid gap-4 xl:grid-cols-2">
      {(['precision', 'recall'] as const).map((metric) => {
        const actualKey = metric === 'precision' ? 'actualPrecision' : 'actualRecall';
        const simKey = metric === 'precision' ? 'simPrecision' : 'simRecall';
        return <section key={metric} className="min-w-0 rounded-lg border border-border/70 bg-muted/10 p-3" aria-label={t(metric)}>
          <h3 className="mb-2 text-sm font-semibold">{t(metric)} <span className="font-normal text-muted-foreground">{metric === 'precision' ? 'Precision' : 'Recall'}</span></h3>
          <div className="overflow-x-auto">
            <div className="h-60 min-w-[560px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rows} syncId="pr-comparison" margin={{ top: 12, right: 18, bottom: 4, left: 0 }}>
                  <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 5" />
                  <XAxis dataKey="version_key" interval={0} tickFormatter={shortVersion} tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} padding={{ left: 12, right: 12 }} height={30} />
                  <YAxis domain={domain} tickFormatter={(v: number) => `${v}%`} width={46} tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} />
                  <Tooltip content={({ active, payload }) => {
                    const row = payload?.[0]?.payload as PrPoint | undefined;
                    if (!active || !row) return null;
                    return <div className="max-w-xs rounded-lg border border-border bg-card p-3 text-xs text-foreground shadow-lg">
                      <p className="mb-2 font-semibold">{row.version_key}</p>
                      <p>{t('prOnline')}: <strong>{percent(row[actualKey])}</strong></p>
                      <p>{t('prSimulation')}: <strong>{percent(row[simKey])}</strong></p>
                      {mode === 'same-version' || metric === 'precision' ? <p className="mt-2 border-t border-border pt-2">{t('prGap')}: <strong>{gap(row[actualKey], row[simKey])}</strong></p> : null}
                      {row[simKey] == null ? <p className="mt-2 text-muted-foreground">{reason(row)}</p> : null}
                    </div>;
                  }} />
                  <Line type="linear" dataKey={actualKey} name={t('prOnline')} stroke={onlineColor} strokeWidth={2.5} dot={{ r: 3, fill: 'hsl(var(--card))', strokeWidth: 2 }} activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false} />
                  <Line type="linear" dataKey={simKey} name={t('prSimulation')} stroke={simColor} strokeWidth={2.5} strokeDasharray="6 4" dot={{ r: 3, fill: 'hsl(var(--card))', strokeWidth: 2 }} activeDot={{ r: 5 }} connectNulls={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>;
      })}
    </div>
    <details className="rounded-lg border border-border/70">
      <summary className="cursor-pointer px-3 py-2 text-xs font-medium">{t('prValuesTable')}</summary>
      <div className="overflow-x-auto px-3 pb-3">
        <table className="w-full min-w-[600px] text-left text-xs tabular-nums">
          <thead><tr className="border-b border-border text-muted-foreground">
            {[t('prVersion'), `${t('precision')} · ${t('prOnline')}`, `${t('precision')} · ${t('prSimulation')}`, `${t('recall')} · ${t('prOnline')}`, `${t('recall')} · ${t('prSimulation')}`].map((label) => <th className="py-2 pr-3 font-medium" key={label}>{label}</th>)}
          </tr></thead>
          <tbody>{rows.map((row) => <tr key={row.version_key} className="border-b border-border/40">
            <td className="py-2 pr-3" title={row.version_key}>{shortVersion(row.version_key)}</td>
            {[row.actualPrecision, row.simPrecision, row.actualRecall, row.simRecall].map((value, i) => <td key={i} className="py-2 pr-3">{percent(value)}</td>)}
          </tr>)}</tbody>
        </table>
      </div>
    </details>
  </div>;
}
