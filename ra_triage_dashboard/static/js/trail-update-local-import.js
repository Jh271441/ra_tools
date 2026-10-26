/* Explicit Trail → local adoption. Preview never saves or sends notifications. */
const trailLocalImport = { epoch: 0, busy: false, preview: null, context: null, scope: "", actor: "",
  scanId:0, scanning:false, loading:false, pollTimer:null, candidates:[], selected:new Set(), scanned:0, total:0,
  scanError:"", scanDone:false, checkedAt:null, snapshotTotal:0, membershipChanged:false };
function trailLocalImportIds() {
  return $("#trailLocalImportManual")?.open ? parseIssueIdsInput($("#trailLocalImportInput")?.value || "")
    : {ids:[...trailLocalImport.selected],invalid:[]};
}
function renderTrailLocalImportCandidates() {
  const target = $("#trailLocalImportCandidates");
  if (!target) return;
  const scan = trailLocalImport;
  target.hidden = Boolean(scan.preview);
  if (typeof $("#trailLocalImportSelectAll")?.closest === "function") $("#trailLocalImportSelectAll").closest("label").hidden = Boolean(scan.preview);
  $("#trailLocalImportScan").disabled = scan.loading || scan.scanning || scan.busy;
  const status = [];
  if (scan.checkedAt) status.push(uiText(`上次扫描 ${formatTime(scan.checkedAt)} · ${scan.snapshotTotal} 条`, `Last scanned ${formatTime(scan.checkedAt)} · ${scan.snapshotTotal} Issues`));
  if (scan.scanning) status.push(uiText(`后台扫描 ${scan.scanned}/${scan.total || "…"} · 关闭窗口后继续`, `Background scan ${scan.scanned}/${scan.total || "…"} · continues after closing`));
  else if (scan.loading && !scan.checkedAt) status.push(uiText("正在读取已保存结果…", "Loading saved results…"));
  if (scan.scanError) status.push(uiText(`扫描未完成：${scan.scanError}。${scan.checkedAt ? "保留上次完整结果" : "当前仅为部分结果"}。`, `Scan incomplete: ${scan.scanError}. ${scan.checkedAt ? "Previous complete results retained" : "Results are partial"}.`));
  if (scan.membershipChanged) status.push(uiText("数据集成员已变化，请刷新差异", "Dataset membership changed; refresh differences"));
  if (scan.scanDone) status.push(uiText(`${scan.candidates.length} 条差异 · 已选 ${scan.selected.size} 条`, `${scan.candidates.length} differences · ${scan.selected.size} selected`));
  $("#trailLocalImportScanStatus").textContent = status.join(" · ");
  const eligible = scan.candidates.filter(item=>item.can_import);
  const all = $("#trailLocalImportSelectAll");
  all.disabled = scan.busy || !eligible.length;
  all.checked = eligible.length > 0 && eligible.slice(0,200).every(item=>scan.selected.has(item.issue_id));
  all.indeterminate = scan.selected.size > 0 && !all.checked;
  target.innerHTML = scan.candidates.map(item=>`<label class="trail-import-candidate"><input type="checkbox" data-trail-import-issue="${escapeHtml(item.issue_id)}" ${scan.selected.has(item.issue_id) ? "checked" : ""} ${!item.can_import || scan.busy ? "disabled" : ""}>
    <span><strong>${escapeHtml(item.issue_id)}</strong><small>${escapeHtml(item.local_excluded === false ? uiText("本地未排除", "Not excluded locally") : uiText("本地无排除结论", "No local exclusion outcome"))}</small>
    <span class="trail-import-candidate-reason">${escapeHtml(typeof item.remote_reason === "string" && item.remote_reason || uiText("Trail 未填写理由", "No reason in Trail"))}</span>
    ${item.blocked_reason ? `<small class="is-error">${escapeHtml(item.blocked_reason)}</small>` : ""}</span></label>`).join("") || (scan.scanDone ? `<p>${uiText("未发现此类差异。", "No matching differences found.")}</p>` : "");
}
async function scanTrailLocalImport(refresh = false) {
  if (trailLocalImport.busy) return;
  clearTimeout(trailLocalImport.pollTimer);
  const epoch = trailLocalImport.epoch, scanId = ++trailLocalImport.scanId;
  const scope = trailLocalImport.scope;
  trailLocalImport.loading = true;
  if (refresh) Object.assign(trailLocalImport,{selected:new Set(),preview:null});
  refreshTrailLocalImportLanguage();
  try {
    const result = await api("/api/trail-attribute-update/local-import-candidates",{method:"POST",body:JSON.stringify({baselines:scope,refresh:refresh === true})});
    if (scanId !== trailLocalImport.scanId || !trailLocalImportCurrent(epoch) || !$("#trailLocalImportDialog").open) return;
    if (!Array.isArray(result.items) || result.direction !== "trail_to_local" || !["running","ready","failed","interrupted"].includes(result.status)) throw new Error(uiText("查询响应无效", "Invalid scan response"));
    const eligible = new Set(result.items.filter(item=>item.can_import).map(item=>item.issue_id));
    Object.assign(trailLocalImport,{candidates:result.items,
      selected:new Set([...trailLocalImport.selected].filter(id=>eligible.has(id))),
      scanned:result.scanned,total:result.total,scanning:result.status === "running",
      scanDone:Boolean(result.snapshot_available),checkedAt:result.checked_at,
      snapshotTotal:result.snapshot_total,membershipChanged:result.membership_changed,scanError:result.error || ""});
    if (trailLocalImport.scanning) trailLocalImport.pollTimer = setTimeout(() => {
      if (scanId === trailLocalImport.scanId && trailLocalImportCurrent(epoch) && $("#trailLocalImportDialog").open) scanTrailLocalImport();
    }, 1500);
  } catch (error) {
    if (scanId === trailLocalImport.scanId && trailLocalImportCurrent(epoch)) {
      trailLocalImport.scanError = error.message;
      trailLocalImport.scanning = false;
    }
  } finally {
    if (scanId === trailLocalImport.scanId) {trailLocalImport.loading=false;refreshTrailLocalImportLanguage();}
  }
}
function trailLocalImportCurrent(epoch) {
  return epoch === trailLocalImport.epoch && isPageContextCurrent(trailLocalImport.context)
    && selectedBaselineQueryValue() === trailLocalImport.scope
    && String(state.session?.username || "") === trailLocalImport.actor && trailNonExclusionAllowed();
}
function refreshTrailLocalImportLanguage() {
  const button = $("#trailLocalImportOpen");
  if (button) {
    button.textContent = uiText("从 Trail 导入", "Import from Trail");
    button.disabled = !trailNonExclusionAllowed() || trailLocalImport.busy || Boolean(state.trailUpdate?.selectionBusy);
  }
  renderTrailLocalImportCandidates();
  const parsed = trailLocalImportIds();
  $("#trailLocalImportPreview")?.toggleAttribute("disabled", trailLocalImport.busy || trailLocalImport.loading || trailLocalImport.scanning || !parsed.ids.length || parsed.ids.length > 200 || Boolean(parsed.invalid.length));
  $("#trailLocalImportInput")?.toggleAttribute("disabled", trailLocalImport.busy);
  const confirm = $("#trailLocalImportConfirm");
  if (confirm) {
    confirm.hidden = !trailLocalImport.preview;
    confirm.disabled = trailLocalImport.busy;
  }
  const target = $("#trailLocalImportDiff");
  if (target) {
    target.hidden = !trailLocalImport.preview;
    target.innerHTML = (trailLocalImport.preview?.items || []).map(item => `<article class="trail-selected-confirm">
      <strong>${escapeHtml(item.issue_id)}</strong><p>${escapeHtml(item.before.is_excluded === true ? uiText("我的标注：排除 → 排除", "My annotation: excluded → excluded") : item.before.is_excluded === false ? uiText("我的标注：不排除 → 排除", "My annotation: not excluded → excluded") : uiText("我的标注：无记录 → 排除", "My annotation: no record → excluded"))}</p>
      <div class="trail-reason-comparison"><section><strong>${uiText("本地原理由", "Previous local reason")}</strong><p>${escapeHtml(item.before.rationale || uiText("未填写", "Empty"))}</p></section>
      <section><strong>${uiText("导入后理由", "Reason after import")}</strong><p>${escapeHtml(item.after.rationale || uiText("未填写", "Empty"))}</p></section></div>
      <small>${escapeHtml(item.unchanged ? uiText("内容一致，无需追加", "Already matches; no revision needed") : item.expected_output ? uiText("保留我的分类、Tags 和图片", "Preserve my classification, tags and images") : uiText("没有我的分类记录；仅记录排除，分类仍待标注", "No personal classification; only exclusion is recorded, classification remains pending"))}</small></article>`).join("");
  }
}
function openTrailLocalImport() {
  if (!trailNonExclusionAllowed() || trailLocalImport.busy || state.trailUpdate.selectionBusy) return;
  trailLocalImport.epoch++;
  clearTimeout(trailLocalImport.pollTimer);
  Object.assign(trailLocalImport, {preview:null,context:capturePageContext(),scope:selectedBaselineQueryValue(),actor:String(state.session?.username || ""),
    candidates:[],selected:new Set(),scanned:0,total:0,scanError:"",scanDone:false,checkedAt:null,snapshotTotal:0,membershipChanged:false,scanning:false});
  $("#trailLocalImportFeedback").textContent = "";
  refreshTrailLocalImportLanguage();
  $("#trailLocalImportDialog").showModal();
  scanTrailLocalImport();
}
async function runTrailLocalImport(commit = false) {
  const epoch = trailLocalImport.epoch;
  const feedback = $("#trailLocalImportFeedback");
  if (trailLocalImport.busy || trailLocalImport.loading || trailLocalImport.scanning || state.trailUpdate.selectionBusy) return;
  if (!trailLocalImportCurrent(epoch)) {
    feedback.textContent = uiText("页面、数据集或用户已变化，请关闭后重新打开", "Page, dataset or user changed; close and reopen"); return;
  }
  const parsed = trailLocalImportIds();
  if (parsed.invalid.length || !parsed.ids.length || parsed.ids.length > 200 || (commit && !trailLocalImport.preview)) return;
  const body = commit ? {preview_id:trailLocalImport.preview.preview_id,confirm:true} : {issue_ids:parsed.ids,baselines:trailLocalImport.scope};
  trailLocalImport.busy = true; state.trailUpdate.selectionBusy = true;
  feedback.textContent = uiText("正在处理…", "Working…"); feedback.classList.remove("is-error");
  refreshTrailLocalImportLanguage(); syncTrailAttributeActions();
  try {
    const result = await api(`/api/trail-attribute-update/local-import-${commit ? "commit" : "preview"}`, {method:"POST",body:JSON.stringify(body)});
    if (!trailLocalImportCurrent(epoch) || !$("#trailLocalImportDialog").open) return;
    if (commit) {
      if (!result.ok) throw new Error(uiText("导入未完成，请核查", "Import incomplete; inspect the result"));
      trailLocalImport.preview = null;
      const importedIds = new Set((result.items || []).map(item=>item.issue_id));
      trailLocalImport.candidates = trailLocalImport.candidates.filter(item=>!importedIds.has(item.issue_id));
      trailLocalImport.selected.clear();
      feedback.textContent = uiText(`已导入 ${result.imported_count} 条，可在 Issue 标注记录中查看。`, `${result.imported_count} imported; view them in Issue annotation records.`);
      try { await loadTrailAttributePreview(true); }
      catch (_) {
        if (trailLocalImportCurrent(epoch) && $("#trailLocalImportDialog").open) feedback.textContent = uiText("已保存到本地；列表刷新失败，请手动刷新，无需重复导入。", "Saved locally; list refresh failed. Refresh manually; no need to import again.");
      }
    } else {
      if (!result.preview_id || result.direction !== "trail_to_local" || !Array.isArray(result.items)) throw new Error(uiText("预览无效", "Invalid preview"));
      trailLocalImport.preview = result;
      feedback.textContent = uiText("请核对以下改动，确认后仅保存到本地。", "Review below; confirmation saves locally only.");
    }
  } catch (error) {
    if (epoch === trailLocalImport.epoch && $("#trailLocalImportDialog").open) {
      feedback.textContent = error.message; feedback.classList.add("is-error");
    }
  } finally {
    trailLocalImport.busy = false; state.trailUpdate.selectionBusy = false;
    refreshTrailLocalImportLanguage(); syncTrailAttributeActions();
  }
}
function bindTrailLocalImportEvents() {
  const anchor = $("#trailNonExclusionOpen");
  if (anchor && !$("#trailLocalImportOpen")) {
    const button = document.createElement("button");
    button.id = "trailLocalImportOpen"; button.type = "button"; button.className = "button button-quiet";
    button.setAttribute("aria-haspopup", "dialog"); anchor.before(button);
    button.addEventListener("click", openTrailLocalImport);
  }
  $("#trailLocalImportInput")?.addEventListener("input", () => {trailLocalImport.preview=null;refreshTrailLocalImportLanguage();});
  $("#trailLocalImportManual")?.addEventListener("toggle", () => {trailLocalImport.preview=null;refreshTrailLocalImportLanguage();});
  $("#trailLocalImportScan")?.addEventListener("click", () => scanTrailLocalImport(true));
  $("#trailLocalImportCandidates")?.addEventListener("change", event => {
    const id = event.target.dataset.trailImportIssue;
    if (!id || trailLocalImport.busy || !trailLocalImport.candidates.some(item=>item.issue_id === id && item.can_import)) return;
    if (event.target.checked && trailLocalImport.selected.size < 200) trailLocalImport.selected.add(id);
    else trailLocalImport.selected.delete(id);
    trailLocalImport.preview=null; refreshTrailLocalImportLanguage();
  });
  $("#trailLocalImportSelectAll")?.addEventListener("change", event => {
    if (trailLocalImport.busy) return;
    trailLocalImport.selected = new Set(event.target.checked ? trailLocalImport.candidates.filter(item=>item.can_import).slice(0,200).map(item=>item.issue_id) : []);
    trailLocalImport.preview=null; refreshTrailLocalImportLanguage();
  });
  $("#trailLocalImportPreview")?.addEventListener("click", () => runTrailLocalImport(false));
  $("#trailLocalImportConfirm")?.addEventListener("click", () => runTrailLocalImport(true));
  $("#trailLocalImportDialog")?.addEventListener("close", () => {
    clearTimeout(trailLocalImport.pollTimer); // Stop UI polling, never the server job.
    trailLocalImport.epoch++;trailLocalImport.scanId++;trailLocalImport.scanning=false;trailLocalImport.loading=false;trailLocalImport.preview=null;
  });
  refreshTrailLocalImportLanguage();
}
