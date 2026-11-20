import type { LabelCycleState } from './CollectionLoop';
import { releaseName } from '../lib/releaseName';
import { changeEvaluationReleaseQuery } from '../lib/evaluationContext';
import type { ReproductionSummary, ReproductionResult } from '../types/reproduction';
import type { ResultPublication } from "../types";
import { lazy, memo, Suspense, useCallback, useEffect, useId, useRef, useState, useSyncExternalStore } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Select } from './ui/select';
import { Activity, ArrowUpRight, ExternalLink, Layers3, RefreshCw, SlidersHorizontal } from 'lucide-react';

import { SimulationJobCard as JobCard, SimulationMetricCard, SimulationStat as Stat, simulationResultsGrid } from './SimulationResults';
import { request } from '../api/workflow';
import { LiveView, ViewCache } from '../lib/liveView';
import { startVisiblePolling } from '../lib/visiblePolling';
import { recordLoadStage } from '../lib/loadTiming';
export { request } from '../api/workflow';

let flowModule: Promise<typeof import('./SimulationFlow')> | undefined;
const preloadFlow = () => flowModule ||= import('./SimulationFlow').catch(error => { flowModule = undefined; throw error; });
const SimulationFlow = lazy(preloadFlow);
const EvaluationWorkspace = lazy(() => import('./EvaluationWorkspace').then(m => ({default:m.EvaluationWorkspace})));
const SimulationParameters = lazy(() => import('./SimulationParameters').then(module => ({ default: memo(module.SimulationParameters) })));
const boardCache = new ViewCache<BoardData>();
function metricRate(value?: number | null) { return value == null ? '—' : (value * 100).toFixed(1) + '%'; }

export function localTime(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '尚未同步';
}

export interface Workflow {
  current_version: string | null; reference_thursday: string; status: string; reason: string;
  current_period: { cycle_end: string; case_start: string; case_end_exclusive: string; evidence: string; target_road_version?: string; binary_id?: number } | null;
  acceptance_only: boolean; period_verified: boolean; retained_previous: boolean; population_complete: boolean; collected_through: string | null;
  source_metrics: { online_precision: number | null; online_recall: number | null; eligible: number; excluded: number } | null;
  metrics: { reproduction?: ReproductionSummary; basis?: string; covered?: number; eligible?: number; missing_results?: number; covered_precision?: number | null; covered_recall?: number | null; covered_repro_rate?: number | null; publication?: ResultPublication | null; available: boolean; archived?: boolean; quality_gate_passed?: boolean; precision?: number; recall?: number; sim_repro_rate?: number; online_precision?: number; online_recall?: number; reason?: string; job_id?: number };
  mode: 'manual' | 'auto'; driver_ready: boolean; scheduler_enabled: boolean;
  synced_at: string | null; issue_count: number; scenario_count: number; manual_population_count: number;
  last_sync: { status?: string; reason?: string; mapping_error?: string; checked_at?: string };
  periods: { release: string; verified: boolean; basis: string | null; status: string; cycle_end: string }[];
  batches: { fingerprint: string; release: string; status: string; job_id: string | null; scenario_count: number }[];
}
export interface SourceIssue {
  ra_type?: number;
  issue_id: string; issue_topic: string; source_result: string | null; road_version: string; scenario_id: string; scenario_name: string; scenario_labels: string[];
  job_id?: number; result_note?: string; execution_conflict?: boolean; reproduction?: ReproductionResult; simulation_status: string; sim_triggered: boolean | null; reproduced: boolean | null; precision_label: string | null;
}
export const stateNames: Record<string, string> = { collecting: '待准备仿真', cancelled: '已取消', verifying: '结果核验中', excluded: '不参与评测', pending_gt: '待确认路测 GT', queued: '排队中', preflight_failed: '预检失败', cancelled_stale: '计划已过期', quality_failed: '结果未通过验收', result_ready: '结果已导入', pending_mapping: '待匹配场景', pending_simulation: '待仿真', submitting: '提交中', submission_uncertain: '提交待核对', running: '运行中', complete: '完成', failed: '失败' };

export function CurrentBusinessRelease() {
  const { t } = useTranslation();
  const [data, setData] = useState<Workflow | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    const stop = startVisiblePolling(async () => {
      try {
        const value = await request<Workflow>();
        if (active) { setData(previous => JSON.stringify(previous) === JSON.stringify(value) ? previous : value); setError(''); }
        return value;
      } catch { if (active) setError('businessVersionFailed'); return null; }
    });
    return () => { active = false; stop(); };
  }, []);
  return <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm" role="status">
    <strong title={data?.current_version || undefined}>{t('simFlow.businessVersion')}：{data?.current_version ? releaseName(data.current_version) : t('simFlow.noData')}</strong>
    <span className="ml-4 text-muted-foreground">{data ? t('simFlow.businessPeriod', { date: data.current_period ? data.current_period.cycle_end : data.reference_thursday }) : t('loading')}</span>
    {(error || data?.reason) && <p className="mt-1 text-muted-foreground">{error ? t(`simFlow.${error}`) : data?.reason} {t('simFlow.retainedResults')}</p>}
  </div>;
}

interface JobProgress {
  job_id: number; state: string; priority?: string; total: number; completed: number; running: number; queued: number;
  failed: number; cancelled: number; unknown: number; finished: number; percent: number;
  max_concurrency: number; started_at: string | null; finished_at: string | null; observed_at: string;
  failures: { task_id: string; scenario_id: string; status: string }[];
}
interface Evaluation {
  publication_decision?: { status: string; reason?: string; minimum_coverage: number } | null;
  publication?: ResultPublication | null;
  task_key: string; primary_job_id: number; job_ids: number[]; scenario_count: number; valid_scenario_count: number; missing_scenario_count: number; coverage: number; quality_gate_passed: boolean;
  subset_summary: { precision: number | null; recall: number | null; sim_repro_rate: number | null; eligible: number };
  comparison: { comparable: number; agree: number; conflicts: string[] };
  failures: { scenario_id: string; issue_id: string; outcome: string; outcome_detail: string }[];
}
interface BoardJob {
  backfill?:boolean;
  evaluation_task_key?: string; primary_execution?: boolean; job_id: number | null; status: string; scenario_count: number | null; archived: boolean; url: string | null;
  progress: JobProgress | null; progress_error: string | null; error: string | null;
}
export interface BoardData {
  versions: { release: string; is_current: boolean; cycle_status: string | null; has_job: boolean; collection_status?: string | null; collection_completed?: boolean; collection_stale?: boolean }[];
  selected: {
    release: string; is_current: boolean; kind: string; period: Workflow['current_period'] & { status?: string } | null;
    collection_anomalies?: import('../lib/simulationFlow').FlowAnomaly[];
    issue_count: number | null; scenario_count: number | null; source_metrics: Workflow['source_metrics'];
    quality_grade?: {quality_level:'normal'|'degraded'|'blocked';issue_count:number;valid_issue_count:number;abnormal_issue_count:number;issue_coverage:number;basis:'results'|'preparation'};
    issue_tolerance?: { issue_count: number; valid_issue_count: number; abnormal_issue_count: number; issue_coverage: number; preparation_failures: { issue_id: string; reason: string }[] };
    publication_policy?: { enabled: boolean; minimum_coverage: number };
    label_cycle?: LabelCycleState;
    backfill?: import('./BackfillLoop').BackfillState;
    resume?: {enabled:boolean;status?:string;reason?:string;checkpoint:string;fingerprint?:string|null};
    collection?: { source: string; collection_status: string; collection_completed?: boolean; issue_count: number | null; auto_count: number | null; manual_count: number | null; stale: boolean; monitor_status?: string | null; monitor_error_code?: string | null; monitor_error_action?: string | null; preparation?: { prepared: number; failed: number; failures: { issue_id: string; reason: string }[] } | null; quiet_seconds?: number; quiet_seconds_required?: number; last_issue_at?: string | null; last_success_at?: string | null; eligible_at?: string | null; population_changed_after_submission?: boolean } | null;
    metric_scope?: {date_start:string;date_end:string};
    metrics: Workflow['metrics']; binary_id: number | null; synced_at: string | null; population_complete: boolean; evaluation?: Evaluation | null; jobs: BoardJob[];
  };
  mode: 'manual' | 'auto'; driver_ready: boolean; scheduler_enabled: boolean; current_status: string; refreshing: boolean;
}
const jobStates: Record<string,string> = { RUNNING:'运行中', STARTING:'启动中', COMPLETED:'任务已结束', CANCELLED:'已取消', UNKNOWN_STATE:'状态待确认' };
function number(value?: number | null) { return value == null ? '—' : value.toLocaleString('zh-CN'); }
export function ReleaseWorkflow({ onOpenIssues }: { onOpenIssues: (release?: string) => void }) {
  const { t, i18n } = useTranslation();
  const [view] = useState(() => new LiveView<BoardData>(
    new URLSearchParams(window.location.search).get('version') || new URLSearchParams(window.location.search).get('release') || '@current', boardCache,
    (release, options) => request<BoardData>(`/board?${new URLSearchParams({ release, refresh: String(Boolean(options.force)) })}`, 'GET', undefined, { fresh: options.fresh || options.force }),
  ));
  const { key: release, data, error: readError, verified } = useSyncExternalStore(view.subscribe, view.getSnapshot);
  const [versionOptions, setVersionOptions] = useState<BoardData['versions']>([]);
  const [actionError, setError] = useState('');
  const error = actionError || readError;
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const writeDisabled = busy || !verified;
  const [notice, setNotice] = useState('');
  const readSidecar = () => { const q = new URLSearchParams(location.search); return q.get('sidecar') === '1'; };
  const [showAutoTriage, setShowAutoTriage] = useState(readSidecar);
  const tabId = useId();
  const [autoData, setAutoData] = useState<import('../types/evaluation').EvaluationBoard | null>(null);
  const sidecarPanel = useRef<HTMLDivElement>(null);
  const focusSidecar = useCallback(() => { sidecarPanel.current?.scrollIntoView({block:'start',behavior:'smooth'}); sidecarPanel.current?.focus({preventScroll:true}); }, []);
  const sidecarFocusPending = useRef(false);
  useEffect(() => { setAutoData(null); }, [release]);
  useEffect(() => { const pop = () => setShowAutoTriage(readSidecar()); addEventListener('popstate',pop); return () => removeEventListener('popstate',pop); }, []);
  const toggleSidecar = useCallback((enabled:boolean) => { setShowAutoTriage(enabled); const q = new URLSearchParams(location.search); q.set('sidecar',enabled?'1':'0'); history.pushState(history.state,'',`${location.pathname}?${q}`); }, []);
  const openSidecar = useCallback(() => {
    if (showAutoTriage) focusSidecar();
    else { sidecarFocusPending.current = true; toggleSidecar(true); }
  }, [showAutoTriage, focusSidecar, toggleSidecar]);
  useEffect(() => { if (showAutoTriage && sidecarFocusPending.current) { sidecarFocusPending.current = false; focusSidecar(); } }, [showAutoTriage, focusSidecar]);
  const parametersScrolled = useRef(false);
  const parameters = useRef<HTMLDivElement>(null);
  const [showParameters, setShowParameters] = useState(() => new URLSearchParams(window.location.search).get('parameters') === '1');
  const [existingJob, setExistingJob] = useState('');
  const [plan, setPlan] = useState<{fingerprint:string;release:string;binary_id:number;scenarios:unknown[];simulation:{max_concurrency:number;priority?:string}} | null>(null);
  const load = useCallback(() => view.reload(), [view]);
  const afterResume = useCallback(() => { view.invalidate(); return view.reload({fresh:true}); }, [view]);
  useEffect(()=>{
    const stop = startVisiblePolling(() => busyRef.current ? Promise.resolve(null) : load(), value => value.refreshing);
    return () => { stop(); view.cancel(); };
  },[load,release,view]);
  useEffect(() => { if (release !== '@current') void preloadFlow().catch(() => {}); }, [release]);
  useEffect(() => {
    if (data) setVersionOptions(previous => JSON.stringify(previous) === JSON.stringify(data.versions) ? previous : data.versions);
  }, [data]);
  useEffect(() => {
    const onPopState = () => { if (!busyRef.current) { view.select(new URLSearchParams(window.location.search).get('version') || new URLSearchParams(window.location.search).get('release') || '@current'); setPlan(null); setError(''); } };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [view]);
  const act=async(fn:()=>Promise<void>)=>{
    if (busyRef.current || !view.getSnapshot().verified) return;
    busyRef.current=true;setBusy(true);setError('');setNotice('');view.invalidate();
    try { await fn(); } catch(err) {setError(err instanceof Error?err.message:String(err));}
    finally {await view.reload({fresh:true});busyRef.current=false;setBusy(false);}
  };
  const refresh=async()=>{
    if (busyRef.current) return;
    busyRef.current=true;setBusy(true);setError('');
    try { await view.reload({force:true}); } finally {busyRef.current=false;setBusy(false);}
  };
  const selected=data?.selected;
  useEffect(() => { if (selected && verified) recordLoadStage('board'); }, [selected, verified]);
  useEffect(() => {
    if (!selected || showParameters || !parameters.current) return;
    const observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) { setShowParameters(true); observer.disconnect(); } }, {rootMargin:'160px'});
    observer.observe(parameters.current);
    return () => observer.disconnect();
  }, [selected?.release, showParameters]);
  useEffect(() => {
    if (selected && !parametersScrolled.current && new URLSearchParams(window.location.search).get('parameters') === '1') {
      setShowParameters(true);
      parameters.current?.scrollIntoView({ block: 'start' });
      parametersScrolled.current = true;
    }
  }, [selected?.release]);
  const jobs=selected?.jobs || [];
  const activeJob=jobs.some(job=>job.progress ? ['RUNNING','STARTING'].includes(job.progress.state) : ['queued','submitting','submission_uncertain','running','verifying'].includes(job.status));
  const relevantJobs = jobs.filter(job =>
    job.job_id === selected?.evaluation?.primary_job_id ||
    (job.progress ? ['RUNNING','STARTING'].includes(job.progress.state) :
      ['queued','submitting','submission_uncertain','running','verifying'].includes(job.status))
  );
  const visibleJobs = relevantJobs.length ? relevantJobs : jobs.filter(job =>
    job.status !== 'cancelled' && job.status !== 'cancelled_stale' && job.progress?.state !== 'CANCELLED'
  ).slice(0, 1);
  const otherJobs = jobs.filter(job => !visibleJobs.includes(job));
  const source=selected?.source_metrics;
  function choose(value:string){if(busyRef.current || value===release)return;view.select(value);setError('');setPlan(null);setNotice('');setExistingJob('');const url=new URL(window.location.href);url.search=changeEvaluationReleaseQuery(url.searchParams,value).toString();window.history.replaceState(window.history.state,'',url.pathname+url.search);}
  return <div className="min-w-0 space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-semibold">{t('simFlow.boardTitle')}</h2></div><div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" className="min-h-11" disabled={busy} onClick={()=>void refresh()}><RefreshCw className={`h-4 w-4${busy ? ' animate-spin' : ''}`}/>{t('simFlow.refreshProgress')}</Button>
      <Button variant="outline" className="min-h-11" disabled={!selected} aria-controls="simulation-parameters-entry" onClick={() => {setShowParameters(true);parameters.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });}}><SlidersHorizontal className="h-4 w-4"/>{t('simFlow.parameters')}</Button>
      <div id="evaluation-actions" className="contents"/>
      <Button variant="outline" className="min-h-11" disabled={!selected} onClick={()=>onOpenIssues(selected?.is_current?undefined:selected?.release)}>{t('simFlow.issueDetails')}<ArrowUpRight className="h-4 w-4"/></Button>
    </div></div>
    <nav aria-label={t('simFlow.versionFlows')} className="flex max-w-full gap-2 overflow-x-auto rounded-lg border bg-card/60 p-2">
      <Button className="min-h-11" disabled={busy} variant={release==='@current'?'default':'ghost'} aria-pressed={release==='@current'} onClick={()=>choose('@current')}>{t('simFlow.followCurrent')}</Button>
      {versionOptions.map(version=>{const status=version.collection_completed?'evaluation.collection_complete':version.collection_stale?'evaluation.collection_pending_update':version.collection_status==='collecting'?'simFlow.collectingShort':null;return <Button key={version.release} className="min-h-11" disabled={busy} variant={release===version.release?'default':'ghost'} aria-pressed={release===version.release} title={`${version.release}${status ? ` · ${t(status)}` : ''}${version.collection_stale && version.collection_completed ? ` · ${t('evaluation.collection_pending_update')}` : ''}`} onClick={()=>choose(version.release)}>{releaseName(version.release)}{status && <span className="text-xs opacity-80">{t(status)}</span>}</Button>;})}
    </nav>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
    {selected && !verified && !readError && <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground"><RefreshCw className="h-3.5 w-3.5 animate-spin"/>{t('simFlow.checkingSnapshot')}</p>}
    {!selected ? <Card role="status" aria-busy="true"><CardContent className="p-10 text-center text-sm text-muted-foreground">{t('simFlow.loadingBoard')}</CardContent></Card> : <>
      <div className="flex flex-wrap items-center gap-3"><h3 className="font-semibold" title={selected.release}>{releaseName(selected.release)}</h3>{selected.is_current && <Badge variant="secondary">{t('simFlow.businessVersion')}</Badge>}{selected.kind==='archived' && <Badge>{t('evaluation.result_archived')}</Badge>}{selected.metrics.basis && <Badge variant="outline">{t('evaluation.source_shuyi')}</Badge>}{selected.collection?.collection_completed ? <Badge variant="success">{t('evaluation.collection_complete')}</Badge> : selected.period?.status==='running' && <Badge variant="warning">{t('simFlow.collecting')}</Badge>}{selected.collection?.stale && <Badge variant="outline">{t('evaluation.collection_pending_update')}</Badge>}<span className="text-xs text-muted-foreground">{selected.metric_scope ? `${selected.metric_scope.date_start} — ${selected.metric_scope.date_end}` : selected.period?.cycle_end ? `${selected.period.case_start.slice(0,10)} — ${selected.period.cycle_end}` : selected.kind==='archived'?t('evaluation.result_archived'):''}</span></div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Stat title={t('evaluation.source_eligible_count')} value={number(source?.eligible)} detail={source?.excluded != null?t('evaluation.source_excluded_count',{amount:number(source.excluded)}):undefined}/><Stat title={t('evaluation.source_scenario_count')} value={number(selected.scenario_count)} detail={selected.issue_count != null?t('evaluation.source_auto_issue_count',{amount:number(selected.issue_count)}):undefined}/><Stat title={t('evaluation.source_online_precision')} value={metricRate(source?.online_precision)} color="text-blue-600 dark:text-blue-400"/><Stat title={t('evaluation.source_online_recall')} value={metricRate(source?.online_recall)} color="text-orange-600 dark:text-orange-400"/></div>
      {!selected.metrics.basis && <Suspense fallback={<Card role="status" className="p-5 text-sm text-muted-foreground">{t('simFlow.loading')}</Card>}>
        <SimulationFlow key={selected.release} data={data!} stale={Boolean(readError)} readOnly={writeDisabled} onRefresh={afterResume} autoTriageEnabled autoTriage={autoData?.context.release === selected.release ? autoData : null} onOpenAutoTriage={openSidecar}/>
      </Suspense>}
      <div role="tablist" aria-label={t('evaluation.simulation_views')} className="flex flex-wrap gap-1 rounded-lg bg-muted p-1">
        {([['results','evaluation.issue_simulation'],['sidecar','evaluation.sidecar_title']] as const).map(([key,label],index) => <button key={key} id={`${tabId}-${key}`} type="button" role="tab" aria-selected={showAutoTriage === (key === 'sidecar')} aria-controls={`${tabId}-${key}-panel`} tabIndex={showAutoTriage === (key === 'sidecar') ? 0 : -1} onClick={() => toggleSidecar(key === 'sidecar')} onKeyDown={event => {
          if (['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1-index; toggleSidecar(next===1); document.getElementById(`${tabId}-${next ? 'sidecar' : 'results'}`)?.focus(); }
        }} className={`min-h-11 min-w-0 rounded-md px-4 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${showAutoTriage === (key === 'sidecar') ? 'bg-card font-medium text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}>{t(label)}</button>)}
      </div>
      <div ref={sidecarPanel} hidden={!showAutoTriage} role="tabpanel" id={`${tabId}-sidecar-panel`} aria-labelledby={`${tabId}-sidecar`} tabIndex={-1} className="min-w-0 scroll-mt-4 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"><Suspense fallback={<p role="status">{t('loading')}</p>}><EvaluationWorkspace key={selected.release} release={selected.release} hideRelease embedded page="simulation" onDataChange={setAutoData} onNavigate={()=>onOpenIssues(selected.release)}/></Suspense></div>
      <div hidden={showAutoTriage} role="tabpanel" id={`${tabId}-results-panel`} aria-labelledby={`${tabId}-results`} className="min-w-0 space-y-5">
      <div className={simulationResultsGrid}>
        <div className="min-w-0 space-y-4">{selected.evaluation ? <>
          <Card><CardHeader><CardTitle>同版本评测任务 · {selected.evaluation.scenario_count.toLocaleString()} 场景</CardTitle><p className="text-xs text-muted-foreground">{selected.evaluation.job_ids.length} 次执行，共用同一场景与参数；每个场景仅统计一次。</p></CardHeader><CardContent className="space-y-4"><div className="grid gap-3 sm:grid-cols-3"><Stat title="有效场景" value={number(selected.evaluation.valid_scenario_count)}/><Stat title={selected.evaluation.publication?"未计入指标的异常":"待补齐结果"} value={number(selected.evaluation.missing_scenario_count)} color="text-amber-700"/><Stat title="结果覆盖率" value={metricRate(selected.evaluation.coverage)}/></div><p className="text-sm text-muted-foreground">主结果 Job {selected.evaluation.primary_job_id} · 复跑可比 {number(selected.evaluation.comparison.comparable)} 条 · 触发一致 {number(selected.evaluation.comparison.agree)} 条 · 差异 {number(selected.evaluation.comparison.conflicts.length)} 条</p>{selected.evaluation.comparison.conflicts.length > 0 && <details className="rounded border p-3 text-sm"><summary>两次执行触发差异（{selected.evaluation.comparison.conflicts.length} 条）</summary><p className="mt-2 break-all font-mono text-xs">{selected.evaluation.comparison.conflicts.join('、')}</p></details>}{selected.evaluation.failures.length > 0 && <details className="rounded border p-3 text-sm"><summary>失败与待核验场景（{selected.evaluation.failures.length} 条）</summary><div className="mt-3 space-y-3">{selected.evaluation.failures.map(row=><div key={row.scenario_id} className="border-t pt-2"><p className="font-mono text-xs">Scenario {row.scenario_id} · {row.issue_id}</p><p className="mt-1 break-all text-xs text-muted-foreground">{row.outcome || '结果质量未通过'}</p>{row.outcome_detail && <p className="mt-1 whitespace-pre-wrap break-all text-xs text-muted-foreground">{row.outcome_detail}</p>}</div>)}</div></details>}</CardContent></Card>
        </> : null}
        {visibleJobs.map((job,index)=><JobCard key={job.job_id || index} job={job}/>)}
        {otherJobs.length > 0 && <details className="border-t border-border/70 pt-4"><summary className="min-h-11 cursor-pointer py-3 text-sm text-muted-foreground hover:text-foreground">{t('evaluation.other_execution_records',{amount:number(otherJobs.length)})}</summary><div className="mt-4 space-y-4">{otherJobs.map((job,index)=><JobCard key={job.job_id || index} job={job}/>)}</div></details>}
        {jobs.length ? null : <Card><CardContent className="flex flex-col items-center gap-3 p-10 text-center"><Layers3 className="h-8 w-8 text-muted-foreground"/><h3 className="font-semibold">{t(selected.collection?.source==='observation'?'simFlow.awaitStable':'simFlow.noJobs')}</h3><p className="text-sm text-muted-foreground">{t(selected.collection?.source==='observation'?(data.mode==='auto'?'simFlow.autoAfterStable':'simFlow.manualAfterStable'):'simFlow.awaitExecution')}</p></CardContent></Card>}</div>
        <div className="min-w-0 space-y-4">
          <SimulationMetricCard
            status={t(selected.metrics.basis && !selected.metrics.available ? 'evaluation.partial_short' : selected.metrics.publication?'evaluation.result_published':selected.metrics.archived?'evaluation.result_archived':selected.metrics.available?'evaluation.result_accepted':selected.evaluation?'evaluation.result_unaccepted':'evaluation.result_pending')}
            variant={selected.metrics.basis && !selected.metrics.available ? 'warning' : selected.metrics.archived && !selected.metrics.quality_gate_passed?'warning':selected.metrics.available?'success':'outline'}
            available={selected.metrics.available || Boolean(selected.metrics.basis && selected.metrics.covered)} precision={selected.metrics.covered_precision ?? selected.metrics.precision} recall={selected.metrics.covered_recall ?? selected.metrics.recall} reproduction={selected.metrics.covered_repro_rate ?? selected.metrics.sim_repro_rate} reproductionScope={selected.metrics.reproduction} decimals={selected.metrics.basis ? 2 : 1}
            summary={selected.metrics.basis ? t('evaluation.covered_scope',{covered:number(selected.metrics.covered),eligible:number(selected.metrics.eligible)}) : selected.metrics.publication ? selected.metrics.publication.issue_count != null ? t('labelLoop.metricPopulation',{valid:number(selected.metrics.publication.valid_issue_count),total:number(selected.metrics.publication.issue_count),count:selected.metrics.publication.abnormal_issue_count || 0}) : t('evaluation.result_scene_coverage',{valid:number(selected.metrics.publication.valid_scenario_count),total:number(selected.metrics.publication.scenario_count),excluded:number(selected.metrics.publication.excluded_scenario_ids.length)}) : undefined}>
              {selected.metrics.publication && <details key={selected.release} className="text-xs leading-5 text-muted-foreground">
                <summary className="cursor-pointer hover:text-foreground">{t('evaluation.result_scope')}</summary>
                <div className="mt-2 space-y-1">
                  <p>{t('labelLoop.metricScope')}</p>
                  {selected.metrics.publication.automatic && <p>{t('labelLoop.metricCoverage',{coverage:metricRate(selected.metrics.publication.issue_coverage ?? selected.metrics.publication.coverage),threshold:metricRate(selected.metrics.publication.minimum_coverage)})}</p>}
                  <p>{t('labelLoop.metricSources',{jobs:(selected.metrics.publication.source_job_ids || [selected.metrics.publication.primary_job_id]).join(', ')})}</p>
                  <p>{t('labelLoop.metricObserved')}</p>
                </div>
              </details>}
              {selected.metrics.archived && !selected.metrics.quality_gate_passed && <p className="text-xs leading-5 text-amber-700 dark:text-amber-400">{t('evaluation.result_archived_note')}</p>}
              {!selected.metrics.available && <p className="text-xs leading-5 text-muted-foreground">{selected.metrics.basis ? t('evaluation.complete_pending',{amount:selected.metrics.missing_results}) : activeJob?t('evaluation.result_running_note'):selected.evaluation?(selected.evaluation.publication_decision?.reason || t('evaluation.result_verifying_note')):jobs.length?t('evaluation.result_pending_note'):t('evaluation.result_empty_note')}</p>}
          </SimulationMetricCard>
          {selected.evaluation && !selected.evaluation.publication && !selected.evaluation.quality_gate_passed && <Card><CardHeader><CardTitle>有效样本参考</CardTitle><Badge variant="warning">尚未达到发布条件</Badge></CardHeader><CardContent className="space-y-3"><p className="text-xs leading-5 text-muted-foreground">仅统计主结果中通过场景质量检查的 {number(selected.evaluation.subset_summary.eligible)} 个样本，覆盖率 {metricRate(selected.evaluation.coverage)}；失败样本未计入准召分母。</p>{[['精确率',selected.evaluation.subset_summary.precision],['召回率',selected.evaluation.subset_summary.recall],['行为复现率',selected.evaluation.subset_summary.sim_repro_rate]].map(([label,value])=><div key={String(label)} className="flex justify-between text-sm"><span>{label}</span><strong className="font-mono">{metricRate(value as number | null)}</strong></div>)}<p className="text-xs leading-5 text-amber-700">{selected.evaluation.publication_decision?.reason || t('simFlow.thresholdNote')}</p></CardContent></Card>}
          {selected.is_current && <Card><CardHeader><CardTitle>仿真操作</CardTitle></CardHeader><CardContent className="space-y-3"><div className="flex flex-wrap items-center justify-between gap-2 text-sm"><span>{t('simFlow.mode')}</span><Select label={t('simFlow.mode')} value={data.mode} disabled={writeDisabled} options={[{value:'manual',label:t('simFlow.manualMode')},{value:'auto',label:t('simFlow.autoMode'),disabled:!data.driver_ready || !data.scheduler_enabled}]} onChange={mode=>{void act(async()=>{await request('/mode','PUT',{mode});setNotice(t('simFlow.modeSaved',{mode:t(mode==='auto'?'simFlow.autoMode':'simFlow.manualMode')}));});}}/></div><Button className="w-full" disabled={writeDisabled || activeJob || data.current_status!=='ready'} onClick={()=>void act(async()=>setPlan(await request('/plan')))}>{activeJob?'已有任务运行中':'预览仿真计划'}</Button><p className="text-xs leading-5 text-muted-foreground">自动模式会补齐场景并提交仿真；Issue 同步每 15 分钟独立运行。</p>{notice && <p role="status" className="text-sm text-primary">{notice}</p>}</CardContent></Card>}
        </div>
      </div>
      {plan && selected.is_current && <Card><CardHeader><CardTitle>待提交计划</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><p title={plan.release}>{releaseName(plan.release)} · Binary {plan.binary_id} · {number(plan.scenarios.length)} 个场景</p><p className="text-xs text-muted-foreground">完整周期，prod_gen4，并发 {number(plan.simulation.max_concurrency)}，优先级 {plan.simulation.priority || 'NORMAL'}，禁用缓存，启用 DPE；沿用历史基线参数。</p><div className="flex flex-wrap gap-2"><Button disabled={writeDisabled || activeJob} onClick={()=>void act(async()=>{const result=await request<{status:string}>('/submit','POST',{fingerprint:plan.fingerprint});setNotice(stateNames[result.status]||result.status);setPlan(null);})}>提交此计划</Button><input aria-label="已有 Job ID" placeholder="关联已有 Job ID" className="rounded border bg-background p-2" value={existingJob} onChange={event=>setExistingJob(event.target.value)}/><Button variant="outline" disabled={writeDisabled || !/^\d+$/.test(existingJob)} onClick={()=>void act(async()=>{await request('/attach','POST',{fingerprint:plan.fingerprint,job_id:Number(existingJob)});setPlan(null);setNotice('Job 已关联，正在核验');})}>关联并核验</Button></div></CardContent></Card>}
      <details data-release-runtime-config className="rounded-lg border bg-card/60 p-4"><summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">{t('evaluation.release_runtime_config')}</summary><p className="mt-3 break-all text-xs text-muted-foreground">{t('evaluation.release_identifier',{release:selected.release})}</p><div className="mt-4 grid gap-4 text-sm sm:grid-cols-3"><div><p className="text-xs text-muted-foreground">{t('evaluation.target_build_binary')}</p><p className="mt-1 break-all">{selected.period?.target_road_version || selected.release}</p><p className="font-mono text-xs text-muted-foreground">{selected.binary_id || '—'}</p></div><div><p className="text-xs text-muted-foreground">{t('evaluation.last_source_sync')}</p><p className="mt-1">{selected.synced_at ? new Date(selected.synced_at).toLocaleString(i18n.language.startsWith('zh')?'zh-CN':'en-GB',{timeZone:'Asia/Shanghai',hour12:false}) : t('evaluation.source_not_synced')}</p></div><div><p className="text-xs text-muted-foreground">{t('evaluation.data_definition')}</p><p className="mt-1 break-words">{t(selected.metrics.basis?'evaluation.ordinary_shuyi_definition':selected.kind==='archived'?'evaluation.archived_definition':selected.period?.status==='running'?'evaluation.collecting_definition':'evaluation.release_cycle_definition')}</p></div></div>{selected.period?.evidence && !selected.metrics.basis && <p className="mt-4 border-t pt-3 text-xs leading-5 text-muted-foreground">{t('evaluation.period_evidence',{evidence:selected.period.evidence})}</p>}</details>
      </div>
      <div ref={parameters} id="simulation-parameters-entry" className="scroll-mt-6 min-w-0">
        {showParameters ? <Suspense fallback={<Card role="status" className="p-5 text-sm text-muted-foreground">{t('loading')}</Card>}><SimulationParameters key={selected.release} release={selected.release} binaryId={selected.binary_id} scenarioId={new URLSearchParams(window.location.search).get('scenario') || undefined}/></Suspense> : <Card className="p-4"><Button variant="ghost" className="min-h-11" onClick={() => setShowParameters(true)}><SlidersHorizontal className="h-4 w-4"/>{t('simFlow.parameters')}</Button></Card>}
      </div>
    </>}
  </div>;
}
