import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TrailHistoryPage } from "./TrailHistoryPage";

const MOCK_LIST = {
  items: [
    {
      id: "op-abc-123",
      created_at: "2026-11-25T10:00:00Z",
      actor: "jasperchen",
      actor_verified: true,
      source: "exclusion_summary",
      status: "succeeded",
      succeeded_count: 2,
      item_count: 2,
    },
    {
      id: "op-legacy-456",
      created_at: "2026-11-20T08:00:00Z",
      actor: "legacy_bot",
      actor_verified: false,
      source: "legacy",
      status: "succeeded",
      succeeded_count: 1,
      item_count: 1,
    },
  ],
  total: 2,
  page: 1,
  page_size: 20,
  started_at: "2026-10-01T00:00:00Z",
  can_restore: true,
};

const MOCK_DETAIL = {
  id: "op-abc-123",
  source: "exclusion_summary",
  status: "succeeded",
  actor: "jasperchen",
  created_at: "2026-11-25T10:00:00Z",
  reason: "Exclude duplicate sensor clips",
  parent_id: null,
  children: [],
  items: [
    {
      issue_id: "cn37760285",
      before: { should_exclude: false, should_exclude_comment: "", operation_id: "op-0" },
      after: { should_exclude: true, should_exclude_comment: "Duplicate clip", operation_id: "op-abc-123" },
    },
  ],
  outcomes: { cn37760285: "succeeded" },
  events: [
    {
      status: "succeeded",
      created_at: "2026-11-25T10:00:02Z",
      actor: "jasperchen",
      outcomes: { cn37760285: "succeeded" },
    },
  ],
  restorable: true,
  restorable_issue_ids: ["cn37760285"],
  current_conflicts: [],
};

function renderPage(lang: "zh" | "en" = "zh") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TrailHistoryPage active lang={lang} selectedBaselines={["version-20261106"]} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

describe("TrailHistoryPage", () => {
  it("renders list with zero native selects and opens body-portaled detail & restore flow", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/trail-history/op-abc-123/restore-preview") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            preview_id: "prev-1",
            ready: true,
            conflicts: [],
            items: [
              {
                issue_id: "cn37760285",
                current: { should_exclude: true, should_exclude_comment: "Duplicate clip" },
                restore: { should_exclude: false, should_exclude_comment: "" },
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.includes("/api/trail-history/op-abc-123")) {
        return new Response(JSON.stringify(MOCK_DETAIL), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/api/trail-history")) {
        return new Response(JSON.stringify(MOCK_LIST), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response("{}", { status: 200 });
    });

    const { container } = renderPage("zh");

    await waitFor(() => {
      expect(screen.getByText("jasperchen")).toBeTruthy();
      expect(screen.getByText("问题排除 · 汇总")).toBeTruthy();
      expect(screen.getByText("共 2 条")).toBeTruthy();
    });

    expect(container.querySelectorAll("select").length).toBe(0);

    // Open detail dialog (portaled to document.body)
    const detailButtons = screen.getAllByRole("button", { name: "详情／回溯" });
    fireEvent.click(detailButtons[0]);

    await waitFor(() => {
      const dialog = document.getElementById("raTrailHistoryDialog");
      expect(dialog).toBeTruthy();
      expect(dialog?.parentElement).toBe(document.body);
      expect(screen.getAllByText("cn37760285").length).toBeGreaterThan(0);
      expect(screen.getByText("Exclude duplicate sensor clips")).toBeTruthy();
    });

    // Enter restore workflow and preview
    fireEvent.click(screen.getByRole("button", { name: "恢复…" }));
    await waitFor(() => {
      expect(screen.getByText("选择要恢复的 Issue")).toBeTruthy();
    });

    const checkbox = screen.getByRole("checkbox", { name: "恢复 cn37760285" });
    fireEvent.click(checkbox);
    const reasonInput = document.getElementById("trailHistoryReason") as HTMLTextAreaElement;
    fireEvent.change(reasonInput, { target: { value: "False alarm restore" } });

    const previewBtn = screen.getByRole("button", { name: "预览恢复" });
    expect((previewBtn as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(previewBtn);

    await waitFor(() => {
      expect(screen.getByText("恢复预览")).toBeTruthy();
      expect(screen.getByRole("button", { name: "确认恢复" })).toBeTruthy();
    });
    expect(fetchMock).toHaveBeenCalled();
  });

  it("renders English strings cleanly", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(MOCK_LIST), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    renderPage("en");
    await waitFor(() => {
      expect(screen.getByText("2 records")).toBeTruthy();
      expect(screen.getByText("Issue exclusion · Summary")).toBeTruthy();
      expect(screen.getAllByRole("button", { name: "Details / Restore" }).length).toBe(2);
    });
  });
});
