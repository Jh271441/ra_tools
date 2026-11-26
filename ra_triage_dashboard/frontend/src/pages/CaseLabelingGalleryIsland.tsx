import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, UiLanguage } from "../bridge/useWorkbenchBridge";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";
import {
  CASE_PAGE_SIZES,
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { TRIAGE_LABELS } from "../components/charts/AnalysisCharts";
import {
  GalleryCaseItem,
  IssueCardGrid,
} from "../components/gallery/IssueCardGrid";
import { IssueQueryModal } from "../components/gallery/IssueQueryModal";
import { showToast } from "../components/ui/Toast";
import {
  BaselineCatalogItem,
  DashboardConfigPayload,
  ISSUE_QUERY_ID_RE,
  joinFilterList,
  normalizedGtRelationFilters,
  normalizedLabelingStatusFilters,
  parseFilterList,
  readLegacyConfig,
  UiInfoPopover,
} from "../utils/analysisHelpers";

export interface CaseLabelingGalleryIslandProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
  isAdmin: boolean;
  canWrite: boolean;
}

interface LabelingTaskProgressAssignee {
  name: string;
  labeled: number;
  total: number;
}

interface LabelingTaskItem {
  id: string;
  name?: string;
  member_count?: number;
  workset_id?: string;
  baseline_scope?: string;
  baseline_scopes?: string[];
  progress?: {
    total?: number;
    resolved?: number;
    conflict?: number;
    assignees?: LabelingTaskProgressAssignee[];
  };
}

interface LabelingCasesResponse {
  items: GalleryCaseItem[];
  total: number;
  page: number;
  pages: number;
  page_size: number;
  labelers?: string[];
  assignees?: string[];
  queue_issue_ids?: string[];
  inactive?: boolean;
}

interface LabelingFilterState {
  taskId: string;
  targetGroup: string;
  issueTags: string[];
  search: string;
  issueIds: string[];
  status: string[];
  author: string[];
  assignee: string[];
  cluster: string;
  label: string[];
  gt: string[];
  gtRelations: string[];
  commentState: string[];
  exclusion: string[];
  page: number;
  pageSize: number;
}

interface LegacyLabelingBridgeWindow {
  state?: {
    config?: DashboardConfigPayload & {
      case_labeling?: { active_baseline_ids?: string[] };
    };
    baselineCatalog?: BaselineCatalogItem[];
    caseLabeling?: { issueId?: string };
  };
  pageUrl?: (page: string, opts?: Record<string, unknown>) => string;
  showPage?: (page: string, opts?: Record<string, unknown>) => void;
  navigatePage?: (page: string, opts?: Record<string, unknown>) => void;
  setBaselineScopes?: (ids: string[]) => Promise<void>;
  selectCaseLabelingIssue?: (issueId: string, opts?: Record<string, unknown>) => Promise<void>;
  exportLabelingGtUpdate?: (filters: Record<string, unknown>, button?: HTMLButtonElement | null) => Promise<void>;
  createCaseLabelingResultSnapshot?: () => Promise<void>;
  syncCaseLabelingGalleryState?: (snapshot: Record<string, unknown>) => void;
}

function readLabelingFiltersFromUrl(): LabelingFilterState {
  const params = new URLSearchParams(
    typeof window !== "undefined" ? window.location.search : "",
  );
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(
    params.get("page_size") || String(DEFAULT_CASE_PAGE_SIZE),
    10,
  );
  const cluster = String(params.get("cluster") || "").trim();
  return {
    taskId: /^(?:split|campaign)-[A-Za-z0-9]+$/.test(params.get("task") || "")
      ? params.get("task") || ""
      : "",
    targetGroup: params.get("target_group") || "",
    issueTags: parseFilterList(params.get("issue_tags")),
    search: params.get("q") || "",
    issueIds: parseFilterList(params.get("issue_ids")).filter((v) =>
      ISSUE_QUERY_ID_RE.test(v),
    ),
    status: normalizedLabelingStatusFilters(params.get("status")),
    author: parseFilterList(params.get("author"))
      .map((v) => v.toLowerCase())
      .filter((v) => /^[a-z0-9._@-]{1,128}$/.test(v)),
    assignee: parseFilterList(params.get("assignee"))
      .map((v) => v.toLowerCase())
      .filter((v) => /^[a-z0-9._@-]{1,128}$/.test(v)),
    cluster:
      cluster === "adjudicated" || /^(pair|scenario):.{1,200}$/.test(cluster)
        ? cluster
        : "",
    label: parseFilterList(params.get("label")).filter((v) =>
      (TRIAGE_LABELS as readonly string[]).includes(v),
    ),
    gt: parseFilterList(params.get("gt")).filter((v) =>
      (TRIAGE_LABELS as readonly string[]).includes(v),
    ),
    gtRelations: normalizedGtRelationFilters(params.get("gt_relation")),
    commentState: parseFilterList(params.get("comment_state")).filter((v) =>
      ["with", "without"].includes(v),
    ),
    exclusion: parseFilterList(params.get("exclusion")).filter((v) =>
      ["excluded", "active"].includes(v),
    ),
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

function buildTaskScopeKey(
  baselines: string,
  f: LabelingFilterState,
  liveSearch: string,
): string {
  const trimmedSearch = liveSearch.trim();
  return JSON.stringify({
    baselines,
    taskId: f.taskId || "",
    q: trimmedSearch,
    issueIds: trimmedSearch ? [] : f.issueIds,
    targetGroup: f.targetGroup || "",
    issueTags: f.issueTags,
    status: f.status,
    author: f.author,
    assignee: f.assignee,
    cluster: f.cluster || "",
    exclusion: f.exclusion,
    label: f.label,
    gt: f.gt,
    gtRelations: f.gtRelations,
    commentState: f.commentState,
  });
}

export const CaseLabelingGalleryIsland: React.FC<CaseLabelingGalleryIslandProps> = ({
  active,
  lang,
  selectedBaselines,
  isAdmin,
  canWrite,
}) => {
  const [filters, setFilters] = useState<LabelingFilterState>(() =>
    readLabelingFiltersFromUrl(),
  );
  const [searchDraft, setSearchDraft] = useState<string>(filters.search);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [issueQueryOpen, setIssueQueryOpen] = useState(false);
  const [exportingIssues, setExportingIssues] = useState(false);
  const [exportingGt, setExportingGt] = useState(false);
  const [savingSnapshot, setSavingSnapshot] = useState(false);
  const [checkingTaskScope, setCheckingTaskScope] = useState(false);
  const prevBaselinesKeyRef = useRef<string>(selectedBaselines.join(","));
  const wasActiveRef = useRef<boolean>(false);
  const activeRef = useRef<boolean>(active);
  activeRef.current = active;
  const taskCheckAbortRef = useRef<AbortController | null>(null);
  const taskCheckSeqRef = useRef<number>(0);

  const baselinesQuery = useMemo(
    () => (selectedBaselines.length ? selectedBaselines.join(",") : "0508"),
    [selectedBaselines],
  );

  const currentTaskScopeKey = useMemo(
    () => buildTaskScopeKey(baselinesQuery, filters, searchDraft),
    [baselinesQuery, filters, searchDraft],
  );
  const currentTaskScopeKeyRef = useRef<string>(currentTaskScopeKey);
  currentTaskScopeKeyRef.current = currentTaskScopeKey;
  const prevTaskScopeKeyRef = useRef<string>(currentTaskScopeKey);

  // Cancel any pending task-scope recount when leaving the gallery or unmounting
  useEffect(() => {
    if (!active) {
      taskCheckSeqRef.current += 1;
      taskCheckAbortRef.current?.abort();
      taskCheckAbortRef.current = null;
      setCheckingTaskScope(false);
    }
    return () => {
      taskCheckSeqRef.current += 1;
      taskCheckAbortRef.current?.abort();
      taskCheckAbortRef.current = null;
    };
  }, [active]);

  // Cancel any pending task-scope recount if the user edits search, filters, or dataset in-place
  useEffect(() => {
    if (prevTaskScopeKeyRef.current !== currentTaskScopeKey) {
      prevTaskScopeKeyRef.current = currentTaskScopeKey;
      if (taskCheckAbortRef.current) {
        taskCheckSeqRef.current += 1;
        taskCheckAbortRef.current.abort();
        taskCheckAbortRef.current = null;
        setCheckingTaskScope(false);
      }
    }
  }, [currentTaskScopeKey]);

  // Read config via legacy state or /api/config fallback
  const legacyConfig = readLegacyConfig() as
    | (DashboardConfigPayload & { case_labeling?: { active_baseline_ids?: string[] } })
    | null;
  const configQuery = useQuery<
    DashboardConfigPayload & { case_labeling?: { active_baseline_ids?: string[] } }
  >({
    queryKey: ["labeling-gallery-config"],
    queryFn: ({ signal }) => apiRequest("/api/dashboard-config", { signal }),
    enabled: active && !legacyConfig?.baselines?.length,
    staleTime: 60_000,
  });
  const effectiveConfig = legacyConfig?.baselines?.length
    ? legacyConfig
    : configQuery.data || legacyConfig;

  const activeBaselineIds = useMemo(
    () =>
      Array.from(
        new Set((effectiveConfig?.case_labeling?.active_baseline_ids || []).map(String)),
      ),
    [effectiveConfig],
  );

  const selectedActiveBaselines = useMemo(() => {
    if (!effectiveConfig) return selectedBaselines.length ? selectedBaselines : ["0508"];
    const activeSet = new Set(activeBaselineIds);
    const current = selectedBaselines.length ? selectedBaselines : ["0508"];
    return current.filter((id) => activeSet.has(id));
  }, [effectiveConfig, activeBaselineIds, selectedBaselines]);

  const isInactiveScope = Boolean(
    effectiveConfig && activeBaselineIds.length > 0 && selectedActiveBaselines.length === 0,
  );

  // Sync URL -> state on page re-entry or popstate
  useEffect(() => {
    if (active && !wasActiveRef.current) {
      const next = readLabelingFiltersFromUrl();
      setFilters(next);
      setSearchDraft(next.search);
    }
    wasActiveRef.current = active;
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const onPopState = () => {
      const next = readLabelingFiltersFromUrl();
      setFilters(next);
      setSearchDraft(next.search);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [active]);

  // Reset to page 1 when topbar dataset changes
  useEffect(() => {
    const key = selectedBaselines.join(",");
    if (prevBaselinesKeyRef.current && prevBaselinesKeyRef.current !== key) {
      setFilters((prev) => ({ ...prev, page: 1 }));
    }
    prevBaselinesKeyRef.current = key;
  }, [selectedBaselines]);

  // Persist URL when user edits filters (preserve deep-linked ?issue= if present on initial mount)
  const persistRoute = useCallback(
    (next: LabelingFilterState, clearIssue = true) => {
      if (!active || typeof window === "undefined") return;
      const win = window as unknown as LegacyLabelingBridgeWindow;
      const currentIssue = clearIssue
        ? ""
        : new URLSearchParams(window.location.search).get("issue") || "";
      let nextUrl = "";
      if (typeof win.pageUrl === "function") {
        nextUrl = win.pageUrl("labeling", {
          issue: currentIssue,
          taskId: next.taskId,
          targetGroup: next.targetGroup,
          issueTags: next.issueTags,
          search: next.search,
          issueIds: next.issueIds,
          status: next.status,
          author: next.author,
          assignee: next.assignee,
          cluster: next.cluster,
          label: next.label,
          gt: next.gt,
          gtRelations: next.gtRelations,
          commentState: next.commentState,
          exclusion: next.exclusion,
          page: next.page,
          pageSize: next.pageSize,
          baselines: selectedBaselines,
        });
      } else {
        const params = new URLSearchParams();
        if (currentIssue) params.set("issue", currentIssue);
        if (next.taskId) params.set("task", next.taskId);
        if (next.targetGroup) params.set("target_group", next.targetGroup);
        if (next.issueTags.length) params.set("issue_tags", joinFilterList(next.issueTags));
        if (next.search) params.set("q", next.search);
        if (next.issueIds.length) params.set("issue_ids", next.issueIds.join(","));
        if (next.status.length) params.set("status", joinFilterList(next.status));
        if (next.author.length) params.set("author", joinFilterList(next.author));
        if (next.assignee.length) params.set("assignee", joinFilterList(next.assignee));
        if (next.cluster) params.set("cluster", next.cluster);
        if (next.label.length) params.set("label", joinFilterList(next.label));
        if (next.gt.length) params.set("gt", joinFilterList(next.gt));
        if (next.gtRelations.length) params.set("gt_relation", joinFilterList(next.gtRelations));
        if (next.commentState.length) params.set("comment_state", joinFilterList(next.commentState));
        if (next.exclusion.length) params.set("exclusion", joinFilterList(next.exclusion));
        if (next.page > 1) params.set("page", String(next.page));
        if (next.pageSize !== DEFAULT_CASE_PAGE_SIZE) params.set("page_size", String(next.pageSize));
        if (selectedBaselines.length) params.set("baselines", selectedBaselines.join(","));
        const qs = params.toString();
        nextUrl = `${window.location.pathname}${qs ? `?${qs}` : ""}`;
      }
      const currentUrl = `${window.location.pathname}${window.location.search}`;
      if (nextUrl && nextUrl !== currentUrl) {
        window.history.replaceState({ page: "labeling" }, "", nextUrl);
      }
    },
    [active, selectedBaselines],
  );

  const updateFilters = useCallback(
    (updater: (prev: LabelingFilterState) => LabelingFilterState) => {
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
    if (!active) return;
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
  }, [active, searchDraft, filters.search, updateFilters]);

  // Tasks query
  const tasksQuery = useQuery<{ items?: LabelingTaskItem[] }>({
    queryKey: ["labeling-gallery-tasks", baselinesQuery],
    queryFn: ({ signal }) =>
      apiRequest(`/api/labeling/tasks?baselines=${encodeURIComponent(baselinesQuery)}`, {
        signal,
      }),
    enabled: active && (canWrite || isAdmin),
    staleTime: 15_000,
  });
  const tasks = tasksQuery.data?.items || [];

  // Build list query params
  const listParams = useMemo(() => {
    return new URLSearchParams({
      baselines: baselinesQuery,
      task_id: filters.taskId || "",
      q: filters.search || "",
      issue_ids: filters.issueIds.join(","),
      target_group: filters.targetGroup || "",
      issue_tags: joinFilterList(filters.issueTags),
      status: joinFilterList(filters.status),
      author: joinFilterList(filters.author),
      assignee: joinFilterList(filters.assignee),
      cluster: filters.cluster || "",
      exclusion: joinFilterList(filters.exclusion),
      label: joinFilterList(filters.label),
      gt: joinFilterList(filters.gt),
      gt_relation: joinFilterList(filters.gtRelations),
      comment_state: joinFilterList(filters.commentState),
      page: String(Math.max(1, filters.page)),
      page_size: String(filters.pageSize),
    });
  }, [baselinesQuery, filters]);

  const casesQuery = useQuery<LabelingCasesResponse>({
    queryKey: ["labeling-gallery-cases", listParams.toString()],
    queryFn: ({ signal }) => apiRequest(`/api/labeling/cases?${listParams.toString()}`, { signal }),
    enabled: active && !isInactiveScope && (canWrite || isAdmin),
    placeholderData: (prev) => prev,
  });

  const casesRefreshFailed = casesQuery.isError || casesQuery.failureCount > 0;
  const casesFailureError = casesQuery.isError
    ? casesQuery.error
    : casesQuery.failureCount > 0
      ? casesQuery.failureReason
      : null;

  const data: LabelingCasesResponse = useMemo(() => {
    if (isInactiveScope) {
      return {
        items: [],
        total: 0,
        page: 1,
        pages: 1,
        page_size: filters.pageSize,
        inactive: true,
      };
    }
    if (casesRefreshFailed) {
      return {
        items: [],
        total: 0,
        page: filters.page,
        pages: 1,
        page_size: filters.pageSize,
        labelers: casesQuery.data?.labelers || [],
        assignees: casesQuery.data?.assignees || [],
      };
    }
    return (
      casesQuery.data || {
        items: [],
        total: 0,
        page: filters.page,
        pages: 1,
        page_size: filters.pageSize,
      }
    );
  }, [isInactiveScope, casesRefreshFailed, casesQuery.data, filters.page, filters.pageSize]);

  // Sync bridge state so classic #caseLabelingDetail has queue, tasks, filters, and export payload
  useEffect(() => {
    if (!active) return;
    const win = window as unknown as LegacyLabelingBridgeWindow;
    win.syncCaseLabelingGalleryState?.({
      ...filters,
      tasks,
      data,
      labelers: data.labelers || [],
      assignees: data.assignees || [],
    });
  }, [active, filters, tasks, data]);

  // Dropdown options
  const taskOptions: UiSelectOption[] = useMemo(() => {
    return [
      { value: "", label: bilingual(lang, "全部标注", "All labeling") },
      ...tasks.map((task) => {
        const name = task.name || task.id;
        const progress = task.progress || {};
        const total = Number(progress.total || task.member_count || 0);
        const resolved = Number(progress.resolved || 0);
        const conflict = Number(progress.conflict || 0);
        const parts = [
          bilingual(
            lang,
            `${name} · ${resolved}/${total} 已标注`,
            `${name} · ${resolved}/${total} labeled`,
          ),
        ];
        if (conflict > 0) {
          parts.push(bilingual(lang, `${conflict} 冲突`, `${conflict} conflicts`));
        }
        return { value: task.id, label: parts.join(" · ") };
      }),
    ];
  }, [tasks, lang]);

  const selectedTask = useMemo(
    () => (filters.taskId ? tasks.find((t) => t.id === filters.taskId) || null : null),
    [tasks, filters.taskId],
  );

  const statusOptions: MultiSelectOption[] = useMemo(
    () => [
      { value: "unannotated", label: bilingual(lang, "未标注", "Not annotated") },
      { value: "incomplete", label: bilingual(lang, "已提交 · 待补齐", "Submitted · Incomplete") },
      { value: "resolved", label: bilingual(lang, "已确认", "Confirmed") },
      {
        value: "conflict",
        label: bilingual(lang, "有分歧 / 待复核", "Disagreement / Needs recheck"),
      },
    ],
    [lang],
  );

  const issueTagOptions = useMemo(
    () => buildIssueTagOptions(effectiveConfig, filters.issueTags, lang),
    [effectiveConfig, filters.issueTags, lang],
  );

  const authorOptions: MultiSelectOption[] = useMemo(() => {
    const known = new Set(data.labelers || []);
    const all = Array.from(new Set([...(data.labelers || []), ...filters.author]));
    return all.map((name) => ({
      value: name,
      label: known.has(name) ? name : `${name} · ${bilingual(lang, "当前筛选", "Current filter")}`,
    }));
  }, [data.labelers, filters.author, lang]);

  const assigneeOptions: MultiSelectOption[] = useMemo(() => {
    const known = new Set(data.assignees || []);
    const all = Array.from(new Set([...(data.assignees || []), ...filters.assignee]));
    return all.map((name) => ({
      value: name,
      label: known.has(name) ? name : `${name} · ${bilingual(lang, "当前筛选", "Current filter")}`,
    }));
  }, [data.assignees, filters.assignee, lang]);

  const triageOptions: MultiSelectOption[] = useMemo(
    () => TRIAGE_LABELS.map((l) => ({ value: l, label: l })),
    [],
  );

  const gtRelationOptions: MultiSelectOption[] = useMemo(
    () => [
      { value: "matches_gt", label: bilingual(lang, "与 GT 一致", "Matches GT") },
      { value: "differs_from_gt", label: bilingual(lang, "与 GT 不一致", "Differs from GT") },
      { value: "fills_missing_gt", label: bilingual(lang, "GT 缺失", "GT missing") },
    ],
    [lang],
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
      { value: "active", label: bilingual(lang, "未排除", "Not excluded") },
      { value: "excluded", label: bilingual(lang, "已排除", "Excluded") },
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

  const handleReset = () => {
    setSearchDraft("");
    updateFilters((prev) => ({
      taskId: "",
      targetGroup: "",
      issueTags: [],
      search: "",
      issueIds: [],
      status: [],
      author: [],
      assignee: [],
      cluster: "",
      label: [],
      gt: [],
      gtRelations: [],
      commentState: [],
      exclusion: [],
      page: 1,
      pageSize: prev.pageSize,
    }));
  };

  const handleExportIssues = async () => {
    if (exportingIssues || isInactiveScope || casesRefreshFailed || !Number(data.total || 0)) return;
    setExportingIssues(true);
    try {
      const activeSearch = searchDraft.trim();
      const exportParams = new URLSearchParams(listParams);
      exportParams.set("q", activeSearch);
      if (activeSearch) exportParams.set("issue_ids", "");
      exportParams.set("page", "1");
      exportParams.set("page_size", "10");
      const result = await apiRequest<LabelingCasesResponse>(
        `/api/labeling/cases?${exportParams.toString()}`,
      );
      const rawIds = Array.isArray(result.queue_issue_ids)
        ? result.queue_issue_ids
        : (result.items || []).map((it) => it.issue_id);
      const ids = Array.from(new Set(rawIds.filter(Boolean)));
      if (ids.length !== Number(result.total || 0)) {
        throw new Error(
          bilingual(
            lang,
            "未获取完整 Issue 列表，请刷新后重试。",
            "The complete Issue list was not returned. Refresh and retry.",
          ),
        );
      }
      if (!ids.length) {
        showToast(bilingual(lang, "当前筛选没有可导出的 Issue。", "No Issues match the current filters."));
        return;
      }
      const csv =
        "\ufeffissue_id\r\n" +
        ids.map((id) => `"${String(id).replaceAll('"', '""')}"`).join("\r\n") +
        "\r\n";
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `labeling-issues-${ids.length}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      showToast(bilingual(lang, `已导出 ${ids.length} 个 Issue。`, `Exported ${ids.length} Issues.`));
    } catch (err) {
      showToast(err instanceof Error ? err.message : String(err), true);
    } finally {
      setExportingIssues(false);
    }
  };

  const handleExportGt = async (event: React.MouseEvent<HTMLButtonElement>) => {
    if (casesRefreshFailed || isInactiveScope) return;
    const win = window as unknown as LegacyLabelingBridgeWindow;
    if (typeof win.exportLabelingGtUpdate !== "function") return;
    setExportingGt(true);
    try {
      const activeSearch = searchDraft.trim();
      const activeIssueIds = activeSearch ? [] : filters.issueIds;
      const payload = {
        baselines: baselinesQuery,
        task_id: filters.taskId || "",
        q: activeSearch,
        issue_ids: activeIssueIds.join(","),
        target_group: filters.targetGroup || "",
        issue_tags: joinFilterList(filters.issueTags),
        status: joinFilterList(filters.status),
        author: joinFilterList(filters.author),
        assignee: joinFilterList(filters.assignee),
        cluster: filters.cluster || "",
        exclusion: joinFilterList(filters.exclusion),
        gt: joinFilterList(filters.gt),
        gt_relation: joinFilterList(filters.gtRelations),
        comment_state: joinFilterList(filters.commentState),
        label: joinFilterList(filters.label),
      };
      await win.exportLabelingGtUpdate(payload, event.currentTarget);
    } catch (err) {
      showToast(err instanceof Error ? err.message : String(err), true);
    } finally {
      setExportingGt(false);
    }
  };

  const handleSaveSnapshot = async () => {
    if (casesRefreshFailed || isInactiveScope) return;
    const win = window as unknown as LegacyLabelingBridgeWindow;
    if (typeof win.createCaseLabelingResultSnapshot !== "function") return;
    setSavingSnapshot(true);
    try {
      await win.createCaseLabelingResultSnapshot();
    } catch (err) {
      showToast(err instanceof Error ? err.message : String(err), true);
    } finally {
      setSavingSnapshot(false);
    }
  };

  const handleCreateTask = async () => {
    if (checkingTaskScope) return;
    if (!isAdmin) {
      showToast(bilingual(lang, "仅管理员可创建任务分配。", "Admin access is required."), true);
      return;
    }
    if (casesRefreshFailed) {
      showToast(
        casesFailureError instanceof Error
          ? casesFailureError.message
          : bilingual(lang, "读取 Case 列表失败，请重试。", "Failed to load Cases. Please retry."),
        true,
      );
      return;
    }
    if (isInactiveScope) {
      showToast(bilingual(lang, "当前筛选没有可分配的 Issue。", "No Issues match the current filters."), true);
      return;
    }
    const activeSearch = searchDraft.trim();
    const activeIssueIds = activeSearch ? [] : filters.issueIds;
    const searchChanged = activeSearch !== filters.search;
    const win = window as unknown as LegacyLabelingBridgeWindow;

    if (searchChanged || casesQuery.isFetching || casesQuery.isPlaceholderData) {
      const nextFilters: LabelingFilterState = searchChanged
        ? {
            ...filters,
            search: activeSearch,
            issueIds: activeIssueIds,
            page: 1,
          }
        : filters;
      const requestedScopeKey = buildTaskScopeKey(baselinesQuery, nextFilters, activeSearch);
      const countParams = new URLSearchParams({
        baselines: baselinesQuery,
        task_id: nextFilters.taskId || "",
        q: nextFilters.search || "",
        issue_ids: nextFilters.issueIds.join(","),
        target_group: nextFilters.targetGroup || "",
        issue_tags: joinFilterList(nextFilters.issueTags),
        status: joinFilterList(nextFilters.status),
        author: joinFilterList(nextFilters.author),
        assignee: joinFilterList(nextFilters.assignee),
        cluster: nextFilters.cluster || "",
        exclusion: joinFilterList(nextFilters.exclusion),
        label: joinFilterList(nextFilters.label),
        gt: joinFilterList(nextFilters.gt),
        gt_relation: joinFilterList(nextFilters.gtRelations),
        comment_state: joinFilterList(nextFilters.commentState),
        page: "1",
        page_size: "1",
      });
      taskCheckAbortRef.current?.abort();
      const controller = new AbortController();
      taskCheckAbortRef.current = controller;
      const seq = ++taskCheckSeqRef.current;
      setCheckingTaskScope(true);
      try {
        if (searchChanged) {
          setFilters(nextFilters);
          persistRoute(nextFilters, true);
        }
        const fresh = await apiRequest<LabelingCasesResponse>(
          `/api/labeling/cases?${countParams.toString()}`,
          { signal: controller.signal },
        );
        const activeLegacyPage = (win.state as { activePage?: string } | undefined)?.activePage;
        if (
          !activeRef.current ||
          taskCheckSeqRef.current !== seq ||
          controller.signal.aborted ||
          currentTaskScopeKeyRef.current !== requestedScopeKey ||
          (activeLegacyPage && activeLegacyPage !== "labeling")
        ) {
          return;
        }
        const freshTotal = Number(fresh.total || 0);
        if (!freshTotal) {
          showToast(
            bilingual(lang, "当前筛选没有可分配的 Issue。", "No Issues match the current filters."),
            true,
          );
          return;
        }
        win.syncCaseLabelingGalleryState?.({
          ...nextFilters,
          tasks,
          data: { ...data, total: freshTotal },
          labelers: fresh.labelers || data.labelers || [],
          assignees: fresh.assignees || data.assignees || [],
        });
        win.showPage?.("labeling-new-task", { historyMode: "push" });
      } catch (err) {
        if (
          !activeRef.current ||
          taskCheckSeqRef.current !== seq ||
          controller.signal.aborted ||
          currentTaskScopeKeyRef.current !== requestedScopeKey ||
          (err instanceof DOMException && err.name === "AbortError")
        ) {
          return;
        }
        showToast(
          err instanceof Error
            ? err.message
            : bilingual(lang, "读取 Case 列表失败，请重试。", "Failed to load Cases. Please retry."),
          true,
        );
      } finally {
        if (taskCheckAbortRef.current === controller) {
          taskCheckAbortRef.current = null;
        }
        if (activeRef.current && taskCheckSeqRef.current === seq) {
          setCheckingTaskScope(false);
        }
      }
      return;
    }

    if (casesQuery.isLoading || !Number(data.total || 0)) {
      showToast(bilingual(lang, "当前筛选没有可分配的 Issue。", "No Issues match the current filters."), true);
      return;
    }
    win.showPage?.("labeling-new-task", { historyMode: "push" });
  };

  const handleOpenIssue = (issueId: string) => {
    const win = window as unknown as LegacyLabelingBridgeWindow;
    win.selectCaseLabelingIssue?.(issueId).catch((err: unknown) => {
      showToast(err instanceof Error ? err.message : String(err), true);
    });
  };

  const selectedBaselineItems = useMemo(() => {
    const catalog =
      (window as unknown as LegacyLabelingBridgeWindow).state?.baselineCatalog ||
      effectiveConfig?.baselines ||
      [];
    const wanted = new Set(selectedBaselines.length ? selectedBaselines : ["0508"]);
    return catalog.filter((item) => wanted.has(String(item.id || "")));
  }, [effectiveConfig, selectedBaselines]);

  const activeBaselineItems = useMemo(() => {
    const catalog =
      (window as unknown as LegacyLabelingBridgeWindow).state?.baselineCatalog ||
      effectiveConfig?.baselines ||
      [];
    const wanted = new Set(activeBaselineIds);
    return catalog.filter((item) => wanted.has(String(item.id || "")));
  }, [effectiveConfig, activeBaselineIds]);

  const activeIssueId =
    (window as unknown as LegacyLabelingBridgeWindow).state?.caseLabeling?.issueId || "";

  const showSnapshotButton = Boolean(isAdmin && selectedTask?.workset_id);
  const taskProgress = selectedTask?.progress;
  const showTaskProgressStrip = Boolean(selectedTask && taskProgress && Number(taskProgress.total));

  const casesErrorMessage = casesQuery.isError
    ? casesQuery.error instanceof Error
      ? casesQuery.error.message
      : bilingual(lang, "读取 Case 列表失败，请重试。", "Failed to load Cases. Please retry.")
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

  const emptyContent = isInactiveScope ? (
    <div className="empty-state issue-grid-empty case-labeling-inactive-state">
      <h2>
        {selectedBaselineItems.length
          ? selectedBaselineItems.map((b) => b.label || b.id).join("、")
          : bilingual(lang, "当前数据集", "Current dataset")}{" "}
        {bilingual(lang, "尚未切换到 问题标注", "is not yet enabled for Case labeling")}
        <small className="case-labeling-preview-badge">
          {bilingual(lang, "writer / 管理员", "writer / admin")}
        </small>
      </h2>
      <p>
        {bilingual(
          lang,
          "该范围仍在「判错复核」工作台。问题标注只列出已激活数据集，避免把未迁移范围显示成 0 个 Case。",
          "This scope remains in the Review workbench. Case labeling only lists enabled datasets.",
        )}
      </p>
      {activeBaselineItems.length > 0 ? (
        <div className="case-labeling-active-switchers">
          {activeBaselineItems.map((item) => (
            <button
              key={String(item.id)}
              className="button button-primary"
              type="button"
              onClick={() => {
                const win = window as unknown as LegacyLabelingBridgeWindow;
                win.setBaselineScopes?.([String(item.id)]).catch((err: unknown) => {
                  showToast(err instanceof Error ? err.message : String(err), true);
                });
              }}
            >
              {bilingual(lang, "查看", "View")} {item.label || item.id} · {item.count ?? "—"}
            </button>
          ))}
        </div>
      ) : (
        <p>{bilingual(lang, "当前还没有已激活的标注数据集。", "No enabled labeling datasets yet.")}</p>
      )}
    </div>
  ) : casesQuery.isError ? (
    <div className="empty-state issue-grid-empty case-labeling-error-state" role="alert">
      <h2>{bilingual(lang, "Case 列表读取失败", "Failed to load Cases")}</h2>
      <p>{casesErrorMessage}</p>
      <button
        className="button button-quiet"
        type="button"
        onClick={() => void casesQuery.refetch()}
      >
        {bilingual(lang, "重试", "Retry")}
      </button>
    </div>
  ) : casesRefreshFailed ? (
    <div className="no-asset issue-grid-empty" role="status">
      {bilingual(lang, "Case 列表刷新失败，正在自动重试…", "Failed to refresh Cases, retrying…")}
    </div>
  ) : casesQuery.isLoading ? (
    <div className="no-asset issue-grid-empty">
      {bilingual(lang, "正在加载 Case…", "Loading Cases…")}
    </div>
  ) : (
    <div className="empty-state issue-grid-empty">
      <h2>{bilingual(lang, "当前范围没有 Case", "No Cases in current scope")}</h2>
      <p>
        {bilingual(
          lang,
          "请切换已激活的数据集、任务或状态。",
          "Switch to an enabled dataset, task, or status.",
        )}
      </p>
    </div>
  );

  return (
    <div className="ra-case-labeling-gallery-root" data-react-island="labeling">
      <section
        className="review-commandbar case-labeling-command"
        aria-label={bilingual(lang, "标注筛选", "Labeling filters")}
        hidden={isInactiveScope}
      >
        <div className="mobile-filter-bar">
          <button
            className="button button-quiet mobile-filter-toggle"
            type="button"
            aria-expanded={mobileFiltersOpen}
            aria-controls="caseLabelingFilterForm"
            onClick={() => setMobileFiltersOpen((prev) => !prev)}
          >
            <span>{bilingual(lang, "标注筛选", "Filters")}</span>
            <span className="mobile-filter-hint">
              {mobileFiltersOpen
                ? bilingual(lang, "收起条件", "Hide filters")
                : bilingual(lang, "展开条件", "Show filters")}
            </span>
          </button>
        </div>

        <form
          className={`review-filters case-labeling-filters${mobileFiltersOpen ? " is-open" : ""}`}
          id="caseLabelingFilterForm"
          data-mobile-filter-panel="caseLabelingFilters"
          onSubmit={(e) => e.preventDefault()}
        >
          <div className="ra-gallery-field case-labeling-search">
            <span>Issue</span>
            <div className="issue-query-control">
              <input
                id="caseLabelingSearch"
                type="search"
                value={searchDraft}
                onChange={(e) => setSearchDraft(e.target.value)}
                placeholder={bilingual(lang, "Issue ID、场景", "Issue ID, scene")}
                aria-label={bilingual(lang, "搜索 Issue", "Search Issue")}
                autoComplete="off"
              />
              <button
                className={`button button-quiet issue-query-button${filters.issueIds.length > 0 ? " has-issues" : ""}`}
                id="openCaseLabelingIssueQueryButton"
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

          <div className="ra-gallery-field case-labeling-task">
            <span>{bilingual(lang, "标注任务", "Labeling task")}</span>
            <UiSelect
              id="caseLabelingTaskPicker"
              value={filters.taskId}
              options={taskOptions}
              ariaLabel={bilingual(lang, "标注任务", "Labeling task")}
              onChange={(val) =>
                updateFilters((prev) => ({
                  ...prev,
                  taskId: val,
                  author: [],
                  assignee: [],
                  cluster: "",
                  page: 1,
                }))
              }
            />
          </div>

          <div className="ra-gallery-field">
            <span>{bilingual(lang, "结果状态", "Result status")}</span>
            <MultiSelect
              id="caseLabelingStatusPicker"
              values={filters.status}
              options={statusOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部状态", "All states")}
              ariaLabel={bilingual(lang, "结果状态", "Result status")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, status: vals, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field">
            <span>{bilingual(lang, "Issue 标签", "Issue tags")}</span>
            <MultiSelect
              id="caseLabelingIssueTagFilter"
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
                updateFilters((prev) => ({ ...prev, issueTags: vals, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field">
            <span>{bilingual(lang, "标注人", "Labeler")}</span>
            <MultiSelect
              id="caseLabelingAuthorPicker"
              values={filters.author}
              options={authorOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部标注人", "All labelers")}
              ariaLabel={bilingual(lang, "标注人", "Labeler")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, author: vals, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field">
            <span>{bilingual(lang, "任务负责人", "Assignee")}</span>
            <MultiSelect
              id="caseLabelingAssigneePicker"
              values={filters.assignee}
              options={assigneeOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部负责人", "All assignees")}
              ariaLabel={bilingual(lang, "任务负责人", "Assignee")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, assignee: vals, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field">
            <span>GT</span>
            <MultiSelect
              id="caseLabelingGtPicker"
              values={filters.gt}
              options={triageOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部 GT", "All GT")}
              ariaLabel="GT"
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, gt: vals, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field">
            <div className="filter-field-heading">
              <span>{bilingual(lang, "GT 关系", "GT relation")}</span>
              <UiInfoPopover
                id="caseLabelGtInfo"
                ariaLabel={bilingual(lang, "标注状态与 GT 关系说明", "Label state and GT relation help")}
              >
                {bilingual(
                  lang,
                  "比较当前有效标注结论与所选 GT；未形成结论或有分歧的 Case 不计入。GT 缺失只包含已有结论且 GT 为空的 Case。",
                  "Compare the current resolved label with the selected GT. Unresolved or conflicting cases are excluded. GT missing includes resolved cases whose GT is empty.",
                )}
              </UiInfoPopover>
            </div>
            <MultiSelect
              id="caseLabelingGtRelationPicker"
              values={filters.gtRelations}
              options={gtRelationOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部关系", "All relations")}
              ariaLabel={bilingual(lang, "GT 关系筛选", "GT relation filter")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, gtRelations: vals, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field">
            <span>{bilingual(lang, "结果类别", "Result label")}</span>
            <MultiSelect
              id="caseLabelingLabelPicker"
              values={filters.label}
              options={triageOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部类别", "All labels")}
              ariaLabel={bilingual(lang, "结果类别", "Result label")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, label: vals, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field">
            <span>{bilingual(lang, "讨论", "Discussion")}</span>
            <MultiSelect
              id="caseLabelingDiscussionPicker"
              values={filters.commentState}
              options={discussionOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部讨论状态", "All discussions")}
              ariaLabel={bilingual(lang, "讨论", "Discussion")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, commentState: vals, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field">
            <span>{bilingual(lang, "排除", "Exclusion")}</span>
            <MultiSelect
              id="caseLabelingExclusionPicker"
              values={filters.exclusion}
              options={exclusionOptions}
              lang={lang}
              placeholder={bilingual(lang, "全部（含问题排除）", "All cases")}
              ariaLabel={bilingual(lang, "排除", "Exclusion")}
              onChange={(vals) =>
                updateFilters((prev) => ({ ...prev, exclusion: vals, cluster: "", page: 1 }))
              }
            />
          </div>

          <div className="ra-gallery-field filter-target-group">
            <span>{bilingual(lang, "目标集合", "Target cohort")}</span>
            <UiSelect
              id="caseLabelingTargetGroupPicker"
              value={filters.targetGroup}
              options={targetGroupOptions}
              ariaLabel={bilingual(lang, "目标集合", "Target cohort")}
              title={bilingual(
                lang,
                "按当前版本目标集合筛选；抽样优先于低置信度",
                "Filter current version target cohorts; samples take precedence over low confidence",
              )}
              onChange={(val) =>
                updateFilters((prev) => ({ ...prev, targetGroup: val, cluster: "", page: 1 }))
              }
            />
          </div>

          <button
            className="button button-quiet filter-submit"
            id="caseLabelingReset"
            type="button"
            onClick={handleReset}
          >
            {bilingual(lang, "重置", "Reset")}
          </button>
        </form>
      </section>

      <section className="gallery-panel" id="caseLabelingGallery">
        <div className="gallery-heading case-labeling-gallery-heading">
          <div className="case-labeling-heading-copy">
            <h2>{bilingual(lang, "问题图库", "Issue Gallery")}</h2>
            <span className="count-pill" id="caseLabelingCount">
              {isInactiveScope
                ? "0"
                : casesQuery.isLoading || casesRefreshFailed
                  ? "—"
                  : String(data.total || 0)}
            </span>
          </div>
          <div className="gallery-heading-actions">
            <button
              className="button button-quiet"
              id="caseLabelingExportIssues"
              type="button"
              disabled={exportingIssues || isInactiveScope || casesRefreshFailed || !Number(data.total || 0)}
              title={bilingual(
                lang,
                "导出当前筛选下的全部 Issue ID（CSV）",
                "Export all Issue IDs matching the current filters (CSV)",
              )}
              onClick={() => void handleExportIssues()}
            >
              {exportingIssues
                ? bilingual(lang, "导出中…", "Exporting…")
                : bilingual(lang, "导出 Issue", "Export Issues")}
            </button>
            <button
              className="button button-quiet"
              id="caseLabelingExportGt"
              type="button"
              disabled={exportingGt || isInactiveScope || casesRefreshFailed || !isAdmin}
              onClick={(e) => void handleExportGt(e)}
            >
              {bilingual(lang, "导出 GT 更新", "Export GT updates")}
            </button>
            <button
              className="button button-quiet"
              id="caseLabelingCampaignsButton"
              type="button"
              onClick={() => {
                const win = window as unknown as LegacyLabelingBridgeWindow;
                const queryParams: Record<string, string> = {};
                const activeSearch = searchDraft.trim();
                const activeIssueIds = activeSearch ? [] : filters.issueIds;
                if (filters.taskId) queryParams.task = filters.taskId;
                if (filters.targetGroup) queryParams.target_group = filters.targetGroup;
                if (activeSearch) queryParams.q = activeSearch;
                if (activeIssueIds.length) queryParams.issue_ids = activeIssueIds.join(",");
                if (filters.issueTags.length) queryParams.issue_tags = joinFilterList(filters.issueTags);
                if (filters.gtRelations.length) queryParams.gt_relation = joinFilterList(filters.gtRelations);
                if (filters.status.length) queryParams.status = joinFilterList(filters.status);
                if (filters.author.length) queryParams.author = joinFilterList(filters.author);
                if (filters.assignee.length) queryParams.assignee = joinFilterList(filters.assignee);
                if (filters.label.length) queryParams.label = joinFilterList(filters.label);
                if (filters.gt.length) queryParams.gt = joinFilterList(filters.gt);
                if (filters.commentState.length) {
                  queryParams.comment_state = joinFilterList(filters.commentState);
                }
                if (filters.exclusion.length) queryParams.exclusion = joinFilterList(filters.exclusion);
                if (filters.cluster) queryParams.cluster = filters.cluster;
                if (baselinesQuery) queryParams.baselines = baselinesQuery;
                if (typeof win.navigatePage === "function") {
                  win.navigatePage("labeling-summary", { queryParams });
                } else {
                  const qs = new URLSearchParams(queryParams).toString();
                  window.location.assign(
                    `${window.location.pathname.replace(/\/case-labeling\/?$/, "/labeling-summary")}${qs ? `?${qs}` : ""}`,
                  );
                }
              }}
            >
              {bilingual(lang, "标注汇总", "Labeling summary")}
            </button>
            {showSnapshotButton && (
              <button
                className="button button-quiet"
                id="caseLabelingCreateLabelSnapshot"
                type="button"
                disabled={savingSnapshot || isInactiveScope || casesRefreshFailed}
                onClick={() => void handleSaveSnapshot()}
              >
                {bilingual(lang, "保存 Label 快照", "Save Label snapshot")}
              </button>
            )}
            <button
              className="button button-primary"
              id="caseLabelingCreateTask"
              type="button"
              disabled={isInactiveScope || casesRefreshFailed || casesQuery.isLoading || checkingTaskScope}
              onClick={() => void handleCreateTask()}
            >
              {bilingual(lang, "标注任务", "Labeling task")}
            </button>
          </div>
        </div>

        <div
          className="review-cluster-strip case-labeling-progress-strip"
          id="caseLabelingTaskProgress"
          hidden={!showTaskProgressStrip}
        >
          <span className="subheading">{bilingual(lang, "任务进度", "Task progress")}</span>
          <div className="cluster-list" id="caseLabelingTaskProgressList">
            {showTaskProgressStrip && taskProgress && (
              <>
                <span className="cluster-chip">
                  <span>{bilingual(lang, "总计", "Total")}</span>
                  <b>
                    {taskProgress.resolved ?? 0}/{taskProgress.total ?? 0}
                  </b>
                </span>
                {Number(taskProgress.conflict || 0) > 0 && (
                  <span className="cluster-chip">
                    <span>{bilingual(lang, "冲突", "Conflicts")}</span>
                    <b>{taskProgress.conflict}</b>
                  </span>
                )}
                {(taskProgress.assignees || []).map((person) => (
                  <span key={person.name} className="cluster-chip">
                    <span>{person.name}</span>
                    <b>
                      {person.labeled}/{person.total}
                    </b>
                  </span>
                ))}
              </>
            )}
          </div>
        </div>

        <IssueCardGrid
          id="caseLabelingList"
          workspace="labeling"
          items={casesRefreshFailed ? [] : data.items || []}
          lang={lang}
          config={effectiveConfig}
          selectedIssueId={activeIssueId}
          emptyContent={emptyContent}
          onOpenIssue={handleOpenIssue}
        />

        {!isInactiveScope && (
          <Pagination
            page={data.page || filters.page}
            pageSize={filters.pageSize}
            total={casesRefreshFailed ? 0 : data.total || 0}
            lang={lang}
            loading={casesQuery.isFetching}
            showPageUnit
            disableJumpWhenSinglePage
            labelText={
              !casesRefreshFailed && data.total > 0
                ? `${data.page || filters.page} / ${Math.max(1, data.pages || Math.ceil(data.total / filters.pageSize))}`
                : "— / —"
            }
            ariaLabel={bilingual(lang, "标注 Case 分页", "Case labeling pagination")}
            onPageChange={(nextPage) =>
              updateFilters((prev) => ({ ...prev, page: nextPage }))
            }
            onPageSizeChange={(nextSize) =>
              updateFilters((prev) => ({ ...prev, pageSize: nextSize, page: 1 }))
            }
          />
        )}
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
