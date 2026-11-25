import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, UiLanguage, withWorkbenchBase } from "../bridge/useWorkbenchBridge";
import { CASE_PAGE_SIZES, DEFAULT_CASE_PAGE_SIZE, Pagination } from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

const VERSION_DATASET_CACHE_MS = 30_000;
const STANDARD_MODES = ["targets", "sampled_targets", "low"] as const;

export interface VersionDatasetCatalogItem {
  id: string;
  release_family: string;
  historical?: boolean;
  total: number;
  targets?: number | null;
  states?: Record<string, number>;
}

export interface VersionDatasetCatalogResponse {
  items: VersionDatasetCatalogItem[];
}

export interface VersionDatasetCountScope {
  total: number;
  targets?: number | null;
  states?: Record<string, number>;
  exclusions?: Array<{ type: string; count: number }>;
  sampled?: number;
  completed?: number;
  low_only?: number;
  trail_links?: Record<string, string>;
  trail_link_types?: Record<string, string>;
  trail_reason_exclusions?: string[];
}

export interface VersionCompositionGroup {
  key: string;
  count: number;
  ratio: number;
}

export interface VersionComposition {
  total: number;
  pending: number;
  excluded: number;
  groups: VersionCompositionGroup[];
}

export interface VersionTeSummary {
  total: number;
  filled: number;
  unfilled: number;
  unknown: number;
  rate: number;
}

export interface VersionTeDailyItem {
  date: string;
  summary: VersionTeSummary;
}

export interface VersionTePayload {
  summary: VersionTeSummary;
  source_status: string;
  last_success_at?: string | number | null;
  observed_changes?: { te?: number } | null;
  distribution: Array<{ value: string; count: number }>;
  daily: VersionTeDailyItem[];
}

export interface VersionRdPayload {
  source_status?: string;
  total: number;
  completed: number;
  pending: number;
  conflict: number;
  distribution: Record<string, number>;
}

export interface VersionMemberRow {
  issue_id: string;
  state: string;
  date?: string | null;
  issue_time?: string | number | null;
  ra_start_timestamp?: string | number | null;
  first_seen?: string | number | null;
  trigger?: string | null;
  is_target?: boolean;
  is_sample?: boolean;
  is_low?: boolean;
  te_status: string;
  te_value?: string | null;
  review_submitted?: boolean;
  reviewers?: Array<{ submitted?: boolean }>;
  prediction?: {
    model_label?: string | null;
    model_confidence?: number | null;
  } | null;
  binding?: {
    run_id?: string | null;
    campaign_id?: string | null;
    assignee?: string | null;
    assignees?: string[] | null;
  } | null;
}

export interface VersionWorkbenchResponse {
  dataset_id: string;
  dataset: VersionDatasetCatalogItem;
  count_scope?: VersionDatasetCountScope | null;
  composition?: VersionComposition | null;
  te: VersionTePayload;
  rd?: VersionRdPayload | null;
  assignees?: string[];
  date_options?: string[];
  snapshot_revision?: string | number;
  page: number;
  page_size: number;
  total: number;
  items: VersionMemberRow[];
}

export interface VersionBatchesResponse {
  items: Array<{
    created_at?: string | number | null;
    target_added?: number;
    added: number;
    changed: number;
  }>;
}

export interface VersionDatasetRouteState {
  dataset: string;
  mode: string;
  sort: string;
  query: string;
  page: number;
  pageSize: number;
  date: string;
  teStatus: string;
  media: string;
  assignee: string;
  reviewStatus: string;
}

export function versionDatasetScopeLabel(mode: string, lang: UiLanguage): string {
  const map: Record<string, string> = {
    targets: bilingual(lang, "全部复核目标", "All review targets"),
    sampled_targets: bilingual(lang, "随机抽样集", "Random sample"),
    low: bilingual(lang, "低置信（不含抽样）", "Low confidence (excluding samples)"),
    samples: bilingual(lang, "抽样候选（含未就绪）", "Sample candidates (including pending)"),
    waiting: bilingual(lang, "等待数据或重试", "Awaiting data or retry"),
    published: bilingual(lang, "已回刷", "Published"),
    excluded: bilingual(lang, "已过滤", "Excluded"),
    source_waiting: bilingual(lang, "待源信息", "Awaiting source"),
    all: bilingual(lang, "全部与历史", "All and history"),
  };
  return map[mode] || mode;
}

export function versionDatasetTime(
  value: string | number | null | undefined,
  lang: UiLanguage,
): string {
  if (!value) return "—";
  const n = Number(value);
  const d = new Date(Number.isFinite(n) && n > 0 ? (n < 1e11 ? n * 1000 : n) : value);
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

export function versionDatasetStatusLabel(state: string, lang: UiLanguage): string {
  const map: Record<string, string> = {
    ready: bilingual(lang, "待处理", "Queued"),
    running: bilingual(lang, "推理中", "Inferring"),
    published: bilingual(lang, "已回刷", "Published"),
    inferred: bilingual(lang, "已推理", "Inferred"),
    waiting_metadata: bilingual(lang, "待齐备", "Awaiting source"),
    retry_wait: bilingual(lang, "等待重试", "Retry pending"),
    excluded: bilingual(lang, "已过滤", "Excluded"),
    needs_attention: bilingual(lang, "需处理", "Needs attention"),
    identity_conflict: bilingual(lang, "信息冲突", "Identity conflict"),
  };
  return map[state] || state;
}

export function versionTEResultLabel(value: string | null | undefined, lang: UiLanguage): string {
  const raw = String(value ?? "");
  const labels: Record<string, string> = {
    失败: bilingual(lang, "失败", "Failed"),
    成功: bilingual(lang, "成功", "Succeeded"),
    超出范围: bilingual(lang, "超出范围", "Out of scope"),
    out_of_scope: bilingual(lang, "超出范围", "Out of scope"),
    误触发: bilingual(lang, "误触发", "False trigger"),
    未接起: bilingual(lang, "未接起", "Unanswered"),
    无需协助: bilingual(lang, "无需协助", "No assistance needed"),
    正确触发: bilingual(lang, "正确触发", "Correct trigger"),
  };
  return Object.prototype.hasOwnProperty.call(labels, raw) ? labels[raw] : raw;
}

export function versionTEBadgeLabel(row: VersionMemberRow, lang: UiLanguage): string {
  if (row.te_status === "filled") return `TE · ${versionTEResultLabel(row.te_value, lang)}`;
  if (row.te_status === "unfilled") return bilingual(lang, "TE 待标", "TE pending");
  if (row.te_status === "not_target") return bilingual(lang, "未纳入复核", "Outside review set");
  return bilingual(lang, "TE 未知", "TE unknown");
}

export function versionLabelColor(value: string | null | undefined): string {
  switch (String(value ?? "")) {
    case "成功":
    case "正确触发":
      return "var(--chart-teal)";
    case "误触发":
      return "var(--chart-rose)";
    case "失败":
      return "var(--chart-indigo)";
    case "无需协助":
      return "var(--chart-blue)";
    case "未接起":
      return "var(--chart-slate)";
    default:
      return "var(--muted)";
  }
}

export function dailyStatusRows(
  summary: Pick<VersionTeSummary, "filled" | "unfilled" | "unknown"> | null | undefined,
  lang: UiLanguage,
): Array<["filled" | "unfilled" | "unknown", string, number]> {
  return [
    ["filled", bilingual(lang, "已标", "Filled"), summary?.filled ?? 0],
    ["unfilled", bilingual(lang, "待标", "Pending"), summary?.unfilled ?? 0],
    ["unknown", bilingual(lang, "未知", "Unknown"), summary?.unknown ?? 0],
  ];
}

export function readVersionDatasetRoute(
  search: string = typeof window !== "undefined" ? window.location.search : "",
  fallbackDataset = "",
): VersionDatasetRouteState {
  const p = new URLSearchParams(search);
  const rawSize = Number(p.get("page_size"));
  const pageSize = CASE_PAGE_SIZES.includes(rawSize as (typeof CASE_PAGE_SIZES)[number])
    ? rawSize
    : DEFAULT_CASE_PAGE_SIZE;
  return {
    dataset: p.get("dataset") || fallbackDataset,
    mode: p.get("mode") || "targets",
    sort: p.get("sort") || "added",
    query: p.get("q") || "",
    page: Math.max(1, Number(p.get("page")) || 1),
    pageSize,
    date: p.get("date") || "",
    teStatus: p.get("te_status") || "all",
    media: p.get("media") || "bev",
    assignee: p.get("assignee") || "",
    reviewStatus: p.get("review_status") || "all",
  };
}

function writeVersionDatasetRoute(next: VersionDatasetRouteState) {
  if (typeof window === "undefined") return;
  const u = new URL(window.location.href);
  const params: Record<string, string | number> = {
    dataset: next.dataset,
    mode: next.mode,
    sort: next.sort,
    q: next.query,
    page: next.page,
    page_size: next.pageSize,
    date: next.date,
    te_status: next.teStatus,
    media: next.media,
    assignee: next.assignee,
    review_status: next.reviewStatus,
  };
  for (const [key, value] of Object.entries(params)) {
    if (value) u.searchParams.set(key, String(value));
    else u.searchParams.delete(key);
  }
  window.history.pushState({}, "", u);
}

function buildReviewCaseUrl(
  issueId: string,
  runId: string,
  campaignId: string,
  releaseFamily: string,
): string {
  const win = window as unknown as {
    pageUrl?: (page: string, options?: Record<string, unknown>) => string;
  };
  if (typeof win.pageUrl === "function") {
    return win.pageUrl("review", {
      issue: issueId,
      runId,
      workSplitId: campaignId || "",
      workflowMode: "model_review_and_case_label",
      comparisonStatus: "all",
      baselines: [`version-${releaseFamily}`],
    });
  }
  const url = new URL(withWorkbenchBase("/review"), window.location.origin);
  url.searchParams.set("issue", issueId);
  url.searchParams.set("run", runId);
  if (campaignId) url.searchParams.set("work_split", campaignId);
  url.searchParams.set("workflow_mode", "model_review_and_case_label");
  url.searchParams.set("comparison", "all");
  url.searchParams.set("baselines", `version-${releaseFamily}`);
  return url.toString();
}

function buildDetailsTooltip(row: VersionMemberRow, lang: UiLanguage): string {
  const owner =
    row.binding?.assignees?.join(", ") ||
    row.binding?.assignee ||
    bilingual(lang, "未分配", "Unassigned");
  const trigger = row.trigger || "—";
  const occurred = row.issue_time || row.ra_start_timestamp;
  const time = occurred ? versionDatasetTime(occurred, lang) : row.date || "—";
  const added = versionDatasetTime(row.first_seen, lang);
  return bilingual(
    lang,
    `负责人 ${owner} · 触发 ${trigger} · 入库 ${added} · 发生 ${time} CST`,
    `Assignee ${owner} · Trigger ${trigger} · Added ${added} · Occurred ${time} CST`,
  );
}

const InfoIconSvg: React.FC = () => (
  <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true">
    <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.4" />
    <path d="M10 9.1v4.6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    <circle cx="10" cy="6.3" r=".9" fill="currentColor" />
  </svg>
);

interface MetricTrailLinkSpec {
  href: string;
  label: string;
  note: string;
}

function makeTrailLink(
  scope: VersionDatasetCountScope | null | undefined,
  mode: string,
  label: string,
  lang: UiLanguage,
): MetricTrailLinkSpec | null {
  const href = scope?.trail_links?.[mode];
  if (!href) return null;
  const byReason = scope?.trail_link_types?.[mode] === "reason_fields";
  const note = byReason
    ? bilingual(
        lang,
        "Trail实时字段筛选，数量可能随更新变化。",
        "Live Trail field query; counts may change as data updates.",
      ) +
      (scope?.trail_reason_exclusions?.length
        ? bilingual(
            lang,
            "1009额外排除kEndOfLaneSequence。",
            "1009 additionally excludes kEndOfLaneSequence.",
          )
        : "")
    : bilingual(lang, "在Trail按当前统计的案例ID筛选", "Filter the current recorded case IDs in Trail");
  return { href, label, note };
}

export interface VersionDatasetsPageProps {
  active: boolean;
  lang: UiLanguage;
}

export const VersionDatasetsPage: React.FC<VersionDatasetsPageProps> = ({ active, lang }) => {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const mediaSeqRef = useRef(0);

  const [routeState, setRouteState] = useState<VersionDatasetRouteState>(() =>
    readVersionDatasetRoute(),
  );
  const [searchDraft, setSearchDraft] = useState<string>(() => readVersionDatasetRoute().query);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [docHidden, setDocHidden] = useState<boolean>(() =>
    typeof document !== "undefined" ? Boolean(document.hidden) : false,
  );
  const [retainedOverview, setRetainedOverview] = useState<{
    datasetId: string;
    data: VersionWorkbenchResponse;
    scope: { mode: string; date: string; assignee: string; reviewStatus: string };
  } | null>(null);

  // Sync URL on activation, workbench sync, or browser back/forward
  useEffect(() => {
    if (!active) return;
    const sync = () => {
      setRouteState((prev) => {
        const next = readVersionDatasetRoute(window.location.search, prev.dataset);
        if (JSON.stringify(prev) === JSON.stringify(next)) return prev;
        setSearchDraft(next.query);
        return next;
      });
    };
    sync();
    window.addEventListener("popstate", sync);
    window.addEventListener("ra:workbench-sync", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("ra:workbench-sync", sync);
    };
  }, [active]);

  // Track document visibility to pause/resume 30s polling just like classic
  useEffect(() => {
    const onVisibility = () => {
      setDocHidden(Boolean(document.hidden));
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  // Bind classic info popovers for the 4 KPI cards (`[data-version-info]`) and `#versionTEInfo`
  useEffect(() => {
    const win = window as unknown as {
      bindUiInfoPopovers?: (root: HTMLElement | null) => void;
      closeUiInfoPopovers?: (root: HTMLElement | null) => void;
    };
    const root = rootRef.current;
    if (active && root) {
      win.bindUiInfoPopovers?.(root);
    }
    return () => {
      if (root) win.closeUiInfoPopovers?.(root);
    };
  }, [active]);

  const catalogQuery = useQuery<VersionDatasetCatalogResponse>({
    queryKey: ["version-datasets", "catalog"],
    queryFn: ({ signal }) =>
      apiRequest<VersionDatasetCatalogResponse>("/api/version-datasets?include_legacy=true", {
        signal,
      }),
    enabled: active && !docHidden,
    staleTime: VERSION_DATASET_CACHE_MS,
    refetchInterval: active && !docHidden ? VERSION_DATASET_CACHE_MS : false,
  });

  const catalogItems = useMemo(() => catalogQuery.data?.items || [], [catalogQuery.data]);

  const effectiveDataset = useMemo(() => {
    if (!catalogItems.length) return routeState.dataset;
    if (catalogItems.some((x) => x.id === routeState.dataset)) return routeState.dataset;
    return catalogItems.find((x) => (x.targets || 0) > 0)?.id || catalogItems[0]?.id || "";
  }, [catalogItems, routeState.dataset]);

  // Keep routeState.dataset aligned once catalog resolves an initial default dataset
  useEffect(() => {
    if (!active || !effectiveDataset || effectiveDataset === routeState.dataset) return;
    setRouteState((prev) => ({ ...prev, dataset: effectiveDataset }));
  }, [active, effectiveDataset, routeState.dataset]);

  const workbenchQuery = useQuery<VersionWorkbenchResponse>({
    queryKey: [
      "version-datasets",
      "workbench",
      effectiveDataset,
      routeState.page,
      routeState.pageSize,
      routeState.mode,
      routeState.sort,
      routeState.query,
      routeState.date,
      routeState.teStatus,
      routeState.assignee,
      routeState.reviewStatus,
    ],
    queryFn: ({ signal }) => {
      const p = new URLSearchParams({
        page: String(routeState.page),
        page_size: String(routeState.pageSize),
        mode: routeState.mode,
        sort: routeState.sort,
        q: routeState.query,
        date: routeState.date,
        te_status: routeState.teStatus,
        assignee: routeState.assignee,
        review_status: routeState.reviewStatus,
      });
      return apiRequest<VersionWorkbenchResponse>(
        `/api/version-datasets/${encodeURIComponent(effectiveDataset)}/workbench?${p.toString()}`,
        { signal },
      );
    },
    enabled: active && !docHidden && Boolean(effectiveDataset),
    staleTime: VERSION_DATASET_CACHE_MS,
    refetchInterval: active && !docHidden ? VERSION_DATASET_CACHE_MS : false,
  });

  // Retain last resolved overview for the same dataset while switching filters (classic `chartsPending`)
  useEffect(() => {
    const data = workbenchQuery.data;
    if (data && data.dataset_id === effectiveDataset) {
      setRetainedOverview({
        datasetId: data.dataset_id,
        data,
        scope: {
          mode: routeState.mode,
          date: routeState.date,
          assignee: routeState.assignee,
          reviewStatus: routeState.reviewStatus,
        },
      });
    }
  }, [
    workbenchQuery.data,
    effectiveDataset,
    routeState.mode,
    routeState.date,
    routeState.assignee,
    routeState.reviewStatus,
  ]);

  // Clear retained overview when switching to a different dataset
  useEffect(() => {
    if (retainedOverview && retainedOverview.datasetId !== effectiveDataset) {
      setRetainedOverview(null);
    }
  }, [effectiveDataset, retainedOverview]);

  const batchesQuery = useQuery<VersionBatchesResponse>({
    queryKey: ["version-datasets", "batches", effectiveDataset],
    queryFn: ({ signal }) =>
      apiRequest<VersionBatchesResponse>(
        `/api/version-datasets/${encodeURIComponent(effectiveDataset)}/batches`,
        { signal },
      ),
    enabled:
      active &&
      historyOpen &&
      Boolean(effectiveDataset) &&
      effectiveDataset !== "historical-0821",
    staleTime: VERSION_DATASET_CACHE_MS,
  });

  const changeRoute = useCallback(
    (patch: Partial<VersionDatasetRouteState>) => {
      setRouteState((prev) => {
        const mergedPatch: Partial<VersionDatasetRouteState> = { ...patch };
        const mediaOnly =
          Object.keys(mergedPatch).length > 0 &&
          Object.keys(mergedPatch).every((k) => k === "media");
        const datasetChanged =
          "dataset" in mergedPatch &&
          mergedPatch.dataset !== undefined &&
          mergedPatch.dataset !== prev.dataset;
        if (datasetChanged) {
          mergedPatch.date = "";
        }
        if (mergedPatch.dataset === "historical-0821") {
          mergedPatch.assignee = "";
          mergedPatch.reviewStatus = "all";
        }
        const next: VersionDatasetRouteState = {
          ...prev,
          ...(mediaOnly ? {} : { page: 1 }),
          ...mergedPatch,
        };
        next.page = Math.max(1, Number(next.page) || 1);
        if (JSON.stringify(next) === JSON.stringify(prev)) return prev;
        if ("query" in mergedPatch) setSearchDraft(next.query);
        writeVersionDatasetRoute(next);
        return next;
      });
    },
    [],
  );

  const members =
    workbenchQuery.data && workbenchQuery.data.dataset_id === effectiveDataset
      ? workbenchQuery.data
      : null;
  const overview =
    members || (retainedOverview?.datasetId === effectiveDataset ? retainedOverview.data : null);
  const chartsPending = !members && Boolean(overview);
  const overviewScope = members
    ? {
        mode: routeState.mode,
        date: routeState.date,
        assignee: routeState.assignee,
        reviewStatus: routeState.reviewStatus,
      }
    : retainedOverview?.scope || {
        mode: routeState.mode,
        date: routeState.date,
        assignee: routeState.assignee,
        reviewStatus: routeState.reviewStatus,
      };

  const isLoading =
    catalogQuery.isFetching || (Boolean(effectiveDataset) && workbenchQuery.isFetching);
  const hasError = catalogQuery.isError || workbenchQuery.isError;

  const currentDataset: VersionDatasetCatalogItem | undefined =
    members?.dataset || catalogItems.find((x) => x.id === effectiveDataset);
  const isHistorical = Boolean(currentDataset?.historical);

  const metricsFamilyMatch = /^release-(20\d{6})-odd2$/.exec(effectiveDataset || "");
  const metricsFamily = metricsFamilyMatch?.[1] || "";

  // Concurrency-limited (max 4) IntersectionObserver lazy thumbnail loader matching classic `observeVersionDatasetImages`
  const gridRenderKey = useMemo(
    () =>
      JSON.stringify([
        effectiveDataset,
        routeState.mode,
        routeState.sort,
        routeState.query,
        routeState.media,
        routeState.date,
        routeState.teStatus,
        routeState.assignee,
        routeState.reviewStatus,
        members?.items?.map((i) => i.issue_id) || [],
      ]),
    [
      effectiveDataset,
      routeState.mode,
      routeState.sort,
      routeState.query,
      routeState.media,
      routeState.date,
      routeState.teStatus,
      routeState.assignee,
      routeState.reviewStatus,
      members,
    ],
  );

  useEffect(() => {
    if (!active || !gridRef.current) return;
    const grid = gridRef.current;
    const images = Array.from(grid.querySelectorAll<HTMLImageElement>("img[data-src]"));
    if (!images.length) return;

    let cancelled = false;
    const queue: HTMLImageElement[] = [];
    let running = 0;

    const drain = () => {
      if (cancelled) return;
      while (queue.length && running < 4) {
        const img = queue.shift();
        if (!img || !img.isConnected || img.getAttribute("src")) continue;
        const src = img.dataset.src;
        if (!src) continue;
        running += 1;
        const done = () => {
          running -= 1;
          delete img.dataset.src;
          drain();
        };
        img.addEventListener(
          "load",
          () => {
            img.classList.remove("is-loading");
            img.hidden = false;
            const placeholder = img.previousElementSibling as HTMLElement | null;
            if (placeholder) placeholder.hidden = true;
            done();
          },
          { once: true },
        );
        img.addEventListener(
          "error",
          () => {
            img.hidden = true;
            done();
          },
          { once: true },
        );
        img.src = src;
      }
    };

    if (typeof IntersectionObserver === "undefined") {
      queue.push(...images);
      drain();
      return () => {
        cancelled = true;
      };
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (cancelled) return;
        for (const entry of entries) {
          if (entry.isIntersecting) {
            observer.unobserve(entry.target);
            queue.push(entry.target as HTMLImageElement);
          }
        }
        drain();
      },
      { rootMargin: "120px" },
    );

    images.forEach((img) => observer.observe(img));
    return () => {
      cancelled = true;
      observer.disconnect();
    };
  }, [active, gridRenderKey]);

  // Open classic `#mediaDialog` lightbox seamlessly via global `window.openMedia`
  const openVersionMedia = useCallback(
    async (row: VersionMemberRow) => {
      const seq = (mediaSeqRef.current += 1);
      const kind = routeState.media;
      const win = window as unknown as {
        openMedia?: (
          mediaKind: string,
          index: number,
          opts: { caseData: Record<string, unknown> },
        ) => void;
        heroFrameIndex?: (frames: unknown[]) => number;
        preferredMediaKind?: (data: Record<string, unknown>) => string;
        showToast?: (msg: string, isError?: boolean) => void;
      };
      try {
        const data = await apiRequest<{
          camera?: { frames?: unknown[] };
          assets?: { frames?: unknown[] };
          [key: string]: unknown;
        }>(`/api/cases/${encodeURIComponent(row.issue_id)}/media`);
        if (!active || seq !== mediaSeqRef.current) return;
        const frames = kind === "camera" ? data.camera?.frames : data.assets?.frames;
        const fallbackKind = win.preferredMediaKind?.(data);
        if (!frames?.length && !fallbackKind) {
          win.showToast?.(bilingual(lang, "媒体待就绪", "Media pending"));
          return;
        }
        const heroIdx = typeof win.heroFrameIndex === "function" ? win.heroFrameIndex(frames || []) : 0;
        win.openMedia?.(kind, heroIdx, {
          caseData: {
            ...data,
            gt_label: "",
            reference_media: true,
            te_observation: { ...row, version_dataset: true },
          },
        });
      } catch {
        if (active && seq === mediaSeqRef.current) {
          win.showToast?.(
            bilingual(lang, "媒体暂不可用，请稍后重试", "Media unavailable; try again"),
            true,
          );
        }
      }
    },
    [active, lang, routeState.media],
  );

  // Dropdown options (zero raw native <select>)
  const datasetOptions: UiSelectOption[] = useMemo(
    () =>
      catalogItems.map((x) => ({
        value: x.id,
        label: `${x.release_family.slice(4)} · ${x.targets ?? "—"} ${bilingual(
          lang,
          "复核案例",
          "review cases",
        )}`,
      })),
    [catalogItems, lang],
  );

  const modeOptions: UiSelectOption[] = useMemo(() => {
    const modes: string[] = [...STANDARD_MODES];
    if (routeState.mode && !modes.includes(routeState.mode)) modes.push(routeState.mode);
    return modes.map((m) => ({ value: m, label: versionDatasetScopeLabel(m, lang) }));
  }, [routeState.mode, lang]);

  const facets = members || overview;

  const dateOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "全部日期", "All dates") },
      ...(facets?.date_options || []).map((d) => ({ value: d, label: d })),
    ],
    [facets?.date_options, lang],
  );

  const assigneeOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "全部负责人", "All assignees") },
      ...(facets?.assignees || []).map((x) => ({ value: x, label: x })),
    ],
    [facets?.assignees, lang],
  );

  const reviewStatusOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "all", label: bilingual(lang, "全部复核状态", "All review states") },
      { value: "pending", label: bilingual(lang, "联合待办", "Review pending") },
      { value: "completed", label: bilingual(lang, "联合已完成", "Review completed") },
    ],
    [lang],
  );

  const teStatusOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "all", label: bilingual(lang, "全部 TE 状态", "All TE states") },
      { value: "unfilled", label: bilingual(lang, "TE 待标", "TE pending") },
      { value: "filled", label: bilingual(lang, "TE 已标", "TE filled") },
      { value: "unknown", label: bilingual(lang, "TE 未知", "TE unknown") },
    ],
    [lang],
  );

  const mediaOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "bev", label: "BEV" },
      { value: "camera", label: "Camera" },
    ],
    [],
  );

  const sortOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "added", label: bilingual(lang, "最新入库", "Recently added") },
      { value: "updated", label: bilingual(lang, "最近更新", "Recently updated") },
      { value: "occurred", label: bilingual(lang, "最近发生", "Recently occurred") },
      { value: "issue", label: bilingual(lang, "Issue 编号", "Issue ID") },
    ],
    [lang],
  );

  // Build 4 KPI metric cards (exact parity with `renderVersionMetricCards`)
  const metricCards = useMemo(() => {
    if (!currentDataset) return null;
    const scope = overview?.dataset_id === effectiveDataset ? overview.count_scope : null;
    const historical = Boolean(currentDataset.historical);
    const states = scope?.states || currentDataset.states || {};
    const total = scope?.total ?? currentDataset.total;
    const published = states.published || 0;
    const excluded = states.excluded || 0;
    const waiting = states.waiting_metadata || 0;
    const other = total - published - excluded - waiting;
    const targets = scope?.targets ?? currentDataset.targets ?? "—";
    const titleScope = historical
      ? bilingual(lang, "固定历史集", "Frozen historical cohort")
      : bilingual(lang, "全版本 · 全部日期", "Whole version · All dates");

    const allLink = makeTrailLink(
      scope,
      historical ? "targets" : "all",
      bilingual(lang, "Trail · 全部案例", "Trail · All cases"),
      lang,
    );
    const excludedLink = !historical
      ? makeTrailLink(
          scope,
          "excluded",
          bilingual(lang, `Trail · 已过滤${excluded}条`, `Trail · ${excluded} excluded cases`),
          lang,
        )
      : null;
    const publishedLink = makeTrailLink(
      scope,
      "published",
      bilingual(lang, "Trail · 已回刷案例", "Trail · Published cases"),
      lang,
    );
    const targetsLink = makeTrailLink(
      scope,
      "targets",
      bilingual(lang, "Trail · 复核目标", "Trail · Review targets"),
      lang,
    );
    const sampledTargetsLink = !historical
      ? makeTrailLink(
          scope,
          "sampled_targets",
          bilingual(lang, "Trail · 抽样目标", "Trail · Sampled targets"),
          lang,
        )
      : null;
    const waitingLink = makeTrailLink(
      scope,
      "source_waiting",
      bilingual(lang, "Trail · 待齐备案例", "Trail · Awaiting source"),
      lang,
    );

    const exclusionNames: Record<string, string> = {
      CZ_TL: bilingual(lang, "CZ_TL（红绿灯）", "CZ_TL (traffic lights)"),
      kEndOfLaneSequence: bilingual(
        lang,
        "kEndOfLaneSequence（车道序列结束）",
        "kEndOfLaneSequence (lane sequence end)",
      ),
      other_exclusion: bilingual(lang, "原始事件或其他排除", "Raw-event or other exclusions"),
    };
    const breakdown = (scope?.exclusions || [])
      .map((x) => `${exclusionNames[x.type] || x.type} ${x.count}`)
      .join("；");
    const counts = scope
      ? bilingual(
          lang,
          `${total}＝已回刷${published}＋已过滤${excluded}＋待源${waiting}${other ? `＋其他待处理${other}` : ""}。`,
          ` ${total} = published ${published} + excluded ${excluded} + awaiting source ${waiting}${
            other ? ` + other pending ${other}` : ""
          }.`,
        )
      : bilingual(lang, "载入明细中…", "Loading breakdown…");
    const sampling =
      scope && !historical
        ? bilingual(
            lang,
            `抽样${scope.sampled ?? 0}/${scope.completed ?? 0}（${
              scope.completed ? ((100 * (scope.sampled ?? 0)) / scope.completed).toFixed(2) : "0"
            }%）；每条准入案例独立10%概率，数量可波动。`,
            `Samples ${scope.sampled ?? 0}/${scope.completed ?? 0} (${
              scope.completed ? ((100 * (scope.sampled ?? 0)) / scope.completed).toFixed(2) : "0"
            }%); each eligible case has a 10% probability, so counts vary.`,
          )
        : "";

    return {
      titleScope,
      cards: [
        {
          label: historical
            ? bilingual(lang, "固定案例", "Frozen cases")
            : bilingual(lang, "发现总数", "Discovered"),
          value: total,
          note: historical
            ? bilingual(
                lang,
                "0821固定历史目标集，不参与本流程增量抽样。",
                "Frozen 0821 cohort; not resampled by this workflow.",
              )
            : `${counts}${breakdown ? ` ${breakdown}。` : ""}${bilingual(
                lang,
                "按触发源过滤，不按画面是否有红绿灯。",
                "Exclusions follow trigger sources, not visible traffic lights.",
              )}`,
          links: [allLink, excludedLink].filter((x): x is MetricTrailLinkSpec => Boolean(x)),
        },
        {
          label: bilingual(lang, "已回刷", "Published"),
          value: historical ? "—" : published,
          note: historical
            ? bilingual(
                lang,
                "历史集未登记本流程回刷状态。",
                "Publication status is not registered for this historical cohort.",
              )
            : bilingual(
                lang,
                "已完成推理及Trail回刷校验；含低置信、抽样和其他案例。",
                "Inference and Trail publication verified; includes low-confidence, sampled and other cases.",
              ) +
              (scope?.trail_reason_exclusions?.length
                ? bilingual(
                    lang,
                    "1009查询排除kEndOfLaneSequence。",
                    "1009 query excludes kEndOfLaneSequence.",
                  )
                : ""),
          links: [historical ? allLink : publishedLink].filter(
            (x): x is MetricTrailLinkSpec => Boolean(x),
          ),
        },
        {
          label: bilingual(lang, "复核目标", "Review targets"),
          value: targets,
          note: historical
            ? bilingual(lang, "固定历史复核集。", "Frozen historical review set.")
            : `${bilingual(
                lang,
                `低置信（未被抽样覆盖）${scope?.low_only ?? "—"}＋抽样${scope?.sampled ?? "—"}＝${targets}。`,
                `Low confidence excluding samples ${scope?.low_only ?? "—"} + sampled ${scope?.sampled ?? "—"} = ${targets}.`,
              )} ${sampling}`,
          links: [targetsLink, sampledTargetsLink].filter(
            (x): x is MetricTrailLinkSpec => Boolean(x),
          ),
        },
        {
          label: bilingual(lang, "待齐备", "Awaiting source"),
          value: historical ? "—" : waiting,
          note: historical
            ? bilingual(
                lang,
                "历史集无增量待齐备队列。",
                "No incremental source queue for the frozen cohort.",
              )
            : bilingual(
                lang,
                "触发源或锚点未齐备，后续补查；不计入当前抽样分母。",
                "Trigger source or anchor is incomplete; checked later and excluded from the current sampling denominator.",
              ),
          links: [historical ? allLink : waitingLink].filter(
            (x): x is MetricTrailLinkSpec => Boolean(x),
          ),
        },
      ],
    };
  }, [currentDataset, overview, effectiveDataset, lang]);

  // Composition section data
  const composition = overview?.composition || null;
  const compositionLabels: Record<string, string> = useMemo(
    () => ({
      low: bilingual(lang, "低置信", "Low confidence"),
      sample: bilingual(lang, "抽样", "Sample"),
      other: bilingual(lang, "其他", "Other"),
    }),
    [lang],
  );

  // TE overview data
  const te = overview?.te || null;
  const teSummary = te?.summary || null;
  const teFilledPct = teSummary?.total ? (100 * teSummary.filled) / teSummary.total : 0;
  const teKnownPct = teSummary?.total
    ? (100 * (teSummary.filled + teSummary.unfilled)) / teSummary.total
    : 0;
  const teRingSegments = useMemo(() => {
    if (!teSummary || !teSummary.total) return [];
    let offset = 0;
    return dailyStatusRows(teSummary, lang)
      .filter(([, , count]) => count > 0)
      .map(([key, label, count]) => {
        const share = (100 * count) / teSummary.total;
        const startOffset = offset;
        offset += share;
        return { key, label, count, share, startOffset };
      });
  }, [teSummary, lang]);

  const sortedTeDistribution = useMemo(
    () => (te?.distribution ? [...te.distribution].sort((a, b) => b.count - a.count) : []),
    [te?.distribution],
  );

  const teScopeText = useMemo(() => {
    if (!overview || !teSummary) return "";
    const parts: string[] = [];
    if (overviewScope.date) parts.push(overviewScope.date);
    parts.push(versionDatasetScopeLabel(overviewScope.mode, lang));
    parts.push(
      overview.dataset.historical
        ? bilingual(lang, `${teSummary.total} 个固定目标`, `${teSummary.total} frozen targets`)
        : bilingual(lang, `${teSummary.total} 个目标`, `${teSummary.total} targets`),
    );
    if (overviewScope.assignee) parts.push(overviewScope.assignee);
    if (overviewScope.reviewStatus === "pending") {
      parts.push(bilingual(lang, "联合待完成", "Combined review pending"));
    } else if (overviewScope.reviewStatus === "completed") {
      parts.push(bilingual(lang, "联合已完成", "Combined review complete"));
    }
    return parts.join(" · ");
  }, [overview, teSummary, overviewScope, lang]);

  const teSourceText = useMemo(() => {
    if (!te) return bilingual(lang, "读取中…", "Loading…");
    const statusLabel =
      te.source_status === "ready"
        ? bilingual(lang, "最近核对", "Last checked")
        : te.source_status === "stale"
          ? bilingual(lang, "观测过期", "Stale observation")
          : bilingual(lang, "同步异常 · 未知单列", "Sync unavailable · Unknown shown separately");
    return `Trail · ${statusLabel} ${versionDatasetTime(te.last_success_at, lang)} CST`;
  }, [te, lang]);

  const teSourceTitle = useMemo(() => {
    if (!te) return "";
    return (
      bilingual(
        lang,
        "来源：ra_review_result_new；不包含平台联合标注。",
        "Source: ra_review_result_new; excludes platform combined labels.",
      ) +
      (te.observed_changes
        ? bilingual(
            lang,
            ` 本轮变化 ${te.observed_changes.te ?? 0}；非当天标注量。`,
            ` Changes this check: ${te.observed_changes.te ?? 0}; not daily annotation volume.`,
          )
        : "")
    );
  }, [te, lang]);

  const loadingStatusText = hasError
    ? bilingual(
        lang,
        "更新失败，图表仍为上次范围；请刷新重试",
        "Update failed; charts show the previous scope. Refresh to retry",
      )
    : chartsPending
      ? bilingual(
          lang,
          "正在切换筛选，图表暂显示上次范围…",
          "Changing filters; charts show the previous scope…",
        )
      : bilingual(lang, "更新中…", "Updating…");

  // CSV export href
  const exportHref = useMemo(() => {
    if (!members || chartsPending || !effectiveDataset) return "";
    const params = new URLSearchParams({
      mode: routeState.mode,
      q: routeState.query,
      sort: routeState.sort,
      date: routeState.date,
      te_status: routeState.teStatus,
      revision: String(members.snapshot_revision ?? ""),
      assignee: routeState.assignee,
      review_status: routeState.reviewStatus,
    });
    return withWorkbenchBase(
      `/api/version-datasets/${encodeURIComponent(effectiveDataset)}/workbench.csv?${params.toString()}`,
    );
  }, [members, chartsPending, effectiveDataset, routeState]);

  // RD panel rendering (1:1 port of `version-rd.js`)
  const rd = overview?.rd || null;
  const rdFailed = hasError && !chartsPending;

  const renderRdPanel = () => {
    if (rdFailed || rd?.source_status === "unsupported") {
      return (
        <p className="version-rd-empty">
          {rdFailed
            ? bilingual(lang, "RD 标注暂不可用，请刷新重试", "RD annotations unavailable; refresh to retry")
            : bilingual(
                lang,
                "此历史固定集暂不提供 RD 统计",
                "RD statistics are unavailable for this frozen historical set",
              )}
        </p>
      );
    }
    if (!rd) {
      return (
        <p className="version-rd-empty">
          {bilingual(lang, "正在读取 RD 标注…", "Loading RD annotations…")}
        </p>
      );
    }
    if (!rd.total) {
      return (
        <p className="version-rd-empty">
          {bilingual(lang, "当前范围暂无复核目标", "No review targets in this scope")}
        </p>
      );
    }
    const rate = ((100 * rd.completed) / rd.total).toFixed(1);
    const categories: Array<[string, string, string]> = [
      ["正确触发", bilingual(lang, "正确触发", "Correct trigger"), "rd-correct"],
      ["误触发", bilingual(lang, "误触发", "False trigger"), "rd-false"],
      ["无需协助", bilingual(lang, "无需协助", "No assistance needed"), "rd-assistance"],
    ];
    const scopeStr = [
      versionDatasetScopeLabel(overviewScope.mode, lang),
      overviewScope.date || bilingual(lang, "全部日期", "All dates"),
    ].join(" · ");
    const sourceDesc = bilingual(
      lang,
      "Manual 当前人工结论；冲突及需复核不计已标。分母为筛选范围内全部目标，不随 TE 状态或翻页改变。",
      "Current Manual human conclusions; conflicts and rechecks are not labeled. Denominator: all filtered targets, independent of TE status and pagination.",
    );
    const pendingText = bilingual(
      lang,
      `待标 ${rd.pending} · 冲突待确认 ${rd.conflict}`,
      `Pending ${rd.pending} · Conflicts to resolve ${rd.conflict}`,
    );
    return (
      <div className="version-rd-grid">
        <section
          className="page-card version-rd-block"
          data-version-chart=""
          aria-labelledby="versionRDProgressTitle"
        >
          <header className="version-rd-header section-heading version-chart-heading">
            <h2 id="versionRDProgressTitle" title={`${sourceDesc} · ${scopeStr}`}>
              {bilingual(lang, "RD 标注进度", "RD labeling progress")}
            </h2>
            <div
              className="version-rd-legend version-rd-progress-legend"
              tabIndex={0}
              role="group"
              aria-label={`${sourceDesc} ${bilingual(
                lang,
                "RD 标注状态图例，可横向滚动",
                "RD labeling status legend; scroll horizontally",
              )}`}
            >
              <span className="version-rd-category" tabIndex={0} data-chart-key="filled">
                <i className="rd-filled" aria-hidden="true" />
                <span>{bilingual(lang, "已标", "Labeled")}</span>
                <span>{`${rd.completed} / ${rd.total}`}</span>
              </span>
              <span className="version-rd-category" tabIndex={0} data-chart-key="unfilled">
                <i className="rd-pending" aria-hidden="true" />
                <span>{bilingual(lang, "待标", "Pending")}</span>
                <span>{rd.pending}</span>
              </span>
              <span
                className="version-rd-category"
                tabIndex={0}
                data-chart-key="conflict"
                title={bilingual(
                  lang,
                  "冲突或来源已变更，需复核",
                  "Conflicting or changed sources; needs recheck",
                )}
              >
                <i className="rd-conflict" aria-hidden="true" />
                <span>{bilingual(lang, "冲突", "Conflicts")}</span>
                <span>{rd.conflict}</span>
              </span>
              <strong>{`${rate}%`}</strong>
            </div>
          </header>
          <div
            className="version-rd-track"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={rd.total}
            aria-valuenow={rd.completed}
            aria-label={bilingual(lang, "RD 标注完成率", "RD annotation completion")}
            aria-valuetext={`${rate}% · ${pendingText}`}
            title={pendingText}
          >
            <i
              data-chart-key="filled"
              className="rd-filled"
              style={{ flex: `${rd.completed} 0 0` }}
            />
            <i
              data-chart-key="unfilled"
              className="rd-pending"
              style={{ flex: `${rd.pending} 0 0` }}
            />
            <i
              data-chart-key="conflict"
              className="rd-conflict"
              style={{ flex: `${rd.conflict} 0 0` }}
            />
          </div>
        </section>

        <section
          className="page-card version-rd-block"
          data-version-chart=""
          aria-labelledby="versionRDMixTitle"
        >
          <header className="version-rd-header section-heading version-chart-heading">
            <h2
              id="versionRDMixTitle"
              title={`${sourceDesc} · ${bilingual(lang, "占已标有效结果", "Share of valid labeled results")}`}
            >
              {bilingual(lang, "RD 三分类分布", "RD classification mix")}
            </h2>
            {rd.completed > 0 && (
              <div
                className="version-rd-legend"
                tabIndex={0}
                role="group"
                aria-label={bilingual(
                  lang,
                  "三分类图例；数量及占已标有效结果比例，可横向滚动",
                  "Classification legend; count and share of valid labeled results; scroll horizontally",
                )}
              >
                {categories.map(([key, label, cls]) => {
                  const count = rd.distribution?.[key] ?? 0;
                  const share = ((100 * count) / rd.completed).toFixed(1);
                  return (
                    <span
                      key={cls}
                      className="version-rd-category"
                      tabIndex={0}
                      data-chart-key={cls}
                      title={`${label} · ${count} / ${rd.completed}`}
                    >
                      <i
                        className={cls}
                        style={{ "--version-label-color": versionLabelColor(key) } as React.CSSProperties}
                        aria-hidden="true"
                      />
                      <span>{label}</span>
                      <span>{`${count} · ${share}%`}</span>
                    </span>
                  );
                })}
              </div>
            )}
          </header>
          {rd.completed > 0 ? (
            <div className="version-rd-stack" aria-hidden="true">
              {categories
                .filter(([key]) => (rd.distribution?.[key] ?? 0) > 0)
                .map(([key, , cls]) => (
                  <i
                    key={cls}
                    data-chart-key={cls}
                    className={cls}
                    style={
                      {
                        "--version-label-color": versionLabelColor(key),
                        flex: `${rd.distribution[key]} 0 0`,
                      } as React.CSSProperties
                    }
                  />
                ))}
            </div>
          ) : (
            <p className="version-rd-empty">
              {bilingual(lang, "暂无有效三分类结果", "No valid classifications yet")}
            </p>
          )}
        </section>
      </div>
    );
  };

  const totalMembers = members?.total ?? 0;
  const pageSizeMembers = members?.page_size ?? routeState.pageSize;
  const currentPageMembers = members?.page ?? routeState.page;
  const totalPagesMembers = Math.max(1, Math.ceil(totalMembers / Math.max(1, pageSizeMembers)));

  return (
    <div
      ref={rootRef}
      className="ra-version-datasets-root"
      data-react-island="version-datasets"
    >
      <a
        id="versionDatasetMetricsLink"
        className="button button-quiet"
        hidden={!metricsFamily}
        href={
          metricsFamily
            ? `${withWorkbenchBase("/version-metrics")}?families=${metricsFamily}`
            : undefined
        }
      >
        {bilingual(lang, "查看版本指标", "View version metrics")}
      </a>

      <div className="version-metrics" id="versionDatasetSummary" aria-live="polite">
        {!catalogQuery.data ? null : !metricCards ? (
          bilingual(lang, "等待首次导入", "Awaiting first import")
        ) : (
          metricCards.cards.map((card, i) => {
            const defAria = bilingual(
              lang,
              `${card.label}统计口径`,
              `${card.label} definition`,
            );
            return (
              <article key={i} className="analysis-stat-card">
                <span className="version-metric-title">
                  <span>{card.label}</span>
                  <span className="model-review-run-help version-te-info" data-version-info="">
                    <button
                      className="version-te-info-button"
                      type="button"
                      aria-label={defAria}
                      aria-expanded="false"
                      aria-controls={`versionMetricInfo${i}`}
                    >
                      <InfoIconSvg />
                    </button>
                    <span
                      className="model-review-run-tooltip version-te-info-tooltip version-metric-tooltip"
                      id={`versionMetricInfo${i}`}
                      role="dialog"
                      aria-label={defAria}
                    >
                      <strong>{`${card.label} · ${metricCards.titleScope}`}</strong>
                      <span>{card.note}</span>
                      <span className="version-metric-links">
                        {card.links.map((link) => (
                          <a
                            key={link.href + link.label}
                            href={link.href}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={link.note}
                          >
                            {`${link.label} ↗`}
                          </a>
                        ))}
                      </span>
                    </span>
                  </span>
                </span>
                <strong>{String(card.value)}</strong>
              </article>
            );
          })
        )}
      </div>

      <section
        className="version-composition"
        aria-label={bilingual(lang, "版本构成", "Version composition")}
      >
        <header>
          <h2>{bilingual(lang, "版本构成", "Version composition")}</h2>
          <span className="muted version-counts" id="versionDatasetCounts">
            {composition && overview
              ? overview.dataset.historical
                ? bilingual(lang, `固定目标集 ${composition.total}`, `Frozen targets ${composition.total}`)
                : bilingual(
                    lang,
                    `已推理准入 ${composition.total} · 待处理 ${composition.pending} · 已过滤 ${composition.excluded}`,
                    `Inferred and admitted ${composition.total} · Pending ${composition.pending} · Excluded ${composition.excluded}`,
                  )
              : ""}
          </span>
        </header>
        <div
          className={`version-composition-bar${!composition?.total ? " is-empty" : ""}`}
          id="versionCompositionBar"
          role="img"
          aria-label={
            composition
              ? composition.groups
                  .map(
                    (g) =>
                      `${compositionLabels[g.key] || g.key} ${g.count} (${(100 * g.ratio).toFixed(1)}%)`,
                  )
                  .join(", ")
              : undefined
          }
        >
          {composition?.groups.map((g) => (
            <i
              key={g.key}
              className={`version-reason-${g.key}`}
              style={{ width: `${100 * g.ratio}%` }}
            />
          ))}
        </div>
        <div className="version-composition-legend" id="versionCompositionLegend">
          {composition?.groups.map((g) => (
            <div key={g.key}>
              <i className={`te-swatch version-reason-${g.key}`} />
              <span>{compositionLabels[g.key] || g.key}</span>
              <strong>{g.count}</strong>
              <small>{composition.total ? `${(100 * g.ratio).toFixed(1)}%` : "—"}</small>
            </div>
          ))}
        </div>
      </section>

      <section
        className="review-commandbar version-filter-panel"
        aria-label={bilingual(lang, "版本数据筛选", "Version dataset filters")}
      >
        <div className="version-toolbar">
          <div className="version-filter-field">
            <span>{bilingual(lang, "数据集", "Dataset")}</span>
            <UiSelect
              id="versionDatasetPicker"
              value={effectiveDataset}
              options={datasetOptions}
              disabled={!datasetOptions.length}
              ariaLabel={bilingual(lang, "数据集", "Dataset")}
              onChange={(val) => changeRoute({ dataset: val })}
            />
          </div>

          <div className="version-filter-field">
            <span>{bilingual(lang, "案例范围", "Case scope")}</span>
            <UiSelect
              id="versionDatasetMode"
              value={routeState.mode}
              options={modeOptions}
              ariaLabel={bilingual(lang, "案例范围", "Case scope")}
              onChange={(val) => changeRoute({ mode: val })}
            />
          </div>

          <div
            className="version-filter-field"
            id="versionDatasetDateField"
            hidden={isHistorical}
          >
            <span>{bilingual(lang, "发生日期 · CST", "Occurrence date · CST")}</span>
            <UiSelect
              id="versionDatasetDate"
              value={routeState.date}
              options={dateOptions}
              disabled={!facets}
              ariaLabel={bilingual(lang, "发生日期 · CST", "Occurrence date · CST")}
              onChange={(val) => changeRoute({ date: val })}
            />
          </div>
        </div>
      </section>

      <div
        id="versionTEPanel"
        className="version-te-grid"
        role="group"
        aria-label={bilingual(lang, "TE 标注概览", "TE annotation overview")}
        aria-busy={isLoading ? "true" : "false"}
      >
        <div className="version-te-context">
          <span className="version-te-scope muted" id="versionTEScope">
            {teScopeText}
          </span>
          <span
            className="version-loading-status muted"
            id="versionDatasetLoading"
            role="status"
            hidden={!isLoading && !chartsPending}
          >
            {loadingStatusText}
          </span>
          <span
            className={`muted${te && te.source_status !== "ready" ? " te-warning" : ""}`}
            id="versionTESource"
            role="status"
            title={teSourceTitle}
          >
            {teSourceText}
          </span>
        </div>

        <section className="page-card version-chart-card version-progress-card">
          <div className="section-heading version-chart-heading">
            <h2>
              {bilingual(lang, "TE 标注进度", "TE labeling progress")}
              <span className="model-review-run-help version-te-info" id="versionTEInfo">
                <button
                  className="version-te-info-button"
                  id="versionTEInfoButton"
                  type="button"
                  aria-label={bilingual(lang, "查看 TE 标注来源", "About the TE annotation source")}
                  aria-describedby="versionTEInfoTooltip"
                  aria-expanded="false"
                >
                  <InfoIconSvg />
                </button>
                <span
                  className="model-review-run-tooltip version-te-info-tooltip"
                  id="versionTEInfoTooltip"
                  role="tooltip"
                >
                  <strong>{bilingual(lang, "TE 标注来源", "TE annotation source")}</strong>
                  <span className="version-te-info-line">
                    {bilingual(
                      lang,
                      "Trail 的 RA Review Result New（ra_review_result_new），与平台联合复核分开统计。",
                      "Trail RA Review Result New (ra_review_result_new), tracked separately from platform combined review.",
                    )}
                  </span>
                  <span className="version-te-info-line">
                    {bilingual(
                      lang,
                      "分母：当前范围的低置信＋抽样目标。非空结果（含失败、未接起等）计已标；无观测记未知。",
                      "Denominator: low-confidence and sampled targets in the current scope. Nonempty results, including failure or unanswered, count as filled; missing observations remain unknown.",
                    )}
                  </span>
                  <span className="version-te-info-line">
                    {bilingual(
                      lang,
                      "按 CST 发生日聚合，晚到数据回填发生日，不代表当天标注量。约 5 分钟采集，页面每 30 秒刷新。",
                      "Dates use occurrence time in CST, including late arrivals, rather than annotation time. Collection runs about every 5 minutes; the page refreshes every 30 seconds.",
                    )}
                  </span>
                </span>
              </span>
            </h2>
          </div>

          <div className="te-scope-chart" data-version-chart="">
            <div
              className={`te-donut${!teSummary?.total ? " is-empty" : ""}`}
              id="versionTEDonut"
              role="img"
              aria-label={
                teSummary
                  ? bilingual(
                      lang,
                      `TE 已标 ${teSummary.filled}，共 ${teSummary.total}`,
                      `TE filled ${teSummary.filled} of ${teSummary.total}`,
                    )
                  : undefined
              }
              style={
                {
                  "--te-filled": `${teFilledPct}%`,
                  "--te-known": `${teKnownPct}%`,
                } as React.CSSProperties
              }
            >
              <svg id="versionTERing" viewBox="0 0 124 124" aria-hidden="true">
                <circle className="version-ring-track" cx="62" cy="62" r="57" />
                {teRingSegments.map((seg) => (
                  <circle
                    key={seg.key}
                    data-chart-key={seg.key}
                    cx="62"
                    cy="62"
                    r="57"
                    pathLength={100}
                    strokeDasharray={`${seg.share} ${100 - seg.share}`}
                    strokeDashoffset={-seg.startOffset}
                  >
                    <title>{`${seg.label} · ${seg.count} · ${seg.share.toFixed(1)}%`}</title>
                  </circle>
                ))}
              </svg>
              <strong id="versionTERate">
                {teSummary?.total ? `${teFilledPct.toFixed(1)}%` : "—"}
              </strong>
              <small id="versionTERatio">
                {teSummary ? `${teSummary.filled} / ${teSummary.total}` : "—"}
              </small>
            </div>

            <div className="te-status-legend" id="versionTEStatusChart">
              {teSummary &&
                dailyStatusRows(teSummary, lang).map(([key, label, count]) => (
                  <button
                    key={key}
                    type="button"
                    className={`te-legend-item${count === 0 ? " is-zero" : ""}`}
                    data-chart-key={key}
                    data-version-te-status={key}
                    aria-pressed={routeState.teStatus === key}
                    onClick={() =>
                      changeRoute({
                        teStatus: routeState.teStatus === key ? "all" : key,
                      })
                    }
                  >
                    <i className={`te-swatch te-${key}`} />
                    <span>{label}</span>
                    <strong>{count}</strong>
                  </button>
                ))}
            </div>
          </div>
        </section>

        <section className="page-card version-chart-card version-results">
          <div className="section-heading version-chart-heading">
            <h2>{bilingual(lang, "TE 结果分布", "TE results")}</h2>
            <small id="versionTEResultCount">
              {teSummary
                ? bilingual(
                    lang,
                    `${teSummary.filled} 条`,
                    `${teSummary.filled} ${teSummary.filled === 1 ? "result" : "results"}`,
                  )
                : ""}
            </small>
          </div>
          <div className="version-result-chart" id="versionTEDistribution" data-version-chart="">
            {te ? (
              sortedTeDistribution.length > 0 ? (
                sortedTeDistribution.map((r) => {
                  const share = teSummary?.filled ? (100 * r.count) / teSummary.filled : 0;
                  const label = versionTEResultLabel(r.value, lang);
                  return (
                    <div
                      key={r.value}
                      className="version-result-row"
                      tabIndex={0}
                      data-chart-key={r.value}
                      style={
                        {
                          "--te-result-color": versionLabelColor(r.value),
                        } as React.CSSProperties
                      }
                    >
                      <span title={label}>{label}</span>
                      <strong>
                        {r.count}
                        <small>{`${share.toFixed(1)}%`}</small>
                      </strong>
                      <span className="version-result-track" aria-hidden="true">
                        <i style={{ width: `${share}%` }} />
                      </span>
                    </div>
                  );
                })
              ) : (
                <p className="te-chart-empty">
                  {bilingual(lang, "暂无已标结果", "No filled results")}
                </p>
              )
            ) : null}
          </div>
        </section>

        <section
          className="page-card version-chart-card version-days"
          id="versionTEDays"
          hidden={Boolean(overview?.dataset.historical ?? isHistorical)}
        >
          <div className="section-heading version-chart-heading version-days-heading">
            <h2>
              {bilingual(lang, "每日进度", "Daily progress")}
              <small>{bilingual(lang, "已标 / 目标 · 发生日 CST", "Filled / targets · Occurred CST")}</small>
            </h2>
            <button
              type="button"
              className="button button-secondary version-dates-reset"
              id="versionTEAllDates"
              data-version-all-dates=""
              aria-pressed={!routeState.date}
              onClick={() => {
                if (routeState.date) changeRoute({ date: "" });
              }}
            >
              {bilingual(lang, "全部日期", "All dates")}
            </button>
          </div>
          <div className="te-daily-chart" id="versionTEDailyChart">
            {te ? (
              te.daily.length > 0 ? (
                te.daily.map((day) => {
                  const d = day.summary;
                  const aria = `${day.date} · ${bilingual(
                    lang,
                    `已标 ${d.filled}，目标 ${d.total}，待标 ${d.unfilled}，未知 ${d.unknown}`,
                    `Filled ${d.filled}, targets ${d.total}, pending ${d.unfilled}, unknown ${d.unknown}`,
                  )}`;
                  return (
                    <button
                      key={day.date}
                      type="button"
                      className="te-day"
                      data-version-date={day.date}
                      aria-pressed={day.date === routeState.date}
                      aria-label={aria}
                      onClick={() =>
                        changeRoute({
                          date: routeState.date === day.date ? "" : day.date,
                        })
                      }
                    >
                      <span className="version-day-date">
                        {day.date.slice(5).replace("-", "/")}
                      </span>
                      <span className="version-day-track" aria-hidden="true">
                        {dailyStatusRows(d, lang).map(([k, , count]) => (
                          <i
                            key={k}
                            className={`te-${k}`}
                            style={{ width: `${d.total ? (100 * count) / d.total : 0}%` }}
                          />
                        ))}
                      </span>
                      <strong>{`${d.filled}/${d.total}`}</strong>
                      <small>{d.total ? `${(100 * d.rate).toFixed(1)}%` : "—"}</small>
                    </button>
                  );
                })
              ) : (
                <p className="te-chart-empty">
                  {bilingual(lang, "暂无可用发生日", "No occurrence dates available")}
                </p>
              )
            ) : null}
          </div>
        </section>
      </div>

      <div
        id="versionRDPanel"
        className="version-rd"
        role="group"
        aria-label={bilingual(lang, "RD 标注概览", "RD annotation overview")}
        aria-busy={isLoading ? "true" : "false"}
      >
        {renderRdPanel()}
      </div>

      <section className="gallery-panel version-gallery">
        <header className="gallery-heading">
          <div className="section-heading version-gallery-heading">
            <h2>{bilingual(lang, "案例列表", "Cases")}</h2>
            <form
              id="versionDatasetSearchForm"
              onSubmit={(e) => {
                e.preventDefault();
                changeRoute({ query: searchDraft.trim() });
              }}
            >
              <input
                id="versionDatasetSearch"
                type="search"
                placeholder="Issue ID"
                aria-label="Issue ID"
                maxLength={128}
                value={searchDraft}
                onChange={(e) => setSearchDraft(e.target.value)}
              />
              <button className="button button-quiet" type="submit">
                {bilingual(lang, "搜索", "Search")}
              </button>
            </form>
          </div>

          <div className="version-gallery-filters">
            <div className="version-filter-field">
              <span>{bilingual(lang, "负责人", "Assignee")}</span>
              <UiSelect
                id="versionDatasetOwner"
                value={routeState.assignee}
                options={assigneeOptions}
                disabled={isHistorical}
                ariaLabel={bilingual(lang, "负责人", "Assignee")}
                onChange={(val) => changeRoute({ assignee: val })}
              />
            </div>

            <div className="version-filter-field">
              <span>{bilingual(lang, "联合复核", "Combined review")}</span>
              <UiSelect
                id="versionDatasetReviewStatus"
                value={routeState.reviewStatus}
                options={reviewStatusOptions}
                disabled={isHistorical}
                ariaLabel={bilingual(lang, "联合复核状态", "Combined review status")}
                onChange={(val) => changeRoute({ reviewStatus: val })}
              />
            </div>

            <div className="version-filter-field">
              <span>{bilingual(lang, "TE 状态", "TE status")}</span>
              <UiSelect
                id="versionDatasetTEStatus"
                value={routeState.teStatus}
                options={teStatusOptions}
                ariaLabel={bilingual(lang, "TE 状态", "TE status")}
                onChange={(val) => changeRoute({ teStatus: val })}
              />
            </div>

            <div className="version-filter-field">
              <span>{bilingual(lang, "媒体", "Media")}</span>
              <UiSelect
                id="versionDatasetMedia"
                value={routeState.media}
                options={mediaOptions}
                ariaLabel={bilingual(lang, "媒体", "Media")}
                onChange={(val) => changeRoute({ media: val })}
              />
            </div>

            <div className="version-filter-field">
              <span>{bilingual(lang, "排序", "Sort")}</span>
              <UiSelect
                id="versionDatasetSort"
                value={routeState.sort}
                options={sortOptions}
                ariaLabel={bilingual(lang, "案例排序", "Case order")}
                onChange={(val) => changeRoute({ sort: val })}
              />
            </div>

            <a
              className="button button-secondary"
              id="versionDatasetExport"
              hidden={!exportHref}
              href={exportHref || undefined}
            >
              {bilingual(lang, "导出 CSV", "Export CSV")}
            </a>
          </div>
        </header>

        <p id="versionDatasetError" className="muted" role="status">
          {hasError
            ? bilingual(
                lang,
                "读取失败，保留上次结果。可点击刷新重试。",
                "Read failed. Previous results retained; refresh to retry.",
              )
            : ""}
        </p>

        <div
          ref={gridRef}
          className="issue-grid"
          id="versionDatasetGrid"
          aria-busy={isLoading ? "true" : "false"}
        >
          {members && currentDataset ? (
            members.items.length > 0 ? (
              members.items.map((row) => {
                const binding = row.binding || {};
                const pred = row.prediction;
                const reviewUrl = binding.run_id
                  ? buildReviewCaseUrl(
                      row.issue_id,
                      binding.run_id,
                      binding.campaign_id || "",
                      currentDataset.release_family,
                    )
                  : "";
                const confidence = pred?.model_confidence;
                const occurred = row.issue_time || row.ra_start_timestamp;
                const time = occurred ? versionDatasetTime(occurred, lang) : row.date || "—";
                const owner =
                  binding.assignees?.join(", ") ||
                  binding.assignee ||
                  (currentDataset.historical ? "—" : bilingual(lang, "未分配", "Unassigned"));
                const joint =
                  row.is_target && !currentDataset.historical
                    ? row.reviewers && row.reviewers.length > 1
                      ? bilingual(
                          lang,
                          `复核 ${row.reviewers.filter((r) => r.submitted).length}/${row.reviewers.length}`,
                          `Reviewed ${row.reviewers.filter((r) => r.submitted).length}/${row.reviewers.length}`,
                        )
                      : row.review_submitted
                        ? bilingual(lang, "复核完成", "Review done")
                        : bilingual(lang, "待复核", "Review pending")
                    : "";
                const details = buildDetailsTooltip(row, lang);
                const model = pred?.model_label
                  ? versionTEResultLabel(pred.model_label, lang)
                  : currentDataset.historical
                    ? bilingual(lang, "历史固定集", "Frozen set")
                    : versionDatasetStatusLabel(row.state, lang);
                const thumbSrc = withWorkbenchBase(
                  `/api/case-thumbnails/${encodeURIComponent(row.issue_id)}?kind=${routeState.media}`,
                );
                const href =
                  reviewUrl ||
                  `https://voyager.intra.xiaojukeji.com/static/management/#/issue/${encodeURIComponent(
                    row.issue_id,
                  )}`;

                return (
                  <article key={`${row.issue_id}-${routeState.media}`} className="issue-card version-card">
                    <button
                      type="button"
                      className="issue-card-open"
                      data-version-open={row.issue_id}
                      title={details}
                      aria-label={`${row.issue_id} ${bilingual(lang, "查看媒体", "View media")}`}
                      onClick={() => void openVersionMedia(row)}
                    />
                    <div className="issue-thumbnail">
                      <div className="issue-thumbnail-placeholder">
                        <span>{routeState.media.toUpperCase()}</span>
                        <small>{bilingual(lang, "媒体待就绪", "Media pending")}</small>
                      </div>
                      {row.is_target && (
                        <img
                          data-src={thumbSrc}
                          loading="lazy"
                          decoding="async"
                          alt={`${row.issue_id} ${routeState.media.toUpperCase()}`}
                          className="is-loading"
                        />
                      )}
                    </div>
                    <div className="issue-card-body">
                      <div className="issue-card-heading">
                        <a
                          className="issue-id"
                          href={href}
                          target={reviewUrl ? undefined : "_blank"}
                          rel={reviewUrl ? undefined : "noopener noreferrer"}
                        >
                          {`${row.issue_id} ↗`}
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
                        <span title={model}>{model}</span>
                        <span className="muted">
                          {confidence == null ? "" : `${(confidence * 100).toFixed(1)}%`}
                        </span>
                      </div>
                      <div className="version-card-statuses">
                        <span className="version-te-result" data-status={row.te_status}>
                          {versionTEBadgeLabel(row, lang)}
                        </span>
                        {joint && (
                          <span
                            className="version-joint-result muted"
                            title={bilingual(
                              lang,
                              "平台联合复核，与 TE 分开统计",
                              "Platform combined review, tracked separately from TE",
                            )}
                          >
                            {joint}
                          </span>
                        )}
                      </div>
                      <div
                        className="version-card-meta muted"
                        title={details}
                        aria-label={details}
                      >
                        <span>{owner}</span>
                        <time>{`${time} CST`}</time>
                      </div>
                    </div>
                  </article>
                );
              })
            ) : (
              <div className="no-asset issue-grid-empty">
                {bilingual(lang, "该筛选暂无案例", "No cases in this view")}
              </div>
            )
          ) : null}
        </div>

        <Pagination
          page={currentPageMembers}
          pageSize={routeState.pageSize}
          total={totalMembers}
          lang={lang}
          loading={Boolean(isLoading || hasError || !members)}
          ariaLabel={bilingual(lang, "版本案例分页", "Version cases pagination")}
          labelText={
            members ? `${currentPageMembers} / ${totalPagesMembers} · ${totalMembers}` : ""
          }
          onPageChange={(nextPage) => changeRoute({ page: nextPage })}
          onPageSizeChange={(nextSize) => changeRoute({ pageSize: nextSize, page: 1 })}
        />
      </section>

      <details
        className="version-history"
        id="versionDatasetHistory"
        hidden={isHistorical}
        open={historyOpen}
        onToggle={(e) => setHistoryOpen((e.currentTarget as HTMLDetailsElement).open)}
      >
        <summary>{bilingual(lang, "导入记录 · CST", "Import history · CST")}</summary>
        <div id="versionDatasetBatches">
          {historyOpen &&
            (batchesQuery.isError ? (
              bilingual(lang, "记录读取失败", "History unavailable")
            ) : batchesQuery.data ? (
              batchesQuery.data.items.length > 0 ? (
                batchesQuery.data.items.map((x, idx) => (
                  <div key={idx}>
                    <time>{`${versionDatasetTime(x.created_at, lang)} CST`}</time>
                    {` · ${bilingual(lang, "新增目标", "Targets added")} ${x.target_added || 0} · ${bilingual(
                      lang,
                      "候选",
                      "Candidates",
                    )} +${x.added} · ${bilingual(lang, "更新", "Updated")} ${x.changed}`}
                  </div>
                ))
              ) : (
                bilingual(lang, "暂无记录", "No records")
              )
            ) : null)}
        </div>
      </details>
    </div>
  );
};
