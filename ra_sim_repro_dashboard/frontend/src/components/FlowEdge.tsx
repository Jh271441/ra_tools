import {
  BaseEdge,
  getSmoothStepPath,
  getStraightPath,
  Position,
  type EdgeProps,
} from '@xyflow/react';
import { lanePath, returnPath } from '../lib/flowLayout';

/** Directional motion follows the same path as the connector, including return bends. */
function FlowEdge(props: EdgeProps) {
  // Short aligned connectors must not double back when their handle offsets overlap.
  const aligned =
    (props.sourceY === props.targetY &&
      props.sourcePosition === Position.Right &&
      props.targetPosition === Position.Left) ||
    (props.sourceX === props.targetX &&
      props.sourcePosition === Position.Bottom &&
      props.targetPosition === Position.Top);
  const [standardPath] = aligned
    ? getStraightPath(props)
    : getSmoothStepPath({ ...props, borderRadius: 6, offset: 22 });
  const lx = Number(props.data?.loopX),
    ly = Number(props.data?.loopY);
  const { sourceX: sx, sourceY: sy, targetX: tx, targetY: ty } = props;
  const laneY = Number(props.data?.laneY);
  const path = Number.isFinite(laneY)
    ? lanePath(sx, sy, tx, ty, laneY)
    : props.data?.returnLane === true && Number.isFinite(lx) && Number.isFinite(ly)
      ? returnPath(sx, sy, tx, ty, lx, ly)
      : standardPath;
  const moving = props.animated || props.data?.scheduled === true;
  const seconds = props.animated ? 2.4 : 6;
  return (
    <>
      <BaseEdge
        id={props.id}
        path={path}
        markerEnd={props.markerEnd}
        style={props.style}
        label={props.label}
        labelX={(sx + tx) / 2}
        labelY={Number.isFinite(laneY) ? laneY : (sy + ty) / 2}
        labelStyle={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }}
        labelBgStyle={{ fill: 'hsl(var(--card))' }}
        labelBgPadding={[5, 3]}
      />
      {moving && (
        <g
          className="sim-flow-travelers"
          aria-hidden="true"
          pointerEvents="none"
          fill="none"
          stroke={props.style?.stroke || 'hsl(var(--primary))'}
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          {[0, 1].map((index) => (
            <g key={index} className="sim-flow-traveler">
              <path d="M -5 -3 L 0 0 L -5 3" />
              <animateMotion
                path={path}
                rotate="auto"
                dur={`${seconds}s`}
                begin={`${(-index * seconds) / 2}s`}
                repeatCount="indefinite"
              />
            </g>
          ))}
        </g>
      )}
    </>
  );
}
export const flowEdgeTypes = { flow: FlowEdge };
