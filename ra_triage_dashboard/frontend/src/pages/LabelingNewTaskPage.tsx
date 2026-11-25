import React, { useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  formatCstTime,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import {
  AllocationPreviewPanel,
  AllocationPreviewPayload,
} from "../features/allocation/AllocationPreviewPanel";
import { GroupShareEditor } from "../features/allocation/GroupShareEditor";
import {
  AllocationGroup,
  createNewAllocationGroup,
  InputUnit,
  PairingMode,
  ruleBasedAssignmentName,
  validateAllocationGroups,
} from "../features/allocation/rebalance";
import {
  DashboardConfigPayload,
  navigateWorkbenchPage,
  showWorkbenchToast,
} from "../features/review/reviewHelpers";

export interface LabelingNewTaskPageProps {
  active: boolean;
  lang: UiLanguage;
  isAdmin: boolean;
  selectedBaselines: string[];
}

interface LabelingTaskRecord {
  id: string;
  name?: string;
  reviewers_per_issue?: number;
  overlap_ratio?: number;
  member_count?: number;
  created_by?: string;
  created_at?: string;
  progress?: { total?: number; resolved?: number; conflict?: number };
}

interface CombinedSplitItem {
  split_id: string;
  name?: string;
  workflow_mode?: string;
  member_count?: number;
  created_by?: string;
  created_at?: string;
  model_run_id?: string;
}

export const LabelingNewTaskPage: React.FC<LabelingNewTaskPageProps> = ({
  active,
  lang,
  isAdmin,
  selectedBaselines,
}) => {
  const queryClient = useQueryClient();
  const baselinesKey = selectedBaselines.join(",");
  const [unit, setUnit] = useState<InputUnit>("percent");
  const [pairingMode] = useState<PairingMode>("orthogonal");
  const [groups, setGroups] = useState<AllocationGroup[]>(() => [createNewAllocationGroup([])]);
  const [seed, setSeed] = useState("");
  const [name, setName] = useState("");
  const [manualName, setManualName] = useState(false);
  const [nameSource, setNameSource] = useState<"rule" | "llm" | "manual">("rule");
  const [nameLoading, setNameLoading] = useState(false);
  const [createdTaskId, setCreatedTaskId] = useState<string>("");
  const [submitError, setSubmitError] = useState<string>("");
  const nameSeqRef = useRef(0);
  const requestIdRef = useRef<string>(
    typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `lbl-${Date.now()}`,
  );

  // Read inherited gallery filter query params from URL
  const inheritedFilters = useMemo(() => {
    const params = new URLSearchParams(window.location.search);
    return {
      baselines: baselinesKey || params.get("baselines") || "",
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
  }, [baselinesKey, active]);

  const configQuery = useQuery<DashboardConfigPayload>({
    queryKey: ["dashboard-config"],
    queryFn: ({ signal }) => apiRequest<DashboardConfigPayload>("/api/dashboard-config", { signal }),
    enabled: active,
    staleTime: 60_000,
  });

  const membersQuery = useQuery<{ items?: { username: string; access_role?: string }[] }>({
    queryKey: ["access-users-for-labeling-alloc"],
    queryFn: ({ signal }) =>
      apiRequest<{ items?: { username: string; access_role?: string }[] }>("/api/access-users", {
        signal,
      }),
    enabled: active && isAdmin,
    staleTime: 60_000,
  });

  const eligibleMembers = useMemo(
    () =>
      (membersQuery.data?.items || [])
        .filter((u) => ["writer", "admin"].includes(String(u.access_role || "")))
        .map((u) => u.username),
    [membersQuery.data],
  );

  const scopeCountQuery = useQuery<{ total: number }>({
    queryKey: ["labeling-new-task-scope-count", inheritedFilters],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({ ...inheritedFilters, page: "1", page_size: "1" });
      return apiRequest<{ total: number }>(`/api/labeling/cases?${qs.toString()}`, { signal });
    },
    enabled: active && Boolean(inheritedFilters.baselines),
    staleTime: 10_000,
  });

  const tasksQuery = useQuery<{ items?: LabelingTaskRecord[] }>({
    queryKey: ["labeling-tasks-history", baselinesKey],
    queryFn: ({ signal }) =>
      apiRequest<{ items?: LabelingTaskRecord[] }>(
        `/api/labeling/tasks${baselinesKey ? `?baselines=${encodeURIComponent(baselinesKey)}` : ""}`,
        { signal },
      ),
    enabled: active,
    staleTime: 20_000,
  });

  const combinedTasksQuery = useQuery<{ items?: CombinedSplitItem[] }>({
    queryKey: ["labeling-combined-tasks"],
    queryFn: ({ signal }) =>
      apiRequest<{ items?: CombinedSplitItem[] }>(
        "/api/cases/work-splits?limit=100&lifecycle=current&group_by_version=true&version_only=false",
        { signal },
      ),
    enabled: active,
    staleTime: 20_000,
  });

  const caseCount = Number(scopeCountQuery.data?.total || 0);
  const baselinesCatalog = configQuery.data?.baselines || [];
  const datasetLabels = useMemo(
    () =>
      selectedBaselines.map((id) => baselinesCatalog.find((b) => b.id === id)?.label || id),
    [selectedBaselines, baselinesCatalog],
  );

  const namedMembers = useMemo(
    () => new Set(groups.flatMap((g) => g.members.map((m) => m.name).filter(Boolean))),
    [groups],
  );

  const fallbackName = useMemo(() => {
    const activeGroups = groups.filter((g) => g.coverage_percent > 0);
    const overlap = activeGroups.slice(1).reduce((s, g) => s + g.coverage_percent, 0);
    return ruleBasedAssignmentName({
      datasetLabels,
      caseCount,
      reviewersPerIssue: Math.max(1, activeGroups.length),
      overlapRatio: Math.min(1, overlap / 100),
      memberCount: namedMembers.size,
      workflowMode: "case_labeling",
      runName: "",
      comparison: "all",
    });
  }, [datasetLabels, caseCount, groups, namedMembers.size]);

  const requestAiName = async (force = false) => {
    if (!active || !selectedBaselines.length || !caseCount || !namedMembers.size) {
      if (!manualName) {
        setName(fallbackName);
        setNameSource("rule");
      }
      return;
    }
    if (manualName && !force) return;
    const seq = ++nameSeqRef.current;
    setNameLoading(true);
    if (force) setManualName(false);
    try {
      const activeGroups = groups.filter((g) => g.coverage_percent > 0);
      const overlap = activeGroups.slice(1).reduce((s, g) => s + g.coverage_percent, 0);
      const res = await apiRequest<{ suggestion?: string; source?: string }>(
        "/api/assignment-name-suggestion",
        {
          method: "POST",
          body: {
            assignment_kind: "case_labeling",
            baseline_ids: selectedBaselines,
            case_count: caseCount,
            reviewers_per_issue: Math.max(1, activeGroups.length),
            overlap_ratio: Math.min(1, overlap / 100),
            member_count: namedMembers.size,
            draft_name: fallbackName,
          },
        },
      );
      if (seq !== nameSeqRef.current) return;
      if (res.source === "llm" && res.suggestion?.trim()) {
        setName(res.suggestion.trim());
        setNameSource("llm");
      } else {
        setName(fallbackName);
        setNameSource("rule");
      }
    } catch {
      if (seq === nameSeqRef.current) {
        setName(fallbackName);
        setNameSource("rule");
      }
    } finally {
      if (seq === nameSeqRef.current) setNameLoading(false);
    }
  };

  useEffect(() => {
    if (!active || manualName) return;
    setName(fallbackName);
    setNameSource("rule");
    if (!selectedBaselines.length || !caseCount || !namedMembers.size) return;
    const timer = window.setTimeout(() => void requestAiName(false), 650);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, fallbackName, manualName]);

  const validationError = useMemo(() => {
    if (!isAdmin) return bilingual(lang, "仅管理员可创建标注任务。", "Admin role required to create tasks.");
    if (caseCount <= 0) return bilingual(lang, "当前筛选范围没有 Case。", "No cases match the current scope.");
    return validateAllocationGroups(groups, lang);
  }, [isAdmin, caseCount, groups, lang]);

  const previewBody = useMemo(() => {
    if (validationError) return null;
    return {
      groups: groups.map((g) => ({
        group_id: g.group_id,
        coverage_percent: g.coverage_percent,
        coverage_strategy: g.coverage_strategy || "overlap",
        members: g.members
          .filter((m) => m.name.trim())
          .map((m) => ({ name: m.name, review_percent: m.review_percent })),
      })),
      cross_groups: [],
      pairing_mode: pairingMode,
      filters: inheritedFilters,
      ...(name.trim() ? { name: name.trim() } : {}),
      ...(seed.trim() ? { seed: Number(seed) } : {}),
    };
  }, [validationError, groups, pairingMode, inheritedFilters, name, seed]);

  const serializedPreview = useMemo(
    () => (previewBody ? JSON.stringify(previewBody) : ""),
    [previewBody],
  );

  const previewQuery = useQuery<AllocationPreviewPayload>({
    queryKey: ["labeling-task-preview", serializedPreview],
    queryFn: async ({ signal }) => {
      const nextId =
        typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `lbl-${Date.now()}`;
      requestIdRef.current = nextId;
      const res = await apiRequest<{ preview?: AllocationPreviewPayload } & AllocationPreviewPayload>(
        "/api/labeling/tasks",
        {
          method: "POST",
          body: {
            ...JSON.parse(serializedPreview),
            request_id: nextId,
            preview_only: true,
          },
          signal,
        },
      );
      return res.preview || res;
    },
    enabled: active && Boolean(serializedPreview),
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 10_000,
  });

  const createMutation = useMutation({
    mutationFn: () => {
      if (!previewBody || !previewQuery.data?.preview_token) {
        throw new Error(bilingual(lang, "请先等待预览完成。", "Wait for live preview first."));
      }
      return apiRequest<{ task?: { id?: string }; id?: string }>("/api/labeling/tasks", {
        method: "POST",
        body: {
          ...previewBody,
          request_id: requestIdRef.current,
          preview_token: previewQuery.data.preview_token,
        },
      });
    },
    onSuccess: (res) => {
      const tid = res.task?.id || res.id || "";
      setCreatedTaskId(tid);
      setSubmitError("");
      showWorkbenchToast(bilingual(lang, "标注任务已创建。", "Labeling task created."));
      void queryClient.invalidateQueries({ queryKey: ["labeling-tasks-history"] });
    },
    onError: (err) => {
      setSubmitError(
        err instanceof Error ? err.message : bilingual(lang, "创建失败。", "Creation failed."),
      );
    },
  });

  if (!active) return null;

  const combinedTasks = (combinedTasksQuery.data?.items || []).filter(
    (item) => item.workflow_mode === "model_review_and_case_label",
  );
  const historyTasks = tasksQuery.data?.items || [];

  return (
    <div className="case-experiment-layout ra-labeling-newtask-root">
      <section className="page-card assignment-composer">
        <div className="intent-experiment-section-heading">
          <div>
            <h3>{bilingual(lang, "分配配置", "Assignment setup")}</h3>
            <p className="quiet-meta">
              {bilingual(lang, `当前筛选范围：${caseCount} 个 Case`, `Filtered scope: ${caseCount} Cases`)}
            </p>
          </div>
          <button
            type="button"
            className="button button-quiet"
            onClick={() => navigateWorkbenchPage("labeling")}
          >
            {bilingual(lang, "返回图库", "Back to gallery")}
          </button>
        </div>

        <div className="ra-newtask-name-row">
          <label className="work-split-seed">
            <span>{bilingual(lang, "实验名称", "Experiment name")}</span>
            <div className="intent-experiment-name-control">
              <input
                type="text"
                maxLength={80}
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setManualName(Boolean(e.target.value.trim()));
                  setNameSource("manual");
                }}
                placeholder={bilingual(lang, "自动生成实验名称", "Generated from configuration")}
              />
              <small className="assignment-name-source">
                {nameLoading
                  ? bilingual(lang, "AI 命名中…", "AI naming…")
                  : nameSource === "llm"
                    ? "AI"
                    : nameSource === "manual"
                      ? bilingual(lang, "手动", "Manual")
                      : bilingual(lang, "规则", "Rule")}
              </small>
              <button
                type="button"
                className="button button-quiet"
                disabled={nameLoading || !caseCount || !namedMembers.size}
                onClick={() => void requestAiName(true)}
                title={bilingual(lang, "重新生成实验名称", "Regenerate name")}
              >
                ↻
              </button>
            </div>
          </label>

          <div className="ra-unit-toggle" role="group" aria-label={bilingual(lang, "输入单位", "Input unit")}>
            <button
              type="button"
              className={`button ${unit === "percent" ? "button-primary" : "button-quiet"}`}
              onClick={() => setUnit("percent")}
            >
              %
            </button>
            <button
              type="button"
              className={`button ${unit === "count" ? "button-primary" : "button-quiet"}`}
              onClick={() => setUnit("count")}
            >
              {bilingual(lang, "条数", "Count")}
            </button>
          </div>
        </div>

        <div className="ra-alloc-split-grid">
          <GroupShareEditor
            groups={groups}
            unit={unit}
            caseCount={caseCount}
            quotaBasis="total"
            eligibleMembers={eligibleMembers}
            lang={lang}
            onChange={(next) => setGroups(next)}
          />
          <AllocationPreviewPanel
            preview={previewQuery.data ?? null}
            isUpdating={previewQuery.isFetching}
            errorText={
              validationError ||
              (previewQuery.isError ? String((previewQuery.error as Error)?.message || "Preview error") : null)
            }
            onRetry={() => void previewQuery.refetch()}
            lang={lang}
          />
        </div>

        <div className="work-split-toolbar assignment-footer-row">
          <label className="work-split-seed">
            <span>{bilingual(lang, "随机种子（可选）", "Random seed (optional)")}</span>
            <input
              type="number"
              inputMode="numeric"
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              placeholder={bilingual(lang, "留空则每次不同", "Leave blank to randomize")}
            />
          </label>
          <div className="dialog-actions">
            <button
              type="button"
              className="button button-quiet"
              onClick={() => navigateWorkbenchPage("labeling")}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-primary ra-primary-touch"
              disabled={
                Boolean(validationError) ||
                !previewQuery.data?.preview_token ||
                previewQuery.isFetching ||
                createMutation.isPending
              }
              onClick={() => createMutation.mutate()}
            >
              {createMutation.isPending
                ? bilingual(lang, "创建中…", "Creating…")
                : bilingual(lang, "确认创建标注任务", "Create labeling task")}
            </button>
          </div>
        </div>

        {submitError && (
          <p className="rd-notice is-error" role="alert">
            {submitError}
          </p>
        )}

        {createdTaskId && (
          <div className="ra-created-task-banner" role="status">
            <span>{bilingual(lang, "标注任务创建成功！", "Labeling task created!")}</span>
            <a
              className="button button-primary"
              href={`${withWorkbenchBase("/case-labeling")}?task=${encodeURIComponent(createdTaskId)}${baselinesKey ? `&baselines=${encodeURIComponent(baselinesKey)}` : ""}`}
            >
              {bilingual(lang, "立即打开任务", "Open task")}
            </a>
          </div>
        )}
      </section>

      <section className="page-card assignment-history">
        <div className="intent-experiment-section-heading">
          <h3>
            {bilingual(lang, "联合复核任务", "Combined review tasks")} ({combinedTasks.length})
          </h3>
          <button
            type="button"
            className="button button-quiet"
            onClick={() => void combinedTasksQuery.refetch()}
          >
            {bilingual(lang, "刷新", "Refresh")}
          </button>
        </div>
        <div className="review-assignment-list">
          {combinedTasks.length === 0 ? (
            <div className="review-assignment-empty">
              {bilingual(lang, "暂无当前有效的联合复核任务。", "No active combined review tasks.")}
            </div>
          ) : (
            combinedTasks.map((item) => (
              <article key={item.split_id} className="intent-experiment-item">
                <div>
                  <h4>{item.name || item.split_id}</h4>
                  <div className="intent-experiment-meta">
                    {item.member_count || 0} Cases · {item.created_by || "—"} ·{" "}
                    {formatCstTime(item.created_at, lang)}
                  </div>
                </div>
                <div className="review-assignment-batch-actions">
                  <a
                    className="button button-quiet"
                    href={`${withWorkbenchBase("/review-assignments")}?lifecycle=current&split=${encodeURIComponent(item.split_id)}`}
                  >
                    {bilingual(lang, "查看详情", "Details")}
                  </a>
                </div>
              </article>
            ))
          )}
        </div>
      </section>

      <section className="page-card assignment-history">
        <div className="intent-experiment-section-heading">
          <h3>
            {bilingual(lang, "实验记录", "Experiment records")} ({historyTasks.length})
          </h3>
          <a
            className="button button-quiet"
            href={`${withWorkbenchBase("/campaigns")}?purpose=labeling&lifecycle=history`}
          >
            {bilingual(lang, "历史任务与成果", "Task history & evidence")}
          </a>
        </div>
        <div className="intent-experiment-list">
          {historyTasks.length === 0 ? (
            <div className="intent-experiment-empty">
              <strong>{bilingual(lang, "尚未创建实验", "No experiments yet")}</strong>
            </div>
          ) : (
            historyTasks.map((task) => {
              const total = Number(task.progress?.total || task.member_count || 0);
              const resolved = Number(task.progress?.resolved || 0);
              const conflict = Number(task.progress?.conflict || 0);
              const pct = total ? Math.min(100, Math.round((resolved * 100) / total)) : 0;
              return (
                <article key={task.id} className="intent-experiment-item case-experiment-item">
                  <div>
                    <h4>{task.name || bilingual(lang, "未命名实验", "Unnamed experiment")}</h4>
                    <div className="intent-experiment-meta">
                      {Number(task.reviewers_per_issue || 1) > 1
                        ? bilingual(
                            lang,
                            `${task.reviewers_per_issue} 人 · ${Math.round(Number(task.overlap_ratio || 0) * 100)}% 交叉盲标`,
                            `${task.reviewers_per_issue} people · ${Math.round(Number(task.overlap_ratio || 0) * 100)}% cross-label`,
                          )
                        : bilingual(lang, "单人标注", "Single labeler")}{" "}
                      · {total} Cases · {task.created_by || "—"}
                    </div>
                  </div>
                  <div className="review-assignment-batch-actions">
                    {isAdmin && (
                      <button
                        type="button"
                        className="button button-quiet"
                        onClick={() => {
                          const win = window as unknown as {
                            __RA_REACT_WORKBENCH__?: { openTaskAllocationEditor?: (id: string) => boolean };
                          };
                          win.__RA_REACT_WORKBENCH__?.openTaskAllocationEditor?.(task.id);
                        }}
                      >
                        {bilingual(lang, "修改分配", "Edit allocation")}
                      </button>
                    )}
                    <a
                      className="button button-quiet"
                      href={`${withWorkbenchBase("/case-labeling")}?task=${encodeURIComponent(task.id)}${baselinesKey ? `&baselines=${encodeURIComponent(baselinesKey)}` : ""}`}
                    >
                      {bilingual(lang, "打开实验", "Open experiment")}
                    </a>
                  </div>
                  <div className="intent-experiment-detail-row">
                    <div className="intent-experiment-member-stats">
                      <span>{bilingual(lang, `已完成 ${resolved}`, `Done ${resolved}`)}</span>
                      <span>
                        {bilingual(lang, `待处理 ${Math.max(0, total - resolved)}`, `Pending ${Math.max(0, total - resolved)}`)}
                      </span>
                      {conflict > 0 && <span>{bilingual(lang, `冲突 ${conflict}`, `Conflicts ${conflict}`)}</span>}
                    </div>
                    <div className="intent-experiment-progress">
                      <span className="intent-experiment-progress-track">
                        <i className="is-complete" style={{ width: `${pct}%` }} />
                      </span>
                      <small>{pct}%</small>
                    </div>
                  </div>
                </article>
              );
            })
          )}
        </div>
      </section>
    </div>
  );
};
