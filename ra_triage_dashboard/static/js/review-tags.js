/* ra_triage_dashboard/static/js/review-tags.js
 * Issue tags, missing evidence catalogs, dropdown popovers
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function renderReviewTagGroups(tagCatalog, chosenTags, tagOption) {
  // Axis/group chrome is translated; option labels stay catalog Chinese (domain).
  const definitions = [
    {
      section: "scene",
      label: t("tag.scene"),
      groups: [
        { key: "environment", label: t("tag.env") },
        { key: "self_intent", label: t("tag.ego_intent") },
      ],
    },
    {
      section: "interaction_decision",
      label: t("tag.trigger"),
      groups: [
        { key: "false_trigger", label: t("tag.false_trigger") },
        { key: "true_trigger", label: t("tag.should_trigger") },
      ],
    },
    {
      section: "egress",
      label: t("tag.egress"),
      groups: [
        { key: "ra", label: t("tag.correct_trigger") },
        { key: "no_assist", label: t("tag.no_assist") },
      ],
    },
  ];
  const visible = (tagCatalog || []).filter(
    (item) => item.visible !== false && !item.deleted
  );
  const selectedChipMarkup = (items, section) => items
    .map((item) => `<button class="tag-group-selected-chip" type="button" data-remove-review-tag="${escapeHtml(item.key)}" data-remove-review-tag-group="${escapeHtml(item.group || "")}" data-tag-section="${escapeHtml(section)}" data-tag-group="${escapeHtml(item.group || "")}" title="${escapeHtml(uiText(`取消选择 ${item.label}`, `Deselect ${item.label}`))}"><span>${escapeHtml(item.label)}</span><b aria-hidden="true">×</b></button>`)
    .join("");
  const sections = definitions.map((section) => {
    const sectionItems = visible
      .filter((item) => item.section === section.section && chosenTags.has(item.key))
      .map((item) => ({ ...item, group: item.group || "" }));
    return `
    <div class="review-tag-axis" data-tag-section="${escapeHtml(section.section)}">
      <div class="review-tag-axis-title">
        <span>${escapeHtml(section.label)}</span>
        <span class="review-axis-selected" data-selected-tags-section="${escapeHtml(section.section)}"${sectionItems.length ? "" : " hidden"}>${selectedChipMarkup(sectionItems, section.section)}</span>
      </div>
      <div class="review-tag-groups">
        ${section.groups.map((group) => {
          const items = visible.filter(
            (item) => item.section === section.section && item.group === group.key
          );
          const selectedCount = items.filter((item) => chosenTags.has(item.key)).length;
          const creatorAction = `<button class="tag-catalog-add-button" type="button" data-open-review-tag-creator="${escapeHtml(group.key)}" data-tag-create-group-label="${escapeHtml(group.label)}" aria-label="${escapeHtml(uiText(`新增${group.label}标签`, `Add ${group.label} tag`))}" title="${escapeHtml(uiText(`新增${group.label}标签`, `Add ${group.label} tag`))}">＋</button>`;
          return `<details class="review-tag-dropdown review-dropdown" data-tag-dropdown-group="${escapeHtml(group.key)}">
            <summary>
              <span class="tag-group-label">${escapeHtml(group.label)}</span>
              <span class="tag-group-trailing">
                ${creatorAction}
                <span class="tag-group-summary" data-tag-summary="${escapeHtml(group.key)}">${escapeHtml(t("detail.count_n", { n: selectedCount }))}</span>
                <span class="tag-group-chevron" aria-hidden="true"></span>
              </span>
            </summary>
            <div class="review-tag-options">${items.map((item) => tagOption(item.key, item.label, chosenTags.has(item.key), group.key, item)).join("") || `<div class="review-tag-empty">${escapeHtml(uiText("暂无标签，点 ＋ 添加", "No tags — click ＋ to add"))}</div>`}</div>
          </details>`;
        }).join("")}
      </div>
    </div>`;
  }).join("");
  const legacy = (tagCatalog || []).filter(
    (item) => (item.visible === false || item.deleted) && chosenTags.has(item.key)
  );
  if (legacy.length) {
    return `${sections}
      <div class="review-tag-legacy"><span>${escapeHtml(uiText("历史标签", "Legacy tags"))}</span><div class="review-tag-options">${legacy.map((item) => tagOption(item.key, item.label, true)).join("")}</div></div>`;
  }
  return sections;
}

function updateEvidenceSummary() {
  const root = $("#reviewPane") || document;
  const selected = [...root.querySelectorAll('input[name="missingEvidence"]:checked')].map((input) => ({
    key: input.value,
    label: input.parentElement?.querySelector("span")?.textContent?.trim() || evidenceLabel(input.value),
  }));
  const count = selected.length;
  const target = $("#evidenceSummaryCount");
  if (target) target.textContent = `已选 ${count} 项`;
  const selectedContainer = root.querySelector("[data-selected-missing-evidence]");
  if (!selectedContainer) return;
  selectedContainer.innerHTML = selected
    .map((item) => `<button class="tag-group-selected-chip missing-evidence-selected-chip" type="button" data-remove-review-evidence="${escapeHtml(item.key)}" title="取消选择 ${escapeHtml(item.label)}"><span>${escapeHtml(item.label)}</span><b aria-hidden="true">×</b></button>`)
    .join("");
  selectedContainer.hidden = selected.length === 0;
}

function setMissingEvidenceCatalogFromResult(result) {
  if (!result || !Array.isArray(result.missing_evidence_catalog)) return;
  state.config = {
    ...(state.config || {}),
    missing_evidence_catalog: result.missing_evidence_catalog,
  };
  acknowledgeLocalChange(result);
  renderConfig();
}

function missingEvidenceCatalogItem(key) {
  return (state.config?.missing_evidence_catalog || []).find(
    (item) => String(item.key) === String(key)
  );
}

function updateMissingEvidenceOptionRow(item) {
  const row = [...document.querySelectorAll("[data-evidence-option]")].find(
    (node) => node.dataset.evidenceOption === String(item?.key || "")
  );
  if (!row) return;
  const label = row.querySelector(".tag-option-check span, span");
  const shell = row.querySelector(".tag-option") || row;
  if (label) label.textContent = String(item?.label || evidenceLabel(item?.key));
  if (shell) {
    if (item?.hint) shell.title = String(item.hint);
    else shell.removeAttribute("title");
  }
}

function markDeletedMissingEvidenceOption(item) {
  const row = [...document.querySelectorAll("[data-evidence-option]")].find(
    (node) => node.dataset.evidenceOption === String(item?.key || "")
  );
  if (!row) return;
  const checkbox = row.querySelector('input[name="missingEvidence"]');
  if (checkbox?.checked) {
    row.classList.add("tag-option-deleted", "evidence-option-deleted");
    row.querySelector(".tag-option")?.classList.add("tag-option-deleted");
    row.querySelector(".tag-option-menu")?.remove();
    const shell = row.querySelector(".tag-option") || row;
    shell.title = "已从共享目录删除；当前 Review 仍保留此历史值";
  } else {
    row.remove();
  }
  updateEvidenceSummary();
}

function openMissingEvidenceEditorDialog({
  mode = "create",
  key = "",
  label = "",
  hint = "",
} = {}) {
  const dialog = $("#missingEvidenceCreateDialog");
  const form = $("#missingEvidenceCreateForm");
  const modeInput = $("#missingEvidenceCreateMode");
  const keyInput = $("#missingEvidenceCreateKey");
  const labelInput = $("#missingEvidenceCreateLabel");
  const hintInput = $("#missingEvidenceCreateHint");
  const title = $("#missingEvidenceCreateDialogTitle");
  const copy = $("#missingEvidenceCreateDialogHint");
  const submit = $("#missingEvidenceCreateSubmit");
  if (!dialog || !form || !labelInput) return;
  const resolvedMode = mode === "edit" ? "edit" : "create";
  if (modeInput) modeInput.value = resolvedMode;
  if (keyInput) keyInput.value = resolvedMode === "edit" ? String(key || "") : "";
  labelInput.value = resolvedMode === "edit" ? String(label || "") : "";
  if (hintInput) hintInput.value = resolvedMode === "edit" ? String(hint || "") : "";
  if (title) title.textContent = resolvedMode === "edit" ? "编辑缺失信息" : "新增缺失信息";
  if (copy) {
    copy.textContent =
      resolvedMode === "edit"
        ? "修改共享目录条目；历史 Review 中的 key 不变。"
        : "写入共享目录后，所有用户与 Issue 均可使用。";
  }
  if (submit) submit.textContent = resolvedMode === "edit" ? "保存修改" : "添加条目";
  openDialog("missingEvidenceCreateDialog");
  window.requestAnimationFrame(() => {
    labelInput.focus();
    if (resolvedMode === "edit") labelInput.select();
  });
}

function appendMissingEvidenceOption(item) {
  const key = String(item?.key || "");
  if (!key) return;
  const list = $("#missingEvidenceOptions");
  if (!list) return;
  if (
    [...document.querySelectorAll('input[name="missingEvidence"]')].some(
      (node) => node.value === key
    )
  ) {
    return;
  }
  list.querySelector(".review-tag-empty")?.remove();
  const template = document.createElement("template");
  template.innerHTML = missingEvidenceOptionMarkup(
    {
      ...item,
      label: item.label || evidenceLabel(key),
      hint: item.hint || "",
      builtin: false,
    },
    true,
    true
  );
  const option = template.content.firstElementChild;
  list.appendChild(option);
  option?.querySelector("input")?.addEventListener("change", updateEvidenceSummary);
  bindMissingEvidenceCatalogControls(option || list);
  bindReviewTagCatalogControls(option || list);
}

function bindMissingEvidenceCatalogControls(root = document) {
  root.querySelectorAll("[data-open-missing-evidence-creator]").forEach((button) => {
    if (button.dataset.missingEvidenceBound === "1") return;
    button.dataset.missingEvidenceBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openMissingEvidenceEditorDialog({ mode: "create" });
    });
  });
  // Dialog form lives outside the review pane; bind once from document.
  const createForm = $("#missingEvidenceCreateForm");
  if (createForm && createForm.dataset.missingEvidenceBound !== "1") {
    createForm.dataset.missingEvidenceBound = "1";
    createForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const mode = String($("#missingEvidenceCreateMode")?.value || "create");
      const key = String($("#missingEvidenceCreateKey")?.value || "").trim();
      const value = String($("#missingEvidenceCreateLabel")?.value || "").trim();
      const hint = String($("#missingEvidenceCreateHint")?.value || "").trim();
      const submit = $("#missingEvidenceCreateSubmit");
      if (!value) return showToast("请输入缺失信息标题。", true);
      if (value.length > 48 || /[\x00-\x1f\x7f]/.test(value)) {
        return showToast("缺失信息标题长度或字符不合法。", true);
      }
      if (hint.length > 160 || /[\x00-\x1f\x7f]/.test(hint)) {
        return showToast("缺失信息说明长度或字符不合法。", true);
      }
      if (mode === "edit" && !key) {
        return showToast("缺少要编辑的缺失信息。", true);
      }
      if (submit) {
        submit.disabled = true;
        submit.setAttribute("aria-busy", "true");
      }
      try {
        if (mode === "edit") {
          const result = await api(`/api/missing-evidence/${encodeURIComponent(key)}`, {
            method: "PUT",
            body: JSON.stringify({ label: value, hint }),
          });
          setMissingEvidenceCatalogFromResult(result);
          updateMissingEvidenceOptionRow(result.item || { key, label: value, hint });
          closeDialog("missingEvidenceCreateDialog");
          showToast("缺失信息已更新。");
        } else {
          const result = await api("/api/missing-evidence", {
            method: "POST",
            body: JSON.stringify({ label: value, hint }),
          });
          setMissingEvidenceCatalogFromResult(result);
          appendMissingEvidenceOption(result.item || {});
          state.reviewFormDirty = true;
          updateEvidenceSummary();
          closeDialog("missingEvidenceCreateDialog");
          showToast("已加入共享目录，所有用户和 Issue 均可使用。");
        }
      } catch (error) {
        showToast(error.message, true);
      } finally {
        if (submit) {
          submit.disabled = false;
          submit.removeAttribute("aria-busy");
        }
      }
    });
  }
  root.querySelectorAll("[data-edit-missing-evidence]").forEach((button) => {
    if (button.dataset.missingEvidenceBound === "1") return;
    button.dataset.missingEvidenceBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      closeAllTagOptionMenus();
      const key = String(button.dataset.editMissingEvidence || "");
      const item = missingEvidenceCatalogItem(key);
      if (!item || item.deleted) return;
      openMissingEvidenceEditorDialog({
        mode: "edit",
        key,
        label: item.label || "",
        hint: item.hint || "",
      });
    });
  });
  root.querySelectorAll("[data-delete-missing-evidence]").forEach((button) => {
    if (button.dataset.missingEvidenceBound === "1") return;
    button.dataset.missingEvidenceBound = "1";
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      closeAllTagOptionMenus();
      const key = String(button.dataset.deleteMissingEvidence || "");
      const item = missingEvidenceCatalogItem(key);
      if (!item || item.deleted) return;
      if (!window.confirm(`确认删除“${item.label}”？\n历史 Review 仍会保留该标签。`)) return;
      button.disabled = true;
      try {
        const result = await api(`/api/missing-evidence/${encodeURIComponent(key)}`, {
          method: "DELETE",
          body: JSON.stringify({}),
        });
        setMissingEvidenceCatalogFromResult(result);
        markDeletedMissingEvidenceOption(result.item || { key });
        showToast("缺失信息已删除。");
      } catch (error) {
        showToast(error.message, true);
      } finally {
        button.disabled = false;
      }
    });
  });
}

function updateTagSummary() {
  const inputs = [...document.querySelectorAll('input[name="reviewTags"]')];
  const count = inputs.filter((input) => input.checked).length;
  const target = $("#tagSummaryCount");
  if (target) target.textContent = `已选 ${count} 项`;
  document.querySelectorAll("[data-tag-summary]").forEach((summary) => {
    const group = summary.dataset.tagSummary || "";
    const groupCount = inputs.filter(
      (input) => input.checked && input.dataset.tagGroup === group
    ).length;
    summary.textContent = `${groupCount} 项`;
  });
  document.querySelectorAll("[data-selected-tags-section]").forEach((container) => {
    const root = container.closest(".review-tag-axis");
    if (!root) return;
    const section = container.dataset.selectedTagsSection || "";
    const selected = [...root.querySelectorAll('input[name="reviewTags"]')]
      .filter((input) => input.checked)
      .map((input) => ({
        key: input.value,
        label: input.parentElement?.querySelector("span")?.textContent?.trim() || input.value,
        group: input.dataset.tagGroup || "",
      }));
    container.innerHTML = selected
      .map((item) => `<button class="tag-group-selected-chip" type="button" data-remove-review-tag="${escapeHtml(item.key)}" data-remove-review-tag-group="${escapeHtml(item.group)}" data-tag-section="${escapeHtml(section)}" data-tag-group="${escapeHtml(item.group)}" title="取消选择 ${escapeHtml(item.label)}"><span>${escapeHtml(item.label)}</span><b aria-hidden="true">×</b></button>`)
      .join("");
    container.hidden = selected.length === 0;
  });
}

function bindSelectedReviewTagControls(root) {
  if (!root || root.dataset.selectedReviewTagControlsBound === "1") return;
  root.dataset.selectedReviewTagControlsBound = "1";
  root.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-review-tag], [data-remove-review-evidence]");
    if (!button || !root.contains(button)) return;
    event.preventDefault();
    event.stopPropagation();
    const isEvidence = button.hasAttribute("data-remove-review-evidence");
    const key = isEvidence
      ? button.dataset.removeReviewEvidence || ""
      : button.dataset.removeReviewTag || "";
    const input = root.querySelector(
      `${isEvidence ? 'input[name="missingEvidence"]' : 'input[name="reviewTags"]'}[value="${CSS.escape(key)}"]`
    );
    if (!input) return;
    input.checked = false;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function setReviewTagCatalogFromResult(result) {
  if (!result || !Array.isArray(result.review_tag_catalog)) return;
  state.config = {
    ...(state.config || {}),
    review_tag_catalog: result.review_tag_catalog,
  };
  acknowledgeLocalChange(result);
  renderConfig();
}

function reviewTagCatalogOptionRow(key) {
  return [...document.querySelectorAll("[data-review-tag-option]")].find(
    (node) => node.dataset.reviewTagOption === String(key || "")
  );
}

function updateReviewTagOptionRow(item) {
  const row = reviewTagCatalogOptionRow(item?.key);
  if (!row) return;
  const option = row.querySelector(".tag-option");
  const label = option?.querySelector(".tag-option-check span, span");
  if (label) label.textContent = String(item?.label || tagLabel(item?.key));
  if (option) {
    if (item?.hint) option.title = String(item.hint);
    else option.removeAttribute("title");
  }
}

function markDeletedReviewTagOption(item) {
  const row = reviewTagCatalogOptionRow(item?.key);
  if (!row) return;
  const checkbox = row.querySelector('input[name="reviewTags"]');
  if (checkbox?.checked) {
    row.classList.add("tag-option-deleted");
    row.querySelector(".tag-option")?.classList.add("tag-option-deleted");
    row.querySelector(".tag-option-menu")?.remove();
  } else {
    row.remove();
  }
  updateTagSummary();
}

function reviewTagGroupLabel(group = "environment") {
  const key = String(group || "environment");
  if (key === "environment") return "环境";
  if (key === "self_intent") return "自车意图";
  if (key === "false_trigger") return "误触发";
  if (key === "true_trigger") return "应该触发";
  if (key === "ra") return "正确触发";
  if (key === "no_assist") return "无需协助";
  return key;
}

// Keep the historical name for any remaining callers.
function sceneTagGroupLabel(group = "environment") {
  return reviewTagGroupLabel(group);
}

function openReviewTagEditorDialog({
  mode = "create",
  group = "environment",
  groupLabel = "",
  key = "",
  label = "",
  hint = "",
} = {}) {
  const dialog = $("#reviewTagCreateDialog");
  const form = $("#reviewTagCreateForm");
  const modeInput = $("#reviewTagCreateMode");
  const keyInput = $("#reviewTagCreateKey");
  const groupInput = $("#reviewTagCreateGroup");
  const labelInput = $("#reviewTagCreateLabel");
  const hintInput = $("#reviewTagCreateHint");
  const title = $("#reviewTagCreateDialogTitle");
  const copy = $("#reviewTagCreateDialogHint");
  const submit = $("#reviewTagCreateSubmit");
  if (!dialog || !form || !groupInput || !labelInput) return;
  const resolvedMode = mode === "edit" ? "edit" : "create";
  const resolvedGroup = String(group || "environment");
  const resolvedLabel = String(groupLabel || reviewTagGroupLabel(resolvedGroup));
  if (modeInput) modeInput.value = resolvedMode;
  if (keyInput) keyInput.value = resolvedMode === "edit" ? String(key || "") : "";
  groupInput.value = resolvedGroup;
  labelInput.value = resolvedMode === "edit" ? String(label || "") : "";
  if (hintInput) hintInput.value = resolvedMode === "edit" ? String(hint || "") : "";
  if (title) {
    title.textContent = resolvedMode === "edit"
      ? `编辑${resolvedLabel}标签`
      : `新增${resolvedLabel}标签`;
  }
  if (copy) {
    copy.textContent = resolvedMode === "edit"
      ? `修改「${resolvedLabel}」共享目录中的标签；历史 Review 中的 key 不变。`
      : `添加到「${resolvedLabel}」共享目录；所有用户与 Issue 均可使用。`;
  }
  if (submit) submit.textContent = resolvedMode === "edit" ? "保存修改" : "添加标签";
  openDialog("reviewTagCreateDialog");
  window.requestAnimationFrame(() => {
    labelInput.focus();
    if (resolvedMode === "edit") labelInput.select();
  });
}

function openReviewTagCreateDialog(group = "environment", groupLabel = "") {
  openReviewTagEditorDialog({ mode: "create", group, groupLabel });
}

function appendReviewTagOptionToGroup(item, group) {
  const key = String(item?.key || "");
  if (!key || reviewTagCatalogOptionRow(key)) return;
  const groupKey = String(group || "").replace(/["\\]/g, "");
  const list = document.querySelector(
    `.review-tag-dropdown[data-tag-dropdown-group="${groupKey}"] .review-tag-options`
  );
  if (!list) return;
  list.querySelector(".review-tag-empty")?.remove();
  const template = document.createElement("template");
  template.innerHTML = reviewTagOptionMarkup(item, true, group, true);
  const option = template.content.firstElementChild;
  list.appendChild(option);
  option?.querySelector('input[name="reviewTags"]')?.addEventListener("change", updateTagSummary);
  bindReviewTagCatalogControls(option || list);
}

function resetTagOptionMenuPanel(panel) {
  if (!panel) return;
  panel.classList.remove(
    "is-drop-up",
    "is-drop-down",
    "is-fixed-menu",
    "is-positioned",
    "is-measuring"
  );
  panel.style.position = "";
  panel.style.top = "";
  panel.style.left = "";
  panel.style.right = "";
  panel.style.bottom = "";
  panel.style.maxHeight = "";
  panel.style.visibility = "";
  panel.style.opacity = "";
  panel.style.pointerEvents = "";
  panel.style.zIndex = "";
}

/** Park ⋯ menu off-screen before first paint so absolute top:100% never flashes down. */
function prepareTagOptionMenuPanelForMeasure(panel) {
  if (!panel) return;
  panel.classList.add("is-fixed-menu", "is-measuring");
  panel.classList.remove("is-positioned", "is-drop-up", "is-drop-down");
  panel.style.position = "fixed";
  panel.style.right = "auto";
  panel.style.bottom = "auto";
  panel.style.top = "0px";
  panel.style.left = "-10000px";
  panel.style.visibility = "hidden";
  panel.style.opacity = "0";
  panel.style.pointerEvents = "none";
  panel.style.maxHeight = "";
  panel.style.zIndex = "80";
}

function positionTagOptionMenuPanel(menu) {
  const toggle = menu?.querySelector("[data-tag-menu-toggle]");
  const panel = menu?.querySelector(".tag-option-menu-panel");
  if (!toggle || !panel || panel.hidden) return;

  // Stay hidden while measuring/placing (no intermediate absolute downward paint).
  prepareTagOptionMenuPanelForMeasure(panel);
  // Temporary origin for accurate getBoundingClientRect height/width.
  panel.style.left = "0px";
  panel.style.top = "0px";

  const toggleRect = toggle.getBoundingClientRect();
  const panelRect = panel.getBoundingClientRect();
  const gap = 3;
  const margin = 6;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const scroller =
    menu.closest(".review-tag-options") ||
    menu.closest(".evidence-options") ||
    null;
  const clip = scroller?.getBoundingClientRect();
  const clipTop = Math.max(0, clip?.top ?? 0);
  const clipBottom = Math.min(vh, clip?.bottom ?? vh);
  const spaceBelow = clipBottom - toggleRect.bottom - gap;
  const spaceAbove = toggleRect.top - clipTop - gap;
  const need = panelRect.height || 64;
  const openUp =
    spaceBelow < need && spaceAbove > spaceBelow
      ? true
      : spaceBelow < need && spaceAbove >= need
        ? true
        : false;

  let top = openUp
    ? toggleRect.top - panelRect.height - gap
    : toggleRect.bottom + gap;
  if (openUp) {
    panel.classList.add("is-drop-up");
    // If still short above, cap height and pin to the top of the clip area.
    if (spaceAbove < need && spaceAbove > 40) {
      panel.style.maxHeight = `${Math.floor(spaceAbove)}px`;
      top = toggleRect.top - Math.min(panelRect.height, spaceAbove) - gap;
    }
  } else {
    panel.classList.add("is-drop-down");
    if (spaceBelow < need && spaceBelow > 40) {
      panel.style.maxHeight = `${Math.floor(spaceBelow)}px`;
    }
  }

  top = Math.max(margin, Math.min(top, vh - (panel.offsetHeight || panelRect.height) - margin));
  let left = toggleRect.right - (panel.offsetWidth || panelRect.width);
  left = Math.max(margin, Math.min(left, vw - (panel.offsetWidth || panelRect.width) - margin));
  panel.style.top = `${Math.round(top)}px`;
  panel.style.left = `${Math.round(left)}px`;
  panel.classList.remove("is-measuring");
  panel.classList.add("is-fixed-menu", "is-positioned");
  // Reveal only at final coords (single paint — never down-then-up).
  panel.style.visibility = "";
  panel.style.opacity = "";
  panel.style.pointerEvents = "";
}

function closeAllTagOptionMenus(except = null) {
  document.querySelectorAll(".tag-option-menu.is-open").forEach((menu) => {
    if (except && menu === except) return;
    menu.classList.remove("is-open");
    const toggle = menu.querySelector("[data-tag-menu-toggle]");
    const panel = menu.querySelector(".tag-option-menu-panel");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
    if (panel) {
      panel.hidden = true;
      resetTagOptionMenuPanel(panel);
    }
  });
}

function reviewDropdownPanel(dropdown) {
  if (!dropdown) return null;
  return (
    dropdown.querySelector(".review-tag-options") ||
    dropdown.querySelector(".evidence-options") ||
    null
  );
}

function resetReviewDropdownPanel(panel) {
  if (!panel) return;
  panel.classList.remove(
    "is-drop-up",
    "is-drop-down",
    "is-fixed-dropdown",
    "is-positioned",
    "is-measuring"
  );
  panel.style.position = "";
  panel.style.top = "";
  panel.style.left = "";
  panel.style.right = "";
  panel.style.bottom = "";
  panel.style.width = "";
  panel.style.maxHeight = "";
  panel.style.visibility = "";
  panel.style.opacity = "";
  panel.style.pointerEvents = "";
  panel.style.zIndex = "";
}

/** Park panel off-screen/hidden before first paint so default absolute top:100% never flashes. */
function prepareReviewDropdownPanelForMeasure(panel) {
  if (!panel) return;
  panel.classList.add("is-fixed-dropdown", "is-measuring");
  panel.classList.remove("is-positioned", "is-drop-up", "is-drop-down");
  panel.style.position = "fixed";
  panel.style.right = "auto";
  panel.style.bottom = "auto";
  panel.style.top = "0px";
  panel.style.left = "-10000px";
  panel.style.visibility = "hidden";
  panel.style.opacity = "0";
  panel.style.pointerEvents = "none";
  panel.style.maxHeight = "";
  panel.style.zIndex = "70";
}

function positionReviewDropdownPanel(dropdown) {
  if (!dropdown?.open) return;
  const summary = dropdown.querySelector(":scope > summary");
  const panel = reviewDropdownPanel(dropdown);
  if (!summary || !panel) return;

  // Stay hidden while measuring/placing (no intermediate downward absolute paint).
  prepareReviewDropdownPanelForMeasure(panel);

  const summaryRect = summary.getBoundingClientRect();
  const width = Math.max(summaryRect.width, 180);
  panel.style.width = `${Math.round(width)}px`;
  // Temporarily place at origin with full width for accurate scrollHeight.
  panel.style.left = "0px";
  panel.style.top = "0px";

  // Prefer down; flip up only when below is short and above has more room.
  const naturalH = panel.scrollHeight || panel.getBoundingClientRect().height || 200;
  const gap = 4;
  const margin = 8;
  const vh = window.innerHeight;
  const vw = window.innerWidth;
  const spaceBelow = vh - summaryRect.bottom - gap - margin;
  const spaceAbove = summaryRect.top - gap - margin;
  const openUp =
    spaceBelow < Math.min(naturalH, 160) && spaceAbove > spaceBelow;

  const available = Math.max(120, Math.floor(openUp ? spaceAbove : spaceBelow));
  const maxH = Math.min(available, Math.floor(vh * 0.55), 420);
  panel.style.maxHeight = `${maxH}px`;

  const height = Math.min(panel.scrollHeight || naturalH, maxH);
  let top = openUp
    ? summaryRect.top - height - gap
    : summaryRect.bottom + gap;
  top = Math.max(margin, Math.min(top, vh - height - margin));
  let left = summaryRect.left;
  left = Math.max(margin, Math.min(left, vw - width - margin));

  panel.style.top = `${Math.round(top)}px`;
  panel.style.left = `${Math.round(left)}px`;
  panel.classList.remove("is-measuring");
  panel.classList.add("is-fixed-dropdown", "is-positioned");
  panel.classList.add(openUp ? "is-drop-up" : "is-drop-down");
  // Reveal only at final coords (single paint).
  panel.style.visibility = "";
  panel.style.opacity = "";
  panel.style.pointerEvents = "";
}

function closeAllReviewDropdowns(except = null) {
  document.querySelectorAll(".review-dropdown[open]").forEach((dropdown) => {
    if (except && dropdown === except) return;
    dropdown.open = false;
    resetReviewDropdownPanel(reviewDropdownPanel(dropdown));
  });
}

function bindReviewDropdownDismiss() {
  if (document.documentElement.dataset.reviewDropdownDismissBound === "1") return;
  document.documentElement.dataset.reviewDropdownDismissBound = "1";
  document.addEventListener(
    "click",
    (event) => {
      const target = event.target instanceof Element ? event.target : null;
      // Fixed panels live outside the details box hit-test for some events;
      // keep clicks inside the open panel from dismissing.
      if (target?.closest(".review-tag-options.is-fixed-dropdown, .evidence-options.is-fixed-dropdown")) {
        return;
      }
      const current = target?.closest(".review-dropdown") || null;
      closeAllReviewDropdowns(current);
    },
    true
  );
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Escape") closeAllReviewDropdowns();
    },
    true
  );
  document.addEventListener(
    "scroll",
    (event) => {
      if (!document.querySelector(".review-dropdown[open]")) return;
      const target = event.target;
      if (
        target instanceof Element &&
        target.closest(
          ".review-tag-options.is-fixed-dropdown, .evidence-options.is-fixed-dropdown, .tag-option-menu-panel"
        )
      ) {
        return;
      }
      closeAllReviewDropdowns();
    },
    true
  );
  window.addEventListener("resize", () => closeAllReviewDropdowns());
}

function bindReviewTagCatalogControls(root = document) {
  root.querySelectorAll("[data-open-review-tag-creator]").forEach((button) => {
    if (button.dataset.reviewTagBound === "1") return;
    button.dataset.reviewTagBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openReviewTagCreateDialog(
        button.dataset.openReviewTagCreator || "environment",
        button.dataset.tagCreateGroupLabel || ""
      );
    });
  });
  root.querySelectorAll("[data-tag-menu-toggle]").forEach((button) => {
    if (button.dataset.reviewTagBound === "1") return;
    button.dataset.reviewTagBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const menu = button.closest(".tag-option-menu");
      const panel = menu?.querySelector(".tag-option-menu-panel");
      if (!menu || !panel) return;
      const willOpen = panel.hidden;
      closeAllTagOptionMenus(willOpen ? menu : null);
      menu.classList.toggle("is-open", willOpen);
      button.setAttribute("aria-expanded", willOpen ? "true" : "false");
      if (willOpen) {
        // Unhide while parked off-screen, then place + reveal in the same tick.
        panel.hidden = false;
        prepareTagOptionMenuPanelForMeasure(panel);
        positionTagOptionMenuPanel(menu);
      } else {
        panel.hidden = true;
        resetTagOptionMenuPanel(panel);
      }
    });
  });
  if (!document.documentElement.dataset.tagMenuDismissBound) {
    document.documentElement.dataset.tagMenuDismissBound = "1";
    document.addEventListener(
      "click",
      (event) => {
        if (event.target.closest(".tag-option-menu")) return;
        closeAllTagOptionMenus();
      },
      true
    );
    document.addEventListener(
      "keydown",
      (event) => {
        if (event.key === "Escape") closeAllTagOptionMenus();
      },
      true
    );
    // List scroll or viewport resize would leave a fixed panel stranded.
    document.addEventListener(
      "scroll",
      (event) => {
        if (!document.querySelector(".tag-option-menu.is-open")) return;
        const target = event.target;
        if (
          target instanceof Element &&
          target.closest(".tag-option-menu-panel")
        ) {
          return;
        }
        closeAllTagOptionMenus();
      },
      true
    );
    window.addEventListener("resize", () => closeAllTagOptionMenus());
  }
  // Dialog lives outside the review pane; bind once from document.
  const createForm = $("#reviewTagCreateForm");
  if (createForm && createForm.dataset.reviewTagBound !== "1") {
    createForm.dataset.reviewTagBound = "1";
    createForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const mode = String($("#reviewTagCreateMode")?.value || "create");
      const key = String($("#reviewTagCreateKey")?.value || "").trim();
      const group = String($("#reviewTagCreateGroup")?.value || "environment");
      const value = String($("#reviewTagCreateLabel")?.value || "").trim();
      const hint = String($("#reviewTagCreateHint")?.value || "").trim();
      const submit = $("#reviewTagCreateSubmit");
      if (!value) return showToast("请输入场景标签标题。", true);
      if (value.length > 48 || /[\x00-\x1f\x7f]/.test(value)) {
        return showToast("场景标签标题长度或字符不合法。", true);
      }
      if (hint.length > 160 || /[\x00-\x1f\x7f]/.test(hint)) {
        return showToast("场景标签说明长度或字符不合法。", true);
      }
      if (mode === "edit" && !key) {
        return showToast("缺少要编辑的场景标签。", true);
      }
      if (submit) {
        submit.disabled = true;
        submit.setAttribute("aria-busy", "true");
      }
      try {
        if (mode === "edit") {
          const result = await api(`/api/review-tags/${encodeURIComponent(key)}`, {
            method: "PUT",
            body: JSON.stringify({ label: value, hint, group }),
          });
          setReviewTagCatalogFromResult(result);
          updateReviewTagOptionRow(result.item || { key, label: value, hint });
          closeDialog("reviewTagCreateDialog");
          showToast("场景标签已更新。");
        } else {
          const result = await api("/api/review-tags", {
            method: "POST",
            body: JSON.stringify({ label: value, hint, group }),
          });
          setReviewTagCatalogFromResult(result);
          const item = result.item || {};
          appendReviewTagOptionToGroup(item, group);
          state.reviewFormDirty = true;
          updateTagSummary();
          closeDialog("reviewTagCreateDialog");
          showToast("场景标签已加入共享目录，所有用户和 Issue 均可使用。");
        }
      } catch (error) {
        showToast(error.message, true);
      } finally {
        if (submit) {
          submit.disabled = false;
          submit.removeAttribute("aria-busy");
        }
      }
    });
  }
  root.querySelectorAll("[data-edit-review-tag]").forEach((button) => {
    if (button.dataset.reviewTagBound === "1") return;
    button.dataset.reviewTagBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      closeAllTagOptionMenus();
      const key = String(button.dataset.editReviewTag || "");
      const item = reviewTagCatalogItem(key);
      if (!item || item.deleted) return;
      openReviewTagEditorDialog({
        mode: "edit",
        group: item.group || "environment",
        groupLabel: reviewTagGroupLabel(item.group || "environment"),
        key,
        label: item.label || "",
        hint: item.hint || "",
      });
    });
  });
  root.querySelectorAll("[data-delete-review-tag]").forEach((button) => {
    if (button.dataset.reviewTagBound === "1") return;
    button.dataset.reviewTagBound = "1";
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      closeAllTagOptionMenus();
      const key = String(button.dataset.deleteReviewTag || "");
      const item = reviewTagCatalogItem(key);
      if (!item || item.deleted) return;
      if (!window.confirm(`确认删除“${item.label}”？\n历史 Review 仍会保留该标签。`)) return;
      button.disabled = true;
      try {
        const result = await api(`/api/review-tags/${encodeURIComponent(key)}`, {
          method: "DELETE",
          body: JSON.stringify({}),
        });
        setReviewTagCatalogFromResult(result);
        markDeletedReviewTagOption(result.item || { key });
        showToast("场景标签已删除。 ");
      } catch (error) {
        showToast(error.message, true);
      } finally {
        button.disabled = false;
      }
    });
  });
}

