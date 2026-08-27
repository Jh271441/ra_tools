/* Shared @mention autocomplete backed by the server-managed notification directory. */

const REVIEW_MENTION_RE = /(^|[^A-Za-z0-9._@-])@(?:\{([A-Za-z0-9._-]{1,64})\}|([A-Za-z0-9._-]{1,64}))/g;
const reviewMentionComposerStates = new WeakMap();
const REVIEW_MENTION_CARET_STYLE_PROPERTIES = [
  "boxSizing", "width", "height", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
  "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
  "fontFamily", "fontSize", "fontStyle", "fontWeight", "fontVariant", "lineHeight",
  "letterSpacing", "textAlign", "textIndent", "textTransform", "tabSize", "wordSpacing",
];

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
  const normalizedQuery = String(query || "").toLowerCase();
  return [...new Set((state.mentionUsers || [])
    .filter((item) => item.enabled !== false)
    .map((item) => String(item.username || "").trim().toLowerCase()))]
    .filter((item) =>
      /^[A-Za-z0-9._-]{1,64}$/.test(item) &&
      (!normalizedQuery || item.includes(normalizedQuery))
    )
    .sort((left, right) => {
      const leftPrefix = left.startsWith(normalizedQuery) ? 0 : 1;
      const rightPrefix = right.startsWith(normalizedQuery) ? 0 : 1;
      return leftPrefix - rightPrefix || left.localeCompare(right);
    });
}

function activeMentionQuery(textarea) {
  const cursor = textarea.selectionStart ?? textarea.value.length;
  const prefix = textarea.value.slice(0, cursor);
  const match = prefix.match(/(^|[^A-Za-z0-9._@-])@(?:\{)?([A-Za-z0-9._-]{0,64})$/);
  if (!match) return null;
  const boundary = String(match[1] || "");
  const token = match[0].slice(boundary.length);
  return {
    query: String(match[2] || "").toLowerCase(),
    start: cursor - token.length,
    end: cursor,
  };
}

function reviewMentionComposerState(textarea) {
  if (!reviewMentionComposerStates.has(textarea)) {
    reviewMentionComposerStates.set(textarea, {
      activeIndex: 0,
      dismissedStart: null,
    });
  }
  return reviewMentionComposerStates.get(textarea);
}

function reviewMentionCaretAnchor(textarea, tokenStart) {
  const rect = textarea.getBoundingClientRect();
  const computed = window.getComputedStyle(textarea);
  const mirror = document.createElement("div");
  mirror.setAttribute("aria-hidden", "true");
  Object.assign(mirror.style, {
    position: "fixed",
    visibility: "hidden",
    pointerEvents: "none",
    overflow: "hidden",
    whiteSpace: "pre-wrap",
    overflowWrap: "break-word",
    wordBreak: "normal",
    left: `${rect.left}px`,
    top: `${rect.top}px`,
  });
  REVIEW_MENTION_CARET_STYLE_PROPERTIES.forEach((property) => {
    mirror.style[property] = computed[property];
  });
  mirror.textContent = textarea.value.slice(0, tokenStart);
  const marker = document.createElement("span");
  marker.textContent = textarea.value.slice(tokenStart, tokenStart + 1) || "\u200b";
  mirror.append(marker);
  document.body.append(mirror);
  mirror.scrollTop = textarea.scrollTop;
  mirror.scrollLeft = textarea.scrollLeft;
  const markerRect = marker.getBoundingClientRect();
  const parsedLineHeight = Number.parseFloat(computed.lineHeight);
  const parsedFontSize = Number.parseFloat(computed.fontSize) || 14;
  mirror.remove();
  return {
    left: markerRect.left,
    top: markerRect.top,
    lineHeight: Number.isFinite(parsedLineHeight) ? parsedLineHeight : parsedFontSize * 1.2,
  };
}

function positionReviewMentionPopover(textarea, root, active = activeMentionQuery(textarea)) {
  const popover = root?.querySelector(".review-mention-popover");
  if (!popover || !active) return;
  const anchor = reviewMentionCaretAnchor(textarea, active.start);
  const viewportMargin = 8;
  const gap = 6;
  const textareaWidth = textarea.getBoundingClientRect().width;
  const width = Math.min(430, Math.max(220, textareaWidth), window.innerWidth - viewportMargin * 2);
  const spaceAbove = Math.max(0, anchor.top - viewportMargin);
  const spaceBelow = Math.max(0, window.innerHeight - anchor.top - anchor.lineHeight - viewportMargin);
  const preferredHeight = Math.min(290, popover.scrollHeight || 290);
  const opensUp = spaceBelow < preferredHeight && spaceAbove > spaceBelow;
  const availableSpace = Math.max(112, (opensUp ? spaceAbove : spaceBelow) - gap);
  const left = Math.min(
    Math.max(viewportMargin, anchor.left),
    Math.max(viewportMargin, window.innerWidth - width - viewportMargin)
  );
  popover.style.setProperty("--review-mention-left", `${Math.round(left)}px`);
  popover.style.setProperty(
    "--review-mention-top",
    `${Math.round(opensUp ? anchor.top - gap : anchor.top + anchor.lineHeight + gap)}px`
  );
  popover.style.setProperty("--review-mention-width", `${Math.round(width)}px`);
  popover.style.setProperty("--review-mention-space", `${Math.floor(availableSpace)}px`);
  popover.classList.toggle("opens-up", opensUp);
}

function closeReviewMentionComposer(textarea, root, { preserveTrigger = false } = {}) {
  if (!textarea || !root) return;
  const composer = reviewMentionComposerState(textarea);
  const active = activeMentionQuery(textarea);
  composer.dismissedStart = preserveTrigger && active ? active.start : null;
  composer.activeIndex = 0;
  root.replaceChildren();
  root.hidden = true;
}

function insertReviewMention(textarea, root, username) {
  const active = activeMentionQuery(textarea);
  if (!active) return;
  textarea.setRangeText(`@${username} `, active.start, active.end, "end");
  reviewMentionComposerState(textarea).dismissedStart = null;
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  textarea.focus();
  closeReviewMentionComposer(textarea, root);
}

function reviewMentionStatus(mentions, unsupported) {
  const enabled = Boolean(state.config?.review_notifications?.enabled);
  const verified = Boolean(state.session?.verified);
  if (unsupported.length) {
    return {
      text: uiText(
        `目录外人员无法保存：${unsupported.map((name) => `@${name}`).join("、")}`,
        `Not in mention directory: ${unsupported.map((name) => `@${name}`).join(", ")}`
      ),
      invalid: true,
    };
  }
  if (!mentions.length) return { text: "", invalid: false };
  if (!enabled) {
    return {
      text: uiText(`已识别 ${mentions.length} 人 · DChat 尚未启用`, `${mentions.length} mentioned · DChat disabled`),
      invalid: false,
    };
  }
  if (!verified) {
    return {
      text: uiText(`已识别 ${mentions.length} 人 · 需从 SSO 入口保存才会通知`, `${mentions.length} mentioned · verified SSO required`),
      invalid: false,
    };
  }
  return {
    text: uiText(`保存后将异步通知 ${mentions.length} 人`, `${mentions.length} will be notified after save`),
    invalid: false,
  };
}

function updateReviewMentionComposer(
  textarea = $("#annotationNote"),
  root = $("#reviewMentionComposer")
) {
  if (!root || !textarea) return;
  const composer = reviewMentionComposerState(textarea);
  const parsedMentions = reviewMentions(textarea.value);
  const allowed = new Set((state.mentionUsers || [])
    .filter((item) => item.enabled !== false)
    .map((item) => String(item.username || "").trim().toLowerCase()));
  const active = activeMentionQuery(textarea);
  if (!active) composer.dismissedStart = null;
  // The token under the caret is a search query until the user inserts a
  // delimiter or chooses a result. Do not flag a partial username as invalid and
  // do not hide an exact match merely because the parser can already read it.
  const mentions = active
    ? parsedMentions.filter((name) => name !== active.query)
    : parsedMentions;
  const unsupported = mentions.filter((name) => !allowed.has(name));
  const status = reviewMentionStatus(mentions, unsupported);
  const dismissed = active && composer.dismissedStart === active.start;
  const candidates = active && !dismissed
    ? reviewMentionCandidates(active.query).filter((name) => !mentions.includes(name)).slice(0, 8)
    : [];
  composer.activeIndex = Math.min(Math.max(0, composer.activeIndex), Math.max(0, candidates.length - 1));
  const current = String(state.session?.username || "").trim().toLowerCase();
  const statusMarkup = status.text
    ? `<span class="review-mention-status${status.invalid ? " is-invalid" : ""}">${escapeHtml(status.text)}</span>`
    : "";
  const popoverMarkup = active && !dismissed
    ? `<div class="review-mention-popover" role="listbox" aria-label="${escapeHtml(uiText("可 @ 人员", "Mention users"))}">
        <div class="review-mention-search-row">
          <span class="review-mention-search-icon" aria-hidden="true">@</span>
          <span class="review-mention-search-query">${escapeHtml(active.query || uiText("搜索可 @ 人员", "Search mention users"))}</span>
          <kbd>Esc</kbd>
        </div>
        <div class="review-mention-options">
          ${candidates.length ? candidates.map((name, index) => `
            <button class="review-mention-option${index === composer.activeIndex ? " is-active" : ""}" type="button" role="option" aria-selected="${index === composer.activeIndex ? "true" : "false"}" data-review-mention="${escapeHtml(name)}" data-review-mention-index="${index}">
              <span class="review-mention-avatar" aria-hidden="true">${escapeHtml(name.slice(0, 1).toUpperCase())}</span>
              <strong>@${escapeHtml(name)}</strong>
              ${name === current ? `<small>${escapeHtml(uiText("自己", "You"))}</small>` : ""}
            </button>`).join("") : `<div class="review-mention-empty">${escapeHtml(uiText("没有匹配的可 @ 人员", "No matching mention user"))}</div>`}
        </div>
      </div>`
    : "";
  root.innerHTML = `${statusMarkup}${popoverMarkup}`;
  root.hidden = !statusMarkup && !popoverMarkup;
  if (popoverMarkup) positionReviewMentionPopover(textarea, root, active);
  root.querySelectorAll("[data-review-mention]").forEach((button) => {
    button.addEventListener("pointerdown", (event) => event.preventDefault());
    button.addEventListener("mouseenter", () => {
      composer.activeIndex = Number(button.dataset.reviewMentionIndex) || 0;
      root.querySelectorAll("[data-review-mention]").forEach((option, index) => {
        option.classList.toggle("is-active", index === composer.activeIndex);
        option.setAttribute("aria-selected", index === composer.activeIndex ? "true" : "false");
      });
    });
    button.addEventListener("click", () => insertReviewMention(textarea, root, button.dataset.reviewMention));
  });
}

function bindReviewMentionComposer(
  textarea = $("#annotationNote"),
  root = $("#reviewMentionComposer")
) {
  if (!textarea || !root || textarea.dataset.reviewMentionBound === "1") return;
  textarea.dataset.reviewMentionBound = "1";
  textarea.setAttribute("autocomplete", "off");
  const composer = reviewMentionComposerState(textarea);
  textarea.addEventListener("input", () => {
    composer.activeIndex = 0;
    updateReviewMentionComposer(textarea, root);
  });
  textarea.addEventListener("keydown", (event) => {
    const active = activeMentionQuery(textarea);
    const options = [...root.querySelectorAll("[data-review-mention]")];
    const popoverOpen = Boolean(active && !root.hidden && root.querySelector(".review-mention-popover"));
    if (event.key === "Escape" && popoverOpen) {
      event.preventDefault();
      event.stopPropagation();
      closeReviewMentionComposer(textarea, root, { preserveTrigger: true });
      return;
    }
    if (!popoverOpen || !options.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const delta = event.key === "ArrowDown" ? 1 : -1;
      composer.activeIndex = (composer.activeIndex + delta + options.length) % options.length;
      updateReviewMentionComposer(textarea, root);
      root.querySelector(".review-mention-option.is-active")?.scrollIntoView({ block: "nearest" });
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      const selected = options[composer.activeIndex];
      if (!selected) return;
      event.preventDefault();
      insertReviewMention(textarea, root, selected.dataset.reviewMention);
    }
  });
  ["click", "focus", "select"].forEach((eventName) => {
    textarea.addEventListener(eventName, () => updateReviewMentionComposer(textarea, root));
  });
  const reposition = () => positionReviewMentionPopover(textarea, root);
  textarea.addEventListener("scroll", reposition, { passive: true });
  window.addEventListener("resize", reposition, { passive: true });
  window.addEventListener("scroll", reposition, { passive: true, capture: true });
  textarea.addEventListener("blur", () => {
    window.setTimeout(() => {
      if (!root.contains(document.activeElement)) closeReviewMentionComposer(textarea, root);
    }, 0);
  });
  updateReviewMentionComposer(textarea, root);
}
