/* Shared group controls for task creation and protected redistribution. */
function newAllocationGroup(groups = []) {
  const ids = new Set(groups.map((group) => group.group_id));
  let index = 1;
  while (ids.has("group-" + index)) index += 1;
  return { group_id: "group-" + index, coverage_percent: groups.length ? 50 : 100,
    coverage_strategy: "overlap", members: [{ name: "", review_percent: 100 }] };
}

function allocationGroupRole(id) {
  return /^(rd|te)(?:-[0-9]+)?$/.exec(id)?.[1];
}

function allocationGroupName(id, index, formal = false) {
  if (formal && allocationGroupRole(id)) {
    const label = id.toUpperCase().replace("-", " ");
    return uiText(label + " 组", label);
  }
  return uiText("第 " + (index + 1) + " 组", "Group " + (index + 1));
}

function allocationGroupShortBadge(id, index, formal = false) {
  if (formal && allocationGroupRole(id)) return id.toUpperCase().replace("-", "");
  return uiText((index + 1) + "组", "G" + (index + 1));
}

function allocationGroupOptions(options, selected) {
  return options.map(({ value, label }) => '<option value="' + escapeHtml(value) + '"' +
    (value === selected ? " selected" : "") + ">" + escapeHtml(label) + "</option>").join("");
}

function allocationColorSlot(groupIndex, memberIndex) {
  return (groupIndex * 2 + memberIndex) % 4;
}

function groupAllocationInput(value, label, field, disabled = false, extraStyle = "") {
  return '<span class="assignment-ratio-input"' + (extraStyle ? ' style="' + escapeHtml(extraStyle) + '"' : '') +
    '><input data-group-field="' + field +
    '" aria-label="' + escapeHtml(label) + '" type="number" min="0" max="100" step="0.01" inputmode="decimal" required value="' +
    escapeHtml(value ?? "") + '"' + (disabled ? " disabled" : "") + '><span aria-hidden="true">%</span></span>';
}

function readAllocationGroupSetup(root) {
  if (!root?.querySelectorAll) return null;
  const number = (input) => input?.value !== "" && Number.isFinite(input?.valueAsNumber) ? input.valueAsNumber : null;
  const groups = [...root.querySelectorAll("[data-setup-group]")].map((card) => ({
    group_id: card.dataset.setupGroup,
    coverage_percent: number(card.querySelector('[data-group-field="coverage"]')),
    coverage_strategy: card.querySelector("[data-group-strategy]").value,
    members: [...card.querySelectorAll("[data-setup-member]")].map((row) => ({
      name: row.querySelector("[data-group-member]").value,
      review_percent: number(row.querySelector('[data-group-field="share"]')),
    })),
  }));
  const cross_groups = [...root.querySelectorAll("[data-setup-rule]")].map((row) => ({
    members: [...row.querySelectorAll("[data-rule-member]")].map((control) =>
      control.value ? JSON.parse(control.value) : null).filter(Boolean),
    issue_ids: row.querySelector("textarea").value.trim().split(/[\s,，]+/u).filter(Boolean),
    count: number(row.querySelector("[data-rule-count]")),
  }));
  return { groups, cross_groups, rulesOpen: root.querySelector("[data-setup-rules]")?.open || false,
    ruleLengths: [...root.querySelectorAll("[data-setup-rule]")].map((row) => row.querySelectorAll("select").length) };
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

function rebalanceGroupShare(input, edit) {
  if (edit?.input !== input) {
    const card = input.closest("[data-setup-group]");
    const shares = [...card.querySelectorAll("[data-setup-member]")]
      .filter((row) => row.querySelector("[data-group-member]").value)
      .map((row) => row.querySelector('[data-group-field="share"]'));
    if (!shares.includes(input) || shares.length < 2) return null;
    const peers = shares.filter((share) => share !== input);
    // Use the proportions from the start of this edit, including while typing 100.
    edit = { input, peers, weights: peers.map((peer) => allocationPercentUnits(peer.valueAsNumber) ?? 0) };
  }
  const units = allocationPercentUnits(input.valueAsNumber);
  if (units != null) {
    const shares = splitGroupShares(10000 - units, edit.weights);
    edit.peers.forEach((peer, index) => { peer.value = String(shares[index]); });
  }
  return edit;
}

function groupAllocationSetupError(draft) {
  const invalid = (value) => allocationPercentUnits(value) == null;
  if (!draft?.groups?.length || draft.groups.some((group) => !group.members.length ||
      group.members.some((person) => !person.name))) {
    return apiResponseError("请为每组选择成员。", "Select members for each group.");
  }
  if (draft.groups.some((group) => invalid(group.coverage_percent) ||
      group.members.some((member) => invalid(member.review_percent)) ||
      group.members.reduce((sum, person) => sum + Math.round(person.review_percent * 100), 0) !== 10000)) {
    return apiResponseError("请检查覆盖率，各组的成员比例须分别合计 100%。",
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

function groupAllocationRulePicker(groups, current, formal) {
  const prompt = uiText("选择组和成员", "Select a group member");
  const options = [{ value: "", label: prompt }, ...groups.flatMap((group, index) =>
    group.members.filter((person) => person.name).map((person) => ({
      value: JSON.stringify({ group_id: group.group_id, name: person.name }),
      label: allocationGroupName(group.group_id, index, formal) + " · " + person.name,
    })))];
  const value = current ? JSON.stringify({ group_id: current.group_id, name: current.name }) : "";
  if (value && !options.some((option) => option.value === value)) {
    options.push({ value, label: current.name + " · " + uiText("已移除", "Removed") });
  }
  return '<select data-rule-member aria-label="' + escapeHtml(prompt) + '">' +
    allocationGroupOptions(options, value) + "</select>";
}

function renderAllocationGroupSetup(root, draft, options) {
  const { users, formal = false, editable = true, change } = options;
  const groups = draft.groups?.length ? draft.groups : [newAllocationGroup()];
  const rules = draft.cross_groups || [];
  const empty = uiText("选择成员", "Select a member");
  const coverageLabel = uiText("覆盖率", "Coverage");
  const shareLabel = uiText("组内比例", "Group share");
  const removeMember = uiText("移除成员", "Remove member");
  const cards = groups.map((group, index) => {
    const role = formal ? allocationGroupRole(group.group_id) : null;
    const required = formal && (group.group_id === "rd" || group.group_id === "te");
    const candidates = users.filter((user) => ["writer", "admin"].includes(user.role) &&
      (!role || user.human_role === role));
    const members = group.members.length ? group.members : [{ name: "", review_percent: 100 }];
    const card = members.map((person, memberIndex) => {
      const slot = allocationColorSlot(index, memberIndex);
      const pct = Math.max(0, Math.min(100, Number(person.review_percent) || 0));
      const names = [{ value: "", label: empty }, ...candidates.map((user) => ({
        value: user.username, label: user.username,
      }))];
      if (person.name && !names.some((item) => item.value === person.name)) {
        names.push({ value: person.name, label: person.name + " · " + uiText("不可用", "Unavailable") });
      }
      const rowStyle = "--member-swatch:var(--allocation-swatch-" + slot + ");--share-color:var(--allocation-swatch-" + slot + ")";
      return '<div class="allocation-setup-member" data-setup-member data-empty="' + String(!person.name) + '" style="' + rowStyle + '">' +
        '<span class="allocation-member-swatch" aria-hidden="true"></span>' +
        '<select data-group-member aria-label="' +
        escapeHtml(empty) + '">' + allocationGroupOptions(names, person.name) + '</select>' +
        groupAllocationInput(person.review_percent, shareLabel, "share", false, "--share-fill:" + pct + "%") +
        '<button class="allocation-remove-control" type="button" data-setup-action="remove-member" aria-label="' +
        escapeHtml(removeMember) + '" title="' + escapeHtml(removeMember) + '">×</button></div>';
    }).join("");
    const coverageControl = required
      ? '<span class="allocation-coverage-pill">' + escapeHtml(uiText("覆盖 100%", "100% cover")) +
        '<input data-group-field="coverage" aria-label="' + escapeHtml(coverageLabel) +
        '" type="number" min="0" max="100" step="0.01" value="' + escapeHtml(group.coverage_percent ?? 100) + '" disabled hidden></span>'
      : '<label class="allocation-coverage-inline"><span>' + escapeHtml(uiText("覆盖", "Cover")) + '</span>' +
        groupAllocationInput(group.coverage_percent, coverageLabel, "coverage", false) + '</label>';
    return '<section class="allocation-setup-card" data-setup-group="' + escapeHtml(group.group_id) + '">' +
      '<header class="allocation-setup-header"><div class="allocation-setup-title"><strong>' +
      escapeHtml(allocationGroupName(group.group_id, index, formal)) + '</strong>' + coverageControl +
      '<span data-group-share hidden></span></div>' +
      '<div class="allocation-setup-tools">' +
      '<button class="text-button allocation-tool-link" type="button" data-setup-action="equalize">' +
      escapeHtml(uiText("均分", "Even")) + '</button>' +
      (!required && groups.length > 1 ? '<button class="text-button allocation-tool-link" type="button" data-setup-action="remove-group">' +
        escapeHtml(uiText("移除", "Remove")) + '</button>' : '') + '</div></header>' +
      '<label class="allocation-setup-strategy" data-strategy-field' + (group.coverage_percent < 100 && !required ? '' : ' hidden') + '><span>' +
      escapeHtml(uiText("覆盖策略", "Strategy")) + '</span><select data-group-strategy>' +
      allocationGroupOptions([
        { value: "overlap", label: uiText("优先与前组重叠", "Prefer overlap with earlier groups") },
        { value: "fill", label: uiText("优先补未交叉 Case", "Prefer cases without cross-review") },
      ], group.coverage_strategy || "overlap") + '</select></label>' +
      '<div class="allocation-setup-members">' + card + '</div>' +
      '<div class="allocation-setup-actions"><button class="text-button allocation-add-member" type="button" data-setup-action="add-member">+ ' +
      escapeHtml(uiText("添加成员", "Add member")) + '</button></div></section>';
  }).join("");
  const rulesMarkup = rules.map((rule, index) => {
    const count = draft.ruleLengths?.[index] || Math.max(2, rule.members.length);
    return '<div class="allocation-setup-rule" data-setup-rule>' +
      '<div class="allocation-rule-partners"><div class="allocation-rule-pickers">' +
      Array.from({ length: count }, (_, idx) => groupAllocationRulePicker(groups, rule.members[idx], formal)).join("") +
      '</div><div class="allocation-rule-tools">' +
      '<button class="text-button allocation-tool-link" type="button" data-setup-action="add-partner">+ ' +
      escapeHtml(uiText("搭档", "Partner")) + '</button>' +
      '<button class="text-button allocation-tool-link" type="button" data-setup-action="remove-rule">' +
      escapeHtml(uiText("移除", "Remove")) + '</button></div></div>' +
      '<div class="allocation-rule-scope"><label><span>' + escapeHtml(uiText("指定 Case ID", "Case IDs")) +
      '</span><textarea rows="1" placeholder="' +
      escapeHtml(uiText("用空格或换行分隔", "Separate with spaces or newlines")) + '">' +
      escapeHtml(rule.issue_ids.join("\n")) + '</textarea></label><label><span>' +
      escapeHtml(uiText("或指定数量", "Or count")) +
      '</span><input type="number" min="1" step="1" inputmode="numeric" data-rule-count placeholder="' +
      escapeHtml(uiText("例如 10", "e.g. 10")) + '" value="' +
      escapeHtml(rule.count ?? "") + '"></label></div></div>';
  }).join("");
  root.innerHTML = '<div class="allocation-setup-bar"><span class="allocation-setup-bar-title"><span>' +
    escapeHtml(uiText("分配组", "Allocation groups")) + '</span><small data-setup-summary></small></span>' +
    '<button class="button button-secondary allocation-compact-btn allocation-add-group" type="button" data-setup-action="add-group">+ ' +
    escapeHtml(uiText("添加分配组", "Add group")) + '</button></div>' +
    '<div class="allocation-setup-cards" data-group-count="' + groups.length + '">' + cards + '</div>' +
    (groups.length > 1 ?
    '<details class="assignment-groups allocation-partner-rules" data-setup-rules' + (draft.rulesOpen ? ' open' : '') + '><summary>' +
    '<span>' + escapeHtml(uiText("指定交叉搭档", "Cross-review partners")) + '</span>' +
    '<span class="allocation-disclosure-meta">' + escapeHtml(rules.length
      ? uiText(rules.length + " 条规则", rules.length + (rules.length === 1 ? " rule" : " rules"))
      : uiText("按组自动安排", "Automatic by group")) + '</span></summary>' +
    '<p class="allocation-rules-hint">' + escapeHtml(uiText(
      "选择不同组中比例大于 0% 的成员，再填共同复核的 Case ID 或数量。",
      "Select members with a positive share from different groups, then enter the shared Case IDs or a count.",
    )) + '</p>' + rulesMarkup +
    '<div class="allocation-rules-footer"><button class="button button-secondary allocation-compact-btn" type="button" data-setup-action="add-rule">+ ' +
    escapeHtml(uiText("添加搭档规则", "Add partner rule")) + '</button></div></details>' : '');
  if (!editable) root.querySelectorAll("input, button, select, textarea").forEach((control) => { control.disabled = true; });
  root.querySelectorAll("select").forEach((select) => enhanceNativeUiSelect(select));
  updateGroupSetupIndicators(root);
  let shareEdit = null;
  const refresh = (input) => {
    if (input.matches('[data-group-field="share"]')) shareEdit = rebalanceGroupShare(input, shareEdit);
    updateGroupSetupIndicators(root);
    change?.();
  };
  root.onfocusout = (event) => {
    if (event.target === shareEdit?.input) shareEdit = null;
  };
  root.oninput = (event) => {
    if (!event.isComposing && !event.target.matches("select")) refresh(event.target);
  };
  root.onchange = (event) => {
    if (event.target.matches("[data-group-member]") && root.querySelector("[data-setup-rule]")) {
      const next = readAllocationGroupSetup(root);
      const cards = [...root.querySelectorAll("[data-setup-group]")];
      const group = cards.indexOf(event.target.closest("[data-setup-group]"));
      const member = [...cards[group].querySelectorAll("[data-group-member]")].indexOf(event.target);
      renderAllocationGroupSetup(root, next, options);
      root.querySelectorAll("[data-setup-group]")[group]?.querySelectorAll("[data-setup-member]")[member]
        ?.querySelector(".ui-select-trigger")?.focus({ preventScroll: true });
    }
    refresh(event.target);
  };
  root.onclick = (event) => {
    const control = event.target.closest("[data-setup-action]");
    if (!control || !editable) return;
    const next = readAllocationGroupSetup(root);
    const card = control.closest("[data-setup-group]");
    const groupIndex = [...root.querySelectorAll("[data-setup-group]")].indexOf(card);
    const group = next.groups[groupIndex];
    const ruleIndex = [...root.querySelectorAll("[data-setup-rule]")].indexOf(control.closest("[data-setup-rule]"));
    const action = control.dataset.setupAction;
    if (action === "add-group") next.groups.push(newAllocationGroup(next.groups));
    if (action === "remove-group") {
      next.groups.splice(groupIndex, 1);
      next.cross_groups = next.cross_groups.filter((rule) => !rule.members.some((person) => person.group_id === group.group_id));
      next.ruleLengths = [];
    }
    if (action === "add-member") group.members.push({ name: "", review_percent: 0 });
    if (action === "remove-member") {
      const index = [...card.querySelectorAll("[data-setup-member]")].indexOf(control.closest("[data-setup-member]"));
      group.members.splice(index, 1);
    }
    if (action === "equalize") {
      const shares = splitGroupShares(10000, group.members.map(() => 1));
      group.members.forEach((person, index) => { person.review_percent = shares[index]; });
    }
    if (action === "add-rule") next.cross_groups.push({ members: [], issue_ids: [], count: null });
    if (action === "remove-rule") {
      next.cross_groups.splice(ruleIndex, 1);
      next.ruleLengths.splice(ruleIndex, 1);
    }
    if (action === "add-partner") next.ruleLengths[ruleIndex] += 1;
    renderAllocationGroupSetup(root, next, options);
    const newCards = root.querySelectorAll("[data-setup-group]");
    const newCard = newCards[action === "add-group" ? newCards.length - 1 : groupIndex];
    const newRules = root.querySelectorAll("[data-setup-rule]");
    const focus = action === "add-group" || action === "add-member"
      ? [...(newCard?.querySelectorAll("[data-setup-member] .ui-select-trigger") || [])].at(-1)
      : action === "add-rule" || action === "add-partner"
        ? [...(newRules[action === "add-rule" ? newRules.length - 1 : ruleIndex]?.querySelectorAll(".ui-select-trigger") || [])].at(-1)
        : action === "remove-group" ? (root.closest(".task-allocation-settings")?.querySelector("[data-allocation-add-group]")
            || root.querySelector('[data-setup-action="add-group"]'))
          : action === "remove-member" ? newCard?.querySelector('[data-setup-action="add-member"]')
            : action === "remove-rule" ? root.querySelector('[data-setup-action="add-rule"]')
              : newCard?.querySelector('[data-setup-action="equalize"]');
    focus?.focus({ preventScroll: action !== "add-group" && action !== "add-member" });
    change?.();
  };
}

function updateGroupSetupIndicators(root) {
  const number = new Intl.NumberFormat(i18nLocale(), { maximumFractionDigits: 2 });
  const cards = [...root.querySelectorAll("[data-setup-group]")];
  let totalCoverage = 0;
  cards.forEach((card) => {
    const coverageInput = card.querySelector('[data-group-field="coverage"]');
    const coverage = coverageInput.valueAsNumber;
    if (Number.isFinite(coverage)) totalCoverage += coverage;
    const strategy = card.querySelector("[data-strategy-field]");
    strategy.hidden = Number.isNaN(coverage) || coverage >= 100 || coverageInput.disabled;
    const rows = [...card.querySelectorAll("[data-setup-member]")];
    let shares = 0;
    rows.forEach((row) => {
      const memberSelect = row.querySelector("[data-group-member]");
      const shareInput = row.querySelector('[data-group-field="share"]');
      const val = shareInput?.valueAsNumber || 0;
      shares += val;
      row.dataset.empty = String(!memberSelect?.value);
      shareInput?.closest(".assignment-ratio-input")?.style.setProperty("--share-fill", Math.max(0, Math.min(100, val)) + "%");
    });
    const valid = Math.round(shares * 100) === 10000;
    const shareNode = card.querySelector("[data-group-share]");
    shareNode.hidden = valid;
    shareNode.dataset.invalid = String(!valid);
    shareNode.textContent = valid ? "" : uiText("合计 " + number.format(shares) + "% / 100%", number.format(shares) + "% / 100%");
  });
  const summary = root.querySelector("[data-setup-summary]");
  if (summary) {
    summary.textContent = uiText(
      cards.length + " 组 · 共 " + number.format(totalCoverage) + "%",
      cards.length + (cards.length === 1 ? " group · " : " groups · ") + number.format(totalCoverage) + "%",
    );
  }
}
