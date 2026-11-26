import { useId, useState } from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { ManualBatchCard } from "./BatchCard";
import {
  formatVersionDatasetTime,
  i18nLocaleTag,
  reviewAssignmentBatchHref,
  reviewAssignmentCanReview,
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

type Panel = "batches" | "conflicts" | "unknown";

interface Historical0821CardProps {
  partition: Historical0821Partition;
  batches: WorkSplitItem[];
  matchedBatches: WorkSplitItem[];
  lang: UiLanguage;
  isAdmin: boolean;
  username: string;
  verified: boolean;
  onOpenDetail: (splitId: string) => void;
  onEditAllocation: (splitId: string) => void;
}

export function Historical0821Card({
  partition, batches, matchedBatches, lang, isAdmin, username, verified, onOpenDetail, onEditAllocation,
}: Historical0821CardProps) {
  const panelId = useId();
  const [panel, setPanel] = useState<Panel | null>();
  const format = new Intl.NumberFormat(i18nLocaleTag(lang));
  const cases = batches.reduce((sum, item) => sum + (item.total_count || 0), 0);
  const assigned = batches.reduce((sum, item) => sum + (item.assignment_count || 0), 0);
  const completed = batches.reduce((sum, item) => sum + (item.completed_count || 0), 0);
  const conflicts = new Set(batches.flatMap((item) => item.conflict_issue_ids || [])).size;
  const unknown = batches.filter((item) => item.filter_snapshot?.partition_value == null);
  const unknownCount = unknown.reduce((sum, item) => sum + (item.total_count || 0), 0);
  const members = new Map<string, WorkSplitMember>();
  for (const batch of batches) {
    for (const member of batch.members || []) {
      const previous = members.get(member.username);
      const assignedCount = (previous?.assigned_count || 0) + (member.assigned_count || 0);
      const completedCount = (previous?.completed_count || 0) + (member.completed_count || 0);
      members.set(member.username, {
        username: member.username,
        assigned_count: assignedCount,
        completed_count: completedCount,
        pending_count: (previous?.pending_count || 0) + (member.pending_count || 0),
        extra_completed_count: (previous?.extra_completed_count || 0) + (member.extra_completed_count || 0),
        completion_ratio: assignedCount ? completedCount / assignedCount : 0,
      });
    }
  }
  const summary: WorkSplitItem = {
    split_id: partition,
    is_current: batches.some(reviewAssignmentCanReview),
    partition_case_counts: { [partition]: cases },
    total_count: cases,
    assignment_count: assigned,
    completed_count: completed,
    completion_ratio: assigned ? completed / assigned : 0,
    change_count: batches.reduce((sum, item) => sum + (item.change_count || 0), 0),
    members: [...members.values()],
  };
  const shown = panel === "conflicts" ? batches.filter((item) => item.conflict_issue_ids?.length)
    : panel === "unknown" ? unknown : matchedBatches;
  const expandedPanel = panel === undefined && matchedBatches.length < batches.length ? "batches" : panel;

  const panelButton = (id: Panel, label: string) => (
    <button
      type="button"
      className="button button-quiet"
      aria-controls={panelId}
      aria-expanded={expandedPanel === id}
      onClick={() => setPanel(expandedPanel === id ? null : id)}
    >
      {label}
    </button>
  );

  return (
    <ManualBatchCard
      item={summary}
      lang={lang}
      title={historical0821Title(partition, lang)}
      metadata={bilingual(lang, `${format.format(batches.length)} 个批次`,
        `${format.format(batches.length)} ${batches.length === 1 ? "batch" : "batches"}`)}
      conflictBadge={conflicts > 0 ? (
        <button
          type="button"
          className="review-assignment-conflict-pill"
          aria-controls={panelId}
          aria-expanded={expandedPanel === "conflicts"}
          onClick={() => setPanel(expandedPanel === "conflicts" ? null : "conflicts")}
        >
          {bilingual(lang, `${format.format(conflicts)} 条相交冲突待裁决`,
            `${format.format(conflicts)} overlap ${conflicts === 1 ? "conflict" : "conflicts"}`)}
        </button>
      ) : <small>{bilingual(lang, "无待裁决冲突", "No pending conflicts")}</small>}
      actions={(
        <>
          {panelButton("batches", bilingual(lang, "查看批次", "View batches"))}
          {unknownCount > 0 && panelButton("unknown", bilingual(lang,
            `ODD 未填写 · ${format.format(unknownCount)} 例`,
            `ODD missing · ${format.format(unknownCount)} ${unknownCount === 1 ? "case" : "cases"}`))}
        </>
      )}
    >
      <ul className="ra-historical-batches" id={panelId} hidden={!expandedPanel}>
        {expandedPanel && shown.map((item) => {
          const conflictCount = item.conflict_issue_ids?.length || 0;
          const date = formatVersionDatasetTime(item.source_created_at, lang);
          const canReview = reviewAssignmentCanReview(item);
          const missingOdd = item.filter_snapshot?.partition_value == null;
          return (
            <li className="ra-historical-batch-row" key={item.split_id}>
              <div>
                <strong>{bilingual(lang, `${date} · ${item.total_count} 例`, `${date} · ${item.total_count} ${item.total_count === 1 ? "case" : "cases"}`)}{missingOdd ? bilingual(lang, " · ODD 未填写", " · ODD missing") : ""}</strong>
                <span className="review-assignment-batch-meta">
                  {bilingual(lang, `${item.completed_count}/${item.assignment_count} 份已完成`, `${item.completed_count}/${item.assignment_count} assignments completed`)}
                </span>
              </div>
              <div className="review-assignment-batch-actions">
                {canReview && panel !== "conflicts" && (
                  <a className="button button-quiet" href={reviewAssignmentBatchHref(item, "review", username, verified)}>
                    {bilingual(lang, "开始联合复核", "Start combined review")}
                  </a>
                )}
                {canReview && conflictCount > 0 && (
                  <a className="button button-quiet" href={reviewAssignmentBatchHref(item, "review", "", false, {
                    issueIds: item.conflict_issue_ids || [], labelStates: ["conflict"], taskProgress: [],
                  })}>
                    {bilingual(lang, `裁决 ${conflictCount} 条冲突`, `Resolve ${conflictCount} ${conflictCount === 1 ? "conflict" : "conflicts"}`)}
                  </a>
                )}
                {isAdmin && canReview && (
                  <button className="button button-quiet" type="button" onClick={() => onEditAllocation(item.split_id)}>
                    {bilingual(lang, "修改分配", "Edit allocation")}
                  </button>
                )}
                <button className="button button-quiet" type="button" onClick={() => onOpenDetail(item.split_id)}>
                  {bilingual(lang, "查看任务明细", "View task detail")}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </ManualBatchCard>
  );
}
