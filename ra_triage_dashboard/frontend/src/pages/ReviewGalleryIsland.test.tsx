import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReviewGalleryIsland } from "./ReviewGalleryIsland";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("ReviewGalleryIsland", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/manual-s6/review");
    (window as unknown as Record<string, unknown>).selectCase = vi.fn().mockResolvedValue(undefined);
    (window as unknown as Record<string, unknown>).syncReviewGalleryState = vi.fn();
    (window as unknown as Record<string, unknown>).state = {
      config: {
        baselines: [{ id: "0508", label: "0508", count: 1071 }],
        default_model_run_id: "run-1",
        review_tag_catalog: [
          { key: "queue", label: "排队", group: "false_trigger", section: "interaction_decision" },
        ],
        missing_evidence_catalog: [{ key: "bev_blur", label: "BEV 模糊" }],
        batch_prediction: { enabled: true, max_issues: 50 },
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/model-runs")) {
          return new Response(
            JSON.stringify({
              default_model_run_id: "run-1",
              items: [
                {
                  id: "run-1",
                  name: "1106 联合复核",
                  is_default: true,
                  baseline_prediction_count: 465,
                  failure_count: 172,
                },
              ],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.includes("/api/review-work-splits")) {
          return new Response(JSON.stringify({ items: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("/api/reviewers")) {
          return new Response(
            JSON.stringify({ items: [{ name: "jasperchen", verified: true, review_count: 12 }] }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.includes("/api/model-review-facets")) {
          return new Response(JSON.stringify({ reviewers: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("/api/work-assignees")) {
          return new Response(
            JSON.stringify({ items: [{ username: "jasperchen", issue_count: 5 }] }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.includes("/api/cases")) {
          return new Response(
            JSON.stringify({
              total: 1,
              page: 1,
              page_size: 20,
              items: [
                {
                  issue_id: "cn38048091",
                  gt_label: "误触发",
                  prediction: {
                    label: "正确触发",
                    model_run_id: "run-1",
                    mismatch: true,
                  },
                  annotation: {
                    id: 99,
                    model_run_id: "run-1",
                    model_review_status: "completed",
                    author: "jasperchen",
                    author_verified: true,
                    missing_evidence: ["bev_blur"],
                  },
                  label_state: {
                    state: "resolved",
                    expected_output: "误触发",
                    gt_relation: "matches_gt",
                  },
                  thumbnail: { url: "/api/cases/cn38048091/thumbnail", label: "BEV 关键帧" },
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

  it("opens chart results as cards and clears the scope with the gallery reset", async () => {
    window.history.replaceState({}, "", "/manual-s6/review?baselines=0508&run=run-1&comparison=all&analysis_scope=chart_review%3Dcompleted");
    renderWithQuery(<ReviewGalleryIsland active lang="zh" selectedBaselines={["0508"]} isAdmin canWrite identityPending={false} />);
    await screen.findByText("cn38048091");
    const caseRequests = () => vi.mocked(fetch).mock.calls
      .map(([input]) => new URL(String(input), window.location.origin))
      .filter(url => url.pathname.endsWith("/api/cases"));
    const initialRequests = caseRequests();
    expect(initialRequests.at(-1)?.searchParams.get("analysis_scope")).toBe("chart_review=completed");
    expect(screen.queryByRole("button", { name: "清除图表筛选" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重置" }));
    expect(new URLSearchParams(window.location.search).has("analysis_scope")).toBe(false);
    await waitFor(() => {
      const resetRequest = caseRequests().slice(initialRequests.length).at(-1);
      expect(resetRequest?.searchParams.get("model_run_id")).toBe("run-1");
      expect(resetRequest?.searchParams.has("analysis_scope")).toBe(false);
    });
  });

  it("renders filters, issue cards, zero native selects, and delegates card open to classic detail", async () => {
    const { container } = renderWithQuery(
      <ReviewGalleryIsland
        active
        lang="zh"
        selectedBaselines={["0508"]}
        isAdmin
        canWrite
        identityPending={false}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("cn38048091")).toBeInTheDocument();
    });

    expect(container.querySelectorAll("select").length).toBe(0);
    expect(screen.getByText("MISMATCH")).toBeInTheDocument();
    expect(screen.getByText("与 GT 一致")).toBeInTheDocument();
    expect(screen.getByText("当前 1–1 / 共 1 条")).toBeInTheDocument();

    const openBtn = container.querySelector<HTMLButtonElement>('[data-open-issue="cn38048091"]');
    expect(openBtn).not.toBeNull();
    fireEvent.click(openBtn!);
    expect((window as unknown as { selectCase: ReturnType<typeof vi.fn> }).selectCase).toHaveBeenCalledWith(
      "cn38048091",
    );
  });

  it("writes search query ?q= into URL, renders group jump navigation for Issue tags, and shows explicit error state on HTTP 503", async () => {
    (window as unknown as Record<string, unknown>).state = {
      config: {
        baselines: [{ id: "0508", label: "0508", count: 1071 }],
        default_model_run_id: "run-1",
        review_tag_catalog: [
          { key: "night", label: "夜晚", group: "environment", section: "scene" },
          { key: "queue", label: "排队", group: "false_trigger", section: "interaction_decision" },
        ],
        missing_evidence_catalog: [{ key: "bev_blur", label: "BEV 模糊" }],
        batch_prediction: { enabled: true, max_issues: 50 },
      },
    };

    const { container } = renderWithQuery(
      <ReviewGalleryIsland
        active
        lang="zh"
        selectedBaselines={["0508"]}
        isAdmin
        canWrite
        identityPending={false}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("cn38048091")).toBeInTheDocument();
    });

    // 1. Typing search writes ?q= into window.location.search after debounce
    const searchInput = container.querySelector<HTMLInputElement>("#searchInput");
    expect(searchInput).not.toBeNull();
    fireEvent.change(searchInput!, { target: { value: "cn38048091" } });
    await waitFor(
      () => {
        expect(new URLSearchParams(window.location.search).get("q")).toBe("cn38048091");
      },
      { timeout: 1500 },
    );

    // 2. Opening Issue tag filter shows group jump navigation buttons matching 8785
    const tagTrigger = container.querySelector<HTMLButtonElement>("#reviewIssueTagFilter");
    expect(tagTrigger).not.toBeNull();
    fireEvent.click(tagTrigger!);
    const jumpButtons = container.querySelectorAll<HTMLButtonElement>(
      "#reviewIssueTagFilter-panel [data-multi-group-jump]",
    );
    expect(jumpButtons.length).toBeGreaterThanOrEqual(2);
    expect(
      container.querySelector("#reviewIssueTagFilter-panel .multi-filter-group-nav"),
    ).not.toBeNull();
  });

  it("renders explicit error state instead of zero-results when /api/cases returns HTTP 503", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/model-runs")) {
          return new Response(
            JSON.stringify({
              default_model_run_id: "run-1",
              items: [{ id: "run-1", name: "Run 1", is_default: true, baseline_prediction_count: 10 }],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.includes("/api/cases?")) {
          return new Response(JSON.stringify({ detail: "后端暂不可用 (503)" }), {
            status: 503,
            headers: { "Content-Type": "application/json" },
          });
        }
        return new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    const { container } = renderWithQuery(
      <ReviewGalleryIsland
        active
        lang="zh"
        selectedBaselines={["0508"]}
        isAdmin
        canWrite
        identityPending={false}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getAllByText("Issue 列表读取失败").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("当前没有匹配的 Issue")).not.toBeInTheDocument();
    expect(container.querySelector("#caseCount")?.textContent).toBe("—");
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });

  it("disables allocation and clears cached count when a subsequent refresh returns HTTP 503", async () => {
    const syncState = vi.fn();
    (window as unknown as Record<string, unknown>).syncReviewGalleryState = syncState;
    let failCases = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/model-runs")) {
          return new Response(
            JSON.stringify({
              default_model_run_id: "run-1",
              items: [{ id: "run-1", name: "Run 1", is_default: true, baseline_prediction_count: 10 }],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.includes("/api/cases?")) {
          if (failCases) {
            return new Response(JSON.stringify({ detail: "刷新失败 (503)" }), {
              status: 503,
              headers: { "Content-Type": "application/json" },
            });
          }
          return new Response(
            JSON.stringify({
              total: 5,
              page: 1,
              page_size: 20,
              items: [{ issue_id: "cn38048091", gt_label: "误触发" }],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response(JSON.stringify({ items: [], reviewers: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <ReviewGalleryIsland
          active
          lang="zh"
          selectedBaselines={["0508"]}
          isAdmin
          canWrite
          identityPending={false}
        />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(container.querySelector("#caseCount")?.textContent).toBe("5");
    });
    const splitBtn = container.querySelector<HTMLButtonElement>("#splitFilteredButton");
    expect(splitBtn).not.toBeDisabled();

    failCases = true;
    await client.invalidateQueries({ queryKey: ["review-gallery-cases"] });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(container.querySelector("#caseCount")?.textContent).toBe("—");
    expect(splitBtn).toBeDisabled();
    const lastSynced = syncState.mock.calls.at(-1)?.[0] as { caseTotal?: number } | undefined;
    expect(lastSynced?.caseTotal).toBe(0);
  });
});
