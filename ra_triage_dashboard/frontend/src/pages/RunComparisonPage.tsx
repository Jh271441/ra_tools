import React, { useCallback, useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import {
  CASE_PAGE_SIZES,
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { StatusChip } from "../components/ui/StatusChip";
import { UiSelect } from "../components/ui/UiSelect";
import { useShortcut } from "../core/shortcutManager";

interface ModelRunItem {
  id: string;
  name?: string;
  source_name?: string;
  baseline_prediction_count?: number;
  created_at?: string;
}

interface ComparisonPrediction {
  model_label?: string;
  model_confidence?: number | null;
  model_reason?: string;
  correct?: boolean;
}

interface ComparisonCaseItem {
  issue_id: string;
  gt_label?: string;
  transition?: string;
  baseline?: ComparisonPrediction;
  candidate?: ComparisonPrediction;
  scene_review?: { tags?: string[]; author?: string };
}

interface ComparisonMatrix {
  columns: string[];
  rows: Array<{ gt_label: string; total: number; accuracy: number; cells: Record<string, number> }>;
}

interface ComparisonRunSnapshot {
  id?: string;
  name?: string;
  model?: { name?: string; resolved_id?: string; requested_id?: string };
  prompt?: { version?: string; mode?: string; sha256?: string; template?: string };
  input?: { profile?: string; config?: Record<string, unknown> };
}

interface ComparisonResponse {
  view_mode?: "single" | "pair";
  page: number;
  page_size: number;
  page_count: number;
  total: number;
  baseline_run?: ComparisonRunSnapshot | null;
  candidate_run?: ComparisonRunSnapshot | null;
  summary?: {
    total_count?: number;
    label_changed_count?: number;
    accuracy_delta?: number;
    transition_counts?: Record<string, number>;
    baseline?: { accuracy?: number; correct_count?: number; total_count?: number; prediction_count?: number };
    candidate?: { accuracy?: number; correct_count?: number; total_count?: number; prediction_count?: number };
  };
  matrices?: { baseline?: ComparisonMatrix; candidate?: ComparisonMatrix };
  items: ComparisonCaseItem[];
}

const TRANSITIONS = ["ALL", "P2F", "F2P", "F2F", "P2P"] as const;
const LABELS = ["正确触发", "误触发", "无需协助"];
const MODEL_LABELS = ["正确触发", "误触发", "无需协助", "真实卡住"];

function pct(v: number | undefined | null): string {
  return `${(Number(v || 0) * 100).toFixed(1)}%`;
}

function transitionText(t: string | undefined, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    ALL: ["全部", "All"],
    P2F: ["P2F · 退化", "P2F · Regression"],
    F2P: ["F2P · 改善", "F2P · Improvement"],
    F2F: ["F2F · 仍错误", "F2F · Still wrong"],
    P2P: ["P2P · 均正确", "P2P · Both correct"],
  };
  const key = String(t || "ALL").toUpperCase();
  return map[key] ? bilingual(lang, map[key][0], map[key][1]) : key;
}

export interface RunComparisonPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
  isAdmin: boolean;
}

export const RunComparisonPage: React.FC<RunComparisonPageProps> = ({
  active,
  lang,
  selectedBaselines,
  isAdmin,
}) => {
  const initialParams = useMemo(
    () => new URLSearchParams(typeof window !== "undefined" ? window.location.search : ""),
    [],
  );

  const [baselineRunId, setBaselineRunId] = useState(() => initialParams.get("baseline_run_id") || initialParams.get("baseline") || "");
  const [candidateRunId, setCandidateRunId] = useState(() => initialParams.get("candidate_run_id") || initialParams.get("candidate") || "");
  const [transition, setTransition] = useState(() => (initialParams.get("transition") || "ALL").toUpperCase());
  const [gtLabel, setGtLabel] = useState(() => initialParams.get("gt_label") || "ALL");
  const [baselineLabel, setBaselineLabel] = useState(() => initialParams.get("baseline_label") || "ALL");
  const [candidateLabel, setCandidateLabel] = useState(() => initialParams.get("candidate_label") || "ALL");
  const [labelChange, setLabelChange] = useState(() => (initialParams.get("label_change") || "ALL").toUpperCase());
  const [searchInput, setSearchInput] = useState(() => initialParams.get("q") || "");
  const [search, setSearch] = useState(() => initialParams.get("q") || "");
  const [page, setPage] = useState(() => Math.max(1, Number(initialParams.get("page")) || 1));
  const [pageSize, setPageSize] = useState(() => {
    const ps = Number(initialParams.get("page_size") || DEFAULT_CASE_PAGE_SIZE);
    return CASE_PAGE_SIZES.includes(ps as (typeof CASE_PAGE_SIZES)[number])
      ? ps
      : DEFAULT_CASE_PAGE_SIZE;
  });
  const [activeIssueId, setActiveIssueId] = useState<string | null>(null);
  const [modalTab, setModalTab] = useState<"output" | "inputs">("output");
  const [saveNotice, setSaveNotice] = useState<string>("");

  const baselinesParam = selectedBaselines.join(",");

  const runsQuery = useQuery<{ items: ModelRunItem[] }>({
    queryKey: ["model-runs-for-comparison", baselinesParam],
    queryFn: ({ signal }) => {
      const sp = new URLSearchParams();
      if (baselinesParam) sp.set("baselines", baselinesParam);
      return apiRequest(`/api/model-runs?${sp}`, { signal });
    },
    enabled: active,
    staleTime: 60_000,
  });

  const availableRuns = runsQuery.data?.items || [];

  // Auto-select top 2 covered runs if user has not chosen any yet
  useEffect(() => {
    if (!active || !availableRuns.length) return;
    if (baselineRunId || candidateRunId) return;
    const covered = availableRuns.filter((r) => Number(r.baseline_prediction_count || 0) > 0);
    const cand = covered[0]?.id || availableRuns[0]?.id || "";
    const base =
      covered[1]?.id || availableRuns.find((r) => r.id !== cand)?.id || "";
    setCandidateRunId(cand);
    setBaselineRunId(base);
  }, [active, availableRuns, baselineRunId, candidateRunId]);

  const hasValidSelection = Boolean(
    (baselineRunId || candidateRunId) && baselineRunId !== candidateRunId,
  );

  const comparisonQuery = useQuery<ComparisonResponse>({
    queryKey: [
      "model-run-comparison",
      baselineRunId,
      candidateRunId,
      transition,
      gtLabel,
      baselineLabel,
      candidateLabel,
      labelChange,
      search,
      page,
      pageSize,
      baselinesParam,
    ],
    queryFn: ({ signal }) => {
      const sp = new URLSearchParams({
        baseline_run_id: baselineRunId,
        candidate_run_id: candidateRunId,
        transition: transition.toLowerCase(),
        gt_label: gtLabel.toLowerCase() === "all" ? "all" : gtLabel,
        baseline_label: baselineLabel.toLowerCase() === "all" ? "all" : baselineLabel,
        candidate_label: candidateLabel.toLowerCase() === "all" ? "all" : candidateLabel,
        label_change: labelChange.toLowerCase(),
        q: search,
        page: String(page),
        page_size: String(pageSize),
      });
      if (baselinesParam) sp.set("baselines", baselinesParam);
      return apiRequest(`/api/model-run-comparison?${sp}`, { signal });
    },
    enabled: active && hasValidSelection,
    placeholderData: keepPreviousData,
    staleTime: 25_000,
  });

  const caseInputsQuery = useQuery<Record<string, unknown>>({
    queryKey: ["comparison-case-inputs", activeIssueId, baselineRunId, candidateRunId, baselinesParam],
    queryFn: ({ signal }) => {
      const sp = new URLSearchParams({
        baseline_run_id: baselineRunId,
        candidate_run_id: candidateRunId,
      });
      if (baselinesParam) sp.set("baselines", baselinesParam);
      return apiRequest(
        `/api/model-run-comparison/cases/${encodeURIComponent(activeIssueId || "")}/inputs?${sp}`,
        { signal },
      );
    },
    enabled: Boolean(activeIssueId) && modalTab === "inputs",
    staleTime: 60_000,
  });

  const saveCollectionMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ id: string; name: string }>("/api/run-comparison/save-collection", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": `pairwise-${baselineRunId}-${candidateRunId}-${Date.now()}`,
        },
        body: JSON.stringify({
          baseline_run_id: baselineRunId,
          candidate_run_id: candidateRunId,
          name: `${comparisonQuery.data?.baseline_run?.name || baselineRunId.slice(0, 8)} vs ${comparisonQuery.data?.candidate_run?.name || candidateRunId.slice(0, 8)}`,
        }),
      }),
    onSuccess: (created) => {
      setSaveNotice(
        bilingual(
          lang,
          `已保存为评测项目：${created.name || created.id}`,
          `Saved as evaluation project: ${created.name || created.id}`,
        ),
      );
    },
    onError: (err: Error) => {
      setSaveNotice(err.message);
    },
  });

  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    if (!window.location.pathname.replace(/\/+$/, "").endsWith("/run-comparison")) return;
    const url = new URL(window.location.href);
    const kv: Record<string, string> = {
      baseline: baselineRunId,
      candidate: candidateRunId,
      transition: transition !== "ALL" ? transition : "",
      gt_label: gtLabel !== "ALL" ? gtLabel : "",
      baseline_label: baselineLabel !== "ALL" ? baselineLabel : "",
      candidate_label: candidateLabel !== "ALL" ? candidateLabel : "",
      label_change: labelChange !== "ALL" ? labelChange : "",
      q: search,
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
    baselineRunId,
    candidateRunId,
    transition,
    gtLabel,
    baselineLabel,
    candidateLabel,
    labelChange,
    search,
    page,
    pageSize,
  ]);

  const data = comparisonQuery.data;
  const items = data?.items || [];
  const activeIndex = activeIssueId ? items.findIndex((i) => i.issue_id === activeIssueId) : -1;
  const activeItem = activeIndex >= 0 ? items[activeIndex] : null;

  const stepModal = useCallback(
    (delta: number) => {
      if (activeIndex < 0) return;
      const next = items[activeIndex + delta];
      if (next) setActiveIssueId(next.issue_id);
    },
    [activeIndex, items],
  );

  useShortcut("modal", "ArrowLeft", () => stepModal(-1), { enabled: Boolean(activeItem) });
  useShortcut("modal", "ArrowRight", () => stepModal(1), { enabled: Boolean(activeItem) });

  const runOptions = (disabledId: string) => [
    { value: "", label: bilingual(lang, "不选择（单 Run 查看）", "Not selected (single Run)") },
    ...availableRuns.map((run) => ({
      value: run.id,
      label: `${run.name || run.source_name || run.id} · ${run.baseline_prediction_count ?? 0} ${bilingual(lang, "条输出", "outputs")}`,
      disabled: Boolean(disabledId && run.id === disabledId),
    })),
  ];

  const isSingle = data?.view_mode === "single";
  const summary = data?.summary || {};
  const delta = Number(summary.accuracy_delta || 0);
  const tc = summary.transition_counts || {};

  return (
    <div className="ra-react-page ra-comparison-page" data-react-island="comparison">
      <div className="page-card ra-page-toolbar-card">
        <div className="ra-section-header">
          <div>
            <h2 className="ra-page-title">{bilingual(lang, "模型 Run 对比", "Model Run comparison")}</h2>
            <p className="ra-page-subtitle">
              {bilingual(
                lang,
                "只读对比两个不可变评测 Run 的准确率变化、P2F/F2P 迁移、混淆矩阵与逐 Case Reason 差异。",
                "Read-only comparison of two immutable Runs: accuracy delta, P2F/F2P transitions, confusion matrices, and per-case reasoning.",
              )}
            </p>
          </div>
          <div className="ra-toolbar-actions">
            <button
              type="button"
              className="button button-quiet"
              disabled={!baselineRunId && !candidateRunId}
              onClick={() => {
                setBaselineRunId(candidateRunId);
                setCandidateRunId(baselineRunId);
                setPage(1);
              }}
            >
              {bilingual(lang, "交换基线 / 新 Run", "Swap Runs")}
            </button>
            {isAdmin && baselineRunId && candidateRunId && (
              <button
                type="button"
                className="button button-quiet"
                disabled={saveCollectionMutation.isPending}
                onClick={() => saveCollectionMutation.mutate()}
              >
                {bilingual(lang, "存为评测项目", "Save as project")}
              </button>
            )}
            <button
              type="button"
              className="button button-primary"
              disabled={!hasValidSelection || comparisonQuery.isFetching}
              onClick={() => void comparisonQuery.refetch()}
            >
              {comparisonQuery.isFetching
                ? bilingual(lang, "加载中…", "Loading…")
                : bilingual(lang, "刷新对比", "Refresh")}
            </button>
          </div>
        </div>

        {saveNotice && <div className="ra-inline-notice">{saveNotice}</div>}

        <div className="ra-two-col-grid">
          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "基线 Run (Baseline)", "Baseline Run")}</span>
            <UiSelect
              id="raComparisonBaselineRun"
              value={baselineRunId}
              options={runOptions(candidateRunId)}
              ariaLabel={bilingual(lang, "基线 Run", "Baseline Run")}
              onChange={(next) => {
                setBaselineRunId(next);
                setTransition("ALL");
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "新 Run (Candidate)", "Candidate Run")}</span>
            <UiSelect
              id="raComparisonCandidateRun"
              value={candidateRunId}
              options={runOptions(baselineRunId)}
              ariaLabel={bilingual(lang, "新 Run", "Candidate Run")}
              onChange={(next) => {
                setCandidateRunId(next);
                setTransition("ALL");
                setPage(1);
              }}
            />
          </div>
        </div>
      </div>

      {/* Summary KPI Cards */}
      {data && (
        <div className={isSingle ? "ra-kpi-grid-3" : "ra-kpi-grid-6"}>
          {isSingle ? (
            <>
              <article className="page-card ra-kpi-card">
                <span className="ra-kpi-label">{bilingual(lang, "Run 准确率", "Run accuracy")}</span>
                <strong className="ra-kpi-value">
                  {pct((data.candidate_run ? summary.candidate : summary.baseline)?.accuracy)}
                </strong>
                <small className="muted">
                  {(data.candidate_run ? summary.candidate : summary.baseline)?.correct_count || 0} /{" "}
                  {(data.candidate_run ? summary.candidate : summary.baseline)?.total_count || 0}
                </small>
              </article>
              <article className="page-card ra-kpi-card">
                <span className="ra-kpi-label">{bilingual(lang, "有输出 Case", "Predicted cases")}</span>
                <strong className="ra-kpi-value">
                  {(data.candidate_run ? summary.candidate : summary.baseline)?.prediction_count || 0}
                </strong>
              </article>
              <article className="page-card ra-kpi-card">
                <span className="ra-kpi-label">{bilingual(lang, "正确 Case", "Correct cases")}</span>
                <strong className="ra-kpi-value">
                  {(data.candidate_run ? summary.candidate : summary.baseline)?.correct_count || 0}
                </strong>
              </article>
            </>
          ) : (
            <>
              <article className="page-card ra-kpi-card">
                <span className="ra-kpi-label">{bilingual(lang, "基线准确率", "Baseline Acc")}</span>
                <strong className="ra-kpi-value">{pct(summary.baseline?.accuracy)}</strong>
                <small className="muted">
                  {summary.baseline?.correct_count || 0} / {summary.baseline?.total_count || 0}
                </small>
              </article>
              <article className="page-card ra-kpi-card">
                <span className="ra-kpi-label">{bilingual(lang, "新 Run 准确率", "Candidate Acc")}</span>
                <strong className="ra-kpi-value">{pct(summary.candidate?.accuracy)}</strong>
                <small className="muted">
                  {summary.candidate?.correct_count || 0} / {summary.candidate?.total_count || 0}
                </small>
              </article>
              <article className={`page-card ra-kpi-card ${delta > 0 ? "is-positive" : delta < 0 ? "is-negative" : ""}`}>
                <span className="ra-kpi-label">{bilingual(lang, "准确率变化", "Acc delta")}</span>
                <strong className="ra-kpi-value">
                  {delta >= 0 ? "+" : ""}
                  {(delta * 100).toFixed(1)} pp
                </strong>
              </article>
              <article className="page-card ra-kpi-card is-negative">
                <span className="ra-kpi-label">{bilingual(lang, "P2F 退化", "P2F regressions")}</span>
                <strong className="ra-kpi-value">{tc.P2F || 0}</strong>
              </article>
              <article className="page-card ra-kpi-card is-positive">
                <span className="ra-kpi-label">{bilingual(lang, "F2P 改善", "F2P improvements")}</span>
                <strong className="ra-kpi-value">{tc.F2P || 0}</strong>
              </article>
              <article className="page-card ra-kpi-card">
                <span className="ra-kpi-label">{bilingual(lang, "标签变化", "Label changes")}</span>
                <strong className="ra-kpi-value">{summary.label_changed_count || 0}</strong>
                <small className="muted">
                  {summary.total_count || 0} {bilingual(lang, "条 GT Case", "GT cases")}
                </small>
              </article>
            </>
          )}
        </div>
      )}

      {/* Matrices & Prompt Snapshot Disclosures */}
      {data?.matrices && (data.matrices.baseline || data.matrices.candidate) && (
        <div className="ra-two-col-grid">
          {data.matrices.baseline && data.baseline_run && (
            <section className="page-card ra-table-card">
              <h3>
                {bilingual(lang, "基线混淆矩阵", "Baseline confusion matrix")} · {data.baseline_run.name}
              </h3>
              <div className="ra-table-scroll">
                <table className="ra-data-table comparison-matrix">
                  <thead>
                    <tr>
                      <th>GT ↓ / Model →</th>
                      {data.matrices.baseline.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                      <th>Σ</th>
                      <th>Acc</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.matrices.baseline.rows.map((row) => (
                      <tr key={row.gt_label}>
                        <th>{row.gt_label}</th>
                        {data.matrices!.baseline!.columns.map((c) => (
                          <td
                            key={c}
                            className={c === row.gt_label ? "matrix-correct" : row.cells?.[c] ? "matrix-error" : ""}
                          >
                            {row.cells?.[c] || 0}
                          </td>
                        ))}
                        <td>{row.total}</td>
                        <td>{pct(row.accuracy)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {data.matrices.candidate && data.candidate_run && (
            <section className="page-card ra-table-card">
              <h3>
                {bilingual(lang, "新 Run 混淆矩阵", "Candidate confusion matrix")} · {data.candidate_run.name}
              </h3>
              <div className="ra-table-scroll">
                <table className="ra-data-table comparison-matrix">
                  <thead>
                    <tr>
                      <th>GT ↓ / Model →</th>
                      {data.matrices.candidate.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                      <th>Σ</th>
                      <th>Acc</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.matrices.candidate.rows.map((row) => (
                      <tr key={row.gt_label}>
                        <th>{row.gt_label}</th>
                        {data.matrices!.candidate!.columns.map((c) => (
                          <td
                            key={c}
                            className={c === row.gt_label ? "matrix-correct" : row.cells?.[c] ? "matrix-error" : ""}
                          >
                            {row.cells?.[c] || 0}
                          </td>
                        ))}
                        <td>{row.total}</td>
                        <td>{pct(row.accuracy)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}

      {/* Case Filters + Table */}
      <section className="page-card ra-table-card">
        {!isSingle && (
          <div className="ra-chip-row" role="group" aria-label={bilingual(lang, "迁移状态筛选", "Transition filter")}>
            {TRANSITIONS.map((tKey) => {
              const count = tc[tKey];
              const isSelected = transition === tKey;
              return (
                <button
                  key={tKey}
                  type="button"
                  className={`button button-quiet ra-filter-pill${isSelected ? " is-active" : ""}`}
                  aria-pressed={isSelected}
                  onClick={() => {
                    setTransition(tKey);
                    setPage(1);
                  }}
                >
                  {transitionText(tKey, lang)}
                  {tKey !== "ALL" && count != null ? ` ${count}` : ""}
                </button>
              );
            })}
          </div>
        )}

        <div className="ra-filter-grid">
          <div className="ra-filter-field">
            <span className="ra-field-label">GT</span>
            <UiSelect
              id="raCompGtFilter"
              value={gtLabel}
              options={[
                { value: "ALL", label: bilingual(lang, "全部 GT", "All GT") },
                ...LABELS.map((l) => ({ value: l, label: l })),
              ]}
              ariaLabel="GT filter"
              onChange={(next) => {
                setGtLabel(next);
                setPage(1);
              }}
            />
          </div>

          {baselineRunId && (
            <div className="ra-filter-field">
              <span className="ra-field-label">{bilingual(lang, "基线输出", "Baseline output")}</span>
              <UiSelect
                id="raCompBaseLabelFilter"
                value={baselineLabel}
                options={[
                  { value: "ALL", label: bilingual(lang, "全部", "All") },
                  ...MODEL_LABELS.map((l) => ({ value: l, label: l })),
                  { value: "NONE", label: "NONE" },
                ]}
                ariaLabel={bilingual(lang, "基线输出", "Baseline output")}
                onChange={(next) => {
                  setBaselineLabel(next);
                  setPage(1);
                }}
              />
            </div>
          )}

          {candidateRunId && (
            <div className="ra-filter-field">
              <span className="ra-field-label">{bilingual(lang, "新 Run 输出", "Candidate output")}</span>
              <UiSelect
                id="raCompCandLabelFilter"
                value={candidateLabel}
                options={[
                  { value: "ALL", label: bilingual(lang, "全部", "All") },
                  ...MODEL_LABELS.map((l) => ({ value: l, label: l })),
                  { value: "NONE", label: "NONE" },
                ]}
                ariaLabel={bilingual(lang, "新 Run 输出", "Candidate output")}
                onChange={(next) => {
                  setCandidateLabel(next);
                  setPage(1);
                }}
              />
            </div>
          )}

          {!isSingle && (
            <div className="ra-filter-field">
              <span className="ra-field-label">{bilingual(lang, "输出变化", "Label change")}</span>
              <UiSelect
                id="raCompLabelChange"
                value={labelChange}
                options={[
                  { value: "ALL", label: bilingual(lang, "全部", "All") },
                  { value: "CHANGED", label: bilingual(lang, "仅变化", "Changed only") },
                  { value: "UNCHANGED", label: bilingual(lang, "未变化", "Unchanged") },
                ]}
                ariaLabel={bilingual(lang, "输出变化", "Label change")}
                onChange={(next) => {
                  setLabelChange(next);
                  setPage(1);
                }}
              />
            </div>
          )}

          <form
            className="ra-filter-field ra-search-field"
            onSubmit={(e) => {
              e.preventDefault();
              setSearch(searchInput.trim());
              setPage(1);
            }}
          >
            <span className="ra-field-label">{bilingual(lang, "搜索 Case", "Search case")}</span>
            <div className="ra-inline-input-group">
              <input
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder={bilingual(lang, "Issue ID / Reason…", "Issue ID / Reason…")}
                aria-label={bilingual(lang, "搜索 Case", "Search case")}
              />
              <button type="submit" className="button button-quiet">
                {bilingual(lang, "搜索", "Search")}
              </button>
            </div>
          </form>
        </div>

        <div className="ra-table-scroll">
          <table className="ra-data-table">
            <thead>
              <tr>
                <th>Issue</th>
                <th>GT</th>
                {!isSingle && <th>{bilingual(lang, "迁移", "Transition")}</th>}
                {data?.baseline_run && <th>{bilingual(lang, "基线输出", "Baseline")}</th>}
                {data?.candidate_run && <th>{bilingual(lang, "新 Run 输出", "Candidate")}</th>}
                <th>{bilingual(lang, "操作", "Actions")}</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="ra-table-empty">
                    {comparisonQuery.isLoading
                      ? bilingual(lang, "正在加载对比数据…", "Loading comparison…")
                      : bilingual(lang, "暂无匹配 Case", "No matching cases")}
                  </td>
                </tr>
              ) : (
                items.map((item) => (
                  <tr key={item.issue_id}>
                    <th>
                      <button
                        type="button"
                        className="text-link ra-link-btn"
                        onClick={() => {
                          setActiveIssueId(item.issue_id);
                          setModalTab("output");
                        }}
                      >
                        {item.issue_id}
                      </button>
                    </th>
                    <td>{item.gt_label || "—"}</td>
                    {!isSingle && (
                      <td>
                        <StatusChip
                          tone={
                            item.transition === "F2P" || item.transition === "P2P"
                              ? "ok"
                              : item.transition === "P2F" || item.transition === "F2F"
                                ? "fail"
                                : "neutral"
                          }
                          label={item.transition || "—"}
                        />
                      </td>
                    )}
                    {data?.baseline_run && (
                      <td>
                        <div className="ra-pred-cell">
                          <strong>{item.baseline?.model_label || "NONE"}</strong>
                          {item.baseline?.model_confidence != null && (
                            <small className="muted">{item.baseline.model_confidence.toFixed(3)}</small>
                          )}
                          <StatusChip
                            tone={item.baseline?.correct ? "ok" : "fail"}
                            label={
                              item.baseline?.correct
                                ? bilingual(lang, "匹配", "Match")
                                : bilingual(lang, "不匹配", "Mismatch")
                            }
                          />
                        </div>
                        {item.baseline?.model_reason && (
                          <p className="ra-reason-snippet" title={item.baseline.model_reason}>
                            {item.baseline.model_reason}
                          </p>
                        )}
                      </td>
                    )}
                    {data?.candidate_run && (
                      <td>
                        <div className="ra-pred-cell">
                          <strong>{item.candidate?.model_label || "NONE"}</strong>
                          {item.candidate?.model_confidence != null && (
                            <small className="muted">{item.candidate.model_confidence.toFixed(3)}</small>
                          )}
                          <StatusChip
                            tone={item.candidate?.correct ? "ok" : "fail"}
                            label={
                              item.candidate?.correct
                                ? bilingual(lang, "匹配", "Match")
                                : bilingual(lang, "不匹配", "Mismatch")
                            }
                          />
                        </div>
                        {item.candidate?.model_reason && (
                          <p className="ra-reason-snippet" title={item.candidate.model_reason}>
                            {item.candidate.model_reason}
                          </p>
                        )}
                      </td>
                    )}
                    <td>
                      <div className="ra-toolbar-actions">
                        <button
                          type="button"
                          className="button button-quiet ra-compact-btn"
                          onClick={() => {
                            setActiveIssueId(item.issue_id);
                            setModalTab("output");
                          }}
                        >
                          {bilingual(lang, "对比详情", "Compare")}
                        </button>
                        <a
                          className="button button-quiet ra-compact-btn"
                          href={withWorkbenchBase(
                            `/review?issue=${encodeURIComponent(item.issue_id)}&run=${encodeURIComponent(candidateRunId || baselineRunId)}&comparison=all`,
                          )}
                        >
                          Review
                        </a>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <Pagination
          page={data?.page || page}
          pageSize={pageSize}
          total={data?.total || 0}
          lang={lang}
          loading={comparisonQuery.isFetching}
          onPageChange={setPage}
          onPageSizeChange={(next) => {
            setPageSize(next);
            setPage(1);
          }}
        />
      </section>

      {/* Case Comparison Detail Modal with ShortcutManager ← / → */}
      <ModalDialog
        open={Boolean(activeItem)}
        title={
          activeItem
            ? `${activeItem.issue_id} · ${bilingual(lang, isSingle ? "Case 详情" : "Case 对比", isSingle ? "Case details" : "Case comparison")}`
            : ""
        }
        lang={lang}
        wide
        onClose={() => setActiveIssueId(null)}
        footer={
          <div className="ra-modal-nav-footer">
            <button
              type="button"
              className="button button-quiet"
              disabled={activeIndex <= 0}
              onClick={() => stepModal(-1)}
            >
              ← {bilingual(lang, "上一个", "Prev")}
            </button>
            <button
              type="button"
              className="button button-quiet"
              disabled={activeIndex < 0 || activeIndex >= items.length - 1}
              onClick={() => stepModal(1)}
            >
              {bilingual(lang, "下一个", "Next")} →
            </button>
            <button
              type="button"
              className="button button-primary"
              onClick={() => setActiveIssueId(null)}
            >
              {bilingual(lang, "关闭", "Close")}
            </button>
          </div>
        }
      >
        {activeItem && (
          <div className="ra-comp-modal-content">
            <div className="ra-chip-row">
              <StatusChip tone="neutral" label={`GT: ${activeItem.gt_label || "—"}`} />
              {!isSingle && (
                <StatusChip
                  tone={activeItem.transition === "F2P" || activeItem.transition === "P2P" ? "ok" : "fail"}
                  label={transitionText(activeItem.transition, lang)}
                />
              )}
              <button
                type="button"
                className={`button button-quiet ra-filter-pill${modalTab === "output" ? " is-active" : ""}`}
                onClick={() => setModalTab("output")}
              >
                {bilingual(lang, "输出与 Reason", "Outputs & reason")}
              </button>
              <button
                type="button"
                className={`button button-quiet ra-filter-pill${modalTab === "inputs" ? " is-active" : ""}`}
                onClick={() => setModalTab("inputs")}
              >
                {bilingual(lang, "输入快照", "Inputs snapshot")}
              </button>
            </div>

            {modalTab === "output" ? (
              <>
                <div className="ra-comp-modal-thumb">
                  <img
                    src={withWorkbenchBase(`/api/case-thumbnails/${encodeURIComponent(activeItem.issue_id)}`)}
                    alt={`${activeItem.issue_id} BEV`}
                  />
                </div>
                <div className="ra-two-col-grid">
                  {data?.baseline_run && (
                    <div className="ra-comp-side-card">
                      <h4>{bilingual(lang, "基线 Run", "Baseline")}: {data.baseline_run.name}</h4>
                      <div className="ra-chip-row">
                        <strong>{activeItem.baseline?.model_label || "NONE"}</strong>
                        <span className="muted">
                          {activeItem.baseline?.model_confidence != null
                            ? activeItem.baseline.model_confidence.toFixed(3)
                            : "—"}
                        </span>
                      </div>
                      <pre className="ra-reason-pre">
                        {activeItem.baseline?.model_reason ||
                          bilingual(lang, "未保存 Reason", "Reason not saved")}
                      </pre>
                    </div>
                  )}
                  {data?.candidate_run && (
                    <div className="ra-comp-side-card">
                      <h4>{bilingual(lang, "新 Run", "Candidate")}: {data.candidate_run.name}</h4>
                      <div className="ra-chip-row">
                        <strong>{activeItem.candidate?.model_label || "NONE"}</strong>
                        <span className="muted">
                          {activeItem.candidate?.model_confidence != null
                            ? activeItem.candidate.model_confidence.toFixed(3)
                            : "—"}
                        </span>
                      </div>
                      <pre className="ra-reason-pre">
                        {activeItem.candidate?.model_reason ||
                          bilingual(lang, "未保存 Reason", "Reason not saved")}
                      </pre>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="ra-inputs-preview">
                {caseInputsQuery.isLoading ? (
                  <p className="muted">{bilingual(lang, "正在加载输入快照…", "Loading input snapshot…")}</p>
                ) : caseInputsQuery.isError ? (
                  <p className="muted">{bilingual(lang, "无法读取该 Case 输入快照", "Input snapshot unavailable")}</p>
                ) : (
                  <pre className="ra-reason-pre">
                    {JSON.stringify(caseInputsQuery.data || {}, null, 2)}
                  </pre>
                )}
              </div>
            )}
          </div>
        )}
      </ModalDialog>
    </div>
  );
};
