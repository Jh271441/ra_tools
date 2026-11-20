import { useEffect, useId, useRef, useState } from 'react';
import { Check, ChevronDown, Copy, Download, ExternalLink } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Select } from './ui/select';
import { ANIMATION_CONFIG, BASELINE_JOB_URL, buildSimulationParameters, ORION_LAUNCH_URL, SIM_FLAGS } from '../lib/simulationParameters';

function CopyBlock({ title, value, defaultOpen = true }: { title: string; value: string; defaultOpen?: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();
  const [status, setStatus] = useState('');
  const field = useRef<HTMLTextAreaElement>(null);
  useEffect(() => setStatus(''), [value]);
  async function copy() {
    try { await navigator.clipboard.writeText(value); setStatus('copied'); }
    catch { field.current?.focus(); field.current?.select(); setStatus('manualCopy'); }
  }
  return <section className="min-w-0 border-t py-3">
    <div className="flex items-center justify-between gap-2">
      <button type="button" className="flex min-h-11 min-w-0 items-center gap-2 text-left text-sm font-medium hover:text-primary" aria-expanded={open} aria-controls={contentId} onClick={() => setOpen(!open)}><ChevronDown className={`h-4 w-4 shrink-0 transition-transform ${open ? '' : '-rotate-90'}`}/>{title}</button>
      <Button variant="ghost" className="min-h-11" disabled={!value} onClick={() => { setStatus(''); void copy(); }} aria-label={t('simParameters.copyTitle', { title })}>{status === 'copied' ? <Check className="h-4 w-4"/> : <Copy className="h-4 w-4"/>}{t(`simParameters.${status === 'copied' ? 'copied' : 'copy'}`)}</Button>
    </div>
    <div id={contentId} hidden={!open} className="mt-2">
      <textarea ref={field} aria-label={title} readOnly spellCheck={false} value={value} className="h-72 w-full resize-y rounded-md border-0 bg-muted/40 p-3 font-mono text-xs leading-6 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"/>
      {status === 'manualCopy' && <p role="status" className="text-xs text-muted-foreground">{t('simParameters.manualCopy')}</p>}
    </div>
  </section>;
}

export function SimulationParameters({ binaryId, release, scenarioId }: { binaryId: number | null; release: string; scenarioId?: string }) {
  const { t } = useTranslation();
  const text = (key: string) => t(`simParameters.${key}`);
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
  const tabs = [['job', 'Orion Job'], ['plan', 'Sim Plan'], ['reference', text('reference')]] as const;
  const inputStyle = 'min-h-11 min-w-0 rounded-md border bg-background px-3 text-sm text-foreground';
  return <Card id="simulation-parameters" className="min-w-0 scroll-mt-6 overflow-hidden">
    <CardHeader><div className="flex flex-wrap items-start justify-between gap-3"><CardTitle><button type="button" className="flex min-h-11 items-center gap-2 text-left" aria-expanded={expanded} aria-controls={`${id}-content`} onClick={() => setExpanded(!expanded)}><ChevronDown className={`h-4 w-4 transition-transform ${expanded ? '' : '-rotate-90'}`}/>{text('title')}</button></CardTitle><a className="inline-flex min-h-11 items-center gap-1 text-sm text-primary hover:underline" href={ORION_LAUNCH_URL} target="_blank" rel="noreferrer">{text('openOrion')}<ExternalLink className="h-3.5 w-3.5"/></a></div></CardHeader>
    <CardContent id={`${id}-content`} hidden={!expanded} className="min-w-0 space-y-5">
      <section className="space-y-3" aria-label={text('settings')}>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <label className="grid min-w-0 gap-1.5 text-xs text-muted-foreground">Binary ID<input aria-label={text('binary')} inputMode="numeric" className={inputStyle} placeholder={text('binaryPlaceholder')} value={binary} onChange={event => setBinary(event.target.value)}/></label>
          <div className="grid min-w-0 gap-1.5 text-xs text-muted-foreground"><span>{text('sourceKind')}</span><Select label={text('sourceKind')} value={sourceKind} options={[{value:'ids',label:'Scenario ID'},{value:'label',label:'Scenario label'}]} onChange={value => { setSourceKind(value as 'ids' | 'label'); setSource(''); }}/></div>
          <label className="grid min-w-0 gap-1.5 text-xs text-muted-foreground sm:col-span-2">{text(sourceKind === 'ids' ? 'ids' : 'label')}<input aria-label={text('source')} className={inputStyle} placeholder={text(sourceKind === 'ids' ? 'idsPlaceholder' : 'labelPlaceholder')} value={source} onChange={event => setSource(event.target.value)}/></label>
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
          <label className="flex flex-wrap items-center gap-2">{text('concurrency')}<input aria-label={text('concurrency')} type="number" min="1" max="3000" className={`${inputStyle} w-24`} value={concurrency} onChange={event => setConcurrency(event.target.value)}/></label>
          <label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={animation} onChange={event => setAnimation(event.target.checked)}/>{text('animation')}</label>
        </div>
        <p className="break-words text-xs text-muted-foreground">PLANNING · prod_gen4 · {text('priority')}</p>
        {result.errors.length > 0 && <p role="status" className="text-xs text-muted-foreground">{result.errors.map(text).join(' · ')}</p>}
      </section>
      <section className="space-y-3">
        <div role="tablist" aria-label={text('format')} className="flex flex-wrap gap-1 rounded-lg bg-muted p-1">{tabs.map(([key, label], index) => <button key={key} id={`${id}-${key}`} role="tab" aria-selected={tab === key} aria-controls={`${id}-panel`} tabIndex={tab === key ? 0 : -1} onClick={() => setTab(key)} onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length; setTab(tabs[next][0]); document.getElementById(`${id}-${tabs[next][0]}`)?.focus(); } }} className={`min-h-11 rounded-md px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${tab === key ? 'bg-card font-medium text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}>{label}</button>)}</div>
        <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-${tab}`} className="min-w-0 space-y-3">
          {tab === 'job' ? <>
            <div className="flex flex-wrap items-center justify-between gap-3"><div className="grid min-w-0 gap-1.5 text-sm"><span>{text('importMode')}</span><Select label={text('importMode')} value={importMode} options={[{value:'single',label:text('single')},{value:'batch',label:text('batch')}]} onChange={value => setImportMode(value as 'single' | 'batch')}/></div>
            <Button variant="outline" className="min-h-11" disabled={!importJson} onClick={downloadJson}><Download className="h-4 w-4"/>{text(result.errors.length ? 'downloadTemplate' : 'downloadJson')}</Button></div>
            <CopyBlock key="json" title="Orion Job JSON" value={importJson}/>
            <CopyBlock key="cli" title={text('cli')} value={result.jobArgsPreview} defaultOpen={false}/>
          </> : tab === 'plan' ? <>
            <p className="text-sm leading-6">{text('planHint')}</p>
            <CopyBlock key="plan" title={text('planArgs')} value={result.simPlanArgs}/>
          </> : <section className="space-y-4 text-sm">
            <p className="break-words text-xs text-muted-foreground">{release} · <a className="text-primary hover:underline" href={BASELINE_JOB_URL} target="_blank" rel="noreferrer">{text('templateSource')} 47739079</a></p>
            <p className="text-xs leading-6 text-muted-foreground">{text('policy')}</p>
            <div className="divide-y">{SIM_FLAGS.map(([flag, detail]) => <div key={flag} className="py-3"><code className="block break-all text-xs">{flag}</code><p className="mt-1 text-xs text-muted-foreground">{text(detail)}</p></div>)}</div>
            <p className="text-xs text-muted-foreground">{text('animationLayout')}: <code className="break-all">{ANIMATION_CONFIG}</code></p>
          </section>}
        </div>
      </section>
      <details className="border-t pt-3 text-xs text-muted-foreground"><summary className="min-h-11 cursor-pointer py-3">{text('instructions')}</summary><p className="leading-6">{text('instructionsText')}</p></details>
    </CardContent>
  </Card>;
}
