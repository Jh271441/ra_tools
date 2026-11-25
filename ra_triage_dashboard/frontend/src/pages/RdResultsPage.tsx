import React, { useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  formatCstTime,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import {
  CASE_PAGE_SIZES,
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { UiSelect } from "../components/ui/UiSelect";
import {
  displayLabelText,
  labelBadgeClass,
  parseIssueIdsInput,
  showWorkbenchToast,
} from "../features/review/reviewHelpers";

export interface RdResultsPageProps {
  active: boolean;
  lang: UiLanguage;
  isAdmin: boolean;
  selectedBaselines: string[];
}

const RD_UPLOAD_ENDPOINT = "https://voyager.intra.xiaojukeji.com/paladin/issue/pool/multi_update/";

interface RdRow {
  issue_id: string;
  group?: string;
  state?: string;
  label?: string;
  te_current?: string;
  correction_status?: string;
  authors?: string[];
}

interface RdListResponse {
  items: RdRow[];
  total: number;
  page: number;
  pages: number;
  page_size: number;
  write_enabled?: boolean;
  counts: Record<string, number>;
  snapshot?: {
    last_success_at?: string;
    refresh?: {
      status?: string;
      scanned?: number;
      total?: number;
      checked_at?: string;
    };
  };
}

interface RdOperationItem {
  issue_id: string;
  eligible?: boolean;
  status?: string;
  current?: string;
  desired?: string;
  rd_current?: string;
  manual_current?: { state?: string; label?: string };
}

interface RdOperationResult {
  issue_id: string;
  state?: string;
  phase?: string;
  observed?: string;
  reason?: string;
}

interface RdOperationReceipt {
  id: string;
  mode?: string;
  state: string;
  actor?: string;
  reason?: string;
  baselines?: string;
  policy_version?: number;
  history_operation_id?: string;
  audit_error?: string;
  items?: RdOperationItem[];
  results?: RdOperationResult[];
  scope?: {
    total?: number;
    excluded?: number;
    blocked?: number;
    source?: { kind?: string; filename?: string; sheet?: string; sha256?: string; duplicates?: number };
  };
  progress?: {
    stage?: string;
    checked?: number;
    check_total?: number;
    verified?: number;
    total?: number;
    active?: number;
    waiting?: number;
    elapsed_seconds?: number;
  };
}

interface HumanPubRow {
  issue_id: string;
  conclusion: string;
  label?: string;
  authors: string[];
  submitted: number;
  required: number;
  publication_armed?: number;
  sync_state: string;
  checked_at?: string;
  error_code?: string;
  objections?: { author: string; label: string }[];
}

interface HumanPubListResponse {
  items: HumanPubRow[];
  total: number;
  page: number;
  pages: number;
  page_size: number;
  field?: string;
  write_enabled?: boolean;
  counts: Record<string, number>;
}

interface HumanPubPreviewResponse {
  id: string;
  items: { issue_id: string; action: string; desired: string | null; eligible?: boolean }[];
}

interface HumanPubHistoryResponse {
  items: { created_at: string; action: string; desired: string | null; state: string }[];
  total: number;
  page: number;
  pages: number;
}

function statusDisplay(value: string | undefined, lang: UiLanguage): string {
  const key = String(value || "");
  const map: Record<string, [string, string]> = {
    resolved: ["已完成", "Completed"],
    pending: ["待上传", "Pending"],
    conflict: ["冲突 / 差异", "Conflict"],
    same: ["已一致", "Already matches"],
    blocked: ["不可上传", "Blocked"],
    preparing: ["正在生成预览", "Preparing preview"],
    preview: ["预览待确认", "Preview ready"],
    preview_failed: ["预览失败", "Preview failed"],
    complete: ["已核验完成", "Verified complete"],
    needs_recheck: ["需重新核对", "Recheck required"],
    running: ["正在上传并核验", "Uploading & verifying"],
    verified: ["读回一致", "Verified"],
    unverified: ["未确认", "Unverified"],
    not_attempted: ["未执行", "Not attempted"],
    synced: ["已同步", "Synced"],
    not_ready: ["待结论", "Awaiting result"],
    awaiting_activation: ["历史结果待启用", "Awaiting activation"],
    none: ["未裁决", "No decision"],
    stale: ["裁决失效", "Stale"],
    objection: ["有任务外异议", "Objection"],
    unassigned: ["未分配该角色", "Unassigned"],
    inactive: ["来源已停用", "Inactive"],
    unclassified: ["身份待确认", "Unclassified"],
  };
  const pair = map[key];
  return pair ? bilingual(lang, pair[0], pair[1]) : key || "—";
}

function statusTone(value: string | undefined): string {
  const key = String(value || "");
  if (["same", "complete", "verified", "synced"].includes(key)) return "rd-status-ok";
  if (["conflict", "needs_recheck", "unverified", "stale", "preview_failed"].includes(key))
    return "rd-status-warn";
  if (["pending", "resolved", "preview"].includes(key)) return "rd-status-ready";
  return "rd-status-neutral";
}

export const RdResultsPage: React.FC<RdResultsPageProps> = ({
  active,
  lang,
  isAdmin,
  selectedBaselines,
}) => {
  const queryClient = useQueryClient();
  const initialParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const baselinesKey = selectedBaselines.join(",");
  const isHumanPubScope =
    selectedBaselines.length > 0 &&
    selectedBaselines.every((id) => /^version-20\d{6}$/.test(id) && id.slice(8) >= "20261106");
  const isSingleVersion =
    selectedBaselines.length === 1 && /^version-20\d{6}$/.test(selectedBaselines[0]);

  const [mode, setMode] = useState<"rd" | "te-correction">(
    initialParams.get("mode") === "te-correction" ? "te-correction" : "rd",
  );
  const [hpLane, setHpLane] = useState<"rd" | "te" | "arbitrated">(
    (["rd", "te", "arbitrated"].includes(initialParams.get("lane") || "")
      ? (initialParams.get("lane") as "rd" | "te" | "arbitrated")
      : "rd"),
  );
  const [searchDraft, setSearchDraft] = useState(initialParams.get("q") || "");
  const [queryText, setQueryText] = useState(initialParams.get("q") || "");
  const [statusFilter, setStatusFilter] = useState(initialParams.get("status") || "all");
  const [page, setPage] = useState(Math.max(1, Number(initialParams.get("page")) || 1));
  const [pageSize, setPageSize] = useState(
    CASE_PAGE_SIZES.includes(Number(initialParams.get("page_size")) as 10 | 20 | 50 | 100)
      ? Number(initialParams.get("page_size"))
      : DEFAULT_CASE_PAGE_SIZE,
  );
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [allSelected, setAllSelected] = useState(false);
  const [excludedIds, setExcludedIds] = useState<string[]>([]);
  const [excelFile, setExcelFile] = useState<File | null>(null);
  const [errorBanner, setErrorBanner] = useState("");
  const [activeOperationId, setActiveOperationId] = useState<string | null>(null);
  const [showOperations, setShowOperations] = useState(false);
  const [hpPreview, setHpPreview] = useState<HumanPubPreviewResponse | null>(null);
  const [hpHistoryIssue, setHpHistoryIssue] = useState<string>("");
  const [hpHistoryPage, setHpHistoryPage] = useState<number>(1);
  const [hpHistorySize, setHpHistorySize] = useState<number>(DEFAULT_CASE_PAGE_SIZE);
  const [previewPage, setPreviewPage] = useState<number>(1);
  const [previewPageSize, setPreviewPageSize] = useState<number>(DEFAULT_CASE_PAGE_SIZE);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const useHumanPub = isHumanPubScope && mode !== "te-correction";
  const isTe = mode === "te-correction";

  // Sync URL
  useEffect(() => {
    if (!active) return;
    const url = new URL(window.location.href);
    if (baselinesKey) url.searchParams.set("baselines", baselinesKey);
    if (isTe) url.searchParams.set("mode", "te-correction");
    else url.searchParams.delete("mode");
    if (useHumanPub) url.searchParams.set("lane", hpLane);
    else url.searchParams.delete("lane");
    if (queryText) url.searchParams.set("q", queryText);
    else url.searchParams.delete("q");
    if (statusFilter && statusFilter !== "all") url.searchParams.set("status", statusFilter);
    else url.searchParams.delete("status");
    url.searchParams.set("page", String(page));
    url.searchParams.set("page_size", String(pageSize));
    window.history.replaceState(window.history.state, "", url.pathname + url.search);
  }, [active, baselinesKey, isTe, useHumanPub, hpLane, queryText, statusFilter, page, pageSize]);

  // Clear selection when scope/mode/page changes
  useEffect(() => {
    setSelectedIds([]);
    setAllSelected(false);
    setExcludedIds([]);
    setHpPreview(null);
  }, [baselinesKey, mode, hpLane, page, pageSize, queryText, statusFilter]);

  const rdListQuery = useQuery<RdListResponse>({
    queryKey: ["rd-results-list", baselinesKey, mode, queryText, statusFilter, page, pageSize],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        baselines: baselinesKey,
        mode,
        q: queryText,
        status: statusFilter,
        page: String(page),
        page_size: String(pageSize),
      });
      return apiRequest<RdListResponse>(`/api/rd-results?${qs.toString()}`, { signal });
    },
    enabled: active && !useHumanPub && (!isTe || isSingleVersion),
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  });

  const hpListQuery = useQuery<HumanPubListResponse>({
    queryKey: ["human-publications-list", baselinesKey, hpLane, queryText, statusFilter, page, pageSize],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        baselines: baselinesKey,
        lane: hpLane,
        q: queryText,
        status: statusFilter,
        page: String(page),
        page_size: String(pageSize),
      });
      return apiRequest<HumanPubListResponse>(`/api/human-publications?${qs.toString()}`, { signal });
    },
    enabled: active && useHumanPub,
    placeholderData: keepPreviousData,
    staleTime: 15_000,
    refetchInterval: active && useHumanPub && !hpPreview ? 15_000 : false,
  });

  const hpHistoryQuery = useQuery<HumanPubHistoryResponse>({
    queryKey: ["human-pub-history", hpHistoryIssue, hpLane, hpHistoryPage, hpHistorySize],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        issue_id: hpHistoryIssue,
        lane: hpLane,
        page: String(hpHistoryPage),
        page_size: String(hpHistorySize),
      });
      return apiRequest<HumanPubHistoryResponse>(`/api/human-publications/history?${qs.toString()}`, {
        signal,
      });
    },
    enabled: active && useHumanPub && Boolean(hpHistoryIssue),
    staleTime: 10_000,
  });

  const operationsQuery = useQuery<{ items?: RdOperationReceipt[] }>({
    queryKey: ["rd-operations", mode],
    queryFn: ({ signal }) =>
      apiRequest<{ items?: RdOperationReceipt[] }>(`/api/rd-results/operations?mode=${mode}`, { signal }),
    enabled: active && !useHumanPub && isAdmin && showOperations,
    staleTime: 10_000,
  });

  const activeOperationQuery = useQuery<RdOperationReceipt>({
    queryKey: ["rd-operation-detail", activeOperationId],
    queryFn: ({ signal }) =>
      apiRequest<RdOperationReceipt>(`/api/rd-results/operations/${encodeURIComponent(activeOperationId || "")}`, {
        signal,
      }),
    enabled: active && !useHumanPub && Boolean(activeOperationId),
    refetchInterval: (query) => {
      const st = query.state.data?.state;
      return st === "preparing" || st === "running" ? 1500 : false;
    },
  });

  const teRefreshMutation = useMutation({
    mutationFn: () =>
      apiRequest("/api/rd-results/te-refresh", {
        method: "POST",
        body: { baselines: baselinesKey },
      }),
    onSuccess: () => {
      showWorkbenchToast(bilingual(lang, "已触发 TE 标签刷新。", "TE label refresh started."));
      void rdListQuery.refetch();
    },
    onError: (err) => setErrorBanner(err instanceof Error ? err.message : "TE refresh failed"),
  });

  const rdPreviewMutation = useMutation({
    mutationFn: async () => {
      if (excelFile && isTe) {
        const form = new FormData();
        form.append("file", excelFile, excelFile.name);
        form.append("baselines", baselinesKey);
        return apiRequest<RdOperationReceipt>("/api/rd-results/te-excel-preview?background=true", {
          method: "POST",
          body: form,
        });
      }
      if (allSelected) {
        return apiRequest<RdOperationReceipt>("/api/rd-results/preview-scope?background=true", {
          method: "POST",
          body: {
            baselines: baselinesKey,
            mode,
            q: queryText,
            status: statusFilter,
            overwrite: true,
            excluded_issue_ids: excludedIds,
          },
        });
      }
      return apiRequest<RdOperationReceipt>("/api/rd-results/preview?background=true", {
        method: "POST",
        body: {
          baselines: baselinesKey,
          mode,
          issue_ids: selectedIds,
          overwrite: true,
        },
      });
    },
    onSuccess: (receipt) => {
      setErrorBanner("");
      setActiveOperationId(receipt.id);
      setPreviewPage(1);
    },
    onError: (err) => setErrorBanner(err instanceof Error ? err.message : "Preview failed"),
  });

  const rdCommitMutation = useMutation({
    mutationFn: (operationId: string) =>
      apiRequest<RdOperationReceipt>("/api/rd-results/commit?background=true", {
        method: "POST",
        body: { operation_id: operationId, confirmed: true },
      }),
    onSuccess: () => {
      void activeOperationQuery.refetch();
      void rdListQuery.refetch();
    },
    onError: (err) => setErrorBanner(err instanceof Error ? err.message : "Commit failed"),
  });

  const hpPreviewMutation = useMutation({
    mutationFn: () =>
      apiRequest<HumanPubPreviewResponse>("/api/human-publications/preview", {
        method: "POST",
        body: { lane: hpLane, baselines: baselinesKey, issue_ids: selectedIds },
      }),
    onSuccess: (res) => {
      setErrorBanner("");
      setHpPreview(res);
    },
    onError: (err) => setErrorBanner(err instanceof Error ? err.message : "Preview failed"),
  });

  const hpCommitMutation = useMutation({
    mutationFn: (requestId: string) =>
      apiRequest("/api/human-publications/commit", {
        method: "POST",
        body: { request_id: requestId, confirmed: true },
      }),
    onSuccess: () => {
      setHpPreview(null);
      setSelectedIds([]);
      showWorkbenchToast(
        bilingual(lang, "已加入同步队列，稍后自动更新状态。", "Queued for synchronization."),
      );
      void hpListQuery.refetch();
    },
    onError: (err) => setErrorBanner(err instanceof Error ? err.message : "Commit failed"),
  });

  const applyFilterSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const raw = searchDraft.trim();
    if (!useHumanPub && raw.split(/[\s,，、;；]+/).filter(Boolean).length > 1) {
      const parsed = parseIssueIdsInput(raw);
      if (parsed.invalid.length || parsed.ids.some((id) => !/^cn\d+$/i.test(id)) || parsed.ids.length > 500) {
        setErrorBanner(bilingual(lang, "请输入最多 500 个有效 Issue ID。", "Enter up to 500 valid Issue IDs."));
        return;
      }
      setErrorBanner("");
      setQueryText(parsed.ids.join(","));
    } else {
      setErrorBanner("");
      setQueryText(raw);
    }
    setPage(1);
  };

  if (!active) return null;

  // Render RD Operation Preview/Outcome subview if active
  if (!useHumanPub && activeOperationId) {
    const op = activeOperationQuery.data;
    const opItems = op?.items || [];
    const resultsMap = new Map((op?.results || []).map((r) => [r.issue_id, r]));
    const eligibleCount = opItems.filter((i) => i.eligible).length;
    const isPreviewState = op?.state === "preview";
    const isRunning = op?.state === "preparing" || op?.state === "running";
    const pagedItems = opItems.slice(
      (previewPage - 1) * previewPageSize,
      previewPage * previewPageSize,
    );

    return (
      <div className="ra-rd-root">
        <section className="page-card runs-source-card rd-preview-overview">
          <div className="runs-source-heading">
            <div>
              <h3>
                {isTe
                  ? bilingual(lang, "TE 修正预览 / 结果", "TE correction preview / outcome")
                  : bilingual(lang, "上传预览 / 结果", "Upload preview / outcome")}
              </h3>
              <p className="rd-description">
                {bilingual(lang, "操作编号：", "Operation ID: ")}
                <code>{activeOperationId}</code> ·{" "}
                <span className={`run-source-badge rd-status ${statusTone(op?.state)}`}>
                  {statusDisplay(op?.state, lang)}
                </span>
              </p>
            </div>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => {
                setActiveOperationId(null);
                void rdListQuery.refetch();
              }}
            >
              {bilingual(lang, "返回选择", "Back to selection")}
            </button>
          </div>
          {errorBanner && (
            <p className="rd-notice is-error" role="alert">
              {errorBanner}
            </p>
          )}
          <div className="rd-preview-summary">
            <div className="rd-preview-total">
              <strong>{eligibleCount}</strong>
              <span>{bilingual(lang, "条可上传", "eligible items")}</span>
            </div>
            <div className="run-manager-actions">
              {isPreviewState && isAdmin && (
                <button
                  type="button"
                  className="button button-primary ra-primary-touch"
                  disabled={
                    eligibleCount === 0 ||
                    !rdListQuery.data?.write_enabled ||
                    rdCommitMutation.isPending
                  }
                  onClick={() => rdCommitMutation.mutate(activeOperationId)}
                >
                  {isTe
                    ? bilingual(lang, `确认修正 TE (${eligibleCount})`, `Confirm TE correction (${eligibleCount})`)
                    : bilingual(lang, `确认上传 (${eligibleCount})`, `Confirm upload (${eligibleCount})`)}
                </button>
              )}
              {!isPreviewState && (
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={activeOperationQuery.isFetching}
                  onClick={() => void activeOperationQuery.refetch()}
                >
                  {bilingual(lang, "刷新本次结果", "Refresh outcome")}
                </button>
              )}
            </div>
          </div>
        </section>

        <section className="page-card runs-page-card rd-preview-details">
          <div className="rd-table-wrap ra-table-scroll">
            <table className="rd-table">
              <thead>
                <tr>
                  <th>Issue</th>
                  <th>{bilingual(lang, "Trail 原值", "Current Trail")}</th>
                  <th>{bilingual(lang, "目标值", "Target value")}</th>
                  {!isPreviewState && <th>{bilingual(lang, "读回值", "Readback")}</th>}
                  <th>{bilingual(lang, "状态", "Status")}</th>
                </tr>
              </thead>
              <tbody>
                {pagedItems.map((row) => {
                  const res = resultsMap.get(row.issue_id);
                  return (
                    <tr key={row.issue_id}>
                      <td>{row.issue_id}</td>
                      <td>
                        <span className={labelBadgeClass(row.current)}>
                          {displayLabelText(row.current, lang)}
                        </span>
                      </td>
                      <td>
                        <span className={labelBadgeClass(row.desired)}>
                          {displayLabelText(row.desired, lang)}
                        </span>
                      </td>
                      {!isPreviewState && (
                        <td>
                          <span className={labelBadgeClass(res?.observed)}>
                            {displayLabelText(res?.observed, lang)}
                          </span>
                        </td>
                      )}
                      <td>
                        <span
                          className={`run-source-badge rd-status ${statusTone(res?.phase || res?.state || row.status)}`}
                        >
                          {statusDisplay(res?.phase || res?.state || row.status, lang)}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pagination
            page={previewPage}
            pageSize={previewPageSize}
            total={opItems.length}
            lang={lang}
            loading={isRunning}
            onPageChange={setPreviewPage}
            onPageSizeChange={(s) => {
              setPreviewPageSize(s);
              setPreviewPage(1);
            }}
          />
        </section>
      </div>
    );
  }

  // Human Publications view (>= 20261106 version scopes, non-TE-correction)
  if (useHumanPub) {
    const data = hpListQuery.data;
    const rows = data?.items || [];
    const counts = data?.counts || {};
    const totalInScope = Object.entries(counts).reduce(
      (sum, [k, v]) => sum + (k === "objection" ? 0 : Number(v || 0)),
      0,
    );
    const isDecisionLane = hpLane === "arbitrated";
    const fieldName =
      data?.field ||
      (hpLane === "te"
        ? "ra_review_result_sampling"
        : hpLane === "arbitrated"
          ? "ra_review_result_arbitrated"
          : "ra_rd_review_result");

    const hpStatusOptions = [
      "all",
      "resolved",
      "pending",
      "conflict",
      "objection",
      "stale",
      "none",
      "unassigned",
      "inactive",
      "unclassified",
    ].map((val) => ({
      value: val,
      label: val === "all" ? bilingual(lang, "全部状态", "All statuses") : statusDisplay(val, lang),
    }));

    const selectionOptions = [
      { value: "", label: bilingual(lang, "选中操作", "Selection actions"), disabled: true },
      { value: "page", label: bilingual(lang, "选择本页", "Select this page"), disabled: rows.length === 0 },
      { value: "clear", label: bilingual(lang, "清空选择", "Clear selection"), disabled: selectedIds.length === 0 },
    ];

    return (
      <div className="ra-rd-root human-publications-page">
        <section className="page-card runs-source-card rd-overview">
          <div className="runs-source-heading rd-mode-header">
            <div className="rd-mode-tabs" role="tablist" aria-label={bilingual(lang, "标注上传类型", "Publication type")}>
              {(
                [
                  ["rd", "RD 标注", "RD labels"],
                  ["te", "TE′ 标注", "TE′ labels"],
                  ["arbitrated", "裁决标注", "Adjudication"],
                ] as const
              ).map(([laneKey, zh, en]) => (
                <button
                  key={laneKey}
                  type="button"
                  role="tab"
                  className="button button-secondary rd-mode-tab"
                  aria-selected={hpLane === laneKey}
                  onClick={() => {
                    setHpLane(laneKey);
                    setStatusFilter("all");
                    setPage(1);
                    setHpHistoryIssue("");
                  }}
                >
                  {bilingual(lang, zh, en)}
                </button>
              ))}
              {isSingleVersion && (
                <button
                  type="button"
                  role="tab"
                  className="button button-quiet rd-mode-tab"
                  aria-selected={false}
                  onClick={() => {
                    setMode("te-correction");
                    setStatusFilter("all");
                    setPage(1);
                  }}
                >
                  {bilingual(lang, "TE 修正", "TE correction")}
                </button>
              )}
            </div>
            <div className="run-manager-actions">
              <button
                type="button"
                className="button button-quiet"
                disabled={hpListQuery.isFetching}
                onClick={() => void hpListQuery.refetch()}
              >
                {bilingual(lang, "刷新", "Refresh")}
              </button>
            </div>
          </div>

          <div className="run-source-tabs rd-metrics">
            {(
              [
                ["all", totalInScope, "范围内 Issues", "Issues in scope"],
                [
                  "resolved",
                  counts.resolved ?? 0,
                  isDecisionLane ? "已裁决" : "已完成",
                  isDecisionLane ? "Adjudicated" : "Completed",
                ],
                [
                  isDecisionLane ? "none" : "pending",
                  isDecisionLane ? (counts.none ?? 0) : (counts.pending ?? 0),
                  isDecisionLane ? "待裁决" : "待标注",
                  isDecisionLane ? "Pending decision" : "Pending labels",
                ],
                [
                  isDecisionLane ? "stale" : "conflict",
                  isDecisionLane ? (counts.stale ?? 0) : (counts.conflict ?? 0),
                  "需复核",
                  "Needs review",
                ],
              ] as const
            ).map(([filterKey, countVal, zh, en]) => (
              <button
                key={filterKey}
                type="button"
                className={`run-source-tab rd-metric${statusFilter === filterKey ? " active" : ""}`}
                aria-pressed={statusFilter === filterKey}
                onClick={() => {
                  setStatusFilter(filterKey);
                  setPage(1);
                }}
              >
                <span>
                  <strong>{bilingual(lang, zh, en)}</strong>
                </span>
                <em>{data ? countVal : "—"}</em>
              </button>
            ))}
          </div>

          <dl className="rd-upload-target">
            <div>
              <dt>{bilingual(lang, "上传接口", "Upload endpoint")}</dt>
              <dd>
                <span className="rd-http-method">POST</span> <code>{RD_UPLOAD_ENDPOINT}</code>
              </dd>
            </div>
            <div>
              <dt>{bilingual(lang, "目标字段", "Target field")}</dt>
              <dd>
                <code>{fieldName}</code>
              </dd>
            </div>
          </dl>
        </section>

        <section className="page-card runs-page-card rd-workspace">
          <div className="rd-detail-toolbar">
            <h3>{bilingual(lang, "标注明细", "Label details")}</h3>
            <form className="run-filter-bar rd-filters" onSubmit={applyFilterSubmit}>
              <input
                type="search"
                value={searchDraft}
                onChange={(e) => setSearchDraft(e.target.value)}
                placeholder={bilingual(lang, "搜索 Issue ID", "Find Issue ID")}
                aria-label={bilingual(lang, "搜索 Issue ID", "Find Issue ID")}
              />
              <UiSelect
                value={statusFilter}
                options={hpStatusOptions}
                ariaLabel={bilingual(lang, "结论筛选", "Conclusion filter")}
                onChange={(v) => {
                  setStatusFilter(v);
                  setPage(1);
                }}
              />
              <button type="submit" className="button button-secondary">
                {bilingual(lang, "筛选", "Apply")}
              </button>
            </form>
          </div>

          {(errorBanner || hpListQuery.isError) && (
            <p className="rd-notice is-error" role="alert">
              {errorBanner || bilingual(lang, "加载失败，请刷新重试。", "Failed to load. Refresh to retry.")}
            </p>
          )}

          <div className={`rd-selection-bar${selectedIds.length ? " has-selection" : ""}`}>
            <div className="rd-selection-tools">
              <div className="run-manager-actions">
                <UiSelect
                  value=""
                  options={selectionOptions}
                  ariaLabel={bilingual(lang, "选中操作", "Selection actions")}
                  onChange={(val) => {
                    if (val === "page") setSelectedIds(rows.map((r) => r.issue_id));
                    else if (val === "clear") setSelectedIds([]);
                  }}
                />
                <span className="rd-selection-count" role="status">
                  {selectedIds.length
                    ? bilingual(lang, `已选 ${selectedIds.length} 条`, `Selected ${selectedIds.length}`)
                    : bilingual(lang, "请选择标注", "Select labels to preview")}
                </span>
              </div>
            </div>
            <div className="run-manager-actions">
              {data && !data.write_enabled && (
                <span className="rd-notice">{bilingual(lang, "写入未启用", "Publishing disabled")}</span>
              )}
              {isAdmin && (
                <button
                  type="button"
                  className="button button-primary"
                  disabled={selectedIds.length === 0 || hpPreviewMutation.isPending}
                  onClick={() => hpPreviewMutation.mutate()}
                >
                  {bilingual(lang, "预览上传", "Preview upload")}
                </button>
              )}
            </div>
          </div>

          <div className="rd-table-wrap ra-table-scroll">
            <table className="rd-table human-publication-table">
              <thead>
                <tr>
                  <th />
                  <th>Issue</th>
                  <th>{bilingual(lang, "人工结论", "Human label")}</th>
                  <th>{bilingual(lang, "标注人", "Contributors")}</th>
                  <th>{bilingual(lang, "同步状态", "Sync status")}</th>
                  <th>{bilingual(lang, "记录", "History")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const checked = selectedIds.includes(row.issue_id);
                  const issueHref = `${withWorkbenchBase("/case-labeling")}?issue=${encodeURIComponent(row.issue_id)}${baselinesKey ? `&baselines=${encodeURIComponent(baselinesKey)}` : ""}`;
                  return (
                    <tr key={row.issue_id} className={checked ? "is-selected" : ""}>
                      <td>
                        <label className="rd-checkbox">
                          <input
                            type="checkbox"
                            className="ui-checkbox"
                            checked={checked}
                            aria-label={`${bilingual(lang, "选择", "Select")} ${row.issue_id}`}
                            onChange={(e) => {
                              setSelectedIds((prev) =>
                                e.target.checked
                                  ? [...prev, row.issue_id]
                                  : prev.filter((id) => id !== row.issue_id),
                              );
                            }}
                          />
                        </label>
                      </td>
                      <td>
                        <a className="rd-issue-link" href={issueHref}>
                          {row.issue_id}
                        </a>
                      </td>
                      <td>
                        {row.conclusion === "resolved" && row.label ? (
                          <span className={labelBadgeClass(row.label)}>
                            {displayLabelText(row.label, lang)}
                          </span>
                        ) : (
                          <span className={`run-source-badge rd-status ${statusTone(row.conclusion)}`}>
                            {statusDisplay(row.conclusion, lang)}
                          </span>
                        )}
                      </td>
                      <td>
                        {(row.authors || []).join(", ") || "—"}
                        {row.required > 1 && (
                          <span className="muted">
                            {" "}
                            ({row.submitted}/{row.required})
                          </span>
                        )}
                      </td>
                      <td>
                        <span
                          className={`run-source-badge rd-status ${statusTone(row.publication_armed === 0 ? "awaiting_activation" : row.sync_state)}`}
                        >
                          {statusDisplay(
                            row.publication_armed === 0 ? "awaiting_activation" : row.sync_state,
                            lang,
                          )}
                        </span>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="button button-quiet"
                          onClick={() => {
                            setHpHistoryIssue(row.issue_id);
                            setHpHistoryPage(1);
                          }}
                        >
                          {row.objections?.length
                            ? bilingual(lang, `异议 ${row.objections.length}`, `${row.objections.length} obj.`)
                            : bilingual(lang, "查看", "View")}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {!hpListQuery.isPending && rows.length === 0 && (
            <div className="rd-empty">
              {bilingual(lang, "当前范围暂无正式标注记录。", "No formal label records in this scope.")}
            </div>
          )}

          <Pagination
            page={page}
            pageSize={pageSize}
            total={data?.total || 0}
            lang={lang}
            loading={hpListQuery.isFetching}
            onPageChange={setPage}
            onPageSizeChange={(s) => {
              setPageSize(s);
              setPage(1);
            }}
          />
        </section>

        {hpPreview && (
          <section className="page-card rd-workspace">
            <h3>{bilingual(lang, "本次将排队处理", "Queue preview")}</h3>
            <ul className="ra-hp-preview-list">
              {hpPreview.items.map((item) => (
                <li key={item.issue_id}>
                  <strong>{item.issue_id}</strong> · {statusDisplay(item.action, lang)} ·{" "}
                  {item.desired ? displayLabelText(item.desired, lang) : bilingual(lang, "无有效结果", "None")}
                </li>
              ))}
            </ul>
            <div className="run-manager-actions">
              <button
                type="button"
                className="button button-primary"
                disabled={
                  !data?.write_enabled ||
                  !hpPreview.items.some((i) => i.eligible) ||
                  hpCommitMutation.isPending
                }
                onClick={() => hpCommitMutation.mutate(hpPreview.id)}
              >
                {bilingual(lang, "确认加入队列", "Confirm queue")}
              </button>
              <button type="button" className="button button-secondary" onClick={() => setHpPreview(null)}>
                {bilingual(lang, "关闭预览", "Close preview")}
              </button>
            </div>
          </section>
        )}

        {hpHistoryIssue && (
          <section className="page-card rd-workspace rd-preview-details">
            <div className="runs-toolbar">
              <h3>
                {hpHistoryIssue} · {bilingual(lang, "上传记录", "Publication history")}
              </h3>
              <button type="button" className="button button-quiet" onClick={() => setHpHistoryIssue("")}>
                {bilingual(lang, "关闭记录", "Close history")}
              </button>
            </div>
            {hpHistoryQuery.data?.items?.length ? (
              <div className="rd-table-wrap ra-table-scroll">
                <table className="rd-table">
                  <tbody>
                    {hpHistoryQuery.data.items.map((h, idx) => (
                      <tr key={idx}>
                        <td>{formatCstTime(h.created_at, lang)}</td>
                        <td>{statusDisplay(h.action, lang)}</td>
                        <td>{h.desired ? displayLabelText(h.desired, lang) : "NULL"}</td>
                        <td>
                          <span className={`run-source-badge rd-status ${statusTone(h.state)}`}>
                            {statusDisplay(h.state, lang)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="rd-description">{bilingual(lang, "暂无上传尝试。", "No publication attempts yet.")}</p>
            )}
            <Pagination
              page={hpHistoryPage}
              pageSize={hpHistorySize}
              total={hpHistoryQuery.data?.total || 0}
              lang={lang}
              loading={hpHistoryQuery.isFetching}
              onPageChange={setHpHistoryPage}
              onPageSizeChange={(s) => {
                setHpHistorySize(s);
                setHpHistoryPage(1);
              }}
            />
          </section>
        )}
      </div>
    );
  }

  // Classic RD Upload / TE Correction view
  const data = rdListQuery.data;
  const rows = data?.items || [];
  const counts = data?.counts || {};
  const scopeResolvedCount = ["all", "resolved"].includes(statusFilter) ? Number(counts.resolved || 0) : 0;
  const selectedCount = allSelected
    ? Math.max(0, scopeResolvedCount - excludedIds.length)
    : selectedIds.length;
  const isRowSelected = (row: RdRow) =>
    row.group === "resolved" &&
    (allSelected ? !excludedIds.includes(row.issue_id) : selectedIds.includes(row.issue_id));

  const statusOptions = isTe
    ? [
        { value: "all", label: bilingual(lang, "全部状态", "All statuses") },
        { value: "resolved", label: bilingual(lang, "待修正候选", "Correction candidates") },
        { value: "same", label: bilingual(lang, "已一致", "Already matches") },
        { value: "blocked", label: bilingual(lang, "暂不可修正", "Unavailable") },
      ]
    : [
        { value: "all", label: bilingual(lang, "全部状态", "All statuses") },
        { value: "resolved", label: bilingual(lang, "已完成", "Completed") },
        { value: "pending", label: bilingual(lang, "待标注", "Pending labels") },
        { value: "conflict", label: bilingual(lang, "冲突 / 失效", "Conflict / stale") },
      ];

  const selectionOptions = [
    { value: "", label: bilingual(lang, "选中操作", "Selection actions"), disabled: true },
    {
      value: "page",
      label: bilingual(lang, "选择本页", "Select this page"),
      disabled: !rows.some((r) => r.group === "resolved"),
    },
    {
      value: "all",
      label: bilingual(lang, `选择全部 ${scopeResolvedCount} 条`, `Select all ${scopeResolvedCount}`),
      disabled: scopeResolvedCount === 0,
    },
    {
      value: "clear",
      label: bilingual(lang, "清空选择", "Clear selection"),
      disabled: selectedCount === 0,
    },
  ];

  const metrics = isTe
    ? ([
        ["all", "total", "范围内 Issues", "Issues in scope"],
        ["resolved", "resolved", "待修正候选", "Correction candidates"],
        ["same", "same", "已一致", "Already matches"],
        ["blocked", "blocked", "暂不可修正", "Unavailable"],
      ] as const)
    : ([
        ["all", "total", "范围内 Issues", "Issues in scope"],
        ["resolved", "resolved", "已完成", "Completed"],
        ["pending", "pending", "待标注", "Pending labels"],
        ["conflict", "conflict", "需复核", "Needs review"],
      ] as const);

  return (
    <div className={`ra-rd-root${isTe ? " is-te-correction" : ""}`}>
      <section className="page-card runs-source-card rd-overview">
        <div className="runs-source-heading rd-mode-header">
          <div className="rd-mode-tabs" role="tablist" aria-label={bilingual(lang, "标注上传类型", "Publication type")}>
            <button
              type="button"
              role="tab"
              className="button button-secondary rd-mode-tab"
              aria-selected={mode === "rd"}
              onClick={() => {
                setMode("rd");
                setStatusFilter("all");
                setPage(1);
                setExcelFile(null);
              }}
            >
              {bilingual(lang, "RD 标注上传", "RD label upload")}
            </button>
            <button
              type="button"
              role="tab"
              className="button button-secondary rd-mode-tab"
              aria-selected={mode === "te-correction"}
              onClick={() => {
                setMode("te-correction");
                setStatusFilter("all");
                setPage(1);
              }}
            >
              {bilingual(lang, "TE 标注修正", "TE label correction")}
            </button>
          </div>
          <div className="run-manager-actions">
            <button
              type="button"
              className="button button-quiet"
              disabled={rdListQuery.isFetching}
              onClick={() => void rdListQuery.refetch()}
            >
              {bilingual(lang, "刷新", "Refresh")}
            </button>
          </div>
        </div>

        <div className="run-source-tabs rd-metrics">
          {metrics.map(([filterKey, countKey, zh, en]) => (
            <button
              key={filterKey}
              type="button"
              className={`run-source-tab rd-metric${statusFilter === filterKey ? " active" : ""}`}
              aria-pressed={statusFilter === filterKey}
              onClick={() => {
                setStatusFilter(filterKey);
                setPage(1);
              }}
            >
              <span>
                <strong>{bilingual(lang, zh, en)}</strong>
              </span>
              <em>{data ? (counts[countKey] ?? 0) : "—"}</em>
            </button>
          ))}
        </div>

        <dl className="rd-upload-target">
          <div>
            <dt>{bilingual(lang, "上传接口", "Upload endpoint")}</dt>
            <dd>
              <span className="rd-http-method">POST</span> <code>{RD_UPLOAD_ENDPOINT}</code>
            </dd>
          </div>
          <div>
            <dt>{bilingual(lang, "目标字段", "Target field")}</dt>
            <dd>
              <code>{isTe ? "ra_review_result_new" : "ra_rd_review_result"}</code>
            </dd>
          </div>
        </dl>
      </section>

      <section className="page-card runs-page-card rd-workspace">
        <div className="rd-detail-toolbar">
          <div className="rd-detail-heading">
            <h3>{bilingual(lang, "标注明细", "Label details")}</h3>
            {isTe && (
              <div className="run-manager-actions">
                <button
                  type="button"
                  className="button button-quiet"
                  disabled={!isSingleVersion || teRefreshMutation.isPending}
                  onClick={() => teRefreshMutation.mutate()}
                >
                  {bilingual(lang, "刷新 TE 标签", "Refresh TE labels")}
                </button>
                {isAdmin && (
                  <>
                    <button
                      type="button"
                      className="button button-quiet"
                      disabled={!isSingleVersion}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      {bilingual(lang, "导入 XLSX", "Import XLSX")}
                    </button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".xlsx"
                      className="hidden"
                      onChange={(e) => {
                        const file = e.target.files?.[0] || null;
                        setExcelFile(file);
                        e.target.value = "";
                      }}
                    />
                  </>
                )}
              </div>
            )}
          </div>

          <form className="run-filter-bar rd-filters" onSubmit={applyFilterSubmit}>
            <textarea
              rows={1}
              maxLength={8000}
              value={searchDraft}
              onChange={(e) => setSearchDraft(e.target.value)}
              placeholder={bilingual(lang, "粘贴 Issue ID，可多个", "Paste Issue IDs")}
              aria-label={bilingual(lang, "Issue 搜索", "Search Issues")}
            />
            <UiSelect
              value={statusFilter}
              options={statusOptions}
              ariaLabel={bilingual(lang, "标注状态", "Label status")}
              onChange={(v) => {
                setStatusFilter(v);
                setPage(1);
              }}
            />
            <button type="submit" className="button button-secondary">
              {bilingual(lang, "筛选", "Apply")}
            </button>
          </form>
        </div>

        {isTe && !isSingleVersion && (
          <p className="rd-notice is-error" role="status">
            {bilingual(lang, "TE 修正请选择一个版本数据集。", "Select one version dataset for TE correction.")}
          </p>
        )}

        {errorBanner && (
          <p className="rd-notice is-error" role="alert">
            {errorBanner}
          </p>
        )}

        <div className={`rd-selection-bar${selectedCount > 0 ? " has-selection" : ""}`}>
          <div className="rd-selection-tools">
            <div className="run-manager-actions">
              <UiSelect
                value=""
                options={selectionOptions}
                disabled={Boolean(excelFile)}
                ariaLabel={bilingual(lang, "选中操作", "Selection actions")}
                onChange={(action) => {
                  setSelectedIds([]);
                  setExcludedIds([]);
                  setAllSelected(false);
                  if (action === "page") {
                    setSelectedIds(rows.filter((r) => r.group === "resolved").map((r) => r.issue_id));
                  } else if (action === "all") {
                    setAllSelected(true);
                  }
                }}
              />
              <span className="rd-selection-count" role="status">
                {excelFile ? (
                  <>
                    {bilingual(lang, "XLSX 期望输出：", "XLSX targets: ")} {excelFile.name}{" "}
                    <button
                      type="button"
                      className="button button-quiet"
                      onClick={() => setExcelFile(null)}
                    >
                      {bilingual(lang, "清除文件", "Clear")}
                    </button>
                  </>
                ) : selectedCount > 0 ? (
                  bilingual(
                    lang,
                    `已选 ${selectedCount} 条${allSelected ? " · 跨全部页" : ""}`,
                    `Selected ${selectedCount}${allSelected ? " · across all pages" : ""}`,
                  )
                ) : (
                  bilingual(lang, "请选择标注", "Select labels to preview")
                )}
              </span>
            </div>
          </div>
          <div className="run-manager-actions">
            {data && !data.write_enabled && (
              <span className="rd-notice">{bilingual(lang, "写入未启用", "Publishing disabled")}</span>
            )}
            {isAdmin && (
              <button
                type="button"
                className="button button-primary"
                disabled={(!excelFile && selectedCount === 0) || rdPreviewMutation.isPending}
                onClick={() => rdPreviewMutation.mutate()}
              >
                {excelFile
                  ? bilingual(lang, "预览文件", "Preview file")
                  : bilingual(lang, "预览上传", "Preview upload")}
              </button>
            )}
          </div>
        </div>

        <div className="rd-table-wrap ra-table-scroll">
          <table className="rd-table">
            <thead>
              <tr>
                <th />
                <th>Issue</th>
                {isTe && <th>{bilingual(lang, "当前 TE（观测）", "Current TE")}</th>}
                <th>{bilingual(lang, isTe ? "RD 人工结论" : "人工结论", isTe ? "RD human label" : "Human label")}</th>
                {isTe && <th>{bilingual(lang, "修正状态", "Correction status")}</th>}
                <th>{bilingual(lang, "标注人", "Contributors")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const eligible = row.group === "resolved";
                const checked = isRowSelected(row);
                const issueHref = `${withWorkbenchBase("/case-labeling")}?issue=${encodeURIComponent(row.issue_id)}${baselinesKey ? `&baselines=${encodeURIComponent(baselinesKey)}` : ""}`;
                return (
                  <tr key={row.issue_id} className={checked ? "is-selected" : ""}>
                    <td>
                      <label className="rd-checkbox">
                        <input
                          type="checkbox"
                          className="ui-checkbox"
                          checked={checked}
                          disabled={!eligible || Boolean(excelFile)}
                          aria-label={`${bilingual(lang, "选择", "Select")} ${row.issue_id}`}
                          onChange={(e) => {
                            if (allSelected) {
                              setExcludedIds((prev) =>
                                e.target.checked
                                  ? prev.filter((id) => id !== row.issue_id)
                                  : [...prev, row.issue_id],
                              );
                            } else {
                              setSelectedIds((prev) =>
                                e.target.checked
                                  ? [...prev, row.issue_id]
                                  : prev.filter((id) => id !== row.issue_id),
                              );
                            }
                          }}
                        />
                      </label>
                    </td>
                    <td>
                      <a className="rd-issue-link" href={issueHref}>
                        {row.issue_id}
                      </a>
                    </td>
                    {isTe && (
                      <td>
                        <span className={labelBadgeClass(row.te_current)}>
                          {displayLabelText(row.te_current, lang)}
                        </span>
                      </td>
                    )}
                    <td>
                      {(isTe ? row.state === "resolved" : row.group === "resolved") ? (
                        <span className={labelBadgeClass(row.label)}>
                          {displayLabelText(row.label, lang)}
                        </span>
                      ) : (
                        <span className="muted">{statusDisplay(row.state || row.group, lang)}</span>
                      )}
                    </td>
                    {isTe && (
                      <td>
                        <span className={`run-source-badge rd-status ${statusTone(row.correction_status)}`}>
                          {statusDisplay(row.correction_status, lang)}
                        </span>
                      </td>
                    )}
                    <td>{(row.authors || []).join(", ") || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {!rdListQuery.isPending && rows.length === 0 && (
          <div className="rd-empty">
            <strong>{bilingual(lang, "当前范围没有标注结果", "No labels in this scope")}</strong>
          </div>
        )}

        <Pagination
          page={page}
          pageSize={pageSize}
          total={data?.total || 0}
          lang={lang}
          loading={rdListQuery.isFetching}
          onPageChange={setPage}
          onPageSizeChange={(s) => {
            setPageSize(s);
            setPage(1);
          }}
        />
      </section>

      {isAdmin && (
        <section className="page-card job-history-card">
          <div className="runs-toolbar">
            <h3>{bilingual(lang, "上传记录", "Publication history")}</h3>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                setShowOperations(true);
                void queryClient.invalidateQueries({ queryKey: ["rd-operations", mode] });
              }}
            >
              {bilingual(lang, "查看最近记录", "Show recent operations")}
            </button>
          </div>
          {showOperations && (
            <div className="job-history-list">
              {(operationsQuery.data?.items || []).map((op) => (
                <div key={op.id} className="job-history-row">
                  <div className="job-history-main">
                    <strong>{op.actor || "admin"}</strong>
                    <span className="muted">{op.id.slice(0, 12)}</span>
                  </div>
                  <div className="run-manager-actions">
                    <span className={`run-source-badge rd-status ${statusTone(op.state)}`}>
                      {statusDisplay(op.state, lang)}
                    </span>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => setActiveOperationId(op.id)}
                    >
                      {bilingual(lang, "查看详情", "View details")}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
};
