// Durable completion and live execution use separate evidence and clocks.
function cronPlanningTextNodes(text) {
  const known = text.status === 'ready';
  const pipeline = text.pipeline || {}, runtime = pipeline.runtime || {};
  const observed = !dailyCronState.error && runtime.status === 'ready';
  const selected = text.selected;
  const terminal = (text.collected || 0) + (text.partial_source || 0) + (text.failed || 0);
  const fallback = known && [selected, terminal, text.pending || 0].every(v => Number.isInteger(v) && v >= 0) && terminal + (text.pending || 0) <= selected;
  const savedStage = { total: selected, completed: terminal, running: 0, blocked: 0, state: selected > 0 && terminal === selected ? 'complete' : 'pending' };
  const definitions = [
    ['text-input', uiText('目标登记', 'Register targets'), uiText('准确 Issue / trip / 时间', 'Exact Issue / trip / time')],
    ['text-export', uiText('Orion 文本采集', 'Collect text on Orion'), 'PlanningDebug'],
    ['text-verify', uiText('文字验收', 'Validate text'), uiText('身份 · 原文 · 时序', 'Identity · Raw · Timing')],
    ['text-index', uiText('索引发布', 'Publish index'), 'Issue ID + timestamp'],
    ['text-recover', uiText('按需恢复', 'Recover if needed'), uiText('复用已完成窗口', 'Reuse saved windows')],
    ['text-source', uiText('源缺口留证', 'Record source gaps'), uiText('有效帧和异常均保留', 'Keep valid frames and errors')]
  ];
  const labels = {
    complete: uiText('已完成', 'Complete'), running: uiText('运行中', 'Running'),
    pending: uiText('尚未开始 · 自动接续', 'Not started · Resumes automatically'),
    blocked: uiText('待处理 · 保留断点', 'Needs attention · Checkpoint saved'),
    unknown: uiText('状态待核实', 'Awaiting status evidence')
  };
  return definitions.map(([id, label, detail], index) => {
    let receipt = pipeline.stages?.[id];
    // Older servers still provide validated capture counts; these prove saved
    // work, never a live worker or an optional recovery attempt.
    if (!receipt && fallback && index < 4) receipt = { ...savedStage };
    if (!receipt && fallback && id === 'text-source') {
      const count = (text.partial_source || 0) + (text.failed || 0);
      receipt = { total: count, completed: count, running: 0, blocked: 0, state: count ? 'complete' : 'not_required' };
    }
    const valid = known && receipt && ['total', 'completed', 'running', 'blocked'].every(k => Number.isInteger(receipt[k]) && receipt[k] >= 0)
      && receipt.completed + receipt.running + receipt.blocked <= receipt.total;
    let phase = valid ? receipt.state : 'unknown';
    if (phase === 'complete' && (receipt.total === 0 || receipt.completed !== receipt.total)) phase = 'unknown';
    if (phase === 'running' && (!observed || !receipt.running)) phase = 'unknown';
    const status = { complete: 'success', running: 'running', pending: 'pending', blocked: 'failed', not_required: 'skipped' }[phase] || 'unknown';
    let stateLabel = labels[phase] || labels.unknown;
    if (phase === 'not_required') stateLabel = id === 'text-recover' ? uiText('当前无待恢复项', 'No recovery pending') : uiText('当前无源异常', 'No source issues');
    if (id === 'text-export' && phase === 'pending' && runtime.queued) stateLabel = uiText('已排队 · 等待 Orion', 'Queued · Awaiting Orion');
    if (id === 'text-verify' && phase === 'pending' && runtime.awaiting_result) stateLabel = uiText('等待小结果验收', 'Awaiting result validation');
    if (id === 'text-index' && phase === 'complete' && text.failed) stateLabel = uiText('已发布 · 源异常已留证', 'Published · Source errors recorded');
    else if (id === 'text-index' && phase === 'complete' && text.partial_source) stateLabel = uiText('已发布 · 源缺口已留证', 'Published · Source gaps recorded');
    const rows = [
      [uiText('已完成 / 阶段目标', 'Completed / Stage targets'), valid ? `${receipt.completed} / ${receipt.total}` : '—'],
      [uiText('完成依据', 'Completion evidence'), id === 'text-input' ? uiText('同一 Issue / trip / 时间的持久登记或已验收结果', 'Durable registration or validated saved results for the same Issue / trip / time') : uiText('同一 Issue / trip / 时间的已验收持久回执；进程退出不清空', 'Validated saved receipts for the same Issue / trip / time; retained after process exit')],
      [uiText('自动接续', 'Automatic continuation'), pipeline.durable_queue === 'ready' ? uiText('调度器先对账已有 Job 和结果，只接续未完成项；已完成窗口复用', 'Reconcile existing jobs and results, resume unfinished work, and reuse completed windows') : uiText('调度回执暂不可用；已完成的保存结果仍保留', 'Scheduling evidence is unavailable; completed saved results remain valid')]
    ];
    if (id === 'text-export') rows.push(
      [uiText('当前运行 / 排队', 'Running / Queued now'), observed ? `${runtime.running || 0} / ${runtime.queued || 0}` : '—'],
      [uiText('Orion 全局并发上限', 'Global Orion concurrency limit'), runtime.max_concurrency ?? '—'],
      [uiText('资源监督', 'Resource limits'), uiText('每窗口 512MiB / 4GiB / 120秒，累计600秒；与媒体独立调度', '512MiB / 4GiB / 120s per window, 600s total; scheduled independently of media')]
    );
    if (id === 'text-index' || id === 'text-source') rows.push(
      [uiText('真实有帧 / 同批目标', 'With actual frames / Same cohort'), known ? `${text.with_frames} / ${selected}` : '—'],
      [uiText('完整 / 源缺口 / 源失败', 'Complete / Source gaps / Source failures'), known ? `${text.collected} / ${text.partial_source} / ${text.failed}` : '—'],
      [uiText('数据质量', 'Data quality'), uiText('阶段完成表示处理和留证结束；源缺口仍保留，源失败不伪造为成功数据', 'Stage completion means processing and evidence are saved; source gaps and failures retain their original meaning')]
    );
    if (runtime.observed_at) rows.push([uiText('运行观测 · CST', 'Runtime observed · CST'), cronTime(runtime.observed_at)]);
    if (dailyCronState.error || runtime.status === 'stale') rows.push([uiText('观测状态', 'Observation status'), uiText('运行观测过期；已完成回执仍有效', 'Runtime observation is stale; saved completion receipts remain valid')]);
    const progress = phase === 'not_required' ? null : cronTaskProgress(valid ? receipt.completed : null, valid ? receipt.total : null, {
      stale: Boolean(dailyCronState.error), label: uiText('按同批阶段回执计数', 'Same-cohort stage receipts')
    });
    return { id, data: { label, detail, status, stateLabel, progress, rows, issues: [] } };
  });
}
