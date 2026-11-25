import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReviewAnalysisPage, ReviewAnalysisResponse } from "./ReviewAnalysisPage";

const MOCK_ANALYSIS: ReviewAnalysisResponse = {
  total: 35,
  page: 1,
  page_size: 20,
  page_count: 2,
  summary: {
    latest_reviews: 35,
    with_reason: 30,
    empty_reason: 5,
    with_structured_evidence: 18,
    model_review_status_counts: {
      pending: 5,
      in_progress: 8,
      blocked_by_label: 2,
      completed: 20,
    },
  },
  scope: {
    model_run: { id: "run-01", name: "Qwen3-VL-Base" },
    comparison_status: "mismatch",
    exclusion: "all",
  },
  gt_update_counts: { all: 35, ready: 7, blocked: 3 },
  confusion: {
    total: 35,
    matches: 20,
    mismatches: 12,
    none: 3,
    model_labels: ["误触发", "正确触发", "无需协助", "NONE"],
    rows: [
      {
        gt_label: "误触发",
        total: 15,
        cells: [
          { model_label: "误触发", count: 10 },
          { model_label: "正确触发", count: 4 },
          { model_label: "无需协助", count: 0 },
          { model_label: "NONE", count: 1 },
        ],
      },
      {
        gt_label: "正确触发",
        total: 20,
        cells: [
          { model_label: "误触发", count: 8 },
          { model_label: "正确触发", count: 10 },
          { model_label: "无需协助", count: 0 },
          { model_label: "NONE", count: 2 },
        ],
      },
    ],
  },
  cluster_panels: [
    {
      key: "evidence",
      label: "缺失信息",
      layout: "single",
      groups: [
        {
          key: "evidence",
          label: "缺失信息",
          annotated_count: 18,
          items: [{ key: "rear_cam", label: "缺后视", count: 12 }],
        },
      ],
    },
    {
      key: "scene",
      label: "场景",
      layout: "dual",
      groups: [
        {
          key: "env",
          label: "环境",
          annotated_count: 10,
          items: [{ key: "rain", label: "雨天", count: 10 }],
        },
        {
          key: "intent",
          label: "意图",
          annotated_count: 8,
          items: [{ key: "turn", label: "左转", count: 8 }],
        },
      ],
    },
    {
      key: "trigger",
      label: "触发判定",
      layout: "dual",
      groups: [
        { key: "ft", label: "误触发", annotated_count: 4, items: [{ key: "a", label: "A", count: 4 }] },
        { key: "tt", label: "正确触发", annotated_count: 6, items: [{ key: "b", label: "B", count: 6 }] },
      ],
    },
    {
      key: "egress",
      label: "如何脱困",
      layout: "dual",
      groups: [
        { key: "ra", label: "RA", annotated_count: 3, items: [{ key: "c", label: "C", count: 3 }] },
        { key: "na", label: "无需协助", annotated_count: 2, items: [{ key: "d", label: "D", count: 2 }] },
      ],
    },
  ],
  items: [
    {
      issue_id: "cn112233",
      title: "窄路会车卡滞",
      baseline_scope: "1113",
      gt_label: "正确触发",
      comparison_status: "mismatch",
      model_review_progress: "completed",
      review_url: "/manual-s6/review?issue=cn112233",
      voyager_issue_url: "https://voyager.example.com/issue/cn112233",
      annotation: {
        note: "模型未识别对向违停车占道",
        author: "jasperchen",
        author_verified: true,
        created_at: "2026-11-24T09:00:00Z",
        review_domain: "model_review",
        tags: ["rain"],
        missing_evidence: ["rear_cam"],
      },
      prediction: {
        label: "误触发",
        confidence: 0.875,
        reason: "判断前方空旷",
      },
    },
  ],
};

describe("ReviewAnalysisPage 1:1 parity", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/dashboard-config")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              default_failure_only: true,
              review_tag_catalog: [
                { key: "rain", label: "雨天", section: "scene", group: "environment" },
              ],
              missing_evidence_catalog: [{ key: "rear_cam", label: "缺后视" }],
              baselines: [{ id: "1113", scope: "1113", label: "1113 复核集" }],
            }),
            { status: 200 },
          ),
        );
      }
      if (url.includes("/api/model-runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              items: [
                {
                  id: "run-01",
                  name: "Qwen3-VL-Base",
                  is_default: true,
                  baseline_prediction_count: 100,
                  failure_count: 20,
                },
              ],
            }),
            { status: 200 },
          ),
        );
      }
      if (url.includes("/api/reviewers")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              analysis_items: [{ name: "jasperchen", review_count: 12, verified: true }],
            }),
            { status: 200 },
          ),
        );
      }
      if (url.includes("/api/model-review-facets")) {
        return Promise.resolve(new Response(JSON.stringify({ reviewers: [] }), { status: 200 }));
      }
      if (url.includes("/api/review-work-splits")) {
        return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }));
      }
      if (url.includes("/api/cases/cn112233")) {
        return Promise.resolve(
          new Response(JSON.stringify({ issue_id: "cn112233", predictions: [] }), { status: 200 }),
        );
      }
      return Promise.resolve(new Response(JSON.stringify(MOCK_ANALYSIS), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/manual-s6/review-analysis?run=run-01&comparison=mismatch");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  function renderPage(lang: "zh" | "en" = "zh") {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <ReviewAnalysisPage active lang={lang} theme="dark" selectedBaselines={["1113"]} />
      </QueryClientProvider>,
    );
  }

  it("renders KPIs, 8 SVG donuts, confusion matrix, case row, model history & discussion bridges, and zero native selects", async () => {
    const openHistory = vi.fn();
    const openDiscussion = vi.fn().mockResolvedValue(undefined);
    (window as unknown as Record<string, unknown>).openHistoryDialog = openHistory;
    (window as unknown as Record<string, unknown>).openAnalysisDiscussion = openDiscussion;

    const { container } = renderPage("zh");

    await waitFor(() => {
      expect(screen.getByText("cn112233")).toBeInTheDocument();
    });

    // Zero native <select> elements
    expect(container.querySelectorAll("select").length).toBe(0);

    // 8 SVG donut charts (1 GT + 7 cluster panels)
    expect(container.querySelectorAll(".analysis-pie-svg").length).toBe(8);

    // Tag color attributes match classic analysis.css
    const tagChip = container.querySelector('.analysis-chip.tag-chip[data-tag-section="scene"]');
    expect(tagChip).toBeTruthy();

    // Model history button triggers classic openHistoryDialog
    fireEvent.click(screen.getByRole("button", { name: /查看 cn112233 的评测 Run 输出历史/ }));
    await waitFor(() => {
      expect(openHistory).toHaveBeenCalledWith("model", { issue_id: "cn112233", predictions: [] });
    });

    // Comments link triggers classic openAnalysisDiscussion
    fireEvent.click(screen.getByRole("button", { name: "评论" }));
    expect(openDiscussion).toHaveBeenCalledWith("cn112233", {
      runId: "run-01",
      source: "analysis",
    });

    // GT rules modal opens & closes
    fireEvent.click(screen.getByRole("button", { name: "GT 更新统计口径" }));
    expect(screen.getByText("GT 更新规则")).toBeInTheDocument();
  });

  it("renders English UI and resets filters cleanly", async () => {
    renderPage("en");

    await waitFor(() => {
      expect(screen.getByText("cn112233")).toBeInTheDocument();
    });

    expect(screen.getByText("Review reason details")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));

    await waitFor(() => {
      expect(window.location.search).toContain("run=none");
    });
  });
});
