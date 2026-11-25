import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

interface IntentDatasetItem {
  id: string;
  display_name: string;
  available: boolean;
  case_count?: number;
}

interface EligibleMember {
  username: string;
  role: string;
}

interface ExperimentMemberStat {
  username: string;
  total: number;
  base: number;
  cross: number;
}

interface IntentExperimentItem {
  id: string;
  dataset_id: string;
  name: string;
  label_scope: string;
  annotation_mode: string;
  annotation_status_filter?: string;
  overlap_ratio: number;
  overlap_reviewers?: number;
  case_count: number;
  assignment_count: number;
  member_count?: number;
  created_by: string;
  status: string;
  update_count?: number;
  members?: ExperimentMemberStat[];
  progress?: {
    total?: number;
    completed?: number;
    partial?: number;
    pending?: number;
  };
}

interface IntentExperimentsResponse {
  items?: IntentExperimentItem[];
  eligible_members?: EligibleMember[];
  annotation_status_counts?: Record<string, Record<string, number>>;
  name_suggestion?: {
    llm_available?: boolean;
  };
}

interface LegacyWindow {
  state?: {
    intentLabeling?: {
      datasets?: IntentDatasetItem[];
      experimentDatasetIds?: string[];
      experimentDatasetId?: string;
      assigneeDatasetId?: string;
      assigneeSelectionDatasetId?: string;
      selectedAssignees?: string[];
    };
  };
  renderIntentTopbarDatasetPicker?: (selectedIds?: string[] | null) => void;
  navigatePage?: (page: string, opts?: Record<string, unknown>) => void;
  loadIntentLabeling?: (opts?: Record<string, unknown>) => Promise<void>;
  showToast?: (msg: string, isError?: boolean) => void;
  acknowledgeLocalChange?: (payload: unknown) => void;
}

function getLegacyWindow(): LegacyWindow {
  return window as unknown as LegacyWindow;
}

function modeLabel(mode: string, lang: UiLanguage): string {
  return mode === "full"
    ? bilingual(lang, "全量盲标", "Full blind labeling")
    : bilingual(lang, "交叉盲标", "Cross blind labeling");
}

function scopeLabel(scope: string, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    routing: ["仅 Routing 意图", "Routing only"],
    lane_change: ["仅变道意图", "Lane-change only"],
    all: ["Routing + 变道意图", "Routing + lane-change"],
  };
  const pair = map[scope] || map.all;
  return bilingual(lang, pair[0], pair[1]);
}

function annotationStatusLabel(status: string, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    labeled: ["已有人标注", "Already labeled"],
    unlabeled: ["尚无人标注", "Not yet labeled"],
    all: ["全部 Case", "All Cases"],
  };
  const pair = map[status] || map.all;
  return bilingual(lang, pair[0], pair[1]);
}

function ruleBasedName(ctx: {
  datasets: IntentDatasetItem[];
  mode: string;
  labelScope: string;
  requested: number;
  overlap: number;
  reviewers: number;
  memberCount: number;
}): string {
  const scope =
    ctx.datasets
      .map((item) => String(item.display_name || item.id || "").split("·", 1)[0].trim())
      .filter(Boolean)
      .join("+") || "Routing";
  let mode = "全量盲标";
  if (ctx.mode !== "full") {
    const hasCrossReview = ctx.memberCount > 1 && ctx.reviewers > 1 && ctx.overlap > 0;
    mode = hasCrossReview
      ? `交叉${Math.round(ctx.overlap * 100)}%复核`
      : ctx.memberCount === 1
        ? "单人盲标"
        : "分工盲标";
  }
  const intentName =
    ({ routing: "Routing", lane_change: "变道意图", all: "Routing+变道意图" } as Record<
      string,
      string
    >)[ctx.labelScope] || "Routing+变道意图";
  return `${scope} ${intentName} ${mode} ${ctx.requested} Case`.slice(0, 80);
}

export interface IntentExperimentsPageProps {
  active: boolean;
  lang: UiLanguage;
  canManageIntent: boolean;
}

export const IntentExperimentsPage: React.FC<IntentExperimentsPageProps> = ({
  active,
  lang,
  canManageIntent,
}) => {
  const queryClient = useQueryClient();

  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>(() =>
    new URLSearchParams(window.location.search).getAll("dataset").filter(Boolean),
  );
  const [name, setName] = useState<string>("");
  const [manualNameEdited, setManualNameEdited] = useState<boolean>(false);
  const [aiNaming, setAiNaming] = useState<boolean>(false);
  const [labelScope, setLabelScope] = useState<string>("all");
  const [mode, setMode] = useState<string>("blind");
  const [annotationStatus, setAnnotationStatus] = useState<string>("all");
  const [caseCount, setCaseCount] = useState<string>("");
  const [overlap, setOverlap] = useState<string>("0.2");
  const [reviewers, setReviewers] = useState<string>("2");
  const [selectedMembers, setSelectedMembers] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState<boolean>(false);

  // Edit & Close dialogs
  const [editingExp, setEditingExp] = useState<IntentExperimentItem | null>(null);
  const [editName, setEditName] = useState<string>("");
  const [editScope, setEditScope] = useState<string>("all");
  const [editSaving, setEditSaving] = useState<boolean>(false);
  const [closingExp, setClosingExp] = useState<IntentExperimentItem | null>(null);
  const [closingBusy, setClosingBusy] = useState<boolean>(false);

  const editDialogRef = useRef<HTMLDialogElement | null>(null);
  const nameSuggestionTimerRef = useRef<number | null>(null);
  const nameSuggestionSeqRef = useRef<number>(0);
  const lastFingerprintRef = useRef<string>("");

  const datasetsQuery = useQuery<{ items?: IntentDatasetItem[] }>({
    queryKey: ["intent-datasets"],
    queryFn: ({ signal }) => apiRequest("/api/intent-datasets", { signal }),
    enabled: active,
    staleTime: 60_000,
  });

  const availableDatasets = useMemo(
    () => (datasetsQuery.data?.items || []).filter((d) => d.available),
    [datasetsQuery.data],
  );

  const effectiveDatasetIds = useMemo(() => {
    const valid = selectedDatasetIds.filter((id) =>
      availableDatasets.some((d) => d.id === id),
    );
    if (valid.length) return valid;
    const legacyIds = getLegacyWindow().state?.intentLabeling?.experimentDatasetIds || [];
    const validLegacy = legacyIds.filter((id) =>
      availableDatasets.some((d) => d.id === id),
    );
    if (validLegacy.length) return validLegacy;
    return availableDatasets[0] ? [availableDatasets[0].id] : [];
  }, [selectedDatasetIds, availableDatasets]);

  const effectiveDatasets = useMemo(
    () => availableDatasets.filter((d) => effectiveDatasetIds.includes(d.id)),
    [availableDatasets, effectiveDatasetIds],
  );

  // Sync classic topbar dataset picker & URL
  useEffect(() => {
    if (!active || !availableDatasets.length) return;
    const legacy = getLegacyWindow();
    if (legacy.state?.intentLabeling) {
      legacy.state.intentLabeling.datasets = datasetsQuery.data?.items || [];
      legacy.state.intentLabeling.experimentDatasetIds = effectiveDatasetIds;
      legacy.state.intentLabeling.experimentDatasetId = effectiveDatasetIds[0] || "";
    }
    legacy.renderIntentTopbarDatasetPicker?.(effectiveDatasetIds);

    const params = new URLSearchParams();
    effectiveDatasetIds.forEach((id) => params.append("dataset", id));
    const target = `${withWorkbenchBase("/intent-experiments")}${
      params.toString() ? `?${params.toString()}` : ""
    }`;
    if (`${window.location.pathname}${window.location.search}` !== target) {
      window.history.replaceState(
        {
          page: "intent-experiments",
          datasetId: effectiveDatasetIds[0] || "",
          datasetIds: effectiveDatasetIds,
        },
        "",
        target,
      );
    }
  }, [active, availableDatasets, datasetsQuery.data, effectiveDatasetIds]);

  // Listen to topbar picker changes
  useEffect(() => {
    if (!active) return;
    const handleSync = () => {
      const legacyIds = getLegacyWindow().state?.intentLabeling?.experimentDatasetIds;
      if (Array.isArray(legacyIds) && legacyIds.length) {
        setSelectedDatasetIds((prev) =>
          prev.join(",") === legacyIds.join(",") ? prev : [...legacyIds],
        );
      }
    };
    window.addEventListener("ra:workbench-sync", handleSync);
    return () => window.removeEventListener("ra:workbench-sync", handleSync);
  }, [active]);

  const experimentsQuery = useQuery<IntentExperimentsResponse>({
    queryKey: ["intent-experiments", effectiveDatasetIds.slice().sort().join(",")],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams();
      effectiveDatasetIds.forEach((id) => params.append("dataset_id", id));
      return apiRequest<IntentExperimentsResponse>(
        `/api/intent-experiments${params.toString() ? `?${params.toString()}` : ""}`,
        { signal },
      );
    },
    enabled: active && effectiveDatasetIds.length > 0,
    staleTime: 10_000,
  });

  const experiments = experimentsQuery.data?.items || [];
  const eligibleMembers = experimentsQuery.data?.eligible_members || [];
  const annotationStatusCounts = experimentsQuery.data?.annotation_status_counts || {};
  const llmNamingAvailable = Boolean(experimentsQuery.data?.name_suggestion?.llm_available);

  // Max case count limit
  const maxCaseCount = useMemo(() => {
    const counts = effectiveDatasets.map((item) =>
      Math.max(0, Number(annotationStatusCounts?.[item.id]?.[annotationStatus] ?? item.case_count) || 0),
    );
    return Math.max(1, ...counts);
  }, [effectiveDatasets, annotationStatusCounts, annotationStatus]);

  useEffect(() => {
    const current = Number(caseCount) || 0;
    if (current < 1 || current > maxCaseCount) {
      setCaseCount(String(maxCaseCount));
    }
  }, [maxCaseCount]);

  // Clamp reviewers to member count when members selected
  useEffect(() => {
    if (selectedMembers.length > 0 && Number(reviewers) > selectedMembers.length) {
      setReviewers(String(selectedMembers.length));
    }
  }, [selectedMembers.length, reviewers]);

  // Auto-suggest experiment name (rule-based + optional LLM refinement)
  useEffect(() => {
    if (!active || !effectiveDatasets.length) return;
    const requested = Math.max(1, Number(caseCount) || maxCaseCount || 1);
    const overlapNum = Math.max(0, Number(overlap) || 0);
    const reviewersNum = Math.max(1, Number(reviewers) || 1);
    const fallback = ruleBasedName({
      datasets: effectiveDatasets,
      mode,
      labelScope,
      requested,
      overlap: overlapNum,
      reviewers: reviewersNum,
      memberCount: selectedMembers.length,
    });
    if (!manualNameEdited) {
      setName(fallback);
    }
    if (nameSuggestionTimerRef.current) window.clearTimeout(nameSuggestionTimerRef.current);
    if (!llmNamingAvailable || !canManageIntent) {
      setAiNaming(false);
      return;
    }
    const fingerprint = JSON.stringify({
      dataset_ids: effectiveDatasets.map((d) => d.id),
      annotation_mode: mode,
      label_scope: labelScope,
      annotation_status_filter: annotationStatus,
      case_count: requested,
      overlap_ratio: overlapNum,
      overlap_reviewers: reviewersNum,
      member_count: selectedMembers.length,
      draft_name: manualNameEdited ? name.trim() : "",
    });
    if (fingerprint === lastFingerprintRef.current) return;
    const seq = ++nameSuggestionSeqRef.current;
    setAiNaming(true);
    nameSuggestionTimerRef.current = window.setTimeout(async () => {
      lastFingerprintRef.current = fingerprint;
      try {
        const res = await apiRequest<{ source?: string; suggestion?: string }>(
          "/api/intent-experiments/name-suggestion",
          {
            method: "POST",
            body: fingerprint,
          },
        );
        if (seq !== nameSuggestionSeqRef.current) return;
        const suggestion = String(res?.suggestion || "").trim();
        if (res?.source === "llm" && suggestion && !manualNameEdited) {
          setName(suggestion);
        }
      } catch {
        // Keep rule-based fallback silently
      } finally {
        if (seq === nameSuggestionSeqRef.current) setAiNaming(false);
      }
    }, 650);

    return () => {
      if (nameSuggestionTimerRef.current) window.clearTimeout(nameSuggestionTimerRef.current);
    };
  }, [
    active,
    effectiveDatasets,
    mode,
    labelScope,
    annotationStatus,
    caseCount,
    maxCaseCount,
    overlap,
    reviewers,
    selectedMembers.length,
    llmNamingAvailable,
    canManageIntent,
    manualNameEdited,
  ]);

  // Native edit dialog open/close
  useEffect(() => {
    const dlg = editDialogRef.current;
    if (!dlg) return;
    if (editingExp) {
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
  }, [editingExp]);

  // Estimate message
  const estimateText = useMemo(() => {
    if (!effectiveDatasets.length) {
      return availableDatasets.length > 0
        ? bilingual(lang, "请在顶栏至少选择 1 个数据集。", "Select at least one dataset in the top bar.")
        : bilingual(
            lang,
            "暂无可用于意图实验分配的数据集。",
            "No dataset is available for intent experiment assignment.",
          );
    }
    const emptyDs = effectiveDatasets.find((item) => {
      const counts = annotationStatusCounts?.[item.id] || {};
      return Number(counts[annotationStatus] ?? item.case_count) <= 0;
    });
    if (emptyDs) {
      const st = annotationStatusLabel(annotationStatus, lang);
      return bilingual(
        lang,
        `${emptyDs.display_name} 没有符合“${st}”的 Case。`,
        `${emptyDs.display_name} has no Cases matching “${st}”.`,
      );
    }
    if (selectedMembers.length < 1) {
      return bilingual(lang, "至少选择 1 名成员。", "Select at least one labeler.");
    }
    const requested = Math.max(0, Number(caseCount) || 0);
    const overlapNum = Math.max(0, Number(overlap) || 0);
    const reviewersNum = Math.max(
      1,
      Math.min(selectedMembers.length, Number(reviewers) || 1),
    );
    let totalCases = 0;
    let totalAssignments = 0;
    effectiveDatasets.forEach((item) => {
      const counts = annotationStatusCounts?.[item.id] || {};
      const avail = Math.max(0, Number(counts[annotationStatus] ?? item.case_count) || 0);
      const c = Math.min(requested || avail, avail);
      totalCases += c;
      const overlapCases = Math.round(c * overlapNum);
      totalAssignments +=
        mode === "full"
          ? c * selectedMembers.length
          : c + overlapCases * (reviewersNum - 1);
    });
    const datasetText =
      effectiveDatasets.length > 1
        ? bilingual(lang, `${effectiveDatasets.length} 个数据集`, `${effectiveDatasets.length} datasets`)
        : effectiveDatasets[0].display_name;
    const annotationText = annotationStatusLabel(annotationStatus, lang);
    const scopeText = scopeLabel(labelScope, lang);
    return mode === "full"
      ? bilingual(
          lang,
          `${datasetText} · ${annotationText} · ${scopeText} · ${totalCases} 个 Case · ${selectedMembers.length} 人全量复核 · 共 ${totalAssignments} 份独立任务`,
          `${datasetText} · ${annotationText} · ${scopeText} · ${totalCases} Cases · ${selectedMembers.length} labelers on full scope · ${totalAssignments} assignments`,
        )
      : bilingual(
          lang,
          `${datasetText} · ${annotationText} · ${scopeText} · ${totalCases} 个 Case · 交叉 ${Math.round(
            overlapNum * 100,
          )}% · 共 ${totalAssignments} 份独立任务`,
          `${datasetText} · ${annotationText} · ${scopeText} · ${totalCases} Cases · ${Math.round(
            overlapNum * 100,
          )}% overlap · ${totalAssignments} assignments`,
        );
  }, [
    effectiveDatasets,
    availableDatasets.length,
    annotationStatusCounts,
    annotationStatus,
    selectedMembers.length,
    caseCount,
    overlap,
    reviewers,
    mode,
    labelScope,
    lang,
  ]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!effectiveDatasetIds.length) {
      getLegacyWindow().showToast?.(
        bilingual(lang, "请在顶栏至少选择 1 个数据集。", "Select at least one dataset in the top bar."),
        true,
      );
      return;
    }
    setSubmitting(true);
    try {
      const result = await apiRequest<{
        experiments?: unknown[];
        experiment?: unknown;
      }>("/api/intent-experiments", {
        method: "POST",
        body: JSON.stringify({
          dataset_id: effectiveDatasetIds[0],
          dataset_ids: effectiveDatasetIds,
          name: name.trim(),
          annotation_mode: mode,
          label_scope: labelScope,
          annotation_status_filter: annotationStatus,
          case_count: Number(caseCount) || 0,
          overlap_ratio: Number(overlap) || 0,
          overlap_reviewers: Number(reviewers) || 1,
          members: selectedMembers,
        }),
      });
      getLegacyWindow().acknowledgeLocalChange?.(result);
      setName("");
      setManualNameEdited(false);
      setSelectedMembers([]);
      void queryClient.invalidateQueries({ queryKey: ["intent-experiments"] });
      const created = result.experiments || (result.experiment ? [result.experiment] : []);
      getLegacyWindow().showToast?.(
        created.length > 1
          ? bilingual(
              lang,
              `已在 ${created.length} 个数据集创建实验，任务分配快照已保存。`,
              `Experiments were created in ${created.length} datasets; assignment snapshots were saved.`,
            )
          : bilingual(
              lang,
              "实验已创建，任务分配快照已保存。",
              "The experiment and its assignment snapshot were created.",
            ),
        false,
      );
    } catch (err) {
      getLegacyWindow().showToast?.((err as Error)?.message || "Create failed", true);
    } finally {
      setSubmitting(false);
    }
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingExp || editSaving) return;
    setEditSaving(true);
    try {
      const result = await apiRequest(
        `/api/intent-experiments/${encodeURIComponent(editingExp.id)}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            name: editName.trim(),
            label_scope: editScope,
          }),
        },
      );
      getLegacyWindow().acknowledgeLocalChange?.(result);
      setEditingExp(null);
      void queryClient.invalidateQueries({ queryKey: ["intent-experiments"] });
      getLegacyWindow().showToast?.(
        bilingual(
          lang,
          "实验信息已更新，原任务分配保持不变。",
          "Experiment details were updated; the original assignments are unchanged.",
        ),
        false,
      );
    } catch (err) {
      getLegacyWindow().showToast?.((err as Error)?.message || "Update failed", true);
    } finally {
      setEditSaving(false);
    }
  };

  const handleConfirmClose = async () => {
    if (!closingExp || closingBusy) return;
    setClosingBusy(true);
    try {
      const result = await apiRequest(
        `/api/intent-experiments/${encodeURIComponent(closingExp.id)}/close`,
        { method: "POST" },
      );
      getLegacyWindow().acknowledgeLocalChange?.(result);
      setClosingExp(null);
      void queryClient.invalidateQueries({ queryKey: ["intent-experiments"] });
      getLegacyWindow().showToast?.(
        bilingual(
          lang,
          "实验已关闭，历史分配仍然保留。",
          "The experiment is closed; its assignment history is preserved.",
        ),
        false,
      );
    } catch (err) {
      getLegacyWindow().showToast?.((err as Error)?.message || "Close failed", true);
    } finally {
      setClosingBusy(false);
    }
  };

  const handleResumeExperiment = useCallback((exp: IntentExperimentItem) => {
    const legacy = getLegacyWindow();
    if (legacy.state?.intentLabeling) {
      legacy.state.intentLabeling.assigneeDatasetId = "";
      legacy.state.intentLabeling.assigneeSelectionDatasetId = "";
      legacy.state.intentLabeling.selectedAssignees = [];
    }
    legacy.navigatePage?.("intent", {
      loadPageData: false,
      intentDatasetId: exp.dataset_id,
      intentDatasetIds: [exp.dataset_id],
      intentExperimentId: exp.id,
    });
    legacy
      .loadIntentLabeling?.({
        datasetId: exp.dataset_id,
        datasetIds: [exp.dataset_id],
        caseId: "",
        assignees: null,
        experimentId: exp.id,
        resumeIncomplete: true,
        historyMode: "replace",
      })
      ?.catch((error: Error) => legacy.showToast?.(error.message, true));
  }, []);

  const scopeOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "all", label: scopeLabel("all", lang) },
      { value: "routing", label: scopeLabel("routing", lang) },
      { value: "lane_change", label: scopeLabel("lane_change", lang) },
    ],
    [lang],
  );

  const modeOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "blind", label: modeLabel("blind", lang) },
      { value: "full", label: modeLabel("full", lang) },
    ],
    [lang],
  );

  const statusOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "all", label: annotationStatusLabel("all", lang) },
      { value: "labeled", label: annotationStatusLabel("labeled", lang) },
      { value: "unlabeled", label: annotationStatusLabel("unlabeled", lang) },
    ],
    [lang],
  );

  const overlapOptions: UiSelectOption[] = useMemo(
    () =>
      [0, 0.1, 0.2, 0.3, 0.5, 1].map((val) => ({
        value: String(val),
        label: `${Math.round(val * 100)}%`,
      })),
    [],
  );

  const memberOptions: MultiSelectOption[] = useMemo(
    () =>
      eligibleMembers.map((m) => ({
        value: m.username,
        label: `${m.username} · ${
          m.role === "admin"
            ? bilingual(lang, "管理员", "Admin")
            : bilingual(lang, "标注人", "Labeler")
        }`,
      })),
    [eligibleMembers, lang],
  );

  const formDisabled = !availableDatasets.length || submitting;
  const fullMode = mode === "full";

  return (
    <div
      className={`ra-intent-experiments-root${!canManageIntent ? " is-readonly" : ""}`}
      data-react-island="intent-experiments"
    >
      <section
        className="intent-experiment-panel"
        aria-label={bilingual(lang, "多盲实验与任务分配", "Blind experiments & task assignment")}
      >
        <div className="intent-experiment-layout">
          {canManageIntent ? (
            <section className="intent-experiment-create" aria-labelledby="intentExperimentTitle">
              <div className="intent-experiment-section-heading">
                <div>
                  <h3 id="intentExperimentTitle">
                    {bilingual(lang, "创建与分配实验", "Create and assign experiment")}
                  </h3>
                </div>
              </div>
              <div className="intent-experiment-create-body">
                <form
                  className="intent-experiment-form"
                  id="intentExperimentForm"
                  aria-disabled={formDisabled ? "true" : undefined}
                  onSubmit={(e) => void handleCreate(e)}
                >
                  <label className="intent-experiment-name-field">
                    <span>{bilingual(lang, "实验名称", "Experiment name")}</span>
                    <span className="intent-experiment-name-control">
                      <input
                        id="intentExperimentName"
                        maxLength={160}
                        autoComplete="off"
                        required
                        disabled={formDisabled}
                        value={name}
                        placeholder={bilingual(
                          lang,
                          "例如 0206 Routing 双盲复核",
                          "For example: 0206 Routing blind review",
                        )}
                        onChange={(e) => {
                          setName(e.target.value);
                          setManualNameEdited(Boolean(e.target.value.trim()));
                        }}
                      />
                      <small
                        id="intentExperimentNameStatus"
                        aria-live="polite"
                        data-status={aiNaming ? "loading" : "ready"}
                        title={
                          aiNaming
                            ? bilingual(
                                lang,
                                "AI 正在后台优化实验名称",
                                "AI is refining the experiment name",
                              )
                            : ""
                        }
                      >
                        {aiNaming ? bilingual(lang, "AI 推理中", "AI naming") : ""}
                      </small>
                    </span>
                  </label>

                  <div className="intent-experiment-form-row">
                    <div className="ra-ie-field">
                      <span>{bilingual(lang, "标注维度", "Label dimension")}</span>
                      <UiSelect
                        id="intentExperimentScopePicker"
                        value={labelScope}
                        options={scopeOptions}
                        disabled={formDisabled}
                        ariaLabel={bilingual(lang, "标注维度", "Label dimension")}
                        onChange={setLabelScope}
                      />
                    </div>

                    <div className="ra-ie-field">
                      <span>{bilingual(lang, "实验模式", "Experiment mode")}</span>
                      <UiSelect
                        id="intentExperimentModePicker"
                        value={mode}
                        options={modeOptions}
                        disabled={formDisabled}
                        ariaLabel={bilingual(lang, "实验模式", "Experiment mode")}
                        onChange={(val) => {
                          setMode(val);
                          if (val === "full") setOverlap("1");
                        }}
                      />
                    </div>

                    <div className="ra-ie-field">
                      <span>{bilingual(lang, "已有标注筛选", "Existing-label filter")}</span>
                      <UiSelect
                        id="intentExperimentAnnotationStatusPicker"
                        value={annotationStatus}
                        options={statusOptions}
                        disabled={formDisabled}
                        ariaLabel={bilingual(lang, "已有标注筛选", "Existing-label filter")}
                        onChange={setAnnotationStatus}
                      />
                    </div>

                    <label>
                      <span>
                        {bilingual(lang, "抽样 Case 数量 ", "Sampled Cases ")}
                        <small>{bilingual(lang, "可小于全量", "Up to full scope")}</small>
                      </span>
                      <input
                        id="intentExperimentCaseCount"
                        type="number"
                        min={1}
                        max={maxCaseCount}
                        step={1}
                        required
                        disabled={formDisabled}
                        value={caseCount}
                        onChange={(e) => setCaseCount(e.target.value)}
                      />
                    </label>

                    <div
                      className={`ra-ie-field${fullMode ? " is-disabled" : ""}`}
                      id="intentExperimentOverlapField"
                    >
                      <span>{bilingual(lang, "交叉复核比例", "Cross-review ratio")}</span>
                      <UiSelect
                        id="intentExperimentOverlapPicker"
                        value={overlap}
                        options={overlapOptions}
                        disabled={formDisabled || fullMode}
                        ariaLabel={bilingual(lang, "交叉复核比例", "Cross-review ratio")}
                        onChange={setOverlap}
                      />
                    </div>

                    <label
                      id="intentExperimentReviewersField"
                      className={fullMode ? "is-disabled" : ""}
                    >
                      <span>{bilingual(lang, "每个 问题标注人数", "Labelers per Case")}</span>
                      <input
                        id="intentExperimentReviewers"
                        type="number"
                        min={1}
                        max={Math.max(1, selectedMembers.length)}
                        step={1}
                        required
                        disabled={formDisabled || fullMode}
                        value={reviewers}
                        onChange={(e) => setReviewers(e.target.value)}
                      />
                    </label>
                  </div>

                  <div className="intent-experiment-members-field">
                    <span>
                      {bilingual(lang, "标注人员 ", "Labelers ")}
                      <small>
                        {bilingual(
                          lang,
                          "至少 1 人 · 仅显示可写账号",
                          "At least 1 · writable accounts only",
                        )}
                      </small>
                    </span>
                    <MultiSelect
                      id="intentExperimentMembers"
                      options={memberOptions}
                      values={selectedMembers}
                      ariaLabel={bilingual(lang, "参与标注人员", "Labelers")}
                      placeholder={bilingual(lang, "选择标注人员", "Select labelers")}
                      lang={lang}
                      disabled={formDisabled}
                      onChange={setSelectedMembers}
                    />
                  </div>

                  <div className="intent-experiment-form-footer">
                    <p id="intentExperimentEstimate">{estimateText}</p>
                    <button
                      className="button button-primary"
                      id="intentCreateExperiment"
                      type="submit"
                      disabled={formDisabled}
                    >
                      {bilingual(lang, "创建并分配", "Create and assign")}
                    </button>
                  </div>
                </form>
              </div>
            </section>
          ) : null}

          <section className="intent-experiment-history" aria-labelledby="intentExperimentHistoryTitle">
            <div className="intent-experiment-section-heading">
              <div>
                <h3 id="intentExperimentHistoryTitle">
                  {bilingual(lang, "实验记录", "Experiment records")}
                </h3>
              </div>
              <strong className="intent-experiment-count" id="intentExperimentCount">
                {experiments.length}
              </strong>
            </div>

            <div className="intent-experiment-list" id="intentExperimentList">
              {experiments.length ? (
                experiments.map((item) => {
                  const datasetName =
                    availableDatasets.find((d) => d.id === item.dataset_id)?.display_name ||
                    item.dataset_id ||
                    "";
                  const overlapText =
                    item.annotation_mode === "blind"
                      ? bilingual(
                          lang,
                          ` · 交叉 ${Math.round(item.overlap_ratio * 100)}% · 每 Case ${
                            item.overlap_reviewers || 2
                          } 人`,
                          ` · ${Math.round(item.overlap_ratio * 100)}% overlap · ${
                            item.overlap_reviewers || 2
                          } per Case`,
                        )
                      : "";
                  const filterText =
                    item.annotation_status_filter && item.annotation_status_filter !== "all"
                      ? ` · ${annotationStatusLabel(item.annotation_status_filter, lang)}`
                      : "";
                  const updateMeta = item.update_count
                    ? bilingual(
                        lang,
                        ` · 已修改 ${item.update_count} 次`,
                        ` · edited ${item.update_count} times`,
                      )
                    : "";
                  const progress = item.progress || {};
                  const total = Math.max(0, Number(progress.total) || 0);
                  const completed = Math.max(0, Number(progress.completed) || 0);
                  const partial = Math.max(0, Number(progress.partial) || 0);
                  const pending = Math.max(0, Number(progress.pending) || 0);
                  const pct = (v: number) => (total ? Math.max(0, Math.min(100, (v * 100) / total)) : 0);
                  const progressTitle = bilingual(
                    lang,
                    `完成 ${completed}，进行中 ${partial}，待标 ${pending}`,
                    `Completed ${completed}, in progress ${partial}, pending ${pending}`,
                  );
                  const progressText = bilingual(
                    lang,
                    `完成 ${completed} / ${total}${partial ? ` · 进行中 ${partial}` : ""}`,
                    `Completed ${completed} / ${total}${partial ? ` · in progress ${partial}` : ""}`,
                  );

                  return (
                    <article
                      key={item.id}
                      className={`intent-experiment-item${item.status === "closed" ? " is-closed" : ""}`}
                      data-intent-experiment={item.id}
                    >
                      <div>
                        <h4>{item.name}</h4>
                        <div className="intent-experiment-meta">
                          {datasetName} · {scopeLabel(item.label_scope, lang)} ·{" "}
                          {modeLabel(item.annotation_mode, lang)}
                          {filterText}
                          {overlapText} ·{" "}
                          {bilingual(lang, `${item.case_count} 个 Case`, `${item.case_count} Cases`)}{" "}
                          ·{" "}
                          {bilingual(
                            lang,
                            `${item.assignment_count} 份任务`,
                            `${item.assignment_count} assignments`,
                          )}{" "}
                          · {item.created_by}
                          {updateMeta}
                        </div>
                      </div>

                      <div className="intent-experiment-controls">
                        <span className="intent-experiment-status">
                          {item.status === "closed"
                            ? bilingual(lang, "已关闭", "Closed")
                            : bilingual(lang, "进行中", "Active")}
                        </span>
                        {item.status === "active" ? (
                          <button
                            className="button button-quiet"
                            type="button"
                            onClick={() => handleResumeExperiment(item)}
                          >
                            {bilingual(lang, "继续标注", "Resume labeling")}
                          </button>
                        ) : null}
                        {item.status === "active" && canManageIntent ? (
                          <>
                            <button
                              className="button button-quiet"
                              type="button"
                              onClick={() => {
                                setEditingExp(item);
                                setEditName(item.name || "");
                                setEditScope(item.label_scope || "all");
                              }}
                            >
                              {bilingual(lang, "编辑实验", "Edit")}
                            </button>
                            <button
                              className="button button-quiet"
                              type="button"
                              onClick={() => setClosingExp(item)}
                            >
                              {bilingual(lang, "关闭实验", "Close")}
                            </button>
                          </>
                        ) : null}
                      </div>

                      <div className="intent-experiment-detail-row">
                        <div className="intent-experiment-member-stats">
                          {(item.members || []).map((member) => (
                            <span key={member.username} title={member.username}>
                              {member.username} ·{" "}
                              {item.annotation_mode === "full"
                                ? bilingual(lang, `${member.total} 个 Case`, `${member.total} Cases`)
                                : bilingual(
                                    lang,
                                    `基础 ${member.base} · 交叉 ${member.cross}`,
                                    `Base ${member.base} · overlap ${member.cross}`,
                                  )}
                            </span>
                          ))}
                        </div>
                        <div className="intent-experiment-progress" title={progressTitle}>
                          <div
                            className="intent-experiment-progress-track"
                            role="img"
                            aria-label={bilingual(
                              lang,
                              `标注进度：${progressTitle}`,
                              `Labeling progress: ${progressTitle}`,
                            )}
                          >
                            <i className="is-complete" style={{ width: `${pct(completed)}%` }} />
                            <i className="is-partial" style={{ width: `${pct(partial)}%` }} />
                            <i className="is-pending" style={{ width: `${pct(pending)}%` }} />
                          </div>
                          <small>{progressText}</small>
                        </div>
                      </div>
                    </article>
                  );
                })
              ) : (
                <div className="intent-experiment-empty">
                  <span aria-hidden="true">◎</span>
                  <strong>
                    {availableDatasets.length
                      ? bilingual(
                          lang,
                          "所选数据集尚未创建实验",
                          "No experiments for the selected datasets",
                        )
                      : bilingual(lang, "暂无可分配数据集", "No datasets available")}
                  </strong>
                  <p>
                    {availableDatasets.length
                      ? bilingual(
                          lang,
                          "完成上方配置后，实验和任务量会显示在这里。",
                          "Experiments and workloads will appear here after setup.",
                        )
                      : bilingual(
                          lang,
                          "当前没有可用于意图实验分配的数据集。",
                          "No dataset is currently available for intent experiment assignment.",
                        )}
                  </p>
                </div>
              )}
            </div>
          </section>
        </div>
      </section>

      {createPortal(
        <dialog
          ref={editDialogRef}
          className="dialog intent-experiment-edit-dialog"
          id="raIntentExperimentEditDialog"
          aria-labelledby="raIntentExperimentEditTitle"
          onClose={() => setEditingExp(null)}
        >
          {editingExp ? (
            <form className="dialog-card" onSubmit={(e) => void handleSaveEdit(e)}>
              <div className="dialog-heading">
                <div>
                  <h2 id="raIntentExperimentEditTitle">
                    {bilingual(lang, "编辑已分配实验", "Edit assigned experiment")}
                  </h2>
                  <p className="dialog-copy">
                    {(() => {
                      const dsName =
                        availableDatasets.find((d) => d.id === editingExp.dataset_id)
                          ?.display_name || editingExp.dataset_id;
                      const memberCount =
                        editingExp.member_count ?? (editingExp.members || []).length;
                      return bilingual(
                        lang,
                        `${dsName} · ${editingExp.case_count} 个 Case · ${memberCount} 名成员`,
                        `${dsName} · ${editingExp.case_count} Cases · ${memberCount} members`,
                      );
                    })()}
                  </p>
                </div>
                <button
                  className="icon-button"
                  type="button"
                  aria-label={bilingual(lang, "关闭", "Close")}
                  onClick={() => setEditingExp(null)}
                >
                  ×
                </button>
              </div>
              <div className="intent-experiment-edit-fields">
                <label>
                  <span>{bilingual(lang, "实验名称", "Experiment name")}</span>
                  <input
                    maxLength={160}
                    autoComplete="off"
                    required
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                  />
                </label>
                <div className="ra-ie-edit-field">
                  <span>{bilingual(lang, "标注维度", "Label dimension")}</span>
                  <UiSelect
                    id="raIntentExperimentEditScope"
                    value={editScope}
                    options={scopeOptions}
                    ariaLabel={bilingual(lang, "标注维度", "Label dimension")}
                    onChange={setEditScope}
                  />
                </div>
              </div>
              <p className="intent-experiment-edit-note">
                {bilingual(
                  lang,
                  "Case 范围、标注成员、实验模式与交叉分配保持不变；本次修改会写入审计记录。",
                  "Case scope, members, mode, and overlap stay unchanged; this edit is audited.",
                )}
              </p>
              <div className="dialog-actions">
                <button
                  className="button button-quiet"
                  type="button"
                  disabled={editSaving}
                  onClick={() => setEditingExp(null)}
                >
                  {bilingual(lang, "取消", "Cancel")}
                </button>
                <button className="button button-primary" type="submit" disabled={editSaving}>
                  {bilingual(lang, "保存修改", "Save changes")}
                </button>
              </div>
            </form>
          ) : null}
        </dialog>,
        document.body,
      )}

      <ModalDialog
        open={Boolean(closingExp)}
        title={bilingual(lang, "关闭实验", "Close experiment")}
        lang={lang}
        onClose={() => !closingBusy && setClosingExp(null)}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              disabled={closingBusy}
              onClick={() => setClosingExp(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={closingBusy}
              onClick={() => void handleConfirmClose()}
            >
              {bilingual(lang, "确认关闭", "Confirm close")}
            </button>
          </>
        }
      >
        <p>
          {bilingual(
            lang,
            `关闭「${closingExp?.name || ""}」后仍会保留实验与分配记录。确认关闭这个实验？`,
            `Closing "${closingExp?.name || ""}" preserves the experiment and assignment records. Close this experiment?`,
          )}
        </p>
      </ModalDialog>
    </div>
  );
};
