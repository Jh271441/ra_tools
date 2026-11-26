export interface IntentOverrideDraft {
  timepoint_id: string;
  offset_ms: number;
  routing_intent?: string;
  lane_change_intent?: string;
}

export interface IntentLabelDraft {
  version: 1;
  dataset_id: string;
  case_id: string;
  author: string;
  routing_default: string;
  lane_change_default: string;
  overrides: Record<string, IntentOverrideDraft>;
  expected_revision_id: number | null;
  idempotency_key: string;
  draft_token?: string;
  persisted?: boolean;
  signature: string;
  saved_at: number;
}

export const INTENT_DRAFT_STORAGE_PREFIX = "ra-triage-intent-draft:v1:";
export const INTENT_DRAFT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const INTENT_DRAFT_MAX_ENTRIES = 60;
const memoryIntentDrafts = new Map<string, IntentLabelDraft>();

export function createIntentIdempotencyKey(): string {
  try {
    if (typeof globalThis.crypto?.randomUUID === "function") {
      return `intent-${globalThis.crypto.randomUUID()}`;
    }
  } catch {
    /* fallback below */
  }
  return `intent-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function createIntentDraftToken(): string {
  try {
    if (typeof globalThis.crypto?.randomUUID === "function") {
      return `draft-${globalThis.crypto.randomUUID()}`;
    }
  } catch {
    /* fallback below */
  }
  return `draft-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function intentDraftKey(datasetId: string, caseId: string, author: string): string {
  const ds = String(datasetId || "").trim();
  const cid = String(caseId || "").trim();
  const actor = String(author || "").trim().toLowerCase() || "anonymous";
  if (!ds || !cid) return "";
  return `${INTENT_DRAFT_STORAGE_PREFIX}${encodeURIComponent(ds)}:${encodeURIComponent(cid)}:${encodeURIComponent(actor)}`;
}

export function normalizeIntentOverridesMap(
  overrides: Record<string, IntentOverrideDraft> | IntentOverrideDraft[] | null | undefined,
): Record<string, IntentOverrideDraft> {
  const list = Array.isArray(overrides) ? overrides : Object.values(overrides || {});
  const result: Record<string, IntentOverrideDraft> = {};
  for (const item of list) {
    if (!item || !item.timepoint_id) continue;
    const tpId = String(item.timepoint_id).trim();
    if (!tpId) continue;
    result[tpId] = {
      timepoint_id: tpId,
      offset_ms: Number(item.offset_ms || 0),
      routing_intent: String(item.routing_intent || ""),
      lane_change_intent: String(item.lane_change_intent || ""),
    };
  }
  return result;
}

export function intentDraftSignature(
  routingDefault: string,
  laneChangeDefault: string,
  overrides: Record<string, IntentOverrideDraft> | IntentOverrideDraft[] | null | undefined,
): string {
  const routing = String(routingDefault || "").trim();
  const laneChange = String(laneChangeDefault || "").trim();
  const normalized = Object.values(normalizeIntentOverridesMap(overrides))
    .map((item) => {
      const r = item.routing_intent === routing ? "" : item.routing_intent || "";
      const l = item.lane_change_intent === laneChange ? "" : item.lane_change_intent || "";
      return {
        timepoint_id: item.timepoint_id,
        offset_ms: item.offset_ms,
        routing_intent: r,
        lane_change_intent: l,
      };
    })
    .filter((item) => item.routing_intent || item.lane_change_intent)
    .sort((a, b) => a.offset_ms - b.offset_ms || a.timepoint_id.localeCompare(b.timepoint_id));
  return JSON.stringify({
    routing_default: routing,
    lane_change_default: laneChange,
    overrides: normalized,
  });
}

function getStorage(): Storage | null {
  try {
    return typeof window !== "undefined" && window.localStorage ? window.localStorage : null;
  } catch {
    return null;
  }
}

function readStoredIntentDraftFromStorage(
  storage: Storage,
  key: string,
  datasetId: string,
  caseId: string,
  author: string,
  nowMs: number,
): IntentLabelDraft | null {
  let raw: string | null = null;
  try {
    raw = storage.getItem(key);
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<IntentLabelDraft>;
    const savedAt = Number(parsed?.saved_at || 0);
    if (
      parsed?.version !== 1 ||
      !savedAt ||
      nowMs - savedAt > INTENT_DRAFT_MAX_AGE_MS ||
      typeof parsed.idempotency_key !== "string" ||
      !parsed.idempotency_key.trim()
    ) {
      storage.removeItem(key);
      return null;
    }
    const overrides = normalizeIntentOverridesMap(parsed.overrides);
    const routing = String(parsed.routing_default || "");
    const laneChange = String(parsed.lane_change_default || "");
    return {
      version: 1,
      dataset_id: String(parsed.dataset_id || datasetId),
      case_id: String(parsed.case_id || caseId),
      author: String(parsed.author || author).toLowerCase() || "anonymous",
      routing_default: routing,
      lane_change_default: laneChange,
      overrides,
      expected_revision_id:
        typeof parsed.expected_revision_id === "number" ? parsed.expected_revision_id : null,
      idempotency_key: parsed.idempotency_key.trim(),
      draft_token: typeof parsed.draft_token === "string" ? parsed.draft_token : undefined,
      persisted: true,
      signature:
        typeof parsed.signature === "string" && parsed.signature
          ? parsed.signature
          : intentDraftSignature(routing, laneChange, overrides),
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

export function readIntentDraft(
  datasetId: string,
  caseId: string,
  author: string,
  nowMs: number = Date.now(),
): IntentLabelDraft | null {
  const key = intentDraftKey(datasetId, caseId, author);
  if (!key) return null;
  const storage = getStorage();
  if (storage) {
    const fromStorage = readStoredIntentDraftFromStorage(storage, key, datasetId, caseId, author, nowMs);
    if (fromStorage) return fromStorage;
  }
  const fromMemory = memoryIntentDrafts.get(key);
  if (fromMemory) {
    if (nowMs - fromMemory.saved_at > INTENT_DRAFT_MAX_AGE_MS) {
      memoryIntentDrafts.delete(key);
      return null;
    }
    return { ...fromMemory };
  }
  return null;
}

function pruneOldIntentDrafts(storage: Storage, keepKey: string, nowMs: number): void {
  const entries: Array<{ key: string; savedAt: number }> = [];
  for (let i = 0; i < storage.length; i += 1) {
    const k = storage.key(i);
    if (!k || !k.startsWith(INTENT_DRAFT_STORAGE_PREFIX)) continue;
    try {
      const parsed = JSON.parse(storage.getItem(k) || "{}") as { saved_at?: number };
      const savedAt = Number(parsed?.saved_at || 0);
      if (!savedAt || nowMs - savedAt > INTENT_DRAFT_MAX_AGE_MS) {
        storage.removeItem(k);
        continue;
      }
      entries.push({ key: k, savedAt });
    } catch {
      storage.removeItem(k);
    }
  }
  if (entries.length <= INTENT_DRAFT_MAX_ENTRIES) return;
  entries.sort((a, b) => a.savedAt - b.savedAt);
  let remaining = entries.length;
  for (const item of entries) {
    if (remaining <= INTENT_DRAFT_MAX_ENTRIES) break;
    if (item.key === keepKey) continue;
    storage.removeItem(item.key);
    remaining -= 1;
  }
}

export function writeIntentDraft(
  params: {
    datasetId: string;
    caseId: string;
    author: string;
    routingDefault: string;
    laneChangeDefault: string;
    overrides: Record<string, IntentOverrideDraft>;
    expectedRevisionId: number | null;
    preferredIdempotencyKey?: string;
    forceNewIdempotencyKey?: boolean;
  },
  nowMs: number = Date.now(),
): IntentLabelDraft | null {
  const key = intentDraftKey(params.datasetId, params.caseId, params.author);
  if (!key) return null;
  const overrides = normalizeIntentOverridesMap(params.overrides);
  const signature = intentDraftSignature(params.routingDefault, params.laneChangeDefault, overrides);
  const existing = readIntentDraft(params.datasetId, params.caseId, params.author, nowMs);
  const idempotencyKey =
    !params.forceNewIdempotencyKey && existing && existing.signature === signature
      ? existing.idempotency_key
      : !params.forceNewIdempotencyKey && params.preferredIdempotencyKey && existing?.signature === signature
        ? params.preferredIdempotencyKey
        : createIntentIdempotencyKey();

  const draft: IntentLabelDraft = {
    version: 1,
    dataset_id: params.datasetId,
    case_id: params.caseId,
    author: String(params.author || "").trim().toLowerCase() || "anonymous",
    routing_default: String(params.routingDefault || ""),
    lane_change_default: String(params.laneChangeDefault || ""),
    overrides,
    expected_revision_id: params.expectedRevisionId,
    idempotency_key: idempotencyKey,
    draft_token: createIntentDraftToken(),
    persisted: false,
    signature,
    saved_at: nowMs,
  };

  const storage = getStorage();
  let persisted = false;
  if (storage) {
    const serialized = JSON.stringify({ ...draft, persisted: true });
    try {
      storage.setItem(key, serialized);
      persisted = true;
      pruneOldIntentDrafts(storage, key, nowMs);
    } catch {
      try {
        pruneOldIntentDrafts(storage, key, nowMs);
        storage.setItem(key, serialized);
        persisted = true;
      } catch {
        persisted = false;
      }
    }
  }
  draft.persisted = persisted;
  memoryIntentDrafts.set(key, { ...draft });
  return draft;
}

function intentDraftMatchesExpected(
  stored: IntentLabelDraft | null,
  expected: { draftToken?: string; idempotencyKey?: string; signature?: string },
): boolean {
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

export function clearIntentDraftIfMatch(
  datasetId: string,
  caseId: string,
  author: string,
  expected: { draftToken?: string; idempotencyKey?: string; signature?: string },
): boolean {
  const key = intentDraftKey(datasetId, caseId, author);
  if (!key) return false;
  const storage = getStorage();
  let clearedStorage = false;
  let hadStorageEntry = false;
  if (storage) {
    const fromStorage = readStoredIntentDraftFromStorage(storage, key, datasetId, caseId, author, Date.now());
    if (fromStorage) {
      hadStorageEntry = true;
      if (intentDraftMatchesExpected(fromStorage, expected)) {
        try {
          storage.removeItem(key);
          clearedStorage = true;
        } catch {
          /* ignore */
        }
      }
    }
  }
  const mem = memoryIntentDrafts.get(key) || null;
  let clearedMemory = false;
  if (mem && intentDraftMatchesExpected(mem, expected)) {
    memoryIntentDrafts.delete(key);
    clearedMemory = true;
  }
  if (hadStorageEntry) {
    return clearedStorage;
  }
  return clearedMemory;
}

export function clearIntentDraft(datasetId: string, caseId: string, author: string): void {
  const key = intentDraftKey(datasetId, caseId, author);
  if (!key) return;
  memoryIntentDrafts.delete(key);
  const storage = getStorage();
  if (!storage) return;
  try {
    storage.removeItem(key);
  } catch {
    /* ignore */
  }
}
