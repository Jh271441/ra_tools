/* ra_triage_dashboard/static/js/review-attachments.js
 * Review screenshot selection, previews, and background upload lifecycle.
 * Loaded as a classic script before review-form.js.
 */

function imageFilesFromDataTransfer(dataTransfer) {
  if (!dataTransfer) return [];
  // Prefer FileList once; walking items too would add the same paste twice.
  let candidates = [...(dataTransfer.files || [])].filter((file) =>
    String(file.type || "").startsWith("image/")
  );
  if (!candidates.length) {
    candidates = [...(dataTransfer.items || [])]
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .map((item) => item.getAsFile())
      .filter(Boolean);
  }
  const seen = new Set();
  return candidates.filter((file) => {
    const key = `${file.type}|${file.size}|${file.lastModified}|${file.name || ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function bindReviewAttachmentInputs() {
  const pasteZone = $("#screenshotPasteZone");
  const screenshotInput = $("#reviewScreenshotInput");
  const screenshotBrowse = $("#reviewScreenshotBrowse");
  if (!pasteZone || !screenshotInput) return;

  const openScreenshotPicker = () => screenshotInput.click();
  screenshotBrowse?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    openScreenshotPicker();
  });
  pasteZone.addEventListener("click", () => {
    pasteZone.focus({ preventScroll: true });
  });
  pasteZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openScreenshotPicker();
    }
  });

  const acceptImagePasteOrDrop = (event, dataTransfer) => {
    const files = imageFilesFromDataTransfer(dataTransfer);
    if (!files.length) return false;
    event.preventDefault();
    event.stopPropagation();
    addPendingReviewImages(files);
    return true;
  };
  // Single form-level paste handler: the paste zone is inside the form.
  $("#annotationForm")?.addEventListener("paste", (event) => {
    const target = event.target;
    if (target?.closest?.(".combined-case-label-card")) return;
    if (
      target instanceof HTMLTextAreaElement ||
      (target instanceof HTMLInputElement &&
        !["checkbox", "radio", "file", "button", "submit"].includes(target.type))
    ) {
      const hasImage = [...(event.clipboardData?.items || [])].some(
        (item) => item.kind === "file" && item.type.startsWith("image/")
      );
      if (!hasImage) return;
    }
    acceptImagePasteOrDrop(event, event.clipboardData);
  });

  let dragDepth = 0;
  const setDragOver = (active) => pasteZone.classList.toggle("is-dragover", active);
  pasteZone.addEventListener("dragenter", (event) => {
    if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
    event.preventDefault();
    dragDepth += 1;
    setDragOver(true);
  });
  pasteZone.addEventListener("dragover", (event) => {
    if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    setDragOver(true);
  });
  pasteZone.addEventListener("dragleave", (event) => {
    if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
    event.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) setDragOver(false);
  });
  pasteZone.addEventListener("drop", (event) => {
    dragDepth = 0;
    setDragOver(false);
    if (!acceptImagePasteOrDrop(event, event.dataTransfer)) {
      event.preventDefault();
      showToast("请拖入 PNG / JPEG / WebP 图片。", true);
    }
  });
  screenshotInput.addEventListener("change", () => {
    addPendingReviewImages([...screenshotInput.files]);
    screenshotInput.value = "";
  });
}

function releasePreviewUrlLater(previewUrl) {
  window.setTimeout(() => URL.revokeObjectURL(previewUrl), 5000);
}

function clearPendingReviewImages() {
  const previewUrls = state.pendingReviewImages.map((item) => item.previewUrl);
  state.pendingReviewImages = [];
  renderPendingReviewImages();
  previewUrls.forEach(releasePreviewUrlLater);
}

function addPendingReviewImages(files) {
  const limits = state.config?.review_attachment_limits || {};
  const maxCount = Number(limits.max_count || 4);
  const maxBytes = Number(limits.max_bytes_each || 8 * 1024 * 1024);
  const maxTotalBytes = Number(limits.max_bytes_total || 24 * 1024 * 1024);
  const allowed = new Set(limits.media_types || ["image/png", "image/jpeg", "image/webp"]);
  let rejected = "";
  const previousCount = state.pendingReviewImages.length;
  files.forEach((file) => {
    if (state.pendingReviewImages.length >= maxCount) {
      rejected = `最多只能添加 ${maxCount} 张截图。`;
      return;
    }
    if (!allowed.has(file.type)) {
      rejected = "仅支持 PNG、JPEG 或 WebP 图片。";
      return;
    }
    if (file.size > maxBytes) {
      rejected = "单张截图不能超过 8 MB。";
      return;
    }
    const currentBytes = state.pendingReviewImages.reduce(
      (sum, item) => sum + item.file.size,
      0
    );
    if (currentBytes + file.size > maxTotalBytes) {
      rejected = "本次截图总大小不能超过 24 MB。";
      return;
    }
    state.pendingReviewImages.push({
      id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
      file,
      previewUrl: URL.createObjectURL(file),
    });
  });
  if (state.pendingReviewImages.length !== previousCount) state.reviewFormDirty = true;
  renderPendingReviewImages();
  if (rejected) showToast(rejected, true);
}

function reviewUploadTaskKey(issueId, payload) {
  return [
    String(issueId || ""),
    String(payload?.model_run_id || ""),
    String(payload?.work_split_id || ""),
  ].join("|");
}

function restoreFailedReviewUploadImages(issueId) {
  const prefix = `${String(issueId || "")}|`;
  const failed = [...state.backgroundReviewUploads.entries()].find(
    ([key, task]) => key.startsWith(prefix) && task?.failed
  );
  if (!failed || state.pendingReviewImages.length) return;
  const [key, task] = failed;
  state.backgroundReviewUploads.delete(key);
  const previewItems = Array.isArray(task.previewItems) && task.previewItems.length
    ? task.previewItems
    : task.files.map((file) => ({
        id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
        file,
        previewUrl: URL.createObjectURL(file),
      }));
  state.pendingReviewImages.push(...previewItems);
  task.previewItems = [];
  state.reviewFormDirty = true;
  renderPendingReviewImages();
}

function activeReviewUploadForIssue(issueId = state.selectedId) {
  const prefix = `${String(issueId || "")}|`;
  return [...state.backgroundReviewUploads.entries()].find(
    ([key, task]) => key.startsWith(prefix) && task && !task.failed
  )?.[1] || null;
}

function releaseReviewUploadPreviews(task) {
  (task?.previewItems || []).forEach((item) => releasePreviewUrlLater(item.previewUrl));
  if (task) task.previewItems = [];
}

function enqueueBackgroundReviewUpload(task) {
  const run = async () => {
    task.status = "uploading";
    if (state.selectedId === task.issueId) renderPendingReviewImages();
    try {
      const form = new FormData();
      form.append("payload", JSON.stringify(task.payload));
      task.files.forEach((file, index) => {
        form.append("attachments", file, file.name || `clipboard-${index + 1}.png`);
      });
      const result = await api(
        `/api/cases/${encodeURIComponent(task.issueId)}/annotations-with-attachments`,
        {
          method: "POST",
          body: form,
          headers: { "X-RA-Triage-Request": "review-v1" },
        }
      );
      acknowledgeLocalChange(result);
      state.backgroundReviewUploads.delete(task.key);
      const draft = readReviewDraft(
        task.issueId,
        task.payload.model_run_id,
        task.payload.work_split_id,
        task.payload.author
      );
      const draftChangedAfterQueue = Boolean(
        draft && Number(draft.saved_at || 0) > Number(task.queuedAt || 0)
      );
      if (!draftChangedAfterQueue) {
        clearReviewDraft(task.issueId, task.payload.model_run_id, task.payload.work_split_id, task.payload.author);
      }
      if (state.selectedId === task.issueId && result?.annotation) {
        state.reviewEditRunId = result.annotation.model_run_id || state.reviewEditRunId;
        state.reviewEditBaseAnnotationId = result.annotation.id || null;
        if (state.selectedCase?.issue_id === task.issueId) {
          state.selectedCase.annotations = [
            result.annotation,
            ...(state.selectedCase.annotations || []).filter(
              (item) => String(item.id) !== String(result.annotation.id)
            ),
          ];
          if (!draftChangedAfterQueue) state.reviewFormDirty = false;
          updateReviewHistory(state.selectedCase);
        }
      }
      releaseReviewUploadPreviews(task);
      if (state.selectedId === task.issueId) renderPendingReviewImages();
      showToast(uiText(
        `Issue ${task.issueId} 已保存 Review 和 ${task.files.length} 张截图。`,
        `Issue ${task.issueId}: Review and ${task.files.length} screenshot(s) saved.`,
      ));
      await refreshReviewAfterSave(task.navigationContext);
    } catch (error) {
      task.failed = true;
      if (state.selectedId === task.issueId) restoreFailedReviewUploadImages(task.issueId);
      showToast(uiText(
        `Issue ${task.issueId} 的截图后台上传失败，请重新按 Enter 重试。`,
        `Issue ${task.issueId}: background screenshot upload failed. Press Enter to retry.`,
      ), true);
    }
  };
  state.reviewUploadTail = state.reviewUploadTail.catch(() => {}).then(run);
}

function renderPendingReviewImages() {
  const target = $("#pendingScreenshotList");
  if (!target) return;
  const activeUpload = activeReviewUploadForIssue();
  if (!state.pendingReviewImages.length && !activeUpload) {
    target.innerHTML = "";
    return;
  }
  const uploadStatus = activeUpload?.status === "uploading"
    ? uiText(`正在后台保存 Review 和 ${activeUpload.files.length} 张截图`, `Saving Review and ${activeUpload.files.length} screenshot(s) in background`)
    : uiText(`等待后台保存 Review 和 ${activeUpload?.files.length || 0} 张截图`, `Waiting to save Review and ${activeUpload?.files.length || 0} screenshot(s)`);
  const uploadMarkup = activeUpload
    ? `<section class="review-upload-progress" role="status" aria-live="polite">
        <div class="review-upload-progress-copy">
          <span class="review-upload-spinner" aria-hidden="true"></span>
          <span><strong>${escapeHtml(uploadStatus)}</strong><small>${escapeHtml(uiText("可以继续切换 Issue；完成后截图会自动进入 Review 历史。", "You can switch Issues; screenshots will appear in Review history when saved."))}</small></span>
        </div>
        <div class="review-upload-thumbnails">${(activeUpload.previewItems || []).map((item) => `<div class="pending-screenshot is-uploading"><img src="${escapeHtml(item.previewUrl)}" alt="${escapeHtml(item.file.name || uiText("正在上传的截图", "Screenshot uploading"))}" /><span>${escapeHtml(uiText("上传中", "Uploading"))}</span></div>`).join("")}</div>
      </section>`
    : "";
  const pendingMarkup = state.pendingReviewImages
    .map(
      (item) => `<div class="pending-screenshot">
        <img src="${escapeHtml(item.previewUrl)}" alt="${escapeHtml(item.file.name || "待上传截图")}" />
        <button type="button" data-remove-screenshot="${escapeHtml(item.id)}" aria-label="移除截图">×</button>
      </div>`
    )
    .join("");
  target.innerHTML = uploadMarkup + pendingMarkup;
  target.querySelectorAll("[data-remove-screenshot]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = state.pendingReviewImages.findIndex(
        (item) => item.id === button.dataset.removeScreenshot
      );
      if (index < 0) return;
      const previewUrl = state.pendingReviewImages[index].previewUrl;
      state.pendingReviewImages.splice(index, 1);
      state.reviewFormDirty = true;
      renderPendingReviewImages();
      releasePreviewUrlLater(previewUrl);
    });
  });
}


// Case evidence is separate from Run-review screenshots and follows the same
// Issue / Run / explicit task / verified actor namespace as the text draft.
function caseRationaleImageKey(caseData = state.selectedCase) {
  return reviewDraftStorageKey(caseData?.issue_id, currentReviewRunId(caseData),
    String(state.reviewWorkSplitId || ""), reviewDraftReviewer(caseData));
}

function caseRationalePendingImages(caseData = state.selectedCase) {
  state.caseRationaleImages ||= new Map();
  return state.caseRationaleImages.get(caseRationaleImageKey(caseData)) || [];
}

function labelImageMarkup(items) {
  return (items || []).map((item) => {
    const url = withBase(`/api/labeling/attachments/${encodeURIComponent(item.id)}`);
    return `<a class="pending-screenshot" href="${escapeHtml(url)}" target="_blank" rel="noopener" title="${escapeHtml(item.original_name || uiText("查看标签图片", "View label image"))}"><img loading="lazy" src="${escapeHtml(url)}" alt="${escapeHtml(item.original_name || uiText("标签图片", "Label image"))}" /></a>`;
  }).join("");
}

function renderCaseRationaleImages(caseData = state.selectedCase) {
  const list = $("#caseRationaleImageList");
  if (!list || !caseData || state.selectedCase !== caseData) return;
  const context = state.combinedReviewContext;
  const saved = String(context?.issue?.issue_id || "") === String(caseData.issue_id)
    && state.combinedReviewLoad?.key === combinedReviewContextKey(caseData) ? context.case_attachments || [] : [];
  const items = caseRationalePendingImages(caseData);
  const upload = caseRationaleUploadTask(caseData);
  list.innerHTML = caseRationaleUploadMarkup(upload) + labelImageMarkup(saved) + items.map((item) => `<div class="pending-screenshot"><img src="${escapeHtml(item.previewUrl)}" alt="${escapeHtml(item.file.name || uiText("待上传标签图片", "Pending label image"))}" /><button type="button" ${upload?.imageItems.some((image) => image.id === item.id) ? "disabled" : ""} data-remove-case-image="${escapeHtml(item.id)}" aria-label="${escapeHtml(uiText("移除待上传图片", "Remove pending image"))}">×</button></div>`).join("");
  list.querySelector("[data-retry-case-upload]")?.addEventListener("click", () => enqueueCaseRationaleUpload(upload));
  list.querySelector("[data-refresh-case-upload]")?.addEventListener("click", async () => {
    try {
      await loadCombinedReviewContext(caseData);
      state.backgroundCaseUploads.delete(upload.key);
      renderCaseRationaleImages(caseData);
      renderCombinedReviewContextStatus();
    } catch (_) { /* Existing context status exposes its retry action. */ }
  });
  list.querySelectorAll("[data-remove-case-image]").forEach((button) => button.addEventListener("click", () => {
    const item = items.find((item) => item.id === button.dataset.removeCaseImage);
    if (!item) return;
    clearSavedCaseRationaleImages(caseRationaleImageKey(caseData), [item]);
    renderCaseRationaleImages(caseData);
  }));
}

function addCaseRationaleImages(files, caseData = state.selectedCase) {
  if (!hasDashboardWriteRole() || state.session?.read_only || state.selectedCase !== caseData) return;
  const limits = state.config?.review_attachment_limits || {};
  const items = caseRationalePendingImages(caseData);
  const allowed = new Set(limits.media_types || ["image/png", "image/jpeg", "image/webp"]);
  let rejected = false;
  for (const file of files) {
    if (!allowed.has(file.type) || file.size > Number(limits.max_bytes_each || 8388608)
        || items.length >= Number(limits.max_count || 4)
        || items.reduce((sum, item) => sum + item.file.size, 0) + file.size > Number(limits.max_bytes_total || 25165824)) {
      rejected = true;
      continue;
    }
    items.push({id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`, file, previewUrl: URL.createObjectURL(file)});
  }
  state.caseRationaleImages.set(caseRationaleImageKey(caseData), items);
  if (items.length) state.reviewFormDirty = true;
  renderCaseRationaleImages(caseData);
  if (rejected) showToast(uiText("仅支持 PNG/JPEG/WebP，最多 4 张，单张 8 MB、合计 24 MB。", "PNG/JPEG/WebP only; max 4 images, 8 MB each and 24 MB total."), true);
}

function clearSavedCaseRationaleImages(key, snapshot) {
  const ids = new Set(snapshot.map((item) => item.id));
  const existing = state.caseRationaleImages?.get(key) || [];
  const remaining = existing.filter((item) => !ids.has(item.id));
  if (remaining.length) state.caseRationaleImages.set(key, remaining);
  else state.caseRationaleImages?.delete(key);
  existing.filter((item) => ids.has(item.id)).forEach((item) => releasePreviewUrlLater(item.previewUrl));
}

function bindCaseRationaleImages(caseData) {
  const input = $("#caseRationaleImageInput"), zone = $("#caseRationalePasteZone");
  if (!input || !zone) return;
  $("#caseRationaleImageBrowse")?.addEventListener("click", () => input.click());
  input.addEventListener("change", () => { addCaseRationaleImages([...input.files], caseData); input.value = ""; });
  zone.addEventListener("keydown", (event) => {
    if (event.target === zone && ["Enter", " "].includes(event.key)) { event.preventDefault(); event.stopPropagation(); input.click(); }
  });
  const accept = (event, transfer) => {
    const files = imageFilesFromDataTransfer(transfer);
    if (!files.length) return;
    event.preventDefault(); event.stopPropagation(); addCaseRationaleImages(files, caseData);
  };
  $("#combinedCaseRationale")?.addEventListener("paste", (event) => accept(event, event.clipboardData));
  zone.addEventListener("paste", (event) => accept(event, event.clipboardData));
  zone.addEventListener("dragover", (event) => { event.preventDefault(); });
  zone.addEventListener("drop", (event) => { event.preventDefault(); event.stopPropagation(); accept(event, event.dataTransfer); });
  renderCaseRationaleImages(caseData);
}

async function submitCaseRationalePayload(issueId, action, payload, items, headers = {}) {
  if (!items.length) return api(`/api/cases/${encodeURIComponent(issueId)}/${action}`, {
    method: "POST", headers, body: JSON.stringify(payload),
  });
  const form = new FormData();
  form.append("payload", JSON.stringify(payload));
  items.forEach((item, index) => form.append("attachments", item.file, item.file.name || `label-${index + 1}.png`));
  return api(`/api/cases/${encodeURIComponent(issueId)}/${action}-with-attachments`, {
    method: "POST", headers: {...headers, "X-RA-Triage-Request": "labeling-v1"}, body: form,
  });
}


function caseRationaleUploadTask(caseData = state.selectedCase) {
  return caseData ? state.backgroundCaseUploads?.get(caseRationaleImageKey(caseData)) || null : null;
}

function caseUploadDraftSignature(draft) {
  return JSON.stringify(REVIEW_DRAFT_FIELDS.map((key) => draft?.[key]));
}

function caseRationaleUploadMarkup(task) {
  if (!task) return "";
  const failed = task.status === "failed", conflict = task.conflict;
  const copy = failed
    ? (conflict ? uiText("数据已变化，图片和草稿已保留，请刷新上下文后重新提交。", "Data changed. Images and draft are retained; refresh context before submitting again.")
      : uiText("后台保存未确认，图片和草稿已保留。", "Background save was not confirmed. Images and draft are retained."))
    : uiText("图片和复核正在后台保存，可切换 Issue。", "Images and review are saving in the background; you can switch Issues.");
  return `<div class="review-upload-progress case-upload-progress" role="status"><span>${escapeHtml(copy)}</span>${failed ? `<button type="button" class="button button-quiet" ${conflict ? "data-refresh-case-upload" : "data-retry-case-upload"}>${escapeHtml(conflict ? uiText("刷新上下文", "Refresh context") : uiText("重试提交", "Retry submission"))}</button>` : ""}</div>`;
}

function enqueueCaseRationaleUpload(task) {
  if (!task || ["queued", "uploading"].includes(task.status)) return;
  task.status = "queued";
  const current = () => state.activePage === "review" && state.selectedCase
    && caseRationaleImageKey(state.selectedCase) === task.key;
  const repaint = () => {
    if (!current()) return;
    renderCaseRationaleImages(state.selectedCase);
    renderCombinedReviewContextStatus();
  };
  repaint();
  const run = async () => {
    task.status = "uploading";
    repaint();
    let result;
    try {
      result = await submitCaseRationalePayload(task.issueId, task.action, task.payload, task.imageItems, task.headers);
    } catch (error) {
      task.status = "failed";
      task.conflict = Number(error?.status || 0) === 409;
      repaint();
      showToast(uiText(`Issue ${task.issueId} 后台保存未确认，图片已保留；返回此条重试。`, `Issue ${task.issueId}: background save was not confirmed. Images retained; return to retry.`), true);
      return;
    }
    // From here the write succeeded. A later display refresh failure must never
    // turn this task into an upload retry or resubmit the saved transaction.
    acknowledgeLocalChange(result);
    const currentDraft = current() ? persistReviewDraft(state.selectedCase) : null;
    const draft = currentDraft || readReviewDraft(...task.draftScope);
    const newerDraft = caseUploadDraftSignature(draft) !== caseUploadDraftSignature(task.draft);
    clearSavedCaseRationaleImages(task.key, task.imageItems);
    const moreImages = Boolean(state.caseRationaleImages?.get(task.key)?.length);
    if (newerDraft && draft) {
      // Edits made during upload predate the server commit, but are not part of it.
      const annotation = result.combined_review?.model_review;
      draft.saved_at = Math.max(Date.now(), annotationTimestamp(annotation) + 1);
      try { window.localStorage.setItem(reviewDraftStorageKey(...task.draftScope), JSON.stringify(draft)); } catch (_) {}
    } else clearReviewDraft(...task.draftScope);
    state.backgroundCaseUploads.delete(task.key);
    task.status = "saved";
    state.reviewQueueStale = true;
    showToast(uiText(`Issue ${task.issueId} 的图片和复核已保存。`, `Issue ${task.issueId}: images and review saved.`));
    if (!current()) return;
    const caseData = state.selectedCase;
    caseData.label_state = (result.combined_review || result.case_label)?.label_state || caseData.label_state;
    delete caseData.label_source_contexts;
    state.reviewFormDirty = newerDraft || moreImages;
    // Context refresh already guards Issue/Run/task/page ownership and preserves
    // newer drafts. Do not reconcile/navigate the queue after a background save.
    try {
      await loadCombinedReviewContext(caseData);
    } catch (_) { /* Saved is final; the context panel provides refresh retry. */ }
    repaint();
  };
  state.reviewUploadTail = (state.reviewUploadTail || Promise.resolve()).catch(() => {}).then(run);
  return state.reviewUploadTail;
}
