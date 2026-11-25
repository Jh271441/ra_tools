import React, { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  ColorTheme,
  UiLanguage,
} from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { DEFAULT_CASE_PAGE_SIZE, Pagination } from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";
import { buildCronGraphModel } from "../features/cron-graph/buildCronGraphModel";

const CronGraphCanvas = React.lazy(() =>
  import("../features/cron-graph/CronGraphCanvas").then((m) => ({ default: m.CronGraphCanvas })),
);

export interface CronTiming {
  mode?: string;
  kind?: string;
  basis?: string;
  elapsed_seconds?: number;
  started_at?: string | number;
  finished_at?: string | number;
  observed_at?: string | number;
  observed?: number;
  total?: number;
}

export interface CronCaseRef {
  issue_id: string;
  code?: string;
}

export interface CronDailyRun {
  id: string;
  target_date_cst?: string;
  target_is_weekend?: boolean;
  health?: string;
  state?: string;
  stage?: string;
  selected?: number;
  inferred?: number;
  published?: number;
  verified?: number;
  skipped?: number;
  finished?: number;
  total?: number;
  percent?: number | null;
  started_at?: string | number;
  updated_at?: string | number;
  evidence_error?: boolean;
  timing?: CronTiming;
  skipped_cases?: CronCaseRef[];
  failure_details?: CronCaseRef[];
}

export interface CronLaunchRecord {
  target_date_cst?: string;
  state?: string;
  returncode?: number;
  started_at?: string | number;
  finished_at?: string | number;
}

export interface CronMediaScope {
  day?: string;
  state?: string;
  selected?: number;
  verified?: number;
  triple_verified?: number;
  camera_verified?: number;
  bev_verified?: number;
  failure_count?: number;
  closeup?: {
    receipt_status?: string;
    verified?: number;
    attention?: number;
    queued?: number;
    unknown?: number;
  };
}

export interface CronPlanningText {
  status?: string;
  selected?: number;
  with_frames?: number;
  collected?: number;
  partial_source?: number;
  failed?: number;
  pending?: number;
  unknown?: number;
}

export interface CronIncrementRow {
  start_at: string | number;
  family?: string;
  scan_state?: string;
  new?: number;
  filled?: number;
  published?: number;
  target_added?: number;
  target_removed?: number;
}

export interface CronIncrementalVersion {
  family: string;
  states_status?: string;
  updated_at?: string | number;
  states?: Record<string, number>;
  media?: CronMediaScope;
  planning_text?: CronPlanningText;
}

export interface CronIncrementalData {
  enabled?: boolean;
  stale?: boolean;
  updated_at?: string | number;
  families?: string[];
  versions?: CronIncrementalVersion[];
  datasets?: Array<{ release_family?: string; targets?: number; assigned?: Record<string, number> }>;
  states?: Record<string, number>;
  media?: CronMediaScope;
  planning_text?: CronPlanningText;
  discovery_schedule?: { hours?: number[] };
  increments?: {
    status?: string;
    items?: CronIncrementRow[];
  };
}

export interface CronJobRow {
  name: string;
  schedule: string;
  log_updated_at?: string | number;
  evidence?: string;
}

export interface DailyCronPayload {
  observed_at?: number;
  sources?: Record<string, string>;
  overview?: {
    collected_at?: number;
    stale?: boolean;
    collector_error?: boolean;
    daily?: {
      health?: string;
      next_run_at?: string | number;
      target_date?: string;
      heartbeat_at?: string | number;
      runs?: CronDailyRun[];
      launches?: CronLaunchRecord[];
      recoveries?: CronLaunchRecord[];
      alerts?: Array<{ kind: string; severity?: string }>;
    };
    jobs?: CronJobRow[];
  };
  media_daily?: {
    stale?: boolean;
    controller_error?: boolean;
    runs?: CronMediaScope[];
  };
  sidecar?: {
    daily_enabled?: boolean;
    updated_at?: string | number;
    controller_error?: boolean;
    stale?: boolean;
    state?: string;
    imported?: number;
    media_verified?: number;
    total?: number;
    failure_count?: number;
    camera?: { completed?: number; total?: number };
    bev_pilot?: { completed?: number; failed?: number };
    bev_backfill?: { completed?: number; failed?: number };
  } | null;
  closeup?: {
    state?: string;
    stale?: boolean;
    next_action_at?: string | number;
    versions?: Record<string, Record<string, number>>;
    source_members?: Record<string, Record<string, number>>;
  } | null;
  incremental?: CronIncrementalData | null;
  history?: Array<{ at: number; observations?: number; severity?: number }>;
}

export interface DailyCronPageProps {
  active: boolean;
  lang: UiLanguage;
  theme: ColorTheme;
}

const INCREMENT_KEYS = ["new", "filled", "published", "target_added", "target_removed"] as const;

function readInitialCronScope(): { version: string; day: string } {
  if (typeof window === "undefined") return { version: "", day: "" };
  const params = new URLSearchParams(window.location.search);
  const rawVersion = params.get("cron_version") || "";
  const rawDay = params.get("cron_day") || "";
  return {
    version: rawVersion === "all" || /^\d{8}$/.test(rawVersion) ? rawVersion : "",
    day: /^\d{4}-\d{2}-\d{2}$/.test(rawDay) ? rawDay : "",
  };
}

function cronTime(value: string | number | null | undefined, lang: UiLanguage): string {
  if (value == null || value === "") return "—";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(lang === "en" ? "en-GB" : "zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function cronCount(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : "—";
}

function cronFraction(done: number | null | undefined, total: number | null | undefined): string {
  return `${cronCount(done)} / ${cronCount(total)}`;
}

function cronDuration(value: number | null | undefined, lang: UiLanguage, compact = false): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "—";
  if (value > 0 && value < 1) return bilingual(lang, "<1秒", "<1s");
  const seconds = Math.floor(value);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds / 3600) % 24;
  const minutes = Math.floor(seconds / 60) % 60;
  const rest = seconds % 60;
  const parts: string[] = [];
  if (days) parts.push(bilingual(lang, `${days}天`, `${days}d`));
  if (hours) parts.push(bilingual(lang, `${hours}小时`, `${hours}h`));
  if (minutes && !(compact && days)) parts.push(bilingual(lang, `${minutes}分钟`, `${minutes}m`));
  if (!(compact && (days || hours)) && (rest || !parts.length)) {
    parts.push(bilingual(lang, `${rest}秒`, `${rest}s`));
  }
  return parts.join(bilingual(lang, "", " "));
}

function cronTimingText(
  timing: CronTiming | null | undefined,
  lang: UiLanguage,
  stale = false,
): string {
  if (
    !timing ||
    timing.mode === "unavailable" ||
    typeof timing.elapsed_seconds !== "number" ||
    !Number.isFinite(timing.elapsed_seconds) ||
    timing.elapsed_seconds < 0
  ) {
    return bilingual(lang, "耗时 —", "Duration —");
  }
  const prefix =
    timing.mode === "running"
      ? stale
        ? bilingual(lang, "上次已运行", "Last elapsed")
        : bilingual(lang, "已运行", "Elapsed")
      : timing.kind === "p50"
        ? bilingual(lang, "任务 P50", "Task P50")
        : timing.kind === "span"
          ? timing.mode === "observed"
            ? bilingual(lang, "已观测跨度", "Observed span")
            : bilingual(lang, "阶段用时", "Stage duration")
          : timing.basis === "media_registration_to_verified"
            ? bilingual(lang, "注册后耗时", "Since registration")
            : timing.basis === "camera_latest_attempt"
              ? bilingual(lang, "本轮耗时", "Attempt duration")
              : bilingual(lang, "耗时", "Duration");
  return `${prefix} ${cronDuration(timing.elapsed_seconds, lang)}`;
}

function cronLabel(value: string | undefined, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    success: ["已完成", "Complete"],
    complete: ["已完成", "Complete"],
    partial: ["已完成 · 有缺失", "Complete with gaps"],
    complete_with_gaps: ["已完成 · 有缺失", "Complete with gaps"],
    empty: ["无数据 · 正常结束", "No data · Complete"],
    waiting: ["等待任务", "Waiting"],
    running: ["运行中", "Running"],
    collecting: ["媒体采集中", "Collecting media"],
    failed: ["执行失败", "Failed"],
    media_failed: ["媒体失败", "Media failed"],
    missed: ["未按时启动", "Missed schedule"],
    stalled: ["进度停滞", "Progress stalled"],
    unknown: ["证据不足", "Insufficient evidence"],
    inferred: ["推理完成 · 未回刷", "Inferred · Not published"],
    inferred_with_gaps: ["推理完成 · 有缺失", "Inferred with gaps"],
    planned: ["仅计划", "Planned only"],
    recent: ["近期有活动", "Recent activity"],
    old: ["较久未更新", "Older activity"],
    finished: ["退出正常", "Exited normally"],
    launching: ["已启动", "Launched"],
    launch_error: ["启动异常", "Launch error"],
    partial_failed: ["部分失败", "Partial failure"],
    unavailable: ["暂不可用", "Unavailable"],
    awaiting_frontend_release: ["等待播放器验收", "Awaiting player validation"],
    incomplete: ["待补齐", "Incomplete"],
  };
  if (value && map[value]) return bilingual(lang, map[value][0], map[value][1]);
  return value || "—";
}

function cronTone(value: string | undefined): "ok" | "fail" | "warn" | "neutral" {
  if (!value) return "neutral";
  if (["success", "complete", "empty", "finished"].includes(value)) return "ok";
  if (["failed", "media_failed", "missed", "launch_error"].includes(value)) return "fail";
  if (
    [
      "partial",
      "complete_with_gaps",
      "stalled",
      "partial_failed",
      "inferred_with_gaps",
      "unavailable",
      "incomplete",
    ].includes(value)
  ) {
    return "warn";
  }
  return "neutral";
}

function cronMediaOutcome(media: CronMediaScope | undefined, stale = false): string {
  if (stale) return "stalled";
  if (!media || media.closeup?.receipt_status !== "ready") return "unknown";
  if (media.selected === 0) return "waiting";
  if (media.triple_verified === media.selected) return "complete";
  if (media.failure_count || media.closeup.attention || media.closeup.unknown) return "incomplete";
  return "waiting";
}

function cronVersionFamilies(inc: CronIncrementalData | null | undefined): string[] {
  const all = [
    ...(inc?.families || []),
    ...(inc?.versions || []).map((v) => v.family),
    ...(inc?.datasets || []).map((d) => d.release_family || ""),
  ]
    .map(String)
    .filter((v) => /^\d{8}$/.test(v));
  return Array.from(new Set(all)).sort().reverse();
}

function cronLatestLaunch(
  daily: NonNullable<DailyCronPayload["overview"]>["daily"] | undefined,
  run: CronDailyRun | undefined,
): CronLaunchRecord | undefined {
  const list = [...(daily?.launches || []), ...(daily?.recoveries || [])].filter(
    (item) => item.target_date_cst === run?.target_date_cst,
  );
  return list.sort((a, b) => String(b.started_at || "").localeCompare(String(a.started_at || "")))[0];
}

function isIncrementKnown(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v) && v >= 0;
}

function isIncrementIdle(row: CronIncrementRow): boolean {
  return row.scan_state === "success" && INCREMENT_KEYS.every((k) => row[k] === 0);
}

function formatIncrementFamily(row: CronIncrementRow, lang: UiLanguage): string {
  const fam = String(row.family || "");
  return /^\d{8}$/.test(fam) ? fam.slice(4) : fam || bilingual(lang, "未知版本", "Unknown version");
}

function incrementStatus(
  rows: CronIncrementRow[],
  lang: UiLanguage,
): ["ok" | "fail" | "warn" | "neutral", string] {
  if (rows.some((r) => r.scan_state === "failed")) return ["fail", bilingual(lang, "扫描失败", "Scan failed")];
  if (rows.some((r) => r.scan_state === "running")) return ["neutral", bilingual(lang, "扫描中", "Scanning")];
  if (rows.some((r) => r.scan_state !== "success")) return ["warn", bilingual(lang, "扫描未知", "Scan unknown")];
  return ["ok", bilingual(lang, "扫描成功", "Scan succeeded")];
}

const CronChip: React.FC<{ value?: string; lang: UiLanguage }> = ({ value, lang }) => (
  <span className="cron-chip" data-tone={cronTone(value)}>
    {cronLabel(value, lang)}
  </span>
);

export const DailyCronPage: React.FC<DailyCronPageProps> = ({ active, lang, theme }) => {
  const queryClient = useQueryClient();
  const initialScope = useMemo(() => readInitialCronScope(), []);
  const [selectedVersion, setSelectedVersion] = useState(initialScope.version);
  const [selectedDay, setSelectedDay] = useState(initialScope.day);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [helpLane, setHelpLane] = useState<"" | "main" | "media">("");
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState(false);
  const [jobSearch, setJobSearch] = useState("");
  const [jobsPage, setJobsPage] = useState(1);
  const [jobsPageSize, setJobsPageSize] = useState(DEFAULT_CASE_PAGE_SIZE);

  const workspaceRef = useRef<HTMLDivElement | null>(null);

  const cronQuery = useQuery<DailyCronPayload>({
    queryKey: ["daily-cron"],
    queryFn: ({ signal }) => apiRequest<DailyCronPayload>("/api/daily-cron", { signal }),
    enabled: active,
    refetchInterval: active ? 30_000 : false,
    staleTime: 10_000,
  });

  const data = cronQuery.data;
  const hasConnectionError = cronQuery.isError || refreshError;

  const incrementalEnabled = Boolean(data?.incremental?.enabled || selectedVersion);
  const families = useMemo(() => cronVersionFamilies(data?.incremental), [data?.incremental]);

  const effectiveVersion = useMemo(() => {
    if (selectedVersion) return selectedVersion;
    return families[0] || "all";
  }, [selectedVersion, families]);

  const isIncrementalView = incrementalEnabled && !selectedDay;

  const selectedIncremental = useMemo(() => {
    if (!isIncrementalView || !data) return null;
    const source = data.incremental?.enabled
      ? data.incremental
      : {
          enabled: true,
          stale: true,
          families: [],
          versions: [],
          datasets: [],
          states: {},
          media: {},
        };
    const family = effectiveVersion;
    if (family === "all") {
      return {
        ...source,
        family: "",
        stale: Boolean(source.stale || hasConnectionError),
        unavailable: false,
        statesUnavailable: false,
        states: source.states || {},
        media: source.media || {},
        planning_text: source.planning_text || {},
      };
    }
    const ver = source.versions?.find((v) => v.family === family);
    return {
      ...source,
      ...ver,
      family,
      families: [family],
      stale: Boolean(source.stale || hasConnectionError),
      unavailable: !ver,
      statesUnavailable: !ver || ver.states_status !== "ready",
      states: ver?.states || {},
      media: ver?.media || {},
      planning_text: ver?.planning_text || {},
      increments: source.increments
        ? {
            ...source.increments,
            items: (source.increments.items || []).filter((r) => r.family === family),
          }
        : undefined,
    };
  }, [isIncrementalView, data, effectiveVersion, hasConnectionError]);

  const dailyRuns = useMemo(
    () => (data?.overview?.daily?.runs || []).filter((r) => /^daily-\d{4}-\d{2}-\d{2}$/.test(r.id)),
    [data],
  );

  const pickedDay = selectedDay || dailyRuns[0]?.target_date_cst || "";
  const pickedMainRun = useMemo(
    () => dailyRuns.find((r) => r.target_date_cst === pickedDay),
    [dailyRuns, pickedDay],
  );
  const pickedMediaRun = useMemo(
    () => data?.media_daily?.runs?.find((r) => r.day === pickedDay),
    [data, pickedDay],
  );

  // Sync URL parameters when scope changes.
  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    try {
      const url = new URL(window.location.href);
      if (effectiveVersion) url.searchParams.set("cron_version", effectiveVersion);
      if (selectedDay) url.searchParams.set("cron_day", selectedDay);
      else url.searchParams.delete("cron_day");
      const next = `${url.pathname}${url.search}`;
      const current = `${window.location.pathname}${window.location.search}`;
      if (next !== current) {
        window.history.replaceState(window.history.state, "", next);
      }
    } catch {
      // Ignore history restrictions in tests.
    }
  }, [active, effectiveVersion, selectedDay]);

  const scopeSelectValue = selectedDay
    ? selectedDay
    : incrementalEnabled
      ? effectiveVersion === "all"
        ? "all"
        : `version:${effectiveVersion}`
      : "";

  const scopeOptions = useMemo<UiSelectOption[]>(() => {
    const opts: UiSelectOption[] = [];
    if (incrementalEnabled) {
      const famList = [...families];
      if (/^\d{8}$/.test(effectiveVersion) && !famList.includes(effectiveVersion)) {
        famList.push(effectiveVersion);
      }
      for (const fam of famList) {
        opts.push({
          value: `version:${fam}`,
          label: `${bilingual(lang, "版本", "Version")} ${fam.slice(4)} · ${fam.slice(0, 4)}`,
        });
      }
      opts.push({ value: "all", label: bilingual(lang, "全部版本汇总", "All versions") });
    } else {
      opts.push({
        value: "",
        label: [bilingual(lang, "最新运行", "Latest run"), dailyRuns[0]?.target_date_cst]
          .filter(Boolean)
          .join(" · "),
      });
    }
    for (const run of dailyRuns) {
      const statusText = ["partial", "complete_with_gaps"].includes(run.health || "")
        ? bilingual(lang, "已完成（有缺失）", "Complete with gaps")
        : cronLabel(run.health, lang);
      opts.push({
        value: run.target_date_cst || run.id,
        label: `${bilingual(lang, "旧日期批次", "Legacy daily run")} · ${run.target_date_cst || run.id} · ${statusText}`,
      });
    }
    return opts;
  }, [incrementalEnabled, families, effectiveVersion, dailyRuns, lang]);

  // Pure React graph model built directly (no legacy vendor/cron-graph bridge)
  const activeGraphModel = useMemo(() => {
    if (!data) return null;
    return buildCronGraphModel(data, {
      selectedVersion: effectiveVersion,
      selectedDay,
      selectedNode: selectedNodeId,
      error: hasConnectionError,
      active,
      lang,
      theme,
    });
  }, [data, effectiveVersion, selectedDay, selectedNodeId, hasConnectionError, active, lang, theme]);

  const helpGraphModel = useMemo(() => {
    if (!helpLane || !data) return null;
    return buildCronGraphModel(data, {
      selectedVersion: effectiveVersion,
      selectedDay,
      selectedNode: "",
      error: false,
      active: true,
      definitionLane: helpLane,
      lang,
      theme,
    });
  }, [helpLane, data, effectiveVersion, selectedDay, lang, theme]);

  const selectedNode = useMemo(() => {
    if (!selectedNodeId || !activeGraphModel) return null;
    for (const lane of activeGraphModel.lanes || []) {
      const match = lane.nodes.find((n) => n.id === selectedNodeId);
      if (match) return match;
    }
    return null;
  }, [selectedNodeId, activeGraphModel]);

  const handleForceRefresh = async () => {
    setRefreshing(true);
    setRefreshError(false);
    try {
      const fresh = await apiRequest<DailyCronPayload>("/api/daily-cron?refresh=true");
      queryClient.setQueryData(["daily-cron"], fresh);
    } catch {
      setRefreshError(true);
    } finally {
      setRefreshing(false);
    }
  };

  const handleScopeChange = (value: string) => {
    setSelectedNodeId("");
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      setSelectedDay(value);
    } else {
      setSelectedDay("");
      if (value === "all" || /^version:\d{8}$/.test(value)) {
        setSelectedVersion(value.replace("version:", ""));
      }
    }
  };

  // Filtered + paginated scheduled jobs
  const filteredJobs = useMemo(() => {
    const q = jobSearch.trim().toLowerCase();
    return (data?.overview?.jobs || []).filter((job) =>
      `${job.name} ${job.schedule}`.toLowerCase().includes(q),
    );
  }, [data, jobSearch]);

  const jobsPageCount = Math.max(1, Math.ceil(filteredJobs.length / jobsPageSize));
  const safeJobsPage = Math.max(1, Math.min(jobsPageCount, jobsPage));
  const visibleJobs = useMemo(() => {
    const start = (safeJobsPage - 1) * jobsPageSize;
    return filteredJobs.slice(start, start + jobsPageSize);
  }, [filteredJobs, safeJobsPage, jobsPageSize]);

  // Increment rounds (up to 14 latest rounds)
  const incrementRounds = useMemo(() => {
    const history = selectedIncremental?.increments;
    if (history?.status !== "ready") return [] as Array<[string, CronIncrementRow[]]>;
    const map = new Map<string, CronIncrementRow[]>();
    for (const row of history.items || []) {
      const key = String(row.start_at);
      const list = map.get(key) || [];
      list.push(row);
      map.set(key, list);
    }
    const epoch = (val: string | number) => (typeof val === "number" ? val * 1000 : Date.parse(val));
    return Array.from(map.entries())
      .sort((a, b) => epoch(b[1][0]!.start_at) - epoch(a[1][0]!.start_at))
      .slice(0, 14);
  }, [selectedIncremental]);

  // Compute hero display metrics
  const overview = data?.overview;
  const daily = overview?.daily;
  const observationAge = Date.now() / 1000 - (overview?.collected_at || 0);
  const legacyStale = Boolean(
    overview && (overview.stale || overview.collector_error || observationAge > 90),
  );
  const sourcesUnavailable = Object.values(data?.sources || {}).some((v) => v !== "ready");

  let connectionTone: "ok" | "warn" = "ok";
  let connectionText = bilingual(lang, "正在连接…", "Connecting…");
  let mainStatus = "unavailable";
  let mainValue = "—";
  let mainNote = "09:00 CST · T−2";
  let mainTiming = "";
  let mediaStatus = "unavailable";
  let mediaValue = "—";
  let mediaNote = bilingual(lang, "完成回执触发 · 独立判定", "Completion receipt · Independent outcome");
  let activeMedia: CronMediaScope | undefined;

  if (data && selectedIncremental) {
    const c = selectedIncremental.states || {};
    const m = selectedIncremental.media || {};
    activeMedia = m;
    const eligible = Object.entries(c)
      .filter(([k]) => !["excluded", "waiting_metadata"].includes(k))
      .reduce((n, [, x]) => n + (x || 0), 0);
    const inferred = (c.inferred || 0) + (c.published || 0);
    const scopeLabel = selectedIncremental.family
      ? selectedIncremental.family.slice(4)
      : bilingual(lang, "全部版本汇总", "All versions");
    const pending = (c.ready || 0) + (c.running || 0) + (c.retry_wait || 0) + (c.inferred || 0);
    const attention = (c.needs_attention || 0) + (c.identity_conflict || 0);

    connectionTone = selectedIncremental.stale || selectedIncremental.statesUnavailable ? "warn" : "ok";
    connectionText = `${scopeLabel} · ${bilingual(lang, "版本增量", "Version incremental")} · ${cronTime(selectedIncremental.updated_at, lang)} CST`;
    mainStatus = selectedIncremental.statesUnavailable
      ? "unavailable"
      : selectedIncremental.stale
        ? "stalled"
        : attention
          ? "partial"
          : pending
            ? "running"
            : c.waiting_metadata
              ? "waiting"
              : "complete";
    mainValue = `${scopeLabel} · ${selectedIncremental.statesUnavailable ? "— / —" : cronFraction(inferred, eligible)}`;
    mainNote = selectedIncremental.statesUnavailable
      ? bilingual(
          lang,
          "该版本队列状态暂不可用；不以其他版本或导入快照替代。",
          "Version queue status unavailable; other versions and import snapshots are not substituted.",
        )
      : bilingual(
          lang,
          `已推理 ${inferred} · 已回刷 ${c.published || 0} · 待源 ${c.waiting_metadata || 0} · 待核实 ${attention}`,
          `Inferred ${inferred} · Published ${c.published || 0} · Pending source ${c.waiting_metadata || 0} · Attention ${attention}`,
        );
    mediaStatus = selectedIncremental.unavailable
      ? "unavailable"
      : cronMediaOutcome(m, selectedIncremental.stale);
    mediaValue = cronFraction(m.triple_verified, m.selected);
    mediaNote = selectedIncremental.unavailable
      ? bilingual(lang, "该版本媒体状态暂不可用。", "Version media status unavailable.")
      : `${bilingual(lang, "三项均验收 / 同批目标", "All three verified / Same cohort")} · ${bilingual(lang, "待排查", "Needs review")} ${cronCount(m.closeup?.attention)} · ${bilingual(lang, "待队列处理", "Queued")} ${cronCount(m.closeup?.queued)} · ${bilingual(lang, "身份或范围待核实", "Identity / scope unconfirmed")} ${cronCount(m.closeup?.unknown)}`;
  } else if (data) {
    activeMedia = pickedMediaRun;
    connectionTone = hasConnectionError || legacyStale || sourcesUnavailable ? "warn" : "ok";
    const baseMsg = hasConnectionError
      ? bilingual(lang, "连接失败 · 保留上次快照，可能已过期", "Connection failed · Last snapshot may be stale")
      : legacyStale
        ? bilingual(lang, "采集异常或数据过期", "Collector error or stale data")
        : sourcesUnavailable
          ? bilingual(lang, "部分数据源不可用 · 其他状态独立显示", "Some sources unavailable · Other outcomes remain visible")
          : bilingual(lang, "监控已连接 · 每 30 秒刷新", "Monitor connected · Refreshes every 30s");
    connectionText = `${baseMsg} · ${bilingual(lang, "采集于", "Collected")} ${cronTime(overview?.collected_at || data.observed_at, lang)} CST`;
    mainStatus = pickedMainRun?.health || daily?.health || "unavailable";
    const processing =
      !["complete", "complete_with_gaps", "empty"].includes(pickedMainRun?.state || "") &&
      Number.isSafeInteger(pickedMainRun?.finished) &&
      Number.isSafeInteger(pickedMainRun?.total) &&
      (pickedMainRun?.total || 0) > 0;
    mainValue = `${pickedDay || "—"} · ${processing ? cronFraction(pickedMainRun?.finished, pickedMainRun?.total) : cronFraction(pickedMainRun?.verified, pickedMainRun?.selected)}`;
    mainTiming = cronTimingText(pickedMainRun?.timing, lang, legacyStale || hasConnectionError);
    const stageNames: Record<string, [string, string]> = {
      inference: ["采集 / 推理", "Acquisition / inference"],
      publication: ["回刷", "Publication"],
      sample_hook: ["抽样验证", "Sample verification"],
    };
    const stageText =
      pickedMainRun?.stage && stageNames[pickedMainRun.stage]
        ? bilingual(lang, stageNames[pickedMainRun.stage]![0], stageNames[pickedMainRun.stage]![1])
        : bilingual(lang, "当前阶段", "Current stage");
    mainNote = `${processing && pickedMainRun?.total ? `${stageText} · ${bilingual(lang, "已处理", "Processed")} ${Math.round(((pickedMainRun.finished || 0) / pickedMainRun.total) * 1000) / 10}%` : bilingual(lang, "已验证 / 选中", "Verified / Selected")} · ${bilingual(lang, "跳过", "Skipped")} ${cronCount(pickedMainRun?.skipped)}`;

    const runtime = data.media_daily;
    mediaStatus = !runtime
      ? "unavailable"
      : runtime.controller_error
        ? "failed"
        : cronMediaOutcome(pickedMediaRun, runtime.stale);
    const waitingMedia = pickedMediaRun?.state === "waiting" && pickedMediaRun.selected === 0;
    mediaValue = `${pickedDay || "—"} · ${waitingMedia ? bilingual(lang, "等待上游", "Waiting upstream") : cronFraction(pickedMediaRun?.triple_verified, pickedMediaRun?.selected)}`;
    mediaNote = waitingMedia
      ? bilingual(lang, "主流程完成后生成媒体任务", "Media tasks follow the main pipeline")
      : `${bilingual(lang, "三项均验收 / 同批目标", "All three verified / Same cohort")} · ${bilingual(lang, "待排查", "Needs review")} ${cronCount(pickedMediaRun?.closeup?.attention)} · ${bilingual(lang, "待队列处理", "Queued")} ${cronCount(pickedMediaRun?.closeup?.queued)} · ${bilingual(lang, "身份或范围待核实", "Identity / scope unconfirmed")} ${cronCount(pickedMediaRun?.closeup?.unknown)}`;
  } else if (hasConnectionError) {
    connectionTone = "warn";
    connectionText = bilingual(lang, "监控暂时无法连接，将自动重试。", "Monitor unavailable; retrying automatically.");
  }

  // 24h history strip buckets
  const nowHour = Math.floor(Date.now() / 3600000) * 3600;
  const historyHours = Array.from({ length: 24 }, (_, idx) => {
    const at = nowHour - (23 - idx) * 3600;
    const bucket = data?.history?.find((item) => item.at === at);
    const tone = bucket ? (["ok", "warn", "fail"][bucket.severity ?? 0] || "neutral") : "neutral";
    const label = `${cronTime(at, lang)} CST · ${bucket ? `${cronCount(bucket.observations)} ${bilingual(lang, "次观测", "observations")}` : bilingual(lang, "无观测", "No observations")}`;
    return { at, tone, label };
  });

  // Closeup versions filtered by selected incremental family
  const closeupVersions = useMemo(() => {
    if (!data?.closeup) return [];
    const family = selectedIncremental?.family || "";
    return Array.from(
      new Set([
        ...Object.keys(data.closeup.versions || {}),
        ...Object.keys(data.closeup.source_members || {}),
      ]),
    )
      .sort()
      .filter((v) => !family || v === family || v === family.slice(4));
  }, [data?.closeup, selectedIncremental?.family]);

  const closeupLabels: Record<string, [string, string]> = {
    queued: ["已入队", "Queued"],
    collecting: ["录制中", "Recording"],
    waiting: ["等待重试", "Waiting to retry"],
    idle: ["队列空闲", "Queue idle"],
    blocked_auth: ["需要刷新 Ares 登录", "Ares login refresh required"],
    pilot_failed_requires_review: ["小批失败待排查", "Pilot failures need review"],
    pilot_visual_review_required: ["小批待画面验收", "Pilot visual review required"],
    resource_wait: ["等待资源", "Waiting for resources"],
    stopped: ["已停止", "Stopped"],
    scheduled: ["等待计划启动", "Scheduled"],
    download_resource_wait: ["等待下载验收资源", "Waiting for download resources"],
    orion_observation_unavailable: ["原生状态暂不可用", "Native status unavailable"],
    interrupted_claim_requires_review: ["中断任务待恢复", "Interrupted jobs need recovery"],
    orion_results_require_review: ["未发布成员待排查", "Unpublished cases need review"],
    orion_running: ["离线队列处理中", "Offline queue processing"],
    orion_idle: ["队列空闲", "Queue idle"],
    unavailable: ["状态不可用", "Status unavailable"],
    unknown: ["状态未知", "Unknown status"],
  };

  const alertMessages: Record<string, [string, string]> = {
    heartbeat: ["调度心跳超过 3 分钟未更新", "Scheduler heartbeat is over 3 minutes old"],
    evidence: ["首次启用时间缺失，无法判定漏跑", "First activation time is missing"],
    missed: ["计划启动后 5 分钟仍无启动记录", "No launch record 5 minutes after the schedule"],
    partial: ["主流程已完成，少量采集缺失已如实记录", "Pipeline complete; acquisition gaps recorded"],
    failed: ["调度存在失败退出记录，请结合最终回执判断", "A scheduler failure exit is recorded; check the final receipt"],
    stalled: ["流水线进度超过阈值未更新", "Pipeline progress has not updated within its threshold"],
    unknown: ["启动记录与完成证据不完整", "Launch or completion evidence is incomplete"],
    source: ["部分状态文件读取异常", "Some state files could not be read"],
    cron: ["未发现每日定时任务或无法读取", "Daily scheduled task missing or unreadable"],
  };

  const latestLaunch = cronLatestLaunch(daily, pickedMainRun);
  const recoveredAlert =
    !isIncrementalView &&
    ["success", "partial", "empty"].includes(mainStatus) &&
    ["failed", "launch_error"].includes(latestLaunch?.state || "");

  const toggleFullscreen = () => {
    if (document.fullscreenElement) {
      void document.exitFullscreen?.();
    } else {
      void workspaceRef.current?.requestFullscreen?.();
    }
  };

  const planningText = selectedIncremental?.planning_text;

  return (
    <div id="raDailyCronRoot" className="ra-daily-cron-root" data-react-island="daily-cron">
      <div className="cron-page-heading">
        <div className="cron-scope-control ra-cron-scope-control">
          <span>{bilingual(lang, "查看范围", "View scope")}</span>
          <UiSelect
            id="raDailyCronScopeSelect"
            value={scopeSelectValue}
            options={scopeOptions}
            disabled={!data && cronQuery.isLoading}
            ariaLabel={bilingual(lang, "选择版本或旧日期批次", "Select version or legacy daily run")}
            onChange={handleScopeChange}
          />
        </div>
        <div
          className="cron-connection muted"
          id="raDailyCronConnection"
          data-tone={connectionTone}
          role="status"
          aria-live="polite"
        >
          {connectionText}
        </div>
        <button
          className="button button-quiet"
          id="raDailyCronRefresh"
          type="button"
          disabled={refreshing || cronQuery.isFetching}
          onClick={() => void handleForceRefresh()}
        >
          {refreshing || cronQuery.isFetching
            ? bilingual(lang, "刷新中…", "Refreshing…")
            : bilingual(lang, "刷新", "Refresh")}
        </button>
      </div>

      {isIncrementalView && (
        <p id="raDailyCronScopeNote" className="cron-note muted">
          {bilingual(
            lang,
            "同一套流水线，按版本查看；旧版本仍继续采集和补齐。",
            "One shared pipeline, viewed by version. Older versions continue collection and source checks.",
          )}
        </p>
      )}

      <div className="cron-monitors" id="raDailyCronMetrics">
        <article className="cron-monitor" data-monitor="main">
          <div className="cron-section-heading">
            <h3>{bilingual(lang, "推理回刷", "Inference / publication")}</h3>
            <CronChip value={mainStatus} lang={lang} />
            <button
              className="cron-info-button"
              type="button"
              aria-label={bilingual(lang, "推理回刷流程说明", "Inference pipeline definition")}
              title={bilingual(lang, "流程说明", "Pipeline definition")}
              onClick={() => setHelpLane("main")}
            >
              !
            </button>
          </div>
          <strong id="raDailyCronMainValue">{mainValue}</strong>
          <span className="muted" id="raDailyCronMainNote">
            {mainNote}
          </span>
          {mainTiming && <span className="cron-monitor-timing">{mainTiming}</span>}
        </article>

        <article className="cron-monitor" data-monitor="media">
          <div className="cron-section-heading">
            <h3>{bilingual(lang, "平台与媒体", "Platform / media")}</h3>
            <CronChip value={mediaStatus} lang={lang} />
            <button
              className="cron-info-button"
              type="button"
              aria-label={bilingual(lang, "平台与媒体流程说明", "Platform and media pipeline definition")}
              title={bilingual(lang, "流程说明", "Pipeline definition")}
              onClick={() => setHelpLane("media")}
            >
              !
            </button>
          </div>
          <strong id="raDailyCronMediaValue">{mediaValue}</strong>
          <span className="muted" id="raDailyCronMediaNote">
            {mediaNote}
          </span>
          <div className="cron-media-tracks" id="raDailyCronMediaTracks">
            <div>
              <span>Camera</span>
              <strong>{cronFraction(activeMedia?.camera_verified, activeMedia?.selected)}</strong>
            </div>
            <div>
              <span>BEV</span>
              <strong>{cronFraction(activeMedia?.bev_verified, activeMedia?.selected)}</strong>
            </div>
            <div>
              <span>{bilingual(lang, "局部 BEV", "Closeup BEV")}</span>
              <strong>{cronFraction(activeMedia?.closeup?.verified, activeMedia?.selected)}</strong>
            </div>
            {isIncrementalView && (
              <div className="cron-text-track">
                <span>
                  {bilingual(lang, "约束文本", "Constraint text")}
                  <small>
                    {planningText?.status === "ready"
                      ? bilingual(
                          lang,
                          `完整 ${planningText.collected} · 源缺口 ${planningText.partial_source} · 失败 ${planningText.failed} · 等待 ${planningText.pending} · 未取得 ${planningText.unknown}`,
                          `Complete ${planningText.collected} · Source gaps ${planningText.partial_source} · Failed ${planningText.failed} · Pending ${planningText.pending} · Missing ${planningText.unknown}`,
                        )
                      : bilingual(lang, "文字状态暂不可用", "Text status unavailable")}
                  </small>
                </span>
                <strong>
                  {cronFraction(
                    planningText?.status === "ready" ? planningText.with_frames : null,
                    planningText?.selected,
                  )}
                </strong>
              </div>
            )}
          </div>
        </article>
      </div>

      <section className="cron-panel cron-graph-panel" aria-labelledby="raDailyCronGraphTitle">
        <div className="cron-section-heading cron-graph-toolbar">
          <h3 id="raDailyCronGraphTitle">{bilingual(lang, "调度流水线", "Run graph")}</h3>
          <button
            className="button button-quiet"
            type="button"
            onClick={toggleFullscreen}
          >
            {bilingual(lang, "全屏", "Fullscreen")}
          </button>
        </div>
        <div
          ref={workspaceRef}
          className={`cron-graph-workspace${selectedNode ? " has-selection" : ""}`}
          id="raDailyCronGraphWorkspace"
        >
          <div
            className="cron-run-graph"
            id="raDailyCronGraph"
            aria-label={bilingual(
              lang,
              "两条独立任务链的动态运行图",
              "Live graph of two independent pipelines",
            )}
          >
            {activeGraphModel ? (
              <Suspense
                fallback={
                  <p className="cron-note muted">
                    {bilingual(lang, "正在加载运行图…", "Loading run graph…")}
                  </p>
                }
              >
                <CronGraphCanvas model={activeGraphModel} onSelect={setSelectedNodeId} />
              </Suspense>
            ) : (
              <p className="cron-note muted">
                {bilingual(lang, "正在加载运行图…", "Loading run graph…")}
              </p>
            )}
          </div>

          {selectedNode && (
            <aside className="cron-node-details" id="raDailyCronNodeDetails">
              <div className="cron-section-heading">
                <strong>{selectedNode.data.label}</strong>
                <button
                  type="button"
                  className="button button-quiet"
                  aria-label={bilingual(lang, "关闭详情", "Close details")}
                  onClick={() => setSelectedNodeId("")}
                >
                  ×
                </button>
              </div>
              <span
                className="cron-chip"
                data-tone={
                  selectedNode.data.status === "success"
                    ? "ok"
                    : selectedNode.data.status === "failed"
                      ? "fail"
                      : selectedNode.data.status === "warn"
                        ? "warn"
                        : "neutral"
                }
              >
                {selectedNode.data.stateLabel}
              </span>
              {selectedNode.data.progress &&
                (selectedNode.data.progress.mode === "count" ? (
                  <div
                    className="cron-task-progress"
                    data-stale={String(Boolean(selectedNode.data.progress.stale))}
                  >
                    <div className="cron-task-progress-values">
                      <span>{selectedNode.data.progress.text}</span>
                      <strong>{selectedNode.data.progress.percentText}</strong>
                    </div>
                    <div
                      className="cron-task-progress-track"
                      role="progressbar"
                      aria-label={selectedNode.data.progress.label}
                      aria-valuemin={0}
                      aria-valuemax={selectedNode.data.progress.total}
                      aria-valuenow={selectedNode.data.progress.done}
                    >
                      <span style={{ width: `${selectedNode.data.progress.completePercent || 0}%` }} />
                      <i style={{ width: `${selectedNode.data.progress.failurePercent || 0}%` }} />
                    </div>
                  </div>
                ) : (
                  <span className="cron-task-progress-empty">{selectedNode.data.progress.text}</span>
                ))}
              <dl>
                {(selectedNode.data.rows || []).map(([k, v], i) => (
                  <div key={`${k}-${i}`}>
                    <dt>{k}</dt>
                    <dd>{String(v)}</dd>
                  </div>
                ))}
              </dl>
              {Boolean(selectedNode.data.issues?.length) && (
                <ul className="cron-case-list">
                  {Array.from(new Set(selectedNode.data.issues)).map((issue) => (
                    <li key={issue}>
                      <a
                        href={`https://voyager.intra.xiaojukeji.com/static/management/#/issue/${encodeURIComponent(issue)}?view_id=2410`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {issue} ↗
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </aside>
          )}

          <button
            className="button button-quiet cron-exit-fullscreen"
            type="button"
            onClick={toggleFullscreen}
          >
            {bilingual(lang, "退出全屏", "Exit fullscreen")}
          </button>
        </div>

        <div className="cron-graph-legend muted">
          <span data-state="success">{bilingual(lang, "完成", "Complete")}</span>
          <span data-state="running">{bilingual(lang, "运行", "Running")}</span>
          <span data-state="warn">{bilingual(lang, "有缺失 / 恢复", "Gaps / Recovered")}</span>
          <span data-state="failed">{bilingual(lang, "失败", "Failed")}</span>
          <span data-state="unknown">{bilingual(lang, "等待 / 无回执", "Waiting / No evidence")}</span>
          <span className="cron-mobile-hint">
            {bilingual(lang, "点击阶段查看进度与失败明细", "Select a stage for progress and failures")}
          </span>
          <span className="cron-graph-hint">
            {bilingual(
              lang,
              "点击节点查看详情 · 拖动画布 / 双指缩放",
              "Select a task for details · Drag / pinch to zoom",
            )}
          </span>
        </div>
      </section>

      {isIncrementalView && selectedIncremental && (
        <section className="cron-panel cron-increments" aria-labelledby="raDailyCronIncrementsTitle">
          <div className="cron-section-heading">
            <h3 id="raDailyCronIncrementsTitle">
              {bilingual(lang, "每轮增量", "Increments per round")}
            </h3>
            <span className="muted">07:00 / 19:00 · CST</span>
          </div>
          {!incrementRounds.length ? (
            <p className="cron-increment-message muted" role="status">
              {selectedIncremental.increments?.status === "empty" ||
              selectedIncremental.increments?.status === "ready"
                ? bilingual(lang, "尚无定时扫描记录。", "No scheduled scans yet.")
                : bilingual(lang, "增量记录暂不可用。", "Increment history is unavailable.")}
            </p>
          ) : (
            <div className="cron-increment-rounds">
              {incrementRounds.map(([at, rows], idx) => {
                const [tone, status] = incrementStatus(rows, lang);
                const changed = rows.filter((r) =>
                  INCREMENT_KEYS.some((k) => isIncrementKnown(r[k]) && (r[k] as number) > 0),
                );
                const incomplete = rows.some(
                  (r) =>
                    r.scan_state !== "success" ||
                    INCREMENT_KEYS.some((k) => !isIncrementKnown(r[k])),
                );
                const brief = changed.length
                  ? bilingual(
                      lang,
                      `有变化 ${changed.map((r) => formatIncrementFamily(r, lang)).join(" / ")}`,
                      `Changed: ${changed.map((r) => formatIncrementFamily(r, lang)).join(" / ")}`,
                    )
                  : incomplete
                    ? bilingual(lang, "数据待确认", "Data unconfirmed")
                    : bilingual(lang, "所选范围无增量", "No changes in the selected scope");
                const activeRows = rows.filter((r) => !isIncrementIdle(r));
                const idleRows = rows.filter(isIncrementIdle);
                const metricDefs: Array<[typeof INCREMENT_KEYS[number], string]> = [
                  ["new", bilingual(lang, "新发现", "New cases")],
                  ["filled", bilingual(lang, "旧案例补齐", "Source filled")],
                  ["published", bilingual(lang, "回刷完成", "Published")],
                  ["target_added", bilingual(lang, "目标入库", "Targets added")],
                ];
                return (
                  <details
                    key={at}
                    className="cron-increment-round"
                    data-latest={String(idx === 0)}
                    open={idx === 0}
                  >
                    <summary>
                      <span className="cron-round-time">
                        {idx === 0 && (
                          <span className="muted">{bilingual(lang, "最近一轮", "Latest round")}</span>
                        )}
                        <strong>{cronTime(rows[0]!.start_at, lang).replace(/:\d{2}$/, "")}</strong>
                      </span>
                      <span className="cron-chip" data-tone={tone}>
                        {status}
                      </span>
                      <span className="cron-round-brief muted">
                        {brief}
                        {incomplete && changed.length
                          ? ` · ${bilingual(lang, "含未知", "Includes unknowns")}`
                          : ""}
                      </span>
                      <span className="cron-round-chevron" aria-hidden="true">
                        ⌄
                      </span>
                    </summary>
                    <div className="cron-increment-body">
                      {activeRows.map((row, rIdx) => {
                        const [rTone, rStatus] = incrementStatus([row], lang);
                        const hasUnknown = INCREMENT_KEYS.some((k) => !isIncrementKnown(row[k]));
                        return (
                          <article key={`${row.family}-${rIdx}`} className="cron-increment-version">
                            <header>
                              <strong>{formatIncrementFamily(row, lang)}</strong>
                              {row.scan_state !== "success" && (
                                <span className="cron-chip" data-tone={rTone}>
                                  {rStatus}
                                </span>
                              )}
                              {hasUnknown && (
                                <span className="muted">
                                  {bilingual(lang, "数据不完整", "Incomplete data")}
                                </span>
                              )}
                              {row.target_removed !== 0 && (
                                <span>
                                  {bilingual(lang, "目标移出", "Targets removed")}{" "}
                                  <b>
                                    {isIncrementKnown(row.target_removed)
                                      ? cronCount(row.target_removed)
                                      : bilingual(lang, "未知", "Unknown")}
                                  </b>
                                </span>
                              )}
                            </header>
                            <dl className="cron-increment-metrics">
                              {metricDefs.map(([key, label]) => (
                                <div key={key}>
                                  <dt>{label}</dt>
                                  <dd className={isIncrementKnown(row[key]) ? "" : "muted"}>
                                    {isIncrementKnown(row[key])
                                      ? cronCount(row[key] as number)
                                      : bilingual(lang, "未知", "Unknown")}
                                  </dd>
                                </div>
                              ))}
                            </dl>
                          </article>
                        );
                      })}
                      {idleRows.length > 0 && (
                        <p className="cron-increment-idle">
                          <span className="muted">{bilingual(lang, "无增量", "No changes")}</span>
                          <strong>
                            {idleRows.map((r) => formatIncrementFamily(r, lang)).join(" / ")}
                          </strong>
                        </p>
                      )}
                    </div>
                  </details>
                );
              })}
            </div>
          )}
          <details className="cron-increment-explanation">
            <summary>{bilingual(lang, "统计口径 · 最近14轮", "Counting rules · Latest 14 rounds")}</summary>
            <p className="cron-note muted">
              {bilingual(
                lang,
                "新发现：首次发现。补齐：旧案例触发源齐备并入队。回刷与目标入库按实际完成时段统计，可含前轮待办；目标移出取导入回执。各项独立，不能相加或计算转化率。未知不等于零。底层历史保留。",
                "New: first discoveries. Source filled: previously waiting cases now ready and queued. Published and targets added follow actual completion windows and may include earlier work; removals come from import receipts. Metrics are independent, not additive or conversion rates. Unknown is not zero. Underlying history is retained.",
              )}
            </p>
          </details>
        </section>
      )}

      <details className="cron-panel cron-fold">
        <summary>{bilingual(lang, "调度与历史", "Schedule / History")}</summary>
        <div className="cron-schedule">
          {isIncrementalView && selectedIncremental
            ? selectedIncremental.discovery_schedule?.hours?.length
              ? bilingual(
                  lang,
                  "每天 07:00、19:00 CST 全量发现及补查；队列独立持续处理，无单轮总量上限。",
                  "Full discovery and source checks at 07:00/19:00 CST; the queue continues independently without a per-round case cap.",
                )
              : bilingual(
                  lang,
                  "按版本持续处理；查询计划等待同步。",
                  "Version-scoped processing; awaiting discovery schedule.",
                )
            : daily
              ? `${bilingual(lang, "下次计划", "Next schedule")} ${cronTime(daily.next_run_at, lang)} CST · ${bilingual(lang, "对应目标日", "Target")} ${daily.target_date || "—"} · ${bilingual(lang, "调度心跳", "Scheduler heartbeat")} ${cronTime(daily.heartbeat_at, lang)} CST`
              : bilingual(lang, "主流程监控暂不可用", "Pipeline monitor unavailable")}
        </div>
        <div>
          {isIncrementalView && selectedIncremental ? (
            <p className="cron-note">
              {selectedIncremental.stale
                ? bilingual(lang, "增量心跳过期，请核实任务。", "Incremental heartbeat is stale.")
                : bilingual(
                    lang,
                    "逐 case 完成后进入回刷和媒体；不等待整批。各节点为当前累计进度，缺源与异常单独等待。",
                    "Completed cases stream to publication and media independently. Nodes show cumulative progress; missing sources and ambiguous cases wait separately.",
                  )}
            </p>
          ) : (
            <>
              {recoveredAlert && (
                <div className="cron-alert" data-tone="warn">
                  {bilingual(
                    lang,
                    "调度退出记录仍为失败；最终回执已完成。两份证据分别保留，请查看流水线详情。",
                    "Scheduler exit records a failure; the final receipt is complete. Both records are retained below.",
                  )}
                </div>
              )}
              {(daily?.alerts || [])
                .filter((a) => !(recoveredAlert && a.kind === "failed"))
                .map((alert, idx) => {
                  const pair = alertMessages[alert.kind] || [
                    "监控有提醒，请查看运行详情",
                    "Monitor alert; inspect the run details",
                  ];
                  return (
                    <div
                      key={`${alert.kind}-${idx}`}
                      className="cron-alert"
                      data-tone={alert.severity === "critical" ? "fail" : "warn"}
                    >
                      {bilingual(lang, pair[0], pair[1])}
                    </div>
                  );
                })}
              {!recoveredAlert && !(daily?.alerts || []).length && (
                <p className="cron-note muted">
                  {daily
                    ? bilingual(lang, "本次观测未发现调度异常。", "No scheduler alerts in this observation.")
                    : bilingual(lang, "等待主流程观测恢复。", "Waiting for pipeline observations.")}
                </p>
              )}
            </>
          )}
        </div>
        <div className="cron-history-caption muted">
          {bilingual(lang, "近24小时 · 最严重观测", "24h · Worst observed state")}
        </div>
        <div className="cron-history">
          {historyHours.map((cell) => (
            <span
              key={cell.at}
              className="cron-history-hour"
              data-tone={cell.tone}
              tabIndex={0}
              role="img"
              aria-label={cell.label}
              title={cell.label}
            />
          ))}
        </div>
      </details>

      <details className="cron-panel cron-fold">
        <summary>{bilingual(lang, "运行记录", "Run history")}</summary>
        <div className="cron-runs">
          {!(daily?.runs || []).length ? (
            <p className="cron-note muted">
              {overview
                ? bilingual(lang, "尚无流水线记录，首次执行后显示。", "Runs appear after the first execution.")
                : bilingual(lang, "流水线数据源暂不可用。", "Pipeline source unavailable.")}
            </p>
          ) : (
            (daily?.runs || []).map((run) => {
              const launch = cronLatestLaunch(daily, run);
              const failures = [...(run.skipped_cases || []), ...(run.failure_details || [])];
              const uniqueCases = Array.from(
                new Map(failures.map((c) => [c.issue_id, c])).values(),
              );
              const stageMap: Record<string, [string, string]> = {
                inference: ["模型推理", "Inference"],
                publication: ["Trail 回刷", "Trail publication"],
                sample_hook: ["抽样与验证", "Sampling and verification"],
                complete: ["完成", "Complete"],
              };
              const stageLabel =
                run.health === "empty"
                  ? bilingual(lang, "无数据，正常结束", "No data, completed")
                  : run.stage && stageMap[run.stage]
                    ? bilingual(lang, stageMap[run.stage]![0], stageMap[run.stage]![1])
                    : run.stage || run.state || "—";
              return (
                <article key={run.id} className="cron-run">
                  <div className="cron-run-heading">
                    <div>
                      <strong>{run.target_date_cst || run.id}</strong>
                      {run.target_is_weekend && (
                        <span className="cron-chip" data-tone="neutral">
                          {bilingual(lang, "CST 周末", "CST weekend")}
                        </span>
                      )}
                    </div>
                    <CronChip value={run.health} lang={lang} />
                  </div>
                  <div className="cron-run-counts">
                    {`${bilingual(lang, "选中", "Selected")} ${cronCount(run.selected)} · ${bilingual(lang, "已推理", "Inferred")} ${cronCount(run.inferred)} · ${bilingual(lang, "已回刷", "Published")} ${cronCount(run.published)} · ${bilingual(lang, "已验证", "Verified")} ${cronCount(run.verified)} · ${bilingual(lang, "跳过", "Skipped")} ${cronCount(run.skipped)}`}
                  </div>
                  {run.percent != null && (
                    <div className="cron-stage-progress">
                      <progress
                        max={100}
                        value={Math.max(0, Math.min(100, run.percent))}
                        aria-label={bilingual(lang, "当前阶段完成百分比", "Current stage progress")}
                      />
                      <span className="muted">
                        {`${stageLabel} · ${cronFraction(run.finished, run.total)} · ${run.percent}%`}
                      </span>
                    </div>
                  )}
                  <div className="cron-run-timing">
                    {cronTimingText(run.timing, lang, hasConnectionError || legacyStale)}
                  </div>
                  <details className="cron-run-detail">
                    <summary>
                      {bilingual(lang, "运行证据与缺失案例", "Run evidence and missing cases")}
                      {uniqueCases.length ? ` · ${uniqueCases.length}` : ""}
                    </summary>
                    <dl>
                      <div>
                        <dt>Run</dt>
                        <dd>{run.id}</dd>
                      </div>
                      <div>
                        <dt>{bilingual(lang, "最终状态", "Final state")}</dt>
                        <dd>{run.state || "—"}</dd>
                      </div>
                      <div>
                        <dt>{bilingual(lang, "开始 / 更新 · CST", "Started / Updated · CST")}</dt>
                        <dd>{`${cronTime(run.started_at, lang)} / ${cronTime(run.updated_at, lang)}`}</dd>
                      </div>
                      <div>
                        <dt>{bilingual(lang, "最近调度退出", "Latest scheduler exit")}</dt>
                        <dd>
                          {launch
                            ? `${cronLabel(launch.state, lang)} · exit ${cronCount(launch.returncode)} · ${cronTime(launch.finished_at || launch.started_at, lang)}`
                            : "—"}
                        </dd>
                      </div>
                    </dl>
                    {run.evidence_error && (
                      <p className="cron-alert" data-tone="warn">
                        {bilingual(lang, "状态证据读取异常", "Run evidence could not be read")}
                      </p>
                    )}
                    {uniqueCases.length ? (
                      <ul className="cron-case-list">
                        {uniqueCases.map((item) => (
                          <li key={item.issue_id}>
                            <a
                              href={`https://voyager.intra.xiaojukeji.com/static/management/#/issue/${encodeURIComponent(item.issue_id)}?view_id=2410`}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {item.issue_id} ↗
                            </a>
                            <span className="muted">
                              {item.code || bilingual(lang, "采集失败", "Acquisition failed")}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="cron-note muted">
                        {bilingual(lang, "未记录跳过或失败案例。", "No skipped or failed cases recorded.")}
                      </p>
                    )}
                  </details>
                </article>
              );
            })
          )}
        </div>
      </details>

      {data?.closeup && (
        <details className="cron-panel cron-fold">
          <summary>
            {bilingual(lang, "局部 BEV · 历史全量回溯", "Closeup BEV · Full historical backfill")}
          </summary>
          <p className="cron-note muted">
            {(() => {
              const pair = data.closeup.stale
                ? (["心跳过期", "Stale heartbeat"] as [string, string])
                : closeupLabels[data.closeup.state || ""] || closeupLabels.unknown!;
              const suffix =
                !data.closeup.stale &&
                data.closeup.state === "scheduled" &&
                data.closeup.next_action_at
                  ? ` · ${cronTime(data.closeup.next_action_at, lang)} CST`
                  : "";
              return `${bilingual(lang, pair[0], pair[1])}${suffix}`;
            })()}
          </p>
          <div className="cron-sidecar-metrics">
            {closeupVersions.map((ver) => {
              const states = data.closeup?.versions?.[ver] || {};
              const source = data.closeup?.source_members?.[ver] || {};
              const published = Object.entries(source).filter(([k]) => k.startsWith("published:"));
              const total = published.length
                ? published.reduce((n, [, c]) => n + c, 0)
                : Object.values(states).reduce((n, c) => n + c, 0);
              const missing = published
                .filter(([k]) => k !== "published:ready")
                .reduce((n, [, c]) => n + c, 0);
              const detail = bilingual(
                lang,
                `待处理 ${Math.max(0, total - (states.verified || 0))} · 失败 ${states.failed || 0} · 锚点待解决 ${missing}`,
                `Pending ${Math.max(0, total - (states.verified || 0))} · Failed ${states.failed || 0} · Unresolved anchors ${missing}`,
              );
              return (
                <article
                  key={ver}
                  className="cron-metric"
                  data-tone={states.failed || missing ? "warn" : "neutral"}
                >
                  <span className="muted">{ver}</span>
                  <strong>{cronFraction(states.verified || 0, total)}</strong>
                  <small className="muted">{detail}</small>
                </article>
              );
            })}
          </div>
          <p className="cron-note muted">
            {!closeupVersions.length
              ? bilingual(lang, "该版本暂无局部 BEV 回执。", "No closeup BEV receipts for this version.")
              : bilingual(
                  lang,
                  "历史全量范围（含非 daily 成员）；当前 daily 的三媒体进度见上方。历史失败不代表正在录制。",
                  "Historical full scope, including non-daily members. Daily three-media coverage is shown above. Historical failures do not indicate active recording.",
                )}
          </p>
        </details>
      )}

      <details className="cron-panel cron-fold">
        <summary>{bilingual(lang, "历史媒体回溯", "Historical media backfill")}</summary>
        {!data?.sidecar ? (
          <p className="cron-alert" data-tone="warn">
            {bilingual(
              lang,
              "旁路监控暂不可用，主任务状态独立显示。",
              "Sidecar monitor unavailable; main pipeline remains independent.",
            )}
          </p>
        ) : (
          <div>
            <div className="cron-sidecar-heading">
              <span>
                {bilingual(lang, "每日自动导入", "Daily import")} ·{" "}
                {data.sidecar.daily_enabled
                  ? bilingual(lang, "已启用", "Enabled")
                  : bilingual(lang, "等待启用", "Waiting")}
              </span>
              <span className="muted">
                {bilingual(lang, "更新", "Updated")} {cronTime(data.sidecar.updated_at, lang)} CST
              </span>
            </div>
            {(data.sidecar.controller_error || data.sidecar.stale) && (
              <p className="cron-alert" data-tone="warn">
                {data.sidecar.controller_error
                  ? bilingual(lang, "旁路控制器异常", "Sidecar controller error")
                  : bilingual(lang, "旁路状态超过一小时未更新", "Sidecar status over one hour old")}
              </p>
            )}
            <details className="cron-backfill">
              <summary>
                {bilingual(lang, "历史回溯媒体", "Historical media backfill")} ·{" "}
                {cronFraction(data.sidecar.media_verified, data.sidecar.total)}{" "}
                <CronChip value={data.sidecar.state} lang={lang} />
              </summary>
              <div className="cron-sidecar-metrics">
                <article className="cron-metric" data-tone="neutral">
                  <span className="muted">
                    {bilingual(lang, "历史 Run 导入", "Historical Run imports")}
                  </span>
                  <strong>{cronFraction(data.sidecar.imported, data.sidecar.total)}</strong>
                  <small className="muted">
                    {bilingual(lang, "历史回溯口径，非当天数据量", "Historical scope, not today's volume")}
                  </small>
                </article>
                <article className="cron-metric" data-tone="neutral">
                  <span className="muted">
                    {bilingual(lang, "媒体最终验证", "Final media validation")}
                  </span>
                  <strong>{cronFraction(data.sidecar.media_verified, data.sidecar.total)}</strong>
                  <small className="muted">
                    {bilingual(lang, "未解决失败", "Unresolved failures")}{" "}
                    {cronCount(data.sidecar.failure_count)}
                  </small>
                </article>
                <article className="cron-metric" data-tone="neutral">
                  <span className="muted">
                    {bilingual(lang, "Camera 已采集", "Camera collected")}
                  </span>
                  <strong>
                    {cronFraction(data.sidecar.camera?.completed, data.sidecar.camera?.total)}
                  </strong>
                  <small className="muted">
                    {bilingual(lang, "以最终媒体验证为准", "Final media validation is authoritative")}
                  </small>
                </article>
              </div>
              <p className="cron-note muted">
                {bilingual(
                  lang,
                  "原始 Orion 失败数保留历史；重试或本地修复后的结果计入“媒体最终验证”。历史回溯数量与每日新增 Run 分别统计。",
                  "Original Orion failures are retained as history. Successful retries/local repairs count in final media validation. Historical backfill and daily Runs use separate scopes.",
                )}
              </p>
            </details>
          </div>
        )}
      </details>

      <details className="cron-panel cron-fold" id="raDailyCronJobsFold">
        <summary>
          {bilingual(lang, "其他定时任务", "Other scheduled tasks")}
          {filteredJobs.length ? ` · ${filteredJobs.length}` : ""}
        </summary>
        <div className="cron-section-heading ra-cron-jobs-search">
          <input
            id="raDailyCronSearch"
            type="search"
            value={jobSearch}
            aria-label={bilingual(lang, "搜索定时任务", "Search scheduled tasks")}
            placeholder={bilingual(lang, "搜索任务或调度表达式", "Search task or schedule")}
            onChange={(e) => {
              setJobSearch(e.target.value);
              setJobsPage(1);
            }}
          />
        </div>
        <div className="cron-table-wrap ra-table-scroll">
          <table className="cron-table">
            <thead>
              <tr>
                <th>{bilingual(lang, "任务", "Task")}</th>
                <th>{bilingual(lang, "调度", "Schedule")}</th>
                <th>{bilingual(lang, "日志更新 · CST", "Log updated · CST")}</th>
                <th>{bilingual(lang, "活动证据", "Activity")}</th>
              </tr>
            </thead>
            <tbody>
              {visibleJobs.length ? (
                visibleJobs.map((job, idx) => (
                  <tr key={`${job.name}-${idx}`}>
                    <td>{job.name}</td>
                    <td>
                      <code>{job.schedule}</code>
                    </td>
                    <td>{cronTime(job.log_updated_at, lang)}</td>
                    <td>
                      <CronChip value={job.evidence} lang={lang} />
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} className="muted">
                    {bilingual(
                      lang,
                      "暂无匹配任务或清单不可用",
                      "No matching tasks or inventory unavailable",
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {filteredJobs.length > 0 && (
          <Pagination
            page={safeJobsPage}
            pageSize={jobsPageSize}
            total={filteredJobs.length}
            lang={lang}
            ariaLabel={bilingual(lang, "定时任务分页", "Scheduled tasks pagination")}
            onPageChange={(next) => setJobsPage(next)}
            onPageSizeChange={(nextSize) => {
              setJobsPageSize(nextSize);
              setJobsPage(1);
            }}
          />
        )}
      </details>

      <ModalDialog
        open={Boolean(helpLane)}
        wide
        title={
          helpLane === "main"
            ? bilingual(lang, "推理回刷 · 流程说明", "Daily inference · Definition")
            : bilingual(lang, "平台与媒体 · 流程说明", "Media sidecar · Definition")
        }
        lang={lang}
        onClose={() => setHelpLane("")}
      >
        <div className="cron-help-graph">
          {helpGraphModel && (
            <Suspense
              fallback={
                <p className="cron-note muted">
                  {bilingual(lang, "正在加载流程图…", "Loading definition graph…")}
                </p>
              }
            >
              <CronGraphCanvas model={helpGraphModel} />
            </Suspense>
          )}
        </div>
        <p className="cron-note muted">
          {helpLane === "main"
            ? data?.incremental?.enabled
              ? bilingual(
                  lang,
                  "每天 07:00、19:00 CST 按版本全量发现和补查；队列 4 并发全量处理，固定版本级 10% 概率抽样。缺源独立等待，每轮增量分开记录。",
                  "Version discovery and source checks at 07:00/19:00 CST; four workers process all eligible queued cases with stable 10% probability sampling. Missing sources wait independently; increments are recorded per round.",
                )
              : bilingual(
                  lang,
                  "09:00 CST，处理 T−2；周末照常查询。少量采集缺失 ≤5 且 ≤2% 可继续并记录，超限阻塞。空数据正常结束。",
                  "09:00 CST, T−2 data; weekends queried normally. Acquisition gaps ≤5 AND ≤2% may continue with records; larger gaps block. Empty data completes normally.",
                )
            : bilingual(
                lang,
                "同批目标生成 Camera、BEV、局部 BEV，分别验收发布，三项交集计为齐全。两种 BEV 均先 Orion 重试 1 次，仍失败或验收不通过则本地最多 2 次，共享全局 2 个本地名额。源异常保留待查。Camera 清理沿用原发布回执与 1 小时策略。",
                "Camera, BEV and closeup BEV share the target cohort and publish independently. Complete coverage is their intersection. Both BEV tracks retry Orion once, then use up to two local attempts for failures or invalid output, sharing two global local slots. Source failures retain evidence. Camera cleanup keeps its existing publication receipt and 1h policy.",
              )}
        </p>
      </ModalDialog>
    </div>
  );
};
