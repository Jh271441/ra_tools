import { beforeEach, describe, expect, it } from "vitest";
import {
  clearIntentDraft,
  INTENT_DRAFT_MAX_AGE_MS,
  intentDraftSignature,
  readIntentDraft,
  writeIntentDraft,
} from "./intentDraftStorage";

describe("intentDraftStorage", () => {
  beforeEach(() => {
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
});
