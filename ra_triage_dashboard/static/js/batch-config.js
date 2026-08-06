/* ra_triage_dashboard/static/js/batch-config.js
 * Batch prompt/input presets and catalog filters
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
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

