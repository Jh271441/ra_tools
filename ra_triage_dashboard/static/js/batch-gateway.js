/* ra_triage_dashboard/static/js/batch-gateway.js
 * Gateway provider/model pickers for Batch page
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
  const parts = [t("batch.issue_count_fmt", { n: ids.length })];
  if (maxIssues) parts.push(t("batch.max_issues", { limit: maxIssues }));
  if (invalid.length) parts.push(t("batch.invalid_ids", { n: invalid.length }));
  target.textContent = parts.join(" · ");
  target.classList.toggle("input-warning", Boolean(invalid.length || overLimit));
}

function providerStatusLabel(provider) {
  const selectable = Boolean(provider?.enabled && provider?.supports_batch);
  if (selectable) return t("status.available");
  if (provider?.credential_configured) return t("status.unavailable_now");
  return t("status.no_credential");
}

function selectGatewayProvider(providerId, { reloadModels = true } = {}) {
  const nextId = String(providerId || "").trim();
  if (!nextId || nextId === state.selectedGatewayProviderId) {
    closeGatewayProviderPicker();
    return;
  }
  state.selectedGatewayProviderId = nextId;
  state.selectedGatewayModelId = "";
  const modelSelect = $("#predictionModelSelect");
  if (modelSelect) modelSelect.value = "";
  renderGatewayProviders();
  closeGatewayProviderPicker();
  if (!reloadModels) return;
  loadGatewayModels({ providerId: state.selectedGatewayProviderId }).catch((error) => {
    showToast(error.message, true);
  });
}

function closeGatewayProviderPicker() {
  const picker = $("#gatewayProviderPicker");
  const panel = $("#gatewayProviderPickerPanel");
  const trigger = $("#gatewayProviderPickerTrigger");
  if (!picker || !panel) return;
  panel.hidden = true;
  picker.classList.remove("is-open");
  resetAnchoredPanel(panel);
  trigger?.setAttribute("aria-expanded", "false");
}

function bindGatewayProviderPicker() {
  const picker = $("#gatewayProviderPicker");
  const trigger = $("#gatewayProviderPickerTrigger");
  const panel = $("#gatewayProviderPickerPanel");
  if (!picker || !trigger || !panel || picker.dataset.bound === "true") return;
  picker.dataset.bound = "true";
  trigger.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (trigger.disabled) return;
    const willOpen = panel.hidden;
    closeGatewayProviderPicker();
    closeGatewayModelPicker();
    closeAllMultiFilters();
    if (!willOpen) return;
    picker.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
    const triggerWidth = trigger.getBoundingClientRect().width;
    openAnchoredPanel(panel, trigger, {
      maxHeight: 280,
      minWidth: Math.max(triggerWidth, 200),
      matchAnchorWidth: true,
      maxWidth: Math.max(triggerWidth, 360),
    });
  });
  panel.addEventListener("click", (event) => {
    event.stopPropagation();
    const option = event.target.closest("[data-gateway-provider]");
    if (!option || option.disabled || option.getAttribute("aria-disabled") === "true") return;
    selectGatewayProvider(option.dataset.gatewayProvider || "");
  });
  document.addEventListener("click", (event) => {
    if (!picker.contains(event.target) && !panel.contains(event.target)) {
      closeGatewayProviderPicker();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeGatewayProviderPicker();
  });
  document.addEventListener(
    "scroll",
    (event) => {
      if (!picker.classList.contains("is-open")) return;
      const target = event.target;
      if (target instanceof Element && target.closest(".gateway-provider-picker-panel")) return;
      closeGatewayProviderPicker();
    },
    true
  );
  window.addEventListener("resize", () => closeGatewayProviderPicker());
}

function renderGatewayProviders() {
  const target = $("#gatewayProviderSelect");
  const summary = $("#gatewayProviderPickerSummary");
  const options = $("#gatewayProviderPickerOptions");
  const trigger = $("#gatewayProviderPickerTrigger");
  if (!target) return;
  bindGatewayProviderPicker();
  const catalog = state.config?.prediction_batch?.providers || {};
  const providers = Array.isArray(catalog.providers) ? catalog.providers : [];
  if (!providers.length) {
    target.innerHTML = `<option value="">${escapeHtml(t("batch.no_provider"))}</option>`;
    target.disabled = true;
    if (summary) summary.textContent = t("batch.no_provider");
    if (options) options.innerHTML = `<div class="multi-filter-empty">${escapeHtml(t("batch.no_providers"))}</div>`;
    if (trigger) trigger.disabled = true;
    closeGatewayProviderPicker();
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
      const status = providerStatusLabel(provider);
      return `<option value="${escapeHtml(provider.id)}" ${selectable ? "" : "disabled"}>${escapeHtml(provider.display_name || provider.id)} · ${escapeHtml(status)}</option>`;
    })
    .join("");
  target.value = selectedId;
  target.disabled = false;
  if (trigger) trigger.disabled = false;
  const selectedProvider =
    providers.find((item) => item.id === selectedId) || providers[0] || null;
  if (summary) {
    summary.textContent = selectedProvider
      ? `${selectedProvider.display_name || selectedProvider.id} · ${providerStatusLabel(selectedProvider)}`
      : t("batch.pick_provider");
  }
  if (options) {
    options.innerHTML = providers
      .map((provider) => {
        const selectable = Boolean(provider.enabled && provider.supports_batch);
        const active = provider.id === selectedId;
        const status = providerStatusLabel(provider);
        const label = `${provider.display_name || provider.id} · ${status}`;
        return `<button class="gateway-provider-option${active ? " is-active" : ""}${selectable ? "" : " is-disabled"}" type="button" role="option" data-gateway-provider="${escapeHtml(provider.id)}" aria-selected="${active ? "true" : "false"}" ${selectable ? "" : "disabled aria-disabled=\"true\""} title="${escapeHtml(label)}">
          <span class="gateway-provider-option-check" aria-hidden="true">${active ? "✓" : ""}</span>
          <span class="gateway-provider-option-label">${escapeHtml(label)}</span>
        </button>`;
      })
      .join("");
  }
}

function gatewayModelTier(model) {
  return model?.unavailable
    ? t("status.unavailable")
    : model?.validation_status === "validated"
      ? t("status.validated")
      : t("status.experimental");
}

function gatewayModelOptionMarkup(model, active = false, attribute = "data-gateway-model") {
  const unavailable = Boolean(model?.unavailable);
  const tier = gatewayModelTier(model);
  const resolved = model?.resolved_model_id && model.resolved_model_id !== model.id
    ? model.resolved_model_id
    : model?.id || "";
  const displayName = model?.display_name || model?.id || t("batch.unnamed_model");
  const title = `${displayName} · ${resolved}`;
  return `<button class="gateway-model-option ${active ? "active" : ""} ${unavailable ? "unavailable" : ""}" type="button" title="${escapeHtml(title)}" ${attribute}="${escapeHtml(model?.id || "")}" ${unavailable ? "disabled" : ""}>
    <span class="gateway-model-option-head">
      <strong>${escapeHtml(displayName)}</strong>
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
  resetAnchoredPanel(panel);
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
    closeGatewayProviderPicker();
    closeAllMultiFilters();
    if (!willOpen) return;
    picker.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
    const triggerWidth = trigger.getBoundingClientRect().width;
    openAnchoredPanel(panel, trigger, {
      maxHeight: 360,
      minWidth: Math.max(triggerWidth, 240),
      matchAnchorWidth: true,
      maxWidth: Math.max(triggerWidth, 420),
    });
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
    if (!picker.contains(event.target) && !panel.contains(event.target)) {
      closeGatewayModelPicker();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeGatewayModelPicker();
  });
  document.addEventListener(
    "scroll",
    (event) => {
      if (!picker.classList.contains("is-open")) return;
      const target = event.target;
      if (target instanceof Element && target.closest(".gateway-model-picker-panel")) return;
      closeGatewayModelPicker();
    },
    true
  );
  window.addEventListener("resize", () => closeGatewayModelPicker());
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
      display_name: `${previous}${t("batch.model_unavailable_suffix")}`,
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
              ? t("status.unavailable")
              : model.validation_status === "validated"
                ? t("status.validated")
                : t("status.experimental");
            return `<option value="${escapeHtml(model.id)}">[${tier}] ${escapeHtml(model.display_name || model.id)}</option>`;
          }
        )
        .join("")
    : `<option value="">${escapeHtml(t("batch.no_models"))}</option>`;
  select.value = unavailableSelection ? previous : selectedModel?.id || "";
  state.selectedGatewayModelId = select.value;
  const pickerSummary = $("#gatewayModelPickerSummary");
  const pickerOptions = $("#gatewayModelPickerOptions");
  if (pickerSummary) {
    const selectedForPicker = displayModels.find((model) => model.id === select.value);
    pickerSummary.textContent = selectedForPicker
      ? `[${gatewayModelTier(selectedForPicker)}] ${selectedForPicker.display_name || selectedForPicker.id}`
      : t("batch.no_models");
  }
  if (pickerOptions) {
    pickerOptions.innerHTML = displayModels.length
      ? displayModels.map((model) => gatewayModelOptionMarkup(
          model,
          !model.unavailable && model.id === state.selectedGatewayModelId,
          "data-gateway-picker-model",
        )).join("")
      : `<div class="muted">${escapeHtml(t("batch.no_models_dot"))}</div>`;
  }
  if (listTarget) {
    listTarget.innerHTML = displayModels.length
      ? displayModels.map((model) => gatewayModelOptionMarkup(
          model,
          !model.unavailable && model.id === state.selectedGatewayModelId,
        )).join("")
      : `<div class="muted">${escapeHtml(t("batch.no_models_dot"))}</div>`;
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
    ? t("batch.model_gone", { id: previous })
    : ready
      ? `${t("batch.model_counts", {
          v: state.gatewayModels.filter((model) => model.validation_status === "validated").length,
          e: state.gatewayModels.filter((model) => model.validation_status !== "validated").length,
        })} · ${visibleModels.length}`
      : catalog.message || t("batch.catalog_not_ready");
  if (createButton) createButton.disabled = !ready;
  renderBatchCatalogFilters();
  renderBatchRuntimeSummary();
}

