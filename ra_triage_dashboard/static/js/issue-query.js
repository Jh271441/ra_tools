/* ra_triage_dashboard/static/js/issue-query.js
 * Multi-Issue query parser and dialog.
 *
 * The normal search box remains a free-text filter.  This dialog is an
 * explicit, exact Issue filter so pasted lists do not get mixed with scene
 * or reason keyword search.  It is intentionally dependency-light and is
 * loaded before the other review modules; handlers run only after bootstrap.
 */

const ISSUE_QUERY_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{2,127}$/;
const ISSUE_QUERY_SPLIT_RE = /[\s,，、;；]+/;

function parseIssueIdsInput(raw) {
  const text = String(raw ?? "")
    .replace(/[，、；;]/g, ",")
    .replace(/\r?\n/g, ",");
  const ids = [];
  const invalid = [];
  const seen = new Set();
  for (const part of text.split(ISSUE_QUERY_SPLIT_RE)) {
    const token = String(part || "")
      .trim()
      .replace(/^[([\]{<\"']+|[)\]}>\"'.,，、;；]+$/g, "");
    if (!token) continue;
    const urlMatch = token.match(/(?:\/issue\/|[?&]issue=)([A-Za-z0-9][A-Za-z0-9_-]{2,127})/i);
    const issueId = urlMatch ? urlMatch[1] : token;
    if (!ISSUE_QUERY_ID_RE.test(issueId)) {
      invalid.push(token);
      continue;
    }
    if (!seen.has(issueId)) {
      seen.add(issueId);
      ids.push(issueId);
    }
  }
  return { ids, invalid };
}

function issueQueryFeedback(parsed) {
  const ids = parsed?.ids || [];
  const invalid = parsed?.invalid || [];
  if (invalid.length) {
    return uiText(
      `已识别 ${ids.length} 个 Issue；无法识别：${invalid.slice(0, 4).join("、")}${invalid.length > 4 ? "…" : ""}`,
      `${ids.length} Issues recognized; invalid: ${invalid.slice(0, 4).join(", ")}${invalid.length > 4 ? "…" : ""}`
    );
  }
  return uiText(
    ids.length ? `已识别 ${ids.length} 个 Issue（重复项已去重）` : "输入为空，将清除多 Issue 条件",
    ids.length ? `${ids.length} Issues recognized (duplicates removed)` : "Empty input will clear the multi-Issue filter"
  );
}

function renderIssueQueryFeedback() {
  const input = $("#issueQueryInput");
  const feedback = $("#issueQueryFeedback");
  if (!input || !feedback) return { ids: [], invalid: [] };
  const parsed = parseIssueIdsInput(input.value);
  feedback.textContent = issueQueryFeedback(parsed);
  feedback.classList.toggle("is-error", parsed.invalid.length > 0);
  feedback.classList.toggle("is-ready", !parsed.invalid.length && parsed.ids.length > 0);
  return parsed;
}

function updateIssueQueryButton() {
  const button = $("#openIssueQueryButton");
  if (!button) return;
  const count = Array.isArray(state.reviewIssueIds) ? state.reviewIssueIds.length : 0;
  button.dataset.issueCount = String(count);
  button.classList.toggle("has-issues", count > 0);
  button.title = count
    ? uiText(`已设置 ${count} 个 Issue`, `${count} Issues selected`)
    : uiText("按 Issue 列表查询", "Query an Issue list");
}

function openIssueQueryDialog() {
  const dialog = $("#issueQueryDialog");
  const input = $("#issueQueryInput");
  if (!dialog || !input) return;
  input.value = (state.reviewIssueIds || []).join("\n");
  renderIssueQueryFeedback();
  if (!dialog.open) dialog.showModal();
  window.requestAnimationFrame(() => input.focus());
}

async function applyIssueQuery() {
  const parsed = renderIssueQueryFeedback();
  if (parsed.invalid.length) {
    showToast(uiText("请先修正无法识别的 Issue。", "Fix invalid Issue tokens first."), true);
    return;
  }
  state.reviewIssueIds = parsed.ids;
  state.casePage = 1;
  state.selectedId = "";
  state.selectedCase = null;
  if ($("#searchInput")) $("#searchInput").value = "";
  updateIssueQueryButton();
  closeDialog("issueQueryDialog");
  await reloadReviewGallery({ includeOverview: true, historyMode: "push" });
}

function clearIssueQuery() {
  const input = $("#issueQueryInput");
  if (input) input.value = "";
  renderIssueQueryFeedback();
}

function bindIssueQueryControls() {
  $("#openIssueQueryButton")?.addEventListener("click", openIssueQueryDialog);
  $("#issueQueryInput")?.addEventListener("input", renderIssueQueryFeedback);
  $("#clearIssueQueryButton")?.addEventListener("click", clearIssueQuery);
  $("#applyIssueQueryButton")?.addEventListener("click", () => {
    applyIssueQuery().catch((error) => showToast(error.message, true));
  });
  updateIssueQueryButton();
}
