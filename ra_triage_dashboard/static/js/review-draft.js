/* ra_triage_dashboard/static/js/review-draft.js
 * Review draft storage and annotation helpers
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
const REVIEW_DRAFT_FIELDS = [
  "model_review_status",
  "label",
  "expected_output",
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

// A blind-task binding applies only to assigned reviewers; anyone else keeps
// editing the ordinary Review stream for the selected Run.
function reviewWorkSplitBinding(caseData) {
  const assignment = caseData?.review_assignment;
  if (assignment?.mode !== "blind" || !assignment?.assigned) return "";
  return String(assignment.split_id || "").trim();
}

function reviewAnnotationsForCurrentRun(caseData) {
  const runId = currentReviewRunId(caseData);
  const annotations = caseData?.annotations || [];
  let bound = annotations.filter(
    (annotation) => String(annotation.model_run_id || "").trim() === runId
  );
  const workSplitId = reviewWorkSplitBinding(caseData);
  const verifiedReviewer = state.session?.verified
    ? String(state.session?.username || "").trim().toLowerCase()
    : "";
  if (verifiedReviewer) {
    bound = bound.filter(
      (annotation) => String(annotation.author || "").trim().toLowerCase() === verifiedReviewer
    );
  }
  if (workSplitId) {
    const currentUser = verifiedReviewer || String(state.session?.username || "").trim().toLowerCase();
    bound = bound.filter(
      (annotation) =>
        String(annotation.work_split_id || "").trim() === workSplitId &&
        String(annotation.author || "").trim().toLowerCase() === currentUser
    );
  } else {
    // Single-review assignments and unassigned Issues share the ordinary
    // stream. Historical blind-split versions stay visible in History, but
    // must never become the edit head for this stream.
    bound = bound.filter(
      (annotation) => !String(annotation.work_split_id || "").trim()
    );
  }
  // A selected Run is an explicit Review namespace.  Do not fall back to a
  // legacy unbound annotation when that Run has not been reviewed yet; doing
  // so makes another person's/Run's Review look like it belongs here.
  if (runId) return bound;
  // With no selected Run, preserve the legacy/unbound editing stream.
  return bound;
}

// The edit form is scoped to the selected Run, while the Issue-level history
// is a complete append-only audit trail across every model Run.
function reviewAnnotationsForAllRuns(caseData) {
  return [...(caseData?.annotations || [])].sort(
    (left, right) => Number(right?.id || 0) - Number(left?.id || 0)
  );
}

function currentReviewSourceSuggestion(caseData) {
  const suggestion = caseData?.issue_tag_suggestion;
  const annotation = suggestion?.annotation;
  if (!suggestion || !annotation || !Array.isArray(annotation.tags)) return null;
  // A historical source is only an unsaved form default. A Review in the
  // selected Run always wins and remains the sole persisted/auditable record.
  if (reviewAnnotationsForCurrentRun(caseData).length) return null;
  return suggestion;
}

function currentReviewAnnotation(caseData) {
  return (
    reviewAnnotationsForCurrentRun(caseData)[0] ||
    currentReviewSourceSuggestion(caseData)?.annotation ||
    {}
  );
}

// The detail form must remain bound to the selected Run. There is one safe
// exception when choosing its initial Tag state: Gallery/analysis can display
// legacy and prior-Run Review evidence when this Run has no own Review. If the
// form starts empty and is saved, the new bound version would otherwise hide
// that historical environment/self-intent evidence from the current Run.
//
// We only use this for the initial checkbox values.  It never changes the
// legacy record and a user can still deliberately clear a Tag before saving.
function inheritedHistoricalTagsForCurrentRun(caseData) {
  if (String(caseData?.legacy_read_policy?.policy || "legacy") === "canonical") return [];
  const runId = currentReviewRunId(caseData);
  if (!runId || reviewAnnotationsForCurrentRun(caseData).length) return [];
  const history = reviewAnnotationsForAllRuns(caseData);
  const legacy = history.find(
    (annotation) => !String(annotation?.model_run_id || "").trim()
  );
  const priorRun = history.find(
    (annotation) => String(annotation?.model_run_id || "").trim() !== runId
  );
  const source = legacy || priorRun;
  return Array.isArray(source?.tags) ? source.tags : [];
}

function initialReviewTagsForCurrentRun(caseData, annotation, draft) {
  // A local draft is an explicit user edit, including an intentionally empty
  // set of Tags.  Likewise, a bound Review is authoritative for its Run.
  if (draft || reviewAnnotationsForCurrentRun(caseData).length) {
    return Array.isArray(annotation?.tags) ? annotation.tags : [];
  }
  const inherited = inheritedHistoricalTagsForCurrentRun(caseData);
  if (inherited.length) return inherited;
  return Array.isArray(annotation?.tags) ? annotation.tags : [];
}

const REVIEW_DRAFT_STORAGE_PREFIX = "ra-triage-review-draft:v2:";
const REVIEW_DRAFT_LEGACY_STORAGE_PREFIX = "ra-triage-review-draft:v1:";
const REVIEW_DRAFT_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
function reviewDraftReviewer(caseData, reviewerOverride = "") {
  const verifiedReviewer = state.session?.verified ? state.session?.username : "";
  const form = typeof $ === "function" ? $("#annotationForm") : null;
  const formReviewer = caseData?.issue_id && form?.dataset?.issueId === String(caseData.issue_id)
    ? $("#annotationAuthor")?.value
    : "";
  const reviewer = String(
    reviewerOverride || verifiedReviewer || formReviewer || state.session?.username || currentReviewAnnotation(caseData)?.author || ""
  ).trim().toLowerCase();
  return reviewer || "anonymous";
}

function reviewDraftStorageKey(issueId, runId = "", workSplitId = "", reviewer = "") {
  const base = `${REVIEW_DRAFT_STORAGE_PREFIX}${encodeURIComponent(String(issueId || ""))}:${encodeURIComponent(String(runId || "legacy"))}:${encodeURIComponent(String(workSplitId || "ordinary"))}`;
  return `${base}:${encodeURIComponent(reviewDraftReviewer(null, reviewer))}`;
}

function legacyReviewDraftStorageKey(issueId, runId = "", workSplitId = "") {
  const base = `${REVIEW_DRAFT_LEGACY_STORAGE_PREFIX}${encodeURIComponent(String(issueId || ""))}:${encodeURIComponent(String(runId || "legacy"))}`;
  return workSplitId ? `${base}:${encodeURIComponent(String(workSplitId))}` : base;
}

function reviewDraftMatchesReviewer(draft, reviewer) {
  const expected = String(reviewer || "").trim().toLowerCase();
  const actual = String(draft?.author || "").trim().toLowerCase();
  return expected === "anonymous" ? !actual : actual === expected;
}

function readReviewDraft(issueId, runId = "", workSplitId = "", reviewer = "") {
  if (!issueId || typeof window === "undefined" || !window.localStorage) return null;
  const actor = reviewDraftReviewer(null, reviewer);
  const key = reviewDraftStorageKey(issueId, runId, workSplitId, actor);
  const legacyKey = legacyReviewDraftStorageKey(issueId, runId, workSplitId);
  try {
    let sourceKey = key;
    let raw = window.localStorage.getItem(key);
    if (!raw) {
      sourceKey = legacyKey;
      raw = window.localStorage.getItem(legacyKey);
    }
    if (!raw) return null;
    const draft = JSON.parse(raw);
    if (sourceKey === legacyKey && !reviewDraftMatchesReviewer(draft, actor)) return null;
    const savedAt = Number(draft?.saved_at || 0);
    if (draft?.version !== 1 || !savedAt || Date.now() - savedAt > REVIEW_DRAFT_MAX_AGE_MS) {
      window.localStorage.removeItem(sourceKey);
      return null;
    }
    if (sourceKey === legacyKey) {
      window.localStorage.setItem(key, raw);
      window.localStorage.removeItem(legacyKey);
    }
    return draft;
  } catch {
    return null;
  }
}

function clearReviewDraft(issueId, runId = "", workSplitId = "", reviewer = "") {
  if (!issueId || typeof window === "undefined" || !window.localStorage) return;
  try {
    window.localStorage.removeItem(reviewDraftStorageKey(issueId, runId, workSplitId, reviewer));
    const legacyKey = legacyReviewDraftStorageKey(issueId, runId, workSplitId);
    const legacyRaw = window.localStorage.getItem(legacyKey);
    if (legacyRaw && reviewDraftMatchesReviewer(JSON.parse(legacyRaw), reviewDraftReviewer(null, reviewer))) {
      window.localStorage.removeItem(legacyKey);
    }
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
  const workSplitId = reviewWorkSplitBinding(caseData);
  const reviewer = reviewDraftReviewer(caseData);
  const draft = readReviewDraft(caseData?.issue_id, runId, workSplitId, reviewer);
  if (!draft) return null;
  const serverAnnotation = reviewAnnotationsForCurrentRun(caseData)[0];
  if (serverAnnotation && Number(draft.saved_at) <= annotationTimestamp(serverAnnotation)) {
    clearReviewDraft(caseData.issue_id, runId, workSplitId, reviewer);
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
    model_review_status: $("#modelReviewStatusInput")?.value || "",
    saved_at: Date.now(),
    expected_output: $("#expectedOutputInput")?.value || "",
    is_excluded: Boolean($("#reviewExcludeInput")?.checked),
    tags: [...form.querySelectorAll('input[name="reviewTags"]:checked')].map((input) => input.value),
    missing_evidence: [...form.querySelectorAll('input[name="missingEvidence"]:checked')].map((input) => input.value),
    note: $("#annotationNote")?.value || "",
    author: $("#annotationAuthor")?.value || "",
  };
  try {
    const workSplitId = reviewWorkSplitBinding(caseData);
    const reviewer = reviewDraftReviewer(
      caseData,
      state.session?.verified ? state.session?.username : draft.author
    );
    window.localStorage.setItem(reviewDraftStorageKey(caseData.issue_id, runId, workSplitId, reviewer), JSON.stringify(draft));
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

function currentReviewBaseAnnotationId(annotation, runId, reviewerOverride = "") {
  if (!annotation?.id) return null;
  const annotationRunId = String(annotation.model_run_id || "").trim();
  if (annotationRunId !== String(runId || "").trim()) return null;
  const reviewer = String(
    state.session?.verified ? state.session?.username : reviewerOverride || annotation.author || ""
  ).trim().toLowerCase();
  if (reviewer && String(annotation.author || "").trim().toLowerCase() !== reviewer) return null;
  return annotation.id;
}

function reviewRunLabel(runId) {
  const normalized = String(runId || "").trim();
  if (!normalized) return "未绑定 Model Run";
  const run = (state.modelRuns || []).find((item) => String(item.id) === normalized);
  return run?.name || normalized;
}
