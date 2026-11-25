import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  ColorTheme,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import {
  AnalysisDonutGroup,
  AnalysisPieItem,
  analysisPiePalette,
  AnalysisPieTooltip,
  useAnalysisPieTooltip,
} from "../components/charts/AnalysisCharts";
import { ModalDialog } from "../components/ui/ModalDialog";
import { Pagination } from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

interface CampaignProgress {
  purpose?: string;
  member_count?: number;
  assigned_issue_count?: number;
  completed_issue_count?: number;
  required_submitter_count?: number;
  submitted_submitter_count?: number;
  pending_issue_count?: number;
  conflict_issue_count?: number;
  adjudicated_issue_count?: number;
  excluded_issue_count?: number;
  rationale_issue_count?: number;
  unclustered_rationale_issue_count?: number;
  label_output_counts?: Record<string, number>;
  reference_relation_counts?: Record<string, number>;
  tag_counts?: Record<string, number>;
  evidence_gap_counts?: Record<string, number>;
  scenario_counts?: Record<string, number>;
  rationale_theme_counts?: Record<string, number>;
  rationale_theme_catalog?: Array<{ key: string; label?: string }>;
}

interface CampaignSummaryItem {
  id: string;
  name?: string;
  purpose?: string;
  lifecycle?: string;
  config_revision?: number;
  legacy_read_only?: boolean;
  task_group_id?: string;
  baseline_scopes?: string[];
  workset_baseline_scope?: string;
  workset_member_count?: number;
  reference_type?: string;
  reference_id?: string;
  progress?: CampaignProgress;
}

interface HistoricalImportItem {
  id: string;
  name?: string;
  migration_version?: string;
  baseline_scope?: string;
  stats?: {
    scanned_reviews?: number;
    effective_label_sources?: number;
    reviewer_dedup_votes?: number;
    resolved_cases?: number;
    gt_review_pending_cases?: number;
    conflict_cases?: number;
    pending_adjudication_cases?: number;
  };
}

interface CampaignsListResponse {
  items?: CampaignSummaryItem[];
  historical_imports?: HistoricalImportItem[];
}

interface CampaignAssigneeStat {
  name: string;
  assigned_slots?: number;
  submitted_slots?: number;
  completed_slots?: number;
}

interface CampaignIssueRow {
  issue_id: string;
  baseline_scope?: string;
  title?: string;
  scenario?: string;
  gt_label?: string;
  reference_label?: string;
  reference_relation?: string;
  expected_output?: string;
  tags?: string[];
  evidence_gaps?: string[];
  is_excluded?: boolean;
  assignments?: Array<{ assignee: string; assignment_kind?: string }>;
  submitted?: number;
  required_submitter_count?: number;
  state?: string;
}

interface CampaignDetailResponse {
  campaign?: CampaignSummaryItem;
  progress?: CampaignProgress;
  assignees?: CampaignAssigneeStat[];
  issues?: CampaignIssueRow[];
  total?: number;
  page?: number;
  page_count?: number;
  close_snapshot?: {
    id?: string;
    config_revision?: number;
    completed_issue_count?: number;
    assigned_issue_count?: number;
    closed_at?: string;
  } | null;
  revisions?: Array<{
    revision_no?: number;
    change_source?: string;
    changed_by?: string;
    changed_by_verified?: boolean;
    changed_at?: string;
    config_sha256?: string;
  }>;
  lifecycle_audit?: Array<{
    action?: string;
    from_lifecycle?: string;
    to_lifecycle?: string;
    changed_by?: string;
    changed_by_verified?: boolean;
    config_revision?: number;
    reason?: string;
    changed_at?: string;
  }>;
  assignment_audit?: Array<{
    action?: string;
    issue_id?: string;
    from_assignee?: string;
    to_assignee?: string;
    changed_by?: string;
    changed_by_verified?: boolean;
    config_revision?: number;
    reason?: string;
    changed_at?: string;
  }>;
}

interface CampaignGroupResponse {
  group?: {
    id?: string;
    name?: string;
    purpose?: string;
    lifecycle?: string;
    workset_id?: string;
    reference_type?: string;
    reference_id?: string;
    source_run_ids?: string[];
  };
  children?: Array<{
    campaign_id: string;
    evaluation_run_id?: string;
  }>;
  campaigns?: Array<{
    campaign?: CampaignSummaryItem;
    progress?: CampaignProgress;
  }>;
}

interface DashboardConfigResponse {
  review_tag_catalog?: Array<{
    key: string;
    label?: string;
    section?: string;
  }>;
}

interface AccessUsersResponse {
  items?: Array<{
    username: string;
    enabled?: boolean;
  }>;
}

interface LegacyWindow {
  showToast?: (msg: string, isError?: boolean) => void;
  acknowledgeLocalChange?: (payload: unknown) => void;
  openAnalysisDiscussion?: (issueId: string, opts?: Record<string, unknown>) => Promise<void>;
  evidenceLabel?: (key: string) => string;
  pageUrl?: (page: string, opts?: Record<string, unknown>) => string;
}

function getLegacyWindow(): LegacyWindow {
  return window as unknown as LegacyWindow;
}

const CAMPAIGN_LIST_PAGE_SIZE = 50;
const CAMPAIGN_ISSUE_PAGE_SIZE_DEFAULT = 50;

function campaignLabel(value: string | undefined, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    labeling: ["标注实验", "Labeling experiment"],
    model_review: ["复核任务", "Review task"],
    active: ["进行中", "Active"],
    draft: ["草稿", "Draft"],
    closed: ["已关闭", "Closed"],
    cancelled: ["已取消", "Cancelled"],
    superseded: ["已替代", "Superseded"],
    activated: ["已激活", "Activated"],
    reopened: ["已重新打开", "Reopened"],
    reassigned: ["转派", "Reassigned"],
    assigned: ["已分配", "Assigned"],
    pending: ["待处理", "Pending"],
    in_progress: ["进行中", "In progress"],
    completed: ["完成", "Completed"],
    conflict: ["冲突", "Conflict"],
    adjudicated: ["已裁决", "Adjudicated"],
    stale: ["已过期", "Stale"],
    blocked: ["阻塞", "Blocked"],
    unassigned: ["未分配", "Unassigned"],
    legacy_read_only: ["Legacy 只读", "Legacy read-only"],
    matches_gt: ["与 GT 一致", "Matches GT"],
    differs_from_gt: ["与 GT 不同", "Differs from GT"],
    fills_missing_gt: ["补齐缺失 GT", "Fills missing GT"],
    matches_reference: ["与参考标签一致", "Matches reference"],
    differs_from_reference: ["与参考标签不同", "Differs from reference"],
    unknown: ["未知 / 暂无结果", "Unknown / no result"],
  };
  const key = String(value || "");
  const pair = map[key];
  if (!pair) return key || "—";
  return lang === "en" ? pair[1] : pair[0];
}

function fmtNum(value: number | undefined): string {
  const num = Number(value || 0);
  return Number.isFinite(num) ? num.toLocaleString() : "0";
}

function parseCampaignRoute() {
  const params = new URLSearchParams(window.location.search);
  const path = window.location.pathname;
  const match = path.match(/\/campaigns\/([^/?#]+)/);
  const pathId = match ? decodeURIComponent(match[1]) : "";
  return {
    campaignId: (params.get("campaign") || pathId || "").trim(),
    groupId: (params.get("group") || "").trim(),
    purpose: (params.get("purpose") || "").trim(),
    lifecycle: (params.get("lifecycle") || "current").trim() || "current",
    query: (params.get("q") || "").trim().slice(0, 128),
    openComments: params.get("comments") === "1",
    discussionIssue: (params.get("issue") || "").trim(),
    commentId: Number(params.get("comment") || 0) || 0,
    discussionChannel: (params.get("channel") || "").trim(),
  };
}

export interface CampaignsPageProps {
  active: boolean;
  lang: UiLanguage;
  theme: ColorTheme;
  selectedBaselines: string[];
  isAdmin: boolean;
}

export const CampaignsPage: React.FC<CampaignsPageProps> = ({
  active,
  lang,
  theme,
  selectedBaselines,
  isAdmin,
}) => {
  const queryClient = useQueryClient();
  const pieTooltip = useAnalysisPieTooltip();

  const initial = useMemo(() => parseCampaignRoute(), []);
  const [campaignId, setCampaignId] = useState(initial.campaignId);
  const [groupId, setGroupId] = useState(initial.groupId);
  const [groupReturnCampaignId, setGroupReturnCampaignId] = useState("");
  const [purpose, setPurpose] = useState(initial.purpose);
  const [source, setSource] = useState("all");
  const [lifecycle, setLifecycle] = useState(initial.lifecycle);
  const [queryInput, setQueryInput] = useState(initial.query);
  const [appliedQuery, setAppliedQuery] = useState(initial.query);

  // Detail issue filters
  const [issuePage, setIssuePage] = useState(1);
  const [issuePageSize, setIssuePageSize] = useState(CAMPAIGN_ISSUE_PAGE_SIZE_DEFAULT);
  const [issueAssignee, setIssueAssignee] = useState("");
  const [issueState, setIssueState] = useState("all");
  const [issueQueryInput, setIssueQueryInput] = useState(
    initial.openComments && initial.discussionIssue ? initial.discussionIssue : "",
  );
  const [appliedIssueQuery, setAppliedIssueQuery] = useState(
    initial.openComments && initial.discussionIssue ? initial.discussionIssue : "",
  );

  // Per-row admin assign/reassign drafts
  const [assignDrafts, setAssignDrafts] = useState<Record<string, string>>({});
  const [reassignFromDrafts, setReassignFromDrafts] = useState<Record<string, string>>({});
  const [reassignToDrafts, setReassignToDrafts] = useState<Record<string, string>>({});

  // Lifecycle & reassign modal state (replaces window.confirm/window.prompt)
  const [lifecycleModal, setLifecycleModal] = useState<{
    action: "activate" | "close" | "reopen" | "cancel" | "supersede";
    reason: string;
    busy: boolean;
  } | null>(null);
  const [reassignModal, setReassignModal] = useState<{
    issueId: string;
    fromAssignee: string;
    toAssignee: string;
    reason: string;
    busy: boolean;
  } | null>(null);

  // Sync URL & popstate
  useEffect(() => {
    if (!active) return;
    const syncFromUrl = () => {
      const r = parseCampaignRoute();
      setCampaignId(r.campaignId);
      setGroupId(r.groupId);
      setPurpose(r.purpose);
      setLifecycle(r.lifecycle);
      setQueryInput(r.query);
      setAppliedQuery(r.query);
    };
    window.addEventListener("popstate", syncFromUrl);
    window.addEventListener("ra:workbench-sync", syncFromUrl);
    return () => {
      window.removeEventListener("popstate", syncFromUrl);
      window.removeEventListener("ra:workbench-sync", syncFromUrl);
    };
  }, [active]);

  // Toggle .is-detail-view on host section so classic CSS matches 1:1
  useEffect(() => {
    const el = document.getElementById("campaignsPage");
    if (!el) return;
    el.classList.toggle("is-detail-view", Boolean(campaignId || groupId));
  }, [campaignId, groupId]);

  const baselinesParam = selectedBaselines.join(",");

  const pushCampaignRoute = useCallback(
    (
      next: {
        campaignId?: string;
        groupId?: string;
        purpose?: string;
        lifecycle?: string;
        query?: string;
      },
      mode: "push" | "replace" = "push",
    ) => {
      const nextCid = next.campaignId ?? campaignId;
      const nextGid = next.groupId ?? groupId;
      const nextPurpose = next.purpose ?? purpose;
      const nextLifecycle = next.lifecycle ?? lifecycle;
      const nextQ = next.query ?? appliedQuery;
      const params = new URLSearchParams();
      if (baselinesParam) params.set("baselines", baselinesParam);
      if (nextCid) params.set("campaign", nextCid);
      if (nextGid) params.set("group", nextGid);
      if (nextPurpose) params.set("purpose", nextPurpose);
      if (nextLifecycle && nextLifecycle !== "current") params.set("lifecycle", nextLifecycle);
      if (nextQ) params.set("q", nextQ);
      const url = `${withWorkbenchBase("/campaigns")}${params.toString() ? `?${params.toString()}` : ""}`;
      const stateObj = { ...(window.history.state || {}), page: "campaigns" };
      if (mode === "replace") window.history.replaceState(stateObj, "", url);
      else window.history.pushState(stateObj, "", url);
    },
    [campaignId, groupId, purpose, lifecycle, appliedQuery, baselinesParam],
  );

  // Dashboard config for review_tag_catalog
  const configQuery = useQuery<DashboardConfigResponse>({
    queryKey: ["dashboard-config"],
    queryFn: ({ signal }) => apiRequest("/api/dashboard-config", { signal }),
    enabled: active,
    staleTime: 300_000,
  });

  // Access users for admin assign/reassign dropdowns
  const accessUsersQuery = useQuery<AccessUsersResponse>({
    queryKey: ["access-users"],
    queryFn: ({ signal }) => apiRequest("/api/access-users", { signal }),
    enabled: active && isAdmin && Boolean(campaignId),
    staleTime: 60_000,
  });

  const enabledUsers = useMemo(
    () => (accessUsersQuery.data?.items || []).filter((u) => u.enabled !== false),
    [accessUsersQuery.data],
  );

  // List query
  const listQuery = useQuery<CampaignsListResponse>({
    queryKey: ["campaigns-list", baselinesParam, purpose, lifecycle, appliedQuery],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        baselines: baselinesParam,
        lifecycle: lifecycle || "current",
        page: "1",
        page_size: String(CAMPAIGN_LIST_PAGE_SIZE),
      });
      if (purpose) params.set("purpose", purpose);
      if (appliedQuery) params.set("q", appliedQuery);
      return apiRequest<CampaignsListResponse>(`/api/campaigns?${params.toString()}`, { signal });
    },
    enabled: active && !campaignId && !groupId,
    staleTime: 10_000,
  });

  // Detail query
  const detailQuery = useQuery<CampaignDetailResponse>({
    queryKey: [
      "campaign-detail",
      campaignId,
      issuePage,
      issuePageSize,
      issueState,
      issueAssignee,
      appliedIssueQuery,
    ],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        page: String(issuePage),
        page_size: String(issuePageSize),
        state: issueState,
      });
      if (issueAssignee) params.set("assignee", issueAssignee);
      if (appliedIssueQuery) params.set("q", appliedIssueQuery);
      return apiRequest<CampaignDetailResponse>(
        `/api/campaigns/${encodeURIComponent(campaignId)}?${params.toString()}`,
        { signal },
      );
    },
    enabled: active && Boolean(campaignId) && !groupId,
    staleTime: 10_000,
  });

  // Group query
  const groupQuery = useQuery<CampaignGroupResponse>({
    queryKey: ["campaign-group", groupId],
    queryFn: ({ signal }) =>
      apiRequest<CampaignGroupResponse>(
        `/api/review-task-groups/${encodeURIComponent(groupId)}`,
        { signal },
      ),
    enabled: active && Boolean(groupId),
    staleTime: 10_000,
  });

  const tagCatalogByKey = useMemo(() => {
    const map = new Map<string, { key: string; label?: string; section?: string }>();
    for (const item of configQuery.data?.review_tag_catalog || []) {
      map.set(String(item.key || ""), item);
    }
    return map;
  }, [configQuery.data]);

  const mutateAssignment = async (
    targetIssueId: string,
    opts: { action: "assign" | "unassign" | "reassign"; assignee?: string; fromAssignee?: string; reason?: string },
  ) => {
    const camp = detailQuery.data?.campaign;
    if (!camp?.id || !isAdmin) return;
    const key =
      globalThis.crypto?.randomUUID?.() ||
      `campaign-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    try {
      const res = await apiRequest(
        `/api/campaigns/${encodeURIComponent(camp.id)}/issues/${encodeURIComponent(
          targetIssueId,
        )}/assignments`,
        {
          method: "PATCH",
          headers: { "Idempotency-Key": key },
          body: {
            action: opts.action,
            assignee: opts.assignee || "",
            from_assignee: opts.fromAssignee || "",
            expected_revision: Number(camp.config_revision || 1),
            idempotency_key: key,
            assignment_kind: "base",
            reason: opts.reason || "",
          },
        },
      );
      getLegacyWindow().acknowledgeLocalChange?.(res);
      getLegacyWindow().showToast?.(
        bilingual(lang, "实验分配已更新。", "Campaign assignment updated."),
        false,
      );
      void queryClient.invalidateQueries({ queryKey: ["campaign-detail", campaignId] });
    } catch (err) {
      const msg = (err as Error)?.message || bilingual(lang, "更新实验分配失败。", "Unable to update assignment.");
      if (msg.includes("已更新")) {
        void queryClient.invalidateQueries({ queryKey: ["campaign-detail", campaignId] });
      }
      getLegacyWindow().showToast?.(msg, true);
    }
  };

  const confirmLifecycleMutation = async () => {
    if (!lifecycleModal) return;
    const camp = detailQuery.data?.campaign;
    if (!camp?.id || !isAdmin) return;
    const { action, reason } = lifecycleModal;
    const trimmedReason =
      action === "close"
        ? bilingual(lang, "从 实验管理页关闭。", "Closed from Campaign management.")
        : reason.trim();
    if (action !== "close" && !trimmedReason) return;
    setLifecycleModal({ ...lifecycleModal, busy: true });
    const key =
      globalThis.crypto?.randomUUID?.() ||
      `campaign-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    try {
      const res = await apiRequest(
        `/api/campaigns/${encodeURIComponent(camp.id)}/${action}`,
        {
          method: "POST",
          headers: { "Idempotency-Key": key },
          body: {
            expected_revision: Number(camp.config_revision || 1),
            idempotency_key: key,
            reason: trimmedReason,
          },
        },
      );
      getLegacyWindow().acknowledgeLocalChange?.(res);
      const toastMap: Record<string, [string, string]> = {
        activate: ["实验已激活。", "Campaign activated."],
        close: ["实验已关闭并保存快照。", "Campaign closed with a saved snapshot."],
        reopen: ["Campaign 已重新打开。", "Campaign reopened."],
        cancel: ["实验已取消。", "Campaign canceled."],
        supersede: ["实验已标记为替代。", "Campaign superseded."],
      };
      const pair = toastMap[action] || ["实验状态已更新。", "Campaign lifecycle updated."];
      getLegacyWindow().showToast?.(bilingual(lang, pair[0], pair[1]), false);
      setLifecycleModal(null);
      void queryClient.invalidateQueries({ queryKey: ["campaign-detail", campaignId] });
      void queryClient.invalidateQueries({ queryKey: ["campaigns-list"] });
    } catch (err) {
      const msg = (err as Error)?.message || bilingual(lang, "更新 Campaign 生命周期失败。", "Unable to update Campaign lifecycle.");
      if (msg.includes("已更新")) {
        void queryClient.invalidateQueries({ queryKey: ["campaign-detail", campaignId] });
      }
      getLegacyWindow().showToast?.(msg, true);
      setLifecycleModal((prev) => (prev ? { ...prev, busy: false } : null));
    }
  };

  // Select options
  const sourceOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "all", label: bilingual(lang, "全部来源", "All sources") },
      { value: "campaign", label: bilingual(lang, "标注实验", "Labeling experiment") },
      { value: "legacy_model_review", label: bilingual(lang, "历史判错复核", "Legacy review") },
    ],
    [lang],
  );

  const lifecycleOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "current", label: bilingual(lang, "当前任务", "Current") },
      { value: "history", label: bilingual(lang, "历史任务", "History") },
      { value: "all", label: bilingual(lang, "全部", "All") },
      { value: "active", label: bilingual(lang, "进行中", "Active") },
      { value: "draft", label: bilingual(lang, "草稿", "Draft") },
      { value: "closed", label: bilingual(lang, "已关闭", "Closed") },
      { value: "cancelled", label: bilingual(lang, "已取消", "Cancelled") },
      { value: "superseded", label: bilingual(lang, "已替代", "Superseded") },
    ],
    [lang],
  );

  const issueStateOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "all", label: bilingual(lang, "全部", "All") },
      { value: "pending", label: campaignLabel("pending", lang) },
      { value: "in_progress", label: campaignLabel("in_progress", lang) },
      { value: "completed", label: campaignLabel("completed", lang) },
      { value: "conflict", label: campaignLabel("conflict", lang) },
      { value: "adjudicated", label: campaignLabel("adjudicated", lang) },
      { value: "stale", label: campaignLabel("stale", lang) },
      { value: "blocked", label: campaignLabel("blocked", lang) },
      { value: "unassigned", label: campaignLabel("unassigned", lang) },
      { value: "legacy_read_only", label: campaignLabel("legacy_read_only", lang) },
    ],
    [lang],
  );

  const visibleCampaignItems = useMemo(() => {
    const items = listQuery.data?.items || [];
    return source === "legacy_model_review" ? [] : items;
  }, [listQuery.data, source]);

  const visibleImports = useMemo(() => {
    const imports = listQuery.data?.historical_imports || [];
    return source === "campaign" ? [] : imports;
  }, [listQuery.data, source]);

  const listStatusText = useMemo(() => {
    if (listQuery.isLoading) return bilingual(lang, "正在加载实验…", "Loading campaigns…");
    if (listQuery.isError)
      return (listQuery.error as Error)?.message || bilingual(lang, "加载失败", "Failed to load");
    const count = visibleCampaignItems.length + visibleImports.length;
    const noun =
      purpose === "labeling"
        ? bilingual(lang, "个标注实验", "labeling experiments")
        : purpose === "model_review"
          ? bilingual(lang, "个复核任务", "review tasks")
          : bilingual(lang, "个实验", "experiments");
    return `${fmtNum(count)} ${noun}`;
  }, [listQuery.isLoading, listQuery.isError, listQuery.error, visibleCampaignItems.length, visibleImports.length, purpose, lang]);

  // Detail derived data
  const detail = detailQuery.data;
  const campaign = detail?.campaign || ({} as CampaignSummaryItem);
  const progress = detail?.progress || ({} as CampaignProgress);
  const isLabelingDetail = campaign.purpose === "labeling";
  const canManageLifecycle = Boolean(isAdmin && campaign.purpose && !campaign.legacy_read_only);
  const canManageAssignments = Boolean(canManageLifecycle && campaign.lifecycle === "active");

  const assigneeFilterOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "全部负责人", "All assignees") },
      ...(detail?.assignees || []).map((a) => ({ value: a.name, label: a.name })),
    ],
    [detail?.assignees, lang],
  );

  const userSelectOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "选择负责人", "Choose assignee") },
      ...enabledUsers.map((u) => ({ value: u.username, label: u.username })),
    ],
    [enabledUsers, lang],
  );

  const reassignToOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "转派给", "Reassign to") },
      ...enabledUsers.map((u) => ({ value: u.username, label: u.username })),
    ],
    [enabledUsers, lang],
  );

  // Label analysis distributions
  const labelOutputItems: AnalysisPieItem[] = useMemo(() => {
    const counts = progress.label_output_counts || {};
    return (["误触发", "正确触发", "无需协助"] as const)
      .map((k) => ({ key: k, label: k, count: Math.max(0, Number(counts[k] || 0)) }))
      .filter((i) => i.count > 0);
  }, [progress.label_output_counts]);

  const refRelationItems: AnalysisPieItem[] = useMemo(() => {
    const counts = progress.reference_relation_counts || {};
    const keys = [
      "matches_gt",
      "differs_from_gt",
      "fills_missing_gt",
      "matches_reference",
      "differs_from_reference",
      "unknown",
    ];
    return keys
      .map((k) => ({
        key: k,
        label: campaignLabel(k, lang),
        count: Math.max(0, Number(counts[k] || 0)),
      }))
      .filter((i) => i.count > 0);
  }, [progress.reference_relation_counts, lang]);

  const tagSectionItems = useMemo(() => {
    const sections: Record<"scene" | "trigger" | "egress" | "other", AnalysisPieItem[]> = {
      scene: [],
      trigger: [],
      egress: [],
      other: [],
    };
    for (const [key, raw] of Object.entries(progress.tag_counts || {})) {
      const count = Number(raw || 0);
      if (count <= 0) continue;
      const item = tagCatalogByKey.get(String(key));
      const sec = String(item?.section || "");
      const target =
        sec === "scene"
          ? "scene"
          : sec === "interaction_decision"
            ? "trigger"
            : sec === "egress"
              ? "egress"
              : "other";
      sections[target].push({
        key,
        label: item?.label || bilingual(lang, "未分类标签", "Unclassified tag"),
        count,
      });
    }
    for (const list of Object.values(sections)) {
      list.sort((a, b) => b.count - a.count || a.key.localeCompare(b.key));
    }
    return sections;
  }, [progress.tag_counts, tagCatalogByKey, lang]);

  const renderRankedList = (
    values: Record<string, number> | undefined,
    catalog?: Array<{ key: string; label?: string }>,
  ) => {
    const byKey = new Map((catalog || []).map((c) => [String(c.key), c]));
    const entries = Object.entries(values || {})
      .map(([k, v]) => ({ key: k, count: Number(v || 0), label: byKey.get(k)?.label || k }))
      .filter((e) => e.count > 0)
      .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key))
      .slice(0, 12);
    if (!entries.length) return null;
    const max = Math.max(1, ...entries.map((e) => e.count));
    return (
      <div className="campaign-ranked-list">
        {entries.map((e) => (
          <div className="campaign-ranked-row" key={e.key}>
            <span title={e.key}>{e.label}</span>
            <strong>{fmtNum(e.count)}</strong>
            <i>
              <b style={{ width: `${Math.round((e.count / max) * 100)}%` }} />
            </i>
          </div>
        ))}
      </div>
    );
  };

  if (!active) return null;

  const hasDetail = Boolean(campaignId) && !groupId;
  const hasGroup = Boolean(groupId);
  const showList = !hasDetail && !hasGroup;

  return (
    <div className="ra-campaigns-root" data-react-island="campaigns">
      {showList ? (
        <>
          <section className="page-card campaigns-header">
            <div>
              <span className="campaigns-eyebrow">LABELING EXPERIMENTS</span>
              <h2>{bilingual(lang, "任务与标注汇总", "Tasks and labeling results")}</h2>
              <p>
                {bilingual(
                  lang,
                  "按用途、生命周期与冻结参考查看任务组、逐 Issue 要求和提交进度。",
                  "Browse task groups, per-Issue requirements, and submission progress by purpose, lifecycle, and frozen reference.",
                )}
              </p>
            </div>
            {purpose === "labeling" ? (
              <section className="labeling-experiment-guide" id="labelingExperimentGuide">
                <span className="eyebrow">LABELING EXPERIMENT</span>
                <h3>{bilingual(lang, "创建标注实验", "Create a labeling experiment")}</h3>
                <ol>
                  <li>
                    <span>1</span>
                    <b>{bilingual(lang, "选择数据集和 Case 范围", "Select datasets & Case scope")}</b>
                  </li>
                  <li>
                    <span>2</span>
                    <b>{bilingual(lang, "选择人员", "Choose labelers")}</b>
                  </li>
                  <li>
                    <span>3</span>
                    <b>{bilingual(lang, "设置单人/双人/交叉比例", "Configure overlap ratio")}</b>
                  </li>
                  <li>
                    <span>4</span>
                    <b>{bilingual(lang, "预览工作量和重叠", "Preview workload & overlap")}</b>
                  </li>
                  <li>
                    <span>5</span>
                    <b>{bilingual(lang, "创建实验", "Create experiment")}</b>
                  </li>
                </ol>
              </section>
            ) : null}
            <button
              className="button button-quiet"
              id="campaignsRefresh"
              type="button"
              onClick={() => void queryClient.invalidateQueries({ queryKey: ["campaigns-list"] })}
            >
              {bilingual(lang, "刷新", "Refresh")}
            </button>
          </section>

          <section className="page-card campaigns-list-card" id="campaignsListView">
            <div className="campaigns-toolbar">
              <div
                className="campaigns-view-tabs"
                role="tablist"
                aria-label={bilingual(lang, "实验视图", "Experiment views")}
              >
                <button
                  className={`button button-quiet${purpose !== "labeling" ? " is-active" : ""}`}
                  id="campaignsAllTab"
                  type="button"
                  role="tab"
                  aria-selected={purpose !== "labeling"}
                  onClick={() => {
                    setPurpose("");
                    setCampaignId("");
                    setGroupId("");
                    pushCampaignRoute({ purpose: "", campaignId: "", groupId: "" });
                  }}
                >
                  {bilingual(lang, "全部实验", "All experiments")}
                </button>
                <button
                  className={`button button-quiet${purpose === "labeling" ? " is-active" : ""}`}
                  id="campaignsLabelAnalysisTab"
                  type="button"
                  role="tab"
                  aria-selected={purpose === "labeling"}
                  onClick={() => {
                    setPurpose("labeling");
                    setCampaignId("");
                    setGroupId("");
                    pushCampaignRoute({ purpose: "labeling", campaignId: "", groupId: "" });
                  }}
                >
                  {bilingual(lang, "标注汇总", "Labeling summary")}
                </button>
              </div>

              <form
                className="campaigns-filters"
                id="campaignsFilterForm"
                onSubmit={(e) => {
                  e.preventDefault();
                  const q = queryInput.trim().slice(0, 128);
                  setAppliedQuery(q);
                  setCampaignId("");
                  setIssuePage(1);
                  pushCampaignRoute({ campaignId: "", lifecycle, query: q });
                }}
              >
                <div className="ra-camp-field">
                  <span>{bilingual(lang, "来源", "Source")}</span>
                  <UiSelect
                    id="campaignsSource"
                    value={source}
                    options={sourceOptions}
                    ariaLabel={bilingual(lang, "来源", "Source")}
                    onChange={setSource}
                  />
                </div>
                <div className="ra-camp-field">
                  <span>{bilingual(lang, "生命周期", "Lifecycle")}</span>
                  <UiSelect
                    id="campaignsLifecycle"
                    value={lifecycle}
                    options={lifecycleOptions}
                    ariaLabel={bilingual(lang, "生命周期", "Lifecycle")}
                    onChange={(v) => {
                      setLifecycle(v);
                      pushCampaignRoute({ lifecycle: v, campaignId: "" });
                    }}
                  />
                </div>
                <label className="campaigns-search">
                  <span>{bilingual(lang, "Search", "Search")}</span>
                  <input
                    id="campaignsQuery"
                    type="search"
                    maxLength={128}
                    autoComplete="off"
                    value={queryInput}
                    placeholder={bilingual(lang, "名称或 Issue", "Name or Issue")}
                    onChange={(e) => setQueryInput(e.target.value)}
                  />
                </label>
                <button className="button button-primary" type="submit">
                  {bilingual(lang, "筛选", "Filter")}
                </button>
              </form>
            </div>

            <p className="campaigns-list-status" id="campaignsListStatus" aria-live="polite">
              {listStatusText}
            </p>

            <div className="table-scroll">
              <table className="campaigns-table">
                <thead>
                  <tr>
                    <th>{bilingual(lang, "实验", "Experiment")}</th>
                    <th>{bilingual(lang, "用途", "Purpose")}</th>
                    <th>{bilingual(lang, "生命周期", "Lifecycle")}</th>
                    <th>{bilingual(lang, "成员 / 要求", "Members / Req")}</th>
                    <th>{bilingual(lang, "已提交", "Submitted")}</th>
                    <th>{bilingual(lang, "进度", "Progress")}</th>
                    <th>{bilingual(lang, "数据集 / 参考", "Dataset / Ref")}</th>
                  </tr>
                </thead>
                <tbody id="campaignsRows">
                  {listQuery.isLoading ? (
                    <tr>
                      <td colSpan={7} className="campaign-empty-state">
                        {bilingual(lang, "正在加载…", "Loading…")}
                      </td>
                    </tr>
                  ) : !visibleCampaignItems.length && !visibleImports.length ? (
                    <tr>
                      <td colSpan={7} className="campaign-empty-state">
                        {bilingual(lang, "当前筛选没有 Campaign。", "No campaigns match these filters.")}
                      </td>
                    </tr>
                  ) : (
                    <>
                      {visibleImports.map((item) => {
                        const stats = item.stats || {};
                        return (
                          <tr key={`imp-${item.id}`} data-label-import-batch={item.id}>
                            <td>
                              <div className="campaign-row-identity">
                                <span className="campaign-row-name">{item.name || item.id}</span>
                                <span className="campaign-row-id">
                                  {item.migration_version || ""}
                                </span>
                              </div>
                            </td>
                            <td>
                              <span className="campaign-purpose-badge">
                                {bilingual(lang, "历史标签导入", "Historical label import")}
                              </span>
                            </td>
                            <td>
                              <span className="campaign-lifecycle-badge" data-lifecycle="closed">
                                {bilingual(lang, "已导入", "Imported")}
                              </span>
                            </td>
                            <td>
                              {fmtNum(stats.scanned_reviews)} /{" "}
                              {fmtNum(stats.effective_label_sources)}
                            </td>
                            <td>{fmtNum(stats.reviewer_dedup_votes)}</td>
                            <td className="campaign-progress-cell">
                              <span>
                                {bilingual(lang, "一致", "Resolved")}{" "}
                                {fmtNum(stats.resolved_cases)} ·{" "}
                                <span className="campaign-import-warning">
                                  {bilingual(lang, "GT待复核", "GT review")}{" "}
                                  {fmtNum(stats.gt_review_pending_cases)} ·{" "}
                                  {bilingual(lang, "冲突", "Conflicts")}{" "}
                                  {fmtNum(stats.conflict_cases)} ·{" "}
                                  {bilingual(lang, "待裁决", "Pending adjudication")}{" "}
                                  {fmtNum(stats.pending_adjudication_cases)}
                                </span>
                              </span>
                            </td>
                            <td>
                              {item.baseline_scope || "—"}
                              <span className="campaign-reference-text">
                                {bilingual(lang, "来源：历史判错复核", "Source: historical Review")}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                      {visibleCampaignItems.map((item) => {
                        const p = item.progress || {};
                        const memberCount = Number(p.member_count ?? item.workset_member_count ?? 0);
                        const assigned = Number(p.assigned_issue_count || 0);
                        const completed = Number(p.completed_issue_count || 0);
                        const required = Number(p.required_submitter_count || 0);
                        const submitted = Number(p.submitted_submitter_count || 0);
                        const ratio = assigned ? Math.max(0, Math.min(1, completed / assigned)) : 0;
                        const baseline =
                          (item.baseline_scopes || []).join(", ") ||
                          item.workset_baseline_scope ||
                          "—";
                        const reference = item.reference_id
                          ? `${item.reference_type || "reference"} · ${String(item.reference_id).slice(0, 18)}`
                          : bilingual(lang, "参考未解析", "Reference unresolved");
                        const itemPurpose = item.purpose
                          ? campaignLabel(item.purpose, lang)
                          : bilingual(lang, "未分类", "Unclassified");
                        return (
                          <tr key={item.id}>
                            <td>
                              <div className="campaign-row-identity">
                                <button
                                  type="button"
                                  className="campaign-row-button"
                                  data-campaign-open={item.id}
                                  onClick={() => {
                                    setCampaignId(item.id);
                                    setGroupId("");
                                    setIssuePage(1);
                                    setIssueAssignee("");
                                    setIssueState("all");
                                    setIssueQueryInput("");
                                    setAppliedIssueQuery("");
                                    pushCampaignRoute({ campaignId: item.id, groupId: "" });
                                  }}
                                >
                                  <span className="campaign-row-name">
                                    {item.name || item.id}
                                  </span>
                                  <span className="campaign-row-id">{item.id}</span>
                                </button>
                                {item.task_group_id ? (
                                  <button
                                    type="button"
                                    className="campaign-group-link"
                                    onClick={() => {
                                      setGroupReturnCampaignId("");
                                      setGroupId(item.task_group_id || "");
                                      setCampaignId("");
                                      pushCampaignRoute({
                                        campaignId: "",
                                        groupId: item.task_group_id || "",
                                      });
                                    }}
                                  >
                                    {bilingual(lang, "查看 Task Group", "View Task Group")} ·{" "}
                                    {item.task_group_id}
                                  </button>
                                ) : null}
                              </div>
                            </td>
                            <td>
                              <span className="campaign-purpose-badge">{itemPurpose}</span>
                            </td>
                            <td>
                              <span
                                className="campaign-lifecycle-badge"
                                data-lifecycle={item.lifecycle || ""}
                              >
                                {campaignLabel(item.lifecycle, lang)}
                              </span>
                            </td>
                            <td>
                              {fmtNum(memberCount)} / {fmtNum(required)}
                            </td>
                            <td>
                              {fmtNum(submitted)} / {fmtNum(required)}
                            </td>
                            <td className="campaign-progress-cell">
                              {fmtNum(completed)} / {fmtNum(assigned)}
                              <div
                                className="campaign-progress-bar"
                                aria-label={`${Math.round(ratio * 100)}%`}
                              >
                                <span style={{ width: `${Math.round(ratio * 100)}%` }} />
                              </div>
                            </td>
                            <td>
                              {baseline}
                              <span className="campaign-reference-text">{reference}</span>
                            </td>
                          </tr>
                        );
                      })}
                    </>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}

      {hasDetail ? (
        <section className="page-card campaign-detail-card" id="campaignDetailView">
          <header className="campaign-detail-header">
            <div className="campaign-detail-identity">
              <button
                className="button button-quiet"
                id="campaignDetailBack"
                type="button"
                onClick={() => {
                  setCampaignId("");
                  setGroupId("");
                  pushCampaignRoute({ campaignId: "", groupId: "" });
                }}
              >
                ← {bilingual(lang, "返回实验列表", "Back to experiments")}
              </button>
              <div className="campaign-detail-title-line">
                <h2 id="campaignDetailTitle">
                  {detailQuery.isLoading
                    ? bilingual(lang, "正在加载实验…", "Loading campaign…")
                    : campaign.name || campaign.id || "Campaign"}
                </h2>
                <span
                  className="campaign-lifecycle-badge"
                  id="campaignDetailLifecycle"
                  data-lifecycle={campaign.lifecycle || ""}
                >
                  {campaignLabel(campaign.lifecycle, lang)}
                </span>
              </div>
              <p id="campaignDetailMeta">
                {(() => {
                  const scopes =
                    campaign.baseline_scopes ||
                    (campaign.workset_baseline_scope ? [campaign.workset_baseline_scope] : []);
                  const datasets = scopes.map(
                    (s) => String(s).match(/^release(\d{4})/)?.[1] || String(s),
                  );
                  const noun = isLabelingDetail ? "Case" : "Issue";
                  return `${datasets.join(" + ") || bilingual(lang, "当前数据集", "Current dataset")} · ${campaignLabel(
                    campaign.purpose || "",
                    lang,
                  )} · ${fmtNum(progress.member_count)} ${bilingual(lang, `个 ${noun}`, `${noun}s`)}${
                    campaign.reference_id
                      ? bilingual(lang, " · 已冻结 GT 参考", " · Frozen GT reference")
                      : ""
                  }`;
                })()}
              </p>
              <details className="campaign-technical-details">
                <summary>{bilingual(lang, "技术信息", "Technical info")}</summary>
                <div id="campaignDetailTechnical">
                  {`任务 ID：${campaign.id || "—"}\n数据范围：${
                    (campaign.baseline_scopes || []).join(", ") ||
                    campaign.workset_baseline_scope ||
                    "—"
                  }\n参考：${campaign.reference_type || "—"} · ${campaign.reference_id || "—"}`}
                </div>
              </details>
              {campaign.task_group_id ? (
                <button
                  className="button button-quiet"
                  id="campaignOpenGroupButton"
                  type="button"
                  onClick={() => {
                    setGroupReturnCampaignId(campaign.id || campaignId);
                    setGroupId(campaign.task_group_id || "");
                    setCampaignId("");
                    pushCampaignRoute({ campaignId: "", groupId: campaign.task_group_id || "" });
                  }}
                >
                  {bilingual(lang, "查看关联任务组", "View task group")}
                </button>
              ) : null}
            </div>

            {canManageLifecycle ? (
              <details className="campaign-manage-menu">
                <summary>{bilingual(lang, "管理实验", "Manage experiment")}</summary>
                <div className="campaign-detail-actions">
                  {campaign.lifecycle === "draft" ? (
                    <button
                      className="button button-quiet"
                      type="button"
                      onClick={() =>
                        setLifecycleModal({ action: "activate", reason: "", busy: false })
                      }
                    >
                      {bilingual(lang, "激活草稿", "Activate draft")}
                    </button>
                  ) : null}
                  {campaign.lifecycle === "active" ? (
                    <button
                      className="button button-quiet"
                      type="button"
                      onClick={() =>
                        setLifecycleModal({ action: "close", reason: "", busy: false })
                      }
                    >
                      {bilingual(lang, "关闭实验", "Close experiment")}
                    </button>
                  ) : null}
                  {campaign.lifecycle === "closed" ? (
                    <button
                      className="button button-quiet"
                      type="button"
                      onClick={() =>
                        setLifecycleModal({ action: "reopen", reason: "", busy: false })
                      }
                    >
                      {bilingual(lang, "重新打开", "Reopen")}
                    </button>
                  ) : null}
                  {campaign.lifecycle === "draft" || campaign.lifecycle === "active" ? (
                    <button
                      className="button button-quiet"
                      type="button"
                      onClick={() =>
                        setLifecycleModal({ action: "cancel", reason: "", busy: false })
                      }
                    >
                      {bilingual(lang, "取消实验", "Cancel experiment")}
                    </button>
                  ) : null}
                  {campaign.lifecycle === "active" ? (
                    <button
                      className="button button-quiet"
                      type="button"
                      onClick={() =>
                        setLifecycleModal({ action: "supersede", reason: "", busy: false })
                      }
                    >
                      {bilingual(lang, "标记为替代", "Supersede")}
                    </button>
                  ) : null}
                </div>
              </details>
            ) : null}
          </header>

          <p className="campaign-scope-note">
            {bilingual(
              lang,
              "实验总览 · 以下进度和分布统计整个实验；明细筛选仅作用于 Case 列表和明细导出。",
              "Experiment overview · Progress and distributions reflect the entire experiment; detail filters apply to the Case table and CSV export.",
            )}
          </p>

          {(() => {
            const members = Number(progress.member_count || 0);
            const assigned = Number(progress.assigned_issue_count || 0);
            const completed = Number(progress.completed_issue_count || 0);
            const required = Number(progress.required_submitter_count || 0);
            const submitted = Number(progress.submitted_submitter_count || 0);
            const pending = Number(progress.pending_issue_count || 0);
            const conflicts = Number(progress.conflict_issue_count || 0);
            const percent = assigned ? Math.min(100, Math.round((completed * 100) / assigned)) : 0;
            const noun = isLabelingDetail ? "Case" : "Issue";
            return (
              <div className="campaign-progress-metrics" id="campaignProgressMetrics">
                <div className="campaign-progress-hero">
                  <span>{bilingual(lang, "完成进度", "Completion")}</span>
                  <strong>
                    {fmtNum(completed)}{" "}
                    <small>
                      / {fmtNum(assigned)} {noun}
                    </small>
                  </strong>
                  <div
                    className="campaign-progress-bar"
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={percent}
                    aria-label={bilingual(lang, `已完成 ${percent}%`, `${percent}% completed`)}
                  >
                    <span style={{ width: `${percent}%` }} />
                  </div>
                  <small>
                    {bilingual(
                      lang,
                      `已分配 ${fmtNum(assigned)} / ${fmtNum(members)} · 完成 ${percent}%`,
                      `Assigned ${fmtNum(assigned)} / ${fmtNum(members)} · ${percent}% done`,
                    )}
                  </small>
                </div>
                <div className="campaign-progress-metric">
                  <span>{bilingual(lang, `待处理 ${noun}`, `Pending ${noun}s`)}</span>
                  <strong>{fmtNum(pending)}</strong>
                </div>
                <div className="campaign-progress-metric">
                  <span>{bilingual(lang, "已提交 / 所需", "Submitted / Req")}</span>
                  <strong>
                    {fmtNum(submitted)} <small>/ {fmtNum(required)}</small>
                  </strong>
                </div>
                <div className={`campaign-progress-metric${conflicts ? " has-conflict" : ""}`}>
                  <span>{bilingual(lang, "冲突待处理", "Pending conflicts")}</span>
                  <strong>{fmtNum(conflicts)}</strong>
                </div>
              </div>
            );
          })()}

          {isLabelingDetail ? (
            <section
              className={`campaign-label-analysis${
                Number(progress.submitted_submitter_count || 0) > 0 ? "" : " is-empty"
              }`}
              id="campaignLabelAnalysis"
            >
              <div className="campaign-analysis-toolbar">
                <h3>{bilingual(lang, "标注结果", "Labeling results")}</h3>
                {isAdmin && Number(progress.submitted_submitter_count || 0) > 0 ? (
                  <a
                    className="button button-quiet"
                    id="campaignLabelExportCsv"
                    href={(() => {
                      const p = new URLSearchParams();
                      if (appliedIssueQuery) p.set("q", appliedIssueQuery);
                      if (issueAssignee) p.set("assignee", issueAssignee);
                      if (issueState !== "all") p.set("state", issueState);
                      const qs = p.toString();
                      return withWorkbenchBase(
                        `/api/campaigns/${encodeURIComponent(campaign.id)}/analysis/export.csv${
                          qs ? `?${qs}` : ""
                        }`,
                      );
                    })()}
                  >
                    {bilingual(lang, "导出明细 CSV", "Export detail CSV")}
                  </a>
                ) : null}
              </div>

              {Number(progress.submitted_submitter_count || 0) <= 0 ? (
                <p className="campaign-analysis-empty" id="campaignAnalysisEmpty">
                  {bilingual(
                    lang,
                    "尚无提交。开始标注后，这里会显示结果分布及与冻结 GT 的差异。",
                    "No submissions yet. Result distributions and comparison against frozen GT will appear once labeling starts.",
                  )}
                </p>
              ) : (
                <>
                  <div className="campaign-analysis-grid campaign-analysis-primary">
                    <article className="campaign-analysis-card">
                      <h3>{bilingual(lang, "标注结果分布", "Label output distribution")}</h3>
                      <AnalysisDonutGroup
                        group={{
                          key: "campaignLabelOutputCounts",
                          label: "Case",
                          annotated_count: labelOutputItems.reduce((s, i) => s + i.count, 0),
                          items: labelOutputItems,
                        }}
                        palette={analysisPiePalette("evidence", theme)}
                        lang={lang}
                        onShowTooltip={pieTooltip.showTooltip}
                        onHideTooltip={pieTooltip.hideTooltip}
                      />
                    </article>
                    <article className="campaign-analysis-card">
                      <h3>{bilingual(lang, "相对冻结参考", "Against frozen reference")}</h3>
                      <AnalysisDonutGroup
                        group={{
                          key: "campaignReferenceRelationCounts",
                          label: "Case",
                          annotated_count: refRelationItems.reduce((s, i) => s + i.count, 0),
                          items: refRelationItems,
                        }}
                        palette={analysisPiePalette("trigger", theme)}
                        lang={lang}
                        onShowTooltip={pieTooltip.showTooltip}
                        onHideTooltip={pieTooltip.hideTooltip}
                      />
                    </article>
                  </div>

                  <div className="campaign-analysis-grid campaign-analysis-clusters">
                    {(
                      [
                        ["scene", "场景", "Scene tags", "scene"],
                        ["trigger", "触发判定", "Trigger / interaction", "trigger"],
                        ["egress", "如何脱困", "Egress", "egress"],
                        ["other", "历史 / 其他标签", "Legacy / other tags", "evidence"],
                      ] as const
                    ).map(([secKey, zhTitle, enTitle, palKey]) => {
                      const items = tagSectionItems[secKey];
                      if (!items.length) return null;
                      return (
                        <article className="campaign-analysis-card" key={secKey}>
                          <h3>{bilingual(lang, zhTitle, enTitle)}</h3>
                          <AnalysisDonutGroup
                            group={{
                              key: `campaign-${secKey}`,
                              label: bilingual(lang, "标签次数", "Tag count"),
                              annotated_count: items.reduce((s, i) => s + i.count, 0),
                              items,
                            }}
                            palette={analysisPiePalette(palKey, theme)}
                            lang={lang}
                            onShowTooltip={pieTooltip.showTooltip}
                            onHideTooltip={pieTooltip.hideTooltip}
                          />
                        </article>
                      );
                    })}

                    {renderRankedList(
                      progress.rationale_theme_counts,
                      progress.rationale_theme_catalog,
                    ) ? (
                      <article className="campaign-analysis-card">
                        <h3>{bilingual(lang, "标注依据原因聚类", "Label rationale themes")}</h3>
                        {renderRankedList(
                          progress.rationale_theme_counts,
                          progress.rationale_theme_catalog,
                        )}
                      </article>
                    ) : null}

                    {renderRankedList(progress.evidence_gap_counts) ? (
                      <article className="campaign-analysis-card">
                        <h3>{bilingual(lang, "证据缺口", "Evidence gaps")}</h3>
                        {renderRankedList(progress.evidence_gap_counts)}
                      </article>
                    ) : null}

                    {renderRankedList(progress.scenario_counts) ? (
                      <article className="campaign-analysis-card">
                        <h3>{bilingual(lang, "Scenario 分布", "Scenario distribution")}</h3>
                        {renderRankedList(progress.scenario_counts)}
                      </article>
                    ) : null}

                    <article className="campaign-analysis-card">
                      <h3>{bilingual(lang, "标注提醒", "Labeling notes")}</h3>
                      <div className="campaign-analysis-counts">
                        {(
                          [
                            [campaignLabel("conflict", lang), progress.conflict_issue_count],
                            [campaignLabel("adjudicated", lang), progress.adjudicated_issue_count],
                            [
                              bilingual(lang, "提出排除", "Exclusion proposed"),
                              progress.excluded_issue_count,
                            ],
                            [
                              bilingual(lang, "有标注依据", "With rationale"),
                              progress.rationale_issue_count,
                            ],
                            [
                              bilingual(lang, "原因待归类", "Unclustered rationale"),
                              progress.unclustered_rationale_issue_count,
                            ],
                          ] as Array<[string, number | undefined]>
                        ).map(([lbl, cnt]) => (
                          <div className="campaign-analysis-count-row" key={lbl}>
                            <span>{lbl}</span>
                            <strong>{fmtNum(cnt)}</strong>
                          </div>
                        ))}
                      </div>
                    </article>
                  </div>
                </>
              )}
            </section>
          ) : null}

          {detail?.close_snapshot ? (
            <div className="campaign-close-snapshot" id="campaignCloseSnapshot">
              {`${bilingual(lang, "关闭快照", "Close snapshot")} ${
                detail.close_snapshot.id || ""
              } · ${bilingual(lang, "版本", "Revision")} ${
                detail.close_snapshot.config_revision ?? ""
              } · ${bilingual(lang, "完成", "Completed")} ${
                detail.close_snapshot.completed_issue_count ?? 0
              }/${detail.close_snapshot.assigned_issue_count ?? 0} · ${
                detail.close_snapshot.closed_at || ""
              }`}
            </div>
          ) : null}

          <section className="campaign-assignee-section">
            <h3>{bilingual(lang, "负责人进度", "Assignee progress")}</h3>
            <div className="table-scroll">
              <table className="campaigns-table">
                <thead>
                  <tr>
                    <th>{bilingual(lang, "负责人", "Assignee")}</th>
                    <th>{bilingual(lang, "已分配", "Assigned")}</th>
                    <th>{bilingual(lang, "已提交", "Submitted")}</th>
                    <th>{bilingual(lang, "已完成", "Completed")}</th>
                  </tr>
                </thead>
                <tbody id="campaignAssigneeRows">
                  {!(detail?.assignees || []).length ? (
                    <tr>
                      <td colSpan={4} className="campaign-empty-state">
                        {bilingual(lang, "暂无负责人分配。", "No assignees.")}
                      </td>
                    </tr>
                  ) : (
                    (detail?.assignees || []).map((a) => (
                      <tr key={a.name}>
                        <td>{a.name}</td>
                        <td>{fmtNum(a.assigned_slots)}</td>
                        <td>{fmtNum(a.submitted_slots)}</td>
                        <td>{fmtNum(a.completed_slots)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section className="campaign-issue-section">
            <div className="campaign-issue-heading">
              <h3 id="campaignIssuesHeading">
                {isLabelingDetail
                  ? bilingual(lang, "Case 明细", "Case details")
                  : bilingual(lang, "Issue 明细", "Issue details")}
              </h3>
              <span id="campaignIssueCount">
                {`${fmtNum(detail?.total)} ${bilingual(
                  lang,
                  `个 ${isLabelingDetail ? "Case" : "Issue"}`,
                  `${isLabelingDetail ? "Cases" : "Issues"}`,
                )}`}
              </span>
            </div>

            <div
              className="campaign-issue-filters"
              aria-label={bilingual(lang, "筛选 Case 明细", "Filter Case details")}
            >
              <div className="ra-camp-field">
                <span>{bilingual(lang, "负责人", "Assignee")}</span>
                <UiSelect
                  id="campaignIssueAssignee"
                  value={issueAssignee}
                  options={assigneeFilterOptions}
                  ariaLabel={bilingual(lang, "负责人", "Assignee")}
                  onChange={(v) => {
                    setIssueAssignee(v);
                    setIssuePage(1);
                  }}
                />
              </div>
              <div className="ra-camp-field">
                <span>{bilingual(lang, "状态", "State")}</span>
                <UiSelect
                  id="campaignIssueState"
                  value={issueState}
                  options={issueStateOptions}
                  ariaLabel={bilingual(lang, "状态", "State")}
                  onChange={(v) => {
                    setIssueState(v);
                    setIssuePage(1);
                  }}
                />
              </div>
              <label className="campaigns-search">
                <span>{bilingual(lang, "检索 Case 或标注依据", "Search Case or rationale")}</span>
                <input
                  id="campaignIssueQuery"
                  type="search"
                  maxLength={128}
                  autoComplete="off"
                  value={issueQueryInput}
                  placeholder={bilingual(lang, "Issue ID、场景或标注依据", "Issue ID, scene, or rationale")}
                  onChange={(e) => setIssueQueryInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      setAppliedIssueQuery(issueQueryInput.trim().slice(0, 128));
                      setIssuePage(1);
                    }
                  }}
                />
              </label>
              <button
                className="button button-quiet"
                id="campaignIssueFilterButton"
                type="button"
                onClick={() => {
                  setAppliedIssueQuery(issueQueryInput.trim().slice(0, 128));
                  setIssuePage(1);
                }}
              >
                {bilingual(lang, "筛选", "Filter")}
              </button>
            </div>

            <div className="table-scroll">
              <table className="campaigns-table campaign-issues-table">
                <thead>
                  <tr>
                    <th>Issue</th>
                    <th>{bilingual(lang, "GT / 参考", "GT / Ref")}</th>
                    <th>{bilingual(lang, "期望输出", "Expected output")}</th>
                    <th>{bilingual(lang, "标签 / 证据缺口", "Tags / Evidence gaps")}</th>
                    <th>{bilingual(lang, "排除", "Exclusion")}</th>
                    <th>{bilingual(lang, "负责人", "Assignees")}</th>
                    <th>{bilingual(lang, "已提交 / 要求", "Submitted / Req")}</th>
                    <th>{bilingual(lang, "状态", "State")}</th>
                    {canManageAssignments ? (
                      <th data-campaign-admin-column>{bilingual(lang, "管理", "Manage")}</th>
                    ) : null}
                  </tr>
                </thead>
                <tbody id="campaignIssueRows">
                  {detailQuery.isLoading ? (
                    <tr>
                      <td colSpan={canManageAssignments ? 9 : 8} className="campaign-empty-state">
                        {bilingual(lang, "正在加载…", "Loading…")}
                      </td>
                    </tr>
                  ) : !(detail?.issues || []).length ? (
                    <tr>
                      <td colSpan={canManageAssignments ? 9 : 8} className="campaign-empty-state">
                        {bilingual(lang, "当前筛选没有 Issue。", "No Issues match these filters.")}
                      </td>
                    </tr>
                  ) : (
                    (detail?.issues || []).map((item) => {
                      const assignments = item.assignments || [];
                      const currentAssignees = assignments
                        .map((a) => String(a.assignee || "").trim())
                        .filter(Boolean);
                      const fromOptions: UiSelectOption[] = [
                        { value: "", label: bilingual(lang, "当前负责人", "Current assignee") },
                        ...currentAssignees.map((n) => ({ value: n, label: n })),
                      ];
                      const issueUrl = isLabelingDetail
                        ? getLegacyWindow().pageUrl?.("labeling", {
                            issue: item.issue_id,
                            taskId: campaign.id,
                            baselines: (campaign.baseline_scopes || []).map(
                              (s) => String(s).match(/^release(\d{4})/)?.[1] || s,
                            ),
                            search: "",
                            status: "all",
                            author: "",
                            assignee: "",
                            cluster: "",
                            label: "all",
                            exclusion: "all",
                            page: 1,
                          }) || withWorkbenchBase(`/case-labeling?issue=${encodeURIComponent(item.issue_id)}&task=${encodeURIComponent(campaign.id)}`)
                        : withWorkbenchBase(`/review?issue=${encodeURIComponent(item.issue_id)}`);
                      const labelTags = [
                        ...(item.tags || []).map((k) => ({
                          key: k,
                          label:
                            tagCatalogByKey.get(k)?.label ||
                            bilingual(lang, "未分类标签", "Unclassified tag"),
                        })),
                        ...(item.evidence_gaps || []).map((k) => ({
                          key: `gap:${k}`,
                          label: `${bilingual(lang, "缺证据", "Evidence gap")} · ${
                            getLegacyWindow().evidenceLabel?.(k) || k
                          }`,
                        })),
                      ];
                      const refLabel = item.reference_label || item.gt_label || "—";
                      return (
                        <tr key={item.issue_id}>
                          <td>
                            {campaign.lifecycle === "active" && !campaign.legacy_read_only ? (
                              <a href={issueUrl} className="campaign-row-name">
                                {item.issue_id}
                              </a>
                            ) : (
                              <span className="campaign-row-name">{item.issue_id}</span>
                            )}
                            <span className="campaign-reference-text">
                              {item.title || item.scenario || ""}
                            </span>
                            <button
                              className="analysis-discussion-link"
                              type="button"
                              onClick={() => {
                                getLegacyWindow()
                                  .openAnalysisDiscussion?.(item.issue_id, {
                                    source: "campaign",
                                    kind: "campaign",
                                    campaignId: campaign.id || campaignId,
                                    baselineScope: item.baseline_scope || "",
                                    discussionChannel: "both",
                                  })
                                  ?.catch((err: Error) =>
                                    getLegacyWindow().showToast?.(err.message, true),
                                  );
                              }}
                            >
                              {bilingual(lang, "讨论", "Discussion")}
                            </button>
                          </td>
                          <td>
                            {refLabel}
                            {item.reference_relation && item.reference_relation !== "unknown" ? (
                              <span className="campaign-reference-text">
                                {campaignLabel(item.reference_relation, lang)}
                              </span>
                            ) : null}
                          </td>
                          <td>{item.expected_output || "—"}</td>
                          <td>
                            {labelTags.length ? (
                              <div className="campaign-assignee-chips">
                                {labelTags.map((t) => (
                                  <span
                                    className="campaign-assignee-chip"
                                    key={t.key}
                                    title={t.key}
                                  >
                                    {t.label}
                                  </span>
                                ))}
                              </div>
                            ) : (
                              "—"
                            )}
                          </td>
                          <td>
                            {item.is_excluded
                              ? bilingual(lang, "提出排除", "Proposed exclusion")
                              : "—"}
                          </td>
                          <td>
                            <div className="campaign-assignee-chips">
                              {assignments.length
                                ? assignments.map((a, idx) => (
                                    <span
                                      className="campaign-assignee-chip"
                                      key={`${a.assignee}-${idx}`}
                                    >
                                      {a.assignee}
                                      {a.assignment_kind && a.assignment_kind !== "base"
                                        ? ` · ${a.assignment_kind}`
                                        : ""}
                                      {canManageAssignments ? (
                                        <button
                                          className="campaign-unassign-button"
                                          type="button"
                                          aria-label={bilingual(
                                            lang,
                                            `移除 ${a.assignee}`,
                                            `Remove ${a.assignee}`,
                                          )}
                                          onClick={() =>
                                            void mutateAssignment(item.issue_id, {
                                              action: "unassign",
                                              fromAssignee: a.assignee,
                                            })
                                          }
                                        >
                                          ×
                                        </button>
                                      ) : null}
                                    </span>
                                  ))
                                : "—"}
                            </div>
                          </td>
                          <td>
                            {fmtNum(item.submitted)} / {fmtNum(item.required_submitter_count)}
                          </td>
                          <td>
                            <span
                              className="campaign-state-badge"
                              data-state={item.state || ""}
                            >
                              {campaignLabel(item.state, lang)}
                            </span>
                          </td>
                          {canManageAssignments ? (
                            <td>
                              <div className="campaign-assignment-controls">
                                <div className="campaign-assignment-action">
                                  <UiSelect
                                    value={assignDrafts[item.issue_id] || ""}
                                    options={userSelectOptions}
                                    ariaLabel={bilingual(lang, "选择新负责人", "Choose new assignee")}
                                    onChange={(v) =>
                                      setAssignDrafts((prev) => ({ ...prev, [item.issue_id]: v }))
                                    }
                                  />
                                  <button
                                    className="button button-quiet"
                                    type="button"
                                    onClick={() => {
                                      const target = (assignDrafts[item.issue_id] || "").trim();
                                      if (!target) {
                                        getLegacyWindow().showToast?.(
                                          bilingual(lang, "请先选择负责人。", "Choose an assignee first."),
                                          true,
                                        );
                                        return;
                                      }
                                      void mutateAssignment(item.issue_id, {
                                        action: "assign",
                                        assignee: target,
                                      });
                                    }}
                                  >
                                    {bilingual(lang, "分配", "Assign")}
                                  </button>
                                </div>
                                {currentAssignees.length ? (
                                  <div className="campaign-assignment-action">
                                    <UiSelect
                                      value={reassignFromDrafts[item.issue_id] || ""}
                                      options={fromOptions}
                                      ariaLabel={bilingual(
                                        lang,
                                        "选择要转出的负责人",
                                        "Current assignee",
                                      )}
                                      onChange={(v) =>
                                        setReassignFromDrafts((prev) => ({
                                          ...prev,
                                          [item.issue_id]: v,
                                        }))
                                      }
                                    />
                                    <UiSelect
                                      value={reassignToDrafts[item.issue_id] || ""}
                                      options={reassignToOptions}
                                      ariaLabel={bilingual(lang, "选择转入负责人", "Reassign to")}
                                      onChange={(v) =>
                                        setReassignToDrafts((prev) => ({
                                          ...prev,
                                          [item.issue_id]: v,
                                        }))
                                      }
                                    />
                                    <button
                                      className="button button-quiet"
                                      type="button"
                                      onClick={() => {
                                        const from = (
                                          reassignFromDrafts[item.issue_id] || ""
                                        ).trim();
                                        const to = (reassignToDrafts[item.issue_id] || "").trim();
                                        if (!from || !to) {
                                          getLegacyWindow().showToast?.(
                                            bilingual(
                                              lang,
                                              "请选择原负责人和新负责人。",
                                              "Choose both current and new assignees.",
                                            ),
                                            true,
                                          );
                                          return;
                                        }
                                        setReassignModal({
                                          issueId: item.issue_id,
                                          fromAssignee: from,
                                          toAssignee: to,
                                          reason: "",
                                          busy: false,
                                        });
                                      }}
                                    >
                                      {bilingual(lang, "转派", "Reassign")}
                                    </button>
                                  </div>
                                ) : null}
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
              page={Number(detail?.page || issuePage)}
              pageSize={issuePageSize}
              total={Number(detail?.total || 0)}
              lang={lang}
              loading={detailQuery.isFetching}
              className="case-pagination gallery-pagination campaign-issue-pagination"
              showPageUnit
              keepControlsEnabledWhenEmpty
              labelText={`${detail?.page || issuePage} / ${Math.max(1, Number(detail?.page_count || 1))}`}
              ariaLabel={bilingual(lang, "Issue 明细分页", "Issue details pagination")}
              onPageChange={setIssuePage}
              onPageSizeChange={(next) => {
                setIssuePageSize(next);
                setIssuePage(1);
              }}
            />
          </section>

          <details className="campaign-audit-panel">
            <summary>{bilingual(lang, "配置与变更记录", "Configuration & change audit")}</summary>
            <details className="campaign-config-history">
              <summary>{bilingual(lang, "配置版本历史", "Configuration history")}</summary>
              <div className="table-scroll">
                <table className="campaigns-table">
                  <thead>
                    <tr>
                      <th>Revision</th>
                      <th>Change</th>
                      <th>Changed by</th>
                      <th>At</th>
                      <th>Config SHA-256</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!(detail?.revisions || []).length ? (
                      <tr>
                        <td colSpan={5} className="campaign-empty-state">
                          {bilingual(lang, "暂无配置版本。", "No configuration revisions.")}
                        </td>
                      </tr>
                    ) : (
                      (detail?.revisions || []).map((r, i) => (
                        <tr key={i}>
                          <td>{fmtNum(r.revision_no)}</td>
                          <td>{r.change_source || "—"}</td>
                          <td>
                            {r.changed_by || "—"}
                            {r.changed_by_verified ? " · SSO" : ""}
                          </td>
                          <td>{r.changed_at || ""}</td>
                          <td title={r.config_sha256 || ""}>
                            {r.config_sha256 ? `${String(r.config_sha256).slice(0, 16)}…` : "—"}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </details>

            <details className="campaign-config-history">
              <summary>{bilingual(lang, "生命周期审计", "Lifecycle audit")}</summary>
              <div className="table-scroll">
                <table className="campaigns-table">
                  <thead>
                    <tr>
                      <th>Action</th>
                      <th>Transition</th>
                      <th>Changed by</th>
                      <th>Revision</th>
                      <th>Reason</th>
                      <th>At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!(detail?.lifecycle_audit || []).length ? (
                      <tr>
                        <td colSpan={6} className="campaign-empty-state">
                          {bilingual(lang, "暂无生命周期变更。", "No lifecycle changes.")}
                        </td>
                      </tr>
                    ) : (
                      (detail?.lifecycle_audit || []).map((a, i) => (
                        <tr key={i}>
                          <td>{campaignLabel(a.action, lang)}</td>
                          <td>
                            {campaignLabel(a.from_lifecycle, lang)} →{" "}
                            {campaignLabel(a.to_lifecycle, lang)}
                          </td>
                          <td>
                            {a.changed_by || "—"}
                            {a.changed_by_verified ? " · SSO" : ""}
                          </td>
                          <td>{fmtNum(a.config_revision)}</td>
                          <td>{a.reason || "—"}</td>
                          <td>{a.changed_at || ""}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </details>

            <details className="campaign-config-history">
              <summary>{bilingual(lang, "分配转派审计", "Assignment audit")}</summary>
              <div className="table-scroll">
                <table className="campaigns-table">
                  <thead>
                    <tr>
                      <th>Action</th>
                      <th>Issue</th>
                      <th>Assignee</th>
                      <th>Changed by</th>
                      <th>Revision</th>
                      <th>Reason</th>
                      <th>At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {!(detail?.assignment_audit || []).length ? (
                      <tr>
                        <td colSpan={7} className="campaign-empty-state">
                          {bilingual(lang, "暂无分配变更。", "No assignment changes.")}
                        </td>
                      </tr>
                    ) : (
                      (detail?.assignment_audit || []).map((a, i) => {
                        const movement =
                          a.action === "assigned"
                            ? a.to_assignee
                            : a.action === "unassigned"
                              ? a.from_assignee
                              : `${a.from_assignee || "—"} → ${a.to_assignee || "—"}`;
                        return (
                          <tr key={i}>
                            <td>{campaignLabel(a.action, lang)}</td>
                            <td>{a.issue_id || ""}</td>
                            <td>{movement || "—"}</td>
                            <td>
                              {a.changed_by || "—"}
                              {a.changed_by_verified ? " · SSO" : ""}
                            </td>
                            <td>{fmtNum(a.config_revision)}</td>
                            <td>{a.reason || "—"}</td>
                            <td>{a.changed_at || ""}</td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </details>
          </details>
        </section>
      ) : null}

      {hasGroup ? (
        <section className="page-card campaign-group-view" id="campaignGroupView">
          {(() => {
            const g = groupQuery.data?.group || {};
            const children = groupQuery.data?.children || [];
            const detailsById = new Map(
              (groupQuery.data?.campaigns || []).map((item) => [
                String(item?.campaign?.id || ""),
                item,
              ]),
            );
            const runs = (g.source_run_ids || []).filter(Boolean).join(", ") || "—";
            return (
              <>
                <header className="campaign-detail-header">
                  <div>
                    <button
                      className="button button-quiet"
                      id="campaignGroupBack"
                      type="button"
                      onClick={() => {
                        const ret = groupReturnCampaignId;
                        setGroupId("");
                        setCampaignId(ret);
                        pushCampaignRoute({ groupId: "", campaignId: ret });
                      }}
                    >
                      ← {bilingual(lang, "返回", "Back")}
                    </button>
                    <h2 id="campaignGroupTitle">
                      {groupQuery.isLoading
                        ? bilingual(lang, "正在加载 Task Group…", "Loading Task Group…")
                        : g.name || g.id || "Task Group"}
                    </h2>
                    <p id="campaignGroupMeta">
                      {`${g.id || groupId} · ${campaignLabel(g.purpose, lang)} · ${campaignLabel(
                        g.lifecycle,
                        lang,
                      )} · Workset ${g.workset_id || "—"} · ${g.reference_type || "—"}: ${
                        g.reference_id || "—"
                      } · Runs ${runs}`}
                    </p>
                  </div>
                </header>
                <section className="campaign-issue-section">
                  <div className="campaign-issue-heading">
                    <h3>
                      {bilingual(
                        lang,
                        "子 Campaign 独立进度",
                        "Independent child Campaign progress",
                      )}
                    </h3>
                    <span id="campaignGroupChildCount">
                      {`${fmtNum(children.length)} ${bilingual(lang, "个子 Campaign", "child Campaigns")}`}
                    </span>
                  </div>
                  <div className="table-scroll">
                    <table className="campaigns-table">
                      <thead>
                        <tr>
                          <th>Model Run</th>
                          <th>{bilingual(lang, "实验", "Experiment")}</th>
                          <th>Purpose</th>
                          <th>Lifecycle</th>
                          <th>Issues</th>
                          <th>Required</th>
                          <th>Submitted / Completed</th>
                        </tr>
                      </thead>
                      <tbody id="campaignGroupRows">
                        {groupQuery.isLoading ? (
                          <tr>
                            <td colSpan={7} className="campaign-empty-state">
                              {bilingual(lang, "正在加载…", "Loading…")}
                            </td>
                          </tr>
                        ) : !children.length ? (
                          <tr>
                            <td colSpan={7} className="campaign-empty-state">
                              {bilingual(
                                lang,
                                "此 Group 没有子 Campaign。",
                                "This group has no child campaigns.",
                              )}
                            </td>
                          </tr>
                        ) : (
                          children.map((child) => {
                            const d = detailsById.get(String(child.campaign_id || "")) || {};
                            const c = d.campaign || ({} as CampaignSummaryItem);
                            const p = d.progress || ({} as CampaignProgress);
                            return (
                              <tr key={child.campaign_id}>
                                <td>{child.evaluation_run_id || "—"}</td>
                                <td>
                                  <button
                                    className="campaign-group-child-button"
                                    type="button"
                                    onClick={() => {
                                      setGroupId("");
                                      setGroupReturnCampaignId("");
                                      setCampaignId(child.campaign_id);
                                      pushCampaignRoute({
                                        groupId: "",
                                        campaignId: child.campaign_id,
                                      });
                                    }}
                                  >
                                    {c.name || child.campaign_id || "Campaign"}
                                  </button>
                                  <small className="campaign-row-id">{child.campaign_id || ""}</small>
                                </td>
                                <td>{campaignLabel(c.purpose, lang)}</td>
                                <td>
                                  <span
                                    className="campaign-lifecycle-badge"
                                    data-lifecycle={c.lifecycle || ""}
                                  >
                                    {campaignLabel(c.lifecycle, lang)}
                                  </span>
                                </td>
                                <td>{fmtNum(p.member_count)}</td>
                                <td>{fmtNum(p.required_submitter_count)}</td>
                                <td>
                                  {fmtNum(p.submitted_submitter_count)} /{" "}
                                  {fmtNum(p.required_submitter_count)} ·{" "}
                                  {fmtNum(p.completed_issue_count)}{" "}
                                  {bilingual(lang, "已完成", "completed")}
                                </td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>
              </>
            );
          })()}
        </section>
      ) : null}

      <AnalysisPieTooltip tooltip={pieTooltip.tooltip} tipRef={pieTooltip.tipRef} lang={lang} />

      <ModalDialog
        open={Boolean(lifecycleModal)}
        title={
          lifecycleModal
            ? bilingual(
                lang,
                ({
                  activate: "激活草稿",
                  close: "关闭实验",
                  reopen: "重新打开实验",
                  cancel: "取消实验",
                  supersede: "标记为替代",
                } as Record<string, string>)[lifecycleModal.action],
                ({
                  activate: "Activate draft",
                  close: "Close experiment",
                  reopen: "Reopen experiment",
                  cancel: "Cancel experiment",
                  supersede: "Supersede experiment",
                } as Record<string, string>)[lifecycleModal.action],
              )
            : ""
        }
        lang={lang}
        onClose={() => !lifecycleModal?.busy && setLifecycleModal(null)}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              disabled={lifecycleModal?.busy}
              onClick={() => setLifecycleModal(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={
                lifecycleModal?.busy ||
                (lifecycleModal?.action !== "close" && !lifecycleModal?.reason.trim())
              }
              onClick={() => void confirmLifecycleMutation()}
            >
              {bilingual(lang, "确认", "Confirm")}
            </button>
          </>
        }
      >
        {lifecycleModal ? (
          <div className="ra-camp-modal-body">
            {lifecycleModal.action === "close" ? (
              <p>
                {bilingual(
                  lang,
                  "关闭后将冻结成员和进度快照。继续关闭此 Campaign？",
                  "Closing freezes membership and progress. Close this Campaign?",
                )}
              </p>
            ) : (
              <>
                {lifecycleModal.action === "cancel" || lifecycleModal.action === "supersede" ? (
                  <p>
                    {lifecycleModal.action === "cancel"
                      ? bilingual(
                          lang,
                          "取消后 Campaign 将进入终态，不能重新激活。",
                          "Canceling is terminal and cannot be reactivated.",
                        )
                      : bilingual(
                          lang,
                          "替代后 Campaign 将进入终态，不能重新激活。",
                          "Superseding is terminal and cannot be reactivated.",
                        )}
                  </p>
                ) : null}
                <label className="ra-camp-reason-field">
                  <span>{bilingual(lang, "变更原因", "Reason")}</span>
                  <input
                    type="text"
                    value={lifecycleModal.reason}
                    placeholder={bilingual(lang, "填写原因", "Enter a reason")}
                    onChange={(e) =>
                      setLifecycleModal((prev) => (prev ? { ...prev, reason: e.target.value } : null))
                    }
                  />
                </label>
              </>
            )}
          </div>
        ) : null}
      </ModalDialog>

      <ModalDialog
        open={Boolean(reassignModal)}
        title={bilingual(lang, "确认转派", "Confirm reassignment")}
        lang={lang}
        onClose={() => !reassignModal?.busy && setReassignModal(null)}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              disabled={reassignModal?.busy}
              onClick={() => setReassignModal(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={reassignModal?.busy || !reassignModal?.reason.trim()}
              onClick={async () => {
                if (!reassignModal) return;
                setReassignModal({ ...reassignModal, busy: true });
                await mutateAssignment(reassignModal.issueId, {
                  action: "reassign",
                  fromAssignee: reassignModal.fromAssignee,
                  assignee: reassignModal.toAssignee,
                  reason: reassignModal.reason.trim(),
                });
                setReassignModal(null);
              }}
            >
              {bilingual(lang, "确认转派", "Confirm")}
            </button>
          </>
        }
      >
        {reassignModal ? (
          <div className="ra-camp-modal-body">
            <p>
              {bilingual(
                lang,
                `将 ${reassignModal.issueId} 从 ${reassignModal.fromAssignee} 转派给 ${reassignModal.toAssignee}：`,
                `Reassign ${reassignModal.issueId} from ${reassignModal.fromAssignee} to ${reassignModal.toAssignee}:`,
              )}
            </p>
            <label className="ra-camp-reason-field">
              <span>{bilingual(lang, "转派原因", "Reassignment reason")}</span>
              <input
                type="text"
                value={reassignModal.reason}
                placeholder={bilingual(lang, "填写转派原因", "Enter a reassignment reason")}
                onChange={(e) =>
                  setReassignModal((prev) => (prev ? { ...prev, reason: e.target.value } : null))
                }
              />
            </label>
          </div>
        ) : null}
      </ModalDialog>
    </div>
  );
};
