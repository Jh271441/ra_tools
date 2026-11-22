/* The same after-state projection drives the creation and edit previews. */
function allocationPreviewView() {
  return { selected: new Map(), rosters: new Set(), unchanged: false };
}

function allocationMemberBadgeMap(plan, chartGroups, formal) {
  const map = new Map();
  const addFromGroups = (list) => {
    (list || []).forEach((group, index) => {
      const badge = allocationGroupShortBadge(group.group_id, index, formal);
      (group.members || []).forEach((person) => {
        if (person?.name && !map.has(person.name)) map.set(person.name, badge);
      });
    });
  };
  addFromGroups(chartGroups);
  addFromGroups(plan?.groups);
  if (typeof taskAllocationEditor === "object" && taskAllocationEditor?.config?.groups) {
    addFromGroups(taskAllocationEditor.config.groups);
  }
  return map;
}

function renderGroupedAllocationPreview(root, plan, view, { formal = false, editing = false } = {}) {
  const chart = plan?.group_coverage;
  if (!root || !chart?.case_count) return false;
  const number = new Intl.NumberFormat(i18nLocale(), { maximumFractionDigits: 2 });
  const fmt = (value) => number.format(value);
  const groups = chart.groups;
  const slots = plan.total_slots ?? groups.reduce((sum, group) => sum + group.members.reduce((total, p) => total + p.total, 0), 0);
  const activeMembers = new Set(groups.flatMap((group) => group.members.map((person) => person.name)));
  for (const [id, name] of view.selected) {
    if (!groups.some((group) => group.group_id === id && group.members.some((person) => person.name === name))) view.selected.delete(id);
  }
  const selected = [...view.selected];
  const intersections = groups.map(() => new Map());
  let sharedTotal = 0;
  if (selected.length) {
    const criteria = selected.map(([id, name]) => [groups.findIndex((g) => g.group_id === id), name]);
    for (const { owners, count } of chart.combinations) {
      if (criteria.every(([index, name]) => owners[index] === name)) {
        sharedTotal += count;
        owners.forEach((name, index) => intersections[index].set(name, (intersections[index].get(name) || 0) + count));
      }
    }
  }
  const workloadPct = fmt(100 * slots / chart.case_count) + "%";
  const summary = uiText(
    "<strong>" + escapeHtml(workloadPct) + "</strong> 总工作量 · " + escapeHtml(fmt(chart.case_count)) + " 个 Case · " + escapeHtml(fmt(slots)) + " 份",
    "<strong>" + escapeHtml(workloadPct) + "</strong> workload · " + escapeHtml(fmt(chart.case_count)) + " cases · " + escapeHtml(fmt(slots)) + " slots",
  );
  const groupsMarkup = groups.map((group, index) => {
    const name = allocationGroupName(group.group_id, index, formal);
    const total = group.members.reduce((sum, member) => sum + member.total, 0);
    const uncovered = chart.case_count - total;
    const parts = uncovered ? [...group.members, { name: null, total: uncovered, completed: 0 }] : group.members;
    const segments = parts.map((person, memberIndex) => {
      const isMember = person.name != null;
      const showShared = selected.length > 0 && !view.selected.has(group.group_id);
      const active = view.selected.get(group.group_id) === person.name;
      const shared = intersections[index].get(person.name) || 0;
      const label = person.name ?? uiText("未覆盖", "Uncovered");
      const textPlain = showShared ? fmt(shared) + "/" + fmt(person.total) : fmt(person.total);
      const countMarkup = showShared
        ? '<strong>' + escapeHtml(fmt(shared)) + '</strong><small>/' + escapeHtml(fmt(person.total)) + '</small>'
        : '<strong class="is-total">' + escapeHtml(fmt(person.total)) + '</strong>';
      const description = label + " · " + fmt(person.total) + (isMember ? " · " +
        uiText("已完成 ", "Completed ") + fmt(person.completed) : "") +
        (selected.length ? " · " + uiText("共同 Case ", "Shared cases ") + fmt(shared) : "");
      const controls = ' data-plot-group="' + escapeHtml(group.group_id) + '" data-plot-member="' + escapeHtml(person.name ?? "") + '"';
      const style = "--portion:" + (100 * person.total / chart.case_count) + "%;--member-color:var(--allocation-color-" +
        ((index * 2 + memberIndex) % 4) + ");--done:" + (100 * person.completed / person.total) +
        "%;--shared:" + (100 * shared / person.total) + "%";
      const hasSeam = isMember && person.completed > 0 && person.completed < person.total;
      const mark = '<span class="allocation-group-fill" aria-hidden="true"><i' + (hasSeam ? ' data-seam="true"' : '') + '></i></span>' +
        '<span class="allocation-group-segment-label" aria-hidden="true"><span>' + escapeHtml(label) +
        '</span><span class="allocation-segment-num">' + countMarkup + '</span></span>' +
        (shared ? '<i class="allocation-group-shared" aria-hidden="true"></i>' : '');
      const attributes = ' class="allocation-group-portion"' + (shared ? ' data-shared' : '') +
        ' aria-label="' + escapeHtml(description) + '" title="' + escapeHtml(description) + '" style="' + style + '"';
      return isMember
        ? '<button type="button"' + attributes + controls + ' aria-pressed="' + active + '">' + mark + '</button>'
        : '<span' + attributes + ' data-uncovered role="img">' + mark + '</span>';
    });
    return '<div class="allocation-group-row"><div class="allocation-group-header"><strong>' +
      escapeHtml(name) + '</strong><span>' +
      escapeHtml(uiText("覆盖 ", "Cover ") + fmt(100 * total / chart.case_count) + "%") + '</span></div>' +
      '<div class="allocation-group-bar" role="group" aria-label="' + escapeHtml(name) + '">' +
      segments.join("") + '</div></div>';
  }).join("");
  const focus = selected.length ? '<strong>' + escapeHtml(selected.map(([, name]) => name).join(" × ")) +
    '</strong><span>' + escapeHtml(selected.length > 1 ? uiText("共同 Case ", "Shared cases ") :
      uiText("负责 Case ", "Assigned cases ")) + '<strong class="allocation-focus-count">' + escapeHtml(fmt(sharedTotal)) + '</strong></span>' : '';
  root.innerHTML = '<div class="allocation-group-meta"><p class="allocation-group-summary">' + summary + '</p>' +
    '<div class="allocation-group-legend"><span><i class="allocation-legend-done"></i>' + escapeHtml(uiText("已完成", "Completed")) +
    '</span><span><i class="allocation-legend-pending"></i>' + escapeHtml(uiText("待完成", "Pending")) +
    '</span><span><i class="allocation-legend-shared"></i>' + escapeHtml(uiText("共同 Case", "Shared")) + '</span></div></div>' +
    '<section class="allocation-group-plot">' +
    '<div class="allocation-group-axis" aria-hidden="true"><span>0%</span><span>50%</span><span>100%</span></div>' +
    '<div class="allocation-group-rows"' + (selected.length ? ' data-plot-focused' : '') + '>' + groupsMarkup + '</div>' +
    '<div class="allocation-plot-focus"><span class="allocation-plot-focus-text" aria-live="polite">' +
    (selected.length ? focus : escapeHtml(uiText("点击成员色块查看跨组共同 Case", "Click a member segment to inspect shared cases"))) + '</span>' +
    (selected.length ? '<button type="button" class="text-button allocation-clear-btn" data-plot-clear>' +
      escapeHtml(uiText("清除选择", "Clear")) + '</button>' : '') +
    '</div></section>' + (editing ? renderAllocationDiff(plan, view, activeMembers, fmt, { formal, groups }) : '');
  const options = { formal, editing };
  root.onclick = (event) => {
    const control = event.target.closest("button");
    if (!control) return;
    const { plotGroup, plotMember, diffMember } = control.dataset;
    let focusSelector;
    if (control.hasAttribute("data-plot-clear")) {
      view.selected.clear();
      focusSelector = ".allocation-group-portion[aria-pressed]";
    } else if (control.hasAttribute("data-diff-toggle")) {
      view.unchanged = !view.unchanged;
      focusSelector = "[data-diff-toggle]";
    } else if (plotMember != null || diffMember != null) {
      const name = plotMember ?? diffMember;
      const gid = plotGroup ?? selected.find(([, person]) => person === name)?.[0] ??
        groups.find((g) => g.members.some((person) => person.name === name))?.group_id;
      if (!gid) return;
      if (view.selected.get(gid) === name) view.selected.delete(gid);
      else view.selected.set(gid, name);
      focusSelector = diffMember != null ? '[data-diff-member="' + CSS.escape(name) + '"]' :
        '.allocation-group-portion[data-plot-group="' + CSS.escape(gid) + '"][data-plot-member="' + CSS.escape(name) + '"]';
    } else return;
    renderGroupedAllocationPreview(root, plan, view, options);
    root.querySelector(focusSelector)?.focus({ preventScroll: true });
  };
  return true;
}

function renderAllocationDiff(plan, view, activeMembers, fmt, { formal = false, groups = [] } = {}) {
  const members = plan.members || [];
  const changed = members.filter((p) => p.incoming || p.outgoing);
  const stable = members.filter((p) => !p.incoming && !p.outgoing);
  const visible = view.unchanged ? [...changed, ...stable] : changed;
  const movedSlots = changed.reduce((sum, p) => sum + (p.incoming || 0), 0);
  const scale = Math.max(1, ...members.map((p) => p.total_after + p.outgoing));
  const selected = new Set(view.selected.values());
  const badgeMap = allocationMemberBadgeMap(plan, groups, formal);
  const row = (person) => {
    const style = (name, value) => value ? '<i class="allocation-diff-' + name + '" style="--part:' +
      (100 * value / scale) + '%"></i>' : "";
    const retainedPending = Math.max(0, person.retained_pending ?? person.total_after - person.incoming - person.completed);
    const net = (person.incoming || 0) - (person.outgoing || 0);
    const delta = net > 0 ? "+" + fmt(net) : net < 0 ? "−" + fmt(Math.abs(net))
      : [person.incoming ? "+" + fmt(person.incoming) : "", person.outgoing ? "−" + fmt(person.outgoing) : ""].filter(Boolean).join("/");
    const sign = net > 0 || (net === 0 && person.incoming) ? "in" : net < 0 || person.outgoing ? "out" : "none";
    const badge = badgeMap.get(person.name) || (person.pool_role ? person.pool_role.toUpperCase() : "");
    const comparisonHtml = '<span>' + escapeHtml(fmt(person.before)) + ' → <strong>' + escapeHtml(fmt(person.total_after)) + '</strong></span>';
    const title = '<span class="allocation-diff-person">' +
      (badge ? '<span class="allocation-diff-badge">' + escapeHtml(badge) + '</span>' : '') +
      '<span class="allocation-diff-name" title="' + escapeHtml(person.name) + '">' + escapeHtml(person.name) + '</span></span>';
    const segments = '<span class="allocation-diff-track" aria-hidden="true">' +
      style("done", person.completed) + style("pending", retainedPending) +
      style("incoming", person.incoming) + style("outgoing", person.outgoing) + '</span>';
    const comparisonPlain = fmt(person.before) + " → " + fmt(person.total_after);
    const description = person.name + " · " + comparisonPlain + (delta ? " · " + delta : "");
    const content = title + segments + '<span class="allocation-diff-values">' + comparisonHtml +
      '<strong data-diff-sign="' + sign + '">' + escapeHtml(delta || "—") + '</strong></span>';
    return activeMembers.has(person.name) ? '<button type="button" class="allocation-diff-row" data-diff-member="' +
      escapeHtml(person.name) + '" aria-pressed="' + selected.has(person.name) + '" aria-label="' +
      escapeHtml(description) + '">' + content + '</button>' : '<div class="allocation-diff-row">' + content + '</div>';
  };
  const summaryText = changed.length
    ? uiText("涉及 " + fmt(changed.length) + " 人 · 调拨 " + fmt(movedSlots) + " 份待办",
      fmt(changed.length) + " changed · " + fmt(movedSlots) + " pending moved")
    : uiText("0 人变动", "No changes");
  const headerRight = '<div class="allocation-diff-controls">' +
    (changed.length ? '<span class="allocation-group-legend allocation-diff-legend"><span><i class="allocation-diff-incoming"></i>' +
      escapeHtml(uiText("新转入", "Added")) + '</span><span><i class="allocation-diff-outgoing"></i>' +
      escapeHtml(uiText("已转出", "Moved out")) + '</span></span>' : '') +
    (stable.length ? '<button type="button" class="button button-secondary allocation-compact-btn" data-diff-toggle aria-expanded="' + view.unchanged + '">' +
      escapeHtml((view.unchanged ? uiText("收起未变动", "Hide unchanged") : uiText("展开未变动", "Show unchanged")) +
        " (" + fmt(stable.length) + ")") + '</button>' : '') + '</div>';
  const bodyMarkup = !visible.length
    ? '<p class="allocation-diff-empty">' + escapeHtml(uiText("当前配置未产生人员待办调拨。", "No pending assignments move under the current settings.")) + '</p>'
    : '<div class="allocation-diff-list">' + visible.map(row).join("") + '</div>';
  return '<section class="allocation-diff"><header class="allocation-diff-header"><div class="allocation-diff-title"><h3>' +
    escapeHtml(uiText("本次变动", "Changes")) + '</h3><span>' + escapeHtml(summaryText) + '</span></div>' +
    headerRight + '</header>' + bodyMarkup + '</section>';
}
