import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ReactFlow, ReactFlowProvider, Background, Controls, MiniMap, Handle, Position, MarkerType, BaseEdge, useReactFlow } from '@xyflow/react';
import { layout, TASK_WIDTH, TASK_HEIGHT } from './layout.mjs';
import '@xyflow/react/dist/style.css';

const roots = new Map();
const colors = { success: 'var(--ok)', warn: 'var(--warn)', failed: 'var(--fail)', running: 'var(--accent)', pending: 'var(--faint)', skipped: 'var(--faint)', unknown: 'var(--faint)', definition: 'var(--muted)' };

function TaskNode({ data }) {
  return <div className="cron-dag-task" data-state={data.status}>
    {data.ports.filter(port => port.type === 'target').map(port => <Handle key={port.id} id={port.id} type="target" position={Position.Left} style={{ top: port.y }} isConnectable={false} />)}
    <div className="cron-dag-task-label"><span className="cron-dag-state-dot" /><strong>{data.label}</strong></div>
    <span className="cron-dag-task-meta">{data.detail}</span>
    <span className="cron-dag-task-state">{data.stateLabel}</span>
    <span className="cron-dag-task-timing" title={data.timingText}>{data.timingText}</span>
    {data.ports.filter(port => port.type === 'source').map(port => <Handle key={port.id} id={port.id} type="source" position={Position.Right} style={{ top: port.y }} isConnectable={false} />)}
  </div>;
}

function LaneNode({ data }) { return <div className="cron-dag-lane-label">{data.label}</div>; }
const nodeTypes = { task: TaskNode, lane: LaneNode };

// Render the same paths/label coordinates that ELK used to avoid the nodes.
function RoutedEdge({ id, data, markerEnd, style, interactionWidth, label, labelStyle, labelBgStyle }) {
  const route = data.route;
  return <BaseEdge id={id} path={route.path} markerEnd={markerEnd} style={style} interactionWidth={interactionWidth}
    label={label} labelX={route.label?.x} labelY={route.label?.y} labelStyle={labelStyle}
    labelBgStyle={labelBgStyle} labelBgPadding={[6, 4]} labelBgBorderRadius={4} />;
}
const edgeTypes = { routed: RoutedEdge };

function Graph({ model, onSelect }) {
  const [geometry, setGeometry] = useState(null);
  const { fitView } = useReactFlow();
  const topology = JSON.stringify([model.lanes.map(l => [l.id, l.nodes.map(n => n.id)]), model.edges.map(e => [e.id, e.source, e.target, e.label])]);
  useEffect(() => {
    let alive = true;
    layout(model).then(value => { if (alive) setGeometry(value); }).catch(() => { if (alive) setGeometry({ error: true }); });
    return () => { alive = false; };
  }, [topology]);
  useEffect(() => {
    if (!geometry || geometry.error) return;
    const timer = setTimeout(() => fitView({ padding: 0.06, duration: 0, maxZoom: 1 }), 40);
    return () => clearTimeout(timer);
  }, [geometry, fitView]);
  useEffect(() => {
    const resize = () => setTimeout(() => fitView({ padding: 0.06, duration: 0, maxZoom: 1 }), 80);
    document.addEventListener('fullscreenchange', resize);
    return () => document.removeEventListener('fullscreenchange', resize);
  }, [fitView]);
  const all = model.lanes.flatMap(lane => lane.nodes);
  const byId = new Map(all.map(node => [node.id, node.data]));
  const nodes = useMemo(() => geometry && !geometry.error ? [
    ...geometry.sizes.map(size => ({ id: size.id, type: 'lane', data: { label: model.lanes.find(l => l.id === size.id).label }, position: { x: size.x, y: size.y }, width: size.width, height: size.height, style: { width: size.width, height: size.height }, selectable: false, draggable: false, focusable: false })),
    ...geometry.positions.map(pos => ({ id: pos.id, type: 'task', data: { ...byId.get(pos.id), ports: pos.ports }, parentId: pos.parentId, extent: 'parent', position: { x: pos.x, y: pos.y }, selected: pos.id === model.selectedNode, width: TASK_WIDTH, height: TASK_HEIGHT, ariaLabel: [byId.get(pos.id).label, byId.get(pos.id).stateLabel, byId.get(pos.id).detail, byId.get(pos.id).timingText].join(' · '), style: { width: TASK_WIDTH, height: TASK_HEIGHT } })),
  ] : [], [geometry, model]);
  const routes = new Map((geometry?.edges || []).map(edge => [edge.id, edge]));
  const edges = model.edges.filter(edge => routes.has(edge.id)).map(edge => {
    const state = byId.get(edge.target)?.status;
    const sourceState = byId.get(edge.source)?.status;
    const unknownPath = [state, sourceState].some(status => ['skipped', 'unknown', 'pending'].includes(status));
    const color = unknownPath ? 'var(--muted)' : sourceState === 'warn' ? colors.warn : colors[state] || colors.unknown;
    return { ...edge, type: 'routed', sourceHandle: routes.get(edge.id).sourceHandle, targetHandle: routes.get(edge.id).targetHandle, data: { route: routes.get(edge.id) }, animated: !unknownPath && !model.definition && model.active && state === 'running', markerEnd: { type: MarkerType.ArrowClosed, color, width: 18, height: 18 }, style: { stroke: color, strokeWidth: 2, ...(edge.optional ? { strokeDasharray: '5 4' } : {}) }, labelStyle: { fill: 'var(--muted)', fontSize: 11 }, labelBgStyle: { fill: 'var(--raised)' }, interactionWidth: 12 };
  });
  if (geometry?.error) return <p className="cron-note muted">{model.ui.error}</p>;
  if (!geometry) return <p className="cron-note muted">{model.ui.loading}</p>;
  return <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} nodesDraggable={false} nodesConnectable={false} edgesFocusable={false} onNodeClick={(_, node) => node.type === 'task' && onSelect?.(node.id)} onPaneClick={() => onSelect?.('')} minZoom={0.25} maxZoom={2} fitView fitViewOptions={{ padding: 0.06, maxZoom: 1 }} zoomOnScroll={false} preventScrolling={false} colorMode={model.theme} proOptions={{ hideAttribution: false }}>
    <Background color="var(--line)" gap={20} size={1} />
    <Controls showInteractive={false} />
    <MiniMap ariaLabel={model.ui.minimap} style={{ width: 160, height: 100 }} nodeColor={node => node.type === 'lane' ? 'transparent' : colors[node.data?.status] || colors.unknown} nodeStrokeColor="var(--line)" maskColor="var(--cron-minimap-mask, rgba(0,0,0,.12))" pannable zoomable />
  </ReactFlow>;
}

class Boundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <p className="cron-note muted">{this.props.model.ui.error}</p> : this.props.children; }
}

export function render(element, model, onSelect) {
  if (!roots.has(element)) roots.set(element, createRoot(element));
  roots.get(element).render(<Boundary model={model}><ReactFlowProvider><Graph model={model} onSelect={onSelect} /></ReactFlowProvider></Boundary>);
}

export function unmount(element) {
  const root = roots.get(element);
  if (root) { root.unmount(); roots.delete(element); }
}
