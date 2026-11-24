import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";

export type InputUnit = "percent" | "count";
export type QuotaBasis = "remaining" | "total";
export type PairingMode = "orthogonal" | "paired";

export interface AllocationMember {
  name: string;
  review_percent: number;
}

export interface AllocationGroup {
  group_id: string;
  coverage_percent: number;
  coverage_strategy?: string;
  members: AllocationMember[];
  /** Indices of members pinned by manual edits (oldest first). */
  pinnedIndices?: number[];
  /** Hint to highlight Equal Split button after moving a member in at 0%. */
  highlightEven?: boolean;
}

export interface MoveMemberResult {
  moved: boolean;
  reason?: "invalid" | "empty" | "noop" | "duplicate";
  sameGroup?: boolean;
  memberName?: string;
  targetGroupIndex?: number;
  targetMemberIndex?: number;
  groups: AllocationGroup[];
}

export function createNewAllocationGroup(existing: AllocationGroup[]): AllocationGroup {
  const ids = new Set(existing.map((g) => g.group_id));
  let idx = 1;
  while (ids.has(`group-${idx}`)) idx += 1;
  return {
    group_id: `group-${idx}`,
    coverage_percent: 100,
    coverage_strategy: "overlap",
    members: [{ name: "", review_percent: 100 }],
    pinnedIndices: [],
  };
}

/** Hamilton largest-remainder apportionment of an integer total across non-negative weights. */
export function apportionIntegerCounts(total: number, weights: number[]): number[] {
  const intTotal = Math.max(0, Math.round(Number(total) || 0));
  if (!weights.length) return [];
  const safeWeights = weights.map((w) => (Number.isFinite(w) && w > 0 ? w : 0));
  const sum = safeWeights.reduce((acc, w) => acc + w, 0);
  const divisor = sum || safeWeights.length;
  const parts = safeWeights.map((w, index) => {
    const num = intTotal * (sum ? w : 1);
    return { count: Math.floor(num / divisor), rem: num % divisor, index };
  });
  const leftover = intTotal - parts.reduce((acc, p) => acc + p.count, 0);
  [...parts]
    .sort((a, b) => b.rem - a.rem || a.index - b.index)
    .slice(0, leftover)
    .forEach((p) => {
      p.count += 1;
    });
  return parts.map((p) => p.count);
}

/** Distribute basis points (`totalUnits`, e.g. 10000 = 100.00%) into 2-decimal percentages. */
export function splitGroupShares(totalUnits: number, weights: number[]): number[] {
  if (!weights.length) return [];
  const intTotal = Math.max(0, Math.round(totalUnits));
  const safeWeights = weights.map((w) => (Number.isFinite(w) && w > 0 ? w : 0));
  const sum = safeWeights.reduce((acc, w) => acc + w, 0);
  const divisor = sum || safeWeights.length;
  const portions = safeWeights.map((weight, index) => {
    const numerator = intTotal * (sum ? weight : 1);
    return { units: Math.floor(numerator / divisor), remainder: numerator % divisor, index };
  });
  const leftover = intTotal - portions.reduce((acc, p) => acc + p.units, 0);
  [...portions]
    .sort((a, b) => b.remainder - a.remainder || a.index - b.index)
    .slice(0, leftover)
    .forEach((p) => {
      p.units += 1;
    });
  return portions.map((p) => p.units / 100);
}

export function percentToUnits(value: number): number | null {
  if (!Number.isFinite(value) || value < 0 || value > 100) return null;
  const scaled = value * 100;
  const units = Math.round(scaled);
  return Math.abs(scaled - units) < 1e-6 ? units : null;
}

export function coverageCountFromPercent(caseCount: number, coveragePercent: number): number {
  if (caseCount <= 0 || !Number.isFinite(coveragePercent)) return 0;
  return Math.max(1, Math.min(caseCount, Math.round((caseCount * coveragePercent) / 100)));
}

export function coveragePercentFromCount(caseCount: number, count: number): number {
  if (caseCount <= 0 || !Number.isFinite(count)) return 100;
  const clamped = Math.max(1, Math.min(caseCount, Math.round(count)));
  return clamped === caseCount ? 100 : Math.round((clamped * 10000) / caseCount) / 100;
}

export function groupMemberDenom(
  caseCount: number,
  coveragePercent: number,
  groupCompleted: number,
  quotaBasis: QuotaBasis,
): number {
  const target = coverageCountFromPercent(caseCount, coveragePercent);
  if (quotaBasis === "remaining") {
    const movable = Math.max(0, target - Math.max(0, Math.round(groupCompleted || 0)));
    return movable > 0 ? movable : target;
  }
  return target;
}

/** Normalize named members to sum to exactly 100.00% (either evenly or proportionally). */
export function normalizeGroupShares(
  members: AllocationMember[],
  even = false,
): AllocationMember[] {
  const namedIndices = members
    .map((m, idx) => (m.name ? idx : -1))
    .filter((idx) => idx >= 0);
  if (!namedIndices.length) return members.map((m) => ({ ...m }));
  const weights = namedIndices.map((idx) =>
    even ? 1 : (percentToUnits(members[idx].review_percent) ?? 0),
  );
  const shares = splitGroupShares(10000, weights);
  const next = members.map((m) => ({ ...m }));
  namedIndices.forEach((memberIdx, pos) => {
    next[memberIdx] = { ...next[memberIdx], review_percent: shares[pos] };
  });
  return next;
}

/**
 * Pure sequential pin-on-edit share rebalancing (v872 semantics).
 *
 * When editing member `editedIndex` to `newValue`:
 * - Previously edited members (`pinnedHistory`) keep their exact shares as long as
 *   `newValue + sum(pinnedPeers) <= total`.
 * - Free (unpinned) peers absorb the remaining share proportionally.
 * - If all peers are already pinned, release ONLY the oldest pinned peer (`pinnedHistory[0]`).
 * - If `newValue + sum(pinnedPeers) > total`, free peers go to 0 and pinned peers scale down
 *   proportionally to `total - newValue`.
 */
export function rebalanceGroupMembers(
  members: AllocationMember[],
  editedIndex: number,
  newValue: number,
  pinnedHistory: number[],
  unit: InputUnit = "percent",
  denom = 100,
): { members: AllocationMember[]; pinnedIndices: number[] } {
  const next = members.map((m) => ({ ...m }));
  const namedIndices = next
    .map((m, idx) => (m.name ? idx : -1))
    .filter((idx) => idx >= 0);

  if (!namedIndices.includes(editedIndex) || namedIndices.length < 2) {
    if (next[editedIndex] && Number.isFinite(newValue) && newValue >= 0) {
      const pct =
        unit === "count" && denom > 0
          ? Math.min(100, Math.round((newValue * 10000) / denom) / 100)
          : Math.min(100, Math.round(newValue * 100) / 100);
      next[editedIndex] = { ...next[editedIndex], review_percent: pct };
    }
    return { members: next, pinnedIndices: [editedIndex] };
  }

  const peers = namedIndices.filter((idx) => idx !== editedIndex);
  const validHistory = pinnedHistory.filter((idx) => namedIndices.includes(idx) && idx !== editedIndex);
  let pinnedPeers = peers.filter((idx) => validHistory.includes(idx));
  let freePeers = peers.filter((idx) => !validHistory.includes(idx));
  let releasedPeer: number | null = null;

  if (!freePeers.length && pinnedPeers.length) {
    releasedPeer = validHistory[0] ?? pinnedPeers[0];
    pinnedPeers = pinnedPeers.filter((idx) => idx !== releasedPeer);
    freePeers = [releasedPeer];
  }

  const nextPinned = validHistory.filter((idx) => idx !== releasedPeer);
  nextPinned.push(editedIndex);

  if (unit === "count" && denom > 0) {
    const intVal = Math.max(0, Math.min(denom, Math.round(newValue)));
    const currentCounts = apportionIntegerCounts(
      denom,
      namedIndices.map((idx) => percentToUnits(next[idx].review_percent) ?? 0),
    );
    const countMap = new Map<number, number>();
    namedIndices.forEach((idx, pos) => countMap.set(idx, currentCounts[pos] ?? 0));

    const pinnedInitial = pinnedPeers.map((idx) => countMap.get(idx) ?? 0);
    const pinnedSum = pinnedInitial.reduce((acc, v) => acc + v, 0);
    const freeWeights = freePeers.map((idx) => countMap.get(idx) ?? 0);
    const rem = denom - intVal;

    const resultCounts = new Map<number, number>();
    resultCounts.set(editedIndex, intVal);
    if (rem >= pinnedSum) {
      pinnedPeers.forEach((idx, pos) => resultCounts.set(idx, pinnedInitial[pos]));
      const distributed = apportionIntegerCounts(rem - pinnedSum, freeWeights);
      freePeers.forEach((idx, pos) => resultCounts.set(idx, distributed[pos]));
    } else {
      freePeers.forEach((idx) => resultCounts.set(idx, 0));
      const scaled = apportionIntegerCounts(rem, pinnedInitial);
      pinnedPeers.forEach((idx, pos) => resultCounts.set(idx, scaled[pos]));
    }

    const orderedCounts = namedIndices.map((idx) => resultCounts.get(idx) ?? 0);
    const convertedShares = splitGroupShares(10000, orderedCounts);
    namedIndices.forEach((idx, pos) => {
      next[idx] = { ...next[idx], review_percent: convertedShares[pos] };
    });
    return { members: next, pinnedIndices: nextPinned };
  }

  const units = percentToUnits(Math.max(0, Math.min(100, newValue)));
  if (units == null) return { members: next, pinnedIndices: pinnedHistory };

  const pinnedInitial = pinnedPeers.map((idx) => percentToUnits(next[idx].review_percent) ?? 0);
  const pinnedSum = pinnedInitial.reduce((acc, w) => acc + w, 0);
  const freeWeights = freePeers.map((idx) => percentToUnits(next[idx].review_percent) ?? 0);
  const rem = 10000 - units;

  next[editedIndex] = { ...next[editedIndex], review_percent: units / 100 };
  if (rem >= pinnedSum) {
    pinnedPeers.forEach((idx, pos) => {
      next[idx] = { ...next[idx], review_percent: pinnedInitial[pos] / 100 };
    });
    const freeShares = splitGroupShares(rem - pinnedSum, freeWeights);
    freePeers.forEach((idx, pos) => {
      next[idx] = { ...next[idx], review_percent: freeShares[pos] };
    });
  } else {
    freePeers.forEach((idx) => {
      next[idx] = { ...next[idx], review_percent: 0 };
    });
    const pinnedShares = splitGroupShares(rem, pinnedInitial);
    pinnedPeers.forEach((idx, pos) => {
      next[idx] = { ...next[idx], review_percent: pinnedShares[pos] };
    });
  }

  return { members: next, pinnedIndices: nextPinned };
}

/** Pure immutable cross-group & intra-group member move (v872 drag-and-drop & keyboard semantics). */
export function moveMemberAcrossGroups(
  groups: AllocationGroup[],
  fromGroupIndex: number,
  fromMemberIndex: number,
  toGroupIndex: number,
  toSlot?: number,
): MoveMemberResult {
  const cloned: AllocationGroup[] = groups.map((g) => ({
    ...g,
    members: g.members.map((m) => ({ ...m })),
    pinnedIndices: [...(g.pinnedIndices || [])],
  }));
  const sourceGroup = cloned[fromGroupIndex];
  const targetGroup = cloned[toGroupIndex];
  if (!sourceGroup || !targetGroup) return { moved: false, reason: "invalid", groups };
  const sourceMember = sourceGroup.members[fromMemberIndex];
  if (!sourceMember?.name) return { moved: false, reason: "empty", groups };

  const rawSlot = Number.isInteger(toSlot) ? (toSlot as number) : targetGroup.members.length;
  const clampedSlot = Math.max(0, Math.min(targetGroup.members.length, rawSlot));

  if (fromGroupIndex === toGroupIndex) {
    if (clampedSlot === fromMemberIndex || clampedSlot === fromMemberIndex + 1) {
      return { moved: false, reason: "noop", groups };
    }
    const [item] = sourceGroup.members.splice(fromMemberIndex, 1);
    const insertIndex = clampedSlot > fromMemberIndex ? clampedSlot - 1 : clampedSlot;
    sourceGroup.members.splice(insertIndex, 0, item);
    sourceGroup.pinnedIndices = [];
    return {
      moved: true,
      sameGroup: true,
      memberName: item.name,
      targetGroupIndex: toGroupIndex,
      targetMemberIndex: insertIndex,
      groups: cloned,
    };
  }

  if (targetGroup.members.some((m) => m.name === sourceMember.name)) {
    return {
      moved: false,
      reason: "duplicate",
      memberName: sourceMember.name,
      targetGroupIndex: toGroupIndex,
      groups,
    };
  }

  const [item] = sourceGroup.members.splice(fromMemberIndex, 1);
  sourceGroup.pinnedIndices = [];
  if (!sourceGroup.members.length) {
    sourceGroup.members.push({ name: "", review_percent: 100 });
  } else {
    sourceGroup.members = normalizeGroupShares(sourceGroup.members, false);
  }

  const targetNamed = targetGroup.members.filter((m) => m.name);
  let insertedIndex = 0;
  targetGroup.pinnedIndices = [];
  if (!targetNamed.length) {
    targetGroup.members = [{ name: item.name, review_percent: 100 }];
    targetGroup.highlightEven = false;
    insertedIndex = 0;
  } else {
    const slotMember = targetGroup.members[clampedSlot];
    if (slotMember && !slotMember.name) {
      targetGroup.members[clampedSlot] = { name: item.name, review_percent: 0 };
      insertedIndex = clampedSlot;
    } else {
      targetGroup.members.splice(clampedSlot, 0, { name: item.name, review_percent: 0 });
      insertedIndex = clampedSlot;
    }
    targetGroup.highlightEven = true;
  }

  return {
    moved: true,
    sameGroup: false,
    memberName: item.name,
    targetGroupIndex: toGroupIndex,
    targetMemberIndex: insertedIndex,
    groups: cloned,
  };
}

export function validateAllocationGroups(
  groups: AllocationGroup[],
  lang: UiLanguage,
): string | null {
  if (!groups.length) {
    return bilingual(lang, "至少需要 1 个分配组。", "At least one allocation group is required.");
  }
  for (let i = 0; i < groups.length; i += 1) {
    const group = groups[i];
    const gLabel = bilingual(lang, `第 ${i + 1} 组`, `Group ${i + 1}`);
    if (
      !Number.isFinite(group.coverage_percent) ||
      group.coverage_percent <= 0 ||
      group.coverage_percent > 100
    ) {
      return bilingual(
        lang,
        `${gLabel} 覆盖率须在 0%–100% 之间。`,
        `${gLabel} coverage must be between 0% and 100%.`,
      );
    }
    const named = group.members.filter((m) => m.name.trim());
    if (!named.length) {
      return bilingual(
        lang,
        `${gLabel} 请至少选择 1 位成员。`,
        `${gLabel} must have at least one member.`,
      );
    }
    const seen = new Set<string>();
    let totalUnits = 0;
    for (const m of named) {
      if (seen.has(m.name)) {
        return bilingual(
          lang,
          `${gLabel} 中成员 ${m.name} 重复。`,
          `Duplicate member ${m.name} in ${gLabel}.`,
        );
      }
      seen.add(m.name);
      const u = percentToUnits(m.review_percent);
      if (u == null) {
        return bilingual(
          lang,
          `${gLabel} 中 ${m.name} 比例无效。`,
          `Invalid share for ${m.name} in ${gLabel}.`,
        );
      }
      totalUnits += u;
    }
    if (Math.abs(totalUnits - 10000) > 1) {
      return bilingual(
        lang,
        `${gLabel} 成员比例合计为 ${(totalUnits / 100).toFixed(2)}%，需等于 100%。`,
        `${gLabel} shares sum to ${(totalUnits / 100).toFixed(2)}%; must equal 100%.`,
      );
    }
  }
  return null;
}

export function ruleBasedAssignmentName(ctx: {
  datasetLabels: string[];
  caseCount: number;
  reviewersPerIssue: number;
  overlapRatio: number;
  memberCount: number;
  workflowMode: string;
  runName: string;
  comparison: string;
}): string {
  const scope =
    ctx.datasetLabels
      .map((l) => String(l || "").split("·", 1)[0].trim())
      .filter(Boolean)
      .join("+") || "Dataset";
  const mode =
    ctx.memberCount <= 0
      ? "待选人员"
      : ctx.reviewersPerIssue > 1 && ctx.memberCount > 1 && ctx.overlapRatio > 0
        ? `${ctx.reviewersPerIssue}人交叉${Math.round(ctx.overlapRatio * 100)}%复核`
        : ctx.reviewersPerIssue === 1
          ? ctx.memberCount === 1
            ? "单人均分"
            : `${ctx.memberCount}人均分`
          : `${ctx.reviewersPerIssue}人复核`;
  const subject = ctx.workflowMode === "model_review_and_case_label" ? "联合复核" : "判错复核";
  const runPart = String(ctx.runName || "").split("·", 1)[0].trim().slice(0, 28);
  const comp =
    !["", "all"].includes(String(ctx.comparison || "").toLowerCase())
      ? String(ctx.comparison).toUpperCase()
      : "";
  const suffix = [subject, comp, mode, String(Math.max(1, ctx.caseCount)), "Case"]
    .filter(Boolean)
    .join(" ");
  const prefix = [scope, runPart].filter(Boolean).join(" ");
  const available = Math.max(0, 80 - suffix.length - 1);
  return `${prefix.slice(0, available)} ${suffix}`.trim().slice(0, 80);
}
