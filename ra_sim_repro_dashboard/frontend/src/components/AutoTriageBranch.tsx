import { memo, useMemo } from 'react';
import { Handle, MarkerType, Position, type Node, type NodeProps } from '@xyflow/react';
import { Clock3, GitBranch, Play, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { EvaluationBoard } from '../types/evaluation';
import { evaluationFlow, evaluationMotion, type EvaluationStage, type EvaluationStep } from '../lib/evaluationFlow';

interface BranchData extends EvaluationStage, Record<string, unknown> { onOpen: () => void }
const icons = {sync:Clock3,rules:SlidersHorizontal,plan:GitBranch,manual:Play,evaluate:ShieldCheck};
const titles: Record<EvaluationStep,string> = {sync:'flow_snapshot',rules:'flow_profile',plan:'flow_plan',manual:'flow_simulation',evaluate:'flow_metrics'};
function BranchCard({step,value,total,state,status,params,onOpen}: BranchData) {
  const {t,i18n}=useTranslation(), Icon=icons[step];
  return <button className={`nodrag nopan sim-auto-node sim-flow-${state}`} type="button" onClick={onOpen} aria-label={`${t(`evaluation.${titles[step]}`)} · ${t('evaluation.sidecar_open')}`}>
    <span className="sim-flow-node-title"><Icon size={16}/><strong>{t(`evaluation.${titles[step]}`)}</strong></span>
    <span className="sim-flow-count">{step === 'rules' && value != null ? t('evaluation.current_rules') : value == null ? '—' : typeof value === 'number' ? value.toLocaleString(i18n.language) : value}{total != null && <span className="text-sm font-normal text-muted-foreground"> / {total.toLocaleString(i18n.language)}</span>}</span>
    <span className="sim-flow-status">{t(`evaluation.${status}`,params)}</span>
  </button>;
}
export const AutoTriageNode=memo(function AutoTriageNode({data}:NodeProps<Node<BranchData>>) {
  return <><Handle id="in" type="target" position={Position.Left} isConnectable={false}/><BranchCard {...data}/><Handle id="out" type="source" position={Position.Right} isConnectable={false}/>{data.step==='plan' && <Handle id="bottom-out" type="source" position={Position.Bottom} isConnectable={false}/>}{data.step==='evaluate' && <Handle id="bottom-in" type="target" position={Position.Bottom} isConnectable={false}/>}</>;
});
export function useAutoTriageGraph(data:EvaluationBoard|null|undefined,enabled:boolean,y:number,onOpen:()=>void) {
  const {t}=useTranslation();
  return useMemo(()=>{
    if(!enabled)return {nodes:[] as Node[],edges:[],steps:[] as BranchData[]};
    const steps:BranchData[]=evaluationFlow(data).map(stage=>({...stage,onOpen}));
    const nodes:Node[]=steps.map((data,i)=>({id:`auto-${data.step}`,type:'autoTriage',position:{x:i*240,y},width:196,height:132,data,draggable:false,selectable:false,focusable:false}));
    nodes.push({id:'auto-caption',type:'labelCaption',position:{x:0,y:y-34},data:{label:`${t('evaluation.sidecar_title')} · ${t('evaluation.shared_inputs')}`},selectable:false,focusable:false});
    const motion = evaluationMotion(data);
    const links = [
      {source:'sync',target:'rules',animated:motion.refreshing,scheduled:motion.check},
      {source:'rules',target:'plan',animated:motion.refreshing,scheduled:motion.check},
      {source:'plan',target:'manual',animated:motion.dispatch,scheduled:false},
      {source:'manual',target:'evaluate',animated:motion.evaluating && !motion.refreshing,scheduled:false},
      {source:'plan',target:'evaluate',animated:motion.evaluating,scheduled:false,reuse:true},
    ];
    const edges=links.map(link=>({id:`auto-${link.source}-${link.target}`,source:`auto-${link.source}`,target:`auto-${link.target}`,
      sourceHandle:link.reuse?'bottom-out':'out',targetHandle:link.reuse?'bottom-in':'in',type:'flow',animated:link.animated,
      data:{scheduled:link.scheduled,...(link.reuse?{laneY:y+164}:{})},label:link.reuse?t('evaluation.reuse_link'):undefined,
      style:{stroke:link.animated || link.scheduled?'hsl(var(--primary))':'hsl(var(--muted-foreground))',strokeWidth:1.3,strokeDasharray:link.reuse?'4 5':undefined},
      markerEnd:{type:MarkerType.ArrowClosed,color:'hsl(var(--muted-foreground))'}}));
    return {nodes,edges,steps};
  },[data,enabled,y,onOpen,t]);
}
export function AutoTriageBranchList({steps}:{steps:BranchData[]}) {
  const {t}=useTranslation();
  return <section className="sim-auto-mobile" aria-label={t('evaluation.sidecar_title')}><h3 className="text-sm font-semibold">{t('evaluation.sidecar_title')}</h3><ol>{steps.map(data=><li key={data.step}><BranchCard {...data}/></li>)}</ol></section>;
}
