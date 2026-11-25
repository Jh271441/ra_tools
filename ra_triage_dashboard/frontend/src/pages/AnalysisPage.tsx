import React, { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  formatCstTime,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import { MultiSelect } from "../components/ui/MultiSelect";
import {
  CASE_PAGE_SIZES,
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { StatusChip } from "../components/ui/StatusChip";
import { UiSelect } from "../components/ui/UiSelect";

interface AnalysisCaseItem {
  issue_id: string;
  title?: string;
  scenario?: string;
  gt_label?: string;
  baseline_scope?: string;
  comparison_status?: string;
  review_url?: string;
  voyager_issue_url?: string;
  model_review_progress?: string;
  annotation?: {
    note?: string;
    author?: string;
    author_verified?: boolean;
    created_at?: string;
    expected_output?: string;
    review_domain?: string;
    review_status?: string;
    model_review_status?: string;
    model_run_id?: string;
    tags?: string[];
    missing_evidence?: string[];
  };
  case_label_context?: { tags?: string[] };
  prediction?: {
    label?: string;
    confidence?: number | null;
    reason?: string;
  };
  multi_review?: {
    agreement?: string;
    completed_count?: number;
    assigned_count?: number;
    output_counts?: Record<string, number>;
  };
}

interface AnalysisResponse {
  total: number;
  page: number;
  page_size: number;
  page_count: number;
  summary?: {
    latest_reviews?: number;
    with_reason?: number;
    empty_reason?: number;
    with_structured_evidence?: number;
  };
  scope?: {
    model_run?: { id: string; name: string } | null;
    comparison_status?: string;
    exclusion?: string;
  };
  missing_evidence?: Array<{ key: string; label?: string; count: number }>;
  tag_clusters?: Array<{ key: string; label?: string; section?: string; count: number }>;
  confusion?: {
    columns?: string[];
    rows?: Array<{ gt_label: string; total: number; accuracy: number; cells: Record<string, number> }>;
  };
  items: AnalysisCaseItem[];
}

interface ModelRunSummary {
  id: string;
  name?: string;
  source_name?: string;
  baseline_prediction_count?: number;
}

const GT_LABELS = ["正确触发", "误触发", "无需协助"];
const MODEL_LABELS = ["正确触发", "误触发", "无需协助", "真实卡住"];

export interface AnalysisPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
}

export const AnalysisPage: React.FC<AnalysisPageProps> = ({
  active,
  lang,
  selectedBaselines,
}) => {
  const initialParams = useMemo(
    () => new URLSearchParams(typeof window !== "undefined" ? window.location.search : ""),
    [],
  );

  const [runId, setRunId] = useState(() => initialParams.get("run") || initialParams.get("model_run_id") || "");
  const [comparisons, setComparisons] = useState<string[]>(() => {
    const raw = initialParams.get("comparison") || "";
    return raw && raw !== "all" ? raw.split(",").filter(Boolean) : [];
  });
  const [exclusion, setExclusion] = useState(() => initialParams.get("exclusion") || "all");
  const [workAgreement, setWorkAgreement] = useState(() => initialParams.get("work_agreement") || "all");
  const [commentState, setCommentState] = useState(() => initialParams.get("comment_state") || "all");
  const [gtLabels, setGtLabels] = useState<string[]>(() => {
    const raw = initialParams.get("gt_label") || "";
    return raw ? raw.split(",").filter(Boolean) : [];
  });
  const [modelLabels, setModelLabels] = useState<string[]>(() => {
    const raw = initialParams.get("model_label") || "";
    return raw ? raw.split(",").filter(Boolean) : [];
  });
  const [reviewers, setReviewers] = useState<string[]>(() => {
    const raw = initialParams.get("annotation_author") || "";
    return raw ? raw.split(",").filter(Boolean) : [];
  });
  const [selectedEvidence, setSelectedEvidence] = useState<string>(
    () => initialParams.get("missing_evidence") || "",
  );
  const [selectedTag, setSelectedTag] = useState<string>(() => initialParams.get("tag") || "");
  const [searchInput, setSearchInput] = useState(() => initialParams.get("search") || "");
  const [search, setSearch] = useState(() => initialParams.get("search") || "");
  const [page, setPage] = useState(() => Math.max(1, Number(initialParams.get("page")) || 1));
  const [pageSize, setPageSize] = useState(() => {
    const ps = Number(initialParams.get("page_size") || DEFAULT_CASE_PAGE_SIZE);
    return CASE_PAGE_SIZES.includes(ps as (typeof CASE_PAGE_SIZES)[number])
      ? ps
      : DEFAULT_CASE_PAGE_SIZE;
  });

  const baselinesParam = selectedBaselines.join(",");

  const runsQuery = useQuery<{ items: ModelRunSummary[] }>({
    queryKey: ["model-runs-for-analysis", baselinesParam],
    queryFn: ({ signal }) => {
      const sp = new URLSearchParams();
      if (baselinesParam) sp.set("baselines", baselinesParam);
      return apiRequest(`/api/model-runs?${sp}`, { signal });
    },
    enabled: active,
    staleTime: 60_000,
  });

  const reviewersQuery = useQuery<{ items?: Array<string | { username: string }> }>({
    queryKey: ["reviewers-for-analysis"],
    queryFn: ({ signal }) => apiRequest("/api/reviewers", { signal }),
    enabled: active,
    staleTime: 60_000,
  });

  const queryParamsString = useMemo(() => {
    const sp = new URLSearchParams();
    if (runId) sp.set("model_run_id", runId);
    sp.set("comparison", runId && comparisons.length ? comparisons.join(",") : "all");
    if (exclusion !== "all") sp.set("exclusion", exclusion);
    if (workAgreement !== "all") sp.set("work_agreement", workAgreement);
    if (commentState !== "all") sp.set("comment_state", commentState);
    if (gtLabels.length) sp.set("gt_label", gtLabels.join(","));
    if (modelLabels.length) sp.set("model_label", modelLabels.join(","));
    if (reviewers.length) sp.set("annotation_author", reviewers.join(","));
    if (selectedEvidence) sp.set("missing_evidence", selectedEvidence);
    if (selectedTag) sp.set("tag", selectedTag);
    if (search) sp.set("search", search);
    if (baselinesParam) sp.set("baselines", baselinesParam);
    sp.set("page", String(page));
    sp.set("page_size", String(pageSize));
    return sp.toString();
  }, [
    runId,
    comparisons,
    exclusion,
    workAgreement,
    commentState,
    gtLabels,
    modelLabels,
    reviewers,
    selectedEvidence,
    selectedTag,
    search,
    baselinesParam,
    page,
    pageSize,
  ]);

  const analysisQuery = useQuery<AnalysisResponse>({
    queryKey: ["review-reason-analysis", queryParamsString],
    queryFn: ({ signal }) => apiRequest(`/api/review-reason-analysis?${queryParamsString}`, { signal }),
    enabled: active,
    placeholderData: keepPreviousData,
    staleTime: 20_000,
  });

  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    if (!window.location.pathname.replace(/\/+$/, "").endsWith("/analysis")) return;
    const url = new URL(window.location.href);
    const kv: Record<string, string> = {
      run: runId,
      comparison: runId && comparisons.length ? comparisons.join(",") : "",
      exclusion: exclusion !== "all" ? exclusion : "",
      work_agreement: workAgreement !== "all" ? workAgreement : "",
      comment_state: commentState !== "all" ? commentState : "",
      gt_label: gtLabels.join(","),
      model_label: modelLabels.join(","),
      annotation_author: reviewers.join(","),
      missing_evidence: selectedEvidence,
      tag: selectedTag,
      search,
      page: String(page),
      page_size: String(pageSize),
    };
    for (const [k, v] of Object.entries(kv)) {
      if (v) url.searchParams.set(k, v);
      else url.searchParams.delete(k);
    }
    window.history.replaceState(window.history.state, "", url);
  }, [
    active,
    runId,
    comparisons,
    exclusion,
    workAgreement,
    commentState,
    gtLabels,
    modelLabels,
    reviewers,
    selectedEvidence,
    selectedTag,
    search,
    page,
    pageSize,
  ]);

  const data = analysisQuery.data;
  const summary = data?.summary || {};
  const reviewerOptions = useMemo(
    () =>
      (reviewersQuery.data?.items || [])
        .map((r) => (typeof r === "string" ? r : r.username))
        .filter(Boolean)
        .map((name) => ({ value: name, label: name })),
    [reviewersQuery.data?.items],
  );

  const exportBaseUrl = (format: "csv" | "xlsx") => {
    const sp = new URLSearchParams(queryParamsString);
    sp.delete("page");
    sp.delete("page_size");
    sp.set("format", format);
    return withWorkbenchBase(`/api/review-reason-analysis/export?${sp.toString()}`);
  };

  const openLegacyModelHistory = async (issueId: string) => {
    const win = window as unknown as { openHistoryDialog?: (kind: string, caseData: unknown) => void };
    if (typeof win.openHistoryDialog !== "function") return;
    try {
      const caseData = await apiRequest(`/api/cases/${encodeURIComponent(issueId)}`);
      win.openHistoryDialog("model", caseData);
    } catch {
      // ignore transient error
    }
  };

  const openLegacyDiscussion = (issueId: string, modelRunId?: string) => {
    const win = window as unknown as {
      openAnalysisDiscussion?: (id: string, opts?: Record<string, string>) => Promise<void>;
    };
    if (typeof win.openAnalysisDiscussion === "function") {
      void win.openAnalysisDiscussion(issueId, { runId: modelRunId || runId || "", source: "analysis" });
    }
  };

  const evidenceItems = (data?.missing_evidence || []).slice(0, 12);
  const tagItems = (data?.tag_clusters || []).slice(0, 16);
  const maxEvidence = Math.max(1, ...evidenceItems.map((i) => i.count));
  const maxTag = Math.max(1, ...tagItems.map((i) => i.count));

  return (
    <div className="ra-react-page ra-analysis-page" data-react-island="analysis">
      <div className="page-card ra-page-toolbar-card">
        <div className="ra-section-header">
          <div>
            <h2 className="ra-page-title">{bilingual(lang, "原因聚类与分析", "Reason clusters & analysis")}</h2>
            <p className="ra-page-subtitle">
              {bilingual(
                lang,
                "按模型 Run、判错状态、场景标签与缺失证据聚合分析，支持混淆矩阵交互下钻与导出。",
                "Cluster review reasons, tags, and missing evidence with interactive confusion matrix drill-down.",
              )}
            </p>
          </div>
          <div className="ra-toolbar-actions">
            <a className="button button-quiet" href={exportBaseUrl("csv")} download>
              {bilingual(lang, "导出 CSV", "Export CSV")}
            </a>
            <a className="button button-quiet" href={exportBaseUrl("xlsx")} download>
              {bilingual(lang, "导出 XLSX", "Export XLSX")}
            </a>
            <button
              type="button"
              className="button button-quiet"
              disabled={analysisQuery.isFetching}
              onClick={() => void analysisQuery.refetch()}
            >
              {analysisQuery.isFetching
                ? bilingual(lang, "加载中…", "Loading…")
                : bilingual(lang, "刷新", "Refresh")}
            </button>
          </div>
        </div>

        <div className="ra-filter-grid">
          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "叠加模型 Run", "Overlay model Run")}</span>
            <UiSelect
              id="raAnalysisRunFilter"
              value={runId}
              options={[
                { value: "", label: bilingual(lang, "不叠加模型 Run", "No model Run overlay") },
                ...(runsQuery.data?.items || []).map((r) => ({
                  value: r.id,
                  label: `${r.name || r.source_name || r.id} (${r.baseline_prediction_count ?? 0})`,
                })),
              ]}
              ariaLabel={bilingual(lang, "叠加模型 Run", "Overlay model Run")}
              onChange={(next) => {
                setRunId(next);
                if (!next) setComparisons([]);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "比对状态", "Comparison status")}</span>
            <MultiSelect
              id="raAnalysisComparisonFilter"
              values={comparisons}
              disabled={!runId}
              lang={lang}
              ariaLabel={bilingual(lang, "比对状态", "Comparison status")}
              options={[
                { value: "mismatch", label: "MISMATCH" },
                { value: "match", label: "MATCH" },
                { value: "no_gt", label: "NO GT" },
                { value: "none", label: "NONE" },
              ]}
              onChange={(next) => {
                setComparisons(next);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "GT 标签", "GT label")}</span>
            <MultiSelect
              id="raAnalysisGtFilter"
              values={gtLabels}
              lang={lang}
              ariaLabel={bilingual(lang, "GT 标签", "GT label")}
              options={GT_LABELS.map((l) => ({ value: l, label: l }))}
              onChange={(next) => {
                setGtLabels(next);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "模型标签", "Model label")}</span>
            <MultiSelect
              id="raAnalysisModelLabelFilter"
              values={modelLabels}
              lang={lang}
              ariaLabel={bilingual(lang, "模型标签", "Model label")}
              options={MODEL_LABELS.map((l) => ({ value: l, label: l }))}
              onChange={(next) => {
                setModelLabels(next);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "复核人", "Reviewer")}</span>
            <MultiSelect
              id="raAnalysisReviewerFilter"
              values={reviewers}
              lang={lang}
              ariaLabel={bilingual(lang, "复核人", "Reviewer")}
              options={reviewerOptions}
              onChange={(next) => {
                setReviewers(next);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "问题排除", "Exclusions")}</span>
            <UiSelect
              id="raAnalysisExclusion"
              value={exclusion}
              options={[
                { value: "all", label: bilingual(lang, "全部（含问题排除）", "All (incl. shielded)") },
                { value: "included", label: bilingual(lang, "不含问题排除", "Exclude shielded") },
                { value: "excluded", label: bilingual(lang, "仅问题排除", "Only shielded") },
              ]}
              ariaLabel={bilingual(lang, "问题排除", "Exclusions")}
              onChange={(next) => {
                setExclusion(next);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "多人一致度", "Agreement")}</span>
            <UiSelect
              id="raAnalysisAgreement"
              value={workAgreement}
              options={[
                { value: "all", label: bilingual(lang, "全部", "All") },
                { value: "pending", label: bilingual(lang, "未完成", "Pending") },
                { value: "agreed", label: bilingual(lang, "一致", "Agreed") },
                { value: "conflict", label: bilingual(lang, "冲突", "Conflict") },
              ]}
              ariaLabel={bilingual(lang, "多人一致度", "Agreement")}
              onChange={(next) => {
                setWorkAgreement(next);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "评论筛选", "Comments")}</span>
            <UiSelect
              id="raAnalysisComments"
              value={commentState}
              options={[
                { value: "all", label: bilingual(lang, "全部评论", "All comments") },
                { value: "with", label: bilingual(lang, "有评论", "With comments") },
                { value: "without", label: bilingual(lang, "无评论", "Without comments") },
              ]}
              ariaLabel={bilingual(lang, "评论筛选", "Comments")}
              onChange={(next) => {
                setCommentState(next);
                setPage(1);
              }}
            />
          </div>

          <form
            className="ra-filter-field ra-search-field"
            onSubmit={(e) => {
              e.preventDefault();
              setSearch(searchInput.trim());
              setPage(1);
            }}
          >
            <span className="ra-field-label">{bilingual(lang, "关键词搜索", "Search")}</span>
            <div className="ra-inline-input-group">
              <input
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder={bilingual(lang, "Issue / 原因 / 场景…", "Issue / reason / scene…")}
                aria-label={bilingual(lang, "关键词搜索", "Search")}
              />
              <button type="submit" className="button button-quiet">
                {bilingual(lang, "搜索", "Search")}
              </button>
            </div>
          </form>
        </div>

        {(selectedEvidence || selectedTag) && (
          <div className="ra-chip-row">
            {selectedEvidence && (
              <button
                type="button"
                className="button button-quiet ra-filter-pill is-active"
                onClick={() => {
                  setSelectedEvidence("");
                  setPage(1);
                }}
              >
                {bilingual(lang, "缺失信息", "Evidence")}: {selectedEvidence} ×
              </button>
            )}
            {selectedTag && (
              <button
                type="button"
                className="button button-quiet ra-filter-pill is-active"
                onClick={() => {
                  setSelectedTag("");
                  setPage(1);
                }}
              >
                Tag: {selectedTag} ×
              </button>
            )}
          </div>
        )}
      </div>

      {/* 4 KPI Summary Cards */}
      <div className="ra-kpi-grid-4">
        <article className="page-card ra-kpi-card">
          <span className="ra-kpi-label">{bilingual(lang, "最新 Review 数", "Latest reviews")}</span>
          <strong className="ra-kpi-value">{(summary.latest_reviews ?? 0).toLocaleString()}</strong>
        </article>
        <article className="page-card ra-kpi-card">
          <span className="ra-kpi-label">{bilingual(lang, "已填写原因", "With reason")}</span>
          <strong className="ra-kpi-value">{(summary.with_reason ?? 0).toLocaleString()}</strong>
          <small className="muted">
            {bilingual(lang, `${summary.empty_reason ?? 0} 条未填`, `${summary.empty_reason ?? 0} empty`)}
          </small>
        </article>
        <article className="page-card ra-kpi-card">
          <span className="ra-kpi-label">{bilingual(lang, "结构化证据", "Structured evidence")}</span>
          <strong className="ra-kpi-value">
            {(summary.with_structured_evidence ?? 0).toLocaleString()}
          </strong>
        </article>
        <article className="page-card ra-kpi-card">
          <span className="ra-kpi-label">{bilingual(lang, "匹配案例", "Matched cases")}</span>
          <strong className="ra-kpi-value">{(data?.total ?? 0).toLocaleString()}</strong>
        </article>
      </div>

      {/* Cluster Panels + Confusion Matrix */}
      <div className="ra-two-col-grid">
        <section className="page-card ra-chart-card">
          <div className="ra-card-header">
            <h3>{bilingual(lang, "缺失信息聚类", "Missing evidence clusters")}</h3>
          </div>
          {evidenceItems.length === 0 ? (
            <p className="muted">{bilingual(lang, "暂无缺失信息聚类", "No missing evidence clusters")}</p>
          ) : (
            <div className="ra-dist-list">
              {evidenceItems.map((item) => {
                const isSelected = selectedEvidence === item.key;
                return (
                  <button
                    key={item.key}
                    type="button"
                    className={`ra-cluster-bar-btn${isSelected ? " is-active" : ""}`}
                    onClick={() => {
                      setSelectedEvidence(isSelected ? "" : item.key);
                      setPage(1);
                    }}
                  >
                    <span>{item.label || item.key}</span>
                    <div className="ra-dist-track">
                      <i style={{ width: `${(100 * item.count) / maxEvidence}%`, background: "var(--accent)" }} />
                    </div>
                    <strong>{item.count}</strong>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        <section className="page-card ra-chart-card">
          <div className="ra-card-header">
            <h3>{bilingual(lang, "高频场景 / 判定标签", "Top scene & decision tags")}</h3>
          </div>
          {tagItems.length === 0 ? (
            <p className="muted">{bilingual(lang, "暂无标签聚类", "No tag clusters")}</p>
          ) : (
            <div className="ra-dist-list">
              {tagItems.map((item) => {
                const isSelected = selectedTag === item.key;
                return (
                  <button
                    key={item.key}
                    type="button"
                    className={`ra-cluster-bar-btn${isSelected ? " is-active" : ""}`}
                    onClick={() => {
                      setSelectedTag(isSelected ? "" : item.key);
                      setPage(1);
                    }}
                  >
                    <span>{item.label || item.key}</span>
                    <div className="ra-dist-track">
                      <i style={{ width: `${(100 * item.count) / maxTag}%`, background: "var(--chart-teal, #0d9488)" }} />
                    </div>
                    <strong>{item.count}</strong>
                  </button>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {data?.confusion?.rows && data.confusion.rows.length > 0 && (
        <section className="page-card ra-table-card">
          <div className="ra-card-header">
            <h3>{bilingual(lang, "混淆矩阵（点击单元格下钻）", "Confusion matrix (click cell to filter)")}</h3>
          </div>
          <div className="ra-table-scroll">
            <table className="ra-data-table comparison-matrix">
              <thead>
                <tr>
                  <th>GT ↓ / Model →</th>
                  {(data.confusion.columns || []).map((col) => (
                    <th key={col}>{col}</th>
                  ))}
                  <th>Σ</th>
                  <th>Acc</th>
                </tr>
              </thead>
              <tbody>
                {data.confusion.rows.map((row) => (
                  <tr key={row.gt_label}>
                    <th>{row.gt_label}</th>
                    {(data.confusion?.columns || []).map((col) => {
                      const cnt = row.cells?.[col] || 0;
                      const isDiag = col === row.gt_label;
                      return (
                        <td
                          key={col}
                          className={isDiag ? "matrix-correct" : cnt > 0 ? "matrix-error" : ""}
                        >
                          <button
                            type="button"
                            className="ra-matrix-cell-btn"
                            disabled={cnt === 0}
                            onClick={() => {
                              setGtLabels([row.gt_label]);
                              if (col !== "NONE") setModelLabels([col]);
                              setPage(1);
                            }}
                          >
                            {cnt}
                          </button>
                        </td>
                      );
                    })}
                    <td>{row.total}</td>
                    <td>{`${(row.accuracy * 100).toFixed(1)}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Case List + Pagination */}
      <section className="page-card ra-table-card">
        <div className="ra-card-header">
          <h3>
            {bilingual(
              lang,
              `共 ${data?.total ?? 0} 条 · 当前显示 ${data?.items?.length ?? 0} 条`,
              `${data?.total ?? 0} total · showing ${data?.items?.length ?? 0}`,
            )}
          </h3>
        </div>

        {analysisQuery.isError ? (
          <div className="no-asset">
            {bilingual(lang, "加载失败，请点击刷新重试。", "Failed to load analysis cases.")}
          </div>
        ) : (data?.items || []).length === 0 ? (
          <div className="no-asset">
            {analysisQuery.isLoading
              ? bilingual(lang, "正在加载分析数据…", "Loading analysis cases…")
              : bilingual(lang, "当前筛选条件下暂无匹配案例", "No matching cases")}
          </div>
        ) : (
          <div className="ra-analysis-case-list">
            {(data?.items || []).map((item) => {
              const ann = item.annotation || {};
              const pred = item.prediction || {};
              const tags = item.case_label_context?.tags || ann.tags || [];
              const evidences = ann.missing_evidence || [];
              const reviewHref = item.review_url
                ? withWorkbenchBase(item.review_url.replace(/^\/manual/, ""))
                : withWorkbenchBase(`/review?issue=${encodeURIComponent(item.issue_id)}`);
              return (
                <article key={item.issue_id} className="analysis-case-row ra-analysis-row">
                  <div className="ra-analysis-row-head">
                    <div className="ra-analysis-id-col">
                      {item.voyager_issue_url ? (
                        <a
                          className="analysis-issue-link"
                          href={item.voyager_issue_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {item.issue_id} ↗
                        </a>
                      ) : (
                        <strong>{item.issue_id}</strong>
                      )}
                      <span className="muted">{item.title || item.scenario || "—"}</span>
                    </div>
                    <div className="ra-chip-row">
                      {item.comparison_status && (
                        <StatusChip
                          tone={
                            item.comparison_status === "match"
                              ? "ok"
                              : item.comparison_status === "mismatch"
                                ? "fail"
                                : "neutral"
                          }
                          label={item.comparison_status.toUpperCase()}
                        />
                      )}
                      <StatusChip tone="neutral" label={`GT: ${item.gt_label || "—"}`} />
                      <button
                        type="button"
                        className="button button-quiet ra-compact-btn"
                        onClick={() => void openLegacyModelHistory(item.issue_id)}
                      >
                        {bilingual(lang, "模型", "Model")}: {pred.label || "—"}
                        {pred.confidence != null ? ` · ${(pred.confidence * 100).toFixed(1)}%` : ""}
                      </button>
                    </div>
                  </div>

                  <div className="ra-analysis-row-body">
                    <p className={ann.note ? "" : "muted"}>
                      {ann.note || bilingual(lang, "未填写人工原因", "No manual reason recorded")}
                    </p>
                    {pred.reason && (
                      <p className="muted ra-small-copy">
                        {bilingual(lang, "模型说明：", "Model note: ")}
                        {pred.reason}
                      </p>
                    )}
                    {(tags.length > 0 || evidences.length > 0) && (
                      <div className="ra-chip-row">
                        {tags.map((t) => (
                          <span key={t} className="analysis-chip tag-chip">
                            {t}
                          </span>
                        ))}
                        {evidences.map((ev) => (
                          <span key={ev} className="analysis-chip evidence-chip">
                            {ev}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="ra-analysis-row-foot">
                    <span className="muted">
                      {ann.author || bilingual(lang, "未记录复核人", "Unknown reviewer")}
                      {ann.author_verified ? " · SSO" : ""} · {formatCstTime(ann.created_at, lang)}
                    </span>
                    <div className="ra-toolbar-actions">
                      <button
                        type="button"
                        className="button button-quiet ra-compact-btn"
                        onClick={() => openLegacyDiscussion(item.issue_id, ann.model_run_id)}
                      >
                        {bilingual(lang, "评论", "Discuss")}
                      </button>
                      <a className="button button-quiet ra-compact-btn" href={reviewHref}>
                        {bilingual(lang, "问题详情", "Open detail")}
                      </a>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}

        <Pagination
          page={data?.page || page}
          pageSize={pageSize}
          total={data?.total || 0}
          lang={lang}
          loading={analysisQuery.isFetching}
          onPageChange={setPage}
          onPageSizeChange={(next) => {
            setPageSize(next);
            setPage(1);
          }}
        />
      </section>
    </div>
  );
};
