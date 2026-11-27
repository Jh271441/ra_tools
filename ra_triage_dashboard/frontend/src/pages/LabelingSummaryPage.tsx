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
  AnalysisClusterGroupData,
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
  StatusSegmentItem,
  TRIAGE_LABELS,
  useAnalysisPieTooltip,
} from "../components/charts/AnalysisCharts";
import { ModalDialog } from "../components/ui/ModalDialog";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import {
  CASE_PAGE_SIZES,
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";
import {
  buildLabelGtFilterOptions,
  DashboardConfigPayload,
  evidenceLabel,
  isTriageLabel,
  ISSUE_QUERY_ID_RE,
  joinFilterList,
  labelGtFilterSelection,
  normalizedGtRelationFilters,
  normalizedLabelingStatusFilters,
  parseFilterList,
  parseIssueIdsInput,
  readLegacyConfig,
  showWorkbenchToast,
  splitLabelGtFilterSelection,
  tagLabel,
  UiInfoPopover,
} from "../utils/analysisHelpers";

export interface LabelingSummaryTaskItem {
  id: string;
  name?: string;
  workflow_mode?: string;
  selection_source_run_id?: string;
  appendable?: boolean;
}

export interface LabelingSummarySourceDetail {
  kind?: string;
  task_id?: string;
  source_run_id?: string;
  authors?: string[];
  revision_ids?: Array<string | number>;
}

export interface LabelingSummaryCaseItem {
  issue_id: string;
  title?: string;
  scenario?: string;
  label_state?: string;
  expected_output?: string;
  gt_label?: string;
  is_excluded?: boolean;
  exclusion_conflict?: boolean;
  rationales?: string[];
  tags?: string[];
  evidence_gaps?: string[];
  authors?: string[];
  source_count?: number;
  created_at?: string;
  decision?: { stale?: boolean };
  adjudication?: { kind?: string } | null;
  original_conflict?: boolean;
  original_votes?: Array<{
    author: string;
    expected_output?: string;
    rationale?: string;
  }>;
  expected_output_source?: {
    kind?: string;
    decision_id?: string | number;
    authors?: string[];
    sources?: LabelingSummarySourceDetail[];
  };
}

export interface LabelingSummaryResponse {
  total: number;
  annotated: number;
  reason_count: number;
  empty_reason_count: number;
  adjudicated_count: number;
  page: number;
  page_size: number;
  page_count: number;
  labelers?: string[];
  assignees?: string[];
  submitted_states?: {
    resolved?: number;
    pending?: number;
    conflict?: number;
  };
  gt_update_counts?: GtUpdateCounts;
  pairs?: Array<{ gt: string; label: string; count: number }>;
  matrix_exclusions?: { missing_gt?: number; unsupported_gt?: number; no_final_label?: number };
  matrix_gt_exclusions?: Array<{ label: string | null; count: number }>;
  tags?: Record<string, number>;
  items?: LabelingSummaryCaseItem[];
}

interface LabelSummaryRouteState {
  search: string;
  issueIds: string[];
  issueTags: string[];
  taskId: string;
  targetGroup: string;
  status: string[];
  chartGt: string;
  chartLabel: string;
  author: string[];
  assignee: string[];
  label: string[];
  gt: string[];
  gtRelations: string[];
  commentState: string[];
  exclusion: string[];
  cluster: string;
  page: number;
  pageSize: number;
}

function defaultRouteState(): LabelSummaryRouteState {
  return {
    search: "",
    issueIds: [],
    issueTags: [],
    taskId: "",
    targetGroup: "",
    status: [],
    chartGt: "",
    chartLabel: "",
    author: [],
    assignee: [],
    label: [],
    gt: [],
    gtRelations: [],
    commentState: [],
    exclusion: [],
    cluster: "",
    page: 1,
    pageSize: DEFAULT_CASE_PAGE_SIZE,
  };
}

function readRouteFromUrl(): LabelSummaryRouteState {
  if (typeof window === "undefined") return defaultRouteState();
  const params = new URLSearchParams(window.location.search);
  const rawPage = Number(params.get("page") || 1);
  const rawSize = Number(params.get("page_size") || DEFAULT_CASE_PAGE_SIZE);
  const rawTargetGroup = String(params.get("target_group") || "").trim().toLowerCase();
  return {
    search: String(params.get("q") || "").trim(),
    issueTags: parseFilterList(params.get("issue_tags")),
    issueIds: parseFilterList(params.get("issue_ids")).filter((v) =>
      ISSUE_QUERY_ID_RE.test(v),
    ),
    taskId: String(params.get("task") || "").trim(),
    targetGroup: ["sample", "low"].includes(rawTargetGroup) ? rawTargetGroup : "",
    chartGt: params.get("chart_gt") || "",
    chartLabel: params.get("chart_label") || "",
    status: normalizedLabelingStatusFilters(params.get("status"), {
      submittedOnly: true,
    }),
    author: parseFilterList(params.get("author")),
    assignee: parseFilterList(params.get("assignee")),
    label: parseFilterList(params.get("label")).filter((v) => isTriageLabel(v)),
    gtRelations: normalizedGtRelationFilters(params.get("gt_relation")),
    gt: parseFilterList(params.get("gt")).filter((v) => isTriageLabel(v)),
    commentState: parseFilterList(params.get("comment_state")).filter((v) =>
      ["with", "without"].includes(v),
    ),
    exclusion: parseFilterList(params.get("exclusion")).filter((v) =>
      ["active", "excluded"].includes(v),
    ),
    cluster: String(params.get("cluster") || "").trim(),
    page: Number.isInteger(rawPage) && rawPage > 0 ? rawPage : 1,
    pageSize: (CASE_PAGE_SIZES as readonly number[]).includes(rawSize)
      ? rawSize
      : DEFAULT_CASE_PAGE_SIZE,
  };
}

function buildLabelingSummaryUrl(
  state: LabelSummaryRouteState,
  baselines: string[],
): string {
  const params = new URLSearchParams();
  if (state.chartGt) params.set("chart_gt", state.chartGt);
  if (state.chartLabel) params.set("chart_label", state.chartLabel);
  if (state.search) params.set("q", state.search);
  if (state.gtRelations.length) params.set("gt_relation", joinFilterList(state.gtRelations));
  if (state.issueTags.length) params.set("issue_tags", joinFilterList(state.issueTags));
  const validIds = state.issueIds.filter((v) => ISSUE_QUERY_ID_RE.test(v));
  if (validIds.length) params.set("issue_ids", validIds.join(","));
  if (state.taskId) params.set("task", state.taskId);
  if (state.targetGroup) params.set("target_group", state.targetGroup);
  if (state.status.length) params.set("status", joinFilterList(state.status));
  if (state.author.length) params.set("author", joinFilterList(state.author));
  if (state.assignee.length) params.set("assignee", joinFilterList(state.assignee));
  if (state.label.length) params.set("label", joinFilterList(state.label));
  if (state.gt.length) params.set("gt", joinFilterList(state.gt));
  if (state.commentState.length) {
    params.set("comment_state", joinFilterList(state.commentState));
  }
  if (state.exclusion.length) params.set("exclusion", joinFilterList(state.exclusion));
  if (state.cluster) params.set("cluster", state.cluster);
  if (state.page > 1) params.set("page", String(state.page));
  if (state.pageSize !== DEFAULT_CASE_PAGE_SIZE) {
    params.set("page_size", String(state.pageSize));
  }
  if (baselines.length) params.set("baselines", baselines.join(","));
  const qs = params.toString();
  const basePath = withWorkbenchBase("/labeling-summary");
  return qs ? `${basePath}?${qs}` : basePath;
}

function buildCaseDetailUrl(
  issueId: string,
  state: LabelSummaryRouteState,
  tasks: LabelingSummaryTaskItem[],
  baselines: string[],
): string {
  const task = tasks.find((t) => t.id === state.taskId);
  if (task?.workflow_mode === "model_review_and_case_label") {
    const params = new URLSearchParams();
    if (task.selection_source_run_id) params.set("run", task.selection_source_run_id);
    if (issueId) params.set("issue", issueId);
    params.set("work_split", task.id);
    if (task.appendable) params.set("task_view", "targets");
    if (state.targetGroup) params.set("target_group", state.targetGroup);
    if (state.gtRelations.length) params.set("gt_relation", joinFilterList(state.gtRelations));
    if (baselines.length) params.set("baselines", baselines.join(","));
    return `${withWorkbenchBase("/review")}?${params.toString()}`;
  }
  const params = new URLSearchParams();
  if (issueId) params.set("issue", issueId);
  if (state.taskId) params.set("task", state.taskId);
  if (state.targetGroup) params.set("target_group", state.targetGroup);
  if (state.search) params.set("q", state.search);
  if (state.issueIds.length) params.set("issue_ids", state.issueIds.join(","));
  if (state.issueTags.length) params.set("issue_tags", joinFilterList(state.issueTags));
  if (state.gtRelations.length) params.set("gt_relation", joinFilterList(state.gtRelations));
  if (state.status.length) params.set("status", joinFilterList(state.status));
  if (state.author.length) params.set("author", joinFilterList(state.author));
  if (state.assignee.length) params.set("assignee", joinFilterList(state.assignee));
  if (state.cluster) params.set("cluster", state.cluster);
  if (state.label.length) params.set("label", joinFilterList(state.label));
  if (state.gt.length) params.set("gt", joinFilterList(state.gt));
  if (state.commentState.length) {
    params.set("comment_state", joinFilterList(state.commentState));
  }
  if (state.exclusion.length) params.set("exclusion", joinFilterList(state.exclusion));
  if (baselines.length) params.set("baselines", baselines.join(","));
  return `${withWorkbenchBase("/case-labeling")}?${params.toString()}`;
}

export interface LabelingSummaryPageProps {
  active: boolean;
  lang: UiLanguage;
  theme: ColorTheme;
  selectedBaselines: string[];
  isAdmin: boolean;
}

export const LabelingSummaryPage: React.FC<LabelingSummaryPageProps> = ({
  active,
  lang,
  theme,
  selectedBaselines,
  isAdmin,
}) => {
  const [route, setRoute] = useState<LabelSummaryRouteState>(readRouteFromUrl);
  const [searchDraft, setSearchDraft] = useState<string>(route.search);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [mobileChartsOpen, setMobileChartsOpen] = useState(false);
  const [rulesModalMode, setRulesModalMode] = useState<null | "gt" | "expected">(null);
  const [issueModalOpen, setIssueModalOpen] = useState(false);
  const [issueDraft, setIssueDraft] = useState("");
  const [exportingGt, setExportingGt] = useState(false);
  const searchTimerRef = useRef<number | null>(null);
  const exportBtnRef = useRef<HTMLButtonElement | null>(null);
  const caseListRef = useRef<HTMLDivElement | null>(null);

  const { tooltip, tipRef, showTooltip, hideTooltip } = useAnalysisPieTooltip();

  const baselinesKey = selectedBaselines.join(",");

  const wasActiveRef = useRef<boolean>(active);
  const lastPersistedStateRef = useRef<string | null>(null);

  // Sync route state on re-entry and popstate when active.
  useEffect(() => {
    if (!active) {
      wasActiveRef.current = false;
      lastPersistedStateRef.current = null;
      return;
    }
    const syncFromUrl = () => {
      const next = readRouteFromUrl();
      setRoute(next);
      setSearchDraft(next.search);
      lastPersistedStateRef.current = null;
    };
    if (!wasActiveRef.current) {
      syncFromUrl();
    }
    wasActiveRef.current = true;
    window.addEventListener("popstate", syncFromUrl);
    return () => window.removeEventListener("popstate", syncFromUrl);
  }, [active]);

  // Persist URL only after initial mount / URL sync so cold links keep ?baselines=...
  // intact while classic bootstrap() finishes hydrating state.selectedBaselineIds.
  useEffect(() => {
    if (!active || !wasActiveRef.current || typeof window === "undefined") return;
    const key = JSON.stringify({ route, baselines: selectedBaselines });
    if (lastPersistedStateRef.current === null) {
      lastPersistedStateRef.current = key;
      return;
    }
    if (lastPersistedStateRef.current === key) return;
    lastPersistedStateRef.current = key;
    const nextUrl = buildLabelingSummaryUrl(route, selectedBaselines);
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (nextUrl !== currentUrl) {
      window.history.replaceState(
        { ...(window.history.state || {}), page: "labeling-summary" },
        "",
        nextUrl,
      );
    }
  }, [active, route, selectedBaselines]);

  // Fetch dashboard config if not already populated on classic window.state.
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

  // Fetch labeling tasks list for the active baselines.
  const tasksQuery = useQuery<{ items?: LabelingSummaryTaskItem[] }>({
    queryKey: ["labeling-summary-tasks", baselinesKey],
    queryFn: ({ signal }) =>
      apiRequest<{ items?: LabelingSummaryTaskItem[] }>(
        `/api/labeling/tasks?include_combined=true&baselines=${encodeURIComponent(baselinesKey)}`,
        { signal },
      ),
    enabled: active,
    staleTime: 30_000,
  });
  const tasks = tasksQuery.data?.items || [];

  // If URL had a taskId that does not exist in the loaded task directory, clear it (1:1 classic).
  useEffect(() => {
    if (!active || !tasksQuery.isSuccess || !route.taskId) return;
    if (!tasks.some((item) => item.id === route.taskId)) {
      setRoute((prev) => (prev.taskId ? { ...prev, taskId: "", page: 1 } : prev));
    }
  }, [active, tasksQuery.isSuccess, tasks, route.taskId]);

  const effectiveTaskId =
    route.taskId && tasksQuery.isSuccess && !tasks.some((item) => item.id === route.taskId)
      ? ""
      : route.taskId;

  const summaryParams = useMemo(() => {
    const p = new URLSearchParams({
      baselines: baselinesKey,
      task_id: effectiveTaskId,
      target_group: route.targetGroup,
      q: route.search,
      issue_ids: route.issueIds.join(","),
      status: joinFilterList(route.status),
      chart_gt: route.chartGt, chart_label: route.chartLabel,
      author: joinFilterList(route.author),
      assignee: joinFilterList(route.assignee),
      exclusion: joinFilterList(route.exclusion),
      label: joinFilterList(route.label),
      gt: joinFilterList(route.gt),
      gt_relation: joinFilterList(route.gtRelations),
      comment_state: joinFilterList(route.commentState),
      issue_tags: joinFilterList(route.issueTags),
      cluster: route.cluster,
      page: String(route.page),
      page_size: String(route.pageSize),
    });
    return p.toString();
  }, [baselinesKey, effectiveTaskId, route]);

  const summaryQuery = useQuery<LabelingSummaryResponse>({
    queryKey: ["labeling-summary", summaryParams],
    queryFn: ({ signal }) =>
      apiRequest<LabelingSummaryResponse>(`/api/labeling/summary?${summaryParams}`, {
        signal,
      }),
    enabled: active && (!route.taskId || !tasksQuery.isLoading),
    placeholderData: (prev) => prev,
  });

  const data = summaryQuery.data;
  const focusDetailOnLoad = useRef(window.location.hash === "#labelSummaryCaseList");
  useEffect(() => {
    if (active && data && !summaryQuery.isPlaceholderData && focusDetailOnLoad.current && caseListRef.current) {
      focusDetailOnLoad.current = false;
      caseListRef.current.focus({ preventScroll: true });
      caseListRef.current.scrollIntoView({ block: "start" });
    }
  }, [active, data, summaryQuery.isPlaceholderData]);

  const chartHref = (filters: Partial<typeof route>) =>
    buildLabelingSummaryUrl({ ...route, ...filters, page: 1 }, selectedBaselines);
  const labelingHref = (filters: Partial<typeof route>) =>
    chartHref(filters).replace("/labeling-summary?", "/case-labeling?");


  // Debounced search handler matching classic 280ms behavior.
  const handleSearchInput = useCallback((value: string) => {
    setSearchDraft(value);
    if (searchTimerRef.current !== null) {
      window.clearTimeout(searchTimerRef.current);
    }
    searchTimerRef.current = window.setTimeout(() => {
      searchTimerRef.current = null;
      const trimmed = value.trim();
      setRoute((prev) => ({
        ...prev,
        search: trimmed,
        issueIds: trimmed ? [] : prev.issueIds,
        page: 1,
      }));
    }, 280);
  }, []);

  useEffect(() => {
    return () => {
      if (searchTimerRef.current !== null) {
        window.clearTimeout(searchTimerRef.current);
      }
    };
  }, []);

  // Filter options
  const taskOptions: UiSelectOption[] = useMemo(() => {
    const opts: UiSelectOption[] = [
      {
        value: "",
        label: bilingual(lang, "全部标注（含历史迁移）", "All annotations (including migrated)"),
      },
      ...tasks.map((t) => ({
        value: t.id,
        label: t.name || bilingual(lang, "标注任务", "Labeling task"),
      })),
    ];
    if (route.taskId && !opts.some((item) => item.value === route.taskId)) {
      opts.push({ value: route.taskId, label: route.taskId });
    }
    return opts;
  }, [lang, tasks, route.taskId]);

  const labelGtOptions = useMemo(
    () => buildLabelGtFilterOptions({ lang, labeling: true }),
    [lang],
  );
  const labelGtSelected = useMemo(
    () => labelGtFilterSelection(route.status, route.gtRelations),
    [route.status, route.gtRelations],
  );

  const labelerOptions: MultiSelectOption[] = useMemo(
    () =>
      Array.from(new Set([...(data?.labelers || []), ...route.author])).map((value) => ({
        value,
        label: value,
      })),
    [data?.labelers, route.author],
  );

  const assigneeOptions: MultiSelectOption[] = useMemo(
    () =>
      Array.from(new Set([...(data?.assignees || []), ...route.assignee])).map((value) => ({
        value,
        label: value,
      })),
    [data?.assignees, route.assignee],
  );

  const triageOptions: MultiSelectOption[] = useMemo(
    () => TRIAGE_LABELS.map((value) => ({ value, label: value })),
    [],
  );

  const discussionOptions: MultiSelectOption[] = useMemo(
    () => [
      { value: "with", label: bilingual(lang, "有讨论", "With discussion") },
      { value: "without", label: bilingual(lang, "无讨论", "Without discussion") },
    ],
    [lang],
  );

  const exclusionOptions: MultiSelectOption[] = useMemo(
    () => [
      { value: "active", label: bilingual(lang, "未排除", "Active") },
      { value: "excluded", label: bilingual(lang, "已排除", "Excluded") },
    ],
    [lang],
  );

  const showTargetGroupFilter = useMemo(() => {
    if (route.targetGroup) return true;
    const selected = selectedBaselines.length ? selectedBaselines : ["0508"];
    const catalog =
      (config as { baselines?: Array<{ id?: string; loader?: string }> } | undefined)?.baselines ||
      [];
    return selected.some((id) => {
      if (id.startsWith("version-")) return true;
      const item = catalog.find((b) => String(b.id || "") === id);
      return item?.loader === "version_projection";
    });
  }, [config, selectedBaselines, route.targetGroup]);

  const targetGroupOptions: UiSelectOption[] = useMemo(() => {
    const base: UiSelectOption[] = [
      { value: "", label: bilingual(lang, "全部", "All") },
      { value: "sample", label: bilingual(lang, "抽样集", "Random sample") },
      {
        value: "low",
        label: bilingual(lang, "低置信度（不含抽样）", "Low confidence (excluding samples)"),
      },
    ];
    if (route.targetGroup && !base.some((o) => o.value === route.targetGroup)) {
      base.push({ value: route.targetGroup, label: route.targetGroup });
    }
    return base;
  }, [route.targetGroup, lang]);

  // Derived charts data
  const statusItems: StatusSegmentItem[] = useMemo(() => {
    const counts = data?.submitted_states || {};
    return [
      {
        key: "resolved",
        cssKey: "completed",
        label: bilingual(lang, "已形成结论", "Resolved"),
        count: Number(counts.resolved || 0),
        description: bilingual(
          lang,
          "多来源聚合后已形成唯一结论",
          "Unique result formed across sources",
        ),
      },
      {
        key: "pending",
        cssKey: "pending",
        label: bilingual(lang, "待形成结论", "Pending"),
        count: Number(counts.pending || 0),
        description: bilingual(
          lang,
          "已有提交，但还没有形成唯一结论",
          "Submitted but no unique result yet",
        ),
      },
      {
        key: "conflict",
        cssKey: "blocked_by_label",
        label: bilingual(lang, "待裁决 / 需确认", "Needs adjudication / confirmation"),
        count: Number(counts.conflict || 0),
        description: bilingual(
          lang,
          "当前来源之间存在冲突或 Issue 裁决已过期",
          "Sources conflict or Issue decision is stale",
        ),
      },
    ];
  }, [data?.submitted_states, lang]);

  const matrixGtLabels = new Map([
    ["out_of_scope", "Out of scope"],
    ["未接起", bilingual(lang, "未接起", "Unanswered")],
  ]);
  const matrixReasons = (data?.matrix_gt_exclusions || []).map(({ label, count }) => ({
    key: label ?? "null",
    label: matrixGtLabels.get(label ?? "") ?? label ?? "Null",
    count,
  }));
  const noFinalLabel = data?.matrix_exclusions?.no_final_label ?? 0;
  if (noFinalLabel) matrixReasons.push({ key: "no_final_label", label: bilingual(lang, "无最终标注", "No final label"), count: noFinalLabel });

  const confusionData = useMemo(() => {
    const pairs = new Map(
      (data?.pairs || []).map((row) => [`${row.gt}|${row.label}`, Number(row.count || 0)]),
    );
    const columnLabels = lang === "en" ? ["False trigger", "Correct trigger", "No assist"] : [...TRIAGE_LABELS];
    const colTotals = TRIAGE_LABELS.map(() => 0);
    let comparable = 0;
    let matches = 0;

    const rows: ConfusionTableRow[] = TRIAGE_LABELS.map((gt, rowIndex) => {
      let rowTotal = 0;
      const cells = TRIAGE_LABELS.map((label, colIndex) => {
        const count = pairs.get(`${gt}|${label}`) || 0;
        rowTotal += count;
        colTotals[colIndex] += count;
        comparable += count;
        if (gt === label) matches += count;
        return {
          colLabel: columnLabels[colIndex],
          count,
          tone: (gt === label ? "match" : count ? "mismatch" : "") as
            | "match"
            | "mismatch"
            | "",
          title: `GT ${columnLabels[rowIndex]} · ${bilingual(lang, "标注", "Label")} ${columnLabels[colIndex]} · ${count}`,
        };
      });
      return { gtLabel: columnLabels[rowIndex], cells, total: rowTotal };
    });
    const grandTotal = colTotals.reduce((a, b) => a + b, 0);
    return { rows, columnLabels, colTotals, grandTotal, comparable, matches };
  }, [data?.pairs, lang]);

  const clusterPanels = useMemo(() => {
    const catalog = new Map(
      (config?.review_tag_catalog || []).map((item) => [item.key, item]),
    );
    const tagCounts = data?.tags || {};
    const groupItems = (section: string, group: string): AnalysisPieItem[] =>
      Object.entries(tagCounts)
        .map(([key, count]) => ({
          key,
          count: Number(count || 0),
          item: catalog.get(key),
        }))
        .filter(({ item }) => item?.section === section && item?.group === group)
        .map(({ key, count, item }) => ({
          key,
          count,
          label: item?.label || key,
          description: item?.hint || "",
        }))
        .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));

    const makeGroup = (
      key: string,
      label: string,
      items: AnalysisPieItem[],
    ): AnalysisClusterGroupData => ({
      key,
      label,
      annotated_count: items.reduce((sum, item) => sum + item.count, 0),
      items,
    });

    return [
      {
        key: "environment",
        label: bilingual(lang, "场景环境", "Environment"),
        layout: "single" as const,
        groups: [
          makeGroup(
            "environment",
            bilingual(lang, "场景环境", "Environment"),
            groupItems("scene", "environment"),
          ),
        ],
      },
      {
        key: "self_intent",
        label: bilingual(lang, "自车意图", "Ego intent"),
        layout: "single" as const,
        groups: [
          makeGroup(
            "self_intent",
            bilingual(lang, "自车意图", "Ego intent"),
            groupItems("scene", "self_intent"),
          ),
        ],
      },
      {
        key: "trigger",
        label: bilingual(lang, "触发判定", "Trigger decision"),
        layout: "dual" as const,
        groups: [
          makeGroup("false_trigger", "误触发", groupItems("interaction_decision", "false_trigger")),
          makeGroup("true_trigger", "正确触发", groupItems("interaction_decision", "true_trigger")),
        ],
      },
      {
        key: "egress",
        label: bilingual(lang, "如何脱困", "Egress"),
        layout: "dual" as const,
        groups: [
          makeGroup("ra", "RA", groupItems("egress", "ra")),
          makeGroup("no_assist", "无需协助", groupItems("egress", "no_assist")),
        ],
      },
    ];
  }, [config?.review_tag_catalog, data?.tags, lang]);

  // Multi-Issue modal live parse
  const parsedIssues = useMemo(() => parseIssueIdsInput(issueDraft), [issueDraft]);

  const handleApplyIssues = () => {
    if (parsedIssues.invalid.length) {
      showWorkbenchToast(
        bilingual(lang, "请先修正无法识别的 Issue。", "Fix invalid Issue tokens first."),
        true,
      );
      return;
    }
    setSearchDraft("");
    setRoute((prev) => ({
      ...prev,
      issueIds: parsedIssues.ids,
      search: "",
      page: 1,
    }));
    setIssueModalOpen(false);
  };

  const handleReset = () => {
    if (searchTimerRef.current !== null) {
      window.clearTimeout(searchTimerRef.current);
      searchTimerRef.current = null;
    }
    setSearchDraft("");
    setRoute(defaultRouteState());
  };

  const handleExportGt = async () => {
    if (!isAdmin || exportingGt) return;
    const win = window as unknown as {
      exportLabelingGtUpdate?: (
        filters: Record<string, string>,
        button?: HTMLButtonElement | null,
      ) => Promise<void>;
    };
    const activeSearch = searchDraft.trim();
    const activeIssueIds = activeSearch ? [] : route.issueIds;
    const payload = {
      baselines: baselinesKey,
      task_id: route.taskId,
      target_group: route.targetGroup,
      q: activeSearch,
      issue_ids: activeIssueIds.join(","),
      status: joinFilterList(route.status),
      chart_gt: route.chartGt, chart_label: route.chartLabel,
      author: joinFilterList(route.author),
      assignee: joinFilterList(route.assignee),
      label: joinFilterList(route.label),
      gt: joinFilterList(route.gt),
      gt_relation: joinFilterList(route.gtRelations),
      comment_state: joinFilterList(route.commentState),
      issue_tags: joinFilterList(route.issueTags),
      exclusion: joinFilterList(route.exclusion),
      cluster: route.cluster,
    };
    if (typeof win.exportLabelingGtUpdate === "function") {
      setExportingGt(true);
      try {
        await win.exportLabelingGtUpdate(payload, exportBtnRef.current);
      } catch (err) {
        showWorkbenchToast(err instanceof Error ? err.message : String(err), true);
      } finally {
        setExportingGt(false);
      }
    }
  };

  const renderSourceMarkup = (item: LabelingSummaryCaseItem) => {
    const source = item.expected_output_source || { kind: "unknown" };
    const sources = source.sources || [];
    const names: Record<string, string> = {
      issue_adjudication: bilingual(lang, "Issue 裁决", "Issue decision"),
      task_adjudication: bilingual(lang, "任务内裁决", "Task decision"),
      source_consensus: bilingual(lang, "多来源一致", "Source consensus"),
      consensus: bilingual(lang, "多人一致", "Reviewer consensus"),
      single: bilingual(lang, "单人标注", "Single annotation"),
      unresolved: bilingual(lang, "尚未形成有效结论", "No valid result yet"),
      unknown: bilingual(lang, "来源未记录", "Source not recorded"),
    };
    const label = names[source.kind || "unknown"] || names.unknown;
    const authors = (source.authors || []).join("、");
    const containsDecision =
      source.kind === "source_consensus" &&
      sources.some((v) => v.kind === "task_adjudication");
    const detailLines = sources.map(
      (v) =>
        `${names[v.kind || ""] || v.kind || ""} · ${
          v.task_id
            ? `${bilingual(lang, "任务", "Task")} ${v.task_id}`
            : bilingual(lang, "任务外标注", "Outside tasks")
        }${v.source_run_id ? ` · Run ${v.source_run_id}` : ""} · ${(v.authors || []).join("、")}${
          v.revision_ids?.length
            ? ` · ${bilingual(lang, "记录", "Revisions")} ${v.revision_ids.join("、")}`
            : ""
        }`,
    );
    const text = `${label}${
      containsDecision ? bilingual(lang, "（含任务裁决）", " (includes task decisions)") : ""
    }${
      source.kind === "source_consensus"
        ? ` · ${bilingual(lang, `${sources.length} 个来源`, `${sources.length} sources`)}`
        : ""
    }${authors ? ` · ${authors}` : ""}`;
    const traceLines =
      detailLines.length > 0
        ? detailLines
        : source.decision_id
          ? [`${bilingual(lang, "Issue 裁决", "Issue decision")} #${source.decision_id} · ${authors}`]
          : [];

    if (traceLines.length > 0) {
      return (
        <details className="label-summary-source">
          <summary>{`${bilingual(lang, "来源", "Source")}: ${text}`}</summary>
          <div className="label-summary-source-trace">
            {traceLines.map((line, idx) => (
              <p key={idx}>{line}</p>
            ))}
          </div>
        </details>
      );
    }
    return (
      <span className="label-summary-source">
        {`${bilingual(lang, "来源", "Source")}: ${text}`}
      </span>
    );
  };

  if (!active) return null;

  const page = Number(data?.page || route.page || 1);
  const pageCount = Math.max(1, Number(data?.page_count || 0));
  const items = data?.items || [];

  return (
    <div className="ra-labeling-summary-root" data-react-island="labeling-summary">
      <section
        className="review-commandbar labeling-summary-command"
        aria-label={bilingual(lang, "标注汇总筛选", "Labeling summary filters")}
      >
        <div className="mobile-filter-bar">
          <button
            className="button button-quiet mobile-filter-toggle"
            type="button"
            aria-expanded={mobileFiltersOpen}
            aria-controls="labelSummaryFilterForm"
            onClick={() => setMobileFiltersOpen((prev) => !prev)}
          >
            {bilingual(lang, "汇总筛选", "Filters")}
            <span className="mobile-filter-hint">
              {mobileFiltersOpen
                ? bilingual(lang, "收起条件", "Hide filters")
                : bilingual(lang, "展开条件", "Show filters")}
            </span>
          </button>
        </div>

        <form
          className={`review-filters case-labeling-filters labeling-summary-filters${
            mobileFiltersOpen ? " is-open" : ""
          }`}
          id="labelSummaryFilterForm"
          onSubmit={(e) => {
            e.preventDefault();
            if (searchTimerRef.current !== null) {
              window.clearTimeout(searchTimerRef.current);
              searchTimerRef.current = null;
            }
            const trimmed = searchDraft.trim();
            setRoute((prev) => ({
              ...prev,
              search: trimmed,
              issueIds: trimmed ? [] : prev.issueIds,
              page: 1,
            }));
          }}
        >
          <div className="ra-analysis-field case-labeling-search">
            <span>Issue</span>
            <div className="issue-query-control">
              <input
                id="labelSummarySearch"
                type="search"
                value={searchDraft}
                placeholder={bilingual(lang, "Issue ID、场景", "Issue ID, scene")}
                autoComplete="off"
                onChange={(e) => handleSearchInput(e.target.value)}
              />
              <button
                className={`button button-quiet issue-query-button${
                  route.issueIds.length ? " has-issues" : ""
                }`}
                id="openLabelSummaryIssueQueryButton"
                type="button"
                data-issue-count={String(route.issueIds.length)}
                title={
                  route.issueIds.length
                    ? bilingual(
                        lang,
                        `已设置 ${route.issueIds.length} 个 Issue`,
                        `${route.issueIds.length} Issues selected`,
                      )
                    : bilingual(lang, "按 Issue 列表查询", "Query an Issue list")
                }
                onClick={() => {
                  setIssueDraft(route.issueIds.join("\n"));
                  setIssueModalOpen(true);
                }}
              >
                {bilingual(lang, "多 Issue", "Issue list")}
              </button>
            </div>
          </div>

          <div className="ra-analysis-field">
            <span>{bilingual(lang, "标注任务", "Labeling task")}</span>
            <UiSelect
              id="labelSummaryTaskPicker"
              value={route.taskId}
              options={taskOptions}
              disabled={tasksQuery.isLoading}
              ariaLabel={bilingual(lang, "标注任务", "Labeling task")}
              onChange={(nextVal) =>
                setRoute((prev) => ({
                  ...prev,
                  taskId: nextVal,
                  author: [],
                  assignee: [],
                  cluster: "",
                  page: 1,
                }))
              }
            />
          </div>

          <div className="ra-analysis-field">
            <div className="filter-field-heading">
              <span>{bilingual(lang, "标注状态 / GT", "Label state / GT")}</span>
              <UiInfoPopover
                id="labelSummaryLabelGtInfo"
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
              id="labelSummaryStatusPicker"
              values={labelGtSelected}
              options={labelGtOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部标注 / GT", "All labels / GT")}
              ariaLabel={bilingual(lang, "标注状态 / GT", "Label state / GT")}
              onChange={(values) => {
                const split = splitLabelGtFilterSelection(values);
                setRoute((prev) => ({
                  ...prev,
                  status: normalizedLabelingStatusFilters(split.labelStates, {
                    submittedOnly: true,
                  }),
                  gtRelations: split.gtRelations,
                  cluster: "",
                  page: 1,
                }));
              }}
            />
          </div>

          <div className="ra-analysis-field">
            <span>{bilingual(lang, "标注人", "Labeler")}</span>
            <MultiSelect
              id="labelSummaryAuthorPicker"
              values={route.author}
              options={labelerOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部标注人", "All labelers")}
              ariaLabel={bilingual(lang, "标注人", "Labeler")}
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, author: values, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-analysis-field">
            <span>{bilingual(lang, "任务负责人", "Assignee")}</span>
            <MultiSelect
              id="labelSummaryAssigneePicker"
              values={route.assignee}
              options={assigneeOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部负责人", "All assignees")}
              ariaLabel={bilingual(lang, "任务负责人", "Assignee")}
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, assignee: values, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-analysis-field">
            <span>GT</span>
            <MultiSelect
              id="labelSummaryGtPicker"
              values={route.gt}
              options={triageOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部 GT", "All GT")}
              ariaLabel="GT"
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, gt: values, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-analysis-field">
            <span>{bilingual(lang, "结果类别", "Result label")}</span>
            <MultiSelect
              id="labelSummaryLabelPicker"
              values={route.label}
              options={triageOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部类别", "All labels")}
              ariaLabel={bilingual(lang, "结果类别", "Result label")}
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, label: values, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-analysis-field">
            <span>{bilingual(lang, "讨论", "Discussion")}</span>
            <MultiSelect
              id="labelSummaryDiscussionPicker"
              values={route.commentState}
              options={discussionOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部讨论状态", "All discussions")}
              ariaLabel={bilingual(lang, "讨论", "Discussion")}
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, commentState: values, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-analysis-field">
            <span>{bilingual(lang, "排除", "Exclusion")}</span>
            <MultiSelect
              id="labelSummaryExclusionPicker"
              values={route.exclusion}
              options={exclusionOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部（含问题排除）", "All cases")}
              ariaLabel={bilingual(lang, "排除", "Exclusion")}
              onChange={(values) =>
                setRoute((prev) => ({ ...prev, exclusion: values, cluster: "", page: 1 }))
              }
            />
          </div>

          {showTargetGroupFilter && (
            <div className="ra-analysis-field filter-target-group">
              <span>{bilingual(lang, "目标集合", "Target cohort")}</span>
              <UiSelect
                id="labelSummaryTargetGroupPicker"
                value={route.targetGroup}
                options={targetGroupOptions}
                ariaLabel={bilingual(lang, "目标集合", "Target cohort")}
                title={bilingual(
                  lang,
                  "按当前版本目标集合筛选；抽样优先于低置信度",
                  "Filter current version target cohorts; samples take precedence over low confidence",
                )}
                onChange={(val) =>
                  setRoute((prev) => ({ ...prev, targetGroup: val, cluster: "", page: 1 }))
                }
              />
            </div>
          )}

          <div className="labeling-summary-actions">
            <button
              ref={exportBtnRef}
              className="button button-quiet"
              id="labelSummaryExportGt"
              type="button"
              disabled={!isAdmin || exportingGt}
              onClick={() => void handleExportGt()}
            >
              {bilingual(lang, "导出 GT 更新表", "Export GT updates")}
            </button>
            <button
              className="button button-quiet"
              id="labelSummaryReset"
              type="button"
              onClick={handleReset}
            >
              {bilingual(lang, "重置", "Reset")}
            </button>
          </div>
        </form>
      </section>

      <div id="labelSummaryContent" aria-live="polite">
        {summaryQuery.isLoading && !data ? (
          <div className="page-card campaign-analysis-empty">
            {bilingual(lang, "正在汇总标注…", "Loading annotations…")}
          </div>
        ) : summaryQuery.isError && !data ? (
          <div className="page-card campaign-analysis-empty">
            {summaryQuery.error instanceof Error
              ? summaryQuery.error.message
              : bilingual(lang, "加载标注汇总失败", "Failed to load labeling summary")}
          </div>
        ) : data ? (
          <>
            <nav className="mobile-summary-tools">
              <button
                className="button button-quiet"
                type="button"
                onClick={() => caseListRef.current?.scrollIntoView({ behavior: "smooth" })}
              >
                {bilingual(lang, "查看标注明细", "Go to annotations")}
              </button>
              <button
                className="button button-quiet"
                type="button"
                aria-controls="labelSummaryClusterPanels"
                aria-expanded={mobileChartsOpen}
                onClick={() => setMobileChartsOpen((prev) => !prev)}
              >
                {bilingual(lang, "场景与标签图表", "Tag charts")}
              </button>
            </nav>

            <section className="analysis-summary-grid" aria-label="Labeling overview">
              <article className="analysis-stat-card">
                <span>{bilingual(lang, "问题标注", "Annotations")}</span>
                <strong>{Number(data.annotated || 0)}</strong>
                <small>
                  {bilingual(
                    lang,
                    `当前范围 ${Number(data.total || 0)} 个 Case`,
                    `${Number(data.total || 0)} cases in scope`,
                  )}
                </small>
              </article>

              <article className="analysis-stat-card">
                <span>{bilingual(lang, "已填写依据", "With rationale")}</span>
                <strong>{Number(data.reason_count || 0)}</strong>
                <small>
                  {bilingual(
                    lang,
                    `未填写 ${Number(data.empty_reason_count || 0)}`,
                    `${Number(data.empty_reason_count || 0)} empty`,
                  )}
                </small>
              </article>

              <button
                className="analysis-stat-card label-summary-adjudicated"
                id="labelSummaryAdjudicated"
                type="button"
                aria-pressed={route.cluster === "adjudicated"}
                onClick={() =>
                  setRoute((prev) => ({
                    ...prev,
                    cluster: prev.cluster === "adjudicated" ? "" : "adjudicated",
                    page: 1,
                  }))
                }
              >
                <span>{bilingual(lang, "已裁决 Case", "Adjudicated cases")}</span>
                <strong>{Number(data.adjudicated_count || 0)}</strong>
                <small>
                  {route.cluster === "adjudicated"
                    ? bilingual(lang, "正在筛选 · 点击取消", "Filtering · click to clear")
                    : bilingual(lang, "查看裁决记录", "View adjudicated")}
                </small>
              </button>
            </section>

            <section
              className="analysis-decision-grid analysis-has-gt"
              aria-label={bilingual(lang, "标注状态与 GT 对照", "Label state and GT comparison")}
            >
              <AnalysisGtCard
                counts={data.gt_update_counts}
                detailHref={chartGt => labelingHref({ chartGt })}
                prefix="labelSummary"
                lang={lang}
                onOpenRules={() => setRulesModalMode("gt")}
                onShowTooltip={showTooltip}
                onHideTooltip={hideTooltip}
              />

              <section
                className="page-card analysis-review-status-card"
                aria-labelledby="labelSummaryStatusTitle"
              >
                <div className="section-heading analysis-review-status-heading">
                  <div>
                    <h3 id="labelSummaryStatusTitle">
                      {bilingual(lang, "标注状态", "Labeling status")}
                    </h3>
                  </div>
                  <small>
                    {bilingual(
                      lang,
                      `已提交 ${Number(data.annotated || 0)} 个 Issue`,
                      `${Number(data.annotated || 0)} submitted Issues`,
                    )}
                  </small>
                </div>
                <div className="analysis-review-status-chart" id="labelSummaryStatusChart">
                  <AnalysisStatusBar
                    statuses={statusItems}
                    lang={lang}
                    detailHref={chartLabel => labelingHref({ chartLabel })}
                    emptyText={bilingual(lang, "暂无标注提交", "No annotations yet")}
                  />
                </div>
              </section>

              <section className="page-card analysis-confusion-card" aria-labelledby="labelSummaryMatrixTitle">
                <div className="section-heading analysis-confusion-heading label-summary-matrix-heading">
                  <h3 id="labelSummaryMatrixTitle">{bilingual(lang, "GT × 标注结果混淆矩阵", "GT × labeling confusion matrix")}</h3>
                  <span className="label-summary-matrix-counts">
                    <small>
                      {bilingual(
                        lang,
                        `可比较 ${confusionData.comparable} / ${data.total} · 一致 ${confusionData.matches}`,
                        `Comparable ${confusionData.comparable} / ${data.total} · Matches ${confusionData.matches}`,
                      )}
                    </small>
                    {matrixReasons.length > 0 && (
                      <UiInfoPopover id="labelSummaryMatrixInfo" ariaLabel={bilingual(lang, "可比较说明", "Comparison details")}>
                        <strong>{bilingual(lang, "未纳入", "Excluded")} {data.total - confusionData.comparable}</strong>
                        {matrixReasons.map(({ key, label, count }) => (
                          <span key={key} className="label-summary-matrix-exclusion"><span>{label}</span><b>{count}</b></span>
                        ))}
                      </UiInfoPopover>
                    )}
                  </span>
                </div>
                <div className="analysis-confusion-wrap" id="labelSummaryConfusionMatrix">
                  <AnalysisConfusionTable
                    cornerHeader={bilingual(lang, "GT ↓ / 标注 →", "GT ↓ / Label →")}
                    columnLabels={confusionData.columnLabels}
                    rows={confusionData.rows}
                    totalLabel={bilingual(lang, "合计", "Total")}
                    columnTotals={confusionData.colTotals}
                    grandTotal={confusionData.grandTotal}
                  />
                </div>
              </section>
            </section>

            <section
              className={`analysis-cluster-grid${mobileChartsOpen ? " mobile-expanded" : ""}`}
              id="labelSummaryClusterPanels"
              aria-label="Structured labeling clusters"
            >
              {clusterPanels.map((panel) => {
                const dual = panel.layout === "dual";
                const palette = analysisPiePalette(panel.key, theme);
                return (
                  <article
                    key={panel.key}
                    className={`page-card analysis-cluster-card layout-${panel.layout}`}
                    data-panel={panel.key}
                  >
                    <div className="section-heading">
                      <div>
                        <h3>{panel.label}</h3>
                      </div>
                    </div>
                    <div className={`analysis-pie-groups ${dual ? "dual" : "single"}`}>
                      {panel.groups.map((group) => (
                        <AnalysisDonutGroup
                          key={group.key}
                          group={group}
                          palette={palette}
                          dual={dual}
                          lang={lang}
                          onShowTooltip={showTooltip}
                          onHideTooltip={hideTooltip}
                        />
                      ))}
                    </div>
                  </article>
                );
              })}
            </section>

            <section className="page-card analysis-case-card">
              <div className="section-heading label-summary-detail-heading">
                <h3>{bilingual(lang, "标注依据明细", "Label rationales")}</h3>
                <div className="label-summary-detail-actions">
                  {(route.chartGt || route.chartLabel) && (
                    <span className="chart-detail-filter">
                      <a href={chartHref({ chartGt: "", chartLabel: "" })}>
                        {bilingual(lang, "清除图表筛选", "Clear chart filter")}
                      </a>
                    </span>
                  )}
                  <button
                    className="text-link label-summary-rules-button"
                    id="labelSummaryRulesButton"
                    type="button"
                    aria-haspopup="dialog"
                    onClick={() => setRulesModalMode("expected")}
                  >
                    <span aria-hidden="true">ⓘ</span>{" "}
                    {bilingual(lang, "期望输出规则", "Result rules")}
                  </button>
                  <small>
                    {bilingual(
                      lang,
                      `共 ${Number(data.annotated || 0)} 个 Case · 当前页 ${items.length} 个`,
                      `${Number(data.annotated || 0)} ${
                        Number(data.annotated || 0) === 1 ? "Case" : "Cases"
                      } · ${items.length} on this page`,
                    )}
                  </small>
                </div>
              </div>

              <div className="analysis-case-list" id="labelSummaryCaseList" tabIndex={-1} ref={caseListRef}>
                {items.length ? (
                  items.map((item) => {
                    const issueId = String(item.issue_id || "");
                    const scene =
                      item.title ||
                      item.scenario ||
                      bilingual(lang, "未提供场景描述", "No scene description");
                    const statusLabel =
                      (
                        {
                          resolved: bilingual(lang, "已形成结论", "Resolved"),
                          pending: bilingual(lang, "待形成结论", "Pending"),
                          conflict: bilingual(
                            lang,
                            "待裁决 / 需确认",
                            "Needs adjudication / confirmation",
                          ),
                        } as Record<string, string>
                      )[item.label_state || ""] || bilingual(lang, "待形成结论", "Pending");
                    const rationales = item.rationales || [];
                    const detailUrl = buildCaseDetailUrl(
                      issueId,
                      route,
                      tasks,
                      selectedBaselines,
                    );
                    const primary =
                      item.label_state === "resolved" ? item.adjudication || null : null;
                    const currentStatus = item.decision?.stale
                      ? bilingual(lang, "裁决需确认", "Decision needs confirmation")
                      : primary
                        ? bilingual(lang, "已裁决", "Adjudicated")
                        : statusLabel;
                    const statusKind = item.decision?.stale
                      ? "stale"
                      : primary
                        ? "adjudicated"
                        : item.label_state || "pending";
                    const statusTitle =
                      primary?.kind === "task"
                        ? bilingual(lang, "任务内裁决", "Task decision")
                        : primary?.kind === "issue"
                          ? bilingual(lang, "Issue 裁决", "Issue decision")
                          : currentStatus;
                    const resolved =
                      item.label_state === "resolved" && isTriageLabel(item.expected_output);
                    const gtMatches = resolved && isTriageLabel(item.gt_label);
                    const sourceCount = Number(item.source_count || 0);
                    const actionLabel =
                      item.label_state === "conflict"
                        ? bilingual(lang, "查看并确认", "Review sources")
                        : bilingual(lang, "Case 详情", "Case details");

                    return (
                      <article key={issueId} className="analysis-case-row label-summary-case-row">
                        <div className="analysis-case-identity">
                          <a className="analysis-issue-link" href={detailUrl}>
                            {issueId}
                          </a>
                          {!isTriageLabel(scene.trim()) && <span title={scene}>{scene}</span>}
                        </div>

                        <div className="analysis-case-labels">
                          <div className="label-summary-result-line">
                            <span className="label-summary-final-label">
                              <span>{bilingual(lang, "期望输出", "Expected result")}</span>
                              {resolved ? (
                                <LabelBadge label={item.expected_output} />
                              ) : (
                                <span className="muted">
                                  {bilingual(lang, "待确定", "Undetermined")}
                                </span>
                              )}
                            </span>
                          </div>
                          <div className="label-summary-result-line">
                            <span className="label-summary-gt-line">
                              {`${bilingual(lang, "当前 GT", "Current GT")}：${
                                item.gt_label || bilingual(lang, "未设置", "Not set")
                              }`}
                              {gtMatches && (
                                <span
                                  className={`label-summary-gt-relation ${
                                    item.gt_label === item.expected_output
                                      ? "is-match"
                                      : "is-different"
                                  }`}
                                >
                                  {item.gt_label === item.expected_output
                                    ? bilingual(lang, "一致", "Matches")
                                    : bilingual(lang, "与 GT 不一致", "Differs from GT")}
                                </span>
                              )}
                            </span>
                            <span
                              className="label-summary-status"
                              data-state={statusKind}
                              title={statusTitle}
                            >
                              {currentStatus}
                            </span>
                            {item.exclusion_conflict ? (
                              <span className="label-summary-status" data-state="pending">{bilingual(lang, "排除待确定", "Exclusion pending")}</span>
                            ) : item.is_excluded && (
                              <span className="label-summary-excluded">
                                {bilingual(lang, "已排除", "Excluded")}
                              </span>
                            )}
                          </div>
                        </div>

                        <div className="analysis-case-reason">
                          <strong className={rationales.length ? undefined : "reason-empty"}>
                            {rationales[0] ||
                              bilingual(lang, "未填写标注依据", "No label rationale")}
                          </strong>
                          {rationales.slice(1).map((reason, idx) => (
                            <p key={idx}>{reason}</p>
                          ))}
                          <div className="analysis-chip-list">
                            {(item.tags || []).map((key) => (
                              <span key={`tag-${key}`} className="analysis-chip tag-chip">
                                {tagLabel(key, config)}
                              </span>
                            ))}
                            {(item.evidence_gaps || []).map((key) => (
                              <span key={`ev-${key}`} className="analysis-chip evidence-chip">
                                {evidenceLabel(key, config)}
                              </span>
                            ))}
                          </div>
                          {primary && (item.original_votes || []).length > 0 && (
                            <details className="label-summary-original-votes">
                              <summary>
                                {item.original_conflict
                                  ? bilingual(
                                      lang,
                                      "原始冲突 · 查看标注意见",
                                      "Original conflict · view votes",
                                    )
                                  : bilingual(lang, "原始标注意见", "Original votes")}
                              </summary>
                              {(item.original_votes || []).map((vote, idx) => (
                                <p key={idx}>
                                  {`${vote.author}：${
                                    vote.expected_output || bilingual(lang, "待补充", "Pending")
                                  }${vote.rationale ? ` · ${vote.rationale}` : ""}`}
                                </p>
                              ))}
                            </details>
                          )}
                        </div>

                        <div className="analysis-case-meta">
                          <div className="label-summary-source-line">
                            {renderSourceMarkup(item)}
                          </div>
                          {!resolved && (
                            <span>
                              {(item.authors || []).join("、") ||
                                bilingual(lang, "未记录标注人", "No labeler recorded")}
                            </span>
                          )}
                          <span>
                            {bilingual(
                              lang,
                              `${sourceCount} 个来源`,
                              `${sourceCount} ${sourceCount === 1 ? "source" : "sources"}`,
                            )}
                            {item.created_at ? ` · ${formatCstTime(item.created_at, lang)}` : ""}
                          </span>
                          <span className="analysis-case-actions">
                            <a className="text-link" href={detailUrl}>
                              {actionLabel}
                            </a>
                          </span>
                        </div>
                      </article>
                    );
                  })
                ) : (
                  <div className="analysis-empty">
                    {bilingual(lang, "当前范围暂无标注提交", "No annotations in this scope")}
                  </div>
                )}
              </div>

              <div className="label-summary-pagination">
                <Pagination
                  page={page}
                  pageSize={Number(data.page_size || route.pageSize)}
                  total={Number(data.annotated || 0)}
                  lang={lang}
                  loading={summaryQuery.isFetching}
                  labelText={`${page} / ${pageCount}`}
                  ariaLabel={bilingual(lang, "标注明细分页", "Annotation pagination")}
                  onPageChange={(nextPage) =>
                    setRoute((prev) => ({ ...prev, page: nextPage }))
                  }
                  onPageSizeChange={(nextSize) =>
                    setRoute((prev) => ({ ...prev, page: 1, pageSize: nextSize }))
                  }
                />
              </div>
            </section>
          </>
        ) : null}
      </div>

      <AnalysisPieTooltip tooltip={tooltip} tipRef={tipRef} lang={lang} />

      <LabelSummaryRulesDialog
        mode={rulesModalMode}
        lang={lang}
        onClose={() => setRulesModalMode(null)}
      />

      <ModalDialog
        open={issueModalOpen}
        title={bilingual(lang, "按多 Issue 查询", "Query by Issue list")}
        lang={lang}
        onClose={() => setIssueModalOpen(false)}
        footer={
          <>
            <button
              className="button button-quiet"
              type="button"
              onClick={() => setIssueDraft("")}
            >
              {bilingual(lang, "清空", "Clear")}
            </button>
            <button
              className="button button-primary"
              type="button"
              onClick={handleApplyIssues}
            >
              {bilingual(lang, "应用筛选", "Apply filter")}
            </button>
          </>
        }
      >
        <div className="ra-issue-query-body">
          <textarea
            className="analysis-issue-input"
            rows={5}
            value={issueDraft}
            placeholder={bilingual(
              lang,
              "粘贴多个 Issue ID 或链接，用换行、空格或逗号分隔",
              "Paste multiple Issue IDs or URLs separated by newlines, spaces, or commas",
            )}
            aria-label={bilingual(lang, "多 Issue 输入框", "Multi-Issue input")}
            onChange={(e) => setIssueDraft(e.target.value)}
          />
          <p
            className={`issue-query-feedback${
              parsedIssues.invalid.length
                ? " is-error"
                : parsedIssues.ids.length
                  ? " is-ready"
                  : ""
            }`}
          >
            {parsedIssues.invalid.length
              ? bilingual(
                  lang,
                  `已识别 ${parsedIssues.ids.length} 个 Issue；无法识别：${parsedIssues.invalid
                    .slice(0, 4)
                    .join("、")}${parsedIssues.invalid.length > 4 ? "…" : ""}`,
                  `${parsedIssues.ids.length} Issues recognized; invalid: ${parsedIssues.invalid
                    .slice(0, 4)
                    .join(", ")}${parsedIssues.invalid.length > 4 ? "…" : ""}`,
                )
              : parsedIssues.ids.length
                ? bilingual(
                    lang,
                    `已识别 ${parsedIssues.ids.length} 个 Issue（重复项已去重）`,
                    `${parsedIssues.ids.length} Issues recognized (duplicates removed)`,
                  )
                : bilingual(
                    lang,
                    "输入为空，将清除多 Issue 条件",
                    "Empty input will clear the multi-Issue filter",
                  )}
          </p>
        </div>
      </ModalDialog>
    </div>
  );
};
