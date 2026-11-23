/* One task allocation editor shared by Combined Review and Case labeling. */
const taskAllocationEditor = { config: null, busy: false, error: null, request: null, opener: null, sequence: 0, preview: null, live: null };

function invalidateTaskAllocationPreview() {
  const editor = taskAllocationEditor;
  clearTimeout(editor.live?.timer);
  editor.live?.controller?.abort();
  Object.assign(editor, { live: null, preview: null, request: null });
}

function allocationComparison(before, after) {
  return before === after ? `<strong>${escapeHtml(after)}</strong>`
    : `<span class="allocation-comparison"><span>${escapeHtml(before)}</span><span aria-hidden="true">→</span><strong>${escapeHtml(after)}</strong></span>`;
}

function allocationFact(label, value, { before, detail } = {}) {
  const content = before == null ? `<strong>${escapeHtml(String(value))}</strong>`
    : allocationComparison(String(before), String(value));
  return `<div><dt>${escapeHtml(label)}</dt><dd>${content}${detail ? `<small>${escapeHtml(detail)}</small>` : ""}</dd></div>`;
}

function renderTaskAllocationMembers(members) {
  const config = taskAllocationEditor.config;
  return `<div class="task-allocation-members">${members.map((p) => {
    const saved = config?.assignees.find((item) => item.name === p.name);
    const original = saved?.review_percent == null ? uiText("未记录", "Not recorded") : `${saved.review_percent}%`;
    const actual = assignmentPercent(p.before, config?.total_slots);
    return `<article class="task-allocation-member"><strong>${escapeHtml(p.name)}</strong>
      <dl>${allocationFact(uiText("原分配", "Before"), p.before)}
        ${allocationFact(uiText("已完成并保留", "Completed, retained"), p.completed)}
        ${allocationFact(uiText("已保存/保护待办", "Saved/protected pending"), p.saved_pending)}</dl>
      <details><summary>${escapeHtml(uiText("比例明细", "Share details"))}</summary>
        <p>${escapeHtml(uiText(`原配置 ${original} · 原实际占比 ${actual}`,
          `Previous configured share ${original} · Previous actual share ${actual}`))}</p></details>
      ${saved && config.editable ? `<button type="button" class="button button-quiet"
        data-allocation-remove-member="${escapeHtml(p.name)}">${escapeHtml(uiText("取消此人的未开始分配", "Remove this person's unstarted assignments"))}</button>` : ""}
    </article>`;
  }).join("")}</div>`;
}

function allocationWorkloadBars(member, scale, number) {
  const retained = member.completed + member.saved_pending;
  const compare = member.total_after != null;
  const row = (label, count, extraClass = "") => {
    const movable = Math.max(0, count - retained);
    const breakdown = uiText(`保留 ${number.format(retained)}，可调整 ${number.format(movable)}`,
      `${number.format(retained)} retained, ${number.format(movable)} movable`);
    return `<span class="allocation-workload-bar ${extraClass}">
    <span>${escapeHtml(label)}</span><span class="allocation-workload-track" role="img" aria-label="${escapeHtml(breakdown)}" title="${escapeHtml(breakdown)}">
      <i class="allocation-workload-retained" style="width:${100 * retained / scale}%"></i>
      <i class="allocation-workload-movable" style="width:${100 * movable / scale}%"></i>
    </span><strong>${escapeHtml(number.format(count))}</strong>
  </span>`;
  };
  return `<span class="allocation-workload-bars">
    ${row(compare ? uiText("调整前", "Before") : uiText("当前", "Current"), member.before)}
    ${compare ? row(uiText("调整后", "After"), member.total_after, "is-after") : ""}
  </span>`;
}

function allocationWorkloadLegend() {
  return `<div class="allocation-workload-legend">
    <span><i class="allocation-workload-retained"></i>${escapeHtml(uiText("已保留", "Retained"))}</span>
    <span><i class="allocation-workload-movable"></i>${escapeHtml(uiText("可调整待办", "Movable pending"))}</span>
  </div>`;
}

function renderCurrentAllocationChart(config, number) {
  const members = config.progress_members;
  if (!members.length) return `<p class="dialog-copy">${escapeHtml(uiText("暂无分配记录。", "There are no assignments yet."))}</p>`;
  const scale = Math.max(1, ...members.map((p) => p.before));
  return `<h3>${escapeHtml(uiText("当前人员工作量", "Current member workload"))}</h3>
    ${allocationWorkloadLegend()}
    <div class="allocation-preview-roster">${members.map((member) => `<div class="allocation-preview-person allocation-current-person">
      <strong>${escapeHtml(member.name)}</strong>
      ${allocationWorkloadBars(member, scale, number)}
    </div>`).join("")}</div>`;
}

function renderAllocationPreviewRoster(preview, number) {
  const config = taskAllocationEditor.config;
  const beforeTotal = config?.total_slots || 0;
  const scale = Math.max(1, ...preview.members.flatMap((p) => [p.before, p.total_after]));
  return `<h3>${escapeHtml(uiText("人员工作量", "Member workload"))}</h3>
    ${allocationWorkloadLegend()}
    <div class="allocation-preview-roster">
      ${preview.members.map((member) => {
        const { name, before, total_after: after, pending_after: pending } = member;
        const saved = config?.assignees.find((item) => item.name === name);
        const requested = member.requested_percent == null ? uiText("均分或数量", "Even or by quota") : `${number.format(member.requested_percent)}%`;
        const retained = member.completed + member.saved_pending;
        const label = uiText(
          `${name}，工作量 ${before} 到 ${after}，保留 ${retained}，转入 ${member.incoming}，转出 ${member.outgoing}，调整后待办 ${pending}`,
          `${name}, workload ${before} to ${after}, ${retained} retained, ${member.incoming} incoming, ${member.outgoing} outgoing, ${pending} pending`);
        const transfer = [member.incoming ? `+${number.format(member.incoming)}` : "", member.outgoing ? `−${number.format(member.outgoing)}` : ""].filter(Boolean).join(" / ");
        return `<details class="allocation-preview-person" data-allocation-detail="${escapeHtml(`member:${name}`)}">
          <summary aria-label="${escapeHtml(label)}">
            <span class="allocation-preview-person-title"><strong>${escapeHtml(name)}</strong>
              ${transfer ? `<span>${escapeHtml(transfer)}</span>` : ""}
              <span class="allocation-preview-caret" aria-hidden="true">›</span></span>
            ${allocationWorkloadBars(member, scale, number)}
          </summary>
          <dl>
            ${allocationFact(uiText("已完成", "Completed"), number.format(member.completed))}
            ${allocationFact(uiText("已保护待办", "Protected pending"), number.format(member.saved_pending))}
            ${allocationFact(uiText("转入 / 转出", "In / out"), `${number.format(member.incoming)} / ${number.format(member.outgoing)}`)}
            ${allocationFact(uiText("基础 / 交叉", "Base / cross-review"), `${number.format(member.base_after ?? 0)} / ${number.format(member.cross_after ?? 0)}`)}
            ${allocationFact(uiText("原配置比例", "Previous configured share"),
              saved?.review_percent == null ? uiText("未记录", "Not recorded") : `${number.format(saved.review_percent)}%`,
              { detail: uiText(`原实际 ${assignmentPercent(before, beforeTotal)}`, `Previous actual ${assignmentPercent(before, beforeTotal)}`) })}
            ${allocationFact(uiText("本次目标比例", "Target share"), requested,
              { detail: uiText(`目标 ${number.format(member.ideal)} 份`, `Target ${number.format(member.ideal)} slots`) })}
            ${allocationFact(uiText("最终实际占比", "Final actual share"), `${number.format(member.actual_percent)}%`)}
            ${member.pool_role && member.pool_percent != null ? allocationFact(
              uiText(`${member.pool_role.toUpperCase()} 池内比例`, `${member.pool_role.toUpperCase()} pool share`),
              `${number.format(member.pool_percent)}%`) : ""}
          </dl>
          ${member.constrained ? `<p class="dialog-copy">${escapeHtml(uiText(
            "实际工作量受已有记录、每条人数或角色要求约束。", "Saved work, reviewer counts or role requirements constrain the actual workload.",
          ))}</p>` : ""}
        </details>`;
      }).join("")}
    </div>`;
}

function renderTaskAllocationResults(preview) {
  const number = new Intl.NumberFormat(i18nLocale(), { maximumFractionDigits: 2 });
  const values = preview.coverage_after;
  const before = preview.coverage_before;
  const counts = values ? `${number.format(values.cross_cases)} / ${number.format(values.case_count)}` : "";
  return `
    <dl class="allocation-preview-facts">
      ${values && before ? allocationFact(uiText("交叉比例", "Cross-review ratio"), assignmentPercent(values.cross_cases, values.case_count), {
        before: assignmentPercent(before.cross_cases, before.case_count),
        detail: uiText(`${counts} 个 Case`, `${counts} ${values.case_count === 1 ? "Case" : "Cases"}`),
      }) : ""}
      ${allocationFact(uiText("分配总量", "Total workload"), number.format(preview.total_slots), {
        before: number.format(taskAllocationEditor.config?.total_slots ?? preview.total_slots),
      })}
      ${allocationFact(uiText("涉及 Case", "Cases affected"), number.format(preview.changed_cases), {
        detail: uiText(`转入 ${number.format(preview.moved_slots)} 份`,
          `${number.format(preview.moved_slots)} incoming ${preview.moved_slots === 1 ? "slot" : "slots"}`),
      })}
      ${allocationFact(uiText("保留工作", "Work retained"), number.format(preview.completed_slots + preview.saved_pending_slots), {
        detail: uiText(`完成 ${number.format(preview.completed_slots)} · 保护待办 ${number.format(preview.saved_pending_slots)}`,
          `${number.format(preview.completed_slots)} completed · ${number.format(preview.saved_pending_slots)} protected pending`),
      })}
    </dl>
    ${!preview.changed_cases ? `<p class="dialog-copy">${escapeHtml(uiText(
      "本次没有 Case 需要改派。", "No Case assignments change.",
    ))}</p>` : ""}
    ${renderAllocationPreviewRoster(preview, number)}
    ${preview.cross_groups?.length || preview.changes.length ? `<div class="allocation-preview-details">
      ${assignmentPreviewGroups(preview.cross_groups)}
      ${preview.changes.length ? `<details class="assignment-preview-groups" data-allocation-detail="cases">
        <summary>${escapeHtml(uiText("逐 Case 变更", "Changes by Case"))} · ${number.format(preview.changes.length)}</summary>
        <ul>${preview.changes.slice(0, 12).map((item) => `<li><strong>${escapeHtml(item.issue_id)}</strong>
          <div class="quiet-meta">${escapeHtml(item.before.join(" + "))} → ${escapeHtml(item.after.join(" + "))}</div></li>`).join("")}</ul>
        ${preview.changes.length > 12 ? `<p class="quiet-meta">${escapeHtml(uiText("下载 CSV 查看完整变更。", "Download the CSV for all changes."))}</p>` : ""}
        <button type="button" class="button button-quiet" data-allocation-export>${escapeHtml(uiText("下载变更 CSV", "Download changes CSV"))}</button>
      </details>` : ""}
    </div>` : ""}`;
}

function renderTaskAllocationPreview(preview) {
  return `<section id="taskAllocationPreview" class="task-allocation-preview" aria-label="${escapeHtml(uiText("调整结果", "Allocation results"))}">
    ${renderTaskAllocationResults(preview)}
  </section>`;
}

function exportTaskAllocationChanges() {
  const preview = taskAllocationEditor.preview;
  if (!preview) return;
  const cell = (value) => `"${String(value).replace(/^[=+@-]/, "'$&").replaceAll('"', '""')}"`;
  const rows = [[uiText("Case", "Case"), uiText("原负责人", "Previous owners"), uiText("调整后负责人", "New owners")],
    ...preview.changes.map((r) => [r.issue_id, r.before.join(", "), r.after.join(", ")])];
  const url = URL.createObjectURL(new Blob(["\ufeff", rows.map((row) => row.map(cell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url; link.download = "allocation-changes.csv"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function taskAllocationEditAction(item) {
  const id = item?.split_id || item?.id;
  if (!id || !state.session?.is_admin || item.legacy_read_only ||
      (item.lifecycle && item.lifecycle !== "active") || item.is_current === false) return "";
  return `<button type="button" class="button button-quiet" data-edit-task-allocation="${escapeHtml(id)}">${escapeHtml(uiText("修改分配", "Edit allocation"))}</button>`;
}

function taskAllocationDraft() {
  if (taskAllocationEditor.removal) return {
    quota_basis: $("#taskAllocationBasis")?.value || taskAllocationEditor.config?.quota_basis || "remaining",
  };
  const setup = $("#taskAllocationGroupSetup");
  if (setup) return { ...readAllocationGroupSetup(setup),
    quota_basis: $("#taskAllocationBasis")?.value || "remaining" };
  return taskAllocationEditor.config;
}

function taskAllocationRequestBody(draft, config) {
  return {
    groups: draft.groups, cross_groups: draft.cross_groups, quota_basis: draft.quota_basis,
    expected_revision: config.expected_revision,
  };
}

function taskAllocationPreviewError(error) {
  if (error.messages) return error;
  const parts = typeof error.message === "string" ? error.message.split(" / ") : [];
  return parts.length === 2 ? apiResponseError(parts[0], parts[1])
    : apiResponseError("暂时无法计算预览，请重试。", "The preview could not be calculated. Try again.");
}

function renderTaskAllocationLivePreview() {
  const editor = taskAllocationEditor;
  const content = $("#taskAllocationLiveContent");
  if (!content) return;
  const error = editor.live?.error?.messages;
  const status = $("#taskAllocationLiveStatus");
  status.textContent = error ? uiText(error.zh, error.en)
    : editor.preview || !editor.config.editable ? "" : uiText("正在计算预览…", "Calculating preview…");
  status.classList.toggle("task-allocation-error", Boolean(error));
  $("#taskAllocationRetryPreview").hidden = !editor.live?.failed;
  $("#taskAllocationSave").disabled = editor.busy || !editor.preview || !editor.config.editable;
  const number = new Intl.NumberFormat(i18nLocale(), { maximumFractionDigits: 2 });
  if (renderGroupedAllocationPreview(content, editor.preview || editor.config, editor.plot,
      { formal: editor.config.role_required, editing: Boolean(editor.preview) })) return;
  const open = new Set([...content.querySelectorAll("details[open]")].map((detail) => detail.dataset.allocationDetail));
  content.innerHTML = editor.preview ? renderTaskAllocationResults(editor.preview)
    : renderCurrentAllocationChart(editor.config, number);
  for (const detail of content.querySelectorAll("details[data-allocation-detail]")) {
    if (open.has(detail.dataset.allocationDetail)) detail.open = true;
  }
}

async function fetchTaskAllocationPreview(live, campaignId) {
  const editor = taskAllocationEditor;
  if (editor.live !== live) return;
  const controller = new AbortController();
  live.controller = controller;
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const preview = await api(`/api/campaigns/${encodeURIComponent(campaignId)}/allocation/preview`, {
      method: "POST", body: live.serialized, signal: controller.signal,
    });
    if (editor.live !== live) return;
    editor.preview = preview;
  } catch (error) {
    if (editor.live !== live) return;
    live.failed = error.status !== 400;
    live.error = taskAllocationPreviewError(error);
  } finally {
    clearTimeout(timeout);
  }
  renderTaskAllocationLivePreview();
}

function queueTaskAllocationPreview(draft = taskAllocationDraft()) {
  const editor = taskAllocationEditor;
  const config = editor.config;
  if (!config?.editable || editor.busy || editor.removal || !$("#taskAllocationDialog")?.open) return;
  const serialized = JSON.stringify(taskAllocationRequestBody(draft, config));
  if (editor.live?.serialized === serialized) return;
  if (editor.live && editor.error) {
    editor.error = null;
    $("#taskAllocationError").textContent = "";
  }
  invalidateTaskAllocationPreview();
  const error = groupAllocationSetupError(draft);
  const live = { serialized, error };
  editor.live = live;
  if (!error) live.timer = setTimeout(() => fetchTaskAllocationPreview(live, config.campaign_id), 400);
  renderTaskAllocationLivePreview();
}

async function retryTaskAllocationPreview() {
  const editor = taskAllocationEditor;
  const live = editor.live;
  if (!live?.failed || editor.busy) return;
  const campaignId = editor.config.campaign_id;
  live.failed = false;
  live.error = null;
  renderTaskAllocationLivePreview();
  try {
    const config = await api(`/api/campaigns/${encodeURIComponent(campaignId)}/allocation`);
    if (editor.live !== live) return;
    const draft = taskAllocationDraft();
    editor.config = config;
    invalidateTaskAllocationPreview();
    renderTaskAllocationEditor(draft);
  } catch (error) {
    if (editor.live !== live) return;
    live.failed = true;
    live.error = taskAllocationPreviewError(error);
    renderTaskAllocationLivePreview();
  }
}

function renderTaskAllocationEditor(draft) {
  const editor = taskAllocationEditor;
  const dialog = $("#taskAllocationDialog");
  if (!dialog?.open) return;
  if (editor.removal) {
    renderTaskAllocationRemoval(draft);
    return;
  }
  const config = editor.config;
  const errorText = editor.error?.messages
    ? uiText(editor.error.messages.zh, editor.error.messages.en) : "";
  draft = draft || (config && $("#taskAllocationGroupSetup") ? taskAllocationDraft() : config);
  const basis = draft?.quota_basis || "remaining";
  const number = new Intl.NumberFormat(i18nLocale());
  const currentDetailsOpen = dialog.querySelector(".task-allocation-current")?.open;
  const scrollSelectors = [".task-allocation-body", ".task-allocation-settings", "#taskAllocationPreview"];
  const scrollPositions = scrollSelectors.map((selector) => dialog.querySelector(selector)?.scrollTop || 0);
  const opened = [...dialog.querySelectorAll("#taskAllocationLiveContent details[data-allocation-detail][open]")]
    .map((detail) => detail.dataset.allocationDetail);
  dialog.classList.toggle("is-allocation-edit", Boolean(config));
  dialog.innerHTML = `<form class="dialog-card" id="taskAllocationForm">
    <header class="dialog-header"><div class="task-allocation-heading">
      <h2 id="taskAllocationTitle" tabindex="-1">${escapeHtml(uiText("修改任务分配", "Edit task allocation"))}</h2>
      ${config ? `<p class="dialog-copy">${escapeHtml(config.name || config.campaign_id)} · ${escapeHtml(uiText(
        "已完成与已保存记录自动保留",
        "Completed and saved work stays locked",
      ))}</p>` : ""}
      </div>
      <button class="icon-button" type="button" data-allocation-close aria-label="${escapeHtml(uiText("关闭", "Close"))}">×</button></header>
    ${config ? `<div class="task-allocation-body"><div class="task-allocation-settings">
      <div class="allocation-basis-bar">
        <div class="allocation-section-heading">
          <h3 class="allocation-section-title">${escapeHtml(uiText("分配组", "Allocation groups"))}</h3>
          <span class="allocation-basis-meta">${config.role_movable_slots
            ? uiText(
              `可调 <strong>${escapeHtml(number.format(config.movable_slots))}</strong> 份 · RD ${escapeHtml(number.format(config.role_movable_slots.rd))} / TE ${escapeHtml(number.format(config.role_movable_slots.te))}`,
              `<strong>${escapeHtml(number.format(config.movable_slots))}</strong> movable · RD ${escapeHtml(number.format(config.role_movable_slots.rd))} / TE ${escapeHtml(number.format(config.role_movable_slots.te))}`,
            )
            : uiText(
              `可调 <strong>${escapeHtml(number.format(config.movable_slots))}</strong> 份`,
              `<strong>${escapeHtml(number.format(config.movable_slots))}</strong> movable`,
            )}</span>
        </div>
        <div class="allocation-basis-controls">
          <label class="allocation-basis-inline"><span>${escapeHtml(uiText("分配基数", "Basis"))}</span>
            <select id="taskAllocationBasis">
              <option value="remaining" ${basis === "remaining" ? "selected" : ""}>${escapeHtml(uiText("按剩余量分配", "Distribute remaining work"))}</option>
              <option value="total" ${basis === "total" ? "selected" : ""}>${escapeHtml(uiText("按全量目标补齐", "Fill toward total targets"))}</option>
            </select></label>
          ${config.editable ? `<button class="button button-secondary allocation-compact-btn" type="button" data-allocation-add-group>+ ${escapeHtml(uiText("添加分配组", "Add group"))}</button>` : ""}
        </div>
      </div>
      ${basis === "total" ? `<p class="dialog-copy allocation-basis-hint">${escapeHtml(uiText(
        "已保留工作计入每人的目标配额。", "Retained work counts toward each person's target.",
      ))}</p>` : ""}
      <div id="taskAllocationGroupSetup" class="allocation-group-setup"></div>
      </div>
      <section id="taskAllocationPreview" class="task-allocation-preview" aria-labelledby="taskAllocationPreviewTitle">
        <h3 id="taskAllocationPreviewTitle" tabindex="-1">${escapeHtml(uiText("实时预览", "Live preview"))}</h3>
        <div id="taskAllocationLiveContent" class="allocation-live-content"></div>
      </section>
      <details class="task-allocation-current assignment-preview-groups" ${currentDetailsOpen ? "open" : ""}>
        <summary><span>${escapeHtml(uiText("已保存的分配明细", "Saved allocation details"))}</span>
          <span class="allocation-disclosure-meta">${escapeHtml(uiText(
            `已完成 ${number.format(config.completed_slots)} · 已保护待办 ${number.format(config.saved_pending_slots)}`,
            `${number.format(config.completed_slots)} completed · ${number.format(config.saved_pending_slots)} protected pending`,
          ))}</span></summary>
        ${renderTaskAllocationMembers(config.progress_members || [])}
        ${config.editable ? `<button class="button button-secondary" type="button" data-allocation-delete>${escapeHtml(uiText("删除整条分配", "Delete entire allocation"))}</button>` : ""}
      </details></div>` : `<p class="dialog-copy">${escapeHtml(uiText("正在加载分配…", "Loading allocation…"))}</p>`}
    ${config ? `<div class="allocation-live-status">
      <p id="taskAllocationLiveStatus" class="dialog-copy" role="status"></p>
      <button class="button button-secondary" type="button" id="taskAllocationRetryPreview" data-allocation-retry-preview hidden>
        ${escapeHtml(uiText("重新计算", "Recalculate"))}</button>
    </div>` : ""}
    <p class="task-allocation-error" role="alert" id="taskAllocationError">${escapeHtml(errorText)}</p>
    <footer class="task-allocation-edit-footer">
      ${config ? `<button class="button button-secondary task-allocation-preview-jump" type="button" data-allocation-view-preview>
        ${escapeHtml(uiText("查看图表", "View chart"))}</button>` : ""}
      <div class="dialog-actions">
        <button class="button button-secondary" type="button" data-allocation-reload ${!config && editor.error ? "" : "hidden"}>${escapeHtml(uiText("重新加载分配", "Reload allocation"))}</button>
        <button class="button button-secondary" type="button" data-allocation-close>${escapeHtml(uiText("取消", "Cancel"))}</button>
        <button class="button button-primary" type="button" id="taskAllocationSave" data-allocation-apply disabled>${escapeHtml(editor.busy
          ? uiText("正在保存…", "Saving…") : uiText("应用调整", "Apply changes"))}</button>
      </div>
    </footer>
  </form>`;
  if (config) {
    enhanceNativeUiSelect($("#taskAllocationBasis"));
    renderAllocationGroupSetup($("#taskAllocationGroupSetup"), {
      ...draft, cross_groups: draft === config ? config.group_rules : draft.cross_groups,
    }, { users: config.eligible_members, formal: config.role_required, editable: config.editable,
      change: () => queueTaskAllocationPreview() });
    queueTaskAllocationPreview();
    renderTaskAllocationLivePreview();
    for (const detail of dialog.querySelectorAll("#taskAllocationLiveContent details[data-allocation-detail]")) {
      if (opened.includes(detail.dataset.allocationDetail)) detail.open = true;
    }
    scrollSelectors.forEach((selector, index) => {
      const element = dialog.querySelector(selector);
      if (element) element.scrollTop = scrollPositions[index];
    });
  }
  if (editor.busy) dialog.querySelectorAll("button, input, select, textarea").forEach((control) => { control.disabled = true; });
}

function renderTaskAllocationRemoval(draft = taskAllocationDraft()) {
  const editor = taskAllocationEditor, config = editor.config;
  const whole = editor.removal === "all";
  const errorText = editor.error?.messages ? uiText(editor.error.messages.zh, editor.error.messages.en) : "";
  const member = config?.progress_members?.find((p) => p.name === editor.removeAssignee);
  $("#taskAllocationDialog").classList.remove("is-allocation-edit");
  $("#taskAllocationDialog").innerHTML = `<form class="dialog-card">
    <header class="dialog-header"><h2 id="taskAllocationTitle">${escapeHtml(whole
      ? uiText("删除整条任务分配", "Delete the whole allocation")
      : uiText("取消个人未开始分配", "Remove unstarted assignments"))}</h2>
      <button class="icon-button" type="button" data-allocation-close aria-label="${escapeHtml(uiText("关闭", "Close"))}">×</button></header>
    ${config ? `<p class="dialog-copy">${escapeHtml(config.name || config.campaign_id)}</p>
      <p class="task-allocation-note">${escapeHtml(whole ? uiText(
        `此任务将进入“已取消”，从当前分配中移除。已有 ${config.completed_slots} 份完成记录和 ${config.saved_pending_slots} 份已保存/保护待办全部保留，可从历史任务查看。取消后不能恢复为当前任务。`,
        `This task will become Cancelled and leave current allocations. All ${config.completed_slots} completed and ${config.saved_pending_slots} saved/protected pending slots are retained in task history. Cancellation cannot be undone.`)
        : uiText(
          `取消 ${editor.removeAssignee} 的未开始分配。保留其 ${member?.completed || 0} 份已完成和 ${member?.saved_pending || 0} 份已保存/保护待办；未开始部分由其余成员接续。`,
          `Remove ${editor.removeAssignee} from unstarted assignments. Retain their ${member?.completed || 0} completed and ${member?.saved_pending || 0} saved/protected pending slots; other members will take the untouched work.`))}</p>
      ${whole ? `<p class="dialog-copy">${escapeHtml(uiText("任务及成果保留在历史记录中，后续提交将被停止。", "The task and its evidence remain in history; further submissions will stop."))}</p>
        ${config.appendable ? `<p class="dialog-copy">${escapeHtml(uiText("该任务为持续追加任务，取消后也将停止向其追加新 Case。", "This is an appendable task. Cancellation also stops new Cases from being appended."))}</p>` : ""}`
        : `<p class="dialog-copy">${escapeHtml(uiText(
          "使用已保存的成员比例，在剩余成员中归一为 100%。原交叉人数和 RD/TE 要求保持；人数不足时，请返回修改分配并先补充接收人。",
          "Saved shares are normalized to 100% among the remaining members. Cross-review counts and RD/TE requirements stay fixed. If recipients are insufficient, go back and add a replacement first."))}</p>
        <div class="task-allocation-fields"><label><span>${escapeHtml(uiText("分配基数", "Allocation basis"))}</span>
          <select id="taskAllocationBasis">
            <option value="remaining" ${draft.quota_basis !== "total" ? "selected" : ""}>${escapeHtml(uiText("按剩余量分配", "Distribute remaining work"))}</option>
            <option value="total" ${draft.quota_basis === "total" ? "selected" : ""}>${escapeHtml(uiText("按全量均衡", "Balance total workload"))}</option>
          </select></label></div>`}` : `<p class="dialog-copy">${escapeHtml(uiText("正在加载分配…", "Loading allocation…"))}</p>`}
    ${editor.preview ? renderTaskAllocationPreview(editor.preview) : ""}
    <p class="task-allocation-error" role="alert">${escapeHtml(errorText)}</p>
    <footer class="dialog-actions">
      <button type="button" class="button button-quiet" data-allocation-back>${escapeHtml(uiText("返回修改分配", "Back to editing"))}</button>
      <button type="button" class="button button-quiet" data-allocation-reload ${editor.error ? "" : "hidden"}>${escapeHtml(uiText("重新核对分配", "Reload allocation"))}</button>
      ${whole ? "" : `<button type="button" class="button button-quiet" data-allocation-close>${escapeHtml(uiText("返回", "Go back"))}</button>`}
      <button type="submit" class="button button-primary" id="taskAllocationSave" ${!config?.editable ? "disabled" : ""}>${escapeHtml(editor.busy
        ? uiText("正在处理…", "Working…") : whole ? uiText("删除分配并保留成果", "Delete allocation, retain evidence")
          : editor.preview ? uiText("确认取消并接续待办", "Confirm removal and redistribute") : uiText("预览调整", "Preview changes"))}</button>
    </footer></form>`;
  if (!whole && config) enhanceNativeUiSelect($("#taskAllocationBasis"));
  if (editor.busy) $("#taskAllocationDialog").querySelectorAll("button, input, select").forEach((control) => { control.disabled = true; });
}

function returnToTaskAllocationEditor() {
  const editor = taskAllocationEditor;
  const whole = editor.removal === "all";
  const draft = editor.previousDraft;
  Object.assign(editor, { removal: "", error: "", previousDraft: null });
  invalidateTaskAllocationPreview();
  renderTaskAllocationEditor(draft);
  if (whole) {
    const current = $("#taskAllocationDialog .task-allocation-current");
    if (current) {
      current.open = true;
      current.querySelector("[data-allocation-delete]")?.focus();
    }
  }
}

async function openTaskAllocationEditor(campaignId, opener = null, removal = "") {
  let dialog = $("#taskAllocationDialog");
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = "taskAllocationDialog";
    dialog.className = "dialog task-allocation-dialog";
    dialog.setAttribute("aria-labelledby", "taskAllocationTitle");
    document.body.append(dialog);
    dialog.addEventListener("cancel", (event) => {
      if (taskAllocationEditor.busy) event.preventDefault();
      else if (taskAllocationEditor.removal === "all") {
        event.preventDefault();
        returnToTaskAllocationEditor();
      }
    });
    dialog.addEventListener("close", () => {
      invalidateTaskAllocationPreview();
      taskAllocationEditor.sequence += 1;
      taskAllocationEditor.opener?.focus();
    });
    dialog.addEventListener("submit", (event) => {
      event.preventDefault();
      if (taskAllocationEditor.removal) saveTaskAllocation();
    });
    dialog.addEventListener("change", (event) => {
      if (taskAllocationEditor.removal) {
        const draft = taskAllocationDraft();
        invalidateTaskAllocationPreview();
        renderTaskAllocationEditor(draft);
        return;
      }
      if (event.target.id === "taskAllocationBasis") queueTaskAllocationPreview();
    });
    dialog.addEventListener("click", (event) => {
      if (taskAllocationEditor.busy) return;
      if (event.target.closest("[data-allocation-close]")) dialog.close();
      if (event.target.closest("[data-allocation-reload]")) {
        const removedMember = taskAllocationEditor.removeAssignee;
        openTaskAllocationEditor(dialog.dataset.campaignId, null, taskAllocationEditor.removal);
        taskAllocationEditor.removeAssignee = removedMember;
      }
      if (event.target.closest("[data-allocation-export]")) exportTaskAllocationChanges();
      if (event.target.closest("[data-allocation-apply]")) saveTaskAllocation();
      if (event.target.closest("[data-allocation-retry-preview]")) retryTaskAllocationPreview();
      if (event.target.closest("[data-allocation-add-group]")) {
        dialog.querySelector('#taskAllocationGroupSetup [data-setup-action="add-group"]')?.click();
      }
      if (event.target.closest("[data-allocation-view-preview]")) {
        const heading = $("#taskAllocationPreviewTitle");
        heading?.scrollIntoView({ block: "start" });
        heading?.focus({ preventScroll: true });
      }
      if (event.target.closest("[data-allocation-delete]")) {
        taskAllocationEditor.previousDraft = taskAllocationDraft();
        Object.assign(taskAllocationEditor, { removal: "all", error: "" });
        invalidateTaskAllocationPreview();
        renderTaskAllocationEditor();
        dialog.querySelector("[data-allocation-back]")?.focus();
      }
      const removeMember = event.target.closest("[data-allocation-remove-member]");
      if (removeMember) {
        taskAllocationEditor.previousDraft = taskAllocationDraft();
        Object.assign(taskAllocationEditor, { removal: "member", removeAssignee: removeMember.dataset.allocationRemoveMember, error: "" });
        invalidateTaskAllocationPreview();
        renderTaskAllocationEditor();
        $("#taskAllocationSave")?.focus();
      }
      if (event.target.closest("[data-allocation-back]")) returnToTaskAllocationEditor();

    });
  }
  invalidateTaskAllocationPreview();
  Object.assign(taskAllocationEditor, { config: null, busy: false, error: null, removal, removeAssignee: "", plot: allocationPreviewView() });
  if (opener) taskAllocationEditor.opener = opener;
  const sequence = ++taskAllocationEditor.sequence;
  dialog.dataset.campaignId = campaignId;
  if (!dialog.open) dialog.showModal();
  renderTaskAllocationEditor();
  try {
    const config = await api(`/api/campaigns/${encodeURIComponent(campaignId)}/allocation`);
    if (sequence !== taskAllocationEditor.sequence || !dialog.open) return;
    taskAllocationEditor.config = config;
    if (!config.editable) taskAllocationEditor.error = apiResponseError("此任务已结束，无法修改分配。", "This task is no longer active.");
    renderTaskAllocationEditor(config);
  } catch (error) {
    if (sequence !== taskAllocationEditor.sequence) return;
    taskAllocationEditor.error = error.messages ? error
      : apiResponseError("加载分配失败，请重试。", "Loading the allocation failed. Please retry.");
    renderTaskAllocationEditor();
  }
}

async function saveTaskAllocation() {
  const editor = taskAllocationEditor;
  if (editor.busy || !editor.config?.editable) return;
  if (editor.removal) return saveTaskAllocationRemoval();
  const draft = taskAllocationDraft();
  const body = taskAllocationRequestBody(draft, editor.config);
  if (!editor.preview || editor.live?.serialized !== JSON.stringify(body) || editor.preview.expires_at * 1000 <= Date.now()) {
    invalidateTaskAllocationPreview();
    queueTaskAllocationPreview(draft);
    return;
  }
  body.preview_token = editor.preview.preview_token;
  const serialized = JSON.stringify(body);
  if (editor.request?.serialized !== serialized) editor.request = { serialized, key: crypto.randomUUID() };
  editor.busy = true; editor.error = "";
  renderTaskAllocationEditor(draft);
  try {
    editor.lastResult = await api(`/api/campaigns/${encodeURIComponent(editor.config.campaign_id)}/allocation`, {
      method: "PATCH", headers: { "Idempotency-Key": editor.request.key }, body: serialized,
    });
  } catch (error) {
    const stale = error.status === 409;
    if (stale) invalidateTaskAllocationPreview();
    const bilingual = error.status === 400 && typeof error.message === "string" ? error.message.split(" / ") : [];
    const validationError = bilingual.length === 2 ? apiResponseError(bilingual[0], bilingual[1]) : null;
    editor.error = stale
      ? apiResponseError("标注、成员或任务已变化。请核对更新后的预览。", "Work, members or the task changed. Review the updated preview.")
      : error.messages ? error : validationError || (error.status === 400
        ? apiResponseError("分配配置无效，请检查成员权限、个人比例或数量及交叉设置。", "Invalid allocation. Check member access, personal shares or quotas and cross-review settings.")
        : apiResponseError("保存失败，请重试。", "Saving failed. Please retry."));
    editor.busy = false;
    renderTaskAllocationEditor(draft);
    return;
  }
  editor.busy = false;
  $("#taskAllocationDialog").close();
  showToast(editor.lastResult?.changed ? uiText("分配已更新，已保存工作的内容和归属均已保留。", "Allocation updated. Saved work and ownership were preserved.") : uiText("分配没有变化，已保留原任务。", "No allocation changes. The task was retained."));
  await refreshTaskAllocationLists();
}

async function refreshTaskAllocationLists() {
  const editor = taskAllocationEditor;
  const refreshes = [];
  if (state.activePage === "review-assignments") refreshes.push(loadReviewAssignments({ force: true }));
  if (state.activePage === "labeling-new-task" || state.activePage === "case-labeling") {
    refreshes.push(loadCaseLabelingTasks(), loadLabelingCombinedTasks());
  }
  const results = await Promise.allSettled(refreshes);
  if (results.some((r) => r.status === "rejected")) showToast(uiText("分配已保存；列表刷新失败，请刷新页面。", "Allocation saved; refresh the page to reload the list."), true);
  const id = CSS.escape(editor.config.campaign_id);
  const focusTarget = document.querySelector(`[data-edit-task-allocation="${id}"]`)
    || document.querySelector("main h1, main h2, main h3");
  if (focusTarget && !$("#taskAllocationDialog")?.open) {
    if (!focusTarget.matches("button, a")) focusTarget.tabIndex = -1;
    focusTarget.focus({ preventScroll: true });
  }
}

async function saveTaskAllocationRemoval() {
  const editor = taskAllocationEditor, draft = taskAllocationDraft();
  const whole = editor.removal === "all";
  const base = `/api/campaigns/${encodeURIComponent(editor.config.campaign_id)}/allocation`;
  const path = whole ? base : `${base}/assignees/${encodeURIComponent(editor.removeAssignee)}`;
  const previewing = !whole && !editor.preview;
  editor.busy = true; editor.error = "";
  renderTaskAllocationEditor(draft);
  try {
    if (previewing) {
      editor.config = await api(base);
      editor.preview = await api(`${path}/removal-preview`, { method: "POST", body: JSON.stringify({
        expected_revision: editor.config.expected_revision, quota_basis: draft.quota_basis,
      }) });
    } else {
      const body = whole ? { expected_revision: editor.config.expected_revision,
        reason: "Allocation deleted through task editor; saved evidence retained." }
        : { expected_revision: editor.config.expected_revision, quota_basis: draft.quota_basis, preview_token: editor.preview.preview_token };
      const serialized = JSON.stringify(body);
      if (editor.request?.serialized !== serialized) editor.request = { serialized, key: crypto.randomUUID() };
      editor.lastResult = await api(path, { method: "DELETE", headers: { "Idempotency-Key": editor.request.key }, body: serialized });
    }
  } catch (error) {
    if (error.status === 409) editor.preview = null;
    const parts = typeof error.message === "string" ? error.message.split(" / ") : [];
    editor.error = parts.length === 2 ? apiResponseError(parts[0], parts[1])
      : error.status === 409 ? apiResponseError("任务或标注已有变化，请重新核对分配。", "The task or saved work changed. Reload the allocation.")
        : apiResponseError("操作失败。请检查剩余成员能否满足分配要求，再重试。", "The operation failed. Check that remaining members meet allocation requirements, then retry.");
    editor.busy = false;
    renderTaskAllocationEditor(draft);
    return;
  }
  editor.busy = false;
  if (previewing) {
    renderTaskAllocationEditor(draft);
    $("#taskAllocationPreview")?.scrollIntoView({ block: "start", behavior: "smooth" });
    return;
  }
  $("#taskAllocationDialog").close();
  showToast(whole ? uiText("分配已删除，已有成果保留在历史任务中。", "Allocation deleted; evidence remains in task history.")
    : uiText("个人未开始分配已取消，待办已接续，已有成果保留。", "Unstarted assignments removed and redistributed; saved work was retained."));
  await refreshTaskAllocationLists();
}

function bindTaskAllocationEditor() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-edit-task-allocation]");
    if (button) openTaskAllocationEditor(button.dataset.editTaskAllocation, button);
  });
}
