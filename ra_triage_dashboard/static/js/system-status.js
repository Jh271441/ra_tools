/* ra_triage_dashboard/static/js/system-status.js
 * System status page
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function formatStatusDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  if (days) return t("system.duration_dh", { d: days, h: hours });
  if (hours) return t("system.duration_hm", { h: hours, m: minutes });
  return t("system.duration_m", { m: minutes });
}

function formatStatusBytes(bytes) {
  const value = Math.max(0, Number(bytes) || 0);
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let index = 0;
  let size = value;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  const digits = index >= 3 ? 1 : index ? 1 : 0;
  return `${size.toFixed(digits)} ${units[index]}`;
}

function systemStatusChip(label, tone = "ok") {
  return `<span class="status-chip ${tone}">${escapeHtml(label)}</span>`;
}

function systemStatusRows(items) {
  return `<div class="system-status-rows">${items
    .map(
      ([label, value]) => `<div class="system-status-row"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`
    )
    .join("")}</div>`;
}

function systemStatusCard({ title, chip, tone = "ok", rows, extra = "" }) {
  return `<article class="system-status-card">
    <div class="system-status-card-head"><h3>${escapeHtml(title)}</h3>${systemStatusChip(chip, tone)}</div>
    ${systemStatusRows(rows)}${extra}
  </article>`;
}

function renderSystemStatus() {
  const hero = $("#systemStatusHero");
  const grid = $("#systemStatusGrid");
  if (!hero || !grid) return;
  const data = state.systemStatus;
  if (!data) return;
  const database = data.database || {};
  const backups = data.backups || {};
  const volume = data.volume || {};
  const baseline = data.baseline || {};
  const baselines = Array.isArray(data.baselines) && data.baselines.length
    ? data.baselines
    : baseline && Object.keys(baseline).length
      ? [baseline]
      : [];
  const trail = data.trail_sync || {};
  const gateway = data.model_gateway || {};
  const application = data.application || {};
  const overall = data.overall || { status: "degraded", problems: [] };
  const healthy = overall.status === "healthy";
  const problemLabels = {
    database_unavailable: t("system.problem.database_unavailable"),
    database_not_persistent: t("system.problem.database_not_persistent"),
    baseline_unavailable: t("system.problem.baseline_unavailable"),
    backup_missing: t("system.problem.backup_missing"),
    backup_checksum_missing: t("system.problem.backup_checksum_missing"),
    backup_stale: t("system.problem.backup_stale"),
    backup_schedule_unregistered: t("system.problem.backup_schedule_unregistered"),
    disk_space_low: t("system.problem.disk_space_low"),
  };
  const problems = (overall.problems || []).map((key) => problemLabels[key] || key);
  hero.classList.toggle("degraded", !healthy);
  hero.innerHTML = `
    <div class="system-status-summary">
      <div class="system-status-indicator" aria-hidden="true">${healthy ? "✓" : "!"}</div>
      <div>
        <h2>${escapeHtml(healthy ? t("system.healthy_title") : t("system.degraded_title"))}</h2>
        <p>${escapeHtml(healthy ? t("system.healthy_body") : problems.join(" · ") || t("system.degraded_body"))}</p>
      </div>
    </div>
    <div class="system-status-build"><span>${escapeHtml(t("system.build"))}</span><code>${escapeHtml(application.build_commit || data.build_commit || "unverified")}</code></div>`;

  const backupAge = backups.latest_age_seconds == null
    ? "—"
    : formatStatusDuration(backups.latest_age_seconds);
  const backupReady = Boolean(
    backups.available && backups.latest_checksum_present && backups.schedule_registered
  );
  const databaseReady = Boolean(database.ok && (database.backend !== "postgresql" || database.persistent_data));
  const baselineReady = baselines.length > 0 && baselines.every(
    (item) => item.status === "ready" && Number(item.count || 0) > 0
  );
  const baselineMediaReady = baselines.length > 0 && baselines.every(
    (item) => Number(item.media_ready?.bev_indexed_issues || 0) >= Number(item.count || 0)
  );
  const assetsReady = Boolean(
    data.ra_auto_triage_root_available && data.ares_manifest_available && data.camera_cache_root_available
  );
  const gatewayReady = Boolean(gateway.configured);
  const usedPercent = Math.max(0, Math.min(100, Number(volume.used_percent) || 0));
  const baselineRows = baselines.map((item) => {
    const count = Number(item.count || 0);
    const indexed = Number(item.media_ready?.bev_indexed_issues || 0);
    const media = item.media_ready
      ? ` · BEV ${indexed} / ${count || "—"}`
      : " · BEV —";
    return [
      item.label || item.id || t("system.baseline"),
      `${count} · ${item.status || "—"}${media}`,
    ];
  });
  const conflictCount = Array.isArray(data.baseline_conflicts)
    ? data.baseline_conflicts.length
    : 0;
  grid.innerHTML = [
    systemStatusCard({
      title: t("system.app"),
      chip: t("status.online"),
      rows: [
        [t("system.uptime"), formatStatusDuration(application.uptime_seconds)],
        [t("system.started"), formatTime(application.started_at)],
        [t("system.revision"), String(database.revision ?? "—")],
      ],
    }),
    systemStatusCard({
      title: t("system.database"),
      chip: databaseReady ? t("status.healthy") : t("status.issue"),
      tone: databaseReady ? "ok" : "fail",
      rows: [
        [t("system.backend"), database.backend === "postgresql" ? "PostgreSQL" : "SQLite"],
        [t("system.persistence"), database.persistent_data ? t("system.persistent_volume") : t("system.local_storage")],
        [t("system.latency"), database.latency_ms == null ? "—" : `${database.latency_ms} ms`],
        [t("system.version_mig"), `${database.server_version || "—"} · ${database.migration_count ?? 0}`],
        [t("system.pool"), String(database.pool_max_size || "—")],
      ],
    }),
    systemStatusCard({
      title: t("system.backups"),
      chip: backupReady ? t("status.protected") : t("status.attention"),
      tone: backupReady ? "ok" : "warn",
      rows: [
        [t("system.latest_backup"), backups.latest_created_at ? formatTime(backups.latest_created_at) : "—"],
        [t("system.backup_age"), backupAge],
        [t("system.size_copies"), `${formatStatusBytes(backups.latest_size_bytes)} · ${backups.count || 0}`],
        [t("system.sha256"), backups.latest_checksum_present ? t("status.present") : t("status.missing_file")],
        [t("system.schedule"), backups.schedule_registered ? `${backups.schedule} · ${t("system.server_time")}` : t("status.not_registered")],
      ],
    }),
    systemStatusCard({
      title: t("system.dataset_media"),
      chip: baselineReady && baselineMediaReady && assetsReady ? t("status.ready") : t("status.partial"),
      tone: baselineReady && baselineMediaReady && assetsReady ? "ok" : "warn",
      rows: [
        ...baselineRows,
        [t("system.baseline_conflicts"), String(conflictCount)],
        [t("system.camera_cache"), data.camera_cache_root_available ? t("status.available") : t("status.unavailable")],
        [t("system.bev_video"), data.ares_video_root_available ? t("status.available") : t("status.unavailable")],
      ],
    }),
    systemStatusCard({
      title: t("system.models"),
      chip: gatewayReady ? t("system.gateway_ready") : t("system.gateway_missing"),
      tone: gatewayReady ? "ok" : "warn",
      rows: [
        [t("system.deploy_mode"), data.application?.deployment_mode === "production" ? t("status.production") : t("status.development")],
        [t("system.model_gateway"), gateway.configured ? t("system.gateway_cred") : t("status.not_configured")],
        [t("system.batch_pred"), data.batch_prediction_enabled ? t("status.enabled") : t("status.disabled")],
        [t("system.autotriage_push"), data.autotriage_push_enabled ? t("status.enabled") : t("system.autotriage_off")],
        [t("system.trail_fields"), ["ready", "preview_ready"].includes(trail.status) ? t("status.available") : t("system.trail_unavailable")],
      ],
      extra: trail.message ? `<p class="system-status-note">${escapeHtml(trail.message)}</p>` : "",
    }),
    systemStatusCard({
      title: t("system.volume"),
      chip: volume.available && Number(volume.free_bytes || 0) >= 1024 ** 3 ? t("status.capacity_ok") : t("status.low_space"),
      tone: volume.available && Number(volume.free_bytes || 0) >= 1024 ** 3 ? "ok" : "fail",
      rows: [
        [t("system.used"), `${formatStatusBytes(volume.used_bytes)} · ${usedPercent}%`],
        [t("system.free"), formatStatusBytes(volume.free_bytes)],
        [t("system.total"), formatStatusBytes(volume.total_bytes)],
      ],
      extra: `<div class="system-capacity"><div class="system-capacity-track"><span class="${usedPercent >= 95 ? "warn" : ""}" style="width:${usedPercent}%"></span></div></div>`,
    }),
  ].join("");
  const updated = $("#systemStatusUpdatedAt");
  if (updated) {
    updated.textContent = `${t("system.updated")} ${formatTime(data.generated_at)}`;
  }
}

async function loadStatus() {
  const data = await api("/api/status");
  state.systemStatus = data;
  if (data.baseline || data.trail_sync) {
    state.config = {
      ...(state.config || {}),
      baseline: data.baseline || state.config?.baseline,
      trail_sync: data.trail_sync || state.config?.trail_sync,
    };
    renderConfig();
  }
  renderSystemStatus();
}
