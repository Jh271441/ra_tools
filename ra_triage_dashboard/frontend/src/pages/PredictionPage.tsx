import React, { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, formatCstTime, UiLanguage } from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";
import {
  displayLabelText,
  labelBadgeClass,
  parseIssueIdsInput,
  safeExternalUrl,
  showWorkbenchToast,
} from "../features/review/reviewHelpers";
import { useWorkbench } from "../shell/WorkbenchContext";

interface GatewayProvider {
  id: string;
  display_name?: string;
  enabled?: boolean;
  supports_batch?: boolean;
}

interface GatewayModel {
  id: string;
  display_name?: string;
  resolved_model_id?: string;
  validation_status?: string;
}

interface PromptItem {
  id: string;
  display_name?: string;
  is_default?: boolean;
  template?: string;
  sha256?: string;
}

interface BatchItemDetail {
  issue_id: string;
  status: string;
  voyager_issue_url?: string;
  error_text?: string;
  result?: {
    model_label?: string;
    model_confidence?: number;
    model_reason?: string;
    result?: { model_label?: string; model_confidence?: number; model_reason?: string };
  };
}

interface PredictionBatchRow {
  id: string;
  name?: string;
  batch_name?: string;
  status: string;
  publish_status?: string;
  provider_id?: string;
  model_name?: string;
  resolved_model_id?: string;
  model_validation_status?: string;
  prompt_version?: string;
  prompt_mode?: string;
  prompt_template_sha256?: string;
  input_profile?: string;
  total_count?: number;
  requested_count?: number;
  completed_count?: number;
  success_count?: number;
  succeeded_count?: number;
  failed_count?: number;
  requested_by?: string;
  requested_by_verified?: boolean;
  created_at?: string;
  finished_at?: string;
  model_run_id?: string;
  error_text?: string;
  autotriage_record_url?: string;
  record_url?: string;
  items?: BatchItemDetail[];
}

export interface PredictionPageProps {
  active: boolean;
  lang: UiLanguage;
}

const INPUT_PROFILES = [
  {
    id: "camera_ra_event",
    zh: "Camera + RA Events",
    en: "Camera + RA Events",
    offsets: "-19000,-15000,-10000,-5000,0,5000,10000,15000,19000",
    raEvent: true,
    raOptions: false,
  },
  {
    id: "camera_ra_options",
    zh: "Camera + RA/SWAG Options",
    en: "Camera + RA/SWAG Options",
    offsets: "-19000,-15000,-10000,-5000,0,5000,10000,15000,19000",
    raEvent: true,
    raOptions: true,
  },
  {
    id: "camera_only",
    zh: "仅 Camera",
    en: "Camera only",
    offsets: "-19000,-15000,-10000,-5000,0,5000,10000,15000,19000",
    raEvent: false,
    raOptions: false,
  },
] as const;

function batchStatusText(status: string, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    queued: ["排队中", "Queued"],
    running: ["运行中", "Running"],
    succeeded: ["成功", "Succeeded"],
    completed: ["成功", "Completed"],
    partial: ["部分成功", "Partial"],
    partially_succeeded: ["部分成功", "Partial"],
    failed: ["失败", "Failed"],
    cancelled: ["已取消", "Cancelled"],
  };
  return map[status] ? bilingual(lang, map[status][0], map[status][1]) : status;
}

export const PredictionPage: React.FC<PredictionPageProps> = ({ active, lang }) => {
  const queryClient = useQueryClient();
  const { session, config } = useWorkbench();

  const [providerId, setProviderId] = useState("kylin");
  const [modelId, setModelId] = useState("");
  const [promptId, setPromptId] = useState("");
  const [promptTemplate, setPromptTemplate] = useState("");
  const [inputProfile, setInputProfile] = useState("camera_ra_event");
  const [frameOffsets, setFrameOffsets] = useState(
    "-19000,-15000,-10000,-5000,0,5000,10000,15000,19000",
  );
  const [useRaEvent, setUseRaEvent] = useState(true);
  const [useRaOptions, setUseRaOptions] = useState(false);
  const [useBev, setUseBev] = useState(false);
  const [batchName, setBatchName] = useState("");
  const [issuesText, setIssuesText] = useState("");

  // History filters & expand state
  const [statusFilter, setStatusFilter] = useState("");
  const [requesterFilter, setRequesterFilter] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [publishTarget, setPublishTarget] = useState<PredictionBatchRow | null>(null);

  const batchConfigQuery = useQuery<{
    providers?: { active_provider_id?: string; providers?: GatewayProvider[] };
    max_issues?: number;
    autotriage_push_enabled?: boolean;
  }>({
    queryKey: ["prediction-config"],
    queryFn: ({ signal }) => apiRequest("/api/prediction-batches/config", { signal }),
    enabled: active,
    staleTime: 60_000,
  });

  const modelsQuery = useQuery<{ status?: string; stale?: boolean; default_model_id?: string; models?: GatewayModel[] }>({
    queryKey: ["prediction-models", providerId],
    queryFn: ({ signal }) =>
      apiRequest(`/api/prediction-batches/models?provider_id=${encodeURIComponent(providerId)}`, {
        signal,
      }),
    enabled: active,
    staleTime: 30_000,
  });

  const promptsQuery = useQuery<{ default_prompt_id?: string; items?: PromptItem[] }>({
    queryKey: ["prediction-prompts"],
    queryFn: ({ signal }) => apiRequest("/api/prediction-batches/prompts", { signal }),
    enabled: active,
    staleTime: 60_000,
  });

  const batchesQuery = useQuery<{
    items?: PredictionBatchRow[];
    total?: number;
    requesters?: Array<{ name?: string; requested_by?: string; count?: number }>;
  }>({
    queryKey: ["prediction-batches", statusFilter, requesterFilter],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({ page_size: "100" });
      if (statusFilter) qs.set("status", statusFilter);
      const req = requesterFilter === "__me__" ? session.username : requesterFilter;
      if (req) qs.set("requested_by", req);
      return apiRequest(`/api/prediction-batches?${qs.toString()}`, { signal });
    },
    enabled: active,
    staleTime: 10_000,
  });

  const detailQuery = useQuery<{ batch?: PredictionBatchRow; job?: PredictionBatchRow }>({
    queryKey: ["prediction-batch-detail", expandedId],
    queryFn: ({ signal }) =>
      apiRequest(`/api/prediction-batches/${encodeURIComponent(expandedId!)}`, { signal }),
    enabled: Boolean(expandedId),
  });

  const gatewayModels = useMemo(
    () => (modelsQuery.data?.models || []).filter((m) => m.id !== "auto"),
    [modelsQuery.data],
  );
  const prompts = useMemo(() => promptsQuery.data?.items || [], [promptsQuery.data]);

  useEffect(() => {
    const activeProv = batchConfigQuery.data?.providers?.active_provider_id;
    if (activeProv && providerId === "kylin" && activeProv !== providerId) {
      setProviderId(activeProv);
    }
  }, [batchConfigQuery.data]);

  useEffect(() => {
    if (!modelId && gatewayModels.length) {
      const def = modelsQuery.data?.default_model_id;
      setModelId(gatewayModels.find((m) => m.id === def)?.id || gatewayModels[0].id);
    }
  }, [gatewayModels, modelId, modelsQuery.data]);

  useEffect(() => {
    if (!promptId && prompts.length) {
      const def = promptsQuery.data?.default_prompt_id;
      const picked = prompts.find((p) => p.id === def) || prompts[0];
      setPromptId(picked.id);
      setPromptTemplate(picked.template || "");
    }
  }, [prompts, promptId, promptsQuery.data]);

  const parsedIssues = useMemo(() => parseIssueIdsInput(issuesText), [issuesText]);
  const maxIssues = Number(batchConfigQuery.data?.max_issues || 0);
  const publishEnabled = Boolean(
    batchConfigQuery.data?.autotriage_push_enabled ??
      (config?.batch_prediction as { autotriage_push_enabled?: boolean } | undefined)
        ?.autotriage_push_enabled,
  );

  const createMutation = useMutation({
    mutationFn: () => {
      const offsets = frameOffsets
        .split(/[\s,，;；]+/)
        .filter(Boolean)
        .map(Number);
      if (!parsedIssues.ids.length) {
        throw new Error(bilingual(lang, "请至少输入一个 Issue ID。", "Enter at least one Issue ID."));
      }
      if (parsedIssues.invalid.length) {
        throw new Error(
          bilingual(
            lang,
            `Issue ID 不合法：${parsedIssues.invalid.slice(0, 3).join("、")}`,
            `Invalid Issue IDs: ${parsedIssues.invalid.slice(0, 3).join(", ")}`,
          ),
        );
      }
      if (!offsets.length || offsets.some((n) => !Number.isInteger(n))) {
        throw new Error(bilingual(lang, "帧偏移必须是整数列表。", "Frame offsets must be integers."));
      }
      const selectedModel = gatewayModels.find((m) => m.id === modelId);
      return apiRequest("/api/prediction-batches", {
        method: "POST",
        body: JSON.stringify({
          issue_ids: parsedIssues.ids,
          provider_id: providerId,
          model_id: modelId,
          allow_experimental_model: selectedModel?.validation_status !== "validated",
          prompt_id: promptId,
          prompt_template: promptTemplate,
          input_config: {
            profile_id: inputProfile,
            frame_offsets_ms: offsets,
            use_ra_event: useRaEvent,
            use_ra_options: useRaOptions,
            use_bev_animation: useBev,
          },
          name: batchName.trim(),
          requested_by: session.username || "",
        }),
      });
    },
    onSuccess: () => {
      setIssuesText("");
      setBatchName("");
      void queryClient.invalidateQueries({ queryKey: ["prediction-batches"] });
      showWorkbenchToast(
        bilingual(lang, `Batch 已创建，共 ${parsedIssues.ids.length} 个 Issue。`, `Batch created for ${parsedIssues.ids.length} Issues.`),
      );
    },
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

  const publishMutation = useMutation({
    mutationFn: (batchId: string) =>
      apiRequest(`/api/prediction-batches/${encodeURIComponent(batchId)}/publish-autotriage`, {
        method: "POST",
        headers: { "X-RA-Triage-Request": "publish-v1" },
        body: JSON.stringify({ confirm: true }),
      }),
    onSuccess: () => {
      setPublishTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["prediction-batches"] });
      showWorkbenchToast(
        bilingual(lang, "AutoTriage 推送任务已接受。", "AutoTriage publish accepted."),
      );
    },
    onError: (err: Error) => showWorkbenchToast(err.message, true),
  });

  const providerOptions = useMemo<UiSelectOption[]>(
    () =>
      (batchConfigQuery.data?.providers?.providers || [{ id: "kylin", display_name: "Kylin", enabled: true }]).map(
        (p) => ({
          value: p.id,
          label: p.display_name || p.id,
          disabled: p.enabled === false,
        }),
      ),
    [batchConfigQuery.data],
  );

  const modelOptions = useMemo<UiSelectOption[]>(
    () =>
      gatewayModels.length
        ? gatewayModels.map((m) => ({
            value: m.id,
            label: `[${m.validation_status === "validated" ? bilingual(lang, "已验证", "Validated") : bilingual(lang, "实验", "Experimental")}] ${m.display_name || m.id}`,
          }))
        : [{ value: "", label: bilingual(lang, "暂无在线模型", "No online models") }],
    [gatewayModels, lang],
  );

  const promptOptions = useMemo<UiSelectOption[]>(
    () =>
      prompts.length
        ? prompts.map((p) => ({
            value: p.id,
            label: `${p.display_name || p.id}${p.is_default ? bilingual(lang, " · 默认", " · Default") : ""}`,
          }))
        : [{ value: "", label: bilingual(lang, "暂无 Prompt", "No prompts") }],
    [prompts, lang],
  );

  const profileOptions = useMemo<UiSelectOption[]>(
    () => INPUT_PROFILES.map((p) => ({ value: p.id, label: bilingual(lang, p.zh, p.en) })),
    [lang],
  );

  const statusFilterOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "", label: bilingual(lang, "全部状态", "All statuses") },
      { value: "running", label: bilingual(lang, "运行中", "Running") },
      { value: "succeeded", label: bilingual(lang, "成功", "Succeeded") },
      { value: "partial", label: bilingual(lang, "部分成功", "Partial") },
      { value: "failed", label: bilingual(lang, "失败", "Failed") },
    ],
    [lang],
  );

  const requesterOptions = useMemo<UiSelectOption[]>(() => {
    const opts: UiSelectOption[] = [{ value: "", label: bilingual(lang, "全部请求人", "All requesters") }];
    if (session.username) {
      opts.push({ value: "__me__", label: `${bilingual(lang, "我的", "Mine")} · ${session.username}` });
    }
    for (const r of batchesQuery.data?.requesters || []) {
      const n = r.name || r.requested_by;
      if (n) opts.push({ value: n, label: `${n} (${r.count ?? 0})` });
    }
    return opts;
  }, [batchesQuery.data, session.username, lang]);

  const expandedDetail = detailQuery.data?.batch || detailQuery.data?.job || null;

  return (
    <section
      id="predictionPage"
      className="app-page ra-react-page"
      data-page="prediction"
      data-react-island="prediction"
    >
      <div className="panel-card">
        <div className="ra-page-header-row">
          <div>
            <h2>{bilingual(lang, "批次模型预测", "Batch Model Prediction")}</h2>
            <p className="muted">
              {bilingual(
                lang,
                "模型网关与密钥由服务端托管；预测完成后需人工显式推送 AutoTriage。",
                "Model gateway credentials are server-managed; AutoTriage push requires explicit confirmation.",
              )}
            </p>
          </div>
          <button
            type="button"
            className="button button-quiet"
            onClick={() => void modelsQuery.refetch()}
          >
            {bilingual(lang, "刷新模型列表", "Refresh models")}
          </button>
        </div>

        <form
          className="ra-filter-grid"
          style={{ marginTop: 12 }}
          onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate();
          }}
        >
          <div className="ra-field-stack">
            <span>{bilingual(lang, "模型网关 Provider", "Gateway provider")}</span>
            <UiSelect
              id="raBatchProvider"
              value={providerId}
              options={providerOptions}
              ariaLabel={bilingual(lang, "选择 Provider", "Select provider")}
              onChange={(v) => {
                setProviderId(v);
                setModelId("");
              }}
            />
          </div>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "在线模型", "Online model")}</span>
            <UiSelect
              id="raBatchModel"
              value={modelId}
              options={modelOptions}
              ariaLabel={bilingual(lang, "选择在线模型", "Select model")}
              onChange={setModelId}
            />
          </div>
          <div className="ra-field-stack">
            <span>Prompt</span>
            <UiSelect
              id="raBatchPrompt"
              value={promptId}
              options={promptOptions}
              ariaLabel={bilingual(lang, "选择 Prompt 模板", "Select prompt")}
              onChange={(v) => {
                setPromptId(v);
                const found = prompts.find((p) => p.id === v);
                if (found) setPromptTemplate(found.template || "");
              }}
            />
          </div>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "输入配置 Profile", "Input profile")}</span>
            <UiSelect
              id="raBatchProfile"
              value={inputProfile}
              options={profileOptions}
              ariaLabel={bilingual(lang, "选择输入配置", "Select input profile")}
              onChange={(v) => {
                setInputProfile(v);
                const preset = INPUT_PROFILES.find((p) => p.id === v);
                if (preset) {
                  setFrameOffsets(preset.offsets);
                  setUseRaEvent(preset.raEvent);
                  setUseRaOptions(preset.raOptions);
                }
              }}
            />
          </div>
          <label className="ra-field-stack" style={{ gridColumn: "span 2" }}>
            <span>{bilingual(lang, "Camera 帧偏移 (ms)", "Camera frame offsets (ms)")}</span>
            <input
              type="text"
              value={frameOffsets}
              onChange={(e) => setFrameOffsets(e.target.value)}
            />
          </label>
          <label className="ra-field-stack">
            <span>{bilingual(lang, "批次名称（可选）", "Batch name (optional)")}</span>
            <input type="text" value={batchName} onChange={(e) => setBatchName(e.target.value)} />
          </label>
          <div className="ra-inline-actions" style={{ alignItems: "center" }}>
            <label className="ra-checkbox-label">
              <input
                type="checkbox"
                checked={useRaEvent}
                onChange={(e) => setUseRaEvent(e.target.checked)}
              />
              <span>RA Events</span>
            </label>
            <label className="ra-checkbox-label">
              <input
                type="checkbox"
                checked={useRaOptions}
                onChange={(e) => setUseRaOptions(e.target.checked)}
              />
              <span>RA Options</span>
            </label>
            <label className="ra-checkbox-label">
              <input type="checkbox" checked={useBev} onChange={(e) => setUseBev(e.target.checked)} />
              <span>BEV Animation</span>
            </label>
          </div>
          <label className="ra-field-stack" style={{ gridColumn: "1 / -1" }}>
            <span>
              {bilingual(
                lang,
                `Issue IDs（已识别 ${parsedIssues.ids.length}${maxIssues ? ` / 上限 ${maxIssues}` : ""}）`,
                `Issue IDs (${parsedIssues.ids.length} recognized${maxIssues ? ` / max ${maxIssues}` : ""})`,
              )}
            </span>
            <textarea
              rows={3}
              value={issuesText}
              placeholder="cn32171803, cn31954847"
              onChange={(e) => setIssuesText(e.target.value)}
            />
          </label>
          <label className="ra-field-stack" style={{ gridColumn: "1 / -1" }}>
            <span>{bilingual(lang, "Prompt 正文（可微调）", "Prompt template")}</span>
            <textarea
              rows={4}
              value={promptTemplate}
              onChange={(e) => setPromptTemplate(e.target.value)}
            />
          </label>
          <div className="ra-inline-actions">
            <button
              type="submit"
              className="button button-primary ra-primary-touch"
              disabled={createMutation.isPending || !parsedIssues.ids.length || !modelId}
            >
              {createMutation.isPending
                ? bilingual(lang, "创建中…", "Creating…")
                : bilingual(lang, "启动 Batch 预测", "Start Batch Prediction")}
            </button>
          </div>
        </form>
      </div>

      {/* Batch History */}
      <div className="panel-card">
        <div className="ra-page-header-row">
          <h3>
            {bilingual(
              lang,
              `Batch 历史记录 (${batchesQuery.data?.total ?? 0})`,
              `Batch History (${batchesQuery.data?.total ?? 0})`,
            )}
          </h3>
          <button
            type="button"
            className="button button-quiet"
            disabled={batchesQuery.isFetching}
            onClick={() => void batchesQuery.refetch()}
          >
            {bilingual(lang, "刷新", "Refresh")}
          </button>
        </div>

        <div className="ra-filter-grid" style={{ marginTop: 10 }}>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "请求人", "Requester")}</span>
            <UiSelect
              id="raBatchFilterRequester"
              value={requesterFilter}
              options={requesterOptions}
              ariaLabel={bilingual(lang, "按请求人筛选", "Filter by requester")}
              onChange={setRequesterFilter}
            />
          </div>
          <div className="ra-field-stack">
            <span>{bilingual(lang, "状态", "Status")}</span>
            <UiSelect
              id="raBatchFilterStatus"
              value={statusFilter}
              options={statusFilterOptions}
              ariaLabel={bilingual(lang, "按状态筛选", "Filter by status")}
              onChange={setStatusFilter}
            />
          </div>
        </div>

        <div className="run-manager-list" style={{ marginTop: 12 }}>
          {batchesQuery.isLoading ? (
            <div className="no-asset">{bilingual(lang, "正在加载 Batch 列表…", "Loading batches…")}</div>
          ) : !(batchesQuery.data?.items || []).length ? (
            <div className="no-asset">
              {bilingual(lang, "当前筛选下没有 Batch 预测任务。", "No batch prediction jobs match.")}
            </div>
          ) : (
            batchesQuery.data!.items!.map((batch) => {
              const total = Number(batch.total_count ?? batch.requested_count ?? 0);
              const done = Number(batch.completed_count ?? 0);
              const ok = Number(batch.success_count ?? batch.succeeded_count ?? 0);
              const fail = Number(batch.failed_count ?? 0);
              const expanded = expandedId === batch.id;
              const recordUrl = safeExternalUrl(batch.autotriage_record_url || batch.record_url);
              const canPublish =
                ["succeeded", "completed", "partial", "partially_succeeded"].includes(batch.status) &&
                ok > 0 &&
                Boolean(batch.model_run_id) &&
                ["not_requested", "not_published", "pending", "failed", undefined].includes(
                  batch.publish_status,
                );
              return (
                <article key={batch.id} className="job-history-row batch-history-row">
                  <div className="job-history-main">
                    <div className="run-row-title">
                      <strong>{batch.name || batch.batch_name || batch.id}</strong>
                      <span className={`job-status status-${batch.status}`}>
                        {batchStatusText(batch.status, lang)}
                      </span>
                    </div>
                    <div className="run-row-meta">
                      <span>{batch.model_name || batch.resolved_model_id || "—"}</span>
                      {batch.prompt_version && <span>Prompt · {batch.prompt_version}</span>}
                      <span>
                        {done}/{total} · {bilingual(lang, "成功", "OK")} {ok} ·{" "}
                        {bilingual(lang, "失败", "Fail")} {fail}
                      </span>
                      <span>{batch.requested_by || "—"}</span>
                      <span>{formatCstTime(batch.created_at, lang)}</span>
                    </div>
                  </div>
                  <div className="run-row-actions">
                    <button
                      type="button"
                      className="button button-quiet"
                      onClick={() => setExpandedId(expanded ? null : batch.id)}
                    >
                      {expanded
                        ? bilingual(lang, "收起日志", "Hide logs")
                        : bilingual(lang, "查看日志", "View logs")}
                    </button>
                    {canPublish && publishEnabled && (
                      <button
                        type="button"
                        className="button button-primary"
                        onClick={() => setPublishTarget(batch)}
                      >
                        {bilingual(lang, "推送 AutoTriage", "Push AutoTriage")}
                      </button>
                    )}
                    {recordUrl && (
                      <a
                        className="button button-quiet"
                        href={recordUrl}
                        target="_blank"
                        rel="noreferrer"
                      >
                        AutoTriage ↗
                      </a>
                    )}
                  </div>
                  {expanded && (
                    <div className="batch-history-detail">
                      {detailQuery.isLoading ? (
                        <span className="muted">{bilingual(lang, "正在读取明细…", "Loading items…")}</span>
                      ) : !(expandedDetail?.items || []).length ? (
                        <span className="muted">{bilingual(lang, "暂无明细。", "No items yet.")}</span>
                      ) : (
                        <div className="batch-result-items">
                          {expandedDetail!.items!.map((it) => {
                            const res = it.result?.result || it.result || {};
                            return (
                              <div key={it.issue_id} className="batch-result-item">
                                <strong>{it.issue_id}</strong>
                                <span className={`job-status status-${it.status}`}>
                                  {batchStatusText(it.status, lang)}
                                </span>
                                {res.model_label && (
                                  <span className={labelBadgeClass(res.model_label)}>
                                    {displayLabelText(res.model_label, lang)}
                                  </span>
                                )}
                                {res.model_reason && (
                                  <small className="batch-item-reason">{res.model_reason}</small>
                                )}
                                {it.error_text && <small>{it.error_text}</small>}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </article>
              );
            })
          )}
        </div>
      </div>

      <ModalDialog
        open={Boolean(publishTarget)}
        title={bilingual(lang, "确认推送到 AutoTriage", "Confirm Push to AutoTriage")}
        lang={lang}
        onClose={() => {
          if (!publishMutation.isPending) setPublishTarget(null);
        }}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => setPublishTarget(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-primary"
              disabled={publishMutation.isPending}
              onClick={() => publishTarget && publishMutation.mutate(publishTarget.id)}
            >
              {publishMutation.isPending
                ? bilingual(lang, "推送中…", "Pushing…")
                : bilingual(lang, "确认推送", "Confirm push")}
            </button>
          </>
        }
      >
        <p>
          {bilingual(
            lang,
            `将把 Batch「${publishTarget?.name || publishTarget?.id || ""}」的成功预测显式写入 AutoTriage。继续？`,
            `Push succeeded predictions from batch "${publishTarget?.name || publishTarget?.id || ""}" to AutoTriage?`,
          )}
        </p>
      </ModalDialog>
    </section>
  );
};
