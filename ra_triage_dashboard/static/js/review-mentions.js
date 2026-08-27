/* Review @mention composer. Uses only identities already present in Review facets. */

const REVIEW_MENTION_RE = /(^|[^A-Za-z0-9._@-])@(?:\{([A-Za-z0-9._-]{1,64})\}|([A-Za-z0-9._-]{1,64}))/g;

function reviewMentions(value) {
  const mentions = [];
  const seen = new Set();
  for (const match of String(value || "").matchAll(REVIEW_MENTION_RE)) {
    const username = String(match[2] || match[3] || "").toLowerCase();
    if (!username || ["all", "everyone", "group", "here"].includes(username) || seen.has(username)) continue;
    seen.add(username);
    mentions.push(username);
  }
  return mentions;
}

function reviewMentionCandidates() {
  const names = [
    ...(state.reviewers || []).map((item) => item.name),
    ...(state.workAssignees || []).map((item) => item.username),
  ];
  const current = String(state.session?.username || "").toLowerCase();
  return [...new Set(names.map((item) => String(item || "").trim().toLowerCase()))]
    .filter((item) => /^[A-Za-z0-9._-]{1,64}$/.test(item) && item !== current)
    .slice(0, 8);
}

function updateReviewMentionComposer(textarea = $("#annotationNote")) {
  const root = $("#reviewMentionComposer");
  if (!root || !textarea) return;
  const mentions = reviewMentions(textarea.value);
  const enabled = Boolean(state.config?.review_notifications?.enabled);
  const verified = Boolean(state.session?.verified);
  const status = !mentions.length
    ? uiText("输入 @ldap 提及同事", "Type @ldap to mention a teammate")
    : !enabled
      ? uiText(`已识别 ${mentions.length} 人 · DChat 尚未启用`, `${mentions.length} mentioned · DChat disabled`)
      : !verified
        ? uiText(`已识别 ${mentions.length} 人 · 需从 SSO 入口保存才会通知`, `${mentions.length} mentioned · verified SSO required`)
        : uiText(`保存后将异步通知 ${mentions.length} 人`, `${mentions.length} will be notified after save`);
  const candidates = reviewMentionCandidates().filter((name) => !mentions.includes(name));
  root.innerHTML = `
    <span class="review-mention-status">${escapeHtml(status)}</span>
    ${mentions.map((name) => `<span class="review-mention-chip is-selected">@${escapeHtml(name)}</span>`).join("")}
    ${candidates.map((name) => `<button class="review-mention-chip" type="button" data-review-mention="${escapeHtml(name)}">@${escapeHtml(name)}</button>`).join("")}`;
  root.querySelectorAll("[data-review-mention]").forEach((button) => {
    button.addEventListener("click", () => {
      const separator = textarea.value && !/\s$/.test(textarea.value) ? " " : "";
      const insertion = `${separator}@${button.dataset.reviewMention} `;
      const start = textarea.selectionStart ?? textarea.value.length;
      const end = textarea.selectionEnd ?? start;
      textarea.setRangeText(insertion, start, end, "end");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.focus();
    });
  });
}

function bindReviewMentionComposer(textarea = $("#annotationNote")) {
  if (!textarea || textarea.dataset.reviewMentionBound === "1") return;
  textarea.dataset.reviewMentionBound = "1";
  textarea.addEventListener("input", () => updateReviewMentionComposer(textarea));
  updateReviewMentionComposer(textarea);
}
