import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IntentSummaryPage } from "./IntentSummaryPage";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const DATASETS_PAYLOAD = {
  items: [
    { id: "0206-1335-v1", display_name: "0206 · 1335", available: true, case_count: 1335 },
    { id: "0508-1071-v1", display_name: "0508 · 1071", available: true, case_count: 1071 },
  ],
};

const SUMMARY_PAYLOAD = {
  dataset_ids: ["0206-1335-v1"],
  axis: "all",
  label_scope: "all",
  case_count: 1335,
  annotated_cases: 120,
  complete_records: 118,
  agreement: { comparable_cases: 40, matching_cases: 36 },
  frame_distributions: {
    routing: { go_straight: 200, left_turn: 80 },
    lane_change: { lane_keep: 210, left_lane_change: 70 },
  },
  comment_query: "",
  comment_hits: [],
  blind_active: false,
  answers_revealed: true,
  experiments: [
    { id: "exp-1", dataset_id: "0206-1335-v1", name: "首轮盲标", label_scope: "all" },
  ],
  owners: ["jasperchen", "alice"],
  items: [
    {
      dataset_id: "0206-1335-v1",
      case_id: "cn37760285",
      username: "jasperchen",
      revision_id: 42,
      completion: { complete: true, reason: "全部时间点已标注" },
      frame_counts: {
        routing: { go_straight: 10, left_turn: 2 },
        lane_change: { lane_keep: 12 },
      },
      comments: [{ id: 7, author: "jasperchen", body: "交叉口直行" }],
      comment_count: 1,
      updated_at: "2026-11-25T07:08:28Z",
    },
  ],
  total: 1,
  page: 1,
  page_size: 20,
};

describe("IntentSummaryPage", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    if (!HTMLDialogElement.prototype.showModal) {
      HTMLDialogElement.prototype.showModal = function () {
        this.setAttribute("open", "");
      };
    }
    if (!HTMLDialogElement.prototype.close) {
      HTMLDialogElement.prototype.close = function () {
        this.removeAttribute("open");
      };
    }
    window.history.replaceState({}, "", "/intent-summary?dataset=0206-1335-v1");
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/intent-datasets")) {
        return Promise.resolve(
          new Response(JSON.stringify(DATASETS_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/intent-summary")) {
        return Promise.resolve(
          new Response(JSON.stringify(SUMMARY_PAYLOAD), {
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

  it("renders KPIs, distributions, table rows, zero native selects, and admin delete dialog", async () => {
    const { container } = renderWithQuery(
      <IntentSummaryPage active lang="zh" username="jasperchen" isAdmin />,
    );

    await waitFor(() => {
      expect(screen.getByText("cn37760285")).toBeInTheDocument();
    });
    expect(container.querySelectorAll("select").length).toBe(0);
    expect(screen.getByText("36 / 40")).toBeInTheDocument();
    expect(screen.getByText("Routing 标签比例")).toBeInTheDocument();
    expect(screen.getByText("变道意图标签比例")).toBeInTheDocument();

    const deleteBtn = screen.getByRole("button", { name: "删除标注" });
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(document.getElementById("raIntentDeleteConfirmDialog")).toBeInTheDocument();
    });
    expect(screen.getByText(/确认删除 jasperchen 在 cn37760285 的当前标注/)).toBeInTheDocument();
  });

  it("renders English labels cleanly when lang=en", async () => {
    renderWithQuery(<IntentSummaryPage active lang="en" username="jasperchen" isAdmin />);

    await waitFor(() => {
      expect(screen.getByText("cn37760285")).toBeInTheDocument();
    });
    expect(screen.getByText("Export Case JSONL")).toBeInTheDocument();
    expect(screen.getByText("Export frame JSONL")).toBeInTheDocument();
  });
});
