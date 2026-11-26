import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import "./main";

describe("Workbench refreshPage cache invalidation parity", () => {
  it.each([
    ["trail-history", "trail-history-list"],
    ["trail-history", "trail-history-detail"],
    ["rd-results", "rd-results-classic"],
    ["rd-results", "human-publications"],
    ["rd-results", "human-publications-history"],
    ["prediction", "batch-prediction-list"],
    ["prediction", "batch-prediction-config"],
    ["prediction", "batch-prediction-models"],
    ["prediction", "batch-prediction-prompts"],
    ["review", "review-gallery-cases"],
    ["labeling", "labeling-gallery-cases"],
    ["labeling-summary", "labeling-summary"],
  ])("refreshPage(%s) invalidates subscribed query key %s", (page, subscribedKey) => {
    const spy = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    const handle = (
      window as unknown as {
        __RA_REACT_WORKBENCH__?: { refreshPage: (target: string) => void };
      }
    ).__RA_REACT_WORKBENCH__;
    expect(handle).toBeDefined();

    handle!.refreshPage(page);
    const client = spy.mock.contexts.at(-1) as QueryClient;
    expect(client).toBeInstanceOf(QueryClient);

    const cacheKey = [subscribedKey, "regression-check"];
    client.setQueryData(cacheKey, { ok: true });
    spy.mockClear();

    handle!.refreshPage(page);
    expect(client.getQueryState(cacheKey)?.isInvalidated).toBe(true);
    spy.mockRestore();
  });
});
