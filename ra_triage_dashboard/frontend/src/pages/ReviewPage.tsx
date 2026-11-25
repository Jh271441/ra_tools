import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  formatCstTime,
  UiLanguage,
  withWorkbenchBase,
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
import { NewAllocationModal } from "../features/allocation/NewAllocationModal";
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
  MODEL_LABELS,
  MODEL_REVIEW_STATUS_OPTIONS,
  navigateWorkbenchPage,
  normalizeAssetUrl,
  parseIssueIdsInput,
  safeExternalUrl,
  showWorkbenchToast,
} from "../features/review/reviewHelpers";
import { ReviewTagSelector } from "../features/review/ReviewTagSelector";

export interface ReviewPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
  username: string;
  canWrite: boolean;
  isAdmin: boolean;
}

interface ModelRunOption {
  id: string;
  name?: string;
  baseline_prediction_count?: number;
}

interface WorkSplitSummary {
  split_id: string;
  name?: string;
  model_run_id?: string;
  workflow_mode?: string;
  members?: string[];
  assignees?: string[];
}

interface ReviewAnnotationRecord {
  id: number | string;
  model_run_id?: string;
  model_review_status?: string;
  label?: string;
  expected_output?: string;
  review_status?: string;
  is_excluded?: boolean;
  tags?: string[];
  missing_evidence?: string[];
  note?: string;
  author?: string;
  author_verified?: boolean;
  created_at?: string;
  attachments?: { id: string; url?: string }[];
}

interface ReviewCaseCardItem {
  issue_id: string;
  gt_label?: string;
  is_excluded?: boolean;
  voyager_issue_url?: string;
  thumbnail?: { url?: string; label?: string };
  prediction?: {
    model_run_id?: string;
    label?: string;
    reason?: string;
    mismatch?: boolean;
    comparable?: boolean;
  };
  annotation?: ReviewAnnotationRecord;
  label_state?: {
    state?: string;
    expected_output?: string;
  };
}

interface ReviewListResponse {
  items?: ReviewCaseCardItem[];
  total?: number;
  page?: number;
  pages?: number;
  page_size?: number;
  reviewers?: string[];
}

interface ReviewCaseDetailResponse {
  issue_id: string;
  summary?: string;
  review_note?: string;
  gt_label?: string;
  voyager_issue_url?: string;
  trail_url?: string;
  predictions?: {
    model_run_id: string;
    run_name?: string;
    model_label?: string;
    reason?: string;
    confidence?: number | null;
    is_rule?: boolean;
    created_at?: string;
  }[];
  annotations?: ReviewAnnotationRecord[];
  review_assignment?: {
    split_id?: string;
    workflow_mode?: string;
    config_revision?: number | null;
    current_user_assigned?: boolean;
  };
  label_state?: {
    state?: string;
    expected_output?: string;
    sources?: {
      label_case_id?: string;
      task_name?: string;
      revision_summaries?: {
        id: number;
        author?: string;
        expected_output?: string;
        tags?: string[];
        rationale?: string;
        is_excluded?: boolean;
      }[];
    }[];
  };
}

interface CombinedReviewContextResponse {
  issue?: { issue_id?: string };
  campaign?: {
    id?: string;
    workflow_mode?: string;
    evaluation_run_id?: string;
    config_revision?: number | null;
  };
  case_revision_id?: number | null;
  label_state_fingerprint?: string;
  model_review_storage_id?: number | null;
  own_case_revision?: {
    expected_output?: string;
    tags?: string[];
    rationale?: string;
    is_excluded?: boolean;
  };
}

interface PendingAttachment {
  id: string;
  file: File;
  previewUrl: string;
}

export const ReviewPage: React.FC<ReviewPageProps> = ({
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

  // Gallery & route filter state
  const [selectedIssueId, setSelectedIssueId] = useState(initialParams.get("issue") || "");
  const [modelRunId, setModelRunId] = useState(initialParams.get("run") || "");
  const [workSplitId, setWorkSplitId] = useState(initialParams.get("work_split") || "");
  const [workAssignee, setWorkAssignee] = useState(initialParams.get("work_assignee") || "");
  const [searchText, setSearchText] = useState(initialParams.get("q") || "");
  const [issueIds, setIssueIds] = useState<string[]>(() =>
    (initialParams.get("issue_ids") || "").split(",").filter(Boolean),
  );
  const [comparisons, setComparisons] = useState<string[]>(() =>
    (initialParams.get("comparison") || "").split(",").filter((v) => v && v !== "all"),
  );
  const [reviewStatuses, setReviewStatuses] = useState<string[]>(() =>
    (initialParams.get("review_status") || "").split(",").filter(Boolean),
  );
  const [reviewers, setReviewers] = useState<string[]>(() =>
    (initialParams.get("reviewer") || "").split(",").filter(Boolean),
  );
  const [gtLabels, setGtLabels] = useState<string[]>(() =>
    (initialParams.get("gt_label") || "").split(",").filter(Boolean),
  );
  const [modelLabels, setModelLabels] = useState<string[]>(() =>
    (initialParams.get("model_label") || "").split(",").filter(Boolean),
  );
  const [issueTagsFilter, setIssueTagsFilter] = useState<string[]>(() =>
    (initialParams.get("issue_tags") || "").split(",").filter(Boolean),
  );
  const [missingEvidenceFilter, setMissingEvidenceFilter] = useState<string[]>(() =>
    (initialParams.get("missing_evidence") || "").split(",").filter(Boolean),
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
  const [newAllocOpen, setNewAllocOpen] = useState(false);
  const [previewMediaIssueId, setPreviewMediaIssueId] = useState<string | null>(null);

  // Detail & Review form state
  const [expectedOutput, setExpectedOutput] = useState("");
  const [manualOutput, setManualOutput] = useState(false);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [isExcluded, setIsExcluded] = useState(false);
  const [caseRationale, setCaseRationale] = useState("");
  const [modelReviewStatus, setModelReviewStatus] = useState("completed");
  const [reviewNote, setReviewNote] = useState("");
  const [missingEvidence, setMissingEvidence] = useState<string[]>([]);
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [discussionOpen, setDiscussionOpen] = useState(false);
  const [discussionCount, setDiscussionCount] = useState(0);
  const [historyModalKind, setHistoryModalKind] = useState<"review" | "model" | "shared" | null>(null);
  const [raEventOpen, setRaEventOpen] = useState(false);
  const [queueJumpInput, setQueueJumpInput] = useState("");

  const noteRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const mediaAnchorRef = useRef<HTMLDivElement | null>(null);
  const reviewAnchorRef = useRef<HTMLDivElement | null>(null);

  // Sync from URL popstate / external navigation
  useEffect(() => {
    if (!active) return;
    const syncFromUrl = () => {
      const p = new URLSearchParams(window.location.search);
      setSelectedIssueId(p.get("issue") || "");
      const run = p.get("run");
      if (run !== null) setModelRunId(run);
      const split = p.get("work_split");
      if (split !== null) setWorkSplitId(split);
      if (p.get("comments") === "1" && p.get("issue")) {
        setDiscussionOpen(true);
      }
    };
    if (initialParams.get("comments") === "1" && initialParams.get("issue")) {
      setDiscussionOpen(true);
    }
    window.addEventListener("popstate", syncFromUrl);
    return () => window.removeEventListener("popstate", syncFromUrl);
  }, [active, initialParams]);

  // Persist URL
  useEffect(() => {
    if (!active) return;
    const url = new URL(window.location.href);
    const setOrDel = (k: string, v: string) => {
      if (v) url.searchParams.set(k, v);
      else url.searchParams.delete(k);
    };
    setOrDel("baselines", baselinesKey);
    setOrDel("issue", selectedIssueId);
    setOrDel("run", modelRunId);
    setOrDel("work_split", workSplitId);
    setOrDel("work_assignee", workAssignee);
    setOrDel("q", searchText.trim());
    setOrDel("issue_ids", issueIds.join(","));
    setOrDel("comparison", comparisons.join(","));
    setOrDel("review_status", reviewStatuses.join(","));
    setOrDel("reviewer", reviewers.join(","));
    setOrDel("gt_label", gtLabels.join(","));
    setOrDel("model_label", modelLabels.join(","));
    setOrDel("issue_tags", issueTagsFilter.join(","));
    setOrDel("missing_evidence", missingEvidenceFilter.join(","));
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
    modelRunId,
    workSplitId,
    workAssignee,
    searchText,
    issueIds,
    comparisons,
    reviewStatuses,
    reviewers,
    gtLabels,
    modelLabels,
    issueTagsFilter,
    missingEvidenceFilter,
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

  const runsQuery = useQuery<{ items?: ModelRunOption[] }>({
    queryKey: ["review-model-runs", baselinesKey],
    queryFn: ({ signal }) =>
      apiRequest<{ items?: ModelRunOption[] }>(
        `/api/model-runs${baselinesKey ? `?baselines=${encodeURIComponent(baselinesKey)}` : ""}`,
        { signal },
      ),
    enabled: active,
    staleTime: 30_000,
  });

  const splitsQuery = useQuery<{ items?: WorkSplitSummary[] }>({
    queryKey: ["review-work-splits", baselinesKey, modelRunId],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        lifecycle: "current",
        limit: "100",
        ...(baselinesKey ? { baselines: baselinesKey } : {}),
        ...(modelRunId ? { model_run_id: modelRunId } : {}),
      });
      return apiRequest<{ items?: WorkSplitSummary[] }>(`/api/cases/work-splits?${qs.toString()}`, {
        signal,
      });
    },
    enabled: active,
    staleTime: 30_000,
  });

  const membersQuery = useQuery<{ items?: { username: string; access_role?: string }[] }>({
    queryKey: ["access-users-for-review-alloc"],
    queryFn: ({ signal }) =>
      apiRequest<{ items?: { username: string; access_role?: string }[] }>("/api/access-users", {
        signal,
      }),
    enabled: active && isAdmin && newAllocOpen,
    staleTime: 60_000,
  });

  const casesQueryParams = useMemo(() => {
    const qs = new URLSearchParams({
      baselines: baselinesKey,
      model_run_id: modelRunId,
      work_split_id: workSplitId,
      work_assignee: workAssignee,
      q: searchText.trim(),
      issue_ids: issueIds.join(","),
      comparison: comparisons.length ? comparisons.join(",") : "all",
      comparison_status: comparisons.length ? comparisons.join(",") : "all",
      review_status: reviewStatuses.join(","),
      reviewer: reviewers.join(","),
      gt_label: gtLabels.join(","),
      model_label: modelLabels.join(","),
      issue_tags: issueTagsFilter.join(","),
      missing_evidence: missingEvidenceFilter.join(","),
      comment_state: commentStates.length === 1 ? commentStates[0] : "all",
      exclusion: exclusions.length === 1 ? exclusions[0] : "all",
      target_group: targetGroup,
      include_thumbnail: "true",
      page: String(page),
      page_size: String(pageSize),
    });
    return qs.toString();
  }, [
    baselinesKey,
    modelRunId,
    workSplitId,
    workAssignee,
    searchText,
    issueIds,
    comparisons,
    reviewStatuses,
    reviewers,
    gtLabels,
    modelLabels,
    issueTagsFilter,
    missingEvidenceFilter,
    commentStates,
    exclusions,
    targetGroup,
    page,
    pageSize,
  ]);

  const casesQuery = useQuery<ReviewListResponse>({
    queryKey: ["review-cases", casesQueryParams],
    queryFn: ({ signal }) =>
      apiRequest<ReviewListResponse>(`/api/cases?${casesQueryParams}`, { signal }),
    enabled: active,
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  });

  const detailQuery = useQuery<ReviewCaseDetailResponse>({
    queryKey: ["review-case-detail", selectedIssueId, modelRunId, workSplitId, baselinesKey],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        include_media: "false",
        ...(modelRunId ? { model_run_id: modelRunId } : {}),
        ...(workSplitId ? { work_split_id: workSplitId } : {}),
        ...(baselinesKey ? { baselines: baselinesKey } : {}),
      });
      return apiRequest<ReviewCaseDetailResponse>(
        `/api/cases/${encodeURIComponent(selectedIssueId)}?${qs.toString()}`,
        { signal },
      );
    },
    enabled: active && Boolean(selectedIssueId),
    staleTime: 5_000,
  });

  const combinedContextQuery = useQuery<CombinedReviewContextResponse>({
    queryKey: ["combined-review-context", selectedIssueId, modelRunId, workSplitId, baselinesKey],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        ...(modelRunId ? { model_run_id: modelRunId } : {}),
        ...(workSplitId ? { work_split_id: workSplitId } : {}),
        ...(baselinesKey ? { baselines: baselinesKey } : {}),
      });
      return apiRequest<CombinedReviewContextResponse>(
        `/api/cases/${encodeURIComponent(selectedIssueId)}/combined-review-context?${qs.toString()}`,
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

  const detail = detailQuery.data;
  const combinedCtx = combinedContextQuery.data;
  const tagCatalog = configQuery.data?.review_tag_catalog || [];
  const evidenceCatalog = configQuery.data?.missing_evidence_catalog || [];

  const isCombinedWorkflow = useMemo(() => {
    const mode =
      combinedCtx?.campaign?.workflow_mode || detail?.review_assignment?.workflow_mode || "";
    if (mode === "model_review_only") return false;
    if (mode === "model_review_and_case_label") return true;
    return !modelRunId || Boolean(combinedCtx);
  }, [combinedCtx, detail?.review_assignment?.workflow_mode, modelRunId]);

  // Hydrate form when detail or combinedContext arrives
  useEffect(() => {
    if (!detail) return;
    setPendingAttachments((prev) => {
      prev.forEach((p) => URL.revokeObjectURL(p.previewUrl));
      return [];
    });

    const runAnn = (detail.annotations || []).find(
      (a) =>
        (!modelRunId || String(a.model_run_id || "") === modelRunId) &&
        (!username || String(a.author || "").toLowerCase() === username.toLowerCase()),
    ) || (detail.annotations || []).find((a) => !modelRunId || String(a.model_run_id || "") === modelRunId);

    setModelReviewStatus(
      runAnn?.model_review_status === "needs_review" ? "needs_review" : "completed",
    );
    setReviewNote(runAnn?.note || "");
    setMissingEvidence(runAnn?.missing_evidence || []);

    const ownCase = combinedCtx?.own_case_revision;
    const out = ownCase?.expected_output || "";
    setExpectedOutput(out);
    setManualOutput(Boolean(out));
    setSelectedTags(ownCase?.tags || []);
    setIsExcluded(Boolean(ownCase?.is_excluded));
    setCaseRationale(ownCase?.rationale || "");
  }, [detail, combinedCtx, modelRunId, username]);

  const tagInference = useMemo(
    () => inferExpectedOutputFromTags(selectedTags, tagCatalog),
    [selectedTags, tagCatalog],
  );
  useEffect(() => {
    if (!manualOutput) setExpectedOutput(tagInference.value);
  }, [tagInference.value, manualOutput]);

  const outputConflict =
    isCombinedWorkflow &&
    (tagInference.conflict ||
      Boolean(tagInference.value && expectedOutput && tagInference.value !== expectedOutput));

  const pageItems = casesQuery.data?.items || [];
  const currentIdxOnPage = pageItems.findIndex((i) => i.issue_id === selectedIssueId);
  const absoluteIdx =
    currentIdxOnPage >= 0 ? (page - 1) * pageSize + currentIdxOnPage + 1 : null;
  const totalCases = Number(casesQuery.data?.total || 0);

  useEffect(() => {
    setQueueJumpInput(absoluteIdx != null ? String(absoluteIdx) : "");
  }, [absoluteIdx]);

  const navigateAdjacent = useCallback(
    (delta: -1 | 1) => {
      if (currentIdxOnPage < 0) return;
      const target = pageItems[currentIdxOnPage + delta];
      if (target) {
        setSelectedIssueId(target.issue_id);
        return;
      }
      if (delta > 0 && page * pageSize < totalCases) {
        setPage((p) => p + 1);
      } else if (delta < 0 && page > 1) {
        setPage((p) => p - 1);
      }
    },
    [currentIdxOnPage, pageItems, page, pageSize, totalCases],
  );

  // Submit annotation or combined review
  const submitMutation = useMutation({
    mutationFn: async () => {
      if (!detail) throw new Error("Case not loaded");
      const idempotencyKey =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? crypto.randomUUID()
          : `rev-${Date.now()}-${Math.random().toString(16).slice(2)}`;

      if (isCombinedWorkflow) {
        if (!expectedOutput) {
          throw new Error(bilingual(lang, "请明确选择 Case 期望输出标签。", "Select an expected output label."));
        }
        if (outputConflict) {
          throw new Error(bilingual(lang, "Case 标签与所选 Tags 冲突。", "Label conflicts with selected tags."));
        }
        const payload: Record<string, unknown> = {
          author: username,
          expected_output: expectedOutput,
          is_excluded: isExcluded,
          tags: selectedTags,
          rationale: caseRationale,
          update_case_details: true,
          expected_case_revision_id: combinedCtx?.case_revision_id ?? null,
          expected_label_state_fingerprint: combinedCtx?.label_state_fingerprint || "",
        };
        if (modelRunId) {
          Object.assign(payload, {
            model_run_id: modelRunId,
            campaign_id: combinedCtx?.campaign?.id || workSplitId || "",
            work_split_id: combinedCtx?.campaign?.id || workSplitId || "",
            model_review_status: modelReviewStatus,
            reason: reviewNote,
            missing_evidence: missingEvidence,
            expected_model_review_storage_id: combinedCtx?.model_review_storage_id ?? null,
            expected_allocation_revision:
              combinedCtx?.campaign?.config_revision ?? detail.review_assignment?.config_revision ?? null,
          });
        }
        const action = modelRunId ? "combined-review" : "case-label-from-review";
        if (pendingAttachments.length > 0) {
          const form = new FormData();
          form.append("payload", JSON.stringify(payload));
          pendingAttachments.forEach((a) => form.append("attachments", a.file, a.file.name));
          return apiRequest(
            `/api/cases/${encodeURIComponent(detail.issue_id)}/${action}-with-attachments`,
            {
              method: "POST",
              body: form,
              headers: { "Idempotency-Key": idempotencyKey },
            },
          );
        }
        return apiRequest(`/api/cases/${encodeURIComponent(detail.issue_id)}/${action}`, {
          method: "POST",
          body: payload,
          headers: { "Idempotency-Key": idempotencyKey },
        });
      }

      if (!modelRunId) {
        throw new Error(bilingual(lang, "请先选择 Model Run。", "Select a Model Run first."));
      }
      const ownAnn = (detail.annotations || []).find(
        (a) =>
          String(a.model_run_id || "") === modelRunId &&
          String(a.author || "").toLowerCase() === username.toLowerCase(),
      );
      const payload = {
        model_run_id: modelRunId,
        work_split_id: workSplitId || detail.review_assignment?.split_id || "",
        expected_allocation_revision: detail.review_assignment?.config_revision ?? null,
        expected_previous_annotation_id: ownAnn?.id ?? null,
        model_review_status: modelReviewStatus,
        missing_evidence: missingEvidence,
        note: reviewNote,
        author: username,
      };
      if (pendingAttachments.length > 0) {
        const form = new FormData();
        form.append("payload", JSON.stringify(payload));
        pendingAttachments.forEach((a) => form.append("attachments", a.file, a.file.name));
        return apiRequest(
          `/api/cases/${encodeURIComponent(detail.issue_id)}/annotations-with-attachments`,
          {
            method: "POST",
            body: form,
          },
        );
      }
      return apiRequest(`/api/cases/${encodeURIComponent(detail.issue_id)}/annotations`, {
        method: "POST",
        body: payload,
      });
    },
    onSuccess: () => {
      pendingAttachments.forEach((p) => URL.revokeObjectURL(p.previewUrl));
      setPendingAttachments([]);
      showWorkbenchToast(
        isCombinedWorkflow
          ? bilingual(lang, "联合复核 / 问题标注已保存。", "Combined review saved.")
          : bilingual(lang, "Model Review 已保存。", "Model review saved."),
      );
      void queryClient.invalidateQueries({ queryKey: ["review-case-detail", selectedIssueId] });
      void queryClient.invalidateQueries({ queryKey: ["combined-review-context", selectedIssueId] });
      void queryClient.invalidateQueries({ queryKey: ["review-cases"] });
    },
    onError: (err) => {
      showWorkbenchToast(
        err instanceof Error ? err.message : bilingual(lang, "提交失败。", "Submit failed."),
        true,
      );
    },
  });

  const revokeReviewMutation = useMutation({
    mutationFn: (annotationId: number | string) =>
      apiRequest(
        `/api/cases/${encodeURIComponent(selectedIssueId)}/model-reviews/${encodeURIComponent(String(annotationId))}/revoke`,
        { method: "POST", body: {} },
      ),
    onSuccess: () => {
      showWorkbenchToast(bilingual(lang, "已撤销复核记录。", "Review revoked."));
      void queryClient.invalidateQueries({ queryKey: ["review-case-detail", selectedIssueId] });
      void queryClient.invalidateQueries({ queryKey: ["review-cases"] });
    },
    onError: (err) =>
      showWorkbenchToast(err instanceof Error ? err.message : "Revoke failed", true),
  });

  // Keyboard shortcuts in Detail view
  const detailShortcutsEnabled = active && Boolean(selectedIssueId);
  useShortcut(
    "page",
    "[",
    (e) => {
      e.preventDefault();
      navigateAdjacent(-1);
      return true;
    },
    { enabled: detailShortcutsEnabled },
  );
  useShortcut(
    "page",
    "]",
    (e) => {
      e.preventDefault();
      navigateAdjacent(1);
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
      setHistoryModalKind((prev) => (prev === "review" ? null : "review"));
      return true;
    },
    { enabled: detailShortcutsEnabled },
  );
  useShortcut(
    "page",
    "p",
    (e) => {
      e.preventDefault();
      setHistoryModalKind((prev) => (prev === "model" ? null : "model"));
      return true;
    },
    { enabled: detailShortcutsEnabled },
  );
  useShortcut(
    "page",
    "l",
    (e) => {
      e.preventDefault();
      setHistoryModalKind((prev) => (prev === "shared" ? null : "shared"));
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
      if (!canWrite || !isCombinedWorkflow) return false;
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
      noteRef.current?.focus();
      return true;
    },
    { enabled: detailShortcutsEnabled },
  );

  const addAttachments = (files: FileList | File[]) => {
    const allowed = new Set(["image/png", "image/jpeg", "image/webp"]);
    const next = [...pendingAttachments];
    for (const file of Array.from(files)) {
      if (next.length >= 4) break;
      if (!allowed.has(file.type) || file.size > 8 * 1024 * 1024) continue;
      next.push({
        id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
        file,
        previewUrl: URL.createObjectURL(file),
      });
    }
    setPendingAttachments(next);
  };

  const resetFilters = () => {
    setModelRunId("");
    setWorkSplitId("");
    setWorkAssignee("");
    setSearchText("");
    setIssueIds([]);
    setComparisons([]);
    setReviewStatuses([]);
    setReviewers([]);
    setGtLabels([]);
    setModelLabels([]);
    setIssueTagsFilter([]);
    setMissingEvidenceFilter([]);
    setCommentStates([]);
    setExclusions([]);
    setTargetGroup("");
    setPage(1);
  };

  if (!active) return null;

  const runs = runsQuery.data?.items || [];
  const splits = splitsQuery.data?.items || [];
  const activeSplit = splits.find((s) => s.split_id === workSplitId);
  const splitAssignees = activeSplit?.assignees || activeSplit?.members || [];
  const eligibleMembers = (membersQuery.data?.items || [])
    .filter((u) => ["writer", "admin"].includes(String(u.access_role || "")))
    .map((u) => u.username);

  // DETAIL VIEW
  if (selectedIssueId) {
    const primaryPred =
      (detail?.predictions || []).find((p) => p.model_run_id === modelRunId) ||
      (modelRunId ? null : (detail?.predictions || [])[0] || null);
    const extLinks = trailMetadataQuery.data?.external_links || {};
    const voyagerHref = safeExternalUrl(
      detail?.voyager_issue_url || detail?.trail_url || extLinks.voyager_issue_url,
    );
    const aresHref = safeExternalUrl(extLinks.ares_studio);
    const raRecHref = safeExternalUrl(extLinks.ra_recording);
    const raEventCount = (trailMetadataQuery.data?.ra_events || trailMetadataQuery.data?.events || []).length;
    const predMatches =
      primaryPred?.model_label &&
      detail?.gt_label &&
      (CORE_LABELS as readonly string[]).includes(detail.gt_label) &&
      (MODEL_LABELS as readonly string[]).includes(primaryPred.model_label)
        ? primaryPred.model_label === detail.gt_label
        : null;

    return (
      <div className="review-detail-view ra-review-detail-root">
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
            onClick={() => reviewAnchorRef.current?.scrollIntoView({ behavior: "smooth" })}
          >
            {bilingual(lang, "填写复核", "Review")}
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
                      disabled={currentIdxOnPage <= 0 && page <= 1}
                      onClick={() => navigateAdjacent(-1)}
                    >
                      {bilingual(lang, "← 上一 Issue", "← Prev")}{" "}
                      <kbd className="review-control-shortcut">[</kbd>
                    </button>
                    <span className="detail-queue-position">
                      <input
                        className="detail-queue-index-input"
                        type="number"
                        min={1}
                        max={totalCases || 1}
                        value={queueJumpInput}
                        disabled={totalCases === 0}
                        aria-label={bilingual(lang, "跳转到筛选队列序号", "Jump to queue index")}
                        onChange={(e) => setQueueJumpInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            const n = Number(queueJumpInput);
                            if (Number.isInteger(n) && n >= 1 && n <= totalCases) {
                              const targetPage = Math.ceil(n / pageSize);
                              const idxInPage = (n - 1) % pageSize;
                              if (targetPage === page && pageItems[idxInPage]) {
                                setSelectedIssueId(pageItems[idxInPage].issue_id);
                              } else {
                                setPage(targetPage);
                              }
                            }
                          }
                        }}
                      />
                      <span className="detail-queue-total">/ {totalCases || "—"}</span>
                    </span>
                    <button
                      type="button"
                      className="button button-quiet"
                      disabled={
                        currentIdxOnPage < 0 ||
                        (currentIdxOnPage >= pageItems.length - 1 && page * pageSize >= totalCases)
                      }
                      onClick={() => navigateAdjacent(1)}
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
                  <b aria-hidden="true">→</b>
                  <span className="comparison-side-label comparison-side-model">
                    {primaryPred?.is_rule
                      ? bilingual(lang, "规则输出", "Rule output")
                      : bilingual(lang, "当前模型", "Model")}
                  </span>
                  <span className={labelBadgeClass(primaryPred?.model_label)}>
                    {primaryPred?.model_label
                      ? displayLabelText(primaryPred.model_label, lang)
                      : modelRunId
                        ? bilingual(lang, "未输出", "None")
                        : bilingual(lang, "未选 Run", "No Run")}
                  </span>
                  {predMatches !== null && (
                    <strong className={predMatches ? "comparison-neutral" : "comparison-fail"}>
                      {predMatches ? bilingual(lang, "一致", "Match") : bilingual(lang, "不一致", "Mismatch")}
                    </strong>
                  )}
                </div>

                <button
                  type="button"
                  className="button button-quiet detail-back-button"
                  onClick={() => setSelectedIssueId("")}
                >
                  {bilingual(lang, "← 返回筛选结果", "← Back to gallery")}
                </button>

                <div className="detail-actions">
                  <button
                    type="button"
                    className="button button-quiet"
                    onClick={() => {
                      const win = window as unknown as {
                        openBatchDraft?: (ids: string[], source: string) => void;
                      };
                      if (typeof win.openBatchDraft === "function") {
                        win.openBatchDraft([selectedIssueId], "single");
                      } else {
                        navigateWorkbenchPage("prediction");
                      }
                    }}
                  >
                    {bilingual(lang, "API 推理", "API inference")}
                  </button>
                  <button
                    type="button"
                    className="history-inline-button"
                    onClick={() => setHistoryModalKind("model")}
                  >
                    {bilingual(lang, "Run 历史", "Run history")} · {(detail?.predictions || []).length}{" "}
                    <kbd className="review-control-shortcut">P</kbd>
                  </button>
                </div>
              </div>

              {primaryPred?.reason && (
                <details className="review-note-details" open>
                  <summary>{bilingual(lang, "当前模型判断理由", "Model reasoning")}</summary>
                  <div className="review-note">{primaryPred.reason}</div>
                </details>
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

          <aside ref={reviewAnchorRef} className="review-pane">
            <form
              className="review-form"
              onSubmit={(e) => {
                e.preventDefault();
                submitMutation.mutate();
              }}
            >
              {isCombinedWorkflow && (
                <section className="review-section issue-tag-section">
                  <div className="review-section-heading">
                    <div>
                      <h2>
                        {bilingual(lang, "Issue 标签", "Issue tags")}{" "}
                        <span className="status-chip">{bilingual(lang, "联合", "Combined")}</span>
                      </h2>
                    </div>
                    <div className="review-heading-actions">
                      <button
                        type="button"
                        className="history-inline-button"
                        onClick={() => setHistoryModalKind("shared")}
                      >
                        {bilingual(lang, "汇总", "Summary")}{" "}
                        <kbd className="review-control-shortcut">L</kbd>
                      </button>
                      <button
                        type="button"
                        className="history-inline-button"
                        onClick={() => setDiscussionOpen(true)}
                      >
                        {bilingual(lang, "讨论", "Discuss")}
                        {discussionCount > 0 ? ` · ${discussionCount}` : ""}{" "}
                        <kbd className="review-control-shortcut">D</kbd>
                      </button>
                    </div>
                  </div>

                  <div className="review-expected-output-field">
                    <div className="review-expected-output-heading">
                      <span>{bilingual(lang, "期望输出", "Expected output")}</span>
                      <span className={`derived-review-status${outputConflict ? " is-conflict" : ""}`}>
                        {outputConflict
                          ? bilingual(lang, "标签冲突", "Conflict")
                          : expectedOutput
                            ? displayLabelText(expectedOutput, lang)
                            : bilingual(lang, "待补充", "Pending")}
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
                      onChange={(v) => {
                        setExpectedOutput(v);
                        setManualOutput(Boolean(v));
                      }}
                    />
                  </div>

                  <ReviewTagSelector
                    catalog={tagCatalog}
                    selectedTags={selectedTags}
                    onChange={setSelectedTags}
                    lang={lang}
                    disabled={!canWrite}
                    canCreateCustom={canWrite}
                    onCatalogRefresh={() =>
                      void queryClient.invalidateQueries({ queryKey: ["dashboard-config"] })
                    }
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

                  <label className="review-reason">
                    <span>{bilingual(lang, "标签依据 / 说明", "Label rationale")}</span>
                    <textarea
                      rows={2}
                      value={caseRationale}
                      disabled={!canWrite}
                      onChange={(e) => setCaseRationale(e.target.value)}
                      placeholder={bilingual(
                        lang,
                        "说明 Case 标签依据；输入 @ 可通知同事",
                        "Explain Case label rationale",
                      )}
                    />
                  </label>
                </section>
              )}

              <section className="review-section model-error-section">
                <div className="review-section-heading">
                  <h2>{bilingual(lang, "模型结果 Review", "Model result Review")}</h2>
                  <div className="review-heading-actions">
                    <button
                      type="button"
                      className="history-inline-button"
                      onClick={() => setDiscussionOpen(true)}
                    >
                      {bilingual(lang, "讨论", "Discuss")}{" "}
                      <kbd className="review-control-shortcut">D</kbd>
                    </button>
                    <button
                      type="button"
                      className="history-inline-button"
                      onClick={() => setHistoryModalKind("review")}
                    >
                      {bilingual(lang, "历史", "History")} · {(detail?.annotations || []).length}{" "}
                      <kbd className="review-control-shortcut">J</kbd>
                    </button>
                  </div>
                </div>

                {!modelRunId ? (
                  <div className="ra-no-run-callout">
                    <span>
                      {bilingual(
                        lang,
                        "未选 Model Run：模型复核暂不可用，Case 标签仍可提交。",
                        "No Model Run selected: model review unavailable, Case label can still be saved.",
                      )}
                    </span>
                    <button
                      type="button"
                      className="text-link"
                      onClick={() => setSelectedIssueId("")}
                    >
                      {bilingual(lang, "选择 Model Run", "Select Model Run")}
                    </button>
                  </div>
                ) : (
                  <div className="ra-filter-field">
                    <span>{bilingual(lang, "复核状态", "Review status")}</span>
                    <UiSelect
                      value={modelReviewStatus}
                      options={MODEL_REVIEW_STATUS_OPTIONS.map((o) => ({
                        value: o.value,
                        label: bilingual(lang, o.zh, o.en),
                      }))}
                      disabled={!canWrite}
                      ariaLabel={bilingual(lang, "复核状态", "Review status")}
                      onChange={setModelReviewStatus}
                    />
                  </div>
                )}

                <label className="review-reason">
                  <span>{bilingual(lang, "模型为什么判错？", "Why did the model err?")}</span>
                  <textarea
                    ref={noteRef}
                    rows={3}
                    value={reviewNote}
                    disabled={!canWrite || !modelRunId}
                    onChange={(e) => setReviewNote(e.target.value)}
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
                        if (canWrite && !outputConflict && !submitMutation.isPending) {
                          submitMutation.mutate();
                        }
                      }
                    }}
                    placeholder={bilingual(
                      lang,
                      "说明关键证据；输入 @ 可通知同事。",
                      "Explain key evidence; type @ to mention.",
                    )}
                  />
                </label>

                <div className="ra-filter-field">
                  <span>{bilingual(lang, "缺失信息（多选）", "Missing evidence")}</span>
                  <MultiSelect
                    values={missingEvidence}
                    options={evidenceCatalog.map((ev) => ({
                      value: ev.key,
                      label: lang === "en" && ev.label_en ? ev.label_en : ev.label || ev.key,
                    }))}
                    lang={lang}
                    disabled={!canWrite}
                    ariaLabel={bilingual(lang, "缺失信息", "Missing evidence")}
                    placeholder={bilingual(lang, "已选 0 项", "0 selected")}
                    onChange={setMissingEvidence}
                  />
                </div>

                <div className="review-attachment-field">
                  <div className="screenshot-paste-zone is-compact">
                    <span className="screenshot-paste-copy">
                      <strong>{bilingual(lang, "复核截图", "Screenshots")}</strong>
                      <small>{bilingual(lang, "最多 4 张 · 随保存上传", "Up to 4 images")}</small>
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

                <div className="ra-filter-field">
                  <span>{bilingual(lang, "复核人 (SSO)", "Reviewer (SSO)")}</span>
                  <input type="text" value={username || "—"} readOnly />
                </div>

                <button
                  type="submit"
                  className="button button-primary full-width review-save-button ra-primary-touch"
                  disabled={
                    !canWrite ||
                    outputConflict ||
                    (!isCombinedWorkflow && !modelRunId) ||
                    submitMutation.isPending
                  }
                >
                  {submitMutation.isPending
                    ? bilingual(lang, "提交中…", "Submitting…")
                    : isCombinedWorkflow
                      ? modelRunId
                        ? bilingual(lang, "提交联合复核", "Submit combined review")
                        : bilingual(lang, "提交问题标注", "Submit case label")
                      : bilingual(lang, "保存 Review", "Save Review")}
                </button>
              </section>
            </form>
          </aside>
        </section>

        <IssueDiscussion
          open={discussionOpen}
          issueId={selectedIssueId}
          reviewOrigin={modelRunId ? { model_run_id: modelRunId, campaign_id: workSplitId } : null}
          lang={lang}
          username={username}
          canWrite={canWrite}
          isAdmin={isAdmin}
          onClose={() => setDiscussionOpen(false)}
          onCountChange={setDiscussionCount}
        />

        <ModalDialog
          open={historyModalKind !== null}
          wide
          lang={lang}
          title={
            historyModalKind === "model"
              ? `${bilingual(lang, "评测 Run 历史", "Model Run history")} · ${selectedIssueId}`
              : historyModalKind === "shared"
                ? `${bilingual(lang, "共享标注结论", "Shared Case Label")} · ${selectedIssueId}`
                : `${bilingual(lang, "Review 历史", "Review history")} · ${selectedIssueId}`
          }
          onClose={() => setHistoryModalKind(null)}
        >
          {historyModalKind === "model" && (
            <div className="ra-decision-modal-list">
              {(detail?.predictions || []).length === 0 ? (
                <p className="muted">{bilingual(lang, "暂无模型预测记录。", "No model predictions.")}</p>
              ) : (
                (detail?.predictions || []).map((p, idx) => (
                  <article key={`${p.model_run_id}-${idx}`} className="comment-thread-item">
                    <div className="comment-thread-meta">
                      <strong>{p.run_name || p.model_run_id}</strong>
                      <span>
                        <span className={labelBadgeClass(p.model_label)}>
                          {displayLabelText(p.model_label, lang)}
                        </span>
                      </span>
                    </div>
                    {p.reason && <p>{p.reason}</p>}
                  </article>
                ))
              )}
            </div>
          )}

          {historyModalKind === "review" && (
            <div className="ra-decision-modal-list">
              {(detail?.annotations || []).length === 0 ? (
                <p className="muted">{bilingual(lang, "暂无 Review 历史。", "No review history yet.")}</p>
              ) : (
                (detail?.annotations || []).map((ann) => {
                  const canRevoke =
                    isAdmin ||
                    (canWrite &&
                      ann.author_verified &&
                      String(ann.author || "").toLowerCase() === username.toLowerCase());
                  return (
                    <article key={String(ann.id)} className="comment-thread-item">
                      <div className="comment-thread-meta">
                        <strong>{ann.author || "—"}</strong>
                        <span>
                          {ann.model_run_id ? `Run ${ann.model_run_id} · ` : ""}
                          {formatCstTime(ann.created_at, lang)}
                        </span>
                      </div>
                      {ann.note && <p>{ann.note}</p>}
                      {canRevoke && (
                        <button
                          type="button"
                          className="button button-quiet"
                          disabled={revokeReviewMutation.isPending}
                          onClick={() => revokeReviewMutation.mutate(ann.id)}
                        >
                          {bilingual(lang, "撤销此条 Review", "Revoke review")}
                        </button>
                      )}
                    </article>
                  );
                })
              )}
            </div>
          )}

          {historyModalKind === "shared" && (
            <div className="ra-decision-modal-list">
              <p>
                <strong>{bilingual(lang, "当前共享结论：", "Shared conclusion: ")}</strong>
                <span className={labelBadgeClass(detail?.label_state?.expected_output)}>
                  {displayLabelText(detail?.label_state?.expected_output, lang)}
                </span>{" "}
                ({decisionStateLabel(detail?.label_state?.state, lang)})
              </p>
              <a
                className="button button-secondary"
                href={`${withWorkbenchBase("/case-labeling")}?issue=${encodeURIComponent(selectedIssueId)}${baselinesKey ? `&baselines=${encodeURIComponent(baselinesKey)}` : ""}`}
              >
                {bilingual(lang, "前往问题标注工作台查看裁决", "Open in Case labeling")}
              </a>
            </div>
          )}
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
  const tagFilterOptions: MultiSelectOption[] = tagCatalog.map((t) => ({
    value: t.key,
    label: lang === "en" && t.label_en ? t.label_en : t.label || t.key,
    group: t.group || "",
  }));

  const evidenceFilterOptions: MultiSelectOption[] = evidenceCatalog.map((e) => ({
    value: e.key,
    label: lang === "en" && e.label_en ? e.label_en : e.label || e.key,
  }));

  const fromIdx = totalCases > 0 ? (page - 1) * pageSize + 1 : 0;
  const toIdx = Math.min(page * pageSize, totalCases);

  return (
    <div className="review-gallery-view ra-review-gallery-root">
      <section className="review-commandbar">
        <div className="mobile-filter-bar">
          <button
            type="button"
            className="button button-quiet mobile-filter-toggle"
            aria-expanded={filtersOpenMobile}
            onClick={() => setFiltersOpenMobile((o) => !o)}
          >
            <span>{bilingual(lang, "复核筛选", "Review filters")}</span>
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
                placeholder={bilingual(lang, "Issue ID / 场景", "Issue ID / scene")}
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
            <span>Model Run</span>
            <UiSelect
              value={modelRunId}
              options={[
                { value: "", label: bilingual(lang, "不限 Run", "All Runs") },
                ...runs.map((r) => ({ value: r.id, label: r.name || r.id })),
              ]}
              ariaLabel="Model Run"
              onChange={(v) => {
                setModelRunId(v);
                setWorkSplitId("");
                setWorkAssignee("");
                setComparisons(v ? ["mismatch"] : []);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "模型对比", "Comparison")}</span>
            <MultiSelect
              values={comparisons}
              options={[
                { value: "mismatch", label: bilingual(lang, "模型判错 (MISMATCH)", "Mismatch") },
                { value: "match", label: bilingual(lang, "模型判对 (MATCH)", "Match") },
                { value: "no_gt", label: bilingual(lang, "缺 GT (NO GT)", "No GT") },
                { value: "none", label: bilingual(lang, "未输出 (NONE)", "None") },
              ]}
              lang={lang}
              disabled={!modelRunId}
              ariaLabel={bilingual(lang, "模型对比", "Comparison")}
              placeholder={bilingual(lang, "全部对比状态", "All")}
              onChange={(v) => {
                setComparisons(v);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "复核状态", "Review status")}</span>
            <MultiSelect
              values={reviewStatuses}
              options={[
                { value: "unreviewed", label: bilingual(lang, "未复核", "Unreviewed") },
                { value: "needs_review", label: bilingual(lang, "待复核", "Needs review") },
                { value: "completed", label: bilingual(lang, "已完成", "Completed") },
              ]}
              lang={lang}
              ariaLabel={bilingual(lang, "复核状态", "Review status")}
              placeholder={bilingual(lang, "全部复核状态", "All statuses")}
              onChange={(v) => {
                setReviewStatuses(v);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "任务分配", "Task split")}</span>
            <UiSelect
              value={workSplitId}
              options={[
                { value: "", label: bilingual(lang, "全部任务", "All splits") },
                ...splits.map((s) => ({ value: s.split_id, label: s.name || s.split_id })),
              ]}
              ariaLabel={bilingual(lang, "任务分配", "Task split")}
              onChange={(v) => {
                setWorkSplitId(v);
                setWorkAssignee("");
                setPage(1);
              }}
            />
          </div>

          {workSplitId && (
            <div className="ra-filter-field">
              <span>{bilingual(lang, "分配人", "Assignee")}</span>
              <UiSelect
                value={workAssignee}
                options={[
                  { value: "", label: bilingual(lang, "全部成员", "All assignees") },
                  ...splitAssignees.map((m) => ({ value: m, label: m })),
                ]}
                ariaLabel={bilingual(lang, "分配人", "Assignee")}
                onChange={(v) => {
                  setWorkAssignee(v);
                  setPage(1);
                }}
              />
            </div>
          )}

          <div className="ra-filter-field">
            <span>{bilingual(lang, "复核人", "Reviewer")}</span>
            <MultiSelect
              values={reviewers}
              options={(casesQuery.data?.reviewers || []).map((r) => ({ value: r, label: r }))}
              lang={lang}
              ariaLabel={bilingual(lang, "复核人", "Reviewer")}
              placeholder={bilingual(lang, "全部复核人", "All reviewers")}
              onChange={(v) => {
                setReviewers(v);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>GT</span>
            <MultiSelect
              values={gtLabels}
              options={CORE_LABELS.map((l) => ({ value: l, label: displayLabelText(l, lang) }))}
              lang={lang}
              ariaLabel="GT"
              placeholder={bilingual(lang, "全部 GT", "All GT")}
              onChange={(v) => {
                setGtLabels(v);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "模型标注", "Model label")}</span>
            <MultiSelect
              values={modelLabels}
              options={MODEL_LABELS.map((l) => ({ value: l, label: displayLabelText(l, lang) }))}
              lang={lang}
              ariaLabel={bilingual(lang, "模型标注", "Model label")}
              placeholder={bilingual(lang, "全部模型标注", "All model labels")}
              onChange={(v) => {
                setModelLabels(v);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "Issue 标签", "Issue tags")}</span>
            <MultiSelect
              values={issueTagsFilter}
              options={tagFilterOptions}
              lang={lang}
              ariaLabel={bilingual(lang, "Issue 标签", "Issue tags")}
              placeholder={bilingual(lang, "全部 Issue 标签", "All tags")}
              onChange={(v) => {
                setIssueTagsFilter(v);
                setPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span>{bilingual(lang, "缺失信息", "Missing evidence")}</span>
            <MultiSelect
              values={missingEvidenceFilter}
              options={evidenceFilterOptions}
              lang={lang}
              ariaLabel={bilingual(lang, "缺失信息", "Missing evidence")}
              placeholder={bilingual(lang, "全部证据", "All evidence")}
              onChange={(v) => {
                setMissingEvidenceFilter(v);
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

        <div className={`ra-summary-toolbar-actions${filtersOpenMobile ? " is-mobile-open" : ""}`}>
          <button type="button" className="button button-quiet" onClick={resetFilters}>
            {bilingual(lang, "重置", "Reset")}
          </button>
        </div>
      </section>

      <section className="gallery-panel">
        <div className="gallery-heading">
          <div className="case-labeling-heading-copy">
            <h2>{bilingual(lang, "复核图库", "Review gallery")}</h2>
            <span className="count-pill">
              {totalCases > 0
                ? bilingual(lang, `第 ${fromIdx}–${toIdx} / ${totalCases}`, `${fromIdx}–${toIdx} of ${totalCases}`)
                : "0"}
            </span>
          </div>
          <div className="gallery-heading-actions">
            <a
              className="button button-quiet"
              href={withWorkbenchBase(`/api/cases/export?${casesQueryParams}&format=csv`)}
              target="_blank"
              rel="noreferrer"
            >
              {bilingual(lang, "导出 Issue", "Export Issues")}
            </a>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => navigateWorkbenchPage("runs")}
            >
              {bilingual(lang, "上传模型结果", "Upload Model Run")}
            </button>
            {isAdmin && (
              <button
                type="button"
                className="button button-primary"
                onClick={() => setNewAllocOpen(true)}
              >
                {bilingual(lang, "新建任务分配", "New assignment")}
              </button>
            )}
          </div>
        </div>

        <div className="issue-grid" aria-live="polite">
          {pageItems.map((item) => {
            const thumbUrl = normalizeAssetUrl(item.thumbnail?.url);
            const voyagerUrl = safeExternalUrl(item.voyager_issue_url);
            const predLabel = item.prediction?.label || "";
            const sharedLabel =
              item.label_state?.state === "resolved" ? item.label_state.expected_output : "";
            return (
              <article key={item.issue_id} className="issue-card" data-issue-id={item.issue_id}>
                <button
                  type="button"
                  className="issue-card-open"
                  aria-label={bilingual(lang, `打开 ${item.issue_id} Review`, `Open ${item.issue_id} Review`)}
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
                  {modelRunId && item.prediction?.comparable && (
                    <span
                      className={`comparison-chip issue-thumbnail-status ${item.prediction.mismatch ? "comparison-mismatch" : "comparison-match"}`}
                    >
                      {item.prediction.mismatch ? "MISMATCH" : "MATCH"}
                    </span>
                  )}
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
                      {(item.is_excluded || item.annotation?.is_excluded) && (
                        <span className="issue-card-flag issue-card-flag-excluded">
                          {bilingual(lang, "应该排除", "Exclude")}
                        </span>
                      )}
                      <span className="issue-label-pair issue-human-label">
                        <small>{bilingual(lang, "人工", "Human")}</small>
                        <span className={labelBadgeClass(sharedLabel)}>
                          {sharedLabel
                            ? displayLabelText(sharedLabel, lang)
                            : decisionStateLabel(item.label_state?.state, lang)}
                        </span>
                      </span>
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
                      <small>{bilingual(lang, "模型", "Model")}</small>
                      <span className={labelBadgeClass(predLabel)}>
                        {displayLabelText(predLabel, lang)}
                      </span>
                    </span>
                    {item.annotation?.author && (
                      <span className="issue-reviewer">
                        {item.annotation.author}
                        {item.annotation.author_verified ? " · SSO" : ""}
                      </span>
                    )}
                  </div>
                </div>
              </article>
            );
          })}

          {!casesQuery.isPending && pageItems.length === 0 && (
            <div className="empty-state issue-grid-empty">
              <h2>{bilingual(lang, "当前筛选没有匹配的 Case", "No matching cases")}</h2>
            </div>
          )}
        </div>

        <Pagination
          page={page}
          pageSize={pageSize}
          total={totalCases}
          lang={lang}
          loading={casesQuery.isFetching}
          onPageChange={setPage}
          onPageSizeChange={(s) => {
            setPageSize(s);
            setPage(1);
          }}
        />
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

      <NewAllocationModal
        open={newAllocOpen}
        lang={lang}
        eligibleMembers={eligibleMembers}
        onClose={() => setNewAllocOpen(false)}
        onCreated={() => {
          void queryClient.invalidateQueries({ queryKey: ["review-work-splits"] });
          void queryClient.invalidateQueries({ queryKey: ["review-assignments-list"] });
        }}
      />

      <CaseMediaPreviewModal
        issueId={previewMediaIssueId}
        lang={lang}
        onClose={() => setPreviewMediaIssueId(null)}
      />
    </div>
  );
};
