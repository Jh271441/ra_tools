import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Handle, MarkerType, Position, type Node, type NodeProps } from '@xyflow/react';
import { RefreshCw, ScanLine, Activity, GitMerge, ArrowDown, CornerUpLeft } from 'lucide-react';

export interface BackfillState {
  enabled: boolean; status: string; reason?: string; checked_at?: string; next_check_at?: string;
  applied_at?: string; interval_seconds: number; pending_count?: number; recovered_count?: number;
  issue_count?: number; job_id?: number | null;
}
const steps = ['sync','prepare','simulate','merge'] as const;
type Step = typeof steps[number];
const icons = {sync:RefreshCw,prepare:ScanLine,simulate:Activity,merge:GitMerge};
type RecoveryData = Record<string, unknown> & {step:Step; active:boolean; value:string; warning:boolean};
export const BackfillNode = memo(function BackfillNode({data}:NodeProps<Node<RecoveryData>>) {
  const {t} = useTranslation(); const Icon = icons[data.step];
  return <><Handle id="in" type="target" position={Position.Left} isConnectable={false}/>
    {data.step==='sync' && <Handle id="branch-in" type="target" position={Position.Top} isConnectable={false}/>}
    <div className={`sim-backfill-node${data.active?' is-active':''}${data.warning?' is-warning':''}`}>
      <span><Icon size={15} aria-hidden="true"/>{t(`backfill.${data.step}`)}</span><strong>{data.value}</strong>
    </div><Handle id="out" type="source" position={Position.Right} isConnectable={false}/>
    {data.step==='merge' && <Handle id="branch-out" type="source" position={Position.Top} isConnectable={false}/>}
    <Handle id="loop" type={data.step==='sync'?'target':'source'} position={Position.Bottom} isConnectable={false}/></>;
});
export function useBackfillGraph(state?:BackfillState, stale=false, y=258) {
  const {t,i18n} = useTranslation();
  const status = stale?'stale':state?.status || 'waiting';
  const index = ['syncing','preparing','simulating','merging'].indexOf(status);
  const active = index>=0;
  const n=(value?:number)=>value==null?'—':value.toLocaleString(i18n.language==='zh'?'zh-CN':'en-US');
  const values = [t('backfill.interval',{count:(state?.interval_seconds||21600)/3600}),
    t('backfill.pending',{formattedCount:n(state?.pending_count)}),
    state?.job_id?`Job ${state.job_id}`:t(`backfill.${status==='waiting_bags'?'waiting_bags':'waiting'}`),
    state?.issue_count?`${n(state.recovered_count)} / ${n(state.issue_count)}`:'—'];
  const nodes:Node<RecoveryData>[] = steps.map((step,i)=>({id:`backfill-${step}`,type:'backfillStep',position:{x:240+i*240,y},
    style:{width:196},height:76,draggable:false,focusable:false,selectable:false,
    data:{step,active:index===i,value:values[i],warning:status==='blocked'&&i===1}}));
  const edge=(source:Step,target:Step,loop=false)=>({id:`backfill-${source}-${target}`,source:`backfill-${source}`,target:`backfill-${target}`,
    sourceHandle:loop?'loop':'out',targetHandle:loop?'loop':'in',type:'flow',animated:active,
    data:{scheduled:!active&&['waiting_bags','complete'].includes(status)},
    style:{stroke:active?'hsl(var(--primary))':'hsl(var(--muted-foreground))',strokeWidth:1.2,strokeDasharray:loop?'4 5':undefined},
    markerEnd:{type:MarkerType.ArrowClosed,color:'hsl(var(--muted-foreground))'}});
  return {nodes,edges:[edge('sync','prepare'),edge('prepare','simulate'),edge('simulate','merge'),edge('merge','sync',true)],status,active,index,values};
}
export default function BackfillLoop({state,stale}:{state?:BackfillState;stale:boolean}) {
  const {t,i18n}=useTranslation();const graph=useBackfillGraph(state,stale);
  return <section className="sim-backfill-mobile" aria-label={t('backfill.title')}>
    <header><GitMerge size={15}/><h4>{t('backfill.title')}</h4><span role="status">{t(`backfill.${graph.status}`)}</span></header>
    <ol>{steps.map((step,index)=>{const Icon=icons[step];return <li key={step} className={graph.index===index?'is-active':''}>
      <Icon size={15}/><span>{t(`backfill.${step}`)}</span><strong>{graph.values[index]}</strong>
      {index<3 && <ArrowDown className={graph.active?'is-flowing':''} size={14} aria-hidden="true"/>}</li>;})}</ol>
    <footer><CornerUpLeft size={14}/><span>{t('backfill.return')}</span>{state?.next_check_at && <time>{t('backfill.next',{time:new Date(state.next_check_at).toLocaleString(i18n.language==='zh'?'zh-CN':'en-GB',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})})}</time>}</footer>
    {state?.reason && <p role="status">{t(`backfill.reason_${state.reason}`,{defaultValue:t('backfill.needsReview')})}</p>}
  </section>;
}
