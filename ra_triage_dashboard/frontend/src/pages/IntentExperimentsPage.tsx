import React, { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, UiLanguage } from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";
import { showWorkbenchToast } from "../features/review/reviewHelpers";
import { useWorkbench } from "../shell/WorkbenchContext";

interface IntentExperimentMemberStat {
  username: string;
  base: number;
  cross: number;
  total: number;
}

interface IntentExperimentItem {
  id: string;
  dataset_id: string;
  name: string;
  label_scope: string;
  annotation_mode: string;
  annotation_status_filter?: string;
  overlap_ratio: number;
  overlap_reviewers: number;
  case_count: number;
  assignment_count: number;
  status: string;
  created_by: string;
  update_count?: number;
  selected_members?: string[];
  members?: IntentExperimentMemberStat[];
  progress?: { total?: number; completed?: number; partial?: number; pending?: number };
}

interface IntentExperimentsPayload {
  items: IntentExperimentItem[];
  eligible_members: Array<{ username: string; role: string }>;
  annotation_status_counts?: Record<string, Record<string, number>>;
  name_suggestion?: { llm_available?: boolean };
}

export interface IntentExperimentsPageProps {
  active: boolean;
  lang: UiLanguage;
}

function scopeLabel(scope: string, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    all: ["Routing + 变道意图", "Routing + lane-change"],
    routing: ["仅 Routing 意图", "Routing only"],
    lane_change: ["仅变道意图", "Lane-change only"],
  };
  return map[scope] ? bilingual(lang, map[scope][0], map[scope][1]) : scope;
}

function modeLabel(mode: string, lang: UiLanguage): string {
  return mode === "full"
    ? bilingual(lang, "全量盲标", "Full blind labeling")
    : bilingual(lang, "交叉盲标", "Cross blind labeling");
}

function statusFilterLabel(status: string, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    all: ["全部 Case", "All Cases"],
    labeled: ["已有人标注", "Already labeled"],
    unlabeled: ["尚无人标注", "Not yet labeled"],
  };
  return map[status] ? bilingual(lang, map[status][0], map[status][1]) : status;
}

export const IntentExperimentsPage: React.FC<IntentExperimentsPageProps> = ({ active, lang }) => {
  const queryClient = useQueryClient();
  const { session, intentDatasets, selectedIntentDatasets, navigate } = useWorkbench();
  const canManage = Boolean(session.can_manage_intent || session.is_admin);

  // Create form state
  const [name, setName] = useState("");
  const [manualName, setManualName] = useState(false);
  const [labelScope, setLabelScope] = useState("all");
  const [annotationMode, setAnnotationMode] = useState("blind");
  const [annotationStatus, setAnnotationStatus] = useState("all");
  const [caseCount, setCaseCount] = useState("50");
  const [overlapRatio, setOverlapRatio] = useState("0.2");
  const [overlapReviewers, setOverlapReviewers] = useState("2");
  const [members, setMembers] = useState<string[]>([]);
  const [aiNaming, setAiNaming] = useState(false);

  // Converged 062 Protected Reallocation Edit dialog state
  const [editTarget, setEditTarget] = useState<IntentExperimentItem | null>(null);
  const [editName, setEditName] = useState("");
  const [editScope, setEditScope] = useState("all");
  const [editMode, setEditMode] = useState("blind");
  const [editOverlap, setEditOverlap] = useState("0.2");
  const [editReviewers, setEditReviewers] = useState("2");
  const [editMembers, setEditMembers] = useState<string[]>([]);
  const [editError, setEditError] = useState("");

  // Close confirmation dialog
  const [closeTarget, setCloseTarget] = useState<IntentExperimentItem | null>(null);

  const scopeKey = selectedIntentDatasets.join(",");

  const expQuery = useQuery<IntentExperimentsPayload>({
    queryKey: ["intent-experiments", scopeKey],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams();
      selectedIntentDatasets.forEach((id) => qs.append("dataset_id", id));
      return apiRequest<IntentExperimentsPayload>(
        `/api/intent-experiments${qs.toString() ? `?${qs.toString()}` : ""}`,
        { signal },
      );
    },
    enabled: active && selectedIntentDatasets.length > 0,
    staleTime: 10_000,
  });

  const eligibleMembers = expQuery.data?.eligible_members || [];
  const statusCounts = expQuery.data?.annotation_status_counts || {};
  const experiments = expQuery.data?.items || [];

  const maxAvailableCount = useMemo(() => {
    const counts = selectedIntentDatasets.map((id) => {
      const ds = intentDatasets.find((d) => d.id === id);
      return Number(statusCounts[id]?.[annotationStatus] ?? ds?.case_count ?? 50);
    });
    return Math.max(1, ...counts);
  }, [selectedIntentDatasets, intentDatasets, statusCounts, annotationStatus]);

  useEffect(() => {
    const num = Number(caseCount) || 0;
    if (num < 1 || num > maxAvailableCount) {
      setCaseCount(String(maxAvailableCount));
    }
  }, [maxAvailableCount]);

  // Rule-based & AI name suggestion
  const ruleSuggestedName = useMemo(() => {
    const dsLabel = selectedIntentDatasets
      .map((id) => intentDatasets.find((d) => d.id === id)?.display_name.split("·")[0]?.trim() || id)
      .join("+");
    const modeStr =
      annotationMode === "full"
        ? "全量盲标"
        : members.length > 1 && Number(overlapReviewers) > 1 && Number(overlapRatio) > 0
          ? `交叉${Math.round(Number(overlapRatio) * 100)}%复核`
          : "分工盲标";
    const scopeStr = labelScope === "routing" ? "Routing" : labelScope === "lane_change" ? "变道意图" : "Routing+变道意图";
    return `${dsLabel || "Routing"} ${scopeStr} ${modeStr} ${Number(caseCount) || 1} Case`.slice(0, 80);
  }, [selectedIntentDatasets, intentDatasets, annotationMode, members.length, overlapReviewers, overlapRatio, labelScope, caseCount]);

  useEffect(() => {
    if (!manualName) setName(ruleSuggestedName);
  }, [ruleSuggestedName, manualName]);

  const requestAiName = async () => {
    if (!canManage || !selectedIntentDatasets.length) return;
    setAiNaming(true);
    try {
      const payload = await apiRequest<{ suggestion?: string; source?: string }>(
        "/api/intent-experiments/name-suggestion",
        {
          method: "POST",
          body: JSON.stringify({
            dataset_ids: selectedIntentDatasets,
            annotation_mode: annotationMode,
            label_scope: labelScope,
            annotation_status_filter: annotationStatus,
            case_count: Number(caseCount) || 1,
            overlap_ratio: Number(overlapRatio) || 0,
            overlap_reviewers: Number(overlapReviewers) || 1,
            member_count: members.length,
            draft_name: manualName ? name : "",
          }),
        },
      );
      if (payload.suggestion) {
        setName(payload.suggestion.trim());
        setManualName(false);
      }
    } catch {
      // fallback keeps rule name
    } finally {
      setAiNaming(false);
    }
  };

  const createMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ experiments?: IntentExperimentItem[]; experiment?: IntentExperimentItem }>(
        "/api/intent-experiments",
        {
          method: "POST",
          body: JSON.stringify({
            dataset_id: selectedIntentDatasets[0],
            dataset_ids: selectedIntentDatasets,
            name: name.trim(),
            annotation_mode: annotationMode,
            label_scope: labelScope,
            annotation_status_filter: annotationStatus,
            case_count: Number(caseCount) || 0,
            overlap_ratio: annotationMode === "full" ? 1 : Number(overlapRatio) || 0,
            overlap_reviewers: annotationMode === "full" ? Math.max(1, members.length) : Number(overlapReviewers) || 1,
            members,
          }),
        },
      ),
    onSuccess: () => {
      setManualName(false);
      setMembers([]);
      void queryClient.invalidateQueries({ queryKey: ["intent-experiments"] });
      showWorkbenchToast(
        bilingual(lang, "实验已创建，任务分配快照已保存。", "Experiment created and assignment snapshot saved."),
      );
    },
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

  const updateMutation = useMutation({
    mutationFn: () => {
      if (!editTarget) throw new Error("No experiment selected");
      return apiRequest<{ experiment?: IntentExperimentItem }>(
        `/api/intent-experiments/${encodeURIComponent(editTarget.id)}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            name: editName.trim(),
            label_scope: editScope,
            annotation_mode: editMode,
            overlap_ratio: editMode === "full" ? 1 : Number(editOverlap),
            overlap_reviewers: editMode === "full" ? Math.max(1, editMembers.length) : Number(editReviewers),
            members: editMembers,
            expected_update_count: editTarget.update_count || 0,
          }),
        },
      );
    },
    onSuccess: () => {
      setEditTarget(null);
      setEditError("");
      void queryClient.invalidateQueries({ queryKey: ["intent-experiments"] });
      showWorkbenchToast(
        bilingual(
          lang,
          "实验配置已保存，已有标注完整保留。",
          "Experiment settings saved. Existing annotations preserved.",
        ),
      );
    },
    onError: (err: Error) => setEditError(err.message),
  });

  const closeMutation = useMutation({
    mutationFn: (id: string) =>
      apiRequest(`/api/intent-experiments/${encodeURIComponent(id)}/close`, { method: "POST" }),
    onSuccess: () => {
      setCloseTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["intent-experiments"] });
      showWorkbenchToast(
        bilingual(lang, "实验已关闭，历史分配仍然保留。", "Experiment closed; assignment history preserved."),
      );
    },
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

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
      { value: "all", label: statusFilterLabel("all", lang) },
      { value: "labeled", label: statusFilterLabel("labeled", lang) },
      { value: "unlabeled", label: statusFilterLabel("unlabeled", lang) },
    ],
    [lang],
  );

  const overlapOptions: UiSelectOption[] = useMemo(
    () =>
      ["0", "0.1", "0.2", "0.3", "0.5", "1"].map((v) => ({
        value: v,
        label: `${Math.round(Number(v) * 100)}%`,
      })),
    [],
  );

  const memberOptions = useMemo<MultiSelectOption[]>(
    () =>
      eligibleMembers.map((m) => ({
        value: m.username,
        label: `${m.username} · ${m.role === "admin" ? bilingual(lang, "管理员", "Admin") : bilingual(lang, "标注人", "Labeler")}`,
      })),
    [eligibleMembers, lang],
  );

  const openEditor = (exp: IntentExperimentItem) => {
    const initialMembers = exp.selected_members || (exp.members || []).map((m) => m.username);
    setEditTarget(exp);
    setEditName(exp.name);
    setEditScope(exp.label_scope || "all");
    setEditMode(exp.annotation_mode || "blind");
    setEditOverlap(String(exp.overlap_ratio ?? 0.2));
    setEditReviewers(String(exp.overlap_reviewers || 1));
    setEditMembers(initialMembers);
    setEditError("");
  };

  return (
    <section
      id="intentExperimentsPage"
      className="app-page ra-react-page"
      data-page="intent-experiments"
      data-react-island="intent-experiments"
    >
      {canManage && (
        <div className="panel-card intent-experiment-create">
          <div className="ra-page-header-row">
            <h2>{bilingual(lang, "创建意图标注实验", "Create Intent Labeling Experiment")}</h2>
            {expQuery.data?.name_suggestion?.llm_available && (
              <button
                type="button"
                className="button button-quiet"
                disabled={aiNaming}
                onClick={() => void requestAiName()}
              >
                {aiNaming
                  ? bilingual(lang, "AI 命名中…", "AI naming…")
                  : bilingual(lang, "AI 优化实验名", "AI suggest name")}
              </button>
            )}
          </div>

          <form
            className="ra-filter-grid"
            style={{ marginTop: 12 }}
            onSubmit={(e) => {
              e.preventDefault();
              if (!members.length) {
                showWorkbenchToast(bilingual(lang, "请至少选择 1 名标注成员。", "Select at least 1 labeler."), true);
                return;
              }
              createMutation.mutate();
            }}
          >
            <label className="ra-field-stack" style={{ gridColumn: "span 2" }}>
              <span>{bilingual(lang, "实验名称", "Experiment name")}</span>
              <input
                type="text"
                value={name}
                maxLength={160}
                required
                onChange={(e) => {
                  setName(e.target.value);
                  setManualName(Boolean(e.target.value.trim()));
                }}
              />
            </label>
            <div className="ra-field-stack">
              <span>{bilingual(lang, "标注维度", "Label scope")}</span>
              <UiSelect
                id="raIntentExpScope"
                value={labelScope}
                options={scopeOptions}
                ariaLabel={bilingual(lang, "标注维度", "Label scope")}
                onChange={setLabelScope}
              />
            </div>
            <div className="ra-field-stack">
              <span>{bilingual(lang, "分配模式", "Allocation mode")}</span>
              <UiSelect
                id="raIntentExpMode"
                value={annotationMode}
                options={modeOptions}
                ariaLabel={bilingual(lang, "分配模式", "Allocation mode")}
                onChange={setAnnotationMode}
              />
            </div>
            <div className="ra-field-stack">
              <span>{bilingual(lang, "候选 Case 范围", "Candidate scope")}</span>
              <UiSelect
                id="raIntentExpStatus"
                value={annotationStatus}
                options={statusOptions}
                ariaLabel={bilingual(lang, "候选 Case 范围", "Candidate scope")}
                onChange={setAnnotationStatus}
              />
            </div>
            <label className="ra-field-stack">
              <span>
                {bilingual(lang, `Case 数量（上限 ${maxAvailableCount}）`, `Cases (max ${maxAvailableCount})`)}
              </span>
              <input
                type="number"
                min={1}
                max={maxAvailableCount}
                value={caseCount}
                onChange={(e) => setCaseCount(e.target.value)}
              />
            </label>
            <div className="ra-field-stack">
              <span>{bilingual(lang, "交叉复核比例", "Overlap ratio")}</span>
              <UiSelect
                id="raIntentExpOverlap"
                value={annotationMode === "full" ? "1" : overlapRatio}
                options={overlapOptions}
                disabled={annotationMode === "full"}
                ariaLabel={bilingual(lang, "交叉比例", "Overlap ratio")}
                onChange={setOverlapRatio}
              />
            </div>
            <label className="ra-field-stack">
              <span>{bilingual(lang, "交叉人数", "Reviewers per overlap")}</span>
              <input
                type="number"
                min={1}
                max={Math.max(1, members.length)}
                value={annotationMode === "full" ? String(Math.max(1, members.length)) : overlapReviewers}
                disabled={annotationMode === "full"}
                onChange={(e) => setOverlapReviewers(e.target.value)}
              />
            </label>
            <div className="ra-field-stack" style={{ gridColumn: "span 2" }}>
              <span>{bilingual(lang, "参与成员", "Labelers")}</span>
              <MultiSelect
                id="raIntentExpMembers"
                options={memberOptions}
                values={members}
                lang={lang}
                placeholder={bilingual(lang, "选择标注成员", "Select labelers")}
                ariaLabel={bilingual(lang, "选择标注成员", "Select labelers")}
                onChange={setMembers}
              />
            </div>
            <div className="ra-inline-actions" style={{ alignItems: "flex-end" }}>
              <button
                type="submit"
                className="button button-primary ra-primary-touch"
                disabled={createMutation.isPending || !members.length || !selectedIntentDatasets.length}
              >
                {createMutation.isPending
                  ? bilingual(lang, "创建中…", "Creating…")
                  : bilingual(lang, "创建实验分配", "Create experiment")}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Experiments List */}
      <div className="panel-card">
        <div className="ra-page-header-row">
          <h3>
            {bilingual(lang, `实验列表 (${experiments.length})`, `Experiments (${experiments.length})`)}
          </h3>
          <button
            type="button"
            className="button button-quiet"
            disabled={expQuery.isFetching}
            onClick={() => void expQuery.refetch()}
          >
            {bilingual(lang, "刷新", "Refresh")}
          </button>
        </div>

        {expQuery.isLoading ? (
          <div className="no-asset">{bilingual(lang, "正在加载实验…", "Loading experiments…")}</div>
        ) : !experiments.length ? (
          <div className="no-asset">
            {bilingual(lang, "所选数据集尚未创建实验。", "No experiments for the selected datasets.")}
          </div>
        ) : (
          <div className="intent-experiment-list" style={{ marginTop: 12 }}>
            {experiments.map((exp) => {
              const prog = exp.progress || {};
              const total = Math.max(0, Number(prog.total) || 0);
              const completed = Math.max(0, Number(prog.completed) || 0);
              const partial = Math.max(0, Number(prog.partial) || 0);
              const pct = total ? Math.round((completed * 100) / total) : 0;
              return (
                <article
                  key={exp.id}
                  className={`intent-experiment-item${exp.status === "closed" ? " is-closed" : ""}`}
                >
                  <div>
                    <h4>{exp.name}</h4>
                    <div className="intent-experiment-meta">
                      {exp.dataset_id} · {scopeLabel(exp.label_scope, lang)} ·{" "}
                      {modeLabel(exp.annotation_mode, lang)} · {exp.case_count} Cases ·{" "}
                      {exp.assignment_count} {bilingual(lang, "份任务", "assignments")} · {exp.created_by}
                      {exp.update_count
                        ? bilingual(lang, ` · 已修改 ${exp.update_count} 次`, ` · edited ${exp.update_count}×`)
                        : ""}
                    </div>
                  </div>
                  <div className="intent-experiment-controls">
                    <span className="intent-experiment-status">
                      {exp.status === "closed"
                        ? bilingual(lang, "已关闭", "Closed")
                        : bilingual(lang, "进行中", "Active")}
                    </span>
                    {exp.status === "active" && (
                      <button
                        type="button"
                        className="button button-quiet"
                        onClick={() =>
                          navigate("intent", { dataset: exp.dataset_id, experiment: exp.id })
                        }
                      >
                        {bilingual(lang, "继续标注", "Resume labeling")}
                      </button>
                    )}
                    {exp.status === "active" && canManage && (
                      <>
                        <button
                          type="button"
                          className="button button-quiet"
                          onClick={() => openEditor(exp)}
                        >
                          {bilingual(lang, "编辑实验", "Edit")}
                        </button>
                        <button
                          type="button"
                          className="button button-quiet"
                          onClick={() => setCloseTarget(exp)}
                        >
                          {bilingual(lang, "关闭实验", "Close")}
                        </button>
                      </>
                    )}
                  </div>
                  <div className="intent-experiment-detail-row">
                    <div className="intent-experiment-member-stats">
                      {(exp.members || []).map((m) => (
                        <span key={m.username}>
                          {m.username} ·{" "}
                          {exp.annotation_mode === "full"
                            ? `${m.total} Cases`
                            : bilingual(lang, `基础 ${m.base} · 交叉 ${m.cross}`, `Base ${m.base} · overlap ${m.cross}`)}
                        </span>
                      ))}
                    </div>
                    <div className="intent-experiment-progress">
                      <div className="intent-experiment-progress-track">
                        <i className="is-complete" style={{ width: `${pct}%` }} />
                      </div>
                      <small>
                        {bilingual(
                          lang,
                          `完成 ${completed} / ${total}${partial ? ` · 进行中 ${partial}` : ""}`,
                          `Completed ${completed} / ${total}${partial ? ` · in progress ${partial}` : ""}`,
                        )}
                      </small>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>

      {/* Protected Reallocation Edit Modal (PRE 062 convergence) */}
      <ModalDialog
        open={Boolean(editTarget)}
        title={bilingual(lang, "编辑意图标注实验（受保护再分配）", "Edit Intent Experiment (Protected Reallocation)")}
        lang={lang}
        onClose={() => {
          if (!updateMutation.isPending) setEditTarget(null);
        }}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              disabled={updateMutation.isPending}
              onClick={() => setEditTarget(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-primary ra-primary-touch"
              disabled={updateMutation.isPending || !editMembers.length || !editName.trim()}
              onClick={() => updateMutation.mutate()}
            >
              {updateMutation.isPending
                ? bilingual(lang, "保存中…", "Saving…")
                : bilingual(lang, "保存修改", "Save changes")}
            </button>
          </>
        }
      >
        {editTarget && (
          <div className="ra-modal-stack">
            <p className="muted">
              {bilingual(
                lang,
                `${editTarget.dataset_id} · ${editTarget.case_count} 个 Case · 已选 ${editMembers.length} 名成员（已有标注将完整保留，仅重新分配未完成槽位）。`,
                `${editTarget.dataset_id} · ${editTarget.case_count} Cases · ${editMembers.length} labelers selected (existing annotations are preserved; only unfinished slots reallocate).`,
              )}
            </p>
            {editError && <p className="ra-inline-feedback is-error">{editError}</p>}
            <label className="ra-field-stack">
              <span>{bilingual(lang, "实验名称", "Experiment name")}</span>
              <input
                type="text"
                maxLength={160}
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
              />
            </label>
            <div className="ra-filter-grid">
              <div className="ra-field-stack">
                <span>{bilingual(lang, "标注维度", "Label scope")}</span>
                <UiSelect
                  id="raIntentEditScope"
                  value={editScope}
                  options={scopeOptions}
                  ariaLabel={bilingual(lang, "编辑标注维度", "Edit label scope")}
                  onChange={setEditScope}
                />
              </div>
              <div className="ra-field-stack">
                <span>{bilingual(lang, "分配模式", "Allocation mode")}</span>
                <UiSelect
                  id="raIntentEditMode"
                  value={editMode}
                  options={modeOptions}
                  ariaLabel={bilingual(lang, "编辑分配模式", "Edit allocation mode")}
                  onChange={setEditMode}
                />
              </div>
              <div className="ra-field-stack">
                <span>{bilingual(lang, "交叉比例", "Overlap ratio")}</span>
                <UiSelect
                  id="raIntentEditOverlap"
                  value={editMode === "full" ? "1" : editOverlap}
                  options={overlapOptions}
                  disabled={editMode === "full"}
                  ariaLabel={bilingual(lang, "编辑交叉比例", "Edit overlap ratio")}
                  onChange={setEditOverlap}
                />
              </div>
              <label className="ra-field-stack">
                <span>{bilingual(lang, "交叉人数", "Reviewers per overlap")}</span>
                <input
                  type="number"
                  min={1}
                  max={Math.max(1, editMembers.length)}
                  value={editMode === "full" ? String(Math.max(1, editMembers.length)) : editReviewers}
                  disabled={editMode === "full"}
                  onChange={(e) => setEditReviewers(e.target.value)}
                />
              </label>
            </div>
            <div className="ra-field-stack">
              <span>{bilingual(lang, "参与成员", "Labelers")}</span>
              <MultiSelect
                id="raIntentEditMembers"
                options={memberOptions}
                values={editMembers}
                lang={lang}
                placeholder={bilingual(lang, "选择标注成员", "Select labelers")}
                ariaLabel={bilingual(lang, "编辑标注成员", "Edit labelers")}
                onChange={setEditMembers}
              />
            </div>
          </div>
        )}
      </ModalDialog>

      {/* Close Confirm Modal */}
      <ModalDialog
        open={Boolean(closeTarget)}
        title={bilingual(lang, "确认关闭实验", "Confirm Close Experiment")}
        lang={lang}
        onClose={() => {
          if (!closeMutation.isPending) setCloseTarget(null);
        }}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              disabled={closeMutation.isPending}
              onClick={() => setCloseTarget(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-danger"
              disabled={closeMutation.isPending}
              onClick={() => closeTarget && closeMutation.mutate(closeTarget.id)}
            >
              {bilingual(lang, "确认关闭", "Close experiment")}
            </button>
          </>
        }
      >
        <p>
          {bilingual(
            lang,
            `关闭「${closeTarget?.name || ""}」后仍会保留实验与历史分配记录。确认继续？`,
            `Closing "${closeTarget?.name || ""}" preserves all experiment and assignment history. Continue?`,
          )}
        </p>
      </ModalDialog>
    </section>
  );
};
