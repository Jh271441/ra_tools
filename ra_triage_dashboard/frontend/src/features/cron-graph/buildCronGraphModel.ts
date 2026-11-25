import { bilingual, ColorTheme, UiLanguage } from "../../bridge/useWorkbenchBridge";
import type {
  CronGraphEdge,
  CronGraphLane,
  CronGraphModel,
  CronGraphNode,
  CronGraphNodeProgress,
} from "./layout";

/* eslint-disable @typescript-eslint/no-explicit-any */

function fmtTime(value: string | number | null | undefined, lang: UiLanguage): string {
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

function fmtCount(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : "—";
}

function fmtFraction(done: unknown, total: unknown): string {
  return `${fmtCount(done)} / ${fmtCount(total)}`;
}

function fmtDuration(value: unknown, lang: UiLanguage, compact = false): string {
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

function fmtTimingText(timing: any, lang: UiLanguage, compact = false, stale = false): string {
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
  return `${prefix} ${fmtDuration(timing.elapsed_seconds, lang, compact)}`;
}

function fmtTimingRows(timing: any, lang: UiLanguage, stale = false): Array<[string, string]> {
  if (!timing) return [];
  const rows: Array<[string, string]> = [];
  if (timing.started_at) {
    rows.push([bilingual(lang, "开始 · CST", "Started · CST"), fmtTime(timing.started_at, lang)]);
  }
  if (timing.finished_at) {
    rows.push([bilingual(lang, "结束 · CST", "Finished · CST"), fmtTime(timing.finished_at, lang)]);
  }
  if (typeof timing.elapsed_seconds === "number" && Number.isFinite(timing.elapsed_seconds)) {
    rows.push([bilingual(lang, "耗时", "Duration"), fmtTimingText(timing, lang, false, stale)]);
  }
  return rows;
}

function stateLabelOf(status: string, lang: UiLanguage): string {
  const labels: Record<string, [string, string]> = {
    success: ["完成", "Complete"],
    warn: ["有缺失 / 已恢复", "Gaps / Recovered"],
    failed: ["失败", "Failed"],
    running: ["运行中", "Running"],
    pending: ["等待", "Waiting"],
    skipped: ["未执行", "Not executed"],
    unknown: ["无回执", "No evidence"],
    definition: ["流程说明", "Definition"],
  };
  const pair = labels[status] || labels.unknown;
  return bilingual(lang, pair[0], pair[1]);
}

function cronStatusLabel(value: string | undefined, lang: UiLanguage): string {
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
    finished: ["退出正常", "Exited normally"],
    incomplete: ["待补齐", "Incomplete"],
  };
  if (value && map[value]) return bilingual(lang, map[value][0], map[value][1]);
  return value || "—";
}

function makeTaskProgress(
  done: unknown,
  total: unknown,
  lang: UiLanguage,
  opts: {
    label: string;
    failed?: number | null;
    skipped?: number | null;
    stale?: boolean;
    empty?: boolean;
    waiting?: boolean;
  },
): CronGraphNodeProgress {
  const isInt = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
  if (opts.empty && total === 0) {
    return {
      mode: "empty",
      text: bilingual(lang, "无待处理项", "No work items"),
      label: opts.label,
      stale: Boolean(opts.stale),
    };
  }
  if (opts.waiting) {
    return {
      mode: "waiting",
      text: bilingual(lang, "等待上游", "Waiting upstream"),
      label: opts.label,
      stale: Boolean(opts.stale),
    };
  }
  if (
    !isInt(done) ||
    !isInt(total) ||
    !total ||
    done > total ||
    (opts.failed != null && (!isInt(opts.failed) || opts.failed > done)) ||
    (opts.skipped != null && (!isInt(opts.skipped) || opts.skipped > done))
  ) {
    return {
      mode: "unknown",
      text: bilingual(lang, "进度待回执", "Awaiting counts"),
      label: opts.label,
      stale: Boolean(opts.stale),
    };
  }
  const percent = Math.round((done / total) * 1000) / 10;
  return {
    mode: "count",
    done,
    total,
    remaining: total - done,
    failed: opts.failed ?? null,
    skipped: opts.skipped ?? null,
    percent,
    text: fmtFraction(done, total),
    percentText: `${percent}%`,
    label: opts.label,
    stale: Boolean(opts.stale),
    failurePercent: opts.failed == null ? 0 : (opts.failed / total) * 100,
    completePercent: ((done - (opts.failed || 0)) / total) * 100,
  };
}

function progressRows(
  progress: CronGraphNodeProgress | null | undefined,
  lang: UiLanguage,
): Array<[string, string | number]> {
  if (!progress) return [];
  const rows: Array<[string, string | number]> = [
    [bilingual(lang, "进度口径", "Progress scope"), progress.label || "—"],
    [
      bilingual(lang, "已处理 / 总数", "Processed / Total"),
      progress.mode === "count" ? `${progress.text} · ${progress.percentText}` : progress.text,
    ],
  ];
  if (progress.mode === "count") {
    rows.push([bilingual(lang, "待处理", "Remaining"), fmtCount(progress.remaining)]);
    if (progress.failed != null) rows.push([bilingual(lang, "失败", "Failed"), fmtCount(progress.failed)]);
    if (progress.skipped != null) rows.push([bilingual(lang, "跳过", "Skipped"), fmtCount(progress.skipped)]);
  }
  if (progress.stale) {
    rows.push([
      bilingual(lang, "进度快照", "Progress snapshot"),
      bilingual(lang, "数据已过期，显示最后一次观测", "Stale: showing the last observation"),
    ]);
  }
  return rows;
}

function bevRecoveryEdges(source: string, retry: string, local: string, lang: UiLanguage): CronGraphEdge[] {
  const edge = (a: string, b: string, label = "", optional = false): CronGraphEdge => ({
    id: `${a}:${b}`,
    source: a,
    target: b,
    label,
    optional,
  });
  return [
    edge(source, "media-verify"),
    edge(source, retry, bilingual(lang, "失败", "Failed"), true),
    edge(retry, "media-verify", bilingual(lang, "成功", "Success"), true),
    edge(retry, local, bilingual(lang, "仍失败", "Still failed"), true),
    edge(local, "media-verify", "", true),
  ];
}

function closeupEdges(lang: UiLanguage): CronGraphEdge[] {
  return [
    { id: "media-import:media-closeup", source: "media-import", target: "media-closeup" },
    ...bevRecoveryEdges("media-closeup", "media-closeup-retry", "media-closeup-local", lang),
  ];
}

function applyThirdMedia(nodes: CronGraphNode[], media: any, stale: boolean, lang: UiLanguage): void {
  const closeup = media?.closeup;
  const known = closeup?.receipt_status === "ready";
  const complete = known && media.selected > 0 && closeup.verified === media.selected;
  const status = complete ? "success" : !known ? "unknown" : closeup.attention ? "warn" : "pending";
  const progress = makeTaskProgress(closeup?.verified, media?.selected, lang, {
    stale: Boolean(stale),
    empty: media?.selected === 0,
    label: bilingual(lang, "同批目标的局部 BEV 发布验收", "Closeup BEV publication receipts for the same cohort"),
  });
  nodes.push({
    id: "media-closeup",
    data: {
      label: bilingual(lang, "局部 BEV · Orion", "Closeup BEV · Orion"),
      detail: bilingual(lang, "40秒 · 400帧 · t0=20秒", "40s · 400 frames · t0=20s"),
      status: stale ? "unknown" : status,
      stateLabel: stale
        ? stateLabelOf("unknown", lang)
        : closeup?.attention
          ? bilingual(lang, "待排查 / 验收", "Needs review / verification")
          : stateLabelOf(status, lang),
      progress,
      timingText: bilingual(lang, "独立验收 / 发布", "Verify / Publish independently"),
      issues: closeup?.attention_ids || [],
      rows: [
        ...progressRows(progress, lang),
        [bilingual(lang, "待队列处理", "Queued"), fmtCount(closeup?.queued)],
        [bilingual(lang, "待排查 / 验收", "Needs review / verification"), fmtCount(closeup?.attention)],
        [bilingual(lang, "身份或范围待核实", "Identity / scope unconfirmed"), fmtCount(closeup?.unknown)],
        [
          bilingual(lang, "恢复路径", "Recovery path"),
          bilingual(
            lang,
            "失败子集 Orion 重试1次 → 仍失败则本地最多2次 → 验收发布",
            "Failed subset: one Orion retry → Still failed: up to two local attempts → Verify / Publish",
          ),
        ],
      ],
    },
  });

  const retry = closeup?.retry;
  const retryStatus = stale
    ? "unknown"
    : retry?.status === "completed"
      ? "success"
      : retry?.status === "partial_failed"
        ? "warn"
        : "unknown";
  const retryProgress = makeTaskProgress(retry?.processed, retry?.total, lang, {
    stale: Boolean(stale),
    failed: retry?.failed,
    label: bilingual(lang, "局部 BEV 的 Orion 重试子集（含失败）", "Closeup BEV Orion retry subset, including failures"),
  });
  nodes.push({
    id: "media-closeup-retry",
    data: {
      label: bilingual(lang, "局部 Orion 重试", "Closeup Orion retry"),
      detail: bilingual(lang, "仅失败子集 · 1次", "Failed subset only · Once"),
      status: retryStatus,
      stateLabel: stateLabelOf(retryStatus, lang),
      progress: retryProgress,
      timingText: bilingual(lang, "与 BEV 相同策略", "Same policy as BEV"),
      issues: [],
      rows: [
        ...progressRows(retryProgress, lang),
        [bilingual(lang, "重试次数上限", "Retry limit"), bilingual(lang, "Orion 重试1次", "One Orion retry")],
        [bilingual(lang, "原生完成 / 失败", "Native completed / failed"), fmtFraction(retry?.completed, retry?.failed)],
        [bilingual(lang, "重试证据 · CST", "Retry evidence · CST"), fmtTime(retry?.evidence_at, lang)],
      ],
    },
  });

  const fallback = closeup?.fallback;
  const recovered = fallback?.verified;
  const fallbackStatus = stale
    ? "unknown"
    : fallback?.source_blocked > 0
      ? "warn"
      : recovered > 0
        ? "success"
        : "unknown";
  nodes.push({
    id: "media-closeup-local",
    data: {
      label: bilingual(lang, "局部本地兜底", "Closeup fallback"),
      detail: bilingual(lang, "全局2并发 · 最多2次", "Global concurrency 2 · Up to 2 attempts"),
      status: fallbackStatus,
      stateLabel: stale
        ? stateLabelOf("unknown", lang)
        : fallback?.source_blocked > 0
          ? bilingual(lang, "源异常待处理", "Source failures pending")
          : recovered > 0
            ? bilingual(lang, "本地恢复已发布", "Local recovery published")
            : stateLabelOf(fallbackStatus, lang),
      timingText: bilingual(lang, "与 BEV 相同策略", "Same policy as BEV"),
      issues: fallback?.source_blocked_ids || [],
      rows: [
        [bilingual(lang, "本地恢复发布", "Published via local recovery"), fmtCount(recovered)],
        [bilingual(lang, "已有执行证据的案例", "Cases with execution evidence"), fmtCount(fallback?.attempted_cases)],
        [bilingual(lang, "已登记恢复子集", "Registered recovery subset"), fmtCount(fallback?.registered)],
        [bilingual(lang, "源异常 / 缺口", "Source errors / gaps"), fmtCount(fallback?.source_blocked)],
        [bilingual(lang, "回执时间 · CST", "Evidence time · CST"), fmtTime(fallback?.evidence_at, lang)],
      ],
    },
  });

  const closeupNodes = nodes.splice(-3);
  const verificationIndex = nodes.findIndex((n) => n.id === "media-verify");
  nodes.splice(verificationIndex < 0 ? nodes.length : verificationIndex, 0, ...closeupNodes);

  const all = media?.selected > 0 && media?.triple_verified === media?.selected;
  for (const n of nodes.filter((item) => ["media-verify", "media-ready"].includes(item.id))) {
    if (n.id === "media-verify") n.data.label = bilingual(lang, "三媒体验证", "Verify three videos");
    n.data.detail = fmtFraction(media?.triple_verified, media?.selected);
    n.data.progress = makeTaskProgress(media?.triple_verified, media?.selected, lang, {
      stale: Boolean(stale),
      empty: media?.selected === 0,
      label: bilingual(lang, "同批 Camera ∩ BEV ∩ 局部 BEV", "Same cohort: Camera ∩ BEV ∩ Closeup BEV"),
    });
    n.data.rows = [
      ...progressRows(n.data.progress, lang),
      [bilingual(lang, "原双媒体已验证", "Original two videos verified"), fmtFraction(media?.verified, media?.selected)],
      [
        bilingual(lang, "分别发布", "Independent publication"),
        bilingual(lang, "各项验收后即发布；不等待三项齐全", "Each verified track publishes without waiting for the others"),
      ],
    ];
    if (!all) n.data.status = !known ? "unknown" : closeup.attention || media?.failure_count ? "warn" : "pending";
    else if (n.id === "media-verify") n.data.status = "success";
    if (stale) n.data.status = "unknown";
    n.data.stateLabel = stateLabelOf(n.data.status, lang);
    if (n.id === "media-verify" && known && !all && !stale) {
      n.data.stateLabel = bilingual(lang, "待补齐", "Incomplete");
    }
    if (n.id === "media-ready") {
      n.data.status = "unknown";
      n.data.stateLabel = bilingual(lang, "按单项回执发布", "Per-track publication");
    }
  }
}

function buildPlanningTextNodes(text: any, hasError: boolean, lang: UiLanguage): CronGraphNode[] {
  const known = text?.status === "ready";
  const pipeline = text?.pipeline || {};
  const runtime = pipeline.runtime || {};
  const observed = !hasError && runtime.status === "ready";
  const selected = text?.selected;
  const terminal = (text?.collected || 0) + (text?.partial_source || 0) + (text?.failed || 0);
  const fallback =
    known &&
    [selected, terminal, text?.pending || 0].every((v) => Number.isInteger(v) && v >= 0) &&
    terminal + (text?.pending || 0) <= selected;
  const savedStage = {
    total: selected,
    completed: terminal,
    running: 0,
    blocked: 0,
    state: selected > 0 && terminal === selected ? "complete" : "pending",
  };
  const definitions: Array<[string, string, string]> = [
    ["text-input", bilingual(lang, "目标登记", "Register targets"), bilingual(lang, "准确 Issue / trip / 时间", "Exact Issue / trip / time")],
    ["text-export", bilingual(lang, "Orion 文本采集", "Collect text on Orion"), "PlanningDebug"],
    ["text-verify", bilingual(lang, "文字验收", "Validate text"), bilingual(lang, "身份 · 原文 · 时序", "Identity · Raw · Timing")],
    ["text-index", bilingual(lang, "索引发布", "Publish index"), "Issue ID + timestamp"],
    ["text-recover", bilingual(lang, "按需恢复", "Recover if needed"), bilingual(lang, "复用已完成窗口", "Reuse saved windows")],
    ["text-source", bilingual(lang, "源缺口留证", "Record source gaps"), bilingual(lang, "有效帧和异常均保留", "Keep valid frames and errors")],
  ];
  const phaseLabels: Record<string, string> = {
    complete: bilingual(lang, "已完成", "Complete"),
    running: bilingual(lang, "运行中", "Running"),
    pending: bilingual(lang, "尚未开始 · 自动接续", "Not started · Resumes automatically"),
    blocked: bilingual(lang, "待处理 · 保留断点", "Needs attention · Checkpoint saved"),
    unknown: bilingual(lang, "状态待核实", "Awaiting status evidence"),
  };
  const statusMap: Record<string, string> = {
    complete: "success",
    running: "running",
    pending: "pending",
    blocked: "failed",
    not_required: "skipped",
  };

  return definitions.map(([id, label, detail], index) => {
    let receipt = pipeline.stages?.[id];
    if (!receipt && fallback && index < 4) receipt = { ...savedStage };
    if (!receipt && fallback && id === "text-source") {
      const count = (text?.partial_source || 0) + (text?.failed || 0);
      receipt = { total: count, completed: count, running: 0, blocked: 0, state: count ? "complete" : "not_required" };
    }
    const valid =
      known &&
      receipt &&
      ["total", "completed", "running", "blocked"].every((k) => Number.isInteger(receipt[k]) && receipt[k] >= 0) &&
      receipt.completed + receipt.running + receipt.blocked <= receipt.total;
    let phase = valid ? receipt.state : "unknown";
    if (phase === "complete" && (receipt.total === 0 || receipt.completed !== receipt.total)) phase = "unknown";
    if (phase === "running" && (!observed || !receipt.running)) phase = "unknown";
    const status = statusMap[phase] || "unknown";
    let stateLabel = phaseLabels[phase] || phaseLabels.unknown;
    if (phase === "not_required") {
      stateLabel =
        id === "text-recover"
          ? bilingual(lang, "当前无待恢复项", "No recovery pending")
          : bilingual(lang, "当前无源异常", "No source issues");
    }
    if (id === "text-export" && phase === "pending" && runtime.queued) {
      stateLabel = bilingual(lang, "已排队 · 等待 Orion", "Queued · Awaiting Orion");
    }
    if (id === "text-verify" && phase === "pending" && runtime.awaiting_result) {
      stateLabel = bilingual(lang, "等待小结果验收", "Awaiting result validation");
    }
    if (id === "text-index" && phase === "complete" && text?.failed) {
      stateLabel = bilingual(lang, "已发布 · 源异常已留证", "Published · Source errors recorded");
    } else if (id === "text-index" && phase === "complete" && text?.partial_source) {
      stateLabel = bilingual(lang, "已发布 · 源缺口已留证", "Published · Source gaps recorded");
    }

    const rows: Array<[string, string | number]> = [
      [bilingual(lang, "已完成 / 阶段目标", "Completed / Stage targets"), valid ? `${receipt.completed} / ${receipt.total}` : "—"],
      [
        bilingual(lang, "自动接续", "Automatic continuation"),
        pipeline.durable_queue === "ready"
          ? bilingual(lang, "调度器先对账已有 Job 和结果，只接续未完成项", "Reconcile existing jobs and resume unfinished work")
          : bilingual(lang, "调度回执暂不可用；已完成结果仍保留", "Scheduling evidence unavailable; saved results remain valid"),
      ],
    ];
    if (id === "text-export") {
      rows.push(
        [bilingual(lang, "当前运行 / 排队", "Running / Queued now"), observed ? `${runtime.running || 0} / ${runtime.queued || 0}` : "—"],
        [bilingual(lang, "Orion 全局并发上限", "Global Orion concurrency limit"), runtime.max_concurrency ?? "—"],
      );
    }
    if (id === "text-index" || id === "text-source") {
      rows.push(
        [bilingual(lang, "真实有帧 / 同批目标", "With actual frames / Same cohort"), known ? `${text.with_frames} / ${selected}` : "—"],
        [bilingual(lang, "完整 / 源缺口 / 源失败", "Complete / Source gaps / Source failures"), known ? `${text.collected} / ${text.partial_source} / ${text.failed}` : "—"],
      );
    }
    if (runtime.observed_at) {
      rows.push([bilingual(lang, "运行观测 · CST", "Runtime observed · CST"), fmtTime(runtime.observed_at, lang)]);
    }
    const progress =
      phase === "not_required"
        ? null
        : makeTaskProgress(valid ? receipt.completed : null, valid ? receipt.total : null, lang, {
            stale: Boolean(hasError),
            label: bilingual(lang, "按同批阶段回执计数", "Same-cohort stage receipts"),
          });
    return { id, data: { label, detail, status, stateLabel, progress, rows, issues: [] } };
  });
}

export interface BuildCronGraphOptions {
  selectedVersion?: string;
  selectedDay?: string;
  selectedNode?: string;
  error?: boolean;
  active?: boolean;
  definitionLane?: "" | "main" | "media";
  lang: UiLanguage;
  theme: ColorTheme;
}

export function buildCronGraphModel(data: any, opts: BuildCronGraphOptions): CronGraphModel {
  const { lang, theme, selectedVersion = "", selectedDay = "", selectedNode = "", error = false, active = true, definitionLane = "" } = opts;
  const incremental = data?.incremental;
  const incrementalEnabled = Boolean(incremental?.enabled || selectedVersion);

  if (incrementalEnabled && !selectedDay) {
    const source = incremental?.enabled
      ? incremental
      : { enabled: true, stale: true, families: [], versions: [], datasets: [], states: {}, media: {} };
    const families: string[] = Array.from(
      new Set<string>(
        [
          ...(source.families || []),
          ...(source.versions || []).map((v: any) => v.family),
          ...(source.datasets || []).map((d: any) => d.release_family || ""),
        ]
          .map(String)
          .filter((v) => /^\d{8}$/.test(v)),
      ),
    )
      .sort()
      .reverse();
    const family = selectedVersion || families[0] || "all";
    const ver = family === "all" ? null : source.versions?.find((v: any) => v.family === family);
    const v =
      family === "all"
        ? {
            ...source,
            stale: Boolean(source.stale || error),
            unavailable: false,
            statesUnavailable: false,
            states: source.states || {},
            media: source.media || {},
            planning_text: source.planning_text || {},
          }
        : {
            ...source,
            ...ver,
            families: [family],
            stale: Boolean(source.stale || error),
            unavailable: !ver,
            statesUnavailable: !ver || ver.states_status !== "ready",
            states: ver?.states || {},
            media: ver?.media || {},
            planning_text: ver?.planning_text || {},
          };

    const c = v.states || {};
    const m = v.media || {};
    const isFresh = !v.stale;
    const done = (c.inferred || 0) + (c.published || 0);
    const pending = (c.ready || 0) + (c.running || 0) + (c.retry_wait || 0);
    const attention = (c.needs_attention || 0) + (c.identity_conflict || 0);
    const total = done + pending + attention;
    const continuing = pending > 0 || attention > 0 || (c.inferred || 0) > 0;
    const admitted = (v.datasets || []).reduce((n: number, d: any) => n + (d.targets || 0), 0);
    const assigned = (v.datasets || []).reduce(
      (n: number, d: any) => n + Object.values(d.assigned || {}).reduce((a: number, b: any) => a + Number(b || 0), 0),
      0,
    );
    const mkNode = (
      id: string,
      label: string,
      detail: string,
      status: string,
      stateLabel: string,
      rows: Array<[string, string | number]> = [],
    ): CronGraphNode => ({
      id,
      data: {
        label,
        detail,
        status: isFresh ? status : "unknown",
        stateLabel: isFresh ? stateLabel : bilingual(lang, "观测过期", "Stale observation"),
        rows,
        issues: [],
      },
    });
    const rolling = bilingual(lang, "分批持续处理", "Streaming per case");
    const mainNodes: CronGraphNode[] = [
      mkNode("main-schedule", bilingual(lang, "增量发现", "Discover"), "07:00 / 19:00 CST", "success", bilingual(lang, "周期调度", "Scheduled polling")),
      mkNode("main-query", bilingual(lang, "版本分流", "Route by version"), (v.families || []).map((x: string) => x.slice(4)).join(" / "), "success", bilingual(lang, "独立归集", "Separate worksets")),
      mkNode("main-wait", bilingual(lang, "等待源信息", "Await source"), String(c.waiting_metadata || 0), "pending", bilingual(lang, "不阻塞其他 case", "Other cases continue")),
      mkNode("main-verify", bilingual(lang, "版本统一抽样", "Version sampling"), bilingual(lang, "固定种子 · 每 case 约10%", "Frozen seed · 10% probability per case"), "success", bilingual(lang, "固定策略", "Frozen policy")),
      mkNode(
        "main-infer",
        bilingual(lang, "采集与推理", "Collect / Infer"),
        `${done} / ${total}`,
        attention ? "warn" : pending ? "running" : "success",
        pending ? bilingual(lang, "仍有待处理", "Cases still pending") : bilingual(lang, "当前已处理", "Current cases processed"),
        [
          [bilingual(lang, "已推理", "Inferred"), done],
          [bilingual(lang, "待推理 / 重试", "Queued / Retry"), pending],
          [bilingual(lang, "待核实", "Needs attention"), attention],
        ],
      ),
      mkNode(
        "main-publish",
        bilingual(lang, "Trail 回刷", "Trail publication"),
        `${c.published || 0} / ${done}`,
        continuing ? "running" : "success",
        continuing ? bilingual(lang, "已完成结果持续回刷", "Streaming finished results") : bilingual(lang, "已有结果已回刷", "Existing results published"),
        [
          [bilingual(lang, "已完成推理", "Finished inference"), done],
          [bilingual(lang, "已回刷", "Published"), c.published || 0],
        ],
      ),
    ];
    mainNodes[4].data.progress = makeTaskProgress(done, total, lang, {
      stale: !isFresh,
      label: bilingual(lang, "当前准入队列", "Current admitted queue"),
    });
    mainNodes[5].data.progress = makeTaskProgress(c.published || 0, done, lang, {
      stale: !isFresh,
      label: bilingual(lang, "已完成推理的结果", "Finished inference results"),
    });

    const mediaPending = (m.verified || 0) < (m.selected || 0);
    const mediaNodes: CronGraphNode[] = [
      mkNode("media-source", bilingual(lang, "低置信＋抽样", "Low confidence + sample"), String(m.selected || 0), continuing ? "running" : "success", continuing ? bilingual(lang, "持续纳入", "Continuing admissions") : bilingual(lang, "当前目标", "Current targets")),
      mkNode("media-import", bilingual(lang, "统一 Run 与数据集", "Unified Run / Dataset"), `${assigned} / ${admitted}`, assigned < admitted || continuing ? "running" : "success", continuing ? bilingual(lang, "分批导入与分配", "Incremental import / assignment") : bilingual(lang, "当前成员已分配", "Current members assigned")),
      mkNode("media-camera", "Camera", bilingual(lang, "全局4并发", "Global concurrency 4"), mediaPending ? "running" : "success", mediaPending ? rolling : bilingual(lang, "当前媒体已验证", "Current media verified")),
      mkNode("media-orion", "Orion BEV", bilingual(lang, "全局≤1000并发", "Global concurrency ≤1000"), mediaPending ? "running" : "success", mediaPending ? rolling : bilingual(lang, "当前媒体已验证", "Current media verified")),
      mkNode("media-retry", bilingual(lang, "Orion 重试", "Orion retry"), bilingual(lang, "仅失败子集 · 1次", "Failed subset only · Once"), "unknown", bilingual(lang, "按单项回执判定", "Requires attempt receipts")),
      mkNode("media-local", bilingual(lang, "本地兜底", "Local fallback"), bilingual(lang, "全局2并发 · 最多2次", "Global concurrency 2 · Up to 2 attempts"), "unknown", bilingual(lang, "按单项回执判定", "Requires attempt receipts")),
      mkNode("media-verify", bilingual(lang, "双媒体验证", "Dual media verification"), `${m.verified || 0} / ${m.selected || 0}`, m.failure_count ? "warn" : mediaPending ? "running" : "success", mediaPending ? bilingual(lang, "逐条验证中", "Verifying per case") : bilingual(lang, "当前目标已验证", "Current targets verified")),
      mkNode("media-ready", bilingual(lang, "逐条发布 / 清理", "Publish / Clean per case"), bilingual(lang, `累计验证 ${m.verified || 0} · 满1小时后清理`, `Verified so far ${m.verified || 0} · Cleanup after 1h`), mediaPending || continuing ? "running" : "unknown", mediaPending || continuing ? rolling : bilingual(lang, "清理回执未观测", "Cleanup receipt not observed")),
    ];
    mediaNodes[6].data.progress = makeTaskProgress(m.verified || 0, m.selected || 0, lang, {
      stale: !isFresh,
      label: bilingual(lang, "当前媒体目标", "Current media targets"),
    });
    applyThirdMedia(mediaNodes, m, !isFresh, lang);
    for (const [id, count] of [
      ["media-camera", m.camera_verified],
      ["media-orion", m.bev_verified],
    ] as const) {
      const n = mediaNodes.find((item) => item.id === id);
      if (!n) continue;
      n.data.progress = makeTaskProgress(count, m.selected, lang, {
        stale: !isFresh,
        label: bilingual(lang, "同批发布验收（双媒体回执确认的覆盖）", "Same-cohort publication coverage confirmed by paired receipts"),
      });
      n.data.detail = fmtFraction(count, m.selected);
      n.data.status = !isFresh || count == null ? "unknown" : count === m.selected && m.selected > 0 ? "success" : "pending";
      n.data.stateLabel = stateLabelOf(n.data.status, lang);
    }

    if (v.statesUnavailable || v.unavailable) {
      for (const n of mainNodes.filter((item) => ["main-wait", "main-infer", "main-publish"].includes(item.id))) {
        n.data.status = "unknown";
        n.data.stateLabel = bilingual(lang, "状态暂不可用", "Status unavailable");
        n.data.detail = "—";
        n.data.rows = [];
        n.data.progress = makeTaskProgress(null, null, lang, {
          label: bilingual(lang, "所选版本队列", "Selected version queue"),
        });
      }
    }
    if (v.unavailable) {
      for (const n of mediaNodes) {
        n.data.status = "unknown";
        n.data.stateLabel = bilingual(lang, "状态暂不可用", "Status unavailable");
        n.data.detail = "—";
        n.data.rows = [];
        n.data.progress = null;
      }
    }

    const textNodes = buildPlanningTextNodes(v.planning_text || {}, Boolean(error), lang);
    const edge = (a: string, b: string, optional = false): CronGraphEdge => ({
      id: `${a}:${b}`,
      source: a,
      target: b,
      optional,
    });
    let lanes: CronGraphLane[] = [
      { id: "main-lane", label: bilingual(lang, "按版本增量处理", "Version incremental processing"), nodes: mainNodes },
      { id: "media-lane", label: bilingual(lang, "平台与独立媒体", "Platform and independent media"), nodes: mediaNodes },
    ];
    let edges: CronGraphEdge[] = [
      edge("main-schedule", "main-query"),
      edge("main-query", "main-wait", true),
      edge("main-wait", "main-verify", true),
      edge("main-query", "main-verify"),
      edge("main-verify", "main-infer"),
      edge("main-infer", "main-publish"),
      edge("main-infer", "media-source", true),
      edge("media-source", "media-import"),
      ...closeupEdges(lang),
      edge("media-import", "media-camera"),
      edge("media-import", "media-orion"),
      edge("media-camera", "media-verify"),
      ...bevRecoveryEdges("media-orion", "media-retry", "media-local", lang),
      edge("media-verify", "media-ready"),
    ];
    if (definitionLane !== "main") {
      lanes.push({
        id: "text-lane",
        label: bilingual(lang, "规划约束文本 · 独立队列自动接续", "Planning text · Independent resumable queue"),
        nodes: textNodes,
      });
      edges.push(
        edge("media-source", "text-input", true),
        edge("text-input", "text-export"),
        edge("text-export", "text-verify"),
        edge("text-verify", "text-index"),
        edge("text-export", "text-recover", true),
        edge("text-recover", "text-export", true),
        edge("text-verify", "text-source", true),
        edge("text-source", "text-index", true),
      );
    }
    if (definitionLane) {
      lanes = lanes.filter((x) => x.id === `${definitionLane}-lane` || (definitionLane === "media" && x.id === "text-lane"));
      const ids = new Set(lanes.flatMap((x) => x.nodes.map((n) => n.id)));
      edges = edges.filter((e) => ids.has(e.source) && ids.has(e.target));
      lanes.forEach((l) =>
        l.nodes.forEach((n) => {
          n.data.status = "definition";
          n.data.stateLabel = stateLabelOf("definition", lang);
          n.data.progress = null;
        }),
      );
    }
    return {
      lanes,
      edges,
      selectedNode,
      definition: Boolean(definitionLane),
      active: isFresh && active,
      theme,
      ui: {
        minimap: bilingual(lang, "流程缩略图", "Workflow minimap"),
        loading: bilingual(lang, "加载运行图…", "Loading graph…"),
        error: bilingual(lang, "运行图暂不可用", "Graph unavailable"),
      },
    };
  }

  // Legacy daily batch view
  const runs = (data?.overview?.daily?.runs || []).filter((r: any) => /^daily-\d{4}-\d{2}-\d{2}$/.test(r.id));
  const day = selectedDay || runs[0]?.target_date_cst || "";
  const run = runs.find((r: any) => r.target_date_cst === day);
  const media = data?.media_daily?.runs?.find((r: any) => r.day === day);
  const daily = data?.overview?.daily;
  const runtime = data?.media_daily;
  const launches = [...(daily?.launches || []), ...(daily?.recoveries || [])]
    .filter((item: any) => item.target_date_cst === run?.target_date_cst)
    .sort((a: any, b: any) => String(b.started_at || "").localeCompare(String(a.started_at || "")));
  const launch = launches[0];
  const terminal = ["complete", "complete_with_gaps"].includes(run?.state);
  const empty = run?.health === "empty";
  const mainStale = Boolean(
    !data?.overview ||
      data.overview.stale ||
      data.overview.collector_error ||
      Date.now() / 1000 - (data.overview.collected_at || 0) > 90 ||
      error,
  );
  const activeRun = !mainStale && run?.health === "running";
  const mediaStale = Boolean(!runtime || runtime.stale || runtime.controller_error || error);
  const mkLegacyNode = (
    id: string,
    label: string,
    detail: string,
    status: string,
    rows: Array<[string, string | number]> = [],
    issues: string[] = [],
  ): CronGraphNode => ({
    id,
    data: { label, detail, status, stateLabel: stateLabelOf(status, lang), rows, issues },
  });
  const progressState = (stage: string) =>
    activeRun && run?.stage === stage ? "running" : run?.health === "failed" && run?.stage === stage ? "failed" : "unknown";

  const mainNodes: CronGraphNode[] = [
    mkLegacyNode(
      "main-schedule",
      bilingual(lang, "定时启动", "Schedule"),
      launch ? fmtTime(launch.started_at, lang) : "09:00 CST",
      launch?.started_at ? "success" : "pending",
      [
        [bilingual(lang, "最近调度退出", "Scheduler exit"), launch ? `${cronStatusLabel(launch.state, lang)} · exit ${fmtCount(launch.returncode)}` : "—"],
        [bilingual(lang, "下次运行", "Next run"), fmtTime(daily?.next_run_at, lang)],
      ],
    ),
    mkLegacyNode(
      "main-query",
      bilingual(lang, "查询 / 冻结选集", "Query / Freeze cohort"),
      `${bilingual(lang, "选中", "Selected")} ${fmtCount(run?.selected)}`,
      run?.selected != null ? "success" : "unknown",
      [
        [bilingual(lang, "目标日期", "Target day"), day || "—"],
        [bilingual(lang, "选中", "Selected"), fmtCount(run?.selected)],
      ],
    ),
    mkLegacyNode(
      "main-infer",
      bilingual(lang, "采集 / 模型推理", "Collect / Infer"),
      fmtFraction(run?.inferred, run?.selected),
      empty ? "skipped" : terminal ? (run.skipped > 0 ? "warn" : "success") : run?.state === "inferred" ? "success" : progressState("inference"),
      [
        [bilingual(lang, "已推理", "Inferred"), fmtCount(run?.inferred)],
        [bilingual(lang, "跳过", "Skipped"), fmtCount(run?.skipped)],
      ],
      [...(run?.skipped_cases || []), ...(run?.failure_details || [])].map((row: any) => row.issue_id),
    ),
    mkLegacyNode(
      "main-publish",
      bilingual(lang, "Trail 回刷", "Trail publication"),
      fmtFraction(run?.published, run?.inferred),
      empty
        ? "skipped"
        : terminal || (run?.published != null && run?.published === run?.inferred && run?.inferred > 0)
          ? "success"
          : progressState("publication"),
      [
        [bilingual(lang, "已回刷", "Published"), fmtCount(run?.published)],
        [bilingual(lang, "已验证", "Verified"), fmtCount(run?.verified)],
      ],
    ),
    mkLegacyNode(
      "main-verify",
      bilingual(lang, "抽样 / 验证", "Sample / Verify"),
      `${bilingual(lang, "验证", "Verified")} ${fmtCount(run?.verified)}`,
      empty ? "skipped" : terminal ? "success" : progressState("sample_hook"),
      [
        [bilingual(lang, "最终状态", "Final state"), cronStatusLabel(run?.health || "unknown", lang)],
        [bilingual(lang, "更新 · CST", "Updated · CST"), fmtTime(run?.updated_at, lang)],
      ],
    ),
  ];

  const allMedia = Boolean(media && media.selected > 0 && media.verified === media.selected);
  const noMedia = media?.state === "empty" && media.selected === 0;
  const mediaActive = !mediaStale && media?.state === "collecting";
  const retryObserved = media?.retry_state && media.retry_state !== "not_observed";
  const recoveryUnneeded =
    noMedia || (allMedia && media.original_orion_total === media.selected && media.original_orion_failed === 0);

  const mediaNodes: CronGraphNode[] = [
    mkLegacyNode("media-source", bilingual(lang, "低置信度 / 抽样", "Low confidence / Sample"), `${day || "—"} · ${fmtCount(media?.selected)}`, media?.selected > 0 || noMedia ? "success" : runtime ? "pending" : "unknown"),
    mkLegacyNode("media-import", bilingual(lang, "Run 导入 / 分配", "Import / Assign"), `${fmtCount(media?.imported)} / ${fmtCount(media?.assigned)}`, noMedia ? "skipped" : media?.imported === media?.selected && media?.assigned === media?.selected && media?.selected > 0 ? "success" : media ? "pending" : "unknown"),
    mkLegacyNode("media-camera", "Camera · ±20s", fmtFraction(media?.camera_verified, media?.selected), noMedia ? "skipped" : allMedia ? "success" : mediaActive ? "running" : "unknown"),
    mkLegacyNode("media-orion", "BEV · Orion", `${bilingual(lang, "验证", "Verified")} ${fmtCount(media?.bev_verified)}`, noMedia ? "skipped" : allMedia ? (media.original_orion_failed > 0 ? "warn" : "success") : mediaActive ? "running" : "unknown"),
    mkLegacyNode("media-retry", bilingual(lang, "Orion 重试 ×1", "Orion retry ×1"), retryObserved ? `${fmtCount(media?.retry_completed)}` : bilingual(lang, "未观测到执行", "No execution observed"), recoveryUnneeded ? "skipped" : retryObserved ? (media.retry_state === "completed" ? "success" : media.retry_state === "partial_failed" ? "warn" : "unknown") : "unknown"),
    mkLegacyNode("media-local", bilingual(lang, "本地兜底 · 最多2次", "Local · At most 2 tries"), media?.local_attempts ? `${media.local_attempts}` : bilingual(lang, "未观测到执行", "No execution observed"), recoveryUnneeded ? "skipped" : media?.local_attempts ? (media.local_verified > 0 ? "success" : "warn") : "unknown"),
    mkLegacyNode("media-verify", bilingual(lang, "双媒体验证", "Verify both videos"), fmtFraction(media?.verified, media?.selected), noMedia ? "skipped" : allMedia ? "success" : media?.state === "media_failed" ? "failed" : mediaActive ? "running" : "unknown", [], media?.failure_ids || []),
    mkLegacyNode("media-ready", bilingual(lang, "平台就绪", "Platform ready"), media ? cronStatusLabel(media.state, lang) : bilingual(lang, "等待当日回执", "Awaiting daily receipt"), noMedia ? "skipped" : allMedia && media.assigned === media.selected ? "success" : media?.state === "complete_with_gaps" ? "warn" : media?.state === "media_failed" ? "failed" : "pending"),
  ];

  applyThirdMedia(mediaNodes, media, mediaStale, lang);
  for (const n of mainNodes) {
    n.data.timing = run?.stage_timings?.[n.id];
    n.data.timingText =
      n.id === "main-schedule"
        ? bilingual(lang, "定时触发", "Scheduled event")
        : fmtTimingText(n.data.timing, lang, true, mainStale);
    n.data.rows = [...(n.data.rows || []), ...fmtTimingRows(n.data.timing, lang, mainStale)];
  }
  const edge = (source: string, target: string, label = "", optional = false): CronGraphEdge => ({
    id: `${source}:${target}`,
    source,
    target,
    label,
    optional,
  });
  const mainEdges = mainNodes.slice(1).map((n, i) => edge(mainNodes[i].id, n.id));
  const mediaEdges: CronGraphEdge[] = [
    ...closeupEdges(lang),
    edge("media-source", "media-import"),
    edge("media-import", "media-camera"),
    edge("media-import", "media-orion"),
    edge("media-camera", "media-verify"),
    ...bevRecoveryEdges("media-orion", "media-retry", "media-local", lang),
    edge("media-verify", "media-ready"),
  ];
  let lanes: CronGraphLane[] = [
    { id: "main-lane", label: bilingual(lang, "推理回刷", "Inference / publication"), nodes: mainNodes },
    { id: "media-lane", label: bilingual(lang, "平台与媒体", "Platform / media"), nodes: mediaNodes },
  ];
  let edges: CronGraphEdge[] = [
    ...mainEdges,
    ...mediaEdges,
    edge("main-verify", "media-source", bilingual(lang, "完成回执 · 旁路不反向阻塞", "Completion receipt · No reverse blocking"), true),
  ];
  if (definitionLane) {
    lanes = lanes.filter((lane) => lane.id === `${definitionLane}-lane`);
    const ids = new Set(lanes.flatMap((lane) => lane.nodes.map((n) => n.id)));
    edges = edges.filter((e) => ids.has(e.source) && ids.has(e.target));
    lanes.forEach((lane) =>
      lane.nodes.forEach((n) => {
        n.data = {
          ...n.data,
          status: "definition",
          stateLabel: stateLabelOf("definition", lang),
          timingText: "",
          progress: null,
        };
      }),
    );
  }
  return {
    lanes,
    edges,
    selectedNode,
    definition: Boolean(definitionLane),
    active: active && !error,
    theme,
    ui: {
      minimap: bilingual(lang, "流程缩略图", "Flow overview"),
      loading: bilingual(lang, "正在加载运行图…", "Loading run graph…"),
      error: bilingual(lang, "运行图加载失败，可刷新重试。", "Graph unavailable; refresh to retry."),
    },
  };
}
