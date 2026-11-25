import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import {
  CASE_PAGE_SIZES,
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

interface TrailHistoryRow {
  id: string;
  created_at?: string | null;
  actor?: string | null;
  actor_verified?: boolean;
  source: string;
  status: string;
  succeeded_count: number;
  item_count: number;
}

interface TrailHistoryListResponse {
  items: TrailHistoryRow[];
  total: number;
  page: number;
  page_size: number;
  started_at?: string | null;
  can_restore?: boolean;
}

interface TrailHistoryDiffItem {
  issue_id: string;
  field?: string;
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
  current?: Record<string, unknown>;
  restore?: Record<string, unknown>;
}

interface TrailHistoryEvent {
  status: string;
  created_at?: string | null;
  actor?: string | null;
  outcomes: Record<string, string>;
}

interface TrailHistoryChildRef {
  id: string;
  created_at?: string | null;
  actor?: string | null;
}

interface TrailHistoryDetail {
  id: string;
  source: string;
  status: string;
  actor?: string | null;
  created_at?: string | null;
  reason?: string | null;
  parent_id?: string | null;
  children: TrailHistoryChildRef[];
  items: TrailHistoryDiffItem[];
  outcomes: Record<string, string>;
  events: TrailHistoryEvent[];
  restorable?: boolean;
  restorable_issue_ids?: string[];
  current_conflicts?: string[];
}

interface TrailRestorePreview {
  preview_id: string;
  ready: boolean;
  conflicts: string[];
  items: TrailHistoryDiffItem[];
}

interface TrailHistoryFilters {
  issue_id: string;
  actor: string;
  source: string;
  status: string;
  since: string;
  until: string;
}

interface LegacyWindow {
  showToast?: (msg: string, isError?: boolean) => void;
}

const SOURCE_KEYS = [
  "exclusion_summary",
  "exclusion_direct",
  "model_label_normalization",
  "model_publication",
  "model_label_restore",
  "rd_upload",
  "te_correction",
  "rollback",
  "legacy",
] as const;

const STATUS_KEYS = ["pending", "succeeded", "partial", "unknown", "conflict"] as const;

function getLegacyWindow(): LegacyWindow {
  return window as unknown as LegacyWindow;
}

function sourceLabel(value: string, lang: UiLanguage): string {
  const labels: Record<string, [string, string]> = {
    exclusion_summary: ["问题排除 · 汇总", "Issue exclusion · Summary"],
    exclusion_direct: ["问题排除 · Issue ID", "Issue exclusion · Issue ID"],
    model_label_normalization: ["模型枚举修正", "Model enum correction"],
    model_publication: ["Cron 模型发布", "Cron model publication"],
    model_label_restore: ["模型字段恢复", "Model field restore"],
    rd_upload: ["RD 标注上传", "RD label upload"],
    te_correction: ["TE 标注修正", "TE label correction"],
    rollback: ["恢复操作", "Restore"],
    legacy: ["旧版历史", "Legacy history"],
  };
  const pair = labels[value];
  return pair ? bilingual(lang, pair[0], pair[1]) : value;
}

function statusLabel(value: string, lang: UiLanguage, source = ""): string {
  if (source === "legacy" && value === "succeeded") {
    return bilingual(lang, "旧记录成功", "Legacy success");
  }
  const labels: Record<string, [string, string]> = {
    pending: ["待核验", "Pending verification"],
    succeeded: ["已回读成功", "Readback verified"],
    not_attempted: ["未执行", "Not attempted"],
    partial: ["部分成功", "Partial"],
    unknown: ["结果待核验", "Outcome unknown"],
    conflict: ["存在冲突", "Conflict"],
  };
  const pair = labels[value];
  return pair ? bilingual(lang, pair[0], pair[1]) : bilingual(lang, "未知", "Unknown");
}

function formatHistoryTime(value: string | null | undefined, lang: UiLanguage): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(lang === "en" ? "en-GB" : "zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function isoToLocalInput(value: string): string {
  if (!value || Number.isNaN(Date.parse(value))) return "";
  return new Date(Date.parse(value) + 8 * 3600_000).toISOString().slice(0, 16);
}

function localInputToIso(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  const parsed = new Date(`${trimmed}:00+08:00`);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString();
}

function labelFieldName(field: string | undefined, lang: UiLanguage): string {
  if (field === "ra_stuck_auto_result") return bilingual(lang, "模型主字段", "Model result");
  if (field === "ra_review_result_new") return bilingual(lang, "TE 标注", "TE label");
  if (field === "ra_rd_review_result") return bilingual(lang, "RD 标注", "RD label");
  return "";
}

function formatFieldValue(
  obj: Record<string, unknown> | undefined,
  key: string,
  lang: UiLanguage,
): string {
  if (!obj || !Object.prototype.hasOwnProperty.call(obj, key)) {
    return bilingual(lang, "字段不存在", "Field absent");
  }
  const value = obj[key];
  if (key === "value" && typeof value === "string") {
    const labels: Record<string, [string, string]> = {
      成功: ["正确触发", "Correct trigger"],
      正确触发: ["正确触发", "Correct trigger"],
      误触发: ["误触发", "False trigger"],
      无需协助: ["无需协助", "No assistance needed"],
    };
    if (labels[value]) return bilingual(lang, labels[value][0], labels[value][1]);
  }
  if (value === null) return "null";
  if (typeof value === "string") return value || bilingual(lang, "空字符串", "Empty string");
  return JSON.stringify(value);
}

function formatLabelItemValue(
  item: TrailHistoryDiffItem,
  key: "before" | "after" | "current" | "restore",
  lang: UiLanguage,
): string {
  const obj = item[key] || {};
  if (item.field !== "ra_stuck_auto_result") return formatFieldValue(obj, "value", lang);
  if (obj.present === false || !Object.prototype.hasOwnProperty.call(obj, "value")) {
    return bilingual(lang, "字段不存在", "Field absent");
  }
  const val = obj.value;
  if (val === null) return "null";
  if (typeof val === "string") return val || bilingual(lang, "空字符串", "Empty string");
  return JSON.stringify(val);
}

function parseRouteFromLocation() {
  const params = new URLSearchParams(window.location.search);
  const rawPage = Number(params.get("page") || 1);
  const rawSize = Number(params.get("page_size") || DEFAULT_CASE_PAGE_SIZE);
  return {
    filters: {
      issue_id: params.get("issue_id") || "",
      actor: params.get("actor") || "",
      source: params.get("source") || "",
      status: params.get("status") || "",
      since: params.get("since") || "",
      until: params.get("until") || "",
    } as TrailHistoryFilters,
    page: Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1,
    pageSize: (CASE_PAGE_SIZES as readonly number[]).includes(rawSize)
      ? rawSize
      : DEFAULT_CASE_PAGE_SIZE,
    operation: params.get("operation") || "",
  };
}

const StatusBadge: React.FC<{ status: string; source?: string; lang: UiLanguage }> = ({
  status,
  source = "",
  lang,
}) => {
  const symbols: Record<string, string> = {
    succeeded: "✓",
    partial: "◐",
    pending: "○",
    unknown: "?",
    conflict: "!",
  };
  return (
    <span className="trail-history-status" data-status={status}>
      <span aria-hidden="true">{symbols[status] || "?"}</span>{" "}
      {statusLabel(status, lang, source)}
    </span>
  );
};

export interface TrailHistoryPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
}

export const TrailHistoryPage: React.FC<TrailHistoryPageProps> = ({
  active,
  lang,
  selectedBaselines,
}) => {
  const queryClient = useQueryClient();
  const baselinesParam = selectedBaselines.join(",");
  const initial = useMemo(() => parseRouteFromLocation(), []);

  const [filters, setFilters] = useState<TrailHistoryFilters>(initial.filters);
  const [draft, setDraft] = useState<{
    issue_id: string;
    actor: string;
    source: string;
    status: string;
    sinceLocal: string;
    untilLocal: string;
  }>(() => ({
    issue_id: initial.filters.issue_id,
    actor: initial.filters.actor,
    source: initial.filters.source,
    status: initial.filters.status,
    sinceLocal: isoToLocalInput(initial.filters.since),
    untilLocal: isoToLocalInput(initial.filters.until),
  }));
  const [page, setPage] = useState<number>(initial.page);
  const [pageSize, setPageSize] = useState<number>(initial.pageSize);
  const [operationId, setOperationId] = useState<string>(initial.operation);

  // Dialog restore state
  const [detailOverride, setDetailOverride] = useState<TrailHistoryDetail | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [selectedIssues, setSelectedIssues] = useState<string[]>([]);
  const [restoreReason, setRestoreReason] = useState("");
  const [restorePreview, setRestorePreview] = useState<TrailRestorePreview | null>(null);
  const [busy, setBusy] = useState(false);

  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const dialogBodyRef = useRef<HTMLDivElement | null>(null);
  const restoreResultRef = useRef<HTMLDivElement | null>(null);

  const syncUrl = useCallback(
    (next: {
      filters?: TrailHistoryFilters;
      page?: number;
      pageSize?: number;
      operation?: string;
    }) => {
      if (!active) return;
      const f = next.filters ?? filters;
      const p = next.page ?? page;
      const ps = next.pageSize ?? pageSize;
      const op = next.operation ?? operationId;
      const url = new URL(withWorkbenchBase("/trail-update-history"), window.location.origin);
      if (baselinesParam) url.searchParams.set("baselines", baselinesParam);
      if (f.issue_id) url.searchParams.set("issue_id", f.issue_id);
      if (f.actor) url.searchParams.set("actor", f.actor);
      if (f.source) url.searchParams.set("source", f.source);
      if (f.status) url.searchParams.set("status", f.status);
      if (f.since) url.searchParams.set("since", f.since);
      if (f.until) url.searchParams.set("until", f.until);
      if (p > 1) url.searchParams.set("page", String(p));
      if (ps !== DEFAULT_CASE_PAGE_SIZE) url.searchParams.set("page_size", String(ps));
      if (op) url.searchParams.set("operation", op);
      const target = `${url.pathname}${url.search}`;
      if (`${window.location.pathname}${window.location.search}` !== target) {
        window.history.replaceState(
          { ...(window.history.state || {}), page: "trail-history" },
          "",
          target,
        );
      }
    },
    [active, baselinesParam, filters, page, pageSize, operationId],
  );

  // Sync from URL when entering page or on popstate
  useEffect(() => {
    if (!active) return;
    const syncFromLoc = () => {
      const parsed = parseRouteFromLocation();
      setFilters(parsed.filters);
      setDraft({
        issue_id: parsed.filters.issue_id,
        actor: parsed.filters.actor,
        source: parsed.filters.source,
        status: parsed.filters.status,
        sinceLocal: isoToLocalInput(parsed.filters.since),
        untilLocal: isoToLocalInput(parsed.filters.until),
      });
      setPage(parsed.page);
      setPageSize(parsed.pageSize);
      setOperationId(parsed.operation);
    };
    syncFromLoc();
    window.addEventListener("popstate", syncFromLoc);
    return () => window.removeEventListener("popstate", syncFromLoc);
  }, [active]);

  const listQuery = useQuery<TrailHistoryListResponse>({
    queryKey: ["trail-history-list", baselinesParam, filters, page, pageSize],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        issue_id: filters.issue_id,
        actor: filters.actor,
        source: filters.source,
        status: filters.status,
        since: filters.since,
        until: filters.until,
        baselines: baselinesParam,
        page: String(page),
        page_size: String(pageSize),
      });
      return apiRequest<TrailHistoryListResponse>(`/api/trail-history?${qs.toString()}`, {
        signal,
      });
    },
    enabled: active,
    staleTime: 10_000,
  });

  const detailQuery = useQuery<TrailHistoryDetail>({
    queryKey: ["trail-history-detail", operationId],
    queryFn: ({ signal }) =>
      apiRequest<TrailHistoryDetail>(`/api/trail-history/${encodeURIComponent(operationId)}`, {
        signal,
      }),
    enabled: active && Boolean(operationId),
    staleTime: 5_000,
  });

  const detail = detailOverride?.id === operationId ? detailOverride : detailQuery.data || null;

  // Reset restore workflow state whenever operationId changes
  useEffect(() => {
    setDetailOverride(null);
    setRestoring(false);
    setSelectedIssues([]);
    setRestoreReason("");
    setRestorePreview(null);
  }, [operationId]);

  // Open/close native <dialog>
  useEffect(() => {
    const dlg = dialogRef.current;
    if (!dlg) return;
    if (active && operationId && detail) {
      if (!dlg.open) {
        try {
          dlg.showModal();
        } catch {
          dlg.setAttribute("open", "");
        }
      }
    } else if (dlg.open) {
      dlg.close();
    }
  }, [active, operationId, detail]);

  const closeDialog = useCallback(() => {
    if (busy) return;
    setOperationId("");
    syncUrl({ operation: "" });
  }, [busy, syncUrl]);

  const handleOpenDetail = (id: string) => {
    if (busy) return;
    setOperationId(id);
    syncUrl({ operation: id });
  };

  const handleSubmitFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const nextFilters: TrailHistoryFilters = {
      issue_id: draft.issue_id.trim(),
      actor: draft.actor.trim(),
      source: draft.source,
      status: draft.status,
      since: localInputToIso(draft.sinceLocal),
      until: localInputToIso(draft.untilLocal),
    };
    setFilters(nextFilters);
    setPage(1);
    setOperationId("");
    syncUrl({ filters: nextFilters, page: 1, operation: "" });
  };

  const handleResetFilters = () => {
    const empty: TrailHistoryFilters = {
      issue_id: "",
      actor: "",
      source: "",
      status: "",
      since: "",
      until: "",
    };
    setFilters(empty);
    setDraft({
      issue_id: "",
      actor: "",
      source: "",
      status: "",
      sinceLocal: "",
      untilLocal: "",
    });
    setPage(1);
    setOperationId("");
    syncUrl({ filters: empty, page: 1, operation: "" });
  };

  const handleVerify = async () => {
    if (busy || !operationId) return;
    setBusy(true);
    setRestorePreview(null);
    try {
      const next = await apiRequest<TrailHistoryDetail>(
        `/api/trail-history/${encodeURIComponent(operationId)}/verify`,
        { method: "POST", body: {} },
      );
      setDetailOverride(next);
      setSelectedIssues((prev) => prev.filter((id) => next.outcomes?.[id] === "succeeded"));
    } catch (err) {
      getLegacyWindow().showToast?.(err instanceof Error ? err.message : String(err), true);
    } finally {
      setBusy(false);
    }
  };

  const handlePreviewRestore = async () => {
    if (busy || !restoring || !operationId) return;
    if (!restoreReason.trim()) {
      getLegacyWindow().showToast?.(
        bilingual(lang, "请填写恢复原因。", "Enter a restore reason."),
        true,
      );
      return;
    }
    if (!selectedIssues.length) {
      getLegacyWindow().showToast?.(
        bilingual(lang, "请选择已核验成功的 Issue。", "Select at least one verified Issue."),
        true,
      );
      return;
    }
    setBusy(true);
    setRestorePreview(null);
    try {
      const preview = await apiRequest<TrailRestorePreview>(
        `/api/trail-history/${encodeURIComponent(operationId)}/restore-preview`,
        {
          method: "POST",
          body: { reason: restoreReason, issue_ids: selectedIssues },
        },
      );
      setRestorePreview(preview);
      window.requestAnimationFrame(() =>
        restoreResultRef.current?.scrollIntoView?.({ block: "start" }),
      );
    } catch (err) {
      getLegacyWindow().showToast?.(err instanceof Error ? err.message : String(err), true);
    } finally {
      setBusy(false);
    }
  };

  const handleCommitRestore = async () => {
    if (busy || !restoring || !restorePreview?.ready || !operationId) return;
    setBusy(true);
    try {
      const result = await apiRequest<{ ok: boolean; operation_id: string }>(
        `/api/trail-history/${encodeURIComponent(operationId)}/restore-commit`,
        {
          method: "POST",
          body: { preview_id: restorePreview.preview_id, confirm: true },
        },
      );
      setRestorePreview(null);
      getLegacyWindow().showToast?.(
        result.ok
          ? bilingual(lang, "恢复已回读验证。", "Restore verified by readback.")
          : bilingual(
              lang,
              "恢复尚未全部验证，请查看执行事件。",
              "Restore is not fully verified; inspect execution events.",
            ),
        !result.ok,
      );
      void queryClient.invalidateQueries({ queryKey: ["trail-history-list"] });
      if (result.operation_id) {
        setOperationId(result.operation_id);
        syncUrl({ operation: result.operation_id });
      }
    } catch (err) {
      getLegacyWindow().showToast?.(err instanceof Error ? err.message : String(err), true);
    } finally {
      setBusy(false);
    }
  };

  const sourceOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "全部来源", "All sources") },
      ...SOURCE_KEYS.map((key) => ({ value: key, label: sourceLabel(key, lang) })),
    ],
    [lang],
  );

  const statusOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "全部结果", "All outcomes") },
      ...STATUS_KEYS.map((key) => ({ value: key, label: statusLabel(key, lang) })),
    ],
    [lang],
  );

  if (!active) return null;

  const data = listQuery.data;
  const columns = [
    bilingual(lang, "时间（CST）", "Time (CST)"),
    bilingual(lang, "操作人", "Operator"),
    bilingual(lang, "来源", "Source"),
    bilingual(lang, "成功 / 总数", "Success / total"),
    bilingual(lang, "执行结果", "Outcome"),
    bilingual(lang, "操作", "Actions"),
  ];

  const renderComparisonBoxes = (
    before: Record<string, unknown> | undefined,
    after: Record<string, unknown> | undefined,
    key: string,
    preview = false,
  ) => (
    <div className="trail-history-diff">
      <div className="trail-history-diff-cell">
        <small>
          {preview ? bilingual(lang, "当前值", "Current") : bilingual(lang, "修改前", "Before")}
        </small>
        <pre>{formatFieldValue(before, key, lang)}</pre>
      </div>
      <span className="trail-history-arrow" aria-hidden="true">
        →
      </span>
      <div className="trail-history-diff-cell trail-history-diff-after">
        <small>
          {preview ? bilingual(lang, "恢复为", "Restore to") : bilingual(lang, "修改后", "After")}
        </small>
        <pre>{formatFieldValue(after, key, lang)}</pre>
      </div>
    </div>
  );

  const toggleIssueSelected = (issueId: string, checked: boolean) => {
    setSelectedIssues((prev) =>
      checked ? (prev.includes(issueId) ? prev : [...prev, issueId]) : prev.filter((x) => x !== issueId),
    );
    setRestorePreview(null);
  };

  const renderLabelTable = (
    items: TrailHistoryDiffItem[],
    beforeKey: "before" | "current",
    afterKey: "after" | "restore",
    selectable: boolean,
  ) => {
    const preview = afterKey === "restore";
    const showOutcomes =
      !preview &&
      items.some((it) => (detail?.outcomes?.[it.issue_id] || "unknown") !== detail?.status);
    const beforeHdr = preview
      ? bilingual(lang, "当前值", "Current")
      : bilingual(lang, "修改前", "Before");
    const afterHdr = preview
      ? bilingual(lang, "恢复为", "Restore to")
      : bilingual(lang, "修改后", "After");
    return (
      <div className="trail-history-label-table-wrap">
        <table className="trail-history-label-table">
          <caption>{labelFieldName(items[0]?.field, lang)}</caption>
          <thead>
            <tr>
              <th scope="col">Issue ID</th>
              <th scope="col">{beforeHdr}</th>
              <th scope="col">{afterHdr}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const checked = selectedIssues.includes(item.issue_id);
              const eligible = Boolean(detail?.restorable_issue_ids?.includes(item.issue_id));
              return (
                <tr key={item.issue_id}>
                  <th scope="row">
                    {selectable ? (
                      <label className="trail-history-select">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={!eligible || busy}
                          aria-label={bilingual(
                            lang,
                            `恢复 ${item.issue_id}`,
                            `Restore ${item.issue_id}`,
                          )}
                          onChange={(e) => toggleIssueSelected(item.issue_id, e.target.checked)}
                        />
                        <span>{item.issue_id}</span>
                      </label>
                    ) : (
                      <span>{item.issue_id}</span>
                    )}
                    {showOutcomes && detail?.outcomes?.[item.issue_id] !== "succeeded" ? (
                      <StatusBadge
                        status={detail?.outcomes?.[item.issue_id] || "unknown"}
                        source={detail?.source}
                        lang={lang}
                      />
                    ) : null}
                  </th>
                  <td>{formatLabelItemValue(item, beforeKey, lang)}</td>
                  <td className="trail-history-label-after">
                    {formatLabelItemValue(item, afterKey, lang)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  };

  const renderIssueDiff = (
    item: TrailHistoryDiffItem,
    beforeKey: "before" | "current",
    afterKey: "after" | "restore",
    selectable: boolean,
  ) => {
    const before = item[beforeKey] || {};
    const after = item[afterKey] || {};
    if (labelFieldName(item.field, lang)) {
      return renderLabelTable([item], beforeKey, afterKey, selectable);
    }
    const renderFlag = (obj: Record<string, unknown>) =>
      typeof obj.should_exclude === "boolean" ? (
        <span className="trail-history-value" data-excluded={String(obj.should_exclude)}>
          {obj.should_exclude
            ? bilingual(lang, "已排除", "Excluded")
            : bilingual(lang, "未排除", "Not excluded")}
        </span>
      ) : (
        <span className="trail-history-value">
          {formatFieldValue(obj, "should_exclude", lang)}
        </span>
      );
    const preview = afterKey === "restore";
    const legacy = detail?.source === "legacy";
    const from = preview ? bilingual(lang, "当前值", "Current") : bilingual(lang, "修改前", "Before");
    const to = preview ? bilingual(lang, "恢复为", "Restore to") : bilingual(lang, "修改后", "After");
    const outcome = detail?.outcomes?.[item.issue_id];
    const eligible = outcome === "succeeded";
    const reasonChanged =
      JSON.stringify(before.should_exclude_comment) !==
      JSON.stringify(after.should_exclude_comment);
    const flagChanged =
      JSON.stringify(before.should_exclude) !== JSON.stringify(after.should_exclude);

    return (
      <section className="trail-history-issue" key={`${item.issue_id}-${item.field || "excl"}`}>
        <div className="trail-history-issue-heading">
          {selectable ? (
            <label className="trail-history-select">
              <input
                type="checkbox"
                checked={selectedIssues.includes(item.issue_id)}
                disabled={!eligible || busy}
                aria-label={bilingual(lang, `恢复 ${item.issue_id}`, `Restore ${item.issue_id}`)}
                onChange={(e) => toggleIssueSelected(item.issue_id, e.target.checked)}
              />
              <strong>{item.issue_id}</strong>
            </label>
          ) : (
            <h4>{item.issue_id}</h4>
          )}
          {!preview && !eligible ? (
            <StatusBadge status={outcome || "unknown"} source={detail?.source} lang={lang} />
          ) : null}
        </div>

        {legacy ? (
          <div className="trail-history-reason">
            <h5>{bilingual(lang, "原记录说明", "Recorded note")}</h5>
            <pre className="trail-history-note">
              {formatFieldValue(after, "should_exclude_comment", lang)}
            </pre>
          </div>
        ) : (
          <>
            {flagChanged ? (
              <div className="trail-history-transition">
                <span className="trail-history-muted">
                  {bilingual(lang, "排除状态", "Exclusion")}
                </span>
                <span>
                  <small>{from}</small> {renderFlag(before)}
                </span>
                <span className="trail-history-arrow" aria-hidden="true">
                  →
                </span>
                <span>
                  <small>{to}</small> {renderFlag(after)}
                </span>
              </div>
            ) : (
              <div className="trail-history-unchanged">
                <span>{bilingual(lang, "排除状态未变", "Exclusion unchanged")}</span>
                {renderFlag(after)}
              </div>
            )}
            <div className="trail-history-reason">
              <div className="trail-history-field-heading">
                <h5>{bilingual(lang, "排除理由", "Exclusion reason")}</h5>
                <span className={reasonChanged ? "trail-history-changed" : "trail-history-muted"}>
                  {reasonChanged
                    ? bilingual(lang, "已变化", "Changed")
                    : bilingual(lang, "未变化", "Unchanged")}
                </span>
              </div>
              {reasonChanged ? (
                renderComparisonBoxes(before, after, "should_exclude_comment", preview)
              ) : (
                <pre className="trail-history-note">
                  {formatFieldValue(after, "should_exclude_comment", lang)}
                </pre>
              )}
            </div>
          </>
        )}
      </section>
    );
  };

  const renderGroupedChanges = (
    items: TrailHistoryDiffItem[],
    beforeKey: "before" | "current",
    afterKey: "after" | "restore",
    selectable: boolean,
  ) => {
    const groups: Array<{ field?: string; items?: TrailHistoryDiffItem[]; item?: TrailHistoryDiffItem }> = [];
    const fieldMap = new Map<string, { field: string; items: TrailHistoryDiffItem[] }>();
    for (const item of items) {
      if (!item.field || !labelFieldName(item.field, lang)) {
        groups.push({ item });
        continue;
      }
      let grp = fieldMap.get(item.field);
      if (!grp) {
        grp = { field: item.field, items: [] };
        fieldMap.set(item.field, grp);
        groups.push(grp);
      }
      grp.items.push(item);
    }
    return groups.map((g, idx) =>
      g.items ? (
        <React.Fragment key={`grp-${g.field}-${idx}`}>
          {renderLabelTable(g.items, beforeKey, afterKey, selectable)}
        </React.Fragment>
      ) : g.item ? (
        renderIssueDiff(g.item, beforeKey, afterKey, selectable)
      ) : null,
    );
  };

  const allowedRestore = Boolean(
    detail &&
      !["legacy", "rd_upload", "te_correction"].includes(detail.source) &&
      data?.can_restore,
  );
  const editingRestore = allowedRestore && restoring;
  const readyRestore = Boolean(editingRestore && restorePreview?.ready);
  const activeStep = readyRestore ? 2 : selectedIssues.length ? 1 : 0;

  const actionHint = !editingRestore
    ? ""
    : busy
      ? bilingual(lang, "正在处理，请稍候…", "Processing, please wait…")
      : readyRestore
        ? bilingual(
            lang,
            `将恢复 ${restorePreview?.items.length || 0} 个 Issue`,
            `${restorePreview?.items.length || 0} ${
              restorePreview?.items.length === 1 ? "Issue" : "Issues"
            } will be restored`,
          )
        : !detail?.restorable
          ? bilingual(lang, "请先重新核验 Trail。", "Verify Trail before restoring.")
          : !selectedIssues.length
            ? bilingual(lang, "请选择要恢复的 Issue。", "Select Issues to restore.")
            : !restoreReason.trim()
              ? bilingual(lang, "填写恢复原因后预览差异。", "Enter a reason to preview changes.")
              : bilingual(
                  lang,
                  `已选 ${selectedIssues.length} 个 Issue · 尚未写入`,
                  `${selectedIssues.length} selected · Nothing written`,
                );

  return (
    <div className="ra-trail-history-root" data-react-island="trail-history">
      <div className="trail-history-toolbar">
        <div id="trailHistoryCoverage">
          <details>
            <summary>
              {bilingual(lang, "问题排除 · 标注上传 · 恢复", "Exclusion · Labels · Restore")}{" "}
              <span className="trail-history-muted">
                {bilingual(lang, "覆盖范围", "Coverage")}
              </span>
            </summary>
            <ul className="trail-history-coverage-list">
              <li>
                ✓{" "}
                {bilingual(
                  lang,
                  "问题排除、RD 上传、TE 修正、恢复",
                  "Issue exclusion, RD uploads, TE corrections, restores",
                )}
              </li>
              <li>
                —{" "}
                {bilingual(
                  lang,
                  "未接入：自动回刷、抽样、外部 RD 同步、外部 AutoTriage、Trail 原站",
                  "Not connected: daily publication, sampling, external RD sync, external AutoTriage, native Trail",
                )}
              </li>
              <li>
                —{" "}
                {bilingual(
                  lang,
                  "旧版记录无完整快照，不可恢复",
                  "Legacy records have no complete snapshots and cannot be restored",
                )}
              </li>
            </ul>
            {data?.started_at ? (
              <p>
                {bilingual(lang, "新版记录始于", "New records since")}{" "}
                {formatHistoryTime(data.started_at, lang)} CST
              </p>
            ) : null}
          </details>
        </div>
        <button
          className="button button-secondary"
          id="trailHistoryRefresh"
          type="button"
          disabled={listQuery.isFetching}
          onClick={() => void listQuery.refetch()}
        >
          {bilingual(lang, "刷新", "Refresh")}
        </button>
      </div>

      <form
        id="trailHistoryFilters"
        className="trail-history-filters"
        onSubmit={handleSubmitFilters}
      >
        <label>
          Issue ID
          <input
            name="issue_id"
            autoComplete="off"
            value={draft.issue_id}
            onChange={(e) => setDraft((prev) => ({ ...prev, issue_id: e.target.value }))}
          />
        </label>
        <label>
          {bilingual(lang, "操作人 LDAP", "Operator LDAP")}
          <input
            name="actor"
            autoComplete="off"
            value={draft.actor}
            onChange={(e) => setDraft((prev) => ({ ...prev, actor: e.target.value }))}
          />
        </label>
        <div className="ra-th-field">
          <span>{bilingual(lang, "来源", "Source")}</span>
          <UiSelect
            id="trailHistorySourceSelect"
            value={draft.source}
            options={sourceOptions}
            ariaLabel={bilingual(lang, "来源", "Source")}
            onChange={(val) => setDraft((prev) => ({ ...prev, source: val }))}
          />
        </div>
        <div className="ra-th-field">
          <span>{bilingual(lang, "执行结果", "Outcome")}</span>
          <UiSelect
            id="trailHistoryStatusSelect"
            value={draft.status}
            options={statusOptions}
            ariaLabel={bilingual(lang, "执行结果", "Outcome")}
            onChange={(val) => setDraft((prev) => ({ ...prev, status: val }))}
          />
        </div>
        <label>
          {bilingual(lang, "开始时间（CST）", "From (CST)")}
          <input
            type="datetime-local"
            name="since"
            value={draft.sinceLocal}
            onChange={(e) => setDraft((prev) => ({ ...prev, sinceLocal: e.target.value }))}
          />
        </label>
        <label>
          {bilingual(lang, "结束时间（CST）", "Until (CST)")}
          <input
            type="datetime-local"
            name="until"
            value={draft.untilLocal}
            onChange={(e) => setDraft((prev) => ({ ...prev, untilLocal: e.target.value }))}
          />
        </label>
        <div className="trail-history-filter-actions">
          <button className="button button-primary" type="submit">
            {bilingual(lang, "查询", "Search")}
          </button>
          <button
            className="button button-secondary"
            type="button"
            data-action="reset"
            onClick={handleResetFilters}
          >
            {bilingual(lang, "重置", "Reset")}
          </button>
        </div>
      </form>

      <div id="trailHistoryResults" aria-live="polite">
        {listQuery.isError ? (
          <p role="alert">{(listQuery.error as Error)?.message || "Load failed"}</p>
        ) : !data ? (
          <p role="status">
            {bilingual(lang, "正在加载更新记录…", "Loading update history…")}
          </p>
        ) : (
          <>
            <div className="trail-history-table-wrap">
              <table className="trail-history-table">
                <thead>
                  <tr>
                    {columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.length === 0 ? (
                    <tr>
                      <td colSpan={6}>
                        {bilingual(lang, "没有匹配的更新记录。", "No matching updates.")}
                      </td>
                    </tr>
                  ) : (
                    data.items.map((row) => {
                      const pct = row.item_count
                        ? Math.max(0, Math.min(100, (row.succeeded_count / row.item_count) * 100))
                        : 0;
                      const meterLabel =
                        row.source === "legacy"
                          ? bilingual(lang, "记录成功 / 总数", "Recorded success / total")
                          : bilingual(lang, "已核验 / 总数", "Verified / total");
                      return (
                        <tr key={row.id}>
                          <td data-label={columns[0]}>{formatHistoryTime(row.created_at, lang)}</td>
                          <td data-label={columns[1]}>
                            {row.actor || bilingual(lang, "未知", "Unknown")}
                            <small>
                              {row.actor_verified
                                ? bilingual(lang, "已验证身份", "Verified identity")
                                : bilingual(lang, "身份未验证", "Unverified identity")}
                            </small>
                          </td>
                          <td data-label={columns[2]}>{sourceLabel(row.source, lang)}</td>
                          <td data-label={columns[3]}>
                            <div
                              className="trail-history-meter"
                              aria-label={`${meterLabel}: ${row.succeeded_count} / ${row.item_count}`}
                            >
                              <span>
                                {row.succeeded_count} / {row.item_count}
                              </span>
                              <div className="review-assignment-progress-track" aria-hidden="true">
                                <span style={{ width: `${pct}%` }} />
                              </div>
                            </div>
                          </td>
                          <td data-label={columns[4]}>
                            <StatusBadge status={row.status} source={row.source} lang={lang} />
                          </td>
                          <td data-label={columns[5]}>
                            <button
                              type="button"
                              className="button button-secondary"
                              data-operation={row.id}
                              onClick={() => handleOpenDetail(row.id)}
                            >
                              {bilingual(lang, "详情／回溯", "Details / Restore")}
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            <Pagination
              page={data.page || page}
              pageSize={data.page_size || pageSize}
              total={data.total || 0}
              lang={lang}
              loading={listQuery.isFetching}
              className="case-pagination"
              summaryText={bilingual(lang, `共 ${data.total} 条`, `${data.total} records`)}
              ariaLabel={bilingual(lang, "更新记录分页", "Update history pagination")}
              onPageChange={(nextPage) => {
                setPage(nextPage);
                syncUrl({ page: nextPage });
              }}
              onPageSizeChange={(nextSize) => {
                setPageSize(nextSize);
                setPage(1);
                syncUrl({ pageSize: nextSize, page: 1 });
              }}
            />
          </>
        )}
      </div>

      {createPortal(
        <dialog
          ref={dialogRef}
          id="raTrailHistoryDialog"
          className="trail-history-dialog"
          aria-labelledby="raTrailHistoryDialogTitle"
          onCancel={(e) => {
            if (busy) {
              e.preventDefault();
            }
          }}
          onClose={() => {
            if (!busy && operationId) {
              setOperationId("");
              syncUrl({ operation: "" });
            }
          }}
        >
          {detail ? (
            <div className="dialog-card">
              <div className="dialog-heading">
                <h2 id="raTrailHistoryDialogTitle">
                  {editingRestore
                    ? bilingual(lang, "恢复 Trail 更新", "Restore Trail update")
                    : bilingual(lang, "Trail 更新详情", "Trail update details")}
                </h2>
                <button
                  className="icon-button"
                  type="button"
                  disabled={busy}
                  aria-label={bilingual(lang, "关闭", "Close")}
                  onClick={closeDialog}
                >
                  ×
                </button>
              </div>

              <div className="trail-history-dialog-body" ref={dialogBodyRef}>
                {editingRestore ? (
                  <section className="trail-history-restore-intro">
                    <ol
                      id="trailHistoryRestoreSteps"
                      className="trail-history-steps"
                      aria-label={bilingual(lang, "恢复步骤", "Restore steps")}
                    >
                      {[
                        bilingual(lang, "选择 Issue", "Select Issues"),
                        bilingual(lang, "预览差异", "Preview changes"),
                        bilingual(lang, "确认恢复", "Confirm restore"),
                      ].map((label, idx) => (
                        <li
                          key={label}
                          aria-current={idx === activeStep ? "step" : undefined}
                          data-complete={String(idx < activeStep)}
                        >
                          <span aria-hidden="true">{idx < activeStep ? "✓" : idx + 1}</span>
                          {label}
                        </li>
                      ))}
                    </ol>
                    <p>
                      {bilingual(
                        lang,
                        "仅恢复所选 Issue 本次修改的 Trail 字段；人工标注及其他字段保留。",
                        "Restore only the recorded Trail fields for selected Issues; human labels and other fields are preserved.",
                      )}
                    </p>
                  </section>
                ) : null}

                <section
                  className="trail-history-overview"
                  aria-label={bilingual(lang, "更新概览", "Update overview")}
                >
                  <div className="trail-history-overview-heading">
                    <StatusBadge status={detail.status} source={detail.source} lang={lang} />
                    <span>
                      {(() => {
                        const total = detail.items.length;
                        const verified = Object.values(detail.outcomes || {}).filter(
                          (v) => v === "succeeded",
                        ).length;
                        return detail.source === "legacy"
                          ? bilingual(
                              lang,
                              `${total} 个 Issue · 旧版记录`,
                              `${total} ${total === 1 ? "Issue" : "Issues"} · Legacy record`,
                            )
                          : bilingual(
                              lang,
                              `${verified} / ${total} 个 Issue 已核验`,
                              `${verified} / ${total} ${total === 1 ? "Issue" : "Issues"} verified`,
                            );
                      })()}
                    </span>
                  </div>
                  <dl className="trail-history-facts">
                    <div>
                      <dt>{bilingual(lang, "更新来源", "Source")}</dt>
                      <dd>{sourceLabel(detail.source, lang)}</dd>
                    </div>
                    <div>
                      <dt>{bilingual(lang, "操作人", "Operator")}</dt>
                      <dd>{detail.actor || "—"}</dd>
                    </div>
                    <div>
                      <dt>{bilingual(lang, "更新时间（CST）", "Updated (CST)")}</dt>
                      <dd>
                        <time>{formatHistoryTime(detail.created_at, lang)}</time>
                      </dd>
                    </div>
                  </dl>
                  {detail.reason ? (
                    <div className="trail-history-operation-reason">
                      <span>{bilingual(lang, "操作原因", "Operation reason")}</span>
                      <p>{detail.reason}</p>
                    </div>
                  ) : null}
                </section>

                {detail.source === "legacy" ? (
                  <p role="note" className="trail-history-muted">
                    {bilingual(
                      lang,
                      "旧版记录 · 无完整快照 · 不可恢复",
                      "Legacy · No complete snapshots · Restore unavailable",
                    )}
                  </p>
                ) : null}

                {detail.parent_id ? (
                  <p className="trail-history-related">
                    {bilingual(lang, "恢复自", "Restores")}{" "}
                    <button
                      type="button"
                      className="button button-secondary"
                      title={detail.parent_id}
                      onClick={() => handleOpenDetail(detail.parent_id!)}
                    >
                      {bilingual(lang, "查看原更新", "View original update")}
                    </button>
                  </p>
                ) : null}

                {!readyRestore ? (
                  <section
                    className="trail-history-changes"
                    aria-labelledby="trailHistoryChangesTitle"
                  >
                    <div className="trail-history-section-heading">
                      <h3 id="trailHistoryChangesTitle">
                        {editingRestore
                          ? bilingual(lang, "选择要恢复的 Issue", "Select Issues to restore")
                          : bilingual(lang, "变更内容", "Changes")}
                      </h3>
                      <span>
                        {bilingual(
                          lang,
                          `${detail.items.length} 个 Issue`,
                          `${detail.items.length} ${detail.items.length === 1 ? "Issue" : "Issues"}`,
                        )}
                      </span>
                    </div>
                    {detail.items.length ? (
                      renderGroupedChanges(
                        detail.items,
                        "before",
                        "after",
                        Boolean(editingRestore && detail.restorable),
                      )
                    ) : (
                      <p className="trail-history-muted">
                        {bilingual(lang, "没有可展示的 Issue 记录。", "No Issue records to display.")}
                      </p>
                    )}
                  </section>
                ) : null}

                {!editingRestore ? (
                  <section
                    className="trail-history-execution"
                    aria-labelledby="trailHistoryTimelineTitle"
                  >
                    <div className="trail-history-section-heading">
                      <h3 id="trailHistoryTimelineTitle">
                        {bilingual(lang, "执行记录", "Execution history")}
                      </h3>
                      <span>
                        {bilingual(
                          lang,
                          `${detail.events.length} 条事件`,
                          `${detail.events.length} ${detail.events.length === 1 ? "event" : "events"}`,
                        )}
                      </span>
                    </div>
                    {detail.events.length ? (
                      <ol className="trail-history-timeline">
                        {detail.events.map((ev, idx) => {
                          const counts: Record<string, number> = {};
                          for (const st of Object.values(ev.outcomes || {})) {
                            counts[st] = (counts[st] || 0) + 1;
                          }
                          const summaryText =
                            Object.entries(counts)
                              .map(([st, cnt]) => `${statusLabel(st, lang, detail.source)} · ${cnt}`)
                              .join(" / ") || bilingual(lang, "暂无逐项回执", "No item receipts");
                          return (
                            <li key={idx}>
                              <div>
                                <StatusBadge status={ev.status} source={detail.source} lang={lang} />
                                <time>{formatHistoryTime(ev.created_at, lang)} CST</time>
                                <span>{ev.actor || "—"}</span>
                              </div>
                              <p>{summaryText}</p>
                            </li>
                          );
                        })}
                      </ol>
                    ) : (
                      <p className="trail-history-muted">
                        {bilingual(lang, "暂无执行事件。", "No execution events.")}
                      </p>
                    )}
                  </section>
                ) : null}

                {detail.children?.length ? (
                  <div className="trail-history-related">
                    <span>{bilingual(lang, "后续恢复", "Subsequent restores")}</span>
                    {detail.children.map((child) => (
                      <button
                        key={child.id}
                        type="button"
                        className="button button-secondary"
                        onClick={() => handleOpenDetail(child.id)}
                      >
                        {formatHistoryTime(child.created_at, lang)} · {child.actor || "—"}
                      </button>
                    ))}
                  </div>
                ) : null}

                {!editingRestore ? (
                  <details className="review-history-toggle trail-history-audit">
                    <summary id="trailHistoryAuditSummary">
                      <span>
                        <strong>{bilingual(lang, "审计信息", "Audit details")}</strong>
                        <small>
                          {bilingual(
                            lang,
                            "操作标识与逐项回执",
                            "Operation markers and item receipts",
                          )}
                        </small>
                      </span>
                    </summary>
                    <div className="trail-history-audit-content">
                      <div>
                        <h4>{bilingual(lang, "本次操作标识", "Operation ID")}</h4>
                        <code className="trail-history-id">{detail.id}</code>
                      </div>
                      {(() => {
                        const fields = [
                          ...new Set(detail.items.map((it) => it.field).filter(Boolean)),
                        ] as string[];
                        if (!fields.length) return null;
                        return (
                          <section>
                            <h4>{bilingual(lang, "目标字段", "Target fields")}</h4>
                            <ul className="trail-history-audit-fields">
                              {fields.map((f) => (
                                <li key={f}>
                                  <span>{labelFieldName(f, lang)}</span>
                                  <code className="trail-history-id">{f}</code>
                                </li>
                              ))}
                            </ul>
                          </section>
                        );
                      })()}
                      {["exclusion_summary", "exclusion_direct", "rollback"].includes(
                        detail.source,
                      ) ? (
                        <section>
                          <h4>{bilingual(lang, "Issue 操作标识", "Issue operation markers")}</h4>
                          <div className="trail-history-audit-items">
                            {detail.items.map((item) => (
                              <div key={item.issue_id}>
                                <strong>{item.issue_id}</strong>
                                {renderComparisonBoxes(item.before, item.after, "operation_id")}
                              </div>
                            ))}
                          </div>
                        </section>
                      ) : null}
                      {detail.events.map((ev, idx) => (
                        <section key={idx}>
                          <h4>
                            {bilingual(lang, "Issue 结果", "Issue outcomes")} ·{" "}
                            {formatHistoryTime(ev.created_at, lang)} CST
                          </h4>
                          <ul className="trail-history-outcomes">
                            {Object.entries(ev.outcomes || {}).length ? (
                              Object.entries(ev.outcomes).map(([iss, st]) => (
                                <li key={iss}>
                                  <span>{iss}</span>
                                  <StatusBadge status={st} source={detail.source} lang={lang} />
                                </li>
                              ))
                            ) : (
                              <li>{bilingual(lang, "暂无逐项回执", "No item receipts")}</li>
                            )}
                          </ul>
                        </section>
                      ))}
                    </div>
                  </details>
                ) : null}

                {editingRestore ? (
                  <section className="trail-history-restore">
                    <p>
                      {bilingual(
                        lang,
                        "不撤销本地裁决或通知。提交前重新检查冲突并回读；Trail 不支持原子条件写入，仍可能存在外部并发。",
                        "Local decisions and notifications stay unchanged. Conflicts are checked before writing and results are read back; Trail has no atomic conditional writes, so external concurrency remains possible.",
                      )}
                    </p>
                    {!readyRestore ? (
                      <button
                        type="button"
                        className="button button-secondary"
                        disabled={busy}
                        onClick={() => void handleVerify()}
                      >
                        {bilingual(lang, "重新核验 Trail", "Verify Trail again")}
                      </button>
                    ) : null}
                    {detail.current_conflicts?.length ? (
                      <p role="alert">
                        {bilingual(lang, "当前值已变化：", "Current values changed: ")}
                        {detail.current_conflicts.join(", ")}
                      </p>
                    ) : null}
                    {detail.restorable ? (
                      readyRestore ? (
                        <p>
                          {bilingual(lang, "恢复原因：", "Restore reason: ")}
                          {restoreReason}
                        </p>
                      ) : (
                        <label htmlFor="trailHistoryReason">
                          {bilingual(lang, "恢复原因", "Restore reason")}
                          <textarea
                            id="trailHistoryReason"
                            rows={2}
                            maxLength={1000}
                            disabled={busy}
                            value={restoreReason}
                            onChange={(e) => {
                              setRestoreReason(e.target.value);
                              setRestorePreview(null);
                            }}
                          />
                        </label>
                      )
                    ) : (
                      <p>
                        {bilingual(lang, "核验成功后可恢复。", "Restore is available after verification.")}
                      </p>
                    )}

                    <div id="trailHistoryRestoreResult" ref={restoreResultRef} aria-live="polite">
                      {restorePreview ? (
                        restorePreview.conflicts?.length ? (
                          <p role="alert">
                            {bilingual(
                              lang,
                              "这些 Issue 已发生变化，未写入：",
                              "These Issues changed; nothing written: ",
                            )}
                            {restorePreview.conflicts.join(", ")}
                          </p>
                        ) : (
                          <>
                            <h3>{bilingual(lang, "恢复预览", "Restore preview")}</h3>
                            {restorePreview.items.map((item) =>
                              renderIssueDiff(item, "current", "restore", false),
                            )}
                          </>
                        )
                      ) : null}
                    </div>
                  </section>
                ) : null}
              </div>

              <div className="trail-history-dialog-footer">
                {editingRestore ? (
                  <p id="trailHistoryActionHint" className="trail-history-muted" role="status">
                    {actionHint}
                  </p>
                ) : null}
                <div className="dialog-actions">
                  {!editingRestore ? (
                    <button
                      className="button button-secondary"
                      type="button"
                      disabled={busy}
                      onClick={closeDialog}
                    >
                      {bilingual(lang, "关闭", "Close")}
                    </button>
                  ) : null}
                  {editingRestore ? (
                    <button
                      className="button button-secondary"
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setRestoring(false);
                        setRestorePreview(null);
                        setSelectedIssues([]);
                        setRestoreReason("");
                      }}
                    >
                      {bilingual(lang, "取消恢复", "Cancel restore")}
                    </button>
                  ) : null}
                  {readyRestore ? (
                    <button
                      className="button button-secondary"
                      type="button"
                      disabled={busy}
                      onClick={() => setRestorePreview(null)}
                    >
                      {bilingual(lang, "返回选择", "Edit selection")}
                    </button>
                  ) : null}
                  {allowedRestore && !editingRestore ? (
                    <button
                      className="button button-secondary"
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setRestoring(true);
                        setSelectedIssues([]);
                        setRestorePreview(null);
                        if (dialogBodyRef.current) dialogBodyRef.current.scrollTop = 0;
                      }}
                    >
                      {bilingual(lang, "恢复…", "Restore…")}
                    </button>
                  ) : null}
                  {editingRestore && !readyRestore ? (
                    <button
                      className="button button-primary"
                      type="button"
                      disabled={
                        busy || !detail.restorable || !selectedIssues.length || !restoreReason.trim()
                      }
                      onClick={() => void handlePreviewRestore()}
                    >
                      {bilingual(lang, "预览恢复", "Preview restore")}
                    </button>
                  ) : null}
                  {readyRestore ? (
                    <button
                      className="button button-danger"
                      type="button"
                      disabled={busy || !readyRestore}
                      onClick={() => void handleCommitRestore()}
                    >
                      {bilingual(lang, "确认恢复", "Confirm restore")}
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
        </dialog>,
        document.body,
      )}
    </div>
  );
};
