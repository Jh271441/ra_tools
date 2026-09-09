/* ra_triage_dashboard/static/js/work-split.js
 * Admin Review work-split: persist assignee ownership and gallery filters.
 * Loaded as a classic script (shared global scope).
 */
function workAssigneeRouteSelection() {
  const params = new URLSearchParams(window.location.search);
  return parseFilterList(params.get("work_assignee") || params.get("assignee") || "");
}

function workAssigneeFilterSelection() {
  const values = parseFilterList(getMultiFilterValues($("#workAssigneeFilter")));
  // The custom facet is rebuilt after an asynchronous request.  During that
  // short window it has no checked inputs, but the active Review URL still
  // carries the operator's intended task-assignee filter.
  if (values.length || state.activePage !== "review") return values;
  return workAssigneeRouteSelection();
}

function persistWorkAssigneeFilterRoute(values) {
  if (state.activePage !== "review") return;
  const selection = parseFilterList(
    values === undefined ? workAssigneeFilterSelection() : values
  );
  const nextUrl = pageUrl(
    "review",
    currentReviewRouteOptions({ workAssignee: selection })
  );
  const currentUrl = `${window.location.pathname}${window.location.search}`;
  if (nextUrl === currentUrl) return;
  window.history.replaceState(
    { ...(window.history.state || {}), page: "review" },
    "",
    nextUrl
  );
}

function currentReviewFilterPayload() {
  return {
    search: $("#searchInput")?.value.trim() || "",
    gt_label: joinFilterList(getMultiFilterValues($("#gtFilter"))),
    model_label: joinFilterList(getMultiFilterValues($("#annotationFilter"))),
    annotation_author: joinFilterList(getMultiFilterValues($("#reviewerFilter"))),
    review_status: joinFilterList(getMultiFilterValues($("#reviewStatusFilter"))),
    exclusion:
      typeof selectedReviewExclusionFilter === "function"
        ? selectedReviewExclusionFilter()
        : "all",
    model_run_id: state.selectedRunId || $("#modelRunFilter")?.value || "",
    comparison:
      state.selectedRunId || $("#modelRunFilter")?.value
        ? selectedReviewComparisonStatus()
        : "all",
    failure_only: false,
    missing_evidence: state.clusterKey || "",
    issue_ids: (state.reviewIssueIds || []).join(","),
    baselines: selectedBaselineQueryValue(),
    // When creating a new split, ignore current assignee filter so the pool
    // is the full filtered set unless the admin intentionally kept it.
    work_assignee: "",
  };
}

function workSplitPersonRow(name = "", count = "") {
  const users = Array.isArray(state.accessUsers) ? state.accessUsers : [];
  const selectedUser = users.find((item) => item.username === name);
  const selectedLabel = selectedUser
    ? `${selectedUser.username}${selectedUser.role === "admin" ? t("work.admin_suffix") : ""}`
    : t("work.pick_person");
  return `<div class="work-split-person-row">
    <div class="ui-select work-split-person-picker" data-work-split-selected="${escapeHtml(name)}">
      <button class="ui-select-trigger" type="button" aria-haspopup="listbox" aria-expanded="false" aria-label="复核人">
        <span class="ui-select-summary">${escapeHtml(selectedLabel)}</span>
        <span class="ui-select-caret" aria-hidden="true"></span>
      </button>
      <div class="ui-select-panel" role="listbox" hidden></div>
      <select class="ui-select-native work-split-person-name" aria-hidden="true" tabindex="-1"></select>
    </div>
    <input class="work-split-person-count" type="number" min="0" step="1" placeholder="${escapeHtml(t("work.even_split"))}" value="${escapeHtml(
      count
    )}" title="留空=参与剩余均分；填数字=固定领取数量" />
    <button class="button button-quiet work-split-remove-person" type="button" aria-label="移除">×</button>
  </div>`;
}

function renderWorkSplitPersonPickers() {
  const pickers = [...document.querySelectorAll("#workSplitPeople .work-split-person-picker")];
  const selectedByPicker = new Map(
    pickers.map((picker) => {
      const select = picker.querySelector(".work-split-person-name");
      return [picker, select?.value || picker.dataset.workSplitSelected || ""];
    })
  );
  pickers.forEach((picker) => {
    const selected = selectedByPicker.get(picker) || "";
    const selectedElsewhere = new Set(
      [...selectedByPicker.entries()]
        .filter(([other]) => other !== picker)
        .map(([, value]) => value)
        .filter(Boolean)
    );
    const options = [
      { value: "", label: t("work.pick_person") },
      ...(state.accessUsers || []).map((item) => ({
        value: item.username,
        label: `${item.username}${item.role === "admin" ? t("work.admin_suffix") : ""}`,
        disabled: selectedElsewhere.has(item.username),
      })),
    ];
    populateUiSelect(picker, options, selected);
    bindUiSelect(picker, { maxHeight: 320, maxWidth: 520 });
    picker.dataset.workSplitSelected =
      picker.querySelector(".work-split-person-name")?.value || "";
  });
}

function ensureWorkSplitPeople(minRows = 2) {
  const root = $("#workSplitPeople");
  if (!root) return;
  while (root.querySelectorAll(".work-split-person-row").length < minRows) {
    root.insertAdjacentHTML("beforeend", workSplitPersonRow());
  }
}

function readWorkSplitAssignees() {
  const rows = [...document.querySelectorAll("#workSplitPeople .work-split-person-row")];
  return rows
    .map((row) => {
      const name = row.querySelector(".work-split-person-name")?.value.trim() || "";
      const countRaw = row.querySelector(".work-split-person-count")?.value.trim() || "";
      return {
        name,
        count: countRaw === "" ? null : Number(countRaw),
      };
    })
    .filter((item) => item.name);
}

function workSplitReviewersPerIssue() {
  const value = Number.parseInt($("#workSplitReviewersPerIssue")?.value || "1", 10);
  return Number.isFinite(value) ? Math.max(1, value) : 1;
}

function renderWorkSplitReviewersPerIssuePicker(selected = null) {
  const picker = $("#workSplitReviewersPerIssuePicker");
  const memberCount = readWorkSplitAssignees().length;
  const maximum = Math.max(1, memberCount);
  const requested = selected === null
    ? workSplitReviewersPerIssue()
    : Number.parseInt(String(selected), 10);
  const value = Math.min(Math.max(1, Number.isFinite(requested) ? requested : 1), maximum);
  populateUiSelect(
    picker,
    Array.from({ length: maximum }, (_, index) => ({
      value: String(index + 1),
      label: `${index + 1} 人`,
    })),
    String(value),
  );
  bindUiSelect(picker, { maxHeight: 260, maxWidth: 180 });
  return value;
}

function updateWorkSplitEstimate() {
  const reviewers = workSplitReviewersPerIssue();
  const people = readWorkSplitAssignees();
  const total = Number(state.caseTotal || 0);
  const target = $("#workSplitEstimate");
  document.querySelectorAll(".work-split-person-count").forEach((input) => {
    input.placeholder = reviewers > 1 ? "自动均衡" : t("work.even_split");
  });
  if (!target) return;
  if (reviewers > people.length && people.length) {
    target.textContent = `每个 Issue 的人数不能超过已选 ${people.length} 人`;
    return;
  }
  const assignmentCount = total * reviewers;
  const fixedTotal = people.reduce(
    (sum, person) => sum + (person.count === null ? 0 : Number(person.count || 0)),
    0,
  );
  const automaticPeople = people.filter((person) => person.count === null).length;
  if (people.some((person) => person.count !== null && person.count > total)) {
    target.textContent = `个人数量不能超过 ${total}，同一人不能重复领取同一个 Issue`;
    return;
  }
  if (fixedTotal > assignmentCount) {
    target.textContent = `已指定 ${fixedTotal} 条，超过任务总数 ${assignmentCount}`;
    return;
  }
  if (!automaticPeople && fixedTotal !== assignmentCount) {
    target.textContent = `已指定 ${fixedTotal} 条，需合计 ${assignmentCount} 条`;
    return;
  }
  if (automaticPeople && assignmentCount - fixedTotal > automaticPeople * total) {
    target.textContent = "剩余任务超过自动均衡人员可领取上限，请降低固定数量或增加人员";
    return;
  }
  const low = people.length ? Math.floor(assignmentCount / people.length) : 0;
  const high = people.length ? Math.ceil(assignmentCount / people.length) : 0;
  target.textContent = reviewers === 1
    ? `单人均分 · ${total} 条任务`
    : `${total} × ${reviewers} = ${assignmentCount} 条盲标任务 · ${
        fixedTotal ? `已指定 ${fixedTotal} 条，其余自动均衡` : `每人约 ${low}${high !== low ? `～${high}` : ""} 条`
      }`;
}

function workAssigneeOptionsWithSelected(options, selected) {
  const known = new Set(options.map((item) => String(item.value || "")));
  const retained = parseFilterList(selected)
    .filter((name) => !known.has(name))
    .map((name) => ({
      value: name,
      // A task owner can be absent from the current facet after changing Run
      // or baseline. Keep the URL-restored choice visible and removable.
      label: `${name} · ${uiText("当前筛选", "Current filter")}`,
    }));
  return [...options, ...retained];
}

function renderWorkAssigneeFilter(selected = workAssigneeFilterSelection()) {
  const root = $("#workAssigneeFilter");
  if (!root) return;
  const items = Array.isArray(state.workAssignees) ? state.workAssignees : [];
  const options = [
    { value: "__none__", label: t("work.unassigned") },
    ...items.map((item) => ({
      value: item.username,
      label: `${item.username} · ${Number(item.issue_count || 0)}`,
    })),
  ];
  renderMultiFilter(root, {
    options: workAssigneeOptionsWithSelected(options, selected),
    selected,
    onChange: (values) => {
      // Persist before triggering the async facet refresh.  Any in-flight
      // detail navigation or top-bar refresh then serializes the same filter.
      persistWorkAssigneeFilterRoute(values);
      scheduleReviewFilterReload?.(0);
    },
  });
}

async function loadWorkAssignees() {
  const requestSeq = ++state.workAssigneeRequestSeq;
  try {
    const params = new URLSearchParams();
    Object.entries(currentReviewFilterPayload()).forEach(([key, value]) => {
      if (key === "work_assignee" || key === "failure_only" || !value) return;
      params.set(key, String(value));
    });
    const query = params.toString();
    const result = await api(`/api/work-assignees${query ? `?${query}` : ""}`);
    if (requestSeq !== state.workAssigneeRequestSeq) return;
    state.workAssignees = result.items || [];
    renderWorkAssigneeFilter(workAssigneeFilterSelection());
  } catch (_error) {
    // Filter remains usable with default options.
  }
}

function updateWorkSplitAdminVisibility() {
  const button = $("#splitFilteredButton");
  const isAdmin = Boolean(state.session?.is_admin);
  const analysisField = $("#analysisWorkAgreementField");
  if (analysisField) analysisField.hidden = !isAdmin;
  if (!button) return;
  button.hidden = !isAdmin;
  if (!isAdmin) button.disabled = true;
}

async function openWorkSplitDialog() {
  if (!state.session?.is_admin) {
    showToast(t("work.split_admin_only"), true);
    return;
  }
  const total = Number(state.caseTotal || 0);
  const summary = $("#workSplitSummary");
  const results = $("#workSplitResults");
  if (summary) {
    summary.textContent = total
      ? t("work.summary_n", { n: total })
      : t("work.no_issues");
  }
  if (results) {
    results.classList.add("hidden");
    results.innerHTML = "";
  }
  try {
    if (!state.accessUsers?.length) {
      await loadAccessUsers();
    }
  } catch (error) {
    showToast(error.message || t("work.load_users_fail"), true);
    return;
  }
  const root = $("#workSplitPeople");
  if (root) {
    root.innerHTML = "";
    const users = state.accessUsers || [];
    if (users.length) {
      users.forEach((user) => {
        root.insertAdjacentHTML("beforeend", workSplitPersonRow(user.username, ""));
      });
    } else {
      ensureWorkSplitPeople(2);
      showToast(t("work.no_writers"), true);
    }
  }
  renderWorkSplitPersonPickers();
  if ($("#workSplitReviewersPerIssue")) $("#workSplitReviewersPerIssue").value = "1";
  renderWorkSplitReviewersPerIssuePicker(1);
  updateWorkSplitEstimate();
  openDialog("workSplitDialog");
}

function renderWorkSplitResults(payload) {
  const root = $("#workSplitResults");
  if (!root) return;
  const assignments = Array.isArray(payload?.assignments) ? payload.assignments : [];
  if (!assignments.length) {
    root.classList.add("hidden");
    root.innerHTML = "";
    return;
  }
  const cards = assignments
    .map((item, index) => {
      const ids = Array.isArray(item.issue_ids) ? item.issue_ids : [];
      const mode =
        item.mode === "fixed"
          ? t("work.fixed_n", { n: item.requested_count ?? "—" })
          : item.mode === "blind"
            ? `${Number(payload.reviewers_per_issue || 2)} 人盲标`
          : t("work.even_rest");
      return `<article class="work-split-card" data-work-split-index="${index}">
        <header>
          <strong>${escapeHtml(item.name || "—")}</strong>
          <span>${escapeHtml(t("runs.count_n", { n: Number(item.count || 0) }))} · ${escapeHtml(mode)}</span>
        </header>
        <textarea class="work-split-ids" readonly rows="4">${escapeHtml(
          ids.join("\n")
        )}</textarea>
        <div class="work-split-card-actions">
          <button class="button button-quiet" type="button" data-copy-work-split="${index}">${escapeHtml(t("work.copy_ids"))}</button>
          <button class="button button-primary" type="button" data-filter-work-assignee="${escapeHtml(
            item.name || ""
          )}">${escapeHtml(t("work.filter_assignee"))}</button>
        </div>
      </article>`;
    })
    .join("");
  root.classList.remove("hidden");
  root.innerHTML = `
    <div class="work-split-results-heading">
      <strong>${escapeHtml(t("work.result_title"))}</strong>
      <span>${escapeHtml(t("work.result_meta", { n: Number(payload.total || 0), seed: payload.split_id || "" }))} · ${Number(payload.assignment_count || payload.total || 0)} 条任务${payload.truncated ? escapeHtml(t("work.truncated")) : ""}</span>
    </div>
    <div class="work-split-card-grid">${cards}</div>
  `;
  root.dataset.payload = JSON.stringify(payload);
}

async function generateWorkSplit() {
  if (!state.session?.is_admin) {
    showToast(t("work.split_admin_only"), true);
    return;
  }
  const assignees = readWorkSplitAssignees();
  if (!assignees.length) {
    showToast(t("work.need_reviewer"), true);
    return;
  }
  const reviewersPerIssue = workSplitReviewersPerIssue();
  const seedRaw = $("#workSplitSeed")?.value.trim() || "";
  const body = {
    filters: currentReviewFilterPayload(),
    assignees,
    reviewers_per_issue: reviewersPerIssue,
  };
  if (body.reviewers_per_issue > assignees.length) {
    showToast("每个 Issue 的复核人数不能超过已选成员数。", true);
    return;
  }
  if (seedRaw !== "") {
    const seed = Number(seedRaw);
    if (!Number.isFinite(seed)) {
      showToast(t("work.seed_int"), true);
      return;
    }
    body.seed = seed;
  }
  const button = $("#workSplitGenerate");
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  }
  try {
    const result = await api("/api/cases/work-split", {
      method: "POST",
      body: JSON.stringify(body),
    });
    acknowledgeLocalChange(result);
    state.workAssigneeRequestSeq += 1;
    if (Array.isArray(result.work_assignees)) {
      state.workAssignees = result.work_assignees;
      renderWorkAssigneeFilter();
    } else {
      await loadWorkAssignees();
    }
    renderWorkSplitResults(result);
    showToast(t("work.saved"));
  } catch (error) {
    showToast(error.message, true);
  } finally {
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }
}

function filterGalleryByWorkAssignee(assignee) {
  const name = String(assignee || "").trim();
  if (!name) return;
  state.reviewIssueIds = [];
  setMultiFilterValues($("#workAssigneeFilter"), [name]);
  persistWorkAssigneeFilterRoute([name]);
  state.casePage = 1;
  closeDialog("workSplitDialog");
  loadCases({ keepSelection: false, page: 1 })
    .then(() => showToast(`已筛选任务负责人：${name}`))
    .catch((error) => showToast(error.message, true));
}

function copyWorkSplitAssignment(index) {
  const root = $("#workSplitResults");
  if (!root?.dataset.payload) return;
  let payload;
  try {
    payload = JSON.parse(root.dataset.payload);
  } catch (_error) {
    showToast("无法读取分配结果。", true);
    return;
  }
  const item = payload.assignments?.[Number(index)];
  const ids = Array.isArray(item?.issue_ids) ? item.issue_ids : [];
  if (!ids.length) {
    showToast("该成员没有分到 Issue。", true);
    return;
  }
  const text = ids.join("\n");
  const done = () => showToast(`已复制 ${item.name} 的 ${ids.length} 个 Issue ID。`);
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => {
      window.prompt("复制以下 Issue ID：", text);
    });
    return;
  }
  window.prompt("复制以下 Issue ID：", text);
  done();
}

function bindWorkSplitControls() {
  $("#splitFilteredButton")?.addEventListener("click", () => {
    if (!state.session?.is_admin) {
      showToast(t("work.split_admin_only"), true);
      return;
    }
    if (!state.caseTotal) {
      showToast(t("work.no_issues"), true);
      return;
    }
    openWorkSplitDialog().catch((error) => showToast(error.message, true));
  });
  $("#workSplitAddPerson")?.addEventListener("click", () => {
    $("#workSplitPeople")?.insertAdjacentHTML("beforeend", workSplitPersonRow());
    renderWorkSplitPersonPickers();
    renderWorkSplitReviewersPerIssuePicker();
    updateWorkSplitEstimate();
  });
  $("#workSplitPeople")?.addEventListener("click", (event) => {
    const remove = event.target.closest(".work-split-remove-person");
    if (!remove) return;
    const row = remove.closest(".work-split-person-row");
    const root = $("#workSplitPeople");
    if (!row || !root) return;
    row.remove();
    ensureWorkSplitPeople(1);
    renderWorkSplitPersonPickers();
    renderWorkSplitReviewersPerIssuePicker();
    updateWorkSplitEstimate();
  });
  $("#workSplitPeople")?.addEventListener("change", (event) => {
    if (event.target.matches(".work-split-person-name")) {
      event.target.closest(".work-split-person-picker").dataset.workSplitSelected =
        event.target.value || "";
      renderWorkSplitPersonPickers();
      renderWorkSplitReviewersPerIssuePicker();
    }
    updateWorkSplitEstimate();
  });
  $("#workSplitPeople")?.addEventListener("input", (event) => {
    if (event.target.matches(".work-split-person-count")) updateWorkSplitEstimate();
  });
  $("#workSplitReviewersPerIssue")?.addEventListener("change", updateWorkSplitEstimate);
  $("#workSplitGenerate")?.addEventListener("click", () => {
    generateWorkSplit().catch((error) => showToast(error.message, true));
  });
  $("#workSplitResults")?.addEventListener("click", (event) => {
    const copy = event.target.closest("[data-copy-work-split]");
    if (copy) {
      copyWorkSplitAssignment(copy.dataset.copyWorkSplit);
      return;
    }
    const filter = event.target.closest("[data-filter-work-assignee]");
    if (filter) filterGalleryByWorkAssignee(filter.dataset.filterWorkAssignee);
  });
}
