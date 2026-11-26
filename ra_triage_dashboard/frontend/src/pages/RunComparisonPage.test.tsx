import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RunComparisonPage } from "./RunComparisonPage";

const MOCK_RUNS = [
  {
    id: "run-cand",
    name: "Candidate V2",
    source_name: "cand_v2.json",
    created_at: "2026-11-25T10:00:00Z",
    baseline_prediction_count: 10,
  },
  {
    id: "run-base",
    name: "Baseline V1",
    source_name: "base_v1.json",
    created_at: "2026-11-24T10:00:00Z",
    baseline_prediction_count: 10,
  },
];

function makeComparisonPayload(overrides: Record<string, unknown> = {}) {
  return {
    view_mode: "pairwise",
    baseline_run: {
      id: "run-base",
      name: "Baseline V1",
      prompt: {
        source_type: "run_template",
        sha256: "aaaa111122223333",
        template: "System prompt line 1\nOld rule A",
      },
      input: { available: true, config: { frames: 4, model: "v1" } },
    },
    candidate_run: {
      id: "run-cand",
      name: "Candidate V2",
      prompt: {
        source_type: "run_template",
        sha256: "bbbb444455556666",
        template: "System prompt line 1\nNew rule B",
      },
      input: { available: true, config: { frames: 6, model: "v2" } },
    },
    summary: {
      baseline: {
        accuracy: 0.7,
        correct_count: 7,
        total_count: 10,
        prediction_count: 10,
        columns: ["误触发", "正确触发", "无需协助"],
        rows: [
          {
            gt_label: "误触发",
            cells: { 误触发: 4, 正确触发: 1, 无需协助: 0 },
            total: 5,
            accuracy: 0.8,
          },
          {
            gt_label: "正确触发",
            cells: { 误触发: 2, 正确触发: 3, 无需协助: 0 },
            total: 5,
            accuracy: 0.6,
          },
        ],
      },
      candidate: {
        accuracy: 0.8,
        correct_count: 8,
        total_count: 10,
        prediction_count: 10,
        columns: ["误触发", "正确触发", "无需协助"],
        rows: [
          {
            gt_label: "误触发",
            cells: { 误触发: 4, 正确触发: 1, 无需协助: 0 },
            total: 5,
            accuracy: 0.8,
          },
          {
            gt_label: "正确触发",
            cells: { 误触发: 1, 正确触发: 4, 无需协助: 0 },
            total: 5,
            accuracy: 0.8,
          },
        ],
      },
      accuracy_delta: 0.1,
      label_changed_count: 2,
      total_count: 10,
      transition_counts: { P2F: 1, F2P: 2, F2F: 2, P2P: 5 },
    },
    page: 1,
    page_count: 1,
    total: 2,
    items: [
      {
        issue_id: "cn-case-1",
        gt_label: "误触发",
        baseline_scope: "version-20261106",
        transition: "P2F",
        baseline: {
          model_label: "误触发",
          model_confidence: 0.91,
          model_reason: "Baseline predicted false trigger",
          correct: true,
        },
        candidate: {
          model_label: "正确触发",
          model_confidence: 0.82,
          model_reason: "Candidate predicted true trigger",
          correct: false,
        },
        extra_inputs: {
          baseline: {
            available: true,
            axes: { routing: { label: "左转", status: "available" } },
          },
          candidate: {
            available: true,
            axes: { routing: { label: "左转", status: "available" } },
          },
        },
        scene_review: { tags: ["排队"], source: "candidate", author: "jasperchen" },
      },
      {
        issue_id: "cn-case-2",
        gt_label: "正确触发",
        baseline_scope: "version-20261106",
        transition: "F2P",
        baseline: {
          model_label: "误触发",
          model_confidence: 0.61,
          model_reason: "Baseline missed stuck vehicle",
          correct: false,
        },
        candidate: {
          model_label: "正确触发",
          model_confidence: 0.94,
          model_reason: "Candidate caught stuck vehicle",
          correct: true,
        },
      },
    ],
    ...overrides,
  };
}

function makeCaseInputsPayload(issueId: string) {
  return {
    issue_id: issueId,
    scene_review: { tags: ["排队"], source: "candidate", author: "jasperchen" },
    baseline: {
      prompt: {
        source_type: "actual_input",
        sha256: "1111222233334444",
        text: `Prompt for ${issueId}\nRule old`,
      },
      input: { available: true, config: { version: "v1" } },
      media: { available: true, notice: "4 frames", count: 4, items: [] },
      run_reference: {
        prompt: { source_type: "run_template", template: "Ref base" },
        input: { available: false },
      },
    },
    candidate: {
      prompt: {
        source_type: "actual_input",
        sha256: "5555666677778888",
        text: `Prompt for ${issueId}\nRule new`,
      },
      input: { available: true, config: { version: "v2" } },
      media: { available: true, notice: "6 frames", count: 6, items: [] },
      run_reference: {
        prompt: { source_type: "run_template", template: "Ref cand" },
        input: { available: false },
      },
    },
  };
}

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return {
    client,
    ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>),
  };
}

describe("RunComparisonPage", () => {
  beforeEach(() => {
    if (!HTMLDialogElement.prototype.showModal) {
      HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
        this.setAttribute("open", "");
      };
    }
    if (!HTMLDialogElement.prototype.close) {
      HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
        this.removeAttribute("open");
        this.dispatchEvent(new Event("close"));
      };
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState({}, "", "/");
  });

  it("serves current page rows to the media dialog without a legacy state global", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input), window.location.origin);
      if (url.pathname.endsWith("/api/model-runs")) {
        return Response.json({ items: MOCK_RUNS });
      }
      if (url.pathname.endsWith("/api/model-run-comparison")) {
        const page = Number(url.searchParams.get("page"));
        return Response.json(makeComparisonPayload({
          page,
          page_count: 2,
          total: 3,
          ...(page === 2 ? { items: [{ issue_id: "cn-case-3" }] } : {}),
        }));
      }
      return Response.json({});
    });
    const getBridge = () => (window as unknown as {
      __RA_COMPARISON_BRIDGE__?: {
        getPageForMedia: () => { page: number; items: { issue_id: string }[] } | null;
        stepPageForMedia: (page: number) => Promise<{ issue_id: string }[]>;
      };
    }).__RA_COMPARISON_BRIDGE__;

    renderWithClient(<RunComparisonPage active lang="zh" selectedBaselines={["version-20261106"]} />);
    expect(await screen.findByText("cn-case-2")).toBeInTheDocument();
    expect(getBridge()?.getPageForMedia()?.items.map((item) => item.issue_id))
      .toEqual(["cn-case-1", "cn-case-2"]);

    await act(async () => {
      expect(await getBridge()?.stepPageForMedia(2)).toEqual([{ issue_id: "cn-case-3" }]);
    });
    expect(await screen.findByText("cn-case-3")).toBeInTheDocument();
    expect(getBridge()?.getPageForMedia()?.page).toBe(2);
    expect(new URLSearchParams(window.location.search).get("page")).toBe("2");
    expect(fetchSpy.mock.calls.some(([input]) => {
      const url = new URL(String(input), window.location.origin);
      return url.pathname.endsWith("/api/model-run-comparison")
        && url.searchParams.get("page") === "2"
        && url.searchParams.get("baselines") === "version-20261106";
    })).toBe(true);
  });

  it("renders pairwise KPIs, matrices, case rows with 0 native selects, and supports transition, extra-input, and swap filters", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/model-runs")) {
        return new Response(JSON.stringify({ items: MOCK_RUNS }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/api/model-run-comparison?")) {
        return new Response(JSON.stringify(makeComparisonPayload()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    const { container } = renderWithClient(
      <RunComparisonPage active lang="zh" selectedBaselines={["version-20261106"]} />,
    );

    expect(await screen.findByText("cn-case-1")).toBeInTheDocument();
    expect(screen.getByText("cn-case-2")).toBeInTheDocument();
    expect(screen.getByText("+10.0 pp")).toBeInTheDocument();
    expect(screen.getByText("基线混淆矩阵")).toBeInTheDocument();
    expect(screen.getByText("新 Run 混淆矩阵")).toBeInTheDocument();
    expect(container.querySelectorAll("select").length).toBe(0);

    // Transition filter pill updates request query
    fireEvent.click(screen.getByRole("button", { name: /P2F 退化 1/ }));
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining("transition=P2F"),
        expect.any(Object),
      );
    });

    // Extra inputs popover open -> select checkbox -> apply -> closes
    const extraBtn = screen.getByRole("button", { name: /额外输入/ });
    fireEvent.click(extraBtn);
    expect(screen.getByText("筛选 Run")).toBeInTheDocument();
    expect(container.querySelectorAll("select").length).toBe(0);
    fireEvent.click(screen.getByLabelText("左转"));
    fireEvent.click(screen.getByRole("button", { name: "应用" }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining("input_filter="),
        expect.any(Object),
      );
      expect(screen.queryByText("筛选 Run")).not.toBeInTheDocument();
    });

    // Swap runs button reverses baseline_run_id and candidate_run_id
    fireEvent.click(screen.getByRole("button", { name: "交换两个 Run" }));
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringMatching(/baseline_run_id=run-cand.*candidate_run_id=run-base/),
        expect.any(Object),
      );
    });
  });

  it("opens native Case Compare dialog, renders LCS diff across tabs, steps with ArrowDown, and supports English mode", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/model-runs")) {
        return new Response(JSON.stringify({ items: MOCK_RUNS }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/api/model-run-comparison/cases/")) {
        const match = url.match(/cases\/([^/]+)\/inputs/);
        const issueId = match ? decodeURIComponent(match[1]!) : "cn-case-1";
        return new Response(JSON.stringify(makeCaseInputsPayload(issueId)), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/api/model-run-comparison?")) {
        return new Response(JSON.stringify(makeComparisonPayload()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ assets: { frames: [] }, camera: { frames: [] } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    const { container, rerender, client } = renderWithClient(
      <RunComparisonPage active lang="zh" selectedBaselines={["version-20261106"]} />,
    );

    expect(await screen.findByText("cn-case-1")).toBeInTheDocument();
    const row = container.querySelector<HTMLTableRowElement>('tr[data-issue-id="cn-case-1"]')!;
    fireEvent.click(row);

    const dialog = document.querySelector<HTMLDialogElement>("#raComparisonReasonDialog")!;
    expect(dialog.open).toBe(true);
    expect(screen.getByText("cn-case-1 · Case 对比")).toBeInTheDocument();
    expect(await screen.findByText("Prompt 对比")).toBeInTheDocument();
    // Inline diff highlight renders <mark> for old vs new
    expect(dialog.querySelectorAll("mark").length).toBeGreaterThan(0);

    // Switch to Input config tab
    fireEvent.click(screen.getByRole("tab", { name: "输入配置" }));
    expect(screen.getByText(/逐 Case 配置/)).toBeInTheDocument();
    expect(document.querySelector("#raComparisonCaseEvidence")).toBeNull();

    // ArrowDown steps to second case
    fireEvent.keyDown(document, { key: "ArrowDown" });
    expect(await screen.findByText("cn-case-2 · Case 对比")).toBeInTheDocument();

    // Language switch to EN
    rerender(
      <QueryClientProvider client={client}>
        <RunComparisonPage active lang="en" selectedBaselines={["version-20261106"]} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Baseline Run")).toBeInTheDocument();
    expect(screen.getByText("Candidate Run")).toBeInTheDocument();
    expect(screen.getByText("cn-case-2 · Case comparison")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Input config" })).toBeInTheDocument();
  });
});
