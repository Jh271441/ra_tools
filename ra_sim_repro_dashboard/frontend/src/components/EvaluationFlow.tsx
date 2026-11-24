import { FlowControls } from './FlowControls';
import { useId, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react';
import {
  Background,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './simulation-flow.css';
import {
  Activity,
  CheckCircle2,
  Clock3,
  Database,
  GitBranch,
  Layers3,
  Play,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Card, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import type { EvaluationBoard } from '../types/evaluation';

interface Stage {
  id: string;
  state: string;
  count?: number;
  detail: string;
}
interface StageData extends Record<string, unknown> {
  detailId: string;
  stage: Stage;
  selected: boolean;
  onSelect: (id: string) => void;
}
const icons = {
  collect: Database,
  prepare: Layers3,
  execute: Activity,
  verify: ShieldCheck,
  publish: CheckCircle2,
  rules: SlidersHorizontal,
  plan: GitBranch,
  manual: Play,
  cron: Clock3,
};
function StageCard({ stage, selected, onSelect, detailId }: StageData) {
  const { t, i18n } = useTranslation();
  const Icon = icons[stage.id as keyof typeof icons];
  return (
    <button
      type="button"
      data-stage-id={stage.id}
      className={`nodrag nopan sim-flow-node sim-flow-${stage.state}${selected ? ' is-selected' : ''}`}
      onClick={() => onSelect(stage.id)}
      aria-expanded={selected}
      aria-controls={detailId}
    >
      <span className="sim-flow-node-title">
        <Icon size={17} />
        <strong>{t(`evaluation.stage_${stage.id}`)}</strong>
      </span>
      <span className="sim-flow-count">
        {stage.count == null ? '—' : stage.count.toLocaleString(i18n.language)}
      </span>
      <span className="sim-flow-status">{t(`evaluation.${stage.detail}`)}</span>
    </button>
  );
}
function StageNode({ data }: NodeProps<Node<StageData>>) {
  return (
    <>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <Handle id="top-in" type="target" position={Position.Top} isConnectable={false} />
      <Handle id="bottom-in" type="target" position={Position.Bottom} isConnectable={false} />
      <StageCard {...data} />
      <Handle type="source" position={Position.Right} isConnectable={false} />
      <Handle id="top-out" type="source" position={Position.Top} isConnectable={false} />
      <Handle id="bottom-out" type="source" position={Position.Bottom} isConnectable={false} />
    </>
  );
}
const nodeTypes = { evaluationStage: StageNode };

function AdaptiveFit({ container }: { container: RefObject<HTMLDivElement> }) {
  const { fitView } = useReactFlow();
  useLayoutEffect(() => {
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => void fitView({ padding: 0.08, maxZoom: 1 }));
    });
    if (container.current) observer.observe(container.current);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [container, fitView]);
  return null;
}

export function EvaluationFlow({
  data,
  expected = false,
}: {
  data?: EvaluationBoard;
  expected?: boolean;
}) {
  const { t } = useTranslation();
  const detailId = useId();
  const section = useRef<HTMLDivElement>(null);
  const detail = useRef<HTMLDivElement>(null);
  const origin = useRef<HTMLElement | null>(null);
  const [compact, setCompact] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  useLayoutEffect(() => {
    const element = section.current!;
    const observer = new ResizeObserver(() => setCompact(element.clientWidth < 760));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const select = (id: string) => {
    origin.current = document.activeElement as HTMLElement;
    setSelected(id);
    if (compact)
      requestAnimationFrame(() =>
        detail.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }),
      );
  };
  const revision = data?.revision,
    plan = data?.plan;
  const busy = ['queued', 'running'].includes(data?.refresh.status || '');
  const active = data?.executions.find((e) =>
    ['preparing', 'running', 'verifying', 'submitting', 'submission_uncertain'].includes(e.status),
  );
  const stages: Stage[] = [
    {
      id: 'collect',
      state: busy
        ? 'active'
        : data?.refresh.status === 'failed'
          ? 'blocked'
          : revision
            ? 'complete'
            : 'waiting',
      count: revision?.source_count,
      detail: busy ? 'syncing' : revision ? 'reconciled' : 'await_sync',
    },
    {
      id: 'prepare',
      state: plan?.prepare_count ? 'warning' : revision ? 'complete' : 'waiting',
      count: plan?.prepare_count,
      detail: plan?.prepare_count ? 'await_manual' : 'ready',
    },
    {
      id: 'execute',
      state: active
        ? active.status === 'submission_uncertain'
          ? 'blocked'
          : 'active'
        : revision?.metrics.available
          ? 'complete'
          : 'waiting',
      count: revision?.metrics.covered,
      detail: active ? 'executing' : plan?.gap_count ? 'await_manual' : 'reuse',
    },
    {
      id: 'verify',
      state: revision?.metrics.available ? 'complete' : revision ? 'warning' : 'waiting',
      count: revision?.metrics.missing_results,
      detail: revision?.metrics.available ? 'verified' : 'coverage_pending',
    },
    {
      id: 'publish',
      state: revision?.metrics.available ? 'complete' : 'waiting',
      detail: revision?.metrics.available ? 'published' : 'partial_only',
    },
    { id: 'rules', state: revision ? 'complete' : 'waiting', detail: 'versioned_rules' },
    {
      id: 'plan',
      state: plan?.id ? 'complete' : 'waiting',
      count: plan?.gap_count,
      detail: 'plan_only',
    },
    {
      id: 'manual',
      state: plan?.review_count ? 'blocked' : active ? 'active' : 'waiting',
      count: plan?.review_count,
      detail: plan?.review_count ? 'review_required' : 'await_manual',
    },
    {
      id: 'cron',
      state: data?.cron.enabled ? 'complete' : 'waiting',
      detail: data?.cron.enabled ? 'cron_enabled' : 'cron_paused',
    },
  ];
  const nodes: Node<StageData>[] = stages.map((stage, i) => ({
    id: stage.id,
    type: 'evaluationStage',
    position:
      i < 5 ? { x: i * 240, y: 24 } : { x: stage.id === 'cron' ? 0 : (i - 4) * 240, y: 258 },
    data: {
      detailId,
      stage: expected ? { ...stage, state: 'waiting' } : stage,
      selected: selected === stage.id,
      onSelect: select,
    },
    draggable: false,
    focusable: false,
    selectable: false,
  }));
  const edges = useMemo(
    () =>
      [
        ['prepare', 'execute'],
        ['execute', 'verify'],
        ['verify', 'publish'],
        ['collect', 'rules'],
        ['rules', 'plan'],
        ['plan', 'manual'],
        ['manual', 'prepare'],
        ['plan', 'verify'],
        ['cron', 'collect'],
      ].map(([source, target]) => ({
        id: `${source}-${target}`,
        source,
        target,
        ...(source === 'cron' || source === 'manual' || (target === 'verify' && source === 'plan')
          ? { sourceHandle: 'top-out', targetHandle: 'bottom-in' }
          : target === 'rules'
            ? { sourceHandle: 'bottom-out', targetHandle: 'top-in' }
            : {}),
        type: 'smoothstep',
        style: {
          stroke: 'hsl(var(--muted-foreground))',
          strokeWidth: 1.5,
          strokeDasharray:
            ['cron', 'rules', 'plan', 'manual'].includes(source) || target === 'rules'
              ? '5 5'
              : undefined,
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: 'hsl(var(--muted-foreground))' },
      })),
    [],
  );
  const selectedStage = stages.find((s) => s.id === selected);
  const close = () => {
    setSelected(null);
    (origin.current?.isConnected
      ? origin.current
      : section.current?.querySelector<HTMLElement>(`[data-stage-id="${selected}"]`)
    )?.focus({ preventScroll: true });
  };
  return (
    <div ref={section} className="min-w-0">
      <Card className="sim-flow">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitBranch size={18} />
            {t(expected ? 'evaluation.expected_flow' : 'simFlow.title')}
          </CardTitle>
          <p className="text-sm text-muted-foreground">{t('evaluation.manual_policy')}</p>
        </CardHeader>
        {!compact ? (
          <div className="sim-flow-desktop has-label-branch" style={{ height: 470 }}>
            <ReactFlowProvider>
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                fitView
                fitViewOptions={{ padding: 0.08, maxZoom: 1 }}
                minZoom={0.4}
                maxZoom={1.6}
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable={false}
                zoomOnScroll={false}
                preventScrolling={false}
              >
                <Background gap={18} size={1} />
                <FlowControls />
                <AdaptiveFit container={section} />
              </ReactFlow>
            </ReactFlowProvider>
          </div>
        ) : (
          <ol className="sim-flow-mobile">
            {[
              'cron',
              'collect',
              'rules',
              'plan',
              'manual',
              'prepare',
              'execute',
              'verify',
              'publish',
            ].map((id, i) => {
              const stage = stages.find((s) => s.id === id)!;
              return (
                <li key={stage.id}>
                  <span className="sim-flow-step">{i + 1}</span>
                  <StageCard
                    detailId={detailId}
                    stage={stage}
                    selected={stage.id === selected}
                    onSelect={select}
                  />
                </li>
              );
            })}
          </ol>
        )}
        {selectedStage && (
          <div
            ref={detail}
            id={detailId}
            className="sim-flow-detail"
            onKeyDown={(e) => {
              if (e.key === 'Escape') close();
            }}
          >
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold">{t(`evaluation.stage_${selected}`)}</h3>
              <Button
                variant="ghost"
                size="icon"
                className="h-11 w-11"
                aria-label={t('simFlow.closeDetails')}
                onClick={close}
              >
                <X size={17} />
              </Button>
            </div>
            <p className="mt-2 break-words text-sm text-muted-foreground">
              {t(`evaluation.detail_${selected}`)}
            </p>
          </div>
        )}
      </Card>
    </div>
  );
}
