import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  VersionMetricsPage,
  VersionMetricsPayload,
  VM_SCHEMES,
  vmChartGeometry,
  vmFreshnessSummary,
  vmPercentageScale,
  vmPointLabels,
  vmVersionPage,
} from "./VersionMetricsPage";

function buildPayload(): VersionMetricsPayload {
  const makeMetrics = (acc: number, correct: number, total: number, human = 12) => ({
    accuracy: acc,
    macro_f1: acc - 0.02,
    correct,
    total,
    reference_total: 155,
    human_count: human,
    per_class: [
      { label: "正确触发", tp: 40, support: 45, recall: 40 / 45 },
      { label: "误触发", tp: 70, support: 75, recall: 70 / 75 },
      { label: "无需协助", tp: 22, support: 35, recall: 22 / 35 },
    ],
  });
  return {
    catalog: [{ family: "20261016" }, { family: "20261030" }],
    selected: ["20261016", "20261030"],
    refresh: { status: "idle", completed: 2, total: 2 },
    items: [
      {
        family: "20261016",
        status: "ready",
        started_at: "2026-11-16T01:55:00Z",
        observed_at: "2026-11-16T02:00:00Z",
        valid_total: 155,
        sample_total: 160,
        published_total: 1600,
        membership_changed: true,
        coverage: {
          te: { filled: 157, total: 158, observed: 158 },
          rd: { filled: 0, total: 158, observed: 0 },
        },
        metrics: {
          model: makeMetrics(132 / 153, 132, 153, 0),
          chain: makeMetrics(134 / 155, 134, 155, 0),
          model_human_sim: makeMetrics(145 / 155, 145, 155, 25),
          chain_human_sim: makeMetrics(148 / 155, 148, 155, 22),
          chain_post_human_sim: makeMetrics(150 / 155, 150, 155, 18),
        },
        thresholds: [
          {
            threshold: 0.9,
            full_low: 180,
            full_total: 1600,
            reduction: "0%",
            human_count: 18,
            total: 155,
            accuracy: 150 / 155,
            correct: 150,
          },
          {
            threshold: 0.85,
            full_low: 140,
            full_total: 1600,
            reduction: "-22.2%",
            human_count: 14,
            total: 155,
            accuracy: 148 / 155,
            correct: 148,
          },
        ],
      },
      {
        family: "20261030",
        status: "ready",
        started_at: "2026-11-16T02:55:00Z",
        observed_at: "2026-11-16T03:00:00Z",
        valid_total: 150,
        sample_total: 155,
        published_total: 1550,
        coverage: {
          te: { filled: 152, total: 155, observed: 155 },
          rd: { filled: 140, total: 155, observed: 155 },
        },
        metrics: {
          model: makeMetrics(130 / 150, 130, 150, 0),
          chain: makeMetrics(136 / 150, 136, 150, 0),
          model_human_sim: makeMetrics(142 / 150, 142, 150, 20),
          chain_human_sim: makeMetrics(144 / 150, 144, 150, 18),
          chain_post_human_sim: makeMetrics(146 / 150, 146, 150, 15),
        },
        thresholds: [
          {
            threshold: 0.9,
            full_low: 150,
            full_total: 1550,
            reduction: "0%",
            human_count: 15,
            total: 150,
            accuracy: 146 / 150,
            correct: 146,
          },
        ],
      },
    ],
  };
}

function renderMetrics(props: { lang?: "zh" | "en"; canWrite?: boolean } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <VersionMetricsPage active lang={props.lang || "zh"} canWrite={props.canWrite ?? true} />
    </QueryClientProvider>,
  );
}

describe("VersionMetricsPage pure chart/report helpers", () => {
  it("computes /sim 4-interval percentage scale and lifts close point labels", () => {
    const closeRow = {
      family: "20261030",
      status: "ready",
      valid_total: 100,
      sample_total: 100,
      metrics: Object.fromEntries(
        VM_SCHEMES.map((key, idx) => [
          key,
          {
            accuracy: 0.999 + idx * 0.0002,
            correct: 100,
            total: 100,
            reference_total: 100,
            human_count: 0,
            per_class: [],
          },
        ]),
      ),
    };
    const geom = vmChartGeometry([closeRow], VM_SCHEMES, "accuracy", 320);
    const labels = vmPointLabels(closeRow, VM_SCHEMES, "accuracy", geom.y);
    expect(labels).toHaveLength(5);
    labels.forEach((lbl, idx) => {
      expect(lbl.y).toBeGreaterThanOrEqual(14);
      if (idx > 0) expect(labels[idx - 1].y - lbl.y).toBeGreaterThanOrEqual(18);
    });

    const scale = vmPercentageScale(
      [
        {
          family: "1",
          status: "ready",
          valid_total: 1,
          sample_total: 1,
          metrics: {
            model: { accuracy: 0.7611, correct: 1, total: 1, reference_total: 1, human_count: 0, per_class: [] },
            chain: { accuracy: 0.9767, correct: 1, total: 1, reference_total: 1, human_count: 0, per_class: [] },
          },
        },
        {
          family: "2",
          status: "ready",
          valid_total: 1,
          sample_total: 1,
          metrics: {
            model: { accuracy: 0.8627, correct: 1, total: 1, reference_total: 1, human_count: 0, per_class: [] },
            chain: { accuracy: 0.9742, correct: 1, total: 1, reference_total: 1, human_count: 0, per_class: [] },
          },
        },
      ],
      ["model", "chain"],
      "accuracy",
    );
    expect(scale).toEqual({ domain: [76, 100], ticks: [76, 82, 88, 94, 100] });
  });

  it("paginates descending and summarizes oldest/newest CST freshness", () => {
    const rows = Array.from({ length: 25 }, (_, i) => ({
      family: `202601${String(i + 1).padStart(2, "0")}`,
      status: "ready",
      valid_total: 10,
      sample_total: 10,
    }));
    const page = vmVersionPage(rows, 99, 10);
    expect(page.page).toBe(3);
    expect(page.pages).toBe(3);
    expect(page.items[0].family).toBe("20260105");

    const freshness = vmFreshnessSummary(
      [
        { family: "1", status: "ready", observed_at: "2026-11-16T03:00:00Z", valid_total: 1, sample_total: 1 },
        { family: "2", status: "ready", observed_at: "2026-11-16T02:00:00Z", valid_total: 1, sample_total: 1 },
      ],
      "en",
    );
    expect(freshness.label).toContain("10:00");
    expect(freshness.title).toContain("11:00");
  });
});

describe("VersionMetricsPage component", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/version-metrics");
    vi.restoreAllMocks();
  });

  it("renders trend SVG, scheme toggles with schemes=none URL sync, Cooper report link, and RD Unknown fallback", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(buildPayload()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderMetrics({ lang: "zh", canWrite: true });

    await waitFor(() => {
      expect(container.querySelector(".vm-trend-svg")).not.toBeNull();
    });

    // Zero duplicate initial request when reconciling default families
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Zero raw native selects
    expect(container.querySelectorAll("select").length).toBe(0);

    // Cooper report links and RD unobserved fallback + membership_changed badge
    expect(container.querySelector('a[href="https://cooper.didichuxing.com/didocs/2210331433301"]')).not.toBeNull();
    expect(screen.getByText("版本已变化")).toBeInTheDocument();
    expect(screen.getByText("未知")).toBeInTheDocument();
    expect(screen.getByText("132/153")).toBeInTheDocument();

    // Toggling both default schemes off writes schemes=none without refetching
    const callCountBefore = fetchMock.mock.calls.length;
    fireEvent.click(container.querySelector('[data-vm-scheme="chain"]')!);
    fireEvent.click(container.querySelector('[data-vm-scheme="chain_post_human_sim"]')!);
    expect(new URLSearchParams(window.location.search).get("schemes")).toBe("none");
    expect(screen.getByText("请选择要比较的方案")).toBeInTheDocument();
    expect(fetchMock.mock.calls.length).toBe(callCountBefore);
  });

  it("disables refresh button for read-only users and switches to recall tp/support counts locally", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(buildPayload()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderMetrics({ lang: "en", canWrite: false });
    await waitFor(() => {
      expect(screen.getByText("132/153")).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: "Update metrics" })).toBeDisabled();

    // Switch metric to Correct-trigger recall via UiSelect
    fireEvent.click(screen.getByRole("combobox", { name: "Metric" }));
    fireEvent.click(screen.getByRole("option", { name: "Correct-trigger recall" }));
    expect(screen.getAllByText("40/45").length).toBeGreaterThan(0);
    expect(new URLSearchParams(window.location.search).get("metric")).toBe("recall_correct");
  });
});
