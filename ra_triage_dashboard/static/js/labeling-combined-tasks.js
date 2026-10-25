/* A read-only entry to existing combined tasks; never creates a labeling copy. */
const labelingCombinedTasks = { items: [], scope: '', loaded: false, error: false, seq: 0 };

function labelingCombinedTaskHref(item) {
  if (item.appendable) {
    const reviewer = state.session?.verified ? String(state.session.username || '').toLowerCase() : '';
    const own = (item.members || []).some(person => person.username.toLowerCase() === reviewer);
    return pageUrl('version-datasets', { dataset: item.dataset_id, mode: 'targets',
      assignee: own ? reviewer : '', review_status: 'pending' });
  }
  return reviewAssignmentBatchHref(item, 'review');
}

function renderLabelingCombinedTasks() {
  const list = $('#labelingCombinedTaskList');
  if (!list) return;
  const data = labelingCombinedTasks;
  const count = $('#labelingCombinedTaskCount');
  if (count) count.textContent = data.loaded ? String(data.items.length) : '—';
  const status = $('#labelingCombinedTaskStatus');
  if (status) status.textContent = data.error
    ? uiText('联合任务加载失败，请重试。', 'Could not load combined tasks. Retry.')
    : !data.loaded ? uiText('加载中…', 'Loading…') : '';
  // Keep existing card and link nodes on unchanged polls, including focus/scroll.
  const signature = JSON.stringify([data.items, data.loaded, state.uiLanguage,
    state.session?.username, state.session?.verified]);
  if (list.dataset.signature === signature) return;
  const focused = document.activeElement?.closest('[data-combined-task-link]')?.dataset.combinedTaskLink;
  list.dataset.signature = signature;
  list.innerHTML = data.items.map(item => {
    const total = Number(item.total || 0);
    const percent = total ? Math.round(Number(item.labeled || 0) * 100 / total) : 0;
    const name = item.appendable && item.release_family
      ? `${item.release_family.slice(4)} · ${uiText('版本联合复核', 'Version combined review')}` : item.name;
    return `<article class="intent-experiment-item case-experiment-item labeling-combined-task">
      <div><h4>${escapeHtml(name)}</h4><div class="intent-experiment-meta">${escapeHtml(item.appendable
        ? uiText('当前版本目标集', 'Current version targets') : uiText('联合复核任务', 'Combined review task'))} · ${escapeHtml(uiText(`${item.member_count} 个案例`, `${item.member_count} ${Number(item.member_count) === 1 ? 'case' : 'cases'}`))}</div></div>
      <a class="button button-quiet" data-combined-task-link="${escapeHtml(item.split_id)}" href="${escapeHtml(labelingCombinedTaskHref(item))}">${escapeHtml(uiText('继续联合复核', 'Continue combined review'))}</a>
      <div class="labeling-combined-counts">
        <span>${escapeHtml(uiText('标注', 'Labels'))} <b>${item.labeled}/${total}</b></span>
        <span>${escapeHtml(uiText('模型复核', 'Model review'))} <b>${item.reviewed}/${total}</b></span>
        <span>${escapeHtml(uiText('联合完成', 'Both complete'))} <b>${item.completed}/${total}</b></span>
      </div>
      <div class="intent-experiment-progress"><span class="intent-experiment-progress-track"><i class="is-complete" style="width:${percent}%"></i></span><small>${percent}% ${escapeHtml(uiText('标注', 'labeled'))}</small></div>
      <div class="labeling-combined-people">${(item.members || []).map(person => `<span><strong>${escapeHtml(person.username)}</strong><span>${escapeHtml(uiText('标注', 'Labels'))} ${person.labeled}/${person.total} · ${escapeHtml(uiText('联合', 'Both'))} ${person.completed}/${person.total}</span></span>`).join('')}</div>
    </article>`;
  }).join('') || (data.loaded ? `<p class="quiet-meta">${escapeHtml(uiText('当前范围暂无联合复核任务。', 'No combined review tasks in this scope.'))}</p>` : '');
  if (focused) [...list.querySelectorAll('[data-combined-task-link]')]
    .find(link => link.dataset.combinedTaskLink === focused)?.focus({ preventScroll: true });
}

async function loadLabelingCombinedTasks() {
  const data = labelingCombinedTasks;
  const scope = selectedBaselineQueryValue();
  const actor = String(state.session?.username || '');
  const seq = ++data.seq;
  if (data.scope !== `${actor}:${scope}`) {
    data.items = []; data.loaded = false; data.error = false; data.scope = `${actor}:${scope}`;
  }
  renderLabelingCombinedTasks();
  const current = () => seq === data.seq && scope === selectedBaselineQueryValue()
    && actor === String(state.session?.username || '');
  try {
    const result = await api(`/api/labeling/combined-tasks?${new URLSearchParams({ baselines: scope })}`);
    if (!current()) return;
    data.items = result.items || []; data.loaded = true; data.error = false;
  } catch (_) {
    if (!current()) return;
    data.error = true;
  }
  renderLabelingCombinedTasks();
}
