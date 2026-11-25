import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RdResultsPage } from "./RdResultsPage";

const MOCK_HP = {
  items: [
    {
      issue_id: "cn37760285",
      generation: 1,
      conclusion: "resolved",
      label: "误触发",
      authors: ["jasperchen"],
      required: 1,
      submitted: 1,
      publication_armed: 1,
      sync_state: "synced",
      checked_at: "2026-11-25T10:00:00Z",
      error_code: null,
      objections: [],
    },
  ],
  counts: { resolved: 1, pending: 0, conflict: 0 },
  total: 1,
  page: 1,
  pages: 1,
  page_size: 20,
  field: "ra_rd_review_result",
  write_enabled: false,
};

const MOCK_RD = {
  items: [
    {
      issue_id: "cn32171803",
      group: "resolved",
      state: "resolved",
      label: "正确触发",
      te_current: "误触发",
      correction_status: "candidate",
      authors: ["jasperchen"],
    },
  ],
  counts: { total: 1, resolved: 1, pending: 0, conflict: 0, same: 0, blocked: 0 },
  total: 1,
  page: 1,
  pages: 1,
  page_size: 20,
  write_enabled: false,
};

function renderPage(baselines: string[], lang: "zh" | "en" = "zh") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RdResultsPage active lang={lang} selectedBaselines={baselines} isAdmin />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

describe("RdResultsPage", () => {
  it("renders 3-lane Human Publications for version >= 20261106 with zero native selects and inline history", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/human-publications/history")) {
        return new Response(
          JSON.stringify({
            items: [
              {
                created_at: "2026-11-25T10:00:00Z",
                action: "set",
                desired: "误触发",
                state: "verified",
              },
            ],
            total: 1,
            page: 1,
            pages: 1,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.includes("/api/human-publications")) {
        return new Response(JSON.stringify(MOCK_HP), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response("{}", { status: 200 });
    });

    const { container } = renderPage(["version-20261106"], "zh");

    await waitFor(() => {
      expect(screen.getByText("cn37760285")).toBeTruthy();
      expect(screen.getByRole("tab", { name: "RD 标注" })).toBeTruthy();
      expect(screen.getByRole("tab", { name: "TE′ 标注" })).toBeTruthy();
      expect(screen.getByRole("tab", { name: "裁决标注" })).toBeTruthy();
    });

    expect(container.querySelectorAll("select").length).toBe(0);

    // Open inline history drawer
    fireEvent.click(screen.getByRole("button", { name: "查看" }));
    await waitFor(() => {
      expect(document.getElementById("hpHistory")).toBeTruthy();
      expect(screen.getByText("读回一致")).toBeTruthy();
    });
  });

  it("renders Classic RD & TE correction modes for 0508 dataset with zero native selects", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(MOCK_RD), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const { container } = renderPage(["0508"], "en");

    await waitFor(() => {
      expect(screen.getByText("cn32171803")).toBeTruthy();
      expect(screen.getByRole("tab", { name: "RD label upload" })).toBeTruthy();
      expect(screen.getByRole("tab", { name: "TE label correction" })).toBeTruthy();
    });

    expect(container.querySelectorAll("select").length).toBe(0);

    // Switch to TE correction tab -> shows version requirement notice for 0508
    fireEvent.click(screen.getByRole("tab", { name: "TE label correction" }));
    await waitFor(() => {
      expect(screen.getByText("Select one version dataset for TE correction.")).toBeTruthy();
    });
  });
});
