import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiRequest, parseRetryAfterSeconds } from "./client";

describe("apiRequest resilience and retry semantics", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.documentElement.dataset.uiLang = "zh";
  });

  it("parses Retry-After integer seconds and HTTP dates", () => {
    expect(parseRetryAfterSeconds("15")).toBe(15);
    expect(parseRetryAfterSeconds("0")).toBe(0);
    expect(parseRetryAfterSeconds("")).toBeUndefined();
    const future = new Date(Date.now() + 10_000).toUTCString();
    const parsed = parseRetryAfterSeconds(future);
    expect(parsed).toBeDefined();
    expect(parsed!).toBeGreaterThanOrEqual(8);
  });

  it("maps GET 502 HTML gateway errors cleanly and retries when maxAttempts is requested", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response("<html><body>502 Bad Gateway</body></html>", {
          status: 502,
          headers: { "content-type": "text/html" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    // Default GET surfaces the first 502 cleanly so TanStack Query owns retry state.
    await expect(apiRequest<{ ok: boolean }>("/api/health")).rejects.toMatchObject({
      status: 502,
      transient: true,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Explicit opt-in retries transient GETs.
    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(
        new Response("<html><body>502 Bad Gateway</body></html>", {
          status: 502,
          headers: { "content-type": "text/html" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    const res = await apiRequest<{ ok: boolean }>("/api/health", {
      maxAttempts: 2,
      retryBaseDelayMs: 1,
    });
    expect(res.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retries PUT with Idempotency-Key on 503 + Retry-After and maps exhausted HTML 502 cleanly", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response("<html>503</html>", {
          status: 503,
          headers: { "content-type": "text/html", "retry-after": "0" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ saved: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const res = await apiRequest<{ saved: boolean }>("/api/intent-datasets/ds/cases/c1/labels", {
      method: "PUT",
      headers: { "Idempotency-Key": "intent-key-1" },
      body: { routing_default: "straight" },
      retryBaseDelayMs: 1,
    });
    expect(res.saved).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // Exhausted 502 HTML must never leak raw HTML tags in message
    const badFetch = vi.fn<typeof fetch>().mockImplementation(() =>
      Promise.resolve(
        new Response("<html><body><h1>502 Bad Gateway</h1></body></html>", {
          status: 502,
          headers: { "content-type": "text/html" },
        }),
      ),
    );
    vi.stubGlobal("fetch", badFetch);
    let caught: unknown;
    try {
      await apiRequest("/api/test", {
        method: "PUT",
        headers: { "Idempotency-Key": "intent-key-2" },
        body: {},
        retryBaseDelayMs: 1,
      });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    const apiErr = caught as ApiError;
    expect(apiErr.status).toBe(502);
    expect(apiErr.transient).toBe(true);
    expect(apiErr.message).not.toContain("<html>");
    expect(apiErr.message).toContain("草稿");
    expect(badFetch).toHaveBeenCalledTimes(3);
  });

  it("never auto-retries mutations without Idempotency-Key", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response("<html>502</html>", {
        status: 502,
        headers: { "content-type": "text/html" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    document.documentElement.dataset.uiLang = "en";

    await expect(
      apiRequest("/api/non-idempotent", {
        method: "POST",
        body: { x: 1 },
        retryBaseDelayMs: 1,
      }),
    ).rejects.toThrow(/preserved/i);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("honors full Retry-After: 15 without truncating to 5s, and stops immediately on long windows", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ detail: "系统维护中", maintenance: true, retry_after: 15 }), {
            status: 503,
            headers: { "content-type": "application/json", "retry-after": "15" },
          }),
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
        );
      vi.stubGlobal("fetch", fetchMock);

      const pending = apiRequest<{ ok: boolean }>("/api/intent-datasets/ds/cases/c1/labels", {
        method: "PUT",
        headers: { "Idempotency-Key": "intent-maint-1" },
        body: { routing_default: "straight" },
      });

      await vi.advanceTimersByTimeAsync(14_999);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(1);
      const res = await pending;
      expect(res.ok).toBe(true);
      expect(fetchMock).toHaveBeenCalledTimes(2);

      // Long Retry-After (60s > 20s auto-wait budget) stops immediately and surfaces wait time.
      const longMaintFetch = vi.fn<typeof fetch>().mockResolvedValue(
        new Response("<html>503</html>", {
          status: 503,
          headers: { "content-type": "text/html", "retry-after": "60" },
        }),
      );
      vi.stubGlobal("fetch", longMaintFetch);
      await expect(
        apiRequest("/api/intent-datasets/ds/cases/c1/labels", {
          method: "PUT",
          headers: { "Idempotency-Key": "intent-maint-2" },
          body: {},
        }),
      ).rejects.toMatchObject({
        status: 503,
        retryAfterSeconds: 60,
        message: expect.stringContaining("60"),
      });
      expect(longMaintFetch).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
