/* RA Triage Workbench frontend entry.
 *
 * Domain logic lives under static/js/*.js and is loaded in MANIFEST order as
 * classic scripts (shared global scope). This preserves historical behavior
 * without a bundler or ES-module graph.
 *
 * Tests concatenate static/js/*.js via the MANIFEST; do not put product logic
 * back into this file. Load order is defined only by MODULES / MANIFEST —
 * filenames are domain names without numeric prefixes.
 */
(() => {
  const CACHE_VERSION = "manual-triage-270";
  const MODULES = [
    "core-base.js",
    "i18n-messages.js",
    "i18n.js",
    "routing.js",
    "issue-query.js",
    "format-api.js",
    "gt-sync.js",
    "session-config.js",
    "system-status.js",
    "runs.js",
    "run-comparison.js",
    "review-gallery.js",
    "work-split.js",
    "analysis.js",
    "detail-media.js",
    "review-draft.js",
    "review-history.js",
    "review-mentions.js",
    "review-tags.js",
    "review-form.js",
    "media-dialog.js",
    "batch-gateway.js",
    "batch-config.js",
    "batch.js",
    "import-refresh.js",
    "trail-update-state.js",
    "trail-update.js",
    "bind-bootstrap.js"
  ];

  const base = window.__RA_TRIAGE_BASE__ || "";
  // Preload all modules first so HTTP/1.1 can pipeline downloads before ordered
  // execution begins (async=false scripts still run in MODULES order).
  for (const name of MODULES) {
    const preload = document.createElement("link");
    preload.rel = "preload";
    preload.as = "script";
    preload.href = `${base}/static/js/${name}?v=${CACHE_VERSION}`;
    document.head.appendChild(preload);
  }
  // Insert with async=false so execution order matches MODULES even when
  // scripts are appended dynamically (HTML5 ordered script loading).
  for (const name of MODULES) {
    const script = document.createElement("script");
    script.src = `${base}/static/js/${name}?v=${CACHE_VERSION}`;
    script.async = false;
    document.body.appendChild(script);
  }
})();
