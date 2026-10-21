import ELK from 'elkjs/lib/elk.bundled.js';

export const TASK_WIDTH = 152;
export const TASK_HEIGHT = 104;
const LANE_GAP = 88;
const OUTER_CHANNEL = 24;
const elk = new ELK();

// Include the label background in ELK's reservation, for Chinese and English.
function labelSize(text) {
  return { width: Math.ceil([...text].reduce((width, char) => width + (/[^\u0000-\u00ff]/.test(char) ? 12 : 6.8), 0)) + 16, height: 26 };
}

function roundedPath(points) {
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i++) {
    const prev = points[i - 1], point = points[i], next = points[i + 1];
    const before = Math.hypot(point.x - prev.x, point.y - prev.y);
    const after = Math.hypot(next.x - point.x, next.y - point.y);
    if (!before || !after) continue;
    const radius = Math.min(6, before / 2, after / 2);
    const start = { x: point.x + (prev.x - point.x) * radius / before, y: point.y + (prev.y - point.y) * radius / before };
    const end = { x: point.x + (next.x - point.x) * radius / after, y: point.y + (next.y - point.y) * radius / after };
    path += ` L ${start.x} ${start.y} Q ${point.x} ${point.y} ${end.x} ${end.y}`;
  }
  const end = points.at(-1);
  return `${path} L ${end.x} ${end.y}`;
}

export async function layout(model) {
  const positions = [], sizes = [], edges = [];
  const portsByNode = new Map(model.lanes.flatMap(lane => lane.nodes).map(node => {
    const ports = ['target', 'source'].flatMap(type => {
      const connected = model.edges.filter(edge => edge[type] === node.id);
      return (connected.length ? connected : [{ id: `${node.id}:unused` }]).map((edge, i, all) => ({
        id: `${edge.id}:${type}`, type, y: TASK_HEIGHT * (i + 1) / (all.length + 1),
      }));
    });
    return [node.id, ports];
  }));
  let offsetY = 0;
  for (const lane of model.lanes) {
    const ids = new Set(lane.nodes.map(node => node.id));
    const graph = await elk.layout({
      id: lane.id,
      layoutOptions: {
        'elk.algorithm': 'layered', 'elk.direction': 'RIGHT', 'elk.edgeRouting': 'ORTHOGONAL',
        'elk.spacing.nodeNode': '44', 'elk.spacing.edgeNode': '18', 'elk.spacing.edgeEdge': '14',
        'elk.layered.spacing.nodeNodeBetweenLayers': '44',
        'elk.layered.spacing.edgeNodeBetweenLayers': '18',
        'elk.layered.spacing.edgeEdgeBetweenLayers': '14',
        'elk.padding': '[top=46,left=24,bottom=24,right=24]',
      },
      children: lane.nodes.map(node => ({
        id: node.id, width: TASK_WIDTH, height: TASK_HEIGHT,
        layoutOptions: { 'elk.portConstraints': 'FIXED_POS' },
        ports: portsByNode.get(node.id).map(port => ({
          id: port.id, x: port.type === 'target' ? 0 : TASK_WIDTH, y: port.y, width: 0, height: 0,
          layoutOptions: { 'elk.port.side': port.type === 'target' ? 'WEST' : 'EAST' },
        })),
      })),
      edges: model.edges.filter(edge => ids.has(edge.source) && ids.has(edge.target)).map(edge => ({
        id: edge.id, sources: [`${edge.id}:source`], targets: [`${edge.id}:target`],
        labels: edge.label ? [{ text: edge.label, ...labelSize(edge.label), layoutOptions: { 'elk.edgeLabels.placement': 'CENTER', 'elk.edgeLabels.inline': 'true' } }] : [],
      })),
    });
    const laneX = OUTER_CHANNEL + 8;
    sizes.push({ id: lane.id, x: laneX, y: offsetY, width: graph.width, height: graph.height });
    for (const child of graph.children) positions.push({ id: child.id, parentId: lane.id, x: child.x, y: child.y, ports: portsByNode.get(child.id) });
    for (const edge of graph.edges) {
      const section = edge.sections[0];
      const points = [section.startPoint, ...(section.bendPoints || []), section.endPoint].map(p => ({ x: p.x + laneX, y: p.y + offsetY }));
      const label = edge.labels?.[0];
      edges.push({ id: edge.id, sourceHandle: `${edge.id}:source`, targetHandle: `${edge.id}:target`, points, path: roundedPath(points), label: label && { x: label.x + laneX + label.width / 2, y: label.y + offsetY + label.height / 2, width: label.width, height: label.height } });
    }
    offsetY += graph.height + LANE_GAP;
  }
  const lanesById = new Map(sizes.map(lane => [lane.id, lane]));
  const tasks = new Map(positions.map(pos => {
    const lane = lanesById.get(pos.parentId);
    return [pos.id, { ...pos, x: pos.x + lane.x, y: pos.y + lane.y, lane }];
  }));
  // Cross-lane receipts use their own gutter, clear of lane borders and titles.
  for (const edge of model.edges) {
    const source = tasks.get(edge.source), target = tasks.get(edge.target);
    if (source.parentId === target.parentId) continue;
    const right = source.lane.x + source.lane.width + OUTER_CHANNEL;
    const left = target.lane.x - OUTER_CHANNEL;
    const channelY = (source.lane.y + source.lane.height + target.lane.y) / 2;
    const sourceY = source.y + source.ports.find(port => port.id === `${edge.id}:source`).y;
    const targetY = target.y + target.ports.find(port => port.id === `${edge.id}:target`).y;
    const points = [
      { x: source.x + TASK_WIDTH, y: sourceY },
      { x: right, y: sourceY },
      { x: right, y: channelY }, { x: left, y: channelY },
      { x: left, y: targetY },
      { x: target.x, y: targetY },
    ];
    edges.push({ id: edge.id, sourceHandle: `${edge.id}:source`, targetHandle: `${edge.id}:target`, points, path: roundedPath(points), label: edge.label && { x: (left + right) / 2, y: channelY, ...labelSize(edge.label) } });
  }
  return { positions, sizes, edges };
}
