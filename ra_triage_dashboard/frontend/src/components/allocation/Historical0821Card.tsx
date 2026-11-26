import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { BatchCard, BatchCardProps } from "./BatchCard";
import {
  i18nLocaleTag,
  reviewAssignmentCanReview,
  reviewAssignmentMemberPending,
  WorkSplitItem,
  WorkSplitMember,
} from "./allocationMath";

export type Historical0821Partition = "0821-odd2" | "0821-nonodd2";

export function historical0821Partition(item: WorkSplitItem): Historical0821Partition | undefined {
  if (!item.filter_snapshot?.partition_parent_campaign_id || item.filter_snapshot.partition_field !== "trip_odd") {
    return undefined;
  }
  const [baseline, ...others] = item.baseline_ids || [];
  if (!others.length && (baseline === "0821-odd2" || baseline === "0821-nonodd2")) return baseline;
}

export function historical0821Title(partition: Historical0821Partition, lang: UiLanguage): string {
  return partition === "0821-odd2"
    ? bilingual(lang, "0821 历史 · ODD2 联合复核", "0821 Historical · ODD2 combined review")
    : bilingual(lang, "0821 历史 · 非 ODD2 联合复核", "0821 Historical · Non-ODD2 combined review");
}

interface Historical0821CardProps extends Omit<BatchCardProps, "item" | "title" | "metadata" | "actionTargets"> {
  partition: Historical0821Partition;
  batches: WorkSplitItem[];
  matchedBatches: WorkSplitItem[];
}

export function Historical0821Card({
  partition, batches, matchedBatches, ...cardProps
}: Historical0821CardProps) {
  const { lang } = cardProps;
  const format = new Intl.NumberFormat(i18nLocaleTag(lang));
  const cases = batches.reduce((sum, item) => sum + (item.total_count || 0), 0);
  const assigned = batches.reduce((sum, item) => sum + (item.assignment_count || 0), 0);
  const completed = batches.reduce((sum, item) => sum + (item.completed_count || 0), 0);
  const conflicts = new Set(matchedBatches.flatMap((item) => item.conflict_issue_ids || []));
  const unknownCount = batches.reduce((sum, item) =>
    sum + (item.filter_snapshot?.partition_value == null ? item.total_count || 0 : 0), 0);
  const members = new Map<string, WorkSplitMember>();
  for (const batch of batches) {
    for (const member of batch.members || []) {
      const previous = members.get(member.username);
      const assignedCount = (previous?.assigned_count || 0) + (member.assigned_count || 0);
      members.set(member.username, {
        username: member.username,
        assigned_count: assignedCount,
        completed_count: (previous?.completed_count || 0) + (member.completed_count || 0),
        pending_count: (previous?.pending_count || 0) + reviewAssignmentMemberPending(member),
        extra_completed_count: (previous?.extra_completed_count || 0) + (member.extra_completed_count || 0),
      });
    }
  }
  const summary: WorkSplitItem = {
    split_id: partition,
    is_current: batches.some(reviewAssignmentCanReview),
    workflow_mode: "model_review_and_case_label",
    conflict_count: conflicts.size,
    conflict_issue_ids: [...conflicts],
    partition_case_counts: { [partition]: cases },
    total_count: cases,
    assignment_count: assigned,
    completed_count: completed,
    completion_ratio: assigned ? completed / assigned : 0,
    change_count: batches.reduce((sum, item) => sum + (item.change_count || 0), 0),
    members: [...members.values()],
  };
  const batchCount = format.format(batches.length);
  const note = [bilingual(lang, `${batchCount} 个批次`,
    `${batchCount} ${batches.length === 1 ? "batch" : "batches"}`)];
  if (unknownCount > 0) {
    const count = format.format(unknownCount);
    note.push(bilingual(lang, `ODD 未填写 ${count} 例`,
      `ODD missing for ${count} ${unknownCount === 1 ? "case" : "cases"}`));
  }

  return (
    <BatchCard
      {...cardProps}
      item={summary}
      title={historical0821Title(partition, lang)}
      metadata={note.join(" · ")}
      actionTargets={matchedBatches}
    />
  );
}
