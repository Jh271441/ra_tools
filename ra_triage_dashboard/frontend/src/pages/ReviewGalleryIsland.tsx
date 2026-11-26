import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, UiLanguage, withWorkbenchBase } from "../bridge/useWorkbenchBridge";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";
import {
  CASE_PAGE_SIZES,
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { MODEL_LABELS, TRIAGE_LABELS } from "../components/charts/AnalysisCharts";
import {
  GalleryCaseItem,
  GT_FILTER_VALUES,
  IssueCardGrid,
} from "../components/gallery/IssueCardGrid";
import { IssueQueryModal } from "../components/gallery/IssueQueryModal";
import { showToast } from "../components/ui/Toast";
import {
  buildLabelGtFilterOptions,
  comparisonStatusMeta,
  comparisonStatusParam,
  DashboardConfigPayload,
  ISSUE_QUERY_ID_RE,
  joinFilterList,
  labelGtFilterSelection,
  normalizedGtRelationFilters,
  parseComparisonStatuses,
  parseFilterList,
  readLegacyConfig,
  splitLabelGtFilterSelection,
  UiInfoPopover,
} from "../utils/analysisHelpers";

export interface ReviewGalleryIslandProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
  isAdmin: boolean;
  canWrite: boolean;
  identityPending: boolean;
}

interface ModelRunItem {
  id: string;
  name: string;
  is_default?: boolean;
  inferred_baseline_ids?: string[];
  baseline_prediction_count?: number;
  failure_count?: number;
}

interface ModelRunsResponse {
  items?: ModelRunItem[];
  default_model_run_id?: string;
  aliases?: Record<string, string>;
}

interface ReviewerItem {
  name: string;
  verified?: boolean;
  verified_count?: number;
  unverified_count?: number;
  review_count?: number;
  model_review_count?: number;
}

interface ModelReviewFacetItem {
  value?: string;
  count?: number;
  verified_count?: number;
  unverified_count?: number;
}

interface WorkAssigneeItem {
  username: string;
  issue_count?: number;
}

interface ReviewWorkSplitOption {
  split_id: string;
  name?: string;
  completed_count?: number;
  assignment_count?: number;
  lifecycle?: string;
  can_review?: boolean;
  baselines?: string[];
  model_run_id?: string;
  workflow_mode?: string;
}

interface ReviewTaskContext {
  id: string;
  name?: string;
  issue_count?: number;
  workflow_mode?: string;
  legacy_no_run?: boolean;
  supplemental_only?: boolean;
  baseline_ids?: string[];
  model_run_id?: string;
}

interface ReviewCasesResponse {
  items: GalleryCaseItem[];
  total: number;
  page?: number;
  page_size?: number;
}

interface ReviewFilterState {
  runId: string;
  runExplicitNone: boolean;
  runInitialized: boolean;
  comparisonStatus: string;
  search: string;
  issueIds: string[];
  gtLabel: string[];
  modelLabel: string[];
  annotationAuthor: string[];
  reviewStatus: string[];
  labelStates: string[];
  gtRelations: string[];
  issueTags: string[];
  commentState: string[];
  targetGroup: string;
  exclusion: string[];
  workAssignee: string[];
  workSplitId: string;
  taskView: string;
  taskProgress: string[];
  workflowMode: string;
  clusterKey: string;
  page: number;
  pageSize: number;
}

interface LegacyReviewBridgeWindow {
  state?: {
    config?: DashboardConfigPayload & {
      default_model_run_id?: string;
      prediction_batch?: { max_issues?: number };
      batch_prediction?: { enabled?: boolean; max_issues?: number };
    };
    selectedCase?: {
      review_assignment?: { split_id?: string; workflow_mode?: string };
    } | null;
    savingAnnotation?: boolean;
  };
  pageUrl?: (page: string, opts?: Record<string, unknown>) => string;
  navigatePage?: (page: string, opts?: Record<string, unknown>) => void;
  openRunImport?: (kind?: string) => void;
  openBatchDraft?: (issueIds: string[], source?: string) => void;
  selectCase?: (issueId: string, opts?: Record<string, unknown>) => Promise<void>;
  loadOverview?: () => Promise<void>;
  renderActiveRun?: () => void;
  renderReview?: (caseData: unknown) => void;
  applyInferredBaselinesFromRun?: (run: ModelRunItem, opts?: { reason?: string }) => Promise<void>;
  setBaselineScopes?: (ids: string[]) => Promise<void>;
  reviewAssignmentRouteOptions?: (item: Record<string, unknown>, target?: string) => Record<string, unknown>;
  syncReviewGalleryState?: (snapshot: Record<string, unknown>) => void;
}

const REVIEW_ALLOCATION_DRAFT_KEY = "manual-review-allocation-draft-v1";

function readReviewFiltersFromUrl(): ReviewFilterState {
  const params = new URLSearchParams(
    typeof window !== "undefined" ? window.location.search : "",
  );
  const rawRun = String(params.get("run") || "").trim();
  const runExplicitNone = rawRun === "none";
  const runId = runExplicitNone ? "" : rawRun;

  const rawComparison = String(params.get("comparison") || "").trim().toLowerCase();
  let comparisonStatus = "";
  if (rawComparison) {
    const parsed = parseComparisonStatuses(rawComparison);
    comparisonStatus = parsed.length
      ? comparisonStatusParam(parsed)
      : rawComparison === "all"
        ? "all"
        : "";
  } else if (params.get("failure") === "1") {
    comparisonStatus = "mismatch";
  }

  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(
    params.get("page_size") || String(DEFAULT_CASE_PAGE_SIZE),
    10,
  );
  const exclusionVal = String(params.get("exclusion") || "all").trim().toLowerCase();
  const commentVal = String(params.get("comment_state") || "all").trim().toLowerCase();
  const workSplitId = /^(?:split|campaign)-[A-Za-z0-9-]{1,120}$/.test(
    params.get("work_split") || "",
  )
    ? params.get("work_split") || ""
    : "";

  return {
    runId,
    runExplicitNone,
    runInitialized: Boolean(runId || runExplicitNone),
    comparisonStatus: comparisonStatus || (runId ? "mismatch" : "all"),
    search: params.get("q") || "",
    issueIds: parseFilterList(params.get("issue_ids")).filter((v) =>
      ISSUE_QUERY_ID_RE.test(v),
    ),
    gtLabel: parseFilterList(params.get("gt")).filter((v) =>
      (GT_FILTER_VALUES as readonly string[]).includes(v),
    ),
    modelLabel: parseFilterList(
      params.get("model_label") || params.get("annotation") || "",
    ).filter((v) => (MODEL_LABELS as readonly string[]).includes(v)),
    annotationAuthor: parseFilterList(params.get("reviewer")),
    reviewStatus: parseFilterList(params.get("status")).filter((v) =>
      ["pending", "in_progress", "completed", "blocked_by_label", "reviewed", "needs_gt_review"].includes(v),
    ),
    labelStates: parseFilterList(params.get("label_state")).filter((v) =>
      ["none", "pending", "resolved", "conflict", "stale", "matches_gt", "needs_gt_review", "unknown"].includes(v),
    ),
    gtRelations: normalizedGtRelationFilters(params.get("gt_relation")),
    issueTags: parseFilterList(params.get("issue_tags")),
    commentState: ["with", "without"].includes(commentVal) ? [commentVal] : [],
    targetGroup: params.get("target_group") || "",
    exclusion: ["included", "excluded"].includes(exclusionVal) ? [exclusionVal] : [],
    workAssignee: parseFilterList(
      params.get("work_assignee") || params.get("assignee") || "",
    ),
    workSplitId,
    taskView: ["targets", "pending"].includes(params.get("task_view") || "")
      ? "targets"
      : "",
    taskProgress: params.has("task_progress")
      ? parseFilterList(params.get("task_progress")).filter((v) =>
          ["pending", "completed"].includes(v),
        )
      : params.get("task_view") === "pending"
        ? ["pending"]
        : [],
    workflowMode:
      params.get("workflow") === "model_only"
        ? "model_review_only"
        : "model_review_and_case_label",
    clusterKey: params.get("evidence") || "",
    page: Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1,
    pageSize: CASE_PAGE_SIZES.includes(rawPageSize as (typeof CASE_PAGE_SIZES)[number])
      ? rawPageSize
      : DEFAULT_CASE_PAGE_SIZE,
  };
}

function buildIssueTagOptions(
  config: DashboardConfigPayload | null | undefined,
  selected: readonly string[],
  lang: UiLanguage,
): MultiSelectOption[] {
  const definitions: ReadonlyArray<[string, string, string]> = [
    ["environment", "环境", "Environment"],
    ["self_intent", "自车意图", "Ego intent"],
    ["false_trigger", "误触发", "False trigger"],
    ["true_trigger", "应该触发", "Should trigger"],
    ["ra", "正确触发", "Correct trigger"],
    ["no_assist", "无需协助", "No assistance"],
  ];
  const catalog = config?.review_tag_catalog || [];
  const options: MultiSelectOption[] = [];
  const known = new Set<string>();
  for (const [groupKey, zh, en] of definitions) {
    const groupLabel = bilingual(lang, zh, en);
    for (const item of catalog) {
      if (
        item.group === groupKey &&
        ((!item.deleted && item.visible !== false) || selected.includes(item.key))
      ) {
        options.push({ value: item.key, label: item.label, group: groupLabel });
        known.add(item.key);
      }
    }
  }
  const otherLabel = bilingual(lang, "其他标签", "Other tags");
  for (const key of selected) {
    if (!known.has(key)) {
      options.push({ value: key, label: key, group: otherLabel });
    }
  }
  return options;
}

export const ReviewGalleryIsland: React.FC<ReviewGalleryIslandProps> = ({
  active,
  lang,
  selectedBaselines,
  isAdmin,
  canWrite,
  identityPending,
}) => {
  const [filters, setFilters] = useState<ReviewFilterState>(() =>
    readReviewFiltersFromUrl(),
  );
  const [searchDraft, setSearchDraft] = useState<string>(filters.search);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [issueQueryOpen, setIssueQueryOpen] = useState(false);
  const [pendingJumpBusy, setPendingJumpBusy] = useState(false);
  const [pendingTargetId, setPendingTargetId] = useState("");
  const prevBaselinesKeyRef = useRef<string>(selectedBaselines.join(","));
  const wasActiveRef = useRef<boolean>(false);
  const lastTaskAppliedIdRef = useRef<string>("");

  const baselinesQuery = useMemo(
    () => (selectedBaselines.length ? selectedBaselines.join(",") : "0508"),
    [selectedBaselines],
  );

  // Read config via legacy state or /api/config fallback
  const legacyConfig = readLegacyConfig() as
    | (DashboardConfigPayload & {
        default_model_run_id?: string;
        prediction_batch?: { max_issues?: number };
        batch_prediction?: { enabled?: boolean; max_issues?: number };
      })
    | null;
  const configQuery = useQuery<
    DashboardConfigPayload & {
      default_model_run_id?: string;
      prediction_batch?: { max_issues?: number };
      batch_prediction?: { enabled?: boolean; max_issues?: number };
    }
  >({
    queryKey: ["review-gallery-config"],
    queryFn: ({ signal }) => apiRequest("/api/dashboard-config", { signal }),
    enabled: active && !legacyConfig?.baselines?.length,
    staleTime: 60_000,
  });
  const effectiveConfig = legacyConfig?.baselines?.length
    ? legacyConfig
    : configQuery.data || legacyConfig;

  // Sync URL -> state on page re-entry or popstate
  useEffect(() => {
    if (active && !wasActiveRef.current) {
      const next = readReviewFiltersFromUrl();
      setFilters(next);
      setSearchDraft(next.search);
      setPendingTargetId("");
    }
    wasActiveRef.current = active;
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const onPopState = () => {
      const next = readReviewFiltersFromUrl();
      setFilters(next);
      setSearchDraft(next.search);
      setPendingTargetId("");
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [active]);

  // Reset page when baseline scope changes from topbar
  useEffect(() => {
    const key = selectedBaselines.join(",");
    if (prevBaselinesKeyRef.current && prevBaselinesKeyRef.current !== key) {
      setFilters((prev) => ({
        ...prev,
        page: 1,
        // Allow re-checking run compatibility against the new dataset unless locked by a task
        runInitialized: prev.workSplitId ? prev.runInitialized : false,
      }));
      setPendingTargetId("");
    }
    prevBaselinesKeyRef.current = key;
  }, [selectedBaselines]);

  // 1. Model Runs query
  const runsQuery = useQuery<ModelRunsResponse>({
    queryKey: ["review-gallery-runs", baselinesQuery],
    queryFn: ({ signal }) =>
      apiRequest(`/api/model-runs?baselines=${encodeURIComponent(baselinesQuery)}`, {
        signal,
      }),
    enabled: active,
    staleTime: 15_000,
  });
  const modelRuns = runsQuery.data?.items || [];

  // Resolve default Run once runs arrive (matching runs.js:506-563)
  useEffect(() => {
    if (!active || !runsQuery.data || filters.workSplitId) return;
    const data = runsQuery.data;
    const items = data.items || [];
    // Resolve run alias if present
    if (filters.runId && data.aliases?.[filters.runId]) {
      const aliased = data.aliases[filters.runId];
      setFilters((prev) => ({ ...prev, runId: aliased, runInitialized: true }));
      return;
    }
    if (filters.runInitialized) {
      // Check if selectedRunId still exists in items
      if (filters.runId && !items.some((r) => r.id === filters.runId)) {
        setFilters((prev) => ({ ...prev, runId: "", comparisonStatus: "all" }));
      }
      return;
    }
    if (filters.runExplicitNone) {
      setFilters((prev) => ({
        ...prev,
        runId: "",
        comparisonStatus: "all",
        runInitialized: true,
      }));
      return;
    }
    const preferred =
      filters.runId ||
      data.default_model_run_id ||
      effectiveConfig?.default_model_run_id ||
      "";
    let candidate = preferred;
    const candidateRun = items.find((r) => r.id === candidate);
    if (candidateRun && Number(candidateRun.baseline_prediction_count || 0) <= 0) {
      candidate = "";
    }
    const resolvedRunId = items.some((r) => r.id === candidate) ? candidate : "";
    const hadExplicitComparison = new URLSearchParams(window.location.search).has("comparison");
    setFilters((prev) => ({
      ...prev,
      runId: resolvedRunId,
      comparisonStatus: resolvedRunId
        ? hadExplicitComparison
          ? prev.comparisonStatus
          : "mismatch"
        : "all",
      runInitialized: true,
    }));
  }, [
    active,
    runsQuery.data,
    filters.workSplitId,
    filters.runId,
    filters.runInitialized,
    filters.runExplicitNone,
    effectiveConfig?.default_model_run_id,
  ]);

  // 2. Review task options (for 复核任务 dropdown)
  const taskOptionsQuery = useQuery<{ items?: ReviewWorkSplitOption[] }>({
    queryKey: ["review-gallery-task-options"],
    queryFn: ({ signal }) =>
      apiRequest("/api/review-work-splits?all_baselines=true&assigned_to_me=true", {
        signal,
      }),
    enabled: active,
    staleTime: 30_000,
  });
  const reviewTaskOptions = useMemo(
    () =>
      (taskOptionsQuery.data?.items || []).filter(
        (item) =>
          !["superseded", "cancelled"].includes(String(item.lifecycle || "")) &&
          item.can_review !== false,
      ),
    [taskOptionsQuery.data],
  );

  // 3. Active Review Task Context query (when workSplitId is set)
  const taskContextQuery = useQuery<{ task?: ReviewTaskContext }>({
    queryKey: ["review-gallery-task-context", filters.workSplitId, filters.taskView],
    queryFn: ({ signal }) => {
      const p = new URLSearchParams();
      if (filters.taskView) p.set("task_view", filters.taskView);
      const urlIssue = new URLSearchParams(window.location.search).get("issue") || "";
      if (urlIssue) p.set("issue_id", urlIssue);
      return apiRequest(
        `/api/review-task-context/${encodeURIComponent(filters.workSplitId)}?${p.toString()}`,
        { signal },
      );
    },
    enabled: active && Boolean(filters.workSplitId),
    retry: 0,
  });
  const activeTask = filters.workSplitId ? taskContextQuery.data?.task || null : null;
  const taskContextError = filters.workSplitId ? taskContextQuery.error : null;

  // Apply task context overrides (locked Run, workflow mode, baseline switch)
  useEffect(() => {
    if (!active || !activeTask) return;
    if (lastTaskAppliedIdRef.current === activeTask.id) return;
    lastTaskAppliedIdRef.current = activeTask.id;
    const taskRunId = activeTask.model_run_id || "";
    const taskMode = activeTask.workflow_mode || "model_review_only";
    setFilters((prev) => ({
      ...prev,
      workSplitId: activeTask.id || prev.workSplitId,
      runId: taskRunId,
      runInitialized: true,
      workflowMode: taskMode,
      comparisonStatus: taskRunId ? prev.comparisonStatus : "all",
    }));
    const taskBaselines = (activeTask.baseline_ids || []).map(String).filter(Boolean);
    if (
      taskBaselines.length > 0 &&
      taskBaselines.join(",") !== selectedBaselines.join(",")
    ) {
      const win = window as unknown as LegacyReviewBridgeWindow;
      win.setBaselineScopes?.(taskBaselines).catch(() => {});
    }
  }, [active, activeTask, selectedBaselines]);

  useEffect(() => {
    if (!filters.workSplitId) {
      lastTaskAppliedIdRef.current = "";
    }
  }, [filters.workSplitId]);

  const effectiveRunId = filters.workSplitId
    ? activeTask?.model_run_id ?? filters.runId
    : filters.runId;
  const effectiveWorkflowMode = activeTask
    ? activeTask.workflow_mode || "model_review_only"
    : canWrite || identityPending
      ? filters.workflowMode
      : "model_review_only";

  const isCombinedTask = Boolean(
    filters.workSplitId && effectiveWorkflowMode === "model_review_and_case_label",
  );
  const showWorkflowMode = Boolean(canWrite || Boolean(activeTask));
  const workflowLocked = Boolean(filters.workSplitId && activeTask);

  const selectedExclusion =
    filters.exclusion.length === 1 && ["included", "excluded"].includes(filters.exclusion[0])
      ? filters.exclusion[0]
      : "all";
  const selectedCommentState =
    filters.commentState.length === 1 && ["with", "without"].includes(filters.commentState[0])
      ? filters.commentState[0]
      : "all";
  const effectiveComparison = effectiveRunId
    ? comparisonStatusParam(parseComparisonStatuses(filters.comparisonStatus))
    : "all";

  // Build filter payload used by /api/cases, /api/work-assignees, export, and allocation draft
  const buildFilterPayload = useCallback(
    (includeAssignee = true): Record<string, string> => {
      const payload: Record<string, string> = {
        baselines: baselinesQuery,
      };
      if (filters.search) payload.search = filters.search;
      const gt = joinFilterList(filters.gtLabel);
      if (gt) payload.gt_label = gt;
      const ml = joinFilterList(filters.modelLabel);
      if (ml) payload.model_label = ml;
      const auth = joinFilterList(filters.annotationAuthor);
      if (auth) payload.annotation_author = auth;
      const rs = joinFilterList(filters.reviewStatus);
      if (rs) payload.review_status = rs;
      if (isCombinedTask) {
        const tp = joinFilterList(filters.taskProgress);
        if (tp) payload.task_progress = tp;
      }
      const ls = joinFilterList(filters.labelStates);
      if (ls) payload.label_state = ls;
      const gtr = joinFilterList(filters.gtRelations);
      if (gtr) payload.gt_relation = gtr;
      const tags = joinFilterList(filters.issueTags);
      if (tags) payload.issue_tags = tags;
      if (filters.targetGroup) payload.target_group = filters.targetGroup;
      if (includeAssignee) {
        const wa = joinFilterList(filters.workAssignee);
        if (wa) payload.work_assignee = wa;
      }
      if (filters.workSplitId) payload.work_split_id = filters.workSplitId;
      if (filters.workSplitId && filters.taskView) payload.task_view = filters.taskView;
      if (selectedExclusion !== "all") payload.exclusion = selectedExclusion;
      if (selectedCommentState !== "all") payload.comment_state = selectedCommentState;
      if (effectiveRunId) payload.model_run_id = effectiveRunId;
      if (effectiveRunId && effectiveComparison !== "all") {
        payload.comparison = effectiveComparison;
      }
      if (filters.clusterKey) payload.missing_evidence = filters.clusterKey;
      if (filters.issueIds.length) payload.issue_ids = filters.issueIds.join(",");
      return payload;
    },
    [
      baselinesQuery,
      filters,
      isCombinedTask,
      selectedExclusion,
      selectedCommentState,
      effectiveRunId,
      effectiveComparison,
    ],
  );

  // 4. Reviewers facet query
  const reviewersQuery = useQuery<ReviewerItem[]>({
    queryKey: ["review-gallery-reviewers", baselinesQuery, effectiveRunId],
    queryFn: async ({ signal }) => {
      const p = new URLSearchParams();
      if (effectiveRunId) p.set("model_run_id", effectiveRunId);
      p.set("baselines", baselinesQuery);
      const q = `?${p.toString()}`;
      const [revData, facets] = await Promise.all([
        apiRequest<{ items?: ReviewerItem[] }>(`/api/reviewers${q}`, { signal }).catch(() => ({
          items: [] as ReviewerItem[],
        })),
        effectiveRunId
          ? apiRequest<{ reviewers?: ModelReviewFacetItem[] }>(`/api/model-review-facets${q}`, {
              signal,
            }).catch(() => null)
          : Promise.resolve(null),
      ]);
      const merged = new Map<string, ReviewerItem>();
      for (const item of revData.items || []) {
        const key = String(item.name || "").toLowerCase();
        if (key) merged.set(key, { ...item });
      }
      for (const item of facets?.reviewers || []) {
        const name = String(item.value || "").trim();
        const key = name.toLowerCase();
        if (!key) continue;
        const cur = merged.get(key);
        const mc = Number(item.count || 0);
        const mv = Number(item.verified_count || 0);
        const mu = Number(item.unverified_count || 0);
        if (cur) {
          cur.model_review_count = mc;
          cur.review_count = Math.max(Number(cur.review_count || 0), mc);
          cur.verified_count = Math.max(Number(cur.verified_count || 0), mv);
          cur.unverified_count = Math.max(Number(cur.unverified_count || 0), mu);
          cur.verified = (cur.verified_count || 0) > 0 && (cur.unverified_count || 0) === 0;
        } else {
          merged.set(key, {
            name,
            verified: mv > 0 && mu === 0,
            verified_count: mv,
            unverified_count: mu,
            review_count: mc,
            model_review_count: mc,
          });
        }
      }
      return Array.from(merged.values());
    },
    enabled: active && (filters.runInitialized || Boolean(filters.workSplitId)),
    staleTime: 20_000,
  });

  // 5. Work assignees facet query
  const assigneeParamsString = useMemo(() => {
    const p = new URLSearchParams();
    const payload = buildFilterPayload(false);
    Object.entries(payload).forEach(([k, v]) => {
      if (k === "work_assignee" || k === "task_progress" || !v) return;
      p.set(k, v);
    });
    return p.toString();
  }, [buildFilterPayload]);

  const workAssigneesQuery = useQuery<{ items?: WorkAssigneeItem[] }>({
    queryKey: ["review-gallery-work-assignees", assigneeParamsString],
    queryFn: ({ signal }) =>
      apiRequest(`/api/work-assignees${assigneeParamsString ? `?${assigneeParamsString}` : ""}`, {
        signal,
      }),
    enabled: active && (filters.runInitialized || Boolean(filters.workSplitId)),
    staleTime: 20_000,
  });

  // 6. Main cases query
  const casesParamsString = useMemo(() => {
    const p = new URLSearchParams(buildFilterPayload(true));
    p.set("page", String(Math.max(1, filters.page)));
    p.set("page_size", String(filters.pageSize));
    p.set("include_thumbnail", "true");
    return p.toString();
  }, [buildFilterPayload, filters.page, filters.pageSize]);

  const readyToLoadCases =
    active &&
    (filters.workSplitId
      ? Boolean(activeTask) && !taskContextQuery.isLoading && !taskContextError
      : filters.runInitialized);

  const casesQuery = useQuery<ReviewCasesResponse>({
    queryKey: ["review-gallery-cases", casesParamsString],
    queryFn: ({ signal }) => apiRequest(`/api/cases?${casesParamsString}`, { signal }),
    enabled: readyToLoadCases,
    placeholderData: (prev) => prev,
  });

  const casesData: ReviewCasesResponse = casesQuery.data || {
    items: [],
    total: 0,
    page: filters.page,
    page_size: filters.pageSize,
  };
  const totalCount = Number(casesData.total || 0);
  const totalPages = Math.max(1, Math.ceil(totalCount / filters.pageSize));

  // Persist URL when user updates gallery filters
  const persistRoute = useCallback(
    (next: ReviewFilterState, clearIssue = true) => {
      if (!active || typeof window === "undefined") return;
      const win = window as unknown as LegacyReviewBridgeWindow;
      const currentIssue = clearIssue
        ? ""
        : new URLSearchParams(window.location.search).get("issue") || "";
      let nextUrl = "";
      if (typeof win.pageUrl === "function") {
        nextUrl = win.pageUrl("review", {
          issue: currentIssue,
          runId: next.runId,
          comparisonStatus: next.runId ? next.comparisonStatus : "all",
          failureOnly: Boolean(next.runId && next.comparisonStatus === "mismatch"),
          search: next.search,
          issueIds: next.issueIds,
          gtLabel: next.gtLabel,
          modelLabel: next.modelLabel,
          annotationAuthor: next.annotationAuthor,
          reviewStatus: next.reviewStatus,
          labelStates: next.labelStates,
          gtRelations: next.gtRelations,
          issueTags: next.issueTags,
          targetGroup: next.targetGroup,
          commentState:
            next.commentState.length === 1 ? next.commentState[0] : "all",
          workAssignee: next.workAssignee,
          workSplitId: next.workSplitId,
          taskView: next.workSplitId ? next.taskView : "",
          taskProgress: next.workSplitId ? next.taskProgress : [],
          baselines: activeTask?.baseline_ids || selectedBaselines,
          forceBaselines: Boolean(activeTask),
          workflowMode: next.workflowMode,
          exclusion: next.exclusion.length === 1 ? next.exclusion[0] : "all",
          clusterKey: next.clusterKey,
          casePage: next.page,
          casePageSize: next.pageSize,
        });
      } else {
        const params = new URLSearchParams();
        if (currentIssue) params.set("issue", currentIssue);
        if (next.runId) {
          params.set("run", next.runId);
          if (next.comparisonStatus && next.comparisonStatus !== "all") {
            params.set("comparison", next.comparisonStatus);
          }
        } else if (next.runExplicitNone) {
          params.set("run", "none");
        }
        if (next.search) params.set("q", next.search);
        if (next.issueIds.length) params.set("issue_ids", next.issueIds.join(","));
        if (next.gtLabel.length) params.set("gt", joinFilterList(next.gtLabel));
        if (next.modelLabel.length) params.set("model_label", joinFilterList(next.modelLabel));
        if (next.annotationAuthor.length) params.set("reviewer", joinFilterList(next.annotationAuthor));
        if (next.reviewStatus.length) params.set("status", joinFilterList(next.reviewStatus));
        if (next.labelStates.length) params.set("label_state", joinFilterList(next.labelStates));
        if (next.gtRelations.length) params.set("gt_relation", joinFilterList(next.gtRelations));
        if (next.issueTags.length) params.set("issue_tags", joinFilterList(next.issueTags));
        if (next.targetGroup) params.set("target_group", next.targetGroup);
        if (next.commentState.length === 1) params.set("comment_state", next.commentState[0]);
        if (next.exclusion.length === 1) params.set("exclusion", next.exclusion[0]);
        if (next.workAssignee.length) params.set("work_assignee", joinFilterList(next.workAssignee));
        if (next.workSplitId) {
          params.set("work_split", next.workSplitId);
          if (next.taskView) params.set("task_view", next.taskView);
          if (next.taskProgress.length) params.set("task_progress", joinFilterList(next.taskProgress));
        }
        if (next.workflowMode === "model_review_only") params.set("workflow", "model_only");
        if (next.clusterKey) params.set("evidence", next.clusterKey);
        if (next.page > 1) params.set("page", String(next.page));
        if (next.pageSize !== DEFAULT_CASE_PAGE_SIZE) params.set("page_size", String(next.pageSize));
        const scopes = activeTask?.baseline_ids || selectedBaselines;
        if (scopes.length) params.set("baselines", scopes.join(","));
        const qs = params.toString();
        nextUrl = `${window.location.pathname}${qs ? `?${qs}` : ""}`;
      }
      const currentUrl = `${window.location.pathname}${window.location.search}`;
      if (nextUrl && nextUrl !== currentUrl) {
        window.history.replaceState({ page: "review" }, "", nextUrl);
      }
    },
    [active, activeTask, selectedBaselines],
  );

  const updateFilters = useCallback(
    (updater: (prev: ReviewFilterState) => ReviewFilterState) => {
      setPendingTargetId("");
      setFilters((prev) => {
        const next = updater(prev);
        persistRoute(next, true);
        return next;
      });
    },
    [persistRoute],
  );

  // Debounce search input -> filters.search & sync URL ?q=
  useEffect(() => {
    const trimmed = searchDraft.trim();
    if (trimmed === filters.search) return;
    const timer = window.setTimeout(() => {
      updateFilters((prev) => ({
        ...prev,
        search: trimmed,
        issueIds: trimmed ? [] : prev.issueIds,
        page: 1,
      }));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [searchDraft, filters.search, updateFilters]);

  // Sync classic bridge state for #reviewDetailView, topbar active Run/overview, and prev/next navigation
  useEffect(() => {
    if (!active) return;
    const win = window as unknown as LegacyReviewBridgeWindow;
    win.syncReviewGalleryState?.({
      selectedRunId: effectiveRunId,
      modelRuns,
      reviewComparisonStatus: effectiveComparison,
      failureOnly: effectiveComparison === "mismatch",
      search: filters.search,
      reviewIssueIds: filters.issueIds,
      gtLabel: filters.gtLabel,
      modelLabel: filters.modelLabel,
      annotationAuthor: filters.annotationAuthor,
      reviewStatus: filters.reviewStatus,
      labelStates: filters.labelStates,
      gtRelations: filters.gtRelations,
      reviewIssueTags: filters.issueTags,
      reviewTargetGroup: filters.targetGroup,
      commentState: selectedCommentState,
      exclusion: selectedExclusion,
      workAssignee: filters.workAssignee,
      reviewWorkSplitId: filters.workSplitId,
      reviewTaskView: filters.taskView,
      reviewTaskProgress: filters.taskProgress,
      reviewTaskContext: activeTask,
      reviewTaskContextError: taskContextError || null,
      reviewWorkflowMode: effectiveWorkflowMode,
      clusterKey: filters.clusterKey,
      casePage: filters.page,
      casePageSize: filters.pageSize,
      cases: casesData.items || [],
      caseTotal: totalCount,
    });
  }, [
    active,
    effectiveRunId,
    modelRuns,
    effectiveComparison,
    filters,
    selectedCommentState,
    selectedExclusion,
    activeTask,
    taskContextError,
    effectiveWorkflowMode,
    casesData.items,
    totalCount,
  ]);

  // Options for all filter pickers
  const runSelectOptions: UiSelectOption[] = useMemo(() => {
    return [
      { value: "", label: bilingual(lang, "未选择模型 Run", "No model Run") },
      ...modelRuns.map((run) => {
        const tag = run.is_default ? bilingual(lang, "默认 · ", "Default · ") : "";
        const inferred = Array.isArray(run.inferred_baseline_ids)
          ? run.inferred_baseline_ids.filter(Boolean)
          : [];
        const setHint = inferred.length ? ` · ${inferred.join("+")}` : "";
        return {
          value: run.id,
          label: `${tag}${run.name}${setHint} · ${bilingual(lang, "当前集", "Set")} ${run.baseline_prediction_count ?? 0} · ${bilingual(lang, "错", "Err")} ${run.failure_count ?? 0}`,
        };
      }),
    ];
  }, [modelRuns, lang]);

  const comparisonOptions: MultiSelectOption[] = useMemo(
    () => [
      { value: "mismatch", label: bilingual(lang, "MISMATCH · 判断失败", "MISMATCH · Incorrect") },
      { value: "match", label: bilingual(lang, "MATCH · 判断一致", "MATCH · Correct") },
      { value: "no_gt", label: bilingual(lang, "NO GT · GT 待复核", "NO GT · Needs GT") },
      { value: "none", label: bilingual(lang, "NONE · 未预测", "NONE · No prediction") },
    ],
    [lang],
  );

  const gtOptions: MultiSelectOption[] = useMemo(
    () => GT_FILTER_VALUES.map((l) => ({ value: l, label: l })),
    [],
  );

  const modelLabelOptions: MultiSelectOption[] = useMemo(
    () => TRIAGE_LABELS.map((l) => ({ value: l, label: l })),
    [],
  );

  const reviewerOptions: MultiSelectOption[] = useMemo(() => {
    const base = (reviewersQuery.data || []).map((item) => {
      const trust =
        (item.verified_count || 0) > 0 && (item.unverified_count || 0) > 0
          ? bilingual(lang, " · 混合身份", " · Mixed")
          : item.verified
            ? " · SSO"
            : "";
      return {
        value: item.name,
        label: `${item.name} · ${bilingual(lang, `${item.review_count ?? 0} 条`, `${item.review_count ?? 0}`)}${trust}`,
      };
    });
    const known = new Set(base.map((o) => o.value));
    for (const sel of filters.annotationAuthor) {
      if (!known.has(sel)) {
        base.push({
          value: sel,
          label: `${sel} · ${bilingual(lang, "当前筛选", "Current filter")}`,
        });
      }
    }
    return base;
  }, [reviewersQuery.data, filters.annotationAuthor, lang]);

  const modelReviewStatusOptions: MultiSelectOption[] = useMemo(
    () => [
      { value: "pending", label: bilingual(lang, "待开始", "Not started") },
      { value: "in_progress", label: bilingual(lang, "待复核", "Needs review") },
      { value: "completed", label: bilingual(lang, "已完成", "Completed") },
    ],
    [lang],
  );

  const labelGtValues = useMemo(
    () => labelGtFilterSelection(filters.labelStates, filters.gtRelations),
    [filters.labelStates, filters.gtRelations],
  );
  const labelGtOptions = useMemo(
    () => buildLabelGtFilterOptions({ lang, labeling: false, selected: labelGtValues }),
    [lang, labelGtValues],
  );

  const issueTagOptions = useMemo(
    () => buildIssueTagOptions(effectiveConfig, filters.issueTags, lang),
    [effectiveConfig, filters.issueTags, lang],
  );

  const discussionOptions: MultiSelectOption[] = useMemo(
    () => [
      { value: "with", label: bilingual(lang, "有讨论", "With discussion") },
      { value: "without", label: bilingual(lang, "无讨论", "Without discussion") },
    ],
    [lang],
  );

  const targetGroupOptions: UiSelectOption[] = useMemo(() => {
    const base: UiSelectOption[] = [
      { value: "", label: bilingual(lang, "全部", "All") },
      { value: "sample", label: bilingual(lang, "抽样集", "Random sample") },
      {
        value: "low",
        label: bilingual(lang, "低置信度（不含抽样）", "Low confidence (excluding samples)"),
      },
    ];
    if (filters.targetGroup && !base.some((o) => o.value === filters.targetGroup)) {
      base.push({ value: filters.targetGroup, label: filters.targetGroup });
    }
    return base;
  }, [filters.targetGroup, lang]);

  const exclusionOptions: MultiSelectOption[] = useMemo(
    () => [
      { value: "included", label: bilingual(lang, "不含问题排除", "Exclude shielded cases") },
      { value: "excluded", label: bilingual(lang, "仅问题排除", "Only shielded cases") },
    ],
    [lang],
  );

  const workAssigneeOptions: MultiSelectOption[] = useMemo(() => {
    const base: MultiSelectOption[] = [
      { value: "__none__", label: bilingual(lang, "未分配", "Unassigned") },
      ...(workAssigneesQuery.data?.items || []).map((item) => ({
        value: item.username,
        label: `${item.username} · ${Number(item.issue_count || 0)}`,
      })),
    ];
    const known = new Set(base.map((o) => o.value));
    for (const sel of filters.workAssignee) {
      if (!known.has(sel)) {
        base.push({
          value: sel,
          label: `${sel} · ${bilingual(lang, "当前筛选", "Current filter")}`,
        });
      }
    }
    return base;
  }, [workAssigneesQuery.data, filters.workAssignee, lang]);

  const reviewTaskSelectOptions: UiSelectOption[] = useMemo(() => {
    const opts: UiSelectOption[] = [
      { value: "", label: bilingual(lang, "综合结果", "Combined results") },
      ...reviewTaskOptions.map((item) => ({
        value: item.split_id,
        label: `${item.name || bilingual(lang, "复核任务", "Review task")} · ${Number(item.completed_count || 0)}/${Number(item.assignment_count || 0)}`,
      })),
    ];
    if (filters.workSplitId && !opts.some((o) => o.value === filters.workSplitId)) {
      const label = activeTask
        ? `${activeTask.name || bilingual(lang, "当前任务", "Current task")} · ${Number(activeTask.issue_count || 0)} ${bilingual(lang, "个 Issue", "Issues")}`
        : bilingual(lang, "当前复核任务", "Current review task");
      opts.push({ value: filters.workSplitId, label });
    }
    return opts;
  }, [reviewTaskOptions, filters.workSplitId, activeTask, lang]);

  const taskProgressOptions: MultiSelectOption[] = useMemo(
    () => [
      { value: "pending", label: bilingual(lang, "待完成", "Pending") },
      { value: "completed", label: bilingual(lang, "已完成", "Completed") },
    ],
    [lang],
  );

  const workflowModeOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "model_review_only", label: bilingual(lang, "仅判错复核", "Model review only") },
      {
        value: "model_review_and_case_label",
        label: bilingual(lang, "判错复核 + 问题标注", "Model review + Case labeling"),
      },
    ],
    [lang],
  );

  // Handlers
  const handleRunChange = async (nextRunId: string) => {
    const prevRunId = effectiveRunId;
    const nextComp = !nextRunId
      ? "all"
      : !prevRunId
        ? "mismatch"
        : filters.comparisonStatus || "mismatch";
    updateFilters((prev) => ({
      ...prev,
      runId: nextRunId,
      runExplicitNone: !nextRunId,
      runInitialized: true,
      workSplitId: nextRunId !== prevRunId ? "" : prev.workSplitId,
      taskView: nextRunId !== prevRunId ? "" : prev.taskView,
      taskProgress: nextRunId !== prevRunId ? [] : prev.taskProgress,
      comparisonStatus: nextComp,
      page: 1,
    }));
    const win = window as unknown as LegacyReviewBridgeWindow;
    if (nextRunId) {
      const run = modelRuns.find((r) => String(r.id) === String(nextRunId));
      if (run && typeof win.applyInferredBaselinesFromRun === "function") {
        await win.applyInferredBaselinesFromRun(run, { reason: "run" }).catch(() => {});
      }
    }
    win.renderActiveRun?.();
    win.loadOverview?.().catch(() => {});
  };

  const handleExitTask = () => {
    updateFilters((prev) => ({
      ...prev,
      workSplitId: "",
      taskView: "",
      taskProgress: [],
      runId: "",
      runExplicitNone: true,
      runInitialized: true,
      comparisonStatus: "all",
      page: 1,
    }));
    const win = window as unknown as LegacyReviewBridgeWindow;
    win.renderActiveRun?.();
    win.loadOverview?.().catch(() => {});
  };

  const handleTaskSelect = (nextSplitId: string) => {
    if (!nextSplitId) {
      handleExitTask();
      return;
    }
    const item = reviewTaskOptions.find((t) => t.split_id === nextSplitId);
    const win = window as unknown as LegacyReviewBridgeWindow;
    if (item && typeof win.pageUrl === "function" && typeof win.reviewAssignmentRouteOptions === "function") {
      window.location.assign(
        win.pageUrl(
          "review",
          win.reviewAssignmentRouteOptions(
            { ...item, baseline_ids: item.baselines, assigned_to_me: true },
            "review",
          ),
        ),
      );
      return;
    }
    updateFilters((prev) => ({ ...prev, workSplitId: nextSplitId, page: 1 }));
  };

  const handleReset = () => {
    setSearchDraft("");
    updateFilters((prev) => ({
      ...prev,
      search: "",
      issueIds: [],
      gtLabel: [],
      modelLabel: [],
      annotationAuthor: [],
      reviewStatus: [],
      labelStates: [],
      gtRelations: [],
      issueTags: [],
      commentState: [],
      targetGroup: "",
      exclusion: [],
      workAssignee: [],
      taskProgress: [],
      clusterKey: "",
      comparisonStatus: prev.runId ? "all" : "all",
      page: 1,
    }));
  };

  const handleExportSelection = () => {
    if (!totalCount) return;
    const p = new URLSearchParams({ format: "xlsx", gallery_scope: "true" });
    Object.entries(buildFilterPayload(true)).forEach(([k, v]) => {
      if (v && v !== "all") p.set(k, v);
    });
    const link = document.createElement("a");
    link.href = withWorkbenchBase(`/api/review-reason-analysis/export?${p.toString()}`);
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  const handleCreateAllocation = () => {
    if (!isAdmin) {
      showToast(bilingual(lang, "仅管理员可创建复核任务。", "Admin access is required."), true);
      return;
    }
    if (!effectiveRunId) {
      showToast(
        bilingual(
          lang,
          "请先选择 Model Run；若只做 Case 标签，请前往 问题标注 > 实验分配。",
          "Select a Model Run first. For Case labels only, use Case labeling > Experiment assignment.",
        ),
        true,
      );
      return;
    }
    if (!totalCount) {
      showToast(bilingual(lang, "当前筛选没有 Issue。", "No Issues match the current filter."), true);
      return;
    }
    const win = window as unknown as LegacyReviewBridgeWindow;
    const draft = {
      filters: {
        ...buildFilterPayload(true),
        failure_only: false,
        comparison_status: effectiveComparison,
      },
      total: totalCount,
      fromReview: true,
      returnUrl: `${window.location.pathname}${window.location.search}`,
    };
    try {
      window.sessionStorage.setItem(REVIEW_ALLOCATION_DRAFT_KEY, JSON.stringify(draft));
    } catch {
      /* ignore storage errors */
    }
    win.navigatePage?.("review-assignments");
  };

  const predictionBatchLimit = Math.min(
    50,
    Number(
      effectiveConfig?.prediction_batch?.max_issues ||
        effectiveConfig?.batch_prediction?.max_issues ||
        50,
    ),
  );
  const predictionDisabled =
    totalCount === 0 || effectiveConfig?.batch_prediction?.enabled === false;

  const handlePredictSelection = () => {
    if (totalCount > predictionBatchLimit) {
      showToast(
        bilingual(
          lang,
          `当前筛选有 ${totalCount} 个 Issue；单批最多 ${predictionBatchLimit} 个，请继续收窄筛选。`,
          `${totalCount} issues selected; batch limit is ${predictionBatchLimit}. Narrow the filter.`,
        ),
        true,
      );
      return;
    }
    const items = casesData.items || [];
    if (items.length !== totalCount) {
      showToast(
        bilingual(
          lang,
          `当前仅加载 ${items.length} / ${totalCount} 个筛选结果，不能创建不完整 Batch。`,
          `Only ${items.length} / ${totalCount} results are loaded on this page; increase page size or narrow filter.`,
        ),
        true,
      );
      return;
    }
    const win = window as unknown as LegacyReviewBridgeWindow;
    win.openBatchDraft?.(
      items.map((it) => it.issue_id),
      "filtered",
    );
  };

  const showNextPendingBtn = Boolean(
    isCombinedTask &&
      activeTask &&
      !taskContextQuery.isLoading &&
      !taskContextError &&
      (filters.taskProgress.length === 0 ||
        (filters.taskProgress.includes("pending") && filters.taskProgress.includes("completed"))),
  );

  const handleJumpNextPending = async () => {
    if (!showNextPendingBtn || pendingJumpBusy) return;
    setPendingJumpBusy(true);
    try {
      const baseParams = new URLSearchParams(buildFilterPayload(true));
      const pendingParams = new URLSearchParams(baseParams);
      pendingParams.set("task_progress", "pending");
      const [queueRes, pendingRes] = await Promise.all([
        apiRequest<{ issue_ids?: string[] }>(`/api/cases/issue-ids?${baseParams.toString()}`),
        apiRequest<{ issue_ids?: string[] }>(`/api/cases/issue-ids?${pendingParams.toString()}`),
      ]);
      const ids = queueRes.issue_ids || [];
      const pendingSet = new Set(pendingRes.issue_ids || []);
      const anchor = pendingTargetId ? ids.indexOf(pendingTargetId) : -1;
      const start = anchor >= 0 ? anchor + 1 : 0;
      const nextIdx = ids.findIndex(
        (id, i) => i >= start && id !== pendingTargetId && pendingSet.has(id),
      );
      if (nextIdx < 0) {
        showToast(
          bilingual(
            lang,
            "当前筛选范围内，后续没有待完成任务。",
            "No further pending tasks in the current filters.",
          ),
        );
        return;
      }
      const targetId = ids[nextIdx];
      const targetPage = Math.floor(nextIdx / filters.pageSize) + 1;
      setPendingTargetId(targetId);
      if (targetPage !== filters.page) {
        setFilters((prev) => {
          const next = { ...prev, page: targetPage };
          persistRoute(next, true);
          return next;
        });
      }
      window.setTimeout(() => {
        const card = document.querySelector<HTMLElement>(
          `#issueList article[data-issue-id="${CSS.escape(targetId)}"]`,
        );
        card?.scrollIntoView?.({ block: "center", inline: "nearest", behavior: "smooth" });
        card?.querySelector<HTMLButtonElement>("[data-open-issue]")?.focus({ preventScroll: true });
      }, 120);
    } catch (err) {
      showToast(err instanceof Error ? err.message : String(err), true);
    } finally {
      setPendingJumpBusy(false);
    }
  };

  const handleOpenIssue = (issueId: string) => {
    const win = window as unknown as LegacyReviewBridgeWindow;
    win.selectCase?.(issueId).catch((err: unknown) => {
      showToast(err instanceof Error ? err.message : String(err), true);
    });
  };

  const casesErrorMessage = casesQuery.isError
    ? casesQuery.error instanceof Error
      ? casesQuery.error.message
      : bilingual(lang, "读取 Issue 列表失败，请重试。", "Failed to load Issues. Please retry.")
    : "";

  const lastCasesErrorRef = useRef<string>("");
  useEffect(() => {
    if (casesQuery.isError && casesErrorMessage && lastCasesErrorRef.current !== casesErrorMessage) {
      lastCasesErrorRef.current = casesErrorMessage;
      showToast(casesErrorMessage, true);
    } else if (!casesQuery.isError) {
      lastCasesErrorRef.current = "";
    }
  }, [casesQuery.isError, casesErrorMessage]);

  // Gallery range summary matching classic renderCasePagination()
  const gallerySummaryText = useMemo(() => {
    if (filters.workSplitId && taskContextQuery.isLoading) {
      return bilingual(lang, "正在加载任务范围", "Loading task scope");
    }
    if (taskContextError) {
      return bilingual(lang, "任务范围加载失败", "Failed to load task scope");
    }
    if (casesQuery.isError) {
      return bilingual(lang, "Issue 列表读取失败", "Failed to load Issues");
    }
    if (!readyToLoadCases || (casesQuery.isLoading && !casesQuery.data)) {
      return bilingual(lang, "正在加载 Issue…", "Loading Issues…");
    }
    if (!totalCount) {
      return bilingual(lang, "当前没有匹配的 Issue", "No matching Issues");
    }
    const from = (filters.page - 1) * filters.pageSize + 1;
    const to = Math.min(filters.page * filters.pageSize, totalCount);
    return bilingual(
      lang,
      `当前 ${from}–${to} / 共 ${totalCount} 条`,
      `Showing ${from}–${to} of ${totalCount}`,
    );
  }, [
    filters.workSplitId,
    filters.page,
    filters.pageSize,
    taskContextQuery.isLoading,
    taskContextError,
    casesQuery.isError,
    readyToLoadCases,
    casesQuery.isLoading,
    casesQuery.data,
    totalCount,
    lang,
  ]);

  const emptyContent = useMemo(() => {
    if (filters.workSplitId && taskContextQuery.isLoading) {
      return (
        <>
          {Array.from({ length: 8 }, (_, idx) => (
            <article
              key={idx}
              className="issue-card issue-card-skeleton"
              aria-label={bilingual(lang, "正在加载任务范围", "Loading task scope")}
            >
              <div className="issue-thumbnail" />
              <div className="issue-card-body">
                <span />
                <span />
                <small>
                  {bilingual(lang, "正在加载任务范围", "Loading task scope")} ·{" "}
                  {filters.workSplitId.slice(0, 18)}
                  {idx === 0 ? "…" : ""}
                </small>
              </div>
            </article>
          ))}
        </>
      );
    }
    if (taskContextError) return null;
    if (casesQuery.isError) {
      return (
        <div className="empty-state issue-grid-empty review-gallery-error-state" role="alert">
          <h2>{bilingual(lang, "Issue 列表读取失败", "Failed to load Issues")}</h2>
          <p>{casesErrorMessage}</p>
          <button
            className="button button-quiet"
            type="button"
            onClick={() => void casesQuery.refetch()}
          >
            {bilingual(lang, "重试", "Retry")}
          </button>
        </div>
      );
    }
    if (!readyToLoadCases || casesQuery.isLoading) {
      return (
        <div className="no-asset issue-grid-empty">
          {bilingual(lang, "正在加载 Issue…", "Loading Issues…")}
        </div>
      );
    }
    const compMeta = comparisonStatusMeta(effectiveComparison, lang);
    const hint =
      effectiveComparison !== "all"
        ? bilingual(
            lang,
            `当前没有符合「${compMeta.label}」的 Issue，可切换模型判断结果或筛选条件。`,
            `No Issues match "${compMeta.label}". Adjust the comparison or filters.`,
          )
        : bilingual(
            lang,
            "当前筛选条件下没有匹配的 Issue。",
            "No Issues match the current filters.",
          );
    return <div className="no-asset issue-grid-empty">{hint}</div>;
  }, [
    filters.workSplitId,
    taskContextQuery.isLoading,
    taskContextError,
    casesQuery.isError,
    casesErrorMessage,
    casesQuery.refetch,
    readyToLoadCases,
    casesQuery.isLoading,
    effectiveComparison,
    lang,
  ]);

  const taskSummaryText = activeTask
    ? `${activeTask.legacy_no_run ? bilingual(lang, "历史任务", "Historical task") : activeTask.name || bilingual(lang, "当前任务", "Current task")} · ${Number(activeTask.issue_count || 0)} ${bilingual(lang, "个 Issue", "Issues")}${activeTask.supplemental_only ? bilingual(lang, " · 任务外补充", " · Supplemental review") : ""}`
    : "";
  const taskDetailsText = activeTask
    ? activeTask.legacy_no_run
      ? bilingual(
          lang,
          "历史无 Run 任务，仅查看原分配范围",
          "Historical task without a Run; original assignment scope only",
        )
      : `${activeTask.workflow_mode === "model_review_and_case_label" ? bilingual(lang, "联合复核", "Combined review") : bilingual(lang, "仅判错复核", "Model review only")} · ${activeTask.supplemental_only ? bilingual(lang, "未分配：提交不计任务进度 · ", "Unassigned: submissions do not count toward task progress · ") : ""}${activeTask.id || ""}`
    : "";

  const runPickerLockedTitle = activeTask
    ? activeTask.legacy_no_run
      ? bilingual(
          lang,
          "历史无 Run 任务仅用于查看原分配范围；退出任务后可选择 Model Run",
          "Historical task without a Run; exit the task to select a Model Run",
        )
      : bilingual(lang, "当前 Model Run 由任务锁定", "Current Model Run is locked by the task")
    : undefined;

  return (
    <div className="ra-review-gallery-root" data-react-island="review">
      <section
        className="review-commandbar"
        aria-label={bilingual(lang, "Review 筛选", "Review filters")}
      >
        <div className="mobile-filter-bar">
          <button
            className="button button-quiet mobile-filter-toggle"
            type="button"
            aria-expanded={mobileFiltersOpen}
            aria-controls="filterForm"
            onClick={() => setMobileFiltersOpen((prev) => !prev)}
          >
            <span>{bilingual(lang, "筛选", "Filters")}</span>
            <span className="mobile-filter-hint">
              {mobileFiltersOpen
                ? bilingual(lang, "收起条件", "Hide filters")
                : bilingual(lang, "展开条件", "Show filters")}
            </span>
          </button>
        </div>

        <form
          className={`review-filters${mobileFiltersOpen ? " is-open" : ""}`}
          id="filterForm"
          data-mobile-filter-panel="reviewFilters"
          onSubmit={(e) => e.preventDefault()}
        >
          <div className="ra-gallery-field filter-model-run">
            <span>{bilingual(lang, "对比模型 Run", "Compare model Run")}</span>
            <UiSelect
              id="modelRunPickerTrigger"
              value={effectiveRunId}
              options={runSelectOptions}
              disabled={Boolean(activeTask)}
              title={runPickerLockedTitle}
              ariaLabel={bilingual(lang, "对比模型 Run", "Compare model Run")}
              onChange={(val) => void handleRunChange(val)}
            />
          </div>

          <div className="ra-gallery-field filter-comparison">
            <span>{bilingual(lang, "模型判断结果", "Model comparison")}</span>
            <MultiSelect
              id="comparisonFilter"
              values={
                effectiveRunId && effectiveComparison !== "all"
                  ? parseComparisonStatuses(effectiveComparison)
                  : []
              }
              options={comparisonOptions}
              lang={lang}
              disabled={!effectiveRunId}
              placeholder={bilingual(lang, "全部结果", "All results")}
              ariaLabel={bilingual(lang, "模型判断结果", "Model comparison filter")}
              onChange={(vals) =>
                updateFilters((prev) => ({
                  ...prev,
                  comparisonStatus: comparisonStatusParam(vals),
                  page: 1,
                }))
              }
            />
          </div>

          <div className="ra-gallery-field filter-search">
            <span>{bilingual(lang, "检索", "Search")}</span>
            <div className="issue-query-control">
              <input
                id="searchInput"
                name="search"
                value={searchDraft}
                onChange={(e) => setSearchDraft(e.target.value)}
                placeholder={bilingual(
                  lang,
                  "Issue ID、场景或关键词",
                  "Issue ID, scene, or keyword",
                )}
                aria-label={bilingual(lang, "检索", "Search")}
                autoComplete="off"
              />
              <button
                className={`button button-quiet issue-query-button${filters.issueIds.length > 0 ? " has-issues" : ""}`}
                id="openIssueQueryButton"
                type="button"
                data-issue-count={String(filters.issueIds.length)}
                title={
                  filters.issueIds.length > 0
                    ? bilingual(
                        lang,
                        `已设置 ${filters.issueIds.length} 个 Issue`,
                        `${filters.issueIds.length} Issues selected`,
                      )
                    : bilingual(lang, "按 Issue 列表查询", "Query an Issue list")
                }
                onClick={() => setIssueQueryOpen(true)}
              >
                {bilingual(lang, "多 Issue", "Multi-Issue")}
              </button>
            </div>
          </div>

          <div className="ra-gallery-field filter-gt">
            <span>GT</span>
            <MultiSelect
              id="gtFilter"
              values={filters.gtLabel}
              options={gtOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部 GT", "All GT")}
              ariaLabel="GT"
              onChange={(vals) => updateFilters((prev) => ({ ...prev, gtLabel: vals, page: 1 }))}
            />
          </div>

          <div className="ra-gallery-field filter-model-label">
            <span>{bilingual(lang, "模型标注", "Model label")}</span>
            <MultiSelect
              id="annotationFilter"
              values={filters.modelLabel}
              options={modelLabelOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部模型标注", "All model labels")}
              ariaLabel={bilingual(lang, "模型标注", "Model label")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, modelLabel: vals, page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field filter-reviewer">
            <span
              title={bilingual(
                lang,
                "按已有复核记录的提交人筛选；任务负责人用于筛选分配对象",
                "Filter by reviewer who submitted a record; Assignee filters assigned owners",
              )}
            >
              {bilingual(lang, "复核提交人", "Reviewer")}
            </span>
            <MultiSelect
              id="reviewerFilter"
              values={filters.annotationAuthor}
              options={reviewerOptions}
              lang={lang}
              disabled={reviewersQuery.isLoading && !reviewersQuery.data}
              placeholder={
                reviewersQuery.isLoading && !reviewersQuery.data
                  ? bilingual(lang, "正在加载复核人…", "Loading reviewers…")
                  : bilingual(lang, "全部复核人", "All reviewers")
              }
              ariaLabel={bilingual(lang, "复核提交人", "Reviewer")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, annotationAuthor: vals, page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field filter-review-status">
            <span className="ra-gallery-ellipsis-label">
              {bilingual(lang, "模型判错复核", "Model review")}
            </span>
            <MultiSelect
              id="reviewStatusFilter"
              values={filters.reviewStatus}
              options={modelReviewStatusOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部判错状态", "All model review statuses")}
              ariaLabel={bilingual(lang, "模型判错复核", "Model review")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, reviewStatus: vals, page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field filter-shared-label-state">
            <div className="filter-field-heading">
              <span>{bilingual(lang, "标注状态 / GT", "Label state / GT")}</span>
              <UiInfoPopover
                id="reviewLabelGtInfo"
                ariaLabel={bilingual(
                  lang,
                  "标注状态与 GT 关系说明",
                  "Label state and GT relation help",
                )}
              >
                {bilingual(
                  lang,
                  "组内任一、组间同时满足。GT 关系比较当前有效标注结论与所选 GT；未形成结论或有分歧的 Case 不计入。GT 缺失只包含已有结论且 GT 为空的 Case。",
                  "Selections within a group use OR; groups use AND. Compare the current resolved label with the selected GT. Unresolved or conflicting cases are excluded. GT missing includes resolved cases whose GT is empty.",
                )}
              </UiInfoPopover>
            </div>
            <MultiSelect
              id="sharedLabelStateFilter"
              values={labelGtValues}
              options={labelGtOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部标注 / GT", "All labels / GT")}
              ariaLabel={bilingual(lang, "标注状态与 GT 关系筛选", "Label state / GT filter")}
              onChange={(vals) => {
                const { labelStates, gtRelations } = splitLabelGtFilterSelection(vals);
                updateFilters((prev) => ({
                  ...prev,
                  labelStates,
                  gtRelations,
                  page: 1,
                }));
              }}
            />
          </div>

          <div className="ra-gallery-field filter-issue-tags">
            <span>{bilingual(lang, "Issue 标签", "Issue tags")}</span>
            <MultiSelect
              id="reviewIssueTagFilter"
              values={filters.issueTags}
              options={issueTagOptions}
              lang={lang}
              searchable
              summaryCount
              groupNavigation
              placeholder={bilingual(lang, "全部 Issue 标签", "All Issue tags")}
              ariaLabel={bilingual(lang, "Issue 标签筛选", "Issue tag filter")}
              title={bilingual(
                lang,
                "同组满足任一标签，不同组同时满足",
                "Match any selected tag within each group, and all selected groups",
              )}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, issueTags: vals, page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field filter-discussion-state">
            <span>{bilingual(lang, "讨论", "Discussion")}</span>
            <MultiSelect
              id="reviewDiscussionFilter"
              values={filters.commentState}
              options={discussionOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部讨论状态", "All discussion states")}
              ariaLabel={bilingual(lang, "讨论", "Discussion state filter")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, commentState: vals, page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field filter-target-group">
            <span>{bilingual(lang, "目标集合", "Target cohort")}</span>
            <UiSelect
              id="reviewTargetGroupPicker"
              value={filters.targetGroup}
              options={targetGroupOptions}
              ariaLabel={bilingual(lang, "目标集合", "Target cohort")}
              title={bilingual(
                lang,
                "按当前版本目标集合筛选；抽样优先于低置信度",
                "Filter current version target cohorts; samples take precedence over low confidence",
              )}
              onChange={(val) =>
                updateFilters((prev) => ({ ...prev, targetGroup: val, page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field filter-exclusion">
            <span>{bilingual(lang, "问题排除", "Issue exclusion")}</span>
            <MultiSelect
              id="reviewExclusionFilter"
              values={filters.exclusion}
              options={exclusionOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部（含问题排除）", "All (including shielded)")}
              ariaLabel={bilingual(lang, "问题排除", "Issue exclusion filter")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, exclusion: vals, page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field filter-assignee">
            <span>{bilingual(lang, "任务负责人", "Assignee")}</span>
            <MultiSelect
              id="workAssigneeFilter"
              values={filters.workAssignee}
              options={workAssigneeOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部负责人", "All assignees")}
              ariaLabel={bilingual(lang, "任务负责人", "Work assignee filter")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, workAssignee: vals, page: 1 }))
              }
            />
          </div>

          <div className="review-task-filter">
            <div className="filter-field-heading">
              <span>{bilingual(lang, "复核任务", "Review task")}</span>
              {Boolean(activeTask && !taskContextError) && (
                <button
                  className="review-task-exit"
                  id="reviewTaskContextExit"
                  type="button"
                  aria-label={bilingual(lang, "退出任务范围", "Exit task scope")}
                  title={bilingual(lang, "退出任务范围", "Exit task scope")}
                  onClick={handleExitTask}
                >
                  ×
                </button>
              )}
              <UiInfoPopover
                id="reviewTaskInfo"
                ariaLabel={bilingual(lang, "复核任务说明", "Review task help")}
              >
                <span>
                  {bilingual(
                    lang,
                    "选择任务后按该任务范围复核；“综合结果”不绑定任务。",
                    "Selecting a task scopes reviews to that task. Combined results is not bound to a task.",
                  )}
                </span>
                {taskSummaryText && (
                  <span className="review-task-summary" id="reviewTaskSummary">
                    {taskSummaryText}
                  </span>
                )}
                {taskDetailsText && <span id="reviewTaskDetails">{taskDetailsText}</span>}
                {!taskOptionsQuery.isLoading && reviewTaskOptions.length === 0 && (
                  <span id="reviewTaskPickerHint">
                    {bilingual(
                      lang,
                      "暂无分配给当前账号的进行中任务；综合结果不绑定任务。",
                      "No active tasks assigned to this account. Combined results is not bound to a task.",
                    )}
                  </span>
                )}
              </UiInfoPopover>
            </div>
            <div className="review-task-filter-row">
              <UiSelect
                id="reviewTaskPicker"
                value={filters.workSplitId}
                options={reviewTaskSelectOptions}
                ariaLabel={bilingual(lang, "复核任务", "Review task")}
                onChange={handleTaskSelect}
              />
            </div>
          </div>

          <div
            className="ra-gallery-field"
            id="reviewTaskProgressField"
            hidden={!isCombinedTask}
          >
            <span
              id="reviewTaskProgressLabel"
              title={bilingual(
                lang,
                "按任务负责人统计：标签确认与模型复核均已提交才算完成；不代表共享标签已形成结论。",
                "By assignee: complete when both label acknowledgement and model review are submitted, regardless of shared label resolution.",
              )}
            >
              {bilingual(lang, "任务状态", "Task status")}
            </span>
            <MultiSelect
              id="reviewTaskProgressFilter"
              values={filters.taskProgress}
              options={taskProgressOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部任务状态", "All task statuses")}
              ariaLabel={bilingual(lang, "任务状态", "Task status")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, taskProgress: vals, page: 1 }))
              }
            />
          </div>

          <div
            className="review-workflow-mode"
            id="reviewWorkflowModeField"
            hidden={!showWorkflowMode}
          >
            <div className="filter-field-heading">
              <span>{bilingual(lang, "复核模式", "Review mode")}</span>
              <UiInfoPopover
                id="reviewModeInfoPanel"
                ariaLabel={bilingual(lang, "复核模式说明", "Review mode help")}
              >
                <span>
                  {bilingual(
                    lang,
                    "选择仅判错复核，或同时填写问题标注。任务可锁定模式。",
                    "Review model judgments only, or also label the Issue. A task may lock this mode.",
                  )}
                </span>
                {workflowLocked && (
                  <span id="reviewWorkflowModeHint">
                    {bilingual(lang, "当前任务已锁定模式", "The current task locks this mode")}
                  </span>
                )}
              </UiInfoPopover>
            </div>
            <UiSelect
              id="reviewWorkflowMode"
              value={effectiveWorkflowMode}
              options={workflowModeOptions}
              disabled={workflowLocked || !canWrite}
              title={
                workflowLocked
                  ? bilingual(lang, "页面模式由当前任务锁定", "The current task locks this mode")
                  : !canWrite
                    ? bilingual(
                        lang,
                        "需要模型复核与 问题标注双重写权限",
                        "Model review and Issue labeling write permissions are required",
                      )
                    : undefined
              }
              ariaLabel={bilingual(lang, "复核模式", "Review mode")}
              onChange={(val) => {
                if (filters.workSplitId) return;
                const nextMode =
                  val === "model_review_and_case_label"
                    ? "model_review_and_case_label"
                    : "model_review_only";
                updateFilters((prev) => ({ ...prev, workflowMode: nextMode }));
                const win = window as unknown as LegacyReviewBridgeWindow;
                if (win.state?.selectedCase) win.renderReview?.(win.state.selectedCase);
              }}
            />
          </div>

          <button
            className="button button-quiet filter-submit"
            id="resetReviewFiltersButton"
            type="button"
            onClick={handleReset}
          >
            {bilingual(lang, "重置", "Reset")}
          </button>
        </form>
      </section>

      <section
        className="review-task-context-error"
        id="reviewTaskContextError"
        hidden={!taskContextError}
      >
        <strong>{bilingual(lang, "任务范围加载失败", "Failed to load task scope")}</strong>
        <span id="reviewTaskContextErrorMessage">
          {taskContextError instanceof Error
            ? taskContextError.message
            : bilingual(lang, "任务上下文暂时不可用。", "Task context is unavailable.")}
        </span>
        <code id="reviewTaskContextErrorId">{filters.workSplitId || "—"}</code>
        <div>
          <button
            className="button button-quiet"
            id="reviewTaskContextRetry"
            type="button"
            onClick={() => void taskContextQuery.refetch()}
          >
            {bilingual(lang, "重试", "Retry")}
          </button>
          <button
            className="button button-quiet"
            id="reviewTaskContextErrorExit"
            type="button"
            onClick={handleExitTask}
          >
            {bilingual(lang, "退出任务范围", "Exit task scope")}
          </button>
        </div>
      </section>

      <section className="gallery-panel">
        <div className="gallery-heading">
          <div>
            <h2>{bilingual(lang, "问题图库", "Issue Gallery")}</h2>
          </div>
          <div className="gallery-heading-actions">
            <div className="review-quick-actions">
              <button
                className="button button-quiet"
                id="reviewUploadModelButton"
                type="button"
                onClick={() => {
                  const win = window as unknown as LegacyReviewBridgeWindow;
                  win.openRunImport?.("model");
                }}
              >
                {bilingual(lang, "上传模型结果", "Upload model results")}
              </button>
              <button
                className="button button-quiet"
                id="exportFilteredIssuesButton"
                type="button"
                disabled={
                  totalCount === 0 ||
                  casesQuery.isError ||
                  Boolean(taskContextError) ||
                  taskContextQuery.isLoading
                }
                title={
                  totalCount > 0
                    ? bilingual(
                        lang,
                        `按复核汇总格式导出当前 ${totalCount} 个 Issue。`,
                        `Export ${totalCount} filtered Issues using the review-summary schema.`,
                      )
                    : bilingual(lang, "当前筛选没有可导出的 Issue。", "No Issues match the current filter.")
                }
                onClick={handleExportSelection}
              >
                {totalCount > 0 && !casesQuery.isError
                  ? bilingual(lang, `导出当前筛选 · ${totalCount}`, `Export selection · ${totalCount}`)
                  : bilingual(lang, "导出当前筛选", "Export selection")}
              </button>
              {isAdmin && (
                <button
                  className="button button-quiet"
                  id="splitFilteredButton"
                  type="button"
                  disabled={
                    totalCount === 0 ||
                    casesQuery.isError ||
                    !effectiveRunId ||
                    Boolean(taskContextError) ||
                    taskContextQuery.isLoading
                  }
                  title={
                    !effectiveRunId
                      ? bilingual(
                          lang,
                          "请先选择 Model Run；若只做 Case 标签，请前往 问题标注 > 实验分配。",
                          "Select a Model Run first. For Case labels only, use Case labeling > Experiment assignment.",
                        )
                      : totalCount > 0 && !casesQuery.isError
                        ? bilingual(
                            lang,
                            `管理员：把当前 ${totalCount} 个筛选 Issue 写入任务负责人；可指定数量，剩余均分。`,
                            `Admin: assign ${totalCount} filtered issues to owners.`,
                          )
                        : bilingual(lang, "当前筛选没有 Issue。", "No Issues match the current filter.")
                  }
                  onClick={handleCreateAllocation}
                >
                  {totalCount > 0 && !casesQuery.isError
                    ? bilingual(lang, `新建分配 · ${totalCount}`, `New allocation · ${totalCount}`)
                    : bilingual(lang, "新建分配", "New allocation")}
                </button>
              )}
              <button
                className={`button button-primary${totalCount > predictionBatchLimit ? " button-limit-warning" : ""}`}
                id="predictFilteredButton"
                type="button"
                disabled={
                  predictionDisabled ||
                  casesQuery.isError ||
                  Boolean(taskContextError) ||
                  taskContextQuery.isLoading
                }
                title={
                  totalCount > predictionBatchLimit
                    ? bilingual(
                        lang,
                        `单批最多 ${predictionBatchLimit} 个 Issue，请继续收窄筛选后再发起。`,
                        `Batch limit is ${predictionBatchLimit} issues; narrow the filter first.`,
                      )
                    : bilingual(
                        lang,
                        `把当前 ${totalCount} 个筛选结果带入 Batch 页面；不会立即运行或自动推送。`,
                        `Carry ${totalCount} filtered issues into Batch; does not run or publish yet.`,
                      )
                }
                onClick={handlePredictSelection}
              >
                {totalCount > 0 && !casesQuery.isError
                  ? bilingual(
                      lang,
                      `预测当前筛选 · ${totalCount}`,
                      `Predict selection · ${totalCount}`,
                    )
                  : bilingual(lang, "预测当前筛选", "Predict selection")}
              </button>
            </div>
            <div className="gallery-heading-meta">
              <button
                className="button button-quiet"
                id="reviewNextPendingTaskButton"
                type="button"
                hidden={!showNextPendingBtn}
                disabled={pendingJumpBusy || casesQuery.isError}
                title={bilingual(
                  lang,
                  "保留筛选和每页条数，首次定位首个待完成任务；再次点击继续向后查找",
                  "Keep filters and page size; first locate the earliest pending task, then click again to continue",
                )}
                onClick={() => void handleJumpNextPending()}
              >
                {pendingJumpBusy
                  ? bilingual(lang, "正在查找…", "Finding…")
                  : bilingual(lang, "下一个待完成", "Next pending")}
              </button>
              <span id="galleryResultSummary">{gallerySummaryText}</span>
              <span className="count-pill" id="caseCount">
                {!readyToLoadCases ||
                casesQuery.isError ||
                (casesQuery.isLoading && !casesQuery.data)
                  ? "—"
                  : String(totalCount)}
              </span>
            </div>
          </div>
        </div>

        <IssueCardGrid
          id="issueList"
          workspace="review"
          items={
            taskContextError ||
            casesQuery.isError ||
            (filters.workSplitId && taskContextQuery.isLoading)
              ? []
              : casesData.items || []
          }
          lang={lang}
          config={effectiveConfig}
          selectedRunId={effectiveRunId}
          selectedIssueId={pendingTargetId}
          highlightedIssueId={pendingTargetId}
          emptyContent={emptyContent}
          onOpenIssue={handleOpenIssue}
        />

        <Pagination
          page={filters.page}
          pageSize={filters.pageSize}
          total={casesQuery.isError ? 0 : totalCount}
          lang={lang}
          loading={casesQuery.isFetching}
          showPageUnit
          disableJumpWhenSinglePage
          labelText={
            readyToLoadCases &&
            !casesQuery.isError &&
            (!casesQuery.isLoading || casesQuery.data)
              ? `${filters.page} / ${totalPages}`
              : "— / —"
          }
          ariaLabel={bilingual(lang, "Issue 分页", "Issue pagination")}
          onPageChange={(nextPage) => updateFilters((prev) => ({ ...prev, page: nextPage }))}
          onPageSizeChange={(nextSize) =>
            updateFilters((prev) => ({ ...prev, pageSize: nextSize, page: 1 }))
          }
        />
      </section>

      <IssueQueryModal
        open={issueQueryOpen}
        lang={lang}
        initialIssueIds={filters.issueIds}
        onApply={(ids) => {
          setSearchDraft("");
          updateFilters((prev) => ({ ...prev, issueIds: ids, search: "", page: 1 }));
        }}
        onClose={() => setIssueQueryOpen(false)}
      />
    </div>
  );
};
