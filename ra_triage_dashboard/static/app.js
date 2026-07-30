const LABELS = ["误触发", "正确触发", "无需协助"];

const state = {
  config: null,
  cases: [],
  selectedId: "",
  selectedCase: null,
  modelRuns: [],
  selectedRunId: "",
  failureOnly: false,
  clusterKey: "",
  selectedAnnotationLabel: "",
  pollingJobId: "",
  pollTimer: null,
  media: { kind: "bev", index: 0 },
  session: { username: "", source: "anonymous", authenticated: false, verified: false },
  sidebarCollapsed: false,
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function safeUrl(url) {
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

function labelBadge(label, fallback = "—") {
  const actual = label || "";
  const className = LABELS.includes(actual) ? `label-${actual}` : "label-empty";
  return `<span class="label-badge ${className}">${escapeHtml(actual || fallback)}</span>`;
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? escapeHtml(value) : date.toLocaleString("zh-CN", { hour12: false });
}

function evidenceLabel(key) {
  return state.config?.missing_evidence_catalog?.find((item) => item.key === key)?.label || key;
}

function frameLabel(frame) {
  if (frame.offset_ms !== undefined && frame.offset_ms !== null) {
    const seconds = Math.round(Number(frame.offset_ms) / 1000);
    return `${seconds >= 0 ? "+" : ""}${seconds}s`;
  }
  if (frame.offset_sec !== undefined && frame.offset_sec !== null) {
    const seconds = Number(frame.offset_sec);
    return `${seconds >= 0 ? "+" : ""}${seconds}s`;
  }
  return frame.frame_number !== undefined ? `#${frame.frame_number}` : "帧";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `请求失败 (${response.status})`);
  return payload;
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.remove("hidden", "error");
  if (isError) toast.classList.add("error");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 4600);
}

function applySidebarState() {
  $("#appShell").classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  $("#sidebarToggle").setAttribute("aria-expanded", String(!state.sidebarCollapsed));
  $("#sidebarToggle").title = state.sidebarCollapsed ? "展开工具栏" : "折叠工具栏";
}

function toggleSidebar() {
  state.sidebarCollapsed = !state.sidebarCollapsed;
  localStorage.setItem("ra-triage-sidebar-collapsed", String(state.sidebarCollapsed));
  applySidebarState();
}

function validDisplayName(value) {
  const username = String(value || "").trim();
  return /^[A-Za-z0-9._@-]{1,128}$/.test(username) ? username : "";
}

async function browserLcaUsername() {
  const endpoints =
    window.location.protocol === "https:"
      ? ["https://127.0.0.1:19888/lcainfo"]
      : ["http://127.0.0.1:18888/lcainfo"];
  for (const endpoint of endpoints) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1500);
    try {
      const response = await fetch(endpoint, {
        credentials: "omit",
        mode: "cors",
        signal: controller.signal,
      });
      if (!response.ok) continue;
      const payload = await response.json();
      const username = validDisplayName(payload?.LocalUserAccount);
      if (username) return username;
    } catch {
      // LCA is an optional display-name fallback on direct-IP deployments.
    } finally {
      clearTimeout(timer);
    }
  }
  return "";
}

function renderSession() {
  const username = state.session.username;
  $("#sessionUserName").textContent = username || "SSO 未接入";
  $("#userAvatar").textContent = username ? username.slice(0, 1).toUpperCase() : "?";
  $("#sessionUserSource").textContent = state.session.verified
    ? "企业 SSO · 已验证"
    : username
      ? "本机 LCA · 未验证"
      : "直接 IP 会话";
  $("#sidebarUser").title = state.session.verified
    ? `可信代理认证：${username}`
    : username
      ? `本机 LCA 用户：${username}（仅作显示与默认标注人）`
      : "当前没有可用的用户名";
  const requestedBy = $("#requestedByInput");
  if (requestedBy && username && !requestedBy.value) requestedBy.value = username;
  if (requestedBy) requestedBy.readOnly = Boolean(state.session.verified);
}

async function loadSession() {
  const serverSession = await api("/api/session");
  if (serverSession.authenticated && validDisplayName(serverSession.username)) {
    state.session = serverSession;
  } else {
    const username = serverSession.browser_lca_fallback ? await browserLcaUsername() : "";
    state.session = {
      username,
      source: username ? "browser_lca_unverified" : "anonymous",
      authenticated: false,
      verified: false,
    };
  }
  renderSession();
}

function renderConfig() {
  const baseline = state.config?.baseline || {};
  $(".header-metrics")?.setAttribute("title", baseline.message || "0508 baseline GT 只读");
}

async function loadConfig() {
  state.config = await api("/api/dashboard-config");
  renderConfig();
}

function renderOverview(data) {
  $("#statIssues").textContent = data.issues ?? "—";
  $("#statFailures").textContent = data.model_failures ?? "—";
  $("#statReviewed").textContent = data.reviewed_failures ?? data.labelled ?? "—";
  $("#statPredictions").textContent = data.predictions ?? "—";
  renderActiveRun(data);
}

async function loadOverview() {
  const query = state.selectedRunId ? `?model_run_id=${encodeURIComponent(state.selectedRunId)}` : "";
  renderOverview(await api(`/api/overview${query}`));
}

async function loadStatus() {
  const data = await api("/api/status");
  if (data.baseline || data.trail_sync) {
    state.config = {
      ...(state.config || {}),
      baseline: data.baseline || state.config?.baseline,
      trail_sync: data.trail_sync || state.config?.trail_sync,
    };
    renderConfig();
  }
}

async function loadRuns({ preferDefault = false } = {}) {
  const data = await api("/api/model-runs");
  state.modelRuns = data.items || [];
  const select = $("#modelRunFilter");
  const previousRunId = state.selectedRunId;
  const preferredRunId =
    data.default_model_run_id ||
    state.config?.default_model_run_id ||
    (preferDefault ? state.modelRuns[0]?.id || "" : "");
  const candidate = preferDefault
    ? preferredRunId
    : state.selectedRunId || data.default_model_run_id || state.config?.default_model_run_id || "";
  select.innerHTML = `<option value="">未选择模型 run</option>${state.modelRuns
    .map((run) => {
      const tag = run.is_default ? "默认 · " : "";
      return `<option value="${escapeHtml(run.id)}">${tag}${escapeHtml(run.name)} · ${run.baseline_prediction_count ?? 0} 条 · 错 ${run.failure_count ?? 0}</option>`;
    })
    .join("")}`;
  state.selectedRunId = state.modelRuns.some((run) => run.id === candidate) ? candidate : "";
  select.value = state.selectedRunId;
  const failure = $("#failureOnlyInput");
  failure.disabled = !state.selectedRunId;
  if (preferDefault && !previousRunId && state.selectedRunId) state.failureOnly = true;
  if (!state.selectedRunId) state.failureOnly = false;
  failure.checked = state.failureOnly;
  renderActiveRun();
  renderRunManager();
}

function activeRun() {
  return state.modelRuns.find((run) => run.id === state.selectedRunId);
}

function renderActiveRun(overview = null) {
  const run = activeRun();
  $("#activeRunName").textContent = run?.name || "尚未选择模型 run";
  if (!run) {
    $("#activeRunMeta").textContent = state.config?.trail_sync?.message || "同步 Trail 字段或导入 JSON / CSV / XLSX";
    return;
  }
  const coverage = overview?.predictions ?? run.baseline_prediction_count ?? 0;
  const failures = overview?.model_failures ?? run.failure_count ?? 0;
  const reviewed = overview?.reviewed_failures;
  $("#activeRunMeta").textContent =
    `${coverage} / ${state.config?.baseline?.count || "—"} 覆盖 · ${failures} 条判断失败` +
    `${reviewed === undefined ? "" : ` · ${reviewed} 条已复核`}` +
    ` · ${run.kind === "trail_snapshot" ? "Trail 快照" : "文件导入"}`;
}

function renderRunManager() {
  const list = $("#modelRunList");
  if (!list) return;
  const totalCoverage = state.modelRuns.reduce((sum, run) => sum + Number(run.baseline_prediction_count || 0), 0);
  $("#runManagerSummary").textContent = `${state.modelRuns.length} 个不可变 run · 累计 ${totalCoverage} 条 baseline 预测记录`;
  if (!state.modelRuns.length) {
    list.innerHTML = '<div class="no-asset">暂无模型 run。可上传 JSON / CSV / XLSX，或同步 Trail 字段。</div>';
    return;
  }
  list.innerHTML = state.modelRuns
    .map(
      (run) => `<article class="run-row ${run.id === state.selectedRunId ? "active" : ""}">
        <div class="run-row-main">
          <div class="run-row-title">
            <strong>${escapeHtml(run.name)}</strong>
            ${run.is_default ? '<span class="run-default-badge">默认</span>' : ""}
          </div>
          <div class="run-row-meta">
            <span>${run.baseline_prediction_count ?? 0} / ${state.config?.baseline?.count || "—"} 覆盖</span>
            <span>${run.failure_count ?? 0} 条失败</span>
            <span>${run.kind === "trail_snapshot" ? "Trail 快照" : "文件导入"}</span>
            <span>${formatTime(run.created_at)}</span>
          </div>
          <div class="run-row-source" title="${escapeHtml(run.source_name || "")}">${escapeHtml(run.source_name || "无来源文件")}</div>
        </div>
        <div class="run-row-actions">
          <button class="button ${run.id === state.selectedRunId ? "button-primary" : "button-quiet"}" type="button" data-use-run="${escapeHtml(run.id)}">${run.id === state.selectedRunId ? "使用中" : "用于 Review"}</button>
          ${run.is_default ? "" : `<button class="button button-quiet" type="button" data-default-run="${escapeHtml(run.id)}">设为默认</button>`}
        </div>
      </article>`
    )
    .join("");
  list.querySelectorAll("[data-use-run]").forEach((button) => {
    button.addEventListener("click", () => useModelRun(button.dataset.useRun));
  });
  list.querySelectorAll("[data-default-run]").forEach((button) => {
    button.addEventListener("click", () => setDefaultRun(button.dataset.defaultRun));
  });
}

async function useModelRun(runId) {
  if (!state.modelRuns.some((run) => run.id === runId)) return;
  state.selectedRunId = runId;
  state.failureOnly = true;
  state.selectedId = "";
  $("#modelRunFilter").value = runId;
  $("#failureOnlyInput").disabled = false;
  $("#failureOnlyInput").checked = true;
  renderActiveRun();
  renderRunManager();
  await Promise.all([loadCases({ keepSelection: false }), loadClusters(), loadOverview()]);
  closeDialog("runManagerDialog");
}

async function setDefaultRun(runId) {
  try {
    await api(`/api/model-runs/${encodeURIComponent(runId)}/default`, { method: "POST", body: "{}" });
    await loadRuns();
    await loadOverview();
    showToast("已更新默认模型 run；历史输出未被改写。");
  } catch (error) {
    showToast(error.message, true);
  }
}

function issueRow(item) {
  const isSelected = item.issue_id === state.selectedId;
  const title = item.title || item.scenario || "未命名 issue";
  const annotation = item.annotation?.label;
  const prediction = item.prediction?.label;
  const mismatch = item.prediction?.mismatch;
  return `
    <button class="issue-row ${isSelected ? "selected" : ""}" data-issue-id="${escapeHtml(item.issue_id)}">
      <div class="issue-row-top">
        <span class="issue-id">${escapeHtml(item.issue_id)}</span>
        ${mismatch ? '<span class="mismatch-chip">MISMATCH</span>' : labelBadge(annotation, "待 review")}
      </div>
      <div class="issue-title">${escapeHtml(title)}</div>
      <div class="issue-row-meta">
        ${labelBadge(item.gt_label, "GT —")}
        ${prediction ? labelBadge(prediction, "模型 —") : '<span class="quiet-meta">模型 —</span>'}
      </div>
      ${item.annotation?.missing_evidence?.length ? `<div class="row-evidence">${item.annotation.missing_evidence.map((key) => `<span>${escapeHtml(evidenceLabel(key))}</span>`).join("")}</div>` : ""}
    </button>`;
}

function renderCases(data) {
  state.cases = data.items || [];
  $("#caseCount").textContent = data.total ?? 0;
  const list = $("#issueList");
  if (!state.cases.length) {
    const hint = state.failureOnly ? "没有符合条件的模型失败 case。可切换 model run 或关闭失败筛选。" : "没有匹配的 Issue。";
    list.innerHTML = `<div class="no-asset">${hint}</div>`;
    return;
  }
  list.innerHTML = state.cases.map(issueRow).join("");
  list.querySelectorAll("[data-issue-id]").forEach((element) => {
    element.addEventListener("click", () => selectCase(element.dataset.issueId));
  });
}

async function loadCases({ keepSelection = true } = {}) {
  const params = new URLSearchParams();
  const search = $("#searchInput").value.trim();
  const gtLabel = $("#gtFilter").value;
  const annotationLabel = $("#annotationFilter").value;
  state.selectedRunId = $("#modelRunFilter").value;
  state.failureOnly = Boolean($("#failureOnlyInput").checked && state.selectedRunId);
  if (search) params.set("search", search);
  if (gtLabel) params.set("gt_label", gtLabel);
  if (annotationLabel) params.set("annotation_label", annotationLabel);
  if (state.selectedRunId) params.set("model_run_id", state.selectedRunId);
  if (state.failureOnly) params.set("failure_only", "true");
  if (state.clusterKey) params.set("missing_evidence", state.clusterKey);
  params.set("page_size", "1500");
  renderCases(await api(`/api/cases?${params.toString()}`));
  if (!keepSelection || !state.cases.some((item) => item.issue_id === state.selectedId)) {
    if (state.cases[0]) await selectCase(state.cases[0].issue_id);
    else clearDetail();
  }
}

async function loadClusters() {
  const params = new URLSearchParams();
  if (state.selectedRunId) params.set("model_run_id", state.selectedRunId);
  params.set("failure_only", String(Boolean(state.failureOnly && state.selectedRunId)));
  const data = await api(`/api/review-clusters?${params.toString()}`);
  const list = $("#clusterList");
  if (!(data.items || []).length) {
    list.innerHTML = '<span class="muted">标注缺失信息后，这里会按错误模式自动聚类。</span>';
    return;
  }
  list.innerHTML = data.items
    .map(
      (item) => `<button type="button" class="cluster-chip ${state.clusterKey === item.key ? "active" : ""}" data-cluster-key="${escapeHtml(item.key)}">
        <span>${escapeHtml(evidenceLabel(item.key))}</span><b>${item.count}</b>
      </button>`
    )
    .join("");
  list.querySelectorAll("[data-cluster-key]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.clusterKey = button.dataset.clusterKey === state.clusterKey ? "" : button.dataset.clusterKey;
      await loadCases({ keepSelection: false });
      await loadClusters();
    });
  });
}

function clearDetail() {
  state.selectedId = "";
  state.selectedCase = null;
  $("#openInferButton").disabled = true;
  $("#detailPane").innerHTML = `
    <div class="empty-state">
      <div class="empty-glyph" aria-hidden="true">+</div>
      <h2>选择一个 case 开始 review</h2>
      <p>可在左侧筛选失败 case；模型 run 的完整历史与导入操作放在全局工具栏中。</p>
    </div>`;
  $("#reviewPane").innerHTML = `
    <div class="review-placeholder"><span class="eyebrow">HUMAN REVIEW</span><h2>人工复核</h2><p>选择 Issue 后记录结论和模型遗漏的关键信息。</p></div>`;
}

function heroFrameIndex(frames) {
  const exact = frames.findIndex((frame) => Number(frame.offset_ms ?? frame.offset_sec * 1000) === 0);
  if (exact >= 0) return exact;
  return Math.floor(frames.length / 2);
}

function heroMediaSection(bev, camera) {
  const frames = bev?.frames || [];
  if (!bev?.available || !frames.length) {
    return '<section class="hero-media"><div class="section-heading"><div><span class="eyebrow">ARES CAPTURE</span><h3>BEV 主视图</h3></div></div><div class="no-asset">没有找到 Ares Capture BEV 帧。</div></section>';
  }
  const index = heroFrameIndex(frames);
  const frame = frames[index];
  const cameraCount = camera?.frames?.length || 0;
  return `
    <section class="hero-media">
      <div class="section-heading">
        <div><span class="eyebrow">PRIMARY REVIEW CANVAS</span><h3>Ares Capture · BEV</h3></div>
        <small>默认 ${escapeHtml(frameLabel(frame))} · 点击进入时序预览</small>
      </div>
      <button type="button" class="hero-media-button" data-media-kind="bev" data-media-index="${index}" aria-label="打开 BEV 与 Camera 时序预览">
        <img src="${escapeHtml(frame.url)}" alt="Ares Capture BEV ${escapeHtml(frameLabel(frame))}" />
        <span class="hero-media-overlay">展开预览 · ${escapeHtml(frameLabel(frame))}</span>
      </button>
      <div class="hero-media-meta">
        <span><b>${frames.length}</b> 帧 BEV 时序</span>
        <span>${cameraCount ? `<b>${cameraCount}</b> 帧 Camera 可在预览中切换` : "Camera 暂不可用"}</span>
      </div>
    </section>`;
}

function predictionCards(caseData) {
  const predictions = caseData.predictions || [];
  if (!predictions.length) {
    return '<div class="no-asset">当前 case 没有模型输出。可同步 Trail 字段、上传结果文件，或运行单 case 推理。</div>';
  }
  return `<div class="model-list">${predictions
    .map((prediction) => {
      const selected = prediction.model_run_id === state.selectedRunId;
      const extra = prediction.model_extra?.ra_stuck_auto_result_info;
      const detail = prediction.model_reason || (typeof extra === "object" ? extra.text || "" : "") || "模型未返回解释。";
      return `<article class="model-card ${selected ? "active" : ""}">
        <div class="model-card-head"><div><span class="eyebrow">${escapeHtml(prediction.run_kind || "model run")}</span><h3>${escapeHtml(prediction.run_name || "模型输出")}</h3></div>${labelBadge(prediction.model_label, "未输出")}</div>
        <p>${escapeHtml(detail)}</p>
        <div class="model-card-meta">${prediction.model_confidence ?? "—"} confidence · ${formatTime(prediction.created_at)}</div>
      </article>`;
    })
    .join("")}</div>`;
}

function renderDetail(caseData) {
  const title = caseData.title || caseData.scenario || "未命名 issue";
  const primary = (caseData.predictions || []).find((item) => item.model_run_id === state.selectedRunId) || caseData.predictions?.[0];
  const trailUrl = safeUrl(caseData.trail_url);
  $("#detailPane").innerHTML = `
    <div class="detail-header">
      <div class="detail-title-row">
        <div class="detail-title"><span class="eyebrow">CASE REVIEW</span><h2>${escapeHtml(title)}</h2><span class="detail-id">${escapeHtml(caseData.issue_id)}</span></div>
        <div class="detail-actions">${trailUrl ? `<a class="button button-quiet" href="${escapeHtml(trailUrl)}" target="_blank" rel="noreferrer">打开 Trail</a>` : ""}</div>
      </div>
      <p class="detail-summary">${escapeHtml(caseData.summary || caseData.review_note || "暂无补充描述。请结合 BEV、Camera 与触发后时序复核。")}</p>
      <div class="comparison-strip">
        <div><span>0508 GT</span>${labelBadge(caseData.gt_label, "GT 缺失")}</div>
        <div><span>当前模型</span>${labelBadge(primary?.model_label, "未输出")}</div>
        <div><span>对比</span><b class="${primary?.model_label && primary.model_label !== caseData.gt_label ? "comparison-fail" : "comparison-neutral"}">${primary?.model_label ? primary.model_label === caseData.gt_label ? "一致" : "不一致" : "不可比较"}</b></div>
      </div>
      ${caseData.review_note ? `<div class="review-note"><span>历史备注</span>${escapeHtml(caseData.review_note)}</div>` : ""}
    </div>
    ${heroMediaSection(caseData.assets, caseData.camera)}
    <section class="section"><div class="section-heading"><div><span class="eyebrow">MODEL COMPARISON</span><h3>模型输出历史</h3></div><small>默认 run 会高亮</small></div>${predictionCards(caseData)}</section>`;
  $("#openInferButton").disabled = false;
  $("#detailPane").querySelectorAll("[data-media-kind]").forEach((button) => {
    button.addEventListener("click", () => openMedia(button.dataset.mediaKind, Number(button.dataset.mediaIndex)));
  });
}

function annotationHistory(annotations) {
  if (!annotations?.length) return '<p class="muted history-empty">尚无人工 review；保存后会保留旧版本。</p>';
  return annotations
    .map(
      (annotation) => `<article class="history-row">
        <div class="history-head">${labelBadge(annotation.label, annotation.review_status === "needs_gt_review" ? "GT 待复核" : "已记录")}<span>${formatTime(annotation.created_at)}</span></div>
        ${annotation.missing_evidence?.length ? `<div class="tags">${annotation.missing_evidence.map((key) => `<span class="tag evidence-tag">${escapeHtml(evidenceLabel(key))}</span>`).join("")}</div>` : ""}
        ${annotation.tags?.length ? `<div class="tags">${annotation.tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
        ${annotation.note ? `<p>${escapeHtml(annotation.note)}</p>` : ""}
        ${annotation.author ? `<small>${escapeHtml(annotation.author)}</small>` : ""}
      </article>`)
    .join("");
}

function renderReview(caseData) {
  const previous = caseData.annotations?.[0] || {};
  state.selectedAnnotationLabel = previous.label || "";
  const chosenEvidence = new Set(previous.missing_evidence || []);
  const catalog = state.config?.missing_evidence_catalog || [];
  const author = state.session.username || previous.author || "";
  const authorLocked = Boolean(state.session.verified && state.session.username);
  $("#reviewPane").innerHTML = `
    <div class="review-title"><div><span class="eyebrow">HUMAN REVIEW</span><h2>标注与错误归因</h2></div><span class="review-issue">${escapeHtml(caseData.issue_id)}</span></div>
    <form class="review-form" id="annotationForm">
      <div class="review-context"><span>GT ${escapeHtml(caseData.gt_label || "—")}</span><span>模型 ${escapeHtml((caseData.predictions || []).find((item) => item.model_run_id === state.selectedRunId)?.model_label || "—")}</span></div>
      <div><label><span>人工最终判断</span></label><div class="label-buttons">${LABELS.map((label) => `<button class="label-choice ${state.selectedAnnotationLabel === label ? "active" : ""}" data-annotation-label="${label}" type="button">${label}</button>`).join("")}</div></div>
      <label><span>复核状态</span><select id="reviewStatusInput"><option value="pending">待补充</option><option value="reviewed" ${previous.review_status === "reviewed" ? "selected" : ""}>已复核</option><option value="needs_gt_review" ${previous.review_status === "needs_gt_review" ? "selected" : ""}>GT 需复核</option></select></label>
      <label class="review-reason">
        <span>模型为什么判错？</span>
        <small>请写清交通灯、routing、绕行空间、时序或 RA / SWAG 操作链等关键依据。</small>
        <textarea id="annotationNote" placeholder="例如：自车 routing 为右转，前车直行等灯；右侧存在可安全通行空间，模型只看到排队而遗漏 routing 与绕行条件。">${escapeHtml(previous.note || "")}</textarea>
      </label>
      <details class="evidence-dropdown">
        <summary>缺失信息（多选）<span class="evidence-summary-count" id="evidenceSummaryCount">已选 ${chosenEvidence.size} 项</span></summary>
        <div class="evidence-options">${catalog.map((item) => `<label class="evidence-option" title="${escapeHtml(item.hint || "")}"><input type="checkbox" name="missingEvidence" value="${escapeHtml(item.key)}" ${chosenEvidence.has(item.key) ? "checked" : ""} /><span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.hint || "")}</small></span></label>`).join("")}</div>
      </details>
      <label><span>补充 tags（可选，逗号分隔）</span><input id="annotationTags" value="${escapeHtml((previous.tags || []).join(", "))}" placeholder="例如：右转, 双闪, 遮挡" autocomplete="off" /></label>
      <label><span>标注人${authorLocked ? "（SSO）" : "（可编辑）"}</span><input id="annotationAuthor" value="${escapeHtml(author)}" placeholder="姓名或工号" autocomplete="off" ${authorLocked ? "readonly" : ""} /></label>
      <button class="button button-primary full-width" type="submit">保存新的 review 版本</button>
    </form>
    <section class="annotation-history"><div class="subheading"><span>Review 历史</span><small>追加式，不覆盖旧记录</small></div>${annotationHistory(caseData.annotations)}</section>`;
  $("#reviewPane").querySelectorAll("[data-annotation-label]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedAnnotationLabel = button.dataset.annotationLabel;
      $("#reviewPane").querySelectorAll("[data-annotation-label]").forEach((item) => item.classList.toggle("active", item === button));
    });
  });
  $("#reviewPane").querySelectorAll('input[name="missingEvidence"]').forEach((input) => {
    input.addEventListener("change", updateEvidenceSummary);
  });
  $("#annotationForm").addEventListener("submit", saveAnnotation);
}

function updateEvidenceSummary() {
  const count = document.querySelectorAll('input[name="missingEvidence"]:checked').length;
  const target = $("#evidenceSummaryCount");
  if (target) target.textContent = `已选 ${count} 项`;
}

async function selectCase(issueId) {
  if (!issueId) return;
  state.selectedId = issueId;
  renderCases({ items: state.cases, total: $("#caseCount").textContent });
  try {
    const data = await api(`/api/cases/${encodeURIComponent(issueId)}`);
    state.selectedCase = data;
    renderDetail(data);
    renderReview(data);
    history.replaceState({}, "", `#${encodeURIComponent(issueId)}`);
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveAnnotation(event) {
  event.preventDefault();
  if (!state.selectedId) return;
  const payload = {
    label: state.selectedAnnotationLabel,
    review_status: $("#reviewStatusInput").value,
    tags: $("#annotationTags").value.split(",").map((tag) => tag.trim()).filter(Boolean),
    missing_evidence: [...document.querySelectorAll('input[name="missingEvidence"]:checked')].map((input) => input.value),
    note: $("#annotationNote").value,
    author: $("#annotationAuthor").value,
  };
  try {
    await api(`/api/cases/${encodeURIComponent(state.selectedId)}/annotations`, { method: "POST", body: JSON.stringify(payload) });
    showToast("已保存新的 review 版本，并更新缺失信息聚类。");
    await Promise.all([loadOverview(), loadClusters(), loadCases()]);
    await selectCase(state.selectedId);
  } catch (error) {
    showToast(error.message, true);
  }
}

function mediaFrames(kind) {
  if (!state.selectedCase) return [];
  return (kind === "bev" ? state.selectedCase.assets : state.selectedCase.camera)?.frames || [];
}

function openDialog(id) {
  const dialog = $(`#${id}`);
  if (!dialog.open) dialog.showModal();
}

function closeDialog(id) {
  const dialog = $(`#${id}`);
  if (dialog.open) dialog.close();
}

function renderMediaDialog() {
  const bev = mediaFrames("bev");
  const camera = mediaFrames("camera");
  if (!mediaFrames(state.media.kind).length) state.media.kind = bev.length ? "bev" : "camera";
  const frames = mediaFrames(state.media.kind);
  state.media.index = Math.max(0, Math.min(state.media.index, Math.max(frames.length - 1, 0)));
  const current = frames[state.media.index];
  if (!current) return;
  $("#mediaEyebrow").textContent = state.media.kind === "bev" ? "ARES CAPTURE / BEV" : "CAMERA / AFTER_COMPRESS";
  $("#mediaTitle").textContent = `${state.selectedCase?.issue_id || ""} · ${frameLabel(current)} · ${state.media.index + 1}/${frames.length}`;
  $("#mediaPreviewImage").src = current.url;
  $("#mediaPreviewImage").alt = `${state.media.kind} ${frameLabel(current)}`;
  $("#mediaModeTabs").innerHTML = `
    <button type="button" class="media-mode ${state.media.kind === "bev" ? "active" : ""}" data-media-mode="bev" ${bev.length ? "" : "disabled"}>BEV <span>${bev.length}</span></button>
    <button type="button" class="media-mode ${state.media.kind === "camera" ? "active" : ""}" data-media-mode="camera" ${camera.length ? "" : "disabled"}>Camera <span>${camera.length}</span></button>`;
  $("#mediaTimeline").innerHTML = frames.map((frame, index) => `<button type="button" class="timeline-dot ${index === state.media.index ? "active" : ""}" data-media-frame="${index}" title="${escapeHtml(frameLabel(frame))}">${escapeHtml(frameLabel(frame))}</button>`).join("");
  $("#mediaModeTabs").querySelectorAll("[data-media-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.media.kind = button.dataset.mediaMode;
      state.media.index = 0;
      renderMediaDialog();
    });
  });
  $("#mediaTimeline").querySelectorAll("[data-media-frame]").forEach((button) => {
    button.addEventListener("click", () => {
      state.media.index = Number(button.dataset.mediaFrame);
      renderMediaDialog();
    });
  });
}

function openMedia(kind, index) {
  if (!mediaFrames(kind).length) return;
  state.media.kind = kind;
  state.media.index = index;
  renderMediaDialog();
  openDialog("mediaDialog");
}

function moveMedia(delta) {
  const frames = mediaFrames(state.media.kind);
  if (!frames.length) return;
  state.media.index = (state.media.index + delta + frames.length) % frames.length;
  renderMediaDialog();
}

function openInferDialog() {
  if (!state.selectedId) return;
  $("#jobResult").classList.add("hidden");
  $("#jobResult").textContent = "";
  openDialog("inferDialog");
}

function showJob(job) {
  const target = $("#jobResult");
  target.classList.remove("hidden");
  const result = job.result || {};
  if (["queued", "running"].includes(job.status)) {
    target.textContent = `任务${job.status === "queued" ? "排队中" : "运行中"}…\nissue: ${job.issue_id}\n默认最多等待 12 分钟。`;
  } else if (job.status === "failed") {
    target.textContent = `任务失败\n${job.error_text || result.error || "未知错误"}`;
  } else if (result.dry_run) {
    target.textContent = `预检通过\nTrail issue: ${result.issue_id}\ntrip: ${result.trip_id}\nAres BEV: ${result.bev_asset_available ? "可用" : "未使用"}\nRA Tools 回写: ${result.ra_tools_enabled}`;
  } else {
    const detail = result.result || {};
    target.textContent = `推理完成\n标签：${detail.model_label || "—"}\n置信度：${detail.model_confidence ?? "—"}\n耗时：${detail.duration_sec ?? "—"}s\n\n${detail.model_reason || "模型未返回 reason。"}`;
  }
}

async function pollJob(jobId) {
  clearInterval(state.pollTimer);
  state.pollingJobId = jobId;
  const tick = async () => {
    try {
      const data = await api(`/api/inference/jobs/${encodeURIComponent(jobId)}`);
      showJob(data.job);
      if (!["queued", "running"].includes(data.job.status)) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        state.pollingJobId = "";
        await loadOverview();
        if (state.selectedId) await selectCase(state.selectedId);
      }
    } catch (error) {
      clearInterval(state.pollTimer);
      showToast(error.message, true);
    }
  };
  await tick();
  state.pollTimer = setInterval(tick, 2000);
}

async function submitInference({ dryRun }) {
  if (!state.selectedId) return;
  const keyInput = $("#apiKeyInput");
  const payload = {
    issue_id: state.selectedId,
    model_name: $("#modelNameInput").value.trim(),
    prompt_version: $("#promptVersionInput").value.trim(),
    base_url: $("#baseUrlInput").value.trim(),
    api_key: keyInput.value,
    max_tokens: Number($("#maxTokensInput").value || 512),
    requested_by: $("#requestedByInput").value.trim(),
    use_bev_animation: $("#useBevInput").checked,
    use_ra_options: $("#useRaOptionsInput").checked,
    dry_run: dryRun,
  };
  if (dryRun) Object.assign(payload, { model_name: "", base_url: "", api_key: "" });
  try {
    const result = await api("/api/inference/jobs", { method: "POST", body: JSON.stringify(payload) });
    keyInput.value = "";
    showJob(result.job);
    await pollJob(result.job.id);
  } catch (error) {
    keyInput.value = "";
    showToast(error.message, true);
  }
}

function currentImportKind() {
  return $("#importKind input[name='kind']:checked").value;
}

function updateImportFields() {
  const isModel = currentImportKind() === "model";
  $("#runNameField").classList.toggle("hidden", !isModel);
  $("#issueImportOptions").classList.toggle("hidden", isModel);
}

function openImportDialog(kind) {
  const input = $(`#importKind input[name="kind"][value="${kind}"]`);
  if (input) input.checked = true;
  updateImportFields();
  $("#importResult").classList.add("hidden");
  $("#importResult").textContent = "";
  openDialog("importDialog");
}

async function submitImport(event) {
  event.preventDefault();
  const file = $("#importFile").files[0];
  if (!file) return showToast("请选择文件。", true);
  const kind = currentImportKind();
  const form = new FormData();
  form.append("file", file);
  const endpoint = kind === "model" ? "/api/import/model-results" : "/api/import/issues";
  if (kind === "model") form.append("run_name", $("#runNameInput").value.trim());
  else {
    form.append("source", $("#issueSourceInput").value.trim() || "manual_upload");
    form.append("replace_gt", String($("#replaceGtInput").checked));
  }
  const target = $("#importResult");
  target.classList.remove("hidden");
  target.textContent = "正在导入…";
  try {
    const result = await api(endpoint, { method: "POST", body: form });
    target.textContent = JSON.stringify(result, null, 2);
    showToast(kind === "model" ? "模型 run 已导入；可从列表切换对比。" : "Issue 工作集已导入。");
    await Promise.all([loadRuns(), loadOverview(), loadCases({ keepSelection: true }), loadClusters()]);
  } catch (error) {
    target.textContent = `导入失败：${error.message}`;
    showToast(error.message, true);
  }
}

async function syncTrail() {
  const button = $("#syncTrailButton");
  button.disabled = true;
  button.textContent = "同步中…";
  try {
    const result = await api("/api/trail-model-sync", { method: "POST", body: "{}" });
    state.config = { ...(state.config || {}), trail_sync: result, default_model_run_id: result.run_id || state.config?.default_model_run_id };
    renderConfig();
    if (result.run_id) {
      state.selectedRunId = result.run_id;
      state.failureOnly = true;
    }
    await loadRuns({ preferDefault: Boolean(result.run_id) });
    await Promise.all([loadOverview(), loadCases({ keepSelection: false }), loadClusters()]);
    showToast(result.message || "Trail 字段同步完成。", result.status === "failed");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "同步 Trail 字段";
  }
}

async function refreshAll({ resetSelection = false } = {}) {
  await loadConfig();
  await loadRuns();
  await Promise.all([loadStatus(), loadOverview(), loadCases({ keepSelection: !resetSelection }), loadClusters()]);
}

function bindEvents() {
  $("#filterForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await Promise.all([loadCases({ keepSelection: false }), loadClusters(), loadOverview()]);
  });
  $("#modelRunFilter").addEventListener("change", async () => {
    const previousRunId = state.selectedRunId;
    state.selectedRunId = $("#modelRunFilter").value;
    if (!state.selectedRunId) state.failureOnly = false;
    if (state.selectedRunId && !previousRunId) state.failureOnly = true;
    $("#failureOnlyInput").disabled = !state.selectedRunId;
    $("#failureOnlyInput").checked = state.failureOnly;
    renderActiveRun();
    renderRunManager();
    await Promise.all([loadCases({ keepSelection: false }), loadClusters(), loadOverview()]);
  });
  $("#failureOnlyInput").addEventListener("change", async () => {
    state.failureOnly = $("#failureOnlyInput").checked;
    await Promise.all([loadCases({ keepSelection: false }), loadClusters(), loadOverview()]);
  });
  $("#clearClusterButton").addEventListener("click", async () => {
    state.clusterKey = "";
    await Promise.all([loadCases({ keepSelection: false }), loadClusters()]);
  });
  $("#refreshButton").addEventListener("click", async () => {
    try {
      await refreshAll();
      if (state.selectedId) await selectCase(state.selectedId);
      showToast("页面数据已刷新。");
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#syncTrailButton").addEventListener("click", syncTrail);
  $("#importButton").addEventListener("click", () => openImportDialog("issues"));
  $("#runManagerImportButton").addEventListener("click", () => {
    closeDialog("runManagerDialog");
    openImportDialog("model");
  });
  $("#openRunManagerButton").addEventListener("click", () => {
    renderRunManager();
    openDialog("runManagerDialog");
  });
  $("#manageRunsButton").addEventListener("click", () => {
    renderRunManager();
    openDialog("runManagerDialog");
  });
  $("#refreshRunsButton").addEventListener("click", async () => {
    try {
      await loadRuns();
      await loadOverview();
      showToast("模型 run 列表已刷新。");
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#openInferButton").addEventListener("click", openInferDialog);
  $("#reviewNavButton").addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  $("#sidebarToggle").addEventListener("click", toggleSidebar);
  document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => closeDialog(button.dataset.close)));
  $("#importKind").querySelectorAll("input").forEach((input) => input.addEventListener("change", updateImportFields));
  $("#importFile").addEventListener("change", () => { $("#importFileName").textContent = $("#importFile").files[0]?.name || "未选择文件"; });
  $("#importForm").addEventListener("submit", submitImport);
  $("#preflightButton").addEventListener("click", () => submitInference({ dryRun: true }));
  $("#inferForm").addEventListener("submit", (event) => { event.preventDefault(); submitInference({ dryRun: false }); });
  $("#mediaPrevButton").addEventListener("click", () => moveMedia(-1));
  $("#mediaNextButton").addEventListener("click", () => moveMedia(1));
  document.addEventListener("keydown", (event) => {
    if (!$("#mediaDialog").open) return;
    if (["ArrowLeft", "ArrowUp"].includes(event.key)) { event.preventDefault(); moveMedia(-1); }
    if (["ArrowRight", "ArrowDown"].includes(event.key)) { event.preventDefault(); moveMedia(1); }
    if (event.key.toLowerCase() === "b" && mediaFrames("bev").length) { state.media.kind = "bev"; state.media.index = 0; renderMediaDialog(); }
    if (event.key.toLowerCase() === "c" && mediaFrames("camera").length) { state.media.kind = "camera"; state.media.index = 0; renderMediaDialog(); }
  });
}

async function bootstrap() {
  state.sidebarCollapsed = localStorage.getItem("ra-triage-sidebar-collapsed") === "true";
  applySidebarState();
  bindEvents();
  updateImportFields();
  try {
    await Promise.all([loadConfig(), loadSession()]);
    state.selectedRunId = state.config.default_model_run_id || "";
    state.failureOnly = Boolean(state.config.default_failure_only && state.selectedRunId);
    await loadRuns({ preferDefault: true });
    $("#failureOnlyInput").checked = state.failureOnly;
    await Promise.all([loadStatus(), loadOverview(), loadCases({ keepSelection: false }), loadClusters()]);
    const hashId = decodeURIComponent(window.location.hash.slice(1));
    if (hashId && state.cases.some((item) => item.issue_id === hashId)) await selectCase(hashId);
  } catch (error) {
    showToast(`启动失败：${error.message}`, true);
  }
}

window.addEventListener("DOMContentLoaded", bootstrap);
