/* Authoritative 0508 GT synchronization status and manual refresh. */
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

function renderGtSyncStatus(status = null) {
  const current = status || state.gtSync || state.config?.gt_sync || {};
  state.gtSync = current;
  const control = $("#gtSyncControl");
  const meta = $("#gtSyncMeta");
  const time = $("#gtSyncSourceTime");
  const button = $("#gtSyncButton");
  if (!control || !meta || !time || !button) return;

  const stateName = String(current.status || "not_started");
  const sourceTime = gtSyncTime(current.source_updated_at, { compact: true });
  const checkedTime = gtSyncTime(current.last_checked_at);
  const appliedTime = gtSyncTime(current.last_applied_at);
  const sourceTimeFull = gtSyncTime(current.source_updated_at);
  const ready = stateName === "ready";
  const failed = ["failed", "unavailable"].includes(stateName);
  const running = stateName === "running";
  control.dataset.status = stateName;
  time.textContent = sourceTime || uiText("待首次同步", "Not synced");
  meta.classList.toggle("is-ready", ready);
  meta.classList.toggle("is-failed", failed);

  const details = [
    uiText(
      `权威源：Trail view ${current.source_view_id || 1000} / ${current.source_field || "ra_merge_result"}`,
      `Authority: Trail view ${current.source_view_id || 1000} / ${current.source_field || "ra_merge_result"}`
    ),
    uiText(`权威 GT 更新时间：${sourceTimeFull || "未知"}`, `Authority GT updated: ${sourceTimeFull || "unknown"}`),
    uiText(`Manual 最近检查：${checkedTime || "尚未检查"}`, `Manual last checked: ${checkedTime || "not checked"}`),
    uiText(
      `最近应用：${appliedTime || "尚未应用"}${current.last_applied_at ? `（${current.last_applied_change_count || 0} 条）` : ""}`,
      `Last applied: ${appliedTime || "not applied"}${current.last_applied_at ? ` (${current.last_applied_change_count || 0})` : ""}`
    ),
    current.message || "",
  ].filter(Boolean);
  control.title = details.join("\n");
  button.disabled = running || current.enabled === false || Boolean(state.session?.read_only);
  button.classList.toggle("is-running", running);
  button.querySelector(".ui-lang-zh").textContent = running ? "同步中…" : "刷新 GT";
  button.querySelector(".ui-lang-en").textContent = running ? "Syncing…" : "Refresh GT";
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
      body: JSON.stringify({ requested_by: state.session.username || "" }),
    });
    acknowledgeLocalChange(result);
    state.gtSync = result;
    if (state.config) state.config.gt_sync = result;
    renderGtSyncStatus(result);
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
