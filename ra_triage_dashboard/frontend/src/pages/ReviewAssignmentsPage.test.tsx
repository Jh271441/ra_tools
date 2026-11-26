import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

    // 638bfdef parity: batch search filters cards and syncs batch_search to URL
    const batchSearchInput = container.querySelector<HTMLInputElement>("#reviewAssignmentBatchSearch");
    expect(batchSearchInput).not.toBeNull();
    fireEvent.change(batchSearchInput!, { target: { value: "nonexistent-batch" } });
    expect(screen.getByText(/未找到匹配的批次/)).toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).get("batch_search")).toBe("nonexistent-batch");
    fireEvent.change(batchSearchInput!, { target: { value: "1113" } });
    expect(screen.getByText(/1113 · 抽样集/)).toBeInTheDocument();
    expect(container.querySelector("#reviewAssignmentListStatus")?.textContent).toBe("匹配 1 / 1 个任务");
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
              baseline_ids: ["0821-odd2", "0821-nonodd2"],
              partition_case_counts: { "0821-odd2": 12, "0821-nonodd2": 3 },
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
          purpose: "model_review",
          editable: true,
          expected_revision: 1,
          member_count: 10,
          movable_slots: 6,
          quota_basis: "total",
          total_slots: 10,
          completed_slots: 4,
          coverage: { cross_cases: 0, case_count: 10 },
          eligible_members: [{ username: "alice", role: "writer" }, { username: "bob", role: "writer" }],
          groups: [{ group_id: "group-1", coverage_percent: 100, coverage_strategy: "overlap",
            members: [{ name: "alice", review_percent: 50 }, { name: "bob", review_percent: 50 }] }],
          group_coverage: {
            case_count: 10,
            active_slots: 10,
            groups: [{ group_id: "group-1", members: [{ name: "alice", total: 6, completed: 4 }, { name: "bob", total: 4, completed: 0 }] }],
            combinations: [{ owners: ["alice"], count: 6 }, { owners: ["bob"], count: 4 }],
          },
        };
      }
      if (path === "/api/campaigns/split-manual-1/allocation/preview") {
        return {
          preview_token: "tok-1",
          moved_slots: 0,
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
    expect(await screen.findByText(/0821 · ODD2 12 例 \/ 非 ODD2 3 例/)).toBeInTheDocument();
    const detailBtn = await screen.findByRole("button", { name: "查看任务明细" });
    fireEvent.click(detailBtn);
    expect(await screen.findByText("cn100001")).toBeInTheDocument();

    const editBtn = screen.getByRole("button", { name: "修改分配" });
    fireEvent.click(editBtn);
    expect(await screen.findByText("修改任务分配")).toBeInTheDocument();
    expect(await screen.findByText("当前分配 · 0 人变动")).toBeInTheDocument();
    expect(screen.getByDisplayValue("60")).toBeInTheDocument();
    expect(screen.getByDisplayValue("40")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^条$/ }));
    expect(screen.getByDisplayValue("6")).toBeInTheDocument();
    expect(screen.getByDisplayValue("4")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "应用调整" })).toBeDisabled();
    expect(mockApi.mock.calls.some(([path]) => path.endsWith("/allocation/preview"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "将可转派待办分给我" }));
    expect(await screen.findByText("没有可转给你的待办")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "关闭" }));
    fireEvent.click(screen.getByRole("button", { name: "修改分配" }));
    expect(await screen.findByText("当前分配 · 0 人变动")).toBeInTheDocument();
    expect(mockApi.mock.calls.filter(([path]) => path.endsWith("/allocation/preview"))).toHaveLength(1);
  });

  it("groups historical 0821 batches and opens the exact pending queue for all owners", async () => {
    const historical = (id: string, baseline: string, odd: string | null, cases: number) => ({
      split_id: `campaign-${id}`, model_run_id: `run-${id}`, campaign_name: id,
      source_created_at: "2026-09-09T13:18:07+08:00",
      is_current: true, lifecycle: "active", workflow_mode: "model_review_and_case_label",
      baseline_ids: [baseline], total_count: cases, assignment_count: cases * 2,
      completed_count: cases * 2, pending_issue_ids: [], conflict_issue_ids: [],
      filter_snapshot: { partition_parent_campaign_id: "parent", partition_field: "trip_odd", partition_value: odd },
    });
    mockApi.mockImplementation(async (path) => path.startsWith("/api/cases/work-splits?")
      ? { items: [
          { split_id: "campaign-ordinary", campaign_name: "Ordinary", is_current: true },
          { ...historical("odd2", "0821-odd2", "ODD2", 110), completed_count: 217,
            pending_issue_ids: ["cn35722425", "cn35743259", "cn35690387"] },
          historical("odd3", "0821-nonodd2", "ODD3", 88),
          historical("unknown", "0821-nonodd2", null, 2),
        ] }
      : { items: [] });

    const { container } = renderPage();
    await screen.findByText("0821 历史 · ODD2 联合复核");
    expect(Array.from(container.querySelectorAll("[data-review-assignment-batch]"))
      .map((item) => item.getAttribute("data-review-assignment-batch")))
      .toEqual(["campaign-ordinary", "0821-odd2", "0821-nonodd2"]);
    fireEvent.click(screen.getByRole("button", { name: "查看剩余 3 个 Issue" }));
    const target = screen.getByRole("link", { name: "查看剩余 3 个 Issue" });
    const params = new URL(target.getAttribute("href")!, window.location.origin).searchParams;
    expect(params.get("work_split")).toBe("campaign-odd2");
    expect(params.get("task_progress")).toBe("pending");
    expect(params.get("issue_ids")).toBe("cn35722425,cn35743259,cn35690387");
    expect(params.has("work_assignee")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "ODD 未填写 · 2 例" }));
    const nonOdd2 = container.querySelector<HTMLElement>('[data-review-assignment-batch="0821-nonodd2"]')!;
    expect(within(nonOdd2).getByText(/2 例 · ODD 未填写/)).toBeInTheDocument();
    expect(within(nonOdd2).queryByText(/88 例/)).not.toBeInTheDocument();
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

  it("preserves baselines and existing URL params during batch search enter/edit/clear, restores on cold boot, and does not push history entries", async () => {
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
              total_count: 119,
              assignment_count: 238,
              completed_count: 77,
              pending_count: 161,
              completion_ratio: 0.32,
              last_target_added_at: "2026-11-26T00:00:00Z",
              members: [],
            },
            {
              split_id: "ver-1106",
              appendable: true,
              actively_appending: false,
              release_family: "20261106",
              role_cohort: "low",
              is_current: true,
              lifecycle: "active",
              workflow_mode: "model_review_and_case_label",
              total_count: 348,
              assignment_count: 348,
              completed_count: 200,
              pending_count: 148,
              completion_ratio: 0.57,
              last_target_added_at: "2026-11-20T00:00:00Z",
              members: [],
            },
          ],
          metrics: { assignment_count: 586, completed_count: 277, pending_count: 309 },
        };
      }
      if (path.startsWith("/api/model-runs")) return { items: [] };
      if (path === "/api/access-users") return { items: [] };
      return {};
    });

    // Scenario 1: URL with baselines only — enter, edit, clear search step-by-step
    window.history.replaceState({}, "", "/manual-s6/review-assignments?baselines=0821-odd2");
    const historyLenBefore = window.history.length;
    const replaceSpy = vi.spyOn(window.history, "replaceState");
    const pushSpy = vi.spyOn(window.history, "pushState");

    const first = renderPage({ selectedBaselines: ["0821-odd2"] });
    expect(await screen.findByText(/1113 · 抽样集/)).toBeInTheDocument();
    expect(screen.getByText(/1106 · 低置信集/)).toBeInTheDocument();

    const input1 = first.container.querySelector<HTMLInputElement>("#reviewAssignmentBatchSearch")!;
    fireEvent.change(input1, { target: { value: "1113" } });
    expect(window.location.pathname + window.location.search).toBe(
      "/manual-s6/review-assignments?baselines=0821-odd2&batch_search=1113",
    );
    expect(screen.getByText(/1113 · 抽样集/)).toBeInTheDocument();
    expect(screen.queryByText(/1106 · 低置信集/)).not.toBeInTheDocument();
    expect(first.container.querySelector("#reviewAssignmentListStatus")?.textContent).toBe("匹配 1 / 2 个任务");

    // Modify search term
    fireEvent.change(input1, { target: { value: "1106" } });
    expect(window.location.pathname + window.location.search).toBe(
      "/manual-s6/review-assignments?baselines=0821-odd2&batch_search=1106",
    );
    expect(screen.getByText(/1106 · 低置信集/)).toBeInTheDocument();
    expect(screen.queryByText(/1113 · 抽样集/)).not.toBeInTheDocument();

    // Clear search term — deletes ONLY batch_search, preserves baselines
    fireEvent.change(input1, { target: { value: "" } });
    expect(window.location.pathname + window.location.search).toBe(
      "/manual-s6/review-assignments?baselines=0821-odd2",
    );
    expect(screen.getByText(/1113 · 抽样集/)).toBeInTheDocument();
    expect(screen.getByText(/1106 · 低置信集/)).toBeInTheDocument();
    expect(first.container.querySelector("#reviewAssignmentListStatus")?.textContent).toBe("2 个任务");
    expect(window.history.length).toBe(historyLenBefore);
    expect(pushSpy).not.toHaveBeenCalled();
    expect(replaceSpy).toHaveBeenCalled();

    // Copy searched URL for cold-boot test (Scenario 3)
    fireEvent.change(input1, { target: { value: "1113" } });
    const copiedUrl = window.location.pathname + window.location.search;
    expect(copiedUrl).toBe("/manual-s6/review-assignments?baselines=0821-odd2&batch_search=1113");
    first.unmount();

    // Scenario 3: Cold boot from copied URL restores baselines, search input, and filtered results
    window.history.replaceState({}, "", copiedUrl);
    const cold = renderPage({ selectedBaselines: ["0821-odd2"] });
    expect(await screen.findByText(/1113 · 抽样集/)).toBeInTheDocument();
    expect(screen.queryByText(/1106 · 低置信集/)).not.toBeInTheDocument();
    expect(cold.container.querySelector<HTMLInputElement>("#reviewAssignmentBatchSearch")?.value).toBe("1113");
    expect(window.location.pathname + window.location.search).toBe(copiedUrl);
    expect(window.history.length).toBe(historyLenBefore);
    cold.unmount();

    // Scenario 2: URL with baselines + lifecycle + assigned_to_me preserves all params verbatim
    window.history.replaceState(
      {},
      "",
      "/manual-s6/review-assignments?baselines=0821-odd2&lifecycle=versions&assigned_to_me=true",
    );
    const second = renderPage({ selectedBaselines: ["0821-odd2"] });
    expect(await screen.findByText(/1113 · 抽样集/)).toBeInTheDocument();
    const input2 = second.container.querySelector<HTMLInputElement>("#reviewAssignmentBatchSearch")!;
    fireEvent.change(input2, { target: { value: "1113" } });
    const pWithSearch = new URLSearchParams(window.location.search);
    expect(pWithSearch.get("baselines")).toBe("0821-odd2");
    expect(pWithSearch.get("lifecycle")).toBe("versions");
    expect(pWithSearch.get("assigned_to_me")).toBe("true");
    expect(pWithSearch.get("batch_search")).toBe("1113");

    fireEvent.change(input2, { target: { value: "   " } });
    const pCleared = new URLSearchParams(window.location.search);
    expect(pCleared.get("baselines")).toBe("0821-odd2");
    expect(pCleared.get("lifecycle")).toBe("versions");
    expect(pCleared.get("assigned_to_me")).toBe("true");
    expect(pCleared.get("batch_search")).toBeNull();
    expect(window.history.length).toBe(historyLenBefore);
    expect(pushSpy).not.toHaveBeenCalled();

    replaceSpy.mockRestore();
    pushSpy.mockRestore();
  });
});
