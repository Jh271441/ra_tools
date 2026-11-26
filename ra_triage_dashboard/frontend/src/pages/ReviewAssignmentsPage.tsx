import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, UiLanguage, withWorkbenchBase } from "../bridge/useWorkbenchBridge";
import { AllocationGroupSetup } from "../components/allocation/AllocationGroupSetup";
import { AllocationLivePreview } from "../components/allocation/AllocationLivePreview";
import { BatchCard } from "../components/allocation/BatchCard";
import { TaskAllocationDialog } from "../components/allocation/TaskAllocationDialog";
import { useAssignmentNaming } from "../components/allocation/useAssignmentNaming";
import {
  AccessUserItem,
  AllocationDraft,
  AllocationPreviewPlan,
  BilingualMessage,
  WorkSplitDetail,
  WorkSplitItem,
  createInitialAllocationDraft,
  formatClassicTime,
  formatVersionDatasetTime,
  groupAllocationSetupError,
  i18nLocaleTag,
  parseBilingualError,
  reviewAssignmentBatchHref,
  reviewAssignmentCanReview,
  reviewAssignmentLifecycleLabel,
  reviewAssignmentModeLabel,
  reviewAssignmentPercent,
  reviewAssignmentSourceHref,
  roleVersionTaskName,
} from "../components/allocation/allocationMath";
import { CASE_PAGE_SIZES, DEFAULT_CASE_PAGE_SIZE, Pagination } from "../components/ui/Pagination";
import { showWorkbenchToast } from "../components/ui/Toast";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

export interface ReviewAssignmentsPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
  isAdmin: boolean;
  username: string;
  verified: boolean;
}

interface ModelRunSummary {
  id: string;
  name: string;
  baseline_prediction_count?: number;
}

interface WorkSplitsResponse {
  items: WorkSplitItem[];
  metrics?: {
    assignment_count?: number;
    completed_count?: number;
    pending_count?: number;
  };
}

interface SavedDraftEnvelope {
  filters: Record<string, string>;
  total: number;
  fromReview?: boolean;
  returnUrl?: string;
  groupSetup?: AllocationDraft;
}

interface CreatedWorkSplitResult {
  split_id?: string;
  total?: number;
  assignment_count?: number;
  reviewers_per_issue?: number;
  overlap_ratio?: number;
  truncated?: boolean;
  assignments?: Array<{
    name?: string;
    count?: number;
    mode?: string;
    requested_count?: number;
    issue_ids?: string[];
  }>;
}

const REVIEW_ALLOCATION_DRAFT_KEY = "manual-review-allocation-draft-v1";
const VALID_LIFECYCLES = ["current", "versions", "manual", "history", "all"] as const;
type LifecycleScope = (typeof VALID_LIFECYCLES)[number];

function readInitialRoute() {
  const params = new URLSearchParams(window.location.search);
  const rawLifecycle = params.get("lifecycle") || "current";
  const lifecycle: LifecycleScope = (VALID_LIFECYCLES as readonly string[]).includes(rawLifecycle)
    ? (rawLifecycle as LifecycleScope)
    : "current";
  const assignedToMe = params.get("assigned_to_me") === "true";
  const batchSearch = String(params.get("batch_search") || "").slice(0, 128);
  const splitId = String(params.get("split") || "").trim();
  const assignee = String(params.get("assignee") || "").trim();
  const rawStatus = params.get("status") || "all";
  const status = rawStatus === "pending" || rawStatus === "completed" ? rawStatus : "all";
  const query = String(params.get("q") || "").trim().slice(0, 128);
  const rawPage = Number(params.get("page"));
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1;
  const rawSize = Number(params.get("page_size"));
  const pageSize = CASE_PAGE_SIZES.includes(rawSize as (typeof CASE_PAGE_SIZES)[number])
    ? rawSize
    : DEFAULT_CASE_PAGE_SIZE;
  return { lifecycle, assignedToMe, batchSearch, splitId, assignee, status, query, page, pageSize };
}

function replaceBatchSearchParam(value: string): void {
  const url = new URL(window.location.href);
  const trimmed = value.trim();
  if (trimmed) url.searchParams.set("batch_search", trimmed);
  else url.searchParams.delete("batch_search");
  window.history.replaceState(
    window.history.state,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}

function buildAssignmentsUrl(opts: {
  lifecycle: LifecycleScope;
  assignedToMe: boolean;
  batchSearch?: string;
  splitId?: string;
  assignee?: string;
  status?: string;
  query?: string;
  page?: number;
  pageSize?: number;
  includeDetailFilters?: boolean;
  taskOnly?: boolean;
  preserveCurrentBaselines?: boolean;
}): string {
  const url = new URL(withWorkbenchBase("/review-assignments"), window.location.origin);
  if (opts.taskOnly) {
    url.searchParams.set("lifecycle", "all");
  } else {
    if (opts.preserveCurrentBaselines !== false && typeof window !== "undefined") {
      const currentBaselines = new URLSearchParams(window.location.search).get("baselines");
      if (currentBaselines) url.searchParams.set("baselines", currentBaselines);
    }
    if (opts.lifecycle) url.searchParams.set("lifecycle", opts.lifecycle);
    if (opts.assignedToMe) url.searchParams.set("assigned_to_me", "true");
    if (opts.batchSearch?.trim()) url.searchParams.set("batch_search", opts.batchSearch.trim());
  }
  if (opts.splitId) {
    url.searchParams.set("split", opts.splitId);
    if (!opts.taskOnly && opts.includeDetailFilters !== false) {
      if (opts.assignee) url.searchParams.set("assignee", opts.assignee);
      if (opts.status === "pending" || opts.status === "completed") {
        url.searchParams.set("status", opts.status);
      }
      if (opts.query) url.searchParams.set("q", opts.query);
      if ((opts.page || 1) > 1) url.searchParams.set("page", String(opts.page));
      if (CASE_PAGE_SIZES.includes(Number(opts.pageSize) as (typeof CASE_PAGE_SIZES)[number])) {
        url.searchParams.set("page_size", String(opts.pageSize));
      }
    }
  }
  return `${url.pathname}${url.search}`;
}

function hasExtraGalleryFilters(filters: Record<string, unknown>): boolean {
  const keys = [
    "search",
    "issue_ids",
    "gt_label",
    "model_label",
    "annotation_author",
    "review_status",
    "label_state",
    "gt_relation",
    "issue_tags",
    "target_group",
    "work_assignee",
    "work_split_id",
    "missing_evidence",
  ];
  const comp = String(filters.comparison || filters.comparison_status || "all").trim();
  const hasCustomComparison = Boolean(comp && !["all", "mismatch", "match"].includes(comp));
  return (
    keys.some((k) => {
      const v = filters[k];
      return Array.isArray(v) ? v.length > 0 : Boolean(String(v || "").trim());
    }) ||
    hasCustomComparison ||
    Boolean(filters.comment_state && filters.comment_state !== "all") ||
    Boolean(filters.exclusion && filters.exclusion !== "all")
  );
}

function formatComparisonScopeLabel(comp: string, lang: UiLanguage): string {
  const clean = String(comp || "").trim();
  if (clean === "none") return bilingual(lang, "仅未预测 (NONE)", "Model NONE only");
  if (clean === "no_gt") return bilingual(lang, "仅无 GT (NO GT)", "NO GT only");
  const tokenMap: Record<string, string> = {
    mismatch: "MISMATCH",
    match: "MATCH",
    no_gt: "NO GT",
    none: "NONE",
  };
  const labels = clean
    .split(",")
    .map((part) => tokenMap[part.trim().toLowerCase()] || part.trim())
    .filter(Boolean);
  const joined = labels.join(lang === "en" ? ", " : "、") || clean;
  return bilingual(lang, `图库筛选 (${joined})`, `Gallery filter (${joined})`);
}

export const ReviewAssignmentsPage: React.FC<ReviewAssignmentsPageProps> = ({
  active,
  lang,
  selectedBaselines,
  isAdmin,
  username,
  verified,
}) => {
  const queryClient = useQueryClient();
  const initial = useMemo(() => readInitialRoute(), []);

  const [lifecycle, setLifecycle] = useState<LifecycleScope>(initial.lifecycle);
  const [assignedToMe, setAssignedToMe] = useState<boolean>(initial.assignedToMe);
  const [batchSearch, setBatchSearch] = useState<string>(initial.batchSearch);
  const [selectedSplitId, setSelectedSplitId] = useState<string>(initial.splitId);
  const [detailAssignee, setDetailAssignee] = useState<string>(initial.assignee);
  const [detailStatus, setDetailStatus] = useState<string>(initial.status);
  const [detailSearchInput, setDetailSearchInput] = useState<string>(initial.query);
  const [detailQuery, setDetailQuery] = useState<string>(initial.query);
  const [detailPage, setDetailPage] = useState<number>(initial.page);
  const [detailPageSize, setDetailPageSize] = useState<number>(initial.pageSize);
  const [rowTransfers, setRowTransfers] = useState<Record<string, string>>({});
  const [savingIssueId, setSavingIssueId] = useState<string>("");

  // Edit task allocation modal
  const [editCampaignId, setEditCampaignId] = useState<string | null>(null);

  // Inline WorkSplit composer state
  const [composerOpen, setComposerOpen] = useState(false);
  const [workflowMode, setWorkflowMode] = useState<"model_review_and_case_label" | "model_review_only">(
    "model_review_and_case_label",
  );
  const [composerRunId, setComposerRunId] = useState("");
  const [composerComparison, setComposerComparison] = useState<string>("all");
  const [composerSeed, setComposerSeed] = useState("");
  const [composerFilters, setComposerFilters] = useState<Record<string, string>>({});
  const [composerTotal, setComposerTotal] = useState<number>(0);
  const [composerTotalLoading, setComposerTotalLoading] = useState(false);
  const [composerFromReview, setComposerFromReview] = useState(false);
  const [composerReturnUrl, setComposerReturnUrl] = useState("");
  const [composerDraft, setComposerDraft] = useState<AllocationDraft>(() =>
    createInitialAllocationDraft(),
  );
  const [composerResetTick, setComposerResetTick] = useState(0);

  // Creation live preview state
  const [creationPlan, setCreationPlan] = useState<AllocationPreviewPlan | null>(null);
  const [creationLastPlan, setCreationLastPlan] = useState<AllocationPreviewPlan | null>(null);
  const [creationError, setCreationError] = useState<BilingualMessage | null>(null);
  const [creationRetry, setCreationRetry] = useState(false);
  const [creationPending, setCreationPending] = useState(false);
  const [creationBusy, setCreationBusy] = useState(false);
  const [creationSubmitted, setCreationSubmitted] = useState(false);
  const [createdResult, setCreatedResult] = useState<CreatedWorkSplitResult | null>(null);

  const previewTimerRef = useRef<number | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);
  const previewRequestIdRef = useRef<string>("");
  const previewSerializedRef = useRef<string>("");
  const detailRef = useRef<HTMLElement | null>(null);
  const pendingDetailScrollRef = useRef<string>("");
  const composerRef = useRef<HTMLElement | null>(null);
  const searchDebounceRef = useRef<number | null>(null);
  const restoredDraftRef = useRef(false);

  const baselineQuery = selectedBaselines.join(",");

  // Sync URL on popstate or active entry
  useEffect(() => {
    if (!active) return;
    const next = readInitialRoute();
    setLifecycle(next.lifecycle);
    setAssignedToMe(next.assignedToMe);
    setBatchSearch(next.batchSearch);
    setSelectedSplitId(next.splitId);
    setDetailAssignee(next.assignee);
    setDetailStatus(next.status);
    setDetailSearchInput(next.query);
    setDetailQuery(next.query);
    setDetailPage(next.page);
    setDetailPageSize(next.pageSize);
  }, [active]);

  useEffect(() => {
    if (!active) return;
    const onPop = () => {
      const next = readInitialRoute();
      setLifecycle(next.lifecycle);
      setAssignedToMe(next.assignedToMe);
      setBatchSearch(next.batchSearch);
      setSelectedSplitId(next.splitId);
      setDetailAssignee(next.assignee);
      setDetailStatus(next.status);
      setDetailSearchInput(next.query);
      setDetailQuery(next.query);
      setDetailPage(next.page);
      setDetailPageSize(next.pageSize);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [active]);

  const pushRoute = useCallback(
    (overrides?: {
      lifecycle?: LifecycleScope;
      assignedToMe?: boolean;
      batchSearch?: string;
      splitId?: string;
      assignee?: string;
      status?: string;
      query?: string;
      page?: number;
      pageSize?: number;
    }) => {
      const url = buildAssignmentsUrl({
        lifecycle: overrides?.lifecycle ?? lifecycle,
        assignedToMe: overrides?.assignedToMe ?? assignedToMe,
        batchSearch: overrides?.batchSearch !== undefined ? overrides.batchSearch : batchSearch,
        splitId: overrides?.splitId !== undefined ? overrides.splitId : selectedSplitId,
        assignee: overrides?.assignee !== undefined ? overrides.assignee : detailAssignee,
        status: overrides?.status !== undefined ? overrides.status : detailStatus,
        query: overrides?.query !== undefined ? overrides.query : detailQuery,
        page: overrides?.page !== undefined ? overrides.page : detailPage,
        pageSize: overrides?.pageSize !== undefined ? overrides.pageSize : detailPageSize,
      });
      window.history.replaceState({ ...(window.history.state || {}), page: "review-assignments" }, "", url);
    },
    [
      lifecycle,
      assignedToMe,
      batchSearch,
      selectedSplitId,
      detailAssignee,
      detailStatus,
      detailQuery,
      detailPage,
      detailPageSize,
    ],
  );

  // Queries: work-splits list, model-runs, access-users, selected detail
  const splitsQuery = useQuery<WorkSplitsResponse>({
    queryKey: ["review-assignments-list", lifecycle, assignedToMe],
    queryFn: ({ signal }) => {
      const apiLifecycle =
        lifecycle === "versions" || lifecycle === "manual" ? "current" : lifecycle;
      const params = new URLSearchParams({
        limit: "100",
        lifecycle: apiLifecycle,
        group_by_version: "true",
        version_only: String(lifecycle === "versions"),
        manual_only: String(lifecycle === "manual"),
      });
      if (assignedToMe) params.set("assigned_to_me", "true");
      return apiRequest<WorkSplitsResponse>(`/api/cases/work-splits?${params.toString()}`, {
        signal,
      });
    },
    enabled: active,
    staleTime: 10_000,
  });

  const runsQuery = useQuery<{ items: ModelRunSummary[]; default_model_run_id?: string }>({
    queryKey: ["review-assignments-runs", baselineQuery],
    queryFn: ({ signal }) => {
      const qs = baselineQuery ? `?baselines=${encodeURIComponent(baselineQuery)}` : "";
      return apiRequest<{ items: ModelRunSummary[]; default_model_run_id?: string }>(
        `/api/model-runs${qs}`,
        { signal },
      );
    },
    enabled: active,
    staleTime: 30_000,
  });

  const usersQuery = useQuery<{ items: AccessUserItem[] }>({
    queryKey: ["access-users"],
    queryFn: ({ signal }) => apiRequest<{ items: AccessUserItem[] }>("/api/access-users", { signal }),
    enabled: active && isAdmin,
    staleTime: 60_000,
  });

  const detailQueryRes = useQuery<WorkSplitDetail>({
    queryKey: [
      "review-assignment-detail",
      selectedSplitId,
      detailAssignee,
      detailStatus,
      detailQuery,
      detailPage,
      detailPageSize,
    ],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        page: String(detailPage),
        page_size: String(detailPageSize),
        status: detailStatus || "all",
      });
      if (detailAssignee) params.set("assignee", detailAssignee);
      if (detailQuery) params.set("q", detailQuery);
      return apiRequest<WorkSplitDetail>(
        `/api/cases/work-splits/${encodeURIComponent(selectedSplitId)}?${params.toString()}`,
        { signal },
      );
    },
    enabled: active && Boolean(selectedSplitId),
    staleTime: 5_000,
  });

  // Reset inline row transfer drafts when detail payload changes, and scroll once loaded
  useEffect(() => {
    setRowTransfers({});
    if (
      detailQueryRes.data?.split_id &&
      pendingDetailScrollRef.current === detailQueryRes.data.split_id
    ) {
      pendingDetailScrollRef.current = "";
      detailRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    }
  }, [detailQueryRes.data]);

  const orderedRuns = useMemo(() => {
    const runs = runsQuery.data?.items || [];
    const matching = runs.filter((r) => Number(r.baseline_prediction_count || 0) > 0);
    return matching.length
      ? [...matching, ...runs.filter((r) => !matching.includes(r))]
      : runs;
  }, [runsQuery.data]);

  const runNameLookup = useCallback(
    (runId?: string) => {
      const value = String(runId || "").trim();
      if (!value) return bilingual(lang, "未绑定 Model Run", "No Model Run");
      const found = orderedRuns.find((r) => String(r.id) === value);
      return found?.name || value;
    },
    [orderedRuns, lang],
  );

  // Baseline labels from classic config if available
  const datasetLabels = useMemo(() => {
    const ids = (composerFilters.baselines || baselineQuery)
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const win = window as unknown as {
      assignmentBaselineLabels?: (ids: string[]) => string[];
    };
    if (typeof win.assignmentBaselineLabels === "function") {
      return win.assignmentBaselineLabels(ids);
    }
    return ids;
  }, [composerFilters.baselines, baselineQuery]);

  // Naming hook for inline composer
  const namingContext = useMemo(() => {
    const activeGroups = composerDraft.groups.filter((g) => (g.coverage_percent ?? 0) > 0);
    const reviewersPerIssue = Math.max(1, activeGroups.length);
    const coverage = activeGroups
      .slice(1)
      .reduce((sum, g) => sum + (g.coverage_percent ?? 0), 0);
    const overlapRatio = Math.min(1, coverage / 100);
    const assignees = new Set(
      composerDraft.groups.flatMap((g) => g.members.map((m) => m.name).filter(Boolean)),
    );
    const baselineIds = (composerFilters.baselines || baselineQuery)
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const run = orderedRuns.find((r) => String(r.id) === composerRunId);
    return {
      assignmentKind: "model_review" as const,
      baselineIds,
      datasetLabels,
      caseCount: composerTotal,
      reviewersPerIssue,
      overlapRatio,
      memberCount: assignees.size,
      workflowMode,
      modelRunId: composerRunId,
      runName: String(run?.name || composerRunId),
      comparison: composerComparison,
    };
  }, [
    composerDraft.groups,
    composerFilters.baselines,
    baselineQuery,
    datasetLabels,
    composerTotal,
    workflowMode,
    composerRunId,
    orderedRuns,
    composerComparison,
  ]);

  const naming = useAssignmentNaming({
    enabled: active && composerOpen && isAdmin,
    isAdmin,
    context: namingContext,
    lang,
    resetKey: composerResetTick,
  });

  // Fetch scope total when composer run/comparison/baselines change
  const refreshScopeCount = useCallback(
    async (
      runId: string,
      comparison: string,
      baseFilters: Record<string, string>,
      keepGallery: boolean,
      notifyEmpty = false,
    ) => {
      const effectiveComparison = String(comparison || "all").trim() || "all";
      const effectiveBaselines =
        keepGallery && baseFilters.baselines ? baseFilters.baselines : baselineQuery;
      const nextFilters: Record<string, string> = keepGallery
        ? {
            ...baseFilters,
            model_run_id: runId,
            baselines: effectiveBaselines,
            comparison: effectiveComparison,
            comparison_status: effectiveComparison,
          }
        : {
            model_run_id: runId,
            baselines: baselineQuery,
            comparison: effectiveComparison,
            comparison_status: effectiveComparison,
            comment_state: "all",
            exclusion: "all",
          };
      setComposerFilters(nextFilters);
      if (!runId) {
        setComposerTotal(0);
        return;
      }
      setComposerTotalLoading(true);
      try {
        const params = new URLSearchParams({
          ...nextFilters,
          page: "1",
          page_size: "1",
          include_thumbnail: "false",
        });
        const res = await apiRequest<{ total?: number }>(`/api/cases?${params.toString()}`);
        const count = Number(res.total || 0);
        setComposerTotal(count);
        if (notifyEmpty && !count) {
          showWorkbenchToast(
            bilingual(
              lang,
              "原筛选范围当前没有 Issue，请返回调整。",
              "No Issues currently match the original filter scope. Go back to adjust.",
            ),
            true,
          );
        }
      } catch (error) {
        setComposerTotal(0);
        showWorkbenchToast((error as Error).message, true);
      } finally {
        setComposerTotalLoading(false);
      }
    },
    [baselineQuery, lang],
  );

  // Restore draft from sessionStorage if navigated from Review Gallery's "按筛选分配"
  useEffect(() => {
    if (!active || !isAdmin || restoredDraftRef.current || composerOpen) return;
    let saved: SavedDraftEnvelope | null = null;
    try {
      saved = JSON.parse(sessionStorage.getItem(REVIEW_ALLOCATION_DRAFT_KEY) || "null");
    } catch {
      saved = null;
    }
    if (!saved?.filters?.model_run_id) return;
    restoredDraftRef.current = true;
    const preservedComp =
      String(saved.filters.comparison || saved.filters.comparison_status || "all").trim() ||
      "all";
    setComposerRunId(saved.filters.model_run_id);
    setComposerComparison(preservedComp);
    setComposerFromReview(Boolean(saved.fromReview));
    setComposerReturnUrl(saved.returnUrl || "");
    setComposerDraft(saved.groupSetup || createInitialAllocationDraft());
    setComposerOpen(true);
    setComposerResetTick((n) => n + 1);
    void refreshScopeCount(
      saved.filters.model_run_id,
      preservedComp,
      saved.filters,
      true,
      true,
    );
  }, [active, isAdmin, composerOpen, refreshScopeCount]);

  // Live preview for inline composer
  const creationBody = useMemo(() => {
    const body: Record<string, unknown> = {
      groups: composerDraft.groups,
      cross_groups: composerDraft.pairing_mode === "custom" ? composerDraft.cross_groups : [],
      pairing_mode: composerDraft.pairing_mode === "paired" ? "paired" : "orthogonal",
      filters: composerFilters,
      workflow_mode: workflowMode,
    };
    const trimmedName = naming.name.trim();
    const trimmedSeed = composerSeed.trim();
    if (trimmedName) body.name = trimmedName;
    if (trimmedSeed) body.seed = Number(trimmedSeed);
    return body;
  }, [composerDraft, composerFilters, workflowMode, naming.name, composerSeed]);

  const cancelCreationPreview = useCallback(() => {
    if (previewTimerRef.current) {
      window.clearTimeout(previewTimerRef.current);
      previewTimerRef.current = null;
    }
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
  }, []);

  const triggerCreationPreview = useCallback(
    (force = false, immediate = false) => {
      if (!composerOpen || !isAdmin || creationBusy || creationSubmitted) return;
      const serialized = JSON.stringify(creationBody);
      if (!force && serialized === previewSerializedRef.current) return;
      cancelCreationPreview();
      previewSerializedRef.current = serialized;
      const seedVal = creationBody.seed as number | undefined;
      const setupErr =
        groupAllocationSetupError(composerDraft) ||
        (seedVal !== undefined && !Number.isSafeInteger(seedVal)
          ? { zh: "种子必须为整数。", en: "Seed must be an integer." }
          : null);
      setCreationPlan(null);
      setCreationRetry(false);
      if (setupErr) {
        setCreationError(setupErr);
        setCreationPending(false);
        return;
      }
      setCreationError(null);
      setCreationPending(true);
      const reqId =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `ws-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      previewRequestIdRef.current = reqId;
      const runFetch = async () => {
        const controller = new AbortController();
        previewAbortRef.current = controller;
        const timeout = window.setTimeout(() => controller.abort(), 20000);
        try {
          const result = await apiRequest<{ preview: AllocationPreviewPlan }>(
            "/api/cases/work-split",
            {
              method: "POST",
              signal: controller.signal,
              body: { ...creationBody, request_id: reqId, preview_only: true },
            },
          );
          if (previewRequestIdRef.current !== reqId) return;
          setCreationPlan(result.preview);
          setCreationLastPlan(result.preview);
          setCreationPending(false);
        } catch (error) {
          if (previewRequestIdRef.current !== reqId) return;
          setCreationError(
            parseBilingualError(
              error,
              "暂时无法计算预览，请重试。",
              "The preview could not be calculated. Try again.",
            ),
          );
          setCreationRetry(true);
          setCreationLastPlan(null);
          setCreationPending(false);
        } finally {
          window.clearTimeout(timeout);
        }
      };
      if (immediate) {
        void runFetch();
      } else {
        previewTimerRef.current = window.setTimeout(() => {
          previewTimerRef.current = null;
          void runFetch();
        }, 120);
      }
    },
    [
      composerOpen,
      isAdmin,
      creationBusy,
      creationSubmitted,
      creationBody,
      composerDraft,
      cancelCreationPreview,
    ],
  );

  useEffect(() => {
    if (!composerOpen || !isAdmin) return;
    triggerCreationPreview(false, false);
    return () => cancelCreationPreview();
  }, [composerOpen, isAdmin, creationBody]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleOpenNewTask = async () => {
    if (!isAdmin) {
      showWorkbenchToast(bilingual(lang, "仅管理员可创建复核任务。", "Only admins can create allocations."), true);
      return;
    }
    const matching = orderedRuns.filter((r) => Number(r.baseline_prediction_count || 0) > 0);
    const defaultId = runsQuery.data?.default_model_run_id || "";
    const chosen =
      (composerRunId && orderedRuns.some((r) => r.id === composerRunId) ? composerRunId : "") ||
      (defaultId && matching.some((r) => r.id === defaultId) ? defaultId : "") ||
      matching[0]?.id ||
      orderedRuns[0]?.id ||
      "";
    if (!chosen) {
      showWorkbenchToast(
        bilingual(
          lang,
          "当前数据集暂无 Model Run，请先切换数据集或上传模型预测 Run。",
          "No Model Run is available for the selected dataset.",
        ),
        true,
      );
      return;
    }
    setWorkflowMode("model_review_and_case_label");
    setComposerRunId(chosen);
    setComposerComparison("all");
    setComposerSeed("");
    setComposerFromReview(false);
    setComposerReturnUrl("");
    setComposerDraft(createInitialAllocationDraft());
    setCreationSubmitted(false);
    setCreatedResult(null);
    setCreationPlan(null);
    setCreationLastPlan(null);
    setCreationError(null);
    previewSerializedRef.current = "";
    setComposerOpen(true);
    setComposerResetTick((n) => n + 1);
    await refreshScopeCount(chosen, "all", {}, false);
    composerRef.current?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  };

  const handleCancelComposer = () => {
    cancelCreationPreview();
    setComposerOpen(false);
    setCreatedResult(null);
    try {
      sessionStorage.removeItem(REVIEW_ALLOCATION_DRAFT_KEY);
    } catch {
      /* ignore */
    }
  };

  const handleCreateWorkSplit = async () => {
    if (!isAdmin || !creationPlan || creationBusy || creationSubmitted) return;
    setCreationBusy(true);
    try {
      const result = await apiRequest<CreatedWorkSplitResult>("/api/cases/work-split", {
        method: "POST",
        body: {
          ...creationBody,
          request_id: previewRequestIdRef.current,
          preview_token: creationPlan.preview_token,
        },
      });
      setCreatedResult(result);
      setCreationSubmitted(true);
      try {
        sessionStorage.removeItem(REVIEW_ALLOCATION_DRAFT_KEY);
      } catch {
        /* ignore */
      }
      if (lifecycle === "versions" || lifecycle === "history") {
        setLifecycle("current");
        pushRoute({ lifecycle: "current" });
      }
      void queryClient.invalidateQueries({ queryKey: ["review-assignments-list"] });
      showWorkbenchToast(bilingual(lang, "复核任务分配已保存。", "Work split saved."));
    } catch (error) {
      const err = error as { status?: number };
      if (err.status === 409) {
        setCreationPlan(null);
        setCreationRetry(true);
        setCreationError(
          parseBilingualError(
            error,
            "暂时无法计算预览，请重试。",
            "The preview could not be calculated. Try again.",
          ),
        );
      }
      const msg = parseBilingualError(
        error,
        "无法预览分配，请检查任务配置。",
        "Unable to plan the allocation. Check the task settings.",
      );
      showWorkbenchToast(bilingual(lang, msg.zh, msg.en), true);
    } finally {
      setCreationBusy(false);
    }
  };

  const copyShareUrl = useCallback(
    async (splitId = selectedSplitId, taskOnly = false) => {
      const rel = buildAssignmentsUrl({
        lifecycle,
        assignedToMe,
        batchSearch: taskOnly ? "" : batchSearch,
        splitId,
        assignee: detailAssignee,
        status: detailStatus,
        query: detailQuery,
        page: detailPage,
        pageSize: detailPageSize,
        includeDetailFilters: !taskOnly,
        taskOnly,
        preserveCurrentBaselines: !taskOnly,
      });
      const fullUrl = new URL(rel, window.location.origin).href;
      if (navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(fullUrl);
          showWorkbenchToast(bilingual(lang, "任务分配链接已复制。", "Assignment link copied."));
          return;
        } catch {
          /* fallback below */
        }
      }
      window.prompt(bilingual(lang, "请复制任务分配链接：", "Copy the assignment link:"), fullUrl);
    },
    [
      selectedSplitId,
      lifecycle,
      assignedToMe,
      batchSearch,
      detailAssignee,
      detailStatus,
      detailQuery,
      detailPage,
      detailPageSize,
      lang,
    ],
  );

  const handleGoReview = () => {
    if (composerOpen && composerFilters.model_run_id) {
      window.location.assign(composerReturnUrl || reviewAssignmentSourceHref(composerFilters));
      return;
    }
    const preferredRun =
      orderedRuns.find((r) => Number(r.baseline_prediction_count || 0) > 0)?.id ||
      orderedRuns[0]?.id ||
      "";
    const win = window as unknown as {
      navigatePage?: (page: string, opts?: Record<string, unknown>) => void;
    };
    if (typeof win.navigatePage === "function") {
      win.navigatePage("review", preferredRun ? { runId: preferredRun } : {});
    } else {
      window.location.assign(
        withWorkbenchBase(preferredRun ? `/review?run=${encodeURIComponent(preferredRun)}` : "/review"),
      );
    }
  };

  const handleOpenDetail = (splitId: string) => {
    pendingDetailScrollRef.current = splitId;
    setSelectedSplitId(splitId);
    setDetailPage(1);
    setDetailAssignee("");
    setDetailStatus("all");
    setDetailSearchInput("");
    setDetailQuery("");
    pushRoute({
      splitId,
      assignee: "",
      status: "all",
      query: "",
      page: 1,
    });
    if (detailQueryRes.data?.split_id === splitId) {
      pendingDetailScrollRef.current = "";
      window.setTimeout(() => {
        detailRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
      }, 0);
    }
  };

  const handleCloseDetail = () => {
    setSelectedSplitId("");
    pushRoute({ splitId: "" });
  };

  const handleSaveTransfer = async (issueId: string, originalAssignee: string) => {
    if (!isAdmin || !detailQueryRes.data?.split_id) return;
    const nextAssignee = rowTransfers[issueId];
    if (!nextAssignee || nextAssignee === originalAssignee) return;
    setSavingIssueId(issueId);
    try {
      await apiRequest(
        `/api/cases/work-splits/${encodeURIComponent(detailQueryRes.data.split_id)}/assignments/${encodeURIComponent(issueId)}`,
        {
          method: "PATCH",
          body: { assignee: nextAssignee },
        },
      );
      showWorkbenchToast(
        bilingual(
          lang,
          `${issueId} 已转派给 ${nextAssignee}。`,
          `${issueId} transferred to ${nextAssignee}.`,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ["review-assignments-list"] });
      void queryClient.invalidateQueries({ queryKey: ["review-assignment-detail"] });
    } catch (error) {
      showWorkbenchToast((error as Error).message, true);
    } finally {
      setSavingIssueId("");
    }
  };

  const splits = splitsQuery.data?.items || [];
  const metrics = splitsQuery.data?.metrics || {};
  const activeCount = splits.filter((item) => item.is_current).length;
  const totalAssignments =
    metrics.assignment_count ??
    splits.reduce((sum, s) => sum + Number(s.assignment_count || 0), 0);
  const totalCompleted =
    metrics.completed_count ??
    splits.reduce((sum, s) => sum + Number(s.completed_count || 0), 0);
  const totalPending =
    metrics.pending_count ??
    splits.reduce((sum, s) => sum + Number(s.pending_count || 0), 0);

  const lifecycleOptions: UiSelectOption[] = [
    { value: "current", label: bilingual(lang, "全部进行中", "All active") },
    { value: "versions", label: bilingual(lang, "自动任务", "Auto tasks") },
    { value: "manual", label: bilingual(lang, "手动任务", "Manual tasks") },
    { value: "history", label: bilingual(lang, "历史任务", "Historical tasks") },
    { value: "all", label: bilingual(lang, "全部任务", "All tasks") },
  ];

  const workflowOptions: UiSelectOption[] = [
    {
      value: "model_review_and_case_label",
      label: bilingual(
        lang,
        "联合复核任务（判错复核 + 问题标注）",
        "Combined review (Model review + Case labeling)",
      ),
    },
    {
      value: "model_review_only",
      label: bilingual(lang, "独立判错复核任务（仅判错复核）", "Model review only"),
    },
  ];

  const runOptions: UiSelectOption[] = orderedRuns.length
    ? orderedRuns.map((run) => ({
        value: run.id,
        label: `${run.name} · ${Number(run.baseline_prediction_count || 0)} ${bilingual(lang, "例", "cases")}`,
      }))
    : [
        {
          value: "",
          label: bilingual(lang, "当前数据集暂无 Model Run", "No Model Run in this dataset"),
        },
      ];

  const comparisonOptions: UiSelectOption[] = useMemo(() => {
    const base: UiSelectOption[] = [
      { value: "all", label: bilingual(lang, "全部 Case", "All Cases") },
      { value: "mismatch", label: bilingual(lang, "仅模型判错 (MISMATCH)", "Model MISMATCH only") },
      { value: "match", label: bilingual(lang, "仅模型判对 (MATCH)", "Model MATCH only") },
    ];
    if (
      composerComparison &&
      !base.some((option) => option.value === composerComparison)
    ) {
      base.push({
        value: composerComparison,
        label: formatComparisonScopeLabel(composerComparison, lang),
      });
    }
    return base;
  }, [composerComparison, lang]);

  const scopeCountText = useMemo(() => {
    if (!composerRunId) return bilingual(lang, "请先选择 Run", "Select a Run");
    if (composerTotalLoading) return bilingual(lang, "统计中…", "Counting…");
    const formatted = new Intl.NumberFormat(i18nLocaleTag(lang)).format(Math.max(0, composerTotal));
    return hasExtraGalleryFilters(composerFilters)
      ? bilingual(lang, `图库筛选 · ${formatted} 个 Case`, `Gallery · ${formatted} cases`)
      : bilingual(lang, `${formatted} 个 Case`, `${formatted} cases`);
  }, [composerRunId, composerTotalLoading, composerTotal, composerFilters, lang]);

  const shownCreationPlan = creationPlan || (!creationRetry ? creationLastPlan : null);
  const creationIsPending = Boolean(creationPending && !creationPlan && !creationError);

  const detail = detailQueryRes.data;
  const detailCanReview = reviewAssignmentCanReview(detail);
  const detailAssigneeOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "全部负责人", "All assignees") },
      ...(detail?.members || []).map((m) => ({
        value: m.username,
        label: `${m.username} · ${m.assigned_count || 0}`,
      })),
    ],
    [detail?.members, lang],
  );
  const detailStatusOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "all", label: bilingual(lang, "全部任务", "All tasks") },
      { value: "pending", label: bilingual(lang, "待处理", "Pending") },
      { value: "completed", label: bilingual(lang, "已完成", "Completed") },
    ],
    [lang],
  );

  const accessUsers = usersQuery.data?.items || [];
  const personOptionsFor = (selected: string): UiSelectOption[] => {
    const opts = accessUsers
      .map((u) => ({
        value: String(u.username || "").trim(),
        label: `${u.username}${u.role === "admin" ? bilingual(lang, " · 管理员", " · admin") : ""}`,
      }))
      .filter((o) => o.value);
    if (selected && !opts.some((o) => o.value === selected)) {
      opts.unshift({
        value: selected,
        label:
          accessUsers.length && !usersQuery.isFetching
            ? `${selected} · ${bilingual(lang, "已移除账号", "removed user")}`
            : selected,
      });
    }
    return opts;
  };

  const detailTotalRows =
    detail?.filtered_count ??
    detail?.total_filtered ??
    (detail?.page_count ? detail.page_count * detailPageSize : detail?.items?.length || 0);

  return (
    <div className="ra-review-assignments-root" data-react-island="review-assignments">
      <section
        className="review-assignment-metrics"
        id="reviewAssignmentMetrics"
        aria-label={bilingual(lang, "任务分配概览", "Review assignment summary")}
      >
        <article className="review-assignment-metric">
          <small>{bilingual(lang, "任务", "Tasks")}</small>
          <strong>{splits.length}</strong>
          <span>
            {bilingual(lang, `${activeCount} 个当前任务`, `${activeCount} current tasks`)}
          </span>
        </article>
        <article className="review-assignment-metric">
          <small>{bilingual(lang, "任务总量", "Assigned tasks")}</small>
          <strong>{totalAssignments}</strong>
          <span>
            {assignedToMe
              ? bilingual(lang, "仅统计当前账号", "Current user only")
              : bilingual(lang, "按负责人任务计数", "Assignments by owner")}
          </span>
        </article>
        <article className="review-assignment-metric">
          <small>{bilingual(lang, "已完成", "Completed")}</small>
          <strong>{totalCompleted}</strong>
          <span>
            {bilingual(lang, "联合任务需两部分均完成", "Combined tasks require both parts")}
          </span>
        </article>
        <article className="review-assignment-metric">
          <small>{bilingual(lang, "待处理", "Pending")}</small>
          <strong>{totalPending}</strong>
          <span>
            {lifecycle === "history"
              ? bilingual(lang, "历史未完成，只读", "Historical unfinished; read-only")
              : bilingual(lang, "当前范围内未完成", "Unfinished in this scope")}
          </span>
        </article>
      </section>

      <section className="review-assignments-header page-card assignment-composer">
        <div className="review-assignments-header-main">
          <div>
            <h2 id="reviewAssignmentsHeading">
              {isAdmin
                ? bilingual(lang, "分配配置", "Assignment setup")
                : bilingual(lang, "任务分配", "Review assignments")}
            </h2>
          </div>
          <div className="review-assignments-header-actions">
            <button
              className="button button-primary"
              id="reviewAssignmentsNewTask"
              type="button"
              hidden={!isAdmin}
              onClick={() => void handleOpenNewTask()}
            >
              {bilingual(lang, "+ 新建分配", "+ New allocation")}
            </button>
            <button
              className="button button-quiet"
              id="reviewAssignmentsGoReview"
              type="button"
              onClick={handleGoReview}
            >
              {bilingual(lang, "从图库筛选", "Filter in gallery")}
            </button>
            <button
              className="button button-quiet"
              id="reviewAssignmentsShare"
              type="button"
              onClick={() => void copyShareUrl(selectedSplitId, false)}
            >
              {bilingual(lang, "复制链接", "Copy link")}
            </button>
            <button
              className="button button-quiet"
              id="reviewAssignmentsRefresh"
              type="button"
              onClick={() => {
                void queryClient.invalidateQueries({ queryKey: ["review-assignments-list"] });
                if (selectedSplitId) {
                  void queryClient.invalidateQueries({ queryKey: ["review-assignment-detail"] });
                }
              }}
            >
              {bilingual(lang, "刷新", "Refresh")}
            </button>
          </div>
        </div>

        <section
          ref={composerRef}
          className="work-split-inline"
          id="workSplitPanel"
          hidden={!composerOpen || !isAdmin}
        >
          {composerOpen && isAdmin && (
            <div className="work-split-inline-body">
              <div className="assignment-config-fields work-split-config-fields">
                <div className="work-split-seed work-split-workflow-mode ra-assign-field">
                  <span>{bilingual(lang, "任务类型", "Task type")}</span>
                  <UiSelect
                    id="workSplitWorkflowMode"
                    value={workflowMode}
                    options={workflowOptions}
                    ariaLabel={bilingual(lang, "任务类型", "Task type")}
                    onChange={(val) =>
                      setWorkflowMode(
                        val === "model_review_only"
                          ? "model_review_only"
                          : "model_review_and_case_label",
                      )
                    }
                  />
                </div>

                <div className="work-split-seed work-split-model-run ra-assign-field">
                  <span>{bilingual(lang, "模型 Run", "Model run")}</span>
                  <UiSelect
                    id="workSplitModelRun"
                    value={composerRunId}
                    options={runOptions}
                    disabled={!orderedRuns.length}
                    ariaLabel={bilingual(lang, "模型 Run", "Model run")}
                    onChange={(val) => {
                      setComposerRunId(val);
                      void refreshScopeCount(val, composerComparison, composerFilters, composerFromReview);
                    }}
                  />
                </div>

                <div className="work-split-seed work-split-comparison ra-assign-field">
                  <span className="work-split-scope-heading">
                    <span>{bilingual(lang, "筛选范围", "Case scope")}</span>
                    <small className="work-split-scope-count" aria-live="polite">
                      {scopeCountText}
                    </small>
                  </span>
                  <UiSelect
                    id="workSplitComparison"
                    value={composerComparison}
                    options={comparisonOptions}
                    ariaLabel={bilingual(lang, "筛选范围", "Case scope")}
                    onChange={(val) => {
                      const nextComp = String(val || "all").trim() || "all";
                      setComposerComparison(nextComp);
                      void refreshScopeCount(composerRunId, nextComp, composerFilters, composerFromReview);
                    }}
                  />
                </div>

                <label className="work-split-seed work-split-name">
                  <span>{bilingual(lang, "实验名称", "Experiment name")}</span>
                  <span className="intent-experiment-name-control">
                    <input
                      id="workSplitName"
                      type="text"
                      maxLength={80}
                      placeholder={bilingual(
                        lang,
                        "自动生成实验名称",
                        "Generated from the experiment configuration",
                      )}
                      autoComplete="off"
                      value={naming.name}
                      onChange={(e) => naming.setManualName(e.target.value)}
                    />
                    <small
                      className="assignment-name-source"
                      data-status={naming.status}
                      data-source={naming.source}
                      title={naming.statusTitle}
                      aria-live="polite"
                    >
                      {naming.statusText}
                    </small>
                    <button
                      className="assignment-name-refresh"
                      type="button"
                      disabled={!naming.canRefresh}
                      data-loading={String(naming.status === "loading")}
                      aria-busy={naming.status === "loading"}
                      aria-label={naming.refreshLabel}
                      title={naming.refreshLabel}
                      onClick={naming.refreshName}
                    >
                      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                        <path d="M20 7v5h-5M4 17v-5h5M6.1 7a7 7 0 0 1 11.6-1L20 9M4 15l2.3 3A7 7 0 0 0 17.9 17" />
                      </svg>
                    </button>
                  </span>
                </label>
              </div>

              <div className="allocation-creation-layout">
                <AllocationGroupSetup
                  id="workSplitGroupSetup"
                  draft={composerDraft}
                  users={accessUsers}
                  lang={lang}
                  editable={!creationBusy}
                  caseCount={composerTotal}
                  quotaBasis="total"
                  onChange={(next, meta) => {
                    setComposerDraft(next);
                    if (meta.immediate) {
                      window.setTimeout(() => triggerCreationPreview(false, true), 0);
                    }
                  }}
                  onFlush={() => triggerCreationPreview(false, true)}
                />

                <section className="allocation-creation-preview">
                  <div className="allocation-preview-heading">
                    <h3>{bilingual(lang, "实时预览", "Live preview")}</h3>
                    <span
                      className="allocation-preview-pending"
                      aria-live="polite"
                      hidden={!(creationIsPending && shownCreationPlan)}
                    >
                      <i className="allocation-preview-spinner" aria-hidden="true" />
                      <span>{bilingual(lang, "更新中…", "Updating…")}</span>
                    </span>
                  </div>
                  <p
                    className={`dialog-copy${creationError && creationRetry ? " task-allocation-error" : ""}`}
                    role="status"
                  >
                    {creationError
                      ? bilingual(lang, creationError.zh, creationError.en)
                      : creationIsPending && !shownCreationPlan
                        ? bilingual(lang, "正在计算预览…", "Calculating preview…")
                        : ""}
                  </p>
                  <button
                    className="button button-quiet"
                    id="workSplitRetryPreview"
                    type="button"
                    hidden={!creationRetry}
                    onClick={() => triggerCreationPreview(true, true)}
                  >
                    {bilingual(lang, "重新计算", "Recalculate")}
                  </button>
                  <div
                    id="workSplitPlanPreview"
                    className={`allocation-live-content${creationIsPending && shownCreationPlan ? " is-preview-updating" : ""}${creationError && shownCreationPlan ? " is-preview-stale" : ""}`}
                    hidden={!shownCreationPlan}
                  >
                    {shownCreationPlan && (
                      <AllocationLivePreview
                        plan={shownCreationPlan}
                        configuredGroups={composerDraft.groups}
                        lang={lang}
                      />
                    )}
                  </div>
                </section>
              </div>

              <div className="work-split-toolbar assignment-footer-row">
                <label className="work-split-seed">
                  <span>{bilingual(lang, "随机种子（可选）", "Random seed (optional)")}</span>
                  <input
                    id="workSplitSeed"
                    type="number"
                    inputMode="numeric"
                    placeholder={bilingual(lang, "留空则每次不同", "Leave blank to randomize")}
                    value={composerSeed}
                    onChange={(e) => setComposerSeed(e.target.value)}
                  />
                </label>
                <div className="dialog-actions">
                  <button
                    className="button button-quiet"
                    id="workSplitResetDraft"
                    type="button"
                    onClick={handleCancelComposer}
                  >
                    {bilingual(lang, "取消", "Cancel")}
                  </button>
                  <button
                    className="button button-primary"
                    id="workSplitGenerate"
                    type="button"
                    disabled={!creationPlan || creationBusy || creationSubmitted}
                    onClick={() => void handleCreateWorkSplit()}
                  >
                    {creationBusy
                      ? bilingual(lang, "正在创建…", "Creating…")
                      : bilingual(lang, "创建分配", "Create allocation")}
                  </button>
                </div>
              </div>

              {createdResult?.assignments?.length ? (
                <div className="work-split-results" id="workSplitResults" aria-live="polite">
                  <div className="work-split-results-heading">
                    <strong>{bilingual(lang, "复核任务分配已完成", "Work split created")}</strong>
                    <span>
                      {bilingual(
                        lang,
                        `共 ${createdResult.total || 0} 个 Case · ${createdResult.split_id || ""} · ${createdResult.assignment_count || createdResult.total || 0} 条任务`,
                        `${createdResult.total || 0} Cases · ${createdResult.split_id || ""} · ${createdResult.assignment_count || createdResult.total || 0} tasks`,
                      )}
                    </span>
                    {createdResult.split_id && (
                      <button
                        className="button button-quiet"
                        type="button"
                        onClick={() => handleOpenDetail(createdResult.split_id!)}
                      >
                        {bilingual(lang, "打开任务管理", "Open assignment manager")}
                      </button>
                    )}
                  </div>
                  <div className="work-split-card-grid">
                    {createdResult.assignments.map((a, idx) => (
                      <article key={`${a.name}-${idx}`} className="work-split-card">
                        <header>
                          <strong>{a.name || "—"}</strong>
                          <span>{bilingual(lang, `${a.count || 0} 条`, `${a.count || 0} items`)}</span>
                        </header>
                        <textarea
                          className="work-split-ids"
                          readOnly
                          rows={4}
                          value={(a.issue_ids || []).join("\n")}
                        />
                      </article>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </section>
      </section>

      <section className="page-card review-assignment-list-card assignment-history">
        {(() => {
          const batchSearchTerms = batchSearch.trim().toLowerCase().split(/\s+/).filter(Boolean);
          const matches = (item: WorkSplitItem) => {
            const cohort =
              item.role_cohort === "sampling"
                ? "抽样集 sampling"
                : item.role_cohort === "low"
                  ? "低置信集 low confidence"
                  : "";
            const fields = [
              item.release_family,
              item.campaign_name,
              roleVersionTaskName(item, lang, runNameLookup),
              runNameLookup(item.model_run_id),
              item.split_id,
              item.source_split_id,
              ...(item.baseline_ids || []),
              item.appendable && !item.role_cohort ? "版本联合复核 version combined review" : "",
              cohort,
            ];
            const haystack = fields.filter(Boolean).join(" ").toLowerCase();
            return batchSearchTerms.every((term) => haystack.includes(term));
          };
          const filteredSplits = splits.filter(matches);
          const listStatusText = !splits.length
            ? ""
            : batchSearchTerms.length
              ? bilingual(
                  lang,
                  `匹配 ${filteredSplits.length} / ${splits.length} 个任务`,
                  `${filteredSplits.length} of ${splits.length} tasks`,
                )
              : bilingual(
                  lang,
                  `${filteredSplits.length} 个任务`,
                  `${filteredSplits.length} ${filteredSplits.length === 1 ? "task" : "tasks"}`,
                );
          return (
            <>
              <header className="review-assignment-section-heading">
                <div>
                  <h2>{bilingual(lang, "分配批次", "Allocation batches")}</h2>
                </div>
                <label className="review-assignment-batch-search">
                  <span>{bilingual(lang, "搜索", "Search")}</span>
                  <input
                    id="reviewAssignmentBatchSearch"
                    type="search"
                    autoComplete="off"
                    maxLength={128}
                    value={batchSearch}
                    placeholder={bilingual(
                      lang,
                      "版本或任务名称，如 1106",
                      "Version or task name, e.g. 1106",
                    )}
                    aria-controls="reviewAssignmentList"
                    onChange={(e) => {
                      const nextValue = e.target.value;
                      setBatchSearch(nextValue);
                      replaceBatchSearchParam(nextValue);
                    }}
                  />
                </label>
                <div className="review-assignment-list-filters">
                  <div className="ra-assign-scope-filter">
                    <span>{bilingual(lang, "任务范围", "Task scope")}</span>
                    <UiSelect
                      id="reviewAssignmentLifecycleFilter"
                      className="dashboard-native-ui-select"
                      value={lifecycle}
                      options={lifecycleOptions}
                      ariaLabel={bilingual(lang, "任务范围", "Task scope")}
                      onChange={(val) => {
                        const nextScope = (VALID_LIFECYCLES as readonly string[]).includes(val)
                          ? (val as LifecycleScope)
                          : "current";
                        setLifecycle(nextScope);
                        setSelectedSplitId("");
                        pushRoute({ lifecycle: nextScope, splitId: "" });
                      }}
                    />
                  </div>
                  <button
                    className={`button ${assignedToMe ? "button-primary" : "button-quiet"}`}
                    id="reviewAssignmentMyTasks"
                    type="button"
                    aria-pressed={assignedToMe}
                    title={
                      assignedToMe
                        ? bilingual(lang, "当前仅显示我的任务，点击查看全部成员", "Showing my tasks; click for all members")
                        : bilingual(lang, "仅查看分配给当前账号的任务", "Show tasks assigned to the current account")
                    }
                    onClick={() => {
                      const nextMine = !assignedToMe;
                      setAssignedToMe(nextMine);
                      setSelectedSplitId("");
                      pushRoute({ assignedToMe: nextMine, splitId: "" });
                    }}
                  >
                    {bilingual(lang, "我的任务", "My tasks")}
                  </button>
                  <small id="reviewAssignmentListStatus" aria-live="polite">
                    {listStatusText}
                  </small>
                </div>
              </header>

              <div className="review-assignment-list" id="reviewAssignmentList">
                {splitsQuery.isLoading && !splits.length ? (
                  <div className="review-assignment-empty">
                    {bilingual(lang, "正在加载任务分配。", "Loading assignments.")}
                  </div>
                ) : !splits.length ? (
                  lifecycle === "history" ? (
                    <div className="review-assignment-empty">
                      {bilingual(lang, "暂无已替代或已取消的历史任务。", "No superseded or cancelled tasks.")}
                    </div>
                  ) : lifecycle === "manual" ? (
                    <div className="review-assignment-empty">
                      <strong>{bilingual(lang, "暂无进行中的手动任务", "No active manual tasks")}</strong>
                      <span>
                        {bilingual(
                          lang,
                          "点击上方“+ 新建分配”或从图库筛选后创建任务。",
                          'Click "+ New allocation" above or filter cases in the gallery.',
                        )}
                      </span>
                    </div>
                  ) : lifecycle === "versions" ? (
                    <div className="review-assignment-empty">
                      <strong>{bilingual(lang, "暂无进行中的自动任务", "No active auto tasks")}</strong>
                      <span>
                        {bilingual(
                          lang,
                          "可切换至“手动任务”或“全部任务”查看其他分配。",
                          'Switch to "Manual tasks" or "All tasks" to view other allocations.',
                        )}
                      </span>
                    </div>
                  ) : (
                    <div className="review-assignment-empty">
                      <strong>{bilingual(lang, "暂无进行中的任务分配", "No active assignments yet")}</strong>
                      <span>
                        {bilingual(
                          lang,
                          "点击上方“+ 新建分配”或从图库筛选后创建任务。",
                          'Click "+ New allocation" above or filter cases in the gallery.',
                        )}
                      </span>
                    </div>
                  )
                ) : !filteredSplits.length ? (
                  <div className="review-assignment-empty">
                    {bilingual(
                      lang,
                      "未找到匹配的批次，请更换关键词或调整任务范围。",
                      "No matching batches. Try another search or change the task scope.",
                    )}
                  </div>
                ) : (
                  filteredSplits.map((item) => (
                    <BatchCard
                      key={item.split_id}
                      item={item}
                      lang={lang}
                      isAdmin={isAdmin}
                      username={username}
                      verified={verified}
                      runNameLookup={runNameLookup}
                      onOpenDetail={handleOpenDetail}
                      onEditAllocation={(cid) => setEditCampaignId(cid)}
                      onShareLink={(sid) => void copyShareUrl(sid, true)}
                    />
                  ))
                )}
              </div>
            </>
          );
        })()}
      </section>

      <section
        ref={detailRef}
        className="page-card review-assignment-detail-card"
        id="reviewAssignmentDetail"
        hidden={!selectedSplitId}
      >
        {selectedSplitId && (
          <>
            <header className="review-assignment-section-heading">
              <div>
                <h2 id="reviewAssignmentDetailTitle">
                  {detail
                    ? `${roleVersionTaskName(detail, lang, runNameLookup)} · ${bilingual(lang, "任务明细", "Task detail")}`
                    : bilingual(lang, "正在加载任务明细", "Loading task detail")}
                </h2>
                <p id="reviewAssignmentDetailMeta">
                  {detail
                    ? `${detail.split_id} · ${detail.total_count || 0} ${bilingual(lang, "个 Issue", "Issues")} · ${detail.assignment_count || 0} ${bilingual(lang, "条任务", "tasks")} · ${reviewAssignmentModeLabel(detail, lang)}${
                        detailCanReview
                          ? ""
                          : ` · ${reviewAssignmentLifecycleLabel(detail, lang)} · ${bilingual(lang, "历史任务，只读", "Historical task; read-only")}`
                      }`
                    : ""}
                </p>
              </div>
              <div className="review-assignment-batch-actions">
                <button
                  className="button button-quiet"
                  type="button"
                  disabled={!detail || detailQueryRes.isFetching}
                  onClick={() => void copyShareUrl(selectedSplitId, false)}
                >
                  {bilingual(lang, "复制链接", "Copy link")}
                </button>
                <button
                  className="button button-quiet"
                  type="button"
                  onClick={handleCloseDetail}
                >
                  {bilingual(lang, "收起明细", "Close detail")}
                </button>
              </div>
            </header>

            <div className="review-assignment-detail-filters">
              <div className="ra-detail-filter-field">
                <span>{bilingual(lang, "负责人", "Assignee")}</span>
                <UiSelect
                  id="reviewAssignmentAssigneePicker"
                  value={detailAssignee}
                  options={detailAssigneeOptions}
                  ariaLabel={bilingual(lang, "负责人", "Assignee")}
                  onChange={(val) => {
                    setDetailAssignee(val);
                    setDetailPage(1);
                    pushRoute({ assignee: val, page: 1 });
                  }}
                />
              </div>
              <div className="ra-detail-filter-field">
                <span>{bilingual(lang, "任务状态", "Task status")}</span>
                <UiSelect
                  id="reviewAssignmentStatusPicker"
                  value={detailStatus}
                  options={detailStatusOptions}
                  ariaLabel={bilingual(lang, "任务状态", "Task status")}
                  onChange={(val) => {
                    setDetailStatus(val);
                    setDetailPage(1);
                    pushRoute({ status: val, page: 1 });
                  }}
                />
              </div>
              <label className="review-assignment-search">
                <span>{bilingual(lang, "搜索 Issue", "Search Issue")}</span>
                <input
                  id="reviewAssignmentSearch"
                  type="search"
                  maxLength={128}
                  autoComplete="off"
                  placeholder={bilingual(lang, "Issue ID / 场景", "Issue ID / scene")}
                  value={detailSearchInput}
                  onChange={(e) => {
                    const val = e.target.value;
                    setDetailSearchInput(val);
                    if (searchDebounceRef.current) window.clearTimeout(searchDebounceRef.current);
                    searchDebounceRef.current = window.setTimeout(() => {
                      const trimmed = val.trim();
                      setDetailQuery(trimmed);
                      setDetailPage(1);
                      pushRoute({ query: trimmed, page: 1 });
                    }, 240);
                  }}
                />
              </label>
            </div>

            {detail && (
              <div className="review-assignment-detail-summary">
                <span className="review-assignment-summary-chip is-complete">
                  {`${detail.completed_count || 0} ${bilingual(lang, "已完成", "completed")}`}
                </span>
                <span className="review-assignment-summary-chip is-pending">
                  {`${detail.pending_count || 0} ${bilingual(lang, "待处理", "pending")}`}
                </span>
                <span className="review-assignment-summary-chip">
                  {`${reviewAssignmentPercent(detail.completion_ratio)}% ${bilingual(lang, "完成率", "complete")}`}
                </span>
                <span className="review-assignment-summary-chip">
                  {`${detail.change_count || 0} ${bilingual(lang, "次转派", "transfers")}`}
                </span>
              </div>
            )}

            <div className="table-scroll review-assignment-table-scroll">
              <table className="review-assignment-table">
                <thead>
                  <tr>
                    <th>Issue</th>
                    <th>{bilingual(lang, "负责人", "Assignee")}</th>
                    <th>{bilingual(lang, "类型", "Type")}</th>
                    <th>{bilingual(lang, "状态", "Status")}</th>
                    <th>{bilingual(lang, "提交时间", "Submitted")}</th>
                    <th>{bilingual(lang, "任务调整", "Reassign")}</th>
                  </tr>
                </thead>
                <tbody id="reviewAssignmentDetailRows">
                  {detailQueryRes.isLoading || (detailQueryRes.isFetching && !detail) ? (
                    <tr>
                      <td colSpan={6} className="review-assignment-empty">
                        {bilingual(lang, "正在加载。", "Loading.")}
                      </td>
                    </tr>
                  ) : !detail?.items?.length ? (
                    <tr>
                      <td colSpan={6} className="review-assignment-empty">
                        {detailCanReview
                          ? bilingual(lang, "没有符合当前筛选的任务。", "No tasks match these filters.")
                          : bilingual(lang, "该批次的任务已被后续分配覆盖。", "This batch has been superseded.")}
                      </td>
                    </tr>
                  ) : (
                    detail.items.map((row) => {
                      const locked =
                        Boolean(detail.appendable) ||
                        !isAdmin ||
                        Boolean(row.submitted) ||
                        !detailCanReview;
                      const selectedAssignee = rowTransfers[row.issue_id] ?? row.assignee;
                      const taskTypeLabel = detail.appendable
                        ? bilingual(lang, "联合复核", "Combined review")
                        : row.assignment_kind === "cross"
                          ? bilingual(lang, "交叉复核", "Cross-review")
                          : row.assignment_kind === "full"
                            ? bilingual(lang, "全量复核", "Full review")
                            : bilingual(lang, "基础任务", "Base task");
                      const issueHref = reviewAssignmentBatchHref(detail, "review", username, verified, {
                        issue: row.issue_id,
                        runId: row.split_model_run_id || detail.model_run_id || "",
                        workAssignee: [row.assignee],
                        workSplitId: row.source_split_id || detail.split_id,
                      });
                      const rowKey = `${row.issue_id}-${row.assignee}`;
                      return (
                        <tr key={rowKey} data-issue-id={row.issue_id}>
                          <td>
                            {detailCanReview ? (
                              <a className="review-assignment-issue-link" href={issueHref}>
                                {row.issue_id}
                              </a>
                            ) : (
                              <span className="review-assignment-locked">{row.issue_id}</span>
                            )}
                            {(row.title || row.scenario) && (
                              <small
                                className="review-assignment-issue-meta"
                                title={row.title || row.scenario}
                              >
                                {row.title || row.scenario}
                              </small>
                            )}
                          </td>
                          <td>
                            {locked ? (
                              <span className="review-assignment-locked">
                                {row.assignee}
                                {row.submitted ? ` · ${bilingual(lang, "已提交", "submitted")}` : ""}
                              </span>
                            ) : (
                              <UiSelect
                                className="review-assignment-person-picker"
                                value={selectedAssignee}
                                options={personOptionsFor(selectedAssignee)}
                                disabled={usersQuery.isFetching || !accessUsers.length}
                                ariaLabel={`${row.issue_id} ${bilingual(lang, "负责人", "Assignee")}`}
                                onChange={(val) =>
                                  setRowTransfers((prev) => ({ ...prev, [row.issue_id]: val }))
                                }
                              />
                            )}
                          </td>
                          <td>{taskTypeLabel}</td>
                          <td>
                            {row.submitted ? (
                              <span className="review-assignment-task-status is-complete">
                                {bilingual(lang, "已完成", "Completed")}
                              </span>
                            ) : (
                              <span className="review-assignment-task-status is-pending">
                                {bilingual(lang, "待处理", "Pending")}
                              </span>
                            )}
                          </td>
                          <td>
                            {row.submitted_at
                              ? detail.appendable
                                ? `${formatVersionDatasetTime(row.submitted_at, lang)} CST`
                                : formatClassicTime(row.submitted_at)
                              : "—"}
                          </td>
                          <td>
                            {detail.appendable ? (
                              <span className="review-assignment-locked">
                                {bilingual(lang, "版本任务", "Version task")}
                              </span>
                            ) : locked ? (
                              <span className="review-assignment-locked">
                                {row.submitted
                                  ? bilingual(lang, "已完成，锁定", "Completed; locked")
                                  : !detailCanReview
                                    ? bilingual(lang, "历史批次，只读", "Read-only history")
                                    : bilingual(lang, "仅管理员可转派", "Only admins can transfer")}
                              </span>
                            ) : (
                              <button
                                className="button button-quiet review-assignment-save"
                                type="button"
                                disabled={
                                  selectedAssignee === row.assignee ||
                                  savingIssueId === row.issue_id
                                }
                                aria-busy={savingIssueId === row.issue_id}
                                onClick={() => void handleSaveTransfer(row.issue_id, row.assignee)}
                              >
                                {bilingual(lang, "保存转派", "Save transfer")}
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            <Pagination
              className="case-pagination gallery-pagination review-assignment-pagination"
              page={detail?.page || detailPage}
              pageSize={detailPageSize}
              total={detailTotalRows}
              lang={lang}
              loading={detailQueryRes.isFetching}
              labelText={`${detail?.page || detailPage} / ${Math.max(1, Number(detail?.page_count || 1))}`}
              showPageUnit
              keepControlsEnabledWhenEmpty
              ariaLabel={bilingual(lang, "任务明细分页", "Task detail pagination")}
              onPageChange={(nextPage) => {
                setDetailPage(nextPage);
                pushRoute({ page: nextPage });
              }}
              onPageSizeChange={(nextSize) => {
                setDetailPageSize(nextSize);
                setDetailPage(1);
                pushRoute({ page: 1, pageSize: nextSize });
              }}
            />

            {detail?.appendable && (
              <details className="review-assignment-change-log" id="reviewAssignmentAppendHistory">
                <summary>{bilingual(lang, "最近追加记录", "Recent additions")}</summary>
                <div id="reviewAssignmentAppendRows">
                  {detail.additions?.length ? (
                    detail.additions.map((b, idx) => (
                      <div key={`add-${idx}`} className="review-assignment-change-row">
                        <span>{`${formatVersionDatasetTime(b.created_at, lang)} CST`}</span>
                        <strong>{`+${b.target_added || 0} ${bilingual(lang, "个目标", "targets")}`}</strong>
                      </div>
                    ))
                  ) : (
                    <span className="quiet-meta">
                      {bilingual(lang, "暂无追加记录", "No additions recorded")}
                    </span>
                  )}
                </div>
              </details>
            )}

            <details className="review-assignment-change-log">
              <summary>{bilingual(lang, "最近的转派记录", "Recent reassignment history")}</summary>
              <div id="reviewAssignmentChangeLog">
                {detail?.changes?.length ? (
                  detail.changes.map((c, idx) => (
                    <div key={`chg-${idx}`} className="review-assignment-change-row">
                      <span>
                        <strong>{c.issue_id}</strong> · {c.from_assignee} → {c.to_assignee}
                      </span>
                      <small>{`${c.changed_by} · ${formatClassicTime(c.changed_at)}`}</small>
                    </div>
                  ))
                ) : (
                  <span className="quiet-meta">
                    {bilingual(lang, "暂无转派记录。", "No reassignment history.")}
                  </span>
                )}
              </div>
            </details>
          </>
        )}
      </section>

      <TaskAllocationDialog
        campaignId={editCampaignId}
        lang={lang}
        task={splits.find((item) => item.split_id === editCampaignId)}
        onClose={() => setEditCampaignId(null)}
        onSaved={() => {
          void queryClient.invalidateQueries({ queryKey: ["review-assignments-list"] });
          if (selectedSplitId) {
            void queryClient.invalidateQueries({ queryKey: ["review-assignment-detail"] });
          }
        }}
      />
    </div>
  );
};
