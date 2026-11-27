import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  ColorTheme,
  formatCstTime,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import {
  AnalysisClusterPanelData,
  AnalysisConfusionTable,
  AnalysisDonutGroup,
  AnalysisGtCard,
  AnalysisPieItem,
  AnalysisPieTooltip,
  AnalysisStatusBar,
  analysisPiePalette,
  ConfusionTableRow,
  GtUpdateCounts,
  LabelBadge,
  LabelSummaryRulesDialog,
  MODEL_LABELS,
  modelLabelMatchesGt,
  StatusSegmentItem,
  TRIAGE_LABELS,
  useAnalysisPieTooltip,
} from "../components/charts/AnalysisCharts";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import {
  CASE_PAGE_SIZES,
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";
import {
  annotationExpectedOutput,
  baselineLabelForScope,
  buildLabelGtFilterOptions,
  comparisonStatusMeta,
  comparisonStatusParam,
  DashboardConfigPayload,
  evidenceLabel,
  isTriageLabel,
  ISSUE_QUERY_ID_RE,
  joinFilterList,
  labelGtFilterSelection,
  normalizedGtRelationFilters,
  parseComparisonStatuses,
  parseFilterList,
  parseIssueIdsInput,
  readLegacyConfig,
  readLegacySelectedRunId,
  reviewTagCatalogItem,
  safeExternalUrl,
  safeSameOriginReviewUrl,
  showWorkbenchToast,
  splitLabelGtFilterSelection,
  syncLegacySelectedRunId,
  tagLabel,
  UiInfoPopover,
} from "../utils/analysisHelpers";

export interface AnalysisModelRun {
  id: string;
  name: string;
  is_default?: boolean;
  baseline_prediction_count?: number;
  failure_count?: number;
  inferred_baseline_ids?: string[];
}

interface ModelRunsResponse {
  items?: AnalysisModelRun[];
  aliases?: Record<string, string>;
}

interface ReviewerItem {
  name: string;
  review_count?: number;
  verified?: boolean;
  verified_count?: number;
  unverified_count?: number;
}

interface ReviewersResponse {
  items?: ReviewerItem[];
  analysis_items?: ReviewerItem[];
}

interface ModelReviewFacetsResponse {
  reviewers?: Array<{
    value: string;
    count?: number;
    verified_count?: number;
    unverified_count?: number;
  }>;
}

interface WorkSplitOptionItem {
  split_id: string;
  name?: string;
  created_at?: string;
  completed_count?: number;
  assignment_count?: number;
  created_by?: string;
}

interface AnalysisCaseAnnotation {
  note?: string;
  author?: string;
  author_verified?: boolean;
  created_at?: string;
  review_domain?: string;
  model_review_status?: string;
  review_status?: string;
  expected_output?: string;
  label?: string;
  model_run_id?: string;
  tags?: string[];
  missing_evidence?: string[];
}

export interface ReviewAnalysisCaseItem {
  issue_id: string;
  title?: string;
  scenario?: string;
  baseline_scope?: string;
  gt_label?: string;
  comparison_status?: string;
  model_review_progress?: string;
  review_url?: string;
  voyager_issue_url?: string;
  annotation?: AnalysisCaseAnnotation;
  prediction?: {
    label?: string;
    confidence?: number | null;
    reason?: string;
  };
  case_label_context?: { tags?: string[] };
  multi_review?: {
    agreement?: string;
    completed_count?: number;
    assigned_count?: number;
    output_counts?: Record<string, number>;
    reviews?: Array<{ username: string; expected_output?: string }>;
  } | null;
}

export interface ReviewAnalysisResponse {
  total: number;
  page: number;
  page_size: number;
  page_count: number;
  summary?: {
    latest_reviews?: number;
    with_reason?: number;
    empty_reason?: number;
    with_structured_evidence?: number;
    model_review_status_counts?: {
      pending?: number;
      in_progress?: number;
      blocked_by_label?: number;
      completed?: number;
    };
  };
  scope?: {
    model_run?: { id?: string; name?: string } | null;
    comparison_status?: string;
    exclusion?: string;
    work_split_id?: string;
  };
  gt_update_counts?: GtUpdateCounts;
  confusion?: {
    total?: number;
    matches?: number;
    mismatches?: number;
    none?: number;
    labels?: string[];
    model_labels?: string[];
    rows?: Array<{
      gt_label: string;
      total: number;
      cells: Array<{ model_label: string; count: number }>;
    }>;
  };
  cluster_panels?: AnalysisClusterPanelData[];
  evidence_clusters?: AnalysisPieItem[];
  items?: ReviewAnalysisCaseItem[];
}

interface AnalysisRouteState {
  runId: string;
  explicitNoRun: boolean;
  explicitRunInUrl: boolean;
  comparisonStatus: string;
  explicitComparisonInUrl: boolean;
  issueIds: string[];
  search: string;
  commentState: "all" | "with" | "without";
  commentSearch: string;
  gtLabel: string[];
  modelLabel: string[];
  annotationAuthor: string[];
  reviewStatus: string[];
  chartGt: string;
  chartReview: string;
  labelStates: string[];
  gtRelations: string[];
  missingEvidence: string[];
  sceneTag: string[];
  triggerTag: string[];
  egressTag: string[];
  legacyTag: string;
  exclusion: "all" | "included" | "excluded";
  workAgreement: "all" | "pending" | "agreed" | "conflict";
  workSplitId: string;
  taskView: string;
  page: number;
  pageSize: number;
}

function defaultAnalysisRouteState(): AnalysisRouteState {
  return {
    runId: "",
    explicitNoRun: true,
    explicitRunInUrl: true,
    comparisonStatus: "all",
    explicitComparisonInUrl: false,
    issueIds: [],
    search: "",
    commentState: "all",
    commentSearch: "",
    gtLabel: [],
    modelLabel: [],
    annotationAuthor: [],
    reviewStatus: [],
    chartGt: "",
    chartReview: "",
    labelStates: [],
    gtRelations: [],
    missingEvidence: [],
    sceneTag: [],
    triggerTag: [],
    egressTag: [],
    legacyTag: "",
    exclusion: "all",
    workAgreement: "all",
    workSplitId: "",
    taskView: "",
    page: 1,
    pageSize: DEFAULT_CASE_PAGE_SIZE,
  };
}

function readAnalysisRouteFromUrl(): AnalysisRouteState {
  if (typeof window === "undefined") return defaultAnalysisRouteState();
  const params = new URLSearchParams(window.location.search);
  const rawRun = params.get("run");
  const explicitNoRun = rawRun === "none";
  const explicitRunInUrl = params.has("run");
  const runId = explicitNoRun ? "" : String(rawRun || "").trim();
  const rawComparison = params.get("comparison");
  const explicitComparisonInUrl = params.has("comparison");
  const comparisonStatus = explicitComparisonInUrl
    ? comparisonStatusParam(rawComparison)
    : params.get("failure") === "1"
      ? "mismatch"
      : "all";
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawSize = Number.parseInt(params.get("page_size") || "", 10);
  const rawExcl = String(params.get("exclusion") || "all").trim().toLowerCase();
  const exclusion: "all" | "included" | "excluded" =
    rawExcl === "included" || rawExcl === "excluded" ? rawExcl : "all";
  const rawComment = params.get("comment_state") || "all";
  const commentState: "all" | "with" | "without" =
    rawComment === "with" || rawComment === "without" ? rawComment : "all";
  const rawAgree = params.get("work_agreement") || "all";
  const workAgreement: "all" | "pending" | "agreed" | "conflict" =
    rawAgree === "pending" || rawAgree === "agreed" || rawAgree === "conflict"
      ? rawAgree
      : "all";
  const rawSplit = params.get("work_split") || "";
  const workSplitId = /^(?:split|campaign)-[A-Za-z0-9-]{1,120}$/.test(rawSplit) ? rawSplit : "";

  return {
    runId,
    explicitNoRun,
    explicitRunInUrl,
    comparisonStatus,
    explicitComparisonInUrl,
    issueIds: parseFilterList(params.get("issue_ids")).filter((v) =>
      ISSUE_QUERY_ID_RE.test(v),
    ),
    search: params.get("q") || "",
    commentState,
    commentSearch: params.get("comment_search") || "",
    gtLabel: parseFilterList(params.get("gt")).filter((v) => isTriageLabel(v)),
    modelLabel: parseFilterList(
      params.get("model_label") || params.get("annotation") || "",
    ).filter((v) => (MODEL_LABELS as readonly string[]).includes(v)),
    annotationAuthor: parseFilterList(params.get("reviewer")),
    chartGt: params.get("chart_gt") || "",
    chartReview: params.get("chart_review") || "",
    reviewStatus: parseFilterList(params.get("status")).filter((v) =>
      [
        "pending",
        "in_progress",
        "completed",
        "blocked_by_label",
        "reviewed",
        "needs_gt_review",
      ].includes(v),
    ),
    labelStates: parseFilterList(params.get("label_state")).filter((v) =>
      [
        "none",
        "pending",
        "resolved",
        "conflict",
        "exclusion_pending",
        "stale",
        "matches_gt",
        "needs_gt_review",
        "unknown",
      ].includes(v),
    ),
    gtRelations: normalizedGtRelationFilters(params.get("gt_relation")),
    missingEvidence: parseFilterList(params.get("evidence")),
    sceneTag: parseFilterList(params.get("scene_tag")),
    triggerTag: parseFilterList(params.get("trigger_tag")),
    egressTag: parseFilterList(params.get("egress_tag")),
    legacyTag: params.get("tag") || "",
    exclusion,
    workAgreement,
    workSplitId,
    taskView: workSplitId && params.get("task_view") === "targets" ? "targets" : "",
    page: Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1,
    pageSize: (CASE_PAGE_SIZES as readonly number[]).includes(rawSize)
      ? rawSize
      : DEFAULT_CASE_PAGE_SIZE,
  };
}

function buildAnalysisUrl(state: AnalysisRouteState, baselines: string[]): string {
  const params = new URLSearchParams();
  params.set("run", state.runId || "none");
  params.set("comparison", state.runId ? comparisonStatusParam(state.comparisonStatus) : "all");
  if (state.chartGt) params.set("chart_gt", state.chartGt);
  if (state.chartReview) params.set("chart_review", state.chartReview);
  if (state.search) params.set("q", state.search);
  const validIds = state.issueIds.filter((v) => ISSUE_QUERY_ID_RE.test(v));
  if (validIds.length) params.set("issue_ids", validIds.join(","));
  if (state.commentState !== "all") params.set("comment_state", state.commentState);
  if (state.commentSearch) params.set("comment_search", state.commentSearch);
  if (state.gtLabel.length) params.set("gt", joinFilterList(state.gtLabel));
  if (state.modelLabel.length) params.set("model_label", joinFilterList(state.modelLabel));
  if (state.annotationAuthor.length) {
    params.set("reviewer", joinFilterList(state.annotationAuthor));
  }
  if (state.reviewStatus.length) params.set("status", joinFilterList(state.reviewStatus));
  if (state.labelStates.length) params.set("label_state", joinFilterList(state.labelStates));
  if (state.gtRelations.length) params.set("gt_relation", joinFilterList(state.gtRelations));
  if (state.missingEvidence.length) params.set("evidence", joinFilterList(state.missingEvidence));
  if (state.sceneTag.length) params.set("scene_tag", joinFilterList(state.sceneTag));
  if (state.triggerTag.length) params.set("trigger_tag", joinFilterList(state.triggerTag));
  if (state.egressTag.length) params.set("egress_tag", joinFilterList(state.egressTag));
  if (state.exclusion !== "all") params.set("exclusion", state.exclusion);
  if (state.workAgreement !== "all") params.set("work_agreement", state.workAgreement);
  if (state.workSplitId) params.set("work_split", state.workSplitId);
  if (state.workSplitId && state.taskView) params.set("task_view", state.taskView);
  if (state.page > 1) params.set("page", String(state.page));
  if (state.pageSize !== DEFAULT_CASE_PAGE_SIZE) {
    params.set("page_size", String(state.pageSize));
  }
  if (baselines.length) params.set("baselines", baselines.join(","));
  return `${withWorkbenchBase("/review-analysis")}?${params.toString()}`;
}

function buildAnalysisApiParams(
  state: AnalysisRouteState,
  baselines: string[],
  { format = "", includePagination = true }: { format?: string; includePagination?: boolean } = {},
): URLSearchParams {
  const params = new URLSearchParams();
  if (format) params.set("format", format);
  if (state.runId) params.set("model_run_id", state.runId);
  params.set("comparison", state.runId ? comparisonStatusParam(state.comparisonStatus) : "all");
  const fields: Array<[string, string]> = [
    ["issue_ids", joinFilterList(state.issueIds)],
    ["annotation_author", joinFilterList(state.annotationAuthor)],
    ["review_status", joinFilterList(state.reviewStatus)],
    ["chart_gt", state.chartGt], ["chart_review", state.chartReview],
    ["label_state", joinFilterList(state.labelStates)],
    ["gt_relation", joinFilterList(state.gtRelations)],
    ["gt_label", joinFilterList(state.gtLabel)],
    ["model_label", joinFilterList(state.modelLabel)],
    ["missing_evidence", joinFilterList(state.missingEvidence)],
    ["scene_tag", joinFilterList(state.sceneTag)],
    ["trigger_tag", joinFilterList(state.triggerTag)],
    ["egress_tag", joinFilterList(state.egressTag)],
    ["search", state.search],
    ["comment_state", state.commentState === "all" ? "" : state.commentState],
    ["comment_search", state.commentSearch],
  ];
  if (state.exclusion !== "all") params.set("exclusion", state.exclusion);
  if (state.workAgreement !== "all") params.set("work_agreement", state.workAgreement);
  if (state.workSplitId) params.set("work_split_id", state.workSplitId);
  if (state.workSplitId && state.taskView) params.set("task_view", state.taskView);
  for (const [k, v] of fields) {
    if (v) params.set(k, v);
  }
  if (includePagination) {
    params.set("page", String(Math.max(1, Number(state.page) || 1)));
    params.set("page_size", String(state.pageSize));
  }
  if (baselines.length) params.set("baselines", baselines.join(","));
  return params;
}

function reviewStatusLabel(status: string | null | undefined, lang: UiLanguage): string {
  switch (String(status || "")) {
    case "pending":
      return bilingual(lang, "待开始", "Pending");
    case "in_progress":
    case "blocked_by_label":
      return bilingual(lang, "待复核", "Needs review");
    case "completed":
      return bilingual(lang, "已完成", "Completed");
    case "reviewed":
      return bilingual(lang, "与 GT 一致", "Matches GT");
    case "needs_gt_review":
      return bilingual(lang, "GT 待复核", "GT needs review");
    default:
      return String(status || "") || bilingual(lang, "已记录", "Recorded");
  }
}

function analysisExclusionLabel(value: string, lang: UiLanguage): string {
  if (value === "included") return bilingual(lang, "不含问题排除", "Exclude shielded cases");
  if (value === "excluded") return bilingual(lang, "仅问题排除", "Only shielded cases");
  return bilingual(lang, "全部（含问题排除）", "All (including shielded)");
}

export interface ReviewAnalysisPageProps {
  active: boolean;
  lang: UiLanguage;
  theme: ColorTheme;
  selectedBaselines: string[];
}

export const ReviewAnalysisPage: React.FC<ReviewAnalysisPageProps> = ({
  active,
  lang,
  theme,
  selectedBaselines,
}) => {
  const [route, setRoute] = useState<AnalysisRouteState>(readAnalysisRouteFromUrl);
  const [issueDraft, setIssueDraft] = useState<string>(() => route.issueIds.join(", "));
  const [searchDraft, setSearchDraft] = useState<string>(() => route.search);
  const [commentSearchDraft, setCommentSearchDraft] = useState<string>(
    () => route.commentSearch,
  );
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [rulesModalMode, setRulesModalMode] = useState<null | "gt">(null);
  const [historyBusyIssue, setHistoryBusyIssue] = useState<string | null>(null);
  const debounceTimerRef = useRef<number | null>(null);
  const caseListRef = useRef<HTMLDivElement | null>(null);
  const legacyTagAppliedRef = useRef(false);

  const { tooltip, tipRef, showTooltip, hideTooltip } = useAnalysisPieTooltip();
  const baselinesKey = selectedBaselines.join(",");

  // Sync from popstate
  useEffect(() => {
    if (!active) return;
    const onPopState = () => {
      const next = readAnalysisRouteFromUrl();
      setRoute(next);
      setIssueDraft(next.issueIds.join(", "));
      setSearchDraft(next.search);
      setCommentSearchDraft(next.commentSearch);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [active]);

  // Dashboard config (tag + evidence catalog)
  const legacyConfig = readLegacyConfig();
  const configQuery = useQuery<DashboardConfigPayload>({
    queryKey: ["dashboard-config", baselinesKey],
    queryFn: ({ signal }) =>
      apiRequest<DashboardConfigPayload>(
        baselinesKey
          ? `/api/dashboard-config?baselines=${encodeURIComponent(baselinesKey)}`
          : "/api/dashboard-config",
        { signal },
      ),
    enabled: active && !legacyConfig?.review_tag_catalog?.length,
    staleTime: 60_000,
  });
  const config = legacyConfig?.review_tag_catalog?.length ? legacyConfig : configQuery.data;

  // Apply legacy `?tag=...` parameter once config catalog is available (1:1 classic routing.js:898-908).
  useEffect(() => {
    if (!route.legacyTag || legacyTagAppliedRef.current || !config?.review_tag_catalog?.length) {
      return;
    }
    const item = config.review_tag_catalog.find((entry) => entry.key === route.legacyTag);
    legacyTagAppliedRef.current = true;
    if (!item) return;
    setRoute((prev) => {
      if (item.section === "scene" && !prev.sceneTag.length) {
        return { ...prev, sceneTag: [prev.legacyTag], legacyTag: "" };
      }
      if (item.section === "interaction_decision" && !prev.triggerTag.length) {
        return { ...prev, triggerTag: [prev.legacyTag], legacyTag: "" };
      }
      if (item.section === "egress" && !prev.egressTag.length) {
        return { ...prev, egressTag: [prev.legacyTag], legacyTag: "" };
      }
      return { ...prev, legacyTag: "" };
    });
  }, [route.legacyTag, config]);

  // Model runs catalog
  const runsQuery = useQuery<ModelRunsResponse>({
    queryKey: ["analysis-model-runs", baselinesKey],
    queryFn: ({ signal }) =>
      apiRequest<ModelRunsResponse>(
        baselinesKey
          ? `/api/model-runs?baselines=${encodeURIComponent(baselinesKey)}`
          : "/api/model-runs",
        { signal },
      ),
    enabled: active,
    staleTime: 30_000,
  });
  const runs = runsQuery.data?.items || [];

  // Reconcile runId with aliases / team default when runs finish loading
  useEffect(() => {
    if (!active || !runsQuery.isSuccess) return;
    const aliases = runsQuery.data?.aliases || {};
    setRoute((prev) => {
      if (prev.explicitNoRun) return prev;
      let targetRun = prev.runId;
      if (targetRun && aliases[targetRun]) {
        targetRun = aliases[targetRun];
      }
      if (targetRun && !runs.some((r) => r.id === targetRun)) {
        targetRun = "";
      }
      if (!targetRun && !prev.explicitRunInUrl) {
        const legacySelected = readLegacySelectedRunId();
        if (legacySelected && runs.some((r) => r.id === legacySelected)) {
          targetRun = legacySelected;
        } else {
          const defaultRun =
            runs.find((r) => r.is_default && Number(r.baseline_prediction_count || 0) > 0) ||
            runs.find((r) => r.is_default);
          if (defaultRun) targetRun = defaultRun.id;
        }
      }
      const nextComparison = targetRun
        ? prev.explicitComparisonInUrl
          ? prev.comparisonStatus
          : config?.default_failure_only
            ? "mismatch"
            : prev.comparisonStatus
        : "all";
      if (
        targetRun === prev.runId &&
        nextComparison === prev.comparisonStatus &&
        prev.explicitRunInUrl
      ) {
        return prev;
      }
      syncLegacySelectedRunId(targetRun, nextComparison);
      return {
        ...prev,
        runId: targetRun,
        explicitRunInUrl: true,
        comparisonStatus: nextComparison,
      };
    });
  }, [active, runsQuery.isSuccess, runsQuery.data, runs, config?.default_failure_only]);

  // Persist URL when route changes (only after runs resolve if initial URL omitted `run`)
  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    if (!route.explicitRunInUrl && runsQuery.isLoading) return;
    const nextUrl = buildAnalysisUrl(route, selectedBaselines);
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (nextUrl !== currentUrl) {
      window.history.replaceState(
        { ...(window.history.state || {}), page: "analysis" },
        "",
        nextUrl,
      );
    }
  }, [active, route, selectedBaselines, runsQuery.isLoading]);

  // Reviewers facet (/api/reviewers + /api/model-review-facets)
  const reviewersQuery = useQuery<ReviewerItem[]>({
    queryKey: ["analysis-reviewers", route.runId, baselinesKey],
    queryFn: async ({ signal }) => {
      const p = new URLSearchParams();
      if (route.runId) p.set("model_run_id", route.runId);
      if (baselinesKey) p.set("baselines", baselinesKey);
      const qs = p.toString() ? `?${p.toString()}` : "";
      const [baseRes, facetsRes] = await Promise.all([
        apiRequest<ReviewersResponse>(`/api/reviewers${qs}`, { signal }).catch(
          () => ({ items: [], analysis_items: [] }) as ReviewersResponse,
        ),
        route.runId
          ? apiRequest<ModelReviewFacetsResponse>(`/api/model-review-facets${qs}`, {
              signal,
            }).catch(() => null)
          : Promise.resolve(null),
      ]);
      const baseItems = Array.isArray(baseRes.analysis_items)
        ? baseRes.analysis_items
        : baseRes.items || [];
      const merged = new Map<string, ReviewerItem>(
        baseItems.map((item) => [String(item.name || "").toLowerCase(), { ...item }]),
      );
      for (const item of facetsRes?.reviewers || []) {
        const name = String(item.value || "").trim();
        const key = name.toLowerCase();
        if (!key) continue;
        const count = Number(item.count || 0);
        const verifiedCount = Number(item.verified_count || 0);
        const unverifiedCount = Number(item.unverified_count || 0);
        const existing = merged.get(key);
        if (existing) {
          existing.review_count = Math.max(Number(existing.review_count || 0), count);
          existing.verified_count = Math.max(Number(existing.verified_count || 0), verifiedCount);
          existing.unverified_count = Math.max(
            Number(existing.unverified_count || 0),
            unverifiedCount,
          );
          existing.verified =
            (existing.verified_count || 0) > 0 && (existing.unverified_count || 0) === 0;
        } else {
          merged.set(key, {
            name,
            review_count: count,
            verified_count: verifiedCount,
            unverified_count: unverifiedCount,
            verified: verifiedCount > 0 && unverifiedCount === 0,
          });
        }
      }
      return Array.from(merged.values());
    },
    enabled: active,
    staleTime: 30_000,
  });

  // Work split options
  const workSplitsQuery = useQuery<WorkSplitOptionItem[]>({
    queryKey: ["analysis-work-splits", route.runId, baselinesKey],
    queryFn: async ({ signal }) => {
      const p = new URLSearchParams();
      if (route.runId) p.set("model_run_id", route.runId);
      if (baselinesKey) p.set("baselines", baselinesKey);
      const res = await apiRequest<{ items?: WorkSplitOptionItem[] }>(
        `/api/review-work-splits?${p.toString()}`,
        { signal },
      );
      return res.items || [];
    },
    enabled: active,
    staleTime: 30_000,
  });

  // Main analysis query
  const apiParamsString = useMemo(
    () => buildAnalysisApiParams(route, selectedBaselines, { includePagination: true }).toString(),
    [route, selectedBaselines],
  );

  const analysisQuery = useQuery<ReviewAnalysisResponse>({
    queryKey: ["review-reason-analysis", apiParamsString],
    queryFn: ({ signal }) =>
      apiRequest<ReviewAnalysisResponse>(`/api/review-reason-analysis?${apiParamsString}`, {
        signal,
      }),
    enabled: active && (route.explicitRunInUrl || !runsQuery.isLoading),
    placeholderData: (prev) => prev,
  });

  const data = analysisQuery.data;
  const focusDetailOnLoad = useRef(window.location.hash === "#analysisCaseList");
  useEffect(() => {
    if (active && data && !analysisQuery.isPlaceholderData && focusDetailOnLoad.current && caseListRef.current) {
      focusDetailOnLoad.current = false;
      caseListRef.current.focus({ preventScroll: true });
      caseListRef.current.scrollIntoView({ block: "start" });
    }
  }, [active, data, analysisQuery.isPlaceholderData]);

  const chartHref = (filters: Partial<typeof route>) =>
    buildAnalysisUrl({ ...route, ...filters, page: 1 }, selectedBaselines) + "#analysisCaseList";


  // Debounced text inputs (Issue IDs, Comment content, Search reasons)
  const scheduleDraftCommit = useCallback(
    (updater: (prev: AnalysisRouteState) => AnalysisRouteState) => {
      if (debounceTimerRef.current !== null) {
        window.clearTimeout(debounceTimerRef.current);
      }
      debounceTimerRef.current = window.setTimeout(() => {
        debounceTimerRef.current = null;
        setRoute((prev) => ({ ...updater(prev), page: 1 }));
      }, 220);
    },
    [],
  );

  useEffect(() => {
    return () => {
      if (debounceTimerRef.current !== null) {
        window.clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  // Filter options
  const runOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "不叠加模型输出", "No model overlay") },
      ...runs.map((run) => {
        const tag = run.is_default ? bilingual(lang, "默认 · ", "Default · ") : "";
        const countStr = bilingual(
          lang,
          `${run.baseline_prediction_count ?? 0} 条 · 错 ${run.failure_count ?? 0}`,
          `${run.baseline_prediction_count ?? 0} · ${run.failure_count ?? 0} wrong`,
        );
        return { value: run.id, label: `${tag}${run.name} · ${countStr}` };
      }),
    ],
    [runs, lang],
  );

  const comparisonOptions: MultiSelectOption[] = useMemo(
    () => [
      { value: "mismatch", label: bilingual(lang, "MISMATCH（判错）", "MISMATCH") },
      { value: "match", label: bilingual(lang, "MATCH（判对）", "MATCH") },
      { value: "no_gt", label: bilingual(lang, "NO GT（无 GT）", "NO GT") },
      { value: "none", label: bilingual(lang, "NONE（未覆盖）", "NONE") },
    ],
    [lang],
  );

  const reviewerOptions: MultiSelectOption[] = useMemo(() => {
    const baseOpts: MultiSelectOption[] = (reviewersQuery.data || []).map((item) => {
      const trust =
        (item.verified_count || 0) > 0 && (item.unverified_count || 0) > 0
          ? bilingual(lang, " · 含历史未核验", " · mixed identity")
          : item.verified
            ? " · SSO"
            : "";
      const countText = bilingual(
        lang,
        `${item.review_count ?? 0} 条`,
        `${item.review_count ?? 0}`,
      );
      return { value: item.name, label: `${item.name} · ${countText}${trust}` };
    });
    const known = new Set(baseOpts.map((o) => o.value));
    for (const selected of route.annotationAuthor) {
      if (!known.has(selected)) {
        baseOpts.push({
          value: selected,
          label: `${selected} · ${bilingual(lang, "当前筛选", "Current filter")}`,
        });
      }
    }
    return baseOpts;
  }, [reviewersQuery.data, route.annotationAuthor, lang]);

  const reviewStatusOptions: MultiSelectOption[] = useMemo(
    () => [
      { value: "pending", label: bilingual(lang, "待开始", "Pending") },
      { value: "in_progress", label: bilingual(lang, "待复核", "Needs review") },
      { value: "completed", label: bilingual(lang, "已完成", "Completed") },
    ],
    [lang],
  );

  const workAgreementOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "all", label: bilingual(lang, "全部", "All") },
      { value: "pending", label: bilingual(lang, "未完成", "Pending") },
      { value: "agreed", label: bilingual(lang, "一致", "Agreed") },
      { value: "conflict", label: bilingual(lang, "冲突", "Conflict") },
    ],
    [lang],
  );

  const workSplitOptions: UiSelectOption[] = useMemo(() => {
    const opts: UiSelectOption[] = [
      { value: "", label: bilingual(lang, "综合结果", "Combined results") },
      ...(workSplitsQuery.data || []).map((item) => {
        const splitId = String(item.split_id || "").trim();
        const date = item.created_at ? formatCstTime(item.created_at, lang) : "";
        const progress = `${Number(item.completed_count || 0)}/${Number(
          item.assignment_count || 0,
        )}`;
        const owner = String(item.created_by || "").trim();
        const label = [item.name || splitId.slice(0, 14), progress, date, owner]
          .filter(Boolean)
          .join(" · ");
        return { value: splitId, label };
      }),
    ];
    if (route.workSplitId && !opts.some((o) => o.value === route.workSplitId)) {
      opts.push({
        value: route.workSplitId,
        label: bilingual(lang, "当前复核任务", "Current review task"),
      });
    }
    return opts;
  }, [workSplitsQuery.data, route.workSplitId, lang]);

  const gtOptions: MultiSelectOption[] = useMemo(
    () => TRIAGE_LABELS.map((label) => ({ value: label, label })),
    [],
  );

  const modelLabelOptions: MultiSelectOption[] = useMemo(
    () => MODEL_LABELS.map((label) => ({ value: label, label })),
    [],
  );

  const labelGtSelected = useMemo(
    () => labelGtFilterSelection(route.labelStates, route.gtRelations),
    [route.labelStates, route.gtRelations],
  );

  const labelGtOptions = useMemo(
    () => buildLabelGtFilterOptions({ lang, labeling: false, selected: labelGtSelected }),
    [lang, labelGtSelected],
  );

  const exclusionOptions: MultiSelectOption[] = useMemo(
    () => [
      { value: "included", label: bilingual(lang, "不含问题排除", "Exclude shielded cases") },
      { value: "excluded", label: bilingual(lang, "仅问题排除", "Only shielded cases") },
    ],
    [lang],
  );

  const evidenceOptions: MultiSelectOption[] = useMemo(
    () =>
      (config?.missing_evidence_catalog || [])
        .filter((item) => !item.deleted)
        .map((item) => ({ value: item.key, label: item.label })),
    [config?.missing_evidence_catalog],
  );

  const buildTagOptions = useCallback(
    (section: string): MultiSelectOption[] => {
      const groupLabels: Record<string, string> = {
        environment: bilingual(lang, "环境", "Environment"),
        self_intent: bilingual(lang, "自车意图", "Ego intent"),
        false_trigger: "误触发",
        true_trigger: bilingual(lang, "应该触发", "Should trigger"),
        ra: "正确触发",
        no_assist: "无需协助",
      };
      return (config?.review_tag_catalog || [])
        .filter((item) => item.visible !== false && !item.deleted && item.section === section)
        .map((item) => ({
          value: item.key,
          label: item.label,
          group: groupLabels[item.group || "other"] || item.group || "other",
        }));
    },
    [config?.review_tag_catalog, lang],
  );

  const sceneOptions = useMemo(() => buildTagOptions("scene"), [buildTagOptions]);
  const triggerOptions = useMemo(
    () => buildTagOptions("interaction_decision"),
    [buildTagOptions],
  );
  const egressOptions = useMemo(() => buildTagOptions("egress"), [buildTagOptions]);

  const commentStateOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "all", label: bilingual(lang, "全部评论", "All comments") },
      { value: "with", label: bilingual(lang, "有评论", "With comments") },
      { value: "without", label: bilingual(lang, "无评论", "Without comments") },
    ],
    [lang],
  );

  // Handlers
  const handleRunChange = async (nextRunId: string) => {
    const previouslyHadRun = Boolean(route.runId);
    const nextComparison = !nextRunId
      ? "all"
      : previouslyHadRun
        ? route.comparisonStatus
        : "mismatch";
    syncLegacySelectedRunId(nextRunId, nextComparison);
    setRoute((prev) => ({
      ...prev,
      runId: nextRunId,
      explicitNoRun: !nextRunId,
      explicitRunInUrl: true,
      comparisonStatus: nextComparison,
      explicitComparisonInUrl: true,
      workSplitId: nextRunId !== prev.runId ? "" : prev.workSplitId,
      taskView: nextRunId !== prev.runId ? "" : prev.taskView,
      page: 1,
    }));
    const run = runs.find((item) => item.id === nextRunId);
    const win = window as unknown as {
      applyInferredBaselinesFromRun?: (
        runObj: AnalysisModelRun,
        opts: { reason: string; reloadActivePage: boolean },
      ) => Promise<unknown>;
      loadOverview?: () => Promise<unknown>;
    };
    if (run && typeof win.applyInferredBaselinesFromRun === "function") {
      await win.applyInferredBaselinesFromRun(run, {
        reason: "run",
        reloadActivePage: false,
      });
    }
    void win.loadOverview?.();
  };

  const handleDownloadExport = (format: "csv" | "xlsx" | "trail_xlsx") => {
    const params = buildAnalysisApiParams(route, selectedBaselines, {
      format,
      includePagination: false,
    });
    const link = document.createElement("a");
    link.href = withWorkbenchBase(`/api/review-reason-analysis/export?${params.toString()}`);
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  };

  const handleReset = () => {
    if (debounceTimerRef.current !== null) {
      window.clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
    setIssueDraft("");
    setSearchDraft("");
    setCommentSearchDraft("");
    syncLegacySelectedRunId("", "all");
    setRoute(defaultAnalysisRouteState());
  };

  const handleOpenModelHistory = async (issueId: string) => {
    if (historyBusyIssue === issueId) return;
    setHistoryBusyIssue(issueId);
    try {
      const caseData = await apiRequest(`/api/cases/${encodeURIComponent(issueId)}`);
      const win = window as unknown as {
        openHistoryDialog?: (kind: string, data: unknown) => void;
      };
      win.openHistoryDialog?.("model", caseData);
    } catch (err) {
      showWorkbenchToast(err instanceof Error ? err.message : String(err), true);
    } finally {
      setHistoryBusyIssue(null);
    }
  };

  const handleOpenDiscussion = (issueId: string, runId: string) => {
    const win = window as unknown as {
      openAnalysisDiscussion?: (
        id: string,
        opts: { runId: string; source: string },
      ) => Promise<void>;
    };
    if (typeof win.openAnalysisDiscussion === "function") {
      win.openAnalysisDiscussion(issueId, { runId, source: "analysis" }).catch((err) => {
        showWorkbenchToast(err instanceof Error ? err.message : String(err), true);
      });
    }
  };

  // Derived visualizations
  const summary = data?.summary || {};
  const reviewScopeLabel = useMemo(() => {
    const run = data?.scope?.model_run;
    const comp = comparisonStatusParam(data?.scope?.comparison_status || "all");
    const compLabels = parseComparisonStatuses(comp)
      .map((s) => comparisonStatusMeta(s, lang).label)
      .join(" / ");
    const excl = data?.scope?.exclusion || "all";
    const exclSuffix = excl === "all" ? "" : ` · ${analysisExclusionLabel(excl, lang)}`;
    const base = run
      ? `${run.name}${comp === "all" ? "" : ` · ${compLabels}`}${exclSuffix}`
      : `${bilingual(lang, "全部最新 Review", "All latest reviews")}${exclSuffix}`;
    const splitSuffix = data?.scope?.work_split_id
      ? ` · ${bilingual(lang, "本次任务新增", "This task only")}`
      : "";
    return `${base}${splitSuffix}`;
  }, [data?.scope, lang]);

  const statusItems: StatusSegmentItem[] = useMemo(() => {
    const counts = summary.model_review_status_counts || {};
    return [
      {
        key: "pending",
        cssKey: "pending",
        label: reviewStatusLabel("pending", lang),
        count: Number(counts.pending || 0),
        description: bilingual(lang, "尚未开始模型判错复核", "Model review has not started"),
      },
      {
        key: "in_progress",
        cssKey: "in_progress",
        label: reviewStatusLabel("in_progress", lang),
        count: Number(counts.in_progress || 0) + Number(counts.blocked_by_label || 0),
        description: bilingual(lang, "模型判错复核正在进行", "Model review is in progress"),
      },
      {
        key: "completed",
        cssKey: "completed",
        label: reviewStatusLabel("completed", lang),
        count: Number(counts.completed || 0),
        description: bilingual(lang, "模型判错复核已完成", "Model review is complete"),
      },
    ];
  }, [summary.model_review_status_counts, lang]);

  const statusTotal = statusItems.reduce((sum, item) => sum + item.count, 0);

  const confusionData = useMemo(() => {
    const run = data?.scope?.model_run;
    const confusion = data?.confusion || {};
    if (!run) {
      return {
        state: "no-run" as const,
        summaryText: bilingual(
          lang,
          "选择 Model Run 后展示混淆统计",
          "Select a Model Run to show confusion stats",
        ),
        emptyText: bilingual(
          lang,
          "尚未选择可比较的 Model Run。",
          "No comparable Model Run selected.",
        ),
        columnLabels: [] as string[],
        rows: [] as ConfusionTableRow[],
      };
    }
    const summaryText = `${run.name} · MATCH ${confusion.matches || 0} · MISMATCH ${
      confusion.mismatches || 0
    } · NONE ${confusion.none || 0}`;
    if (!confusion.total) {
      return {
        state: "empty" as const,
        summaryText,
        emptyText: bilingual(
          lang,
          "当前筛选范围内暂无可比较的预测结果。",
          "No comparable predictions in the current filter scope.",
        ),
        columnLabels: [] as string[],
        rows: [] as ConfusionTableRow[],
      };
    }
    const rawLabels = confusion.model_labels || confusion.labels || [...TRIAGE_LABELS];
    const columnLabels = rawLabels.map((lbl) =>
      lbl === "NONE" ? bilingual(lang, "未输出", "NONE") : lbl,
    );
    const rows: ConfusionTableRow[] = (confusion.rows || []).map((row) => ({
      gtLabel: row.gt_label,
      total: Number(row.total || 0),
      cells: (row.cells || []).map((cell) => {
        const displayModelLabel =
          cell.model_label === "NONE"
            ? bilingual(lang, "未输出", "NONE")
            : cell.model_label;
        const tone: "match" | "mismatch" | "none" | "" =
          cell.model_label === "NONE"
            ? "none"
            : modelLabelMatchesGt(cell.model_label, row.gt_label)
              ? "match"
              : cell.count
                ? "mismatch"
                : "";
        return {
          colLabel: displayModelLabel,
          count: Number(cell.count || 0),
          tone,
          title: `GT ${row.gt_label} · ${bilingual(lang, "模型", "Model")} ${displayModelLabel}: ${cell.count}`,
        };
      }),
    }));
    return { state: "ready" as const, summaryText, emptyText: "", columnLabels, rows };
  }, [data?.scope?.model_run, data?.confusion, lang]);

  const localizeClusterLabel = useCallback(
    (key: string, fallback: string) => {
      if (lang !== "en") return fallback;
      const map: Record<string, string> = {
        evidence: "Missing evidence",
        scene: "Scene",
        trigger: "Trigger decision",
        egress: "Egress",
        environment: "Environment",
        self_intent: "Ego intent",
        all: "Missing evidence",
      };
      return map[key] || fallback;
    },
    [lang],
  );

  const clusterPanels: AnalysisClusterPanelData[] = useMemo(() => {
    const panels = data?.cluster_panels || [];
    if (panels.length) {
      return panels.map((panel) => ({
        ...panel,
        label: localizeClusterLabel(panel.key, panel.label),
        groups: (panel.groups || []).map((group) => ({
          ...group,
          label: localizeClusterLabel(group.key, group.label),
        })),
      }));
    }
    if (!data) return [];
    return [
      {
        key: "evidence",
        label: bilingual(lang, "缺失信息", "Missing evidence"),
        layout: "single",
        groups: [
          {
            key: "all",
            label: bilingual(lang, "缺失信息", "Missing evidence"),
            annotated_count: Number(data.summary?.with_structured_evidence || 0),
            items: data.evidence_clusters || [],
          },
        ],
      },
    ];
  }, [data, lang, localizeClusterLabel]);

  if (!active) return null;

  const page = Number(data?.page || route.page || 1);
  const pageCount = Math.max(1, Number(data?.page_count || 1));
  const items = data?.items || [];
  const exclusionSelected = route.exclusion === "all" ? [] : [route.exclusion];
  const comparisonSelected = route.runId ? parseComparisonStatuses(route.comparisonStatus) : [];

  return (
    <div className="ra-review-analysis-root" data-react-island="analysis">
      <section className="page-card analysis-filter-card">
        <div className="mobile-filter-bar">
          <button
            className="button button-quiet mobile-filter-toggle"
            type="button"
            aria-expanded={mobileFiltersOpen}
            aria-controls="reviewAnalysisFilterForm"
            onClick={() => setMobileFiltersOpen((prev) => !prev)}
          >
            {bilingual(lang, "筛选", "Filters")}
            <span className="mobile-filter-hint">
              {mobileFiltersOpen
                ? bilingual(lang, "收起条件", "Hide filters")
                : bilingual(lang, "展开条件", "Show filters")}
            </span>
          </button>
        </div>

        <form
          className={`analysis-filters${mobileFiltersOpen ? " is-open" : ""}`}
          id="reviewAnalysisFilterForm"
          onSubmit={(e) => {
            e.preventDefault();
            if (debounceTimerRef.current !== null) {
              window.clearTimeout(debounceTimerRef.current);
              debounceTimerRef.current = null;
            }
            setRoute((prev) => ({
              ...prev,
              issueIds: parseIssueIdsInput(issueDraft).ids,
              search: searchDraft.trim(),
              commentSearch: commentSearchDraft.trim(),
              page: 1,
            }));
          }}
        >
          <div className="ra-analysis-field analysis-run-filter">
            <span>{bilingual(lang, "对比模型 Run", "Compare model Run")}</span>
            <UiSelect
              id="analysisRunPicker"
              value={route.runId}
              options={runOptions}
              ariaLabel={bilingual(lang, "对比模型 Run", "Compare model Run")}
              onChange={(val) => void handleRunChange(val)}
            />
          </div>

          <label className="analysis-issue-filter">
            <span>Issue</span>
            <textarea
              className="analysis-issue-input"
              id="analysisIssueInput"
              rows={1}
              maxLength={4096}
              value={issueDraft}
              placeholder={bilingual(
                lang,
                "Issue ID，支持多个",
                "Issue IDs, multiple supported",
              )}
              autoComplete="off"
              onChange={(e) => {
                const val = e.target.value;
                setIssueDraft(val);
                scheduleDraftCommit((prev) => ({
                  ...prev,
                  issueIds: parseIssueIdsInput(val).ids,
                }));
              }}
            />
          </label>

          <div className="ra-analysis-field analysis-comparison-filter">
            <span>{bilingual(lang, "模型判断结果", "Model comparison")}</span>
            <MultiSelect
              id="analysisComparisonFilter"
              values={comparisonSelected}
              options={comparisonOptions}
              lang={lang}
              disabled={!route.runId}
              placeholder={bilingual(lang, "全部结果", "All results")}
              ariaLabel={bilingual(lang, "模型判断结果", "Model comparison")}
              onChange={(values) => {
                const nextStatus = comparisonStatusParam(values);
                syncLegacySelectedRunId(route.runId, nextStatus);
                setRoute((prev) => ({
                  ...prev,
                  comparisonStatus: nextStatus,
                  explicitComparisonInUrl: true,
                  page: 1,
                }));
              }}
            />
          </div>

          <div className="ra-analysis-field analysis-reviewer-filter">
            <span>{bilingual(lang, "复核人", "Reviewer")}</span>
            <MultiSelect
              id="analysisReviewerFilter"
              values={route.annotationAuthor}
              options={reviewerOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部复核人", "All reviewers")}
              ariaLabel={bilingual(lang, "复核人", "Reviewer")}
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, annotationAuthor: values, page: 1 }))
              }
            />
          </div>

          <div className="ra-analysis-field filter-review-status analysis-review-status-filter">
            <span title={bilingual(lang, "模型判错复核状态", "Model error review status")}>
              {bilingual(lang, "模型判错复核", "Model review")}
            </span>
            <MultiSelect
              id="analysisStatusFilter"
              values={route.reviewStatus}
              options={reviewStatusOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部状态", "All statuses")}
              ariaLabel={bilingual(lang, "模型判错复核", "Model review")}
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, reviewStatus: values, page: 1 }))
              }
            />
          </div>

          <div
            className="ra-analysis-field analysis-work-agreement-filter"
            id="analysisWorkAgreementField"
          >
            <span>{bilingual(lang, "多人复核结果", "Multi-review agreement")}</span>
            <UiSelect
              id="analysisWorkAgreementPicker"
              value={route.workAgreement}
              options={workAgreementOptions}
              ariaLabel={bilingual(lang, "多人复核结果", "Multi-review agreement")}
              onChange={(val) =>
                setRoute((prev) => ({
                  ...prev,
                  workAgreement: val as AnalysisRouteState["workAgreement"],
                  page: 1,
                }))
              }
            />
          </div>

          <div className="analysis-work-split-filter">
            <div className="analysis-scope-heading">
              <span id="analysisScopeLabel">
                {bilingual(lang, "Review 数据范围", "Review data scope")}
              </span>
              <UiInfoPopover
                id="analysisScopeInfo"
                ariaLabel={bilingual(lang, "Review 数据范围说明", "Review data scope help")}
              >
                <strong>{bilingual(lang, "Review 数据范围", "Review data scope")}</strong>
                <span>
                  {bilingual(
                    lang,
                    "仅列出当前数据集和 Run 对应的复核任务。找不到任务时，请切换到任务对应的数据集和 Run；没有可选任务不代表没有复核记录。",
                    "Only tasks for the selected dataset and Run are listed. If a task is missing, switch to its dataset and Run. An empty task list does not mean there are no review records.",
                  )}
                </span>
                <span>
                  {bilingual(
                    lang,
                    "“综合结果”汇总当前范围内的复核；选择任务后，仅查看该任务已提交的复核结果。",
                    "Combined results aggregates reviews in the current scope. Selecting a task shows only reviews submitted for that task.",
                  )}
                </span>
              </UiInfoPopover>
            </div>
            <UiSelect
              id="analysisWorkSplitPicker"
              value={route.workSplitId}
              options={workSplitOptions}
              ariaLabel={bilingual(lang, "Review 数据范围", "Review data scope")}
              onChange={(val) =>
                setRoute((prev) => ({
                  ...prev,
                  workSplitId: val,
                  taskView: "",
                  page: 1,
                }))
              }
            />
          </div>

          <div className="ra-analysis-field analysis-gt-filter">
            <span>GT</span>
            <MultiSelect
              id="analysisGtFilter"
              values={route.gtLabel}
              options={gtOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部 GT", "All GT")}
              ariaLabel="GT"
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, gtLabel: values, page: 1 }))
              }
            />
          </div>

          <div className="ra-analysis-field analysis-label-gt-filter">
            <div className="filter-field-heading">
              <span>{bilingual(lang, "标注状态 / GT", "Label state / GT")}</span>
              <UiInfoPopover
                id="analysisLabelGtInfo"
                ariaLabel={bilingual(lang, "标注状态与 GT 筛选说明", "Label state / GT filter help")}
              >
                <span>
                  {bilingual(
                    lang,
                    "组内任一、组间同时满足。GT 关系比较当前有效标注结论与所选 GT；未形成结论或有分歧的 Case 不计入。GT 缺失只包含已有结论且 GT 为空的 Case。",
                    "Selections within a group use OR; groups use AND. Compare the current resolved label with the selected GT. Unresolved or conflicting cases are excluded. GT missing includes resolved cases whose GT is empty.",
                  )}
                </span>
              </UiInfoPopover>
            </div>
            <MultiSelect
              id="analysisLabelGtFilter"
              values={labelGtSelected}
              options={labelGtOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部标注 / GT", "All labels / GT")}
              ariaLabel={bilingual(lang, "标注状态 / GT", "Label state / GT")}
              onChange={(values) => {
                const split = splitLabelGtFilterSelection(values);
                setRoute((prev) => ({
                  ...prev,
                  labelStates: split.labelStates,
                  gtRelations: split.gtRelations,
                  page: 1,
                }));
              }}
            />
          </div>

          <div className="ra-analysis-field analysis-model-label-filter">
            <span>{bilingual(lang, "模型预测", "Model prediction")}</span>
            <MultiSelect
              id="analysisModelLabelFilter"
              values={route.modelLabel}
              options={modelLabelOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部模型预测", "All model predictions")}
              ariaLabel={bilingual(lang, "模型预测", "Model prediction")}
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, modelLabel: values, page: 1 }))
              }
            />
          </div>

          <div className="ra-analysis-field analysis-exclusion-filter">
            <span>{bilingual(lang, "问题排除", "Issue exclusion")}</span>
            <MultiSelect
              id="analysisExclusionFilter"
              values={exclusionSelected}
              options={exclusionOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部（含问题排除）", "All (including shielded)")}
              ariaLabel={bilingual(lang, "问题排除", "Issue exclusion")}
              onChange={(values) => {
                const nextExclusion: "all" | "included" | "excluded" =
                  values.length === 1 && (values[0] === "included" || values[0] === "excluded")
                    ? values[0]
                    : "all";
                setRoute((prev) => ({ ...prev, exclusion: nextExclusion, page: 1 }));
              }}
            />
          </div>

          <div className="ra-analysis-field analysis-evidence-filter">
            <span>{bilingual(lang, "缺失信息", "Missing evidence")}</span>
            <MultiSelect
              id="analysisEvidenceFilter"
              values={route.missingEvidence}
              options={evidenceOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部缺失信息", "All missing evidence")}
              ariaLabel={bilingual(lang, "缺失信息", "Missing evidence")}
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, missingEvidence: values, page: 1 }))
              }
            />
          </div>

          <div className="ra-analysis-field analysis-tag-filter">
            <span>{bilingual(lang, "场景", "Scene")}</span>
            <MultiSelect
              id="analysisSceneFilter"
              values={route.sceneTag}
              options={sceneOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部场景", "All scenes")}
              ariaLabel={bilingual(lang, "场景", "Scene")}
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, sceneTag: values, page: 1 }))
              }
            />
          </div>

          <div className="ra-analysis-field analysis-trigger-filter">
            <span>{bilingual(lang, "触发判定", "Trigger decision")}</span>
            <MultiSelect
              id="analysisTriggerFilter"
              values={route.triggerTag}
              options={triggerOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部触发判定", "All trigger decisions")}
              ariaLabel={bilingual(lang, "触发判定", "Trigger decision")}
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, triggerTag: values, page: 1 }))
              }
            />
          </div>

          <div className="ra-analysis-field analysis-egress-filter">
            <span>{bilingual(lang, "如何脱困", "Egress")}</span>
            <MultiSelect
              id="analysisEgressFilter"
              values={route.egressTag}
              options={egressOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部脱困方式", "All egress")}
              ariaLabel={bilingual(lang, "如何脱困", "Egress")}
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, egressTag: values, page: 1 }))
              }
            />
          </div>

          <div className="ra-analysis-field analysis-comment-state-filter">
            <span>{bilingual(lang, "评论状态", "Comment status")}</span>
            <UiSelect
              id="analysisCommentStatePicker"
              value={route.commentState}
              options={commentStateOptions}
              ariaLabel={bilingual(lang, "评论状态", "Comment status")}
              onChange={(val) =>
                setRoute((prev) => ({
                  ...prev,
                  commentState: val as AnalysisRouteState["commentState"],
                  page: 1,
                }))
              }
            />
          </div>

          <label className="analysis-comment-search-filter">
            <span>{bilingual(lang, "评论内容", "Comment content")}</span>
            <input
              id="analysisCommentSearchInput"
              value={commentSearchDraft}
              placeholder={bilingual(
                lang,
                "搜索当前 Run 的评论内容",
                "Search comments in this Run",
              )}
              autoComplete="off"
              onChange={(e) => {
                const val = e.target.value;
                setCommentSearchDraft(val);
                scheduleDraftCommit((prev) => ({ ...prev, commentSearch: val.trim() }));
              }}
            />
          </label>

          <div className="analysis-search-actions">
            <label className="analysis-search-filter">
              <span>{bilingual(lang, "检索 Review 原因", "Search review reasons")}</span>
              <input
                id="analysisSearchInput"
                value={searchDraft}
                placeholder={bilingual(
                  lang,
                  "人工原因、复核人、Tags 或缺失信息",
                  "Reason, reviewer, tags, or missing evidence",
                )}
                autoComplete="off"
                onChange={(e) => {
                  const val = e.target.value;
                  setSearchDraft(val);
                  scheduleDraftCommit((prev) => ({ ...prev, search: val.trim() }));
                }}
              />
            </label>
            <div className="analysis-filter-actions">
              <button
                className="button button-quiet"
                id="exportReviewAnalysisCsvButton"
                type="button"
                onClick={() => handleDownloadExport("csv")}
              >
                {bilingual(lang, "导出 CSV", "Export CSV")}
              </button>
              <button
                className="button button-quiet"
                id="exportReviewAnalysisXlsxButton"
                type="button"
                onClick={() => handleDownloadExport("xlsx")}
              >
                {bilingual(lang, "导出 XLSX", "Export XLSX")}
              </button>
              <button
                className="button button-quiet"
                id="exportTrailExpectedOutputButton"
                type="button"
                onClick={() => handleDownloadExport("trail_xlsx")}
              >
                {bilingual(lang, "导出 GT 更新表", "Export GT update")}
              </button>
              <button
                className="button button-quiet"
                id="resetReviewAnalysisButton"
                type="button"
                onClick={handleReset}
              >
                {bilingual(lang, "重置", "Reset")}
              </button>
            </div>
          </div>
        </form>
      </section>

      <section className="analysis-summary-grid" aria-label="Analysis overview">
        <article className="analysis-stat-card">
          <span>{bilingual(lang, "最新 Review", "Latest reviews")}</span>
          <strong id="analysisReviewCount">{data ? summary.latest_reviews ?? 0 : "—"}</strong>
          <small id="analysisReviewScope" title={reviewScopeLabel}>
            {data
              ? reviewScopeLabel
              : bilingual(lang, "当前筛选范围", "Current filter scope")}
          </small>
        </article>

        <article className="analysis-stat-card">
          <span>{bilingual(lang, "已填写原因", "With reason")}</span>
          <strong id="analysisReasonCount">{data ? summary.with_reason ?? 0 : "—"}</strong>
          <small id="analysisEmptyReasonCount">
            {data
              ? bilingual(
                  lang,
                  `${summary.empty_reason ?? 0} 条未填写`,
                  `${summary.empty_reason ?? 0} empty`,
                )
              : "—"}
          </small>
        </article>

        <article className="analysis-stat-card">
          <span>{bilingual(lang, "结构化缺失信息", "Structured missing evidence")}</span>
          <strong id="analysisEvidenceCount">
            {data ? summary.with_structured_evidence ?? 0 : "—"}
          </strong>
          <small>{bilingual(lang, "至少选择 1 项", "Select at least 1")}</small>
        </article>
      </section>

      <section
        className="analysis-decision-grid analysis-has-gt"
        aria-label="GT review and model comparison"
      >
        <section
          className="page-card analysis-review-status-card"
          aria-labelledby="analysisReviewStatusTitle"
        >
          <div className="section-heading analysis-review-status-heading">
            <div>
              <h3 id="analysisReviewStatusTitle">
                {bilingual(lang, "模型判错复核状态", "Model review status")}
              </h3>
            </div>
            <small id="analysisReviewStatusSummary">
              {data
                ? bilingual(
                    lang,
                    `${statusTotal} 条 · 当前筛选范围`,
                    `${statusTotal} reviews · current filter scope`,
                  )
                : bilingual(lang, "正在统计当前筛选范围…", "Aggregating the current filter scope…")}
            </small>
          </div>
          <div
            className="analysis-review-status-chart"
            id="analysisReviewStatusChart"
            aria-live="polite"
          >
            {data ? (
              <AnalysisStatusBar
                statuses={statusItems}
                lang={lang}
                detailHref={chartReview => chartHref({ chartReview })}
                emptyText={bilingual(lang, "暂无 Review", "No reviews")}
              />
            ) : (
              <div className="analysis-empty">
                {bilingual(lang, "正在统计状态比例…", "Building status proportions…")}
              </div>
            )}
          </div>
        </section>

        <div className="analysis-gt-card-mount" id="analysisGtCardMount" aria-live="polite">
          {data && (
            <AnalysisGtCard
              counts={data.gt_update_counts}
              detailHref={chartGt => chartHref({ chartGt })}
              prefix="analysis"
              lang={lang}
              onOpenRules={() => setRulesModalMode("gt")}
              onShowTooltip={showTooltip}
              onHideTooltip={hideTooltip}
            />
          )}
        </div>

        <section
          className="page-card analysis-confusion-card"
          aria-labelledby="analysisConfusionTitle"
        >
          <div className="section-heading analysis-confusion-heading">
            <div>
              <h3 id="analysisConfusionTitle">
                {bilingual(lang, "GT × 模型预测混淆矩阵", "GT × Model prediction confusion matrix")}
              </h3>
            </div>
            <small id="analysisConfusionSummary">
              {data
                ? confusionData.summaryText
                : bilingual(lang, "正在统计当前筛选范围…", "Aggregating the current filter scope…")}
            </small>
          </div>
          <div
            className="analysis-confusion-wrap"
            id="analysisConfusionMatrix"
            aria-live="polite"
          >
            {!data ? (
              <div className="analysis-empty">
                {bilingual(lang, "正在统计混淆矩阵…", "Building confusion matrix…")}
              </div>
            ) : confusionData.state === "ready" ? (
              <AnalysisConfusionTable
                cornerHeader={bilingual(lang, "GT ↓ / 模型 →", "GT ↓ / Model →")}
                columnLabels={confusionData.columnLabels}
                rows={confusionData.rows}
                totalLabel={bilingual(lang, "合计", "Total")}
              />
            ) : (
              <div className="analysis-empty">{confusionData.emptyText}</div>
            )}
          </div>
        </section>
      </section>

      <section
        className="analysis-cluster-grid"
        id="analysisClusterPanels"
        aria-label="Structured clusters"
      >
        {!data ? (
          <div className="analysis-empty">
            {bilingual(lang, "正在统计结构化字段…", "Aggregating structured fields…")}
          </div>
        ) : (
          clusterPanels.map((panel) => {
            const groups = panel.groups || [];
            const dual = panel.layout === "dual" || groups.length > 1;
            const palette = analysisPiePalette(panel.key, theme);
            return (
              <article
                key={panel.key}
                className={`page-card analysis-cluster-card layout-${panel.layout || "single"}`}
                data-panel={panel.key}
              >
                <div className="section-heading">
                  <div>
                    <h3>{panel.label}</h3>
                  </div>
                </div>
                <div className={`analysis-pie-groups ${dual ? "dual" : "single"}`}>
                  {groups.length ? (
                    groups.map((group) => (
                      <AnalysisDonutGroup
                        key={group.key}
                        group={group}
                        palette={palette}
                        dual={dual}
                        lang={lang}
                        onShowTooltip={showTooltip}
                        onHideTooltip={hideTooltip}
                      />
                    ))
                  ) : (
                    <div className="analysis-empty">
                      {bilingual(lang, "暂无聚类数据", "No cluster data")}
                    </div>
                  )}
                </div>
              </article>
            );
          })
        )}
      </section>

      <section className="page-card analysis-case-card">
        <div className="section-heading">
          <div>
            <h3>{bilingual(lang, "Review 原因明细", "Review reason details")}</h3>
          </div>
          <small id="analysisCaseSummary">
            {(route.chartGt || route.chartReview) && (
              <span className="chart-detail-filter">
                <a href={chartHref({ chartGt: "", chartReview: "" })}>
                  {bilingual(lang, "清除图表筛选", "Clear chart filter")}
                </a>
              </span>
            )}
            {analysisQuery.isLoading && !data
              ? bilingual(lang, "正在加载最新 Review…", "Loading latest reviews…")
              : bilingual(
                  lang,
                  `${data?.total || 0} 条最新 Review · 当前显示 ${items.length} 条`,
                  `${data?.total || 0} latest reviews · showing ${items.length}`,
                )}
          </small>
        </div>

        <div className="analysis-case-list" id="analysisCaseList" tabIndex={-1} ref={caseListRef} aria-live="polite">
          {analysisQuery.isError && !data ? (
            <div className="analysis-empty">
              {analysisQuery.error instanceof Error
                ? analysisQuery.error.message
                : bilingual(lang, "加载失败", "Failed to load")}
            </div>
          ) : !data ? (
            <div className="analysis-empty">
              {bilingual(lang, "正在加载…", "Loading…")}
            </div>
          ) : !items.length ? (
            <div className="analysis-empty">
              {bilingual(lang, "当前筛选范围内暂无 Review 记录", "No reviews in this filter scope")}
            </div>
          ) : (
            items.map((item) => {
              const annotation = item.annotation || {};
              const prediction = item.prediction || {};
              const expectedOutput = annotationExpectedOutput(annotation);
              const reviewUrl = safeSameOriginReviewUrl(item.review_url);
              const voyagerUrl = safeExternalUrl(item.voyager_issue_url);
              const issueId = String(item.issue_id || "");
              const sceneLabel =
                item.title ||
                item.scenario ||
                bilingual(lang, "未填写场景", "Scene not set");
              const rawComp = String(item.comparison_status || "").toLowerCase();
              const validComp = ["mismatch", "match", "no_gt", "none"].includes(rawComp)
                ? rawComp
                : "";
              const compMeta = validComp ? comparisonStatusMeta(validComp, lang) : null;
              const multi = item.multi_review || null;
              const multiLabel = multi
                ? (
                    {
                      pending: bilingual(lang, "未完成", "Pending"),
                      agreed: bilingual(lang, "一致", "Agreed"),
                      conflict: bilingual(lang, "冲突", "Conflict"),
                    } as Record<string, string>
                  )[multi.agreement || ""] || bilingual(lang, "多人复核", "Multi-review")
                : "";
              const multiDist = multi
                ? Object.entries(multi.output_counts || {})
                    .map(([lbl, cnt]) => `${lbl} ${cnt}`)
                    .join(" · ")
                : "";
              const multiLines = multi
                ? (multi.reviews || [])
                    .map(
                      (r) =>
                        `${r.username}：${
                          r.expected_output || bilingual(lang, "待补充", "Pending")
                        }`,
                    )
                    .join(" · ")
                : "";
              const confidence =
                prediction.confidence === null || prediction.confidence === undefined
                  ? ""
                  : ` · ${(Number(prediction.confidence) * 100).toFixed(1)}%`;
              const tags = item.case_label_context?.tags || annotation.tags || [];
              const evidence = annotation.missing_evidence || [];
              const discussionRunId = route.runId || annotation.model_run_id || "";

              return (
                <article key={issueId} className="analysis-case-row">
                  <div className="analysis-case-identity">
                    {voyagerUrl ? (
                      <a
                        className="analysis-issue-link"
                        href={voyagerUrl}
                        target="_blank"
                        rel="noreferrer"
                        title={bilingual(
                          lang,
                          `在 Voyager 中打开 ${issueId}`,
                          `Open ${issueId} in Voyager`,
                        )}
                      >
                        {issueId}
                      </a>
                    ) : (
                      <strong>{issueId}</strong>
                    )}
                    <span title={sceneLabel}>{sceneLabel}</span>
                  </div>

                  <div className="analysis-case-labels">
                    {compMeta && (
                      <span
                        className={`analysis-comparison-badge comparison-${validComp}`}
                        title={compMeta.description}
                      >
                        {compMeta.label}
                        {validComp === "none" ? bilingual(lang, " 未输出", " no pred") : ""}
                      </span>
                    )}
                    {multi && (
                      <span
                        className={`analysis-comparison-badge comparison-${
                          multi.agreement === "conflict"
                            ? "mismatch"
                            : multi.agreement === "agreed"
                              ? "match"
                              : "none"
                        }`}
                      >
                        {`${multiLabel} · ${Number(multi.completed_count || 0)}/${Number(
                          multi.assigned_count || 0,
                        )}`}
                      </span>
                    )}
                    <span title={`${baselineLabelForScope(item.baseline_scope, config, lang)} GT`}>
                      GT <LabelBadge label={item.gt_label} />
                    </span>
                    {annotation.review_domain === "model_review" ? (
                      <span title={bilingual(lang, "模型判错复核状态", "Model review status")}>
                        {bilingual(lang, "模型复核", "Model review")}{" "}
                        {reviewStatusLabel(
                          item.model_review_progress || annotation.model_review_status,
                          lang,
                        )}
                      </span>
                    ) : (
                      <span title={bilingual(lang, "历史 Review 期望输出", "Legacy expected output")}>
                        {bilingual(lang, "历史期望", "Legacy expected")}{" "}
                        <LabelBadge
                          label={expectedOutput}
                          emptyText={bilingual(lang, "待补充", "Pending")}
                        />
                      </span>
                    )}
                    <button
                      className="analysis-model-history-button"
                      type="button"
                      aria-busy={historyBusyIssue === issueId ? "true" : undefined}
                      title={bilingual(
                        lang,
                        "查看此 Issue 的全部评测 Run 输出历史",
                        "View model Run history for this Issue",
                      )}
                      aria-label={bilingual(
                        lang,
                        `查看 ${issueId} 的评测 Run 输出历史`,
                        `View model Run history for ${issueId}`,
                      )}
                      onClick={() => void handleOpenModelHistory(issueId)}
                    >
                      <span>{bilingual(lang, "模型", "Model")}</span>
                      <LabelBadge
                        label={prediction.label}
                        emptyText={bilingual(lang, "未输出", "None")}
                      />
                      {confidence}
                    </button>
                  </div>

                  <div className="analysis-case-reason">
                    <strong className={annotation.note ? undefined : "reason-empty"}>
                      {annotation.note ||
                        bilingual(
                          lang,
                          "未填写“模型为什么判错”",
                          "“Why was the model wrong?” not filled",
                        )}
                    </strong>
                    {prediction.reason && (
                      <p>
                        {bilingual(
                          lang,
                          `模型理由：${prediction.reason}`,
                          `Model reason: ${prediction.reason}`,
                        )}
                      </p>
                    )}
                    {multiDist && (
                      <p>
                        {bilingual(
                          lang,
                          `多人结论：${multiDist}`,
                          `Multi-review: ${multiDist}`,
                        )}
                      </p>
                    )}
                    {multiLines && (
                      <p>
                        {bilingual(
                          lang,
                          `复核人：${multiLines}`,
                          `Reviewers: ${multiLines}`,
                        )}
                      </p>
                    )}
                    <div className="analysis-chip-list">
                      {tags.map((key) => {
                        const catalogItem = reviewTagCatalogItem(key, config);
                        return (
                          <span
                            key={`tag-${key}`}
                            className="analysis-chip tag-chip"
                            data-tag-section={catalogItem?.section || undefined}
                            data-tag-group={catalogItem?.group || undefined}
                          >
                            {tagLabel(key, config)}
                          </span>
                        );
                      })}
                      {evidence.map((key) => (
                        <span key={`ev-${key}`} className="analysis-chip evidence-chip">
                          {evidenceLabel(key, config)}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="analysis-case-meta">
                    <span>
                      {annotation.author || bilingual(lang, "未记录复核人", "No reviewer")}
                      {annotation.author_verified ? " · SSO" : ""}
                    </span>
                    <span>
                      {reviewStatusLabel(
                        item.model_review_progress ||
                          annotation.model_review_status ||
                          annotation.review_status,
                        lang,
                      )}{" "}
                      · {formatCstTime(annotation.created_at, lang)}
                    </span>
                    <span className="analysis-case-actions">
                      <button
                        className="analysis-discussion-link"
                        type="button"
                        onClick={() => handleOpenDiscussion(issueId, discussionRunId)}
                      >
                        {bilingual(lang, "评论", "Comments")}
                      </button>
                      {reviewUrl && (
                        <a
                          className="text-link"
                          href={reviewUrl}
                          title={bilingual(lang, "打开问题详情与 Review", "Open case details & review")}
                        >
                          {bilingual(lang, "问题详情", "Details")}
                        </a>
                      )}
                    </span>
                  </div>
                </article>
              );
            })
          )}
        </div>

        <Pagination
          page={page}
          pageSize={Number(data?.page_size || route.pageSize)}
          total={Number(data?.total || 0)}
          lang={lang}
          loading={analysisQuery.isFetching}
          labelText={!data && analysisQuery.isFetching ? "— / —" : `${page} / ${pageCount}`}
          ariaLabel={bilingual(lang, "原因明细分页", "Reason detail pagination")}
          onPageChange={(nextPage) => {
            setRoute((prev) => ({ ...prev, page: nextPage }));
            if (caseListRef.current && typeof window !== "undefined") {
              window.scrollTo({
                top: Math.max(0, caseListRef.current.offsetTop - 72),
                behavior: "smooth",
              });
            }
          }}
          onPageSizeChange={(nextSize) =>
            setRoute((prev) => ({ ...prev, page: 1, pageSize: nextSize }))
          }
        />
      </section>

      <AnalysisPieTooltip tooltip={tooltip} tipRef={tipRef} lang={lang} />

      <LabelSummaryRulesDialog
        mode={rulesModalMode}
        lang={lang}
        onClose={() => setRulesModalMode(null)}
      />
    </div>
  );
};
