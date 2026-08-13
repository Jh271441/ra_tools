/* ra_triage_dashboard/static/js/work-split.js
 * Admin Review work-split: persist assignee ownership and gallery filters.
 * Loaded as a classic script (shared global scope).
 */
function currentReviewFilterPayload() {
  return {
    search: $("#searchInput")?.value.trim() || "",
    gt_label: joinFilterList(getMultiFilterValues($("#gtFilter"))),
    model_label: joinFilterList(getMultiFilterValues($("#annotationFilter"))),
    annotation_author: joinFilterList(getMultiFilterValues($("#reviewerFilter"))),
    review_status: joinFilterList(getMultiFilterValues($("#reviewStatusFilter"))),
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
  const options = [
    `<option value="">${escapeHtml(t("work.pick_person"))}</option>`,
    ...users.map(
      (item) =>
        `<option value="${escapeHtml(item.username)}"${
          item.username === name ? " selected" : ""
        }>${escapeHtml(item.username)}${
          item.role === "admin" ? t("work.admin_suffix") : ""
        }</option>`
    ),
  ].join("");
  return `<div class="work-split-person-row">
    <select class="work-split-person-name" aria-label="复核人">${options}</select>
    <input class="work-split-person-count" type="number" min="0" step="1" placeholder="${escapeHtml(t("work.even_split"))}" value="${escapeHtml(
      count
    )}" title="留空=参与剩余均分；填数字=固定领取数量" />
    <button class="button button-quiet work-split-remove-person" type="button" aria-label="移除">×</button>
  </div>`;
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

function renderWorkAssigneeFilter() {
  const root = $("#workAssigneeFilter");
  if (!root) return;
  const items = Array.isArray(state.workAssignees) ? state.workAssignees : [];
  renderMultiFilter(root, {
    options: [
      { value: "__none__", label: t("work.unassigned") },
      ...items.map((item) => ({
        value: item.username,
        label: `${item.username} · ${Number(item.issue_count || 0)}`,
      })),
    ],
    selected: getMultiFilterValues(root),
    onChange: () => scheduleReviewFilterReload?.(0),
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
    renderWorkAssigneeFilter();
  } catch (_error) {
    // Filter remains usable with default options.
  }
}

function updateWorkSplitAdminVisibility() {
  const button = $("#splitFilteredButton");
  if (!button) return;
  const isAdmin = Boolean(state.session?.is_admin);
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
      <span>${escapeHtml(t("work.result_meta", { n: Number(payload.total || 0), seed: payload.split_id || "" }))}${payload.truncated ? escapeHtml(t("work.truncated")) : ""}</span>
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
  const seedRaw = $("#workSplitSeed")?.value.trim() || "";
  const body = {
    filters: currentReviewFilterPayload(),
    assignees,
  };
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
  });
  $("#workSplitPeople")?.addEventListener("click", (event) => {
    const remove = event.target.closest(".work-split-remove-person");
    if (!remove) return;
    const row = remove.closest(".work-split-person-row");
    const root = $("#workSplitPeople");
    if (!row || !root) return;
    row.remove();
    ensureWorkSplitPeople(1);
  });
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
  $("#workAssigneeFilter")?.addEventListener("change", () => {
    state.reviewIssueIds = [];
    state.casePage = 1;
    loadCases({ keepSelection: false, page: 1 }).catch((error) =>
      showToast(error.message, true)
    );
  });
}
