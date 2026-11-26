import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunsManagerIsland, ModelRunItem } from "./RunsManagerIsland";

function makeRuns(count: number): ModelRunItem[] {
  return Array.from({ length: count }, (_, idx) => ({
    id: `run-${idx + 1}`,
    name: idx === 0 ? "Baseline V1" : `Candidate Run ${idx + 1}`,
    kind: idx % 2 === 0 ? "upload" : "trail_snapshot",
    is_default: idx === 0,
    created_by: idx % 3 === 0 ? "jasperchen" : "alice",
    created_at: "2026-11-24T12:00:00Z",
    baseline_prediction_count: idx === 0 ? 100 : 40,
    failure_count: idx,
    source_name: `model_${idx + 1}.json`,
    source_file:
      idx === 0
        ? {
            filename: "model_1.json",
            available: true,
            preview_supported: true,
            preview_url: "/api/model-runs/run-1/source-preview",
            download_url: "/api/model-runs/run-1/source-download",
          }
        : undefined,
    metadata: {
      model_name: idx === 0 ? "qwen-ra-v1" : "qwen-ra-v2",
      prompt_version: "p3",
    },
  }));
}

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("RunsManagerIsland", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState({}, "", "/");
  });

  it("renders runs with zero native selects, filters by person/kind/search, and paginates", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          items: makeRuns(15),
          baseline_issue_count: 100,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { container } = renderWithClient(
      <RunsManagerIsland active lang="en" username="jasperchen" />,
    );

    expect(await screen.findByText("Baseline V1")).toBeInTheDocument();
    expect(container.querySelectorAll("select").length).toBe(0);
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/api/model-runs"),
      expect.any(Object),
    );

    // Filter by source kind via shared UiSelect
    const kindTrigger = screen.getByRole("combobox", { name: "Filter runs by source type" });
    fireEvent.click(kindTrigger);
    fireEvent.click(screen.getByRole("option", { name: "Trail snapshot" }));

    await waitFor(() => {
      expect(screen.queryByText("Baseline V1")).not.toBeInTheDocument();
      expect(screen.getByText("Candidate Run 2")).toBeInTheDocument();
    });

    // Reset kind to All sources and change page size to 10
    fireEvent.click(kindTrigger);
    fireEvent.click(screen.getByRole("option", { name: "All sources" }));
    expect(await screen.findByText("Baseline V1")).toBeInTheDocument();

    const sizeTrigger = screen.getByRole("combobox", { name: "Items per page" });
    fireEvent.click(sizeTrigger);
    fireEvent.click(screen.getByRole("option", { name: "10" }));

    expect(await screen.findByText("1 / 2 · 15")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("2 / 2 · 15")).toBeInTheDocument();
    expect(screen.getByText("Candidate Run 15")).toBeInTheDocument();
  });

  it("delegates review/preview actions and confirms deletion via ModalDialog", async () => {
    const useModelRun = vi.fn();
    const openSourcePreview = vi.fn();
    (window as unknown as Record<string, unknown>).useModelRun = useModelRun;
    (window as unknown as Record<string, unknown>).openSourcePreview = openSourcePreview;

    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (init?.method === "DELETE" && url.includes("/api/model-runs/run-2")) {
          return new Response(
            JSON.stringify({ deleted: { name: "Candidate Run 2" }, source_deleted: true }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response(
          JSON.stringify({ items: makeRuns(2), baseline_issue_count: 100 }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      });

    renderWithClient(<RunsManagerIsland active lang="zh" username="jasperchen" />);
    expect(await screen.findByText("Baseline V1")).toBeInTheDocument();

    // Default run cannot be deleted
    expect(screen.getByRole("button", { name: "默认 Run" })).toBeDisabled();

    // Preview delegates to legacy openSourcePreview
    fireEvent.click(screen.getByRole("button", { name: "预览" }));
    expect(openSourcePreview).toHaveBeenCalledWith("run-1");

    // Open in Review delegates to legacy useModelRun
    fireEvent.click(screen.getAllByRole("button", { name: "打开 Review" })[1]!);
    expect(useModelRun).toHaveBeenCalledWith("run-2");

    // Delete opens confirmation modal and sends DELETE
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining("/api/model-runs/run-2"),
        expect.objectContaining({ method: "DELETE" }),
      );
    });
  });
});
