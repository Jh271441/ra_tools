import React, { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, UiLanguage, withWorkbenchBase } from "../bridge/useWorkbenchBridge";
import { IssueDiscussion } from "../components/discussion/IssueDiscussion";
import { ModalDialog } from "../components/ui/ModalDialog";
import { DEFAULT_CASE_PAGE_SIZE, Pagination } from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";
import { showWorkbenchToast } from "../features/review/reviewHelpers";
import { useWorkbench } from "../shell/WorkbenchContext";

interface CampaignSummary {
  id: string;
  name?: string;
  purpose?: string;
  lifecycle: string;
  task_group_id?: string;
  baseline_scopes?: string[];
  workset_baseline_scope?: string;
  reference_type?: string;
  reference_id?: string;
  config_revision?: number;
  legacy_read_only?: boolean;
  progress?: {
    member_count?: number;
    assigned_issue_count?: number;
    completed_issue_count?: number;
    required_submitter_count?: number;
    submitted_submitter_count?: number;
    pending_issue_count?: number;
    conflict_issue_count?: number;
  };
}

interface CampaignListPayload {
  items?: CampaignSummary[];
  historical_imports?: Array<{
    id: string;
    name?: string;
    baseline_scope?: string;
    stats?: Record<string, number>;
  }>;
}

interface CampaignIssueRow {
  issue_id: string;
  title?: string;
  scenario?: string;
  baseline_scope?: string;
  reference_label?: string;
  gt_label?: string;
  expected_output?: string;
  is_excluded?: boolean;
  submitted?: number;
  required_submitter_count?: number;
  state: string;
  assignments?: Array<{ assignee: string; assignment_kind?: string }>;
}

interface CampaignDetailPayload {
  campaign: CampaignSummary;
  progress: CampaignSummary["progress"];
  assignees?: Array<{
    name: string;
    assigned_slots: number;
    submitted_slots: number;
    completed_slots: number;
  }>;
  issues?: CampaignIssueRow[];
  total?: number;
  page?: number;
  page_count?: number;
  close_snapshot?: {
    id: string;
    config_revision: number;
    completed_issue_count: number;
    assigned_issue_count: number;
    closed_at?: string;
  };
}

export interface CampaignsPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
  isAdmin: boolean;
}

function campaignStateText(value: string | undefined, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    labeling: ["标注实验", "Labeling experiment"],
    model_review: ["复核任务", "Review task"],
    active: ["进行中", "Active"],
    draft: ["草稿", "Draft"],
    closed: ["已关闭", "Closed"],
    cancelled: ["已取消", "Cancelled"],
    superseded: ["已替代", "Superseded"],
    pending: ["待处理", "Pending"],
    in_progress: ["进行中", "In progress"],
    completed: ["已完成", "Completed"],
    conflict: ["冲突", "Conflict"],
    adjudicated: ["已裁决", "Adjudicated"],
  };
  return value && map[value] ? bilingual(lang, map[value][0], map[value][1]) : value || "—";
}

export const CampaignsPage: React.FC<CampaignsPageProps> = ({
  active,
  lang,
  selectedBaselines,
  isAdmin,
}) => {
  const queryClient = useQueryClient();
  const { navigate, session } = useWorkbench();
  const [selectedCampaignId, setSelectedCampaignId] = useState<string>(() =>
    typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("campaign") || "" : "",
  );
  const [purpose, setPurpose] = useState<string>(() =>
    typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("purpose") || "" : "",
  );
  const [lifecycle, setLifecycle] = useState("current");
  const [search, setSearch] = useState("");
  const [issuePage, setIssuePage] = useState(1);
  const [issuePageSize, setIssuePageSize] = useState(DEFAULT_CASE_PAGE_SIZE);
  const [issueAssignee, setIssueAssignee] = useState("");
  const [issueState, setIssueState] = useState("all");
  const [issueSearch, setIssueSearch] = useState("");
  const [lifecycleAction, setLifecycleAction] = useState<string | null>(null);
  const [lifecycleReason, setLifecycleReason] = useState("");
  const [discussionIssueId, setDiscussionIssueId] = useState<string | null>(null);

  const baselinesCsv = selectedBaselines.join(",");

  const listQuery = useQuery<CampaignListPayload>({
    queryKey: ["campaigns-list", baselinesCsv, purpose, lifecycle, search],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        baselines: baselinesCsv,
        lifecycle,
        page: "1",
        page_size: "50",
      });
      if (purpose) qs.set("purpose", purpose);
      if (search.trim()) qs.set("q", search.trim());
      return apiRequest<CampaignListPayload>(`/api/campaigns?${qs.toString()}`, { signal });
    },
    enabled: active && !selectedCampaignId,
    staleTime: 15_000,
  });

  const detailQuery = useQuery<CampaignDetailPayload>({
    queryKey: [
      "campaign-detail",
      selectedCampaignId,
      issuePage,
      issuePageSize,
      issueAssignee,
      issueState,
      issueSearch,
    ],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        page: String(issuePage),
        page_size: String(issuePageSize),
        state: issueState,
      });
      if (issueAssignee) qs.set("assignee", issueAssignee);
      if (issueSearch.trim()) qs.set("q", issueSearch.trim());
      return apiRequest<CampaignDetailPayload>(
        `/api/campaigns/${encodeURIComponent(selectedCampaignId)}?${qs.toString()}`,
        { signal },
      );
    },
    enabled: active && Boolean(selectedCampaignId),
    staleTime: 10_000,
  });

  const lifecycleMutation = useMutation({
    mutationFn: async () => {
      const camp = detailQuery.data?.campaign;
      if (!camp || !lifecycleAction) return;
      const key = globalThis.crypto?.randomUUID?.() || `camp-${Date.now()}`;
      return apiRequest(`/api/campaigns/${encodeURIComponent(camp.id)}/${lifecycleAction}`, {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({
          expected_revision: Number(camp.config_revision || 1),
          idempotency_key: key,
          reason: lifecycleReason.trim() || bilingual(lang, "从实验管理页操作", "Updated from Campaigns"),
        }),
      });
    },
    onSuccess: () => {
      setLifecycleAction(null);
      setLifecycleReason("");
      void queryClient.invalidateQueries({ queryKey: ["campaign-detail", selectedCampaignId] });
      void queryClient.invalidateQueries({ queryKey: ["campaigns-list"] });
      showWorkbenchToast(bilingual(lang, "实验生命周期已更新。", "Campaign lifecycle updated."));
    },
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

  const lifecycleOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "current", label: bilingual(lang, "当前活跃", "Current") },
      { value: "all", label: bilingual(lang, "全部状态", "All lifecycles") },
      { value: "active", label: bilingual(lang, "进行中", "Active") },
      { value: "closed", label: bilingual(lang, "已关闭", "Closed") },
      { value: "draft", label: bilingual(lang, "草稿", "Draft") },
    ],
    [lang],
  );

  const issueStateOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "all", label: bilingual(lang, "全部状态", "All states") },
      { value: "pending", label: bilingual(lang, "待处理", "Pending") },
      { value: "completed", label: bilingual(lang, "已完成", "Completed") },
      { value: "conflict", label: bilingual(lang, "冲突", "Conflict") },
    ],
    [lang],
  );

  const assigneeOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "", label: bilingual(lang, "全部负责人", "All assignees") },
      ...(detailQuery.data?.assignees || []).map((a) => ({ value: a.name, label: a.name })),
    ],
    [detailQuery.data?.assignees, lang],
  );

  const detail = detailQuery.data;
  const camp = detail?.campaign;
  const canManageLifecycle = Boolean(isAdmin && camp?.purpose && !camp.legacy_read_only);

  return (
    <section
      id="campaignsPage"
      className="app-page ra-react-page"
      data-page="campaigns"
      data-react-island="campaigns"
    >
      {!selectedCampaignId ? (
        <div className="panel-card">
          <div className="ra-page-header-row">
            <div>
              <h2>{bilingual(lang, "任务与标注汇总", "Campaigns & Label Analysis")}</h2>
              <p className="muted">
                {bilingual(
                  lang,
                  `共 ${(listQuery.data?.items || []).length} 个实验`,
                  `${(listQuery.data?.items || []).length} campaigns`,
                )}
              </p>
            </div>
            <div className="ra-inline-actions">
              <button
                type="button"
                className={`button ${purpose === "" ? "button-primary" : "button-quiet"}`}
                onClick={() => setPurpose("")}
              >
                {bilingual(lang, "全部实验", "All")}
              </button>
              <button
                type="button"
                className={`button ${purpose === "labeling" ? "button-primary" : "button-quiet"}`}
                onClick={() => setPurpose("labeling")}
              >
                {bilingual(lang, "标注实验", "Labeling")}
              </button>
            </div>
          </div>

          <div className="ra-filter-grid" style={{ marginTop: 12 }}>
            <div className="ra-field-stack">
              <span>{bilingual(lang, "生命周期", "Lifecycle")}</span>
              <UiSelect
                id="raCampaignLifecycle"
                value={lifecycle}
                options={lifecycleOptions}
                ariaLabel={bilingual(lang, "按生命周期筛选", "Filter by lifecycle")}
                onChange={setLifecycle}
              />
            </div>
            <label className="ra-field-stack" style={{ gridColumn: "span 2" }}>
              <span>{bilingual(lang, "搜索实验", "Search campaigns")}</span>
              <input
                type="search"
                value={search}
                placeholder={bilingual(lang, "名称或 ID", "Name or ID")}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
          </div>

          <div className="ra-table-scroll" style={{ marginTop: 14 }}>
            <table className="trail-history-table">
              <thead>
                <tr>
                  <th>{bilingual(lang, "实验名称", "Campaign")}</th>
                  <th>{bilingual(lang, "类型", "Purpose")}</th>
                  <th>{bilingual(lang, "状态", "Lifecycle")}</th>
                  <th>{bilingual(lang, "已提交 / 所需", "Submitted / Required")}</th>
                  <th>{bilingual(lang, "完成进度", "Completion")}</th>
                  <th>{bilingual(lang, "数据范围", "Baselines")}</th>
                </tr>
              </thead>
              <tbody>
                {listQuery.isLoading ? (
                  <tr>
                    <td colSpan={6}>{bilingual(lang, "正在加载…", "Loading…")}</td>
                  </tr>
                ) : !(listQuery.data?.items || []).length ? (
                  <tr>
                    <td colSpan={6}>{bilingual(lang, "当前筛选没有 Campaign。", "No campaigns match.")}</td>
                  </tr>
                ) : (
                  listQuery.data!.items!.map((item) => {
                    const p = item.progress || {};
                    return (
                      <tr key={item.id}>
                        <td>
                          <button
                            type="button"
                            className="campaign-row-button"
                            onClick={() => {
                              setSelectedCampaignId(item.id);
                              setIssuePage(1);
                            }}
                          >
                            <span className="campaign-row-name">{item.name || item.id}</span>
                            <span className="campaign-row-id">{item.id}</span>
                          </button>
                        </td>
                        <td>{campaignStateText(item.purpose, lang)}</td>
                        <td>
                          <span className="campaign-lifecycle-badge" data-lifecycle={item.lifecycle}>
                            {campaignStateText(item.lifecycle, lang)}
                          </span>
                        </td>
                        <td>
                          {p.submitted_submitter_count ?? 0} / {p.required_submitter_count ?? 0}
                        </td>
                        <td>
                          {p.completed_issue_count ?? 0} / {p.assigned_issue_count ?? 0}
                        </td>
                        <td>{(item.baseline_scopes || []).join(", ") || item.workset_baseline_scope || "—"}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="panel-card">
          <div className="ra-page-header-row">
            <div>
              <button
                type="button"
                className="button button-quiet"
                onClick={() => setSelectedCampaignId("")}
              >
                ← {bilingual(lang, "返回实验列表", "Back to campaigns")}
              </button>
              <h2 style={{ marginTop: 8 }}>{camp?.name || selectedCampaignId}</h2>
              {camp && (
                <p className="muted">
                  {camp.id} · {campaignStateText(camp.purpose, lang)} ·{" "}
                  {campaignStateText(camp.lifecycle, lang)}
                </p>
              )}
            </div>
            <div className="ra-inline-actions">
              {isAdmin && camp?.purpose === "labeling" && (
                <a
                  className="button button-quiet"
                  href={withWorkbenchBase(`/api/campaigns/${encodeURIComponent(camp.id)}/analysis/export.csv`)}
                  download
                >
                  {bilingual(lang, "导出 CSV", "Export CSV")}
                </a>
              )}
              {canManageLifecycle && camp?.lifecycle === "active" && (
                <button
                  type="button"
                  className="button button-quiet"
                  onClick={() => setLifecycleAction("close")}
                >
                  {bilingual(lang, "关闭实验", "Close")}
                </button>
              )}
              {canManageLifecycle && camp?.lifecycle === "closed" && (
                <button
                  type="button"
                  className="button button-quiet"
                  onClick={() => setLifecycleAction("reopen")}
                >
                  {bilingual(lang, "重新打开", "Reopen")}
                </button>
              )}
              {canManageLifecycle && camp?.lifecycle === "draft" && (
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => setLifecycleAction("activate")}
                >
                  {bilingual(lang, "激活草稿", "Activate")}
                </button>
              )}
            </div>
          </div>

          {detail?.progress && (
            <div className="ra-kpi-grid" style={{ marginTop: 12 }}>
              <div className="ra-kpi-card">
                <span>{bilingual(lang, "已完成", "Completed")}</span>
                <strong>
                  {detail.progress.completed_issue_count ?? 0} / {detail.progress.assigned_issue_count ?? 0}
                </strong>
              </div>
              <div className="ra-kpi-card">
                <span>{bilingual(lang, "待处理", "Pending")}</span>
                <strong>{detail.progress.pending_issue_count ?? 0}</strong>
              </div>
              <div className="ra-kpi-card">
                <span>{bilingual(lang, "冲突待处理", "Conflicts")}</span>
                <strong>{detail.progress.conflict_issue_count ?? 0}</strong>
              </div>
              <div className="ra-kpi-card">
                <span>{bilingual(lang, "已提交 / 所需", "Submitted / Required")}</span>
                <strong>
                  {detail.progress.submitted_submitter_count ?? 0} /{" "}
                  {detail.progress.required_submitter_count ?? 0}
                </strong>
              </div>
            </div>
          )}

          <div className="ra-filter-grid" style={{ marginTop: 14 }}>
            <div className="ra-field-stack">
              <span>{bilingual(lang, "负责人", "Assignee")}</span>
              <UiSelect
                id="raCampIssueAssignee"
                value={issueAssignee}
                options={assigneeOptions}
                ariaLabel={bilingual(lang, "按负责人筛选", "Filter by assignee")}
                onChange={(v) => {
                  setIssueAssignee(v);
                  setIssuePage(1);
                }}
              />
            </div>
            <div className="ra-field-stack">
              <span>{bilingual(lang, "状态", "State")}</span>
              <UiSelect
                id="raCampIssueState"
                value={issueState}
                options={issueStateOptions}
                ariaLabel={bilingual(lang, "按状态筛选", "Filter by state")}
                onChange={(v) => {
                  setIssueState(v);
                  setIssuePage(1);
                }}
              />
            </div>
            <label className="ra-field-stack">
              <span>{bilingual(lang, "搜索 Issue", "Search Issue")}</span>
              <input
                type="search"
                value={issueSearch}
                onChange={(e) => {
                  setIssueSearch(e.target.value);
                  setIssuePage(1);
                }}
              />
            </label>
          </div>

          <div className="ra-table-scroll" style={{ marginTop: 12 }}>
            <table className="trail-history-table">
              <thead>
                <tr>
                  <th>Issue ID</th>
                  <th>{bilingual(lang, "GT / 参考", "GT / Ref")}</th>
                  <th>{bilingual(lang, "标注结果", "Expected")}</th>
                  <th>{bilingual(lang, "负责人", "Assignees")}</th>
                  <th>{bilingual(lang, "进度", "Progress")}</th>
                  <th>{bilingual(lang, "状态", "State")}</th>
                  <th>{bilingual(lang, "讨论", "Discuss")}</th>
                </tr>
              </thead>
              <tbody>
                {!(detail?.issues || []).length ? (
                  <tr>
                    <td colSpan={7}>{bilingual(lang, "暂无明细。", "No issues.")}</td>
                  </tr>
                ) : (
                  detail!.issues!.map((row) => (
                    <tr key={row.issue_id}>
                      <td>
                        <button
                          type="button"
                          className="button button-quiet"
                          onClick={() =>
                            camp?.purpose === "labeling"
                              ? navigate("labeling", { issue: row.issue_id, task: camp.id })
                              : navigate("review", { issue: row.issue_id })
                          }
                        >
                          {row.issue_id}
                        </button>
                      </td>
                      <td>{row.reference_label || row.gt_label || "—"}</td>
                      <td>{row.expected_output || "—"}</td>
                      <td>{(row.assignments || []).map((a) => a.assignee).join(", ") || "—"}</td>
                      <td>
                        {row.submitted ?? 0} / {row.required_submitter_count ?? 0}
                      </td>
                      <td>{campaignStateText(row.state, lang)}</td>
                      <td>
                        <button
                          type="button"
                          className="button button-quiet"
                          onClick={() => setDiscussionIssueId(row.issue_id)}
                        >
                          {bilingual(lang, "讨论", "Discuss")}
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {(detail?.total || 0) > 0 && (
            <Pagination
              page={issuePage}
              pageSize={issuePageSize}
              total={detail!.total!}
              lang={lang}
              loading={detailQuery.isFetching}
              ariaLabel={bilingual(lang, "实验明细分页", "Campaign issues pagination")}
              onPageChange={setIssuePage}
              onPageSizeChange={(n) => {
                setIssuePageSize(n);
                setIssuePage(1);
              }}
            />
          )}
        </div>
      )}

      {/* Lifecycle Action Modal */}
      <ModalDialog
        open={Boolean(lifecycleAction)}
        title={bilingual(lang, `确认操作：${lifecycleAction}`, `Confirm action: ${lifecycleAction}`)}
        lang={lang}
        onClose={() => {
          if (!lifecycleMutation.isPending) setLifecycleAction(null);
        }}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => setLifecycleAction(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={lifecycleMutation.isPending}
              onClick={() => lifecycleMutation.mutate()}
            >
              {bilingual(lang, "确认执行", "Confirm")}
            </button>
          </>
        }
      >
        <label className="ra-field-stack">
          <span>{bilingual(lang, "操作原因", "Reason")}</span>
          <textarea
            rows={2}
            value={lifecycleReason}
            onChange={(e) => setLifecycleReason(e.target.value)}
          />
        </label>
      </ModalDialog>

      {/* Discussion Modal */}
      {discussionIssueId && (
        <IssueDiscussion
          open={Boolean(discussionIssueId)}
          kind="issue"
          issueId={discussionIssueId}
          lang={lang}
          username={session.username}
          canWrite={Boolean(session.can_write || session.is_admin)}
          isAdmin={Boolean(session.is_admin)}
          onClose={() => setDiscussionIssueId(null)}
        />
      )}
    </section>
  );
};
