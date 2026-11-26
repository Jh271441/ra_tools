import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { queryOptions, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  formatCstTime,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import {
  ComparisonDiffView,
  comparisonConfigText,
  PromptMetaBadge,
  PromptMetaLike,
  RunSnapshotLike,
  RunSnapshotView,
} from "../components/comparison/ComparisonDiffView";
import { CASE_PAGE_SIZES, Pagination } from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

const LABELS = ["误触发", "正确触发", "无需协助"] as const;
const MODEL_LABELS = ["误触发", "正确触发", "无需协助", "真实卡住"] as const;
const RUN_TRANSITIONS = ["ALL", "P2F", "F2P", "F2F", "P2P"] as const;
const ROUTING_VALUES = ["泊车", "直行", "左转", "右转", "掉头"] as const;
const LANE_CHANGE_VALUES = ["非变道", "变道"] as const;

export interface InputFilterCondition {
  axis: "routing" | "lane_change";
  operator: "any" | "all" | "none";
  values: string[];
}

export interface ComparisonInputFilter {
  version: 1;
  run: "candidate" | "baseline" | "either";
  relation: "all" | "any";
  conditions: InputFilterCondition[];
}

interface ModelRunItem {
  id: string;
  name?: string | null;
  source_name?: string | null;
  created_at?: string | null;
  baseline_prediction_count?: number | null;
  prediction_count?: number | null;
  baseline_scope?: string | null;
}

interface MatrixRow {
  gt_label: string;
  cells?: Record<string, number>;
  total: number;
  accuracy: number;
}

interface SideSummary {
  accuracy?: number;
  correct_count?: number;
  total_count?: number;
  prediction_count?: number;
  columns?: string[];
  rows?: MatrixRow[];
}

interface PredictionSide {
  model_label?: string | null;
  model_confidence?: number | null;
  model_reason?: string | null;
  correct?: boolean;
}

interface ExtraInputAxis {
  label?: string;
  status?: string;
  counts?: Record<string, number>;
}

interface ExtraInputSide {
  available?: boolean;
  axes?: Record<string, ExtraInputAxis>;
  frames?: Array<{
    offset_ms?: number;
    axes?: Record<string, { label?: string; value?: string }>;
  }>;
}

interface SceneReviewInfo {
  tags?: string[];
  source?: string;
  author?: string;
  created_at?: string;
}

interface ComparisonCaseItem {
  issue_id: string;
  gt_label?: string | null;
  baseline_scope?: string | null;
  transition?: string | null;
  baseline?: PredictionSide | null;
  candidate?: PredictionSide | null;
  extra_inputs?: {
    baseline?: ExtraInputSide | null;
    candidate?: ExtraInputSide | null;
  } | null;
  scene_review?: SceneReviewInfo | null;
}

interface ComparisonPayload {
  view_mode?: "single" | "pairwise" | string;
  baseline_run?: RunSnapshotLike | null;
  candidate_run?: RunSnapshotLike | null;
  summary?: {
    baseline?: SideSummary;
    candidate?: SideSummary;
    accuracy_delta?: number;
    label_changed_count?: number;
    total_count?: number;
    transition_counts?: Record<string, number>;
  };
  items?: ComparisonCaseItem[];
  total?: number;
  page?: number;
  page_count?: number;
  page_size?: number;
}

interface CaseInputSide {
  prompt?: PromptMetaLike;
  input?: { available?: boolean; config?: Record<string, unknown> | null };
  media?: { available?: boolean; notice?: string; count?: number; items?: unknown[] };
  extra_inputs?: ExtraInputSide | null;
  run_reference?: RunSnapshotLike;
}

interface CaseInputsPayload {
  baseline?: CaseInputSide | null;
  candidate?: CaseInputSide | null;
  scene_review?: SceneReviewInfo | null;
}

interface CaseMediaFrame {
  url?: string;
  offset_ms?: number;
  offset_s?: number;
  time_s?: number;
  t?: number;
}

interface CaseMediaPayload {
  assets?: { frames?: CaseMediaFrame[] };
  camera?: { frames?: CaseMediaFrame[] };
}

interface ComparisonRouteState {
  baselineRunId: string;
  candidateRunId: string;
  transition: string;
  gtLabel: string;
  baselineLabel: string;
  candidateLabel: string;
  labelChange: string;
  inputFilter: ComparisonInputFilter;
  search: string;
  page: number;
  pageSize: number;
}

interface LegacyWindowBridge {
  state?: {
    config?: {
      review_tag_catalog?: Array<{
        key?: string;
        label?: string;
        section?: string;
        group?: string;
      }>;
    };
    runComparison?: {
      baselineRunId?: string;
      candidateRunId?: string;
      data?: unknown;
      page?: number;
      pageSize?: number;
    };
  };
  showToast?: (message: string, isError?: boolean) => void;
  openComparisonMedia?: (issueId: string, kind: "bev" | "camera") => Promise<void>;
  comparisonImageMedia?: (issueId: string, kind?: string) => Promise<CaseMediaPayload>;
  applyInferredBaselinesFromRun?: (run: unknown, options?: { reason?: string }) => Promise<boolean> | boolean;
  heroFrameIndex?: (frames: CaseMediaFrame[]) => number;
  mediaFrameOffsetMs?: (frame: CaseMediaFrame) => number;
  safeSameOriginAssetUrl?: (url?: string) => string;
  __RA_COMPARISON_BRIDGE__?: {
    getPageForMedia: () => ComparisonPayload | null;
    openCaseDialog: (issueId: string, preserveTab?: boolean) => void;
    isCaseDialogOpen: () => boolean;
    stepPageForMedia: (nextPage: number) => Promise<ComparisonCaseItem[]>;
  };
}

function getLegacyWindow(): LegacyWindowBridge {
  return window as unknown as LegacyWindowBridge;
}

function comparisonPageQuery(route: ComparisonRouteState, baselines: string, page = route.page) {
  const inputFilter = JSON.stringify(route.inputFilter);
  return queryOptions({
    queryKey: [
      "model-run-comparison",
      baselines,
      route.baselineRunId,
      route.candidateRunId,
      route.transition,
      route.gtLabel,
      route.baselineLabel,
      route.candidateLabel,
      route.labelChange,
      inputFilter,
      route.search,
      page,
      route.pageSize,
    ],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        baseline_run_id: route.baselineRunId,
        candidate_run_id: route.candidateRunId,
        transition: route.transition,
        gt_label: route.gtLabel,
        baseline_label: route.baselineLabel,
        candidate_label: route.candidateLabel,
        label_change: route.labelChange,
        input_filter: inputFilter,
        q: route.search,
        page: String(page),
        page_size: String(route.pageSize),
      });
      if (baselines) params.set("baselines", baselines);
      return apiRequest<ComparisonPayload>(`/api/model-run-comparison?${params.toString()}`, { signal });
    },
  });
}

function defaultInputFilter(): ComparisonInputFilter {
  return { version: 1, run: "candidate", relation: "all", conditions: [] };
}

function parseInputFilter(raw: unknown): ComparisonInputFilter {
  try {
    const parsed = typeof raw === "string" ? JSON.parse(raw || "{}") : raw;
    if (parsed && typeof parsed === "object" && (parsed as { version?: unknown }).version === 1) {
      const p = parsed as Partial<ComparisonInputFilter>;
      const run = p.run === "baseline" || p.run === "either" ? p.run : "candidate";
      const relation = p.relation === "any" ? "any" : "all";
      const conditions: InputFilterCondition[] = Array.isArray(p.conditions)
        ? p.conditions
            .filter(
              (item): item is InputFilterCondition =>
                Boolean(item) &&
                (item.axis === "routing" || item.axis === "lane_change") &&
                Array.isArray(item.values) &&
                item.values.length > 0,
            )
            .map((item) => ({
              axis: item.axis,
              operator:
                item.operator === "all" || item.operator === "none" ? item.operator : "any",
              values: item.values.map(String),
            }))
        : [];
      return { version: 1, run, relation, conditions };
    }
  } catch {
    // fallback to empty filter
  }
  return defaultInputFilter();
}

function parseComparisonRouteFromLocation(): ComparisonRouteState {
  const params = new URLSearchParams(window.location.search);
  const transition = String(params.get("transition") || "ALL").toUpperCase();
  const gtLabel = String(params.get("gt") || "ALL");
  const baselineLabel = String(params.get("baseline_label") || "ALL");
  const candidateLabel = String(params.get("candidate_label") || "ALL");
  const labelChange = String(params.get("label_change") || "ALL").toUpperCase();
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(params.get("page_size") || "10", 10);
  return {
    baselineRunId: params.get("baseline_run") || params.get("baseline") || "",
    candidateRunId: params.get("candidate_run") || params.get("new") || "",
    transition: (RUN_TRANSITIONS as readonly string[]).includes(transition) ? transition : "ALL",
    gtLabel: ["ALL", ...LABELS].includes(gtLabel) ? gtLabel : "ALL",
    baselineLabel: ["ALL", ...MODEL_LABELS, "NONE"].includes(baselineLabel)
      ? baselineLabel
      : "ALL",
    candidateLabel: ["ALL", ...MODEL_LABELS, "NONE"].includes(candidateLabel)
      ? candidateLabel
      : "ALL",
    labelChange: ["ALL", "CHANGED", "UNCHANGED"].includes(labelChange) ? labelChange : "ALL",
    inputFilter: parseInputFilter(params.get("input_filter") || ""),
    search: String(params.get("q") || "").trim().slice(0, 128),
    page: Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1,
    pageSize: (CASE_PAGE_SIZES as readonly number[]).includes(rawPageSize) ? rawPageSize : 10,
  };
}

function normalizeRunIds(
  runs: ModelRunItem[],
  aliases: Record<string, string> | undefined,
  baselineRunId: string,
  candidateRunId: string,
  repairCoverage: boolean,
): { baselineRunId: string; candidateRunId: string } {
  const available = runs.filter((run) => Boolean(run?.id));
  if (!available.length) return { baselineRunId, candidateRunId };
  const covered = available.filter((run) => Number(run.baseline_prediction_count || 0) > 0);
  const ids = new Set(available.map((run) => String(run.id)));
  const resolveRunId = (value: string) => {
    if (!value || ids.has(value)) return value;
    const alias = aliases?.[value];
    if (alias && ids.has(alias)) return alias;
    const named = available.filter((run) => run.name === value);
    return named.length === 1 ? named[0].id : "";
  };
  const hadSelection = Boolean(baselineRunId || candidateRunId);
  let nextBase = resolveRunId(baselineRunId);
  let nextCand = resolveRunId(candidateRunId);

  if (!hadSelection) {
    nextCand = String(covered[0]?.id || available[0]?.id || "");
    nextBase = String(
      covered[1]?.id || available.find((run) => String(run.id) !== nextCand)?.id || "",
    );
  }
  if (nextBase && nextBase === nextCand && available.length > 1) {
    nextBase = String(
      covered.find((run) => String(run.id) !== nextCand)?.id ||
        available.find((run) => String(run.id) !== nextCand)?.id ||
        "",
    );
  }
  const selectedCoverage = available
    .filter((run) => [nextBase, nextCand].includes(String(run.id)))
    .reduce((sum, run) => sum + Number(run.baseline_prediction_count || 0), 0);

  if (repairCoverage && selectedCoverage <= 0 && covered.length) {
    if (nextBase && !nextCand) {
      nextBase = String(covered[0].id);
    } else if (nextCand && !nextBase) {
      nextCand = String(covered[0].id);
    } else {
      nextCand = String(covered[0].id);
      nextBase = String(
        covered[1]?.id || available.find((run) => String(run.id) !== nextCand)?.id || "",
      );
    }
  }
  return { baselineRunId: nextBase, candidateRunId: nextCand };
}

function modelLabelMatchesGt(modelLabel: string, gtLabel: string): boolean {
  if (!modelLabel || !gtLabel) return false;
  if (modelLabel === "真实卡住") {
    return gtLabel === "正确触发" || gtLabel === "无需协助";
  }
  return modelLabel === gtLabel;
}

function percentage(value: number | null | undefined): string {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function comparisonTransitionText(value: string | null | undefined, lang: UiLanguage): string {
  const key = String(value || "");
  const map: Record<string, [string, string]> = {
    P2F: ["P2F · 退化", "P2F · Regression"],
    F2P: ["F2P · 改善", "F2P · Improvement"],
    F2F: ["F2F · 仍错误", "F2F · Still wrong"],
    P2P: ["P2P · 均正确", "P2P · Both correct"],
  };
  const pair = map[key];
  return pair ? bilingual(lang, pair[0], pair[1]) : key;
}

function extraInputsEqual(left?: ExtraInputSide | null, right?: ExtraInputSide | null): boolean {
  const comparable = (summary?: ExtraInputSide | null) =>
    Object.fromEntries(
      Object.entries(summary?.axes || {})
        .sort()
        .map(([axis, val]) => [
          axis,
          {
            status: val.status,
            counts: Object.fromEntries(Object.entries(val.counts || {}).sort()),
          },
        ]),
    );
  return JSON.stringify(comparable(left)) === JSON.stringify(comparable(right));
}

function resolveHeroFrameIndex(frames: CaseMediaFrame[]): number {
  const win = getLegacyWindow();
  if (typeof win.heroFrameIndex === "function") return win.heroFrameIndex(frames);
  if (!frames.length) return 0;
  let bestIdx = 0;
  let bestDist = Infinity;
  frames.forEach((f, idx) => {
    const ms = resolveFrameOffsetMs(f);
    if (Number.isFinite(ms)) {
      const d = Math.abs(ms);
      if (d < bestDist) {
        bestDist = d;
        bestIdx = idx;
      }
    }
  });
  return bestIdx;
}

function resolveFrameOffsetMs(frame: CaseMediaFrame): number {
  const win = getLegacyWindow();
  if (typeof win.mediaFrameOffsetMs === "function") return win.mediaFrameOffsetMs(frame);
  if (Number.isFinite(Number(frame.offset_ms))) return Number(frame.offset_ms);
  if (Number.isFinite(Number(frame.offset_s))) return Number(frame.offset_s) * 1000;
  if (Number.isFinite(Number(frame.time_s))) return Number(frame.time_s) * 1000;
  if (Number.isFinite(Number(frame.t))) return Number(frame.t) * 1000;
  return Number.NaN;
}

function safeAssetUrl(url?: string): string {
  const win = getLegacyWindow();
  if (typeof win.safeSameOriginAssetUrl === "function") return win.safeSameOriginAssetUrl(url);
  if (!url) return "";
  try {
    const parsed = new URL(url, window.location.origin);
    if (parsed.origin !== window.location.origin) return "";
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return "";
  }
}

const ExtraInputsView: React.FC<{
  extraInputs?: ComparisonCaseItem["extra_inputs"];
  dialog?: boolean;
  lang: UiLanguage;
}> = ({ extraInputs, dialog = false, lang }) => {
  const baseline = extraInputs?.baseline || {};
  const candidate = extraInputs?.candidate || {};
  if (!baseline.available && !candidate.available) {
    return dialog ? null : <span className="muted">{bilingual(lang, "未保存", "Not saved")}</span>;
  }

  const renderSummary = (summary: ExtraInputSide) =>
    Object.entries(summary.axes || {}).map(([axisKey, axis]) => {
      const chips = Object.entries(axis.counts || {}).filter(([, count]) => Number(count) > 0);
      if (!chips.length) {
        if (dialog) return null;
        return (
          <div className="comparison-extra-axis" key={axisKey}>
            <small>{axis.label || ""}</small>
            <span className="muted">
              {bilingual(lang, "部分输入未保存", "Partial inputs not saved")}
            </span>
          </div>
        );
      }
      return (
        <div className="comparison-extra-axis" key={axisKey}>
          <small>{axis.label || ""}</small>
          <div>
            {chips.map(([label, count]) => (
              <span className="comparison-extra-chip" key={label}>
                {label} {Number(count)}
                {bilingual(lang, "帧", "f")}
              </span>
            ))}
          </div>
        </div>
      );
    });

  if (baseline.available && candidate.available && extraInputsEqual(baseline, candidate)) {
    return <div className="comparison-extra-side">{renderSummary(candidate)}</div>;
  }
  return (
    <>
      {baseline.available ? (
        <div className="comparison-extra-side">
          <b>{bilingual(lang, "基线", "Baseline")}</b>
          {renderSummary(baseline)}
        </div>
      ) : null}
      {candidate.available ? (
        <div className="comparison-extra-side">
          <b>{bilingual(lang, "新 Run", "Candidate")}</b>
          {renderSummary(candidate)}
        </div>
      ) : null}
    </>
  );
};

const SceneTagsView: React.FC<{ review?: SceneReviewInfo | null; lang: UiLanguage }> = ({
  review,
  lang,
}) => {
  const tags = Array.isArray(review?.tags) ? review.tags : [];
  if (!tags.length) return null;
  const catalog = getLegacyWindow().state?.config?.review_tag_catalog || [];
  const byKey = new Map(catalog.map((item) => [String(item.key || ""), item]));
  const tagLabel = (key: string) => byKey.get(key)?.label || key;
  const sourceMap: Record<string, string> = {
    candidate: bilingual(lang, "新 Run Review", "Candidate Run Review"),
    unbound: bilingual(lang, "未绑定 Run 的历史 Review", "Historical unbound Review"),
    other_run: bilingual(lang, "其他 Run 的最新 Review", "Latest Review from other Run"),
  };
  const header = [
    sourceMap[String(review?.source || "")] || "Review",
    review?.author,
    review?.created_at ? formatCstTime(review.created_at, lang) : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const full = `${tags.map(tagLabel).join(" · ")}\n${header}`;
  return (
    <div className="comparison-scene-tags-line" tabIndex={0} title={full}>
      {tags.map((key) => {
        const item = byKey.get(key);
        return (
          <span
            className="comparison-scene-tag"
            key={key}
            data-tag-section={item?.section || ""}
            data-tag-group={item?.group || ""}
          >
            {tagLabel(key)}
          </span>
        );
      })}
    </div>
  );
};

export interface RunComparisonPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
}

export const RunComparisonPage: React.FC<RunComparisonPageProps> = ({
  active,
  lang,
  selectedBaselines,
}) => {
  const queryClient = useQueryClient();
  const baselinesParam = selectedBaselines.join(",");
  const [route, setRoute] = useState<ComparisonRouteState>(() => parseComparisonRouteFromLocation());
  const [searchDraft, setSearchDraft] = useState<string>(route.search);
  const searchTimerRef = useRef<number | null>(null);
  const prevBaselinesRef = useRef<string>(baselinesParam);

  // Extra input popover state
  const [inputPopoverOpen, setInputPopoverOpen] = useState(false);
  const [inputDraft, setInputDraft] = useState<ComparisonInputFilter>(route.inputFilter);
  const [popoverStyle, setPopoverStyle] = useState<React.CSSProperties>({});
  const inputFilterRef = useRef<HTMLDivElement | null>(null);
  const inputSummaryBtnRef = useRef<HTMLButtonElement | null>(null);
  const inputPanelRef = useRef<HTMLDivElement | null>(null);

  // Case Compare Dialog state
  const [dialogIssueId, setDialogIssueId] = useState<string>("");
  const [dialogTab, setDialogTab] = useState<"output" | "prompt" | "config">("output");
  const [bevBrokenIds, setBevBrokenIds] = useState<Record<string, boolean>>({});
  const [dialogBevMissing, setDialogBevMissing] = useState(false);
  const [dialogBevTime, setDialogBevTime] = useState("BEV · t = 0s");
  const [dialogCamTime, setDialogCamTime] = useState("Camera");
  const [dialogCamUrl, setDialogCamUrl] = useState("");
  const [dialogCamMissing, setDialogCamMissing] = useState(true);
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const dialogScrollRef = useRef<HTMLDivElement | null>(null);
  const navTailRef = useRef<Promise<void>>(Promise.resolve());

  const syncUrl = useCallback(
    (next: ComparisonRouteState, mode: "replace" | "push" = "replace") => {
      if (!active) return;
      const url = new URL(withWorkbenchBase("/run-comparison"), window.location.origin);
      if (baselinesParam) url.searchParams.set("baselines", baselinesParam);
      if (next.baselineRunId) url.searchParams.set("baseline_run", next.baselineRunId);
      if (next.candidateRunId) url.searchParams.set("candidate_run", next.candidateRunId);
      if (next.transition && next.transition !== "ALL") {
        url.searchParams.set("transition", next.transition);
      }
      if (next.gtLabel && next.gtLabel !== "ALL") url.searchParams.set("gt", next.gtLabel);
      if (next.baselineLabel && next.baselineLabel !== "ALL") {
        url.searchParams.set("baseline_label", next.baselineLabel);
      }
      if (next.candidateLabel && next.candidateLabel !== "ALL") {
        url.searchParams.set("candidate_label", next.candidateLabel);
      }
      if (next.labelChange && next.labelChange !== "ALL") {
        url.searchParams.set("label_change", next.labelChange);
      }
      if (next.search) url.searchParams.set("q", next.search);
      if (next.inputFilter.conditions.length) {
        url.searchParams.set("input_filter", JSON.stringify(next.inputFilter));
      }
      if (next.page > 1) url.searchParams.set("page", String(next.page));
      if (next.pageSize !== 10) url.searchParams.set("page_size", String(next.pageSize));
      const target = `${url.pathname}${url.search}`;
      if (`${window.location.pathname}${window.location.search}` !== target) {
        window.history[mode === "push" ? "pushState" : "replaceState"](
          { page: "comparison" },
          "",
          target,
        );
      }
    },
    [active, baselinesParam],
  );

  // Sync from browser back/forward
  useEffect(() => {
    if (!active) return;
    const onPopState = () => {
      const parsed = parseComparisonRouteFromLocation();
      setRoute(parsed);
      setSearchDraft(parsed.search);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [active]);

  // Fetch all runs for the current baselines
  const runsQuery = useQuery<{
    items?: ModelRunItem[];
    runs?: ModelRunItem[];
    aliases?: Record<string, string>;
  }>({
    queryKey: ["comparison-model-runs", baselinesParam],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({ page: "1", page_size: "200" });
      if (baselinesParam) qs.set("baselines", baselinesParam);
      return apiRequest(`/api/model-runs?${qs.toString()}`, { signal });
    },
    enabled: active,
    staleTime: 20_000,
  });

  const modelRuns = useMemo<ModelRunItem[]>(
    () => runsQuery.data?.items || runsQuery.data?.runs || [],
    [runsQuery.data],
  );
  const runAliases = runsQuery.data?.aliases;
  const selectedRunIds = useMemo(
    () => [route.baselineRunId, route.candidateRunId].filter(Boolean),
    [route.baselineRunId, route.candidateRunId],
  );
  const selectedRuns = useMemo(
    () =>
      selectedRunIds
        .map((id) => modelRuns.find((r) => String(r.id) === String(id)))
        .filter((r): r is ModelRunItem => Boolean(r)),
    [selectedRunIds, modelRuns],
  );
  // Wait for the catalog before sending comparison requests with IDs from a bookmark.
  const needsRunResolution = selectedRuns.length !== selectedRunIds.length;
  const selectionValid =
    selectedRunIds.length > 0 &&
    new Set(selectedRunIds).size === selectedRunIds.length &&
    !needsRunResolution;

  // Reconcile the selection when the catalog, dataset or an unresolved bookmark changes.
  useEffect(() => {
    if (!active || !modelRuns.length) return;
    const datasetChanged = prevBaselinesRef.current !== baselinesParam;
    prevBaselinesRef.current = baselinesParam;
    setRoute((prev) => {
      const normalized = normalizeRunIds(
        modelRuns,
        runAliases,
        prev.baselineRunId,
        prev.candidateRunId,
        true,
      );
      if (
        normalized.baselineRunId === prev.baselineRunId &&
        normalized.candidateRunId === prev.candidateRunId &&
        !datasetChanged
      ) {
        return prev;
      }
      const next: ComparisonRouteState = {
        ...prev,
        baselineRunId: normalized.baselineRunId,
        candidateRunId: normalized.candidateRunId,
        page: datasetChanged ? 1 : prev.page,
      };
      syncUrl(next, "replace");
      return next;
    });
  }, [active, modelRuns, runAliases, baselinesParam, needsRunResolution, syncUrl]);

  const comparisonQuery = useQuery({
    ...comparisonPageQuery(route, baselinesParam),
    enabled: active && selectionValid,
    placeholderData: (prev) => prev,
  });
  const loadError = comparisonQuery.error || (modelRuns.length === 0 ? runsQuery.error : null);

  const payload = comparisonQuery.data || null;
  const hasPayload = Boolean(payload?.summary);
  const single = payload?.view_mode === "single";

  // Preserve the classic route projection for Run Collections.
  useEffect(() => {
    const win = getLegacyWindow();
    if (!win.state) return;
    if (!win.state.runComparison) win.state.runComparison = {};
    win.state.runComparison.baselineRunId = route.baselineRunId;
    win.state.runComparison.candidateRunId = route.candidateRunId;
    win.state.runComparison.page = route.page;
    win.state.runComparison.pageSize = route.pageSize;
    if (payload) win.state.runComparison.data = payload;
  }, [payload, route.baselineRunId, route.candidateRunId, route.page, route.pageSize]);

  // Enforce single-run input filter run side
  useEffect(() => {
    if (!single || !payload) return;
    const forcedRun = payload.candidate_run ? "candidate" : "baseline";
    if (route.inputFilter.run !== forcedRun) {
      setRoute((prev) => ({
        ...prev,
        inputFilter: { ...prev.inputFilter, run: forcedRun },
      }));
    }
  }, [single, payload, route.inputFilter.run]);

  // Case inputs query when Case Compare Dialog is open
  const caseInputsQuery = useQuery<CaseInputsPayload>({
    queryKey: [
      "comparison-case-inputs",
      dialogIssueId,
      baselinesParam,
      payload?.baseline_run?.id || "",
      payload?.candidate_run?.id || "",
    ],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ baselines: baselinesParam || "" });
      if (payload?.baseline_run?.id) params.set("baseline_run_id", String(payload.baseline_run.id));
      if (payload?.candidate_run?.id) params.set("candidate_run_id", String(payload.candidate_run.id));
      return apiRequest<CaseInputsPayload>(
        `/api/model-run-comparison/cases/${encodeURIComponent(dialogIssueId)}/inputs?${params.toString()}`,
        { signal },
      );
    },
    enabled: Boolean(active && dialogIssueId && payload),
  });

  // Sync native <dialog> open/close with dialogIssueId
  useEffect(() => {
    const dlg = dialogRef.current;
    if (!dlg) return;
    if (dialogIssueId) {
      if (!dlg.open) {
        try {
          dlg.showModal();
        } catch {
          // jsdom fallback
          dlg.setAttribute("open", "");
        }
      }
      if (dialogScrollRef.current) dialogScrollRef.current.scrollTop = 0;
    } else if (dlg.open) {
      dlg.close();
    }
  }, [dialogIssueId]);

  // Load BEV & Camera preview timestamps/image when dialogIssueId changes
  useEffect(() => {
    if (!dialogIssueId) return;
    let cancelled = false;
    setDialogBevMissing(false);
    setDialogCamMissing(true);
    setDialogCamUrl("");
    setDialogBevTime(bilingual(lang, "BEV · 时间读取中…", "BEV · Loading time…"));
    setDialogCamTime(bilingual(lang, "Camera · 加载中…", "Camera · Loading…"));

    const fetchMedia = async () => {
      try {
        const win = getLegacyWindow();
        const data: CaseMediaPayload =
          typeof win.comparisonImageMedia === "function"
            ? await win.comparisonImageMedia(dialogIssueId, "images")
            : await apiRequest<CaseMediaPayload>(
                `/api/cases/${encodeURIComponent(dialogIssueId)}/media?kind=images`,
              );
        if (cancelled) return;
        const bevFrames = data.assets?.frames || [];
        const camFrames = data.camera?.frames || [];
        const bevFrame = bevFrames[resolveHeroFrameIndex(bevFrames)];
        if (!bevFrame) {
          setDialogBevTime(bilingual(lang, "BEV · 未保存", "BEV · Not saved"));
        } else {
          const ms = resolveFrameOffsetMs(bevFrame);
          setDialogBevTime(
            Number.isFinite(ms)
              ? `BEV · t = ${ms / 1000}s${ms === 0 ? "" : bilingual(lang, "（最近帧）", " (nearest)")}`
              : bilingual(lang, "BEV · 时间未保存", "BEV · Time unavailable"),
          );
        }
        const camFrame = camFrames[resolveHeroFrameIndex(camFrames)];
        if (!camFrame) {
          setDialogCamTime(bilingual(lang, "Camera · 未保存", "Camera · Not saved"));
          setDialogCamMissing(true);
        } else {
          const ms = resolveFrameOffsetMs(camFrame);
          setDialogCamTime(
            Number.isFinite(ms)
              ? `Camera · t = ${ms / 1000}s${ms === 0 ? "" : bilingual(lang, "（最近帧）", " (nearest)")}`
              : bilingual(lang, "Camera · 时间未保存", "Camera · Time unavailable"),
          );
          const safe = safeAssetUrl(camFrame.url);
          if (safe) {
            setDialogCamUrl(safe);
            setDialogCamMissing(false);
          } else {
            setDialogCamMissing(true);
          }
        }
      } catch {
        if (!cancelled) {
          setDialogCamTime(bilingual(lang, "Camera · 加载失败", "Camera · Failed"));
        }
      }
    };
    void fetchMedia();
    return () => {
      cancelled = true;
    };
  }, [dialogIssueId, lang]);

  // Step to prev/next Case inside Case Compare Modal (including crossing pages!)
  const stepDialogCase = useCallback(
    async (delta: -1 | 1) => {
      if (!dialogIssueId || !payload) return;
      const items = payload.items || [];
      const index = items.findIndex((item) => String(item.issue_id) === String(dialogIssueId));
      if (index < 0) return;
      const immediate = items[index + delta];
      if (immediate) {
        setDialogIssueId(String(immediate.issue_id));
        return;
      }
      const nextPage = Number(payload.page || 1) + delta;
      const pageCount = Number(payload.page_count || 1);
      if (nextPage < 1 || nextPage > pageCount) {
        getLegacyWindow().showToast?.(
          delta < 0
            ? bilingual(lang, "已经是第一个 Case", "Already at the first Case")
            : bilingual(lang, "已经是最后一个 Case", "Already at the last Case"),
        );
        return;
      }
      const nextPayload = await queryClient.fetchQuery(
        comparisonPageQuery(route, baselinesParam, nextPage),
      );
      const nextItems = nextPayload.items || [];
      const targetItem = delta > 0 ? nextItems[0] : nextItems[nextItems.length - 1];
      setRoute((prev) => {
        const nextRoute = { ...prev, page: nextPage };
        syncUrl(nextRoute, "replace");
        return nextRoute;
      });
      if (targetItem) {
        setDialogIssueId(String(targetItem.issue_id));
      }
    },
    [dialogIssueId, payload, lang, route, baselinesParam, queryClient, syncUrl],
  );

  // Register bridge for classic #mediaDialog ↑/↓ stepping
  useEffect(() => {
    if (!active) return;
    const win = getLegacyWindow();
    let mediaPage = comparisonQuery.isPlaceholderData ? null : payload;
    win.__RA_COMPARISON_BRIDGE__ = {
      getPageForMedia: () => mediaPage,
      openCaseDialog: (issueId: string, preserveTab = false) => {
        if (!preserveTab) setDialogTab("output");
        setDialogIssueId(String(issueId));
      },
      isCaseDialogOpen: () => Boolean(dialogIssueId),
      stepPageForMedia: async (nextPage: number) => {
        const nextPayload = await queryClient.fetchQuery(
          comparisonPageQuery(route, baselinesParam, nextPage),
        );
        mediaPage = nextPayload;
        setRoute((prev) => {
          const nextRoute = { ...prev, page: nextPage };
          syncUrl(nextRoute, "replace");
          return nextRoute;
        });
        return nextPayload.items || [];
      },
    };
    return () => {
      delete win.__RA_COMPARISON_BRIDGE__;
    };
  }, [active, comparisonQuery.isPlaceholderData, dialogIssueId, payload, route, baselinesParam, queryClient, syncUrl]);

  // Keyboard ↑/↓ navigation inside Case Compare Modal (when #mediaDialog is NOT open)
  useEffect(() => {
    if (!active || !dialogIssueId) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.isComposing || event.keyCode === 229) return;
      const mediaDlg = document.getElementById("mediaDialog") as HTMLDialogElement | null;
      if (mediaDlg?.open) return;
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest("input, textarea, select, [contenteditable='true'], [role='textbox']")) {
        return;
      }
      if (
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        (event.key === "ArrowUp" || event.key === "ArrowDown")
      ) {
        event.preventDefault();
        const dir: -1 | 1 = event.key === "ArrowUp" ? -1 : 1;
        const task = navTailRef.current.then(() => stepDialogCase(dir));
        navTailRef.current = task.catch((err) => {
          getLegacyWindow().showToast?.(
            err instanceof Error ? err.message : String(err),
            true,
          );
        });
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [active, dialogIssueId, stepDialogCase]);

  // Extra input popover positioning & outside-click / Escape dismiss
  const updateInputPopoverPosition = useCallback(() => {
    const trigger = inputSummaryBtnRef.current;
    const panel = inputPanelRef.current;
    if (!trigger) return;
    const margin = 12;
    const gap = 6;
    const rect = trigger.getBoundingClientRect();
    const width = Math.min(460, window.innerWidth - margin * 2);
    const measuredH = Math.min(panel?.scrollHeight || 340, window.innerHeight - margin * 2);
    const below = window.innerHeight - rect.bottom - gap - margin;
    const above = rect.top - gap - margin;
    const openAbove = below < Math.min(measuredH, 300) && above > below;
    const available = Math.max(120, openAbove ? above : below);
    const top = openAbove
      ? Math.max(margin, rect.top - gap - Math.min(measuredH, available))
      : Math.min(window.innerHeight - margin, rect.bottom + gap);
    const left = Math.max(margin, Math.min(rect.right - width, window.innerWidth - width - margin));
    setPopoverStyle({
      "--comparison-filter-width": `${width}px`,
      "--comparison-filter-left": `${left}px`,
      "--comparison-filter-top": `${top}px`,
      "--comparison-filter-max-height": `${available}px`,
    } as React.CSSProperties);
  }, []);

  useEffect(() => {
    if (!inputPopoverOpen) return;
    updateInputPopoverPosition();
    const raf = window.requestAnimationFrame(updateInputPopoverPosition);
    const onDocClick = (event: MouseEvent) => {
      if (inputFilterRef.current && !inputFilterRef.current.contains(event.target as Node)) {
        setInputPopoverOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (inputFilterRef.current?.querySelector(".ra-react-select.is-open")) return;
        event.preventDefault();
        setInputPopoverOpen(false);
        inputSummaryBtnRef.current?.focus();
      }
    };
    window.addEventListener("resize", updateInputPopoverPosition);
    window.addEventListener("scroll", updateInputPopoverPosition, true);
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(raf);
      window.removeEventListener("resize", updateInputPopoverPosition);
      window.removeEventListener("scroll", updateInputPopoverPosition, true);
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [inputPopoverOpen, updateInputPopoverPosition]);

  const commitRoute = useCallback(
    (
      updater: (prev: ComparisonRouteState) => ComparisonRouteState,
      mode: "replace" | "push" = "push",
    ) => {
      setRoute((prev) => {
        const next = updater(prev);
        syncUrl(next, mode);
        return next;
      });
    },
    [syncUrl],
  );

  const runOptionLabel = useCallback(
    (run: ModelRunItem) => {
      const name = String(run.name || run.source_name || run.id || bilingual(lang, "未命名 Run", "Untitled Run"));
      const coverage = Math.max(0, Number(run.baseline_prediction_count || 0));
      const shortId = String(run.id || "").slice(0, 8);
      const createdAt = run.created_at ? formatCstTime(run.created_at, lang) : "";
      return [
        name,
        `${coverage} ${bilingual(lang, "条当前数据集输出", "outputs in current dataset")}`,
        shortId,
        createdAt,
      ]
        .filter(Boolean)
        .join(" · ");
    },
    [lang],
  );

  const makeRunOptions = useCallback(
    (disabledId: string): UiSelectOption[] => [
      {
        value: "",
        label: bilingual(lang, "不选择（单 Run 查看）", "Not selected (single Run)"),
      },
      ...modelRuns.map((run) => ({
        value: String(run.id),
        label: runOptionLabel(run),
        disabled: Boolean(disabledId && String(run.id) === String(disabledId)),
      })),
    ],
    [lang, modelRuns, runOptionLabel],
  );

  const baselineRunOptions = useMemo(
    () => makeRunOptions(route.candidateRunId),
    [makeRunOptions, route.candidateRunId],
  );
  const candidateRunOptions = useMemo(
    () => makeRunOptions(route.baselineRunId),
    [makeRunOptions, route.baselineRunId],
  );

  const handleSelectRun = useCallback(
    async (side: "baseline" | "candidate", runId: string) => {
      commitRoute((prev) => {
        const nextBase = side === "baseline" ? runId : prev.baselineRunId;
        const nextCand = side === "candidate" ? runId : prev.candidateRunId;
        const nextInputRun =
          !nextBase || !nextCand ? (nextCand ? "candidate" : "baseline") : prev.inputFilter.run;
        return {
          ...prev,
          baselineRunId: nextBase,
          candidateRunId: nextCand,
          transition: "ALL",
          labelChange: "ALL",
          baselineLabel: nextBase ? prev.baselineLabel : "ALL",
          candidateLabel: nextCand ? prev.candidateLabel : "ALL",
          inputFilter: { ...prev.inputFilter, run: nextInputRun },
          page: 1,
        };
      }, "push");
      const chosen = modelRuns.find((item) => String(item.id) === String(runId));
      if (chosen) {
        try {
          await getLegacyWindow().applyInferredBaselinesFromRun?.(chosen, { reason: "run" });
        } catch (err) {
          getLegacyWindow().showToast?.(
            err instanceof Error ? err.message : String(err),
            true,
          );
        }
      }
    },
    [commitRoute, modelRuns],
  );

  const handleSwap = () => {
    commitRoute((prev) => {
      const nextInputRun =
        prev.inputFilter.run === "baseline"
          ? "candidate"
          : prev.inputFilter.run === "candidate"
            ? "baseline"
            : prev.inputFilter.run;
      return {
        ...prev,
        baselineRunId: prev.candidateRunId,
        candidateRunId: prev.baselineRunId,
        baselineLabel: prev.candidateLabel,
        candidateLabel: prev.baselineLabel,
        inputFilter: { ...prev.inputFilter, run: nextInputRun },
        page: 1,
      };
    }, "push");
  };

  const handleResetFilters = () => {
    setSearchDraft("");
    const resetFilter: ComparisonInputFilter = {
      version: 1,
      run: route.candidateRunId ? "candidate" : "baseline",
      relation: "all",
      conditions: [],
    };
    setInputDraft(resetFilter);
    setInputPopoverOpen(false);
    commitRoute(
      (prev) => ({
        ...prev,
        transition: "ALL",
        gtLabel: "ALL",
        baselineLabel: "ALL",
        candidateLabel: "ALL",
        labelChange: "ALL",
        inputFilter: resetFilter,
        search: "",
        page: 1,
      }),
      "push",
    );
  };

  const reviewUrl = useCallback(
    (issueId: string, runId: string) => {
      const url = new URL(withWorkbenchBase("/review"), window.location.origin);
      url.searchParams.set("issue", String(issueId));
      url.searchParams.set("run", String(runId));
      url.searchParams.set("comparison", "all");
      if (baselinesParam) url.searchParams.set("baselines", baselinesParam);
      return `${url.pathname}${url.search}`;
    },
    [baselinesParam],
  );

  const selectionNote = useMemo(() => {
    if (!selectionValid) {
      return bilingual(lang, "请至少选择一个有效 Run。", "Choose at least one valid Run.");
    }
    const isSingle = selectedRunIds.length === 1;
    const selectedCoverage = selectedRuns.reduce(
      (sum, run) => sum + Number(run.baseline_prediction_count || 0),
      0,
    );
    const oneSideMissing =
      selectedRuns.length === 2 &&
      selectedRuns.some((run) => Number(run.baseline_prediction_count || 0) <= 0);
    if (isSingle) {
      return selectedCoverage > 0
        ? bilingual(
            lang,
            "单 Run 查看；另一侧的对比内容已收起。",
            "Single Run view; comparison-only content is hidden.",
          )
        : bilingual(
            lang,
            "单 Run 查看；当前数据集暂无输出。",
            "Single Run view; no outputs in the current dataset.",
          );
    }
    if (oneSideMissing) {
      return bilingual(
        lang,
        "按并集比较；无当前数据集输出的一侧将显示为 NONE。",
        "Union comparison; the uncovered side is shown as NONE.",
      );
    }
    return bilingual(lang, "比较只读，不会修改任何 Review 或 Run。", "Comparison is read-only.");
  }, [lang, selectionValid, selectedRunIds.length, selectedRuns]);

  const inputFilterCount = useMemo(
    () => route.inputFilter.conditions.reduce((sum, item) => sum + item.values.length, 0),
    [route.inputFilter],
  );

  const gtOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "ALL", label: bilingual(lang, "全部 GT", "All GT") },
      ...LABELS.map((v) => ({ value: v, label: v })),
    ],
    [lang],
  );
  const outputOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "ALL", label: bilingual(lang, "全部输出", "All outputs") },
      ...MODEL_LABELS.map((v) => ({ value: v, label: v })),
      { value: "NONE", label: bilingual(lang, "NONE / 无输出", "NONE / Missing") },
    ],
    [lang],
  );
  const labelChangeOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "ALL", label: bilingual(lang, "全部", "All") },
      { value: "CHANGED", label: bilingual(lang, "输出有变化", "Label changed") },
      { value: "UNCHANGED", label: bilingual(lang, "输出未变化", "Label unchanged") },
    ],
    [lang],
  );
  const inputRunOptions: UiSelectOption[] = useMemo(
    () => [
      {
        value: "candidate",
        label: bilingual(lang, "新 Run", "Candidate"),
        disabled: Boolean(payload && !payload.candidate_run),
      },
      {
        value: "baseline",
        label: bilingual(lang, "基线", "Baseline"),
        disabled: Boolean(payload && !payload.baseline_run),
      },
      {
        value: "either",
        label: bilingual(lang, "任一 Run", "Either Run"),
        disabled: single,
      },
    ],
    [lang, payload, single],
  );
  const inputRelationOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "all", label: bilingual(lang, "全部满足", "Match all") },
      { value: "any", label: bilingual(lang, "任一满足", "Match any") },
    ],
    [lang],
  );
  const operatorOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "any", label: bilingual(lang, "包含任一", "Any of") },
      { value: "all", label: bilingual(lang, "包含全部", "All of") },
      { value: "none", label: bilingual(lang, "不包含", "None of") },
    ],
    [lang],
  );

  const getDraftCondition = (axis: "routing" | "lane_change"): InputFilterCondition => {
    const found = inputDraft.conditions.find((c) => c.axis === axis);
    return found || { axis, operator: "any", values: [] };
  };

  const setDraftAxisOperator = (
    axis: "routing" | "lane_change",
    operator: "any" | "all" | "none",
  ) => {
    setInputDraft((prev) => {
      const existing = prev.conditions.find((c) => c.axis === axis);
      const rest = prev.conditions.filter((c) => c.axis !== axis);
      return {
        ...prev,
        conditions: [...rest, { axis, operator, values: existing?.values || [] }],
      };
    });
  };

  const toggleDraftAxisValue = (axis: "routing" | "lane_change", val: string) => {
    setInputDraft((prev) => {
      const existing = prev.conditions.find((c) => c.axis === axis) || {
        axis,
        operator: "any" as const,
        values: [],
      };
      const rest = prev.conditions.filter((c) => c.axis !== axis);
      const nextValues = existing.values.includes(val)
        ? existing.values.filter((v) => v !== val)
        : [...existing.values, val];
      return {
        ...prev,
        conditions: [...rest, { ...existing, values: nextValues }],
      };
    });
  };

  const activeDialogItem = useMemo(
    () => (payload?.items || []).find((entry) => String(entry.issue_id) === String(dialogIssueId)) || null,
    [payload, dialogIssueId],
  );

  if (!active) return null;

  const summary = payload?.summary || {};
  const baselineSummary = summary.baseline || {};
  const candidateSummary = summary.candidate || {};
  const transitionCounts = summary.transition_counts || {};
  const delta = Number(summary.accuracy_delta || 0);
  const baselineRunId = String(payload?.baseline_run?.id || "");
  const candidateRunId = String(payload?.candidate_run?.id || "");
  const columnCount =
    3 + Number(Boolean(baselineRunId)) + Number(Boolean(candidateRunId)) + Number(!single);

  const renderMatrixTable = (matrix?: SideSummary) => {
    const columns = matrix?.columns || [];
    const rows = matrix?.rows || [];
    return (
      <table className="comparison-matrix">
        <thead>
          <tr>
            <th>GT ↓ / Model →</th>
            {columns.map((col) => (
              <th key={col}>{col}</th>
            ))}
            <th>Σ</th>
            <th>Acc</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.gt_label}>
              <th>{row.gt_label}</th>
              {columns.map((col) => {
                const count = Number(row.cells?.[col] || 0);
                const correct = col !== "NONE" && modelLabelMatchesGt(col, row.gt_label);
                return (
                  <td
                    key={col}
                    className={correct ? "matrix-correct" : count ? "matrix-error" : ""}
                  >
                    {count}
                  </td>
                );
              })}
              <td>{row.total}</td>
              <td>{percentage(row.accuracy)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  const renderPredictionCell = (
    prediction: PredictionSide | null | undefined,
    url: string,
    reviewBtnLabel: string,
  ) => {
    const label = prediction?.model_label || "NONE";
    const confidence = prediction?.model_confidence;
    const verdict = prediction?.correct
      ? bilingual(lang, "匹配 GT", "Matches GT")
      : bilingual(lang, "不匹配 GT", "Differs from GT");
    const savedReason = String(prediction?.model_reason || "").trim();
    const reasonText =
      savedReason || bilingual(lang, "未保存／未生成 Reason", "Reason not saved / generated");
    return (
      <div className={`comparison-prediction ${prediction?.correct ? "is-correct" : "is-error"}`}>
        <div className="comparison-prediction-output">
          <strong className="comparison-output-label">{label}</strong>
          {confidence != null ? (
            <span className="comparison-prediction-confidence">
              {Number(confidence).toFixed(3)}
            </span>
          ) : null}
          <small
            className={`comparison-prediction-verdict comparison-chip ${
              prediction?.correct ? "comparison-match" : "comparison-mismatch"
            }`}
          >
            {verdict}
          </small>
        </div>
        <span
          className={`comparison-prediction-reason${savedReason ? " has-saved-reason" : " is-empty"}`}
          title={savedReason || undefined}
          aria-label={savedReason || reasonText}
        >
          {reasonText}
        </span>
        {url ? (
          <a
            className="button button-quiet comparison-inline-review"
            href={url}
            onClick={(e) => e.stopPropagation()}
          >
            {reviewBtnLabel}
          </a>
        ) : null}
      </div>
    );
  };

  const renderDialogSidePanel = (
    titleZh: string,
    titleEn: string,
    prediction: PredictionSide | null | undefined,
    run: RunSnapshotLike | null | undefined,
    idPrefix: "Baseline" | "Candidate",
  ) => {
    const modelLabel = prediction?.model_label || "NONE";
    const confidence = prediction?.model_confidence;
    const verdict = prediction?.correct
      ? bilingual(lang, "匹配 GT", "Matches GT")
      : bilingual(lang, "不匹配 GT", "Differs from GT");
    return (
      <section className="comparison-reason-panel" id={`raComparisonReason${idPrefix}Panel`}>
        <header>
          <h3>{bilingual(lang, titleZh, titleEn)}</h3>
          <p>{run?.name || run?.id || "—"}</p>
        </header>
        <div className="comparison-reason-summary">
          <div>
            <span>Model</span>
            <strong data-triage-label={modelLabel}>{modelLabel}</strong>
          </div>
          <div>
            <span>Confidence</span>
            <strong>{confidence == null ? "—" : Number(confidence).toFixed(3)}</strong>
          </div>
          <div>
            <span>Status</span>
            <strong
              id={`raComparisonReason${idPrefix}Verdict`}
              className={prediction?.correct ? "" : "is-error"}
            >
              {verdict}
            </strong>
          </div>
        </div>
        <div className="comparison-reason-content">
          <h4>{bilingual(lang, "完整 Reason", "Full reason")}</h4>
          <p>
            {prediction?.model_reason ||
              bilingual(lang, "未保存／未生成 Reason", "Reason not saved / generated")}
          </p>
        </div>
      </section>
    );
  };

  const dialogExtraInputs = caseInputsQuery.data
    ? {
        baseline: caseInputsQuery.data.baseline?.extra_inputs,
        candidate: caseInputsQuery.data.candidate?.extra_inputs,
      }
    : activeDialogItem?.extra_inputs;
  const dialogSceneReview = caseInputsQuery.data?.scene_review ?? activeDialogItem?.scene_review;

  const transitionDefs: Array<{ value: string; zh: string; en: string; cls?: string }> = [
    { value: "ALL", zh: "全部", en: "All" },
    { value: "P2F", zh: "P2F 退化", en: "P2F Regressions", cls: "transition-regression" },
    { value: "F2P", zh: "F2P 改善", en: "F2P Improvements", cls: "transition-improvement" },
    { value: "F2F", zh: "F2F 仍错误", en: "F2F Still wrong", cls: "transition-f2f" },
    { value: "P2P", zh: "P2P 均正确", en: "P2P Both correct", cls: "transition-p2p" },
  ];

  const routingCond = getDraftCondition("routing");
  const laneCond = getDraftCondition("lane_change");

  return (
    <div className="ra-run-comparison-root" data-react-island="comparison">
      <section className="page-card run-comparison-controls">
        <div className="run-comparison-picker-grid">
          <div className="ra-comparison-field">
            <span>{bilingual(lang, "基线 Run", "Baseline Run")}</span>
            <UiSelect
              id="comparisonBaselineRunPicker"
              className="comparison-run-picker"
              value={route.baselineRunId}
              options={baselineRunOptions}
              placeholder={bilingual(lang, "请选择 Run", "Select a Run")}
              ariaLabel={bilingual(lang, "基线 Run", "Baseline Run")}
              onChange={(val) => void handleSelectRun("baseline", val)}
            />
          </div>

          <button
            className="button button-quiet comparison-swap"
            id="comparisonSwapButton"
            type="button"
            aria-label={bilingual(lang, "交换两个 Run", "Swap Runs")}
            title={bilingual(lang, "交换两个 Run", "Swap Runs")}
            onClick={handleSwap}
          >
            ⇄
          </button>

          <div className="ra-comparison-field">
            <span>{bilingual(lang, "新 Run", "Candidate Run")}</span>
            <UiSelect
              id="comparisonCandidateRunPicker"
              className="comparison-run-picker"
              value={route.candidateRunId}
              options={candidateRunOptions}
              placeholder={bilingual(lang, "请选择 Run", "Select a Run")}
              ariaLabel={bilingual(lang, "新 Run", "Candidate Run")}
              onChange={(val) => void handleSelectRun("candidate", val)}
            />
          </div>

          <button
            className="button button-primary"
            id="comparisonLoadButton"
            type="button"
            disabled={!selectionValid || comparisonQuery.isFetching}
            onClick={() => void comparisonQuery.refetch()}
          >
            {bilingual(lang, "查看结果", "View results")}
          </button>
        </div>
        <p className="muted comparison-selection-note" id="comparisonSelectionNote">
          {selectionNote}
        </p>
      </section>

      {!hasPayload ? (
        <section className="comparison-empty page-card" id="comparisonEmptyState">
          <strong>
            {loadError
              ? bilingual(lang, "加载对比结果失败", "Failed to load comparison")
              : runsQuery.isLoading || comparisonQuery.isLoading
                ? bilingual(lang, "正在加载对比结果…", "Loading comparison…")
                : bilingual(lang, "至少选择一个 Run", "Select at least one Run")}
          </strong>
          <p className="muted">
            {loadError
              ? loadError.message
              : bilingual(
                  lang,
                  "结果不会修改 Review、GT、Run 或 Trail。",
                  "Comparison does not change Reviews, GT, Runs, or Trail.",
                )}
          </p>
        </section>
      ) : (
        <div
          className={`comparison-results${single ? " is-single-run" : ""}`}
          id="comparisonResults"
        >
          <section className="comparison-summary-grid" id="comparisonSummary">
            {single ? (
              (() => {
                const side = payload?.candidate_run ? candidateSummary : baselineSummary;
                const run = payload?.candidate_run || payload?.baseline_run || {};
                return (
                  <>
                    <article className="page-card comparison-metric">
                      <span>{bilingual(lang, "Run 准确率", "Run accuracy")}</span>
                      <strong>{percentage(side.accuracy)}</strong>
                      <small>
                        {side.correct_count || 0} / {side.total_count || 0}
                      </small>
                    </article>
                    <article className="page-card comparison-metric">
                      <span>{bilingual(lang, "有输出 Case", "Predicted cases")}</span>
                      <strong>{side.prediction_count || 0}</strong>
                      <small>{run.name || run.id || ""}</small>
                    </article>
                    <article className="page-card comparison-metric">
                      <span>{bilingual(lang, "正确 Case", "Correct cases")}</span>
                      <strong>{side.correct_count || 0}</strong>
                      <small>
                        {side.total_count || 0} {bilingual(lang, "条 GT Case", "GT cases")}
                      </small>
                    </article>
                  </>
                );
              })()
            ) : (
              <>
                <article className="page-card comparison-metric">
                  <span>{bilingual(lang, "基线准确率", "Baseline accuracy")}</span>
                  <strong>{percentage(baselineSummary.accuracy)}</strong>
                  <small>
                    {baselineSummary.correct_count || 0} / {baselineSummary.total_count || 0}
                  </small>
                </article>
                <article className="page-card comparison-metric">
                  <span>{bilingual(lang, "新 Run 准确率", "Candidate accuracy")}</span>
                  <strong>{percentage(candidateSummary.accuracy)}</strong>
                  <small>
                    {candidateSummary.correct_count || 0} / {candidateSummary.total_count || 0}
                  </small>
                </article>
                <article
                  className={`page-card comparison-metric ${
                    delta > 0 ? "is-positive" : delta < 0 ? "is-negative" : ""
                  }`}
                >
                  <span>{bilingual(lang, "准确率变化", "Accuracy delta")}</span>
                  <strong>
                    {delta >= 0 ? "+" : ""}
                    {(delta * 100).toFixed(1)} pp
                  </strong>
                  <small>
                    {candidateSummary.prediction_count || 0}{" "}
                    {bilingual(lang, "条有输出", "predicted")}
                  </small>
                </article>
                <article className="page-card comparison-metric is-negative">
                  <span>{bilingual(lang, "P2F 退化", "P2F regressions")}</span>
                  <strong>{transitionCounts.P2F || 0}</strong>
                  <small>
                    {bilingual(
                      lang,
                      "基线正确 → 新 Run 错误",
                      "baseline correct → candidate wrong",
                    )}
                  </small>
                </article>
                <article className="page-card comparison-metric is-positive">
                  <span>{bilingual(lang, "F2P 改善", "F2P improvements")}</span>
                  <strong>{transitionCounts.F2P || 0}</strong>
                  <small>
                    {bilingual(
                      lang,
                      "基线错误 → 新 Run 正确",
                      "baseline wrong → candidate correct",
                    )}
                  </small>
                </article>
                <article className="page-card comparison-metric">
                  <span>{bilingual(lang, "标签变化", "Label changes")}</span>
                  <strong>{summary.label_changed_count || 0}</strong>
                  <small>
                    {summary.total_count || 0} {bilingual(lang, "条 GT Case", "GT cases")}
                  </small>
                </article>
              </>
            )}
          </section>

          <section className="comparison-matrix-grid">
            {payload?.baseline_run ? (
              <article className="page-card comparison-matrix-card" id="comparisonBaselineMatrixCard">
                <div className="comparison-card-heading">
                  <h3>{bilingual(lang, "基线混淆矩阵", "Baseline matrix")}</h3>
                  <span id="comparisonBaselineMatrixMeta">
                    {percentage(baselineSummary.accuracy)}
                  </span>
                </div>
                <div className="comparison-matrix-wrap" id="comparisonBaselineMatrix">
                  {renderMatrixTable(baselineSummary)}
                </div>
              </article>
            ) : null}

            {payload?.candidate_run ? (
              <article
                className="page-card comparison-matrix-card"
                id="comparisonCandidateMatrixCard"
              >
                <div className="comparison-card-heading">
                  <h3>{bilingual(lang, "新 Run 混淆矩阵", "Candidate matrix")}</h3>
                  <span id="comparisonCandidateMatrixMeta">
                    {percentage(candidateSummary.accuracy)}
                  </span>
                </div>
                <div className="comparison-matrix-wrap" id="comparisonCandidateMatrix">
                  {renderMatrixTable(candidateSummary)}
                </div>
              </article>
            ) : null}
          </section>

          <details className="page-card comparison-snapshot">
            <summary>{bilingual(lang, "Run Prompt / 输入配置", "Run Prompt / Input config")}</summary>
            <div id="comparisonRunDiff">
              {single ? (
                <RunSnapshotView
                  run={payload?.candidate_run || payload?.baseline_run}
                  lang={lang}
                />
              ) : (
                <>
                  <div className="comparison-original">
                    <div className="prompt-meta">
                      <strong>{payload?.baseline_run?.name || "—"}</strong>
                      <br />
                      <PromptMetaBadge prompt={payload?.baseline_run?.prompt} lang={lang} />
                    </div>
                    <div className="prompt-meta">
                      <strong>{payload?.candidate_run?.name || "—"}</strong>
                      <br />
                      <PromptMetaBadge prompt={payload?.candidate_run?.prompt} lang={lang} />
                    </div>
                  </div>
                  <h4>Prompt</h4>
                  <ComparisonDiffView
                    left={payload?.baseline_run?.prompt?.template || ""}
                    right={payload?.candidate_run?.prompt?.template || ""}
                    lang={lang}
                  />
                  <h4>{bilingual(lang, "输入配置 · Run 参考", "Input config · Run reference")}</h4>
                  <ComparisonDiffView
                    left={
                      payload?.baseline_run?.input?.available
                        ? comparisonConfigText(payload.baseline_run.input.config)
                        : ""
                    }
                    right={
                      payload?.candidate_run?.input?.available
                        ? comparisonConfigText(payload.candidate_run.input.config)
                        : ""
                    }
                    lang={lang}
                  />
                </>
              )}
            </div>
          </details>

          <section className="page-card comparison-cases-card">
            <div className="comparison-cases-heading">
              <div>
                <h3 id="comparisonCasesTitle">
                  {single
                    ? bilingual(lang, "Case 明细", "Cases")
                    : bilingual(lang, "Case 变化明细", "Case transitions")}
                </h3>
                <p className="muted" id="comparisonCaseCount">
                  {bilingual(
                    lang,
                    `筛选后 ${payload?.total || 0} 条；当前第 ${payload?.page || 1} / ${payload?.page_count || 1} 页`,
                    `${payload?.total || 0} filtered · page ${payload?.page || 1} / ${payload?.page_count || 1}`,
                  )}
                </p>
              </div>

              {!single ? (
                <div
                  className="comparison-transition-filter"
                  id="comparisonTransitionFilter"
                  role="group"
                  aria-label={bilingual(lang, "变化类型", "Transition type")}
                >
                  {transitionDefs.map((item) => {
                    const count = transitionCounts[item.value];
                    const activeBtn = route.transition === item.value;
                    const baseLabel = bilingual(lang, item.zh, item.en);
                    return (
                      <button
                        key={item.value}
                        className={`button button-quiet${item.cls ? ` ${item.cls}` : ""}${
                          activeBtn ? " active" : ""
                        }`}
                        type="button"
                        data-comparison-transition={item.value}
                        onClick={() =>
                          commitRoute(
                            (prev) => ({ ...prev, transition: item.value, page: 1 }),
                            "push",
                          )
                        }
                      >
                        {item.value === "ALL" || count == null
                          ? baseLabel
                          : `${baseLabel} ${count}`}
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>

            <div
              className="comparison-filter-grid"
              aria-label={bilingual(lang, "Case 筛选", "Case filters")}
            >
              <label className="comparison-search">
                <span>Issue ID / reason</span>
                <input
                  id="comparisonSearchInput"
                  type="search"
                  value={searchDraft}
                  placeholder={bilingual(lang, "搜索 Issue ID / reason", "Search Issue ID / reason")}
                  autoComplete="off"
                  onChange={(e) => {
                    const val = e.target.value;
                    setSearchDraft(val);
                    if (searchTimerRef.current !== null) {
                      window.clearTimeout(searchTimerRef.current);
                    }
                    searchTimerRef.current = window.setTimeout(() => {
                      commitRoute(
                        (prev) => ({ ...prev, search: val.trim().slice(0, 128), page: 1 }),
                        "replace",
                      );
                    }, 250);
                  }}
                />
              </label>

              <div className="ra-comparison-filter-field">
                <span>GT</span>
                <UiSelect
                  id="comparisonGtFilter"
                  value={route.gtLabel}
                  options={gtOptions}
                  ariaLabel="GT"
                  onChange={(val) =>
                    commitRoute((prev) => ({ ...prev, gtLabel: val, page: 1 }), "push")
                  }
                />
              </div>

              {payload?.baseline_run ? (
                <div className="ra-comparison-filter-field">
                  <span>{bilingual(lang, "基线输出", "Baseline output")}</span>
                  <UiSelect
                    id="comparisonBaselineLabelFilter"
                    value={route.baselineLabel}
                    options={outputOptions}
                    ariaLabel={bilingual(lang, "基线输出", "Baseline output")}
                    onChange={(val) =>
                      commitRoute((prev) => ({ ...prev, baselineLabel: val, page: 1 }), "push")
                    }
                  />
                </div>
              ) : null}

              {payload?.candidate_run ? (
                <div className="ra-comparison-filter-field">
                  <span>{bilingual(lang, "新 Run 输出", "Candidate output")}</span>
                  <UiSelect
                    id="comparisonCandidateLabelFilter"
                    value={route.candidateLabel}
                    options={outputOptions}
                    ariaLabel={bilingual(lang, "新 Run 输出", "Candidate output")}
                    onChange={(val) =>
                      commitRoute((prev) => ({ ...prev, candidateLabel: val, page: 1 }), "push")
                    }
                  />
                </div>
              ) : null}

              {!single ? (
                <div className="ra-comparison-filter-field">
                  <span>{bilingual(lang, "标签变化", "Label change")}</span>
                  <UiSelect
                    id="comparisonLabelChangeFilter"
                    value={route.labelChange}
                    options={labelChangeOptions}
                    ariaLabel={bilingual(lang, "标签变化", "Label change")}
                    onChange={(val) =>
                      commitRoute((prev) => ({ ...prev, labelChange: val, page: 1 }), "push")
                    }
                  />
                </div>
              ) : null}

              <div className="comparison-input-filter" id="comparisonInputFilter" ref={inputFilterRef}>
                <button
                  ref={inputSummaryBtnRef}
                  type="button"
                  className="button button-quiet ra-comparison-input-trigger"
                  aria-expanded={inputPopoverOpen}
                  onClick={() => {
                    setInputPopoverOpen((prev) => {
                      const next = !prev;
                      if (next) setInputDraft(route.inputFilter);
                      return next;
                    });
                  }}
                >
                  <span id="comparisonInputFilterSummary">
                    {inputFilterCount
                      ? bilingual(
                          lang,
                          `额外输入 · ${inputFilterCount} 项`,
                          `Extra inputs · ${inputFilterCount}`,
                        )
                      : bilingual(lang, "额外输入", "Extra inputs")}
                  </span>
                  {inputFilterCount > 0 ? (
                    <b id="comparisonInputFilterCount">{inputFilterCount}</b>
                  ) : null}
                </button>

                {inputPopoverOpen ? (
                  <div
                    ref={inputPanelRef}
                    className="comparison-input-filter-panel"
                    style={popoverStyle}
                  >
                    <div className="comparison-input-filter-settings">
                      <div className="ra-comparison-filter-field">
                        <span>{bilingual(lang, "筛选 Run", "Filter Run")}</span>
                        <UiSelect
                          id="comparisonInputFilterRun"
                          value={inputDraft.run}
                          options={inputRunOptions}
                          ariaLabel={bilingual(lang, "筛选 Run", "Filter Run")}
                          onChange={(val) =>
                            setInputDraft((prev) => ({
                              ...prev,
                              run: val as ComparisonInputFilter["run"],
                            }))
                          }
                        />
                      </div>
                      <div className="ra-comparison-filter-field">
                        <span>{bilingual(lang, "维度关系", "Axis relation")}</span>
                        <UiSelect
                          id="comparisonInputFilterRelation"
                          value={inputDraft.relation}
                          options={inputRelationOptions}
                          ariaLabel={bilingual(lang, "维度关系", "Axis relation")}
                          onChange={(val) =>
                            setInputDraft((prev) => ({
                              ...prev,
                              relation: val as ComparisonInputFilter["relation"],
                            }))
                          }
                        />
                      </div>
                    </div>

                    <fieldset data-input-filter-axis="routing">
                      <legend>Routing</legend>
                      <UiSelect
                        id="comparisonInputRoutingOp"
                        value={routingCond.operator}
                        options={operatorOptions}
                        ariaLabel="Routing operator"
                        onChange={(val) =>
                          setDraftAxisOperator("routing", val as InputFilterCondition["operator"])
                        }
                      />
                      <div className="comparison-input-filter-values">
                        {ROUTING_VALUES.map((val) => (
                          <label key={val}>
                            <input
                              type="checkbox"
                              checked={routingCond.values.includes(val)}
                              onChange={() => toggleDraftAxisValue("routing", val)}
                            />
                            {val}
                          </label>
                        ))}
                      </div>
                    </fieldset>

                    <fieldset data-input-filter-axis="lane_change">
                      <legend>{bilingual(lang, "自车变道", "Ego lane change")}</legend>
                      <UiSelect
                        id="comparisonInputLaneOp"
                        value={laneCond.operator}
                        options={operatorOptions}
                        ariaLabel={bilingual(lang, "自车变道条件", "Lane change operator")}
                        onChange={(val) =>
                          setDraftAxisOperator(
                            "lane_change",
                            val as InputFilterCondition["operator"],
                          )
                        }
                      />
                      <div className="comparison-input-filter-values">
                        {LANE_CHANGE_VALUES.map((val) => (
                          <label key={val}>
                            <input
                              type="checkbox"
                              checked={laneCond.values.includes(val)}
                              onChange={() => toggleDraftAxisValue("lane_change", val)}
                            />
                            {val}
                          </label>
                        ))}
                      </div>
                    </fieldset>

                    <div className="comparison-input-filter-actions">
                      <button
                        className="button button-quiet"
                        id="comparisonInputFilterClear"
                        type="button"
                        onClick={() =>
                          setInputDraft({
                            version: 1,
                            run: payload?.candidate_run ? "candidate" : "baseline",
                            relation: "all",
                            conditions: [],
                          })
                        }
                      >
                        {bilingual(lang, "清空", "Clear")}
                      </button>
                      <button
                        className="button button-primary"
                        id="comparisonInputFilterApply"
                        type="button"
                        onClick={() => {
                          const cleaned: ComparisonInputFilter = {
                            ...inputDraft,
                            conditions: inputDraft.conditions.filter((c) => c.values.length > 0),
                          };
                          setInputPopoverOpen(false);
                          commitRoute(
                            (prev) => ({ ...prev, inputFilter: cleaned, page: 1 }),
                            "push",
                          );
                        }}
                      >
                        {bilingual(lang, "应用", "Apply")}
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>

              <button
                className="button button-quiet"
                id="comparisonResetFilters"
                type="button"
                onClick={handleResetFilters}
              >
                {bilingual(lang, "重置筛选", "Reset filters")}
              </button>
            </div>

            <div className="comparison-table-wrap">
              <table className="comparison-case-table">
                <thead>
                  <tr>
                    <th>Issue / GT</th>
                    <th>{bilingual(lang, "BEV 预览", "BEV preview")}</th>
                    {baselineRunId ? (
                      <th id="comparisonBaselineOutputHeading">
                        {bilingual(lang, "基线输出", "Baseline")}
                      </th>
                    ) : null}
                    {candidateRunId ? (
                      <th id="comparisonCandidateOutputHeading">
                        {bilingual(lang, "新 Run 输出", "Candidate")}
                      </th>
                    ) : null}
                    {!single ? (
                      <th id="comparisonTransitionHeading">
                        {bilingual(lang, "变化", "Change")}
                      </th>
                    ) : null}
                    <th>{bilingual(lang, "额外输入", "Extra inputs")}</th>
                  </tr>
                </thead>
                <tbody id="comparisonCaseRows">
                  {(payload?.items || []).length === 0 ? (
                    <tr>
                      <td colSpan={columnCount} className="comparison-no-rows">
                        {bilingual(
                          lang,
                          "当前条件下没有 Case。",
                          "No cases match the current filters.",
                        )}
                      </td>
                    </tr>
                  ) : (
                    (payload?.items || []).map((item) => {
                      const reviewRunId = candidateRunId || baselineRunId;
                      const transLower = String(item.transition || "").toLowerCase();
                      const bevBroken = Boolean(bevBrokenIds[item.issue_id]);
                      const rowLabel = bilingual(
                        lang,
                        `打开 ${item.issue_id} 的${single ? "单 Run 详情" : "双 Run Case 对比"}`,
                        `Open ${single ? "the single-Run details" : "the two-Run comparison"} for ${item.issue_id}`,
                      );
                      return (
                        <tr
                          key={item.issue_id}
                          className={`transition-${transLower}`}
                          data-comparison-row=""
                          data-issue-id={item.issue_id}
                          tabIndex={0}
                          aria-label={rowLabel}
                          onClick={(e) => {
                            if (
                              (e.target as HTMLElement).closest(
                                "a, button, input, select, textarea",
                              )
                            ) {
                              return;
                            }
                            setDialogTab("output");
                            setDialogIssueId(item.issue_id);
                          }}
                          onKeyDown={(e) => {
                            if (e.target !== e.currentTarget) return;
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              setDialogTab("output");
                              setDialogIssueId(item.issue_id);
                            }
                          }}
                        >
                          <td>
                            <a
                              className="comparison-issue-link"
                              href={reviewUrl(item.issue_id, reviewRunId)}
                              onClick={(e) => e.stopPropagation()}
                            >
                              {item.issue_id}
                            </a>
                            <div className="comparison-issue-meta">
                              <span className="comparison-gt-summary">
                                <span>GT</span>
                                <strong>{item.gt_label || "—"}</strong>
                              </span>
                              <small>{item.baseline_scope || ""}</small>
                            </div>
                            <SceneTagsView review={item.scene_review} lang={lang} />
                          </td>

                          <td>
                            <button
                              type="button"
                              className={`comparison-bev${bevBroken ? " is-missing" : ""}`}
                              data-comparison-media={item.issue_id}
                              aria-label={bilingual(
                                lang,
                                `打开 ${item.issue_id} 参考媒体`,
                                `Open reference media for ${item.issue_id}`,
                              )}
                              onClick={(e) => {
                                e.stopPropagation();
                                void getLegacyWindow()
                                  .openComparisonMedia?.(item.issue_id, "bev")
                                  ?.catch((err: Error) =>
                                    getLegacyWindow().showToast?.(err.message, true),
                                  );
                              }}
                            >
                              {!bevBroken ? (
                                <img
                                  loading="lazy"
                                  src={withWorkbenchBase(
                                    `/api/case-thumbnails/${encodeURIComponent(item.issue_id)}`,
                                  )}
                                  alt={bilingual(lang, "BEV 预览", "BEV preview")}
                                  onError={() =>
                                    setBevBrokenIds((prev) => ({
                                      ...prev,
                                      [item.issue_id]: true,
                                    }))
                                  }
                                />
                              ) : null}
                              <span>{bilingual(lang, "暂无 BEV", "No BEV")}</span>
                            </button>
                          </td>

                          {baselineRunId ? (
                            <td>
                              {renderPredictionCell(
                                item.baseline,
                                reviewUrl(item.issue_id, baselineRunId),
                                bilingual(lang, "基线复核", "Baseline review"),
                              )}
                            </td>
                          ) : null}

                          {candidateRunId ? (
                            <td>
                              {renderPredictionCell(
                                item.candidate,
                                reviewUrl(item.issue_id, candidateRunId),
                                bilingual(lang, "新 Run 复核", "Candidate review"),
                              )}
                            </td>
                          ) : null}

                          {!single ? (
                            <td>
                              <div className="comparison-transition-cell">
                                <span className={`comparison-transition-badge ${transLower}`}>
                                  {comparisonTransitionText(item.transition, lang)}
                                </span>
                              </div>
                            </td>
                          ) : null}

                          <td>
                            <div className="comparison-extra-inputs">
                              <ExtraInputsView extraInputs={item.extra_inputs} lang={lang} />
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            <div className="comparison-pagination">
              <Pagination
                page={Number(payload?.page || route.page || 1)}
                pageSize={route.pageSize}
                total={Number(payload?.total || 0)}
                lang={lang}
                loading={comparisonQuery.isFetching}
                labelText={`${Number(payload?.page || 1)} / ${Math.max(1, Number(payload?.page_count || 1))}`}
                ariaLabel={bilingual(
                  lang,
                  "Run 对比 Case 分页",
                  "Run comparison case pagination",
                )}
                onPageChange={(nextPage) =>
                  commitRoute((prev) => ({ ...prev, page: nextPage }), "push")
                }
                onPageSizeChange={(nextSize) =>
                  commitRoute((prev) => ({ ...prev, pageSize: nextSize, page: 1 }), "push")
                }
              />
            </div>
          </section>
        </div>
      )}

      {/* Native top-layer <dialog> portaled to document.body to match classic #comparisonReasonDialog 1:1 */}
      {createPortal(
        <dialog
          ref={dialogRef}
          id="raComparisonReasonDialog"
          className={`dialog comparison-reason-dialog ra-comparison-reason-dialog${
            single ? " is-single-run" : ""
          }`}
          aria-labelledby="raComparisonReasonTitle"
          aria-keyshortcuts="ArrowUp ArrowDown"
          onClose={() => setDialogIssueId("")}
          onClick={(e) => {
            if (e.target === e.currentTarget) {
              setDialogIssueId("");
            }
          }}
        >
        {dialogIssueId && activeDialogItem ? (
          <div className="dialog-card">
            <div className="dialog-heading">
              <div>
                <h2 id="raComparisonReasonTitle">
                  {activeDialogItem.issue_id} ·{" "}
                  {single
                    ? bilingual(lang, "Case 详情", "Case details")
                    : bilingual(lang, "Case 对比", "Case comparison")}
                </h2>
                <p className="dialog-copy" id="raComparisonReasonContext">
                  <span className="comparison-context-gt">
                    <small>GT</small>
                    <strong data-triage-label={activeDialogItem.gt_label || ""}>
                      {activeDialogItem.gt_label || bilingual(lang, "未保存", "Not saved")}
                    </strong>
                  </span>
                  {!single ? (
                    <span className="comparison-context-transition">
                      {comparisonTransitionText(activeDialogItem.transition, lang)}
                    </span>
                  ) : null}
                </p>
              </div>

              {dialogExtraInputs &&
              (dialogExtraInputs.baseline?.available || dialogExtraInputs.candidate?.available) ? (
                <div className="comparison-dialog-extra-inputs" id="raComparisonDialogExtraInputs">
                  <ExtraInputsView extraInputs={dialogExtraInputs} dialog lang={lang} />
                </div>
              ) : null}

              <div
                className="comparison-case-tabs"
                role="tablist"
                aria-label={
                  single
                    ? bilingual(lang, "Case 详情", "Case details")
                    : bilingual(lang, "Case 对比", "Case comparison")
                }
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={dialogTab === "output"}
                  onClick={() => setDialogTab("output")}
                >
                  {bilingual(lang, "总览", "Overview")}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={dialogTab === "prompt"}
                  onClick={() => setDialogTab("prompt")}
                >
                  Prompt
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={dialogTab === "config"}
                  onClick={() => setDialogTab("config")}
                >
                  {bilingual(lang, "输入配置", "Input config")}
                </button>
              </div>

              <button
                className="icon-button"
                type="button"
                aria-label={bilingual(lang, "关闭", "Close")}
                onClick={() => setDialogIssueId("")}
              >
                ×
              </button>
            </div>

            <div className="comparison-case-scroll" ref={dialogScrollRef}>
              {dialogTab === "output" ? (
                <div className="comparison-case-evidence" id="raComparisonCaseEvidence">
                  <aside className="comparison-case-bev">
                    <h3>{bilingual(lang, "参考媒体", "Reference media")}</h3>
                    <div className="comparison-bev-meta">
                      <small>{dialogBevTime}</small>
                      {dialogSceneReview?.tags?.length ? (
                        <div className="comparison-scene-tags">
                          <SceneTagsView review={dialogSceneReview} lang={lang} />
                        </div>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      className={`comparison-bev${dialogBevMissing ? " is-missing" : ""}`}
                      aria-label={bilingual(lang, "打开参考 BEV 媒体", "Open reference BEV media")}
                      onClick={() =>
                        void getLegacyWindow()
                          .openComparisonMedia?.(dialogIssueId, "bev")
                          ?.catch((err: Error) => getLegacyWindow().showToast?.(err.message, true))
                      }
                    >
                      {!dialogBevMissing ? (
                        <img
                          src={withWorkbenchBase(
                            `/api/case-thumbnails/${encodeURIComponent(dialogIssueId)}`,
                          )}
                          alt={bilingual(lang, "BEV 预览", "BEV preview")}
                          onError={() => setDialogBevMissing(true)}
                        />
                      ) : null}
                      <span>{bilingual(lang, "暂无 BEV", "No BEV")}</span>
                    </button>
                    <small>{dialogCamTime}</small>
                    <button
                      type="button"
                      className={`comparison-bev${dialogCamMissing ? " is-missing" : ""}`}
                      aria-label={bilingual(
                        lang,
                        "打开参考 Camera 媒体",
                        "Open reference Camera media",
                      )}
                      onClick={() =>
                        void getLegacyWindow()
                          .openComparisonMedia?.(dialogIssueId, "camera")
                          ?.catch((err: Error) => getLegacyWindow().showToast?.(err.message, true))
                      }
                    >
                      {!dialogCamMissing && dialogCamUrl ? (
                        <img
                          src={dialogCamUrl}
                          alt={bilingual(lang, "Camera 预览", "Camera preview")}
                          onError={() => setDialogCamMissing(true)}
                        />
                      ) : null}
                      <span>{bilingual(lang, "暂无 Camera", "No Camera")}</span>
                    </button>
                  </aside>

                  <div className="comparison-reason-grid">
                    {payload?.baseline_run
                      ? renderDialogSidePanel(
                          "基线 Run",
                          "Baseline Run",
                          activeDialogItem.baseline,
                          payload.baseline_run,
                          "Baseline",
                        )
                      : null}
                    {payload?.candidate_run
                      ? renderDialogSidePanel(
                          "新 Run",
                          "Candidate Run",
                          activeDialogItem.candidate,
                          payload.candidate_run,
                          "Candidate",
                        )
                      : null}
                  </div>
                </div>
              ) : null}

              <div id="raComparisonCaseInputs" className="ra-comparison-case-inputs">
                {caseInputsQuery.isLoading ? (
                  <p className="muted">
                    {bilingual(lang, "正在读取已保存输入…", "Loading saved inputs…")}
                  </p>
                ) : caseInputsQuery.isError ? (
                  <p className="muted">
                    {bilingual(lang, "输入读取失败：", "Failed to load inputs: ")}
                    {(caseInputsQuery.error as Error)?.message || ""}
                  </p>
                ) : caseInputsQuery.data ? (
                  single ? (
                    (() => {
                      const side = caseInputsQuery.data.candidate || caseInputsQuery.data.baseline;
                      const runLabel = payload?.candidate_run
                        ? bilingual(lang, "新 Run", "Candidate Run")
                        : bilingual(lang, "基线 Run", "Baseline Run");
                      if (!side) return null;
                      return dialogTab === "config" ? (
                        <section>
                          <p>
                            {bilingual(lang, "逐 Case 配置：", "Per-case config: ")}
                            {side.input?.available
                              ? bilingual(lang, "实际输入", "Actual input")
                              : bilingual(lang, "未保存", "Not saved")}
                          </p>
                          <pre>
                            {side.input?.available
                              ? comparisonConfigText(side.input.config)
                              : bilingual(lang, "未保存", "Not saved")}
                          </pre>
                          <h4>
                            {bilingual(
                              lang,
                              "已记录媒体 · 顺序与时间点",
                              "Recorded media · order & timestamps",
                            )}
                          </h4>
                          <p>{side.media?.notice || ""}</p>
                          <pre>
                            {side.media?.available
                              ? comparisonConfigText({
                                  count: side.media.count,
                                  items: side.media.items,
                                })
                              : bilingual(lang, "未保存", "Not saved")}
                          </pre>
                        </section>
                      ) : (
                        <section>
                          <h3>{runLabel} Prompt</h3>
                          <div className="prompt-meta">
                            <PromptMetaBadge prompt={side.prompt} lang={lang} />
                          </div>
                          <pre>{side.prompt?.text || bilingual(lang, "未保存", "Not saved")}</pre>
                          <details>
                            <summary>
                              {bilingual(
                                lang,
                                "Run 模板／示例参考（不是该 Case 实际输入）",
                                "Run template / example reference (not this Case's actual input)",
                              )}
                            </summary>
                            <RunSnapshotView run={side.run_reference} lang={lang} />
                          </details>
                        </section>
                      );
                    })()
                  ) : (
                    (() => {
                      const a = caseInputsQuery.data.baseline;
                      const b = caseInputsQuery.data.candidate;
                      if (!a || !b) return null;
                      return dialogTab === "config" ? (
                        <section>
                          <p>
                            {bilingual(lang, "逐 Case 配置：", "Per-case config: ")}
                            {bilingual(lang, "基线 ", "Baseline ")}
                            {a.input?.available
                              ? bilingual(lang, "实际输入", "Actual input")
                              : bilingual(lang, "未保存", "Not saved")}{" "}
                            · {bilingual(lang, "新 Run ", "Candidate ")}
                            {b.input?.available
                              ? bilingual(lang, "实际输入", "Actual input")
                              : bilingual(lang, "未保存", "Not saved")}
                          </p>
                          <ComparisonDiffView
                            left={a.input?.available ? comparisonConfigText(a.input.config) : ""}
                            right={b.input?.available ? comparisonConfigText(b.input.config) : ""}
                            lang={lang}
                          />
                          <h4>
                            {bilingual(
                              lang,
                              "已记录媒体 · 顺序与时间点",
                              "Recorded media · order & timestamps",
                            )}
                          </h4>
                          <p>{a.media?.notice || ""}</p>
                          <ComparisonDiffView
                            left={
                              a.media?.available
                                ? comparisonConfigText({
                                    count: a.media.count,
                                    items: a.media.items,
                                  })
                                : ""
                            }
                            right={
                              b.media?.available
                                ? comparisonConfigText({
                                    count: b.media.count,
                                    items: b.media.items,
                                  })
                                : ""
                            }
                            lang={lang}
                          />
                          <details>
                            <summary>
                              {bilingual(lang, "Run 输入配置参考", "Run input config reference")}
                            </summary>
                            <ComparisonDiffView
                              left={
                                a.run_reference?.input?.available
                                  ? comparisonConfigText(a.run_reference.input.config)
                                  : ""
                              }
                              right={
                                b.run_reference?.input?.available
                                  ? comparisonConfigText(b.run_reference.input.config)
                                  : ""
                              }
                              lang={lang}
                            />
                          </details>
                        </section>
                      ) : (
                        <section>
                          <h3>{bilingual(lang, "Prompt 对比", "Prompt comparison")}</h3>
                          <div className="comparison-original">
                            <div className="prompt-meta">
                              <PromptMetaBadge prompt={a.prompt} lang={lang} />
                            </div>
                            <div className="prompt-meta">
                              <PromptMetaBadge prompt={b.prompt} lang={lang} />
                            </div>
                          </div>
                          <ComparisonDiffView
                            left={a.prompt?.text || ""}
                            right={b.prompt?.text || ""}
                            lang={lang}
                          />
                          <details>
                            <summary>
                              {bilingual(
                                lang,
                                "Run 模板／示例参考（不是该 Case 实际输入）",
                                "Run template / example reference (not this Case's actual input)",
                              )}
                            </summary>
                            <div className="comparison-original">
                              <div className="prompt-meta">
                                <PromptMetaBadge prompt={a.run_reference?.prompt} lang={lang} />
                              </div>
                              <div className="prompt-meta">
                                <PromptMetaBadge prompt={b.run_reference?.prompt} lang={lang} />
                              </div>
                            </div>
                            <ComparisonDiffView
                              left={a.run_reference?.prompt?.template || ""}
                              right={b.run_reference?.prompt?.template || ""}
                              lang={lang}
                            />
                          </details>
                        </section>
                      );
                    })()
                  )
                ) : null}
              </div>
            </div>

            <div className="dialog-actions">
              <small className="comparison-case-shortcuts">
                <kbd>↑</kbd>
                <kbd>↓</kbd> {bilingual(lang, "上一个 / 下一个 Case", "Previous / next Case")}
              </small>
              <button
                className="button button-primary"
                type="button"
                onClick={() => setDialogIssueId("")}
              >
                {bilingual(lang, "关闭", "Close")}
              </button>
            </div>
          </div>
        ) : null}
      </dialog>,
        document.body,
      )}
    </div>
  );
};
