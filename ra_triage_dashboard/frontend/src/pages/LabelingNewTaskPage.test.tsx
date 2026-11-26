import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LabelingNewTaskPage } from "./LabelingNewTaskPage";

vi.mock("../api/client", () => ({
  apiRequest: vi.fn(),
  getApiBasePath: () => "/manual-s6",
}));

import { apiRequest } from "../api/client";
const mockApi = vi.mocked(apiRequest);

describe("LabelingNewTaskPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/manual-s6/case-labeling/new-task?baselines=0508");
  });

  it("renders assignment setup, combined review tasks, experiment records, and zero native selects", async () => {
    mockApi.mockImplementation(async (path: string) => {
      if (path.startsWith("/api/labeling/cases?")) return { total: 42 };
      if (path.startsWith("/api/labeling/tasks")) {
        return {
          items: [
            {
              id: "lbl-exp-1",
              name: "0508 标注实验",
              lifecycle: "active",
              is_current: true,
              member_count: 42,
              reviewers_per_issue: 2,
              overlap_ratio: 0.5,
              created_by: "ux-smoke-admin",
              progress: { total: 42, resolved: 21, conflict: 2 },
            },
          ],
        };
      }
      if (path.startsWith("/api/cases/work-splits?")) {
        return {
          items: [
            {
              split_id: "comb-1",
              campaign_name: "Combined Review Alpha",
              workflow_mode: "model_review_and_case_label",
              is_current: true,
              lifecycle: "active",
              total_count: 30,
              assignment_count: 30,
              completed_count: 10,
              pending_count: 20,
              completion_ratio: 0.33,
              members: [{ username: "alice", assigned_count: 30, completed_count: 10, pending_count: 20 }],
            },
          ],
        };
      }
      if (path === "/api/access-users") {
        return { items: [{ username: "alice", role: "writer" }] };
      }
      if (path.startsWith("/api/model-runs")) return { items: [] };
      return {};
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={qc}>
        <LabelingNewTaskPage
          active
          lang="zh"
          selectedBaselines={["0508"]}
          isAdmin
          username="ux-smoke-admin"
          verified
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("0508 标注实验")).toBeInTheDocument();
    expect(await screen.findByText(/Combined Review Alpha/)).toBeInTheDocument();
    expect(screen.getByText("联合复核任务")).toBeInTheDocument();
    expect(screen.getByText("实验记录")).toBeInTheDocument();
    expect(container.querySelectorAll("select").length).toBe(0);
  });
});
