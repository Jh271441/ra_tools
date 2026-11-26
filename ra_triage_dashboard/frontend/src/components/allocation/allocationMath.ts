import { bilingual, UiLanguage, withWorkbenchBase } from "../../bridge/useWorkbenchBridge";

export interface AllocationMember {
  name: string;
  review_percent: number | null;
}

export interface AllocationGroup {
  group_id: string;
  coverage_percent: number | null;
  coverage_strategy: "overlap" | "fill";
  members: AllocationMember[];
}

export interface CrossGroupRuleMember {
  group_id: string;
  name: string;
}

export interface CrossGroupRule {
  members: CrossGroupRuleMember[];
  issue_ids: string[];
  count: number | null;
}

export interface AllocationDraft {
  groups: AllocationGroup[];
  cross_groups: CrossGroupRule[];
  pairing_mode: "orthogonal" | "paired" | "custom";
  ruleScopes: Array<"count" | "cases">;
  inputUnit: "percent" | "count";
  quota_basis?: "remaining" | "total";
}

export interface AccessUserItem {
  username: string;
  role: string;
  display_name?: string;
}

export interface GroupCoverageMember {
  name: string;
  total: number;
  completed: number;
  movable?: number;
}

export interface GroupCoverageGroup {
  group_id: string;
  members: GroupCoverageMember[];
  union_completed?: number;
  retained_slots?: number;
}

export interface GroupCoverageData {
  case_count: number;
  active_slots?: number;
  groups: GroupCoverageGroup[];
  combinations: Array<{ owners: Array<string | null>; count: number }>;
}

export interface AllocationConvergence {
  case_count: number;
  union_completed_cases: number;
  overlap_completed_cases?: number;
  consensus_cases: number;
  adjudicated_cases: number;
  conflict_cases: number;
  pending_cases: number;
}

export interface AllocationPlanMember {
  name: string;
  before?: number;
  active_before?: number;
  total_after?: number;
  active_after?: number;
  completed?: number;
  active_completed?: number;
  saved_pending?: number;
  pending_after?: number;
  incoming?: number;
  outgoing?: number;
  base_after?: number;
  cross_after?: number;
  requested_percent?: number | null;
  ideal?: number;
  actual_percent?: number;
  pool_role?: string;
  pool_percent?: number | null;
  constrained?: boolean;
}

export interface AllocationPreviewPlan {
  preview_token?: string;
  expires_at?: number;
  total_slots?: number;
  active_slots?: number;
  changed_cases?: number;
  moved_slots?: number;
  completed_slots?: number;
  saved_pending_slots?: number;
  coverage_before?: { cross_cases: number; case_count: number };
  coverage_after?: { cross_cases: number; case_count: number };
  groups?: AllocationGroup[];
  group_coverage?: GroupCoverageData;
  convergence?: AllocationConvergence;
  members?: AllocationPlanMember[];
  cross_groups?: Array<{ members: Array<{ name?: string } | string>; issue_ids: string[] }>;
  changes?: Array<{ issue_id: string; before: string[]; after: string[] }>;
  remaining_assignments?: Array<{
    issue_id: string;
    owner: string;
    reason: "transfer" | "mine" | "label_pending" | "adjudicated" | "saved" | "other_slot" | "pairing";
  }>;
}

export interface AllocationConfig extends AllocationPreviewPlan {
  campaign_id: string;
  name?: string;
  purpose?: string;
  role_required?: boolean;
  editable: boolean;
  appendable?: boolean;
  expected_revision?: number;
  member_count?: number;
  movable_slots?: number;
  coverage?: { cross_cases: number; case_count: number };
  quota_basis?: "remaining" | "total";
  pairing_mode?: "orthogonal" | "paired" | "custom";
  group_rules?: CrossGroupRule[];
  assignees?: Array<{ name: string; review_percent?: number | null }>;
  eligible_members?: AccessUserItem[];
  progress_members?: AllocationPlanMember[];
}

export interface WorkSplitMember {
  username: string;
  assigned_count?: number;
  completed_count?: number;
  pending_count?: number;
  extra_completed_count?: number;
  completion_ratio?: number;
}

export interface WorkSplitItem {
  split_id: string;
  id?: string;
  campaign_name?: string;
  name?: string;
  model_run_id?: string;
  workflow_mode?: string;
  lifecycle?: string;
  is_current?: boolean;
  legacy_read_only?: boolean;
  appendable?: boolean;
  actively_appending?: boolean;
  release_family?: string;
  role_cohort?: string;
  allocation_group_count?: number;
  reviewers_per_issue?: number;
  overlap_ratio?: number;
  total_count?: number;
  assignment_count?: number;
  completed_count?: number;
  pending_count?: number;
  completion_ratio?: number;
  conflict_count?: number;
  conflict_issue_ids?: string[] | null;
  pending_issue_ids?: string[] | null;
  source_split_id?: string | null;
  change_count?: number;
  assigned_to_me?: boolean;
  baseline_ids?: string[];
  baseline_scopes?: string[];
  baselines?: string[];
  partition_case_counts?: Record<string, number> | null;
  created_at?: string;
  source_created_at?: string;
  created_by?: string;
  source_created_by?: string;
  updated_at?: string;
  last_target_added_at?: string;
  filter_snapshot?: Record<string, unknown>;
  source_filter_snapshot?: Record<string, unknown>;
  members?: WorkSplitMember[];
}

export interface WorkSplitDetailRow {
  issue_id: string;
  title?: string;
  scenario?: string;
  assignee: string;
  assignment_kind?: string;
  submitted?: boolean;
  submitted_at?: string | null;
  source_split_id?: string;
  split_model_run_id?: string;
}

export interface WorkSplitDetail extends WorkSplitItem {
  items?: WorkSplitDetailRow[];
  page?: number;
  page_count?: number;
  page_size?: number;
  filtered_count?: number;
  total_filtered?: number;
  additions?: Array<{ created_at?: string; target_added?: number }>;
  changes?: Array<{
    issue_id: string;
    from_assignee: string;
    to_assignee: string;
    changed_by: string;
    changed_at?: string;
  }>;
}

export interface LabelingTaskItem {
  id: string;
  name?: string;
  lifecycle?: string;
  is_current?: boolean;
  legacy_read_only?: boolean;
  member_count?: number;
  reviewers_per_issue?: number;
  overlap_ratio?: number;
  created_by?: string;
  created_at?: string;
  workset_id?: string;
  baseline_scope?: string;
  baseline_scopes?: string[];
  progress?: {
    total?: number;
    resolved?: number;
    conflict?: number;
    assignees?: Array<{ name: string; labeled: number; total: number }>;
  };
}

export interface BilingualMessage {
  zh: string;
  en: string;
}

export function i18nLocaleTag(lang: UiLanguage): string {
  return lang === "en" ? "en-US" : "zh-CN";
}

export function formatClassicTime(value: string | number | null | undefined): string {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString("zh-CN", { hour12: false });
}

export function formatVersionDatasetTime(
  value: string | number | null | undefined,
  lang: UiLanguage,
): string {
  if (!value) return "—";
  const n = Number(value);
  const d = new Date(Number.isFinite(n) && n > 0 ? (n < 1e11 ? n * 1000 : n) : String(value));
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat(lang === "en" ? "en-GB" : "zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

export function newAllocationGroup(groups: AllocationGroup[] = []): AllocationGroup {
  const ids = new Set(groups.map((g) => g.group_id));
  let index = 1;
  while (ids.has(`group-${index}`)) index += 1;
  return {
    group_id: `group-${index}`,
    coverage_percent: 100,
    coverage_strategy: "overlap",
    members: [{ name: "", review_percent: 100 }],
  };
}

export function createInitialAllocationDraft(): AllocationDraft {
  return {
    groups: [newAllocationGroup()],
    cross_groups: [],
    pairing_mode: "orthogonal",
    ruleScopes: [],
    inputUnit: "percent",
  };
}

export function allocationGroupName(index: number, lang: UiLanguage): string {
  return bilingual(lang, `第 ${index + 1} 组`, `Group ${index + 1}`);
}

export function allocationGroupShortBadge(index: number, lang: UiLanguage): string {
  return bilingual(lang, `${index + 1}组`, `G${index + 1}`);
}

export function allocationColorSlot(groupIndex: number, memberIndex: number): number {
  return (groupIndex * 2 + memberIndex) % 4;
}

export function allocationPercentUnits(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value) || value < 0 || value > 100) return null;
  const scaled = value * 100;
  const units = Math.round(scaled);
  return Math.abs(scaled - units) < 1e-7 ? units : null;
}

export function apportionIntegerCounts(total: number, weights: number[]): number[] {
  const intTotal = Math.max(0, Math.round(Number(total) || 0));
  if (!weights.length) return [];
  const sum = weights.reduce((acc, w) => acc + w, 0);
  const divisor = sum || weights.length;
  const parts = weights.map((w, index) => {
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

export function splitGroupShares(total: number, weights: number[]): number[] {
  const sum = weights.reduce((acc, w) => acc + w, 0);
  const divisor = sum || weights.length;
  const portions = weights.map((w, index) => {
    const num = total * (sum ? w : 1);
    return { units: Math.floor(num / divisor), remainder: num % divisor, index };
  });
  const leftover = total - portions.reduce((acc, p) => acc + p.units, 0);
  [...portions]
    .sort((a, b) => b.remainder - a.remainder || a.index - b.index)
    .slice(0, leftover)
    .forEach((p) => {
      p.units += 1;
    });
  return portions.map((p) => p.units / 100);
}

export function currentAllocationGroups(config: AllocationConfig, basis: "total" | "remaining"): AllocationGroup[] {
  const projection = config.group_coverage;
  return (config.groups || []).map((group) => {
    const actual = projection?.groups.find((item) => item.group_id === group.group_id);
    const totals = new Map(actual?.members.map((member) => [member.name, member]));
    const assigned = group.members.map((member) => totals.get(member.name)?.total || 0);
    const movable = group.members.map((member) => totals.get(member.name)?.movable || 0);
    const covered = assigned.reduce((sum, count) => sum + count, actual?.union_completed || 0);
    const weights = basis === "remaining" && movable.some(Boolean) ? movable : assigned;
    const actualShares = weights.some(Boolean) ? splitGroupShares(10000, weights) : undefined;
    return {
      group_id: group.group_id,
      coverage_strategy: group.coverage_strategy === "fill" ? "fill" : "overlap",
      coverage_percent: coveragePercentFromCount(projection?.case_count || 0, covered) ?? group.coverage_percent ?? 100,
      members: group.members.map((member, i) => ({
        name: member.name,
        review_percent: actualShares?.[i] ?? member.review_percent ?? 0,
      })),
    };
  });
}

export function completeGroupShares(members: AllocationMember[], even = false): AllocationMember[] {
  const cloned = members.map((m) => ({ ...m }));
  const selected = cloned.filter((m) => m.name);
  if (!selected.length) return cloned;
  const shares = splitGroupShares(
    10000,
    selected.map((m) => (even ? 1 : allocationPercentUnits(m.review_percent) ?? 0)),
  );
  selected.forEach((m, i) => {
    m.review_percent = shares[i];
  });
  return cloned;
}

export function allocationGroupDenom(
  caseCount: number,
  coverageCount: number | null,
  groupCompleted: number,
  quotaBasis: string,
): number {
  const target = Math.max(0, Math.min(caseCount, Math.round(Number(coverageCount) || 0)));
  if (quotaBasis === "remaining") {
    return Math.max(0, target - Math.max(0, Math.round(Number(groupCompleted) || 0)));
  }
  return target;
}

export function coverageCountFromPercent(
  caseCount: number,
  coveragePercent: number | null | undefined,
): number | null {
  if (!(caseCount > 0) || coveragePercent == null || !Number.isFinite(coveragePercent)) return null;
  return Math.max(1, Math.min(caseCount, Math.round((caseCount * coveragePercent) / 100)));
}

export function coveragePercentFromCount(
  caseCount: number,
  count: number | null | undefined,
): number | null {
  if (!(caseCount > 0) || count == null || !Number.isInteger(count) || count < 1 || count > caseCount) {
    return null;
  }
  return count === caseCount ? 100 : Math.round((count * 10000) / caseCount) / 100;
}

export function computeGroupEqualizeSuggestion(
  members: Array<{ name: string; review_percent: number | null }>,
  { unit = "percent", denom = 100, lang = "zh" }: { unit?: "percent" | "count"; denom?: number; lang?: UiLanguage } = {},
): { shares: number[]; textZh: string; textEn: string } | null {
  const selected = (members || []).filter((p) => p?.name);
  if (selected.length < 2) return null;
  const num = new Intl.NumberFormat(i18nLocaleTag(lang), { maximumFractionDigits: 2 });
  if (unit === "count" && denom > 0) {
    const evenCounts = apportionIntegerCounts(denom, selected.map(() => 1));
    const vals = selected.map((p) => {
      const v = p.review_percent != null ? Number(p.review_percent) : NaN;
      return Number.isInteger(v) && v >= 0 ? v : null;
    });
    const sum = vals.reduce<number>((acc, v) => acc + (v ?? 0), 0);
    const nonNull = vals.filter((v): v is number => v != null);
    const alreadyEven =
      nonNull.length === vals.length && sum === denom && Math.max(...nonNull) - Math.min(...nonNull) <= 1;
    if (alreadyEven) return null;
    const uniform = new Set(evenCounts).size === 1;
    return {
      shares: evenCounts,
      textZh: uniform
        ? `可一键均分：每人 ${num.format(evenCounts[0])} 条`
        : `可一键均分：${selected.map((p, i) => `${p.name} ${num.format(evenCounts[i])} 条`).join(" · ")}`,
      textEn: uniform
        ? `Even split: ${num.format(evenCounts[0])} cases each`
        : `Even split: ${selected.map((p, i) => `${p.name} ${num.format(evenCounts[i])}`).join(" · ")}`,
    };
  }
  const evenShares = splitGroupShares(10000, selected.map(() => 1));
  const units = selected.map((p) => allocationPercentUnits(p.review_percent));
  const alreadyEven = units.every((val, idx) => val != null && val === Math.round(evenShares[idx] * 100));
  if (alreadyEven) return null;
  const uniform = new Set(evenShares).size === 1;
  return {
    shares: evenShares,
    textZh: uniform
      ? `可一键均分：每人 ${num.format(evenShares[0])}%`
      : `可一键均分：${selected.map((p, i) => `${p.name} ${num.format(evenShares[i])}%`).join(" · ")}`,
    textEn: uniform
      ? `Even split: ${num.format(evenShares[0])}% each`
      : `Even split: ${selected.map((p, i) => `${p.name} ${num.format(evenShares[i])}%`).join(" · ")}`,
  };
}

export function groupAllocationSetupError(draft: AllocationDraft | null): BilingualMessage | null {
  const invalid = (v: number | null | undefined) => allocationPercentUnits(v) == null;
  if (
    !draft?.groups?.length ||
    draft.groups.some((g) => !g.members.length || g.members.some((p) => !p.name))
  ) {
    return { zh: "请为每组选择成员。", en: "Select members for each group." };
  }
  if (
    draft.groups.some(
      (g) =>
        invalid(g.coverage_percent) ||
        (g.coverage_percent ?? 0) <= 0 ||
        g.members.some((m) => invalid(m.review_percent)) ||
        g.members.reduce((sum, p) => sum + Math.round((p.review_percent ?? 0) * 100), 0) !== 10000,
    )
  ) {
    return draft.inputUnit === "count"
      ? {
          zh: "请检查覆盖条数，各组的成员条数须分别合计等于该组配额。",
          en: "Check coverage counts and make member counts total each group's quota.",
        }
      : {
          zh: "请检查覆盖率，各组的成员比例须分别合计 100%。",
          en: "Check coverage and make the member shares in each group total 100%.",
        };
  }
  if (draft.groups.some((g) => new Set(g.members.map((p) => p.name)).size !== g.members.length)) {
    return { zh: "同一组内的成员不能重复。", en: "Members must be distinct within each group." };
  }
  const rules = draft.pairing_mode === "custom" ? draft.cross_groups || [] : [];
  if (
    rules.some(
      (rule) =>
        rule.members.length < 2 ||
        new Set(rule.members.map((p) => p.group_id)).size !== rule.members.length ||
        new Set(rule.members.map((p) => p.name)).size !== rule.members.length ||
        Boolean(rule.issue_ids.length) === (rule.count != null) ||
        (rule.count != null && (!Number.isSafeInteger(rule.count) || rule.count < 1)),
    )
  ) {
    return {
      zh: "为每条规则选择不同组的搭档，并填写 Case ID 或数量。",
      en: "Select partners from different groups and enter Case IDs or a count for each rule.",
    };
  }
  return null;
}

export function moveAllocationGroupMember(
  draft: AllocationDraft,
  fromGroupIndex: number,
  fromMemberIndex: number,
  toGroupIndex: number,
  toSlot: number | null,
): {
  moved: boolean;
  reason?: string;
  sameGroup?: boolean;
  memberName?: string;
  targetGroupIndex?: number;
  targetMemberIndex?: number;
  nextDraft?: AllocationDraft;
} {
  const next: AllocationDraft = {
    ...draft,
    groups: draft.groups.map((g) => ({ ...g, members: g.members.map((m) => ({ ...m })) })),
    cross_groups: (draft.cross_groups || []).map((r) => ({
      ...r,
      members: r.members.map((m) => ({ ...m })),
      issue_ids: [...(r.issue_ids || [])],
    })),
    ruleScopes: [...(draft.ruleScopes || [])],
  };
  const sourceGroup = next.groups[fromGroupIndex];
  const targetGroup = next.groups[toGroupIndex];
  if (!sourceGroup || !targetGroup) return { moved: false, reason: "invalid" };
  const sourceMember = sourceGroup.members[fromMemberIndex];
  if (!sourceMember?.name) return { moved: false, reason: "empty" };
  const rawSlot = Number.isInteger(toSlot) ? (toSlot as number) : targetGroup.members.length;
  const clampedSlot = Math.max(0, Math.min(targetGroup.members.length, rawSlot));

  if (fromGroupIndex === toGroupIndex) {
    if (clampedSlot === fromMemberIndex || clampedSlot === fromMemberIndex + 1) {
      return { moved: false, reason: "noop" };
    }
    const [item] = sourceGroup.members.splice(fromMemberIndex, 1);
    const insertIndex = clampedSlot > fromMemberIndex ? clampedSlot - 1 : clampedSlot;
    sourceGroup.members.splice(insertIndex, 0, item);
    return {
      moved: true,
      sameGroup: true,
      memberName: item.name,
      targetGroupIndex: toGroupIndex,
      targetMemberIndex: insertIndex,
      nextDraft: next,
    };
  }

  if (targetGroup.members.some((m) => m.name === sourceMember.name)) {
    return {
      moved: false,
      reason: "duplicate",
      memberName: sourceMember.name,
      targetGroupIndex: toGroupIndex,
    };
  }

  const [item] = sourceGroup.members.splice(fromMemberIndex, 1);
  if (!sourceGroup.members.length) {
    sourceGroup.members.push({ name: "", review_percent: 100 });
  } else {
    sourceGroup.members = completeGroupShares(sourceGroup.members);
  }

  const targetSelected = targetGroup.members.filter((m) => m.name);
  let insertedIndex = 0;
  if (!targetSelected.length) {
    targetGroup.members = [{ name: item.name, review_percent: 100 }];
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
  }

  next.cross_groups.forEach((rule) => {
    rule.members = rule.members.filter(
      (p) => !(p.group_id === sourceGroup.group_id && p.name === item.name),
    );
  });

  return {
    moved: true,
    sameGroup: false,
    memberName: item.name,
    targetGroupIndex: toGroupIndex,
    targetMemberIndex: insertedIndex,
    nextDraft: next,
  };
}

export function assignmentPercent(count: number, total: number, lang: UiLanguage): string {
  return new Intl.NumberFormat(i18nLocaleTag(lang), {
    style: "percent",
    maximumFractionDigits: 2,
  }).format(total ? count / total : 0);
}

export function parseBilingualError(error: unknown, fallbackZh: string, fallbackEn: string): BilingualMessage {
  const err = error as { messages?: BilingualMessage; message?: string } | null;
  if (err?.messages?.zh && err?.messages?.en) return err.messages;
  const msg = typeof err?.message === "string" ? err.message : "";
  const parts = msg.split(" / ");
  if (parts.length === 2) return { zh: parts[0], en: parts[1] };
  if (msg) return { zh: msg, en: msg };
  return { zh: fallbackZh, en: fallbackEn };
}

export interface AssignmentNameContext {
  assignmentKind: "model_review" | "case_labeling";
  baselineIds: string[];
  datasetLabels: string[];
  caseCount: number;
  reviewersPerIssue: number;
  overlapRatio: number;
  memberCount: number;
  workflowMode: string;
  modelRunId: string;
  runName: string;
  comparison: string;
}

export function ruleBasedAssignmentName(context: AssignmentNameContext): string {
  const scope =
    context.datasetLabels
      .map((label) => String(label || "").split("·", 1)[0].trim())
      .filter(Boolean)
      .join("+") || "Dataset";
  const mode =
    context.memberCount <= 0
      ? "待选人员"
      : context.reviewersPerIssue > 1 && context.memberCount > 1 && context.overlapRatio > 0
        ? `${context.reviewersPerIssue}人交叉${Math.round(context.overlapRatio * 100)}%复核`
        : context.reviewersPerIssue === 1
          ? context.memberCount === 1
            ? "单人均分"
            : `${context.memberCount}人均分`
          : `${context.reviewersPerIssue}人复核`;
  const subject =
    context.assignmentKind === "case_labeling"
      ? "Case标注"
      : context.workflowMode === "model_review_and_case_label"
        ? "联合复核"
        : "判错复核";
  const runPart =
    context.assignmentKind === "model_review"
      ? String(context.runName || "").split("·", 1)[0].trim().slice(0, 28)
      : "";
  const comparisonPart =
    context.assignmentKind === "model_review" &&
    !["", "all"].includes(String(context.comparison || "").toLowerCase())
      ? String(context.comparison).toUpperCase()
      : "";
  const suffix = [subject, comparisonPart, mode, String(Math.max(1, context.caseCount)), "Case"]
    .filter(Boolean)
    .join(" ");
  const prefix = [scope, runPart].filter(Boolean).join(" ");
  const available = Math.max(0, 80 - suffix.length - 1);
  return `${prefix.slice(0, available)} ${suffix}`.trim().slice(0, 80);
}

export function reviewAssignmentCanReview(item: Partial<WorkSplitItem> | null | undefined): boolean {
  return Boolean(
    item?.is_current && !item.legacy_read_only && (!item.lifecycle || item.lifecycle === "active"),
  );
}

export function reviewAssignmentLifecycleLabel(
  item: Partial<WorkSplitItem> | null | undefined,
  lang: UiLanguage,
): string {
  const map: Record<string, [string, string]> = {
    superseded: ["已替代", "Superseded"],
    cancelled: ["已取消", "Cancelled"],
    closed: ["已关闭", "Closed"],
    draft: ["草稿", "Draft"],
  };
  const pair = item?.lifecycle ? map[item.lifecycle] : undefined;
  if (pair) return bilingual(lang, pair[0], pair[1]);
  return item?.is_current
    ? bilingual(lang, "手动分配", "Manual")
    : bilingual(lang, "已被后续分配覆盖", "Superseded");
}

export function reviewAssignmentPercent(value: unknown): number {
  const num = Number(value);
  if (!Number.isFinite(num)) return 0;
  return Math.max(0, Math.min(100, Math.round(num * 100)));
}

export function roleVersionTaskName(
  task: Partial<WorkSplitItem>,
  lang: UiLanguage,
  runNameLookup: (runId?: string) => string,
): string {
  if (task.role_cohort) {
    return `${String(task.release_family || "").slice(4)} · ${
      task.role_cohort === "sampling"
        ? bilingual(lang, "抽样集", "Sampling")
        : bilingual(lang, "低置信集", "Low confidence")
    }`;
  }
  if (task.appendable) {
    return `${String(task.release_family || "").slice(4)} · ${bilingual(
      lang,
      "版本联合复核",
      "Version combined review",
    )}`;
  }
  return task.campaign_name || runNameLookup(task.model_run_id);
}

export function reviewAssignmentModeLabel(item: Partial<WorkSplitItem>, lang: UiLanguage): string {
  const groups = Number(item?.allocation_group_count || 0);
  if (groups) {
    const label =
      groups === 1
        ? bilingual(lang, "单组分配", "Single review group")
        : bilingual(lang, `${groups} 个分配组`, `${groups} allocation groups`);
    if (groups > 1 && item.source_split_id) {
      const percent = reviewAssignmentPercent(item.overlap_ratio);
      return (
        label +
        bilingual(lang, ` · 交叉覆盖 ${percent}%`, ` · ${percent}% cross-review coverage`)
      );
    }
    return item.role_cohort === "low"
      ? bilingual(lang, "不含抽样 · ", "Excludes sampling · ") + label
      : label;
  }
  if (item?.role_cohort === "sampling") {
    return bilingual(lang, "RD＋TE 交叉标注", "RD + TE cross-review");
  }
  if (item?.role_cohort === "low") {
    return Number(item.reviewers_per_issue || 1) > 1
      ? bilingual(lang, "不含抽样 · RD＋TE 交叉标注", "Excludes sampling · RD + TE cross-review")
      : bilingual(lang, "不含抽样 · RD 单人标注", "Excludes sampling · One RD per case");
  }
  const reviewers = Math.max(1, Number(item?.reviewers_per_issue || 1));
  if (reviewers <= 1) return bilingual(lang, "单人分配", "Single review");
  return bilingual(
    lang,
    `交叉盲标 ${Math.round(Number(item?.overlap_ratio || 0) * 100)}% · 每个 Issue ${reviewers} 人`,
    `${Math.round(Number(item?.overlap_ratio || 0) * 100)}% cross-review · ${reviewers} reviewers / Issue`,
  );
}

export function reviewAssignmentFilterLabel(item: Partial<WorkSplitItem>, lang: UiLanguage): string {
  const filter =
    item?.filter_snapshot && typeof item.filter_snapshot === "object"
      ? (item.filter_snapshot as Record<string, unknown>)
      : {};
  const values: string[] = [];
  const counts = item?.partition_case_counts;
  if (counts) {
    const partitions: Array<[string, string]> = [
      ["0821-odd2", "ODD2"],
      ["0821-nonodd2", bilingual(lang, "非 ODD2", "Non-ODD2")],
    ];
    const labels = partitions.map(([id, name]) => {
      const n = counts[id];
      return bilingual(lang, `${name} ${n} 例`, `${name} ${n} ${n === 1 ? "case" : "cases"}`);
    });
    const others = (item.baseline_ids || []).filter(
      (id) => !Object.prototype.hasOwnProperty.call(counts, id),
    );
    values.push(
      `${bilingual(lang, "数据集", "Datasets")}: ${[...others, `0821 · ${labels.join(" / ")}`].join(" · ")}`,
    );
  } else if (filter.baselines) {
    values.push(`${bilingual(lang, "数据集", "Datasets")}: ${String(filter.baselines)}`);
  }
  if (filter.comparison_status && filter.comparison_status !== "all") {
    values.push(`${bilingual(lang, "模型结果", "Model")}: ${String(filter.comparison_status)}`);
  }
  if (filter.gt_label) values.push(`GT: ${String(filter.gt_label)}`);
  if (filter.model_label) {
    values.push(`${bilingual(lang, "模型标注", "Model label")}: ${String(filter.model_label)}`);
  }
  if (filter.annotation_author) {
    values.push(`${bilingual(lang, "复核人", "Reviewer")}: ${String(filter.annotation_author)}`);
  }
  if (filter.search) values.push(`${bilingual(lang, "检索", "Search")}: ${String(filter.search)}`);
  return values.length
    ? values.join(" · ")
    : bilingual(lang, "按创建时的筛选结果分配", "Created from the saved Review filter");
}

function normalizeFilterStrList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).map((s) => s.trim()).filter(Boolean);
  return String(value || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function reviewAssignmentBatchHref(
  item: Partial<WorkSplitItem>,
  page: "review" | "analysis",
  currentUsername: string,
  verified: boolean,
  overrides: {
    issue?: string;
    issueIds?: string[];
    runId?: string;
    workAssignee?: string[];
    workSplitId?: string;
    labelStates?: string[];
    taskProgress?: string[];
  } = {},
): string {
  const win = window as unknown as {
    pageUrl?: (target: string, opts?: Record<string, unknown>) => string;
  };
  const filter = (item?.filter_snapshot || {}) as Record<string, unknown>;
  const reviewer = verified ? String(currentUsername || "").trim().toLowerCase() : "";
  const ownTasks =
    Boolean(reviewer) &&
    (item?.assigned_to_me === true ||
      (item?.members || []).some((m) => String(m.username || "").trim().toLowerCase() === reviewer));
  const baselines =
    item?.baseline_ids ||
    item?.baseline_scopes ||
    item?.baselines ||
    filter.baselines ||
    filter.baseline_scopes ||
    [];
  const baseOpts: Record<string, unknown> = {
    runId: overrides.runId ?? item?.model_run_id ?? "",
    comparisonStatus: "all",
    search: "",
    issueIds: overrides.issueIds ?? [],
    gtLabel: [],
    modelLabel: [],
    annotationAuthor: [],
    reviewStatus: [],
    commentState: "all",
    commentSearch: "",
    exclusion: "all",
    workSplitId: overrides.workSplitId ?? item?.split_id ?? "",
    baselines,
    forceBaselines: true,
    taskView: item?.appendable ? "targets" : "",
    taskProgress:
      overrides.taskProgress ??
      (page === "review" && item?.workflow_mode === "model_review_and_case_label"
        ? ["pending"]
        : []),
  };
  const opts: Record<string, unknown> =
    page === "analysis"
      ? {
          ...baseOpts,
          labelStates: [],
          gtRelations: [],
          missingEvidence: [],
          sceneTag: [],
          triggerTag: [],
          egressTag: [],
          workAgreement: "all",
          legacyTag: "",
          page: 1,
          pageSize: 20,
        }
      : {
          ...baseOpts,
          issue: overrides.issue ?? "",
          labelStates: overrides.labelStates ?? [],
          gtRelations: [],
          issueTags: [],
          targetGroup: "",
          workAssignee: overrides.workAssignee ?? (ownTasks ? [reviewer] : []),
          clusterKey: "",
          workflowMode: item?.workflow_mode || "model_review_only",
          casePage: 1,
          casePageSize: 20,
        };
  if (typeof win.pageUrl === "function") {
    return win.pageUrl(page, opts);
  }
  const path = page === "analysis" ? "/review-analysis" : "/review";
  const params = new URLSearchParams();
  if (opts.runId) params.set("run", String(opts.runId));
  params.set("comparison", "all");
  if (opts.workSplitId) params.set("work_split", String(opts.workSplitId));
  if (opts.issue) params.set("issue", String(opts.issue));
  for (const [key, option] of [
    ["issue_ids", opts.issueIds], ["work_assignee", opts.workAssignee],
    ["label_state", opts.labelStates], ["task_progress", opts.taskProgress],
  ] as const) {
    const values = normalizeFilterStrList(option);
    if (values.length) params.set(key, values.join(","));
  }
  if (opts.taskView) params.set("task_view", String(opts.taskView));
  if (opts.workflowMode === "model_review_only") params.set("workflow", "model_only");
  const bs = normalizeFilterStrList(baselines);
  if (bs.length) params.set("baselines", bs.join(","));
  const qs = params.toString();
  return `${withWorkbenchBase(path)}${qs ? `?${qs}` : ""}`;
}

export function pendingReviewHref(item: WorkSplitItem): string {
  return reviewAssignmentBatchHref(item, "review", "", false, {
    issueIds: item.pending_issue_ids || [],
    workAssignee: [],
    taskProgress: ["pending"],
  });
}

export function reviewAssignmentSourceHref(filter: Record<string, unknown> = {}): string {
  const win = window as unknown as {
    pageUrl?: (target: string, opts?: Record<string, unknown>) => string;
  };
  const opts = {
    issue: "",
    runId: String(filter.model_run_id || ""),
    comparisonStatus: String(filter.comparison_status || filter.comparison || "all"),
    search: String(filter.search || ""),
    issueIds: normalizeFilterStrList(filter.issue_ids),
    gtLabel: normalizeFilterStrList(filter.gt_label),
    modelLabel: normalizeFilterStrList(filter.model_label),
    annotationAuthor: normalizeFilterStrList(filter.annotation_author),
    reviewStatus: normalizeFilterStrList(filter.review_status),
    labelStates: normalizeFilterStrList(filter.label_state),
    gtRelations: normalizeFilterStrList(filter.gt_relation),
    commentState: String(filter.comment_state || "all"),
    issueTags: normalizeFilterStrList(filter.issue_tags),
    targetGroup: String(filter.target_group || ""),
    workAssignee: normalizeFilterStrList(filter.work_assignee),
    workSplitId: String(filter.work_split_id || ""),
    clusterKey: String(filter.missing_evidence || ""),
    exclusion: String(filter.exclusion || "all"),
    baselines: filter.baselines || filter.baseline_scopes || [],
    forceBaselines: true,
    workflowMode: "model_review_and_case_label",
    casePage: 1,
    casePageSize: 20,
    taskView: "",
  };
  if (typeof win.pageUrl === "function") {
    return win.pageUrl("review", opts);
  }
  return withWorkbenchBase("/review");
}

export function campaignsHistoryHref(params: Record<string, string>): string {
  const win = window as unknown as {
    pageUrl?: (target: string, opts?: Record<string, unknown>) => string;
  };
  if (typeof win.pageUrl === "function") {
    return win.pageUrl("campaigns", params);
  }
  const sp = new URLSearchParams(params);
  return `${withWorkbenchBase("/campaigns")}?${sp.toString()}`;
}

export function taskAllocationGroupCompleted(
  config: AllocationConfig | null | undefined,
): Record<string, number> {
  const completed: Record<string, number> = {};
  for (const group of config?.group_coverage?.groups || []) {
    completed[group.group_id] =
      group.retained_slots ??
      (group.members || []).reduce((sum, person) => sum + (Number(person.completed) || 0), 0);
  }
  return completed;
}
