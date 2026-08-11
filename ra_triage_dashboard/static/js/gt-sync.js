/* Authoritative multi-baseline GT synchronization status and manual refresh. */
function gtSyncTime(value, { compact = false } = {}) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return new Intl.DateTimeFormat(state.uiLanguage === "en" ? "en-GB" : "zh-CN", {
    ...(compact ? { month: "2-digit", day: "2-digit" } : { year: "numeric", month: "2-digit", day: "2-digit" }),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date).replace(/\//g, "-");
}

function gtSyncStatusText(value) {
  const name = String(value || "not_started");
  const labels = {
    ready: uiText("已同步", "ready"),
    running: uiText("同步中", "syncing"),
    failed: uiText("同步失败", "failed"),
    unavailable: uiText("不可用", "unavailable"),
    not_started: uiText("待首次同步", "not synced"),
  };
  return labels[name] || name;
}

function renderGtSyncStatus(status = null) {
  const current = status || state.gtSync || state.config?.gt_sync || {};
  state.gtSync = current;
  const control = $("#gtSyncControl");
  const meta = $("#gtSyncMeta");
  const time = $("#gtSyncSourceTime");
  const button = $("#gtSyncButton");
  if (!control || !meta || !time || !button) return;

  const allItems = Array.isArray(current.baselines) && current.baselines.length
    ? current.baselines
    : current.baseline_id
      ? [current]
      : [];
  const selected = new Set(normalizeBaselineIds(state.selectedBaselineIds, { fallback: [] }));
  const items = allItems.filter((item) => !selected.size || selected.has(String(item.baseline_id || "")));
  const visibleItems = items.length ? items : allItems;
  const names = visibleItems.map((item) => String(item.status || "not_started"));
  const stateName = names.some((name) => name === "running") || current.status === "running"
    ? "running"
    : names.some((name) => ["failed", "unavailable"].includes(name))
      ? "failed"
      : names.length && names.every((name) => name === "ready")
        ? "ready"
        : "not_started";
  const single = visibleItems.length === 1 ? visibleItems[0] : null;
  const sourceTime = gtSyncTime(single?.source_updated_at, { compact: true });
  const ready = stateName === "ready";
  const failed = ["failed", "unavailable"].includes(stateName);
  const running = stateName === "running";
  control.dataset.status = stateName;
  if (single) {
    time.textContent = sourceTime || (ready
      ? uiText("已同步", "Synced")
      : uiText("待首次同步", "Not synced"));
  } else if (visibleItems.length) {
    const readyCount = names.filter((name) => name === "ready").length;
    time.textContent = `${readyCount}/${visibleItems.length}`;
  } else {
    time.textContent = uiText("未配置", "Unavailable");
  }
  meta.classList.toggle("is-ready", ready);
  meta.classList.toggle("is-failed", failed);

  const intervalMinutes = Math.max(1, Math.round(Number(current.interval_seconds || 1800) / 60));
  const details = [
    uiText(
      `权威源：Trail view ${current.source_view_id || 1000} / ${current.source_field || "ra_merge_result"}`,
      `Authority: Trail view ${current.source_view_id || 1000} / ${current.source_field || "ra_merge_result"}`
    ),
    uiText(`后台周期：每 ${intervalMinutes} 分钟`, `Background interval: every ${intervalMinutes} min`),
    ...visibleItems.flatMap((item) => {
      const label = item.baseline_label || item.baseline_id || "—";
      const sourceTimeFull = gtSyncTime(item.source_updated_at);
      const checkedTime = gtSyncTime(item.last_checked_at);
      const appliedTime = gtSyncTime(item.last_applied_at);
      return [
        uiText(
          `${label}：${gtSyncStatusText(item.status)}`,
          `${label}: ${gtSyncStatusText(item.status)}`
        ),
        uiText(`  权威 GT 更新时间：${sourceTimeFull || "未知"}`, `  Authority GT updated: ${sourceTimeFull || "unknown"}`),
        uiText(`  Manual 最近检查：${checkedTime || "尚未检查"}`, `  Manual last checked: ${checkedTime || "not checked"}`),
        uiText(
          `  最近应用：${appliedTime || "尚未应用"}${item.last_applied_at ? `（${item.last_applied_change_count || 0} 条）` : ""}`,
          `  Last applied: ${appliedTime || "not applied"}${item.last_applied_at ? ` (${item.last_applied_change_count || 0})` : ""}`
        ),
        item.message || "",
      ];
    }),
  ].filter(Boolean);
  control.title = details.join("\n");
  button.disabled = running || current.enabled === false || Boolean(state.session?.read_only);
  button.classList.toggle("is-running", running);
  button.querySelector(".ui-lang-zh").textContent = running ? "同步中…" : "同步";
  button.querySelector(".ui-lang-en").textContent = running ? "Syncing…" : "Sync";
}

async function refreshAuthoritativeGt() {
  const button = $("#gtSyncButton");
  if (!button || button.disabled) return;
  button.disabled = true;
  state.gtSync = { ...(state.gtSync || {}), status: "running" };
  renderGtSyncStatus();
  try {
    const result = await api("/api/gt-sync", {
      method: "POST",
      body: JSON.stringify({
        requested_by: state.session.username || "",
        baselines: normalizeBaselineIds(state.selectedBaselineIds),
      }),
    });
    acknowledgeLocalChange(result);
    state.gtSync = result;
    renderGtSyncStatus(result);
    if (result.status === "running") {
      showToast(
        result.accepted === false
          ? result.message || uiText("已有 GT 同步任务在运行。", "A GT sync is already running.")
          : uiText(
              "GT 后台同步已开始，完成后状态会自动更新。",
              "GT sync started in the background; status will update automatically."
            )
      );
      return;
    }
    let latest = result;
    try {
      latest = await api("/api/gt-sync-status");
    } catch {
      /* The mutation result is still complete for the requested baselines. */
    }
    state.gtSync = latest;
    if (state.config) state.config.gt_sync = latest;
    renderGtSyncStatus(latest);
    const changed = Number(result.last_check_change_count || 0);
    if (changed > 0) await refreshChangedData();
    showToast(
      result.status === "ready"
        ? changed > 0
          ? uiText(`GT 已同步：更新 ${changed} 条，Review 状态已重算。`, `GT synced: ${changed} changed; Review status recalculated.`)
          : uiText("GT 已是最新，无需更新。", "GT is already up to date.")
        : result.message || uiText("GT 同步失败。", "GT sync failed."),
      result.status !== "ready"
    );
  } catch (error) {
    showToast(error.message, true);
    try {
      const latest = await api("/api/gt-sync-status");
      state.gtSync = latest;
      if (state.config) state.config.gt_sync = latest;
    } catch {
      state.gtSync = { ...(state.gtSync || {}), status: "failed" };
    }
    renderGtSyncStatus();
  }
}
