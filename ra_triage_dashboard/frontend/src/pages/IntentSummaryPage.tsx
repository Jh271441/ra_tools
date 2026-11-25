import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  formatCstTime,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import {
  CASE_PAGE_SIZES,
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

interface IntentDatasetItem {
  id: string;
  display_name: string;
  available: boolean;
  case_count?: number;
}

interface IntentExperimentRef {
  id: string;
  dataset_id: string;
  name: string;
  label_scope?: string;
}

interface IntentCommentRef {
  id: number;
  author: string;
  body?: string;
  snippet?: string;
  created_at?: string;
  case_id?: string;
  dataset_id?: string;
}

interface IntentSummaryRow {
  dataset_id?: string;
  case_id: string;
  username: string;
  revision_id: number;
  completion?: {
    complete?: boolean;
    reason?: string;
  };
  frame_counts?: {
    routing?: Record<string, number>;
    lane_change?: Record<string, number>;
  };
  comments?: IntentCommentRef[];
  comment_count?: number;
  updated_at?: string;
}

interface IntentSummaryResponse {
  dataset_ids?: string[];
  axis?: string;
  label_scope?: string;
  case_count: number;
  annotated_cases: number;
  complete_records: number;
  agreement?: {
    comparable_cases?: number;
    matching_cases?: number;
  };
  frame_distributions?: {
    routing?: Record<string, number>;
    lane_change?: Record<string, number>;
  };
  comment_query?: string;
  comment_hits?: IntentCommentRef[];
  blind_active?: boolean;
  answers_revealed?: boolean;
  experiments?: IntentExperimentRef[];
  owners?: string[];
  items?: IntentSummaryRow[];
  total: number;
  page: number;
  page_size: number;
}

interface LegacyWindow {
  state?: {
    intentLabeling?: {
      datasets?: IntentDatasetItem[];
      summaryDatasetIds?: string[];
      summaryDatasetId?: string;
      summaryExperimentId?: string;
      summaryAssignees?: string[];
      summaryAxis?: string;
      summaryPage?: number;
      summaryPageSize?: number;
      summaryCommentQuery?: string;
      summaryReveal?: boolean;
      datasetId?: string;
    };
  };
  renderIntentTopbarDatasetPicker?: (selectedIds?: string[] | null) => void;
  showToast?: (msg: string, isError?: boolean) => void;
  acknowledgeLocalChange?: (payload: unknown) => void;
}

function getLegacyWindow(): LegacyWindow {
  return window as unknown as LegacyWindow;
}

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

function chipClass(value: string): string {
  const map: Record<string, string> = {
    straight: "is-straight",
    left_turn: "is-left",
    right_turn: "is-right",
    u_turn: "is-uturn",
    parking: "is-parking",
    no_lane_change: "is-no-lane",
    left_lane_change: "is-left-lane",
    right_lane_change: "is-right-lane",
    lane_change: "is-legacy-lane",
  };
  return map[value] || "";
}

function labelForValue(
  value: string,
  table: Record<string, [string, string]>,
  lang: UiLanguage,
): string {
  const pair = table[value];
  return pair ? bilingual(lang, pair[0], pair[1]) : value;
}

function parseRouteParams() {
  const params = new URLSearchParams(window.location.search);
  const datasets = params.getAll("dataset").filter(Boolean);
  const owners = params
    .getAll("owner")
    .filter((v) => /^[A-Za-z0-9._@-]{1,128}$/.test(v));
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawSize = Number.parseInt(params.get("page_size") || "20", 10);
  const rawAxis = params.get("axis") || "all";
  return {
    datasets,
    experimentId: params.get("experiment") || "",
    owners,
    page: Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1,
    pageSize: (CASE_PAGE_SIZES as readonly number[]).includes(rawSize)
      ? rawSize
      : DEFAULT_CASE_PAGE_SIZE,
    axis: ["routing", "lane_change"].includes(rawAxis) ? rawAxis : "all",
    commentQuery: (params.get("q") || "").trim().slice(0, 80),
  };
}

function rowSelectionKey(row: IntentSummaryRow, fallbackDataset: string): string {
  return `${row.dataset_id || fallbackDataset}::${row.case_id}::${row.username}::${row.revision_id}`;
}

export interface IntentSummaryPageProps {
  active: boolean;
  lang: UiLanguage;
  username: string;
  isAdmin: boolean;
}

export const IntentSummaryPage: React.FC<IntentSummaryPageProps> = ({
  active,
  lang,
  username,
  isAdmin,
}) => {
  const queryClient = useQueryClient();
  const initial = useMemo(() => parseRouteParams(), []);

  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>(initial.datasets);
  const [experimentId, setExperimentId] = useState<string>(initial.experimentId);
  const [assignees, setAssignees] = useState<string[]>(initial.owners);
  const [axis, setAxis] = useState<string>(initial.axis);
  const [commentInput, setCommentInput] = useState<string>(initial.commentQuery);
  const [commentQuery, setCommentQuery] = useState<string>(initial.commentQuery);
  const [page, setPage] = useState<number>(initial.page);
  const [pageSize, setPageSize] = useState<number>(initial.pageSize);
  const [revealAnswers, setRevealAnswers] = useState<boolean>(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<Set<string>>(() => new Set());
  const [deleting, setDeleting] = useState<boolean>(false);
  const [confirmDelete, setConfirmDelete] = useState<
    | { kind: "single"; row: IntentSummaryRow; datasetId: string }
    | { kind: "bulk"; rows: Array<{ dataset_id: string; case_id: string; username: string; expected_revision_id: number }> }
    | null
  >(null);

  const confirmDialogRef = useRef<HTMLDialogElement | null>(null);
  const commentTimerRef = useRef<number | null>(null);

  // Datasets catalog
  const datasetsQuery = useQuery<{ items?: IntentDatasetItem[] }>({
    queryKey: ["intent-datasets"],
    queryFn: ({ signal }) => apiRequest("/api/intent-datasets", { signal }),
    enabled: active,
    staleTime: 60_000,
  });

  const availableDatasets = useMemo(
    () => (datasetsQuery.data?.items || []).filter((d) => d.available),
    [datasetsQuery.data],
  );

  // Resolve effective datasets & sync classic topbar picker
  const effectiveDatasetIds = useMemo(() => {
    const valid = selectedDatasetIds.filter((id) =>
      availableDatasets.some((d) => d.id === id),
    );
    if (valid.length) return valid;
    const legacyIds = getLegacyWindow().state?.intentLabeling?.summaryDatasetIds || [];
    const validLegacy = legacyIds.filter((id) =>
      availableDatasets.some((d) => d.id === id),
    );
    if (validLegacy.length) return validLegacy;
    return availableDatasets[0] ? [availableDatasets[0].id] : [];
  }, [selectedDatasetIds, availableDatasets]);

  useEffect(() => {
    if (!active || !availableDatasets.length) return;
    const legacy = getLegacyWindow();
    if (legacy.state?.intentLabeling) {
      legacy.state.intentLabeling.datasets = datasetsQuery.data?.items || [];
      legacy.state.intentLabeling.summaryDatasetIds = effectiveDatasetIds;
      legacy.state.intentLabeling.summaryDatasetId = effectiveDatasetIds[0] || "";
    }
    legacy.renderIntentTopbarDatasetPicker?.(effectiveDatasetIds);
  }, [active, availableDatasets, datasetsQuery.data, effectiveDatasetIds]);

  // Listen to topbar intent dataset changes from classic shell
  useEffect(() => {
    if (!active) return;
    const handleSync = () => {
      const legacyIds = getLegacyWindow().state?.intentLabeling?.summaryDatasetIds;
      if (Array.isArray(legacyIds) && legacyIds.length) {
        setSelectedDatasetIds((prev) => {
          if (prev.join(",") === legacyIds.join(",")) return prev;
          setExperimentId("");
          setAssignees([]);
          setPage(1);
          setSelectedRowKeys(new Set());
          return [...legacyIds];
        });
      }
    };
    window.addEventListener("ra:workbench-sync", handleSync);
    return () => window.removeEventListener("ra:workbench-sync", handleSync);
  }, [active]);

  // Persist URL
  const syncUrl = useCallback(
    (overrides?: {
      datasets?: string[];
      experimentId?: string;
      assignees?: string[];
      axis?: string;
      page?: number;
      pageSize?: number;
      commentQuery?: string;
    }) => {
      if (!active) return;
      const ds = overrides?.datasets ?? effectiveDatasetIds;
      if (!ds.length) return;
      const exp = overrides?.experimentId ?? experimentId;
      const own = overrides?.assignees ?? assignees;
      const ax = overrides?.axis ?? axis;
      const p = overrides?.page ?? page;
      const ps = overrides?.pageSize ?? pageSize;
      const q = overrides?.commentQuery ?? commentQuery;
      const params = new URLSearchParams();
      ds.forEach((id) => params.append("dataset", id));
      if (exp) params.set("experiment", exp);
      own.forEach((v) => params.append("owner", v));
      if (p > 1) params.set("page", String(p));
      if (ax && ax !== "all") params.set("axis", ax);
      if (ps !== DEFAULT_CASE_PAGE_SIZE) params.set("page_size", String(ps));
      if (q) params.set("q", q);
      const nextUrl = `${withWorkbenchBase("/intent-summary")}?${params.toString()}`;
      if (`${window.location.pathname}${window.location.search}` !== nextUrl) {
        window.history.replaceState(
          { page: "intent-summary", datasetId: ds[0], datasetIds: ds },
          "",
          nextUrl,
        );
      }
    },
    [active, effectiveDatasetIds, experimentId, assignees, axis, page, pageSize, commentQuery],
  );

  // Summary data query
  const summaryQuery = useQuery<IntentSummaryResponse>({
    queryKey: [
      "intent-summary",
      effectiveDatasetIds.join(","),
      experimentId,
      assignees.join(","),
      axis,
      page,
      pageSize,
      commentQuery,
      revealAnswers,
    ],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams();
      effectiveDatasetIds.forEach((id) => params.append("dataset_id", id));
      if (experimentId) params.set("experiment_id", experimentId);
      assignees.forEach((v) => params.append("assignee", v));
      if (revealAnswers) params.set("reveal_answers", "true");
      params.set("axis", axis || "all");
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (commentQuery) params.set("q", commentQuery);
      return apiRequest<IntentSummaryResponse>(`/api/intent-summary?${params.toString()}`, {
        signal,
      });
    },
    enabled: active && effectiveDatasetIds.length > 0,
    staleTime: 10_000,
  });

  const payload = summaryQuery.data || null;

  useEffect(() => {
    if (active && payload) {
      syncUrl();
    }
  }, [active, payload, syncUrl]);

  // Clear selection when rows change
  useEffect(() => {
    setSelectedRowKeys(new Set());
  }, [effectiveDatasetIds.join(","), experimentId, assignees.join(","), axis, page, pageSize, commentQuery]);

  // Native <dialog> open/close for delete confirm
  useEffect(() => {
    const dlg = confirmDialogRef.current;
    if (!dlg) return;
    if (confirmDelete) {
      if (!dlg.open) {
        try {
          dlg.showModal();
        } catch {
          dlg.setAttribute("open", "");
        }
      }
    } else if (dlg.open) {
      dlg.close();
    }
  }, [confirmDelete]);

  // Debounced comment search
  const handleCommentChange = (val: string) => {
    setCommentInput(val);
    if (commentTimerRef.current) window.clearTimeout(commentTimerRef.current);
    commentTimerRef.current = window.setTimeout(() => {
      const trimmed = val.trim().slice(0, 80);
      setCommentQuery(trimmed);
      setPage(1);
      syncUrl({ commentQuery: trimmed, page: 1 });
    }, 350);
  };

  useEffect(() => {
    return () => {
      if (commentTimerRef.current) window.clearTimeout(commentTimerRef.current);
    };
  }, []);

  const labelingHref = (datasetId: string, caseId: string, extra?: Record<string, string | number>) => {
    const ordered = [datasetId, ...effectiveDatasetIds.filter((id) => id !== datasetId)];
    const params = new URLSearchParams();
    ordered.forEach((id) => params.append("dataset", id));
    params.set("case", caseId);
    if (extra) {
      Object.entries(extra).forEach(([k, v]) => params.set(k, String(v)));
    }
    return `${withWorkbenchBase("/intent-labeling")}?${params.toString()}`;
  };

  const handleExport = (view: "compact" | "expanded") => {
    if (!isAdmin || !effectiveDatasetIds.length) return;
    let targetDatasets = [...effectiveDatasetIds];
    const params = new URLSearchParams({ view, include_incomplete: "true" });
    if (experimentId) {
      const exp = (payload?.experiments || []).find((e) => e.id === experimentId);
      if (exp?.dataset_id) targetDatasets = [exp.dataset_id];
      params.set("experiment_id", experimentId);
    }
    targetDatasets.forEach((dsId) => {
      const link = document.createElement("a");
      link.href = withWorkbenchBase(
        `/api/intent-datasets/${encodeURIComponent(dsId)}/export?${params.toString()}`,
      );
      link.click();
    });
  };

  const executeDelete = async () => {
    if (!confirmDelete || !isAdmin || deleting) return;
    setDeleting(true);
    try {
      if (confirmDelete.kind === "single") {
        const { row, datasetId } = confirmDelete;
        const result = await apiRequest(
          `/api/intent-datasets/${encodeURIComponent(datasetId)}/cases/${encodeURIComponent(
            row.case_id,
          )}/labels/${encodeURIComponent(row.username)}?expected_revision_id=${row.revision_id}`,
          { method: "DELETE" },
        );
        getLegacyWindow().acknowledgeLocalChange?.(result);
        getLegacyWindow().showToast?.(
          bilingual(
            lang,
            "标注已删除，历史修订与审计记录已保留。",
            "Label deleted; revision history and audit records retained.",
          ),
          false,
        );
      } else {
        const result = await apiRequest<{ count?: number }>("/api/intent-labels/bulk-delete", {
          method: "POST",
          body: JSON.stringify({ items: confirmDelete.rows }),
        });
        getLegacyWindow().acknowledgeLocalChange?.(result);
        const deletedCount = Number(result?.count) || confirmDelete.rows.length;
        getLegacyWindow().showToast?.(
          bilingual(
            lang,
            `已删除 ${deletedCount} 条标注，历史修订与审计记录已保留。`,
            `Deleted ${deletedCount} labels; revision history and audit records retained.`,
          ),
          false,
        );
      }
      setConfirmDelete(null);
      setSelectedRowKeys(new Set());
      void queryClient.invalidateQueries({ queryKey: ["intent-summary"] });
    } catch (err) {
      getLegacyWindow().showToast?.((err as Error)?.message || "Delete failed", true);
    } finally {
      setDeleting(false);
    }
  };

  const labelScope = payload?.label_scope || "all";
  const effectiveAxis = labelScope !== "all" ? labelScope : payload?.axis || axis || "all";
  const showRouting = labelScope !== "lane_change" && effectiveAxis !== "lane_change";
  const showLaneChange = labelScope !== "routing" && effectiveAxis !== "routing";
  const columnCount = 5 + Number(showRouting) + Number(showLaneChange) + Number(isAdmin);

  const experimentOptions: MultiSelectOption[] = useMemo(
    () =>
      (payload?.experiments || []).map((e) => ({
        value: e.id,
        label: effectiveDatasetIds.length > 1 ? `${e.dataset_id} · ${e.name}` : e.name,
      })),
    [payload?.experiments, effectiveDatasetIds.length],
  );

  const assigneeOptions: MultiSelectOption[] = useMemo(
    () =>
      (payload?.owners || []).map((owner) => ({
        value: owner,
        label: owner === username ? `${owner}${bilingual(lang, "（我）", " (me)")}` : owner,
      })),
    [payload?.owners, username, lang],
  );

  const axisOptions: UiSelectOption[] = useMemo(() => {
    const allOpts: UiSelectOption[] = [
      { value: "all", label: bilingual(lang, "Routing + 变道意图", "Routing + lane-change") },
      { value: "routing", label: bilingual(lang, "仅 Routing", "Routing only") },
      { value: "lane_change", label: bilingual(lang, "仅变道意图", "Lane-change only") },
    ];
    return allOpts.filter((opt) => labelScope === "all" || opt.value === labelScope);
  }, [lang, labelScope]);

  const rows = payload?.items || [];
  const fallbackDataset = effectiveDatasetIds[0] || "";
  const allRowsSelected = rows.length > 0 && rows.every((r) => selectedRowKeys.has(rowSelectionKey(r, fallbackDataset)));

  const renderDistribution = (
    title: string,
    counts: Record<string, number> | undefined,
    table: Record<string, [string, string]>,
  ) => {
    const entries = Object.entries(counts || {})
      .filter(([, c]) => Number(c) > 0)
      .sort((a, b) => Number(b[1]) - Number(a[1]));
    const total = entries.reduce((sum, [, c]) => sum + Number(c), 0);
    if (!entries.length) return null;
    return (
      <article className="intent-summary-distribution">
        <header>
          <strong>{title}</strong>
          <small>
            {bilingual(lang, `${total} 个已标注帧`, `${total} labeled frames`)}
          </small>
        </header>
        <div className="intent-summary-distribution-track">
          {entries.map(([val, c]) => (
            <i
              key={val}
              className={chipClass(val)}
              style={{ width: `${(Number(c) * 100) / total}%` }}
              title={`${labelForValue(val, table, lang)} ${Number(c)} ${bilingual(lang, "帧", "frames")}`}
            />
          ))}
        </div>
        <div className="intent-summary-distribution-legend">
          {entries.map(([val, c]) => (
            <span key={val}>
              <b className={chipClass(val)} />
              {labelForValue(val, table, lang)} {Number(c)}
              {bilingual(lang, "帧", "f")} · {Math.round((Number(c) * 100) / total)}%
            </span>
          ))}
        </div>
      </article>
    );
  };

  const renderFrameChips = (
    counts: Record<string, number> | undefined,
    table: Record<string, [string, string]>,
  ) => {
    const entries = Object.entries(counts || {})
      .filter(([, c]) => Number(c) > 0)
      .sort((a, b) => Number(b[1]) - Number(a[1]));
    if (!entries.length) return <div className="intent-summary-result is-empty">—</div>;
    return (
      <div className="intent-summary-result">
        {entries.map(([val, c]) => (
          <b key={val} className={`intent-summary-chip ${chipClass(val)}`}>
            {labelForValue(val, table, lang)} {Number(c)}
            {bilingual(lang, "帧", "f")}
          </b>
        ))}
      </div>
    );
  };

  const routingDist = showRouting
    ? renderDistribution(
        bilingual(lang, "Routing 标签比例", "Routing label share"),
        payload?.frame_distributions?.routing,
        ROUTING_LABELS,
      )
    : null;
  const laneDist = showLaneChange
    ? renderDistribution(
        bilingual(lang, "变道意图标签比例", "Lane-change label share"),
        payload?.frame_distributions?.lane_change,
        LANE_LABELS,
      )
    : null;
  const hasDistributions = Boolean(routingDist || laneDist);

  const pageCount = Math.max(
    1,
    Math.ceil(Number(payload?.total || 0) / Number(payload?.page_size || pageSize || 20)),
  );
  const currentPage = payload?.page || page;

  return (
    <div className="ra-intent-summary-root" data-react-island="intent-summary">
      <section className="intent-summary-filters page-card">
        <div className="intent-command-field">
          <span>{bilingual(lang, "实验分配", "Experiment")}</span>
          <MultiSelect
            id="intentSummaryExperimentPicker"
            options={experimentOptions}
            values={experimentId ? [experimentId] : []}
            ariaLabel={bilingual(lang, "实验分配", "Experiment")}
            placeholder={bilingual(lang, "全部实验", "All experiments")}
            allLabel={bilingual(lang, "全部实验", "All experiments")}
            lang={lang}
            showOnlyThis
            onChange={(values) => {
              const nextExp = values[values.length - 1] || "";
              setExperimentId(nextExp);
              const exp = (payload?.experiments || []).find((e) => e.id === nextExp);
              const nextAxis =
                exp?.label_scope && exp.label_scope !== "all" ? exp.label_scope : axis;
              if (nextAxis !== axis) setAxis(nextAxis);
              setAssignees([]);
              setPage(1);
              syncUrl({ experimentId: nextExp, assignees: [], axis: nextAxis, page: 1 });
            }}
          />
        </div>

        <div className="intent-command-field">
          <span>{bilingual(lang, "任务负责人", "Assignee")}</span>
          <MultiSelect
            id="intentSummaryAssignees"
            options={assigneeOptions}
            values={assignees}
            ariaLabel={bilingual(lang, "任务负责人", "Assignee")}
            placeholder={bilingual(lang, "全部负责人", "All assignees")}
            allLabel={bilingual(lang, "全部负责人", "All assignees")}
            lang={lang}
            showOnlyThis
            onChange={(values) => {
              setAssignees(values);
              setPage(1);
              syncUrl({ assignees: values, page: 1 });
            }}
          />
        </div>

        <div className="intent-command-field">
          <span>{bilingual(lang, "结果维度", "Dimension")}</span>
          <UiSelect
            id="intentSummaryAxisPicker"
            value={effectiveAxis}
            options={axisOptions}
            ariaLabel={bilingual(lang, "结果维度", "Dimension")}
            onChange={(nextAxis) => {
              setAxis(nextAxis || "all");
              setPage(1);
              syncUrl({ axis: nextAxis || "all", page: 1 });
            }}
          />
        </div>

        <label className="intent-command-field intent-summary-comment-field">
          <span>{bilingual(lang, "搜索评论", "Search comments")}</span>
          <input
            id="intentSummaryCommentQuery"
            maxLength={80}
            autoComplete="off"
            value={commentInput}
            placeholder={bilingual(lang, "按评论内容查找 Case", "Find Case by comment text")}
            onChange={(e) => handleCommentChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                if (commentTimerRef.current) window.clearTimeout(commentTimerRef.current);
                const trimmed = commentInput.trim().slice(0, 80);
                setCommentQuery(trimmed);
                setPage(1);
                syncUrl({ commentQuery: trimmed, page: 1 });
              }
            }}
          />
        </label>

        <button
          className="button button-quiet"
          id="intentSummaryRefresh"
          type="button"
          onClick={() => void queryClient.invalidateQueries({ queryKey: ["intent-summary"] })}
        >
          {bilingual(lang, "刷新汇总", "Refresh")}
        </button>

        {isAdmin && payload?.blind_active ? (
          <button
            className="button button-quiet"
            id="intentSummaryReveal"
            type="button"
            onClick={() => setRevealAnswers((v) => !v)}
          >
            {payload.answers_revealed
              ? bilingual(lang, "恢复盲态", "Restore blind mode")
              : bilingual(lang, "管理员解盲", "Admin reveal")}
          </button>
        ) : null}
      </section>

      <section className="intent-summary-metrics" id="intentSummaryMetrics">
        <article className="intent-summary-metric">
          <small>{bilingual(lang, "范围 Case", "Cases in scope")}</small>
          <strong>{payload ? payload.case_count : "—"}</strong>
        </article>
        <article className="intent-summary-metric">
          <small>{bilingual(lang, "已标注 Case", "Annotated Cases")}</small>
          <strong>{payload ? payload.annotated_cases : "—"}</strong>
        </article>
        <article className="intent-summary-metric">
          <small>{bilingual(lang, "完整标注记录", "Complete records")}</small>
          <strong>{payload ? payload.complete_records : "—"}</strong>
        </article>
        <article className="intent-summary-metric">
          <small>{bilingual(lang, "多人一致性", "Multi-rater agreement")}</small>
          <strong>
            {payload?.agreement?.comparable_cases
              ? `${payload.agreement.matching_cases} / ${payload.agreement.comparable_cases}`
              : "—"}
          </strong>
        </article>
      </section>

      {hasDistributions ? (
        <section
          className={`intent-summary-distributions${
            Number(showRouting) + Number(showLaneChange) === 1 ? " is-single-axis" : ""
          }`}
          id="intentSummaryDistributions"
        >
          {routingDist}
          {laneDist}
        </section>
      ) : null}

      {payload?.comment_query?.trim() ? (
        <section className="page-card intent-summary-comments-card" id="intentSummaryCommentHits">
          <header>
            <h2>{bilingual(lang, "评论搜索", "Comment search")}</h2>
            <p>
              {bilingual(
                lang,
                `${(payload.comment_hits || []).length} 条`,
                `${(payload.comment_hits || []).length} hits`,
              )}
              {payload.blind_active && !payload.answers_revealed ? (
                <small>
                  {" "}
                  {bilingual(lang, "盲标中仅搜索自己的评论。", "Blind mode searches own comments only.")}
                </small>
              ) : null}
            </p>
          </header>
          <div className="intent-summary-comment-list">
            {(payload.comment_hits || []).length ? (
              (payload.comment_hits || []).map((item) => {
                const ds = item.dataset_id || fallbackDataset;
                return (
                  <article className="intent-summary-comment-hit" key={`${item.id}-${item.case_id}`}>
                    <a
                      className="intent-summary-case-link"
                      href={labelingHref(ds, item.case_id || "", { comments: 1, comment: item.id })}
                    >
                      {item.case_id}
                    </a>
                    <strong>
                      {item.author}
                      {item.author === username ? bilingual(lang, "（我）", " (me)") : ""}
                    </strong>
                    <p>{item.snippet || item.body || ""}</p>
                    <time>{formatCstTime(item.created_at, lang)}</time>
                  </article>
                );
              })
            ) : (
              <p className="intent-summary-comment-empty">
                {bilingual(
                  lang,
                  `没有匹配“${payload.comment_query}”的评论。`,
                  `No comments matching "${payload.comment_query}".`,
                )}
              </p>
            )}
          </div>
        </section>
      ) : null}

      <section className="page-card intent-summary-table-card">
        <header>
          <div>
            <h2>{bilingual(lang, "标注汇总", "Label summary")}</h2>
            <p id="intentSummarySafety">
              {payload?.blind_active && !payload?.answers_revealed
                ? bilingual(
                    lang,
                    "进行中的盲标实验仅显示自己的答案。",
                    "Active blind experiments show only your own answers.",
                  )
                : bilingual(
                    lang,
                    "汇总当前标注头；不会加载 Camera / BEV 图片。",
                    "Summarizes current label heads without loading Camera / BEV images.",
                  )}
            </p>
          </div>
          {isAdmin ? (
            <div className="intent-summary-export-actions">
              <button
                className="button button-danger"
                id="intentSummaryBulkDelete"
                type="button"
                disabled={selectedRowKeys.size === 0 || deleting}
                onClick={() => {
                  const targets = rows
                    .filter((r) => selectedRowKeys.has(rowSelectionKey(r, fallbackDataset)))
                    .map((r) => ({
                      dataset_id: r.dataset_id || fallbackDataset,
                      case_id: r.case_id,
                      username: r.username,
                      expected_revision_id: Number(r.revision_id),
                    }))
                    .filter((t) => t.dataset_id && t.case_id && t.username && t.expected_revision_id);
                  if (targets.length) setConfirmDelete({ kind: "bulk", rows: targets });
                }}
              >
                {selectedRowKeys.size
                  ? bilingual(
                      lang,
                      `批量删除 (${selectedRowKeys.size})`,
                      `Bulk delete (${selectedRowKeys.size})`,
                    )
                  : bilingual(lang, "批量删除", "Bulk delete")}
              </button>
              <button
                className="button button-quiet"
                id="intentExportCompact"
                type="button"
                onClick={() => handleExport("compact")}
              >
                {bilingual(lang, "导出 Case JSONL", "Export Case JSONL")}
              </button>
              <button
                className="button button-quiet"
                id="intentExportExpanded"
                type="button"
                onClick={() => handleExport("expanded")}
              >
                {bilingual(lang, "导出帧级 JSONL", "Export frame JSONL")}
              </button>
            </div>
          ) : null}
        </header>

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Issue / Case</th>
                <th>{bilingual(lang, "标注人", "Annotator")}</th>
                <th>{bilingual(lang, "完成状态", "Completion")}</th>
                {showRouting ? (
                  <th className="intent-summary-routing-column">
                    {bilingual(lang, "Routing 帧分布", "Routing frames")}
                  </th>
                ) : null}
                {showLaneChange ? (
                  <th className="intent-summary-lane-column">
                    {bilingual(lang, "变道意图帧分布", "Lane-change frames")}
                  </th>
                ) : null}
                <th className="intent-summary-comments-column">
                  {bilingual(lang, "评论", "Comments")}
                </th>
                <th>{bilingual(lang, "更新时间", "Updated")}</th>
                {isAdmin ? (
                  <th className="intent-summary-admin-column intent-summary-actions-column">
                    <label className="intent-summary-select-all">
                      <input
                        id="intentSummarySelectPage"
                        type="checkbox"
                        checked={allRowsSelected}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedRowKeys(
                              new Set(rows.map((r) => rowSelectionKey(r, fallbackDataset))),
                            );
                          } else {
                            setSelectedRowKeys(new Set());
                          }
                        }}
                      />{" "}
                      {bilingual(lang, "全选本页", "Select page")}
                    </label>
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody id="intentSummaryRows">
              {summaryQuery.isLoading ? (
                <tr>
                  <td colSpan={columnCount}>
                    {bilingual(lang, "正在加载标注汇总…", "Loading intent summary…")}
                  </td>
                </tr>
              ) : summaryQuery.isError ? (
                <tr>
                  <td colSpan={columnCount}>
                    {(summaryQuery.error as Error)?.message ||
                      bilingual(lang, "加载失败", "Failed to load")}
                  </td>
                </tr>
              ) : !rows.length ? (
                <tr>
                  <td colSpan={columnCount}>
                    {bilingual(
                      lang,
                      "当前筛选下没有已标注结果。",
                      "No annotated results match the current filters.",
                    )}
                  </td>
                </tr>
              ) : (
                rows.map((item) => {
                  const ds = item.dataset_id || fallbackDataset;
                  const key = rowSelectionKey(item, fallbackDataset);
                  const completion = item.completion || {};
                  const itemComments = item.comments || [];
                  return (
                    <tr key={key}>
                      <td>
                        <a className="intent-summary-case-link" href={labelingHref(ds, item.case_id)}>
                          {item.case_id}
                        </a>
                        {(payload?.dataset_ids || []).length > 1 ? <small>{ds}</small> : null}
                      </td>
                      <td>
                        {item.username}
                        {item.username === username ? bilingual(lang, "（我）", " (me)") : ""}
                      </td>
                      <td>
                        <div
                          className={`intent-summary-completion ${
                            completion.complete ? "is-complete" : "is-partial"
                          }`}
                        >
                          <b>
                            {completion.complete
                              ? bilingual(lang, "完整", "Complete")
                              : bilingual(lang, "部分", "Partial")}
                          </b>
                          <small>
                            {completion.reason ||
                              bilingual(lang, "覆盖情况未知", "Coverage unknown")}
                          </small>
                        </div>
                      </td>
                      {showRouting ? (
                        <td className="intent-summary-routing-column">
                          {renderFrameChips(item.frame_counts?.routing, ROUTING_LABELS)}
                        </td>
                      ) : null}
                      {showLaneChange ? (
                        <td className="intent-summary-lane-column">
                          {renderFrameChips(item.frame_counts?.lane_change, LANE_LABELS)}
                        </td>
                      ) : null}
                      <td className="intent-summary-comments-column">
                        {itemComments.length ? (
                          <div className="intent-summary-row-comments">
                            {itemComments.map((c) => (
                              <a
                                key={c.id}
                                href={labelingHref(ds, item.case_id, { comments: 1, comment: c.id })}
                                title={c.body || bilingual(lang, "此评论已删除", "Comment deleted")}
                              >
                                <b>{c.author}：</b>
                                {c.body || bilingual(lang, "此评论已删除", "Comment deleted")}
                              </a>
                            ))}
                            {Number(item.comment_count || 0) > itemComments.length ? (
                              <small>
                                {bilingual(
                                  lang,
                                  `共 ${Number(item.comment_count)} 条`,
                                  `${Number(item.comment_count)} total`,
                                )}
                              </small>
                            ) : null}
                          </div>
                        ) : (
                          <span className="intent-summary-no-comment">—</span>
                        )}
                      </td>
                      <td>{formatCstTime(item.updated_at, lang)}</td>
                      {isAdmin ? (
                        <td className="intent-summary-admin-column">
                          <div className="intent-summary-row-actions">
                            <label className="intent-summary-select">
                              <input
                                type="checkbox"
                                checked={selectedRowKeys.has(key)}
                                aria-label={bilingual(
                                  lang,
                                  `选择 ${item.case_id} ${item.username} 的标注`,
                                  `Select ${item.case_id} ${item.username}`,
                                )}
                                onChange={(e) => {
                                  setSelectedRowKeys((prev) => {
                                    const next = new Set(prev);
                                    if (e.target.checked) next.add(key);
                                    else next.delete(key);
                                    return next;
                                  });
                                }}
                              />
                            </label>
                            <button
                              className="button button-quiet intent-summary-delete"
                              type="button"
                              disabled={deleting}
                              onClick={() =>
                                setConfirmDelete({ kind: "single", row: item, datasetId: ds })
                              }
                            >
                              {bilingual(lang, "删除标注", "Delete")}
                            </button>
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <Pagination
          page={currentPage}
          pageSize={pageSize}
          total={payload?.total || 0}
          lang={lang}
          loading={summaryQuery.isFetching}
          className="case-pagination gallery-pagination intent-summary-pagination"
          showPageUnit
          labelText={`${currentPage} / ${pageCount}`}
          ariaLabel={bilingual(lang, "标注汇总分页", "Intent summary pagination")}
          onPageChange={(nextPage) => {
            setPage(nextPage);
            syncUrl({ page: nextPage });
          }}
          onPageSizeChange={(nextSize) => {
            setPageSize(nextSize);
            setPage(1);
            syncUrl({ pageSize: nextSize, page: 1 });
          }}
        />
      </section>

      {createPortal(
        <dialog
          ref={confirmDialogRef}
          className="dialog intent-delete-confirm-dialog"
          id="raIntentDeleteConfirmDialog"
          aria-labelledby="raIntentDeleteConfirmTitle"
          onClose={() => setConfirmDelete(null)}
        >
          {confirmDelete ? (
            <div className="dialog-card">
              <div className="dialog-heading">
                <div>
                  <h2 id="raIntentDeleteConfirmTitle">
                    {confirmDelete.kind === "bulk"
                      ? bilingual(lang, "批量删除当前标注", "Bulk delete current labels")
                      : bilingual(lang, "删除当前标注", "Delete current label")}
                  </h2>
                  <p className="dialog-copy">
                    {confirmDelete.kind === "bulk"
                      ? bilingual(
                          lang,
                          `确认批量删除选中的 ${confirmDelete.rows.length} 条当前标注？`,
                          `Delete ${confirmDelete.rows.length} selected labels?`,
                        )
                      : bilingual(
                          lang,
                          `确认删除 ${confirmDelete.row.username} 在 ${confirmDelete.row.case_id} 的当前标注？`,
                          `Delete ${confirmDelete.row.username}'s label on ${confirmDelete.row.case_id}?`,
                        )}
                  </p>
                </div>
                <button
                  className="icon-button"
                  type="button"
                  aria-label={bilingual(lang, "关闭", "Close")}
                  onClick={() => setConfirmDelete(null)}
                >
                  ×
                </button>
              </div>
              <p className="intent-delete-confirm-note">
                {bilingual(
                  lang,
                  "当前答案会从工作区移除；历史修订与删除审计仍会完整保留。",
                  "Current answers will be removed from the workspace; revision history and audit records are preserved.",
                )}
              </p>
              <div className="dialog-actions">
                <button
                  className="button button-quiet"
                  type="button"
                  disabled={deleting}
                  onClick={() => setConfirmDelete(null)}
                >
                  {bilingual(lang, "取消", "Cancel")}
                </button>
                <button
                  className="button button-danger"
                  type="button"
                  disabled={deleting}
                  onClick={() => void executeDelete()}
                >
                  {confirmDelete.kind === "bulk"
                    ? bilingual(
                        lang,
                        `确认删除 ${confirmDelete.rows.length} 条`,
                        `Confirm delete (${confirmDelete.rows.length})`,
                      )
                    : bilingual(lang, "确认删除", "Confirm delete")}
                </button>
              </div>
            </div>
          ) : null}
        </dialog>,
        document.body,
      )}
    </div>
  );
};
