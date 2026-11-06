/* Canonical Manual labels -> explicit RD publication or TE correction. */
const rdResults = { mode: 'rd', excelFile: null, data: null, remote: {}, selected: new Set(), allSelected: false, excluded: new Set(), epoch: 0, loading: false,
  busy: false, busyAction: '', committing: false, error: '', preview: null, operations: [], overwrite: false, baselines: '', filterDraft: null, pageJumpDraft: null,
  previewOpen: false, previewInfoOpen: false, teRefresh: null, teTracking: null, listScroll: 0, previewPage: 1, previewPageSize: DEFAULT_CASE_PAGE_SIZE, previewJumpDraft: null, pendingPreview: null, tracking: null, trackingError: '',
  filters: { q: '', status: 'all', page: 1, page_size: DEFAULT_CASE_PAGE_SIZE } };
const rdText = (zh, en) => uiText(zh, en);
const RD_UPLOAD_ENDPOINT = 'https://voyager.intra.xiaojukeji.com/paladin/issue/pool/multi_update/';
const RD_UPLOAD_FIELD = 'ra_rd_review_result';
const rdIsTE = () => rdResults.mode === 'te-correction';
const rdUploadField = () => rdIsTE() ? 'ra_review_result_new' : RD_UPLOAD_FIELD;
const rdObservationTime = value => new Date(value).toLocaleString(state.uiLanguage === 'en' ? 'en-GB' : 'zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
const rdValidVersion = () => state.selectedBaselineIds.length === 1 && /^version-20\d{6}$/.test(state.selectedBaselineIds[0]);
const rdPreviewStorageKey = () => `rd-results-preview:${location.pathname}:${rdResults.mode}${rdIsTE() ? ":v2" : ""}`;
function rdModeTabs() {
  return `<div class="rd-mode-tabs" role="tablist" aria-label="${rdText('标注上传类型', 'Publication type')}">${[['rd','RD 上传','RD upload','RD 标注上传','RD label upload'],['te-correction','TE 修正','TE correction','TE 标注修正','TE label correction']].map(([mode,zh,en,titleZh,titleEn]) => `<button id="rdMode-${mode}" type="button" role="tab" class="button button-secondary rd-mode-tab" data-rd-mode="${mode}" aria-label="${rdText(titleZh,titleEn)}" aria-selected="${rdResults.mode === mode}" aria-controls="rdModePanel" tabindex="${rdResults.mode === mode ? '0' : '-1'}" ${rdResults.busy || rdResults.committing ? 'disabled' : ''}><span class="rd-mode-label-full">${rdText(titleZh,titleEn)}</span><span class="rd-mode-label-compact" aria-hidden="true">${rdText(zh,en)}</span></button>`).join('')}</div>`;
}
function rdOverviewInfoMarkup() {
  return `<dl class="rd-upload-target"><div><dt>${rdText('上传接口','Upload endpoint')}</dt><dd><span class="rd-http-method">POST</span><code>${RD_UPLOAD_ENDPOINT}</code></dd></div><div><dt>${rdText('目标字段','Target field')}</dt><dd><code>${rdUploadField()}</code></dd></div></dl>`;
}
const rdTERefreshing = () => rdIsTE() && rdResults.teRefresh?.status === 'running';
const rdHasExcel = () => rdIsTE() && Boolean(rdResults.excelFile);
function rdSizeSearch(input = $('#rdSearch')) {
  if (input) { input.style.height = 'auto'; input.style.height = `${Math.min(128,input.scrollHeight)}px`; }
}
function rdTERefreshControls() {
  if (!rdIsTE()) return '';
  const refresh = rdResults.teRefresh, running = rdTERefreshing();
  const checked = refresh?.checked_at || rdResults.data?.snapshot?.last_success_at;
  const title = rdText('从 Trail 读取当前版本全部 TE 标签', 'Read all current TE labels for this version from Trail')
    + (checked ? rdText('；上次更新（CST）：', '; last updated (CST): ') + rdObservationTime(checked) : '');
  const disabled = rdResults.busy || rdResults.loading || running || !rdValidVersion();
  return `<div class="run-manager-actions">${rdButton('refresh-te', rdText('刷新 TE 标签','Refresh TE labels'), disabled, 'quiet', title)}${state.session.is_admin ? rdButton('import-excel', rdText('导入 XLSX','Import XLSX'), disabled, 'quiet', rdText('列：Issue ID、期望输出（正确触发 / 误触发 / 无需协助）','Columns: Issue ID, expected_output (正确触发 / 误触发 / 无需协助)')) + '<input id="rdExcelFile" class="hidden" type="file" accept=".xlsx" />' : ''}${running ? `<span class="rd-description" role="status" aria-label="${rdText('TE 刷新进度','TE refresh progress')}">${refresh.scanned || 0} / ${refresh.total || 0}</span>` : ''}</div>`;
}
function rdPreviewScopeKey() {
  return JSON.stringify([rdResults.mode, state.selectedBaselineIds, rdResults.filters]);
}
function rdSavePreview() {
  if (!rdResults.previewOpen || !rdResults.preview) return;
  // Keep only the operation reference and presentation state. Always read the
  // receipt again after refresh; cached label data cannot authorize a write.
  const saved = { scope: rdPreviewScopeKey(), id: rdResults.preview.id,
    outcome: rdResults.committing || rdResults.preview.state !== 'preview',
    infoOpen: rdResults.previewInfoOpen, page: rdResults.previewPage, pageSize: rdResults.previewPageSize };
  try { sessionStorage.setItem(rdPreviewStorageKey(), JSON.stringify(saved)); } catch (_) { /* Storage may be unavailable. */ }
}
function rdForgetPreview() {
  try { sessionStorage.removeItem(rdPreviewStorageKey()); } catch (_) { /* Storage may be unavailable. */ }
}
function rdSavedPreview() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(rdPreviewStorageKey()) || 'null');
    if (saved && saved.scope === rdPreviewScopeKey() && /^[0-9a-f]{32}$/.test(saved.id)
        && typeof saved.outcome === 'boolean' && state.session.is_admin) return saved;
    rdForgetPreview();
  } catch (_) { rdForgetPreview(); }
  return null;
}
function rdStatus(value) {
  const names = { resolved: ['已完成', 'Completed'], pending: ['待上传', 'Ready to upload'],
    conflict: ['结果不同', 'Different result'], same: ['已一致', 'Already matches'], blocked: ['不可上传', 'Blocked'],
    unchecked: ['未核对', 'Not checked'], preparing: ['正在生成预览', 'Preparing preview'], preview: ['预览待确认', 'Preview ready'], preview_failed: ['预览失败', 'Preview failed'], complete: ['已核验完成', 'Verified complete'],
    needs_recheck: ['需重新核对', 'Recheck required'], running: ['正在上传并核验', 'Uploading and verifying'],
    waiting: ['等待处理', 'Waiting'], checking: ['写前核对中', 'Checking before upload'], uploading: ['上传中', 'Uploading'], readback: ['读回核验中', 'Verifying readback'],
    verified: ['读回一致', 'Readback verified'], unverified: ['未确认', 'Unverified'], intent: ['结果待核对', 'Outcome needs checking'],
    not_attempted: ['未执行', 'Not attempted'],
    te_empty: ['TE 为空', 'TE empty'], rd_mismatch: ['旧预览，请重新预览', 'Old preview; preview again'],
    candidate: ['待修正', 'Candidate'],
    label_pending: ['待标注', 'Label pending'], label_conflict: ['需复核', 'Needs review'],
    te_unknown: ['暂无观测', 'No observation'],
    outcome_unknown: ['结果暂不可查', 'Outcome unavailable'] };
  return names[value] ? rdText(...names[value]) : value;
}
function rdReason(value) {
  const names = {
    preview_check_failed: ['预览核对失败，未执行上传。可重新预览。', 'Preview check failed; nothing was uploaded. Create a new preview.'],
    preview_interrupted: ['预览任务已中断，未执行上传。请重新预览。', 'Preview interrupted; nothing was uploaded. Create a new preview.'],
    preflight_failed: ['提交前核对未通过，未执行写入。请刷新后重新预览。', 'Preflight check failed; nothing was written. Refresh and preview again.'],
    source_changed: ['标注或 Trail 值已变化，未执行写入。', 'Labels or Trail changed; nothing was written.'],
    check_failed: ['写入前核对失败，未执行写入。', 'Check before writing failed; nothing was written.'],
    batch_stopped: ['批次出现异常，已停止派发后续上传。', 'A batch failed verification; no further uploads were dispatched.'],
    protected_changed: ['读回发现其他字段变化，已停止上传，需人工核对。', 'Readback found changes to other fields. Upload stopped; inspect manually.'],
    value_mismatch: ['读回值与上传值不一致，已停止上传。', 'Readback differs from the requested value. Upload stopped.'],
    readback_failed: ['写入后读回失败，结果未知；请重新核对 Trail。', 'Readback failed after writing; outcome unknown. Check Trail again.'],
    interrupted: ['执行中断，可能已写入；请重新核对 Trail。', 'Execution was interrupted; a write may have occurred. Check Trail again.'],
    receipt_unavailable: ['无法取得操作记录；请刷新本次结果，勿重复上传。', 'Operation receipt unavailable. Refresh this outcome before uploading again.'],
    receipt_pending: ['尚无执行结果，请稍后刷新本次结果；请求可能仍在处理中。', 'No execution outcome yet. Refresh this outcome shortly; the request may still be processing.'],
    audit_failed: ['更新记录保存失败，未上传。', 'Could not save update history; nothing uploaded.'],
    response_recovered: ['提交响应未收到，已找回操作记录；请以逐条核验状态为准。', 'The submit response was lost; the operation receipt was recovered. Use the per-item verification states.'],
  };
  return names[value] ? rdText(...names[value]) : '';
}
function rdLabel(value) {
  return ({ '成功': rdText('正确触发（Trail：成功）', 'Correct trigger (Trail: 成功)'),
    '正确触发': rdText('正确触发', 'Correct trigger'), '误触发': rdText('误触发', 'False trigger'),
    '无需协助': rdText('无需协助', 'No assistance needed') })[value] || value || '—';
}
function rdButton(action, text, disabled = false, variant = 'secondary', title = '') {
  const style = { primary: 'button-primary', quiet: 'button-quiet', text: 'text-button', secondary: 'button-secondary' }[variant];
  return `<button type="button" class="button ${style}" data-rd-action="${action}" ${title ? `title="${escapeHtml(title)}"` : ''} ${disabled ? 'disabled' : ''}>${escapeHtml(text)}</button>`;
}
function rdStatusBadge(status) {
  const tone = ['same', 'complete', 'verified'].includes(status) ? 'ok'
    : ['conflict', 'needs_recheck', 'unverified'].includes(status) ? 'warn'
    : status === 'pending' ? 'ready' : 'neutral';
  return `<span class="run-source-badge rd-status rd-status-${tone}">${escapeHtml(rdStatus(status))}</span>`;
}
function rdMetricsMarkup(data) {
  const metrics = rdIsTE() ? [
    ['all','total','范围内 Issues','Issues in scope','M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z'],
    ['resolved','resolved','待修正候选','Correction candidates','m5 12 4 4L19 6'],
    ['same','same','已一致','Already matches','m5 12 4 4L19 6'],
    ['blocked','blocked','暂不可修正','Unavailable for correction','m12 3 10 18H2L12 3zm0 6v5m0 3v1'],
  ] : [
    ['all', 'total', '范围内 Issues', 'Issues in scope', 'M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z'],
    ['resolved', 'resolved', '已完成', 'Completed', 'm5 12 4 4L19 6'],
    ['pending', 'pending', '待标注', 'Pending labels', 'M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0'],
    ['conflict', 'conflict', '需复核', 'Needs review', 'm12 3 10 18H2L12 3zm0 6v5m0 3v1'],
  ];
  return `<div class="run-source-tabs rd-metrics" aria-label="${rdText('标注概览与筛选', 'Label overview and filters')}">${metrics.map(([filter,key,zh,en,path]) => `<button class="run-source-tab rd-metric ${rdResults.filters.status === filter ? 'active' : ''}" type="button" data-rd-filter="${filter}" aria-pressed="${rdResults.filters.status === filter}" ${rdResults.loading || rdResults.busy ? 'disabled' : ''}><span class="run-source-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="${path}"/></svg></span><span><strong>${rdText(zh,en)}</strong></span><em>${data ? data.counts[key] : '—'}</em></button>`).join('')}</div>`;
}
function rdSelectable(row) {
  return row.group === 'resolved';
}
function rdScopeCount() {
  return ['all', 'resolved'].includes(rdResults.filters.status) ? (rdResults.data?.counts.resolved || 0) : 0;
}
function rdSelectedCount() { return rdResults.allSelected ? Math.max(0, rdScopeCount() - rdResults.excluded.size) : rdResults.selected.size; }
function rdIsSelected(row) { return rdSelectable(row) && (rdResults.allSelected ? !rdResults.excluded.has(row.issue_id) : rdResults.selected.has(row.issue_id)); }
function rdClearSelection() { rdResults.selected.clear(); rdResults.excluded.clear(); rdResults.allSelected = false; }
function rdPreviewProgress() {
  const progress = rdResults.pendingPreview?.progress;
  if (progress?.stage === 'trail') return rdText(`正在核对 Trail ${progress.checked} / ${progress.total}，完成后展示预览…`, `Checking Trail ${progress.checked} / ${progress.total}; preview will open when ready…`);
  return rdText('正在汇总标注并核对 Trail，尚未上传…', 'Collecting labels and checking Trail; nothing uploaded yet…');
}
function renderRdResults() {
  if (state.activePage !== 'rd-results') return;
  if (rdResults.previewOpen && rdResults.preview) return rdRenderPreview();
  const root = $('#rdResultsPage'), d = rdResults.data, f = rdResults.filters;
  root.classList.toggle('is-te-correction', rdIsTE());
  const draft = rdResults.filterDraft || f;
  const focus = document.activeElement?.id, caret = document.activeElement?.selectionStart;
  const focusedMode = document.activeElement?.dataset.rdMode;
  const focusedIssue = document.activeElement?.dataset.rdId;
  const selectedCount = rdSelectedCount();
  const selectionDisabled = rdResults.busy || rdResults.loading || rdTERefreshing();
  const fileActive = rdHasExcel();
  const refreshFailed = rdIsTE() && ['failed','interrupted'].includes(rdResults.teRefresh?.status);
  root.innerHTML = `<section class="page-card runs-source-card rd-overview" aria-label="${rdText('标注上传概览','Label publication overview')}"><div class="runs-source-heading rd-mode-header"><div>${rdModeTabs()}</div><div class="run-manager-actions">${rdButton('refresh', rdText('刷新', 'Refresh'), rdResults.loading || rdResults.busy, 'quiet')}</div></div>
    <div id="rdModePanel" class="rd-mode-panel" role="tabpanel" aria-labelledby="rdMode-${rdResults.mode}">${rdMetricsMarkup(d)}
    ${rdOverviewInfoMarkup()}</div></section>
    <section class="page-card runs-page-card rd-workspace"><div class="rd-detail-toolbar"><div class="rd-detail-heading"><h3>${rdText('标注明细', 'Label details')}</h3>${rdTERefreshControls()}</div>
    <form id="rdFilters" class="run-filter-bar rd-filters"><textarea id="rdSearch" name="q" rows="1" maxlength="8000" aria-label="${rdText('Issue 搜索，可多个','Find Issues; multiple IDs supported')}" placeholder="${rdText('粘贴 Issue ID，可多个', 'Paste Issue IDs')}" title="${rdText('支持从 Excel 粘贴；换行、空格、逗号分隔，最多 500 个','Paste from Excel; separate up to 500 IDs with newlines, spaces or commas')}" autocomplete="off">${escapeHtml(draft.q)}</textarea>
    <select id="rdState" name="status" aria-label="${rdText('标注状态','Label status')}">${(rdIsTE() ? [['all','全部状态','All statuses'],['resolved','待修正候选','Correction candidates'],['same','已一致','Already matches'],['blocked','暂不可修正','Unavailable for correction']] : [['all','全部状态','All statuses'],['resolved','已完成','Completed'],['pending','待标注','Pending labels'],['conflict','冲突 / 失效','Conflict / stale']]).map(([v,zh,en]) => `<option value="${v}" ${draft.status === v ? 'selected' : ''}>${rdText(zh,en)}</option>`).join('')}</select><button class="button button-secondary" type="submit" ${rdResults.busy || rdResults.loading ? 'disabled' : ''}>${rdText('筛选','Apply')}</button></form></div>
    ${rdResults.error || rdResults.loading || (rdResults.busy && rdResults.busyAction !== 'refresh-te') || refreshFailed ? `<p class="rd-notice ${rdResults.error || refreshFailed ? 'is-error' : ''}" role="status">${escapeHtml(rdResults.error || (rdResults.loading ? rdText('正在加载标注…','Loading labels…') : refreshFailed ? rdText('TE 刷新失败，保留上次结果。请重试。','TE refresh failed. Previous labels retained; retry.') : rdResults.busyAction?.includes('preview') ? rdPreviewProgress() : rdText('正在处理，请稍候…','Processing, please wait…')))}${rdResults.pendingPreview && !rdResults.busy ? `<button type="button" class="button button-quiet" data-rd-operation="${rdResults.pendingPreview.id}">${rdText('继续查看预览','Resume preview')}</button>` : ''}</p>` : ''}
    <div class="rd-selection-bar ${selectedCount ? 'has-selection' : ''}"><div class="rd-selection-tools"><div class="run-manager-actions"><select id="rdSelectionAction" aria-label="${rdText('选中操作','Selection actions')}" ${selectionDisabled || fileActive ? 'disabled' : ''}><option value="" selected disabled>${rdText('选中操作','Selection actions')}</option><option value="page" ${!d?.items.some(rdSelectable) ? 'disabled' : ''}>${rdText('选择本页','Select this page')}</option><option value="all" ${!rdScopeCount() ? 'disabled' : ''}>${rdText(`选择全部 ${rdScopeCount()} 条`, `Select all ${rdScopeCount()} labels`)}</option><option value="clear" ${!selectedCount ? 'disabled' : ''}>${rdText('清空选择','Clear selection')}</option></select><span class="rd-selection-count" role="status">${fileActive ? rdText('XLSX 期望输出：','XLSX targets: ') + escapeHtml(rdResults.excelFile.name) + rdButton('clear-excel',rdText('清除文件','Clear file'),selectionDisabled,'quiet') : selectedCount ? rdText('已选','Selected') + ` <strong>${selectedCount}</strong>` + (rdResults.allSelected ? rdText(' 条 · 跨全部页',' · across all pages') : rdText(' 条',' labels')) : rdText('请选择标注','Select labels to preview')}</span></div>
    ${state.session.is_admin && !rdIsTE() ? `<label class="rd-checkbox"><input class="ui-checkbox" id="rdOverwrite" type="checkbox" ${rdResults.overwrite ? 'checked' : ''} ${selectionDisabled ? 'disabled' : ''}>${rdText('覆盖不同的 RD 结果','Overwrite different RD results')}</label>` : ''}</div>
    <div class="run-manager-actions">${d && !d.write_enabled ? `<span class="rd-notice" title="${rdText('真实写入开关关闭，预览可用','Publishing is disabled; preview is available')}">${rdText('写入未启用','Publishing disabled')}</span>` : ''}${state.session.is_admin ? rdButton('preview',fileActive ? rdText('预览文件','Preview file') : rdText('预览上传','Preview upload'), (!fileActive && !selectedCount) || selectionDisabled, 'primary', rdText('自动核对选中标注，预览后确认上传','Automatically check selected labels, then preview and confirm upload')) : ''}</div></div>
    <div class="rd-table-wrap"><table class="rd-table"><thead><tr>${['', 'Issue', ...(rdIsTE() ? [rdText('当前 TE（观测）','Current TE (observed)')] : []), rdText(rdIsTE() ? 'RD 人工结论' : '人工结论',rdIsTE() ? 'RD human label' : 'Human label'), ...(rdIsTE() ? [rdText('修正状态','Correction status')] : []), rdText('标注人','Contributors')].map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${(d?.items || []).map(row => {
      const eligible = rdSelectable(row), selected = rdIsSelected(row);
      return `<tr class="${selected ? 'is-selected' : ''}"><td><label class="rd-checkbox"><input class="ui-checkbox" type="checkbox" data-rd-id="${escapeHtml(row.issue_id)}" aria-label="${escapeHtml(rdText('选择 ','Select ') + row.issue_id)}" ${selected ? 'checked' : ''} ${!eligible || selectionDisabled || fileActive ? 'disabled' : ''}></label></td><td><a class="rd-issue-link" href="${escapeHtml(pageUrl('labeling',{ issue: row.issue_id, baselines: state.selectedBaselineIds }))}">${escapeHtml(row.issue_id)}</a></td>${rdIsTE() ? `<td>${rdValueMarkup(row.te_current)}</td>` : ''}<td>${(rdIsTE() ? row.state === 'resolved' : row.group === 'resolved') ? labelBadge(row.label, '—', rdLabel(row.label)) : `<span class="muted">${rdText(['conflict','stale'].includes(row.state || row.group) ? '冲突 / 失效' : '待标注', ['conflict','stale'].includes(row.state || row.group) ? 'Conflict / stale' : 'Pending label')}</span>`}</td>${rdIsTE() ? `<td>${rdStatusBadge(row.correction_status)}</td>` : ''}<td>${escapeHtml(row.authors.join(', ') || '—')}</td></tr>`;
    }).join('')}</tbody></table></div>${!rdResults.loading && !d?.items.length ? `<div class="rd-empty"><strong>${rdResults.error ? rdText('暂时无法加载标注','Unable to load labels') : rdText('当前范围没有标注结果','No labels in this scope')}</strong><p>${rdText('可调整顶部数据集或筛选条件后重试。','Adjust the selected datasets or filters and try again.')}</p></div>` : ''}
    ${rdPaginationMarkup(d)}</section>
    ${state.session.is_admin ? `<section class="page-card job-history-card"><div class="runs-toolbar"><div><h3>${rdText('上传记录','Publication history')}</h3></div>${rdButton('history',rdText('查看最近记录','Show recent operations'), rdResults.busy)}</div><div class="job-history-list">${rdResults.operations.map(r=>`<div class="job-history-row"><div class="job-history-main"><strong>${escapeHtml(r.actor)}</strong><span class="muted">${escapeHtml(r.id.slice(0,12))}</span></div><div class="run-manager-actions">${rdStatusBadge(r.state)}<button type="button" class="button button-secondary" data-rd-operation="${r.id}">${rdText('查看详情','View details')}</button></div></div>`).join('')}</div></section>` : ''}`;
  enhanceDashboardSelects(root);
  root.onclick = rdClick;
  root.oninput = event => {
    if (event.target.id === 'rdSearch') {
      rdResults.filterDraft = { ...(rdResults.filterDraft || draft), q: event.target.value };
      rdSizeSearch(event.target);
    }
    if (event.target.id === 'rdPageJump') rdResults.pageJumpDraft = event.target.value;
  };
  root.onchange = (event) => {
    if (event.target.id === 'rdExcelFile') {
      const file = event.target.files?.[0];
      if (file) {
        rdForgetPreview(); rdClearSelection(); rdResults.pendingPreview = null; rdResults.error = '';
        rdResults.excelFile = file; renderRdResults();
        $('#rdResultsPage [data-rd-action="preview"]')?.focus();
      }
      return;
    }
    if (event.target.id === 'rdState') rdResults.filterDraft = { ...(rdResults.filterDraft || draft), status: event.target.value };
    if (event.target.dataset.rdId) {
      const id = event.target.dataset.rdId;
      if (rdResults.allSelected) event.target.checked ? rdResults.excluded.delete(id) : rdResults.excluded.add(id);
      else event.target.checked ? rdResults.selected.add(id) : rdResults.selected.delete(id);
      renderRdResults();
    }
    if (event.target.id === 'rdSelectionAction' && !selectionDisabled) {
      const action = event.target.value;
      rdClearSelection();
      if (action === 'page') d.items.filter(rdSelectable).forEach(row => rdResults.selected.add(row.issue_id));
      if (action === 'all') rdResults.allSelected = true;
      renderRdResults();
      $('#rdSelectionAction')?.closest('.ui-select')?.querySelector('.ui-select-trigger')?.focus();
    }
    if (event.target.id === 'rdOverwrite') { rdResults.overwrite = event.target.checked; renderRdResults(); }
    if (event.target.id === 'rdPageSize') {
      const size = Number(event.target.value);
      if (!rdResults.loading && !rdResults.busy && CASE_PAGE_SIZES.includes(size)) {
        rdResults.filters.page_size = size; rdResults.filters.page = 1; rdPersist(); loadRdResults();
      }
    }
  };
  root.onkeydown = event => {
    const tab = event.target.closest('.rd-mode-tabs [role="tab"]');
    if (tab && ['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
      event.preventDefault();
      const tabs = [...root.querySelectorAll('.rd-mode-tabs [role="tab"]:not(:disabled)')];
      if (!tabs.length) return;
      const index = tabs.indexOf(tab), next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1
        : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs.forEach((node,i) => { node.tabIndex = i === next ? 0 : -1; });
      tabs[next].focus(); return;
    }
    if (event.target.id === 'rdPageJump' && event.key === 'Enter' && !event.isComposing) { event.preventDefault(); rdJumpToPage(); }
    if (event.target.id === 'rdSearch' && event.key === 'Enter' && !event.shiftKey && !isImeComposing(event) && !reviewTouchTextEntry(event.target)) {
      event.preventDefault(); $('#rdFilters').requestSubmit();
    }
  };
  $('#rdFilters').onsubmit = event => {
    event.preventDefault();
    const raw = $('#rdSearch').value.trim();
    let q = raw;
    if (raw.split(/[\s,，、;；]+/).filter(Boolean).length > 1) {
      const parsed = parseIssueIdsInput(raw);
      if (parsed.invalid.length || parsed.ids.some(id => !/^cn\d+$/i.test(id)) || parsed.ids.length > 500) {
        rdResults.error = rdText('请输入最多 500 个有效 Issue ID。','Enter up to 500 valid Issue IDs.'); renderRdResults(); return;
      }
      q = [...new Set(parsed.ids.map(id => id.toLowerCase()))].join(',');
    }
    rdResults.filters = { ...f, q, status: $('#rdState').value, page: 1 }; rdPersist(); loadRdResults();
  };
  rdSizeSearch();
  if (focus === 'rdSearch') { $('#rdSearch').focus(); $('#rdSearch').setSelectionRange(caret, caret); }
  if (focus === 'rdOverwrite') $('#rdOverwrite')?.focus();
  if (focusedIssue) root.querySelector(`[data-rd-id="${CSS.escape(focusedIssue)}"]`)?.focus();
  if (focusedMode) {
    root.querySelectorAll('[data-rd-mode]').forEach(tab => { tab.tabIndex = tab.dataset.rdMode === focusedMode ? 0 : -1; });
    root.querySelector(`[data-rd-mode="${focusedMode}"]`)?.focus({ preventScroll: true });
  }
}
function rdPaginationMarkup(data, inDialog = false) {
  const disabled = !data || !data.total || rdResults.loading || rdResults.busy;
  const page = data?.page || 1, pages = data?.pages || 1;
  const prefix = inDialog ? 'rdPreview' : 'rd';
  const action = value => inDialog ? `preview-${value}` : value;
  const size = inDialog ? rdResults.previewPageSize : rdResults.filters.page_size;
  return `<nav class="case-pagination rd-pagination" aria-label="${rdText('标注明细分页','Annotation pagination')}">
    <span>${data ? `${data.total} ${rdText('条结果','results')}` : '—'}</span>
    <div class="case-pagination-main">${rdButton(action('previous'),rdText('上一页','Previous'), disabled || page <= 1, 'quiet')}<span>${data ? `${page} / ${pages}` : '— / —'}</span>${rdButton(action('next'),rdText('下一页','Next'), disabled || page >= pages, 'quiet')}
      <span class="page-jump-control"><label for="${prefix}PageJump">${rdText('跳至','Go to')}</label><input id="${prefix}PageJump" type="number" min="1" max="${pages}" step="1" inputmode="numeric" value="${escapeHtml((inDialog ? rdResults.previewJumpDraft : rdResults.pageJumpDraft) ?? String(page))}" ${disabled || pages <= 1 ? 'disabled' : ''}><span>${rdText('页','page')}</span>${rdButton(action('jump'),rdText('跳转','Go'), disabled || pages <= 1, 'quiet')}</span>
    </div><label class="case-page-size" for="${prefix}PageSize"><span>${rdText('每页','Per page')}</span><select id="${prefix}PageSize" ${disabled ? 'disabled' : ''}>${CASE_PAGE_SIZES.map(value=>`<option value="${value}" ${value === size ? 'selected' : ''}>${value}</option>`).join('')}</select><span>${rdText('条','items')}</span></label></nav>`;
}
function rdJumpToPage() {
  if (!rdResults.data || rdResults.busy || rdResults.loading) return;
  const input = $('#rdPageJump'), value = Number(input.value);
  if (!input.value.trim() || !Number.isSafeInteger(value)) { input.value = String(rdResults.data.page); rdResults.pageJumpDraft = null; return; }
  const page = Math.max(1, Math.min(rdResults.data.pages, value));
  input.value = String(page); rdResults.pageJumpDraft = null;
  if (page === rdResults.data.page) return;
  rdResults.filters.page = page; rdPersist(); loadRdResults();
}
function rdPersist() {
  const url = new URL(pageUrl('rd-results', { baselines: state.selectedBaselineIds }), location.origin);
  if (rdIsTE()) url.searchParams.set('mode', rdResults.mode);
  Object.entries(rdResults.filters).forEach(([k,v]) => url.searchParams.set(k, v));
  history.replaceState(history.state, '', url);
}
async function loadRdResults() {
  if (rdResults.committing) return;
  if (rdResults.busyAction === 'refresh-te') { rdResults.busy = false; rdResults.busyAction = ''; }
  const epoch = ++rdResults.epoch, scope = state.selectedBaselineIds.join(',');
  if (scope !== rdResults.baselines) { rdResults.overwrite = false; rdResults.operations = []; rdResults.pendingPreview = null; }
  rdResults.previewOpen = false; rdResults.preview = null; rdClearSelection(); rdResults.remote = {}; rdResults.pageJumpDraft = null;
  rdResults.excelFile = null;
  rdResults.teRefresh = null;
  rdResults.data = null; rdResults.error = ''; rdResults.loading = true; rdResults.baselines = scope;
  const params = new URLSearchParams(location.search);
  const mode = params.get('mode') === 'te-correction' ? 'te-correction' : 'rd';
  if (mode !== rdResults.mode) { rdResults.overwrite = false; rdResults.operations = []; rdResults.pendingPreview = null; }
  rdResults.mode = mode;
  const requestedPage = Number(params.get('page')), requestedSize = Number(params.get('page_size'));
  const allowedStatuses = rdIsTE() ? ['all','resolved','same','blocked'] : ['all','resolved','pending','conflict'];
  rdResults.filters = { q: params.get('q') || '', status: allowedStatuses.includes(params.get('status')) ? params.get('status') : 'all',
    page: Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1,
    page_size: CASE_PAGE_SIZES.includes(requestedSize) ? requestedSize : DEFAULT_CASE_PAGE_SIZE };
  rdResults.filterDraft = { ...rdResults.filters };
  const savedPreview = rdSavedPreview();
  renderRdResults();
  if (rdIsTE() && !rdValidVersion()) {
    rdResults.loading = false;
    rdResults.error = rdText('TE 修正请选择一个版本数据集。', 'Select one version dataset for TE correction.');
    rdPersist(); renderRdResults(); return;
  }
  try {
    const data = await api(`/api/rd-results?${new URLSearchParams({ baselines: scope, mode: rdResults.mode, ...rdResults.filters })}`);
    if (epoch !== rdResults.epoch || state.activePage !== 'rd-results' || scope !== state.selectedBaselineIds.join(',')) return;
    if (savedPreview) {
      try {
        const receipt = savedPreview.outcome ? await rdReadReceipt(savedPreview.id)
          : await rdWaitPreview(await api(`/api/rd-results/operations/${savedPreview.id}`), epoch, scope);
        if (epoch !== rdResults.epoch || state.activePage !== 'rd-results' || scope !== state.selectedBaselineIds.join(',')) return;
        if (receipt && (receipt.mode || 'rd') === rdResults.mode && (!receipt.baselines || receipt.baselines === scope)) {
          rdResults.preview = receipt; rdResults.previewOpen = true;
          rdResults.previewInfoOpen = savedPreview.infoOpen === true;
          rdResults.previewPage = Number.isSafeInteger(savedPreview.page) && savedPreview.page > 0 ? savedPreview.page : 1;
          rdResults.previewPageSize = CASE_PAGE_SIZES.includes(savedPreview.pageSize) ? savedPreview.pageSize : DEFAULT_CASE_PAGE_SIZE;
        }
      } catch (error) {
        if (epoch !== rdResults.epoch) return;
        rdResults.error = rdText('无法恢复本次预览，请刷新重试或查看上传记录。', 'Could not restore this preview. Refresh to retry or check publication history.');
      }
    }
    if (epoch !== rdResults.epoch || state.activePage !== 'rd-results') return;
    rdResults.data = data;
    rdResults.teRefresh = data.snapshot?.refresh || null;
    rdResults.filters.page = data.page;
    rdResults.filters.page_size = data.page_size;
    rdResults.filterDraft = { ...rdResults.filterDraft, page: data.page, page_size: data.page_size };
    rdPersist();
  } catch (error) { if (epoch === rdResults.epoch) rdResults.error = error.message; }
  finally {
    if (epoch === rdResults.epoch) {
      rdResults.loading = false; renderRdResults();
      if (rdTERefreshing() && !rdResults.previewOpen) rdTrackTERefresh();
    }
  }
}
async function rdReloadAfterTERefresh() {
  const draft = rdResults.filterDraft ? { ...rdResults.filterDraft } : null;
  const scope = rdResults.baselines, nextEpoch = rdResults.epoch + 1;
  await loadRdResults();
  if (rdIsTE() && rdResults.epoch === nextEpoch && scope === rdResults.baselines && draft) {
    rdResults.filterDraft = { ...rdResults.filterDraft, q: draft.q, status: draft.status };
    renderRdResults();
  }
}
async function rdRefreshTE() {
  if (!rdIsTE() || !rdValidVersion() || rdResults.busy || rdResults.loading || rdTERefreshing()) return;
  const epoch = rdResults.epoch, scope = rdResults.baselines;
  const current = () => epoch === rdResults.epoch && rdIsTE() && state.activePage === 'rd-results' && scope === state.selectedBaselineIds.join(',');
  rdForgetPreview(); rdClearSelection(); rdResults.remote = {}; rdResults.overwrite = false; rdResults.pendingPreview = null; rdResults.excelFile = null;
  rdResults.busy = true; rdResults.busyAction = 'refresh-te'; rdResults.error = '';
  rdResults.teRefresh = { status: 'running', scanned: 0, total: rdResults.data?.counts.total || 0 };
  renderRdResults();
  try {
    const response = await api('/api/rd-results/te-refresh', { method: 'POST', body: JSON.stringify({ baselines: scope }) });
    if (!current()) return;
    rdResults.teRefresh = response;
  } catch (_) {
    if (current()) {
      rdResults.teRefresh = null;
      rdResults.error = rdText('无法刷新 TE 标签，请重试。','Could not refresh TE labels; retry.');
    }
  } finally {
    if (current()) { rdResults.busy = false; rdResults.busyAction = ''; renderRdResults(); }
  }
  if (!current()) return;
  if (rdTERefreshing()) rdTrackTERefresh();
  else if (rdResults.teRefresh) await rdReloadAfterTERefresh();
}
async function rdTrackTERefresh() {
  const token = { epoch: rdResults.epoch, scope: rdResults.baselines };
  if (rdResults.teTracking?.epoch === token.epoch) return;
  rdResults.teTracking = token;
  const current = () => rdResults.teTracking === token && token.epoch === rdResults.epoch && rdIsTE()
    && state.activePage === 'rd-results' && token.scope === state.selectedBaselineIds.join(',') && !rdResults.previewOpen;
  try {
    while (current() && rdTERefreshing()) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      if (!current()) return;
      try {
        const status = await api(`/api/rd-results/te-refresh?${new URLSearchParams({ baselines: token.scope })}`);
        if (!current()) return;
        rdResults.teRefresh = status;
        if (status.status !== 'running') {
          if (status.status === 'ready') showToast(rdText('TE 标签已刷新','TE labels refreshed'));
          await rdReloadAfterTERefresh(); return;
        }
        if (!$('#rdResultsPage .ui-select.is-open')) renderRdResults();
      } catch (_) {
        if (current()) {
          rdResults.teRefresh = null;
          rdResults.error = rdText('TE 刷新状态暂不可用，请刷新页面。','TE refresh status unavailable; reload the page.');
          renderRdResults();
        }
        return;
      }
    }
  } finally { if (rdResults.teTracking === token) rdResults.teTracking = null; }
}
async function rdPost(path, body) { return api(`/api/rd-results/${path}${['preview','preview-scope','commit'].includes(path) ? '?background=true' : ''}`, { method: 'POST', body: JSON.stringify(path === 'commit' ? body : { ...body, mode: rdResults.mode }) }); }
async function rdWaitPreview(receipt, epoch, scope) {
  while (receipt.state === 'preparing') {
    rdResults.pendingPreview = receipt;
    renderRdResults();
    await new Promise(resolve => setTimeout(resolve, 1000));
    if (epoch !== rdResults.epoch || state.activePage !== 'rd-results' || scope !== state.selectedBaselineIds.join(',')) return null;
    receipt = await api(`/api/rd-results/operations/${receipt.id}`);
  }
  rdResults.pendingPreview = null;
  if (receipt.state === 'preview_failed') throw Error(rdReason(receipt.reason));
  return receipt;
}
async function rdReadReceipt(operation) {
  const receipt = await api(`/api/rd-results/operations/${operation}`);
  // A preview receipt may also belong to a commit still in preflight. It is
  // not proof of rejection or cancellation, and must never enable resubmission.
  return receipt.state === 'preview' ? { ...receipt, state: 'outcome_unknown', reason: 'receipt_pending' } : receipt;
}
async function rdTrackCommit() {
  const p = rdResults.preview;
  if (!p || p.state !== 'running' || (rdResults.tracking?.id === p.id && rdResults.tracking.epoch === rdResults.epoch)) return;
  const token = { id: p.id, epoch: rdResults.epoch };
  rdResults.tracking = token; rdResults.trackingError = '';
  const current = () => rdResults.tracking === token && token.epoch === rdResults.epoch
    && state.activePage === 'rd-results' && rdResults.previewOpen && rdResults.preview?.id === token.id;
  try {
    while (current() && rdResults.preview.state === 'running') {
      await new Promise(resolve => setTimeout(resolve, rdResults.trackingError ? 3000 : 1000));
      if (!current()) return;
      try {
        const receipt = await api(`/api/rd-results/operations/${token.id}?progress_only=true`);
        if (!current()) return;
        rdResults.preview = { ...rdResults.preview, ...receipt };
        rdResults.trackingError = '';
      } catch (_) {
        if (!current()) return;
        rdResults.trackingError = true;
      }
      // Keep keyboard/dropdown interaction stable while progress is polling.
      if (!$('#rdResultsPage .ui-select.is-open')) rdRenderPreview();
    }
  } finally {
    if (rdResults.tracking === token) rdResults.tracking = null;
  }
}
async function rdRefreshPublishedSummary(p) {
  if (!p.refresh || !['complete','needs_recheck'].includes(p.state) || rdResults.refreshedOperation === p.id) return;
  rdResults.refreshedOperation = p.id;
  const epoch = rdResults.epoch, scope = rdResults.baselines, mode = rdResults.mode;
  try {
    const data = await api(`/api/rd-results?${new URLSearchParams({ baselines:scope, mode, ...rdResults.filters })}`);
    if (epoch !== rdResults.epoch || mode !== rdResults.mode || state.activePage !== 'rd-results' || scope !== state.selectedBaselineIds.join(',')) return;
    rdResults.data = data; rdResults.filters.page = data.page; rdPersist();
    if (!rdResults.previewOpen) renderRdResults();
  } catch (_) {
    if (epoch === rdResults.epoch) rdResults.refreshedOperation = null;
  }
}
function rdCommitProgress(p) {
  const g = p.progress;
  if (!g || !['running', 'complete', 'needs_recheck'].includes(p.state)) return '';
  const preflight = g.stage === 'preflight';
  const done = preflight ? g.checked || 0 : g.verified || 0, total = preflight ? g.check_total || 0 : g.total || 0;
  const label = preflight ? rdText('提交前核对', 'Preflight check') : g.stage === 'refreshing' ? rdText('刷新 Trail 标签', 'Refreshing Trail labels') : p.state === 'running' ? rdText('上传并读回核验', 'Upload and verify readback') : rdStatus(p.state);
  const seconds = Math.floor(g.elapsed_seconds || 0);
  const detail = p.state === 'running' && !preflight ? rdText(`处理中 ${g.active || 0} · 等待 ${g.waiting || 0}`, `${g.active || 0} active · ${g.waiting || 0} waiting`) : '';
  return `<div class="cron-stage-progress rd-upload-progress" role="status"><span>${escapeHtml(label)} <strong>${done} / ${total}</strong></span><progress max="${Math.max(1,total)}" value="${done}" aria-label="${escapeHtml(label)}"></progress><span>${total ? Math.floor(done / total * 100) : 0}%${detail ? ` · ${detail}` : ''} · ${rdText(`已用时 ${seconds}s`, `${seconds}s elapsed`)}</span></div>${p.state === 'running' ? `<p class="rd-description">${rdText('后台自动更新进度；异常时停止派发，已发出的批次会继续读回核验。', 'Progress updates automatically. On failure, dispatch stops and in-flight batches finish readback verification.')}</p>` : ''}`;
}
async function rdClick(event) {
  const mode = event.target.closest('[data-rd-mode]')?.dataset.rdMode;
  if (mode && mode !== rdResults.mode && !rdResults.busy && !rdResults.committing) {
    rdForgetPreview(); rdResults.mode = mode; rdResults.overwrite = false; rdResults.operations = []; rdResults.pendingPreview = null;
    rdResults.filters.status = 'all'; rdResults.filters.page = 1;
    rdPersist(); return loadRdResults();
  }
  const filter = event.target.closest('[data-rd-filter]')?.dataset.rdFilter;
  if (filter && !rdResults.busy && !rdResults.loading) {
    rdResults.filters.status = filter; rdResults.filters.page = 1; rdPersist(); return loadRdResults();
  }
  const operation = event.target.closest('[data-rd-operation]')?.dataset.rdOperation;
  let action = event.target.closest('[data-rd-action]')?.dataset.rdAction;
  if ((!action && !operation) || rdResults.busy) return;
  if (action === 'import-excel') { $('#rdExcelFile')?.click(); return; }
  if (action === 'clear-excel') {
    rdForgetPreview(); rdResults.excelFile = null; rdResults.pendingPreview = null; rdResults.error = '';
    renderRdResults(); $('#rdResultsPage [data-rd-action="import-excel"]')?.focus(); return;
  }
  if (action === 'refresh-te') return rdRefreshTE();
  if (rdTERefreshing() && (action === 'preview' || action === 'history' || operation)) return;
  if (action === 'refresh') return loadRdResults();
  if (action === 'jump') return rdJumpToPage();
  if (['previous','next'].includes(action)) { rdResults.filters.page = rdResults.data.page + (action === 'next' ? 1 : -1); rdPersist(); return loadRdResults(); }
  if (action === 'preview') {
    if (rdHasExcel()) return rdPreviewExcel();
    if (!rdSelectedCount()) return;
    if (rdResults.allSelected) action = 'preview-scope';
  }
  const epoch = rdResults.epoch, scope = rdResults.baselines;
  rdResults.busy = true; rdResults.busyAction = operation ? 'resume-preview' : action; rdResults.error = ''; renderRdResults();
  try {
    if (action === 'history' || operation) {
      let response = await api(`/api/rd-results/operations${operation ? '/' + operation : '?mode=' + rdResults.mode}`);
      if (operation) response = await rdWaitPreview(response, epoch, scope);
      if (!response) return;
      if (epoch !== rdResults.epoch || state.activePage !== 'rd-results') return;
      if (operation) { rdOpenPreview(response); }
      else rdResults.operations = response.items;
      return;
    }
    let response = await rdPost(action, action === 'preview-scope'
      ? { baselines: scope, q: rdResults.filters.q, status: rdResults.filters.status, overwrite: rdResults.overwrite, excluded_issue_ids: [...rdResults.excluded] }
      : { baselines: scope, issue_ids: action === 'status' ? rdResults.data.items.map(r=>r.issue_id) : [...rdResults.selected], overwrite: rdResults.overwrite });
    if (action !== 'status') response = await rdWaitPreview(response, epoch, scope);
    if (!response || epoch !== rdResults.epoch || state.activePage !== 'rd-results' || scope !== state.selectedBaselineIds.join(',')) return;
    if (action === 'status') { rdResults.remote = Object.fromEntries(response.items.map(r=>[r.issue_id,r])); rdResults.selected.clear(); }
    else { rdOpenPreview(response); }
  } catch (error) { if (epoch === rdResults.epoch) rdResults.error = error.message; }
  finally { rdResults.busy = false; rdResults.busyAction = ''; renderRdResults(); }
}
async function rdPreviewExcel() {
  const file = rdResults.excelFile;
  if (!file || !rdIsTE() || !rdValidVersion() || rdResults.loading || rdTERefreshing()) return;
  const epoch = rdResults.epoch, scope = rdResults.baselines;
  rdForgetPreview(); rdResults.busy = true; rdResults.busyAction = 'excel-preview'; rdResults.error = ''; renderRdResults();
  try {
    const body = new FormData(); body.append('file', file, file.name); body.append('baselines', scope); body.append('overwrite', String(rdResults.overwrite));
    const response = await api('/api/rd-results/te-excel-preview?background=true', { method: 'POST', body });
    const receipt = await rdWaitPreview(response, epoch, scope);
    if (receipt && epoch === rdResults.epoch && scope === state.selectedBaselineIds.join(',')) rdOpenPreview(receipt);
  } catch (error) { if (epoch === rdResults.epoch) rdResults.error = error.message; }
  finally { rdResults.busy = false; rdResults.busyAction = ''; renderRdResults(); }
}
function rdOpenPreview(receipt) {
  if ((receipt.mode || 'rd') !== rdResults.mode) throw Error(rdText('上传类型不一致，请返回重新预览。', 'Publication type changed; create a new preview.'));
  rdResults.listScroll = window.scrollY;
  rdResults.preview = receipt;
  rdResults.previewOpen = true;
  rdResults.previewPage = 1;
  rdResults.previewJumpDraft = null;
  rdResults.previewInfoOpen = false;
  renderRdResults();
  window.scrollTo(0, 0);
  $('#rdPreviewTitle')?.focus({ preventScroll: true });
}
function rdValueMarkup(value) {
  if (!value) return '<span class="muted">—</span>';
  const label = value === '成功' ? '正确触发' : value;
  return ['正确触发', '误触发', '无需协助'].includes(label)
    ? labelBadge(label, '—', rdLabel(label))
    : escapeHtml(({ '失败': rdText('失败','Failed'), '未接起': rdText('未接起','Unanswered'), '超出范围': rdText('超出范围','Out of scope') })[value] || value);
}
function rdPreviewStatus(row) {
  if (rdIsTE()) return row.eligible ? rdText('修正 TE', 'Correct TE') : rdStatus(row.status);
  return row.eligible ? row.status === 'conflict' ? rdText('覆盖现有结果', 'Overwrite existing') : rdText('新增结果', 'New result')
    : row.status === 'same' ? rdText('已一致，跳过', 'Already matches · skip')
    : row.status === 'conflict' ? rdText('未允许覆盖', 'Overwrite not allowed') : rdText('不可上传', 'Blocked');
}
function rdRenderPreview() {
  const p = rdResults.preview, root = $('#rdResultsPage');
  if (!p || state.activePage !== 'rd-results') return;
  root.classList.toggle('is-te-correction', rdIsTE());
  const focused = root.contains(document.activeElement) ? document.activeElement : null;
  const focusedAction = focused?.dataset.rdAction, focusedId = focused?.id;
  const count = p.items.filter(r => r.eligible).length;
  const fileSource = p.scope?.source?.kind === 'xlsx' ? p.scope.source : null;
  const results = new Map(p.results.map(result => [result.issue_id, result]));
  const outcomes = p.items.map(row => ({ row, result: results.get(row.issue_id) }));
  const pages = Math.max(1, Math.ceil(outcomes.length / rdResults.previewPageSize));
  rdResults.previewPage = Math.max(1, Math.min(pages, rdResults.previewPage));
  const visible = outcomes.slice((rdResults.previewPage - 1) * rdResults.previewPageSize, rdResults.previewPage * rdResults.previewPageSize);
  const counts = key => outcomes.filter(({row,result}) => row.eligible && (result?.state || 'unverified') === key).length;
  const overwritten = p.items.filter(r => r.eligible && r.status === 'conflict').length;
  const skipped = p.items.filter(r => !r.eligible).length;
  const preview = p.state === 'preview';
  const running = p.state === 'running';
  const legacyTEPreview = rdIsTE() && preview && p.policy_version !== 2;
  const displayState = result => result?.phase || (running && result?.state === 'not_attempted' && !result.reason ? 'waiting' : result?.state);
  const stat = (label, value) => `<div><dt>${label}</dt><dd>${value}</dd></div>`;
  const summary = preview
    ? (overwritten ? stat(rdText('将覆盖', 'Will overwrite'), overwritten) : '') + (skipped ? stat(rdText('将跳过', 'Will skip'), skipped) : '')
    : (counts('unverified') + (running ? 0 : counts('intent')) ? stat(rdText('未确认', 'Unverified'), counts('unverified') + (running ? 0 : counts('intent'))) : '') + (!running && counts('not_attempted') ? stat(rdText('未执行', 'Not attempted'), counts('not_attempted')) : '');
  const distribution = ['正确触发', '误触发', '无需协助'].map(label => {
    const value = label === '正确触发' ? '成功' : label;
    const n = p.items.filter(row => row.eligible && row.desired === value).length;
    return n ? `<span>${rdValueMarkup(value)}<span class="rd-label-count">${n}</span></span>` : '';
  }).join('');
  const scopeDetails = p.scope ? `${p.scope.total !== p.items.length ? stat(rdText('筛选范围', 'Filtered scope'), p.scope.total) : ''}${p.scope.excluded ? stat(rdText('手动排除', 'Manually excluded'), p.scope.excluded) : ''}${p.scope.blocked ? stat(rdText('无有效标注', 'Without valid labels'), p.scope.blocked) : ''}` : '';
  rdSavePreview();
  root.innerHTML = `<div id="rdResultsPreview" class="rd-preview-page" aria-labelledby="rdPreviewTitle">
    <section class="page-card runs-source-card rd-preview-overview">
      <div class="runs-source-heading"><div><h3 id="rdPreviewTitle" tabindex="-1">${rdIsTE() ? preview ? rdText('TE 修正预览', 'TE correction preview') : running ? rdText('TE 修正进度', 'TE correction progress') : rdText('TE 修正结果', 'TE correction outcome') : preview ? rdText('上传预览', 'Upload preview') : running ? rdText('上传进度', 'Upload progress') : rdText('上传结果', 'Upload outcome')}</h3>${fileSource ? `<p class="rd-description">${rdText('XLSX 期望输出：','XLSX expected outputs: ')}${escapeHtml(fileSource.filename)}</p>` : preview || p.progress ? '' : `<p class="rd-description">${rdStatus(p.state)}</p>`}</div>${rdButton('close', rdText('返回选择', 'Back to selection'), rdResults.busy, 'quiet')}</div>
      <div class="rd-preview-summary"><div class="rd-preview-total"><strong>${preview ? count : counts('verified')}</strong><span>${preview ? rdText('条可上传', 'ready to upload') : rdText('条已核验', 'verified')}</span></div>${summary ? `<dl class="rd-preview-counts">${summary}</dl>` : ''}${distribution && preview ? `<div class="rd-preview-distribution" aria-label="${rdText('上传标注分布', 'Upload label distribution')}">${distribution}</div>` : ''}</div>
      ${rdCommitProgress(p)}
      ${rdResults.trackingError && running ? `<p class="rd-notice is-error" role="status">${rdText('进度连接中断，任务可能仍在执行；正在重连…', 'Progress connection lost; the task may still be running. Reconnecting…')}</p>` : ''}
      ${legacyTEPreview ? `<p class="rd-notice is-error" role="status">${rdText('TE 修正规则已更新，请返回选择后重新预览。','TE correction rules changed. Return to selection and preview again.')}</p>` : ''}
      ${preview && !count ? `<p class="rd-notice">${rdText('没有需要上传的变更，请检查明细或返回修改选择。', 'No changes to upload. Check the details or return to adjust your selection.')}</p>` : ''}
      ${p.reason ? `<p class="rd-notice" role="status">${escapeHtml(rdReason(p.reason))}</p>` : ''}
      ${rdResults.error ? `<p class="rd-notice is-error" role="alert">${escapeHtml(rdResults.error)}</p>` : ''}
      ${p.refresh ? `<p class="rd-description" role="status">${p.refresh.status === 'ready' ? rdText('标签已回读刷新', 'Labels refreshed from Trail') : rdText('上传结果已保留，标签刷新失败；可手动刷新。','Upload outcomes saved; label refresh failed. Refresh manually.')}</p>` : ''}
      ${!preview && !running && p.history_operation_id ? `<a class="text-link" href="${escapeHtml(pageUrl('trail-history', { operation:p.history_operation_id, baselines:state.selectedBaselineIds }))}">${rdText('查看 Trail 更新记录','View Trail update history')}</a>` : ''}
      ${p.audit_error ? `<p class="rd-notice is-error" role="status">${rdText('更新记录暂未同步，请刷新 Trail 更新记录。','Update history sync pending. Refresh Trail update history.')}</p>` : ''}
      <details id="rdPreviewInfo" class="rd-preview-info" ${rdResults.previewInfoOpen ? 'open' : ''}><summary>${rdText('接口与规则', 'Endpoint and rules')}</summary><div>
        <dl class="rd-upload-target"><div><dt>${rdText('上传接口', 'Upload endpoint')}</dt><dd><span class="rd-http-method">POST</span><code>${RD_UPLOAD_ENDPOINT.replace('/paladin/', '<wbr>/paladin/')}</code></dd></div><div><dt>${rdText('更新字段', 'Updated field')}</dt><dd><code>${rdUploadField()}</code></dd></div>
        ${stat(rdText('映射规则', 'Value mapping'), rdText('正确触发 → 成功；其他结论保持原值。', 'Correct trigger → 成功; other labels keep their values.'))}${scopeDetails}
        ${rdIsTE() ? stat(rdText('版本数据集', 'Version dataset'), escapeHtml(p.baselines || rdResults.baselines)) : ''}
        ${fileSource ? stat(rdText('文件工作表', 'Worksheet'), escapeHtml(fileSource.sheet)) + stat(rdText('文件 SHA-256', 'File SHA-256'), `<code>${escapeHtml(fileSource.sha256)}</code>`) + (fileSource.duplicates ? stat(rdText('已去重', 'Duplicates removed'), fileSource.duplicates) : '') : ''}
        ${stat(rdText('操作编号', 'Operation ID'), `<code>${escapeHtml(p.id)}</code>`)}</dl>
      </div></details>
    </section>
    <section class="page-card runs-page-card rd-preview-details"><div class="runs-toolbar"><h3>${preview ? rdText('差异明细', 'Change details') : rdText('逐条结果', 'Item outcomes')}</h3><span class="rd-description">${fileSource ? rdText('按文件期望输出修正', 'Use expected outputs from the file') : p.scope ? rdText('已包含全部页的选中标注', 'Includes selected labels across all pages') : rdText('仅包含本次选中标注', 'Only the selected labels')}</span></div>
      <div class="rd-table-wrap" role="region" tabindex="0" aria-label="${rdText('上传明细，可横向滚动', 'Upload details; scroll horizontally')}"><table class="rd-table"><thead><tr><th>Issue</th><th>${rdIsTE() ? rdText('当前 TE（实时）', 'Current TE (live)') : rdText('Trail 原值', 'Current Trail value')}</th>${rdIsTE() ? `<th>${rdText('当前 RD（实时）','Current RD (live)')}</th>` : ''}<th>${fileSource ? rdText('文件期望输出','File expected output') : rdIsTE() ? rdText('TE 修正值', 'New TE value') : rdText('上传值', 'New value')}</th>${preview ? '' : `<th>${rdText('读回值', 'Readback value')}</th>`}<th>${rdText('处理状态', 'Disposition')}</th></tr></thead><tbody>${visible.map(({row:r,result}) => `<tr><td>${escapeHtml(r.issue_id)}</td><td>${rdValueMarkup(r.current)}</td>${rdIsTE() ? `<td>${rdValueMarkup(r.rd_current)}</td>` : ''}<td>${rdValueMarkup(r.desired)}</td>${preview ? '' : `<td>${rdValueMarkup(result?.observed)}</td>`}<td>${preview ? `<span class="run-source-badge rd-status rd-status-${r.eligible ? r.status === 'conflict' ? 'warn' : 'ready' : 'neutral'}">${escapeHtml(rdPreviewStatus(r))}</span>` : rdStatusBadge(displayState(result) || (!r.eligible ? r.status : 'unverified'))}${result?.reason ? `<div class="rd-row-reason">${escapeHtml(rdReason(result.reason))}</div>` : ''}</td></tr>`).join('')}</tbody></table></div>
      ${rdPaginationMarkup({ total: outcomes.length, page: rdResults.previewPage, pages }, true)}
      <div class="rd-preview-footer"><p class="rd-description" role="status">${rdResults.busy ? rdText('正在读取操作记录…', 'Reading operation receipt…') : running ? rdText('无需手动刷新；可返回选择，稍后从上传记录继续查看。', 'No manual refresh needed. You can return and follow this task from publication history.') : preview ? rdText('预览 10 分钟内有效；数据变化后需重新预览。', 'Valid for 10 minutes. Preview again if the data changes.') : rdText('请以逐条核验结果为准。', 'Use the per-item verification results.')}${!rdResults.data?.write_enabled && preview ? ' ' + rdText('真实上传未启用。', 'Publishing is disabled.') : ''}</p><div class="run-manager-actions">${preview ? rdButton('commit', rdIsTE() ? rdText(`确认修正 TE ${count} 条`, `Confirm TE correction · ${count}`) : rdText(`确认上传 ${count} 条`, `Confirm upload · ${count}`), rdResults.busy || !count || !rdResults.data?.write_enabled || legacyTEPreview, 'primary') : rdButton('receipt', rdText('刷新本次结果', 'Refresh outcome'), rdResults.busy)}</div></div>
    </section></div>`;
  enhanceDashboardSelects(root);
  root.oninput = event => { if (event.target.id === 'rdPreviewPageJump') rdResults.previewJumpDraft = event.target.value; };
  root.onchange = event => {
    if (event.target.id === 'rdPreviewPageSize' && !rdResults.busy && CASE_PAGE_SIZES.includes(Number(event.target.value))) {
      rdResults.previewPageSize = Number(event.target.value); rdResults.previewPage = 1; rdResults.previewJumpDraft = null; rdRenderPreview();
    }
  };
  $('#rdPreviewInfo').ontoggle = event => { if (event.target.isConnected) { rdResults.previewInfoOpen = event.target.open; rdSavePreview(); } };
  const jumpPreview = () => {
    const input = $('#rdPreviewPageJump'), value = Number(input.value);
    if (input.value.trim() && Number.isSafeInteger(value)) rdResults.previewPage = Math.max(1, Math.min(pages, value));
    rdResults.previewJumpDraft = null;
    rdRenderPreview();
  };
  root.onkeydown = event => {
    if (event.target.id === 'rdPreviewPageJump' && event.key === 'Enter' && !event.isComposing && !rdResults.busy) { event.preventDefault(); jumpPreview(); }
  };
  if (!rdResults.busy) {
    const nextFocus = focusedId ? document.getElementById(focusedId) : focusedAction ? root.querySelector(`[data-rd-action="${focusedAction}"]`) : null;
    nextFocus?.focus({ preventScroll: true });
  }
  if (running && !rdResults.committing) rdTrackCommit();
  if (!running && !preview) rdRefreshPublishedSummary(p);
  root.onclick = async event => {
    const action = event.target.closest('[data-rd-action]')?.dataset.rdAction;
    if (rdResults.busy) return;
    if (action === 'close') {
      rdForgetPreview();
      rdResults.previewOpen = false;
      if (['complete','needs_recheck'].includes(p.state)) await loadRdResults();
      else renderRdResults();
      window.scrollTo(0, rdResults.listScroll);
      $('#rdResultsPage [data-rd-action="preview"]')?.focus({ preventScroll: true });
      return;
    }
    if (action === 'preview-jump') { jumpPreview(); return; }
    if (action === 'preview-previous' || action === 'preview-next') {
      rdResults.previewPage = Math.max(1, Math.min(pages, rdResults.previewPage + (action === 'preview-next' ? 1 : -1))); rdResults.previewJumpDraft = null; rdRenderPreview(); return;
    }
    if (!['commit', 'receipt'].includes(action)) return;
    rdResults.busy = true; rdResults.committing = true; rdResults.error = '';
    if (action === 'commit') {
      rdResults.preview = { ...p, state: 'running', results: p.items.filter(r => r.eligible).map(r => ({ issue_id: r.issue_id, state: 'not_attempted', reason: '' })),
        progress: { stage: 'preflight', checked: 0, check_total: p.items.length, total: count, elapsed_seconds: 0 } };
    }
    rdRenderPreview();
    try {
      if (action === 'receipt') rdResults.preview = await rdReadReceipt(p.id);
      else {
        rdClearSelection(); rdResults.remote = {};
        try { rdResults.preview = await rdPost('commit', { operation_id: p.id, confirmed: true }); }
        catch (error) {
          rdResults.error = error.message;
          rdResults.preview = await rdReadReceipt(p.id);
          if (['complete', 'running'].includes(rdResults.preview.state)) {
            rdResults.error = '';
            rdResults.preview.reason ||= 'response_recovered';
          }
        }
      }
    } catch (error) {
      rdResults.error = error.message;
      // Keep already received item outcomes if only a refresh failed.
      rdResults.preview = { ...rdResults.preview, state: 'outcome_unknown', reason: 'receipt_unavailable' };
    }
    finally { rdResults.busy = false; rdResults.committing = false; renderRdResults(); }
  };
}
