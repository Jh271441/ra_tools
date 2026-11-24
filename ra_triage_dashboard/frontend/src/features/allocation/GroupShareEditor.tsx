import React, { useState } from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { UiSelect } from "../../components/ui/UiSelect";
import {
  AllocationGroup,
  apportionIntegerCounts,
  coverageCountFromPercent,
  coveragePercentFromCount,
  groupMemberDenom,
  InputUnit,
  moveMemberAcrossGroups,
  normalizeGroupShares,
  percentToUnits,
  QuotaBasis,
  rebalanceGroupMembers,
} from "./rebalance";

export interface GroupShareEditorProps {
  groups: AllocationGroup[];
  eligibleMembers: string[];
  lang: UiLanguage;
  unit: InputUnit;
  caseCount: number;
  quotaBasis: QuotaBasis;
  groupCompleted?: Record<string, number>;
  editable?: boolean;
  onChange: (nextGroups: AllocationGroup[], discrete: boolean) => void;
  onBlurFlush?: () => void;
}

export const GroupShareEditor: React.FC<GroupShareEditorProps> = ({
  groups,
  eligibleMembers,
  lang,
  unit,
  caseCount,
  quotaBasis,
  groupCompleted = {},
  editable = true,
  onChange,
  onBlurFlush,
}) => {
  const [dragOrigin, setDragOrigin] = useState<{ gIdx: number; mIdx: number } | null>(null);
  const [dropGroupIdx, setDropGroupIdx] = useState<number | null>(null);
  const [moveNotice, setMoveNotice] = useState<string>("");

  const handleMove = (fromG: number, fromM: number, toG: number, toSlot?: number) => {
    const res = moveMemberAcrossGroups(groups, fromG, fromM, toG, toSlot);
    if (!res.moved) {
      if (res.reason === "duplicate" && res.memberName) {
        setMoveNotice(
          bilingual(
            lang,
            `${res.memberName} 已在第 ${(res.targetGroupIndex ?? 0) + 1} 组中，不能重复加入。`,
            `${res.memberName} is already in Group ${(res.targetGroupIndex ?? 0) + 1}.`,
          ),
        );
      }
      return;
    }
    setMoveNotice("");
    onChange(res.groups, true);
  };

  return (
    <div className="ra-group-editor" data-allocation-groups>
      {moveNotice && (
        <div className="ra-inline-feedback is-error" role="alert">
          {moveNotice}
        </div>
      )}

      {groups.map((group, gIdx) => {
        const gLabel = bilingual(lang, `第 ${gIdx + 1} 组`, `Group ${gIdx + 1}`);
        const denom =
          caseCount > 0
            ? groupMemberDenom(
                caseCount,
                group.coverage_percent,
                groupCompleted[group.group_id] || 0,
                quotaBasis,
              )
            : 100;
        const namedIndices = group.members
          .map((m, idx) => (m.name ? idx : -1))
          .filter((idx) => idx >= 0);
        const memberCounts =
          unit === "count" && denom > 0
            ? apportionIntegerCounts(
                denom,
                namedIndices.map((idx) => percentToUnits(group.members[idx].review_percent) ?? 0),
              )
            : [];
        const countByMemberIdx = new Map<number, number>();
        namedIndices.forEach((idx, pos) => countByMemberIdx.set(idx, memberCounts[pos] ?? 0));

        const covDisplay =
          unit === "count" && caseCount > 0
            ? coverageCountFromPercent(caseCount, group.coverage_percent)
            : group.coverage_percent;

        const usedInGroup = new Set(group.members.map((m) => m.name).filter(Boolean));

        return (
          <section
            key={group.group_id}
            className={`ra-group-card${dropGroupIdx === gIdx ? " is-drop-target" : ""}`}
            data-setup-group={group.group_id}
            onDragOver={(e) => {
              if (!editable || !dragOrigin) return;
              e.preventDefault();
              setDropGroupIdx(gIdx);
            }}
            onDragLeave={() => {
              if (dropGroupIdx === gIdx) setDropGroupIdx(null);
            }}
            onDrop={(e) => {
              e.preventDefault();
              if (dragOrigin) {
                handleMove(dragOrigin.gIdx, dragOrigin.mIdx, gIdx);
              }
              setDragOrigin(null);
              setDropGroupIdx(null);
            }}
          >
            <header className="ra-group-card-head">
              <div className="ra-group-card-title">
                <strong>{gLabel}</strong>
                <label className="ra-coverage-field">
                  <span>{bilingual(lang, "覆盖", "Coverage")}</span>
                  <input
                    type="number"
                    min={unit === "count" ? 1 : 0.01}
                    max={unit === "count" && caseCount > 0 ? caseCount : 100}
                    step={unit === "count" ? 1 : 1}
                    disabled={!editable || gIdx === 0}
                    value={covDisplay}
                    aria-label={bilingual(lang, `${gLabel} 覆盖率`, `${gLabel} coverage`)}
                    onChange={(e) => {
                      const raw = Number(e.target.value);
                      if (!Number.isFinite(raw)) return;
                      const pct =
                        unit === "count" && caseCount > 0
                          ? coveragePercentFromCount(caseCount, raw)
                          : Math.max(0, Math.min(100, raw));
                      const next = groups.map((g, i) =>
                        i === gIdx ? { ...g, coverage_percent: pct } : g,
                      );
                      onChange(next, false);
                    }}
                    onBlur={onBlurFlush}
                  />
                  <span className="muted">{unit === "count" ? bilingual(lang, "条", "cases") : "%"}</span>
                </label>
              </div>
              <div className="ra-group-card-actions">
                {editable && (
                  <>
                    <button
                      type="button"
                      className={`button button-quiet${group.highlightEven ? " ra-highlight-even" : ""}`}
                      onClick={() => {
                        const next = groups.map((g, i) =>
                          i === gIdx
                            ? {
                                ...g,
                                members: normalizeGroupShares(g.members, true),
                                pinnedIndices: [],
                                highlightEven: false,
                              }
                            : g,
                        );
                        onChange(next, true);
                      }}
                    >
                      {bilingual(lang, "均分", "Equal split")}
                    </button>
                    <button
                      type="button"
                      className="button button-quiet"
                      onClick={() => {
                        const next = groups.map((g, i) =>
                          i === gIdx
                            ? {
                                ...g,
                                members: [...g.members, { name: "", review_percent: 0 }],
                              }
                            : g,
                        );
                        onChange(next, true);
                      }}
                    >
                      + {bilingual(lang, "成员", "Member")}
                    </button>
                    {groups.length > 1 && (
                      <button
                        type="button"
                        className="button button-quiet"
                        aria-label={bilingual(lang, `删除${gLabel}`, `Remove ${gLabel}`)}
                        onClick={() => {
                          const next = groups.filter((_, i) => i !== gIdx);
                          onChange(next, true);
                        }}
                      >
                        ×
                      </button>
                    )}
                  </>
                )}
              </div>
            </header>

            <div className="ra-group-members">
              {group.members.map((member, mIdx) => {
                const memberOptions = [
                  { value: "", label: bilingual(lang, "选择成员…", "Select member…") },
                  ...eligibleMembers.map((name) => ({
                    value: name,
                    label: name,
                    disabled: name !== member.name && usedInGroup.has(name),
                  })),
                ];
                if (member.name && !eligibleMembers.includes(member.name)) {
                  memberOptions.splice(1, 0, {
                    value: member.name,
                    label: member.name,
                    disabled: false,
                  });
                }

                const shareDisplay =
                  unit === "count" && caseCount > 0
                    ? (countByMemberIdx.get(mIdx) ?? 0)
                    : member.review_percent;

                return (
                  <div
                    key={`${group.group_id}-${mIdx}`}
                    className="ra-group-member-row"
                    draggable={editable && Boolean(member.name)}
                    onDragStart={() => setDragOrigin({ gIdx, mIdx })}
                    onDragEnd={() => {
                      setDragOrigin(null);
                      setDropGroupIdx(null);
                    }}
                    onDragOver={(e) => {
                      if (!editable || !dragOrigin) return;
                      e.preventDefault();
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      if (dragOrigin) {
                        handleMove(dragOrigin.gIdx, dragOrigin.mIdx, gIdx, mIdx);
                      }
                      setDragOrigin(null);
                      setDropGroupIdx(null);
                    }}
                  >
                    {editable && (
                      <span
                        className="ra-drag-handle"
                        title={bilingual(lang, "拖拽调整顺序或跨组移动", "Drag to reorder or move across groups")}
                        aria-hidden="true"
                      >
                        ⋮⋮
                      </span>
                    )}
                    <div className="ra-member-picker">
                      <UiSelect
                        value={member.name}
                        options={memberOptions}
                        disabled={!editable}
                        ariaLabel={bilingual(
                          lang,
                          `${gLabel} 成员 ${mIdx + 1}`,
                          `${gLabel} member ${mIdx + 1}`,
                        )}
                        onChange={(val) => {
                          const updatedMembers = group.members.map((m, idx) =>
                            idx === mIdx ? { ...m, name: val } : m,
                          );
                          const normalized = normalizeGroupShares(updatedMembers, false);
                          const next = groups.map((g, i) =>
                            i === gIdx
                              ? { ...g, members: normalized, pinnedIndices: [], highlightEven: false }
                              : g,
                          );
                          onChange(next, true);
                        }}
                      />
                    </div>
                    <div className="ra-share-input-wrap">
                      <input
                        type="number"
                        min={0}
                        max={unit === "count" ? denom : 100}
                        step={unit === "count" ? 1 : 0.01}
                        disabled={!editable || !member.name}
                        value={shareDisplay}
                        aria-label={bilingual(
                          lang,
                          `${member.name || gLabel} 配额`,
                          `Share for ${member.name || gLabel}`,
                        )}
                        onChange={(e) => {
                          const raw = Number(e.target.value);
                          if (!Number.isFinite(raw)) return;
                          const rebalanced = rebalanceGroupMembers(
                            group.members,
                            mIdx,
                            raw,
                            group.pinnedIndices || [],
                            unit,
                            denom,
                          );
                          const next = groups.map((g, i) =>
                            i === gIdx
                              ? {
                                  ...g,
                                  members: rebalanced.members,
                                  pinnedIndices: rebalanced.pinnedIndices,
                                  highlightEven: false,
                                }
                              : g,
                          );
                          onChange(next, false);
                        }}
                        onBlur={onBlurFlush}
                      />
                      <span className="muted">
                        {unit === "count" ? bilingual(lang, "条", "cases") : "%"}
                      </span>
                    </div>

                    {editable && (
                      <div className="ra-member-row-actions">
                        {groups.length > 1 && member.name && (
                          <button
                            type="button"
                            className="button button-quiet ra-compact-icon-btn"
                            title={bilingual(lang, "移到下一组", "Move to next group")}
                            aria-label={bilingual(
                              lang,
                              `将 ${member.name} 移到下一组`,
                              `Move ${member.name} to next group`,
                            )}
                            onClick={() => handleMove(gIdx, mIdx, (gIdx + 1) % groups.length)}
                          >
                            ⇄
                          </button>
                        )}
                        {group.members.length > 1 && (
                          <button
                            type="button"
                            className="button button-quiet ra-compact-icon-btn"
                            title={bilingual(lang, "移除成员", "Remove member")}
                            aria-label={bilingual(
                              lang,
                              `移除 ${member.name || "成员"}`,
                              `Remove ${member.name || "member"}`,
                            )}
                            onClick={() => {
                              const remaining = group.members.filter((_, idx) => idx !== mIdx);
                              const normalized = normalizeGroupShares(remaining, false);
                              const next = groups.map((g, i) =>
                                i === gIdx
                                  ? { ...g, members: normalized, pinnedIndices: [] }
                                  : g,
                              );
                              onChange(next, true);
                            }}
                          >
                            ×
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
};
