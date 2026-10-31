import { memo, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Handle, MarkerType, Position, ReactFlow, type Node, type NodeProps } from '@xyflow/react';
import { flowEdgeTypes } from './FlowEdge';
import { RefreshCw, Clock3, ScanLine, Calculator, AlertCircle, Check, LoaderCircle } from 'lucide-react';

export interface LabelCycleState {
  enabled: boolean;
  status: 'waiting' | 'checking' | 'idle' | 'queued' | 'paused' | 'updated' | 'needs_simulation' | 'blocked' | 'source_error';
  reason?: string | null;
  checked_at?: string;
  next_check_at?: string;
  next_process_at?: string;
  applied_at?: string;
  pending_count?: number;
  change_count?: number;
  valid_issue_count?: number;
  issue_ids?: string[];
  check_seconds?: number;
  merge_seconds?: number;
}


type Step = 'sync' | 'diff' | 'apply';
type LoopData = Record<string, unknown> & { step: Step; compact: boolean; status: string; value: string; timeLabel: string; time?: string; active: boolean; warning: boolean; complete: boolean; incoming: Position; outgoing: Position };
const icons = {sync: RefreshCw, diff: ScanLine, apply: Calculator};
export const LoopNode = memo(function LoopNode({data}: NodeProps<Node<LoopData>>) {
  const {t,i18n} = useTranslation();
  const Icon = icons[data.step];
  const StatusIcon = data.warning ? AlertCircle : data.active ? LoaderCircle : data.complete ? Check : Clock3;
  const validTime = data.time && Number.isFinite(Date.parse(data.time));
  const time = validTime ? new Date(data.time!) : null;
  return <>
    <Handle id="in" type="target" position={data.incoming} isConnectable={false}/>{data.step === 'sync' && <Handle id="branch-in" type="target" position={Position.Top} isConnectable={false}/>}
    <div className={`sim-label-node${data.compact ? ' is-compact' : ''}${data.active ? ' is-active' : ''}${data.warning ? ' is-warning' : ''}`} role="group" aria-label={t(`labelLoop.${data.step}`)}>
      <span className="sim-label-node-title"><Icon size={16} aria-hidden="true"/>{t(`labelLoop.${data.step}`)}</span>
      <span className="sim-label-node-state"><StatusIcon size={14} aria-hidden="true"/>{data.status}</span>
      <span className="sim-label-node-value">{data.value}</span>
      <span className="sim-label-node-time">{data.timeLabel}<time dateTime={validTime?data.time:undefined} title={time?.toLocaleString(i18n.language==='zh'?'zh-CN':'en-GB',{timeZone:'Asia/Shanghai',hour12:false})}>{time?.toLocaleString(i18n.language==='zh'?'zh-CN':'en-GB',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) || '—'}</time></span>
    </div>
    <Handle id="out" type="source" position={data.outgoing} isConnectable={false}/>
  </>;
});
const nodeTypes = {labelStep: LoopNode};

export function useLabelGraph(state: LabelCycleState | undefined, stale: boolean, width: number, compact: boolean) {
  const {t,i18n} = useTranslation();
  const status = !state?.enabled ? 'disabled' : stale ? 'source_error' : state.status;
  const running = status === 'checking';
  const scheduled = ['queued','idle','updated'].includes(status);
  const stopped = ['disabled','waiting','paused','source_error'].includes(status);
  const warning = ['source_error','blocked','needs_simulation'].includes(status);
  const count = (value?:number)=>value == null ? '—' : value.toLocaleString(i18n.language === 'zh'?'zh-CN':'en-US');
  const nodeWidth = Math.max(160, compact ? width-56 : (width-88)/3);
  const steps: Step[] = ['sync','diff','apply'];
  const statuses = [
    t(`labelLoop.${running ? 'checking' : stopped ? status : 'synced'}`),
    t(`labelLoop.${running || stopped || !state?.checked_at ? 'pending' : state?.pending_count ? 'foundChanges' : 'noChanges'}`),
    t(`labelLoop.${status==='idle' && state?.applied_at && !state?.pending_count ? 'updated' : ['queued','updated','blocked','needs_simulation','paused'].includes(status) ? status : 'pending'}`),
  ];
  const values = [t('labelLoop.intervalHours',{count:(state?.check_seconds || 3600)/3600}),
    t('labelLoop.changeTotal',{formattedCount:count(state?.pending_count)}),
    status==='updated' ? t('labelLoop.validTotal',{formattedCount:count(state?.valid_issue_count)}) : t('labelLoop.mergeHours',{count:(state?.merge_seconds || 21600)/3600})];
  const times = [state?.checked_at,state?.next_check_at,state?.pending_count ? state.next_process_at : state?.applied_at];
  const timeKeys = ['checkedShort','nextShort',state?.pending_count?'mergeShort':'appliedShort'];
  const nodes: Node<LoopData>[] = steps.map((step,index)=>({
    id:`label-${step}`,type:'labelStep',position:{x:compact?36:16+index*(nodeWidth+28),y:12+(compact?index*160:0)},
    style:{width:nodeWidth},height:compact?132:114,draggable:false,focusable:false,selectable:false,
    data:{step,compact,status:statuses[index],value:values[index],time:times[index],timeLabel:t(`labelLoop.${timeKeys[index]}`),active:running && index===0,
      complete:(index===0 && !stopped && !running)||(index===1 && !!state?.checked_at && !running && !stopped)||(index===2 && (status==='updated' || status==='idle' && !!state?.applied_at && !state?.pending_count)),
      warning:warning && index===(status==='source_error'?0:2),
      incoming:compact ? index===0?Position.Left:Position.Top : index===0?Position.Bottom:Position.Left,
      outgoing:compact ? index===2?Position.Left:Position.Bottom : index===2?Position.Bottom:Position.Right},
  }));
  const edges = steps.map((step,index)=>({id:`label-${step}-next`,source:`label-${step}`,sourceHandle:'out',target:`label-${steps[(index+1)%3]}`,targetHandle:'in',type:'flow',data:{scheduled},animated:running && (index===0 || index===2),
    style:{stroke:running && index!==1 ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground))',strokeWidth:1.3,strokeDasharray:index===2?'4 5':undefined},markerEnd:{type:MarkerType.ArrowClosed,color:'hsl(var(--muted-foreground))'},pathOptions:{offset:22}}));
  return {nodes,edges,status,warning,running,scheduled};
}

export default function CollectionLoop({state, stale}: {state?:LabelCycleState; stale:boolean}) {
  const {t,i18n} = useTranslation();
  const container = useRef<HTMLDivElement>(null);
  const [width,setWidth] = useState(0);
  useEffect(()=>{
    const observer = new ResizeObserver(entries=>setWidth(Math.floor(entries[0].contentRect.width)));
    if(container.current) observer.observe(container.current);
    return ()=>observer.disconnect();
  },[]);
  const {nodes,edges,status,warning} = useLabelGraph(state,stale,width,width<620);
  const compact = width < 620;
  return <section className="sim-label-loop" aria-label={t('labelLoop.title')}>
    <div className="sim-label-heading"><h4><RefreshCw size={16} aria-hidden="true"/>{t('labelLoop.title')}</h4><span className={warning?'text-destructive':'text-muted-foreground'} role="status">{t(`labelLoop.${status}`)}</span><span className="sim-label-timezone">{t('labelLoop.timezone')}</span></div>
    <div ref={container} className="sim-label-canvas" style={{height:compact?492:176}}>
      {width > 0 && <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={flowEdgeTypes} viewport={{x:0,y:0,zoom:1}} minZoom={1} maxZoom={1} nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} edgesFocusable={false} panOnDrag={false} zoomOnScroll={false} zoomOnPinch={false} zoomOnDoubleClick={false} preventScrolling={false} deleteKeyCode={null}/>}
    </div>
  </section>;
}
