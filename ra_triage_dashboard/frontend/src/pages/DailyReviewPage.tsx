import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  formatCstTime,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import { CaseMediaPreviewModal } from "../components/media/MediaStage";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

interface DailyReviewSummary {
  total: number;
  filled: number;
  unfilled: number;
  unknown: number;
  rate: number;
  coverage: number;
  reasons?: { low?: number; sample?: number };
}

interface DailyReviewDayOverview {
  date: string;
  source_status?: string;
  summary?: DailyReviewSummary | null;
}

interface DailyReviewRow {
  issue_id: string;
  date?: string;
  first_seen?: string;
  reason?: string;
  te_status: string;
  te_value?: string;
}

interface DailyReviewPayload {
  scope: { dataset: string; date?: string };
  version_membership?: boolean;
  date_options?: string[];
  summary?: DailyReviewSummary | null;
  daily_overview?: DailyReviewDayOverview[];
  result_distribution?: Array<{ value: string; count: number }>;
  items: DailyReviewRow[];
  total: number;
  page: number;
  size: number;
  source_status?: string;
  last_success_at?: string;
  snapshot_revision?: string;
}

export interface DailyReviewPageProps {
  active: boolean;
  lang: UiLanguage;
}

function readInitialDailyReviewParams() {
  if (typeof window === "undefined") {
    return { dataset: "1009", date: "", reason: "all", teStatus: "all", media: "bev", sort: "added", page: 1 };
  }
  const p = new URLSearchParams(window.location.search);
  return {
    dataset: p.get("dataset") || "1009",
    date: p.get("date") || "",
    reason: p.get("reason") || "all",
    teStatus: p.get("te_status") || "all",
    media: p.get("media") || "bev",
    sort: p.get("sort") || "added",
    page: Math.max(1, Number(p.get("page") || 1) || 1),
  };
}

export const DailyReviewPage: React.FC<DailyReviewPageProps> = ({ active, lang }) => {
  const init = useMemo(readInitialDailyReviewParams, []);
  const [dataset, setDataset] = useState(init.dataset);
  const [date, setDate] = useState(init.date);
  const [reason, setReason] = useState(init.reason);
  const [teStatus, setTeStatus] = useState(init.teStatus);
  const [media, setMedia] = useState(init.media);
  const [sort, setSort] = useState(init.sort);
  const [page, setPage] = useState(init.page);
  const [failedThumbs, setFailedThumbs] = useState<Record<string, number>>({});
  const [previewIssueId, setPreviewIssueId] = useState<string | null>(null);

  const query = useQuery<DailyReviewPayload>({
    queryKey: ["daily-review", dataset, date, reason, teStatus, sort, page],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        dataset,
        reason,
        te_status: teStatus,
        sort,
        page: String(page),
        include_overview: "true",
      });
      if (date) qs.set("date", date);
      return apiRequest<DailyReviewPayload>(`/api/daily-review/cases?${qs.toString()}`, { signal });
    },
    enabled: active,
    refetchInterval: active ? 30_000 : false,
    staleTime: 10_000,
  });

  const data = query.data;
  const summary = data?.summary;
  const pageCount = Math.max(1, Math.ceil((data?.total || 0) / Math.max(1, data?.size || 20)));

  const dateOptions = useMemo<UiSelectOption[]>(() => {
    const opts: UiSelectOption[] = [];
    if (data?.version_membership) {
      opts.push({ value: "", label: bilingual(lang, "整个版本", "Whole version") });
    }
    for (const d of data?.date_options || []) {
      opts.push({ value: d, label: d });
    }
    if (!opts.length) opts.push({ value: "", label: bilingual(lang, "全部日期", "All dates") });
    return opts;
  }, [data, lang]);

  const reasonOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "all", label: bilingual(lang, "全部来源", "All sources") },
      { value: "low", label: bilingual(lang, "低置信", "Low confidence") },
      { value: "sample", label: bilingual(lang, "抽样", "Sample") },
    ],
    [lang],
  );

  const statusOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "all", label: bilingual(lang, "全部状态", "All statuses") },
      { value: "filled", label: bilingual(lang, "已标", "Filled") },
      { value: "unfilled", label: bilingual(lang, "待标", "Pending") },
      { value: "unknown", label: bilingual(lang, "未知", "Unknown") },
    ],
    [lang],
  );

  const mediaOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "bev", label: "BEV" },
      { value: "camera", label: "Camera" },
    ],
    [],
  );

  const sortOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "added", label: bilingual(lang, "按入库时间", "By added time") },
      { value: "date", label: bilingual(lang, "按发生日期", "By occurrence date") },
    ],
    [lang],
  );

  const badgeText = (row: DailyReviewRow) =>
    row.te_status === "filled"
      ? `TE ${row.te_value || ""}`
      : row.te_status === "unfilled"
        ? bilingual(lang, "TE 待标", "TE pending")
        : bilingual(lang, "TE 未知", "TE unknown");

  const filledPct = summary?.total ? (100 * summary.filled) / summary.total : 0;
  const knownPct = summary?.total ? (100 * (summary.filled + summary.unfilled)) / summary.total : 0;

  const exportUrl = data?.snapshot_revision
    ? withWorkbenchBase(
        `/api/daily-review/export?dataset=${encodeURIComponent(dataset)}&date=${encodeURIComponent(data.scope.date || "")}&reason=${encodeURIComponent(reason)}&te_status=${encodeURIComponent(teStatus)}&sort=${encodeURIComponent(sort)}&revision=${encodeURIComponent(data.snapshot_revision)}`,
      )
    : "";

  return (
    <section
      id="dailyReviewPage"
      className="app-page ra-react-page"
      data-page="daily-review"
      data-react-island="daily-review"
    >
      <div className="panel-card">
        <div className="ra-page-header-row">
          <div>
            <h2>{bilingual(lang, "TE 每日标注进度观测", "TE Daily Labeling Progress")}</h2>
            <p className="muted">
              {data
                ? data.scope.dataset === "0821"
                  ? bilingual(lang, "0821 · 历史固定集", "0821 · Frozen set")
                  : `${data.scope.dataset} · ${data.scope.date || bilingual(lang, "整个版本", "Whole version")} · CST`
                : bilingual(lang, "正在读取快照…", "Reading snapshot…")}
            </p>
          </div>
          <div className="ra-inline-actions">
            <button
              type="button"
              className={`button ${dataset === "1009" ? "button-primary" : "button-quiet"}`}
              onClick={() => {
                setDataset("1009");
                setDate("");
                setPage(1);
              }}
            >
              1009
            </button>
            <button
              type="button"
              className={`button ${dataset === "0821" ? "button-primary" : "button-quiet"}`}
              onClick={() => {
                setDataset("0821");
                setDate("");
                setPage(1);
              }}
            >
              0821
            </button>
            {exportUrl && (
              <a className="button button-quiet" href={exportUrl} download>
                {bilingual(lang, "导出 CSV", "Export CSV")}
              </a>
            )}
            <button
              type="button"
              className="button button-quiet"
              disabled={query.isFetching}
              onClick={() => void query.refetch()}
            >
              {query.isFetching ? bilingual(lang, "刷新中…", "Refreshing…") : bilingual(lang, "刷新", "Refresh")}
            </button>
          </div>
        </div>

        <div className="ra-kpi-grid" style={{ marginTop: 12 }}>
          <div className="ra-kpi-card">
            <span>{bilingual(lang, "TE 进度", "TE progress")}</span>
            <strong>{summary ? `${summary.filled} / ${summary.total}` : "— / —"}</strong>
            <small>{summary?.total ? `${(summary.rate * 100).toFixed(1)}%` : "—"}</small>
          </div>
          <div className="ra-kpi-card">
            <span>{bilingual(lang, "低置信 / 抽样", "Low / Sample")}</span>
            <strong>
              {summary ? `${summary.reasons?.low || 0} / ${summary.reasons?.sample || 0}` : "—"}
            </strong>
            <small>
              {bilingual(lang, "未知", "Unknown")} {summary?.unknown ?? "—"}
            </small>
          </div>
          <div className="ra-kpi-card">
            <span>{bilingual(lang, "读取覆盖率", "Read coverage")}</span>
            <strong>{summary?.total ? `${(summary.coverage * 100).toFixed(1)}%` : "—"}</strong>
            <small>
              {data?.last_success_at ? `${formatCstTime(data.last_success_at, lang)} CST` : "—"}
            </small>
          </div>
        </div>

        <div className="ra-filter-grid" style={{ marginTop: 14 }}>
          {dataset !== "0821" && (
            <div className="ra-field-stack">
              <span>{bilingual(lang, "日期", "Date")}</span>
              <UiSelect
                id="raDailyReviewDate"
                value={date}
                options={dateOptions}
                ariaLabel={bilingual(lang, "选择日期", "Select date")}
                onChange={(v) => {
                  setDate(v);
                  setPage(1);
                }}
              />
            </div>
          )}
          <div className="ra-field-stack">
            <span>{bilingual(lang, "来源", "Reason")}</span>
            <UiSelect
              id="raDailyReviewReason"
              value={reason}
              options={reasonOptions}
              ariaLabel={bilingual(lang, "按来源筛选", "Filter by reason")}
              onChange={(v) => {
                setReason(v);
                setPage(1);
              }}
            />
          </div>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "TE 状态", "TE status")}</span>
            <UiSelect
              id="raDailyReviewStatus"
              value={teStatus}
              options={statusOptions}
              ariaLabel={bilingual(lang, "按状态筛选", "Filter by TE status")}
              onChange={(v) => {
                setTeStatus(v);
                setPage(1);
              }}
            />
          </div>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "缩略图", "Thumbnail")}</span>
            <UiSelect
              id="raDailyReviewMedia"
              value={media}
              options={mediaOptions}
              ariaLabel={bilingual(lang, "切换缩略图类型", "Thumbnail type")}
              onChange={(v) => {
                setMedia(v);
                setFailedThumbs({});
              }}
            />
          </div>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "排序", "Sort")}</span>
            <UiSelect
              id="raDailyReviewSort"
              value={sort}
              options={sortOptions}
              ariaLabel={bilingual(lang, "排序方式", "Sort order")}
              onChange={(v) => {
                setSort(v);
                setPage(1);
              }}
            />
          </div>
        </div>
      </div>

      {/* Charts */}
      {data && (
        <div className="panel-card te-charts-grid">
          <div className="te-donut-card">
            <div
              className={`te-donut${!summary?.total ? " is-empty" : ""}`}
              style={
                {
                  "--te-filled": `${filledPct}%`,
                  "--te-known": `${knownPct}%`,
                } as React.CSSProperties
              }
            />
            <div className="te-legend-list">
              {(
                [
                  ["filled", bilingual(lang, "已标", "Filled"), summary?.filled],
                  ["unfilled", bilingual(lang, "待标", "Pending"), summary?.unfilled],
                  ["unknown", bilingual(lang, "未知", "Unknown"), summary?.unknown],
                ] as const
              ).map(([key, label, val]) => (
                <button
                  key={key}
                  type="button"
                  className="te-legend-item"
                  aria-pressed={teStatus === key}
                  onClick={() => {
                    setTeStatus(teStatus === key ? "all" : key);
                    setPage(1);
                  }}
                >
                  <i className={`te-swatch te-${key}`} />
                  <span>{label}</span>
                  <strong>{val ?? "—"}</strong>
                </button>
              ))}
            </div>
          </div>

          {dataset !== "0821" && (data.daily_overview?.length || 0) > 0 && (
            <div className="te-daily-strip">
              {data.daily_overview!.map((day) => {
                const n = day.summary;
                return (
                  <button
                    key={day.date}
                    type="button"
                    className="te-day"
                    aria-pressed={day.date === data.scope.date}
                    onClick={() => {
                      setDate(day.date);
                      setPage(1);
                    }}
                  >
                    <strong>{n?.total ? `${(n.rate * 100).toFixed(0)}%` : "—"}</strong>
                    <span>{day.date.slice(5).replace("-", "/")}</span>
                    <small>{n ? `${n.filled}/${n.total}` : "—"}</small>
                  </button>
                );
              })}
            </div>
          )}

          <div className="te-distribution-list">
            {(data.result_distribution || []).map((row) => {
              const pct = summary?.filled ? (row.count / summary.filled) * 100 : 0;
              return (
                <div key={row.value} className="te-result-row">
                  <div>
                    <span>{row.value}</span>
                    <strong>
                      {row.count}
                      <small> · {pct.toFixed(0)}%</small>
                    </strong>
                  </div>
                  <div className="te-result-track">
                    <i style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Gallery */}
      <div className="panel-card">
        <div className="ra-page-header-row">
          <h3>
            {bilingual(
              lang,
              `${data?.total ?? 0} 个案例 · 状态筛选仅影响 Gallery`,
              `${data?.total ?? 0} cases · Status filters affect Gallery only`,
            )}
          </h3>
          <div className="ra-inline-actions">
            <button
              type="button"
              className="button button-quiet"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              {bilingual(lang, "上一页", "Previous")}
            </button>
            <span className="muted">
              {page} / {pageCount}
            </span>
            <button
              type="button"
              className="button button-quiet"
              disabled={page >= pageCount}
              onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
            >
              {bilingual(lang, "下一页", "Next")}
            </button>
          </div>
        </div>

        {query.isLoading ? (
          <div className="no-asset">{bilingual(lang, "正在加载案例…", "Loading cases…")}</div>
        ) : !data?.items?.length ? (
          <div className="no-asset">
            {bilingual(lang, "此筛选下暂无案例。", "No cases match the current filters.")}
          </div>
        ) : (
          <div className="issue-grid" style={{ marginTop: 12 }}>
            {data.items.map((row) => {
              const retryKey = failedThumbs[row.issue_id] || 0;
              const isFailed = retryKey < 0;
              const thumbSrc = withWorkbenchBase(
                `/api/case-thumbnails/${encodeURIComponent(row.issue_id)}?kind=${encodeURIComponent(media)}${retryKey > 0 ? `&r=${retryKey}` : ""}`,
              );
              return (
                <article key={row.issue_id} className="issue-card te-card">
                  <div
                    className="issue-thumbnail"
                    role="button"
                    tabIndex={0}
                    aria-label={`${row.issue_id} ${bilingual(lang, "查看媒体", "View media")}`}
                    onClick={() => setPreviewIssueId(row.issue_id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setPreviewIssueId(row.issue_id);
                      }
                    }}
                  >
                    {!isFailed ? (
                      <img
                        src={thumbSrc}
                        alt={`${row.issue_id} ${media}`}
                        loading="lazy"
                        onError={() =>
                          setFailedThumbs((prev) => ({ ...prev, [row.issue_id]: -1 }))
                        }
                      />
                    ) : (
                      <div className="issue-thumbnail-placeholder te-placeholder">
                        <span>{media.toUpperCase()}</span>
                        <small>{bilingual(lang, "图片待就绪", "Image pending")}</small>
                      </div>
                    )}
                  </div>
                  <div className="issue-card-body">
                    <div className="issue-card-heading">
                      <a
                        className="issue-id"
                        href={`https://voyager.intra.xiaojukeji.com/static/management/#/issue/${encodeURIComponent(row.issue_id)}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {row.issue_id} ↗
                      </a>
                      <span className="te-reason">
                        {row.reason === "low"
                          ? bilingual(lang, "低置信", "Low")
                          : bilingual(lang, "抽样", "Sample")}
                      </span>
                    </div>
                    <div className="issue-card-labels">
                      <span className="te-result" data-status={row.te_status}>
                        {badgeText(row)}
                      </span>
                      {isFailed && (
                        <button
                          type="button"
                          className="te-retry"
                          onClick={() =>
                            setFailedThumbs((prev) => ({
                              ...prev,
                              [row.issue_id]: Math.abs(prev[row.issue_id] || 0) + 1,
                            }))
                          }
                        >
                          {bilingual(lang, "重试图片", "Retry image")}
                        </button>
                      )}
                    </div>
                    <div className="te-case-date muted">
                      {bilingual(lang, "发生", "Occurred")} {row.date || "—"} ·{" "}
                      {bilingual(lang, "入库", "Added")}{" "}
                      {row.first_seen ? formatCstTime(row.first_seen, lang) : "—"} CST
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>

      {previewIssueId && (
        <CaseMediaPreviewModal
          issueId={previewIssueId}
          lang={lang}
          onClose={() => setPreviewIssueId(null)}
        />
      )}
    </section>
  );
};
