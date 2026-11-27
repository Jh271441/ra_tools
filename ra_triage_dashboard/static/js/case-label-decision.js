/* Complete Issue decisions reuse the main labeling form; personal drafts stay separate. */
const caseLabelDecisionUi = {context:null, drafts:new Map(), saving:false, editor:null};
function caseDecisionCurrentIssueId() {
  return state.activePage === "review" ? state.selectedId : state.caseLabeling.issueId;
}
function caseLabelHasIssueDecision(data) { return Boolean(data?.label_state?.sources?.length || data?.label_state?.decision || data?.label_cases?.length); }
function caseDecisionSourceName(data, source, index = 0) {
  const context = data.label_source_contexts?.[source.label_case_id || source.id] || {};
  const linked = (context.combined_reviews || []).map(item => item.task_name).filter(Boolean);
  return linked.length ? [...new Set(linked)].join(" · ") : source.task_name || context.task_name
    || (source.task_id ? uiText(`标注任务 ${index + 1}`, `Labeling task ${index + 1}`) : uiText("Issue 标注", "Issue label"));
}
function caseDecisionStateText(value) {
  return ({resolved:uiText("已确认", "Confirmed"), conflict:uiText("有分歧", "Disagreement"), stale:uiText("待复核", "Needs recheck"), pending:uiText("待补齐", "Incomplete"), none:uiText("待补齐", "Incomplete")})[value] || uiText("待补齐", "Incomplete");
}
function caseDecisionImageMarkup(images) {
  return (images || []).map(a => `<a class="case-decision-image" href="${escapeHtml(a.url || withBase(`/api/labeling/attachments/${encodeURIComponent(a.id)}`))}" target="_blank" rel="noopener"><img loading="lazy" src="${escapeHtml(a.url || withBase(`/api/labeling/attachments/${encodeURIComponent(a.id)}`))}" alt="${escapeHtml(uiText("标注截图", "Label evidence"))}" /></a>`).join("");
}
function caseDecisionRecordMarkup(vote, sourceName, kind = "", adopt = false) {
  const full = vote.full_result;
  const rationale = (full ? vote.label_rationale : vote.rationale) || "";
  const badges = `${vote.expected_output ? labelBadge(vote.expected_output, "—", expectedOutputDisplayText(vote.expected_output)) : `<span class="tag">${uiText("待补齐分类", "Classification missing")}</span>`}<span class="tag ${vote.is_excluded === true ? "exclusion-tag" : ""}">${escapeHtml(caseExclusionText(vote.is_excluded))}</span>`;
  const sourceMeta = [sourceName, `${uiText("版本", "Revision")} ${vote.id}`, kind].filter(Boolean).map(escapeHtml).join(" · ");
  const meta = `<span>${sourceMeta}</span>${vote.tags?.length ? `<span class="tags">${vote.tags.map(tag => `<span class="tag">${escapeHtml(tagLabel(tag))}</span>`).join("")}</span>` : ""}`;
  const body = `${rationale ? `<p>${escapeHtml(rationale)}</p>` : ""}
    ${full ? `${vote.rationale ? `<p><strong>${uiText("裁决人补充依据", "Decision review rationale")}</strong> ${escapeHtml(vote.rationale)}</p>` : ""}${full.adopted_revision ? `<small class="history-record-meta">${escapeHtml(uiText(`采纳 ${full.adopted_revision.author} 的版本 ${full.adopted_revision_id}`, `Adopted ${full.adopted_revision.author}'s revision ${full.adopted_revision_id}`))}</small>` : ""}` : ""}
    ${vote.attachments?.length ? `<div class="case-decision-images">${caseDecisionImageMarkup(vote.attachments)}</div>` : ""}`;
  const actions = adopt && hasDashboardWriteRole() ? `<button type="button" class="history-inline-button history-adopt-button" data-adopt-decision="${Number(vote.id)}">${uiText("采用此标注", "Use this label")}</button>` : "";
  return historyRecordMarkup({author:vote.author || vote.created_by || uiText("未记录作者", "Unknown author"),createdAt:vote.created_at,badges,meta,body,actions});
}

function caseDecisionSourceBasis(data, source, index) {
  const revisions = source.revision_summaries || [];
  const effective = source.state === "resolved" && source.method === "adjudication"
    ? revisions.filter(r => r.id === source.result_revision_id) : revisions;
  const progress = source.task_id && source.assigned_count > 0
    ? uiText(`${source.submitted_count}/${source.assigned_count} 人已提交`, `${source.submitted_count}/${source.assigned_count} reviewers submitted`) : "";
  const outcome = source.state === "resolved" && source.expected_output
    ? expectedOutputDisplayText(source.expected_output) : caseDecisionStateText(source.state);
  return `<li><div class="case-decision-basis-source-head"><strong>${escapeHtml(caseDecisionSourceName(data, source, index))}</strong><span>${escapeHtml([outcome, progress].filter(Boolean).join(" · "))}</span></div>
    ${effective.map(r => {
      const label = r.expected_output ? expectedOutputDisplayText(r.expected_output) : uiText("缺少分类", "Classification missing");
      const note = r.rationale || uiText("未填写标注说明", "No rationale recorded");
      return `<p>${escapeHtml([r.author, `#${r.id}`, label].filter(Boolean).join(" · "))} — ${escapeHtml(note)}</p>`;
    }).join("")}</li>`;
}

function caseDecisionValueTone(raw) {
  if (raw === "正确触发" || raw === "included") return "ok";
  if (raw === "误触发" || raw === "conflict") return "fail";
  if (raw === "无需协助" || raw === "stale" || raw === "excluded") return "warn";
  if (raw === "真实卡住" || raw === "decision") return "accent";
  return "muted";
}

function caseDecisionBridgeIcon(icon) {
  if (icon === "check") return '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.4 6.2 4.9 8.7 9.6 3.5"/></svg>';
  if (icon === "alert" || icon === "split") return '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M6 2.6v4M6 9.1v.3"/></svg>';
  return '<svg viewBox="0 0 12 12" aria-hidden="true"><circle cx="3" cy="6" r=".95" fill="currentColor" stroke="none"/><circle cx="6" cy="6" r=".95" fill="currentColor" stroke="none"/><circle cx="9" cy="6" r=".95" fill="currentColor" stroke="none"/></svg>';
}

function caseDecisionBranch(inputs, { caption, outcome, note = "", kind = "", tone = "accent", badge = "", icon = "pending" }) {
  const multi = inputs.length > 1;
  const wireH = multi
    ? '<path d="M0 25C18 25 20 50 32 50"/><path d="M0 75C18 75 20 50 32 50"/><path d="M32 50H58"/>'
    : '<path d="M0 50H58"/>';
  const wireV = multi
    ? '<path d="M25 0C25 13 48 11 50 17"/><path d="M75 0C75 13 52 11 50 17"/><path d="M50 17V37"/>'
    : '<path d="M50 0V37"/>';
  const itemsMarkup = inputs.map(item => {
    const nodeTone = item.tone || "muted";
    const bar = typeof item.ratio === "number"
      ? `<span class="case-decision-vote-track" aria-hidden="true"><i style="width:${item.ratio}%"></i></span>` : "";
    return `<li data-node-tone="${nodeTone}"><div class="case-decision-node"><span class="case-decision-node-label"><i class="case-decision-dot" aria-hidden="true"></i><span>${escapeHtml(item.name)}</span></span>${bar}<b class="case-decision-pill" data-tone="${nodeTone}">${escapeHtml(item.value)}</b></div></li>`;
  }).join("");
  return `<div class="case-decision-branch ${kind}" data-flow-tone="${tone}" data-input-count="${inputs.length}">
    <ul class="case-decision-inputs">${itemsMarkup}</ul>
    <div class="case-decision-bridge" aria-hidden="true">
      <svg class="case-decision-wire case-decision-wire-h" viewBox="0 0 64 100" preserveAspectRatio="none">${wireH}</svg>
      <svg class="case-decision-arrow case-decision-arrow-h" viewBox="0 0 8 10"><path d="M1.5 1.5 6 5 1.5 8.5"/></svg>
      <svg class="case-decision-wire case-decision-wire-v" viewBox="0 0 100 42" preserveAspectRatio="none">${wireV}</svg>
      <svg class="case-decision-arrow case-decision-arrow-v" viewBox="0 0 10 8"><path d="M1.5 1.5 5 6 8.5 1.5"/></svg>
      <span class="case-decision-junction">${caseDecisionBridgeIcon(icon)}</span>
    </div>
    <div class="case-decision-conclusion">
      <div class="case-decision-conclusion-head"><span>${escapeHtml(caption)}</span>${badge ? `<em class="case-decision-state-chip">${escapeHtml(badge)}</em>` : ""}</div>
      <h3>${escapeHtml(outcome)}</h3>
      ${note ? `<small class="case-decision-note">${escapeHtml(note)}</small>` : ""}
    </div>
  </div>`;
}

function caseDecisionFlowMarkup(data) {
  const explanation = caseLabelExplanation(data), result = data.label_state || {};
  const {status, sources, output} = explanation;
  const decision = result.decision, human = result.human_publication;
  const pendingRoles = ["rd", "te"].filter(role => human?.lanes?.[role]?.state === "pending");
  const waitingForRole = !sources.length && pendingRoles.length > 0;
  const headline = output ? expectedOutputDisplayText(output) : ({
    conflict: uiText("分类有分歧，待裁决", "Classification disputed · decision needed"),
    stale: uiText("分类结论待复核", "Classification needs rechecking"),
    pending: uiText("分类待补齐", "Classification incomplete"),
  })[status] || (waitingForRole ? uiText("等待人工标注", "Awaiting human labels") : uiText("尚无分类结论", "No classification yet"));
  const excluded = data.exclusion_summary?.is_excluded;
  const votes = caseExclusionVotes(data);
  const exclusionConflict = caseExclusionNeedsDecision(data);
  const labelInputs = [];
  if (human?.lanes) {
    for (const [role, name] of [["rd", "RD"], ["te", "TE′"]]) {
      const lane = human.lanes[role];
      if (!lane) continue;
      labelInputs.push({
        name,
        value: lane.label ? rdLabel(lane.label) : humanStatus(lane.state),
        tone: lane.label ? caseDecisionValueTone(lane.label) : caseDecisionValueTone(lane.state),
      });
    }
  } else if (sources.length && sources.length <= 2) {
    sources.forEach((source, i) => labelInputs.push({
      name: caseDecisionSourceName(data, source, i),
      value: source.expected_output ? expectedOutputDisplayText(source.expected_output) : caseDecisionStateText(source.state),
      tone: caseDecisionValueTone(source.expected_output || source.state),
    }));
  } else {
    labelInputs.push({
      name: uiText("标注来源", "Label sources"),
      value: String(sources.length),
      tone: sources.length ? "accent" : "muted",
    });
  }
  const decisionRef = decision ? uiText(`裁决 #${decision.id}`, `Decision #${decision.id}`) : "";
  const labelTone = output ? caseDecisionValueTone(output) : status === "conflict" ? "fail" : status === "stale" ? "warn" : "muted";
  const labelBadge = decision && !decision.stale ? uiText("已裁决", "Decided")
    : output ? uiText("已确认", "Confirmed")
    : status === "conflict" ? uiText("需裁决", "Needs decision")
    : status === "stale" ? uiText("待复核", "Recheck")
    : uiText("待提交", "Waiting");
  const labelIcon = output ? "check" : (status === "conflict" || status === "stale") ? "alert" : "pending";
  const labelFlow = caseDecisionBranch(labelInputs, {
    caption: uiText("分类结论", "Classification"),
    outcome: headline,
    note: decision && !decision.stale ? decisionRef : "",
    kind: "classification-flow",
    tone: labelTone,
    badge: labelBadge,
    icon: labelIcon,
  });
  const exclusionInputs = [];
  if (decision?.full_result && !decision.stale) {
    exclusionInputs.push({ name: uiText("裁决", "Decision"), value: `#${decision.id}`, tone: "accent" });
  } else {
    const totalVotes = votes.filter(v => typeof v.is_excluded === "boolean").length;
    for (const [value, name, voteTone] of [[true, uiText("排除", "Exclude"), "warn"], [false, uiText("不排除", "Include"), "ok"]]) {
      const count = votes.filter(v => v.is_excluded === value).length;
      if (count) {
        exclusionInputs.push({
          name,
          value: uiText(`${count} 票`, `${count} ${count === 1 ? "vote" : "votes"}`),
          tone: voteTone,
          ratio: totalVotes ? Math.round((count / totalVotes) * 100) : 0,
        });
      }
    }
  }
  const exclusionTone = exclusionConflict ? "warn" : excluded === true ? "warn" : excluded === false ? "ok" : "muted";
  const exclusionBadge = decision?.full_result && !decision.stale ? uiText("已裁决", "Decided")
    : exclusionConflict ? uiText("意见相反", "Split")
    : typeof excluded === "boolean" ? uiText("已一致", "Agreed") : "";
  const exclusionFlow = exclusionInputs.length
    ? caseDecisionBranch(exclusionInputs, {
        caption: uiText("排除意见", "Exclusion"),
        outcome: exclusionConflict ? uiText("排除待确定", "Exclusion pending") : caseExclusionText(excluded),
        note: exclusionConflict ? uiText("当前暂按排除", "Provisionally excluded") : "",
        kind: "case-decision-exclusion",
        tone: exclusionTone,
        badge: exclusionBadge,
        icon: exclusionConflict ? "split" : "check",
      })
    : `<div class="case-decision-exclusion-empty"><span class="case-decision-empty-dot" aria-hidden="true"></span><span class="case-decision-empty-caption">${uiText("排除意见", "Exclusion")}</span><p class="quiet-meta">${uiText("暂无排除意见", "No exclusion opinion recorded")}</p></div>`;
  let reason = explanation.reason;
  if (!sources.length && status === "none") {
    const roles = pendingRoles.map(role => role === "rd" ? "RD" : "TE′");
    reason = waitingForRole
      ? uiText(`${roles.join("、")} 尚待提交有效标注，当前没有可用于判定分类的人工记录。`,
        `Awaiting valid labels from ${roles.join(" and ")}. No Case labels are available to establish a classification.`)
      : uiText("尚无 Case 标注记录。", "No Case labels have been recorded.");
  }
  const decisionNote = decision?.rationale || decision?.label_rationale;
  return `<section class="case-decision-result">
    ${labelFlow}
    ${exclusionFlow}
    <details class="case-decision-basis"><summary id="caseDecisionBasisToggle"><span class="case-decision-basis-title"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.2h10M3 8h10M3 11.8h6.5"/></svg>${uiText("判定依据", "Decision basis")}</span><span class="case-decision-basis-chevron" aria-hidden="true"></span></summary>
      <div class="case-decision-basis-body">
        ${humanRoleSummary(human, {showProgress:true})}
        <p class="case-decision-basis-reason">${escapeHtml(reason)}</p>
        ${decision ? `<p class="case-decision-basis-decision">${escapeHtml([uiText(`裁决 #${decision.id}`, `Decision #${decision.id}`), decision.created_by, formatTime(decision.created_at), decisionNote || uiText("未填写裁决说明", "No decision rationale recorded")].filter(Boolean).join(" · "))}</p>` : ""}
        ${sources.length ? `<ul class="case-decision-basis-sources">${sources.map((source, i) => caseDecisionSourceBasis(data, source, i)).join("")}</ul>` : ""}
        ${status === "pending" && !exclusionConflict ? `<p class="quiet-meta">${uiText("可直接关闭，待标注人补齐分类。", "You can close this dialog while the reviewers complete their labels.")}</p>` : ""}
        <p class="quiet-meta case-decision-trail-row"><span>${uiText("Trail 排除状态", "Trail exclusion status")}</span><span class="case-decision-trail-value" data-decision-trail>${escapeHtml(caseExclusionTrailText(data))}</span></p>
      </div>
    </details>
  </section>`;
}
function caseDecisionRevisions(data) {
  const heads = new Set((data.label_state?.sources || []).flatMap(s => s.source_revision_ids || []));
  const rows = (data.label_cases || []).flatMap((c,i) => (c.revisions || c.resolution?.heads || []).map(r => ({...r, sourceName:caseDecisionSourceName(data,c,i), historical:!heads.has(r.id)})));
  return [...new Map(rows.map(r => [r.id,r])).values()].sort((a,b) => b.id-a.id);
}
function caseLabelDecisionMarkup(data) {
  const rows = caseDecisionRevisions(data), current = rows.filter(r => !r.historical), old = rows.filter(r => r.historical);
  const history = data.decision_history || [];
  return `${caseDecisionFlowMarkup(data)}<h3 class="case-decision-section-title">${uiText("当前标注", "Current labels")}</h3><div class="case-decision-records history-dialog-content">${current.map(r => caseDecisionRecordMarkup(r,r.sourceName,"",true)).join("") || `<p>${uiText("暂无标注", "No labels yet.")}</p>`}</div>${old.length ? `<details class="case-decision-history"><summary>${uiText("历史标注", "Earlier labels")} · ${old.length}</summary><div class="case-decision-records history-dialog-content">${old.map(r => caseDecisionRecordMarkup(r,r.sourceName,uiText("旧版本", "Earlier revision"),true)).join("")}</div></details>` : ""}${history.length ? `<details class="case-decision-history"><summary>${uiText("裁决记录", "Decision history")} · ${history.length}</summary><div class="case-decision-records history-dialog-content">${history.map(r => caseDecisionRecordMarkup(r,uiText("Issue 裁决", "Issue decision"))).join("")}</div></details>` : ""}`;
}
function renderCaseLabelDecisionDialog() {
  const c = caseLabelDecisionUi.context, dialog = $("#caseLabelDecisionDialog");
  if (!c || !dialog) return;
  const focusId = dialog.contains?.(document.activeElement) ? document.activeElement?.id : "";
  const restoreFocusId = focusId || ([document.body, dialog].includes(document.activeElement) ? c.pendingFocusId : "");
  const loading = c.sourcesStatus === "loading", failed = c.sourcesStatus === "error";
  const ready = !loading && !failed;
  const error = c.sourceError?.messages ? uiText(c.sourceError.messages.zh, c.sourceError.messages.en)
    : c.sourceError ? caseExclusionErrorMessage(c.sourceError) : "";
  const body = loading
    ? `<p class="comment-thread-empty" role="status" aria-live="polite">${uiText("正在加载标注来源…", "Loading label sources…")}</p>`
    : failed ? `<div class="case-label-decision-error" role="alert"><p>${uiText("标注来源加载失败，请重试。", "Could not load label sources. Try again.")}</p><small>${escapeHtml(error)}</small></div>`
    : caseLabelDecisionMarkup(c.caseData);
  const decisionNeeded = ["conflict", "stale"].includes(c.caseData.label_state?.state);
  const actionLabel = decisionNeeded ? uiText("重新标注并裁决", "Relabel and decide")
    : ready && caseExclusionNeedsDecision(c.caseData) ? uiText("核对排除意见", "Review exclusion")
    : uiText("裁决（可选）", "Optional decision");
  dialog.innerHTML = `<div class="dialog-card"><div class="dialog-heading"><div><h2 id="caseLabelDecisionTitle">${uiText("标注与裁决", "Labels and decisions")}</h2><small>${escapeHtml(c.caseData.issue_id)}</small></div><button type="button" class="icon-button" id="caseDecisionCloseIcon" data-close-decision aria-label="${uiText("关闭", "Close")}">×</button></div><div class="case-label-decision-body" id="caseDecisionEvidence" aria-busy="${loading}">${body}</div><div class="dialog-actions"><button type="button" class="button button-quiet" id="caseDecisionRefresh" ${loading ? "disabled" : ""}>${failed ? uiText("重试加载", "Retry loading") : uiText("刷新来源", "Refresh sources")}</button><button type="button" class="button ${decisionNeeded ? "button-primary" : "button-quiet"}" id="caseDecisionRelabel" ${!ready || !hasDashboardWriteRole() || !caseDecisionRevisions(c.caseData).length ? "disabled" : ""}>${actionLabel}</button><button type="button" class="button ${decisionNeeded ? "button-quiet" : "button-primary"}" id="caseDecisionClose" data-close-decision>${uiText("关闭", "Close")}</button></div></div>`;
  const basis = dialog.querySelector(".case-decision-basis");
  if (basis) {
    basis.open = Boolean(c.basisOpen);
    basis.addEventListener("toggle", () => { if (basis.isConnected) c.basisOpen = basis.open; });
  }
  dialog.querySelectorAll("[data-close-decision]").forEach(b => b.addEventListener("click", () => dialog.close()));
  dialog.querySelectorAll("[data-adopt-decision]").forEach(b => b.addEventListener("click", () => startCaseDecisionEditor(c.caseData, Number(b.dataset.adoptDecision))));
  $("#caseDecisionRelabel").addEventListener("click", () => startCaseDecisionEditor(c.caseData));
  $("#caseDecisionRefresh").addEventListener("click", () => void refreshUnifiedCaseDecisionSources());
  if (ready && c.compareEditor && c.compareEditor === caseLabelDecisionUi.editor) {
    const button = document.createElement("button");
    button.type = "button"; button.className = "button button-primary";
    button.textContent = uiText("已对照，保留草稿继续裁决", "Reviewed; continue with my draft");
    button.addEventListener("click", () => {
      const editor = c.compareEditor;
      if (caseLabelDecisionUi.saving || editor !== caseLabelDecisionUi.editor || !isPageContextCurrent(editor.pageContext)
          || selectedBaselineQueryValue() !== editor.baselines || (editor.actor && editor.actor !== state.session?.username)) return;
      editor.data = structuredClone(c.caseData);
      editor.sourceConflict = null;
      editor.excludedConfirmed = false;
      const confirmBox = $("#caseDecisionConfirmExclusion");
      if (confirmBox) confirmBox.checked = false;
      rememberCaseLabelDecisionDraft({ forceNewIdempotencyKey: true });
      if (typeof refreshCaseLabelingDraftBanner === "function") {
        refreshCaseLabelingDraftBanner(editor.data, { decision: editor });
      }
      dialog.close();
    });
    dialog.querySelector(".dialog-actions").appendChild(button);
  }
  // A completed read or locale change must retain the focused dialog action.
  if (restoreFocusId) {
    const action = $(`#${restoreFocusId}`);
    c.pendingFocusId = action?.disabled ? restoreFocusId : "";
    if (action && !action.disabled) action.focus({preventScroll:true});
  }
}
function openCaseLabelDecision(data, {compareEditor = null, loading = false, opener = document.activeElement} = {}) {
  if (caseLabelDecisionUi.saving) return;
  let dialog = $("#caseLabelDecisionDialog");
  if (!dialog) {
    dialog = document.createElement("dialog"); dialog.id = "caseLabelDecisionDialog";
    dialog.className = "dialog case-label-decision-dialog history-dialog"; dialog.setAttribute("aria-labelledby","caseLabelDecisionTitle");
    dialog.addEventListener("click", e => {if(e.target === dialog) dialog.close();});
    dialog.addEventListener("close", () => {
      if (dialog.open) return;
      const c = caseLabelDecisionUi.context;
      c?.sourceRequest?.abort();
      c?.suspendedVideos?.forEach(video => {
        if (video.isConnected && !video.closest("[hidden]")) video._resumeBevPlayback?.();
      });
      if (c) c.suspendedVideos = [];
      if (!caseLabelDecisionUi.editor) c?.opener?.focus({preventScroll:true});
    }); document.body.appendChild(dialog);
  }
  const previous = caseLabelDecisionUi.context;
  previous?.sourceRequest?.abort();
  const suspendedVideos = dialog.open ? previous?.suspendedVideos || []
    : [...(document.querySelectorAll?.("video") || [])].filter(video => video._pauseBevPlayback && !video.closest("[hidden]"));
  if (!dialog.open) suspendedVideos.forEach(video => video._pauseBevPlayback());
  caseLabelDecisionUi.context = {caseData:structuredClone(data),baselines:selectedBaselineQueryValue(),pageContext:capturePageContext(),actor:state.session?.username || "",mode:"issue",compareEditor,opener,suspendedVideos,sourcesStatus:loading ? "loading" : "ready"};
  renderCaseLabelDecisionDialog();
  if (!dialog.open) dialog.showModal();
}
function bindCaseLabelResultActions(data) {
  $("#caseDecisionInfo")?.addEventListener("click", showCaseDecisionInfo);
  $("#caseLabelGoAdjudication")?.addEventListener("click", () => openCaseLabelDecision(data));
}
function caseDecisionDraftKey(data) {
  return JSON.stringify([data.issue_id,selectedBaselineQueryValue(),state.activePage, state.activePage === "review" ? [state.selectedRunId || "",state.reviewWorkSplitId || ""] : state.caseLabeling.taskId || "",(state.session?.username || "")]);
}
function startCaseDecisionEditor(data, revisionId = null) {
  if (!hasDashboardWriteRole() || caseLabelDecisionUi.saving || data.issue_id !== caseDecisionCurrentIssueId()) return;
  const context = caseLabelDecisionUi.context;
  if (context && ((context.sourcesStatus && context.sourcesStatus !== "ready")
      || !isPageContextCurrent(context.pageContext) || context.baselines !== selectedBaselineQueryValue()
      || context.actor !== (state.session?.username || ""))) return;
  if (caseLabelDecisionUi.editor) exitCaseDecisionEditor();
  const adopted = revisionId == null ? null : caseDecisionRevisions(data).find(r => r.id === revisionId);
  if (revisionId != null && !adopted) return;
  const key = caseDecisionDraftKey(data), saved = caseLabelDecisionUi.drafts.get(key);
  const storedDraft = !saved && typeof readCaseLabelDraft === "function"
    ? readCaseLabelDraft(data.issue_id, "", "decision")
    : null;
  const reuse = saved && saved.adoptedId === revisionId;
  const reuseStored = !reuse && storedDraft && storedDraft.adopted_revision_id === revisionId;
  const source = reuse
    ? saved.source
    : reuseStored
      ? {
          expected_output: storedDraft.expected_output,
          tags: storedDraft.tags,
          evidence_gaps: storedDraft.evidence_gaps,
          rationale: storedDraft.rationale,
          is_excluded: storedDraft.is_excluded,
        }
      : adopted || {expected_output:"",tags:[],rationale:"",is_excluded:false};
  const reviewHost = state.activePage === "review" ? mountReviewDecisionEditor(data) : null;
  const node = $("#caseLabelingForm"), ordinary = {node,images:state.caseLabeling.pendingImages,dirty:state.caseLabeling.dirty,focus:document.activeElement?.id};
  closeAllReviewDropdowns();
  node?.remove();
  const storedSourceCheck = reuseStored && typeof caseLabelDecisionSourceChanged === "function"
    ? caseLabelDecisionSourceChanged(storedDraft, data)
    : { changed: false };
  const storedMissingAttachments = reuseStored && typeof caseLabelMissingAttachments === "function"
    ? caseLabelMissingAttachments(storedDraft.pending_attachments || [], [])
    : [];
  const sourceConflict = storedSourceCheck.changed
    ? { ...storedSourceCheck, acknowledged: false }
    : (reuse && saved.sourceConflict ? structuredClone(saved.sourceConflict) : null);
  const c = {key,data:structuredClone(reuse ? saved.data : data),adoptedId:revisionId,adopted,source,ordinary,reviewHost,
    images:reuse ? saved.images : [],retained:reuse ? saved.retained : reuseStored ? storedDraft.retained_attachment_ids : (adopted?.attachments || []).map(a=>a.id),
    rationale:reuse ? saved.rationale : reuseStored ? storedDraft.decision_rationale : "",confirmed:false,
    excludedConfirmed: sourceConflict && !sourceConflict.acknowledged
      ? false
      : (reuse ? saved.excludedConfirmed : reuseStored ? storedDraft.excluded_confirmed : false),
    sourceConflict,
    missingAttachments: reuse ? (saved.missingAttachments || []) : storedMissingAttachments,
    restoredFromStorage: Boolean(reuseStored),
    pageContext:capturePageContext(),baselines:selectedBaselineQueryValue(),actor:state.session?.username || "",error:""};
  caseLabelDecisionUi.editor = c; state.caseLabeling.pendingImages = c.images; state.caseLabeling.dirty = true;
  $("#caseLabelDecisionDialog")?.close(); renderCaseLabelingEditor(data,{decision:c});
  $("#caseDecisionMode")?.focus();
}
function rememberCaseLabelDecisionDraft({ forceNewIdempotencyKey = false } = {}) {
  const c = caseLabelDecisionUi.editor;
  if (!c || !$("#caseLabelingForm")) return;
  c.source = caseLabelingFormPayload(); c.rationale = $("#caseDecisionReviewRationale")?.value || "";
  c.excludedConfirmed = Boolean($("#caseDecisionConfirmExclusion")?.checked);
  c.images = state.caseLabeling.pendingImages;
  caseLabelDecisionUi.drafts.set(c.key,{source:c.source,rationale:c.rationale,images:c.images,retained:c.retained,
    adoptedId:c.adoptedId,excludedConfirmed:c.excludedConfirmed,data:c.data,
    sourceConflict:c.sourceConflict,missingAttachments:c.missingAttachments});
  if (typeof writeCaseLabelDraft === "function") {
    const unresolvedConflict = Boolean(c.sourceConflict && !c.sourceConflict.acknowledged);
    const currentPending = typeof normalizeCaseLabelPendingAttachments === "function"
      ? normalizeCaseLabelPendingAttachments(c.images)
      : [];
    const missing = Array.isArray(c.missingAttachments) ? c.missingAttachments : [];
    const pendingAttachments = missing.length ? [...currentPending, ...missing] : currentPending;
    writeCaseLabelDraft(c.data.issue_id, "", "decision", {
      ...c.source,
      decision_rationale: c.rationale,
      excluded_confirmed: unresolvedConflict ? false : c.excludedConfirmed,
      adopted_revision_id: c.adoptedId,
      retained_attachment_ids: c.retained,
      pending_attachments: pendingAttachments,
    }, {
      expectedPreviousId: unresolvedConflict
        ? c.sourceConflict.expectedPreviousId
        : (c.data.label_state?.decision?.id || null),
      expectedSourceFingerprint: unresolvedConflict
        ? c.sourceConflict.expectedSourceFingerprint
        : (c.data.label_state?.source_fingerprint || ""),
      pendingAttachments,
      forceNewIdempotencyKey,
    });
  }
}
function exitCaseDecisionEditor({discard = false, clearStoredDraft = true} = {}) {
  const c = caseLabelDecisionUi.editor;
  if (!c || caseLabelDecisionUi.saving) return;
  if (discard) {
    c.images.forEach(i=>releasePreviewUrlLater(i.previewUrl));
    caseLabelDecisionUi.drafts.delete(c.key);
    if (clearStoredDraft && typeof clearCaseLabelDraft === "function") clearCaseLabelDraft(c.data.issue_id, "", "decision");
  }
  else rememberCaseLabelDecisionDraft();
  caseLabelDecisionUi.editor = null;
  state.caseLabeling.pendingImages = c.ordinary.images; state.caseLabeling.dirty = c.ordinary.dirty;
  if (c.reviewHost) { restoreReviewDecisionEditor(c.reviewHost); return; }
  $("#caseLabelingEditor")?.replaceChildren(c.ordinary.node);
  refreshCaseLabelDecisionLanguage();
  syncCaseLabelingExpectedOutputFromTags(); updateTagSummary();
  $("#caseLabelGoAdjudication")?.focus();
}
function caseDecisionEditorHeader(c) {
  const source = c.adopted
    ? uiText(`采纳 ${c.adopted.author} · 版本 ${c.adopted.id}${c.adopted.historical ? "（旧版本）" : ""}`, `Adopting ${c.adopted.author} · revision ${c.adopted.id}${c.adopted.historical ? " (earlier revision)" : ""}`)
    : uiText("重新标注，确认完整 Issue 结果", "Relabel and confirm the complete Issue result");
  return `<section class="case-decision-mode" id="caseDecisionMode" tabindex="-1"><div class="review-section-heading"><h2>${uiText("裁决模式", "Decision mode")}</h2><div class="review-heading-actions"><button type="button" class="history-inline-button" id="caseDecisionExit">${uiText("退出裁决", "Exit decision mode")}</button></div></div><p class="quiet-meta">${escapeHtml(source)}</p>${c.adopted?.rationale ? `<details><summary>${uiText("查看原作者依据", "View original rationale")}</summary><p>${escapeHtml(c.adopted.rationale)}</p></details>` : ""}</section>`;
}

function caseDecisionEditorFields(c) {
  return `${c.source.evidence_gaps?.length ? `<p>${uiText("证据缺口", "Evidence gaps")}: ${escapeHtml(c.source.evidence_gaps.map(evidenceLabel).join(" · "))}</p>` : ""}<label class="review-reason case-decision-rationale"><span class="review-reason-heading">${uiText("裁决人补充依据（选填）", "Decision review rationale (optional)")}</span><textarea id="caseDecisionReviewRationale" rows="2" maxlength="8000">${escapeHtml(c.rationale)}</textarea></label><label class="case-decision-confirm"><input type="checkbox" id="caseDecisionConfirmExclusion" ${c.excludedConfirmed ? "checked" : ""} aria-required="true" aria-describedby="caseDecisionConfirmError"/><span>${uiText("已确认上方“是否排除”的选择", "I confirm the exclusion choice above")}</span></label><p class="case-label-decision-error" id="caseDecisionConfirmError" role="alert"></p><div class="case-decision-images" id="caseDecisionRetainedImages">${(c.adopted?.attachments || []).filter(a=>c.retained.includes(a.id)).map(a=>`<div>${caseDecisionImageMarkup([a])}<button type="button" class="button button-quiet" data-remove-decision-image="${escapeHtml(a.id)}">${uiText("移除引用", "Remove reference")}</button></div>`).join("")}</div><div class="case-decision-preview" id="caseDecisionPreview" aria-live="polite"></div><p class="case-label-decision-error" id="caseDecisionEditorError" role="alert">${escapeHtml(c.error ? caseExclusionErrorMessage({message:c.error}) : "")}</p>`;
}
function bindCaseDecisionEditor(c) {
  $("#caseDecisionExit").addEventListener("click",()=>exitCaseDecisionEditor());
  $("#caseDecisionEditorRefresh").addEventListener("click",()=>void refreshDecisionEditorSources());
  document.querySelectorAll("[data-remove-decision-image]").forEach(b=>b.addEventListener("click",()=>{c.retained=c.retained.filter(id=>id!==b.dataset.removeDecisionImage);b.parentElement.remove();rememberCaseLabelDecisionDraft();updateCaseDecisionPreview();}));
  $("#caseLabelingExcluded").addEventListener("change",()=>{$("#caseDecisionConfirmExclusion").checked=false;});
  $("#caseLabelingForm").addEventListener("input",()=>{rememberCaseLabelDecisionDraft();updateCaseDecisionPreview();});
  $("#caseLabelingForm").addEventListener("change",()=>{rememberCaseLabelDecisionDraft();updateCaseDecisionPreview();});
  updateCaseDecisionPreview();
}
function updateCaseDecisionConfirmation() {
  const c=caseLabelDecisionUi.editor, checkbox=$("#caseDecisionConfirmExclusion"), error=$("#caseDecisionConfirmError");
  if(!c || !checkbox || !error)return;
  if(checkbox.checked)c.confirmationInvalid=false;
  checkbox.setAttribute("aria-invalid",String(Boolean(c.confirmationInvalid)));
  error.textContent=c.confirmationInvalid ? uiText("请确认上方“是否排除”的选择后再提交。","Confirm the exclusion choice above before submitting.") : "";
}
function updateCaseDecisionPreview() {
  updateCaseDecisionConfirmation();
  const c=caseLabelDecisionUi.editor, target=$("#caseDecisionPreview"); if(!c || !target)return;
  const p=caseLabelingFormPayload();
  const names={expected_output:uiText("分类","Classification"),tags:uiText("标签","Tags"),rationale:uiText("标注依据","Label rationale"),is_excluded:uiText("是否排除","Exclusion")};
  const changed=c.adopted ? Object.keys(names).filter(k=>JSON.stringify(p[k])!==JSON.stringify(c.adopted[k])).map(k=>names[k]) : [];
  target.textContent=uiText(`将确认：${expectedOutputDisplayText(p.expected_output) || "待补齐分类"} · ${caseExclusionText(p.is_excluded)}${changed.length ? `；已调整：${changed.join("、")}` : ""}`,`Confirm: ${expectedOutputDisplayText(p.expected_output) || "Classification missing"} · ${caseExclusionText(p.is_excluded)}${changed.length ? `; changed: ${changed.join(", ")}` : ""}`);
}
function refreshCaseLabelDecisionLanguage() {
  const sharedDialog = $("#sharedLabelStateDialog");
  if (sharedDialog?.open && sharedDialog._humanPublication) {
    const summary = sharedDialog.querySelector(".human-role-summary");
    if (summary) summary.outerHTML = humanRoleSummary(sharedDialog._humanPublication);
  }
  const reviewEntry = $("#reviewSharedLabelState [data-open-shared-label-state]");
  if (reviewEntry) {
    reviewEntry.setAttribute("aria-label", uiText("标注汇总与裁决", "Label summary and decisions"));
    reviewEntry.title = uiText("查看标注、分歧与裁决（L）", "View labels, disagreements and decisions (L)");
  }
  renderCaseLabelingStatusPicker();
  const data = state.caseLabeling.caseData, actions = $("#caseLabelResultActions");
  if(data && actions){actions.outerHTML=caseLabelFinalResultMarkup(data);bindCaseLabelResultActions(data);}
  if($("#caseLabelDecisionDialog")?.open){
    const body=$("#caseLabelDecisionDialog .case-label-decision-body");
    const scroll=body?.scrollTop || 0;
    const expanded=Array.from(body?.querySelectorAll("details") || [],item=>item.open);
    renderCaseLabelDecisionDialog();
    const next=$("#caseLabelDecisionDialog .case-label-decision-body");
    next?.querySelectorAll("details").forEach((item,index)=>{item.open=!!expanded[index];});
    if(next)next.scrollTop=scroll;
  }
  if(caseLabelDecisionUi.editor && !caseLabelDecisionUi.saving){
    const c=caseLabelDecisionUi.editor, focus=document.activeElement?.id, node=document.activeElement;
    const selection=node?.tagName === "TEXTAREA" ? [node.selectionStart,node.selectionEnd] : null;
    rememberCaseLabelDecisionDraft();renderCaseLabelingEditor(c.data,{decision:c});
    if(focus)document.getElementById(focus)?.focus({preventScroll:true});
    if(selection)document.getElementById(focus)?.setSelectionRange(...selection);
  }else if(data && state.caseLabeling.draftNotice && typeof refreshCaseLabelingDraftBanner === "function"){
    refreshCaseLabelingDraftBanner(data, { decision: null });
  }
}
async function refreshUnifiedCaseDecisionSources() {
  const c=caseLabelDecisionUi.context, dialog=$("#caseLabelDecisionDialog");
  if(!c || !dialog?.open)return;
  c.sourceRequest?.abort();
  const controller=new AbortController();
  c.sourceRequest=controller;c.sourcesStatus="loading";c.sourceError=null;
  renderCaseLabelDecisionDialog();
  const current=()=>{
    if(c!==caseLabelDecisionUi.context || c.sourceRequest!==controller || controller.signal.aborted || !dialog.open)return false;
    if(!isPageContextCurrent(c.pageContext) || caseDecisionCurrentIssueId()!==c.caseData.issue_id
        || c.baselines!==selectedBaselineQueryValue() || c.actor!==(state.session?.username || "")){
      dialog.close();return false;
    }
    return true;
  };
  try {
    const fresh=await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(c.caseData.issue_id)}`), {
      cache:"no-store",signal:controller.signal,
    });
    if(!current())return;
    if(fresh.issue_id!==c.caseData.issue_id)throw apiResponseError("返回的 Issue 不一致，请重试。","The returned Issue does not match. Retry loading.");
    // Trail facts arrive independently of the labeling detail.
    if (c.caseData.trail_metadata_status && !fresh.trail_metadata_status) {
      fresh.trail_metadata_status = c.caseData.trail_metadata_status;
      fresh.dashboard_should_exclude = c.caseData.dashboard_should_exclude;
    }
    c.caseData=fresh;c.sourcesStatus="ready";renderCaseLabelDecisionDialog();
  }catch(e){
    if(!current())return;
    c.sourcesStatus="error";c.sourceError=e;renderCaseLabelDecisionDialog();
  }finally{if(c.sourceRequest===controller)c.sourceRequest=null;}
}
async function refreshDecisionEditorSources() {
  const c=caseLabelDecisionUi.editor;if(!c || caseLabelDecisionUi.saving)return;
  try{
    const fresh=await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(c.data.issue_id)}`));
    if(c!==caseLabelDecisionUi.editor || !isPageContextCurrent(c.pageContext)
      || c.baselines!==selectedBaselineQueryValue() || c.actor!==(state.session?.username || ""))return;
    // The new fingerprint becomes eligible only after explicit review in the dialog.
    openCaseLabelDecision(fresh, {compareEditor:c});
  }catch(e){if(c===caseLabelDecisionUi.editor){c.error=e.message;$("#caseDecisionEditorError").textContent=caseExclusionErrorMessage(e);}}
}
async function adjudicateIssueLabel(event) {
  event?.preventDefault();
  const c=caseLabelDecisionUi.editor;
  if(!c || caseLabelDecisionUi.saving || !hasDashboardWriteRole() || !isPageContextCurrent(c.pageContext) || caseDecisionCurrentIssueId()!==c.data.issue_id || selectedBaselineQueryValue()!==c.baselines || (c.actor && c.actor !== state.session?.username))return;
  rememberCaseLabelDecisionDraft();
  const p=caseLabelingFormPayload(), error=$("#caseDecisionEditorError");
  error.textContent="";
  if(c.sourceConflict && !c.sourceConflict.acknowledged){
    error.textContent=uiText("来源标注或历史裁决已变化，请先点击“对照最新来源”确认后再提交。","Source labels or prior decision changed. Review the latest sources before submitting.");
    return;
  }
  if(Array.isArray(c.missingAttachments) && c.missingAttachments.length){
    error.textContent=uiText("上次裁决草稿包含未补齐的待上传截图，请重新选择截图或点击“不含原截图继续”后再提交。","Previous decision draft had pending screenshots. Re-attach them or choose 'Continue without screenshots' before submitting.");
    return;
  }
  if(!p.expected_output || caseLabelingOutputValidation().conflict){error.textContent=uiText("请补齐分类并解决标签冲突。","Complete the classification and resolve conflicting tags.");return;}
  if(!c.excludedConfirmed){c.confirmationInvalid=true;updateCaseDecisionConfirmation();$("#caseDecisionConfirmExclusion")?.focus();return;}
  if(c.images.length+c.retained.length>4){error.textContent=uiText("裁决截图最多 4 张。","Maximum 4 decision images.");return;}
  const payload={...p,full_result:true,label_rationale:p.rationale,rationale:c.rationale,adopted_revision_id:c.adoptedId,retained_attachment_ids:c.retained,
    expected_source_fingerprint:c.data.label_state?.source_fingerprint || "",expected_previous_decision_id:c.data.label_state?.decision?.id || null};
  const formNode=$("#caseLabelingForm");caseLabelDecisionUi.saving=true;
  formNode.querySelectorAll("button,input,textarea,select").forEach(n=>{n.dataset.decisionWasDisabled=String(n.disabled);n.disabled=true;});
  enhanceDashboardSelects(formNode);
  let committed=false;
  try{
    const navigationContext = state.activePage === "review"
      ? await reviewSaveNavigationContext(c.data.issue_id) : null;
    if (navigationContext && !reviewSaveNavigationIsCurrent(navigationContext)) return;
    if (navigationContext) navigationContext.savedKind = "decision";
    const labelingQueue = state.activePage === "labeling" ? captureCaseLabelingDecisionQueue() : null;
    const pendingAttachments = typeof normalizeCaseLabelPendingAttachments === "function"
      ? normalizeCaseLabelPendingAttachments(c.images)
      : [];
    const persistedDraft = typeof writeCaseLabelDraft === "function"
      ? writeCaseLabelDraft(c.data.issue_id, "", "decision", {
          ...p,
          decision_rationale: c.rationale,
          excluded_confirmed: c.excludedConfirmed,
          adopted_revision_id: c.adoptedId,
          retained_attachment_ids: c.retained,
          pending_attachments: pendingAttachments,
        }, {
          expectedPreviousId: c.data.label_state?.decision?.id || null,
          expectedSourceFingerprint: c.data.label_state?.source_fingerprint || "",
          pendingAttachments,
        })
      : null;
    const idemKey = persistedDraft?.idempotency_key || "";
    const storagePersisted = persistedDraft ? persistedDraft.persisted !== false : false;
    c._lastDraftPersisted = storagePersisted;
    let body=JSON.stringify(payload),suffix="",headers=idemKey ? {"Idempotency-Key":idemKey} : {};
    if(c.images.length){body=new FormData();body.append("payload",JSON.stringify(payload));c.images.forEach(i=>body.append("attachments",i.file,i.file.name));suffix="-with-attachments";headers={"X-RA-Triage-Request":"labeling-v1",...(idemKey ? {"Idempotency-Key":idemKey} : {})};}
    const saved=await api(`/api/labeling/issues/${encodeURIComponent(c.data.issue_id)}/decisions${suffix}`,{method:"POST",body,headers});
    committed=true;acknowledgeLocalChange(saved);caseLabelDecisionUi.drafts.delete(c.key);
    if (typeof clearCaseLabelDraftIfMatch === "function") {
      clearCaseLabelDraftIfMatch(c.data.issue_id, "", "decision", {
        draftToken: persistedDraft?.draft_token || "",
        idempotencyKey: idemKey,
        signature: persistedDraft?.signature || "",
      });
    } else if (typeof clearCaseLabelDraft === "function") {
      clearCaseLabelDraft(c.data.issue_id, "", "decision");
    }
    caseLabelDecisionUi.saving=false;
    if(caseLabelDecisionUi.editor===c)exitCaseDecisionEditor({discard:true,clearStoredDraft:false});
    showToast(uiText("完整裁决已保存。","Complete decision saved."));
    await refreshCaseDecisionResult({caseData:c.data,pageContext:c.pageContext,baselines:c.baselines,actor:c.actor,navigationContext,labelingQueue});
  }catch(e){
    if(!committed && caseLabelDecisionUi.editor===c){
      const baseText = caseExclusionErrorMessage(e);
      const memWarn = c._lastDraftPersisted === false
        ? uiText("（浏览器存储已满，草稿仅暂存在本页内存中，刷新将丢失，请勿刷新并直接重试。）", " (Browser storage is full; draft is in memory on this page only and will be lost on reload. Do not reload; retry directly.)")
        : "";
      c.error=e.message;
      error.textContent=`${baseText}${memWarn}`;
    }
  }
  finally{caseLabelDecisionUi.saving=false;formNode.querySelectorAll("[data-decision-was-disabled]").forEach(n=>{n.disabled=n.dataset.decisionWasDisabled==="true";delete n.dataset.decisionWasDisabled;});enhanceDashboardSelects(formNode);}
}
function caseDecisionResultIsCurrent(c) {
  return isPageContextCurrent(c.pageContext) && caseDecisionCurrentIssueId() === c.caseData.issue_id
    && selectedBaselineQueryValue() === c.baselines && (!c.actor || c.actor === state.session?.username)
    && (!c.labelingQueue || (c.labelingQueue.detailSeq === state.caseLabeling.detailSeq
      && c.labelingQueue.filterKey === caseLabelingListParams().toString()));
}

async function refreshCaseDecisionResult(c) {
  try{
    if (c.navigationContext) {
      if (!reviewSaveNavigationIsCurrent(c.navigationContext)) { state.reviewQueueStale=true; return; }
      // Reconcile independently of the saved Issue's detail/concurrency reads.
      await refreshReviewAfterSave(c.navigationContext);
      if (!reviewSaveNavigationIsCurrent(c.navigationContext)) return;
    }
    if (!caseDecisionResultIsCurrent(c)) return;
    if (c.labelingQueue) {
      await refreshCaseLabelingDecisionQueue(c);
      if (!caseDecisionResultIsCurrent(c)) return;
    }
    const fresh=await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(c.caseData.issue_id)}`), {
      cache:"no-store", signal:new AbortController().signal,
    });
    if (!caseDecisionResultIsCurrent(c)) return;
    if (state.activePage === "review") { await refreshReviewDecisionResult(fresh); return; }
    for(const key of ["label_cases","label_state","label_source_contexts","decision_history","exclusion_summary"])state.caseLabeling.caseData[key]=fresh[key];
    if (caseLabelDecisionUi.context?.caseData.issue_id === fresh.issue_id) caseLabelDecisionUi.context.caseData = fresh;
    refreshCaseLabelDecisionLanguage();
  }catch(_){showToast(uiText("裁决已保存，请刷新查看最新汇总。","Decision saved. Refresh to see the latest result."),true);}
}
