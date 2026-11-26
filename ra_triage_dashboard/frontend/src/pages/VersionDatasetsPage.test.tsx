import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  VersionDatasetCatalogResponse,
  VersionDatasetsPage,
  VersionWorkbenchResponse,
  versionLabelColor,
  versionTEResultLabel,
} from "./VersionDatasetsPage";

function buildCatalog(): VersionDatasetCatalogResponse {
  return {
    items: [
      {
        id: "release-20261113-odd2",
        release_family: "20261113",
        historical: false,
        total: 1200,
        targets: 180,
        states: { published: 1000, excluded: 150, waiting_metadata: 50 },
      },
      {
        id: "historical-0821",
        release_family: "20260821",
        historical: true,
        total: 400,
        targets: 400,
        states: {},
      },
    ],
  };
}

function buildWorkbench(datasetId = "release-20261113-odd2"): VersionWorkbenchResponse {
  return {
    dataset_id: datasetId,
    dataset: {
      id: datasetId,
      release_family: datasetId === "historical-0821" ? "20260821" : "20261113",
      historical: datasetId === "historical-0821",
      total: 1200,
      targets: 180,
      states: { published: 1000, excluded: 150, waiting_metadata: 50 },
    },
    count_scope: {
      total: 1200,
      targets: 180,
      states: { published: 1000, excluded: 150, waiting_metadata: 50 },
      exclusions: [{ type: "CZ_TL", count: 120 }],
      sampled: 100,
      completed: 1000,
      low_only: 80,
      trail_links: {
        all: "https://trail.example/all",
        excluded: "https://trail.example/excluded",
        published: "https://trail.example/published",
        targets: "https://trail.example/targets",
        sampled_targets: "https://trail.example/sampled",
        source_waiting: "https://trail.example/waiting",
      },
      trail_link_types: { all: "reason_fields" },
    },
    composition: {
      total: 1000,
      pending: 50,
      excluded: 150,
      groups: [
        { key: "low", count: 100, ratio: 0.1 },
        { key: "sample", count: 80, ratio: 0.08 },
        { key: "other", count: 820, ratio: 0.82 },
      ],
    },
    te: {
      summary: { total: 180, filled: 120, unfilled: 50, unknown: 10, rate: 120 / 180 },
      source_status: "ready",
      last_success_at: "2026-11-24T04:00:00Z",
      observed_changes: { te: 4 },
      distribution: [
        { value: "误触发", count: 70 },
        { value: "成功", count: 50 },
      ],
      daily: [
        {
          date: "2026-11-22",
          summary: { total: 90, filled: 60, unfilled: 25, unknown: 5, rate: 60 / 90 },
        },
        {
          date: "2026-11-23",
          summary: { total: 90, filled: 60, unfilled: 25, unknown: 5, rate: 60 / 90 },
        },
      ],
    },
    rd: {
      source_status: "ready",
      total: 180,
      completed: 100,
      pending: 75,
      conflict: 5,
      distribution: { 正确触发: 40, 误触发: 45, 无需协助: 15 },
    },
    assignees: ["alice", "bob"],
    date_options: ["2026-11-22", "2026-11-23"],
    snapshot_revision: "rev-1",
    page: 1,
    page_size: 20,
    total: 1,
    items: [
      {
        issue_id: "cn12345678",
        state: "published",
        date: "2026-11-23",
        issue_time: "2026-11-23T06:00:00Z",
        first_seen: "2026-11-23T06:10:00Z",
        trigger: "STUCK",
        is_target: true,
        is_sample: true,
        is_low: false,
        te_status: "filled",
        te_value: "误触发",
        review_submitted: true,
        prediction: { model_label: "误触发", model_confidence: 0.945 },
        binding: { run_id: "run-1", campaign_id: "camp-1", assignees: ["alice"] },
      },
    ],
  };
}

function renderDatasets(lang: "zh" | "en" = "zh") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <VersionDatasetsPage active lang={lang} />
    </QueryClientProvider>,
  );
}

describe("VersionDatasetsPage helpers", () => {
  it("maps categorical label colors and bilingual TE labels identically to classic", () => {
    expect(versionLabelColor("成功")).toBe("var(--chart-teal)");
    expect(versionLabelColor("正确触发")).toBe("var(--chart-teal)");
    expect(versionLabelColor("误触发")).toBe("var(--chart-rose)");
    expect(versionLabelColor("失败")).toBe("var(--chart-indigo)");
    expect(versionLabelColor("无需协助")).toBe("var(--chart-blue)");
    expect(versionLabelColor("未接起")).toBe("var(--chart-slate)");
    expect(versionLabelColor("__proto__")).toBe("var(--muted)");

    expect(versionTEResultLabel("成功", "en")).toBe("Succeeded");
    expect(versionTEResultLabel("out_of_scope", "en")).toBe("Out of scope");
    expect(versionTEResultLabel("custom", "en")).toBe("custom");
  });
});

describe("VersionDatasetsPage component", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/version-datasets");
    vi.restoreAllMocks();
  });

  it("renders KPI popovers, composition, 124px TE ring, daily bars, RD strip, and dense gallery with zero native selects", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/workbench")) {
        return Promise.resolve(
          new Response(JSON.stringify(buildWorkbench()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(buildCatalog()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderDatasets("zh");

    await waitFor(() => {
      expect(screen.getByText("cn12345678 ↗")).toBeInTheDocument();
    });

    // Zero raw native selects
    expect(container.querySelectorAll("select").length).toBe(0);

    // Metrics deep link
    const metricsLink = container.querySelector<HTMLAnchorElement>("#versionDatasetMetricsLink");
    expect(metricsLink?.hidden).toBe(false);
    expect(metricsLink?.getAttribute("href")).toContain("/version-metrics?families=20261113");

    // 4 KPI cards with Trail links & info tooltips
    expect(container.querySelectorAll("#versionDatasetSummary .analysis-stat-card").length).toBe(4);
    expect(container.querySelectorAll("#versionDatasetSummary .version-metric-links a").length).toBe(6);

    // 124px SVG ring, TE distribution, daily bars, RD 2-col strip
    expect(container.querySelectorAll("#versionTERing circle[data-chart-key]").length).toBe(3);
    expect(container.querySelectorAll("#versionTEDailyChart .te-day").length).toBe(2);
    expect(container.querySelectorAll("#versionRDPanel .version-rd-block").length).toBe(2);

    // Clicking a daily progress row toggles URL date filter
    fireEvent.click(container.querySelector('[data-version-date="2026-11-22"]')!);
    expect(new URLSearchParams(window.location.search).get("date")).toBe("2026-11-22");

    // Clicking All dates clears date without dropping other filters
    fireEvent.click(container.querySelector("#versionTEAllDates")!);
    expect(new URLSearchParams(window.location.search).has("date")).toBe(false);
  });

  it("opens classic openMedia bridge when clicking a case card thumbnail", async () => {
    const openMediaSpy = vi.fn();
    (window as unknown as { openMedia?: unknown; heroFrameIndex?: unknown }).openMedia =
      openMediaSpy;
    (window as unknown as { heroFrameIndex?: unknown }).heroFrameIndex = () => 2;

    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/cases/cn12345678/media")) {
        return Promise.resolve(
          new Response(JSON.stringify({ issue_id: "cn12345678", assets: { frames: ["f0", "f1", "f2"] } }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/workbench")) {
        return Promise.resolve(
          new Response(JSON.stringify(buildWorkbench()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(buildCatalog()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderDatasets("zh");
    await waitFor(() => {
      expect(container.querySelector('[data-version-open="cn12345678"]')).not.toBeNull();
    });

    fireEvent.click(container.querySelector('[data-version-open="cn12345678"]')!);
    await waitFor(() => {
      expect(openMediaSpy).toHaveBeenCalledTimes(1);
    });
    expect(openMediaSpy.mock.calls[0][0]).toBe("bev");
    expect(openMediaSpy.mock.calls[0][1]).toBe(2);
    expect(openMediaSpy.mock.calls[0][2].caseData.te_observation.version_dataset).toBe(true);
  });
});
