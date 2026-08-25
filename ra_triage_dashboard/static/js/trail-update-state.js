/* Trail exclusion state, URL and remote-status projection helpers.
 *
 * This module is intentionally UI-framework-free.  It is loaded before
 * trail-update.js, which owns rendering and event bindings.
 */

function trailUpdatePreviewKey(runId = state.trailUpdate?.runId || "") {
  return `${String(runId || "").trim()}|${selectedBaselineQueryValue()}`;
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

function trailUpdateStatusMeta(status = "not_checked") {
  const key = String(status || "not_checked");
  const labels = {
    querying: ["查询中", "Checking", "is-querying", "Trail 查询尚未完成"],
    synced: ["已同步", "Synced", "is-synced", "排除标记与排除说明均与当前 Review 一致"],
    pending: ["待同步", "Pending", "is-pending", "排除标记或排除说明与当前 Review 不一致"],
    not_found: ["未找到", "Not found", "is-not-found", "Trail 未返回该 Issue"],
    query_failed: ["查询失败", "Query failed", "is-failed", "请刷新后重试"],
    not_checked: ["未检查", "Not checked", "is-not-checked", "当前环境未执行 Trail 查询"],
  };
  const [zh, en, className, detail] = labels[key] || labels.not_checked;
  return { key, label: uiText(zh, en), className, detail: uiText(detail, detail) };
}

function trailUpdateStatusCellMarkup(status = "not_checked") {
  const meta = trailUpdateStatusMeta(status);
  return `<span class="trail-update-state-badge ${meta.className}" title="${escapeHtml(meta.detail)}">${escapeHtml(meta.label)}</span><small>${escapeHtml(meta.detail)}</small>`;
}

function trailUpdateStatusSummary(data, items) {
  const counts = {};
  // A locally filtered/paged table must project its own status distribution;
  // the server aggregate remains useful only when callers have no item list.
  if (Array.isArray(items)) {
    items.forEach((item) => {
      const key = String(item?.trail_update_status || "not_checked");
      counts[key] = Number(counts[key] || 0) + 1;
    });
  } else {
    const provided = data?.trail_update_status_summary;
    if (provided && typeof provided === "object") {
      Object.entries(provided).forEach(([key, value]) => {
        const count = Number(value || 0);
        if (count > 0) counts[key] = count;
      });
    }
  }
  const entries = Object.entries(counts).filter(([, count]) => count > 0);
  const priority = ["querying", "query_failed", "pending", "not_found", "not_checked", "synced"];
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
