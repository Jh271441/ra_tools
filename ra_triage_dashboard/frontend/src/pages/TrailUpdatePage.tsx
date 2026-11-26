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

const LABELS = ["误触发", "正确触发", "无需协助"] as const;

interface TrailDetailObj {
  state?: string;
  trail_should_exclude?: boolean | null;
  trail_comment?: string | null;
  local_comment?: string | null;
  needs_reason_update?: boolean;
  needs_exclusion_update?: boolean;
}

interface TrailReasonSource {
  kind?: string;
  author?: string;
  created_at?: string;
  original_created_at?: string;
  source_annotation_id?: number | string;
  revision_id?: number | string;
  rationale?: string;
  decision_rationale?: string;
}

interface TrailHistoricalSource {
  kind?: string;
  label?: string;
  source_id?: string;
  row_number?: number;
  filename?: string;
  column?: string;
  value?: string;
  sha256?: string;
  captured_at?: string;
  snapshot_filename?: string;
  snapshot_sha256?: string;
  issue_id?: string;
}

interface TrailCandidateItem {
  row_key?: string;
  issue_id: string;
  baseline_id?: string;
  baseline_scope?: string;
  source_kind?: string;
  local_selected?: boolean | null;
  readonly?: boolean;
  gt_label?: string;
  title?: string;
  scenario?: string;
  comment?: string;
  trail_update_status?: string;
  trail_detail?: TrailDetailObj;
  reason_source?: TrailReasonSource;
  historical_source?: TrailHistoricalSource;
  local_evidence?: {
    legacy_reviews?: Array<{
      id: number;
      is_excluded?: boolean;
      author?: string;
      created_at?: string;
      note?: string;
    }>;
    migrated_revisions?: Array<{
      id: number;
      is_excluded?: boolean;
      source_annotation_id?: number;
      created_at?: string;
    }>;
  };
  model?: { label?: string; reason?: string; run_id?: string };
  review?: { reviewer?: string; status?: string; note?: string; model_run_id?: string };
  before?: { should_exclude?: boolean | null; should_exclude_comment?: string | null };
  current_should_exclude?: boolean;
  current_label?: string;
  comment_defaulted?: boolean;
  source?: TrailHistoricalSource;
  target?: { path?: string; patch?: { ra_triage_dashboard?: { should_exclude_comment?: string } } };
  field_updates?: Record<string, unknown>;
  field_update?: { patch?: unknown };
}

interface TrailPreviewResponse {
  mode?: string;
  intent?: string;
  items?: TrailCandidateItem[];
  baselines?: string[];
  local_candidate_count?: number;
  reconciliation?: boolean;
  historical_sources?: Array<{
    baseline_id: string;
    available: boolean;
    captured_at?: string;
  }>;
  checked_at?: string;
  payload_sha256?: string;
  write_status?: string;
  write_ready?: boolean;
  write_mode?: string;
  target_field?: string;
  target_fields?: string[];
  target_path?: string;
  comment_target_path?: string;
  model_result_field?: string;
  pending_count?: number;
  requested_issue_ids?: string[];
  requested_entries?: Array<{ issue_id: string; comment?: string; source?: TrailHistoricalSource }>;
  missing_issue_ids?: string[];
  invalid_issue_ids?: string[];
  draft?: unknown;
  trail_capability?: {
    status?: string;
    message?: string;
    fields_visible?: string[];
  };
  selected_run?: { id?: string; name?: string };
}

interface TrailStatusResponse {
  trail_update_statuses?: Record<string, string>;
  trail_update_details?: Record<string, TrailDetailObj>;
  trail_capability?: TrailPreviewResponse["trail_capability"];
  trail_update_status_summary?: Record<string, number>;
  pending_count?: number;
  write_status?: string;
  write_ready?: boolean;
  checked_at?: string;
}

interface DirectEntryRow {
  uid: number;
  issue_id: string;
  comment: string;
  source?: TrailHistoricalSource | null;
}

interface IssueHistoryBatch {
  status: string;
  created_at?: string;
  actor?: string;
  requested_count?: number;
  synced_count?: number;
  failed_count?: number;
  operation_id?: string;
  message?: string;
  entries?: Array<{
    issue_id?: string;
    comment?: string;
    status?: string;
    detail?: string;
    source?: TrailHistoricalSource;
  }>;
}

interface LocalImportCandidate {
  issue_id: string;
  can_import: boolean;
  local_excluded?: boolean | null;
  remote_reason?: string | null;
  blocked_reason?: string | null;
}

interface LocalImportPreviewResponse {
  preview_id: string;
  direction: string;
  items: Array<{
    issue_id: string;
    before: { is_excluded?: boolean | null; rationale?: string | null };
    after: { rationale?: string | null };
    unchanged?: boolean;
    expected_output?: string | null;
  }>;
}

interface ImportPreviewResponse {
  can_apply?: boolean;
  entries?: Array<{ issue_id: string; comment?: string; source?: TrailHistoricalSource }>;
  global_errors?: string[];
  warnings?: string[];
  summary?: {
    source_row_count?: number;
    ready_count?: number;
    skipped_count?: number;
    invalid_count?: number;
    message?: string;
  };
  items?: Array<{
    row_number?: number;
    issue_id?: string;
    should_exclude?: boolean | null;
    comment?: string;
    source?: TrailHistoricalSource;
    source_label?: string;
    status?: string;
    message?: string;
  }>;
}

interface LegacyWindow {
  showToast?: (msg: string, isError?: boolean) => void;
  openAnalysisDiscussion?: (issueId: string, opts?: Record<string, unknown>) => Promise<void>;
}

function getLegacyWindow(): LegacyWindow {
  return window as unknown as LegacyWindow;
}

const PROGRESS_STAGES = [
  { key: "prepare", zh: "校验预览", en: "Validate preview", subZh: "确认本次写入内容未变化", subEn: "Confirm the draft is unchanged" },
  { key: "request", zh: "连接 Trail 接口", en: "Connect to Trail", subZh: "发起一次受控提交", subEn: "Start the guarded commit" },
  { key: "write", zh: "分批写入字段与排除说明", en: "Write fields and exclusion notes in batches", subZh: "说明与屏蔽标记一起写入 info", subEn: "Save the note with the exclusion marker in info" },
  { key: "readback", zh: "批量回读并校验", en: "Read back and verify", subZh: "确认每个成功项已写入", subEn: "Verify every successful item" },
  { key: "done", zh: "完成", en: "Complete", subZh: "展示字段、排除说明和回读结果", subEn: "Show fields, exclusion notes, and readback results" },
] as const;

const STATUS_PRIORITY = [
  "needs_exclusion",
  "reason_sync",
  "reason_needed",
  "matched",
  "excluded",
  "not_excluded",
  "querying",
  "unconfirmed",
];

function trailStatusGroup(status: string): string {
  const map: Record<string, string> = {
    reason_changed: "reason_sync",
    reason_missing: "reason_sync",
    excluded_keep_reason: "reason_needed",
    excluded_no_reason: "matched",
    synced: "matched",
    reconcile_excluded: "excluded",
    reconcile_not_excluded: "not_excluded",
    query_failed: "unconfirmed",
    not_found: "unconfirmed",
    pending: "unconfirmed",
    not_checked: "unconfirmed",
  };
  if (map[status]) return map[status];
  return STATUS_PRIORITY.includes(status) ? status : "unconfirmed";
}

function trailStatusMeta(status: string, lang: UiLanguage) {
  const key = String(status || "not_checked");
  const labels: Record<string, [string, string, string, string, string]> = {
    reason_sync: ["理由可同步", "Reason ready to sync", "is-reason", "本地有理由且与 Trail 不同，可预览同步", "A local reason differs from Trail and can be previewed for sync"],
    reason_needed: ["本地理由待补", "Local reason needed", "is-reason-needed", "没有可提交的本地理由；请先补充标注依据，保留 Trail 原文", "No local reason to submit; add annotation evidence first. Trail text is preserved"],
    excluded: ["已排除", "Excluded", "is-synced", "排除已生效，理由已核对", "Exclusion is active and the reason has been checked"],
    matched: ["已同步", "Synced", "is-synced", "本地与 Trail 排除标记、理由一致（含两端理由均为空）", "Local and Trail exclusion and reasons match, including two empty reasons"],
    not_excluded: ["未排除", "Not excluded", "is-not-checked", "远端未排除或未设置标记；核对视图只读", "Remote marker is false or unset; reconciliation is read-only"],
    unconfirmed: ["无法确认", "Unconfirmed", "is-failed", "查询未完成或失败，请刷新重试", "Not checked or the query failed; refresh to retry"],
    reconcile_excluded: ["已排除", "Excluded", "is-excluded", "仅供核对，不进入提交集合", "Read-only; excluded from submissions"],
    reconcile_not_excluded: ["未排除", "Not excluded", "is-not-checked", "历史记录不代表当前状态", "Historical membership is not the current state"],
    querying: ["查询中", "Checking", "is-querying", "等待 Trail 查询", "Waiting for Trail"],
    synced: ["已排除", "Excluded", "is-synced", "排除标记与理由一致", "Exclusion and reason match"],
    pending: ["待同步", "Pending", "is-pending", "请刷新以查看具体差异", "Refresh to inspect differences"],
    needs_exclusion: ["待排除", "Awaiting exclusion", "is-pending", "Trail 尚无有效排除标记", "Trail has no active exclusion"],
    reason_changed: ["理由待更新", "Update reason", "is-reason", "排除已生效，仅理由不同", "Already excluded; only the reason differs"],
    reason_missing: ["理由待更新", "Update reason", "is-reason", "排除已生效，可补充理由", "Already excluded; a reason can be added"],
    excluded_keep_reason: ["理由待更新", "Reason needs update", "is-reason", "本地理由缺失，待核对原始来源；Trail 原文保留", "Local reason missing; verify its original source. The Trail text is preserved"],
    excluded_no_reason: ["已同步", "Synced", "is-synced", "两端均已排除且理由均为空，无需更新", "Both sides are excluded with empty reasons; no update needed"],
    not_found: ["无法确认", "Unconfirmed", "is-not-found", "Trail 未返回此 Issue，请刷新重试", "Issue missing from Trail; refresh to retry"],
    query_failed: ["无法确认", "Unconfirmed", "is-failed", "查询失败或预览过期，请刷新重试", "Query failed or preview expired; refresh to retry"],
    not_checked: ["未检查", "Not checked", "is-not-checked", "请刷新查询 Trail", "Refresh to check Trail"],
  };
  const entry = labels[key] || labels.not_checked;
  const groupKey = trailStatusGroup(key);
  const group = labels[groupKey] || labels.not_checked;
  return {
    key: groupKey,
    label: bilingual(lang, group[0], group[1]),
    className: group[2],
    detail: bilingual(lang, entry[3], entry[4]),
  };
}

function rowKey(item: TrailCandidateItem): string {
  return item.row_key || `${item.baseline_id || ""}|${item.issue_id}`;
}

function reasonState(item: TrailCandidateItem): string {
  if (
    item.readonly &&
    item.trail_detail &&
    !["querying", "query_failed", "not_checked", "not_found", "pending"].includes(
      String(item.trail_detail.state || ""),
    )
  ) {
    return item.trail_detail.trail_should_exclude === true
      ? "reconcile_excluded"
      : "reconcile_not_excluded";
  }
  return String(item.trail_detail?.state || item.trail_update_status || "not_checked");
}

function localState(item: TrailCandidateItem): "true" | "false" | "unknown" {
  return item.local_selected === true ? "true" : item.local_selected === false ? "false" : "unknown";
}

function remoteState(item: TrailCandidateItem): "true" | "false" | "unset" | "unknown" {
  const detail = item.trail_detail;
  if (
    !detail ||
    ["querying", "query_failed", "not_checked", "not_found", "pending"].includes(
      String(detail.state || ""),
    )
  ) {
    return "unknown";
  }
  return detail.trail_should_exclude === true
    ? "true"
    : detail.trail_should_exclude === false
      ? "false"
      : "unset";
}

function reasonAuthor(item: TrailCandidateItem): string {
  return String(item.reason_source?.author || item.review?.reviewer || "").trim();
}

function parseIssueTokens(raw: string): { ids: string[]; invalid: string[] } {
  const tokens = String(raw || "")
    .split(/[\s,，、;；]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const ids: string[] = [];
  const invalid: string[] = [];
  const seen = new Set<string>();
  for (const token of tokens) {
    const match = token.match(/\b(cn\d{4,16})\b/i);
    const id = match ? match[1].toLowerCase() : /^[A-Za-z0-9_-]{3,128}$/.test(token) ? token : "";
    if (!id) {
      invalid.push(token);
      continue;
    }
    if (!seen.has(id)) {
      seen.add(id);
      ids.push(id);
    }
  }
  return { ids, invalid };
}

function targetSpec(data: TrailPreviewResponse | null) {
  const field =
    String(
      data?.target_field ||
        (data?.write_mode === "info_only" ? data?.target_fields?.[0] : data?.target_fields?.[1]) ||
        "ra_stuck_auto_result_info",
    ).trim() || "ra_stuck_auto_result_info";
  const path = String(data?.target_path || "ra_triage_dashboard.should_exclude")
    .trim()
    .replace(/^\.+|\.+$/g, "");
  return { field, path, fullPath: path ? `${field}.${path}` : field };
}

function writeReady(data: TrailPreviewResponse | null): boolean {
  return Boolean(data && (data.write_status === "ready" || data.write_ready === true));
}

function historyStatusMeta(status: string | undefined, lang: UiLanguage) {
  const map: Record<string, [string, string, string]> = {
    pending: ["待提交", "Pending", "is-pending"],
    completed: ["已排除", "Excluded", "is-success"],
    synced: ["已排除", "Excluded", "is-success"],
    unknown: ["结果待确认", "Unconfirmed outcome", "is-warning"],
    partial: ["部分成功", "Partial", "is-warning"],
    failed: ["失败", "Failed", "is-error"],
    trail_synced_not_in_dashboard: ["已排除（看板外）", "Excluded (outside dashboard)", "is-warning"],
  };
  const entry = map[String(status || "pending")] || map.pending;
  return { label: bilingual(lang, entry[0], entry[1]), className: entry[2] };
}

function parseInitialTrailRoute() {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get("tab") === "issue" ? "issue" : "review";
  const view = params.get("view") === "reconciliation" ? "reconciliation" : "local";
  const rawPage = Number(params.get("page") || "1");
  const rawSize = Number(params.get("page_size") || String(DEFAULT_CASE_PAGE_SIZE));
  return {
    tab: tab as "review" | "issue",
    view: view as "local" | "reconciliation",
    exclusionIssue: params.get("exclusion_issue") || "",
    search: params.get("search") || "",
    sourceKind: params.get("source_kind") || "",
    localState: params.get("local_state") || "",
    remoteState: params.get("remote_state") || "",
    gtLabel: (params.get("gt_label") || "").split(",").filter((v) => (LABELS as readonly string[]).includes(v)),
    reviewer: (params.get("annotation_author") || params.get("reviewer") || "").split(",").filter(Boolean),
    trailStatus: (params.get("trail_status") || "").split(",").filter(Boolean).map(trailStatusGroup),
    page: Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1,
    pageSize: (CASE_PAGE_SIZES as readonly number[]).includes(rawSize) ? rawSize : DEFAULT_CASE_PAGE_SIZE,
  };
}

export interface TrailUpdatePageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
  canWrite: boolean;
}

export const TrailUpdatePage: React.FC<TrailUpdatePageProps> = ({
  active,
  lang,
  selectedBaselines,
  canWrite,
}) => {
  const queryClient = useQueryClient();
  const baselinesParam = selectedBaselines.join(",");
  const init = useMemo(() => parseInitialTrailRoute(), []);

  const [tab, setTab] = useState<"review" | "issue">(init.tab);
  const [view, setView] = useState<"local" | "reconciliation">(init.view);
  const [searchInput, setSearchInput] = useState<string>(init.search);
  const [search, setSearch] = useState<string>(init.search);
  const [sourceKind, setSourceKind] = useState<string>(init.sourceKind);
  const [localStateFilter, setLocalStateFilter] = useState<string>(init.localState);
  const [remoteStateFilter, setRemoteStateFilter] = useState<string>(init.remoteState);
  const [gtFilter, setGtFilter] = useState<string[]>(init.gtLabel);
  const [reviewerFilter, setReviewerFilter] = useState<string[]>(init.reviewer);
  const [statusFilter, setStatusFilter] = useState<string[]>(init.trailStatus);
  const [page, setPage] = useState<number>(init.page);
  const [pageSize, setPageSize] = useState<number>(init.pageSize);
  const [statusBanner, setStatusBanner] = useState<string>("");
  const [historyOpLink, setHistoryOpLink] = useState<string>("");

  // Two-stage data + async Trail status patch
  const [patchedPreview, setPatchedPreview] = useState<TrailPreviewResponse | null>(null);
  const [statusPatchedKey, setStatusPatchedKey] = useState<string>("");
  const statusReqSeqRef = useRef<number>(0);

  // Batch selection mode
  const [selectionMode, setSelectionMode] = useState<boolean>(false);
  const [selectionIntent, setSelectionIntent] = useState<"reason_only" | "exclude">("reason_only");
  const [selectedIssues, setSelectedIssues] = useState<Set<string>>(() => new Set());
  const [selectionBusy, setSelectionBusy] = useState<boolean>(false);

  // Tab 2: Direct Issue ID shielding
  const nextUidRef = useRef<number>(2);
  const [directRows, setDirectRows] = useState<DirectEntryRow[]>(() => [
    { uid: 1, issue_id: init.tab === "issue" ? init.exclusionIssue : "", comment: "" },
  ]);
  const [directStatus, setDirectStatus] = useState<string>("");
  const [directPreview, setDirectPreview] = useState<TrailPreviewResponse | null>(null);
  const [directBusy, setDirectBusy] = useState<boolean>(false);

  // Dialog states
  const [reasonDetailItem, setReasonDetailItem] = useState<TrailCandidateItem | null>(null);
  const [jsonModal, setJsonModal] = useState<{
    title: string;
    subtitle: string;
    filename: string;
    text: string;
  } | null>(null);
  const [nonExclOpen, setNonExclOpen] = useState<boolean>(false);
  const [nonExclInput, setNonExclInput] = useState<string>("");
  const [nonExclError, setNonExclError] = useState<string>("");
  const [nonExclBusy, setNonExclBusy] = useState<boolean>(false);

  // Local Import Dialog state
  const [localImportOpen, setLocalImportOpen] = useState<boolean>(false);
  const [localImportCandidates, setLocalImportCandidates] = useState<LocalImportCandidate[]>([]);
  const [localImportSelected, setLocalImportSelected] = useState<Set<string>>(() => new Set());
  const [localImportManualOpen, setLocalImportManualOpen] = useState<boolean>(false);
  const [localImportManualInput, setLocalImportManualInput] = useState<string>("");
  const [localImportScanState, setLocalImportScanState] = useState<{
    loading: boolean;
    scanning: boolean;
    scanned: number;
    total: number;
    done: boolean;
    checkedAt: string | null;
    snapshotTotal: number;
    membershipChanged: boolean;
    error: string;
  }>({
    loading: false,
    scanning: false,
    scanned: 0,
    total: 0,
    done: false,
    checkedAt: null,
    snapshotTotal: 0,
    membershipChanged: false,
    error: "",
  });
  const [localImportPreview, setLocalImportPreview] = useState<LocalImportPreviewResponse | null>(null);
  const [localImportFeedback, setLocalImportFeedback] = useState<{ text: string; error?: boolean }>({
    text: "",
  });
  const [localImportBusy, setLocalImportBusy] = useState<boolean>(false);
  const localImportPollRef = useRef<number | null>(null);

  // JSON / Excel Import Dialog state
  const [issueImportMode, setIssueImportMode] = useState<"json" | "excel" | null>(null);
  const [issueImportText, setIssueImportText] = useState<string>("");
  const [issueImportFile, setIssueImportFile] = useState<File | null>(null);
  const [issueImportFileName, setIssueImportFileName] = useState<string>("");
  const [issueImportStatus, setIssueImportStatus] = useState<{ text: string; error?: boolean }>({
    text: "",
  });
  const [issueImportPreview, setIssueImportPreview] = useState<ImportPreviewResponse | null>(null);
  const [issueImportBusy, setIssueImportBusy] = useState<boolean>(false);
  const issueImportFileInputRef = useRef<HTMLInputElement | null>(null);

  // Confirm & Progress Dialogs
  const [confirmState, setConfirmState] = useState<{
    mode: "review" | "direct_issue_ids";
    data: TrailPreviewResponse;
    onConfirm: () => void;
  } | null>(null);
  const [confirmExpandAll, setConfirmExpandAll] = useState<boolean>(false);
  const [progressState, setProgressState] = useState<{
    open: boolean;
    running: boolean;
    result?: "success" | "warning" | "error";
    stage: string;
    total: number;
    message: string;
    startedAt: number;
    elapsedSec: number;
    operationId?: string;
  }>({
    open: false,
    running: false,
    stage: "prepare",
    total: 0,
    message: "",
    startedAt: 0,
    elapsedSec: 0,
  });

  // Dialog refs
  const reasonDialogRef = useRef<HTMLDialogElement | null>(null);
  const jsonDialogRef = useRef<HTMLDialogElement | null>(null);
  const nonExclDialogRef = useRef<HTMLDialogElement | null>(null);
  const localImportDialogRef = useRef<HTMLDialogElement | null>(null);
  const issueImportDialogRef = useRef<HTMLDialogElement | null>(null);
  const confirmDialogRef = useRef<HTMLDialogElement | null>(null);
  const progressDialogRef = useRef<HTMLDialogElement | null>(null);

  const syncDialog = (ref: React.RefObject<HTMLDialogElement | null>, open: boolean) => {
    const dlg = ref.current;
    if (!dlg) return;
    if (open) {
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
  };

  useEffect(() => syncDialog(reasonDialogRef, Boolean(reasonDetailItem)), [reasonDetailItem]);
  useEffect(() => syncDialog(jsonDialogRef, Boolean(jsonModal)), [jsonModal]);
  useEffect(() => syncDialog(nonExclDialogRef, nonExclOpen), [nonExclOpen]);
  useEffect(() => syncDialog(localImportDialogRef, localImportOpen), [localImportOpen]);
  useEffect(() => syncDialog(issueImportDialogRef, Boolean(issueImportMode)), [issueImportMode]);
  useEffect(() => syncDialog(confirmDialogRef, Boolean(confirmState)), [confirmState]);
  useEffect(() => syncDialog(progressDialogRef, progressState.open), [progressState.open]);

  // Progress elapsed timer
  useEffect(() => {
    if (!progressState.open || !progressState.running) return;
    const t = window.setInterval(() => {
      setProgressState((prev) => ({
        ...prev,
        elapsedSec: Math.max(0, Math.floor((Date.now() - prev.startedAt) / 1000)),
      }));
    }, 500);
    return () => window.clearInterval(t);
  }, [progressState.open, progressState.running]);

  // Debounce search input
  useEffect(() => {
    const t = window.setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, 180);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  // Stage 1: Fast local preview query
  const previewScopeKey = `${baselinesParam}|${view}`;
  const previewQuery = useQuery<TrailPreviewResponse>({
    queryKey: ["trail-update-preview", baselinesParam, view],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams();
      if (baselinesParam) params.set("baselines", baselinesParam);
      if (view === "reconciliation") params.set("reconciliation", "true");
      params.set("probe_trail", "false");
      return apiRequest<TrailPreviewResponse>(
        `/api/trail-attribute-update/preview?${params.toString()}`,
        { signal, cache: "no-store" },
      );
    },
    enabled: active && tab === "review",
    staleTime: 10_000,
  });

  // Stage 2: Async Trail status probe
  const runStatusProbe = useCallback(
    async (baseData: TrailPreviewResponse, scopeKey: string, force = false) => {
      const items = baseData.items || [];
      if (!items.length) {
        setPatchedPreview(baseData);
        setStatusPatchedKey(scopeKey);
        return;
      }
      const seq = ++statusReqSeqRef.current;
      const ids = [...new Set(items.map((it) => String(it.issue_id || "").trim()).filter(Boolean))];
      const params = new URLSearchParams();
      if (ids.length) params.set("issue_ids", ids.join(","));
      if (baseData.payload_sha256) params.set("payload_sha256", baseData.payload_sha256);
      if (force) params.set("refresh", "true");
      try {
        const st = await apiRequest<TrailStatusResponse>(
          `/api/trail-attribute-update/status?${params.toString()}`,
          { cache: "no-store" },
        );
        if (seq !== statusReqSeqRef.current) return;
        const statuses = st.trail_update_statuses || {};
        const details = st.trail_update_details || {};
        const merged: TrailPreviewResponse = {
          ...baseData,
          trail_capability: st.trail_capability || baseData.trail_capability,
          pending_count: Number(st.pending_count ?? baseData.pending_count ?? 0),
          write_status: st.write_status || baseData.write_status,
          write_ready: st.write_ready === true,
          checked_at: st.checked_at || baseData.checked_at,
          items: items.map((it) => {
            const id = String(it.issue_id || "");
            if (Object.prototype.hasOwnProperty.call(statuses, id)) {
              return {
                ...it,
                trail_update_status: statuses[id],
                trail_detail: details[id] || { state: statuses[id] },
              };
            }
            return it;
          }),
        };
        setPatchedPreview(merged);
        setStatusPatchedKey(scopeKey);
        setStatusBanner("");
      } catch {
        if (seq !== statusReqSeqRef.current) return;
        const failed: TrailPreviewResponse = {
          ...baseData,
          write_status: "status_check_incomplete",
          write_ready: false,
          items: items.map((it) => ({
            ...it,
            trail_update_status: "query_failed",
            trail_detail: { state: "query_failed" },
          })),
        };
        setPatchedPreview(failed);
        setStatusPatchedKey(scopeKey);
        setStatusBanner(
          bilingual(
            lang,
            "Trail 状态查询失败；案例已加载，可点击顶部刷新重试。",
            "Trail status check failed; cases are loaded. Use the top refresh to retry.",
          ),
        );
      }
    },
    [lang],
  );

  useEffect(() => {
    if (!active || tab !== "review" || !previewQuery.data) return;
    setPatchedPreview(previewQuery.data);
    setStatusPatchedKey(previewScopeKey);
    void runStatusProbe(previewQuery.data, previewScopeKey, false);
  }, [active, tab, previewQuery.data, previewScopeKey, runStatusProbe]);

  // Reset batch selection on scope/view change
  useEffect(() => {
    setSelectionMode(false);
    setSelectedIssues(new Set());
  }, [previewScopeKey]);

  // Tab 2 history query
  const issueHistoryQuery = useQuery<{ items?: IssueHistoryBatch[] }>({
    queryKey: ["trail-issue-history"],
    queryFn: ({ signal }) =>
      apiRequest("/api/trail-attribute-update/issue-history?limit=20", { signal }),
    enabled: active && tab === "issue",
    staleTime: 10_000,
  });

  const data = statusPatchedKey === previewScopeKey && patchedPreview ? patchedPreview : previewQuery.data || null;
  const allItems = data?.items || [];

  // Filter items (matches classic trailUpdateFilteredItems)
  const filterItems = useCallback(
    (ignoreStatus = false) => {
      const q = search.trim().toLocaleLowerCase();
      const gtSet = new Set(gtFilter);
      const revSet = new Set(reviewerFilter);
      const stSet = new Set(ignoreStatus ? [] : statusFilter);
      return allItems.filter((item) => {
        if (sourceKind && sourceKind !== item.source_kind) return false;
        if (localStateFilter && localStateFilter !== localState(item)) return false;
        if (remoteStateFilter && remoteStateFilter !== remoteState(item)) return false;
        if (q) {
          const hay = [
            item.issue_id,
            item.title,
            item.scenario,
            item.gt_label,
            item.model?.label,
            item.model?.reason,
            item.review?.reviewer,
            reasonAuthor(item),
            item.review?.status,
            item.review?.note,
            item.comment,
            item.trail_detail?.local_comment,
            item.trail_detail?.trail_comment,
            item.baseline_id,
            item.baseline_scope,
          ]
            .filter(Boolean)
            .join(" ")
            .toLocaleLowerCase();
          if (!hay.includes(q)) return false;
        }
        if (gtSet.size && !gtSet.has(String(item.gt_label || ""))) return false;
        if (revSet.size && !revSet.has(reasonAuthor(item))) return false;
        if (stSet.size && !stSet.has(trailStatusGroup(reasonState(item)))) return false;
        return true;
      });
    },
    [allItems, search, sourceKind, localStateFilter, remoteStateFilter, gtFilter, reviewerFilter, statusFilter],
  );

  const itemsForStatusChart = useMemo(() => filterItems(true), [filterItems]);
  const filteredItems = useMemo(() => filterItems(false), [filterItems]);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    itemsForStatusChart.forEach((it) => {
      const g = trailStatusGroup(reasonState(it));
      counts[g] = (counts[g] || 0) + 1;
    });
    return counts;
  }, [itemsForStatusChart]);

  const statusEntries = useMemo(() => {
    const raw = Object.entries(statusCounts).filter(([, c]) => c > 0);
    return raw.length
      ? raw.sort(([a], [b]) => STATUS_PRIORITY.indexOf(a) - STATUS_PRIORITY.indexOf(b))
      : ([["not_checked", 0]] as Array<[string, number]>);
  }, [statusCounts]);

  const statusTotal = useMemo(
    () => Object.values(statusCounts).reduce((sum, c) => sum + c, 0),
    [statusCounts],
  );

  const totalPages = Math.max(1, Math.ceil(filteredItems.length / pageSize));
  const safePage = Math.min(Math.max(1, page), totalPages);
  const pageStart = filteredItems.length ? (safePage - 1) * pageSize : 0;
  const pageItems = filteredItems.slice(pageStart, pageStart + pageSize);

  const isEligible = useCallback(
    (item: TrailCandidateItem): boolean => {
      if (item.readonly || view === "reconciliation") return false;
      const d = item.trail_detail || {};
      return selectionIntent === "reason_only"
        ? d.trail_should_exclude === true && d.needs_reason_update === true
        : d.needs_exclusion_update === true;
    },
    [view, selectionIntent],
  );

  const pageEligibleIds = useMemo(
    () => pageItems.filter(isEligible).map((it) => it.issue_id),
    [pageItems, isEligible],
  );

  const selectionReady = useMemo(() => {
    if (!writeReady(data) || selectedIssues.size === 0 || selectedIssues.size > 200) return false;
    const byId = new Map(allItems.map((it) => [it.issue_id, it]));
    return [...selectedIssues].every((id) => {
      const it = byId.get(id);
      return Boolean(it && isEligible(it));
    });
  }, [data, selectedIssues, allItems, isEligible]);

  // Filter options
  const statusOptions: MultiSelectOption[] = useMemo(() => {
    const distinct = [
      ...new Set([...allItems.map((it) => trailStatusGroup(reasonState(it))), ...statusFilter]),
    ].sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
    return distinct.map((v) => ({ value: v, label: trailStatusMeta(v, lang).label }));
  }, [allItems, statusFilter, lang]);

  const gtOptions: MultiSelectOption[] = useMemo(
    () =>
      LABELS.filter((lbl) => allItems.some((it) => it.gt_label === lbl) || gtFilter.includes(lbl)).map(
        (v) => ({ value: v, label: v }),
      ),
    [allItems, gtFilter],
  );

  const reviewerOptions: MultiSelectOption[] = useMemo(() => {
    const distinct = [...new Set([...allItems.map(reasonAuthor).filter(Boolean), ...reviewerFilter])].sort(
      (a, b) => a.localeCompare(b, "zh-Hans-CN"),
    );
    return distinct.map((v) => ({ value: v, label: v }));
  }, [allItems, reviewerFilter]);

  const advancedCount = [
    sourceKind,
    localStateFilter,
    remoteStateFilter,
    gtFilter.length,
    reviewerFilter.length,
  ].filter(Boolean).length;

  // Direct Issue ID entry parser
  const parsedDirect = useMemo(() => {
    const entries: Array<{ issue_id: string; comment: string; source?: TrailHistoricalSource }> = [];
    const invalid: string[] = [];
    const seen = new Set<string>();
    directRows.forEach((row, idx) => {
      const raw = row.issue_id.trim();
      const comment = row.comment.trim().slice(0, 4000);
      if (!raw && !comment) return;
      const p = parseIssueTokens(raw);
      if (p.invalid.length) {
        invalid.push(...p.invalid.map((tok) => `${tok}（第 ${idx + 1} 行）`));
      }
      if (!p.ids.length) {
        invalid.push(`${raw || `第 ${idx + 1} 行`}（未识别到 Issue ID）`);
        return;
      }
      p.ids.forEach((id) => {
        if (seen.has(id)) {
          invalid.push(`${id}（重复）`);
          return;
        }
        seen.add(id);
        const srcMatch =
          row.source && p.ids.length === 1 && String(row.source.issue_id || "") === id
            ? row.source
            : undefined;
        entries.push({ issue_id: id, comment, ...(srcMatch ? { source: srcMatch } : {}) });
      });
    });
    entries.sort((a, b) => a.issue_id.localeCompare(b.issue_id));
    return { ids: entries.map((e) => e.issue_id), invalid, entries };
  }, [directRows]);

  // --- Action Handlers ---
  const openJsonDraft = (mode: "review" | "issue") => {
    const draft = mode === "issue" ? directPreview?.draft : data?.draft;
    if (!draft) {
      getLegacyWindow().showToast?.(
        bilingual(lang, "当前没有可预览的 JSON 草稿。", "There is no JSON draft to preview."),
        true,
      );
      return;
    }
    const safeName = String(data?.selected_run?.name || data?.selected_run?.id || "run").replace(
      /[^A-Za-z0-9._-]+/g,
      "_",
    );
    setJsonModal({
      text: JSON.stringify(draft, null, 2),
      filename:
        mode === "issue"
          ? "trail_issue_exclusion_update.json"
          : `trail_attribute_update_${safeName}.json`,
      title:
        mode === "issue"
          ? bilingual(lang, "Issue 屏蔽 JSON 预览", "Issue shielding JSON preview")
          : bilingual(lang, "问题排除 JSON 预览", "Issue exclusion JSON preview"),
      subtitle:
        mode === "issue"
          ? bilingual(
              lang,
              "当前 Issue ID 屏蔽 Tab 的草稿；可复制或下载。",
              "Draft from the Issue shielding tab; copy or download it.",
            )
          : bilingual(
              lang,
              "当前 Review 排除汇总 Tab 的草稿；可复制或下载。",
              "Draft from the Review exclusion tab; copy or download it.",
            ),
    });
  };

  const handleCopyText = (text: string, msgZh: string, msgEn: string) => {
    navigator.clipboard
      ?.writeText(text)
      .then(() => getLegacyWindow().showToast?.(bilingual(lang, msgZh, msgEn)))
      .catch(() =>
        getLegacyWindow().showToast?.(
          bilingual(lang, "无法复制，请选择文本复制", "Could not copy; select text to copy"),
          true,
        ),
      );
  };

  // Batch commit workflow
  const handleBatchSelectionCommit = async () => {
    if (!selectionReady || selectionBusy || !data) return;
    const issueIds = [...selectedIssues];
    setSelectionBusy(true);
    setStatusBanner(
      bilingual(lang, "正在核对所选案例的最新理由…", "Checking the latest reasons for selected cases…"),
    );
    try {
      const preview = await apiRequest<TrailPreviewResponse>(
        "/api/trail-attribute-update/selection-preview",
        {
          method: "POST",
          body: {
            issue_ids: issueIds,
            intent: selectionIntent,
            baselines: data.baselines || [],
          },
        },
      );
      setConfirmExpandAll(false);
      setConfirmState({
        mode: "review",
        data: preview,
        onConfirm: async () => {
          setConfirmState(null);
          setProgressState({
            open: true,
            running: true,
            stage: "request",
            total: issueIds.length,
            message: bilingual(
              lang,
              "服务端正在分批写入；完成后会统一回读，请不要重复提交。",
              "The server is writing in batches; it will read back once complete.",
            ),
            startedAt: Date.now(),
            elapsedSec: 0,
          });
          try {
            const result = await apiRequest<{
              ok?: boolean;
              payload_sha256?: string;
              readback?: { verified_count?: number };
              skipped_synced_issue_ids?: string[];
              failed_issue_ids?: string[];
            }>("/api/trail-attribute-update/selection-commit", {
              method: "POST",
              body: { confirm: true, payload_sha256: preview.payload_sha256 },
            });
            const msg = bilingual(
              lang,
              `Trail 已验证 ${result.readback?.verified_count || 0} 条，跳过已成功 ${
                result.skipped_synced_issue_ids?.length || 0
              } 条；本地标注无需补写。${
                result.failed_issue_ids?.length
                  ? ` 未确认：${result.failed_issue_ids.join("、")}`
                  : ""
              }`,
              `Trail verified ${result.readback?.verified_count || 0}; ${
                result.skipped_synced_issue_ids?.length || 0
              } already applied.`,
            );
            setProgressState((prev) => ({
              ...prev,
              running: false,
              stage: result.ok ? "done" : "request",
              result: result.ok ? "success" : "error",
              message: msg,
              operationId: result.ok ? result.payload_sha256 : "",
            }));
            if (result.ok && result.payload_sha256) setHistoryOpLink(result.payload_sha256);
            setStatusBanner(msg);
            if (result.ok) setSelectedIssues(new Set());
            void runStatusProbe(data, previewScopeKey, true);
          } catch (err) {
            setProgressState((prev) => ({
              ...prev,
              running: false,
              result: "error",
              message: (err as Error)?.message || "Commit failed",
            }));
            setStatusBanner((err as Error)?.message || "Commit failed");
          }
        },
      });
    } catch (err) {
      setStatusBanner((err as Error)?.message || "Preview failed");
      getLegacyWindow().showToast?.((err as Error)?.message || "Preview failed", true);
    } finally {
      setSelectionBusy(false);
    }
  };

  // Non-exclusion preview & commit
  const handleNonExclPreview = async () => {
    const parsed = parseIssueTokens(nonExclInput);
    if (!parsed.ids.length || parsed.ids.length > 200 || parsed.invalid.length || nonExclBusy) return;
    setNonExclBusy(true);
    setNonExclError("");
    try {
      const preview = await apiRequest<TrailPreviewResponse>(
        "/api/trail-attribute-update/non-exclusion-preview",
        {
          method: "POST",
          body: { issue_ids: parsed.ids, baselines: baselinesParam },
        },
      );
      if (preview.intent !== "unexclude" || !preview.write_ready || !preview.payload_sha256) {
        throw new Error(bilingual(lang, "预览无效，请重新核验。", "Invalid preview; check again."));
      }
      setConfirmExpandAll(false);
      setConfirmState({
        mode: "review",
        data: preview,
        onConfirm: async () => {
          setConfirmState(null);
          setNonExclOpen(false);
          setProgressState({
            open: true,
            running: true,
            stage: "request",
            total: parsed.ids.length,
            message: bilingual(lang, "正在同步不排除…", "Syncing non-exclusion…"),
            startedAt: Date.now(),
            elapsedSec: 0,
          });
          try {
            const res = await apiRequest<{
              ok?: boolean;
              payload_sha256?: string;
              readback?: { verified_count?: number };
              skipped_synced_issue_ids?: string[];
            }>("/api/trail-attribute-update/non-exclusion-commit", {
              method: "POST",
              body: { confirm: true, payload_sha256: preview.payload_sha256 },
            });
            const verified =
              Number(res.readback?.verified_count || 0) +
              Number(res.skipped_synced_issue_ids?.length || 0);
            const msg = res.ok
              ? bilingual(
                  lang,
                  `已确认 ${verified} 条不排除更新；原理由和本地标注不变。`,
                  `${verified} non-exclusion updates confirmed.`,
                )
              : bilingual(
                  lang,
                  "部分更新未确认，请查看记录并刷新核对。",
                  "Some updates are unconfirmed; inspect the record and refresh.",
                );
            setProgressState((prev) => ({
              ...prev,
              running: false,
              stage: res.ok ? "done" : "request",
              result: res.ok ? "success" : "error",
              message: msg,
              operationId: res.ok ? res.payload_sha256 : "",
            }));
            if (res.ok) {
              setNonExclInput("");
              if (res.payload_sha256) setHistoryOpLink(res.payload_sha256);
            }
            if (data) void runStatusProbe(data, previewScopeKey, true);
          } catch (err) {
            setProgressState((prev) => ({
              ...prev,
              running: false,
              result: "error",
              message: (err as Error)?.message || "Commit failed",
            }));
          }
        },
      });
    } catch (err) {
      setNonExclError((err as Error)?.message || "Preview failed");
    } finally {
      setNonExclBusy(false);
    }
  };

  // Local Import Scan (Trail -> Local)
  const scanLocalImport = useCallback(
    async (refresh = false) => {
      if (localImportPollRef.current) window.clearTimeout(localImportPollRef.current);
      setLocalImportScanState((prev) => ({ ...prev, loading: true, error: "" }));
      if (refresh) {
        setLocalImportSelected(new Set());
        setLocalImportPreview(null);
      }
      try {
        const res = await apiRequest<{
          items?: LocalImportCandidate[];
          status?: string;
          scanned?: number;
          total?: number;
          snapshot_available?: boolean;
          checked_at?: string | null;
          snapshot_total?: number;
          membership_changed?: boolean;
          error?: string;
        }>("/api/trail-attribute-update/local-import-candidates", {
          method: "POST",
          body: { baselines: baselinesParam, refresh },
        });
        const items = Array.isArray(res.items) ? res.items : [];
        setLocalImportCandidates(items);
        const scanning = res.status === "running";
        setLocalImportScanState({
          loading: false,
          scanning,
          scanned: Number(res.scanned || 0),
          total: Number(res.total || 0),
          done: Boolean(res.snapshot_available),
          checkedAt: res.checked_at || null,
          snapshotTotal: Number(res.snapshot_total || 0),
          membershipChanged: Boolean(res.membership_changed),
          error: res.error || "",
        });
        if (scanning) {
          localImportPollRef.current = window.setTimeout(() => void scanLocalImport(false), 1500);
        }
      } catch (err) {
        setLocalImportScanState((prev) => ({
          ...prev,
          loading: false,
          scanning: false,
          error: (err as Error)?.message || "Scan failed",
        }));
      }
    },
    [baselinesParam],
  );

  useEffect(() => {
    if (!localImportOpen && localImportPollRef.current) {
      window.clearTimeout(localImportPollRef.current);
      localImportPollRef.current = null;
    }
  }, [localImportOpen]);

  const runLocalImport = async (commit: boolean) => {
    const parsed = localImportManualOpen
      ? parseIssueTokens(localImportManualInput)
      : { ids: [...localImportSelected], invalid: [] };
    if (!parsed.ids.length || parsed.invalid.length || parsed.ids.length > 200) return;
    if (commit && !localImportPreview) return;
    setLocalImportBusy(true);
    setLocalImportFeedback({ text: bilingual(lang, "正在处理…", "Working…") });
    try {
      const res = await apiRequest<LocalImportPreviewResponse & { ok?: boolean; imported_count?: number }>(
        `/api/trail-attribute-update/local-import-${commit ? "commit" : "preview"}`,
        {
          method: "POST",
          body: commit
            ? { preview_id: localImportPreview?.preview_id, confirm: true }
            : { issue_ids: parsed.ids, baselines: baselinesParam },
        },
      );
      if (commit) {
        setLocalImportPreview(null);
        setLocalImportSelected(new Set());
        setLocalImportFeedback({
          text: bilingual(
            lang,
            `已导入 ${res.imported_count || 0} 条，可在 Issue 标注记录中查看。`,
            `${res.imported_count || 0} imported; view them in Issue annotation records.`,
          ),
        });
        void queryClient.invalidateQueries({ queryKey: ["trail-update-preview"] });
      } else {
        setLocalImportPreview(res);
        setLocalImportFeedback({
          text: bilingual(
            lang,
            "请核对以下改动，确认后仅保存到本地。",
            "Review below; confirmation saves locally only.",
          ),
        });
      }
    } catch (err) {
      setLocalImportFeedback({ text: (err as Error)?.message || "Failed", error: true });
    } finally {
      setLocalImportBusy(false);
    }
  };

  // Tab 2: Build direct issue shield preview & commit
  const handleDirectPreview = async () => {
    if (parsedDirect.invalid.length || !parsedDirect.ids.length) {
      setDirectPreview(null);
      setDirectStatus(
        bilingual(
          lang,
          "请先填写合法的 Issue ID（每行可填多个）。",
          "Enter valid Issue IDs first (multiple per row are supported).",
        ),
      );
      return;
    }
    setDirectBusy(true);
    setDirectStatus(bilingual(lang, "正在检查 Issue 和 Trail 字段…", "Checking Issues and Trail fields…"));
    try {
      const res = await apiRequest<TrailPreviewResponse>(
        "/api/trail-attribute-update/issue-preview",
        {
          method: "POST",
          body: { entries: parsedDirect.entries },
        },
      );
      setDirectPreview(res);
      const count = (res.items || []).length;
      const missingCount = (res.missing_issue_ids || []).length;
      setDirectStatus(
        res.write_status === "ready"
          ? bilingual(
              lang,
              `已生成屏蔽预览：${count} 条，可提交。`,
              `Shield preview ready: ${count} item(s); commit is available.`,
            )
          : bilingual(
              lang,
              `已生成预览：${count} 条；${missingCount ? `未找到 ${missingCount} 条。` : ""}${
                res.trail_capability?.message || "当前不可写入 Trail"
              }`,
              `Preview ready: ${count} item(s); ${missingCount ? `${missingCount} missing. ` : ""}${
                res.trail_capability?.message || "Trail is not writable yet."
              }`,
            ),
      );
    } catch (err) {
      setDirectStatus((err as Error)?.message || bilingual(lang, "屏蔽预览失败。", "Shield preview failed."));
    } finally {
      setDirectBusy(false);
    }
  };

  const handleDirectCommit = () => {
    if (!writeReady(directPreview) || !directPreview) return;
    const entries =
      directPreview.requested_entries ||
      (directPreview.requested_issue_ids || []).map((id) => ({ issue_id: id, comment: "" }));
    setConfirmExpandAll(false);
    setConfirmState({
      mode: "direct_issue_ids",
      data: directPreview,
      onConfirm: async () => {
        setConfirmState(null);
        setDirectBusy(true);
        setProgressState({
          open: true,
          running: true,
          stage: "request",
          total: entries.length,
          message: bilingual(lang, "正在写入 Trail 字段和 info 排除说明…", "Writing Trail fields and info notes…"),
          startedAt: Date.now(),
          elapsedSec: 0,
        });
        try {
          const res = await apiRequest<{
            ok?: boolean;
            trail_ok?: boolean;
            payload_sha256?: string;
            stats?: { success_count?: number; failed_count?: number; total?: number };
            readback?: { verified_count?: number; checked_count?: number };
          }>("/api/trail-attribute-update/issue-commit", {
            method: "POST",
            body: {
              confirm: true,
              entries,
              payload_sha256: directPreview.payload_sha256,
            },
          });
          const ok = typeof res.trail_ok === "boolean" ? res.trail_ok : Boolean(res.ok);
          const msg = bilingual(
            lang,
            `字段与 info 排除说明 ${res.stats?.success_count || 0}/${
              res.stats?.total || entries.length
            }；回读 ${res.readback?.verified_count || 0}/${res.readback?.checked_count || 0}。`,
            `Trail fields & notes ${res.stats?.success_count || 0}/${
              res.stats?.total || entries.length
            }; read back ${res.readback?.verified_count || 0}/${res.readback?.checked_count || 0}.`,
          );
          setProgressState((prev) => ({
            ...prev,
            running: false,
            stage: ok ? "done" : "request",
            result: ok ? "success" : "error",
            message: msg,
            operationId: ok ? res.payload_sha256 : "",
          }));
          setDirectStatus(msg);
          void queryClient.invalidateQueries({ queryKey: ["trail-issue-history"] });
          void queryClient.invalidateQueries({ queryKey: ["trail-update-preview"] });
        } catch (err) {
          setProgressState((prev) => ({
            ...prev,
            running: false,
            result: "error",
            message: (err as Error)?.message || "Commit failed",
          }));
        } finally {
          setDirectBusy(false);
        }
      },
    });
  };

  // JSON / Excel import preview & apply
  const handleRunIssueImportPreview = async () => {
    if (!issueImportMode || issueImportBusy) return;
    setIssueImportBusy(true);
    try {
      if (issueImportMode === "json") {
        let parsedBody: unknown;
        try {
          parsedBody = JSON.parse(issueImportText.trim());
        } catch {
          setIssueImportStatus({
            text: bilingual(lang, "JSON 格式不合法，请粘贴对象或数组。", "Invalid JSON; paste an object or array."),
            error: true,
          });
          return;
        }
        const res = await apiRequest<ImportPreviewResponse>(
          "/api/trail-attribute-update/issue-import/json-preview",
          { method: "POST", body: parsedBody },
        );
        setIssueImportPreview(res);
        setIssueImportStatus({
          text: String(res.summary?.message || ""),
          error: Boolean((res.global_errors || []).length || res.summary?.invalid_count),
        });
      } else {
        if (!issueImportFile) {
          setIssueImportStatus({
            text: bilingual(lang, "请先选择 .xlsx 或 .xlsm 文件。", "Choose a .xlsx or .xlsm file first."),
            error: true,
          });
          return;
        }
        const form = new FormData();
        form.append("file", issueImportFile, issueImportFile.name || "issue-exclusions.xlsx");
        const res = await apiRequest<ImportPreviewResponse>(
          "/api/trail-attribute-update/issue-import/excel-preview",
          { method: "POST", body: form },
        );
        setIssueImportPreview(res);
        setIssueImportStatus({
          text: String(res.summary?.message || ""),
          error: Boolean((res.global_errors || []).length || res.summary?.invalid_count),
        });
      }
    } catch (err) {
      setIssueImportStatus({ text: (err as Error)?.message || "Import preview failed", error: true });
    } finally {
      setIssueImportBusy(false);
    }
  };

  const applyIssueImport = () => {
    if (!issueImportPreview?.can_apply || !issueImportPreview.entries?.length) return;
    setDirectRows(
      issueImportPreview.entries.map((entry) => ({
        uid: nextUidRef.current++,
        issue_id: entry.issue_id,
        comment: entry.comment || "",
        source: entry.source || null,
      })),
    );
    setDirectPreview(null);
    setIssueImportMode(null);
    getLegacyWindow().showToast?.(
      bilingual(
        lang,
        `已替换 ${issueImportPreview.entries.length} 条屏蔽草稿；尚未写入 Trail。`,
        `${issueImportPreview.entries.length} shielding draft row(s) replaced; Trail has not been written.`,
      ),
    );
  };

  // Static select options
  const viewOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "local", label: bilingual(lang, "本地候选", "Local candidates") },
      {
        value: "reconciliation",
        label: bilingual(lang, "Trail 排除核对（只读）", "Trail exclusion reconciliation (read-only)"),
      },
    ],
    [lang],
  );

  const sourceKindOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "全部来源", "All sources") },
      { value: "local", label: bilingual(lang, "仅本地候选", "Local only") },
      { value: "historical", label: bilingual(lang, "仅历史记录", "History only") },
      { value: "both", label: bilingual(lang, "本地与历史都有", "Local and historical") },
    ],
    [lang],
  );

  const localStateOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "全部", "All") },
      { value: "true", label: bilingual(lang, "排除", "Excluded") },
      { value: "false", label: bilingual(lang, "不排除", "Not excluded") },
      { value: "unknown", label: bilingual(lang, "无本地结论", "No local outcome") },
    ],
    [lang],
  );

  const remoteStateOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "全部", "All") },
      { value: "true", label: bilingual(lang, "已排除", "Excluded") },
      { value: "false", label: bilingual(lang, "未排除", "Not excluded") },
      { value: "unset", label: bilingual(lang, "未设置", "Unset") },
      { value: "unknown", label: bilingual(lang, "无法确认", "Unconfirmed") },
    ],
    [lang],
  );

  const intentOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "reason_only", label: bilingual(lang, "仅更新理由", "Reasons only") },
      { value: "exclude", label: bilingual(lang, "排除所选案例", "Exclude selected cases") },
    ],
    [lang],
  );

  const sourceLabel = (data?.baselines || []).join(" · ") || bilingual(lang, "当前数据集", "Selected datasets");
  const scopeSummaryText =
    filteredItems.length === allItems.length
      ? sourceLabel
      : `${sourceLabel} · ${bilingual(
          lang,
          `筛选 ${filteredItems.length}/${allItems.length} 条`,
          `${filteredItems.length}/${allItems.length} filtered`,
        )}`;

  const nonExclParsed = useMemo(() => parseIssueTokens(nonExclInput), [nonExclInput]);
  const nonExclValid =
    nonExclParsed.ids.length > 0 && nonExclParsed.ids.length <= 200 && !nonExclParsed.invalid.length;

  const localImportEligible = useMemo(
    () => localImportCandidates.filter((c) => c.can_import),
    [localImportCandidates],
  );
  const localImportIdsCount = localImportManualOpen
    ? parseIssueTokens(localImportManualInput).ids.length
    : localImportSelected.size;

  return (
    <div className="ra-trail-update-root" data-react-island="trail-update">
      <section className="page-card trail-update-header-card">
        <div
          className="trail-update-tabs"
          role="tablist"
          aria-label={bilingual(lang, "问题排除模式", "Trail update modes")}
        >
          <button
            className={`trail-update-tab${tab === "review" ? " active" : ""}`}
            id="trailUpdateReviewTab"
            type="button"
            role="tab"
            aria-selected={tab === "review"}
            aria-controls="trailUpdateReviewPanel"
            onClick={() => setTab("review")}
          >
            <span>{bilingual(lang, "排除汇总", "Exclusions")}</span>
            <small>{bilingual(lang, "按 Issue 汇总", "By Issue")}</small>
          </button>
          <button
            className={`trail-update-tab${tab === "issue" ? " active" : ""}`}
            id="trailUpdateIssueTab"
            type="button"
            role="tab"
            aria-selected={tab === "issue"}
            aria-controls="trailUpdateIssuePanel"
            onClick={() => setTab("issue")}
          >
            <span>{bilingual(lang, "Issue ID 屏蔽", "Shield by Issue ID")}</span>
            <small>{bilingual(lang, "按 ID 添加排除", "Add exclusions by ID")}</small>
          </button>
        </div>

        {tab === "issue" ? (
          <section className="trail-update-header-panel" id="trailUpdateIssueControlsPanel">
            <section className="trail-update-controls-card">
              <div className="trail-update-direct-lead">
                <h3>{bilingual(lang, "按 Issue ID 直接屏蔽", "Shield issues directly by ID")}</h3>
                <div className="trail-update-direct-actions">
                  <button
                    className="button button-quiet"
                    id="trailUpdateIssueJsonImportButton"
                    type="button"
                    onClick={() => {
                      setIssueImportMode("json");
                      setIssueImportPreview(null);
                      setIssueImportStatus({ text: "" });
                    }}
                  >
                    {bilingual(lang, "导入 JSON", "Import JSON")}
                  </button>
                  <button
                    className="button button-quiet"
                    id="trailUpdateIssueExcelImportButton"
                    type="button"
                    onClick={() => {
                      setIssueImportMode("excel");
                      setIssueImportPreview(null);
                      setIssueImportStatus({ text: "" });
                    }}
                  >
                    {bilingual(lang, "导入 Excel", "Import Excel")}
                  </button>
                  <button
                    className="button button-quiet"
                    id="trailUpdateIssueClearAllButton"
                    type="button"
                    onClick={() => {
                      setDirectRows([{ uid: nextUidRef.current++, issue_id: "", comment: "" }]);
                      setDirectPreview(null);
                      setDirectStatus(
                        bilingual(
                          lang,
                          "已清空所有屏蔽草稿行；尚未写入 Trail。",
                          "All shielding draft rows were cleared; Trail has not been written.",
                        ),
                      );
                    }}
                  >
                    {bilingual(lang, "清空所有行", "Clear all rows")}
                  </button>
                  <button
                    className="button button-quiet trail-update-entry-add"
                    id="trailUpdateIssueAddButton"
                    type="button"
                    onClick={() => {
                      setDirectRows((prev) => [
                        ...prev,
                        { uid: nextUidRef.current++, issue_id: "", comment: "" },
                      ]);
                      setDirectPreview(null);
                    }}
                  >
                    <span aria-hidden="true">＋</span>
                    {bilingual(lang, "添加一行", "Add row")}
                  </button>
                </div>
              </div>

              <div className="trail-update-entry-editor">
                <div className="trail-update-entry-list" id="trailUpdateIssueEntries" aria-live="polite">
                  {directRows.map((row) => (
                    <div className="trail-update-entry-row" key={row.uid}>
                      <label>
                        <span>{bilingual(lang, "Issue ID（可多个）", "Issue IDs (multiple)")}</span>
                        <textarea
                          rows={2}
                          inputMode="text"
                          autoComplete="off"
                          spellCheck={false}
                          placeholder="cn32171803, cn31994663"
                          value={row.issue_id}
                          onChange={(e) => {
                            const val = e.target.value;
                            setDirectRows((prev) =>
                              prev.map((r) =>
                                r.uid === row.uid ? { ...r, issue_id: val, source: null } : r,
                              ),
                            );
                            setDirectPreview(null);
                          }}
                        />
                      </label>
                      <label>
                        <span>
                          {bilingual(
                            lang,
                            "排除说明（可选，写入 info）",
                            "Exclusion note (optional; saved in info)",
                          )}
                        </span>
                        <textarea
                          rows={2}
                          placeholder={bilingual(
                            lang,
                            "留空时使用默认说明；提交后写入 info.ra_triage_dashboard.should_exclude_comment。",
                            "Default note if empty; saved to info.ra_triage_dashboard.should_exclude_comment.",
                          )}
                          value={row.comment}
                          onChange={(e) => {
                            const val = e.target.value;
                            setDirectRows((prev) =>
                              prev.map((r) =>
                                r.uid === row.uid ? { ...r, comment: val, source: null } : r,
                              ),
                            );
                            setDirectPreview(null);
                          }}
                        />
                      </label>
                      <button
                        className="button button-quiet trail-update-entry-remove"
                        type="button"
                        aria-label={bilingual(lang, "删除此行", "Remove row")}
                        disabled={directRows.length <= 1}
                        onClick={() => {
                          setDirectRows((prev) => prev.filter((r) => r.uid !== row.uid));
                          setDirectPreview(null);
                        }}
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              </div>

              <div className="trail-update-direct-footer">
                <div
                  id="trailUpdateIssueIdsFeedback"
                  className={`trail-update-direct-feedback${
                    parsedDirect.invalid.length
                      ? " is-error"
                      : parsedDirect.ids.length
                        ? " is-ready"
                        : ""
                  }`}
                  role="status"
                  aria-live="polite"
                >
                  {parsedDirect.invalid.length
                    ? bilingual(
                        lang,
                        `已识别 ${parsedDirect.ids.length} 个 Issue；请修正：${parsedDirect.invalid
                          .slice(0, 4)
                          .join("、")}`,
                        `${parsedDirect.ids.length} Issues recognized; fix: ${parsedDirect.invalid
                          .slice(0, 4)
                          .join(", ")}`,
                      )
                    : parsedDirect.ids.length
                      ? bilingual(
                          lang,
                          `已识别 ${parsedDirect.ids.length} 个 Issue（每行可填多个，可分别填写说明）`,
                          `${parsedDirect.ids.length} Issues recognized`,
                        )
                      : bilingual(lang, "请输入 Issue ID", "Enter at least one Issue ID")}
                </div>
                <div className="page-actions trail-update-actions">
                  <button
                    className="button button-primary"
                    id="trailUpdateIssuePreviewButton"
                    type="button"
                    disabled={directBusy}
                    onClick={() => void handleDirectPreview()}
                  >
                    {bilingual(lang, "生成屏蔽预览", "Build shield preview")}
                  </button>
                  <button
                    className="button button-primary"
                    id="trailUpdateIssueCommitButton"
                    type="button"
                    disabled={directBusy || !writeReady(directPreview)}
                    onClick={handleDirectCommit}
                  >
                    {bilingual(lang, "提交屏蔽到 Trail", "Commit shield to Trail")}
                  </button>
                </div>
              </div>

              {directStatus ? (
                <div className="trail-update-status" id="trailUpdateIssueStatus" role="status">
                  {directStatus}
                </div>
              ) : null}
            </section>
          </section>
        ) : null}
      </section>

      {statusBanner ? (
        <div className="trail-update-status" id="trailUpdateStatus" role="status">
          {statusBanner}
        </div>
      ) : null}

      {historyOpLink ? (
        <a
          className="button button-secondary trail-update-history-link"
          href={`${withWorkbenchBase("/trail-update-history")}?operation=${encodeURIComponent(
            historyOpLink,
          )}`}
        >
          {bilingual(lang, "查看本次更新记录", "View this update record")}
        </a>
      ) : null}

      {tab === "review" ? (
        <section
          className="trail-update-tab-panel trail-update-results-panel"
          id="trailUpdateReviewPanel"
          role="tabpanel"
          aria-labelledby="trailUpdateReviewTab"
        >
          {previewQuery.isLoading && !data ? (
            <div className="trail-update-initial-loading" id="trailUpdateLoading" role="status">
              <span>{bilingual(lang, "正在加载本地候选…", "Loading local candidates…")}</span>
              <div aria-hidden="true">
                <i />
                <i />
                <i />
              </div>
            </div>
          ) : (
            <section
              className="trail-update-results"
              id="trailUpdateResults"
              aria-label={bilingual(lang, "Trail 更新结果", "Trail update results")}
            >
              {data?.reconciliation ? (
                <p className="trail-reconcile-coverage" id="trailReconcileCoverage" role="status">
                  {[
                    bilingual(
                      lang,
                      `数据集 ${(data.baselines || []).join(", ") || baselinesParam} · 本地候选 ${
                        data.local_candidate_count ?? allItems.filter((i) => !i.readonly).length
                      }`,
                      `Datasets ${(data.baselines || []).join(", ") || baselinesParam} · ${
                        data.local_candidate_count ?? allItems.filter((i) => !i.readonly).length
                      } local candidates`,
                    ),
                    bilingual(
                      lang,
                      `已确认 ${allItems.filter((i) => remoteState(i) !== "unknown").length} / 共 ${
                        allItems.length
                      } · 最近核验 ${data.checked_at ? formatCstTime(data.checked_at, lang) : "尚未完成"}`,
                      `Confirmed ${allItems.filter((i) => remoteState(i) !== "unknown").length} / total ${
                        allItems.length
                      } · checked ${data.checked_at ? formatCstTime(data.checked_at, lang) : "pending"}`,
                    ),
                  ].join("\n")}
                </p>
              ) : null}

              <section
                className="trail-update-summary-grid trail-update-review-summary-grid"
                aria-label={bilingual(lang, "Trail 更新汇总", "Trail update summary")}
              >
                <article className="analysis-stat-card">
                  <span>{bilingual(lang, "本地候选", "Local candidates")}</span>
                  <strong id="trailUpdateCount">
                    {data
                      ? String(
                          data.local_candidate_count ??
                            allItems.filter((it) => !it.readonly).length,
                        )
                      : "—"}
                  </strong>
                  <small id="trailUpdateScopeSummary">{data ? scopeSummaryText : "—"}</small>
                </article>

                <article
                  className="page-card analysis-review-status-card trail-update-status-card"
                  aria-labelledby="trailUpdateStatusTitle"
                >
                  <div className="section-heading analysis-review-status-heading trail-update-status-heading">
                    <div>
                      <h3 id="trailUpdateStatusTitle">
                        {bilingual(lang, "Trail 更新状态", "Trail update status")}
                      </h3>
                    </div>
                    <small id="trailUpdateFilterHelp">
                      {bilingual(
                        lang,
                        "点选状态筛选 · 随其他条件统计",
                        "Click to filter · Counts follow other filters",
                      )}
                    </small>
                  </div>
                  <div
                    className="analysis-review-status-chart analysis-review-status-visual trail-update-status-chart trail-update-status-visual trail-update-status-summary"
                    id="trailUpdateStatusSummary"
                    role="group"
                    aria-live="polite"
                  >
                    <div className="analysis-review-status-bar" role="img">
                      {statusEntries.map(([key, count]) => {
                        const meta = trailStatusMeta(key, lang);
                        const pct = statusTotal
                          ? Math.round((count / statusTotal) * 1000) / 10
                          : 100;
                        return (
                          <span
                            key={key}
                            className={`analysis-review-status-segment trail-status-${meta.key}`}
                            style={{ width: `${pct}%` }}
                            title={`${meta.label} · ${count} · ${pct}%`}
                          />
                        );
                      })}
                    </div>
                    <div className="analysis-review-status-legend" role="list">
                      {statusEntries.map(([key, count]) => {
                        const meta = trailStatusMeta(key, lang);
                        const pct = statusTotal
                          ? Math.round((count / statusTotal) * 1000) / 10
                          : 0;
                        const activeBtn = statusFilter.includes(meta.key);
                        return (
                          <div role="listitem" key={key}>
                            <button
                              type="button"
                              className={`analysis-review-status-legend-item trail-status-${meta.key}`}
                              aria-pressed={activeBtn}
                              disabled={!count}
                              title={meta.detail}
                              onClick={() => {
                                setStatusFilter((prev) =>
                                  prev.length === 1 && prev[0] === meta.key ? [] : [meta.key],
                                );
                                setPage(1);
                              }}
                            >
                              <span className="analysis-review-status-swatch" />
                              <span className="analysis-review-status-legend-copy">
                                <strong>{meta.label}</strong>
                                <small>
                                  {count} · {pct}%
                                </small>
                              </span>
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </article>
              </section>

              <section className="page-card trail-update-table-card">
                <form
                  className="trail-update-filters"
                  id="trailUpdateFilterForm"
                  aria-label={bilingual(lang, "排除案例筛选", "Excluded cases filters")}
                  onSubmit={(e) => {
                    e.preventDefault();
                    setSearch(searchInput);
                    setPage(1);
                  }}
                >
                  <div className="trail-reconcile-controls">
                    <div className="ra-tu-field">
                      <span>{bilingual(lang, "视图", "View")}</span>
                      <UiSelect
                        id="trailReconcileView"
                        value={view}
                        options={viewOptions}
                        ariaLabel={bilingual(lang, "视图", "View")}
                        onChange={(v) => {
                          setView(v === "reconciliation" ? "reconciliation" : "local");
                          setPage(1);
                        }}
                      />
                    </div>
                  </div>

                  <label className="trail-update-search-filter">
                    <span>{bilingual(lang, "检索", "Search")}</span>
                    <input
                      id="trailUpdateSearchInput"
                      type="search"
                      autoComplete="off"
                      value={searchInput}
                      placeholder={bilingual(lang, "Issue ID、理由或作者", "Issue ID, reason or author")}
                      onChange={(e) => setSearchInput(e.target.value)}
                    />
                  </label>

                  <div className="ra-tu-field">
                    <span>{bilingual(lang, "Trail 更新状态", "Trail update status")}</span>
                    <MultiSelect
                      id="trailUpdateStatusFilter"
                      options={statusOptions}
                      values={statusFilter}
                      ariaLabel={bilingual(lang, "Trail 更新状态", "Trail update status")}
                      placeholder={bilingual(lang, "全部 Trail 状态", "All Trail statuses")}
                      allLabel={bilingual(lang, "全部 Trail 状态", "All Trail statuses")}
                      lang={lang}
                      onChange={(vals) => {
                        setStatusFilter(vals);
                        setPage(1);
                      }}
                    />
                  </div>

                  <div className="trail-update-filter-actions">
                    <button
                      className="button button-quiet"
                      id="trailUpdateResetFiltersButton"
                      type="button"
                      onClick={() => {
                        setSearchInput("");
                        setSearch("");
                        setSourceKind("");
                        setLocalStateFilter("");
                        setRemoteStateFilter("");
                        setGtFilter([]);
                        setReviewerFilter([]);
                        setStatusFilter([]);
                        setPage(1);
                      }}
                    >
                      {bilingual(lang, "重置筛选", "Reset filters")}
                    </button>
                  </div>

                  <details className="trail-reconcile-advanced">
                    <summary id="trailAdvancedFilterLabel">
                      {bilingual(
                        lang,
                        `更多筛选${advancedCount ? ` · ${advancedCount}` : ""}`,
                        `More filters${advancedCount ? ` · ${advancedCount}` : ""}`,
                      )}
                    </summary>
                    <div className="trail-advanced-fields">
                      <div className="ra-tu-field">
                        <span>{bilingual(lang, "记录来源", "Record source")}</span>
                        <UiSelect
                          id="trailReconcileSource"
                          value={sourceKind}
                          options={sourceKindOptions}
                          ariaLabel={bilingual(lang, "记录来源", "Record source")}
                          onChange={(v) => {
                            setSourceKind(v);
                            setPage(1);
                          }}
                        />
                      </div>
                      <div className="ra-tu-field">
                        <span>{bilingual(lang, "本地排除结论", "Local exclusion outcome")}</span>
                        <UiSelect
                          id="trailReconcileLocal"
                          value={localStateFilter}
                          options={localStateOptions}
                          ariaLabel={bilingual(lang, "本地排除结论", "Local exclusion outcome")}
                          onChange={(v) => {
                            setLocalStateFilter(v);
                            setPage(1);
                          }}
                        />
                      </div>
                      <div className="ra-tu-field">
                        <span>{bilingual(lang, "Trail 排除", "Trail exclusion")}</span>
                        <UiSelect
                          id="trailReconcileRemote"
                          value={remoteStateFilter}
                          options={remoteStateOptions}
                          ariaLabel={bilingual(lang, "Trail 排除", "Trail exclusion")}
                          onChange={(v) => {
                            setRemoteStateFilter(v);
                            setPage(1);
                          }}
                        />
                      </div>
                      <div className="ra-tu-field">
                        <span>GT</span>
                        <MultiSelect
                          id="trailUpdateGtFilter"
                          options={gtOptions}
                          values={gtFilter}
                          ariaLabel="GT"
                          placeholder={bilingual(lang, "全部 GT", "All GT")}
                          allLabel={bilingual(lang, "全部 GT", "All GT")}
                          lang={lang}
                          onChange={(vals) => {
                            setGtFilter(vals);
                            setPage(1);
                          }}
                        />
                      </div>
                      <div className="ra-tu-field">
                        <span>{bilingual(lang, "理由作者", "Reason author")}</span>
                        <MultiSelect
                          id="trailUpdateReviewerFilter"
                          options={reviewerOptions}
                          values={reviewerFilter}
                          ariaLabel={bilingual(lang, "理由作者", "Reason author")}
                          placeholder={bilingual(lang, "全部作者", "All authors")}
                          allLabel={bilingual(lang, "全部作者", "All authors")}
                          lang={lang}
                          onChange={(vals) => {
                            setReviewerFilter(vals);
                            setPage(1);
                          }}
                        />
                      </div>
                    </div>
                  </details>
                </form>

                <div className="section-heading trail-update-results-heading">
                  <div>
                    <h3>{bilingual(lang, "排除候选明细", "Excluded case details")}</h3>
                    <small
                      id="trailUpdateResultSummary"
                      className="trail-update-result-summary"
                      aria-live="polite"
                    >
                      {filteredItems.length
                        ? bilingual(
                            lang,
                            `当前显示 ${pageStart + 1}–${Math.min(
                              pageStart + pageSize,
                              filteredItems.length,
                            )} / 筛选结果 ${filteredItems.length} 条`,
                            `Showing ${pageStart + 1}–${Math.min(
                              pageStart + pageSize,
                              filteredItems.length,
                            )} of ${filteredItems.length} matches`,
                          )
                        : bilingual(
                            lang,
                            "当前筛选没有匹配案例",
                            "No cases match the current filters",
                          )}
                    </small>
                  </div>
                  <div className="trail-update-result-actions">
                    <button
                      className="button button-quiet"
                      id="trailLocalImportOpen"
                      type="button"
                      aria-haspopup="dialog"
                      disabled={!canWrite || selectionBusy}
                      onClick={() => {
                        setLocalImportOpen(true);
                        setLocalImportPreview(null);
                        setLocalImportFeedback({ text: "" });
                        void scanLocalImport(false);
                      }}
                    >
                      {bilingual(lang, "从 Trail 导入", "Import from Trail")}
                    </button>
                    <button
                      className="button button-quiet"
                      id="trailNonExclusionOpen"
                      type="button"
                      aria-haspopup="dialog"
                      disabled={!canWrite || selectionBusy}
                      onClick={() => {
                        setNonExclError("");
                        setNonExclOpen(true);
                      }}
                    >
                      {bilingual(lang, "同步不排除", "Sync non-exclusion")}
                    </button>
                    {view !== "reconciliation" ? (
                      <button
                        className="button button-quiet"
                        id="trailReasonBatchToggle"
                        type="button"
                        aria-expanded={selectionMode}
                        disabled={selectionBusy}
                        onClick={() => {
                          setSelectionMode((prev) => {
                            if (prev) setSelectedIssues(new Set());
                            return !prev;
                          });
                        }}
                      >
                        {selectionMode
                          ? bilingual(lang, "完成选择", "Done selecting")
                          : bilingual(lang, "批量更新", "Batch update")}
                      </button>
                    ) : null}
                    <button
                      className="button button-quiet"
                      type="button"
                      disabled={!data?.draft}
                      onClick={() => openJsonDraft("review")}
                    >
                      {bilingual(lang, "预览 JSON", "Preview JSON")}
                    </button>
                  </div>
                </div>

                {selectionMode && view !== "reconciliation" ? (
                  <div className="trail-reason-selection-bar">
                    <div className="ra-tu-inline-field">
                      <span>{bilingual(lang, "更新类型", "Update type")}</span>
                      <UiSelect
                        id="trailReasonIntent"
                        value={selectionIntent}
                        options={intentOptions}
                        disabled={selectionBusy}
                        ariaLabel={bilingual(lang, "更新类型", "Update type")}
                        onChange={(v) => {
                          setSelectionIntent(v === "exclude" ? "exclude" : "reason_only");
                          setSelectedIssues(new Set());
                        }}
                      />
                    </div>
                    <button
                      className="button button-quiet"
                      id="trailReasonSelectVisible"
                      type="button"
                      disabled={selectionBusy || !pageEligibleIds.length}
                      onClick={() => {
                        setSelectedIssues((prev) => {
                          const next = new Set(prev);
                          pageEligibleIds.forEach((id) => next.add(id));
                          return next;
                        });
                      }}
                    >
                      {bilingual(
                        lang,
                        `选择本页可更新项（${pageEligibleIds.length}）`,
                        `Select eligible on page (${pageEligibleIds.length})`,
                      )}
                    </button>
                    <button
                      className="button button-quiet"
                      id="trailReasonClear"
                      type="button"
                      disabled={!selectedIssues.size || selectionBusy}
                      onClick={() => setSelectedIssues(new Set())}
                    >
                      {bilingual(lang, "清空选择", "Clear selection")}
                    </button>
                    <button
                      className="button button-primary"
                      id="trailUpdateCommitButton"
                      type="button"
                      disabled={selectionBusy || !selectionReady}
                      onClick={() => void handleBatchSelectionCommit()}
                    >
                      {bilingual(lang, "预览所选更新", "Preview selected updates")}
                    </button>
                    <small id="trailReasonSelectionCount" role="status">
                      {bilingual(
                        lang,
                        `已选 ${selectedIssues.size} 条`,
                        `${selectedIssues.size} selected`,
                      )}
                    </small>
                  </div>
                ) : null}

                <div className="trail-update-table-wrap">
                  <table className="trail-update-table trail-reconcile-table">
                    <thead>
                      <tr>
                        <th>Issue</th>
                        <th>{bilingual(lang, "来源", "Source")}</th>
                        <th>{bilingual(lang, "本地状态", "Local state")}</th>
                        <th>{bilingual(lang, "Trail 状态", "Trail state")}</th>
                        <th>{bilingual(lang, "理由摘要", "Reasons")}</th>
                        <th>{bilingual(lang, "操作", "Actions")}</th>
                      </tr>
                    </thead>
                    <tbody id="trailUpdateTableBody">
                      {!allItems.length ? (
                        <tr>
                          <td colSpan={6} className="trail-update-empty">
                            {bilingual(
                              lang,
                              "当前数据集没有已标记排除的 Issue。",
                              "No Issues marked for exclusion in the selected datasets.",
                            )}
                          </td>
                        </tr>
                      ) : !pageItems.length ? (
                        <tr>
                          <td colSpan={6} className="trail-update-empty">
                            {bilingual(
                              lang,
                              "当前筛选没有匹配的排除案例。",
                              "No excluded cases match the current filters.",
                            )}
                          </td>
                        </tr>
                      ) : (
                        pageItems.map((item) => {
                          const key = rowKey(item);
                          const st = trailStatusMeta(reasonState(item), lang);
                          const eligible = isEligible(item);
                          const remoteText =
                            remoteState(item) === "unknown"
                              ? bilingual(lang, "尚未确认", "Unconfirmed")
                              : item.trail_detail?.trail_comment ||
                                bilingual(lang, "理由未填写", "No reason provided");
                          const localText =
                            item.trail_detail?.local_comment ||
                            item.comment ||
                            (reasonState(item) === "excluded_no_reason"
                              ? bilingual(lang, "理由未填写", "No reason provided")
                              : bilingual(lang, "理由待补充", "Reason needed"));
                          const srcMap: Record<string, [string, string]> = {
                            local: ["本地候选", "Local candidate"],
                            historical: ["历史排除", "Historical exclusion"],
                            both: ["两者都有", "Both"],
                          };
                          const srcPair = srcMap[item.source_kind || "local"];
                          const locMap: Record<string, [string, string]> = {
                            true: ["已勾选排除", "Exclusion selected"],
                            false: ["本地未勾选", "Not selected locally"],
                            unknown: ["本地状态未知", "Local state unknown"],
                          };
                          const locPair = locMap[localState(item)];

                          return (
                            <tr key={key} data-trail-reason-row={key}>
                              <td data-label="Issue">
                                <div className="trail-issue-identity">
                                  {selectionMode && !item.readonly && view !== "reconciliation" ? (
                                    <label
                                      className="trail-reason-check"
                                      title={
                                        eligible
                                          ? bilingual(lang, "可加入本次更新", "Eligible for update")
                                          : st.detail
                                      }
                                    >
                                      <input
                                        type="checkbox"
                                        checked={selectedIssues.has(item.issue_id)}
                                        disabled={!eligible}
                                        aria-label={bilingual(
                                          lang,
                                          `选择 ${item.issue_id}`,
                                          `Select ${item.issue_id}`,
                                        )}
                                        onChange={(e) => {
                                          setSelectedIssues((prev) => {
                                            const next = new Set(prev);
                                            if (e.target.checked) next.add(item.issue_id);
                                            else next.delete(item.issue_id);
                                            return next;
                                          });
                                        }}
                                      />
                                    </label>
                                  ) : null}
                                  <div>
                                    <strong className="trail-update-issue">{item.issue_id}</strong>
                                    {item.baseline_id ? <small>{item.baseline_id}</small> : null}
                                  </div>
                                </div>
                              </td>
                              <td data-label={bilingual(lang, "来源", "Source")}>
                                {srcPair
                                  ? bilingual(lang, srcPair[0], srcPair[1])
                                  : item.source_kind || "local"}
                              </td>
                              <td data-label={bilingual(lang, "本地状态", "Local state")}>
                                {bilingual(lang, locPair[0], locPair[1])}
                              </td>
                              <td data-label={bilingual(lang, "Trail 状态", "Trail state")}>
                                <span
                                  className={`trail-update-state-badge ${st.className}`}
                                  title={st.detail}
                                >
                                  {st.label}
                                </span>
                              </td>
                              <td data-label={bilingual(lang, "理由摘要", "Reasons")}>
                                <div className="trail-reason-summary">
                                  <p title={remoteText}>
                                    <span>Trail</span>
                                    {remoteText}
                                  </p>
                                  <p title={localText}>
                                    <span>{bilingual(lang, "本地", "Local")}</span>
                                    {localText}
                                  </p>
                                </div>
                              </td>
                              <td data-label={bilingual(lang, "操作", "Actions")}>
                                <div className="trail-row-actions">
                                  <button
                                    className="text-link trail-reason-toggle"
                                    type="button"
                                    aria-haspopup="dialog"
                                    onClick={() => setReasonDetailItem(item)}
                                  >
                                    {bilingual(lang, "详情", "Details")}
                                  </button>
                                  <button
                                    className="analysis-discussion-link trail-update-discussion-link"
                                    type="button"
                                    onClick={() => {
                                      getLegacyWindow()
                                        .openAnalysisDiscussion?.(item.issue_id, {
                                          runId:
                                            item.review?.model_run_id || item.model?.run_id || "",
                                          source: "trail-update",
                                        })
                                        ?.catch((err: Error) =>
                                          getLegacyWindow().showToast?.(err.message, true),
                                        );
                                    }}
                                  >
                                    {bilingual(lang, "评论", "Discuss")}
                                  </button>
                                </div>
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>

                {filteredItems.length > 0 ? (
                  <Pagination
                    page={safePage}
                    pageSize={pageSize}
                    total={filteredItems.length}
                    lang={lang}
                    className="case-pagination gallery-pagination trail-update-pagination"
                    showPageUnit
                    disableJumpWhenSinglePage
                    labelText={`${safePage} / ${totalPages}`}
                    ariaLabel={bilingual(lang, "排除候选分页", "Excluded cases pagination")}
                    onPageChange={setPage}
                    onPageSizeChange={(nextSize) => {
                      setPageSize(nextSize);
                      setPage(1);
                    }}
                  />
                ) : null}
              </section>
            </section>
          )}
        </section>
      ) : (
        <section
          className="trail-update-tab-panel trail-update-results-panel"
          id="trailUpdateIssuePanel"
          role="tabpanel"
          aria-labelledby="trailUpdateIssueTab"
        >
          <section
            className="trail-update-direct-results"
            id="trailUpdateIssueResults"
            aria-label={bilingual(lang, "Issue 屏蔽预览", "Issue shielding preview")}
          >
            <section
              className="trail-update-summary-grid trail-update-issue-summary-grid"
              aria-label={bilingual(lang, "Issue 屏蔽摘要", "Issue shielding summary")}
            >
              <article className="analysis-stat-card">
                <span>{bilingual(lang, "可写 Issue", "Writable Issues")}</span>
                <strong id="trailUpdateIssueCount">
                  {directPreview ? (directPreview.items || []).length : "—"}
                </strong>
                <small id="trailUpdateIssueSummary">
                  {directPreview
                    ? bilingual(
                        lang,
                        `${directPreview.requested_issue_ids?.length || 0} 条请求；${
                          (directPreview.items || []).length
                        } 条可写`,
                        `${directPreview.requested_issue_ids?.length || 0} requested; ${
                          (directPreview.items || []).length
                        } writable`,
                      )
                    : "—"}
                </small>
              </article>
              <article className="analysis-stat-card">
                <span>{bilingual(lang, "未找到", "Missing")}</span>
                <strong id="trailUpdateIssueMissingCount">
                  {directPreview
                    ? (directPreview.missing_issue_ids || []).length +
                      (directPreview.invalid_issue_ids || []).length
                    : "—"}
                </strong>
                <small>Trail view 2410</small>
              </article>
              <article className="analysis-stat-card trail-update-field-stat-card">
                <span>{bilingual(lang, "目标字段", "Target field")}</span>
                <strong
                  id="trailUpdateIssueField"
                  className="trail-update-target-value"
                  title={
                    directPreview
                      ? targetSpec(directPreview).fullPath
                      : "ra_stuck_auto_result_info.ra_triage_dashboard.should_exclude"
                  }
                >
                  {directPreview
                    ? targetSpec(directPreview).fullPath
                    : "ra_stuck_auto_result_info.ra_triage_dashboard.should_exclude"}
                </strong>
              </article>
            </section>

            <section className="page-card trail-update-table-card">
              <div className="section-heading trail-update-results-heading">
                <div>
                  <h3>{bilingual(lang, "预计改动（仅写 info）", "Expected changes (info only)")}</h3>
                </div>
                <div className="trail-update-result-actions">
                  <button
                    className="button button-quiet"
                    type="button"
                    disabled={!directPreview?.draft}
                    onClick={() => openJsonDraft("issue")}
                  >
                    {bilingual(lang, "预览 JSON", "Preview JSON")}
                  </button>
                </div>
              </div>
              <div className="trail-update-table-wrap">
                <table className="trail-update-table trail-update-direct-table">
                  <thead>
                    <tr>
                      <th>Issue</th>
                      <th>{bilingual(lang, "数据集版本", "Dataset")}</th>
                      <th>{bilingual(lang, "当前模型 label（不改）", "Model label (unchanged)")}</th>
                      <th>{bilingual(lang, "当前屏蔽状态", "Current shield")}</th>
                      <th>{bilingual(lang, "预计写入 info", "Planned info write")}</th>
                      <th>{bilingual(lang, "排除说明", "Exclusion note")}</th>
                    </tr>
                  </thead>
                  <tbody id="trailUpdateIssueTableBody">
                    {!directPreview || !(directPreview.items || []).length ? (
                      <tr>
                        <td colSpan={6} className="trail-update-empty">
                          {bilingual(
                            lang,
                            "生成预览后显示 Issue。",
                            "Issues appear after building a preview.",
                          )}
                        </td>
                      </tr>
                    ) : (
                      (directPreview.items || []).map((item) => {
                        const patchPath = item.target?.path || "ra_triage_dashboard.should_exclude";
                        const shortPath = patchPath.split(".").filter(Boolean).pop() || patchPath;
                        const commentPatch =
                          item.target?.patch?.ra_triage_dashboard?.should_exclude_comment || "";
                        const infoPreview = [
                          `${shortPath} = true`,
                          commentPatch ? `should_exclude_comment = ${commentPatch}` : "",
                        ]
                          .filter(Boolean)
                          .join("; ");
                        return (
                          <tr key={item.issue_id}>
                            <td data-label="Issue">
                              <strong className="trail-update-issue">{item.issue_id}</strong>
                            </td>
                            <td data-label="数据集版本" className="trail-update-release-cell">
                              <strong>{item.baseline_id || item.baseline_scope || "—"}</strong>
                            </td>
                            <td data-label="当前模型 label">
                              {item.current_label ? (
                                <span className={`label-badge label-${item.current_label}`}>
                                  {item.current_label}
                                </span>
                              ) : (
                                <span className="muted">
                                  {bilingual(lang, "未输出", "No output")}
                                </span>
                              )}
                            </td>
                            <td data-label="当前屏蔽状态">
                              <span
                                className={`trail-update-state-badge${
                                  item.current_should_exclude ? " is-on" : ""
                                }`}
                              >
                                {item.current_should_exclude
                                  ? bilingual(lang, "已屏蔽", "Shielded")
                                  : bilingual(lang, "未屏蔽", "Not shielded")}
                              </span>
                            </td>
                            <td data-label="预计写入 info" className="trail-update-info-cell">
                              <strong>{shortPath}</strong>
                              <small>{bilingual(lang, "info-only · label 不变", "info-only · label unchanged")}</small>
                              <code>{infoPreview}</code>
                            </td>
                            <td data-label="Comment">
                              <div className="trail-update-comment">{item.comment || "—"}</div>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </section>

          <section
            className="page-card trail-update-history-card"
            id="trailUpdateIssueHistory"
            aria-label={bilingual(lang, "Issue ID 屏蔽上传历史", "Issue shielding upload history")}
          >
            <div className="section-heading trail-update-history-heading">
              <div>
                <h3>{bilingual(lang, "Issue ID 屏蔽上传历史", "Issue shielding upload history")}</h3>
                <small>
                  {bilingual(
                    lang,
                    "按批次记录提交人、状态和每个 Issue 的说明",
                    "Batches, actors, statuses, and per-Issue notes",
                  )}
                </small>
              </div>
              <button
                className="button button-quiet"
                id="trailUpdateIssueHistoryRefresh"
                type="button"
                onClick={() => void queryClient.invalidateQueries({ queryKey: ["trail-issue-history"] })}
              >
                {bilingual(lang, "刷新历史", "Refresh history")}
              </button>
            </div>
            <div className="trail-update-history-list" id="trailUpdateIssueHistoryList">
              {issueHistoryQuery.isLoading ? (
                <div className="trail-update-history-empty">
                  {bilingual(lang, "正在加载屏蔽历史…", "Loading shielding history…")}
                </div>
              ) : !(issueHistoryQuery.data?.items || []).length ? (
                <div className="trail-update-history-empty">
                  {bilingual(lang, "暂无 Issue ID 屏蔽上传记录。", "No Issue shielding uploads yet.")}
                </div>
              ) : (
                (issueHistoryQuery.data?.items || []).map((batch, idx) => {
                  const meta = historyStatusMeta(batch.status, lang);
                  const entries = batch.entries || [];
                  const total = Number(batch.requested_count || entries.length || 0);
                  const synced = Number(batch.synced_count || 0);
                  const failed = Number(batch.failed_count || 0);
                  return (
                    <details className="trail-update-history-item" key={batch.operation_id || idx}>
                      <summary>
                        <div className="trail-update-history-summary-main">
                          <span className={`trail-update-history-status ${meta.className}`}>
                            {meta.label}
                          </span>
                          <strong>
                            {total} {bilingual(lang, "个 Issue", "Issues")}
                          </strong>
                          <small>
                            {formatCstTime(batch.created_at, lang)} ·{" "}
                            {batch.actor || bilingual(lang, "未记录", "Unknown")}
                          </small>
                        </div>
                        <div className="trail-update-history-summary-count">
                          <strong>
                            {synced}/{total}
                          </strong>
                          <small>
                            {failed
                              ? `${failed} ${bilingual(lang, "失败", "failed")}`
                              : bilingual(lang, "全部回读成功", "readback complete")}
                          </small>
                        </div>
                      </summary>
                      <div className="trail-update-history-details">
                        <div className="trail-update-history-operation">
                          <span>
                            {batch.message ||
                              bilingual(lang, "Issue 屏蔽提交记录。", "Issue shielding submission.")}
                          </span>
                          <code title={batch.operation_id || ""}>
                            {batch.operation_id ? `${batch.operation_id.slice(0, 12)}…` : "—"}
                          </code>
                        </div>
                        <div className="trail-update-history-table-wrap">
                          <table>
                            <thead>
                              <tr>
                                <th>Issue</th>
                                <th>{bilingual(lang, "排除说明", "Exclusion note")}</th>
                                <th>{bilingual(lang, "结果", "Result")}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {entries.map((entry, i) => {
                                const em = historyStatusMeta(entry.status, lang);
                                return (
                                  <tr key={`${entry.issue_id}-${i}`}>
                                    <td data-label="Issue">
                                      <strong>{entry.issue_id || "—"}</strong>
                                    </td>
                                    <td data-label="排除说明">
                                      <div className="trail-update-history-comment">
                                        {entry.comment || "—"}
                                      </div>
                                    </td>
                                    <td data-label="结果">
                                      <span
                                        className={`trail-update-history-entry-status ${em.className}`}
                                      >
                                        {em.label}
                                      </span>
                                      {entry.detail ? <small>{entry.detail}</small> : null}
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </details>
                  );
                })
              )}
            </div>
          </section>
        </section>
      )}

      {/* Dialog 1: Reason Details */}
      {createPortal(
        <dialog
          ref={reasonDialogRef}
          id="raTrailReasonDetailsDialog"
          className="dialog case-label-decision-dialog"
          aria-labelledby="raTrailReasonDetailsTitle"
          onClose={() => setReasonDetailItem(null)}
        >
          {reasonDetailItem ? (
            <div className="dialog-card">
              <div className="dialog-heading">
                <div>
                  <small>{reasonDetailItem.issue_id}</small>
                  <h2 id="raTrailReasonDetailsTitle">
                    {bilingual(lang, "排除理由与来源", "Exclusion reasons and source")}
                  </h2>
                </div>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={bilingual(lang, "关闭", "Close")}
                  onClick={() => setReasonDetailItem(null)}
                >
                  ×
                </button>
              </div>
              <div className="case-label-decision-body">
                {(() => {
                  const stateKey = reasonState(reasonDetailItem);
                  const st = trailStatusMeta(stateKey, lang);
                  const detail = reasonDetailItem.trail_detail || {};
                  const src = reasonDetailItem.reason_source || {};
                  const remote = detail.trail_comment || "";
                  const local = String(detail.local_comment ?? reasonDetailItem.comment ?? "");
                  const known = ![
                    "querying",
                    "query_failed",
                    "not_checked",
                    "not_found",
                    "pending",
                  ].includes(stateKey);
                  const restored =
                    src.kind === "historical_restore" || src.kind === "legacy_exclusion_note";
                  const sourceLabel = reasonDetailItem.readonly
                    ? bilingual(lang, "无本地排除理由", "No local exclusion reason")
                    : src.kind === "legacy_exclusion_note"
                      ? bilingual(lang, "迁移前排除备注", "Original exclusion note")
                      : restored
                        ? bilingual(lang, "历史理由恢复", "Restored historical reason")
                        : src.kind === "trail_import"
                          ? bilingual(lang, "Trail 导入", "Imported from Trail")
                          : src.kind === "case_label"
                            ? bilingual(lang, "Issue 标注", "Issue annotation")
                            : bilingual(lang, "模型复核（旧记录）", "Model review (legacy)");
                  const originalTime = src.original_created_at || (!restored ? src.created_at : "");
                  const localMeta = [
                    sourceLabel,
                    src.author || bilingual(lang, "作者未知", "Unknown author"),
                    originalTime
                      ? formatCstTime(originalTime, lang)
                      : bilingual(lang, "原始时间未知", "Original time unknown"),
                    src.source_annotation_id
                      ? bilingual(
                          lang,
                          `原 Review #${src.source_annotation_id}`,
                          `Original Review #${src.source_annotation_id}`,
                        )
                      : "",
                    src.revision_id
                      ? bilingual(lang, `版本 #${src.revision_id}`, `Revision #${src.revision_id}`)
                      : "",
                    src.kind === "historical_restore" && src.created_at
                      ? bilingual(
                          lang,
                          `恢复时间 ${formatCstTime(src.created_at, lang)}`,
                          `Restored ${formatCstTime(src.created_at, lang)}`,
                        )
                      : "",
                  ]
                    .filter(Boolean)
                    .join(" · ");
                  const remoteHint = known
                    ? bilingual(lang, "Trail 未填写理由", "No reason in Trail")
                    : bilingual(lang, "尚未确认，请刷新查询", "Unconfirmed; refresh to check");
                  const localHint =
                    stateKey === "excluded_no_reason"
                      ? bilingual(lang, "两端均未填写理由，已同步", "Neither side has a reason; synced")
                      : bilingual(
                          lang,
                          "本地理由待补充；保留 Trail 原文",
                          "Local reason needed; the Trail text is preserved",
                        );
                  const rState = remoteState(reasonDetailItem);
                  const markerLabel =
                    rState === "true"
                      ? bilingual(lang, "Trail 已排除", "Excluded in Trail")
                      : rState === "false"
                        ? bilingual(lang, "Trail 未排除（false）", "Not excluded in Trail (false)")
                        : rState === "unset"
                          ? bilingual(lang, "Trail 排除标记未设置", "Trail exclusion is unset")
                          : bilingual(lang, "Trail 状态无法确认", "Trail state unconfirmed");
                  return (
                    <>
                      <span className={`trail-update-state-badge ${st.className}`} title={st.detail}>
                        {st.label}
                      </span>
                      <div className="trail-reason-comparison">
                        <section>
                          <strong>{bilingual(lang, "Trail 当前理由", "Current Trail reason")}</strong>
                          <p>{remote || remoteHint}</p>
                          <small>
                            {`${markerLabel} · ${bilingual(
                              lang,
                              "远端修改时间未知",
                              "Remote modification time unknown",
                            )}`}
                          </small>
                          {remote ? (
                            <button
                              type="button"
                              className="button button-quiet"
                              onClick={() =>
                                handleCopyText(remote, "已复制理由", "Reason copied")
                              }
                            >
                              {bilingual(lang, "复制", "Copy")}
                            </button>
                          ) : null}
                        </section>
                        <section>
                          <strong>{bilingual(lang, "本地最新理由", "Latest local reason")}</strong>
                          <p>{local || localHint}</p>
                          <small>{localMeta}</small>
                          {local ? (
                            <button
                              type="button"
                              className="button button-quiet"
                              onClick={() =>
                                handleCopyText(local, "已复制理由", "Reason copied")
                              }
                            >
                              {bilingual(lang, "复制", "Copy")}
                            </button>
                          ) : null}
                        </section>
                      </div>
                    </>
                  );
                })()}
              </div>
              <div className="dialog-actions">
                <button
                  type="button"
                  className="button button-quiet"
                  onClick={() => setReasonDetailItem(null)}
                >
                  {bilingual(lang, "关闭", "Close")}
                </button>
              </div>
            </div>
          ) : null}
        </dialog>,
        document.body,
      )}

      {/* Dialog 2: JSON Preview */}
      {createPortal(
        <dialog
          ref={jsonDialogRef}
          id="raTrailUpdateJsonDialog"
          className="dialog dialog-wide trail-update-json-dialog"
          aria-labelledby="raTrailUpdateJsonTitle"
          onClose={() => setJsonModal(null)}
        >
          {jsonModal ? (
            <div className="dialog-card">
              <div className="dialog-heading">
                <div>
                  <span className="eyebrow">JSON PREVIEW</span>
                  <h2 id="raTrailUpdateJsonTitle">{jsonModal.title}</h2>
                  <p className="dialog-copy">{jsonModal.subtitle}</p>
                </div>
                <button
                  className="icon-button"
                  type="button"
                  aria-label={bilingual(lang, "关闭", "Close")}
                  onClick={() => setJsonModal(null)}
                >
                  ×
                </button>
              </div>
              <pre className="trail-update-json-dialog-preview" tabIndex={0}>
                {jsonModal.text}
              </pre>
              <div className="dialog-actions trail-update-json-actions">
                <button
                  className="button button-quiet"
                  type="button"
                  onClick={() => setJsonModal(null)}
                >
                  {bilingual(lang, "关闭", "Close")}
                </button>
                <button
                  className="button button-quiet"
                  type="button"
                  onClick={() => handleCopyText(jsonModal.text, "已复制 JSON。", "JSON copied.")}
                >
                  {bilingual(lang, "复制 JSON", "Copy JSON")}
                </button>
                <button
                  className="button button-primary"
                  type="button"
                  onClick={() => {
                    const blob = new Blob([jsonModal.text], {
                      type: "application/json;charset=utf-8",
                    });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url;
                    a.download = jsonModal.filename;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  {bilingual(lang, "下载 JSON", "Download JSON")}
                </button>
              </div>
            </div>
          ) : null}
        </dialog>,
        document.body,
      )}

      {/* Dialog 3: Local Import (Trail -> Local) */}
      {createPortal(
        <dialog
          ref={localImportDialogRef}
          id="raTrailLocalImportDialog"
          className="dialog issue-query-dialog"
          aria-labelledby="raTrailLocalImportTitle"
          onClose={() => setLocalImportOpen(false)}
        >
          {localImportOpen ? (
            <div className="dialog-card">
              <div className="dialog-heading">
                <div>
                  <h2 id="raTrailLocalImportTitle">
                    {bilingual(lang, "从 Trail 导入", "Import from Trail")}
                  </h2>
                  <p className="dialog-copy">
                    {bilingual(
                      lang,
                      "采用 Trail 当前排除标记与理由，保存为我的新标注。保留历史；不修改 Trail、GT 或模型结果。已有裁决或理由冲突时需先人工核对。",
                      "Adopt the current Trail exclusion and reason as my new annotation. History is retained; Trail, GT and model results stay unchanged. Adjudications or conflicting reasons require manual review.",
                    )}
                  </p>
                </div>
                <button
                  className="icon-button"
                  type="button"
                  aria-label={bilingual(lang, "关闭", "Close")}
                  onClick={() => setLocalImportOpen(false)}
                >
                  ×
                </button>
              </div>
              <div className="trail-import-discovery-heading">
                <strong>
                  {bilingual(lang, "Trail 已排除 · 本地未排除", "Excluded in Trail · Not excluded locally")}
                </strong>
                <button
                  type="button"
                  className="button button-quiet"
                  disabled={
                    localImportScanState.loading || localImportScanState.scanning || localImportBusy
                  }
                  onClick={() => void scanLocalImport(true)}
                >
                  {bilingual(lang, "刷新差异", "Refresh differences")}
                </button>
              </div>
              <p className="dialog-copy" aria-live="polite">
                {[
                  localImportScanState.checkedAt
                    ? bilingual(
                        lang,
                        `上次扫描 ${formatCstTime(localImportScanState.checkedAt, lang)} · ${
                          localImportScanState.snapshotTotal
                        } 条`,
                        `Last scanned ${formatCstTime(localImportScanState.checkedAt, lang)} · ${
                          localImportScanState.snapshotTotal
                        } Issues`,
                      )
                    : "",
                  localImportScanState.scanning
                    ? bilingual(
                        lang,
                        `后台扫描 ${localImportScanState.scanned}/${
                          localImportScanState.total || "…"
                        }`,
                        `Background scan ${localImportScanState.scanned}/${
                          localImportScanState.total || "…"
                        }`,
                      )
                    : localImportScanState.loading
                      ? bilingual(lang, "正在读取已保存结果…", "Loading saved results…")
                      : "",
                  localImportScanState.done
                    ? bilingual(
                        lang,
                        `${localImportCandidates.length} 条差异 · 已选 ${localImportSelected.size} 条`,
                        `${localImportCandidates.length} differences · ${localImportSelected.size} selected`,
                      )
                    : "",
                  localImportScanState.error,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>

              {!localImportPreview ? (
                <>
                  <label className="trail-import-select-all">
                    <input
                      type="checkbox"
                      disabled={localImportBusy || !localImportEligible.length}
                      checked={
                        localImportEligible.length > 0 &&
                        localImportEligible
                          .slice(0, 200)
                          .every((it) => localImportSelected.has(it.issue_id))
                      }
                      onChange={(e) => {
                        setLocalImportSelected(
                          e.target.checked
                            ? new Set(localImportEligible.slice(0, 200).map((it) => it.issue_id))
                            : new Set(),
                        );
                      }}
                    />
                    <span>
                      {bilingual(lang, "选择可导入项（最多 200 条）", "Select importable items (up to 200)")}
                    </span>
                  </label>
                  <div className="trail-import-candidates">
                    {localImportCandidates.length ? (
                      localImportCandidates.map((it) => (
                        <label className="trail-import-candidate" key={it.issue_id}>
                          <input
                            type="checkbox"
                            disabled={!it.can_import || localImportBusy}
                            checked={localImportSelected.has(it.issue_id)}
                            onChange={(e) => {
                              setLocalImportSelected((prev) => {
                                const next = new Set(prev);
                                if (e.target.checked && next.size < 200) next.add(it.issue_id);
                                else next.delete(it.issue_id);
                                return next;
                              });
                            }}
                          />
                          <span>
                            <strong>{it.issue_id}</strong>
                            <small>
                              {it.local_excluded === false
                                ? bilingual(lang, "本地未排除", "Not excluded locally")
                                : bilingual(lang, "本地无排除结论", "No local exclusion outcome")}
                            </small>
                            <span className="trail-import-candidate-reason">
                              {it.remote_reason ||
                                bilingual(lang, "Trail 未填写理由", "No reason in Trail")}
                            </span>
                            {it.blocked_reason ? (
                              <small className="is-error">{it.blocked_reason}</small>
                            ) : null}
                          </span>
                        </label>
                      ))
                    ) : localImportScanState.done ? (
                      <p>{bilingual(lang, "未发现此类差异。", "No matching differences found.")}</p>
                    ) : null}
                  </div>
                </>
              ) : (
                <div id="trailLocalImportDiff">
                  {localImportPreview.items.map((it) => (
                    <article className="trail-selected-confirm" key={it.issue_id}>
                      <strong>{it.issue_id}</strong>
                      <div className="trail-reason-comparison">
                        <section>
                          <strong>{bilingual(lang, "本地原理由", "Previous local reason")}</strong>
                          <p>{it.before.rationale || bilingual(lang, "未填写", "Empty")}</p>
                        </section>
                        <section>
                          <strong>{bilingual(lang, "导入后理由", "Reason after import")}</strong>
                          <p>{it.after.rationale || bilingual(lang, "未填写", "Empty")}</p>
                        </section>
                      </div>
                    </article>
                  ))}
                </div>
              )}

              <details
                open={localImportManualOpen}
                onToggle={(e) => {
                  setLocalImportManualOpen((e.currentTarget as HTMLDetailsElement).open);
                  setLocalImportPreview(null);
                }}
              >
                <summary>{bilingual(lang, "或手动输入 Issue", "Or enter Issues manually")}</summary>
                <label className="issue-query-field">
                  <span>{bilingual(lang, "Issue 列表", "Issue list")}</span>
                  <textarea
                    rows={3}
                    placeholder="cn12345678, cn23456789"
                    value={localImportManualInput}
                    disabled={localImportBusy}
                    onChange={(e) => {
                      setLocalImportManualInput(e.target.value);
                      setLocalImportPreview(null);
                    }}
                  />
                </label>
              </details>

              {localImportFeedback.text ? (
                <div
                  className={`issue-query-feedback${localImportFeedback.error ? " is-error" : ""}`}
                >
                  {localImportFeedback.text}
                </div>
              ) : null}

              <div className="dialog-actions">
                <button
                  className="button button-quiet"
                  type="button"
                  onClick={() => setLocalImportOpen(false)}
                >
                  {bilingual(lang, "关闭", "Close")}
                </button>
                <button
                  className="button button-quiet"
                  type="button"
                  disabled={
                    localImportBusy ||
                    localImportScanState.loading ||
                    localImportScanState.scanning ||
                    localImportIdsCount === 0 ||
                    localImportIdsCount > 200
                  }
                  onClick={() => void runLocalImport(false)}
                >
                  {bilingual(lang, "预览导入", "Preview import")}
                </button>
                {localImportPreview ? (
                  <button
                    className="button button-primary"
                    type="button"
                    disabled={localImportBusy}
                    onClick={() => void runLocalImport(true)}
                  >
                    {bilingual(lang, "确认保存到本地", "Save locally")}
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}
        </dialog>,
        document.body,
      )}

      {/* Dialog 4: Sync Non-Exclusion */}
      {createPortal(
        <dialog
          ref={nonExclDialogRef}
          id="raTrailNonExclusionDialog"
          className="dialog issue-query-dialog"
          aria-labelledby="raTrailNonExclusionTitle"
          onClose={() => setNonExclOpen(false)}
        >
          {nonExclOpen ? (
            <div className="dialog-card">
              <div className="dialog-heading">
                <div>
                  <h2 id="raTrailNonExclusionTitle">
                    {bilingual(lang, "同步不排除", "Sync non-exclusion")}
                  </h2>
                  <p className="dialog-copy">
                    {bilingual(
                      lang,
                      "仅同步本地已明确为“不排除”的 Issue；待裁决或有排除意见的记录不能提交。Trail 原理由保留不变。",
                      "Sync only Issues with a confirmed local non-exclusion outcome. Original Trail reasons are preserved.",
                    )}
                  </p>
                </div>
                <button
                  className="icon-button"
                  type="button"
                  aria-label={bilingual(lang, "关闭", "Close")}
                  onClick={() => setNonExclOpen(false)}
                >
                  ×
                </button>
              </div>
              <label className="issue-query-field">
                <span>{bilingual(lang, "Issue 列表", "Issue list")}</span>
                <textarea
                  rows={5}
                  spellCheck={false}
                  autoComplete="off"
                  placeholder="cn12345678, cn23456789"
                  disabled={nonExclBusy}
                  value={nonExclInput}
                  onChange={(e) => {
                    setNonExclInput(e.target.value);
                    setNonExclError("");
                  }}
                />
              </label>
              <div
                className={`issue-query-feedback${
                  nonExclError || nonExclParsed.invalid.length || nonExclParsed.ids.length > 200
                    ? " is-error"
                    : ""
                }`}
              >
                {nonExclError ||
                  (nonExclBusy
                    ? bilingual(lang, "正在核验，请稍候…", "Checking; please wait…")
                    : !nonExclParsed.ids.length && !nonExclParsed.invalid.length
                      ? bilingual(
                          lang,
                          "填写 1–200 个 Issue，支持换行、逗号或 Issue 链接。",
                          "Enter 1–200 Issues, separated by lines, commas, or Issue links.",
                        )
                      : bilingual(
                          lang,
                          `已识别 ${nonExclParsed.ids.length} 个 Issue`,
                          `${nonExclParsed.ids.length} Issues recognized`,
                        ))}
              </div>
              <div className="dialog-actions">
                <button
                  className="button button-quiet"
                  type="button"
                  onClick={() => setNonExclOpen(false)}
                >
                  {bilingual(lang, "取消", "Cancel")}
                </button>
                <button
                  className="button button-primary"
                  type="button"
                  disabled={nonExclBusy || !canWrite || !nonExclValid}
                  onClick={() => void handleNonExclPreview()}
                >
                  {bilingual(lang, "预览改动", "Preview changes")}
                </button>
              </div>
            </div>
          ) : null}
        </dialog>,
        document.body,
      )}

      {/* Dialog 5: JSON / Excel Import */}
      {createPortal(
        <dialog
          ref={issueImportDialogRef}
          id="raTrailIssueImportDialog"
          className="dialog dialog-wide trail-update-json-import-dialog"
          onClose={() => setIssueImportMode(null)}
        >
          {issueImportMode ? (
            <div className="dialog-card">
              <div className="dialog-heading">
                <div>
                  <span className="eyebrow">
                    {issueImportMode === "excel" ? "IMPORT EXCEL" : "IMPORT JSON"}
                  </span>
                  <h2>
                    {issueImportMode === "excel"
                      ? bilingual(lang, "导入 Issue 屏蔽 Excel", "Import Issue shielding Excel")
                      : bilingual(lang, "导入 Issue 屏蔽 JSON", "Import Issue shielding JSON")}
                  </h2>
                  <p className="dialog-copy">
                    {issueImportMode === "excel"
                      ? bilingual(
                          lang,
                          "上传 .xlsx 或 .xlsm。必填列：Issue ID、是否排除；可选列：comment。",
                          "Upload .xlsx or .xlsm. Required: Issue ID and Exclude?; optional: comment.",
                        )
                      : bilingual(
                          lang,
                          "可粘贴上一步复制的预览 JSON，或选择 JSON 文件。确认替换草稿前不会写入 Trail。",
                          "Paste preview JSON or choose a JSON file. Trail is never written before confirmation.",
                        )}
                  </p>
                </div>
                <button
                  className="icon-button"
                  type="button"
                  aria-label={bilingual(lang, "关闭", "Close")}
                  onClick={() => setIssueImportMode(null)}
                >
                  ×
                </button>
              </div>
              <div className="trail-update-json-import-file-row">
                <input
                  ref={issueImportFileInputRef}
                  type="file"
                  accept={
                    issueImportMode === "excel" ? ".xlsx,.xlsm" : ".json,application/json"
                  }
                  hidden
                  onChange={async (e) => {
                    const f = e.target.files?.[0] || null;
                    setIssueImportFile(f);
                    setIssueImportFileName(f?.name || "");
                    setIssueImportPreview(null);
                    if (f && issueImportMode === "json") {
                      const txt = await f.text();
                      setIssueImportText(txt);
                    }
                  }}
                />
                <button
                  className="button button-quiet"
                  type="button"
                  onClick={() => issueImportFileInputRef.current?.click()}
                >
                  {issueImportMode === "excel"
                    ? bilingual(lang, "选择 Excel 文件", "Choose Excel file")
                    : bilingual(lang, "选择 JSON 文件", "Choose JSON file")}
                </button>
                <small>
                  {issueImportFileName ||
                    (issueImportMode === "excel"
                      ? bilingual(lang, "尚未选择 Excel 文件。", "No Excel file selected.")
                      : bilingual(lang, "也可以直接在下方粘贴 JSON。", "Or paste JSON below."))}
                </small>
              </div>
              {issueImportMode === "json" ? (
                <textarea
                  className="trail-update-json-import-text"
                  rows={10}
                  spellCheck={false}
                  value={issueImportText}
                  placeholder={bilingual(
                    lang,
                    "粘贴 trail_issue_exclusion_update.json 内容…",
                    "Paste JSON content…",
                  )}
                  onChange={(e) => {
                    setIssueImportText(e.target.value);
                    setIssueImportPreview(null);
                  }}
                />
              ) : null}
              {issueImportStatus.text ? (
                <div
                  className={`trail-update-json-import-status${
                    issueImportStatus.error ? " is-error" : " is-ready"
                  }`}
                >
                  {issueImportStatus.text}
                </div>
              ) : null}
              {issueImportPreview ? (
                <section className="trail-update-import-preview">
                  <div className="trail-update-import-preview-summary">
                    <strong>
                      {issueImportPreview.summary?.message ||
                        bilingual(lang, "导入预览已生成。", "Import preview generated.")}
                    </strong>
                    <small>
                      {bilingual(
                        lang,
                        `源数据 ${issueImportPreview.summary?.source_row_count || 0} 行 · 将导入 ${
                          issueImportPreview.summary?.ready_count || 0
                        } · 跳过 ${issueImportPreview.summary?.skipped_count || 0} · 需修正 ${
                          issueImportPreview.summary?.invalid_count || 0
                        }`,
                        `${issueImportPreview.summary?.source_row_count || 0} rows · ${
                          issueImportPreview.summary?.ready_count || 0
                        } ready · ${issueImportPreview.summary?.skipped_count || 0} skipped · ${
                          issueImportPreview.summary?.invalid_count || 0
                        } to fix`,
                      )}
                    </small>
                  </div>
                </section>
              ) : null}
              <div className="dialog-actions trail-update-json-actions">
                <button
                  className="button button-quiet"
                  type="button"
                  onClick={() => setIssueImportMode(null)}
                >
                  {bilingual(lang, "取消", "Cancel")}
                </button>
                <button
                  className="button button-quiet"
                  type="button"
                  disabled={issueImportBusy}
                  onClick={() => void handleRunIssueImportPreview()}
                >
                  {bilingual(lang, "生成导入预览", "Build import preview")}
                </button>
                <button
                  className="button button-primary"
                  type="button"
                  disabled={!issueImportPreview?.can_apply}
                  onClick={applyIssueImport}
                >
                  {bilingual(lang, "将有效行替换到草稿", "Replace draft with valid rows")}
                </button>
              </div>
            </div>
          ) : null}
        </dialog>,
        document.body,
      )}

      {/* Dialog 6: Confirm Trail Write */}
      {createPortal(
        <dialog
          ref={confirmDialogRef}
          id="raTrailUpdateConfirmDialog"
          className="dialog dialog-wide trail-update-confirm-dialog"
          onClose={() => setConfirmState(null)}
        >
          {confirmState ? (
            <div className="dialog-card">
              <div className="dialog-heading">
                <div>
                  <span className="eyebrow">TRAIL WRITE REVIEW</span>
                  <h2>{bilingual(lang, "确认提交到 Trail", "Confirm Trail update")}</h2>
                  <p className="dialog-copy">
                    {bilingual(
                      lang,
                      "请核对本次即将写入的 Issue 和字段。",
                      "Review the Issues and fields before committing.",
                    )}
                  </p>
                </div>
                <button
                  className="icon-button"
                  type="button"
                  aria-label={bilingual(lang, "关闭", "Close")}
                  onClick={() => setConfirmState(null)}
                >
                  ×
                </button>
              </div>
              <div className="trail-update-confirm-banner">
                <span className="trail-update-confirm-banner-icon">!</span>
                <div>
                  <strong>{targetSpec(confirmState.data).fullPath}</strong>
                  <small>
                    {bilingual(
                      lang,
                      "模型 label 保持不变；info 使用 deep_merge。",
                      "Model label stays unchanged; info is deep-merged.",
                    )}
                  </small>
                </div>
              </div>
              <div className="trail-update-confirm-list-wrap">
                <div className="trail-update-confirm-list-heading">
                  <strong>{bilingual(lang, "预计改动", "Expected changes")}</strong>
                  <div>
                    <small>
                      {(confirmState.data.items || []).filter(
                        (it) => it.trail_update_status === "pending",
                      ).length}{" "}
                      {bilingual(lang, "条", "items")}
                    </small>
                    <button
                      className="button button-quiet trail-update-confirm-expand"
                      type="button"
                      onClick={() => setConfirmExpandAll((v) => !v)}
                    >
                      {confirmExpandAll
                        ? bilingual(lang, "收起全部", "Collapse all")
                        : bilingual(lang, "展开全部", "Expand all")}
                    </button>
                  </div>
                </div>
                <div className="trail-update-confirm-list">
                  {(confirmState.data.items || [])
                    .filter((it) => it.trail_update_status === "pending")
                    .slice(0, 20)
                    .map((it) => (
                      <details
                        className="trail-update-confirm-item"
                        key={it.issue_id}
                        open={confirmExpandAll}
                      >
                        <summary>
                          <div>
                            <strong>{it.issue_id}</strong>
                          </div>
                          <div>
                            <code>{it.comment || it.trail_detail?.local_comment || "—"}</code>
                          </div>
                        </summary>
                      </details>
                    ))}
                </div>
              </div>
              <div className="dialog-actions trail-update-confirm-actions">
                <button
                  className="button button-quiet"
                  type="button"
                  onClick={() => setConfirmState(null)}
                >
                  {bilingual(lang, "返回检查", "Back to review")}
                </button>
                <button
                  className="button button-primary"
                  type="button"
                  onClick={confirmState.onConfirm}
                >
                  {bilingual(lang, "确认写入", "Confirm write")}
                </button>
              </div>
            </div>
          ) : null}
        </dialog>,
        document.body,
      )}

      {/* Dialog 7: Write Progress */}
      {createPortal(
        <dialog
          ref={progressDialogRef}
          id="raTrailUpdateProgressDialog"
          className="dialog trail-update-progress-dialog"
          data-running={String(progressState.running)}
          data-result={progressState.result || ""}
          onCancel={(e) => {
            if (progressState.running) e.preventDefault();
          }}
        >
          {progressState.open ? (
            <div className="dialog-card">
              <div className="dialog-heading">
                <div>
                  <span className="eyebrow">TRAIL WRITE PROGRESS</span>
                  <h2>
                    {progressState.running
                      ? bilingual(lang, "正在提交到 Trail", "Submitting to Trail")
                      : progressState.result === "error"
                        ? bilingual(lang, "Trail 更新失败", "Trail update failed")
                        : bilingual(lang, "Trail 更新完成", "Trail update complete")}
                  </h2>
                </div>
                <strong className="trail-update-progress-count">
                  {progressState.total
                    ? `${progressState.total} ${bilingual(lang, "个 Issue", "Issues")}`
                    : ""}
                </strong>
              </div>
              <div className="trail-update-progress-summary">
                <span className="trail-update-progress-spinner" aria-hidden="true" />
                <div>
                  <strong role="status">{progressState.message}</strong>
                  <small>
                    {bilingual(
                      lang,
                      `已用时 ${progressState.elapsedSec}s`,
                      `${progressState.elapsedSec}s elapsed`,
                    )}
                  </small>
                </div>
              </div>
              <ol className="trail-update-progress-steps">
                {PROGRESS_STAGES.map((st, idx) => {
                  const activeIdx = PROGRESS_STAGES.findIndex((s) => s.key === progressState.stage);
                  const complete = idx < activeIdx || progressState.stage === "done";
                  const isAct = idx === activeIdx && progressState.stage !== "done";
                  return (
                    <li
                      key={st.key}
                      className={isAct ? "is-active" : complete ? "is-complete" : "is-pending"}
                    >
                      <span className="trail-update-progress-step-dot">{idx + 1}</span>
                      <div>
                        <strong>{bilingual(lang, st.zh, st.en)}</strong>
                        <small>{bilingual(lang, st.subZh, st.subEn)}</small>
                      </div>
                    </li>
                  );
                })}
              </ol>
              <div className="dialog-actions trail-update-progress-actions">
                {progressState.operationId ? (
                  <a
                    className="button button-secondary trail-update-history-link"
                    href={`${withWorkbenchBase("/trail-update-history")}?operation=${encodeURIComponent(
                      progressState.operationId,
                    )}`}
                  >
                    {bilingual(lang, "查看本次更新记录", "View this update record")}
                  </a>
                ) : null}
                {!progressState.running ? (
                  <button
                    className="button button-quiet"
                    type="button"
                    onClick={() => setProgressState((prev) => ({ ...prev, open: false }))}
                  >
                    {bilingual(lang, "关闭", "Close")}
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}
        </dialog>,
        document.body,
      )}
    </div>
  );
};
