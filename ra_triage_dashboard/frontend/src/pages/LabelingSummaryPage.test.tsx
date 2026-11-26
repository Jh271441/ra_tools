import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LabelingSummaryPage, LabelingSummaryResponse } from "./LabelingSummaryPage";

const MOCK_SUMMARY: LabelingSummaryResponse = {
  total: 120,
  annotated: 48,
  reason_count: 42,
  empty_reason_count: 6,
  adjudicated_count: 5,
  page: 1,
  page_size: 20,
  page_count: 3,
  labelers: ["jasperchen", "liangxianghui"],
  assignees: ["jasperchen"],
  submitted_states: { resolved: 40, pending: 5, conflict: 3 },
  gt_update_counts: { all: 48, ready: 12, blocked: 3 },
  pairs: [
    { gt: "误触发", label: "误触发", count: 20 },
    { gt: "误触发", label: "正确触发", count: 2 },
    { gt: "正确触发", label: "正确触发", count: 15 },
    { gt: "无需协助", label: "无需协助", count: 3 },
  ],
  tags: {
    rain: 12,
    lane_change: 9,
    ghost_brake: 7,
    real_block: 6,
    ra_guide: 5,
    self_clear: 4,
  },
  items: [
    {
      issue_id: "cn998877",
      title: "路口施工绕行",
      label_state: "resolved",
      expected_output: "正确触发",
      gt_label: "误触发",
      rationales: ["实景确认前方施工完全封路"],
      tags: ["rain", "real_block"],
      evidence_gaps: ["missing_rear"],
      source_count: 2,
      created_at: "2026-11-24T08:00:00Z",
      adjudication: { kind: "issue" },
      original_conflict: true,
      original_votes: [
        { author: "alice", expected_output: "误触发", rationale: "远看可绕行" },
        { author: "bob", expected_output: "正确触发", rationale: "无路可走" },
      ],
      expected_output_source: {
        kind: "issue_adjudication",
        decision_id: 77,
        authors: ["jasperchen"],
      },
    },
  ],
};

const MOCK_CONFIG = {
  review_tag_catalog: [
    { key: "rain", label: "雨天", section: "scene", group: "environment", hint: "雨雾天气" },
    { key: "lane_change", label: "变道", section: "scene", group: "self_intent" },
    { key: "ghost_brake", label: "误判障碍", section: "interaction_decision", group: "false_trigger" },
    { key: "real_block", label: "施工封路", section: "interaction_decision", group: "true_trigger" },
    { key: "ra_guide", label: "远程绕行", section: "egress", group: "ra" },
    { key: "self_clear", label: "自主脱困", section: "egress", group: "no_assist" },
  ],
  missing_evidence_catalog: [{ key: "missing_rear", label: "缺后视相机" }],
};

describe("LabelingSummaryPage 1:1 parity", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/dashboard-config")) {
        return Promise.resolve(new Response(JSON.stringify(MOCK_CONFIG), { status: 200 }));
      }
      if (url.includes("/api/labeling/tasks")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({ items: [{ id: "campaign-1", name: "11月标注任务" }] }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response(JSON.stringify(MOCK_SUMMARY), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/manual-s6/labeling-summary");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  function renderPage(lang: "zh" | "en" = "zh", isAdmin = true) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <LabelingSummaryPage
          active
          lang={lang}
          theme="dark"
          selectedBaselines={["1113"]}
          isAdmin={isAdmin}
        />
      </QueryClientProvider>,
    );
  }

  it("renders KPIs, 7 SVG donuts, confusion matrix, case rationale, rules modals, and zero native selects", async () => {
    const { container } = renderPage("zh", true);

    await waitFor(() => {
      expect(screen.getByText("cn998877")).toBeInTheDocument();
    });

    // Zero native <select> elements
    expect(container.querySelectorAll("select").length).toBe(0);

    // 7 SVG donut charts (1 GT + 1 env + 1 intent + 2 trigger + 2 egress)
    expect(container.querySelectorAll(".analysis-pie-svg").length).toBe(7);

    // Classic label badge class uses Chinese taxonomy slug
    const badge = container.querySelector(".label-badge.label-正确触发");
    expect(badge).toBeTruthy();

    // Adjudicated KPI toggle updates cluster=adjudicated query
    const adjBtn = screen.getByRole("button", { name: /已裁决 Case/i });
    expect(adjBtn).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(adjBtn);
    await waitFor(() => {
      expect(adjBtn).toHaveAttribute("aria-pressed", "true");
      expect(window.location.search).toContain("cluster=adjudicated");
    });

    // Rules modal opens for Expected result rules and GT update rules
    fireEvent.click(screen.getByRole("button", { name: /期望输出规则/i }));
    expect(screen.getByText("三个案例，一眼看懂")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "知道了" }));

    fireEvent.click(screen.getByRole("button", { name: "GT 更新统计口径" }));
    expect(screen.getByText("GT 更新规则")).toBeInTheDocument();
  });

  it("supports Multi-Issue modal parsing and English bilingual rendering", async () => {
    renderPage("en", false);

    await waitFor(() => {
      expect(screen.getByText("cn998877")).toBeInTheDocument();
    });

    // Export button disabled for non-admin
    expect(screen.getByRole("button", { name: "Export GT updates" })).toBeDisabled();

    // Open Multi-Issue modal and apply IDs
    fireEvent.click(screen.getByRole("button", { name: "Issue list" }));
    const textarea = screen.getByLabelText("Multi-Issue input");
    fireEvent.change(textarea, { target: { value: "cn10001, cn10002 cn10001" } });
    expect(screen.getByText(/2 Issues recognized/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));

    await waitFor(() => {
      expect(window.location.search).toContain("issue_ids=cn10001%2Ccn10002");
    });
  });

  it("reads, displays, queries, and resets target_group=sample without expanding scope", async () => {
    window.history.replaceState(
      {},
      "",
      "/manual-s6/labeling-summary?baselines=version-20261106&target_group=sample",
    );
    const summaryUrls: string[] = [];
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/dashboard-config")) {
        return Promise.resolve(new Response(JSON.stringify(MOCK_CONFIG), { status: 200 }));
      }
      if (url.includes("/api/labeling/tasks")) {
        return Promise.resolve(new Response(JSON.stringify({ items: [] }), { status: 200 }));
      }
      if (url.includes("/api/labeling/summary?")) {
        summaryUrls.push(url);
        const params = new URLSearchParams(url.split("?")[1] || "");
        const total = params.get("target_group") === "sample" ? 117 : 465;
        return Promise.resolve(
          new Response(JSON.stringify({ ...MOCK_SUMMARY, total }), { status: 200 }),
        );
      }
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
    });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={qc}>
        <LabelingSummaryPage
          active
          lang="zh"
          theme="dark"
          selectedBaselines={["version-20261106"]}
          isAdmin
        />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(summaryUrls.length).toBeGreaterThan(0);
    });
    expect(
      new URLSearchParams(summaryUrls[0].split("?")[1] || "").get("target_group"),
    ).toBe("sample");
    expect(new URLSearchParams(window.location.search).get("target_group")).toBe("sample");
    expect(container.querySelector("#labelSummaryTargetGroupPicker")?.textContent).toContain("抽样集");
    await waitFor(() => {
      expect(screen.getByText(/当前范围 117 个 Case/)).toBeInTheDocument();
    });

    // Reset clears target_group from URL and re-queries full cohort
    fireEvent.click(container.querySelector("#labelSummaryReset")!);
    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("target_group")).toBeNull();
    });
  });
});
