/* Trail exclusion state, URL and remote-status projection helpers.
 *
 * This module is intentionally UI-framework-free.  It is loaded before
 * trail-update.js, which owns rendering and event bindings.
 */

function trailUpdatePreviewKey(runId = state.trailUpdate?.runId || "") {
  return `${String(runId || "").trim()}|${selectedBaselineQueryValue()}|${state.trailUpdate.view || "local"}`;
}

function trailAttributePreviewNeedsLoad(runId = state.trailUpdate?.runId || "") {
  const key = trailUpdatePreviewKey(runId);
  const cached = state.trailUpdate?.data;
  if (!cached || state.trailUpdate.previewKey !== key) return true;
  const writerEnabled = Boolean(
    state.config?.trail_attribute_update?.enabled
    && state.config?.trail_attribute_update?.review_write_enabled
  );
  return writerEnabled && cached.write_status === "disabled";
}

function trailUpdateEndpoint(runId, probeTrail = true, refresh = false) {
  const params = new URLSearchParams();
  if (runId) params.set("model_run_id", runId);
  const baselines = selectedBaselineQueryValue();
  if (baselines) params.set("baselines", baselines);
  if (state.trailUpdate.view === "reconciliation") params.set("reconciliation", "true");
  if (!probeTrail) params.set("probe_trail", "false");
  if (refresh) params.set("refresh", "true");
  return `/api/trail-attribute-update/preview?${params.toString()}`;
}

function trailUpdateStatusEndpoint(items = [], refresh = false) {
  const ids = [...new Set((items || [])
    .map((item) => String(item?.issue_id || "").trim())
    .filter(Boolean))];
  const params = new URLSearchParams();
  if (ids.length) params.set("issue_ids", ids.join(","));
  const digest = String(state.trailUpdate?.data?.payload_sha256 || "").trim();
  if (digest) params.set("payload_sha256", digest);
  if (refresh) params.set("refresh", "true");
  return `/api/trail-attribute-update/status?${params.toString()}`;
}

// Presentation groups are shared by badges, totals and filters. Raw API states stay intact.
function trailStatusGroup(status) {
  return ({reason_changed:"reason_update",reason_missing:"reason_update",excluded_keep_reason:"excluded",excluded_no_reason:"excluded",reconcile_excluded:"excluded",reconcile_not_excluded:"not_excluded",query_failed:"unconfirmed",not_found:"unconfirmed",pending:"unconfirmed",not_checked:"unconfirmed"})[status] || (["needs_exclusion","reason_update","synced","excluded","not_excluded","querying","unconfirmed"].includes(status) ? status : "unconfirmed");
}
function trailUpdateStatusMeta(status = "not_checked") {
  const key = String(status || "not_checked");
  const labels = {
    reason_update: ["理由待更新", "Update reason", "is-reason", "已排除；本地有新理由可更新或补充", "Already excluded; a local reason can be updated or added"],
    excluded: ["已排除", "Excluded", "is-excluded", "排除已生效；没有本地新理由，保留远端原文", "Exclusion is active; no new local reason, so keep the remote text"],
    not_excluded: ["未排除", "Not excluded", "is-not-checked", "远端未排除或未设置标记；核对视图只读", "Remote marker is false or unset; reconciliation is read-only"],
    unconfirmed: ["无法确认", "Unconfirmed", "is-failed", "查询未完成或失败，请刷新重试", "Not checked or the query failed; refresh to retry"],
    reconcile_excluded: ["已排除", "Excluded", "is-excluded", "仅供核对，不进入提交集合", "Read-only; excluded from submissions"],
    reconcile_not_excluded: ["未排除", "Not excluded", "is-not-checked", "历史记录不代表当前状态", "Historical membership is not the current state"],
    querying: ["查询中", "Checking", "is-querying", "等待 Trail 查询", "Waiting for Trail"],
    synced: ["已同步", "Synced", "is-synced", "排除标记与理由一致", "Exclusion and reason match"],
    pending: ["待同步", "Pending", "is-pending", "请刷新以查看具体差异", "Refresh to inspect differences"],
    needs_exclusion: ["待排除", "Awaiting exclusion", "is-pending", "Trail 尚无有效排除标记", "Trail has no active exclusion"],
    reason_changed: ["理由待更新", "Update reason", "is-reason", "排除已生效，仅理由不同", "Already excluded; only the reason differs"],
    reason_missing: ["理由待更新", "Update reason", "is-reason", "排除已生效，可补充理由", "Already excluded; a reason can be added"],
    excluded_keep_reason: ["已排除", "Excluded", "is-excluded", "本地理由为空，沿用 Trail 理由", "Local reason empty; keep the Trail reason"],
    excluded_no_reason: ["已排除", "Excluded", "is-excluded", "双方理由未填写", "Neither side has a reason"],
    not_found: ["无法确认", "Unconfirmed", "is-not-found", "Trail 未返回此 Issue，请刷新重试", "Issue missing from Trail; refresh to retry"],
    query_failed: ["无法确认", "Unconfirmed", "is-failed", "查询失败或预览过期，请刷新重试", "Query failed or preview expired; refresh to retry"],
    not_checked: ["未检查", "Not checked", "is-not-checked", "请刷新查询 Trail", "Refresh to check Trail"],
  };
  const [, , , detailZh, detailEn] = labels[key] || labels.not_checked;
  const groupKey = trailStatusGroup(key);
  const group = labels[groupKey] || labels.not_checked;
  return { key:groupKey, label:uiText(group[0], group[1]), className:group[2], detail:uiText(detailZh, detailEn) };
}

function trailUpdateStatusCellMarkup(status = "not_checked") {
  const meta = trailUpdateStatusMeta(status);
  return `<span class="trail-update-state-badge ${meta.className}" title="${escapeHtml(meta.detail)}">${escapeHtml(meta.label)}</span>`;
}

function trailUpdateStatusSummary(data, items) {
  items = (items || data?.items || []);
  const counts = {};
  // A locally filtered/paged table must project its own status distribution;
  // the server aggregate remains useful only when callers have no item list.
  if (Array.isArray(items)) {
    items.forEach((item) => {
      const key = trailStatusGroup(trailReasonState(item));
      counts[key] = Number(counts[key] || 0) + 1;
    });
  } else {
    const provided = data?.trail_update_status_summary;
    if (provided && typeof provided === "object") {
      Object.entries(provided).forEach(([key, value]) => {
        const count = Number(value || 0);
        if (count > 0) counts[trailStatusGroup(key)] = (counts[trailStatusGroup(key)] || 0) + count;
      });
    }
  }
  const entries = Object.entries(counts).filter(([, count]) => count > 0);
  const priority = ["needs_exclusion", "reason_update", "synced", "excluded", "not_excluded", "querying", "unconfirmed"];
  const primaryKey = priority.find((key) => counts[key]) || "not_checked";
  const primary = trailUpdateStatusMeta(primaryKey);
  const total = Object.values(counts).reduce((sum, count) => sum + Number(count || 0), 0);
  const detail = entries
    .sort(([a], [b]) => priority.indexOf(a) - priority.indexOf(b))
    .map(([key, count]) => `${count} ${trailUpdateStatusMeta(key).label}`)
    .join(" · ");
  const statusElement = $("#trailUpdateStatusSummary");
  if (statusElement) {
    const visualEntries = entries.length ? entries : [["not_checked", 0]];
    const segments = visualEntries.map(([key, count]) => {
      const meta = trailUpdateStatusMeta(key);
      const percent = total ? Math.round((Number(count) / total) * 1000) / 10 : 100;
      return `<span class="analysis-review-status-segment trail-status-${escapeHtml(meta.key)}" data-trail-update-status-key="${escapeHtml(meta.key)}" style="width:${percent}%" title="${escapeHtml(`${meta.label} · ${count} · ${percent}%`)}"></span>`;
    }).join("");
    const legend = visualEntries.map(([key, count]) => {
      const meta = trailUpdateStatusMeta(key);
      const percent = total ? Math.round((Number(count) / total) * 1000) / 10 : 0;
      return `<div class="analysis-review-status-legend-item trail-status-${escapeHtml(meta.key)}" data-trail-update-status-key="${escapeHtml(meta.key)}" role="listitem" tabindex="0" aria-label="${escapeHtml(`${meta.label}: ${count}, ${percent}%. ${meta.detail}`)}" title="${escapeHtml(meta.detail)}"><span class="analysis-review-status-swatch"></span><span class="analysis-review-status-legend-copy"><strong>${escapeHtml(meta.label)}</strong><small>${count} · ${percent}%</small></span></div>`;
    }).join("");
    statusElement.innerHTML = `<div class="analysis-review-status-bar" role="img" aria-label="${escapeHtml(detail || primary.label)}">${segments}</div><div class="analysis-review-status-legend" role="list">${legend}</div>`;
    statusElement.className = "analysis-review-status-chart analysis-review-status-visual trail-update-status-chart trail-update-status-visual trail-update-status-summary";
    statusElement.title = detail;
    statusElement.setAttribute("aria-label", detail || primary.label);
    if (!statusElement.dataset.hoverBound) {
      statusElement.dataset.hoverBound = "true";
      if (typeof bindAnalysisLinkedHover === "function") {
        bindAnalysisLinkedHover(statusElement, "[data-trail-update-status-key]", (node) => {
          const key = node.dataset.trailUpdateStatusKey;
          statusElement.querySelectorAll(`[data-trail-update-status-key="${CSS.escape(key)}"]`).forEach((peer) => peer.classList.add("is-hover"));
        });
      }
    }
  }
  return counts;
}

function trailUpdateSourceRun(model = {}, data = {}, item = {}) {
  const runId = String(model?.run_id || "").trim();
  const selectedRun = data?.selected_run || {};
  const knownRun = (state.modelRuns || []).find((run) => String(run?.id || "") === runId) || {};
  const selected = String(selectedRun.id || "") === runId ? selectedRun : {};
  const selectedBaselineIds = Array.isArray(data?.baseline_ids)
    ? data.baseline_ids : (Array.isArray(data?.baselines) ? data.baselines : []);
  const baselineId = String(item?.baseline_id || "").trim()
    || (selectedBaselineIds.length === 1 ? String(selectedBaselineIds[0]) : "");
  const name = knownRun.name || selected.name || runId || uiText("未绑定 Run", "Unbound Run");
  const source = knownRun.source_name || selected.source_name || "";
  const version = knownRun.source_sha256
    ? `v${String(knownRun.source_sha256).slice(0, 10)}`
    : (knownRun.schema_version || selected.schema_version || "");
  const label = baselineId || uiText("未标记", "Unassigned");
  return { label, name, source, version, runId, title: [label, name, source, version, item?.baseline_scope].filter(Boolean).join(" · ") };
}
