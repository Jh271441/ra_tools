import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown, Download, ExternalLink, Settings2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { evaluationRequest as request } from '../api/evaluation';
import { SimulationJobCard, SimulationMetricCard, SimulationStat, simulationResultsGrid } from './SimulationResults';
import { EvaluationScenarioLabels } from './EvaluationScenarioLabels';
import { ReproductionStatus } from './ReproductionStatus';
import { EvaluationSettings } from './EvaluationSettings';
import { EvaluationLabelSummary } from './EvaluationLabelSummary';
import { EvaluationSources } from './EvaluationSources';
import { cn } from '../lib/utils';
import { releaseName } from '../lib/releaseName';
import { startVisiblePolling } from '../lib/visiblePolling';
import { evaluationKpi, evaluationSummary } from '../lib/evaluationProjection';
import { completeMetrics, evaluationActivity } from '../lib/evaluationFlow';
import { comparisonParams, comparisonRevisions, changeEvaluationRelease, overviewRevision } from '../lib/evaluationContext';
import { createSavedEvaluationInitializer, savedEvaluationInitializationKey } from '../lib/evaluationInitialization';
import { createComparisonReader, createRevisionObserver, evaluationBoardParams, evaluationParams as params, evaluationScope, matchingComparison } from '../lib/evaluationReads';
import type { EvaluationBoard, EvaluationContext, EvaluationIssuePage, EvaluationRevision, MetricProfile, ProfileConfig, ProfilePreview } from '../types/evaluation';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Select } from './ui/select';
import { Pagination, PAGE_SIZES } from './ui/pagination';
const Overview = lazy(() => import('./Overview').then(m => ({ default: m.Overview })));

function readContext(): EvaluationContext {
  const q = new URLSearchParams(location.search);
  return { release: q.get('release') || q.get('version') || '@current', profile_id: q.get('profile') || undefined,
    date_start: q.get('date_start') || undefined, date_end: q.get('date_end') || undefined };
}
const pct = (v?: number | null) => v == null ? '—' : `${(v*100).toFixed(2)}%`;
type EvaluationComparison = { profile: MetricProfile; versions: { release: string; revision: EvaluationRevision | null; stale: boolean }[] };

export function EvaluationWorkspace({ page, onNavigate, visibleReleases, release, hideRelease = false, embedded = false, onDataChange }: { page: 'overview' | 'issues' | 'simulation'; onNavigate: (page: 'overview' | 'issues' | 'simulation', release?: string) => void; visibleReleases?: string[]; release?: string; hideRelease?: boolean; embedded?: boolean; onDataChange?: (value: EvaluationBoard | null) => void }) {
  const { t, i18n } = useTranslation();
  const [ctx, setContext] = useState(() => ({ ...readContext(), ...(release ? { release } : {}) }));
  const [data, setData] = useState<EvaluationBoard | null>(null);
  const [profiles, setProfiles] = useState<MetricProfile[]>([]);
  const [comparisonResult, setComparisonResult] = useState<{ requestedProfile?: string; value: EvaluationComparison } | null>(null);
  const comparison = useMemo(() => matchingComparison(comparisonResult, ctx.profile_id)?.versions.filter(value => value.revision && !value.stale).map(value => value.revision!) || [], [comparisonResult, ctx.profile_id]);
  const [comparisonLoading, setComparisonLoading] = useState(page === 'overview');
  const [comparisonFailed, setComparisonFailed] = useState(false);
  const [comparisonAttempt, setComparisonAttempt] = useState(0);
  const readComparison = useRef(createComparisonReader((profile_id?: string) => request<EvaluationComparison>(`/comparison?${comparisonParams({ release: '@current', profile_id })}`)));
  const observeRevision = useRef(createRevisionObserver());
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [initializing, setInitializing] = useState(false);
  const [initializationFailure, setInitializationFailure] = useState<{ key: string; message: string } | null>(null);
  const initializeSaved = useRef(createSavedEvaluationInitializer(body => request('/runs', 'POST', body)));
  const [editing, setEditing] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [actionTarget, setActionTarget] = useState<HTMLElement | null>(null);
  useEffect(() => { setActionTarget(document.getElementById('evaluation-actions')); }, [page]);
  const generation = useRef(0);
  const scope = evaluationScope(ctx);
  const boardPage = page === 'simulation' ? 'simulation' : 'overview';
  const canonicalRead = useRef<{ scope: string; value: EvaluationBoard } | null>(null);
  const activeScope = useRef(scope); activeScope.current = scope;
  const time = (value?: string) => value ? new Date(value).toLocaleString(i18n.language.startsWith('zh') ? 'zh-CN' : 'en-GB', { timeZone: 'Asia/Shanghai', hour12: false }) : '—';
  const update = (next: Partial<EvaluationContext>) => {
    const base = next.release ? changeEvaluationRelease(ctx, next.release) : ctx;
    const value = { ...base, ...next };
    const q = new URLSearchParams(location.search);
    if (!embedded) q.set('basis', 'auto-triage'); q.set('release', value.release); q.set('version', value.release); q.set('page', '1');
    for (const [key, val] of [['profile', value.profile_id], ['date_start', value.date_start], ['date_end', value.date_end]]) { if (val) q.set(key!, val); else q.delete(key!); }
    history.pushState(history.state, '', `${location.pathname}?${q}`);
    canonicalRead.current = null; setComparisonAttempt(attempt => attempt + 1); setData(null); setContext(value);
  };
  useEffect(() => { const pop = () => { canonicalRead.current = null; setComparisonAttempt(attempt => attempt + 1); setData(null); setContext({ ...readContext(), ...(release ? { release } : {}) }); setEditing(false); setSettingsOpen(false); }; addEventListener('popstate', pop); return () => removeEventListener('popstate', pop); }, []);
  const load = useCallback(async () => {
    if (activeScope.current !== scope) return null;
    const id = ++generation.current;
    try {
      const value = await request<EvaluationBoard>(`/board?${evaluationBoardParams(ctx, boardPage)}`);
      if (id !== generation.current || activeScope.current !== scope) return null;
      if (observeRevision.current(value.context, value.revision?.revision_key || null)) setComparisonAttempt(value => value + 1);
      setData(previous => JSON.stringify(previous) === JSON.stringify(value) ? previous : value); setError('');
      if (scope !== evaluationScope(value.context)) {
        const canonical = value.context;
        const q = new URLSearchParams(location.search);
        if (!embedded) q.set('basis', 'auto-triage'); q.set('release', canonical.release); q.set('version', canonical.release);
        for (const [key, val] of [['profile', canonical.profile_id], ['date_start', canonical.date_start], ['date_end', canonical.date_end]]) { if (val) q.set(key!, val); else q.delete(key!); }
        history.replaceState(history.state, '', `${location.pathname}?${q}`);
        canonicalRead.current = { scope: evaluationScope(canonical), value };
        setContext(canonical);
      }
      return value;
    } catch (err) { if (id === generation.current && activeScope.current === scope) setError(err instanceof Error ? err.message : 'upstream_error'); return null; }
  }, [scope, boardPage]);
  useEffect(() => { onDataChange?.(data); }, [data, onDataChange]);
  useEffect(() => {
    // Canonicalizing the URL does not invalidate the board that supplied it.
    // The next scheduled poll still reads the canonical scope from the server.
    const adopted = !document.hidden && canonicalRead.current?.scope === scope ? canonicalRead.current.value : null;
    canonicalRead.current = null;
    let first = true;
    const stop = startVisiblePolling(() => { if (first) { first = false; if (adopted) return Promise.resolve(adopted); } return load(); }, value => ['queued','running'].includes(value.refresh.status || '') || value.starts.some(s => s.status === 'preparing') || value.executions.some(e => e.metrics_status === 'pending' || ['preparing','submitting','submission_uncertain','running','verifying'].includes(e.status)));
    return () => { ++generation.current; stop(); };
  }, [load]);
  useEffect(() => {
    if (!settingsOpen && !editing) return;
    let active = true;
    void request<{ versions: MetricProfile[] }>('/profiles').then(v => { if (active) setProfiles(v.versions); }).catch(() => {});
    return () => { active = false; };
  }, [settingsOpen, editing]);
  useEffect(() => {
    if (page !== 'overview') return;
    let active = true;
    setComparisonLoading(true);
    setComparisonFailed(false);
    void readComparison.current(ctx.profile_id, comparisonAttempt).then(value => {
      if (active) { setComparisonResult({ requestedProfile: ctx.profile_id, value }); setComparisonLoading(false); }
    }).catch(() => { if (active) { setComparisonLoading(false); setComparisonFailed(true); } });
    return () => { active = false; };
  }, [ctx.profile_id, page, comparisonAttempt]);
  async function act(fn: () => Promise<unknown>) {
    if (busy || activeScope.current !== scope) return;
    setBusy(true); setError('');
    try { await fn(); await load(); } catch (err) { if (activeScope.current === scope) setError(err instanceof Error ? err.message : 'upstream_error'); }
    finally { setBusy(false); }
  }
  const refresh = () => { setInitializationFailure(null); return act(() => request('/runs', 'POST', { ...ctx, refresh_labels: false })); };
  const working = busy || initializing || ['queued','running'].includes(data?.refresh.status || '') || Boolean(data?.executions.some(e=>e.metrics_status==='pending'));
  const revision = data?.revision;
  const overview = page === 'overview' ? overviewRevision(revision, Boolean(data?.stale), comparison, visibleReleases) : undefined;
  const showingSaved = Boolean(overview && overview.revision_key !== revision?.revision_key);
  const label = (value: string | null) => value === null ? t('autoTriage.result_none') : value === '' ? t('autoTriage.result_empty') : t(`autoTriage.result_${value}`, { defaultValue: value });
  const initializationKey = savedEvaluationInitializationKey(data);
  const showError = error || (initializationFailure?.key === initializationKey ? initializationFailure.message : '') || (data?.refresh.status === 'failed' ? data.refresh.error : '');
  useEffect(() => {
    const pending = data ? initializeSaved.current(data) : null;
    if (!pending) { setInitializing(false); return; }
    let active = true;
    setInitializing(true);
    void pending.then(() => {
      if (active && activeScope.current === scope) return load();
    }).catch(err => {
      if (active && activeScope.current === scope && initializationKey) setInitializationFailure({ key: initializationKey, message: err instanceof Error ? err.message : 'upstream_error' });
    }).finally(() => { if (active) setInitializing(false); });
    return () => { active = false; };
  }, [data, load, scope]);
  const calculatingSaved = working || Boolean(!showError && initializationKey);
  return <div className="grid min-w-0 gap-4">
    {actionTarget && createPortal(<Button className="min-h-11" variant="outline" disabled={!data} onClick={()=>setSettingsOpen(true)}><Settings2 size={16}/>{t('evaluation.settings')}</Button>, actionTarget)}
    {settingsOpen && data && createPortal(<EvaluationSettings ctx={ctx} data={data} profiles={profiles.length ? profiles : [data.profile]} hideRelease={hideRelease} working={working} error={showError || ''} onApply={update} onClose={()=>setSettingsOpen(false)} onManage={()=>setEditing(true)} onRefresh={()=>void refresh()}/>, document.body)}
    {showError && <p role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{t(`evaluation.error_${showError}`,{defaultValue:t('evaluation.action_failed')})}<Button className="min-h-11" variant="outline" disabled={working} onClick={()=>void (data?.sample_source.status==='ready' && !revision ? refresh() : load())}>{t('autoTriage.retry')}</Button></p>}
    {data?.stale && <p role="status" className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm">{t('evaluation.stale_short')}</p>}
    {!data && !error && <p role="status">{t('loading')}</p>}
    {data?.sample_source.status==='missing' && !showingSaved && !comparisonFailed && (page!=='overview' || !comparisonLoading) && <p role="status" className="rounded-md border bg-muted/30 p-3 text-sm">{t('evaluation.error_sample_snapshot_required')}</p>}
    {data && page==='overview' && comparisonLoading && !overview && <p role="status">{t('loading')}</p>}
    {page==='overview' && comparisonFailed && <div role="alert" className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm"><span>{t('autoTriage.loadError')}</span><Button className="min-h-11" variant="outline" onClick={()=>setComparisonAttempt(value=>value+1)}>{t('autoTriage.retry')}</Button></div>}
    {showingSaved && overview && <div role="status" className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-md border bg-muted/30 p-3 text-sm"><span className="min-w-0 break-words">{t('evaluation.overview_saved_context', { requested: releaseName(ctx.release), saved: releaseName(overview.context.release) })}</span><Button className="min-h-11" variant="outline" onClick={()=>update(overview.context)}>{t('evaluation.open_saved_release', { release: releaseName(overview.context.release) })}</Button></div>}
    {data && !revision && data.sample_source.status==='ready' && <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-4 text-sm"><span>{t(calculatingSaved ? 'evaluation.calculating_saved' : 'evaluation.flow_ready_recalculate')}</span>{!calculatingSaved && !showError && <Button className="min-h-11" variant="outline" onClick={()=>void refresh()}>{t('evaluation.recalculate_short')}</Button>}</div>}
    {page==='overview' && overview && <Suspense fallback={<p>{t('loading')}</p>}><Overview evaluationBasis sourceAnalysis={<EvaluationSources revision={overview} revisions={comparison.filter(item=>!visibleReleases||visibleReleases.includes(item.context.release))} stale={false} busy={working} onRelease={release=>update({release})}/>} summary={evaluationSummary(overview)} comparison={comparisonRevisions(comparison,overview).map(item=>evaluationKpi(item)).filter(item=>!visibleReleases || visibleReleases.includes(item.version_key))} onOpenCurrent={()=>onNavigate('issues',overview.context.release)} onOpenIssues={filters=>{if(filters.version)update({release:filters.version});onNavigate('issues',filters.version);}}/></Suspense>}
    {page==='issues' && <EvaluationLabelSummary key={scope + '/' + (data?.stale ? 'stale' : revision?.revision_key || '')}
      ctx={ctx} loading={!data && !error} revision={!data?.stale && revision && evaluationScope(revision.context) === scope ? revision.revision_key : undefined}/>}
    {page==='issues' && revision && !data?.stale && evaluationScope(revision.context) === scope &&
      <EvaluationSources revision={revision} revisions={[]} stale={false} busy={working}/>}
    {page==='issues' && revision && <EvaluationIssues ctx={ctx} revision={revision.revision_key} label={label}/>}
    {page==='simulation' && data && <EvaluationSimulationResults data={data} ctx={ctx} busy={busy} working={working} act={act}/>}
    {editing && data && createPortal(<ProfileEditor ctx={ctx} profile={data.profile} profiles={profiles} onClose={()=>setEditing(false)} onPublished={async profile=>{update({profile_id:profile.id});setEditing(false);setSettingsOpen(false);}}/>, document.body)}
  </div>;
}

function EvaluationSimulationResults({ data, ctx, busy, working, act }: { data: EvaluationBoard; ctx: EvaluationContext; busy: boolean; working: boolean; act: (fn: () => Promise<unknown>) => Promise<void> }) {
  const { t, i18n } = useTranslation();
  const activity = evaluationActivity(data), execution = activity.latest;
  const metrics = data.revision?.metrics;
  const comparison = data.recall_comparison;
  const differenceLink = (coverage: string) => { const q = new URLSearchParams(location.search); q.set('basis', 'auto-triage'); q.set('coverage', coverage); q.set('page', '1'); q.delete('query'); q.delete('changed'); return `${import.meta.env.BASE_URL}issues?${q}`; };
  const full = Boolean(metrics && completeMetrics(metrics, data.stale));
  const failedHistory = activity.failed.filter(start => start.id !== activity.currentFailure?.id);
  const time = (value?: string) => value ? new Date(value).toLocaleString(i18n.language.startsWith('zh') ? 'zh-CN' : 'en-GB', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '—';
  const exportPlan = () => { const url=URL.createObjectURL(new Blob([JSON.stringify(data.plan,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`incremental-plan-${data.plan.id}.json`;a.click();URL.revokeObjectURL(url); };
  return <div className={simulationResultsGrid}>
    <div className="min-w-0 space-y-4">
      {activity.currentFailure && <p role="alert" className="rounded-md border border-destructive/40 p-3 text-sm text-destructive">{t(`evaluation.error_${activity.currentFailure.error}`, { defaultValue: t('evaluation.action_failed') })}</p>}
      {execution ? <SimulationJobCard job={{ ...execution, backfill: true, scenario_count: execution.progress?.total, url: execution.job_id ? `https://voyager.intra.xiaojukeji.com/static/management/#/orion/job/detail?job_id=${execution.job_id}` : undefined, error: execution.error ? t(`evaluation.error_${execution.error}`, { defaultValue: t('evaluation.action_failed') }) : undefined }} extraStatus={execution.metrics_status==='pending' ? <Badge variant="outline">{t('evaluation.flow_updating_metrics')}</Badge> : undefined}/> : <Card><CardContent className="space-y-2 p-8 text-center text-sm text-muted-foreground"><p>{t('simFlow.noJobs')}</p><p>{t(data.plan.runnable_count ? 'evaluation.flow_ready_manual' : data.plan.blocked_count ? 'evaluation.flow_wait_source' : 'evaluation.flow_no_simulation')}</p></CardContent></Card>}
      {data.plan.id && <Card><CardHeader><CardTitle>{t('evaluation.incremental_plan')}</CardTitle></CardHeader><CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{(['reuse_count','prepare_count','simulate_count','blocked_count'] as const).map(key => <SimulationStat key={key} title={t(`evaluation.${key}`)} value={(data.plan[key] || 0).toLocaleString(i18n.language)}/>)}</div>
        <div className="flex flex-wrap items-center gap-2"><Button className="min-h-12" disabled={working || data.stale || !(data.plan.runnable_count ?? data.plan.gap_count) || !!data.plan.review_count || data.starts.some(start=>start.status==='preparing') || Boolean(activity.active)} onClick={()=>void act(()=>request(`/plans/${data.plan.id}/start`,'POST'))}>{t('evaluation.start_short')}</Button><Button className="min-h-11" variant="outline" onClick={exportPlan}><Download size={16}/>{t('evaluation.export_plan')}</Button></div>
        {!!data.plan.blocked_count && <details className="border-t pt-2 text-sm"><summary className="min-h-11 cursor-pointer py-3 text-amber-700 dark:text-amber-400">{t('evaluation.deferred_compact', { amount: data.plan.blocked_count })}</summary><ul className="mt-2 space-y-1">{data.plan.actions.filter(a=>a.action==='deferred').map(a => <li key={a.issue_id} className="break-words"><code>{a.issue_id}</code> · {t(`evaluation.deferred_${a.reason}`)}</li>)}</ul><p className="mt-2 text-xs text-muted-foreground">{t('evaluation.deferred_note')}</p></details>}
        {!!data.plan.review_count && <p role="status" className="text-sm text-amber-700 dark:text-amber-400">{t('evaluation.flow_review', { amount: data.plan.review_count })}</p>}
        <details className="border-t pt-2 text-xs text-muted-foreground"><summary className="min-h-11 cursor-pointer py-3">{t('evaluation.plan_details')}</summary><p className="break-all">{t('evaluation.plan_hash')} <code>{data.plan.id}</code></p><p className="mt-2">{t('evaluation.manual_policy')}</p></details>
      </CardContent></Card>}
      {!!failedHistory.length && <details className="rounded-lg border p-3 text-xs text-muted-foreground"><summary className="min-h-11 cursor-pointer py-3">{t('evaluation.past_attempts', { amount: failedHistory.length })}</summary><ul className="space-y-2">{failedHistory.map(start => <li key={start.id} className="break-words"><time>{time(start.created_at)}</time> · {t(`evaluation.error_${start.error}`, { defaultValue: t('evaluation.action_failed') })}</li>)}</ul></details>}
    </div>
    <div className="min-w-0 space-y-4">
      <SimulationMetricCard status={t(full ? 'evaluation.result_computed' : 'evaluation.partial_short')} variant={full ? 'outline' : 'warning'} decimals={2} available={!data.stale} precision={metrics?.covered_precision} recall={metrics?.covered_recall} reproduction={metrics?.covered_repro_rate} reproductionScope={metrics?.reproduction} summary={metrics ? t('evaluation.covered_scope', { covered: metrics.covered.toLocaleString(i18n.language), eligible: metrics.eligible.toLocaleString(i18n.language) }) : undefined}>
        {!full && <p className="text-xs leading-5 text-muted-foreground">{t(data.stale ? 'evaluation.flow_recalculate' : !metrics ? 'evaluation.result_empty_note' : metrics.eligible===0 ? 'evaluation.flow_no_eligible' : 'evaluation.complete_pending', { amount: metrics?.missing_results })}</p>}
        {comparison && comparison.gap !== null && <details className="group border-t pt-2 text-sm"><summary className="flex min-h-11 cursor-pointer flex-wrap items-center justify-between gap-2 py-3"><span>{t('evaluation.recall_difference')}</span><span className="inline-flex items-center gap-2 font-mono tabular-nums">{comparison.gap >= 0 ? '+' : ''}{(comparison.gap*100).toFixed(2)} pp<ChevronDown size={14} className="shrink-0 transition-transform group-open:rotate-180" aria-hidden="true"/></span></summary><div className="space-y-2 pt-2"><p className="text-xs text-muted-foreground">{t('evaluation.recall_paired_counts', { road: `${comparison.road_numerator.toLocaleString(i18n.language)} / ${comparison.road_denominator.toLocaleString(i18n.language)}`, simulation: `${comparison.sim_numerator.toLocaleString(i18n.language)} / ${comparison.sim_denominator.toLocaleString(i18n.language)}` })}</p><div className="flex flex-wrap gap-x-4 gap-y-1">{(['recall_gain','recall_loss'] as const).map((coverage,index)=><a key={coverage} className="inline-flex min-h-11 items-center text-primary underline-offset-4 hover:underline" href={differenceLink(coverage)}>{t(`evaluation.${coverage}`, { amount: (index===0?comparison.gains:comparison.losses).toLocaleString(i18n.language) })}</a>)}</div><p className="text-xs leading-5 text-muted-foreground">{t('evaluation.recall_window_note')}</p></div></details>}
      </SimulationMetricCard>
      <Card><CardHeader><div className="flex flex-wrap items-center justify-between gap-2"><CardTitle>{t('evaluation.hourly_check')}</CardTitle><Badge variant="outline">{t((data.cron.effective ?? data.cron.enabled) ? 'evaluation.schedule_on' : 'evaluation.schedule_off')}</Badge></div></CardHeader><CardContent className="space-y-3"><p className="text-xs text-muted-foreground">{t('evaluation.schedule_next', { time: time(data.cron.next_check_at) })}</p><Button className="min-h-11" variant="outline" disabled={busy} onClick={()=>void act(()=>request('/cron','PUT',{...ctx,enabled:!data.cron.enabled}))}>{t(data.cron.enabled ? 'evaluation.disable_short' : 'evaluation.enable_short')}</Button></CardContent></Card>
    </div>
  </div>;
}

function EvaluationIssues({ ctx, revision, label }: { ctx: EvaluationContext; revision?: string; label: (v: string | null) => string }) {
  const { t, i18n } = useTranslation();
  const initial = () => { const q = new URLSearchParams(location.search); const size = Number(q.get('page_size') || 20); return { page: (/^\d+$/.test(q.get('page') || '1') ? Math.max(1, Number(q.get('page') || 1)) : 1), size: PAGE_SIZES.includes(size) ? size : 20, query: q.get('query') || '', coverage: ['gap','reused','recall_gain','recall_loss','before_manual','after_manual','reproduction_pending'].includes(q.get('coverage') || '') ? q.get('coverage')! : '', changed: q.get('changed') === '1' }; };
  const [filters, setFilters] = useState(initial);
  const [rows, setRows] = useState<EvaluationIssuePage>({ items: [], total: 0, page: 1, pages: 0, page_size: 20 });
  const [loading, setLoading] = useState(true), [failed, setFailed] = useState(false), [retry, setRetry] = useState(0);
  const [selectedId, setSelectedId] = useState('');
  const sequence = useRef(0);
  const clearSelection = () => { setSelectedId(''); setRows(v => ({ ...v, items: [] })); setLoading(true); };
  const change = (value: Partial<typeof filters>) => { clearSelection(); setFilters(v => ({ ...v, ...value, page: value.page ?? 1 })); };
  useEffect(() => { clearSelection(); setFilters(initial()); setRows(v => ({ ...v, total: 0 })); }, [JSON.stringify(ctx)]);
  useEffect(() => { const pop = () => { clearSelection(); setFilters(initial()); }; addEventListener('popstate', pop); return () => removeEventListener('popstate', pop); }, []);
  useEffect(() => {
    const q = new URLSearchParams(location.search); q.set('page', String(filters.page)); q.set('page_size', String(filters.size));
    for (const [k,v] of [['query',filters.query],['coverage',filters.coverage],['changed',filters.changed ? '1' : '']]) { if (v) q.set(k,v); else q.delete(k); }
    history.replaceState(history.state, '', `${location.pathname}?${q}`);
    const id = ++sequence.current; clearSelection(); setFailed(false);
    const query = params(ctx); query.set('page', String(filters.page)); query.set('page_size', String(filters.size)); query.set('query', filters.query); query.set('coverage', filters.coverage); query.set('changed_only', String(filters.changed));
    const timer = setTimeout(() => void request<EvaluationIssuePage>(`/issues?${query}`).then(value => { if (id === sequence.current) { if (value.pages && filters.page > value.pages) change({ page: value.pages }); else setRows(value); } }).catch(() => { if (id === sequence.current) setFailed(true); }).finally(() => { if (id === sequence.current) setLoading(false); }), 160);
    return () => { clearTimeout(timer); ++sequence.current; };
  }, [JSON.stringify(ctx), filters, revision, retry]);
  const selected = !loading && !failed ? rows.items.find(row => row.issue_id === selectedId) || rows.items[0] : undefined;
  const reason = (value: string) => t(['missing_bag','upstream_error'].includes(value) ? `evaluation.deferred_${value}` : `autoTriage.reason_${value}`);
  const triggered = (value: boolean | null) => t(value === null ? 'autoTriage.pending' : value ? 'autoTriage.triggered' : 'autoTriage.notTriggered');
  const membership = (values: Record<string, number> | null, metric: 'precision' | 'recall') => values ? t(values[`${metric}_numerator`] ? 'autoTriage.membershipBoth' : values[`${metric}_denominator`] ? 'autoTriage.membershipDenominator' : 'autoTriage.membershipExcluded') : '—';
  return <div className="grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.6fr)]">
    <Card className="min-w-0 overflow-hidden"><CardHeader><CardTitle>{t('issues')} ({rows.total.toLocaleString(i18n.language)})</CardTitle><p className="break-words text-xs text-muted-foreground">{releaseName(ctx.release)}</p></CardHeader><CardContent className="grid min-w-0 gap-3">
      <div className="flex min-w-0 flex-wrap gap-2">
        <input className="min-h-11 min-w-0 basis-full rounded-md border bg-background px-3 text-sm sm:basis-40 sm:flex-1" aria-label={t('autoTriage.search')} placeholder={t('autoTriage.search')} value={filters.query} onChange={e => change({ query: e.target.value })}/>
        <Select label={t('autoTriage.coverageFilter')} value={filters.coverage} options={[{ value: '', label: t('autoTriage.allCases') }, { value: 'reused', label: t('autoTriage.reused') }, { value: 'gap', label: t('autoTriage.missing') }, { value: 'recall_gain', label: t('evaluation.recall_gain_filter') }, { value: 'recall_loss', label: t('evaluation.recall_loss_filter') }, { value: 'before_manual', label: t('reproduction.before_manual_trigger') }, { value: 'after_manual', label: t('reproduction.after_manual_trigger') }, { value: 'reproduction_pending', label: t('reproduction.pending') }]} onChange={coverage => change({ coverage })}/>
        <Select label={t('evaluation.label_changes')} value={filters.changed ? '1' : ''} options={[{ value: '', label: t('evaluation.all_labels') }, { value: '1', label: t('autoTriage.changedOnly') }]} onChange={changed => change({ changed: changed === '1' })}/>
        <Button variant="outline" className="min-h-11" onClick={()=>change({query:'',coverage:'',changed:false})}>{t('reset')}</Button>
      </div>
      <div className="min-w-0 overflow-x-auto" aria-busy={loading}><table className="w-full min-w-[560px] table-fixed text-left text-sm"><colgroup>{[150,130,110,110].map((width,index)=><col key={index} style={{width}}/>)}</colgroup>
        <thead><tr>{['issue','scenario','evaluation.issue_road','evaluation.issue_result'].map(key=><th key={key} className="p-2 text-xs text-muted-foreground">{t(key)}</th>)}</tr></thead>
        <tbody>{rows.items.map(row=><tr key={row.issue_id} className={cn('border-t', selected?.issue_id===row.issue_id && 'bg-primary/5')}>
          <td className="p-2"><button className="min-h-11 text-left font-mono text-primary hover:underline" aria-label={t('evaluation.issue_open',{id:row.issue_id})} onClick={()=>setSelectedId(row.issue_id)}>{row.issue_id}</button><p className="truncate text-xs text-muted-foreground" title={row.issue_topic}>{row.issue_topic}</p></td>
          <td className="p-2"><span className="break-all">{row.scenario_ids[0] || t('evaluation.issue_unmapped')}</span>{row.scenario_ids.length>1 && <p className="text-xs text-muted-foreground">{t('evaluation.scenario_count',{amount:row.scenario_ids.length})}</p>}</td>
          <td className="p-2">{label(row.auto_label)}<p className="text-xs text-muted-foreground">{t(row.ra_type===2?'autoTriage.autoTrigger':'autoTriage.manualTrigger')}</p></td>
          <td className="p-2">{triggered(row.sim_triggered)}<p className="text-xs text-muted-foreground">{reason(row.result_status)}</p></td>
        </tr>)}</tbody>
      </table>{!rows.items.length && <p role={failed?'alert':'status'} className="p-6 text-center text-sm text-muted-foreground">{t(failed?'autoTriage.loadError':loading?'loading':'autoTriage.noRows')}</p>}</div>
      <Pagination total={rows.total} page={filters.page} pageSize={filters.size} loading={loading || failed} onPageChange={page=>change({page})} onPageSizeChange={size=>change({size})}/>
      {failed && <Button variant="outline" className="min-h-11" onClick={()=>setRetry(value=>value+1)}>{t('autoTriage.retry')}</Button>}
    </CardContent></Card>
    <Card className="min-w-0 overflow-hidden xl:sticky xl:top-6"><CardHeader><div className="flex flex-wrap items-center justify-between gap-3"><CardTitle>{selected?.issue_id || t('evaluation.issue_detail')}</CardTitle>{selected && <a className="inline-flex min-h-11 items-center gap-1 text-sm text-primary" href={`https://voyager.intra.xiaojukeji.com/paladin/issue/detail/${encodeURIComponent(selected.issue_id)}`} target="_blank" rel="noreferrer">{t('evaluation.issue_open_link')}<ExternalLink size={14}/></a>}</div></CardHeader>
      <CardContent className="grid min-w-0 gap-4 text-sm">{selected ? <>
        <p className="break-words">{selected.issue_topic}</p>
        <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-x-4 gap-y-2">{[
          ['autoTriage.trigger',t(selected.ra_type===2?'autoTriage.autoTrigger':'autoTriage.manualTrigger')],
          ['autoTriage.baselineLabel',selected.baseline_available===false ? t('evaluation.source_unavailable') : label(selected.baseline_label)],
          ['autoTriage.modelRaw',label(selected.raw_model_result)],
          ['autoTriage.simTriggered',triggered(selected.sim_triggered)],
          ...(selected.reproduction ? [['reproduction.title', <ReproductionStatus value={selected.reproduction}/>]] : []),
          ['evaluation.original_sim_result',selected.precision_label==null?'—':label(selected.precision_label)],
          ['autoTriage.reuseStatus',reason(selected.result_status)],
        ].map(([key,value])=><div key={String(key)} className="contents"><dt className="break-words text-muted-foreground">{t(String(key))}</dt><dd className="break-words">{value}</dd></div>)}</dl>
        <EvaluationScenarioLabels key={`${JSON.stringify(ctx)}:${revision}:${selected.issue_id}`} issue={selected} context={ctx} revision={revision} label={label}/>
        <div className="flex flex-wrap gap-2">{selected.job_ids.map(id=><a key={id} className="inline-flex min-h-11 items-center text-xs text-primary hover:underline" target="_blank" rel="noreferrer" href={`http://voyager.intra.xiaojukeji.com/static/management/#/orion/job/detail?job_id=${id}`}>Job {id}<ExternalLink size={13}/></a>)}</div>
        <details className="min-w-0 rounded border p-3 text-xs"><summary className="min-h-11 cursor-pointer py-3">{t('evaluation.metric_memberships')}</summary><div className="overflow-x-auto"><table className="w-full text-left"><thead><tr>{['evaluation.metric_name','evaluation.issue_road','evaluation.issue_simulation'].map(key=><th key={key} className="p-2 font-medium">{t(key)}</th>)}</tr></thead><tbody>{(['precision','recall'] as const).map(metric=><tr key={metric} className="border-t"><th className="p-2 font-medium">{t(`evaluation.partial_${metric}`)}</th><td className="p-2">{membership(selected.auto_memberships,metric)}</td><td className="p-2">{membership(selected.sim_memberships,metric)}</td></tr>)}</tbody></table></div><p className="mt-2 break-words text-muted-foreground">{t('evaluation.independent_counts')}</p></details>
      </> : <p role="status" className="py-8 text-center text-muted-foreground">{t(loading?'loading':'evaluation.issue_select')}</p>}</CardContent>
    </Card>
  </div>;

}

function ProfileEditor({ ctx, profile, profiles, onClose, onPublished }: { ctx: EvaluationContext; profile: MetricProfile; profiles: MetricProfile[]; onClose: () => void; onPublished: (p: MetricProfile) => Promise<void> }) {
  const { t } = useTranslation();
  const [config, setConfig] = useState<ProfileConfig>(() => structuredClone(profile.config));
  const [name, setName] = useState(''), [description, setDescription] = useState(''), [mapping, setMapping] = useState(JSON.stringify(config.label.mapping, null, 2));
  const [draft, setDraft] = useState<MetricProfile | null>(null), [preview, setPreview] = useState<ProfilePreview | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const dialog = useRef<HTMLDialogElement>(null), origin = useRef<HTMLElement | null>(null);
  useEffect(() => { origin.current = document.activeElement as HTMLElement; dialog.current?.showModal(); return () => { origin.current?.focus({ preventScroll: true }); }; }, []);
  const edit = (next: ProfileConfig) => { setConfig(next); setDraft(null); setPreview(null); };
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); setError(''); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : 'invalid_configuration'); } finally { setBusy(false); } };
  return <dialog ref={dialog} onCancel={e => { e.preventDefault(); onClose(); }} className="m-auto max-h-[90dvh] w-[min(760px,calc(100%_-_24px))] max-w-full overflow-y-auto rounded-lg border bg-card p-0 text-foreground shadow-xl backdrop:bg-black/40" aria-labelledby="metric-profile-title"><div className="flex items-start justify-between gap-3 border-b p-4"><div><h2 id="metric-profile-title" className="text-lg font-semibold">{t('evaluation.manage_rules')}</h2><p className="mt-1 text-sm text-muted-foreground">{t('evaluation.profile_description')}</p></div><Button variant="ghost" size="icon" className="h-11 w-11 shrink-0" aria-label={t('simFlow.closeDetails')} onClick={onClose}><X size={17}/></Button></div><div className="grid min-w-0 gap-4 p-4">
    <label className="grid gap-1 text-sm">{t('evaluation.profile_name')}<input className="min-h-11 min-w-0 rounded-md border bg-background px-3" maxLength={80} value={name} onChange={e => { setName(e.target.value); setDraft(null); setPreview(null); }}/></label>
    <label className="grid gap-1 text-sm">{t('evaluation.change_reason')}<textarea className="min-h-20 min-w-0 rounded-md border bg-background p-3" maxLength={2000} value={description} onChange={e => { setDescription(e.target.value); setDraft(null); setPreview(null); }}/></label>
    <Select label={t('evaluation.label_source')} value={config.label.source} options={[{ value: 'merged_ra_auto_result', label: t('autoTriage.autoBasis') }, { value: 'merged_ra_result', label: t('autoTriage.baseline') }]} onChange={source => edit({ ...config, label: { ...config.label, source } })}/>
    <label className="grid min-w-0 gap-1 text-sm">{t('evaluation.mapping')}<textarea className="min-h-24 min-w-0 rounded-md border bg-background p-3 font-mono text-xs" value={mapping} spellCheck={false} onChange={e => { setMapping(e.target.value); setDraft(null); setPreview(null); }}/></label>
    <fieldset className="grid min-w-0 gap-3 rounded-md border p-3"><legend className="px-1 text-sm font-medium">{t('evaluation.population_filters')}</legend>{Object.entries(config.population.filters).filter(([key]) => key !== 'is_deleted').map(([key, values]) => <label key={key} className="grid min-w-0 gap-1 text-sm">{t(`evaluation.filter_${key}`)}<input className="min-h-11 min-w-0 rounded-md border bg-background px-3" value={values.join(', ')} onChange={e => edit({ ...config, population: { ...config.population, filters: { ...config.population.filters, [key]: e.target.value.split(',').map(v => v.trim()) } } })}/></label>)}</fieldset>
    <fieldset className="grid min-w-0 gap-3 rounded-md border p-3"><legend className="px-1 text-sm font-medium">{t('evaluation.membership_rules')}</legend>{Object.entries(config.memberships).map(([key, rule]) => <div key={key} className="grid min-w-0 gap-2 border-b pb-3 last:border-0"><strong className="text-sm">{t(`evaluation.${key}`)}</strong><div className="flex min-w-0 flex-wrap items-center gap-2"><Select label={t('evaluation.trigger_condition')} value={rule.triggers.join(',')} options={[{ value: '2', label: t('autoTriage.autoTrigger') }, { value: '3', label: t('autoTriage.manualTrigger') }, { value: '2,3', label: t('evaluation.both_triggers') }]} onChange={v => edit({ ...config, memberships: { ...config.memberships, [key]: { ...rule, triggers: v.split(',').map(Number) } } })}/><Select label={t('evaluation.label_condition')} value={rule.include ? 'include' : 'exclude'} options={[{ value: 'include', label: t('evaluation.include') }, { value: 'exclude', label: t('evaluation.exclude') }]} onChange={v => edit({ ...config, memberships: { ...config.memberships, [key]: { triggers: rule.triggers, [v]: rule.include || rule.exclude } } })}/></div><input aria-label={t(`evaluation.${key}`)} className="min-h-11 min-w-0 rounded-md border bg-background px-3 text-sm" value={(rule.include || rule.exclude || []).join(', ')} onChange={e => edit({ ...config, memberships: { ...config.memberships, [key]: { triggers: rule.triggers, [rule.include ? 'include' : 'exclude']: e.target.value.split(',').map(v => v.trim()) } } })}/></div>)}</fieldset>
    {error && <p role="alert" className="break-words text-sm text-destructive">{t(`evaluation.error_${error}`, { defaultValue: t('evaluation.action_failed') })} <code>{error}</code></p>}
    <Button className="min-h-12" disabled={busy || !name.trim() || !description.trim()} onClick={() => void run(async () => { const parsed = JSON.parse(mapping); const value = await request<MetricProfile>('/profiles/drafts', 'POST', { name, description, parent: profile.id, config: { ...config, label: { ...config.label, mapping: parsed } } }); setDraft(value); setPreview(await request<ProfilePreview>(`/profiles/${value.id}/preview`, 'POST', ctx)); })}>{t(busy ? 'evaluation.previewing' : 'evaluation.save_preview')}</Button>
    {preview && draft && <section className="grid gap-3 rounded-md border bg-primary/5 p-3"><h3 className="font-medium">{t('evaluation.impact_preview')}</h3><dl className="grid grid-cols-2 gap-3">{(['changed_labels','population_added','population_removed','newly_eligible','no_longer_eligible'] as const).map(key => <div key={key}><dt className="text-xs text-muted-foreground">{t(`evaluation.${key}`)}</dt><dd>{preview[key]}</dd></div>)}<div><dt>{t('evaluation.reuse_count')}</dt><dd>{preview.metrics.covered}</dd></div><div><dt>{t('autoTriage.missing')}</dt><dd>{preview.metrics.missing_results}</dd></div></dl><p className="text-sm">{pct(preview.previous_metrics.online_precision)} → {pct(preview.metrics.online_precision)} / {pct(preview.previous_metrics.online_recall)} → {pct(preview.metrics.online_recall)}</p><Button className="min-h-12" disabled={busy} onClick={() => void run(async () => onPublished(await request<MetricProfile>(`/profiles/${draft.id}/publish`, 'POST', { preview_hash: preview.preview_hash }))) }>{t('evaluation.publish_rules')}</Button><p className="text-xs text-muted-foreground">{t('evaluation.manual_policy')}</p></section>}
    <details><summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">{t('evaluation.history')}</summary><ul className="grid gap-2 text-sm">{profiles.map(p => <li key={p.id} className="break-words rounded-md border p-3"><strong>{p.name}</strong> <Badge variant="outline">{t(`evaluation.profile_${p.status}`)}</Badge><p className="mt-1">{p.description}</p><code className="break-all text-xs text-muted-foreground">{p.id}</code></li>)}</ul></details>
  </div></dialog>;
}
