import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, UiLanguage, withWorkbenchBase } from "../bridge/useWorkbenchBridge";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

export const VM_SCHEMES = [
  "model",
  "chain",
  "model_human_sim",
  "chain_human_sim",
  "chain_post_human_sim",
] as const;
export type VmSchemeKey = (typeof VM_SCHEMES)[number];

export const VM_DEFAULT_SCHEMES: readonly VmSchemeKey[] = ["chain", "chain_post_human_sim"];

export const VM_COLORS: Record<VmSchemeKey, string> = {
  model: "var(--chart-blue)",
  chain: "var(--chart-teal)",
  model_human_sim: "var(--chart-slate)",
  chain_human_sim: "var(--chart-indigo)",
  chain_post_human_sim: "var(--accent)",
};

export const VM_METRICS = [
  "accuracy",
  "macro_f1",
  "recall_correct",
  "recall_false",
  "recall_no_assist",
  "human_share",
] as const;
export type VmMetricKey = (typeof VM_METRICS)[number];

export const VM_REFERENCES = ["release", "te", "rd", "te_prime", "arbitrated"] as const;
export type VmReferenceKey = (typeof VM_REFERENCES)[number];

export const VM_EXCLUSIONS = ["all", "exclude"] as const;
export type VmExclusionKey = (typeof VM_EXCLUSIONS)[number];

export const VM_THRESHOLDS = [0.9, 0.85, 0.8, 0.76, 0.75, 0.7, 0.65] as const;

export const VM_REPORT_IDS: Record<string, string> = {
  "20261009": "2210331546058",
  "20261016": "2210331433301",
  "20261023": "2210462491274",
  "20261030": "2210502394530",
};

export interface VmPerClassMetric {
  label: string;
  tp: number;
  support: number;
  recall?: number | null;
}

export interface VmSchemeMetrics {
  accuracy?: number | null;
  macro_f1?: number | null;
  correct: number;
  total: number;
  reference_total: number;
  human_count: number;
  per_class: VmPerClassMetric[];
}

export interface VmLaneCoverage {
  filled: number;
  total: number;
  observed: number;
}

export interface VmThresholdRow {
  threshold: number;
  full_low: number;
  full_total: number;
  reduction: string | number;
  human_count: number;
  total: number;
  accuracy?: number | null;
  correct: number;
}

export interface VmItemRow {
  family: string;
  status: string;
  reason?: string | null;
  report_id?: string | null;
  observed_at?: string | null;
  started_at?: string | null;
  last_checked_at?: string | null;
  valid_total: number;
  sample_total: number;
  current_sample_total?: number | null;
  published_total?: number;
  membership_changed?: boolean;
  reference_lanes?: string[] | null;
  reference_counts?: Record<string, number> | null;
  metrics?: Partial<Record<VmSchemeKey, VmSchemeMetrics | null>> | null;
  coverage?: {
    te?: VmLaneCoverage | null;
    rd?: VmLaneCoverage | null;
  } | null;
  thresholds?: VmThresholdRow[] | null;
}

export interface VmCatalogItem {
  family: string;
}

export interface VmRefreshInfo {
  status?: string;
  completed?: number;
  total?: number;
}

export interface VersionMetricsPayload {
  catalog: VmCatalogItem[];
  selected: string[];
  items: VmItemRow[];
  refresh?: VmRefreshInfo | null;
}

export interface VmRouteState {
  families: string;
  metric: VmMetricKey;
  reference: VmReferenceKey;
  exclusion: VmExclusionKey;
  threshold: number;
  schemes: VmSchemeKey[];
  thresholdFamily: string;
  thresholdExpanded: boolean;
}

export interface VmPointLabel {
  key: VmSchemeKey;
  keys: VmSchemeKey[];
  value: number;
  y: number;
}

export interface VmChartGeometry {
  width: number;
  height: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
  plotW: number;
  plotH: number;
  scale: { domain: [number, number]; ticks: number[] };
  x: (i: number) => number;
  y: (value: number) => number;
}

function vmLocale(lang: UiLanguage): string {
  return lang === "en" ? "en-US" : "zh-CN";
}

export function vmSchemeLabel(key: VmSchemeKey, lang: UiLanguage): string {
  const map: Record<VmSchemeKey, string> = {
    model: bilingual(lang, "纯模型", "Model"),
    chain: bilingual(lang, "模型＋规则", "Model + rules"),
    model_human_sim: bilingual(lang, "模型＋人工（模拟）", "Model + review (simulated)"),
    chain_human_sim: bilingual(
      lang,
      "模型＋规则＋人工（模拟）",
      "Model + rules + review (simulated)",
    ),
    chain_post_human_sim: bilingual(
      lang,
      "模型＋规则＋规则后人工（模拟）",
      "Model + rules + post-rule review (simulated)",
    ),
  };
  return map[key] || key;
}

export function vmSchemeShortLabel(key: VmSchemeKey, lang: UiLanguage): string {
  const map: Record<VmSchemeKey, string> = {
    model: bilingual(lang, "纯模型", "Model"),
    chain: bilingual(lang, "模型＋规则", "Model + rules"),
    model_human_sim: bilingual(lang, "模型＋人工", "Model + review"),
    chain_human_sim: bilingual(lang, "模型＋规则＋人工", "Model + rules + review"),
    chain_post_human_sim: bilingual(lang, "规则后人工", "Post-rule review"),
  };
  return map[key] || key;
}

export function vmMetricLabel(key: VmMetricKey, lang: UiLanguage): string {
  const map: Record<VmMetricKey, string> = {
    accuracy: bilingual(lang, "准确率 ACC", "Accuracy ACC"),
    macro_f1: "Macro-F1",
    recall_correct: bilingual(lang, "正确触发召回率", "Correct-trigger recall"),
    recall_false: bilingual(lang, "误触发召回率", "False-trigger recall"),
    recall_no_assist: bilingual(lang, "无需协助召回率", "No-assistance recall"),
    human_share: bilingual(lang, "人工介入比例（模拟）", "Human intervention (simulated)"),
  };
  return map[key] || key;
}

export function vmReferenceLabel(reference: VmReferenceKey, lang: UiLanguage): string {
  const map: Record<VmReferenceKey, string> = {
    release: bilingual(lang, "按版本取人工 GT", "Release-specific human GT"),
    te: bilingual(lang, "TE 原始标注", "Original TE"),
    rd: bilingual(lang, "RD 标注", "RD labels"),
    te_prime: bilingual(lang, "TE′ 人工标注", "Manual TE′"),
    arbitrated: bilingual(lang, "裁决结果", "Adjudication"),
  };
  return map[reference] || reference;
}

export function vmReferenceCounts(row: VmItemRow, lang: UiLanguage): string {
  const names: Record<string, string> = {
    arbitrated: bilingual(lang, "复核", "Adjudication"),
    te_prime: "TE′",
    te: "TE",
    rd: "RD",
  };
  const counts = row.reference_counts || {};
  return (row.reference_lanes || [])
    .map((lane) => `${names[lane] || lane} ${counts[lane] ?? 0}`)
    .join(" · ");
}

export function vmPct(
  value: number | null | undefined,
  lang: UiLanguage,
  digits = 2,
): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(vmLocale(lang), {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

export function vmTime(value: string | number | Date | null | undefined, lang: UiLanguage): string {
  if (!value) return "—";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(vmLocale(lang), {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function vmFamilyLabel(family: string): string {
  return `${family.slice(4, 6)}-${family.slice(6)}`;
}

export function vmClassForMetric(metric: VmMetricKey): string | undefined {
  const map: Partial<Record<VmMetricKey, string>> = {
    recall_correct: "正确触发",
    recall_false: "误触发",
    recall_no_assist: "无需协助",
  };
  return map[metric];
}

export function vmValue(
  row: VmItemRow,
  key: VmSchemeKey,
  metric: VmMetricKey,
): number | null {
  const m = row.metrics?.[key];
  if (!m) return null;
  if (metric === "human_share") return m.total ? m.human_count / m.total : null;
  const label = vmClassForMetric(metric);
  if (label) {
    const found = m.per_class?.find((c) => c.label === label);
    return found?.recall ?? null;
  }
  const raw = metric === "accuracy" ? m.accuracy : metric === "macro_f1" ? m.macro_f1 : null;
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

export function vmPercentageScale(
  rows: VmItemRow[],
  keys: readonly VmSchemeKey[],
  metric: VmMetricKey,
): { domain: [number, number]; ticks: number[] } {
  const values = rows
    .flatMap((row) => keys.map((key) => vmValue(row, key, metric)))
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v))
    .map((v) => v * 100);
  if (!values.length) return { domain: [0, 100], ticks: [0, 25, 50, 75, 100] };
  const min = Math.max(0, Math.floor(Math.min(...values) + 1e-9));
  const max = Math.min(100, Math.ceil(Math.max(...values) - 1e-9));
  const step = Math.max(1, Math.ceil((max - min) / 4));
  const lower = Math.max(0, Math.min(min, 100 - step * 4));
  return {
    domain: [lower, lower + step * 4],
    ticks: Array.from({ length: 5 }, (_, i) => lower + i * step),
  };
}

export function vmPointLabels(
  row: VmItemRow,
  keys: readonly VmSchemeKey[],
  metric: VmMetricKey,
  y: (value: number) => number,
): VmPointLabel[] {
  const labels: Array<{ key: VmSchemeKey; keys: VmSchemeKey[]; value: number }> = [];
  for (const key of keys) {
    const value = vmValue(row, key, metric);
    if (value == null || !Number.isFinite(value)) continue;
    const same = labels.find((p) => p.value === value);
    if (same) same.keys.push(key);
    else labels.push({ key, keys: [key], value });
  }
  labels.sort((a, b) => a.value - b.value);
  let previous = Infinity;
  return labels.map((point) => {
    const baseline = Math.min(y(point.value) - 12, previous - 18);
    previous = baseline;
    return { ...point, y: baseline };
  });
}

export function vmChartGeometry(
  rows: VmItemRow[],
  keys: readonly VmSchemeKey[],
  metric: VmMetricKey,
  containerWidth: number,
): VmChartGeometry {
  const scale = vmPercentageScale(rows, keys, metric);
  const width = Math.max(containerWidth || 0, 680, rows.length * 70 + 128);
  const height = 288;
  const left = 52;
  const right = 76;
  const bottom = 34;
  const plotW = width - left - right;
  let top = 28;
  const x = (i: number) => left + ((i + 0.5) * plotW) / Math.max(1, rows.length);
  const y = (value: number) =>
    top +
    ((scale.domain[1] - value * 100) / (scale.domain[1] - scale.domain[0])) *
      (height - top - bottom);
  for (let pass = 0; pass < 3; pass += 1) {
    const pointYs = rows.flatMap((row) => vmPointLabels(row, keys, metric, y).map((p) => p.y));
    const minY = pointYs.length ? Math.min(...pointYs) : 14;
    if (minY >= 14) break;
    top += 14 - minY + 4;
  }
  return {
    width,
    height,
    left,
    right,
    top,
    bottom,
    plotW,
    plotH: height - top - bottom,
    scale,
    x,
    y,
  };
}

export function vmSampleChange(row: VmItemRow, lang: UiLanguage): string {
  if (
    !Number.isInteger(row.current_sample_total) ||
    row.current_sample_total === row.sample_total
  ) {
    return "";
  }
  return bilingual(
    lang,
    `当前抽样 ${row.current_sample_total}`,
    `Current sample ${row.current_sample_total}`,
  );
}

export function vmFreshnessSummary(
  rows: VmItemRow[],
  lang: UiLanguage,
): { label: string; title: string } {
  const times = rows
    .filter((row) => row.status === "ready")
    .map((row) => new Date(row.observed_at || ""))
    .filter((date) => Number.isFinite(date.getTime()))
    .sort((a, b) => a.getTime() - b.getTime());
  if (!times.length) {
    return {
      label: bilingual(lang, "Trail · 待采集", "Trail · Not collected"),
      title: bilingual(
        lang,
        "点击更新指标，读取新的 Trail 快照",
        "Update metrics to collect a new Trail snapshot",
      ),
    };
  }
  const oldest = vmTime(times[0], lang);
  const newest = vmTime(times[times.length - 1], lang);
  return {
    label: `${bilingual(lang, "最早快照", "Oldest snapshot")} · ${oldest}`,
    title: bilingual(
      lang,
      `所选版本最早／最新采集完成时间：${oldest} / ${newest} CST。版本调度会自动核对，也可手动更新。`,
      `Earliest / latest completed collection: ${oldest} / ${newest} CST. The version scheduler checks automatically. A manual refresh is also available.`,
    ),
  };
}

export function readVmRouteState(search: string = typeof window !== "undefined" ? window.location.search : ""): VmRouteState {
  const p = new URLSearchParams(search);
  const families = p.get("families") || "";
  const rawMetric = p.get("metric") || "";
  const metric: VmMetricKey = (VM_METRICS as readonly string[]).includes(rawMetric)
    ? (rawMetric as VmMetricKey)
    : "accuracy";
  const rawRef = p.get("reference") || "";
  const reference: VmReferenceKey = (VM_REFERENCES as readonly string[]).includes(rawRef)
    ? (rawRef as VmReferenceKey)
    : "release";
  const exclusion: VmExclusionKey = p.get("exclusion") === "exclude" ? "exclude" : "all";
  const rawThreshold = Number(p.get("threshold") || 0.9);
  const threshold = (VM_THRESHOLDS as readonly number[]).includes(rawThreshold)
    ? rawThreshold
    : 0.9;
  const schemes: VmSchemeKey[] = p.has("schemes")
    ? VM_SCHEMES.filter((k) => (p.get("schemes") || "").split(",").includes(k))
    : p.get("expanded") === "1"
      ? [...VM_SCHEMES]
      : [...VM_DEFAULT_SCHEMES];
  const thresholdFamily = p.get("threshold_family") || "";
  const thresholdExpanded = p.get("threshold_open") === "1";
  return {
    families,
    metric,
    reference,
    exclusion,
    threshold,
    schemes,
    thresholdFamily,
    thresholdExpanded,
  };
}

function writeVmRouteState(next: VmRouteState, mode: "push" | "replace" = "replace") {
  if (typeof window === "undefined") return;
  const url = new URL(withWorkbenchBase("/version-metrics"), window.location.origin);
  const entries: Record<string, string | number> = {
    families: next.families,
    metric: next.metric,
    schemes: next.schemes.join(",") || "none",
    reference: next.reference,
    exclusion: next.exclusion,
    threshold: next.threshold,
    threshold_family: next.thresholdFamily,
    threshold_open: next.thresholdExpanded ? "1" : "",
  };
  for (const [key, value] of Object.entries(entries)) {
    if (value !== "") url.searchParams.set(key, String(value));
  }
  if (mode === "push") {
    window.history.pushState({ page: "version-metrics" }, "", url);
  } else {
    window.history.replaceState({ page: "version-metrics" }, "", url);
  }
}

function getScoreCounts(row: VmItemRow, key: VmSchemeKey, metric: VmMetricKey): string {
  const m = row.metrics?.[key];
  if (!m) return "";
  const label = vmClassForMetric(metric);
  const klass = label ? m.per_class?.find((item) => item.label === label) : null;
  if (metric === "accuracy") return `${m.correct}/${m.total}`;
  if (klass) return `${klass.tp}/${klass.support}`;
  if (metric === "human_share") return `${m.human_count}/${m.total}`;
  return `n=${m.total}`;
}

export interface VersionMetricsPageProps {
  active: boolean;
  lang: UiLanguage;
  canWrite: boolean;
}

interface TooltipState {
  family: string;
  xCoord: number;
  left: number;
  top: number;
}

export const VersionMetricsPage: React.FC<VersionMetricsPageProps> = ({
  active,
  lang,
  canWrite,
}) => {
  const queryClient = useQueryClient();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const chartScrollRef = useRef<HTMLDivElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);

  const [routeState, setRouteState] = useState<VmRouteState>(() => readVmRouteState());
  const [catalogCache, setCatalogCache] = useState<VmCatalogItem[]>([]);
  const [refreshError, setRefreshError] = useState(false);
  const [chartWidth, setChartWidth] = useState(0);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const activeAnchorRef = useRef<{ family: string; clientY: number | null; el: SVGGElement } | null>(
    null,
  );

  // Re-read URL query parameters on activation, workbench sync, or browser popstate
  useEffect(() => {
    if (!active) {
      setTooltip(null);
      activeAnchorRef.current = null;
      return;
    }
    const syncFromLocation = () => {
      const next = readVmRouteState(window.location.search);
      setRouteState((prev) =>
        JSON.stringify(prev) === JSON.stringify(next) ? prev : next,
      );
    };
    syncFromLocation();
    window.addEventListener("popstate", syncFromLocation);
    window.addEventListener("ra:workbench-sync", syncFromLocation);
    return () => {
      window.removeEventListener("popstate", syncFromLocation);
      window.removeEventListener("ra:workbench-sync", syncFromLocation);
    };
  }, [active]);

  // Bind shared classic info popovers (`bindUiInfoPopovers` / `closeUiInfoPopovers`)
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

  // Measure `#vmChart` container width responsively via ResizeObserver
  useLayoutEffect(() => {
    if (!active) return;
    const host = chartScrollRef.current;
    if (!host) return;
    const measure = () => {
      const w = Math.round(host.clientWidth);
      setChartWidth((prev) => (prev === w ? prev : w));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    let lastWidth = Math.round(host.clientWidth);
    const observer = new ResizeObserver((entries) => {
      const next = Math.round(entries[0]?.contentRect.width || 0);
      if (next !== lastWidth) {
        lastWidth = next;
        setTooltip(null);
        activeAnchorRef.current = null;
        setChartWidth(next);
      }
    });
    observer.observe(host);
    return () => observer.disconnect();
  }, [active]);

  // Hide floating tooltip on window/chart scroll or Escape
  useEffect(() => {
    if (!active) return;
    const hide = () => {
      setTooltip(null);
      activeAnchorRef.current = null;
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") hide();
    };
    const host = chartScrollRef.current;
    window.addEventListener("scroll", hide, { passive: true });
    window.addEventListener("keydown", onKeyDown);
    host?.addEventListener("scroll", hide, { passive: true });
    return () => {
      window.removeEventListener("scroll", hide);
      window.removeEventListener("keydown", onKeyDown);
      host?.removeEventListener("scroll", hide);
    };
  }, [active]);

  const metricsQuery = useQuery<VersionMetricsPayload>({
    queryKey: [
      "version-metrics",
      routeState.families,
      routeState.reference,
      routeState.exclusion,
      routeState.threshold,
    ],
    queryFn: ({ signal }) => {
      const query = new URLSearchParams({
        families: routeState.families,
        reference: routeState.reference,
        exclusion: routeState.exclusion,
        threshold: String(routeState.threshold),
      });
      return apiRequest<VersionMetricsPayload>(`/api/version-metrics?${query.toString()}`, {
        signal,
      });
    },
    enabled: active,
    staleTime: 10_000,
    refetchInterval: (query) => {
      if (!active) return false;
      return query.state.data?.refresh?.status === "running" ? 5000 : 60000;
    },
  });

  const data = metricsQuery.data || null;
  const rows = useMemo(() => data?.items || [], [data]);
  const catalog = data?.catalog?.length ? data.catalog : catalogCache;

  // Reconcile thresholdFamily after data arrives (classic `vmReconcileReports`)
  useEffect(() => {
    if (!active || !data) return;
    if (Array.isArray(data.catalog) && data.catalog.length) {
      setCatalogCache(data.catalog);
    }
    setRouteState((prev) => {
      const sortedDesc = [...(data.items || [])].sort((a, b) =>
        b.family.localeCompare(a.family),
      );
      const nextThresholdFamily = (data.items || []).some(
        (r) => r.family === prev.thresholdFamily,
      )
        ? prev.thresholdFamily
        : sortedDesc[0]?.family || "";
      const reconciled: VmRouteState = {
        ...prev,
        thresholdFamily: nextThresholdFamily,
      };
      writeVmRouteState(reconciled, "replace");
      if (JSON.stringify(reconciled) === JSON.stringify(prev)) return prev;
      return reconciled;
    });
  }, [active, data]);

  const updateRoute = useCallback(
    (patch: Partial<VmRouteState>, options: { local?: boolean } = {}) => {
      setRefreshError(false);
      setTooltip(null);
      activeAnchorRef.current = null;
      setRouteState((prev) => {
        const merged: VmRouteState = {
          ...prev,
          ...patch,
        };
        if (options.local && data?.items) {
          if (!data.items.some((r) => r.family === merged.thresholdFamily)) {
            merged.thresholdFamily =
              [...data.items].sort((a, b) => b.family.localeCompare(a.family))[0]?.family || "";
          }
        }
        writeVmRouteState(merged, "push");
        return merged;
      });
    },
    [data],
  );

  const toggleScheme = useCallback(
    (key: VmSchemeKey) => {
      const selected = new Set(routeState.schemes);
      if (selected.has(key)) selected.delete(key);
      else selected.add(key);
      updateRoute(
        { schemes: VM_SCHEMES.filter((value) => selected.has(value)) },
        { local: true },
      );
    },
    [routeState.schemes, updateRoute],
  );

  const refreshMutation = useMutation({
    mutationFn: (families: string[]) =>
      apiRequest("/api/version-metrics/refresh", {
        method: "POST",
        body: { families },
      }),
    onMutate: () => {
      setRefreshError(false);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["version-metrics"] });
    },
    onError: () => {
      setRefreshError(true);
    },
  });

  const loading = metricsQuery.isPending || (metricsQuery.isFetching && !data);
  const loadError = metricsQuery.isError;
  const errorKind: "" | "load_failed" | "refresh_not_started" = refreshError
    ? "refresh_not_started"
    : loadError
      ? "load_failed"
      : "";

  const refreshJob = data?.refresh;
  const isUpdatingJob = refreshJob?.status === "running";
  const statusText = isUpdatingJob
    ? bilingual(
        lang,
        `正在更新 ${refreshJob?.completed ?? 0}/${refreshJob?.total ?? 0} 个版本`,
        `Updating ${refreshJob?.completed ?? 0}/${refreshJob?.total ?? 0} versions`,
      )
    : refreshJob?.status === "failed" || refreshJob?.status === "interrupted"
      ? bilingual(
          lang,
          "更新未完成，保留上次快照",
          "Refresh incomplete; previous snapshots retained",
        )
      : loading
        ? bilingual(lang, "读取中…", "Loading…")
        : "";

  const versionPickerOptions: MultiSelectOption[] = useMemo(
    () => catalog.map((d) => ({ value: d.family, label: d.family.slice(4) })),
    [catalog],
  );
  const selectedFamilyValues = useMemo(
    () =>
      routeState.families === "all"
        ? []
        : routeState.families
          ? routeState.families.split(",").filter(Boolean)
          : data?.selected || [],
    [routeState.families, data?.selected],
  );

  const metricOptions: UiSelectOption[] = useMemo(
    () => VM_METRICS.map((k) => ({ value: k, label: vmMetricLabel(k, lang) })),
    [lang],
  );
  const referenceOptions: UiSelectOption[] = useMemo(
    () => VM_REFERENCES.map((k) => ({ value: k, label: vmReferenceLabel(k, lang) })),
    [lang],
  );
  const exclusionOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "all", label: bilingual(lang, "全部三分类有效", "All valid samples") },
      { value: "exclude", label: bilingual(lang, "剔除人工排除项", "Remove manual exclusions") },
    ],
    [lang],
  );
  const thresholdOptions: UiSelectOption[] = useMemo(
    () => VM_THRESHOLDS.map((t) => ({ value: t.toFixed(2), label: t.toFixed(2) })),
    [],
  );

  const freshness = useMemo(() => vmFreshnessSummary(rows, lang), [rows, lang]);
  const reportRows = useMemo(() => [...rows].reverse(), [rows]);
  const sortedDescRows = useMemo(
    () => [...rows].sort((a, b) => b.family.localeCompare(a.family)),
    [rows],
  );
  const thresholdFamilyOptions: UiSelectOption[] = useMemo(
    () =>
      sortedDescRows.map((row) => ({
        value: row.family,
        label: row.family,
      })),
    [sortedDescRows],
  );
  const activeThresholdFamily =
    sortedDescRows.find((r) => r.family === routeState.thresholdFamily)?.family ||
    sortedDescRows[0]?.family ||
    "";
  const activeThresholdRow = sortedDescRows.find((r) => r.family === activeThresholdFamily);
  const thresholdAvailable = activeThresholdRow?.status === "ready";

  const hasChartPoints = useMemo(
    () =>
      rows.some((row) =>
        routeState.schemes.some((key) => vmValue(row, key, routeState.metric) != null),
      ),
    [rows, routeState.schemes, routeState.metric],
  );

  const geometry = useMemo(() => {
    if (errorKind === "load_failed" || !rows.length || !routeState.schemes.length || !hasChartPoints) {
      return null;
    }
    return vmChartGeometry(rows, routeState.schemes, routeState.metric, chartWidth);
  }, [errorKind, rows, routeState.schemes, routeState.metric, hasChartPoints, chartWidth]);

  const positionTooltip = useCallback(
    (family: string, clientY: number | null, anchor: SVGGElement) => {
      const host = chartScrollRef.current;
      if (!host) return;
      const xCoord = Number(anchor.dataset.vmX || 0);
      activeAnchorRef.current = { family, clientY, el: anchor };
      const rect = anchor.getBoundingClientRect();
      const bounds = host.getBoundingClientRect();
      const tipBox = tooltipRef.current?.getBoundingClientRect();
      const tipW = tipBox && tipBox.width > 0 ? tipBox.width : 240;
      const tipH = tipBox && tipBox.height > 0 ? tipBox.height : 120;
      const px = rect.x + rect.width / 2;
      const py = clientY ?? bounds.top + 28;
      const rightBound = Math.min(window.innerWidth - 8, bounds.right);
      let tipX = px + 40;
      let tipY = Math.max(
        8,
        Math.min(
          Math.max(bounds.top, py + 12),
          bounds.bottom - tipH,
          window.innerHeight - tipH - 8,
        ),
      );
      if (tipX + tipW > rightBound) tipX = px - 40 - tipW;
      if (tipX < 8) {
        tipX = Math.max(8, Math.min(px - tipW / 2, window.innerWidth - tipW - 8));
        tipY = Math.max(8, bounds.top - tipH - 8);
      }
      const clampedX = Math.max(8, Math.min(tipX, window.innerWidth - tipW - 8));
      setTooltip({ family, xCoord, left: clampedX, top: tipY });
    },
    [],
  );

  // Refine tooltip position once rendered with real bounding box height/width
  useLayoutEffect(() => {
    if (!tooltip || !activeAnchorRef.current || !tooltipRef.current || !chartScrollRef.current) {
      return;
    }
    const { clientY, el } = activeAnchorRef.current;
    const host = chartScrollRef.current;
    const box = tooltipRef.current.getBoundingClientRect();
    if (!box.width || !box.height) return;
    const rect = el.getBoundingClientRect();
    const bounds = host.getBoundingClientRect();
    const px = rect.x + rect.width / 2;
    const py = clientY ?? bounds.top + 28;
    const rightBound = Math.min(window.innerWidth - 8, bounds.right);
    let tipX = px + 40;
    let tipY = Math.max(
      8,
      Math.min(
        Math.max(bounds.top, py + 12),
        bounds.bottom - box.height,
        window.innerHeight - box.height - 8,
      ),
    );
    if (tipX + box.width > rightBound) tipX = px - 40 - box.width;
    if (tipX < 8) {
      tipX = Math.max(8, Math.min(px - box.width / 2, window.innerWidth - box.width - 8));
      tipY = Math.max(8, bounds.top - box.height - 8);
    }
    const clampedX = Math.max(8, Math.min(tipX, window.innerWidth - box.width - 8));
    if (Math.abs(clampedX - tooltip.left) > 1 || Math.abs(tipY - tooltip.top) > 1) {
      setTooltip((prev) => (prev ? { ...prev, left: clampedX, top: tipY } : null));
    }
  }, [tooltip?.family]);

  const hideTooltip = useCallback(() => {
    setTooltip(null);
    activeAnchorRef.current = null;
  }, []);

  const tooltipRow = tooltip ? rows.find((r) => r.family === tooltip.family) || null : null;

  const busyReport = loading || Boolean(loadError);
  const reportEmptyMsg = loadError
    ? bilingual(lang, "指标读取失败，请重试", "Metrics unavailable. Please retry.")
    : loading
      ? bilingual(lang, "正在读取指标…", "Loading metrics…")
      : bilingual(lang, "暂无版本数据", "No release data");

  const yearsSet = useMemo(() => new Set(rows.map((r) => r.family.slice(0, 4))), [rows]);
  const xTickInterval = Math.max(1, Math.ceil(rows.length / 12));

  const readyRows = useMemo(() => rows.filter((r) => r.status === "ready"), [rows]);

  const renderCoverageCell = (row: VmItemRow, lane: "te" | "rd") => {
    const coverage = row.coverage?.[lane];
    if (!coverage) return <span>—</span>;
    const known = bilingual(
      lang,
      `已观测 ${coverage.observed}/${coverage.total}；已标包含 OOS 和未接起`,
      `Observed ${coverage.observed}/${coverage.total}; filled includes OOS and unanswered`,
    );
    if (!coverage.observed && coverage.total) {
      return <span title={known}>{bilingual(lang, "未知", "Unknown")}</span>;
    }
    return (
      <span className="vm-cell-stack" title={known}>
        {coverage.total ? (
          <>
            <strong>
              {coverage.filled}/{coverage.total}
            </strong>
            <small>{vmPct(coverage.filled / coverage.total, lang)}</small>
          </>
        ) : (
          <span>—</span>
        )}
      </span>
    );
  };

  const renderScoreCell = (row: VmItemRow, key: VmSchemeKey) => {
    const m = row.metrics?.[key];
    const value = vmValue(row, key, routeState.metric);
    if (!m) return <span>—</span>;
    const counts = getScoreCounts(row, key, routeState.metric);
    const coverageTitle = bilingual(
      lang,
      `模型输出覆盖 ${m.total}/${m.reference_total}`,
      `Output coverage ${m.total}/${m.reference_total}`,
    );
    return (
      <>
        <strong title={coverageTitle}>{vmPct(value, lang)}</strong>
        <small>{counts}</small>
      </>
    );
  };

  const renderCountRate = (count: number, total: number) => {
    if (!total) return <span>—</span>;
    return (
      <>
        <strong>
          {count}/{total}
        </strong>
        <small>{vmPct(count / total, lang)}</small>
      </>
    );
  };

  const refreshDisabled =
    loading || !data?.selected?.length || !canWrite || isUpdatingJob || refreshMutation.isPending;

  return (
    <div
      ref={rootRef}
      className="ra-version-metrics-root"
      data-react-island="version-metrics"
      onClick={(e) => {
        const target = e.target as HTMLElement | null;
        if (!target?.closest("[data-vm-family]")) {
          hideTooltip();
        }
      }}
    >
      <section className="page-card vm-chart-panel">
        <div className="vm-toolbar">
          <div className="vm-field">
            <label htmlFor="vmVersionPicker">{bilingual(lang, "版本", "Versions")}</label>
            <MultiSelect
              id="vmVersionPicker"
              values={selectedFamilyValues}
              options={versionPickerOptions}
              onChange={(values) =>
                updateRoute({ families: values.length ? values.join(",") : "all" })
              }
              ariaLabel={bilingual(lang, "评测版本", "Evaluation versions")}
              lang={lang}
              placeholder={bilingual(lang, "全部版本", "All versions")}
              allLabel={bilingual(lang, "全部版本", "All versions")}
              showOnlyThis
            />
          </div>

          <div className="vm-field">
            <label htmlFor="vmMetric">{bilingual(lang, "指标", "Metric")}</label>
            <UiSelect
              id="vmMetric"
              value={routeState.metric}
              options={metricOptions}
              ariaLabel={bilingual(lang, "指标", "Metric")}
              onChange={(val) => updateRoute({ metric: val as VmMetricKey }, { local: true })}
            />
          </div>
        </div>

        <div className="vm-scope-toolbar">
          <details className="vm-scope">
            <summary className="button button-quiet">
              {bilingual(lang, "更多筛选", "More filters")}
            </summary>
            <div className="vm-scope-filters">
              <div className="vm-field">
                <label htmlFor="vmReference">{bilingual(lang, "评测参考", "Reference")}</label>
                <UiSelect
                  id="vmReference"
                  value={routeState.reference}
                  options={referenceOptions}
                  ariaLabel={bilingual(lang, "评测参考", "Reference")}
                  onChange={(val) => updateRoute({ reference: val as VmReferenceKey })}
                />
              </div>
              <div className="vm-field">
                <label htmlFor="vmExclusion">{bilingual(lang, "排除口径", "Exclusions")}</label>
                <UiSelect
                  id="vmExclusion"
                  value={routeState.exclusion}
                  options={exclusionOptions}
                  ariaLabel={bilingual(lang, "排除口径", "Exclusions")}
                  onChange={(val) => updateRoute({ exclusion: val as VmExclusionKey })}
                />
              </div>
            </div>
            <button
              id="vmReset"
              type="button"
              className="button button-secondary"
              onClick={() =>
                updateRoute({
                  metric: "accuracy",
                  reference: "release",
                  exclusion: "all",
                  threshold: 0.9,
                  schemes: [...VM_DEFAULT_SCHEMES],
                  thresholdFamily: "",
                  thresholdExpanded: false,
                })
              }
            >
              {bilingual(lang, "重置选项", "Reset options")}
            </button>
          </details>

          <div className="vm-toolbar-actions">
            <button
              id="vmRefresh"
              className="button button-quiet"
              type="button"
              disabled={refreshDisabled}
              title={
                canWrite
                  ? bilingual(
                      lang,
                      "只读更新数据并保留历史快照",
                      "Read sources and retain snapshot history",
                    )
                  : bilingual(
                      lang,
                      "更新指标需要writer或管理员权限",
                      "Writer or admin access is required to refresh",
                    )
              }
              onClick={() => {
                if (!data?.selected?.length || !canWrite) return;
                refreshMutation.mutate(data.selected);
              }}
            >
              {bilingual(lang, "更新指标", "Update metrics")}
            </button>
          </div>
        </div>

        <div id="vmError" className="vm-error" role="alert" hidden={!errorKind}>
          <span id="vmErrorText">
            {errorKind === "refresh_not_started"
              ? bilingual(lang, "更新未启动，请稍后重试。", "Refresh did not start. Retry later.")
              : errorKind === "load_failed"
                ? bilingual(lang, "指标读取失败，请重试。", "Metrics could not be loaded. Please retry.")
                : ""}
          </span>
          <button
            id="vmRetry"
            type="button"
            className="button button-quiet"
            onClick={() => {
              setRefreshError(false);
              void metricsQuery.refetch();
            }}
          >
            {bilingual(lang, "重试", "Retry")}
          </button>
        </div>

        <span id="vmStatus" className="vm-job-status" role="status" hidden={!statusText}>
          {statusText}
        </span>

        <div className="vm-chart-heading">
          <div
            id="vmLegend"
            className="vm-legend"
            role="group"
            aria-label={bilingual(lang, "显示方案", "Visible schemes")}
          >
            {VM_SCHEMES.map((key) => {
              const pressed = routeState.schemes.includes(key);
              const fullLabel = vmSchemeLabel(key, lang);
              return (
                <button
                  key={key}
                  type="button"
                  className="button button-secondary vm-scheme-button"
                  data-vm-scheme={key}
                  style={{ "--vm-color": VM_COLORS[key] } as React.CSSProperties}
                  aria-pressed={pressed}
                  aria-label={fullLabel}
                  title={fullLabel}
                  onClick={() => toggleScheme(key)}
                >
                  <i className="vm-swatch" aria-hidden="true" />
                  {vmSchemeShortLabel(key, lang)}
                </button>
              );
            })}
          </div>

          <div className="vm-chart-meta">
            <span id="vmDataFreshness" title={freshness.title}>
              {freshness.label}
            </span>
            <div className="vm-chart-threshold">
              <label htmlFor="vmThreshold">
                {bilingual(lang, "人工模拟 conf <", "Simulated review conf <")}
              </label>
              <UiSelect
                id="vmThreshold"
                className="dashboard-native-ui-select"
                value={routeState.threshold.toFixed(2)}
                options={thresholdOptions}
                ariaLabel={bilingual(lang, "人工模拟 conf 阈值", "Simulated review conf threshold")}
                onChange={(val) => updateRoute({ threshold: Number(val) })}
              />
            </div>
            <span className="model-review-run-help ui-info" data-ui-info="">
              <button
                id="vmInfoButton"
                type="button"
                className="button button-secondary vm-info-button"
                data-ui-info-trigger=""
                aria-expanded="false"
                aria-controls="vmInfoTooltip"
                aria-label={bilingual(lang, "指标统计口径", "Metric definitions")}
              >
                ⓘ
              </button>
              <span id="vmInfoTooltip" className="model-review-run-tooltip ui-info-tooltip" role="tooltip">
                <strong>{bilingual(lang, "统计口径", "Metric definitions")}</strong>
                <span id="vmReferenceNote">
                  {bilingual(lang, "评测参考：", "Reference: ")}
                  {vmReferenceLabel(routeState.reference, lang)}
                  {" · "}
                  {routeState.exclusion === "exclude"
                    ? bilingual(lang, "剔除人工排除项", "Manual exclusions removed")
                    : bilingual(lang, "全部三分类有效", "All valid samples")}
                </span>
                <span>
                  {bilingual(
                    lang,
                    "来源：Trail 快照。点击更新指标重新采集；采集时间见下方，页面刷新读取最近快照。",
                    "Source: Trail snapshots. Update metrics to collect again; collection times are listed below. Page refresh reads the latest snapshot.",
                  )}
                </span>
                <span>
                  {bilingual(
                    lang,
                    "概率抽样集三分类有效项参与评分；OOS、未接起及缺失标注不计入。TE/RD 已标数量包含明确的 OOS、未接起。",
                    "Scores use valid three-class probability samples, excluding OOS, unanswered and missing labels. TE/RD filled counts include explicit OOS and unanswered labels.",
                  )}
                </span>
                <span>
                  {bilingual(
                    lang,
                    "人工方案以同一参考替代低置信输出，仅为流程模拟；conf 不改变线上配置。",
                    "Review schemes replace low-confidence outputs with the same reference as a simulation. The conf setting does not change production routing.",
                  )}
                </span>
                <span id="vmSchemeDefinitions">
                  {VM_SCHEMES.map((key, idx) => (
                    <React.Fragment key={key}>
                      {idx > 0 && <br />}
                      {`${vmSchemeShortLabel(key, lang)} → ${vmSchemeLabel(key, lang)}`}
                    </React.Fragment>
                  ))}
                </span>
                <span id="vmSnapshotInfo">
                  {readyRows.length
                    ? readyRows.map((row, idx) => (
                        <React.Fragment key={row.family}>
                          {idx > 0 && <br />}
                          {`${row.family} · ${bilingual(lang, "采集", "Collected")} ${vmTime(
                            row.started_at || row.observed_at,
                            lang,
                          )} – ${vmTime(row.observed_at, lang)} CST`}
                        </React.Fragment>
                      ))
                    : bilingual(lang, "暂无 Trail 快照", "No Trail snapshots")}
                </span>
              </span>
            </span>
          </div>
        </div>

        <p className="vm-scope-note" id="vmChartReference">
          {routeState.reference === "release"
            ? bilingual(
                lang,
                "11-06 起，GT 按复核 → TE′ → TE → RD 取值。此前版本使用 TE。",
                "From Nov 6, GT uses the first entry in this order: adjudication → TE′ → TE → RD. Earlier releases use TE.",
              )
            : `GT · ${vmReferenceLabel(routeState.reference, lang)}`}
        </p>

        <div
          ref={chartScrollRef}
          className="vm-chart-scroll"
          id="vmChart"
          onPointerLeave={hideTooltip}
        >
          {!geometry ? (
            <div className="vm-chart-empty">
              {errorKind === "load_failed"
                ? bilingual(lang, "暂时无法显示指标", "Metrics are unavailable")
                : loading
                  ? bilingual(lang, "正在读取指标…", "Loading metrics…")
                  : !routeState.schemes.length
                    ? bilingual(lang, "请选择要比较的方案", "Select schemes to compare")
                    : !rows.length
                      ? bilingual(
                          lang,
                          "暂无版本快照，请更新指标",
                          "No version snapshots. Update metrics to begin.",
                        )
                      : rows.some((row) => row.status === "ready")
                        ? bilingual(lang, "当前筛选暂无有效指标", "No valid metrics for the current filters")
                        : bilingual(lang, "暂无 Trail 快照，请更新指标", "No Trail snapshot. Update metrics.")}
            </div>
          ) : (
            <svg
              className="vm-trend-svg"
              width={geometry.width}
              height={geometry.height}
              viewBox={`0 0 ${geometry.width} ${geometry.height}`}
              role="group"
              aria-label={`${bilingual(lang, "跨版本", "Cross-version")} ${vmMetricLabel(
                routeState.metric,
                lang,
              )}`}
            >
              {geometry.scale.ticks.map((tick) => {
                const yPos = geometry.y(tick / 100);
                return (
                  <React.Fragment key={tick}>
                    <line
                      x1={geometry.left}
                      y1={yPos}
                      x2={geometry.width - geometry.right}
                      y2={yPos}
                      className="vm-grid-line"
                    />
                    <text
                      x={geometry.left - 10}
                      y={yPos + 4}
                      textAnchor="end"
                      className="vm-axis vm-y-axis"
                    >
                      {`${tick}%`}
                    </text>
                  </React.Fragment>
                );
              })}

              {routeState.schemes.map((key) => {
                let d = "";
                let open = false;
                for (let i = 0; i < rows.length; i += 1) {
                  const v = vmValue(rows[i], key, routeState.metric);
                  if (v == null) {
                    open = false;
                    continue;
                  }
                  d += `${open ? "L" : "M"}${geometry.x(i)},${geometry.y(v)} `;
                  open = true;
                }
                return (
                  <React.Fragment key={key}>
                    <path
                      className="vm-series-line"
                      d={d.trim()}
                      fill="none"
                      stroke={VM_COLORS[key]}
                      strokeWidth={2.5}
                    />
                    {rows.map((row, i) => {
                      const v = vmValue(row, key, routeState.metric);
                      if (v == null) return null;
                      const isActive = tooltip?.family === row.family;
                      return (
                        <circle
                          key={`${key}-${row.family}`}
                          className={`vm-point${isActive ? " is-active" : ""}`}
                          data-vm-dot={row.family}
                          cx={geometry.x(i)}
                          cy={geometry.y(v)}
                          r={3}
                          fill="var(--raised)"
                          stroke={VM_COLORS[key]}
                          strokeWidth={2}
                        />
                      );
                    })}
                  </React.Fragment>
                );
              })}

              <line
                className={`vm-cursor${tooltip ? " is-active" : ""}`}
                x1={tooltip ? tooltip.xCoord : 0}
                x2={tooltip ? tooltip.xCoord : 0}
                y1={geometry.top}
                y2={geometry.top + geometry.plotH}
                aria-hidden="true"
              />

              {rows.map((row, i) =>
                vmPointLabels(row, routeState.schemes, routeState.metric, geometry.y).map(
                  (point) => (
                    <text
                      key={`${row.family}-${point.key}`}
                      className="vm-value-label"
                      data-vm-label={point.key}
                      data-vm-point={row.family}
                      x={geometry.x(i)}
                      y={point.y}
                      textAnchor="middle"
                      aria-hidden="true"
                    >
                      {vmPct(point.value, lang, 1)}
                    </text>
                  ),
                ),
              )}

              {rows.map((row, i) => {
                const date = `${row.family.slice(4, 6)}-${row.family.slice(6)}`;
                const label = yearsSet.size > 1 ? `${row.family.slice(0, 4)}/${date}` : date;
                const hint = routeState.schemes
                  .map(
                    (k) =>
                      `${vmSchemeLabel(k, lang)} ${vmPct(
                        vmValue(row, k, routeState.metric),
                        lang,
                      )}`,
                  )
                  .join("; ");
                const colX = geometry.x(i);
                return (
                  <g
                    key={row.family}
                    data-vm-family={row.family}
                    data-vm-x={colX}
                    role="button"
                    tabIndex={0}
                    aria-label={`${row.family}; ${hint}`}
                    onPointerMove={(e) =>
                      positionTooltip(row.family, e.clientY, e.currentTarget)
                    }
                    onClick={(e) => {
                      e.stopPropagation();
                      positionTooltip(row.family, e.clientY, e.currentTarget);
                    }}
                    onFocus={(e) => positionTooltip(row.family, null, e.currentTarget)}
                    onBlur={hideTooltip}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        positionTooltip(row.family, null, e.currentTarget);
                      } else if (e.key === "Escape") {
                        hideTooltip();
                      }
                    }}
                  >
                    <rect
                      x={geometry.left + (i * geometry.plotW) / rows.length}
                      y={0}
                      width={geometry.plotW / rows.length}
                      height={geometry.height}
                      fill="transparent"
                    />
                    {i % xTickInterval === 0 && (
                      <text
                        className="vm-axis"
                        x={colX}
                        y={geometry.height - 12}
                        textAnchor="middle"
                      >
                        {label}
                      </text>
                    )}
                  </g>
                );
              })}
            </svg>
          )}
        </div>
      </section>

      <section className="page-card vm-report-panel" aria-labelledby="vmWorkloadTitle">
        {(() => {
          const byThreshold = routeState.thresholdExpanded;
          const workloadRows = busyReport ? [] : reportRows;
          const workloadScope = byThreshold
            ? workloadRows.filter((row) => row.family === activeThresholdFamily)
            : workloadRows;
          const baselineCounts = workloadScope.map((row) =>
            row.status === "ready"
              ? (row.thresholds?.find((t) => t.threshold === 0.9)?.full_low ?? null)
              : null,
          );
          const baselineComplete =
            baselineCounts.length > 0 &&
            baselineCounts.every((c): c is number => Number.isInteger(c));
          const baselineTotal = baselineComplete
            ? baselineCounts.reduce((sum, count) => sum + count, 0).toLocaleString(vmLocale(lang))
            : "—";
          const baselineLabel =
            workloadScope.length > 1
              ? bilingual(lang, "标注量合计", "total reviews")
              : bilingual(lang, "标注量", "reviews");
          const workloadBaselineText = `conf = 0.90 ${baselineLabel} ${baselineTotal}`;

          const renderRow = (
            rowKey: string,
            label: string,
            point: VmThresholdRow | undefined,
          ) => {
            if (!point) {
              return (
                <tr key={rowKey}>
                  <th scope="row">{label}</th>
                  <td colSpan={3} className="vm-table-empty">
                    {bilingual(lang, "暂无阈值数据", "No threshold data")}
                  </td>
                </tr>
              );
            }
            const reductionNum = Number(point.reduction);
            const baseline = Number(point.full_low) + reductionNum;
            const reductionRate =
              Number.isFinite(baseline) && baseline > 0
                ? vmPct(reductionNum / baseline, lang, 1)
                : "—";
            const selected = byThreshold && point.threshold === routeState.threshold;
            return (
              <tr
                key={rowKey}
                className={selected ? "is-selected" : undefined}
                aria-current={selected ? "true" : undefined}
              >
                <th scope="row">{label}</th>
                <td>
                  <strong>{`${point.full_low} / ${point.full_total}`}</strong>
                  {byThreshold && point.full_total ? (
                    <small>{vmPct(point.full_low / point.full_total, lang)}</small>
                  ) : null}
                </td>
                <td>
                  <strong>{point.reduction}</strong>
                  <small>{reductionRate}</small>
                </td>
                {byThreshold ? <td>{renderCountRate(point.human_count, point.total)}</td> : null}
                <td>
                  <strong>{vmPct(point.accuracy, lang)}</strong>
                  <small>{`${point.correct}/${point.total}`}</small>
                </td>
              </tr>
            );
          };

          return (
            <>
              <header className="vm-report-heading vm-workload-heading">
                <h2 id="vmWorkloadTitle">
                  {bilingual(lang, "低置信标注量", "Low-confidence review volume")}
                </h2>
                <div
                  className="segmented vm-workload-mode"
                  role="radiogroup"
                  aria-label={bilingual(lang, "比较方式", "Comparison mode")}
                >
                  <label>
                    <input
                      type="radio"
                      name="vmWorkloadMode"
                      value="release"
                      checked={!byThreshold}
                      onChange={() => updateRoute({ thresholdExpanded: false }, { local: true })}
                    />
                    <span>{bilingual(lang, "按版本", "By release")}</span>
                  </label>
                  <label>
                    <input
                      type="radio"
                      name="vmWorkloadMode"
                      value="threshold"
                      checked={byThreshold}
                      onChange={() => updateRoute({ thresholdExpanded: true }, { local: true })}
                    />
                    <span>{bilingual(lang, "按阈值", "By threshold")}</span>
                  </label>
                </div>
                <div id="vmWorkloadReleasePicker" hidden={!byThreshold}>
                  <UiSelect
                    id="vmThresholdFamily"
                    className="dashboard-native-ui-select"
                    value={activeThresholdFamily}
                    options={thresholdFamilyOptions}
                    disabled={busyReport || !sortedDescRows.length}
                    ariaLabel={bilingual(lang, "版本", "Release")}
                    onChange={(val) => updateRoute({ thresholdFamily: val }, { local: true })}
                  />
                </div>
                <div className="vm-workload-summary muted">
                  <strong id="vmWorkloadBaseline">{workloadBaselineText}</strong>
                  <span id="vmWorkloadThreshold">{`conf < ${routeState.threshold.toFixed(2)}`}</span>
                </div>
              </header>

              <div className="rd-table-wrap">
                <table className="rd-table vm-workload-table" aria-labelledby="vmWorkloadTitle">
                  <thead>
                    <tr>
                      <th scope="col" id="vmWorkloadDimension">
                        {byThreshold ? "conf" : bilingual(lang, "版本", "Release")}
                      </th>
                      <th scope="col">
                        {bilingual(lang, "需标注 / 已发布", "For review / published")}
                      </th>
                      <th scope="col">{bilingual(lang, "较 0.90 少标", "Fewer than at 0.90")}</th>
                      <th scope="col" id="vmWorkloadSampleHead" hidden={!byThreshold}>
                        {bilingual(lang, "抽样人工量", "Sample review count")}
                      </th>
                      <th scope="col">{bilingual(lang, "抽样模拟 ACC", "Simulated sample ACC")}</th>
                    </tr>
                  </thead>
                  <tbody id="vmWorkloadRows">
                    {!byThreshold
                      ? !workloadRows.length
                        ? (
                          <tr>
                            <td colSpan={4} className="vm-table-empty">
                              {reportEmptyMsg}
                            </td>
                          </tr>
                        )
                        : workloadRows.map((row) =>
                            renderRow(
                              row.family,
                              row.family,
                              row.status === "ready"
                                ? row.thresholds?.find((t) => t.threshold === routeState.threshold)
                                : undefined,
                            ),
                          )
                      : (() => {
                          const points =
                            !busyReport && thresholdAvailable
                              ? activeThresholdRow?.thresholds || []
                              : [];
                          if (!points.length) {
                            return (
                              <tr>
                                <td colSpan={5} className="vm-table-empty">
                                  {!busyReport && reportRows.length
                                    ? bilingual(
                                        lang,
                                        "当前版本暂无阈值数据",
                                        "No threshold data for this release",
                                      )
                                    : reportEmptyMsg}
                                </td>
                              </tr>
                            );
                          }
                          return points.map((t) =>
                            renderRow(String(t.threshold), t.threshold.toFixed(2), t),
                          );
                        })()}
                  </tbody>
                </table>
              </div>
            </>
          );
        })()}
      </section>

      <section className="page-card vm-report-panel">
        <header className="vm-report-heading">
          <h2>{bilingual(lang, "各版本指标", "Release metrics")}</h2>
          <span id="vmTableMetric" className="muted">
            {`${vmMetricLabel(routeState.metric, lang)} · ${bilingual(
              lang,
              "人工列为模拟值",
              "Review columns are simulated",
            )}`}
          </span>
        </header>

        <div className="rd-table-wrap">
          <table
            className="rd-table vm-report-table"
            id="vmReportTable"
            aria-label={`${bilingual(lang, "各版本五方案指标", "Five-scheme release metrics")} · ${vmMetricLabel(
              routeState.metric,
              lang,
            )}`}
          >
            <thead id="vmReportHead">
              <tr>
                <th scope="col">{bilingual(lang, "版本", "Release")}</th>
                <th scope="col">{bilingual(lang, "有效／抽样", "Valid / sample")}</th>
                <th scope="col">{bilingual(lang, "有效 GT 来源", "Valid GT sources")}</th>
                <th scope="col">{bilingual(lang, "TE 已标", "TE filled")}</th>
                <th scope="col">{bilingual(lang, "RD 已标", "RD filled")}</th>
                {VM_SCHEMES.map((key) => (
                  <th key={key} scope="col" title={vmSchemeLabel(key, lang)}>
                    {vmSchemeShortLabel(key, lang)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody id="vmReportRows">
              {busyReport || !reportRows.length ? (
                <tr>
                  <td colSpan={10} className="vm-table-empty">
                    {reportEmptyMsg}
                  </td>
                </tr>
              ) : (
                reportRows.map((row) => {
                  const reportId = /^[0-9]{1,20}$/.test(row.report_id || "")
                    ? String(row.report_id)
                    : VM_REPORT_IDS[row.family];
                  const reportAria = bilingual(
                    lang,
                    `查看 ${row.family} 版本报告（新标签页）`,
                    `Open ${row.family} release report (new tab)`,
                  );
                  const dateCell = (
                    <th
                      scope="row"
                      title={`release-${row.family} · ${vmTime(row.observed_at, lang)} CST`}
                    >
                      <strong>{vmFamilyLabel(row.family)}</strong>
                      {reportId && (
                        <a
                          className="text-link vm-report-link"
                          href={`https://cooper.didichuxing.com/didocs/${reportId}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={reportAria}
                          title={reportAria}
                        >
                          {bilingual(lang, "报告", "Report")}
                        </a>
                      )}
                      {row.membership_changed && (
                        <small>{bilingual(lang, "版本已变化", "Membership changed")}</small>
                      )}
                    </th>
                  );

                  const change = vmSampleChange(row, lang);
                  if (row.status !== "ready") {
                    return (
                      <tr key={row.family}>
                        {dateCell}
                        <td>
                          <strong>{`—/${row.current_sample_total ?? "—"}`}</strong>
                        </td>
                        <td colSpan={8} className="vm-table-empty">
                          {row.reason === "human_fields_required"
                            ? bilingual(
                                lang,
                                "请更新指标以补齐人工 GT 字段",
                                "Update metrics to collect the missing human GT fields",
                              )
                            : row.status === "error"
                              ? bilingual(
                                  lang,
                                  "Trail 快照不可用，请更新指标",
                                  "Trail snapshot unavailable. Update metrics.",
                                )
                              : bilingual(
                                  lang,
                                  "暂无 Trail 快照，请更新指标",
                                  "No Trail snapshot. Update metrics.",
                                )}
                        </td>
                      </tr>
                    );
                  }

                  return (
                    <tr key={row.family}>
                      {dateCell}
                      <td>
                        <strong>
                          {row.valid_total}/{row.sample_total}
                        </strong>
                        {change && <small>{change}</small>}
                      </td>
                      <td>{vmReferenceCounts(row, lang)}</td>
                      <td>{renderCoverageCell(row, "te")}</td>
                      <td>{renderCoverageCell(row, "rd")}</td>
                      {VM_SCHEMES.map((key) => (
                        <td key={key}>{renderScoreCell(row, key)}</td>
                      ))}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      <div
        ref={tooltipRef}
        id="vmTooltip"
        className="analysis-pie-tooltip"
        role="tooltip"
        hidden={!tooltip || !tooltipRow}
        style={
          tooltip
            ? { left: `${tooltip.left}px`, top: `${tooltip.top}px` }
            : undefined
        }
      >
        {tooltipRow && (
          <>
            <strong>{`release-${tooltipRow.family} · conf < ${routeState.threshold.toFixed(2)}`}</strong>
            {tooltipRow.status === "ready" ? (
              <>
                {routeState.schemes.map((key) => {
                  const m = tooltipRow.metrics?.[key];
                  if (!m) return null;
                  const counts = getScoreCounts(tooltipRow, key, routeState.metric);
                  return (
                    <span key={key} style={{ color: VM_COLORS[key] }}>
                      <i
                        className="vm-swatch"
                        style={{ "--vm-color": VM_COLORS[key] } as React.CSSProperties}
                        aria-hidden="true"
                      />
                      {vmSchemeLabel(key, lang)}
                      <b>{vmPct(vmValue(tooltipRow, key, routeState.metric), lang)}</b>
                      <small>{counts}</small>
                    </span>
                  );
                })}
                <small>
                  {`${bilingual(lang, "快照有效／抽样", "Snapshot valid / sample")} ${tooltipRow.valid_total}/${tooltipRow.sample_total} · ${vmTime(
                    tooltipRow.observed_at,
                    lang,
                  )} CST`}
                </small>
                {vmReferenceCounts(tooltipRow, lang) && (
                  <small>{`GT · ${vmReferenceCounts(tooltipRow, lang)}`}</small>
                )}
                {tooltipRow.last_checked_at && (
                  <small>
                    {`${bilingual(lang, "自动核对", "Auto-checked")} · ${vmTime(
                      tooltipRow.last_checked_at,
                      lang,
                    )} CST`}
                  </small>
                )}
              </>
            ) : (
              <span>{bilingual(lang, "暂无有效快照", "No valid snapshot")}</span>
            )}
            {vmSampleChange(tooltipRow, lang) && (
              <small>{vmSampleChange(tooltipRow, lang)}</small>
            )}
          </>
        )}
      </div>
    </div>
  );
};
