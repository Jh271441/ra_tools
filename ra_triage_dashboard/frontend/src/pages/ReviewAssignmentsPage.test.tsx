import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReviewAssignmentsPage } from "./ReviewAssignmentsPage";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ReviewAssignmentsPage", () => {
  it("renders KPIs, task cards, UiSelect lifecycle filter, and paginated task detail with zero native selects", async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.startsWith("/api/cases/work-splits?")) {
        return {
          ok: true,
          status: 200,
          text: async () =>
            JSON.stringify({
              items: [
                {
                  split_id: "campaign-1113-low",
                  campaign_name: "1113 Low Confidence",
                  lifecycle: "active",
                  is_current: true,
                  appendable: true,
                  release_family: "20261113",
                  role_cohort: "low",
                  workflow_mode: "model_review_and_case_label",
                  total_count: 272,
                  assignment_count: 272,
                  completed_count: 100,
                  pending_count: 172,
                  completion_ratio: 100 / 272,
                  members: [
                    { username: "jasperchen", assigned_count: 68, completed_count: 25, pending_count: 43, completion_ratio: 25 / 68 },
                  ],
                },
              ],
              metrics: { assignment_count: 272, completed_count: 100, pending_count: 172 },
            }),
        };
      }
      if (url.startsWith("/api/cases/work-splits/campaign-1113-low?")) {
        return {
          ok: true,
          status: 200,
          text: async () =>
            JSON.stringify({
              split_id: "campaign-1113-low",
              release_family: "20261113",
              role_cohort: "low",
              lifecycle: "active",
              is_current: true,
              appendable: true,
              total_count: 272,
              assignment_count: 272,
              completed_count: 100,
              pending_count: 172,
              filtered_count: 272,
              page: 1,
              page_size: 20,
              page_count: 14,
              members: [{ username: "jasperchen", assigned_count: 68, completed_count: 25, pending_count: 43 }],
              items: [
                { issue_id: "cn37631883", assignee: "jasperchen", submitted: false },
              ],
            }),
        };
      }
      if (url === "/api/access-users") {
        return {
          ok: true,
          status: 200,
          text: async () => JSON.stringify({ items: [{ username: "jasperchen", role: "admin" }] }),
        };
      }
      return { ok: true, status: 200, text: async () => "{}" };
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithQuery(
      <ReviewAssignmentsPage active lang="en" isAdmin username="jasperchen" />,
    );

    await waitFor(() => expect(screen.getByText("1113 · Low confidence")).toBeInTheDocument());
    expect(container.querySelector("select")).toBeNull();
    expect(screen.getByRole("button", { name: "+ New allocation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit allocation" })).toBeInTheDocument();

    // Open task detail and check Pagination
    fireEvent.click(screen.getByRole("button", { name: "View task detail" }));
    await waitFor(() => expect(screen.getByText("cn37631883")).toBeInTheDocument());
    expect(screen.getByText("1 / 14 · 272")).toBeInTheDocument();
    expect(container.querySelector("select")).toBeNull();
  });
});
