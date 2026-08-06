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
  if (days) return uiText(`${days} 天 ${hours} 小时`, `${days}d ${hours}h`);
  if (hours) return uiText(`${hours} 小时 ${minutes} 分`, `${hours}h ${minutes}m`);
  return uiText(`${minutes} 分钟`, `${minutes}m`);
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
  const trail = data.trail_sync || {};
  const gateway = data.model_gateway || {};
  const application = data.application || {};
  const overall = data.overall || { status: "degraded", problems: [] };
  const healthy = overall.status === "healthy";
  const problemLabels = {
    database_unavailable: uiText("数据库不可用", "Database unavailable"),
    database_not_persistent: uiText("数据库未使用持久卷", "Database is not persistent"),
    baseline_unavailable: uiText("基线不可用", "Baseline unavailable"),
    backup_missing: uiText("缺少数据库备份", "Database backup missing"),
    backup_checksum_missing: uiText("备份缺少校验文件", "Backup checksum missing"),
    backup_stale: uiText("最近备份已过期", "Latest backup is stale"),
    backup_schedule_unregistered: uiText("备份计划未登记", "Backup schedule unregistered"),
    disk_space_low: uiText("磁盘剩余空间不足", "Disk space is low"),
  };
  const problems = (overall.problems || []).map((key) => problemLabels[key] || key);
  hero.classList.toggle("degraded", !healthy);
  hero.innerHTML = `
    <div class="system-status-summary">
      <div class="system-status-indicator" aria-hidden="true">${healthy ? "✓" : "!"}</div>
      <div>
        <h2>${escapeHtml(healthy ? uiText("关键系统运行正常", "Core systems are healthy") : uiText("系统有项目需要关注", "System needs attention"))}</h2>
        <p>${escapeHtml(healthy ? uiText("服务、持久化数据库与备份保护均已就绪。", "Service, persistent database, and backup protection are ready.") : problems.join(" · ") || uiText("请查看下方状态卡。", "Review the status cards below."))}</p>
      </div>
    </div>
    <div class="system-status-build"><span>${escapeHtml(uiText("部署版本", "Build"))}</span><code>${escapeHtml(application.build_commit || data.build_commit || "unverified")}</code></div>`;

  const backupAge = backups.latest_age_seconds == null
    ? "—"
    : formatStatusDuration(backups.latest_age_seconds);
  const backupReady = Boolean(
    backups.available && backups.latest_checksum_present && backups.schedule_registered
  );
  const databaseReady = Boolean(database.ok && (database.backend !== "postgresql" || database.persistent_data));
  const baselineReady = baseline.status === "ready" && Number(baseline.count || 0) > 0;
  const assetsReady = Boolean(
    data.ra_auto_triage_root_available && data.ares_manifest_available && data.camera_cache_root_available
  );
  const gatewayReady = Boolean(gateway.configured);
  const usedPercent = Math.max(0, Math.min(100, Number(volume.used_percent) || 0));
  grid.innerHTML = [
    systemStatusCard({
      title: uiText("应用服务", "Application"),
      chip: uiText("在线", "Online"),
      rows: [
        [uiText("运行时间", "Uptime"), formatStatusDuration(application.uptime_seconds)],
        [uiText("启动时间", "Started"), formatTime(application.started_at)],
        [uiText("共享数据版本", "Shared revision"), String(database.revision ?? "—")],
      ],
    }),
    systemStatusCard({
      title: uiText("数据库", "Database"),
      chip: databaseReady ? uiText("正常", "Healthy") : uiText("异常", "Issue"),
      tone: databaseReady ? "ok" : "fail",
      rows: [
        [uiText("存储引擎", "Backend"), database.backend === "postgresql" ? "PostgreSQL" : "SQLite"],
        [uiText("持久化", "Persistence"), database.persistent_data ? uiText("/volume 持久卷", "/volume persistent") : uiText("本地存储", "Local storage")],
        [uiText("连接延迟", "Latency"), database.latency_ms == null ? "—" : `${database.latency_ms} ms`],
        [uiText("版本 / Migration", "Version / migrations"), `${database.server_version || "—"} · ${database.migration_count ?? 0}`],
        [uiText("连接池上限", "Pool limit"), String(database.pool_max_size || "—")],
      ],
    }),
    systemStatusCard({
      title: uiText("数据库备份", "Database backups"),
      chip: backupReady ? uiText("已保护", "Protected") : uiText("需关注", "Attention"),
      tone: backupReady ? "ok" : "warn",
      rows: [
        [uiText("最近备份", "Latest backup"), backups.latest_created_at ? formatTime(backups.latest_created_at) : "—"],
        [uiText("备份距今", "Backup age"), backupAge],
        [uiText("大小 / 份数", "Size / copies"), `${formatStatusBytes(backups.latest_size_bytes)} · ${backups.count || 0}`],
        [uiText("SHA-256 文件", "SHA-256 file"), backups.latest_checksum_present ? uiText("已生成", "Present") : uiText("缺失", "Missing")],
        [uiText("自动计划", "Schedule"), backups.schedule_registered ? `${backups.schedule} · ${uiText("服务器时间", "server time")}` : uiText("未登记", "Not registered")],
      ],
    }),
    systemStatusCard({
      title: uiText("数据与媒体", "Dataset & media"),
      chip: baselineReady && assetsReady ? uiText("就绪", "Ready") : uiText("部分可用", "Partial"),
      tone: baselineReady && assetsReady ? "ok" : "warn",
      rows: [
        [uiText("0508 基线", "0508 baseline"), `${baseline.count ?? 0} · ${baseline.status || "—"}`],
        [uiText("基线范围", "Baseline scope"), baseline.scope || "—"],
        [uiText("Ares BEV", "Ares BEV"), data.ares_manifest_available ? `${data.ares_indexed_issues || 0} Issues` : uiText("不可用", "Unavailable")],
        [uiText("Camera 缓存", "Camera cache"), data.camera_cache_root_available ? uiText("可用", "Available") : uiText("不可用", "Unavailable")],
        [uiText("BEV 视频", "BEV video"), data.ares_video_root_available ? uiText("可用", "Available") : uiText("不可用", "Unavailable")],
      ],
    }),
    systemStatusCard({
      title: uiText("模型与集成", "Models & integrations"),
      chip: gatewayReady ? uiText("网关就绪", "Gateway ready") : uiText("网关未配置", "Gateway unavailable"),
      tone: gatewayReady ? "ok" : "warn",
      rows: [
        [uiText("运行模式", "Deployment mode"), data.application?.deployment_mode === "production" ? uiText("生产", "Production") : uiText("开发", "Development")],
        [uiText("模型网关", "Model gateway"), gateway.configured ? uiText("服务端凭证已配置", "Server credential configured") : uiText("未配置", "Not configured")],
        [uiText("Batch 预测", "Batch prediction"), data.batch_prediction_enabled ? uiText("已启用", "Enabled") : uiText("已关闭", "Disabled")],
        [uiText("AutoTriage 推送", "AutoTriage publish"), data.autotriage_push_enabled ? uiText("已启用", "Enabled") : uiText("关闭（安全默认）", "Off (safe default)")],
        [uiText("Trail 字段", "Trail fields"), ["ready", "preview_ready"].includes(trail.status) ? uiText("可用", "Available") : uiText("当前不可用", "Currently unavailable")],
      ],
      extra: trail.message ? `<p class="system-status-note">${escapeHtml(trail.message)}</p>` : "",
    }),
    systemStatusCard({
      title: uiText("持久卷容量", "Persistent volume"),
      chip: volume.available && Number(volume.free_bytes || 0) >= 1024 ** 3 ? uiText("空间充足", "Capacity OK") : uiText("空间不足", "Low space"),
      tone: volume.available && Number(volume.free_bytes || 0) >= 1024 ** 3 ? "ok" : "fail",
      rows: [
        [uiText("已使用", "Used"), `${formatStatusBytes(volume.used_bytes)} · ${usedPercent}%`],
        [uiText("剩余", "Free"), formatStatusBytes(volume.free_bytes)],
        [uiText("总容量", "Total"), formatStatusBytes(volume.total_bytes)],
      ],
      extra: `<div class="system-capacity"><div class="system-capacity-track"><span class="${usedPercent >= 95 ? "warn" : ""}" style="width:${usedPercent}%"></span></div></div>`,
    }),
  ].join("");
  const updated = $("#systemStatusUpdatedAt");
  if (updated) {
    updated.textContent = `${uiText("更新于", "Updated")} ${formatTime(data.generated_at)}`;
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
