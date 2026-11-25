import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WorkbenchProvider } from "../shell/WorkbenchContext";
import { AppShell } from "../shell/AppShell";
import { resolvePageFromLocation } from "../shell/routes";
import { buildCronGraphModel } from "../features/cron-graph/buildCronGraphModel";
import { DailyReviewPage } from "./DailyReviewPage";
import { TrailHistoryPage } from "./TrailHistoryPage";
import { IntentExperimentsPage } from "./IntentExperimentsPage";
import { IntentLabelingPage } from "./IntentLabelingPage";
import { IntentSummaryPage } from "./IntentSummaryPage";
import { CampaignsPage } from "./CampaignsPage";
import { PredictionPage } from "./PredictionPage";
import { TrailUpdatePage } from "./TrailUpdatePage";
import { RunsPage } from "./RunsPage";

function wrap(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <WorkbenchProvider>{ui}</WorkbenchProvider>
    </QueryClientProvider>
  );
}

describe("Wave 3.6 Pure React AppShell & Final 8 Pages", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState({}, "", "/review");
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      let body: unknown = {};
      if (url.includes("/api/session")) {
        body = {
          authenticated: true,
          verified: true,
          username: "jasperchen",
          access_role: "admin",
          is_admin: true,
          can_write: true,
          can_view_intent: true,
          can_annotate_intent: true,
          can_manage_intent: true,
        };
      } else if (url.includes("/api/dashboard-config")) {
        body = {
          baselines: [{ id: "0508", label: "0508", count: 1071, default_selected: true }],
          default_baseline_ids: ["0508"],
          gt_sync: { status: "ready", baselines: [] },
        };
      } else if (url.includes("/api/overview")) {
        body = {
          issues: 1071,
          model_failures: 12,
          labelled: 7,
          label_state_counts: { resolved: 260 },
          predictions: 100,
        };
      } else if (url.includes("/api/intent-datasets")) {
        body = { items: [{ id: "intent_0206", display_name: "0206 Intent", available: true, case_count: 42 }] };
      } else if (url.includes("/api/daily-review/cases")) {
        body = {
          scope: { dataset: "1009", date: "" },
          version_membership: true,
          date_options: ["2026-11-24"],
          summary: { total: 10, filled: 6, unfilled: 4, unknown: 0, rate: 0.6, coverage: 1, reasons: { low: 7, sample: 3 } },
          daily_overview: [],
          result_distribution: [{ value: "误触发", count: 4 }],
          items: [{ issue_id: "cn37631883", date: "2026-11-24", reason: "low", te_status: "filled", te_value: "误触发" }],
          total: 1,
          page: 1,
          size: 20,
        };
      } else if (url.includes("/api/trail-history")) {
        body = {
          items: [{ id: "op-1", created_at: "2026-11-25T02:00:00Z", actor: "jasperchen", actor_verified: true, source: "exclusion_direct", item_count: 2, succeeded_count: 2, status: "succeeded" }],
          total: 1,
          page: 1,
          page_size: 20,
          can_restore: true,
        };
      } else if (url.includes("/api/intent-experiments")) {
        body = {
          items: [
            {
              id: "exp-1",
              dataset_id: "intent_0206",
              name: "0206 Blind Review",
              label_scope: "all",
              annotation_mode: "blind",
              overlap_ratio: 0.2,
              overlap_reviewers: 2,
              case_count: 20,
              assignment_count: 24,
              status: "active",
              created_by: "jasperchen",
              update_count: 1,
              selected_members: ["jasperchen", "alice"],
              members: [{ username: "jasperchen", base: 10, cross: 2, total: 12 }],
              progress: { total: 24, completed: 12, partial: 2, pending: 10 },
            },
          ],
          eligible_members: [
            { username: "jasperchen", role: "admin" },
            { username: "alice", role: "labeler" },
          ],
          name_suggestion: { llm_available: true },
        };
      } else if (url.includes("/api/intent-summary")) {
        body = {
          case_count: 42,
          annotated_cases: 18,
          complete_records: 15,
          agreement: { comparable_cases: 5, matching_cases: 4 },
          items: [],
          total: 0,
          page: 1,
          page_size: 20,
          owners: ["jasperchen"],
          experiments: [],
        };
      } else if (url.includes("/api/campaigns")) {
        body = { items: [{ id: "camp-1", name: "Demo Campaign", purpose: "labeling", lifecycle: "active", progress: { completed_issue_count: 5, assigned_issue_count: 10 } }] };
      } else if (url.includes("/api/prediction-batches/config")) {
        body = { providers: { active_provider_id: "kylin", providers: [{ id: "kylin", display_name: "Kylin", enabled: true }] }, max_issues: 50 };
      } else if (url.includes("/api/prediction-batches/models")) {
        body = { status: "ready", default_model_id: "qwen3.5", models: [{ id: "qwen3.5", display_name: "Qwen3.5", validation_status: "validated" }] };
      } else if (url.includes("/api/prediction-batches/prompts")) {
        body = { default_prompt_id: "p1", items: [{ id: "p1", display_name: "Default Prompt", is_default: true, template: "Classify stuck" }] };
      } else if (url.includes("/api/prediction-batches")) {
        body = { items: [], total: 0, requesters: [] };
      } else if (url.includes("/api/trail-attribute-update/preview")) {
        body = { items: [], baselines: ["0508"], write_status: "ready" };
      } else if (url.includes("/api/model-runs")) {
        body = { items: [], baseline_issue_count: 1071 };
      } else if (url.includes("/api/intent-cases/next")) {
        body = {
          dataset_id: "intent_0206",
          case_id: "cn28896325",
          issue_id: "cn28896325",
          case_index: 1,
          total_cases: 10,
          frames: [{ frame_index: 0, camera_url: "", bev_url: "" }],
          my_annotation: { frame_labels: {} },
        };
      }
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
  });

  it("resolves all canonical and legacy alias routes", () => {
    expect(resolvePageFromLocation("/review")).toBe("review");
    expect(resolvePageFromLocation("/")).toBe("review");
    expect(resolvePageFromLocation("/inference")).toBe("prediction");
    expect(resolvePageFromLocation("/import")).toBe("runs");
    expect(resolvePageFromLocation("/labeling-experiments")).toBe("labeling-new-task");
    expect(resolvePageFromLocation("/multi-run-evaluation")).toBe("run-collections");
    expect(resolvePageFromLocation("/daily-review")).toBe("daily-review");
    expect(resolvePageFromLocation("/intent-experiments")).toBe("intent-experiments");
    expect(resolvePageFromLocation("/trail-update-history")).toBe("trail-history");
  });

  it("renders AppShell with bilingual toggle, theme toggle, sidebar nav, and zero native selects", async () => {
    const { container } = render(wrap(<AppShell><div>PageBody</div></AppShell>));
    await waitFor(() => expect(screen.getByText("jasperchen")).toBeInTheDocument());
    await waitFor(() => expect(document.getElementById("statIssues")?.textContent).toBe("1,071"));
    expect(document.getElementById("statFailures")?.textContent).toBe("12");
    expect(document.getElementById("statReviewed")?.textContent).toBe("7");
    expect(document.getElementById("statSharedLabels")?.textContent).toBe("260");
    expect(document.getElementById("statPredictions")?.textContent).toBe("100");
    expect(container.querySelectorAll("select").length).toBe(0);

    // Toggle language ZH -> EN
    const langBtn = document.getElementById("languageToggleButton")!;
    fireEvent.click(langBtn);
    expect(document.documentElement.dataset.uiLang).toBe("en");
    expect(screen.getByRole("heading", { name: "Failure Review" })).toBeInTheDocument();

    // Toggle theme Dark -> Light
    const themeBtn = document.getElementById("themeToggleButton")!;
    fireEvent.click(themeBtn);
    expect(document.documentElement.dataset.colorTheme).toBe("light");
  });

  it("builds pure TS cron graph model without legacy bridge", () => {
    const model = buildCronGraphModel(
      {
        incremental: {
          enabled: true,
          families: ["20261113"],
          versions: [
            {
              family: "20261113",
              states_status: "ready",
              states: { inferred: 5, published: 4, ready: 1 },
              media: { selected: 10, verified: 8, triple_verified: 7, camera_verified: 9, bev_verified: 8, closeup: { receipt_status: "ready", verified: 7 } },
              planning_text: { status: "ready", selected: 10, with_frames: 8, collected: 8, partial_source: 0, failed: 0, pending: 2 },
            },
          ],
        },
      },
      { selectedVersion: "20261113", lang: "en", theme: "light" },
    );
    expect(model.lanes.length).toBe(3);
    expect(model.lanes[0].nodes.length).toBeGreaterThanOrEqual(6);
    expect(model.edges.length).toBeGreaterThan(10);
  });

  it("renders DailyReviewPage, TrailHistoryPage, IntentExperimentsPage (with 062 edit modal), IntentSummaryPage, CampaignsPage, PredictionPage, TrailUpdatePage, and RunsPage with zero native selects", async () => {
    const cases: Array<{ name: string; ui: React.ReactElement; waitText: string | RegExp }> = [
      { name: "DailyReview", ui: <DailyReviewPage active lang="en" />, waitText: /cn37631883/ },
      { name: "TrailHistory", ui: <TrailHistoryPage active lang="en" selectedBaselines={["0508"]} />, waitText: "Details / Restore" },
      { name: "IntentExperiments", ui: <IntentExperimentsPage active lang="en" />, waitText: "0206 Blind Review" },
      { name: "IntentLabeling", ui: <IntentLabelingPage active lang="en" />, waitText: "Case / Issue ID" },
      { name: "IntentSummary", ui: <IntentSummaryPage active lang="en" />, waitText: "Intent Labeling Summary" },
      { name: "Campaigns", ui: <CampaignsPage active lang="en" selectedBaselines={["0508"]} isAdmin />, waitText: "Demo Campaign" },
      { name: "Prediction", ui: <PredictionPage active lang="en" />, waitText: "Start Batch Prediction" },
      { name: "TrailUpdate", ui: <TrailUpdatePage active lang="en" selectedBaselines={["0508"]} />, waitText: "Review summary" },
      { name: "RunsPage", ui: <RunsPage active lang="en" username="jasperchen" />, waitText: "Import Model Results" },
    ];

    for (const tc of cases) {
      const { container, unmount } = render(wrap(tc.ui));
      await waitFor(() => expect(screen.getByText(tc.waitText)).toBeInTheDocument());
      expect(container.querySelectorAll("select").length, `${tc.name} must have 0 native selects`).toBe(0);
      unmount();
    }
  });

  it("opens converged 062 Protected Reallocation Edit modal on IntentExperimentsPage", async () => {
    render(wrap(<IntentExperimentsPage active lang="en" />));
    await waitFor(() => expect(screen.getByText("0206 Blind Review")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/Protected Reallocation/i)).toBeInTheDocument();
  });
});
