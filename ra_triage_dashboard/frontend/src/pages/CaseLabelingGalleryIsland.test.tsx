import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CaseLabelingGalleryIsland } from "./CaseLabelingGalleryIsland";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("CaseLabelingGalleryIsland", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/manual-s6/case-labeling?baselines=0508");
    (window as unknown as Record<string, unknown>).selectCaseLabelingIssue = vi
      .fn()
      .mockResolvedValue(undefined);
    (window as unknown as Record<string, unknown>).syncCaseLabelingGalleryState = vi.fn();
    (window as unknown as Record<string, unknown>).state = {
      config: {
        baselines: [{ id: "0508", label: "0508", count: 1071 }],
        case_labeling: { active_baseline_ids: ["0508"] },
        review_tag_catalog: [
          { key: "queue", label: "排队", group: "false_trigger", section: "interaction_decision" },
        ],
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/labeling/tasks")) {
          return new Response(
            JSON.stringify({
              items: [
                {
                  id: "split-abc123",
                  name: "0508 盲标实验",
                  progress: { total: 10, resolved: 6, conflict: 1, assignees: [] },
                },
              ],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.includes("/api/labeling/cases")) {
          return new Response(
            JSON.stringify({
              total: 1,
              page: 1,
              pages: 1,
              page_size: 20,
              labelers: ["jasperchen"],
              assignees: ["jasperchen"],
              queue_issue_ids: ["cn37760285"],
              items: [
                {
                  issue_id: "cn37760285",
                  gt_label: "误触发",
                  expected_output: "误触发",
                  label_state: "resolved",
                  author: "jasperchen",
                  author_verified: true,
                  decision: { full_result: true, stale: false, tags: ["queue"] },
                  thumbnail_url: "/api/cases/cn37760285/thumbnail",
                },
              ],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
  });

  it("renders labeling gallery filters, resolved tag chips, zero native selects, and delegates card open", async () => {
    const { container } = renderWithQuery(
      <CaseLabelingGalleryIsland
        active
        lang="zh"
        selectedBaselines={["0508"]}
        isAdmin
        canWrite
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("cn37760285")).toBeInTheDocument();
    });

    expect(container.querySelectorAll("select").length).toBe(0);
    expect(screen.getByText("排队")).toBeInTheDocument();
    expect(screen.getByText("问题图库")).toBeInTheDocument();

    const openBtn = container.querySelector<HTMLButtonElement>('[data-open-issue="cn37760285"]');
    expect(openBtn).not.toBeNull();
    fireEvent.click(openBtn!);
    expect(
      (window as unknown as { selectCaseLabelingIssue: ReturnType<typeof vi.fn> })
        .selectCaseLabelingIssue,
    ).toHaveBeenCalledWith("cn37760285");
  });

  it("writes search ?q= to URL, forwards active filters to labeling-summary, and renders Issue tag group jump buttons", async () => {
    const navigatePage = vi.fn();
    (window as unknown as Record<string, unknown>).navigatePage = navigatePage;
    (window as unknown as Record<string, unknown>).state = {
      config: {
        baselines: [{ id: "0508", label: "0508", count: 1071 }],
        case_labeling: { active_baseline_ids: ["0508"] },
        review_tag_catalog: [
          { key: "night", label: "夜晚", group: "environment", section: "scene" },
          { key: "queue", label: "排队", group: "false_trigger", section: "interaction_decision" },
        ],
      },
    };

    const { container } = renderWithQuery(
      <CaseLabelingGalleryIsland
        active
        lang="zh"
        selectedBaselines={["0508"]}
        isAdmin
        canWrite
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("cn37760285")).toBeInTheDocument();
    });

    // 1. Typing search updates URL ?q=
    const searchInput = container.querySelector<HTMLInputElement>("#caseLabelingSearch");
    expect(searchInput).not.toBeNull();
    fireEvent.change(searchInput!, { target: { value: "cn37760285" } });
    await waitFor(
      () => {
        expect(new URLSearchParams(window.location.search).get("q")).toBe("cn37760285");
      },
      { timeout: 1500 },
    );

    // 2. Clicking "标注汇总" forwards active filters (q + baselines) to labeling-summary
    const summaryBtn = container.querySelector<HTMLButtonElement>("#caseLabelingCampaignsButton");
    expect(summaryBtn).not.toBeNull();
    fireEvent.click(summaryBtn!);
    expect(navigatePage).toHaveBeenCalledWith(
      "labeling-summary",
      expect.objectContaining({
        queryParams: expect.objectContaining({
          q: "cn37760285",
          baselines: "0508",
        }),
      }),
    );

    // 3. Issue tag dropdown renders group jump navigation
    const tagTrigger = container.querySelector<HTMLButtonElement>("#caseLabelingIssueTagFilter");
    expect(tagTrigger).not.toBeNull();
    fireEvent.click(tagTrigger!);
    const jumpButtons = container.querySelectorAll<HTMLButtonElement>(
      "#caseLabelingIssueTagFilter-panel [data-multi-group-jump]",
    );
    expect(jumpButtons.length).toBeGreaterThanOrEqual(2);
    expect(
      container.querySelector("#caseLabelingIssueTagFilter-panel .multi-filter-group-nav"),
    ).not.toBeNull();
  });

  it("renders explicit error alert instead of zero-results when /api/labeling/cases returns HTTP 503", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/labeling/tasks")) {
          return new Response(JSON.stringify({ items: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("/api/labeling/cases")) {
          return new Response(JSON.stringify({ detail: "标注服务暂不可用 (503)" }), {
            status: 503,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response(JSON.stringify({}), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    const { container } = renderWithQuery(
      <CaseLabelingGalleryIsland
        active
        lang="zh"
        selectedBaselines={["0508"]}
        isAdmin
        canWrite
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByText("Case 列表读取失败")).toBeInTheDocument();
    expect(screen.queryByText("当前范围没有 Case。")).not.toBeInTheDocument();
    expect(container.querySelector("#caseLabelingCount")?.textContent).toBe("—");
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });
});
