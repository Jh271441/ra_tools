function renderIntentLabels() {
  const intent = state.intentLabeling;
  const currentOverride = intentOverride();
  const effective = intentEffective();
  const selectedCount = intentSelectedTimepoints().length;
  document.querySelectorAll("[data-intent-axis-section]").forEach((node) => {
    node.hidden = !intentAxisEnabled(node.dataset.intentAxisSection);
  });
  document.querySelectorAll("[data-intent-aggregate-axis], [data-intent-frame-axis]").forEach((button) => {
    const axis = button.dataset.intentAggregateAxis || button.dataset.intentFrameAxis;
    button.closest(".intent-label-grid").hidden = !intentAxisEnabled(axis);
  });
  $("#intentFrameTitle").textContent = selectedCount > 1 ? "多个帧标签" : "当前帧标签";
  document.querySelectorAll("[data-intent-aggregate-axis]").forEach((button) => {
    const value = button.dataset.value;
    const selected = button.dataset.intentAggregateAxis === "routing"
      ? intent.aggregate.routing === value
      : intent.aggregate.laneChange === value;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  });
  document.querySelectorAll("[data-intent-frame-axis]").forEach((button) => {
    const value = button.dataset.value;
    const selected = button.dataset.intentFrameAxis === "routing"
      ? effective.routing === value
      : effective.laneChange === value;
    button.classList.toggle("active", selected);
    button.classList.toggle("is-override", Boolean(
      selected && (button.dataset.intentFrameAxis === "routing"
        ? currentOverride?.routing_intent
        : currentOverride?.lane_change_intent)
    ));
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  });
  $("#intentFrameSource").textContent = selectedCount > 1
    ? `已选 ${selectedCount} 帧，数字键应用到全部选中帧`
    : (currentOverride ? "当前帧已单独修改" : "当前帧来自批量预填");
  $("#intentRestoreBatchPrefillText").textContent = selectedCount > 1
    ? `选中 ${selectedCount} 帧恢复批量预填`
    : "当前帧恢复批量预填";
  const total = intent.caseData?.timepoints?.length || 0;
  const overrideCount = Object.keys(intent.overrides).length;
  $("#intentCoverage").textContent = `${Math.max(0, total - overrideCount)} 帧使用批量预填 · ${overrideCount} 帧单独修改`;
}

function intentLocalFrameCounts() {
  const routing = {};
  const laneChange = {};
  (state.intentLabeling.caseData?.timepoints || []).forEach((item) => {
    const effective = intentEffective(item);
    if (effective.routing) routing[effective.routing] = (routing[effective.routing] || 0) + 1;
    if (effective.laneChange) laneChange[effective.laneChange] = (laneChange[effective.laneChange] || 0) + 1;
  });
  return { routing, lane_change: laneChange };
}

function intentContributorIsLabeled(item) {
  return Boolean(
    item.labeled
    || item.routing_default
    || item.lane_change_default
    || (item.overrides || []).length
  );
}

function intentContributorStatus(item) {
  return intentContributorIsLabeled(item) ? "已标注" : "待标注";
}

function renderIntentCollaboration() {
  const active = intentActiveTimepoint();
  const collaboration = state.intentLabeling.caseData?.collaboration || {};
  const discussionButton = $("#intentOpenComments");
  if (discussionButton) {
    discussionButton.dataset.intentDatasetId = state.intentLabeling.datasetId || "";
    discussionButton.dataset.intentCaseId = state.intentLabeling.caseId || "";
  }
  const contributors = [...(collaboration.contributors || [])].sort((left, right) => {
    if (Boolean(left.is_current) !== Boolean(right.is_current)) return left.is_current ? -1 : 1;
    const leftLabeled = intentContributorIsLabeled(left);
    const rightLabeled = intentContributorIsLabeled(right);
    if (leftLabeled !== rightLabeled) return leftLabeled ? -1 : 1;
    return String(left.username || "").localeCompare(String(right.username || ""));
  });
  const contributorList = $("#intentContributorList");
  const revealButton = $("#intentToggleReveal");
  const canReveal = Boolean(state.session.is_admin && collaboration.blind_active);
  if (revealButton) {
    revealButton.hidden = !canReveal;
    revealButton.textContent = collaboration.answers_revealed ? "恢复盲态" : "管理员解盲";
  }
  const canDelete = Boolean(state.session.can_annotate_intent && state.intentLabeling.revisionId);
  if (contributorList) {
    contributorList.innerHTML = contributors.length ? contributors.map((item) => {
      const labeled = intentContributorIsLabeled(item);
      const name = `<strong>${escapeHtml(item.username)}${item.is_current ? "（我）" : ""}</strong>`;
      if (!item.revealed || !labeled) {
        return `<article class="intent-contributor${item.is_current ? " is-current" : ""}">${name}<span class="intent-contributor-status ${labeled ? "is-labeled" : "is-pending"}">${intentContributorStatus(item)}</span></article>`;
      }
      const frameOverride = (item.overrides || []).find((entry) => entry.timepoint_id === active?.id) || {};
      const routingValue = frameOverride.routing_intent || item.routing_default;
      const laneChangeValue = frameOverride.lane_change_intent || item.lane_change_default;
      const menu = item.is_current && canDelete
        ? `<div class="intent-contributor-menu">
            <button class="intent-contributor-menu-trigger" type="button" data-intent-contributor-menu aria-haspopup="menu" aria-expanded="false" title="更多">⋯</button>
            <div class="intent-contributor-menu-panel" hidden>
              <button type="button" data-intent-delete-mine>删除标注</button>
            </div>
          </div>`
        : "";
      const routingChip = intentAxisEnabled("routing")
        ? intentChipMarkup(INTENT_ROUTING_LABELS[routingValue] || "Routing 待填", { pending: !routingValue, value: routingValue })
        : "";
      const laneChip = intentAxisEnabled("laneChange")
        ? intentChipMarkup(INTENT_LANE_LABELS[laneChangeValue] || "变道待填", { pending: !laneChangeValue, value: laneChangeValue })
        : "";
      return `<article class="intent-contributor is-revealed${item.is_current ? " is-current" : ""}">
        ${name}
        <div class="intent-contributor-labels">${routingChip}${laneChip}</div>
        ${menu}
      </article>`;
    }).join("") : "<p>尚无标注记录</p>";
  }
  const comments = collaboration.comments || [];
  if ($("#intentCommentCount")) $("#intentCommentCount").textContent = `${comments.length} 条`;
  if (discussionButton) {
    discussionButton.innerHTML = comments.length
      ? `打开讨论 · ${comments.length} <kbd>D</kbd>`
      : "打开讨论 <kbd>D</kbd>";
  }
}

async function deleteMyIntentLabel() {
  const intent = state.intentLabeling;
  if (!state.session.can_annotate_intent || !intent.caseId || !intent.revisionId) return;
  if (!await confirmIntentLabelDeletion({
    username: state.session.username,
    caseId: intent.caseId,
    own: true,
  })) return;
  await intentFlushSave();
  const revisionId = intent.revisionId;
  if (!revisionId) return;
  const result = await api(
    `/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases/${encodeURIComponent(intent.caseId)}/labels?expected_revision_id=${encodeURIComponent(revisionId)}`,
    { method: "DELETE" }
  );
  acknowledgeLocalChange(result);
  intent.revisionId = null;
  intent.aggregate = { routing: "", laneChange: "" };
  intent.overrides = {};
  intent.undoStack = [];
  intent.dirty = false;
  intent.editVersion = 0;
  intent.autoAdvanceOnSave = false;
  intent.autoAdvanceTimepointId = "";
  if (intent.caseData) {
    intent.caseData.labels = result.labels;
    intent.caseData.status = "unlabeled";
    const username = String(state.session.username || "").toLowerCase();
    intent.caseData.collaboration ||= { contributors: [], comments: [] };
    const contributors = intent.caseData.collaboration.contributors ||= [];
    const current = contributors.find((item) => item.is_current || item.username === username);
    if (current) {
      Object.assign(current, {
        username,
        is_current: true,
        labeled: false,
        completed: false,
        revealed: true,
        routing_default: "",
        lane_change_default: "",
        overrides: [],
        frame_counts: {},
        updated_at: "",
        version: 0,
      });
    }
  }
  intentSetSaveState("尚未标注", "");
  updateIntentTimelineState({ scroll: false });
  renderIntentLabels();
  renderIntentCollaboration();
  showToast("当前标注已删除，历史版本与审计记录已保留。", false);
}

async function toggleIntentAnswerReveal() {
  const intent = state.intentLabeling;
  if (!state.session.is_admin || !intent.caseId) return;
  await intentFlushSave();
  intent.adminRevealAnswers = !intent.adminRevealAnswers;
  const params = intentAssigneeSearchParams();
  if (intent.adminRevealAnswers) params.set("reveal_answers", "true");
  try {
    const data = await api(intentApiUrl(`/api/intent-datasets/${encodeURIComponent(intent.datasetId)}/cases/${encodeURIComponent(intent.caseId)}`, params));
    if (intent.caseId !== data.case_id) return;
    intent.caseData.collaboration = data.collaboration;
    renderIntentCollaboration();
  } catch (error) {
    intent.adminRevealAnswers = !intent.adminRevealAnswers;
    throw error;
  }
}

function openIntentComments({ focusCommentId = 0 } = {}) {
  const intent = state.intentLabeling;
  const issueId = intent.caseData?.issue_id || intent.caseId;
  if (!issueId || typeof openAnalysisDiscussion !== "function") return;
  const discussionButton = $("#intentOpenComments");
  if (discussionButton) {
    discussionButton.dataset.intentDatasetId = intent.datasetId;
    discussionButton.dataset.intentCaseId = intent.caseId;
  }
  return openAnalysisDiscussion(issueId, {
    source: "intent",
    intentDatasetId: intent.datasetId,
    intentCaseId: intent.caseId,
    focusCommentId,
  });
}

function renderIntentCase({ deferTimelineThumbnails = false } = {}) {
  const intent = state.intentLabeling;
  const data = intent.caseData;
  renderIntentTopbarDatasetPicker(intent.selectedDatasetIds);
  if (!data) return;
  $("#intentCaseInput").value = data.issue_id;
  $("#intentPreviousCase").disabled = !(data.previous_case?.case_id || data.previous_case_id);
  $("#intentNextCase").disabled = !(data.next_case?.case_id || data.next_case_id);
  const caseOrdinal = $("#intentCaseOrdinalInput");
  if (caseOrdinal) {
    caseOrdinal.value = String(data.ordinal || "");
    caseOrdinal.max = String(Math.max(1, data.case_count || 0));
  }
  if ($("#intentCaseCount")) $("#intentCaseCount").textContent = String(data.case_count || "—");
  updateIntentFrameNavigation();
  const heroReady = renderIntentHero();
  renderIntentTimeline({ loadThumbnails: !deferTimelineThumbnails });
  renderIntentLabels();
  renderIntentCollaboration();
  if (deferTimelineThumbnails) {
    const renderedCase = data;
    heroReady.finally(() => {
      window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
        if (state.intentLabeling.caseData === renderedCase) activateIntentTimelineThumbnails();
      }));
    });
  }
}
