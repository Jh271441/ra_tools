import React, { useEffect, useMemo, useRef, useState } from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { UiSelect, UiSelectOption } from "../ui/UiSelect";
import {
  AccessUserItem,
  AllocationDraft,
  allocationColorSlot,
  allocationGroupDenom,
  allocationGroupName,
  allocationGroupShortBadge,
  allocationPercentUnits,
  apportionIntegerCounts,
  completeGroupShares,
  computeGroupEqualizeSuggestion,
  coverageCountFromPercent,
  coveragePercentFromCount,
  i18nLocaleTag,
  moveAllocationGroupMember,
  newAllocationGroup,
  splitGroupShares,
} from "./allocationMath";

export interface AllocationGroupSetupProps {
  id?: string;
  draft: AllocationDraft;
  users: AccessUserItem[];
  lang: UiLanguage;
  editable?: boolean;
  caseCount?: number;
  quotaBasis?: "total" | "remaining";
  groupCompleted?: Record<string, number>;
  hideBar?: boolean;
  onChange: (next: AllocationDraft, meta: { immediate: boolean }) => void;
  onFlush?: () => void;
  onUnitChange?: (unit: "percent" | "count") => void;
}

interface ShareEditSession {
  groupId: string;
  memberIndex: number;
  isCount: boolean;
  denom: number;
  selectedIndices: number[];
  pinnedIndices: number[];
  pinnedInitial: number[];
  pinnedSum: number;
  freeIndices: number[];
  freeWeights: number[];
  releasedIndex: number | null;
}

export const AllocationGroupSetup: React.FC<AllocationGroupSetupProps> = ({
  id,
  draft,
  users,
  lang,
  editable = true,
  caseCount = 0,
  quotaBasis = "total",
  groupCompleted = {},
  hideBar = false,
  onChange,
  onFlush,
  onUnitChange,
}) => {
  const safeCaseCount = Math.max(0, Math.round(Number(caseCount) || 0));
  const inputUnit: "percent" | "count" =
    draft.inputUnit === "count" && safeCaseCount > 0 ? "count" : "percent";
  const isCount = inputUnit === "count";
  const groups = draft.groups?.length ? draft.groups : [newAllocationGroup()];
  const rules = draft.cross_groups || [];
  const pairingMode = draft.pairing_mode || (rules.length ? "custom" : "orthogonal");
  const singleGroup = groups.length === 1;

  const [rulesInfoOpen, setRulesInfoOpen] = useState(false);
  const [dragStatus, setDragStatus] = useState<string>("");
  const dragStatusTimerRef = useRef<number | null>(null);
  const pinnedByGroupRef = useRef<Record<string, number[]>>({});
  const editSessionRef = useRef<ShareEditSession | null>(null);
  const infoRef = useRef<HTMLSpanElement | null>(null);

  // Local text overrides while typing so count mode or partial decimals don't jump mid-keystroke
  const [rawCountCov, setRawCountCov] = useState<Record<string, string>>({});
  const [rawCountShares, setRawCountShares] = useState<Record<string, Record<number, string>>>({});
  const [rawPctCov, setRawPctCov] = useState<Record<string, string>>({});
  const [rawPctShares, setRawPctShares] = useState<Record<string, Record<number, string>>>({});

  // Clear local editing buffers when switching unit or quotaBasis or group structure changes externally
  useEffect(() => {
    setRawCountCov({});
    setRawCountShares({});
    setRawPctCov({});
    setRawPctShares({});
    editSessionRef.current = null;
  }, [inputUnit, quotaBasis, safeCaseCount, groups.length]);

  useEffect(() => {
    if (!rulesInfoOpen) return;
    const handleOutside = (event: MouseEvent) => {
      if (infoRef.current && !infoRef.current.contains(event.target as Node)) {
        setRulesInfoOpen(false);
      }
    };
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setRulesInfoOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleEsc);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleEsc);
    };
  }, [rulesInfoOpen]);

  useEffect(() => {
    return () => {
      if (dragStatusTimerRef.current) window.clearTimeout(dragStatusTimerRef.current);
    };
  }, []);

  const candidates = useMemo(
    () => (users || []).filter((u) => ["writer", "admin"].includes(u.role)),
    [users],
  );

  const numFmt = useMemo(
    () => new Intl.NumberFormat(i18nLocaleTag(lang), { maximumFractionDigits: 2 }),
    [lang],
  );

  const showTempDragStatus = (msg: string) => {
    setDragStatus(msg);
    if (dragStatusTimerRef.current) window.clearTimeout(dragStatusTimerRef.current);
    if (msg) {
      dragStatusTimerRef.current = window.setTimeout(() => setDragStatus(""), 3600);
    }
  };

  const commitDraft = (next: AllocationDraft, immediate: boolean) => {
    onChange(next, { immediate });
  };

  const cloneDraft = (): AllocationDraft => ({
    ...draft,
    inputUnit,
    pairing_mode: pairingMode,
    groups: groups.map((g) => ({ ...g, members: g.members.map((m) => ({ ...m })) })),
    cross_groups: rules.map((r) => ({
      ...r,
      members: r.members.map((m) => ({ ...m })),
      issue_ids: [...(r.issue_ids || [])],
    })),
    ruleScopes: [...(draft.ruleScopes || [])],
  });

  // Compute display counts & denoms per group
  const groupCalcs = useMemo(() => {
    return groups.map((group) => {
      const members = group.members.length ? group.members : [{ name: "", review_percent: 100 }];
      const selected = members.filter((m) => m.name);
      const completedInGroup = Math.max(0, Math.round(Number(groupCompleted[group.group_id]) || 0));
      const computedCovCount = isCount
        ? singleGroup
          ? safeCaseCount
          : coverageCountFromPercent(safeCaseCount, group.coverage_percent) ?? safeCaseCount
        : null;
      const rawCovStr = isCount ? rawCountCov[group.group_id] : rawPctCov[group.group_id];
      const covCountVal =
        isCount && rawCovStr !== undefined && rawCovStr !== "" && Number.isInteger(Number(rawCovStr))
          ? Number(rawCovStr)
          : computedCovCount;
      const memberDenom = isCount
        ? allocationGroupDenom(safeCaseCount, covCountVal, completedInGroup, quotaBasis)
        : 100;
      const apportionedCounts = isCount
        ? apportionIntegerCounts(
            memberDenom,
            selected.map((p) => allocationPercentUnits(p.review_percent) ?? 0),
          )
        : null;
      let cursor = 0;
      const displayMembers = members.map((person, mIdx) => {
        if (!isCount) {
          const rawStr = rawPctShares[group.group_id]?.[mIdx];
          const val = rawStr !== undefined ? (rawStr === "" ? null : Number(rawStr)) : person.review_percent;
          return {
            name: person.name,
            value: val,
            displayStr: rawStr !== undefined ? rawStr : person.review_percent != null ? String(person.review_percent) : "",
            savedShare: Number(person.review_percent) || 0,
          };
        }
        const defaultCount = person.name ? (apportionedCounts?.[cursor++] ?? 0) : 0;
        const rawStr = rawCountShares[group.group_id]?.[mIdx];
        const val = rawStr !== undefined ? (rawStr === "" ? null : Number(rawStr)) : defaultCount;
        return {
          name: person.name,
          value: val,
          displayStr: rawStr !== undefined ? rawStr : String(defaultCount),
          savedShare: Number(person.review_percent) || 0,
        };
      });
      return {
        group,
        members,
        selectedCount: selected.length,
        completedInGroup,
        covCount: covCountVal,
        covDisplayStr:
          rawCovStr !== undefined
            ? rawCovStr
            : isCount
              ? String(computedCovCount ?? safeCaseCount)
              : group.coverage_percent != null
                ? String(group.coverage_percent)
                : "",
        memberDenom,
        displayMembers,
      };
    });
  }, [
    groups,
    groupCompleted,
    isCount,
    singleGroup,
    safeCaseCount,
    quotaBasis,
    rawCountCov,
    rawCountShares,
    rawPctCov,
    rawPctShares,
  ]);

  const totalCoverage = useMemo(() => {
    return groupCalcs.reduce((sum, calc) => {
      if (isCount) {
        const v = Number(calc.covDisplayStr);
        return sum + (Number.isFinite(v) ? v : 0);
      }
      const v = singleGroup ? 100 : Number(calc.covDisplayStr);
      return sum + (Number.isFinite(v) ? v : 0);
    }, 0);
  }, [groupCalcs, isCount, singleGroup]);

  const handleUnitToggle = (targetUnit: "percent" | "count") => {
    const resolved = targetUnit === "count" && safeCaseCount > 0 ? "count" : "percent";
    if (resolved === inputUnit) return;
    const next = cloneDraft();
    next.inputUnit = resolved;
    setRawCountCov({});
    setRawCountShares({});
    setRawPctCov({});
    setRawPctShares({});
    editSessionRef.current = null;
    commitDraft(next, true);
    onUnitChange?.(resolved);
  };

  const handleAddGroup = () => {
    if (!editable) return;
    const next = cloneDraft();
    next.groups.push(newAllocationGroup(next.groups));
    commitDraft(next, true);
  };

  const handleRemoveGroup = (gIdx: number) => {
    if (!editable) return;
    const next = cloneDraft();
    const removed = next.groups[gIdx];
    next.groups.splice(gIdx, 1);
    if (next.groups.length === 1) {
      next.groups[0].coverage_percent = 100;
      next.pairing_mode = "orthogonal";
      next.cross_groups = [];
      next.ruleScopes = [];
    } else if (removed) {
      next.cross_groups = next.cross_groups.filter(
        (rule) => !rule.members.some((p) => p.group_id === removed.group_id),
      );
    }
    commitDraft(next, true);
  };

  const handleEqualize = (gIdx: number) => {
    if (!editable) return;
    const next = cloneDraft();
    const group = next.groups[gIdx];
    if (!group) return;
    group.members = completeGroupShares(group.members, true);
    delete pinnedByGroupRef.current[group.group_id];
    setRawCountShares((prev) => {
      const copy = { ...prev };
      delete copy[group.group_id];
      return copy;
    });
    setRawPctShares((prev) => {
      const copy = { ...prev };
      delete copy[group.group_id];
      return copy;
    });
    editSessionRef.current = null;
    commitDraft(next, true);
  };

  const handleCoverageChange = (gIdx: number, rawStr: string) => {
    if (!editable) return;
    const calc = groupCalcs[gIdx];
    const gid = calc.group.group_id;
    const next = cloneDraft();
    const group = next.groups[gIdx];
    const parsed = rawStr === "" ? null : Number(rawStr);
    if (isCount) {
      setRawCountCov((prev) => ({ ...prev, [gid]: rawStr }));
      if (parsed != null && Number.isInteger(parsed) && parsed >= 1 && parsed <= safeCaseCount) {
        group.coverage_percent = coveragePercentFromCount(safeCaseCount, parsed);
        const newDenom = allocationGroupDenom(
          safeCaseCount,
          parsed,
          calc.completedInGroup,
          quotaBasis,
        );
        if (newDenom !== calc.memberDenom) {
          delete pinnedByGroupRef.current[gid];
          editSessionRef.current = null;
          setRawCountShares((prev) => {
            const copy = { ...prev };
            delete copy[gid];
            return copy;
          });
        }
      } else {
        group.coverage_percent = null;
      }
    } else {
      setRawPctCov((prev) => ({ ...prev, [gid]: rawStr }));
      group.coverage_percent = parsed != null && Number.isFinite(parsed) ? parsed : null;
    }
    commitDraft(next, false);
  };

  const handleMemberSelect = (gIdx: number, mIdx: number, newName: string) => {
    if (!editable) return;
    const next = cloneDraft();
    const group = next.groups[gIdx];
    if (!group) return;
    group.members[mIdx] = { ...group.members[mIdx], name: newName };
    const selected = group.members.filter((m) => m.name);
    if (selected.length === 1) {
      selected[0].review_percent = 100;
    }
    delete pinnedByGroupRef.current[group.group_id];
    setRawCountShares((prev) => {
      const copy = { ...prev };
      delete copy[group.group_id];
      return copy;
    });
    setRawPctShares((prev) => {
      const copy = { ...prev };
      delete copy[group.group_id];
      return copy;
    });
    editSessionRef.current = null;
    commitDraft(next, true);
  };

  const handleShareChange = (gIdx: number, mIdx: number, rawStr: string) => {
    if (!editable) return;
    const calc = groupCalcs[gIdx];
    const gid = calc.group.group_id;
    const next = cloneDraft();
    const group = next.groups[gIdx];
    const selectedIndices = group.members
      .map((m, idx) => (m.name ? idx : -1))
      .filter((idx) => idx >= 0);

    // Prepare or reuse rebalance session for this input
    let session = editSessionRef.current;
    if (
      !session ||
      session.groupId !== gid ||
      session.memberIndex !== mIdx ||
      session.isCount !== isCount
    ) {
      if (selectedIndices.includes(mIdx) && selectedIndices.length >= 2) {
        const peers = selectedIndices.filter((idx) => idx !== mIdx);
        const history = (pinnedByGroupRef.current[gid] || []).filter(
          (idx) => selectedIndices.includes(idx) && idx !== mIdx,
        );
        let pinnedIndices = peers.filter((idx) => history.includes(idx));
        let freeIndices = peers.filter((idx) => !history.includes(idx));
        let releasedIndex: number | null = null;
        if (!freeIndices.length && pinnedIndices.length) {
          releasedIndex = history[0] ?? pinnedIndices[0];
          pinnedIndices = pinnedIndices.filter((idx) => idx !== releasedIndex);
          freeIndices = [releasedIndex];
        }
        const readWeight = (idx: number) => {
          const dm = calc.displayMembers[idx];
          if (isCount) {
            const v = dm?.value;
            return v != null && Number.isInteger(v) && v >= 0 ? v : 0;
          }
          return allocationPercentUnits(dm?.value) ?? 0;
        };
        const pinnedInitial = pinnedIndices.map(readWeight);
        const pinnedSum = pinnedInitial.reduce((a, b) => a + b, 0);
        const freeWeights = freeIndices.map(readWeight);
        session = {
          groupId: gid,
          memberIndex: mIdx,
          isCount,
          denom: isCount ? calc.memberDenom : 10000,
          selectedIndices,
          pinnedIndices,
          pinnedInitial,
          pinnedSum,
          freeIndices,
          freeWeights,
          releasedIndex,
        };
        editSessionRef.current = session;
      } else {
        session = null;
        editSessionRef.current = null;
      }
    }

    const commitPin = (s: ShareEditSession) => {
      const prev = pinnedByGroupRef.current[gid] || [];
      const updated = prev.filter(
        (idx) => s.selectedIndices.includes(idx) && idx !== s.memberIndex && idx !== s.releasedIndex,
      );
      updated.push(s.memberIndex);
      pinnedByGroupRef.current[gid] = updated;
    };

    const parsed = rawStr === "" ? null : Number(rawStr);

    if (isCount) {
      const nextCountRowMap: Record<number, string> = {
        ...(rawCountShares[gid] || {}),
        [mIdx]: rawStr,
      };
      // Populate defaults for peers if not yet in raw map
      calc.displayMembers.forEach((dm, idx) => {
        if (nextCountRowMap[idx] === undefined) nextCountRowMap[idx] = dm.displayStr;
      });
      if (session && parsed != null && Number.isInteger(parsed) && parsed >= 0 && parsed <= session.denom) {
        const rem = session.denom - parsed;
        if (rem >= session.pinnedSum) {
          session.pinnedIndices.forEach((pIdx, i) => {
            nextCountRowMap[pIdx] = String(session!.pinnedInitial[i]);
          });
          const counts = apportionIntegerCounts(rem - session.pinnedSum, session.freeWeights);
          session.freeIndices.forEach((fIdx, i) => {
            nextCountRowMap[fIdx] = String(counts[i]);
          });
        } else {
          session.freeIndices.forEach((fIdx) => {
            nextCountRowMap[fIdx] = "0";
          });
          const counts = apportionIntegerCounts(rem, session.pinnedInitial);
          session.pinnedIndices.forEach((pIdx, i) => {
            nextCountRowMap[pIdx] = String(counts[i]);
          });
        }
        commitPin(session);
      }
      setRawCountShares((prev) => ({ ...prev, [gid]: nextCountRowMap }));

      // Convert count map back to review_percent on draft
      const denom = calc.memberDenom;
      const selCounts: number[] = [];
      let allInts = denom > 0;
      selectedIndices.forEach((idx) => {
        const v = nextCountRowMap[idx] === "" ? NaN : Number(nextCountRowMap[idx]);
        if (Number.isInteger(v) && v >= 0) selCounts.push(v);
        else allInts = false;
      });
      const sumCounts = selCounts.reduce((a, b) => a + b, 0);
      const converted =
        allInts && selectedIndices.length && sumCounts === denom
          ? splitGroupShares(10000, selCounts)
          : null;
      let selCursor = 0;
      group.members = group.members.map((m, idx) => {
        if (!m.name) return { name: "", review_percent: 0 };
        const v = nextCountRowMap[idx] === "" ? null : Number(nextCountRowMap[idx]);
        if (denom === 0 && v === 0) return { name: m.name, review_percent: calc.displayMembers[idx]?.savedShare ?? 0 };
        if (converted) return { name: m.name, review_percent: converted[selCursor++] };
        if (v == null || !Number.isInteger(v) || v < 0 || !(denom > 0)) {
          return { name: m.name, review_percent: null };
        }
        return { name: m.name, review_percent: Math.round((v * 10000) / denom) / 100 };
      });
      commitDraft(next, false);
      return;
    }

    // Percent mode
    const nextPctRowMap: Record<number, string> = {
      ...(rawPctShares[gid] || {}),
      [mIdx]: rawStr,
    };
    const units = allocationPercentUnits(parsed);
    if (session && units != null) {
      const rem = 10000 - units;
      if (rem >= session.pinnedSum) {
        session.pinnedIndices.forEach((pIdx, i) => {
          const v = session!.pinnedInitial[i] / 100;
          group.members[pIdx].review_percent = v;
          nextPctRowMap[pIdx] = String(v);
        });
        const shares = splitGroupShares(rem - session.pinnedSum, session.freeWeights);
        session.freeIndices.forEach((fIdx, i) => {
          group.members[fIdx].review_percent = shares[i];
          nextPctRowMap[fIdx] = String(shares[i]);
        });
      } else {
        session.freeIndices.forEach((fIdx) => {
          group.members[fIdx].review_percent = 0;
          nextPctRowMap[fIdx] = "0";
        });
        const shares = splitGroupShares(rem, session.pinnedInitial);
        session.pinnedIndices.forEach((pIdx, i) => {
          group.members[pIdx].review_percent = shares[i];
          nextPctRowMap[pIdx] = String(shares[i]);
        });
      }
      group.members[mIdx].review_percent = parsed;
      commitPin(session);
    } else {
      group.members[mIdx].review_percent = parsed != null && Number.isFinite(parsed) ? parsed : null;
    }
    setRawPctShares((prev) => ({ ...prev, [gid]: nextPctRowMap }));
    commitDraft(next, false);
  };

  const handleAddMember = (gIdx: number) => {
    if (!editable) return;
    const next = cloneDraft();
    next.groups[gIdx]?.members.push({ name: "", review_percent: 0 });
    commitDraft(next, true);
  };

  const handleRemoveMember = (gIdx: number, mIdx: number) => {
    if (!editable) return;
    const next = cloneDraft();
    const group = next.groups[gIdx];
    if (!group) return;
    group.members.splice(mIdx, 1);
    if (!group.members.length) {
      group.members.push({ name: "", review_percent: 100 });
    } else {
      group.members = completeGroupShares(group.members);
    }
    delete pinnedByGroupRef.current[group.group_id];
    setRawCountShares((prev) => {
      const copy = { ...prev };
      delete copy[group.group_id];
      return copy;
    });
    setRawPctShares((prev) => {
      const copy = { ...prev };
      delete copy[group.group_id];
      return copy;
    });
    editSessionRef.current = null;
    commitDraft(next, true);
  };

  const handleStrategy = (gIdx: number, strategy: "overlap" | "fill") => {
    if (!editable) return;
    const next = cloneDraft();
    if (next.groups[gIdx]) next.groups[gIdx].coverage_strategy = strategy;
    commitDraft(next, true);
  };

  const handlePairingMode = (mode: "orthogonal" | "paired" | "custom") => {
    if (!editable) return;
    const next = cloneDraft();
    next.pairing_mode = mode;
    if (mode === "custom" && !next.cross_groups.length) {
      const used = new Set<string>();
      const defaultMembers = next.groups
        .map((g) => {
          const first =
            g.members.find((m) => m.name && (Number(m.review_percent) || 0) > 0 && !used.has(m.name)) ||
            g.members.find((m) => m.name && !used.has(m.name));
          if (!first) return null;
          used.add(first.name);
          return { group_id: g.group_id, name: first.name };
        })
        .filter((x): x is { group_id: string; name: string } => Boolean(x));
      next.cross_groups = [{ members: defaultMembers.slice(0, 2), issue_ids: [], count: null }];
      next.ruleScopes = ["count"];
    } else if (mode !== "custom") {
      next.cross_groups = [];
      next.ruleScopes = [];
    }
    commitDraft(next, true);
  };

  const handleKeyboardMove = (
    event: React.KeyboardEvent,
    gIdx: number,
    mIdx: number,
  ) => {
    if (!editable) return;
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
    const groupMembersCount = groups[gIdx]?.members.length || 0;
    let toG = gIdx;
    let toSlot: number | null = null;
    if (event.key === "ArrowUp" && mIdx > 0) {
      toSlot = mIdx - 1;
    } else if (event.key === "ArrowDown" && mIdx < groupMembersCount - 1) {
      toSlot = mIdx + 2;
    } else if (event.key === "ArrowLeft" && gIdx > 0) {
      toG = gIdx - 1;
    } else if (event.key === "ArrowRight" && gIdx < groups.length - 1) {
      toG = gIdx + 1;
    } else {
      return;
    }
    event.preventDefault();
    const outcome = moveAllocationGroupMember(cloneDraft(), gIdx, mIdx, toG, toSlot);
    if (!outcome.moved) {
      if (outcome.reason === "duplicate" && outcome.memberName != null && outcome.targetGroupIndex != null) {
        const gLabel = allocationGroupName(outcome.targetGroupIndex, lang);
        showTempDragStatus(
          bilingual(
            lang,
            `「${outcome.memberName}」已在${gLabel}中，未重复移入。`,
            `"${outcome.memberName}" is already in ${gLabel}.`,
          ),
        );
      }
      return;
    }
    if (outcome.nextDraft) {
      commitDraft(outcome.nextDraft, true);
    }
  };

  const pairedChips = useMemo(() => {
    if (pairingMode !== "paired" || groups.length < 2) return null;
    const lists = groups.map((group, gIdx) =>
      (group.members || [])
        .map((p, mIdx) => ({
          name: p.name,
          share: Number(p.review_percent) || 0,
          slot: allocationColorSlot(gIdx, mIdx),
        }))
        .filter((p) => p.name && p.share > 0),
    );
    const g0 = lists[0] || [];
    if (!g0.length || lists.slice(1).every((list) => !list.length)) return null;
    const pairCount = Math.max(...lists.map((list) => list.length));
    return Array.from({ length: pairCount }, (_, idx) => {
      const lead = g0[idx % g0.length];
      const members = [lead];
      for (let gIdx = 1; gIdx < lists.length; gIdx += 1) {
        const list = lists[gIdx];
        if (!list.length) continue;
        let partner = list[idx % list.length];
        if (partner.name === lead.name && list.length > 1) {
          partner = list[(idx + 1) % list.length];
        }
        members.push(partner);
      }
      return members;
    });
  }, [pairingMode, groups]);

  const coverageLabel = isCount
    ? bilingual(lang, "覆盖条数", "Coverage cases")
    : bilingual(lang, "覆盖率", "Coverage");
  const shareLabel = isCount
    ? bilingual(lang, "组内条数", "Group cases")
    : bilingual(lang, "组内比例", "Group share");
  const unitText = isCount ? bilingual(lang, "条", "cases") : "%";
  const emptyLabel = bilingual(lang, "选择成员", "Select a member");
  const removeMemberLabel = bilingual(lang, "移除成员", "Remove member");
  const dragHelp = bilingual(
    lang,
    "拖动调整顺序或移至其他组（聚焦后也可用方向键）",
    "Drag to reorder or move to another group (arrow keys supported)",
  );

  const summaryText = isCount
    ? bilingual(
        lang,
        `${groups.length} 组 · 共 ${numFmt.format(totalCoverage)} 份`,
        `${groups.length} ${groups.length === 1 ? "group" : "groups"} · ${numFmt.format(totalCoverage)} slots`,
      )
    : bilingual(
        lang,
        `${groups.length} 组 · 共 ${numFmt.format(totalCoverage)}%`,
        `${groups.length} ${groups.length === 1 ? "group" : "groups"} · ${numFmt.format(totalCoverage)}%`,
      );

  return (
    <div
      id={id}
      className="allocation-group-setup"
      data-input-unit={inputUnit}
      data-case-count={String(safeCaseCount)}
      data-quota-basis={quotaBasis}
    >
      {!hideBar && (
        <div className="allocation-setup-bar">
          <span className="allocation-setup-bar-title">
            <span>{bilingual(lang, "分配组", "Allocation groups")}</span>
            <small data-setup-summary="">{summaryText}</small>
          </span>
          <div className="allocation-setup-bar-tools">
            <div
              className="allocation-unit-switch"
              role="group"
              aria-label={bilingual(lang, "数值单位", "Input unit")}
            >
              <button
                type="button"
                className={!isCount ? "is-active" : undefined}
                aria-pressed={!isCount}
                title={bilingual(lang, "按百分比输入", "Enter percentages")}
                onClick={() => handleUnitToggle("percent")}
              >
                %
              </button>
              <button
                type="button"
                className={isCount ? "is-active" : undefined}
                aria-pressed={isCount}
                disabled={!(safeCaseCount > 0)}
                title={bilingual(lang, "按具体条数输入", "Enter exact case counts")}
                onClick={() => handleUnitToggle("count")}
              >
                {bilingual(lang, "条", "Count")}
              </button>
            </div>
            <button
              className="button button-secondary allocation-compact-btn allocation-add-group"
              type="button"
              disabled={!editable}
              onClick={handleAddGroup}
            >
              + {bilingual(lang, "添加分配组", "Add group")}
            </button>
          </div>
        </div>
      )}

      <div className="allocation-setup-surface">
        <div className="allocation-setup-cards" data-group-count={String(groups.length)}>
          {groupCalcs.map((calc, gIdx) => {
            const { group, displayMembers, selectedCount, memberDenom, completedInGroup } = calc;
            const groupName = allocationGroupName(gIdx, lang);
            const removeGroupLabel = bilingual(lang, `移除${groupName}`, `Remove ${groupName}`);
            const singleMember = selectedCount === 1;
            const sharesSum = displayMembers.reduce(
              (acc, dm) => acc + (dm.name && dm.value != null && Number.isFinite(dm.value) ? dm.value : 0),
              0,
            );
            const allInt = displayMembers.every(
              (dm) => !dm.name || (dm.value != null && Number.isInteger(dm.value) && dm.value >= 0),
            );
            const shareValid = isCount
              ? allInt && memberDenom > 0 && sharesSum === memberDenom
              : Math.round(sharesSum * 100) === 10000;
            const suggestion =
              editable && memberDenom > 0
                ? computeGroupEqualizeSuggestion(
                    displayMembers.map((dm) => ({ name: dm.name, review_percent: dm.value })),
                    { unit: inputUnit, denom: memberDenom, lang },
                  )
                : null;
            const canDragGroup = editable && (groups.length > 1 || selectedCount > 1);
            const covNum = Number(calc.covDisplayStr);
            const isPartial =
              !singleGroup &&
              Number.isFinite(covNum) &&
              covNum < (isCount ? safeCaseCount : 100);

            return (
              <section
                key={group.group_id}
                className="allocation-setup-card"
                data-setup-group={group.group_id}
                data-member-denom={String(memberDenom)}
                data-group-completed={String(completedInGroup)}
              >
                <header className="allocation-setup-header">
                  <div className="allocation-setup-title">
                    <strong>{groupName}</strong>
                    {singleGroup ? (
                      <span className="allocation-coverage-pill">
                        {isCount
                          ? bilingual(lang, `覆盖 ${safeCaseCount} 条`, `${safeCaseCount} cases`)
                          : bilingual(lang, "覆盖 100%", "100% cover")}
                      </span>
                    ) : (
                      <label className="allocation-coverage-inline">
                        <span>{bilingual(lang, "覆盖", "Cover")}</span>
                        <span className="assignment-ratio-input">
                          <span className="assignment-ratio-box">
                            <input
                              type="number"
                              aria-label={coverageLabel}
                              min={isCount ? 1 : 0}
                              max={isCount ? safeCaseCount : 100}
                              step={isCount ? 1 : 0.01}
                              inputMode={isCount ? "numeric" : "decimal"}
                              disabled={!editable}
                              value={calc.covDisplayStr}
                              onChange={(e) => handleCoverageChange(gIdx, e.target.value)}
                              onBlur={() => onFlush?.()}
                            />
                          </span>
                          <span className="assignment-ratio-unit" aria-hidden="true">
                            {unitText}
                          </span>
                        </span>
                      </label>
                    )}
                    <span
                      data-group-share=""
                      aria-live="polite"
                      hidden={shareValid || selectedCount === 0}
                      data-invalid={String(!shareValid && selectedCount > 0)}
                    >
                      {shareValid || selectedCount === 0
                        ? ""
                        : isCount
                          ? bilingual(
                              lang,
                              `合计 ${numFmt.format(sharesSum)} / ${numFmt.format(memberDenom)} 条`,
                              `${numFmt.format(sharesSum)} / ${numFmt.format(memberDenom)}`,
                            )
                          : bilingual(
                              lang,
                              `合计 ${numFmt.format(sharesSum)}% / 100%`,
                              `${numFmt.format(sharesSum)}% / 100%`,
                            )}
                    </span>
                  </div>
                  <div className="allocation-setup-tools">
                    <button
                      className="text-button allocation-tool-link allocation-equalize-btn"
                      type="button"
                      hidden={selectedCount < 2}
                      disabled={!suggestion || !editable}
                      data-needs-equalize={suggestion && editable ? "true" : undefined}
                      aria-label={bilingual(lang, `${groupName}均分`, `Even split ${groupName}`)}
                      title={
                        suggestion
                          ? bilingual(lang, suggestion.textZh, suggestion.textEn)
                          : bilingual(lang, "当前组已均分", "Already evenly split")
                      }
                      onClick={() => handleEqualize(gIdx)}
                    >
                      {bilingual(lang, "均分", "Even split")}
                    </button>
                    {!singleGroup && (
                      <button
                        className="text-button allocation-tool-link"
                        type="button"
                        disabled={!editable}
                        aria-label={removeGroupLabel}
                        onClick={() => handleRemoveGroup(gIdx)}
                      >
                        {bilingual(lang, "移除", "Remove")}
                      </button>
                    )}
                  </div>
                </header>

                <div className="allocation-setup-members">
                  {displayMembers.map((dm, mIdx) => {
                    const slot = allocationColorSlot(gIdx, mIdx);
                    const val = dm.value != null && Number.isFinite(dm.value) ? dm.value : 0;
                    const fillPct = isCount
                      ? memberDenom > 0
                        ? Math.max(0, Math.min(100, (100 * val) / memberDenom))
                        : 0
                      : Math.max(0, Math.min(100, val));
                    const memberOptions: UiSelectOption[] = [
                      { value: "", label: emptyLabel },
                      ...candidates.map((u) => ({ value: u.username, label: u.username })),
                    ];
                    if (dm.name && !memberOptions.some((o) => o.value === dm.name)) {
                      memberOptions.push({
                        value: dm.name,
                        label: `${dm.name} · ${bilingual(lang, "不可用", "Unavailable")}`,
                      });
                    }
                    const canDragRow = canDragGroup && Boolean(dm.name);
                    return (
                      <div
                        key={`${group.group_id}-m-${mIdx}`}
                        className="allocation-setup-member"
                        data-setup-member=""
                        data-empty={String(!dm.name)}
                        data-draggable={String(canDragRow)}
                        style={
                          {
                            "--member-swatch": `var(--allocation-swatch-${slot})`,
                            "--share-color": `var(--allocation-swatch-${slot})`,
                          } as React.CSSProperties
                        }
                      >
                        {canDragRow ? (
                          <button
                            className="allocation-drag-handle"
                            type="button"
                            data-drag-handle=""
                            aria-label={`${dm.name} · ${dragHelp}`}
                            title={dragHelp}
                            onKeyDown={(e) => handleKeyboardMove(e, gIdx, mIdx)}
                          >
                            <span className="allocation-drag-swatch" aria-hidden="true" />
                            <svg
                              className="allocation-drag-grip"
                              viewBox="0 0 8 14"
                              fill="currentColor"
                              aria-hidden="true"
                            >
                              <circle cx="2" cy="3" r="1.15" />
                              <circle cx="6" cy="3" r="1.15" />
                              <circle cx="2" cy="7" r="1.15" />
                              <circle cx="6" cy="7" r="1.15" />
                              <circle cx="2" cy="11" r="1.15" />
                              <circle cx="6" cy="11" r="1.15" />
                            </svg>
                          </button>
                        ) : (
                          <span className="allocation-member-swatch" aria-hidden="true" />
                        )}

                        <UiSelect
                          value={dm.name}
                          options={memberOptions}
                          ariaLabel={emptyLabel}
                          disabled={!editable}
                          onChange={(valStr) => handleMemberSelect(gIdx, mIdx, valStr)}
                        />

                        <span
                          className="assignment-ratio-input"
                          style={{ "--share-fill": `${fillPct}%` } as React.CSSProperties}
                        >
                          <span className="assignment-ratio-box">
                            <input
                              type="number"
                              aria-label={shareLabel}
                              min={0}
                              max={isCount ? memberDenom : 100}
                              step={isCount ? 1 : 0.01}
                              inputMode={isCount ? "numeric" : "decimal"}
                              disabled={!editable || !dm.name}
                              readOnly={singleMember || (isCount && memberDenom === 0)}
                              value={dm.displayStr}
                              onChange={(e) => handleShareChange(gIdx, mIdx, e.target.value)}
                              onBlur={() => {
                                editSessionRef.current = null;
                                onFlush?.();
                              }}
                            />
                          </span>
                          <span className="assignment-ratio-unit" aria-hidden="true">
                            {unitText}
                          </span>
                        </span>

                        <button
                          className="allocation-remove-control"
                          type="button"
                          disabled={!editable}
                          aria-label={removeMemberLabel}
                          title={removeMemberLabel}
                          onClick={() => handleRemoveMember(gIdx, mIdx)}
                        >
                          ×
                        </button>
                      </div>
                    );
                  })}
                </div>

                <div className="allocation-setup-actions">
                  <button
                    className="text-button allocation-add-member"
                    type="button"
                    disabled={!editable}
                    onClick={() => handleAddMember(gIdx)}
                  >
                    <svg className="allocation-add-icon" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                      <path
                        d="M6 2.2v7.6M2.2 6h7.6"
                        stroke="currentColor"
                        strokeWidth="1.4"
                        strokeLinecap="round"
                      />
                    </svg>
                    <span>{bilingual(lang, "添加成员", "Add member")}</span>
                  </button>

                  {gIdx > 0 && (
                    <div
                      className="allocation-strategy-switch"
                      role="group"
                      aria-label={bilingual(lang, "覆盖策略", "Coverage strategy")}
                      hidden={!isPartial}
                    >
                      <button
                        type="button"
                        disabled={!editable}
                        className={group.coverage_strategy !== "fill" ? "is-active" : undefined}
                        aria-pressed={group.coverage_strategy !== "fill"}
                        title={bilingual(lang, "优先与前组重叠", "Prefer overlap with earlier groups")}
                        onClick={() => handleStrategy(gIdx, "overlap")}
                      >
                        {bilingual(lang, "重叠前组", "Overlap")}
                      </button>
                      <button
                        type="button"
                        disabled={!editable}
                        className={group.coverage_strategy === "fill" ? "is-active" : undefined}
                        aria-pressed={group.coverage_strategy === "fill"}
                        title={bilingual(
                          lang,
                          "优先补未交叉 Case",
                          "Prefer cases without cross-review",
                        )}
                        onClick={() => handleStrategy(gIdx, "fill")}
                      >
                        {bilingual(lang, "补未交叉", "Fill gaps")}
                      </button>
                    </div>
                  )}
                </div>
              </section>
            );
          })}
        </div>

        <p className="allocation-drag-status" role="status" aria-live="polite" hidden={!dragStatus}>
          {dragStatus}
        </p>

        {groups.length > 1 && (
          <div className="allocation-pairing-section">
            <div className="allocation-pairing-bar">
              <div className="allocation-pairing-left">
                <span className="allocation-pairing-label">
                  {bilingual(lang, "跨组配对", "Cross-pairing")}
                </span>
                <div
                  className="allocation-pairing-switch"
                  role="group"
                  aria-label={bilingual(lang, "跨组配对方式", "Cross-group pairing mode")}
                >
                  {(
                    [
                      ["orthogonal", "正交打散", "Orthogonal"],
                      ["paired", "固定结对", "1-to-1"],
                      ["custom", "定向规则", "Custom"],
                    ] as const
                  ).map(([mode, zh, en]) => (
                    <button
                      key={mode}
                      type="button"
                      disabled={!editable}
                      className={pairingMode === mode ? "is-active" : undefined}
                      aria-pressed={pairingMode === mode}
                      onClick={() => handlePairingMode(mode)}
                    >
                      {bilingual(lang, zh, en)}
                    </button>
                  ))}
                </div>
              </div>

              <span
                ref={infoRef}
                className={`model-review-run-help ui-info allocation-rules-info${rulesInfoOpen ? " is-open" : ""}`}
                data-ui-info=""
                data-ui-info-align="end"
              >
                <button
                  className="ui-info-button"
                  type="button"
                  aria-expanded={rulesInfoOpen}
                  aria-label={bilingual(lang, "跨组配对说明", "Cross-group pairing help")}
                  title={bilingual(lang, "跨组配对说明", "Cross-group pairing help")}
                  onClick={(e) => {
                    e.stopPropagation();
                    setRulesInfoOpen((v) => !v);
                  }}
                >
                  <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                    <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.4" />
                    <path
                      d="M10 9.1v4.6"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                    />
                    <circle cx="10" cy="6.3" r=".9" fill="currentColor" />
                  </svg>
                </button>
                <span className="model-review-run-tooltip ui-info-tooltip" role="dialog">
                  <strong>{bilingual(lang, "跨组配对方式", "Cross-group pairing modes")}</strong>
                  <span>
                    {bilingual(
                      lang,
                      "正交打散（默认）：按各组比例自动均匀交叉打散。",
                      "Orthogonal (default): automatically balances cross-group pairs by member shares.",
                    )}
                  </span>
                  <span>
                    {bilingual(
                      lang,
                      "固定结对：按组内成员顺序 1 对 1 结对。",
                      "1-to-1 paired: matches members sequentially across groups.",
                    )}
                  </span>
                  <span>
                    {bilingual(
                      lang,
                      "定向规则：指定特定搭档共同复核固定条数或指定 Case，其余自动正交打散。",
                      "Custom: pin specific partners to a count or exact Case IDs; remaining cases stay orthogonal.",
                    )}
                  </span>
                </span>
              </span>
            </div>

            {pairingMode === "paired" && pairedChips && (
              <div className="allocation-paired-chips">
                {pairedChips.map((chip, idx) => (
                  <span key={`pair-${idx}`} className="allocation-paired-chip">
                    {chip.map((item, i) => (
                      <React.Fragment key={`${item.name}-${i}`}>
                        {i > 0 && (
                          <span className="allocation-paired-sep" aria-hidden="true">
                            ↔
                          </span>
                        )}
                        <span className="allocation-paired-member">
                          <i
                            className="allocation-member-swatch"
                            style={
                              {
                                "--member-swatch": `var(--allocation-swatch-${item.slot})`,
                              } as React.CSSProperties
                            }
                            aria-hidden="true"
                          />
                          {item.name}
                        </span>
                      </React.Fragment>
                    ))}
                  </span>
                ))}
              </div>
            )}

            {pairingMode === "custom" && (
              <div className="allocation-custom-rules">
                {rules.map((rule, rIdx) => {
                  const scope = draft.ruleScopes?.[rIdx] || (rule.issue_ids?.length ? "cases" : "count");
                  const byGroup = new Map(rule.members.map((m) => [m.group_id, m.name]));
                  return (
                    <div key={`rule-${rIdx}`} className="allocation-setup-rule" data-rule-scope={scope}>
                      <div className="allocation-rule-main">
                        <div className="allocation-rule-pickers">
                          {groups.map((group, gIdx) => {
                            const selectedName = byGroup.get(group.group_id) || "";
                            const members = group.members.filter((p) => p.name);
                            const prompt =
                              groups.length > 2
                                ? bilingual(lang, "不限", "Any")
                                : bilingual(lang, "选择成员", "Select member");
                            const opts: UiSelectOption[] = [
                              { value: "", label: prompt },
                              ...members.map((p) => ({ value: p.name, label: p.name })),
                            ];
                            if (selectedName && !opts.some((o) => o.value === selectedName)) {
                              opts.push({
                                value: selectedName,
                                label: `${selectedName} · ${bilingual(lang, "已移除", "Removed")}`,
                              });
                            }
                            const memberIdx = Math.max(
                              0,
                              members.findIndex((p) => p.name === selectedName),
                            );
                            const slot = allocationColorSlot(gIdx, selectedName ? memberIdx : 0);
                            return (
                              <React.Fragment key={`${group.group_id}-slot`}>
                                {gIdx > 0 && (
                                  <span className="allocation-rule-times" aria-hidden="true">
                                    ×
                                  </span>
                                )}
                                <div
                                  className="allocation-rule-slot"
                                  style={
                                    {
                                      "--member-swatch": selectedName
                                        ? `var(--allocation-swatch-${slot})`
                                        : "var(--faint)",
                                    } as React.CSSProperties
                                  }
                                >
                                  <span className="allocation-rule-slot-tag">
                                    <span className="allocation-member-swatch" aria-hidden="true" />
                                    <span>{allocationGroupShortBadge(gIdx, lang)}</span>
                                  </span>
                                  <UiSelect
                                    value={selectedName}
                                    options={opts}
                                    disabled={!editable}
                                    ariaLabel={`${allocationGroupName(gIdx, lang)} · ${prompt}`}
                                    onChange={(valStr) => {
                                      const next = cloneDraft();
                                      const target = next.cross_groups[rIdx];
                                      if (!target) return;
                                      const filtered = target.members.filter(
                                        (p) => p.group_id !== group.group_id,
                                      );
                                      if (valStr) {
                                        filtered.push({ group_id: group.group_id, name: valStr });
                                      }
                                      target.members = filtered;
                                      commitDraft(next, true);
                                    }}
                                  />
                                </div>
                              </React.Fragment>
                            );
                          })}
                        </div>

                        <div className="allocation-rule-scope-controls">
                          <div
                            className="allocation-rule-scope-switch"
                            role="group"
                            aria-label={bilingual(lang, "范围方式", "Scope mode")}
                          >
                            <button
                              type="button"
                              disabled={!editable}
                              className={scope === "count" ? "is-active" : undefined}
                              onClick={() => {
                                const next = cloneDraft();
                                next.ruleScopes[rIdx] = "count";
                                next.cross_groups[rIdx].issue_ids = [];
                                commitDraft(next, true);
                              }}
                            >
                              {bilingual(lang, "按数量", "Count")}
                            </button>
                            <button
                              type="button"
                              disabled={!editable}
                              className={scope === "cases" ? "is-active" : undefined}
                              onClick={() => {
                                const next = cloneDraft();
                                next.ruleScopes[rIdx] = "cases";
                                next.cross_groups[rIdx].count = null;
                                commitDraft(next, true);
                              }}
                            >
                              {bilingual(lang, "按 Case", "Cases")}
                            </button>
                          </div>

                          {scope === "count" && (
                            <span className="allocation-rule-count-box">
                              <input
                                type="number"
                                min={1}
                                step={1}
                                inputMode="numeric"
                                disabled={!editable}
                                aria-label={bilingual(lang, "共同复核数量", "Shared case count")}
                                placeholder="10"
                                value={rule.count ?? ""}
                                onChange={(e) => {
                                  const next = cloneDraft();
                                  const v = e.target.value === "" ? null : Number(e.target.value);
                                  next.cross_groups[rIdx].count = v != null && Number.isFinite(v) ? v : null;
                                  commitDraft(next, false);
                                }}
                                onBlur={() => onFlush?.()}
                              />
                              <span className="assignment-ratio-unit" aria-hidden="true">
                                {bilingual(lang, "条", "cases")}
                              </span>
                            </span>
                          )}

                          <button
                            className="allocation-remove-control"
                            type="button"
                            disabled={!editable}
                            aria-label={bilingual(lang, "移除规则", "Remove rule")}
                            title={bilingual(lang, "移除规则", "Remove rule")}
                            onClick={() => {
                              const next = cloneDraft();
                              next.cross_groups.splice(rIdx, 1);
                              next.ruleScopes.splice(rIdx, 1);
                              if (!next.cross_groups.length) next.pairing_mode = "orthogonal";
                              commitDraft(next, true);
                            }}
                          >
                            ×
                          </button>
                        </div>
                      </div>

                      {scope === "cases" && (
                        <div className="allocation-rule-cases-row">
                          <input
                            type="text"
                            disabled={!editable}
                            aria-label={bilingual(lang, "指定 Case ID", "Case IDs")}
                            placeholder={bilingual(
                              lang,
                              "粘贴 Case ID，用空格或逗号分隔",
                              "Paste Case IDs separated by spaces or commas",
                            )}
                            value={(rule.issue_ids || []).join(" ")}
                            onChange={(e) => {
                              const next = cloneDraft();
                              next.cross_groups[rIdx].issue_ids = e.target.value
                                .trim()
                                .split(/[\s,，]+/u)
                                .filter(Boolean);
                              commitDraft(next, false);
                            }}
                            onBlur={() => onFlush?.()}
                          />
                        </div>
                      )}
                    </div>
                  );
                })}

                <div className="allocation-rules-footer">
                  <button
                    className="text-button allocation-add-member"
                    type="button"
                    disabled={!editable}
                    onClick={() => {
                      const next = cloneDraft();
                      next.pairing_mode = "custom";
                      next.cross_groups.push({ members: [], issue_ids: [], count: null });
                      next.ruleScopes.push("count");
                      commitDraft(next, true);
                    }}
                  >
                    <svg className="allocation-add-icon" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                      <path
                        d="M6 2.2v7.6M2.2 6h7.6"
                        stroke="currentColor"
                        strokeWidth="1.4"
                        strokeLinecap="round"
                      />
                    </svg>
                    <span>{bilingual(lang, "添加定向搭档", "Add partner rule")}</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
