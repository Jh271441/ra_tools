/* A read-only entry to existing combined tasks; never creates a labeling copy. */
const labelingCombinedTasks = { items: [], actor: '', loaded: false, error: false, seq: 0 };

function labelingCombinedTaskHref(item) {
  return reviewAssignmentBatchHref(item, 'review');
}

function labelingCombinedTaskActor() {
  return JSON.stringify([state.session?.username, state.session?.verified, state.session?.access_role]);
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
  const active = list.contains(document.activeElement) ? document.activeElement : null;
  const focused = active?.closest('[data-review-assignment-batch]')?.dataset.reviewAssignmentBatch;
  const focusedHref = active?.getAttribute('href');
  list.dataset.signature = signature;
  list.innerHTML = data.items.map(item => {
    const detailHref = `${withBase('/review-assignments')}?${new URLSearchParams({ lifecycle: 'current', split: item.split_id })}`;
    return renderReviewAssignmentBatch(item, { detailHref });
  }).join('') || (data.loaded ? `<div class="review-assignment-empty">${escapeHtml(uiText('暂无当前有效的联合复核任务。', 'No active combined review tasks.'))}</div>` : '');
  if (focused && focusedHref) [...list.querySelectorAll('[data-review-assignment-batch]')]
    .find(card => card.dataset.reviewAssignmentBatch === focused)
    ?.querySelectorAll('a').forEach(link => {
      if (link.getAttribute('href') === focusedHref) link.focus({ preventScroll: true });
    });
}

async function loadLabelingCombinedTasks() {
  const data = labelingCombinedTasks;
  const actor = labelingCombinedTaskActor();
  const seq = ++data.seq;
  if (data.actor !== actor) {
    data.items = []; data.loaded = false; data.error = false; data.actor = actor;
  }
  renderLabelingCombinedTasks();
  const current = () => seq === data.seq && actor === labelingCombinedTaskActor();
  try {
    // Same cross-dataset discovery and progress projection as Review assignments.
    // The creation form's baseline must not hide already assigned work.
    const params = new URLSearchParams({ limit: '100', lifecycle: 'current', group_by_version: 'true', version_only: 'false' });
    const result = await api(`/api/cases/work-splits?${params}`);
    if (!current()) return;
    data.items = (result.items || []).filter(item =>
      item.workflow_mode === 'model_review_and_case_label' && reviewAssignmentCanReview(item));
    data.loaded = true; data.error = false;
  } catch (_) {
    if (!current()) return;
    data.error = true;
  }
  renderLabelingCombinedTasks();
}
