import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReviewAssignmentsPage } from "./ReviewAssignmentsPage";

vi.mock("../api/client", () => ({
  apiRequest: vi.fn(),
  getApiBasePath: () => "/manual-s6",
}));

import { apiRequest } from "../api/client";
const mockApi = vi.mocked(apiRequest);

function renderPage(props: Partial<React.ComponentProps<typeof ReviewAssignmentsPage>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ReviewAssignmentsPage
        active
        lang="zh"
        selectedBaselines={["0508"]}
        isAdmin
        username="ux-smoke-admin"
        verified
        {...props}
      />
    </QueryClientProvider>,
  );
}

describe("ReviewAssignmentsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/manual-s6/review-assignments");
  });

  it("renders KPI metrics, version & manual batches with conflict badge, and zero native selects", async () => {
    mockApi.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/cases/work-splits?")) {
        return {
          items: [
            {
              split_id: "ver-1113",
              appendable: true,
              actively_appending: true,
              release_family: "20261113",
              role_cohort: "sampling",
              is_current: true,
              lifecycle: "active",
              workflow_mode: "model_review_and_case_label",
              total_count: 80,
              assignment_count: 160,
              completed_count: 120,
              pending_count: 40,
              completion_ratio: 0.75,
              conflict_count: 3,
              last_target_added_at: "2026-11-25T10:00:00Z",
              members: [
                { username: "alice", assigned_count: 80, completed_count: 60, pending_count: 20, completion_ratio: 0.75 },
              ],
            },
          ],
          metrics: { assignment_count: 160, completed_count: 120, pending_count: 40 },
        };
      }
      if (path.startsWith("/api/model-runs")) {
        return { items: [{ id: "run-1", name: "Run Alpha", baseline_prediction_count: 100 }] };
      }
      if (path === "/api/access-users") {
        return { items: [{ username: "alice", role: "writer" }] };
      }
      return {};
    });

    const { container } = renderPage();
    expect(await screen.findByText(/1113 · 抽样集/)).toBeInTheDocument();
    expect(screen.getByText("3 条相交冲突待裁决")).toBeInTheDocument();
    expect(screen.getByText("自动 · 持续追加")).toBeInTheDocument();
    expect(container.querySelectorAll("select").length).toBe(0);
  });

  it("opens inline detail card and allocation editor dialog on click", async () => {
    mockApi.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/cases/work-splits?")) {
        return {
          items: [
            {
              split_id: "split-manual-1",
              campaign_name: "Manual Split A",
              model_run_id: "run-1",
              is_current: true,
              lifecycle: "active",
              workflow_mode: "model_review_and_case_label",
              total_count: 10,
              assignment_count: 10,
              completed_count: 4,
              pending_count: 6,
              completion_ratio: 0.4,
              created_by: "ux-smoke-admin",
              created_at: "2026-11-25T08:00:00Z",
              members: [{ username: "alice", assigned_count: 10, completed_count: 4, pending_count: 6, completion_ratio: 0.4 }],
            },
          ],
          metrics: { assignment_count: 10, completed_count: 4, pending_count: 6 },
        };
      }
      if (path.startsWith("/api/cases/work-splits/split-manual-1")) {
        return {
          split_id: "split-manual-1",
          campaign_name: "Manual Split A",
          is_current: true,
          lifecycle: "active",
          total_count: 10,
          assignment_count: 10,
          completed_count: 4,
          pending_count: 6,
          completion_ratio: 0.4,
          page: 1,
          page_count: 1,
          members: [{ username: "alice", assigned_count: 10 }],
          items: [
            { issue_id: "cn100001", assignee: "alice", assignment_kind: "base", submitted: false, title: "Scenario X" },
          ],
          changes: [],
        };
      }
      if (path === "/api/campaigns/split-manual-1/allocation") {
        return {
          campaign_id: "split-manual-1",
          name: "Manual Split A",
          editable: true,
          expected_revision: 1,
          member_count: 10,
          movable_slots: 6,
          quota_basis: "remaining",
          eligible_members: [{ username: "alice", role: "writer" }, { username: "bob", role: "writer" }],
          groups: [{ group_id: "group-1", coverage_percent: 100, coverage_strategy: "overlap", members: [{ name: "alice", review_percent: 100 }] }],
          group_coverage: {
            case_count: 10,
            active_slots: 10,
            groups: [{ group_id: "group-1", members: [{ name: "alice", total: 10, completed: 4 }] }],
            combinations: [{ owners: ["alice"], count: 10 }],
          },
        };
      }
      if (path === "/api/campaigns/split-manual-1/allocation/preview") {
        return {
          preview_token: "tok-1",
          group_coverage: {
            case_count: 10,
            active_slots: 10,
            groups: [{ group_id: "group-1", members: [{ name: "alice", total: 10, completed: 4 }] }],
            combinations: [{ owners: ["alice"], count: 10 }],
          },
          members: [{ name: "alice", before: 10, total_after: 10, completed: 4, incoming: 0, outgoing: 0 }],
        };
      }
      if (path.startsWith("/api/model-runs")) return { items: [] };
      if (path === "/api/access-users") {
        return { items: [{ username: "alice", role: "writer" }, { username: "bob", role: "writer" }] };
      }
      return {};
    });

    renderPage();
    const detailBtn = await screen.findByRole("button", { name: "查看任务明细" });
    fireEvent.click(detailBtn);
    expect(await screen.findByText("cn100001")).toBeInTheDocument();

    const editBtn = screen.getByRole("button", { name: "修改分配" });
    fireEvent.click(editBtn);
    expect(await screen.findByText("修改任务分配")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("本次变动")).toBeInTheDocument();
    });
  });

  it("preserves comparison=none (and non-standard gallery comparison filters) across recount and preview without expanding to all", async () => {
    window.sessionStorage.setItem(
      "manual-review-allocation-draft-v1",
      JSON.stringify({
        created_at: new Date().toISOString(),
        total: 866,
        fromReview: true,
        filters: {
          model_run_id: "0821-review-backfill-20261019",
          comparison: "none",
          baselines: "0821-odd2",
        },
        groupSetup: {
          groups: [
            {
              group_id: "group-1",
              coverage_percent: 100,
              coverage_strategy: "overlap",
              members: [{ name: "alice", review_percent: 100 }],
            },
          ],
          cross_groups: [],
          pairing_mode: "orthogonal",
          inputUnit: "percent",
          ruleScopes: [],
        },
      }),
    );

    const caseUrls: string[] = [];
    const splitPayloads: Array<Record<string, unknown>> = [];

    mockApi.mockImplementation(async (path: string, init?: { method?: string; body?: unknown }) => {
      if (path.startsWith("/api/cases/work-splits?")) {
        return {
          items: [],
          metrics: { assignment_count: 0, completed_count: 0, pending_count: 0 },
        };
      }
      if (path.startsWith("/api/model-runs")) {
        return {
          items: [
            {
              id: "0821-review-backfill-20261019",
              name: "0821 Backfill",
              baseline_prediction_count: 160,
            },
          ],
        };
      }
      if (path === "/api/access-users") {
        return {
          items: [
            { username: "alice", role: "writer" },
            { username: "bob", role: "writer" },
          ],
        };
      }
      if (path.startsWith("/api/cases?")) {
        caseUrls.push(path);
        const params = new URLSearchParams(path.split("?")[1] || "");
        const comp = params.get("comparison") || "";
        return {
          total: comp === "none" ? 866 : 1026,
          items: [],
        };
      }
      if (path === "/api/cases/work-split" && init?.method === "POST") {
        const body = (init.body || {}) as Record<string, unknown>;
        splitPayloads.push(body);
        const filters = (body.filters || {}) as Record<string, string>;
        const count = filters.comparison === "none" ? 866 : 1026;
        return {
          preview: {
            total: count,
            assignment_count: count,
            group_coverage: {
              case_count: count,
              active_slots: count,
              groups: [{ group_id: "group-1", members: [{ name: "alice", total: count, completed: 0 }] }],
              combinations: [{ owners: ["alice"], count }],
            },
            members: [{ name: "alice", total: count, before: 0, total_after: count, completed: 0 }],
          },
        };
      }
      return {};
    });

    window.history.replaceState({}, "", "/manual-s6/review-assignments?new=1&baselines=0821-odd2");
    const { container } = renderPage({ selectedBaselines: ["0821-odd2"] });

    await waitFor(() => {
      expect(caseUrls.length).toBeGreaterThan(0);
    });
    expect(
      caseUrls.every((u) => new URLSearchParams(u.split("?")[1] || "").get("comparison") === "none"),
    ).toBe(true);
    expect(screen.getByText(/仅未预测 \(NONE\)/)).toBeInTheDocument();
    await waitFor(() => {
      expect(container.querySelector(".work-split-scope-count")?.textContent || "").toContain("866");
    });

    await waitFor(
      () => {
        expect(splitPayloads.length).toBeGreaterThan(0);
      },
      { timeout: 1500 },
    );
    const lastBody = splitPayloads.at(-1) || {};
    const lastFilters = (lastBody.filters || {}) as Record<string, string>;
    expect(lastBody.preview_only).toBe(true);
    expect(lastFilters.comparison).toBe("none");
    expect(lastFilters.comparison_status).toBe("none");
    expect(lastFilters.baselines).toBe("0821-odd2");
    window.sessionStorage.removeItem("manual-review-allocation-draft-v1");
  });
});
