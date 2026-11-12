/* RA Triage Workbench frontend entry.
 *
 * Source modules stay under static/js/*.js. The server joins them in MANIFEST
 * order once at startup, preserving classic-script globals without one network
 * request per source file. Product logic belongs in those modules.
 */
(() => {
  const CACHE_VERSION = "manual-triage-795";
  const base = window.__RA_TRIAGE_BASE__ || "";
  const script = document.createElement("script");
  script.src = `${base}/static/app-bundle.js?v=${CACHE_VERSION}`;
  script.async = false;
  document.body.appendChild(script);
})();
