import { $ } from "./state.js";
import { escapeHtml, formatEpoch } from "./utils.js";

export function renderDetails(payload) {
  const record = payload.record || {};
  const summary = payload.summary || {};
  const ifx = record.ifx || {};
  const mapping = ifx.ifx_mapping || {};
  const apply = record.apply_handoff || {};
  const commands = payload.commands || {};
  const errors = record.errors || [];

  const artifacts =
    Object.entries(mapping)
      .map(
        ([platform, item]) =>
          `<div class="kv"><span>${escapeHtml(platform)}</span><b>${escapeHtml(item.name || "NA")} -v ${item.version ?? "NA"}</b></div>`
      )
      .join("") || `<div class="empty-state">No IFX mapping yet.</div>`;

  const branches =
    (apply.results || [])
      .map(
        (item) =>
          `<div class="kv"><span>${escapeHtml(item.branch)}</span><b>${escapeHtml(item.checkout_branch)}: ${item.returncode === 0 ? "OK" : `FAILED(${item.returncode})`}</b></div>`
      )
      .join("") || `<div class="empty-state">No applied handoff branches yet.</div>`;

  const metrics = (payload.offboard_metrics || []).length
    ? `<pre class="metric-table">${escapeHtml(payload.offboard_metrics.join("\n"))}</pre>`
    : `<div class="empty-state">No offboard metrics captured yet.</div>`;

  const dcl =
    (commands.dcl_commands || [])
      .map((command) => `<div class="code-line">${escapeHtml(command)}</div>`)
      .join("") || `<div class="empty-state">DCL commands are not ready.</div>`;

  $("details").className = "details";
  $("details").innerHTML = `
    <div class="detail-block">
      <h4>Release</h4>
      <div class="kv"><span>stage</span><b>${escapeHtml(summary.stage || "NA")} / ${escapeHtml(summary.status || "NA")}</b></div>
      <div class="kv"><span>experiment</span><b>${escapeHtml(summary.experiment_name || "NA")}</b></div>
      <div class="kv"><span>epoch</span><b>${formatEpoch(summary.selected_epoch)} (${escapeHtml(summary.selection_source || "unknown")})</b></div>
      <div class="kv"><span>updated</span><b>${escapeHtml(summary.updated_at || "NA")}</b></div>
    </div>

    <div class="detail-block">
      <h4>IFX Artifacts</h4>
      ${artifacts}
    </div>

    <div class="detail-block">
      <h4>Handoff Branches</h4>
      ${branches}
      ${dcl}
    </div>

    <div class="detail-block">
      <h4>Offboard Metrics</h4>
      ${metrics}
    </div>

    <div class="detail-block">
      <h4>Next CLI Commands</h4>
      <div class="code-line">${escapeHtml(commands.ifx_convert || "")}</div>
      <div class="code-line">${escapeHtml(commands.apply_handoff || "")}</div>
      <div class="code-line">${escapeHtml(commands.dcl || "")}</div>
      <div class="code-line">${escapeHtml(commands.offboard || "")}</div>
    </div>

    <div class="detail-block">
      <h4>Errors</h4>
      ${
        errors.length
          ? errors
              .slice(-6)
              .map((item) => `<div class="code-line">${escapeHtml(item.message || String(item))}</div>`)
              .join("")
          : `<div class="empty-state">No recorded errors.</div>`
      }
    </div>
  `;
}
