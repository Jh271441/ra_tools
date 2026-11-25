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

function systemStatusCard({ title, chip, tone = "ok", rows = [], extra = "", wide = false }) {
  return `<article class="system-status-card${wide ? " system-status-card--wide" : ""}">
    <div class="system-status-card-head"><h3>${escapeHtml(title)}</h3>${systemStatusChip(chip, tone)}</div>
    ${systemStatusRows(rows)}${extra}
  </article>`;
}

function systemStatusMediaTable(baselines) {
  const count = value => typeof value === "number" && Number.isFinite(value) && value >= 0 ? value.toLocaleString() : "—";
  const headers = [t("system.baseline"), uiText("成员", "Members"), "BEV", uiText("BEV 视频", "BEV video"), "Camera", uiText("媒体状态", "Media status")];
  const rows = baselines.map(item => {
    const membership = item.membership || {}, media = item.media_ready || {};
    const expected = membership.expected_count ?? item.count;
    const fraction = value => `${count(value)} / ${count(expected)}`;
    const status = item.media_status || item.status;
    const registered = ["registered", "ready"].includes(item.registration_status || item.status);
    const ready = registered && ["complete", "ready"].includes(status);
    const missing = Object.entries(item.missing_media || {}).filter(([, value]) => value > 0)
      .map(([key, value]) => `${({bev:"BEV",video:uiText("视频", "Video"),camera:"Camera"})[key] || key} ${uiText("缺少", "missing")} ${count(value)}`);
    if (media.failure_count > 0) missing.push(uiText(`采集错误 ${count(media.failure_count)} 项`, `${count(media.failure_count)} capture errors`));
    const values = [fraction(membership.registered_count ?? item.count), fraction(media.bev_indexed_issues), fraction(media.video_indexed_issues), fraction(media.camera_indexed_issues)];
    return `<tr><th scope="row">${escapeHtml(item.label || item.id || "—")}</th>${values.map(value => `<td>${escapeHtml(value)}</td>`).join("")}<td>${systemStatusChip(registered ? baselineLifecycleLabel(status) : uiText("成员异常", "Membership issue"), ready ? "ok" : status === "blocked" ? "fail" : "warn")}${missing.length ? `<small class="system-media-missing">${escapeHtml(missing.join(" · "))}</small>` : ""}</td></tr>`;
  }).join("");
  return `<div class="system-media-table-wrap" tabindex="0" role="region" aria-label="${escapeHtml(t("system.dataset_media"))}"><table class="system-media-table"><thead><tr>${headers.map(label => `<th scope="col">${escapeHtml(label)}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="6">${escapeHtml(uiText("暂无数据集状态", "No dataset status available"))}</td></tr>`}</tbody></table></div>`;
}

function systemStatusLegacyCard(legacy, baselines) {
  const policies = Array.isArray(legacy.policies) ? legacy.policies : [];
  const labels = new Map(baselines.map(item => [item.scope, item.label || item.id]));
  const modes = { legacy: uiText("沿用现有记录", "Existing records"), shadow: uiText("迁移核对中", "Migration checks"), canonical: uiText("新版记录", "New records") };
  return systemStatusCard({
    title: uiText("历史复核数据", "Historical reviews"), chip: policies.length ? uiText("读取方式", "Read mode") : uiText("沿用现有记录", "Existing records"), tone: "neutral",
    rows: policies.length ? policies.map(item => [labels.get(item.baseline_scope) || t("system.baseline"), modes[item.policy] || uiText("待确认", "Unknown")]) : [],
    extra: `<p class="system-status-note">${escapeHtml(uiText("这里说明历史复核记录的读取方式。当前问题标注与判错复核仍按用户权限提交。", "This describes how historical reviews are read. Current labeling and reviews follow user permissions."))}</p>`,
  });
}

function baselineLifecycleLabel(status) {
  const labels = {
    checking: uiText("统计中", "Counting"),
    unavailable: uiText("统计异常", "Count unavailable"),
    registered: uiText("已注册", "Registered"),
    collecting: uiText("采集中", "Collecting"),
    partial: uiText("部分可用", "Partial"),
    verifying: uiText("校验中", "Verifying"),
    complete: uiText("完整", "Complete"),
    blocked: uiText("阻塞", "Blocked"),
    ready: uiText("就绪", "Ready"),
  };
  return labels[String(status || "")] || String(status || "—");
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
  const legacyCutover = data.legacy_cutover || {};
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
    (item) => ["registered", "ready"].includes(item.registration_status || item.status)
      && Number(item.count || 0) > 0
  );
  const baselineMediaReady = baselines.length > 0 && baselines.every(
    (item) => ["complete", "ready"].includes(item.media_status || item.status)
  );
  const mediaBusy = baselines.some(item => ["pending", "refreshing"].includes(item.media_ready?.coverage_status));
  const mediaError = baselines.some(item => item.media_ready?.coverage_status === "error");
  const assetsReady = Boolean(
    data.ra_auto_triage_root_available && data.ares_manifest_available && data.camera_cache_root_available
  );
  const gatewayReady = Boolean(gateway.configured);
  const usedPercent = Math.max(0, Math.min(100, Number(volume.used_percent) || 0));
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
      chip: mediaError ? uiText("统计异常", "Count unavailable") : mediaBusy ? uiText("统计更新中", "Updating counts") : baselineReady && baselineMediaReady && assetsReady ? t("status.ready") : t("status.partial"),
      tone: mediaError ? "warn" : mediaBusy ? "neutral" : baselineReady && baselineMediaReady && assetsReady ? "ok" : "warn",
      wide: true,
      extra: systemStatusMediaTable(baselines) + `<p class="system-status-note">${escapeHtml(mediaError ? uiText("媒体统计暂不可用，请稍后刷新；已有计数保留上次结果。", "Media counts are unavailable; refresh later. Existing counts retain the last result.") : mediaBusy ? uiText("媒体统计正在后台更新，完成后本页自动刷新；已有计数为上次结果。", "Media counts are updating in the background. This page refreshes when ready; existing counts show the last result.") : uiText("按各数据集成员统计，BEV、视频与 Camera 分别计数。", "Counts are scoped to each dataset's members; BEV, video and Camera are counted independently."))}</p>`,
      rows: [
        [t("system.baseline_conflicts"), String(conflictCount)],
        [t("system.camera_cache"), data.camera_cache_root_available ? t("status.available") : t("status.unavailable")],
        [t("system.bev_video"), data.ares_video_root_available ? t("status.available") : t("status.unavailable")],
      ],
    }),
    systemStatusCard({
      title: t("system.models"),
      chip: gatewayReady ? uiText("网关已配置", "Gateway configured") : t("system.gateway_missing"),
      tone: gatewayReady ? "ok" : "warn",
      rows: [
        [t("system.deploy_mode"), data.application?.deployment_mode === "production" ? t("status.production") : t("status.development")],
        [t("system.model_gateway"), gateway.configured ? t("system.gateway_cred") : t("status.not_configured")],
        [t("system.batch_pred"), data.batch_prediction_enabled ? t("status.enabled") : t("status.disabled")],
        [uiText("看板手动推送", "Dashboard publication"), data.autotriage_push_enabled ? t("status.enabled") : t("status.disabled")],
        [t("system.trail_fields"), ["ready", "preview_ready"].includes(trail.status) ? t("status.available") : t("system.trail_unavailable")],
      ],
      extra: `<p class="system-status-note">${escapeHtml(uiText("手动推送开关仅作用于本看板；每日推理与回刷进度请查看“每日任务”。", "The publication switch applies to this dashboard. Check Daily tasks for scheduled inference and publication."))}</p>` + (trail.message ? `<details class="system-status-diagnostics"><summary>${escapeHtml(uiText("连接详情", "Connection details"))}</summary><p class="system-status-note">${escapeHtml(trail.message)}</p></details>` : ""),
    }),
    systemStatusLegacyCard(legacyCutover, baselines),
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

let systemStatusRefreshTimer = null;
let systemStatusRequestSeq = 0;
let systemStatusInFlight = 0;

function syncSystemStatusRefresh() {
  if (systemStatusRefreshTimer !== null) window.clearTimeout(systemStatusRefreshTimer);
  systemStatusRefreshTimer = null;
  if (systemStatusInFlight || state.activePage !== "status"
      || !(state.systemStatus?.baselines || []).some(item => ["pending", "refreshing"].includes(item.media_ready?.coverage_status))) return;
  const context = capturePageContext(), requestSeq = systemStatusRequestSeq;
  systemStatusRefreshTimer = window.setTimeout(() => {
    systemStatusRefreshTimer = null;
    if (state.activePage === "status" && isPageContextCurrent(context) && requestSeq === systemStatusRequestSeq) {
      void loadStatus().catch(() => {});
    }
  }, 2000);
}

async function loadStatus() {
  if (systemStatusRefreshTimer !== null) window.clearTimeout(systemStatusRefreshTimer);
  systemStatusRefreshTimer = null;
  const requestSeq = ++systemStatusRequestSeq;
  systemStatusInFlight = requestSeq;
  let data;
  try {
    data = await api("/api/status");
  } finally {
    if (requestSeq === systemStatusRequestSeq) systemStatusInFlight = 0;
  }
  if (requestSeq !== systemStatusRequestSeq) return;
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
  syncSystemStatusRefresh();
}
