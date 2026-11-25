import React, { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  formatCstTime,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import { DEFAULT_CASE_PAGE_SIZE, Pagination } from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";
import { showWorkbenchToast } from "../features/review/reviewHelpers";
import { useWorkbench } from "../shell/WorkbenchContext";

const ROUTING_LABELS: Record<string, [string, string]> = {
  left_turn: ["左转", "Left turn"],
  right_turn: ["右转", "Right turn"],
  straight: ["直行", "Straight"],
  u_turn: ["掉头", "U-turn"],
  parking: ["泊车", "Parking"],
};

const LANE_LABELS: Record<string, [string, string]> = {
  no_lane_change: ["非变道", "No lane change"],
  left_lane_change: ["左变道", "Left lane change"],
  right_lane_change: ["右变道", "Right lane change"],
  lane_change: ["变道（旧）", "Lane change (legacy)"],
};

interface IntentSummaryRow {
  dataset_id: string;
  case_id: string;
  username: string;
  revision_id: number;
  updated_at?: string;
  completion?: { complete?: boolean; reason?: string };
  frame_counts?: {
    routing?: Record<string, number>;
    lane_change?: Record<string, number>;
  };
  comments?: Array<{ id: number; author: string; body?: string }>;
  comment_count?: number;
}

interface IntentSummaryPayload {
  dataset_ids?: string[];
  case_count: number;
  annotated_cases: number;
  complete_records: number;
  agreement?: { comparable_cases?: number; matching_cases?: number };
  label_scope?: string;
  axis?: string;
  blind_active?: boolean;
  answers_revealed?: boolean;
  owners?: string[];
  experiments?: Array<{ id: string; dataset_id: string; name: string; label_scope?: string }>;
  frame_distributions?: {
    routing?: Record<string, number>;
    lane_change?: Record<string, number>;
  };
  comment_query?: string;
  comment_hits?: Array<{
    id: number;
    dataset_id?: string;
    case_id: string;
    author: string;
    snippet?: string;
    body?: string;
    created_at?: string;
  }>;
  items: IntentSummaryRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface IntentSummaryPageProps {
  active: boolean;
  lang: UiLanguage;
}

export const IntentSummaryPage: React.FC<IntentSummaryPageProps> = ({ active, lang }) => {
  const queryClient = useQueryClient();
  const { session, selectedIntentDatasets, navigate } = useWorkbench();
  const isAdmin = Boolean(session.is_admin && session.verified);

  const [experimentId, setExperimentId] = useState("");
  const [assignees, setAssignees] = useState<string[]>([]);
  const [axis, setAxis] = useState("all");
  const [commentQuery, setCommentQuery] = useState("");
  const [revealAnswers, setRevealAnswers] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_CASE_PAGE_SIZE);
  const [selectedRows, setSelectedRows] = useState<string[]>([]);
  const [confirmDelete, setConfirmDelete] = useState<
    | { mode: "single"; row: IntentSummaryRow }
    | { mode: "bulk"; rows: IntentSummaryRow[] }
    | null
  >(null);

  const scopeKey = selectedIntentDatasets.join(",");

  const summaryQuery = useQuery<IntentSummaryPayload>({
    queryKey: [
      "intent-summary",
      scopeKey,
      experimentId,
      assignees.join(","),
      axis,
      commentQuery,
      revealAnswers,
      page,
      pageSize,
    ],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams();
      selectedIntentDatasets.forEach((id) => qs.append("dataset_id", id));
      if (experimentId) qs.set("experiment_id", experimentId);
      assignees.forEach((a) => qs.append("assignee", a));
      if (revealAnswers) qs.set("reveal_answers", "true");
      qs.set("axis", axis);
      qs.set("page", String(page));
      qs.set("page_size", String(pageSize));
      if (commentQuery.trim()) qs.set("q", commentQuery.trim());
      return apiRequest<IntentSummaryPayload>(`/api/intent-summary?${qs.toString()}`, { signal });
    },
    enabled: active && selectedIntentDatasets.length > 0,
    staleTime: 10_000,
  });

  const data = summaryQuery.data;
  const items = data?.items || [];

  const rowKey = (r: IntentSummaryRow) => `${r.dataset_id}:${r.case_id}:${r.username}:${r.revision_id}`;

  const deleteMutation = useMutation({
    mutationFn: async (target: NonNullable<typeof confirmDelete>) => {
      if (target.mode === "single") {
        const r = target.row;
        await apiRequest(
          `/api/intent-datasets/${encodeURIComponent(r.dataset_id)}/cases/${encodeURIComponent(r.case_id)}/labels/${encodeURIComponent(r.username)}?expected_revision_id=${r.revision_id}`,
          { method: "DELETE" },
        );
      } else {
        await apiRequest("/api/intent-labels/bulk-delete", {
          method: "POST",
          body: JSON.stringify({
            items: target.rows.map((r) => ({
              dataset_id: r.dataset_id,
              case_id: r.case_id,
              username: r.username,
              expected_revision_id: r.revision_id,
            })),
          }),
        });
      }
    },
    onSuccess: () => {
      setConfirmDelete(null);
      setSelectedRows([]);
      void queryClient.invalidateQueries({ queryKey: ["intent-summary"] });
      showWorkbenchToast(
        bilingual(lang, "标注已删除，历史修订与审计记录已保留。", "Annotations deleted; revision history preserved."),
      );
    },
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

  const experimentOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "", label: bilingual(lang, "全部实验", "All experiments") },
      ...(data?.experiments || []).map((e) => ({
        value: e.id,
        label: selectedIntentDatasets.length > 1 ? `${e.dataset_id} · ${e.name}` : e.name,
      })),
    ],
    [data?.experiments, selectedIntentDatasets.length, lang],
  );

  const ownerOptions = useMemo<MultiSelectOption[]>(
    () =>
      (data?.owners || []).map((u) => ({
        value: u,
        label: u === session.username ? `${u} (${bilingual(lang, "我", "Me")})` : u,
      })),
    [data?.owners, session.username, lang],
  );

  const axisOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "all", label: bilingual(lang, "Routing + 变道意图", "Routing + lane-change") },
      { value: "routing", label: bilingual(lang, "仅 Routing", "Routing only") },
      { value: "lane_change", label: bilingual(lang, "仅变道意图", "Lane-change only") },
    ],
    [lang],
  );

  const labelText = (map: Record<string, [string, string]>, key: string) =>
    map[key] ? bilingual(lang, map[key][0], map[key][1]) : key;

  const triggerExport = (view: "compact" | "expanded") => {
    const targetDs = selectedIntentDatasets[0];
    if (!targetDs) return;
    const qs = new URLSearchParams({ view, include_incomplete: "true" });
    if (experimentId) qs.set("experiment_id", experimentId);
    window.open(
      withWorkbenchBase(`/api/intent-datasets/${encodeURIComponent(targetDs)}/export?${qs.toString()}`),
      "_blank",
      "noopener",
    );
  };

  const showRouting = data?.label_scope !== "lane_change" && axis !== "lane_change";
  const showLane = data?.label_scope !== "routing" && axis !== "routing";

  return (
    <section
      id="intentSummaryPage"
      className="app-page ra-react-page"
      data-page="intent-summary"
      data-react-island="intent-summary"
    >
      <div className="panel-card">
        <div className="ra-page-header-row">
          <div>
            <h2>{bilingual(lang, "意图标注汇总", "Intent Labeling Summary")}</h2>
            <p className="muted">
              {data?.blind_active && !data.answers_revealed
                ? bilingual(lang, "进行中的盲标实验仅显示自己的答案。", "Active blind experiment shows your own labels only.")
                : bilingual(lang, "汇总当前标注头；不会加载 Camera / BEV 图片。", "Summarizes current label heads without loading media frames.")}
            </p>
          </div>
          <div className="ra-inline-actions">
            {isAdmin && data?.blind_active && (
              <button
                type="button"
                className="button button-quiet"
                onClick={() => setRevealAnswers((v) => !v)}
              >
                {revealAnswers
                  ? bilingual(lang, "恢复盲态", "Restore blind mode")
                  : bilingual(lang, "管理员解盲", "Admin reveal")}
              </button>
            )}
            {isAdmin && (
              <>
                <button type="button" className="button button-quiet" onClick={() => triggerExport("compact")}>
                  {bilingual(lang, "导出精简版", "Export compact")}
                </button>
                <button type="button" className="button button-quiet" onClick={() => triggerExport("expanded")}>
                  {bilingual(lang, "导出展开版", "Export expanded")}
                </button>
              </>
            )}
            <button
              type="button"
              className="button button-quiet"
              disabled={summaryQuery.isFetching}
              onClick={() => void summaryQuery.refetch()}
            >
              {bilingual(lang, "刷新", "Refresh")}
            </button>
          </div>
        </div>

        <div className="ra-filter-grid" style={{ marginTop: 12 }}>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "实验", "Experiment")}</span>
            <UiSelect
              id="raIntentSummaryExp"
              value={experimentId}
              options={experimentOptions}
              ariaLabel={bilingual(lang, "按实验筛选", "Filter by experiment")}
              onChange={(v) => {
                setExperimentId(v);
                setAssignees([]);
                setPage(1);
                setSelectedRows([]);
              }}
            />
          </div>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "标注人", "Labeler")}</span>
            <MultiSelect
              id="raIntentSummaryOwners"
              options={ownerOptions}
              values={assignees}
              lang={lang}
              showOnlyThis
              placeholder={bilingual(lang, "全部标注人", "All labelers")}
              ariaLabel={bilingual(lang, "按标注人筛选", "Filter by labeler")}
              onChange={(vals) => {
                setAssignees(vals);
                setPage(1);
                setSelectedRows([]);
              }}
            />
          </div>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "维度", "Axis")}</span>
            <UiSelect
              id="raIntentSummaryAxis"
              value={axis}
              options={axisOptions}
              ariaLabel={bilingual(lang, "选择维度", "Select axis")}
              onChange={(v) => {
                setAxis(v);
                setPage(1);
              }}
            />
          </div>
          <label className="ra-field-stack">
            <span>{bilingual(lang, "搜索评论", "Search comments")}</span>
            <input
              type="search"
              value={commentQuery}
              placeholder={bilingual(lang, "输入评论关键词", "Keyword in comments")}
              onChange={(e) => {
                setCommentQuery(e.target.value);
                setPage(1);
              }}
            />
          </label>
        </div>

        {data && (
          <div className="ra-kpi-grid" style={{ marginTop: 14 }}>
            <div className="ra-kpi-card">
              <span>{bilingual(lang, "范围 Case", "Scope Cases")}</span>
              <strong>{data.case_count}</strong>
            </div>
            <div className="ra-kpi-card">
              <span>{bilingual(lang, "已标注 Case", "Annotated Cases")}</span>
              <strong>{data.annotated_cases}</strong>
            </div>
            <div className="ra-kpi-card">
              <span>{bilingual(lang, "完整标注记录", "Complete records")}</span>
              <strong>{data.complete_records}</strong>
            </div>
            <div className="ra-kpi-card">
              <span>{bilingual(lang, "多人一致性", "Agreement")}</span>
              <strong>
                {data.agreement?.comparable_cases
                  ? `${data.agreement.matching_cases} / ${data.agreement.comparable_cases}`
                  : "—"}
              </strong>
            </div>
          </div>
        )}
      </div>

      {/* Results Table */}
      <div className="panel-card">
        {isAdmin && selectedRows.length > 0 && (
          <div className="ra-inline-actions" style={{ marginBottom: 10 }}>
            <button
              type="button"
              className="button button-danger"
              onClick={() => {
                const picked = items.filter((r) => selectedRows.includes(rowKey(r)));
                if (picked.length) setConfirmDelete({ mode: "bulk", rows: picked });
              }}
            >
              {bilingual(lang, `批量删除 (${selectedRows.length})`, `Bulk delete (${selectedRows.length})`)}
            </button>
          </div>
        )}

        {summaryQuery.isLoading ? (
          <div className="no-asset">{bilingual(lang, "正在加载汇总…", "Loading summary…")}</div>
        ) : (
          <>
            <div className="ra-table-scroll">
              <table className="trail-history-table">
                <thead>
                  <tr>
                    {isAdmin && <th />}
                    <th>Case</th>
                    <th>{bilingual(lang, "标注人", "Labeler")}</th>
                    <th>{bilingual(lang, "完整度", "Completion")}</th>
                    {showRouting && <th>Routing</th>}
                    {showLane && <th>{bilingual(lang, "变道意图", "Lane change")}</th>}
                    <th>{bilingual(lang, "更新时间", "Updated")}</th>
                    {isAdmin && <th>{bilingual(lang, "操作", "Action")}</th>}
                  </tr>
                </thead>
                <tbody>
                  {!items.length ? (
                    <tr>
                      <td colSpan={8}>
                        {bilingual(lang, "当前筛选下没有已标注结果。", "No annotations match the current filters.")}
                      </td>
                    </tr>
                  ) : (
                    items.map((row) => {
                      const k = rowKey(row);
                      return (
                        <tr key={k}>
                          {isAdmin && (
                            <td>
                              <input
                                type="checkbox"
                                checked={selectedRows.includes(k)}
                                onChange={(e) =>
                                  setSelectedRows((prev) =>
                                    e.target.checked ? [...prev, k] : prev.filter((x) => x !== k),
                                  )
                                }
                              />
                            </td>
                          )}
                          <td>
                            <button
                              type="button"
                              className="button button-quiet"
                              onClick={() =>
                                navigate("intent", { dataset: row.dataset_id, case: row.case_id })
                              }
                            >
                              {row.case_id}
                            </button>
                          </td>
                          <td>
                            {row.username}
                            {row.username === session.username ? bilingual(lang, "（我）", " (Me)") : ""}
                          </td>
                          <td>
                            <strong>
                              {row.completion?.complete
                                ? bilingual(lang, "完整", "Complete")
                                : bilingual(lang, "部分", "Partial")}
                            </strong>
                          </td>
                          {showRouting && (
                            <td>
                              {Object.entries(row.frame_counts?.routing || {})
                                .filter(([, c]) => c > 0)
                                .map(([v, c]) => `${labelText(ROUTING_LABELS, v)} ${c}`)
                                .join(" · ") || "—"}
                            </td>
                          )}
                          {showLane && (
                            <td>
                              {Object.entries(row.frame_counts?.lane_change || {})
                                .filter(([, c]) => c > 0)
                                .map(([v, c]) => `${labelText(LANE_LABELS, v)} ${c}`)
                                .join(" · ") || "—"}
                            </td>
                          )}
                          <td>{formatCstTime(row.updated_at, lang)}</td>
                          {isAdmin && (
                            <td>
                              <button
                                type="button"
                                className="button button-quiet"
                                onClick={() => setConfirmDelete({ mode: "single", row })}
                              >
                                {bilingual(lang, "删除", "Delete")}
                              </button>
                            </td>
                          )}
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {(data?.total || 0) > 0 && (
              <Pagination
                page={page}
                pageSize={pageSize}
                total={data!.total}
                lang={lang}
                loading={summaryQuery.isFetching}
                ariaLabel={bilingual(lang, "意图标注汇总分页", "Intent summary pagination")}
                onPageChange={(next) => {
                  setPage(next);
                  setSelectedRows([]);
                }}
                onPageSizeChange={(nextSize) => {
                  setPageSize(nextSize);
                  setPage(1);
                  setSelectedRows([]);
                }}
              />
            )}
          </>
        )}
      </div>

      <ModalDialog
        open={Boolean(confirmDelete)}
        title={bilingual(lang, "确认删除标注", "Confirm Delete Annotations")}
        lang={lang}
        onClose={() => {
          if (!deleteMutation.isPending) setConfirmDelete(null);
        }}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              disabled={deleteMutation.isPending}
              onClick={() => setConfirmDelete(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-danger"
              disabled={deleteMutation.isPending}
              onClick={() => confirmDelete && deleteMutation.mutate(confirmDelete)}
            >
              {deleteMutation.isPending
                ? bilingual(lang, "删除中…", "Deleting…")
                : bilingual(lang, "确认删除", "Confirm delete")}
            </button>
          </>
        }
      >
        <p>
          {confirmDelete?.mode === "bulk"
            ? bilingual(
                lang,
                `确认批量删除选中的 ${confirmDelete.rows.length} 条当前标注？历史修订仍保留。`,
                `Delete ${confirmDelete.rows.length} selected annotations? Revision history is preserved.`,
              )
            : bilingual(
                lang,
                `确认删除 ${confirmDelete?.row.username || ""} 在 ${confirmDelete?.row.case_id || ""} 的标注？`,
                `Delete annotation by ${confirmDelete?.row.username || ""} on ${confirmDelete?.row.case_id || ""}?`,
              )}
        </p>
      </ModalDialog>
    </section>
  );
};
