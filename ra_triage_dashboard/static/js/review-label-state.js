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
    return { kind: "conflict", zh: "标签有分歧", en: "Label disagreement" };
  }
  if (state === "stale") {
    return { kind: "stale", zh: "待复核", en: "Needs recheck" };
  }
  if (state === "pending") {
    return { kind: "pending", zh: "标签待补齐", en: "Label incomplete" };
  }
  return { kind: "none", zh: "无共享标签", en: "No shared label" };
}

function sharedLabelStateStateText(value) {
  return ({
    none: uiText("无共享标签", "No shared label"),
    pending: uiText("待补齐", "Incomplete"),
    resolved: uiText("已确认", "Confirmed"),
    conflict: uiText("有分歧", "Disagreement"),
    stale: uiText("待复核", "Needs recheck"),
  })[String(value || "none")] || uiText("待补齐", "Incomplete");
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

function sharedLabelStateButtonMarkup(item, { showEmpty = false, compact = false, summaryOnly = false } = {}) {
  const labelState = item?.label_state || {};
  const visual = sharedLabelStateVisual(labelState);
  if (visual.kind === "none" && !showEmpty) return "";
  const issueId = escapeHtml(item?.issue_id || "");
  if (summaryOnly) {
    return `<button class="history-inline-button label-summary-inline-button" type="button" data-open-shared-label-state data-issue-id="${issueId}" aria-keyshortcuts="L" aria-haspopup="dialog" aria-label="${escapeHtml(uiText("标注汇总与裁决", "Label summary and decisions"))}" title="${escapeHtml(uiText("查看标注、分歧与裁决（L）", "View labels, disagreements and decisions (L)"))}"><span class="ui-lang-zh">汇总</span><span class="ui-lang-en">Summary</span><kbd class="review-control-shortcut" aria-hidden="true">L</kbd></button>`;
  }
  const sourceCount = Array.isArray(labelState.sources) ? labelState.sources.length : 0;
  const sourceCountMarkup = sourceCount && !compact
    ? `<small class="shared-label-state-source-count"><span class="ui-lang-zh">来源 ${sourceCount}</span><span class="ui-lang-en">${sourceCount} source${sourceCount === 1 ? "" : "s"}</span></small>`
    : "";
  const prefixMarkup = compact
    ? ""
    : `<span class="shared-label-state-prefix"><span class="ui-lang-zh">共享标签</span><span class="ui-lang-en">Shared label</span></span>`;
  const title = escapeHtml(
    uiText(
      `${visual.zh} · 查看 ${item?.issue_id || ""} 的共享标签来源`,
      `${visual.en} · View shared label sources for ${item?.issue_id || ""}`
    )
  );
  return `<button class="shared-label-state-trigger shared-label-state-${visual.kind}${compact ? " shared-label-state-compact" : ""}" type="button" data-open-shared-label-state data-issue-id="${issueId}" aria-label="${title}" title="${title}">
    ${prefixMarkup}
    <span class="shared-label-state-value"><span class="ui-lang-zh">${escapeHtml(visual.zh)}</span><span class="ui-lang-en">${escapeHtml(visual.en)}</span></span>
    ${sourceCountMarkup}
  </button>`;
}

function sharedLabelRevisionTagsMarkup(revision) {
  if (!Array.isArray(revision.tags)) {
    return `<p class="shared-label-revision-empty">${uiText("此版本未提供 Issue 标签明细", "Issue tag details are unavailable for this revision")}</p>`;
  }
  const tags = [...new Set(revision.tags.map((key) => String(key || "")).filter(Boolean))];
  if (!tags.length) {
    return `<p class="shared-label-revision-empty">${uiText("此版本未填写 Issue 标签", "No Issue tags recorded in this revision")}</p>`;
  }
  const groups = [
    ["environment", t("tag.env")], ["self_intent", t("tag.ego_intent")],
    ["false_trigger", t("tag.false_trigger")], ["true_trigger", t("tag.should_trigger")],
    ["ra", t("tag.correct_trigger")], ["no_assist", t("tag.no_assist")],
    ["other", uiText("其他标签", "Other tags")],
  ];
  const knownGroups = new Set(groups.map(([key]) => key));
  const items = tags.map((key) => {
    const item = reviewTagCatalogItem(key) || {};
    return { key, section: item.section || "", group: knownGroups.has(item.group) ? item.group : "other" };
  });
  return `<dl class="shared-label-revision-tags">${groups.map(([group, label]) => {
    const selected = items.filter((item) => item.group === group);
    if (!selected.length) return "";
    return `<div><dt>${escapeHtml(label)}</dt><dd class="analysis-chip-list">${selected.map((item) => `<span class="analysis-chip tag-chip" data-tag-section="${escapeHtml(item.section)}" data-tag-group="${escapeHtml(item.group)}">${escapeHtml(tagLabel(item.key))}</span>`).join("")}</dd></div>`;
  }).join("")}</dl>`;
}

function sharedLabelRevisionMarkup(revision, source, images = []) {
  const isResult = source?.state === "resolved"
    && Number(source.result_revision_id) === Number(revision.id);
  return `<li class="shared-label-revision">
    <div class="shared-label-revision-head"><code>#${escapeHtml(String(revision.id || ""))}</code>${labelBadge(String(revision.expected_output || ""), uiText("待补充", "Pending"))}
      ${isResult ? `<span class="shared-label-revision-result">${uiText("结果依据", "Result source")}</span>` : ""}
      ${revision.is_excluded ? `<span class="tag exclusion-tag">${uiText("已排除此 Issue", "Issue excluded")}</span>` : ""}
    </div>
    <div class="shared-label-revision-meta"><span>${uiText("标注人", "Author")} · ${escapeHtml(String(revision.author || uiText("未记录", "Not recorded")))}</span>${revision.created_at ? `<time datetime="${escapeHtml(String(revision.created_at))}">${formatTime(revision.created_at)}</time>` : ""}</div>
    ${sharedLabelRevisionTagsMarkup(revision)}
    <div class="shared-label-revision-note"><strong>${uiText("标注说明", "Label rationale")}</strong><p class="${revision.rationale ? "shared-label-revision-rationale" : "shared-label-revision-empty"}">${escapeHtml(String(revision.rationale || uiText("此版本未填写标注说明", "No rationale recorded in this revision")))}</p></div>
    ${images.length ? `<div class="pending-screenshot-list">${labelImageMarkup(images)}</div>` : ""}
  </li>`;
}

function sharedLabelSourceContextMarkup(context, issueId) {
  const taskName = String(context.task_name || (context.task_id ? uiText("关联任务（名称未记录）", "Linked task (name unavailable)") : uiText("任务外提交", "Outside a task")));
  const runName = String(context.run_name || context.source_run_name || uiText("名称未记录", "Name unavailable"));
  const historical = context.task_lifecycle && context.task_lifecycle !== "active";
  const title = context.task_lifecycle === "superseded" ? uiText("已替代", "Superseded") : uiText("历史任务", "Historical task");
  return `<div class="shared-label-context"><dl class="shared-label-source-facts">
    <div><dt>${uiText("任务", "Task")}</dt><dd>${escapeHtml(taskName)}${historical ? ` · ${escapeHtml(title)}` : ""}</dd></div>
    <div><dt>${uiText("评测 Run", "Evaluation Run")}</dt><dd>${escapeHtml(runName)}</dd></div>
  </dl></div>`;
}

function sharedLabelStateSourceMarkup(source, issueId, context = {}) {
  const taskId = String(source?.task_id || "");
  const sourceRunId = String(source?.source_run_id || "");
  const combined = Array.isArray(context.combined_reviews) ? context.combined_reviews : [];
  const sourceTitle = combined.length ? uiText("联合复核标签", "Combined review label")
    : taskId ? uiText("任务标注", "Task label")
    : source?.source_type === "legacy_model_review" ? uiText("历史复核标签", "Historical review label")
    : uiText("Issue 标注", "Issue label");
  const contextsMarkup = combined.length
    ? combined.map((item) => sharedLabelSourceContextMarkup(item, issueId)).join("")
    : taskId || sourceRunId ? sharedLabelSourceContextMarkup({ task_id: taskId, source_run_id: sourceRunId, ...context }, issueId) : "";
  const revisionSummaries = Array.isArray(source?.revision_summaries)
    ? source.revision_summaries
    : [];
  const revisionsMarkup = revisionSummaries.length
    ? `<ul class="shared-label-revision-list shared-label-revision-details">${revisionSummaries.map((revision) => sharedLabelRevisionMarkup(revision, source, context.revision_attachments?.[String(revision.id)] || [])).join("")}</ul>`
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
    editLink = `<a class="button button-quiet shared-label-edit-link" data-labeling-edit-link href="${escapeHtml(href)}"><span class="ui-lang-zh">打开 Issue 标注</span><span class="ui-lang-en">Open Issue labeling</span></a>`;
  }
  return `<article class="shared-label-source">
    <div class="shared-label-source-heading">
      <strong>${escapeHtml(sourceTitle)}</strong>
      <span class="shared-label-source-state">${escapeHtml(sharedLabelStateStateText(source?.state))} · ${escapeHtml(sharedLabelStateMethodText(source?.method))}</span>
    </div>
    <dl class="shared-label-source-facts">
      <div><dt>${uiText("提交来源", "Submission source")}</dt><dd>${escapeHtml(combined.length ? uiText("问题标签与模型复核一起提交", "Issue label submitted with model review") : taskId ? uiText("问题标注任务", "Issue labeling task") : uiText("Issue 级标注，独立保存", "Issue-level label, saved independently"))}</dd></div>
      <div><dt><span class="ui-lang-zh">结果</span><span class="ui-lang-en">Result</span></dt><dd>${escapeHtml(String(source?.expected_output || "—"))}</dd></div>
      ${source?.source_type === "legacy_model_review" ? `<div><dt><span class="ui-lang-zh">来源</span><span class="ui-lang-en">Source</span></dt><dd>${escapeHtml(String(source?.import_batch_name || "历史判错复核"))}</dd></div><div><dt><span class="ui-lang-zh">冻结 GT</span><span class="ui-lang-en">Frozen GT</span></dt><dd>${escapeHtml(String(source?.frozen_gt_label || "—"))}</dd></div>` : ""}
    </dl>
    ${contextsMarkup}
    <details class="shared-label-source-audit"><summary>${uiText("记录详情", "Record details")}</summary><dl class="shared-label-source-facts">
      <div><dt>${uiText("标签记录 ID", "Label record ID")}</dt><dd><code>${escapeHtml(String(source?.label_case_id || "—"))}</code></dd></div>
      <div><dt>${uiText("标注任务 ID", "Labeling task ID")}</dt><dd><code>${escapeHtml(taskId || "—")}</code></dd></div>
      <div><dt>${uiText("选样 Run ID", "Selection Run ID")}</dt><dd><code>${escapeHtml(sourceRunId || "—")}</code></dd></div>
      ${combined.map((item) => `<div><dt>${uiText("联合提交", "Combined submission")} · #${escapeHtml(String(item.revision_id))}</dt><dd><code>${escapeHtml(item.submission_id)}</code><br>${escapeHtml(item.task_id || uiText("任务外", "Outside task"))}<br>${escapeHtml(item.run_id)}</dd></div>`).join("")}
    </dl></details>
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
  const sourceContexts = item.label_source_contexts || {};
  const taskIds = [...new Set([
    ...(Array.isArray(labelState.source_task_ids) ? labelState.source_task_ids : []),
    ...Object.values(sourceContexts).flatMap((context) => (context.combined_reviews || []).map((review) => review.task_id)).filter(Boolean),
  ])];
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
    ? sourceItems.map((source) => sharedLabelStateSourceMarkup(source, issueId, sourceContexts[source.label_case_id] || {})).join("")
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
  const sourceSequence = String(Number(dialog.dataset.sourceSequence || 0) + 1);
  dialog.dataset.sourceSequence = sourceSequence;
  if (!Object.prototype.hasOwnProperty.call(item, "label_source_contexts") && typeof api === "function") {
    const pageContext = capturePageContext();
    const loading = document.createElement("p");
    loading.className = "shared-label-source-empty";
    loading.textContent = uiText("正在加载任务来源…", "Loading task sources…");
    body.prepend(loading);
    api(`/api/cases/${encodeURIComponent(issueId)}?include_media=false`).then((detail) => {
      if (!dialog.open || dialog.dataset.sourceSequence !== sourceSequence || !isPageContextCurrent(pageContext)) return;
      openSharedLabelStateDialog({ ...item, label_source_contexts: detail.label_source_contexts || {} });
    }).catch(() => {
      if (!dialog.open || dialog.dataset.sourceSequence !== sourceSequence || !isPageContextCurrent(pageContext)) return;
      loading.textContent = uiText("任务来源暂时无法加载，请关闭后重试。", "Task sources are unavailable. Close and reopen to retry.");
    });
  }
}

function bindSharedLabelStateTriggers(root, getItem) {
  root?.querySelectorAll("[data-open-shared-label-state]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const item = getItem?.(button.dataset.issueId);
      if (item && state.activePage === "review" && state.selectedId === item.issue_id && hasDashboardWriteRole()) {
        void openReviewIssueDecision(item, button);
      } else if (item) openSharedLabelStateDialog(item);
    });
  });
}

function currentRunReviewStatusMarkup(item, { compact = false } = {}) {
  const annotation = item?.annotation || null;
  const annotationRunId = String(annotation?.model_run_id || "").trim();
  const belongsToSelectedRun = state.selectedRunId
    ? Boolean(annotation?.id && annotationRunId === state.selectedRunId)
    : Boolean(annotation?.id);
  const status = !belongsToSelectedRun ? "pending"
    : annotation.model_review_status === "completed" || (!annotation.model_review_status && annotation.note)
      ? "completed" : "in_progress";
  const labels = {
    pending: { zh: "待开始", en: "Not started" },
    in_progress: { zh: "待复核", en: "Needs review" },
    completed: { zh: "已完成", en: "Completed" },
  };
  const label = labels[status];
  const title = state.selectedRunId
    ? uiText("当前 Run 的判错复核进度", "Model error review progress for the selected Run")
    : uiText("当前 Review 范围的判错复核进度", "Model error review progress in the current scope");
  const prefixMarkup = compact
    ? ""
    : `<span class="issue-card-run-review-prefix"><span class="ui-lang-zh">判错复核</span><span class="ui-lang-en">Model review</span></span>`;
  return `<span class="issue-card-run-review-state" title="${escapeHtml(title)}">${prefixMarkup}<span class="issue-card-run-review-value"><span class="ui-lang-zh">${label.zh}</span><span class="ui-lang-en">${label.en}</span></span></span>`;
}
