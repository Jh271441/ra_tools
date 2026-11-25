import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
});
