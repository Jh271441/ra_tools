/* ra_triage_dashboard/static/js/import-refresh.js
 * Import, AutoTriage, Trail sync, refresh helpers
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function currentImportKind() {
  return "model";
}

const IMPORT_EXAMPLES = Object.freeze({
  csv: {
    filename: "model_results.csv",
    description: "平铺表格，每行一个 Issue",
    content: [
      "issue_id,model_label,reason,confidence,ra_stuck_auto_result_info",
      'cn32171803,无需协助,"红灯持续亮起，前车停在停止线后，自车同步等待",0.96,"{""reason"":""红绿灯周期性等待"",""confidence"":0.96}"',
      'cn31954847,误触发,"前方大车遮挡，但红灯转绿后车流正常放行",0.88,"{""reason"":""排队等灯"",""confidence"":0.88}"',
      'cn32000543,正确触发,"前车双闪临停，右侧存在可通行空间",0.81,"{""reason"":""异常停车"",""confidence"":0.81}"',
    ].join("\n"),
  },
  json: {
    filename: "model_results.json",
    description: "支持原生 experiment + results 结果包",
    content: [
      "{",
      '  "experiment": {',
      '    "model_name": "Qwen3.5-9B-finetuned/base",',
      '    "prompt": "stuck_triage_auto_opt_api",',
      '    "input_profile": "Camera 9 帧 + RA Events + Ares Animation"',
      "  },",
      '  "results": [',
      "    {",
      '      "issue_id": "cn32171803",',
      '      "model_label": "无需协助",',
      '      "reason": "红绿灯周期性等待",',
      '      "confidence": 0.96',
      "    },",
      "    {",
      '      "issue_id": "cn31954847",',
      '      "ra_stuck_auto_result": "误触发",',
      '      "ra_stuck_auto_result_info": {',
      '        "reason": "排队等灯",',
      '        "confidence": 0.88',
      "      }",
      "    }",
      "  ]",
      "}",
    ].join("\n"),
  },
  xlsx: {
    filename: "model_results.xlsx",
    description: "Sheet1：首行是表头，后续每行一个 Issue",
    content: [
      "Sheet1",
      "",
      "issue_id       | model_label | reason                          | confidence | ra_stuck_auto_result_info",
      "cn32171803     | 无需协助     | 红绿灯周期性等待                  | 0.96       | {\"reason\":\"红绿灯周期性等待\"}",
      "cn31954847     | 误触发       | 排队等灯，红灯转绿后正常放行        | 0.88       | {\"reason\":\"排队等灯\"}",
      "cn32000543     | 正确触发     | 前车双闪临停，存在绕行空间          | 0.81       | {\"reason\":\"异常停车\"}",
    ].join("\n"),
  },
});

function renderImportExample(format = "csv") {
  const key = Object.prototype.hasOwnProperty.call(IMPORT_EXAMPLES, format) ? format : "csv";
  const example = IMPORT_EXAMPLES[key];
  const dialog = $("#importExamplesDialog");
  if (dialog) dialog.dataset.exampleFormat = key;
  document.querySelectorAll("[data-import-example-format]").forEach((tab) => {
    const active = tab.dataset.importExampleFormat === key;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  $("#importExampleFilename").textContent = example.filename;
  $("#importExampleDescription").textContent = example.description;
  $("#importExampleContent").textContent = example.content;
}

function openImportExamples() {
  renderImportExample("csv");
  openDialog("importExamplesDialog");
}

async function copyImportExample() {
  const format = $("#importExamplesDialog")?.dataset.exampleFormat || "csv";
  const example = IMPORT_EXAMPLES[format] || IMPORT_EXAMPLES.csv;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(example.content);
    } else {
      const input = document.createElement("textarea");
      input.value = example.content;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }
    showToast(`已复制 ${example.filename} 示例。`);
  } catch (error) {
    showToast(`复制失败，请直接选中示例内容：${error.message || "浏览器未授权剪贴板"}`, true);
  }
}

function updateImportFields() {
  $("#runNameField")?.classList.remove("hidden");
}

function activateRunSourceTab(kind = "upload") {
  const targetKind = ["upload", "autotriage", "trail"].includes(kind) ? kind : "upload";
  document.querySelectorAll("[data-run-source-tab]").forEach((tab) => {
    const active = tab.dataset.runSourceTab === targetKind;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-run-source-panel]").forEach((panel) => {
    const active = panel.dataset.runSourcePanel === targetKind;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
    panel.setAttribute("aria-hidden", String(!active));
  });
}

function setImportKind(kind) {
  updateImportFields();
  activateRunSourceTab("upload");
}

function openRunImport(kind = "model") {
  navigatePage("runs", { importKind: "model" });
  activateRunSourceTab("upload");
  window.setTimeout(() => $("#runsSourceCard")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
}

async function submitImport(event) {
  event.preventDefault();
  const file = $("#importFile").files[0];
  if (!file) return showToast("请选择文件。", true);
  const form = new FormData();
  form.append("file", file);
  form.append("run_name", $("#runNameInput").value.trim());
  form.append("created_by", state.session.username || "");
  const target = $("#importResult");
  target.classList.remove("hidden");
  target.textContent = "正在导入…";
  try {
    const result = await api("/api/import/model-results", { method: "POST", body: form });
    target.textContent = JSON.stringify(result, null, 2);
    const run = result.run || {};
    if (run.id) {
      state.selectedRunId = String(run.id);
    }
    // 测评 Run 通常只覆盖一个 GT 集：按 issue 命中自动勾选顶栏数据集。
    const switched = await applyInferredBaselinesFromRun(run, { reason: "import" });
    if (!switched) {
      showToast(
        result.duplicate
          ? "已复用相同内容的模型 Run。"
          : "模型 Run 已导入；可从列表切换对比。"
      );
    }
    await Promise.all([
      loadRuns({ preserveEmpty: true }),
      loadOverview(),
      loadCases({ keepSelection: true }),
      loadClusters(),
    ]);
    if ($("#modelRunFilter") && state.selectedRunId) {
      $("#modelRunFilter").value = state.selectedRunId;
    }
    setReviewComparisonStatus(state.reviewComparisonStatus || "mismatch", {
      hasRun: Boolean(state.selectedRunId),
    });
  } catch (error) {
    target.textContent = `导入失败：${error.message}`;
    showToast(error.message, true);
  }
}

function openAutoTriageImport() {
  activateRunSourceTab("autotriage");
}

async function submitAutoTriageImport(event) {
  event.preventDefault();
  const batchRef = $("#autotriageBatchInput")?.value.trim() || "";
  if (!batchRef) return showToast("请输入 AutoTriage Batch ID 或 records 链接。", true);
  const button = $("#importAutoTriageButton");
  const target = $("#autotriageImportResult");
  button.disabled = true;
  button.textContent = "正在拉取…";
  target.classList.remove("hidden");
  target.textContent = "正在通过服务器固定只读接口校验 Batch 与结果覆盖…";
  try {
    const result = await api("/api/import/autotriage", {
      method: "POST",
      body: JSON.stringify({
        batch_id: batchRef,
        run_name: $("#autotriageRunNameInput")?.value.trim() || "",
        created_by: state.session.username || "",
      }),
    });
    const coverage = result.coverage || {};
    const recordUrl = safeUrl(result.record_url);
    target.innerHTML = `
      <strong>${result.duplicate ? "已复用相同内容 Run" : "已创建 AutoTriage 快照 Run"}</strong>
      <span>Batch ${escapeHtml(result.batch_id)} · 接受 ${coverage.accepted_result_count ?? "—"} / 声明 ${coverage.declared_total ?? "—"} 条${coverage.partial ? " · 部分覆盖" : " · 覆盖完整"}</span>
      ${recordUrl ? `<a href="${escapeHtml(recordUrl)}" target="_blank" rel="noreferrer">打开 AutoTriage</a>` : ""}`;
    await loadRuns();
    renderRunManager();
    showToast(coverage.partial ? "Run 已拉取，但平台 Batch 为部分覆盖。" : "AutoTriage Run 已拉取。", Boolean(coverage.partial));
  } catch (error) {
    target.textContent = `拉取失败：${error.message}`;
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "拉取并创建 Run";
  }
}

async function syncTrail(mode = "preview") {
  const createRun = mode === "create";
  if (
    createRun &&
    !window.confirm(
      "将创建或复用一个本地 Run。不会写入 Trail，也不会修改 GT、人工复核或默认 Run。继续？"
    )
  ) {
    return;
  }
  const button = createRun ? $("#syncTrailButton") : $("#checkTrailButton");
  button.disabled = true;
  button.textContent = createRun ? "创建中…" : "检查中…";
  try {
    const result = await api("/api/trail-model-sync", {
      method: "POST",
      body: JSON.stringify({
        mode,
        requested_by: state.session.username || "",
      }),
    });
    state.trailInspection = result;
    state.config = {
      ...(state.config || {}),
      trail_sync: result,
      default_model_run_id: state.config?.default_model_run_id || "",
    };
    renderConfig();
    if (createRun && result.run_id) {
      await loadRuns();
    }
    showToast(
      result.message || (createRun ? "Trail 只读快照处理完成。" : "Trail 字段检查完成。"),
      ["failed", "unavailable"].includes(result.status)
    );
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = createRun ? "创建 Run" : "检查字段";
    renderTrailSyncState();
  }
}

async function refreshAll({ resetSelection = false } = {}) {
  // Capture reviewer selections before any refresh work rebuilds a facet.
  // Their URL-backed values must survive both the Review and Analysis pages.
  const reviewerSelections = typeof reviewerFilterSelections === "function"
    ? reviewerFilterSelections()
    : undefined;
  await loadConfig();
  // “No overlay Run” is an intentional filter state.  Re-selecting the team
  // default here changes reviewer facets and used to make an active reviewer
  // filter appear to disappear after a top-bar refresh.
  await loadRuns({ preserveEmpty: !state.selectedRunId });
  await Promise.all([
    loadStatus(),
    loadOverview(),
    loadCases({ keepSelection: !resetSelection }),
    loadClusters(),
    loadReviewers(reviewerSelections),
    loadWorkAssignees(),
  ]);
  if (state.activePage === "trail-update" && typeof loadTrailAttributePreview === "function") {
    await loadTrailAttributePreview(true);
  }
}

async function reloadReviewGallery({
  includeOverview = true,
  historyMode = "push",
} = {}) {
  const reloadSeq = ++state.reviewReloadSeq;
  state.casePage = 1;
  state.galleryScrollY = 0;
  clearPendingReviewImages();
  const requests = [
    loadCases({ keepSelection: false, page: 1 }),
    loadClusters(),
    loadWorkAssignees(),
  ];
  if (includeOverview) requests.push(loadOverview());
  await Promise.all(requests);
  if (reloadSeq !== state.reviewReloadSeq) return;
  showPage("review", { historyMode, issue: "" });
}

async function resetReviewFilters() {
  state.reviewIssueIds = [];
  state.clusterKey = "";
  state.casePage = 1;
  if ($("#searchInput")) $("#searchInput").value = "";
  if (typeof updateIssueQueryButton === "function") updateIssueQueryButton();
  if ($("#issueQueryInput")) $("#issueQueryInput").value = "";
  setMultiFilterValues($("#gtFilter"), []);
  setMultiFilterValues($("#annotationFilter"), []);
  setMultiFilterValues($("#reviewerFilter"), []);
  // The URL is intentionally the durable reviewer-filter source while a
  // custom multi-select is rebuilt. Clear it synchronously for an explicit
  // reset so the fallback cannot revive a deliberately removed reviewer.
  persistReviewerFilterRoute?.("review", []);
  setMultiFilterValues($("#reviewStatusFilter"), []);
  setMultiFilterValues($("#reviewExclusionFilter"), []);
  setMultiFilterValues($("#workAssigneeFilter"), []);
  // The task-owner filter also falls back to its URL value while its custom
  // facet is being rebuilt. Remove that durable value for an explicit reset.
  persistWorkAssigneeFilterRoute?.([]);
  if ($("#modelRunFilter")) $("#modelRunFilter").value = "";
  state.selectedRunId = "";
  state.reviewComparisonStatus = "all";
  state.failureOnly = false;
  setReviewComparisonStatus("all", { hasRun: false });
  renderAnalysisRunFilter();
  renderActiveRun();
  renderRunManager();
  await reloadReviewGallery({ includeOverview: true, historyMode: "replace" });
  showToast("筛选已重置。");
}
