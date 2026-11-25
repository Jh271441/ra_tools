import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

const RD_UPLOAD_ENDPOINT = "https://voyager.intra.xiaojukeji.com/paladin/issue/pool/multi_update/";

interface HumanPubRow {
  issue_id: string;
  generation?: string | number;
  conclusion: string;
  label?: string | null;
  authors: string[];
  required: number;
  submitted: number;
  publication_armed?: number;
  sync_state: string;
  checked_at?: string | null;
  error_code?: string | null;
  objections: Array<{ author: string; label: string }>;
}

interface HumanPubResponse {
  items: HumanPubRow[];
  counts: Record<string, number>;
  total: number;
  page: number;
  pages: number;
  page_size: number;
  field?: string;
  write_enabled?: boolean;
}

interface HumanPubPreview {
  id: string;
  items: Array<{
    issue_id: string;
    action: string;
    desired: string | null;
    eligible: boolean;
  }>;
}

interface HumanPubHistoryResponse {
  items: Array<{
    created_at: string;
    action: string;
    desired: string | null;
    state: string;
  }>;
  total: number;
  page: number;
  pages: number;
}

interface RdRow {
  issue_id: string;
  group: string;
  state?: string;
  label?: string | null;
  te_current?: string | null;
  correction_status?: string;
  authors: string[];
}

interface RdDataResponse {
  items: RdRow[];
  counts: Record<string, number>;
  total: number;
  page: number;
  pages: number;
  page_size: number;
  write_enabled?: boolean;
  snapshot?: {
    last_success_at?: string | null;
    refresh?: {
      status?: string;
      scanned?: number;
      total?: number;
      checked_at?: string | null;
    } | null;
  } | null;
}

interface RdOperationSummary {
  id: string;
  actor: string;
  state: string;
}

interface RdPreviewItem {
  issue_id: string;
  current?: string | null;
  manual_current?: { state?: string; label?: string | null } | null;
  rd_current?: string | null;
  desired?: string | null;
  status: string;
  eligible: boolean;
}

interface RdPreviewResult {
  issue_id: string;
  state?: string;
  phase?: string;
  observed?: string | null;
  reason?: string;
}

interface RdReceipt {
  id: string;
  mode?: string;
  state: string;
  reason?: string;
  policy_version?: number;
  baselines?: string;
  history_operation_id?: string;
  audit_error?: boolean;
  refresh?: { status?: string } | null;
  progress?: {
    stage?: string;
    checked?: number;
    check_total?: number;
    verified?: number;
    total?: number;
    active?: number;
    waiting?: number;
    elapsed_seconds?: number;
  } | null;
  scope?: {
    total?: number;
    excluded?: number;
    blocked?: number;
    source?: {
      kind?: string;
      filename?: string;
      sheet?: string;
      sha256?: string;
      duplicates?: number;
    } | null;
  } | null;
  items: RdPreviewItem[];
  results: RdPreviewResult[];
}

function isHumanPublicationActive(baselines: string[], modeParam: string): boolean {
  return (
    baselines.length > 0 &&
    baselines.every((id) => /^version-20\d{6}$/.test(id) && id.slice(8) >= "20261106") &&
    modeParam !== "te-correction"
  );
}

function isValidSingleVersion(baselines: string[]): boolean {
  return baselines.length === 1 && /^version-20\d{6}$/.test(baselines[0]);
}

function formatCstObsTime(value: string | null | undefined, lang: UiLanguage): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(lang === "en" ? "en-GB" : "zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
  });
}

function rdStatusText(value: string, lang: UiLanguage): string {
  const names: Record<string, [string, string]> = {
    resolved: ["已完成", "Completed"],
    pending: ["待上传", "Ready to upload"],
    conflict: ["结果不同", "Different result"],
    same: ["已一致", "Already matches"],
    blocked: ["不可上传", "Blocked"],
    unchecked: ["未核对", "Not checked"],
    preparing: ["正在生成预览", "Preparing preview"],
    preview: ["预览待确认", "Preview ready"],
    preview_failed: ["预览失败", "Preview failed"],
    complete: ["已核验完成", "Verified complete"],
    needs_recheck: ["需重新核对", "Recheck required"],
    running: ["正在上传并核验", "Uploading and verifying"],
    waiting: ["等待处理", "Waiting"],
    checking: ["写前核对中", "Checking before upload"],
    uploading: ["上传中", "Uploading"],
    readback: ["读回核验中", "Verifying readback"],
    verified: ["读回一致", "Readback verified"],
    unverified: ["未确认", "Unverified"],
    intent: ["结果待核对", "Outcome needs checking"],
    not_attempted: ["未执行", "Not attempted"],
    te_empty: ["TE 为空", "TE empty"],
    rd_mismatch: ["旧预览，请重新预览", "Old preview; preview again"],
    candidate: ["待修正", "Candidate"],
    label_pending: ["待标注", "Label pending"],
    label_conflict: ["需复核", "Needs review"],
    te_unknown: ["暂无观测", "No observation"],
    outcome_unknown: ["结果暂不可查", "Outcome unavailable"],
  };
  const pair = names[value];
  return pair ? bilingual(lang, pair[0], pair[1]) : value;
}

function humanStatusText(value: string, lang: UiLanguage): string {
  const names: Record<string, [string, string]> = {
    resolved: ["已完成", "Completed"],
    pending: ["待标注", "Pending labels"],
    conflict: ["标注冲突", "Conflicting labels"],
    unassigned: ["未分配该角色", "Role not assigned"],
    unclassified: ["身份待确认", "Role needs confirmation"],
    inactive: ["来源已停用", "Source inactive"],
    none: ["未裁决", "No adjudication"],
    stale: ["裁决已失效", "Adjudication stale"],
    objection: ["有任务外异议", "Advisory objection"],
    awaiting_activation: ["历史结果待启用", "Historical publishing not activated"],
    synced: ["已同步", "Synced"],
    same: ["已一致", "Already matches"],
    not_ready: ["待结论", "Awaiting result"],
    retry_wait: ["等待重试", "Retry scheduled"],
    unverified: ["上传结果未确认", "Upload outcome unverified"],
    needs_recheck: ["需人工核对", "Needs reconciliation"],
    verified: ["读回一致", "Readback verified"],
    not_applied: ["未写入", "Not applied"],
    external_conflict: ["远端值已变化", "Remote value changed"],
    pre_read_failed: ["上传前读取失败", "Pre-upload read failed"],
    readback_failed: ["读回核验失败", "Readback failed"],
    intent: ["写入待核验", "Write awaiting verification"],
    set: ["同步结论", "Synchronize result"],
    clear: ["撤回旧结论", "Retract previous result"],
    recheck: ["核对未确认结果", "Recheck uncertain outcome"],
    blocked: ["暂无可上传结论", "No publishable result"],
  };
  const pair = names[value];
  return pair ? bilingual(lang, pair[0], pair[1]) : rdStatusText(value, lang);
}

function rdReasonText(value: string | undefined, lang: UiLanguage): string {
  if (!value) return "";
  const names: Record<string, [string, string]> = {
    preview_check_failed: [
      "预览核对失败，未执行上传。可重新预览。",
      "Preview check failed; nothing was uploaded. Create a new preview.",
    ],
    preview_interrupted: [
      "预览任务已中断，未执行上传。请重新预览。",
      "Preview interrupted; nothing was uploaded. Create a new preview.",
    ],
    preflight_failed: [
      "提交前核对未通过，未执行写入。请刷新后重新预览。",
      "Preflight check failed; nothing was written. Refresh and preview again.",
    ],
    source_changed: [
      "标注或 Trail 值已变化，未执行写入。",
      "Labels or Trail changed; nothing was written.",
    ],
    check_failed: [
      "写入前核对失败，未执行写入。",
      "Check before writing failed; nothing was written.",
    ],
    batch_stopped: [
      "批次出现异常，已停止派发后续上传。",
      "A batch failed verification; no further uploads were dispatched.",
    ],
    protected_changed: [
      "读回发现其他字段变化，已停止上传，需人工核对。",
      "Readback found changes to other fields. Upload stopped; inspect manually.",
    ],
    value_mismatch: [
      "读回值与上传值不一致，已停止上传。",
      "Readback differs from the requested value. Upload stopped.",
    ],
    readback_failed: [
      "写入后读回失败，结果未知；请重新核对 Trail。",
      "Readback failed after writing; outcome unknown. Check Trail again.",
    ],
    interrupted: [
      "执行中断，可能已写入；请重新核对 Trail。",
      "Execution was interrupted; a write may have occurred. Check Trail again.",
    ],
    receipt_unavailable: [
      "无法取得操作记录；请刷新本次结果，勿重复上传。",
      "Operation receipt unavailable. Refresh this outcome before uploading again.",
    ],
    receipt_pending: [
      "尚无执行结果，请稍后刷新本次结果；请求可能仍在处理中。",
      "No execution outcome yet. Refresh this outcome shortly; the request may still be processing.",
    ],
    audit_failed: [
      "更新记录保存失败，未上传。",
      "Could not save update history; nothing uploaded.",
    ],
    response_recovered: [
      "提交响应未收到，已找回操作记录；请以逐条核验状态为准。",
      "The submit response was lost; the operation receipt was recovered. Use the per-item verification states.",
    ],
  };
  const pair = names[value];
  return pair ? bilingual(lang, pair[0], pair[1]) : "";
}

function rdLabelText(value: string | null | undefined, lang: UiLanguage): string {
  if (!value) return "—";
  const map: Record<string, [string, string]> = {
    成功: ["正确触发（Trail：成功）", "Correct trigger (Trail: 成功)"],
    正确触发: ["正确触发", "Correct trigger"],
    误触发: ["误触发", "False trigger"],
    无需协助: ["无需协助", "No assistance needed"],
  };
  const pair = map[value];
  return pair ? bilingual(lang, pair[0], pair[1]) : value;
}

const LabelPill: React.FC<{ label?: string | null; lang: UiLanguage }> = ({ label, lang }) => {
  if (!label) return <span className="muted">—</span>;
  const canonical = label === "成功" ? "正确触发" : label;
  if (["正确触发", "误触发", "无需协助"].includes(canonical)) {
    return (
      <span className={`label-badge label-${canonical}`}>{rdLabelText(label, lang)}</span>
    );
  }
  const extra: Record<string, [string, string]> = {
    失败: ["失败", "Failed"],
    未接起: ["未接起", "Unanswered"],
    超出范围: ["超出范围", "Out of scope"],
  };
  return <>{extra[label] ? bilingual(lang, extra[label][0], extra[label][1]) : label}</>;
};

const RdStatusPill: React.FC<{ status?: string; lang: UiLanguage }> = ({ status = "", lang }) => {
  const tone = ["same", "complete", "verified"].includes(status)
    ? "ok"
    : ["conflict", "needs_recheck", "unverified"].includes(status)
      ? "warn"
      : status === "pending"
        ? "ready"
        : "neutral";
  return (
    <span className={`run-source-badge rd-status rd-status-${tone}`}>
      {rdStatusText(status, lang)}
    </span>
  );
};

const HumanStatusPill: React.FC<{ status: string; lang: UiLanguage }> = ({ status, lang }) => {
  const tone = ["conflict", "stale", "unverified", "needs_recheck"].includes(status)
    ? "rd-status-warn"
    : ["synced", "same", "verified"].includes(status)
      ? "rd-status-ok"
      : "rd-status-neutral";
  return (
    <span className={`run-source-badge rd-status ${tone}`}>
      {humanStatusText(status, lang)}
    </span>
  );
};

export interface RdResultsPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
  isAdmin: boolean;
}

export const RdResultsPage: React.FC<RdResultsPageProps> = ({
  active,
  lang,
  selectedBaselines,
  isAdmin,
}) => {
  const queryClient = useQueryClient();
  const baselinesParam = selectedBaselines.join(",");
  const initialParams = useMemo(() => new URLSearchParams(window.location.search), []);

  // Classic vs Human mode
  const [rdMode, setRdMode] = useState<"rd" | "te-correction">(() =>
    initialParams.get("mode") === "te-correction" ? "te-correction" : "rd",
  );
  const humanActive = isHumanPublicationActive(selectedBaselines, rdMode);

  // --- Human Publications (3-lane) state ---
  const [hpLane, setHpLane] = useState<"rd" | "te" | "arbitrated">(() => {
    const l = initialParams.get("lane");
    return l === "te" || l === "arbitrated" ? l : "rd";
  });
  const [hpFilters, setHpFilters] = useState(() => ({
    q: initialParams.get("q") || "",
    status: initialParams.get("status") || "all",
    page: Math.max(1, Number(initialParams.get("page")) || 1),
    page_size: (CASE_PAGE_SIZES as readonly number[]).includes(
      Number(initialParams.get("page_size")),
    )
      ? Number(initialParams.get("page_size"))
      : DEFAULT_CASE_PAGE_SIZE,
  }));
  const [hpDraft, setHpDraft] = useState({ q: hpFilters.q, status: hpFilters.status });
  const [hpSelected, setHpSelected] = useState<string[]>([]);
  const [hpPreview, setHpPreview] = useState<HumanPubPreview | null>(null);
  const [hpHistoryIssue, setHpHistoryIssue] = useState<string>(() =>
    /^cn\d+$/.test(initialParams.get("history_issue") || "")
      ? initialParams.get("history_issue")!
      : "",
  );
  const [hpHistoryPage, setHpHistoryPage] = useState<number>(() =>
    Math.max(1, Number(initialParams.get("history_page")) || 1),
  );
  const [hpHistorySize, setHpHistorySize] = useState<number>(() =>
    (CASE_PAGE_SIZES as readonly number[]).includes(Number(initialParams.get("history_size")))
      ? Number(initialParams.get("history_size"))
      : DEFAULT_CASE_PAGE_SIZE,
  );
  const [hpBusy, setHpBusy] = useState(false);
  const [hpError, setHpError] = useState("");
  const [hpNotice, setHpNotice] = useState("");

  // --- Classic RD / TE Correction state ---
  const [rdFilters, setRdFilters] = useState(() => ({
    q: initialParams.get("q") || "",
    status: initialParams.get("status") || "all",
    page: Math.max(1, Number(initialParams.get("page")) || 1),
    page_size: (CASE_PAGE_SIZES as readonly number[]).includes(
      Number(initialParams.get("page_size")),
    )
      ? Number(initialParams.get("page_size"))
      : DEFAULT_CASE_PAGE_SIZE,
  }));
  const [rdDraft, setRdDraft] = useState({ q: rdFilters.q, status: rdFilters.status });
  const [rdSelected, setRdSelected] = useState<string[]>([]);
  const [rdAllSelected, setRdAllSelected] = useState(false);
  const [rdExcluded, setRdExcluded] = useState<string[]>([]);
  const [rdExcelFile, setRdExcelFile] = useState<File | null>(null);
  const [rdBusy, setRdBusy] = useState(false);
  const [rdBusyAction, setRdBusyAction] = useState("");
  const [rdError, setRdError] = useState("");
  const [rdOperations, setRdOperations] = useState<RdOperationSummary[]>([]);
  const [rdPreview, setRdPreview] = useState<RdReceipt | null>(null);
  const [rdPreviewPage, setRdPreviewPage] = useState(1);
  const [rdPreviewPageSize, setRdPreviewPageSize] = useState<number>(DEFAULT_CASE_PAGE_SIZE);
  const [rdTeRefresh, setRdTeRefresh] = useState<{
    status?: string;
    scanned?: number;
    total?: number;
    checked_at?: string | null;
  } | null>(null);

  const excelInputRef = useRef<HTMLInputElement | null>(null);
  const rdSearchRef = useRef<HTMLTextAreaElement | null>(null);

  // Reset selections when baselines or mode changes
  useEffect(() => {
    setHpSelected([]);
    setHpPreview(null);
    setHpNotice("");
    setHpError("");
    setRdSelected([]);
    setRdAllSelected(false);
    setRdExcluded([]);
    setRdExcelFile(null);
    setRdPreview(null);
    setRdError("");
    setRdOperations([]);
  }, [baselinesParam, rdMode]);

  // URL sync for Human mode
  const syncHpUrl = useCallback(
    (overrides?: {
      lane?: "rd" | "te" | "arbitrated";
      filters?: typeof hpFilters;
      historyIssue?: string;
      historyPage?: number;
      historySize?: number;
    }) => {
      if (!active || !humanActive) return;
      const url = new URL(withWorkbenchBase("/rd-results"), window.location.origin);
      if (baselinesParam) url.searchParams.set("baselines", baselinesParam);
      const l = overrides?.lane ?? hpLane;
      const f = overrides?.filters ?? hpFilters;
      const hi = overrides?.historyIssue ?? hpHistoryIssue;
      const hp = overrides?.historyPage ?? hpHistoryPage;
      const hs = overrides?.historySize ?? hpHistorySize;
      url.searchParams.set("lane", l);
      url.searchParams.set("q", f.q);
      url.searchParams.set("status", f.status);
      url.searchParams.set("page", String(f.page));
      url.searchParams.set("page_size", String(f.page_size));
      if (hi) {
        url.searchParams.set("history_issue", hi);
        url.searchParams.set("history_page", String(hp));
        url.searchParams.set("history_size", String(hs));
      }
      window.history.replaceState(
        { ...(window.history.state || {}), page: "rd-results" },
        "",
        `${url.pathname}${url.search}`,
      );
    },
    [active, humanActive, baselinesParam, hpLane, hpFilters, hpHistoryIssue, hpHistoryPage, hpHistorySize],
  );

  // URL sync for Classic mode
  const syncRdUrl = useCallback(
    (overrides?: { mode?: "rd" | "te-correction"; filters?: typeof rdFilters }) => {
      if (!active || humanActive) return;
      const url = new URL(withWorkbenchBase("/rd-results"), window.location.origin);
      if (baselinesParam) url.searchParams.set("baselines", baselinesParam);
      const m = overrides?.mode ?? rdMode;
      const f = overrides?.filters ?? rdFilters;
      if (m === "te-correction") url.searchParams.set("mode", m);
      url.searchParams.set("q", f.q);
      url.searchParams.set("status", f.status);
      url.searchParams.set("page", String(f.page));
      url.searchParams.set("page_size", String(f.page_size));
      window.history.replaceState(
        { ...(window.history.state || {}), page: "rd-results" },
        "",
        `${url.pathname}${url.search}`,
      );
    },
    [active, humanActive, baselinesParam, rdMode, rdFilters],
  );

  // Query: 3-Lane Human Publications
  const hpQuery = useQuery<HumanPubResponse>({
    queryKey: ["human-publications", baselinesParam, hpLane, hpFilters],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        baselines: baselinesParam,
        lane: hpLane,
        q: hpFilters.q,
        status: hpFilters.status,
        page: String(hpFilters.page),
        page_size: String(hpFilters.page_size),
      });
      return apiRequest<HumanPubResponse>(`/api/human-publications?${qs.toString()}`, { signal });
    },
    enabled: active && humanActive,
    refetchInterval: active && humanActive && !hpBusy && !hpPreview ? 15_000 : false,
  });

  // Query: Human Publication History for selected issue
  const hpHistoryQuery = useQuery<HumanPubHistoryResponse>({
    queryKey: ["human-publications-history", hpHistoryIssue, hpLane, hpHistoryPage, hpHistorySize],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        issue_id: hpHistoryIssue,
        lane: hpLane,
        page: String(hpHistoryPage),
        page_size: String(hpHistorySize),
      });
      return apiRequest<HumanPubHistoryResponse>(`/api/human-publications/history?${qs.toString()}`, {
        signal,
      });
    },
    enabled: active && humanActive && Boolean(hpHistoryIssue),
  });

  const teInvalidVersion = !humanActive && rdMode === "te-correction" && !isValidSingleVersion(selectedBaselines);

  // Query: Classic RD / TE Correction
  const rdQuery = useQuery<RdDataResponse>({
    queryKey: ["rd-results-classic", baselinesParam, rdMode, rdFilters],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        baselines: baselinesParam,
        mode: rdMode,
        q: rdFilters.q,
        status: rdFilters.status,
        page: String(rdFilters.page),
        page_size: String(rdFilters.page_size),
      });
      return apiRequest<RdDataResponse>(`/api/rd-results?${qs.toString()}`, { signal });
    },
    enabled: active && !humanActive && !teInvalidVersion,
  });

  useEffect(() => {
    if (rdQuery.data?.snapshot?.refresh) {
      setRdTeRefresh(rdQuery.data.snapshot.refresh);
    }
  }, [rdQuery.data]);

  // Poll TE refresh while running
  useEffect(() => {
    if (!active || humanActive || rdMode !== "te-correction" || rdTeRefresh?.status !== "running") {
      return;
    }
    const timer = window.setInterval(async () => {
      try {
        const st = await apiRequest<{ status?: string; scanned?: number; total?: number; checked_at?: string }>(
          `/api/rd-results/te-refresh?${new URLSearchParams({ baselines: baselinesParam })}`,
        );
        setRdTeRefresh(st);
        if (st.status !== "running") {
          void queryClient.invalidateQueries({ queryKey: ["rd-results-classic"] });
        }
      } catch {
        setRdTeRefresh(null);
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [active, humanActive, rdMode, rdTeRefresh?.status, baselinesParam, queryClient]);

  // Poll classic commit progress while preview.state === 'running'
  useEffect(() => {
    if (!active || !rdPreview || rdPreview.state !== "running") return;
    const opId = rdPreview.id;
    const timer = window.setInterval(async () => {
      try {
        const next = await apiRequest<RdReceipt>(
          `/api/rd-results/operations/${encodeURIComponent(opId)}?progress_only=true`,
        );
        setRdPreview((prev) => (prev && prev.id === opId ? { ...prev, ...next } : prev));
        if (next.state !== "running") {
          void queryClient.invalidateQueries({ queryKey: ["rd-results-classic"] });
        }
      } catch {
        // retry on next tick
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [active, rdPreview?.id, rdPreview?.state, queryClient]);

  if (!active) return null;

  const labelingHref = (issueId: string) => {
    const qs = new URLSearchParams({ issue: issueId });
    if (baselinesParam) qs.set("baselines", baselinesParam);
    return withWorkbenchBase(`/case-labeling?${qs.toString()}`);
  };

  // =========================================================================
  // RENDER MODE A: 3-LANE HUMAN PUBLICATIONS (>= 20261106)
  // =========================================================================
  if (humanActive) {
    const d = hpQuery.data || null;
    const disabled = hpQuery.isLoading || hpBusy;
    const decision = hpLane === "arbitrated";
    const totalCount = d
      ? Object.entries(d.counts || {}).reduce((sum, [k, n]) => sum + (k === "objection" ? 0 : n), 0)
      : null;
    const metrics: Array<[string, number | null, string, string, string]> = [
      [
        "all",
        totalCount,
        "范围内 Issues",
        "Issues in scope",
        "M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z",
      ],
      [
        "resolved",
        d ? Number(d.counts?.resolved ?? 0) : null,
        decision ? "已裁决" : "已完成",
        decision ? "Adjudicated" : "Completed",
        "m5 12 4 4L19 6",
      ],
      [
        decision ? "none" : "pending",
        d ? Number(d.counts?.[decision ? "none" : "pending"] ?? 0) : null,
        decision ? "待裁决" : "待标注",
        decision ? "Pending decision" : "Pending labels",
        "M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
      ],
      [
        decision ? "stale" : "conflict",
        d ? Number(d.counts?.[decision ? "stale" : "conflict"] ?? 0) : null,
        "需复核",
        "Needs review",
        "m12 3 10 18H2L12 3zm0 6v5m0 3v1",
      ],
    ];

    const laneName = (lane: "rd" | "te" | "arbitrated") =>
      lane === "arbitrated"
        ? bilingual(lang, "裁决标注", "Adjudication")
        : lane === "te"
          ? bilingual(lang, "TE′ 标注", "TE′ labels")
          : bilingual(lang, "RD 标注", "RD labels");

    const fieldName =
      d?.field ||
      (hpLane === "te"
        ? "ra_review_result_sampling"
        : hpLane === "arbitrated"
          ? "ra_review_result_arbitrated"
          : "ra_rd_review_result");

    const hpStatusOptions: UiSelectOption[] = [
      "all",
      "resolved",
      "pending",
      "conflict",
      "objection",
      "stale",
      "none",
      "unassigned",
      "inactive",
      "unclassified",
    ].map((val) => ({
      value: val,
      label: val === "all" ? bilingual(lang, "全部状态", "All statuses") : humanStatusText(val, lang),
    }));

    const hpSelectionOptions: UiSelectOption[] = [
      { value: "", label: bilingual(lang, "选中操作", "Selection actions"), disabled: true },
      {
        value: "page",
        label: bilingual(lang, "选择本页", "Select this page"),
        disabled: !d?.items?.length,
      },
      {
        value: "clear",
        label: bilingual(lang, "清空选择", "Clear selection"),
        disabled: hpSelected.length === 0,
      },
    ];

    const handleHpPreview = async () => {
      if (disabled || !hpSelected.length) return;
      setHpBusy(true);
      setHpError("");
      try {
        const res = await apiRequest<HumanPubPreview>("/api/human-publications/preview", {
          method: "POST",
          body: { lane: hpLane, baselines: baselinesParam, issue_ids: hpSelected },
        });
        setHpPreview(res);
      } catch (err) {
        setHpError(err instanceof Error ? err.message : String(err));
      } finally {
        setHpBusy(false);
      }
    };

    const handleHpCommit = async () => {
      if (disabled || !hpPreview) return;
      setHpBusy(true);
      setHpError("");
      try {
        await apiRequest("/api/human-publications/commit", {
          method: "POST",
          body: { request_id: hpPreview.id, confirmed: true },
        });
        setHpPreview(null);
        setHpSelected([]);
        setHpNotice(
          bilingual(
            lang,
            "已加入队列，稍后自动更新同步状态。",
            "Queued. Synchronization status will update shortly.",
          ),
        );
        void hpQuery.refetch();
      } catch (err) {
        setHpError(err instanceof Error ? err.message : String(err));
      } finally {
        setHpBusy(false);
      }
    };

    const historyRow = d?.items.find((r) => r.issue_id === hpHistoryIssue);

    return (
      <div
        className="ra-rd-results-root human-publications-page"
        data-react-island="rd-results"
      >
        <section
          className="page-card runs-source-card rd-overview"
          aria-label={bilingual(lang, "标注上传概览", "Label publication overview")}
        >
          <div className="runs-source-heading rd-mode-header">
            <div>
              <div
                className="rd-mode-tabs"
                role="tablist"
                aria-label={bilingual(lang, "标注上传类型", "Publication type")}
              >
                {(["rd", "te", "arbitrated"] as const).map((lane) => (
                  <button
                    key={lane}
                    id={`hpTab-${lane}`}
                    type="button"
                    role="tab"
                    className="button button-secondary rd-mode-tab"
                    aria-label={laneName(lane)}
                    aria-selected={hpLane === lane}
                    aria-controls="hpPanel"
                    tabIndex={hpLane === lane ? 0 : -1}
                    disabled={disabled}
                    onClick={() => {
                      setHpLane(lane);
                      setHpHistoryIssue("");
                      setHpSelected([]);
                      setHpPreview(null);
                      const nextF = { ...hpFilters, page: 1 };
                      setHpFilters(nextF);
                      syncHpUrl({ lane, filters: nextF, historyIssue: "" });
                    }}
                  >
                    <span className="rd-mode-label-full">{laneName(lane)}</span>
                    <span className="rd-mode-label-compact" aria-hidden="true">
                      {lane === "arbitrated"
                        ? bilingual(lang, "裁决", "Decision")
                        : lane === "te"
                          ? "TE′"
                          : "RD"}
                    </span>
                  </button>
                ))}
              </div>
            </div>
            <div className="run-manager-actions">
              <button
                type="button"
                className="button button-quiet"
                disabled={disabled}
                onClick={() => void hpQuery.refetch()}
              >
                {bilingual(lang, "刷新", "Refresh")}
              </button>
            </div>
          </div>

          <div className="rd-mode-panel">
            <div
              className="run-source-tabs rd-metrics"
              aria-label={bilingual(lang, "标注概览与筛选", "Label overview and filters")}
            >
              {metrics.map(([key, count, zh, en, svgPath]) => (
                <button
                  key={key}
                  type="button"
                  className={`run-source-tab rd-metric${hpFilters.status === key ? " active" : ""}`}
                  aria-pressed={hpFilters.status === key}
                  disabled={disabled}
                  onClick={() => {
                    const nextF = { ...hpFilters, status: key, page: 1 };
                    setHpFilters(nextF);
                    setHpDraft((prev) => ({ ...prev, status: key }));
                    setHpSelected([]);
                    setHpPreview(null);
                    syncHpUrl({ filters: nextF });
                  }}
                >
                  <span className="run-source-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24">
                      <path d={svgPath} />
                    </svg>
                  </span>
                  <span>
                    <strong>{bilingual(lang, zh, en)}</strong>
                  </span>
                  <em>{count == null ? "—" : count}</em>
                </button>
              ))}
            </div>
            <dl className="rd-upload-target">
              <div>
                <dt>{bilingual(lang, "上传接口", "Upload endpoint")}</dt>
                <dd>
                  <span className="rd-http-method">POST</span>
                  <code>{RD_UPLOAD_ENDPOINT}</code>
                </dd>
              </div>
              <div>
                <dt>{bilingual(lang, "目标字段", "Target field")}</dt>
                <dd>
                  <code>{fieldName}</code>
                </dd>
              </div>
            </dl>
          </div>
        </section>

        <section
          id="hpPanel"
          className="page-card runs-page-card rd-workspace"
          role="tabpanel"
          aria-labelledby={`hpTab-${hpLane}`}
        >
          <div className="rd-detail-toolbar">
            <div className="rd-detail-heading">
              <h3>{bilingual(lang, "标注明细", "Label details")}</h3>
            </div>
            <form
              id="hpFilters"
              className="run-filter-bar rd-filters"
              onSubmit={(e) => {
                e.preventDefault();
                const nextF = { ...hpFilters, q: hpDraft.q, status: hpDraft.status, page: 1 };
                setHpFilters(nextF);
                setHpSelected([]);
                setHpPreview(null);
                syncHpUrl({ filters: nextF });
              }}
            >
              <input
                id="hpSearch"
                maxLength={128}
                value={hpDraft.q}
                disabled={disabled}
                placeholder={bilingual(lang, "搜索 Issue ID", "Find Issue ID")}
                aria-label={bilingual(lang, "搜索 Issue ID", "Find Issue ID")}
                onChange={(e) => setHpDraft((prev) => ({ ...prev, q: e.target.value }))}
              />
              <UiSelect
                id="hpStatus"
                value={hpDraft.status}
                options={hpStatusOptions}
                disabled={disabled}
                ariaLabel={bilingual(lang, "结论筛选", "Conclusion filter")}
                onChange={(val) => setHpDraft((prev) => ({ ...prev, status: val }))}
              />
              <button className="button button-secondary" type="submit" disabled={disabled}>
                {bilingual(lang, "筛选", "Apply")}
              </button>
            </form>
          </div>

          {hpQuery.isLoading || hpError || hpQuery.isError || hpNotice ? (
            <p
              className={`rd-notice${hpError || hpQuery.isError ? " is-error" : ""}`}
              role="status"
            >
              {hpError ||
                (hpQuery.isError
                  ? bilingual(lang, "暂时无法加载，请刷新重试。", "Unable to load results. Refresh to retry.")
                  : hpQuery.isLoading
                    ? bilingual(lang, "正在加载…", "Loading…")
                    : hpNotice)}
            </p>
          ) : null}

          <div className={`rd-selection-bar${hpSelected.length ? " has-selection" : ""}`}>
            <div className="rd-selection-tools">
              <div className="run-manager-actions">
                <UiSelect
                  id="hpSelectionAction"
                  value=""
                  options={hpSelectionOptions}
                  disabled={disabled}
                  placeholder={bilingual(lang, "选中操作", "Selection actions")}
                  ariaLabel={bilingual(lang, "选中操作", "Selection actions")}
                  onChange={(val) => {
                    if (val === "page") {
                      setHpSelected((d?.items || []).map((r) => r.issue_id));
                    } else if (val === "clear") {
                      setHpSelected([]);
                    }
                    setHpPreview(null);
                  }}
                />
                <span className="rd-selection-count" role="status">
                  {hpSelected.length ? (
                    <>
                      {bilingual(lang, "已选", "Selected")} <strong>{hpSelected.length}</strong>{" "}
                      {bilingual(lang, "条", "labels")}
                    </>
                  ) : (
                    bilingual(lang, "请选择标注", "Select labels to preview")
                  )}
                </span>
              </div>
            </div>
            <div className="run-manager-actions">
              {d && !d.write_enabled ? (
                <span
                  className="rd-notice"
                  title={bilingual(
                    lang,
                    "真实写入开关关闭，预览可用",
                    "Publishing is disabled; preview is available",
                  )}
                >
                  {bilingual(lang, "写入未启用", "Publishing disabled")}
                </span>
              ) : null}
              {isAdmin ? (
                <button
                  type="button"
                  className="button button-primary"
                  data-rd-action="preview"
                  disabled={disabled || !hpSelected.length}
                  onClick={() => void handleHpPreview()}
                >
                  {bilingual(lang, "预览上传", "Preview upload")}
                </button>
              ) : null}
            </div>
          </div>

          <div className="rd-table-wrap">
            <table className="rd-table human-publication-table">
              <thead>
                <tr>
                  <th />
                  <th>Issue</th>
                  <th>{bilingual(lang, "人工结论", "Human label")}</th>
                  <th>{bilingual(lang, "标注人", "Contributors")}</th>
                  <th>{bilingual(lang, "同步状态", "Sync status")}</th>
                  <th>{bilingual(lang, "记录", "History")}</th>
                </tr>
              </thead>
              <tbody>
                {(d?.items || []).map((row) => {
                  const checked = hpSelected.includes(row.issue_id);
                  return (
                    <tr key={row.issue_id} className={checked ? "is-selected" : ""}>
                      <td>
                        <label className="rd-checkbox">
                          <input
                            id={`hpSelect-${row.issue_id}`}
                            type="checkbox"
                            className="ui-checkbox"
                            checked={checked}
                            disabled={disabled}
                            aria-label={`${bilingual(lang, "选择 ", "Select ")}${row.issue_id}`}
                            onChange={(e) => {
                              setHpSelected((prev) =>
                                e.target.checked
                                  ? [...prev, row.issue_id]
                                  : prev.filter((id) => id !== row.issue_id),
                              );
                              setHpPreview(null);
                            }}
                          />
                        </label>
                      </td>
                      <td>
                        <a className="rd-issue-link" href={labelingHref(row.issue_id)}>
                          {row.issue_id}
                        </a>
                      </td>
                      <td>
                        {row.conclusion === "resolved" && row.label ? (
                          <LabelPill label={row.label} lang={lang} />
                        ) : (
                          <HumanStatusPill status={row.conclusion} lang={lang} />
                        )}
                      </td>
                      <td>
                        {row.authors.join(", ") || "—"}
                        {row.required > 1 ? (
                          <>
                            {" "}
                            <span className="muted">
                              ({row.submitted}/{row.required})
                            </span>
                          </>
                        ) : null}
                      </td>
                      <td>
                        <HumanStatusPill
                          status={row.publication_armed === 0 ? "awaiting_activation" : row.sync_state}
                          lang={lang}
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="button button-quiet"
                          disabled={disabled}
                          onClick={() => {
                            setHpHistoryIssue(row.issue_id);
                            setHpHistoryPage(1);
                            syncHpUrl({ historyIssue: row.issue_id, historyPage: 1 });
                          }}
                        >
                          {row.objections?.length
                            ? bilingual(
                                lang,
                                `异议 ${row.objections.length}`,
                                `${row.objections.length} objection${
                                  row.objections.length === 1 ? "" : "s"
                                }`,
                              )
                            : bilingual(lang, "查看", "View")}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {!hpQuery.isLoading && !d?.items?.length ? (
            <div className="rd-empty">
              {hpQuery.isError
                ? bilingual(lang, "加载失败，可刷新重试。", "Loading failed. Refresh to retry.")
                : bilingual(lang, "当前范围暂无正式标注记录。", "No formal label records in this scope.")}
            </div>
          ) : null}

          <Pagination
            page={d?.page || hpFilters.page}
            pageSize={hpFilters.page_size}
            total={d?.total || 0}
            lang={lang}
            loading={disabled || hpQuery.isError}
            className="case-pagination rd-pagination"
          summaryText={d ? `${d.total} ${bilingual(lang, "条结果", "results")}` : "—"}
            ariaLabel={bilingual(lang, "标注明细分页", "Annotation pagination")}
            onPageChange={(nextPage) => {
              const nextF = { ...hpFilters, page: nextPage };
              setHpFilters(nextF);
              setHpSelected([]);
              setHpPreview(null);
              syncHpUrl({ filters: nextF });
            }}
            onPageSizeChange={(nextSize) => {
              const nextF = { ...hpFilters, page_size: nextSize, page: 1 };
              setHpFilters(nextF);
              setHpSelected([]);
              setHpPreview(null);
              syncHpUrl({ filters: nextF });
            }}
          />
        </section>

        {hpPreview ? (
          <section
            id="hpPreview"
            className="page-card rd-workspace"
            aria-label={bilingual(lang, "上传预览", "Publication preview")}
          >
            <h3>{bilingual(lang, "本次将排队处理", "Queue preview")}</h3>
            <p>
              {bilingual(
                lang,
                "执行时会再次核对当前结论和远端值。冲突来源不能强制上传。",
                "The worker will recheck the current conclusion and remote value. Conflicted sources cannot be forced through.",
              )}
            </p>
            <ul>
              {hpPreview.items.map((it) => (
                <li key={it.issue_id}>
                  {it.issue_id} · {humanStatusText(it.action, lang)} ·{" "}
                  {it.desired === null
                    ? bilingual(lang, "无有效结果", "No valid result")
                    : rdLabelText(it.desired, lang)}
                </li>
              ))}
            </ul>
            <div className="run-manager-actions">
              <button
                type="button"
                className="button button-primary"
                disabled={disabled || !d?.write_enabled || !hpPreview.items.some((i) => i.eligible)}
                onClick={() => void handleHpCommit()}
              >
                {bilingual(lang, "确认加入队列", "Confirm queue")}
              </button>
              <button
                type="button"
                className="button button-secondary"
                disabled={disabled}
                onClick={() => setHpPreview(null)}
              >
                {bilingual(lang, "关闭预览", "Close preview")}
              </button>
            </div>
          </section>
        ) : null}

        {hpHistoryIssue ? (
          <section id="hpHistory" className="page-card rd-workspace rd-preview-details">
            <div className="runs-toolbar">
              <h3>
                {hpHistoryIssue} · {bilingual(lang, "上传记录", "Publication history")}
              </h3>
              <button
                type="button"
                className="button button-quiet"
                onClick={() => {
                  setHpHistoryIssue("");
                  syncHpUrl({ historyIssue: "" });
                }}
              >
                {bilingual(lang, "关闭记录", "Close history")}
              </button>
            </div>
            {historyRow ? (
              <>
                <div className="rd-preview-summary">
                  {hpLane !== "arbitrated" ? (
                    <span>
                      {bilingual(lang, "必需标注", "Required votes")} {historyRow.submitted}/
                      {historyRow.required}
                    </span>
                  ) : null}
                  {historyRow.checked_at ? (
                    <span>
                      {bilingual(lang, "最近核对", "Last checked")}{" "}
                      {formatCstObsTime(historyRow.checked_at, lang)} CST
                    </span>
                  ) : null}
                </div>
                {historyRow.error_code ? (
                  <p className="rd-notice is-error">
                    {rdReasonText(historyRow.error_code, lang) ||
                      humanStatusText(historyRow.error_code, lang)}
                  </p>
                ) : null}
                {historyRow.objections?.length ? (
                  <div>
                    <h3>{bilingual(lang, "任务外异议", "Advisory objections")}</h3>
                    {historyRow.objections.map((v, idx) => (
                      <p className="rd-description" key={idx}>
                        {v.author} · {rdLabelText(v.label, lang)}
                      </p>
                    ))}
                  </div>
                ) : null}
              </>
            ) : null}
            {hpHistoryQuery.data?.items?.length ? (
              <div className="rd-table-wrap">
                <table className="rd-table">
                  <tbody>
                    {hpHistoryQuery.data.items.map((item, idx) => (
                      <tr key={idx}>
                        <td>{formatCstObsTime(item.created_at, lang)} CST</td>
                        <td>{humanStatusText(item.action, lang)}</td>
                        <td>{item.desired === null ? "NULL" : rdLabelText(item.desired, lang)}</td>
                        <td>
                          <HumanStatusPill status={item.state} lang={lang} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="rd-description">
                {bilingual(lang, "暂无上传尝试。", "No publication attempts yet.")}
              </p>
            )}
            <Pagination
              page={hpHistoryQuery.data?.page || hpHistoryPage}
              pageSize={hpHistorySize}
              total={hpHistoryQuery.data?.total || 0}
              lang={lang}
              loading={hpHistoryQuery.isFetching}
              onPageChange={(nextPage) => {
                setHpHistoryPage(nextPage);
                syncHpUrl({ historyPage: nextPage });
              }}
              onPageSizeChange={(nextSize) => {
                setHpHistorySize(nextSize);
                setHpHistoryPage(1);
                syncHpUrl({ historySize: nextSize, historyPage: 1 });
              }}
            />
          </section>
        ) : null}
      </div>
    );
  }

  // =========================================================================
  // RENDER MODE B: CLASSIC RD UPLOAD & TE CORRECTION
  // =========================================================================
  const isTE = rdMode === "te-correction";
  const uploadField = isTE ? "ra_review_result_new" : "ra_rd_review_result";
  const d = rdQuery.data || null;
  const teRefreshing = isTE && rdTeRefresh?.status === "running";
  const selectionDisabled = rdBusy || rdQuery.isLoading || teRefreshing;
  const scopeCount = ["all", "resolved"].includes(rdFilters.status)
    ? Number(d?.counts?.resolved || 0)
    : 0;
  const selectedCount = rdAllSelected
    ? Math.max(0, scopeCount - rdExcluded.length)
    : rdSelected.length;

  const isRowSelected = (row: RdRow) =>
    row.group === "resolved" &&
    (rdAllSelected ? !rdExcluded.includes(row.issue_id) : rdSelected.includes(row.issue_id));

  const waitPreviewReceipt = async (initialReceipt: RdReceipt): Promise<RdReceipt> => {
    let cur = initialReceipt;
    while (cur.state === "preparing") {
      await new Promise((r) => window.setTimeout(r, 1000));
      cur = await apiRequest<RdReceipt>(`/api/rd-results/operations/${encodeURIComponent(cur.id)}`);
    }
    if (cur.state === "preview_failed") {
      throw new Error(rdReasonText(cur.reason, lang) || "Preview failed");
    }
    return cur;
  };

  const handleRdPreview = async () => {
    if (selectionDisabled) return;
    setRdBusy(true);
    setRdBusyAction("preview");
    setRdError("");
    try {
      let receipt: RdReceipt;
      if (isTE && rdExcelFile) {
        const fd = new FormData();
        fd.append("file", rdExcelFile, rdExcelFile.name);
        fd.append("baselines", baselinesParam);
        const res = await apiRequest<RdReceipt>("/api/rd-results/te-excel-preview?background=true", {
          method: "POST",
          body: fd,
        });
        receipt = await waitPreviewReceipt(res);
      } else {
        const endpoint = rdAllSelected ? "preview-scope" : "preview";
        const body = rdAllSelected
          ? {
              baselines: baselinesParam,
              mode: rdMode,
              q: rdFilters.q,
              status: rdFilters.status,
              overwrite: true,
              excluded_issue_ids: rdExcluded,
            }
          : {
              baselines: baselinesParam,
              mode: rdMode,
              issue_ids: rdSelected,
              overwrite: true,
            };
        const res = await apiRequest<RdReceipt>(`/api/rd-results/${endpoint}?background=true`, {
          method: "POST",
          body,
        });
        receipt = await waitPreviewReceipt(res);
      }
      setRdPreview(receipt);
      setRdPreviewPage(1);
      window.scrollTo(0, 0);
    } catch (err) {
      setRdError(err instanceof Error ? err.message : String(err));
    } finally {
      setRdBusy(false);
      setRdBusyAction("");
    }
  };

  const handleRdHistory = async () => {
    if (rdBusy) return;
    setRdBusy(true);
    setRdBusyAction("history");
    setRdError("");
    try {
      const res = await apiRequest<{ items: RdOperationSummary[] }>(
        `/api/rd-results/operations?mode=${encodeURIComponent(rdMode)}`,
      );
      setRdOperations(res.items || []);
    } catch (err) {
      setRdError(err instanceof Error ? err.message : String(err));
    } finally {
      setRdBusy(false);
      setRdBusyAction("");
    }
  };

  const handleOpenOperation = async (opId: string) => {
    if (rdBusy) return;
    setRdBusy(true);
    setRdError("");
    try {
      const res = await apiRequest<RdReceipt>(`/api/rd-results/operations/${encodeURIComponent(opId)}`);
      const ready = await waitPreviewReceipt(res);
      setRdPreview(ready);
      setRdPreviewPage(1);
    } catch (err) {
      setRdError(err instanceof Error ? err.message : String(err));
    } finally {
      setRdBusy(false);
    }
  };

  const handleRdCommitOrReceipt = async (kind: "commit" | "receipt") => {
    if (!rdPreview || rdBusy) return;
    setRdBusy(true);
    setRdError("");
    try {
      if (kind === "receipt") {
        const rec = await apiRequest<RdReceipt>(
          `/api/rd-results/operations/${encodeURIComponent(rdPreview.id)}`,
        );
        setRdPreview(
          rec.state === "preview"
            ? { ...rec, state: "outcome_unknown", reason: "receipt_pending" }
            : rec,
        );
      } else {
        setRdSelected([]);
        setRdAllSelected(false);
        setRdExcluded([]);
        const rec = await apiRequest<RdReceipt>("/api/rd-results/commit?background=true", {
          method: "POST",
          body: { operation_id: rdPreview.id, confirmed: true },
        });
        setRdPreview(rec);
      }
    } catch (err) {
      setRdError(err instanceof Error ? err.message : String(err));
    } finally {
      setRdBusy(false);
    }
  };

  const handleRefreshTe = async () => {
    if (!isTE || teInvalidVersion || rdBusy || rdQuery.isLoading || teRefreshing) return;
    setRdBusy(true);
    setRdBusyAction("refresh-te");
    setRdError("");
    setRdTeRefresh({ status: "running", scanned: 0, total: d?.counts?.total || 0 });
    try {
      const res = await apiRequest<{ status?: string; scanned?: number; total?: number }>(
        "/api/rd-results/te-refresh",
        { method: "POST", body: { baselines: baselinesParam } },
      );
      setRdTeRefresh(res);
      if (res.status !== "running") {
        void rdQuery.refetch();
      }
    } catch {
      setRdTeRefresh(null);
      setRdError(
        bilingual(lang, "无法刷新 TE 标签，请重试。", "Could not refresh TE labels; retry."),
      );
    } finally {
      setRdBusy(false);
      setRdBusyAction("");
    }
  };

  // --- Classic Preview / Outcome Sub-view ---
  if (rdPreview) {
    const p = rdPreview;
    const isPreviewState = p.state === "preview";
    const isRunning = p.state === "running";
    const eligibleCount = p.items.filter((r) => r.eligible).length;
    const resultsMap = new Map((p.results || []).map((r) => [r.issue_id, r]));
    const outcomes = p.items.map((row) => ({ row, result: resultsMap.get(row.issue_id) }));
    const visibleOutcomes = outcomes.slice(
      (rdPreviewPage - 1) * rdPreviewPageSize,
      rdPreviewPage * rdPreviewPageSize,
    );
    const verifiedCount = outcomes.filter(
      ({ row, result }) => row.eligible && (result?.state || "unverified") === "verified",
    ).length;
    const legacyTePreview = isTE && isPreviewState && p.policy_version !== 2;

    return (
      <div
        className={`ra-rd-results-root${isTE ? " is-te-correction" : ""}`}
        data-react-island="rd-results"
      >
        <div id="rdResultsPreview" className="rd-preview-page" aria-labelledby="rdPreviewTitle">
          <section className="page-card runs-source-card rd-preview-overview">
            <div className="runs-source-heading">
              <div>
                <h3 id="rdPreviewTitle" tabIndex={-1}>
                  {isTE
                    ? isPreviewState
                      ? bilingual(lang, "TE 修正预览", "TE correction preview")
                      : isRunning
                        ? bilingual(lang, "TE 修正进度", "TE correction progress")
                        : bilingual(lang, "TE 修正结果", "TE correction outcome")
                    : isPreviewState
                      ? bilingual(lang, "上传预览", "Upload preview")
                      : isRunning
                        ? bilingual(lang, "上传进度", "Upload progress")
                        : bilingual(lang, "上传结果", "Upload outcome")}
                </h3>
              </div>
              <button
                type="button"
                className="button button-quiet"
                disabled={rdBusy}
                onClick={() => {
                  const shouldRefresh = ["complete", "needs_recheck"].includes(p.state);
                  setRdPreview(null);
                  if (shouldRefresh) void rdQuery.refetch();
                }}
              >
                {bilingual(lang, "返回选择", "Back to selection")}
              </button>
            </div>

            <div className="rd-preview-summary">
              <div className="rd-preview-total">
                <strong>{isPreviewState ? eligibleCount : verifiedCount}</strong>
                <span>
                  {isPreviewState
                    ? bilingual(lang, "条可上传", "ready to upload")
                    : bilingual(lang, "条已核验", "verified")}
                </span>
              </div>
            </div>

            {p.reason ? (
              <p className="rd-notice" role="status">
                {rdReasonText(p.reason, lang)}
              </p>
            ) : null}
            {rdError ? (
              <p className="rd-notice is-error" role="alert">
                {rdError}
              </p>
            ) : null}

            <details id="rdPreviewInfo" className="rd-preview-info">
              <summary>{bilingual(lang, "接口与规则", "Endpoint and rules")}</summary>
              <div>
                <dl className="rd-upload-target">
                  <div>
                    <dt>{bilingual(lang, "上传接口", "Upload endpoint")}</dt>
                    <dd>
                      <span className="rd-http-method">POST</span>
                      <code>{RD_UPLOAD_ENDPOINT}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>{bilingual(lang, "更新字段", "Updated field")}</dt>
                    <dd>
                      <code>{uploadField}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>{bilingual(lang, "操作编号", "Operation ID")}</dt>
                    <dd>
                      <code>{p.id}</code>
                    </dd>
                  </div>
                </dl>
              </div>
            </details>
          </section>

          <section className="page-card runs-page-card rd-preview-details">
            <div className="runs-toolbar">
              <h3>
                {isPreviewState
                  ? bilingual(lang, "差异明细", "Change details")
                  : bilingual(lang, "逐条结果", "Item outcomes")}
              </h3>
            </div>
            <div className="rd-table-wrap">
              <table className="rd-table">
                <thead>
                  <tr>
                    <th>Issue</th>
                    <th>
                      {isTE
                        ? bilingual(lang, "当前 TE（实时）", "Current TE (live)")
                        : bilingual(lang, "Trail 原值", "Current Trail value")}
                    </th>
                    <th>
                      {isTE
                        ? bilingual(lang, "TE 修正值", "New TE value")
                        : bilingual(lang, "上传值", "New value")}
                    </th>
                    {!isPreviewState ? <th>{bilingual(lang, "读回值", "Readback value")}</th> : null}
                    <th>{bilingual(lang, "处理状态", "Disposition")}</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleOutcomes.map(({ row, result }) => (
                    <tr key={row.issue_id}>
                      <td>{row.issue_id}</td>
                      <td>
                        <LabelPill label={row.current} lang={lang} />
                      </td>
                      <td>
                        <LabelPill label={row.desired} lang={lang} />
                      </td>
                      {!isPreviewState ? (
                        <td>
                          <LabelPill label={result?.observed} lang={lang} />
                        </td>
                      ) : null}
                      <td>
                        <RdStatusPill
                          status={
                            isPreviewState
                              ? row.status
                              : result?.phase || result?.state || (!row.eligible ? row.status : "unverified")
                          }
                          lang={lang}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <Pagination
              page={rdPreviewPage}
              pageSize={rdPreviewPageSize}
              total={outcomes.length}
              lang={lang}
              loading={rdBusy}
              onPageChange={setRdPreviewPage}
              onPageSizeChange={(nextSize) => {
                setRdPreviewPageSize(nextSize);
                setRdPreviewPage(1);
              }}
            />

            <div className="rd-preview-footer">
              <p className="rd-description" role="status">
                {isPreviewState
                  ? bilingual(
                      lang,
                      "预览 10 分钟内有效；数据变化后需重新预览。",
                      "Valid for 10 minutes. Preview again if the data changes.",
                    )
                  : bilingual(lang, "请以逐条核验结果为准。", "Use the per-item verification results.")}
              </p>
              <div className="run-manager-actions">
                {isPreviewState ? (
                  <button
                    type="button"
                    className="button button-primary"
                    disabled={rdBusy || !eligibleCount || !d?.write_enabled || legacyTePreview}
                    onClick={() => void handleRdCommitOrReceipt("commit")}
                  >
                    {isTE
                      ? bilingual(
                          lang,
                          `确认修正 TE ${eligibleCount} 条`,
                          `Confirm TE correction · ${eligibleCount}`,
                        )
                      : bilingual(
                          lang,
                          `确认上传 ${eligibleCount} 条`,
                          `Confirm upload · ${eligibleCount}`,
                        )}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="button button-secondary"
                    disabled={rdBusy}
                    onClick={() => void handleRdCommitOrReceipt("receipt")}
                  >
                    {bilingual(lang, "刷新本次结果", "Refresh outcome")}
                  </button>
                )}
              </div>
            </div>
          </section>
        </div>
      </div>
    );
  }

  // --- Classic Main List View ---
  const classicMetrics: Array<[string, string, string, string, string]> = isTE
    ? [
        ["all", "total", "范围内 Issues", "Issues in scope", "M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z"],
        ["resolved", "resolved", "待修正候选", "Correction candidates", "m5 12 4 4L19 6"],
        ["same", "same", "已一致", "Already matches", "m5 12 4 4L19 6"],
        ["blocked", "blocked", "暂不可修正", "Unavailable for correction", "m12 3 10 18H2L12 3zm0 6v5m0 3v1"],
      ]
    : [
        ["all", "total", "范围内 Issues", "Issues in scope", "M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z"],
        ["resolved", "resolved", "已完成", "Completed", "m5 12 4 4L19 6"],
        ["pending", "pending", "待标注", "Pending labels", "M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0"],
        ["conflict", "conflict", "需复核", "Needs review", "m12 3 10 18H2L12 3zm0 6v5m0 3v1"],
      ];

  const rdStatusOptions: UiSelectOption[] = (
    isTE
      ? [
          ["all", "全部状态", "All statuses"],
          ["resolved", "待修正候选", "Correction candidates"],
          ["same", "已一致", "Already matches"],
          ["blocked", "暂不可修正", "Unavailable for correction"],
        ]
      : [
          ["all", "全部状态", "All statuses"],
          ["resolved", "已完成", "Completed"],
          ["pending", "待标注", "Pending labels"],
          ["conflict", "冲突 / 失效", "Conflict / stale"],
        ]
  ).map(([value, zh, en]) => ({ value, label: bilingual(lang, zh, en) }));

  const rdSelectionOptions: UiSelectOption[] = [
    { value: "", label: bilingual(lang, "选中操作", "Selection actions"), disabled: true },
    {
      value: "page",
      label: bilingual(lang, "选择本页", "Select this page"),
      disabled: !(d?.items || []).some((r) => r.group === "resolved"),
    },
    {
      value: "all",
      label: bilingual(lang, `选择全部 ${scopeCount} 条`, `Select all ${scopeCount} labels`),
      disabled: !scopeCount,
    },
    {
      value: "clear",
      label: bilingual(lang, "清空选择", "Clear selection"),
      disabled: !selectedCount,
    },
  ];

  const effectiveError =
    rdError ||
    (teInvalidVersion
      ? bilingual(lang, "TE 修正请选择一个版本数据集。", "Select one version dataset for TE correction.")
      : rdQuery.isError
        ? (rdQuery.error as Error)?.message || "Load failed"
        : "");

  return (
    <div
      className={`ra-rd-results-root${isTE ? " is-te-correction" : ""}`}
      data-react-island="rd-results"
    >
      <section
        className="page-card runs-source-card rd-overview"
        aria-label={bilingual(lang, "标注上传概览", "Label publication overview")}
      >
        <div className="runs-source-heading rd-mode-header">
          <div>
            <div
              className="rd-mode-tabs"
              role="tablist"
              aria-label={bilingual(lang, "标注上传类型", "Publication type")}
            >
              {(
                [
                  ["rd", "RD 上传", "RD upload", "RD 标注上传", "RD label upload"],
                  ["te-correction", "TE 修正", "TE correction", "TE 标注修正", "TE label correction"],
                ] as const
              ).map(([mode, zh, en, fullZh, fullEn]) => (
                <button
                  key={mode}
                  id={`rdMode-${mode}`}
                  type="button"
                  role="tab"
                  className="button button-secondary rd-mode-tab"
                  aria-label={bilingual(lang, fullZh, fullEn)}
                  aria-selected={rdMode === mode}
                  aria-controls="rdModePanel"
                  tabIndex={rdMode === mode ? 0 : -1}
                  disabled={rdBusy}
                  onClick={() => {
                    setRdMode(mode);
                    const nextF = { ...rdFilters, status: "all", page: 1 };
                    setRdFilters(nextF);
                    setRdDraft((prev) => ({ ...prev, status: "all" }));
                    syncRdUrl({ mode, filters: nextF });
                  }}
                >
                  <span className="rd-mode-label-full">{bilingual(lang, fullZh, fullEn)}</span>
                  <span className="rd-mode-label-compact" aria-hidden="true">
                    {bilingual(lang, zh, en)}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <div className="run-manager-actions">
            <button
              type="button"
              className="button button-quiet"
              disabled={rdQuery.isLoading || rdBusy}
              onClick={() => void rdQuery.refetch()}
            >
              {bilingual(lang, "刷新", "Refresh")}
            </button>
          </div>
        </div>

        <div id="rdModePanel" className="rd-mode-panel" role="tabpanel" aria-labelledby={`rdMode-${rdMode}`}>
          <div
            className="run-source-tabs rd-metrics"
            aria-label={bilingual(lang, "标注概览与筛选", "Label overview and filters")}
          >
            {classicMetrics.map(([filterKey, countKey, zh, en, path]) => (
              <button
                key={filterKey}
                type="button"
                className={`run-source-tab rd-metric${rdFilters.status === filterKey ? " active" : ""}`}
                aria-pressed={rdFilters.status === filterKey}
                disabled={rdQuery.isLoading || rdBusy}
                onClick={() => {
                  const nextF = { ...rdFilters, status: filterKey, page: 1 };
                  setRdFilters(nextF);
                  setRdDraft((prev) => ({ ...prev, status: filterKey }));
                  setRdSelected([]);
                  setRdAllSelected(false);
                  setRdExcluded([]);
                  syncRdUrl({ filters: nextF });
                }}
              >
                <span className="run-source-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24">
                    <path d={path} />
                  </svg>
                </span>
                <span>
                  <strong>{bilingual(lang, zh, en)}</strong>
                </span>
                <em>{d ? Number(d.counts?.[countKey] ?? 0) : "—"}</em>
              </button>
            ))}
          </div>

          <dl className="rd-upload-target">
            <div>
              <dt>{bilingual(lang, "上传接口", "Upload endpoint")}</dt>
              <dd>
                <span className="rd-http-method">POST</span>
                <code>{RD_UPLOAD_ENDPOINT}</code>
              </dd>
            </div>
            <div>
              <dt>{bilingual(lang, "目标字段", "Target field")}</dt>
              <dd>
                <code>{uploadField}</code>
              </dd>
            </div>
          </dl>
        </div>
      </section>

      <section className="page-card runs-page-card rd-workspace">
        <div className="rd-detail-toolbar">
          <div className="rd-detail-heading">
            <h3>{bilingual(lang, "标注明细", "Label details")}</h3>
            {isTE ? (
              <div className="run-manager-actions">
                <button
                  type="button"
                  className="button button-quiet"
                  disabled={selectionDisabled || teInvalidVersion}
                  onClick={() => void handleRefreshTe()}
                >
                  {bilingual(lang, "刷新 TE 标签", "Refresh TE labels")}
                </button>
                {isAdmin ? (
                  <>
                    <button
                      type="button"
                      className="button button-quiet"
                      disabled={selectionDisabled || teInvalidVersion}
                      onClick={() => excelInputRef.current?.click()}
                    >
                      {bilingual(lang, "导入 XLSX", "Import XLSX")}
                    </button>
                    <input
                      ref={excelInputRef}
                      id="rdExcelFile"
                      className="hidden"
                      type="file"
                      accept=".xlsx"
                      onChange={(e) => {
                        const file = e.target.files?.[0] || null;
                        if (file) {
                          setRdExcelFile(file);
                          setRdSelected([]);
                          setRdAllSelected(false);
                          setRdExcluded([]);
                          setRdError("");
                        }
                      }}
                    />
                  </>
                ) : null}
                {teRefreshing ? (
                  <span className="rd-description" role="status">
                    {rdTeRefresh?.scanned || 0} / {rdTeRefresh?.total || 0}
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>

          <form
            id="rdFilters"
            className="run-filter-bar rd-filters"
            onSubmit={(e) => {
              e.preventDefault();
              const raw = rdDraft.q.trim();
              let q = raw;
              const tokens = raw.split(/[\s,，、;；]+/).filter(Boolean);
              if (tokens.length > 1) {
                if (tokens.length > 500 || tokens.some((id) => !/^cn\d+$/i.test(id))) {
                  setRdError(
                    bilingual(
                      lang,
                      "请输入最多 500 个有效 Issue ID。",
                      "Enter up to 500 valid Issue IDs.",
                    ),
                  );
                  return;
                }
                q = [...new Set(tokens.map((id) => id.toLowerCase()))].join(",");
              }
              setRdError("");
              const nextF = { ...rdFilters, q, status: rdDraft.status, page: 1 };
              setRdFilters(nextF);
              setRdSelected([]);
              setRdAllSelected(false);
              setRdExcluded([]);
              syncRdUrl({ filters: nextF });
            }}
          >
            <textarea
              ref={rdSearchRef}
              id="rdSearch"
              name="q"
              rows={1}
              maxLength={8000}
              value={rdDraft.q}
              aria-label={bilingual(lang, "Issue 搜索，可多个", "Find Issues; multiple IDs supported")}
              placeholder={bilingual(lang, "粘贴 Issue ID，可多个", "Paste Issue IDs")}
              autoComplete="off"
              onChange={(e) => {
                setRdDraft((prev) => ({ ...prev, q: e.target.value }));
                const el = e.target;
                el.style.height = "auto";
                el.style.height = `${Math.min(128, el.scrollHeight)}px`;
              }}
            />
            <UiSelect
              id="rdState"
              value={rdDraft.status}
              options={rdStatusOptions}
              disabled={rdBusy || rdQuery.isLoading}
              ariaLabel={bilingual(lang, "标注状态", "Label status")}
              onChange={(val) => setRdDraft((prev) => ({ ...prev, status: val }))}
            />
            <button
              className="button button-secondary"
              type="submit"
              disabled={rdBusy || rdQuery.isLoading}
            >
              {bilingual(lang, "筛选", "Apply")}
            </button>
          </form>
        </div>

        {effectiveError || rdQuery.isLoading || (rdBusy && rdBusyAction !== "refresh-te") ? (
          <p className={`rd-notice${effectiveError ? " is-error" : ""}`} role="status">
            {effectiveError ||
              (rdQuery.isLoading
                ? bilingual(lang, "正在加载标注…", "Loading labels…")
                : bilingual(lang, "正在处理，请稍候…", "Processing, please wait…"))}
          </p>
        ) : null}

        <div className={`rd-selection-bar${selectedCount ? " has-selection" : ""}`}>
          <div className="rd-selection-tools">
            <div className="run-manager-actions">
              <UiSelect
                id="rdSelectionAction"
                value=""
                options={rdSelectionOptions}
                disabled={selectionDisabled || Boolean(rdExcelFile)}
                placeholder={bilingual(lang, "选中操作", "Selection actions")}
                ariaLabel={bilingual(lang, "选中操作", "Selection actions")}
                onChange={(val) => {
                  setRdSelected([]);
                  setRdExcluded([]);
                  setRdAllSelected(false);
                  if (val === "page") {
                    setRdSelected(
                      (d?.items || [])
                        .filter((r) => r.group === "resolved")
                        .map((r) => r.issue_id),
                    );
                  } else if (val === "all") {
                    setRdAllSelected(true);
                  }
                }}
              />
              <span className="rd-selection-count" role="status">
                {rdExcelFile ? (
                  <>
                    {bilingual(lang, "XLSX 期望输出：", "XLSX targets: ")}
                    {rdExcelFile.name}
                    <button
                      type="button"
                      className="button button-quiet"
                      disabled={selectionDisabled}
                      onClick={() => setRdExcelFile(null)}
                    >
                      {bilingual(lang, "清除文件", "Clear file")}
                    </button>
                  </>
                ) : selectedCount ? (
                  <>
                    {bilingual(lang, "已选", "Selected")} <strong>{selectedCount}</strong>
                    {rdAllSelected
                      ? bilingual(lang, " 条 · 跨全部页", " · across all pages")
                      : bilingual(lang, " 条", " labels")}
                  </>
                ) : (
                  bilingual(lang, "请选择标注", "Select labels to preview")
                )}
              </span>
            </div>
          </div>
          <div className="run-manager-actions">
            {d && !d.write_enabled ? (
              <span
                className="rd-notice"
                title={bilingual(
                  lang,
                  "真实写入开关关闭，预览可用",
                  "Publishing is disabled; preview is available",
                )}
              >
                {bilingual(lang, "写入未启用", "Publishing disabled")}
              </span>
            ) : null}
            {isAdmin ? (
              <button
                type="button"
                className="button button-primary"
                data-rd-action="preview"
                disabled={(!rdExcelFile && !selectedCount) || selectionDisabled}
                onClick={() => void handleRdPreview()}
              >
                {rdExcelFile
                  ? bilingual(lang, "预览文件", "Preview file")
                  : bilingual(lang, "预览上传", "Preview upload")}
              </button>
            ) : null}
          </div>
        </div>

        <div className="rd-table-wrap">
          <table className="rd-table">
            <thead>
              <tr>
                <th />
                <th>Issue</th>
                {isTE ? <th>{bilingual(lang, "当前 TE（观测）", "Current TE (observed)")}</th> : null}
                <th>
                  {isTE
                    ? bilingual(lang, "RD 人工结论", "RD human label")
                    : bilingual(lang, "人工结论", "Human label")}
                </th>
                {isTE ? <th>{bilingual(lang, "修正状态", "Correction status")}</th> : null}
                <th>{bilingual(lang, "标注人", "Contributors")}</th>
              </tr>
            </thead>
            <tbody>
              {(d?.items || []).map((row) => {
                const eligible = row.group === "resolved";
                const checked = isRowSelected(row);
                const resolved = isTE ? row.state === "resolved" : row.group === "resolved";
                return (
                  <tr key={row.issue_id} className={checked ? "is-selected" : ""}>
                    <td>
                      <label className="rd-checkbox">
                        <input
                          className="ui-checkbox"
                          type="checkbox"
                          checked={checked}
                          disabled={!eligible || selectionDisabled || Boolean(rdExcelFile)}
                          aria-label={`${bilingual(lang, "选择 ", "Select ")}${row.issue_id}`}
                          onChange={(e) => {
                            if (rdAllSelected) {
                              setRdExcluded((prev) =>
                                e.target.checked
                                  ? prev.filter((id) => id !== row.issue_id)
                                  : [...prev, row.issue_id],
                              );
                            } else {
                              setRdSelected((prev) =>
                                e.target.checked
                                  ? [...prev, row.issue_id]
                                  : prev.filter((id) => id !== row.issue_id),
                              );
                            }
                          }}
                        />
                      </label>
                    </td>
                    <td>
                      <a className="rd-issue-link" href={labelingHref(row.issue_id)}>
                        {row.issue_id}
                      </a>
                    </td>
                    {isTE ? (
                      <td>
                        <LabelPill label={row.te_current} lang={lang} />
                      </td>
                    ) : null}
                    <td>
                      {resolved ? (
                        <LabelPill label={row.label} lang={lang} />
                      ) : (
                        <span className="muted">
                          {["conflict", "stale"].includes(row.state || row.group)
                            ? bilingual(lang, "冲突 / 失效", "Conflict / stale")
                            : bilingual(lang, "待标注", "Pending label")}
                        </span>
                      )}
                    </td>
                    {isTE ? (
                      <td>
                        <RdStatusPill status={row.correction_status} lang={lang} />
                      </td>
                    ) : null}
                    <td>{row.authors.join(", ") || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {!rdQuery.isLoading && !d?.items?.length ? (
          <div className="rd-empty">
            <strong>
              {effectiveError
                ? bilingual(lang, "暂时无法加载标注", "Unable to load labels")
                : bilingual(lang, "当前范围没有标注结果", "No labels in this scope")}
            </strong>
            <p>
              {bilingual(
                lang,
                "可调整顶部数据集或筛选条件后重试。",
                "Adjust the selected datasets or filters and try again.",
              )}
            </p>
          </div>
        ) : null}

        <Pagination
          page={d?.page || rdFilters.page}
          pageSize={rdFilters.page_size}
          total={d?.total || 0}
          lang={lang}
          loading={rdQuery.isLoading || rdBusy}
          className="case-pagination rd-pagination"
          summaryText={d ? `${d.total} ${bilingual(lang, "条结果", "results")}` : "—"}
          ariaLabel={bilingual(lang, "标注明细分页", "Annotation pagination")}
          onPageChange={(nextPage) => {
            const nextF = { ...rdFilters, page: nextPage };
            setRdFilters(nextF);
            setRdSelected([]);
            syncRdUrl({ filters: nextF });
          }}
          onPageSizeChange={(nextSize) => {
            const nextF = { ...rdFilters, page_size: nextSize, page: 1 };
            setRdFilters(nextF);
            setRdSelected([]);
            syncRdUrl({ filters: nextF });
          }}
        />
      </section>

      {isAdmin ? (
        <section className="page-card job-history-card">
          <div className="runs-toolbar">
            <div>
              <h3>{bilingual(lang, "上传记录", "Publication history")}</h3>
            </div>
            <button
              type="button"
              className="button button-secondary"
              disabled={rdBusy}
              onClick={() => void handleRdHistory()}
            >
              {bilingual(lang, "查看最近记录", "Show recent operations")}
            </button>
          </div>
          <div className="job-history-list">
            {rdOperations.map((op) => (
              <div className="job-history-row" key={op.id}>
                <div className="job-history-main">
                  <strong>{op.actor}</strong>
                  <span className="muted">{op.id.slice(0, 12)}</span>
                </div>
                <div className="run-manager-actions">
                  <RdStatusPill status={op.state} lang={lang} />
                  <button
                    type="button"
                    className="button button-secondary"
                    disabled={rdBusy}
                    onClick={() => void handleOpenOperation(op.id)}
                  >
                    {bilingual(lang, "查看详情", "View details")}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
};
