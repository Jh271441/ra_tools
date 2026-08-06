/* ra_triage_dashboard/static/js/review-draft.js
 * Review draft storage and annotation helpers
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
const REVIEW_DRAFT_FIELDS = [
  "label",
  "review_status",
  "is_excluded",
  "tags",
  "missing_evidence",
  "note",
  "author",
];

function currentReviewRunId(caseData) {
  const selected = String(state.selectedRunId || "").trim();
  if (selected) return selected;
  // An empty selection means the legacy/unbound Review stream.  Do not
  // silently attach those records to whichever prediction happens to be
  // first in the case payload.
  return "";
}

function reviewAnnotationsForCurrentRun(caseData) {
  const runId = currentReviewRunId(caseData);
  const annotations = caseData?.annotations || [];
  const bound = annotations.filter(
    (annotation) => String(annotation.model_run_id || "").trim() === runId
  );
  if (runId && bound.length) return bound;
  // Existing pre-run-binding Reviews have no model_run_id.  Keep them
  // visible as a compatibility fallback until this Issue is first reviewed
  // in the selected Run; once a bound version exists, never mix the streams.
  return runId
    ? annotations.filter((annotation) => !String(annotation.model_run_id || "").trim())
    : bound;
}

// The edit form is scoped to the selected Run, while the Issue-level history
// is a complete append-only audit trail across every model Run.
function reviewAnnotationsForAllRuns(caseData) {
  return [...(caseData?.annotations || [])].sort(
    (left, right) => Number(right?.id || 0) - Number(left?.id || 0)
  );
}

function currentReviewAnnotation(caseData) {
  return reviewAnnotationsForCurrentRun(caseData)[0] || {};
}

const REVIEW_DRAFT_STORAGE_PREFIX = "ra-triage-review-draft:v1:";
const REVIEW_DRAFT_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
function reviewDraftStorageKey(issueId, runId = "") {
  return `${REVIEW_DRAFT_STORAGE_PREFIX}${encodeURIComponent(String(issueId || ""))}:${encodeURIComponent(String(runId || "legacy"))}`;
}

function readReviewDraft(issueId, runId = "") {
  if (!issueId || typeof window === "undefined" || !window.localStorage) return null;
  const key = reviewDraftStorageKey(issueId, runId);
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const draft = JSON.parse(raw);
    const savedAt = Number(draft?.saved_at || 0);
    if (draft?.version !== 1 || !savedAt || Date.now() - savedAt > REVIEW_DRAFT_MAX_AGE_MS) {
      window.localStorage.removeItem(key);
      return null;
    }
    return draft;
  } catch {
    return null;
  }
}

function clearReviewDraft(issueId, runId = "") {
  if (!issueId || typeof window === "undefined" || !window.localStorage) return;
  try {
    window.localStorage.removeItem(reviewDraftStorageKey(issueId, runId));
  } catch {
    // Storage can be unavailable in private browsing; the Review itself still works.
  }
}

function annotationTimestamp(annotation) {
  const value = annotation?.updated_at || annotation?.created_at || "";
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function reviewDraftForCase(caseData) {
  const runId = currentReviewRunId(caseData);
  const draft = readReviewDraft(caseData?.issue_id, runId);
  if (!draft) return null;
  const serverAnnotation = reviewAnnotationsForCurrentRun(caseData)[0];
  if (serverAnnotation && Number(draft.saved_at) <= annotationTimestamp(serverAnnotation)) {
    clearReviewDraft(caseData.issue_id, runId);
    return null;
  }
  return draft;
}

function applyReviewDraft(annotation, draft) {
  if (!draft) return annotation || {};
  const next = { ...(annotation || {}), _review_draft: true };
  REVIEW_DRAFT_FIELDS.forEach((field) => {
    if (Object.prototype.hasOwnProperty.call(draft, field)) next[field] = draft[field];
  });
  return next;
}

function persistReviewDraft(caseData) {
  const form = $("#annotationForm");
  if (!caseData?.issue_id || !form || typeof window === "undefined" || !window.localStorage) return;
  const runId = state.reviewEditRunId || currentReviewRunId(caseData);
  const draft = {
    version: 1,
    issue_id: caseData.issue_id,
    model_run_id: runId,
    saved_at: Date.now(),
    label: state.selectedAnnotationLabel || "",
    review_status: $("#reviewStatusInput")?.value || "reviewed",
    is_excluded: Boolean($("#reviewExcludeInput")?.checked),
    tags: [...form.querySelectorAll('input[name="reviewTags"]:checked')].map((input) => input.value),
    missing_evidence: [...form.querySelectorAll('input[name="missingEvidence"]:checked')].map((input) => input.value),
    note: $("#annotationNote")?.value || "",
    author: $("#annotationAuthor")?.value || "",
  };
  try {
    window.localStorage.setItem(reviewDraftStorageKey(caseData.issue_id, runId), JSON.stringify(draft));
  } catch {
    // Draft persistence is best effort and must never block Review input.
  }
}

function bindReviewDraftLifecycle() {
  if (typeof window === "undefined" || window.__raTriageReviewDraftBound) return;
  window.__raTriageReviewDraftBound = true;
  window.addEventListener("beforeunload", () => {
    if (state.reviewFormDirty && state.selectedCase) persistReviewDraft(state.selectedCase);
  });
}

function currentReviewBaseAnnotationId(annotation, runId) {
  if (!annotation?.id) return null;
  const annotationRunId = String(annotation.model_run_id || "").trim();
  return annotationRunId === String(runId || "").trim()
    ? annotation.id
    : null;
}

function reviewRunLabel(runId) {
  const normalized = String(runId || "").trim();
  if (!normalized) return "未绑定 Model Run";
  const run = (state.modelRuns || []).find((item) => String(item.id) === normalized);
  return run?.name || normalized;
}

