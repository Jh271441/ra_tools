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
});
