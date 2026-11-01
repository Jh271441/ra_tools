/* Issue-bound planning facts; intentionally independent of Model Run Reason. */
function planningConstraintAt(frames, timestamp, tolerance = 150) {
  // Hold the latest published planning message, never look ahead in time.
  const frame = frames.filter(item => Number.isFinite(item.timestamp_ms) && item.timestamp_ms <= timestamp)
    .reduce((best, item) => !best || item.timestamp_ms > best.timestamp_ms ? item : best, null);
  return frame && timestamp - frame.timestamp_ms <= tolerance ? frame : null;
}

function bindPlanningConstraint(player, video, getPosition = () => video.currentTime) {
  const trigger = player.querySelector('[data-planning-constraint]');
  if (!trigger) return { dispose() {}, refresh() {} };
  const issueId = player.dataset.planningIssue;
  const panel = document.createElement('section');
  panel.className = 'planning-constraint-panel';
  panel.hidden = true;
  panel.tabIndex = -1;
  panel.setAttribute('role', 'dialog');
  panel.id = `planning-constraint-${issueId}-${Math.random().toString(36).slice(2)}`;
  trigger.setAttribute('aria-controls', panel.id);
  panel.innerHTML = `<div class="planning-constraint-heading"><strong data-pc-title></strong><button type="button" class="button button-quiet" data-pc-close>×</button></div>
    <div class="planning-constraint-identity" data-pc-identity>
      <div class="planning-constraint-identity-heading" data-pc-identity-heading><span data-pc-id-label></span><button type="button" class="button button-quiet" data-pc-copy></button></div>
      <div class="planning-constraint-value" data-pc-value></div>
      <dl class="planning-constraint-object" data-pc-facts><dt><span class="planning-constraint-object-symbol" aria-hidden="true">ID</span><span data-pc-object-label></span></dt><dd data-pc-object-value></dd></dl>
      <button type="button" class="button button-quiet" data-pc-retry hidden></button>
    </div>
    <details class="planning-constraint-raw" data-pc-details><summary data-pc-summary><span data-pc-summary-label></span><span class="planning-constraint-disclosure" aria-hidden="true">⌄</span></summary><pre data-pc-raw></pre></details>`;
  // Keep the nonmodal panel in its player's top layer when media is expanded.
  (player.closest('dialog') || document.body).append(panel);
  const el = key => panel.querySelector(`[data-pc-${key}]`);
  const setText = (key, value) => { if (el(key).textContent !== value) el(key).textContent = value; };
  let open = false, disposed = false, timer = null, controller = null, requestKey = null;
  let epoch = 0, copyValue = '', copiedUntil = 0;
  const cache = new Map();
  // Text follows the timeline's target, including t0 before video metadata and
  // queued seeks. Reading these small facts does not require a decoded frame.
  const offset = () => Math.round((getPosition() + Number(player.dataset.startOffsetSec || 0)) * 1000);
  const place = () => {
    if (!open) return;
    const view = window.visualViewport;
    const left = view?.offsetLeft || 0, top = view?.offsetTop || 0;
    const width = view?.width || window.innerWidth, height = view?.height || window.innerHeight;
    const rect = trigger.getBoundingClientRect();
    panel.style.maxWidth = `${Math.max(0, width - 24)}px`;
    const above = rect.top - top - 20;
    panel.style.maxHeight = `${Math.max(0, Math.min(height - 24, above >= 160 ? above : height - 24))}px`;
    const bounds = panel.getBoundingClientRect();
    panel.style.left = `${Math.max(left + 12, Math.min(rect.left, left + width - bounds.width - 12))}px`;
    panel.style.top = `${Math.max(top + 12, Math.min(rect.top - bounds.height - 8, top + height - bounds.height - 12))}px`;
  };
  const words = () => {
    const title = uiText('规划约束', 'Planning constraint');
    trigger.querySelector('[data-pc-trigger-label]').textContent = title;
    trigger.setAttribute('title', uiText('展开或收起规划约束（G）', 'Toggle planning constraint (G)'));
    el('title').textContent = title;
    panel.setAttribute('aria-label', title);
    el('close').setAttribute('aria-label', uiText('关闭规划约束', 'Close planning constraint'));
    el('copy').textContent = Date.now() < copiedUntil ? uiText('已复制', 'Copied') : uiText('复制 ID', 'Copy ID');
    el('id-label').textContent = uiText('当前主导约束', 'Current dominant constraint');
    el('object-label').textContent = uiText('对象 ID', 'Object ID');
    el('retry').textContent = uiText('重试', 'Retry');
    el('summary-label').textContent = uiText('原文', 'Raw text');
  };
  const fetchWindow = async bucket => {
    if (requestKey === bucket || disposed || !open) return;
    controller?.abort();
    const abort = new AbortController();
    controller = abort;
    requestKey = bucket;
    const generation = ++epoch;
    const timeout = window.setTimeout(() => abort.abort(), 15000);
    try {
      const response = await fetch(withBase(`/api/cases/${encodeURIComponent(issueId)}/planning-constraints?offset_ms=${bucket * 8000}`),
        { signal: abort.signal, credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) throw new Error('planning request failed');
      const data = await response.json();
      if (disposed || !open || generation !== epoch) return;
      if (data.issue_id && data.issue_id !== issueId) throw new Error('issue mismatch');
      if (data.bucket != null && data.bucket !== bucket) throw new Error('window mismatch');
      const previous = cache.get(bucket);
      const firstRequest = previous?.firstRequest || Date.now();
      if (['loading', 'busy'].includes(data.status) && Date.now() - firstRequest > 130000) data.status = 'error';
      cache.set(bucket, { ...data, firstRequest, retryAt: Date.now() + 2000 });
      while (cache.size > 32) cache.delete(cache.keys().next().value);
    } catch (error) {
      if (!disposed && open && generation === epoch) cache.set(bucket, {status: 'error'});
    } finally {
      window.clearTimeout(timeout);
      if (generation === epoch) requestKey = null;
    }
  };
  const refresh = () => {
    words();
    if (!open || disposed) return;
    const relative = offset(), bucket = Math.floor(relative / 8000);
    const data = cache.get(bucket);
    const pending = !data || ['loading', 'busy'].includes(data.status);
    if (pending && (!data?.retryAt || Date.now() >= data.retryAt)) void fetchWindow(bucket);
    // At most one adjacent window warms while the open player is playing.
    // Paused/closed players never scan the rest of an Issue.
    if (data?.status === 'ready' && !video.paused && requestKey === null && !cache.has(bucket + 1)
        && (bucket + 1) * 8000 < (Number(player.dataset.startOffsetSec) + video.duration) * 1000) void fetchWindow(bucket + 1);
    const frame = data?.status === 'ready' && Number.isFinite(data.anchor_ms)
      ? planningConstraintAt(data.frames || [], data.anchor_ms + relative, data.tolerance_ms || 150) : null;
    copyValue = frame?.status === 'ready' ? String(frame.constraint_id || '') : '';
    let message = uiText('当前时刻无匹配规划帧', 'No matching planning frame at this time');
    if (pending) message = data?.status === 'busy'
      ? uiText('规划数据读取中，请稍候…', 'Planning reader is busy; please wait…')
      : uiText('正在读取当前时段规划数据…', 'Loading planning data for this time window…');
    else if (data.status === 'error') message = uiText('规划数据读取失败，请重试', 'Could not load planning data. Retry.');
    else if (data.status === 'unavailable') message = uiText('暂无可用规划数据', 'Planning data unavailable');
    else if (frame?.status === 'no_constraint') message = uiText('当前规划帧无主导约束', 'No dominant constraint in this planning frame');
    else if (frame?.status === 'unresolved') message = uiText('当前规划帧无法确定选中约束', 'Selected constraint unresolved in this planning frame');
    setText('value', copyValue || message);
    el('value').classList.toggle('is-raw-id', Boolean(copyValue));
    el('copy').hidden = !copyValue;
    el('retry').hidden = data?.status !== 'error';
    el('identity-heading').hidden = !copyValue;
    el('identity').classList.toggle('is-ready', Boolean(copyValue));
    el('facts').hidden = !copyValue;
    const objectId = copyValue && Number.isSafeInteger(frame?.object_id) ? frame.object_id : null;
    setText('object-value', objectId === null ? uiText('未提供', 'Not provided') : String(objectId));
    el('object-value').classList.toggle('is-missing', objectId === null);
    el('details').hidden = !frame?.raw;
    setText('raw', frame?.raw || '');
    place();
  };
  const close = (focus = false) => {
    open = false; panel.hidden = true; trigger.setAttribute('aria-expanded', 'false');
    window.clearInterval(timer); timer = null;
    ++epoch; controller?.abort(); requestKey = null;
    if (focus) trigger.focus({preventScroll: true});
  };
  const toggle = () => {
    if (open) { close(); return; }
    open = true; panel.hidden = false; trigger.setAttribute('aria-expanded', 'true');
    refresh(); timer = window.setInterval(refresh, 100);
    panel.focus({preventScroll: true});
  };
  const outside = event => {
    if (open && !panel.contains(event.target) && !player.querySelector('.bev-video-controls').contains(event.target)) close();
  };
  const keyboard = event => {
    if (disposed || event.defaultPrevented || isImeComposing(event)
        || event.ctrlKey || event.metaKey || event.altKey) return;
    if (open && event.key === 'Escape') {
      event.preventDefault(); event.stopPropagation(); close(true); return;
    }
    const target = event.target instanceof Element ? event.target : null;
    const editable = target?.closest('input, textarea, select, .ui-select, [contenteditable]:not([contenteditable="false"]), [role="textbox"]');
    if (!event.shiftKey && String(event.key).toLowerCase() === 'g') {
      if (event.repeat || editable || trigger.disabled || !trigger.getClientRects().length) return;
      // Only the visible player in the active dialog owns this shortcut. The
      // inline player remains mounted underneath expanded media and other dialogs.
      const dialog = document.querySelector('dialog[open]');
      if (dialog ? !dialog.contains(player) : player.closest('dialog')) return;
      if (document.querySelector('.review-dropdown[open], .ui-select.is-open, .review-status-picker.is-open, .detail-media-picker.is-open')) return;
      event.preventDefault(); event.stopPropagation();
      toggle();
      if (!open) trigger.focus({preventScroll: true});
      return;
    }
    // The trigger is a button, and the panel can live outside the player. Both
    // otherwise miss its keyboard handler. Reuse the owner's actual seek
    // controls so step size, seek coalescing and frame readiness stay shared.
    if (!target || event.shiftKey || !['ArrowLeft', 'ArrowRight'].includes(event.key)
        || !(trigger.contains(target) || (open && panel.contains(target)))
        || editable) return;
    const direction = event.key === 'ArrowLeft' ? -1 : 1;
    const control = player.querySelector(`[data-video-jump="${direction}"]`);
    if (!control || control.disabled) return;
    event.preventDefault(); event.stopPropagation();
    control.click();
    player.focus({preventScroll: true});
  };
  trigger.addEventListener('click', toggle);
  el('close').addEventListener('click', () => close(true));
  el('retry').addEventListener('click', () => {cache.delete(Math.floor(offset() / 8000)); refresh();});
  el('copy').addEventListener('click', async () => {
    const value = copyValue;
    if (!value) return;
    try { await navigator.clipboard.writeText(value); copiedUntil = Date.now() + 1600; words(); }
    catch (_) { showToast(uiText('复制失败，请选中 ID 复制', 'Copy failed. Select the ID to copy.'), true); }
  });
  document.addEventListener('pointerdown', outside);
  document.addEventListener('keydown', keyboard, true);
  refresh();
  return { refresh, dispose() {
    disposed = true; close(); panel.remove();
    document.removeEventListener('pointerdown', outside);
    document.removeEventListener('keydown', keyboard, true);
    trigger.removeEventListener('click', toggle);
  }};
}
