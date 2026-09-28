/* Campaign and Label Analysis read-only surfaces. */

const CAMPAIGN_PAGE_SIZE = 50;
const CAMPAIGN_ISSUE_PAGE_SIZE_DEFAULT = 50;
const campaignPageState = {
  campaignId: "",
  purpose: "",
  source: "all",
  lifecycle: "all",
  query: "",
  groupId: "",
  groupReturnCampaignId: "",
  groupDetail: null,
  issuePage: 1,
  issuePageSize: CAMPAIGN_ISSUE_PAGE_SIZE_DEFAULT,
  issueAssignee: "",
  issueState: "all",
  issueQuery: "",
  detail: null,
};

function campaignLabel(value) {
  const map = {
    labeling: ["标注实验", "Labeling experiment"],
    model_review: ["复核任务", "Review task"],
    active: ["进行中", "Active"],
    draft: ["草稿", "Draft"],
    closed: ["已关闭", "Closed"],
    cancelled: ["已取消", "Cancelled"],
    superseded: ["已替代", "Superseded"],
    activated: ["已激活", "Activated"],
    reopened: ["已重新打开", "Reopened"],
    reassigned: ["转派", "Reassigned"],
    assigned: ["已分配", "Assigned"],
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
    groupId: campaignPageState.groupId,
    campaignGroupId: campaignPageState.groupId,
    purpose,
    lifecycle,
    query,
    campaignPurpose: purpose,
    campaignLifecycle: lifecycle,
    campaignQuery: query,
  };
}

async function mutateCampaignAssignment(issueId, { action, assignee = "", fromAssignee = "", reason = "" } = {}) {
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
          reason,
        }),
      }
    );
    acknowledgeLocalChange(result);
    showToast(uiText("实验分配已更新。", "Campaign assignment updated."));
    await loadCampaignDetail(campaign.id);
  } catch (error) {
    if (String(error.message || "").includes("已更新")) {
      await loadCampaignDetail(campaign.id).catch(() => {});
    }
    showToast(error.message || uiText("更新实验分配失败。", "Unable to update assignment."), true);
  }
}

async function mutateCampaignLifecycle(action) {
  const campaign = campaignPageState.detail?.campaign;
  if (!campaign?.id || !state.session?.is_admin) return;
  const isReopen = action === "reopen";
  const confirmation = {
    close: ["关闭后将冻结成员和进度快照。继续关闭此 Campaign？", "Closing freezes membership and progress. Close this Campaign?"],
    cancel: ["取消后 Campaign 将进入终态，不能重新激活。继续？", "Canceling is terminal and cannot be reactivated. Continue?"],
    supersede: ["替代后 Campaign 将进入终态，不能重新激活。继续？", "Superseding is terminal and cannot be reactivated. Continue?"],
  }[action];
  if (confirmation && !window.confirm(uiText(...confirmation))) return;
  const reasonLabel = {
    activate: ["填写草稿激活原因。", "Enter a reason for activating this draft."],
    cancel: ["填写取消原因。", "Enter a reason for canceling this Campaign."],
    supersede: ["填写替代原因。", "Enter a reason for superseding this Campaign."],
    reopen: ["填写重新打开原因。", "Enter a reason for reopening."],
  }[action];
  const reason = action === "close"
    ? uiText("从 实验管理页关闭。", "Closed from Campaign management.")
    : window.prompt(uiText(...(reasonLabel || ["填写原因。", "Enter a reason."])), "");
  if (reason === null || ((action !== "close") && !String(reason || "").trim())) return;
  const key = globalThis.crypto?.randomUUID?.() || `campaign-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  try {
    const result = await api(`/api/campaigns/${encodeURIComponent(campaign.id)}/${action}`, {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({
        expected_revision: Number(campaign.config_revision || 1),
        idempotency_key: key,
        reason: String(reason || ""),
      }),
    });
    acknowledgeLocalChange(result);
    const successText = {
      activate: ["实验已激活。", "Campaign activated."],
      close: ["实验已关闭并保存快照。", "Campaign closed with a saved snapshot."],
      reopen: ["Campaign 已重新打开。", "Campaign reopened."],
      cancel: ["实验已取消。", "Campaign canceled."],
      supersede: ["实验已标记为替代。", "Campaign superseded."],
    }[action] || ["实验状态已更新。", "Campaign lifecycle updated."];
    showToast(uiText(...successText));
    await loadCampaignDetail(campaign.id);
  } catch (error) {
    if (String(error.message || "").includes("已更新")) {
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

function openCampaignGroup(groupId, { returnCampaignId = "" } = {}) {
  campaignPageState.groupId = String(groupId || "").trim();
  campaignPageState.groupReturnCampaignId = String(returnCampaignId || "").trim();
  campaignPageState.campaignId = "";
  navigatePage("campaigns", campaignRouteOptions({ campaignId: "" }));
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
  groupId = "",
  discussionIssue = "",
  openComments = false,
  commentId = 0,
  discussionChannel = "",
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
  campaignPageState.groupId = String(groupId || route.campaignGroupId || "").trim();
  document.getElementById("campaignsPage")?.classList.toggle(
    "is-detail-view", Boolean(campaignPageState.campaignId || campaignPageState.groupId)
  );
  document.getElementById("labelingExperimentGuide")?.toggleAttribute("hidden", campaignPageState.purpose !== "labeling");
  const lifecycleSelect = document.getElementById("campaignsLifecycle");
  const sourceSelect = document.getElementById("campaignsSource");
  const queryInput = document.getElementById("campaignsQuery");
  if (lifecycleSelect) lifecycleSelect.value = campaignPageState.lifecycle;
  if (sourceSelect) sourceSelect.value = campaignPageState.source;
  if (sourceSelect) enhanceNativeUiSelect(sourceSelect);
  if (queryInput) queryInput.value = campaignPageState.query;
  const labelTab = document.getElementById("campaignsLabelAnalysisTab");
  const allTab = document.getElementById("campaignsAllTab");
  labelTab?.classList.toggle("is-active", campaignPageState.purpose === "labeling");
  labelTab?.setAttribute("aria-selected", campaignPageState.purpose === "labeling" ? "true" : "false");
  allTab?.classList.toggle("is-active", campaignPageState.purpose !== "labeling");
  allTab?.setAttribute("aria-selected", campaignPageState.purpose !== "labeling" ? "true" : "false");
  const groupView = document.getElementById("campaignGroupView");
  if (campaignPageState.groupId) {
    document.getElementById("campaignsListView")?.setAttribute("hidden", "");
    document.getElementById("campaignDetailView")?.setAttribute("hidden", "");
    groupView?.removeAttribute("hidden");
    return loadCampaignGroupDetail(campaignPageState.groupId);
  }
  groupView?.setAttribute("hidden", "");
  if (campaignPageState.campaignId) {
    if (openComments && discussionIssue) {
      campaignPageState.issuePage = 1;
      campaignPageState.issueQuery = String(discussionIssue).trim().slice(0, 128);
      const queryInput = document.getElementById("campaignIssueQuery");
      if (queryInput) queryInput.value = campaignPageState.issueQuery;
    }
    const detail = await loadCampaignDetail(campaignPageState.campaignId);
    if (openComments && discussionIssue) {
      const item = (detail?.issues || []).find((issue) => String(issue.issue_id) === String(discussionIssue));
      if (item && typeof openAnalysisDiscussion === "function") {
        await openAnalysisDiscussion(item.issue_id, {
          source: "campaign",
          kind: "campaign",
          campaignId: campaignPageState.campaignId,
          baselineScope: item.baseline_scope || "",
          discussionChannel: ["case", "campaign", "both"].includes(discussionChannel) ? discussionChannel : "both",
          focusCommentId: Number(commentId) || 0,
        });
      }
    }
    return detail;
  }
  campaignPageState.detail = null;
  document.getElementById("campaignsListView")?.removeAttribute("hidden");
  document.getElementById("campaignDetailView")?.setAttribute("hidden", "");
  return loadCampaignList();
}

async function loadCampaignList() {
  const status = document.getElementById("campaignsListStatus");
  const rowsRoot = document.getElementById("campaignsRows");
  if (status) status.textContent = uiText("正在加载实验…", "Loading campaigns…");
  if (rowsRoot) rowsRoot.innerHTML = `<tr><td colspan="7" class="campaign-empty-state">${escapeHtml(uiText("正在加载…", "Loading…"))}</td></tr>`;
  const payload = await api(campaignListEndpoint());
  const campaignItems = Array.isArray(payload.items) ? payload.items : [];
  const historicalItems = Array.isArray(payload.historical_imports) ? payload.historical_imports : [];
  const items = campaignPageState.source === "legacy_model_review" ? [] : campaignItems;
  const imports = campaignPageState.source === "campaign" ? [] : historicalItems;
  if (status) {
    const noun = campaignPageState.purpose === "labeling"
      ? uiText("个标注实验", "labeling experiments")
      : campaignPageState.purpose === "model_review"
        ? uiText("个复核任务", "review tasks")
        : uiText("个实验", "experiments");
    status.textContent = `${campaignNumber(items.length + imports.length)} ${noun}`;
  }
  if (!rowsRoot) return payload;
  if (!items.length && !imports.length) {
    rowsRoot.innerHTML = `<tr><td colspan="7" class="campaign-empty-state">${escapeHtml(uiText("当前筛选没有 Campaign。", "No campaigns match these filters."))}</td></tr>`;
    return payload;
  }
  const campaignRows = items.map((item) => {
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
      <td><div class="campaign-row-identity"><button type="button" class="campaign-row-button" data-campaign-open="${escapeHtml(item.id)}"><span class="campaign-row-name">${escapeHtml(item.name || item.id)}</span><span class="campaign-row-id">${escapeHtml(item.id)}</span></button>${item.task_group_id ? `<button type="button" class="campaign-group-link" data-campaign-group="${escapeHtml(item.task_group_id)}">${escapeHtml(uiText("查看 Task Group", "View Task Group"))} · ${escapeHtml(item.task_group_id)}</button>` : ""}</div></td>
      <td><span class="campaign-purpose-badge">${escapeHtml(purpose)}</span></td>
      <td><span class="campaign-lifecycle-badge" data-lifecycle="${escapeHtml(item.lifecycle)}">${escapeHtml(campaignLabel(item.lifecycle))}</span></td>
      <td>${campaignNumber(memberCount)} / ${campaignNumber(required)}</td>
      <td>${campaignNumber(submitted)} / ${campaignNumber(required)}</td>
      <td class="campaign-progress-cell">${campaignNumber(completed)} / ${campaignNumber(assigned)}<div class="campaign-progress-bar" aria-label="${Math.round(ratio * 100)}%"><span style="width:${Math.round(ratio * 100)}%"></span></div></td>
      <td>${escapeHtml(baseline)}<span class="campaign-reference-text">${escapeHtml(reference)}</span></td>
    </tr>`;
  }).join("");
  const importRows = imports.map((item) => {
    const stats = item.stats || {};
    return `<tr data-label-import-batch="${escapeHtml(item.id)}">
      <td><div class="campaign-row-identity"><span class="campaign-row-name">${escapeHtml(item.name || item.id)}</span><span class="campaign-row-id">${escapeHtml(item.migration_version || "")}</span></div></td>
      <td><span class="campaign-purpose-badge">${escapeHtml(uiText("历史标签导入", "Historical label import"))}</span></td>
      <td><span class="campaign-lifecycle-badge" data-lifecycle="closed">${escapeHtml(uiText("已导入", "Imported"))}</span></td>
      <td>${campaignNumber(stats.scanned_reviews)} / ${campaignNumber(stats.effective_label_sources)}</td>
      <td>${campaignNumber(stats.reviewer_dedup_votes)}</td>
      <td class="campaign-progress-cell"><span>${escapeHtml(uiText("一致", "Resolved"))} ${campaignNumber(stats.resolved_cases)} · <span class="campaign-import-warning">${escapeHtml(uiText("GT待复核", "GT review"))} ${campaignNumber(stats.gt_review_pending_cases)} · ${escapeHtml(uiText("冲突", "Conflicts"))} ${campaignNumber(stats.conflict_cases)} · ${escapeHtml(uiText("待裁决", "Pending adjudication"))} ${campaignNumber(stats.pending_adjudication_cases)}</span></span></td>
      <td>${escapeHtml(item.baseline_scope || "—")}<span class="campaign-reference-text">${escapeHtml(uiText("来源：历史判错复核", "Source: historical Review"))}</span></td>
    </tr>`;
  }).join("");
  rowsRoot.innerHTML = importRows + campaignRows;
  return payload;
}

async function loadCampaignDetail(campaignId) {
  const list = document.getElementById("campaignsListView");
  const detailRoot = document.getElementById("campaignDetailView");
  const title = document.getElementById("campaignDetailTitle");
  if (list) list.setAttribute("hidden", "");
  if (detailRoot) detailRoot.removeAttribute("hidden");
  if (title) title.textContent = uiText("正在加载实验…", "Loading campaign…");
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
  const members = Number(progress.member_count || 0);
  const assigned = Number(progress.assigned_issue_count || 0);
  const completed = Number(progress.completed_issue_count || 0);
  const required = Number(progress.required_submitter_count || 0);
  const submitted = Number(progress.submitted_submitter_count || 0);
  const pending = Number(progress.pending_issue_count || 0);
  const conflicts = Number(progress.conflict_issue_count || 0);
  const percent = assigned ? Math.min(100, Math.round(completed * 100 / assigned)) : 0;
  const noun = progress.purpose === "labeling" ? "Case" : "Issue";
  root.innerHTML = `
    <div class="campaign-progress-hero"><span>完成进度</span><strong>${campaignNumber(completed)} <small>/ ${campaignNumber(assigned)} ${noun}</small></strong><div class="campaign-progress-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}" aria-label="已完成 ${percent}%"><span style="width:${percent}%"></span></div><small>已分配 ${campaignNumber(assigned)} / ${campaignNumber(members)} · 完成 ${percent}%</small></div>
    <div class="campaign-progress-metric"><span>待处理 ${noun}</span><strong>${campaignNumber(pending)}</strong></div>
    <div class="campaign-progress-metric"><span>已提交 / 所需</span><strong>${campaignNumber(submitted)} <small>/ ${campaignNumber(required)}</small></strong></div>
    <div class="campaign-progress-metric ${conflicts ? "has-conflict" : ""}"><span>冲突待处理</span><strong>${campaignNumber(conflicts)}</strong></div>`;
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

function renderCampaignAssignmentAudit(audit = []) {
  const rows = document.getElementById("campaignAssignmentAuditRows");
  if (!rows) return;
  rows.innerHTML = audit.length
    ? audit.map((item) => {
        const movement = item.action === "assigned"
          ? item.to_assignee
          : item.action === "unassigned"
            ? item.from_assignee
            : `${item.from_assignee || "—"} → ${item.to_assignee || "—"}`;
        return `<tr><td>${escapeHtml(campaignLabel(item.action))}</td><td>${escapeHtml(item.issue_id || "")}</td><td>${escapeHtml(movement)}</td><td>${escapeHtml(item.changed_by || "—")}${item.changed_by_verified ? " · SSO" : ""}</td><td>${campaignNumber(item.config_revision)}</td><td>${escapeHtml(item.reason || "—")}</td><td>${escapeHtml(item.changed_at || "")}</td></tr>`;
      }).join("")
    : `<tr><td colspan="7" class="campaign-empty-state">${escapeHtml(uiText("暂无分配变更。", "No assignment changes."))}</td></tr>`;
}

function renderCampaignLifecycleAudit(audit = []) {
  const rows = document.getElementById("campaignLifecycleAuditRows");
  if (!rows) return;
  rows.innerHTML = audit.length
    ? audit.map((item) => `<tr><td>${escapeHtml(campaignLabel(item.action))}</td><td>${escapeHtml(campaignLabel(item.from_lifecycle))} → ${escapeHtml(campaignLabel(item.to_lifecycle))}</td><td>${escapeHtml(item.changed_by || "—")}${item.changed_by_verified ? " · SSO" : ""}</td><td>${campaignNumber(item.config_revision)}</td><td>${escapeHtml(item.reason || "—")}</td><td>${escapeHtml(item.changed_at || "")}</td></tr>`).join("")
    : `<tr><td colspan="6" class="campaign-empty-state">${escapeHtml(uiText("暂无生命周期变更。", "No lifecycle changes."))}</td></tr>`;
}

function renderCampaignLabelAnalysis(campaign, progress) {
  const root = document.getElementById("campaignLabelAnalysis");
  if (!root) return;
  if (campaign.purpose !== "labeling") {
    root.hidden = true;
    return;
  }
  root.hidden = false;
  const hasResults = Number(progress.submitted_submitter_count || 0) > 0;
  root.classList.toggle("is-empty", !hasResults);
  const empty = document.getElementById("campaignAnalysisEmpty");
  if (empty) empty.hidden = hasResults;
  const exportLink = document.getElementById("campaignLabelExportCsv");
  if (exportLink) {
    const params = new URLSearchParams();
    if (campaignPageState.issueQuery) params.set("q", campaignPageState.issueQuery);
    if (campaignPageState.issueAssignee) params.set("assignee", campaignPageState.issueAssignee);
    if (campaignPageState.issueState !== "all") params.set("state", campaignPageState.issueState);
    const query = params.toString();
    exportLink.href = withBase(`/api/campaigns/${encodeURIComponent(campaign.id)}/analysis/export.csv${query ? `?${query}` : ""}`);
    exportLink.hidden = !state.session?.is_admin || !hasResults;
  }
  const renderCounts = (targetId, values, labels) => {
    const target = document.getElementById(targetId);
    if (!target) return;
    target.innerHTML = `<div class="campaign-analysis-counts">${labels.map(([key, fallback]) => {
      const label = fallback || campaignLabel(key);
      return `<div class="campaign-analysis-count-row"><span>${escapeHtml(label)}</span><strong>${campaignNumber(values?.[key])}</strong></div>`;
    }).join("")}</div>`;
  };
  const renderDistribution = (targetId, values, labels) => {
    const target = document.getElementById(targetId);
    if (!target) return;
    const items = labels.map(([key, fallback]) => ({
      key, label: fallback || campaignLabel(key), count: Math.max(0, Number(values?.[key] || 0)),
    })).filter((item) => item.count > 0);
    target.innerHTML = renderAnalysisClusterGroup({ label: "Case", items,
      annotated_count: items.reduce((sum, item) => sum + item.count, 0) }, { key: targetId }, { animatePies: false });
  };
  renderDistribution("campaignLabelOutputCounts", progress.label_output_counts, [
    ["误触发", "误触发"], ["正确触发", "正确触发"], ["无需协助", "无需协助"],
  ]);
  renderDistribution("campaignReferenceRelationCounts", progress.reference_relation_counts, [
    ["matches_gt"], ["differs_from_gt"], ["fills_missing_gt"],
    ["matches_reference"], ["differs_from_reference"], ["unknown"],
  ]);
  const renderTop = (targetId, values, limit = 12, catalog = []) => {
    const target = document.getElementById(targetId);
    if (!target) return;
    const catalogByKey = new Map((catalog || []).map((item) => [String(item.key || ""), item]));
    const entries = Object.entries(values || {})
      .map(([key, value]) => [String(key), Number(value || 0), catalogByKey.get(String(key))])
      .filter(([, value]) => value > 0)
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .slice(0, limit);
    target.closest(".campaign-analysis-card").hidden = entries.length === 0;
    const maximum = Math.max(1, ...entries.map(([, value]) => value));
    target.innerHTML = entries.length
      ? `<div class="campaign-ranked-list">${entries.map(([key, value, item]) => `<div class="campaign-ranked-row"><span title="${escapeHtml(key)}">${escapeHtml(item?.label || key)}</span><strong>${campaignNumber(value)}</strong><i><b style="width:${Math.round(value / maximum * 100)}%"></b></i></div>`).join("")}</div>`
      : `<span class="campaign-reference-text">${escapeHtml(uiText("暂无结果", "No results"))}</span>`;
  };
  const reviewTagCatalog = state.config?.review_tag_catalog || [];
  const tagCatalogByKey = new Map(reviewTagCatalog.map((item) => [String(item.key || ""), item]));
  const tagSections = { scene: {}, trigger: {}, egress: {}, other: {} };
  for (const [key, rawCount] of Object.entries(progress.tag_counts || {})) {
    const item = tagCatalogByKey.get(String(key));
    const section = String(item?.section || "");
    const target = section === "scene"
      ? "scene"
      : section === "interaction_decision"
        ? "trigger"
        : section === "egress"
          ? "egress"
          : "other";
    const label = String(item?.label || uiText("未分类标签", "Unclassified tag"));
    tagSections[target][String(key)] = Number(rawCount || 0);
  }
  const renderTagSection = (targetId, values) => {
    const target = document.getElementById(targetId);
    if (!target) return;
    const entries = Object.entries(values)
      .sort((left, right) => Number(right[1]) - Number(left[1]) || left[0].localeCompare(right[0]));
    const items = entries.map(([key, count]) => ({ key,
      label: tagCatalogByKey.get(key)?.label || uiText("未分类标签", "Unclassified tag"), count: Number(count) }));
    target.innerHTML = renderAnalysisClusterGroup({ label: "标签次数", items,
      annotated_count: items.reduce((sum, item) => sum + item.count, 0) }, { key: targetId }, { animatePies: false });
    target.closest(".campaign-analysis-card").hidden = items.length === 0;
  };
  renderTagSection("campaignSceneTagCounts", tagSections.scene);
  renderTagSection("campaignTriggerTagCounts", tagSections.trigger);
  renderTagSection("campaignEgressTagCounts", tagSections.egress);
  renderTagSection("campaignOtherTagCounts", tagSections.other);
  renderTop("campaignEvidenceGapCounts", progress.evidence_gap_counts);
  renderTop("campaignScenarioCounts", progress.scenario_counts);
  renderTop("campaignRationaleThemeCounts", progress.rationale_theme_counts, 12, progress.rationale_theme_catalog || []);
  renderCounts("campaignLabelingNoteCounts", {
    conflicts: progress.conflict_issue_count,
    adjudicated: progress.adjudicated_issue_count,
    excluded: progress.excluded_issue_count,
    with_rationale: progress.rationale_issue_count,
    unclustered_rationale: progress.unclustered_rationale_issue_count,
  }, [
    ["conflicts", campaignLabel("conflict")],
    ["adjudicated", campaignLabel("adjudicated")],
    ["excluded", uiText("提出排除", "Exclusion proposed")],
    ["with_rationale", uiText("有标注依据", "With rationale")],
    ["unclustered_rationale", uiText("原因待归类", "Unclustered rationale")],
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
  const isLabeling = campaign.purpose === "labeling";
  const heading = document.getElementById("campaignIssuesHeading");
  if (heading) heading.textContent = isLabeling ? "Case 明细" : "Issue 明细";
  if (count) count.textContent = `${campaignNumber(payload.total)} 个 ${isLabeling ? "Case" : "Issue"}`;
  if (!issues.length) {
    root.innerHTML = `<tr><td colspan="${canManage ? 9 : 8}" class="campaign-empty-state">${escapeHtml(uiText("当前筛选没有 Issue。", "No Issues match these filters."))}</td></tr>`;
  } else {
    root.innerHTML = issues.map((item) => {
      const assignees = (item.assignments || []).map((assignment) => `<span class="campaign-assignee-chip">${escapeHtml(assignment.assignee)}${assignment.assignment_kind !== "base" ? ` · ${escapeHtml(assignment.assignment_kind)}` : ""}${canManage ? `<button class="campaign-unassign-button" type="button" data-campaign-unassign="${escapeHtml(item.issue_id)}" data-campaign-user="${escapeHtml(assignment.assignee)}" aria-label="移除 ${escapeHtml(assignment.assignee)}">×</button>` : ""}</span>`).join("") || "—";
      const enabledUsers = (state.accessUsers || []).filter((user) => user.enabled !== false);
      const currentAssignees = (item.assignments || []).map((assignment) => String(assignment.assignee || "").trim()).filter(Boolean);
      const assignmentControls = canManage
        ? `<div class="campaign-assignment-controls"><div class="campaign-assignment-action"><select data-campaign-new-assignee="${escapeHtml(item.issue_id)}" aria-label="选择新负责人"><option value="">${escapeHtml(uiText("选择负责人", "Choose assignee"))}</option>${enabledUsers.map((user) => `<option value="${escapeHtml(user.username)}">${escapeHtml(user.username)}</option>`).join("")}</select><button class="button button-quiet" type="button" data-campaign-assign="${escapeHtml(item.issue_id)}">${escapeHtml(uiText("分配", "Assign"))}</button></div>${currentAssignees.length ? `<div class="campaign-assignment-action"><select data-campaign-reassign-from="${escapeHtml(item.issue_id)}" aria-label="选择要转出的负责人"><option value="">${escapeHtml(uiText("当前负责人", "Current assignee"))}</option>${currentAssignees.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("")}</select><select data-campaign-reassign-to="${escapeHtml(item.issue_id)}" aria-label="选择转入负责人"><option value="">${escapeHtml(uiText("转派给", "Reassign to"))}</option>${enabledUsers.map((user) => `<option value="${escapeHtml(user.username)}">${escapeHtml(user.username)}</option>`).join("")}</select><button class="button button-quiet" type="button" data-campaign-reassign="${escapeHtml(item.issue_id)}">${escapeHtml(uiText("转派", "Reassign"))}</button></div>` : ""}</div>`
        : "";
      const labelTags = [
        ...(item.tags || []).map((key) => {
          const catalogItem = typeof reviewTagCatalogItem === "function" ? reviewTagCatalogItem(key) : null;
          return { key, label: catalogItem?.label || uiText("未分类标签", "Unclassified tag") };
        }),
        ...(item.evidence_gaps || []).map((key) => ({
          key,
          label: `${uiText("缺证据", "Evidence gap")} · ${typeof evidenceLabel === "function" ? evidenceLabel(key) : uiText("未分类", "Unclassified")}`,
        })),
      ];
      const tagMarkup = labelTags.length
        ? `<div class="campaign-assignee-chips">${labelTags.map((value) => `<span class="campaign-assignee-chip" title="${escapeHtml(value.key)}">${escapeHtml(value.label)}</span>`).join("")}</div>`
        : "—";
      const issueUrl = isLabeling
        ? pageUrl("labeling", { issue: item.issue_id, taskId: campaign.id,
          baselines: (campaign.baseline_scopes || []).map((scope) => String(scope).match(/^release(\d{4})/)?.[1] || scope),
          search: "", status: "all", author: "", assignee: "", cluster: "", label: "all", exclusion: "all", page: 1 })
        : withBase(`/review?issue=${encodeURIComponent(item.issue_id)}`);
      const referenceLabel = item.reference_label || item.gt_label || "—";
      const relation = item.reference_relation && item.reference_relation !== "unknown"
        ? `<span class="campaign-reference-text">${escapeHtml(campaignLabel(item.reference_relation))}</span>`
        : "";
      return `<tr><td><a href="${escapeHtml(issueUrl)}" class="campaign-row-name">${escapeHtml(item.issue_id)}</a><span class="campaign-reference-text">${escapeHtml(item.title || item.scenario || "")}</span><button class="analysis-discussion-link" type="button" data-campaign-discussion="${escapeHtml(item.issue_id)}" data-baseline-scope="${escapeHtml(item.baseline_scope || "")}">${escapeHtml(uiText("讨论", "Discussion"))}</button></td><td>${escapeHtml(referenceLabel)}${relation}</td><td>${escapeHtml(item.expected_output || "—")}</td><td>${tagMarkup}</td><td>${item.is_excluded ? escapeHtml(uiText("提出排除", "Proposed exclusion")) : "—"}</td><td><div class="campaign-assignee-chips">${assignees}</div></td><td>${campaignNumber(item.submitted)} / ${campaignNumber(item.required_submitter_count)}</td><td><span class="campaign-state-badge" data-state="${escapeHtml(item.state)}">${escapeHtml(campaignLabel(item.state))}</span></td>${canManage ? `<td>${assignmentControls}</td>` : ""}</tr>`;
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
  const technical = document.getElementById("campaignDetailTechnical");
  const lifecycle = document.getElementById("campaignDetailLifecycle");
  const snapshot = document.getElementById("campaignCloseSnapshot");
  if (title) title.textContent = campaign.name || campaign.id || "Campaign";
  if (meta) {
    const scopes = campaign.baseline_scopes || [campaign.workset_baseline_scope].filter(Boolean);
    const datasets = scopes.map((scope) => String(scope).match(/^release(\d{4})/)?.[1] || String(scope));
    const noun = campaign.purpose === "labeling" ? "Case" : "Issue";
    meta.textContent = `${datasets.join(" + ") || "当前数据集"} · ${campaignLabel(campaign.purpose || "")} · ${campaignNumber(progress.member_count)} 个 ${noun}${campaign.reference_id ? " · 已冻结 GT 参考" : ""}`;
  }
  if (technical) technical.textContent = `任务 ID：${campaign.id || "—"}\n数据范围：${(campaign.baseline_scopes || []).join(", ") || campaign.workset_baseline_scope || "—"}\n参考：${campaign.reference_type || "—"} · ${campaign.reference_id || "—"}`;
  if (lifecycle) {
    lifecycle.textContent = campaignLabel(campaign.lifecycle);
    lifecycle.dataset.lifecycle = campaign.lifecycle || "";
  }
  const isAdmin = Boolean(state.session?.is_admin);
  const canManageLifecycle = isAdmin && campaign.purpose && !campaign.legacy_read_only;
  const manageMenu = document.querySelector(".campaign-manage-menu");
  if (manageMenu) manageMenu.hidden = !canManageLifecycle;
  const closeButton = document.getElementById("campaignCloseButton");
  const reopenButton = document.getElementById("campaignReopenButton");
  const activateButton = document.getElementById("campaignActivateButton");
  const cancelButton = document.getElementById("campaignCancelButton");
  const supersedeButton = document.getElementById("campaignSupersedeButton");
  const groupButton = document.getElementById("campaignOpenGroupButton");
  if (closeButton) closeButton.hidden = !canManageLifecycle || campaign.lifecycle !== "active";
  if (reopenButton) reopenButton.hidden = !canManageLifecycle || campaign.lifecycle !== "closed";
  if (activateButton) activateButton.hidden = !canManageLifecycle || campaign.lifecycle !== "draft";
  if (cancelButton) cancelButton.hidden = !canManageLifecycle || !["draft", "active"].includes(campaign.lifecycle);
  if (supersedeButton) supersedeButton.hidden = !canManageLifecycle || campaign.lifecycle !== "active";
  if (groupButton) groupButton.hidden = !campaign.task_group_id;
  renderCampaignMetrics(progress);
  renderCampaignLabelAnalysis(campaign, progress);
  renderCampaignRevisions(payload.revisions || []);
  renderCampaignAssignmentAudit(payload.assignment_audit || []);
  renderCampaignLifecycleAudit(payload.lifecycle_audit || []);
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

async function loadCampaignGroupDetail(groupId) {
  const title = document.getElementById("campaignGroupTitle");
  const meta = document.getElementById("campaignGroupMeta");
  const rows = document.getElementById("campaignGroupRows");
  const count = document.getElementById("campaignGroupChildCount");
  if (title) title.textContent = uiText("正在加载 Task Group…", "Loading Task Group…");
  if (rows) rows.innerHTML = `<tr><td colspan="7" class="campaign-empty-state">${escapeHtml(uiText("正在加载…", "Loading…"))}</td></tr>`;
  const payload = await api(`/api/review-task-groups/${encodeURIComponent(groupId)}`);
  campaignPageState.groupDetail = payload;
  const group = payload.group || {};
  const children = payload.children || [];
  if (count) count.textContent = `${campaignNumber(children.length)} ${uiText("个子 Campaign", "child Campaigns")}`;
  const detailsById = new Map((payload.campaigns || []).map((item) => [
    String(item?.campaign?.id || ""), item,
  ]));
  if (title) title.textContent = group.name || group.id || "Task Group";
  if (meta) {
    const runs = (group.source_run_ids || []).filter(Boolean).join(", ") || "—";
    meta.textContent = `${group.id || groupId} · ${campaignLabel(group.purpose)} · ${campaignLabel(group.lifecycle)} · Workset ${group.workset_id || "—"} · ${group.reference_type || "—"}: ${group.reference_id || "—"} · Runs ${runs}`;
  }
  if (!rows) return payload;
  rows.innerHTML = children.length
    ? children.map((child) => {
        const detail = detailsById.get(String(child.campaign_id || "")) || {};
        const campaign = detail.campaign || {};
        const progress = detail.progress || {};
        return `<tr><td>${escapeHtml(child.evaluation_run_id || "—")}</td><td><button class="campaign-group-child-button" type="button" data-campaign-group-child="${escapeHtml(child.campaign_id)}">${escapeHtml(campaign.name || child.campaign_id || "Campaign")}</button><small class="campaign-row-id">${escapeHtml(child.campaign_id || "")}</small></td><td>${escapeHtml(campaignLabel(campaign.purpose))}</td><td><span class="campaign-lifecycle-badge" data-lifecycle="${escapeHtml(campaign.lifecycle || "")}">${escapeHtml(campaignLabel(campaign.lifecycle))}</span></td><td>${campaignNumber(progress.member_count)}</td><td>${campaignNumber(progress.required_submitter_count)}</td><td>${campaignNumber(progress.submitted_submitter_count)} / ${campaignNumber(progress.required_submitter_count)} · ${campaignNumber(progress.completed_issue_count)} ${escapeHtml(uiText("已完成", "completed"))}</td></tr>`;
      }).join("")
    : `<tr><td colspan="7" class="campaign-empty-state">${escapeHtml(uiText("此 Group 没有子 Campaign。", "This group has no child campaigns."))}</td></tr>`;
  return payload;
}

function bindCampaignPageEvents() {
  document.getElementById("campaignCloseButton")?.addEventListener("click", () => {
    mutateCampaignLifecycle("close");
  });
  document.getElementById("campaignReopenButton")?.addEventListener("click", () => {
    mutateCampaignLifecycle("reopen");
  });
  document.getElementById("campaignActivateButton")?.addEventListener("click", () => {
    mutateCampaignLifecycle("activate");
  });
  document.getElementById("campaignCancelButton")?.addEventListener("click", () => {
    mutateCampaignLifecycle("cancel");
  });
  document.getElementById("campaignSupersedeButton")?.addEventListener("click", () => {
    mutateCampaignLifecycle("supersede");
  });
  document.getElementById("caseLabelingCampaignsButton")?.addEventListener("click", () => {
    const params = new URLSearchParams();
    const filters = labelingTaskFilterPayload();
    if (filters.task_id) params.set("task", filters.task_id);
    if (filters.q) params.set("q", filters.q);
    if (filters.issue_ids) params.set("issue_ids", filters.issue_ids);
    if (filters.status && filters.status !== "all") params.set("status", filters.status);
    if (filters.author) params.set("author", filters.author);
    if (filters.assignee) params.set("assignee", filters.assignee);
    if (filters.label && filters.label !== "all") params.set("label", filters.label);
    if (filters.gt && filters.gt !== "all") params.set("gt", filters.gt);
    if (filters.comment_state && filters.comment_state !== "all") params.set("comment_state", filters.comment_state);
    if (filters.exclusion && filters.exclusion !== "all") params.set("exclusion", filters.exclusion);
    if (filters.cluster) params.set("cluster", filters.cluster);
    window.location.assign(`${withBase("/labeling-summary")}${params.toString() ? `?${params}` : ""}`);
  });
  document.getElementById("campaignsRefresh")?.addEventListener("click", () => {
    loadCampaigns({ ...campaignRouteOptions() }).catch((error) => showToast(error.message, true));
  });
  document.getElementById("campaignsFilterForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    campaignPageState.lifecycle = document.getElementById("campaignsLifecycle")?.value || "all";
    campaignPageState.source = document.getElementById("campaignsSource")?.value || "all";
    campaignPageState.query = document.getElementById("campaignsQuery")?.value.trim().slice(0, 128) || "";
    campaignPageState.campaignId = "";
    campaignPageState.issuePage = 1;
    saveCampaignRoute("push", { campaignId: "" });
    loadCampaigns({ ...campaignRouteOptions(), campaignId: "" }).catch((error) => showToast(error.message, true));
  });
  document.getElementById("campaignsAllTab")?.addEventListener("click", () => {
    campaignPageState.purpose = "";
    campaignPageState.campaignId = "";
    campaignPageState.groupId = "";
    saveCampaignRoute("push", { purpose: "", campaignId: "" });
    loadCampaigns({ ...campaignRouteOptions(), purpose: "", campaignId: "" }).catch((error) => showToast(error.message, true));
  });
  document.getElementById("campaignsLabelAnalysisTab")?.addEventListener("click", () => {
    campaignPageState.purpose = "labeling";
    campaignPageState.campaignId = "";
    campaignPageState.groupId = "";
    saveCampaignRoute("push", { purpose: "labeling", campaignId: "" });
    loadCampaigns({ ...campaignRouteOptions(), purpose: "labeling", campaignId: "" }).catch((error) => showToast(error.message, true));
  });
  document.getElementById("campaignsRows")?.addEventListener("click", (event) => {
    const groupButton = event.target.closest("[data-campaign-group]");
    if (groupButton) {
      openCampaignGroup(groupButton.dataset.campaignGroup || "");
      return;
    }
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
    campaignPageState.groupId = "";
    navigatePage("campaigns", campaignRouteOptions({ campaignId: "" }));
  });
  document.getElementById("campaignOpenGroupButton")?.addEventListener("click", () => {
    const campaignId = campaignPageState.detail?.campaign?.id || campaignPageState.campaignId;
    const groupId = campaignPageState.detail?.campaign?.task_group_id;
    if (groupId) openCampaignGroup(groupId, { returnCampaignId: campaignId });
  });
  document.getElementById("campaignGroupBack")?.addEventListener("click", () => {
    const returnCampaignId = campaignPageState.groupReturnCampaignId;
    campaignPageState.groupId = "";
    campaignPageState.campaignId = returnCampaignId;
    navigatePage("campaigns", campaignRouteOptions({ campaignId: returnCampaignId }));
  });
  document.getElementById("campaignGroupRows")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-campaign-group-child]");
    if (!button) return;
    campaignPageState.groupId = "";
    campaignPageState.groupReturnCampaignId = "";
    campaignPageState.campaignId = button.dataset.campaignGroupChild || "";
    navigatePage("campaigns", campaignRouteOptions());
  });
  document.getElementById("campaignIssueFilterButton")?.addEventListener("click", () => {
    campaignPageState.issuePage = 1;
    campaignPageState.issueAssignee = document.getElementById("campaignIssueAssignee")?.value || "";
    campaignPageState.issueState = document.getElementById("campaignIssueState")?.value || "all";
    campaignPageState.issueQuery = document.getElementById("campaignIssueQuery")?.value.trim().slice(0, 128) || "";
    loadCampaignDetail(campaignPageState.campaignId).catch((error) => showToast(error.message, true));
  });
  document.getElementById("campaignIssueRows")?.addEventListener("click", (event) => {
    const discussionButton = event.target.closest("[data-campaign-discussion]");
    if (discussionButton) {
      const campaign = campaignPageState.detail?.campaign || {};
      if (typeof openAnalysisDiscussion === "function") {
        openAnalysisDiscussion(discussionButton.dataset.campaignDiscussion, {
          source: "campaign",
          kind: "campaign",
          campaignId: campaign.id || campaignPageState.campaignId,
          baselineScope: discussionButton.dataset.baselineScope || "",
          discussionChannel: "both",
        }).catch((error) => showToast(error.message, true));
      }
      return;
    }
    const removeButton = event.target.closest("[data-campaign-unassign]");
    if (removeButton) {
      mutateCampaignAssignment(removeButton.dataset.campaignUnassign, {
        action: "unassign",
        fromAssignee: removeButton.dataset.campaignUser || "",
      });
      return;
    }
    const reassignButton = event.target.closest("[data-campaign-reassign]");
    if (reassignButton) {
      const issueId = reassignButton.dataset.campaignReassign || "";
      const fromAssignee = String(document.querySelector(`[data-campaign-reassign-from="${CSS.escape(issueId)}"]`)?.value || "").trim();
      const assignee = String(document.querySelector(`[data-campaign-reassign-to="${CSS.escape(issueId)}"]`)?.value || "").trim();
      if (!fromAssignee || !assignee) {
        showToast(uiText("请选择原负责人和新负责人。", "Choose both current and new assignees."), true);
        return;
      }
      const reason = window.prompt(uiText("填写转派原因。", "Enter a reassignment reason."), "");
      if (!String(reason || "").trim()) return;
      mutateCampaignAssignment(issueId, {
        action: "reassign",
        fromAssignee,
        assignee,
        reason: String(reason).trim(),
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

}

bindCampaignPageEvents();

let labelSummaryRequest = 0;
let labelSummaryPage = 1;
let labelSummaryPageSize = 20;
let labelSummaryRouteRestored = false;
let labelSummarySearchTimer = null;
const labelSummaryFilters = {
  search: "", issueIds: [], taskId: "", status: "all", author: "", assignee: "",
  label: "all", gt: "all", commentState: "all", exclusion: "all", cluster: "",
};

function restoreLabelSummaryRoute() {
  if (labelSummaryRouteRestored) return;
  labelSummaryRouteRestored = true;
  const params = new URLSearchParams(window.location.search);
  labelSummaryFilters.search = String(params.get("q") || "").trim();
  labelSummaryFilters.issueIds = parseFilterList(params.get("issue_ids")).filter((value) => ISSUE_QUERY_ID_RE.test(value));
  labelSummaryFilters.taskId = String(params.get("task") || "").trim();
  labelSummaryFilters.status = ["resolved", "pending", "conflict"].includes(params.get("status")) ? params.get("status") : "all";
  labelSummaryFilters.author = String(params.get("author") || "").trim();
  labelSummaryFilters.assignee = String(params.get("assignee") || "").trim();
  labelSummaryFilters.label = LABELS.includes(params.get("label")) ? params.get("label") : "all";
  labelSummaryFilters.gt = LABELS.includes(params.get("gt")) ? params.get("gt") : "all";
  labelSummaryFilters.commentState = ["with", "without"].includes(params.get("comment_state")) ? params.get("comment_state") : "all";
  labelSummaryFilters.exclusion = ["active", "excluded"].includes(params.get("exclusion")) ? params.get("exclusion") : "all";
  labelSummaryFilters.cluster = String(params.get("cluster") || "").trim();
  labelSummaryPage = Math.max(1, Number(params.get("page") || 1));
  labelSummaryPageSize = CASE_PAGE_SIZES.includes(Number(params.get("page_size"))) ? Number(params.get("page_size")) : 20;
}

function persistLabelSummaryRoute() {
  const params = new URLSearchParams();
  if (labelSummaryFilters.search) params.set("q", labelSummaryFilters.search);
  if (labelSummaryFilters.issueIds.length) params.set("issue_ids", labelSummaryFilters.issueIds.join(","));
  if (labelSummaryFilters.taskId) params.set("task", labelSummaryFilters.taskId);
  if (labelSummaryFilters.status !== "all") params.set("status", labelSummaryFilters.status);
  if (labelSummaryFilters.author) params.set("author", labelSummaryFilters.author);
  if (labelSummaryFilters.assignee) params.set("assignee", labelSummaryFilters.assignee);
  if (labelSummaryFilters.label !== "all") params.set("label", labelSummaryFilters.label);
  if (labelSummaryFilters.gt !== "all") params.set("gt", labelSummaryFilters.gt);
  if (labelSummaryFilters.commentState !== "all") params.set("comment_state", labelSummaryFilters.commentState);
  if (labelSummaryFilters.exclusion !== "all") params.set("exclusion", labelSummaryFilters.exclusion);
  if (labelSummaryFilters.cluster) params.set("cluster", labelSummaryFilters.cluster);
  if (labelSummaryPage > 1) params.set("page", String(labelSummaryPage));
  if (labelSummaryPageSize !== 20) params.set("page_size", String(labelSummaryPageSize));
  window.history.replaceState(
    { ...(window.history.state || {}), page: "labeling-summary" },
    "",
    `${withBase("/labeling-summary")}${params.toString() ? `?${params}` : ""}`,
  );
}

function labelSummaryCaseUrl(filters = {}) {
  return pageUrl("labeling", { issue: "", taskId: labelSummaryFilters.taskId,
    search: labelSummaryFilters.search, issueIds: labelSummaryFilters.issueIds,
    status: labelSummaryFilters.status,
    author: labelSummaryFilters.author, assignee: labelSummaryFilters.assignee,
    cluster: labelSummaryFilters.cluster, label: labelSummaryFilters.label,
    gt: labelSummaryFilters.gt, commentState: labelSummaryFilters.commentState,
    exclusion: labelSummaryFilters.exclusion, page: 1,
    ...filters });
}

function renderLabelSummaryPicker(selector, options, selected) {
  const picker = $(selector);
  populateUiSelect(picker, options, selected);
  bindUiSelect(picker, { maxHeight: 300, maxWidth: 420 });
}

function renderLabelSummaryFilters(tasks, data) {
  const taskOptions = [{ value: "", label: "全部标注（含历史迁移）" }, ...(tasks.items || []).map((task) => ({ value: task.id, label: task.name || "标注任务" }))];
  if (!taskOptions.some((item) => item.value === labelSummaryFilters.taskId)) labelSummaryFilters.taskId = "";
  const labelerOptions = [{ value: "", label: "全部标注人" }, ...(data.labelers || []).map((value) => ({ value, label: value }))];
  if (!labelerOptions.some((item) => item.value === labelSummaryFilters.author)) labelSummaryFilters.author = "";
  const assigneeOptions = [{ value: "", label: "全部任务队列" }, ...(data.assignees || []).map((value) => ({ value, label: value }))];
  if (!assigneeOptions.some((item) => item.value === labelSummaryFilters.assignee)) labelSummaryFilters.assignee = "";
  renderLabelSummaryPicker("#labelSummaryTaskPicker", taskOptions, labelSummaryFilters.taskId);
  renderLabelSummaryPicker("#labelSummaryStatusPicker", [
    { value: "all", label: "全部状态" }, { value: "resolved", label: "已形成结论" },
    { value: "pending", label: "待形成结论" }, { value: "conflict", label: "待裁决 / 需确认" },
  ], labelSummaryFilters.status);
  renderLabelSummaryPicker("#labelSummaryAuthorPicker", labelerOptions, labelSummaryFilters.author);
  renderLabelSummaryPicker("#labelSummaryAssigneePicker", assigneeOptions, labelSummaryFilters.assignee);
  renderLabelSummaryPicker("#labelSummaryLabelPicker", [
    { value: "all", label: "全部类别" }, ...LABELS.map((value) => ({ value, label: value })),
  ], labelSummaryFilters.label);
  renderLabelSummaryPicker("#labelSummaryGtPicker", [
    { value: "all", label: "全部 GT" }, ...LABELS.map((value) => ({ value, label: value })),
  ], labelSummaryFilters.gt);
  renderLabelSummaryPicker("#labelSummaryDiscussionPicker", [
    { value: "all", label: "全部讨论状态" },
    { value: "with", label: "有讨论" }, { value: "without", label: "无讨论" },
  ], labelSummaryFilters.commentState);
  renderLabelSummaryPicker("#labelSummaryExclusionPicker", [
    { value: "all", label: "全部（含问题排除）" }, { value: "active", label: "未排除" },
    { value: "excluded", label: "已排除" },
  ], labelSummaryFilters.exclusion);
  const search = $("#labelSummarySearch");
  if (search && document.activeElement !== search) search.value = labelSummaryFilters.search;
  const exportButton = $("#labelSummaryExportGt");
  if (exportButton) exportButton.disabled = !state.session?.is_admin;
  if (typeof updateIssueQueryButton === "function") updateIssueQueryButton();
}

function labelSummaryFilterPayload() {
  return {
    baselines: selectedBaselineQueryValue(),
    task_id: labelSummaryFilters.taskId,
    q: labelSummaryFilters.search,
    issue_ids: labelSummaryFilters.issueIds.join(","),
    status: labelSummaryFilters.status,
    author: labelSummaryFilters.author,
    assignee: labelSummaryFilters.assignee,
    label: labelSummaryFilters.label,
    gt: labelSummaryFilters.gt,
    comment_state: labelSummaryFilters.commentState,
    exclusion: labelSummaryFilters.exclusion,
    cluster: labelSummaryFilters.cluster,
  };
}

function labelSummaryStatusItems(data) {
  const counts = data.submitted_states || {};
  return [
    { key: "resolved", cssKey: "completed", label: "已形成结论", count: Number(counts.resolved || 0), description: "多来源聚合后已形成唯一结论" },
    { key: "pending", cssKey: "pending", label: "待形成结论", count: Number(counts.pending || 0), description: "已有提交，但还没有形成唯一结论" },
    { key: "conflict", cssKey: "blocked_by_label", label: "待裁决 / 需确认", count: Number(counts.conflict || 0), description: "当前来源之间存在冲突或 Issue 裁决已过期" },
  ];
}

function labelSummaryStatusMarkup(data) {
  const statuses = labelSummaryStatusItems(data);
  const total = statuses.reduce((sum, item) => sum + item.count, 0);
  const segments = total
    ? statuses.filter((item) => item.count).map((item) => {
      const percent = analysisPiePercent(item, total);
      return `<span class="analysis-review-status-segment status-${escapeHtml(item.cssKey)}" data-review-status-key="${escapeHtml(item.key)}" style="width:${percent}%" title="${escapeHtml(`${item.label}: ${item.count}, ${percent}%`)}"></span>`;
    }).join("")
    : '<span class="analysis-review-status-empty">暂无标注提交</span>';
  const legend = statuses.map((item) => {
    const percent = analysisPiePercent(item, total);
    return `<div class="analysis-review-status-legend-item status-${escapeHtml(item.cssKey)}" data-review-status-key="${escapeHtml(item.key)}" role="listitem" tabindex="0" title="${escapeHtml(item.description)}"><span class="analysis-review-status-swatch"></span><span class="analysis-review-status-legend-copy"><strong>${escapeHtml(item.label)}</strong><small>${item.count} · ${percent}%</small></span></div>`;
  }).join("");
  return `<div class="analysis-review-status-visual"><div class="analysis-review-status-bar" role="img" aria-label="${escapeHtml(statuses.map((item) => `${item.label} ${item.count}`).join("；"))}">${segments}</div><div class="analysis-review-status-legend" role="list">${legend}</div></div>`;
}

function labelSummaryMatrixMarkup(data) {
  const labels = ["误触发", "正确触发", "无需协助"];
  const pairs = new Map((data.pairs || []).map((row) => [`${row.gt}|${row.label}`, Number(row.count || 0)]));
  const columnTotals = new Map(labels.map((label) => [label, 0]));
  const rows = labels.map((gt, rowIndex) => {
    const cells = labels.map((label, columnIndex) => {
      const count = pairs.get(`${gt}|${label}`) || 0;
      columnTotals.set(label, (columnTotals.get(label) || 0) + count);
      return `<td class="${gt === label ? "confusion-match" : count ? "confusion-mismatch" : ""}" data-confusion-row="${rowIndex}" data-confusion-col="${columnIndex}" tabindex="0" title="GT ${escapeHtml(gt)} · 标注 ${escapeHtml(label)}: ${count}">${count}</td>`;
    }).join("");
    const rowTotal = labels.reduce((sum, label) => sum + (pairs.get(`${gt}|${label}`) || 0), 0);
    return `<tr><th scope="row" data-confusion-row="${rowIndex}">${escapeHtml(gt)}</th>${cells}<td class="confusion-total" data-confusion-row="${rowIndex}" data-confusion-total tabindex="0">${rowTotal}</td></tr>`;
  }).join("");
  const total = [...columnTotals.values()].reduce((sum, count) => sum + count, 0);
  return `<table class="analysis-confusion-table"><thead><tr><th>GT ↓ / 标注 →</th>${labels.map((label, index) => `<th scope="col" data-confusion-col="${index}">${escapeHtml(label)}</th>`).join("")}<th scope="col" data-confusion-total-col>合计</th></tr></thead><tbody>${rows}</tbody><tfoot><tr><th>合计</th>${labels.map((label, index) => `<td class="confusion-total" data-confusion-col="${index}">${columnTotals.get(label) || 0}</td>`).join("")}<td class="confusion-total">${total}</td></tr></tfoot></table>`;
}

function labelSummaryClusterPanels(data) {
  const catalog = new Map((state.config?.review_tag_catalog || []).map((item) => [item.key, item]));
  const tagCounts = data.tags || {};
  const groupItems = (section, group) => Object.entries(tagCounts)
    .map(([key, count]) => ({ key, count: Number(count || 0), item: catalog.get(key) || {} }))
    .filter(({ item }) => item.section === section && item.group === group)
    .map(({ key, count, item }) => ({ key, count, label: item.label || key, description: item.hint || "" }))
    .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
  const makeGroup = (key, label, items) => ({ key, label, annotated_count: items.reduce((sum, item) => sum + item.count, 0), items });
  const evidenceItems = Object.entries(data.evidence || {}).map(([key, count]) => ({
    key, count: Number(count || 0), label: evidenceLabel(key), description: "",
  })).sort((left, right) => right.count - left.count || left.label.localeCompare(right.label));
  const panels = [
    { key: "evidence", label: "缺失信息", layout: "single", groups: [makeGroup("all", "缺失信息", evidenceItems)] },
    { key: "scene", label: "场景", layout: "dual", groups: [makeGroup("environment", "环境", groupItems("scene", "environment")), makeGroup("self_intent", "自车意图", groupItems("scene", "self_intent"))] },
    { key: "trigger", label: "触发判定", layout: "dual", groups: [makeGroup("false_trigger", "误触发", groupItems("interaction_decision", "false_trigger")), makeGroup("true_trigger", "正确触发", groupItems("interaction_decision", "true_trigger"))] },
    { key: "egress", label: "如何脱困", layout: "dual", groups: [makeGroup("ra", "RA", groupItems("egress", "ra")), makeGroup("no_assist", "无需协助", groupItems("egress", "no_assist"))] },
  ];
  return panels.map((panel) => {
    const dual = panel.layout === "dual";
    return `<article class="page-card analysis-cluster-card layout-${panel.layout}" data-panel="${panel.key}"><div class="section-heading"><div><h3>${escapeHtml(panel.label)}</h3></div></div><div class="analysis-pie-groups ${dual ? "dual" : "single"}">${panel.groups.map((group) => renderAnalysisClusterGroup(group, panel, { dual, animatePies: false })).join("")}</div></article>`;
  }).join("");
}

function labelSummaryCaseMarkup(item) {
  const issueId = String(item.issue_id || "");
  const scene = item.title || item.scenario || "未记录场景";
  const status = ({ resolved: "已形成结论", pending: "待形成结论", conflict: "待裁决 / 需确认" })[item.label_state] || "待形成结论";
  const rationales = item.rationales || [];
  const tags = (item.tags || []).map((key) => `<span class="analysis-chip tag-chip">${escapeHtml(tagLabel(key))}</span>`).join("");
  const evidence = (item.evidence_gaps || []).map((key) => `<span class="analysis-chip evidence-chip">${escapeHtml(evidenceLabel(key))}</span>`).join("");
  const detailUrl = labelSummaryCaseUrl({ issue: issueId });
  const decision = item.decision
    ? `<span class="analysis-comparison-badge ${item.decision.stale ? "comparison-none" : "comparison-match"}">${item.decision.stale ? "裁决需确认" : `Issue 裁决 #${escapeHtml(item.decision.id)}`}</span>`
    : "";
  const actionLabel = item.label_state === "conflict" ? "进入裁决" : "Case 详情";
  return `<article class="analysis-case-row label-summary-case-row"><div class="analysis-case-identity"><a class="analysis-issue-link" href="${escapeHtml(detailUrl)}">${escapeHtml(issueId)}</a><span title="${escapeHtml(scene)}">${escapeHtml(scene)}</span></div><div class="analysis-case-labels"><span>GT ${labelBadge(item.gt_label)}</span><span>标注 ${labelBadge(item.expected_output, "待形成")}</span><span>${escapeHtml(status)}</span>${decision}${item.is_excluded ? '<span class="analysis-comparison-badge comparison-none">问题排除</span>' : ""}</div><div class="analysis-case-reason"><strong class="${rationales.length ? "" : "reason-empty"}">${escapeHtml(rationales[0] || "未填写标注依据")}</strong>${rationales.slice(1).map((reason) => `<p>${escapeHtml(reason)}</p>`).join("")}<div class="analysis-chip-list">${tags}${evidence}</div></div><div class="analysis-case-meta"><span>${escapeHtml((item.authors || []).join("、") || "未记录标注人")}</span><span>${Number(item.source_count || 0)} 个来源${item.created_at ? ` · ${escapeHtml(formatTime(item.created_at))}` : ""}</span><span class="analysis-case-actions"><a class="text-link" href="${escapeHtml(detailUrl)}">${actionLabel}</a></span></div></article>`;
}

function renderLabelingSummary(data) {
  const root = $("#labelSummaryContent");
  const comparable = (data.pairs || []).reduce((sum, row) => sum + Number(row.count || 0), 0);
  const matches = (data.pairs || []).filter((row) => row.gt === row.label).reduce((sum, row) => sum + Number(row.count || 0), 0);
  const page = Number(data.page || 1);
  const pageCount = Math.max(1, Number(data.page_count || 0));
  root.innerHTML = `<section class="analysis-summary-grid" aria-label="Labeling overview"><article class="analysis-stat-card"><span>Case 标注</span><strong>${Number(data.annotated || 0)}</strong><small>当前范围 ${Number(data.total || 0)} 个 Case</small></article><article class="analysis-stat-card"><span>已填写依据</span><strong>${Number(data.reason_count || 0)}</strong><small>未填写 ${Number(data.empty_reason_count || 0)}</small></article><article class="analysis-stat-card"><span>结构化缺失信息</span><strong>${Number(data.structured_evidence_count || 0)}</strong><small>至少选择 1 项</small></article></section>
    <section class="analysis-decision-grid" aria-label="Label state and GT comparison"><section class="page-card analysis-review-status-card"><div class="section-heading analysis-review-status-heading"><div><h3>标注状态</h3></div><small>${Number(data.annotated || 0)} 个已提交 Case</small></div><div class="analysis-review-status-chart" id="labelSummaryStatusChart">${labelSummaryStatusMarkup(data)}</div></section><section class="page-card analysis-confusion-card"><div class="section-heading analysis-confusion-heading"><div><h3>GT × 标注结果混淆矩阵</h3></div><small>可比较 ${comparable} · 一致 ${matches}</small></div><div class="analysis-confusion-wrap" id="labelSummaryConfusionMatrix">${labelSummaryMatrixMarkup(data)}</div></section></section>
    <section class="analysis-cluster-grid" id="labelSummaryClusterPanels" aria-label="Structured labeling clusters">${labelSummaryClusterPanels(data)}</section>
    <section class="page-card analysis-case-card"><div class="section-heading"><div><h3>标注依据明细</h3></div><small>共 ${Number(data.annotated || 0)} 个 Case · 当前页 ${(data.items || []).length} 个</small></div><div class="analysis-case-list" id="labelSummaryCaseList">${(data.items || []).length ? data.items.map(labelSummaryCaseMarkup).join("") : '<div class="analysis-empty">当前范围暂无标注提交</div>'}</div><nav class="case-pagination gallery-pagination label-summary-pagination" aria-label="标注依据明细分页"><div class="case-pagination-main"><button class="button button-quiet" id="labelSummaryPrevious" type="button" ${page <= 1 ? "disabled" : ""}>上一页</button><span id="labelSummaryPageState">${page} / ${pageCount}</span><button class="button button-quiet" id="labelSummaryNext" type="button" ${page >= pageCount ? "disabled" : ""}>下一页</button><span class="page-jump-control"><label for="labelSummaryPageJump">跳至</label><input id="labelSummaryPageJump" type="number" min="1" max="${pageCount}" value="${page}" inputmode="numeric" ${pageCount <= 1 ? "disabled" : ""}/><span>页</span><button class="button button-quiet" id="labelSummaryPageJumpButton" type="button" ${pageCount <= 1 ? "disabled" : ""}>跳转</button></span></div><label class="case-page-size" for="labelSummaryPageSize"><span>每页</span><select id="labelSummaryPageSize"><option value="10">10</option><option value="20">20</option><option value="50">50</option><option value="100">100</option></select><span>条</span></label></nav></section>`;
  $("#labelSummaryPageSize").value = String(Number(data.page_size || labelSummaryPageSize));
  bindAnalysisReviewStatusHover($("#labelSummaryStatusChart"));
  bindAnalysisConfusionHover($("#labelSummaryConfusionMatrix")?.querySelector(".analysis-confusion-table"));
  bindAnalysisPieHover($("#labelSummaryClusterPanels"));
  clearAnalysisPieEnterAnimations($("#labelSummaryClusterPanels"));
  $("#labelSummaryPrevious")?.addEventListener("click", () => { labelSummaryPage = Math.max(1, page - 1); loadLabelingSummary().catch((error) => showToast(error.message, true)); });
  $("#labelSummaryNext")?.addEventListener("click", () => { labelSummaryPage = Math.min(pageCount, page + 1); loadLabelingSummary().catch((error) => showToast(error.message, true)); });
  $("#labelSummaryPageJumpButton")?.addEventListener("click", () => { labelSummaryPage = Math.max(1, Math.min(pageCount, Number($("#labelSummaryPageJump")?.value || 1))); loadLabelingSummary().catch((error) => showToast(error.message, true)); });
  $("#labelSummaryPageJump")?.addEventListener("keydown", (event) => { if (event.key === "Enter") $("#labelSummaryPageJumpButton")?.click(); });
  $("#labelSummaryPageSize")?.addEventListener("change", (event) => { labelSummaryPageSize = Number(event.target.value || 20); labelSummaryPage = 1; loadLabelingSummary().catch((error) => showToast(error.message, true)); });
}
async function loadLabelingSummary() {
  restoreLabelSummaryRoute();
  const seq = ++labelSummaryRequest;
  const root = $("#labelSummaryContent");
  if (!root) return;
  root.innerHTML = '<div class="page-card campaign-analysis-empty">正在汇总标注…</div>';
  try {
    const baselines = selectedBaselineQueryValue();
    const tasks = await api(`/api/labeling/tasks?baselines=${encodeURIComponent(baselines)}`);
    if (seq !== labelSummaryRequest || state.activePage !== "labeling-summary") return;
    if (!(tasks.items || []).some((task) => task.id === labelSummaryFilters.taskId)) {
      labelSummaryFilters.taskId = "";
    }
    const params = new URLSearchParams({
      baselines,
      task_id: labelSummaryFilters.taskId,
      q: labelSummaryFilters.search,
      issue_ids: labelSummaryFilters.issueIds.join(","),
      status: labelSummaryFilters.status,
      author: labelSummaryFilters.author,
      assignee: labelSummaryFilters.assignee,
      exclusion: labelSummaryFilters.exclusion,
      label: labelSummaryFilters.label === "all" ? "" : labelSummaryFilters.label,
      gt: labelSummaryFilters.gt === "all" ? "" : labelSummaryFilters.gt,
      comment_state: labelSummaryFilters.commentState,
      cluster: labelSummaryFilters.cluster,
      page: String(labelSummaryPage),
      page_size: String(labelSummaryPageSize),
    });
    const data = await api(`/api/labeling/summary?${params.toString()}`);
    if (seq !== labelSummaryRequest || state.activePage !== "labeling-summary") return;
    labelSummaryPage = Number(data.page || 1);
    labelSummaryPageSize = Number(data.page_size || 20);
    renderLabelSummaryFilters(tasks, data);
    renderLabelingSummary(data);
    persistLabelSummaryRoute();
  } catch(error) {
    if (seq === labelSummaryRequest) root.innerHTML = `<div class="page-card campaign-analysis-empty">${escapeHtml(error.message)}</div>`;
    throw error;
  }
}
document.getElementById("labelSummaryFilterForm")?.addEventListener("submit", (event) => {
  event.preventDefault();
  window.clearTimeout(labelSummarySearchTimer);
  labelSummaryFilters.search = $("#labelSummarySearch")?.value.trim() || "";
  labelSummaryPage = 1;
  loadLabelingSummary().catch((error) => showToast(error.message, true));
});
document.getElementById("labelSummarySearch")?.addEventListener("input", (event) => {
  labelSummaryFilters.search = event.target.value.trim();
  if (labelSummaryFilters.issueIds.length) {
    labelSummaryFilters.issueIds = [];
    if (typeof updateIssueQueryButton === "function") updateIssueQueryButton();
  }
  labelSummaryPage = 1;
  window.clearTimeout(labelSummarySearchTimer);
  labelSummarySearchTimer = window.setTimeout(() => loadLabelingSummary().catch((error) => showToast(error.message, true)), 280);
});
[
  ["labelSummaryTask", "taskId"], ["labelSummaryStatus", "status"],
  ["labelSummaryAuthor", "author"], ["labelSummaryAssignee", "assignee"],
  ["labelSummaryLabel", "label"], ["labelSummaryGt", "gt"],
  ["labelSummaryDiscussion", "commentState"],
  ["labelSummaryExclusion", "exclusion"],
].forEach(([id, key]) => document.getElementById(id)?.addEventListener("change", (event) => {
  labelSummaryFilters[key] = event.target.value;
  if (key === "taskId") {
    labelSummaryFilters.author = "";
    labelSummaryFilters.assignee = "";
  }
  labelSummaryFilters.cluster = "";
  labelSummaryPage = 1;
  loadLabelingSummary().catch((error) => showToast(error.message, true));
}));
document.getElementById("labelSummaryReset")?.addEventListener("click", () => {
  Object.assign(labelSummaryFilters, {
    search: "", issueIds: [], taskId: "", status: "all", author: "", assignee: "",
    label: "all", gt: "all", commentState: "all", exclusion: "all", cluster: "",
  });
  if (typeof updateIssueQueryButton === "function") updateIssueQueryButton();
  labelSummaryPage = 1;
  labelSummaryPageSize = 20;
  loadLabelingSummary().catch((error) => showToast(error.message, true));
});
document.getElementById("labelSummaryRefresh")?.addEventListener("click",()=>loadLabelingSummary().catch(error=>showToast(error.message,true)));
document.getElementById("labelSummaryExportGt")?.addEventListener("click", () => {
  exportLabelingGtUpdate(labelSummaryFilterPayload(), document.getElementById("labelSummaryExportGt"))
    .catch((error) => showToast(error.message, true));
});
