import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, UiLanguage, withWorkbenchBase } from "../bridge/useWorkbenchBridge";
import { AllocationGroupSetup } from "../components/allocation/AllocationGroupSetup";
import { AllocationLivePreview } from "../components/allocation/AllocationLivePreview";
import { BatchCard } from "../components/allocation/BatchCard";
import { TaskAllocationDialog } from "../components/allocation/TaskAllocationDialog";
import { useAssignmentNaming } from "../components/allocation/useAssignmentNaming";
import {
  AccessUserItem,
  AllocationDraft,
  AllocationPreviewPlan,
  BilingualMessage,
  LabelingTaskItem,
  WorkSplitItem,
  campaignsHistoryHref,
  createInitialAllocationDraft,
  formatClassicTime,
  groupAllocationSetupError,
  parseBilingualError,
  reviewAssignmentCanReview,
} from "../components/allocation/allocationMath";
import { showWorkbenchToast } from "../components/ui/Toast";

export interface LabelingNewTaskPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
  isAdmin: boolean;
  username: string;
  verified: boolean;
}

interface CreatedLabelingTaskResult {
  task?: { id?: string; name?: string };
  total?: number;
  reviewers_per_issue?: number;
  overlap_ratio?: number;
  assignments?: Array<{ name?: string; count?: number }>;
}

function readLabelingFiltersFromUrl(selectedBaselines: string[]): Record<string, string> {
  const params = new URLSearchParams(window.location.search);
  return {
    baselines: selectedBaselines.join(",") || params.get("baselines") || "",
    task_id: params.get("task") || "",
    q: params.get("q") || "",
    issue_ids: params.get("issue_ids") || "",
    target_group: params.get("target_group") || "",
    issue_tags: params.get("issue_tags") || "",
    status: params.get("status") || "",
    author: params.get("author") || "",
    assignee: params.get("assignee") || "",
    cluster: params.get("cluster") || "",
    exclusion: params.get("exclusion") || "",
    gt: params.get("gt") || "",
    gt_relation: params.get("gt_relation") || "",
    comment_state: params.get("comment_state") || "",
    label: params.get("label") || "",
  };
}

export const LabelingNewTaskPage: React.FC<LabelingNewTaskPageProps> = ({
  active,
  lang,
  selectedBaselines,
  isAdmin,
  username,
  verified,
}) => {
  const queryClient = useQueryClient();
  const baselineQuery = selectedBaselines.join(",");
  const filters = useMemo(
    () => readLabelingFiltersFromUrl(selectedBaselines),
    [selectedBaselines],
  );

  const [draft, setDraft] = useState<AllocationDraft>(() => createInitialAllocationDraft());
  const [seed, setSeed] = useState("");
  const [plan, setPlan] = useState<AllocationPreviewPlan | null>(null);
  const [lastPlan, setLastPlan] = useState<AllocationPreviewPlan | null>(null);
  const [previewError, setPreviewError] = useState<BilingualMessage | null>(null);
  const [previewRetry, setPreviewRetry] = useState(false);
  const [previewPending, setPreviewPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [closed, setClosed] = useState(false);
  const [createdResult, setCreatedResult] = useState<CreatedLabelingTaskResult | null>(null);
  const [editCampaignId, setEditCampaignId] = useState<string | null>(null);
  const [resetTick, setResetTick] = useState(0);

  const previewTimerRef = useRef<number | null>(null);
  const previewAbortRef = useRef<AbortController | null>(null);
  const previewReqIdRef = useRef<string>("");
  const previewSerializedRef = useRef<string>("");

  // Reset form when entering page
  useEffect(() => {
    if (!active) return;
    setDraft(createInitialAllocationDraft());
    setSeed("");
    setPlan(null);
    setLastPlan(null);
    setPreviewError(null);
    setPreviewRetry(false);
    setClosed(false);
    setCreatedResult(null);
    previewSerializedRef.current = "";
    setResetTick((n) => n + 1);
  }, [active]);

  // Queries: pool count, tasks history, combined tasks, access users, model runs (for batch names)
  const poolQuery = useQuery<{ total?: number }>({
    queryKey: ["labeling-new-task-pool", filters],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ page: "1", page_size: "1" });
      Object.entries(filters).forEach(([k, v]) => {
        if (v) params.set(k, v);
      });
      return apiRequest<{ total?: number }>(`/api/labeling/cases?${params.toString()}`, { signal });
    },
    enabled: active && isAdmin,
    staleTime: 10_000,
  });

  const tasksQuery = useQuery<{ items: LabelingTaskItem[] }>({
    queryKey: ["labeling-tasks-history", baselineQuery],
    queryFn: ({ signal }) => {
      const qs = baselineQuery ? `?baselines=${encodeURIComponent(baselineQuery)}` : "";
      return apiRequest<{ items: LabelingTaskItem[] }>(`/api/labeling/tasks${qs}`, { signal });
    },
    enabled: active,
    staleTime: 10_000,
  });

  const combinedQuery = useQuery<{ items: WorkSplitItem[] }>({
    queryKey: ["labeling-combined-tasks", username, verified],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        limit: "100",
        lifecycle: "current",
        group_by_version: "true",
        version_only: "false",
      });
      return apiRequest<{ items: WorkSplitItem[] }>(`/api/cases/work-splits?${params.toString()}`, {
        signal,
      });
    },
    enabled: active,
    staleTime: 10_000,
  });

  const usersQuery = useQuery<{ items: AccessUserItem[] }>({
    queryKey: ["access-users"],
    queryFn: ({ signal }) => apiRequest<{ items: AccessUserItem[] }>("/api/access-users", { signal }),
    enabled: active && isAdmin,
    staleTime: 60_000,
  });

  const runsQuery = useQuery<{ items: Array<{ id: string; name: string }> }>({
    queryKey: ["review-assignments-runs", baselineQuery],
    queryFn: ({ signal }) => {
      const qs = baselineQuery ? `?baselines=${encodeURIComponent(baselineQuery)}` : "";
      return apiRequest<{ items: Array<{ id: string; name: string }> }>(`/api/model-runs${qs}`, {
        signal,
      });
    },
    enabled: active,
    staleTime: 30_000,
  });

  const caseCount = Number(poolQuery.data?.total || plan?.group_coverage?.case_count || 0);

  const datasetLabels = useMemo(() => {
    const ids = (filters.baselines || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const win = window as unknown as {
      assignmentBaselineLabels?: (ids: string[]) => string[];
    };
    if (typeof win.assignmentBaselineLabels === "function") {
      return win.assignmentBaselineLabels(ids);
    }
    return ids;
  }, [filters.baselines]);

  const namingContext = useMemo(() => {
    const activeGroups = draft.groups.filter((g) => (g.coverage_percent ?? 0) > 0);
    const reviewersPerIssue = Math.max(1, activeGroups.length);
    const coverage = activeGroups.slice(1).reduce((sum, g) => sum + (g.coverage_percent ?? 0), 0);
    const overlapRatio = Math.min(1, coverage / 100);
    const assignees = new Set(
      draft.groups.flatMap((g) => g.members.map((m) => m.name).filter(Boolean)),
    );
    const baselineIds = (filters.baselines || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    return {
      assignmentKind: "case_labeling" as const,
      baselineIds,
      datasetLabels,
      caseCount,
      reviewersPerIssue,
      overlapRatio,
      memberCount: assignees.size,
      workflowMode: "",
      modelRunId: "",
      runName: "",
      comparison: "all",
    };
  }, [draft.groups, filters.baselines, datasetLabels, caseCount]);

  const naming = useAssignmentNaming({
    enabled: active && isAdmin,
    isAdmin,
    context: namingContext,
    lang,
    resetKey: resetTick,
  });

  const creationBody = useMemo(() => {
    const body: Record<string, unknown> = {
      groups: draft.groups,
      cross_groups: draft.pairing_mode === "custom" ? draft.cross_groups : [],
      pairing_mode: draft.pairing_mode === "paired" ? "paired" : "orthogonal",
      filters,
    };
    const trimmedName = naming.name.trim();
    const trimmedSeed = seed.trim();
    if (trimmedName) body.name = trimmedName;
    if (trimmedSeed) body.seed = Number(trimmedSeed);
    return body;
  }, [draft, filters, naming.name, seed]);

  const cancelPreview = useCallback(() => {
    if (previewTimerRef.current) {
      window.clearTimeout(previewTimerRef.current);
      previewTimerRef.current = null;
    }
    previewAbortRef.current?.abort();
    previewAbortRef.current = null;
  }, []);

  const triggerPreview = useCallback(
    (force = false, immediate = false) => {
      if (!active || !isAdmin || busy) return;
      const serialized = JSON.stringify(creationBody);
      if (!force && serialized === previewSerializedRef.current) return;
      cancelPreview();
      previewSerializedRef.current = serialized;
      const seedVal = creationBody.seed as number | undefined;
      const err =
        groupAllocationSetupError(draft) ||
        (seedVal !== undefined && !Number.isSafeInteger(seedVal)
          ? { zh: "种子必须为整数。", en: "Seed must be an integer." }
          : null);
      setPlan(null);
      setPreviewRetry(false);
      setClosed(false);
      if (err) {
        setPreviewError(err);
        setPreviewPending(false);
        return;
      }
      setPreviewError(null);
      setPreviewPending(true);
      const reqId =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `lt-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      previewReqIdRef.current = reqId;
      const runFetch = async () => {
        const controller = new AbortController();
        previewAbortRef.current = controller;
        const timeout = window.setTimeout(() => controller.abort(), 20000);
        try {
          const res = await apiRequest<{ preview: AllocationPreviewPlan }>("/api/labeling/tasks", {
            method: "POST",
            signal: controller.signal,
            body: { ...creationBody, request_id: reqId, preview_only: true },
          });
          if (previewReqIdRef.current !== reqId) return;
          setPlan(res.preview);
          setLastPlan(res.preview);
          setPreviewPending(false);
        } catch (failure) {
          if (previewReqIdRef.current !== reqId) return;
          setPreviewError(
            parseBilingualError(
              failure,
              "暂时无法计算预览，请重试。",
              "The preview could not be calculated. Try again.",
            ),
          );
          setPreviewRetry(true);
          setLastPlan(null);
          setPreviewPending(false);
        } finally {
          window.clearTimeout(timeout);
        }
      };
      if (immediate) void runFetch();
      else {
        previewTimerRef.current = window.setTimeout(() => {
          previewTimerRef.current = null;
          void runFetch();
        }, 120);
      }
    },
    [active, isAdmin, busy, creationBody, draft, cancelPreview],
  );

  useEffect(() => {
    if (!active || !isAdmin) return;
    triggerPreview(false, false);
    return () => cancelPreview();
  }, [active, isAdmin, creationBody]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = async () => {
    if (!isAdmin || !plan || busy || closed) return;
    setBusy(true);
    try {
      const res = await apiRequest<CreatedLabelingTaskResult>("/api/labeling/tasks", {
        method: "POST",
        body: {
          ...creationBody,
          request_id: previewReqIdRef.current,
          preview_token: plan.preview_token,
        },
      });
      setClosed(true);
      setCreatedResult(res);
      void queryClient.invalidateQueries({ queryKey: ["labeling-tasks-history"] });
      showWorkbenchToast(bilingual(lang, "标注任务已创建。", "Labeling task created."));
    } catch (error) {
      const err = error as { status?: number };
      if (err.status === 409) {
        setPlan(null);
        setPreviewRetry(true);
        setPreviewError(
          parseBilingualError(
            error,
            "暂时无法计算预览，请重试。",
            "The preview could not be calculated. Try again.",
          ),
        );
      }
      const msg = parseBilingualError(
        error,
        "无法预览分配，请检查任务配置。",
        "Unable to plan the allocation. Check the task settings.",
      );
      showWorkbenchToast(bilingual(lang, msg.zh, msg.en), true);
    } finally {
      setBusy(false);
    }
  };

  const leaveTaskPage = () => {
    const hs = window.history.state as { page?: string; returnTo?: string } | null;
    if (hs?.page === "labeling-new-task" && hs?.returnTo === "labeling") {
      window.history.back();
      return;
    }
    const win = window as unknown as {
      showPage?: (page: string, opts?: Record<string, unknown>) => void;
    };
    if (typeof win.showPage === "function") {
      win.showPage("labeling", { historyMode: "replace" });
    } else {
      window.location.assign(withWorkbenchBase("/case-labeling"));
    }
  };

  const openLabelingTask = (taskId: string) => {
    if (!taskId) return;
    const url = new URL(withWorkbenchBase("/case-labeling"), window.location.origin);
    if (baselineQuery) url.searchParams.set("baselines", baselineQuery);
    url.searchParams.set("task", taskId);
    window.location.assign(`${url.pathname}${url.search}`);
  };

  const copyCombinedShareLink = async (splitId: string) => {
    const url = new URL(withWorkbenchBase("/review-assignments"), window.location.origin);
    url.searchParams.set("lifecycle", "all");
    url.searchParams.set("split", splitId);
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(url.href);
        showWorkbenchToast(bilingual(lang, "任务分配链接已复制。", "Assignment link copied."));
        return;
      } catch {
        /* fallback */
      }
    }
    window.prompt(bilingual(lang, "请复制任务分配链接：", "Copy the assignment link:"), url.href);
  };

  const runNameLookup = useCallback(
    (runId?: string) => {
      const v = String(runId || "").trim();
      if (!v) return bilingual(lang, "未绑定 Model Run", "No Model Run");
      return runsQuery.data?.items?.find((r) => String(r.id) === v)?.name || v;
    },
    [runsQuery.data, lang],
  );

  const combinedItems = useMemo(
    () =>
      (combinedQuery.data?.items || []).filter(
        (item) =>
          item.workflow_mode === "model_review_and_case_label" && reviewAssignmentCanReview(item),
      ),
    [combinedQuery.data],
  );

  const historyTasks = tasksQuery.data?.items || [];
  const shownPlan = plan || (!previewRetry ? lastPlan : null);
  const isPending = Boolean(previewPending && !plan && !previewError);

  return (
    <div className="case-experiment-layout ra-labeling-new-task-root" data-react-island="labeling-new-task">
      <section className="intent-experiment-create case-experiment-create assignment-composer">
        <div className="intent-experiment-section-heading">
          <div>
            <h3>{bilingual(lang, "分配配置", "Assignment setup")}</h3>
          </div>
          <button
            className="button button-quiet"
            type="button"
            id="labelingTaskBack"
            onClick={leaveTaskPage}
          >
            {bilingual(lang, "返回图库", "Back to gallery")}
          </button>
        </div>

        <div className="case-experiment-create-body">
          <div className="case-experiment-fields assignment-config-fields">
            <label className="work-split-seed labeling-task-name">
              <span>{bilingual(lang, "实验名称", "Experiment name")}</span>
              <span className="intent-experiment-name-control">
                <input
                  id="labelingTaskName"
                  type="text"
                  maxLength={80}
                  placeholder={bilingual(
                    lang,
                    "自动生成实验名称",
                    "Generated from the experiment configuration",
                  )}
                  autoComplete="off"
                  value={naming.name}
                  onChange={(e) => naming.setManualName(e.target.value)}
                />
                <small
                  className="assignment-name-source"
                  id="labelingTaskNameStatus"
                  data-status={naming.status}
                  data-source={naming.source}
                  title={naming.statusTitle}
                  aria-live="polite"
                >
                  {naming.statusText}
                </small>
                <button
                  className="assignment-name-refresh"
                  id="labelingTaskRefreshName"
                  type="button"
                  disabled={!naming.canRefresh}
                  data-loading={String(naming.status === "loading")}
                  aria-busy={naming.status === "loading"}
                  aria-label={naming.refreshLabel}
                  title={naming.refreshLabel}
                  onClick={naming.refreshName}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path d="M20 7v5h-5M4 17v-5h5M6.1 7a7 7 0 0 1 11.6-1L20 9M4 15l2.3 3A7 7 0 0 0 17.9 17" />
                  </svg>
                </button>
              </span>
            </label>
          </div>

          <div className="allocation-creation-layout">
            <AllocationGroupSetup
              id="labelingTaskGroupSetup"
              draft={draft}
              users={usersQuery.data?.items || []}
              lang={lang}
              editable={isAdmin && !busy}
              caseCount={caseCount}
              quotaBasis="total"
              onChange={(next, meta) => {
                setDraft(next);
                if (meta.immediate) {
                  window.setTimeout(() => triggerPreview(false, true), 0);
                }
              }}
              onFlush={() => triggerPreview(false, true)}
            />

            <section className="allocation-creation-preview">
              <div className="allocation-preview-heading">
                <h3>{bilingual(lang, "实时预览", "Live preview")}</h3>
                <span
                  className="allocation-preview-pending"
                  id="labelingTaskPreviewPending"
                  aria-live="polite"
                  hidden={!(isPending && shownPlan)}
                >
                  <i className="allocation-preview-spinner" aria-hidden="true" />
                  <span>{bilingual(lang, "更新中…", "Updating…")}</span>
                </span>
              </div>
              <p
                className={`dialog-copy${previewError && previewRetry ? " task-allocation-error" : ""}`}
                id="labelingTaskPreviewStatus"
                role="status"
              >
                {previewError
                  ? bilingual(lang, previewError.zh, previewError.en)
                  : isPending && !shownPlan
                    ? bilingual(lang, "正在计算预览…", "Calculating preview…")
                    : ""}
              </p>
              <button
                className="button button-quiet"
                id="labelingTaskRetryPreview"
                type="button"
                hidden={!previewRetry}
                onClick={() => triggerPreview(true, true)}
              >
                {bilingual(lang, "重新计算", "Recalculate")}
              </button>
              <div
                id="labelingTaskPlanPreview"
                className={`allocation-live-content${isPending && shownPlan ? " is-preview-updating" : ""}${previewError && shownPlan ? " is-preview-stale" : ""}`}
                hidden={!shownPlan}
              >
                {shownPlan && (
                  <AllocationLivePreview
                    plan={shownPlan}
                    configuredGroups={draft.groups}
                    lang={lang}
                  />
                )}
              </div>
            </section>
          </div>

          <div className="work-split-toolbar assignment-footer-row">
            <label className="work-split-seed">
              <span>{bilingual(lang, "随机种子（可选）", "Random seed (optional)")}</span>
              <input
                id="labelingTaskSeed"
                type="number"
                inputMode="numeric"
                placeholder={bilingual(lang, "留空则每次不同", "Leave blank to randomize")}
                value={seed}
                onChange={(e) => setSeed(e.target.value)}
              />
            </label>
            <div className="dialog-actions">
              <button
                className="button button-quiet"
                type="button"
                id="labelingTaskCancel"
                onClick={leaveTaskPage}
              >
                {bilingual(lang, "取消", "Cancel")}
              </button>
              <button
                className="button button-primary"
                id="labelingTaskGenerate"
                type="button"
                disabled={!plan || busy || closed}
                onClick={() => void handleSubmit()}
              >
                {busy
                  ? bilingual(lang, "正在创建…", "Creating…")
                  : bilingual(lang, "创建分配", "Create allocation")}
              </button>
            </div>
          </div>

          {createdResult?.task && (
            <div className="work-split-results" id="labelingTaskResults" aria-live="polite">
              <div className="work-split-results-heading">
                <strong>{bilingual(lang, "标注任务已创建", "Labeling task created")}</strong>
                <span>
                  {`${createdResult.task.name || createdResult.task.id || ""} · ${bilingual(
                    lang,
                    `${createdResult.total || 0} 条任务`,
                    `${createdResult.total || 0} tasks`,
                  )} · ${
                    Number(createdResult.reviewers_per_issue || 1) > 1
                      ? bilingual(
                          lang,
                          `交叉 ${Math.round(Number(createdResult.overlap_ratio || 0) * 100)}%`,
                          `Cross-review ${Math.round(Number(createdResult.overlap_ratio || 0) * 100)}%`,
                        )
                      : bilingual(lang, "单人复核", "Single review")
                  }`}
                </span>
                {createdResult.task.id && (
                  <button
                    className="button button-quiet"
                    type="button"
                    onClick={() => openLabelingTask(createdResult.task!.id!)}
                  >
                    {bilingual(lang, "查看该任务", "Open task")}
                  </button>
                )}
              </div>
              <div className="work-split-card-grid">
                {(createdResult.assignments || []).map((item, idx) => (
                  <article key={`${item.name}-${idx}`} className="work-split-card">
                    <header>
                      <strong>{item.name || "—"}</strong>
                      <span>{bilingual(lang, `${item.count || 0} 条`, `${item.count || 0} items`)}</span>
                    </header>
                  </article>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>

      <section
        className="intent-experiment-history case-experiment-history assignment-history"
        aria-labelledby="labelingCombinedTaskTitle"
      >
        <div className="intent-experiment-section-heading labeling-combined-heading">
          <h3 id="labelingCombinedTaskTitle">
            {bilingual(lang, "联合复核任务", "Combined review tasks")}
          </h3>
          <span className="intent-experiment-count" id="labelingCombinedTaskCount">
            {combinedQuery.isSuccess ? String(combinedItems.length) : "—"}
          </span>
          <button
            className="button button-quiet"
            type="button"
            id="labelingCombinedTaskRefresh"
            onClick={() => void combinedQuery.refetch()}
          >
            {bilingual(lang, "刷新", "Refresh")}
          </button>
        </div>
        <p className="quiet-meta">
          {bilingual(lang, "全部当前联合任务 · 与判错复核共用", "All current combined tasks · Shared with Review")}
        </p>
        <p className="quiet-meta" id="labelingCombinedTaskStatus" role="status">
          {combinedQuery.isError
            ? bilingual(lang, "联合任务加载失败，请重试。", "Could not load combined tasks. Retry.")
            : combinedQuery.isLoading
              ? bilingual(lang, "加载中…", "Loading…")
              : ""}
        </p>
        <div className="review-assignment-list" id="labelingCombinedTaskList">
          {combinedItems.length ? (
            combinedItems.map((item) => {
              const detailHref = `${withWorkbenchBase("/review-assignments")}?${new URLSearchParams({
                lifecycle: "current",
                split: item.split_id,
              }).toString()}`;
              return (
                <BatchCard
                  key={item.split_id}
                  item={item}
                  lang={lang}
                  isAdmin={isAdmin}
                  username={username}
                  verified={verified}
                  runNameLookup={runNameLookup}
                  detailHref={detailHref}
                  onEditAllocation={(cid) => setEditCampaignId(cid)}
                  onShareLink={(sid) => void copyCombinedShareLink(sid)}
                />
              );
            })
          ) : combinedQuery.isSuccess ? (
            <div className="review-assignment-empty">
              {bilingual(lang, "暂无当前有效的联合复核任务。", "No active combined review tasks.")}
            </div>
          ) : null}
        </div>
      </section>

      <section
        className="intent-experiment-history case-experiment-history assignment-history"
        aria-labelledby="labelingTaskHistoryTitle"
      >
        <div className="intent-experiment-section-heading">
          <div>
            <h3 id="labelingTaskHistoryTitle">
              {bilingual(lang, "实验记录", "Experiment records")}
            </h3>
          </div>
          <span className="intent-experiment-count" id="labelingTaskHistoryCount">
            {historyTasks.length}
          </span>
          <a
            className="button button-quiet"
            id="labelingTaskCancelledHistory"
            href={campaignsHistoryHref({ purpose: "labeling", lifecycle: "history" })}
          >
            {bilingual(lang, "历史任务与成果", "Task history and evidence")}
          </a>
        </div>

        <div className="intent-experiment-list" id="labelingTaskHistoryList">
          {!historyTasks.length ? (
            <div className="intent-experiment-empty">
              <span>◎</span>
              <strong>{bilingual(lang, "尚未创建实验", "No experiments yet")}</strong>
              <p>
                {bilingual(
                  lang,
                  "从图库筛选 Case，再创建标注实验。",
                  "Filter Cases in the gallery, then create a labeling experiment.",
                )}
              </p>
            </div>
          ) : (
            historyTasks.map((task) => {
              const prog = task.progress || {};
              const total = Number(prog.total || task.member_count || 0);
              const resolved = Number(prog.resolved || 0);
              const conflict = Number(prog.conflict || 0);
              const percent = total ? Math.min(100, Math.round((resolved * 100) / total)) : 0;
              const mode =
                Number(task.reviewers_per_issue || 1) > 1
                  ? bilingual(
                      lang,
                      `${Number(task.reviewers_per_issue)} 人 · ${Math.round(Number(task.overlap_ratio || 0) * 100)}% 交叉盲标`,
                      `${Number(task.reviewers_per_issue)} people · ${Math.round(Number(task.overlap_ratio || 0) * 100)}% cross-label`,
                    )
                  : bilingual(lang, "单人标注", "Single labeler");
              const canEdit =
                Boolean(task.id) &&
                isAdmin &&
                !task.legacy_read_only &&
                (!task.lifecycle || task.lifecycle === "active") &&
                task.is_current !== false;

              return (
                <article key={task.id} className="intent-experiment-item case-experiment-item">
                  <div>
                    <h4>{task.name || bilingual(lang, "未命名实验", "Unnamed experiment")}</h4>
                    <div className="intent-experiment-meta">
                      {`${mode} · ${bilingual(lang, `${total} 个 Case`, `${total} Cases`)} · ${
                        task.created_by || ""
                      }${task.created_at ? ` · ${formatClassicTime(task.created_at)}` : ""}`}
                    </div>
                  </div>
                  <div className="review-assignment-batch-actions">
                    {canEdit && (
                      <button
                        type="button"
                        className="button button-quiet"
                        data-edit-task-allocation={task.id}
                        onClick={() => setEditCampaignId(task.id)}
                      >
                        {bilingual(lang, "修改分配", "Edit allocation")}
                      </button>
                    )}
                    <button
                      className="button button-quiet"
                      type="button"
                      data-open-labeling-task={task.id}
                      onClick={() => openLabelingTask(task.id)}
                    >
                      {bilingual(lang, "打开实验", "Open experiment")}
                    </button>
                  </div>
                  <div className="intent-experiment-detail-row">
                    <div className="intent-experiment-member-stats">
                      <span>{bilingual(lang, `已完成 ${resolved}`, `Completed ${resolved}`)}</span>
                      <span>
                        {bilingual(
                          lang,
                          `待处理 ${Math.max(0, total - resolved)}`,
                          `Pending ${Math.max(0, total - resolved)}`,
                        )}
                      </span>
                      {conflict > 0 && (
                        <span>{bilingual(lang, `冲突 ${conflict}`, `Conflicts ${conflict}`)}</span>
                      )}
                    </div>
                    <div className="intent-experiment-progress">
                      <span className="intent-experiment-progress-track">
                        <i className="is-complete" style={{ width: `${percent}%` }} />
                      </span>
                      <small>{`${percent}%`}</small>
                    </div>
                  </div>
                </article>
              );
            })
          )}
        </div>
      </section>

      <TaskAllocationDialog
        campaignId={editCampaignId}
        lang={lang}
        onClose={() => setEditCampaignId(null)}
        onSaved={() => {
          void queryClient.invalidateQueries({ queryKey: ["labeling-tasks-history"] });
          void queryClient.invalidateQueries({ queryKey: ["labeling-combined-tasks"] });
        }}
      />
    </div>
  );
};
