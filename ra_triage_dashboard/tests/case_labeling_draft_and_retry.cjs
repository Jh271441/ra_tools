const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");

function createStorage() {
  const store = new Map();
  return {
    get length() {
      return store.size;
    },
    key(index) {
      return Array.from(store.keys())[index] ?? null;
    },
    getItem(k) {
      return store.has(k) ? store.get(k) : null;
    },
    setItem(k, v) {
      store.set(String(k), String(v));
    },
    removeItem(k) {
      store.delete(k);
    },
    clear() {
      store.clear();
    },
  };
}

async function run() {
  const localStorage = createStorage();
  const scheduledDelays = [];
  const context = {
    console,
    Date,
    Math,
    JSON,
    Map,
    Set,
    Array,
    Object,
    Number,
    String,
    Boolean,
    Promise,
    Error,
    TypeError,
    encodeURIComponent,
    URLSearchParams,
    AbortController,
    FormData: class FormData {},
    crypto: globalThis.crypto,
    state: { session: { username: "Alice", read_only: false }, uiLang: "zh" },
    uiText: (zh, en) => (context.state.uiLang === "en" ? en : zh),
    withBase: (p) => p,
    API_GET_MAX_ATTEMPTS: 3,
    API_GET_TIMEOUT_MS: 5000,
    API_GET_RETRYABLE_STATUSES: new Set([408, 429, 502, 503, 504]),
    window: {
      localStorage,
      setTimeout: (fn, delay) => {
        scheduledDelays.push(delay);
        return setTimeout(fn, 1);
      },
      clearTimeout,
    },
  };
  context.globalThis = context;
  vm.createContext(context);

  const draftSrc = fs.readFileSync(path.join(root, "static/js/case-labeling-draft.js"), "utf8");
  vm.runInContext(draftSrc, context);

  // 1. Case labeling draft storage & Idempotency-Key stability
  const first = context.writeCaseLabelDraft(
    "cn100",
    "task-1",
    "submission",
    { expected_output: "误触发", tags: ["b", "a"], evidence_gaps: [], rationale: "依据1", is_excluded: false },
    { expectedPreviousId: 5 },
  );
  assert.ok(first.idempotency_key.startsWith("case-label-"));
  const secondSame = context.writeCaseLabelDraft(
    "cn100",
    "task-1",
    "submission",
    { expected_output: "误触发", tags: ["a", "b"], evidence_gaps: [], rationale: "依据1", is_excluded: false },
    { expectedPreviousId: 5 },
  );
  assert.equal(secondSame.idempotency_key, first.idempotency_key);
  const changed = context.writeCaseLabelDraft(
    "cn100",
    "task-1",
    "submission",
    { expected_output: "正确触发", tags: ["a", "b"], evidence_gaps: [], rationale: "依据2", is_excluded: false },
    { expectedPreviousId: 5 },
  );
  assert.notEqual(changed.idempotency_key, first.idempotency_key);
  assert.equal(context.readCaseLabelDraft("cn100", "task-1", "submission").expected_output, "正确触发");
  assert.equal(
    context.caseLabelDraftMatchesBaseline(changed, {
      expected_output: "正确触发",
      tags: ["b", "a"],
      evidence_gaps: [],
      rationale: "依据2",
      is_excluded: false,
    }),
    true,
  );
  context.clearCaseLabelDraft("cn100", "task-1", "submission");
  assert.equal(context.readCaseLabelDraft("cn100", "task-1", "submission"), null);

  // 1b. Pending attachments manifest persists, enters signature, detects missing files on reload,
  // preserves Idempotency-Key when exact files are re-attached, and rotates key when dropped.
  const shotA = { file: { name: "bev.png", size: 4096, type: "image/png", lastModified: 1700000000 } };
  const shotB = { file: { name: "cam.jpg", size: 8192, type: "image/jpeg", lastModified: 1700000001 } };
  const withShots = context.writeCaseLabelDraft(
    "cn101",
    "task-1",
    "submission",
    { expected_output: "误触发", tags: ["a"], evidence_gaps: [], rationale: "看图", is_excluded: false },
    { expectedPreviousId: 2, pendingAttachments: [shotA, shotB] },
  );
  assert.equal(withShots.pending_attachments.length, 2);
  const restoredWithShots = context.readCaseLabelDraft("cn101", "task-1", "submission");
  assert.equal(restoredWithShots.pending_attachments.length, 2);
  // Draft with screenshots must NOT match attachment-less baseline.
  assert.equal(
    context.caseLabelDraftMatchesBaseline(restoredWithShots, {
      expected_output: "误触发",
      tags: ["a"],
      evidence_gaps: [],
      rationale: "看图",
      is_excluded: false,
    }),
    false,
  );
  // Missing attachments detected after reload when pendingImages is empty.
  assert.equal(context.caseLabelMissingAttachments(restoredWithShots.pending_attachments, []).length, 2);
  assert.equal(context.caseLabelMissingAttachments(restoredWithShots.pending_attachments, [shotA]).length, 1);
  assert.equal(context.caseLabelMissingAttachments(restoredWithShots.pending_attachments, [shotA, shotB]).length, 0);
  // Re-attaching the exact same files keeps the same Idempotency-Key; continuing without them rotates it.
  const reattached = context.writeCaseLabelDraft(
    "cn101",
    "task-1",
    "submission",
    { expected_output: "误触发", tags: ["a"], evidence_gaps: [], rationale: "看图", is_excluded: false },
    { expectedPreviousId: 2, pendingAttachments: [shotB, shotA] },
  );
  assert.equal(reattached.idempotency_key, withShots.idempotency_key);
  const dropped = context.writeCaseLabelDraft(
    "cn101",
    "task-1",
    "submission",
    { expected_output: "误触发", tags: ["a"], evidence_gaps: [], rationale: "看图", is_excluded: false },
    { expectedPreviousId: 2, pendingAttachments: [], forceNewIdempotencyKey: true },
  );
  assert.notEqual(dropped.idempotency_key, withShots.idempotency_key);
  assert.equal(dropped.pending_attachments.length, 0);

  // 1c. Decision draft source version check detects fingerprint & previous decision ID drift.
  const decDraft = context.writeCaseLabelDraft(
    "cn102",
    "",
    "decision",
    {
      expected_output: "误触发",
      tags: ["a"],
      evidence_gaps: [],
      rationale: "结论",
      decision_rationale: "裁决依据",
      is_excluded: true,
      excluded_confirmed: true,
      adopted_revision_id: 7,
      retained_attachment_ids: [],
    },
    { expectedPreviousId: 3, expectedSourceFingerprint: "fp-old" },
  );
  assert.equal(
    context.caseLabelDecisionSourceChanged(decDraft, {
      label_state: { source_fingerprint: "fp-old", decision: { id: 3 } },
    }).changed,
    false,
  );
  const fpChanged = context.caseLabelDecisionSourceChanged(decDraft, {
    label_state: { source_fingerprint: "fp-new", decision: { id: 3 } },
  });
  assert.equal(fpChanged.changed, true);
  assert.equal(fpChanged.expectedSourceFingerprint, "fp-old");
  assert.equal(fpChanged.currentSourceFingerprint, "fp-new");
  const prevChanged = context.caseLabelDecisionSourceChanged(decDraft, {
    label_state: { source_fingerprint: "fp-old", decision: { id: 4 } },
  });
  assert.equal(prevChanged.changed, true);
  assert.equal(prevChanged.expectedPreviousId, 3);
  assert.equal(prevChanged.currentPreviousId, 4);

  // 2. Classic format-api.js retry for Idempotency-Key mutations & 503/502 messaging
  const formatApiSrc = fs.readFileSync(path.join(root, "static/js/format-api.js"), "utf8");
  vm.runInContext(formatApiSrc, context);

  let calls = 0;
  context.fetch = async () => {
    calls += 1;
    if (calls === 1) {
      return {
        ok: false,
        status: 503,
        redirected: false,
        headers: { get: (k) => (k.toLowerCase() === "retry-after" ? "0" : "text/html") },
        json: async () => { throw new Error("not json"); },
      };
    }
    return {
      ok: true,
      status: 200,
      redirected: false,
      headers: { get: () => "application/json" },
      json: async () => ({ ok: true }),
    };
  };
  const okRes = await context.apiRequest("/api/labeling/cases/cn100/revisions", {
    method: "POST",
    body: JSON.stringify({ expected_output: "误触发" }),
    headers: { "Idempotency-Key": "case-label-retry-1" },
  });
  assert.equal(okRes.ok, true);
  assert.equal(calls, 2);

  // Non-idempotent POST must not retry and returns friendly bilingual message on 502 HTML.
  calls = 0;
  context.fetch = async () => {
    calls += 1;
    return {
      ok: false,
      status: 502,
      redirected: false,
      headers: { get: (k) => (k.toLowerCase() === "content-type" ? "text/html" : null) },
      json: async () => { throw new Error("not json"); },
    };
  };
  await assert.rejects(
    context.apiRequest("/api/other", { method: "POST", body: "{}" }),
    (err) => err.status === 502 && err.transient === true && err.message.includes("未保存内容已保留"),
  );
  assert.equal(calls, 1);

  // 3. Retry-After: 15 waits the FULL 15000ms (never truncated to 5000ms), and Retry-After: 60 stops immediately.
  calls = 0;
  scheduledDelays.length = 0;
  context.fetch = async () => {
    calls += 1;
    if (calls === 1) {
      return {
        ok: false,
        status: 503,
        redirected: false,
        headers: { get: (k) => (k.toLowerCase() === "retry-after" ? "15" : "application/json") },
        json: async () => ({ detail: "系统维护中", maintenance: true, retry_after: 15 }),
      };
    }
    return {
      ok: true,
      status: 200,
      redirected: false,
      headers: { get: () => "application/json" },
      json: async () => ({ ok: true }),
    };
  };
  const afterMaint = await context.apiRequest("/api/labeling/cases/cn100/revisions", {
    method: "POST",
    body: JSON.stringify({ expected_output: "误触发" }),
    headers: { "Idempotency-Key": "case-label-maint-15" },
  });
  assert.equal(afterMaint.ok, true);
  assert.equal(calls, 2);
  assert.equal(scheduledDelays[0], 15000);

  calls = 0;
  scheduledDelays.length = 0;
  context.fetch = async () => {
    calls += 1;
    return {
      ok: false,
      status: 503,
      redirected: false,
      headers: { get: (k) => (k.toLowerCase() === "retry-after" ? "60" : "text/html") },
      json: async () => { throw new Error("not json"); },
    };
  };
  await assert.rejects(
    context.apiRequest("/api/labeling/cases/cn100/revisions", {
      method: "POST",
      body: JSON.stringify({ expected_output: "误触发" }),
      headers: { "Idempotency-Key": "case-label-maint-60" },
    }),
    (err) => err.status === 503 && err.retryAfterSeconds === 60 && err.message.includes("60"),
  );
  assert.equal(calls, 1);
  assert.equal(scheduledDelays.length, 0);

  // 4. Ordinary submission "Discard draft" clears local pendingImages & preview DOM
  // so discarded screenshots cannot leak into the next submission.
  const caseLabelingSrc = fs.readFileSync(path.join(root, "static/js/case-labeling.js"), "utf8");
  const listeners = new Map();
  const pendingPreviewEl = { innerHTML: "<div>stale</div>", querySelectorAll: () => [] };
  const discardButtonEl = {
    addEventListener(evt, fn) {
      listeners.set(`discard:${evt}`, fn);
    },
  };
  let renderedAfterDiscard = 0;
  const releasedUrls = [];
  const uiCtx = {
    ...context,
    state: {
      ...context.state,
      caseLabeling: {
        taskId: "task-1",
        dirty: true,
        draftNotice: { kind: "save_failed" },
        missingDraftAttachments: [],
        pendingImages: [
          { id: "img-1", file: shotA.file, previewUrl: "blob:preview-1" },
        ],
      },
    },
    caseLabelDecisionUi: { editor: null, saving: false, drafts: new Map() },
    $: (sel) => {
      if (sel === "#caseLabelingDraftDiscard") return discardButtonEl;
      if (sel === "#caseLabelingPendingScreenshots") return pendingPreviewEl;
      return null;
    },
    caseLabelingSubmissionTaskId: () => "task-1",
    releasePreviewUrlLater: (url) => releasedUrls.push(url),
    showToast: () => {},
    renderCaseLabelingEditor: () => {
      renderedAfterDiscard += 1;
    },
  };
  vm.createContext(uiCtx);
  vm.runInContext(draftSrc, uiCtx);
  // Extract bindCaseLabelingDraftBanner, clearPendingCaseLabelingImages, and renderPendingCaseLabelingImages
  // directly from case-labeling.js by evaluating case-labeling.js with our stubbed renderCaseLabelingEditor override.
  vm.runInContext(caseLabelingSrc, uiCtx);
  uiCtx.renderCaseLabelingEditor = () => {
    renderedAfterDiscard += 1;
  };
  uiCtx.caseLabelingSubmissionTaskId = () => "task-1";
  uiCtx.writeCaseLabelDraft(
    "cn200",
    "task-1",
    "submission",
    { expected_output: "误触发", tags: [], evidence_gaps: [], rationale: "失败草稿", is_excluded: false },
    { expectedPreviousId: 1, pendingAttachments: [shotA] },
  );
  uiCtx.bindCaseLabelingDraftBanner({ issue_id: "cn200" });
  assert.equal(typeof listeners.get("discard:click"), "function");
  listeners.get("discard:click")();
  assert.equal(uiCtx.state.caseLabeling.pendingImages.length, 0);
  assert.equal(pendingPreviewEl.innerHTML, "");
  assert.deepEqual(releasedUrls, ["blob:preview-1"]);
  assert.equal(uiCtx.readCaseLabelDraft("cn200", "task-1", "submission"), null);
  assert.equal(renderedAfterDiscard, 1);

  // 5. Conditional delete (P1-4): Tab A's earlier save response must NOT delete
  // a newer draft written by Tab B for the same issue/scope.
  const tabADraft = context.writeCaseLabelDraft(
    "cn300",
    "task-1",
    "submission",
    { expected_output: "误触发", tags: ["a"], evidence_gaps: [], rationale: "Tab A 旧内容", is_excluded: false },
    { expectedPreviousId: 10 },
  );
  assert.ok(tabADraft.draft_token);
  const tabBDraft = context.writeCaseLabelDraft(
    "cn300",
    "task-1",
    "submission",
    { expected_output: "正确触发", tags: ["b"], evidence_gaps: [], rationale: "Tab B 新内容", is_excluded: false },
    { expectedPreviousId: 10 },
  );
  assert.notEqual(tabBDraft.draft_token, tabADraft.draft_token);
  assert.equal(
    context.clearCaseLabelDraftIfMatch("cn300", "task-1", "submission", {
      draftToken: tabADraft.draft_token,
      idempotencyKey: tabADraft.idempotency_key,
      signature: tabADraft.signature,
    }),
    false,
  );
  const survivingB = context.readCaseLabelDraft("cn300", "task-1", "submission");
  assert.equal(survivingB.rationale, "Tab B 新内容");
  assert.equal(survivingB.draft_token, tabBDraft.draft_token);
  assert.equal(
    context.clearCaseLabelDraftIfMatch("cn300", "task-1", "submission", {
      draftToken: tabBDraft.draft_token,
      idempotencyKey: tabBDraft.idempotency_key,
      signature: tabBDraft.signature,
    }),
    true,
  );
  assert.equal(context.readCaseLabelDraft("cn300", "task-1", "submission"), null);

  // 6. Quota-full localStorage fallback (P2-7): marks persisted=false and keeps
  // the exact same Idempotency-Key across same-page manual retries.
  const origSetItem = localStorage.setItem;
  localStorage.setItem = () => {
    const err = new Error("QuotaExceededError");
    err.name = "QuotaExceededError";
    throw err;
  };
  try {
    const q1 = context.writeCaseLabelDraft(
      "cn301",
      "task-1",
      "submission",
      { expected_output: "误触发", tags: ["q"], evidence_gaps: [], rationale: "配额满重试", is_excluded: false },
      { expectedPreviousId: 11 },
    );
    assert.equal(q1.persisted, false);
    assert.equal(localStorage.getItem(context.caseLabelDraftStorageKey("cn301", "task-1", "submission")), null);
    const q2 = context.writeCaseLabelDraft(
      "cn301",
      "task-1",
      "submission",
      { expected_output: "误触发", tags: ["q"], evidence_gaps: [], rationale: "配额满重试", is_excluded: false },
      { expectedPreviousId: 11 },
    );
    assert.equal(q2.persisted, false);
    assert.equal(q2.idempotency_key, q1.idempotency_key);
    assert.equal(context.readCaseLabelDraft("cn301", "task-1", "submission").idempotency_key, q1.idempotency_key);
    assert.equal(
      context.clearCaseLabelDraftIfMatch("cn301", "task-1", "submission", {
        draftToken: q2.draft_token,
        idempotencyKey: q2.idempotency_key,
      }),
      true,
    );
    assert.equal(context.readCaseLabelDraft("cn301", "task-1", "submission"), null);
  } finally {
    localStorage.setItem = origSetItem;
  }

  console.log("case_labeling_draft_and_retry.cjs: PASS");
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
