import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, UiLanguage, withWorkbenchBase } from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

interface ModelRunSummary {
  id: string;
  name?: string | null;
  source_name?: string | null;
}

interface CollectionMember {
  run_id: string;
  role?: string;
  is_reference?: boolean;
  ordinal?: number;
  available_now?: boolean;
  run?: ModelRunSummary | null;
}

interface CollectionRevision {
  revision: number;
  content_sha256?: string;
  members_sha256?: string;
  members?: CollectionMember[];
  created_by?: string;
  created_at?: string;
}

interface CollectionAuditRow {
  action?: string;
  revision?: number;
  actor?: string;
  actor_source?: string;
  actor_verified?: boolean;
  created_at?: string;
  context_id?: string;
}

interface CollectionListItem {
  id: string;
  name: string;
  current_revision?: number;
}

interface CollectionDetail {
  id: string;
  name: string;
  description?: string;
  current_revision: number;
  metadata_revision?: number;
  current?: CollectionRevision;
  history?: CollectionRevision[];
  audit?: CollectionAuditRow[];
}

interface EvaluationHistoryItem {
  id: string;
  collection_revision: number;
  reference_type: string;
  context_sha256?: string;
  workset_sha256?: string;
  created_at?: string;
}

interface EvaluationRunMetric {
  run_id: string;
  run?: ModelRunSummary | null;
  accuracy?: number;
  correct_count?: number;
  reference_denominator?: number;
  coverage?: number;
  pairwise_union_denominator?: number;
  supported_coverage?: number;
  supported_count?: number;
  valid_reference_count?: number;
  absent_count?: number;
  absent_prediction_count?: number;
  unknown_count?: number;
  available_now?: boolean;
  transitions_vs_reference?: Record<string, number>;
  confusion?: Array<{ reference_label: string; cells?: Record<string, number> }>;
}

interface EvaluationCaseItem {
  issue_id: string;
  excluded?: boolean;
  reference_label?: string | null;
  reference_valid?: boolean;
  shared_label?: { state?: string; expected_output?: string; method?: string } | null;
  predictions?: Record<
    string,
    {
      label?: string;
      correct?: boolean;
      reason?: string;
      model_reviews?: Array<{ status?: string; reviewer?: string }>;
    }
  >;
}

interface EvaluationPayload {
  id: string;
  collection_id: string;
  collection_revision: number;
  collection_sha256?: string;
  workset_sha256?: string;
  context_sha256?: string;
  scoring_policy_version?: string;
  scoring_policy_sha256?: string;
  exclusion?: { sha256?: string };
  comparison_reference_run_id?: string;
  selection_source_run_id?: string;
  selection_bias_warning?: string;
  workset?: { workset_id?: string; baseline_scopes?: string[] };
  reference?: {
    type?: string;
    id?: string;
    sha256?: string;
    snapshot?: {
      scope_snapshots?: Array<{
        baseline_scope?: string;
        id?: string;
        content_sha256?: string;
        member_count?: number;
      }>;
    };
  };
  members?: CollectionMember[];
  summary?: {
    workset_count?: number;
    runs?: EvaluationRunMetric[];
  };
  items?: EvaluationCaseItem[];
  page?: number;
  page_count?: number;
  total?: number;
}

interface LegacyWindowBridge {
  state?: {
    baselineCatalog?: Array<{ id?: string; scope?: string }>;
    config?: { baselines?: Array<{ id?: string; scope?: string }> };
    runComparison?: { baselineRunId?: string; candidateRunId?: string };
  };
}

function percentage(value: number | null | undefined): string {
  return `${(Number(value || 0) * 100).toFixed(1)}%`;
}

function makeUuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `rc-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function resolveSelectedScopes(selectedBaselines: string[]): string[] {
  const win = window as unknown as LegacyWindowBridge;
  const catalog = win.state?.baselineCatalog || win.state?.config?.baselines || [];
  const chosen = new Set(selectedBaselines);
  return catalog
    .filter((item) => chosen.has(String(item?.id || "")))
    .map((item) => String(item.scope || "").trim())
    .filter(Boolean);
}

export interface RunCollectionsPageProps {
  active: boolean;
  lang: UiLanguage;
  selectedBaselines: string[];
  canWrite: boolean;
}

export const RunCollectionsPage: React.FC<RunCollectionsPageProps> = ({
  active,
  lang,
  selectedBaselines,
  canWrite,
}) => {
  const queryClient = useQueryClient();
  const baselinesParam = selectedBaselines.join(",");
  const initialParams = useMemo(() => new URLSearchParams(window.location.search), []);

  const [selectedCollectionId, setSelectedCollectionId] = useState<string>(
    () => initialParams.get("collection_id") || initialParams.get("collection") || "",
  );
  const [selectedRevision, setSelectedRevision] = useState<number>(() =>
    Number(initialParams.get("collection_revision") || initialParams.get("revision") || 0),
  );
  const [evaluationId, setEvaluationId] = useState<string>(
    () => initialParams.get("evaluation_id") || initialParams.get("context") || "",
  );
  const [evalPage, setEvalPage] = useState<number>(() =>
    Math.max(1, Number(initialParams.get("evaluation_page") || initialParams.get("page") || 1)),
  );
  const [evalSearch, setEvalSearch] = useState<string>(
    () => initialParams.get("evaluation_q") || initialParams.get("q") || "",
  );
  const [evalSearchDraft, setEvalSearchDraft] = useState<string>(evalSearch);
  const searchTimerRef = useRef<number | null>(null);

  // Form fields
  const [nameInput, setNameInput] = useState("");
  const [descInput, setDescInput] = useState("");
  const [draftMembers, setDraftMembers] = useState<CollectionMember[]>([]);
  const [addRunId, setAddRunId] = useState("");
  const [createName, setCreateName] = useState("");
  const [referenceType, setReferenceType] = useState<"gt" | "label_result">("gt");
  const [referenceId, setReferenceId] = useState("");
  const [scopeLabelRefs, setScopeLabelRefs] = useState<Record<string, string>>({});
  const [comparisonRefRunId, setComparisonRefRunId] = useState("");
  const [worksetId, setWorksetId] = useState("");
  const [selectionSourceRunId, setSelectionSourceRunId] = useState("");
  const [taskAssignees, setTaskAssignees] = useState("");
  const [statusMessage, setStatusMessage] = useState<{ text: string; error: boolean }>({
    text: "",
    error: false,
  });
  const [busyAction, setBusyAction] = useState<string>("");
  const [savePairwiseModalOpen, setSavePairwiseModalOpen] = useState(false);
  const [savePairwiseName, setSavePairwiseName] = useState("");

  const syncUrl = useCallback(
    (
      next: {
        collectionId?: string;
        revision?: number;
        evaluationId?: string;
        page?: number;
        search?: string;
        refRunId?: string;
      },
      mode: "replace" | "push" = "replace",
    ) => {
      if (!active) return;
      const url = new URL(window.location.href);
      if (next.collectionId) {
        url.searchParams.set("collection_id", next.collectionId);
        url.searchParams.set("collection", next.collectionId);
        if (next.revision) {
          url.searchParams.set("collection_revision", String(next.revision));
          url.searchParams.set("revision", String(next.revision));
        }
      } else {
        url.searchParams.delete("collection_id");
        url.searchParams.delete("collection");
        url.searchParams.delete("collection_revision");
        url.searchParams.delete("revision");
      }
      if (next.evaluationId) {
        url.searchParams.set("evaluation_id", next.evaluationId);
        url.searchParams.set("context", next.evaluationId);
        url.searchParams.set("evaluation_page", String(next.page || 1));
        url.searchParams.set("page", String(next.page || 1));
        if (next.refRunId) {
          url.searchParams.set("evaluation_reference_run_id", next.refRunId);
          url.searchParams.set("reference_run", next.refRunId);
        } else {
          url.searchParams.delete("evaluation_reference_run_id");
          url.searchParams.delete("reference_run");
        }
        if (next.search) {
          url.searchParams.set("evaluation_q", next.search);
          url.searchParams.set("q", next.search);
        } else {
          url.searchParams.delete("evaluation_q");
          url.searchParams.delete("q");
        }
      } else {
        url.searchParams.delete("evaluation_id");
        url.searchParams.delete("context");
        url.searchParams.delete("evaluation_page");
        url.searchParams.delete("page");
        url.searchParams.delete("evaluation_q");
        url.searchParams.delete("q");
      }
      window.history[mode === "push" ? "pushState" : "replaceState"](
        { ...(window.history.state || {}), page: "run-collections" },
        "",
        `${withWorkbenchBase("/multi-run-evaluation")}${url.search}${url.hash}`,
      );
    },
    [active],
  );

  // Queries
  const runsQuery = useQuery<{ items?: ModelRunSummary[]; runs?: ModelRunSummary[] }>({
    queryKey: ["run-collections-model-runs", baselinesParam],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({ page: "1", page_size: "200" });
      if (baselinesParam) qs.set("baselines", baselinesParam);
      return apiRequest(`/api/model-runs?${qs.toString()}`, { signal });
    },
    enabled: active,
    staleTime: 20_000,
  });
  const modelRuns = useMemo(
    () => runsQuery.data?.items || runsQuery.data?.runs || [],
    [runsQuery.data],
  );

  const collectionsQuery = useQuery<{ items?: CollectionListItem[] }>({
    queryKey: ["run-collections-list"],
    queryFn: ({ signal }) => apiRequest("/api/run-collections", { signal }),
    enabled: active,
  });
  const collections = useMemo(() => collectionsQuery.data?.items || [], [collectionsQuery.data]);

  // Default to first collection if none selected
  useEffect(() => {
    if (!active || collectionsQuery.isLoading) return;
    if (!collections.length) {
      if (selectedCollectionId) setSelectedCollectionId("");
      setStatusMessage({
        text: bilingual(
          lang,
          "尚无 Collection。可从 Pairwise 保存，或选择 Run 创建。",
          "No Collection yet. Save the pairwise Runs or select Runs and create one.",
        ),
        error: false,
      });
      return;
    }
    if (!selectedCollectionId || !collections.some((c) => c.id === selectedCollectionId)) {
      setSelectedCollectionId(collections[0].id);
    }
  }, [active, collections, collectionsQuery.isLoading, selectedCollectionId, lang]);

  const detailQuery = useQuery<CollectionDetail>({
    queryKey: ["run-collection-detail", selectedCollectionId],
    queryFn: ({ signal }) =>
      apiRequest<CollectionDetail>(
        `/api/run-collections/${encodeURIComponent(selectedCollectionId)}`,
        { signal },
      ),
    enabled: active && Boolean(selectedCollectionId),
  });
  const detail = detailQuery.data || null;

  const evalHistoryQuery = useQuery<{ items?: EvaluationHistoryItem[] }>({
    queryKey: ["run-collection-eval-history", selectedCollectionId],
    queryFn: ({ signal }) =>
      apiRequest(
        `/api/run-evaluations?collection_id=${encodeURIComponent(selectedCollectionId)}&limit=100`,
        { signal },
      ),
    enabled: active && Boolean(selectedCollectionId),
  });

  const evaluationQuery = useQuery<EvaluationPayload>({
    queryKey: ["run-collection-evaluation", evaluationId, evalPage, evalSearch],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        page: String(evalPage),
        page_size: "50",
        q: evalSearch,
      });
      return apiRequest<EvaluationPayload>(
        `/api/run-evaluations/${encodeURIComponent(evaluationId)}?${params.toString()}`,
        { signal },
      );
    },
    enabled: active && Boolean(evaluationId),
  });
  const evaluation = evaluationQuery.data || null;

  // Hydrate detail form fields & draft members whenever detail or selectedRevision changes
  useEffect(() => {
    if (!detail) {
      setNameInput("");
      setDescInput("");
      setDraftMembers([]);
      return;
    }
    setNameInput(detail.name || "");
    setDescInput(detail.description || "");
    const history = detail.history || [];
    const matchedRev =
      history.find((item) => Number(item.revision) === Number(selectedRevision)) ||
      detail.current ||
      history[0];
    const resolvedRev = Number(matchedRev?.revision || detail.current_revision || 1);
    if (resolvedRev !== selectedRevision) {
      setSelectedRevision(resolvedRev);
    }
    const members = (matchedRev?.members || []).map((item) => ({ ...item }));
    setDraftMembers(members);
    const markedRef = members.find((m) => m.is_reference)?.run_id || "";
    setComparisonRefRunId((prev) =>
      members.some((m) => m.run_id === prev) ? prev : markedRef,
    );
  }, [detail, selectedRevision]);

  // Hydrate evaluation metadata into controls when loaded
  useEffect(() => {
    if (!evaluation) return;
    if (evaluation.reference?.type === "label_result") {
      setReferenceType("label_result");
    } else {
      setReferenceType("gt");
    }
    setReferenceId(evaluation.reference?.id || "");
    if (evaluation.comparison_reference_run_id) {
      setComparisonRefRunId(evaluation.comparison_reference_run_id);
    }
    if (evaluation.workset?.workset_id) setWorksetId(evaluation.workset.workset_id);
    setSelectionSourceRunId(evaluation.selection_source_run_id || "");
    const scopeSnaps = evaluation.reference?.snapshot?.scope_snapshots || [];
    if (scopeSnaps.length) {
      setScopeLabelRefs(
        Object.fromEntries(
          scopeSnaps
            .filter((item) => item.baseline_scope)
            .map((item) => [String(item.baseline_scope), String(item.id || "")]),
        ),
      );
    }
  }, [evaluation]);

  const memberName = useCallback(
    (member: { run_id?: string; run?: ModelRunSummary | null }) => {
      const run =
        member.run || modelRuns.find((item) => String(item.id) === String(member.run_id)) || null;
      return String(run?.name || run?.source_name || member.run_id || "Unavailable Run");
    },
    [modelRuns],
  );

  const activeRevisionObj = useMemo(
    () =>
      (detail?.history || []).find((item) => Number(item.revision) === Number(selectedRevision)) ||
      null,
    [detail, selectedRevision],
  );

  const activeScopes = useMemo(() => {
    const raw = evaluation?.workset?.baseline_scopes || resolveSelectedScopes(selectedBaselines);
    return Array.from(new Set(raw.map(String).filter(Boolean)));
  }, [evaluation, selectedBaselines]);

  // Select options
  const collectionOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "选择评测项目", "Select an evaluation project") },
      ...collections.map((item) => ({
        value: item.id,
        label: `${item.name} · r${Number(item.current_revision || 0)}`,
      })),
    ],
    [collections, lang],
  );

  const revisionOptions: UiSelectOption[] = useMemo(
    () =>
      (detail?.history || []).map((item) => ({
        value: String(item.revision),
        label: `r${Number(item.revision)} · ${String(item.content_sha256 || "").slice(0, 12)}${
          Number(item.revision) === Number(detail?.current_revision) ? " · current" : ""
        }`,
      })),
    [detail],
  );

  const addRunOptions: UiSelectOption[] = useMemo(() => {
    const existing = new Set(draftMembers.map((m) => String(m.run_id)));
    return [
      { value: "", label: bilingual(lang, "选择 Run", "Select a Run") },
      ...modelRuns
        .filter((r) => !existing.has(String(r.id)))
        .map((r) => ({
          value: String(r.id),
          label: `${r.name || r.source_name || r.id} · ${String(r.id).slice(0, 8)}`,
        })),
    ];
  }, [draftMembers, modelRuns, lang]);

  const referenceTypeOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "gt", label: bilingual(lang, "GT 版本（创建时冻结）", "GT snapshot (frozen)") },
      { value: "label_result", label: bilingual(lang, "标注版本", "Label snapshot") },
    ],
    [lang],
  );

  const comparisonRefOptions: UiSelectOption[] = useMemo(
    () => [
      {
        value: "",
        label: bilingual(lang, "使用 Collection 参考标记", "Use Collection reference mark"),
      },
      ...draftMembers.map((m) => ({ value: m.run_id, label: memberName(m) })),
    ],
    [draftMembers, memberName, lang],
  );

  const selectionSourceOptions: UiSelectOption[] = useMemo(
    () => [
      { value: "", label: bilingual(lang, "不按 Run 筛选", "Do not filter by a Run") },
      ...draftMembers.map((m) => ({ value: m.run_id, label: memberName(m) })),
    ],
    [draftMembers, memberName, lang],
  );

  const runAction = async (key: string, fn: () => Promise<void>) => {
    setBusyAction(key);
    try {
      await fn();
    } catch (err) {
      setStatusMessage({
        text: err instanceof Error ? err.message : String(err),
        error: true,
      });
    } finally {
      setBusyAction("");
    }
  };

  const handleMoveMember = (index: number, delta: -1 | 1) => {
    const nextIdx = index + delta;
    if (nextIdx < 0 || nextIdx >= draftMembers.length) return;
    setDraftMembers((prev) => {
      const copy = [...prev];
      [copy[index], copy[nextIdx]] = [copy[nextIdx], copy[index]];
      return copy.map((item, ord) => ({ ...item, ordinal: ord + 1 }));
    });
  };

  const handleToggleRefMember = (index: number) => {
    setDraftMembers((prev) => {
      const nextFlag = !prev[index]?.is_reference;
      return prev.map((item, idx) => ({ ...item, is_reference: idx === index && nextFlag }));
    });
  };

  const handleRemoveMember = (index: number) => {
    setDraftMembers((prev) => prev.filter((_, idx) => idx !== index));
  };

  const handleAddMember = () => {
    if (!addRunId || draftMembers.some((m) => m.run_id === addRunId)) return;
    const run = modelRuns.find((item) => String(item.id) === addRunId) || null;
    setDraftMembers((prev) => [
      ...prev,
      { run_id: addRunId, role: "", is_reference: prev.length === 0, available_now: true, run },
    ]);
    setAddRunId("");
  };

  const handleRename = () =>
    void runAction("rename", async () => {
      if (!detail?.id) {
        throw new Error(bilingual(lang, "请先选择评测项目。", "Select an evaluation project first."));
      }
      await apiRequest<CollectionDetail>(`/api/run-collections/${encodeURIComponent(detail.id)}`, {
        method: "PATCH",
        body: {
          expected_revision: Number(detail.current_revision),
          expected_metadata_revision: Number(detail.metadata_revision || 0),
          name: nameInput,
          description: descInput,
        },
      });
      await queryClient.invalidateQueries({ queryKey: ["run-collections-list"] });
      await queryClient.invalidateQueries({ queryKey: ["run-collection-detail", detail.id] });
      setStatusMessage({
        text: bilingual(
          lang,
          "元数据已更新，没有创建新 Revision。",
          "Metadata updated without creating a new revision.",
        ),
        error: false,
      });
    });

  const handleAppendRevision = () =>
    void runAction("append", async () => {
      if (!detail?.id) {
        throw new Error(bilingual(lang, "请先选择评测项目。", "Select an evaluation project first."));
      }
      const res = await apiRequest<CollectionDetail>(
        `/api/run-collections/${encodeURIComponent(detail.id)}/revisions`,
        {
          method: "POST",
          headers: { "Idempotency-Key": makeUuid() },
          body: {
            expected_revision: Number(detail.current_revision),
            members: draftMembers.map((item) => ({
              run_id: item.run_id,
              role: item.role || "",
              is_reference: Boolean(item.is_reference),
            })),
          },
        },
      );
      setSelectedRevision(Number(res.current_revision));
      await queryClient.invalidateQueries({ queryKey: ["run-collection-detail", detail.id] });
      syncUrl({ collectionId: detail.id, revision: Number(res.current_revision) }, "push");
      setStatusMessage({
        text: bilingual(
          lang,
          `已保存项目版本 r${res.current_revision}。`,
          `Appended revision r${res.current_revision}.`,
        ),
        error: false,
      });
    });

  const handleCreateCollection = () =>
    void runAction("create", async () => {
      const members = draftMembers
        .map((item) => ({
          run_id: String(item.run_id || ""),
          role: String(item.role || ""),
          is_reference: Boolean(item.is_reference),
        }))
        .filter((item) => item.run_id);
      if (!members.length) {
        throw new Error(bilingual(lang, "先选择至少一个 Run。", "Select at least one Run first."));
      }
      const created = await apiRequest<CollectionDetail>("/api/run-collections", {
        method: "POST",
        headers: { "Idempotency-Key": makeUuid() },
        body: { name: createName.trim(), description: "", members, source: "user" },
      });
      setSelectedCollectionId(created.id);
      setSelectedRevision(Number(created.current_revision || 1));
      setEvaluationId("");
      setCreateName("");
      await queryClient.invalidateQueries({ queryKey: ["run-collections-list"] });
      syncUrl({ collectionId: created.id, revision: Number(created.current_revision || 1) }, "push");
      setStatusMessage({
        text: bilingual(
          lang,
          `已创建 Collection r${created.current_revision}。`,
          `Created Collection r${created.current_revision}.`,
        ),
        error: false,
      });
    });

  const handleOpenSavePairwise = () => {
    const win = window as unknown as LegacyWindowBridge;
    const baseline = String(win.state?.runComparison?.baselineRunId || "");
    const candidate = String(win.state?.runComparison?.candidateRunId || "");
    if (!baseline || !candidate || baseline === candidate) {
      setStatusMessage({
        text: bilingual(
          lang,
          "选择两个不同的 Run 后再保存。",
          "Choose two different Runs before saving.",
        ),
        error: true,
      });
      return;
    }
    setSavePairwiseName(
      `${memberName({ run_id: baseline })} vs ${memberName({ run_id: candidate })}`,
    );
    setSavePairwiseModalOpen(true);
  };

  const handleConfirmSavePairwise = () =>
    void runAction("save-pairwise", async () => {
      const win = window as unknown as LegacyWindowBridge;
      const baseline = String(win.state?.runComparison?.baselineRunId || "");
      const candidate = String(win.state?.runComparison?.candidateRunId || "");
      const trimmed = savePairwiseName.trim();
      if (!trimmed) return;
      const created = await apiRequest<CollectionDetail>("/api/run-comparison/save-collection", {
        method: "POST",
        headers: { "Idempotency-Key": makeUuid() },
        body: { baseline_run_id: baseline, candidate_run_id: candidate, name: trimmed },
      });
      setSavePairwiseModalOpen(false);
      setSelectedCollectionId(created.id);
      setSelectedRevision(Number(created.current_revision || 1));
      await queryClient.invalidateQueries({ queryKey: ["run-collections-list"] });
      setStatusMessage({
        text: bilingual(
          lang,
          "Pairwise 已按基线、新 Run 顺序保存。",
          "Pairwise saved in baseline/candidate order.",
        ),
        error: false,
      });
    });

  const handleEvaluate = () =>
    void runAction("evaluate", async () => {
      if (!detail?.id) {
        throw new Error(
          bilingual(lang, "请先选择或创建 Collection。", "Select or create a Collection first."),
        );
      }
      const body: Record<string, unknown> = {
        collection_id: detail.id,
        collection_revision: Number(selectedRevision || detail.current_revision),
        baselines: baselinesParam,
        workset_id: worksetId.trim(),
        reference_type: referenceType,
        reference_id: referenceId.trim(),
        selection_source_run_id: selectionSourceRunId.trim(),
      };
      if (comparisonRefRunId.trim()) {
        body.comparison_reference_run_id = comparisonRefRunId.trim();
      }
      if (referenceType === "label_result" && activeScopes.length > 1) {
        body.reference_ids = Object.fromEntries(
          activeScopes
            .map((scope) => [scope, String(scopeLabelRefs[scope] || "").trim()])
            .filter(([, val]) => Boolean(val)),
        );
        delete body.reference_id;
      }
      const result = await apiRequest<EvaluationPayload>("/api/run-evaluations", {
        method: "POST",
        headers: { "Idempotency-Key": makeUuid() },
        body,
      });
      setEvaluationId(result.id);
      setEvalPage(Number(result.page || 1));
      setEvalSearch("");
      setEvalSearchDraft("");
      queryClient.setQueryData(["run-collection-evaluation", result.id, 1, ""], result);
      await queryClient.invalidateQueries({
        queryKey: ["run-collection-eval-history", detail.id],
      });
      syncUrl(
        {
          collectionId: detail.id,
          revision: Number(selectedRevision || detail.current_revision),
          evaluationId: result.id,
          page: 1,
          search: "",
          refRunId: result.comparison_reference_run_id,
        },
        "push",
      );
      setStatusMessage({
        text: bilingual(
          lang,
          "Evaluation Context 已冻结并保存。",
          "Evaluation Context frozen and saved.",
        ),
        error: false,
      });
    });

  const handleCreateReviewArtifact = (
    endpoint: "labeling-campaign" | "model-review-group",
    label: string,
  ) =>
    void runAction(endpoint, async () => {
      if (!evaluation?.id) {
        throw new Error(
          bilingual(lang, "请先冻结并完成一次 Evaluation。", "Freeze an Evaluation Context first."),
        );
      }
      const assignees = taskAssignees
        .split(/[\s,，;；]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      if (!assignees.length) {
        throw new Error(
          bilingual(
            lang,
            "填写至少一个已启用的管理员分配对象。",
            "Enter at least one enabled assignee.",
          ),
        );
      }
      const result = await apiRequest<{
        campaign?: { id?: string; campaign?: { id?: string } };
        group?: { id?: string };
      }>(`/api/run-evaluations/${encodeURIComponent(evaluation.id)}/${endpoint}`, {
        method: "POST",
        headers: { "Idempotency-Key": makeUuid() },
        body: {
          name: `${detail?.name || "Evaluation"} · ${label}`,
          assignees,
          run_ids: (evaluation.members || []).map((m) => m.run_id),
        },
      });
      const createdId =
        result.campaign?.campaign?.id || result.campaign?.id || result.group?.id || "created";
      setStatusMessage({ text: `${label}: ${createdId}`, error: false });
    });

  if (!active) return null;

  const multiLabelScope = referenceType === "label_result" && activeScopes.length > 1;
  const scopeSnapshots = evaluation?.reference?.snapshot?.scope_snapshots || [];
  const scopeProvenance = scopeSnapshots
    .map(
      (item) =>
        `${item.baseline_scope || ""}: ${item.id || ""} · ${String(item.content_sha256 || "").slice(0, 16)} · ${Number(item.member_count || 0)}`,
    )
    .join(" | ");

  return (
    <div
      className="run-collections-dedicated-host ra-run-collections-root"
      data-react-island="run-collections"
    >
      <section className="page-card run-collection-workbench" id="runCollectionsWorkbench">
        <div className="run-collection-heading">
          <div>
            <h2>{bilingual(lang, "Multi-run evaluation", "Multi-run evaluation")}</h2>
            <p className="muted">
              {bilingual(
                lang,
                "选择多个 Run 和 Case 范围，生成可复现的模型评测。",
                "Choose multiple Runs and a Case range for a reproducible evaluation.",
              )}
            </p>
          </div>
          {canWrite ? (
            <button
              className="button button-quiet"
              id="comparisonSaveCollectionButton"
              type="button"
              disabled={busyAction === "save-pairwise"}
              onClick={handleOpenSavePairwise}
            >
              {bilingual(lang, "将 Pairwise 保存为 评测项目", "Save pairwise as project")}
            </button>
          ) : null}
        </div>

        <ol
          className="multi-run-step-guide"
          aria-label={bilingual(lang, "多 Run 评测步骤", "Multi-run evaluation steps")}
        >
          <li className="is-active">
            <span>1</span>
            <b>{bilingual(lang, "新建评测", "Create project")}</b>
          </li>
          <li>
            <span>2</span>
            <b>{bilingual(lang, "选择多个 Run", "Select Runs")}</b>
          </li>
          <li>
            <span>3</span>
            <b>{bilingual(lang, "选择数据集和 Case 范围", "Select dataset & Cases")}</b>
          </li>
          <li>
            <span>4</span>
            <b>{bilingual(lang, "选择 GT / 标注版本", "Select GT / Label snapshot")}</b>
          </li>
          <li>
            <span>5</span>
            <b>{bilingual(lang, "生成并查看结果", "Freeze & inspect results")}</b>
          </li>
        </ol>

        <div className="run-collection-toolbar">
          <div className="ra-collection-field">
            <span>{bilingual(lang, "评测项目", "Evaluation project")}</span>
            <UiSelect
              id="runCollectionSelect"
              value={selectedCollectionId}
              options={collectionOptions}
              ariaLabel={bilingual(lang, "评测项目", "Evaluation project")}
              onChange={(val) => {
                setSelectedCollectionId(val);
                setEvaluationId("");
                setSelectedRevision(0);
                syncUrl({ collectionId: val }, "push");
              }}
            />
          </div>

          <div className="ra-collection-field">
            <span>{bilingual(lang, "项目版本", "Project version")}</span>
            <UiSelect
              id="runCollectionRevisionSelect"
              value={selectedRevision ? String(selectedRevision) : ""}
              options={revisionOptions}
              disabled={!revisionOptions.length}
              ariaLabel={bilingual(lang, "项目版本", "Project version")}
              onChange={(val) => {
                const rev = Number(val || 0);
                setSelectedRevision(rev);
                syncUrl({ collectionId: selectedCollectionId, revision: rev }, "push");
              }}
            />
          </div>

          <label className="run-collection-name-field">
            <span>{bilingual(lang, "名称", "Name")}</span>
            <input
              id="runCollectionName"
              maxLength={160}
              autoComplete="off"
              disabled={!canWrite}
              placeholder={bilingual(lang, "评测项目名称", "Project name")}
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
            />
          </label>

          <label className="run-collection-name-field">
            <span>{bilingual(lang, "说明", "Description")}</span>
            <input
              id="runCollectionDescription"
              maxLength={2000}
              autoComplete="off"
              disabled={!canWrite}
              value={descInput}
              onChange={(e) => setDescInput(e.target.value)}
            />
          </label>

          {canWrite ? (
            <button
              className={`button button-quiet${busyAction === "rename" ? " is-loading" : ""}`}
              id="runCollectionRenameButton"
              type="button"
              disabled={busyAction === "rename"}
              onClick={handleRename}
            >
              {bilingual(lang, "只改名称/说明", "Rename metadata")}
            </button>
          ) : null}

          <button
            className="button button-quiet"
            id="runCollectionRefreshButton"
            type="button"
            onClick={() => {
              void queryClient.invalidateQueries({ queryKey: ["run-collections-list"] });
              if (selectedCollectionId) {
                void queryClient.invalidateQueries({
                  queryKey: ["run-collection-detail", selectedCollectionId],
                });
                void queryClient.invalidateQueries({
                  queryKey: ["run-collection-eval-history", selectedCollectionId],
                });
              }
            }}
          >
            {bilingual(lang, "刷新", "Refresh")}
          </button>
        </div>

        <p className="muted run-collection-meta-note">
          {bilingual(
            lang,
            "改名称不会创建新的项目版本；调整成员顺序或成员后，点击“保存项目版本”。历史评测固定指向原项目版本。",
            "Renaming does not create a revision. Member edits and ordering changes require “Save project version”; prior evaluations keep their original revision.",
          )}
        </p>

        <div className="run-collection-member-editor">
          <div className="run-collection-member-tools">
            <div className="ra-collection-field ra-collection-add-run-field">
              <span>{bilingual(lang, "添加 Run", "Add Run")}</span>
              <UiSelect
                id="runCollectionAddRun"
                value={addRunId}
                options={addRunOptions}
                disabled={!canWrite}
                ariaLabel={bilingual(lang, "添加 Run", "Add Run")}
                onChange={setAddRunId}
              />
            </div>

            {canWrite ? (
              <>
                <button
                  className="button button-quiet"
                  id="runCollectionAddRunButton"
                  type="button"
                  onClick={handleAddMember}
                >
                  {bilingual(lang, "添加", "Add")}
                </button>
                <button
                  className={`button button-primary${busyAction === "append" ? " is-loading" : ""}`}
                  id="runCollectionAppendRevisionButton"
                  type="button"
                  disabled={busyAction === "append"}
                  onClick={handleAppendRevision}
                >
                  {bilingual(lang, "保存项目版本", "Save project version")}
                </button>
              </>
            ) : null}

            <span className="muted" id="runCollectionMemberHash">
              {activeRevisionObj
                ? `members ${String(activeRevisionObj.members_sha256 || "").slice(0, 16)}`
                : ""}
            </span>
          </div>

          <ol id="runCollectionMembers" className="run-collection-members">
            {draftMembers.map((member, index) => (
              <li
                key={`${member.run_id}-${index}`}
                className={`run-collection-member${
                  member.available_now === false ? " is-unavailable" : ""
                }`}
              >
                <span className="run-collection-member-order">{index + 1}</span>
                <span className="run-collection-member-info">
                  <strong>{memberName(member)}</strong>
                  <small>
                    {member.run_id}
                    {member.role ? ` · ${member.role}` : ""}
                    {member.available_now === false
                      ? ` · ${bilingual(lang, "当前不可用", "Unavailable now")}`
                      : ""}
                  </small>
                </span>
                {member.is_reference ? (
                  <span className="run-collection-reference-badge">
                    {bilingual(lang, "参考 Run", "reference")}
                  </span>
                ) : null}
                {canWrite ? (
                  <span className="run-collection-member-actions">
                    <button
                      className="button button-quiet"
                      type="button"
                      aria-label={bilingual(lang, "上移", "Move up")}
                      disabled={index === 0}
                      onClick={() => handleMoveMember(index, -1)}
                    >
                      ↑
                    </button>
                    <button
                      className="button button-quiet"
                      type="button"
                      aria-label={bilingual(lang, "下移", "Move down")}
                      disabled={index === draftMembers.length - 1}
                      onClick={() => handleMoveMember(index, 1)}
                    >
                      ↓
                    </button>
                    <button
                      className="button button-quiet"
                      type="button"
                      onClick={() => handleToggleRefMember(index)}
                    >
                      {member.is_reference
                        ? bilingual(lang, "取消参考", "Unset reference")
                        : bilingual(lang, "设为参考", "Set reference")}
                    </button>
                    <button
                      className="button button-quiet"
                      type="button"
                      aria-label={bilingual(lang, "移除", "Remove")}
                      onClick={() => handleRemoveMember(index)}
                    >
                      ×
                    </button>
                  </span>
                ) : null}
              </li>
            ))}
          </ol>
        </div>

        {canWrite ? (
          <details className="run-collection-create-details" id="runCollectionCreateDetails">
            <summary>{bilingual(lang, "创建评测项目", "Create evaluation project")}</summary>
            <div className="run-collection-create-row">
              <label>
                <span>{bilingual(lang, "评测项目名称", "Project name")}</span>
                <input
                  id="runCollectionCreateName"
                  maxLength={160}
                  autoComplete="off"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                />
              </label>
              <button
                className={`button button-primary${busyAction === "create" ? " is-loading" : ""}`}
                id="runCollectionCreateButton"
                type="button"
                disabled={busyAction === "create"}
                onClick={handleCreateCollection}
              >
                {bilingual(lang, "用当前成员创建", "Create from current members")}
              </button>
            </div>
          </details>
        ) : null}

        <details className="run-collection-history">
          <summary>{bilingual(lang, "项目版本历史", "Project version history")}</summary>
          <ol id="runCollectionHistory">
            {(detail?.history || []).map((item) => (
              <li key={item.revision}>
                <button
                  className="button button-quiet"
                  type="button"
                  onClick={() => {
                    setSelectedRevision(Number(item.revision));
                    syncUrl(
                      { collectionId: selectedCollectionId, revision: Number(item.revision) },
                      "push",
                    );
                  }}
                >
                  r{Number(item.revision)} · {Number(item.members?.length || 0)} Runs ·{" "}
                  {String(item.content_sha256 || "").slice(0, 16)}
                </button>
                <small>
                  {item.created_by || ""} · {item.created_at || ""}
                </small>
              </li>
            ))}
          </ol>
        </details>

        <details className="run-collection-audit">
          <summary>{bilingual(lang, "项目审计记录", "Project audit")}</summary>
          <ol id="runCollectionAudit">
            {(detail?.audit || []).map((item, idx) => (
              <li key={idx}>
                <strong>{item.action || "event"}</strong>
                <small>
                  r{Number(item.revision || 0)} · {item.actor || ""} ({item.actor_source || ""}
                  {item.actor_verified ? ", verified" : ", unverified"}) · {item.created_at || ""}
                </small>
                {item.context_id ? <small>context {item.context_id}</small> : null}
              </li>
            ))}
          </ol>
        </details>

        <div className="run-collection-evaluation-controls">
          <div className="ra-collection-field">
            <span>{bilingual(lang, "评分参考", "Scoring reference")}</span>
            <UiSelect
              id="runCollectionReferenceType"
              value={referenceType}
              options={referenceTypeOptions}
              disabled={!canWrite}
              ariaLabel={bilingual(lang, "评分参考", "Scoring reference")}
              onChange={(val) => setReferenceType(val as "gt" | "label_result")}
            />
          </div>

          <label>
            <span>
              {bilingual(
                lang,
                "参考 ID（Label snapshot 可选）",
                "Reference ID (optional for Label snapshot set)",
              )}
            </span>
            <input
              id="runCollectionReferenceId"
              disabled={!canWrite || referenceType === "gt"}
              placeholder={
                referenceType === "label_result"
                  ? "label-result-…"
                  : bilingual(lang, "标注版本 ID", "Label snapshot ID")
              }
              value={referenceId}
              onChange={(e) => setReferenceId(e.target.value)}
            />
          </label>

          {multiLabelScope ? (
            <div id="runCollectionLabelReferenceSet" className="run-collection-label-reference-set">
              {activeScopes.map((scope) => (
                <label key={scope}>
                  <span>{scope} Label snapshot</span>
                  <input
                    value={scopeLabelRefs[scope] || ""}
                    disabled={!canWrite}
                    placeholder="label-result-…"
                    autoComplete="off"
                    onChange={(e) =>
                      setScopeLabelRefs((prev) => ({ ...prev, [scope]: e.target.value }))
                    }
                  />
                </label>
              ))}
            </div>
          ) : null}

          <div className="ra-collection-field">
            <span>{bilingual(lang, "比较基准 Run", "Transition reference Run")}</span>
            <UiSelect
              id="runCollectionComparisonReference"
              value={comparisonRefRunId}
              options={comparisonRefOptions}
              disabled={!canWrite}
              ariaLabel={bilingual(lang, "比较基准 Run", "Transition reference Run")}
              onChange={setComparisonRefRunId}
            />
          </div>

          <label>
            <span>{bilingual(lang, "Case 范围 ID（可选）", "Case range ID (optional)")}</span>
            <input
              id="runCollectionWorksetId"
              disabled={!canWrite}
              placeholder="workset-…"
              value={worksetId}
              onChange={(e) => setWorksetId(e.target.value)}
            />
          </label>

          <div className="ra-collection-field">
            <span>
              {bilingual(
                lang,
                "按来源 Run 筛选范围（可选）",
                "Filter Workset by source Run (optional)",
              )}
            </span>
            <UiSelect
              id="runCollectionSelectionSourceRun"
              value={selectionSourceRunId}
              options={selectionSourceOptions}
              disabled={!canWrite}
              ariaLabel={bilingual(
                lang,
                "按来源 Run 筛选范围",
                "Filter Workset by source Run",
              )}
              onChange={setSelectionSourceRunId}
            />
          </div>

          {canWrite ? (
            <button
              className={`button button-primary${busyAction === "evaluate" ? " is-loading" : ""}`}
              id="runCollectionEvaluateButton"
              type="button"
              disabled={busyAction === "evaluate"}
              onClick={handleEvaluate}
            >
              {bilingual(lang, "冻结并评估", "Freeze and evaluate")}
            </button>
          ) : null}
        </div>

        {!canWrite ? (
          <p className="muted run-collection-readonly-note" id="runCollectionReadonlyNote">
            {bilingual(
              lang,
              "当前为只读会话；可以查看历史和导出，管理与冻结操作需要已验证管理员。",
              "Read-only session: history and export are available; management and freeze actions require a verified administrator.",
            )}
          </p>
        ) : null}

        <details className="run-collection-evaluation-history">
          <summary>{bilingual(lang, "评测快照历史", "Evaluation snapshot history")}</summary>
          <ol id="runCollectionEvaluationHistory">
            {(evalHistoryQuery.data?.items || []).map((item) => (
              <li key={item.id}>
                <button
                  className="button button-quiet"
                  type="button"
                  onClick={() => {
                    setEvaluationId(item.id);
                    setEvalPage(1);
                    setEvalSearch("");
                    setEvalSearchDraft("");
                    syncUrl(
                      {
                        collectionId: selectedCollectionId,
                        revision: Number(item.collection_revision),
                        evaluationId: item.id,
                        page: 1,
                        search: "",
                      },
                      "push",
                    );
                  }}
                >
                  r{Number(item.collection_revision)} · {item.reference_type} ·{" "}
                  {String(item.context_sha256 || "").slice(0, 16)}
                </button>
                <small>
                  {item.created_at || ""} · {String(item.workset_sha256 || "").slice(0, 12)}
                </small>
              </li>
            ))}
          </ol>
        </details>

        <div className="run-collection-integrations">
          <label>
            <span>
              {bilingual(lang, "管理员分配对象（逗号分隔）", "Admin assignees (comma separated)")}
            </span>
            <input
              id="runCollectionTaskAssignees"
              disabled={!canWrite}
              placeholder="user1, user2"
              value={taskAssignees}
              onChange={(e) => setTaskAssignees(e.target.value)}
            />
          </label>
          {canWrite ? (
            <>
              <button
                className="button button-quiet"
                id="runCollectionCreateLabelingCampaign"
                type="button"
                disabled={busyAction === "labeling-campaign"}
                onClick={() =>
                  handleCreateReviewArtifact(
                    "labeling-campaign",
                    bilingual(lang, "创建标注实验", "Labeling experiment"),
                  )
                }
              >
                {bilingual(lang, "创建标注实验", "Create labeling experiment")}
              </button>
              <button
                className="button button-quiet"
                id="runCollectionCreateModelReviewGroup"
                type="button"
                disabled={busyAction === "model-review-group"}
                onClick={() =>
                  handleCreateReviewArtifact(
                    "model-review-group",
                    bilingual(lang, "复核任务", "Review tasks"),
                  )
                }
              >
                {bilingual(lang, "创建每 Run 复核任务", "Create per-Run review tasks")}
              </button>
            </>
          ) : null}
        </div>

        {evaluation ? (
          <div id="runCollectionEvaluation" className="run-collection-evaluation">
            <div id="runCollectionProvenance" className="run-collection-provenance">
              <strong>
                {bilingual(lang, "已冻结的评测快照", "Frozen evaluation snapshot")} ·{" "}
                {evaluation.id}
              </strong>
              {evaluation.selection_bias_warning ? (
                <strong className="run-collection-bias-warning">
                  {evaluation.selection_bias_warning}
                </strong>
              ) : null}
              <span>
                {bilingual(lang, "Case 范围", "Case range")} ·{" "}
                {Number(evaluation.summary?.workset_count || 0)} Issues ·{" "}
                {(evaluation.workset?.baseline_scopes || []).join(", ")}
              </span>
              <details className="run-collection-technical-details">
                <summary>
                  {bilingual(lang, "版本与技术详情", "Version and technical details")}
                </summary>
                <span>
                  Project version r{Number(evaluation.collection_revision)} ·{" "}
                  {evaluation.collection_sha256 || ""}
                </span>
                <span>
                  Case range {evaluation.workset?.workset_id || ""} ·{" "}
                  {evaluation.workset_sha256 || ""}
                </span>
                <span>Frozen references {scopeProvenance}</span>
                <span>
                  {evaluation.reference?.type || ""} {evaluation.reference?.id || ""} ·{" "}
                  {evaluation.reference?.sha256 || ""}
                </span>
                <span>
                  Policy {evaluation.scoring_policy_version || ""} ·{" "}
                  {evaluation.scoring_policy_sha256 || ""}
                </span>
                <span>
                  Exclusion {evaluation.exclusion?.sha256 || ""} · snapshot{" "}
                  {evaluation.context_sha256 || ""}
                </span>
              </details>
            </div>

            <div id="runCollectionMetrics" className="run-collection-metrics">
              {(evaluation.summary?.runs || []).map((item) => {
                const confusionRows = item.confusion || [];
                const confusionCols = Object.keys(confusionRows[0]?.cells || {});
                return (
                  <article className="run-collection-metric-card" key={item.run_id}>
                    <strong>{item.run?.name || item.run_id}</strong>
                    <span>
                      {bilingual(lang, "准确率", "Accuracy")} <b>{percentage(item.accuracy)}</b> ·{" "}
                      {Number(item.correct_count || 0)}/{Number(item.reference_denominator || 0)}
                    </span>
                    <span>
                      {bilingual(lang, "Union 准确率覆盖", "Union accuracy coverage")}{" "}
                      {percentage(item.coverage)} · denominator{" "}
                      {Number(item.pairwise_union_denominator || item.reference_denominator || 0)}
                    </span>
                    <span>
                      {bilingual(
                        lang,
                        "全 valid reference supported 覆盖",
                        "Supported coverage over all valid reference",
                      )}{" "}
                      {percentage(item.supported_coverage)} · {Number(item.supported_count || 0)} /{" "}
                      {Number(item.valid_reference_count || 0)}
                    </span>
                    <span>
                      {bilingual(lang, "缺失 / UNKNOWN", "Absent / UNKNOWN")}{" "}
                      {Number(item.absent_count || item.absent_prediction_count || 0)} /{" "}
                      {Number(item.unknown_count || 0)}
                    </span>
                    {item.transitions_vs_reference ? (
                      <span>
                        P2P {Number(item.transitions_vs_reference.P2P || 0)} · P2F{" "}
                        {Number(item.transitions_vs_reference.P2F || 0)} · F2P{" "}
                        {Number(item.transitions_vs_reference.F2P || 0)} · F2F{" "}
                        {Number(item.transitions_vs_reference.F2F || 0)}
                      </span>
                    ) : null}
                    {confusionRows.length ? (
                      <details className="run-collection-confusion">
                        <summary>{bilingual(lang, "混淆矩阵", "Confusion matrix")}</summary>
                        <div className="run-collection-mini-matrix-wrap">
                          <table className="run-collection-mini-matrix">
                            <thead>
                              <tr>
                                <th>Ref</th>
                                {confusionCols.map((col) => (
                                  <th key={col}>{col}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {confusionRows.map((row) => (
                                <tr key={row.reference_label}>
                                  <th>{row.reference_label}</th>
                                  {confusionCols.map((col) => (
                                    <td key={col}>{Number(row.cells?.[col] || 0)}</td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    ) : null}
                    {item.available_now === false ? (
                      <em>
                        {bilingual(
                          lang,
                          "Run 当前已删除；此评估使用冻结输出。",
                          "Run is unavailable now; this evaluation uses frozen outputs.",
                        )}
                      </em>
                    ) : null}
                  </article>
                );
              })}
            </div>

            <div className="run-collection-table-wrap">
              <table className="run-collection-table">
                <thead id="runCollectionTableHead">
                  <tr>
                    <th>Issue</th>
                    <th>{bilingual(lang, "共享标签状态", "Shared label state")}</th>
                    <th>{bilingual(lang, "参考标签", "Reference")}</th>
                    {(evaluation.members || []).map((m) => (
                      <th key={m.run_id}>
                        {m.run?.name || m.run_id}
                        {m.is_reference ? ` · ${bilingual(lang, "基准", "reference")}` : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody id="runCollectionTableBody">
                  {(evaluation.items || []).map((item) => (
                    <tr key={item.issue_id} className={item.excluded ? "is-excluded" : ""}>
                      <th>
                        {item.issue_id}
                        {item.excluded ? (
                          <small>{bilingual(lang, "已排除", "excluded")}</small>
                        ) : null}
                      </th>
                      <td>
                        <span className="run-collection-shared-label">
                          {item.shared_label?.state || "none"}
                          {item.shared_label?.expected_output
                            ? ` · ${item.shared_label.expected_output}`
                            : ""}
                        </span>
                        <small>{item.shared_label?.method || ""}</small>
                      </td>
                      <td>
                        {item.reference_label || "—"}
                        {!item.reference_valid ? (
                          <small>{bilingual(lang, "无有效参考", "no valid reference")}</small>
                        ) : null}
                      </td>
                      {(evaluation.members || []).map((member) => {
                        const pred = item.predictions?.[member.run_id] || {};
                        const cls = pred.correct
                          ? "is-correct"
                          : pred.label === "NONE"
                            ? "is-missing"
                            : "is-error";
                        const reviews = Array.isArray(pred.model_reviews) ? pred.model_reviews : [];
                        const reviewSummary = reviews
                          .map((r) => `${r.status || "pending"} · ${r.reviewer || "—"}`)
                          .join(" / ");
                        return (
                          <td key={member.run_id}>
                            <span className={`run-collection-prediction ${cls}`}>
                              {pred.label || "NONE"}
                            </span>
                            {pred.reason ? (
                              <small title={pred.reason}>{pred.reason.slice(0, 100)}</small>
                            ) : null}
                            <small
                              className={`run-collection-review-status${
                                reviewSummary ? "" : " is-unreviewed"
                              }`}
                            >
                              review {reviewSummary || bilingual(lang, "暂无", "none")}
                            </small>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="run-collection-pagination">
              <button
                className="button button-quiet"
                id="runCollectionPagePrevious"
                type="button"
                disabled={Number(evaluation.page || 1) <= 1}
                onClick={() => {
                  const next = Math.max(1, evalPage - 1);
                  setEvalPage(next);
                  syncUrl(
                    {
                      collectionId: selectedCollectionId,
                      revision: selectedRevision,
                      evaluationId,
                      page: next,
                      search: evalSearch,
                    },
                    "push",
                  );
                }}
              >
                ‹
              </button>
              <span id="runCollectionPageSummary">
                {Number(evaluation.page || 1)} / {Number(evaluation.page_count || 1)} ·{" "}
                {Number(evaluation.total || 0)} Issues
              </span>
              <button
                className="button button-quiet"
                id="runCollectionPageNext"
                type="button"
                disabled={Number(evaluation.page || 1) >= Number(evaluation.page_count || 1)}
                onClick={() => {
                  const next = evalPage + 1;
                  setEvalPage(next);
                  syncUrl(
                    {
                      collectionId: selectedCollectionId,
                      revision: selectedRevision,
                      evaluationId,
                      page: next,
                      search: evalSearch,
                    },
                    "push",
                  );
                }}
              >
                ›
              </button>
              <label>
                <span>{bilingual(lang, "Issue 搜索", "Issue search")}</span>
                <input
                  id="runCollectionSearch"
                  maxLength={128}
                  autoComplete="off"
                  value={evalSearchDraft}
                  onChange={(e) => {
                    const val = e.target.value;
                    setEvalSearchDraft(val);
                    if (searchTimerRef.current !== null) {
                      window.clearTimeout(searchTimerRef.current);
                    }
                    searchTimerRef.current = window.setTimeout(() => {
                      const trimmed = val.trim().slice(0, 128);
                      setEvalSearch(trimmed);
                      setEvalPage(1);
                      syncUrl(
                        {
                          collectionId: selectedCollectionId,
                          revision: selectedRevision,
                          evaluationId,
                          page: 1,
                          search: trimmed,
                        },
                        "push",
                      );
                    }, 250);
                  }}
                />
              </label>
              <a
                className="button button-quiet"
                id="runCollectionExport"
                href={withWorkbenchBase(
                  `/api/run-evaluations/${encodeURIComponent(evaluation.id)}/export`,
                )}
                target="_blank"
                rel="noopener noreferrer"
              >
                {bilingual(lang, "导出 JSON", "Export JSON")}
              </a>
            </div>
          </div>
        ) : null}

        <p
          className={`muted${statusMessage.error ? " error" : ""}`}
          id="runCollectionStatus"
          role="status"
        >
          {statusMessage.text}
        </p>
      </section>

      <ModalDialog
        open={savePairwiseModalOpen}
        title={bilingual(lang, "保存为评测项目", "Save as evaluation project")}
        lang={lang}
        onClose={() => setSavePairwiseModalOpen(false)}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => setSavePairwiseModalOpen(false)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={!savePairwiseName.trim() || busyAction === "save-pairwise"}
              onClick={handleConfirmSavePairwise}
            >
              {bilingual(lang, "保存", "Save")}
            </button>
          </>
        }
      >
        <label>
          <span>{bilingual(lang, "评测项目名称", "Project name")}</span>
          <input
            type="text"
            maxLength={160}
            value={savePairwiseName}
            onChange={(e) => setSavePairwiseName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleConfirmSavePairwise();
              }
            }}
          />
        </label>
      </ModalDialog>
    </div>
  );
};
