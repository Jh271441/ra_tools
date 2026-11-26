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
});
