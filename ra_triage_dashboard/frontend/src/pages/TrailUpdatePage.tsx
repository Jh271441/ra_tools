import React, { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, formatCstTime, UiLanguage } from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { DEFAULT_CASE_PAGE_SIZE, Pagination } from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";
import {
  displayLabelText,
  labelBadgeClass,
  parseIssueIdsInput,
  showWorkbenchToast,
} from "../features/review/reviewHelpers";

interface TrailUpdateRow {
  issue_id: string;
  title?: string;
  gt_label?: string;
  baseline_id?: string;
  baseline_scope?: string;
  source_kind?: string;
  comment?: string;
  trail_update_status?: string;
  readonly?: boolean;
  review?: { reviewer?: string; status?: string; note?: string };
  model?: { label?: string };
  trail_detail?: {
    local_comment?: string;
    trail_comment?: string;
    remote_excluded?: boolean | null;
  };
}

interface TrailPreviewPayload {
  items?: TrailUpdateRow[];
  baselines?: string[];
  payload_sha256?: string;
  write_status?: string;
  write_ready?: boolean;
  local_candidate_count?: number;
  target_field?: string;
  target_path?: string;
  trail_capability?: { status?: string; message?: string; fields_visible?: string[] };
  draft?: unknown;
}

interface DirectIssueEntry {
  id: number;
  issueIds: string;
  comment: string;
}

interface DirectPreviewPayload {
  items?: Array<{
    issue_id: string;
    baseline_id?: string;
    baseline_scope?: string;
    current_label?: string;
    current_should_exclude?: boolean;
    comment?: string;
    trail_update_status?: string;
  }>;
  requested_issue_ids?: string[];
  requested_entries?: Array<{ issue_id: string; comment: string }>;
  missing_issue_ids?: string[];
  invalid_issue_ids?: string[];
  payload_sha256?: string;
  write_status?: string;
  write_ready?: boolean;
  pending_count?: number;
  trail_capability?: { status?: string; message?: string };
  draft?: unknown;
}

interface IssueHistoryRow {
  operation_id?: string;
  status?: string;
  requested_count?: number;
  synced_count?: number;
  failed_count?: number;
  actor?: string;
  created_at?: string;
  message?: string;
  entries?: Array<{ issue_id?: string; comment?: string; status?: string; detail?: string }>;
}

export interface TrailUpdatePageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
}

let rowSeq = 1;

export const TrailUpdatePage: React.FC<TrailUpdatePageProps> = ({
  active,
  lang,
  selectedBaselines,
}) => {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"review" | "issue">(() => {
    if (typeof window === "undefined") return "review";
    return new URLSearchParams(window.location.search).get("tab") === "issue" ? "issue" : "review";
  });

  // Review tab state
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_CASE_PAGE_SIZE);
  const [selectedIssues, setSelectedIssues] = useState<string[]>([]);
  const [selectionIntent, setSelectionIntent] = useState<"exclude" | "reason_only" | "unexclude">("exclude");
  const [confirmSelectionPreview, setConfirmSelectionPreview] = useState<{
    payload_sha256?: string;
    items?: Array<{ issue_id: string }>;
  } | null>(null);
  const [jsonModalText, setJsonModalText] = useState<string | null>(null);

  // Direct Issue ID tab state
  const [directRows, setDirectRows] = useState<DirectIssueEntry[]>(() => {
    const prefill =
      typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("exclude_issue") || "" : "";
    return [{ id: rowSeq++, issueIds: prefill, comment: "" }];
  });
  const [directPreview, setDirectPreview] = useState<DirectPreviewPayload | null>(null);
  const [directConfirmOpen, setDirectConfirmOpen] = useState(false);

  const baselinesCsv = selectedBaselines.join(",");

  const reviewPreviewQuery = useQuery<TrailPreviewPayload>({
    queryKey: ["trail-update-preview", baselinesCsv],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams();
      if (baselinesCsv) qs.set("baselines", baselinesCsv);
      return apiRequest<TrailPreviewPayload>(
        `/api/trail-attribute-update/preview${qs.toString() ? `?${qs.toString()}` : ""}`,
        { signal },
      );
    },
    enabled: active && tab === "review" && Boolean(baselinesCsv),
    staleTime: 15_000,
  });

  const issueHistoryQuery = useQuery<{ items?: IssueHistoryRow[] }>({
    queryKey: ["trail-issue-history"],
    queryFn: ({ signal }) =>
      apiRequest("/api/trail-attribute-update/issue-history?limit=20", { signal }),
    enabled: active && tab === "issue",
    staleTime: 15_000,
  });

  const filteredItems = useMemo(() => {
    const items = reviewPreviewQuery.data?.items || [];
    const q = search.trim().toLowerCase();
    return items.filter((item) => {
      if (statusFilter && (item.trail_update_status || "pending") !== statusFilter) return false;
      if (!q) return true;
      return [
        item.issue_id,
        item.title,
        item.comment,
        item.review?.reviewer,
        item.trail_detail?.local_comment,
        item.trail_detail?.trail_comment,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(q);
    });
  }, [reviewPreviewQuery.data, search, statusFilter]);

  const pageCount = Math.max(1, Math.ceil(filteredItems.length / pageSize));
  const safePage = Math.max(1, Math.min(pageCount, page));
  const visibleItems = useMemo(
    () => filteredItems.slice((safePage - 1) * pageSize, safePage * pageSize),
    [filteredItems, safePage, pageSize],
  );

  const selectionPreviewMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ payload_sha256?: string; items?: Array<{ issue_id: string }> }>(
        "/api/trail-attribute-update/selection-preview",
        {
          method: "POST",
          body: JSON.stringify({
            issue_ids: selectedIssues,
            intent: selectionIntent,
            baselines: reviewPreviewQuery.data?.baselines || selectedBaselines,
          }),
        },
      ),
    onSuccess: (res) => setConfirmSelectionPreview(res),
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

  const selectionCommitMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ ok?: boolean; readback?: { verified_count?: number } }>(
        "/api/trail-attribute-update/selection-commit",
        {
          method: "POST",
          body: JSON.stringify({
            confirm: true,
            payload_sha256: confirmSelectionPreview?.payload_sha256,
          }),
        },
      ),
    onSuccess: (res) => {
      setConfirmSelectionPreview(null);
      setSelectedIssues([]);
      void queryClient.invalidateQueries({ queryKey: ["trail-update-preview"] });
      showWorkbenchToast(
        bilingual(
          lang,
          `Trail 已验证 ${res.readback?.verified_count ?? 0} 条更新。`,
          `Trail verified ${res.readback?.verified_count ?? 0} updates.`,
        ),
        !res.ok,
      );
    },
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

  const collectedDirectEntries = useMemo(() => {
    const entries: Array<{ issue_id: string; comment: string }> = [];
    const seen = new Set<string>();
    const invalid: string[] = [];
    for (const row of directRows) {
      if (!row.issueIds.trim() && !row.comment.trim()) continue;
      const parsed = parseIssueIdsInput(row.issueIds);
      invalid.push(...parsed.invalid);
      for (const id of parsed.ids) {
        if (seen.has(id)) continue;
        seen.add(id);
        entries.push({ issue_id: id, comment: row.comment.trim().slice(0, 4000) });
      }
    }
    return { entries, invalid };
  }, [directRows]);

  const directPreviewMutation = useMutation({
    mutationFn: () =>
      apiRequest<DirectPreviewPayload>("/api/trail-attribute-update/issue-preview", {
        method: "POST",
        body: JSON.stringify({ entries: collectedDirectEntries.entries }),
      }),
    onSuccess: (res) => {
      setDirectPreview(res);
      showWorkbenchToast(
        bilingual(
          lang,
          `已生成屏蔽预览：${res.items?.length ?? 0} 条可写。`,
          `Shield preview ready: ${res.items?.length ?? 0} writable.`,
        ),
      );
    },
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

  const directCommitMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ ok?: boolean; stats?: { success_count?: number; failed_count?: number } }>(
        "/api/trail-attribute-update/issue-commit",
        {
          method: "POST",
          body: JSON.stringify({
            confirm: true,
            entries: directPreview?.requested_entries || collectedDirectEntries.entries,
            payload_sha256: directPreview?.payload_sha256,
          }),
        },
      ),
    onSuccess: (res) => {
      setDirectConfirmOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["trail-issue-history"] });
      void queryClient.invalidateQueries({ queryKey: ["trail-update-preview"] });
      showWorkbenchToast(
        bilingual(
          lang,
          `屏蔽完成：成功 ${res.stats?.success_count ?? 0}，失败 ${res.stats?.failed_count ?? 0}。`,
          `Shield finished: ${res.stats?.success_count ?? 0} ok, ${res.stats?.failed_count ?? 0} failed.`,
        ),
        !res.ok,
      );
    },
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

  const statusOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "", label: bilingual(lang, "全部同步状态", "All sync states") },
      { value: "pending", label: bilingual(lang, "待提交", "Pending") },
      { value: "synced", label: bilingual(lang, "已同步", "Synced") },
      { value: "conflict", label: bilingual(lang, "存在差异", "Conflict") },
    ],
    [lang],
  );

  const intentOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "exclude", label: bilingual(lang, "排除所选案例", "Exclude selected") },
      { value: "reason_only", label: bilingual(lang, "仅更新理由", "Reasons only") },
      { value: "unexclude", label: bilingual(lang, "同步不排除", "Sync non-exclusion") },
    ],
    [lang],
  );

  const writeReady = Boolean(
    reviewPreviewQuery.data &&
      (reviewPreviewQuery.data.write_status === "ready" || reviewPreviewQuery.data.write_ready),
  );
  const directWriteReady = Boolean(
    directPreview && (directPreview.write_status === "ready" || directPreview.write_ready),
  );

  return (
    <section
      id="trailAttributeUpdatePage"
      className="app-page ra-react-page"
      data-page="trail-update"
      data-react-island="trail-update"
    >
      <div className="panel-card">
        <div className="ra-page-header-row">
          <div>
            <h2>{bilingual(lang, "问题排除与 Trail 属性同步", "Issue Exclusion & Trail Sync")}</h2>
            <p className="muted">
              {bilingual(
                lang,
                "支持从 Review 排除汇总同步，或按 Issue ID 直接生成预览并写入 info 字段。",
                "Sync exclusions from Review summary or shield Issues directly by ID (info-only deep merge).",
              )}
            </p>
          </div>
          <div className="ra-inline-actions" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "review"}
              className={`button ${tab === "review" ? "button-primary" : "button-quiet"}`}
              onClick={() => setTab("review")}
            >
              {bilingual(lang, "Review 排除汇总", "Review summary")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "issue"}
              className={`button ${tab === "issue" ? "button-primary" : "button-quiet"}`}
              onClick={() => setTab("issue")}
            >
              {bilingual(lang, "按 Issue ID 屏蔽", "Shield by Issue ID")}
            </button>
          </div>
        </div>
      </div>

      {tab === "review" ? (
        <div className="panel-card">
          <div className="ra-filter-grid">
            <label className="ra-field-stack">
              <span>{bilingual(lang, "搜索", "Search")}</span>
              <input
                type="search"
                value={search}
                placeholder={bilingual(lang, "Issue ID、理由或作者", "Issue ID, reason, or author")}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
            </label>
            <div className="ra-field-stack">
              <span>{bilingual(lang, "同步状态", "Sync state")}</span>
              <UiSelect
                id="raTrailUpdateStatus"
                value={statusFilter}
                options={statusOptions}
                ariaLabel={bilingual(lang, "按同步状态筛选", "Filter by sync state")}
                onChange={(v) => {
                  setStatusFilter(v);
                  setPage(1);
                }}
              />
            </div>
            <div className="ra-field-stack">
              <span>{bilingual(lang, "提交动作", "Commit intent")}</span>
              <UiSelect
                id="raTrailUpdateIntent"
                value={selectionIntent}
                options={intentOptions}
                ariaLabel={bilingual(lang, "提交动作类型", "Commit intent")}
                onChange={(v) => setSelectionIntent(v as "exclude" | "reason_only" | "unexclude")}
              />
            </div>
            <div className="ra-inline-actions" style={{ alignItems: "flex-end" }}>
              <button
                type="button"
                className="button button-quiet"
                disabled={!reviewPreviewQuery.data?.draft}
                onClick={() =>
                  setJsonModalText(JSON.stringify(reviewPreviewQuery.data?.draft || {}, null, 2))
                }
              >
                {bilingual(lang, "查看 JSON", "Preview JSON")}
              </button>
              <button
                type="button"
                className="button button-primary"
                disabled={!writeReady || !selectedIssues.length || selectionPreviewMutation.isPending}
                onClick={() => selectionPreviewMutation.mutate()}
              >
                {bilingual(
                  lang,
                  `预览并提交 (${selectedIssues.length})`,
                  `Preview & commit (${selectedIssues.length})`,
                )}
              </button>
            </div>
          </div>

          <div className="ra-table-scroll" style={{ marginTop: 14 }}>
            <table className="trail-history-table">
              <thead>
                <tr>
                  <th />
                  <th>Issue ID</th>
                  <th>GT</th>
                  <th>{bilingual(lang, "模型输出", "Model")}</th>
                  <th>{bilingual(lang, "排除说明", "Exclusion note")}</th>
                  <th>{bilingual(lang, "状态", "Status")}</th>
                </tr>
              </thead>
              <tbody>
                {reviewPreviewQuery.isLoading ? (
                  <tr>
                    <td colSpan={6}>{bilingual(lang, "正在加载排除案例…", "Loading excluded cases…")}</td>
                  </tr>
                ) : !visibleItems.length ? (
                  <tr>
                    <td colSpan={6}>
                      {bilingual(lang, "当前筛选没有匹配的排除案例。", "No excluded cases match.")}
                    </td>
                  </tr>
                ) : (
                  visibleItems.map((item) => (
                    <tr key={item.issue_id}>
                      <td>
                        <input
                          type="checkbox"
                          disabled={Boolean(item.readonly)}
                          checked={selectedIssues.includes(item.issue_id)}
                          onChange={(e) =>
                            setSelectedIssues((prev) =>
                              e.target.checked
                                ? [...prev, item.issue_id]
                                : prev.filter((x) => x !== item.issue_id),
                            )
                          }
                        />
                      </td>
                      <td>
                        <strong>{item.issue_id}</strong>
                      </td>
                      <td>
                        <span className={labelBadgeClass(item.gt_label)}>
                          {displayLabelText(item.gt_label, lang)}
                        </span>
                      </td>
                      <td>
                        <span className={labelBadgeClass(item.model?.label)}>
                          {displayLabelText(item.model?.label, lang)}
                        </span>
                      </td>
                      <td>{item.comment || item.trail_detail?.local_comment || "—"}</td>
                      <td>{item.trail_update_status || "pending"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {filteredItems.length > 0 && (
            <Pagination
              page={safePage}
              pageSize={pageSize}
              total={filteredItems.length}
              lang={lang}
              loading={reviewPreviewQuery.isFetching}
              ariaLabel={bilingual(lang, "排除案例分页", "Excluded cases pagination")}
              onPageChange={(p) => {
                setPage(p);
                setSelectedIssues([]);
              }}
              onPageSizeChange={(n) => {
                setPageSize(n);
                setPage(1);
                setSelectedIssues([]);
              }}
            />
          )}
        </div>
      ) : (
        <>
          <div className="panel-card">
            <h3>{bilingual(lang, "按 Issue ID 批量屏蔽", "Direct Shielding by Issue ID")}</h3>
            <div className="ra-modal-stack" style={{ marginTop: 10 }}>
              {directRows.map((row) => (
                <div key={row.id} className="trail-update-entry-row">
                  <label className="ra-field-stack">
                    <span>{bilingual(lang, "Issue ID（可多个）", "Issue IDs (multiple)")}</span>
                    <textarea
                      rows={2}
                      value={row.issueIds}
                      placeholder="cn32171803, cn31994663"
                      onChange={(e) => {
                        setDirectPreview(null);
                        setDirectRows((prev) =>
                          prev.map((r) => (r.id === row.id ? { ...r, issueIds: e.target.value } : r)),
                        );
                      }}
                    />
                  </label>
                  <label className="ra-field-stack">
                    <span>{bilingual(lang, "排除说明（可选）", "Exclusion note (optional)")}</span>
                    <textarea
                      rows={2}
                      value={row.comment}
                      onChange={(e) => {
                        setDirectPreview(null);
                        setDirectRows((prev) =>
                          prev.map((r) => (r.id === row.id ? { ...r, comment: e.target.value } : r)),
                        );
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    className="button button-quiet"
                    disabled={directRows.length <= 1}
                    aria-label={bilingual(lang, "删除此行", "Remove row")}
                    onClick={() => {
                      setDirectPreview(null);
                      setDirectRows((prev) => prev.filter((r) => r.id !== row.id));
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>

            <div className="ra-inline-actions" style={{ marginTop: 12 }}>
              <button
                type="button"
                className="button button-quiet"
                onClick={() =>
                  setDirectRows((prev) => [...prev, { id: rowSeq++, issueIds: "", comment: "" }])
                }
              >
                + {bilingual(lang, "添加一行", "Add row")}
              </button>
              <button
                type="button"
                className="button button-quiet"
                onClick={() => {
                  setDirectRows([{ id: rowSeq++, issueIds: "", comment: "" }]);
                  setDirectPreview(null);
                }}
              >
                {bilingual(lang, "清空", "Clear")}
              </button>
              <button
                type="button"
                className="button button-primary"
                disabled={
                  !collectedDirectEntries.entries.length ||
                  collectedDirectEntries.invalid.length > 0 ||
                  directPreviewMutation.isPending
                }
                onClick={() => directPreviewMutation.mutate()}
              >
                {directPreviewMutation.isPending
                  ? bilingual(lang, "检查中…", "Checking…")
                  : bilingual(
                      lang,
                      `生成预览 (${collectedDirectEntries.entries.length})`,
                      `Build preview (${collectedDirectEntries.entries.length})`,
                    )}
              </button>
              {directPreview && (
                <button
                  type="button"
                  className="button button-danger"
                  disabled={!directWriteReady || directCommitMutation.isPending}
                  onClick={() => setDirectConfirmOpen(true)}
                >
                  {bilingual(lang, "提交屏蔽到 Trail", "Commit shield to Trail")}
                </button>
              )}
            </div>

            {directPreview && (
              <div className="ra-table-scroll" style={{ marginTop: 14 }}>
                <table className="trail-history-table">
                  <thead>
                    <tr>
                      <th>Issue</th>
                      <th>{bilingual(lang, "版本", "Release")}</th>
                      <th>{bilingual(lang, "当前模型输出", "Model")}</th>
                      <th>{bilingual(lang, "当前状态", "Current state")}</th>
                      <th>{bilingual(lang, "排除说明", "Note")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(directPreview.items || []).map((it) => (
                      <tr key={it.issue_id}>
                        <td><strong>{it.issue_id}</strong></td>
                        <td>{it.baseline_id || it.baseline_scope || "—"}</td>
                        <td>{displayLabelText(it.current_label, lang)}</td>
                        <td>
                          {it.current_should_exclude
                            ? bilingual(lang, "已屏蔽", "Shielded")
                            : bilingual(lang, "未屏蔽", "Not shielded")}
                        </td>
                        <td>{it.comment || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="panel-card">
            <h3>{bilingual(lang, "最近 Issue ID 屏蔽记录", "Recent Shielding History")}</h3>
            {issueHistoryQuery.isLoading ? (
              <p className="muted">{bilingual(lang, "正在加载历史…", "Loading history…")}</p>
            ) : !(issueHistoryQuery.data?.items || []).length ? (
              <p className="muted">{bilingual(lang, "暂无记录。", "No records yet.")}</p>
            ) : (
              <div className="ra-modal-stack" style={{ marginTop: 10 }}>
                {issueHistoryQuery.data!.items!.map((h, i) => (
                  <details key={h.operation_id || i} className="ra-disclosure-box">
                    <summary>
                      <strong>{h.requested_count ?? 0} Issues</strong> · {h.synced_count ?? 0}/
                      {h.requested_count ?? 0} · {h.actor || "—"} · {formatCstTime(h.created_at, lang)}
                    </summary>
                    <p className="muted">{h.message || "—"}</p>
                  </details>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* Selection Commit Confirm Modal */}
      <ModalDialog
        open={Boolean(confirmSelectionPreview)}
        title={bilingual(lang, "确认提交所选排除改动到 Trail", "Confirm Trail Update")}
        lang={lang}
        onClose={() => {
          if (!selectionCommitMutation.isPending) setConfirmSelectionPreview(null);
        }}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => setConfirmSelectionPreview(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-danger"
              disabled={selectionCommitMutation.isPending}
              onClick={() => selectionCommitMutation.mutate()}
            >
              {bilingual(lang, "确认写入 Trail", "Confirm write to Trail")}
            </button>
          </>
        }
      >
        <p>
          {bilingual(
            lang,
            `即将提交 ${confirmSelectionPreview?.items?.length ?? selectedIssues.length} 个 Issue 的排除状态/说明到 Trail（指纹 ${String(confirmSelectionPreview?.payload_sha256 || "").slice(0, 12)}…）。确认继续？`,
            `Commit ${confirmSelectionPreview?.items?.length ?? selectedIssues.length} Issues to Trail (fingerprint ${String(confirmSelectionPreview?.payload_sha256 || "").slice(0, 12)}…). Continue?`,
          )}
        </p>
      </ModalDialog>

      {/* Direct Shield Confirm Modal */}
      <ModalDialog
        open={directConfirmOpen}
        title={bilingual(lang, "确认提交 Issue 屏蔽", "Confirm Issue Shielding")}
        lang={lang}
        onClose={() => {
          if (!directCommitMutation.isPending) setDirectConfirmOpen(false);
        }}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => setDirectConfirmOpen(false)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-danger"
              disabled={directCommitMutation.isPending}
              onClick={() => directCommitMutation.mutate()}
            >
              {bilingual(lang, "确认屏蔽", "Confirm shield")}
            </button>
          </>
        }
      >
        <p>
          {bilingual(
            lang,
            `将对 ${directPreview?.pending_count ?? directPreview?.items?.length ?? 0} 个 Issue 写入 info 排除标记（不改模型 label）。继续？`,
            `Write info exclusion marker for ${directPreview?.pending_count ?? directPreview?.items?.length ?? 0} Issues (model labels unchanged). Continue?`,
          )}
        </p>
      </ModalDialog>

      {/* JSON Preview Modal */}
      <ModalDialog
        open={Boolean(jsonModalText)}
        title={bilingual(lang, "JSON 草稿预览", "JSON Draft Preview")}
        lang={lang}
        onClose={() => setJsonModalText(null)}
      >
        <pre className="ra-code-block">{jsonModalText}</pre>
      </ModalDialog>
    </section>
  );
};
