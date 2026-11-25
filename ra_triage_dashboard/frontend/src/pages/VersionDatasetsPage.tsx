import React, { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
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
import { StatusChip } from "../components/ui/StatusChip";
import { UiSelect } from "../components/ui/UiSelect";

interface VersionDatasetCatalogItem {
  id: string;
  release_family: string;
  targets?: number;
  total?: number;
  historical?: boolean;
  states?: Record<string, number>;
}

interface VersionWorkbenchItem {
  issue_id: string;
  is_target?: boolean;
  is_sample?: boolean;
  is_low?: boolean;
  state?: string;
  te_status?: string;
  te_value?: string;
  date?: string;
  issue_time?: string | number;
  ra_start_timestamp?: string | number;
  first_seen?: string | number;
  trigger?: string;
  review_submitted?: boolean;
  reviewers?: Array<{ reviewer?: string; submitted?: boolean }>;
  binding?: {
    run_id?: string;
    campaign_id?: string;
    assignee?: string;
    assignees?: string[];
  };
  prediction?: {
    model_label?: string;
    model_confidence?: number | null;
  };
}

interface VersionWorkbenchResponse {
  dataset_id: string;
  snapshot_revision?: string;
  page: number;
  page_size: number;
  total: number;
  items: VersionWorkbenchItem[];
  assignees?: string[];
  date_options?: string[];
  dataset: VersionDatasetCatalogItem;
  count_scope?: {
    total?: number;
    targets?: number;
    sampled?: number;
    completed?: number;
    low_only?: number;
    states?: Record<string, number>;
    trail_links?: Record<string, string>;
  };
  composition?: {
    total: number;
    pending: number;
    excluded: number;
    groups: Array<{ key: string; count: number; ratio: number }>;
  };
  te?: {
    source_status?: string;
    last_success_at?: string | number;
    summary: { total: number; filled: number; unfilled: number; unknown: number };
    distribution: Array<{ value: string; count: number }>;
    daily: Array<{
      date: string;
      summary: { total: number; filled: number; unfilled: number; unknown: number; rate: number };
    }>;
  };
  rd?: {
    source_status?: string;
    total: number;
    completed: number;
    pending: number;
    conflict: number;
    distribution: Record<string, number>;
  } | null;
}

interface BatchHistoryResponse {
  items: Array<{
    created_at?: string | number;
    target_added?: number;
    added?: number;
    changed?: number;
  }>;
}

function formatShortCst(value: string | number | undefined, lang: UiLanguage): string {
  if (!value) return "—";
  const num = Number(value);
  const d = new Date(Number.isFinite(num) && num > 0 ? (num < 1e11 ? num * 1000 : num) : value);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat(lang === "en" ? "en-GB" : "zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

function labelColor(value: string): string {
  switch (value) {
    case "成功":
    case "正确触发":
      return "var(--chart-teal, #0d9488)";
    case "误触发":
      return "var(--chart-rose, #e11d48)";
    case "失败":
      return "var(--chart-indigo, #4f46e5)";
    case "无需协助":
      return "var(--chart-blue, #2563eb)";
    case "未接起":
      return "var(--chart-slate, #64748b)";
    default:
      return "var(--muted)";
  }
}

function teValueLabel(value: string | undefined, lang: UiLanguage): string {
  const raw = String(value ?? "");
  const map: Record<string, [string, string]> = {
    失败: ["失败", "Failed"],
    成功: ["成功", "Succeeded"],
    超出范围: ["超出范围", "Out of scope"],
    out_of_scope: ["超出范围", "Out of scope"],
    误触发: ["误触发", "False trigger"],
    未接起: ["未接起", "Unanswered"],
    无需协助: ["无需协助", "No assistance needed"],
    正确触发: ["正确触发", "Correct trigger"],
  };
  return map[raw] ? bilingual(lang, map[raw][0], map[raw][1]) : raw;
}

function teBadgeText(row: VersionWorkbenchItem, lang: UiLanguage): string {
  if (row.te_status === "filled") return `TE · ${teValueLabel(row.te_value, lang)}`;
  if (row.te_status === "unfilled") return bilingual(lang, "TE 待标", "TE pending");
  if (row.te_status === "not_target") return bilingual(lang, "未纳入复核", "Outside review set");
  return bilingual(lang, "TE 未知", "TE unknown");
}

function readInitialRoute() {
  const p = new URLSearchParams(typeof window !== "undefined" ? window.location.search : "");
  const ps = Number(p.get("page_size") || DEFAULT_CASE_PAGE_SIZE);
  return {
    dataset: p.get("dataset") || "",
    mode: p.get("mode") || "targets",
    sort: p.get("sort") || "added",
    query: p.get("q") || "",
    date: p.get("date") || "",
    teStatus: p.get("te_status") || "all",
    media: p.get("media") === "camera" ? "camera" : "bev",
    assignee: p.get("assignee") || "",
    reviewStatus: p.get("review_status") || "all",
    page: Math.max(1, Number(p.get("page")) || 1),
    pageSize: CASE_PAGE_SIZES.includes(ps as (typeof CASE_PAGE_SIZES)[number])
      ? ps
      : DEFAULT_CASE_PAGE_SIZE,
  };
}

export interface VersionDatasetsPageProps {
  active: boolean;
  lang: UiLanguage;
}

export const VersionDatasetsPage: React.FC<VersionDatasetsPageProps> = ({ active, lang }) => {
  const initial = useMemo(() => readInitialRoute(), []);
  const [dataset, setDataset] = useState(initial.dataset);
  const [mode, setMode] = useState(initial.mode);
  const [sort, setSort] = useState(initial.sort);
  const [queryInput, setQueryInput] = useState(initial.query);
  const [query, setQuery] = useState(initial.query);
  const [date, setDate] = useState(initial.date);
  const [teStatus, setTeStatus] = useState(initial.teStatus);
  const [media, setMedia] = useState<"bev" | "camera">(initial.media as "bev" | "camera");
  const [assignee, setAssignee] = useState(initial.assignee);
  const [reviewStatus, setReviewStatus] = useState(initial.reviewStatus);
  const [page, setPage] = useState(initial.page);
  const [pageSize, setPageSize] = useState(initial.pageSize);
  const [batchesOpen, setBatchesOpen] = useState(false);

  const catalogQuery = useQuery<{ items: VersionDatasetCatalogItem[] }>({
    queryKey: ["version-datasets-catalog"],
    queryFn: ({ signal }) => apiRequest("/api/version-datasets?include_legacy=true", { signal }),
    enabled: active,
    staleTime: 30_000,
  });

  const catalogItems = catalogQuery.data?.items || [];
  const effectiveDataset = useMemo(() => {
    if (dataset && catalogItems.some((item) => item.id === dataset)) return dataset;
    return catalogItems.find((item) => (item.targets || 0) > 0)?.id || catalogItems[0]?.id || "";
  }, [dataset, catalogItems]);

  useEffect(() => {
    if (active && effectiveDataset && effectiveDataset !== dataset) {
      setDataset(effectiveDataset);
    }
  }, [active, effectiveDataset, dataset]);

  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    if (!window.location.pathname.replace(/\/+$/, "").endsWith("/version-datasets")) return;
    const url = new URL(window.location.href);
    const params: Record<string, string> = {
      dataset: effectiveDataset,
      mode,
      sort,
      q: query,
      page: String(page),
      page_size: String(pageSize),
      date,
      te_status: teStatus,
      media,
      assignee,
      review_status: reviewStatus,
    };
    for (const [k, v] of Object.entries(params)) {
      if (v) url.searchParams.set(k, v);
      else url.searchParams.delete(k);
    }
    window.history.replaceState(window.history.state, "", url);
  }, [
    active,
    effectiveDataset,
    mode,
    sort,
    query,
    page,
    pageSize,
    date,
    teStatus,
    media,
    assignee,
    reviewStatus,
  ]);

  const workbenchQuery = useQuery<VersionWorkbenchResponse>({
    queryKey: [
      "version-datasets-workbench",
      effectiveDataset,
      page,
      pageSize,
      mode,
      sort,
      query,
      date,
      teStatus,
      assignee,
      reviewStatus,
    ],
    queryFn: ({ signal }) => {
      const sp = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
        mode,
        sort,
        q: query,
        date,
        te_status: teStatus,
        assignee,
        review_status: reviewStatus,
      });
      return apiRequest(`/api/version-datasets/${encodeURIComponent(effectiveDataset)}/workbench?${sp}`, {
        signal,
      });
    },
    enabled: active && Boolean(effectiveDataset),
    placeholderData: keepPreviousData,
    staleTime: 25_000,
    refetchInterval: active ? 30_000 : false,
  });

  const batchesQuery = useQuery<BatchHistoryResponse>({
    queryKey: ["version-datasets-batches", effectiveDataset],
    queryFn: ({ signal }) =>
      apiRequest(`/api/version-datasets/${encodeURIComponent(effectiveDataset)}/batches`, { signal }),
    enabled: active && batchesOpen && Boolean(effectiveDataset) && effectiveDataset !== "historical-0821",
    staleTime: 30_000,
  });

  const wb = workbenchQuery.data;
  const currentDataset = wb?.dataset || catalogItems.find((i) => i.id === effectiveDataset);
  const historical = Boolean(currentDataset?.historical);
  const releaseFamilyMatch = /^release-(20\d{6})-odd2$/.exec(effectiveDataset);

  const scope = wb?.count_scope;
  const states = scope?.states || currentDataset?.states || {};
  const totalCount = scope?.total ?? currentDataset?.total ?? 0;
  const publishedCount = states.published || 0;
  const waitingCount = states.waiting_metadata || 0;
  const targetsCount = scope?.targets ?? currentDataset?.targets ?? 0;

  const teSummary = wb?.te?.summary;
  const teRate = teSummary?.total ? (100 * teSummary.filled) / teSummary.total : 0;
  const rd = wb?.rd;
  const rdRate = rd?.total ? ((100 * rd.completed) / rd.total).toFixed(1) : "0.0";

  const exportUrl =
    wb?.snapshot_revision && effectiveDataset
      ? withWorkbenchBase(
          `/api/version-datasets/${encodeURIComponent(effectiveDataset)}/workbench.csv?${new URLSearchParams({
            mode,
            q: query,
            sort,
            date,
            te_status: teStatus,
            revision: wb.snapshot_revision,
            assignee,
            review_status: reviewStatus,
          }).toString()}`,
        )
      : "";

  const openCaseMedia = async (issueId: string) => {
    const win = window as unknown as {
      openVersionDatasetMedia?: (id: string, kind?: string) => Promise<void>;
      openMedia?: (kind: string, idx: number, opts?: Record<string, unknown>) => void;
    };
    if (typeof win.openMedia === "function") {
      try {
        const data = await apiRequest<Record<string, unknown>>(
          `/api/cases/${encodeURIComponent(issueId)}/media`,
        );
        const row = wb?.items.find((r) => r.issue_id === issueId);
        win.openMedia(media, 0, {
          caseData: {
            ...data,
            gt_label: "",
            reference_media: true,
            te_observation: { ...row, version_dataset: true },
          },
        });
      } catch {
        // Fallback to Voyager link if media endpoint fails
      }
    }
  };

  const resetPage = () => setPage(1);

  return (
    <div className="ra-react-page ra-version-datasets" data-react-island="version-datasets">
      <div className="page-card ra-page-toolbar-card">
        <div className="ra-section-header">
          <div>
            <h2 className="ra-page-title">{bilingual(lang, "版本数据工作台", "Version datasets")}</h2>
            <p className="ra-page-subtitle">
              {bilingual(
                lang,
                "查看各发布版本的抽样/低置信复核目标、TE/RD 标注进度与媒体图库。",
                "Inspect release cohorts, review targets, TE/RD annotation progress, and media cards.",
              )}
            </p>
          </div>
          <div className="ra-toolbar-actions">
            {releaseFamilyMatch && (
              <a
                className="button button-quiet"
                href={withWorkbenchBase(`/version-metrics?families=${releaseFamilyMatch[1]}`)}
              >
                {bilingual(lang, "查看版本指标 ↗", "Version metrics ↗")}
              </a>
            )}
            {exportUrl && (
              <a className="button button-quiet" href={exportUrl}>
                {bilingual(lang, "导出 CSV", "Export CSV")}
              </a>
            )}
            <button
              type="button"
              className="button button-quiet"
              disabled={workbenchQuery.isFetching}
              onClick={() => {
                void catalogQuery.refetch();
                void workbenchQuery.refetch();
              }}
            >
              {workbenchQuery.isFetching
                ? bilingual(lang, "刷新中…", "Refreshing…")
                : bilingual(lang, "刷新", "Refresh")}
            </button>
          </div>
        </div>

        <div className="ra-filter-grid">
          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "发布版本", "Release version")}</span>
            <UiSelect
              id="raVersionDatasetPicker"
              value={effectiveDataset}
              options={catalogItems.map((item) => ({
                value: item.id,
                label: `${item.release_family.slice(4)} · ${item.targets ?? "—"} ${bilingual(lang, "复核案例", "review cases")}`,
              }))}
              ariaLabel={bilingual(lang, "发布版本", "Release version")}
              disabled={catalogItems.length === 0}
              onChange={(next) => {
                setDataset(next);
                setDate("");
                if (next === "historical-0821") {
                  setAssignee("");
                  setReviewStatus("all");
                }
                resetPage();
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "范围视角", "Scope")}</span>
            <UiSelect
              id="raVersionDatasetMode"
              value={mode}
              options={[
                { value: "targets", label: bilingual(lang, "全部复核目标", "All review targets") },
                { value: "sampled_targets", label: bilingual(lang, "随机抽样集", "Random sample") },
                { value: "low", label: bilingual(lang, "低置信（不含抽样）", "Low confidence only") },
              ]}
              ariaLabel={bilingual(lang, "范围视角", "Scope")}
              onChange={(next) => {
                setMode(next);
                resetPage();
              }}
            />
          </div>

          {!historical && (
            <div className="ra-filter-field">
              <span className="ra-field-label">{bilingual(lang, "发生日期", "Date")}</span>
              <UiSelect
                id="raVersionDatasetDate"
                value={date}
                options={[
                  { value: "", label: bilingual(lang, "全部日期", "All dates") },
                  ...(wb?.date_options || []).map((d) => ({ value: d, label: d })),
                ]}
                ariaLabel={bilingual(lang, "发生日期", "Date")}
                disabled={!wb}
                onChange={(next) => {
                  setDate(next);
                  resetPage();
                }}
              />
            </div>
          )}

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "TE 状态", "TE status")}</span>
            <UiSelect
              id="raVersionDatasetTeStatus"
              value={teStatus}
              options={[
                { value: "all", label: bilingual(lang, "全部 TE 状态", "All TE statuses") },
                { value: "filled", label: bilingual(lang, "TE 已标", "TE filled") },
                { value: "unfilled", label: bilingual(lang, "TE 待标", "TE pending") },
                { value: "unknown", label: bilingual(lang, "TE 未知", "TE unknown") },
              ]}
              ariaLabel={bilingual(lang, "TE 状态", "TE status")}
              onChange={(next) => {
                setTeStatus(next);
                resetPage();
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "负责人", "Assignee")}</span>
            <UiSelect
              id="raVersionDatasetAssignee"
              value={assignee}
              disabled={historical}
              options={[
                { value: "", label: bilingual(lang, "全部负责人", "All assignees") },
                ...(wb?.assignees || []).map((a) => ({ value: a, label: a })),
              ]}
              ariaLabel={bilingual(lang, "负责人", "Assignee")}
              onChange={(next) => {
                setAssignee(next);
                resetPage();
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "联合复核", "Combined review")}</span>
            <UiSelect
              id="raVersionDatasetReviewStatus"
              value={reviewStatus}
              disabled={historical}
              options={[
                { value: "all", label: bilingual(lang, "全部复核状态", "All review states") },
                { value: "pending", label: bilingual(lang, "待复核", "Pending review") },
                { value: "completed", label: bilingual(lang, "已完成", "Completed") },
              ]}
              ariaLabel={bilingual(lang, "联合复核", "Combined review")}
              onChange={(next) => {
                setReviewStatus(next);
                resetPage();
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "排序", "Sort")}</span>
            <UiSelect
              id="raVersionDatasetSort"
              value={sort}
              options={[
                { value: "added", label: bilingual(lang, "按入库时间", "By added time") },
                { value: "confidence", label: bilingual(lang, "按置信度升序", "Lowest confidence") },
                { value: "issue_id", label: bilingual(lang, "按 Issue ID", "By Issue ID") },
              ]}
              ariaLabel={bilingual(lang, "排序", "Sort")}
              onChange={(next) => {
                setSort(next);
                resetPage();
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "缩略图", "Media")}</span>
            <UiSelect
              id="raVersionDatasetMedia"
              value={media}
              options={[
                { value: "bev", label: "BEV" },
                { value: "camera", label: "Camera" },
              ]}
              ariaLabel={bilingual(lang, "缩略图", "Media")}
              onChange={(next) => setMedia(next === "camera" ? "camera" : "bev")}
            />
          </div>

          <form
            className="ra-filter-field ra-search-field"
            onSubmit={(e) => {
              e.preventDefault();
              setQuery(queryInput.trim());
              resetPage();
            }}
          >
            <span className="ra-field-label">{bilingual(lang, "搜索 Issue", "Search Issue")}</span>
            <div className="ra-inline-input-group">
              <input
                type="search"
                value={queryInput}
                onChange={(e) => setQueryInput(e.target.value)}
                placeholder={bilingual(lang, "输入 Issue ID / 场景…", "Issue ID or scene…")}
                aria-label={bilingual(lang, "搜索 Issue", "Search Issue")}
              />
              <button type="submit" className="button button-quiet">
                {bilingual(lang, "搜索", "Search")}
              </button>
            </div>
          </form>
        </div>
      </div>

      {workbenchQuery.isError && (
        <div className="page-card ra-error-banner" role="alert">
          {bilingual(lang, "读取版本数据失败，请点击刷新重试。", "Failed to load version dataset. Refresh to retry.")}
        </div>
      )}

      {/* 4 KPI Cards */}
      <div className="ra-kpi-grid-4">
        <article className="page-card ra-kpi-card">
          <span className="ra-kpi-label">{bilingual(lang, historical ? "固定案例" : "发现总数", historical ? "Frozen cases" : "Discovered")}</span>
          <strong className="ra-kpi-value">{totalCount.toLocaleString()}</strong>
          {scope?.trail_links?.all && (
            <a className="text-link ra-kpi-link" href={scope.trail_links.all} target="_blank" rel="noopener noreferrer">
              {bilingual(lang, "Trail 全部案例 ↗", "Trail all cases ↗")}
            </a>
          )}
        </article>
        <article className="page-card ra-kpi-card">
          <span className="ra-kpi-label">{bilingual(lang, "已回刷", "Published")}</span>
          <strong className="ra-kpi-value">{historical ? "—" : publishedCount.toLocaleString()}</strong>
          {!historical && scope?.trail_links?.published && (
            <a className="text-link ra-kpi-link" href={scope.trail_links.published} target="_blank" rel="noopener noreferrer">
              {bilingual(lang, "Trail 已回刷 ↗", "Trail published ↗")}
            </a>
          )}
        </article>
        <article className="page-card ra-kpi-card">
          <span className="ra-kpi-label">{bilingual(lang, "复核目标", "Review targets")}</span>
          <strong className="ra-kpi-value">{targetsCount.toLocaleString()}</strong>
          {scope?.trail_links?.targets && (
            <a className="text-link ra-kpi-link" href={scope.trail_links.targets} target="_blank" rel="noopener noreferrer">
              {bilingual(lang, "Trail 复核目标 ↗", "Trail targets ↗")}
            </a>
          )}
        </article>
        <article className="page-card ra-kpi-card">
          <span className="ra-kpi-label">{bilingual(lang, "待齐备", "Awaiting source")}</span>
          <strong className="ra-kpi-value">{historical ? "—" : waitingCount.toLocaleString()}</strong>
          {!historical && scope?.trail_links?.source_waiting && (
            <a className="text-link ra-kpi-link" href={scope.trail_links.source_waiting} target="_blank" rel="noopener noreferrer">
              {bilingual(lang, "Trail 待齐备 ↗", "Trail awaiting ↗")}
            </a>
          )}
        </article>
      </div>

      {/* TE & RD Progress Panels */}
      {wb && (
        <div className="ra-two-col-grid">
          <section className="page-card ra-chart-card">
            <div className="ra-card-header">
              <h3>{bilingual(lang, "TE 标注进度与三分类", "TE progress & breakdown")}</h3>
              <StatusChip
                tone={wb.te?.source_status === "ready" ? "ok" : "warn"}
                label={`Trail · ${formatShortCst(wb.te?.last_success_at, lang)} CST`}
              />
            </div>
            {teSummary && (
              <>
                <div className="ra-progress-headline">
                  <strong>{teSummary.total ? `${teRate.toFixed(1)}%` : "—"}</strong>
                  <span className="muted">
                    {teSummary.filled} / {teSummary.total}
                  </span>
                  <div className="ra-chip-row">
                    {(["filled", "unfilled", "unknown"] as const).map((statusKey) => {
                      const count = teSummary[statusKey];
                      const activeChip = teStatus === statusKey;
                      const labels: Record<string, [string, string]> = {
                        filled: ["已标", "Filled"],
                        unfilled: ["待标", "Pending"],
                        unknown: ["未知", "Unknown"],
                      };
                      return (
                        <button
                          key={statusKey}
                          type="button"
                          className={`button button-quiet ra-filter-pill${activeChip ? " is-active" : ""}`}
                          aria-pressed={activeChip}
                          onClick={() => {
                            setTeStatus(activeChip ? "all" : statusKey);
                            resetPage();
                          }}
                        >
                          {bilingual(lang, labels[statusKey][0], labels[statusKey][1])} · {count}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div className="ra-stacked-bar" aria-hidden="true">
                  <i className="te-filled" style={{ flex: `${teSummary.filled} 0 0` }} />
                  <i className="te-unfilled" style={{ flex: `${teSummary.unfilled} 0 0` }} />
                  <i className="te-unknown" style={{ flex: `${teSummary.unknown} 0 0` }} />
                </div>
              </>
            )}

            <div className="ra-dist-list">
              {[...(wb.te?.distribution || [])]
                .sort((a, b) => b.count - a.count)
                .map((row) => {
                  const share = teSummary?.filled ? (100 * row.count) / teSummary.filled : 0;
                  return (
                    <div key={row.value} className="ra-dist-row">
                      <span>{teValueLabel(row.value, lang)}</span>
                      <div className="ra-dist-track">
                        <i style={{ width: `${share}%`, background: labelColor(row.value) }} />
                      </div>
                      <strong>
                        {row.count} <small>({share.toFixed(1)}%)</small>
                      </strong>
                    </div>
                  );
                })}
            </div>

            {!historical && (wb.te?.daily?.length || 0) > 0 && (
              <div className="ra-daily-bars">
                <div className="ra-daily-bars-head">
                  <span className="ra-field-label">{bilingual(lang, "按发生日筛选", "Filter by date")}</span>
                  {date && (
                    <button
                      type="button"
                      className="button button-quiet ra-compact-btn"
                      onClick={() => {
                        setDate("");
                        resetPage();
                      }}
                    >
                      {bilingual(lang, "清除日期", "Clear date")}
                    </button>
                  )}
                </div>
                <div className="ra-daily-chip-grid">
                  {wb.te!.daily.map((day) => {
                    const isSelected = day.date === date;
                    return (
                      <button
                        key={day.date}
                        type="button"
                        className={`ra-day-chip${isSelected ? " is-active" : ""}`}
                        aria-pressed={isSelected}
                        onClick={() => {
                          setDate(isSelected ? "" : day.date);
                          resetPage();
                        }}
                      >
                        <span>{day.date.slice(5)}</span>
                        <strong>
                          {day.summary.filled}/{day.summary.total}
                        </strong>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </section>

          <section className="page-card ra-chart-card">
            <div className="ra-card-header">
              <h3>{bilingual(lang, "RD 标注进度与构成", "RD progress & cohort mix")}</h3>
              {rd && rd.source_status !== "unsupported" && (
                <span className="muted">
                  {rd.completed} / {rd.total} ({rdRate}%)
                </span>
              )}
            </div>

            {!rd || rd.source_status === "unsupported" ? (
              <p className="muted">
                {bilingual(
                  lang,
                  "此历史固定集暂不提供 RD 统计。",
                  "RD statistics are unavailable for this frozen historical set.",
                )}
              </p>
            ) : (
              <>
                <div className="ra-stacked-bar" aria-hidden="true">
                  <i className="rd-filled" style={{ flex: `${rd.completed} 0 0` }} />
                  <i className="rd-pending" style={{ flex: `${rd.pending} 0 0` }} />
                  <i className="rd-conflict" style={{ flex: `${rd.conflict} 0 0` }} />
                </div>
                <div className="ra-inline-stats">
                  <span>{bilingual(lang, `已标 ${rd.completed}`, `Labeled ${rd.completed}`)}</span>
                  <span>{bilingual(lang, `待标 ${rd.pending}`, `Pending ${rd.pending}`)}</span>
                  <span>{bilingual(lang, `冲突 ${rd.conflict}`, `Conflicts ${rd.conflict}`)}</span>
                </div>
                {rd.completed > 0 && (
                  <div className="ra-dist-list">
                    {(["正确触发", "误触发", "无需协助"] as const).map((key) => {
                      const count = rd.distribution?.[key] || 0;
                      const share = (100 * count) / rd.completed;
                      return (
                        <div key={key} className="ra-dist-row">
                          <span>{teValueLabel(key, lang)}</span>
                          <div className="ra-dist-track">
                            <i style={{ width: `${share}%`, background: labelColor(key) }} />
                          </div>
                          <strong>
                            {count} <small>({share.toFixed(1)}%)</small>
                          </strong>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}

            {wb.composition && (
              <div className="ra-composition-box">
                <div className="ra-field-label">
                  {bilingual(
                    lang,
                    `目标构成 · 总计 ${wb.composition.total}`,
                    `Target composition · Total ${wb.composition.total}`,
                  )}
                </div>
                <div className="ra-stacked-bar" aria-hidden="true">
                  {wb.composition.groups.map((g) => (
                    <i
                      key={g.key}
                      className={`version-reason-${g.key}`}
                      style={{ flex: `${g.count} 0 0` }}
                    />
                  ))}
                </div>
                <div className="ra-inline-stats">
                  {wb.composition.groups.map((g) => {
                    const labels: Record<string, [string, string]> = {
                      low: ["低置信", "Low conf"],
                      sample: ["抽样", "Sample"],
                      other: ["其他", "Other"],
                    };
                    const pair = labels[g.key] || [g.key, g.key];
                    return (
                      <span key={g.key}>
                        {bilingual(lang, pair[0], pair[1])}: <strong>{g.count}</strong> (
                        {(100 * g.ratio).toFixed(1)}%)
                      </span>
                    );
                  })}
                </div>
              </div>
            )}
          </section>
        </div>
      )}

      {/* Case Card Gallery */}
      <section className="page-card ra-gallery-card">
        <div className="ra-card-header">
          <h3>
            {bilingual(lang, "案例列表", "Cases")} ({wb?.total ?? 0})
          </h3>
          {workbenchQuery.isFetching && (
            <span className="muted">{bilingual(lang, "加载中…", "Loading…")}</span>
          )}
        </div>

        {!wb || wb.items.length === 0 ? (
          <div className="no-asset">
            {workbenchQuery.isLoading
              ? bilingual(lang, "正在加载版本案例…", "Loading version cases…")
              : bilingual(lang, "该筛选暂无案例", "No cases in this view")}
          </div>
        ) : (
          <div className="ra-version-case-grid">
            {wb.items.map((row) => {
              const binding = row.binding || {};
              const reviewHref = binding.run_id
                ? withWorkbenchBase(
                    `/review?${new URLSearchParams({
                      issue: row.issue_id,
                      run: binding.run_id,
                      ...(binding.campaign_id ? { work_split_id: binding.campaign_id } : {}),
                      comparison: "all",
                    }).toString()}`,
                  )
                : `https://voyager.intra.xiaojukeji.com/static/management/#/issue/${encodeURIComponent(row.issue_id)}`;
              const owner =
                binding.assignees?.join(", ") ||
                binding.assignee ||
                (historical ? "—" : bilingual(lang, "未分配", "Unassigned"));
              const modelLabel = row.prediction?.model_label
                ? teValueLabel(row.prediction.model_label, lang)
                : historical
                  ? bilingual(lang, "历史固定集", "Frozen set")
                  : row.state || "—";
              const conf = row.prediction?.model_confidence;
              return (
                <article key={row.issue_id} className="issue-card version-card ra-version-card">
                  <button
                    type="button"
                    className="ra-version-thumb-btn"
                    onClick={() => void openCaseMedia(row.issue_id)}
                    aria-label={`${row.issue_id} ${bilingual(lang, "查看媒体", "View media")}`}
                  >
                    {row.is_target ? (
                      <img
                        src={withWorkbenchBase(
                          `/api/case-thumbnails/${encodeURIComponent(row.issue_id)}?kind=${media}`,
                        )}
                        loading="lazy"
                        decoding="async"
                        alt={`${row.issue_id} ${media.toUpperCase()}`}
                      />
                    ) : (
                      <div className="ra-thumb-fallback">{media.toUpperCase()}</div>
                    )}
                  </button>
                  <div className="issue-card-body">
                    <div className="issue-card-heading">
                      <a
                        className="issue-id"
                        href={reviewHref}
                        target={binding.run_id ? undefined : "_blank"}
                        rel={binding.run_id ? undefined : "noopener noreferrer"}
                      >
                        {row.issue_id} ↗
                      </a>
                      <span className="muted">
                        {row.is_sample
                          ? bilingual(lang, "抽样", "Sample")
                          : row.is_low
                            ? bilingual(lang, "低置信", "Low")
                            : ""}
                      </span>
                    </div>
                    <div className="version-card-line">
                      <span title={modelLabel}>{modelLabel}</span>
                      <span className="muted">
                        {conf == null ? "" : `${(conf * 100).toFixed(1)}%`}
                      </span>
                    </div>
                    <div className="version-card-statuses">
                      <span className="version-te-result" data-status={row.te_status || "unknown"}>
                        {teBadgeText(row, lang)}
                      </span>
                    </div>
                    <div className="version-card-meta muted">
                      <span>{owner}</span>
                      <time>{formatShortCst(row.issue_time || row.ra_start_timestamp, lang)} CST</time>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}

        <Pagination
          page={wb?.page || page}
          pageSize={pageSize}
          total={wb?.total || 0}
          lang={lang}
          loading={workbenchQuery.isFetching}
          onPageChange={setPage}
          onPageSizeChange={(nextSize) => {
            setPageSize(nextSize);
            setPage(1);
          }}
        />
      </section>

      {!historical && (
        <details
          className="page-card ra-disclosure-card"
          open={batchesOpen}
          onToggle={(e) => setBatchesOpen((e.currentTarget as HTMLDetailsElement).open)}
        >
          <summary>{bilingual(lang, "入库批次记录", "Ingestion batch history")}</summary>
          <div className="ra-batch-list">
            {batchesQuery.isLoading ? (
              <span className="muted">{bilingual(lang, "加载中…", "Loading…")}</span>
            ) : (batchesQuery.data?.items || []).length === 0 ? (
              <span className="muted">{bilingual(lang, "暂无记录", "No records")}</span>
            ) : (
              (batchesQuery.data?.items || []).map((b, i) => (
                <div key={i} className="ra-batch-item">
                  <time>{formatShortCst(b.created_at, lang)} CST</time>
                  <span>
                    {bilingual(lang, "新增目标", "Targets")} +{b.target_added || 0} ·{" "}
                    {bilingual(lang, "候选", "Candidates")} +{b.added || 0} ·{" "}
                    {bilingual(lang, "更新", "Updated")} {b.changed || 0}
                  </span>
                </div>
              ))
            )}
          </div>
        </details>
      )}
    </div>
  );
};
