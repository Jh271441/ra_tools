/* issue-discussion.js
 * Issue discussion dialog, composer, replies and reliable submission.
 * Review, labeling and analysis share this controller; legacy entry names stay stable.
 * Classic script; shared globals are initialized before bind-bootstrap.js.
 */

function openReviewRouteDiscussion(route) {
  return openAnalysisDiscussion(route.issue, { source: "deep-link", focusCommentId: route.commentId || 0 });
}

async function openAnalysisDiscussion(
  issueId,
  {
    source = "analysis",
    focusCommentId = 0,
    intentDatasetId = "",
    intentCaseId = "",
  } = {}
) {
  const isIntentDiscussion = Boolean(intentDatasetId && intentCaseId);
  if (state.analysisDiscussion) closeAnalysisDiscussion();
  state.analysisDiscussion = {
    kind: isIntentDiscussion ? "intent" : "issue", issueId: String(issueId), runId: "", source,
    intentDatasetId: String(intentDatasetId || ""), intentCaseId: String(intentCaseId || ""),
    pageContext: capturePageContext(), status: "loading", saving: false,
    replyTo: null, comments: [], pendingImages: [], preview: false, actor:discussionDraftActor(),
  };
  const context = state.analysisDiscussion;
  context.draftKey = discussionDraftKey(context);
  if (!isIntentDiscussion && state.activePage === "review" && state.selectedId === String(issueId) && state.selectedRunId) {
    context.reviewOrigin = {model_run_id:String(state.selectedRunId),campaign_id:String(state.reviewWorkSplitId || "")};
  }
  setAnalysisDiscussionFeedback(context);
  const discussionTitle = $("#analysisDiscussionTitle");
  const discussionTitleZh = discussionTitle?.querySelector(".ui-lang-zh");
  const discussionTitleEn = discussionTitle?.querySelector(".ui-lang-en");
  if (discussionTitleZh) discussionTitleZh.textContent = isIntentDiscussion ? "意图标注讨论" : "问题讨论";
  if (discussionTitleEn) discussionTitleEn.textContent = isIntentDiscussion ? "Intent discussion" : "Issue discussion";
  $("#analysisDiscussionContext").textContent = isIntentDiscussion ? `${intentDatasetId} · ${issueId}` : String(issueId);
  const textarea = $("#analysisDiscussionNote");
  textarea.value = "";
  const draft = restoreAnalysisDiscussionDraft(context);
  const restoringImages = restoreDiscussionDraftImages(context, draft);
  textarea.hidden = false;
  $("#analysisDiscussionPreview").hidden = true;
  $("[data-comment-preview-toggle]").innerHTML = discussionActionText("预览", "Preview");
  renderAnalysisDiscussionImages();
  updateAnalysisDiscussionComposerAccess();
  document.querySelectorAll("[data-comment-image]").forEach((button) => {
    button.hidden = isIntentDiscussion;
  });
  const imageInput = $("#analysisDiscussionImageInput");
  if (imageInput) imageInput.disabled = isIntentDiscussion;
  $("#analysisDiscussionImages").hidden = isIntentDiscussion;
  renderAnalysisDiscussionReplyContext();
  $("#analysisDiscussionThread").innerHTML =
    `<div class="comment-thread-empty">${uiText("正在加载评论…", "Loading comments…")}</div>`;
  bindReviewMentionComposer(textarea, $("#analysisDiscussionMentionComposer"));
  updateReviewMentionComposer(textarea, $("#analysisDiscussionMentionComposer"));
  // The modal makes the underlying player inert. Stop its segment traffic
  // before the discussion GET so video buffering cannot consume that bandwidth.
  context.suspendedVideos = [...document.querySelectorAll("video")].filter(
    video => video._pauseBevPlayback && !video.closest("[hidden]")
  );
  context.suspendedVideos.forEach(video => video._pauseBevPlayback());
  $("#analysisDiscussionDialog").showModal();
  await Promise.all([loadAnalysisDiscussion(context, focusCommentId), restoringImages]);
}

function isAnalysisDiscussionCurrent(context) {
  if (!context || state.analysisDiscussion !== context) return false;
  if (context.actor !== undefined && context.actor !== discussionDraftActor()) return false;
  const previous = new URL(context.pageContext.url, window.location.origin);
  const current = new URL(window.location.pathname + window.location.search, window.location.origin);
  if (context.kind === "intent") return isPageContextCurrent(context.pageContext, { matchUrl: false })
    && previous.pathname === current.pathname
    && ["dataset", "case"].every(key => previous.searchParams.get(key) === current.searchParams.get(key));
  // An Issue conversation survives Run/task/filter normalization in Bot links.
  // A real switch to another Issue still blocks a stale modal from submitting.
  const issue = current.searchParams.get("issue");
  return previous.searchParams.get("issue") === issue || !issue || issue === context.issueId;
}

function setAnalysisDiscussionFeedback(context, zh = "", en = "", isError = false) {
  if (state.analysisDiscussion !== context) return;
  const target = $("#analysisDiscussionSubmitStatus");
  if (!target) return;
  target.hidden = !zh && !en;
  target.dataset.error = String(isError);
  target.innerHTML = `<span class="ui-lang-zh">${escapeHtml(zh)}</span><span class="ui-lang-en">${escapeHtml(en)}</span>`;
  if (isError) target.scrollIntoView({ block: "nearest" });
}

async function loadAnalysisDiscussion(context, focusCommentId = 0) {
  if (!isAnalysisDiscussionCurrent(context)) return;
  const { issueId, intentDatasetId, intentCaseId } = context;
  const isIntentDiscussion = context.kind === "intent";
  const textarea = $("#analysisDiscussionNote");
  const requestVersion = context.requestVersion = (context.requestVersion || 0) + 1;
  context.status = "loading";
  updateAnalysisDiscussionComposerAccess();
  try {
    const result = isIntentDiscussion
      ? await api(`/api/intent-datasets/${encodeURIComponent(intentDatasetId)}/cases/${encodeURIComponent(intentCaseId)}/comments`)
      : await api(`/api/cases/${encodeURIComponent(issueId)}/discussion`);
    if (!isAnalysisDiscussionCurrent(context) || context.requestVersion !== requestVersion) return;
    context.status = "ready";
    context.comments = result.comments || [];
    if (context.replyTo) {
      const parent = context.comments.find(item => Number(item.id) === Number(context.replyTo.id));
      context.replyUnavailable = !parent || Boolean(parent.deleted);
      if (parent) context.replyTo = parent;
      renderAnalysisDiscussionReplyContext();
    }
    updateAnalysisDiscussionComposerAccess();
    if (isIntentDiscussion && state.intentLabeling?.caseId === String(intentCaseId)) {
      state.intentLabeling.caseData ||= {};
      state.intentLabeling.caseData.collaboration ||= {};
      state.intentLabeling.caseData.collaboration.comments = state.analysisDiscussion.comments;
      if (typeof renderIntentCollaboration === "function") renderIntentCollaboration();
    }
    if (!isIntentDiscussion && state.caseLabeling?.caseData?.issue_id === String(issueId)) {
      state.caseLabeling.caseData.comments = state.analysisDiscussion.comments;
    }
    renderAnalysisDiscussionThread();
    updateAnalysisDiscussionCount(issueId, "", Number(result.count || 0));
    if (focusCommentId) {
      const focused = $("#analysisDiscussionThread")?.querySelector(
        `[data-comment-id="${Number(focusCommentId)}"]`
      );
      const parentDetails = focused?.closest("details");
      if (parentDetails) parentDetails.open = true;
      focused?.classList.add("is-deep-linked");
      focused?.scrollIntoView({ block: "center" });
    }
    // Keep the shared shortcut/focus behavior consistent for read-only intent
    // viewers: only focus the composer when it is actually available.
    if (!$("#analysisDiscussionComposer")?.hidden) textarea.focus();
  } catch (error) {
    if (!isAnalysisDiscussionCurrent(context) || context.requestVersion !== requestVersion) return;
    context.status = "error";
    disposeReviewMentionComposer($("[data-comment-edit-input]"));
    $("#analysisDiscussionThread").innerHTML = `<div class="comment-thread-empty">${escapeHtml(error.message || uiText("讨论加载失败", "Unable to load discussion"))} <button type="button" class="text-link" data-retry-discussion>${uiText("重试", "Retry")}</button></div>`;
    $("[data-retry-discussion]")?.addEventListener("click", () => loadAnalysisDiscussion(context, focusCommentId));
    updateAnalysisDiscussionComposerAccess();
  }
}

function closeAnalysisDiscussion(event) {
  if (event?.type === "close" && $("#analysisDiscussionDialog")?.open) return;
  persistAnalysisDiscussionDraft();
  disposeReviewMentionComposer($("[data-comment-edit-input]"));
  clearAnalysisDiscussionImages();
  // Re-enable only the still-visible players owned by this dialog. The shared
  // resume hook retains the per-player explicit Play policy (no autoplay).
  state.analysisDiscussion?.suspendedVideos?.forEach(video => {
    if (video.isConnected && !video.closest("[hidden]")) video._resumeBevPlayback?.();
  });
  state.analysisDiscussion = null;
}

function canReplyToAnalysisDiscussion(comment, context = state.analysisDiscussion) {
  if (!context || context.status !== "ready" || context.saving || context.commentAction?.saving || comment.deleted) return false;
  return context.kind === "intent" ? Boolean(state.session?.can_annotate_intent)
    : Boolean(!state.session?.read_only && (state.session?.can_write || state.session?.is_admin));
}

function updateAnalysisDiscussionComposerAccess() {
  const context = state.analysisDiscussion;
  if (!context) return;
  const actorMatches = context.actor === undefined || context.actor === discussionDraftActor();
  const allowed = actorMatches && (context.kind === "intent" ? Boolean(state.session?.can_annotate_intent)
    : Boolean(!state.session?.read_only && (state.session?.can_write || state.session?.is_admin)));
  $("#analysisDiscussionComposer").hidden = !allowed;
  const submit = $("#analysisDiscussionSubmit");
  submit.hidden = !allowed;
  submit.disabled = !allowed || context.status !== "ready" || context.saving || Boolean(context.commentAction?.saving)
    || context.restoringDraftImages || context.pendingImages?.some(item => item.missing) || context.replyUnavailable;
  submit.querySelector(".ui-lang-zh").textContent = context.saving ? "发表中…" : "发表评论";
  submit.querySelector(".ui-lang-en").textContent = context.saving ? "Posting…" : "Post comment";
  $("#analysisDiscussionForm")?.setAttribute("aria-busy", String(context.saving));
  const locked = Boolean(context.saving || context.status === "posted");
  $("#analysisDiscussionNote").readOnly = locked;
  $("#analysisDiscussionDialog")?.querySelectorAll("[data-comment-format], [data-comment-image], [data-comment-preview-toggle], [data-remove-comment-image], [data-cancel-comment-reply]").forEach(button => {button.disabled = locked;});
  $("#analysisDiscussionDialog")?.querySelectorAll("[data-comment-image], [data-remove-comment-image]").forEach(button => {button.disabled = locked || Boolean(context.restoringDraftImages);});
  $("#analysisDiscussionChannelField").hidden = true;
  $("#analysisDiscussionViewField").hidden = true;
  const hint = $("#analysisDiscussionNotice");
  hint.hidden = !allowed && context.kind === "intent";
  hint.textContent = context.status === "error"
    ? uiText("讨论未加载成功，请重试。草稿已保留。", "Load the discussion before posting. Your draft is preserved.")
    : context.replyUnavailable ? uiText("回复对象不可用，请取消回复或选择其他评论；文字草稿已保留。", "The reply target is unavailable. Cancel the reply or choose another comment; your text is retained.")
    : context.restoringDraftImages ? uiText("正在恢复草稿图片…", "Restoring draft images…")
    : context.pendingImages?.some(item => item.missing) ? uiText("草稿文字已恢复，部分图片无法读取，请移除后重新添加。", "Text restored. Some images are unavailable; remove and attach them again.")
    : context.draftStorageError ? uiText("草稿暂存于当前页面，浏览器未能保存到本机。", "Draft retained in this page; browser storage is unavailable.")
    : uiText("草稿自动保存在本机，关闭后可继续编辑。", "Drafts are saved on this device; close and return to continue.");
}

function refreshAnalysisDiscussionLanguage() {
  if (state.analysisDiscussion && $("#analysisDiscussionDialog")?.open) updateAnalysisDiscussionComposerAccess();
}

function clearAnalysisDiscussionImages() {
  const images = state.analysisDiscussion?.pendingImages || [];
  images.forEach((item) => {
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
  });
  if (state.analysisDiscussion) state.analysisDiscussion.pendingImages = [];
  const input = $("#analysisDiscussionImageInput");
  if (input) input.value = "";
  renderAnalysisDiscussionImages();
}

function insertAnalysisDiscussionText(before, after = "", placeholder = "") {
  const textarea = $("#analysisDiscussionNote");
  if (!textarea) return;
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? start;
  const selected = textarea.value.slice(start, end) || placeholder;
  textarea.setRangeText(`${before}${selected}${after}`, start, end, "end");
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  textarea.focus();
}

function applyAnalysisDiscussionFormat(kind) {
  if (kind === "bold") return insertAnalysisDiscussionText("**", "**", "粗体文字");
  if (kind === "italic") return insertAnalysisDiscussionText("*", "*", "斜体文字");
  if (kind === "code") return insertAnalysisDiscussionText("`", "`", "code");
  if (kind === "link") return insertAnalysisDiscussionText("[", "](https://)", "链接文字");
  const textarea = $("#analysisDiscussionNote");
  if (!textarea) return;
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? start;
  const selected = textarea.value.slice(start, end) || (kind === "quote" ? "引用内容" : "列表项");
  const prefix = kind === "quote" ? "> " : "- ";
  const replacement = selected.split("\n").map((line) => `${prefix}${line}`).join("\n");
  textarea.setRangeText(replacement, start, end, "end");
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  textarea.focus();
}

function addAnalysisDiscussionImages(files) {
  const context = state.analysisDiscussion;
  if (!context || context.saving || context.restoringDraftImages) return;
  if (context.kind === "intent") {
    setAnalysisDiscussionFeedback(context, "意图标注讨论暂不支持图片附件，请使用 Markdown 文本。", "Intent discussion does not support images. Use Markdown text.", true);
    return;
  }
  const limits = state.config?.review_attachment_limits || {};
  const maxCount = Number(limits.max_count || 4);
  const maxBytes = Number(limits.max_bytes_each || 8 * 1024 * 1024);
  const maxTotalBytes = Number(limits.max_bytes_total || 24 * 1024 * 1024);
  const allowed = new Set(limits.media_types || ["image/png", "image/jpeg", "image/webp"]);
  let rejected = null;
  [...files].forEach((file) => {
    if (context.pendingImages.length >= maxCount) return void (rejected = [`每条评论最多 ${maxCount} 张图片。`, `Up to ${maxCount} images per comment.`]);
    if (!allowed.has(file.type)) return void (rejected = ["仅支持 PNG、JPEG 或 WebP 图片。", "Only PNG, JPEG and WebP images are supported."]);
    if (file.size > maxBytes) return void (rejected = [`单张图片不能超过 ${maxBytes / (1024 * 1024)} MB。`, `Each image must be at most ${maxBytes / (1024 * 1024)} MB.`]);
    const total = context.pendingImages.reduce((sum, item) => sum + Number(item.file?.size || item.size || 0), 0);
    if (total + file.size > maxTotalBytes) return void (rejected = [`本次图片总大小不能超过 ${maxTotalBytes / (1024 * 1024)} MB。`, `Total image size must be at most ${maxTotalBytes / (1024 * 1024)} MB.`]);
    const randomId = crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    const token = `pending-${String(randomId).replace(/[^A-Za-z0-9-]/g, "-")}`;
    const item = { token, file, previewUrl: URL.createObjectURL(file) };
    context.pendingImages.push(item);
    const safeAlt = String(file.name || uiText("评论图片", "Comment image")).replace(/[\]\n]/g, "").slice(0, 80);
    const textarea = $("#analysisDiscussionNote");
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    const separator = start > 0 && !textarea.value.slice(0, start).endsWith("\n") ? "\n" : "";
    textarea.setRangeText(`${separator}![${safeAlt}](attachment:${token})\n`, start, end, "end");
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
  renderAnalysisDiscussionImages();
  if (context.preview) renderAnalysisDiscussionPreview();
  if (rejected) setAnalysisDiscussionFeedback(context, ...rejected, true);
}

function renderAnalysisDiscussionImages() {
  const target = $("#analysisDiscussionImages");
  if (!target) return;
  const images = state.analysisDiscussion?.pendingImages || [];
  target.innerHTML = images.map((item) => `
    <div class="comment-pending-image">
      ${item.previewUrl ? `<img src="${escapeHtml(item.previewUrl)}" alt="${escapeHtml(item.file?.name || item.name || uiText("待上传图片", "Pending image"))}" />` : ""}
      <span>${escapeHtml(item.file?.name || item.name || uiText("图片", "Image"))}</span>
      <button type="button" data-remove-comment-image="${escapeHtml(item.token)}" data-i18n-aria-label="comment.remove_image" aria-label="${escapeHtml(uiText("移除图片", "Remove image"))}">×</button>
    </div>`).join("");
  target.querySelectorAll("[data-remove-comment-image]").forEach((button) => {
    button.addEventListener("click", () => {
      const context = state.analysisDiscussion;
      const index = context?.pendingImages?.findIndex((item) => item.token === button.dataset.removeCommentImage) ?? -1;
      if (!context || index < 0) return;
      const [item] = context.pendingImages.splice(index, 1);
      URL.revokeObjectURL(item.previewUrl);
      const textarea = $("#analysisDiscussionNote");
      const escapedToken = item.token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      textarea.value = textarea.value.replace(
        new RegExp(`!?\\[[^\\]\\n]*\\]\\(attachment:${escapedToken}\\)\\n?`, "g"),
        ""
      );
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      renderAnalysisDiscussionImages();
      updateAnalysisDiscussionComposerAccess();
    });
  });
}

function renderAnalysisDiscussionPreview() {
  const preview = $("#analysisDiscussionPreview");
  if (!preview) return;
  const attachments = (state.analysisDiscussion?.pendingImages || []).map((item) => ({
    id: item.token,
    url: item.previewUrl,
  }));
  preview.innerHTML = reviewCommentBodyMarkup($("#analysisDiscussionNote")?.value || "", attachments) ||
    `<span class="comment-markdown-empty">${discussionActionText("暂无可预览内容。", "Nothing to preview yet.")}</span>`;
}

function toggleAnalysisDiscussionPreview() {
  const context = state.analysisDiscussion;
  if (!context) return;
  context.preview = !context.preview;
  const textarea = $("#analysisDiscussionNote");
  const preview = $("#analysisDiscussionPreview");
  textarea.hidden = context.preview;
  preview.hidden = !context.preview;
  $("[data-comment-preview-toggle]").innerHTML = context.preview
    ? discussionActionText("继续编辑", "Continue editing") : discussionActionText("预览", "Preview");
  if (context.preview) renderAnalysisDiscussionPreview();
  else textarea.focus();
}

function bindAnalysisDiscussionEditor() {
  const textarea = $("#analysisDiscussionNote");
  const imageInput = $("#analysisDiscussionImageInput");
  if (!textarea || textarea.dataset.commentEditorBound === "1") return;
  textarea.dataset.commentEditorBound = "1";
  document.querySelectorAll("[data-comment-format]").forEach((button) => {
    button.addEventListener("click", () => applyAnalysisDiscussionFormat(button.dataset.commentFormat));
  });
  $("[data-comment-preview-toggle]")?.addEventListener("click", toggleAnalysisDiscussionPreview);
  $("[data-comment-image]")?.addEventListener("click", () => imageInput?.click());
  imageInput?.addEventListener("change", () => {
    addAnalysisDiscussionImages(imageInput.files || []);
    imageInput.value = "";
  });
  textarea.addEventListener("paste", (event) => {
    const images = [...(event.clipboardData?.files || [])].filter((file) => file.type.startsWith("image/"));
    if (!images.length) return;
    event.preventDefault();
    addAnalysisDiscussionImages(images);
  });
  textarea.addEventListener("input", () => {
    persistAnalysisDiscussionDraft();
    if (state.analysisDiscussion?.preview) renderAnalysisDiscussionPreview();
  });
  textarea.addEventListener("select", () => persistAnalysisDiscussionDraft());
  window.addEventListener?.("pagehide", () => persistAnalysisDiscussionDraft());
}

function analysisDiscussionShareUrl(commentId) {
  const context = state.analysisDiscussion;
  if (context?.kind === "intent") {
    const intentUrl = new URL(withBase(PAGE_ROUTES.intent.path), window.location.origin);
    intentUrl.searchParams.set("dataset", String(context.intentDatasetId || ""));
    intentUrl.searchParams.set("case", String(context.intentCaseId || ""));
    intentUrl.searchParams.set("comments", "1");
    intentUrl.searchParams.set("comment", String(Number(commentId)));
    return intentUrl.href;
  }
  const url = new URL(withBase(PAGE_ROUTES.review.path), window.location.origin);
  url.searchParams.set("issue", String(context?.issueId || ""));
  url.searchParams.set("comments", "1");
  url.searchParams.set("channel", "case");
  url.searchParams.set("comment", String(Number(commentId)));
  if (context?.reviewOrigin) {
    url.searchParams.set("run",context.reviewOrigin.model_run_id);
    if (context.reviewOrigin.campaign_id) url.searchParams.set("work_split",context.reviewOrigin.campaign_id);
    url.searchParams.set("comparison","all");
  }
  return url.href;
}

async function shareAnalysisDiscussionComment(commentId) {
  const url = analysisDiscussionShareUrl(commentId);
  if (navigator.share) {
    try {
      await navigator.share({ title: "RA Triage 评论", url });
      return;
    } catch (error) {
      if (error?.name === "AbortError") return;
    }
  }
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(url);
  } else {
    const input = document.createElement("textarea");
    input.value = url;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.append(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }
  showToast("评论链接已复制。");
}

function updateAnalysisDiscussionCount(issueId, runId, count) {
  document.querySelectorAll("[data-analysis-discussion], [data-trail-update-discussion], [data-intent-discussion]").forEach((button) => {
    if (button.hasAttribute("data-intent-discussion")) {
      const intent = state.analysisDiscussion;
      if (
        intent?.kind !== "intent"
        || String(button.dataset.intentDatasetId || "") !== String(intent.intentDatasetId || "")
        || String(button.dataset.intentCaseId || "") !== String(intent.intentCaseId || "")
      ) return;
      button.innerHTML = count > 0
        ? `打开讨论 · ${count} <kbd>D</kbd>`
        : "打开讨论 <kbd>D</kbd>";
      return;
    }
    if (state.analysisDiscussion?.kind === "intent") return;
    const buttonIssue = button.dataset.analysisDiscussion || button.dataset.trailUpdateDiscussion;
    if (String(buttonIssue || "") !== String(issueId || "")) return;
    button.textContent = count > 0 ? `评论 · ${count}` : "评论";
  });
}

function discussionActionText(zh, en) {
  return `<span class="ui-lang-zh">${escapeHtml(zh)}</span><span class="ui-lang-en">${escapeHtml(en)}</span>`;
}

function canManageAnalysisComment(comment, context = state.analysisDiscussion) {
  if (!state.session?.verified || comment.is_label_evidence || !canReplyToAnalysisDiscussion(comment, context)) return false;
  const admin = context.kind === "intent" ? state.session.can_manage_intent : state.session.is_admin;
  return Boolean(admin || (comment.author_verified && String(comment.author).toLowerCase() === String(state.session.username || "").toLowerCase()));
}

function analysisCommentActionMarkup(comment, context) {
  const action = context.commentAction;
  if (!action || action.id !== Number(comment.id)) return "";
  const busy = action.saving ? " disabled" : "";
  const copy = discussionActionText;
  return `<section class="comment-edit-panel">
    ${action.mode === "edit" ? `<label>${copy("编辑评论", "Edit comment")}<textarea data-comment-edit-input rows="4" maxlength="3500"${busy}>${escapeHtml(action.body)}</textarea></label><div class="review-mention-composer" id="analysisCommentEditMentions" data-notification-mode="none" aria-live="polite"></div>
      <p class="discussion-notice">${copy("保留原有图片；保存修改不会发送通知。", "Existing images are retained. Saving edits does not send notifications.")}</p>`
      : `<p>${copy("删除这条评论？保留删除占位和已有回复。已发送的提醒不会撤回。", "Delete this comment? A placeholder and existing replies remain. Sent notifications cannot be recalled.")}</p>`}
    ${action.error ? `<p class="discussion-notice discussion-submit-status is-error" role="alert">${action.error}</p><button class="text-link" type="button" data-comment-action="reload"${busy}>${copy("加载最新评论（保留草稿）", "Load latest comment (keep draft)")}</button>` : ""}
    <div class="comment-edit-actions">
      <button class="button button-quiet" type="button" data-comment-action="cancel"${busy}>${copy("取消", "Cancel")}</button>
      <button class="button ${action.mode === "edit" ? "button-primary" : "button-danger"}" type="button" data-comment-action="save"${busy}>${action.saving ? copy("处理中…", "Saving…") : action.mode === "edit" ? copy("保存修改", "Save changes") : copy("确认删除", "Delete comment")}</button>
    </div>
  </section>`;
}

function beginAnalysisCommentAction(commentId, mode) {
  const context = state.analysisDiscussion;
  const comment = context?.comments?.find(item => Number(item.id) === Number(commentId));
  if (!comment || !isAnalysisDiscussionCurrent(context) || !canManageAnalysisComment(comment, context)) return;
  if (context.commentAction) {
    setAnalysisDiscussionFeedback(context, "请先保存或取消当前评论的修改。", "Save or cancel the current comment action first.", true);
    return;
  }
  context.commentAction = { id: Number(comment.id), mode, body: String(comment.body || ""), version: Number(comment.version || 1), saving: false, error: "" };
  renderAnalysisDiscussionThread();
  $(".comment-edit-panel")?.scrollIntoView({ block: "nearest" });
  $("[data-comment-edit-input]")?.focus({ preventScroll: true });
}

async function saveAnalysisCommentAction() {
  const context = state.analysisDiscussion;
  const action = context?.commentAction;
  if (!action || action.saving || context.saving || !isAnalysisDiscussionCurrent(context)) return;
  const comment = context.comments.find(item => Number(item.id) === action.id);
  if (!comment || !canManageAnalysisComment(comment, context)) return;
  if (action.mode === "edit" && !String(action.body).trim()) {
    action.error = discussionActionText("评论内容不能为空。", "Enter a comment.");
    renderAnalysisDiscussionThread();
    return;
  }
  action.saving = true;
  renderAnalysisDiscussionThread();
  updateAnalysisDiscussionComposerAccess();
  try {
    const path = context.kind === "intent"
      ? `/api/intent-datasets/${encodeURIComponent(context.intentDatasetId)}/cases/${encodeURIComponent(context.intentCaseId)}/comments/${action.id}`
      : `/api/cases/${encodeURIComponent(context.issueId)}/comments/${action.id}`;
    const result = await postAnalysisDiscussionRequest(path, { method: action.mode === "edit" ? "PATCH" : "DELETE",
      body: JSON.stringify({ expected_version: action.version, ...(action.mode === "edit" ? {body: action.body} : {}) }) });
    if (!isAnalysisDiscussionCurrent(context) || context.commentAction !== action) return;
    Object.assign(comment, result.comment);
    for (const item of context.comments) if (Number(item.reply_to_id) === action.id) {
      item.reply_to_body = comment.body;
      item.reply_to_deleted = Boolean(comment.deleted);
    }
    if (context.replyTo?.id === comment.id) {
      if (comment.deleted) { resetAnalysisDiscussionReply(context); renderAnalysisDiscussionReplyContext(); }
      else context.replyTo = comment;
    }
    context.commentAction = null;
    if (context.kind !== "intent" && state.caseLabeling?.caseData?.issue_id === context.issueId) state.caseLabeling.caseData.comments = context.comments;
    if (context.kind === "intent" && state.intentLabeling?.caseId === context.intentCaseId) {
      state.intentLabeling.caseData.collaboration.comments = context.comments;
      if (typeof renderIntentCollaboration === "function") renderIntentCollaboration();
    }
    setAnalysisDiscussionFeedback(context, action.mode === "edit" ? "评论已修改，未发送新通知。" : "评论已删除，已有回复保留。",
      action.mode === "edit" ? "Comment updated. No new notifications sent." : "Comment deleted. Existing replies remain.");
  } catch (error) {
    if (isAnalysisDiscussionCurrent(context) && context.commentAction === action) action.error = discussionActionText("未能确认操作成功，请加载最新评论核对；草稿已保留。", "Could not confirm the change. Load the latest comment to check; your draft is preserved.") + ` ${escapeHtml(error.message || "")}`;
  } finally {
    action.saving = false;
    if (isAnalysisDiscussionCurrent(context)) { renderAnalysisDiscussionThread(); updateAnalysisDiscussionComposerAccess(); }
  }
}

async function reloadAnalysisCommentAction() {
  const context = state.analysisDiscussion, action = context?.commentAction;
  if (!action || action.saving) return;
  await loadAnalysisDiscussion(context);
  if (!isAnalysisDiscussionCurrent(context) || context.commentAction !== action || context.status !== "ready") return;
  const comment = context.comments.find(item => Number(item.id) === action.id);
  if (!comment || comment.deleted) {
    action.error = discussionActionText("评论已删除，请复制草稿后取消编辑。", "The comment was deleted. Copy your draft, then cancel editing.");
  } else {
    action.version = Number(comment.version || 1);
    action.error = discussionActionText("已加载最新正文。请与保留的草稿比较后再保存。", "Latest text loaded. Compare it with your preserved draft before saving.");
  }
  renderAnalysisDiscussionThread();
}

function renderAnalysisDiscussionThread() {
  const context = state.analysisDiscussion;
  const target = $("#analysisDiscussionThread");
  if (!target || !context) return;
  const previousScroll = target.scrollTop;
  disposeReviewMentionComposer(target.querySelector("[data-comment-edit-input]"));
  const renderComment = (comment, { readOnly = false } = {}) => {
    const replyExcerpt = String(comment.reply_to_body || "")
      .replace(/!\[[^\]\n]*\]\([^\n)]+\)/g, "[图片]")
      .replace(/\[([^\]\n]+)\]\(https?:\/\/[^\s)]+\)/g, "$1")
      .replace(/^\s*(?:#{1,3}|>|[-+*]|\d+[.)])\s+/gm, "")
      .replace(/[*_~`]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 120);
    const replyContext = comment.reply_to_id
      ? `<div class="comment-reply-quote">${discussionActionText("回复", "Reply to")} ${escapeHtml(reviewMentionDisplayName(comment.reply_to_author || uiText("评论人", "author")))}: ${comment.reply_to_deleted ? discussionActionText("原评论已删除", "Original comment deleted") : escapeHtml(replyExcerpt)}</div>`
      : "";
    const channelLabel = comment.discussion_channel === "campaign" ? discussionActionText("来自任务讨论", "From task discussion")
      : comment.discussion_channel === "model_review" ? discussionActionText("来自复核讨论", "From review discussion") : "";
    const canReply = canReplyToAnalysisDiscussion(comment, context);
    const canManage = canManageAnalysisComment(comment, context);
    return `<article class="comment-thread-item" data-comment-id="${Number(comment.id)}">
      <div class="comment-thread-meta">
        <strong>${escapeHtml(reviewMentionDisplayName(comment.author || "unknown"))}</strong>
        <span>${channelLabel ? `${channelLabel} · ` : ""}${comment.author_verified ? `${discussionActionText("已验证", "Verified")} · ` : ""}${escapeHtml(formatTime(comment.created_at))}${comment.edited_at ? ` · ${discussionActionText("已编辑", "Edited")} ${escapeHtml(formatTime(comment.edited_at))}` : ""}</span>
      </div>
      ${replyContext}
      <div class="comment-thread-body">${comment.deleted ? discussionActionText("此评论已删除", "This comment was deleted") : reviewCommentBodyMarkup(comment.body || "", comment.attachments || [])}</div>
      <div class="comment-thread-actions">
        <button class="analysis-discussion-link" type="button" data-comment-share="${Number(comment.id)}">${discussionActionText("分享", "Share")}</button>
        ${canReply ? `<button class="analysis-discussion-link" type="button" data-comment-reply="${Number(comment.id)}">${discussionActionText("回复", "Reply")}</button>` : ""}
        ${canManage ? `<button class="analysis-discussion-link" type="button" data-comment-edit="${Number(comment.id)}">${discussionActionText("编辑", "Edit")}</button><button class="analysis-discussion-link" type="button" data-comment-delete="${Number(comment.id)}">${discussionActionText("删除", "Delete")}</button>` : ""}
      </div>
      ${analysisCommentActionMarkup(comment, context)}
    </article>`;
  };
  const comments = context.comments || [];
  target.innerHTML = comments.length ? comments.map(comment => renderComment(comment)).join("")
    : `<div class="comment-thread-empty">${discussionActionText("还没有评论，可以发起第一条讨论。", "No comments yet. Start the discussion.")}</div>`;
  target.querySelectorAll("[data-comment-reply]").forEach((button) => {
    button.addEventListener("click", () =>
      beginAnalysisDiscussionReply(Number(button.dataset.commentReply))
    );
  });
  target.querySelectorAll("[data-comment-share]").forEach((button) => {
    button.addEventListener("click", () => {
      shareAnalysisDiscussionComment(Number(button.dataset.commentShare)).catch((error) => showToast(error.message, true));
    });
  });
  target.querySelectorAll("[data-comment-edit], [data-comment-delete]").forEach(button => {
    button.addEventListener("click", () => beginAnalysisCommentAction(Number(button.dataset.commentEdit || button.dataset.commentDelete), button.dataset.commentEdit ? "edit" : "delete"));
  });
  const editInput = target.querySelector("[data-comment-edit-input]");
  if (editInput) bindReviewMentionComposer(editInput, target.querySelector("#analysisCommentEditMentions"));
  editInput?.addEventListener("input", () => { if (context.commentAction) context.commentAction.body = editInput.value; });
  editInput?.addEventListener("keydown", event => {
    if (isImeComposing(event)) return;
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); event.stopPropagation(); saveAnalysisCommentAction(); }
  });
  target.querySelectorAll("[data-comment-action]").forEach(button => button.addEventListener("click", () => {
    if (context.commentAction?.saving) return;
    if (button.dataset.commentAction === "save") saveAnalysisCommentAction();
    else if (button.dataset.commentAction === "reload") reloadAnalysisCommentAction();
    else { context.commentAction = null; renderAnalysisDiscussionThread(); }
  }));
  target.scrollTop = context.commentAction ? previousScroll : target.scrollHeight;
}

function beginAnalysisDiscussionReply(commentId) {
  const context = state.analysisDiscussion;
  const comment = context?.comments?.find(
    (item) => Number(item.id) === Number(commentId)
  );
  if (!context || !comment || !canReplyToAnalysisDiscussion(comment, context)) return;
  context.replyTo = comment;
  context.replyUnavailable = false;
  const textarea = $("#analysisDiscussionNote");
  const author = String(comment.author || "").trim().toLowerCase();
  // reply_to_id already supplies the notification recipient. Never insert a
  // forbidden @token for an author removed/disabled in the mention directory.
  const canMention = (state.mentionUsers || []).some((item) => item.enabled !== false
    && String(item.username || "").trim().toLowerCase() === author);
  const prefix = canMention && author !== String(state.session?.username || "").toLowerCase() ? `@${author} ` : "";
  if (!String(textarea.value || "").trim() || textarea.value === context.replyMentionPrefix) {
    textarea.value = prefix;
    context.replyMentionPrefix = prefix;
  } else {
    delete context.replyMentionPrefix;
  }
  if (context.preview) toggleAnalysisDiscussionPreview();
  renderAnalysisDiscussionReplyContext();
  updateReviewMentionComposer(textarea, $("#analysisDiscussionMentionComposer"));
  textarea.focus();
  textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  persistAnalysisDiscussionDraft(context);
}

function renderAnalysisDiscussionReplyContext() {
  const target = $("#analysisDiscussionReplyContext");
  const reply = state.analysisDiscussion?.replyTo;
  if (!target) return;
  target.hidden = !reply;
  target.innerHTML = reply
    ? `<span><span class="ui-lang-zh">正在回复</span><span class="ui-lang-en">Replying to</span> <strong>${escapeHtml(reviewMentionDisplayName(reply.author || "unknown"))}</strong></span><button type="button" data-cancel-comment-reply><span class="ui-lang-zh">取消回复</span><span class="ui-lang-en">Cancel reply</span></button>`
    : "";
  target.querySelector("[data-cancel-comment-reply]")?.addEventListener("click", () => {
    resetAnalysisDiscussionReply(state.analysisDiscussion);
    renderAnalysisDiscussionReplyContext();
  });
}

function resetAnalysisDiscussionReply(context) {
  if (!context) return;
  const textarea = $("#analysisDiscussionNote");
  if (context.replyMentionPrefix && textarea?.value === context.replyMentionPrefix) textarea.value = "";
  delete context.replyMentionPrefix;
  context.replyTo = null;
  context.replyUnavailable = false;
  updateAnalysisDiscussionComposerAccess();
  updateReviewMentionComposer(textarea, $("#analysisDiscussionMentionComposer"));
  if (!context.saving) persistAnalysisDiscussionDraft(context);
}

async function postAnalysisDiscussionRequest(path, options) {
  const controller = new AbortController();
  const timeoutMs = options.body instanceof FormData ? 180_000 : 30_000;
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await api(path, { ...options, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted) {
      throw apiResponseError("评论操作请求超时。", "The comment request timed out.", { code: "timeout", ambiguous: true });
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function analysisDiscussionSubmission(context, payload) {
  const {review_context, ...content} = payload;
  const signature = JSON.stringify({ ...content, images: context.pendingImages.map(item => item.token),
    actor: discussionDraftActor() });
  if (context.submission?.signature !== signature) {
    context.submission = { signature, id: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` };
  }
  rememberDiscussionSubmission(context);
  return context.submission;
}

async function findAnalysisDiscussionSubmission(context, submission) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 6000);
  try {
    const result = await api(`/api/cases/${encodeURIComponent(context.issueId)}/discussion-submissions/${encodeURIComponent(submission.id)}`,
      { signal: controller.signal, cache: "no-store" });
    if (!Number.isInteger(Number(result?.comment?.id)) || Number(result.comment.id) <= 0) {
      throw apiResponseError("无法核对评论发表结果。", "Unable to verify whether the comment was posted.", { ambiguous: true });
    }
    return result;
  } catch (error) {
    if (error.status === 404) return null;
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function postIssueDiscussion(context, payload, path, options) {
  const submission = analysisDiscussionSubmission(context, payload);
  if (submission.result) return submission.result;
  if (submission.uncertain) {
    const saved = await findAnalysisDiscussionSubmission(context, submission);
    if (saved) return (submission.result = saved);
  }
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (!isAnalysisDiscussionCurrent(context)) throw new Error(uiText("讨论已切换，草稿已保留。", "The discussion has changed. Your draft is preserved."));
    try {
      submission.uncertain = true;
      rememberDiscussionSubmission(context);
      const result = await postAnalysisDiscussionRequest(path, { ...options,
        headers: { ...options.headers, "Idempotency-Key": submission.id } });
      if (!Number.isInteger(Number(result?.comment?.id)) || Number(result.comment.id) <= 0) {
        throw apiResponseError("服务器未返回有效的评论确认。", "The server did not return a valid comment receipt.", { ambiguous: true });
      }
      return (submission.result = result);
    } catch (error) {
      if (error.ambiguous === false || (error.status >= 400 && error.status < 500)) {
        submission.uncertain = false; rememberDiscussionSubmission(context); throw error;
      }
      submission.uncertain = true;
      if (!isAnalysisDiscussionCurrent(context)) throw error;
      setAnalysisDiscussionFeedback(context, "连接中断，正在核对评论是否已发表…", "Connection interrupted. Checking whether your comment was posted…");
      const saved = await findAnalysisDiscussionSubmission(context, submission);
      if (saved) return (submission.result = saved);
      if (attempt === 1) throw error;
      setAnalysisDiscussionFeedback(context, "尚未查到评论，正在重试发表…", "No saved comment found. Retrying…");
    }
  }
}

async function saveAnalysisDiscussion(event) {
  event.preventDefault();
  const context = state.analysisDiscussion;
  if (!context || context.saving) return;
  if (!isAnalysisDiscussionCurrent(context)) {
    setAnalysisDiscussionFeedback(context,
      "当前 Issue 已切换，请复制草稿后重新打开讨论。",
      "The Issue has changed. Copy your draft and reopen the discussion.", true);
    return;
  }
  if (context.status !== "ready") {
    setAnalysisDiscussionFeedback(context, "讨论尚未加载成功，请重试加载。草稿已保留。", "Load the discussion before posting. Your draft is preserved.", true);
    return;
  }
  const discussion = String($("#analysisDiscussionNote")?.value || "").trim();
  if (!context?.issueId || !discussion) {
    setAnalysisDiscussionFeedback(context, "请输入讨论内容。", "Enter a comment.", true);
    return;
  }
  if ($("#analysisDiscussionSubmit")?.disabled || $("#analysisDiscussionComposer")?.hidden) return;
  setAnalysisDiscussionFeedback(context, "正在发表评论…", "Posting comment…");
  context.sentDraft = persistAnalysisDiscussionDraft(context);
  context.saving = true;
  updateAnalysisDiscussionComposerAccess();
  let committed = false;
  try {
    const payload = {
      body: discussion,
      reply_to_id: context.replyTo?.id || null,
    };
    if (context.reviewOrigin) payload.review_context = context.reviewOrigin;
    let result;
    if (context.kind === "intent") {
      result = await postAnalysisDiscussionRequest(
        `/api/intent-datasets/${encodeURIComponent(context.intentDatasetId)}/cases/${encodeURIComponent(context.intentCaseId)}/comments`,
        {
          method: "POST",
          body: JSON.stringify({
            body: discussion,
            reply_to_id: context.replyTo?.id || null,
          }),
        }
      );
    } else if (context.pendingImages?.length) {
      const form = new FormData();
      payload.attachment_tokens = context.pendingImages.map((item) => item.token);
      form.append("payload", JSON.stringify(payload));
      context.pendingImages.forEach((item, index) => {
        form.append("attachments", item.file, item.file.name || `comment-${index + 1}.png`);
      });
      result = await postIssueDiscussion(context, payload, `/api/cases/${encodeURIComponent(context.issueId)}/discussion-with-attachments`, {
        method: "POST",
        body: form,
        headers: { "X-RA-Triage-Request": "comment-v1" },
      });
    } else {
      result = await postIssueDiscussion(context, payload, `/api/cases/${encodeURIComponent(context.issueId)}/discussion`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    if (!Number.isInteger(Number(result?.comment?.id)) || Number(result.comment.id) <= 0) {
      throw apiResponseError("服务器未返回有效的评论确认。", "The server did not return a valid comment receipt.", { ambiguous: true });
    }
    committed = true;
    const matchingComposer = retireDiscussionDraft(context);
    if (matchingComposer && matchingComposer !== context) {
      try {
        clearPostedDiscussionComposer(matchingComposer);
        if (!matchingComposer.comments.some(item => Number(item.id) === Number(result.comment.id))) matchingComposer.comments.push(result.comment);
        renderAnalysisDiscussionThread();
        setAnalysisDiscussionFeedback(matchingComposer, "评论已发表。", "Comment posted.");
      } catch (_) {
        matchingComposer.status = "posted";
        updateAnalysisDiscussionComposerAccess();
      }
    }
    acknowledgeLocalChange(result);
    if (!isAnalysisDiscussionCurrent(context)) {
      setAnalysisDiscussionFeedback(context,
        "评论已发表到原讨论。页面已切换，草稿仍保留在编辑框中，请重新打开讨论。",
        "Comment posted to the original discussion. The page has changed; your draft remains in the editor. Reopen the discussion.");
      return;
    }
    if (!(context.comments || []).some((item) => Number(item.id) === Number(result.comment.id))) context.comments.push(result.comment);
    if (context.kind === "intent" && state.intentLabeling?.caseId === context.intentCaseId) {
      state.intentLabeling.caseData ||= {};
      state.intentLabeling.caseData.collaboration ||= {};
      state.intentLabeling.caseData.collaboration.comments = context.comments;
      if (typeof renderIntentCollaboration === "function") renderIntentCollaboration();
    }
    if (context.kind !== "intent" && state.caseLabeling?.caseData?.issue_id === context.issueId) {
      state.caseLabeling.caseData.comments = context.comments;
    }
    clearPostedDiscussionComposer(context);
    renderAnalysisDiscussionThread();
    updateAnalysisDiscussionCount(
      context.issueId,
      context.runId,
      Number(result.comment_count ?? context.comments.length)
    );
    const queued = result?.notification?.queued?.length || 0;
    if (result.idempotent_replay) setAnalysisDiscussionFeedback(context,
      "已确认评论已发表，无需重复提交。", "Confirmed: your comment is posted. No need to submit again.");
    else setAnalysisDiscussionFeedback(context,
      `评论已发表${queued ? `；DChat 通知已排队 ${queued} 人` : ""}。`,
      `Comment posted.${queued ? ` DChat notifications queued for ${queued} ${queued === 1 ? "person" : "people"}.` : ""}`);
  } catch (error) {
    if (state.analysisDiscussion === context) {
      const zh = String(error.messages?.zh || error.message || "");
      const en = String(error.messages?.en || error.message || "");
      if (committed) {
        context.status = "posted";
        setAnalysisDiscussionFeedback(context,
          "评论已发表，但界面刷新失败。请重新打开讨论查看。", "Your comment is posted, but the display could not refresh. Reopen the discussion to view it.", true);
      }
      else if (!context.submission?.uncertain && (error.ambiguous === false || (error.status >= 400 && error.status < 500))) setAnalysisDiscussionFeedback(context,
        `评论未发表，草稿和回复对象已保留。${zh}`, `Comment not posted. Your draft and reply target are preserved. ${en}`, true);
      else setAnalysisDiscussionFeedback(context,
        `未能确认评论发表成功，草稿和回复对象已保留。重试会先核对，避免重复发表。${zh ? `（${zh}）` : ""}`,
        `Could not confirm posting. Your draft and reply target are preserved. Retrying checks for a saved comment first to avoid duplicates.${en ? ` (${en})` : ""}`, true);
    }
  } finally {
    context.saving = false;
    if (state.analysisDiscussion === context) {
      updateAnalysisDiscussionComposerAccess();
      if (isAnalysisDiscussionCurrent(context) && context.status !== "posted") renderAnalysisDiscussionThread();
    }
  }
}

function clearPostedDiscussionComposer(context) {
  if (state.analysisDiscussion !== context) return;
  context.clearingSentDraft = true;
  try {
    $("#analysisDiscussionNote").value = "";
    resetAnalysisDiscussionReply(context);
    clearAnalysisDiscussionImages();
    context.submission = null;
    context.preview = false;
    $("#analysisDiscussionNote").hidden = false;
    $("#analysisDiscussionPreview").hidden = true;
    $("[data-comment-preview-toggle]").innerHTML = discussionActionText("预览", "Preview");
    renderAnalysisDiscussionReplyContext();
    updateReviewMentionComposer($("#analysisDiscussionNote"), $("#analysisDiscussionMentionComposer"));
  } finally { context.clearingSentDraft = false; }
  persistAnalysisDiscussionDraft(context);
}

function bindAnalysisDiscussionEnterSubmit() {
  const textarea = $("#analysisDiscussionNote");
  const form = $("#analysisDiscussionForm");
  const submit = $("#analysisDiscussionSubmit");
  if (!textarea || !form || textarea.dataset.enterSubmitBound === "1") return;
  textarea.dataset.enterSubmitBound = "1";
  textarea.addEventListener("keydown", (event) => {
    if (
      event.defaultPrevented
      || isImeComposing(event)
      || event.key !== "Enter"
      || event.shiftKey
      || !(event.ctrlKey || event.metaKey)
    ) return;
    event.preventDefault();
    if (!submit?.disabled) form.requestSubmit(submit);
  });
}
