import React, { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, UiLanguage } from "../bridge/useWorkbenchBridge";
import { MultiSelect } from "../components/ui/MultiSelect";
import {
  CASE_PAGE_SIZES,
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { StatusChip } from "../components/ui/StatusChip";
import { UiSelect } from "../components/ui/UiSelect";

const VM_SCHEMES = [
  "model",
  "chain",
  "model_human_sim",
  "chain_human_sim",
  "chain_post_human_sim",
] as const;
type VmSchemeKey = (typeof VM_SCHEMES)[number];
const VM_DEFAULT_SCHEMES: VmSchemeKey[] = ["chain", "chain_post_human_sim"];

const VM_COLORS: Record<VmSchemeKey, string> = {
  model: "var(--chart-blue, #2563eb)",
  chain: "var(--chart-teal, #0d9488)",
  model_human_sim: "var(--chart-slate, #64748b)",
  chain_human_sim: "var(--chart-indigo, #4f46e5)",
  chain_post_human_sim: "var(--accent)",
};

const VM_REPORT_IDS: Record<string, string> = {
  "20261009": "2210331546058",
  "20261016": "2210331433301",
  "20261023": "2210462491274",
  "20261030": "2210502394530",
};

interface VmSchemeMetric {
  accuracy?: number | null;
  macro_f1?: number | null;
  correct: number;
  total: number;
  reference_total: number;
  human_count: number;
  per_class: Array<{ label: string; recall: number | null; tp: number; support: number }>;
}

interface VmReleaseItem {
  family: string;
  status: "ready" | "unavailable" | "error";
  membership_changed?: boolean;
  valid_total?: number;
  sample_total?: number;
  published_total?: number;
  observed_at?: string;
  started_at?: string;
  coverage?: Record<string, { observed: number; filled: number; total: number }>;
  metrics?: Record<string, VmSchemeMetric>;
  thresholds?: Array<{
    threshold: number;
    full_low: number;
    full_total: number;
    reduction: string | number;
    human_count: number;
    total: number;
    accuracy: number | null;
    correct: number;
  }>;
}

interface VersionMetricsResponse {
  items: VmReleaseItem[];
  catalog: Array<{ family: string; dataset_id: string }>;
  selected: string[];
  refresh?: { status?: string; completed?: number; total?: number };
}

function schemeLabel(key: VmSchemeKey, lang: UiLanguage, short = false): string {
  const full: Record<VmSchemeKey, [string, string]> = {
    model: ["纯模型", "Model"],
    chain: ["模型＋规则", "Model + rules"],
    model_human_sim: ["模型＋人工（模拟）", "Model + review (sim)"],
    chain_human_sim: ["模型＋规则＋人工（模拟）", "Model + rules + review (sim)"],
    chain_post_human_sim: ["模型＋规则＋规则后人工（模拟）", "Model + rules + post-rule review (sim)"],
  };
  const compact: Record<VmSchemeKey, [string, string]> = {
    model: ["纯模型", "Model"],
    chain: ["模型＋规则", "Model + rules"],
    model_human_sim: ["模型＋人工", "Model + review"],
    chain_human_sim: ["模型＋规则＋人工", "Model + rules + review"],
    chain_post_human_sim: ["规则后人工", "Post-rule review"],
  };
  const table = short ? compact : full;
  return bilingual(lang, table[key][0], table[key][1]);
}

function metricLabel(key: string, lang: UiLanguage): string {
  const table: Record<string, [string, string]> = {
    accuracy: ["准确率 ACC", "Accuracy ACC"],
    macro_f1: ["Macro-F1", "Macro-F1"],
    recall_correct: ["正确触发召回率", "Correct-trigger recall"],
    recall_false: ["误触发召回率", "False-trigger recall"],
    recall_no_assist: ["无需协助召回率", "No-assistance recall"],
    human_share: ["人工介入比例（模拟）", "Human intervention (sim)"],
  };
  return table[key] ? bilingual(lang, table[key][0], table[key][1]) : key;
}

function extractMetricValue(row: VmReleaseItem, scheme: VmSchemeKey, metric: string): number | null {
  const m = row.metrics?.[scheme];
  if (!m) return null;
  if (metric === "human_share") return m.total ? m.human_count / m.total : null;
  const classMap: Record<string, string> = {
    recall_correct: "正确触发",
    recall_false: "误触发",
    recall_no_assist: "无需协助",
  };
  if (classMap[metric]) {
    return m.per_class?.find((c) => c.label === classMap[metric])?.recall ?? null;
  }
  const val = (m as unknown as Record<string, unknown>)[metric];
  return typeof val === "number" ? val : null;
}

function formatPct(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export interface VersionMetricsPageProps {
  active: boolean;
  lang: UiLanguage;
  canWrite: boolean;
}

export const VersionMetricsPage: React.FC<VersionMetricsPageProps> = ({
  active,
  lang,
  canWrite,
}) => {
  const queryClient = useQueryClient();
  const initialParams = useMemo(
    () => new URLSearchParams(typeof window !== "undefined" ? window.location.search : ""),
    [],
  );

  const [families, setFamilies] = useState<string>(() => initialParams.get("families") || "");
  const [metric, setMetric] = useState<string>(() => initialParams.get("metric") || "accuracy");
  const [reference, setReference] = useState<string>(() => initialParams.get("reference") || "te");
  const [exclusion, setExclusion] = useState<string>(
    () => (initialParams.get("exclusion") === "exclude" ? "exclude" : "all"),
  );
  const [threshold, setThreshold] = useState<string>(() => {
    const t = Number(initialParams.get("threshold") || 0.9);
    return [0.9, 0.85, 0.8, 0.76, 0.75, 0.65].includes(t) ? t.toFixed(2) : "0.90";
  });
  const [schemes, setSchemes] = useState<VmSchemeKey[]>(() => {
    const raw = initialParams.get("schemes");
    if (!raw) return [...VM_DEFAULT_SCHEMES];
    const parsed = VM_SCHEMES.filter((s) => raw.split(",").includes(s));
    return parsed.length ? parsed : [...VM_DEFAULT_SCHEMES];
  });
  const [page, setPage] = useState<number>(() => Math.max(1, Number(initialParams.get("page")) || 1));
  const [pageSize, setPageSize] = useState<number>(() => {
    const ps = Number(initialParams.get("page_size") || DEFAULT_CASE_PAGE_SIZE);
    return CASE_PAGE_SIZES.includes(ps as (typeof CASE_PAGE_SIZES)[number])
      ? ps
      : DEFAULT_CASE_PAGE_SIZE;
  });
  const [hoveredFamily, setHoveredFamily] = useState<string | null>(null);
  const [thresholdFamily, setThresholdFamily] = useState<string>(
    () => initialParams.get("threshold_family") || "",
  );
  const [thresholdOpen, setThresholdOpen] = useState<boolean>(
    () => initialParams.get("threshold_open") === "1",
  );

  const metricsQuery = useQuery<VersionMetricsResponse>({
    queryKey: ["version-metrics", families, reference, exclusion, threshold],
    queryFn: ({ signal }) => {
      const sp = new URLSearchParams({
        families,
        reference,
        exclusion,
        threshold,
        page: "1",
        page_size: "100",
      });
      return apiRequest(`/api/version-metrics?${sp}`, { signal });
    },
    enabled: active,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    refetchInterval: (q) => (active && q.state.data?.refresh?.status === "running" ? 5_000 : false),
  });

  const refreshMutation = useMutation({
    mutationFn: (selectedFamilies: string[]) =>
      apiRequest("/api/version-metrics/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-RA-Triage-Request": "1" },
        body: JSON.stringify({ families: selectedFamilies }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["version-metrics"] });
    },
  });

  const data = metricsQuery.data;
  const rows = data?.items || [];
  const catalog = data?.catalog || [];
  const selectedFamilyList = useMemo(() => {
    if (families === "all") return [];
    if (families) return families.split(",").filter(Boolean);
    return data?.selected || [];
  }, [families, data?.selected]);

  const orderedDescending = useMemo(
    () => [...rows].sort((a, b) => b.family.localeCompare(a.family)),
    [rows],
  );

  const effectiveThresholdFamily = useMemo(() => {
    if (thresholdFamily && rows.some((r) => r.family === thresholdFamily)) return thresholdFamily;
    return orderedDescending[0]?.family || "";
  }, [thresholdFamily, rows, orderedDescending]);

  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    if (!window.location.pathname.replace(/\/+$/, "").endsWith("/version-metrics")) return;
    const url = new URL(window.location.href);
    const kv: Record<string, string> = {
      families,
      metric,
      schemes: schemes.join(","),
      reference,
      exclusion,
      threshold,
      page: String(page),
      page_size: String(pageSize),
      threshold_family: effectiveThresholdFamily,
      threshold_open: thresholdOpen ? "1" : "",
    };
    for (const [k, v] of Object.entries(kv)) {
      if (v) url.searchParams.set(k, v);
      else url.searchParams.delete(k);
    }
    window.history.replaceState(window.history.state, "", url);
  }, [
    active,
    families,
    metric,
    schemes,
    reference,
    exclusion,
    threshold,
    page,
    pageSize,
    effectiveThresholdFamily,
    thresholdOpen,
  ]);

  const toggleScheme = (key: VmSchemeKey) => {
    setSchemes((prev) =>
      prev.includes(key) ? prev.filter((item) => item !== key) : VM_SCHEMES.filter((s) => prev.includes(s) || s === key),
    );
  };

  // SVG chart scale calculation (matches legacy 4-interval percentage scale)
  const chartModel = useMemo(() => {
    const vals = rows
      .flatMap((row) => schemes.map((s) => extractMetricValue(row, s, metric)))
      .filter((v): v is number => v != null && Number.isFinite(v))
      .map((v) => v * 100);
    let domain: [number, number] = [0, 100];
    let ticks = [0, 25, 50, 75, 100];
    if (vals.length) {
      const min = Math.max(0, Math.floor(Math.min(...vals) + 1e-9));
      const max = Math.min(100, Math.ceil(Math.max(...vals) - 1e-9));
      const step = Math.max(1, Math.ceil((max - min) / 4));
      const lower = Math.max(0, Math.min(min, 100 - step * 4));
      domain = [lower, lower + step * 4];
      ticks = Array.from({ length: 5 }, (_, i) => lower + i * step);
    }
    const width = Math.max(680, rows.length * 80 + 128);
    const height = 288;
    const left = 52;
    const right = 48;
    const top = 32;
    const bottom = 36;
    const plotW = width - left - right;
    const plotH = height - top - bottom;
    const x = (i: number) => left + ((i + 0.5) * plotW) / Math.max(1, rows.length);
    const y = (v: number) => top + ((domain[1] - v * 100) / Math.max(1, domain[1] - domain[0])) * plotH;
    return { width, height, left, right, top, bottom, plotW, plotH, ticks, x, y, hasValues: vals.length > 0 };
  }, [rows, schemes, metric]);

  const pagedRows = useMemo(() => {
    const start = (page - 1) * pageSize;
    return orderedDescending.slice(start, start + pageSize);
  }, [orderedDescending, page, pageSize]);

  const hoveredRow = hoveredFamily ? rows.find((r) => r.family === hoveredFamily) : null;
  const thresholdRow = rows.find((r) => r.family === effectiveThresholdFamily);
  const refreshJob = data?.refresh;
  const isUpdating = refreshJob?.status === "running" || refreshMutation.isPending;

  return (
    <div className="ra-react-page ra-version-metrics" data-react-island="version-metrics">
      <div className="page-card ra-page-toolbar-card">
        <div className="ra-section-header">
          <div>
            <h2 className="ra-page-title">{bilingual(lang, "跨版本评测指标", "Cross-version metrics")}</h2>
            <p className="ra-page-subtitle">
              {bilingual(
                lang,
                "基于冻结 Trail 指标回执对比纯模型、规则链路与人工模拟五套方案表现。",
                "Compare five evaluation schemes across releases using immutable Trail metric receipts.",
              )}
            </p>
          </div>
          <div className="ra-toolbar-actions">
            {isUpdating && (
              <StatusChip
                tone="warn"
                label={bilingual(
                  lang,
                  `更新中 ${refreshJob?.completed || 0}/${refreshJob?.total || 0}`,
                  `Updating ${refreshJob?.completed || 0}/${refreshJob?.total || 0}`,
                )}
              />
            )}
            <button
              type="button"
              className="button button-quiet"
              onClick={() => {
                setMetric("accuracy");
                setReference("te");
                setExclusion("all");
                setThreshold("0.90");
                setSchemes([...VM_DEFAULT_SCHEMES]);
                setPage(1);
              }}
            >
              {bilingual(lang, "重置筛选", "Reset")}
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={!canWrite || isUpdating || !(data?.selected?.length)}
              title={
                canWrite
                  ? bilingual(lang, "只读刷新指标快照", "Refresh Trail metric snapshots")
                  : bilingual(lang, "需要 writer 或管理员权限", "Writer or admin access required")
              }
              onClick={() => {
                if (data?.selected?.length) refreshMutation.mutate(data.selected);
              }}
            >
              {bilingual(lang, "更新指标", "Refresh metrics")}
            </button>
          </div>
        </div>

        <div className="ra-filter-grid">
          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "评测版本", "Release versions")}</span>
            <MultiSelect
              id="raVmVersionPicker"
              values={selectedFamilyList}
              options={catalog.map((d) => ({ value: d.family, label: d.family.slice(4) }))}
              lang={lang}
              ariaLabel={bilingual(lang, "评测版本", "Release versions")}
              allLabel={bilingual(lang, "全部版本", "All versions")}
              onChange={(next) => {
                setFamilies(next.length ? next.join(",") : "all");
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "核心指标", "Metric")}</span>
            <UiSelect
              id="raVmMetric"
              value={metric}
              options={[
                "accuracy",
                "macro_f1",
                "recall_correct",
                "recall_false",
                "recall_no_assist",
                "human_share",
              ].map((k) => ({ value: k, label: metricLabel(k, lang) }))}
              ariaLabel={bilingual(lang, "核心指标", "Metric")}
              onChange={setMetric}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "参考真值", "Reference")}</span>
            <UiSelect
              id="raVmReference"
              value={reference}
              options={[
                { value: "te", label: bilingual(lang, "TE 原始标注", "Original TE") },
                { value: "rd", label: bilingual(lang, "RD 标注", "RD labels") },
                { value: "te_prime", label: bilingual(lang, "TE′ 人工标注", "Manual TE′") },
                { value: "arbitrated", label: bilingual(lang, "裁决结果", "Adjudication") },
              ]}
              ariaLabel={bilingual(lang, "参考真值", "Reference")}
              onChange={(next) => {
                setReference(next);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "排除口径", "Exclusions")}</span>
            <UiSelect
              id="raVmExclusion"
              value={exclusion}
              options={[
                { value: "all", label: bilingual(lang, "全部三分类有效", "All valid samples") },
                { value: "exclude", label: bilingual(lang, "剔除人工排除项", "Remove manual exclusions") },
              ]}
              ariaLabel={bilingual(lang, "排除口径", "Exclusions")}
              onChange={(next) => {
                setExclusion(next);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "低置信阈值", "Confidence threshold")}</span>
            <UiSelect
              id="raVmThreshold"
              value={threshold}
              options={["0.90", "0.85", "0.80", "0.76", "0.75", "0.65"].map((t) => ({
                value: t,
                label: `conf < ${t}`,
              }))}
              ariaLabel={bilingual(lang, "低置信阈值", "Confidence threshold")}
              onChange={(next) => {
                setThreshold(next);
                setPage(1);
              }}
            />
          </div>
        </div>

        {/* 5 Scheme Legend Toggles */}
        <div className="ra-chip-row ra-vm-legend" role="group" aria-label={bilingual(lang, "显示方案", "Visible schemes")}>
          {VM_SCHEMES.map((key) => {
            const activeScheme = schemes.includes(key);
            return (
              <button
                key={key}
                type="button"
                className={`button button-secondary vm-scheme-button${activeScheme ? " is-active" : ""}`}
                style={{ "--vm-color": VM_COLORS[key] } as React.CSSProperties}
                aria-pressed={activeScheme}
                title={schemeLabel(key, lang, false)}
                onClick={() => toggleScheme(key)}
              >
                <i className="vm-swatch" aria-hidden="true" />
                {schemeLabel(key, lang, true)}
              </button>
            );
          })}
        </div>
      </div>

      {/* SVG Trend Chart Card */}
      <section className="page-card ra-chart-card">
        <div className="ra-card-header">
          <h3>
            {bilingual(lang, "跨版本趋势", "Cross-version trend")} · {metricLabel(metric, lang)}
          </h3>
          {hoveredRow && hoveredRow.status === "ready" && (
            <div className="ra-inline-stats">
              <strong>release-{hoveredRow.family}</strong>
              {schemes.map((s) => (
                <span key={s} style={{ color: VM_COLORS[s] }}>
                  {schemeLabel(s, lang, true)}: <b>{formatPct(extractMetricValue(hoveredRow, s, metric))}</b>
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="ra-table-scroll">
          {metricsQuery.isError ? (
            <div className="no-asset">
              {bilingual(lang, "指标读取失败，请重试。", "Failed to load metrics. Please retry.")}
            </div>
          ) : !rows.length || !schemes.length || !chartModel.hasValues ? (
            <div className="no-asset">
              {metricsQuery.isLoading
                ? bilingual(lang, "正在读取指标…", "Loading metrics…")
                : bilingual(lang, "当前筛选暂无有效指标快照", "No valid metric snapshots for current filters")}
            </div>
          ) : (
            <svg
              className="vm-trend-svg"
              width={chartModel.width}
              height={chartModel.height}
              viewBox={`0 0 ${chartModel.width} ${chartModel.height}`}
              role="img"
              aria-label={`${bilingual(lang, "跨版本", "Cross-version")} ${metricLabel(metric, lang)}`}
              onMouseLeave={() => setHoveredFamily(null)}
            >
              {chartModel.ticks.map((tick) => {
                const yy = chartModel.y(tick / 100);
                return (
                  <g key={tick}>
                    <line
                      x1={chartModel.left}
                      y1={yy}
                      x2={chartModel.width - chartModel.right}
                      y2={yy}
                      className="vm-grid-line"
                    />
                    <text x={chartModel.left - 10} y={yy + 4} textAnchor="end" className="vm-axis vm-y-axis">
                      {tick}%
                    </text>
                  </g>
                );
              })}

              {schemes.map((key) => {
                let d = "";
                let open = false;
                rows.forEach((row, i) => {
                  const v = extractMetricValue(row, key, metric);
                  if (v == null) {
                    open = false;
                    return;
                  }
                  d += `${open ? "L" : "M"}${chartModel.x(i)},${chartModel.y(v)} `;
                  open = true;
                });
                return (
                  <g key={key}>
                    <path d={d} fill="none" stroke={VM_COLORS[key]} strokeWidth={2.5} className="vm-series-line" />
                    {rows.map((row, i) => {
                      const v = extractMetricValue(row, key, metric);
                      if (v == null) return null;
                      const cx = chartModel.x(i);
                      const cy = chartModel.y(v);
                      return (
                        <g key={`${key}-${row.family}`}>
                          <circle
                            cx={cx}
                            cy={cy}
                            r={hoveredFamily === row.family ? 5 : 3.5}
                            fill="var(--raised)"
                            stroke={VM_COLORS[key]}
                            strokeWidth={2}
                          />
                          <text x={cx} y={cy - 10} textAnchor="middle" className="vm-value-label">
                            {formatPct(v, 1)}
                          </text>
                        </g>
                      );
                    })}
                  </g>
                );
              })}

              {rows.map((row, i) => {
                const colW = chartModel.plotW / Math.max(1, rows.length);
                const label = `${row.family.slice(4, 6)}-${row.family.slice(6)}`;
                return (
                  <g
                    key={row.family}
                    onMouseEnter={() => setHoveredFamily(row.family)}
                    onFocus={() => setHoveredFamily(row.family)}
                    tabIndex={0}
                    role="button"
                    aria-label={`release-${row.family}`}
                  >
                    <rect
                      x={chartModel.left + i * colW}
                      y={0}
                      width={colW}
                      height={chartModel.height}
                      fill="transparent"
                    />
                    <text
                      x={chartModel.x(i)}
                      y={chartModel.height - 12}
                      textAnchor="middle"
                      className="vm-axis"
                    >
                      {label}
                    </text>
                  </g>
                );
              })}
            </svg>
          )}
        </div>
      </section>

      {/* Five-Scheme Paginated Release Report Table */}
      <section className="page-card ra-table-card">
        <div className="ra-card-header">
          <h3>
            {bilingual(lang, "各版本五方案明细", "Release breakdown")} · {metricLabel(metric, lang)}
          </h3>
        </div>
        <div className="ra-table-scroll">
          <table className="ra-data-table">
            <thead>
              <tr>
                <th>{bilingual(lang, "版本", "Release")}</th>
                <th>{bilingual(lang, "有效 / 抽样", "Valid / sample")}</th>
                <th>{bilingual(lang, "TE 已标", "TE filled")}</th>
                <th>{bilingual(lang, "RD 已标", "RD filled")}</th>
                {VM_SCHEMES.map((s) => (
                  <th key={s} title={schemeLabel(s, lang, false)}>
                    {schemeLabel(s, lang, true)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pagedRows.length === 0 ? (
                <tr>
                  <td colSpan={9} className="ra-table-empty">
                    {bilingual(lang, "暂无版本数据", "No release data")}
                  </td>
                </tr>
              ) : (
                pagedRows.map((row) => {
                  const reportId = VM_REPORT_IDS[row.family];
                  return (
                    <tr key={row.family}>
                      <th>
                        <strong>
                          {row.family.slice(4, 6)}-{row.family.slice(6)}
                        </strong>
                        {reportId && (
                          <>
                            {" "}
                            <a
                              className="text-link"
                              href={`https://cooper.didichuxing.com/didocs/${reportId}`}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {bilingual(lang, "报告", "Report")}
                            </a>
                          </>
                        )}
                      </th>
                      {row.status !== "ready" ? (
                        <td colSpan={8} className="muted">
                          {bilingual(lang, "暂无有效 Trail 快照", "No valid Trail snapshot")}
                        </td>
                      ) : (
                        <>
                          <td>
                            <strong>
                              {row.valid_total}/{row.sample_total}
                            </strong>
                          </td>
                          <td>
                            {row.coverage?.te
                              ? `${row.coverage.te.filled}/${row.coverage.te.total}`
                              : "—"}
                          </td>
                          <td>
                            {row.coverage?.rd
                              ? `${row.coverage.rd.filled}/${row.coverage.rd.total}`
                              : "—"}
                          </td>
                          {VM_SCHEMES.map((s) => {
                            const val = extractMetricValue(row, s, metric);
                            const m = row.metrics?.[s];
                            return (
                              <td key={s}>
                                <strong>{formatPct(val)}</strong>
                                {m && (
                                  <small className="ra-cell-sub">
                                    {metric === "human_share"
                                      ? `${m.human_count}/${m.total}`
                                      : `${m.correct}/${m.total}`}
                                  </small>
                                )}
                              </td>
                            );
                          })}
                        </>
                      )}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <Pagination
          page={page}
          pageSize={pageSize}
          total={orderedDescending.length}
          lang={lang}
          loading={metricsQuery.isFetching}
          onPageChange={setPage}
          onPageSizeChange={(next) => {
            setPageSize(next);
            setPage(1);
          }}
        />
      </section>

      {/* Threshold Sensitivity Disclosure */}
      <details
        className="page-card ra-disclosure-card"
        open={thresholdOpen}
        onToggle={(e) => setThresholdOpen((e.currentTarget as HTMLDetailsElement).open)}
      >
        <summary>{bilingual(lang, "低置信阈值灵敏度分析", "Confidence threshold sensitivity")}</summary>
        <div className="ra-threshold-controls">
          <UiSelect
            id="raVmThresholdFamily"
            value={effectiveThresholdFamily}
            options={orderedDescending.map((r) => ({
              value: r.family,
              label: `${r.family.slice(0, 4)} / ${r.family.slice(4, 6)}-${r.family.slice(6)}`,
            }))}
            ariaLabel={bilingual(lang, "选择版本", "Select release")}
            onChange={setThresholdFamily}
          />
          {thresholdRow?.status === "ready" && (
            <span className="muted">
              {bilingual(
                lang,
                `已回刷全量 ${thresholdRow.published_total ?? "—"} · 有效抽样 ${thresholdRow.valid_total ?? "—"}`,
                `Published ${thresholdRow.published_total ?? "—"} · Valid samples ${thresholdRow.valid_total ?? "—"}`,
              )}
            </span>
          )}
        </div>
        <div className="ra-table-scroll">
          <table className="ra-data-table">
            <thead>
              <tr>
                <th>{bilingual(lang, "阈值", "Threshold")}</th>
                <th>{bilingual(lang, "全量低置信占比", "Full low-conf share")}</th>
                <th>{bilingual(lang, "工作量变化", "Workload delta")}</th>
                <th>{bilingual(lang, "抽样人工介入", "Sample human share")}</th>
                <th>{bilingual(lang, "模拟准确率", "Simulated accuracy")}</th>
              </tr>
            </thead>
            <tbody>
              {(thresholdRow?.thresholds || []).length === 0 ? (
                <tr>
                  <td colSpan={5} className="ra-table-empty">
                    {bilingual(lang, "当前版本暂无阈值分析数据", "No threshold analysis available")}
                  </td>
                </tr>
              ) : (
                (thresholdRow?.thresholds || []).map((t) => (
                  <tr
                    key={t.threshold}
                    className={t.threshold.toFixed(2) === threshold ? "is-selected" : ""}
                  >
                    <th>{t.threshold.toFixed(2)}</th>
                    <td>
                      {t.full_low}/{t.full_total} ({formatPct(t.full_total ? t.full_low / t.full_total : null)})
                    </td>
                    <td>{t.reduction}</td>
                    <td>
                      {t.human_count}/{t.total} ({formatPct(t.total ? t.human_count / t.total : null)})
                    </td>
                    <td>
                      <strong>{formatPct(t.accuracy)}</strong>{" "}
                      <small className="muted">
                        ({t.correct}/{t.total})
                      </small>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
};
