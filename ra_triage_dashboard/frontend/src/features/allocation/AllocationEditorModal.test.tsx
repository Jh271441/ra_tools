import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AllocationEditorModal } from "./AllocationEditorModal";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AllocationEditorModal", () => {
  it("loads campaign allocation, triggers live preview, and submits PATCH with Idempotency-Key", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/campaigns/camp-1/allocation" && (!init?.method || init.method === "GET")) {
        return {
          ok: true,
          status: 200,
          text: async () =>
            JSON.stringify({
              campaign_id: "camp-1",
              name: "1113 Low Confidence",
              editable: true,
              expected_revision: 74,
              member_count: 100,
              movable_slots: 80,
              completed_slots: 20,
              saved_pending_slots: 0,
              quota_basis: "remaining",
              pairing_mode: "orthogonal",
              eligible_members: ["alice", "bob", "carol"],
              groups: [
                {
                  group_id: "group-1",
                  coverage_percent: 100,
                  members: [
                    { name: "alice", review_percent: 50 },
                    { name: "bob", review_percent: 50 },
                  ],
                },
              ],
            }),
        };
      }
      if (url === "/api/campaigns/camp-1/allocation/preview") {
        return {
          ok: true,
          status: 200,
          text: async () =>
            JSON.stringify({
              preview_token: "tok-abc",
              total_slots: 100,
              changed_cases: 12,
              moved_slots: 12,
              completed_slots: 20,
              saved_pending_slots: 0,
              group_coverage: {
                case_count: 100,
                groups: [
                  {
                    group_id: "group-1",
                    members: [
                      { name: "alice", total: 60 },
                      { name: "bob", total: 40 },
                    ],
                  },
                ],
              },
              members: [
                { name: "alice", before: 50, total_after: 60, pending_after: 50, completed: 10, saved_pending: 0, incoming: 10, outgoing: 0 },
                { name: "bob", before: 50, total_after: 40, pending_after: 30, completed: 10, saved_pending: 0, incoming: 0, outgoing: 10 },
              ],
              changes: [{ issue_id: "cn100", before: ["bob"], after: ["alice"] }],
            }),
        };
      }
      if (url === "/api/campaigns/camp-1/allocation" && init?.method === "PATCH") {
        return { ok: true, status: 200, text: async () => JSON.stringify({ changed: true }) };
      }
      return { ok: true, status: 200, text: async () => "{}" };
    });
    vi.stubGlobal("fetch", fetchMock);

    const onClose = vi.fn();
    const onSaved = vi.fn();
    const { container } = renderWithQuery(
      <AllocationEditorModal campaignId="camp-1" lang="en" onClose={onClose} onSaved={onSaved} />,
    );

    await waitFor(() => expect(screen.getByText(/1113 Low Confidence/)).toBeInTheDocument());
    expect(container.querySelector("select")).toBeNull();

    await waitFor(() => expect(screen.getByText(/Changes by Case/)).toBeInTheDocument());
    const applyBtn = screen.getByRole("button", { name: "Apply changes" });
    await waitFor(() => expect(applyBtn).not.toBeDisabled());

    fireEvent.click(applyBtn);
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/campaigns/camp-1/allocation",
        expect.objectContaining({
          method: "PATCH",
          headers: expect.objectContaining({
            "X-RA-Triage-Request": "browser-v1",
            "Idempotency-Key": expect.any(String),
          }),
        }),
      );
    });
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
