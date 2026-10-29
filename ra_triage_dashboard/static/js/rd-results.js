/* Canonical Manual labels -> explicit RD publication. No automatic remote writes. */
const rdResults = { data: null, remote: {}, selected: new Set(), epoch: 0, loading: false,
  busy: false, committing: false, error: '', preview: null, operations: [], overwrite: false, baselines: '', filterDraft: null, filters: { q: '', status: 'all', page: 1 } };
const rdText = (zh, en) => uiText(zh, en);
const RD_UPLOAD_ENDPOINT = 'https://voyager.intra.xiaojukeji.com/paladin/issue/pool/multi_update/';
const RD_UPLOAD_FIELD = 'ra_rd_review_result';
function rdStatus(value) {
  const names = { resolved: ['已完成', 'Completed'], pending: ['待上传', 'Ready to upload'],
    conflict: ['结果不同', 'Different result'], same: ['已一致', 'Already matches'], blocked: ['不可上传', 'Blocked'],
    unchecked: ['未核对', 'Not checked'], complete: ['已核验完成', 'Verified complete'],
    needs_recheck: ['需重新核对', 'Recheck required'], running: ['处理中', 'Processing'],
    verified: ['读回一致', 'Readback verified'], unverified: ['未确认', 'Unverified'], intent: ['结果待核对', 'Outcome needs checking'],
    not_attempted: ['未执行', 'Not attempted'],
    outcome_unknown: ['结果暂不可查', 'Outcome unavailable'] };
  return names[value] ? rdText(...names[value]) : value;
}
function rdReason(value) {
  const names = {
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
function rdButton(action, text, disabled = false, variant = 'secondary') {
  const style = { primary: 'button-primary', quiet: 'button-quiet', text: 'text-button', secondary: 'button-secondary' }[variant];
  return `<button type="button" class="button ${style}" data-rd-action="${action}" ${disabled ? 'disabled' : ''}>${escapeHtml(text)}</button>`;
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
    <section class="page-card runs-page-card rd-workspace"><div class="runs-toolbar"><div><h3>${rdText('标注明细', 'Label details')}</h3><p class="rd-description">${checked ? rdText(`本页已核对 ${checked} 条 · 待上传 ${ready} 条`, `${checked} checked on this page · ${ready} ready to upload`) : rdText('先核对 Trail 当前值，再选择需要上传的标注。', 'Check current Trail values, then select labels to upload.')}</p></div>${rdButton('status',rdText('核对本页 Trail','Check this page in Trail'), !d?.items.length || rdResults.busy || rdResults.loading, 'quiet')}</div>
    <form id="rdFilters" class="run-filter-bar rd-filters"><label>${rdText('Issue 搜索','Find Issue')}<input id="rdSearch" name="q" placeholder="${rdText('输入 Issue ID', 'Enter an Issue ID')}" value="${escapeHtml(draft.q)}" autocomplete="off" /></label>
    <label>${rdText('标注状态','Label status')}<select id="rdState" name="status">${[['all','全部','All'],['resolved','已完成','Completed'],['pending','待标注','Pending labels'],['conflict','冲突 / 失效','Conflict / stale']].map(([v,zh,en]) => `<option value="${v}" ${draft.status === v ? 'selected' : ''}>${rdText(zh,en)}</option>`).join('')}</select></label><button class="button button-secondary" type="submit">${rdText('筛选','Apply')}</button></form>
    ${d && !d.write_enabled ? `<p class="rd-notice">${rdText('上传尚未启用，可核对并预览。','Publishing is not enabled. Checking and preview are available.')}</p>` : ''}
    ${rdResults.error || rdResults.loading || rdResults.busy ? `<p class="rd-notice ${rdResults.error ? 'is-error' : ''}" role="status">${escapeHtml(rdResults.error || (rdResults.loading ? rdText('正在加载标注…','Loading labels…') : rdText('正在处理，请稍候…','Processing, please wait…')))}</p>` : ''}
    <div class="rd-selection-bar ${rdResults.selected.size ? 'has-selection' : ''}"><div class="rd-selection-tools"><div class="run-manager-actions"><span class="rd-selection-count">${rdText('已选','Selected')} <strong>${rdResults.selected.size}</strong></span>${rdButton('select',rdText('选择本页可上传项','Select eligible on this page'), !d || !checked || rdResults.busy || rdResults.loading, 'text')}</div>
    ${state.session.is_admin ? `<label class="rd-checkbox"><input class="ui-checkbox" id="rdOverwrite" type="checkbox" ${rdResults.overwrite ? 'checked' : ''} ${rdResults.busy ? 'disabled' : ''}>${rdText('覆盖不同的 RD 结果','Overwrite different RD results')}</label>` : ''}</div>
    ${state.session.is_admin ? rdButton('preview',rdText('预览上传','Preview upload'), !rdResults.selected.size || rdResults.busy || rdResults.loading, 'primary') : ''}</div>
    <div class="rd-table-wrap"><table class="rd-table"><thead><tr>${['', 'Issue', rdText('人工结论','Human label'), rdText('标注人','Contributors'), rdText('Trail 当前值','Current Trail value'), rdText('上传状态','Upload status')].map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${(d?.items || []).map(row => {
      const remote = rdResults.remote[row.issue_id], eligible = row.group === 'resolved' && remote && (remote.status === 'pending' || (remote.status === 'conflict' && rdResults.overwrite));
      return `<tr class="${rdResults.selected.has(row.issue_id) ? 'is-selected' : ''}"><td><label class="rd-checkbox"><input class="ui-checkbox" type="checkbox" data-rd-id="${escapeHtml(row.issue_id)}" aria-label="${escapeHtml(rdText('选择 ','Select ') + row.issue_id)}" ${rdResults.selected.has(row.issue_id) ? 'checked' : ''} ${!eligible || rdResults.busy ? 'disabled' : ''}></label></td><td><a class="rd-issue-link" href="${escapeHtml(pageUrl('labeling',{ issue: row.issue_id, baselines: state.selectedBaselineIds }))}">${escapeHtml(row.issue_id)}</a></td><td>${row.group === 'resolved' ? labelBadge(row.label, '—', rdLabel(row.label)) : `<span class="muted">${rdText(row.group === 'conflict' ? '冲突 / 失效' : '待标注', row.group === 'conflict' ? 'Conflict / stale' : 'Pending label')}</span>`}</td><td>${escapeHtml(row.authors.join(', ') || '—')}</td><td>${escapeHtml(remote ? rdLabel(remote.current) : '—')}</td><td>${rdStatusBadge(remote?.status || 'unchecked')}</td></tr>`;
    }).join('')}</tbody></table></div>${!rdResults.loading && !d?.items.length ? `<div class="rd-empty"><strong>${rdResults.error ? rdText('暂时无法加载标注','Unable to load labels') : rdText('当前范围没有标注结果','No labels in this scope')}</strong><p>${rdText('可调整顶部数据集或筛选条件后重试。','Adjust the selected datasets or filters and try again.')}</p></div>` : ''}
    <div class="rd-pagination"><span>${d ? `${d.total} ${rdText('条结果','results')}` : ''}</span><div class="run-manager-actions">${rdButton('previous',rdText('上一页','Previous'), !d || d.page <= 1 || rdResults.busy)}<span>${d ? `${d.page} / ${d.pages}` : ''}</span>${rdButton('next',rdText('下一页','Next'), !d || d.page >= d.pages || rdResults.busy)}</div></div></section>
    ${state.session.is_admin ? `<section class="page-card job-history-card"><div class="runs-toolbar"><div><h3>${rdText('上传记录','Publication history')}</h3></div>${rdButton('history',rdText('查看最近记录','Show recent operations'), rdResults.busy)}</div><div class="job-history-list">${rdResults.operations.map(r=>`<div class="job-history-row"><div class="job-history-main"><strong>${escapeHtml(r.actor)}</strong><span class="muted">${escapeHtml(r.id.slice(0,12))}</span></div><div class="run-manager-actions">${rdStatusBadge(r.state)}<button type="button" class="button button-secondary" data-rd-operation="${r.id}">${rdText('查看详情','View details')}</button></div></div>`).join('')}</div></section>` : ''}`;
  enhanceDashboardSelects(root);
  root.onclick = rdClick;
  root.oninput = event => {
    if (event.target.id === 'rdSearch') rdResults.filterDraft = { ...(rdResults.filterDraft || draft), q: event.target.value };
  };
  root.onchange = (event) => {
    if (event.target.id === 'rdState') rdResults.filterDraft = { ...(rdResults.filterDraft || draft), status: event.target.value };
    if (event.target.dataset.rdId) { event.target.checked ? rdResults.selected.add(event.target.dataset.rdId) : rdResults.selected.delete(event.target.dataset.rdId); renderRdResults(); }
    if (event.target.id === 'rdOverwrite') { rdResults.overwrite = event.target.checked; rdResults.selected.clear(); renderRdResults(); }
  };
  $('#rdFilters').onsubmit = event => { event.preventDefault(); rdResults.filters = { q: $('#rdSearch').value, status: $('#rdState').value, page: 1 }; rdPersist(); loadRdResults(); };
  if (focus === 'rdSearch') { $('#rdSearch').focus(); $('#rdSearch').setSelectionRange(caret, caret); }
  if (focus === 'rdOverwrite') $('#rdOverwrite')?.focus();
  if (focusedIssue) root.querySelector(`[data-rd-id="${CSS.escape(focusedIssue)}"]`)?.focus();
  if ($('#rdResultsDialog').open) rdRenderDialog();
}
function rdPersist() {
  const url = new URL(pageUrl('rd-results', { baselines: state.selectedBaselineIds }), location.origin);
  Object.entries(rdResults.filters).forEach(([k,v]) => url.searchParams.set(k, v));
  history.replaceState(history.state, '', url);
}
async function loadRdResults() {
  if (rdResults.committing) return;
  const epoch = ++rdResults.epoch, scope = state.selectedBaselineIds.join(',');
  $('#rdResultsDialog')?.close(); rdResults.preview = null; rdResults.selected.clear(); rdResults.remote = {};
  rdResults.data = null; rdResults.error = ''; rdResults.loading = true; rdResults.baselines = scope;
  const params = new URLSearchParams(location.search);
  rdResults.filters = { q: params.get('q') || '', status: params.get('status') || 'all', page: Number(params.get('page')) || 1 };
  rdResults.filterDraft = { ...rdResults.filters };
  renderRdResults();
  try {
    const data = await api(`/api/rd-results?${new URLSearchParams({ baselines: scope, ...rdResults.filters })}`);
    if (epoch !== rdResults.epoch || state.activePage !== 'rd-results' || scope !== state.selectedBaselineIds.join(',')) return;
    rdResults.data = data;
  } catch (error) { if (epoch === rdResults.epoch) rdResults.error = error.message; }
  finally { if (epoch === rdResults.epoch) { rdResults.loading = false; renderRdResults(); } }
}
async function rdPost(path, body) { return api(`/api/rd-results/${path}`, { method: 'POST', body: JSON.stringify(body) }); }
async function rdReadReceipt(operation) {
  const receipt = await api(`/api/rd-results/operations/${operation}`);
  // A preview receipt may also belong to a commit still in preflight. It is
  // not proof of rejection or cancellation, and must never enable resubmission.
  return receipt.state === 'preview' ? { ...receipt, state: 'outcome_unknown', reason: 'receipt_pending' } : receipt;
}
async function rdClick(event) {
  const filter = event.target.closest('[data-rd-filter]')?.dataset.rdFilter;
  if (filter && !rdResults.busy) {
    rdResults.filters.status = filter; rdResults.filters.page = 1; rdPersist(); return loadRdResults();
  }
  const operation = event.target.closest('[data-rd-operation]')?.dataset.rdOperation;
  const action = event.target.closest('[data-rd-action]')?.dataset.rdAction;
  if ((!action && !operation) || rdResults.busy) return;
  if (action === 'refresh') return loadRdResults();
  if (['previous','next'].includes(action)) { rdResults.filters.page = rdResults.data.page + (action === 'next' ? 1 : -1); rdPersist(); return loadRdResults(); }
  if (action === 'select') { rdResults.data.items.forEach(r => { const s = rdResults.remote[r.issue_id]?.status; if (s === 'pending' || (s === 'conflict' && rdResults.overwrite)) rdResults.selected.add(r.issue_id); }); return renderRdResults(); }
  const epoch = rdResults.epoch, scope = rdResults.baselines;
  rdResults.busy = true; rdResults.error = ''; renderRdResults();
  try {
    if (action === 'history' || operation) {
      const response = await api(`/api/rd-results/operations${operation ? '/' + operation : ''}`);
      if (epoch !== rdResults.epoch || state.activePage !== 'rd-results') return;
      if (operation) { rdResults.preview = response; rdRenderDialog(); $('#rdResultsDialog').showModal(); }
      else rdResults.operations = response.items;
      return;
    }
    const response = await rdPost(action, { baselines: scope, issue_ids: action === 'status' ? rdResults.data.items.map(r=>r.issue_id) : [...rdResults.selected], overwrite: rdResults.overwrite });
    if (epoch !== rdResults.epoch || state.activePage !== 'rd-results' || scope !== state.selectedBaselineIds.join(',')) return;
    if (action === 'status') { rdResults.remote = Object.fromEntries(response.items.map(r=>[r.issue_id,r])); rdResults.selected.clear(); }
    else { rdResults.preview = response; rdRenderDialog(); $('#rdResultsDialog').showModal(); }
  } catch (error) { if (epoch === rdResults.epoch) rdResults.error = error.message; }
  finally { rdResults.busy = false; renderRdResults(); }
}
function rdRenderDialog() {
  const p = rdResults.preview, dialog = $('#rdResultsDialog');
  if (!p) return;
  const scroll = dialog.querySelector('.trail-history-dialog-body')?.scrollTop || 0;
  const focusedAction = dialog.contains(document.activeElement) ? document.activeElement?.dataset.rdAction : '';
  const count = p.items.filter(r=>r.eligible).length;
  const outcomes = p.items.map(row => ({ row, result: p.results.find(r=>r.issue_id===row.issue_id) }));
  const counts = key => outcomes.filter(({row,result}) => row.eligible && (result?.state || 'unverified') === key).length;
  const overwritten = p.items.filter(r=>r.eligible && r.status === 'conflict').length;
  const preview = p.state === 'preview';
  dialog.innerHTML = `<div class="dialog-card"><h2 id="rdResultsDialogTitle">${preview ? rdText('确认标注上传','Confirm label upload') : rdText('标注上传结果','Label upload outcome')}</h2><div class="trail-history-dialog-body"><p>${rdText('仅更新 RD 结果；正确触发写入 Trail 为“成功”。','Updates only the RD result; correct trigger is stored as “成功” in Trail.')}</p><p>${preview ? rdText(`本次可上传 ${count} 条，其中覆盖已有结果 ${overwritten} 条。`, `${count} eligible; ${overwritten} will overwrite existing results.`) : rdText(`已核验 ${counts('verified')} 条 · 未确认 ${counts('unverified') + counts('intent')} 条 · 未执行 ${counts('not_attempted')} 条`, `${counts('verified')} verified · ${counts('unverified') + counts('intent')} unverified · ${counts('not_attempted')} not attempted`)}</p>
    <div class="rd-table-wrap" role="region" tabindex="0" aria-label="${rdText('上传明细，可横向滚动','Upload details; scroll horizontally')}"><table class="rd-table"><thead><tr><th>Issue</th><th>${rdText('上传前值','Value before upload')}</th><th>${rdText('上传值','New value')}</th>${preview ? '' : `<th>${rdText('读回值','Readback value')}</th>`}<th>${rdText('状态','Status')}</th></tr></thead><tbody>${outcomes.map(({row:r,result})=>`<tr><td>${escapeHtml(r.issue_id)}</td><td>${escapeHtml(rdLabel(r.current))}</td><td>${escapeHtml(rdLabel(r.desired))}</td>${preview ? '' : `<td>${escapeHtml(rdLabel(result?.observed))}</td>`}<td>${escapeHtml(rdStatus(result?.state || (preview || !r.eligible ? r.status : 'unverified')))}${result?.reason ? `<div class="muted">${escapeHtml(rdReason(result.reason))}</div>` : ''}</td></tr>`).join('')}</tbody></table></div>
    <p role="status">${escapeHtml(preview ? rdText('预览有效期 10 分钟；标注或远端值变化后需重新预览。','Preview expires in 10 minutes; changed labels or remote values require a new preview.') : rdStatus(p.state))}</p>${p.reason ? `<p>${escapeHtml(rdReason(p.reason))}</p>` : ''}<p>${rdText('操作编号','Operation ID')}: <code>${escapeHtml(p.id)}</code></p><p role="alert">${escapeHtml(rdResults.error)}</p></div><div class="dialog-actions">${rdButton('close',rdText('关闭','Close'), rdResults.busy)}${preview ? rdButton('commit',rdText('确认上传','Confirm upload'), rdResults.busy || !count || !rdResults.data?.write_enabled, 'primary') : rdButton('receipt',rdText('刷新本次结果','Refresh outcome'), rdResults.busy)}</div></div>`;
  dialog.oncancel = event => { if (rdResults.busy) event.preventDefault(); };
  dialog.querySelector('.trail-history-dialog-body').scrollTop = scroll;
  if (dialog.open && !rdResults.busy && (focusedAction || !dialog.contains(document.activeElement))) {
    (dialog.querySelector(`[data-rd-action="${focusedAction}"]`) || dialog.querySelector('[data-rd-action="receipt"]') || dialog.querySelector('[data-rd-action="close"]'))?.focus();
  }
  dialog.onclick = async event => {
    const action = event.target.closest('[data-rd-action]')?.dataset.rdAction;
    if (rdResults.busy) return;
    if (action === 'close') { dialog.close(); return; }
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
