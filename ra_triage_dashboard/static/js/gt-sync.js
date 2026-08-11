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

function latestGtSyncTimestamp(items, field) {
  let latest = "";
  let latestMs = Number.NEGATIVE_INFINITY;
  for (const item of items || []) {
    const raw = String(item?.[field] || "").trim();
    if (!raw) continue;
    const parsed = new Date(raw).getTime();
    if (Number.isNaN(parsed)) {
      if (!latest) latest = raw;
      continue;
    }
    if (parsed > latestMs) {
      latest = raw;
      latestMs = parsed;
    }
  }
  return latest;
}

function gtSyncTriggerText(item) {
  const trigger = String(item?.last_trigger || "").trim();
  const actor = String(item?.requested_by || "").trim();
  const triggerText = trigger === "manual"
    ? uiText("手动", "Manual")
    : trigger === "periodic"
      ? uiText("后台定时", "Scheduled")
      : trigger === "startup"
        ? uiText("启动校验", "Startup")
        : trigger || uiText("未知", "Unknown");
  return actor && actor !== "system" ? `${triggerText} · ${actor}` : triggerText;
}

function appendGtSyncTooltipRow(root, label, value) {
  const row = document.createElement("div");
  row.className = "gt-sync-tooltip-row";
  const key = document.createElement("span");
  key.textContent = label;
  const content = document.createElement("strong");
  content.textContent = value;
  row.append(key, content);
  root.append(row);
}

function renderGtSyncTooltip(tooltip, items, current) {
  tooltip.replaceChildren();
  const heading = document.createElement("div");
  heading.className = "gt-sync-tooltip-heading";
  const title = document.createElement("strong");
  title.textContent = uiText("最近 GT 校验", "Latest GT check");
  const intervalMinutes = Math.max(1, Math.round(Number(current.interval_seconds || 1800) / 60));
  const source = document.createElement("span");
  source.textContent = uiText(
    `Trail view ${current.source_view_id || 1000} · 每 ${intervalMinutes} 分钟`,
    `Trail view ${current.source_view_id || 1000} · every ${intervalMinutes} min`
  );
  heading.append(title, source);
  tooltip.append(heading);

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "gt-sync-tooltip-empty";
    empty.textContent = uiText("尚无同步记录", "No sync record yet");
    tooltip.append(empty);
    return;
  }

  for (const item of items) {
    const section = document.createElement("section");
    section.className = "gt-sync-tooltip-dataset";
    const datasetHeading = document.createElement("div");
    datasetHeading.className = "gt-sync-tooltip-dataset-heading";
    const label = document.createElement("strong");
    label.textContent = item.baseline_label || item.baseline_id || "—";
    const status = document.createElement("span");
    status.textContent = gtSyncStatusText(item.status);
    datasetHeading.append(label, status);
    section.append(datasetHeading);

    const checkedTime = gtSyncTime(item.last_checked_at);
    const checkedRows = Number(item.source_row_count || 0);
    const changedRows = Number(item.last_check_change_count || 0);
    const sourceTime = gtSyncTime(item.source_updated_at);
    const sourceActor = String(item.source_updated_by || "").trim();
    const appliedTime = gtSyncTime(item.last_applied_at);
    appendGtSyncTooltipRow(
      section,
      uiText("本次校验", "Checked"),
      checkedTime || uiText("尚未校验", "Not checked")
    );
    appendGtSyncTooltipRow(
      section,
      uiText("本次结果", "Result"),
      uiText(`校验 ${checkedRows} 条 · 更新 ${changedRows} 条`, `${checkedRows} checked · ${changedRows} changed`)
    );
    appendGtSyncTooltipRow(section, uiText("触发方式", "Triggered by"), gtSyncTriggerText(item));
    appendGtSyncTooltipRow(
      section,
      uiText("Trail GT 更新", "Trail GT updated"),
      `${sourceTime || uiText("未知", "Unknown")}${sourceActor ? ` · ${sourceActor}` : ""}`
    );
    appendGtSyncTooltipRow(
      section,
      uiText("最近写入", "Last applied"),
      appliedTime
        ? uiText(`${appliedTime} · ${Number(item.last_applied_change_count || 0)} 条`, `${appliedTime} · ${Number(item.last_applied_change_count || 0)} changed`)
        : uiText("尚未写入", "Not applied")
    );
    tooltip.append(section);
  }
}

function renderGtSyncStatus(status = null) {
  const current = status || state.gtSync || state.config?.gt_sync || {};
  state.gtSync = current;
  const control = $("#gtSyncControl");
  const meta = $("#gtSyncMeta");
  const time = $("#gtSyncSourceTime");
  const button = $("#gtSyncButton");
  const tooltip = $("#gtSyncTooltip");
  if (!control || !meta || !time || !button || !tooltip) return;

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
  const checkedAt = latestGtSyncTimestamp(visibleItems, "last_checked_at");
  const checkedTime = gtSyncTime(checkedAt, { compact: true });
  const ready = stateName === "ready";
  const failed = ["failed", "unavailable"].includes(stateName);
  const running = stateName === "running";
  control.dataset.status = stateName;
  if (running) {
    time.textContent = uiText("同步中…", "Syncing…");
  } else if (single) {
    time.textContent = checkedTime || (ready
      ? uiText("已同步", "Synced")
      : uiText("待首次同步", "Not synced"));
  } else if (visibleItems.length) {
    const readyCount = names.filter((name) => name === "ready").length;
    time.textContent = checkedTime || `${readyCount}/${visibleItems.length}`;
  } else {
    time.textContent = uiText("未配置", "Unavailable");
  }
  meta.classList.toggle("is-ready", ready);
  meta.classList.toggle("is-failed", failed);
  meta.setAttribute(
    "aria-label",
    uiText(`GT 最近校验：${time.textContent}`, `Latest GT check: ${time.textContent}`)
  );
  renderGtSyncTooltip(tooltip, visibleItems, current);
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
