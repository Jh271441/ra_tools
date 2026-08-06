/* ra_triage_dashboard/static/js/batch.js
 * Batch job history, detail, create/submit
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
async function loadGatewayModels({ refresh = false, providerId = "" } = {}) {
  const requestSeq = ++state.gatewayModelRequestSeq;
  const statusTarget = $("#gatewayModelStatus");
  if (statusTarget) {
    statusTarget.className = "gateway-model-status";
    statusTarget.textContent = refresh ? t("batch.refreshing_catalog") : t("batch.fetching_catalog");
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

async function loadBatchPrompts() {
  const data = await api("/api/prediction-batches/prompts");
  state.batchPromptStatus = data;
  state.batchPrompts = data.items || [];
  renderBatchPrompts();
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
            ${batch.model_validation_status === "experimental" ? `<span>${escapeHtml(t("status.experimental"))}</span>` : ""}
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
    return showToast(t("batch.catalog_not_ready"), true);
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
    button.textContent = t("batch.start");
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
