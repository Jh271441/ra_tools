/* detail-trail.js
 * Issue external links, RA Event dialog and bounded Trail metadata cache.
 * Classic script; shared globals are initialized before bind-bootstrap.js.
 */

function formatRaEventTimestamp(value) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return "—";
  const date = new Date(numeric);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleString(i18nLocale() === "en" ? "en-GB" : "zh-CN", {
        hour12: false, timeZone: "Asia/Shanghai",
      });
}

function formatRaEventRelativeTime(value, t0TimestampMs) {
  const timestamp = Number(value);
  const reference = Number(t0TimestampMs);
  if (
    !Number.isFinite(timestamp) || timestamp <= 0 ||
    !Number.isFinite(reference) || reference <= 0
  ) return "—";
  const deltaSeconds = (timestamp - reference) / 1000;
  if (Math.abs(deltaSeconds) < 0.0005) return "t0";
  const magnitude = Math.abs(deltaSeconds)
    .toFixed(3)
    .replace(/\.0+$/, "")
    .replace(/(\.\d*?)0+$/, "$1");
  return `t${deltaSeconds < 0 ? "−" : "+"}${magnitude}s`;
}

function renderRaEventRows(
  events,
  query = "",
  t0TimestampMs = state.raEventDialog.t0TimestampMs
) {
  const normalizedQuery = String(query || "").trim().toLowerCase();
  const rows = (Array.isArray(events) ? events : []).filter((item) => {
    if (!normalizedQuery) return true;
    return [item?.event, item?.value]
      .map((value) => String(value ?? "").toLowerCase())
      .some((value) => value.includes(normalizedQuery));
  });
  const body = $("#raEventTableBody");
  if (body) {
    body.innerHTML = rows
      .map((item) => {
        const timestamp = item?.timestamp;
        const playbackUrl = aresStudioUrl(
          state.raEventDialog.caseData,
          state.raEventDialog.trailUrl,
          Number(timestamp),
          { beforeMs: 1000, afterMs: 15000 }
        );
        const timeLink = (label) => playbackUrl && label !== "—"
          ? `<a class="ra-event-playback-link" href="${escapeHtml(playbackUrl)}" target="_blank" rel="noreferrer" data-ra-event-timestamp="${escapeHtml(timestamp)}">${escapeHtml(label)}</a>`
          : `<span data-i18n-title="ra_event.unavailable" title="${escapeHtml(t("ra_event.unavailable"))}">${escapeHtml(label)}</span>`;
        const copyButton = Number.isSafeInteger(Number(timestamp)) && Number(timestamp) > 0 && formatRaEventTimestamp(timestamp) !== "—"
          ? `<button class="detail-copy-id-button ra-event-copy-timestamp" type="button" data-copy-ra-event-timestamp="${escapeHtml(timestamp)}">
              <svg viewBox="0 0 20 20" aria-hidden="true"><rect x="7" y="6" width="9" height="10" rx="2"></rect><path d="M13 6V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"></path></svg>
            </button>`
          : "";
        return `<tr>
          <td>${escapeHtml(item?.event || "—")}</td>
          <td>${escapeHtml(item?.value ?? "—")}</td>
          <td class="ra-event-timestamp${copyButton ? " ra-event-copy-cell" : ""}">${timeLink(timestamp ?? "—")}</td>
          <td class="ra-event-relative-time${copyButton ? " ra-event-copy-anchor" : ""}">${copyButton}${timeLink(formatRaEventRelativeTime(timestamp, t0TimestampMs))}</td>
          <td class="ra-event-formatted-time" data-ra-event-timestamp="${escapeHtml(timestamp ?? "")}">${escapeHtml(formatRaEventTimestamp(timestamp))}</td>
        </tr>`;
      })
      .join("");
  }
  const empty = $("#raEventEmpty");
  if (empty) empty.hidden = rows.length > 0;
  refreshRaEventDialogLanguage();
  return rows.length;
}

function bindRaEventTimestampCopy() {
  const body = $("#raEventTableBody");
  if (!body || body.dataset.copyBound === "1") return;
  body.dataset.copyBound = "1";
  body.addEventListener("click", (event) => {
    const button = event.target.closest("[data-copy-ra-event-timestamp]");
    if (!button || !body.contains(button)) return;
    event.preventDefault();
    event.stopPropagation();
    void copyRaEventTimestamp(button);
  });
}

async function copyRaEventTimestamp(button) {
  const timestamp = button.dataset.copyRaEventTimestamp;
  if (!Number.isSafeInteger(Number(timestamp)) || Number(timestamp) <= 0 || formatRaEventTimestamp(timestamp) === "—") return;
  const context = state.raEventDialog;
  try {
    await copyTextToClipboard(timestamp);
    if (state.raEventDialog !== context || !$("#raEventDialog")?.open) return;
    context.copyStatus = { key: "ra_event.copied", timestamp };
    button.classList.add("is-copied");
    window.clearTimeout(button.copyFeedbackTimer);
    button.copyFeedbackTimer = window.setTimeout(() => button.classList.remove("is-copied"), 900);
  } catch (_) {
    if (state.raEventDialog !== context || !$("#raEventDialog")?.open) return;
    window.clearTimeout(button.copyFeedbackTimer);
    button.classList.remove("is-copied");
    context.copyStatus = { key: "ra_event.copy_failed" };
  }
  refreshRaEventDialogLanguage();
}

function refreshRaEventDialogLanguage() {
  const dialog = $("#raEventDialog");
  if (!dialog) return;
  const { events, issueId } = state.raEventDialog;
  const meta = $("#raEventDialogMeta");
  if (meta) meta.textContent = t(events.length === 1 ? "ra_event.meta_one" : "ra_event.meta", {
    n: events.length, issue: issueId,
  });
  const refreshButton = $("#raEventRefreshButton");
  if (refreshButton) refreshButton.disabled = state.raEventDialog.refreshState === "refreshing";
  const refreshStatus = $("#raEventRefreshStatus");
  if (refreshStatus) {
    refreshStatus.hidden = !state.raEventDialog.refreshState;
    refreshStatus.textContent = state.raEventDialog.refreshState
      ? t(`ra_event.${state.raEventDialog.refreshState}`) : "";
  }
  dialog.querySelectorAll(".ra-event-playback-link").forEach((link) => {
    const label = t("ra_event.open_window", { timestamp: link.dataset.raEventTimestamp });
    link.title = label;
    link.setAttribute("aria-label", label);
  });
  dialog.querySelectorAll(".ra-event-copy-timestamp").forEach((button) => {
    const label = t("ra_event.copy_timestamp", { timestamp: button.dataset.copyRaEventTimestamp });
    button.title = label;
    button.setAttribute("aria-label", label);
  });
  const copyStatus = $("#raEventCopyStatus");
  if (copyStatus) {
    const status = state.raEventDialog.copyStatus;
    copyStatus.hidden = !status;
    copyStatus.textContent = status ? t(status.key, status) : "";
  }
  dialog.querySelectorAll(".ra-event-formatted-time").forEach((cell) => {
    cell.textContent = formatRaEventTimestamp(cell.dataset.raEventTimestamp);
  });
}

async function refreshRaEventMetadata() {
  const context = state.raEventDialog;
  const dialog = $("#raEventDialog");
  if (!dialog?.open || !context.issueId || context.refreshState === "refreshing") return;
  context.refreshState = "refreshing";
  refreshRaEventDialogLanguage();
  const result = await startTrailDetailMetadata(context.issueId, 0, null, { refresh: true });
  if (state.raEventDialog !== context || !dialog.open) return;
  if (result?.status !== "ready" || result?.refresh_status === "unavailable") {
    context.refreshState = "refresh_failed";
    refreshRaEventDialogLanguage();
    return;
  }
  const caseData = context.caseData;
  caseData.external_links = result.external_links || {};
  caseData.trail_metadata_status = result.status;
  caseData.dashboard_should_exclude = result.dashboard_should_exclude;
  context.events = Array.isArray(caseData.external_links.ra_events) ? caseData.external_links.ra_events : [];
  context.trailUrl = safeUrl(caseData.external_links.ra_event_url);
  context.t0TimestampMs = reviewCaseT0TimestampMs(caseData);
  context.refreshState = "refreshed";
  const trailLink = $("#raEventTrailLink");
  if (trailLink) {
    trailLink.hidden = !context.trailUrl;
    trailLink.href = context.trailUrl || "#";
  }
  renderRaEventRows(context.events, $("#raEventSearchInput")?.value || "", context.t0TimestampMs);
  if (state.selectedCase === caseData) renderDetailExternalLinks(caseData);
  if (state.caseLabeling.caseData === caseData) {
    const links = $("#caseLabelingExternalLinks");
    if (links) {
      links.innerHTML = detailExternalLinksMarkup(caseData);
      bindDetailExternalLinks(caseData, links);
    }
  }
}

function bindRaEventDialogFocus() {
  const dialog = $("#raEventDialog");
  if (!dialog || dialog.dataset.escapeFocusBound === "1") return;
  dialog.dataset.escapeFocusBound = "1";
  const releaseTriggerFocus = () => {
    if (document.querySelector("dialog[open]")) return false;
    const active = document.activeElement;
    if (!active?.matches?.("[data-open-ra-event]")) return false;
    active.blur();
    return true;
  };
  // Native dialog dismissal restores its opener before the close event. Release
  // only that trigger, never a field the user has moved to in the meantime.
  dialog.addEventListener("close", () => window.requestAnimationFrame(releaseTriggerFocus));
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented || event.isComposing
        || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    if (releaseTriggerFocus()) {
      event.preventDefault();
      event.stopPropagation();
    }
  });
}

function openRaEventDialog(caseData) {
  if (!caseData) return;
  const externalLinks = caseData.external_links || {};
  const events = Array.isArray(externalLinks.ra_events) ? externalLinks.ra_events : [];
  state.raEventDialog = {
    issueId: String(caseData.issue_id || ""),
    caseData,
    events,
    trailUrl: safeUrl(externalLinks.ra_event_url),
    t0TimestampMs: reviewCaseT0TimestampMs(caseData),
  };
  const input = $("#raEventSearchInput");
  if (input) input.value = "";
  const trailLink = $("#raEventTrailLink");
  if (trailLink) {
    trailLink.hidden = !state.raEventDialog.trailUrl;
    trailLink.href = state.raEventDialog.trailUrl || "#";
  }
  renderRaEventRows(events, "", state.raEventDialog.t0TimestampMs);
  openDialog("raEventDialog");
}

function detailExternalLinksMarkup(caseData) {
  const issueUrl = safeUrl(caseData?.voyager_issue_url || caseData?.trail_url);
  const aresUrl = aresStudioUrl(caseData, issueUrl);
  const externalLinks = caseData?.external_links || {};
  const raRecordingUrl = safeUrl(externalLinks.ra_recording_url);
  const raEventUrl = safeUrl(externalLinks.ra_event_url);
  const disableRaSimulationUrl = safeUrl(externalLinks.disable_ra_simulation_url);
  const raEvents = Array.isArray(externalLinks.ra_events) ? externalLinks.ra_events : [];
  const aresLinkMarkup = aresUrl
    ? "<a class=\"detail-id detail-id-link detail-ares-link\" href=\"" + escapeHtml(aresUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"在 Ares Studio 中打开事件前后各 10 秒\">Ares Studio ↗</a>"
    : "";
  const raRecordingLinkMarkup = raRecordingUrl
    ? "<a class=\"detail-id detail-id-link detail-external-link\" href=\"" + escapeHtml(raRecordingUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"打开 RA 录屏" + (externalLinks.ra_task_id ? "：" + escapeHtml(externalLinks.ra_task_id) : "") + "\">RA 录屏 ↗</a>"
    : "";
  const raEventLinkMarkup = raEvents.length
    ? "<button class=\"detail-id detail-id-link detail-external-link detail-inline-button\" type=\"button\" data-open-ra-event aria-keyshortcuts=\"T\" title=\"查看 RA Event（" + raEvents.length + " 条，快捷键 T）\">RA Event · " + raEvents.length + " <kbd class=\"review-control-shortcut detail-external-shortcut\" aria-hidden=\"true\">T</kbd></button>"
    : raEventUrl
      ? "<a class=\"detail-id detail-id-link detail-external-link\" href=\"" + escapeHtml(raEventUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"在 Trail Issue 中查看 RA Event（" + Number(externalLinks.ra_event_count || 0) + " 条）\">RA Event ↗</a>"
      : "";
  const disableRaSimulationLinkMarkup = disableRaSimulationUrl
    ? "<a class=\"detail-id detail-id-link detail-external-link detail-disable-ra-link\" href=\"" + escapeHtml(disableRaSimulationUrl) + "\" target=\"_blank\" rel=\"noreferrer\" title=\"打开屏蔽 RA 指令仿真" + (externalLinks.disable_ra_simulation_task_id ? "：" + escapeHtml(externalLinks.disable_ra_simulation_task_id) : "") + "\">屏蔽 RA ↗</a>"
    : "";
  const pending = caseData?.trail_metadata_status === "pending" && !raRecordingUrl && !raEventUrl && !disableRaSimulationUrl;
  const pendingMarkup = pending
    ? '<span class="detail-external-status" data-trail-metadata-pending>Trail 信息加载中…</span>'
    : "";
  return aresLinkMarkup + raRecordingLinkMarkup + raEventLinkMarkup + disableRaSimulationLinkMarkup + pendingMarkup;
}

function bindDetailExternalLinks(caseData, root = $("#detailExternalLinks") || $("#caseLabelingExternalLinks")) {
  root?.querySelector("[data-open-ra-event]")?.addEventListener("click", () => {
    openRaEventDialog(caseData);
  });
}

function renderDetailExternalLinks(caseData) {
  const root = $("#detailExternalLinks");
  if (!root) return;
  const markup = detailExternalLinksMarkup(caseData);
  root.innerHTML = markup;
  root.hidden = !markup;
  bindDetailExternalLinks(caseData);
}

const TRAIL_DETAIL_CACHE_LIMIT = 200;
const TRAIL_DETAIL_CACHE_TTL_MS = 5 * 60 * 1000;
const TRAIL_DETAIL_FAILURE_TTL_MS = 30 * 1000;
const trailDetailMetadataCache = new Map();

function startTrailDetailMetadata(issueId, requestSeq, signal = null, { refresh = false } = {}) {
  if (signal?.aborted) return Promise.resolve(null);
  const path = "/api/cases/" + encodeURIComponent(issueId) + "/trail-metadata";
  const key = withBase(path);
  let entry = trailDetailMetadataCache.get(key);
  if (!entry || entry.expiresAt <= Date.now() || (refresh && !entry.refreshing)) {
    const previous = entry;
    // Navigation cancels only its consumer. Keep this bounded lookup alive so
    // returning to the Issue reuses the result, rather than restarting Trail.
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    entry = { expiresAt: Infinity, promise: null, refreshing: refresh };
    entry.promise = api(refresh ? path + "?refresh=true" : path, { signal: controller.signal, cache: "no-store" })
      .catch(() => null)
      .then(async (result) => {
        let valid = result?.issue_id === issueId ? result : null;
        if (refresh && valid?.status !== "ready" && previous) {
          const saved = await previous.promise;
          if (saved?.status === "ready") valid = { ...saved, refresh_status: "unavailable" };
        }
        const ready = valid?.status === "ready" || valid?.status === "disabled";
        entry.refreshing = false;
        entry.expiresAt = Date.now() + (ready && valid?.refresh_status !== "unavailable"
          ? TRAIL_DETAIL_CACHE_TTL_MS : TRAIL_DETAIL_FAILURE_TTL_MS);
        return valid;
      })
      .finally(() => window.clearTimeout(timeout));
    trailDetailMetadataCache.set(key, entry);
  }
  trailDetailMetadataCache.delete(key);
  trailDetailMetadataCache.set(key, entry);
  while (trailDetailMetadataCache.size > TRAIL_DETAIL_CACHE_LIMIT) {
    trailDetailMetadataCache.delete(trailDetailMetadataCache.keys().next().value);
  }
  // Callers enrich their own Case; never share mutable event arrays or links.
  return entry.promise.then((result) => signal?.aborted ? null : structuredClone(result));
}

function applyTrailDetailMetadata(result, issueId, requestSeq) {
  if (
    requestSeq !== state.caseRequestSeq ||
    state.selectedId !== issueId ||
    !state.selectedCase
  ) {
    return;
  }
  state.selectedCase.external_links = result?.external_links || {};
  state.selectedCase.trail_metadata_status = result?.status || "unavailable";
  const trailShouldExclude = result?.dashboard_should_exclude === true;
  state.selectedCase.trail_should_exclude = trailShouldExclude;
  const excludeInput = $("#reviewExcludeInput");
  const hasCurrentRunReview = reviewAnnotationsForCurrentRun(state.selectedCase).length > 0;
  const hasLocalDraft = Boolean(reviewDraftForCase(state.selectedCase));
  if (excludeInput && excludeInput.dataset?.caseExclusion !== "true" && trailShouldExclude && !hasCurrentRunReview && !hasLocalDraft && !state.reviewFormDirty) {
    // Trail's namespaced info marker is read-only here.  Checking the local
    // box is only a first-Review suggestion. An explicit Review value,
    // including false, is authoritative for its selected Run.
    excludeInput.checked = true;
  }
  renderDetailExternalLinks(state.selectedCase);
}
