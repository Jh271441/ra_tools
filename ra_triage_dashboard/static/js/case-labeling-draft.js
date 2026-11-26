/* ra_triage_dashboard/static/js/case-labeling-draft.js
 * Browser-local, actor/Issue/task-scoped drafts & stable Idempotency-Key management
 * for /case-labeling submissions and Issue decisions.
 * Loaded as a classic script before case-labeling.js.
 */
const CASE_LABEL_DRAFT_STORAGE_PREFIX = "ra-triage-case-label-draft:v1:";
const CASE_LABEL_DRAFT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const CASE_LABEL_DRAFT_MAX_ENTRIES = 80;
const caseLabelMemoryDrafts = new Map();

function createCaseLabelIdempotencyKey(mode = "submission") {
  const prefix = mode === "decision" ? "case-decision" : "case-label";
  try {
    if (typeof globalThis.crypto?.randomUUID === "function") {
      return `${prefix}-${globalThis.crypto.randomUUID()}`;
    }
  } catch {
    /* ignore */
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function createCaseLabelDraftToken() {
  try {
    if (typeof globalThis.crypto?.randomUUID === "function") {
      return `draft-${globalThis.crypto.randomUUID()}`;
    }
  } catch {
    /* ignore */
  }
  return `draft-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function caseLabelDraftActor() {
  return String(state?.session?.username || "").trim().toLowerCase() || "anonymous";
}

function caseLabelDraftStorageKey(issueId, taskId = "", mode = "submission", author = "") {
  const issue = String(issueId || "").trim();
  if (!issue) return "";
  const task = String(taskId || "").trim();
  const kind = mode === "decision" ? "decision" : "submission";
  const actor = String(author || caseLabelDraftActor()).trim().toLowerCase() || "anonymous";
  return `${CASE_LABEL_DRAFT_STORAGE_PREFIX}${encodeURIComponent(kind)}:${encodeURIComponent(issue)}:${encodeURIComponent(task)}:${encodeURIComponent(actor)}`;
}

function normalizeCaseLabelStringList(values) {
  return [...new Set((Array.isArray(values) ? values : []).map((v) => String(v || "").trim()).filter(Boolean))].sort();
}

function normalizeCaseLabelPendingAttachments(items) {
  const list = Array.isArray(items) ? items : [];
  const normalized = [];
  for (const item of list) {
    if (!item || typeof item !== "object") continue;
    const src = item.file && typeof item.file === "object" ? item.file : item;
    const name = String(src.name || "").trim();
    const size = Math.max(0, Math.trunc(Number(src.size || 0) || 0));
    const type = String(src.type || "").trim().toLowerCase();
    const lastModified = Math.max(0, Math.trunc(Number(src.lastModified ?? src.last_modified ?? 0) || 0));
    if (!name && !size) continue;
    normalized.push({ name, size, type, last_modified: lastModified });
  }
  normalized.sort((a, b) => (
    a.name.localeCompare(b.name)
    || a.size - b.size
    || a.type.localeCompare(b.type)
    || a.last_modified - b.last_modified
  ));
  return normalized;
}

function caseLabelAttachmentMatchKey(item) {
  return `${item.name}\u0000${item.size}\u0000${item.type}`;
}

function caseLabelMissingAttachments(draftAttachments, currentPendingImages) {
  const expected = normalizeCaseLabelPendingAttachments(draftAttachments);
  if (!expected.length) return [];
  const presentCounts = new Map();
  for (const item of normalizeCaseLabelPendingAttachments(currentPendingImages)) {
    const key = caseLabelAttachmentMatchKey(item);
    presentCounts.set(key, (presentCounts.get(key) || 0) + 1);
  }
  const missing = [];
  for (const item of expected) {
    const key = caseLabelAttachmentMatchKey(item);
    const available = presentCounts.get(key) || 0;
    if (available > 0) {
      presentCounts.set(key, available - 1);
    } else {
      missing.push(item);
    }
  }
  return missing;
}

function caseLabelDecisionSourceChanged(draft, caseData) {
  const expectedPreviousId = draft?.expected_previous_id ?? null;
  const expectedSourceFingerprint = String(draft?.expected_source_fingerprint || "");
  const currentPreviousId = caseData?.label_state?.decision?.id ?? null;
  const currentSourceFingerprint = String(caseData?.label_state?.source_fingerprint || "");
  return {
    changed: expectedPreviousId !== currentPreviousId || expectedSourceFingerprint !== currentSourceFingerprint,
    expectedPreviousId,
    expectedSourceFingerprint,
    currentPreviousId,
    currentSourceFingerprint,
  };
}

function caseLabelDraftSignature(fields = {}, mode = "submission") {
  const base = {
    mode: mode === "decision" ? "decision" : "submission",
    expected_output: String(fields.expected_output || "").trim(),
    tags: normalizeCaseLabelStringList(fields.tags),
    evidence_gaps: normalizeCaseLabelStringList(fields.evidence_gaps),
    rationale: String(fields.rationale || ""),
    is_excluded: Boolean(fields.is_excluded),
    pending_attachments: normalizeCaseLabelPendingAttachments(fields.pending_attachments),
  };
  if (base.mode === "decision") {
    base.decision_rationale = String(fields.decision_rationale || "");
    base.excluded_confirmed = Boolean(fields.excluded_confirmed);
    base.adopted_revision_id = fields.adopted_revision_id ?? null;
    base.retained_attachment_ids = normalizeCaseLabelStringList(fields.retained_attachment_ids);
  }
  return JSON.stringify(base);
}

function caseLabelDraftStorage() {
  try {
    return typeof window !== "undefined" && window.localStorage ? window.localStorage : null;
  } catch {
    return null;
  }
}

function pruneCaseLabelDrafts(storage, keepKey = "", nowMs = Date.now()) {
  if (!storage) return;
  const entries = [];
  for (let i = 0; i < storage.length; i += 1) {
    const key = storage.key(i);
    if (!key || !key.startsWith(CASE_LABEL_DRAFT_STORAGE_PREFIX)) continue;
    try {
      const parsed = JSON.parse(storage.getItem(key) || "{}");
      const savedAt = Number(parsed?.saved_at || 0);
      if (!savedAt || nowMs - savedAt > CASE_LABEL_DRAFT_MAX_AGE_MS) {
        storage.removeItem(key);
        continue;
      }
      entries.push({ key, savedAt });
    } catch {
      storage.removeItem(key);
    }
  }
  if (entries.length <= CASE_LABEL_DRAFT_MAX_ENTRIES) return;
  entries.sort((a, b) => a.savedAt - b.savedAt);
  let remaining = entries.length;
  for (const item of entries) {
    if (remaining <= CASE_LABEL_DRAFT_MAX_ENTRIES) break;
    if (item.key === keepKey) continue;
    storage.removeItem(item.key);
    remaining -= 1;
  }
}

function readStoredCaseLabelDraftFromStorage(storage, key, issueId, taskId, mode, author, nowMs) {
  let raw = null;
  try {
    raw = storage.getItem(key);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    const savedAt = Number(parsed?.saved_at || 0);
    if (
      parsed?.version !== 1 ||
      !savedAt ||
      nowMs - savedAt > CASE_LABEL_DRAFT_MAX_AGE_MS ||
      typeof parsed?.idempotency_key !== "string" ||
      !parsed.idempotency_key.trim()
    ) {
      storage.removeItem(key);
      return null;
    }
    const kind = mode === "decision" ? "decision" : "submission";
    return {
      version: 1,
      mode: kind,
      issue_id: String(parsed.issue_id || issueId),
      task_id: String(parsed.task_id || taskId || ""),
      author: String(parsed.author || author || caseLabelDraftActor()).toLowerCase() || "anonymous",
      expected_output: String(parsed.expected_output || ""),
      tags: normalizeCaseLabelStringList(parsed.tags),
      evidence_gaps: normalizeCaseLabelStringList(parsed.evidence_gaps),
      rationale: String(parsed.rationale || ""),
      is_excluded: Boolean(parsed.is_excluded),
      decision_rationale: String(parsed.decision_rationale || ""),
      excluded_confirmed: Boolean(parsed.excluded_confirmed),
      adopted_revision_id: parsed.adopted_revision_id ?? null,
      retained_attachment_ids: normalizeCaseLabelStringList(parsed.retained_attachment_ids),
      pending_attachments: normalizeCaseLabelPendingAttachments(parsed.pending_attachments),
      expected_previous_id: parsed.expected_previous_id ?? null,
      expected_source_fingerprint: String(parsed.expected_source_fingerprint || ""),
      idempotency_key: parsed.idempotency_key.trim(),
      draft_token: typeof parsed.draft_token === "string" ? parsed.draft_token : undefined,
      persisted: true,
      signature: String(parsed.signature || "") || caseLabelDraftSignature(parsed, kind),
      saved_at: savedAt,
    };
  } catch {
    try {
      storage.removeItem(key);
    } catch {
      /* ignore */
    }
    return null;
  }
}

function readCaseLabelDraft(issueId, taskId = "", mode = "submission", author = "", nowMs = Date.now()) {
  const key = caseLabelDraftStorageKey(issueId, taskId, mode, author);
  if (!key) return null;
  const storage = caseLabelDraftStorage();
  if (storage) {
    const fromStorage = readStoredCaseLabelDraftFromStorage(storage, key, issueId, taskId, mode, author, nowMs);
    if (fromStorage) return fromStorage;
  }
  const fromMemory = caseLabelMemoryDrafts.get(key);
  if (fromMemory) {
    if (nowMs - fromMemory.saved_at > CASE_LABEL_DRAFT_MAX_AGE_MS) {
      caseLabelMemoryDrafts.delete(key);
      return null;
    }
    return { ...fromMemory };
  }
  return null;
}

function writeCaseLabelDraft(issueId, taskId = "", mode = "submission", fields = {}, options = {}) {
  const nowMs = options.nowMs ?? Date.now();
  const author = options.author || caseLabelDraftActor();
  const key = caseLabelDraftStorageKey(issueId, taskId, mode, author);
  if (!key) return null;
  const kind = mode === "decision" ? "decision" : "submission";
  const pendingAttachments = normalizeCaseLabelPendingAttachments(
    options.pendingAttachments ?? fields.pending_attachments
  );
  const normalizedFields = { ...fields, pending_attachments: pendingAttachments };
  const signature = caseLabelDraftSignature(normalizedFields, kind);
  const existing = readCaseLabelDraft(issueId, taskId, kind, author, nowMs);
  const idempotencyKey =
    !options.forceNewIdempotencyKey && existing && existing.signature === signature
      ? existing.idempotency_key
      : createCaseLabelIdempotencyKey(kind);
  const draft = {
    version: 1,
    mode: kind,
    issue_id: String(issueId || ""),
    task_id: String(taskId || ""),
    author: String(author || "anonymous").toLowerCase(),
    expected_output: String(fields.expected_output || ""),
    tags: normalizeCaseLabelStringList(fields.tags),
    evidence_gaps: normalizeCaseLabelStringList(fields.evidence_gaps),
    rationale: String(fields.rationale || ""),
    is_excluded: Boolean(fields.is_excluded),
    decision_rationale: String(fields.decision_rationale || ""),
    excluded_confirmed: Boolean(fields.excluded_confirmed),
    adopted_revision_id: fields.adopted_revision_id ?? null,
    retained_attachment_ids: normalizeCaseLabelStringList(fields.retained_attachment_ids),
    pending_attachments: pendingAttachments,
    expected_previous_id: options.expectedPreviousId ?? fields.expected_previous_id ?? null,
    expected_source_fingerprint: String(options.expectedSourceFingerprint ?? fields.expected_source_fingerprint ?? ""),
    idempotency_key: idempotencyKey,
    draft_token: createCaseLabelDraftToken(),
    persisted: false,
    signature,
    saved_at: nowMs,
  };
  const storage = caseLabelDraftStorage();
  let persisted = false;
  if (storage) {
    const serialized = JSON.stringify({ ...draft, persisted: true });
    try {
      storage.setItem(key, serialized);
      persisted = true;
      pruneCaseLabelDrafts(storage, key, nowMs);
    } catch {
      try {
        pruneCaseLabelDrafts(storage, key, nowMs);
        storage.setItem(key, serialized);
        persisted = true;
      } catch {
        persisted = false;
      }
    }
  }
  draft.persisted = persisted;
  caseLabelMemoryDrafts.set(key, { ...draft });
  return draft;
}

function caseLabelDraftMatchesExpected(stored, expected = {}) {
  if (!stored) return false;
  if (expected.draftToken && stored.draft_token) {
    return stored.draft_token === expected.draftToken;
  }
  if (expected.idempotencyKey && stored.idempotency_key !== expected.idempotencyKey) {
    return false;
  }
  if (expected.signature !== undefined && stored.signature !== expected.signature) {
    return false;
  }
  return Boolean(expected.draftToken || expected.idempotencyKey || expected.signature !== undefined);
}

function clearCaseLabelDraftIfMatch(issueId, taskId = "", mode = "submission", expected = {}, author = "") {
  const key = caseLabelDraftStorageKey(issueId, taskId, mode, author);
  if (!key) return false;
  const storage = caseLabelDraftStorage();
  let clearedStorage = false;
  let hadStorageEntry = false;
  if (storage) {
    const fromStorage = readStoredCaseLabelDraftFromStorage(storage, key, issueId, taskId, mode, author, Date.now());
    if (fromStorage) {
      hadStorageEntry = true;
      if (caseLabelDraftMatchesExpected(fromStorage, expected)) {
        try {
          storage.removeItem(key);
          clearedStorage = true;
        } catch {
          /* ignore */
        }
      }
    }
  }
  const mem = caseLabelMemoryDrafts.get(key) || null;
  let clearedMemory = false;
  if (mem && caseLabelDraftMatchesExpected(mem, expected)) {
    caseLabelMemoryDrafts.delete(key);
    clearedMemory = true;
  }
  return hadStorageEntry ? clearedStorage : clearedMemory;
}

function clearCaseLabelDraft(issueId, taskId = "", mode = "submission", author = "") {
  const key = caseLabelDraftStorageKey(issueId, taskId, mode, author);
  if (!key) return;
  caseLabelMemoryDrafts.delete(key);
  const storage = caseLabelDraftStorage();
  if (!storage) return;
  try {
    storage.removeItem(key);
  } catch {
    /* ignore */
  }
}

function caseLabelDraftMatchesBaseline(draft, source = {}, mode = "submission") {
  if (!draft) return true;
  return draft.signature === caseLabelDraftSignature(source, mode);
}
