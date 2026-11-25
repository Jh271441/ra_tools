import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MediaStage, findT0FrameIndex } from "../components/media/MediaStage";
import { IssueDiscussion } from "../components/discussion/IssueDiscussion";
import { ReviewTagSelector } from "../features/review/ReviewTagSelector";
import { inferExpectedOutputFromTags, parseIssueIdsInput } from "../features/review/reviewHelpers";
import { RdResultsPage } from "./RdResultsPage";
import { LabelingSummaryPage } from "./LabelingSummaryPage";
import { LabelingNewTaskPage } from "./LabelingNewTaskPage";
import { CaseLabelingPage } from "./CaseLabelingPage";
import { ReviewPage } from "./ReviewPage";

function wrap(node: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function mockFetch(routes: Record<string, unknown>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    for (const [pattern, payload] of Object.entries(routes)) {
      if (url.includes(pattern)) {
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response(JSON.stringify({ items: [], total: 0 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
}

describe("Wave 3.5 shared components and 5 core workbench islands", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState({}, "", "/manual/review");
    (window as unknown as { __RA_TRIAGE_BASE__?: string }).__RA_TRIAGE_BASE__ = "/manual";
  });

  it("infers expected output from tags and detects conflicts", () => {
    const catalog = [
      { key: "ft_1", group: "false_trigger", section: "interaction_decision", label: "误判障碍物" },
      { key: "ra_1", group: "ra", section: "egress", label: "需要远程绕行" },
    ];
    expect(inferExpectedOutputFromTags(["ft_1"], catalog)).toEqual({
      value: "误触发",
      conflict: false,
      implied: ["误触发"],
    });
    expect(inferExpectedOutputFromTags(["ft_1", "ra_1"], catalog).conflict).toBe(true);
    expect(parseIssueIdsInput("CN100, cn200\ncn100 bad!").ids).toEqual(["cn100", "cn200"]);
  });

  it("renders MediaStage with t0 frame selection and withWorkbenchBase URLs", () => {
    expect(
      findT0FrameIndex([
        { url: "/a", offset_ms: -5000 },
        { url: "/b", offset_ms: 0 },
        { url: "/c", offset_ms: 5000 },
      ]),
    ).toBe(1);

    const { container } = wrap(
      <MediaStage
        issueId="cn37631883"
        lang="zh"
        media={{
          issue_id: "cn37631883",
          assets: {
            frames: [
              { url: "/assets/cn37631883/frame-0-0", offset_ms: -5000, label: "-5s" },
              { url: "/assets/cn37631883/frame-0-4", offset_ms: 0, label: "t0" },
            ],
          },
          camera: {
            frames: [{ url: "/assets/cn37631883/cam-0", offset_ms: 0, label: "t0" }],
          },
        }}
      />,
    );

    const img = container.querySelector("img.detail-media-image") as HTMLImageElement | null;
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toBe("/manual/assets/cn37631883/frame-0-4");
    expect(container.querySelectorAll("select").length).toBe(0);
  });

  it("renders ReviewTagSelector and toggles selected tags", () => {
    const onChange = vi.fn();
    wrap(
      <ReviewTagSelector
        catalog={[
          { key: "env_rain", section: "scene", group: "environment", label: "雨天", label_en: "Rain" },
        ]}
        selectedTags={[]}
        onChange={onChange}
        lang="zh"
      />,
    );
    fireEvent.click(screen.getByText("环境"));
    fireEvent.click(screen.getByText("雨天"));
    expect(onChange).toHaveBeenCalledWith(["env_rain"]);
  });

  it("renders IssueDiscussion thread and mention composer", async () => {
    mockFetch({
      "/api/cases/cn37631883/discussion": {
        count: 1,
        comments: [
          {
            id: 42,
            author: "jasperchen",
            author_verified: true,
            body: "Checked BEV frame at t0.",
            created_at: "2026-11-25T03:00:00Z",
          },
        ],
      },
      "/api/mention-users": { items: [{ username: "alice", display_name: "Alice", enabled: true }] },
    });

    wrap(
      <IssueDiscussion
        open
        issueId="cn37631883"
        lang="en"
        username="jasperchen"
        canWrite
        isAdmin
        onClose={() => {}}
      />,
    );

    await waitFor(() => expect(screen.getByText("Checked BEV frame at t0.")).toBeTruthy());
  });

  it("renders RdResultsPage in both classic RD and Human Publications modes without native selects", async () => {
    mockFetch({
      "/api/rd-results": {
        items: [
          { issue_id: "cn1001", group: "resolved", label: "误触发", authors: ["jasperchen"] },
        ],
        total: 1,
        page: 1,
        pages: 1,
        page_size: 20,
        write_enabled: false,
        counts: { total: 1, resolved: 1, pending: 0, conflict: 0 },
      },
    });

    const { container } = wrap(
      <RdResultsPage active lang="zh" isAdmin selectedBaselines={["0508"]} />,
    );
    await waitFor(() => expect(screen.getByText("cn1001")).toBeTruthy());
    expect(container.querySelectorAll("select").length).toBe(0);
  });

  it("renders LabelingSummaryPage with KPI strip, confusion matrix, and case cards", async () => {
    mockFetch({
      "/api/dashboard-config": { review_tag_catalog: [] },
      "/api/labeling/tasks": { items: [] },
      "/api/labeling/summary": {
        total: 1,
        page: 1,
        pages: 1,
        page_size: 20,
        submitted_states: { resolved: 1, pending: 0, conflict: 0 },
        pairs: [{ gt: "误触发", label: "误触发", count: 1 }],
        items: [
          {
            issue_id: "cn2002",
            title: "Construction detour",
            gt_label: "误触发",
            expected_output: "误触发",
            label_state: "resolved",
            tags: [],
          },
        ],
      },
    });

    const { container } = wrap(
      <LabelingSummaryPage
        active
        lang="en"
        selectedBaselines={["0508"]}
        username="jasperchen"
        canWrite
        isAdmin
      />,
    );
    await waitFor(() => expect(screen.getByText("cn2002")).toBeTruthy());
    expect(container.querySelectorAll("select").length).toBe(0);
  });

  it("renders LabelingNewTaskPage reusing GroupShareEditor & history sections", async () => {
    mockFetch({
      "/api/dashboard-config": { baselines: [{ id: "0508", label: "0508" }] },
      "/api/access-users": { items: [{ username: "jasperchen", access_role: "admin" }] },
      "/api/labeling/cases": { total: 50, items: [] },
      "/api/labeling/tasks": { items: [{ id: "task-1", name: "Task Alpha", member_count: 50 }] },
      "/api/cases/work-splits": { items: [] },
    });

    const { container } = wrap(
      <LabelingNewTaskPage active lang="zh" isAdmin selectedBaselines={["0508"]} />,
    );
    await waitFor(() => expect(screen.getByText("Task Alpha")).toBeTruthy());
    expect(container.querySelectorAll("select").length).toBe(0);
  });

  it("renders CaseLabelingPage gallery and opens case detail cleanly", async () => {
    mockFetch({
      "/api/dashboard-config": {
        baselines: [{ id: "0508", label: "0508", count: 10 }],
        case_labeling: { active_baseline_ids: ["0508"] },
        review_tag_catalog: [],
      },
      "/api/labeling/tasks": { items: [] },
      "/api/labeling/cases?": {
        items: [
          {
            issue_id: "cn3003",
            gt_label: "正确触发",
            expected_output: "正确触发",
            label_state: "resolved",
            thumbnail_url: "/api/case-thumbnails/cn3003",
          },
        ],
        total: 1,
        page: 1,
        pages: 1,
        page_size: 20,
        queue_issue_ids: ["cn3003"],
      },
    });

    const { container } = wrap(
      <CaseLabelingPage
        active
        lang="zh"
        selectedBaselines={["0508"]}
        username="jasperchen"
        canWrite
        isAdmin
      />,
    );
    await waitFor(() => expect(screen.getByText("cn3003")).toBeTruthy());
    const img = container.querySelector("img") as HTMLImageElement | null;
    expect(img?.getAttribute("src")).toBe("/manual/api/case-thumbnails/cn3003");
    expect(container.querySelectorAll("select").length).toBe(0);
  });

  it("renders ReviewPage gallery with thumbnails and zero native selects", async () => {
    mockFetch({
      "/api/dashboard-config": { review_tag_catalog: [], missing_evidence_catalog: [] },
      "/api/model-runs": { items: [{ id: "run-1", name: "Run V1" }] },
      "/api/cases/work-splits": { items: [] },
      "/api/cases?": {
        items: [
          {
            issue_id: "cn37631883",
            gt_label: "误触发",
            thumbnail: { url: "/api/case-thumbnails/cn37631883", label: "t0" },
            prediction: { model_run_id: "run-1", label: "正确触发", comparable: true, mismatch: true },
            label_state: { state: "pending" },
          },
        ],
        total: 1,
        page: 1,
        pages: 1,
        page_size: 20,
        reviewers: ["jasperchen"],
      },
    });

    const { container } = wrap(
      <ReviewPage
        active
        lang="zh"
        selectedBaselines={["version-20261113"]}
        username="jasperchen"
        canWrite
        isAdmin
      />,
    );
    await waitFor(() => expect(screen.getByText("cn37631883")).toBeTruthy());
    const img = container.querySelector("img") as HTMLImageElement | null;
    expect(img?.getAttribute("src")).toBe("/manual/api/case-thumbnails/cn37631883");
    expect(container.querySelectorAll("select").length).toBe(0);
  });
});
