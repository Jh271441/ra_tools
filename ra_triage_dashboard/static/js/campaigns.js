/* Campaign and Label Analysis read-only surfaces. */

const CAMPAIGN_PAGE_SIZE = 50;
const CAMPAIGN_ISSUE_PAGE_SIZE_DEFAULT = 50;
const campaignPageState = {
  campaignId: "",
  purpose: "",
  lifecycle: "all",
  query: "",
  issuePage: 1,
  issuePageSize: CAMPAIGN_ISSUE_PAGE_SIZE_DEFAULT,
  issueAssignee: "",
  issueState: "all",
  issueQuery: "",
  detail: null,
};

function campaignLabel(value) {
  const map = {
    labeling: ["Labeling", "Labeling"],
    model_review: ["Model Review", "Model Review"],
    active: ["进行中", "Active"],
    draft: ["草稿", "Draft"],
    closed: ["已关闭", "Closed"],
    cancelled: ["已取消", "Cancelled"],
    superseded: ["已替代", "Superseded"],
    pending: ["待处理", "Pending"],
    in_progress: ["进行中", "In progress"],
    completed: ["完成", "Completed"],
    conflict: ["冲突", "Conflict"],
    adjudicated: ["已裁决", "Adjudicated"],
    stale: ["已过期", "Stale"],
    blocked: ["阻塞", "Blocked"],
    unassigned: ["未分配", "Unassigned"],
    legacy_read_only: ["Legacy 只读", "Legacy read-only"],
    matches_gt: ["与 GT 一致", "Matches GT"],
    differs_from_gt: ["与 GT 不同", "Differs from GT"],
    fills_missing_gt: ["补齐缺失 GT", "Fills missing GT"],
    matches_reference: ["与参考标签一致", "Matches reference"],
    differs_from_reference: ["与参考标签不同", "Differs from reference"],
    unknown: ["未知 / 暂无结果", "Unknown / no result"],
  };
  const pair = map[String(value || "")] || [String(value || "—"), String(value || "—")];
  return state.uiLanguage === "en" ? pair[1] : pair[0];
}

function campaignNumber(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number.toLocaleString() : "0";
}

function campaignRouteOptions({ campaignId = campaignPageState.campaignId } = {}) {
  const purpose = campaignPageState.purpose;
  const lifecycle = campaignPageState.lifecycle;
  const query = campaignPageState.query;
  return {
    campaignId,
    purpose,
    lifecycle,
    query,
    campaignPurpose: purpose,
    campaignLifecycle: lifecycle,
    campaignQuery: query,
  };
}

async function mutateCampaignAssignment(issueId, { action, assignee = "", fromAssignee = "" } = {}) {
  const campaign = campaignPageState.detail?.campaign;
  if (!campaign?.id || !campaignPageState.detail || !state.session?.is_admin) return;
  const key = globalThis.crypto?.randomUUID?.() || `campaign-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  try {
    const result = await api(
      `/api/campaigns/${encodeURIComponent(campaign.id)}/issues/${encodeURIComponent(issueId)}/assignments`,
      {
        method: "PATCH",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({
          action,
          assignee,
          from_assignee: fromAssignee,
          expected_revision: Number(campaign.config_revision || 1),
          idempotency_key: key,
          assignment_kind: "base",
        }),
      }
    );
    acknowledgeLocalChange(result);
    showToast(uiText("Campaign 分配已更新。", "Campaign assignment updated."));
    await loadCampaignDetail(campaign.id);
  } catch (error) {
    if (String(error.message || "").includes("版本已更新")) {
      await loadCampaignDetail(campaign.id).catch(() => {});
    }
    showToast(error.message || uiText("更新 Campaign 分配失败。", "Unable to update assignment."), true);
  }
}

async function mutateCampaignLifecycle(action) {
  const campaign = campaignPageState.detail?.campaign;
  if (!campaign?.id || !state.session?.is_admin) return;
  const isReopen = action === "reopen";
  if (!isReopen && !window.confirm(uiText("关闭后将冻结成员和进度快照。继续关闭此 Campaign？", "Closing freezes its membership and progress snapshot. Close this Campaign?"))) return;
  const reason = isReopen
    ? window.prompt(uiText("填写重新打开原因。", "Enter a reason for reopening."), "")
    : uiText("从 Campaign 管理页关闭。", "Closed from Campaign management.");
  if (isReopen && !String(reason || "").trim()) return;
  const key = globalThis.crypto?.randomUUID?.() || `campaign-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  try {
    const result = await api(`/api/campaigns/${encodeURIComponent(campaign.id)}/${isReopen ? "reopen" : "close"}`, {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({
        expected_revision: Number(campaign.config_revision || 1),
        idempotency_key: key,
        reason: String(reason || ""),
      }),
    });
    acknowledgeLocalChange(result);
    showToast(isReopen
      ? uiText("Campaign 已重新打开。", "Campaign reopened.")
      : uiText("Campaign 已关闭并保存快照。", "Campaign closed with a saved snapshot."));
    await loadCampaignDetail(campaign.id);
  } catch (error) {
    if (String(error.message || "").includes("版本已更新")) {
      await loadCampaignDetail(campaign.id).catch(() => {});
    }
    showToast(error.message || uiText("更新 Campaign 生命周期失败。", "Unable to update Campaign lifecycle."), true);
  }
}

function saveCampaignRoute(mode = "push", overrides = {}) {
  const url = pageUrl("campaigns", campaignRouteOptions(overrides));
  const nextState = { ...(window.history.state || {}), page: "campaigns" };
  if (mode === "replace") window.history.replaceState(nextState, "", url);
  else window.history.pushState(nextState, "", url);
}

function campaignListEndpoint() {
  const params = new URLSearchParams({
    baselines: selectedBaselineQueryValue(),
    lifecycle: campaignPageState.lifecycle || "all",
    page: "1",
    page_size: String(CAMPAIGN_PAGE_SIZE),
  });
  if (campaignPageState.purpose) params.set("purpose", campaignPageState.purpose);
  if (campaignPageState.query) params.set("q", campaignPageState.query);
  return `/api/campaigns?${params.toString()}`;
}

async function loadCampaigns({
  campaignId = "",
  purpose = "",
  lifecycle = "all",
  query = "",
} = {}) {
  if (!document.getElementById("campaignsPage")) return null;
  if (state.session?.is_admin && !state.accessUsers?.length && typeof loadAccessUsers === "function") {
    await loadAccessUsers().catch(() => {});
  }
  const route = typeof parsePageRoute === "function" ? parsePageRoute() : {};
  campaignPageState.campaignId = String(campaignId || route.campaignId || "").trim();
  campaignPageState.purpose = String(purpose || route.campaignPurpose || "").trim();
  campaignPageState.lifecycle = String(lifecycle || route.campaignLifecycle || "all").trim() || "all";
  campaignPageState.query = String(query || route.campaignQuery || "").trim().slice(0, 128);
  const lifecycleSelect = document.getElementById("campaignsLifecycle");
  const queryInput = document.getElementById("campaignsQuery");
  if (lifecycleSelect) lifecycleSelect.value = campaignPageState.lifecycle;
  if (queryInput) queryInput.value = campaignPageState.query;
  const labelTab = document.getElementById("campaignsLabelAnalysisTab");
  const allTab = document.getElementById("campaignsAllTab");
  labelTab?.classList.toggle("is-active", campaignPageState.purpose === "labeling");
  labelTab?.setAttribute("aria-selected", campaignPageState.purpose === "labeling" ? "true" : "false");
  allTab?.classList.toggle("is-active", campaignPageState.purpose !== "labeling");
  allTab?.setAttribute("aria-selected", campaignPageState.purpose !== "labeling" ? "true" : "false");
  if (campaignPageState.campaignId) {
    return loadCampaignDetail(campaignPageState.campaignId);
  }
  campaignPageState.detail = null;
  document.getElementById("campaignsListView")?.removeAttribute("hidden");
  document.getElementById("campaignDetailView")?.setAttribute("hidden", "");
  return loadCampaignList();
}

async function loadCampaignList() {
  const status = document.getElementById("campaignsListStatus");
  const rowsRoot = document.getElementById("campaignsRows");
  if (status) status.textContent = uiText("正在加载 Campaign…", "Loading campaigns…");
  if (rowsRoot) rowsRoot.innerHTML = `<tr><td colspan="7" class="campaign-empty-state">${escapeHtml(uiText("正在加载…", "Loading…"))}</td></tr>`;
  const payload = await api(campaignListEndpoint());
  const items = Array.isArray(payload.items) ? payload.items : [];
  if (status) {
    const noun = uiText("个 Campaign", "campaigns");
    status.textContent = `${campaignNumber(payload.total)} ${noun}`;
  }
  if (!rowsRoot) return payload;
  if (!items.length) {
    rowsRoot.innerHTML = `<tr><td colspan="7" class="campaign-empty-state">${escapeHtml(uiText("当前筛选没有 Campaign。", "No campaigns match these filters."))}</td></tr>`;
    return payload;
  }
  rowsRoot.innerHTML = items.map((item) => {
    const progress = item.progress || {};
    const memberCount = Number(progress.member_count ?? item.workset_member_count ?? 0);
    const assigned = Number(progress.assigned_issue_count || 0);
    const completed = Number(progress.completed_issue_count || 0);
    const required = Number(progress.required_submitter_count || 0);
    const submitted = Number(progress.submitted_submitter_count || 0);
    const ratio = assigned ? Math.max(0, Math.min(1, completed / assigned)) : 0;
    const baseline = (item.baseline_scopes || []).join(", ") || item.workset_baseline_scope || "—";
    const reference = item.reference_id ? `${item.reference_type || "reference"} · ${String(item.reference_id).slice(0, 18)}` : uiText("参考未解析", "Reference unresolved");
    const purpose = item.purpose ? campaignLabel(item.purpose) : uiText("未分类", "Unclassified");
    return `<tr>
      <td><button type="button" class="campaign-row-button" data-campaign-open="${escapeHtml(item.id)}"><span class="campaign-row-name">${escapeHtml(item.name || item.id)}</span><span class="campaign-row-id">${escapeHtml(item.id)}${item.task_group_id ? ` · ${escapeHtml(item.task_group_id)}` : ""}</span></button></td>
      <td><span class="campaign-purpose-badge">${escapeHtml(purpose)}</span></td>
      <td><span class="campaign-lifecycle-badge" data-lifecycle="${escapeHtml(item.lifecycle)}">${escapeHtml(campaignLabel(item.lifecycle))}</span></td>
      <td>${campaignNumber(memberCount)} / ${campaignNumber(required)}</td>
      <td>${campaignNumber(submitted)} / ${campaignNumber(required)}</td>
      <td class="campaign-progress-cell">${campaignNumber(completed)} / ${campaignNumber(assigned)}<div class="campaign-progress-bar" aria-label="${Math.round(ratio * 100)}%"><span style="width:${Math.round(ratio * 100)}%"></span></div></td>
      <td>${escapeHtml(baseline)}<span class="campaign-reference-text">${escapeHtml(reference)}</span></td>
    </tr>`;
  }).join("");
  return payload;
}

async function loadCampaignDetail(campaignId) {
  const list = document.getElementById("campaignsListView");
  const detailRoot = document.getElementById("campaignDetailView");
  const title = document.getElementById("campaignDetailTitle");
  if (list) list.setAttribute("hidden", "");
  if (detailRoot) detailRoot.removeAttribute("hidden");
  if (title) title.textContent = uiText("正在加载 Campaign…", "Loading campaign…");
  const params = new URLSearchParams({
    page: String(campaignPageState.issuePage),
    page_size: String(campaignPageState.issuePageSize),
    state: campaignPageState.issueState,
  });
  if (campaignPageState.issueAssignee) params.set("assignee", campaignPageState.issueAssignee);
  if (campaignPageState.issueQuery) params.set("q", campaignPageState.issueQuery);
  const payload = await api(`/api/campaigns/${encodeURIComponent(campaignId)}?${params.toString()}`);
  campaignPageState.detail = payload;
  renderCampaignDetail(payload);
  return payload;
}

function renderCampaignMetrics(progress = {}) {
  const root = document.getElementById("campaignProgressMetrics");
  if (!root) return;
  const metrics = [
    [uiText("Issue 成员", "Issues"), progress.member_count],
    [uiText("已分配 Issue", "Assigned Issues"), progress.assigned_issue_count],
    [uiText("所需提交", "Required submissions"), progress.required_submitter_count],
    [uiText("已提交", "Submitted"), progress.submitted_submitter_count],
    [uiText("已完成 Issue", "Completed Issues"), progress.completed_issue_count],
    [uiText("冲突", "Conflicts"), progress.conflict_issue_count],
  ];
  root.innerHTML = metrics.map(([label, value]) => `<div class="campaign-progress-metric"><span>${escapeHtml(label)}</span><strong>${campaignNumber(value)}</strong></div>`).join("");
}

function renderCampaignAssignees(assignees = []) {
  const rows = document.getElementById("campaignAssigneeRows");
  const filter = document.getElementById("campaignIssueAssignee");
  if (!rows) return;
  const selected = campaignPageState.issueAssignee;
  if (filter) {
    filter.innerHTML = `<option value="">${escapeHtml(uiText("全部负责人", "All assignees"))}</option>` + assignees.map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`).join("");
    filter.value = selected;
  }
  if (!assignees.length) {
    rows.innerHTML = `<tr><td colspan="4" class="campaign-empty-state">${escapeHtml(uiText("暂无负责人分配。", "No assignees."))}</td></tr>`;
    return;
  }
  rows.innerHTML = assignees.map((item) => `<tr><td>${escapeHtml(item.name)}</td><td>${campaignNumber(item.assigned_slots)}</td><td>${campaignNumber(item.submitted_slots)}</td><td>${campaignNumber(item.completed_slots)}</td></tr>`).join("");
}

function renderCampaignRevisions(revisions = []) {
  const rows = document.getElementById("campaignRevisionRows");
  if (!rows) return;
  rows.innerHTML = revisions.length
    ? revisions.map((item) => `<tr><td>${campaignNumber(item.revision_no)}</td><td>${escapeHtml(item.change_source || "—")}</td><td>${escapeHtml(item.changed_by || "—")}${item.changed_by_verified ? " · SSO" : ""}</td><td>${escapeHtml(item.changed_at || "")}</td><td title="${escapeHtml(item.config_sha256 || "")}">${escapeHtml(String(item.config_sha256 || "").slice(0, 16))}${item.config_sha256 ? "…" : ""}</td></tr>`).join("")
    : `<tr><td colspan="5" class="campaign-empty-state">${escapeHtml(uiText("暂无配置版本。", "No configuration revisions."))}</td></tr>`;
}

function renderCampaignLabelAnalysis(campaign, progress) {
  const root = document.getElementById("campaignLabelAnalysis");
  if (!root) return;
  if (campaign.purpose !== "labeling") {
    root.hidden = true;
    return;
  }
  root.hidden = false;
  const exportLink = document.getElementById("campaignLabelExportCsv");
  if (exportLink) {
    const params = new URLSearchParams();
    if (campaignPageState.issueQuery) params.set("q", campaignPageState.issueQuery);
    if (campaignPageState.issueAssignee) params.set("assignee", campaignPageState.issueAssignee);
    if (campaignPageState.issueState !== "all") params.set("state", campaignPageState.issueState);
    const query = params.toString();
    exportLink.href = withBase(`/api/campaigns/${encodeURIComponent(campaign.id)}/analysis/export.csv${query ? `?${query}` : ""}`);
    exportLink.hidden = !state.session?.is_admin;
  }
  const renderCounts = (targetId, values, labels) => {
    const target = document.getElementById(targetId);
    if (!target) return;
    target.innerHTML = `<div class="campaign-analysis-counts">${labels.map(([key, fallback]) => {
      const label = fallback || campaignLabel(key);
      return `<div class="campaign-analysis-count-row"><span>${escapeHtml(label)}</span><strong>${campaignNumber(values?.[key])}</strong></div>`;
    }).join("")}</div>`;
  };
  renderCounts("campaignLabelOutputCounts", progress.label_output_counts, [
    ["误触发", "误触发"], ["正确触发", "正确触发"], ["无需协助", "无需协助"],
  ]);
  renderCounts("campaignReferenceRelationCounts", progress.reference_relation_counts, [
    ["matches_gt"], ["differs_from_gt"], ["fills_missing_gt"],
    ["matches_reference"], ["differs_from_reference"], ["unknown"],
  ]);
  const renderTop = (targetId, values, limit = 12) => {
    const target = document.getElementById(targetId);
    if (!target) return;
    const entries = Object.entries(values || {})
      .map(([key, value]) => [String(key), Number(value || 0)])
      .filter(([, value]) => value > 0)
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .slice(0, limit);
    target.innerHTML = entries.length
      ? `<div class="campaign-analysis-counts">${entries.map(([key, value]) => `<div class="campaign-analysis-count-row"><span>${escapeHtml(key)}</span><strong>${campaignNumber(value)}</strong></div>`).join("")}</div>`
      : `<span class="campaign-reference-text">${escapeHtml(uiText("暂无结果", "No results"))}</span>`;
  };
  renderTop("campaignTagCounts", progress.tag_counts);
  renderTop("campaignEvidenceGapCounts", progress.evidence_gap_counts);
  renderTop("campaignScenarioCounts", progress.scenario_counts);
  renderCounts("campaignLabelingNoteCounts", {
    conflicts: progress.conflict_issue_count,
    adjudicated: progress.adjudicated_issue_count,
    excluded: progress.excluded_issue_count,
    with_rationale: progress.rationale_issue_count,
  }, [
    ["conflicts", campaignLabel("conflict")],
    ["adjudicated", campaignLabel("adjudicated")],
    ["excluded", uiText("提出排除", "Exclusion proposed")],
    ["with_rationale", uiText("有标注依据", "With rationale")],
  ]);
}

function renderCampaignIssues(payload) {
  const root = document.getElementById("campaignIssueRows");
  if (!root) return;
  const campaign = campaignPageState.detail?.campaign || {};
  const canManage = Boolean(
    state.session?.is_admin
    && campaign.purpose
    && !campaign.legacy_read_only
    && campaign.lifecycle === "active"
  );
  document.querySelectorAll("[data-campaign-admin-column]").forEach((header) => {
    header.hidden = !canManage;
  });
  const issues = Array.isArray(payload.issues) ? payload.issues : [];
  const count = document.getElementById("campaignIssueCount");
  if (count) count.textContent = `${campaignNumber(payload.total)} ${uiText("个 Issue", "Issues")}`;
  if (!issues.length) {
    root.innerHTML = `<tr><td colspan="${canManage ? 9 : 8}" class="campaign-empty-state">${escapeHtml(uiText("当前筛选没有 Issue。", "No Issues match these filters."))}</td></tr>`;
  } else {
    root.innerHTML = issues.map((item) => {
      const assignees = (item.assignments || []).map((assignment) => `<span class="campaign-assignee-chip">${escapeHtml(assignment.assignee)}${assignment.assignment_kind !== "base" ? ` · ${escapeHtml(assignment.assignment_kind)}` : ""}${canManage ? `<button class="campaign-unassign-button" type="button" data-campaign-unassign="${escapeHtml(item.issue_id)}" data-campaign-user="${escapeHtml(assignment.assignee)}" aria-label="移除 ${escapeHtml(assignment.assignee)}">×</button>` : ""}</span>`).join("") || "—";
      const enabledUsers = (state.accessUsers || []).filter((user) => user.enabled !== false);
      const assignmentControls = canManage
        ? `<div class="campaign-assignment-controls"><select data-campaign-new-assignee="${escapeHtml(item.issue_id)}" aria-label="选择新负责人"><option value="">${escapeHtml(uiText("选择负责人", "Choose assignee"))}</option>${enabledUsers.map((user) => `<option value="${escapeHtml(user.username)}">${escapeHtml(user.username)}</option>`).join("")}</select><button class="button button-quiet" type="button" data-campaign-assign="${escapeHtml(item.issue_id)}">${escapeHtml(uiText("分配", "Assign"))}</button></div>`
        : "";
      const labelTags = [...(item.tags || []), ...(item.evidence_gaps || []).map((value) => `缺证据 · ${value}`)];
      const tagMarkup = labelTags.length
        ? `<div class="campaign-assignee-chips">${labelTags.map((value) => `<span class="campaign-assignee-chip">${escapeHtml(value)}</span>`).join("")}</div>`
        : "—";
      const issueUrl = withBase(`/review?issue=${encodeURIComponent(item.issue_id)}`);
      const referenceLabel = item.reference_label || item.gt_label || "—";
      const relation = item.reference_relation && item.reference_relation !== "unknown"
        ? `<span class="campaign-reference-text">${escapeHtml(campaignLabel(item.reference_relation))}</span>`
        : "";
      return `<tr><td><a href="${escapeHtml(issueUrl)}" class="campaign-row-name">${escapeHtml(item.issue_id)}</a><span class="campaign-reference-text">${escapeHtml(item.title || item.scenario || "")}</span></td><td>${escapeHtml(referenceLabel)}${relation}</td><td>${escapeHtml(item.expected_output || "—")}</td><td>${tagMarkup}</td><td>${item.is_excluded ? escapeHtml(uiText("提出排除", "Proposed exclusion")) : "—"}</td><td><div class="campaign-assignee-chips">${assignees}</div></td><td>${campaignNumber(item.submitted)} / ${campaignNumber(item.required_submitter_count)}</td><td><span class="campaign-state-badge" data-state="${escapeHtml(item.state)}">${escapeHtml(campaignLabel(item.state))}</span></td>${canManage ? `<td>${assignmentControls}</td>` : ""}</tr>`;
    }).join("");
  }
  const pageState = document.getElementById("campaignIssuePageState");
  if (pageState) pageState.textContent = `${payload.page} / ${payload.page_count}`;
  const previous = document.getElementById("campaignIssuePrevious");
  const next = document.getElementById("campaignIssueNext");
  if (previous) previous.disabled = payload.page <= 1;
  if (next) next.disabled = payload.page >= payload.page_count;
}

function renderCampaignDetail(payload) {
  const campaign = payload.campaign || {};
  const progress = payload.progress || {};
  const title = document.getElementById("campaignDetailTitle");
  const meta = document.getElementById("campaignDetailMeta");
  const lifecycle = document.getElementById("campaignDetailLifecycle");
  const snapshot = document.getElementById("campaignCloseSnapshot");
  if (title) title.textContent = campaign.name || campaign.id || "Campaign";
  if (meta) {
    const reference = campaign.reference_id ? `${campaign.reference_type || "reference"}: ${campaign.reference_id}` : uiText("无已解析参考", "No resolved reference");
    meta.textContent = `${campaign.id} · ${campaignLabel(campaign.purpose || "")} · ${(campaign.baseline_scopes || []).join(", ") || campaign.workset_baseline_scope || "—"} · ${reference}`;
  }
  if (lifecycle) {
    lifecycle.textContent = campaignLabel(campaign.lifecycle);
    lifecycle.dataset.lifecycle = campaign.lifecycle || "";
  }
  const isAdmin = Boolean(state.session?.is_admin);
  const canManageLifecycle = isAdmin && campaign.purpose && !campaign.legacy_read_only;
  const closeButton = document.getElementById("campaignCloseButton");
  const reopenButton = document.getElementById("campaignReopenButton");
  if (closeButton) closeButton.hidden = !canManageLifecycle || campaign.lifecycle !== "active";
  if (reopenButton) reopenButton.hidden = !canManageLifecycle || campaign.lifecycle !== "closed";
  renderCampaignMetrics(progress);
  renderCampaignLabelAnalysis(campaign, progress);
  renderCampaignRevisions(payload.revisions || []);
  renderCampaignAssignees(payload.assignees || []);
  renderCampaignIssues(payload);
  if (snapshot) {
    if (payload.close_snapshot) {
      const item = payload.close_snapshot;
      snapshot.hidden = false;
      snapshot.textContent = `${uiText("关闭快照", "Close snapshot")} ${item.id} · ${uiText("版本", "Revision")} ${item.config_revision} · ${uiText("完成", "Completed")} ${item.completed_issue_count}/${item.assigned_issue_count} · ${item.closed_at || ""}`;
    } else {
      snapshot.hidden = true;
      snapshot.textContent = "";
    }
  }
}

function bindCampaignPageEvents() {
  document.getElementById("campaignCloseButton")?.addEventListener("click", () => {
    mutateCampaignLifecycle("close");
  });
  document.getElementById("campaignReopenButton")?.addEventListener("click", () => {
    mutateCampaignLifecycle("reopen");
  });
  document.getElementById("caseLabelingCampaignsButton")?.addEventListener("click", () => {
    campaignPageState.purpose = "labeling";
    campaignPageState.lifecycle = "all";
    campaignPageState.query = "";
    campaignPageState.campaignId = "";
    navigatePage("campaigns", {
      ...campaignRouteOptions({ campaignId: "" }),
      campaignPurpose: "labeling",
      purpose: "labeling",
    });
  });
  document.getElementById("campaignsRefresh")?.addEventListener("click", () => {
    loadCampaigns({ ...campaignRouteOptions() }).catch((error) => showToast(error.message, true));
  });
  document.getElementById("campaignsFilterForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    campaignPageState.lifecycle = document.getElementById("campaignsLifecycle")?.value || "all";
    campaignPageState.query = document.getElementById("campaignsQuery")?.value.trim().slice(0, 128) || "";
    campaignPageState.campaignId = "";
    campaignPageState.issuePage = 1;
    saveCampaignRoute("push", { campaignId: "" });
    loadCampaigns({ ...campaignRouteOptions(), campaignId: "" }).catch((error) => showToast(error.message, true));
  });
  document.getElementById("campaignsAllTab")?.addEventListener("click", () => {
    campaignPageState.purpose = "";
    campaignPageState.campaignId = "";
    saveCampaignRoute("push", { purpose: "", campaignId: "" });
    loadCampaigns({ ...campaignRouteOptions(), purpose: "", campaignId: "" }).catch((error) => showToast(error.message, true));
  });
  document.getElementById("campaignsLabelAnalysisTab")?.addEventListener("click", () => {
    campaignPageState.purpose = "labeling";
    campaignPageState.campaignId = "";
    saveCampaignRoute("push", { purpose: "labeling", campaignId: "" });
    loadCampaigns({ ...campaignRouteOptions(), purpose: "labeling", campaignId: "" }).catch((error) => showToast(error.message, true));
  });
  document.getElementById("campaignsRows")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-campaign-open]");
    if (!button) return;
    campaignPageState.campaignId = button.dataset.campaignOpen || "";
    campaignPageState.issuePage = 1;
    campaignPageState.issueAssignee = "";
    campaignPageState.issueState = "all";
    campaignPageState.issueQuery = "";
    navigatePage("campaigns", campaignRouteOptions());
  });
  document.getElementById("campaignDetailBack")?.addEventListener("click", () => {
    campaignPageState.campaignId = "";
    navigatePage("campaigns", campaignRouteOptions({ campaignId: "" }));
  });
  document.getElementById("campaignIssueFilterButton")?.addEventListener("click", () => {
    campaignPageState.issuePage = 1;
    campaignPageState.issueAssignee = document.getElementById("campaignIssueAssignee")?.value || "";
    campaignPageState.issueState = document.getElementById("campaignIssueState")?.value || "all";
    campaignPageState.issueQuery = document.getElementById("campaignIssueQuery")?.value.trim().slice(0, 128) || "";
    loadCampaignDetail(campaignPageState.campaignId).catch((error) => showToast(error.message, true));
  });
  document.getElementById("campaignIssueRows")?.addEventListener("click", (event) => {
    const removeButton = event.target.closest("[data-campaign-unassign]");
    if (removeButton) {
      mutateCampaignAssignment(removeButton.dataset.campaignUnassign, {
        action: "unassign",
        fromAssignee: removeButton.dataset.campaignUser || "",
      });
      return;
    }
    const assignButton = event.target.closest("[data-campaign-assign]");
    if (!assignButton) return;
    const issueId = assignButton.dataset.campaignAssign || "";
    const input = document.querySelector(`[data-campaign-new-assignee="${CSS.escape(issueId)}"]`);
    const assignee = String(input?.value || "").trim();
    if (!assignee) {
      showToast(uiText("请先选择负责人。", "Choose an assignee first."), true);
      return;
    }
    mutateCampaignAssignment(issueId, { action: "assign", assignee });
  });
  document.getElementById("campaignIssuePrevious")?.addEventListener("click", () => {
    campaignPageState.issuePage = Math.max(1, campaignPageState.issuePage - 1);
    loadCampaignDetail(campaignPageState.campaignId).catch((error) => showToast(error.message, true));
  });
  document.getElementById("campaignIssueNext")?.addEventListener("click", () => {
    campaignPageState.issuePage += 1;
    loadCampaignDetail(campaignPageState.campaignId).catch((error) => showToast(error.message, true));
  });
  document.getElementById("campaignIssuePageSize")?.addEventListener("change", (event) => {
    campaignPageState.issuePageSize = Math.min(100, Math.max(20, Number(event.target.value) || CAMPAIGN_ISSUE_PAGE_SIZE_DEFAULT));
    campaignPageState.issuePage = 1;
    loadCampaignDetail(campaignPageState.campaignId).catch((error) => showToast(error.message, true));
  });
  document.addEventListener("click", (event) => {
    const link = event.target.closest(".campaign-issues-table a[href]");
    if (link) {
      event.preventDefault();
      const url = new URL(link.href, window.location.origin);
      navigatePage("review", { issue: url.searchParams.get("issue") || "" });
    }
  });
}

bindCampaignPageEvents();
