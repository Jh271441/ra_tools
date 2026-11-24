import React, { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest, getApiBasePath } from "../api/client";
import { bilingual, formatCstTime, UiLanguage } from "../bridge/useWorkbenchBridge";
import { CASE_PAGE_SIZES, DEFAULT_CASE_PAGE_SIZE, Pagination } from "../components/ui/Pagination";
import { StatusChip } from "../components/ui/StatusChip";
import { UiSelect } from "../components/ui/UiSelect";
import { AllocationEditorModal } from "../features/allocation/AllocationEditorModal";
import { NewAllocationModal } from "../features/allocation/NewAllocationModal";

export interface SplitMemberSummary {
  username: string;
  assigned_count: number;
  completed_count: number;
  pending_count: number;
  extra_completed_count?: number;
  completion_ratio?: number;
}

export interface WorkSplitItem {
  split_id: string;
  campaign_name?: string;
  lifecycle?: string;
  is_current?: boolean;
  legacy_read_only?: boolean;
  appendable?: boolean;
  actively_appending?: boolean;
  release_family?: string;
  role_cohort?: string;
  workflow_mode?: string;
  model_run_id?: string;
  baseline_ids?: string[];
  baseline_scopes?: string[];
  allocation_group_count?: number;
  reviewers_per_issue?: number;
  overlap_ratio?: number;
  total_count: number;
  assignment_count: number;
  completed_count: number;
  pending_count: number;
  conflict_count?: number;
  change_count?: number;
  completion_ratio?: number;
  created_at?: string;
  created_by?: string;
  updated_at?: string;
  last_target_added_at?: string;
  members?: SplitMemberSummary[];
}

interface WorkSplitListPayload {
  items: WorkSplitItem[];
  metrics?: {
    assignment_count?: number;
    completed_count?: number;
    pending_count?: number;
  };
}

interface WorkSplitDetailCase {
  issue_id: string;
  assignee: string;
  assignment_kind?: string;
  submitted?: boolean;
  submitted_at?: string;
  title?: string;
  scenario?: string;
  source_split_id?: string;
  split_model_run_id?: string;
}

interface WorkSplitDetailPayload extends WorkSplitItem {
  items: WorkSplitDetailCase[];
  page: number;
  page_size: number;
  page_count: number;
  filtered_count?: number;
  changes?: Array<{
    issue_id: string;
    from_assignee: string;
    to_assignee: string;
    changed_by: string;
    changed_at: string;
  }>;
  additions?: Array<{ created_at: string; target_added: number }>;
}

export interface ReviewAssignmentsPageProps {
  active: boolean;
  lang: UiLanguage;
  isAdmin: boolean;
  username: string;
}

type LifecycleFilter = "current" | "versions" | "manual" | "history" | "all";

function taskDisplayTitle(item: WorkSplitItem, lang: UiLanguage): string {
  if (item.role_cohort) {
    const fam = String(item.release_family || "").slice(4);
    const cohort =
      item.role_cohort === "sampling"
        ? bilingual(lang, "抽样集", "Sampling")
        : bilingual(lang, "低置信集", "Low confidence");
    return `${fam} · ${cohort}`;
  }
  if (item.appendable) {
    return `${String(item.release_family || "").slice(4)} · ${bilingual(lang, "版本联合复核", "Version combined review")}`;
  }
  return item.campaign_name || item.model_run_id || item.split_id;
}

function canReviewSplit(item: WorkSplitItem): boolean {
  return Boolean(
    item.is_current && !item.legacy_read_only && (!item.lifecycle || item.lifecycle === "active"),
  );
}

function pct(ratio: number | undefined): number {
  const n = Number(ratio);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n * 100)));
}

function readInitialRoute(): {
  lifecycle: LifecycleFilter;
  assignedToMe: boolean;
  splitId: string;
  page: number;
  pageSize: number;
} {
  if (typeof window === "undefined") {
    return {
      lifecycle: "current",
      assignedToMe: false,
      splitId: "",
      page: 1,
      pageSize: DEFAULT_CASE_PAGE_SIZE,
    };
  }
  const params = new URLSearchParams(window.location.search);
  const rawLc = params.get("lifecycle") || "current";
  const lifecycle: LifecycleFilter = ["current", "versions", "manual", "history", "all"].includes(
    rawLc,
  )
    ? (rawLc as LifecycleFilter)
    : "current";
  const rawSize = Number(params.get("page_size"));
  const pageSize = CASE_PAGE_SIZES.includes(rawSize as (typeof CASE_PAGE_SIZES)[number])
    ? rawSize
    : DEFAULT_CASE_PAGE_SIZE;
  const page = Math.max(1, Number(params.get("page")) || 1);
  return {
    lifecycle,
    assignedToMe: params.get("assigned_to_me") === "true",
    splitId: params.get("split") || "",
    page,
    pageSize,
  };
}

export const ReviewAssignmentsPage: React.FC<ReviewAssignmentsPageProps> = ({
  active,
  lang,
  isAdmin,
  username,
}) => {
  const queryClient = useQueryClient();
  const initial = useMemo(() => readInitialRoute(), []);
  const [lifecycle, setLifecycle] = useState<LifecycleFilter>(initial.lifecycle);
  const [assignedToMe, setAssignedToMe] = useState<boolean>(initial.assignedToMe);
  const [selectedSplitId, setSelectedSplitId] = useState<string>(initial.splitId);
  const [detailAssignee, setDetailAssignee] = useState<string>("");
  const [detailStatus, setDetailStatus] = useState<string>("all");
  const [detailSearch, setDetailSearch] = useState<string>("");
  const [detailPage, setDetailPage] = useState<number>(initial.page);
  const [detailPageSize, setDetailPageSize] = useState<number>(initial.pageSize);
  const [rowAssigneeDrafts, setRowAssigneeDrafts] = useState<Record<string, string>>({});

  const [editingCampaignId, setEditingCampaignId] = useState<string | null>(null);
  const [showNewModal, setShowNewModal] = useState(false);
  const [copyToast, setCopyToast] = useState<string>("");

  const syncUrl = (next: {
    lifecycle?: LifecycleFilter;
    assignedToMe?: boolean;
    splitId?: string;
    page?: number;
    pageSize?: number;
  }) => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    const lc = next.lifecycle ?? lifecycle;
    const mine = next.assignedToMe ?? assignedToMe;
    const sid = next.splitId !== undefined ? next.splitId : selectedSplitId;
    const pg = next.page ?? detailPage;
    const ps = next.pageSize ?? detailPageSize;
    url.searchParams.set("lifecycle", lc);
    if (mine) url.searchParams.set("assigned_to_me", "true");
    else url.searchParams.delete("assigned_to_me");
    if (sid) {
      url.searchParams.set("split", sid);
      url.searchParams.set("page", String(pg));
      url.searchParams.set("page_size", String(ps));
    } else {
      url.searchParams.delete("split");
      url.searchParams.delete("page");
      url.searchParams.delete("page_size");
    }
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}`);
  };

  const splitsQuery = useQuery<WorkSplitListPayload>({
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
      return apiRequest<WorkSplitListPayload>(`/api/cases/work-splits?${params.toString()}`, {
        signal,
      });
    },
    enabled: active,
    staleTime: 15_000,
  });

  const accessUsersQuery = useQuery<{ items: Array<{ username: string; role: string }> }>({
    queryKey: ["access-users"],
    queryFn: ({ signal }) =>
      apiRequest<{ items: Array<{ username: string; role: string }> }>("/api/access-users", {
        signal,
      }),
    enabled: active && isAdmin,
    staleTime: 60_000,
  });

  const detailQuery = useQuery<WorkSplitDetailPayload>({
    queryKey: [
      "review-assignment-detail",
      selectedSplitId,
      detailPage,
      detailPageSize,
      detailAssignee,
      detailStatus,
      detailSearch,
    ],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        page: String(detailPage),
        page_size: String(detailPageSize),
        status: detailStatus,
      });
      if (detailAssignee) params.set("assignee", detailAssignee);
      if (detailSearch.trim()) params.set("q", detailSearch.trim());
      return apiRequest<WorkSplitDetailPayload>(
        `/api/cases/work-splits/${encodeURIComponent(selectedSplitId)}?${params.toString()}`,
        { signal },
      );
    },
    enabled: active && Boolean(selectedSplitId),
    staleTime: 10_000,
  });

  const reassignMutation = useMutation({
    mutationFn: (payload: { splitId: string; issueId: string; assignee: string }) =>
      apiRequest(
        `/api/cases/work-splits/${encodeURIComponent(payload.splitId)}/assignments/${encodeURIComponent(payload.issueId)}`,
        {
          method: "PATCH",
          body: { assignee: payload.assignee },
        },
      ),
    onSuccess: (_res, vars) => {
      setRowAssigneeDrafts((prev) => {
        const next = { ...prev };
        delete next[vars.issueId];
        return next;
      });
      setCopyToast(
        bilingual(
          lang,
          `${vars.issueId} 已转派给 ${vars.assignee}。`,
          `${vars.issueId} transferred to ${vars.assignee}.`,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ["review-assignments-list"] });
      void queryClient.invalidateQueries({ queryKey: ["review-assignment-detail"] });
    },
    onError: (err) => {
      setCopyToast(err instanceof Error ? err.message : bilingual(lang, "转派失败", "Transfer failed"));
    },
  });

  const items = splitsQuery.data?.items || [];
  const metrics = splitsQuery.data?.metrics;
  const activeCount = items.filter((i) => i.is_current).length;
  const totalAssignments =
    metrics?.assignment_count ?? items.reduce((s, i) => s + Number(i.assignment_count || 0), 0);
  const completedCount =
    metrics?.completed_count ?? items.reduce((s, i) => s + Number(i.completed_count || 0), 0);
  const pendingCount =
    metrics?.pending_count ?? items.reduce((s, i) => s + Number(i.pending_count || 0), 0);

  const eligibleMembers = useMemo(
    () => (accessUsersQuery.data?.items || []).map((u) => u.username).filter(Boolean),
    [accessUsersQuery.data],
  );

  const base = getApiBasePath();
  const buildBatchHref = (item: WorkSplitItem, target: "review" | "analysis") => {
    const params = new URLSearchParams();
    if (item.model_run_id) params.set("run", item.model_run_id);
    params.set("work_split", item.split_id);
    const ds = (item.baseline_ids || item.baseline_scopes || []).join(",");
    if (ds) params.set("baselines", ds);
    if (target === "review") {
      if (item.appendable) params.set("task_view", "targets");
      if (item.workflow_mode === "model_review_and_case_label") {
        params.set("task_progress", "pending");
      }
      if (
        username &&
        (item.members || []).some((m) => m.username.toLowerCase() === username.toLowerCase())
      ) {
        params.set("work_assignee", username);
      }
      return `${base}/review?${params.toString()}`;
    }
    return `${base}/review-analysis?${params.toString()}`;
  };

  const handleCopyLink = async (splitId?: string) => {
    const url = new URL(`${base}/review-assignments`, window.location.origin);
    url.searchParams.set("lifecycle", splitId ? "all" : lifecycle);
    if (!splitId && assignedToMe) url.searchParams.set("assigned_to_me", "true");
    if (splitId) url.searchParams.set("split", splitId);
    try {
      await navigator.clipboard.writeText(url.href);
      setCopyToast(bilingual(lang, "任务分配链接已复制。", "Assignment link copied."));
    } catch {
      setCopyToast(url.href);
    }
    window.setTimeout(() => setCopyToast(""), 3500);
  };

  const lifecycleOptions = [
    { value: "current", label: bilingual(lang, "全部进行中", "All active") },
    { value: "versions", label: bilingual(lang, "自动任务", "Auto tasks") },
    { value: "manual", label: bilingual(lang, "手动任务", "Manual tasks") },
    { value: "history", label: bilingual(lang, "历史任务", "Historical tasks") },
    { value: "all", label: bilingual(lang, "全部任务", "All tasks") },
  ];

  const detail = detailQuery.data;
  const detailTotalItems =
    detail?.filtered_count ?? (detail ? detail.page_count * detail.page_size : 0);

  const detailAssigneeOptions = [
    { value: "", label: bilingual(lang, "全部负责人", "All assignees") },
    ...(detail?.members || []).map((m) => ({
      value: m.username,
      label: `${m.username} · ${m.assigned_count || 0}`,
    })),
  ];

  const detailStatusOptions = [
    { value: "all", label: bilingual(lang, "全部状态", "All statuses") },
    { value: "pending", label: bilingual(lang, "待处理", "Pending") },
    { value: "completed", label: bilingual(lang, "已完成", "Completed") },
  ];

  return (
    <div className="ra-assignments-root" data-react-island="review-assignments">
      <section
        className="review-assignment-metrics"
        id="raReviewAssignmentMetrics"
        aria-label={bilingual(lang, "任务分配概览", "Assignment summary")}
      >
        <article className="review-assignment-metric">
          <small>{bilingual(lang, "任务", "Tasks")}</small>
          <strong>{items.length.toLocaleString()}</strong>
          <span>
            {bilingual(lang, `${activeCount} 个当前任务`, `${activeCount} active tasks`)}
          </span>
        </article>
        <article className="review-assignment-metric">
          <small>{bilingual(lang, "任务总量", "Assigned tasks")}</small>
          <strong>{totalAssignments.toLocaleString()}</strong>
          <span>
            {assignedToMe
              ? bilingual(lang, "仅统计当前账号", "Current user only")
              : bilingual(lang, "按负责人任务计数", "Assignments by owner")}
          </span>
        </article>
        <article className="review-assignment-metric">
          <small>{bilingual(lang, "已完成", "Completed")}</small>
          <strong>{completedCount.toLocaleString()}</strong>
          <span>
            {bilingual(lang, "联合任务需两部分均完成", "Combined tasks require both parts")}
          </span>
        </article>
        <article className="review-assignment-metric">
          <small>{bilingual(lang, "待处理", "Pending")}</small>
          <strong>{pendingCount.toLocaleString()}</strong>
          <span>
            {lifecycle === "history"
              ? bilingual(lang, "历史未完成，只读", "Historical unfinished; read-only")
              : bilingual(lang, "当前范围内未完成", "Unfinished in this scope")}
          </span>
        </article>
      </section>

      <section className="page-card ra-assignments-toolbar">
        <div className="ra-assignments-toolbar-left">
          <h2>{isAdmin ? bilingual(lang, "分配配置", "Assignment setup") : bilingual(lang, "任务分配", "Review assignments")}</h2>
          <div className="ra-assignments-filters">
            <UiSelect
              id="raLifecycleFilter"
              value={lifecycle}
              options={lifecycleOptions}
              ariaLabel={bilingual(lang, "任务生命周期筛选", "Filter tasks by lifecycle")}
              onChange={(val) => {
                const nextLc = val as LifecycleFilter;
                setLifecycle(nextLc);
                setSelectedSplitId("");
                syncUrl({ lifecycle: nextLc, splitId: "" });
              }}
            />
            <button
              type="button"
              className={`button ${assignedToMe ? "button-primary" : "button-quiet"}`}
              aria-pressed={assignedToMe}
              onClick={() => {
                const next = !assignedToMe;
                setAssignedToMe(next);
                syncUrl({ assignedToMe: next });
              }}
            >
              {bilingual(lang, "只看我的", "My tasks")}
            </button>
          </div>
        </div>

        <div className="ra-assignments-toolbar-actions">
          {isAdmin && (
            <button
              type="button"
              className="button button-primary ra-primary-touch"
              onClick={() => setShowNewModal(true)}
            >
              {bilingual(lang, "+ 新建分配", "+ New allocation")}
            </button>
          )}
          <a className="button button-quiet" href={`${base}/review`}>
            {bilingual(lang, "从图库筛选", "Filter in gallery")}
          </a>
          <button
            type="button"
            className="button button-quiet"
            onClick={() => void handleCopyLink()}
          >
            {bilingual(lang, "复制链接", "Copy link")}
          </button>
          <button
            type="button"
            className="button button-quiet"
            disabled={splitsQuery.isFetching}
            onClick={() => void splitsQuery.refetch()}
          >
            {splitsQuery.isFetching
              ? bilingual(lang, "刷新中…", "Refreshing…")
              : bilingual(lang, "刷新", "Refresh")}
          </button>
        </div>
      </section>

      {copyToast && (
        <p className="ra-inline-feedback" role="status">
          {copyToast}
        </p>
      )}

      {selectedSplitId && (
        <section
          className="page-card ra-assignment-detail-card"
          id="raReviewAssignmentDetail"
          aria-live="polite"
        >
          <header className="ra-detail-header">
            <div>
              <h3>
                {detail
                  ? `${taskDisplayTitle(detail, lang)} · ${bilingual(lang, "任务明细", "Task detail")}`
                  : bilingual(lang, "正在加载任务明细…", "Loading task detail…")}
              </h3>
              {detail && (
                <p className="muted">
                  {detail.split_id} · {detail.total_count || 0}{" "}
                  {bilingual(lang, "个 Issue", "Issues")} · {detail.assignment_count || 0}{" "}
                  {bilingual(lang, "条任务", "tasks")}
                </p>
              )}
            </div>
            <div className="ra-detail-header-actions">
              <button
                type="button"
                className="button button-quiet"
                onClick={() => void handleCopyLink(selectedSplitId)}
              >
                {bilingual(lang, "复制链接", "Copy link")}
              </button>
              <button
                type="button"
                className="button button-quiet"
                onClick={() => {
                  setSelectedSplitId("");
                  syncUrl({ splitId: "" });
                }}
              >
                {bilingual(lang, "收起明细", "Close detail")}
              </button>
            </div>
          </header>

          {detail && (
            <>
              <div className="ra-detail-filter-bar">
                <UiSelect
                  value={detailAssignee}
                  options={detailAssigneeOptions}
                  ariaLabel={bilingual(lang, "按负责人筛选", "Filter by assignee")}
                  onChange={(val) => {
                    setDetailAssignee(val);
                    setDetailPage(1);
                    setRowAssigneeDrafts({});
                    syncUrl({ page: 1 });
                  }}
                />
                <UiSelect
                  value={detailStatus}
                  options={detailStatusOptions}
                  ariaLabel={bilingual(lang, "按状态筛选", "Filter by status")}
                  onChange={(val) => {
                    setDetailStatus(val);
                    setDetailPage(1);
                    setRowAssigneeDrafts({});
                    syncUrl({ page: 1 });
                  }}
                />
                <input
                  type="search"
                  value={detailSearch}
                  placeholder={bilingual(lang, "搜索 Issue ID…", "Search Issue ID…")}
                  aria-label={bilingual(lang, "搜索 Issue ID", "Search Issue ID")}
                  onChange={(e) => {
                    setDetailSearch(e.target.value);
                    setDetailPage(1);
                    setRowAssigneeDrafts({});
                  }}
                />
              </div>

              <div className="ra-table-scroll" tabIndex={0}>
                <table className="system-media-table ra-detail-table">
                  <thead>
                    <tr>
                      <th scope="col">Issue</th>
                      <th scope="col">{bilingual(lang, "负责人", "Assignee")}</th>
                      <th scope="col">{bilingual(lang, "状态", "Status")}</th>
                      <th scope="col">{bilingual(lang, "提交时间", "Submitted")}</th>
                      <th scope="col">{bilingual(lang, "操作", "Action")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailQuery.isLoading ? (
                      <tr>
                        <td colSpan={5}>{bilingual(lang, "正在加载…", "Loading…")}</td>
                      </tr>
                    ) : !detail.items?.length ? (
                      <tr>
                        <td colSpan={5}>
                          {bilingual(lang, "没有符合当前筛选的任务。", "No tasks match these filters.")}
                        </td>
                      </tr>
                    ) : (
                      detail.items.map((row) => {
                        const isCurrent = canReviewSplit(detail);
                        const locked = detail.appendable || !isAdmin || row.submitted || !isCurrent;
                        const selectedNext = rowAssigneeDrafts[row.issue_id] ?? row.assignee;
                        const personOpts = eligibleMembers.map((u) => ({ value: u, label: u }));
                        if (!personOpts.some((o) => o.value === row.assignee)) {
                          personOpts.unshift({ value: row.assignee, label: row.assignee });
                        }
                        return (
                          <tr key={`${row.issue_id}-${row.assignee}`}>
                            <td>
                              {isCurrent ? (
                                <a
                                  className="review-assignment-issue-link"
                                  href={`${base}/review?issue=${encodeURIComponent(row.issue_id)}&work_split=${encodeURIComponent(row.source_split_id || detail.split_id)}`}
                                >
                                  {row.issue_id}
                                </a>
                              ) : (
                                <span>{row.issue_id}</span>
                              )}
                            </td>
                            <td>
                              {locked ? (
                                <span>{row.assignee}</span>
                              ) : (
                                <UiSelect
                                  value={selectedNext}
                                  options={personOpts}
                                  compact
                                  ariaLabel={bilingual(
                                    lang,
                                    `调整 ${row.issue_id} 负责人`,
                                    `Reassign ${row.issue_id}`,
                                  )}
                                  onChange={(val) =>
                                    setRowAssigneeDrafts((prev) => ({
                                      ...prev,
                                      [row.issue_id]: val,
                                    }))
                                  }
                                />
                              )}
                            </td>
                            <td>
                              <StatusChip
                                label={
                                  row.submitted
                                    ? bilingual(lang, "已完成", "Completed")
                                    : bilingual(lang, "待处理", "Pending")
                                }
                                tone={row.submitted ? "ok" : "neutral"}
                              />
                            </td>
                            <td>{row.submitted_at ? formatCstTime(row.submitted_at, lang) : "—"}</td>
                            <td>
                              {locked ? (
                                <span className="muted">
                                  {detail.appendable
                                    ? bilingual(lang, "版本任务", "Version task")
                                    : row.submitted
                                      ? bilingual(lang, "已锁定", "Locked")
                                      : bilingual(lang, "只读", "Read-only")}
                                </span>
                              ) : (
                                <button
                                  type="button"
                                  className="button button-quiet"
                                  disabled={
                                    selectedNext === row.assignee || reassignMutation.isPending
                                  }
                                  onClick={() =>
                                    reassignMutation.mutate({
                                      splitId: detail.split_id,
                                      issueId: row.issue_id,
                                      assignee: selectedNext,
                                    })
                                  }
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
                page={detailPage}
                pageSize={detailPageSize}
                total={detailTotalItems}
                lang={lang}
                loading={detailQuery.isFetching}
                ariaLabel={bilingual(lang, "任务明细分页", "Task detail pagination")}
                onPageChange={(nextPage) => {
                  setDetailPage(nextPage);
                  syncUrl({ page: nextPage });
                }}
                onPageSizeChange={(nextSize) => {
                  setDetailPageSize(nextSize);
                  setDetailPage(1);
                  syncUrl({ page: 1, pageSize: nextSize });
                }}
                onClearSelection={() => setRowAssigneeDrafts({})}
              />
            </>
          )}
        </section>
      )}

      <div className="review-assignment-list" id="raReviewAssignmentList">
        {splitsQuery.isLoading ? (
          <div className="review-assignment-empty">
            {bilingual(lang, "正在加载任务分配…", "Loading assignments…")}
          </div>
        ) : splitsQuery.isError ? (
          <div className="review-assignment-empty">
            {bilingual(lang, "读取任务分配失败，请刷新重试。", "Failed to load assignments.")}
          </div>
        ) : items.length === 0 ? (
          <div className="review-assignment-empty">
            {bilingual(lang, "当前筛选范围内暂无任务分配。", "No assignments in this filter scope.")}
          </div>
        ) : (
          items.map((item) => {
            const current = canReviewSplit(item);
            const progressPct = pct(item.completion_ratio);
            const statusText = item.appendable
              ? current
                ? item.actively_appending !== false
                  ? bilingual(lang, "自动 · 持续追加", "Auto · Appending")
                  : bilingual(lang, "自动 · 收集完成", "Auto · Collected")
                : bilingual(lang, "历史任务", "Historical")
              : current
                ? bilingual(lang, "手动分配", "Manual")
                : bilingual(lang, "历史任务", "Historical");
            const canEditAllocation = Boolean(isAdmin && current);

            return (
              <article
                key={item.split_id}
                className="review-assignment-batch"
                data-review-assignment-batch={item.split_id}
              >
                <header className="review-assignment-batch-header">
                  <div>
                    <strong className="review-assignment-batch-title">
                      {taskDisplayTitle(item, lang)}
                    </strong>
                    <span className="review-assignment-batch-meta">
                      {item.split_id} · {item.created_by || bilingual(lang, "系统", "System")} ·{" "}
                      {formatCstTime(
                        item.last_target_added_at || item.updated_at || item.created_at,
                        lang,
                      )}
                    </span>
                  </div>
                  <StatusChip label={statusText} tone={current ? "ok" : "neutral"} />
                </header>

                <div className="review-assignment-progress">
                  <div className="review-assignment-progress-heading">
                    <span>
                      {bilingual(lang, "整体进度", "Overall progress")}
                      {(item.conflict_count || 0) > 0 && (
                        <span className="review-assignment-conflict-pill">
                          {bilingual(
                            lang,
                            `${item.conflict_count} 条相交冲突`,
                            `${item.conflict_count} conflicts`,
                          )}
                        </span>
                      )}
                    </span>
                    <strong>
                      {item.completed_count || 0} / {item.assignment_count || 0} · {progressPct}%
                    </strong>
                  </div>
                  <div className="review-assignment-progress-track">
                    <span style={{ width: `${progressPct}%` }} />
                  </div>
                </div>

                <div className="review-assignment-member-grid">
                  {(item.members || []).map((m) => {
                    const mPct =
                      m.assigned_count === 0 && m.completed_count > 0
                        ? 100
                        : pct(m.completion_ratio);
                    return (
                      <div key={m.username} className="review-assignment-member">
                        <div className="review-assignment-member-heading">
                          <strong>{m.username}</strong>
                          <span>
                            {m.completed_count} / {m.assigned_count}
                          </span>
                        </div>
                        <div className="review-assignment-progress-track">
                          <span style={{ width: `${mPct}%` }} />
                        </div>
                        <small>
                          {bilingual(lang, `${m.pending_count} 条待处理`, `${m.pending_count} pending`)}
                        </small>
                      </div>
                    );
                  })}
                </div>

                <footer className="review-assignment-batch-footer">
                  <span>
                    {item.total_count || 0} {bilingual(lang, "个 Case", "Cases")}
                  </span>
                  <div className="review-assignment-batch-actions">
                    {current && (
                      <>
                        <a className="button button-quiet" href={buildBatchHref(item, "review")}>
                          {item.workflow_mode === "model_review_and_case_label"
                            ? bilingual(lang, "开始联合复核", "Start combined review")
                            : bilingual(lang, "去判错复核", "Open Review")}
                        </a>
                        <a className="button button-quiet" href={buildBatchHref(item, "analysis")}>
                          {bilingual(lang, "去原因聚类", "Open analysis")}
                        </a>
                      </>
                    )}
                    {canEditAllocation && (
                      <button
                        type="button"
                        className="button button-quiet"
                        data-ra-edit-allocation={item.split_id}
                        onClick={() => setEditingCampaignId(item.split_id)}
                      >
                        {bilingual(lang, "修改分配", "Edit allocation")}
                      </button>
                    )}
                    <button
                      type="button"
                      className="button button-quiet"
                      onClick={() => {
                        setSelectedSplitId(item.split_id);
                        setDetailPage(1);
                        setDetailAssignee("");
                        setDetailStatus("all");
                        setDetailSearch("");
                        setRowAssigneeDrafts({});
                        syncUrl({ splitId: item.split_id, page: 1 });
                      }}
                    >
                      {bilingual(lang, "查看任务明细", "View task detail")}
                    </button>
                    <button
                      type="button"
                      className="button button-quiet"
                      onClick={() => void handleCopyLink(item.split_id)}
                    >
                      {bilingual(lang, "复制链接", "Copy link")}
                    </button>
                  </div>
                </footer>
              </article>
            );
          })
        )}
      </div>

      <AllocationEditorModal
        campaignId={editingCampaignId}
        lang={lang}
        onClose={() => setEditingCampaignId(null)}
        onSaved={() => {
          void queryClient.invalidateQueries({ queryKey: ["review-assignments-list"] });
          void queryClient.invalidateQueries({ queryKey: ["review-assignment-detail"] });
        }}
      />

      <NewAllocationModal
        open={showNewModal}
        lang={lang}
        eligibleMembers={eligibleMembers}
        onClose={() => setShowNewModal(false)}
        onCreated={() => {
          void queryClient.invalidateQueries({ queryKey: ["review-assignments-list"] });
        }}
      />
    </div>
  );
};
