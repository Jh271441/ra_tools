import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalysisPage } from "./AnalysisPage";
import { RunCollectionsPage } from "./RunCollectionsPage";
import { RunComparisonPage } from "./RunComparisonPage";
import { VersionDatasetsPage } from "./VersionDatasetsPage";
import { VersionMetricsPage } from "./VersionMetricsPage";

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Wave 3.4 React 19 Page Islands", () => {
  it("renders VersionDatasetsPage with zero native <select> and bilingual controls", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/workbench")) {
        return new Response(
          JSON.stringify({
            dataset_id: "release-20261113-odd2",
            page: 1,
            page_size: 20,
            total: 1,
            dataset: { id: "release-20261113-odd2", release_family: "20261113", targets: 1, total: 10 },
            items: [{ issue_id: "cn99990001", is_target: true, te_status: "filled", te_value: "正确触发" }],
            te: {
              source_status: "ready",
              summary: { total: 1, filled: 1, unfilled: 0, unknown: 0 },
              distribution: [{ value: "正确触发", count: 1 }],
              daily: [],
            },
            rd: { total: 1, completed: 1, pending: 0, conflict: 0, distribution: { 正确触发: 1, 误触发: 0, 无需协助: 0 } },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(
        JSON.stringify({
          items: [{ id: "release-20261113-odd2", release_family: "20261113", targets: 1, total: 10 }],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });

    (window as unknown as { __RA_TRIAGE_BASE__?: string }).__RA_TRIAGE_BASE__ = "/manual";
    const { container } = wrap(<VersionDatasetsPage active lang="en" />);
    await waitFor(() => expect(screen.getByText(/cn99990001/)).toBeInTheDocument());
    expect(container.querySelectorAll("select").length).toBe(0);
    expect(screen.getByText("Version datasets")).toBeInTheDocument();
    const img = container.querySelector("img");
    expect(img?.getAttribute("src")).toContain("/manual/api/case-thumbnails/cn99990001");
    delete (window as unknown as { __RA_TRIAGE_BASE__?: string }).__RA_TRIAGE_BASE__;
  });

  it("renders VersionMetricsPage chart, table, and MultiSelect with zero native <select>", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          catalog: [{ family: "20261113", dataset_id: "release-20261113-odd2" }],
          selected: ["20261113"],
          items: [
            {
              family: "20261113",
              status: "ready",
              valid_total: 100,
              sample_total: 110,
              metrics: {
                chain: { accuracy: 0.91, correct: 91, total: 100, reference_total: 100, human_count: 0, per_class: [] },
                chain_post_human_sim: { accuracy: 0.96, correct: 96, total: 100, reference_total: 100, human_count: 10, per_class: [] },
              },
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { container } = wrap(<VersionMetricsPage active lang="zh" canWrite={false} />);
    await waitFor(() => expect(screen.getAllByText("11-13").length).toBeGreaterThanOrEqual(2));
    expect(container.querySelectorAll("select").length).toBe(0);
    expect(container.querySelector("svg.vm-trend-svg")).toBeInTheDocument();
  });

  it("renders AnalysisPage clusters, cases, and pagination with zero native <select>", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/review-reason-analysis")) {
        return new Response(
          JSON.stringify({
            total: 1,
            page: 1,
            page_size: 20,
            page_count: 1,
            summary: { latest_reviews: 12, with_reason: 10, empty_reason: 2, with_structured_evidence: 8 },
            missing_evidence: [{ key: "bev_blur", label: "BEV 模糊", count: 5 }],
            tag_clusters: [{ key: "cone", label: "锥桶占道", count: 4 }],
            items: [
              {
                issue_id: "cn88881111",
                gt_label: "误触发",
                comparison_status: "mismatch",
                annotation: { note: "模型误判红绿灯", author: "jasperchen" },
                prediction: { label: "正确触发", confidence: 0.87 },
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    const { container } = wrap(<AnalysisPage active lang="zh" selectedBaselines={["0508"]} />);
    await waitFor(() => expect(screen.getByText("cn88881111")).toBeInTheDocument());
    expect(container.querySelectorAll("select").length).toBe(0);
    expect(screen.getByText("BEV 模糊")).toBeInTheDocument();
  });

  it("renders RunComparisonPage metrics & cases with zero native <select>", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/model-run-comparison")) {
        return new Response(
          JSON.stringify({
            view_mode: "pair",
            page: 1,
            page_size: 20,
            page_count: 1,
            total: 1,
            baseline_run: { id: "run-a", name: "Baseline A" },
            candidate_run: { id: "run-b", name: "Candidate B" },
            summary: {
              total_count: 10,
              accuracy_delta: 0.05,
              label_changed_count: 2,
              transition_counts: { P2F: 1, F2P: 3, F2F: 1, P2P: 5 },
              baseline: { accuracy: 0.8, correct_count: 8, total_count: 10 },
              candidate: { accuracy: 0.85, correct_count: 9, total_count: 10 },
            },
            items: [
              {
                issue_id: "cn77770001",
                gt_label: "正确触发",
                transition: "F2P",
                baseline: { model_label: "误触发", correct: false, model_confidence: 0.72 },
                candidate: { model_label: "正确触发", correct: true, model_confidence: 0.94 },
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(
        JSON.stringify({
          items: [
            { id: "run-b", name: "Candidate B", baseline_prediction_count: 10 },
            { id: "run-a", name: "Baseline A", baseline_prediction_count: 10 },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });

    const { container } = wrap(
      <RunComparisonPage active lang="en" selectedBaselines={["0508"]} isAdmin={false} />,
    );
    await waitFor(() => expect(screen.getByText("cn77770001")).toBeInTheDocument());
    expect(container.querySelectorAll("select").length).toBe(0);
    expect(screen.getByText("+5.0 pp")).toBeInTheDocument();
  });

  it("renders RunCollectionsPage project detail & frozen snapshot with zero native <select>", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/run-collections")) {
        return new Response(
          JSON.stringify({ items: [{ id: "col-1", name: "Bench 1113", current_revision: 1 }] }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.includes("/api/run-collections/col-1")) {
        return new Response(
          JSON.stringify({
            id: "col-1",
            name: "Bench 1113",
            current_revision: 1,
            history: [
              {
                revision: 1,
                content_sha256: "abcdef123456",
                members: [{ run_id: "run-1", is_reference: true, run: { name: "Run One" } }],
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response(JSON.stringify({ items: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    const { container } = wrap(
      <RunCollectionsPage active lang="zh" isAdmin={false} selectedBaselines={["0508"]} />,
    );
    await waitFor(() => expect(screen.getByText("Run One")).toBeInTheDocument());
    expect(container.querySelectorAll("select").length).toBe(0);
  });
});
