/** Runs independently of React so the first read overlaps the application download. */
export function coldStart({ base, flowJs, flowCss, evaluationJs, evaluationCss = [], overviewJs, overviewCss = [] }) {
  const root = new URL(base, location.href);
  if (root.origin !== location.origin) return;
  const path = location.pathname.replace(/\/$/, '');
  const query = new URLSearchParams(location.search);
  const state = window.__RA_SIM_STARTUP__ ||= {};
  const start = (receipt, url) => {
    if (receipt.claimed || receipt.read) return;
    receipt.url = url;
    receipt.startedAt = Date.now();
    receipt.read = fetch(url, { headers: { 'Content-Type': 'application/json' } })
      .then(async response => ({ ok: response.ok, status: response.status, text: await response.text() }));
    // The main application owns error presentation, including failures before it loads.
    void receipt.read.catch(() => {});
  };
  const assets = [];
  if (path === root.pathname + 'simulation') {
    if (state.claimed || state.read) return;
    const release = query.get('version') || '@current';
    start(state, root.pathname + 'api/dashboard/workflow/board?' + new URLSearchParams({ release, refresh: 'false' }));
    if (release !== '@current') assets.push([flowJs, flowCss]);
  } else if (query.get('basis') === 'auto-triage' && [root.pathname + 'overview', root.pathname + 'issues'].includes(path)) {
    const evaluation = state.evaluation ||= {};
    const release = query.get('release') || query.get('version') || (path.endsWith('/issues') ? '@stable' : '@current');
    const ctx = new URLSearchParams({ release });
    for (const [param, key] of [['profile', 'profile_id'], ['date_start', 'date_start'], ['date_end', 'date_end']]) {
      if (query.get(param)) ctx.set(key, query.get(param));
    }
    const api = root.pathname + 'api/dashboard/evaluation';
    start(evaluation.board ||= {}, api + '/board?' + ctx);
    start(evaluation.versions ||= {}, api + '/versions');
    assets.push([evaluationJs, evaluationCss]);
    if (path.endsWith('/overview')) {
      const comparison = new URLSearchParams(query.get('profile') ? { profile_id: query.get('profile') } : {});
      start(evaluation.comparison ||= {}, api + '/comparison?' + comparison);
      assets.push([overviewJs, overviewCss]);
    }
  } else return;
  const links = state.preloaded ||= {};
  for (const [js, css] of assets) for (const [rel, file] of [['modulepreload', js], ...css.map(file => ['preload', file])]) {
    if (!file || links[file]) continue;
    links[file] = true;
    const link = document.createElement('link');
    link.rel = rel;
    if (rel === 'preload') link.as = 'style';
    link.crossOrigin = '';
    link.href = new URL(file, root).href;
    document.head.appendChild(link);
  }
}

export function coldStartPlugin() {
  let base;
  return {
    name: 'sim-cold-start',
    apply: 'build',
    enforce: 'post',
    configResolved(config) { base = config.base; },
    generateBundle: {
      order: 'post',
      handler(_options, bundle) {
        const html = bundle['index.html'];
        if (html?.type !== 'asset' || typeof html.source !== 'string') throw new Error('Missing application HTML');
        const flow = Object.values(bundle).find(chunk => chunk.type === 'chunk' && chunk.facadeModuleId?.endsWith('/SimulationFlow.tsx'));
        if (!flow) throw new Error('Missing simulation flow chunk');
        const evaluation = Object.values(bundle).find(chunk => chunk.type === 'chunk' && chunk.facadeModuleId?.endsWith('/EvaluationWorkspace.tsx'));
        const overview = Object.values(bundle).find(chunk => chunk.type === 'chunk' && chunk.facadeModuleId?.endsWith('/Overview.tsx'));
        if (!evaluation || !overview) throw new Error('Missing evaluation overview chunks');
        const source = `;(${coldStart.toString()})(${JSON.stringify({ base, flowJs: flow.fileName, flowCss: [...flow.viteMetadata.importedCss],
          evaluationJs: evaluation.fileName, evaluationCss: [...evaluation.viteMetadata.importedCss],
          overviewJs: overview.fileName, overviewCss: [...overview.viteMetadata.importedCss] })});`;
        const id = this.emitFile({ type: 'asset', name: 'sim-startup.js', source });
        const path = base.replace(/\/$/, '') + '/' + this.getFileName(id);
        html.source = html.source.replace('</head>', `  <script async src="${path}"></script>\n  </head>`);
      },
    },
  };
}
