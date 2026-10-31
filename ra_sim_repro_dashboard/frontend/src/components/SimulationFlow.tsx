import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Background, Handle, MarkerType, Panel, Position, ReactFlow, ReactFlowProvider, useReactFlow, type Node, type NodeProps } from '@xyflow/react';
import { Activity, Check, ChevronDown, CircleHelp, Clock3, Database, GitBranch, Maximize, Minus, Plus, ScanLine, ShieldCheck, Upload, X, AlertTriangle } from 'lucide-react';
import { flowEdgeTypes } from './FlowEdge';
import CollectionLoop, {LoopNode, useLabelGraph} from './CollectionLoop';
import { request, type BoardData } from './ReleaseWorkflow';
import BackfillLoop, {BackfillNode, useBackfillGraph} from './BackfillLoop';
import { collectionProgress, executionSeconds, issueAge, simulationFlow, stageMotion, type FlowStage, type StageId } from '../lib/simulationFlow';
import { Card, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import '@xyflow/react/dist/style.css';
import './simulation-flow.css';

type StageData = Record<string, unknown> & { stage: FlowStage; selected: boolean; onSelect: (id: StageId) => void; graph?: boolean; hasBranch?: boolean; recoveryBranch?: boolean; recoveryReturn?: boolean };
const icons = { collect: Database, prepare: ScanLine, execute: Activity, verify: ShieldCheck, publish: Upload };
const countKeys = { collect: 'issues', prepare: 'scenarios', execute: 'simulationProgress', verify: 'valid', publish: 'publishedCount' };
const colors = { complete: '#10b981', active: '#3b82f6', warning: '#d99616', blocked: '#ef4444', waiting: '#94a3b8', unknown: '#94a3b8', archived: '#8b5cf6' };

function StageCard({ stage, selected, onSelect }: StageData) {
  const { t, i18n } = useTranslation();
  const Icon = icons[stage.id];
  const Status = stage.state === 'complete' ? Check : stage.state === 'active' ? Activity : ['warning','blocked'].includes(stage.state) ? AlertTriangle : stage.state === 'unknown' ? CircleHelp : Clock3;
  const n = (value: number) => value.toLocaleString(i18n.language === 'zh' ? 'zh-CN' : 'en-US');
  const execution = stage.id === 'execute';
  const pendingAnomalies = stage.anomalies?.filter(a => !a.resolved);
  const anomaly = pendingAnomalies?.[0];
  const anomalyLabel = anomaly ? `${t(`simFlow.anomaly_${anomaly.code}`)}${anomaly.count != null ? ` · ${n(anomaly.count)}` : ''}${(pendingAnomalies?.length || 0) > 1 ? ` +${pendingAnomalies!.length - 1}` : ''}` : null;
  const percent = stage.progress == null ? '—' : `${(stage.progress === 1 ? 100 : Math.min(99.9, stage.progress * 100)).toLocaleString(i18n.language === 'zh' ? 'zh-CN' : 'en-US', { maximumFractionDigits: 1 })}%`;
  return <button type="button" className={`nodrag nopan sim-flow-node${execution ? ' sim-flow-execution' : ''} sim-flow-${stage.state}${selected ? ' is-selected' : ''}`} aria-label={t('simFlow.openStage', { stage: t(`simFlow.${stage.id}`) })} aria-pressed={selected} aria-controls="sim-flow-detail" onClick={event => { event.stopPropagation(); onSelect(stage.id); }}>
    <span className="sim-flow-node-title"><Icon size={17} aria-hidden="true"/><strong>{t(`simFlow.${stage.id}`)}</strong></span>
    <span className="sim-flow-count-label">{t(`simFlow.${countKeys[stage.id]}`)}</span>
    <span className="sim-flow-count">{execution ? percent : stage.count == null ? '—' : n(stage.count)}{!execution && stage.total != null && <span> / {n(stage.total)}</span>}</span>
    {execution && <span className="sim-flow-processed">{stage.count != null && stage.total != null ? t('simFlow.processedCount', {done: n(stage.count), total: n(stage.total)}) : t('simFlow.pendingCount')}</span>}
    {stage.progress != null ? <span role="progressbar" aria-label={t('simFlow.progress', { stage: t(`simFlow.${stage.id}`) })} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Number((stage.progress * 100).toFixed(2))} className="sim-flow-track"><span style={{ width: `${stage.progress * 100}%` }}/></span> : <span className="sim-flow-track-spacer"/>}
    <span className="sim-flow-status"><Status size={13} aria-hidden="true"/>{anomalyLabel && ['warning','blocked','unknown'].includes(stage.state) ? anomalyLabel : stage.state === 'complete' && stage.resolvedLabelCount ? t('simFlow.labelsApplied', {formattedCount:n(stage.resolvedLabelCount)}) : t(stage.detail === 'preparedWithExceptions' ? 'simFlow.toleranceContinue' : stage.detail === 'scenesFailed' ? 'simFlow.sceneBlocked' : stage.detail === 'scenesTimeout' ? 'simFlow.sceneRetry' : stage.detail === 'scenesPreparing' ? 'simFlow.preparingScenes' : `simFlow.state_${stage.state}`)}{!execution && stage.progress != null && <span className="ml-auto">{(stage.progress * 100).toFixed(stage.progress < 1 && stage.progress > .99 ? 2 : 0)}%</span>}</span>
  </button>;
}
const StageNode = memo(function StageNode({ data }: NodeProps<Node<StageData>>) {
  return <><Handle id="main-in" type="target" position={Position.Left} isConnectable={false}/><StageCard {...data}/>{data.hasBranch && <Handle id="branch-out" type="source" position={Position.Bottom} isConnectable={false}/>}<Handle id="main-out" type="source" position={Position.Right} isConnectable={false}/>{data.recoveryBranch && <Handle id="recovery-out" type="source" position={Position.Bottom} isConnectable={false}/>} {data.recoveryReturn && <Handle id="recovery-in" type="target" position={Position.Bottom} isConnectable={false}/>}</>;
});
const nodeTypes = { stage: StageNode, backfillStep: BackfillNode, labelStep: LoopNode, labelCaption: ({data}: NodeProps) => <div className="sim-label-graph-caption">{String(data.label)}</div> };

function CollectionActivity({ lastIssue, active, paused, ready }: { lastIssue?: string | null; active: boolean; paused: boolean; ready: boolean }) {
  const { t, i18n } = useTranslation();
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const age = issueAge(lastIssue, now);
  const absolute = age == null ? undefined : new Date(lastIssue!).toLocaleString(i18n.language === 'zh' ? 'zh-CN' : 'en-GB', { timeZone: 'Asia/Shanghai', hour12: false });
  return <div className={`sim-collection-activity${active ? ' is-active' : ''}`}>
    <ol className="sim-collection-chain" aria-label={t('simFlow.collectionChain')}>
      <li><Database size={14} aria-hidden="true"/><span>{t('simFlow.issueSource')}</span></li>
      <li className="sim-collection-chain-current"><Activity size={14} aria-hidden="true"/><span>{t(paused ? 'simFlow.collectionPaused' : ready ? 'simFlow.collectionStableShort' : 'simFlow.collectingShort')}</span></li>
      <li><Clock3 size={14} aria-hidden="true"/><span>{t('simFlow.quietWindow')}</span></li>
    </ol>
    <div className="sim-collection-age"><span>{t('simFlow.lastIssueAgo')}</span><time dateTime={age == null ? undefined : lastIssue!} title={absolute ? `${t('simFlow.lastIssue')}: ${absolute}` : undefined}>{age == null ? t('simFlow.noData') : t(age.days ? 'simFlow.issueAgeDays' : 'simFlow.issueAgeTime', age)}</time></div>
  </div>;
}

function FlowControls() {
  const { t } = useTranslation();
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  return <Panel position="bottom-right" className="sim-flow-controls">
    <Button variant="outline" size="icon" aria-label={t('simFlow.zoomIn')} title={t('simFlow.zoomIn')} onClick={() => void zoomIn()}><Plus size={17}/></Button>
    <Button variant="outline" size="icon" aria-label={t('simFlow.zoomOut')} title={t('simFlow.zoomOut')} onClick={() => void zoomOut()}><Minus size={17}/></Button>
    <Button variant="outline" size="icon" aria-label={t('simFlow.fit')} title={t('simFlow.fit')} onClick={() => void fitView({padding: .08, maxZoom: 1})}><Maximize size={17}/></Button>
  </Panel>;
}

export default function SimulationFlow({ data, stale, onRefresh }: { data: BoardData; stale: boolean; onRefresh?: () => Promise<unknown> }) {
  const { t, i18n } = useTranslation();
  const model = useMemo(() => simulationFlow(data, stale), [data, stale]);
  const collection = collectionProgress(data, stale);
  const remainingStages = model.stages;
  const hasLabelLoop = Boolean(data.selected.label_cycle?.enabled);
  const hasBackfill = Boolean(data.selected.backfill?.enabled);
  const [resuming,setResuming] = useState(false);
  const [resumeError,setResumeError] = useState('');
  const resume = async () => {
    setResuming(true);setResumeError('');
    try { await request('/resume','POST',{release:data.selected.release,fingerprint:data.selected.resume?.fingerprint || null}); await onRefresh?.(); }
    catch(err) {setResumeError(err instanceof Error?err.message:'request_failed');}
    finally {setResuming(false);}
  };
  const [selected, setSelected] = useState<StageId | null>(null);
  const section = useRef<HTMLDivElement>(null);
  const detail = useRef<HTMLDivElement>(null);
  const origin = useRef<HTMLElement | null>(null);
  const select = useCallback((id: StageId) => {
    origin.current = document.activeElement as HTMLElement;
    setSelected(id);
    // Only a deliberate selection scrolls. Polling and language changes keep the viewport.
    if ((section.current?.clientWidth || 0) < 760) requestAnimationFrame(() => detail.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
  }, []);
  const close = () => { setSelected(null); origin.current?.focus({ preventScroll: true }); };
  const stageNodes: Node<StageData>[] = useMemo(() => remainingStages.map((stage, index) => ({ id: stage.id, type: 'stage', position: { x: index * 240, y: 24 }, width: 196, height: 158, data: { stage, selected: stage.id === selected, onSelect: select, hasBranch: hasLabelLoop && stage.id === 'collect', recoveryBranch:hasBackfill && stage.id==='prepare', recoveryReturn:hasBackfill && stage.id==='verify' }, draggable: false, focusable: false, selectable: false })), [remainingStages, selected, select, hasLabelLoop, hasBackfill]);
  const stageEdges = useMemo(() => remainingStages.slice(1).map((stage, i) => ({ id: `${remainingStages[i].id}-${stage.id}`, source: remainingStages[i].id, sourceHandle:'main-out', target: stage.id, targetHandle:'main-in', type: 'flow', animated: stageMotion(remainingStages[i],stage,stale).animated, data:{scheduled:stageMotion(remainingStages[i],stage,stale).scheduled}, style: { stroke: colors[stage.state], strokeWidth: 1.8, strokeDasharray: ['unknown', 'waiting', 'archived'].includes(stage.state) ? '5 5' : undefined }, markerEnd: { type: MarkerType.ArrowClosed, color: colors[stage.state] } })), [remainingStages, stale]);
  const labelGraph = useLabelGraph(data.selected.label_cycle, stale, 676, false);
  const labelNodes: Node[] = hasLabelLoop ? [...stageNodes, ...labelGraph.nodes.map((node,index)=>({...node,position:{x:index*240,y:hasBackfill?466:258}})), {id:'label-caption',type:'labelCaption',position:{x:240,y:hasBackfill?432:220},data:{label:`${t('labelLoop.title')} · ${t(`labelLoop.${labelGraph.status}`)}`},focusable:false,selectable:false}] : stageNodes;
  const labelEdges = hasLabelLoop ? [...stageEdges,...labelGraph.edges,{id:'collect-label-sync',source:'collect',sourceHandle:'branch-out',target:'label-sync',targetHandle:'branch-in',type:'flow',data:{scheduled:labelGraph.scheduled},animated:labelGraph.running,style:{stroke:labelGraph.running?'hsl(var(--primary))':'hsl(var(--muted-foreground))',strokeWidth:1.3,strokeDasharray:'4 5'},markerEnd:{type:MarkerType.ArrowClosed,color:'hsl(var(--muted-foreground))'}}] : stageEdges;
  const recovery = useBackfillGraph(data.selected.backfill, stale, 258);
  const nodes:Node[] = hasBackfill ? [...labelNodes,...recovery.nodes,{id:'backfill-caption',type:'labelCaption',position:{x:240,y:222},data:{label:`${t('backfill.title')} · ${t(`backfill.${recovery.status}`)}`},focusable:false,selectable:false}] : labelNodes;
  const connector = (id:string,source:string,sourceHandle:string,target:string,targetHandle:string) => ({id,source,sourceHandle,target,targetHandle,type:'flow',animated:recovery.active,style:{stroke:'hsl(var(--muted-foreground))',strokeWidth:1.2,strokeDasharray:'4 5'},markerEnd:{type:MarkerType.ArrowClosed,color:'hsl(var(--muted-foreground))'}});
  const edges = hasBackfill ? [...labelEdges,...recovery.edges,connector('prepare-backfill','prepare','recovery-out','backfill-sync','branch-in'),connector('backfill-verify','backfill-merge','branch-out','verify','recovery-in')] : labelEdges;
  const stage = model.stages.find(v => v.id === selected);
  const s = data.selected;
  const n = (value?: number | null) => value == null ? '—' : value.toLocaleString(i18n.language === 'zh' ? 'zh-CN' : 'en-US');
  const rate = (value?: number | null) => value == null ? '—' : `${(value * 100).toFixed(2)}%`;
  const time = (value?: string | null) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString(i18n.language === 'zh' ? 'zh-CN' : 'en-GB', { timeZone: 'Asia/Shanghai', hour12: false }) : '—';
  const p = model.job?.progress;
  const seconds = executionSeconds(p?.started_at, p?.finished_at || p?.observed_at);
  const duration = seconds == null ? '—' : t('simFlow.duration', { hours: Math.floor(seconds / 3600), minutes: Math.floor(seconds % 3600 / 60), seconds: seconds % 60 });
  const facts = !stage ? [] : stage.id === 'collect' ? (collection ? [['issues', n(s.collection?.auto_count)], ['manualIssues', n(s.collection?.manual_count)], ['lastIssue', time(s.collection?.last_issue_at)], ['updated', time(s.collection?.last_success_at)], ['eligibleAt', collection.fresh ? time(s.collection?.eligible_at) : '—']] : [['synced', time(s.synced_at)], ['issues', n(s.issue_count)]]) : stage.id === 'prepare' ? [['binary', String(s.binary_id || '—')], ['scenarios', n(stage.count)]] : stage.id === 'execute' ? [['job', String(model.job?.job_id || '—')], ['executionCompleted', n(p?.completed)], ['executionRunning', n(p?.running)], ['executionQueued', n(p?.queued)], ['executionFailed', n(p?.failed)], ['executionCancelled', n(p?.cancelled)], [stale || model.job?.progress_error ? 'lastElapsed' : 'elapsed', duration], ['updated', time(p?.observed_at)]] : stage.id === 'verify' ? [['scenarioCoverage', rate(stage.progress)], ['issueCoverage', rate(model.publication?.issue_coverage)], ['conflicts', n(s.evaluation?.comparison.conflicts.length)], ['missing', n(stage.exceptionCount)]] : [['primaryJob', String(model.publication?.primary_job_id || s.metrics.job_id || '—')], ['threshold', rate(s.publication_policy?.minimum_coverage)]];
  return <Card className="sim-flow" role="region" aria-label={t('simFlow.title')}>
    <div ref={section}>
      <CardHeader><div className="flex flex-wrap items-center justify-between gap-2"><CardTitle className="flex items-center gap-2"><GitBranch size={18} className="text-primary"/>{t('simFlow.title')}</CardTitle><div className="flex flex-wrap items-center gap-2"><span className="text-xs text-muted-foreground">{t('simFlow.phoneHint')}</span>{data.selected.resume?.enabled && <Button variant="outline" className="min-h-11" disabled={stale || resuming || data.mode!=='auto' || ['requested','running'].includes(data.selected.resume.status || '')} onClick={()=>void resume()}>{t(resuming || ['requested','running'].includes(data.selected.resume.status || '')?'resume.running':'resume.action')}</Button>}</div></div></CardHeader>
      {s.quality_grade && <div className="sim-quality-summary"><span className={`sim-quality-grade is-${s.quality_grade.quality_level}`}>{t(`qualityGrade.${s.quality_grade.quality_level}`)}</span><span>{t(`qualityGrade.${s.quality_grade.basis}`)} {rate(s.quality_grade.issue_coverage)}</span><span>{t('qualityGrade.exceptions',{count:s.quality_grade.abnormal_issue_count})}</span></div>}
      {resumeError && <p role="alert" className="mx-5 mb-3 break-words text-sm text-destructive">{t(`resume.error_${resumeError}`,{defaultValue:t('resume.failed')})}</p>}
      {data.selected.resume?.status==='blocked' && <p role="status" className="mx-5 mb-3 break-words text-sm text-amber-700">{t(`resume.error_${data.selected.resume.reason}`,{defaultValue:t('resume.failed')})}</p>}
      {stale && <p role="status" className="mx-5 mb-3 text-sm text-amber-700 dark:text-amber-400">{t('simFlow.stale')}</p>}
      <div className={`sim-flow-desktop${hasLabelLoop?' has-label-branch':''}${hasBackfill?' has-backfill-branch':''}`}><ReactFlowProvider><ReactFlow onNodeClick={(_, node) => {if(node.type==='stage')select(node.id as StageId);}} nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={flowEdgeTypes} fitView fitViewOptions={{padding: .08, maxZoom: 1}} minZoom={.5} maxZoom={1.6} nodesConnectable={false} nodesDraggable={false} elementsSelectable={false} edgesFocusable={false} zoomOnScroll={false} zoomOnDoubleClick={false} preventScrolling={false} deleteKeyCode={null}><Background gap={18} size={1}/><FlowControls/></ReactFlow></ReactFlowProvider></div>
      <ol className="sim-flow-mobile">{remainingStages.map((item, i) => <li key={item.id}><span className="sim-flow-step" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span><div className="sim-flow-mobile-stage"><StageCard stage={item} selected={item.id === selected} onSelect={select}/>{item.id==='collect' && hasLabelLoop && <div className="sim-label-attached"><CollectionLoop key={s.release} state={s.label_cycle} stale={stale}/></div>}{item.id==='prepare' && hasBackfill && <BackfillLoop state={s.backfill} stale={stale}/>}</div>{i < remainingStages.length - 1 && <ChevronDown className={`sim-flow-next${stageMotion(item,remainingStages[i+1],stale).animated ? ' is-active' : stageMotion(item,remainingStages[i+1],stale).scheduled ? ' is-scheduled' : ''}`} size={18} aria-hidden="true"/>}</li>)}</ol>
      <div className="sim-flow-legend">{(['complete','active','warning','blocked','waiting'] as const).map(state => <span key={state}><i style={{background: colors[state]}}/>{t(`simFlow.state_${state}`)}</span>)}</div>
      {model.retained && <p className="mx-5 mb-3 text-xs text-muted-foreground">{t('simFlow.retained', {job: model.publication?.primary_job_id})}</p>}
      {stage && <div ref={detail} id="sim-flow-detail" className="sim-flow-detail" role="region" aria-label={t('simFlow.details')} onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } }}>
        <div className="flex items-start justify-between gap-2"><div><h4 className="font-semibold">{t(`simFlow.${stage.id}`)} <span className="ml-2 text-xs font-normal text-muted-foreground">{t(`simFlow.state_${stage.state}`)}</span></h4></div><Button variant="ghost" size="icon" className="h-11 w-11" onClick={close} aria-label={t('simFlow.closeDetails')}><X size={17}/></Button></div>
        {stage.id === 'collect' && collection && !s.is_current && <CollectionActivity lastIssue={s.collection?.last_issue_at} active={collection.fresh && !collection.ready} paused={!collection.fresh} ready={collection.ready}/>}
        <dl className="sim-flow-facts">{facts.map(([key, value]) => <div key={key}><dt>{t(`simFlow.${key}`)}</dt><dd>{value}</dd></div>)}</dl>
        {['prepare','verify'].includes(stage.id) && s.quality_grade && <p className="mt-2 text-xs text-muted-foreground">{t(`qualityGrade.note_${s.quality_grade.quality_level}`)}</p>}
        {stage.id === 'prepare' && s.issue_tolerance && <p className="mt-2 text-sm break-words">{t('simFlow.toleranceSummary', {valid: n(s.issue_tolerance.valid_issue_count), total: n(s.issue_tolerance.issue_count), count: s.issue_tolerance.abnormal_issue_count, coverage: rate(s.issue_tolerance.issue_coverage)})}</p>}
        {!!stage.anomalies?.length && <section className="sim-flow-anomalies" aria-label={t(stage.resolvedLabelCount ? 'simFlow.changeHistory' : 'simFlow.anomalyDetails')}>
          <h5 className="text-sm font-medium">{t(stage.resolvedLabelCount ? 'simFlow.changeHistory' : 'simFlow.anomalyDetails')}</h5>
          {stage.anomalies.map((a,index)=><div className="sim-flow-anomaly" key={`${a.code}-${a.job_id || index}`}>
            <strong>{t(a.resolved ? 'simFlow.labelsAppliedTitle' : `simFlow.anomaly_${a.code}`)}{a.count != null && ` · ${n(a.count)}`}</strong>
            <p>{t(a.resolved ? 'simFlow.labelsAppliedNote' : `simFlow.anomalyNote_${a.code}`)}</p>{a.resolved_at && <time>{time(a.resolved_at)}</time>}
            <div className="sim-flow-anomaly-meta"><code>{a.code}</code>{a.job_id && <span>Job {a.job_id}</span>}{a.observed_at && <time>{time(a.observed_at)}</time>}</div>
            {!!a.items.length && <ul>{a.items.map((item,i)=><li key={i}>
              <span>{[item.issue_id,item.scenario_id].filter(Boolean).join(' · ')}</span>
              {item.field && <span> · <code>{item.field}</code>: {String(item.before ?? '—')} → {String(item.after ?? '—')}</span>}
              {item.reason && <span> · {item.reason}</span>}
            </li>)}</ul>}
            {a.count != null && a.count > a.items.length && a.items.length > 0 && <p>{t('simFlow.anomalyLimit',{shown:a.items.length,total:n(a.count)})}</p>}
          </div>)}
        </section>}
        <details className="sim-flow-more" key={stage.id}><summary>{t('simFlow.more')}</summary><p className="text-xs leading-5 text-muted-foreground">{t(`simFlow.${stage.detail}`)}</p>
        {stage.id === 'publish' && <p className="mt-3 text-xs leading-5 text-muted-foreground">{t('simFlow.thresholdNote')}</p>}
        {(['prepare','verify'].includes(stage.id) || (stage.id === 'collect' && !collection)) && <p className="mt-3 text-xs text-muted-foreground">{t('simFlow.noTiming')}</p>}
        </details>
      </div>}
    </div>
  </Card>;
}
