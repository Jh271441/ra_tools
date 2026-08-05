/* ra_triage_dashboard/static/js/batch.js
 * Batch prediction UI
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function predictionIssueIds() {
  return [
    ...new Set(
      String($("#predictionBatchIssues")?.value || "")
        .split(/[\s,，;；]+/)
        .map((value) => value.trim())
        .filter(Boolean)
    ),
  ];
}

function updatePredictionBatchCount() {
  const target = $("#predictionBatchIssueCount");
  if (!target) return;
  const ids = predictionIssueIds();
  const invalid = ids.filter((issueId) => !/^[A-Za-z0-9_-]{3,128}$/.test(issueId));
  const maxIssues = Number(state.config?.prediction_batch?.max_issues || 0);
  const overLimit = maxIssues > 0 && ids.length > maxIssues;
  target.textContent =
    `${ids.length} 个${maxIssues ? ` · 单批最多 ${maxIssues} 个` : ""}` +
    `${invalid.length ? ` · ${invalid.length} 个格式不合法` : ""}`;
  target.classList.toggle("input-warning", Boolean(invalid.length || overLimit));
}

function renderGatewayProviders() {
  const target = $("#gatewayProviderSelect");
  if (!target) return;
  const catalog = state.config?.prediction_batch?.providers || {};
  const providers = Array.isArray(catalog.providers) ? catalog.providers : [];
  if (!providers.length) {
    target.innerHTML = '<option value="">未发现服务端 Provider 配置</option>';
    target.disabled = true;
    return;
  }
  const configuredSelected = state.selectedGatewayProviderId || catalog.active_provider_id;
  const selectedId = providers.some((item) => item.id === configuredSelected && item.enabled)
    ? configuredSelected
    : providers.find((item) => item.enabled)?.id || providers[0].id;
  state.selectedGatewayProviderId = selectedId;
  target.innerHTML = providers
    .map((provider) => {
      const selectable = Boolean(provider.enabled && provider.supports_batch);
      const status = selectable ? "可用" : provider.credential_configured ? "暂不可用" : "未配置凭证";
      return `<option value="${escapeHtml(provider.id)}" ${selectable ? "" : "disabled"}>${escapeHtml(provider.display_name || provider.id)} · ${escapeHtml(status)}</option>`;
    })
    .join("");
  target.value = selectedId;
  target.disabled = false;
  target.onchange = () => {
    const nextId = target.value || selectedId;
    if (nextId === state.selectedGatewayProviderId) return;
    state.selectedGatewayProviderId = nextId;
    state.selectedGatewayModelId = "";
    const modelSelect = $("#predictionModelSelect");
    if (modelSelect) modelSelect.value = "";
    renderGatewayProviders();
    loadGatewayModels({ providerId: state.selectedGatewayProviderId }).catch((error) => {
      showToast(error.message, true);
    });
  };
}

function gatewayModelTier(model) {
  return model?.unavailable
    ? "不可用"
    : model?.validation_status === "validated"
      ? "已验证"
      : "实验";
}

function gatewayModelOptionMarkup(model, active = false, attribute = "data-gateway-model") {
  const unavailable = Boolean(model?.unavailable);
  const tier = gatewayModelTier(model);
  const resolved = model?.resolved_model_id && model.resolved_model_id !== model.id
    ? model.resolved_model_id
    : model?.id || "";
  return `<button class="gateway-model-option ${active ? "active" : ""} ${unavailable ? "unavailable" : ""}" type="button" ${attribute}="${escapeHtml(model?.id || "")}" ${unavailable ? "disabled" : ""}>
    <span class="gateway-model-option-head">
      <strong>${escapeHtml(model?.display_name || model?.id || "未命名模型")}</strong>
      <em>${tier}</em>
    </span>
    <small>${escapeHtml(resolved)}</small>
  </button>`;
}

function closeGatewayModelPicker() {
  const picker = $("#gatewayModelPicker");
  const panel = $("#gatewayModelPickerPanel");
  const trigger = $("#gatewayModelPickerTrigger");
  if (!picker || !panel) return;
  panel.hidden = true;
  picker.classList.remove("is-open");
  trigger?.setAttribute("aria-expanded", "false");
}

function bindGatewayModelPicker() {
  const picker = $("#gatewayModelPicker");
  const trigger = $("#gatewayModelPickerTrigger");
  const panel = $("#gatewayModelPickerPanel");
  const select = $("#predictionModelSelect");
  if (!picker || !trigger || !panel || !select || picker.dataset.bound === "true") return;
  picker.dataset.bound = "true";
  trigger.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const willOpen = panel.hidden;
    closeGatewayModelPicker();
    if (!willOpen) return;
    panel.hidden = false;
    picker.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
  });
  panel.addEventListener("click", (event) => {
    event.stopPropagation();
    const option = event.target.closest("[data-gateway-picker-model]");
    if (!option || option.disabled) return;
    select.value = option.dataset.gatewayPickerModel || "";
    state.selectedGatewayModelId = select.value;
    closeGatewayModelPicker();
    renderGatewayModels();
  });
  document.addEventListener("click", (event) => {
    if (!picker.contains(event.target)) closeGatewayModelPicker();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeGatewayModelPicker();
  });
}

function renderGatewayModels() {
  const select = $("#predictionModelSelect");
  const statusTarget = $("#gatewayModelStatus");
  const endpointTarget = $("#gatewayModelsEndpoint");
  const listTarget = $("#gatewayModelList");
  const createButton = $("#createPredictionBatchButton");
  if (!select || !statusTarget || !endpointTarget) return;
  bindGatewayModelPicker();
  const catalog = state.gatewayModelStatus || {};
  const previous = state.selectedGatewayModelId || select.value;
  const visibleModels = state.gatewayModels;
  const defaultId = catalog.ui_default_model_id || catalog.default_model_id || "";
  const selectedModel = previous
    ? state.gatewayModels.find((item) => item.id === previous) || null
    : state.gatewayModels.find((item) => item.id === defaultId) ||
      state.gatewayModels[0] ||
      null;
  const unavailableSelection = Boolean(previous && !selectedModel);
  const displayModels = [...visibleModels];
  if (unavailableSelection) {
    displayModels.unshift({
      id: previous,
      display_name: `${previous} · 当前选择已不可用`,
      unavailable: true,
    });
  }
  endpointTarget.textContent =
    catalog.catalog_label ||
    state.config?.prediction_batch?.model_gateway?.catalog_label ||
    "ra-model · /v1/models";
  select.innerHTML = displayModels.length
    ? displayModels
        .map(
          (model) => {
            const tier = model.unavailable
              ? "不可用"
              : model.validation_status === "validated"
                ? "已验证"
                : "实验";
            return `<option value="${escapeHtml(model.id)}">[${tier}] ${escapeHtml(model.display_name || model.id)}</option>`;
          }
        )
        .join("")
    : '<option value="">没有匹配的模型</option>';
  select.value = unavailableSelection ? previous : selectedModel?.id || "";
  state.selectedGatewayModelId = select.value;
  const pickerSummary = $("#gatewayModelPickerSummary");
  const pickerOptions = $("#gatewayModelPickerOptions");
  if (pickerSummary) {
    const selectedForPicker = displayModels.find((model) => model.id === select.value);
    pickerSummary.textContent = selectedForPicker
      ? `[${gatewayModelTier(selectedForPicker)}] ${selectedForPicker.display_name || selectedForPicker.id}`
      : "没有匹配的模型";
  }
  if (pickerOptions) {
    pickerOptions.innerHTML = displayModels.length
      ? displayModels.map((model) => gatewayModelOptionMarkup(
          model,
          !model.unavailable && model.id === state.selectedGatewayModelId,
          "data-gateway-picker-model",
        )).join("")
      : '<div class="muted">没有匹配的模型。</div>';
  }
  if (listTarget) {
    listTarget.innerHTML = displayModels.length
      ? displayModels.map((model) => gatewayModelOptionMarkup(
          model,
          !model.unavailable && model.id === state.selectedGatewayModelId,
        )).join("")
      : '<div class="muted">没有匹配的模型。</div>';
    listTarget.querySelectorAll("[data-gateway-model]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) return;
        state.selectedGatewayModelId = button.dataset.gatewayModel || "";
        select.value = state.selectedGatewayModelId;
        renderGatewayModels();
      });
    });
  }
  const selectedIsOnline = state.gatewayModels.some(
    (item) => item.id === state.selectedGatewayModelId
  );
  const ready =
    catalog.status === "ready" &&
    !catalog.stale &&
    Boolean(select.value) &&
    selectedIsOnline;
  statusTarget.className = `gateway-model-status ${ready ? "ok" : "warn"}`;
  statusTarget.textContent = unavailableSelection
    ? `当前选择 ${previous} 已不在当前 Provider 在线目录；请选择其他模型后再提交。`
    : ready
      ? `已验证 ${state.gatewayModels.filter((model) => model.validation_status === "validated").length} · 实验模型 ${state.gatewayModels.filter((model) => model.validation_status !== "validated").length} · 当前显示 ${visibleModels.length}`
      : catalog.message || "模型目录尚未就绪。";
  if (createButton) createButton.disabled = !ready;
  renderBatchCatalogFilters();
  renderBatchRuntimeSummary();
}

async function loadGatewayModels({ refresh = false, providerId = "" } = {}) {
  const requestSeq = ++state.gatewayModelRequestSeq;
  const statusTarget = $("#gatewayModelStatus");
  if (statusTarget) {
    statusTarget.className = "gateway-model-status";
    statusTarget.textContent = refresh ? "正在刷新模型目录…" : "正在自动获取模型目录…";
  }
  try {
    const selectedProviderId = providerId || state.selectedGatewayProviderId || "kylin";
    const params = new URLSearchParams({ provider_id: selectedProviderId });
    if (refresh) params.set("refresh", "true");
    const data = await api(`/api/prediction-batches/models?${params.toString()}`);
    if (requestSeq !== state.gatewayModelRequestSeq) return;
    const models = data.models || [];
    const autoModel = models.find((model) => model.id === "auto");
    state.gatewayModelStatus = {
      ...data,
      ui_default_model_id: autoModel?.resolved_model_id || data.default_model_id,
    };
    state.gatewayModels = models.filter((model) => model.id !== "auto");
    renderGatewayModels();
  } catch (error) {
    if (requestSeq !== state.gatewayModelRequestSeq) return;
    state.gatewayModelStatus = {
      status: "failed",
      stale: false,
      message: error.message,
      catalog_label:
        state.config?.prediction_batch?.model_gateway?.catalog_label ||
        "ra-model · /v1/models",
      provider_id: providerId || state.selectedGatewayProviderId || "kylin",
    };
    state.gatewayModels = [];
    renderGatewayModels();
    throw error;
  }
}

function selectedBatchPrompt() {
  const promptId = $("#predictionPromptSelect")?.value || "";
  return state.batchPrompts.find((item) => item.id === promptId) || null;
}

function updatePromptEditorSummary() {
  const target = $("#predictionPromptSummary");
  const editor = $("#predictionPromptTemplate");
  if (!target || !editor) return;
  const selected = selectedBatchPrompt();
  const changed = Boolean(selected && editor.value.trim() !== String(selected.template || "").trim());
  const bytes = new TextEncoder().encode(editor.value).length;
  target.textContent =
    `${bytes} bytes · ${changed ? "已修改，将保存 custom Prompt 快照" : "服务器模板原文"}` +
    (selected?.sha256 ? ` · 基线 SHA ${selected.sha256.slice(0, 12)}…` : "");
  target.classList.toggle("input-warning", bytes === 0 || bytes > 128 * 1024);
  renderBatchRuntimeSummary();
}

function loadSelectedPromptTemplate() {
  const selected = selectedBatchPrompt();
  const editor = $("#predictionPromptTemplate");
  if (!editor) return;
  editor.value = selected?.template || "";
  editor.dataset.promptId = selected?.id || "";
  updatePromptEditorSummary();
}

function renderBatchPrompts() {
  const select = $("#predictionPromptSelect");
  if (!select) return;
  const previous = select.value;
  select.innerHTML = state.batchPrompts.length
    ? state.batchPrompts
        .map((prompt) => `<option value="${escapeHtml(prompt.id)}">${escapeHtml(prompt.display_name || prompt.id)}${prompt.is_default ? " · 默认" : ""}</option>`)
        .join("")
    : '<option value="">暂无可用三分类 Prompt</option>';
  const defaultId = state.batchPromptStatus?.default_prompt_id || "";
  select.value = state.batchPrompts.some((item) => item.id === previous)
    ? previous
    : state.batchPrompts.some((item) => item.id === defaultId)
      ? defaultId
      : state.batchPrompts[0]?.id || "";
  if ($("#predictionPromptTemplate")?.dataset.promptId !== select.value) {
    loadSelectedPromptTemplate();
  }
  renderBatchCatalogFilters();
}

async function loadBatchPrompts() {
  const data = await api("/api/prediction-batches/prompts");
  state.batchPromptStatus = data;
  state.batchPrompts = data.items || [];
  renderBatchPrompts();
}

function batchInputPresets() {
  return (
    state.config?.prediction_batch?.input_policy?.profiles || [
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
    ]
  );
}

function applyBatchInputPreset() {
  const profileId = $("#predictionInputProfile")?.value || "camera_ra_event";
  const preset = batchInputPresets().find((item) => item.id === profileId);
  if (!preset) return;
  $("#predictionFrameOffsets").value = (preset.frame_offsets_ms || []).join(",");
  $("#predictionUseRaEvent").checked = Boolean(preset.use_ra_event);
  $("#predictionUseRaOptions").checked = Boolean(preset.use_ra_options);
  syncCameraFramePreset();
  renderBatchRuntimeSummary();
}

function cameraFramePresets() {
  return [
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
}

function syncCameraFramePreset() {
  const select = $("#predictionCameraPreset");
  const input = $("#predictionFrameOffsets");
  if (!select || !input) return;
  const offsets = String(input.value || "")
    .split(/[\s,，;；]+/)
    .filter(Boolean)
    .map((value) => Number(value));
  const matched = cameraFramePresets().find((preset) =>
    preset.frame_offsets_ms.length === offsets.length &&
    preset.frame_offsets_ms.every((value, index) => value === offsets[index])
  );
  select.value = matched?.id || "custom";
}

function applyCameraFramePreset() {
  const select = $("#predictionCameraPreset");
  const preset = cameraFramePresets().find(
    (item) => item.id === select?.value
  );
  if (!preset) return;
  $("#predictionFrameOffsets").value = preset.frame_offsets_ms.join(",");
  renderBatchRuntimeSummary();
}

function batchPromptFacetValue({ version = "", mode = "", sha256 = "" } = {}) {
  return JSON.stringify([String(version), String(mode), String(sha256)]);
}

function parseBatchPromptFacetValue(value) {
  if (!value) return { version: "", mode: "", sha256: "" };
  try {
    const [version = "", mode = "", sha256 = ""] = JSON.parse(value);
    return {
      version: String(version),
      mode: String(mode),
      sha256: String(sha256),
    };
  } catch {
    return { version: String(value), mode: "", sha256: "" };
  }
}

function renderBatchCatalogFilters() {
  const modelFilter = $("#batchModelFilter");
  if (modelFilter) {
    const previous = modelFilter.value;
    const modelOptions = new Map(
      state.gatewayModels.map((model) => [
        model.id,
        {
          id: model.id,
          label: model.display_name || model.id,
          count: null,
        },
      ])
    );
    (state.batchFacets.models || []).forEach((model) => {
      const existing = modelOptions.get(model.id);
      modelOptions.set(model.id, {
        id: model.id,
        label: existing?.label || `${model.id} · 历史`,
        count: model.job_count,
      });
    });
    modelFilter.innerHTML = [
      '<option value="">全部模型</option>',
      ...[...modelOptions.values()].map(
        (model) =>
          `<option value="${escapeHtml(model.id)}">${escapeHtml(model.label)}${model.count != null ? ` · ${model.count}` : ""}</option>`
      ),
    ].join("");
    modelFilter.value = modelOptions.has(previous) ? previous : "";
  }
  const promptFilter = $("#batchPromptFilter");
  if (promptFilter) {
    const previous = promptFilter.value;
    const promptOptions = new Map();
    state.batchPrompts.forEach((prompt) => {
      const facet = {
        version: prompt.id,
        mode: "catalog",
        sha256: prompt.sha256 || "",
      };
      const value = batchPromptFacetValue(facet);
      promptOptions.set(value, {
        ...facet,
        value,
        label: `${prompt.display_name || prompt.id} · 当前模板`,
        count: null,
      });
    });
    (state.batchFacets.prompts || []).forEach((prompt) => {
      const value = batchPromptFacetValue(prompt);
      const shaLabel = prompt.sha256 ? ` · ${prompt.sha256.slice(0, 10)}…` : "";
      const modeLabel =
        prompt.mode === "custom"
          ? "custom"
          : prompt.mode === "catalog"
            ? "catalog"
            : "legacy";
      const existing = promptOptions.get(value);
      promptOptions.set(value, {
        ...prompt,
        value,
        label:
          existing?.label ||
          `${prompt.version} · ${modeLabel}${shaLabel}`,
        count: prompt.job_count,
      });
    });
    promptFilter.innerHTML = [
      '<option value="">全部 Prompt</option>',
      ...[...promptOptions.values()].map(
        (prompt) =>
          `<option value="${escapeHtml(prompt.value)}">${escapeHtml(prompt.label)}${prompt.count != null ? ` · ${prompt.count}` : ""}</option>`
      ),
    ].join("");
    promptFilter.value = promptOptions.has(previous) ? previous : "";
  }
  const inputFilter = $("#batchInputFilter");
  if (inputFilter) {
    const previous = inputFilter.value;
    const inputLabels = {
      camera_ra_event: "Camera + RA Events",
      camera_ra_options: "Camera + RA/SWAG Options",
      camera_only: "Camera only",
      custom: "Custom",
    };
    const inputOptions = new Map(
      Object.entries(inputLabels).map(([id, label]) => [
        id,
        { id, label, count: null },
      ])
    );
    (state.batchFacets.input_profiles || []).forEach((profile) => {
      inputOptions.set(profile.id, {
        id: profile.id,
        label: inputLabels[profile.id] || `${profile.id} · 历史`,
        count: profile.job_count,
      });
    });
    inputFilter.innerHTML = [
      '<option value="">全部输入</option>',
      ...[...inputOptions.values()].map(
        (profile) =>
          `<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.label)}${profile.count != null ? ` · ${profile.count}` : ""}</option>`
      ),
    ].join("");
    inputFilter.value = inputOptions.has(previous) ? previous : "";
  }
}

function renderBatchRuntimeSummary() {
  const target = $("#batchModelSummary");
  if (!target) return;
  const selectedGatewayModel = state.gatewayModels.find(
    (item) => item.id === $("#predictionModelSelect")?.value
  );
  const configured =
    state.batchDefaultModel ||
    state.config?.prediction_batch?.safe_experiment ||
    state.config?.prediction_batch?.default_model ||
    state.config?.batch_prediction?.safe_experiment ||
    state.config?.batch_prediction?.default_model ||
    state.config?.batch_prediction ||
    {};
  const model =
    selectedGatewayModel?.display_name ||
    (typeof configured === "string"
      ? configured
      : configured.model_name || configured.name || configured.model);
  const prompt =
    selectedBatchPrompt()?.id ||
    (typeof configured === "object"
      ? configured.prompt_version || configured.prompt || state.config?.prediction_batch?.prompt_version
      : "");
  const source = selectedGatewayModel
    ? `${state.selectedGatewayProviderId || selectedGatewayModel.provider || "kylin"} · ${selectedGatewayModel.resolved_model_id}`
    : typeof configured === "object"
      ? configured.experiment_source || configured.runtime || configured.source
      : "";
  const frameCount = String($("#predictionFrameOffsets")?.value || "")
    .split(/[\s,，;；]+/)
    .filter(Boolean).length;
  const media = frameCount
    ? `Camera ${frameCount} 帧 · Ares Animation ${$("#predictionUseBev")?.checked ? "开启" : "关闭"}`
    : "";
  target.innerHTML = `
    <strong>${escapeHtml(model || "服务器模型网关")}</strong>
    <span>${prompt ? `Prompt · ${escapeHtml(prompt)}` : "尚未选择 Prompt"} · 输入 ${escapeHtml($("#predictionInputProfile")?.value || "camera_ra_event")}</span>
    <small>${escapeHtml([source, media].filter(Boolean).join(" · ") || "模型地址与密钥由服务器管理；Prompt 和输入按 Batch 固化")}</small>`;
}

function batchStatusLabel(status) {
  return (
    {
      queued: "排队中",
      running: "运行中",
      succeeded: "成功",
      completed: "成功",
      partial: "部分成功",
      partially_succeeded: "部分成功",
      failed: "失败",
      cancelled: "已取消",
    }[status] || status || "未知"
  );
}

function batchPublishLabel(status) {
  return (
    {
      not_requested: "未推送",
      not_published: "未推送",
      pending: "未推送",
      running: "推送中",
      publishing: "推送中",
      succeeded: "已推送",
      published: "已推送",
      partial: "部分推送",
      failed: "推送失败",
    }[status] || status || "未推送"
  );
}

function batchCounts(batch) {
  const items = batch.items || [];
  return {
    total: Number(batch.total_count ?? batch.requested_count ?? items.length ?? 0),
    completed: Number(batch.completed_count ?? 0),
    success: Number(batch.success_count ?? batch.succeeded_count ?? 0),
    failed: Number(batch.failed_count ?? 0),
  };
}

function batchSummaryText(batch) {
  if (batch.error_text) return batch.error_text;
  if (typeof batch.summary === "string") return batch.summary;
  if (batch.model_run_id) return `已生成模型 Run · ${batch.model_run_id}`;
  return "";
}

function renderBatchRequesterFilter() {
  const select = $("#batchRequesterFilter");
  if (!select) return;
  const previous = select.value;
  const mine = state.session.username;
  select.innerHTML = [
    '<option value="">全部请求人</option>',
    mine ? `<option value="__me__">我的 · ${escapeHtml(mine)}</option>` : "",
    ...state.predictionRequesters.map((item) => {
      const name = item.name || item.requested_by || "";
      const count = item.job_count ?? item.batch_count ?? item.count ?? 0;
      const trust =
        item.verified_count > 0 && item.unverified_count > 0
          ? " · 混合身份"
          : item.verified
            ? " · SSO"
            : "";
      return name
        ? `<option value="${escapeHtml(name)}">${escapeHtml(name)} · ${count} 个${trust}</option>`
        : "";
    }),
  ].join("");
  const names = state.predictionRequesters.map((item) => item.name || item.requested_by);
  select.value = previous === "__me__" || names.includes(previous) ? previous : "";
}

function batchInputSummary(batch) {
  const input = batch.input_config || {};
  const offsets = Array.isArray(input.frame_offsets_ms)
    ? input.frame_offsets_ms.join(", ")
    : "";
  return [
    batch.input_profile ? `Profile ${batch.input_profile}` : "",
    offsets ? `Camera ${input.frame_offsets_ms.length} 帧 · ${offsets} ms` : "",
    input.use_ra_event ? "RA Events" : "无 RA Events",
    input.use_ra_options ? "RA / SWAG Options" : "",
    input.use_bev_animation ? "Ares Animation · API 默认" : "Ares Animation 关闭",
  ].filter(Boolean);
}

function batchOutputLines(batch) {
  const summary = batch.summary && typeof batch.summary === "object"
    ? batch.summary
    : {};
  return [
    summary.ra_repo_commit ? `ra_auto_triage commit · ${summary.ra_repo_commit}` : "",
    summary.trail_view_id ? `Trail view · ${summary.trail_view_id}` : "",
    summary.model_run_duplicate ? "复用已有模型 Run" : "",
    summary.bag_cache_read_only ? "Bag cache · read-only" : "",
    summary.trail_write_enabled === false ? "Trail 写入 · 关闭" : "",
    batch.error_text ? `任务错误 · ${batch.error_text}` : "",
  ].filter(Boolean);
}

function renderPredictionBatchDetail(batch) {
  if (!batch) {
    return `<div class="batch-history-detail" data-batch-detail="loading"><span class="muted">正在读取运行输出…</span></div>`;
  }
  const counts = batchCounts(batch);
  const items = Array.isArray(batch.items) ? batch.items : [];
  const outputLines = batchOutputLines(batch);
  return `<div class="batch-history-detail" data-batch-detail="${escapeHtml(batch.id || "")}">
    <div class="batch-detail-heading">
      <div>
        <strong>运行输出 · ${escapeHtml(batch.name || batch.batch_name || batch.id || "")}</strong>
      </div>
      <span>${escapeHtml(batchStatusLabel(batch.status))} · ${counts.completed}/${counts.total} 完成 · 成功 ${counts.success} · 失败 ${counts.failed}</span>
    </div>
    <div class="batch-detail-meta">
      <span>${escapeHtml(batch.provider_id || "kylin")} · 模型 ${escapeHtml(batch.resolved_model_id || batch.model_name || "—")}${batch.model_validation_status === "experimental" ? " · 实验" : ""}</span>
      <span>Prompt ${escapeHtml(batch.prompt_version || "—")}${batch.prompt_mode === "custom" ? " · custom" : ""}</span>
      ${batchInputSummary(batch).map((value) => `<span>${escapeHtml(value)}</span>`).join("")}
      ${batch.model_run_id ? `<span>Model Run ${escapeHtml(batch.model_run_id)}</span>` : ""}
      ${batch.finished_at ? `<span>结束 ${formatTime(batch.finished_at)}</span>` : ""}
    </div>
    ${outputLines.length ? `<div class="batch-output-lines">${outputLines.map((line) => `<code>${escapeHtml(line)}</code>`).join("")}</div>` : ""}
    ${
      items.length
        ? `<div class="batch-result-items">${items
            .map((item) => {
              const detail = item.result?.result || item.result || {};
              const issueUrl = safeUrl(item.voyager_issue_url || "");
              return `<div class="batch-result-item">
                <strong>${escapeHtml(item.issue_id)}</strong>
                <span class="job-status status-${escapeHtml(item.status)}">${escapeHtml(batchStatusLabel(item.status))}</span>
                ${detail.model_label ? labelBadge(detail.model_label, "—") : ""}
                ${issueUrl ? `<a href="${escapeHtml(issueUrl)}" target="_blank" rel="noreferrer">打开 Voyager Issue</a>` : ""}
                ${detail.model_confidence != null ? `<small>confidence ${escapeHtml(detail.model_confidence)}</small>` : ""}
                ${detail.model_reason ? `<small class="batch-item-reason">${escapeHtml(detail.model_reason)}</small>` : ""}
                ${item.error_text ? `<small>${escapeHtml(item.error_text)}</small>` : ""}
              </div>`;
            })
            .join("")}</div>`
        : '<div class="muted">任务明细尚未生成。</div>'
    }
  </div>`;
}

function renderPredictionBatches(total = state.predictionBatches.length) {
  const list = $("#predictionBatchList");
  if (!list) return;
  $("#batchHistorySummary").textContent =
    `显示 ${state.predictionBatches.length} / ${total} 个 Batch` +
    " · 预测完成后需人工显式推送 AutoTriage";
  if (!state.predictionBatches.length) {
    list.innerHTML = '<div class="no-asset">当前筛选下没有 Batch 预测任务。</div>';
    return;
  }
  const terminal = new Set(["succeeded", "completed", "partial", "partially_succeeded"]);
  list.innerHTML = state.predictionBatches
    .map((batch) => {
      const counts = batchCounts(batch);
      const publishEnabled = Boolean(
        state.config?.prediction_batch?.autotriage_push_enabled ??
          state.config?.batch_prediction?.autotriage_push_enabled
      );
      const publishStatus =
        batch.publish_status ||
        (batch.autotriage_batch_id || batch.platform_batch_id ? "published" : "not_published");
      const canPublish =
        terminal.has(batch.status) &&
        counts.success > 0 &&
        Boolean(batch.model_run_id) &&
        Boolean(batch.prompt_template_sha256) &&
        Boolean(batch.input_profile) &&
        ["not_requested", "not_published", "pending", "failed"].includes(publishStatus);
      const batchUrl = safeUrl(
        batch.autotriage_record_url ||
          batch.record_url ||
          batch.autotriage_url ||
          batch.records_url ||
          ""
      );
      const summaryText = batchSummaryText(batch);
      const expanded = state.expandedPredictionBatchId === batch.id;
      const detail = state.predictionBatchDetails[batch.id];
      return `<article class="job-history-row batch-history-row">
        <div class="job-history-main">
          <div class="run-row-title">
            <strong>${escapeHtml(batch.name || batch.batch_name || batch.id)}</strong>
            <span class="job-status status-${escapeHtml(batch.status)}">${escapeHtml(batchStatusLabel(batch.status))}</span>
            <span class="publish-status publish-${escapeHtml(publishStatus)}">${escapeHtml(batchPublishLabel(publishStatus))}</span>
          </div>
          <div class="run-row-meta">
            <span>Provider ${escapeHtml(batch.provider_id || "kylin")}</span>
            <span>${escapeHtml(
              batch.requested_model_id && batch.requested_model_id !== batch.model_name
                ? `${batch.requested_model_id} → ${batch.model_name || batch.resolved_model_id}`
                : batch.model_name || batch.resolved_model_id || "服务器模型网关"
            )}</span>
            ${batch.model_validation_status === "experimental" ? "<span>实验模型</span>" : ""}
            ${batch.prompt_version ? `<span>Prompt ${escapeHtml(batch.prompt_version)}${batch.prompt_mode === "custom" ? ` · custom${batch.prompt_template_sha256 ? ` · ${escapeHtml(batch.prompt_template_sha256.slice(0, 10))}…` : ""}` : ""}</span>` : ""}
            ${batch.input_profile ? `<span>输入 ${escapeHtml(batch.input_profile)}</span>` : ""}
            <span>${counts.completed} / ${counts.total} 完成</span>
            <span class="batch-success-count">成功 ${counts.success}</span>
            <span class="run-failure-count">失败 ${counts.failed}</span>
            <span>${batch.requested_by ? `请求人 ${escapeHtml(batch.requested_by)}${batch.requested_by_verified ? " · SSO" : ""}` : "请求人未记录"}</span>
            <span>${formatTime(batch.created_at)}</span>
          </div>
          ${summaryText ? `<div class="job-result-preview">${escapeHtml(summaryText)}</div>` : ""}
        </div>
        <div class="run-row-actions">
          <button class="button button-quiet" type="button" data-show-batch="${escapeHtml(batch.id)}">${expanded ? "收起日志" : "查看日志"}</button>
          ${canPublish && publishEnabled ? `<button class="button button-primary" type="button" data-publish-batch="${escapeHtml(batch.id)}">推送 AutoTriage</button>` : ""}
          ${canPublish && !publishEnabled ? '<button class="button button-quiet" type="button" disabled title="生产写入需可信 SSO 域名">推送需 SSO</button>' : ""}
          ${["running", "publishing"].includes(publishStatus) ? '<button class="button button-quiet" type="button" disabled>推送中…</button>' : ""}
          ${batchUrl ? `<a class="button button-quiet" href="${escapeHtml(batchUrl)}" target="_blank" rel="noreferrer">打开 AutoTriage</a>` : ""}
        </div>
        ${expanded ? renderPredictionBatchDetail(detail) : ""}
      </article>`;
    })
    .join("");
  list.querySelectorAll("[data-show-batch]").forEach((button) => {
    button.addEventListener("click", async () => {
      const batchId = button.dataset.showBatch;
      if (state.expandedPredictionBatchId === batchId) {
        state.expandedPredictionBatchId = "";
        renderPredictionBatches(state.predictionBatchTotal);
        return;
      }
      state.expandedPredictionBatchId = batchId;
      renderPredictionBatches(state.predictionBatchTotal);
      try {
        const data = await api(
          `/api/prediction-batches/${encodeURIComponent(batchId)}`
        );
        showPredictionBatch(data.batch || data.job || data);
      } catch (error) {
        if (state.expandedPredictionBatchId === batchId) {
          state.expandedPredictionBatchId = "";
          renderPredictionBatches(state.predictionBatchTotal);
        }
        showToast(error.message, true);
      }
    });
  });
  list.querySelectorAll("[data-publish-batch]").forEach((button) => {
    button.addEventListener("click", () => publishPredictionBatch(button.dataset.publishBatch, button));
  });
}

function showPredictionBatch(batch) {
  if (!batch?.id) return;
  state.predictionBatchDetails[batch.id] = batch;
  state.expandedPredictionBatchId = batch.id;
  renderPredictionBatches(state.predictionBatchTotal);
  requestAnimationFrame(() => {
    document
      .querySelector(`[data-batch-detail="${CSS.escape(batch.id)}"]`)
      ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
}

async function loadPredictionBatches() {
  if (!$("#predictionBatchList")) return;
  const requestSeq = ++state.batchListRequestSeq;
  const params = new URLSearchParams({ page_size: "200" });
  const requesterValue = $("#batchRequesterFilter")?.value || "";
  const requester = requesterValue === "__me__" ? state.session.username : requesterValue;
  const status = $("#batchStatusFilter")?.value || "";
  const modelId = $("#batchModelFilter")?.value || "";
  const promptFacet = parseBatchPromptFacetValue(
    $("#batchPromptFilter")?.value || ""
  );
  const inputProfile = $("#batchInputFilter")?.value || "";
  if (requester) params.set("requested_by", requester);
  if (status) params.set("status", status);
  if (modelId) params.set("model_id", modelId);
  if (promptFacet.version) params.set("prompt_version", promptFacet.version);
  if (promptFacet.mode) params.set("prompt_mode", promptFacet.mode);
  if (promptFacet.sha256) params.set("prompt_sha256", promptFacet.sha256);
  if (inputProfile) params.set("input_profile", inputProfile);
  const data = await api(`/api/prediction-batches?${params.toString()}`);
  if (requestSeq !== state.batchListRequestSeq) return;
  state.predictionBatches = data.items || [];
  state.predictionBatchTotal = data.total ?? state.predictionBatches.length;
  state.predictionRequesters = data.requesters || [];
  state.batchFacets = data.facets || {
    models: [],
    prompts: [],
    input_profiles: [],
  };
  const latestSafeExperiment = state.predictionBatches.find(
    (item) => item.summary?.safe_experiment
  )?.summary?.safe_experiment;
  const incomingModel = data.safe_experiment || data.default_model || data.model;
  state.batchDefaultModel = latestSafeExperiment
    ? { ...(state.batchDefaultModel || {}), ...latestSafeExperiment }
    : incomingModel || state.batchDefaultModel;
  renderBatchRuntimeSummary();
  renderBatchRequesterFilter();
  renderBatchCatalogFilters();
  renderPredictionBatches(state.predictionBatchTotal);
}

async function loadPredictionConfig() {
  const data = await api("/api/prediction-batches/config");
  state.batchDefaultModel = {
    ...(state.batchDefaultModel || {}),
    ...(data.model || {}),
  };
  state.config = {
    ...(state.config || {}),
    prediction_batch: {
      ...(state.config?.prediction_batch || {}),
      ...data,
    },
  };
  renderGatewayProviders();
  renderBatchRuntimeSummary();
  updatePredictionBatchCount();
  await Promise.all([loadGatewayModels(), loadBatchPrompts()]);
}

async function pollPredictionBatch(batchId) {
  clearTimeout(state.pollTimer);
  state.pollingBatchId = batchId;
  const tick = async () => {
    try {
      const data = await api(`/api/prediction-batches/${encodeURIComponent(batchId)}`);
      const batch = data.batch || data.job || data;
      showPredictionBatch(batch);
      state.predictionBatches = state.predictionBatches.map((item) =>
        item.id === batch.id ? { ...item, ...batch, items: undefined } : item
      );
      renderPredictionBatches(state.predictionBatchTotal);
      const batchRunning = ["queued", "running"].includes(batch.status);
      const publishRunning = ["running", "publishing"].includes(batch.publish_status);
      if (!batchRunning && !publishRunning) {
        clearTimeout(state.pollTimer);
        state.pollTimer = null;
        state.pollingBatchId = "";
        await loadPredictionBatches();
      } else if (state.pollingBatchId === batchId) {
        state.pollTimer = setTimeout(tick, 2500);
      }
    } catch (error) {
      clearTimeout(state.pollTimer);
      state.pollTimer = null;
      state.pollingBatchId = "";
      showToast(error.message, true);
    }
  };
  await tick();
}

async function submitPredictionBatch(event) {
  event.preventDefault();
  const issueIds = predictionIssueIds();
  const invalid = issueIds.filter((issueId) => !/^[A-Za-z0-9_-]{3,128}$/.test(issueId));
  const maxIssues = Number(state.config?.prediction_batch?.max_issues || 0);
  const modelId = $("#predictionModelSelect")?.value || "";
  const selectedModel = state.gatewayModels.find((item) => item.id === modelId);
  const promptId = $("#predictionPromptSelect")?.value || "";
  const promptTemplate = $("#predictionPromptTemplate")?.value || "";
  const frameOffsetParts = String($("#predictionFrameOffsets")?.value || "")
    .split(/[\s,，;；]+/)
    .filter(Boolean);
  const frameOffsets = frameOffsetParts.map((value) => Number(value));
  const useRaEvent = Boolean($("#predictionUseRaEvent")?.checked);
  const useRaOptions = Boolean($("#predictionUseRaOptions")?.checked);
  if (!issueIds.length) return showToast("请至少输入一个 Issue ID。", true);
  if (invalid.length) return showToast(`Issue ID 格式不合法：${invalid.slice(0, 3).join("、")}`, true);
  if (!modelId || state.gatewayModelStatus?.status !== "ready" || state.gatewayModelStatus?.stale) {
    return showToast("模型目录尚未就绪，请先刷新并选择可用模型。", true);
  }
  if (!promptId || !promptTemplate.trim()) {
    return showToast("请选择 Prompt，并保留非空正文。", true);
  }
  if (
    !frameOffsets.length ||
    frameOffsets.some((value) => !Number.isInteger(value))
  ) {
    return showToast("Camera 帧偏移必须是逗号分隔的整数。", true);
  }
  if (useRaOptions && !useRaEvent) {
    return showToast("启用 RA / SWAG Options 时必须同时启用 RA Events。", true);
  }
  const experimental = selectedModel?.validation_status !== "validated";
  if (
    experimental &&
    !window.confirm(
      `模型「${selectedModel?.display_name || modelId}」在线但尚未完成 RA 基线验证。仍要用它创建实验 Batch 吗？`
    )
  ) {
    return;
  }
  if (maxIssues && issueIds.length > maxIssues) {
    return showToast(`单批最多 ${maxIssues} 个 Issue；当前 ${issueIds.length} 个。`, true);
  }
  const button = $("#createPredictionBatchButton");
  button.disabled = true;
  button.textContent = "正在创建…";
  try {
    const data = await api("/api/prediction-batches", {
      method: "POST",
      body: JSON.stringify({
        issue_ids: issueIds,
        provider_id: state.selectedGatewayProviderId || "kylin",
        model_id: modelId,
        allow_experimental_model: experimental,
        prompt_id: promptId,
        prompt_template: promptTemplate,
        input_config: {
          profile_id: $("#predictionInputProfile")?.value || "camera_ra_event",
          frame_offsets_ms: frameOffsets,
          use_ra_event: useRaEvent,
          use_ra_options: useRaOptions,
          use_bev_animation: Boolean($("#predictionUseBev")?.checked),
        },
        name: $("#predictionBatchName").value.trim() || "",
        requested_by: state.session.username || "",
      }),
    });
    const batch = data.batch || data.job || data;
    showPredictionBatch(batch);
    showToast(`Batch 已创建，共 ${issueIds.length} 个 Issue。`);
    await loadPredictionBatches();
    if (batch.id && ["queued", "running"].includes(batch.status)) await pollPredictionBatch(batch.id);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.textContent = "开始 Batch 预测";
    renderGatewayModels();
  }
}

async function publishPredictionBatch(batchId, button) {
  const batch = state.predictionBatches.find((item) => item.id === batchId);
  if (
    !window.confirm(
      `将把 Batch「${batch?.name || batchId}」的成功预测显式写入 AutoTriage，并保存关联记录链接。继续？`
    )
  ) {
    return;
  }
  button.disabled = true;
  button.textContent = "推送中…";
  try {
    const data = await api(
      `/api/prediction-batches/${encodeURIComponent(batchId)}/publish-autotriage`,
      {
        method: "POST",
        headers: { "X-RA-Triage-Request": "publish-v1" },
        body: JSON.stringify({ confirm: true }),
      }
    );
    const updated = data.batch || data.job || null;
    if (updated) showPredictionBatch(updated);
    showToast("AutoTriage 推送任务已接受，正在等待平台回查。");
    await loadPredictionBatches();
    const refreshed = state.predictionBatches.find((item) => item.id === batchId);
    if (refreshed) showPredictionBatch(refreshed);
    await pollPredictionBatch(batchId);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = "推送 AutoTriage";
    }
  }
}
