/* Explain the server's current projection; never recompute or override a label. */
function caseLabelExplanation(caseData) {
  const result = caseData.label_state || {};
  const sources = result.sources || [];
  const decision = result.decision;
  const status = result.state || "none";
  let reason, next;
  if (status === "resolved") {
    reason = decision && !decision.stale
      ? uiText("有效 Issue 裁决生效", "Current Issue decision applies")
      : sources.length > 1 ? uiText("所有来源已完成且结果一致", "All sources resolved and agree")
      : sources[0]?.method === "adjudication" ? uiText("有效任务内裁决生效", "Current task decision applies")
      : uiText("有效标注已形成一致结果", "Valid submissions agree");
    next = uiText("当前有效结果", "Current valid result");
  } else if (status === "stale" || decision?.stale) {
    reason = uiText("引用的标注来源已变化", "Referenced labeling sources changed");
    next = uiText("重新确认裁决", "Reconfirm the decision");
  } else if (!sources.length) {
    reason = uiText("暂无有效标注来源", "No valid labeling sources yet");
    next = uiText("提交标注后再汇总", "Submit a label to form a result");
  } else if (status === "conflict") {
    reason = sources.some((source) => source.state === "conflict")
      ? uiText("任务或来源内部意见不一致", "A source has conflicting votes")
      : new Set(sources.filter((source) => source.state === "resolved").map((source) => source.expected_output)).size > 1
        ? uiText("不同来源的结果不一致", "Source results disagree")
        : uiText("来源存在未解决冲突", "An unresolved source conflict remains");
    next = sources.some((source) => source.task_id && source.state !== "resolved")
      ? uiText("先完成任务内裁决", "Resolve the task first")
      : uiText("完成 Issue 裁决", "Adjudicate this Issue");
  } else {
    const missing = sources.reduce((total, source) => total + (source.task_id && source.state === "pending" ? Math.max(0, Number(source.assigned_count || 0) - Number(source.submitted_count || 0)) : 0), 0);
    reason = missing ? uiText(`任务还缺 ${missing} 份提交`, `${missing} task submissions missing`)
      : uiText("仍有来源未形成有效结果", "Some sources have no valid result yet");
    next = uiText("补齐提交或期望输出", "Complete submissions or expected outputs");
  }
  return {status, sources, reason, next,
    output: status === "resolved" ? result.expected_output || "" : ""};
}

function showCaseLabelExplanation(caseData) {
  const explanation = caseLabelExplanation(caseData);
  const statuses = {
    none: uiText("待完成", "Pending"), pending: uiText("待完成", "Pending"),
    conflict: uiText("待裁决", "Needs adjudication"), stale: uiText("需重新确认", "Needs confirmation"),
    resolved: uiText("已形成结论", "Resolved"),
  };
  const methods = {single: uiText("单人标注", "Single label"), consensus: uiText("多人一致", "Consensus"), adjudication: uiText("任务内裁决", "Task decision")};
  const sourceMarkup = explanation.sources.map((source, index) => {
    const task = (state.caseLabeling.tasks || []).find((item) => item.id === source.task_id);
    const name = source.task_id ? task?.name || uiText(`任务来源 ${index + 1}`, `Task source ${index + 1}`) : uiText("任务外标注", "Independent label");
    const counts = source.task_id ? uiText(`已提交 ${Number(source.submitted_count || 0)} / ${Number(source.assigned_count || 0)}`, `Submitted ${Number(source.submitted_count || 0)} / ${Number(source.assigned_count || 0)}`) : "";
    const revisions = (source.revision_summaries || []).map((revision) => `${revision.author || "—"} · ${revision.expected_output || uiText("待补充", "Incomplete")}`).join(" / ");
    return `<div class="case-explanation-source"><strong title="${escapeHtml(source.task_id || "")}">${escapeHtml(name)}</strong><span>${escapeHtml(counts)}${counts ? " · " : ""}${escapeHtml(statuses[source.state] || statuses.pending)}</span>${source.state === "resolved" ? `<span>${escapeHtml(methods[source.method] || "")} · ${escapeHtml(source.expected_output || "")}</span>` : ""}${revisions ? `<details><summary>${escapeHtml(uiText("标注记录", "Label records"))}</summary><p>${escapeHtml(revisions)}</p></details>` : ""}</div>`;
  }).join("") || `<div class="case-explanation-source"><strong>${escapeHtml(uiText("0 个有效来源", "0 valid sources"))}</strong><span>${escapeHtml(uiText("尚无可汇总的标注", "No labels to aggregate yet"))}</span></div>`;
  let dialog = document.getElementById("caseLabelExplanationDialog");
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = "caseLabelExplanationDialog";
    dialog.className = "dialog case-label-explanation-dialog";
    dialog.setAttribute("aria-labelledby", "caseLabelExplanationTitle");
    document.body.appendChild(dialog);
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  }
  const decision = caseData.label_state?.decision;
  const resolved = explanation.status === "resolved";
  const blocked = ["conflict", "stale"].includes(explanation.status);
  const currentStep = resolved ? 2 : blocked ? 1 : 0;
  const steps = [uiText("提交标注", "Submit"), uiText("汇总校验", "Validate"), uiText("形成结论", "Resolve")];
  const title = statuses[explanation.status] || statuses.pending;
  dialog.innerHTML = `<div class="dialog-card"><div class="dialog-heading"><div><p class="case-explanation-issue">${escapeHtml(caseData.issue_id)}</p><h2 id="caseLabelExplanationTitle"><span class="case-label-status" data-state="${escapeHtml(explanation.status)}">${escapeHtml(title)}</span></h2></div><button class="icon-button" type="button" data-close-explanation aria-label="${escapeHtml(uiText("关闭", "Close"))}">×</button></div>
    <ol class="case-explanation-steps" aria-label="${escapeHtml(uiText("当前标注进度", "Current labeling progress"))}">${steps.map((step, index) => `<li class="${index < currentStep || resolved ? "is-done" : index === currentStep ? "is-current" : ""}" ${index === currentStep ? 'aria-current="step"' : ""}><span class="case-explanation-step-dot" aria-hidden="true">${index < currentStep || resolved ? "✓" : index + 1}</span><span>${escapeHtml(step)}</span></li>`).join("")}</ol>
    <div class="case-explanation-reason"><strong>${escapeHtml(explanation.reason)}</strong>${explanation.output ? labelBadge(explanation.output) : ""}${!resolved ? `<p>${escapeHtml(explanation.next)}</p>` : ""}</div>
    ${decision ? `<p class="case-explanation-decision">${escapeHtml(uiText("Issue 裁决", "Issue decision"))} #${escapeHtml(decision.id)} · ${escapeHtml(decision.created_by || "")}${decision.stale ? ` · ${escapeHtml(uiText("已过期", "Stale"))}` : ""}</p>` : ""}
    ${explanation.sources.length ? `<details class="case-explanation-evidence"><summary>${escapeHtml(uiText(`查看 ${explanation.sources.length} 个标注来源`, `View ${explanation.sources.length} sources`))}</summary><div>${sourceMarkup}</div></details>` : ""}
    <div class="dialog-actions"><button class="button button-quiet" type="button" data-close-explanation>${escapeHtml(uiText("返回标注", "Back to labeling"))}</button></div></div>`;
  dialog.querySelectorAll("[data-close-explanation]").forEach((button) => button.addEventListener("click", () => dialog.close()));
  if (!dialog.open) dialog.showModal();
}
