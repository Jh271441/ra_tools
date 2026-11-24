/* Shared group controls for role-free task creation and protected redistribution. */
function newAllocationGroup(groups = []) {
  const ids = new Set(groups.map((group) => group.group_id));
  let index = 1;
  while (ids.has("group-" + index)) index += 1;
  return {
    group_id: "group-" + index,
    coverage_percent: 100,
    coverage_strategy: "overlap",
    members: [{ name: "", review_percent: 100 }],
  };
}

function allocationGroupName(idOrIndex, maybeIndex) {
  const index = typeof maybeIndex === "number" ? maybeIndex : Number(idOrIndex) || 0;
  return uiText("第 " + (index + 1) + " 组", "Group " + (index + 1));
}

function allocationGroupShortBadge(idOrIndex, maybeIndex) {
  const index = typeof maybeIndex === "number" ? maybeIndex : Number(idOrIndex) || 0;
  return uiText((index + 1) + "组", "G" + (index + 1));
}

function allocationGroupOptions(options, selected) {
  return options.map(({ value, label }) => '<option value="' + escapeHtml(value) + '"' +
    (value === selected ? " selected" : "") + ">" + escapeHtml(label) + "</option>").join("");
}

function allocationColorSlot(groupIndex, memberIndex) {
  return (groupIndex * 2 + memberIndex) % 4;
}

function groupAllocationInput(value, label, field, {
  disabled = false, readOnly = false, style = "", unit = "%", min = 0, max = 100, step = 0.01, inputmode = "decimal",
} = {}) {
  return '<span class="assignment-ratio-input"' + (style ? ' style="' + escapeHtml(style) + '"' : '') +
    '><span class="assignment-ratio-box"><input data-group-field="' + field +
    '" aria-label="' + escapeHtml(label) + '" type="number" min="' + min + '" max="' + max +
    '" step="' + step + '" inputmode="' + inputmode + '" required value="' +
    escapeHtml(value ?? "") + '"' + (disabled ? " disabled" : "") + (readOnly ? " readonly" : "") +
    '></span><span class="assignment-ratio-unit" aria-hidden="true">' + escapeHtml(unit) + '</span></span>';
}

function apportionIntegerCounts(total, weights) {
  const intTotal = Math.max(0, Math.round(Number(total) || 0));
  if (!weights.length) return [];
  const sum = weights.reduce((acc, w) => acc + w, 0);
  const divisor = sum || weights.length;
  const parts = weights.map((w, index) => {
    const num = intTotal * (sum ? w : 1);
    return { count: Math.floor(num / divisor), rem: num % divisor, index };
  });
  const leftover = intTotal - parts.reduce((acc, p) => acc + p.count, 0);
  [...parts].sort((a, b) => b.rem - a.rem || a.index - b.index)
    .slice(0, leftover).forEach((p) => { p.count += 1; });
  return parts.map((p) => p.count);
}

function allocationGroupDenom(caseCount, coverageCount, groupCompleted, quotaBasis) {
  const target = Math.max(0, Math.min(caseCount, Math.round(Number(coverageCount) || 0)));
  if (quotaBasis === "remaining") {
    const movable = Math.max(0, target - Math.max(0, Math.round(Number(groupCompleted) || 0)));
    return movable > 0 ? movable : target;
  }
  return target;
}

function coverageCountFromPercent(caseCount, coveragePercent) {
  if (!(caseCount > 0) || !Number.isFinite(coveragePercent)) return null;
  return Math.max(1, Math.min(caseCount, Math.round(caseCount * coveragePercent / 100)));
}

function coveragePercentFromCount(caseCount, count) {
  if (!(caseCount > 0) || !Number.isInteger(count) || count < 1 || count > caseCount) return null;
  return count === caseCount ? 100 : Math.round((count * 10000) / caseCount) / 100;
}

function readAllocationGroupSetup(root) {
  if (!root?.querySelectorAll) return null;
  const number = (input) => input?.value !== "" && Number.isFinite(input?.valueAsNumber) ? input.valueAsNumber : null;
  const inputUnit = root.dataset?.inputUnit === "count" ? "count" : "percent";
  const caseCount = Math.max(0, Math.round(Number(root.dataset?.caseCount || 0)));
  const quotaBasis = root.dataset?.quotaBasis || "total";
  const groups = [...root.querySelectorAll("[data-setup-group]")].map((card) => {
    const covInput = card.querySelector('[data-group-field="coverage"]');
    const rawCov = number(covInput);
    const rawRows = [...card.querySelectorAll("[data-setup-member]")].map((row) => ({
      name: row.querySelector("[data-group-member]").value,
      raw: number(row.querySelector('[data-group-field="share"]')),
    }));
    const strategy = card.querySelector("[data-group-strategy].is-active")?.dataset?.groupStrategy
      || card.querySelector("[data-group-strategy]")?.value
      || "overlap";
    if (inputUnit !== "count" || !(caseCount > 0)) {
      return {
        group_id: card.dataset.setupGroup,
        coverage_percent: rawCov,
        coverage_strategy: strategy,
        members: rawRows.map(({ name, raw }) => ({ name, review_percent: raw })),
      };
    }
    const coverage_percent = covInput?.disabled ? 100 : coveragePercentFromCount(caseCount, rawCov);
    const covCount = covInput?.disabled ? caseCount : rawCov;
    const completed = Math.max(0, Math.round(Number(card.dataset?.groupCompleted || 0)));
    const storedDenom = Math.max(0, Math.round(Number(card.dataset?.memberDenom || 0)));
    const denom = storedDenom || (Number.isInteger(covCount) ? allocationGroupDenom(caseCount, covCount, completed, quotaBasis) : 0);
    const selectedIndices = [];
    const selectedCounts = [];
    let allInts = denom > 0;
    rawRows.forEach((item, idx) => {
      if (!item.name) return;
      selectedIndices.push(idx);
      if (item.raw != null && Number.isInteger(item.raw) && item.raw >= 0) selectedCounts.push(item.raw);
      else allInts = false;
    });
    const sumCounts = selectedCounts.reduce((acc, v) => acc + v, 0);
    let converted = null;
    if (allInts && selectedIndices.length && sumCounts === denom) {
      converted = splitGroupShares(10000, selectedCounts);
    }
    let selCursor = 0;
    const members = rawRows.map(({ name, raw }) => {
      if (!name) return { name, review_percent: 0 };
      if (converted) return { name, review_percent: converted[selCursor++] };
      if (raw == null || !Number.isInteger(raw) || raw < 0 || !(denom > 0)) return { name, review_percent: null };
      return { name, review_percent: Math.round((raw * 10000) / denom) / 100 };
    });
    return {
      group_id: card.dataset.setupGroup,
      coverage_percent,
      coverage_strategy: strategy,
      members,
    };
  });
  const pairing_mode = root.querySelector?.("[data-pairing-mode].is-active")?.dataset?.pairingMode || "orthogonal";
  const ruleRows = [...root.querySelectorAll("[data-setup-rule]")];
  const ruleScopes = ruleRows.map((row) => row.dataset.ruleScope || "count");
  const cross_groups = pairing_mode === "custom" ? ruleRows.map((row) => {
    const scope = row.dataset.ruleScope || "count";
    const members = [...row.querySelectorAll("[data-rule-group-member]")]
      .map((control) => (control.value ? { group_id: control.dataset.ruleGroupMember, name: control.value } : null))
      .filter(Boolean);
    const issueInput = row.querySelector("[data-rule-cases]");
    const issue_ids = scope === "cases" && issueInput
      ? issueInput.value.trim().split(/[\s,，]+/u).filter(Boolean)
      : [];
    const count = scope === "count" ? number(row.querySelector("[data-rule-count]")) : null;
    return { members, issue_ids, count };
  }) : [];
  return {
    groups,
    cross_groups,
    pairing_mode,
    ruleScopes,
    inputUnit,
  };
}

function allocationPercentUnits(value) {
  if (!Number.isFinite(value) || value < 0 || value > 100) return null;
  const scaled = value * 100;
  const units = Math.round(scaled);
  return Math.abs(scaled - units) < 1e-7 ? units : null;
}

function splitGroupShares(total, weights) {
  const sum = weights.reduce((count, weight) => count + weight, 0);
  const divisor = sum || weights.length;
  const portions = weights.map((weight, index) => {
    const numerator = total * (sum ? weight : 1);
    return { units: Math.floor(numerator / divisor), remainder: numerator % divisor, index };
  });
  const leftover = total - portions.reduce((count, portion) => count + portion.units, 0);
  [...portions].sort((a, b) => b.remainder - a.remainder || a.index - b.index)
    .slice(0, leftover).forEach((portion) => { portion.units += 1; });
  return portions.map((portion) => portion.units / 100);
}

function completeGroupShares(members, even = false) {
  const selected = members.filter((member) => member.name);
  if (!selected.length) return;
  const shares = splitGroupShares(10000, selected.map((member) => even ? 1 : allocationPercentUnits(member.review_percent) ?? 0));
  selected.forEach((member, index) => { member.review_percent = shares[index]; });
}

function rebalanceGroupShare(input, edit) {
  const card = input.closest("[data-setup-group]");
  const root = card?.closest?.("[data-input-unit]");
  const isCount = root?.dataset?.inputUnit === "count";
  if (edit?.input !== input) {
    const shares = [...card.querySelectorAll("[data-setup-member]")]
      .filter((row) => row.querySelector("[data-group-member]").value)
      .map((row) => row.querySelector('[data-group-field="share"]'));
    if (!shares.includes(input) || shares.length < 2) return null;
    const peers = shares.filter((share) => share !== input);
    const readWeight = (el) => {
      if (isCount) {
        const v = el.value === "" ? NaN : Number(el.value);
        return Number.isInteger(v) && v >= 0 ? v : 0;
      }
      return allocationPercentUnits(el.valueAsNumber) ?? 0;
    };
    const history = Array.isArray(card._pinnedShares)
      ? card._pinnedShares.filter((el) => shares.includes(el) && el !== input)
      : [];
    let pinnedPeers = peers.filter((peer) => history.includes(peer));
    let freePeers = peers.filter((peer) => !history.includes(peer));
    let releasedPeer = null;
    if (!freePeers.length && pinnedPeers.length) {
      releasedPeer = history[0] || pinnedPeers[0];
      pinnedPeers = pinnedPeers.filter((peer) => peer !== releasedPeer);
      freePeers = [releasedPeer];
    }
    const pinnedInitial = pinnedPeers.map(readWeight);
    const pinnedSum = pinnedInitial.reduce((acc, w) => acc + w, 0);
    const freeWeights = freePeers.map(readWeight);
    const denom = isCount ? Math.max(0, Math.round(Number(card.dataset?.memberDenom || 0))) : 10000;
    edit = {
      input, card, shares, isCount, denom,
      pinnedPeers, pinnedInitial, pinnedSum,
      freePeers, freeWeights, releasedPeer,
    };
  }
  const commitPin = () => {
    const prev = Array.isArray(edit.card._pinnedShares) ? edit.card._pinnedShares : [];
    const next = prev.filter((el) => edit.shares.includes(el) && el !== edit.input && el !== edit.releasedPeer);
    next.push(edit.input);
    edit.card._pinnedShares = next;
  };
  if (edit.isCount) {
    const val = input.value === "" ? NaN : Number(input.value);
    if (Number.isInteger(val) && val >= 0 && val <= edit.denom) {
      const rem = edit.denom - val;
      if (rem >= edit.pinnedSum) {
        edit.pinnedPeers.forEach((peer, index) => { peer.value = String(edit.pinnedInitial[index]); });
        const counts = apportionIntegerCounts(rem - edit.pinnedSum, edit.freeWeights);
        edit.freePeers.forEach((peer, index) => { peer.value = String(counts[index]); });
      } else {
        edit.freePeers.forEach((peer) => { peer.value = "0"; });
        const counts = apportionIntegerCounts(rem, edit.pinnedInitial);
        edit.pinnedPeers.forEach((peer, index) => { peer.value = String(counts[index]); });
      }
      commitPin();
    }
    return edit;
  }
  const units = allocationPercentUnits(input.valueAsNumber);
  if (units != null) {
    const rem = 10000 - units;
    if (rem >= edit.pinnedSum) {
      edit.pinnedPeers.forEach((peer, index) => { peer.value = String(edit.pinnedInitial[index] / 100); });
      const shares = splitGroupShares(rem - edit.pinnedSum, edit.freeWeights);
      edit.freePeers.forEach((peer, index) => { peer.value = String(shares[index]); });
    } else {
      edit.freePeers.forEach((peer) => { peer.value = "0"; });
      const shares = splitGroupShares(rem, edit.pinnedInitial);
      edit.pinnedPeers.forEach((peer, index) => { peer.value = String(shares[index]); });
    }
    commitPin();
  }
  return edit;
}

function moveAllocationGroupMember(draft, fromGroupIndex, fromMemberIndex, toGroupIndex, toSlot) {
  const groups = draft?.groups || [];
  const sourceGroup = groups[fromGroupIndex];
  const targetGroup = groups[toGroupIndex];
  if (!sourceGroup || !targetGroup) return { moved: false, reason: "invalid" };
  const sourceMember = sourceGroup.members?.[fromMemberIndex];
  if (!sourceMember?.name) return { moved: false, reason: "empty" };
  const rawSlot = Number.isInteger(toSlot) ? toSlot : targetGroup.members.length;
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
    };
  }

  if (targetGroup.members.some((member) => member.name === sourceMember.name)) {
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
    completeGroupShares(sourceGroup.members);
  }

  const targetSelected = targetGroup.members.filter((member) => member.name);
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

  if (Array.isArray(draft.cross_groups)) {
    draft.cross_groups.forEach((rule) => {
      if (!Array.isArray(rule.members)) return;
      rule.members = rule.members.filter(
        (person) => !(person.group_id === sourceGroup.group_id && person.name === item.name),
      );
    });
  }

  return {
    moved: true,
    sameGroup: false,
    memberName: item.name,
    targetGroupIndex: toGroupIndex,
    targetMemberIndex: insertedIndex,
  };
}

function computeGroupEqualizeSuggestion(members, { unit = "percent", denom = 100 } = {}) {
  const selected = (members || []).filter((person) => person?.name);
  if (selected.length < 2) return null;
  const number = new Intl.NumberFormat(typeof i18nLocale === "function" ? i18nLocale() : "zh-CN", { maximumFractionDigits: 2 });
  if (unit === "count" && denom > 0) {
    const evenCounts = apportionIntegerCounts(denom, selected.map(() => 1));
    const vals = selected.map((person) => {
      const v = Number(person.review_percent);
      return Number.isInteger(v) && v >= 0 ? v : null;
    });
    const sum = vals.reduce((acc, v) => acc + (v ?? 0), 0);
    const alreadyEven = vals.every((v) => v != null) && sum === denom && (Math.max(...vals) - Math.min(...vals) <= 1);
    if (alreadyEven) return null;
    const uniform = new Set(evenCounts).size === 1;
    const textZh = uniform
      ? "可一键均分：每人 " + number.format(evenCounts[0]) + " 条"
      : "可一键均分：" + selected.map((p, i) => p.name + " " + number.format(evenCounts[i]) + " 条").join(" · ");
    const textEn = uniform
      ? "Even split: " + number.format(evenCounts[0]) + " cases each"
      : "Even split: " + selected.map((p, i) => p.name + " " + number.format(evenCounts[i])).join(" · ");
    return { shares: evenCounts, textZh, textEn };
  }
  const evenShares = splitGroupShares(10000, selected.map(() => 1));
  const units = selected.map((person) => allocationPercentUnits(Number(person.review_percent)));
  const alreadyEven = units.every((val, idx) => val != null && val === Math.round(evenShares[idx] * 100));
  if (alreadyEven) return null;
  const uniform = new Set(evenShares).size === 1;
  const textZh = uniform
    ? "可一键均分：每人 " + number.format(evenShares[0]) + "%"
    : "可一键均分：" + selected.map((p, i) => p.name + " " + number.format(evenShares[i]) + "%").join(" · ");
  const textEn = uniform
    ? "Even split: " + number.format(evenShares[0]) + "% each"
    : "Even split: " + selected.map((p, i) => p.name + " " + number.format(evenShares[i]) + "%").join(" · ");
  return { shares: evenShares, textZh, textEn };
}

function groupAllocationSetupError(draft) {
  const invalid = (value) => allocationPercentUnits(value) == null;
  if (!draft?.groups?.length || draft.groups.some((group) => !group.members.length ||
      group.members.some((person) => !person.name))) {
    return apiResponseError("请为每组选择成员。", "Select members for each group.");
  }
  if (draft.groups.some((group) => invalid(group.coverage_percent) || group.coverage_percent <= 0 ||
      group.members.some((member) => invalid(member.review_percent)) ||
      group.members.reduce((sum, person) => sum + Math.round(person.review_percent * 100), 0) !== 10000)) {
    return draft.inputUnit === "count"
      ? apiResponseError("请检查覆盖条数，各组的成员条数须分别合计等于该组配额。",
          "Check coverage counts and make member counts total each group's quota.")
      : apiResponseError("请检查覆盖率，各组的成员比例须分别合计 100%。",
          "Check coverage and make the member shares in each group total 100%.");
  }
  if (draft.groups.some((group) => new Set(group.members.map((person) => person.name)).size !== group.members.length)) {
    return apiResponseError("同一组内的成员不能重复。", "Members must be distinct within each group.");
  }
  if (draft.cross_groups.some((rule) => rule.members.length < 2 ||
      new Set(rule.members.map((person) => person.group_id)).size !== rule.members.length ||
      new Set(rule.members.map((person) => person.name)).size !== rule.members.length ||
      Boolean(rule.issue_ids.length) === (rule.count != null) ||
      rule.count != null && (!Number.isSafeInteger(rule.count) || rule.count < 1))) {
    return apiResponseError("为每条规则选择不同组的搭档，并填写 Case ID 或数量。",
      "Select partners from different groups and enter Case IDs or a count for each rule.");
  }
  return null;
}

function groupAllocationRuleSlot(group, groupIndex, selectedName, optional) {
  const badge = allocationGroupShortBadge(group.group_id, groupIndex);
  const prompt = optional ? uiText("不限", "Any") : uiText("选择成员", "Select member");
  const members = (group.members || []).filter((person) => person.name);
  const options = [{ value: "", label: prompt }, ...members.map((person) => ({
    value: person.name, label: person.name,
  }))];
  const value = selectedName || "";
  if (value && !options.some((option) => option.value === value)) {
    options.push({ value, label: value + " · " + uiText("已移除", "Removed") });
  }
  const memberIdx = Math.max(0, members.findIndex((person) => person.name === value));
  const slot = allocationColorSlot(groupIndex, value ? memberIdx : 0);
  const swatchStyle = value
    ? "--member-swatch:var(--allocation-swatch-" + slot + ")"
    : "--member-swatch:var(--faint)";
  return '<div class="allocation-rule-slot" style="' + swatchStyle + '">' +
    '<span class="allocation-rule-slot-tag">' +
    '<span class="allocation-member-swatch" aria-hidden="true"></span>' +
    '<span>' + escapeHtml(badge) + '</span></span>' +
    '<select data-rule-group-member="' + escapeHtml(group.group_id) + '" aria-label="' +
    escapeHtml(allocationGroupName(group.group_id, groupIndex) + " · " + prompt) + '">' +
    allocationGroupOptions(options, value) + '</select></div>';
}

function renderAllocationPairedChips(groups) {
  if (groups.length < 2) return "";
  const lists = groups.map((group, gIdx) =>
    (group.members || [])
      .map((person, mIdx) => ({ name: person.name, share: Number(person.review_percent) || 0, slot: allocationColorSlot(gIdx, mIdx) }))
      .filter((person) => person.name && person.share > 0)
  );
  const g0 = lists[0] || [];
  if (!g0.length || lists.slice(1).every((list) => !list.length)) return "";
  const pairCount = Math.max(...lists.map((list) => list.length));
  const chips = Array.from({ length: pairCount }, (_, idx) => {
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
    return '<span class="allocation-paired-chip">' + members.map((item) =>
      '<span class="allocation-paired-member"><i class="allocation-member-swatch" style="--member-swatch:var(--allocation-swatch-' +
      item.slot + ')" aria-hidden="true"></i>' + escapeHtml(item.name) + '</span>'
    ).join('<span class="allocation-paired-sep" aria-hidden="true">↔</span>') + '</span>';
  }).join("");
  return '<div class="allocation-paired-chips" data-paired-preview>' + chips + '</div>';
}

function renderAllocationGroupSetup(root, draft, options) {
  const { users, editable = true, change, onUnitChange } = options;
  const caseCount = Math.max(0, Math.round(Number(options.caseCount) || 0));
  const quotaBasis = options.quotaBasis || "total";
  const groupCompleted = options.groupCompleted || {};
  const inputUnit = draft.inputUnit === "count" && caseCount > 0 ? "count" : "percent";
  const isCount = inputUnit === "count";
  const groups = draft.groups?.length ? draft.groups : [newAllocationGroup()];
  const rules = draft.cross_groups || [];
  const empty = uiText("选择成员", "Select a member");
  const coverageLabel = isCount ? uiText("覆盖条数", "Coverage cases") : uiText("覆盖率", "Coverage");
  const shareLabel = isCount ? uiText("组内条数", "Group cases") : uiText("组内比例", "Group share");
  const unitText = isCount ? uiText("条", "cases") : "%";
  const removeMember = uiText("移除成员", "Remove member");
  const singleGroup = groups.length === 1;
  const candidates = users.filter((user) => ["writer", "admin"].includes(user.role));

  root.dataset.inputUnit = inputUnit;
  root.dataset.caseCount = String(caseCount);
  root.dataset.quotaBasis = quotaBasis;

  const cards = groups.map((group, index) => {
    const groupName = allocationGroupName(group.group_id, index);
    const removeGroup = uiText("移除" + groupName, "Remove " + groupName);
    const members = group.members.length ? group.members : [{ name: "", review_percent: 100 }];
    const selectedMembers = members.filter((person) => person.name);
    if (selectedMembers.length === 1 && selectedMembers[0].review_percent !== 100) {
      selectedMembers[0].review_percent = 100;
    }
    const singleMember = selectedMembers.length === 1;
    const completedInGroup = Math.max(0, Math.round(Number(groupCompleted[group.group_id]) || 0));
    const covCount = isCount
      ? (singleGroup ? caseCount : (coverageCountFromPercent(caseCount, Number(group.coverage_percent)) ?? caseCount))
      : null;
    const memberDenom = isCount ? allocationGroupDenom(caseCount, covCount, completedInGroup, quotaBasis) : 100;
    const apportionedCounts = isCount
      ? apportionIntegerCounts(memberDenom, selectedMembers.map((person) => allocationPercentUnits(Number(person.review_percent)) ?? 0))
      : null;
    let countCursor = 0;
    const displayMembers = members.map((person) => {
      if (!isCount) return person;
      const val = person.name ? apportionedCounts[countCursor++] : 0;
      return { ...person, review_percent: val };
    });
    const suggestion = editable
      ? computeGroupEqualizeSuggestion(displayMembers, { unit: inputUnit, denom: memberDenom })
      : null;
    const dragHelp = uiText(
      "拖动调整顺序或移至其他组（聚焦后也可用方向键）",
      "Drag to reorder or move to another group (arrow keys supported)",
    );
    const canDragGroup = editable && (groups.length > 1 || selectedMembers.length > 1);
    const card = displayMembers.map((person, memberIndex) => {
      const slot = allocationColorSlot(index, memberIndex);
      const val = Number(person.review_percent) || 0;
      const pct = isCount
        ? (memberDenom > 0 ? Math.max(0, Math.min(100, (100 * val) / memberDenom)) : 0)
        : Math.max(0, Math.min(100, val));
      const names = [{ value: "", label: empty }, ...candidates.map((user) => ({
        value: user.username, label: user.username,
      }))];
      if (person.name && !names.some((item) => item.value === person.name)) {
        names.push({ value: person.name, label: person.name + " · " + uiText("不可用", "Unavailable") });
      }
      const rowStyle = "--member-swatch:var(--allocation-swatch-" + slot + ");--share-color:var(--allocation-swatch-" + slot + ")";
      const canDragRow = canDragGroup && Boolean(person.name);
      const leadingControl = canDragRow
        ? '<button class="allocation-drag-handle" type="button" data-drag-handle aria-label="' +
          escapeHtml(person.name + " · " + dragHelp) + '" title="' + escapeHtml(dragHelp) + '">' +
          '<span class="allocation-drag-swatch" aria-hidden="true"></span>' +
          '<svg class="allocation-drag-grip" viewBox="0 0 8 14" fill="currentColor" aria-hidden="true">' +
          '<circle cx="2" cy="3" r="1.15"/><circle cx="6" cy="3" r="1.15"/>' +
          '<circle cx="2" cy="7" r="1.15"/><circle cx="6" cy="7" r="1.15"/>' +
          '<circle cx="2" cy="11" r="1.15"/><circle cx="6" cy="11" r="1.15"/></svg></button>'
        : '<span class="allocation-member-swatch" aria-hidden="true"></span>';
      return '<div class="allocation-setup-member" data-setup-member data-empty="' + String(!person.name) +
        '" data-draggable="' + String(canDragRow) + '" style="' + rowStyle + '">' +
        leadingControl +
        '<select data-group-member aria-label="' +
        escapeHtml(empty) + '">' + allocationGroupOptions(names, person.name) + '</select>' +
        groupAllocationInput(person.review_percent, shareLabel, "share", {
          disabled: !person.name,
          readOnly: singleMember,
          style: "--share-fill:" + pct + "%",
          unit: unitText,
          min: 0,
          max: isCount ? memberDenom : 100,
          step: isCount ? 1 : 0.01,
          inputmode: isCount ? "numeric" : "decimal",
        }) +
        '<button class="allocation-remove-control" type="button" data-setup-action="remove-member" aria-label="' +
        escapeHtml(removeMember) + '" title="' + escapeHtml(removeMember) + '">×</button></div>';
    }).join("");
    const coverageControl = singleGroup
      ? '<span class="allocation-coverage-pill">' +
        escapeHtml(isCount ? uiText("覆盖 " + caseCount + " 条", caseCount + " cases") : uiText("覆盖 100%", "100% cover")) +
        '<input data-group-field="coverage" aria-label="' + escapeHtml(coverageLabel) +
        '" type="number" value="' + (isCount ? caseCount : 100) + '" disabled hidden></span>'
      : '<label class="allocation-coverage-inline"><span>' + escapeHtml(uiText("覆盖", "Cover")) + '</span>' +
        groupAllocationInput(isCount ? covCount : group.coverage_percent, coverageLabel, "coverage", {
          unit: unitText,
          min: isCount ? 1 : 0,
          max: isCount ? caseCount : 100,
          step: isCount ? 1 : 0.01,
          inputmode: isCount ? "numeric" : "decimal",
        }) + '</label>';
    const equalizeTitle = suggestion
      ? uiText(suggestion.textZh, suggestion.textEn)
      : uiText("当前组已均分", "Already evenly split");
    const equalizeBtn = '<button class="text-button allocation-tool-link allocation-equalize-btn" type="button" data-setup-action="equalize" data-group-equalize' +
      (selectedMembers.length < 2 ? ' hidden' : '') +
      (!suggestion || !editable ? ' disabled' : ' data-needs-equalize="true"') +
      ' aria-label="' + escapeHtml(uiText(groupName + "均分", "Even split " + groupName)) + '"' +
      ' title="' + escapeHtml(equalizeTitle) + '">' +
      escapeHtml(uiText("均分", "Even split")) + '</button>';
    const strategyVal = group.coverage_strategy === "fill" ? "fill" : "overlap";
    const isPartial = isCount ? (covCount < caseCount) : (group.coverage_percent < 100);
    const strategySwitch = index > 0
      ? '<div class="allocation-strategy-switch" data-strategy-field role="group" aria-label="' +
        escapeHtml(uiText("覆盖策略", "Coverage strategy")) + '"' +
        (isPartial && !singleGroup ? '' : ' hidden') + '>' +
        '<button type="button" data-setup-action="group-strategy" data-group-strategy="overlap"' +
        (strategyVal === "overlap" ? ' class="is-active" aria-pressed="true"' : ' aria-pressed="false"') +
        ' title="' + escapeHtml(uiText("优先与前组重叠", "Prefer overlap with earlier groups")) + '">' +
        escapeHtml(uiText("重叠前组", "Overlap")) + '</button>' +
        '<button type="button" data-setup-action="group-strategy" data-group-strategy="fill"' +
        (strategyVal === "fill" ? ' class="is-active" aria-pressed="true"' : ' aria-pressed="false"') +
        ' title="' + escapeHtml(uiText("优先补未交叉 Case", "Prefer cases without cross-review")) + '">' +
        escapeHtml(uiText("补未交叉", "Fill gaps")) + '</button></div>'
      : '';
    return '<section class="allocation-setup-card" data-setup-group="' + escapeHtml(group.group_id) +
      '" data-member-denom="' + memberDenom + '" data-group-completed="' + completedInGroup + '">' +
      '<header class="allocation-setup-header"><div class="allocation-setup-title"><strong>' +
      escapeHtml(groupName) + '</strong>' + coverageControl +
      '<span data-group-share aria-live="polite" hidden></span></div>' +
      '<div class="allocation-setup-tools">' + equalizeBtn +
      (!singleGroup ? '<button class="text-button allocation-tool-link" type="button" data-setup-action="remove-group" aria-label="' +
        escapeHtml(removeGroup) + '">' +
        escapeHtml(uiText("移除", "Remove")) + '</button>' : '') + '</div></header>' +
      '<div class="allocation-setup-members">' + card + '</div>' +
      '<div class="allocation-setup-actions"><button class="text-button allocation-add-member" type="button" data-setup-action="add-member">' +
      '<svg class="allocation-add-icon" viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M6 2.2v7.6M2.2 6h7.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>' +
      '<span>' + escapeHtml(uiText("添加成员", "Add member")) + '</span></button>' + strategySwitch + '</div></section>';
  }).join("");

  const pairingMode = draft.pairing_mode || (rules.length ? "custom" : "orthogonal");
  const rulesMarkup = pairingMode === "custom" ? rules.map((rule, index) => {
    const scope = draft.ruleScopes?.[index] || (rule.issue_ids?.length ? "cases" : "count");
    const byGroup = new Map((rule.members || []).map((person) => [person.group_id, person.name]));
    const slotsHtml = groups.map((group, gIdx) =>
      groupAllocationRuleSlot(group, gIdx, byGroup.get(group.group_id) || "", groups.length > 2)
    ).join('<span class="allocation-rule-times" aria-hidden="true">×</span>');
    return '<div class="allocation-setup-rule" data-setup-rule data-rule-scope="' + escapeHtml(scope) + '">' +
      '<div class="allocation-rule-main">' +
      '<div class="allocation-rule-pickers">' + slotsHtml + '</div>' +
      '<div class="allocation-rule-scope-controls">' +
      '<div class="allocation-rule-scope-switch" role="group" aria-label="' + escapeHtml(uiText("范围方式", "Scope mode")) + '">' +
      '<button type="button" class="' + (scope === "count" ? "is-active" : "") + '" data-setup-action="rule-scope" data-scope-value="count">' +
      escapeHtml(uiText("按数量", "Count")) + '</button>' +
      '<button type="button" class="' + (scope === "cases" ? "is-active" : "") + '" data-setup-action="rule-scope" data-scope-value="cases">' +
      escapeHtml(uiText("按 Case", "Cases")) + '</button></div>' +
      (scope === "count"
        ? '<span class="allocation-rule-count-box"><input type="number" min="1" step="1" inputmode="numeric" data-rule-count aria-label="' +
          escapeHtml(uiText("共同复核数量", "Shared case count")) + '" placeholder="10" value="' +
          escapeHtml(rule.count ?? "") + '"><span class="assignment-ratio-unit" aria-hidden="true">' + escapeHtml(uiText("条", "cases")) + '</span></span>'
        : '') +
      '<button class="allocation-remove-control" type="button" data-setup-action="remove-rule" aria-label="' +
      escapeHtml(uiText("移除规则", "Remove rule")) + '" title="' + escapeHtml(uiText("移除规则", "Remove rule")) + '">×</button>' +
      '</div></div>' +
      (scope === "cases"
        ? '<div class="allocation-rule-cases-row"><input type="text" data-rule-cases aria-label="' +
          escapeHtml(uiText("指定 Case ID", "Case IDs")) + '" placeholder="' +
          escapeHtml(uiText("粘贴 Case ID，用空格或逗号分隔", "Paste Case IDs separated by spaces or commas")) + '" value="' +
          escapeHtml((rule.issue_ids || []).join(" ")) + '"></div>'
        : '') +
      '</div>';
  }).join("") : "";

  const rulesHelpLabel = uiText("跨组配对说明", "Cross-group pairing help");
  const rulesInfoMarkup = '<span class="model-review-run-help ui-info allocation-rules-info" data-ui-info data-ui-info-align="end">' +
    '<button class="ui-info-button" type="button" data-ui-info-trigger aria-expanded="false" aria-label="' +
    escapeHtml(rulesHelpLabel) + '" title="' + escapeHtml(rulesHelpLabel) + '">' +
    '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true">' +
    '<circle cx="10" cy="10" r="7.5" stroke="currentColor" stroke-width="1.4"/>' +
    '<path d="M10 9.1v4.6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
    '<circle cx="10" cy="6.3" r=".9" fill="currentColor"/></svg></button>' +
    '<span class="model-review-run-tooltip ui-info-tooltip" role="dialog">' +
    '<strong>' + escapeHtml(uiText("跨组配对方式", "Cross-group pairing modes")) + '</strong>' +
    '<span>' + escapeHtml(uiText("正交打散（默认）：按各组比例自动均匀交叉打散。", "Orthogonal (default): automatically balances cross-group pairs by member shares.")) + '</span>' +
    '<span>' + escapeHtml(uiText("固定结对：按组内成员顺序 1 对 1 结对。", "1-to-1 paired: matches members sequentially across groups.")) + '</span>' +
    '<span>' + escapeHtml(uiText("定向规则：指定特定搭档共同复核固定条数或指定 Case，其余自动正交打散。", "Custom: pin specific partners to a count or exact Case IDs; remaining cases stay orthogonal.")) + '</span>' +
    '</span></span>';

  const modeBtn = (mode, zh, en) => '<button type="button" data-setup-action="pairing-mode" data-pairing-mode="' + mode + '"' +
    (pairingMode === mode ? ' class="is-active" aria-pressed="true"' : ' aria-pressed="false"') + '>' +
    escapeHtml(uiText(zh, en)) + '</button>';

  const pairingSectionMarkup = groups.length > 1
    ? '<div class="allocation-pairing-section">' +
      '<div class="allocation-pairing-bar">' +
      '<div class="allocation-pairing-left">' +
      '<span class="allocation-pairing-label">' + escapeHtml(uiText("跨组配对", "Cross-pairing")) + '</span>' +
      '<div class="allocation-pairing-switch" role="group" aria-label="' + escapeHtml(uiText("跨组配对方式", "Cross-group pairing mode")) + '">' +
      modeBtn("orthogonal", "正交打散", "Orthogonal") +
      modeBtn("paired", "固定结对", "1-to-1") +
      modeBtn("custom", "定向规则", "Custom") +
      '</div></div>' +
      rulesInfoMarkup + '</div>' +
      (pairingMode === "paired" ? renderAllocationPairedChips(groups) : '') +
      (pairingMode === "custom"
        ? '<div class="allocation-custom-rules">' + rulesMarkup +
          '<div class="allocation-rules-footer"><button class="text-button allocation-add-member" type="button" data-setup-action="add-rule">' +
          '<svg class="allocation-add-icon" viewBox="0 0 12 12" fill="none" aria-hidden="true"><path d="M6 2.2v7.6M2.2 6h7.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>' +
          '<span>' + escapeHtml(uiText("添加定向搭档", "Add partner rule")) + '</span></button></div></div>'
        : '') +
      '</div>'
    : '';

  const unitSwitchMarkup = '<div class="allocation-unit-switch" role="group" aria-label="' +
    escapeHtml(uiText("数值单位", "Input unit")) + '">' +
    '<button type="button" data-setup-action="input-unit" data-input-unit="percent"' +
    (!isCount ? ' class="is-active" aria-pressed="true"' : ' aria-pressed="false"') +
    ' title="' + escapeHtml(uiText("按百分比输入", "Enter percentages")) + '">%</button>' +
    '<button type="button" data-setup-action="input-unit" data-input-unit="count"' +
    (isCount ? ' class="is-active" aria-pressed="true"' : ' aria-pressed="false"') +
    (!(caseCount > 0) ? ' disabled' : '') +
    ' title="' + escapeHtml(uiText("按具体条数输入", "Enter exact case counts")) + '">' +
    escapeHtml(uiText("条", "Count")) + '</button></div>';

  root.innerHTML = '<div class="allocation-setup-bar"><span class="allocation-setup-bar-title"><span>' +
    escapeHtml(uiText("分配组", "Allocation groups")) + '</span><small data-setup-summary></small></span>' +
    '<div class="allocation-setup-bar-tools">' + unitSwitchMarkup +
    '<button class="button button-secondary allocation-compact-btn allocation-add-group" type="button" data-setup-action="add-group">+ ' +
    escapeHtml(uiText("添加分配组", "Add group")) + '</button></div></div>' +
    '<div class="allocation-setup-surface">' +
    '<div class="allocation-setup-cards" data-group-count="' + groups.length + '">' + cards + '</div>' +
    '<p class="allocation-drag-status" data-drag-status role="status" aria-live="polite" hidden></p>' +
    pairingSectionMarkup + '</div>';

  if (!editable) root.querySelectorAll("input, button:not(.ui-info-button):not([data-input-unit]), select, textarea").forEach((control) => { control.disabled = true; });
  root.querySelectorAll("select").forEach((select) => enhanceNativeUiSelect(select));
  updateGroupSetupIndicators(root);
  bindAllocationMemberDrag(root, options, change);

  let shareEdit = null;
  const applyEqualizeForGroup = (groupIndex) => {
    const next = readAllocationGroupSetup(root);
    const targetGroup = next?.groups?.[groupIndex];
    if (!targetGroup) return;
    completeGroupShares(targetGroup.members, true);
    renderAllocationGroupSetup(root, next, options);
    const newCard = root.querySelectorAll("[data-setup-group]")[groupIndex];
    newCard?.querySelector('[data-setup-action="add-member"]')?.focus({ preventScroll: true });
    change?.({ immediate: true });
  };

  const refresh = (input, meta = {}) => {
    if (isCount && input.matches('[data-group-field="coverage"]')) {
      const card = input.closest("[data-setup-group]");
      const covVal = input.value === "" ? NaN : Number(input.value);
      const completedInGroup = Math.max(0, Math.round(Number(card?.dataset?.groupCompleted || 0)));
      if (card && Number.isInteger(covVal) && covVal >= 1 && covVal <= caseCount) {
        const newDenom = allocationGroupDenom(caseCount, covVal, completedInGroup, quotaBasis);
        const oldDenom = Math.max(0, Math.round(Number(card.dataset.memberDenom || 0)));
        if (newDenom > 0 && newDenom !== oldDenom) {
          card.dataset.memberDenom = String(newDenom);
          card._pinnedShares = [];
          const memberRows = [...card.querySelectorAll("[data-setup-member]")];
          const selectedInputs = memberRows
            .filter((row) => row.querySelector("[data-group-member]").value)
            .map((row) => row.querySelector('[data-group-field="share"]'));
          const weights = selectedInputs.map((el) => {
            const v = el.value === "" ? NaN : Number(el.value);
            return Number.isInteger(v) && v >= 0 ? v : 0;
          });
          const rescaled = apportionIntegerCounts(newDenom, weights);
          selectedInputs.forEach((el, idx) => {
            el.max = String(newDenom);
            el.value = String(rescaled[idx]);
          });
          shareEdit = null;
        }
      }
    }
    if (input.matches('[data-group-field="share"]')) shareEdit = rebalanceGroupShare(input, shareEdit);
    updateGroupSetupIndicators(root);
    change?.(meta);
  };
  root.onfocusout = (event) => {
    if (event.target === shareEdit?.input) shareEdit = null;
    if (event.target?.matches?.('[data-group-field], [data-rule-count], [data-rule-cases]')) {
      options?.flush?.();
    }
  };
  root.oninput = (event) => {
    if (!event.isComposing && !event.target.matches("select")) refresh(event.target, { immediate: false });
  };
  root.onchange = (event) => {
    if (event.target.matches("[data-group-member]")) {
      const next = readAllocationGroupSetup(root);
      const cardsList = [...root.querySelectorAll("[data-setup-group]")];
      const groupIdx = cardsList.indexOf(event.target.closest("[data-setup-group]"));
      const memberIdx = [...cardsList[groupIdx].querySelectorAll("[data-group-member]")].indexOf(event.target);
      const selected = next.groups[groupIdx].members.filter((m) => m.name);
      // Sole member defaults to 100%; 2+ members preserve existing shares and surface the click/Enter equalize bar.
      if (selected.length === 1) selected[0].review_percent = 100;
      renderAllocationGroupSetup(root, next, options);
      root.querySelectorAll("[data-setup-group]")[groupIdx]?.querySelectorAll("[data-setup-member]")[memberIdx]
        ?.querySelector(".ui-select-trigger")?.focus({ preventScroll: true });
      change?.({ immediate: true });
      return;
    }
    refresh(event.target, { immediate: true });
  };
  root.onclick = (event) => {
    const infoWrap = event.target.closest?.(".allocation-rules-info");
    if (infoWrap) {
      event.preventDefault();
      event.stopPropagation();
      if (typeof showUiInfoPopover === "function" && typeof closeUiInfoPopovers === "function") {
        if (infoWrap.classList.contains("is-open") && infoWrap.dataset.uiInfoPinned) closeUiInfoPopovers(document);
        else showUiInfoPopover(infoWrap, document, { pinned: true });
      }
      return;
    }
    const control = event.target.closest("[data-setup-action]");
    if (!control) return;
    const action = control.dataset.setupAction;
    if (action === "input-unit") {
      const targetUnit = control.dataset.inputUnit === "count" && caseCount > 0 ? "count" : "percent";
      if (targetUnit === inputUnit) return;
      const next = readAllocationGroupSetup(root);
      next.inputUnit = targetUnit;
      renderAllocationGroupSetup(root, next, options);
      onUnitChange?.(targetUnit);
      root.querySelector('[data-setup-action="input-unit"][data-input-unit="' + targetUnit + '"]')?.focus({ preventScroll: true });
      return;
    }
    if (!editable) return;
    const next = readAllocationGroupSetup(root);
    const card = control.closest("[data-setup-group]");
    const groupIndex = [...root.querySelectorAll("[data-setup-group]")].indexOf(card);
    const group = next.groups[groupIndex];
    const ruleIndex = [...root.querySelectorAll("[data-setup-rule]")].indexOf(control.closest("[data-setup-rule]"));
    if (action === "equalize") {
      applyEqualizeForGroup(groupIndex);
      return;
    }
    if (action === "group-strategy" && group) {
      group.coverage_strategy = control.dataset.groupStrategy === "fill" ? "fill" : "overlap";
    }
    if (action === "pairing-mode") {
      const targetMode = control.dataset.pairingMode || "orthogonal";
      next.pairing_mode = targetMode;
      if (targetMode === "custom" && !next.cross_groups.length) {
        const used = new Set();
        const defaultMembers = next.groups
          .map((g) => {
            const first = g.members.find((m) => m.name && (Number(m.review_percent) || 0) > 0 && !used.has(m.name))
              || g.members.find((m) => m.name && !used.has(m.name));
            if (!first) return null;
            used.add(first.name);
            return { group_id: g.group_id, name: first.name };
          })
          .filter(Boolean);
        next.cross_groups = [{ members: defaultMembers.slice(0, 2), issue_ids: [], count: null }];
        next.ruleScopes = ["count"];
      } else if (targetMode !== "custom") {
        next.cross_groups = [];
        next.ruleScopes = [];
      }
    }
    if (action === "rule-scope" && ruleIndex >= 0) {
      const newScope = control.dataset.scopeValue || "count";
      next.ruleScopes[ruleIndex] = newScope;
      if (newScope === "count") next.cross_groups[ruleIndex].issue_ids = [];
      else next.cross_groups[ruleIndex].count = null;
    }
    if (action === "add-group") next.groups.push(newAllocationGroup(next.groups));
    if (action === "remove-group") {
      next.groups.splice(groupIndex, 1);
      if (next.groups.length === 1) {
        next.groups[0].coverage_percent = 100;
        next.pairing_mode = "orthogonal";
        next.cross_groups = [];
        next.ruleScopes = [];
      } else {
        next.cross_groups = next.cross_groups.filter((rule) => !rule.members.some((person) => person.group_id === group.group_id));
      }
    }
    if (action === "add-member") group.members.push({ name: "", review_percent: 0 });
    if (action === "remove-member") {
      const index = [...card.querySelectorAll("[data-setup-member]")].indexOf(control.closest("[data-setup-member]"));
      group.members.splice(index, 1);
      completeGroupShares(group.members);
    }
    if (action === "add-rule") {
      next.pairing_mode = "custom";
      next.cross_groups.push({ members: [], issue_ids: [], count: null });
      next.ruleScopes.push("count");
    }
    if (action === "remove-rule") {
      next.cross_groups.splice(ruleIndex, 1);
      next.ruleScopes.splice(ruleIndex, 1);
      if (!next.cross_groups.length) next.pairing_mode = "orthogonal";
    }
    renderAllocationGroupSetup(root, next, options);
    const newCards = root.querySelectorAll("[data-setup-group]");
    const newCard = newCards[action === "add-group" ? newCards.length - 1 : groupIndex];
    const newRules = root.querySelectorAll("[data-setup-rule]");
    const focus = action === "add-group" || action === "add-member"
      ? [...(newCard?.querySelectorAll("[data-setup-member] .ui-select-trigger") || [])].at(-1)
      : action === "group-strategy"
        ? newCard?.querySelector('[data-group-strategy="' + CSS.escape(group?.coverage_strategy || "overlap") + '"]')
        : action === "pairing-mode"
        ? root.querySelector('[data-pairing-mode="' + CSS.escape(next.pairing_mode) + '"]')
        : action === "rule-scope"
          ? newRules[ruleIndex]?.querySelector(next.ruleScopes[ruleIndex] === "cases" ? "[data-rule-cases]" : "[data-rule-count]")
          : action === "add-rule"
            ? newRules[newRules.length - 1]?.querySelector(".ui-select-trigger")
            : action === "remove-group" ? (root.closest(".task-allocation-settings")?.querySelector("[data-allocation-add-group]")
                || root.querySelector('[data-setup-action="add-group"]'))
              : action === "remove-member" ? newCard?.querySelector('[data-setup-action="add-member"]')
                : action === "remove-rule" ? (root.querySelector('[data-setup-action="add-rule"]') || root.querySelector('[data-pairing-mode="orthogonal"]'))
                  : newCard?.querySelector('[data-setup-action="add-member"]');
    focus?.focus({ preventScroll: action !== "add-group" && action !== "add-member" });
    change?.({ immediate: true });
  };
}

function updateGroupSetupIndicators(root) {
  const number = new Intl.NumberFormat(i18nLocale(), { maximumFractionDigits: 2 });
  const isCount = root.dataset?.inputUnit === "count";
  const caseCount = Math.max(0, Math.round(Number(root.dataset?.caseCount || 0)));
  const cards = [...root.querySelectorAll("[data-setup-group]")];
  let totalCoverage = 0;
  cards.forEach((card) => {
    const coverageInput = card.querySelector('[data-group-field="coverage"]');
    const coverage = coverageInput.valueAsNumber;
    if (Number.isFinite(coverage)) totalCoverage += coverage;
    const strategy = card.querySelector("[data-strategy-field]");
    if (strategy) strategy.hidden = Number.isNaN(coverage) || coverage >= (isCount ? caseCount : 100) || coverageInput.disabled;
    const memberDenom = isCount ? Math.max(0, Math.round(Number(card.dataset?.memberDenom || 0))) : 100;
    const rows = [...card.querySelectorAll("[data-setup-member]")];
    let shares = 0;
    let selected = 0;
    let allInt = true;
    const currentMembers = [];
    rows.forEach((row) => {
      const memberSelect = row.querySelector("[data-group-member]");
      const shareInput = row.querySelector('[data-group-field="share"]');
      const rawVal = shareInput?.value !== "" && Number.isFinite(shareInput?.valueAsNumber) ? shareInput.valueAsNumber : null;
      const val = rawVal || 0;
      const name = memberSelect?.value || "";
      if (name) {
        shares += val;
        selected += 1;
        if (isCount && (rawVal == null || !Number.isInteger(rawVal) || rawVal < 0)) allInt = false;
        currentMembers.push({ name, review_percent: rawVal });
      }
      row.dataset.empty = String(!name);
      const fillPct = isCount
        ? (memberDenom > 0 ? Math.max(0, Math.min(100, (100 * val) / memberDenom)) : 0)
        : Math.max(0, Math.min(100, val));
      shareInput?.closest(".assignment-ratio-input")?.style.setProperty("--share-fill", fillPct + "%");
    });
    const valid = isCount
      ? (allInt && memberDenom > 0 && shares === memberDenom)
      : (Math.round(shares * 100) === 10000);
    const shareNode = card.querySelector("[data-group-share]");
    shareNode.hidden = valid || selected === 0;
    shareNode.dataset.invalid = String(!valid && selected > 0);
    shareNode.textContent = valid || selected === 0
      ? ""
      : isCount
        ? uiText("合计 " + number.format(shares) + " / " + number.format(memberDenom) + " 条",
            number.format(shares) + " / " + number.format(memberDenom))
        : uiText("合计 " + number.format(shares) + "% / 100%", number.format(shares) + "% / 100%");

    const eqBtn = card.querySelector("[data-group-equalize]");
    if (eqBtn) {
      const suggestion = computeGroupEqualizeSuggestion(currentMembers, {
        unit: isCount ? "count" : "percent",
        denom: memberDenom,
      });
      const readOnlyCard = Boolean(card.querySelector('[data-setup-action="add-member"]')?.disabled);
      eqBtn.hidden = selected < 2;
      eqBtn.disabled = Boolean(readOnlyCard || !suggestion);
      if (suggestion && !readOnlyCard) {
        eqBtn.dataset.needsEqualize = "true";
        eqBtn.title = uiText(suggestion.textZh, suggestion.textEn);
      } else {
        delete eqBtn.dataset.needsEqualize;
        eqBtn.title = uiText("当前组已均分", "Already evenly split");
      }
    }
  });
  const pairedPreview = root.querySelector("[data-paired-preview]");
  if (pairedPreview) {
    const liveGroups = readAllocationGroupSetup(root)?.groups || [];
    const html = renderAllocationPairedChips(liveGroups);
    const temp = document.createElement("div");
    temp.innerHTML = html;
    pairedPreview.innerHTML = temp.firstElementChild?.innerHTML || "";
  }
  const ruleSlots = root.querySelectorAll(".allocation-rule-slot");
  if (ruleSlots.length) {
    const liveGroups = readAllocationGroupSetup(root)?.groups || [];
    ruleSlots.forEach((slotEl) => {
      const sel = slotEl.querySelector("[data-rule-group-member]");
      if (!sel) return;
      const gIdx = liveGroups.findIndex((g) => g.group_id === sel.dataset.ruleGroupMember);
      const val = sel.value || "";
      if (!val || gIdx < 0) {
        slotEl.style.setProperty("--member-swatch", "var(--faint)");
      } else {
        const mIdx = Math.max(0, liveGroups[gIdx].members.filter((p) => p.name).findIndex((p) => p.name === val));
        slotEl.style.setProperty("--member-swatch", "var(--allocation-swatch-" + allocationColorSlot(gIdx, mIdx) + ")");
      }
    });
  }
  const summary = root.querySelector("[data-setup-summary]");
  if (summary) {
    summary.textContent = isCount
      ? uiText(
          cards.length + " 组 · 共 " + number.format(totalCoverage) + " 份",
          cards.length + (cards.length === 1 ? " group · " : " groups · ") + number.format(totalCoverage) + " slots",
        )
      : uiText(
          cards.length + " 组 · 共 " + number.format(totalCoverage) + "%",
          cards.length + (cards.length === 1 ? " group · " : " groups · ") + number.format(totalCoverage) + "%",
        );
  }
}

function bindAllocationMemberDrag(root, options, change) {
  if (root._dragStatusTimer) {
    clearTimeout(root._dragStatusTimer);
    root._dragStatusTimer = null;
  }
  if (root._allocationDragKeyHandler) {
    root.removeEventListener("keydown", root._allocationDragKeyHandler);
    root._allocationDragKeyHandler = null;
  }
  root.onpointerdown = null;
  if (options?.editable === false) return;

  const showDragStatus = (message, tone = "warn") => {
    const banner = root.querySelector("[data-drag-status]");
    if (!banner) return;
    banner.textContent = message;
    banner.dataset.tone = tone;
    banner.hidden = !message;
    if (root._dragStatusTimer) clearTimeout(root._dragStatusTimer);
    if (message) {
      root._dragStatusTimer = setTimeout(() => {
        banner.hidden = true;
        banner.textContent = "";
      }, 3600);
    }
  };

  const commitMove = (fromGroupIndex, fromMemberIndex, toGroupIndex, toSlot) => {
    const next = readAllocationGroupSetup(root);
    if (!next) return false;
    const outcome = moveAllocationGroupMember(next, fromGroupIndex, fromMemberIndex, toGroupIndex, toSlot);
    if (!outcome.moved) {
      if (outcome.reason === "duplicate") {
        const gLabel = allocationGroupName(toGroupIndex);
        showDragStatus(
          uiText(
            "「" + outcome.memberName + "」已在" + gLabel + "中，未重复移入。",
            '"' + outcome.memberName + '" is already in ' + gLabel + ".",
          ),
          "warn",
        );
      }
      return false;
    }
    renderAllocationGroupSetup(root, next, options);
    const targetCard = root.querySelectorAll("[data-setup-group]")[outcome.targetGroupIndex];
    const targetRow = targetCard?.querySelectorAll("[data-setup-member]")[outcome.targetMemberIndex];
    (targetRow?.querySelector("[data-drag-handle]") || targetRow?.querySelector(".ui-select-trigger"))
      ?.focus({ preventScroll: true });
    change?.({ immediate: true });
    return true;
  };

  const keyHandler = (event) => {
    const handle = event.target?.closest?.("[data-drag-handle]");
    if (!handle) return;
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) return;
    const cards = [...root.querySelectorAll("[data-setup-group]")];
    const sourceCard = handle.closest("[data-setup-group]");
    const sourceRow = handle.closest("[data-setup-member]");
    const fromGroupIndex = cards.indexOf(sourceCard);
    if (fromGroupIndex < 0) return;
    const rows = [...sourceCard.querySelectorAll("[data-setup-member]")];
    const fromMemberIndex = rows.indexOf(sourceRow);
    if (fromMemberIndex < 0) return;

    if (event.key === "ArrowUp" && fromMemberIndex > 0) {
      event.preventDefault();
      commitMove(fromGroupIndex, fromMemberIndex, fromGroupIndex, fromMemberIndex - 1);
    } else if (event.key === "ArrowDown" && fromMemberIndex < rows.length - 1) {
      event.preventDefault();
      commitMove(fromGroupIndex, fromMemberIndex, fromGroupIndex, fromMemberIndex + 2);
    } else if (event.key === "ArrowLeft" && fromGroupIndex > 0) {
      event.preventDefault();
      commitMove(fromGroupIndex, fromMemberIndex, fromGroupIndex - 1, null);
    } else if (event.key === "ArrowRight" && fromGroupIndex < cards.length - 1) {
      event.preventDefault();
      commitMove(fromGroupIndex, fromMemberIndex, fromGroupIndex + 1, null);
    }
  };
  root._allocationDragKeyHandler = keyHandler;
  root.addEventListener("keydown", keyHandler);

  root.onpointerdown = (event) => {
    const handle = event.target?.closest?.("[data-drag-handle]");
    if (!handle) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const cards = [...root.querySelectorAll("[data-setup-group]")];
    const sourceCard = handle.closest("[data-setup-group]");
    const sourceRow = handle.closest("[data-setup-member]");
    const fromGroupIndex = cards.indexOf(sourceCard);
    if (fromGroupIndex < 0 || !sourceRow) return;
    const sourceRows = [...sourceCard.querySelectorAll("[data-setup-member]")];
    const fromMemberIndex = sourceRows.indexOf(sourceRow);
    const memberName = sourceRow.querySelector("[data-group-member]")?.value || "";
    if (fromMemberIndex < 0 || !memberName) return;

    const shareVal = sourceRow.querySelector('[data-group-field="share"]')?.value || "";
    const unitLabel = root.dataset?.inputUnit === "count" ? uiText("条", "cases") : "%";
    const swatchColor = getComputedStyle(sourceRow).getPropertyValue("--member-swatch").trim() || "var(--accent)";
    const pointerId = event.pointerId;
    const startX = event.clientX;
    const startY = event.clientY;
    let dragging = false;
    let ghost = null;
    let ghostNote = null;
    let dropState = null;

    const clearDropVisuals = () => {
      root.querySelectorAll(".is-drop-target, .is-drop-duplicate, .is-drop-before, .is-drop-after").forEach((el) => {
        el.classList.remove("is-drop-target", "is-drop-duplicate", "is-drop-before", "is-drop-after");
      });
    };

    const computeDropTarget = (clientX, clientY) => {
      const margin = 8;
      let targetCard = null;
      let toGroupIndex = -1;
      for (let i = 0; i < cards.length; i += 1) {
        const rect = cards[i].getBoundingClientRect();
        if (
          clientX >= rect.left - margin && clientX <= rect.right + margin &&
          clientY >= rect.top - margin && clientY <= rect.bottom + margin
        ) {
          targetCard = cards[i];
          toGroupIndex = i;
          break;
        }
      }
      if (!targetCard) return null;
      const rows = [...targetCard.querySelectorAll("[data-setup-member]")];
      const duplicate = toGroupIndex !== fromGroupIndex && rows.some(
        (row) => row.querySelector("[data-group-member]")?.value === memberName,
      );
      if (duplicate) {
        return { targetCard, toGroupIndex, duplicate: true, noop: false };
      }
      let toSlot = rows.length;
      let indicatorRow = rows[rows.length - 1] || null;
      let indicatorPos = "after";
      for (let i = 0; i < rows.length; i += 1) {
        const rect = rows[i].getBoundingClientRect();
        if (clientY < rect.top + rect.height / 2) {
          toSlot = i;
          indicatorRow = rows[i];
          indicatorPos = "before";
          break;
        }
      }
      const noop = toGroupIndex === fromGroupIndex && (toSlot === fromMemberIndex || toSlot === fromMemberIndex + 1);
      return { targetCard, toGroupIndex, toSlot, indicatorRow, indicatorPos, duplicate: false, noop };
    };

    const startGhost = (clientX, clientY) => {
      dragging = true;
      root.classList.add("is-dragging-member");
      sourceRow.classList.add("is-drag-source");
      document.querySelectorAll(".ui-select.is-open").forEach((sel) => {
        sel.classList.remove("is-open");
        const panel = sel.querySelector(".ui-select-panel");
        if (panel) panel.hidden = true;
        const trigger = sel.querySelector(".ui-select-trigger");
        if (trigger) trigger.setAttribute("aria-expanded", "false");
      });
      ghost = document.createElement("div");
      ghost.className = "allocation-drag-ghost";
      ghost.style.setProperty("--member-swatch", swatchColor);
      ghost.innerHTML =
        '<span class="allocation-drag-ghost-dot" aria-hidden="true"></span>' +
        '<strong class="allocation-drag-ghost-name">' + escapeHtml(memberName) + '</strong>' +
        (shareVal !== "" ? '<span class="allocation-drag-ghost-share">' + escapeHtml(shareVal + (unitLabel === "%" ? "%" : " " + unitLabel)) + '</span>' : '') +
        '<span class="allocation-drag-ghost-note" hidden></span>';
      ghostNote = ghost.querySelector(".allocation-drag-ghost-note");
      (root.closest("dialog") || document.body).appendChild(ghost);
      ghost.style.transform = "translate3d(" + Math.round(clientX + 12) + "px, " + Math.round(clientY - 18) + "px, 0)";
    };

    const onPointerMove = (moveEvent) => {
      if (moveEvent.pointerId !== pointerId) return;
      if (!dragging) {
        if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) < 4) return;
        startGhost(moveEvent.clientX, moveEvent.clientY);
      }
      moveEvent.preventDefault();
      if (ghost) {
        ghost.style.transform = "translate3d(" + Math.round(moveEvent.clientX + 12) + "px, " + Math.round(moveEvent.clientY - 18) + "px, 0)";
      }
      clearDropVisuals();
      dropState = computeDropTarget(moveEvent.clientX, moveEvent.clientY);
      if (ghost) ghost.classList.toggle("is-duplicate", Boolean(dropState?.duplicate));
      if (ghostNote) {
        if (dropState?.duplicate) {
          ghostNote.textContent = uiText("该组已有此成员", "Already in group");
          ghostNote.hidden = false;
        } else if (dropState && !dropState.noop && dropState.toGroupIndex !== fromGroupIndex) {
          const targetSelected = [...dropState.targetCard.querySelectorAll("[data-setup-member]")]
            .some((row) => Boolean(row.querySelector("[data-group-member]")?.value));
          const isCountMode = root.dataset?.inputUnit === "count";
          const gLabel = allocationGroupName(dropState.toGroupIndex);
          ghostNote.textContent = targetSelected
            ? uiText(
                "移入 " + gLabel + (isCountMode ? " · 0 条" : " · 0%"),
                "Move to " + gLabel + (isCountMode ? " · 0" : " · 0%"),
              )
            : uiText(
                "移入 " + gLabel + (isCountMode ? " · 全部" : " · 100%"),
                "Move to " + gLabel + (isCountMode ? " · All" : " · 100%"),
              );
          ghostNote.hidden = false;
        } else {
          ghostNote.hidden = true;
        }
      }
      if (!dropState) return;
      if (dropState.duplicate) {
        dropState.targetCard.classList.add("is-drop-duplicate");
      } else {
        dropState.targetCard.classList.add("is-drop-target");
        if (!dropState.noop && dropState.indicatorRow) {
          dropState.indicatorRow.classList.add(dropState.indicatorPos === "before" ? "is-drop-before" : "is-drop-after");
        }
      }
    };

    const finish = (commit) => {
      window.removeEventListener("pointermove", onPointerMove, { passive: false });
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerCancel);
      window.removeEventListener("keydown", onEscape, true);
      clearDropVisuals();
      root.classList.remove("is-dragging-member");
      sourceRow.classList.remove("is-drag-source");
      if (ghost) {
        ghost.remove();
        ghost = null;
      }
      if (commit && dragging && dropState) {
        if (dropState.duplicate) {
          commitMove(fromGroupIndex, fromMemberIndex, dropState.toGroupIndex, 0);
        } else if (!dropState.noop) {
          commitMove(fromGroupIndex, fromMemberIndex, dropState.toGroupIndex, dropState.toSlot);
        }
      }
    };

    const onPointerUp = (upEvent) => {
      if (upEvent.pointerId !== pointerId) return;
      finish(true);
    };
    const onPointerCancel = (cancelEvent) => {
      if (cancelEvent.pointerId !== pointerId) return;
      finish(false);
    };
    const onEscape = (keyEvent) => {
      if (keyEvent.key !== "Escape") return;
      if (dragging) {
        keyEvent.preventDefault();
        keyEvent.stopPropagation();
        finish(false);
      }
    };

    window.addEventListener("pointermove", onPointerMove, { passive: false });
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerCancel);
    window.addEventListener("keydown", onEscape, true);
  };
}
