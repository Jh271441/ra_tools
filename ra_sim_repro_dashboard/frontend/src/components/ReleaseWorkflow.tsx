import { useCallback, useEffect, useRef, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Activity, ArrowUpRight, ExternalLink, Layers3, RefreshCw } from 'lucide-react';

const base = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/api/dashboard/workflow`;
function metricRate(value?: number | null) { return value == null ? '—' : (value * 100).toFixed(1) + '%'; }

export function localTime(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '尚未同步';
}

export async function request<T>(path = '', method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(base + path, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败');
  return data;
}
export interface Workflow {
  current_version: string | null; reference_thursday: string; status: string; reason: string;
  current_period: { cycle_end: string; case_start: string; case_end_exclusive: string; evidence: string; target_road_version?: string; binary_id?: number } | null;
  acceptance_only: boolean; period_verified: boolean; retained_previous: boolean; population_complete: boolean; collected_through: string | null;
  source_metrics: { online_precision: number | null; online_recall: number | null; eligible: number; excluded: number } | null;
  metrics: { available: boolean; archived?: boolean; quality_gate_passed?: boolean; precision?: number; recall?: number; sim_repro_rate?: number; online_precision?: number; online_recall?: number; reason?: string; job_id?: number };
  mode: 'manual' | 'auto'; driver_ready: boolean; scheduler_enabled: boolean;
  synced_at: string | null; issue_count: number; scenario_count: number; manual_population_count: number;
  last_sync: { status?: string; reason?: string; mapping_error?: string; checked_at?: string };
  periods: { release: string; verified: boolean; basis: string | null; status: string; cycle_end: string }[];
  batches: { fingerprint: string; release: string; status: string; job_id: string | null; scenario_count: number }[];
}
export interface SourceIssue {
  issue_id: string; issue_topic: string; source_result: string | null; road_version: string; scenario_id: string; scenario_name: string; scenario_labels: string[];
  simulation_status: string; sim_triggered: boolean | null; reproduced: boolean | null; precision_label: string | null;
}
export const stateNames: Record<string, string> = { cancelled: '已取消', verifying: '结果核验中', excluded: '不参与评测', pending_gt: '待确认路测 GT', queued: '排队中', preflight_failed: '预检失败', cancelled_stale: '计划已过期', quality_failed: '结果未通过验收', pending_mapping: '待匹配场景', pending_simulation: '待仿真', submitting: '提交中', submission_uncertain: '提交待核对', running: '运行中', complete: '完成', failed: '失败' };

export function CurrentBusinessRelease() {
  const [data, setData] = useState<Workflow | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    const load = () => void request<Workflow>().then(value => { if (active) { setData(value); setError(''); } }).catch(() => { if (active) setError('当前业务版本查询失败'); });
    load(); const timer = window.setInterval(load, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  return <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm" role="status">
    <strong>当前业务版本：{data?.current_version || '待核实'}</strong>
    <span className="ml-4 text-muted-foreground">{data ? `周期结束日 ${data.current_period ? data.current_period.cycle_end : data.reference_thursday} · 每周一切换` : '正在查询'}</span>
    {(error || data?.reason) && <p className="mt-1 text-muted-foreground">{error || data?.reason}。下方已有结果按其原版本保留。</p>}
  </div>;
}

interface JobProgress {
  job_id: number; state: string; priority?: string; total: number; completed: number; running: number; queued: number;
  failed: number; cancelled: number; unknown: number; finished: number; percent: number;
  max_concurrency: number; started_at: string | null; finished_at: string | null; observed_at: string;
  failures: { task_id: string; scenario_id: string; status: string }[];
}
interface BoardJob {
  job_id: number | null; status: string; scenario_count: number | null; archived: boolean; url: string | null;
  progress: JobProgress | null; progress_error: string | null; error: string | null;
}
interface BoardData {
  versions: { release: string; is_current: boolean; cycle_status: string | null; has_job: boolean }[];
  selected: {
    release: string; is_current: boolean; kind: string; period: Workflow['current_period'] & { status?: string } | null;
    issue_count: number | null; scenario_count: number | null; source_metrics: Workflow['source_metrics'];
    metrics: Workflow['metrics']; binary_id: number | null; synced_at: string | null; population_complete: boolean; jobs: BoardJob[];
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
      <div className="flex items-center gap-3"><div className="rounded-lg bg-primary/10 p-2"><Activity className="h-5 w-5 text-primary"/></div><div><CardTitle>Job {job.job_id || '待分配'}</CardTitle><p className="mt-1 text-xs text-muted-foreground">{job.archived ? '历史归档任务' : '完整周期仿真'}</p></div></div>
      <div className="flex items-center gap-3">{p?.priority && <Badge variant={p.priority==='HIGH'?'warning':'outline'}>{p.priority==='HIGH'?'高优先级':p.priority==='NORMAL'?'普通优先级':p.priority}</Badge>}<Badge variant={active ? 'secondary' : p?.failed ? 'warning' : p?.state === 'COMPLETED' ? 'success' : 'outline'}>{active && <span className="h-1.5 w-1.5 rounded-full bg-blue-500"/>}{p ? jobStates[p.state] || p.state : stateNames[job.status] || job.status}</Badge>{job.url && <a href={job.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-medium text-primary">Orion 详情<ExternalLink className="h-3.5 w-3.5"/></a>}</div>
    </div></CardHeader>
    <CardContent className="space-y-5">
      {p ? <>
        <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs text-muted-foreground">任务进度 · 已结束</p><p className="mt-1 font-mono text-3xl font-semibold tabular-nums">{p.percent.toFixed(p.finished > 0 && p.finished < p.total && (p.percent < 1 || p.percent > 99) ? 2 : 1)}<span className="ml-1 text-lg text-muted-foreground">%</span></p></div><div className="text-right"><p className="font-mono text-sm tabular-nums">{number(p.finished)} / {number(p.total)} 场景</p><p className="mt-1 text-xs text-muted-foreground">成功 + 失败 + 取消</p></div></div>
        <div role="progressbar" aria-label={`Job ${job.job_id} 已结束进度`} aria-valuemin={0} aria-valuemax={p.total || 1} aria-valuenow={p.finished} className="flex h-3 overflow-hidden rounded-full bg-muted">{parts.filter(part => part.value > 0).map(part => <div key={part.key} className={part.color} title={`${part.label} ${part.value}`} style={{width:`${p.total ? part.value / p.total * 100 : 0}%`, minWidth:2}}/>)}</div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">{parts.filter(part => part.key !== 'unknown' || part.value > 0).map(part => <Stat key={part.key} title={part.label} value={number(part.value)} color={part.text}/>)}</div>
        <div className="flex flex-wrap justify-between gap-3 border-t pt-3 text-xs text-muted-foreground"><span>并发上限 <strong className="text-foreground">{number(p.max_concurrency)}</strong> · 已用时 {duration(p)}</span><span>更新于 {localTime(p.observed_at)}</span></div>
        {(job.progress_error || job.error) && <p role="alert" className="rounded border border-amber-400/40 bg-amber-50/50 p-3 text-sm text-amber-800 dark:bg-amber-950/20 dark:text-amber-300">{job.progress_error ? `进度更新失败，保留上次数据：${job.progress_error}` : `结果核验提示：${job.error}`}</p>}
        {p.failures.length > 0 && <details className="rounded border p-3 text-sm"><summary className="cursor-pointer font-medium">异常任务示例（{p.failures.length} 条）</summary><div className="mt-3 overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th className="p-2">Task</th><th className="p-2">Scenario</th><th className="p-2">状态</th></tr></thead><tbody>{p.failures.map(task=><tr key={task.task_id} className="border-t"><td className="p-2 font-mono">{task.task_id}</td><td className="p-2 font-mono">{task.scenario_id}</td><td className="p-2">{task.status === 'FAILED' ? '失败' : '已取消'}</td></tr>)}</tbody></table></div></details>}
      </> : <div className="rounded-lg bg-muted/40 p-6 text-center text-sm text-muted-foreground"><p>{job.progress_error ? `暂时无法获取进度：${job.progress_error}` : job.job_id ? '正在读取 Orion 任务进度…' : '正在准备任务，等待 Job 回执'}</p><p className="mt-2">计划 {number(job.scenario_count)} 个场景</p></div>}
    </CardContent>
  </Card>;
}

export function ReleaseWorkflow({ onOpenIssues }: { onOpenIssues: (release?: string) => void }) {
  const [data, setData] = useState<BoardData | null>(null);
  const [versionOptions, setVersionOptions] = useState<BoardData['versions']>([]);
  const [release, setRelease] = useState(() => new URLSearchParams(window.location.search).get('version') || '@current');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [existingJob, setExistingJob] = useState('');
  const [plan, setPlan] = useState<{fingerprint:string;release:string;binary_id:number;scenarios:unknown[];simulation:{max_concurrency:number;priority?:string}} | null>(null);
  const generation = useRef(0);
  const load = useCallback(async (force=false) => {
    const id=++generation.current;
    try {
      const result=await request<BoardData>(`/board?${new URLSearchParams({release,refresh:String(force)})}`);
      if(id===generation.current){setData(result);setVersionOptions(result.versions);setError('');}
      return result;
    }catch(err){if(id===generation.current)setError(err instanceof Error?err.message:String(err));return null;}
  },[release]);
  useEffect(()=>{
    let active=true;let timer:number;
    const poll=async()=>{const value=await load();if(active)timer=window.setTimeout(poll,value?.refreshing?3000:30000);};
    void poll();return()=>{active=false;generation.current++;window.clearTimeout(timer);};
  },[load,data?.refreshing]);
  const act=async(fn:()=>Promise<void>)=>{setBusy(true);setError('');setNotice('');try{await fn();await load();}catch(err){setError(err instanceof Error?err.message:String(err));}finally{setBusy(false);}};
  const selected=data?.selected;
  const jobs=selected?.jobs || [];
  const activeJob=jobs.some(job=>job.progress ? ['RUNNING','STARTING'].includes(job.progress.state) : ['queued','submitting','submission_uncertain','running','verifying'].includes(job.status));
  const source=selected?.source_metrics;
  function choose(value:string){generation.current++;setRelease(value);setData(null);setPlan(null);setNotice('');setExistingJob('');const url=new URL(window.location.href);if(value==='@current')url.searchParams.delete('version');else url.searchParams.set('version',value);window.history.replaceState(window.history.state,'',url.pathname+url.search);}
  return <div className="min-w-0 space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-semibold">仿真看板</h2><p className="mt-1 text-xs text-muted-foreground">按版本查看任务进度与评测结果 · 每 30 秒更新进度</p></div><div className="flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-2 text-sm">版本<select aria-label="仿真版本" className="max-w-full rounded-md border bg-card px-3 py-2" value={release} onChange={e=>choose(e.target.value)}><option value="@current">跟随当前版本</option>{versionOptions.map(version=><option key={version.release} value={version.release}>{version.release}{version.is_current?' · 当前':version.cycle_status==='running'?' · 路测收集中':''}</option>)}</select></label>
      <Button variant="outline" disabled={busy} onClick={()=>void act(async()=>{await load(true);})}><RefreshCw className="h-4 w-4"/>刷新进度</Button>
      <Button variant="outline" disabled={!selected || selected.period?.status==='running'} onClick={()=>onOpenIssues(selected?.is_current?undefined:selected?.release)}>Issue 明细<ArrowUpRight className="h-4 w-4"/></Button>
    </div></div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
    {!selected ? <Card><CardContent className="p-10 text-center text-sm text-muted-foreground">正在加载版本看板…</CardContent></Card> : <>
      <div className="flex flex-wrap items-center gap-3"><h3 className="font-semibold">{selected.release}</h3>{selected.is_current && <Badge variant="secondary">当前业务版本</Badge>}{selected.kind==='archived' && <Badge>历史归档</Badge>}{selected.period?.status==='running' && <Badge variant="warning">路测收集中</Badge>}<span className="text-xs text-muted-foreground">{selected.period?.cycle_end ? `${selected.period.case_start.slice(0,10)} — ${selected.period.cycle_end}` : selected.kind==='archived'?'已归档的版本评测':''}</span></div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Stat title="可评测样本" value={number(source?.eligible)} detail={source?.excluded != null?`口径排除 ${number(source.excluded)} 条`:undefined}/><Stat title="关联场景" value={number(selected.scenario_count)} detail={selected.issue_count != null?`自动触发 Issue ${number(selected.issue_count)} 条`:undefined}/><Stat title="线上精确率" value={metricRate(source?.online_precision)} color="text-blue-600 dark:text-blue-400"/><Stat title="线上召回率" value={metricRate(source?.online_recall)} color="text-orange-600 dark:text-orange-400"/></div>
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0 space-y-4">{jobs.length ? jobs.map((job,index)=><JobCard key={job.job_id || index} job={job}/>) : <Card><CardContent className="flex flex-col items-center gap-3 p-10 text-center"><Layers3 className="h-8 w-8 text-muted-foreground"/><h3 className="font-semibold">{selected.period?.status==='running'?'周期尚未结束':'该版本尚无仿真任务'}</h3><p className="text-sm text-muted-foreground">{selected.period?.status==='running'?'路测数据仍在采集中，周期确认结束后进入仿真流程。':'先预览完整计划，再提交仿真。'}</p></CardContent></Card>}</div>
        <div className="min-w-0 space-y-4">
          <Card><CardHeader><div className="flex items-center justify-between"><CardTitle>仿真评测结果</CardTitle><Badge variant={selected.metrics.archived && !selected.metrics.quality_gate_passed?'warning':selected.metrics.available?'success':'outline'}>{selected.metrics.archived?'归档指标':selected.metrics.available?'已通过验收':'待就绪'}</Badge></div></CardHeader><CardContent className="space-y-3">{[['精确率',selected.metrics.precision],['召回率',selected.metrics.recall],['行为复现率',selected.metrics.sim_repro_rate]].map(([label,value])=><div key={String(label)} className="flex items-center justify-between border-b pb-3 last:border-0"><span className="text-sm text-muted-foreground">{label}</span><strong className="font-mono text-xl">{selected.metrics.available?metricRate(value as number | undefined):'—'}</strong></div>)}{selected.metrics.archived && !selected.metrics.quality_gate_passed && <p className="text-xs leading-5 text-amber-700 dark:text-amber-400">保留历史归档指标；质量门禁未通过，请结合异常任务查看。</p>}{!selected.metrics.available && <p className="text-xs leading-5 text-muted-foreground">{activeJob?'任务运行中；完整结果通过质量核验后展示准召。':jobs.length?'任务结束与质量验收分别核对，通过验收后展示结果。':'尚无完整仿真结果。'}</p>}</CardContent></Card>
          {selected.is_current && <Card><CardHeader><CardTitle>仿真操作</CardTitle></CardHeader><CardContent className="space-y-3"><label className="flex items-center justify-between text-sm">仿真方式<select aria-label="仿真方式" className="rounded border bg-background px-3 py-2" value={data.mode} disabled={busy} onChange={event=>{const mode=event.target.value;void act(async()=>{await request('/mode','PUT',{mode});setNotice(`已保存${mode==='auto'?'自动':'手动'}模式`);});}}><option value="manual">手动</option><option value="auto" disabled={!data.driver_ready || !data.scheduler_enabled}>自动</option></select></label><Button className="w-full" disabled={busy || activeJob || data.current_status!=='ready'} onClick={()=>void act(async()=>setPlan(await request('/plan')))}>{activeJob?'已有任务运行中':'预览仿真计划'}</Button><p className="text-xs leading-5 text-muted-foreground">自动模式会补齐场景并提交仿真；Issue 同步每 15 分钟独立运行。</p>{notice && <p role="status" className="text-sm text-primary">{notice}</p>}</CardContent></Card>}
        </div>
      </div>
      {plan && selected.is_current && <Card><CardHeader><CardTitle>待提交计划</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><p>{plan.release} · Binary {plan.binary_id} · {number(plan.scenarios.length)} 个场景</p><p className="text-xs text-muted-foreground">完整周期，prod_gen4，并发 {number(plan.simulation.max_concurrency)}，优先级 {plan.simulation.priority || 'NORMAL'}，禁用缓存，启用 DPE；沿用历史基线参数。</p><div className="flex flex-wrap gap-2"><Button disabled={busy || activeJob} onClick={()=>void act(async()=>{const result=await request<{status:string}>('/submit','POST',{fingerprint:plan.fingerprint});setNotice(stateNames[result.status]||result.status);setPlan(null);})}>提交此计划</Button><input aria-label="已有 Job ID" placeholder="关联已有 Job ID" className="rounded border bg-background p-2" value={existingJob} onChange={event=>setExistingJob(event.target.value)}/><Button variant="outline" disabled={busy || !/^\d+$/.test(existingJob)} onClick={()=>void act(async()=>{await request('/attach','POST',{fingerprint:plan.fingerprint,job_id:Number(existingJob)});setPlan(null);setNotice('Job 已关联，正在核验');})}>关联并核验</Button></div></CardContent></Card>}
      <details className="rounded-lg border bg-card/60 p-4"><summary className="cursor-pointer text-sm font-medium">版本与运行配置</summary><div className="mt-4 grid gap-4 text-sm sm:grid-cols-3"><div><p className="text-xs text-muted-foreground">目标构建 / Binary</p><p className="mt-1 break-all">{selected.period?.target_road_version || selected.release}</p><p className="font-mono text-xs text-muted-foreground">{selected.binary_id || '—'}</p></div><div><p className="text-xs text-muted-foreground">Issue 最近同步 / 归档</p><p className="mt-1">{localTime(selected.synced_at)}</p></div><div><p className="text-xs text-muted-foreground">数据口径</p><p className="mt-1">{selected.kind==='archived'?'原版本归档评测':selected.period?.status==='running'?'周期采集中':'同版本完整周期评测'}</p></div></div>{selected.period?.evidence && <p className="mt-4 border-t pt-3 text-xs leading-5 text-muted-foreground">周期依据：{selected.period.evidence}</p>}</details>
    </>}
  </div>;
}
