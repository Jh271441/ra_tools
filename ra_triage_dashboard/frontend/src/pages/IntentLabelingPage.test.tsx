import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readIntentDraft, writeIntentDraft } from "../features/intent/intentDraftStorage";
import { IntentLabelingPage } from "./IntentLabelingPage";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const DATASETS_PAYLOAD = {
  items: [{ id: "0206-1335-v1", display_name: "0206 · 1335", available: true, case_count: 1335 }],
};

const ASSIGNEES_PAYLOAD = {
  items: [{ username: "jasperchen", case_count: 50 }],
  experiments: [{ id: "exp-1", dataset_id: "0206-1335-v1", name: "首轮盲标", label_scope: "all", case_count: 50 }],
};

const QUEUE_PAYLOAD = {
  scope_total: 1335,
  items: [
    {
      case_id: "cn28896325_0",
      issue_id: "cn28896325",
      dataset_id: "0206-1335-v1",
      ordinal: 1,
      previous: null,
      next: { case_id: "cn28896326_0", dataset_id: "0206-1335-v1" },
    },
  ],
};

const CASE_PAYLOAD = {
  case_id: "cn28896325_0",
  issue_id: "cn28896325",
  dataset_id: "0206-1335-v1",
  timepoints: [
    {
      id: "tp-0",
      offset_ms: -2000,
      camera_delta_ms: 12,
      camera: { url: "/cam0.jpg", thumbnail_url: "/cam0_t.jpg" },
      bev: { url: "/bev0.jpg", thumbnail_url: "/bev0_t.jpg" },
    },
    {
      id: "tp-1",
      offset_ms: 0,
      camera_delta_ms: 0,
      camera: { url: "/cam1.jpg", thumbnail_url: "/cam1_t.jpg" },
      bev: { url: "/bev1.jpg", thumbnail_url: "/bev1_t.jpg" },
    },
  ],
  labels: {
    revision_id: 10,
    routing_default: "straight",
    lane_change_default: "no_lane_change",
    overrides: [],
  },
  collaboration: {
    blind_active: false,
    answers_revealed: true,
    contributors: [
      {
        username: "jasperchen",
        is_current: true,
        revealed: true,
        labeled: true,
        completed: true,
        completion_reason: "全部帧已覆盖",
        routing_default: "straight",
        lane_change_default: "no_lane_change",
        overrides: [],
      },
    ],
    comments: [{ id: 1, author: "jasperchen", body: "直行" }],
  },
};

describe("IntentLabelingPage", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/intent-labeling?dataset=0206-1335-v1");
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/intent-datasets/0206-1335-v1/cases/")) {
        return Promise.resolve(
          new Response(JSON.stringify(CASE_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/intent-datasets")) {
        return Promise.resolve(
          new Response(JSON.stringify(DATASETS_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/intent-assignees")) {
        return Promise.resolve(
          new Response(JSON.stringify(ASSIGNEES_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/intent-cases")) {
        return Promise.resolve(
          new Response(JSON.stringify(QUEUE_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("loads active case, renders media + timeline + rail, enforces zero native selects, and zooms camera", async () => {
    const { container } = renderWithQuery(
      <IntentLabelingPage
        active
        lang="zh"
        username="jasperchen"
        isAdmin
        canAnnotateIntent
      />,
    );

    await waitFor(() => {
      expect(screen.getByDisplayValue("cn28896325")).toBeInTheDocument();
    });
    expect(container.querySelectorAll("select").length).toBe(0);
    expect(screen.getAllByText("-2s").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("+0s").length).toBeGreaterThanOrEqual(1);

    fireEvent.click(screen.getByRole("button", { name: "放大 Camera" }));
    expect(document.getElementById("intentCameraZoomLevel")?.textContent).toBe("120%");
  });

  it("renders English labels cleanly", async () => {
    renderWithQuery(
      <IntentLabelingPage
        active
        lang="en"
        username="jasperchen"
        isAdmin={false}
        canAnnotateIntent
      />,
    );

    await waitFor(() => {
      expect(screen.getByDisplayValue("cn28896325")).toBeInTheDocument();
    });
    expect(screen.getByText("Batch prefill")).toBeInTheDocument();
    expect(screen.getByText("Frame timeline")).toBeInTheDocument();
  });

  it("preserves conflicted draft original revision and blocks implicit overwrite on case navigation", async () => {
    const seeded = writeIntentDraft({
      datasetId: "0206-1335-v1",
      caseId: "cn28896325_0",
      author: "jasperchen",
      routingDefault: "left_turn",
      laneChangeDefault: "no_lane_change",
      overrides: {},
      expectedRevisionId: 9,
    });
    expect(seeded?.expected_revision_id).toBe(9);

    const putCalls: Array<{ url: string; body: Record<string, unknown>; idemKey: string | null }> = [];
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = String(init?.method || "GET").toUpperCase();
      if (method === "PUT" && url.includes("/labels")) {
        const headers = new Headers(init?.headers);
        putCalls.push({
          url,
          body: JSON.parse(String(init?.body || "{}")),
          idemKey: headers.get("Idempotency-Key"),
        });
        return Promise.resolve(
          new Response(
            JSON.stringify({
              labels: {
                revision_id: 11,
                routing_default: "left_turn",
                lane_change_default: "no_lane_change",
                overrides: [],
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.includes("/api/intent-datasets/0206-1335-v1/cases/")) {
        return Promise.resolve(
          new Response(JSON.stringify(CASE_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/intent-datasets")) {
        return Promise.resolve(
          new Response(JSON.stringify(DATASETS_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/intent-assignees")) {
        return Promise.resolve(
          new Response(JSON.stringify(ASSIGNEES_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/intent-cases")) {
        return Promise.resolve(
          new Response(JSON.stringify(QUEUE_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithQuery(
      <IntentLabelingPage
        active
        lang="zh"
        username="jasperchen"
        isAdmin={false}
        canAnnotateIntent
      />,
    );

    await waitFor(() => {
      expect(document.getElementById("intentDraftRecoveryBanner")).toBeInTheDocument();
    });
    // Original expected_revision_id=9 must NOT be rewritten to server revision 10!
    expect(readIntentDraft("0206-1335-v1", "cn28896325_0", "jasperchen")?.expected_revision_id).toBe(9);

    // Navigating to next case must NOT implicitly submit and overwrite revision 10.
    const nextCaseBtn = document.getElementById("intentNextCase");
    expect(nextCaseBtn).toBeInTheDocument();
    fireEvent.click(nextCaseBtn!);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(putCalls.length).toBe(0);
    expect(readIntentDraft("0206-1335-v1", "cn28896325_0", "jasperchen")?.expected_revision_id).toBe(9);

    // Explicit overwrite button DOES submit against latest server revision 10 with a fresh key.
    const overwriteBtn = document.getElementById("intentDraftRetryButton");
    expect(overwriteBtn).toBeInTheDocument();
    fireEvent.click(overwriteBtn!);
    await waitFor(() => {
      expect(putCalls.length).toBe(1);
    });
    expect(putCalls[0].body.expected_revision_id).toBe(10);
    expect(putCalls[0].idemKey).toBeTruthy();
    expect(putCalls[0].idemKey).not.toBe(seeded?.idempotency_key);
  });

  it("retries explicit conflict overwrite after 503 using the same confirmed revision and Idempotency-Key", async () => {
    writeIntentDraft({
      datasetId: "0206-1335-v1",
      caseId: "cn28896325_0",
      author: "jasperchen",
      routingDefault: "left_turn",
      laneChangeDefault: "no_lane_change",
      overrides: {},
      expectedRevisionId: 9,
    });

    const putCalls: Array<{ body: Record<string, unknown>; idemKey: string | null }> = [];
    fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = String(init?.method || "GET").toUpperCase();
      if (method === "PUT" && url.includes("/labels")) {
        const headers = new Headers(init?.headers);
        putCalls.push({
          body: JSON.parse(String(init?.body || "{}")),
          idemKey: headers.get("Idempotency-Key"),
        });
        if (putCalls.length === 1) {
          // Return 503 with long Retry-After so client stops auto-retrying after attempt 1
          // and surfaces the Retry Save button to the user.
          return Promise.resolve(
            new Response(JSON.stringify({ detail: "系统维护中", maintenance: true, retry_after: 60 }), {
              status: 503,
              headers: { "Content-Type": "application/json", "Retry-After": "60" },
            }),
          );
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({
              labels: {
                revision_id: 11,
                routing_default: "left_turn",
                lane_change_default: "no_lane_change",
                overrides: [],
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
        );
      }
      if (url.includes("/api/intent-datasets/0206-1335-v1/cases/")) {
        return Promise.resolve(
          new Response(JSON.stringify(CASE_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/intent-datasets")) {
        return Promise.resolve(
          new Response(JSON.stringify(DATASETS_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/intent-assignees")) {
        return Promise.resolve(
          new Response(JSON.stringify(ASSIGNEES_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/intent-cases")) {
        return Promise.resolve(
          new Response(JSON.stringify(QUEUE_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });

    renderWithQuery(
      <IntentLabelingPage
        active
        lang="zh"
        username="jasperchen"
        isAdmin={false}
        canAnnotateIntent
      />,
    );

    await waitFor(() => {
      expect(document.getElementById("intentDraftRetryButton")).toBeInTheDocument();
    });
    // Step 1: Click explicit overwrite -> 1st PUT hits 503.
    fireEvent.click(document.getElementById("intentDraftRetryButton")!);
    await waitFor(() => {
      expect(putCalls.length).toBe(1);
      expect(document.getElementById("intentDraftRetryButton")?.textContent).toContain("重试保存");
    });
    expect(putCalls[0].body.expected_revision_id).toBe(10);
    expect(putCalls[0].idemKey).toBeTruthy();

    // Step 2: Click "重试保存" -> must issue 2nd PUT with SAME rev=10 & SAME Idempotency-Key!
    fireEvent.click(document.getElementById("intentDraftRetryButton")!);
    await waitFor(() => {
      expect(putCalls.length).toBe(2);
    });
    expect(putCalls[1].body.expected_revision_id).toBe(10);
    expect(putCalls[1].idemKey).toBe(putCalls[0].idemKey);
    await waitFor(() => {
      expect(document.getElementById("intentDraftRecoveryBanner")).not.toBeInTheDocument();
    });
  });
});
