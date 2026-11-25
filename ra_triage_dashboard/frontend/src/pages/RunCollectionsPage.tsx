import React, { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  formatCstTime,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import {
  DEFAULT_CASE_PAGE_SIZE,
  Pagination,
} from "../components/ui/Pagination";
import { StatusChip } from "../components/ui/StatusChip";
import { UiSelect } from "../components/ui/UiSelect";

interface CollectionSummary {
  id: string;
  name: string;
  description?: string;
  current_revision: number;
  metadata_revision?: number;
}

interface CollectionMember {
  run_id: string;
  role?: string;
  is_reference?: boolean;
  available_now?: boolean;
  run?: { id?: string; name?: string; source_name?: string };
}

interface CollectionRevision {
  revision: number;
  content_sha256?: string;
  members_sha256?: string;
  created_by?: string;
  created_at?: string;
  members: CollectionMember[];
}

interface CollectionDetail extends CollectionSummary {
  current?: CollectionRevision;
  history: CollectionRevision[];
  audit?: Array<{
    action?: string;
    revision?: number;
    actor?: string;
    actor_source?: string;
    actor_verified?: boolean;
    created_at?: string;
    context_id?: string;
  }>;
}

interface EvaluationHistoryItem {
  id: string;
  collection_revision: number;
  reference_type: string;
  context_sha256?: string;
  workset_sha256?: string;
  created_at?: string;
}

interface EvaluationDetail {
  id: string;
  collection_id: string;
  collection_revision: number;
  collection_sha256?: string;
  workset_sha256?: string;
  context_sha256?: string;
  selection_bias_warning?: string;
  page: number;
  page_count: number;
  total: number;
  workset?: { workset_id?: string; baseline_scopes?: string[] };
  reference?: { type?: string; id?: string; sha256?: string };
  members: CollectionMember[];
  summary?: {
    workset_count?: number;
    runs?: Array<{
      run_id: string;
      run?: { name?: string };
      accuracy?: number;
      correct_count?: number;
      reference_denominator?: number;
      coverage?: number;
      supported_coverage?: number;
      supported_count?: number;
      valid_reference_count?: number;
      absent_count?: number;
      unknown_count?: number;
      available_now?: boolean;
      transitions_vs_reference?: Record<string, number>;
      confusion?: Array<{ reference_label: string; cells: Record<string, number> }>;
    }>;
  };
  items: Array<{
    issue_id: string;
    excluded?: boolean;
    reference_label?: string;
    reference_valid?: boolean;
    shared_label?: { state?: string; expected_output?: string; method?: string };
    predictions?: Record<
      string,
      {
        label?: string;
        correct?: boolean;
        reason?: string;
      }
    >;
  }>;
}

interface ModelRunSummary {
  id: string;
  name?: string;
  source_name?: string;
}

function pct(v: number | undefined | null): string {
  return `${(Number(v || 0) * 100).toFixed(1)}%`;
}

export interface RunCollectionsPageProps {
  active: boolean;
  lang: UiLanguage;
  isAdmin: boolean;
  selectedBaselines: string[];
}

export const RunCollectionsPage: React.FC<RunCollectionsPageProps> = ({
  active,
  lang,
  isAdmin,
  selectedBaselines,
}) => {
  const queryClient = useQueryClient();
  const initialParams = useMemo(
    () => new URLSearchParams(typeof window !== "undefined" ? window.location.search : ""),
    [],
  );

  const [collectionId, setCollectionId] = useState(
    () => initialParams.get("collection_id") || initialParams.get("collection") || "",
  );
  const [selectedRevision, setSelectedRevision] = useState<number>(
    () => Number(initialParams.get("collection_revision") || initialParams.get("revision") || 0),
  );
  const [evaluationId, setEvaluationId] = useState(
    () => initialParams.get("evaluation_id") || initialParams.get("context") || "",
  );
  const [evalPage, setEvalPage] = useState(
    () => Math.max(1, Number(initialParams.get("evaluation_page") || initialParams.get("page") || 1)),
  );
  const [evalPageSize, setEvalPageSize] = useState(DEFAULT_CASE_PAGE_SIZE);
  const [evalSearchInput, setEvalSearchInput] = useState(
    () => initialParams.get("evaluation_q") || initialParams.get("q") || "",
  );
  const [evalSearch, setEvalSearch] = useState(
    () => initialParams.get("evaluation_q") || initialParams.get("q") || "",
  );

  // Admin draft editing state
  const [draftMembers, setDraftMembers] = useState<CollectionMember[]>([]);
  const [addRunId, setAddRunId] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newFirstRun, setNewFirstRun] = useState("");
  const [statusMessage, setStatusMessage] = useState<{ text: string; error?: boolean } | null>(null);

  const collectionsQuery = useQuery<{ items: CollectionSummary[] }>({
    queryKey: ["run-collections-list"],
    queryFn: ({ signal }) => apiRequest("/api/run-collections", { signal }),
    enabled: active,
    staleTime: 30_000,
  });

  const runsQuery = useQuery<{ items: ModelRunSummary[] }>({
    queryKey: ["model-runs-for-collections"],
    queryFn: ({ signal }) => apiRequest("/api/model-runs", { signal }),
    enabled: active,
    staleTime: 60_000,
  });

  const collections = collectionsQuery.data?.items || [];
  const effectiveCollectionId = useMemo(() => {
    if (collectionId && collections.some((c) => c.id === collectionId)) return collectionId;
    return collections[0]?.id || "";
  }, [collectionId, collections]);

  const detailQuery = useQuery<CollectionDetail>({
    queryKey: ["run-collection-detail", effectiveCollectionId],
    queryFn: ({ signal }) =>
      apiRequest(`/api/run-collections/${encodeURIComponent(effectiveCollectionId)}`, { signal }),
    enabled: active && Boolean(effectiveCollectionId),
    staleTime: 25_000,
  });

  const evalHistoryQuery = useQuery<{ items: EvaluationHistoryItem[] }>({
    queryKey: ["run-collection-eval-history", effectiveCollectionId],
    queryFn: ({ signal }) =>
      apiRequest(
        `/api/run-evaluations?collection_id=${encodeURIComponent(effectiveCollectionId)}&limit=100`,
        { signal },
      ),
    enabled: active && Boolean(effectiveCollectionId),
    staleTime: 25_000,
  });

  const detail = detailQuery.data;
  const effectiveRevision = useMemo(() => {
    if (!detail) return 0;
    if (selectedRevision && detail.history?.some((h) => h.revision === selectedRevision)) {
      return selectedRevision;
    }
    return detail.current_revision;
  }, [detail, selectedRevision]);

  const activeRevisionObj = useMemo(
    () => detail?.history?.find((h) => h.revision === effectiveRevision) || detail?.current || null,
    [detail, effectiveRevision],
  );

  useEffect(() => {
    setDraftMembers((activeRevisionObj?.members || []).map((m) => ({ ...m })));
  }, [activeRevisionObj]);

  const evalHistory = evalHistoryQuery.data?.items || [];
  const effectiveEvaluationId = useMemo(() => {
    if (evaluationId) return evaluationId;
    return evalHistory[0]?.id || "";
  }, [evaluationId, evalHistory]);

  const evaluationQuery = useQuery<EvaluationDetail>({
    queryKey: ["run-evaluation-detail", effectiveEvaluationId, evalPage, evalPageSize, evalSearch],
    queryFn: ({ signal }) => {
      const sp = new URLSearchParams({
        page: String(evalPage),
        page_size: String(evalPageSize),
        q: evalSearch,
      });
      return apiRequest(`/api/run-evaluations/${encodeURIComponent(effectiveEvaluationId)}?${sp}`, {
        signal,
      });
    },
    enabled: active && Boolean(effectiveEvaluationId),
    placeholderData: keepPreviousData,
    staleTime: 25_000,
  });

  const createCollectionMutation = useMutation({
    mutationFn: () =>
      apiRequest<CollectionDetail>("/api/run-collections", {
        method: "POST",
        headers: {
          "Idempotency-Key": `rc-create-${Date.now()}`,
        },
        body: {
          name: newName.trim(),
          description: newDesc.trim(),
          members: newFirstRun ? [{ run_id: newFirstRun, role: "baseline", is_reference: true }] : [],
        },
      }),
    onSuccess: (created) => {
      setCreateOpen(false);
      setNewName("");
      setNewDesc("");
      setNewFirstRun("");
      setCollectionId(created.id);
      setStatusMessage({
        text: bilingual(lang, `已创建项目：${created.name}`, `Created project: ${created.name}`),
      });
      void queryClient.invalidateQueries({ queryKey: ["run-collections-list"] });
    },
    onError: (err: Error) => setStatusMessage({ text: err.message, error: true }),
  });

  const appendRevisionMutation = useMutation({
    mutationFn: () =>
      apiRequest<CollectionDetail>(
        `/api/run-collections/${encodeURIComponent(effectiveCollectionId)}/revisions`,
        {
          method: "POST",
          headers: {
            "Idempotency-Key": `rc-rev-${effectiveCollectionId}-${Date.now()}`,
          },
          body: {
            expected_revision: detail?.current_revision || 0,
            members: draftMembers.map((m) => ({
              run_id: m.run_id,
              role: m.role || "",
              is_reference: Boolean(m.is_reference),
            })),
          },
        },
      ),
    onSuccess: (updated) => {
      setSelectedRevision(updated.current_revision);
      setStatusMessage({
        text: bilingual(
          lang,
          `已保存新版本 r${updated.current_revision}`,
          `Saved revision r${updated.current_revision}`,
        ),
      });
      void queryClient.invalidateQueries({ queryKey: ["run-collection-detail", effectiveCollectionId] });
      void queryClient.invalidateQueries({ queryKey: ["run-collections-list"] });
    },
    onError: (err: Error) => setStatusMessage({ text: err.message, error: true }),
  });

  const runEvaluationMutation = useMutation({
    mutationFn: () =>
      apiRequest<EvaluationDetail>("/api/run-evaluations", {
        method: "POST",
        headers: {
          "Idempotency-Key": `re-eval-${effectiveCollectionId}-${Date.now()}`,
        },
        body: {
          collection_id: effectiveCollectionId,
          collection_revision: effectiveRevision,
          baselines: selectedBaselines.join(","),
          reference_type: "gt",
        },
      }),
    onSuccess: (ev) => {
      setEvaluationId(ev.id);
      setEvalPage(1);
      setStatusMessage({
        text: bilingual(lang, `已生成冻结评测快照 ${ev.id}`, `Created frozen snapshot ${ev.id}`),
      });
      void queryClient.invalidateQueries({ queryKey: ["run-collection-eval-history", effectiveCollectionId] });
    },
    onError: (err: Error) => setStatusMessage({ text: err.message, error: true }),
  });

  const availableAddRuns = useMemo(() => {
    const existing = new Set(draftMembers.map((m) => m.run_id));
    return (runsQuery.data?.items || []).filter((r) => !existing.has(r.id));
  }, [runsQuery.data?.items, draftMembers]);

  const evaluation = evaluationQuery.data;

  return (
    <div className="ra-react-page ra-run-collections" data-react-island="run-collections">
      <div className="page-card ra-page-toolbar-card">
        <div className="ra-section-header">
          <div>
            <h2 className="ra-page-title">{bilingual(lang, "多 Run 冻结评测", "Multi-Run evaluation")}</h2>
            <p className="ra-page-subtitle">
              {bilingual(
                lang,
                "管理多 Run 评测项目与不可变版本快照，在统一冻结工作集上横向对比准确率、覆盖率与逐 Case 结论。",
                "Manage immutable multi-Run projects and frozen evaluation snapshots over a shared workset.",
              )}
            </p>
          </div>
          <div className="ra-toolbar-actions">
            {isAdmin && (
              <button
                type="button"
                className="button button-primary"
                onClick={() => setCreateOpen(true)}
              >
                {bilingual(lang, "新建评测项目", "New project")}
              </button>
            )}
            <button
              type="button"
              className="button button-quiet"
              onClick={() => {
                void collectionsQuery.refetch();
                void detailQuery.refetch();
                void evalHistoryQuery.refetch();
              }}
            >
              {bilingual(lang, "刷新", "Refresh")}
            </button>
          </div>
        </div>

        {!isAdmin && (
          <div className="ra-inline-notice">
            {bilingual(
              lang,
              "当前为只读视图；创建或修改评测项目及运行新快照需要管理员权限。",
              "Read-only view; administrator access is required to create or modify projects and run evaluations.",
            )}
          </div>
        )}

        {statusMessage && (
          <div className={`ra-inline-notice${statusMessage.error ? " is-error" : ""}`}>
            {statusMessage.text}
          </div>
        )}

        <div className="ra-filter-grid">
          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "评测项目", "Evaluation project")}</span>
            <UiSelect
              id="raRunCollectionSelect"
              value={effectiveCollectionId}
              disabled={collections.length === 0}
              options={collections.map((c) => ({
                value: c.id,
                label: `${c.name} · r${c.current_revision}`,
              }))}
              placeholder={bilingual(lang, "暂无评测项目", "No projects")}
              ariaLabel={bilingual(lang, "评测项目", "Evaluation project")}
              onChange={(next) => {
                setCollectionId(next);
                setSelectedRevision(0);
                setEvaluationId("");
                setEvalPage(1);
              }}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "项目版本", "Revision")}</span>
            <UiSelect
              id="raRunCollectionRevision"
              value={effectiveRevision ? String(effectiveRevision) : ""}
              disabled={!detail?.history?.length}
              options={(detail?.history || []).map((h) => ({
                value: String(h.revision),
                label: `r${h.revision} · ${(h.content_sha256 || "").slice(0, 10)}${h.revision === detail?.current_revision ? " · current" : ""}`,
              }))}
              ariaLabel={bilingual(lang, "项目版本", "Revision")}
              onChange={(next) => setSelectedRevision(Number(next))}
            />
          </div>

          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "历史评测快照", "Evaluation snapshot")}</span>
            <UiSelect
              id="raRunCollectionEvalSelect"
              value={effectiveEvaluationId}
              disabled={evalHistory.length === 0}
              options={evalHistory.map((ev) => ({
                value: ev.id,
                label: `r${ev.collection_revision} · ${ev.reference_type} · ${ev.id.slice(0, 12)}`,
              }))}
              placeholder={bilingual(lang, "暂无冻结快照", "No snapshots")}
              ariaLabel={bilingual(lang, "历史评测快照", "Evaluation snapshot")}
              onChange={(next) => {
                setEvaluationId(next);
                setEvalPage(1);
              }}
            />
          </div>
        </div>
      </div>

      {/* Member Runs Card */}
      {detail && (
        <section className="page-card ra-table-card">
          <div className="ra-card-header">
            <div>
              <h3>
                {detail.name} · r{effectiveRevision}
              </h3>
              {detail.description && <p className="muted">{detail.description}</p>}
            </div>
            {isAdmin && (
              <div className="ra-toolbar-actions">
                <button
                  type="button"
                  className="button button-quiet"
                  disabled={appendRevisionMutation.isPending || draftMembers.length === 0}
                  onClick={() => appendRevisionMutation.mutate()}
                >
                  {bilingual(lang, "保存为新版本", "Save revision")}
                </button>
                <button
                  type="button"
                  className="button button-primary"
                  disabled={runEvaluationMutation.isPending || draftMembers.length === 0}
                  onClick={() => runEvaluationMutation.mutate()}
                >
                  {runEvaluationMutation.isPending
                    ? bilingual(lang, "计算中…", "Running…")
                    : bilingual(lang, "生成冻结评测", "Run frozen evaluation")}
                </button>
              </div>
            )}
          </div>

          {draftMembers.length === 0 ? (
            <div className="no-asset">{bilingual(lang, "暂无成员 Run", "No member Runs")}</div>
          ) : (
            <ul className="ra-member-list">
              {draftMembers.map((m, idx) => (
                <li key={m.run_id} className="ra-member-row">
                  <span className="ra-member-idx">{idx + 1}</span>
                  <div className="ra-member-info">
                    <strong>{m.run?.name || m.run?.source_name || m.run_id}</strong>
                    <small className="muted">
                      {m.run_id}
                      {m.role ? ` · ${m.role}` : ""}
                      {m.available_now === false ? ` · ${bilingual(lang, "当前不可用", "Unavailable")}` : ""}
                    </small>
                  </div>
                  {m.is_reference && (
                    <StatusChip tone="ok" label={bilingual(lang, "参考 Run", "Reference")} />
                  )}
                  {isAdmin && (
                    <div className="ra-toolbar-actions">
                      <button
                        type="button"
                        className="button button-quiet ra-compact-btn"
                        disabled={idx === 0}
                        aria-label={bilingual(lang, "上移", "Move up")}
                        onClick={() => {
                          setDraftMembers((prev) => {
                            const copy = [...prev];
                            [copy[idx - 1], copy[idx]] = [copy[idx], copy[idx - 1]];
                            return copy;
                          });
                        }}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        className="button button-quiet ra-compact-btn"
                        disabled={idx === draftMembers.length - 1}
                        aria-label={bilingual(lang, "下移", "Move down")}
                        onClick={() => {
                          setDraftMembers((prev) => {
                            const copy = [...prev];
                            [copy[idx], copy[idx + 1]] = [copy[idx + 1], copy[idx]];
                            return copy;
                          });
                        }}
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        className="button button-quiet ra-compact-btn"
                        onClick={() => {
                          setDraftMembers((prev) =>
                            prev.map((item, i) => ({
                              ...item,
                              is_reference: i === idx ? !item.is_reference : false,
                            })),
                          );
                        }}
                      >
                        {m.is_reference
                          ? bilingual(lang, "取消参考", "Unset ref")
                          : bilingual(lang, "设为参考", "Set ref")}
                      </button>
                      <button
                        type="button"
                        className="button button-quiet ra-compact-btn"
                        aria-label={bilingual(lang, "移除", "Remove")}
                        onClick={() =>
                          setDraftMembers((prev) => prev.filter((_, i) => i !== idx))
                        }
                      >
                        ×
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}

          {isAdmin && (
            <div className="ra-add-member-bar">
              <UiSelect
                id="raRunCollectionAddRun"
                value={addRunId}
                options={availableAddRuns.map((r) => ({
                  value: r.id,
                  label: `${r.name || r.source_name || r.id} · ${r.id.slice(0, 8)}`,
                }))}
                placeholder={bilingual(lang, "选择要加入的 Run…", "Select Run to add…")}
                ariaLabel={bilingual(lang, "添加 Run", "Add Run")}
                onChange={setAddRunId}
              />
              <button
                type="button"
                className="button button-quiet"
                disabled={!addRunId}
                onClick={() => {
                  const found = (runsQuery.data?.items || []).find((r) => r.id === addRunId);
                  if (!found) return;
                  setDraftMembers((prev) => [
                    ...prev,
                    { run_id: found.id, role: "candidate", is_reference: prev.length === 0, run: found },
                  ]);
                  setAddRunId("");
                }}
              >
                {bilingual(lang, "添加成员", "Add member")}
              </button>
            </div>
          )}
        </section>
      )}

      {/* Frozen Evaluation Results */}
      {evaluation && (
        <>
          <section className="page-card ra-table-card">
            <div className="ra-card-header">
              <div>
                <h3>
                  {bilingual(lang, "冻结评测快照", "Frozen evaluation snapshot")} · {evaluation.id}
                </h3>
                <p className="muted">
                  {evaluation.summary?.workset_count || 0} Issues ·{" "}
                  {(evaluation.workset?.baseline_scopes || []).join(", ")}
                </p>
              </div>
              <a
                className="button button-quiet"
                href={withWorkbenchBase(`/api/run-evaluations/${encodeURIComponent(evaluation.id)}/export`)}
              >
                {bilingual(lang, "导出评测 CSV", "Export CSV")}
              </a>
            </div>

            {evaluation.selection_bias_warning && (
              <div className="ra-inline-notice is-error">{evaluation.selection_bias_warning}</div>
            )}

            <div className="ra-eval-metrics-grid">
              {(evaluation.summary?.runs || []).map((runMetric) => {
                const confRows = runMetric.confusion || [];
                const confCols = Object.keys(confRows[0]?.cells || {});
                return (
                  <article key={runMetric.run_id} className="ra-eval-run-card">
                    <h4>{runMetric.run?.name || runMetric.run_id}</h4>
                    <div className="ra-eval-stat-line">
                      <span>{bilingual(lang, "准确率", "Accuracy")}</span>
                      <strong>
                        {pct(runMetric.accuracy)} ({runMetric.correct_count || 0}/
                        {runMetric.reference_denominator || 0})
                      </strong>
                    </div>
                    <div className="ra-eval-stat-line">
                      <span>{bilingual(lang, "Union 覆盖率", "Union coverage")}</span>
                      <span>{pct(runMetric.coverage)}</span>
                    </div>
                    <div className="ra-eval-stat-line">
                      <span>{bilingual(lang, "缺失 / UNKNOWN", "Absent / UNKNOWN")}</span>
                      <span>
                        {runMetric.absent_count || 0} / {runMetric.unknown_count || 0}
                      </span>
                    </div>
                    {runMetric.transitions_vs_reference && (
                      <div className="muted ra-small-copy">
                        P2P {runMetric.transitions_vs_reference.P2P || 0} · P2F{" "}
                        {runMetric.transitions_vs_reference.P2F || 0} · F2P{" "}
                        {runMetric.transitions_vs_reference.F2P || 0} · F2F{" "}
                        {runMetric.transitions_vs_reference.F2F || 0}
                      </div>
                    )}
                    {confRows.length > 0 && (
                      <details className="ra-mini-confusion">
                        <summary>{bilingual(lang, "混淆矩阵", "Confusion matrix")}</summary>
                        <div className="ra-table-scroll">
                          <table className="ra-data-table">
                            <thead>
                              <tr>
                                <th>Ref</th>
                                {confCols.map((c) => (
                                  <th key={c}>{c}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {confRows.map((row) => (
                                <tr key={row.reference_label}>
                                  <th>{row.reference_label}</th>
                                  {confCols.map((c) => (
                                    <td key={c}>{row.cells?.[c] || 0}</td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    )}
                  </article>
                );
              })}
            </div>
          </section>

          <section className="page-card ra-table-card">
            <div className="ra-card-header">
              <h3>
                {bilingual(lang, "多 Run Issue 矩阵", "Multi-Run Issue matrix")} ({evaluation.total})
              </h3>
              <form
                className="ra-inline-input-group"
                onSubmit={(e) => {
                  e.preventDefault();
                  setEvalSearch(evalSearchInput.trim());
                  setEvalPage(1);
                }}
              >
                <input
                  type="search"
                  value={evalSearchInput}
                  onChange={(e) => setEvalSearchInput(e.target.value)}
                  placeholder={bilingual(lang, "搜索 Issue ID…", "Search Issue ID…")}
                  aria-label={bilingual(lang, "搜索 Issue", "Search Issue")}
                />
                <button type="submit" className="button button-quiet">
                  {bilingual(lang, "搜索", "Search")}
                </button>
              </form>
            </div>

            <div className="ra-table-scroll">
              <table className="ra-data-table">
                <thead>
                  <tr>
                    <th>Issue</th>
                    <th>{bilingual(lang, "参考标签", "Reference")}</th>
                    {(evaluation.members || []).map((m) => (
                      <th key={m.run_id}>
                        {m.run?.name || m.run_id}
                        {m.is_reference ? ` · ${bilingual(lang, "基准", "ref")}` : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(evaluation.items || []).length === 0 ? (
                    <tr>
                      <td colSpan={2 + (evaluation.members?.length || 0)} className="ra-table-empty">
                        {bilingual(lang, "暂无匹配条目", "No matching items")}
                      </td>
                    </tr>
                  ) : (
                    (evaluation.items || []).map((row) => (
                      <tr key={row.issue_id}>
                        <th>{row.issue_id}</th>
                        <td>{row.reference_label || "—"}</td>
                        {(evaluation.members || []).map((m) => {
                          const pred = row.predictions?.[m.run_id];
                          return (
                            <td key={m.run_id}>
                              <StatusChip
                                tone={
                                  pred?.correct
                                    ? "ok"
                                    : !pred?.label || pred.label === "NONE"
                                      ? "neutral"
                                      : "fail"
                                }
                                label={pred?.label || "NONE"}
                              />
                            </td>
                          );
                        })}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <Pagination
              page={evaluation.page || evalPage}
              pageSize={evalPageSize}
              total={evaluation.total || 0}
              lang={lang}
              loading={evaluationQuery.isFetching}
              onPageChange={setEvalPage}
              onPageSizeChange={(next) => {
                setEvalPageSize(next);
                setEvalPage(1);
              }}
            />
          </section>
        </>
      )}

      {/* Audit Trail */}
      {detail?.audit && detail.audit.length > 0 && (
        <details className="page-card ra-disclosure-card">
          <summary>{bilingual(lang, "项目审计日志", "Project audit trail")}</summary>
          <ul className="ra-audit-list">
            {detail.audit.slice(0, 20).map((entry, i) => (
              <li key={i}>
                <strong>{entry.action || "event"}</strong>
                <span className="muted">
                  r{entry.revision || 0} · {entry.actor || "—"} ·{" "}
                  {formatCstTime(entry.created_at, lang)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {/* Admin Create Project Modal */}
      <ModalDialog
        open={createOpen}
        title={bilingual(lang, "新建评测项目", "New evaluation project")}
        lang={lang}
        onClose={() => setCreateOpen(false)}
        footer={
          <>
            <button type="button" className="button button-quiet" onClick={() => setCreateOpen(false)}>
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={!newName.trim() || createCollectionMutation.isPending}
              onClick={() => createCollectionMutation.mutate()}
            >
              {bilingual(lang, "创建项目", "Create")}
            </button>
          </>
        }
      >
        <div className="ra-modal-form-grid">
          <label className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "项目名称", "Project name")}</span>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder={bilingual(lang, "例如：1113 模型对比集", "e.g. 1113 Model Benchmark")}
            />
          </label>
          <label className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "说明（可选）", "Description (optional)")}</span>
            <input
              type="text"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
            />
          </label>
          <div className="ra-filter-field">
            <span className="ra-field-label">{bilingual(lang, "初始基准 Run", "Initial baseline Run")}</span>
            <UiSelect
              id="raNewProjectFirstRun"
              value={newFirstRun}
              options={(runsQuery.data?.items || []).map((r) => ({
                value: r.id,
                label: `${r.name || r.source_name || r.id} · ${r.id.slice(0, 8)}`,
              }))}
              placeholder={bilingual(lang, "选择初始 Run…", "Select Run…")}
              ariaLabel={bilingual(lang, "初始基准 Run", "Initial baseline Run")}
              onChange={setNewFirstRun}
            />
          </div>
        </div>
      </ModalDialog>
    </div>
  );
};
