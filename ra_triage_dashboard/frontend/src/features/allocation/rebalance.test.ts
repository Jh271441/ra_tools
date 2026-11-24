import { describe, expect, it } from "vitest";
import {
  AllocationGroup,
  AllocationMember,
  apportionIntegerCounts,
  moveMemberAcrossGroups,
  normalizeGroupShares,
  rebalanceGroupMembers,
  ruleBasedAssignmentName,
  splitGroupShares,
  validateAllocationGroups,
} from "./rebalance";

describe("allocation rebalance engine (v872-v874 semantics)", () => {
  it("apportions integer counts via Hamilton largest remainder", () => {
    expect(apportionIntegerCounts(10, [1, 1, 1])).toEqual([4, 3, 3]);
    expect(apportionIntegerCounts(100, [25, 25, 25, 25])).toEqual([25, 25, 25, 25]);
    expect(apportionIntegerCounts(7, [0, 0])).toEqual([4, 3]);
  });

  it("splits basis points to exact 100.00% sum", () => {
    const shares = splitGroupShares(10000, [1, 1, 1]);
    expect(shares).toEqual([33.34, 33.33, 33.33]);
    expect(shares.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 2);
  });

  it("preserves previously edited members on sequential 3-member edits (0/50/50 -> 40/25/35)", () => {
    const initial: AllocationMember[] = [
      { name: "alice", review_percent: 0 },
      { name: "bob", review_percent: 50 },
      { name: "carol", review_percent: 50 },
    ];
    // Step 1: edit alice -> 40 (bob & carol split 60 evenly -> 30/30)
    const step1 = rebalanceGroupMembers(initial, 0, 40, [], "percent");
    expect(step1.members.map((m) => m.review_percent)).toEqual([40, 30, 30]);
    expect(step1.pinnedIndices).toEqual([0]);

    // Step 2: edit bob -> 25 (alice stays pinned at 40!, carol absorbs remainder -> 35)
    const step2 = rebalanceGroupMembers(step1.members, 1, 25, step1.pinnedIndices, "percent");
    expect(step2.members.map((m) => m.review_percent)).toEqual([40, 25, 35]);
    expect(step2.pinnedIndices).toEqual([0, 1]);

    // Step 3: edit carol -> 50 (all peers pinned -> releases oldest pinned peer alice; bob stays 25!)
    const step3 = rebalanceGroupMembers(step2.members, 2, 50, step2.pinnedIndices, "percent");
    expect(step3.members.map((m) => m.review_percent)).toEqual([25, 25, 50]);
    expect(step3.pinnedIndices).toEqual([1, 2]);
  });

  it("scales down pinned peers cleanly when edited share + pinned sum overflows 100%", () => {
    const members: AllocationMember[] = [
      { name: "alice", review_percent: 60 },
      { name: "bob", review_percent: 20 },
      { name: "carol", review_percent: 20 },
    ];
    // alice is pinned at 60; editing bob to 80 overflows -> carol=0, alice scales to 20
    const res = rebalanceGroupMembers(members, 1, 80, [0], "percent");
    expect(res.members.map((m) => m.review_percent)).toEqual([20, 80, 0]);
  });

  it("supports count-mode rebalancing with exact integer apportionment", () => {
    const members: AllocationMember[] = [
      { name: "alice", review_percent: 50 },
      { name: "bob", review_percent: 50 },
    ];
    const res = rebalanceGroupMembers(members, 0, 3, [], "count", 10);
    expect(res.members.map((m) => m.review_percent)).toEqual([30, 70]);
  });

  it("handles cross-group moves, empty-group 100%, non-empty 0% + highlightEven, and duplicate rejection", () => {
    const groups: AllocationGroup[] = [
      {
        group_id: "group-1",
        coverage_percent: 100,
        members: [
          { name: "alice", review_percent: 50 },
          { name: "bob", review_percent: 50 },
        ],
      },
      {
        group_id: "group-2",
        coverage_percent: 100,
        members: [{ name: "carol", review_percent: 100 }],
      },
    ];

    // Move alice from group-1 to non-empty group-2 -> alice joins at 0% + highlightEven=true, bob becomes 100%
    const moved = moveMemberAcrossGroups(groups, 0, 0, 1, 1);
    expect(moved.moved).toBe(true);
    expect(moved.groups[0].members).toEqual([{ name: "bob", review_percent: 100 }]);
    expect(moved.groups[1].members).toEqual([
      { name: "carol", review_percent: 100 },
      { name: "alice", review_percent: 0 },
    ]);
    expect(moved.groups[1].highlightEven).toBe(true);

    // Equal split group-2
    const evened = normalizeGroupShares(moved.groups[1].members, true);
    expect(evened.map((m) => m.review_percent)).toEqual([50, 50]);

    // Duplicate move rejected
    const dupGroups: AllocationGroup[] = [
      { group_id: "group-1", coverage_percent: 100, members: [{ name: "alice", review_percent: 100 }] },
      { group_id: "group-2", coverage_percent: 100, members: [{ name: "alice", review_percent: 100 }] },
    ];
    const dup = moveMemberAcrossGroups(dupGroups, 0, 0, 1);
    expect(dup.moved).toBe(false);
    expect(dup.reason).toBe("duplicate");
  });

  it("validates bilingual group rules and builds deterministic fallback names", () => {
    const bad: AllocationGroup[] = [
      { group_id: "group-1", coverage_percent: 100, members: [{ name: "alice", review_percent: 60 }] },
    ];
    expect(validateAllocationGroups(bad, "zh")).toContain("60.00%");
    expect(validateAllocationGroups(bad, "en")).toContain("must equal 100%");

    const name = ruleBasedAssignmentName({
      datasetLabels: ["1113"],
      caseCount: 386,
      reviewersPerIssue: 2,
      overlapRatio: 1,
      memberCount: 4,
      workflowMode: "model_review_and_case_label",
      runName: "qwen3-vl",
      comparison: "mismatch",
    });
    expect(name).toContain("1113");
    expect(name).toContain("联合复核");
    expect(name).toContain("386 Case");
  });
});
