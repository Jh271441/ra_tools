import { useEffect, useId, useRef, useState } from 'react';
import { Check, ChevronDown, Copy, Download, ExternalLink } from 'lucide-react';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { ANIMATION_CONFIG, BASELINE_JOB_URL, buildSimulationParameters, ORION_LAUNCH_URL, SIM_FLAGS } from '../lib/simulationParameters';

function CopyBlock({ title, value, defaultOpen = true }: { title: string; value: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();
  const [status, setStatus] = useState('');
  const field = useRef<HTMLTextAreaElement>(null);
  useEffect(() => setStatus(''), [value]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setStatus('已复制');
    } catch {
      field.current?.focus();
      field.current?.select();
      setStatus('自动复制不可用，已选中文本，请按 ⌘C / Ctrl+C。');
    }
  }
  return <section className="min-w-0 border-t py-3">
    <div className="flex items-center justify-between gap-2">
      <button type="button" className="flex min-w-0 items-center gap-2 py-1 text-sm font-medium hover:text-primary" aria-expanded={open} aria-controls={contentId} onClick={() => setOpen(!open)}><ChevronDown className={`h-4 w-4 shrink-0 transition-transform ${open ? '' : '-rotate-90'}`}/>{title}</button>
      <Button variant="ghost" size="sm" disabled={!value} onClick={() => { setStatus(''); void copy(); }} aria-label={`复制${title}`}>{status === '已复制' ? <Check className="h-4 w-4"/> : <Copy className="h-4 w-4"/>}{status === '已复制' ? '已复制' : '复制'}</Button>
    </div>
    <div id={contentId} hidden={!open} className="mt-2">
      <textarea ref={field} aria-label={title} readOnly spellCheck={false} value={value} className="h-72 w-full resize-y rounded-md border-0 bg-muted/40 p-3 font-mono text-xs leading-6 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"/>
      {status && status !== '已复制' && <p role="status" className="text-xs text-muted-foreground">{status}</p>}
    </div>
  </section>;
}

export function SimulationParameters({ binaryId, release, scenarioId }: { binaryId: number | null; release: string; scenarioId?: string }) {
  const [expanded, setExpanded] = useState(true);
  const [binary, setBinary] = useState(binaryId ? String(binaryId) : '');
  const [sourceKind, setSourceKind] = useState<'ids' | 'label'>('ids');
  const [source, setSource] = useState(scenarioId || '');
  const [animation, setAnimation] = useState(false);
  const [concurrency, setConcurrency] = useState('3000');
  const [tab, setTab] = useState<'job' | 'plan' | 'reference'>('job');
  const [importMode, setImportMode] = useState<'single' | 'batch'>('single');
  const id = useId();
  const result = buildSimulationParameters({ binaryId: binary, sourceKind, source, animation, concurrency });
  const importJson = importMode === 'single' ? result.singleJobJsonPreview : result.jobJsonPreview;
  function downloadJson() {
    if (!importJson) return;
    const url = URL.createObjectURL(new Blob([importJson], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url; link.download = importMode === 'single' ? 'ra_sim_single_job.json' : 'ra_sim_batch_jobs.json';
    document.body.appendChild(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const tabs = [['job', 'Orion Job'], ['plan', 'Sim Plan'], ['reference', '参数说明']] as const;
  return <Card id="simulation-parameters" className="min-w-0 scroll-mt-6 overflow-hidden">
    <CardHeader><div className="flex flex-wrap items-start justify-between gap-3"><CardTitle><button type="button" className="flex items-center gap-2" aria-expanded={expanded} aria-controls={`${id}-content`} onClick={() => setExpanded(!expanded)}><ChevronDown className={`h-4 w-4 transition-transform ${expanded ? '' : '-rotate-90'}`}/>仿真参数</button></CardTitle><a className="inline-flex items-center gap-1 text-sm text-primary hover:underline" href={ORION_LAUNCH_URL} target="_blank" rel="noreferrer">打开 Orion<ExternalLink className="h-3.5 w-3.5"/></a></div></CardHeader>
    <CardContent id={`${id}-content`} hidden={!expanded} className="min-w-0 space-y-5">
      <section className="space-y-3" aria-label="任务设置">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <label className="grid gap-1.5 text-xs text-muted-foreground">Binary ID<input aria-label="参数 Binary ID" inputMode="numeric" className="h-9 min-w-0 rounded-md border bg-background px-3 text-sm text-foreground" placeholder="填写与路测版本对应的 Binary" value={binary} onChange={event => setBinary(event.target.value)}/></label>
          <label className="grid gap-1.5 text-xs text-muted-foreground">场景选择方式<select aria-label="场景选择方式" className="h-9 rounded-md border bg-background px-3 text-sm text-foreground" value={sourceKind} onChange={event => { setSourceKind(event.target.value as 'ids' | 'label'); setSource(''); }}><option value="ids">Scenario ID</option><option value="label">Scenario label</option></select></label>
          <label className="grid gap-1.5 text-xs text-muted-foreground sm:col-span-2">{sourceKind === 'ids' ? 'Scenario ID（支持多个）' : 'Scenario label（精确匹配）'}<input aria-label="参数场景来源" className="h-9 min-w-0 rounded-md border bg-background px-3 text-sm text-foreground" placeholder={sourceKind === 'ids' ? '例如 40064248:0 40064242:0' : '从 Issue 详情复制完整 Scenario label'} value={source} onChange={event => setSource(event.target.value)}/></label>
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
          <label className="flex items-center gap-2">并发上限<input aria-label="参数并发上限" type="number" min="1" max="3000" className="h-9 w-24 rounded-md border bg-background px-3" value={concurrency} onChange={event => setConcurrency(event.target.value)}/></label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={animation} onChange={event => setAnimation(event.target.checked)}/>生成 Ares 动画</label>
        </div>
        <p className="break-words text-xs text-muted-foreground">模块 <strong className="text-foreground">PLANNING</strong> · 集群 <strong className="text-foreground">prod_gen4</strong> · 优先级 <strong className="text-foreground">high</strong></p>
        {result.errors.length > 0 && <p role="status" className="text-xs text-muted-foreground">模板 · {result.errors.join('，')}</p>}
      </section>
      <section className="space-y-3">
        <div role="tablist" aria-label="仿真参数格式" className="flex flex-wrap gap-1 rounded-lg bg-muted p-1">{tabs.map(([key, label], index) => <button key={key} id={`${id}-${key}`} role="tab" aria-selected={tab === key} aria-controls={`${id}-panel`} tabIndex={tab === key ? 0 : -1} onClick={() => setTab(key)} onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length; setTab(tabs[next][0]); document.getElementById(`${id}-${tabs[next][0]}`)?.focus(); } }} className={`rounded-md px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${tab === key ? 'bg-card font-medium text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}>{label}</button>)}</div>
        <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${tab}`} className="min-w-0 space-y-3">
          {tab === 'job' ? <>
            <div className="flex flex-wrap items-center justify-between gap-3"><label className="flex items-center gap-3 text-sm">导入方式<select aria-label="Orion 导入入口" className="rounded-md border bg-background px-3 py-2" value={importMode} onChange={event => setImportMode(event.target.value as 'single' | 'batch')}><option value="single">从文件导入（单任务）</option><option value="batch">批量导入</option></select></label>
            <Button variant="outline" disabled={!importJson} onClick={downloadJson}><Download className="h-4 w-4"/>{result.errors.length ? '下载模板' : '下载 JSON'}</Button></div>
            <CopyBlock key="json" title="Orion Job JSON" value={importJson}/>
            <CopyBlock key="cli" title="CLI 参数" value={result.jobArgsPreview} defaultOpen={false}/>
          </> : tab === 'plan' ? <>
            <p className="text-sm leading-6">选择场景集及 Base / Feature Binary，将参数粘贴到“额外参数”。模块 <strong>PLANNING</strong> · 集群 <code>prod_gen4</code> · 优先级 <code>high</code> · 并发 {concurrency}。</p>
            <CopyBlock key="plan" title="Sim Plan 额外参数" value={result.simPlanArgs}/>
          </> : <section className="space-y-4 text-sm">
            <p className="text-xs text-muted-foreground">版本：{release} · 基线 <a className="text-primary hover:underline" href={BASELINE_JOB_URL} target="_blank" rel="noreferrer">Job 47739079</a> · high 优先级</p>
            <p className="text-xs text-muted-foreground">Job 层使用 --sim-extra-args；生成 task 后对应 --sim-exec-args。下表区分提交选项与模拟器内部参数。</p>
            <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr className="border-b"><th className="p-2">Job / Sim Plan 提交选项</th><th className="p-2">值与用途</th></tr></thead><tbody>{[
              ['--override-enabled-modules', 'PLANNING（task 中模块枚举为 6）；其他模块沿用输入回放。'],
              ['--use-trip-hdmap', '启用，使用 trip 对应的地图。'],
              ['--use-dpe', '1；task 中为 --enable-dpe，产出评测指标。'],
              ['--use-deepnet-cache', '1；task 中为 --enable-infer-cache，与 simulator cache 是两类缓存。'],
              ['--use-remote-serving', '1；对应启动页“打开远程推理”，沿用基线设置。'],
              ['--simulator-cache', 'disabled，重新执行仿真。'],
              ['--enable-log-event / --enable-stats', '启用事件与运行统计。'],
              ['--upload-output-bag / --upload-retention-days', 'always / 7，每次上传，保留 7 天。'],
              ['--routing-constraint-endpoint', 'default；使用默认约束入口。'],
              ['--animation-type', 'ares_studio；是否生成动画由下一个选项控制。'],
              ['--create-animation / --ares-animation-config', `布局 ${ANIMATION_CONFIG}；生成动画：${animation ? '开启' : '关闭'}。`],
              ['warmup bag', '沿用 scenario_test 模板的 warmup 下载行为；基线 task 中含 --download-warmup-bag。'],
            ].map(([name, detail]) => <tr key={name} className="border-b last:border-0"><td className="max-w-64 break-words p-2 align-top font-mono">{name}</td><td className="min-w-48 p-2 align-top leading-5">{detail}</td></tr>)}</tbody></table></div>
            <h5 className="font-medium">--sim-extra-args 内部参数</h5>
            <div className="divide-y">{SIM_FLAGS.map(([flag, detail]) => <div key={flag} className="py-3"><code className="block break-all text-xs">{flag}</code><p className="mt-1 text-xs text-muted-foreground">{detail}</p></div>)}</div>
          </section>}
        </div>
      </section>
      <details className="border-t pt-3 text-xs text-muted-foreground"><summary className="cursor-pointer">使用说明</summary><p className="mt-2">单任务 → 从文件导入；批量 → 批量导入。</p><p className="mt-1">提交前补齐场景，核对 Binary / Runtime，删除空白任务。</p></details>
    </CardContent>
  </Card>;
}
