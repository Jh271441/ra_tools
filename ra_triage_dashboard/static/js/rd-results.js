/* Canonical Manual labels -> explicit RD publication. No automatic remote writes. */
const rdResults = { data: null, remote: {}, selected: new Set(), epoch: 0, loading: false,
  busy: false, busyAction: '', committing: false, error: '', preview: null, operations: [], overwrite: false, baselines: '', filterDraft: null, pageJumpDraft: null,
  previewPage: 1, previewPageSize: DEFAULT_CASE_PAGE_SIZE, previewJumpDraft: null, pendingPreview: null,
  filters: { q: '', status: 'all', page: 1, page_size: DEFAULT_CASE_PAGE_SIZE } };
const rdText = (zh, en) => uiText(zh, en);
const RD_UPLOAD_ENDPOINT = 'https://voyager.intra.xiaojukeji.com/paladin/issue/pool/multi_update/';
const RD_UPLOAD_FIELD = 'ra_rd_review_result';
function rdStatus(value) {
  const names = { resolved: ['已完成', 'Completed'], pending: ['待上传', 'Ready to upload'],
    conflict: ['结果不同', 'Different result'], same: ['已一致', 'Already matches'], blocked: ['不可上传', 'Blocked'],
    unchecked: ['未核对', 'Not checked'], preparing: ['正在生成预览', 'Preparing preview'], preview: ['预览待确认', 'Preview ready'], preview_failed: ['预览失败', 'Preview failed'], complete: ['已核验完成', 'Verified complete'],
    needs_recheck: ['需重新核对', 'Recheck required'], running: ['处理中', 'Processing'],
    verified: ['读回一致', 'Readback verified'], unverified: ['未确认', 'Unverified'], intent: ['结果待核对', 'Outcome needs checking'],
    not_attempted: ['未执行', 'Not attempted'],
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
    batch_stopped: ['前序条目未核验，已停止后续上传。', 'Stopped because an earlier item could not be verified.'],
    protected_changed: ['读回发现其他字段变化，已停止上传，需人工核对。', 'Readback found changes to other fields. Upload stopped; inspect manually.'],
    value_mismatch: ['读回值与上传值不一致，已停止上传。', 'Readback differs from the requested value. Upload stopped.'],
    readback_failed: ['写入后读回失败，结果未知；请重新核对 Trail。', 'Readback failed after writing; outcome unknown. Check Trail again.'],
    interrupted: ['执行中断，可能已写入；请重新核对 Trail。', 'Execution was interrupted; a write may have occurred. Check Trail again.'],
    receipt_unavailable: ['无法取得操作记录；请刷新本次结果，勿重复上传。', 'Operation receipt unavailable. Refresh this outcome before uploading again.'],
    receipt_pending: ['尚无执行结果，请稍后刷新本次结果；请求可能仍在处理中。', 'No execution outcome yet. Refresh this outcome shortly; the request may still be processing.'],
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
  const metrics = [
    ['all', 'total', '范围内 Issues', 'Issues in scope', 'M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z'],
    ['resolved', 'resolved', '已完成', 'Completed', 'm5 12 4 4L19 6'],
    ['pending', 'pending', '待标注', 'Pending labels', 'M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0'],
    ['conflict', 'conflict', '需复核', 'Needs review', 'm12 3 10 18H2L12 3zm0 6v5m0 3v1'],
  ];
  return `<div class="run-source-tabs rd-metrics" aria-label="${rdText('标注概览与筛选', 'Label overview and filters')}">${metrics.map(([filter,key,zh,en,path]) => `<button class="run-source-tab rd-metric ${rdResults.filters.status === filter ? 'active' : ''}" type="button" data-rd-filter="${filter}" aria-pressed="${rdResults.filters.status === filter}" ${rdResults.loading || rdResults.busy ? 'disabled' : ''}><span class="run-source-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="${path}"/></svg></span><span><strong>${rdText(zh,en)}</strong></span><em>${data ? data.counts[key] : '—'}</em></button>`).join('')}</div>`;
}
function rdSelectable(row) {
  const remote = rdResults.remote[row.issue_id];
  return row.group === 'resolved' && (!remote || remote.status === 'pending' || (remote.status === 'conflict' && rdResults.overwrite));
}
function rdPreviewProgress() {
  const progress = rdResults.pendingPreview?.progress;
  if (progress?.stage === 'trail') return rdText(`正在核对 Trail ${progress.checked} / ${progress.total}，完成后展示预览…`, `Checking Trail ${progress.checked} / ${progress.total}; preview will open when ready…`);
  return rdText('正在汇总标注并核对 Trail，尚未上传…', 'Collecting labels and checking Trail; nothing uploaded yet…');
}
function renderRdResults() {
  if (state.activePage !== 'rd-results') return;
  const root = $('#rdResultsPage'), d = rdResults.data, f = rdResults.filters;
  const draft = rdResults.filterDraft || f;
  const focus = document.activeElement?.id, caret = document.activeElement?.selectionStart;
  const focusedIssue = document.activeElement?.dataset.rdId;
  const ready = (d?.items || []).filter(r => rdResults.remote[r.issue_id]?.status === 'pending').length;
  const checked = Object.keys(rdResults.remote).length;
  root.innerHTML = `<section class="page-card runs-source-card rd-overview"><div class="runs-source-heading"><div><h3>${rdText('标注上传', 'Label upload')}</h3></div><div class="run-manager-actions">${rdButton('refresh', rdText('刷新', 'Refresh'), rdResults.loading || rdResults.busy, 'quiet')}</div></div>
    ${rdMetricsMarkup(d)}
    <dl class="rd-upload-target"><div><dt>${rdText('上传接口','Upload endpoint')}</dt><dd><span class="rd-http-method">POST</span><code>${RD_UPLOAD_ENDPOINT}</code></dd></div><div><dt>${rdText('目标字段','Target field')}</dt><dd><code>${RD_UPLOAD_FIELD}</code></dd></div></dl></section>
    <section class="page-card runs-page-card rd-workspace"><div class="rd-detail-toolbar"><div class="rd-detail-heading"><h3>${rdText('标注明细', 'Label details')}</h3><span class="rd-description">${checked ? rdText(`已核对 ${checked} · 待上传 ${ready}`, `${checked} checked · ${ready} ready`) : rdText('先选标注，预览时自动核对', 'Select labels; preview checks Trail automatically')}</span></div>
    <form id="rdFilters" class="run-filter-bar rd-filters"><input id="rdSearch" name="q" aria-label="${rdText('Issue 搜索','Find Issue')}" placeholder="${rdText('搜索 Issue ID', 'Find Issue ID')}" value="${escapeHtml(draft.q)}" autocomplete="off" />
    <select id="rdState" name="status" aria-label="${rdText('标注状态','Label status')}">${[['all','全部状态','All statuses'],['resolved','已完成','Completed'],['pending','待标注','Pending labels'],['conflict','冲突 / 失效','Conflict / stale']].map(([v,zh,en]) => `<option value="${v}" ${draft.status === v ? 'selected' : ''}>${rdText(zh,en)}</option>`).join('')}</select><button class="button button-secondary" type="submit" ${rdResults.busy || rdResults.loading ? 'disabled' : ''}>${rdText('筛选','Apply')}</button>${rdButton('status',rdText('核对本页 Trail','Check page in Trail'), !d?.items.length || rdResults.busy || rdResults.loading, 'quiet')}</form></div>
    ${rdResults.error || rdResults.loading || rdResults.busy ? `<p class="rd-notice ${rdResults.error ? 'is-error' : ''}" role="status">${escapeHtml(rdResults.error || (rdResults.loading ? rdText('正在加载标注…','Loading labels…') : rdResults.busyAction?.startsWith('preview') || rdResults.busyAction === 'resume-preview' ? rdPreviewProgress() : rdText('正在处理，请稍候…','Processing, please wait…')))}${rdResults.pendingPreview && !rdResults.busy ? `<button type="button" class="button button-quiet" data-rd-operation="${rdResults.pendingPreview.id}">${rdText('继续查看预览','Resume preview')}</button>` : ''}</p>` : ''}
    <div class="rd-selection-bar ${rdResults.selected.size ? 'has-selection' : ''}"><div class="rd-selection-tools"><div class="run-manager-actions"><span class="rd-selection-count">${rdText('已选','Selected')} <strong>${rdResults.selected.size}</strong></span>${rdButton('select',rdText('全选本页','Select page'), !d?.items.some(rdSelectable) || rdResults.busy || rdResults.loading, 'text')}</div>
    ${state.session.is_admin ? `<label class="rd-checkbox"><input class="ui-checkbox" id="rdOverwrite" type="checkbox" ${rdResults.overwrite ? 'checked' : ''} ${rdResults.busy ? 'disabled' : ''}>${rdText('覆盖不同的 RD 结果','Overwrite different RD results')}</label>` : ''}</div>
    <div class="run-manager-actions">${d && !d.write_enabled ? `<span class="rd-notice" title="${rdText('真实写入开关关闭，核对与预览可用','Publishing is disabled; checking and preview are available')}">${rdText('写入未启用','Publishing disabled')}</span>` : ''}${state.session.is_admin ? rdButton('preview',rdText('预览所选','Preview selected'), !rdResults.selected.size || rdResults.busy || rdResults.loading, 'quiet') + rdButton('preview-scope',rdText('全部上传','Upload all'), !d?.total || !d?.counts.resolved || rdResults.busy || rdResults.loading, 'primary', rdText('核对当前筛选范围的全部页，预览后确认上传','Check all pages in the current filter, then preview and confirm upload')) : ''}</div></div>
    <div class="rd-table-wrap"><table class="rd-table"><thead><tr>${['', 'Issue', rdText('人工结论','Human label'), rdText('标注人','Contributors'), rdText('Trail 当前值','Current Trail value'), rdText('上传状态','Upload status')].map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${(d?.items || []).map(row => {
      const remote = rdResults.remote[row.issue_id], eligible = rdSelectable(row);
      return `<tr class="${rdResults.selected.has(row.issue_id) ? 'is-selected' : ''}"><td><label class="rd-checkbox"><input class="ui-checkbox" type="checkbox" data-rd-id="${escapeHtml(row.issue_id)}" aria-label="${escapeHtml(rdText('选择 ','Select ') + row.issue_id)}" ${rdResults.selected.has(row.issue_id) ? 'checked' : ''} ${!eligible || rdResults.busy ? 'disabled' : ''}></label></td><td><a class="rd-issue-link" href="${escapeHtml(pageUrl('labeling',{ issue: row.issue_id, baselines: state.selectedBaselineIds }))}">${escapeHtml(row.issue_id)}</a></td><td>${row.group === 'resolved' ? labelBadge(row.label, '—', rdLabel(row.label)) : `<span class="muted">${rdText(row.group === 'conflict' ? '冲突 / 失效' : '待标注', row.group === 'conflict' ? 'Conflict / stale' : 'Pending label')}</span>`}</td><td>${escapeHtml(row.authors.join(', ') || '—')}</td><td>${escapeHtml(remote ? rdLabel(remote.current) : '—')}</td><td>${rdStatusBadge(remote?.status || 'unchecked')}</td></tr>`;
    }).join('')}</tbody></table></div>${!rdResults.loading && !d?.items.length ? `<div class="rd-empty"><strong>${rdResults.error ? rdText('暂时无法加载标注','Unable to load labels') : rdText('当前范围没有标注结果','No labels in this scope')}</strong><p>${rdText('可调整顶部数据集或筛选条件后重试。','Adjust the selected datasets or filters and try again.')}</p></div>` : ''}
    ${rdPaginationMarkup(d)}</section>
    ${state.session.is_admin ? `<section class="page-card job-history-card"><div class="runs-toolbar"><div><h3>${rdText('上传记录','Publication history')}</h3></div>${rdButton('history',rdText('查看最近记录','Show recent operations'), rdResults.busy)}</div><div class="job-history-list">${rdResults.operations.map(r=>`<div class="job-history-row"><div class="job-history-main"><strong>${escapeHtml(r.actor)}</strong><span class="muted">${escapeHtml(r.id.slice(0,12))}</span></div><div class="run-manager-actions">${rdStatusBadge(r.state)}<button type="button" class="button button-secondary" data-rd-operation="${r.id}">${rdText('查看详情','View details')}</button></div></div>`).join('')}</div></section>` : ''}`;
  enhanceDashboardSelects(root);
  root.onclick = rdClick;
  root.oninput = event => {
    if (event.target.id === 'rdSearch') rdResults.filterDraft = { ...(rdResults.filterDraft || draft), q: event.target.value };
    if (event.target.id === 'rdPageJump') rdResults.pageJumpDraft = event.target.value;
  };
  root.onchange = (event) => {
    if (event.target.id === 'rdState') rdResults.filterDraft = { ...(rdResults.filterDraft || draft), status: event.target.value };
    if (event.target.dataset.rdId) { event.target.checked ? rdResults.selected.add(event.target.dataset.rdId) : rdResults.selected.delete(event.target.dataset.rdId); renderRdResults(); }
    if (event.target.id === 'rdOverwrite') { rdResults.overwrite = event.target.checked; rdResults.selected.clear(); renderRdResults(); }
    if (event.target.id === 'rdPageSize') {
      const size = Number(event.target.value);
      if (!rdResults.loading && !rdResults.busy && CASE_PAGE_SIZES.includes(size)) {
        rdResults.filters.page_size = size; rdResults.filters.page = 1; rdPersist(); loadRdResults();
      }
    }
  };
  root.onkeydown = event => {
    if (event.target.id === 'rdPageJump' && event.key === 'Enter' && !event.isComposing) { event.preventDefault(); rdJumpToPage(); }
  };
  $('#rdFilters').onsubmit = event => { event.preventDefault(); rdResults.filters = { ...f, q: $('#rdSearch').value, status: $('#rdState').value, page: 1 }; rdPersist(); loadRdResults(); };
  if (focus === 'rdSearch') { $('#rdSearch').focus(); $('#rdSearch').setSelectionRange(caret, caret); }
  if (focus === 'rdOverwrite') $('#rdOverwrite')?.focus();
  if (focusedIssue) root.querySelector(`[data-rd-id="${CSS.escape(focusedIssue)}"]`)?.focus();
  if ($('#rdResultsDialog').open) rdRenderDialog();
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
  Object.entries(rdResults.filters).forEach(([k,v]) => url.searchParams.set(k, v));
  history.replaceState(history.state, '', url);
}
async function loadRdResults() {
  if (rdResults.committing) return;
  const epoch = ++rdResults.epoch, scope = state.selectedBaselineIds.join(',');
  $('#rdResultsDialog')?.close(); rdResults.preview = null; rdResults.selected.clear(); rdResults.remote = {}; rdResults.pageJumpDraft = null;
  rdResults.data = null; rdResults.error = ''; rdResults.loading = true; rdResults.baselines = scope;
  const params = new URLSearchParams(location.search);
  const requestedPage = Number(params.get('page')), requestedSize = Number(params.get('page_size'));
  rdResults.filters = { q: params.get('q') || '', status: params.get('status') || 'all',
    page: Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1,
    page_size: CASE_PAGE_SIZES.includes(requestedSize) ? requestedSize : DEFAULT_CASE_PAGE_SIZE };
  rdResults.filterDraft = { ...rdResults.filters };
  renderRdResults();
  try {
    const data = await api(`/api/rd-results?${new URLSearchParams({ baselines: scope, ...rdResults.filters })}`);
    if (epoch !== rdResults.epoch || state.activePage !== 'rd-results' || scope !== state.selectedBaselineIds.join(',')) return;
    rdResults.data = data;
    rdResults.filters.page = data.page;
    rdResults.filters.page_size = data.page_size;
    rdResults.filterDraft = { ...rdResults.filterDraft, page: data.page, page_size: data.page_size };
    rdPersist();
  } catch (error) { if (epoch === rdResults.epoch) rdResults.error = error.message; }
  finally { if (epoch === rdResults.epoch) { rdResults.loading = false; renderRdResults(); } }
}
async function rdPost(path, body) { return api(`/api/rd-results/${path}${['preview','preview-scope'].includes(path) ? '?background=true' : ''}`, { method: 'POST', body: JSON.stringify(body) }); }
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
async function rdClick(event) {
  const filter = event.target.closest('[data-rd-filter]')?.dataset.rdFilter;
  if (filter && !rdResults.busy && !rdResults.loading) {
    rdResults.filters.status = filter; rdResults.filters.page = 1; rdPersist(); return loadRdResults();
  }
  const operation = event.target.closest('[data-rd-operation]')?.dataset.rdOperation;
  const action = event.target.closest('[data-rd-action]')?.dataset.rdAction;
  if ((!action && !operation) || rdResults.busy) return;
  if (action === 'refresh') return loadRdResults();
  if (action === 'jump') return rdJumpToPage();
  if (['previous','next'].includes(action)) { rdResults.filters.page = rdResults.data.page + (action === 'next' ? 1 : -1); rdPersist(); return loadRdResults(); }
  if (action === 'select') { rdResults.data.items.filter(rdSelectable).forEach(r => rdResults.selected.add(r.issue_id)); return renderRdResults(); }
  const epoch = rdResults.epoch, scope = rdResults.baselines;
  rdResults.busy = true; rdResults.busyAction = operation ? 'resume-preview' : action; rdResults.error = ''; renderRdResults();
  try {
    if (action === 'history' || operation) {
      let response = await api(`/api/rd-results/operations${operation ? '/' + operation : ''}`);
      if (operation) response = await rdWaitPreview(response, epoch, scope);
      if (!response) return;
      if (epoch !== rdResults.epoch || state.activePage !== 'rd-results') return;
      if (operation) { rdResults.preview = response; rdResults.previewPage = 1; rdResults.previewJumpDraft = null; rdRenderDialog(); $('#rdResultsDialog').showModal(); }
      else rdResults.operations = response.items;
      return;
    }
    let response = await rdPost(action, action === 'preview-scope'
      ? { baselines: scope, q: rdResults.filters.q, status: rdResults.filters.status, overwrite: rdResults.overwrite }
      : { baselines: scope, issue_ids: action === 'status' ? rdResults.data.items.map(r=>r.issue_id) : [...rdResults.selected], overwrite: rdResults.overwrite });
    if (action !== 'status') response = await rdWaitPreview(response, epoch, scope);
    if (!response || epoch !== rdResults.epoch || state.activePage !== 'rd-results' || scope !== state.selectedBaselineIds.join(',')) return;
    if (action === 'status') { rdResults.remote = Object.fromEntries(response.items.map(r=>[r.issue_id,r])); rdResults.selected.clear(); }
    else { rdResults.preview = response; rdResults.previewPage = 1; rdResults.previewJumpDraft = null; rdRenderDialog(); $('#rdResultsDialog').showModal(); }
  } catch (error) { if (epoch === rdResults.epoch) rdResults.error = error.message; }
  finally { rdResults.busy = false; rdResults.busyAction = ''; renderRdResults(); }
}
function rdRenderDialog() {
  const p = rdResults.preview, dialog = $('#rdResultsDialog');
  if (!p) return;
  const scroll = dialog.querySelector('.trail-history-dialog-body')?.scrollTop || 0;
  const focusedAction = dialog.contains(document.activeElement) ? document.activeElement?.dataset.rdAction : '';
  const count = p.items.filter(r=>r.eligible).length;
  const results = new Map(p.results.map(result=>[result.issue_id,result]));
  const outcomes = p.items.map(row => ({ row, result: results.get(row.issue_id) }));
  const pages = Math.max(1, Math.ceil(outcomes.length / rdResults.previewPageSize));
  rdResults.previewPage = Math.max(1, Math.min(pages, rdResults.previewPage));
  const visible = outcomes.slice((rdResults.previewPage - 1) * rdResults.previewPageSize, rdResults.previewPage * rdResults.previewPageSize);
  const counts = key => outcomes.filter(({row,result}) => row.eligible && (result?.state || 'unverified') === key).length;
  const overwritten = p.items.filter(r=>r.eligible && r.status === 'conflict').length;
  const preview = p.state === 'preview';
  const scopeSummary = p.scope ? rdText(`当前筛选范围 ${p.scope.total} 条（跨全部页）；跳过无有效标注 ${p.scope.blocked} 条、已一致 ${p.items.filter(r=>r.status==='same').length} 条、未允许覆盖 ${p.items.filter(r=>r.status==='conflict'&&!r.eligible).length} 条。`, `All pages in the current filter: ${p.scope.total} items; skipped ${p.scope.blocked} without valid labels, ${p.items.filter(r=>r.status==='same').length} already matching, ${p.items.filter(r=>r.status==='conflict'&&!r.eligible).length} without overwrite permission.`) : '';
  dialog.innerHTML = `<div class="dialog-card"><h2 id="rdResultsDialogTitle">${preview ? rdText('确认标注上传','Confirm label upload') : rdText('标注上传结果','Label upload outcome')}</h2><div class="trail-history-dialog-body">${scopeSummary ? `<p class="rd-scope-summary">${escapeHtml(scopeSummary)}</p>` : ''}<p>${rdText('仅更新 RD 结果；正确触发写入 Trail 为“成功”。','Updates only the RD result; correct trigger is stored as “成功” in Trail.')}</p><p>${preview ? rdText(`本次可上传 ${count} 条，其中覆盖已有结果 ${overwritten} 条。`, `${count} eligible; ${overwritten} will overwrite existing results.`) : rdText(`已核验 ${counts('verified')} 条 · 未确认 ${counts('unverified') + counts('intent')} 条 · 未执行 ${counts('not_attempted')} 条`, `${counts('verified')} verified · ${counts('unverified') + counts('intent')} unverified · ${counts('not_attempted')} not attempted`)}</p>
    <div class="rd-table-wrap" role="region" tabindex="0" aria-label="${rdText('上传明细，可横向滚动','Upload details; scroll horizontally')}"><table class="rd-table"><thead><tr><th>Issue</th><th>${rdText('上传前值','Value before upload')}</th><th>${rdText('上传值','New value')}</th>${preview ? '' : `<th>${rdText('读回值','Readback value')}</th>`}<th>${rdText('状态','Status')}</th></tr></thead><tbody>${visible.map(({row:r,result})=>`<tr><td>${escapeHtml(r.issue_id)}</td><td>${escapeHtml(rdLabel(r.current))}</td><td>${escapeHtml(rdLabel(r.desired))}</td>${preview ? '' : `<td>${escapeHtml(rdLabel(result?.observed))}</td>`}<td>${escapeHtml(rdStatus(result?.state || (preview || !r.eligible ? r.status : 'unverified')))}${result?.reason ? `<div class="muted">${escapeHtml(rdReason(result.reason))}</div>` : ''}</td></tr>`).join('')}</tbody></table></div>
    ${rdPaginationMarkup({ total: outcomes.length, page: rdResults.previewPage, pages }, true)}
    <p role="status">${escapeHtml(preview ? rdText('预览有效期 10 分钟；标注或远端值变化后需重新预览。','Preview expires in 10 minutes; changed labels or remote values require a new preview.') : rdStatus(p.state))}</p>${p.reason ? `<p>${escapeHtml(rdReason(p.reason))}</p>` : ''}<p>${rdText('操作编号','Operation ID')}: <code>${escapeHtml(p.id)}</code></p><p role="alert">${escapeHtml(rdResults.error)}</p></div><div class="dialog-actions">${rdButton('close',rdText('关闭','Close'), rdResults.busy)}${preview ? rdButton('commit',rdText('确认上传','Confirm upload'), rdResults.busy || !count || !rdResults.data?.write_enabled, 'primary') : rdButton('receipt',rdText('刷新本次结果','Refresh outcome'), rdResults.busy)}</div></div>`;
  enhanceDashboardSelects(dialog);
  dialog.oninput = event => { if (event.target.id === 'rdPreviewPageJump') rdResults.previewJumpDraft = event.target.value; };
  dialog.onchange = event => {
    if (event.target.id === 'rdPreviewPageSize' && !rdResults.busy && CASE_PAGE_SIZES.includes(Number(event.target.value))) {
      rdResults.previewPageSize = Number(event.target.value); rdResults.previewPage = 1; rdResults.previewJumpDraft = null; rdRenderDialog();
    }
  };
  const jumpPreview = () => {
    const input = $('#rdPreviewPageJump'), value = Number(input.value);
    if (input.value.trim() && Number.isSafeInteger(value)) rdResults.previewPage = Math.max(1, Math.min(pages, value));
    rdResults.previewJumpDraft = null;
    rdRenderDialog();
  };
  dialog.onkeydown = event => {
    if (event.target.id === 'rdPreviewPageJump' && event.key === 'Enter' && !event.isComposing && !rdResults.busy) { event.preventDefault(); jumpPreview(); }
  };
  dialog.oncancel = event => { if (rdResults.busy) event.preventDefault(); };
  dialog.querySelector('.trail-history-dialog-body').scrollTop = scroll;
  if (dialog.open && !rdResults.busy && (focusedAction || !dialog.contains(document.activeElement))) {
    (dialog.querySelector(`[data-rd-action="${focusedAction}"]`) || dialog.querySelector('[data-rd-action="receipt"]') || dialog.querySelector('[data-rd-action="close"]'))?.focus();
  }
  dialog.onclick = async event => {
    const action = event.target.closest('[data-rd-action]')?.dataset.rdAction;
    if (rdResults.busy) return;
    if (action === 'close') { dialog.close(); return; }
    if (action === 'preview-jump') { jumpPreview(); return; }
    if (action === 'preview-previous' || action === 'preview-next') {
      rdResults.previewPage = Math.max(1, Math.min(pages, rdResults.previewPage + (action === 'preview-next' ? 1 : -1))); rdResults.previewJumpDraft = null; rdRenderDialog(); return;
    }
    if (!['commit', 'receipt'].includes(action)) return;
    rdResults.busy = true; rdResults.committing = true; rdResults.error = ''; rdRenderDialog();
    try {
      if (action === 'receipt') rdResults.preview = await rdReadReceipt(p.id);
      else {
        rdResults.selected.clear(); rdResults.remote = {};
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
      // Keep any already received per-item results if only a refresh failed.
      rdResults.preview = { ...p, state: 'outcome_unknown', reason: 'receipt_unavailable' };
    }
    finally { rdResults.busy = false; rdResults.committing = false; renderRdResults(); }
  };
}
