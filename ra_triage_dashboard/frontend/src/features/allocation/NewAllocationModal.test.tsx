import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NewAllocationModal } from "./NewAllocationModal";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("NewAllocationModal", () => {
  it("keeps modal open when selecting UiSelect option via mouse click and previews via POST /api/cases/work-split with preview_only:true", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/dashboard-config") {
        return {
          ok: true,
          status: 200,
          text: async () =>
            JSON.stringify({ baselines: [{ id: "0508", label: "0508", default_selected: true }] }),
        };
      }
      if (url.startsWith("/api/model-runs")) {
        return {
          ok: true,
          status: 200,
          text: async () =>
            JSON.stringify({
              items: [{ id: "run-1", name: "H2 Model", baseline_prediction_count: 1071 }],
            }),
        };
      }
      if (url.startsWith("/api/cases?")) {
        return { ok: true, status: 200, text: async () => JSON.stringify({ total: 1071 }) };
      }
      if (url === "/api/cases/work-split" && init?.method === "POST") {
        const parsed = JSON.parse(String(init.body || "{}"));
        expect(parsed.preview_only).toBe(true);
        return {
          ok: true,
          status: 200,
          text: async () =>
            JSON.stringify({
              preview: {
                preview_token: "tok-new",
                total_slots: 1071,
                group_coverage: {
                  case_count: 1071,
                  groups: [{ group_id: "group-1", members: [{ name: "jasperchen", total: 1071 }] }],
                },
              },
            }),
        };
      }
      if (url === "/api/assignment-name-suggestion") {
        return {
          ok: true,
          status: 200,
          text: async () => JSON.stringify({ source: "llm", suggestion: "0508 H2 AI Name" }),
        };
      }
      return { ok: true, status: 200, text: async () => "{}" };
    });
    vi.stubGlobal("fetch", fetchMock);

    const onClose = vi.fn();
    renderWithQuery(
      <NewAllocationModal
        open
        lang="en"
        eligibleMembers={["jasperchen", "bob"]}
        onClose={onClose}
        onCreated={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText(/1,071 Case/)).toBeInTheDocument());

    // Open member UiSelect and click option with mouse (must NOT close modal!)
    const memberPicker = screen.getByRole("combobox", { name: "Group 1 member 1" });
    fireEvent.click(memberPicker);
    const opt = screen.getByRole("option", { name: "jasperchen" });
    fireEvent.mouseDown(opt);
    fireEvent.click(opt);

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    // Verify live preview via POST /api/cases/work-split { preview_only: true }
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/cases/work-split",
        expect.objectContaining({ method: "POST" }),
      );
    });
    await waitFor(() => expect(screen.getByText(/1,071/)).toBeInTheDocument());
  });
});
