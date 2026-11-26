import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearIntentDraft,
  clearIntentDraftIfMatch,
  INTENT_DRAFT_MAX_AGE_MS,
  intentDraftSignature,
  readIntentDraft,
  writeIntentDraft,
} from "./intentDraftStorage";

describe("intentDraftStorage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("persists draft, reuses Idempotency-Key when unchanged, and rotates key when edited", () => {
    const first = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn1_1",
      author: "Alice",
      routingDefault: "straight",
      laneChangeDefault: "no_lane_change",
      overrides: {
        t0: { timepoint_id: "t0", offset_ms: 0, routing_intent: "left_turn", lane_change_intent: "" },
      },
      expectedRevisionId: 12,
    });
    expect(first).not.toBeNull();
    expect(first!.idempotency_key).toMatch(/^intent-/);

    const sameRetry = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn1_1",
      author: "alice",
      routingDefault: "straight",
      laneChangeDefault: "no_lane_change",
      overrides: {
        t0: { timepoint_id: "t0", offset_ms: 0, routing_intent: "left_turn", lane_change_intent: "" },
      },
      expectedRevisionId: 12,
    });
    expect(sameRetry!.idempotency_key).toBe(first!.idempotency_key);

    const edited = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn1_1",
      author: "alice",
      routingDefault: "right_turn",
      laneChangeDefault: "no_lane_change",
      overrides: {},
      expectedRevisionId: 12,
    });
    expect(edited!.idempotency_key).not.toBe(first!.idempotency_key);

    const loaded = readIntentDraft("ds-1", "cn1_1", "alice");
    expect(loaded?.routing_default).toBe("right_turn");
    expect(loaded?.idempotency_key).toBe(edited!.idempotency_key);

    clearIntentDraft("ds-1", "cn1_1", "alice");
    expect(readIntentDraft("ds-1", "cn1_1", "alice")).toBeNull();
  });

  it("drops expired drafts and normalizes sparse overrides in signatures", () => {
    const oldTime = Date.now() - INTENT_DRAFT_MAX_AGE_MS - 10_000;
    writeIntentDraft(
      {
        datasetId: "ds-1",
        caseId: "cn2_1",
        author: "bob",
        routingDefault: "straight",
        laneChangeDefault: "lane_change",
        overrides: {},
        expectedRevisionId: null,
      },
      oldTime,
    );
    expect(readIntentDraft("ds-1", "cn2_1", "bob")).toBeNull();

    const sigA = intentDraftSignature("straight", "no_lane_change", {
      t0: { timepoint_id: "t0", offset_ms: 0, routing_intent: "straight", lane_change_intent: "" },
    });
    const sigB = intentDraftSignature("straight", "no_lane_change", {});
    expect(sigA).toBe(sigB);
  });

  it("clearIntentDraftIfMatch preserves a newer draft written by another tab", () => {
    const tabA = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn3_1",
      author: "alice",
      routingDefault: "left_turn",
      laneChangeDefault: "no_lane_change",
      overrides: {},
      expectedRevisionId: 10,
    });
    expect(tabA?.draft_token).toBeTruthy();

    // Simulate Tab B saving a newer local draft while Tab A's save is in flight.
    const tabB = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn3_1",
      author: "alice",
      routingDefault: "right_turn",
      laneChangeDefault: "lane_change",
      overrides: {},
      expectedRevisionId: 10,
    });
    expect(tabB?.draft_token).not.toBe(tabA?.draft_token);

    // Tab A's stale clear must NOT delete Tab B's newer draft.
    const clearedByA = clearIntentDraftIfMatch("ds-1", "cn3_1", "alice", {
      draftToken: tabA!.draft_token,
      idempotencyKey: tabA!.idempotency_key,
      signature: tabA!.signature,
    });
    expect(clearedByA).toBe(false);
    const survivor = readIntentDraft("ds-1", "cn3_1", "alice");
    expect(survivor?.routing_default).toBe("right_turn");
    expect(survivor?.draft_token).toBe(tabB!.draft_token);

    // Tab B's matching clear succeeds.
    const clearedByB = clearIntentDraftIfMatch("ds-1", "cn3_1", "alice", {
      draftToken: tabB!.draft_token,
      idempotencyKey: tabB!.idempotency_key,
      signature: tabB!.signature,
    });
    expect(clearedByB).toBe(true);
    expect(readIntentDraft("ds-1", "cn3_1", "alice")).toBeNull();
  });

  it("falls back to in-memory draft with persisted=false and preserves Idempotency-Key when localStorage quota is full", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });

    const first = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn_quota",
      author: "alice",
      routingDefault: "left_turn",
      laneChangeDefault: "no_lane_change",
      overrides: {},
      expectedRevisionId: 10,
    });
    expect(first).not.toBeNull();
    expect(first!.persisted).toBe(false);
    expect(window.localStorage.length).toBe(0);

    // Retrying with the exact same payload reuses the identical Idempotency-Key via in-memory fallback.
    const retry = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn_quota",
      author: "alice",
      routingDefault: "left_turn",
      laneChangeDefault: "no_lane_change",
      overrides: {},
      expectedRevisionId: 10,
    });
    expect(retry!.persisted).toBe(false);
    expect(retry!.idempotency_key).toBe(first!.idempotency_key);

    const loaded = readIntentDraft("ds-1", "cn_quota", "alice");
    expect(loaded?.persisted).toBe(false);
    expect(loaded?.idempotency_key).toBe(first!.idempotency_key);

    expect(
      clearIntentDraftIfMatch("ds-1", "cn_quota", "alice", {
        draftToken: retry!.draft_token,
        idempotencyKey: retry!.idempotency_key,
      }),
    ).toBe(true);
    expect(readIntentDraft("ds-1", "cn_quota", "alice")).toBeNull();
  });

  it("prioritizes newer in-memory draft over stale disk draft when quota fills, preserves key on retries, writes when quota recovers, and respects Tab B", () => {
    // 1) Old draft persists to localStorage successfully.
    const oldDraft = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn_quota_nonempty",
      author: "alice",
      routingDefault: "straight",
      laneChangeDefault: "no_lane_change",
      overrides: {},
      expectedRevisionId: 10,
    });
    expect(oldDraft?.persisted).toBe(true);

    // 2) Storage fills up; writing new draft fails -> stays in memory with persisted=false.
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });
    const newAttempt1 = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn_quota_nonempty",
      author: "alice",
      routingDefault: "left_turn",
      laneChangeDefault: "lane_change",
      overrides: {},
      expectedRevisionId: 10,
    });
    expect(newAttempt1?.persisted).toBe(false);
    expect(newAttempt1?.idempotency_key).not.toBe(oldDraft?.idempotency_key);

    // Reading back must return the newer in-memory draft, NOT stale disk `oldDraft`!
    const readWhileFull = readIntentDraft("ds-1", "cn_quota_nonempty", "alice");
    expect(readWhileFull?.routing_default).toBe("left_turn");
    expect(readWhileFull?.persisted).toBe(false);
    expect(readWhileFull?.idempotency_key).toBe(newAttempt1?.idempotency_key);

    // Retrying twice with identical content while quota is still full reuses the exact same key!
    const retry1 = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn_quota_nonempty",
      author: "alice",
      routingDefault: "left_turn",
      laneChangeDefault: "lane_change",
      overrides: {},
      expectedRevisionId: 10,
    });
    const retry2 = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn_quota_nonempty",
      author: "alice",
      routingDefault: "left_turn",
      laneChangeDefault: "lane_change",
      overrides: {},
      expectedRevisionId: 10,
    });
    expect(retry1?.persisted).toBe(false);
    expect(retry2?.persisted).toBe(false);
    expect(retry1?.idempotency_key).toBe(newAttempt1?.idempotency_key);
    expect(retry2?.idempotency_key).toBe(newAttempt1?.idempotency_key);

    // 3) Once quota recovers, writing `new` persists to localStorage with the SAME idempotency_key.
    setItemSpy.mockRestore();
    const recovered = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn_quota_nonempty",
      author: "alice",
      routingDefault: "left_turn",
      laneChangeDefault: "lane_change",
      overrides: {},
      expectedRevisionId: 10,
    });
    expect(recovered?.persisted).toBe(true);
    expect(recovered?.idempotency_key).toBe(newAttempt1?.idempotency_key);
    const fromDisk = readIntentDraft("ds-1", "cn_quota_nonempty", "alice");
    expect(fromDisk?.persisted).toBe(true);
    expect(fromDisk?.routing_default).toBe("left_turn");

    // 4) Cross-tab protection: Tab A fails quota write over `recovered`, then Tab B
    // succeeds writing a newer version directly to localStorage -> Tab B must win & survive Tab A clear.
    const spy2 = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });
    const tabAFailed = writeIntentDraft({
      datasetId: "ds-1",
      caseId: "cn_quota_nonempty",
      author: "alice",
      routingDefault: "u_turn",
      laneChangeDefault: "no_lane_change",
      overrides: {},
      expectedRevisionId: 10,
    });
    expect(tabAFailed?.persisted).toBe(false);
    spy2.mockRestore();

    // Simulate Tab B writing directly to shared localStorage (fresh draft_token).
    const key = window.localStorage.key(0)!;
    const tabBPayload = {
      ...recovered!,
      routing_default: "right_turn",
      draft_token: "draft-from-tab-b",
      idempotency_key: "intent-from-tab-b",
      signature: intentDraftSignature("right_turn", "lane_change", {}),
      saved_at: Date.now() + 1000,
      persisted: true,
    };
    window.localStorage.setItem(key, JSON.stringify(tabBPayload));

    const readAfterTabB = readIntentDraft("ds-1", "cn_quota_nonempty", "alice");
    expect(readAfterTabB?.routing_default).toBe("right_turn");
    expect(readAfterTabB?.draft_token).toBe("draft-from-tab-b");
    expect(
      clearIntentDraftIfMatch("ds-1", "cn_quota_nonempty", "alice", {
        draftToken: tabAFailed!.draft_token,
        idempotencyKey: tabAFailed!.idempotency_key,
        signature: tabAFailed!.signature,
      }),
    ).toBe(false);
    expect(readIntentDraft("ds-1", "cn_quota_nonempty", "alice")?.draft_token).toBe("draft-from-tab-b");
  });
});
