import React, { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import { IssueDiscussion } from "../components/discussion/IssueDiscussion";
import { ModalDialog } from "../components/ui/ModalDialog";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import {
  CASE_PAGE_SIZES,
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { UiSelect } from "../components/ui/UiSelect";
import {
  CORE_LABELS,
  DashboardConfigPayload,
  decisionStateLabel,
  displayLabelText,
  labelBadgeClass,
  parseIssueIdsInput,
  showWorkbenchToast,
} from "../features/review/reviewHelpers";

export interface LabelingSummaryPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
  username: string;
  canWrite: boolean;
  isAdmin: boolean;
}

interface LabelingTaskItem {
  id: string;
  name?: string;
  workflow_mode?: string;
  selection_source_run_id?: string;
}

interface SummaryCaseItem {
  issue_id: string;
  title?: string;
  scenario?: string;
  gt_label?: string;
  expected_output?: string;
  label_state?: string;
  is_excluded?: boolean;
  tags?: string[];
  evidence_gaps?: string[];
  rationales?: { author?: string; text?: string }[];
  comment_count?: number;
  adjudication?: { kind?: string; author?: string };
  decision?: { stale?: boolean };
  expected_output_source?: { kind?: string; authors?: string[] };
}

interface LabelingSummaryPayload {
  total?: number;
  page?: number;
  pages?: number;
  page_size?: number;
  submitted_total?: number;
  submitted_states?: { resolved?: number; pending?: number; conflict?: number };
  gt_summary?: {
    matches?: number;
    to_update?: number;
    needs_attention?: number;
    unlabeled?: number;
  };
  pairs?: { gt: string; label: string; count: number }[];
  tags?: Record<string, number>;
  labelers?: string[];
  assignees?: string[];
  items?: SummaryCaseItem[];
}

export const LabelingSummaryPage: React.FC<LabelingSummaryPageProps> = ({
  active,
  lang,
  selectedBaselines,
  username,
  canWrite,
  isAdmin,
}) => {
  const initialParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const baselinesKey = selectedBaselines.join(",");

  const [searchText, setSearchText] = useState(initialParams.get("q") || "");
  const [issueIds, setIssueIds] = useState<string[]>(() =>
    (initialParams.get("issue_ids") || "").split(",").filter(Boolean),
  );
  const [taskId, setTaskId] = useState(initialParams.get("task") || "");
  const [statuses, setStatuses] = useState<string[]>(() =>
    (initialParams.get("status") || "").split(",").filter(Boolean),
  );
  const [gtRelations, setGtRelations] = useState<string[]>(() =>
    (initialParams.get("gt_relation") || "").split(",").filter(Boolean),
  );
  const [authors, setAuthors] = useState<string[]>(() =>
    (initialParams.get("author") || "").split(",").filter(Boolean),
  );
  const [assignees, setAssignees] = useState<string[]>(() =>
    (initialParams.get("assignee") || "").split(",").filter(Boolean),
  );
  const [labels, setLabels] = useState<string[]>(() =>
    (initialParams.get("label") || "").split(",").filter(Boolean),
  );
  const [gts, setGts] = useState<string[]>(() =>
    (initialParams.get("gt") || "").split(",").filter(Boolean),
  );
  const [commentStates, setCommentStates] = useState<string[]>(() =>
    (initialParams.get("comment_state") || "").split(",").filter(Boolean),
  );
  const [exclusions, setExclusions] = useState<string[]>(() =>
    (initialParams.get("exclusion") || "").split(",").filter(Boolean),
  );
  const [page, setPage] = useState(Math.max(1, Number(initialParams.get("page")) || 1));
  const [pageSize, setPageSize] = useState(
    CASE_PAGE_SIZES.includes(Number(initialParams.get("page_size")) as 10 | 20 | 50 | 100)
      ? Number(initialParams.get("page_size"))
      : DEFAULT_CASE_PAGE_SIZE,
  );
  const [filtersOpenMobile, setFiltersOpenMobile] = useState(false);
  const [rulesModalMode, setRulesModalMode] = useState<"expected" | "gt" | null>(null);
  const [multiIssueModalOpen, setMultiIssueModalOpen] = useState(false);
  const [multiIssueDraft, setMultiIssueDraft] = useState("");
  const [discussionIssueId, setDiscussionIssueId] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    const url = new URL(window.location.href);
    const setOrDel = (k: string, v: string) => {
      if (v) url.searchParams.set(k, v);
      else url.searchParams.delete(k);
    };
    setOrDel("baselines", baselinesKey);
    setOrDel("q", searchText.trim());
    setOrDel("issue_ids", issueIds.join(","));
    setOrDel("task", taskId);
    setOrDel("status", statuses.join(","));
    setOrDel("gt_relation", gtRelations.join(","));
    setOrDel("author", authors.join(","));
    setOrDel("assignee", assignees.join(","));
    setOrDel("label", labels.join(","));
    setOrDel("gt", gts.join(","));
    setOrDel("comment_state", commentStates.join(","));
    setOrDel("exclusion", exclusions.join(","));
    url.searchParams.set("page", String(page));
    url.searchParams.set("page_size", String(pageSize));
    window.history.replaceState(window.history.state, "", url.pathname + url.search);
  }, [
    active,
    baselinesKey,
    searchText,
    issueIds,
    taskId,
    statuses,
    gtRelations,
    authors,
    assignees,
    labels,
    gts,
    commentStates,
    exclusions,
    page,
    pageSize,
  ]);

  const configQuery = useQuery<DashboardConfigPayload>({
    queryKey: ["dashboard-config"],
    queryFn: ({ signal }) => apiRequest<DashboardConfigPayload>("/api/dashboard-config", { signal }),
    enabled: active,
    staleTime: 60_000,
  });

  const tasksQuery = useQuery<{ items?: LabelingTaskItem[] }>({
    queryKey: ["labeling-summary-tasks", baselinesKey],
    queryFn: ({ signal }) =>
      apiRequest<{ items?: LabelingTaskItem[] }>(
        `/api/labeling/tasks?include_combined=true&baselines=${encodeURIComponent(baselinesKey)}`,
        { signal },
      ),
    enabled: active,
    staleTime: 30_000,
  });

  const summaryQuery = useQuery<LabelingSummaryPayload>({
    queryKey: [
      "labeling-summary-data",
      baselinesKey,
      taskId,
      searchText.trim(),
      issueIds.join(","),
      statuses.join(","),
      gtRelations.join(","),
      authors.join(","),
      assignees.join(","),
      labels.join(","),
      gts.join(","),
      commentStates.join(","),
      exclusions.join(","),
      page,
      pageSize,
    ],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        baselines: baselinesKey,
        task_id: taskId,
        q: searchText.trim(),
        issue_ids: issueIds.join(","),
        status: statuses.join(","),
        gt_relation: gtRelations.join(","),
        author: authors.join(","),
        assignee: assignees.join(","),
        label: labels.join(","),
        gt: gts.join(","),
        comment_state: commentStates.join(","),
        exclusion: exclusions.join(","),
        page: String(page),
        page_size: String(pageSize),
      });
      return apiRequest<LabelingSummaryPayload>(`/api/labeling/summary?${qs.toString()}`, { signal });
    },
    enabled: active,
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });

  const data = summaryQuery.data;
  const tagCatalogMap = useMemo(
    () => new Map((configQuery.data?.review_tag_catalog || []).map((t) => [t.key, t])),
    [configQuery.data],
  );

  const taskOptions = useMemo(
    () => [
      { value: "", label: bilingual(lang, "全部标注（含历史迁移）", "All annotations (incl. migrated)") },
      ...(tasksQuery.data?.items || []).map((t) => ({ value: t.id, label: t.name || t.id })),
    ],
    [tasksQuery.data, lang],
  );

  const statusOptions: MultiSelectOption[] = [
    { value: "resolved", label: bilingual(lang, "已形成结论", "Resolved"), group: bilingual(lang, "标注状态", "Label status") },
    { value: "pending", label: bilingual(lang, "待形成结论", "Pending"), group: bilingual(lang, "标注状态", "Label status") },
    { value: "conflict", label: bilingual(lang, "待裁决 / 冲突", "Conflict / stale"), group: bilingual(lang, "标注状态", "Label status") },
  ];

  const gtRelationOptions: MultiSelectOption[] = [
    { value: "differs", label: bilingual(lang, "与 GT 不同", "Differs from GT") },
    { value: "matches", label: bilingual(lang, "与 GT 一致", "Matches GT") },
    { value: "missing_gt", label: bilingual(lang, "GT 缺失", "GT missing") },
  ];

  const labelOptions: MultiSelectOption[] = CORE_LABELS.map((val) => ({
    value: val,
    label: displayLabelText(val, lang),
  }));

  const authorOptions: MultiSelectOption[] = useMemo(
    () =>
      Array.from(new Set([...(data?.labelers || []), ...authors])).map((name) => ({
        value: name,
        label: name,
      })),
    [data?.labelers, authors],
  );

  const assigneeOptions: MultiSelectOption[] = useMemo(
    () =>
      Array.from(new Set([...(data?.assignees || []), ...assignees])).map((name) => ({
        value: name,
        label: name,
      })),
    [data?.assignees, assignees],
  );

  const resetFilters = () => {
    setSearchText("");
    setIssueIds([]);
    setTaskId("");
    setStatuses([]);
    setGtRelations([]);
    setAuthors([]);
    setAssignees([]);
    setLabels([]);
    setGts([]);
    setCommentStates([]);
    setExclusions([]);
    setPage(1);
  };

  const handleExportGt = () => {
    const qs = new URLSearchParams({
      baselines: baselinesKey,
      task_id: taskId,
      q: searchText.trim(),
      issue_ids: issueIds.join(","),
      status: statuses.join(","),
      gt_relation: gtRelations.join(","),
      author: authors.join(","),
      assignee: assignees.join(","),
      label: labels.join(","),
      gt: gts.join(","),
      comment_state: commentStates.join(","),
      exclusion: exclusions.join(","),
    });
    const url = withWorkbenchBase(`/api/labeling/gt-update-export?${qs.toString()}`);
    window.open(url, "_blank", "noopener");
  };

  const clusterSections = useMemo(() => {
    const tagCounts = data?.tags || {};
    const collect = (section: string, group: string) =>
      Object.entries(tagCounts)
        .map(([key, count]) => ({ key, count: Number(count || 0), meta: tagCatalogMap.get(key) }))
        .filter((item) => item.count > 0 && item.meta?.section === section && item.meta?.group === group)
        .sort((a, b) => b.count - a.count)
        .slice(0, 8);
    return [
      { key: "env", title: bilingual(lang, "场景环境", "Environment"), items: collect("scene", "environment") },
      { key: "intent", title: bilingual(lang, "自车意图", "Ego intent"), items: collect("scene", "self_intent") },
      {
        key: "trigger",
        title: bilingual(lang, "触发判定", "Trigger decision"),
        items: [...collect("interaction_decision", "false_trigger"), ...collect("interaction_decision", "true_trigger")].sort(
          (a, b) => b.count - a.count,
        ),
      },
      {
        key: "egress",
        title: bilingual(lang, "如何脱困", "Egress"),
        items: [...collect("egress", "ra"), ...collect("egress", "no_assist")].sort((a, b) => b.count - a.count),
      },
    ];
  }, [data?.tags, tagCatalogMap, lang]);

  if (!active) return null;

  const states = data?.submitted_states || {};
  const stateTotal = Number(states.resolved || 0) + Number(states.pending || 0) + Number(states.conflict || 0);
  const pairsMap = new Map((data?.pairs || []).map((p) => [`${p.gt}|${p.label}`, Number(p.count || 0)]));
  const matrixLabels = ["误触发", "正确触发", "无需协助"] as const;

  return (
    <div className="ra-labeling-summary-root">
      <section className="page-card ra-filter-card">
        <div className="mobile-filter-bar">
          <button
            type="button"
            className="button button-quiet mobile-filter-toggle"
            aria-expanded={filtersOpenMobile}
            onClick={() => setFiltersOpenMobile((o) => !o)}
          >
            <span>{bilingual(lang, "标注汇总筛选", "Summary filters")}</span>
            <span>{filtersOpenMobile ? bilingual(lang, "收起", "Hide") : bilingual(lang, "展开", "Show")}</span>
          </button>
        </div>

        <div className={`ra-summary-filter-grid${filtersOpenMobile ? " is-mobile-open" : ""}`}>
          <label className="ra-filter-field">
            <span>Issue</span>
            <div className="issue-query-control">
              <input
                type="search"
                value={searchText}
                onChange={(e) => {
                  setSearchText(e.target.value);
                  setPage(1);
                }}
                placeholder={bilingual(lang, "Issue ID / 场景", "Issue ID / scene")}
              />
              <button
                type="button"
                className="button button-quiet"
                onClick={() => {
                  setMultiIssueDraft(issueIds.join("\n"));
                  setMultiIssueModalOpen(true);
                }}
              >
                {issueIds.length > 0
                  ? bilingual(lang, `多 Issue (${issueIds.length})`, `IDs (${issueIds.length})`)
                  : bilingual(lang, "多 Issue", "Multi IDs")}
              </button>
            </div>
          </label>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "标注任务", "Task")}</span>
            <UiSelect
              value={taskId}
              options={taskOptions}
              ariaLabel={bilingual(lang, "标注任务", "Labeling task")}
              onChange={(v) => {
                setTaskId(v);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "结论状态", "Status")}</span>
            <MultiSelect
              values={statuses}
              options={statusOptions}
              lang={lang}
              ariaLabel={bilingual(lang, "结论状态", "Result status")}
              placeholder={bilingual(lang, "全部状态", "All states")}
              onChange={(vals) => {
                setStatuses(vals);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "GT 关系", "GT relation")}</span>
            <MultiSelect
              values={gtRelations}
              options={gtRelationOptions}
              lang={lang}
              ariaLabel={bilingual(lang, "GT 关系", "GT relation")}
              placeholder={bilingual(lang, "全部关系", "All relations")}
              onChange={(vals) => {
                setGtRelations(vals);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "标注人", "Labeler")}</span>
            <MultiSelect
              values={authors}
              options={authorOptions}
              lang={lang}
              ariaLabel={bilingual(lang, "标注人", "Labeler")}
              placeholder={bilingual(lang, "全部标注人", "All labelers")}
              onChange={(vals) => {
                setAuthors(vals);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "任务负责人", "Assignee")}</span>
            <MultiSelect
              values={assignees}
              options={assigneeOptions}
              lang={lang}
              ariaLabel={bilingual(lang, "任务负责人", "Assignee")}
              placeholder={bilingual(lang, "全部负责人", "All assignees")}
              onChange={(vals) => {
                setAssignees(vals);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "结果类别", "Result label")}</span>
            <MultiSelect
              values={labels}
              options={labelOptions}
              lang={lang}
              ariaLabel={bilingual(lang, "结果类别", "Result label")}
              placeholder={bilingual(lang, "全部类别", "All labels")}
              onChange={(vals) => {
                setLabels(vals);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>GT</span>
            <MultiSelect
              values={gts}
              options={labelOptions}
              lang={lang}
              ariaLabel="GT"
              placeholder={bilingual(lang, "全部 GT", "All GT")}
              onChange={(vals) => {
                setGts(vals);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "讨论", "Discussion")}</span>
            <MultiSelect
              values={commentStates}
              options={[
                { value: "with", label: bilingual(lang, "有讨论", "With discussion") },
                { value: "without", label: bilingual(lang, "无讨论", "Without discussion") },
              ]}
              lang={lang}
              ariaLabel={bilingual(lang, "讨论", "Discussion")}
              placeholder={bilingual(lang, "全部讨论状态", "All")}
              onChange={(vals) => {
                setCommentStates(vals);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "排除", "Exclusion")}</span>
            <MultiSelect
              values={exclusions}
              options={[
                { value: "active", label: bilingual(lang, "未排除", "Active") },
                { value: "excluded", label: bilingual(lang, "已排除", "Excluded") },
              ]}
              lang={lang}
              ariaLabel={bilingual(lang, "排除", "Exclusion")}
              placeholder={bilingual(lang, "全部", "All")}
              onChange={(vals) => {
                setExclusions(vals);
                setPage(1);
              }}
            />
          </div>
        </div>

        <div className="ra-summary-toolbar-actions">
          <button type="button" className="button button-quiet" onClick={resetFilters}>
            {bilingual(lang, "重置筛选", "Reset filters")}
          </button>
          <button
            type="button"
            className="button button-quiet"
            onClick={() => setRulesModalMode("expected")}
          >
            {bilingual(lang, "期望输出规则", "Expected output rules")}
          </button>
          <button type="button" className="button button-quiet" onClick={() => setRulesModalMode("gt")}>
            {bilingual(lang, "GT 更新规则", "GT update rules")}
          </button>
          <button
            type="button"
            className="button button-secondary"
            disabled={!isAdmin}
            onClick={handleExportGt}
          >
            {bilingual(lang, "导出 GT 更新", "Export GT update")}
          </button>
        </div>
      </section>

      <section className="analysis-summary-grid">
        <article className="analysis-stat-card">
          <span>{bilingual(lang, "筛选范围内 Case", "Cases in scope")}</span>
          <strong>{data?.total ?? "—"}</strong>
        </article>
        <article className="analysis-stat-card">
          <span>{bilingual(lang, "已形成结论", "Resolved")}</span>
          <strong>{states.resolved ?? "—"}</strong>
        </article>
        <article className="analysis-stat-card">
          <span>{bilingual(lang, "待形成结论", "Pending")}</span>
          <strong>{states.pending ?? "—"}</strong>
        </article>
        <article className="analysis-stat-card">
          <span>{bilingual(lang, "待裁决 / 需确认", "Conflict / stale")}</span>
          <strong>{states.conflict ?? "—"}</strong>
        </article>
      </section>

      <section className="ra-summary-visual-grid">
        <article className="page-card">
          <h3>{bilingual(lang, "提交结论状态分布", "Submitted label status")}</h3>
          <div className="analysis-review-status-bar">
            {stateTotal > 0 ? (
              <>
                {Number(states.resolved || 0) > 0 && (
                  <span
                    className="analysis-review-status-segment status-completed"
                    style={{ width: `${(Number(states.resolved) * 100) / stateTotal}%` }}
                  />
                )}
                {Number(states.pending || 0) > 0 && (
                  <span
                    className="analysis-review-status-segment status-pending"
                    style={{ width: `${(Number(states.pending) * 100) / stateTotal}%` }}
                  />
                )}
                {Number(states.conflict || 0) > 0 && (
                  <span
                    className="analysis-review-status-segment status-blocked_by_label"
                    style={{ width: `${(Number(states.conflict) * 100) / stateTotal}%` }}
                  />
                )}
              </>
            ) : (
              <span className="analysis-review-status-empty">
                {bilingual(lang, "暂无标注提交", "No submissions yet")}
              </span>
            )}
          </div>
          <div className="ra-summary-legend-row">
            <span>
              {bilingual(lang, "已形成结论", "Resolved")}: <strong>{states.resolved || 0}</strong>
            </span>
            <span>
              {bilingual(lang, "待形成结论", "Pending")}: <strong>{states.pending || 0}</strong>
            </span>
            <span>
              {bilingual(lang, "待裁决/冲突", "Conflict")}: <strong>{states.conflict || 0}</strong>
            </span>
          </div>
        </article>

        <article className="page-card">
          <h3>{bilingual(lang, "GT vs 标注混淆矩阵", "GT vs Label confusion matrix")}</h3>
          <div className="ra-table-scroll">
            <table className="analysis-confusion-table">
              <thead>
                <tr>
                  <th>{bilingual(lang, "GT ↓ / 标注 →", "GT ↓ / Label →")}</th>
                  {matrixLabels.map((l) => (
                    <th key={l}>{displayLabelText(l, lang)}</th>
                  ))}
                  <th>{bilingual(lang, "合计", "Total")}</th>
                </tr>
              </thead>
              <tbody>
                {matrixLabels.map((gt) => {
                  const rowTotal = matrixLabels.reduce(
                    (s, l) => s + (pairsMap.get(`${gt}|${l}`) || 0),
                    0,
                  );
                  return (
                    <tr key={gt}>
                      <th scope="row">{displayLabelText(gt, lang)}</th>
                      {matrixLabels.map((l) => {
                        const count = pairsMap.get(`${gt}|${l}`) || 0;
                        return (
                          <td
                            key={l}
                            className={gt === l ? "confusion-match" : count > 0 ? "confusion-mismatch" : ""}
                          >
                            {count}
                          </td>
                        );
                      })}
                      <td className="confusion-total">{rowTotal}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section className="ra-summary-clusters-grid">
        {clusterSections.map((sec) => {
          const maxCount = Math.max(1, ...sec.items.map((i) => i.count));
          return (
            <article key={sec.key} className="page-card">
              <h3>{sec.title}</h3>
              {sec.items.length === 0 ? (
                <p className="muted">{bilingual(lang, "暂无标签统计", "No tag counts")}</p>
              ) : (
                <div className="ra-cluster-bar-list">
                  {sec.items.map((item) => {
                    const label =
                      lang === "en" && item.meta?.label_en
                        ? item.meta.label_en
                        : item.meta?.label || item.key;
                    return (
                      <div key={item.key} className="ra-cluster-bar-row">
                        <div className="ra-cluster-bar-meta">
                          <span>{label}</span>
                          <strong>{item.count}</strong>
                        </div>
                        <div className="ra-cluster-bar-track">
                          <div
                            className="ra-cluster-bar-fill"
                            style={{ width: `${Math.round((item.count / maxCount) * 100)}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </article>
          );
        })}
      </section>

      <section className="page-card">
        <div className="runs-toolbar">
          <h3>
            {bilingual(lang, "标注明细列表", "Annotated cases")} ({data?.total ?? 0})
          </h3>
        </div>

        <div className="ra-summary-case-list">
          {(data?.items || []).map((item) => {
            const href = `${withWorkbenchBase("/case-labeling")}?issue=${encodeURIComponent(item.issue_id)}${baselinesKey ? `&baselines=${encodeURIComponent(baselinesKey)}` : ""}${taskId ? `&task=${encodeURIComponent(taskId)}` : ""}`;
            return (
              <article key={item.issue_id} className="ra-summary-case-card">
                <div className="ra-summary-case-head">
                  <div className="ra-summary-case-title">
                    <a className="issue-id" href={href}>
                      {item.issue_id}
                    </a>
                    <span className="label-badge label-empty">
                      GT: {displayLabelText(item.gt_label, lang)}
                    </span>
                    <span className={labelBadgeClass(item.expected_output)}>
                      {displayLabelText(item.expected_output, lang)}
                    </span>
                    <span className="status-chip">
                      {decisionStateLabel(item.decision?.stale ? "stale" : item.label_state, lang)}
                    </span>
                    {item.is_excluded && (
                      <span className="issue-card-flag issue-card-flag-excluded">
                        {bilingual(lang, "排除", "Excluded")}
                      </span>
                    )}
                  </div>
                  <div className="ra-summary-case-actions">
                    <button
                      type="button"
                      className="button button-quiet"
                      onClick={() => setDiscussionIssueId(item.issue_id)}
                    >
                      {item.comment_count
                        ? bilingual(lang, `讨论 · ${item.comment_count}`, `Discuss · ${item.comment_count}`)
                        : bilingual(lang, "讨论", "Discuss")}
                    </button>
                    <a className="button button-secondary" href={href}>
                      {bilingual(lang, "打开标注", "Open")}
                    </a>
                  </div>
                </div>
                {(item.title || item.scenario) && (
                  <p className="ra-summary-case-desc">{item.title || item.scenario}</p>
                )}
                {(item.tags || []).length > 0 && (
                  <div className="ra-summary-chip-row">
                    {(item.tags || []).map((key) => {
                      const meta = tagCatalogMap.get(key);
                      return (
                        <span key={key} className="analysis-chip tag-chip">
                          {lang === "en" && meta?.label_en ? meta.label_en : meta?.label || key}
                        </span>
                      );
                    })}
                  </div>
                )}
              </article>
            );
          })}
          {!summaryQuery.isPending && !(data?.items || []).length && (
            <div className="empty-state">
              {bilingual(lang, "当前筛选条件下没有标注汇总记录。", "No labeling summary items match the current filters.")}
            </div>
          )}
        </div>

        <Pagination
          page={page}
          pageSize={pageSize}
          total={data?.total || 0}
          lang={lang}
          loading={summaryQuery.isFetching}
          onPageChange={setPage}
          onPageSizeChange={(s) => {
            setPageSize(s);
            setPage(1);
          }}
        />
      </section>

      <ModalDialog
        open={rulesModalMode !== null}
        lang={lang}
        title={
          rulesModalMode === "gt"
            ? bilingual(lang, "GT 更新规则", "GT update rules")
            : bilingual(lang, "期望输出规则", "Expected output rules")
        }
        onClose={() => setRulesModalMode(null)}
        footer={
          <button type="button" className="button button-primary" onClick={() => setRulesModalMode(null)}>
            {bilingual(lang, "知道了", "Got it")}
          </button>
        }
      >
        {rulesModalMode === "gt" ? (
          <ol className="label-summary-gt-rules">
            <li>
              {bilingual(
                lang,
                "汇总当前 Issue 的全部任务结果和任务外标注。有效的 Issue 裁决优先。",
                "Combine all task results and annotations outside tasks. A valid Issue decision takes precedence.",
              )}
            </li>
            <li>
              {bilingual(
                lang,
                "没有 Issue 裁决时，全部来源必须完成且结论一致。",
                "Without an Issue decision, all sources must be complete and agree.",
              )}
            </li>
            <li>
              {bilingual(
                lang,
                "结论与当前 GT 不同，或 GT 未设置：计入 GT 待更新。",
                "A result differing from current GT or filling missing GT counts as GT to update.",
              )}
            </li>
          </ol>
        ) : (
          <ol className="label-summary-gt-rules">
            <li>
              {bilingual(
                lang,
                "任务内：有有效任务裁决时采用裁决；否则当全部已分配人员提交一致时形成任务结论。",
                "Within a task: valid task decision takes precedence; otherwise unanimous assignee submissions form the task result.",
              )}
            </li>
            <li>
              {bilingual(
                lang,
                "全部标注：有效 Issue 裁决优先；否则全部来源一致时形成最终期望输出。",
                "Across all annotations: valid Issue decision takes precedence; otherwise unanimous sources form the final expected output.",
              )}
            </li>
            <li>
              {bilingual(
                lang,
                "来源更新会导致旧裁决进入待复核状态；GT 仅作对照，不会自动改写。",
                "Source changes mark existing decisions stale for recheck; GT is comparison-only.",
              )}
            </li>
          </ol>
        )}
      </ModalDialog>

      <ModalDialog
        open={multiIssueModalOpen}
        lang={lang}
        title={bilingual(lang, "多 Issue ID 筛选", "Multi-Issue ID filter")}
        onClose={() => setMultiIssueModalOpen(false)}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => {
                setIssueIds([]);
                setMultiIssueDraft("");
                setMultiIssueModalOpen(false);
                setPage(1);
              }}
            >
              {bilingual(lang, "清空", "Clear")}
            </button>
            <button
              type="button"
              className="button button-primary"
              onClick={() => {
                const parsed = parseIssueIdsInput(multiIssueDraft);
                if (parsed.ids.length > 500) {
                  showWorkbenchToast(bilingual(lang, "最多支持 500 个 Issue ID。", "Up to 500 Issue IDs."), true);
                  return;
                }
                setIssueIds(parsed.ids);
                setMultiIssueModalOpen(false);
                setPage(1);
              }}
            >
              {bilingual(lang, "应用筛选", "Apply")}
            </button>
          </>
        }
      >
        <textarea
          rows={6}
          className="ra-multi-issue-textarea"
          value={multiIssueDraft}
          onChange={(e) => setMultiIssueDraft(e.target.value)}
          placeholder={bilingual(
            lang,
            "每行、空格或逗号分隔多个 Issue ID（如 cn37631883）",
            "Separate multiple Issue IDs by newline, space, or comma",
          )}
        />
      </ModalDialog>

      {discussionIssueId && (
        <IssueDiscussion
          open={Boolean(discussionIssueId)}
          issueId={discussionIssueId}
          lang={lang}
          username={username}
          canWrite={canWrite}
          isAdmin={isAdmin}
          onClose={() => setDiscussionIssueId(null)}
        />
      )}
    </div>
  );
};
