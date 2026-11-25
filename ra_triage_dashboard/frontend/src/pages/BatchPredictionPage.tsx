import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  formatCstTime,
  UiLanguage,
} from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

interface GatewayProviderItem {
  id: string;
  display_name?: string;
  enabled?: boolean;
  supports_batch?: boolean;
  credential_configured?: boolean;
}

interface GatewayModelItem {
  id: string;
  display_name?: string;
  resolved_model_id?: string;
  provider?: string;
  validation_status?: string;
  unavailable?: boolean;
}

interface BatchPromptItem {
  id: string;
  display_name?: string;
  template?: string;
  sha256?: string;
  is_default?: boolean;
}

interface InputProfilePreset {
  id: string;
  frame_offsets_ms: number[];
  use_ra_event: boolean;
  use_ra_options: boolean;
}

interface BatchConfigResponse {
  max_issues?: number;
  autotriage_push_enabled?: boolean;
  prompt_version?: string;
  model?: Record<string, string>;
  model_gateway?: { catalog_label?: string };
  providers?: {
    active_provider_id?: string;
    providers?: GatewayProviderItem[];
  };
  input_policy?: {
    profiles?: InputProfilePreset[];
  };
}

interface GatewayModelsResponse {
  status?: string;
  stale?: boolean;
  message?: string;
  catalog_label?: string;
  default_model_id?: string;
  models?: GatewayModelItem[];
}

interface BatchPromptsResponse {
  default_prompt_id?: string;
  items?: BatchPromptItem[];
}

interface BatchResultItem {
  issue_id: string;
  status: string;
  voyager_issue_url?: string;
  error_text?: string;
  result?: {
    model_label?: string;
    model_confidence?: number;
    model_reason?: string;
    result?: {
      model_label?: string;
      model_confidence?: number;
      model_reason?: string;
    };
  };
}

interface BatchJobItem {
  id: string;
  name?: string;
  batch_name?: string;
  status: string;
  publish_status?: string;
  autotriage_batch_id?: string;
  platform_batch_id?: string;
  provider_id?: string;
  requested_model_id?: string;
  model_name?: string;
  resolved_model_id?: string;
  model_validation_status?: string;
  prompt_version?: string;
  prompt_mode?: string;
  prompt_template_sha256?: string;
  input_profile?: string;
  input_config?: {
    frame_offsets_ms?: number[];
    use_ra_event?: boolean;
    use_ra_options?: boolean;
    use_bev_animation?: boolean;
  };
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
  summary?: string | Record<string, unknown>;
  autotriage_record_url?: string;
  record_url?: string;
  autotriage_url?: string;
  records_url?: string;
  items?: BatchResultItem[];
}

interface BatchListResponse {
  items?: BatchJobItem[];
  total?: number;
  requesters?: Array<{
    name?: string;
    requested_by?: string;
    job_count?: number;
    batch_count?: number;
    count?: number;
    verified?: boolean;
    verified_count?: number;
    unverified_count?: number;
  }>;
  facets?: {
    models?: Array<{ id: string; job_count: number }>;
    prompts?: Array<{ version: string; mode: string; sha256: string; job_count: number }>;
    input_profiles?: Array<{ id: string; job_count: number }>;
  };
}

interface LegacyWindow {
  showPage?: (page: string) => void;
  showToast?: (msg: string, isError?: boolean) => void;
}

const DEFAULT_PROFILES: InputProfilePreset[] = [
  {
    id: "camera_ra_event",
    frame_offsets_ms: [-19000, -15000, -10000, -5000, 0, 5000, 10000, 15000, 19000],
    use_ra_event: true,
    use_ra_options: false,
  },
  {
    id: "camera_ra_options",
    frame_offsets_ms: [-19000, -15000, -10000, -5000, 0, 5000, 10000, 15000, 19000],
    use_ra_event: true,
    use_ra_options: true,
  },
  {
    id: "camera_only",
    frame_offsets_ms: [-19000, -15000, -10000, -5000, 0, 5000, 10000, 15000, 19000],
    use_ra_event: false,
    use_ra_options: false,
  },
];

const CAMERA_PRESETS = [
  {
    id: "camera_9_frames",
    frame_offsets_ms: [-19000, -15000, -10000, -5000, 0, 5000, 10000, 15000, 19000],
  },
  {
    id: "camera_three_moments",
    frame_offsets_ms: [-3000, 0, 3000],
  },
  {
    id: "camera_single_frame",
    frame_offsets_ms: [0],
  },
];

function getLegacyWindow(): LegacyWindow {
  return window as unknown as LegacyWindow;
}

function safeExternalUrl(url?: string): string {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

function defaultBatchName(username: string): string {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value || "00";
  const stamp = `${get("year")}${get("month")}${get("day")}_${get("hour")}${get("minute")}${get("second")}`;
  const cleanUser = (username || "batch").replace(/[^A-Za-z0-9_-]+/g, "_");
  return `${cleanUser}_${stamp}`;
}

function parseIssueIds(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(/[\s,，;；]+/)
        .map((v) => v.trim())
        .filter(Boolean),
    ),
  ];
}

function batchStatusLabel(status: string, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    queued: ["排队中", "Queued"],
    running: ["运行中", "Running"],
    succeeded: ["成功", "Succeeded"],
    completed: ["成功", "Succeeded"],
    partial: ["部分成功", "Partial"],
    partially_succeeded: ["部分成功", "Partial"],
    failed: ["失败", "Failed"],
    cancelled: ["已取消", "Cancelled"],
  };
  const pair = map[status];
  return pair ? bilingual(lang, pair[0], pair[1]) : status || bilingual(lang, "未知", "Unknown");
}

function batchPublishLabel(status: string, lang: UiLanguage): string {
  const map: Record<string, [string, string]> = {
    not_requested: ["未推送", "Not pushed"],
    not_published: ["未推送", "Not pushed"],
    pending: ["未推送", "Not pushed"],
    running: ["推送中", "Pushing"],
    publishing: ["推送中", "Pushing"],
    succeeded: ["已推送", "Pushed"],
    published: ["已推送", "Pushed"],
    partial: ["部分推送", "Partial"],
    failed: ["推送失败", "Push failed"],
  };
  const pair = map[status];
  return pair ? bilingual(lang, pair[0], pair[1]) : status || bilingual(lang, "未推送", "Not pushed");
}

function parsePromptFacet(value: string): { version: string; mode: string; sha256: string } {
  if (!value) return { version: "", mode: "", sha256: "" };
  try {
    const [version = "", mode = "", sha256 = ""] = JSON.parse(value);
    return { version: String(version), mode: String(mode), sha256: String(sha256) };
  } catch {
    return { version: value, mode: "", sha256: "" };
  }
}

export interface BatchPredictionPageProps {
  active: boolean;
  lang: UiLanguage;
  username: string;
}

export const BatchPredictionPage: React.FC<BatchPredictionPageProps> = ({
  active,
  lang,
  username,
}) => {
  const queryClient = useQueryClient();

  const [selectedProviderId, setSelectedProviderId] = useState<string>("");
  const [selectedModelId, setSelectedModelId] = useState<string>("");
  const [refreshModelsTick, setRefreshModelsTick] = useState(0);

  // Batch form state
  const [issuesText, setIssuesText] = useState<string>(() => {
    const params = new URLSearchParams(window.location.search);
    const list = params.get("issues") || params.get("issue") || "";
    return parseIssueIds(list).join(", ");
  });
  const [selectedPromptId, setSelectedPromptId] = useState<string>("");
  const [promptTemplate, setPromptTemplate] = useState<string>("");
  const [inputProfile, setInputProfile] = useState<string>("camera_ra_event");
  const [cameraPreset, setCameraPreset] = useState<string>("camera_9_frames");
  const [frameOffsetsText, setFrameOffsetsText] = useState<string>(
    "-19000,-15000,-10000,-5000,0,5000,10000,15000,19000",
  );
  const [useBev, setUseBev] = useState<boolean>(true);
  const [useRaEvent, setUseRaEvent] = useState<boolean>(true);
  const [useRaOptions, setUseRaOptions] = useState<boolean>(false);
  const [batchName, setBatchName] = useState<string>(() => defaultBatchName(username));
  const [submitting, setSubmitting] = useState<boolean>(false);

  // Filters for history
  const [requesterFilter, setRequesterFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [modelFilter, setModelFilter] = useState<string>("");
  const [promptFilter, setPromptFilter] = useState<string>("");
  const [inputFilter, setInputFilter] = useState<string>("");

  // Expanded detail & polling
  const [expandedBatchId, setExpandedBatchId] = useState<string>("");
  const [batchDetails, setBatchDetails] = useState<Record<string, BatchJobItem>>({});
  const [pollingBatchId, setPollingBatchId] = useState<string>("");
  const [publishingBatchId, setPublishingBatchId] = useState<string>("");

  // Confirm modals (replacing native window.confirm)
  const [confirmExperimentalOpen, setConfirmExperimentalOpen] = useState(false);
  const [confirmPublishBatch, setConfirmPublishBatch] = useState<BatchJobItem | null>(null);

  useEffect(() => {
    if (username && (!batchName || batchName.startsWith("batch_"))) {
      setBatchName(defaultBatchName(username));
    }
  }, [username]);

  // Queries
  const configQuery = useQuery<BatchConfigResponse>({
    queryKey: ["batch-prediction-config"],
    queryFn: ({ signal }) => apiRequest<BatchConfigResponse>("/api/prediction-batches/config", { signal }),
    enabled: active,
    staleTime: 30_000,
  });

  const providers = useMemo(
    () => configQuery.data?.providers?.providers || [],
    [configQuery.data],
  );

  const effectiveProviderId = useMemo(() => {
    if (selectedProviderId && providers.some((p) => p.id === selectedProviderId && p.enabled)) {
      return selectedProviderId;
    }
    const activeCfg = configQuery.data?.providers?.active_provider_id;
    if (activeCfg && providers.some((p) => p.id === activeCfg && p.enabled)) return activeCfg;
    return providers.find((p) => p.enabled)?.id || providers[0]?.id || "kylin";
  }, [selectedProviderId, providers, configQuery.data]);

  const modelsQuery = useQuery<GatewayModelsResponse>({
    queryKey: ["batch-prediction-models", effectiveProviderId, refreshModelsTick],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({ provider_id: effectiveProviderId });
      if (refreshModelsTick > 0) qs.set("refresh", "true");
      return apiRequest<GatewayModelsResponse>(`/api/prediction-batches/models?${qs.toString()}`, {
        signal,
      });
    },
    enabled: active && Boolean(effectiveProviderId),
    staleTime: 30_000,
  });

  const gatewayModels = useMemo(() => {
    const raw = modelsQuery.data?.models || [];
    return raw.filter((m) => m.id !== "auto");
  }, [modelsQuery.data]);

  const defaultModelId = useMemo(() => {
    const raw = modelsQuery.data?.models || [];
    const autoModel = raw.find((m) => m.id === "auto");
    return autoModel?.resolved_model_id || modelsQuery.data?.default_model_id || "";
  }, [modelsQuery.data]);

  const effectiveModelId = useMemo(() => {
    if (selectedModelId) return selectedModelId;
    if (defaultModelId && gatewayModels.some((m) => m.id === defaultModelId)) return defaultModelId;
    return gatewayModels[0]?.id || "";
  }, [selectedModelId, defaultModelId, gatewayModels]);

  const promptsQuery = useQuery<BatchPromptsResponse>({
    queryKey: ["batch-prediction-prompts"],
    queryFn: ({ signal }) =>
      apiRequest<BatchPromptsResponse>("/api/prediction-batches/prompts", { signal }),
    enabled: active,
    staleTime: 30_000,
  });

  const prompts = useMemo(() => promptsQuery.data?.items || [], [promptsQuery.data]);

  useEffect(() => {
    if (!prompts.length) return;
    if (selectedPromptId && prompts.some((p) => p.id === selectedPromptId)) return;
    const defId = promptsQuery.data?.default_prompt_id || "";
    const chosen = prompts.find((p) => p.id === defId) || prompts[0];
    if (chosen) {
      setSelectedPromptId(chosen.id);
      setPromptTemplate(chosen.template || "");
    }
  }, [prompts, promptsQuery.data?.default_prompt_id, selectedPromptId]);

  const batchesQuery = useQuery<BatchListResponse>({
    queryKey: [
      "batch-prediction-list",
      requesterFilter,
      statusFilter,
      modelFilter,
      promptFilter,
      inputFilter,
    ],
    queryFn: ({ signal }) => {
      const qs = new URLSearchParams({ page_size: "200" });
      const req = requesterFilter === "__me__" ? username : requesterFilter;
      if (req) qs.set("requested_by", req);
      if (statusFilter) qs.set("status", statusFilter);
      if (modelFilter) qs.set("model_id", modelFilter);
      const pf = parsePromptFacet(promptFilter);
      if (pf.version) qs.set("prompt_version", pf.version);
      if (pf.mode) qs.set("prompt_mode", pf.mode);
      if (pf.sha256) qs.set("prompt_sha256", pf.sha256);
      if (inputFilter) qs.set("input_profile", inputFilter);
      return apiRequest<BatchListResponse>(`/api/prediction-batches?${qs.toString()}`, { signal });
    },
    enabled: active,
    staleTime: 10_000,
  });

  // Poll active running batch
  useEffect(() => {
    if (!active || !pollingBatchId) return;
    const timer = window.setInterval(async () => {
      try {
        const res = await apiRequest<{ batch?: BatchJobItem; job?: BatchJobItem } & BatchJobItem>(
          `/api/prediction-batches/${encodeURIComponent(pollingBatchId)}`,
        );
        const batch = res.batch || res.job || res;
        if (batch?.id) {
          setBatchDetails((prev) => ({ ...prev, [batch.id]: batch }));
          const running =
            ["queued", "running"].includes(batch.status) ||
            ["running", "publishing"].includes(batch.publish_status || "");
          if (!running) {
            setPollingBatchId("");
            void queryClient.invalidateQueries({ queryKey: ["batch-prediction-list"] });
          }
        }
      } catch {
        setPollingBatchId("");
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [active, pollingBatchId, queryClient]);

  const loadBatchDetail = useCallback(async (batchId: string) => {
    try {
      const res = await apiRequest<{ batch?: BatchJobItem; job?: BatchJobItem } & BatchJobItem>(
        `/api/prediction-batches/${encodeURIComponent(batchId)}`,
      );
      const batch = res.batch || res.job || res;
      if (batch?.id) {
        setBatchDetails((prev) => ({ ...prev, [batch.id]: batch }));
      }
    } catch (err) {
      setExpandedBatchId((cur) => (cur === batchId ? "" : cur));
      getLegacyWindow().showToast?.(err instanceof Error ? err.message : String(err), true);
    }
  }, []);

  if (!active) return null;

  const issueIds = parseIssueIds(issuesText);
  const invalidIds = issueIds.filter((id) => !/^[A-Za-z0-9_-]{3,128}$/.test(id));
  const maxIssues = Number(configQuery.data?.max_issues || 50);
  const overLimit = maxIssues > 0 && issueIds.length > maxIssues;

  const selectedModel = gatewayModels.find((m) => m.id === effectiveModelId) || null;
  const selectedPrompt = prompts.find((p) => p.id === selectedPromptId) || null;
  const promptChanged = Boolean(
    selectedPrompt && promptTemplate.trim() !== String(selectedPrompt.template || "").trim(),
  );
  const promptBytes = new TextEncoder().encode(promptTemplate).length;

  const catalogReady =
    modelsQuery.data?.status === "ready" &&
    !modelsQuery.data?.stale &&
    Boolean(effectiveModelId) &&
    Boolean(selectedModel);

  const tierLabel = (m: GatewayModelItem) =>
    m.unavailable
      ? bilingual(lang, "不可用", "Unavailable")
      : m.validation_status === "validated"
        ? bilingual(lang, "已验证", "Validated")
        : bilingual(lang, "实验", "Experimental");

  const providerOptions: UiSelectOption[] = providers.length
    ? providers.map((p) => {
        const selectable = Boolean(p.enabled && p.supports_batch);
        const st = selectable
          ? bilingual(lang, "可用", "Available")
          : p.credential_configured
            ? bilingual(lang, "暂不可用", "Unavailable")
            : bilingual(lang, "未配置密钥", "No key");
        return {
          value: p.id,
          label: `${p.display_name || p.id} · ${st}`,
          disabled: !selectable,
        };
      })
    : [{ value: "", label: bilingual(lang, "正在读取 Provider…", "Loading providers…") }];

  const modelOptions: UiSelectOption[] = gatewayModels.length
    ? gatewayModels.map((m) => ({
        value: m.id,
        label: `[${tierLabel(m)}] ${m.display_name || m.id}`,
        disabled: Boolean(m.unavailable),
      }))
    : [{ value: "", label: bilingual(lang, "暂无可用模型", "No models available") }];

  const promptOptions: UiSelectOption[] = prompts.length
    ? prompts.map((p) => ({
        value: p.id,
        label: `${p.display_name || p.id}${p.is_default ? bilingual(lang, " · 默认", " · default") : ""}`,
      }))
    : [{ value: "", label: bilingual(lang, "暂无可用三分类 Prompt", "No Prompt available") }];

  const profileOptions: UiSelectOption[] = [
    { value: "camera_ra_event", label: "Camera 9 frames + RA Events" },
    { value: "camera_ra_options", label: "Camera 9 frames + RA Events + RA/SWAG Options" },
    { value: "camera_only", label: "Camera 9 frames" },
  ];

  const cameraPresetOptions: UiSelectOption[] = [
    { value: "camera_9_frames", label: "Camera 9 frames · -19s to +19s (default)" },
    { value: "camera_three_moments", label: "Camera 3 moments · before / now / after" },
    { value: "camera_single_frame", label: "Camera single frame · now" },
    { value: "custom", label: "Custom frame offsets" },
  ];

  const requesters = batchesQuery.data?.requesters || [];
  const requesterOptions: UiSelectOption[] = [
    { value: "", label: bilingual(lang, "全部请求人", "All requesters") },
    ...(username ? [{ value: "__me__", label: `${bilingual(lang, "我的", "Mine")} · ${username}` }] : []),
    ...requesters
      .map((r) => {
        const name = r.name || r.requested_by || "";
        if (!name) return null;
        const cnt = r.job_count ?? r.batch_count ?? r.count ?? 0;
        const trust =
          (r.verified_count || 0) > 0 && (r.unverified_count || 0) > 0
            ? bilingual(lang, " · 混合身份", " · mixed")
            : r.verified
              ? " · SSO"
              : "";
        return { value: name, label: `${name} · ${cnt} ${bilingual(lang, "个", "jobs")}${trust}` };
      })
      .filter((x): x is UiSelectOption => Boolean(x)),
  ];

  const statusFilterOptions: UiSelectOption[] = [
    { value: "", label: bilingual(lang, "全部状态", "All statuses") },
    { value: "queued", label: bilingual(lang, "排队中", "Queued") },
    { value: "running", label: bilingual(lang, "运行中", "Running") },
    { value: "succeeded", label: bilingual(lang, "成功", "Succeeded") },
    { value: "partial", label: bilingual(lang, "部分成功", "Partial") },
    { value: "failed", label: bilingual(lang, "失败", "Failed") },
  ];

  const modelFilterOptions: UiSelectOption[] = (() => {
    const map = new Map<string, { id: string; label: string; count: number | null }>();
    gatewayModels.forEach((m) =>
      map.set(m.id, { id: m.id, label: m.display_name || m.id, count: null }),
    );
    (batchesQuery.data?.facets?.models || []).forEach((m) => {
      const ex = map.get(m.id);
      map.set(m.id, {
        id: m.id,
        label: ex?.label || `${m.id} · ${bilingual(lang, "历史", "history")}`,
        count: m.job_count,
      });
    });
    return [
      { value: "", label: bilingual(lang, "全部模型", "All models") },
      ...[...map.values()].map((m) => ({
        value: m.id,
        label: `${m.label}${m.count != null ? ` · ${m.count}` : ""}`,
      })),
    ];
  })();

  const promptFilterOptions: UiSelectOption[] = (() => {
    const map = new Map<string, { value: string; label: string; count: number | null }>();
    prompts.forEach((p) => {
      const value = JSON.stringify([p.id, "catalog", p.sha256 || ""]);
      map.set(value, {
        value,
        label: `${p.display_name || p.id} · ${bilingual(lang, "当前模板", "current")}`,
        count: null,
      });
    });
    (batchesQuery.data?.facets?.prompts || []).forEach((p) => {
      const value = JSON.stringify([p.version || "", p.mode || "", p.sha256 || ""]);
      const ex = map.get(value);
      const sha = p.sha256 ? ` · ${p.sha256.slice(0, 10)}…` : "";
      const mode = p.mode === "custom" ? "custom" : p.mode === "catalog" ? "catalog" : "legacy";
      map.set(value, {
        value,
        label: ex?.label || `${p.version} · ${mode}${sha}`,
        count: p.job_count,
      });
    });
    return [
      { value: "", label: bilingual(lang, "全部 Prompt", "All Prompts") },
      ...[...map.values()].map((p) => ({
        value: p.value,
        label: `${p.label}${p.count != null ? ` · ${p.count}` : ""}`,
      })),
    ];
  })();

  const inputFilterOptions: UiSelectOption[] = (() => {
    const labels: Record<string, string> = {
      camera_ra_event: "Camera + RA Events",
      camera_ra_options: "Camera + RA/SWAG Options",
      camera_only: "Camera only",
      custom: "Custom",
    };
    const map = new Map<string, { id: string; label: string; count: number | null }>(
      Object.entries(labels).map(([id, label]) => [id, { id, label, count: null }]),
    );
    (batchesQuery.data?.facets?.input_profiles || []).forEach((p) => {
      map.set(p.id, {
        id: p.id,
        label: labels[p.id] || `${p.id} · ${bilingual(lang, "历史", "history")}`,
        count: p.job_count,
      });
    });
    return [
      { value: "", label: bilingual(lang, "全部输入", "All inputs") },
      ...[...map.values()].map((p) => ({
        value: p.id,
        label: `${p.label}${p.count != null ? ` · ${p.count}` : ""}`,
      })),
    ];
  })();

  const executeSubmit = async (allowExperimental: boolean) => {
    const offsets = frameOffsetsText
      .split(/[\s,，;；]+/)
      .filter(Boolean)
      .map(Number);
    setSubmitting(true);
    try {
      const res = await apiRequest<{ batch?: BatchJobItem; job?: BatchJobItem } & BatchJobItem>(
        "/api/prediction-batches",
        {
          method: "POST",
          body: {
            issue_ids: issueIds,
            provider_id: effectiveProviderId || "kylin",
            model_id: effectiveModelId,
            allow_experimental_model: allowExperimental,
            prompt_id: selectedPromptId,
            prompt_template: promptTemplate,
            input_config: {
              profile_id: inputProfile,
              frame_offsets_ms: offsets,
              use_ra_event: useRaEvent,
              use_ra_options: useRaOptions,
              use_bev_animation: useBev,
            },
            name: batchName.trim(),
            requested_by: username || "",
          },
        },
      );
      const created = res.batch || res.job || res;
      if (created?.id) {
        setBatchDetails((prev) => ({ ...prev, [created.id]: created }));
        setExpandedBatchId(created.id);
        if (["queued", "running"].includes(created.status)) setPollingBatchId(created.id);
      }
      getLegacyWindow().showToast?.(
        bilingual(
          lang,
          `Batch 已创建，共 ${issueIds.length} 个 Issue。`,
          `Batch created with ${issueIds.length} Issues.`,
        ),
      );
      void batchesQuery.refetch();
    } catch (err) {
      getLegacyWindow().showToast?.(err instanceof Error ? err.message : String(err), true);
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmitForm = (e: React.FormEvent) => {
    e.preventDefault();
    const offsets = frameOffsetsText
      .split(/[\s,，;；]+/)
      .filter(Boolean)
      .map(Number);
    if (!issueIds.length) {
      getLegacyWindow().showToast?.(
        bilingual(lang, "请至少输入一个 Issue ID。", "Enter at least one Issue ID."),
        true,
      );
      return;
    }
    if (invalidIds.length) {
      getLegacyWindow().showToast?.(
        bilingual(
          lang,
          `Issue ID 格式不合法：${invalidIds.slice(0, 3).join("、")}`,
          `Invalid Issue IDs: ${invalidIds.slice(0, 3).join(", ")}`,
        ),
        true,
      );
      return;
    }
    if (!catalogReady) {
      getLegacyWindow().showToast?.(
        bilingual(lang, "模型目录尚未就绪。", "Model catalog is not ready."),
        true,
      );
      return;
    }
    if (!selectedPromptId || !promptTemplate.trim()) {
      getLegacyWindow().showToast?.(
        bilingual(lang, "请选择 Prompt，并保留非空正文。", "Select a Prompt with non-empty body."),
        true,
      );
      return;
    }
    if (!offsets.length || offsets.some((n) => !Number.isInteger(n))) {
      getLegacyWindow().showToast?.(
        bilingual(lang, "Camera 帧偏移必须是逗号分隔的整数。", "Camera frame offsets must be integers."),
        true,
      );
      return;
    }
    if (useRaOptions && !useRaEvent) {
      getLegacyWindow().showToast?.(
        bilingual(
          lang,
          "启用 RA / SWAG Options 时必须同时启用 RA Events。",
          "RA / SWAG Options requires RA Events.",
        ),
        true,
      );
      return;
    }
    if (overLimit) {
      getLegacyWindow().showToast?.(
        bilingual(
          lang,
          `单批最多 ${maxIssues} 个 Issue；当前 ${issueIds.length} 个。`,
          `Max ${maxIssues} Issues per batch; got ${issueIds.length}.`,
        ),
        true,
      );
      return;
    }
    const experimental = selectedModel?.validation_status !== "validated";
    if (experimental) {
      setConfirmExperimentalOpen(true);
      return;
    }
    void executeSubmit(false);
  };

  const executePublish = async (batch: BatchJobItem) => {
    setConfirmPublishBatch(null);
    setPublishingBatchId(batch.id);
    try {
      const res = await apiRequest<{ batch?: BatchJobItem; job?: BatchJobItem }>(
        `/api/prediction-batches/${encodeURIComponent(batch.id)}/publish-autotriage`,
        {
          method: "POST",
          headers: { "X-RA-Triage-Request": "publish-v1" },
          body: { confirm: true },
        },
      );
      const updated = res.batch || res.job;
      if (updated?.id) {
        setBatchDetails((prev) => ({ ...prev, [updated.id]: updated }));
        setExpandedBatchId(updated.id);
      }
      getLegacyWindow().showToast?.(
        bilingual(
          lang,
          "AutoTriage 推送任务已接受，正在等待平台回查。",
          "AutoTriage publish accepted; polling status.",
        ),
      );
      void batchesQuery.refetch();
      setPollingBatchId(batch.id);
    } catch (err) {
      getLegacyWindow().showToast?.(err instanceof Error ? err.message : String(err), true);
    } finally {
      setPublishingBatchId("");
    }
  };

  const frameCount = frameOffsetsText
    .split(/[\s,，;；]+/)
    .filter(Boolean).length;
  const validatedCount = gatewayModels.filter((m) => m.validation_status === "validated").length;
  const experimentalCount = gatewayModels.length - validatedCount;
  const batches = batchesQuery.data?.items || [];
  const totalBatches = batchesQuery.data?.total ?? batches.length;
  const publishEnabled = Boolean(configQuery.data?.autotriage_push_enabled);
  const terminalStatuses = new Set(["succeeded", "completed", "partial", "partially_succeeded"]);

  return (
    <div className="ra-batch-prediction-root" data-react-island="prediction">
      <div className="compact-page-lead">
        <p>
          {bilingual(
            lang,
            "从服务器模型网关选择模型并批量预测；完成后再显式推送到 AutoTriage。",
            "Pick a gateway model and run batch prediction; publish to AutoTriage explicitly when ready.",
          )}
        </p>
        <button
          className="button button-quiet"
          type="button"
          onClick={() => getLegacyWindow().showPage?.("review")}
        >
          {bilingual(lang, "返回判错复核", "Back to failure review")}
        </button>
      </div>

      <div className="tool-page-grid batch-page-grid">
        <aside className="page-card page-aside gateway-card">
          <h3>{bilingual(lang, "服务器模型网关", "Server model gateway")}</h3>

          <div className="gateway-endpoint ra-gateway-field">
            <span>Provider</span>
            <UiSelect
              id="gatewayProviderPicker"
              value={effectiveProviderId}
              options={providerOptions}
              disabled={!providers.length}
              ariaLabel="Provider"
              onChange={(val) => {
                setSelectedProviderId(val);
                setSelectedModelId("");
              }}
            />
            <small>
              <span id="gatewayModelsEndpoint">
                {modelsQuery.data?.catalog_label ||
                  configQuery.data?.model_gateway?.catalog_label ||
                  "ra-model · /v1/models"}
              </span>{" "}
              · {bilingual(lang, "服务端密钥", "server-owned key")}
            </small>
          </div>

          <div className="ra-batch-field">
            <span>{bilingual(lang, "模型", "Model")}</span>
            <div className="gateway-model-control">
              <UiSelect
                id="gatewayModelPicker"
                value={effectiveModelId}
                options={modelOptions}
                disabled={!gatewayModels.length}
                ariaLabel={bilingual(lang, "模型", "Model")}
                onChange={setSelectedModelId}
              />
              <button
                className="button button-quiet"
                id="refreshGatewayModelsButton"
                type="button"
                title={bilingual(lang, "刷新模型", "Refresh models")}
                onClick={() => setRefreshModelsTick((n) => n + 1)}
              >
                {bilingual(lang, "刷新", "Refresh")}
              </button>
            </div>
          </div>

          <div
            className={`gateway-model-status ${
              modelsQuery.isFetching ? "" : catalogReady ? "ok" : "warn"
            }`}
            id="gatewayModelStatus"
          >
            {modelsQuery.isFetching
              ? bilingual(lang, "正在获取可用模型…", "Fetching model list…")
              : catalogReady
                ? bilingual(
                    lang,
                    `已验证 ${validatedCount} · 实验 ${experimentalCount} · ${gatewayModels.length}`,
                    `Validated ${validatedCount} · Experimental ${experimentalCount} · ${gatewayModels.length}`,
                  )
                : modelsQuery.data?.message ||
                  bilingual(lang, "模型目录暂不可用", "Model catalog not ready")}
          </div>

          <div
            className="gateway-model-list"
            id="gatewayModelList"
            aria-label={bilingual(lang, "可用模型", "Available models")}
          >
            {gatewayModels.length ? (
              gatewayModels.map((m) => {
                const isActive = !m.unavailable && m.id === effectiveModelId;
                const resolved =
                  m.resolved_model_id && m.resolved_model_id !== m.id
                    ? m.resolved_model_id
                    : m.id;
                return (
                  <button
                    key={m.id}
                    type="button"
                    className={`gateway-model-option${isActive ? " active" : ""}${
                      m.unavailable ? " unavailable" : ""
                    }`}
                    disabled={Boolean(m.unavailable)}
                    title={`${m.display_name || m.id} · ${resolved}`}
                    onClick={() => setSelectedModelId(m.id)}
                  >
                    <span className="gateway-model-option-head">
                      <strong>{m.display_name || m.id}</strong>
                      <em>{tierLabel(m)}</em>
                    </span>
                    <small>{resolved}</small>
                  </button>
                );
              })
            ) : (
              <div className="muted">
                {modelsQuery.isFetching
                  ? bilingual(lang, "正在读取模型目录…", "Loading model catalog…")
                  : bilingual(lang, "暂无可用模型。", "No models available.")}
              </div>
            )}
          </div>

          <div className="batch-runtime-summary" id="batchModelSummary">
            <strong>
              {selectedModel?.display_name ||
                configQuery.data?.model?.model_name ||
                bilingual(lang, "服务器模型网关", "Server model gateway")}
            </strong>
            <span>
              {selectedPrompt?.id
                ? `Prompt · ${selectedPrompt.id}`
                : bilingual(lang, "尚未选择 Prompt", "No Prompt selected")}{" "}
              · {bilingual(lang, "输入", "Input")} {inputProfile}
            </span>
            <small>
              {[
                selectedModel
                  ? `${effectiveProviderId} · ${selectedModel.resolved_model_id || selectedModel.id}`
                  : "",
                frameCount
                  ? bilingual(
                      lang,
                      `Camera ${frameCount} 帧 · Ares Animation ${useBev ? "开启" : "关闭"}`,
                      `Camera ${frameCount} frames · Ares Animation ${useBev ? "ON" : "OFF"}`,
                    )
                  : "",
              ]
                .filter(Boolean)
                .join(" · ") ||
                bilingual(
                  lang,
                  "模型地址与密钥由服务器管理；Prompt 和输入按 Batch 固化",
                  "Model endpoints & keys are server-managed; Prompt & input freeze per Batch",
                )}
            </small>
          </div>
        </aside>

        <form className="page-card tool-form" id="predictionBatchForm" onSubmit={handleSubmitForm}>
          <label className="batch-issue-field">
            <span className="batch-field-heading">
              <span>Issue IDs</span>
              <small
                id="predictionBatchIssueCount"
                className={invalidIds.length || overLimit ? "input-warning" : ""}
              >
                {[
                  `${issueIds.length}`,
                  maxIssues ? `max ${maxIssues}` : "",
                  invalidIds.length
                    ? bilingual(lang, `${invalidIds.length} 无效`, `${invalidIds.length} invalid`)
                    : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </small>
            </span>
            <textarea
              className="batch-issue-input"
              id="predictionBatchIssues"
              rows={1}
              required
              autoComplete="off"
              value={issuesText}
              placeholder={bilingual(
                lang,
                "支持逗号或空格分隔，例如：cn32171803, cn31954847, cn32000543",
                "Comma or space separated, e.g. cn32171803, cn31954847",
              )}
              onChange={(e) => setIssuesText(e.target.value)}
            />
          </label>

          <details className="batch-config-details" open>
            <summary>
              {bilingual(lang, "Prompt 与输入配置", "Prompt & input config")}
              <small>
                {bilingual(
                  lang,
                  "每个 Batch 固化完整快照，可按模型 / Prompt / 输入筛选",
                  "Each Batch freezes a full snapshot; filter by model / Prompt / input",
                )}
              </small>
            </summary>

            <div className="batch-config-body">
              <div className="batch-config-grid">
                <div className="ra-batch-field">
                  <span>{bilingual(lang, "Prompt 基线", "Prompt baseline")}</span>
                  <UiSelect
                    id="predictionPromptSelect"
                    value={selectedPromptId}
                    options={promptOptions}
                    ariaLabel={bilingual(lang, "Prompt 基线", "Prompt baseline")}
                    onChange={(val) => {
                      setSelectedPromptId(val);
                      const found = prompts.find((p) => p.id === val);
                      setPromptTemplate(found?.template || "");
                    }}
                  />
                </div>
                <div className="ra-batch-field">
                  <span>{bilingual(lang, "输入 Profile", "Input profile")}</span>
                  <UiSelect
                    id="predictionInputProfile"
                    value={inputProfile}
                    options={profileOptions}
                    ariaLabel={bilingual(lang, "输入 Profile", "Input profile")}
                    onChange={(val) => {
                      setInputProfile(val);
                      const profiles =
                        configQuery.data?.input_policy?.profiles || DEFAULT_PROFILES;
                      const preset = profiles.find((p) => p.id === val);
                      if (preset) {
                        setFrameOffsetsText((preset.frame_offsets_ms || []).join(","));
                        setUseRaEvent(Boolean(preset.use_ra_event));
                        setUseRaOptions(Boolean(preset.use_ra_options));
                        setCameraPreset("camera_9_frames");
                      }
                    }}
                  />
                </div>
              </div>

              <div className="batch-common-config">
                <div className="ra-batch-field">
                  <span>{bilingual(lang, "Camera 取帧预设", "Camera frame preset")}</span>
                  <UiSelect
                    id="predictionCameraPreset"
                    value={cameraPreset}
                    options={cameraPresetOptions}
                    ariaLabel={bilingual(lang, "Camera 取帧预设", "Camera frame preset")}
                    onChange={(val) => {
                      setCameraPreset(val);
                      const preset = CAMERA_PRESETS.find((p) => p.id === val);
                      if (preset) setFrameOffsetsText(preset.frame_offsets_ms.join(","));
                    }}
                  />
                </div>
                <div className="batch-bev-field">
                  <span>{bilingual(lang, "Ares 输入", "Ares input")}</span>
                  <label
                    className="toggle-row compact-toggle batch-bev-toggle"
                    title="Uses server stuck_triage_auto_opt_api default Ares Animation config"
                  >
                    <input
                      id="predictionUseBev"
                      type="checkbox"
                      checked={useBev}
                      onChange={(e) => setUseBev(e.target.checked)}
                    />
                    <span>
                      <strong>BEV / Ares Animation</strong>
                      <small>API default</small>
                    </span>
                  </label>
                </div>
              </div>

              <label>
                <span>{bilingual(lang, "Prompt 正文（可编辑）", "Prompt body (editable)")}</span>
                <textarea
                  className="batch-prompt-input"
                  id="predictionPromptTemplate"
                  rows={12}
                  spellCheck={false}
                  value={promptTemplate}
                  placeholder={bilingual(
                    lang,
                    "选择 Prompt 后载入完整正文",
                    "Full body loads after choosing a Prompt",
                  )}
                  onChange={(e) => setPromptTemplate(e.target.value)}
                />
                <small
                  id="predictionPromptSummary"
                  className={promptBytes === 0 || promptBytes > 128 * 1024 ? "input-warning" : ""}
                >
                  {`${promptBytes} bytes · ${
                    promptChanged
                      ? bilingual(
                          lang,
                          "已修改，将保存 custom Prompt 快照",
                          "Modified; will freeze custom Prompt snapshot",
                        )
                      : bilingual(lang, "服务器模板原文", "Server template verbatim")
                  }${
                    selectedPrompt?.sha256
                      ? ` · ${bilingual(lang, "基线 SHA", "Baseline SHA")} ${selectedPrompt.sha256.slice(0, 12)}…`
                      : ""
                  }`}
                </small>
              </label>

              <label>
                <span>{bilingual(lang, "Camera 帧偏移（ms）", "Camera frame offsets (ms)")}</span>
                <input
                  id="predictionFrameOffsets"
                  autoComplete="off"
                  value={frameOffsetsText}
                  onChange={(e) => {
                    const next = e.target.value;
                    setFrameOffsetsText(next);
                    const nums = next
                      .split(/[\s,，;；]+/)
                      .filter(Boolean)
                      .map(Number);
                    const matched = CAMERA_PRESETS.find(
                      (p) =>
                        p.frame_offsets_ms.length === nums.length &&
                        p.frame_offsets_ms.every((v, idx) => v === nums[idx]),
                    );
                    setCameraPreset(matched?.id || "custom");
                  }}
                />
                <small>
                  {bilingual(
                    lang,
                    "严格递增、包含 0；最多 18 帧，范围 ±30000 ms。",
                    "Strictly increasing, include 0; max 18 frames, ±30000 ms.",
                  )}
                </small>
              </label>

              <div className="batch-input-toggles">
                <label className="toggle-row compact-toggle">
                  <input
                    id="predictionUseRaEvent"
                    type="checkbox"
                    checked={useRaEvent}
                    onChange={(e) => {
                      setUseRaEvent(e.target.checked);
                      if (!e.target.checked) setUseRaOptions(false);
                    }}
                  />
                  <span>
                    <strong>RA Events</strong>
                    <small>{bilingual(lang, "注入协助时序", "Assist timing")}</small>
                  </span>
                </label>
                <label className="toggle-row compact-toggle">
                  <input
                    id="predictionUseRaOptions"
                    type="checkbox"
                    checked={useRaOptions}
                    onChange={(e) => {
                      setUseRaOptions(e.target.checked);
                      if (e.target.checked) setUseRaEvent(true);
                    }}
                  />
                  <span>
                    <strong>RA / SWAG Options</strong>
                    <small>{bilingual(lang, "需同时启用 RA Events", "Requires RA Events")}</small>
                  </span>
                </label>
              </div>
            </div>
          </details>

          <div className="batch-submit-row">
            <label>
              <span>{bilingual(lang, "批次名", "Batch name")}</span>
              <input
                id="predictionBatchName"
                placeholder="e.g. xuhaoxuan_20260729_163454"
                maxLength={120}
                autoComplete="off"
                value={batchName}
                onChange={(e) => setBatchName(e.target.value)}
              />
            </label>
            <div className="page-actions">
              <button
                className="button button-primary"
                id="createPredictionBatchButton"
                type="submit"
                disabled={!catalogReady || submitting}
              >
                {submitting
                  ? bilingual(lang, "正在创建…", "Creating…")
                  : bilingual(lang, "开始 Batch 预测", "Start batch prediction")}
              </button>
            </div>
          </div>
        </form>
      </div>

      <section className="page-card job-history-card">
        <div className="section-heading">
          <div>
            <h3>{bilingual(lang, "全员 Batch 任务", "Team Batch jobs")}</h3>
          </div>
          <button
            className="button button-quiet"
            id="refreshPredictionBatchesButton"
            type="button"
            disabled={batchesQuery.isFetching}
            onClick={() => void batchesQuery.refetch()}
          >
            {bilingual(lang, "刷新任务", "Refresh jobs")}
          </button>
        </div>

        <div className="run-filter-bar batch-history-filters">
          <div className="ra-batch-field">
            <span>{bilingual(lang, "请求人", "Requester")}</span>
            <UiSelect
              id="batchRequesterFilter"
              value={requesterFilter}
              options={requesterOptions}
              ariaLabel={bilingual(lang, "请求人", "Requester")}
              onChange={setRequesterFilter}
            />
          </div>
          <div className="ra-batch-field">
            <span>{bilingual(lang, "任务状态", "Job status")}</span>
            <UiSelect
              id="batchStatusFilter"
              value={statusFilter}
              options={statusFilterOptions}
              ariaLabel={bilingual(lang, "任务状态", "Job status")}
              onChange={setStatusFilter}
            />
          </div>
          <div className="ra-batch-field">
            <span>{bilingual(lang, "模型", "Model")}</span>
            <UiSelect
              id="batchModelFilter"
              value={modelFilter}
              options={modelFilterOptions}
              ariaLabel={bilingual(lang, "模型", "Model")}
              onChange={setModelFilter}
            />
          </div>
          <div className="ra-batch-field">
            <span>Prompt</span>
            <UiSelect
              id="batchPromptFilter"
              value={promptFilter}
              options={promptFilterOptions}
              ariaLabel="Prompt"
              onChange={setPromptFilter}
            />
          </div>
          <div className="ra-batch-field">
            <span>{bilingual(lang, "输入", "Input")}</span>
            <UiSelect
              id="batchInputFilter"
              value={inputFilter}
              options={inputFilterOptions}
              ariaLabel={bilingual(lang, "输入", "Input")}
              onChange={setInputFilter}
            />
          </div>
        </div>

        <div className="run-manager-summary" id="batchHistorySummary">
          {batchesQuery.isLoading
            ? bilingual(lang, "正在加载 Batch 任务…", "Loading Batch jobs…")
            : bilingual(
                lang,
                `显示 ${batches.length} / ${totalBatches} 个 Batch · 预测完成后需人工显式推送 AutoTriage`,
                `Showing ${batches.length} / ${totalBatches} Batches · Publish to AutoTriage manually after completion`,
              )}
        </div>

        <div className="job-history-list" id="predictionBatchList">
          {!batchesQuery.isLoading && batches.length === 0 ? (
            <div className="no-asset">
              {bilingual(lang, "当前筛选下没有 Batch 预测任务。", "No Batch prediction jobs match.")}
            </div>
          ) : (
            batches.map((batch) => {
              const total = Number(batch.total_count ?? batch.requested_count ?? batch.items?.length ?? 0);
              const completed = Number(batch.completed_count ?? 0);
              const success = Number(batch.success_count ?? batch.succeeded_count ?? 0);
              const failed = Number(batch.failed_count ?? 0);
              const publishStatus =
                batch.publish_status ||
                (batch.autotriage_batch_id || batch.platform_batch_id ? "published" : "not_published");
              const canPublish =
                terminalStatuses.has(batch.status) &&
                success > 0 &&
                Boolean(batch.model_run_id) &&
                Boolean(batch.prompt_template_sha256) &&
                Boolean(batch.input_profile) &&
                ["not_requested", "not_published", "pending", "failed"].includes(publishStatus);
              const batchUrl = safeExternalUrl(
                batch.autotriage_record_url ||
                  batch.record_url ||
                  batch.autotriage_url ||
                  batch.records_url,
              );
              const summaryText = batch.error_text
                ? batch.error_text
                : typeof batch.summary === "string"
                  ? batch.summary
                  : batch.model_run_id
                    ? `${bilingual(lang, "已生成模型 Run", "Created Model Run")} · ${batch.model_run_id}`
                    : "";
              const expanded = expandedBatchId === batch.id;
              const detail = batchDetails[batch.id];

              return (
                <article className="job-history-row batch-history-row" key={batch.id}>
                  <div className="job-history-main">
                    <div className="run-row-title">
                      <strong>{batch.name || batch.batch_name || batch.id}</strong>
                      <span className={`job-status status-${batch.status}`}>
                        {batchStatusLabel(batch.status, lang)}
                      </span>
                      <span className={`publish-status publish-${publishStatus}`}>
                        {batchPublishLabel(publishStatus, lang)}
                      </span>
                    </div>
                    <div className="run-row-meta">
                      <span>Provider {batch.provider_id || "kylin"}</span>
                      <span>
                        {batch.requested_model_id && batch.requested_model_id !== batch.model_name
                          ? `${batch.requested_model_id} → ${batch.model_name || batch.resolved_model_id}`
                          : batch.model_name ||
                            batch.resolved_model_id ||
                            bilingual(lang, "服务器模型网关", "Server model gateway")}
                      </span>
                      {batch.model_validation_status === "experimental" ? (
                        <span>{bilingual(lang, "实验", "Experimental")}</span>
                      ) : null}
                      {batch.prompt_version ? (
                        <span>
                          Prompt {batch.prompt_version}
                          {batch.prompt_mode === "custom"
                            ? ` · custom${
                                batch.prompt_template_sha256
                                  ? ` · ${batch.prompt_template_sha256.slice(0, 10)}…`
                                  : ""
                              }`
                            : ""}
                        </span>
                      ) : null}
                      {batch.input_profile ? (
                        <span>
                          {bilingual(lang, "输入", "Input")} {batch.input_profile}
                        </span>
                      ) : null}
                      <span>
                        {completed} / {total} {bilingual(lang, "完成", "done")}
                      </span>
                      <span className="batch-success-count">
                        {bilingual(lang, "成功", "OK")} {success}
                      </span>
                      <span className="run-failure-count">
                        {bilingual(lang, "失败", "Fail")} {failed}
                      </span>
                      <span>
                        {batch.requested_by
                          ? `${bilingual(lang, "请求人", "Requester")} ${batch.requested_by}${
                              batch.requested_by_verified ? " · SSO" : ""
                            }`
                          : bilingual(lang, "请求人未记录", "Requester unknown")}
                      </span>
                      <span>{formatCstTime(batch.created_at, lang)}</span>
                    </div>
                    {summaryText ? <div className="job-result-preview">{summaryText}</div> : null}
                  </div>

                  <div className="run-row-actions">
                    <button
                      className="button button-quiet"
                      type="button"
                      onClick={() => {
                        if (expanded) {
                          setExpandedBatchId("");
                        } else {
                          setExpandedBatchId(batch.id);
                          void loadBatchDetail(batch.id);
                        }
                      }}
                    >
                      {expanded
                        ? bilingual(lang, "收起日志", "Hide logs")
                        : bilingual(lang, "查看日志", "View logs")}
                    </button>
                    {canPublish && publishEnabled ? (
                      <button
                        className="button button-primary"
                        type="button"
                        disabled={publishingBatchId === batch.id}
                        onClick={() => setConfirmPublishBatch(batch)}
                      >
                        {publishingBatchId === batch.id
                          ? bilingual(lang, "推送中…", "Pushing…")
                          : bilingual(lang, "推送 AutoTriage", "Push AutoTriage")}
                      </button>
                    ) : null}
                    {canPublish && !publishEnabled ? (
                      <button
                        className="button button-quiet"
                        type="button"
                        disabled
                        title={bilingual(
                          lang,
                          "生产写入需可信 SSO 域名",
                          "Production push requires verified SSO origin",
                        )}
                      >
                        {bilingual(lang, "推送需 SSO", "Push requires SSO")}
                      </button>
                    ) : null}
                    {["running", "publishing"].includes(publishStatus) ? (
                      <button className="button button-quiet" type="button" disabled>
                        {bilingual(lang, "推送中…", "Pushing…")}
                      </button>
                    ) : null}
                    {batchUrl ? (
                      <a
                        className="button button-quiet"
                        href={batchUrl}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {bilingual(lang, "打开 AutoTriage", "Open AutoTriage")}
                      </a>
                    ) : null}
                  </div>

                  {expanded ? (
                    <div className="batch-history-detail" data-batch-detail={batch.id}>
                      {!detail ? (
                        <span className="muted">
                          {bilingual(lang, "正在读取运行输出…", "Loading execution output…")}
                        </span>
                      ) : (
                        <>
                          <div className="batch-detail-heading">
                            <div>
                              <strong>
                                {bilingual(lang, "运行输出", "Output")} ·{" "}
                                {detail.name || detail.batch_name || detail.id}
                              </strong>
                            </div>
                            <span>
                              {batchStatusLabel(detail.status, lang)} · {completed}/{total}{" "}
                              {bilingual(lang, "完成", "done")} · {bilingual(lang, "成功", "OK")}{" "}
                              {success} · {bilingual(lang, "失败", "Fail")} {failed}
                            </span>
                          </div>
                          <div className="batch-detail-meta">
                            <span>
                              {detail.provider_id || "kylin"} · {bilingual(lang, "模型", "Model")}{" "}
                              {detail.resolved_model_id || detail.model_name || "—"}
                            </span>
                            <span>
                              Prompt {detail.prompt_version || "—"}
                              {detail.prompt_mode === "custom" ? " · custom" : ""}
                            </span>
                            {detail.model_run_id ? <span>Model Run {detail.model_run_id}</span> : null}
                            {detail.finished_at ? (
                              <span>
                                {bilingual(lang, "结束", "Finished")}{" "}
                                {formatCstTime(detail.finished_at, lang)}
                              </span>
                            ) : null}
                          </div>
                          {Array.isArray(detail.items) && detail.items.length ? (
                            <div className="batch-result-items">
                              {detail.items.map((it) => {
                                const res = it.result?.result || it.result || {};
                                const url = safeExternalUrl(it.voyager_issue_url);
                                return (
                                  <div className="batch-result-item" key={it.issue_id}>
                                    <strong>{it.issue_id}</strong>
                                    <span className={`job-status status-${it.status}`}>
                                      {batchStatusLabel(it.status, lang)}
                                    </span>
                                    {res.model_label ? (
                                      <span className={`label-badge label-${res.model_label}`}>
                                        {res.model_label}
                                      </span>
                                    ) : null}
                                    {url ? (
                                      <a href={url} target="_blank" rel="noreferrer">
                                        {bilingual(lang, "打开 Voyager Issue", "Open Voyager Issue")}
                                      </a>
                                    ) : null}
                                    {res.model_confidence != null ? (
                                      <small>confidence {String(res.model_confidence)}</small>
                                    ) : null}
                                    {res.model_reason ? (
                                      <small className="batch-item-reason">{res.model_reason}</small>
                                    ) : null}
                                    {it.error_text ? <small>{it.error_text}</small> : null}
                                  </div>
                                );
                              })}
                            </div>
                          ) : (
                            <div className="muted">
                              {bilingual(lang, "任务明细尚未生成。", "No item results yet.")}
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  ) : null}
                </article>
              );
            })
          )}
        </div>
      </section>

      <ModalDialog
        open={confirmExperimentalOpen}
        title={bilingual(lang, "确认使用实验模型", "Confirm experimental model")}
        lang={lang}
        onClose={() => setConfirmExperimentalOpen(false)}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => setConfirmExperimentalOpen(false)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-primary"
              onClick={() => {
                setConfirmExperimentalOpen(false);
                void executeSubmit(true);
              }}
            >
              {bilingual(lang, "继续创建", "Proceed")}
            </button>
          </>
        }
      >
        <p>
          {bilingual(
            lang,
            `模型「${selectedModel?.display_name || effectiveModelId}」在线但尚未完成 RA 基线验证。仍要用它创建实验 Batch 吗？`,
            `Model "${selectedModel?.display_name || effectiveModelId}" is online but unvalidated against the RA baseline. Create an experimental Batch anyway?`,
          )}
        </p>
      </ModalDialog>

      <ModalDialog
        open={Boolean(confirmPublishBatch)}
        title={bilingual(lang, "确认推送到 AutoTriage", "Confirm push to AutoTriage")}
        lang={lang}
        onClose={() => setConfirmPublishBatch(null)}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              onClick={() => setConfirmPublishBatch(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-primary"
              onClick={() => confirmPublishBatch && void executePublish(confirmPublishBatch)}
            >
              {bilingual(lang, "确认推送", "Confirm push")}
            </button>
          </>
        }
      >
        <p>
          {bilingual(
            lang,
            `将把 Batch「${confirmPublishBatch?.name || confirmPublishBatch?.id || ""}」的成功预测显式写入 AutoTriage，并保存关联记录链接。继续？`,
            `Publish successful predictions from Batch "${confirmPublishBatch?.name || confirmPublishBatch?.id || ""}" to AutoTriage and save record links?`,
          )}
        </p>
      </ModalDialog>
    </div>
  );
};
