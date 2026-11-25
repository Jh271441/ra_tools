import ELK from "elkjs/lib/elk.bundled.js";

export const TASK_WIDTH = 152;
export const TASK_HEIGHT = 116;
const LANE_GAP = 88;
const OUTER_CHANNEL = 24;
const elk = new ELK();

export interface CronGraphPort {
  id: string;
  type: "source" | "target";
  y: number;
}

export interface CronGraphNodeProgress {
  mode: "count" | "empty" | "waiting" | "unknown";
  text: string;
  percentText?: string;
  label?: string;
  stale?: boolean;
  done?: number;
  total?: number;
  remaining?: number;
  failed?: number | null;
  skipped?: number | null;
  percent?: number;
  completePercent?: number;
  failurePercent?: number;
}

export interface CronGraphNodeData {
  label: string;
  detail?: string;
  status: string;
  stateLabel: string;
  timing?: unknown;
  timingText?: string;
  progress?: CronGraphNodeProgress | null;
  rows?: Array<[string, string | number]>;
  issues?: string[];
  ports?: CronGraphPort[];
}

export interface CronGraphNode {
  id: string;
  data: CronGraphNodeData;
}

export interface CronGraphLane {
  id: string;
  label: string;
  nodes: CronGraphNode[];
}

export interface CronGraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  optional?: boolean;
}

export interface CronGraphModel {
  lanes: CronGraphLane[];
  edges: CronGraphEdge[];
  selectedNode?: string;
  definition?: boolean;
  active?: boolean;
  theme?: "dark" | "light";
  ui: {
    minimap: string;
    loading: string;
    error: string;
  };
}

export interface LayoutPoint {
  x: number;
  y: number;
}

export interface LayoutLaneSize {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface LayoutTaskPosition {
  id: string;
  parentId: string;
  x: number;
  y: number;
  ports: CronGraphPort[];
}

export interface LayoutEdgeRoute {
  id: string;
  sourceHandle: string;
  targetHandle: string;
  points: LayoutPoint[];
  path: string;
  label?: { x: number; y: number; width: number; height: number } | null;
}

export interface LayoutGeometry {
  positions: LayoutTaskPosition[];
  sizes: LayoutLaneSize[];
  edges: LayoutEdgeRoute[];
  error?: boolean;
}

function labelSize(text: string): { width: number; height: number } {
  return {
    width:
      Math.ceil(
        [...text].reduce(
          (width, char) => width + (/[^\u0000-\u00ff]/.test(char) ? 12 : 6.8),
          0,
        ),
      ) + 16,
    height: 26,
  };
}

function roundedPath(points: LayoutPoint[]): string {
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length - 1; i += 1) {
    const prev = points[i - 1];
    const point = points[i];
    const next = points[i + 1];
    const before = Math.hypot(point.x - prev.x, point.y - prev.y);
    const after = Math.hypot(next.x - point.x, next.y - point.y);
    if (!before || !after) continue;
    const radius = Math.min(6, before / 2, after / 2);
    const start = {
      x: point.x + ((prev.x - point.x) * radius) / before,
      y: point.y + ((prev.y - point.y) * radius) / before,
    };
    const end = {
      x: point.x + ((next.x - point.x) * radius) / after,
      y: point.y + ((next.y - point.y) * radius) / after,
    };
    path += ` L ${start.x} ${start.y} Q ${point.x} ${point.y} ${end.x} ${end.y}`;
  }
  const end = points[points.length - 1];
  return `${path} L ${end.x} ${end.y}`;
}

export async function layoutCronGraph(model: CronGraphModel): Promise<LayoutGeometry> {
  const positions: LayoutTaskPosition[] = [];
  const sizes: LayoutLaneSize[] = [];
  const edges: LayoutEdgeRoute[] = [];

  const portsByNode = new Map<string, CronGraphPort[]>(
    model.lanes
      .flatMap((lane) => lane.nodes)
      .map((node) => {
        const ports: CronGraphPort[] = (["target", "source"] as const).flatMap((type) => {
          const connected = model.edges.filter((edge) => edge[type] === node.id);
          const list = connected.length ? connected : [{ id: `${node.id}:unused` }];
          return list.map((edge, i, all) => ({
            id: `${edge.id}:${type}`,
            type,
            y: (TASK_HEIGHT * (i + 1)) / (all.length + 1),
          }));
        });
        return [node.id, ports];
      }),
  );

  let offsetY = 0;
  for (const lane of model.lanes) {
    const ids = new Set(lane.nodes.map((node) => node.id));
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const graph: any = await elk.layout({
      id: lane.id,
      layoutOptions: {
        "elk.algorithm": "layered",
        "elk.direction": "RIGHT",
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.spacing.nodeNode": "44",
        "elk.spacing.edgeNode": "18",
        "elk.spacing.edgeEdge": "14",
        "elk.layered.spacing.nodeNodeBetweenLayers": "44",
        "elk.layered.spacing.edgeNodeBetweenLayers": "18",
        "elk.layered.spacing.edgeEdgeBetweenLayers": "14",
        "elk.padding": "[top=46,left=24,bottom=24,right=24]",
      },
      children: lane.nodes.map((node) => ({
        id: node.id,
        width: TASK_WIDTH,
        height: TASK_HEIGHT,
        layoutOptions: { "elk.portConstraints": "FIXED_POS" },
        ports: (portsByNode.get(node.id) || []).map((port) => ({
          id: port.id,
          x: port.type === "target" ? 0 : TASK_WIDTH,
          y: port.y,
          width: 0,
          height: 0,
          layoutOptions: { "elk.port.side": port.type === "target" ? "WEST" : "EAST" },
        })),
      })),
      edges: model.edges
        .filter((edge) => ids.has(edge.source) && ids.has(edge.target))
        .map((edge) => ({
          id: edge.id,
          sources: [`${edge.id}:source`],
          targets: [`${edge.id}:target`],
          labels: edge.label
            ? [
                {
                  text: edge.label,
                  ...labelSize(edge.label),
                  layoutOptions: {
                    "elk.edgeLabels.placement": "CENTER",
                    "elk.edgeLabels.inline": "true",
                  },
                },
              ]
            : [],
        })),
    });

    const laneX = OUTER_CHANNEL + 8;
    const laneWidth = graph.width ?? 400;
    const laneHeight = graph.height ?? TASK_HEIGHT + 70;
    sizes.push({ id: lane.id, x: laneX, y: offsetY, width: laneWidth, height: laneHeight });

    for (const child of graph.children || []) {
      positions.push({
        id: child.id,
        parentId: lane.id,
        x: child.x ?? 0,
        y: child.y ?? 0,
        ports: portsByNode.get(child.id) || [],
      });
    }

    for (const edge of graph.edges || []) {
      const section = edge.sections?.[0];
      if (!section) continue;
      const points = [
        section.startPoint,
        ...(section.bendPoints || []),
        section.endPoint,
      ].map((p) => ({ x: p.x + laneX, y: p.y + offsetY }));
      const label = edge.labels?.[0];
      edges.push({
        id: edge.id,
        sourceHandle: `${edge.id}:source`,
        targetHandle: `${edge.id}:target`,
        points,
        path: roundedPath(points),
        label:
          label && label.x != null && label.y != null && label.width != null && label.height != null
            ? {
                x: label.x + laneX + label.width / 2,
                y: label.y + offsetY + label.height / 2,
                width: label.width,
                height: label.height,
              }
            : null,
      });
    }
    offsetY += laneHeight + LANE_GAP;
  }

  const lanesById = new Map(sizes.map((lane) => [lane.id, lane]));
  const tasks = new Map(
    positions.map((pos) => {
      const lane = lanesById.get(pos.parentId)!;
      return [pos.id, { ...pos, x: pos.x + lane.x, y: pos.y + lane.y, lane }];
    }),
  );

  for (const edge of model.edges) {
    const source = tasks.get(edge.source);
    const target = tasks.get(edge.target);
    if (!source || !target || source.parentId === target.parentId) continue;
    const right = source.x + TASK_WIDTH + OUTER_CHANNEL;
    const left = target.lane.x - OUTER_CHANNEL;
    const channelY = (source.lane.y + source.lane.height + target.lane.y) / 2;
    const sourcePort = source.ports.find((port) => port.id === `${edge.id}:source`);
    const targetPort = target.ports.find((port) => port.id === `${edge.id}:target`);
    const sourceY = source.y + (sourcePort?.y ?? TASK_HEIGHT / 2);
    const targetY = target.y + (targetPort?.y ?? TASK_HEIGHT / 2);
    const points: LayoutPoint[] = [
      { x: source.x + TASK_WIDTH, y: sourceY },
      { x: right, y: sourceY },
      { x: right, y: channelY },
      { x: left, y: channelY },
      { x: left, y: targetY },
      { x: target.x, y: targetY },
    ];
    edges.push({
      id: edge.id,
      sourceHandle: `${edge.id}:source`,
      targetHandle: `${edge.id}:target`,
      points,
      path: roundedPath(points),
      label: edge.label
        ? { x: (left + right) / 2, y: channelY, ...labelSize(edge.label) }
        : null,
    });
  }

  return { positions, sizes, edges };
}
