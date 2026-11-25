import React, { useEffect, useMemo, useState } from "react";
import {
  Background,
  BaseEdge,
  Controls,
  Edge,
  EdgeProps,
  Handle,
  MarkerType,
  MiniMap,
  Node,
  NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  CronGraphModel,
  CronGraphNodeData,
  CronGraphNodeProgress,
  layoutCronGraph,
  LayoutEdgeRoute,
  LayoutGeometry,
  TASK_HEIGHT,
  TASK_WIDTH,
} from "./layout";

const STATUS_COLORS: Record<string, string> = {
  success: "var(--ok)",
  warn: "var(--warn)",
  failed: "var(--fail)",
  running: "var(--warn)",
  pending: "var(--faint)",
  skipped: "var(--faint)",
  unknown: "var(--faint)",
  definition: "var(--muted)",
};

const TaskProgress: React.FC<{ progress: CronGraphNodeProgress }> = ({ progress }) => {
  if (progress.mode !== "count") {
    return <span className="cron-task-progress-empty">{progress.text}</span>;
  }
  return (
    <div className="cron-task-progress" data-stale={String(Boolean(progress.stale))} title={progress.label}>
      <div className="cron-task-progress-values">
        <span>{progress.text}</span>
        <strong>{progress.percentText}</strong>
      </div>
      <div
        className="cron-task-progress-track"
        role="progressbar"
        aria-label={progress.label}
        aria-valuemin={0}
        aria-valuemax={progress.total}
        aria-valuenow={progress.done}
        aria-valuetext={`${progress.text} · ${progress.percentText}`}
      >
        <span style={{ width: `${progress.completePercent || 0}%` }} />
        <i style={{ width: `${progress.failurePercent || 0}%` }} />
      </div>
    </div>
  );
};

const TaskNodeContent: React.FC<{ data: CronGraphNodeData }> = ({ data }) => (
  <div className="cron-dag-task" data-state={data.status}>
    {(data.ports || [])
      .filter((port) => port.type === "target")
      .map((port) => (
        <Handle
          key={port.id}
          id={port.id}
          type="target"
          position={Position.Left}
          style={{ top: port.y }}
          isConnectable={false}
        />
      ))}
    <div className="cron-dag-task-label">
      <span className="cron-dag-state-dot" />
      <strong>{data.label}</strong>
    </div>
    {data.progress ? (
      <TaskProgress progress={data.progress} />
    ) : (
      <span className="cron-dag-task-meta" title={data.detail}>
        {data.detail}
      </span>
    )}
    <span className="cron-dag-task-state">{data.stateLabel}</span>
    <span className="cron-dag-task-timing" title={data.timingText}>
      {data.timingText}
    </span>
    {(data.ports || [])
      .filter((port) => port.type === "source")
      .map((port) => (
        <Handle
          key={port.id}
          id={port.id}
          type="source"
          position={Position.Right}
          style={{ top: port.y }}
          isConnectable={false}
        />
      ))}
  </div>
);

const TaskNode: React.FC<NodeProps> = ({ data }) => (
  <TaskNodeContent data={data as unknown as CronGraphNodeData} />
);

const LaneNode: React.FC<NodeProps> = ({ data }) => (
  <div className="cron-dag-lane-label">{String((data as { label?: string }).label || "")}</div>
);

const nodeTypes = { task: TaskNode, lane: LaneNode };

const RoutedEdge: React.FC<EdgeProps> = ({
  id,
  data,
  markerEnd,
  style,
  interactionWidth,
  label,
  labelStyle,
  labelBgStyle,
}) => {
  const route = (data as { route?: LayoutEdgeRoute } | undefined)?.route;
  if (!route) return null;
  return (
    <BaseEdge
      id={id}
      path={route.path}
      markerEnd={markerEnd}
      style={style}
      interactionWidth={interactionWidth}
      label={label}
      labelX={route.label?.x}
      labelY={route.label?.y}
      labelStyle={labelStyle}
      labelBgStyle={labelBgStyle}
      labelBgPadding={[6, 4]}
      labelBgBorderRadius={4}
    />
  );
};

const edgeTypes = { routed: RoutedEdge };

interface CronGraphInnerProps {
  model: CronGraphModel;
  onSelect?: (nodeId: string) => void;
}

const CronGraphInner: React.FC<CronGraphInnerProps> = ({ model, onSelect }) => {
  const [layoutResult, setLayoutResult] = useState<{
    topology: string;
    geometry: LayoutGeometry;
  } | null>(null);
  const { fitView } = useReactFlow();

  const topology = useMemo(
    () =>
      JSON.stringify([
        model.lanes.map((l) => [l.id, l.nodes.map((n) => n.id)]),
        model.edges.map((e) => [e.id, e.source, e.target, e.label]),
      ]),
    [model.lanes, model.edges],
  );

  const geometry = layoutResult?.topology === topology ? layoutResult.geometry : null;

  useEffect(() => {
    let alive = true;
    layoutCronGraph(model)
      .then((value) => {
        if (alive) setLayoutResult({ topology, geometry: value });
      })
      .catch(() => {
        if (alive) {
          setLayoutResult({
            topology,
            geometry: { positions: [], sizes: [], edges: [], error: true },
          });
        }
      });
    return () => {
      alive = false;
    };
  }, [topology, model]);

  useEffect(() => {
    if (!geometry || geometry.error) return;
    const timer = window.setTimeout(() => fitView({ padding: 0.06, duration: 0, maxZoom: 1 }), 40);
    return () => window.clearTimeout(timer);
  }, [geometry, fitView]);

  useEffect(() => {
    const resize = () =>
      window.setTimeout(() => fitView({ padding: 0.06, duration: 0, maxZoom: 1 }), 80);
    document.addEventListener("fullscreenchange", resize);
    return () => document.removeEventListener("fullscreenchange", resize);
  }, [fitView]);

  useEffect(() => {
    const frame = requestAnimationFrame(() =>
      requestAnimationFrame(() => fitView({ padding: 0.06, duration: 0, maxZoom: 1 })),
    );
    return () => cancelAnimationFrame(frame);
  }, [model.selectedNode, fitView]);

  const byId = useMemo(
    () => new Map(model.lanes.flatMap((lane) => lane.nodes).map((node) => [node.id, node.data])),
    [model.lanes],
  );

  const nodes = useMemo<Node[]>(() => {
    if (!geometry || geometry.error) return [];
    const laneNodes: Node[] = geometry.sizes.map((size) => ({
      id: size.id,
      type: "lane",
      data: { label: model.lanes.find((l) => l.id === size.id)?.label || size.id },
      position: { x: size.x, y: size.y },
      width: size.width,
      height: size.height,
      style: { width: size.width, height: size.height },
      selectable: false,
      draggable: false,
      focusable: false,
    }));
    const taskNodes: Node[] = geometry.positions.map((pos) => {
      const nodeData = byId.get(pos.id);
      return {
        id: pos.id,
        type: "task",
        data: { ...(nodeData || { label: pos.id, status: "unknown", stateLabel: "" }), ports: pos.ports },
        parentId: pos.parentId,
        extent: "parent",
        position: { x: pos.x, y: pos.y },
        selected: pos.id === model.selectedNode,
        width: TASK_WIDTH,
        height: TASK_HEIGHT,
        ariaLabel: [
          nodeData?.label,
          nodeData?.stateLabel,
          nodeData?.progress?.text || nodeData?.detail,
          nodeData?.progress?.percentText,
          nodeData?.timingText,
        ]
          .filter(Boolean)
          .join(" · "),
        style: { width: TASK_WIDTH, height: TASK_HEIGHT },
      };
    });
    return [...laneNodes, ...taskNodes];
  }, [geometry, model.lanes, model.selectedNode, byId]);

  const edges = useMemo<Edge[]>(() => {
    if (!geometry || geometry.error) return [];
    const routes = new Map(geometry.edges.map((edge) => [edge.id, edge]));
    return model.edges
      .filter((edge) => routes.has(edge.id))
      .map((edge) => {
        const route = routes.get(edge.id)!;
        const targetState = byId.get(edge.target)?.status || "unknown";
        const sourceState = byId.get(edge.source)?.status || "unknown";
        const unknownPath = [targetState, sourceState].some((status) =>
          ["skipped", "unknown", "pending"].includes(status),
        );
        const color = unknownPath
          ? "var(--muted)"
          : sourceState === "warn"
            ? STATUS_COLORS.warn
            : STATUS_COLORS[targetState] || STATUS_COLORS.unknown;
        return {
          ...edge,
          type: "routed",
          sourceHandle: route.sourceHandle,
          targetHandle: route.targetHandle,
          data: { route },
          animated: !unknownPath && !model.definition && Boolean(model.active) && targetState === "running",
          markerEnd: { type: MarkerType.ArrowClosed, color, width: 18, height: 18 },
          style: {
            stroke: color,
            strokeWidth: 2,
            ...(edge.optional ? { strokeDasharray: "5 4" } : {}),
          },
          labelStyle: { fill: "var(--muted)", fontSize: 11 },
          labelBgStyle: { fill: "var(--raised)" },
          interactionWidth: 12,
        };
      });
  }, [geometry, model.edges, model.definition, model.active, byId]);

  if (geometry?.error) {
    return <p className="cron-note muted">{model.ui.error}</p>;
  }
  if (!geometry) {
    return <p className="cron-note muted">{model.ui.loading}</p>;
  }

  return (
    <>
      <div className="cron-desktop-graph">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          nodesDraggable={false}
          nodesConnectable={false}
          edgesFocusable={false}
          onNodeClick={(_, node) => {
            if (node.type === "task") onSelect?.(node.id);
          }}
          onPaneClick={() => onSelect?.("")}
          minZoom={0.25}
          maxZoom={2}
          fitView
          fitViewOptions={{ padding: 0.06, maxZoom: 1 }}
          zoomOnScroll={false}
          preventScrolling={false}
          colorMode={model.theme || "dark"}
          proOptions={{ hideAttribution: false }}
        >
          <Background color="var(--line)" gap={20} size={1} />
          <Controls showInteractive={false} />
          <MiniMap
            position="top-right"
            ariaLabel={model.ui.minimap}
            style={{ width: 160, height: 100 }}
            nodeColor={(node) =>
              node.type === "lane"
                ? "transparent"
                : STATUS_COLORS[String((node.data as { status?: string })?.status || "unknown")] ||
                  STATUS_COLORS.unknown
            }
            nodeStrokeColor="var(--line)"
            maskColor="var(--cron-minimap-mask, rgba(0,0,0,.12))"
            pannable
            zoomable
          />
        </ReactFlow>
      </div>
      <div className="cron-mobile-stages">
        {model.lanes.map((lane) => (
          <section key={lane.id}>
            <h4>{lane.label}</h4>
            <div className="cron-mobile-stage-grid">
              {lane.nodes.map((node) => (
                <button
                  type="button"
                  key={node.id}
                  className="cron-mobile-stage-button"
                  data-cron-node={node.id}
                  aria-pressed={model.selectedNode === node.id}
                  onClick={() => onSelect?.(node.id)}
                >
                  <TaskNodeContent data={{ ...node.data, ports: [] }} />
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </>
  );
};

class CronGraphBoundary extends React.Component<
  { fallback: string; children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }
  render(): React.ReactNode {
    return this.state.failed ? <p className="cron-note muted">{this.props.fallback}</p> : this.props.children;
  }
}

export interface CronGraphCanvasProps {
  model: CronGraphModel;
  onSelect?: (nodeId: string) => void;
}

export const CronGraphCanvas: React.FC<CronGraphCanvasProps> = ({ model, onSelect }) => (
  <CronGraphBoundary fallback={model.ui.error}>
    <ReactFlowProvider>
      <CronGraphInner model={model} onSelect={onSelect} />
    </ReactFlowProvider>
  </CronGraphBoundary>
);

export default CronGraphCanvas;
