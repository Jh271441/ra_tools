import { BaseEdge, getSmoothStepPath, getStraightPath, Position, type EdgeProps } from '@xyflow/react';

/** Directional motion follows the same path as the connector, including return bends. */
function FlowEdge(props: EdgeProps) {
  // Short aligned connectors must not double back when their handle offsets overlap.
  const aligned = (props.sourceY === props.targetY && props.sourcePosition === Position.Right && props.targetPosition === Position.Left)
    || (props.sourceX === props.targetX && props.sourcePosition === Position.Bottom && props.targetPosition === Position.Top);
  const [standardPath] = aligned ? getStraightPath(props) : getSmoothStepPath({...props, borderRadius: 6, offset: 22});
  const lx = Number(props.data?.loopX), ly = Number(props.data?.loopY);
  const {sourceX:sx,sourceY:sy,targetX:tx,targetY:ty} = props;
  const path = props.data?.returnLane === true && Number.isFinite(lx) && Number.isFinite(ly)
    ? `M ${sx} ${sy} L ${sx} ${ly-6} Q ${sx} ${ly} ${sx-6} ${ly} L ${lx+6} ${ly} Q ${lx} ${ly} ${lx} ${ly-6} L ${lx} ${ty+28} Q ${lx} ${ty+22} ${lx+6} ${ty+22} L ${tx-6} ${ty+22} Q ${tx} ${ty+22} ${tx} ${ty+16} L ${tx} ${ty}`
    : standardPath;
  const moving = props.animated || props.data?.scheduled === true;
  const seconds = props.animated ? 2.4 : 6;
  return <>
    <BaseEdge id={props.id} path={path} markerEnd={props.markerEnd} style={props.style}/>
    {moving && <g className="sim-flow-travelers" aria-hidden="true" pointerEvents="none" fill="none" stroke={props.style?.stroke || 'hsl(var(--primary))'} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      {[0, 1].map(index=><g key={index} className="sim-flow-traveler">
        <path d="M -5 -3 L 0 0 L -5 3"/>
        <animateMotion path={path} rotate="auto" dur={`${seconds}s`} begin={`${-index*seconds/2}s`} repeatCount="indefinite"/>
      </g>)}
    </g>}
  </>;
}
export const flowEdgeTypes = {flow: FlowEdge};
