import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TrailUpdatePage } from "./TrailUpdatePage";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const PREVIEW_PAYLOAD = {
  mode: "local",
  baselines: ["version-20261106"],
  local_candidate_count: 1,
  payload_sha256: "abcdef1234567890",
  write_status: "disabled",
  write_ready: false,
  target_field: "ra_triage_dashboard",
  target_path: "ra_triage_dashboard.should_exclude",
  comment_target_path: "ra_triage_dashboard.should_exclude_comment",
  trail_capability: { status: "readonly", message: "写入未启用" },
  items: [
    {
      row_key: "version-20261106|cn37760285",
      issue_id: "cn37760285",
      baseline_id: "version-20261106",
      source_kind: "local",
      local_selected: true,
      gt_label: "误触发",
      comment: "GPS 漂移，排除",
      trail_update_status: "pending",
      trail_detail: {
        state: "pending",
        trail_should_exclude: false,
        local_comment: "GPS 漂移，排除",
      },
      reason_source: { kind: "review", author: "jasperchen", rationale: "GPS 漂移，排除" },
      review: { reviewer: "jasperchen", status: "done", note: "GPS 漂移，排除" },
    },
  ],
};

const STATUS_PAYLOAD = {
  trail_capability: { status: "readonly", message: "写入未启用" },
  trail_update_statuses: { cn37760285: "pending" },
  trail_update_details: {
    cn37760285: { state: "pending", trail_should_exclude: false, local_comment: "GPS 漂移，排除" },
  },
  trail_update_status_summary: { pending: 1 },
  pending_count: 1,
  write_status: "disabled",
  write_ready: false,
  checked_at: "2026-11-25T10:00:00Z",
};

const HISTORY_PAYLOAD = {
  items: [
    {
      id: 1,
      status: "completed",
      actor: "jasperchen",
      created_at: "2026-11-25T09:00:00Z",
      requested_count: 2,
      succeeded_count: 2,
      issue_ids: ["cn37760285", "cn37789923"],
    },
  ],
};

describe("TrailUpdatePage", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    if (!HTMLDialogElement.prototype.showModal) {
      HTMLDialogElement.prototype.showModal = function () {
        this.setAttribute("open", "");
      };
    }
    if (!HTMLDialogElement.prototype.close) {
      HTMLDialogElement.prototype.close = function () {
        this.removeAttribute("open");
      };
    }
    window.history.replaceState({}, "", "/trail-attribute-update?baselines=version-20261106");
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/trail-attribute-update/status")) {
        return Promise.resolve(
          new Response(JSON.stringify(STATUS_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/trail-attribute-update/issue-history")) {
        return Promise.resolve(
          new Response(JSON.stringify(HISTORY_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.includes("/api/trail-attribute-update/preview")) {
        return Promise.resolve(
          new Response(JSON.stringify(PREVIEW_PAYLOAD), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ ok: true, items: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads preview + status, enforces zero native selects, opens detail dialog, and switches to Issue ID tab", async () => {
    const { container } = renderWithQuery(
      <TrailUpdatePage
        active
        lang="zh"
        selectedBaselines={["version-20261106"]}
        canWrite
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("cn37760285")).toBeInTheDocument();
    });
    expect(container.querySelectorAll("select").length).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: "详情" }));
    await waitFor(() => {
      expect(document.getElementById("raTrailReasonDetailsDialog")).toBeInTheDocument();
    });

    const issueTab = screen.getByRole("tab", { name: /Issue ID 屏蔽/ });
    fireEvent.click(issueTab);

    await waitFor(() => {
      expect(screen.getByText("导入 JSON")).toBeInTheDocument();
    });
    expect(container.querySelectorAll("select").length).toBe(0);
  });

  it("renders English UI cleanly", async () => {
    renderWithQuery(
      <TrailUpdatePage
        active
        lang="en"
        selectedBaselines={["version-20261106"]}
        canWrite={false}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("cn37760285")).toBeInTheDocument();
    });
    expect(screen.getByRole("tab", { name: /Exclusions/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Shield by Issue ID/ })).toBeInTheDocument();
  });
});
