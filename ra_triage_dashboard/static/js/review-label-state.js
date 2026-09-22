/* Shared Issue-label projection for the Review gallery and detail view. */
function sharedLabelStateVisual(labelState = {}) {
  const state = String(labelState.state || "none");
  const relation = String(labelState.gt_relation || "unknown");
  if (state === "resolved") {
    if (labelState.gt_review_pending) {
      return { kind: "needs-review", zh: "GT 待复核", en: "Needs GT review" };
    }
    if (relation === "matches_gt") {
      return { kind: "matches", zh: "与 GT 一致", en: "Matches GT" };
    }
    if (relation === "differs_from_gt") {
      return { kind: "needs-review", zh: "GT 待复核", en: "Needs GT review" };
    }
    if (relation === "fills_missing_gt") {
      return { kind: "needs-review", zh: "GT 待复核", en: "Needs GT review" };
    }
    return { kind: "unknown", zh: "GT 未知", en: "GT unknown" };
  }
  if (state === "conflict") {
    return { kind: "conflict", zh: "标签冲突", en: "Label conflict" };
  }
  if (state === "stale") {
    return { kind: "stale", zh: "需重新确认", en: "Needs reconfirmation" };
  }
  if (state === "pending") {
    return { kind: "pending", zh: "标签待完成", en: "Label pending" };
  }
  return { kind: "none", zh: "无共享标签", en: "No shared label" };
}

function sharedLabelStateStateText(value) {
  return ({
    none: uiText("无共享标签", "No shared label"),
    pending: uiText("待完成", "Pending"),
    resolved: uiText("已形成结论", "Resolved"),
    conflict: uiText("冲突", "Conflict"),
    stale: uiText("需重新确认", "Needs reconfirmation"),
  })[String(value || "none")] || uiText("待完成", "Pending");
}

function sharedLabelStateMethodText(value) {
  return ({
    single: uiText("单人", "Single"),
    consensus: uiText("共识", "Consensus"),
    adjudication: uiText("裁决", "Adjudication"),
  })[String(value || "single")] || uiText("单人", "Single");
}

function sharedLabelStateRelationText(value) {
  return ({
    matches_gt: uiText("与 GT 一致", "Matches GT"),
    differs_from_gt: uiText("GT 待复核", "Needs GT review"),
    fills_missing_gt: uiText("补充缺失 GT", "Fills missing GT"),
    unknown: uiText("GT 关系未知", "GT relation unknown"),
  })[String(value || "unknown")] || uiText("GT 关系未知", "GT relation unknown");
}

function sharedLabelStateButtonMarkup(item, { showEmpty = false, compact = false } = {}) {
  const labelState = item?.label_state || {};
  const visual = sharedLabelStateVisual(labelState);
  if (visual.kind === "none" && !showEmpty) return "";
  const issueId = escapeHtml(item?.issue_id || "");
  const sourceCount = Array.isArray(labelState.sources) ? labelState.sources.length : 0;
  const sourceCountMarkup = sourceCount && !compact
    ? `<small class="shared-label-state-source-count"><span class="ui-lang-zh">来源 ${sourceCount}</span><span class="ui-lang-en">${sourceCount} source${sourceCount === 1 ? "" : "s"}</span></small>`
    : "";
  const prefixZh = compact ? "共享" : "共享标签";
  const prefixEn = compact ? "Shared" : "Shared label";
  const title = escapeHtml(
    uiText(
      `${visual.zh} · 查看 ${item?.issue_id || ""} 的共享标签来源`,
      `${visual.en} · View shared label sources for ${item?.issue_id || ""}`
    )
  );
  return `<button class="shared-label-state-trigger shared-label-state-${visual.kind}${compact ? " shared-label-state-compact" : ""}" type="button" data-open-shared-label-state data-issue-id="${issueId}" aria-label="${title}" title="${title}">
    <span class="shared-label-state-prefix"><span class="ui-lang-zh">${prefixZh}</span><span class="ui-lang-en">${prefixEn}</span></span>
    <span class="shared-label-state-value"><span class="ui-lang-zh">${escapeHtml(visual.zh)}</span><span class="ui-lang-en">${escapeHtml(visual.en)}</span></span>
    ${sourceCountMarkup}
  </button>`;
}

function sharedLabelStateSourceMarkup(source, issueId) {
  const taskId = String(source?.task_id || "");
  const sourceRunId = String(source?.source_run_id || "");
  const revisionSummaries = Array.isArray(source?.revision_summaries)
    ? source.revision_summaries
    : [];
  const revisionsMarkup = revisionSummaries.length
    ? `<ul class="shared-label-revision-list">${revisionSummaries.map((revision) => `<li><code>#${escapeHtml(String(revision.id || ""))}</code><span>${escapeHtml(String(revision.expected_output || uiText("待补充", "Pending")))}</span></li>`).join("")}</ul>`
    : `<p class="shared-label-source-empty">${uiText("暂无提交版本", "No submitted revisions")}</p>`;
  const adjudication = source?.adjudication;
  const legacySources = Array.isArray(source?.legacy_sources) ? source.legacy_sources : [];
  const legacySourceMarkup = legacySources.length
    ? `<div class="shared-label-source-revisions"><strong><span class="ui-lang-zh">历史判错复核来源</span><span class="ui-lang-en">Historical Review sources</span></strong><ul class="shared-label-revision-list">${legacySources.map((item) => `<li><code>#${escapeHtml(String(item.source_annotation_id || ""))}</code><span>${escapeHtml(String(item.source_reviewer || "—"))} · ${escapeHtml(String(item.source_label || item.source_review_status || "—"))} · ${escapeHtml(String(item.source_run_id || "无 Run"))}</span></li>`).join("")}</ul></div>`
    : "";
  const adjudicationMarkup = adjudication
    ? `<div class="shared-label-source-adjudication"><strong><span class="ui-lang-zh">裁决</span><span class="ui-lang-en">Adjudication</span> #${escapeHtml(String(adjudication.id || ""))}</strong><span>${adjudication.stale ? uiText("源版本已变化，需重新确认", "Source revisions changed; reconfirmation is needed") : uiText("来源版本有效", "Source revisions are current")}</span><small>${escapeHtml((adjudication.source_revision_ids || []).map((value) => `#${value}`).join(" · ") || "—")}</small></div>`
    : "";
  let editLink = `<span class="shared-label-readonly-note"><span class="ui-lang-zh">只读来源摘要</span><span class="ui-lang-en">Read-only source summary</span></span>`;
  if (state.session?.is_admin && typeof pageUrl === "function") {
    const href = pageUrl("labeling", {
      issue: issueId,
      taskId,
      search: "",
      status: "all",
      author: "",
      assignee: "",
      cluster: "",
      label: "all",
      exclusion: "all",
      page: 1,
    });
    editLink = `<a class="button button-quiet shared-label-edit-link" data-labeling-edit-link href="${escapeHtml(href)}"><span class="ui-lang-zh">打开对应 Task / Issue</span><span class="ui-lang-en">Open this Task / Issue</span></a>`;
  }
  return `<article class="shared-label-source">
    <div class="shared-label-source-heading">
      <strong><span class="ui-lang-zh">${taskId ? "任务" : "自由修正"}</span><span class="ui-lang-en">${taskId ? "Task" : "Standalone correction"}</span></strong>
      <span class="shared-label-source-state">${escapeHtml(sharedLabelStateStateText(source?.state))} · ${escapeHtml(sharedLabelStateMethodText(source?.method))}</span>
    </div>
    <dl class="shared-label-source-facts">
      <div><dt>Label Case</dt><dd><code>${escapeHtml(String(source?.label_case_id || "—"))}</code></dd></div>
      <div><dt><span class="ui-lang-zh">Task</span><span class="ui-lang-en">Task</span></dt><dd><code>${escapeHtml(taskId || "—")}</code></dd></div>
      <div><dt><span class="ui-lang-zh">来源 Run</span><span class="ui-lang-en">Source Run</span></dt><dd><code>${escapeHtml(sourceRunId || "—")}</code></dd></div>
      <div><dt><span class="ui-lang-zh">结果</span><span class="ui-lang-en">Result</span></dt><dd>${escapeHtml(String(source?.expected_output || "—"))}</dd></div>
      ${source?.source_type === "legacy_model_review" ? `<div><dt><span class="ui-lang-zh">来源</span><span class="ui-lang-en">Source</span></dt><dd>${escapeHtml(String(source?.import_batch_name || "历史判错复核"))}</dd></div><div><dt><span class="ui-lang-zh">冻结 GT</span><span class="ui-lang-en">Frozen GT</span></dt><dd>${escapeHtml(String(source?.frozen_gt_label || "—"))}</dd></div>` : ""}
    </dl>
    <div class="shared-label-source-revisions"><strong><span class="ui-lang-zh">来源版本</span><span class="ui-lang-en">Source revisions</span></strong>${revisionsMarkup}</div>
    ${legacySourceMarkup}
    ${adjudicationMarkup}
    <div class="shared-label-source-actions">${editLink}</div>
  </article>`;
}

function openSharedLabelStateDialog(item) {
  const dialog = $("#sharedLabelStateDialog");
  const body = $("#sharedLabelStateDialogContent");
  const meta = $("#sharedLabelStateDialogMeta");
  if (!dialog || !body || !meta || !item) return;
  const labelState = item.label_state || {};
  const visual = sharedLabelStateVisual(labelState);
  const issueId = String(item.issue_id || "");
  const gtLabel = String(item.gt_label || "");
  const expectedOutput = String(labelState.expected_output || "");
  const sourceItems = Array.isArray(labelState.sources) ? labelState.sources : [];
  const taskIds = Array.isArray(labelState.source_task_ids) ? labelState.source_task_ids : [];
  const revisionIds = Array.isArray(labelState.source_revision_ids) ? labelState.source_revision_ids : [];
  meta.innerHTML = `<div class="shared-label-dialog-summary shared-label-state-${visual.kind}">
    <span class="shared-label-dialog-status"><span class="ui-lang-zh">${escapeHtml(visual.zh)}</span><span class="ui-lang-en">${escapeHtml(visual.en)}</span></span>
    <span><span class="ui-lang-zh">Issue</span><span class="ui-lang-en">Issue</span> <code>${escapeHtml(issueId)}</code></span>
    <span><span class="ui-lang-zh">GT</span><span class="ui-lang-en">GT</span> · ${escapeHtml(gtLabel || "—")}</span>
    <span><span class="ui-lang-zh">标签状态</span><span class="ui-lang-en">Label state</span> · ${escapeHtml(sharedLabelStateStateText(labelState.state))}</span>
    ${expectedOutput ? `<span><span class="ui-lang-zh">期望输出</span><span class="ui-lang-en">Expected output</span> · ${escapeHtml(expectedOutput)}</span>` : ""}
    <span><span class="ui-lang-zh">与 GT 的关系</span><span class="ui-lang-en">GT relation</span> · ${escapeHtml(sharedLabelStateRelationText(labelState.gt_relation))}</span>
    <span><span class="ui-lang-zh">解析方式</span><span class="ui-lang-en">Method</span> · ${escapeHtml(sharedLabelStateMethodText(labelState.method))}</span>
    <small><span class="ui-lang-zh">任务 ${taskIds.length} · 版本 ${revisionIds.length}</span><span class="ui-lang-en">${taskIds.length} task(s) · ${revisionIds.length} revision(s)</span></small>
  </div>`;
  body.innerHTML = sourceItems.length
    ? sourceItems.map((source) => sharedLabelStateSourceMarkup(source, issueId)).join("")
    : `<div class="shared-label-empty"><span class="ui-lang-zh">当前范围没有共享标签来源记录。</span><span class="ui-lang-en">No shared label sources exist for this Issue in the current baseline.</span></div>`;
  if (!dialog.dataset.sharedLabelBound) {
    dialog.dataset.sharedLabelBound = "true";
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.querySelector("[data-close-shared-label-state]")?.addEventListener("click", () => dialog.close());
    body.addEventListener("click", (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest("[data-labeling-edit-link]")) dialog.close();
    });
  }
  if (!dialog.open) dialog.showModal();
}

function bindSharedLabelStateTriggers(root, getItem) {
  root?.querySelectorAll("[data-open-shared-label-state]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const item = getItem?.(button.dataset.issueId);
      if (item) openSharedLabelStateDialog(item);
    });
  });
}

function currentRunReviewStatusMarkup(item) {
  const annotation = item?.annotation || null;
  const annotationRunId = String(annotation?.model_run_id || "").trim();
  const belongsToSelectedRun = state.selectedRunId
    ? Boolean(annotation?.id && annotationRunId === state.selectedRunId)
    : Boolean(annotation?.id);
  const status = !belongsToSelectedRun
    ? "unsubmitted"
    : String(annotation?.review_status || "pending");
  const labels = {
    unsubmitted: { zh: "未提交", en: "Not submitted" },
    pending: { zh: "待补充", en: "Needs more detail" },
    reviewed: { zh: "已提交", en: "Submitted" },
    needs_gt_review: { zh: "已提交", en: "Submitted" },
  };
  const label = labels[status] || labels.unsubmitted;
  const title = state.selectedRunId
    ? uiText("当前 Run 的判错复核进度", "Model error review progress for the selected Run")
    : uiText("当前 Review 范围的判错复核进度", "Model error review progress in the current scope");
  return `<span class="issue-card-run-review-state" title="${escapeHtml(title)}"><span class="issue-card-run-review-prefix"><span class="ui-lang-zh">判错复核</span><span class="ui-lang-en">Model review</span></span><span class="issue-card-run-review-value"><span class="ui-lang-zh">${label.zh}</span><span class="ui-lang-en">${label.en}</span></span></span>`;
}
