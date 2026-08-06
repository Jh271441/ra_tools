/* ra_triage_dashboard/static/js/i18n.js
 * Locale runtime: t(), uiText(), applyDomI18n. Depends on I18N_MESSAGES from i18n-messages.js.
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function i18nLocale() {
  return state?.uiLanguage === "en" ? "en" : "zh";
}

/** Translate message key with optional {var} interpolation. */
function t(key, vars) {
  const locale = i18nLocale();
  const table = I18N_MESSAGES[locale] || I18N_MESSAGES.zh;
  let text = table[key];
  if (text == null) text = I18N_MESSAGES.zh[key];
  if (text == null) text = key;
  if (vars && typeof vars === "object") {
    for (const [name, value] of Object.entries(vars)) {
      text = String(text).split(`{${name}}`).join(String(value));
    }
  }
  return text;
}

/** Ad-hoc bilingual string (prefer catalog keys via t() for new code). */
function uiText(zh, en) {
  return i18nLocale() === "en" ? en : zh;
}

/**
 * Apply data-i18n* attributes under root.
 * data-i18n="key" → textContent
 * data-i18n-placeholder / data-i18n-title / data-i18n-aria-label / data-i18n-value
 */
function applyDomI18n(root = document) {
  if (!root?.querySelectorAll) return;
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    if (!key) return;
    // Dual-span shells are CSS-toggled; leave them alone.
    const onlyLang =
      el.childElementCount > 0 &&
      [...el.children].every(
        (c) =>
          c.classList?.contains("ui-lang-zh") || c.classList?.contains("ui-lang-en")
      );
    if (onlyLang) return;
    // Leaf labels / <option> / buttons without nested structure.
    if (el.childElementCount === 0) {
      el.textContent = t(key);
    }
  });
  const attrMap = [
    ["data-i18n-placeholder", "placeholder"],
    ["data-i18n-title", "title"],
    ["data-i18n-aria-label", "aria-label"],
    ["data-i18n-value", "value"],
  ];
  for (const [dataAttr, prop] of attrMap) {
    root.querySelectorAll(`[${dataAttr}]`).forEach((el) => {
      const key = el.getAttribute(dataAttr);
      if (!key) return;
      const text = t(key);
      if (prop === "placeholder") el.placeholder = text;
      else if (prop === "title") el.title = text;
      else if (prop === "aria-label") el.setAttribute("aria-label", text);
      else if (prop === "value" && "value" in el) el.value = text;
    });
  }
  // multi-filter placeholders + summaries from active locale
  root.querySelectorAll(".multi-filter").forEach((el) => {
    if (typeof updateMultiFilterSummary === "function") updateMultiFilterSummary(el);
  });
  // Static option labels with data-i18n on <option>
  root.querySelectorAll("option[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    if (key) el.textContent = t(key);
  });
}

function applyI18nPlaceholders(root = document) {
  root.querySelectorAll("input[data-placeholder-zh], textarea[data-placeholder-zh]").forEach((el) => {
    const zh = el.getAttribute("data-placeholder-zh") || "";
    const en = el.getAttribute("data-placeholder-en") || zh;
    el.placeholder = uiText(zh, en);
  });
}
