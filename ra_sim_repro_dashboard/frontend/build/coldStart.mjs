/** Runs independently of React so the first read overlaps the application download. */
export function coldStart({ base, flowJs, flowCss }) {
  const root = new URL(base, location.href);
  if (root.origin !== location.origin || location.pathname.replace(/\/$/, '') !== root.pathname + 'simulation') return;
  const state = window.__RA_SIM_STARTUP__ ||= {};
  if (state.claimed || state.read) return;
  const release = new URLSearchParams(location.search).get('version') || '@current';
  state.url = root.pathname + 'api/dashboard/workflow/board?' + new URLSearchParams({ release, refresh: 'false' });
  state.startedAt = Date.now();
  state.read = fetch(state.url, { headers: { 'Content-Type': 'application/json' } })
    .then(async response => ({ ok: response.ok, status: response.status, text: await response.text() }));
  // The main application owns error presentation, including failures before it loads.
  void state.read.catch(() => {});
  if (release === '@current') return;
  for (const [rel, file] of [['modulepreload', flowJs], ...flowCss.map(file => ['preload', file])]) {
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
        const source = `;(${coldStart.toString()})(${JSON.stringify({ base, flowJs: flow.fileName, flowCss: [...flow.viteMetadata.importedCss] })});`;
        const id = this.emitFile({ type: 'asset', name: 'sim-startup.js', source });
        const path = base.replace(/\/$/, '') + '/' + this.getFileName(id);
        html.source = html.source.replace('</head>', `  <script async src="${path}"></script>\n  </head>`);
      },
    },
  };
}
