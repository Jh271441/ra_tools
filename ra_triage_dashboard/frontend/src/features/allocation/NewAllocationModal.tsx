import React, { useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { apiRequest } from "../../api/client";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { ModalDialog } from "../../components/ui/ModalDialog";
import { UiSelect } from "../../components/ui/UiSelect";
import { AllocationPreviewPanel, AllocationPreviewPayload } from "./AllocationPreviewPanel";
import { GroupShareEditor } from "./GroupShareEditor";
import {
  AllocationGroup,
  createNewAllocationGroup,
  InputUnit,
  PairingMode,
  ruleBasedAssignmentName,
  validateAllocationGroups,
} from "./rebalance";

interface ModelRunSummary {
  id: string;
  name: string;
  baseline_prediction_count?: number;
}

interface BaselineCatalogItem {
  id: string;
  label: string;
  default_selected?: boolean;
}

export interface NewAllocationModalProps {
  open: boolean;
  lang: UiLanguage;
  eligibleMembers: string[];
  onClose: () => void;
  onCreated: () => void;
}

export const NewAllocationModal: React.FC<NewAllocationModalProps> = ({
  open,
  lang,
  eligibleMembers,
  onClose,
  onCreated,
}) => {
  const [workflowMode, setWorkflowMode] = useState("model_review_and_case_label");
  const [comparison, setComparison] = useState("all");
  const [selectedBaselines, setSelectedBaselines] = useState<string[]>([]);
  const [modelRunId, setModelRunId] = useState("");
  const [seed, setSeed] = useState("");
  const [unit, setUnit] = useState<InputUnit>("percent");
  const [pairingMode] = useState<PairingMode>("orthogonal");
  const [groups, setGroups] = useState<AllocationGroup[]>(() => [createNewAllocationGroup([])]);

  // Resilient AI naming state (rule fallback + debounced LLM refinement + manual lock)
  const [name, setName] = useState("");
  const [manualName, setManualName] = useState(false);
  const [nameSource, setNameSource] = useState<"rule" | "llm" | "manual">("rule");
  const [nameLoading, setNameLoading] = useState(false);
  const [nameError, setNameError] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const nameSeqRef = useRef(0);

  const configQuery = useQuery<{ baselines?: BaselineCatalogItem[] }>({
    queryKey: ["dashboard-config"],
    queryFn: ({ signal }) =>
      apiRequest<{ baselines?: BaselineCatalogItem[] }>("/api/dashboard-config", { signal }),
    enabled: open,
    staleTime: 60_000,
  });

  const baselines = configQuery.data?.baselines || [];
  useEffect(() => {
    if (!open || selectedBaselines.length || !baselines.length) return;
    const defaults = baselines.filter((b) => b.default_selected).map((b) => b.id);
    setSelectedBaselines(defaults.length ? defaults : [baselines[0].id]);
  }, [open, baselines, selectedBaselines.length]);

  const baselinesParam = selectedBaselines.join(",");
  const runsQuery = useQuery<{ items?: ModelRunSummary[] }>({
    queryKey: ["model-runs-for-alloc", baselinesParam],
    queryFn: ({ signal }) =>
      apiRequest<{ items?: ModelRunSummary[] }>(
        `/api/model-runs${baselinesParam ? `?baselines=${encodeURIComponent(baselinesParam)}` : ""}`,
        { signal },
      ),
    enabled: open && Boolean(baselinesParam),
    staleTime: 30_000,
  });

  const runs = runsQuery.data?.items || [];
  useEffect(() => {
    if (!runs.length) return;
    if (!modelRunId || !runs.some((r) => r.id === modelRunId)) {
      const preferred = runs.find((r) => (r.baseline_prediction_count || 0) > 0) || runs[0];
      setModelRunId(preferred.id);
    }
  }, [runs, modelRunId]);

  const scopeCountQuery = useQuery<{ total: number }>({
    queryKey: ["alloc-scope-count", baselinesParam, modelRunId, comparison],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({
        baselines: baselinesParam,
        model_run_id: modelRunId,
        comparison,
        comparison_status: comparison,
        page: "1",
        page_size: "1",
        include_thumbnail: "false",
      });
      return apiRequest<{ total: number }>(`/api/cases?${qs.toString()}`, { signal });
    },
    enabled: open && Boolean(baselinesParam) && Boolean(modelRunId),
    staleTime: 10_000,
  });

  const caseCount = Number(scopeCountQuery.data?.total || 0);
  const activeRun = runs.find((r) => r.id === modelRunId);
  const namedMembers = useMemo(
    () => new Set(groups.flatMap((g) => g.members.map((m) => m.name).filter(Boolean))),
    [groups],
  );
  const datasetLabels = useMemo(
    () =>
      selectedBaselines.map((id) => baselines.find((b) => b.id === id)?.label || id),
    [selectedBaselines, baselines],
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
      workflowMode,
      runName: activeRun?.name || modelRunId,
      comparison,
    });
  }, [datasetLabels, caseCount, groups, namedMembers.size, workflowMode, activeRun, modelRunId, comparison]);

  const requestAiSuggestion = async (force = false) => {
    if (!open || !selectedBaselines.length || !caseCount || !namedMembers.size || !modelRunId) {
      if (!manualName) {
        setName(fallbackName);
        setNameSource("rule");
      }
      return;
    }
    if (manualName && !force) return;
    const seq = ++nameSeqRef.current;
    setNameLoading(true);
    setNameError("");
    if (force) setManualName(false);
    try {
      const activeGroups = groups.filter((g) => g.coverage_percent > 0);
      const overlap = activeGroups.slice(1).reduce((s, g) => s + g.coverage_percent, 0);
      const res = await apiRequest<{ suggestion?: string; source?: string; reason?: string }>(
        "/api/assignment-name-suggestion",
        {
          method: "POST",
          body: {
            assignment_kind: "model_review",
            baseline_ids: selectedBaselines,
            case_count: caseCount,
            reviewers_per_issue: Math.max(1, activeGroups.length),
            overlap_ratio: Math.min(1, overlap / 100),
            member_count: namedMembers.size,
            workflow_mode: workflowMode,
            model_run_id: modelRunId,
            comparison,
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
        setNameError(res.reason || "");
      }
    } catch {
      if (seq === nameSeqRef.current) {
        setName(fallbackName);
        setNameSource("rule");
        setNameError("request_failed");
      }
    } finally {
      if (seq === nameSeqRef.current) setNameLoading(false);
    }
  };

  useEffect(() => {
    if (!open || manualName) return;
    setName(fallbackName);
    setNameSource("rule");
    if (!selectedBaselines.length || !caseCount || !namedMembers.size || !modelRunId) return;
    const timer = window.setTimeout(() => {
      void requestAiSuggestion(false);
    }, 650);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, fallbackName, manualName]);

  const validationError = useMemo(() => {
    if (!selectedBaselines.length) return bilingual(lang, "请选择至少一个数据集。", "Select at least one dataset.");
    if (!modelRunId) return bilingual(lang, "请选择 Model Run。", "Select a Model Run.");
    if (caseCount <= 0) return bilingual(lang, "当前筛选范围没有 Case。", "No cases match this scope.");
    return validateAllocationGroups(groups, lang);
  }, [selectedBaselines.length, modelRunId, caseCount, groups, lang]);

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
      workflow_mode: workflowMode,
      filters: {
        model_run_id: modelRunId,
        baselines: baselinesParam,
        comparison,
        comparison_status: comparison,
        comment_state: "all",
        exclusion: "all",
      },
      ...(name.trim() ? { name: name.trim() } : {}),
      ...(seed.trim() ? { seed: Number(seed) } : {}),
    };
  }, [validationError, groups, pairingMode, workflowMode, modelRunId, baselinesParam, comparison, name, seed]);

  const serializedPreview = useMemo(
    () => (previewBody ? JSON.stringify(previewBody) : ""),
    [previewBody],
  );

  const previewQuery = useQuery<AllocationPreviewPayload>({
    queryKey: ["new-work-split-preview", serializedPreview],
    queryFn: ({ signal }) =>
      apiRequest<AllocationPreviewPayload>("/api/cases/work-split/preview", {
        method: "POST",
        body: JSON.parse(serializedPreview),
        signal,
      }),
    enabled: open && Boolean(serializedPreview),
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 10_000,
  });

  const createMutation = useMutation({
    mutationFn: () => {
      if (!previewBody || !previewQuery.data?.preview_token) {
        throw new Error(bilingual(lang, "请先等待预览完成。", "Wait for preview before creating."));
      }
      const reqId =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `split-${Date.now()}`;
      return apiRequest("/api/cases/work-split", {
        method: "POST",
        body: {
          ...previewBody,
          request_id: reqId,
          preview_token: previewQuery.data.preview_token,
        },
      });
    },
    onSuccess: () => {
      setSubmitError(null);
      onCreated();
      onClose();
    },
    onError: (err) => {
      setSubmitError(
        err instanceof Error ? err.message : bilingual(lang, "创建失败，请重试。", "Create failed."),
      );
    },
  });

  const workflowOptions = [
    {
      value: "model_review_and_case_label",
      label: bilingual(lang, "联合复核任务（判错复核 + 问题标注）", "Combined review (Review + Case label)"),
    },
    {
      value: "model_review_only",
      label: bilingual(lang, "独立判错复核任务（仅判错复核）", "Model review only"),
    },
  ];

  const comparisonOptions = [
    { value: "all", label: bilingual(lang, "全部 Case", "All cases") },
    { value: "mismatch", label: bilingual(lang, "仅模型判错 (MISMATCH)", "Model mismatches only") },
    { value: "match", label: bilingual(lang, "仅模型判对 (MATCH)", "Model matches only") },
  ];

  const runOptions = runs.map((r) => ({ value: r.id, label: r.name || r.id }));

  return (
    <ModalDialog
      open={open}
      wide
      lang={lang}
      title={bilingual(lang, "新建复核任务分配", "New review allocation")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="button button-quiet" onClick={onClose}>
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
              ? bilingual(lang, "正在创建…", "Creating…")
              : bilingual(lang, "创建分配", "Create allocation")}
          </button>
        </>
      }
    >
      <div className="ra-new-alloc-root" data-react-island="new-allocation">
        <div className="ra-new-alloc-fields">
          <div className="ra-field-stack">
            <span>{bilingual(lang, "任务类型", "Task type")}</span>
            <UiSelect
              value={workflowMode}
              options={workflowOptions}
              ariaLabel={bilingual(lang, "任务类型", "Task type")}
              onChange={setWorkflowMode}
            />
          </div>

          <div className="ra-field-stack">
            <span>{bilingual(lang, "模型 Run", "Model run")}</span>
            <UiSelect
              value={modelRunId}
              options={runOptions.length ? runOptions : [{ value: "", label: bilingual(lang, "暂无 Run", "No runs") }]}
              disabled={!runOptions.length}
              ariaLabel={bilingual(lang, "模型 Run", "Model run")}
              onChange={setModelRunId}
            />
          </div>

          <div className="ra-field-stack">
            <span>
              {bilingual(lang, "筛选范围", "Case scope")} ·{" "}
              <strong>
                {scopeCountQuery.isFetching
                  ? bilingual(lang, "统计中…", "Counting…")
                  : `${caseCount.toLocaleString()} Case`}
              </strong>
            </span>
            <UiSelect
              value={comparison}
              options={comparisonOptions}
              ariaLabel={bilingual(lang, "筛选范围", "Case scope")}
              onChange={setComparison}
            />
          </div>

          <div className="ra-field-stack ra-name-field">
            <span>
              {bilingual(lang, "实验名称", "Experiment name")}{" "}
              <small className="muted">
                {nameLoading
                  ? bilingual(lang, "AI 优化中…", "AI refining…")
                  : nameSource === "llm"
                    ? bilingual(lang, "AI 模型命名", "AI suggested")
                    : nameSource === "manual"
                      ? bilingual(lang, "手动编辑", "Manual")
                      : nameError
                        ? bilingual(lang, "规则兜底", "Rule fallback")
                        : bilingual(lang, "规则命名", "Rule result")}
              </small>
            </span>
            <div className="ra-name-input-row">
              <input
                type="text"
                maxLength={80}
                value={name}
                placeholder={bilingual(lang, "自动生成实验名称", "Auto-generated name")}
                onChange={(e) => {
                  const val = e.target.value;
                  setName(val);
                  setManualName(Boolean(val.trim()));
                  setNameSource(val.trim() ? "manual" : "rule");
                }}
              />
              <button
                type="button"
                className="button button-quiet"
                disabled={nameLoading || !namedMembers.size || !modelRunId || !caseCount}
                title={bilingual(lang, "重新生成 AI 名称", "Regenerate AI name")}
                aria-label={bilingual(lang, "重新生成实验名称", "Regenerate experiment name")}
                onClick={() => void requestAiSuggestion(true)}
              >
                ↻
              </button>
            </div>
          </div>
        </div>

        <div className="ra-dataset-chips" role="group" aria-label={bilingual(lang, "数据集范围", "Datasets")}>
          {baselines.slice(0, 12).map((b) => {
            const checked = selectedBaselines.includes(b.id);
            return (
              <button
                key={b.id}
                type="button"
                className={`button ${checked ? "button-primary" : "button-quiet"} ra-chip-btn`}
                aria-pressed={checked}
                onClick={() =>
                  setSelectedBaselines((prev) =>
                    prev.includes(b.id)
                      ? prev.length > 1
                        ? prev.filter((id) => id !== b.id)
                        : prev
                      : [...prev, b.id],
                  )
                }
              >
                {b.label}
              </button>
            );
          })}
        </div>

        <div className="ra-alloc-controls-bar">
          <div className="ra-unit-toggle" role="group" aria-label={bilingual(lang, "数值单位", "Input unit")}>
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
              disabled={caseCount <= 0}
              onClick={() => setUnit("count")}
            >
              {bilingual(lang, "条", "Count")}
            </button>
          </div>
          <label className="ra-seed-field">
            <span className="muted">{bilingual(lang, "随机种子（可选）", "Random seed")}</span>
            <input
              type="number"
              inputMode="numeric"
              value={seed}
              placeholder={bilingual(lang, "留空随机", "Optional")}
              onChange={(e) => setSeed(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="button button-quiet"
            onClick={() => setGroups((prev) => [...prev, createNewAllocationGroup(prev)])}
          >
            + {bilingual(lang, "添加分配组", "Add group")}
          </button>
        </div>

        <div className="ra-alloc-split-grid">
          <GroupShareEditor
            groups={groups}
            eligibleMembers={eligibleMembers}
            lang={lang}
            unit={unit}
            caseCount={caseCount}
            quotaBasis="total"
            editable
            onChange={(next) => setGroups(next)}
          />
          <AllocationPreviewPanel
            preview={previewQuery.data || null}
            lang={lang}
            isUpdating={previewQuery.isFetching}
            errorText={
              validationError ||
              (previewQuery.isError && previewQuery.error instanceof Error
                ? previewQuery.error.message
                : null)
            }
            onRetry={() => void previewQuery.refetch()}
          />
        </div>

        {submitError && (
          <p className="ra-inline-feedback is-error" role="alert">
            {submitError}
          </p>
        )}
      </div>
    </ModalDialog>
  );
};
