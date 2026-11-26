import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError, apiRequest } from "../api/client";
import {
  bilingual,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import {
  clearIntentDraft,
  intentDraftSignature,
  readIntentDraft,
  writeIntentDraft,
} from "../features/intent/intentDraftStorage";

interface IntentDatasetItem {
  id: string;
  display_name: string;
  available: boolean;
  case_count?: number;
}

interface IntentAssigneeItem {
  username: string;
  case_count: number;
}

interface IntentExperimentItem {
  id: string;
  dataset_id: string;
  name: string;
  label_scope?: string;
  case_count?: number;
}

interface IntentMediaDescriptor {
  url?: string;
  thumbnail_url?: string;
  offset_ms?: number;
  width?: number;
  height?: number;
}

interface IntentTimepoint {
  id: string;
  offset_ms: number;
  camera_delta_ms?: number | null;
  camera?: IntentMediaDescriptor | null;
  bev?: IntentMediaDescriptor | null;
}

interface IntentOverride {
  timepoint_id: string;
  offset_ms: number;
  routing_intent?: string;
  lane_change_intent?: string;
}

interface IntentContributor {
  username: string;
  is_current?: boolean;
  revealed?: boolean;
  labeled?: boolean;
  completed?: boolean;
  completion_reason?: string;
  routing_default?: string;
  lane_change_default?: string;
  overrides?: IntentOverride[];
  updated_at?: string;
}

interface IntentCaseDetailResponse {
  case_id: string;
  issue_id: string;
  dataset_id?: string;
  status?: string;
  ordinal?: number;
  case_count?: number;
  previous_case?: { case_id: string; dataset_id: string } | null;
  next_case?: { case_id: string; dataset_id: string } | null;
  experiment?: { id?: string; label_scope?: string } | null;
  timepoints: IntentTimepoint[];
  labels?: {
    revision_id?: number | null;
    routing_default?: string;
    lane_change_default?: string;
    overrides?: IntentOverride[];
    created_at?: string;
  } | null;
  collaboration?: {
    blind_active?: boolean;
    answers_revealed?: boolean;
    contributors?: IntentContributor[];
    comments?: Array<{ id: number; author: string; body?: string }>;
  };
}

interface IntentQueueResponse {
  scope_total?: number;
  items?: Array<{
    case_id: string;
    issue_id: string;
    dataset_id: string;
    ordinal?: number;
    previous?: { case_id: string; dataset_id: string } | null;
    next?: { case_id: string; dataset_id: string } | null;
  }>;
}

interface LegacyWindow {
  syncIntentTopbarDatasets?: (
    items: IntentDatasetItem[],
    selectedIds: string[],
    page: string,
  ) => void;
  renderIntentTopbarDatasetPicker?: (selectedIds?: string[] | null) => void;
  showToast?: (msg: string, isError?: boolean) => void;
  acknowledgeLocalChange?: (payload: unknown) => void;
  openMedia?: (kind: string, index: number, opts?: Record<string, unknown>) => void;
  openAnalysisDiscussion?: (issueId: string, opts?: Record<string, unknown>) => Promise<void>;
}

function getLegacyWindow(): LegacyWindow {
  return window as unknown as LegacyWindow;
}

const ROUTING_OPTIONS: Array<{ value: string; zh: string; en: string; key: string; kbd: string }> = [
  { value: "left_turn", zh: "左转", en: "Left", key: "Digit1", kbd: "1" },
  { value: "right_turn", zh: "右转", en: "Right", key: "Digit2", kbd: "2" },
  { value: "straight", zh: "直行", en: "Straight", key: "Digit3", kbd: "3" },
  { value: "u_turn", zh: "掉头", en: "U-turn", key: "Digit4", kbd: "4" },
  { value: "parking", zh: "泊车", en: "Parking", key: "Digit5", kbd: "5" },
];

const LANE_OPTIONS: Array<{ value: string; zh: string; en: string; key: string; kbd: string }> = [
  { value: "no_lane_change", zh: "非变道", en: "Keep lane", key: "Digit6", kbd: "6" },
  { value: "left_lane_change", zh: "左变道", en: "Left LC", key: "Digit7", kbd: "7" },
  { value: "right_lane_change", zh: "右变道", en: "Right LC", key: "Digit8", kbd: "8" },
];

const DIGIT_MAP: Record<string, ["routing" | "laneChange", string]> = {
  Digit1: ["routing", "left_turn"],
  Digit2: ["routing", "right_turn"],
  Digit3: ["routing", "straight"],
  Digit4: ["routing", "u_turn"],
  Digit5: ["routing", "parking"],
  Digit6: ["laneChange", "no_lane_change"],
  Digit7: ["laneChange", "left_lane_change"],
  Digit8: ["laneChange", "right_lane_change"],
};

function routingLabel(value: string | undefined, lang: UiLanguage): string {
  const found = ROUTING_OPTIONS.find((o) => o.value === value);
  return found ? bilingual(lang, found.zh, found.en) : bilingual(lang, "Routing 待填", "Routing pending");
}

function laneLabel(value: string | undefined, lang: UiLanguage): string {
  if (value === "lane_change") return bilingual(lang, "变道（旧）", "Lane change (legacy)");
  const found = LANE_OPTIONS.find((o) => o.value === value);
  return found ? bilingual(lang, found.zh, found.en) : bilingual(lang, "变道待填", "LC pending");
}

function chipToneClass(value: string | undefined): string {
  const map: Record<string, string> = {
    straight: "is-straight",
    left_turn: "is-left",
    right_turn: "is-right",
    u_turn: "is-uturn",
    parking: "is-parking",
    no_lane_change: "is-no-lane",
    left_lane_change: "is-left-lane",
    right_lane_change: "is-right-lane",
    lane_change: "is-legacy-lane",
  };
  return (value && map[value]) || "";
}

function timeLabel(offsetMs: number): string {
  const v = Number(offsetMs) || 0;
  if (v % 1000 === 0) return `${v >= 0 ? "+" : ""}${v / 1000}s`;
  return `${v >= 0 ? "+" : ""}${v}ms`;
}

function scopeLabel(scope: string | undefined, lang: UiLanguage): string {
  if (scope === "routing") return bilingual(lang, "仅 Routing 意图", "Routing only");
  if (scope === "lane_change") return bilingual(lang, "仅变道意图", "Lane-change only");
  return bilingual(lang, "Routing + 变道意图", "Routing + lane-change");
}

function setTopbarSaveState(text: string, kind: "" | "saved" | "dirty" | "saving" | "error" = "") {
  const el = document.getElementById("intentSaveState");
  if (!el) return;
  el.textContent = text;
  el.dataset.status = kind;
}

function parseIntentRoute() {
  const params = new URLSearchParams(window.location.search);
  const datasets = params
    .getAll("dataset")
    .flatMap((v) => v.split(","))
    .map((s) => s.trim())
    .filter(Boolean);
  const assignees = params
    .getAll("assignee")
    .flatMap((v) => v.split(","))
    .map((s) => s.trim())
    .filter(Boolean);
  const offsetRaw = params.get("t");
  const offsetMs = offsetRaw !== null && offsetRaw !== "" && Number.isFinite(Number(offsetRaw)) ? Number(offsetRaw) : null;
  return {
    datasetIds: [...new Set(datasets)],
    caseId: (params.get("case") || "").trim(),
    experimentId: (params.get("experiment") || "").trim(),
    assignees: [...new Set(assignees)],
    offsetMs,
    openComments: params.get("comments") === "1",
    focusCommentId: Number(params.get("comment") || 0) || 0,
  };
}

interface EditSnapshot {
  aggregate: { routing: string; laneChange: string };
  overrides: Record<string, IntentOverride>;
}

interface ZoomTransform {
  scale: number;
  x: number;
  y: number;
}

export interface IntentLabelingPageProps {
  active: boolean;
  lang: UiLanguage;
  username: string;
  isAdmin: boolean;
  canAnnotateIntent: boolean;
}

export const IntentLabelingPage: React.FC<IntentLabelingPageProps> = ({
  active,
  lang,
  username,
  isAdmin,
  canAnnotateIntent,
}) => {
  const initialRoute = useMemo(() => parseIntentRoute(), []);

  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>(initialRoute.datasetIds);
  const [activeDatasetId, setActiveDatasetId] = useState<string>(initialRoute.datasetIds[0] || "");
  const [selectedExperimentId, setSelectedExperimentId] = useState<string>(initialRoute.experimentId);
  const [selectedAssignees, setSelectedAssignees] = useState<string[]>(initialRoute.assignees);
  const [requestedCaseId, setRequestedCaseId] = useState<string>(initialRoute.caseId);
  const [requestedOffsetMs, setRequestedOffsetMs] = useState<number | null>(initialRoute.offsetMs);

  const [caseInput, setCaseInput] = useState("");
  const [caseOrdinalInput, setCaseOrdinalInput] = useState("");
  const [frameOrdinalInput, setFrameOrdinalInput] = useState("");

  const [caseData, setCaseData] = useState<IntentCaseDetailResponse | null>(null);
  const [loadingCase, setLoadingCase] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [activeTimepointId, setActiveTimepointId] = useState("");
  const [selectedTimepointIds, setSelectedTimepointIds] = useState<string[]>([]);
  const [selectionAnchorId, setSelectionAnchorId] = useState("");

  // Editable label state
  const [revisionId, setRevisionId] = useState<number | null>(null);
  const [aggregate, setAggregate] = useState<{ routing: string; laneChange: string }>({
    routing: "",
    laneChange: "",
  });
  const [overrides, setOverrides] = useState<Record<string, IntentOverride>>({});
  const [adminReveal, setAdminReveal] = useState(false);
  const [openMenuUser, setOpenMenuUser] = useState<string | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [draftNotice, setDraftNotice] = useState<{
    kind: "restored" | "save_failed";
    message: string;
    remoteChanged: boolean;
  } | null>(null);
  const serverLabelsRef = useRef<{
    revision_id: number | null;
    routing_default: string;
    lane_change_default: string;
    overrides: Record<string, IntentOverride>;
  } | null>(null);

  // Media zoom/pan per panel
  const [cameraZoom, setCameraZoom] = useState<ZoomTransform>({ scale: 1, x: 0, y: 0 });
  const [bevZoom, setBevZoom] = useState<ZoomTransform>({ scale: 1, x: 0, y: 0 });
  const cameraStageRef = useRef<HTMLDivElement | null>(null);
  const bevStageRef = useRef<HTMLDivElement | null>(null);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{
    kind: "camera" | "bev";
    pointerId: number;
    startClientX: number;
    startClientY: number;
    startX: number;
    startY: number;
  } | null>(null);

  // Auto-save & undo refs
  const undoStackRef = useRef<EditSnapshot[]>([]);
  const dirtyRef = useRef(false);
  const draftBaseRevisionRef = useRef<number | null>(null);
  const conflictBlockedRef = useRef(false);
  const editVersionRef = useRef(0);
  const saveTimerRef = useRef<number | null>(null);
  const savePromiseRef = useRef<Promise<void> | null>(null);
  const autoAdvanceRef = useRef<{ enabled: boolean; tpId: string }>({ enabled: false, tpId: "" });
  const requestSeqRef = useRef(0);
  const stateRef = useRef({
    aggregate,
    overrides,
    revisionId,
    activeDatasetId,
    caseData,
    activeTimepointId,
    selectedTimepointIds,
    selectionAnchorId,
    username,
    canAnnotateIntent,
  });
  stateRef.current = {
    aggregate,
    overrides,
    revisionId,
    activeDatasetId,
    caseData,
    activeTimepointId,
    selectedTimepointIds,
    selectionAnchorId,
    username,
    canAnnotateIntent,
  };

  // Datasets catalog
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
    const valid = selectedDatasetIds.filter((id) => availableDatasets.some((d) => d.id === id));
    if (valid.length) return valid;
    return availableDatasets[0] ? [availableDatasets[0].id] : [];
  }, [selectedDatasetIds, availableDatasets]);

  const effectiveDatasetKey = effectiveDatasetIds.join(",");

  // Sync topbar dataset picker
  useEffect(() => {
    if (!active || !availableDatasets.length) return;
    const legacy = getLegacyWindow();
    const allItems = datasetsQuery.data?.items || [];
    if (legacy.syncIntentTopbarDatasets) {
      legacy.syncIntentTopbarDatasets(allItems, effectiveDatasetIds, "intent");
    } else {
      legacy.renderIntentTopbarDatasetPicker?.(effectiveDatasetIds);
    }
  }, [active, availableDatasets, datasetsQuery.data, effectiveDatasetIds]);

  // Listen to topbar dataset changes
  useEffect(() => {
    if (!active) return;
    const onDatasetChange = (ev: Event) => {
      const detail = (ev as CustomEvent<{ page?: string; datasetIds?: string[] }>).detail;
      if (detail?.page === "intent" && Array.isArray(detail.datasetIds) && detail.datasetIds.length) {
        setSelectedDatasetIds(detail.datasetIds);
        setActiveDatasetId(detail.datasetIds[0] || "");
        setSelectedExperimentId("");
        setSelectedAssignees([]);
        setRequestedCaseId("");
        setRequestedOffsetMs(null);
      }
    };
    window.addEventListener("ra:intent-datasets-change", onDatasetChange);
    return () => window.removeEventListener("ra:intent-datasets-change", onDatasetChange);
  }, [active]);

  // Assignees & experiments catalog
  const assigneesQuery = useQuery<{
    items?: IntentAssigneeItem[];
    experiments?: IntentExperimentItem[];
  }>({
    queryKey: ["intent-assignees", effectiveDatasetKey, selectedExperimentId],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams();
      effectiveDatasetIds.forEach((id) => params.append("dataset_id", id));
      if (selectedExperimentId) params.set("experiment_id", selectedExperimentId);
      return apiRequest(`/api/intent-assignees?${params.toString()}`, { signal });
    },
    enabled: active && effectiveDatasetIds.length > 0,
    staleTime: 15_000,
  });

  const assigneesList = assigneesQuery.data?.items || [];
  const experimentsList = assigneesQuery.data?.experiments || [];

  const validAssignees = useMemo(() => {
    const avail = new Set(assigneesList.map((a) => a.username));
    return selectedAssignees.filter((u) => avail.has(u));
  }, [assigneesList, selectedAssignees]);

  const validExperimentId = useMemo(() => {
    if (!selectedExperimentId) return "";
    return experimentsList.some((e) => e.id === selectedExperimentId) ? selectedExperimentId : "";
  }, [experimentsList, selectedExperimentId]);

  const labelScope = caseData?.experiment?.label_scope || "all";
  const axisEnabled = useCallback(
    (axis: "routing" | "laneChange" | "lane_change") => {
      const norm = axis === "laneChange" ? "lane_change" : axis;
      return labelScope === "all" || labelScope === norm;
    },
    [labelScope],
  );

  const labelsComplete = useCallback(
    (routing: string, laneChange: string) =>
      (!axisEnabled("routing") || Boolean(routing)) &&
      (!axisEnabled("laneChange") || Boolean(laneChange)),
    [axisEnabled],
  );

  // Sync pending intent edits to browser localStorage so reload/502/503 never loses work.
  useEffect(() => {
    if (!dirtyRef.current || !activeDatasetId || !caseData?.case_id) return;
    writeIntentDraft({
      datasetId: activeDatasetId,
      caseId: caseData.case_id,
      author: username || "",
      routingDefault: aggregate.routing,
      laneChangeDefault: aggregate.laneChange,
      overrides,
      expectedRevisionId: conflictBlockedRef.current
        ? draftBaseRevisionRef.current
        : (draftBaseRevisionRef.current ?? revisionId),
    });
  }, [aggregate, overrides, activeDatasetId, caseData?.case_id, revisionId, username]);

  // Flush auto-save
  const flushSave = useCallback(
    async (options?: { allowConflictOverwrite?: boolean }): Promise<void> => {
      const explicitOverwrite = Boolean(options?.allowConflictOverwrite);
      if (conflictBlockedRef.current && !explicitOverwrite) {
        return;
      }
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
      if (savePromiseRef.current) {
        await savePromiseRef.current;
        if (dirtyRef.current && !conflictBlockedRef.current) return flushSave();
        return;
      }
      const cur = stateRef.current;
      if ((!dirtyRef.current && !explicitOverwrite) || !cur.caseData?.case_id || !cur.activeDatasetId) {
        return;
      }
      const savedEditVersion = editVersionRef.current;
      const targetExpectedRevisionId = explicitOverwrite
        ? (serverLabelsRef.current?.revision_id ?? cur.revisionId)
        : draftBaseRevisionRef.current;
      if (explicitOverwrite) {
        // User explicitly confirmed overwriting against targetExpectedRevisionId.
        // Commit this base revision and lift conflictBlockedRef BEFORE issuing PUT
        // so a transient 503/502 retry replays the exact same overwrite key & target.
        draftBaseRevisionRef.current = targetExpectedRevisionId;
        conflictBlockedRef.current = false;
      }
      const persistedDraft = writeIntentDraft({
        datasetId: cur.activeDatasetId,
        caseId: cur.caseData.case_id,
        author: cur.username || "",
        routingDefault: cur.aggregate.routing,
        laneChangeDefault: cur.aggregate.laneChange,
        overrides: cur.overrides,
        expectedRevisionId: targetExpectedRevisionId,
        forceNewIdempotencyKey: explicitOverwrite,
      });
      const idemKey = persistedDraft?.idempotency_key || "";
      dirtyRef.current = false;
      let saveFailed = false;
      setTopbarSaveState(bilingual(lang, "正在保存…", "Saving…"), "saving");
      const promise = apiRequest<{
        labels?: {
          revision_id?: number | null;
          routing_default?: string;
          lane_change_default?: string;
          overrides?: IntentOverride[];
          created_at?: string;
        };
      }>(
        `/api/intent-datasets/${encodeURIComponent(cur.activeDatasetId)}/cases/${encodeURIComponent(
          cur.caseData.case_id,
        )}/labels`,
        {
          method: "PUT",
          headers: idemKey ? { "Idempotency-Key": idemKey } : undefined,
          body: {
            expected_revision_id: targetExpectedRevisionId,
            routing_default: cur.aggregate.routing,
            lane_change_default: cur.aggregate.laneChange,
            overrides: Object.values(cur.overrides).map((item) => ({
              timepoint_id: item.timepoint_id,
              offset_ms: item.offset_ms,
              routing_intent: item.routing_intent || "",
              lane_change_intent: item.lane_change_intent || "",
            })),
            author: cur.username || "",
          },
        },
      )
        .then((payload) => {
          getLegacyWindow().acknowledgeLocalChange?.(payload);
          const nextRev = payload.labels?.revision_id ?? null;
          conflictBlockedRef.current = false;
          draftBaseRevisionRef.current = nextRev;
          setRevisionId(nextRev);
          const nextOverrides: Record<string, IntentOverride> = {};
          for (const ov of payload.labels?.overrides || []) {
            nextOverrides[ov.timepoint_id] = { ...ov };
          }
          serverLabelsRef.current = {
            revision_id: nextRev,
            routing_default: payload.labels?.routing_default || "",
            lane_change_default: payload.labels?.lane_change_default || "",
            overrides: nextOverrides,
          };
          if (editVersionRef.current === savedEditVersion) {
            clearIntentDraft(cur.activeDatasetId, cur.caseData!.case_id, cur.username || "");
            setDraftNotice(null);
            setOverrides(nextOverrides);
            setTopbarSaveState(bilingual(lang, "已自动保存", "Auto-saved"), "saved");
            // Update contributor card locally
            const lowerUser = String(cur.username || "").toLowerCase();
            setCaseData((prev) => {
              if (!prev) return prev;
              const prevCollab = prev.collaboration || { contributors: [], comments: [] };
              const contributors = [...(prevCollab.contributors || [])];
              const idx = contributors.findIndex((c) => c.is_current || c.username === lowerUser);
              const updated: IntentContributor = {
                ...(idx >= 0 ? contributors[idx] : {}),
                username: lowerUser,
                is_current: true,
                revealed: true,
                labeled: true,
                completed: labelsComplete(
                  payload.labels?.routing_default || "",
                  payload.labels?.lane_change_default || "",
                ),
                routing_default: payload.labels?.routing_default || "",
                lane_change_default: payload.labels?.lane_change_default || "",
                overrides: payload.labels?.overrides || [],
                updated_at: payload.labels?.created_at || "",
              };
              if (idx >= 0) contributors[idx] = updated;
              else contributors.push(updated);
              return { ...prev, collaboration: { ...prevCollab, contributors } };
            });
            if (
              autoAdvanceRef.current.enabled &&
              autoAdvanceRef.current.tpId === stateRef.current.activeTimepointId
            ) {
              autoAdvanceRef.current = { enabled: false, tpId: "" };
              const tps = stateRef.current.caseData?.timepoints || [];
              const curIdx = tps.findIndex((t) => t.id === stateRef.current.activeTimepointId);
              if (curIdx >= 0 && curIdx < tps.length - 1) {
                const nextTp = tps[curIdx + 1];
                setActiveTimepointId(nextTp.id);
                setSelectedTimepointIds([nextTp.id]);
                setSelectionAnchorId(nextTp.id);
              }
            }
          } else {
            dirtyRef.current = true;
            setTopbarSaveState(bilingual(lang, "等待自动保存…", "Pending auto-save…"), "dirty");
          }
        })
        .catch((err) => {
          saveFailed = true;
          const message =
            (err as Error)?.message ||
            bilingual(lang, "保存失败，本地草稿已保留。", "Save failed. Local draft preserved.");
          const isConflict = err instanceof ApiError && err.status === 409;
          if (isConflict) {
            conflictBlockedRef.current = true;
            dirtyRef.current = false;
          } else {
            dirtyRef.current = true;
          }
          setDraftNotice({
            kind: "save_failed",
            message,
            remoteChanged: isConflict,
          });
          setTopbarSaveState(
            isConflict
              ? bilingual(lang, "远端版本冲突（需确认）", "Server conflict (review required)")
              : bilingual(lang, "保存失败（草稿已保留）", "Save failed (draft kept)"),
            "error",
          );
          getLegacyWindow().showToast?.(message, true);
        })
        .finally(() => {
          savePromiseRef.current = null;
        });
      savePromiseRef.current = promise;
      await promise;
      if (!saveFailed && dirtyRef.current && !conflictBlockedRef.current) return flushSave();
    },
    [lang, labelsComplete],
  );

  const markDirty = useCallback(() => {
    dirtyRef.current = true;
    editVersionRef.current += 1;
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    if (conflictBlockedRef.current) {
      setTopbarSaveState(
        bilingual(lang, "草稿与远端冲突（等待确认）", "Draft conflicts with server (review required)"),
        "error",
      );
      return;
    }
    setTopbarSaveState(bilingual(lang, "等待自动保存…", "Pending auto-save…"), "dirty");
    saveTimerRef.current = window.setTimeout(() => {
      void flushSave();
    }, 600);
  }, [flushSave, lang]);

  // Load case sequence
  const loadCase = useCallback(
    async (opts: {
      datasetIds?: string[];
      datasetId?: string;
      caseId?: string;
      offsetMs?: number | null;
      assignees?: string[];
      experimentId?: string;
      revealAnswers?: boolean;
      historyMode?: "push" | "replace" | "";
    }) => {
      const scopeIds = opts.datasetIds?.length ? opts.datasetIds : effectiveDatasetIds;
      if (!scopeIds.length) return;
      const seq = ++requestSeqRef.current;
      setLoadingCase(true);
      setLoadError("");
      try {
        const expId = opts.experimentId !== undefined ? opts.experimentId : validExperimentId;
        const assignees = opts.assignees !== undefined ? opts.assignees : validAssignees;
        const targetRaw = (opts.caseId ?? requestedCaseId).trim();
        if (targetRaw && !/^cn[0-9]+(?:_[0-9]+)?$/.test(targetRaw)) {
          throw new Error(
            bilingual(
              lang,
              "请输入完整的 Issue ID，例如 cn28896325。",
              "Enter a full Issue ID, e.g. cn28896325.",
            ),
          );
        }
        const assigneeParams = new URLSearchParams();
        assignees.forEach((u) => assigneeParams.append("assignee", u));
        if (expId) assigneeParams.set("experiment_id", expId);

        const queueParams = new URLSearchParams(assigneeParams);
        scopeIds.forEach((id) => queueParams.append("dataset_id", id));
        const shouldResume = Boolean(expId && !targetRaw);
        queueParams.set("status", shouldResume ? "incomplete" : "all");
        if (shouldResume) queueParams.set("resume", "true");
        queueParams.set("page_size", targetRaw ? "200" : "1");
        if (targetRaw) queueParams.set("q", targetRaw);

        let queue = await apiRequest<IntentQueueResponse>(
          `/api/intent-cases?${queueParams.toString()}`,
        );
        if (seq !== requestSeqRef.current) return;
        let completedFallback = false;
        if (shouldResume && !(queue.items || []).length) {
          queueParams.set("status", "all");
          queueParams.delete("resume");
          queue = await apiRequest<IntentQueueResponse>(
            `/api/intent-cases?${queueParams.toString()}`,
          );
          if (seq !== requestSeqRef.current) return;
          completedFallback = Boolean((queue.items || []).length);
        }

        const preferredDs = opts.datasetId || activeDatasetId || scopeIds[0];
        let queueItem: NonNullable<IntentQueueResponse["items"]>[number] | null = null;
        if (/^cn[0-9]+_[0-9]+$/.test(targetRaw)) {
          const exact = (queue.items || []).filter((i) => i.case_id === targetRaw);
          queueItem = exact.find((i) => i.dataset_id === preferredDs) || exact[0] || null;
        } else if (targetRaw) {
          const exact = (queue.items || []).filter((i) => i.issue_id === targetRaw);
          if (exact.length !== 1) {
            throw new Error(
              exact.length
                ? bilingual(
                    lang,
                    "该 Issue 对应多个数据集或 Episode，无法唯一打开。",
                    "This Issue matches multiple datasets or episodes.",
                  )
                : bilingual(lang, "所选数据集中没有这个 Issue。", "This Issue is not in the selected datasets."),
            );
          }
          queueItem = exact[0];
        } else {
          queueItem = queue.items?.[0] || null;
        }

        const resolvedCaseId = queueItem?.case_id || "";
        if (!resolvedCaseId) {
          throw new Error(bilingual(lang, "数据集中没有可标注 Case。", "No labelable Case in dataset."));
        }
        const resolvedDs = queueItem?.dataset_id || preferredDs;

        const detailParams = new URLSearchParams(assigneeParams);
        if (opts.revealAnswers) detailParams.set("reveal_answers", "true");
        const detail = await apiRequest<IntentCaseDetailResponse>(
          `/api/intent-datasets/${encodeURIComponent(resolvedDs)}/cases/${encodeURIComponent(
            resolvedCaseId,
          )}${detailParams.toString() ? `?${detailParams.toString()}` : ""}`,
        );
        if (seq !== requestSeqRef.current) return;

        detail.ordinal = queueItem?.ordinal;
        detail.case_count = queue.scope_total;
        detail.previous_case = queueItem?.previous || null;
        detail.next_case = queueItem?.next || null;

        const serverRevId = detail.labels?.revision_id ?? null;
        const serverRouting = detail.labels?.routing_default || "";
        const serverLaneChange = detail.labels?.lane_change_default || "";
        const nextOv: Record<string, IntentOverride> = {};
        for (const ov of detail.labels?.overrides || []) {
          nextOv[ov.timepoint_id] = { ...ov };
        }
        serverLabelsRef.current = {
          revision_id: serverRevId,
          routing_default: serverRouting,
          lane_change_default: serverLaneChange,
          overrides: nextOv,
        };
        const savedDraft = readIntentDraft(resolvedDs, resolvedCaseId, stateRef.current.username || "");
        const serverSig = intentDraftSignature(serverRouting, serverLaneChange, nextOv);
        const shouldRestoreDraft = Boolean(savedDraft && savedDraft.signature !== serverSig);
        if (savedDraft && !shouldRestoreDraft) {
          clearIntentDraft(resolvedDs, resolvedCaseId, stateRef.current.username || "");
        }

        setActiveDatasetId(resolvedDs);
        setCaseData(detail);
        setCaseInput(detail.issue_id || "");
        setCaseOrdinalInput(detail.ordinal ? String(detail.ordinal) : "");
        setAdminReveal(Boolean(opts.revealAnswers));
        setRevisionId(serverRevId);
        if (shouldRestoreDraft && savedDraft) {
          const remoteChanged = savedDraft.expected_revision_id !== serverRevId;
          draftBaseRevisionRef.current = savedDraft.expected_revision_id;
          conflictBlockedRef.current = remoteChanged;
          setAggregate({
            routing: savedDraft.routing_default || "",
            laneChange: savedDraft.lane_change_default || "",
          });
          setOverrides(savedDraft.overrides || {});
          undoStackRef.current = [];
          // Never auto-submit or rewrite expected_revision_id on a conflicted draft;
          // wait for an explicit user overwrite or discard decision.
          dirtyRef.current = !remoteChanged;
          editVersionRef.current = 1;
          setDraftNotice({
            kind: "restored",
            remoteChanged,
            message: remoteChanged
              ? bilingual(
                  lang,
                  "已恢复本地未保存草稿，但远端标注版本已更新。切换 Case 不会自动覆盖远端；请明确选择覆盖保存或放弃本地草稿。",
                  "Restored an unsaved local draft, but the server revision has changed. Switching cases will not overwrite the server; explicitly overwrite or discard the draft.",
                )
              : bilingual(
                  lang,
                  "已恢复本地未保存的标注草稿，可点击立即保存或放弃草稿。",
                  "Restored an unsaved local labeling draft. Save now or discard it.",
                ),
          });
        } else {
          draftBaseRevisionRef.current = serverRevId;
          conflictBlockedRef.current = false;
          setAggregate({
            routing: serverRouting,
            laneChange: serverLaneChange,
          });
          setOverrides(nextOv);
          undoStackRef.current = [];
          dirtyRef.current = false;
          editVersionRef.current = 0;
          setDraftNotice(null);
        }

        const tps = detail.timepoints || [];
        const targetOffset = opts.offsetMs !== undefined ? opts.offsetMs : requestedOffsetMs;
        const activeTp =
          targetOffset != null
            ? tps.find((t) => t.offset_ms === targetOffset) || tps[0]
            : tps[0];
        const nextTpId = activeTp?.id || "";
        setActiveTimepointId(nextTpId);
        setSelectedTimepointIds(nextTpId ? [nextTpId] : []);
        setSelectionAnchorId(nextTpId);
        setCameraZoom({ scale: 1, x: 0, y: 0 });
        setBevZoom({ scale: 1, x: 0, y: 0 });
        setTopbarSaveState(
          shouldRestoreDraft
            ? bilingual(lang, "已恢复本地草稿", "Local draft restored")
            : serverRevId
              ? bilingual(lang, "已自动保存", "Auto-saved")
              : bilingual(lang, "尚未标注", "Not labeled yet"),
          shouldRestoreDraft ? "dirty" : serverRevId ? "saved" : "",
        );
        if (completedFallback) {
          getLegacyWindow().showToast?.(
            bilingual(
              lang,
              "该实验已全部标注，已打开队列中的第一个 Case。",
              "All Cases in this experiment are labeled; opened the first Case.",
            ),
            false,
          );
        }

        if (opts.historyMode) {
          const rp = new URLSearchParams();
          scopeIds.forEach((id) => rp.append("dataset", id));
          if (detail.case_id) rp.set("case", detail.case_id);
          if (activeTp) rp.set("t", String(activeTp.offset_ms));
          assignees.forEach((u) => rp.append("assignee", u));
          if (expId) rp.set("experiment", expId);
          const url = `${withWorkbenchBase("/intent-labeling")}?${rp.toString()}`;
          const st = { page: "intent", datasetId: resolvedDs, caseId: detail.case_id };
          if (opts.historyMode === "push") window.history.pushState(st, "", url);
          else window.history.replaceState(st, "", url);
        }
      } catch (err) {
        if (seq === requestSeqRef.current) {
          const msg = (err as Error)?.message || "Load failed";
          setLoadError(msg);
          getLegacyWindow().showToast?.(msg, true);
        }
      } finally {
        if (seq === requestSeqRef.current) setLoadingCase(false);
      }
    },
    [
      effectiveDatasetIds,
      validExperimentId,
      validAssignees,
      requestedCaseId,
      requestedOffsetMs,
      activeDatasetId,
      lang,
    ],
  );

  // Trigger case load when datasets/assignees catalog settles
  useEffect(() => {
    if (!active || !effectiveDatasetIds.length || assigneesQuery.isLoading) return;
    void loadCase({ historyMode: "replace" });
  }, [
    active,
    effectiveDatasetKey,
    validExperimentId,
    validAssignees.join(","),
    requestedCaseId,
    assigneesQuery.isLoading,
  ]);

  // Active timepoint & effective labels
  const timepoints = caseData?.timepoints || [];
  const activeTpIndex = useMemo(
    () => timepoints.findIndex((t) => t.id === activeTimepointId),
    [timepoints, activeTimepointId],
  );
  const activeTp = activeTpIndex >= 0 ? timepoints[activeTpIndex] : null;

  useEffect(() => {
    setFrameOrdinalInput(activeTpIndex >= 0 ? String(activeTpIndex + 1) : "");
  }, [activeTpIndex]);

  // Reset zoom when active frame changes
  useEffect(() => {
    setCameraZoom({ scale: 1, x: 0, y: 0 });
    setBevZoom({ scale: 1, x: 0, y: 0 });
  }, [activeTp?.id]);

  // Scroll active timepoint into view
  useEffect(() => {
    if (!activeTpIdOrEmpty(activeTimepointId) || !timelineRef.current) return;
    const el = timelineRef.current.querySelector<HTMLElement>(
      `[data-intent-timepoint="${CSS.escape(activeTimepointId)}"]`,
    );
    el?.scrollIntoView?.({ block: "nearest", inline: "center" });
  }, [activeTimepointId]);

  function activeTpIdOrEmpty(id: string) {
    return id || "";
  }

  const effectiveFor = useCallback(
    (tp: IntentTimepoint | null) => {
      const ov = tp ? overrides[tp.id] : undefined;
      return {
        routing: ov?.routing_intent || aggregate.routing || "",
        laneChange: ov?.lane_change_intent || aggregate.laneChange || "",
      };
    },
    [aggregate, overrides],
  );

  const selectedTimepoints = useMemo(() => {
    const set = new Set(selectedTimepointIds);
    const matched = timepoints.filter((t) => set.has(t.id));
    if (matched.length) return matched;
    return activeTp ? [activeTp] : [];
  }, [timepoints, selectedTimepointIds, activeTp]);

  // Editing actions
  const pushUndo = useCallback(() => {
    const cur = stateRef.current;
    const snap: EditSnapshot = {
      aggregate: { ...cur.aggregate },
      overrides: Object.fromEntries(
        Object.entries(cur.overrides).map(([k, v]) => [k, { ...v }]),
      ),
    };
    undoStackRef.current.push(snap);
    if (undoStackRef.current.length > 100) undoStackRef.current.shift();
  }, []);

  const setAggregateAxis = useCallback(
    (axis: "routing" | "laneChange", value: string) => {
      if (!canAnnotateIntent || !axisEnabled(axis)) return;
      const key = axis === "routing" ? "routing_intent" : "lane_change_intent";
      pushUndo();
      setAggregate((prev) =>
        axis === "routing" ? { ...prev, routing: value } : { ...prev, laneChange: value },
      );
      setOverrides((prev) => {
        const next: Record<string, IntentOverride> = {};
        for (const [tpId, ov] of Object.entries(prev)) {
          const copy = { ...ov };
          if (copy[key] === value) delete copy[key];
          if (copy.routing_intent || copy.lane_change_intent) next[tpId] = copy;
        }
        return next;
      });
      markDirty();
    },
    [canAnnotateIntent, axisEnabled, pushUndo, markDirty],
  );

  const setFrameAxis = useCallback(
    (axis: "routing" | "laneChange", value: string) => {
      if (!canAnnotateIntent || !axisEnabled(axis) || !selectedTimepoints.length) return;
      const key = axis === "routing" ? "routing_intent" : "lane_change_intent";
      const aggVal = axis === "routing" ? aggregate.routing : aggregate.laneChange;
      pushUndo();
      const nextOv: Record<string, IntentOverride> = { ...overrides };
      for (const tp of selectedTimepoints) {
        const copy: IntentOverride = {
          ...(nextOv[tp.id] || { timepoint_id: tp.id, offset_ms: tp.offset_ms }),
          timepoint_id: tp.id,
          offset_ms: tp.offset_ms,
        };
        if (value === aggVal) delete copy[key];
        else copy[key] = value;
        if (!copy.routing_intent && !copy.lane_change_intent) delete nextOv[tp.id];
        else nextOv[tp.id] = copy;
      }
      setOverrides(nextOv);
      if (selectedTimepoints.length === 1 && activeTp) {
        const ov = nextOv[activeTp.id];
        const effR = ov?.routing_intent || aggregate.routing || "";
        const effL = ov?.lane_change_intent || aggregate.laneChange || "";
        if (labelsComplete(effR, effL)) {
          autoAdvanceRef.current = { enabled: true, tpId: activeTp.id };
        }
      }
      markDirty();
    },
    [
      canAnnotateIntent,
      axisEnabled,
      selectedTimepoints,
      aggregate,
      overrides,
      activeTp,
      labelsComplete,
      pushUndo,
      markDirty,
    ],
  );

  const restoreBatchPrefill = useCallback(() => {
    if (!canAnnotateIntent || !selectedTimepoints.length) return;
    const changed = selectedTimepoints.some((tp) => {
      const ov = overrides[tp.id];
      return Boolean(
        (axisEnabled("routing") && ov?.routing_intent) ||
          (axisEnabled("laneChange") && ov?.lane_change_intent),
      );
    });
    if (!changed) return;
    pushUndo();
    setOverrides((prev) => {
      const next = { ...prev };
      for (const tp of selectedTimepoints) {
        const ov = next[tp.id];
        if (!ov) continue;
        const copy = { ...ov };
        if (axisEnabled("routing")) delete copy.routing_intent;
        if (axisEnabled("laneChange")) delete copy.lane_change_intent;
        if (!copy.routing_intent && !copy.lane_change_intent) delete next[tp.id];
        else next[tp.id] = copy;
      }
      return next;
    });
    markDirty();
  }, [canAnnotateIntent, selectedTimepoints, overrides, axisEnabled, pushUndo, markDirty]);

  const handleUndo = useCallback(() => {
    const prev = undoStackRef.current.pop();
    if (!prev) {
      getLegacyWindow().showToast?.(
        bilingual(lang, "当前 Case 没有可撤销的标注操作。", "Nothing to undo for this Case."),
        false,
      );
      return;
    }
    setAggregate(prev.aggregate);
    setOverrides(prev.overrides);
    markDirty();
    getLegacyWindow().showToast?.(
      bilingual(lang, "已撤销上一次标注操作，正在自动保存。", "Undid last edit; auto-saving."),
      false,
    );
  }, [lang, markDirty]);

  const selectTimepoint = useCallback(
    (tpId: string, extend = false) => {
      const idx = timepoints.findIndex((t) => t.id === tpId);
      if (idx < 0) return;
      if (extend) {
        const anchor = selectionAnchorId || activeTimepointId || tpId;
        const aIdx = timepoints.findIndex((t) => t.id === anchor);
        const start = Math.min(aIdx < 0 ? idx : aIdx, idx);
        const end = Math.max(aIdx < 0 ? idx : aIdx, idx);
        setSelectionAnchorId(anchor);
        setSelectedTimepointIds(timepoints.slice(start, end + 1).map((t) => t.id));
      } else {
        setSelectionAnchorId(tpId);
        setSelectedTimepointIds([tpId]);
      }
      if (activeTimepointId !== tpId) {
        autoAdvanceRef.current = { enabled: false, tpId: "" };
      }
      setActiveTimepointId(tpId);
    },
    [timepoints, selectionAnchorId, activeTimepointId],
  );

  const moveFrame = useCallback(
    (delta: number, opts?: { extend?: boolean; toBoundary?: boolean }) => {
      if (!timepoints.length || activeTpIndex < 0) return;
      const targetIdx = opts?.toBoundary
        ? delta < 0
          ? 0
          : timepoints.length - 1
        : Math.max(0, Math.min(timepoints.length - 1, activeTpIndex + delta));
      selectTimepoint(timepoints[targetIdx].id, Boolean(opts?.extend));
    },
    [timepoints, activeTpIndex, selectTimepoint],
  );

  const navigateCase = useCallback(
    async (direction: -1 | 1) => {
      await flushSave();
      const target = direction < 0 ? caseData?.previous_case : caseData?.next_case;
      if (!target?.case_id) return;
      setRequestedCaseId(target.case_id);
      setRequestedOffsetMs(null);
      await loadCase({
        datasetId: target.dataset_id,
        caseId: target.case_id,
        offsetMs: null,
        historyMode: "push",
      });
    },
    [flushSave, caseData, loadCase],
  );

  const jumpToCaseOrdinal = useCallback(
    async (raw: string) => {
      const total = Number(caseData?.case_count || 0);
      if (!total) return;
      const ordinal = Math.max(1, Math.min(total, Math.trunc(Number(raw) || 1)));
      if (ordinal === Number(caseData?.ordinal)) {
        setCaseOrdinalInput(String(ordinal));
        return;
      }
      await flushSave();
      const params = new URLSearchParams();
      validAssignees.forEach((u) => params.append("assignee", u));
      if (validExperimentId) params.set("experiment_id", validExperimentId);
      effectiveDatasetIds.forEach((id) => params.append("dataset_id", id));
      params.set("status", "all");
      params.set("page_size", "1");
      params.set("page", String(ordinal));
      const payload = await apiRequest<IntentQueueResponse>(`/api/intent-cases?${params.toString()}`);
      const target = payload.items?.[0];
      if (!target?.case_id) {
        getLegacyWindow().showToast?.(
          bilingual(lang, `找不到第 ${ordinal} 个 Issue。`, `Issue #${ordinal} not found.`),
          true,
        );
        return;
      }
      setRequestedCaseId(target.case_id);
      setRequestedOffsetMs(null);
      await loadCase({
        datasetId: target.dataset_id,
        caseId: target.case_id,
        offsetMs: null,
        historyMode: "push",
      });
    },
    [caseData, flushSave, validAssignees, validExperimentId, effectiveDatasetIds, lang, loadCase],
  );

  // Media preview modal (reuses classic lightbox)
  const openIntentMedia = useCallback(
    (kind: "camera" | "bev") => {
      const frames = timepoints.flatMap((tp) => {
        const desc = kind === "camera" ? tp.camera : tp.bev;
        if (!desc?.url) return [];
        return [{ ...desc, offset_ms: tp.offset_ms, timepoint_id: tp.id }];
      });
      if (!frames.length) {
        getLegacyWindow().showToast?.(
          bilingual(
            lang,
            `当前 Issue 没有可用的 ${kind === "camera" ? "Camera" : "BEV"} 图片。`,
            `No ${kind === "camera" ? "Camera" : "BEV"} frames for this Issue.`,
          ),
          true,
        );
        return;
      }
      const exactIdx = frames.findIndex((f) => f.timepoint_id === activeTp?.id);
      const index =
        exactIdx >= 0
          ? exactIdx
          : frames.reduce(
              (best, f, i) =>
                Math.abs(Number(f.offset_ms) - Number(activeTp?.offset_ms || 0)) <
                Math.abs(Number(frames[best]?.offset_ms) - Number(activeTp?.offset_ms || 0))
                  ? i
                  : best,
              0,
            );
      const bevFrames = timepoints.flatMap((tp) =>
        tp.bev?.url ? [{ ...tp.bev, offset_ms: tp.offset_ms, timepoint_id: tp.id }] : [],
      );
      const camFrames = timepoints.flatMap((tp) =>
        tp.camera?.url ? [{ ...tp.camera, offset_ms: tp.offset_ms, timepoint_id: tp.id }] : [],
      );
      getLegacyWindow().openMedia?.(kind, index, {
        caseData: {
          issue_id: caseData?.issue_id || "",
          intent_preview: true,
          assets: { frames: bevFrames },
          camera: { frames: camFrames },
          predictions: [],
        },
      });
    },
    [timepoints, activeTp, caseData, lang],
  );

  const openIntentComments = useCallback(() => {
    const issueId = caseData?.issue_id || caseData?.case_id;
    if (!issueId) return;
    getLegacyWindow()
      .openAnalysisDiscussion?.(issueId, {
        source: "intent",
        intentDatasetId: activeDatasetId,
        intentCaseId: caseData?.case_id || "",
      })
      ?.catch((err: Error) => getLegacyWindow().showToast?.(err.message, true));
  }, [caseData, activeDatasetId]);

  const handleToggleReveal = async () => {
    if (!isAdmin || !caseData?.case_id) return;
    await flushSave();
    const nextReveal = !adminReveal;
    const params = new URLSearchParams();
    validAssignees.forEach((u) => params.append("assignee", u));
    if (validExperimentId) params.set("experiment_id", validExperimentId);
    if (nextReveal) params.set("reveal_answers", "true");
    try {
      const data = await apiRequest<IntentCaseDetailResponse>(
        `/api/intent-datasets/${encodeURIComponent(activeDatasetId)}/cases/${encodeURIComponent(
          caseData.case_id,
        )}${params.toString() ? `?${params.toString()}` : ""}`,
      );
      setAdminReveal(nextReveal);
      setCaseData((prev) => (prev ? { ...prev, collaboration: data.collaboration } : prev));
    } catch (err) {
      getLegacyWindow().showToast?.((err as Error)?.message || "Toggle reveal failed", true);
    }
  };

  const handleDeleteMine = async () => {
    if (!canAnnotateIntent || !caseData?.case_id || !revisionId || deleteBusy) return;
    setDeleteBusy(true);
    try {
      await flushSave();
      const rev = stateRef.current.revisionId;
      if (!rev) return;
      const result = await apiRequest<{ labels?: IntentCaseDetailResponse["labels"] }>(
        `/api/intent-datasets/${encodeURIComponent(activeDatasetId)}/cases/${encodeURIComponent(
          caseData.case_id,
        )}/labels?expected_revision_id=${encodeURIComponent(String(rev))}`,
        { method: "DELETE" },
      );
      getLegacyWindow().acknowledgeLocalChange?.(result);
      clearIntentDraft(activeDatasetId, caseData.case_id, username || "");
      conflictBlockedRef.current = false;
      draftBaseRevisionRef.current = null;
      serverLabelsRef.current = {
        revision_id: null,
        routing_default: "",
        lane_change_default: "",
        overrides: {},
      };
      setDraftNotice(null);
      setRevisionId(null);
      setAggregate({ routing: "", laneChange: "" });
      setOverrides({});
      undoStackRef.current = [];
      dirtyRef.current = false;
      editVersionRef.current = 0;
      setTopbarSaveState(bilingual(lang, "尚未标注", "Not labeled yet"), "");
      const lowerUser = String(username || "").toLowerCase();
      setCaseData((prev) => {
        if (!prev) return prev;
        const collab = prev.collaboration || { contributors: [], comments: [] };
        const contributors = (collab.contributors || []).map((c) =>
          c.is_current || c.username === lowerUser
            ? {
                ...c,
                labeled: false,
                completed: false,
                revealed: true,
                routing_default: "",
                lane_change_default: "",
                overrides: [],
              }
            : c,
        );
        return { ...prev, labels: result.labels || null, status: "unlabeled", collaboration: { ...collab, contributors } };
      });
      setDeleteDialogOpen(false);
      getLegacyWindow().showToast?.(
        bilingual(
          lang,
          "当前标注已删除，历史版本与审计记录已保留。",
          "Label deleted; revision history and audit records retained.",
        ),
        false,
      );
    } catch (err) {
      getLegacyWindow().showToast?.((err as Error)?.message || "Delete failed", true);
    } finally {
      setDeleteBusy(false);
    }
  };

  // Keyboard shortcuts (exact classic parity)
  useEffect(() => {
    if (!active) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.isComposing || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (
        document.querySelector("dialog[open]") ||
        target?.closest("input, textarea, select, [contenteditable='true'], [role='textbox']")
      ) {
        return;
      }
      const mod = event.ctrlKey || event.metaKey;
      if (mod && !event.shiftKey && event.code === "KeyZ") {
        event.preventDefault();
        event.stopPropagation();
        handleUndo();
        return;
      }
      const digit = DIGIT_MAP[event.code];
      if (digit) {
        if (event.repeat || mod || !axisEnabled(digit[0])) return;
        event.preventDefault();
        event.stopPropagation();
        if (event.shiftKey) setAggregateAxis(digit[0], digit[1]);
        else setFrameAxis(digit[0], digit[1]);
        return;
      }
      if (event.code === "ArrowLeft" || event.code === "ArrowRight") {
        event.preventDefault();
        event.stopPropagation();
        moveFrame(event.code === "ArrowLeft" ? -1 : 1, {
          extend: event.shiftKey,
          toBoundary: mod,
        });
        return;
      }
      if (event.repeat || event.shiftKey || mod) return;
      if (event.code === "ArrowUp") {
        event.preventDefault();
        event.stopPropagation();
        void navigateCase(-1);
      } else if (event.code === "ArrowDown") {
        event.preventDefault();
        event.stopPropagation();
        void navigateCase(1);
      } else if (event.code === "KeyB") {
        event.preventDefault();
        event.stopPropagation();
        openIntentMedia("bev");
      } else if (event.code === "KeyC") {
        event.preventDefault();
        event.stopPropagation();
        openIntentMedia("camera");
      } else if (event.code === "KeyD") {
        event.preventDefault();
        event.stopPropagation();
        openIntentComments();
      } else if (event.code === "Digit0") {
        event.preventDefault();
        event.stopPropagation();
        restoreBatchPrefill();
      } else if (event.code === "Space") {
        event.preventDefault();
        event.stopPropagation();
        openIntentMedia(activeTp?.camera?.url ? "camera" : "bev");
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [
    active,
    handleUndo,
    axisEnabled,
    setAggregateAxis,
    setFrameAxis,
    moveFrame,
    navigateCase,
    openIntentMedia,
    openIntentComments,
    restoreBatchPrefill,
    activeTp,
  ]);

  // Close contributor menu on outside click
  useEffect(() => {
    if (!openMenuUser) return;
    const onDocClick = (e: MouseEvent) => {
      if ((e.target as HTMLElement | null)?.closest(".intent-contributor-menu")) return;
      setOpenMenuUser(null);
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, [openMenuUser]);

  // Zoom helpers
  const clampZoom = (kind: "camera" | "bev", next: ZoomTransform): ZoomTransform => {
    const scale = Math.max(1, Math.min(4, Math.round(next.scale * 10) / 10));
    if (scale === 1) return { scale: 1, x: 0, y: 0 };
    const stage = kind === "camera" ? cameraStageRef.current : bevStageRef.current;
    const maxX = stage ? (stage.clientWidth * (scale - 1)) / 2 : 0;
    const maxY = stage ? (stage.clientHeight * (scale - 1)) / 2 : 0;
    return {
      scale,
      x: Math.max(-maxX, Math.min(maxX, next.x)),
      y: Math.max(-maxY, Math.min(maxY, next.y)),
    };
  };

  const adjustZoom = (kind: "camera" | "bev", delta: number | "reset") => {
    const setter = kind === "camera" ? setCameraZoom : setBevZoom;
    setter((prev) =>
      delta === "reset" ? { scale: 1, x: 0, y: 0 } : clampZoom(kind, { ...prev, scale: prev.scale + delta }),
    );
  };

  // MultiSelect options
  const lowerCurrentUser = String(username || "").toLowerCase();
  const assigneeOptions: MultiSelectOption[] = useMemo(
    () =>
      assigneesList.map((a) => ({
        value: a.username,
        label: `${a.username}${
          a.username === lowerCurrentUser ? bilingual(lang, "（我）", " (me)") : ""
        } · ${a.case_count} Case`,
      })),
    [assigneesList, lowerCurrentUser, lang],
  );

  const experimentOptions: MultiSelectOption[] = useMemo(
    () =>
      experimentsList.map((item) => ({
        value: item.id,
        label: `${effectiveDatasetIds.length > 1 ? `${item.dataset_id} · ` : ""}${item.name} · ${scopeLabel(
          item.label_scope,
          lang,
        )} · ${item.case_count ?? 0} Case`,
      })),
    [experimentsList, effectiveDatasetIds.length, lang],
  );

  const assignedToMe = assigneesList.some((a) => a.username === lowerCurrentUser);
  const myTasksActive = validAssignees.length === 1 && validAssignees[0] === lowerCurrentUser;

  // Coverage ratio text
  const coverageText = useMemo(() => {
    const total = Math.max(1, timepoints.length);
    const rCounts: Record<string, number> = {};
    const lCounts: Record<string, number> = {};
    for (const tp of timepoints) {
      const eff = effectiveFor(tp);
      if (eff.routing) rCounts[eff.routing] = (rCounts[eff.routing] || 0) + 1;
      if (eff.laneChange) lCounts[eff.laneChange] = (lCounts[eff.laneChange] || 0) + 1;
    }
    const fmt = (counts: Record<string, number>, fn: (v: string, l: UiLanguage) => string) =>
      Object.entries(counts)
        .filter(([, c]) => c > 0)
        .sort((a, b) => b[1] - a[1])
        .map(([v, c]) => `${fn(v, lang)} ${Math.round((c / total) * 100)}%`)
        .join(" / ");
    const parts: string[] = [];
    if (axisEnabled("routing")) {
      parts.push(
        `Routing：${fmt(rCounts, routingLabel) || bilingual(lang, "待填", "Pending")}`,
      );
    }
    if (axisEnabled("laneChange")) {
      parts.push(
        `${bilingual(lang, "变道：", "LC: ")}${
          fmt(lCounts, laneLabel) || bilingual(lang, "待填", "Pending")
        }`,
      );
    }
    return parts.join(" · ") || "—";
  }, [timepoints, effectiveFor, axisEnabled, lang]);

  // Sorted contributors
  const contributors = useMemo(() => {
    const list = [...(caseData?.collaboration?.contributors || [])];
    const isLabeled = (c: IntentContributor) =>
      Boolean(c.labeled || c.routing_default || c.lane_change_default || (c.overrides || []).length);
    return list.sort((a, b) => {
      if (Boolean(a.is_current) !== Boolean(b.is_current)) return a.is_current ? -1 : 1;
      const al = isLabeled(a);
      const bl = isLabeled(b);
      if (al !== bl) return al ? -1 : 1;
      return String(a.username || "").localeCompare(String(b.username || ""));
    });
  }, [caseData]);

  const commentsCount = caseData?.collaboration?.comments?.length || 0;
  const activeEffective = effectiveFor(activeTp);
  const activeOverride = activeTp ? overrides[activeTp.id] : undefined;
  const frameLabelText = activeTp ? timeLabel(activeTp.offset_ms) : "";

  if (!active) return null;

  return (
    <div className="ra-intent-labeling-root" data-react-island="intent-labeling">
      <section
        className="intent-commandbar"
        aria-label={bilingual(lang, "意图标注导航", "Intent labeling navigation")}
      >
        <label className="intent-case-field">
          <span>Issue</span>
          <input
            id="intentCaseInput"
            autoComplete="off"
            spellCheck={false}
            value={caseInput}
            placeholder={bilingual(lang, "例如 cn28896325", "e.g. cn28896325")}
            onChange={(e) => setCaseInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void (async () => {
                  await flushSave();
                  const nextId = caseInput.trim();
                  setRequestedCaseId(nextId);
                  setRequestedOffsetMs(null);
                  await loadCase({ caseId: nextId, offsetMs: null, historyMode: "push" });
                })();
              }
            }}
          />
        </label>

        <div className="intent-assignee-field intent-command-field">
          <span className="intent-field-heading">
            <span>{bilingual(lang, "任务负责人", "Assignee")}</span>
            <button
              className={`intent-my-tasks${myTasksActive ? " is-active" : ""}`}
              id="intentMyTasks"
              type="button"
              disabled={!assignedToMe}
              title={
                assignedToMe
                  ? bilingual(lang, "只看实验分配给我的 Case", "Show only my assigned Cases")
                  : bilingual(lang, "当前数据集没有分配给我的任务", "No tasks assigned to me in this dataset")
              }
              onClick={() => {
                if (!assignedToMe) return;
                void (async () => {
                  await flushSave();
                  setSelectedAssignees([lowerCurrentUser]);
                  setRequestedCaseId("");
                  setRequestedOffsetMs(null);
                  await loadCase({
                    caseId: "",
                    offsetMs: null,
                    assignees: [lowerCurrentUser],
                    historyMode: "push",
                  });
                })();
              }}
            >
              {bilingual(lang, "我的任务", "My tasks")}
            </button>
          </span>
          <MultiSelect
            id="intentAssigneeFilter"
            options={assigneeOptions}
            values={validAssignees}
            ariaLabel={bilingual(lang, "任务负责人", "Assignee")}
            placeholder={bilingual(lang, "全部负责人", "All assignees")}
            allLabel={bilingual(lang, "全部负责人", "All assignees")}
            lang={lang}
            showOnlyThis
            onChange={(vals) => {
              void (async () => {
                await flushSave();
                setSelectedAssignees(vals);
                setRequestedCaseId("");
                setRequestedOffsetMs(null);
                await loadCase({ caseId: "", offsetMs: null, assignees: vals, historyMode: "push" });
              })();
            }}
          />
        </div>

        <div className="intent-experiment-filter-field intent-command-field">
          <span>{bilingual(lang, "实验分配", "Experiment")}</span>
          <MultiSelect
            id="intentAssignmentPicker"
            options={experimentOptions}
            values={validExperimentId ? [validExperimentId] : []}
            ariaLabel={bilingual(lang, "实验分配", "Experiment")}
            placeholder={bilingual(lang, "未分配（全部 Issue）", "Unassigned (all Issues)")}
            allLabel={bilingual(lang, "未分配（全部 Issue）", "Unassigned (all Issues)")}
            lang={lang}
            showOnlyThis
            onChange={(vals) => {
              const nextExp = vals[vals.length - 1] || "";
              void (async () => {
                await flushSave();
                setSelectedExperimentId(nextExp);
                setSelectedAssignees([]);
                setRequestedCaseId("");
                setRequestedOffsetMs(null);
                await loadCase({
                  caseId: "",
                  offsetMs: null,
                  assignees: [],
                  experimentId: nextExp,
                  historyMode: "push",
                });
              })();
            }}
          />
        </div>

        <button
          className="button button-quiet intent-load-case-button"
          id="intentLoadCaseButton"
          type="button"
          aria-label={bilingual(lang, "搜索并打开 Issue", "Search and open Issue")}
          onClick={() => {
            void (async () => {
              await flushSave();
              const nextId = caseInput.trim();
              setRequestedCaseId(nextId);
              setRequestedOffsetMs(null);
              await loadCase({ caseId: nextId, offsetMs: null, historyMode: "push" });
            })();
          }}
        >
          {bilingual(lang, "打开", "Open")}
        </button>

        <div className="intent-command-navigator intent-case-navigator">
          <span>{bilingual(lang, "Issue 跳转", "Issue jump")}</span>
          <div className="intent-stepper">
            <button
              className="button button-quiet"
              id="intentPreviousCase"
              type="button"
              aria-keyshortcuts="ArrowUp"
              disabled={!caseData?.previous_case?.case_id}
              onClick={() => void navigateCase(-1)}
            >
              {bilingual(lang, "← 上一 Issue", "← Prev")}
            </button>
            <input
              id="intentCaseOrdinalInput"
              type="number"
              min={1}
              max={Math.max(1, Number(caseData?.case_count || 1))}
              step={1}
              inputMode="numeric"
              aria-label={bilingual(lang, "跳转到第几个 Issue", "Jump to Issue number")}
              value={caseOrdinalInput}
              onChange={(e) => setCaseOrdinalInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  e.currentTarget.blur();
                }
              }}
              onBlur={() => void jumpToCaseOrdinal(caseOrdinalInput)}
            />
            <span className="intent-stepper-total">
              / <strong id="intentCaseCount">{caseData?.case_count ?? "—"}</strong>
            </span>
            <button
              className="button button-quiet"
              id="intentNextCase"
              type="button"
              aria-keyshortcuts="ArrowDown"
              disabled={!caseData?.next_case?.case_id}
              onClick={() => void navigateCase(1)}
            >
              {bilingual(lang, "下一 Issue →", "Next →")}
            </button>
          </div>
        </div>

        <div className="intent-command-navigator intent-frame-navigator">
          <span>{bilingual(lang, "帧跳转", "Frame jump")}</span>
          <div className="intent-stepper">
            <button
              className="button button-quiet"
              id="intentPreviousFrame"
              type="button"
              aria-keyshortcuts="ArrowLeft"
              disabled={activeTpIndex <= 0}
              onClick={() => moveFrame(-1)}
            >
              {bilingual(lang, "← 上一帧", "← Prev")}
            </button>
            <input
              id="intentFrameOrdinalInput"
              type="number"
              min={1}
              max={Math.max(1, timepoints.length)}
              step={1}
              inputMode="numeric"
              aria-label={bilingual(lang, "跳转到第几帧", "Jump to frame number")}
              value={frameOrdinalInput}
              onChange={(e) => setFrameOrdinalInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  e.currentTarget.blur();
                }
              }}
              onBlur={() => {
                if (!timepoints.length) return;
                const ord = Math.max(
                  1,
                  Math.min(timepoints.length, Math.trunc(Number(frameOrdinalInput) || 1)),
                );
                setFrameOrdinalInput(String(ord));
                selectTimepoint(timepoints[ord - 1].id);
              }}
            />
            <span className="intent-stepper-total">
              / <strong id="intentFrameCount">{timepoints.length || "—"}</strong>
            </span>
            <button
              className="button button-quiet"
              id="intentNextFrame"
              type="button"
              aria-keyshortcuts="ArrowRight"
              disabled={activeTpIndex < 0 || activeTpIndex >= timepoints.length - 1}
              onClick={() => moveFrame(1)}
            >
              {bilingual(lang, "下一帧 →", "Next →")}
            </button>
          </div>
        </div>
      </section>

      {draftNotice ? (
        <div
          className={`ra-draft-recovery-banner${draftNotice.kind === "save_failed" || draftNotice.remoteChanged ? " is-warning" : ""}`}
          id="intentDraftRecoveryBanner"
          role="status"
          aria-live="polite"
        >
          <div className="ra-draft-recovery-copy">
            <strong>
              {draftNotice.kind === "save_failed"
                ? bilingual(lang, "保存未完成 · 草稿已保留", "Save incomplete · Draft preserved")
                : bilingual(lang, "已恢复本地草稿", "Local draft restored")}
            </strong>
            <span>{draftNotice.message}</span>
          </div>
          <div className="ra-draft-recovery-actions">
            {draftNotice.remoteChanged && draftNotice.kind === "save_failed" ? (
              <button
                type="button"
                className="button button-primary"
                id="intentDraftReloadButton"
                onClick={() => {
                  if (activeDatasetId && caseData?.case_id) {
                    void loadCase({ datasetId: activeDatasetId, caseId: caseData.case_id });
                  }
                }}
              >
                {bilingual(lang, "加载最新远端版本", "Load latest server")}
              </button>
            ) : canAnnotateIntent ? (
              <button
                type="button"
                className="button button-primary"
                id="intentDraftRetryButton"
                onClick={() => {
                  dirtyRef.current = true;
                  void flushSave({ allowConflictOverwrite: Boolean(draftNotice.remoteChanged) });
                }}
              >
                {draftNotice.remoteChanged
                  ? bilingual(lang, "以草稿覆盖远端", "Overwrite server with draft")
                  : draftNotice.kind === "save_failed"
                    ? bilingual(lang, "重试保存", "Retry save")
                    : bilingual(lang, "立即保存", "Save now")}
              </button>
            ) : null}
            <button
              type="button"
              className="button button-quiet"
              id="intentDraftDiscardButton"
              onClick={() => {
                if (activeDatasetId && caseData?.case_id) {
                  clearIntentDraft(activeDatasetId, caseData.case_id, username || "");
                }
                const server = serverLabelsRef.current;
                conflictBlockedRef.current = false;
                draftBaseRevisionRef.current = server?.revision_id ?? null;
                setAggregate({
                  routing: server?.routing_default || "",
                  laneChange: server?.lane_change_default || "",
                });
                setOverrides(server?.overrides ? { ...server.overrides } : {});
                setRevisionId(server?.revision_id ?? null);
                dirtyRef.current = false;
                setDraftNotice(null);
                setTopbarSaveState(
                  server?.revision_id
                    ? bilingual(lang, "已自动保存", "Auto-saved")
                    : bilingual(lang, "尚未标注", "Not labeled yet"),
                  server?.revision_id ? "saved" : "",
                );
              }}
            >
              {draftNotice.remoteChanged
                ? bilingual(lang, "放弃草稿并采用远端", "Discard & use server")
                : bilingual(lang, "放弃草稿", "Discard draft")}
            </button>
          </div>
        </div>
      ) : null}

      {loadError && !caseData ? (
        <div className="page-card no-asset">{loadError}</div>
      ) : null}

      <div className="intent-workspace" aria-busy={loadingCase ? "true" : undefined}>
        <div className="intent-main-column">
          <section
            className="intent-media-panel"
            aria-label={bilingual(lang, "Camera 与 BEV", "Camera & BEV")}
          >
            <div className="intent-media-grid">
              {/* Camera 102 */}
              <figure className="intent-media-card">
                <figcaption>
                  <span className="intent-media-caption">
                    Camera 102 <strong id="intentCameraFrameOffset">{frameLabelText}</strong>{" "}
                    <span id="intentCameraDelta">
                      {activeTp?.camera_delta_ms != null
                        ? `Δ ${activeTp.camera_delta_ms >= 0 ? "+" : ""}${activeTp.camera_delta_ms} ms`
                        : ""}
                    </span>
                  </span>
                  <span className="intent-media-tools">
                    <span
                      className="intent-media-zoom"
                      data-available={activeTp?.camera?.url ? "true" : "false"}
                    >
                      <button
                        type="button"
                        aria-label={bilingual(lang, "缩小 Camera", "Zoom out Camera")}
                        onClick={() => adjustZoom("camera", -0.2)}
                      >
                        −
                      </button>
                      <button
                        type="button"
                        id="intentCameraZoomLevel"
                        aria-label={bilingual(lang, "恢复 Camera 到 100%", "Reset Camera zoom")}
                        onClick={() => adjustZoom("camera", "reset")}
                      >
                        {`${Math.round(cameraZoom.scale * 100)}%`}
                      </button>
                      <button
                        type="button"
                        aria-label={bilingual(lang, "放大 Camera", "Zoom in Camera")}
                        onClick={() => adjustZoom("camera", 0.2)}
                      >
                        ＋
                      </button>
                    </span>
                    <button
                      className="intent-media-open"
                      type="button"
                      aria-label={bilingual(lang, "打开 Camera 大图", "Open Camera lightbox")}
                      onClick={() => openIntentMedia("camera")}
                    >
                      {bilingual(lang, "打开大图", "Expand")} <kbd>C</kbd>
                    </button>
                  </span>
                </figcaption>
                <div
                  ref={cameraStageRef}
                  className={`intent-media-stage${cameraZoom.scale > 1 ? " is-zoomed" : ""}`}
                  onPointerDown={(e) => {
                    if ((e.target as HTMLElement).tagName !== "IMG" || cameraZoom.scale <= 1) return;
                    dragRef.current = {
                      kind: "camera",
                      pointerId: e.pointerId,
                      startClientX: e.clientX,
                      startClientY: e.clientY,
                      startX: cameraZoom.x,
                      startY: cameraZoom.y,
                    };
                    e.currentTarget.setPointerCapture(e.pointerId);
                    e.preventDefault();
                  }}
                  onPointerMove={(e) => {
                    if (!dragRef.current || dragRef.current.kind !== "camera" || dragRef.current.pointerId !== e.pointerId)
                      return;
                    const dx = e.clientX - dragRef.current.startClientX;
                    const dy = e.clientY - dragRef.current.startClientY;
                    setCameraZoom((prev) =>
                      clampZoom("camera", {
                        ...prev,
                        x: dragRef.current!.startX + dx,
                        y: dragRef.current!.startY + dy,
                      }),
                    );
                  }}
                  onPointerUp={(e) => {
                    if (dragRef.current?.pointerId === e.pointerId) dragRef.current = null;
                  }}
                  onWheel={(e) => {
                    if (!e.ctrlKey && !e.metaKey) return;
                    e.preventDefault();
                    adjustZoom("camera", e.deltaY < 0 ? 0.2 : -0.2);
                  }}
                >
                  {activeTp?.camera?.url ? (
                    <img
                      id="intentCameraImage"
                      src={activeTp.camera.url}
                      alt={bilingual(lang, "当前 Camera 帧", "Current Camera frame")}
                      draggable={false}
                      style={{
                        transform: `translate3d(${cameraZoom.x}px, ${cameraZoom.y}px, 0) scale(${cameraZoom.scale})`,
                      }}
                    />
                  ) : (
                    <div className="intent-media-missing" id="intentCameraMissing">
                      {bilingual(lang, "当前时间点无 Camera", "No Camera at this timestamp")}
                    </div>
                  )}
                </div>
              </figure>

              {/* BEV */}
              <figure className="intent-media-card">
                <figcaption>
                  <span className="intent-media-caption">
                    BEV <strong id="intentBevFrameOffset">{frameLabelText}</strong>
                  </span>
                  <span className="intent-media-tools">
                    <span
                      className="intent-media-zoom"
                      data-available={activeTp?.bev?.url ? "true" : "false"}
                    >
                      <button
                        type="button"
                        aria-label={bilingual(lang, "缩小 BEV", "Zoom out BEV")}
                        onClick={() => adjustZoom("bev", -0.2)}
                      >
                        −
                      </button>
                      <button
                        type="button"
                        id="intentBevZoomLevel"
                        aria-label={bilingual(lang, "恢复 BEV 到 100%", "Reset BEV zoom")}
                        onClick={() => adjustZoom("bev", "reset")}
                      >
                        {`${Math.round(bevZoom.scale * 100)}%`}
                      </button>
                      <button
                        type="button"
                        aria-label={bilingual(lang, "放大 BEV", "Zoom in BEV")}
                        onClick={() => adjustZoom("bev", 0.2)}
                      >
                        ＋
                      </button>
                    </span>
                    <button
                      className="intent-media-open"
                      type="button"
                      aria-label={bilingual(lang, "打开 BEV 大图", "Open BEV lightbox")}
                      onClick={() => openIntentMedia("bev")}
                    >
                      {bilingual(lang, "打开大图", "Expand")} <kbd>B</kbd>
                    </button>
                  </span>
                </figcaption>
                <div
                  ref={bevStageRef}
                  className={`intent-media-stage${bevZoom.scale > 1 ? " is-zoomed" : ""}`}
                  onPointerDown={(e) => {
                    if ((e.target as HTMLElement).tagName !== "IMG" || bevZoom.scale <= 1) return;
                    dragRef.current = {
                      kind: "bev",
                      pointerId: e.pointerId,
                      startClientX: e.clientX,
                      startClientY: e.clientY,
                      startX: bevZoom.x,
                      startY: bevZoom.y,
                    };
                    e.currentTarget.setPointerCapture(e.pointerId);
                    e.preventDefault();
                  }}
                  onPointerMove={(e) => {
                    if (!dragRef.current || dragRef.current.kind !== "bev" || dragRef.current.pointerId !== e.pointerId)
                      return;
                    const dx = e.clientX - dragRef.current.startClientX;
                    const dy = e.clientY - dragRef.current.startClientY;
                    setBevZoom((prev) =>
                      clampZoom("bev", {
                        ...prev,
                        x: dragRef.current!.startX + dx,
                        y: dragRef.current!.startY + dy,
                      }),
                    );
                  }}
                  onPointerUp={(e) => {
                    if (dragRef.current?.pointerId === e.pointerId) dragRef.current = null;
                  }}
                  onWheel={(e) => {
                    if (!e.ctrlKey && !e.metaKey) return;
                    e.preventDefault();
                    adjustZoom("bev", e.deltaY < 0 ? 0.2 : -0.2);
                  }}
                >
                  {activeTp?.bev?.url ? (
                    <img
                      id="intentBevImage"
                      src={activeTp.bev.url}
                      alt={bilingual(lang, "当前 BEV 帧", "Current BEV frame")}
                      draggable={false}
                      style={{
                        transform: `translate3d(${bevZoom.x}px, ${bevZoom.y}px, 0) scale(${bevZoom.scale})`,
                      }}
                    />
                  ) : (
                    <div className="intent-media-missing" id="intentBevMissing">
                      {bilingual(lang, "当前时间点无 BEV", "No BEV at this timestamp")}
                    </div>
                  )}
                </div>
              </figure>
            </div>
          </section>

          <section
            className="intent-timeline-panel"
            aria-label={bilingual(lang, "Case 时间轴", "Case timeline")}
          >
            <div className="intent-timeline-heading">
              <strong>{bilingual(lang, "帧时间轴", "Frame timeline")}</strong>
              <span>
                {bilingual(
                  lang,
                  "滚轮横向浏览 · ← → 切帧 · Shift 连选",
                  "Scroll horizontally · ← → frames · Shift multi-select",
                )}
              </span>
            </div>
            <div
              className="intent-timeline"
              id="intentTimeline"
              ref={timelineRef}
              onWheel={(e) => {
                if (e.ctrlKey || e.metaKey || Math.abs(e.deltaX) >= Math.abs(e.deltaY)) return;
                e.preventDefault();
                e.currentTarget.scrollLeft += e.deltaY;
              }}
            >
              {timepoints.map((tp) => {
                const isSelected = selectedTimepointIds.includes(tp.id);
                const isActive = tp.id === activeTimepointId;
                const eff = effectiveFor(tp);
                const ov = overrides[tp.id];
                const camThumb = tp.camera?.thumbnail_url;
                const bevThumb = tp.bev?.thumbnail_url;
                return (
                  <button
                    key={tp.id}
                    type="button"
                    className={`intent-timepoint${isSelected ? " selected" : ""}${
                      isActive ? " active" : ""
                    }`}
                    data-intent-timepoint={tp.id}
                    aria-label={bilingual(
                      lang,
                      `切换到 ${timeLabel(tp.offset_ms)}`,
                      `Switch to ${timeLabel(tp.offset_ms)}`,
                    )}
                    aria-pressed={isSelected}
                    onClick={(e) => {
                      selectTimepoint(tp.id, e.shiftKey);
                      e.currentTarget.blur();
                    }}
                  >
                    <strong>{timeLabel(tp.offset_ms)}</strong>
                    <span className="intent-thumb-stack">
                      {camThumb ? (
                        <img src={camThumb} loading="lazy" decoding="async" alt="" />
                      ) : (
                        <span className="intent-thumb-missing">
                          {bilingual(lang, "Camera 缺失", "No Camera")}
                        </span>
                      )}
                      {bevThumb ? (
                        <img src={bevThumb} loading="lazy" decoding="async" alt="" />
                      ) : (
                        <span className="intent-thumb-missing">
                          {bilingual(lang, "BEV 缺失", "No BEV")}
                        </span>
                      )}
                    </span>
                    <span className={`intent-timepoint-labels${ov ? " is-override" : ""}`}>
                      {axisEnabled("routing") ? (
                        <b
                          className={`intent-chip${
                            !eff.routing
                              ? " is-pending"
                              : ` ${chipToneClass(eff.routing)}${ov?.routing_intent ? " is-override" : ""}`
                          }`}
                        >
                          {routingLabel(eff.routing, lang)}
                        </b>
                      ) : null}
                      {axisEnabled("laneChange") ? (
                        <b
                          className={`intent-chip${
                            !eff.laneChange
                              ? " is-pending"
                              : ` ${chipToneClass(eff.laneChange)}${ov?.lane_change_intent ? " is-override" : ""}`
                          }`}
                        >
                          {laneLabel(eff.laneChange, lang)}
                        </b>
                      ) : null}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        </div>

        <aside className="intent-label-rail">
          {/* Batch Prefill */}
          <section className="intent-card intent-label-editor">
            <h3>
              <span>{bilingual(lang, "批量预填", "Batch prefill")}</span>
              <small className="intent-heading-stat" id="intentCoverage" title={coverageText}>
                {coverageText}
              </small>
            </h3>
            {axisEnabled("routing") ? (
              <>
                <h4>{bilingual(lang, "Routing 意图", "Routing intent")}</h4>
                <div className="intent-label-grid intent-routing-grid" id="intentAggregateRouting">
                  {ROUTING_OPTIONS.map((opt) => {
                    const selected = aggregate.routing === opt.value;
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        className={selected ? "active" : undefined}
                        aria-pressed={selected}
                        aria-keyshortcuts={`Shift+${opt.kbd}`}
                        disabled={!canAnnotateIntent}
                        onClick={() => setAggregateAxis("routing", opt.value)}
                      >
                        <kbd>{`⇧${opt.kbd}`}</kbd>
                        {bilingual(lang, opt.zh, opt.en)}
                      </button>
                    );
                  })}
                </div>
              </>
            ) : null}
            {axisEnabled("laneChange") ? (
              <>
                <h4>{bilingual(lang, "变道意图", "Lane-change intent")}</h4>
                <div className="intent-label-grid intent-lane-grid" id="intentAggregateLane">
                  {LANE_OPTIONS.map((opt) => {
                    const selected = aggregate.laneChange === opt.value;
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        className={selected ? "active" : undefined}
                        aria-pressed={selected}
                        aria-keyshortcuts={`Shift+${opt.kbd}`}
                        disabled={!canAnnotateIntent}
                        onClick={() => setAggregateAxis("laneChange", opt.value)}
                      >
                        <kbd>{`⇧${opt.kbd}`}</kbd>
                        {bilingual(lang, opt.zh, opt.en)}
                      </button>
                    );
                  })}
                </div>
              </>
            ) : null}
          </section>

          {/* Current Frame Labels */}
          <section className="intent-card intent-label-editor">
            <h3>
              <span id="intentFrameTitle">
                {selectedTimepoints.length > 1
                  ? bilingual(lang, "多个帧标签", "Multi-frame labels")
                  : bilingual(lang, "当前帧标签", "Current frame")}
              </span>{" "}
              <small id="intentFrameSource">
                {selectedTimepoints.length > 1
                  ? bilingual(
                      lang,
                      `已选 ${selectedTimepoints.length} 帧，数字键应用到全部选中帧`,
                      `${selectedTimepoints.length} frames selected`,
                    )
                  : activeOverride
                    ? bilingual(lang, "当前帧已单独修改", "Overridden for this frame")
                    : bilingual(lang, "当前帧来自批量预填", "From batch prefill")}
              </small>
            </h3>
            {axisEnabled("routing") ? (
              <>
                <h4>{bilingual(lang, "Routing 意图", "Routing intent")}</h4>
                <div className="intent-label-grid intent-routing-grid">
                  {ROUTING_OPTIONS.map((opt) => {
                    const selected = activeEffective.routing === opt.value;
                    const isOv = selected && Boolean(activeOverride?.routing_intent);
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        className={`${selected ? "active" : ""}${isOv ? " is-override" : ""}`.trim() || undefined}
                        aria-pressed={selected}
                        aria-keyshortcuts={opt.kbd}
                        disabled={!canAnnotateIntent}
                        onClick={() => setFrameAxis("routing", opt.value)}
                      >
                        <kbd>{opt.kbd}</kbd>
                        {bilingual(lang, opt.zh, opt.en)}
                      </button>
                    );
                  })}
                </div>
              </>
            ) : null}
            {axisEnabled("laneChange") ? (
              <>
                <h4>{bilingual(lang, "变道意图", "Lane-change intent")}</h4>
                <div className="intent-label-grid intent-lane-grid">
                  {LANE_OPTIONS.map((opt) => {
                    const selected = activeEffective.laneChange === opt.value;
                    const isOv = selected && Boolean(activeOverride?.lane_change_intent);
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        className={`${selected ? "active" : ""}${isOv ? " is-override" : ""}`.trim() || undefined}
                        aria-pressed={selected}
                        aria-keyshortcuts={opt.kbd}
                        disabled={!canAnnotateIntent}
                        onClick={() => setFrameAxis("laneChange", opt.value)}
                      >
                        <kbd>{opt.kbd}</kbd>
                        {bilingual(lang, opt.zh, opt.en)}
                      </button>
                    );
                  })}
                </div>
              </>
            ) : null}
            <button
              className="button button-quiet intent-restore-button"
              id="intentRestoreBatchPrefill"
              type="button"
              aria-keyshortcuts="0"
              disabled={!canAnnotateIntent}
              onClick={restoreBatchPrefill}
            >
              <span id="intentRestoreBatchPrefillText">
                {selectedTimepoints.length > 1
                  ? bilingual(
                      lang,
                      `选中 ${selectedTimepoints.length} 帧恢复批量预填`,
                      `Restore batch prefill (${selectedTimepoints.length} frames)`,
                    )
                  : bilingual(lang, "当前帧恢复批量预填", "Restore batch prefill")}
              </span>{" "}
              <kbd>0</kbd>
            </button>
          </section>

          {/* Contributors */}
          <section
            className="intent-card intent-collaboration-card intent-contributors-card"
            aria-labelledby="intentContributorsTitle"
          >
            <h3 className="intent-contributors-heading">
              <span id="intentContributorsTitle">{bilingual(lang, "已有标注", "Annotations")}</span>
              {isAdmin && caseData?.collaboration?.blind_active ? (
                <button
                  className="button button-quiet"
                  id="intentToggleReveal"
                  type="button"
                  onClick={() => void handleToggleReveal()}
                >
                  {caseData?.collaboration?.answers_revealed
                    ? bilingual(lang, "恢复盲态", "Hide answers")
                    : bilingual(lang, "管理员解盲", "Admin reveal")}
                </button>
              ) : null}
            </h3>
            <div className="intent-contributor-list" id="intentContributorList">
              {!contributors.length ? (
                <p>{bilingual(lang, "尚无标注记录", "No annotations yet")}</p>
              ) : (
                contributors.map((item) => {
                  const labeled = Boolean(
                    item.labeled ||
                      item.routing_default ||
                      item.lane_change_default ||
                      (item.overrides || []).length,
                  );
                  const statusLabel = !labeled
                    ? bilingual(lang, "待标注", "Pending")
                    : item.completed
                      ? bilingual(lang, "完整", "Complete")
                      : bilingual(lang, "部分", "Partial");
                  if (!item.revealed || !labeled) {
                    return (
                      <article
                        key={item.username}
                        className={`intent-contributor${item.is_current ? " is-current" : ""}`}
                      >
                        <strong>
                          {item.username}
                          {item.is_current ? bilingual(lang, "（我）", " (me)") : ""}
                        </strong>
                        <span
                          className={`intent-contributor-status ${labeled ? "is-labeled" : "is-pending"}`}
                        >
                          {statusLabel}
                        </span>
                      </article>
                    );
                  }
                  const frameOv =
                    (item.overrides || []).find((ov) => ov.timepoint_id === activeTp?.id) ||
                    ({} as IntentOverride);
                  const rVal = frameOv.routing_intent || item.routing_default;
                  const lVal = frameOv.lane_change_intent || item.lane_change_default;
                  const canDeleteMine = Boolean(item.is_current && canAnnotateIntent && revisionId);
                  const menuOpen = openMenuUser === item.username;
                  return (
                    <article
                      key={item.username}
                      className={`intent-contributor is-revealed${item.is_current ? " is-current" : ""}`}
                    >
                      <strong>
                        {item.username}
                        {item.is_current ? bilingual(lang, "（我）", " (me)") : ""}
                      </strong>
                      <div className="intent-contributor-labels">
                        {axisEnabled("routing") ? (
                          <b className={`intent-chip ${!rVal ? "is-pending" : chipToneClass(rVal)}`}>
                            {routingLabel(rVal, lang)}
                          </b>
                        ) : null}
                        {axisEnabled("laneChange") ? (
                          <b className={`intent-chip ${!lVal ? "is-pending" : chipToneClass(lVal)}`}>
                            {laneLabel(lVal, lang)}
                          </b>
                        ) : null}
                      </div>
                      {canDeleteMine ? (
                        <div className={`intent-contributor-menu${menuOpen ? " is-open" : ""}`}>
                          <button
                            className="intent-contributor-menu-trigger"
                            type="button"
                            aria-haspopup="menu"
                            aria-expanded={menuOpen}
                            title={bilingual(lang, "更多", "More")}
                            onClick={(e) => {
                              e.stopPropagation();
                              setOpenMenuUser(menuOpen ? null : item.username);
                            }}
                          >
                            ⋯
                          </button>
                          {menuOpen ? (
                            <div className="intent-contributor-menu-panel">
                              <button
                                type="button"
                                onClick={() => {
                                  setOpenMenuUser(null);
                                  setDeleteDialogOpen(true);
                                }}
                              >
                                {bilingual(lang, "删除标注", "Delete label")}
                              </button>
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                      <small
                        className={`intent-contributor-completion ${
                          item.completed ? "is-complete" : "is-partial"
                        }`}
                        title={item.completion_reason || ""}
                      >
                        {item.completed
                          ? bilingual(lang, "完整", "Complete")
                          : bilingual(lang, "部分", "Partial")}{" "}
                        · {item.completion_reason || bilingual(lang, "覆盖情况未知", "Coverage unknown")}
                      </small>
                    </article>
                  );
                })
              )}
            </div>
          </section>

          {/* Discussion */}
          <section
            className="intent-card intent-collaboration-card intent-discussion-card"
            aria-labelledby="intentCommentsTitle"
          >
            <h3>
              <span id="intentCommentsTitle">{bilingual(lang, "讨论", "Discussion")}</span>
              <small id="intentCommentCount">
                {bilingual(lang, `${commentsCount} 条`, `${commentsCount}`)}
              </small>
            </h3>
            <button
              className="button button-quiet"
              id="intentOpenComments"
              type="button"
              aria-keyshortcuts="D"
              onClick={openIntentComments}
            >
              {commentsCount
                ? bilingual(lang, `打开讨论 · ${commentsCount}`, `Discussion · ${commentsCount}`)
                : bilingual(lang, "打开讨论", "Discussion")}{" "}
              <kbd>D</kbd>
            </button>
          </section>
        </aside>
      </div>

      <ModalDialog
        open={deleteDialogOpen}
        title={bilingual(lang, "删除当前标注", "Delete current label")}
        lang={lang}
        onClose={() => !deleteBusy && setDeleteDialogOpen(false)}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              disabled={deleteBusy}
              onClick={() => setDeleteDialogOpen(false)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-danger"
              disabled={deleteBusy}
              onClick={() => void handleDeleteMine()}
            >
              {bilingual(lang, "确认删除", "Confirm delete")}
            </button>
          </>
        }
      >
        <p>
          {bilingual(
            lang,
            `确认删除你在 ${caseData?.case_id || ""} 的当前标注？历史修订与审计记录会保留。`,
            `Delete your current label on ${caseData?.case_id || ""}? Revision history and audit records will be retained.`,
          )}
        </p>
      </ModalDialog>
    </div>
  );
};
