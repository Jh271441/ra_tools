import React, { useState } from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { ModalDialog } from "../ui/ModalDialog";
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
  title?: string;
  metadata?: string;
  actionTargets?: WorkSplitItem[];
}

interface BatchAction {
  id: string;
  label: string;
  targets: WorkSplitItem[];
  href?: (target: WorkSplitItem) => string;
  onSelect?: (splitId: string) => void;
  attribute?: "data-edit-task-allocation" | "data-open-review-assignment";
  className?: string;
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
  title,
  metadata,
  actionTargets,
}) => {
  const [selectedAction, setSelectedAction] = useState<string | null>(null);
  const targets = actionTargets ?? [item];
  const active = reviewAssignmentCanReview(item);
  const activeTargets = targets.filter(reviewAssignmentCanReview);
  const canEdit = (target: WorkSplitItem) =>
    Boolean(target.split_id) &&
    isAdmin &&
    !target.legacy_read_only &&
    (!target.lifecycle || target.lifecycle === "active") &&
    target.is_current !== false;
  const getSourceFilter = (target: WorkSplitItem) =>
    target.source_filter_snapshot || target.filter_snapshot || {};
  const savedFilterKeys = ["baselines", "baseline_scopes", "comparison_status", "comparison", "search", "issue_ids"];
  const hasSavedFilter = (target: WorkSplitItem) =>
    savedFilterKeys.some((key) => key in getSourceFilter(target));
  const actions: BatchAction[] = [
    {
      id: "source",
      label: bilingual(lang, "查看原筛选", "View source filter"),
      targets: item.appendable ? [] : activeTargets.filter((target) => actionTargets || hasSavedFilter(target)),
      href: (target) => {
        // Some migrated batches only retain their frozen task membership.
        const filter = actionTargets && !hasSavedFilter(target)
          ? { ...getSourceFilter(target), baselines: target.baseline_ids, work_split_id: target.split_id }
          : getSourceFilter(target);
        return reviewAssignmentSourceHref({ ...filter, model_run_id: target.model_run_id || filter.model_run_id });
      },
    },
    {
      id: "review",
      label: item.workflow_mode === "model_review_and_case_label"
        ? bilingual(lang, "开始联合复核", "Start combined review")
        : bilingual(lang, "去判错复核", "Open Review"),
      targets: activeTargets,
      href: (target) => reviewAssignmentBatchHref(target, "review", username, verified),
    },
    {
      id: "analysis",
      label: bilingual(lang, "去原因聚类", "Open analysis"),
      targets: activeTargets,
      href: (target) => reviewAssignmentBatchHref(target, "analysis", username, verified),
    },
    {
      id: "audit",
      label: bilingual(lang, "查看审计与复核", "View audit and reviews"),
      targets: activeTargets.length ? [] : targets,
      href: (target) => campaignsHistoryHref({ campaignId: target.split_id, lifecycle: "history" }),
    },
    {
      id: "edit",
      label: bilingual(lang, "修改分配", "Edit allocation"),
      targets: onEditAllocation ? targets.filter(canEdit) : [],
      onSelect: onEditAllocation,
      attribute: "data-edit-task-allocation",
    },
    {
      id: "detail",
      label: bilingual(lang, "查看任务明细", "View task detail"),
      targets,
      href: detailHref ? () => detailHref : undefined,
      onSelect: onOpenDetail,
      attribute: detailHref ? undefined : "data-open-review-assignment",
    },
    {
      id: "share",
      label: bilingual(lang, "复制链接", "Copy link"),
      targets,
      onSelect: onShareLink,
    },
  ];
  const conflicts = Number(item.conflict_count || 0);
  const conflictAction: BatchAction = {
    id: "conflicts",
    label: bilingual(lang, `${conflicts} 条相交冲突待裁决`,
      `${conflicts} overlap conflict${conflicts === 1 ? "" : "s"}`),
    targets: targets.filter((target) => Number(target.conflict_count || 0) > 0 || target.conflict_issue_ids?.length),
    href: (target) => reviewAssignmentBatchHref(
      { ...target, filter_snapshot: item.appendable ? target.filter_snapshot : getSourceFilter(target) },
      "review", username, verified, {
        issueIds: target.conflict_issue_ids || [],
        labelStates: ["conflict"],
        workAssignee: [],
        taskProgress: [],
      },
    ),
    className: "review-assignment-conflict-pill",
  };
  const renderTarget = (action: BatchAction, target: WorkSplitItem, inPicker = false) => {
    const className = inPicker ? "button button-quiet" : action.className || "button button-quiet";
    if (action.href) {
      return <a className={className} href={action.href(target)}>{action.label}</a>;
    }
    const attributes = action.attribute ? { [action.attribute]: target.split_id } : {};
    return (
      <button type="button" className={className} {...attributes} onClick={() => {
        if (inPicker) setSelectedAction(null);
        action.onSelect?.(target.split_id);
      }}>
        {action.label}
      </button>
    );
  };
  const renderAction = (action: BatchAction) => {
    if (!action.targets.length) return null;
    if (action.targets.length === 1) return renderTarget(action, action.targets[0]);
    return (
      <button type="button" className={action.className || "button button-quiet"}
        aria-haspopup="dialog" onClick={() => setSelectedAction(action.id)}>
        {action.label}
      </button>
    );
  };
  const conflictBadge = conflicts > 0 ? renderAction(conflictAction) :
    Array.isArray(item.conflict_issue_ids) && <small>{bilingual(lang, "无待裁决冲突", "No pending conflicts")}</small>;
  const footerActions = actions.map((action) => (
    <React.Fragment key={action.id}>{renderAction(action)}</React.Fragment>
  ));

  if (item.appendable) {
    const percent = reviewAssignmentPercent(item.completion_ratio);
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
              {conflictBadge}
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
          <div className="review-assignment-batch-actions">{footerActions}</div>
        </footer>
      </article>
    );
  }

  // Manual batch
  const normalized: WorkSplitItem = {
    ...item,
    created_at: item.source_created_at || item.created_at,
    created_by: item.source_created_by || item.created_by,
    filter_snapshot: getSourceFilter(item),
  };
  const pickerAction = [...actions, conflictAction].find((action) => action.id === selectedAction);

  return (
    <>
      <ManualBatchCard
        item={normalized}
        lang={lang}
        title={title ?? `${roleVersionTaskName(normalized, lang, runNameLookup)} · ${formatClassicTime(normalized.created_at)}`}
        metadata={metadata ?? `${normalized.split_id} · ${normalized.created_by || bilingual(lang, "未记录", "Unknown")} · ${reviewAssignmentModeLabel(normalized, lang)}`}
        conflictBadge={conflictBadge}
        actions={footerActions}
      />
      {pickerAction && (
        <ModalDialog open title={`${pickerAction.label} · ${bilingual(lang, "选择批次", "Select batch")}`}
          lang={lang} onClose={() => setSelectedAction(null)}>
          <ul className="ra-historical-batches">
            {pickerAction.targets.map((target) => {
              const date = formatClassicTime(target.source_created_at || target.created_at);
              const count = target.total_count ?? 0;
              const missingOdd = target.filter_snapshot?.partition_value == null;
              return (
                <li className="ra-historical-batch-row" key={target.split_id}>
                  <div>
                    <strong>{`${date} · ${bilingual(lang, `${count} 例`, `${count} ${count === 1 ? "case" : "cases"}`)}`}</strong>
                    {missingOdd && <span className="review-assignment-batch-meta">{bilingual(lang, "ODD 未填写", "ODD missing")}</span>}
                    <span className="review-assignment-batch-meta">
                      {`${target.completed_count || 0} / ${target.assignment_count || 0} · ${bilingual(lang, "已完成", "completed")}`}
                    </span>
                  </div>
                  {renderTarget(pickerAction, target, true)}
                </li>
              );
            })}
          </ul>
        </ModalDialog>
      )}
    </>
  );
};
