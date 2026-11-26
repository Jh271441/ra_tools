import React from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import {
  WorkSplitItem,
  WorkSplitMember,
  campaignsHistoryHref,
  formatClassicTime,
  formatVersionDatasetTime,
  reviewAssignmentBatchHref,
  reviewAssignmentCanReview,
  reviewAssignmentFilterLabel,
  reviewAssignmentLifecycleLabel,
  reviewAssignmentMemberPending,
  reviewAssignmentModeLabel,
  reviewAssignmentPercent,
  reviewAssignmentSourceHref,
  roleVersionTaskName,
} from "./allocationMath";

export interface BatchCardProps {
  item: WorkSplitItem;
  lang: UiLanguage;
  isAdmin: boolean;
  username: string;
  verified: boolean;
  runNameLookup: (runId?: string) => string;
  detailHref?: string;
  onOpenDetail?: (splitId: string) => void;
  onEditAllocation?: (campaignId: string) => void;
  onShareLink: (splitId: string) => void;
}

const MemberCard: React.FC<{ member: WorkSplitMember; lang: UiLanguage }> = ({ member, lang }) => {
  const assigned = Number(member.assigned_count || 0);
  const submitted = Number(member.completed_count || 0);
  const extra = Number(member.extra_completed_count || 0);
  const pending = reviewAssignmentMemberPending(member);
  const completed = assigned - pending;
  const percent = reviewAssignmentPercent(assigned ? completed / assigned : 0);
  const note =
    assigned === 0 && submitted > 0
      ? bilingual(lang, `0 条待处理 · 历史已标 ${submitted}`, `0 pending · ${submitted} prior completed`)
      : extra > 0
        ? bilingual(lang, `${pending} 条待处理 · 另有相交提交 ${extra} 条`, `${pending} pending · +${extra} overlap`)
        : bilingual(lang, `${pending} 条待处理`, `${pending} pending`);
  return (
    <div className="review-assignment-member">
      <div className="review-assignment-member-heading">
        <strong>{member.username || "—"}</strong>
        <span>{`${completed} / ${assigned}`}</span>
      </div>
      <div className="review-assignment-progress-track" aria-label={`${completed} / ${assigned}`}>
        <span style={{ width: `${percent}%` }} />
      </div>
      <small>{note}</small>
    </div>
  );
};

interface ManualBatchCardProps {
  item: WorkSplitItem;
  lang: UiLanguage;
  title: string;
  metadata: string;
  conflictBadge?: React.ReactNode;
  actions: React.ReactNode;
}

function ManualBatchCard({ item, lang, title, metadata, conflictBadge, actions }: ManualBatchCardProps) {
  const percent = reviewAssignmentPercent(item.completion_ratio);
  const isCurrent = reviewAssignmentCanReview(item);
  const status = reviewAssignmentLifecycleLabel({ ...item, is_current: isCurrent }, lang);
  const statusClass = isCurrent ? "is-manual" : "is-superseded";
  const changeNote = Number(item.change_count || 0)
    ? bilingual(lang, `已转派 ${item.change_count} 次`, `${item.change_count} transfers`)
    : bilingual(lang, "尚未转派", "No transfers");

  return (
    <article className="review-assignment-batch" data-review-assignment-batch={item.split_id}>
      <header className="review-assignment-batch-header">
        <div>
          <strong className="review-assignment-batch-title">{title}</strong>
          <span className="review-assignment-batch-meta">{metadata}</span>
          <span className="review-assignment-batch-meta">{reviewAssignmentFilterLabel(item, lang)}</span>
        </div>
        <span className={`review-assignment-status ${statusClass}`}>{status}</span>
      </header>
      <div className="review-assignment-progress">
        <div className="review-assignment-progress-heading">
          <span className="review-assignment-progress-label">
            {bilingual(lang, "整体进度", "Overall progress")}
            {conflictBadge}
          </span>
          <strong>{`${item.completed_count || 0} / ${item.assignment_count || 0} · ${percent}%`}</strong>
        </div>
        <div className="review-assignment-progress-track">
          <span style={{ width: `${percent}%` }} />
        </div>
      </div>
      <div className="review-assignment-member-grid">
        {item.members?.length ? (
          item.members.map((member) => <MemberCard key={member.username} member={member} lang={lang} />)
        ) : (
          <span className="quiet-meta">{bilingual(lang, "没有成员记录", "No member data")}</span>
        )}
      </div>
      <footer className="review-assignment-batch-footer">
        <span>{`${item.total_count || 0} ${bilingual(lang, "个 Issue", "Issues")} · ${changeNote}`}</span>
        <div className="review-assignment-batch-actions">{actions}</div>
      </footer>
    </article>
  );
}

export const BatchCard: React.FC<BatchCardProps> = ({
  item,
  lang,
  isAdmin,
  username,
  verified,
  runNameLookup,
  detailHref,
  onOpenDetail,
  onEditAllocation,
  onShareLink,
}) => {
  const canEdit =
    Boolean(item.split_id) &&
    isAdmin &&
    !item.legacy_read_only &&
    (!item.lifecycle || item.lifecycle === "active") &&
    item.is_current !== false;

  const renderDetailAndEditActions = () => (
    <>
      {canEdit && onEditAllocation && (
        <button
          type="button"
          className="button button-quiet"
          data-edit-task-allocation={item.split_id}
          onClick={() => onEditAllocation(item.split_id)}
        >
          {bilingual(lang, "修改分配", "Edit allocation")}
        </button>
      )}
      {detailHref ? (
        <a className="button button-quiet" href={detailHref}>
          {bilingual(lang, "查看任务明细", "View task detail")}
        </a>
      ) : (
        <button
          className="button button-quiet"
          type="button"
          data-open-review-assignment={item.split_id}
          onClick={() => onOpenDetail?.(item.split_id)}
        >
          {bilingual(lang, "查看任务明细", "View task detail")}
        </button>
      )}
    </>
  );

  const renderTaskLinks = (active: boolean) => {
    if (!active) {
      return (
        <a
          className="button button-quiet"
          href={campaignsHistoryHref({ campaignId: item.split_id, lifecycle: "history" })}
        >
          {bilingual(lang, "查看审计与复核", "View audit and reviews")}
        </a>
      );
    }
    const combined = item.workflow_mode === "model_review_and_case_label";
    return (
      <>
        <a
          className="button button-quiet"
          href={reviewAssignmentBatchHref(item, "review", username, verified)}
        >
          {combined
            ? bilingual(lang, "开始联合复核", "Start combined review")
            : bilingual(lang, "去判错复核", "Open Review")}
        </a>
        <a
          className="button button-quiet"
          href={reviewAssignmentBatchHref(item, "analysis", username, verified)}
        >
          {bilingual(lang, "去原因聚类", "Open analysis")}
        </a>
      </>
    );
  };

  const renderConflictBadge = (target: WorkSplitItem) => {
    const conflicts = Number(target.conflict_count || 0);
    if (!conflicts) {
      return Array.isArray(target.conflict_issue_ids) ? (
        <small>{bilingual(lang, "无待裁决冲突", "No pending conflicts")}</small>
      ) : null;
    }
    const href = reviewAssignmentBatchHref(target, "review", username, verified, {
      issueIds: target.conflict_issue_ids || [],
      labelStates: ["conflict"],
      workAssignee: [],
      taskProgress: [],
    });
    return (
      <a className="review-assignment-conflict-pill" href={href}>
        {bilingual(
          lang,
          `${conflicts} 条相交冲突待裁决`,
          `${conflicts} overlap conflict${conflicts === 1 ? "" : "s"}`,
        )}
      </a>
    );
  };

  if (item.appendable) {
    const percent = reviewAssignmentPercent(item.completion_ratio);
    const active = reviewAssignmentCanReview(item);
    const appending = active && item.actively_appending !== false;
    const statusClass = active ? (appending ? "is-current" : "is-collected") : "is-superseded";
    const statusLabel = active
      ? appending
        ? bilingual(lang, "自动 · 持续追加", "Auto · Appending")
        : bilingual(lang, "自动 · 收集完成", "Auto · Collected")
      : reviewAssignmentLifecycleLabel(item, lang);
    const timeStamp = item.last_target_added_at || item.updated_at;
    const timePrefix = item.last_target_added_at
      ? bilingual(lang, "最近新增", "Last added")
      : bilingual(lang, "最近更新", "Updated");
    const description =
      item.role_cohort ||
      Number(item.reviewers_per_issue || 1) > 1 ||
      Number(item.allocation_group_count || 0) > 0
        ? reviewAssignmentModeLabel(item, lang)
        : bilingual(
            lang,
            "低置信＋抽样 · 单人负责 · 无交叉",
            "Low confidence + sample · Single owner · No overlap",
          );
    return (
      <article className="review-assignment-batch" data-review-assignment-batch={item.split_id}>
        <header className="review-assignment-batch-header">
          <div>
            <strong className="review-assignment-batch-title">
              {roleVersionTaskName(item, lang, runNameLookup)}
            </strong>
            <span className="review-assignment-batch-meta">{description}</span>
            <span className="review-assignment-batch-meta">
              {`${timePrefix} ${formatVersionDatasetTime(timeStamp, lang)} CST`}
            </span>
          </div>
          <span className={`review-assignment-status ${statusClass}`}>{statusLabel}</span>
        </header>
        <div className="review-assignment-progress">
          <div className="review-assignment-progress-heading">
            <span className="review-assignment-progress-label">
              {bilingual(lang, "联合复核进度", "Combined review progress")}
              {renderConflictBadge(item)}
            </span>
            <strong>{`${item.completed_count || 0} / ${item.assignment_count || 0} · ${percent}%`}</strong>
          </div>
          <div className="review-assignment-progress-track">
            <span style={{ width: `${percent}%` }} />
          </div>
        </div>
        <div className="review-assignment-member-grid">
          {(item.members || []).map((member) => (
            <MemberCard key={member.username} member={member} lang={lang} />
          ))}
        </div>
        <footer className="review-assignment-batch-footer">
          <span>{`${item.total_count || 0} ${bilingual(lang, "个案例", "cases")}`}</span>
          <div className="review-assignment-batch-actions">
            {renderTaskLinks(active)}
            {renderDetailAndEditActions()}
            <button
              className="button button-quiet"
              type="button"
              onClick={() => onShareLink(item.split_id)}
            >
              {bilingual(lang, "复制链接", "Copy link")}
            </button>
          </div>
        </footer>
      </article>
    );
  }

  // Manual batch
  const normalized: WorkSplitItem = {
    ...item,
    created_at: item.source_created_at || item.created_at,
    created_by: item.source_created_by || item.created_by,
    filter_snapshot: item.source_filter_snapshot || item.filter_snapshot,
  };
  const isCurrent = reviewAssignmentCanReview(normalized);
  const filterSnap = normalized.filter_snapshot || {};
  const hasSourceFilter =
    isCurrent &&
    Object.keys(filterSnap).some((k) =>
      ["baselines", "baseline_scopes", "comparison_status", "search", "issue_ids"].includes(k),
    );

  return (
    <ManualBatchCard
      item={normalized}
      lang={lang}
      title={`${roleVersionTaskName(normalized, lang, runNameLookup)} · ${formatClassicTime(normalized.created_at)}`}
      metadata={`${normalized.split_id} · ${normalized.created_by || bilingual(lang, "未记录", "Unknown")} · ${reviewAssignmentModeLabel(normalized, lang)}`}
      conflictBadge={renderConflictBadge(normalized)}
      actions={(
        <>
          {hasSourceFilter && (
            <a
              className="button button-quiet"
              href={reviewAssignmentSourceHref({
                ...filterSnap,
                model_run_id: normalized.model_run_id || filterSnap.model_run_id,
              })}
            >
              {bilingual(lang, "查看原筛选", "View source filter")}
            </a>
          )}
          {renderTaskLinks(isCurrent)}
          {renderDetailAndEditActions()}
          <button
            className="button button-quiet"
            type="button"
            onClick={() => onShareLink(normalized.split_id)}
          >
            {bilingual(lang, "复制链接", "Copy link")}
          </button>
        </>
      )}
    />
  );
};
