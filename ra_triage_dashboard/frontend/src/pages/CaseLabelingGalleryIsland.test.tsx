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

  it("forwards target_group=sample and drops cleared search immediately before 250ms debounce when opening labeling summary", async () => {
    const navigatePage = vi.fn();
    (window as unknown as Record<string, unknown>).navigatePage = navigatePage;
    window.history.replaceState(
      {},
      "",
      "/manual-s6/case-labeling?baselines=version-20261106&target_group=sample&q=cn35635511",
    );
    (window as unknown as Record<string, unknown>).state = {
      config: {
        baselines: [{ id: "version-20261106", label: "1106 复核集", count: 465 }],
        case_labeling: { active_baseline_ids: ["version-20261106"] },
        review_tag_catalog: [],
      },
    };

    const { container } = renderWithQuery(
      <CaseLabelingGalleryIsland
        active
        lang="zh"
        selectedBaselines={["version-20261106"]}
        isAdmin
        canWrite
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("cn37760285")).toBeInTheDocument();
    });

    // Clear search input and IMMEDIATELY click "标注汇总" before 250ms debounce fires
    const searchInput = container.querySelector<HTMLInputElement>("#caseLabelingSearch");
    expect(searchInput?.value).toBe("cn35635511");
    fireEvent.change(searchInput!, { target: { value: "" } });

    const summaryBtn = container.querySelector<HTMLButtonElement>("#caseLabelingCampaignsButton");
    fireEvent.click(summaryBtn!);

    expect(navigatePage).toHaveBeenCalledTimes(1);
    const [pageArg, optsArg] = navigatePage.mock.calls[0];
    expect(pageArg).toBe("labeling-summary");
    expect(optsArg?.queryParams?.target_group).toBe("sample");
    expect(optsArg?.queryParams?.baselines).toBe("version-20261106");
    expect(optsArg?.queryParams?.q).toBeUndefined();
  });

  it("disables #caseLabelingCreateTask and clears cached total when a subsequent refresh returns HTTP 503", async () => {
    const showPage = vi.fn();
    const syncState = vi.fn();
    (window as unknown as Record<string, unknown>).showPage = showPage;
    (window as unknown as Record<string, unknown>).syncCaseLabelingGalleryState = syncState;

    let failCases = false;
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
          if (failCases) {
            return new Response(JSON.stringify({ detail: "刷新失败 (503)" }), {
              status: 503,
              headers: { "Content-Type": "application/json" },
            });
          }
          return new Response(
            JSON.stringify({
              total: 10,
              page: 1,
              pages: 1,
              page_size: 20,
              items: [
                {
                  issue_id: "cn37760285",
                  gt_label: "误触发",
                  expected_output: "误触发",
                  label_state: "resolved",
                  author: "jasperchen",
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

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <CaseLabelingGalleryIsland
          active
          lang="zh"
          selectedBaselines={["0508"]}
          isAdmin
          canWrite
        />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(container.querySelector("#caseLabelingCount")?.textContent).toBe("10");
    });
    const createBtn = container.querySelector<HTMLButtonElement>("#caseLabelingCreateTask");
    expect(createBtn).not.toBeNull();
    expect(createBtn).not.toBeDisabled();

    // Now force the same cached query to fail with HTTP 503 on refresh
    failCases = true;
    await client.invalidateQueries({ queryKey: ["labeling-gallery-cases"] });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(container.querySelector("#caseLabelingCount")?.textContent).toBe("—");
    expect(createBtn).toBeDisabled();
    fireEvent.click(createBtn!);
    expect(showPage).not.toHaveBeenCalled();
    const lastSynced = syncState.mock.calls.at(-1)?.[0] as { data?: { total?: number } } | undefined;
    expect(lastSynced?.data?.total).toBe(0);
  });
});
