import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunCollectionsPage } from "./RunCollectionsPage";

const MOCK_RUNS = [
  { id: "run-a", name: "Run A", source_name: "a.json" },
  { id: "run-b", name: "Run B", source_name: "b.json" },
  { id: "run-c", name: "Run C", source_name: "c.json" },
];

const MOCK_COLLECTION_DETAIL = {
  id: "col-1",
  name: "Eval Project 1",
  description: "Multi-run benchmark",
  current_revision: 1,
  metadata_revision: 0,
  history: [
    {
      revision: 1,
      content_sha256: "aaaa1111222233334444",
      members_sha256: "bbbb5555666677778888",
      created_by: "jasperchen",
      created_at: "2026-11-25T10:00:00Z",
      members: [
        {
          run_id: "run-a",
          role: "baseline",
          is_reference: true,
          ordinal: 1,
          available_now: true,
          run: MOCK_RUNS[0],
        },
        {
          run_id: "run-b",
          role: "candidate",
          is_reference: false,
          ordinal: 2,
          available_now: true,
          run: MOCK_RUNS[1],
        },
      ],
    },
  ],
  audit: [
    {
      action: "created",
      revision: 1,
      actor: "jasperchen",
      actor_source: "sso",
      actor_verified: true,
      created_at: "2026-11-25T10:00:00Z",
    },
  ],
};

const MOCK_EVAL_HISTORY = [
  {
    id: "eval-1",
    collection_revision: 1,
    reference_type: "gt",
    context_sha256: "cccc9999000011112222",
    workset_sha256: "dddd3333444455556666",
    created_at: "2026-11-25T11:00:00Z",
  },
];

const MOCK_EVALUATION = {
  id: "eval-1",
  collection_id: "col-1",
  collection_revision: 1,
  collection_sha256: "aaaa111122223333",
  workset_sha256: "dddd333344445555",
  context_sha256: "cccc999900001111",
  scoring_policy_version: "v1",
  scoring_policy_sha256: "eeee777788889999",
  exclusion: { sha256: "ffff000011112222" },
  workset: { workset_id: "ws-1", baseline_scopes: ["version-20261106"] },
  reference: {
    type: "gt",
    id: "gt-snap-1",
    sha256: "9999888877776666",
    snapshot: {
      scope_snapshots: [
        {
          baseline_scope: "version-20261106",
          id: "gt-snap-1",
          content_sha256: "9999888877776666",
          member_count: 100,
        },
      ],
    },
  },
  members: MOCK_COLLECTION_DETAIL.history[0]!.members,
  page: 1,
  page_count: 1,
  total: 1,
  summary: {
    workset_count: 100,
    runs: [
      {
        run_id: "run-a",
        run: MOCK_RUNS[0],
        accuracy: 0.85,
        correct_count: 85,
        reference_denominator: 100,
        coverage: 1,
        pairwise_union_denominator: 100,
        supported_coverage: 1,
        supported_count: 100,
        valid_reference_count: 100,
        absent_count: 0,
        unknown_count: 0,
        available_now: true,
        confusion: [
          { reference_label: "误触发", cells: { 误触发: 45, 正确触发: 5 } },
          { reference_label: "正确触发", cells: { 误触发: 10, 正确触发: 40 } },
        ],
      },
      {
        run_id: "run-b",
        run: MOCK_RUNS[1],
        accuracy: 0.9,
        correct_count: 90,
        reference_denominator: 100,
        coverage: 1,
        pairwise_union_denominator: 100,
        supported_coverage: 1,
        supported_count: 100,
        valid_reference_count: 100,
        absent_count: 0,
        unknown_count: 0,
        available_now: true,
        transitions_vs_reference: { P2P: 82, P2F: 3, F2P: 8, F2F: 7 },
      },
    ],
  },
  items: [
    {
      issue_id: "cn-eval-1",
      excluded: false,
      reference_label: "误触发",
      reference_valid: true,
      shared_label: { state: "agreed", expected_output: "误触发", method: "consensus" },
      predictions: {
        "run-a": { label: "误触发", correct: true, reason: "Reason A" },
        "run-b": { label: "正确触发", correct: false, reason: "Reason B" },
      },
    },
  ],
};

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function mockCollectionsFetch() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method || "GET";
    if (url.includes("/api/model-runs")) {
      return new Response(JSON.stringify({ items: MOCK_RUNS }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/api/run-collections/col-1/revisions") && method === "POST") {
      return new Response(
        JSON.stringify({
          ...MOCK_COLLECTION_DETAIL,
          current_revision: 2,
          history: [
            ...MOCK_COLLECTION_DETAIL.history,
            {
              revision: 2,
              content_sha256: "2222333344445555",
              members_sha256: "6666777788889999",
              created_by: "jasperchen",
              created_at: "2026-11-25T12:00:00Z",
              members: [
                ...MOCK_COLLECTION_DETAIL.history[0]!.members,
                {
                  run_id: "run-c",
                  role: "",
                  is_reference: false,
                  ordinal: 3,
                  available_now: true,
                  run: MOCK_RUNS[2],
                },
              ],
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (url.includes("/api/run-evaluations?collection_id=")) {
      return new Response(JSON.stringify({ items: MOCK_EVAL_HISTORY }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/api/run-collections/col-1")) {
      return new Response(JSON.stringify(MOCK_COLLECTION_DETAIL), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.includes("/api/run-collections")) {
      return new Response(
        JSON.stringify({
          items: [{ id: "col-1", name: "Eval Project 1", current_revision: 1 }],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (url.includes("/api/run-evaluations/eval-1")) {
      return new Response(JSON.stringify(MOCK_EVALUATION), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({}), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
}

describe("RunCollectionsPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState({}, "", "/");
  });

  it("enforces read-only gating when canWrite=false and renders 0 native selects", async () => {
    mockCollectionsFetch();
    const { container } = renderWithClient(
      <RunCollectionsPage
        active
        lang="zh"
        selectedBaselines={["version-20261106"]}
        canWrite={false}
      />,
    );

    const membersList = container.querySelector<HTMLOListElement>("#runCollectionMembers")!;
    expect(await within(membersList).findByText("Run A")).toBeInTheDocument();
    expect(within(membersList).getByText("Run B")).toBeInTheDocument();
    expect(container.querySelectorAll("select").length).toBe(0);
    expect(container.querySelector("#runCollectionReadonlyNote")).toBeInTheDocument();
    expect(container.querySelector("#runCollectionRenameButton")).toBeNull();
    expect(container.querySelector("#runCollectionAppendRevisionButton")).toBeNull();
    expect(container.querySelector("#runCollectionEvaluateButton")).toBeNull();
    expect(container.querySelector("#comparisonSaveCollectionButton")).toBeNull();
  });

  it("supports admin member editing, saving a revision, and loading a frozen evaluation snapshot in EN", async () => {
    const fetchSpy = mockCollectionsFetch();
    const { container } = renderWithClient(
      <RunCollectionsPage
        active
        lang="en"
        selectedBaselines={["version-20261106"]}
        canWrite
      />,
    );

    const membersList = container.querySelector<HTMLOListElement>("#runCollectionMembers")!;
    expect(await within(membersList).findByText("Run A")).toBeInTheDocument();
    expect(container.querySelector("#runCollectionReadonlyNote")).toBeNull();
    expect(container.querySelectorAll("select").length).toBe(0);

    // Add Run C via shared UiSelect and append revision
    const addRunTrigger = screen.getByRole("combobox", { name: "Add Run" });
    fireEvent.click(addRunTrigger);
    fireEvent.click(screen.getByRole("option", { name: /Run C/ }));
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(await within(membersList).findByText("Run C")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save project version" }));
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining("/api/run-collections/col-1/revisions"),
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(await screen.findByText("Appended revision r2.")).toBeInTheDocument();

    // Load frozen evaluation from history
    fireEvent.click(screen.getByText("Evaluation snapshot history"));
    const evalHistoryBtn = await screen.findByRole("button", {
      name: /r1 · gt · cccc999900001111/,
    });
    fireEvent.click(evalHistoryBtn);

    expect(await screen.findByText(/Frozen evaluation snapshot · eval-1/)).toBeInTheDocument();
    expect(screen.getByText("cn-eval-1")).toBeInTheDocument();
    expect(screen.getByText("Confusion matrix")).toBeInTheDocument();
    expect(screen.getByText("Export JSON")).toBeInTheDocument();
  });
});
