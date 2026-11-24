import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DailyCronPage, DailyCronPayload } from "./DailyCronPage";

function sampleCronPayload(): DailyCronPayload {
  return {
    observed_at: 1763980000,
    sources: { overview: "ready", media: "ready" },
    incremental: {
      enabled: true,
      stale: false,
      updated_at: 1763980000,
      families: ["20261113", "20261106"],
      states: { published: 120, inferred: 5, waiting_metadata: 2 },
      media: {
        selected: 50,
        verified: 48,
        triple_verified: 45,
        camera_verified: 50,
        bev_verified: 48,
        closeup: { receipt_status: "ready", verified: 45, attention: 1, queued: 4, unknown: 0 },
      },
      planning_text: {
        status: "ready",
        selected: 50,
        with_frames: 44,
        collected: 40,
        partial_source: 4,
        failed: 1,
        pending: 5,
        unknown: 0,
      },
      versions: [
        {
          family: "20261113",
          states_status: "ready",
          updated_at: 1763980000,
          states: { published: 70, inferred: 2, waiting_metadata: 1 },
          media: {
            selected: 30,
            verified: 30,
            triple_verified: 30,
            camera_verified: 30,
            bev_verified: 30,
            closeup: { receipt_status: "ready", verified: 30, attention: 0, queued: 0, unknown: 0 },
          },
          planning_text: {
            status: "ready",
            selected: 30,
            with_frames: 29,
            collected: 29,
            partial_source: 0,
            failed: 0,
            pending: 1,
            unknown: 0,
          },
        },
        {
          family: "20261106",
          states_status: "ready",
          updated_at: 1763979000,
          states: { published: 50, inferred: 3, waiting_metadata: 1 },
          media: {
            selected: 20,
            verified: 18,
            triple_verified: 15,
            camera_verified: 20,
            bev_verified: 18,
            closeup: { receipt_status: "ready", verified: 15, attention: 1, queued: 4, unknown: 0 },
          },
        },
      ],
      discovery_schedule: { hours: [7, 19] },
      increments: {
        status: "ready",
        items: [
          {
            start_at: 1763970000,
            family: "20261113",
            scan_state: "success",
            new: 4,
            filled: 1,
            published: 3,
            target_added: 2,
            target_removed: 0,
          },
        ],
      },
    },
    overview: {
      collected_at: 1763980000,
      stale: false,
      daily: {
        health: "success",
        target_date: "2026-11-23",
        runs: [],
        alerts: [],
      },
      jobs: Array.from({ length: 12 }, (_, idx) => ({
        name: `job-${idx + 1}`,
        schedule: "0 9 * * *",
        log_updated_at: 1763980000,
        evidence: "recent",
      })),
    },
    sidecar: {
      daily_enabled: true,
      updated_at: 1763980000,
      state: "complete",
      imported: 100,
      media_verified: 100,
      total: 100,
      failure_count: 0,
    },
    history: [],
  };
}

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("DailyCronPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState({}, "", "/");
  });

  it("renders incremental metrics, switches scope via UiSelect, triggers ?refresh=true, and has zero native selects", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      return new Response(JSON.stringify(sampleCronPayload()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });

    const { container } = renderWithClient(<DailyCronPage active lang="en" theme="dark" />);

    expect(await screen.findByText(/1113 · 72 \/ 72/)).toBeInTheDocument();
    expect(container.querySelectorAll("select").length).toBe(0);

    // Switch scope to All versions via shared UiSelect
    const scopeSelect = screen.getByRole("combobox", { name: "Select version or legacy daily run" });
    fireEvent.click(scopeSelect);
    fireEvent.click(screen.getByRole("option", { name: "All versions" }));

    expect(await screen.findByText(/All versions · 125 \/ 125/)).toBeInTheDocument();
    expect(window.location.search).toContain("cron_version=all");

    // Click Refresh and assert cache-bypassing ?refresh=true is sent
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining("/api/daily-cron?refresh=true"),
        expect.any(Object),
      );
    });

    // Open Help modal
    fireEvent.click(screen.getByRole("button", { name: "Inference pipeline definition" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
  });

  it("searches and paginates scheduled tasks table in ZH", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(sampleCronPayload()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithClient(<DailyCronPage active lang="zh" theme="light" />);
    expect(await screen.findByText(/1113 · 72 \/ 72/)).toBeInTheDocument();

    // Open Other scheduled tasks fold
    fireEvent.click(screen.getByText(/其他定时任务/));
    const searchInput = screen.getByPlaceholderText("搜索任务或调度表达式");
    fireEvent.change(searchInput, { target: { value: "job-12" } });
    expect(await screen.findByText("job-12")).toBeInTheDocument();
    expect(screen.queryByText("job-11")).not.toBeInTheDocument();
  });
});
