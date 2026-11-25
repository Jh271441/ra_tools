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
      ? uiText("确认完整 Issue 结果；任务提交进度独立保留", "Decide the complete Issue result; task submissions remain separate")
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

function showCaseDecisionInfo() {
  let dialog = $("#caseDecisionInfoDialog");
  if (!dialog) {
    dialog = document.createElement("dialog"); dialog.id = "caseDecisionInfoDialog";
    dialog.className = "dialog case-label-decision-dialog case-decision-info-dialog";
    dialog.setAttribute("aria-labelledby","caseDecisionInfoTitle"); document.body.appendChild(dialog);
    dialog.addEventListener("click", e => {if (e.target === dialog) dialog.close();});
    dialog.addEventListener("close", () => $("#caseDecisionInfo")?.focus());
  }
  const flow = (label, steps) => `<ol class="case-decision-flow" aria-label="${escapeHtml(label)}">${steps.map(s => `<li>${escapeHtml(s)}</li>`).join("")}</ol>`;
  dialog.innerHTML = `<div class="dialog-card"><div class="dialog-heading"><h2 id="caseDecisionInfoTitle">${uiText("裁决怎样生效", "How decisions work")}</h2><button type="button" class="icon-button" data-close-decision-info aria-label="${uiText("关闭", "Close")}">×</button></div><div class="case-label-decision-body"><section class="case-decision-rule"><h3>${uiText("分类结论", "Classification")}</h3>${flow(uiText("分类流程", "Classification flow"),[uiText("每人最新意见", "Latest opinion per person"),uiText("同一来源形成结论", "Resolve each source"),uiText("所有来源一致，或 Issue 裁决", "Sources agree, or an Issue decision")])}<ul><li>${uiText("同一来源：有有效任务裁决就采用裁决；否则需相关人员提交完整、分类一致。不使用多数票。", "Within a source, a valid task decision applies. Otherwise, required submissions must be complete and agree. There is no majority vote.")}</li><li>${uiText("完整 Issue 裁决统一决定分类、标签与是否排除。采纳已有版本或重新标注后，填写裁决依据；不替他人提交任务。", "A complete Issue decision sets classification, tags and exclusion. Adopt a revision or relabel, then add a review rationale. It does not submit tasks for others.")}</li></ul></section><section class="case-decision-rule"><h3>${uiText("排除意见", "Exclusion")}</h3>${flow(uiText("排除流程", "Exclusion flow"),[uiText("各来源有效意见", "Effective source opinions"),uiText("有任一意见要求排除？", "Does any opinion exclude?"),uiText("有：排除；全部否：不排除", "Yes: excluded; all no: included")])}<ul><li>${uiText("无有效完整裁决时，排除意见有分歧则暂按排除生效。", "Without a valid complete decision, disagreement provisionally excludes the Issue.")}</li><li>${uiText("完整 Issue 裁决的排除／不排除覆盖本地来源意见。旧版仅分类裁决未裁定排除；Trail 同步仍需单独确认。", "A complete Issue decision overrides local exclusion opinions. Legacy classification-only decisions do not decide exclusion. Trail sync remains separate.")}</li></ul></section><section class="case-decision-rule"><h3>${uiText("记录与更新", "History and updates")}</h3><ul><li>${uiText("普通保存只更新自己的意见；所有原记录和裁决依据保留。来源版本改变后，相关裁决需重新确认。", "An ordinary save updates your opinion. Original records and decision rationales are kept. Source changes can require a new decision.")}</li><li>${uiText("Tags 与每人的说明分别保留，不用标签数量决定分类。模型复核与 Issue 标注分开记录。", "Tags and individual rationales are retained. Tag counts do not decide classification. Model reviews are separate from Issue labels.")}</li><li>${uiText("本地标注和裁决不修改 GT 或 Trail。Trail 更新需要另行选中、预览和确认；空理由保留远端原文。", "Local labels and decisions do not change GT or Trail. Trail updates require selection, preview and confirmation; an empty reason preserves remote text.")}</li></ul></section></div><div class="dialog-actions"><button type="button" class="button button-quiet" data-close-decision-info>${uiText("知道了", "Got it")}</button></div></div>`;
  dialog.querySelectorAll("[data-close-decision-info]").forEach(b => b.addEventListener("click", () => dialog.close()));
  if (!dialog.open) dialog.showModal();
}
