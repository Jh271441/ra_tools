import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CampaignsPage } from "./CampaignsPage";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const LIST_PAYLOAD = {
  items: [
    {
      id: "camp-1106",
      name: "1106 复核标注实验",
      purpose: "labeling",
      lifecycle: "active",
      config_revision: 3,
      baseline_scopes: ["release1106"],
      reference_type: "gt",
      reference_id: "gt-snap-1106",
      progress: {
        member_count: 100,
        assigned_issue_count: 100,
        completed_issue_count: 60,
        required_submitter_count: 120,
        submitted_submitter_count: 80,
      },
    },
  ],
  historical_imports: [],
};

const DETAIL_PAYLOAD = {
  campaign: LIST_PAYLOAD.items[0],
  progress: {
    ...LIST_PAYLOAD.items[0].progress,
    purpose: "labeling",
    pending_issue_count: 40,
    conflict_issue_count: 2,
    label_output_counts: { 误触发: 30, 正确触发: 20, 无需协助: 10 },
    reference_relation_counts: { matches_gt: 45, differs_from_gt: 15 },
    tag_counts: {},
    scenario_counts: { 路口排队: 12 },
  },
  assignees: [{ name: "jasperchen", assigned_slots: 60, submitted_slots: 40, completed_slots: 30 }],
  issues: [
    {
      issue_id: "cn37760285",
      gt_label: "误触发",
      expected_output: "误触发",
      assignments: [{ assignee: "jasperchen", assignment_kind: "base" }],
      submitted: 1,
      required_submitter_count: 1,
      state: "completed",
    },
  ],
  total: 1,
  page: 1,
  page_count: 1,
  revisions: [],
  lifecycle_audit: [],
  assignment_audit: [],
};

describe("CampaignsPage", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/campaigns?baselines=version-20261106");
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/campaigns/camp-1106")) {
        return Promise.resolve(
          new Response(JSON.stringify(DETAIL_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/campaigns")) {
        return Promise.resolve(
          new Response(JSON.stringify(LIST_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ items: [], review_tag_catalog: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders list view, enforces zero native selects, and drills into campaign detail", async () => {
    const { container } = renderWithQuery(
      <CampaignsPage
        active
        lang="zh"
        theme="dark"
        selectedBaselines={["version-20261106"]}
        isAdmin
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("1106 复核标注实验")).toBeInTheDocument();
    });
    expect(container.querySelectorAll("select").length).toBe(0);

    fireEvent.click(screen.getByText("1106 复核标注实验"));
    await waitFor(() => {
      expect(screen.getByText("cn37760285")).toBeInTheDocument();
    });
    expect(container.querySelectorAll("select").length).toBe(0);
    expect(screen.getByText("标注结果分布")).toBeInTheDocument();
  });

  it("renders English UI cleanly", async () => {
    renderWithQuery(
      <CampaignsPage
        active
        lang="en"
        theme="light"
        selectedBaselines={["version-20261106"]}
        isAdmin={false}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Tasks and labeling results")).toBeInTheDocument();
    });
    expect(screen.getByRole("tab", { name: "All experiments" })).toBeInTheDocument();
  });
});
