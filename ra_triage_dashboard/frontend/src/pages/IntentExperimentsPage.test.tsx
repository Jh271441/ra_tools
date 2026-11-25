import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IntentExperimentsPage } from "./IntentExperimentsPage";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const DATASETS_PAYLOAD = {
  items: [
    { id: "0206-1335-v1", display_name: "0206 · 1335", available: true, case_count: 1335 },
  ],
};

const EXPERIMENTS_PAYLOAD = {
  items: [
    {
      id: "exp-1",
      dataset_id: "0206-1335-v1",
      name: "0206 交叉盲标",
      label_scope: "all",
      annotation_mode: "blind",
      annotation_status_filter: "all",
      overlap_ratio: 0.2,
      overlap_reviewers: 2,
      case_count: 100,
      assignment_count: 120,
      created_by: "jasperchen",
      status: "active",
      update_count: 1,
      members: [
        { username: "jasperchen", total: 60, base: 50, cross: 10 },
        { username: "alice", total: 60, base: 50, cross: 10 },
      ],
      progress: { total: 120, completed: 80, partial: 10, pending: 30 },
    },
  ],
  eligible_members: [
    { username: "jasperchen", role: "admin" },
    { username: "alice", role: "writer" },
  ],
  annotation_status_counts: {
    "0206-1335-v1": { all: 1335, labeled: 200, unlabeled: 1135 },
  },
  name_suggestion: { llm_available: false },
};

describe("IntentExperimentsPage", () => {
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
    window.history.replaceState({}, "", "/intent-experiments?dataset=0206-1335-v1");
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
      if (url.includes("/api/intent-experiments")) {
        return Promise.resolve(
          new Response(JSON.stringify(EXPERIMENTS_PAYLOAD), {
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

  it("renders create form, experiment cards, zero native selects, and opens edit & close modals", async () => {
    const { container } = renderWithQuery(
      <IntentExperimentsPage active lang="zh" canManageIntent />,
    );

    await waitFor(() => {
      expect(screen.getByText("0206 交叉盲标")).toBeInTheDocument();
    });
    expect(container.querySelectorAll("select").length).toBe(0);
    expect(screen.getByText("完成 80 / 120 · 进行中 10")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "编辑实验" }));
    await waitFor(() => {
      expect(document.getElementById("raIntentExperimentEditDialog")).toBeInTheDocument();
    });
    expect(document.querySelectorAll("#raIntentExperimentEditDialog select").length).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭实验" }));
    await waitFor(() => {
      expect(screen.getByText(/仍会保留实验与分配记录/)).toBeInTheDocument();
    });
  });

  it("renders English UI cleanly", async () => {
    renderWithQuery(<IntentExperimentsPage active lang="en" canManageIntent={false} />);

    await waitFor(() => {
      expect(screen.getByText("0206 交叉盲标")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Resume labeling" })).toBeInTheDocument();
  });
});
