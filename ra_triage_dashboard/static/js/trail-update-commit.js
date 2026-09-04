function trailUpdateProgressStageIndex(key) {
  const index = TRAIL_UPDATE_PROGRESS_STAGES.findIndex((item) => item.key === key);
  return index >= 0 ? index : 0;
}

function trailUpdateProgressSetStage(key, detail = "") {
  const index = trailUpdateProgressStageIndex(key);
  const progress = state.trailUpdate?.progress;
  if (progress) {
    progress.stage = key;
    progress.stageIndex = index;
    progress.detail = detail;
  }
  const dialog = $("#trailUpdateProgressDialog");
  if (!dialog) return;
  dialog.dataset.stage = key;
  const bar = $("#trailUpdateProgressBar");
  if (bar) {
    const percent = key === "done" ? 100 : Math.max(10, Math.round((index / (TRAIL_UPDATE_PROGRESS_STAGES.length - 1)) * 86));
    bar.style.width = `${percent}%`;
    bar.parentElement?.setAttribute("aria-valuenow", String(percent));
  }
  dialog.querySelectorAll("[data-trail-progress-stage]").forEach((node, nodeIndex) => {
    const active = nodeIndex === index;
    const complete = nodeIndex < index || key === "done";
    node.classList.toggle("is-active", active && key !== "done");
    node.classList.toggle("is-complete", complete);
    node.classList.toggle("is-pending", !active && !complete);
    node.setAttribute("aria-current", active ? "step" : "false");
  });
  const title = $("#trailUpdateProgressTitle");
  const message = $("#trailUpdateProgressMessage");
  if (title) title.textContent = key === "done"
    ? uiText("Trail 更新完成", "Trail update complete")
    : uiText("正在提交到 Trail", "Submitting to Trail");
  if (message) {
    message.textContent = detail || (key === "request"
      ? uiText("服务端正在分批写入；完成后会统一回读，请不要重复提交。", "The server is writing in batches; it will read back once complete. Do not submit again.")
      : uiText(TRAIL_UPDATE_PROGRESS_STAGES[index]?.zh || "正在处理…", TRAIL_UPDATE_PROGRESS_STAGES[index]?.en || "Working…"));
  }
}

function trailUpdateProgressElapsed() {
  const elapsed = $("#trailUpdateProgressElapsed");
  const startedAt = Number(state.trailUpdate?.progress?.startedAt || 0);
  if (!elapsed || !startedAt) return;
  const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  elapsed.textContent = uiText(`已用时 ${seconds}s`, `${seconds}s elapsed`);
}

function openTrailUpdateProgress({ mode = "review", total = 0 } = {}) {
  const dialog = $("#trailUpdateProgressDialog");
  if (!dialog || typeof dialog.showModal !== "function") return;
  window.clearInterval(trailUpdateProgressTimer);
  window.clearTimeout(trailUpdateProgressCloseTimer);
  state.trailUpdate.progress = {
    active: true,
    mode,
    total: Number(total || 0),
    startedAt: Date.now(),
    stage: "prepare",
    stageIndex: 0,
  };
  dialog.dataset.mode = mode;
  dialog.dataset.running = "true";
  const count = $("#trailUpdateProgressCount");
  if (count) count.textContent = total ? uiText(`${total} 个 Issue`, `${total} Issues`) : "";
  const close = $("#trailUpdateProgressClose");
  if (close) close.hidden = true;
  const bar = $("#trailUpdateProgressBar");
  if (bar) bar.style.width = "10%";
  const track = bar?.parentElement;
  track?.classList.add("is-running");
  trailUpdateProgressSetStage("prepare", uiText("已确认预览指纹，准备提交。", "Preview fingerprint confirmed; preparing commit."));
  trailUpdateProgressTimer = window.setInterval(trailUpdateProgressElapsed, 500);
  trailUpdateProgressElapsed();
  if (!dialog.open) dialog.showModal();
}

function finishTrailUpdateProgress({ ok = false, warning = false, message = "" } = {}) {
  const dialog = $("#trailUpdateProgressDialog");
  const progress = state.trailUpdate?.progress;
  if (progress) {
    progress.active = false;
    progress.finishedAt = Date.now();
    progress.ok = Boolean(ok);
  }
  window.clearInterval(trailUpdateProgressTimer);
  trailUpdateProgressTimer = null;
  const bar = $("#trailUpdateProgressBar");
  bar?.parentElement?.classList.remove("is-running");
  if (bar) {
    bar.style.width = ok ? "100%" : "34%";
    bar.parentElement?.setAttribute("aria-valuenow", ok ? "100" : "34");
  }
  if (dialog) {
    dialog.dataset.running = "false";
    dialog.dataset.result = ok ? (warning ? "warning" : "success") : "error";
    trailUpdateProgressSetStage(ok ? "done" : "request", message || (ok
      ? uiText("字段和回读结果已返回。", "Field and readback results are ready.")
      : uiText("提交失败，请关闭弹窗查看错误信息。", "The commit failed; close this dialog to inspect the error.")));
    const title = $("#trailUpdateProgressTitle");
    if (title) {
      title.textContent = !ok
        ? uiText("Trail 更新失败", "Trail update failed")
        : warning
          ? uiText("Trail 更新完成（看板同步提示）", "Trail update complete (dashboard sync notice)")
          : uiText("Trail 更新完成", "Trail update complete");
    }
    const close = $("#trailUpdateProgressClose");
    if (close) close.hidden = false;
    if (ok && !warning) {
      trailUpdateProgressCloseTimer = window.setTimeout(() => {
        if (dialog.open) dialog.close();
      }, 900);
    }
  }
}

function closeTrailUpdateProgress() {
  window.clearInterval(trailUpdateProgressTimer);
  window.clearTimeout(trailUpdateProgressCloseTimer);
  trailUpdateProgressTimer = null;
  trailUpdateProgressCloseTimer = null;
  const dialog = $("#trailUpdateProgressDialog");
  if (dialog?.open) dialog.close();
  if (state.trailUpdate?.progress) state.trailUpdate.progress.active = false;
}

let trailUpdateConfirmResolver = null;

function trailUpdateConfirmClose(confirmed = false) {
  const dialog = $("#trailUpdateConfirmDialog");
  const resolve = trailUpdateConfirmResolver;
  trailUpdateConfirmResolver = null;
  if (dialog?.open) dialog.close();
  if (resolve) resolve(Boolean(confirmed));
}

function trailUpdateConfirmPatch(item, infoField) {
  const updates = item?.field_updates;
  if (updates && typeof updates === "object" && updates[infoField] && typeof updates[infoField] === "object") {
    return updates[infoField];
  }
  const update = item?.field_update || {};
  if (update.patch && typeof update.patch === "object") return update.patch;
  if (item?.target?.patch && typeof item.target.patch === "object") return item.target.patch;
  return {};
}

function trailUpdateConfirmCompact(value) {
  try {
    const text = JSON.stringify(value ?? {}, (_key, entry) => entry === undefined ? null : entry);
    return text && text !== "{}" ? text : "{}";
  } catch (_error) {
    return "{}";
  }
}

function trailUpdateConfirmSetExpanded(expanded = false) {
  const dialog = $("#trailUpdateConfirmDialog");
  const details = [...(dialog?.querySelectorAll(".trail-update-confirm-item") || [])];
  details.forEach((item) => {
    item.open = Boolean(expanded);
  });
  const button = $("#trailUpdateConfirmExpand");
  if (!button) return;
  button.hidden = details.length === 0;
  button.dataset.expanded = expanded ? "true" : "false";
  button.innerHTML = expanded
    ? '<span class="ui-lang-zh">收起全部</span><span class="ui-lang-en">Collapse all</span>'
    : '<span class="ui-lang-zh">展开全部</span><span class="ui-lang-en">Expand all</span>';
}

function openTrailUpdateConfirm({ mode = "review", data = {} } = {}) {
  const dialog = $("#trailUpdateConfirmDialog");
  if (!dialog || typeof dialog.showModal !== "function") {
    showToast(uiText("确认弹窗不可用，已取消写入。", "The confirmation dialog is unavailable; write cancelled."), true);
    return Promise.resolve(false);
  }
  if (trailUpdateConfirmResolver) trailUpdateConfirmClose(false);
  const directMode = mode === "direct_issue_ids" || data?.mode === "direct_issue_ids";
  const allItems = Array.isArray(data?.items) ? data.items : [];
  // The server rechecks this state immediately before the write, but make the
  // confirmation surface match the operation: only rows whose dashboard
  // marker *or* exclusion note differs from Trail will be submitted.
  const items = allItems.filter((item) => item?.trail_update_status === "pending");
  const skippedSyncedCount = Math.max(0, allItems.length - items.length);
  const infoField = String(
    data?.target_field
      || (data?.write_mode === "info_only" ? data?.target_fields?.[0] : data?.target_fields?.[1])
      || "ra_stuck_auto_result_info"
  );
  const targetSpec = trailUpdateTargetSpec(data);
  const resultField = String(data?.model_result_field || "ra_stuck_auto_result");
  const infoOnly = data?.write_mode === "info_only" || directMode;
  const count = Number(data?.pending_count ?? items.length);
  const run = data?.selected_run || {};
  const runLabel = directMode
    ? uiText("Issue ID 屏蔽", "Shield by Issue ID")
    : String(run.name || run.id || uiText("全部 Model Runs", "All model Runs"));
  const baselineLabel = Array.isArray(data?.baselines) && data.baselines.length
    ? data.baselines.join(" + ")
    : uiText("当前数据集", "Selected dataset");
  const digest = String(data?.payload_sha256 || "");

  const subtitle = $("#trailUpdateConfirmSubtitle");
  if (subtitle) subtitle.textContent = uiText(
    directMode ? "请核对要屏蔽的 Issue 和 info 标记。" : "请核对本次即将写入的 Issue、字段和预览指纹。",
    directMode ? "Review the Issues and info marker before shielding." : "Review the Issues, fields, and preview fingerprint before committing."
  );
  const bannerTitle = $("#trailUpdateConfirmBannerTitle");
  const bannerText = $("#trailUpdateConfirmBannerText");
  if (bannerTitle) bannerTitle.textContent = infoOnly
    ? uiText(`仅写 ${targetSpec.fullPath}`, `Info only · ${targetSpec.fullPath}`)
    : uiText(`写入 ${resultField} + ${targetSpec.fullPath}`, `Write ${resultField} + ${targetSpec.fullPath}`);
  if (bannerText) bannerText.textContent = infoOnly
    ? uiText(
      directMode
        ? "模型 label 保持不变；info 使用 deep_merge；Trail 回读成功后同步判错复核“应该排除”。"
        : "模型 label 保持不变；info 使用 deep_merge。",
      directMode
        ? "Model label stays unchanged; info is deep-merged; after Trail readback, Review ‘Exclude’ is synchronized."
        : "Model label stays unchanged; info is deep-merged."
    )
    : uiText("模型 label 和 info 将按预览写入。", "Model label and info will be written as previewed.");

  const summary = $("#trailUpdateConfirmSummary");
  if (summary) {
    const cards = [
      [uiText("提交模式", "Mode"), directMode ? uiText("Issue ID 屏蔽", "Issue shielding") : uiText("Review 排除汇总", "Review summary")],
      [uiText("Issue 数量", "Issues"), String(count)],
      [directMode ? uiText("目标字段", "Target field") : uiText("Run / 数据集", "Run / dataset"), directMode ? targetSpec.fullPath : `${runLabel} · ${baselineLabel}`],
    ];
    summary.innerHTML = cards.map(([label, value]) => `<div><small>${escapeHtml(label)}</small><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`).join("");
  }

  const list = $("#trailUpdateConfirmList");
  const listCount = $("#trailUpdateConfirmListCount");
  const shownItems = items.slice(0, 12);
  if (listCount) listCount.textContent = uiText(
    `${count > shownItems.length ? `共 ${count} 条，展示前 ${shownItems.length} 条` : `共 ${count} 条`}${skippedSyncedCount ? `；已同步跳过 ${skippedSyncedCount} 条` : ""}`,
    `${count > shownItems.length ? `${count} total · first ${shownItems.length} shown` : `${count} item(s)`}${skippedSyncedCount ? `; ${skippedSyncedCount} synced item(s) skipped` : ""}`
  );
  if (list) {
    list.innerHTML = shownItems.length
      ? shownItems.map((item) => {
        const issueId = String(item?.issue_id || "—");
        const currentLabel = directMode
          ? (item?.current_should_exclude ? uiText("已屏蔽", "Already shielded") : uiText("未屏蔽", "Not shielded"))
          : String(item?.model?.label || item?.review?.status || uiText("排除候选", "Excluded candidate"));
        const patch = trailUpdateConfirmCompact(trailUpdateConfirmPatch(item, infoField));
        const clippedPatch = patch.length > 420 ? `${patch.slice(0, 417)}…` : patch;
        const sourceMarkup = directMode ? historicalExclusionSourceMarkup(item?.source) : "";
        return `<details class="trail-update-confirm-item"><summary><div><strong>${escapeHtml(issueId)}</strong><small>${escapeHtml(currentLabel)}</small></div><div><code title="${escapeHtml(patch)}">${escapeHtml(`${infoField} = ${clippedPatch}`)}</code><small>${escapeHtml(uiText("点击展开完整 patch · deep_merge · label 不变", "Click to expand full patch · deep_merge · label unchanged"))}</small></div></summary><div class="trail-update-confirm-item-details"><small>${escapeHtml(uiText("完整字段 patch", "Full field patch"))}</small><pre>${escapeHtml(`${infoField} = ${patch}`)}</pre>${sourceMarkup}</div></details>`;
      }).join("")
      : `<div class="trail-update-confirm-empty">${escapeHtml(uiText("没有可提交的 Issue。", "No Issues are ready to commit."))}</div>`;
    trailUpdateConfirmSetExpanded(false);
  }

  const note = $("#trailUpdateConfirmNote");
  if (note) note.textContent = uiText(
    `${infoOnly ? `仅更新 ${targetSpec.fullPath}，不改模型 label。${directMode ? ` Trail 回读成功后同步判错复核“应该排除”。` : ""}` : `将更新 ${resultField} 和 ${targetSpec.fullPath}。`}提交前会再次校验预览指纹${digest ? `（${digest.slice(0, 12)}…）` : ""}。`,
    `${infoOnly ? `Only ${targetSpec.fullPath} will be updated; model labels stay unchanged.${directMode ? " Review ‘Exclude’ will be synchronized after Trail readback. " : " "}` : `Both ${resultField} and ${targetSpec.fullPath} will be updated. `}The preview fingerprint will be checked again before commit${digest ? ` (${digest.slice(0, 12)}…)` : ""}.`
  );
  dialog.dataset.confirmMode = directMode ? "direct_issue_ids" : "review";
  return new Promise((resolve) => {
    trailUpdateConfirmResolver = resolve;
    dialog.showModal();
  });
}

function renderTrailIssuePreview(data) {
  const items = Array.isArray(data?.items) ? data.items : [];
  const missing = Array.isArray(data?.missing_issue_ids) ? data.missing_issue_ids : [];
  const invalid = Array.isArray(data?.invalid_issue_ids) ? data.invalid_issue_ids : [];
  const capability = data?.trail_capability || {};
  setTrailAttributeCapability(data);
  const results = $("#trailUpdateIssueResults");
  if (results) results.hidden = false;
  $("#trailUpdateIssueCount").textContent = String(items.length);
  $("#trailUpdateIssueMissingCount").textContent = String(missing.length + invalid.length);
  $("#trailUpdateIssueSummary").textContent = uiText(
    `${data?.requested_issue_ids?.length || 0} 条请求；${items.length} 条可写`,
    `${data?.requested_issue_ids?.length || 0} requested; ${items.length} writable`
  );
  const targetSpec = renderTrailUpdateTargetField(data, "trailUpdateIssueField");
  const statusText = data?.write_status === "ready"
    ? uiText(`已生成屏蔽预览：${items.length} 条，可提交。`, `Shield preview ready: ${items.length} item(s); commit is available.`)
    : uiText(
      `已生成预览：${items.length} 条；${missing.length ? `未找到 ${missing.length} 条。` : ""}${capability.message || "当前不可写入 Trail"}`,
      `Preview ready: ${items.length} item(s); ${missing.length ? `${missing.length} missing. ` : ""}${capability.message || "Trail is not writable yet."}`
    );
  setTrailIssueStatus(statusText);
  const body = $("#trailUpdateIssueTableBody");
  if (!body) return;
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="6" class="trail-update-empty">${uiText("没有可写的 Issue，请检查 ID 和 Trail view。", "No writable Issues; check IDs and the Trail view.")}</td></tr>`;
    return;
  }
  body.innerHTML = items.map((item) => {
    const target = item.target || {};
    const patchPath = target.path || "ra_triage_dashboard.should_exclude";
    const currentState = item.current_should_exclude
      ? uiText("已屏蔽", "Shielded")
      : uiText("未屏蔽", "Not shielded");
    const shortPath = patchPath.split(".").filter(Boolean).pop() || patchPath;
    const release = String(
      item.baseline_id
        || (typeof baselineLabelForScope === "function" ? baselineLabelForScope(item.baseline_scope) : "")
        || item.baseline_scope
        || "—"
    );
    const comment = String(item.comment || "").trim();
    const commentHint = item.comment_defaulted
      ? uiText("自动说明 · 写入 info.ra_triage_dashboard.should_exclude_comment", "Auto note · saved in info.ra_triage_dashboard.should_exclude_comment")
      : uiText("写入 info.ra_triage_dashboard.should_exclude_comment", "Saved in info.ra_triage_dashboard.should_exclude_comment");
    const dashboardPatch = target.patch?.ra_triage_dashboard || {};
    const commentPatch = String(dashboardPatch.should_exclude_comment || "").trim();
    const infoPreview = [
      `${shortPath} = true`,
      commentPatch ? `should_exclude_comment = ${commentPatch}` : "",
    ].filter(Boolean).join("; ");
    return `<tr>
      <td data-label="Issue"><strong class="trail-update-issue">${escapeHtml(item.issue_id || "—")}</strong></td>
      <td data-label="数据集版本" class="trail-update-release-cell" title="${escapeHtml(item.baseline_scope || release)}"><strong>${escapeHtml(release)}</strong></td>
      <td data-label="当前模型 label">${labelBadge(item.current_label, "未输出")}</td>
      <td data-label="当前屏蔽状态"><span class="trail-update-state-badge ${item.current_should_exclude ? "is-on" : ""}">${escapeHtml(currentState)}</span></td>
      <td data-label="预计写入 info" class="trail-update-info-cell"><strong title="${escapeHtml(targetSpec.fullPath)}">${escapeHtml(shortPath)}</strong><small>${uiText("info-only · label 不变", "info-only · label unchanged")}</small><code title="${escapeHtml(infoPreview)}">${escapeHtml(infoPreview)}</code></td>
      <td data-label="Comment"><div class="trail-update-comment" title="${escapeHtml(comment)}">${escapeHtml(comment || "—")}</div>${historicalExclusionSourceMarkup(item.source)}<small>${commentHint}</small></td>
    </tr>`;
  }).join("");
}

async function loadTrailIssuePreview() {
  const parsed = parseTrailIssueIds();
  if (parsed.invalid.length || !parsed.ids.length) {
    clearTrailIssuePreview(uiText("请先填写合法的 Issue ID（每行可填多个）。", "Enter valid Issue IDs first (multiple per row are supported)."));
    return null;
  }
  const requestSeq = ++state.trailUpdate.directRequestSeq;
  setTrailIssueStatus(uiText("正在检查 Issue 和 Trail 字段…", "Checking Issues and Trail fields…"));
  $("#trailUpdateIssuePreviewButton")?.toggleAttribute("disabled", true);
  try {
    const data = await api("/api/trail-attribute-update/issue-preview", {
      method: "POST",
      allowReadOnlyMutation: true,
      body: JSON.stringify({ entries: parsed.entries }),
    });
    if (requestSeq !== state.trailUpdate.directRequestSeq) return data;
    state.trailUpdate.directData = data;
    renderTrailIssuePreview(data);
    syncTrailIssueActions(data);
    return data;
  } catch (error) {
    if (requestSeq === state.trailUpdate.directRequestSeq) {
      setTrailIssueStatus(error?.message || uiText("屏蔽预览失败。", "Shield preview failed."));
    }
    throw error;
  } finally {
    if (requestSeq === state.trailUpdate.directRequestSeq) $("#trailUpdateIssuePreviewButton")?.toggleAttribute("disabled", false);
  }
}

async function commitTrailIssueExclusion() {
  const data = state.trailUpdate?.directData;
  if (!trailUpdateWriteReady(data)) return;
  const ids = Array.isArray(data.requested_issue_ids) ? data.requested_issue_ids : [];
  const entries = Array.isArray(data.requested_entries)
    ? data.requested_entries
    : ids.map((issueId) => ({ issue_id: issueId, comment: data.comment || "" }));
  const pendingCount = Number(data?.pending_count ?? data?.items?.filter(
    (item) => item?.trail_update_status === "pending"
  ).length ?? ids.length);
  if (!await openTrailUpdateConfirm({ mode: "direct_issue_ids", data })) return;
  const button = $("#trailUpdateIssueCommitButton");
  button?.toggleAttribute("disabled", true);
  setTrailIssueStatus(uiText("正在写入 Trail 字段和 info 排除说明…", "Writing Trail fields and info notes…"));
  openTrailUpdateProgress({ mode: "issue", total: pendingCount });
  trailUpdateProgressSetStage("request");
  try {
    const result = await api("/api/trail-attribute-update/issue-commit", {
      method: "POST",
      body: JSON.stringify({
        confirm: true,
        entries,
        payload_sha256: data.payload_sha256,
      }),
    });
    const stats = result?.stats || {};
    const readback = result?.readback || {};
    const localReview = result?.local_review || {};
    const notificationQueued = Number(localReview.notification_queued_count || 0);
    const trailOk = typeof result?.trail_ok === "boolean" ? result.trail_ok : Boolean(result?.ok);
    const outsideDashboard = Array.isArray(localReview.not_in_dashboard_issue_ids)
      ? localReview.not_in_dashboard_issue_ids
      : [];
    const localFailures = Array.isArray(localReview.failed_issue_ids)
      ? localReview.failed_issue_ids
      : [];
    const readbackText = uiText(
      `回读 ${readback.verified_count || 0}/${readback.checked_count || 0}`,
      `read back ${readback.verified_count || 0}/${readback.checked_count || 0}`
    );
    const localMarked = Number(localReview.marked_count || 0) + Number(localReview.already_excluded_count || 0);
    const localTargetCount = Math.max(0, Number(localReview.requested_count || 0) - outsideDashboard.length);
    const localReviewText = outsideDashboard.length
      ? uiText(
        `看板“应该排除” ${localMarked}/${localTargetCount}；${outsideDashboard.length} 条不在当前看板`,
        `Review “Exclude” ${localMarked}/${localTargetCount}; ${outsideDashboard.length} outside this dashboard`
      )
      : uiText(
        `看板“应该排除” ${localMarked}/${localReview.requested_count || 0}`,
        `Review “Exclude” ${localMarked}/${localReview.requested_count || 0}`
      );
    const localReviewWithFailures = localFailures.length
      ? `${localReviewText}${uiText(`；本地标记失败 ${localFailures.length} 条`, `; ${localFailures.length} local mark failures`)}`
      : localReviewText;
    const progressMessage = uiText(
      `字段与 info 排除说明 ${stats.success_count || 0}/${stats.total || pendingCount}；${readbackText}；${localReviewWithFailures}。`,
      `Trail fields and info notes ${stats.success_count || 0}/${stats.total || pendingCount}; ${readbackText}; ${localReviewWithFailures}.`
    );
    const localSyncWarning = outsideDashboard.length > 0 || localFailures.length > 0;
    finishTrailUpdateProgress({ ok: trailOk, warning: trailOk && localSyncWarning, message: progressMessage });
    setTrailIssueStatus(uiText(
      `屏蔽完成：字段与 info 排除说明成功 ${stats.success_count || 0}，失败 ${stats.failed_count || 0}；${readbackText}；${localReviewWithFailures}。`,
      `Shield finished: fields and info notes ${stats.success_count || 0} succeeded / ${stats.failed_count || 0} failed; ${readbackText}; ${localReviewWithFailures}.`
    ));
    showToast(
      !trailOk
        ? uiText("Issue 屏蔽未完整写入，请查看 Trail 回读明细。", "Issue shielding is incomplete; inspect Trail readback.")
        : localSyncWarning
          ? outsideDashboard.length
            ? uiText(`Trail 已完成；${outsideDashboard.length} 条不在当前看板，未创建本地 Review 排除标记。`, `Trail completed; ${outsideDashboard.length} Issues are outside this dashboard and have no local Review mark.`)
            : uiText(`Trail 已完成；本地 Review 排除标记失败 ${localFailures.length} 条。`, `Trail completed; ${localFailures.length} local Review exclusion marks failed.`)
          : uiText(
              `Issue 屏蔽已提交，Trail 与判错复核排除标记均已更新${notificationQueued ? `；DChat 通知已排队 ${notificationQueued} 人` : ""}。`,
              `Issue shielding and Review exclusion marks were updated${notificationQueued ? `; ${notificationQueued} DChat notifications queued` : ""}.`
            ),
      !trailOk
    );
    if (readback.complete && Number(localReview.requested_count || 0) > 0) {
      void refreshTrailReviewAfterIssueCommit();
    }
    void loadTrailIssueHistory();
  } catch (error) {
    finishTrailUpdateProgress({ ok: false, message: error?.message || uiText("屏蔽失败，请稍后重试。", "Shielding failed; try again later.") });
    setTrailIssueStatus(error?.message || uiText("Issue 屏蔽失败。", "Issue shielding failed."));
    showToast(error?.message || uiText("Issue 屏蔽失败。", "Issue shielding failed."), true);
  } finally {
    syncTrailIssueActions(data);
  }
}

async function commitTrailAttributeUpdate() {
  const data = state.trailUpdate?.data;
  if (!trailUpdateWriteReady(data)) return;
  if (!await openTrailUpdateConfirm({ mode: "review", data })) return;
  const button = $("#trailUpdateCommitButton");
  button?.toggleAttribute("disabled", true);
  setTrailAttributeStatus(uiText("正在提交 Trail 属性…", "Committing Trail info…"));
  openTrailUpdateProgress({ mode: "review", total: Number(data?.pending_count ?? data?.count ?? data?.items?.length ?? 0) });
  trailUpdateProgressSetStage("request");
  try {
    const result = await api("/api/trail-attribute-update/commit", {
      method: "POST",
      body: JSON.stringify({
        confirm: true,
        model_run_id: data.selected_run?.id || state.trailUpdate.runId,
        baselines: data.baselines || [],
        payload_sha256: data.payload_sha256,
      }),
    });
    const stats = result?.stats || {};
    const readback = result?.readback || {};
    const readbackText = uiText(
      `回读 ${readback.verified_count || 0}/${readback.checked_count || 0}`,
      `read back ${readback.verified_count || 0}/${readback.checked_count || 0}`
    );
    const progressMessage = uiText(
      `字段与 info 排除说明 ${stats.success_count || 0}/${stats.total || data?.items?.length || 0}；${readbackText}。`,
      `Trail fields and info notes ${stats.success_count || 0}/${stats.total || data?.items?.length || 0}; ${readbackText}.`
    );
    finishTrailUpdateProgress({ ok: Boolean(result?.ok), message: progressMessage });
    setTrailAttributeStatus(uiText(
      `Trail 更新完成：字段与 info 排除说明成功 ${stats.success_count || 0}，失败 ${stats.failed_count || 0}；${readbackText}。`,
      `Trail update finished: fields and info notes ${stats.success_count || 0} succeeded / ${stats.failed_count || 0} failed; ${readbackText}.`
    ));
    showToast(
      result?.ok
        ? uiText("Trail 属性更新已完成并回读确认。", "Trail attributes updated and read back.")
        : uiText("Trail 属性更新部分失败，请查看回读和失败明细。", "Trail attribute update is incomplete; inspect readback and failures."),
      !result?.ok
    );
    if (result?.ok) {
      const runId = String(data?.selected_run?.id || state.trailUpdate?.runId || "").trim();
      void refreshTrailAttributeStatus({
        runId,
        previewKey: trailUpdatePreviewKey(runId),
        requestSeq: state.trailUpdate.requestSeq,
        force: true,
      }).catch(() => {});
    }
  } catch (error) {
    finishTrailUpdateProgress({ ok: false, message: error?.message || uiText("提交失败，请稍后重试。", "Commit failed; try again later.") });
    setTrailAttributeStatus(error?.message || uiText("Trail 更新失败。", "Trail update failed."));
    showToast(error?.message || uiText("Trail 更新失败。", "Trail update failed."), true);
  } finally {
    syncTrailAttributeActions(data);
  }
}

