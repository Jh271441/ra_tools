/* Shared Case/Review people rows, unique-person pickers and quota reading.
 * Existing workSplit* names are the compatibility interface for both pages. */
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

function renderWorkSplitPersonPickers(rootSelector = "#workSplitPeople") {
  const pickers = [...document.querySelectorAll(`${rootSelector} .work-split-person-picker`)];
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

function ensureWorkSplitPeople(minRows = 2, rootSelector = "#workSplitPeople") {
  const root = $(rootSelector);
  if (!root) return;
  while (root.querySelectorAll(".work-split-person-row").length < minRows) {
    root.insertAdjacentHTML("beforeend", workSplitPersonRow());
  }
}

function readWorkSplitAssignees(rootSelector = "#workSplitPeople") {
  const rows = [...document.querySelectorAll(`${rootSelector} .work-split-person-row`)];
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
