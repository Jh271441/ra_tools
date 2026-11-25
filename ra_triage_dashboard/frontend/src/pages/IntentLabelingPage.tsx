import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, UiLanguage } from "../bridge/useWorkbenchBridge";
import { IssueDiscussion } from "../components/discussion/IssueDiscussion";
import { ModalDialog } from "../components/ui/ModalDialog";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";
import { useShortcut } from "../core/shortcutManager";
import { normalizeAssetUrl, showWorkbenchToast } from "../features/review/reviewHelpers";
import { useWorkbench } from "../shell/WorkbenchContext";

const ROUTING_OPTIONS = [
  { value: "left_turn", key: "1", zh: "左转", en: "Left turn" },
  { value: "right_turn", key: "2", zh: "右转", en: "Right turn" },
  { value: "straight", key: "3", zh: "直行", en: "Straight" },
  { value: "u_turn", key: "4", zh: "掉头", en: "U-turn" },
  { value: "parking", key: "5", zh: "泊车", en: "Parking" },
] as const;

const LANE_OPTIONS = [
  { value: "no_lane_change", key: "6", zh: "非变道", en: "No lane change" },
  { value: "left_lane_change", key: "7", zh: "左变道", en: "Left lane change" },
  { value: "right_lane_change", key: "8", zh: "右变道", en: "Right lane change" },
] as const;

interface IntentTimepoint {
  id: string;
  offset_ms: number;
  camera_delta_ms?: number | null;
  camera?: { url?: string; thumbnail_url?: string };
  bev?: { url?: string; thumbnail_url?: string };
}

interface IntentOverride {
  timepoint_id: string;
  offset_ms: number;
  routing_intent?: string;
  lane_change_intent?: string;
}

interface IntentCaseDetail {
  case_id: string;
  issue_id: string;
  dataset_id?: string;
  ordinal?: number;
  case_count?: number;
  previous_case?: { case_id: string; dataset_id: string } | null;
  next_case?: { case_id: string; dataset_id: string } | null;
  experiment?: { label_scope?: string };
  timepoints: IntentTimepoint[];
  labels?: {
    revision_id?: number | null;
    routing_default?: string;
    lane_change_default?: string;
    overrides?: IntentOverride[];
  };
  collaboration?: {
    blind_active?: boolean;
    answers_revealed?: boolean;
    contributors?: Array<{
      username: string;
      is_current?: boolean;
      revealed?: boolean;
      labeled?: boolean;
      completed?: boolean;
      routing_default?: string;
      lane_change_default?: string;
      overrides?: IntentOverride[];
    }>;
    comments?: Array<{ id: number }>;
  };
}

export interface IntentLabelingPageProps {
  active: boolean;
  lang: UiLanguage;
}

function fmtOffset(ms: number): string {
  if (ms % 1000 === 0) return `${ms >= 0 ? "+" : ""}${ms / 1000}s`;
  return `${ms >= 0 ? "+" : ""}${ms}ms`;
}

export const IntentLabelingPage: React.FC<IntentLabelingPageProps> = ({ active, lang }) => {
  const queryClient = useQueryClient();
  const { session, selectedIntentDatasets } = useWorkbench();
  const canAnnotate = session.can_annotate_intent !== false;
  const isAdmin = Boolean(session.is_admin && session.verified);

  const [experimentId, setExperimentId] = useState<string>(() =>
    typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("experiment") || "" : "",
  );
  const [assignees, setAssignees] = useState<string[]>([]);
  const [targetCase, setTargetCase] = useState<string>(() =>
    typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("case") || "" : "",
  );
  const [caseInput, setCaseInput] = useState("");
  const [revealAnswers, setRevealAnswers] = useState(false);

  // Active labeling draft state
  const [activeTpId, setActiveTpId] = useState("");
  const [aggregate, setAggregate] = useState<{ routing: string; laneChange: string }>({
    routing: "",
    laneChange: "",
  });
  const [overrides, setOverrides] = useState<Record<string, IntentOverride>>({});
  const [revisionId, setRevisionId] = useState<number | null>(null);
  const [undoStack, setUndoStack] = useState<
    Array<{ aggregate: { routing: string; laneChange: string }; overrides: Record<string, IntentOverride> }>
  >([]);
  const [saveState, setSaveState] = useState<"idle" | "dirty" | "saving" | "saved" | "error">("idle");
  const [discussionOpen, setDiscussionOpen] = useState(false);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

  const saveTimerRef = useRef<number | null>(null);
  const scopeKey = selectedIntentDatasets.join(",");

  const assigneesQuery = useQuery<{
    items?: Array<{ username: string; case_count: number }>;
    experiments?: Array<{ id: string; dataset_id: string; name: string; label_scope?: string; case_count?: number }>;
  }>({
    queryKey: ["intent-assignees", scopeKey, experimentId],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams();
      selectedIntentDatasets.forEach((id) => qs.append("dataset_id", id));
      if (experimentId) qs.set("experiment_id", experimentId);
      return apiRequest(`/api/intent-assignees?${qs.toString()}`, { signal });
    },
    enabled: active && selectedIntentDatasets.length > 0,
    staleTime: 15_000,
  });

  const queueQuery = useQuery<{
    items?: Array<{
      case_id: string;
      issue_id: string;
      dataset_id: string;
      ordinal?: number;
      previous?: { case_id: string; dataset_id: string } | null;
      next?: { case_id: string; dataset_id: string } | null;
    }>;
    scope_total?: number;
  }>({
    queryKey: ["intent-queue", scopeKey, experimentId, assignees.join(","), targetCase],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams();
      selectedIntentDatasets.forEach((id) => qs.append("dataset_id", id));
      assignees.forEach((a) => qs.append("assignee", a));
      if (experimentId) qs.set("experiment_id", experimentId);
      qs.set("status", "all");
      if (targetCase) {
        qs.set("q", targetCase);
        qs.set("page_size", "50");
      } else {
        qs.set("page_size", "1");
      }
      return apiRequest(`/api/intent-cases?${qs.toString()}`, { signal });
    },
    enabled: active && selectedIntentDatasets.length > 0,
    staleTime: 10_000,
  });

  const queueItem = useMemo(() => {
    const list = queueQuery.data?.items || [];
    if (!targetCase) return list[0] || null;
    return (
      list.find((it) => it.case_id === targetCase || it.issue_id === targetCase) || list[0] || null
    );
  }, [queueQuery.data, targetCase]);

  const activeDatasetId = queueItem?.dataset_id || selectedIntentDatasets[0] || "";
  const activeCaseId = queueItem?.case_id || "";

  const caseQuery = useQuery<IntentCaseDetail>({
    queryKey: ["intent-case", activeDatasetId, activeCaseId, experimentId, assignees.join(","), revealAnswers],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams();
      assignees.forEach((a) => qs.append("assignee", a));
      if (experimentId) qs.set("experiment_id", experimentId);
      if (revealAnswers) qs.set("reveal_answers", "true");
      return apiRequest<IntentCaseDetail>(
        `/api/intent-datasets/${encodeURIComponent(activeDatasetId)}/cases/${encodeURIComponent(activeCaseId)}${qs.toString() ? `?${qs.toString()}` : ""}`,
        { signal },
      );
    },
    enabled: active && Boolean(activeDatasetId && activeCaseId),
    staleTime: 5_000,
  });

  const caseData = caseQuery.data;

  // Hydrate labeling draft when case changes
  useEffect(() => {
    if (!caseData) return;
    setCaseInput(caseData.issue_id || caseData.case_id);
    setRevisionId(caseData.labels?.revision_id ?? null);
    setAggregate({
      routing: caseData.labels?.routing_default || "",
      laneChange: caseData.labels?.lane_change_default || "",
    });
    const ovMap: Record<string, IntentOverride> = {};
    for (const ov of caseData.labels?.overrides || []) {
      ovMap[ov.timepoint_id] = { ...ov };
    }
    setOverrides(ovMap);
    setUndoStack([]);
    setSaveState(caseData.labels?.revision_id ? "saved" : "idle");
    setActiveTpId(caseData.timepoints?.[0]?.id || "");
  }, [caseData?.case_id]);

  const saveMutation = useMutation({
    mutationFn: (payload: {
      routing: string;
      laneChange: string;
      overridesList: IntentOverride[];
      expectedRev: number | null;
    }) =>
      apiRequest<{ labels?: { revision_id?: number | null } }>(
        `/api/intent-datasets/${encodeURIComponent(activeDatasetId)}/cases/${encodeURIComponent(activeCaseId)}/labels`,
        {
          method: "PUT",
          body: JSON.stringify({
            expected_revision_id: payload.expectedRev,
            routing_default: payload.routing,
            lane_change_default: payload.laneChange,
            overrides: payload.overridesList,
            author: session.username || "",
          }),
        },
      ),
    onSuccess: (res) => {
      setRevisionId(res.labels?.revision_id ?? null);
      setSaveState("saved");
    },
    onError: (err: Error) => {
      setSaveState("error");
      showWorkbenchToast(err.message, true);
    },
  });

  const scheduleSave = useCallback(
    (nextAgg: { routing: string; laneChange: string }, nextOv: Record<string, IntentOverride>) => {
      if (!activeDatasetId || !activeCaseId) return;
      setSaveState("dirty");
      if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = window.setTimeout(() => {
        setSaveState("saving");
        saveMutation.mutate({
          routing: nextAgg.routing,
          laneChange: nextAgg.laneChange,
          overridesList: Object.values(nextOv).map((ov) => ({
            timepoint_id: ov.timepoint_id,
            offset_ms: ov.offset_ms,
            routing_intent: ov.routing_intent || "",
            lane_change_intent: ov.lane_change_intent || "",
          })),
          expectedRev: revisionId,
        });
      }, 600);
    },
    [activeDatasetId, activeCaseId, revisionId, saveMutation],
  );

  const labelScope = caseData?.experiment?.label_scope || "all";
  const routingEnabled = labelScope === "all" || labelScope === "routing";
  const laneEnabled = labelScope === "all" || labelScope === "lane_change";

  const activeTp = useMemo(
    () => (caseData?.timepoints || []).find((tp) => tp.id === activeTpId) || caseData?.timepoints?.[0] || null,
    [caseData, activeTpId],
  );

  const effectiveFor = useCallback(
    (tpId: string) => {
      const ov = overrides[tpId];
      return {
        routing: ov?.routing_intent || aggregate.routing || "",
        laneChange: ov?.lane_change_intent || aggregate.laneChange || "",
      };
    },
    [aggregate, overrides],
  );

  const applyAggregate = useCallback(
    (axis: "routing" | "laneChange", value: string) => {
      if (!canAnnotate) return;
      setUndoStack((s) => [...s.slice(-49), { aggregate: { ...aggregate }, overrides: { ...overrides } }]);
      const nextAgg = { ...aggregate, [axis]: value };
      const nextOv = { ...overrides };
      const key = axis === "routing" ? "routing_intent" : "lane_change_intent";
      for (const [id, ov] of Object.entries(nextOv)) {
        if (ov[key] === value) {
          const copy = { ...ov };
          delete copy[key];
          if (!copy.routing_intent && !copy.lane_change_intent) delete nextOv[id];
          else nextOv[id] = copy;
        }
      }
      setAggregate(nextAgg);
      setOverrides(nextOv);
      scheduleSave(nextAgg, nextOv);
    },
    [canAnnotate, aggregate, overrides, scheduleSave],
  );

  const applyFrameLabel = useCallback(
    (axis: "routing" | "laneChange", value: string) => {
      if (!canAnnotate || !activeTp) return;
      setUndoStack((s) => [...s.slice(-49), { aggregate: { ...aggregate }, overrides: { ...overrides } }]);
      const nextOv = { ...overrides };
      const key = axis === "routing" ? "routing_intent" : "lane_change_intent";
      const base = axis === "routing" ? aggregate.routing : aggregate.laneChange;
      const copy: IntentOverride = {
        ...(nextOv[activeTp.id] || { timepoint_id: activeTp.id, offset_ms: activeTp.offset_ms }),
      };
      if (value === base) delete copy[key];
      else copy[key] = value;
      if (!copy.routing_intent && !copy.lane_change_intent) delete nextOv[activeTp.id];
      else nextOv[activeTp.id] = copy;
      setOverrides(nextOv);
      scheduleSave(aggregate, nextOv);
    },
    [canAnnotate, activeTp, aggregate, overrides, scheduleSave],
  );

  const handleUndo = useCallback(() => {
    setUndoStack((prev) => {
      if (!prev.length) return prev;
      const last = prev[prev.length - 1];
      setAggregate(last.aggregate);
      setOverrides(last.overrides);
      scheduleSave(last.aggregate, last.overrides);
      return prev.slice(0, -1);
    });
  }, [scheduleSave]);

  const moveFrame = useCallback(
    (delta: number) => {
      const list = caseData?.timepoints || [];
      const idx = list.findIndex((t) => t.id === activeTp?.id);
      if (idx < 0) return;
      const nextIdx = Math.max(0, Math.min(list.length - 1, idx + delta));
      setActiveTpId(list[nextIdx].id);
    },
    [caseData, activeTp],
  );

  // Page keyboard shortcuts via ShortcutManager
  useShortcut("page", "ArrowLeft", () => moveFrame(-1), { enabled: active });
  useShortcut("page", "ArrowRight", () => moveFrame(1), { enabled: active });
  useShortcut(
    "page",
    "ArrowUp",
    () => {
      if (queueItem?.previous?.case_id) setTargetCase(queueItem.previous.case_id);
    },
    { enabled: active },
  );
  useShortcut(
    "page",
    "ArrowDown",
    () => {
      if (queueItem?.next?.case_id) setTargetCase(queueItem.next.case_id);
    },
    { enabled: active },
  );
  useShortcut("page", "d", () => setDiscussionOpen(true), { enabled: active });
  useShortcut("page", "Ctrl+z", handleUndo, { enabled: active });
  useShortcut("page", "Meta+z", handleUndo, { enabled: active });
  useShortcut("page", "1", () => routingEnabled && applyFrameLabel("routing", "left_turn"), { enabled: active });
  useShortcut("page", "2", () => routingEnabled && applyFrameLabel("routing", "right_turn"), { enabled: active });
  useShortcut("page", "3", () => routingEnabled && applyFrameLabel("routing", "straight"), { enabled: active });
  useShortcut("page", "4", () => routingEnabled && applyFrameLabel("routing", "u_turn"), { enabled: active });
  useShortcut("page", "5", () => routingEnabled && applyFrameLabel("routing", "parking"), { enabled: active });
  useShortcut("page", "6", () => laneEnabled && applyFrameLabel("laneChange", "no_lane_change"), { enabled: active });
  useShortcut("page", "7", () => laneEnabled && applyFrameLabel("laneChange", "left_lane_change"), { enabled: active });
  useShortcut("page", "8", () => laneEnabled && applyFrameLabel("laneChange", "right_lane_change"), { enabled: active });

  const experimentOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "", label: bilingual(lang, "未分配（全部 Case）", "Unassigned (all Cases)") },
      ...(assigneesQuery.data?.experiments || []).map((e) => ({
        value: e.id,
        label: `${e.name} · ${e.case_count ?? 0} Cases`,
      })),
    ],
    [assigneesQuery.data, lang],
  );

  const assigneeOptions = useMemo<MultiSelectOption[]>(
    () =>
      (assigneesQuery.data?.items || []).map((a) => ({
        value: a.username,
        label: `${a.username} · ${a.case_count} Cases`,
      })),
    [assigneesQuery.data],
  );

  const currentEff = activeTp ? effectiveFor(activeTp.id) : { routing: "", laneChange: "" };
  const cameraUrl = normalizeAssetUrl(activeTp?.camera?.url);
  const bevUrl = normalizeAssetUrl(activeTp?.bev?.url);

  const saveLabel =
    saveState === "saving"
      ? bilingual(lang, "保存中…", "Saving…")
      : saveState === "dirty"
        ? bilingual(lang, "等待自动保存…", "Pending auto-save…")
        : saveState === "saved"
          ? bilingual(lang, "已自动保存", "Auto-saved")
          : saveState === "error"
            ? bilingual(lang, "保存失败", "Save failed")
            : bilingual(lang, "尚未标注", "Not labeled");

  return (
    <section
      id="intentLabelingPage"
      className="app-page ra-react-page"
      data-page="intent"
      data-react-island="intent"
    >
      {/* Controls bar */}
      <div className="panel-card">
        <div className="ra-filter-grid">
          <div className="ra-field-stack">
            <span>{bilingual(lang, "实验分配", "Experiment")}</span>
            <UiSelect
              id="raIntentExpSelect"
              value={experimentId}
              options={experimentOptions}
              ariaLabel={bilingual(lang, "选择意图实验", "Select intent experiment")}
              onChange={(v) => {
                setExperimentId(v);
                setTargetCase("");
              }}
            />
          </div>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "标注人筛选", "Assignees")}</span>
            <MultiSelect
              id="raIntentAssigneePicker"
              options={assigneeOptions}
              values={assignees}
              lang={lang}
              showOnlyThis
              placeholder={bilingual(lang, "全部标注人", "All assignees")}
              ariaLabel={bilingual(lang, "按标注人筛选", "Filter by assignee")}
              onChange={(vals) => {
                setAssignees(vals);
                setTargetCase("");
              }}
            />
          </div>
          <form
            className="ra-inline-actions"
            style={{ alignItems: "flex-end" }}
            onSubmit={(e) => {
              e.preventDefault();
              setTargetCase(caseInput.trim());
            }}
          >
            <label className="ra-field-stack">
              <span>Case / Issue ID</span>
              <input
                type="text"
                value={caseInput}
                placeholder="cn28896325"
                onChange={(e) => setCaseInput(e.target.value)}
              />
            </label>
            <button type="submit" className="button button-quiet">
              {bilingual(lang, "打开", "Open")}
            </button>
          </form>
          <div className="ra-inline-actions" style={{ alignItems: "flex-end", justifyContent: "flex-end" }}>
            <button
              type="button"
              className="button button-quiet"
              disabled={!queueItem?.previous?.case_id}
              onClick={() => queueItem?.previous?.case_id && setTargetCase(queueItem.previous.case_id)}
            >
              ↑ {bilingual(lang, "上一个", "Prev")}
            </button>
            <span className="muted">
              {queueItem?.ordinal ?? "—"} / {queueQuery.data?.scope_total ?? "—"}
            </span>
            <button
              type="button"
              className="button button-quiet"
              disabled={!queueItem?.next?.case_id}
              onClick={() => queueItem?.next?.case_id && setTargetCase(queueItem.next.case_id)}
            >
              {bilingual(lang, "下一个", "Next")} ↓
            </button>
            <button
              type="button"
              className="button button-quiet"
              disabled={!undoStack.length}
              onClick={handleUndo}
            >
              {bilingual(lang, "撤销", "Undo")}
            </button>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => setDiscussionOpen(true)}
            >
              {bilingual(lang, "讨论", "Discuss")} ({caseData?.collaboration?.comments?.length ?? 0})
            </button>
            <span className="muted" data-status={saveState}>
              {saveLabel}
            </span>
          </div>
        </div>
      </div>

      {/* Media & Labeling Grid */}
      {caseQuery.isLoading ? (
        <div className="panel-card">
          <div className="no-asset">{bilingual(lang, "正在加载 Case 媒体…", "Loading case media…")}</div>
        </div>
      ) : !caseData ? (
        <div className="panel-card">
          <div className="no-asset">{bilingual(lang, "当前筛选下没有可标注 Case。", "No case available.")}</div>
        </div>
      ) : (
        <>
          <div className="panel-card intent-hero-grid">
            <div className="intent-media-pane">
              <div className="ra-page-header-row">
                <strong>Camera · {activeTp ? fmtOffset(activeTp.offset_ms) : "—"}</strong>
                {cameraUrl && (
                  <button
                    type="button"
                    className="button button-quiet"
                    onClick={() => setLightboxUrl(cameraUrl)}
                  >
                    {bilingual(lang, "放大", "Zoom")}
                  </button>
                )}
              </div>
              <div className="intent-media-stage">
                {cameraUrl ? (
                  <img src={cameraUrl} alt="Camera frame" />
                ) : (
                  <div className="no-asset">{bilingual(lang, "无 Camera 图片", "No Camera frame")}</div>
                )}
              </div>
            </div>

            <div className="intent-media-pane">
              <div className="ra-page-header-row">
                <strong>BEV · {activeTp ? fmtOffset(activeTp.offset_ms) : "—"}</strong>
                {bevUrl && (
                  <button
                    type="button"
                    className="button button-quiet"
                    onClick={() => setLightboxUrl(bevUrl)}
                  >
                    {bilingual(lang, "放大", "Zoom")}
                  </button>
                )}
              </div>
              <div className="intent-media-stage">
                {bevUrl ? (
                  <img src={bevUrl} alt="BEV frame" />
                ) : (
                  <div className="no-asset">{bilingual(lang, "无 BEV 图片", "No BEV frame")}</div>
                )}
              </div>
            </div>
          </div>

          {/* Timeline */}
          <div className="panel-card">
            <div className="ra-page-header-row">
              <strong>
                {bilingual(lang, "时间轴", "Timeline")} ({caseData.timepoints.length})
              </strong>
              <div className="ra-inline-actions">
                <button
                  type="button"
                  className="button button-quiet"
                  onClick={() => moveFrame(-1)}
                >
                  ← {bilingual(lang, "上一帧", "Prev frame")}
                </button>
                <button
                  type="button"
                  className="button button-quiet"
                  onClick={() => moveFrame(1)}
                >
                  {bilingual(lang, "下一帧", "Next frame")} →
                </button>
              </div>
            </div>
            <div className="intent-timeline" style={{ marginTop: 10 }}>
              {caseData.timepoints.map((tp) => {
                const eff = effectiveFor(tp.id);
                const isAct = tp.id === activeTp?.id;
                return (
                  <button
                    key={tp.id}
                    type="button"
                    className={`intent-timepoint${isAct ? " active selected" : ""}`}
                    onClick={() => setActiveTpId(tp.id)}
                  >
                    <strong>{fmtOffset(tp.offset_ms)}</strong>
                    <small className="muted">
                      {eff.routing ? eff.routing : "—"} / {eff.laneChange ? eff.laneChange : "—"}
                    </small>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Labeling Controls */}
          <div className="panel-card ra-two-col-grid">
            <div>
              <h3>{bilingual(lang, "整条 Case 批量预填 (Shift + 1–8)", "Case Batch Prefill (Shift + 1–8)")}</h3>
              {routingEnabled && (
                <div className="ra-inline-actions" style={{ marginTop: 8, flexWrap: "wrap" }}>
                  {ROUTING_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      disabled={!canAnnotate}
                      className={`button ${aggregate.routing === opt.value ? "button-primary" : "button-quiet"}`}
                      onClick={() => applyAggregate("routing", opt.value)}
                    >
                      {bilingual(lang, opt.zh, opt.en)}
                    </button>
                  ))}
                </div>
              )}
              {laneEnabled && (
                <div className="ra-inline-actions" style={{ marginTop: 8, flexWrap: "wrap" }}>
                  {LANE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      disabled={!canAnnotate}
                      className={`button ${aggregate.laneChange === opt.value ? "button-primary" : "button-quiet"}`}
                      onClick={() => applyAggregate("laneChange", opt.value)}
                    >
                      {bilingual(lang, opt.zh, opt.en)}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div>
              <h3>{bilingual(lang, "当前帧单独微调 (1–8)", "Current Frame Override (1–8)")}</h3>
              {routingEnabled && (
                <div className="ra-inline-actions" style={{ marginTop: 8, flexWrap: "wrap" }}>
                  {ROUTING_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      disabled={!canAnnotate}
                      className={`button ${currentEff.routing === opt.value ? "button-primary" : "button-quiet"}`}
                      onClick={() => applyFrameLabel("routing", opt.value)}
                    >
                      <kbd>{opt.key}</kbd> {bilingual(lang, opt.zh, opt.en)}
                    </button>
                  ))}
                </div>
              )}
              {laneEnabled && (
                <div className="ra-inline-actions" style={{ marginTop: 8, flexWrap: "wrap" }}>
                  {LANE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      disabled={!canAnnotate}
                      className={`button ${currentEff.laneChange === opt.value ? "button-primary" : "button-quiet"}`}
                      onClick={() => applyFrameLabel("laneChange", opt.value)}
                    >
                      <kbd>{opt.key}</kbd> {bilingual(lang, opt.zh, opt.en)}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Collaboration panel */}
          <div className="panel-card">
            <div className="ra-page-header-row">
              <h3>{bilingual(lang, "协作标注人", "Contributors")}</h3>
              {isAdmin && caseData.collaboration?.blind_active && (
                <button
                  type="button"
                  className="button button-quiet"
                  onClick={() => setRevealAnswers((v) => !v)}
                >
                  {revealAnswers
                    ? bilingual(lang, "恢复盲态", "Restore blind")
                    : bilingual(lang, "管理员解盲", "Admin reveal")}
                </button>
              )}
            </div>
            <div className="ra-inline-actions" style={{ marginTop: 8, flexWrap: "wrap" }}>
              {(caseData.collaboration?.contributors || []).map((c) => (
                <span key={c.username} className="status-chip">
                  {c.username}
                  {c.is_current ? bilingual(lang, "（我）", " (Me)") : ""} ·{" "}
                  {c.completed
                    ? bilingual(lang, "完整", "Complete")
                    : c.labeled
                      ? bilingual(lang, "部分", "Partial")
                      : bilingual(lang, "待标注", "Pending")}
                </span>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Intent Discussion Modal */}
      {activeDatasetId && activeCaseId && (
        <IssueDiscussion
          open={discussionOpen}
          kind="intent"
          issueId={caseData?.issue_id || activeCaseId}
          intentDatasetId={activeDatasetId}
          intentCaseId={activeCaseId}
          lang={lang}
          username={session.username}
          canWrite={canAnnotate}
          isAdmin={Boolean(session.is_admin)}
          onClose={() => setDiscussionOpen(false)}
          onCountChange={() => void queryClient.invalidateQueries({ queryKey: ["intent-case"] })}
        />
      )}

      {/* Lightbox Modal */}
      <ModalDialog
        open={Boolean(lightboxUrl)}
        title={bilingual(lang, "媒体高清预览", "Media Preview")}
        lang={lang}
        onClose={() => setLightboxUrl(null)}
      >
        {lightboxUrl && (
          <img
            src={lightboxUrl}
            alt="Zoomed preview"
            style={{ width: "100%", maxHeight: "75dvh", objectFit: "contain" }}
          />
        )}
      </ModalDialog>
    </section>
  );
};
