import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, CheckCircle2, ChevronDown, Download, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { request } from '../api/workflow';
import { releaseName } from '../lib/releaseName';
import { startVisiblePolling } from '../lib/visiblePolling';
import type { AutoTriageIssuePage, AutoTriageMetrics as Metrics, AutoTriageReport } from '../types/autoTriage';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Pagination, PAGE_SIZES } from './ui/pagination';
import { Select } from './ui/select';

const emptyRows: AutoTriageIssuePage = { items: [], total: 0, page: 1, page_size: 20, pages: 0 };

function readFilters() {
  const q = new URLSearchParams(window.location.search);
  const size = Number(q.get('page_size') || 20);
  const page = Number(q.get('page') || 1);
  return { release: q.get('release') || '@current', page: Number.isSafeInteger(page) && page > 0 ? page : 1,
    pageSize: PAGE_SIZES.includes(size) ? size : 20, query: (q.get('query') || '').slice(0, 200),
    dateStart: q.get('date_start') || '', dateEnd: q.get('date_end') || '',
    coverage: ['gap', 'reused'].includes(q.get('coverage') || '') ? q.get('coverage')! : '', changed: q.get('changed') === '1' };
}

export function AutoTriageMetrics() {
  const { t, i18n } = useTranslation();
  const [filters, setFilters] = useState(readFilters);
  const [draftDates, setDraftDates] = useState({ start: filters.dateStart, end: filters.dateEnd });
  const [data, setData] = useState<AutoTriageReport | null>(null);
  const [rows, setRows] = useState<AutoTriageIssuePage>(emptyRows);
  const [loadingRows, setLoadingRows] = useState(false);
  const [rowsError, setRowsError] = useState(false);
  const [rowsRetry, setRowsRetry] = useState(0);
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState('');
  const readGeneration = useRef(0);
  const summaryGeneration = useRef(0);
  const scopeKey = JSON.stringify([filters.release, filters.dateStart, filters.dateEnd]);
  const activeScope = useRef(scopeKey);
  activeScope.current = scopeKey;
  const result = data?.result;
  const refreshing = posting || ['queued', 'running'].includes(data?.refresh.status || '');
  const pct = (value: number | null | undefined) => value == null ? '—' : `${(value * 100).toFixed(2)}%`;
  const time = (value?: string) => value ? new Date(value).toLocaleString(i18n.language.startsWith('zh') ? 'zh-CN' : 'en-US', { timeZone: 'Asia/Shanghai' }) : '—';
  const label = (value: string | null) => value === null ? t('autoTriage.result_none') : value === '' ? t('autoTriage.result_empty') : t(`autoTriage.result_${value}`, { defaultValue: value });
  const group = (value: string | null) => t(`autoTriage.cohort_${value || 'excluded'}`);
  const datesValid = (!draftDates.start && !draftDates.end) || (draftDates.start && draftDates.end && draftDates.start <= draftDates.end);
  const scopeParams = (release: string) => {
    const q = new URLSearchParams({ release });
    if (filters.dateStart) q.set('date_start', filters.dateStart);
    if (filters.dateEnd) q.set('date_end', filters.dateEnd);
    return q;
  };

  const update = (next: Partial<typeof filters>) => setFilters(current => ({ ...current, ...next,
    page: next.page ?? (next.pageSize !== undefined || next.query !== undefined || next.coverage !== undefined || next.changed !== undefined || next.release !== undefined || next.dateStart !== undefined || next.dateEnd !== undefined ? 1 : current.page) }));

  useEffect(() => setDraftDates({ start: filters.dateStart, end: filters.dateEnd }), [filters.dateStart, filters.dateEnd]);

  useEffect(() => {
    const q = new URLSearchParams();
    if (filters.release !== '@current') q.set('release', filters.release);
    q.set('page', String(filters.page)); q.set('page_size', String(filters.pageSize));
    if (filters.query) q.set('query', filters.query);
    if (filters.coverage) q.set('coverage', filters.coverage);
    if (filters.changed) q.set('changed', '1');
    if (filters.dateStart) q.set('date_start', filters.dateStart);
    if (filters.dateEnd) q.set('date_end', filters.dateEnd);
    window.history.replaceState(window.history.state, '', `${window.location.pathname}?${q}`);
  }, [filters]);
  useEffect(() => {
    const pop = () => setFilters(readFilters());
    window.addEventListener('popstate', pop);
    return () => window.removeEventListener('popstate', pop);
  }, []);

  const load = useCallback(async () => {
    const generation = ++summaryGeneration.current;
    try {
      const value = await request<AutoTriageReport>(`/auto-triage?${scopeParams(filters.release)}`);
      if (generation === summaryGeneration.current && activeScope.current === scopeKey) { setData(value); setError(''); }
      return value;
    } catch { if (generation === summaryGeneration.current && activeScope.current === scopeKey) setError('loadError'); return null; }
  }, [scopeKey]);

  useEffect(() => {
    setData(null); setRows(emptyRows);
  }, [load]);
  useEffect(() => {
    if (posting) return;
    const stop = startVisiblePolling(load, value => ['queued', 'running'].includes(value.refresh.status || ''));
    return () => { summaryGeneration.current++; stop(); };
  }, [load, posting]);

  useEffect(() => {
    const generation = ++readGeneration.current;
    if (!result) { setRows(emptyRows); return; }
    setLoadingRows(true); setRowsError(false);
    const params = new URLSearchParams({ release: filters.release, page: String(filters.page), page_size: String(filters.pageSize),
      query: filters.query, coverage: filters.coverage, changed_only: String(filters.changed) });
    if (filters.dateStart) params.set('date_start', filters.dateStart);
    if (filters.dateEnd) params.set('date_end', filters.dateEnd);
    const timer = window.setTimeout(() => {
      void request<AutoTriageIssuePage>(`/auto-triage/issues?${params}`).then(value => {
        if (generation !== readGeneration.current) return;
        if (value.revision_key && value.revision_key !== result.revision_key) { setRows(emptyRows); void load(); return; }
        if (value.pages && filters.page > value.pages) { update({ page: value.pages }); return; }
        setRows(value);
      }).catch(() => { if (generation === readGeneration.current) { setRows(emptyRows); setRowsError(true); } })
        .finally(() => { if (generation === readGeneration.current) setLoadingRows(false); });
    }, 180);
    return () => { window.clearTimeout(timer); readGeneration.current++; };
  }, [filters, result?.revision_key, load, rowsRetry]);

  async function recalculate(refreshLabels: boolean) {
    if (!data?.release || refreshing) return;
    setPosting(true); setError('');
    try {
      await request('/auto-triage/recalculate', 'POST', { release: data.release, refresh_labels: refreshLabels,
        date_start: data.scope?.date_start || filters.dateStart || null, date_end: data.scope?.date_end || filters.dateEnd || null });
      await load();
    } catch { setError('refreshError'); }
    finally { setPosting(false); }
  }

  async function exportGaps() {
    if (!data?.release) return;
    try {
      const plan = await request<unknown>(`/auto-triage/gap-plan?${scopeParams(data.release)}`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(plan, null, 2)], { type: 'application/json' }));
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = `auto-triage-${data.release}-gaps.json`; anchor.click();
      URL.revokeObjectURL(url);
    } catch { setError('exportError'); }
  }

  const metricsRow = (name: string, metrics: Metrics, primary = false) => <tr key={name} className={`border-t${primary ? ' bg-primary/5' : ''}`}>
    <th scope="row" className="p-3 text-left font-medium">{name}</th>
    {[metrics.online_precision, metrics.online_recall, metrics.precision, metrics.recall].map((value, index) => <td key={index} className="p-3 text-center tabular-nums"><span className={primary ? 'text-xl font-semibold' : 'font-medium'}>{pct(value)}</span>
      {index < 2 ? <p className="mt-1 text-xs text-muted-foreground" aria-label={t('autoTriage.countDetail', { numerator: (index === 0 ? metrics.precision_auto_tp : metrics.recall_auto_tp).toLocaleString(), denominator: (index === 0 ? metrics.precision_denominator : metrics.recall_denominator).toLocaleString() })}>{(index === 0 ? metrics.precision_auto_tp : metrics.recall_auto_tp).toLocaleString()} / {(index === 0 ? metrics.precision_denominator : metrics.recall_denominator).toLocaleString()}</p> : null}</td>)}
    <td className="p-3 text-center tabular-nums">{metrics.covered.toLocaleString()} / {metrics.eligible.toLocaleString()}</td>
  </tr>;

  return <div className="grid min-w-0 gap-5" data-testid="auto-triage-metrics">
    <section className="grid min-w-0 gap-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0"><h1 className="text-xl font-semibold">{t('autoTriage.title')}</h1><p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t('autoTriage.subtitle')}</p></div>
        <Select label={t('autoTriage.release')} value={filters.release} onChange={release => update({ release })}
          options={[{ value: '@current', label: t('autoTriage.latest') }, ...(data?.versions || []).map(version => ({ value: version.release, label: releaseName(version.release) }))]}/>
      </div>
      <div className="grid min-w-0 gap-3 rounded-lg border bg-card p-3">
      <div className="flex flex-wrap items-end justify-between gap-3"><div className="flex min-w-0 flex-wrap items-end gap-2">
        <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">{t('autoTriage.dateStart')}<input type="date" className="min-h-11 min-w-0 max-w-full rounded-md border bg-background px-3 text-sm text-foreground" aria-label={t('autoTriage.dateStart')} value={draftDates.start} onChange={event => setDraftDates(current => ({ ...current, start: event.target.value }))}/></label>
        <label className="grid min-w-0 gap-1 text-xs text-muted-foreground">{t('autoTriage.dateEnd')}<input type="date" className="min-h-11 min-w-0 max-w-full rounded-md border bg-background px-3 text-sm text-foreground" aria-label={t('autoTriage.dateEnd')} value={draftDates.end} onChange={event => setDraftDates(current => ({ ...current, end: event.target.value }))}/></label>
        <Button type="button" className="min-h-11" variant="outline" disabled={!datesValid} onClick={() => update({ dateStart: draftDates.start, dateEnd: draftDates.end })}>{t('autoTriage.applyDates')}</Button>
        <Button type="button" className="min-h-11" variant="ghost" onClick={() => update({ dateStart: '', dateEnd: '' })}>{t('autoTriage.periodDates')}</Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" className="min-h-12" disabled={!data?.release || refreshing} onClick={() => void recalculate(true)}><RefreshCw className={`h-4 w-4${refreshing ? ' animate-spin' : ''}`}/>{t(refreshing ? 'autoTriage.refreshing' : 'autoTriage.syncLabels')}</Button>
        <Button type="button" className="min-h-11" variant="outline" disabled={!result || refreshing} onClick={() => void recalculate(false)}>{t('autoTriage.recalculate')}</Button>
        <Button type="button" className="min-h-11" variant="outline" disabled={!result} onClick={() => void exportGaps()}><Download className="h-4 w-4"/>{t('autoTriage.exportGaps')}</Button>
      </div></div>
      <div className="flex flex-wrap justify-between gap-x-5 gap-y-1 text-xs text-muted-foreground">
        {data?.scope ? <p>{t('autoTriage.scopeDates', { start: data.scope.date_start, end: data.scope.date_end })}</p> : null}
        <p>{t('autoTriage.readOnlyAction')}</p>
      </div></div>
      {error || data?.refresh.status === 'failed' ? <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{error ? t(`autoTriage.${error}`) : t(`autoTriage.error_${data?.refresh.error}`, { defaultValue: t('autoTriage.refreshError') })}</p> : null}
      {!data ? <div role="status" className="text-sm text-muted-foreground">{error ? <Button type="button" className="min-h-11" variant="outline" onClick={() => void load()}>{t('autoTriage.retry')}</Button> : t('loading')}</div> : <div role="status" className="rounded-lg border bg-card px-4 py-3">
        <div className="flex flex-wrap items-center gap-2"><Badge variant={data.status === 'complete' ? 'success' : 'warning'}>{t(`autoTriage.status_${data.status}`)}</Badge><span className="text-sm font-medium">{releaseName(data.release || '')}</span></div>
        <p className="mt-2 text-sm text-muted-foreground">{t(data.status === 'complete' ? 'autoTriage.completeDescription' : result ? 'autoTriage.coverageDescription' : 'autoTriage.labelPrompt', { covered: result?.metrics.covered.toLocaleString(), missing: result?.metrics.missing_results.toLocaleString() })}</p>
      </div>}
    </section>

    {result ? <>
      <Card className="min-w-0"><CardHeader><CardTitle>{t('autoTriage.comparison')}</CardTitle><p className="text-sm text-muted-foreground">{t('autoTriage.sourceScope')}</p></CardHeader><CardContent>
        <p className="mb-3 flex items-start gap-2 text-sm text-emerald-700 dark:text-emerald-400"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true"/>{t('autoTriage.reconciled', { count: result.reconciliation.checked_issues, formattedCount: result.reconciliation.checked_issues.toLocaleString() })}</p>
        <div className="max-w-full overflow-x-auto"><table className="w-full min-w-[700px] text-sm"><thead><tr className="bg-muted/50 text-muted-foreground"><th className="p-3 text-left">{t('autoTriage.basis')}</th>
          {['roadPrecision', 'roadRecall', 'simPrecision', 'simRecall', 'coveredCases'].map(key => <th key={key} className="p-3 text-center font-medium">{t(`autoTriage.${key}`)}</th>)}
        </tr></thead><tbody>{metricsRow(t('autoTriage.baseline'), result.baseline)}{metricsRow(t('autoTriage.autoBasis'), result.metrics, true)}</tbody></table></div>
        <p className="mt-2 text-xs text-muted-foreground">{t('autoTriage.independentCounts')}</p>
        {!result.metrics.available && result.metrics.covered > 0 ? <div className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/5 p-3"><p className="text-sm font-medium">{t('autoTriage.partialTitle')}</p><p className="mt-1 text-sm text-muted-foreground">{t('autoTriage.partialMetrics', { precision: pct(result.metrics.covered_precision), recall: pct(result.metrics.covered_recall) })}</p></div> : null}
        <p className="mt-3 text-sm text-muted-foreground">{t('autoTriage.mapping')}</p>
        <dl className="mt-3 grid gap-x-5 gap-y-2 text-xs text-muted-foreground sm:grid-cols-2"><div><dt>{t('autoTriage.labelsChecked')}</dt><dd>{time(data?.label_checked_at)} {t('autoTriage.shanghai')}</dd></div><div><dt>{t('autoTriage.sourceAsOf')}</dt><dd>{time(result.source_as_of)} {t('autoTriage.shanghai')}</dd></div></dl>
      </CardContent></Card>


      <section className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label={t('autoTriage.coverageTitle')}>
        {[[t('autoTriage.sourcePool'), result.source_count], [t('autoTriage.modelLabels'), result.label_sources.model || 0],
          [t('autoTriage.reused'), result.metrics.covered], [t('autoTriage.missing'), result.metrics.missing_results]].map(([name, value]) => <Card key={String(name)}><CardContent className="p-4"><p className="text-sm text-muted-foreground">{name}</p><p className="mt-2 text-2xl font-semibold tabular-nums">{Number(value).toLocaleString()}</p></CardContent></Card>)}
      </section>
      <Card className="min-w-0"><details className="group"><summary className="flex min-h-12 cursor-pointer list-none flex-wrap items-center justify-between gap-3 p-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"><div className="min-w-0"><h2 className="font-semibold">{t('autoTriage.transitions')}</h2><p className="mt-1 text-sm text-muted-foreground">{t('autoTriage.transitionSummary', { changed: result.changed_count.toLocaleString(), added: result.newly_eligible.toLocaleString(), removed: result.no_longer_eligible.toLocaleString() })}</p></div><span className="flex items-center gap-2 text-sm text-muted-foreground">{t('autoTriage.transitionDetails')}<ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" aria-hidden="true"/></span></summary><CardContent>
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">{result.transitions.filter(item => item.before !== item.after).map(item => <div key={`${item.before}-${item.after}`} className="flex min-w-0 items-center justify-between gap-2 rounded-md border p-3 text-sm"><span className="min-w-0 break-words">{group(item.before)} <ArrowRight className="mx-1 inline h-3.5 w-3.5"/> {group(item.after)}</span><span className="font-semibold tabular-nums">{item.count.toLocaleString()}</span></div>)}</div>
        {Object.keys(result.coverage_reasons).length ? <div className="mt-3 flex flex-wrap gap-2">{Object.entries(result.coverage_reasons).map(([key, count]) => <Badge key={key} variant="outline">{t(`autoTriage.reason_${key}`)}: {count.toLocaleString()}</Badge>)}</div> : null}
      </CardContent></details></Card>

      <Card className="min-w-0"><CardHeader><CardTitle>{t('autoTriage.issueDetails')}</CardTitle></CardHeader><CardContent className="grid min-w-0 gap-3">
        <div className="flex flex-wrap items-end gap-2"><input className="min-h-11 min-w-0 flex-1 rounded-md border bg-background px-3 text-sm" aria-label={t('autoTriage.search')} placeholder={t('autoTriage.search')} maxLength={200} value={filters.query} onChange={event => update({ query: event.target.value })}/>
          <Select label={t('autoTriage.coverageFilter')} value={filters.coverage} options={[{ value: '', label: t('autoTriage.allCases') }, { value: 'reused', label: t('autoTriage.reused') }, { value: 'gap', label: t('autoTriage.missing') }]} onChange={coverage => update({ coverage })}/>
          <Button type="button" className="min-h-11" variant={filters.changed ? 'secondary' : 'outline'} aria-pressed={filters.changed} onClick={() => update({ changed: !filters.changed })}>{t('autoTriage.changedOnly')}</Button>
        </div>
        <div className="max-w-full overflow-x-auto" aria-busy={loadingRows}><table className="w-full min-w-[1300px] text-sm"><thead><tr className="bg-muted/50 text-muted-foreground">
          {['issue', 'trigger', 'baselineLabel', 'modelRaw', 'autoLabel', 'labelSource', 'newCohort', 'simTriggered', 'simPrecisionCount', 'simRecallCount', 'reuseStatus', 'jobs'].map(key => <th key={key} className="p-2 text-left font-medium">{t(`autoTriage.${key}`)}</th>)}
        </tr></thead><tbody>{rows.items.map(row => <tr key={row.issue_id} className="border-t align-top"><td className="max-w-[200px] p-2"><span className="font-mono">{row.issue_id}</span><p className="break-words text-xs text-muted-foreground">{row.issue_topic}</p></td>
          <td className="p-2">{t(row.ra_type === 2 ? 'autoTriage.autoTrigger' : 'autoTriage.manualTrigger')}</td><td className="p-2">{label(row.baseline_label)}</td><td className="p-2">{label(row.raw_model_result)}</td><td className="p-2">{label(row.auto_label)}</td><td className="p-2">{t(`autoTriage.source_${row.label_source}`)}</td>
          <td className="p-2">{group(row.scope_excluded ? null : row.new_cohort)}</td><td className="p-2">{t(row.sim_triggered === null ? 'autoTriage.pending' : row.sim_triggered ? 'autoTriage.triggered' : 'autoTriage.notTriggered')}</td>
          {(['precision', 'recall'] as const).map(metric => <td key={metric} className="p-2">{row.sim_memberships ? t(row.sim_memberships[`${metric}_numerator`] ? 'autoTriage.membershipBoth' : row.sim_memberships[`${metric}_denominator`] ? 'autoTriage.membershipDenominator' : 'autoTriage.membershipExcluded') : '—'}</td>)}
          <td className="p-2">{t(`autoTriage.reason_${row.result_status}`)}</td><td className="p-2 font-mono">{row.job_ids.join(', ') || '—'}</td></tr>)}</tbody></table>
          {!rows.items.length ? <p role={rowsError ? 'alert' : 'status'} className="p-5 text-center text-sm text-muted-foreground">{t(rowsError ? 'autoTriage.loadError' : loadingRows ? 'loading' : 'autoTriage.noRows')}</p> : null}
        </div>
        {rowsError ? <Button type="button" className="min-h-11 justify-self-start" variant="outline" onClick={() => setRowsRetry(value => value + 1)}>{t('autoTriage.retry')}</Button> : null}
        <Pagination total={rows.total} page={filters.page} pageSize={filters.pageSize} loading={loadingRows || rowsError} onPageChange={page => update({ page })} onPageSizeChange={pageSize => update({ pageSize })}/>
      </CardContent></Card>
    </> : null}
  </div>;
}
