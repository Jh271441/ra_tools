import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SystemStatusPage, SystemStatusPayload } from "./SystemStatusPage";

const HEALTHY_PAYLOAD: SystemStatusPayload = {
  overall: { status: "healthy", problems: [] },
  build_commit: "04f777c05f6c",
  change_revision: 88,
  generated_at: "2026-11-24T17:44:00Z",
  application: {
    base_path: "/manual",
    build_commit: "04f777c05f6c",
    uptime_seconds: 9000,
    started_at: "2026-11-24T15:14:00Z",
    deployment_mode: "production",
  },
  database: {
    ok: true,
    backend: "postgresql",
    persistent_data: true,
    latency_ms: 1.4,
    server_version: "14.11",
    migration_count: 62,
    pool_max_size: 16,
    revision: 88,
  },
  backups: {
    available: true,
    latest_name: "pg-backup.dump",
    latest_path: "/volume/backups/pg-backup.dump",
    latest_created_at: "2026-11-24T16:00:00Z",
    latest_age_seconds: 6200,
    latest_size_bytes: 52428800,
    count: 14,
    latest_checksum_present: true,
    schedule_registered: true,
    schedule_line: "0 3 * * *",
  },
  volume: {
    path: "/volume",
    available: true,
    used_bytes: 100 * 1024 ** 3,
    free_bytes: 900 * 1024 ** 3,
    total_bytes: 1000 * 1024 ** 3,
    used_percent: 10,
  },
  ra_auto_triage_root_available: true,
  ares_manifest_available: true,
  camera_cache_root_available: true,
  ares_video_root_available: true,
  baseline_conflicts: [],
  baselines: [
    {
      id: "0508",
      scope: "0508",
      label: "0508",
      default_selected: true,
      count: 1071,
      status: "ready",
      registration_status: "registered",
      media_status: "complete",
      membership: { status: "ready", expected_count: 1071, registered_count: 1071 },
      media_ready: {
        bev_indexed_issues: 1071,
        video_indexed_issues: 1071,
        camera_indexed_issues: 1071,
        coverage_status: "ready",
        failure_count: 0,
      },
      missing_media: {},
    },
  ],
  model_gateway: { configured: true },
  batch_prediction_enabled: true,
  autotriage_push_enabled: true,
  trail_sync: { status: "ready", message: "Connected" },
  legacy_cutover: { policies: [{ baseline_scope: "0508", policy: "canonical" }] },
};

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SystemStatusPage", () => {
  it("renders healthy system cards, 18/18 dataset table, and toggles ZH/EN cleanly", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(HEALTHY_PAYLOAD),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = renderWithQuery(<SystemStatusPage active lang="zh" />);

    await waitFor(() => {
      expect(screen.getByText("关键系统运行正常")).toBeInTheDocument();
    });
    expect(screen.getByText("04f777c05f6c")).toBeInTheDocument();
    expect(screen.getByText("14.11 · 62")).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "0508" })).toBeInTheDocument();
    expect(screen.getByText("完整")).toBeInTheDocument();

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["system-status"], HEALTHY_PAYLOAD);
    rerender(
      <QueryClientProvider client={client}>
        <SystemStatusPage active lang="en" />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Core systems healthy")).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
  });

  it("calls /api/status?refresh=true when Refresh status is clicked", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(HEALTHY_PAYLOAD),
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<SystemStatusPage active lang="en" />);
    await waitFor(() => expect(screen.getByText("Core systems healthy")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/status?refresh=true",
        expect.objectContaining({ method: "GET" }),
      );
    });
  });
});
