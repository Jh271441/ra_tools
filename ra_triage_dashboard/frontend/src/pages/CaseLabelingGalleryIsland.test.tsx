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

  it("clears a 0-result search and immediately clicks #caseLabelingCreateTask before debounce, fetching live count and navigating", async () => {
    const showPage = vi.fn();
    const syncState = vi.fn();
    (window as unknown as Record<string, unknown>).showPage = showPage;
    (window as unknown as Record<string, unknown>).syncCaseLabelingGalleryState = syncState;
    window.history.replaceState({}, "", "/manual-s6/case-labeling?baselines=0508&q=cn35635511");

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
          const params = new URLSearchParams(url.split("?")[1] || "");
          const q = params.get("q") || "";
          if (q === "cn35635511") {
            return new Response(
              JSON.stringify({ total: 0, page: 1, pages: 1, page_size: 20, items: [] }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            );
          }
          return new Response(
            JSON.stringify({
              total: 1071,
              page: 1,
              pages: 54,
              page_size: 20,
              items: [{ issue_id: "cn37760285", gt_label: "误触发" }],
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
      expect(container.querySelector("#caseLabelingCount")?.textContent).toBe("0");
    });

    const searchInput = container.querySelector<HTMLInputElement>("#caseLabelingSearch");
    expect(searchInput?.value).toBe("cn35635511");

    // Clear 0-result search and IMMEDIATELY click "标注任务" before 250ms debounce
    fireEvent.change(searchInput!, { target: { value: "" } });
    const createBtn = container.querySelector<HTMLButtonElement>("#caseLabelingCreateTask");
    expect(createBtn).not.toBeDisabled();
    fireEvent.click(createBtn!);

    await waitFor(() => {
      expect(showPage).toHaveBeenCalledWith("labeling-new-task", { historyMode: "push" });
    });
    expect(new URLSearchParams(window.location.search).get("q")).toBeNull();
    const lastSynced = syncState.mock.calls.at(-1)?.[0] as
      | { search?: string; data?: { total?: number } }
      | undefined;
    expect(lastSynced?.search).toBe("");
    expect(lastSynced?.data?.total).toBe(1071);
  });

  it("pauses #caseLabelingCreateTask immediately on first 503 during retry:1 window, recovers on retry success, and stays blocked on final failure", async () => {
    const showPage = vi.fn();
    const syncState = vi.fn();
    (window as unknown as Record<string, unknown>).showPage = showPage;
    (window as unknown as Record<string, unknown>).syncCaseLabelingGalleryState = syncState;

    let mode: "initial" | "fail_then_recover" | "always_fail" = "initial";
    let failCountInPhase = 0;
    let releaseRetry: (() => void) | null = null;

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
          if (mode === "initial") {
            return new Response(
              JSON.stringify({
                total: 10,
                page: 1,
                pages: 1,
                page_size: 20,
                items: [{ issue_id: "cn37760285", gt_label: "误触发" }],
              }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            );
          }
          if (mode === "fail_then_recover") {
            failCountInPhase += 1;
            if (failCountInPhase === 1) {
              return new Response(JSON.stringify({ detail: "首次 503" }), {
                status: 503,
                headers: { "Content-Type": "application/json" },
              });
            }
            await new Promise<void>((resolve) => {
              releaseRetry = resolve;
            });
            return new Response(
              JSON.stringify({
                total: 12,
                page: 1,
                pages: 1,
                page_size: 20,
                items: [{ issue_id: "cn37760285", gt_label: "误触发" }],
              }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            );
          }
          return new Response(JSON.stringify({ detail: "持续 503" }), {
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

    const client = new QueryClient({
      defaultOptions: { queries: { retry: 1, retryDelay: 20 } },
    });
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

    // 1. Initial load succeeds with 10
    await waitFor(() => {
      expect(container.querySelector("#caseLabelingCount")?.textContent).toBe("10");
    });
    const createBtn = container.querySelector<HTMLButtonElement>("#caseLabelingCreateTask");
    expect(createBtn).not.toBeDisabled();

    // 2. Refresh receives FIRST 503 while retry #1 is still in flight -> must pause immediately!
    mode = "fail_then_recover";
    failCountInPhase = 0;
    void client.invalidateQueries({ queryKey: ["labeling-gallery-cases"] });

    await waitFor(() => {
      expect(createBtn).toBeDisabled();
    });
    expect(container.querySelector("#caseLabelingCount")?.textContent).toBe("—");
    fireEvent.click(createBtn!);
    expect(showPage).not.toHaveBeenCalled();

    // 3. Release retry #1 -> succeeds with 12 -> button & count recover!
    await waitFor(() => {
      expect(releaseRetry).not.toBeNull();
    });
    releaseRetry!();
    await waitFor(() => {
      expect(container.querySelector("#caseLabelingCount")?.textContent).toBe("12");
      expect(createBtn).not.toBeDisabled();
    });

    // 4. Refresh fails BOTH attempts -> final alert error state, button remains disabled
    mode = "always_fail";
    void client.invalidateQueries({ queryKey: ["labeling-gallery-cases"] });
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(createBtn).toBeDisabled();
    expect(container.querySelector("#caseLabelingCount")?.textContent).toBe("—");
    fireEvent.click(createBtn!);
    expect(showPage).not.toHaveBeenCalled();
  });

  it("aborts and suppresses delayed #caseLabelingCreateTask recount navigation if user leaves the gallery", async () => {
    const showPage = vi.fn();
    (window as unknown as Record<string, unknown>).showPage = showPage;
    window.history.replaceState({}, "", "/manual-s6/case-labeling?baselines=0508&q=cn35635511");

    let resolveDelayedRecount: ((res: Response) => void) | null = null;
    let capturedSignal: AbortSignal | undefined;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/labeling/tasks")) {
          return new Response(JSON.stringify({ items: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("/api/labeling/cases")) {
          const params = new URLSearchParams(url.split("?")[1] || "");
          const q = params.get("q") || "";
          if (q === "cn35635511") {
            return new Response(
              JSON.stringify({ total: 0, page: 1, pages: 1, page_size: 20, items: [] }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            );
          }
          if (params.get("page_size") === "1") {
            capturedSignal = init?.signal ?? undefined;
            return await new Promise<Response>((resolve) => {
              resolveDelayedRecount = resolve;
            });
          }
          return new Response(
            JSON.stringify({ total: 1071, page: 1, pages: 54, page_size: 20, items: [] }),
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
    const { container, rerender } = render(
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
      expect(container.querySelector("#caseLabelingCount")?.textContent).toBe("0");
    });

    // Clear search and click "标注任务" to trigger delayed recount
    const searchInput = container.querySelector<HTMLInputElement>("#caseLabelingSearch");
    fireEvent.change(searchInput!, { target: { value: "" } });
    fireEvent.click(container.querySelector<HTMLButtonElement>("#caseLabelingCreateTask")!);

    await waitFor(() => {
      expect(resolveDelayedRecount).not.toBeNull();
    });

    // User leaves the gallery BEFORE the delayed recount resolves
    rerender(
      <QueryClientProvider client={client}>
        <CaseLabelingGalleryIsland
          active={false}
          lang="zh"
          selectedBaselines={["0508"]}
          isAdmin
          canWrite
        />
      </QueryClientProvider>,
    );

    expect(capturedSignal?.aborted).toBe(true);

    // Resolve the stale delayed response -> must NOT drag user to labeling-new-task!
    resolveDelayedRecount!(
      new Response(JSON.stringify({ total: 1071, page: 1, pages: 54, page_size: 1, items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await new Promise((r) => window.setTimeout(r, 40));
    expect(showPage).not.toHaveBeenCalled();
  });

  it("aborts and discards delayed task recount when user stays on the gallery and edits search to a 0-result filter", async () => {
    const showPage = vi.fn();
    const syncState = vi.fn();
    (window as unknown as Record<string, unknown>).showPage = showPage;
    (window as unknown as Record<string, unknown>).syncCaseLabelingGalleryState = syncState;
    window.history.replaceState({}, "", "/manual-s6/case-labeling?baselines=0508&q=cn35635511");

    let resolveDelayedRecount: ((resp: Response) => void) | null = null;
    let capturedSignal: AbortSignal | undefined;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/labeling/tasks")) {
          return new Response(JSON.stringify({ items: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("/api/labeling/cases")) {
          const params = new URLSearchParams(url.split("?")[1] || "");
          const q = params.get("q") || "";
          if (q === "cn35635511" || q === "no_match_xyz") {
            return new Response(
              JSON.stringify({ total: 0, page: 1, pages: 1, page_size: 20, items: [] }),
              { status: 200, headers: { "Content-Type": "application/json" } },
            );
          }
          if (params.get("page_size") === "1") {
            capturedSignal = init?.signal ?? undefined;
            return await new Promise<Response>((resolve) => {
              resolveDelayedRecount = resolve;
            });
          }
          return new Response(
            JSON.stringify({ total: 1071, page: 1, pages: 54, page_size: 20, items: [] }),
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
      expect(container.querySelector("#caseLabelingCount")?.textContent).toBe("0");
    });

    // Clear search and click "标注任务" to kick off recount for q=""
    const searchInput = container.querySelector<HTMLInputElement>("#caseLabelingSearch")!;
    fireEvent.change(searchInput, { target: { value: "" } });
    fireEvent.click(container.querySelector<HTMLButtonElement>("#caseLabelingCreateTask")!);

    await waitFor(() => {
      expect(resolveDelayedRecount).not.toBeNull();
    });

    // User stays on the SAME page and types a new 0-result query BEFORE recount resolves
    fireEvent.change(searchInput, { target: { value: "no_match_xyz" } });

    await waitFor(() => {
      expect(capturedSignal?.aborted).toBe(true);
    });
    // Gallery & URL update to 0-result search
    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("q")).toBe("no_match_xyz");
      expect(container.querySelector("#caseLabelingCount")?.textContent).toBe("0");
    });

    // Stale 1071 recount finally resolves -> MUST NOT open labeling-new-task!
    resolveDelayedRecount!(
      new Response(JSON.stringify({ total: 1071, page: 1, pages: 54, page_size: 1, items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await new Promise((r) => window.setTimeout(r, 40));
    expect(showPage).not.toHaveBeenCalled();
  });

  it("aborts and discards delayed task recount when dataset changes in-place", async () => {
    const showPage = vi.fn();
    (window as unknown as Record<string, unknown>).showPage = showPage;
    window.history.replaceState({}, "", "/manual-s6/case-labeling?baselines=0508&q=cn35635511");

    let resolveDelayedRecount: ((resp: Response) => void) | null = null;
    let capturedSignal: AbortSignal | undefined;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/labeling/tasks")) {
          return new Response(JSON.stringify({ items: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("/api/labeling/cases")) {
          const params = new URLSearchParams(url.split("?")[1] || "");
          if (params.get("page_size") === "1") {
            capturedSignal = init?.signal ?? undefined;
            return await new Promise<Response>((resolve) => {
              resolveDelayedRecount = resolve;
            });
          }
          return new Response(
            JSON.stringify({ total: 0, page: 1, pages: 1, page_size: 20, items: [] }),
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
    const { container, rerender } = render(
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
      expect(container.querySelector("#caseLabelingCount")?.textContent).toBe("0");
    });

    fireEvent.change(container.querySelector<HTMLInputElement>("#caseLabelingSearch")!, {
      target: { value: "" },
    });
    fireEvent.click(container.querySelector<HTMLButtonElement>("#caseLabelingCreateTask")!);

    await waitFor(() => {
      expect(resolveDelayedRecount).not.toBeNull();
    });

    // Topbar dataset changes in-place while still active on gallery
    rerender(
      <QueryClientProvider client={client}>
        <CaseLabelingGalleryIsland
          active
          lang="zh"
          selectedBaselines={["0821-odd2"]}
          isAdmin
          canWrite
        />
      </QueryClientProvider>,
    );

    expect(capturedSignal?.aborted).toBe(true);
    resolveDelayedRecount!(
      new Response(JSON.stringify({ total: 1071, page: 1, pages: 54, page_size: 1, items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await new Promise((r) => window.setTimeout(r, 40));
    expect(showPage).not.toHaveBeenCalled();
  });
});
