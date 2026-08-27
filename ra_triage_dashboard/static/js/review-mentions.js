/* Shared @mention composer backed by the server-managed notification directory. */

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

function reviewMentionCandidates(query = "") {
  const current = String(state.session?.username || "").toLowerCase();
  const normalizedQuery = String(query || "").toLowerCase();
  return [...new Set((state.mentionUsers || [])
    .filter((item) => item.enabled !== false)
    .map((item) => String(item.username || "").trim().toLowerCase()))]
    .filter((item) =>
      /^[A-Za-z0-9._-]{1,64}$/.test(item) &&
      item !== current &&
      (!normalizedQuery || item.startsWith(normalizedQuery))
    );
}

function activeMentionQuery(textarea) {
  const cursor = textarea.selectionStart ?? textarea.value.length;
  const prefix = textarea.value.slice(0, cursor);
  const match = prefix.match(/(?:^|\s)@(?:\{)?([A-Za-z0-9._-]{0,64})$/);
  return match
    ? { query: String(match[1] || "").toLowerCase(), start: cursor - match[0].trimStart().length, end: cursor }
    : null;
}

function updateReviewMentionComposer(
  textarea = $("#annotationNote"),
  root = $("#reviewMentionComposer")
) {
  if (!root || !textarea) return;
  const mentions = reviewMentions(textarea.value);
  const allowed = new Set((state.mentionUsers || [])
    .filter((item) => item.enabled !== false)
    .map((item) => String(item.username || "").trim().toLowerCase()));
  const unsupported = mentions.filter((name) => !allowed.has(name));
  const enabled = Boolean(state.config?.review_notifications?.enabled);
  const verified = Boolean(state.session?.verified);
  const status = unsupported.length
    ? uiText(
        `目录外人员无法保存：${unsupported.map((name) => `@${name}`).join("、")}`,
        `Not in mention directory: ${unsupported.map((name) => `@${name}`).join(", ")}`
      )
    : !mentions.length
    ? uiText("输入 @ldap 提及同事", "Type @ldap to mention a teammate")
    : !enabled
      ? uiText(`已识别 ${mentions.length} 人 · DChat 尚未启用`, `${mentions.length} mentioned · DChat disabled`)
      : !verified
        ? uiText(`已识别 ${mentions.length} 人 · 需从 SSO 入口保存才会通知`, `${mentions.length} mentioned · verified SSO required`)
        : uiText(`保存后将异步通知 ${mentions.length} 人`, `${mentions.length} will be notified after save`);
  const activeQuery = activeMentionQuery(textarea);
  const candidates = reviewMentionCandidates(activeQuery?.query)
    .filter((name) => !mentions.includes(name))
    .slice(0, 8);
  root.innerHTML = `
    <span class="review-mention-status">${escapeHtml(status)}</span>
    ${mentions.map((name) => `<span class="review-mention-chip is-selected${allowed.has(name) ? "" : " is-invalid"}">@${escapeHtml(name)}</span>`).join("")}
    ${candidates.map((name) => `<button class="review-mention-chip" type="button" data-review-mention="${escapeHtml(name)}">@${escapeHtml(name)}</button>`).join("")}`;
  root.querySelectorAll("[data-review-mention]").forEach((button) => {
    button.addEventListener("click", () => {
      const active = activeMentionQuery(textarea);
      const separator = !active && textarea.value && !/\s$/.test(textarea.value) ? " " : "";
      const insertion = `${separator}@${button.dataset.reviewMention} `;
      const start = active?.start ?? textarea.selectionStart ?? textarea.value.length;
      const end = active?.end ?? textarea.selectionEnd ?? start;
      textarea.setRangeText(insertion, start, end, "end");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.focus();
    });
  });
}

function bindReviewMentionComposer(
  textarea = $("#annotationNote"),
  root = $("#reviewMentionComposer")
) {
  if (!textarea || textarea.dataset.reviewMentionBound === "1") return;
  textarea.dataset.reviewMentionBound = "1";
  textarea.addEventListener("input", () => updateReviewMentionComposer(textarea, root));
  updateReviewMentionComposer(textarea, root);
}
