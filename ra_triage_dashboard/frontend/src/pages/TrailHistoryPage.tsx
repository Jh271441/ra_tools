import React, { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, formatCstTime, UiLanguage } from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { DEFAULT_CASE_PAGE_SIZE, Pagination } from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";
import { showWorkbenchToast } from "../features/review/reviewHelpers";

interface TrailHistoryRow {
  id: string;
  created_at: string;
  actor?: string;
  actor_verified?: boolean;
  source: string;
  item_count: number;
  succeeded_count: number;
  status: string;
}

interface TrailHistoryListPayload {
  items: TrailHistoryRow[];
  total: number;
  page: number;
  page_size: number;
  can_restore?: boolean;
  started_at?: string;
}

interface TrailHistoryItemDiff {
  issue_id: string;
  field?: string;
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
  current?: Record<string, unknown>;
  restore?: Record<string, unknown>;
}

interface TrailHistoryDetail {
  id: string;
  source: string;
  status: string;
  actor?: string;
  created_at?: string;
  reason?: string;
  parent_id?: string;
  restorable?: boolean;
  restorable_issue_ids?: string[];
  current_conflicts?: string[];
  outcomes: Record<string, string>;
  items: TrailHistoryItemDiff[];
  events: Array<{
    created_at: string;
    actor?: string;
    status: string;
    outcomes: Record<string, string>;
  }>;
  children?: Array<{ id: string; created_at: string; actor?: string }>;
}

interface TrailRestorePreview {
  preview_id: string;
  ready: boolean;
  conflicts: string[];
  items: TrailHistoryItemDiff[];
}

export interface TrailHistoryPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
}

function sourceLabel(value: string, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
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
  return map[value] ? bilingual(lang, map[value][0], map[value][1]) : value;
}

function statusLabel(value: string, lang: UiLanguage, source = ""): string {
  if (source === "legacy" && value === "succeeded") {
    return bilingual(lang, "旧记录成功", "Legacy success");
  }
  const map: Record<string, [string, string]> = {
    pending: ["待核验", "Pending verification"],
    succeeded: ["已回读成功", "Readback verified"],
    not_attempted: ["未执行", "Not attempted"],
    partial: ["部分成功", "Partial"],
    unknown: ["结果待核验", "Outcome unknown"],
    conflict: ["存在冲突", "Conflict"],
  };
  return map[value] ? bilingual(lang, map[value][0], map[value][1]) : bilingual(lang, "未知", "Unknown");
}

function formatFieldVal(obj: Record<string, unknown> | undefined, key: string, lang: UiLanguage): string {
  if (!obj || !(key in obj)) return bilingual(lang, "字段不存在", "Field absent");
  const val = obj[key];
  if (val === null) return "null";
  if (typeof val === "string") return val || bilingual(lang, "空字符串", "Empty string");
  return JSON.stringify(val);
}

export const TrailHistoryPage: React.FC<TrailHistoryPageProps> = ({
  active,
  lang,
  selectedBaselines,
}) => {
  const queryClient = useQueryClient();
  const [issueId, setIssueId] = useState("");
  const [actor, setActor] = useState("");
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [applied, setApplied] = useState({ issueId: "", actor: "", source: "", status: "", since: "", until: "" });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_CASE_PAGE_SIZE);

  // Detail & restore dialog state
  const [openOpId, setOpenOpId] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [selectedIssues, setSelectedIssues] = useState<string[]>([]);
  const [restoreReason, setRestoreReason] = useState("");
  const [restorePreview, setRestorePreview] = useState<TrailRestorePreview | null>(null);

  const baselinesCsv = selectedBaselines.join(",");

  const listQuery = useQuery<TrailHistoryListPayload>({
    queryKey: ["trail-history-list", baselinesCsv, applied, page, pageSize],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        baselines: baselinesCsv,
        page: String(page),
        page_size: String(pageSize),
      });
      if (applied.issueId) qs.set("issue_id", applied.issueId);
      if (applied.actor) qs.set("actor", applied.actor);
      if (applied.source) qs.set("source", applied.source);
      if (applied.status) qs.set("status", applied.status);
      if (applied.since) qs.set("since", new Date(`${applied.since}:00+08:00`).toISOString());
      if (applied.until) qs.set("until", new Date(`${applied.until}:00+08:00`).toISOString());
      return apiRequest<TrailHistoryListPayload>(`/api/trail-history?${qs.toString()}`, { signal });
    },
    enabled: active,
    staleTime: 10_000,
  });

  const detailQuery = useQuery<TrailHistoryDetail>({
    queryKey: ["trail-history-detail", openOpId],
    queryFn: ({ signal }) =>
      apiRequest<TrailHistoryDetail>(`/api/trail-history/${encodeURIComponent(openOpId!)}`, { signal }),
    enabled: Boolean(openOpId),
  });

  const verifyMutation = useMutation({
    mutationFn: (opId: string) =>
      apiRequest<TrailHistoryDetail>(`/api/trail-history/${encodeURIComponent(opId)}/verify`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: (fresh) => {
      queryClient.setQueryData(["trail-history-detail", fresh.id], fresh);
      setRestorePreview(null);
      showWorkbenchToast(bilingual(lang, "已重新核验 Trail 状态。", "Trail state verified."));
    },
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

  const previewRestoreMutation = useMutation({
    mutationFn: () =>
      apiRequest<TrailRestorePreview>(
        `/api/trail-history/${encodeURIComponent(openOpId!)}/restore-preview`,
        {
          method: "POST",
          body: JSON.stringify({ reason: restoreReason.trim(), issue_ids: selectedIssues }),
        },
      ),
    onSuccess: (res) => setRestorePreview(res),
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

  const commitRestoreMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ ok?: boolean; operation_id?: string }>(
        `/api/trail-history/${encodeURIComponent(openOpId!)}/restore-commit`,
        {
          method: "POST",
          body: JSON.stringify({ preview_id: restorePreview?.preview_id, confirm: true }),
        },
      ),
    onSuccess: (res) => {
      setRestoring(false);
      setRestorePreview(null);
      setSelectedIssues([]);
      setRestoreReason("");
      void queryClient.invalidateQueries({ queryKey: ["trail-history-list"] });
      if (res.operation_id) setOpenOpId(res.operation_id);
      showWorkbenchToast(
        res.ok
          ? bilingual(lang, "恢复已回读验证。", "Restore verified by readback.")
          : bilingual(lang, "恢复尚未全部验证，请查看执行事件。", "Restore partially verified; inspect events."),
        !res.ok,
      );
    },
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

  const sourceOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "", label: bilingual(lang, "全部来源", "All sources") },
      ...[
        "exclusion_summary",
        "exclusion_direct",
        "model_label_normalization",
        "model_publication",
        "model_label_restore",
        "rd_upload",
        "te_correction",
        "rollback",
        "legacy",
      ].map((v) => ({ value: v, label: sourceLabel(v, lang) })),
    ],
    [lang],
  );

  const statusOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "", label: bilingual(lang, "全部结果", "All outcomes") },
      ...["pending", "succeeded", "partial", "unknown", "conflict"].map((v) => ({
        value: v,
        label: statusLabel(v, lang),
      })),
    ],
    [lang],
  );

  const detail = detailQuery.data;
  const canRestore = Boolean(
    detail &&
      listQuery.data?.can_restore &&
      !["legacy", "rd_upload", "te_correction"].includes(detail.source),
  );
  const busy =
    verifyMutation.isPending || previewRestoreMutation.isPending || commitRestoreMutation.isPending;

  return (
    <section
      id="trailHistoryPage"
      className="app-page ra-react-page"
      data-page="trail-history"
      data-react-island="trail-history"
    >
      <div className="panel-card">
        <div className="ra-page-header-row">
          <div>
            <h2>{bilingual(lang, "Trail 更新记录与审计回溯", "Trail Update History & Audit")}</h2>
            <p className="muted">
              {bilingual(
                lang,
                "本地只读审计记录；恢复操作需显式预览差异并二次确认。",
                "Local read-only audit records; restore requires explicit preview and confirmation.",
              )}
            </p>
          </div>
          <button
            type="button"
            className="button button-quiet"
            disabled={listQuery.isFetching}
            onClick={() => void listQuery.refetch()}
          >
            {listQuery.isFetching ? bilingual(lang, "刷新中…", "Refreshing…") : bilingual(lang, "刷新", "Refresh")}
          </button>
        </div>

        <details className="ra-disclosure-box" style={{ marginTop: 10 }}>
          <summary>
            {bilingual(lang, "问题排除 · 标注上传 · 恢复（覆盖范围）", "Exclusion · Labels · Restore (Coverage)")}
          </summary>
          <ul className="trail-history-coverage-list">
            <li>✓ {bilingual(lang, "问题排除、RD 上传、TE 修正、恢复", "Issue exclusion, RD uploads, TE corrections, restores")}</li>
            <li>— {bilingual(lang, "未接入：自动回刷、抽样、外部 RD 同步、外部 AutoTriage、Trail 原站", "Not connected: daily publication, sampling, external RD sync, native Trail")}</li>
            <li>— {bilingual(lang, "旧版记录无完整快照，不可恢复", "Legacy records have no complete snapshots and cannot be restored")}</li>
          </ul>
          {listQuery.data?.started_at && (
            <p className="muted">
              {bilingual(lang, "新版记录始于", "New records since")}{" "}
              {formatCstTime(listQuery.data.started_at, lang)} CST
            </p>
          )}
        </details>

        <form
          className="ra-filter-grid"
          style={{ marginTop: 12 }}
          onSubmit={(e) => {
            e.preventDefault();
            setApplied({ issueId: issueId.trim(), actor: actor.trim(), source, status, since, until });
            setPage(1);
          }}
        >
          <label className="ra-field-stack">
            <span>Issue ID</span>
            <input
              type="text"
              value={issueId}
              autoComplete="off"
              placeholder="cn37631883"
              onChange={(e) => setIssueId(e.target.value)}
            />
          </label>
          <label className="ra-field-stack">
            <span>{bilingual(lang, "操作人 LDAP", "Operator LDAP")}</span>
            <input
              type="text"
              value={actor}
              autoComplete="off"
              onChange={(e) => setActor(e.target.value)}
            />
          </label>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "来源", "Source")}</span>
            <UiSelect
              id="raTrailHistorySource"
              value={source}
              options={sourceOptions}
              ariaLabel={bilingual(lang, "按来源筛选", "Filter by source")}
              onChange={setSource}
            />
          </div>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "执行结果", "Outcome")}</span>
            <UiSelect
              id="raTrailHistoryStatus"
              value={status}
              options={statusOptions}
              ariaLabel={bilingual(lang, "按执行结果筛选", "Filter by outcome")}
              onChange={setStatus}
            />
          </div>
          <label className="ra-field-stack">
            <span>{bilingual(lang, "开始时间（CST）", "From (CST)")}</span>
            <input type="datetime-local" value={since} onChange={(e) => setSince(e.target.value)} />
          </label>
          <label className="ra-field-stack">
            <span>{bilingual(lang, "结束时间（CST）", "Until (CST)")}</span>
            <input type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />
          </label>
          <div className="ra-inline-actions" style={{ alignItems: "flex-end" }}>
            <button type="submit" className="button button-primary">
              {bilingual(lang, "查询", "Search")}
            </button>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => {
                setIssueId("");
                setActor("");
                setSource("");
                setStatus("");
                setSince("");
                setUntil("");
                setApplied({ issueId: "", actor: "", source: "", status: "", since: "", until: "" });
                setPage(1);
              }}
            >
              {bilingual(lang, "重置", "Reset")}
            </button>
          </div>
        </form>
      </div>

      <div className="panel-card">
        {listQuery.isLoading ? (
          <div className="no-asset">{bilingual(lang, "正在加载更新记录…", "Loading update history…")}</div>
        ) : listQuery.isError ? (
          <div className="no-asset">{(listQuery.error as Error)?.message}</div>
        ) : (
          <>
            <div className="ra-table-scroll">
              <table className="trail-history-table">
                <thead>
                  <tr>
                    <th>{bilingual(lang, "时间（CST）", "Time (CST)")}</th>
                    <th>{bilingual(lang, "操作人", "Operator")}</th>
                    <th>{bilingual(lang, "来源", "Source")}</th>
                    <th>{bilingual(lang, "成功 / 总数", "Success / total")}</th>
                    <th>{bilingual(lang, "执行结果", "Outcome")}</th>
                    <th>{bilingual(lang, "操作", "Actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {!(listQuery.data?.items || []).length ? (
                    <tr>
                      <td colSpan={6}>
                        {bilingual(lang, "没有匹配的更新记录。", "No matching updates.")}
                      </td>
                    </tr>
                  ) : (
                    listQuery.data!.items.map((row) => (
                      <tr key={row.id}>
                        <td>{formatCstTime(row.created_at, lang)}</td>
                        <td>
                          {row.actor || bilingual(lang, "未知", "Unknown")}{" "}
                          <small className="muted">
                            {row.actor_verified
                              ? bilingual(lang, "· SSO", "· SSO")
                              : bilingual(lang, "· 未验证", "· Unverified")}
                          </small>
                        </td>
                        <td>{sourceLabel(row.source, lang)}</td>
                        <td>
                          {row.succeeded_count} / {row.item_count}
                        </td>
                        <td>
                          <span className="trail-history-status" data-status={row.status}>
                            {statusLabel(row.status, lang, row.source)}
                          </span>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="button button-quiet"
                            onClick={() => {
                              setOpenOpId(row.id);
                              setRestoring(false);
                              setSelectedIssues([]);
                              setRestoreReason("");
                              setRestorePreview(null);
                            }}
                          >
                            {bilingual(lang, "详情 / 回溯", "Details / Restore")}
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {(listQuery.data?.total || 0) > 0 && (
              <Pagination
                page={page}
                pageSize={pageSize}
                total={listQuery.data!.total}
                lang={lang}
                loading={listQuery.isFetching}
                ariaLabel={bilingual(lang, "更新记录分页", "Update history pagination")}
                onPageChange={setPage}
                onPageSizeChange={(next) => {
                  setPageSize(next);
                  setPage(1);
                }}
              />
            )}
          </>
        )}
      </div>

      {/* Detail & Restore Modal */}
      <ModalDialog
        open={Boolean(openOpId)}
        title={
          restoring
            ? bilingual(lang, "恢复 Trail 更新", "Restore Trail update")
            : bilingual(lang, "Trail 更新详情", "Trail update details")
        }
        lang={lang}
        onClose={() => {
          if (!busy) {
            setOpenOpId(null);
            setRestoring(false);
            setRestorePreview(null);
          }
        }}
        footer={
          detail && (
            <>
              {canRestore && !restoring && (
                <button
                  type="button"
                  className="button button-quiet"
                  disabled={busy}
                  onClick={() => {
                    setRestoring(true);
                    setSelectedIssues([]);
                    setRestorePreview(null);
                  }}
                >
                  {bilingual(lang, "恢复…", "Restore…")}
                </button>
              )}
              {restoring && (
                <>
                  <button
                    type="button"
                    className="button button-quiet"
                    disabled={busy}
                    onClick={() => {
                      setRestoring(false);
                      setRestorePreview(null);
                    }}
                  >
                    {bilingual(lang, "取消恢复", "Cancel restore")}
                  </button>
                  {!restorePreview?.ready ? (
                    <button
                      type="button"
                      className="button button-primary"
                      disabled={
                        busy || !detail.restorable || !selectedIssues.length || !restoreReason.trim()
                      }
                      onClick={() => previewRestoreMutation.mutate()}
                    >
                      {previewRestoreMutation.isPending
                        ? bilingual(lang, "预览中…", "Previewing…")
                        : bilingual(lang, "预览恢复", "Preview restore")}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="button button-danger ra-primary-touch"
                      disabled={busy}
                      onClick={() => commitRestoreMutation.mutate()}
                    >
                      {commitRestoreMutation.isPending
                        ? bilingual(lang, "恢复中…", "Restoring…")
                        : bilingual(lang, "确认恢复", "Confirm restore")}
                    </button>
                  )}
                </>
              )}
              <button
                type="button"
                className="button button-quiet"
                disabled={busy}
                onClick={() => setOpenOpId(null)}
              >
                {bilingual(lang, "关闭", "Close")}
              </button>
            </>
          )
        }
      >
        {detailQuery.isLoading ? (
          <p className="muted">{bilingual(lang, "正在加载详情…", "Loading details…")}</p>
        ) : !detail ? (
          <p className="muted">{bilingual(lang, "未能加载详情。", "Unable to load details.")}</p>
        ) : (
          <div className="ra-modal-stack">
            <div className="ra-meta-strip">
              <span>{sourceLabel(detail.source, lang)}</span>
              <span>{detail.actor || "—"}</span>
              <span>{formatCstTime(detail.created_at, lang)} CST</span>
              <span className="trail-history-status" data-status={detail.status}>
                {statusLabel(detail.status, lang, detail.source)}
              </span>
            </div>
            {detail.reason && (
              <p className="muted">
                <strong>{bilingual(lang, "操作原因：", "Reason: ")}</strong>
                {detail.reason}
              </p>
            )}
            {restoring && (
              <div className="ra-inline-actions">
                <button
                  type="button"
                  className="button button-quiet"
                  disabled={busy}
                  onClick={() => verifyMutation.mutate(detail.id)}
                >
                  {verifyMutation.isPending
                    ? bilingual(lang, "核验中…", "Verifying…")
                    : bilingual(lang, "重新核验 Trail", "Verify Trail again")}
                </button>
              </div>
            )}
            <div className="ra-table-scroll">
              <table className="trail-history-table">
                <thead>
                  <tr>
                    {restoring && <th />}
                    <th>Issue ID</th>
                    <th>{bilingual(lang, "修改前", "Before")}</th>
                    <th>{bilingual(lang, "修改后", "After")}</th>
                    <th>{bilingual(lang, "结果", "Outcome")}</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.items.map((item) => {
                    const eligible = detail.outcomes[item.issue_id] === "succeeded";
                    const key = item.field ? "value" : "should_exclude";
                    return (
                      <tr key={item.issue_id}>
                        {restoring && (
                          <td>
                            <input
                              type="checkbox"
                              disabled={!eligible || busy}
                              checked={selectedIssues.includes(item.issue_id)}
                              onChange={(e) => {
                                setRestorePreview(null);
                                setSelectedIssues((prev) =>
                                  e.target.checked
                                    ? [...prev, item.issue_id]
                                    : prev.filter((id) => id !== item.issue_id),
                                );
                              }}
                            />
                          </td>
                        )}
                        <td>
                          <strong>{item.issue_id}</strong>
                        </td>
                        <td>{formatFieldVal(item.before, key, lang)}</td>
                        <td>{formatFieldVal(item.after, key, lang)}</td>
                        <td>{statusLabel(detail.outcomes[item.issue_id] || "unknown", lang, detail.source)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {restoring && detail.restorable && (
              <label className="ra-field-stack">
                <span>{bilingual(lang, "恢复原因", "Restore reason")}</span>
                <textarea
                  rows={2}
                  maxLength={1000}
                  value={restoreReason}
                  disabled={busy}
                  onChange={(e) => {
                    setRestoreReason(e.target.value);
                    setRestorePreview(null);
                  }}
                />
              </label>
            )}
            {restorePreview && (
              <div className="ra-disclosure-box">
                <strong>
                  {restorePreview.conflicts.length
                    ? bilingual(
                        lang,
                        `检测到冲突，未写入：${restorePreview.conflicts.join(", ")}`,
                        `Conflicts detected; nothing written: ${restorePreview.conflicts.join(", ")}`,
                      )
                    : bilingual(
                        lang,
                        `恢复预览就绪：将恢复 ${restorePreview.items.length} 个 Issue。`,
                        `Restore preview ready: ${restorePreview.items.length} Issues will be restored.`,
                      )}
                </strong>
              </div>
            )}
          </div>
        )}
      </ModalDialog>
    </section>
  );
};
