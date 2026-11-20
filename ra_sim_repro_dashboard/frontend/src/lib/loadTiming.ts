type Stage = 'board' | 'flow';
const queued = new Set<Stage>();

/** Local, opt-in diagnostics. No telemetry, persistence, or recurring observer. */
export function recordLoadStage(stage: Stage) {
  if (new URLSearchParams(location.search).get('perf') !== '1' || queued.has(stage)) return;
  queued.add(stage);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const root = document.documentElement;
    const timing = JSON.parse(root.dataset.simLoad || '{}');
    timing[stage] = Math.round(performance.now());
    timing.paint = performance.getEntriesByType('paint').map(entry => ({ name: entry.name, start: Math.round(entry.startTime) }));
    timing.resources = (performance.getEntriesByType('resource') as PerformanceResourceTiming[])
      .filter(entry => new URL(entry.name).pathname.startsWith(import.meta.env.BASE_URL))
      .map(entry => ({ url: new URL(entry.name).pathname + new URL(entry.name).search,
        start: Math.round(entry.startTime), end: Math.round(entry.responseEnd), bytes: entry.transferSize }));
    root.dataset.simLoad = JSON.stringify(timing);
  }));
}
