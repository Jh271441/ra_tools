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
  const CACHE_VERSION = "manual-triage-94";
  const MODULES = [
    "core-base.js",
    "routing.js",
    "format-api.js",
    "session-config.js",
    "system-status.js",
    "runs.js",
    "review-gallery.js",
    "work-split.js",
    "analysis.js",
    "detail-media.js",
    "review-form.js",
    "media-dialog.js",
    "batch.js",
    "import-refresh.js",
    "bind-bootstrap.js"
  ];

  const base = window.__RA_TRIAGE_BASE__ || "";
  // Insert with async=false so execution order matches MODULES even when
  // scripts are appended dynamically (HTML5 ordered script loading).
  for (const name of MODULES) {
    const script = document.createElement("script");
    script.src = `${base}/static/js/${name}?v=${CACHE_VERSION}`;
    script.async = false;
    document.body.appendChild(script);
  }
})();
