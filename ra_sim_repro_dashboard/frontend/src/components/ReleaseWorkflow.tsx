import type { LabelCycleState } from './CollectionLoop';
import { releaseName } from '../lib/releaseName';
import type { ResultPublication } from "../types";
import { lazy, memo, Suspense, useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Select } from './ui/select';
import { Activity, ArrowUpRight, ExternalLink, Layers3, RefreshCw, SlidersHorizontal } from 'lucide-react';

import { request } from '../api/workflow';
import { LiveView, ViewCache } from '../lib/liveView';
import { startVisiblePolling } from '../lib/visiblePolling';
export { request } from '../api/workflow';

let flowModule: Promise<typeof import('./SimulationFlow')> | undefined;
const preloadFlow = () => flowModule ||= import('./SimulationFlow').catch(error => { flowModule = undefined; throw error; });
const SimulationFlow = lazy(preloadFlow);
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
  metrics: { publication?: ResultPublication | null; available: boolean; archived?: boolean; quality_gate_passed?: boolean; precision?: number; recall?: number; sim_repro_rate?: number; online_precision?: number; online_recall?: number; reason?: string; job_id?: number };
  mode: 'manual' | 'auto'; driver_ready: boolean; scheduler_enabled: boolean;
  synced_at: string | null; issue_count: number; scenario_count: number; manual_population_count: number;
  last_sync: { status?: string; reason?: string; mapping_error?: string; checked_at?: string };
  periods: { release: string; verified: boolean; basis: string | null; status: string; cycle_end: string }[];
  batches: { fingerprint: string; release: string; status: string; job_id: string | null; scenario_count: number }[];
}
export interface SourceIssue {
  ra_type?: number;
  issue_id: string; issue_topic: string; source_result: string | null; road_version: string; scenario_id: string; scenario_name: string; scenario_labels: string[];
  job_id?: number; result_note?: string; execution_conflict?: boolean; simulation_status: string; sim_triggered: boolean | null; reproduced: boolean | null; precision_label: string | null;
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
  versions: { release: string; is_current: boolean; cycle_status: string | null; has_job: boolean; collection_status?: string | null }[];
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
    collection?: { source: string; collection_status: string; issue_count: number | null; auto_count: number | null; manual_count: number | null; stale: boolean; monitor_status?: string | null; monitor_error_code?: string | null; monitor_error_action?: string | null; preparation?: { prepared: number; failed: number; failures: { issue_id: string; reason: string }[] } | null; quiet_seconds?: number; quiet_seconds_required?: number; last_issue_at?: string | null; last_success_at?: string | null; eligible_at?: string | null; population_changed_after_submission?: boolean } | null;
    metrics: Workflow['metrics']; binary_id: number | null; synced_at: string | null; population_complete: boolean; evaluation?: Evaluation | null; jobs: BoardJob[];
  };
  mode: 'manual' | 'auto'; driver_ready: boolean; scheduler_enabled: boolean; current_status: string; refreshing: boolean;
}
const jobStates: Record<string,string> = { RUNNING:'运行中', STARTING:'启动中', COMPLETED:'任务已结束', CANCELLED:'已取消', UNKNOWN_STATE:'状态待确认' };
function number(value?: number | null) { return value == null ? '—' : value.toLocaleString('zh-CN'); }
function duration(progress: JobProgress) {
  if (!progress.started_at) return '—';
  const seconds = Math.max(0, Math.floor((Date.parse(progress.finished_at || progress.observed_at) - Date.parse(progress.started_at)) / 1000));
  if (!Number.isFinite(seconds)) return '—';
  return seconds >= 3600 ? `${Math.floor(seconds / 3600)} 小时 ${Math.floor(seconds % 3600 / 60)} 分` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}
function Stat({ title, value, detail, color = '' }: { title: string; value: string; detail?: string; color?: string }) {
  return <div className="rounded-lg border bg-card/70 p-4"><p className="text-xs text-muted-foreground">{title}</p><p className={`mt-2 font-mono text-2xl font-semibold tabular-nums ${color}`}>{value}</p>{detail && <p className="mt-1 text-xs text-muted-foreground">{detail}</p>}</div>;
}
function JobCard({ job }: { job: BoardJob }) {
  const p = job.progress;
  const parts = p ? [
    {key:'completed', label:'成功', value:p.completed, color:'bg-emerald-500', text:'text-emerald-700 dark:text-emerald-400'},
    {key:'running', label:'运行中', value:p.running, color:'bg-blue-500', text:'text-blue-600 dark:text-blue-400'},
    {key:'queued', label:'排队', value:p.queued, color:'bg-slate-300 dark:bg-slate-600', text:''},
    {key:'failed', label:'失败', value:p.failed, color:'bg-red-500', text:'text-red-600 dark:text-red-400'},
    {key:'cancelled', label:'取消', value:p.cancelled, color:'bg-amber-500', text:'text-amber-700 dark:text-amber-400'},
    {key:'unknown', label:'未知', value:p.unknown, color:'bg-violet-400', text:'text-violet-600'},
  ] : [];
  const active = p ? ['RUNNING','STARTING'].includes(p.state) : ['running','queued','submitting'].includes(job.status);
  return <Card className="overflow-hidden">
    <CardHeader><div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3"><div className="rounded-lg bg-primary/10 p-2"><Activity className="h-5 w-5 text-primary"/></div><div><CardTitle>Job {job.job_id || '待分配'}</CardTitle><p className="mt-1 text-xs text-muted-foreground">{job.primary_execution ? '执行记录 · 主结果' : job.evaluation_task_key ? '执行记录 · 复跑对照' : job.archived ? '历史归档任务' : '完整周期仿真'}</p></div></div>
      <div className="flex items-center gap-3">{p?.priority && <Badge variant={p.priority==='HIGH'?'warning':'outline'}>{p.priority==='HIGH'?'高优先级':p.priority==='NORMAL'?'普通优先级':p.priority}</Badge>}<Badge variant={active ? 'secondary' : p?.failed ? 'warning' : p?.state === 'COMPLETED' ? 'success' : 'outline'}>{active && <span className="h-1.5 w-1.5 rounded-full bg-blue-500"/>}{p ? jobStates[p.state] || p.state : stateNames[job.status] || job.status}</Badge>{job.url && <a href={job.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-primary">Orion 详情<ExternalLink className="h-3.5 w-3.5"/></a>}</div>
    </div></CardHeader>
    <CardContent className="space-y-5">
      {p ? <>
        <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs text-muted-foreground">任务进度 · 已结束</p><p className="mt-1 font-mono text-3xl font-semibold tabular-nums">{p.percent.toFixed(p.finished > 0 && p.finished < p.total && (p.percent < 1 || p.percent > 99) ? 2 : 1)}<span className="ml-1 text-lg text-muted-foreground">%</span></p></div><div className="text-right"><p className="font-mono text-sm tabular-nums">{number(p.finished)} / {number(p.total)} 场景</p><p className="mt-1 text-xs text-muted-foreground">成功 + 失败 + 取消</p></div></div>
        <div role="progressbar" aria-label={`Job ${job.job_id} 已结束进度`} aria-valuemin={0} aria-valuemax={p.total || 1} aria-valuenow={p.finished} className="flex h-3 overflow-hidden rounded-full bg-muted">{parts.filter(part => part.value > 0).map(part => <div key={part.key} className={part.color} title={`${part.label} ${part.value}`} style={{width:`${p.total ? part.value / p.total * 100 : 0}%`, minWidth:2}}/>)}</div>
        <dl className="grid grid-cols-3 gap-x-5 gap-y-4 sm:grid-cols-5">{parts.filter(part => part.key !== 'unknown' || part.value > 0).map(part => <div key={part.key}><dt className="text-xs text-muted-foreground">{part.label}</dt><dd className={`mt-1 font-mono text-2xl font-semibold tabular-nums ${part.text}`}>{number(part.value)}</dd></div>)}</dl>
        <div className="flex flex-wrap justify-between gap-3 border-t pt-3 text-xs text-muted-foreground"><span>并发上限 <strong className="text-foreground">{number(p.max_concurrency)}</strong> · 已用时 {duration(p)}</span><span>更新于 {localTime(p.observed_at)}</span></div>
        {(job.progress_error || job.error) && <p role="alert" className="rounded border border-amber-400/40 bg-amber-50/50 p-3 text-sm text-amber-800 dark:bg-amber-950/20 dark:text-amber-300">{job.progress_error ? `进度更新失败，保留上次数据：${job.progress_error}` : `结果核验提示：${job.error}`}</p>}
        {p.failures.length > 0 && <details className="border-t pt-3 text-sm"><summary className="cursor-pointer text-muted-foreground">异常任务示例（{p.failures.length} 条）</summary><div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th className="p-2">Task</th><th className="p-2">Scenario</th><th className="p-2">状态</th></tr></thead><tbody>{p.failures.map(task=><tr key={task.task_id} className="border-t"><td className="p-2 font-mono">{task.task_id}</td><td className="p-2 font-mono">{task.scenario_id}</td><td className="p-2">{task.status === 'FAILED' ? '失败' : '已取消'}</td></tr>)}</tbody></table></div></details>}
      </> : <div className="rounded-lg bg-muted/40 p-6 text-center text-sm text-muted-foreground"><p>{job.progress_error ? `暂时无法获取进度：${job.progress_error}` : job.job_id ? '正在读取 Orion 任务进度…' : '正在准备任务，等待 Job 回执'}</p><p className="mt-2">计划 {number(job.scenario_count)} 个场景</p></div>}
    </CardContent>
  </Card>;
}

export function ReleaseWorkflow({ onOpenIssues }: { onOpenIssues: (release?: string) => void }) {
  const { t } = useTranslation();
  const [view] = useState(() => new LiveView<BoardData>(
    new URLSearchParams(window.location.search).get('version') || '@current', boardCache,
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
    const onPopState = () => { if (!busyRef.current) { view.select(new URLSearchParams(window.location.search).get('version') || '@current'); setPlan(null); setError(''); } };
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
  function choose(value:string){if(busyRef.current || value===release)return;view.select(value);setError('');setPlan(null);setNotice('');setExistingJob('');const url=new URL(window.location.href);if(value==='@current')url.searchParams.delete('version');else url.searchParams.set('version',value);window.history.replaceState(window.history.state,'',url.pathname+url.search);}
  return <div className="min-w-0 space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-semibold">{t('simFlow.boardTitle')}</h2><p className="mt-1 text-xs text-muted-foreground">{t('simFlow.boardSubtitle')}</p></div><div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" className="min-h-11" disabled={busy} onClick={()=>void refresh()}><RefreshCw className={`h-4 w-4${busy ? ' animate-spin' : ''}`}/>{t('simFlow.refreshProgress')}</Button>
      <Button variant="outline" className="min-h-11" disabled={!selected} aria-controls="simulation-parameters-entry" onClick={() => {setShowParameters(true);parameters.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });}}><SlidersHorizontal className="h-4 w-4"/>{t('simFlow.parameters')}</Button>
      <Button variant="outline" className="min-h-11" disabled={!selected} onClick={()=>onOpenIssues(selected?.is_current?undefined:selected?.release)}>{t('simFlow.issueDetails')}<ArrowUpRight className="h-4 w-4"/></Button>
    </div></div>
    <nav aria-label={t('simFlow.versionFlows')} className="flex max-w-full gap-2 overflow-x-auto rounded-lg border bg-card/60 p-2">
      <Button className="min-h-11" disabled={busy} variant={release==='@current'?'default':'ghost'} aria-pressed={release==='@current'} onClick={()=>choose('@current')}>{t('simFlow.followCurrent')}</Button>
      {versionOptions.map(version=><Button key={version.release} className="min-h-11" disabled={busy} variant={release===version.release?'default':'ghost'} aria-pressed={release===version.release} title={version.release} onClick={()=>choose(version.release)}>{releaseName(version.release)}{version.collection_status==='collecting' && <span className="text-xs opacity-80">{t('simFlow.collectingShort')}</span>}</Button>)}
    </nav>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
    {selected && !verified && !readError && <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground"><RefreshCw className="h-3.5 w-3.5 animate-spin"/>{t('simFlow.checkingSnapshot')}</p>}
    {!selected ? <Card role="status" aria-busy="true"><CardContent className="p-10 text-center text-sm text-muted-foreground">{t('simFlow.loadingBoard')}</CardContent></Card> : <>
      <div className="flex flex-wrap items-center gap-3"><h3 className="font-semibold" title={selected.release}>{releaseName(selected.release)}</h3>{selected.is_current && <Badge variant="secondary">当前业务版本</Badge>}{selected.kind==='archived' && <Badge>历史归档</Badge>}{selected.period?.status==='running' && <Badge variant="warning">路测收集中</Badge>}<span className="text-xs text-muted-foreground">{selected.period?.cycle_end ? `${selected.period.case_start.slice(0,10)} — ${selected.period.cycle_end}` : selected.kind==='archived'?'已归档的版本评测':''}</span></div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Stat title="可评测样本" value={number(source?.eligible)} detail={source?.excluded != null?`口径排除 ${number(source.excluded)} 条`:undefined}/><Stat title="关联场景" value={number(selected.scenario_count)} detail={selected.issue_count != null?`自动触发 Issue ${number(selected.issue_count)} 条`:undefined}/><Stat title="线上精确率" value={metricRate(source?.online_precision)} color="text-blue-600 dark:text-blue-400"/><Stat title="线上召回率" value={metricRate(source?.online_recall)} color="text-orange-600 dark:text-orange-400"/></div>
      <Suspense fallback={<Card role="status" className="p-5 text-sm text-muted-foreground">{t('simFlow.loading')}</Card>}>
        {release !== '@current' && <SimulationFlow key={selected.release} data={data!} stale={Boolean(readError)} readOnly={writeDisabled} onRefresh={afterResume} />}
      </Suspense>
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0 space-y-4">{selected.evaluation ? <>
          <Card><CardHeader><CardTitle>同版本评测任务 · {selected.evaluation.scenario_count.toLocaleString()} 场景</CardTitle><p className="text-xs text-muted-foreground">{selected.evaluation.job_ids.length} 次执行，共用同一场景与参数；每个场景仅统计一次。</p></CardHeader><CardContent className="space-y-4"><div className="grid gap-3 sm:grid-cols-3"><Stat title="有效场景" value={number(selected.evaluation.valid_scenario_count)}/><Stat title={selected.evaluation.publication?"未计入指标的异常":"待补齐结果"} value={number(selected.evaluation.missing_scenario_count)} color="text-amber-700"/><Stat title="结果覆盖率" value={metricRate(selected.evaluation.coverage)}/></div><p className="text-sm text-muted-foreground">主结果 Job {selected.evaluation.primary_job_id} · 复跑可比 {number(selected.evaluation.comparison.comparable)} 条 · 触发一致 {number(selected.evaluation.comparison.agree)} 条 · 差异 {number(selected.evaluation.comparison.conflicts.length)} 条</p>{selected.evaluation.comparison.conflicts.length > 0 && <details className="rounded border p-3 text-sm"><summary>两次执行触发差异（{selected.evaluation.comparison.conflicts.length} 条）</summary><p className="mt-2 break-all font-mono text-xs">{selected.evaluation.comparison.conflicts.join('、')}</p></details>}{selected.evaluation.failures.length > 0 && <details className="rounded border p-3 text-sm"><summary>失败与待核验场景（{selected.evaluation.failures.length} 条）</summary><div className="mt-3 space-y-3">{selected.evaluation.failures.map(row=><div key={row.scenario_id} className="border-t pt-2"><p className="font-mono text-xs">Scenario {row.scenario_id} · {row.issue_id}</p><p className="mt-1 break-all text-xs text-muted-foreground">{row.outcome || '结果质量未通过'}</p>{row.outcome_detail && <p className="mt-1 whitespace-pre-wrap break-all text-xs text-muted-foreground">{row.outcome_detail}</p>}</div>)}</div></details>}</CardContent></Card>
        </> : null}
        {visibleJobs.map((job,index)=><JobCard key={job.job_id || index} job={job}/>)}
        {otherJobs.length > 0 && <details className="border-t border-border/70 pt-4"><summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">其他执行记录（{otherJobs.length}）</summary><div className="mt-4 space-y-4">{otherJobs.map((job,index)=><JobCard key={job.job_id || index} job={job}/>)}</div></details>}
        {jobs.length ? null : <Card><CardContent className="flex flex-col items-center gap-3 p-10 text-center"><Layers3 className="h-8 w-8 text-muted-foreground"/><h3 className="font-semibold">{t(selected.collection?.source==='observation'?'simFlow.awaitStable':'simFlow.noJobs')}</h3><p className="text-sm text-muted-foreground">{t(selected.collection?.source==='observation'?(data.mode==='auto'?'simFlow.autoAfterStable':'simFlow.manualAfterStable'):'simFlow.awaitExecution')}</p></CardContent></Card>}</div>
        <div className="min-w-0 space-y-4">
          <Card>
            <CardHeader><div className="flex items-center justify-between"><CardTitle>仿真评测结果</CardTitle><Badge variant={selected.metrics.archived && !selected.metrics.quality_gate_passed?'warning':selected.metrics.available?'success':'outline'}>{selected.metrics.publication?(selected.metrics.publication.automatic?'覆盖率达标 · 已发布':'已发布'):selected.metrics.archived?'归档指标':selected.metrics.available?'已通过验收':selected.evaluation?'验收未通过':'待就绪'}</Badge></div></CardHeader>
            <CardContent className="space-y-3">
              {selected.metrics.publication && <p className="flex flex-wrap gap-x-1 text-xs leading-5 text-muted-foreground"><span>有效 {number(selected.metrics.publication.valid_scenario_count)} / {number(selected.metrics.publication.scenario_count)}</span><span>· 排除异常 {number(selected.metrics.publication.excluded_scenario_ids.length)}</span></p>}
              <div className="divide-y">
                {[['精确率',selected.metrics.precision],['召回率',selected.metrics.recall],['行为复现率',selected.metrics.sim_repro_rate]].map(([label,value])=><div key={String(label)} className="flex items-center justify-between py-3 first:pt-0 last:pb-0"><span className="text-sm text-muted-foreground">{label}</span><strong className="font-mono text-xl">{selected.metrics.available?metricRate(value as number | undefined):'—'}</strong></div>)}
              </div>
              {selected.metrics.publication && <details key={selected.release} className="text-xs leading-5 text-muted-foreground">
                <summary className="cursor-pointer hover:text-foreground">统计口径</summary>
                <div className="mt-2 space-y-1">
                  <p>按原评测快照统计有效样本，异常保留明细但不计入指标分母。</p>
                  {selected.metrics.publication.automatic && <p>有效覆盖率 {metricRate(selected.metrics.publication.coverage)}，发布阈值 {metricRate(selected.metrics.publication.minimum_coverage)}。</p>}
                  <p>以主 Job {selected.metrics.publication.primary_job_id} 为准，复跑结果不合并。</p>
                  <p>上方路测样本为最新同步范围，可能与评测快照不同。</p>
                </div>
              </details>}
              {selected.metrics.archived && !selected.metrics.quality_gate_passed && <p className="text-xs leading-5 text-amber-700 dark:text-amber-400">保留历史归档指标；质量门禁未通过，请结合异常任务查看。</p>}
              {!selected.metrics.available && <p className="text-xs leading-5 text-muted-foreground">{activeJob?'任务运行中；结束后核验有效覆盖率，达标自动发布。':selected.evaluation?(selected.evaluation.publication_decision?.reason || '场景结果已导入，正在核对发布条件。'):jobs.length?'任务结束与质量验收分别核对，通过验收后展示结果。':'尚无完整仿真结果。'}</p>}
            </CardContent>
          </Card>
          {selected.evaluation && !selected.evaluation.publication && !selected.evaluation.quality_gate_passed && <Card><CardHeader><CardTitle>有效样本参考</CardTitle><Badge variant="warning">尚未达到发布条件</Badge></CardHeader><CardContent className="space-y-3"><p className="text-xs leading-5 text-muted-foreground">仅统计主结果中通过场景质量检查的 {number(selected.evaluation.subset_summary.eligible)} 个样本，覆盖率 {metricRate(selected.evaluation.coverage)}；失败样本未计入准召分母。</p>{[['精确率',selected.evaluation.subset_summary.precision],['召回率',selected.evaluation.subset_summary.recall],['行为复现率',selected.evaluation.subset_summary.sim_repro_rate]].map(([label,value])=><div key={String(label)} className="flex justify-between text-sm"><span>{label}</span><strong className="font-mono">{metricRate(value as number | null)}</strong></div>)}<p className="text-xs leading-5 text-amber-700">{selected.evaluation.publication_decision?.reason || t('simFlow.thresholdNote')}</p></CardContent></Card>}
          {selected.is_current && <Card><CardHeader><CardTitle>仿真操作</CardTitle></CardHeader><CardContent className="space-y-3"><div className="flex flex-wrap items-center justify-between gap-2 text-sm"><span>{t('simFlow.mode')}</span><Select label={t('simFlow.mode')} value={data.mode} disabled={writeDisabled} options={[{value:'manual',label:t('simFlow.manualMode')},{value:'auto',label:t('simFlow.autoMode'),disabled:!data.driver_ready || !data.scheduler_enabled}]} onChange={mode=>{void act(async()=>{await request('/mode','PUT',{mode});setNotice(t('simFlow.modeSaved',{mode:t(mode==='auto'?'simFlow.autoMode':'simFlow.manualMode')}));});}}/></div><Button className="w-full" disabled={writeDisabled || activeJob || data.current_status!=='ready'} onClick={()=>void act(async()=>setPlan(await request('/plan')))}>{activeJob?'已有任务运行中':'预览仿真计划'}</Button><p className="text-xs leading-5 text-muted-foreground">自动模式会补齐场景并提交仿真；Issue 同步每 15 分钟独立运行。</p>{notice && <p role="status" className="text-sm text-primary">{notice}</p>}</CardContent></Card>}
        </div>
      </div>
      {plan && selected.is_current && <Card><CardHeader><CardTitle>待提交计划</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><p title={plan.release}>{releaseName(plan.release)} · Binary {plan.binary_id} · {number(plan.scenarios.length)} 个场景</p><p className="text-xs text-muted-foreground">完整周期，prod_gen4，并发 {number(plan.simulation.max_concurrency)}，优先级 {plan.simulation.priority || 'NORMAL'}，禁用缓存，启用 DPE；沿用历史基线参数。</p><div className="flex flex-wrap gap-2"><Button disabled={writeDisabled || activeJob} onClick={()=>void act(async()=>{const result=await request<{status:string}>('/submit','POST',{fingerprint:plan.fingerprint});setNotice(stateNames[result.status]||result.status);setPlan(null);})}>提交此计划</Button><input aria-label="已有 Job ID" placeholder="关联已有 Job ID" className="rounded border bg-background p-2" value={existingJob} onChange={event=>setExistingJob(event.target.value)}/><Button variant="outline" disabled={writeDisabled || !/^\d+$/.test(existingJob)} onClick={()=>void act(async()=>{await request('/attach','POST',{fingerprint:plan.fingerprint,job_id:Number(existingJob)});setPlan(null);setNotice('Job 已关联，正在核验');})}>关联并核验</Button></div></CardContent></Card>}
      <details className="rounded-lg border bg-card/60 p-4"><summary className="cursor-pointer text-sm font-medium">版本与运行配置</summary><p className="mt-3 break-all text-xs text-muted-foreground">版本标识：{selected.release}</p><div className="mt-4 grid gap-4 text-sm sm:grid-cols-3"><div><p className="text-xs text-muted-foreground">目标构建 / Binary</p><p className="mt-1 break-all">{selected.period?.target_road_version || selected.release}</p><p className="font-mono text-xs text-muted-foreground">{selected.binary_id || '—'}</p></div><div><p className="text-xs text-muted-foreground">Issue 最近同步 / 归档</p><p className="mt-1">{localTime(selected.synced_at)}</p></div><div><p className="text-xs text-muted-foreground">数据口径</p><p className="mt-1">{selected.kind==='archived'?'原版本归档评测':selected.period?.status==='running'?'周期采集中':'同版本完整周期评测'}</p></div></div>{selected.period?.evidence && <p className="mt-4 border-t pt-3 text-xs leading-5 text-muted-foreground">周期依据：{selected.period.evidence}</p>}</details>
      <div ref={parameters} id="simulation-parameters-entry" className="scroll-mt-6 min-w-0">
        {showParameters ? <Suspense fallback={<Card role="status" className="p-5 text-sm text-muted-foreground">{t('loading')}</Card>}><SimulationParameters key={selected.release} release={selected.release} binaryId={selected.binary_id} scenarioId={new URLSearchParams(window.location.search).get('scenario') || undefined}/></Suspense> : <Card className="p-4"><Button variant="ghost" className="min-h-11" onClick={() => setShowParameters(true)}><SlidersHorizontal className="h-4 w-4"/>{t('simFlow.parameters')}</Button></Card>}
      </div>
    </>}
  </div>;
}
