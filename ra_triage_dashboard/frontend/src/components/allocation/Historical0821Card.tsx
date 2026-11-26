import { useId, useState } from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import {
  formatVersionDatasetTime,
  i18nLocaleTag,
  pendingReviewHref,
  reviewAssignmentBatchHref,
  reviewAssignmentCanReview,
  reviewAssignmentPercent,
  WorkSplitItem,
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

type Panel = "batches" | "pending" | "conflicts" | "unknown";

interface Historical0821CardProps {
  partition: Historical0821Partition;
  batches: WorkSplitItem[];
  matchedBatches: WorkSplitItem[];
  lang: UiLanguage;
  isAdmin: boolean;
  onOpenDetail: (splitId: string) => void;
  onEditAllocation: (splitId: string) => void;
}

export function Historical0821Card({
  partition, batches, matchedBatches, lang, isAdmin, onOpenDetail, onEditAllocation,
}: Historical0821CardProps) {
  const panelId = useId();
  const [panel, setPanel] = useState<Panel | null>();
  const format = new Intl.NumberFormat(i18nLocaleTag(lang));
  const cases = batches.reduce((sum, item) => sum + (item.total_count || 0), 0);
  const assigned = batches.reduce((sum, item) => sum + (item.assignment_count || 0), 0);
  const completed = batches.reduce((sum, item) => sum + (item.completed_count || 0), 0);
  const pending = new Set(batches.flatMap((item) => item.pending_issue_ids || [])).size;
  const conflicts = new Set(batches.flatMap((item) => item.conflict_issue_ids || [])).size;
  const unknown = batches.filter((item) => item.filter_snapshot?.partition_value == null);
  const unknownCount = unknown.reduce((sum, item) => sum + (item.total_count || 0), 0);
  const percent = reviewAssignmentPercent(assigned ? completed / assigned : 0);
  const title = historical0821Title(partition, lang);
  const shown = panel === "pending" ? batches.filter((item) => item.pending_issue_ids?.length)
    : panel === "conflicts" ? batches.filter((item) => item.conflict_issue_ids?.length)
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
    <article className="review-assignment-batch" data-review-assignment-batch={partition}>
      <header className="review-assignment-batch-header">
        <div>
          <strong className="review-assignment-batch-title">{title}</strong>
          <span className="review-assignment-batch-meta">
            {bilingual(lang, `${format.format(cases)} 个案例`, `${format.format(cases)} cases`)}
          </span>
        </div>
      </header>
      <div className="review-assignment-progress">
        <div className="review-assignment-progress-heading">
          <span>{bilingual(lang, "联合复核进度", "Combined review progress")}</span>
          <strong>{`${format.format(completed)} / ${format.format(assigned)} · ${percent}%`}</strong>
        </div>
        <div className="review-assignment-progress-track">
          <span style={{ width: `${percent}%` }} />
        </div>
      </div>
      <div className="review-assignment-batch-actions">
        {pending > 0 && panelButton("pending", bilingual(lang,
          `查看剩余 ${format.format(pending)} 个 Issue`,
          `View ${format.format(pending)} pending ${pending === 1 ? "case" : "cases"}`))}
        {conflicts > 0 && panelButton("conflicts", bilingual(lang,
          `${format.format(conflicts)} 条冲突待裁决`,
          `${format.format(conflicts)} ${conflicts === 1 ? "conflict" : "conflicts"} to resolve`))}
        {panelButton("batches", bilingual(lang, "查看批次", "View batches"))}
        {unknownCount > 0 && panelButton("unknown", bilingual(lang,
          `ODD 未填写 · ${format.format(unknownCount)} 例`,
          `ODD missing · ${format.format(unknownCount)} ${unknownCount === 1 ? "case" : "cases"}`))}
      </div>
      <ul className="ra-historical-batches" id={panelId} hidden={!expandedPanel}>
        {expandedPanel && shown.map((item) => {
          const pendingCount = item.pending_issue_ids?.length || 0;
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
                {canReview && pendingCount > 0 && panel !== "conflicts" && (
                  <a className="button button-quiet" href={pendingReviewHref(item)}>
                    {bilingual(lang, `查看剩余 ${pendingCount} 个 Issue`, `View ${pendingCount} pending ${pendingCount === 1 ? "case" : "cases"}`)}
                  </a>
                )}
                {canReview && conflictCount > 0 && panel !== "pending" && (
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
    </article>
  );
}
