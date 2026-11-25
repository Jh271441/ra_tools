import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  formatCstTime,
  UiLanguage,
} from "../bridge/useWorkbenchBridge";
import { IssueDiscussion } from "../components/discussion/IssueDiscussion";
import {
  CaseMediaPayload,
  CaseMediaPreviewModal,
  MediaStage,
} from "../components/media/MediaStage";
import { ModalDialog } from "../components/ui/ModalDialog";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import {
  CASE_PAGE_SIZES,
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { UiSelect } from "../components/ui/UiSelect";
import { useShortcut } from "../core/shortcutManager";
import { RaEventModal, TrailMetadataPayload } from "../features/review/RaEventModal";
import {
  CORE_LABELS,
  DashboardConfigPayload,
  decisionStateLabel,
  displayLabelText,
  EXPECTED_OUTPUT_OPTIONS,
  inferExpectedOutputFromTags,
  isTouchDevice,
  labelBadgeClass,
  navigateWorkbenchPage,
  normalizeAssetUrl,
  parseIssueIdsInput,
  safeExternalUrl,
  showWorkbenchToast,
} from "../features/review/reviewHelpers";
import { ReviewTagSelector } from "../features/review/ReviewTagSelector";

export interface CaseLabelingPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
  username: string;
  canWrite: boolean;
  isAdmin: boolean;
}

interface LabelingTaskSummary {
  id: string;
  name?: string;
  workset_id?: string;
  baseline_scope?: string;
  baseline_scopes?: string[];
  member_count?: number;
  progress?: {
    total?: number;
    resolved?: number;
    conflict?: number;
    assignees?: { name: string; labeled: number; total: number }[];
  };
}

interface LabelingGalleryItem {
  issue_id: string;
  gt_label?: string;
  expected_output?: string;
  label_state?: string;
  is_excluded?: boolean;
  author?: string;
  author_verified?: boolean;
  thumbnail_url?: string;
  thumbnail?: { url?: string; label?: string };
  voyager_issue_url?: string;
  evidence_gaps?: string[];
  label_cases?: {
    task_id?: string;
    resolution?: {
      state?: string;
      method?: string;
      heads?: LabelRevision[];
      result_revision?: LabelRevision;
    };
  }[];
  decision?: {
    full_result?: boolean;
    stale?: boolean;
    tags?: string[];
  };
}

interface LabelRevision {
  id: number;
  author?: string;
  author_verified?: boolean;
  expected_output?: string;
  tags?: string[];
  evidence_gaps?: string[];
  rationale?: string;
  is_excluded?: boolean;
  created_at?: string;
  attachments?: { id: string; url?: string }[];
}

interface LabelingListPayload {
  items?: LabelingGalleryItem[];
  total?: number;
  page?: number;
  pages?: number;
  page_size?: number;
  queue_issue_ids?: string[];
  labelers?: string[];
  assignees?: string[];
}

interface LabelingDetailPayload {
  issue_id: string;
  summary?: string;
  gt_label?: string;
  voyager_issue_url?: string;
  trail_url?: string;
  current_user_is_task_member?: boolean;
  allocation_revision?: number | null;
  comments?: { id: number }[];
  label_state?: {
    state?: string;
    expected_output?: string;
    fingerprint?: string;
    decision?: {
      id?: number;
      expected_output?: string;
      tags?: string[];
      rationale?: string;
      label_rationale?: string;
      is_excluded?: boolean;
      stale?: boolean;
      full_result?: boolean;
      created_by?: string;
      created_at?: string;
    };
  };
  label_cases?: {
    id?: string;
    task_id?: string;
    source_run_id?: string;
    task_name?: string;
    revisions?: LabelRevision[];
    resolution?: {
      state?: string;
      method?: string;
      heads?: LabelRevision[];
      result_revision?: LabelRevision;
    };
  }[];
  decision_history?: {
    id: number;
    expected_output?: string;
    rationale?: string;
    label_rationale?: string;
    is_excluded?: boolean;
    created_by?: string;
    created_at?: string;
  }[];
}

interface PendingAttachment {
  id: string;
  file: File;
  previewUrl: string;
}

export const CaseLabelingPage: React.FC<CaseLabelingPageProps> = ({
  active,
  lang,
  selectedBaselines,
  username,
  canWrite,
  isAdmin,
}) => {
  const queryClient = useQueryClient();
  const initialParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const baselinesKey = selectedBaselines.join(",");

  // Gallery filter state
  const [selectedIssueId, setSelectedIssueId] = useState(initialParams.get("issue") || "");
  const [taskId, setTaskId] = useState(initialParams.get("task") || "");
  const [searchText, setSearchText] = useState(initialParams.get("q") || "");
  const [issueIds, setIssueIds] = useState<string[]>(() =>
    (initialParams.get("issue_ids") || "").split(",").filter(Boolean),
  );
  const [statuses, setStatuses] = useState<string[]>(() =>
    (initialParams.get("status") || "").split(",").filter(Boolean),
  );
  const [issueTags, setIssueTags] = useState<string[]>(() =>
    (initialParams.get("issue_tags") || "").split(",").filter(Boolean),
  );
  const [authors, setAuthors] = useState<string[]>(() =>
    (initialParams.get("author") || "").split(",").filter(Boolean),
  );
  const [assignees, setAssignees] = useState<string[]>(() =>
    (initialParams.get("assignee") || "").split(",").filter(Boolean),
  );
  const [gts, setGts] = useState<string[]>(() =>
    (initialParams.get("gt") || "").split(",").filter(Boolean),
  );
  const [gtRelations, setGtRelations] = useState<string[]>(() =>
    (initialParams.get("gt_relation") || "").split(",").filter(Boolean),
  );
  const [labels, setLabels] = useState<string[]>(() =>
    (initialParams.get("label") || "").split(",").filter(Boolean),
  );
  const [commentStates, setCommentStates] = useState<string[]>(() =>
    (initialParams.get("comment_state") || "").split(",").filter(Boolean),
  );
  const [exclusions, setExclusions] = useState<string[]>(() =>
    (initialParams.get("exclusion") || "").split(",").filter(Boolean),
  );
  const [targetGroup, setTargetGroup] = useState(initialParams.get("target_group") || "");
  const [page, setPage] = useState(Math.max(1, Number(initialParams.get("page")) || 1));
  const [pageSize, setPageSize] = useState(
    CASE_PAGE_SIZES.includes(Number(initialParams.get("page_size")) as 10 | 20 | 50 | 100)
      ? Number(initialParams.get("page_size"))
      : DEFAULT_CASE_PAGE_SIZE,
  );
  const [filtersOpenMobile, setFiltersOpenMobile] = useState(false);
  const [multiIssueModalOpen, setMultiIssueModalOpen] = useState(false);
  const [multiIssueDraft, setMultiIssueDraft] = useState("");
  const [previewMediaIssueId, setPreviewMediaIssueId] = useState<string | null>(null);

  // Detail & Editor state
  const [sceneDescOpen, setSceneDescOpen] = useState(false);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [expectedOutput, setExpectedOutput] = useState("");
  const [manualOutput, setManualOutput] = useState(false);
  const [isExcluded, setIsExcluded] = useState(false);
  const [rationale, setRationale] = useState("");
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [discussionOpen, setDiscussionOpen] = useState(false);
  const [discussionCount, setDiscussionCount] = useState<number>(0);
  const [decisionModalOpen, setDecisionModalOpen] = useState(false);
  const [decisionMode, setDecisionMode] = useState<{ adoptedRevisionId: number | null } | null>(null);
  const [decisionReviewRationale, setDecisionReviewRationale] = useState("");
  const [decisionConfirmExclusion, setDecisionConfirmExclusion] = useState(false);
  const [raEventOpen, setRaEventOpen] = useState(false);
  const [queueJumpInput, setQueueJumpInput] = useState("");
  const [exportingCsv, setExportingCsv] = useState(false);

  const rationaleRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const mediaAnchorRef = useRef<HTMLDivElement | null>(null);
  const editorAnchorRef = useRef<HTMLDivElement | null>(null);

  // Respond to URL popstate (e.g. clicking an external /case-labeling?issue= link)
  useEffect(() => {
    if (!active) return;
    const syncFromUrl = () => {
      const p = new URLSearchParams(window.location.search);
      setSelectedIssueId(p.get("issue") || "");
      const t = p.get("task");
      if (t !== null) setTaskId(t);
    };
    window.addEventListener("popstate", syncFromUrl);
    return () => window.removeEventListener("popstate", syncFromUrl);
  }, [active]);

  // Persist URL query params
  useEffect(() => {
    if (!active) return;
    const url = new URL(window.location.href);
    const setOrDel = (k: string, v: string) => {
      if (v) url.searchParams.set(k, v);
      else url.searchParams.delete(k);
    };
    setOrDel("baselines", baselinesKey);
    setOrDel("issue", selectedIssueId);
    setOrDel("task", taskId);
    setOrDel("q", searchText.trim());
    setOrDel("issue_ids", issueIds.join(","));
    setOrDel("status", statuses.join(","));
    setOrDel("issue_tags", issueTags.join(","));
    setOrDel("author", authors.join(","));
    setOrDel("assignee", assignees.join(","));
    setOrDel("gt", gts.join(","));
    setOrDel("gt_relation", gtRelations.join(","));
    setOrDel("label", labels.join(","));
    setOrDel("comment_state", commentStates.join(","));
    setOrDel("exclusion", exclusions.join(","));
    setOrDel("target_group", targetGroup);
    url.searchParams.set("page", String(page));
    url.searchParams.set("page_size", String(pageSize));
    window.history.replaceState(window.history.state, "", url.pathname + url.search);
  }, [
    active,
    baselinesKey,
    selectedIssueId,
    taskId,
    searchText,
    issueIds,
    statuses,
    issueTags,
    authors,
    assignees,
    gts,
    gtRelations,
    labels,
    commentStates,
    exclusions,
    targetGroup,
    page,
    pageSize,
  ]);

  const configQuery = useQuery<DashboardConfigPayload>({
    queryKey: ["dashboard-config"],
    queryFn: ({ signal }) => apiRequest<DashboardConfigPayload>("/api/dashboard-config", { signal }),
    enabled: active,
    staleTime: 60_000,
  });

  const activeLabelingBaselines = useMemo(
    () => configQuery.data?.case_labeling?.active_baseline_ids || [],
    [configQuery.data],
  );
  const isBaselineInactive =
    activeLabelingBaselines.length > 0 &&
    selectedBaselines.length > 0 &&
    !selectedBaselines.some((id) => activeLabelingBaselines.includes(id));

  const tasksQuery = useQuery<{ items?: LabelingTaskSummary[] }>({
    queryKey: ["labeling-tasks", baselinesKey],
    queryFn: ({ signal }) =>
      apiRequest<{ items?: LabelingTaskSummary[] }>(
        `/api/labeling/tasks${baselinesKey ? `?baselines=${encodeURIComponent(baselinesKey)}` : ""}`,
        { signal },
      ),
    enabled: active,
    staleTime: 20_000,
  });

  const listParams = useMemo(() => {
    const qs = new URLSearchParams({
      baselines: baselinesKey,
      task_id: taskId,
      q: searchText.trim(),
      issue_ids: issueIds.join(","),
      target_group: targetGroup,
      issue_tags: issueTags.join(","),
      status: statuses.join(","),
      author: authors.join(","),
      assignee: assignees.join(","),
      exclusion: exclusions.join(","),
      label: labels.join(","),
      gt: gts.join(","),
      gt_relation: gtRelations.join(","),
      comment_state: commentStates.join(","),
      page: String(page),
      page_size: String(pageSize),
    });
    return qs.toString();
  }, [
    baselinesKey,
    taskId,
    searchText,
    issueIds,
    targetGroup,
    issueTags,
    statuses,
    authors,
    assignees,
    exclusions,
    labels,
    gts,
    gtRelations,
    commentStates,
    page,
    pageSize,
  ]);

  const listQuery = useQuery<LabelingListPayload>({
    queryKey: ["labeling-cases", listParams],
    queryFn: ({ signal }) =>
      apiRequest<LabelingListPayload>(`/api/labeling/cases?${listParams}`, { signal }),
    enabled: active && !isBaselineInactive,
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  });

  const detailQuery = useQuery<LabelingDetailPayload>({
    queryKey: ["labeling-case-detail", selectedIssueId, baselinesKey, taskId],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams();
      if (baselinesKey) qs.set("baselines", baselinesKey);
      if (taskId) qs.set("task_id", taskId);
      return apiRequest<LabelingDetailPayload>(
        `/api/labeling/cases/${encodeURIComponent(selectedIssueId)}?${qs.toString()}`,
        { signal },
      );
    },
    enabled: active && Boolean(selectedIssueId),
    staleTime: 5_000,
  });

  const mediaQuery = useQuery<CaseMediaPayload>({
    queryKey: ["case-media", selectedIssueId],
    queryFn: ({ signal }) =>
      apiRequest<CaseMediaPayload>(`/api/cases/${encodeURIComponent(selectedIssueId)}/media`, {
        signal,
      }),
    enabled: active && Boolean(selectedIssueId),
    staleTime: 60_000,
  });

  const trailMetadataQuery = useQuery<TrailMetadataPayload>({
    queryKey: ["case-trail-metadata", selectedIssueId],
    queryFn: ({ signal }) =>
      apiRequest<TrailMetadataPayload>(
        `/api/cases/${encodeURIComponent(selectedIssueId)}/trail-metadata`,
        { signal },
      ),
    enabled: active && Boolean(selectedIssueId),
    staleTime: 60_000,
  });

  const tagCatalog = configQuery.data?.review_tag_catalog || [];
  const detail = detailQuery.data;

  // Hydrate editor form when detail loads
  useEffect(() => {
    if (!detail) return;
    setDecisionMode(null);
    setDecisionReviewRationale("");
    setDecisionConfirmExclusion(false);
    setDiscussionCount((detail.comments || []).length);
    setPendingAttachments((prev) => {
      prev.forEach((p) => URL.revokeObjectURL(p.previewUrl));
      return [];
    });

    const cases = detail.label_cases || [];
    const editableCase =
      taskId && detail.current_user_is_task_member
        ? cases.find((c) => c.task_id === taskId)
        : cases.find((c) => !c.task_id && !c.source_run_id);
    const ownRev = (editableCase?.resolution?.heads || []).find(
      (h) => String(h.author || "").toLowerCase() === username.toLowerCase(),
    );
    const validDecision =
      detail.label_state?.decision && !detail.label_state.decision.stale
        ? detail.label_state.decision
        : null;
    const aggResolved = cases.find((c) => c.resolution?.state === "resolved")?.resolution?.result_revision;
    const src = ownRev || validDecision || aggResolved;

    setSelectedTags(src?.tags || []);
    const out = String(src?.expected_output || "");
    setExpectedOutput(out);
    setManualOutput(Boolean(out));
    setIsExcluded(Boolean(src?.is_excluded));
    setRationale(String((src as { label_rationale?: string; rationale?: string })?.label_rationale || src?.rationale || ""));
  }, [detail, taskId, username]);

  // Tag inference
  const tagInference = useMemo(
    () => inferExpectedOutputFromTags(selectedTags, tagCatalog),
    [selectedTags, tagCatalog],
  );

  useEffect(() => {
    if (!manualOutput) {
      setExpectedOutput(tagInference.value);
    }
  }, [tagInference.value, manualOutput]);

  const outputConflict =
    tagInference.conflict ||
    Boolean(tagInference.value && expectedOutput && tagInference.value !== expectedOutput);

  const queueIds = useMemo(() => {
    const raw = listQuery.data?.queue_issue_ids;
    if (Array.isArray(raw) && raw.length) return raw;
    return (listQuery.data?.items || []).map((i) => i.issue_id);
  }, [listQuery.data]);

  const currentQueueIdx = queueIds.indexOf(selectedIssueId);
  useEffect(() => {
    setQueueJumpInput(currentQueueIdx >= 0 ? String(currentQueueIdx + 1) : "");
  }, [currentQueueIdx]);

  const navigateQueue = useCallback(
    (delta: -1 | 1) => {
      if (currentQueueIdx < 0) return;
      const target = queueIds[currentQueueIdx + delta];
      if (target) setSelectedIssueId(target);
    },
    [currentQueueIdx, queueIds],
  );

  // Save revision or adjudication decision
  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!detail) throw new Error("Case not loaded");
      if (outputConflict) {
        throw new Error(bilingual(lang, "期望输出与所选标签冲突，请先修正。", "Output conflicts with selected tags."));
      }
      if (decisionMode) {
        if (!decisionConfirmExclusion) {
          throw new Error(
            bilingual(lang, "请勾选确认“是否排除”后再提交裁决。", "Confirm exclusion choice before submitting decision."),
          );
        }
        return apiRequest(`/api/labeling/cases/${encodeURIComponent(detail.issue_id)}/decisions`, {
          method: "POST",
          body: {
            expected_output: expectedOutput,
            tags: selectedTags,
            evidence_gaps: [],
            label_rationale: rationale,
            rationale: decisionReviewRationale,
            is_excluded: isExcluded,
            adopted_revision_id: decisionMode.adoptedRevisionId,
            expected_label_state_fingerprint: detail.label_state?.fingerprint || "",
          },
        });
      }

      const submissionTaskId = taskId && detail.current_user_is_task_member ? taskId : "";
      const cases = detail.label_cases || [];
      const editableCase = submissionTaskId
        ? cases.find((c) => c.task_id === submissionTaskId)
        : cases.find((c) => !c.task_id && !c.source_run_id);
      const ownRev = (editableCase?.resolution?.heads || []).find(
        (h) => String(h.author || "").toLowerCase() === username.toLowerCase(),
      );

      const payload = {
        task_id: submissionTaskId,
        expected_output: expectedOutput,
        tags: selectedTags,
        evidence_gaps: [],
        rationale,
        is_excluded: isExcluded,
        expected_previous_revision_id: ownRev?.id ?? null,
        expected_allocation_revision: detail.allocation_revision ?? null,
      };

      if (pendingAttachments.length > 0) {
        const form = new FormData();
        form.append("payload", JSON.stringify(payload));
        pendingAttachments.forEach((att) => form.append("attachments", att.file, att.file.name));
        return apiRequest(
          `/api/labeling/cases/${encodeURIComponent(detail.issue_id)}/revisions-with-attachments`,
          {
            method: "POST",
            body: form,
            headers: { "X-RA-Triage-Request": "labeling-v1" },
          },
        );
      }

      return apiRequest(`/api/labeling/cases/${encodeURIComponent(detail.issue_id)}/revisions`, {
        method: "POST",
        body: payload,
      });
    },
    onSuccess: () => {
      pendingAttachments.forEach((p) => URL.revokeObjectURL(p.previewUrl));
      setPendingAttachments([]);
      setDecisionMode(null);
      showWorkbenchToast(
        decisionMode
          ? bilingual(lang, "裁决已保存。", "Decision saved.")
          : bilingual(lang, "标注已保存。", "Label saved."),
      );
      void queryClient.invalidateQueries({ queryKey: ["labeling-case-detail", selectedIssueId] });
      void queryClient.invalidateQueries({ queryKey: ["labeling-cases"] });
    },
    onError: (err) => {
      showWorkbenchToast(
        err instanceof Error ? err.message : bilingual(lang, "保存失败。", "Save failed."),
        true,
      );
    },
  });

  const saveSnapshotMutation = useMutation({
    mutationFn: async () => {
      const task = (tasksQuery.data?.items || []).find((t) => t.id === taskId);
      if (!task?.workset_id) throw new Error(bilingual(lang, "请先选择冻结标注任务。", "Select a task first."));
      const scopes = Array.from(
        new Set(
          (Array.isArray(task.baseline_scopes) ? task.baseline_scopes : [task.baseline_scope]).filter(
            Boolean,
          ),
        ),
      );
      return apiRequest("/api/labeling/label-result-snapshots", {
        method: "POST",
        body: {
          workset_id: task.workset_id,
          allow_partial: false,
          ...(scopes.length > 1 ? { baseline_scopes: scopes } : {}),
        },
      });
    },
    onSuccess: () => showWorkbenchToast(bilingual(lang, "Label 快照已保存。", "Label snapshot saved.")),
    onError: (err) =>
      showWorkbenchToast(err instanceof Error ? err.message : "Snapshot failed", true),
  });

  // Keyboard shortcuts when detail view is open
  const detailShortcutsEnabled = active && Boolean(selectedIssueId);
  useShortcut(
    "page",
    "[",
    (e) => {
      e.preventDefault();
      navigateQueue(-1);
      return true;
    },
    { enabled: detailShortcutsEnabled },
  );
  useShortcut(
    "page",
    "]",
    (e) => {
      e.preventDefault();
      navigateQueue(1);
      return true;
    },
    { enabled: detailShortcutsEnabled },
  );
  useShortcut(
    "page",
    "d",
    (e) => {
      e.preventDefault();
      setDiscussionOpen((prev) => !prev);
      return true;
    },
    { enabled: detailShortcutsEnabled },
  );
  useShortcut(
    "page",
    "j",
    (e) => {
      e.preventDefault();
      setDecisionModalOpen((prev) => !prev);
      return true;
    },
    { enabled: detailShortcutsEnabled },
  );
  useShortcut(
    "page",
    "t",
    (e) => {
      e.preventDefault();
      setRaEventOpen((prev) => !prev);
      return true;
    },
    { enabled: detailShortcutsEnabled },
  );
  useShortcut(
    "page",
    "k",
    (e) => {
      if (!canWrite) return false;
      e.preventDefault();
      setIsExcluded((prev) => !prev);
      return true;
    },
    { enabled: detailShortcutsEnabled },
  );
  useShortcut(
    "page",
    "e",
    (e) => {
      e.preventDefault();
      rationaleRef.current?.focus();
      return true;
    },
    { enabled: detailShortcutsEnabled },
  );

  const addAttachments = (files: FileList | File[]) => {
    const allowed = new Set(["image/png", "image/jpeg", "image/webp"]);
    const next = [...pendingAttachments];
    for (const file of Array.from(files)) {
      if (next.length >= 4) {
        showWorkbenchToast(bilingual(lang, "标注截图最多 4 张。", "Up to 4 screenshots."), true);
        break;
      }
      if (!allowed.has(file.type) || file.size > 8 * 1024 * 1024) continue;
      next.push({
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        file,
        previewUrl: URL.createObjectURL(file),
      });
    }
    setPendingAttachments(next);
  };

  const handleExportIssuesCsv = async () => {
    if (exportingCsv) return;
    setExportingCsv(true);
    try {
      const qs = new URLSearchParams(listParams);
      qs.set("page", "1");
      qs.set("page_size", "10");
      const res = await apiRequest<LabelingListPayload>(`/api/labeling/cases?${qs.toString()}`);
      const ids = Array.from(
        new Set(
          (Array.isArray(res.queue_issue_ids)
            ? res.queue_issue_ids
            : (res.items || []).map((i) => i.issue_id)
          ).filter(Boolean),
        ),
      );
      if (!ids.length) {
        showWorkbenchToast(bilingual(lang, "当前筛选没有可导出的 Issue。", "No issues to export."));
        return;
      }
      const csv =
        "\ufeffissue_id\r\n" +
        ids.map((id) => `"${String(id).replaceAll('"', '""')}"`).join("\r\n") +
        "\r\n";
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `labeling-issues-${ids.length}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      showWorkbenchToast(bilingual(lang, `已导出 ${ids.length} 个 Issue。`, `Exported ${ids.length} issues.`));
    } catch (err) {
      showWorkbenchToast(err instanceof Error ? err.message : "Export failed", true);
    } finally {
      setExportingCsv(false);
    }
  };

  const resetFilters = () => {
    setTaskId("");
    setSearchText("");
    setIssueIds([]);
    setStatuses([]);
    setIssueTags([]);
    setAuthors([]);
    setAssignees([]);
    setGts([]);
    setGtRelations([]);
    setLabels([]);
    setCommentStates([]);
    setExclusions([]);
    setTargetGroup("");
    setPage(1);
  };

  if (!active) return null;

  const selectedTask = (tasksQuery.data?.items || []).find((t) => t.id === taskId) || null;
  const taskOptions = [
    { value: "", label: bilingual(lang, "全部标注", "All annotations") },
    ...(tasksQuery.data?.items || []).map((t) => {
      const tot = Number(t.progress?.total || t.member_count || 0);
      const res = Number(t.progress?.resolved || 0);
      return { value: t.id, label: `${t.name || t.id} · ${res}/${tot}` };
    }),
  ];

  const allRevisions = (detail?.label_cases || []).flatMap((lc) =>
    (lc.revisions || lc.resolution?.heads || []).map((r) => ({
      ...r,
      sourceName: lc.task_name || (lc.task_id ? `Task ${lc.task_id}` : bilingual(lang, "自由标注", "Independent")),
    })),
  );

  // DETAIL VIEW
  if (selectedIssueId) {
    const extLinks = trailMetadataQuery.data?.external_links || {};
    const voyagerHref = safeExternalUrl(detail?.voyager_issue_url || detail?.trail_url || extLinks.voyager_issue_url);
    const aresHref = safeExternalUrl(extLinks.ares_studio);
    const raRecHref = safeExternalUrl(extLinks.ra_recording);
    const raEventCount = (trailMetadataQuery.data?.ra_events || trailMetadataQuery.data?.events || []).length;
    const supplementalOnly = Boolean(taskId && detail && !detail.current_user_is_task_member);

    return (
      <div className="review-detail-view case-labeling-detail ra-labeling-detail-root">
        <nav className="mobile-workspace-jumps" aria-label={bilingual(lang, "详情区域", "Detail sections")}>
          <button
            type="button"
            className="button button-quiet"
            onClick={() => mediaAnchorRef.current?.scrollIntoView({ behavior: "smooth" })}
          >
            {bilingual(lang, "查看媒体", "Media")}
          </button>
          <button
            type="button"
            className="button button-quiet"
            onClick={() => editorAnchorRef.current?.scrollIntoView({ behavior: "smooth" })}
          >
            {bilingual(lang, "填写标注", "Annotate")}
          </button>
        </nav>

        <section className="review-detail-workspace ra-split-workspace">
          <section ref={mediaAnchorRef} className="detail-pane">
            <div className="detail-header">
              <div className="detail-title-row">
                <div className="detail-title-group">
                  <div className="detail-title">
                    <h2>{bilingual(lang, "问题详情", "Issue Details")}</h2>
                    {voyagerHref ? (
                      <a className="detail-id detail-id-link" href={voyagerHref} target="_blank" rel="noreferrer">
                        {selectedIssueId}
                      </a>
                    ) : (
                      <span className="detail-id">{selectedIssueId}</span>
                    )}
                    <button
                      type="button"
                      className="button button-quiet"
                      onClick={() => {
                        void navigator.clipboard
                          ?.writeText(selectedIssueId)
                          .then(() => showWorkbenchToast(bilingual(lang, "已复制 Issue ID。", "Issue ID copied.")));
                      }}
                    >
                      {bilingual(lang, "复制", "Copy")}
                    </button>
                    <span className="detail-external-links">
                      {aresHref && (
                        <a className="text-link" href={aresHref} target="_blank" rel="noreferrer">
                          Ares Studio ↗
                        </a>
                      )}
                      {raRecHref && (
                        <a className="text-link" href={raRecHref} target="_blank" rel="noreferrer">
                          {bilingual(lang, "RA 录屏 ↗", "RA recording ↗")}
                        </a>
                      )}
                      <button
                        type="button"
                        className="text-link"
                        onClick={() => setRaEventOpen(true)}
                      >
                        RA Event · {raEventCount} <kbd className="review-control-shortcut">T</kbd>
                      </button>
                    </span>
                  </div>
                </div>

                <div className="detail-navigation">
                  <div className="case-detail-pager">
                    <button
                      type="button"
                      className="button button-quiet"
                      disabled={currentQueueIdx <= 0}
                      onClick={() => navigateQueue(-1)}
                    >
                      {bilingual(lang, "← 上一 Issue", "← Prev")}{" "}
                      <kbd className="review-control-shortcut">[</kbd>
                    </button>
                    <span className="detail-queue-position">
                      <input
                        className="detail-queue-index-input"
                        type="number"
                        min={1}
                        max={queueIds.length || 1}
                        value={queueJumpInput}
                        disabled={queueIds.length === 0}
                        aria-label={bilingual(lang, "跳转到筛选队列序号", "Jump to queue index")}
                        onChange={(e) => setQueueJumpInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            const idx = Number(queueJumpInput) - 1;
                            if (Number.isInteger(idx) && queueIds[idx]) {
                              setSelectedIssueId(queueIds[idx]);
                            }
                          }
                        }}
                      />
                      <span className="detail-queue-total">/ {queueIds.length || "—"}</span>
                    </span>
                    <button
                      type="button"
                      className="button button-quiet"
                      disabled={currentQueueIdx < 0 || currentQueueIdx >= queueIds.length - 1}
                      onClick={() => navigateQueue(1)}
                    >
                      {bilingual(lang, "下一 Issue →", "Next →")}{" "}
                      <kbd className="review-control-shortcut">]</kbd>
                    </button>
                  </div>
                </div>
              </div>

              <div className="detail-context-row">
                <div className="comparison-summary">
                  <span className="comparison-side-label comparison-side-gt">GT</span>
                  <span className={labelBadgeClass(detail?.gt_label)}>
                    {displayLabelText(detail?.gt_label, lang)}
                  </span>
                </div>
                <button
                  type="button"
                  className="button button-quiet detail-back-button"
                  onClick={() => setSelectedIssueId("")}
                >
                  {bilingual(lang, "← 返回筛选结果", "← Back to gallery")}
                </button>
                {detail?.summary && (
                  <button
                    type="button"
                    className="history-inline-button"
                    aria-expanded={sceneDescOpen}
                    onClick={() => setSceneDescOpen((o) => !o)}
                  >
                    {sceneDescOpen ? "▾ " : "▸ "}
                    {bilingual(lang, "场景描述", "Scene description")}
                  </button>
                )}
              </div>

              {detail?.summary && sceneDescOpen && (
                <p className="case-scene-description">{detail.summary}</p>
              )}
            </div>

            <MediaStage
              issueId={selectedIssueId}
              media={mediaQuery.data || null}
              loading={mediaQuery.isPending}
              error={mediaQuery.isError ? String((mediaQuery.error as Error)?.message || "Media error") : null}
              lang={lang}
              active={active && Boolean(selectedIssueId)}
              onRetryMedia={() => void mediaQuery.refetch()}
            />
          </section>

          <aside ref={editorAnchorRef} className="review-pane">
            <form
              className="review-form"
              onSubmit={(e) => {
                e.preventDefault();
                saveMutation.mutate();
              }}
            >
              {decisionMode && (
                <section className="case-decision-mode">
                  <div className="review-section-heading">
                    <h2>{bilingual(lang, "裁决模式", "Decision mode")}</h2>
                    <button
                      type="button"
                      className="history-inline-button"
                      onClick={() => setDecisionMode(null)}
                    >
                      {bilingual(lang, "退出裁决", "Exit decision mode")}
                    </button>
                  </div>
                  <p className="quiet-meta">
                    {decisionMode.adoptedRevisionId
                      ? bilingual(
                          lang,
                          `采纳版本 #${decisionMode.adoptedRevisionId}`,
                          `Adopting revision #${decisionMode.adoptedRevisionId}`,
                        )
                      : bilingual(lang, "重新标注并确认完整 Issue 结果", "Relabel and confirm final Issue result")}
                  </p>
                </section>
              )}

              {supplementalOnly && !decisionMode && (
                <div className="case-labeling-supplemental-notice" role="status">
                  <strong>{bilingual(lang, "任务外补充标注", "Supplemental annotation")}</strong>
                  <span>
                    {bilingual(
                      lang,
                      "你未分配到当前任务，本次保存作为独立共享标注，不计入任务进度。",
                      "You are not assigned to this task; saved as a shared independent vote.",
                    )}
                  </span>
                </div>
              )}

              <section className="review-section issue-tag-section">
                <div className="review-section-heading">
                  <h2>{bilingual(lang, "Issue 标签", "Issue tags")}</h2>
                  <button
                    type="button"
                    className="history-inline-button"
                    onClick={() => setDecisionModalOpen(true)}
                  >
                    <span className="case-label-status">
                      {detail?.label_state?.state === "resolved" && detail.label_state.expected_output
                        ? displayLabelText(detail.label_state.expected_output, lang)
                        : decisionStateLabel(detail?.label_state?.state, lang)}
                    </span>
                  </button>
                </div>

                <ReviewTagSelector
                  catalog={tagCatalog}
                  selectedTags={selectedTags}
                  onChange={setSelectedTags}
                  lang={lang}
                  disabled={!canWrite}
                  canCreateCustom={canWrite}
                  onCatalogRefresh={() => void queryClient.invalidateQueries({ queryKey: ["dashboard-config"] })}
                />

                <label className="review-exclude-toggle">
                  <input
                    type="checkbox"
                    checked={isExcluded}
                    disabled={!canWrite}
                    onChange={(e) => setIsExcluded(e.target.checked)}
                  />
                  <span>{bilingual(lang, "排除此 Issue", "Exclude this Issue")}</span>
                  <kbd className="review-control-shortcut" aria-hidden="true">K</kbd>
                </label>
              </section>

              <section className="review-section model-error-section">
                <div className="review-section-heading">
                  <h2>{bilingual(lang, "问题标注", "Case labeling")}</h2>
                  <div className="review-heading-actions">
                    <button
                      type="button"
                      className="history-inline-button"
                      onClick={() => setDiscussionOpen(true)}
                    >
                      {bilingual(lang, "讨论", "Discuss")}
                      {discussionCount > 0 ? ` · ${discussionCount}` : ""}{" "}
                      <kbd className="review-control-shortcut">D</kbd>
                    </button>
                    <button
                      type="button"
                      className="history-inline-button"
                      onClick={() => setDecisionModalOpen(true)}
                    >
                      {bilingual(lang, "历史", "History")} · {allRevisions.length}{" "}
                      <kbd className="review-control-shortcut">J</kbd>
                    </button>
                  </div>
                </div>

                <div className="review-expected-output-field">
                  <div className="review-expected-output-heading">
                    <span>{bilingual(lang, "期望输出", "Expected output")}</span>
                    <span className={`derived-review-status${outputConflict ? " is-conflict" : ""}`}>
                      {outputConflict
                        ? bilingual(lang, "标签冲突", "Conflicting tags")
                        : !expectedOutput
                          ? bilingual(lang, "待补充", "Incomplete")
                          : expectedOutput === detail?.gt_label
                            ? bilingual(lang, "与 GT 一致", "Matches GT")
                            : bilingual(lang, "GT 待复核", "GT needs review")}
                    </span>
                  </div>
                  <UiSelect
                    value={expectedOutput}
                    options={EXPECTED_OUTPUT_OPTIONS.map((o) => ({
                      value: o.value,
                      label: bilingual(lang, o.zh, o.en),
                    }))}
                    disabled={!canWrite}
                    ariaLabel={bilingual(lang, "期望输出", "Expected output")}
                    onChange={(val) => {
                      setExpectedOutput(val);
                      setManualOutput(Boolean(val));
                    }}
                  />
                  {outputConflict && (
                    <small className="case-labeling-output-hint">
                      {tagInference.conflict
                        ? bilingual(lang, "标签指向多个期望输出，请只保留一种方向。", "Tags imply multiple outputs.")
                        : bilingual(
                            lang,
                            `期望输出与标签推断的“${tagInference.value}”不一致。`,
                            `Output disagrees with inferred ${displayLabelText(tagInference.value, lang)}.`,
                          )}
                    </small>
                  )}
                </div>

                <label className="review-reason">
                  <span className="review-reason-heading">
                    <span>{bilingual(lang, "标注依据", "Label rationale")}</span>
                    <small className="muted">
                      {bilingual(lang, "E 聚焦 · Shift+Enter 换行", "E focus · Shift+Enter newline")}
                    </small>
                  </span>
                  <textarea
                    ref={rationaleRef}
                    rows={3}
                    value={rationale}
                    disabled={!canWrite}
                    onChange={(e) => setRationale(e.target.value)}
                    onPaste={(e) => {
                      const files = Array.from(e.clipboardData?.files || []).filter((f) =>
                        f.type.startsWith("image/"),
                      );
                      if (files.length) {
                        e.preventDefault();
                        addAttachments(files);
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.nativeEvent.isComposing || e.keyCode === 229) return;
                      if (e.key === "Enter" && !e.shiftKey && !isTouchDevice()) {
                        e.preventDefault();
                        if (canWrite && !outputConflict && !saveMutation.isPending) {
                          saveMutation.mutate();
                        }
                      }
                    }}
                    placeholder={bilingual(
                      lang,
                      "说明判断依据；输入 @ 可通知同事",
                      "Explain your label rationale; type @ to mention",
                    )}
                  />
                </label>

                <div className="review-attachment-field">
                  <div className="screenshot-paste-zone is-compact">
                    <span className="screenshot-paste-copy">
                      <strong>{bilingual(lang, "标注截图", "Screenshots")}</strong>
                      <small>{bilingual(lang, "粘贴或选择图片 · 最多 4 张", "Paste or browse · max 4")}</small>
                    </span>
                    <button
                      type="button"
                      className="screenshot-browse-button"
                      disabled={!canWrite}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      {bilingual(lang, "选择图片", "Browse")}
                    </button>
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    multiple
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files) addAttachments(e.target.files);
                      e.target.value = "";
                    }}
                  />
                  {pendingAttachments.length > 0 && (
                    <div className="pending-screenshot-list">
                      {pendingAttachments.map((att) => (
                        <div key={att.id} className="pending-screenshot">
                          <img src={att.previewUrl} alt={att.file.name} />
                          <button
                            type="button"
                            aria-label={bilingual(lang, "移除截图", "Remove screenshot")}
                            onClick={() => {
                              URL.revokeObjectURL(att.previewUrl);
                              setPendingAttachments((prev) => prev.filter((p) => p.id !== att.id));
                            }}
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {decisionMode && (
                  <div className="ra-decision-extra-fields">
                    <label className="review-reason">
                      <span>{bilingual(lang, "裁决人补充依据（选填）", "Decision rationale (optional)")}</span>
                      <textarea
                        rows={2}
                        value={decisionReviewRationale}
                        onChange={(e) => setDecisionReviewRationale(e.target.value)}
                      />
                    </label>
                    <label className="case-decision-confirm">
                      <input
                        type="checkbox"
                        checked={decisionConfirmExclusion}
                        onChange={(e) => setDecisionConfirmExclusion(e.target.checked)}
                      />
                      <span>{bilingual(lang, "已确认上方“是否排除”的选择", "I confirm the exclusion choice above")}</span>
                    </label>
                  </div>
                )}

                <button
                  type="submit"
                  className="button button-primary full-width review-save-button ra-primary-touch"
                  disabled={!canWrite || outputConflict || saveMutation.isPending}
                >
                  {saveMutation.isPending
                    ? bilingual(lang, "保存中…", "Saving…")
                    : decisionMode
                      ? bilingual(lang, "确认裁决", "Confirm decision")
                      : supplementalOnly
                        ? bilingual(lang, "保存任务外补充", "Save supplemental label")
                        : bilingual(lang, "保存标注", "Save label")}
                </button>
              </section>
            </form>
          </aside>
        </section>

        <IssueDiscussion
          open={discussionOpen}
          issueId={selectedIssueId}
          lang={lang}
          username={username}
          canWrite={canWrite}
          isAdmin={isAdmin}
          onClose={() => setDiscussionOpen(false)}
          onCountChange={setDiscussionCount}
        />

        <ModalDialog
          open={decisionModalOpen}
          wide
          lang={lang}
          title={`${bilingual(lang, "标注与裁决", "Labels and decisions")} · ${selectedIssueId}`}
          onClose={() => setDecisionModalOpen(false)}
          footer={
            <>
              {canWrite && allRevisions.length > 0 && (
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => {
                    setDecisionMode({ adoptedRevisionId: null });
                    setDecisionModalOpen(false);
                  }}
                >
                  {bilingual(lang, "重新标注并裁决", "Relabel and decide")}
                </button>
              )}
              <button type="button" className="button button-quiet" onClick={() => setDecisionModalOpen(false)}>
                {bilingual(lang, "关闭", "Close")}
              </button>
            </>
          }
        >
          <div className="ra-decision-modal-list">
            {allRevisions.length === 0 ? (
              <p className="muted">{bilingual(lang, "暂无标注记录。", "No annotations yet.")}</p>
            ) : (
              allRevisions.map((rev) => (
                <article key={rev.id} className="comment-thread-item">
                  <div className="comment-thread-meta">
                    <strong>{rev.author || "—"}</strong>
                    <span>
                      {rev.sourceName} · #{rev.id} · {formatCstTime(rev.created_at, lang)}
                    </span>
                  </div>
                  <div className="ra-decision-badges">
                    <span className={labelBadgeClass(rev.expected_output)}>
                      {displayLabelText(rev.expected_output, lang)}
                    </span>
                    {rev.is_excluded && (
                      <span className="issue-card-flag issue-card-flag-excluded">
                        {bilingual(lang, "排除", "Excluded")}
                      </span>
                    )}
                  </div>
                  {rev.rationale && <p>{rev.rationale}</p>}
                  {canWrite && (
                    <button
                      type="button"
                      className="button button-quiet"
                      onClick={() => {
                        setSelectedTags(rev.tags || []);
                        setExpectedOutput(rev.expected_output || "");
                        setManualOutput(Boolean(rev.expected_output));
                        setIsExcluded(Boolean(rev.is_excluded));
                        setRationale(rev.rationale || "");
                        setDecisionMode({ adoptedRevisionId: rev.id });
                        setDecisionModalOpen(false);
                      }}
                    >
                      {bilingual(lang, "采用此标注并裁决", "Adopt & decide")}
                    </button>
                  )}
                </article>
              ))
            )}
          </div>
        </ModalDialog>

        <RaEventModal
          open={raEventOpen}
          issueId={selectedIssueId}
          metadata={trailMetadataQuery.data || null}
          loading={trailMetadataQuery.isFetching}
          lang={lang}
          onRefresh={() => void trailMetadataQuery.refetch()}
          onClose={() => setRaEventOpen(false)}
        />
      </div>
    );
  }

  // GALLERY VIEW
  const listData = listQuery.data;
  const items = listData?.items || [];
  const tagOptions: MultiSelectOption[] = tagCatalog.map((t) => ({
    value: t.key,
    label: lang === "en" && t.label_en ? t.label_en : t.label || t.key,
    group: t.group || "",
  }));

  return (
    <div className="review-gallery-view ra-labeling-gallery-root">
      {!isBaselineInactive && (
        <section className="review-commandbar case-labeling-command">
          <div className="mobile-filter-bar">
            <button
              type="button"
              className="button button-quiet mobile-filter-toggle"
              aria-expanded={filtersOpenMobile}
              onClick={() => setFiltersOpenMobile((o) => !o)}
            >
              <span>{bilingual(lang, "标注筛选", "Filters")}</span>
              <span>{filtersOpenMobile ? bilingual(lang, "收起", "Hide") : bilingual(lang, "展开条件", "Show filters")}</span>
            </button>
          </div>

          <div className={`ra-summary-filter-grid${filtersOpenMobile ? " is-mobile-open" : ""}`}>
            <label className="ra-filter-field">
              <span>Issue</span>
              <div className="issue-query-control">
                <input
                  type="search"
                  value={searchText}
                  onChange={(e) => {
                    setSearchText(e.target.value);
                    setPage(1);
                  }}
                  placeholder={bilingual(lang, "Issue ID、场景", "Issue ID or scene")}
                />
                <button
                  type="button"
                  className="button button-quiet"
                  onClick={() => {
                    setMultiIssueDraft(issueIds.join("\n"));
                    setMultiIssueModalOpen(true);
                  }}
                >
                  {issueIds.length > 0
                    ? bilingual(lang, `多 Issue (${issueIds.length})`, `IDs (${issueIds.length})`)
                    : bilingual(lang, "多 Issue", "Multi IDs")}
                </button>
              </div>
            </label>

            <div className="ra-filter-field">
              <span>{bilingual(lang, "标注任务", "Task")}</span>
              <UiSelect
                value={taskId}
                options={taskOptions}
                ariaLabel={bilingual(lang, "标注任务", "Labeling task")}
                onChange={(v) => {
                  setTaskId(v);
                  setPage(1);
                }}
              />
            </div>

            <div className="ra-filter-field">
              <span>{bilingual(lang, "结果状态", "Result status")}</span>
              <MultiSelect
                values={statuses}
                options={[
                  { value: "unlabelled", label: bilingual(lang, "未标注", "Unlabeled") },
                  { value: "pending", label: bilingual(lang, "待形成结论", "Pending") },
                  { value: "resolved", label: bilingual(lang, "已形成结论", "Resolved") },
                  { value: "conflict", label: bilingual(lang, "冲突 / 待复核", "Conflict / stale") },
                ]}
                lang={lang}
                ariaLabel={bilingual(lang, "结果状态", "Result status")}
                placeholder={bilingual(lang, "全部状态", "All states")}
                onChange={(v) => {
                  setStatuses(v);
                  setPage(1);
                }}
              />
            </div>

            <div className="ra-filter-field">
              <span>{bilingual(lang, "Issue 标签", "Issue tags")}</span>
              <MultiSelect
                values={issueTags}
                options={tagOptions}
                lang={lang}
                ariaLabel={bilingual(lang, "Issue 标签", "Issue tags")}
                placeholder={bilingual(lang, "全部 Issue 标签", "All tags")}
                onChange={(v) => {
                  setIssueTags(v);
                  setPage(1);
                }}
              />
            </div>

            <div className="ra-filter-field">
              <span>{bilingual(lang, "标注人", "Labeler")}</span>
              <MultiSelect
                values={authors}
                options={(listData?.labelers || []).map((n) => ({ value: n, label: n }))}
                lang={lang}
                ariaLabel={bilingual(lang, "标注人", "Labeler")}
                placeholder={bilingual(lang, "全部标注人", "All labelers")}
                onChange={(v) => {
                  setAuthors(v);
                  setPage(1);
                }}
              />
            </div>

            <div className="ra-filter-field">
              <span>{bilingual(lang, "任务负责人", "Assignee")}</span>
              <MultiSelect
                values={assignees}
                options={(listData?.assignees || []).map((n) => ({ value: n, label: n }))}
                lang={lang}
                ariaLabel={bilingual(lang, "任务负责人", "Assignee")}
                placeholder={bilingual(lang, "全部负责人", "All assignees")}
                onChange={(v) => {
                  setAssignees(v);
                  setPage(1);
                }}
              />
            </div>

            <div className="ra-filter-field">
              <span>GT</span>
              <MultiSelect
                values={gts}
                options={CORE_LABELS.map((l) => ({ value: l, label: displayLabelText(l, lang) }))}
                lang={lang}
                ariaLabel="GT"
                placeholder={bilingual(lang, "全部 GT", "All GT")}
                onChange={(v) => {
                  setGts(v);
                  setPage(1);
                }}
              />
            </div>

            <div className="ra-filter-field">
              <span>{bilingual(lang, "GT 关系", "GT relation")}</span>
              <MultiSelect
                values={gtRelations}
                options={[
                  { value: "differs", label: bilingual(lang, "与 GT 不同", "Differs from GT") },
                  { value: "matches", label: bilingual(lang, "与 GT 一致", "Matches GT") },
                  { value: "missing_gt", label: bilingual(lang, "GT 缺失", "GT missing") },
                ]}
                lang={lang}
                ariaLabel={bilingual(lang, "GT 关系", "GT relation")}
                placeholder={bilingual(lang, "全部关系", "All relations")}
                onChange={(v) => {
                  setGtRelations(v);
                  setPage(1);
                }}
              />
            </div>

            <div className="ra-filter-field">
              <span>{bilingual(lang, "结果类别", "Result label")}</span>
              <MultiSelect
                values={labels}
                options={CORE_LABELS.map((l) => ({ value: l, label: displayLabelText(l, lang) }))}
                lang={lang}
                ariaLabel={bilingual(lang, "结果类别", "Result label")}
                placeholder={bilingual(lang, "全部类别", "All labels")}
                onChange={(v) => {
                  setLabels(v);
                  setPage(1);
                }}
              />
            </div>

            <div className="ra-filter-field">
              <span>{bilingual(lang, "讨论", "Discussion")}</span>
              <MultiSelect
                values={commentStates}
                options={[
                  { value: "with", label: bilingual(lang, "有讨论", "With discussion") },
                  { value: "without", label: bilingual(lang, "无讨论", "Without discussion") },
                ]}
                lang={lang}
                ariaLabel={bilingual(lang, "讨论", "Discussion")}
                placeholder={bilingual(lang, "全部", "All")}
                onChange={(v) => {
                  setCommentStates(v);
                  setPage(1);
                }}
              />
            </div>

            <div className="ra-filter-field">
              <span>{bilingual(lang, "排除", "Exclusion")}</span>
              <MultiSelect
                values={exclusions}
                options={[
                  { value: "active", label: bilingual(lang, "未排除", "Active") },
                  { value: "excluded", label: bilingual(lang, "已排除", "Excluded") },
                ]}
                lang={lang}
                ariaLabel={bilingual(lang, "排除", "Exclusion")}
                placeholder={bilingual(lang, "全部", "All")}
                onChange={(v) => {
                  setExclusions(v);
                  setPage(1);
                }}
              />
            </div>

            <div className="ra-filter-field">
              <span>{bilingual(lang, "目标集合", "Target cohort")}</span>
              <UiSelect
                value={targetGroup}
                options={[
                  { value: "", label: bilingual(lang, "全部", "All") },
                  { value: "targets", label: bilingual(lang, "仅目标集", "Targets only") },
                  { value: "non_targets", label: bilingual(lang, "非目标集", "Non-targets") },
                ]}
                ariaLabel={bilingual(lang, "目标集合", "Target cohort")}
                onChange={(v) => {
                  setTargetGroup(v);
                  setPage(1);
                }}
              />
            </div>
          </div>

          <div className="ra-summary-toolbar-actions">
            <button type="button" className="button button-quiet" onClick={resetFilters}>
              {bilingual(lang, "重置", "Reset")}
            </button>
          </div>
        </section>
      )}

      <section className="gallery-panel">
        <div className="gallery-heading case-labeling-gallery-heading">
          <div className="case-labeling-heading-copy">
            <h2>{bilingual(lang, "问题图库", "Case gallery")}</h2>
            <span className="count-pill">{isBaselineInactive ? 0 : (listData?.total ?? "—")}</span>
          </div>
          <div className="gallery-heading-actions">
            <button
              type="button"
              className="button button-quiet"
              disabled={exportingCsv || isBaselineInactive || !(listData?.total || 0)}
              onClick={() => void handleExportIssuesCsv()}
            >
              {exportingCsv
                ? bilingual(lang, "导出中…", "Exporting…")
                : bilingual(lang, "导出 Issue", "Export Issues")}
            </button>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => navigateWorkbenchPage("labeling-summary")}
            >
              {bilingual(lang, "标注汇总", "Labeling summary")}
            </button>
            {isAdmin && selectedTask?.workset_id && (
              <button
                type="button"
                className="button button-quiet"
                disabled={saveSnapshotMutation.isPending}
                onClick={() => saveSnapshotMutation.mutate()}
              >
                {bilingual(lang, "保存 Label 快照", "Save Label snapshot")}
              </button>
            )}
            {isAdmin && (
              <button
                type="button"
                className="button button-primary"
                disabled={isBaselineInactive || !(listData?.total || 0)}
                onClick={() => navigateWorkbenchPage("labeling-new-task")}
              >
                {bilingual(lang, "标注任务", "New task")}
              </button>
            )}
          </div>
        </div>

        {selectedTask?.progress && Number(selectedTask.progress.total) > 0 && (
          <div className="review-cluster-strip case-labeling-progress-strip">
            <span className="subheading">{bilingual(lang, "任务进度", "Task progress")}</span>
            <div className="cluster-list">
              <span className="cluster-chip">
                <span>{bilingual(lang, "总计", "Total")}</span>
                <b>
                  {selectedTask.progress.resolved}/{selectedTask.progress.total}
                </b>
              </span>
              {Number(selectedTask.progress.conflict || 0) > 0 && (
                <span className="cluster-chip">
                  <span>{bilingual(lang, "冲突", "Conflicts")}</span>
                  <b>{selectedTask.progress.conflict}</b>
                </span>
              )}
              {(selectedTask.progress.assignees || []).map((p) => (
                <span key={p.name} className="cluster-chip">
                  <span>{p.name}</span>
                  <b>
                    {p.labeled}/{p.total}
                  </b>
                </span>
              ))}
            </div>
          </div>
        )}

        {isBaselineInactive ? (
          <div className="empty-state issue-grid-empty case-labeling-inactive-state">
            <h2>{bilingual(lang, "当前数据集尚未切换到问题标注", "Dataset not activated for Case labeling")}</h2>
            <p>
              {bilingual(
                lang,
                "请切换到已激活问题标注的数据集，或在「判错复核」工作台查看。",
                "Switch to an activated labeling dataset or open the Review workbench.",
              )}
            </p>
            <div className="case-labeling-active-switchers">
              {(configQuery.data?.baselines || [])
                .filter((b) => activeLabelingBaselines.includes(b.id))
                .map((b) => (
                  <button
                    key={b.id}
                    type="button"
                    className="button button-primary"
                    onClick={() => {
                      const win = window as unknown as {
                        setBaselineScopes?: (ids: string[]) => Promise<void>;
                      };
                      void win.setBaselineScopes?.([b.id]);
                    }}
                  >
                    {bilingual(lang, `查看 ${b.label || b.id}`, `View ${b.label || b.id}`)} ·{" "}
                    {b.count ?? "—"}
                  </button>
                ))}
            </div>
          </div>
        ) : (
          <>
            <div className="issue-grid" aria-live="polite">
              {items.map((item) => {
                const thumbUrl = normalizeAssetUrl(item.thumbnail_url || item.thumbnail?.url);
                const voyagerUrl = safeExternalUrl(item.voyager_issue_url);
                return (
                  <article key={item.issue_id} className="issue-card" data-issue-id={item.issue_id}>
                    <button
                      type="button"
                      className="issue-card-open"
                      aria-label={bilingual(lang, `打开 ${item.issue_id} 标注`, `Open ${item.issue_id}`)}
                      onClick={() => setSelectedIssueId(item.issue_id)}
                    />
                    <div className="issue-thumbnail">
                      <div className="issue-thumbnail-placeholder" aria-hidden="true">
                        <span>RA</span>
                      </div>
                      {thumbUrl && (
                        <img
                          src={thumbUrl}
                          alt={`${item.issue_id} BEV`}
                          loading="lazy"
                          decoding="async"
                        />
                      )}
                      <span className="issue-thumbnail-label">
                        {item.thumbnail?.label || bilingual(lang, "BEV 关键帧", "BEV keyframe")}
                      </span>
                      <button
                        type="button"
                        className="issue-media-preview"
                        onClick={(e) => {
                          e.stopPropagation();
                          setPreviewMediaIssueId(item.issue_id);
                        }}
                      >
                        {bilingual(lang, "媒体预览", "Media")}
                      </button>
                    </div>
                    <div className="issue-card-body">
                      <div className="issue-card-heading">
                        <div className="issue-card-heading-main">
                          {voyagerUrl ? (
                            <a
                              className="issue-id"
                              href={voyagerUrl}
                              target="_blank"
                              rel="noreferrer"
                              onClick={(e) => e.stopPropagation()}
                            >
                              {item.issue_id}
                            </a>
                          ) : (
                            <span className="issue-id">{item.issue_id}</span>
                          )}
                        </div>
                        <div className="issue-card-flags">
                          {item.is_excluded && (
                            <span className="issue-card-flag issue-card-flag-excluded">
                              {bilingual(lang, "应该排除", "Exclude")}
                            </span>
                          )}
                          {(item.label_state === "conflict" || item.label_state === "stale") && (
                            <span className="issue-card-flag issue-card-flag-needs-gt">
                              {bilingual(lang, "冲突待处理", "Conflict")}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="issue-card-labels">
                        <span className="issue-label-pair">
                          <small>GT</small>
                          <span className={labelBadgeClass(item.gt_label)}>
                            {displayLabelText(item.gt_label, lang)}
                          </span>
                        </span>
                        <span className="issue-label-pair">
                          <small>{bilingual(lang, "标注", "Label")}</small>
                          <span className={labelBadgeClass(item.expected_output)}>
                            {displayLabelText(item.expected_output, lang)}
                          </span>
                        </span>
                        {item.author && (
                          <span className="issue-reviewer">
                            {item.author}
                            {item.author_verified ? " · SSO" : ""}
                          </span>
                        )}
                      </div>
                    </div>
                  </article>
                );
              })}

              {!listQuery.isPending && items.length === 0 && (
                <div className="empty-state issue-grid-empty">
                  <h2>{bilingual(lang, "当前范围没有 Case", "No cases in this scope")}</h2>
                  <p>{bilingual(lang, "请调整筛选条件或切换数据集。", "Adjust filters or switch datasets.")}</p>
                </div>
              )}
            </div>

            <Pagination
              page={page}
              pageSize={pageSize}
              total={listData?.total || 0}
              lang={lang}
              loading={listQuery.isFetching}
              onPageChange={setPage}
              onPageSizeChange={(s) => {
                setPageSize(s);
                setPage(1);
              }}
            />
          </>
        )}
      </section>

      <ModalDialog
        open={multiIssueModalOpen}
        lang={lang}
        title={bilingual(lang, "多 Issue ID 筛选", "Multi-Issue ID filter")}
        onClose={() => setMultiIssueModalOpen(false)}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => {
                setIssueIds([]);
                setMultiIssueDraft("");
                setMultiIssueModalOpen(false);
                setPage(1);
              }}
            >
              {bilingual(lang, "清空", "Clear")}
            </button>
            <button
              type="button"
              className="button button-primary"
              onClick={() => {
                const parsed = parseIssueIdsInput(multiIssueDraft);
                setIssueIds(parsed.ids.slice(0, 500));
                setMultiIssueModalOpen(false);
                setPage(1);
              }}
            >
              {bilingual(lang, "应用筛选", "Apply")}
            </button>
          </>
        }
      >
        <textarea
          rows={6}
          className="ra-multi-issue-textarea"
          value={multiIssueDraft}
          onChange={(e) => setMultiIssueDraft(e.target.value)}
          placeholder={bilingual(lang, "每行、空格或逗号分隔多个 Issue ID", "Separate IDs by newline, space, or comma")}
        />
      </ModalDialog>

      <CaseMediaPreviewModal
        issueId={previewMediaIssueId}
        lang={lang}
        onClose={() => setPreviewMediaIssueId(null)}
      />
    </div>
  );
};
