import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ReactFlow, ReactFlowProvider, Background, Controls, MiniMap, Handle, Position, MarkerType, useReactFlow } from '@xyflow/react';
import ELK from 'elkjs/lib/elk.bundled.js';
import '@xyflow/react/dist/style.css';

const roots = new Map();
const elk = new ELK();
const colors = { success: 'var(--ok)', warn: 'var(--warn)', failed: 'var(--fail)', running: 'var(--accent)', pending: 'var(--faint)', skipped: 'var(--faint)', unknown: 'var(--faint)', definition: 'var(--muted)' };

function TaskNode({ data }) {
  return <div className="cron-dag-task" data-state={data.status}>
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <div className="cron-dag-task-label"><span className="cron-dag-state-dot" /><strong>{data.label}</strong></div>
    <span className="cron-dag-task-meta">{data.detail}</span>
    <span className="cron-dag-task-state">{data.stateLabel}</span>
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </div>;
}

function LaneNode({ data }) { return <div className="cron-dag-lane-label">{data.label}</div>; }
const nodeTypes = { task: TaskNode, lane: LaneNode };

async function layout(model) {
  const positions = [], sizes = [];
  let offsetY = 0;
  for (const lane of model.lanes) {
    const ids = new Set(lane.nodes.map(node => node.id));
    const graph = await elk.layout({
      id: lane.id,
      layoutOptions: { 'elk.algorithm': 'layered', 'elk.direction': 'RIGHT', 'elk.spacing.nodeNode': '28', 'elk.layered.spacing.nodeNodeBetweenLayers': '42', 'elk.padding': '[top=52,left=20,bottom=20,right=20]' },
      children: lane.nodes.map(node => ({ id: node.id, width: 152, height: 82 })),
      edges: model.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target)).map(edge => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })),
    });
    sizes.push({ id: lane.id, x: 0, y: offsetY, width: graph.width, height: graph.height });
    for (const child of graph.children) positions.push({ id: child.id, parentId: lane.id, x: child.x, y: child.y });
    offsetY += graph.height + 50;
  }
  return { positions, sizes };
}

function Graph({ model, onSelect }) {
  const [geometry, setGeometry] = useState(null);
  const { fitView } = useReactFlow();
  const topology = JSON.stringify([model.lanes.map(l => [l.id, l.nodes.map(n => n.id)]), model.edges.map(e => [e.id, e.source, e.target])]);
  useEffect(() => {
    let alive = true;
    layout(model).then(value => { if (alive) setGeometry(value); }).catch(() => { if (alive) setGeometry({ error: true }); });
    return () => { alive = false; };
  }, [topology]);
  useEffect(() => {
    if (!geometry || geometry.error) return;
    const timer = setTimeout(() => fitView({ padding: 0.12, duration: 0, maxZoom: 1 }), 40);
    return () => clearTimeout(timer);
  }, [geometry, fitView]);
  useEffect(() => {
    const resize = () => setTimeout(() => fitView({ padding: 0.12, duration: 0, maxZoom: 1 }), 80);
    document.addEventListener('fullscreenchange', resize);
    return () => document.removeEventListener('fullscreenchange', resize);
  }, [fitView]);
  const all = model.lanes.flatMap(lane => lane.nodes);
  const byId = new Map(all.map(node => [node.id, node.data]));
  const nodes = useMemo(() => geometry && !geometry.error ? [
    ...geometry.sizes.map(size => ({ id: size.id, type: 'lane', data: { label: model.lanes.find(l => l.id === size.id).label }, position: { x: size.x, y: size.y }, style: { width: size.width, height: size.height }, selectable: false, draggable: false, focusable: false })),
    ...geometry.positions.map(pos => ({ id: pos.id, type: 'task', data: byId.get(pos.id), parentId: pos.parentId, extent: 'parent', position: { x: pos.x, y: pos.y }, selected: pos.id === model.selectedNode, ariaLabel: [byId.get(pos.id).label, byId.get(pos.id).stateLabel, byId.get(pos.id).detail].join(' · '), style: { width: 152, height: 82 } })),
  ] : [], [geometry, model]);
  const edges = model.edges.map(edge => {
    const state = byId.get(edge.target)?.status;
    const sourceState = byId.get(edge.source)?.status;
    const unknownPath = [state, sourceState].some(status => ['skipped', 'unknown', 'pending'].includes(status));
    const color = unknownPath ? 'var(--line)' : sourceState === 'warn' ? colors.warn : colors[state] || colors.unknown;
    return { ...edge, type: 'smoothstep', animated: !unknownPath && !model.definition && model.active && state === 'running', markerEnd: { type: MarkerType.ArrowClosed, color }, style: { stroke: color, strokeWidth: 1.35, ...(edge.optional ? { strokeDasharray: '5 4' } : {}) }, labelStyle: { fill: 'var(--muted)', fontSize: 10 }, labelBgStyle: { fill: 'var(--raised)' }, interactionWidth: 12 };
  });
  if (geometry?.error) return <p className="cron-note muted">{model.ui.error}</p>;
  if (!geometry) return <p className="cron-note muted">{model.ui.loading}</p>;
  return <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} nodesDraggable={false} nodesConnectable={false} edgesFocusable={false} onNodeClick={(_, node) => node.type === 'task' && onSelect?.(node.id)} onPaneClick={() => onSelect?.('')} minZoom={0.25} maxZoom={2} fitView fitViewOptions={{ padding: 0.12, maxZoom: 1 }} zoomOnScroll={false} preventScrolling={false} colorMode={model.theme} proOptions={{ hideAttribution: false }}>
    <Background color="var(--line)" gap={20} size={1} />
    <Controls showInteractive={false} />
    <MiniMap nodeColor={node => node.type === 'lane' ? 'transparent' : colors[node.data?.status] || colors.unknown} nodeStrokeColor="var(--line)" maskColor="var(--cron-minimap-mask, rgba(0,0,0,.12))" pannable zoomable />
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
