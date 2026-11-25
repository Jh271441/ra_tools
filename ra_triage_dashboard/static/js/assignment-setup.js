/* Shared live creation requests. The submit uses the exact acknowledged preview. */
function assignmentPercent(count, total) {
  return new Intl.NumberFormat(i18nLocale(), { style: "percent", maximumFractionDigits: 2 })
    .format(total ? count / total : 0);
}

function assignmentPreviewGroups(groups) {
  if (!groups?.length) return "";
  return '<details class="assignment-preview-groups"><summary>' +
    escapeHtml(uiText("已指定的交叉搭档", "Specified cross-review partners")) +
    '</summary><ul>' + groups.map((group) => '<li><strong>' +
      escapeHtml(group.members.map((member) => member.name ?? member).join(" + ")) + '</strong><div class="quiet-meta">' +
      escapeHtml(group.issue_ids.join(", ")) + '</div></li>').join("") + '</ul></details>';
}

const creationAllocation = new Map();
const creationAllocationEndpoints = { workSplit: "/api/cases/work-split", labelingTask: "/api/labeling/tasks" };

function creationAllocationBody(prefix) {
  const setup = readAllocationGroupSetup($("#" + prefix + "GroupSetup"));
  const review = prefix === "workSplit";
  const body = {
    groups: setup.groups,
    cross_groups: setup.pairing_mode === "custom" ? setup.cross_groups : [],
    pairing_mode: setup.pairing_mode === "paired" ? "paired" : "orthogonal",
    filters: review ? workSplitFilters() : labelingTaskFilterPayload(),
  };
  if (review) body.workflow_mode = $("#workSplitWorkflowMode")?.value || "model_review_and_case_label";
  const name = $("#" + prefix + "Name")?.value.trim();
  const seed = $("#" + prefix + "Seed")?.value.trim();
  if (name) body.name = name;
  if (seed) body.seed = Number(seed);
  return body;
}

function renderCreationAllocationPreview(prefix) {
  const entry = creationAllocation.get(prefix);
  if (!entry) return;
  const button = $("#" + prefix + "Generate");
  const status = $("#" + prefix + "PreviewStatus");
  const pendingBadge = $("#" + prefix + "PreviewPending");
  const content = $("#" + prefix + "PlanPreview");
  const retry = $("#" + prefix + "RetryPreview");
  const shownPlan = entry.plan || (!entry.retry ? entry.lastPlan : null);
  const isPending = Boolean(!entry.plan && !entry.error);
  button.disabled = !entry.plan || entry.busy || entry.closed;
  button.textContent = entry.busy ? uiText("正在创建…", "Creating…") : uiText("创建分配", "Create allocation");
  if (pendingBadge) pendingBadge.hidden = !(isPending && shownPlan);
  status.textContent = entry.error?.messages
    ? uiText(entry.error.messages.zh, entry.error.messages.en)
    : isPending && !shownPlan ? uiText("正在计算预览…", "Calculating preview…") : "";
  status.classList.toggle("task-allocation-error", Boolean(entry.error?.messages && entry.retry));
  retry.hidden = !entry.retry;
  content.hidden = !shownPlan;
  content.classList.toggle("is-preview-updating", Boolean(isPending && shownPlan));
  content.classList.toggle("is-preview-stale", Boolean(entry.error && shownPlan));
  if (shownPlan) renderGroupedAllocationPreview(content, shownPlan, entry.view);
  else {
    delete content.dataset.previewStructKey;
    content.replaceChildren();
  }
}

function cancelCreationAllocationPreview(entry) {
  clearTimeout(entry.timer);
  entry.timer = null;
  entry.runFetch = null;
  entry.controller?.abort();
}

function flushCreationGroupPreview(prefix) {
  const entry = creationAllocation.get(prefix);
  if (!entry?.timer || !entry.runFetch) return;
  clearTimeout(entry.timer);
  entry.timer = null;
  const run = entry.runFetch;
  entry.runFetch = null;
  void run();
}

function queueCreationGroupPreview(prefix, optionsOrForce = false) {
  const opts = typeof optionsOrForce === "object" && optionsOrForce !== null
    ? optionsOrForce
    : { force: Boolean(optionsOrForce), immediate: Boolean(optionsOrForce) };
  const force = Boolean(opts.force);
  const immediate = Boolean(opts.immediate);
  const delay = typeof opts.delay === "number" ? opts.delay : 120;
  const entry = creationAllocation.get(prefix);
  const root = $("#" + prefix + "GroupSetup");
  if (!entry || !root?.childElementCount || entry.busy || !state.session?.is_admin) return;
  if (prefix === "workSplit" && (workSplitDraft?.dirty || workSplitDraft?.submitted || $("#workSplitPanel")?.hidden)) return;
  if (prefix === "labelingTask" && state.activePage !== "labeling-new-task") return;
  const body = creationAllocationBody(prefix);
  const serialized = JSON.stringify(body);
  if (!force && serialized === entry.serialized) {
    if (immediate && entry.timer) flushCreationGroupPreview(prefix);
    return;
  }
  cancelCreationAllocationPreview(entry);
  const draft = readAllocationGroupSetup(root);
  const error = groupAllocationSetupError(draft) ||
    (body.seed !== undefined && !Number.isSafeInteger(body.seed) ? apiResponseError("种子必须为整数。", "Seed must be an integer.") : null);
  Object.assign(entry, { serialized, plan: null, error, retry: false, closed: false, requestId: crypto.randomUUID() });
  renderCreationAllocationPreview(prefix);
  if (error) return;
  const controller = new AbortController();
  entry.controller = controller;
  const requestId = entry.requestId;
  const runFetch = async () => {
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const result = await api(creationAllocationEndpoints[prefix], { method: "POST", signal: controller.signal,
        body: JSON.stringify({ ...body, request_id: requestId, preview_only: true }) });
      if (creationAllocation.get(prefix) !== entry || entry.requestId !== requestId) return;
      entry.plan = result.preview;
      entry.lastPlan = result.preview;
    } catch (failure) {
      if (creationAllocation.get(prefix) !== entry || entry.requestId !== requestId) return;
      entry.error = taskAllocationPreviewError(failure);
      entry.retry = true;
      entry.lastPlan = null;
    } finally {
      clearTimeout(timeout);
    }
    renderCreationAllocationPreview(prefix);
  };
  if (immediate || delay <= 0) {
    void runFetch();
  } else {
    entry.runFetch = runFetch;
    entry.timer = setTimeout(() => {
      entry.timer = null;
      entry.runFetch = null;
      void runFetch();
    }, delay);
  }
}

function creationAllocationCaseCount(prefix) {
  const live = prefix === "workSplit"
    ? (typeof workSplitTotal === "function" ? Number(workSplitTotal() || 0) : 0)
    : Number(state.caseLabeling?.data?.total || 0);
  if (live > 0) return live;
  return Number(creationAllocation.get(prefix)?.plan?.group_coverage?.case_count || 0);
}

function displayCreationGroupSetup(prefix, draft = null) {
  const root = $("#" + prefix + "GroupSetup");
  if (!root) return;
  const prior = creationAllocation.get(prefix);
  if (draft || !prior) {
    if (prior) cancelCreationAllocationPreview(prior);
    creationAllocation.set(prefix, { view: allocationPreviewView() });
  }
  const content = draft || readAllocationGroupSetup(root);
  const caseCount = creationAllocationCaseCount(prefix);
  renderAllocationGroupSetup(root, content, {
    users: state.accessUsers || [],
    caseCount,
    quotaBasis: "total",
    change: (meta) => {
      const kind = prefix === "workSplit" ? "review" : "labeling";
      if (kind === "review" && workSplitDraft) {
        workSplitDraft.groupSetup = readAllocationGroupSetup(root);
        saveReviewAllocationDraft(workSplitDraft);
      }
      updateAssignmentNameSuggestion(kind);
      queueCreationGroupPreview(prefix, { immediate: Boolean(meta?.immediate) });
    },
    flush: () => flushCreationGroupPreview(prefix),
  });
  queueCreationGroupPreview(prefix, { immediate: true });
  renderCreationAllocationPreview(prefix);
}

function bindCreationGroupSetup(prefix) {
  if (prefix === "workSplit") {
    $("#workSplitWorkflowMode")?.addEventListener("change", () => updateAssignmentNameSuggestion("review"));
  }
  for (const id of ["Name", "Seed", "WorkflowMode"]) {
    const control = $("#" + prefix + id);
    control?.addEventListener("input", () => queueCreationGroupPreview(prefix, { delay: id === "Name" ? 220 : 120 }));
    control?.addEventListener("change", () => queueCreationGroupPreview(prefix, { immediate: true }));
  }
  $("#" + prefix + "RetryPreview")?.addEventListener("click", () => queueCreationGroupPreview(prefix, { force: true, immediate: true }));
}

async function submitGroupedCreation(prefix) {
  const entry = creationAllocation.get(prefix);
  if (!entry?.plan || entry.busy || entry.closed) return null;
  const body = creationAllocationBody(prefix);
  if (JSON.stringify(body) !== entry.serialized) {
    queueCreationGroupPreview(prefix);
    return null;
  }
  entry.busy = true;
  const setup = $("#" + prefix + "GroupSetup");
  setup.inert = true;
  renderCreationAllocationPreview(prefix);
  try {
    const result = await api(creationAllocationEndpoints[prefix], { method: "POST", body: JSON.stringify({
      ...body, request_id: entry.requestId, preview_token: entry.plan.preview_token,
    }) });
    entry.closed = true;
    return result;
  } catch (error) {
    if (error.status === 409) {
      entry.plan = null;
      entry.retry = true;
      entry.error = taskAllocationPreviewError(error);
    }
    throw error;
  } finally {
    entry.busy = false;
    setup.inert = false;
    renderCreationAllocationPreview(prefix);
  }
}

function creationAllocationError(error) {
  const lines = typeof error.message === "string" ? error.message.split(" / ") : [];
  return lines.length === 2 ? uiText(lines[0], lines[1])
    : uiText(error.message || "无法预览分配，请检查任务配置。", "Unable to plan the allocation. Check the task settings.");
}
