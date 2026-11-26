import React, { useMemo, useState } from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import {
  AllocationConfig,
  AllocationGroup,
  AllocationPlanMember,
  AllocationPreviewPlan,
  allocationGroupName,
  allocationGroupShortBadge,
  assignmentPercent,
  i18nLocaleTag,
} from "./allocationMath";

export interface AllocationLivePreviewProps {
  plan: AllocationPreviewPlan | null;
  config?: AllocationConfig | null;
  configuredGroups?: AllocationGroup[];
  lang: UiLanguage;
  editing?: boolean;
}

export function exportAllocationChangesCsv(
  plan: AllocationPreviewPlan | null,
  lang: UiLanguage,
): void {
  if (!plan?.changes?.length) return;
  const cell = (value: string) =>
    `"${String(value).replace(/^[=+@-]/, "'$&").replaceAll('"', '""')}"`;
  const rows = [
    [
      bilingual(lang, "Case", "Case"),
      bilingual(lang, "原负责人", "Previous owners"),
      bilingual(lang, "调整后负责人", "New owners"),
    ],
    ...plan.changes.map((r) => [r.issue_id, r.before.join(", "), r.after.join(", ")]),
  ];
  const blob = new Blob(["\ufeff", rows.map((row) => row.map(cell).join(",")).join("\r\n")], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "allocation-changes.csv";
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

const WorkloadBars: React.FC<{
  member: AllocationPlanMember;
  scale: number;
  fmt: (n: number) => string;
  lang: UiLanguage;
}> = ({ member, scale, fmt, lang }) => {
  const retained = (member.completed || 0) + (member.saved_pending || 0);
  const compare = member.total_after != null;
  const renderRow = (label: string, count: number, extraClass = "") => {
    const movable = Math.max(0, count - retained);
    const breakdown = bilingual(
      lang,
      `保留 ${fmt(retained)}，可调整 ${fmt(movable)}`,
      `${fmt(retained)} retained, ${fmt(movable)} movable`,
    );
    return (
      <span className={`allocation-workload-bar ${extraClass}`}>
        <span>{label}</span>
        <span className="allocation-workload-track" role="img" aria-label={breakdown} title={breakdown}>
          <i className="allocation-workload-retained" style={{ width: `${(100 * retained) / scale}%` }} />
          <i className="allocation-workload-movable" style={{ width: `${(100 * movable) / scale}%` }} />
        </span>
        <strong>{fmt(count)}</strong>
      </span>
    );
  };
  return (
    <span className="allocation-workload-bars">
      {renderRow(
        compare ? bilingual(lang, "调整前", "Before") : bilingual(lang, "当前", "Current"),
        member.before ?? 0,
      )}
      {compare && renderRow(bilingual(lang, "调整后", "After"), member.total_after ?? 0, "is-after")}
    </span>
  );
};

export const LegacyAllocationResults: React.FC<{
  preview: AllocationPreviewPlan;
  config?: AllocationConfig | null;
  lang: UiLanguage;
}> = ({ preview, config, lang }) => {
  const num = useMemo(
    () => new Intl.NumberFormat(i18nLocaleTag(lang), { maximumFractionDigits: 2 }),
    [lang],
  );
  const fmt = (n: number) => num.format(n);
  const values = preview.coverage_after;
  const before = preview.coverage_before;
  const counts = values ? `${fmt(values.cross_cases)} / ${fmt(values.case_count)}` : "";
  const members = preview.members || [];
  const beforeTotal = config?.total_slots || 0;
  const scale = Math.max(1, ...members.flatMap((p) => [p.before || 0, p.total_after || 0]));

  const renderComp = (beforeStr: string, afterStr: string) =>
    beforeStr === afterStr ? (
      <strong>{afterStr}</strong>
    ) : (
      <span className="allocation-comparison">
        <span>{beforeStr}</span>
        <span aria-hidden="true">→</span>
        <strong>{afterStr}</strong>
      </span>
    );

  return (
    <>
      <dl className="allocation-preview-facts">
        {values && before && (
          <div>
            <dt>{bilingual(lang, "交叉比例", "Cross-review ratio")}</dt>
            <dd>
              {renderComp(
                assignmentPercent(before.cross_cases, before.case_count, lang),
                assignmentPercent(values.cross_cases, values.case_count, lang),
              )}
              <small>
                {bilingual(
                  lang,
                  `${counts} 个 Case`,
                  `${counts} ${values.case_count === 1 ? "Case" : "Cases"}`,
                )}
              </small>
            </dd>
          </div>
        )}
        <div>
          <dt>{bilingual(lang, "分配总量", "Total workload")}</dt>
          <dd>
            {renderComp(
              fmt(config?.total_slots ?? preview.total_slots ?? 0),
              fmt(preview.total_slots ?? 0),
            )}
          </dd>
        </div>
        <div>
          <dt>{bilingual(lang, "涉及 Case", "Cases affected")}</dt>
          <dd>
            <strong>{fmt(preview.changed_cases ?? 0)}</strong>
            <small>
              {bilingual(
                lang,
                `转入 ${fmt(preview.moved_slots ?? 0)} 份`,
                `${fmt(preview.moved_slots ?? 0)} incoming ${preview.moved_slots === 1 ? "slot" : "slots"}`,
              )}
            </small>
          </dd>
        </div>
        <div>
          <dt>{bilingual(lang, "保留工作", "Work retained")}</dt>
          <dd>
            <strong>{fmt((preview.completed_slots ?? 0) + (preview.saved_pending_slots ?? 0))}</strong>
            <small>
              {bilingual(
                lang,
                `完成 ${fmt(preview.completed_slots ?? 0)} · 保护待办 ${fmt(preview.saved_pending_slots ?? 0)}`,
                `${fmt(preview.completed_slots ?? 0)} completed · ${fmt(preview.saved_pending_slots ?? 0)} protected pending`,
              )}
            </small>
          </dd>
        </div>
      </dl>

      {!preview.changed_cases && (
        <p className="dialog-copy">
          {bilingual(lang, "本次没有 Case 需要改派。", "No Case assignments change.")}
        </p>
      )}

      <h3>{bilingual(lang, "人员工作量", "Member workload")}</h3>
      <div className="allocation-workload-legend">
        <span>
          <i className="allocation-workload-retained" />
          {bilingual(lang, "已保留", "Retained")}
        </span>
        <span>
          <i className="allocation-workload-movable" />
          {bilingual(lang, "可调整待办", "Movable pending")}
        </span>
      </div>
      <div className="allocation-preview-roster">
        {members.map((member) => {
          const saved = config?.assignees?.find((a) => a.name === member.name);
          const requested =
            member.requested_percent == null
              ? bilingual(lang, "均分或数量", "Even or by quota")
              : `${fmt(member.requested_percent)}%`;
          const transfer = [
            member.incoming ? `+${fmt(member.incoming)}` : "",
            member.outgoing ? `−${fmt(member.outgoing)}` : "",
          ]
            .filter(Boolean)
            .join(" / ");
          return (
            <details key={member.name} className="allocation-preview-person">
              <summary>
                <span className="allocation-preview-person-title">
                  <strong>{member.name}</strong>
                  {transfer && <span>{transfer}</span>}
                  <span className="allocation-preview-caret" aria-hidden="true">
                    ›
                  </span>
                </span>
                <WorkloadBars member={member} scale={scale} fmt={fmt} lang={lang} />
              </summary>
              <dl>
                <div>
                  <dt>{bilingual(lang, "已完成", "Completed")}</dt>
                  <dd>
                    <strong>{fmt(member.completed ?? 0)}</strong>
                  </dd>
                </div>
                <div>
                  <dt>{bilingual(lang, "已保护待办", "Protected pending")}</dt>
                  <dd>
                    <strong>{fmt(member.saved_pending ?? 0)}</strong>
                  </dd>
                </div>
                <div>
                  <dt>{bilingual(lang, "转入 / 转出", "In / out")}</dt>
                  <dd>
                    <strong>{`${fmt(member.incoming ?? 0)} / ${fmt(member.outgoing ?? 0)}`}</strong>
                  </dd>
                </div>
                <div>
                  <dt>{bilingual(lang, "基础 / 交叉", "Base / cross-review")}</dt>
                  <dd>
                    <strong>{`${fmt(member.base_after ?? 0)} / ${fmt(member.cross_after ?? 0)}`}</strong>
                  </dd>
                </div>
                <div>
                  <dt>{bilingual(lang, "原配置比例", "Previous configured share")}</dt>
                  <dd>
                    <strong>
                      {saved?.review_percent == null
                        ? bilingual(lang, "未记录", "Not recorded")
                        : `${fmt(saved.review_percent)}%`}
                    </strong>
                    <small>
                      {bilingual(
                        lang,
                        `原实际 ${assignmentPercent(member.before ?? 0, beforeTotal, lang)}`,
                        `Previous actual ${assignmentPercent(member.before ?? 0, beforeTotal, lang)}`,
                      )}
                    </small>
                  </dd>
                </div>
                <div>
                  <dt>{bilingual(lang, "本次目标比例", "Target share")}</dt>
                  <dd>
                    <strong>{requested}</strong>
                    <small>
                      {bilingual(
                        lang,
                        `目标 ${fmt(member.ideal ?? 0)} 份`,
                        `Target ${fmt(member.ideal ?? 0)} slots`,
                      )}
                    </small>
                  </dd>
                </div>
                <div>
                  <dt>{bilingual(lang, "最终实际占比", "Final actual share")}</dt>
                  <dd>
                    <strong>{`${fmt(member.actual_percent ?? 0)}%`}</strong>
                  </dd>
                </div>
                {member.pool_role && member.pool_percent != null && (
                  <div>
                    <dt>
                      {bilingual(
                        lang,
                        `${member.pool_role.toUpperCase()} 池内比例`,
                        `${member.pool_role.toUpperCase()} pool share`,
                      )}
                    </dt>
                    <dd>
                      <strong>{`${fmt(member.pool_percent)}%`}</strong>
                    </dd>
                  </div>
                )}
              </dl>
              {member.constrained && (
                <p className="dialog-copy">
                  {bilingual(
                    lang,
                    "实际工作量受已有记录、每条人数或角色要求约束。",
                    "Saved work, reviewer counts or role requirements constrain the actual workload.",
                  )}
                </p>
              )}
            </details>
          );
        })}
      </div>

      {Boolean(preview.cross_groups?.length || preview.changes?.length) && (
        <div className="allocation-preview-details">
          {Boolean(preview.cross_groups?.length) && (
            <details className="assignment-preview-groups">
              <summary>{bilingual(lang, "已指定的交叉搭档", "Specified cross-review partners")}</summary>
              <ul>
                {preview.cross_groups!.map((g, idx) => (
                  <li key={`cg-${idx}`}>
                    <strong>
                      {g.members
                        .map((m) => (typeof m === "string" ? m : m.name || ""))
                        .join(" + ")}
                    </strong>
                    <div className="quiet-meta">{g.issue_ids.join(", ")}</div>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {Boolean(preview.changes?.length) && (
            <details className="assignment-preview-groups">
              <summary>
                {bilingual(lang, "逐 Case 变更", "Changes by Case")} · {fmt(preview.changes!.length)}
              </summary>
              <ul>
                {preview.changes!.slice(0, 12).map((item) => (
                  <li key={item.issue_id}>
                    <strong>{item.issue_id}</strong>
                    <div className="quiet-meta">
                      {item.before.join(" + ")} → {item.after.join(" + ")}
                    </div>
                  </li>
                ))}
              </ul>
              {preview.changes!.length > 12 && (
                <p className="quiet-meta">
                  {bilingual(lang, "下载 CSV 查看完整变更。", "Download the CSV for all changes.")}
                </p>
              )}
              <button
                type="button"
                className="button button-quiet"
                onClick={() => exportAllocationChangesCsv(preview, lang)}
              >
                {bilingual(lang, "下载变更 CSV", "Download changes CSV")}
              </button>
            </details>
          )}
        </div>
      )}
    </>
  );
};

export const AllocationLivePreview: React.FC<AllocationLivePreviewProps> = ({
  plan,
  config,
  configuredGroups,
  lang,
  editing = false,
}) => {
  const [selectedMap, setSelectedMap] = useState<Record<string, string>>({});
  const [showUnchanged, setShowUnchanged] = useState(false);

  const num = useMemo(
    () => new Intl.NumberFormat(i18nLocaleTag(lang), { maximumFractionDigits: 2 }),
    [lang],
  );
  const fmt = (n: number) => num.format(n);

  const chart = plan?.group_coverage;

  // Fallback when there is no group_coverage chart
  if (!chart?.case_count) {
    if (plan && editing) {
      return <LegacyAllocationResults preview={plan} config={config} lang={lang} />;
    }
    if (config) {
      const members = config.progress_members || [];
      if (!members.length) {
        return (
          <p className="dialog-copy">
            {bilingual(lang, "暂无分配记录。", "There are no assignments yet.")}
          </p>
        );
      }
      const scale = Math.max(1, ...members.map((p) => p.before || 0));
      return (
        <>
          <h3>{bilingual(lang, "当前人员工作量", "Current member workload")}</h3>
          <div className="allocation-workload-legend">
            <span>
              <i className="allocation-workload-retained" />
              {bilingual(lang, "已保留", "Retained")}
            </span>
            <span>
              <i className="allocation-workload-movable" />
              {bilingual(lang, "可调整待办", "Movable pending")}
            </span>
          </div>
          <div className="allocation-preview-roster">
            {members.map((member) => (
              <div key={member.name} className="allocation-preview-person allocation-current-person">
                <strong>{member.name}</strong>
                <WorkloadBars member={member} scale={scale} fmt={fmt} lang={lang} />
              </div>
            ))}
          </div>
        </>
      );
    }
    return null;
  }

  const groups = chart.groups;
  const activeSlots =
    chart.active_slots ??
    plan?.active_slots ??
    plan?.total_slots ??
    groups.reduce(
      (sum, g) => sum + g.members.reduce((t, p) => t + p.total, 0) + (g.union_completed || 0),
      0,
    );
  const activeMembers = new Set(groups.flatMap((g) => g.members.map((p) => p.name)));

  // Prune stale selections
  const validSelectedEntries = Object.entries(selectedMap).filter(([gid, name]) =>
    groups.some((g) => g.group_id === gid && g.members.some((p) => p.name === name)),
  );
  const validSelectedMap = new Map(validSelectedEntries);
  const intersections = groups.map(() => new Map<string, number>());
  let sharedTotal = 0;
  if (validSelectedEntries.length) {
    const criteria = validSelectedEntries.map(
      ([gid, name]) => [groups.findIndex((g) => g.group_id === gid), name] as const,
    );
    for (const { owners, count } of chart.combinations || []) {
      if (criteria.every(([idx, name]) => owners[idx] === name)) {
        sharedTotal += count;
        owners.forEach((name, idx) => {
          if (name) intersections[idx].set(name, (intersections[idx].get(name) || 0) + count);
        });
      }
    }
  }

  const workloadPct = `${fmt((100 * activeSlots) / chart.case_count)}%`;

  const toggleMember = (gid: string, name: string) => {
    setSelectedMap((prev) => {
      const next = { ...prev };
      if (next[gid] === name) delete next[gid];
      else next[gid] = name;
      return next;
    });
  };

  const toggleDiffMember = (name: string) => {
    const existingGid = validSelectedEntries.find(([, person]) => person === name)?.[0];
    const gid =
      existingGid || groups.find((g) => g.members.some((p) => p.name === name))?.group_id;
    if (gid) toggleMember(gid, name);
  };

  // Convergence strip
  const conv = plan?.convergence;
  const showConvergence = Boolean(
    conv &&
      conv.union_completed_cases &&
      ((groups.length === 1 && (conv.overlap_completed_cases || conv.conflict_cases)) ||
        (groups.length > 1 && conv.conflict_cases)),
  );

  // Badge map for diff rows
  const badgeMap = new Map<string, string>();
  const addBadges = (list?: Array<{ group_id: string; members?: Array<{ name?: string }> }>) => {
    (list || []).forEach((g, idx) => {
      const badge = allocationGroupShortBadge(idx, lang);
      (g.members || []).forEach((p) => {
        if (p?.name && !badgeMap.has(p.name)) badgeMap.set(p.name, badge);
      });
    });
  };
  addBadges(groups);
  addBadges(plan?.groups);
  addBadges(config?.groups);

  // Diff calculation
  const diffMembers = plan?.members || [];
  const beforeOf = (p: AllocationPlanMember) => p.before ?? p.active_before ?? 0;
  const afterOf = (p: AllocationPlanMember) => p.total_after ?? p.active_after ?? 0;
  const hasChange = (p: AllocationPlanMember) =>
    Boolean(p.incoming || p.outgoing || beforeOf(p) !== afterOf(p));
  const changed = diffMembers.filter(hasChange);
  const stable = diffMembers.filter((p) => !hasChange(p));
  const visibleDiff = showUnchanged ? [...changed, ...stable] : changed;
  const movedSlots = diffMembers.reduce((sum, p) => sum + (p.incoming || 0), 0);
  const diffScale = Math.max(
    1,
    ...diffMembers.map((p) => Math.max(beforeOf(p), afterOf(p), p.completed || 0) + (p.outgoing || 0)),
  );
  const selectedNames = new Set(validSelectedEntries.map(([, n]) => n));

  return (
    <>
      <div className="allocation-group-meta">
        <p className="allocation-group-summary">
          <strong>{workloadPct}</strong>{" "}
          {bilingual(
            lang,
            `总工作量 · ${fmt(chart.case_count)} 个 Case · ${fmt(activeSlots)} 份`,
            `workload · ${fmt(chart.case_count)} cases · ${fmt(activeSlots)} slots`,
          )}
        </p>
        <div className="allocation-group-legend">
          <span>
            <i className="allocation-legend-done" />
            {bilingual(lang, "已完成", "Completed")}
          </span>
          <span>
            <i className="allocation-legend-pending" />
            {bilingual(lang, "待完成", "Pending")}
          </span>
          <span>
            <i className="allocation-legend-shared" />
            {bilingual(lang, "共同 Case", "Shared")}
          </span>
        </div>
      </div>

      {showConvergence && conv && (
        <div className="allocation-convergence-bar" role="status">
          <span className="allocation-conv-item">
            {bilingual(
              lang,
              `并集已标 ${fmt(conv.union_completed_cases)} / ${fmt(conv.case_count)}`,
              `Set-union done ${fmt(conv.union_completed_cases)} / ${fmt(conv.case_count)}`,
            )}
          </span>
          {conv.consensus_cases > 0 && (
            <span className="allocation-conv-item">
              {bilingual(
                lang,
                `相交一致 ${fmt(conv.consensus_cases)} 例（自动合一）`,
                `${fmt(conv.consensus_cases)} agreed overlaps`,
              )}
            </span>
          )}
          {conv.adjudicated_cases > 0 && (
            <span className="allocation-conv-item">
              {bilingual(
                lang,
                `已裁决 ${fmt(conv.adjudicated_cases)} 例`,
                `${fmt(conv.adjudicated_cases)} adjudicated`,
              )}
            </span>
          )}
          {conv.conflict_cases > 0 && (
            <span className="allocation-conv-item is-conflict">
              {bilingual(
                lang,
                `相交冲突 ${fmt(conv.conflict_cases)} 例待裁决`,
                `${fmt(conv.conflict_cases)} overlap conflicts to adjudicate`,
              )}
            </span>
          )}
          {conv.pending_cases > 0 && (
            <span className="allocation-conv-item">
              {bilingual(
                lang,
                `剩余待标 ${fmt(conv.pending_cases)} 例`,
                `${fmt(conv.pending_cases)} pending`,
              )}
            </span>
          )}
        </div>
      )}

      <section className="allocation-group-plot">
        <div className="allocation-group-axis" aria-hidden="true">
          <span>0%</span>
          <span>50%</span>
          <span>100%</span>
        </div>
        <div
          className="allocation-group-rows"
          data-plot-focused={validSelectedEntries.length > 0 ? "" : undefined}
        >
          {groups.map((group, gIdx) => {
            const gName = allocationGroupName(gIdx, lang);
            const configured =
              configuredGroups?.find((cg) => cg.group_id === group.group_id)?.members.map((m) => m.name).filter(Boolean) ||
              (plan?.groups || [])
                .find((pg) => pg.group_id === group.group_id)
                ?.members.map((m) => m.name)
                .filter(Boolean) ||
              [];
            const orderMap = new Map(configured.map((name, idx) => [name, idx]));
            const orderedMembers = [...group.members].sort(
              (a, b) => (orderMap.get(a.name) ?? 999) - (orderMap.get(b.name) ?? 999),
            );
            const memberTotal = orderedMembers.reduce((sum, m) => sum + m.total, 0);
            const unionDone = group.union_completed || 0;
            const coveredTotal = memberTotal + unionDone;
            const uncovered = Math.max(0, chart.case_count - coveredTotal);
            const parts: Array<{ name: string | null; total: number; completed: number }> = [
              ...orderedMembers,
            ];
            if (unionDone > 0) parts.push({ name: "__union__", total: unionDone, completed: unionDone });
            if (uncovered > 0) parts.push({ name: null, total: uncovered, completed: 0 });
            const coverText = `${bilingual(lang, "覆盖 ", "Cover ")}${fmt(
              (100 * coveredTotal) / chart.case_count,
            )}%`;

            return (
              <div key={group.group_id} className="allocation-group-row">
                <div className="allocation-group-header">
                  <strong>{gName}</strong>
                  <span>{coverText}</span>
                </div>
                <div className="allocation-group-bar" role="group" aria-label={gName}>
                  {parts.map((person, mIdx) => {
                    const isUnion = person.name === "__union__";
                    const isMember = person.name != null && !isUnion;
                    const showShared =
                      isMember && validSelectedEntries.length > 0 && !validSelectedMap.has(group.group_id);
                    const active = isMember && validSelectedMap.get(group.group_id) === person.name;
                    const shared = isMember ? intersections[gIdx].get(person.name!) || 0 : 0;
                    const label = isUnion
                      ? bilingual(lang, "历史并集已标", "Prior union done")
                      : (person.name ?? bilingual(lang, "未覆盖", "Uncovered"));
                    const description =
                      `${label} · ${fmt(person.total)}` +
                      (isMember || isUnion
                        ? ` · ${bilingual(lang, "已完成 ", "Completed ")}${fmt(person.completed)}`
                        : "") +
                      (isMember && validSelectedEntries.length
                        ? ` · ${bilingual(lang, "共同 Case ", "Shared cases ")}${fmt(shared)}`
                        : "");
                    const slotIndex =
                      isMember && orderMap.has(person.name!) ? (orderMap.get(person.name!) as number) : mIdx;
                    const portionPct = `${(100 * person.total) / chart.case_count}%`;
                    const memberColor = `var(--allocation-color-${(gIdx * 2 + slotIndex) % 4})`;
                    const donePct = `${person.total ? (100 * person.completed) / person.total : 0}%`;
                    const sharedPct = `${person.total ? (100 * shared) / person.total : 0}%`;
                    const hasSeam = isMember && person.completed > 0 && person.completed < person.total;
                    const style = {
                      "--portion": portionPct,
                      "--member-color": memberColor,
                      "--done": donePct,
                      "--shared": sharedPct,
                    } as React.CSSProperties;

                    const inner = (
                      <>
                        <span className="allocation-group-fill" aria-hidden="true">
                          <i data-seam={hasSeam ? "true" : undefined} />
                        </span>
                        <span className="allocation-group-segment-label" aria-hidden="true">
                          <span>{label}</span>
                          <span className="allocation-segment-num">
                            {showShared ? (
                              <>
                                <strong>{fmt(shared)}</strong>
                                <small>/{fmt(person.total)}</small>
                              </>
                            ) : (
                              <strong className="is-total">{fmt(person.total)}</strong>
                            )}
                          </span>
                        </span>
                        {shared > 0 && <i className="allocation-group-shared" aria-hidden="true" />}
                      </>
                    );

                    const key = isUnion ? "__union__" : (person.name ?? "__uncovered__");
                    if (isMember) {
                      return (
                        <button
                          key={key}
                          type="button"
                          className="allocation-group-portion"
                          data-shared={shared > 0 ? "" : undefined}
                          aria-label={description}
                          title={description}
                          aria-pressed={active}
                          style={style}
                          onClick={() => toggleMember(group.group_id, person.name!)}
                        >
                          {inner}
                        </button>
                      );
                    }
                    return (
                      <span
                        key={key}
                        className="allocation-group-portion"
                        data-union-covered={isUnion ? "" : undefined}
                        data-uncovered={!isUnion ? "" : undefined}
                        role="img"
                        aria-label={description}
                        title={description}
                        style={style}
                      >
                        {inner}
                      </span>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        <div className="allocation-plot-focus">
          <span className="allocation-plot-focus-text" aria-live="polite">
            {validSelectedEntries.length > 0 ? (
              <>
                <strong>{validSelectedEntries.map(([, n]) => n).join(" × ")}</strong>
                <span>
                  {validSelectedEntries.length > 1
                    ? bilingual(lang, "共同 Case ", "Shared cases ")
                    : bilingual(lang, "负责 Case ", "Assigned cases ")}
                  <strong className="allocation-focus-count">{fmt(sharedTotal)}</strong>
                </span>
              </>
            ) : groups.length > 1 ? (
              bilingual(lang, "点击成员色块查看跨组共同 Case", "Click a member segment to inspect shared cases")
            ) : (
              bilingual(lang, "点击成员色块查看负责的 Case", "Click a member segment to inspect assigned cases")
            )}
          </span>
          {validSelectedEntries.length > 0 && (
            <button
              type="button"
              className="text-button allocation-clear-btn"
              onClick={() => setSelectedMap({})}
            >
              {bilingual(lang, "清除选择", "Clear")}
            </button>
          )}
        </div>
      </section>

      {editing && (
        <section className="allocation-diff">
          <header className="allocation-diff-header">
            <div className="allocation-diff-title">
              <h3>{bilingual(lang, "本次变动", "Changes")}</h3>
              <span>
                {changed.length
                  ? bilingual(
                      lang,
                      `涉及 ${fmt(changed.length)} 人 · 调拨 ${fmt(movedSlots)} 份待办`,
                      `${fmt(changed.length)} changed · ${fmt(movedSlots)} pending moved`,
                    )
                  : bilingual(lang, "0 人变动", "No changes")}
              </span>
            </div>
            <div className="allocation-diff-controls">
              {changed.length > 0 && (
                <span className="allocation-group-legend allocation-diff-legend">
                  <span>
                    <i className="allocation-diff-incoming" />
                    {bilingual(lang, "新转入", "Added")}
                  </span>
                  <span>
                    <i className="allocation-diff-outgoing" />
                    {bilingual(lang, "已转出", "Moved out")}
                  </span>
                </span>
              )}
              {stable.length > 0 && (
                <button
                  type="button"
                  className="button button-secondary allocation-compact-btn"
                  aria-expanded={showUnchanged}
                  onClick={() => setShowUnchanged((v) => !v)}
                >
                  {(showUnchanged
                    ? bilingual(lang, "收起未变动", "Hide unchanged")
                    : bilingual(lang, "展开未变动", "Show unchanged")) +
                    ` (${fmt(stable.length)})`}
                </button>
              )}
            </div>
          </header>

          {!visibleDiff.length ? (
            <p className="allocation-diff-empty">
              {bilingual(
                lang,
                "当前配置未产生人员待办调拨。",
                "No pending assignments move under the current settings.",
              )}
            </p>
          ) : (
            <div className="allocation-diff-list">
              {visibleDiff.map((person) => {
                const bVal = beforeOf(person);
                const aVal = afterOf(person);
                const doneActive = Math.min(aVal, person.completed ?? person.active_completed ?? 0);
                const retainedPending = Math.max(0, aVal - (person.incoming || 0) - doneActive);
                const net = aVal - bVal;
                const delta =
                  net > 0
                    ? `+${fmt(net)}`
                    : net < 0
                      ? `−${fmt(Math.abs(net))}`
                      : [
                          person.incoming ? `+${fmt(person.incoming)}` : "",
                          person.outgoing ? `−${fmt(person.outgoing)}` : "",
                        ]
                          .filter(Boolean)
                          .join("/");
                const sign =
                  net > 0 || (net === 0 && person.incoming)
                    ? "in"
                    : net < 0 || person.outgoing
                      ? "out"
                      : "none";
                const badge = badgeMap.get(person.name);
                const description = `${person.name} · ${fmt(bVal)} → ${fmt(aVal)}${delta ? ` · ${delta}` : ""}`;
                const content = (
                  <>
                    <span className="allocation-diff-person">
                      {badge && <span className="allocation-diff-badge">{badge}</span>}
                      <span className="allocation-diff-name" title={person.name}>
                        {person.name}
                      </span>
                    </span>
                    <span className="allocation-diff-track" aria-hidden="true">
                      {doneActive > 0 && (
                        <i
                          className="allocation-diff-done"
                          style={{ "--part": `${(100 * doneActive) / diffScale}%` } as React.CSSProperties}
                        />
                      )}
                      {retainedPending > 0 && (
                        <i
                          className="allocation-diff-pending"
                          style={
                            { "--part": `${(100 * retainedPending) / diffScale}%` } as React.CSSProperties
                          }
                        />
                      )}
                      {(person.incoming || 0) > 0 && (
                        <i
                          className="allocation-diff-incoming"
                          style={
                            {
                              "--part": `${(100 * (person.incoming || 0)) / diffScale}%`,
                            } as React.CSSProperties
                          }
                        />
                      )}
                      {(person.outgoing || 0) > 0 && (
                        <i
                          className="allocation-diff-outgoing"
                          style={
                            {
                              "--part": `${(100 * (person.outgoing || 0)) / diffScale}%`,
                            } as React.CSSProperties
                          }
                        />
                      )}
                    </span>
                    <span className="allocation-diff-values">
                      <span>
                        {fmt(bVal)} → <strong>{fmt(aVal)}</strong>
                        {(person.completed || 0) > aVal && (
                          <>
                            {" "}
                            <small className="allocation-diff-kept">
                              {bilingual(
                                lang,
                                `已标 ${fmt(person.completed!)}`,
                                `${fmt(person.completed!)} done`,
                              )}
                            </small>
                          </>
                        )}
                      </span>
                      <strong data-diff-sign={sign}>{delta || "—"}</strong>
                    </span>
                  </>
                );
                if (activeMembers.has(person.name)) {
                  return (
                    <button
                      key={person.name}
                      type="button"
                      className="allocation-diff-row"
                      aria-pressed={selectedNames.has(person.name)}
                      aria-label={description}
                      onClick={() => toggleDiffMember(person.name)}
                    >
                      {content}
                    </button>
                  );
                }
                return (
                  <div key={person.name} className="allocation-diff-row">
                    {content}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}
    </>
  );
};
