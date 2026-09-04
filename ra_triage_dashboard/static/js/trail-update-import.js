function trailUpdateDraftText() {
  const draft = state.trailUpdate?.data?.draft;
  return draft ? JSON.stringify(draft, null, 2) : "";
}

function trailIssueDraftText() {
  const draft = state.trailUpdate?.directData?.draft;
  return draft ? JSON.stringify(draft, null, 2) : "";
}

const trailIssueImportState = {
  json: { preview: null, requestSeq: 0 },
  excel: { preview: null, requestSeq: 0 },
};

function trailIssueImportPrefix(mode) {
  return mode === "excel" ? "trailUpdateIssueExcelImport" : "trailUpdateIssueJsonImport";
}

function trailIssueImportElement(mode, suffix) {
  return $(`#${trailIssueImportPrefix(mode)}${suffix}`);
}

function trailIssueImportModeLabel(mode) {
  return mode === "excel"
    ? uiText("Excel", "Excel")
    : uiText("JSON", "JSON");
}

function setTrailIssueImportStatus(mode, message = "", error = false) {
  const status = trailIssueImportElement(mode, "Status");
  if (!status) return;
  status.textContent = message;
  status.classList.toggle("is-error", Boolean(error));
  status.classList.toggle("is-ready", Boolean(message) && !error);
}

function trailIssueImportStatusMeta(status) {
  const value = String(status || "invalid");
  if (value === "ready") {
    return { label: uiText("将导入", "Ready"), className: "is-ready" };
  }
  if (value === "skipped") {
    return { label: uiText("跳过", "Skipped"), className: "is-skipped" };
  }
  return { label: uiText("需修正", "Fix"), className: "is-invalid" };
}

function clearTrailIssueImportPreview(mode) {
  trailIssueImportState[mode].requestSeq += 1;
  trailIssueImportState[mode].preview = null;
  const preview = trailIssueImportElement(mode, "Preview");
  const summary = trailIssueImportElement(mode, "PreviewSummary");
  const rows = trailIssueImportElement(mode, "PreviewRows");
  const apply = trailIssueImportElement(mode, "Apply");
  if (preview) preview.hidden = true;
  if (summary) summary.textContent = "";
  if (rows) rows.innerHTML = "";
  if (apply) apply.disabled = true;
}

function renderTrailIssueImportPreview(mode, data) {
  const preview = trailIssueImportElement(mode, "Preview");
  const summaryNode = trailIssueImportElement(mode, "PreviewSummary");
  const rowsNode = trailIssueImportElement(mode, "PreviewRows");
  const apply = trailIssueImportElement(mode, "Apply");
  if (!preview || !summaryNode || !rowsNode || !apply) return;
  if (!data || typeof data !== "object") {
    clearTrailIssueImportPreview(mode);
    return;
  }
  const summary = data.summary && typeof data.summary === "object" ? data.summary : {};
  const items = Array.isArray(data.items) ? data.items : [];
  const globalErrors = Array.isArray(data.global_errors) ? data.global_errors.filter(Boolean) : [];
  const warnings = Array.isArray(data.warnings) ? data.warnings.filter(Boolean) : [];
  const sourceRows = Number(summary.source_row_count || 0);
  const ready = Number(summary.ready_count || 0);
  const skipped = Number(summary.skipped_count || 0);
  const invalid = Number(summary.invalid_count || 0);
  const message = String(summary.message || "");
  const countText = uiText(
    `源数据 ${sourceRows} 行 · 将导入 ${ready} · 跳过 ${skipped} · 需修正 ${invalid}`,
    `${sourceRows} source row(s) · ${ready} ready · ${skipped} skipped · ${invalid} to fix`
  );
  summaryNode.innerHTML = [
    `<strong>${escapeHtml(message || uiText("导入预览已生成。", "Import preview generated."))}</strong>`,
    `<small>${escapeHtml(countText)}</small>`,
    ...globalErrors.map((item) => `<small class="is-error">${escapeHtml(String(item))}</small>`),
    ...warnings.map((item) => `<small class="is-warning">${escapeHtml(String(item))}</small>`),
  ].join("");
  rowsNode.innerHTML = items.length
    ? items.map((item) => {
      const meta = trailIssueImportStatusMeta(item?.status);
      const source = historicalExclusionSource(item?.source);
      const sourceMarkup = source
        ? historicalExclusionSourceMarkup(source, "trail-update-import-preview-source")
        : `<div class="trail-update-import-preview-source" title="${escapeHtml(String(item?.source_label || ""))}">${escapeHtml(String(item?.source_label || "—"))}</div>`;
      const comment = String(item?.comment || "—");
      const shouldExclude = item?.should_exclude === true
        ? uiText("是", "Yes")
        : item?.should_exclude === false
          ? uiText("否", "No")
          : "—";
      return `<tr class="${meta.className}">
        <td>${escapeHtml(String(item?.row_number || "—"))}</td>
        <td><code>${escapeHtml(String(item?.issue_id || "—"))}</code></td>
        <td>${escapeHtml(shouldExclude)}</td>
        <td><div class="trail-update-import-preview-comment" title="${escapeHtml(comment)}">${escapeHtml(comment)}</div></td>
        <td>${sourceMarkup}</td>
        <td><span class="trail-update-import-preview-state ${meta.className}">${escapeHtml(meta.label)}</span><small class="trail-update-import-preview-message">${escapeHtml(String(item?.message || ""))}</small></td>
      </tr>`;
    }).join("")
    : `<tr><td class="trail-update-empty" colspan="6">${escapeHtml(uiText("没有可展示的导入行。", "No import rows to display."))}</td></tr>`;
  preview.hidden = false;
  apply.disabled = data.can_apply !== true;
}

function openTrailIssueImport(mode) {
  const dialog = trailIssueImportElement(mode, "Dialog");
  if (!dialog || typeof dialog.showModal !== "function") {
    showToast(uiText(`${trailIssueImportModeLabel(mode)} 导入弹窗不可用。`, `${trailIssueImportModeLabel(mode)} import dialog is unavailable.`), true);
    return;
  }
  clearTrailIssueImportPreview(mode);
  setTrailIssueImportStatus(mode, "");
  if (!dialog.open) dialog.showModal();
  if (mode === "json") trailIssueImportElement(mode, "Text")?.focus();
  else trailIssueImportElement(mode, "ChooseFile")?.focus();
}

function closeTrailIssueImport(mode) {
  trailIssueImportElement(mode, "Dialog")?.close();
}

function applyTrailIssueImportPreview(mode) {
  const preview = trailIssueImportState[mode]?.preview;
  if (!preview?.can_apply) {
    setTrailIssueImportStatus(mode, uiText("请先生成无错误的导入预览。", "Build an error-free import preview first."), true);
    return false;
  }
  const entries = Array.isArray(preview.entries) ? preview.entries : [];
  if (!entries.length) {
    setTrailIssueImportStatus(mode, uiText("预览中没有可替换的屏蔽行。", "The preview has no shielding rows to replace."), true);
    return false;
  }
  const list = $("#trailUpdateIssueEntries");
  if (!list) {
    setTrailIssueImportStatus(mode, uiText("Issue 输入区不可用。", "Issue editor is unavailable."), true);
    return false;
  }
  list.innerHTML = entries.map((entry) => renderTrailIssueEntryRow(entry)).join("");
  syncTrailIssueEntryRemoveButtons();
  parseTrailIssueIds();
  clearTrailIssuePreview();
  closeTrailIssueImport(mode);
  setTrailIssueStatus(uiText(
    `已从 ${trailIssueImportModeLabel(mode)} 预览替换 ${entries.length} 个 Issue；尚未写入 Trail，请生成最终预览后确认。`,
    `${entries.length} Issues from the ${trailIssueImportModeLabel(mode)} preview replaced the draft; no Trail write has occurred. Build the final preview to continue.`
  ));
  showToast(uiText(
    `已替换 ${entries.length} 条屏蔽草稿；尚未写入 Trail。`,
    `${entries.length} shielding draft row(s) replaced; Trail has not been written.`
  ));
  return true;
}

async function importTrailIssueJsonFile(file) {
  if (!file) return;
  const text = typeof file.text === "function"
    ? await file.text()
    : await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error(uiText("JSON 文件读取失败。", "Could not read the JSON file.")));
      reader.readAsText(file);
    });
  const textArea = trailIssueImportElement("json", "Text");
  if (textArea) textArea.value = text;
  const fileName = trailIssueImportElement("json", "FileName");
  if (fileName) fileName.textContent = file.name || uiText("已读取 JSON 文件。", "JSON file loaded.");
  clearTrailIssueImportPreview("json");
  setTrailIssueImportStatus("json", uiText("文件已读取，点击“生成导入预览”继续。", "File loaded; build the import preview to continue."));
}

async function previewTrailIssueJsonImport() {
  const raw = String(trailIssueImportElement("json", "Text")?.value || "").trim();
  if (!raw) {
    setTrailIssueImportStatus("json", uiText("请先粘贴 JSON 或选择文件。", "Paste JSON or choose a file first."), true);
    return null;
  }
  let body;
  try {
    body = JSON.parse(raw);
  } catch (_error) {
    setTrailIssueImportStatus("json", uiText("JSON 格式不合法，请粘贴对象或数组。", "Invalid JSON; paste an object or array."), true);
    return null;
  }
  if (!Array.isArray(body) && (!body || typeof body !== "object")) {
    setTrailIssueImportStatus("json", uiText("JSON 必须是对象或数组。", "JSON must be an object or array."), true);
    return null;
  }
  const button = trailIssueImportElement("json", "PreviewButton");
  const requestSeq = ++trailIssueImportState.json.requestSeq;
  button?.toggleAttribute("disabled", true);
  button?.setAttribute("aria-busy", "true");
  setTrailIssueImportStatus("json", uiText("正在解析 JSON 导入预览…", "Parsing JSON import preview…"));
  try {
    const data = await api("/api/trail-attribute-update/issue-import/json-preview", {
      method: "POST",
      body: JSON.stringify(body),
      allowReadOnlyMutation: true,
    });
    if (requestSeq !== trailIssueImportState.json.requestSeq) return data;
    trailIssueImportState.json.preview = data;
    renderTrailIssueImportPreview("json", data);
    const hasErrors = Boolean((data?.global_errors || []).length || Number(data?.summary?.invalid_count || 0));
    setTrailIssueImportStatus("json", String(data?.summary?.message || ""), hasErrors);
    return data;
  } catch (error) {
    if (requestSeq === trailIssueImportState.json.requestSeq) {
      setTrailIssueImportStatus("json", error?.message || uiText("JSON 导入预览失败。", "Could not preview the JSON import."), true);
    }
    return null;
  } finally {
    if (requestSeq === trailIssueImportState.json.requestSeq) {
      button?.toggleAttribute("disabled", false);
      button?.removeAttribute("aria-busy");
    }
  }
}

async function previewTrailIssueExcelImport() {
  const file = trailIssueImportElement("excel", "File")?.files?.[0];
  if (!file) {
    setTrailIssueImportStatus("excel", uiText("请先选择 .xlsx 或 .xlsm 文件。", "Choose a .xlsx or .xlsm file first."), true);
    return null;
  }
  const button = trailIssueImportElement("excel", "PreviewButton");
  const requestSeq = ++trailIssueImportState.excel.requestSeq;
  button?.toggleAttribute("disabled", true);
  button?.setAttribute("aria-busy", "true");
  setTrailIssueImportStatus("excel", uiText("正在解析 Excel 导入预览…", "Parsing Excel import preview…"));
  try {
    const form = new FormData();
    form.append("file", file, file.name || "issue-exclusions.xlsx");
    const data = await api("/api/trail-attribute-update/issue-import/excel-preview", {
      method: "POST",
      body: form,
      allowReadOnlyMutation: true,
    });
    if (requestSeq !== trailIssueImportState.excel.requestSeq) return data;
    trailIssueImportState.excel.preview = data;
    renderTrailIssueImportPreview("excel", data);
    const hasErrors = Boolean((data?.global_errors || []).length || Number(data?.summary?.invalid_count || 0));
    setTrailIssueImportStatus("excel", String(data?.summary?.message || ""), hasErrors);
    return data;
  } catch (error) {
    if (requestSeq === trailIssueImportState.excel.requestSeq) {
      setTrailIssueImportStatus("excel", error?.message || uiText("Excel 导入预览失败。", "Could not preview the Excel import."), true);
    }
    return null;
  } finally {
    if (requestSeq === trailIssueImportState.excel.requestSeq) {
      button?.toggleAttribute("disabled", false);
      button?.removeAttribute("aria-busy");
    }
  }
}

function bindTrailIssueImportEvents(mode) {
  const dialog = trailIssueImportElement(mode, "Dialog");
  trailIssueImportElement(mode, "Close")?.addEventListener("click", () => closeTrailIssueImport(mode));
  trailIssueImportElement(mode, "Cancel")?.addEventListener("click", () => closeTrailIssueImport(mode));
  dialog?.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeTrailIssueImport(mode);
  });
  trailIssueImportElement(mode, "PreviewButton")?.addEventListener("click", () => {
    void (mode === "excel" ? previewTrailIssueExcelImport() : previewTrailIssueJsonImport());
  });
  trailIssueImportElement(mode, "Apply")?.addEventListener("click", () => {
    applyTrailIssueImportPreview(mode);
  });
  trailIssueImportElement(mode, "ChooseFile")?.addEventListener("click", () => {
    trailIssueImportElement(mode, "File")?.click();
  });
  if (mode === "json") {
    trailIssueImportElement(mode, "Text")?.addEventListener("input", () => {
      clearTrailIssueImportPreview(mode);
      setTrailIssueImportStatus(mode, "");
    });
    trailIssueImportElement(mode, "File")?.addEventListener("change", (event) => {
      void importTrailIssueJsonFile(event.target?.files?.[0]).catch((error) => {
        setTrailIssueImportStatus(mode, error?.message || uiText("JSON 文件读取失败。", "Could not read the JSON file."), true);
      });
    });
    return;
  }
  trailIssueImportElement(mode, "File")?.addEventListener("change", (event) => {
    const file = event.target?.files?.[0];
    const fileName = trailIssueImportElement(mode, "FileName");
    if (fileName) {
      fileName.textContent = file?.name || uiText("尚未选择 Excel 文件。", "No Excel file selected.");
    }
    clearTrailIssueImportPreview(mode);
    setTrailIssueImportStatus(
      mode,
      file
        ? uiText("已选择文件，点击“生成导入预览”继续。", "File selected; build the import preview to continue.")
        : ""
    );
  });
}

function trailUpdateJsonContext(mode = state.trailUpdate?.tab || "review") {
  const direct = mode === "issue";
  const text = direct ? trailIssueDraftText() : trailUpdateDraftText();
  if (!text) return null;
  const run = state.trailUpdate?.data?.selected_run || {};
  const safeName = String(run.name || run.id || "run").replace(/[^A-Za-z0-9._-]+/g, "_");
  return {
    text,
    filename: direct ? "trail_issue_exclusion_update.json" : `trail_attribute_update_${safeName}.json`,
    title: direct ? uiText("Issue 屏蔽 JSON 预览", "Issue shielding JSON preview") : uiText("问题排除 JSON 预览", "Issue exclusion JSON preview"),
    subtitle: direct
      ? uiText("当前 Issue ID 屏蔽 Tab 的草稿；可复制或下载。", "Draft from the Issue shielding tab; copy or download it.")
      : uiText("当前 Review 排除汇总 Tab 的草稿；可复制或下载。", "Draft from the Review exclusion tab; copy or download it."),
  };
}

function openTrailUpdateJsonPreview() {
  const context = trailUpdateJsonContext();
  if (!context) {
    showToast(uiText("当前没有可预览的 JSON 草稿。", "There is no JSON draft to preview."), true);
    return;
  }
  const dialog = $("#trailUpdateJsonDialog");
  const preview = $("#trailUpdateJsonPreview");
  if (!dialog || !preview || typeof dialog.showModal !== "function") {
    showToast(uiText("JSON 预览弹窗不可用。", "The JSON preview dialog is unavailable."), true);
    return;
  }
  state.trailUpdate.jsonPreview = context;
  const title = $("#trailUpdateJsonTitle");
  const subtitle = $("#trailUpdateJsonSubtitle");
  if (title) title.textContent = context.title;
  if (subtitle) subtitle.textContent = context.subtitle;
  preview.textContent = context.text;
  if (!dialog.open) dialog.showModal();
}

function trailUpdateJsonForAction() {
  return state.trailUpdate?.jsonPreview || trailUpdateJsonContext();
}

function downloadTrailUpdateJson() {
  const context = trailUpdateJsonForAction();
  if (!context) return;
  const blob = new Blob([context.text], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = context.filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function copyTrailUpdateJson() {
  const context = trailUpdateJsonForAction();
  if (!context) return;
  if (!navigator.clipboard?.writeText) throw new Error(uiText("当前浏览器不支持复制。", "Clipboard is unavailable in this browser."));
  await navigator.clipboard.writeText(context.text);
  showToast(uiText("已复制 JSON。", "JSON copied."));
}

let trailUpdateProgressTimer = null;
let trailUpdateProgressCloseTimer = null;

const TRAIL_UPDATE_PROGRESS_STAGES = [
  { key: "prepare", zh: "校验预览", en: "Validate preview" },
  { key: "request", zh: "连接 Trail 接口", en: "Connect to Trail" },
  { key: "write", zh: "分批写入字段与排除说明", en: "Write fields and exclusion notes in batches" },
  { key: "readback", zh: "批量回读并校验", en: "Read back and verify" },
  { key: "done", zh: "完成", en: "Complete" },
];

