(() => {
  "use strict";

  const activeBase = (window.__RA_TRIAGE_BASE__ || "").replace(/\/+$/, "");
  const withBase = (path) => {
    if (!path) return activeBase || "/";
    if (/^https?:\/\//i.test(path)) return path;
    const normalized = path.startsWith("/") ? path : `/${path}`;
    return `${activeBase}${normalized}`;
  };

  const PAGE_SIZES = [10, 20, 50, 100];
  const DEFAULT_PAGE_SIZE = 20;

  const I18N = {
    zh: {
      "portal.docTitle": "图表与交互 Artifact 库 · RA Triage",
      "portal.brand": "Artifact 图表库",
      "portal.workbench": "返回工作台",
      "portal.upload": "上传 HTML",
      "portal.eyebrow": "RA TRIAGE · ARTIFACTS HUB",
      "portal.title": "图表与交互 Artifact 管理入口",
      "portal.subtitle": "统一托管与分享各对话生成的架构图、诊断图与交互原型；新图表通过异步 Hook 自动同步，无需重新发版。",
      "portal.statActive": "活跃",
      "portal.statArchived": "已归档",
      "portal.statTotal": "总计",
      "portal.searchPlaceholder": "搜索标题、slug、标签、摘要或对话 ID...",
      "portal.searchClear": "清空搜索",
      "portal.filterToggle": "筛选与排序",
      "portal.filterStatus": "状态",
      "portal.filterSort": "排序",
      "portal.statusActive": "活跃",
      "portal.statusArchived": "已归档",
      "portal.statusAll": "全部",
      "portal.sortUpdatedDesc": "最近更新",
      "portal.sortUpdatedAsc": "最早更新",
      "portal.sortTitleAsc": "按标题 A-Z",
      "portal.sortCreatedDesc": "最新创建",
      "portal.groupAll": "全部分组",
      "portal.open": "打开查看",
      "portal.copyLink": "复制链接",
      "portal.copied": "已复制访问链接",
      "portal.copyFailed": "复制失败，请手动复制地址栏链接",
      "portal.pin": "置顶",
      "portal.unpin": "取消置顶",
      "portal.pinned": "已置顶",
      "portal.builtin": "内置",
      "portal.archived": "已归档",
      "portal.edit": "编辑",
      "portal.archive": "归档",
      "portal.restore": "恢复",
      "portal.delete": "删除",
      "portal.emptyTitle": "暂无匹配的 Artifact",
      "portal.emptyDesc": "当前筛选条件下没有找到图表，可以尝试清空搜索词或切换分组/状态。",
      "portal.resetFilters": "重置筛选",
      "portal.errorTitle": "加载失败",
      "portal.retry": "重试",
      "portal.totalCount": "共 {total} 条",
      "portal.prev": "上一页",
      "portal.next": "下一页",
      "portal.pageRatio": "第 {page} / {totalPages} 页",
      "portal.jumpLabel": "跳至",
      "portal.jumpGo": "跳转",
      "portal.pageSizeLabel": "每页",
      "portal.pageSizeUnit": "{n} 条",
      "portal.updatedAt": "更新于 {time}",
      "portal.convPrefix": "对话",
      "portal.readOnlyHint": "当前为只读模式；通过企业 SSO 登录后可编辑、归档或上传。",
      "modal.editTitle": "编辑 Artifact 信息",
      "modal.uploadTitle": "上传 HTML Artifact",
      "modal.deleteTitle": "确认删除 Artifact",
      "modal.deleteBody": "确定要永久删除「{title}」（{slug}）吗？此操作无法撤销。",
      "modal.close": "关闭",
      "modal.cancel": "取消",
      "modal.save": "保存修改",
      "modal.uploadSubmit": "上传并发布",
      "modal.deleteConfirm": "确认删除",
      "modal.fieldFile": "选择或拖拽 HTML 文件（最大 4 MB）",
      "modal.dropHint": "点击选择 .html 文件，或将文件拖到此处",
      "modal.fileSelected": "已选择：{name}（{size}）",
      "modal.fieldSlug": "URL 路径标识（slug）",
      "modal.slugPlaceholder": "例如：lora-mounting-inside-layers",
      "modal.fieldTitleZh": "中文标题",
      "modal.fieldTitleEn": "英文标题",
      "modal.fieldGroup": "所属分组",
      "modal.fieldTags": "标签（逗号分隔）",
      "modal.tagsPlaceholder": "例如：VLM, LoRA, PIPO",
      "modal.fieldSummaryZh": "中文摘要",
      "modal.fieldSummaryEn": "英文摘要",
      "modal.fieldPinned": "置顶显示",
      "modal.fieldArchived": "归档（隐藏出默认活跃列表）",
      "modal.saved": "已保存修改",
      "modal.uploaded": "已上传并发布：{slug}",
      "modal.deleted": "已删除：{slug}",
      "modal.needFile": "请先选择一个非空的 .html 文件。",
      "modal.needSlug": "请填写合法的 slug（仅小写字母、数字和连字符）。",
      "modal.needTitle": "请填写标题。",
      "viewer.back": "← 图表库",
      "viewer.copyLink": "复制链接",
      "viewer.wideOn": "宽幅铺满",
      "viewer.wideOff": "标准宽度",
      "viewer.openCanvas": "纯画布",
      "viewer.edit": "编辑",
      "viewer.prevLabel": "← 上一张",
      "viewer.nextLabel": "下一张 →",
      "viewer.prevTooltip": "上一张：{title}（←）",
      "viewer.nextTooltip": "下一张：{title}（→）",
      "viewer.noPrev": "已是第一张",
      "viewer.noNext": "已是最后一张",
      "viewer.kbdHint": "← / → 切换",
      "viewer.loading": "正在加载交互式图表画布...",
      "viewer.notFoundTitle": "未找到该 Artifact",
      "viewer.notFoundDesc": "链接对应的图表不存在或已被删除，请返回图表库查看全部内容。",
      "viewer.backToPortal": "返回 Artifact 图表库",
      "theme.toLight": "切换到浅色模式",
      "theme.toDark": "切换到深色模式",
      "lang.toggle": "Switch to English",
    },
    en: {
      "portal.docTitle": "Artifact Gallery · RA Triage",
      "portal.brand": "Artifact Gallery",
      "portal.workbench": "Workbench",
      "portal.upload": "Upload HTML",
      "portal.eyebrow": "RA TRIAGE · ARTIFACTS HUB",
      "portal.title": "Interactive Diagrams & Artifacts Hub",
      "portal.subtitle": "Unified registry for interactive architecture diagrams and UI prototypes across sessions. New HTML artifacts sync asynchronously via hook with zero restarts.",
      "portal.statActive": "Active",
      "portal.statArchived": "Archived",
      "portal.statTotal": "Total",
      "portal.searchPlaceholder": "Search title, slug, tags, summary, or conversation ID...",
      "portal.searchClear": "Clear search",
      "portal.filterToggle": "Filters & Sort",
      "portal.filterStatus": "Status",
      "portal.filterSort": "Sort",
      "portal.statusActive": "Active",
      "portal.statusArchived": "Archived",
      "portal.statusAll": "All",
      "portal.sortUpdatedDesc": "Recently updated",
      "portal.sortUpdatedAsc": "Oldest updated",
      "portal.sortTitleAsc": "Title A-Z",
      "portal.sortCreatedDesc": "Newest created",
      "portal.groupAll": "All groups",
      "portal.open": "Open",
      "portal.copyLink": "Copy link",
      "portal.copied": "Share URL copied",
      "portal.copyFailed": "Copy failed; please copy from the address bar",
      "portal.pin": "Pin",
      "portal.unpin": "Unpin",
      "portal.pinned": "Pinned",
      "portal.builtin": "Built-in",
      "portal.archived": "Archived",
      "portal.edit": "Edit",
      "portal.archive": "Archive",
      "portal.restore": "Restore",
      "portal.delete": "Delete",
      "portal.emptyTitle": "No matching artifacts",
      "portal.emptyDesc": "No artifacts match the active search or filters. Clear the query or switch group/status.",
      "portal.resetFilters": "Reset filters",
      "portal.errorTitle": "Failed to load artifacts",
      "portal.retry": "Retry",
      "portal.totalCount": "{total} items",
      "portal.prev": "Prev",
      "portal.next": "Next",
      "portal.pageRatio": "Page {page} / {totalPages}",
      "portal.jumpLabel": "Go to",
      "portal.jumpGo": "Go",
      "portal.pageSizeLabel": "Per page",
      "portal.pageSizeUnit": "{n} / page",
      "portal.updatedAt": "Updated {time}",
      "portal.convPrefix": "Conv",
      "portal.readOnlyHint": "Read-only preview; sign in via enterprise SSO to edit, archive, or upload.",
      "modal.editTitle": "Edit Artifact Metadata",
      "modal.uploadTitle": "Upload HTML Artifact",
      "modal.deleteTitle": "Delete Artifact",
      "modal.deleteBody": "Permanently delete \"{title}\" ({slug})? This cannot be undone.",
      "modal.close": "Close",
      "modal.cancel": "Cancel",
      "modal.save": "Save Changes",
      "modal.uploadSubmit": "Upload & Publish",
      "modal.deleteConfirm": "Delete",
      "modal.fieldFile": "Select or drop an HTML file (max 4 MB)",
      "modal.dropHint": "Click to choose a .html file, or drag and drop here",
      "modal.fileSelected": "Selected: {name} ({size})",
      "modal.fieldSlug": "URL slug",
      "modal.slugPlaceholder": "e.g. lora-mounting-inside-layers",
      "modal.fieldTitleZh": "Chinese Title",
      "modal.fieldTitleEn": "English Title",
      "modal.fieldGroup": "Group",
      "modal.fieldTags": "Tags (comma-separated)",
      "modal.tagsPlaceholder": "e.g. VLM, LoRA, PIPO",
      "modal.fieldSummaryZh": "Chinese Summary",
      "modal.fieldSummaryEn": "English Summary",
      "modal.fieldPinned": "Pin to top",
      "modal.fieldArchived": "Archive (hide from default active list)",
      "modal.saved": "Saved changes",
      "modal.uploaded": "Published: {slug}",
      "modal.deleted": "Deleted: {slug}",
      "modal.needFile": "Please choose a non-empty .html file first.",
      "modal.needSlug": "Please enter a valid slug (lowercase letters, digits, hyphens).",
      "modal.needTitle": "Title is required.",
      "viewer.back": "← Gallery",
      "viewer.copyLink": "Copy link",
      "viewer.wideOn": "Wide view",
      "viewer.wideOff": "Standard width",
      "viewer.openCanvas": "Raw canvas",
      "viewer.edit": "Edit",
      "viewer.prevLabel": "← Previous",
      "viewer.nextLabel": "Next →",
      "viewer.prevTooltip": "Previous: {title} (←)",
      "viewer.nextTooltip": "Next: {title} (→)",
      "viewer.noPrev": "First artifact",
      "viewer.noNext": "Last artifact",
      "viewer.kbdHint": "← / → to switch",
      "viewer.loading": "Loading interactive artifact canvas...",
      "viewer.notFoundTitle": "Artifact not found",
      "viewer.notFoundDesc": "This artifact does not exist or was removed. Return to the Artifact Gallery to browse available items.",
      "viewer.backToPortal": "Back to Artifact Gallery",
      "theme.toLight": "Switch to light theme",
      "theme.toDark": "Switch to dark theme",
      "lang.toggle": "切换到中文",
    },
  };

  let currentLang = (document.documentElement.dataset.uiLang === "en") ? "en" : "zh";
  let currentTheme = (document.documentElement.dataset.colorTheme === "light") ? "light" : "dark";
  let toastTimer = null;

  function t(key, vars = {}) {
    const dict = I18N[currentLang] || I18N.zh;
    let text = dict[key] ?? I18N.zh[key] ?? key;
    for (const [k, v] of Object.entries(vars)) {
      text = text.replaceAll(`{${k}}`, String(v));
    }
    return text;
  }

  function formatBytes(bytes) {
    const n = Number(bytes || 0);
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(2)} MB`;
  }

  function formatTimeCst(iso) {
    if (!iso) return "--";
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return String(iso);
    try {
      const fmt = new Intl.DateTimeFormat(currentLang === "en" ? "en-GB" : "zh-CN", {
        timeZone: "Asia/Shanghai",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
      return `${fmt.format(dt)} CST`;
    } catch (_) {
      return dt.toISOString().slice(0, 16).replace("T", " ") + " UTC";
    }
  }

  function showToast(message, { isError = false } = {}) {
    const el = document.getElementById("hubToast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("is-error", isError);
    el.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.hidden = true;
    }, isError ? 4200 : 2400);
  }

  async function copyShareUrl(urlPath) {
    const fullUrl = new URL(withBase(urlPath), window.location.origin).href;
    try {
      await navigator.clipboard.writeText(fullUrl);
      showToast(t("portal.copied"));
    } catch (_) {
      try {
        const input = document.createElement("textarea");
        input.value = fullUrl;
        input.style.position = "fixed";
        input.style.opacity = "0";
        document.body.appendChild(input);
        input.select();
        document.execCommand("copy");
        document.body.removeChild(input);
        showToast(t("portal.copied"));
      } catch (__) {
        showToast(t("portal.copyFailed"), { isError: true });
      }
    }
  }

  async function apiJson(path, { method = "GET", body = null } = {}) {
    const headers = { Accept: "application/json" };
    if (method !== "GET" && method !== "HEAD") {
      headers["X-RA-Triage-Request"] = "browser-v1";
      headers["Content-Type"] = "application/json";
    }
    const resp = await fetch(withBase(path), {
      method,
      headers,
      credentials: "same-origin",
      body: body !== null ? JSON.stringify(body) : undefined,
    });
    const text = await resp.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch (_) {
      data = { detail: text || `HTTP ${resp.status}` };
    }
    if (!resp.ok) {
      const msg = (data && data.detail) ? String(data.detail) : `HTTP ${resp.status}`;
      const err = new Error(msg);
      err.status = resp.status;
      throw err;
    }
    return data;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function groupPillClass(groupId) {
    if (groupId === "vlm-architecture") return "pill pill-group-vlm";
    if (groupId === "workbench-ui") return "pill pill-group-workbench";
    return "pill";
  }

  function localizedTitle(item) {
    return (currentLang === "en" ? (item.title_en || item.title) : item.title) || item.slug;
  }

  function localizedSummary(item) {
    return (currentLang === "en" ? (item.summary_en || item.summary) : item.summary) || "";
  }

  function localizedGroup(item) {
    return (currentLang === "en" ? (item.group_label_en || item.group_label) : item.group_label) || item.group;
  }

  /* Shared .ui-select controller matching RA Triage Workbench dropdown contract */
  const openSelects = new Set();

  function closeAllSelects(except = null) {
    for (const sel of Array.from(openSelects)) {
      if (sel !== except) sel.close();
    }
  }

  document.addEventListener("click", (event) => {
    for (const sel of Array.from(openSelects)) {
      if (!sel.root.contains(event.target) && !sel.panel.contains(event.target)) {
        sel.close();
      }
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && openSelects.size > 0) {
      for (const sel of Array.from(openSelects)) {
        sel.close({ restoreFocus: true });
      }
    }
  });

  window.addEventListener("resize", () => {
    for (const sel of Array.from(openSelects)) {
      sel.positionPanel();
    }
  });

  window.addEventListener("scroll", () => {
    for (const sel of Array.from(openSelects)) {
      sel.positionPanel();
    }
  }, true);

  class UiSelect {
    constructor(root, { options = [], value = "", onChange = null, ariaLabel = "" } = {}) {
      this.root = root;
      this.options = options;
      this.value = String(value);
      this.onChange = onChange;
      this.disabled = false;
      this.focusedIndex = -1;
      this.root.classList.add("ui-select");
      this.root.innerHTML = "";

      this.trigger = document.createElement("button");
      this.trigger.type = "button";
      this.trigger.className = "ui-select-trigger";
      this.trigger.setAttribute("aria-haspopup", "listbox");
      this.trigger.setAttribute("aria-expanded", "false");
      if (ariaLabel) this.trigger.setAttribute("aria-label", ariaLabel);

      this.summary = document.createElement("span");
      this.summary.className = "ui-select-summary";
      this.trigger.appendChild(this.summary);

      this.panel = document.createElement("div");
      this.panel.className = "ui-select-panel";
      this.panel.setAttribute("role", "listbox");
      this.panel.hidden = true;

      this.root.appendChild(this.trigger);
      document.body.appendChild(this.panel);

      this.trigger.addEventListener("click", (event) => {
        event.stopPropagation();
        if (this.disabled) return;
        if (this.isOpen()) this.close();
        else this.open();
      });

      this.trigger.addEventListener("keydown", (event) => {
        if (this.disabled) return;
        if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          if (!this.isOpen()) {
            this.open();
          } else if (event.key === "ArrowDown") {
            this.moveFocus(1);
          } else if (event.key === "ArrowUp") {
            this.moveFocus(-1);
          } else {
            this.selectFocused();
          }
        }
      });

      this.panel.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          this.moveFocus(1);
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          this.moveFocus(-1);
        } else if (event.key === "Home") {
          event.preventDefault();
          this.setFocusIndex(0);
        } else if (event.key === "End") {
          event.preventDefault();
          this.setFocusIndex(this.options.length - 1);
        } else if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          this.selectFocused();
        } else if (event.key === "Tab") {
          this.close();
        }
      });

      this.renderOptions();
    }

    isOpen() {
      return !this.panel.hidden;
    }

    setAriaLabel(label) {
      if (label) this.trigger.setAttribute("aria-label", label);
    }

    setDisabled(flag) {
      this.disabled = Boolean(flag);
      this.trigger.disabled = this.disabled;
      this.root.classList.toggle("is-disabled", this.disabled);
      if (this.disabled) this.close();
    }

    setOptions(options, preserveValue = true) {
      this.options = options;
      const valid = this.options.some((o) => String(o.value) === String(this.value));
      if (!preserveValue || !valid) {
        this.value = this.options.length ? String(this.options[0].value) : "";
      }
      this.renderOptions();
    }

    setValue(val) {
      const next = String(val);
      if (this.options.some((o) => String(o.value) === next)) {
        this.value = next;
      }
      this.renderOptions();
    }

    renderOptions() {
      this.panel.innerHTML = "";
      let activeLabel = "";
      this.options.forEach((opt, idx) => {
        const val = String(opt.value);
        const isActive = val === String(this.value);
        if (isActive) activeLabel = opt.label;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `ui-select-option${isActive ? " is-active" : ""}`;
        btn.setAttribute("role", "option");
        btn.setAttribute("aria-selected", isActive ? "true" : "false");
        btn.dataset.value = val;
        btn.dataset.index = String(idx);
        btn.innerHTML = `<span class="ui-select-option-check" aria-hidden="true">${isActive ? "✓" : ""}</span><span class="ui-select-option-label">${escapeHtml(opt.label)}</span>`;
        btn.addEventListener("click", (event) => {
          event.stopPropagation();
          this.choose(val);
        });
        this.panel.appendChild(btn);
      });
      this.summary.textContent = activeLabel || (this.options[0] ? this.options[0].label : "");
      this.summary.title = this.summary.textContent;
    }

    choose(val) {
      const changed = String(val) !== String(this.value);
      this.value = String(val);
      this.renderOptions();
      this.close({ restoreFocus: true });
      if (changed && typeof this.onChange === "function") {
        this.onChange(this.value);
      }
    }

    setFocusIndex(index) {
      const buttons = Array.from(this.panel.querySelectorAll(".ui-select-option"));
      if (!buttons.length) return;
      const clamped = Math.max(0, Math.min(buttons.length - 1, index));
      this.focusedIndex = clamped;
      buttons.forEach((b, i) => b.classList.toggle("is-focused", i === clamped));
      buttons[clamped].focus();
    }

    moveFocus(delta) {
      const len = this.options.length;
      if (!len) return;
      const start = this.focusedIndex >= 0 ? this.focusedIndex : Math.max(0, this.options.findIndex((o) => String(o.value) === String(this.value)));
      this.setFocusIndex((start + delta + len) % len);
    }

    selectFocused() {
      const buttons = Array.from(this.panel.querySelectorAll(".ui-select-option"));
      if (this.focusedIndex >= 0 && buttons[this.focusedIndex]) {
        this.choose(buttons[this.focusedIndex].dataset.value);
      }
    }

    positionPanel() {
      if (!this.isOpen()) return;
      const rect = this.trigger.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const width = Math.min(Math.max(rect.width, 156), vw - 16);
      this.panel.style.width = `${width}px`;
      let left = rect.left;
      if (left + width > vw - 8) left = Math.max(8, vw - width - 8);
      if (left < 8) left = 8;
      this.panel.style.left = `${left}px`;

      const panelHeight = Math.min(this.panel.scrollHeight || 220, 320);
      const spaceBelow = vh - rect.bottom - 10;
      const spaceAbove = rect.top - 10;
      if (spaceBelow >= panelHeight || spaceBelow >= spaceAbove) {
        this.panel.style.top = `${Math.min(vh - 48, rect.bottom + 4)}px`;
        this.panel.style.maxHeight = `${Math.max(120, Math.min(320, spaceBelow))}px`;
      } else {
        const top = Math.max(8, rect.top - Math.min(panelHeight, spaceAbove) - 4);
        this.panel.style.top = `${top}px`;
        this.panel.style.maxHeight = `${Math.max(120, Math.min(320, spaceAbove))}px`;
      }
    }

    open() {
      closeAllSelects(this);
      this.root.classList.add("is-open");
      this.trigger.setAttribute("aria-expanded", "true");
      this.panel.hidden = false;
      openSelects.add(this);
      this.positionPanel();
      const activeIdx = Math.max(0, this.options.findIndex((o) => String(o.value) === String(this.value)));
      this.setFocusIndex(activeIdx);
    }

    close({ restoreFocus = false } = {}) {
      if (!this.isOpen()) return;
      this.root.classList.remove("is-open");
      this.trigger.setAttribute("aria-expanded", "false");
      this.panel.hidden = true;
      openSelects.delete(this);
      this.focusedIndex = -1;
      if (restoreFocus) this.trigger.focus();
    }
  }

  const TAILWIND_SLOT = "<!--RA_TAILWIND_INLINE_SLOT-->";
  const ACCESS_CACHE_KEY = "ra-artifacts-access-v1";
  const ACCESS_CACHE_TTL_MS = 180_000;
  let tailwindSourcePromise = null;
  let manageAccessPromise = null;

  function readBootstrapJson(elementId) {
    const el = document.getElementById(elementId);
    if (!el || !el.textContent) return null;
    try {
      return JSON.parse(el.textContent);
    } catch (_) {
      return null;
    }
  }

  function getTailwindSource() {
    if (tailwindSourcePromise) return tailwindSourcePromise;
    if (window.__RA_TAILWIND_PROMISE__) {
      tailwindSourcePromise = window.__RA_TAILWIND_PROMISE__;
      return tailwindSourcePromise;
    }
    tailwindSourcePromise = fetch(withBase("/static/vendor/tailwindcss/tailwindcss.min.js"), {
      cache: "force-cache",
      credentials: "same-origin",
    })
      .then((resp) => (resp.ok ? resp.text() : ""))
      .catch(() => "");
    window.__RA_TAILWIND_PROMISE__ = tailwindSourcePromise;
    return tailwindSourcePromise;
  }

  function buildSrcdocHtml(slotHtml, theme, tailwindSource) {
    const isLight = theme === "light";
    let html = String(slotHtml || "");
    // Align initial <html> theme class/attribute before first paint inside sandbox.
    html = html.replace(/<html\b([^>]*)>/i, (full, attrs) => {
      let nextAttrs = String(attrs || "");
      nextAttrs = nextAttrs.replace(/\bdata-color-theme\s*=\s*["'][^"']*["']/i, `data-color-theme="${isLight ? "light" : "dark"}"`);
      if (!/\bdata-color-theme=/i.test(nextAttrs)) {
        nextAttrs += ` data-color-theme="${isLight ? "light" : "dark"}"`;
      }
      if (isLight) {
        if (/\bclass\s*=\s*"([^"]*)"/i.test(nextAttrs)) {
          nextAttrs = nextAttrs.replace(/\bclass\s*=\s*"([^"]*)"/i, (m, cls) =>
            cls.split(/\s+/).includes("light") ? m : `class="${cls ? `${cls} ` : ""}light"`,
          );
        } else {
          nextAttrs += ' class="light"';
        }
      } else {
        nextAttrs = nextAttrs.replace(/\bclass\s*=\s*"([^"]*)"/i, (_, cls) => {
          const filtered = cls.split(/\s+/).filter((c) => c && c !== "light").join(" ");
          return filtered ? `class="${filtered}"` : "";
        });
      }
      return `<html${nextAttrs}>`;
    });

    if (html.includes(TAILWIND_SLOT)) {
      if (tailwindSource) {
        // Callback prevents JS String.replace from interpreting $&, $$, $' in minified Tailwind.
        html = html.replace(TAILWIND_SLOT, () => `<script>${tailwindSource}</script>`);
      } else {
        const fallbackUrl = withBase("/static/vendor/tailwindcss/tailwindcss.min.js");
        html = html.replace(TAILWIND_SLOT, () => `<script src="${fallbackUrl}"></script>`);
      }
    }
    return html;
  }

  function resolveManageAccess() {
    if (manageAccessPromise) return manageAccessPromise;
    try {
      const raw = sessionStorage.getItem(ACCESS_CACHE_KEY);
      if (raw) {
        const cached = JSON.parse(raw);
        if (cached && typeof cached.can_manage === "boolean" && Date.now() - Number(cached.ts || 0) < ACCESS_CACHE_TTL_MS) {
          manageAccessPromise = Promise.resolve(Boolean(cached.can_manage));
          return manageAccessPromise;
        }
      }
    } catch (_) {}
    manageAccessPromise = apiJson("/api/artifacts-access")
      .then((res) => {
        const allowed = Boolean(res && res.can_manage);
        try {
          sessionStorage.setItem(ACCESS_CACHE_KEY, JSON.stringify({ can_manage: allowed, ts: Date.now() }));
        } catch (_) {}
        return allowed;
      })
      .catch(() => false);
    return manageAccessPromise;
  }

  /* Theme & Language shared wiring */
  function syncThemeControls() {
    document.documentElement.dataset.colorTheme = currentTheme;
    const btn = document.getElementById("themeToggleBtn");
    if (btn) {
      btn.textContent = currentTheme === "light" ? "☾" : "☀";
      const label = currentTheme === "light" ? t("theme.toDark") : t("theme.toLight");
      btn.setAttribute("aria-label", label);
      btn.title = label;
    }
    document.querySelectorAll(".viewer-stage-frame").forEach((frame) => {
      if (frame && frame.contentWindow) {
        frame.contentWindow.postMessage({ type: "ra-artifact-theme", theme: currentTheme }, "*");
      }
    });
  }

  function syncLangControls() {
    document.documentElement.dataset.uiLang = currentLang;
    document.documentElement.lang = currentLang === "en" ? "en" : "zh-CN";
    const btn = document.getElementById("langToggleBtn");
    if (btn) {
      btn.textContent = currentLang === "en" ? "中文" : "EN";
      const label = t("lang.toggle");
      btn.setAttribute("aria-label", label);
      btn.title = label;
    }
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    document.querySelectorAll("[data-i18n-aria]").forEach((el) => {
      const text = t(el.dataset.i18nAria);
      el.setAttribute("aria-label", text);
      el.title = text;
    });
  }

  /* Shared Edit Modal controller (used by both Portal and Viewer) */
  function createEditModalController({ onSaved }) {
    const backdrop = document.getElementById("editModalBackdrop");
    const form = document.getElementById("editArtifactForm");
    if (!backdrop || !form) return null;

    let currentSlug = "";
    let presetGroups = [];
    const groupSelect = new UiSelect(document.getElementById("editGroupSelect"), {
      options: [],
      value: "general",
      ariaLabel: t("modal.fieldGroup"),
    });

    const close = () => {
      closeAllSelects();
      backdrop.hidden = true;
      currentSlug = "";
    };

    backdrop.querySelectorAll("[data-close-edit]").forEach((btn) => {
      btn.addEventListener("click", close);
    });
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) close();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !backdrop.hidden && openSelects.size === 0) close();
    });

    const refreshGroupOptions = (groups) => {
      if (Array.isArray(groups) && groups.length) presetGroups = groups;
      const list = presetGroups.map((g) => ({
        value: g.id,
        label: currentLang === "en" ? (g.label_en || g.label) : g.label,
      }));
      if (list.length) {
        groupSelect.setOptions(list, true);
        groupSelect.setAriaLabel(t("modal.fieldGroup"));
      }
    };

    const open = (item, groups) => {
      currentSlug = item.slug;
      const mergedGroups = [...(groups || presetGroups)];
      if (item.group && !mergedGroups.some((g) => g.id === item.group)) {
        mergedGroups.push({
          id: item.group,
          label: item.group_label || item.group,
          label_en: item.group_label_en || item.group,
        });
      }
      refreshGroupOptions(mergedGroups);
      groupSelect.setValue(item.group || "general");

      document.getElementById("editTitleZh").value = item.title || "";
      document.getElementById("editTitleEn").value = item.title_en || "";
      document.getElementById("editTags").value = (item.tags || []).join(", ");
      document.getElementById("editSummaryZh").value = item.summary || "";
      document.getElementById("editSummaryEn").value = item.summary_en || "";
      document.getElementById("editPinned").checked = Boolean(item.pinned);
      document.getElementById("editArchived").checked = Boolean(item.archived);
      const errEl = document.getElementById("editFormError");
      errEl.hidden = true;
      errEl.textContent = "";
      backdrop.hidden = false;
      document.getElementById("editTitleZh").focus();
    };

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!currentSlug) return;
      const errEl = document.getElementById("editFormError");
      const submitBtn = document.getElementById("editSubmitBtn");
      const title = document.getElementById("editTitleZh").value.trim();
      if (!title) {
        errEl.textContent = t("modal.needTitle");
        errEl.hidden = false;
        return;
      }
      errEl.hidden = true;
      submitBtn.disabled = true;
      try {
        const res = await apiJson(`/api/artifacts/${encodeURIComponent(currentSlug)}`, {
          method: "PATCH",
          body: {
            title,
            title_en: document.getElementById("editTitleEn").value.trim() || title,
            group: groupSelect.value || "general",
            tags: document.getElementById("editTags").value,
            summary: document.getElementById("editSummaryZh").value.trim(),
            summary_en: document.getElementById("editSummaryEn").value.trim(),
            pinned: document.getElementById("editPinned").checked,
            archived: document.getElementById("editArchived").checked,
          },
        });
        close();
        showToast(t("modal.saved"));
        if (typeof onSaved === "function") onSaved(res.item);
      } catch (err) {
        errEl.textContent = err.message || String(err);
        errEl.hidden = false;
      } finally {
        submitBtn.disabled = false;
      }
    });

    return { open, close, refreshGroupOptions };
  }

  /* ===================== PORTAL PAGE ===================== */
  function initPortal() {
    const params = new URLSearchParams(window.location.search);
    const parsedPage = Number.parseInt(params.get("page") || "1", 10);
    const parsedPageSize = Number.parseInt(params.get("page_size") || String(DEFAULT_PAGE_SIZE), 10);

    const state = {
      q: (params.get("q") || "").trim(),
      group: (params.get("group") || "").trim(),
      status: ["active", "archived", "all"].includes(params.get("status")) ? params.get("status") : "active",
      sort: ["updated_desc", "updated_asc", "title_asc", "created_desc"].includes(params.get("sort")) ? params.get("sort") : "updated_desc",
      page: Number.isFinite(parsedPage) && parsedPage >= 1 ? parsedPage : 1,
      pageSize: PAGE_SIZES.includes(parsedPageSize) ? parsedPageSize : DEFAULT_PAGE_SIZE,
      loading: false,
      error: "",
      canManage: false,
      items: [],
      total: 0,
      totalPages: 1,
      groups: [],
      presetGroups: [],
      counts: { active: 0, archived: 0, all: 0 },
      mobileFiltersOpen: false,
    };

    const workbenchLink = document.getElementById("workbenchBackLink");
    if (workbenchLink) workbenchLink.href = withBase("/review");

    const searchInput = document.getElementById("artifactSearchInput");
    const searchClearBtn = document.getElementById("artifactSearchClear");
    const controlsCard = document.getElementById("hubControlsCard");
    const mobileFilterToggle = document.getElementById("mobileFilterToggle");

    searchInput.value = state.q;
    searchClearBtn.hidden = !state.q;

    const statusSelect = new UiSelect(document.getElementById("statusFilterSelect"), {
      options: [],
      value: state.status,
      ariaLabel: t("portal.filterStatus"),
      onChange: (val) => {
        state.status = val;
        state.page = 1;
        syncUrl();
        loadArtifacts();
      },
    });

    const sortSelect = new UiSelect(document.getElementById("sortFilterSelect"), {
      options: [],
      value: state.sort,
      ariaLabel: t("portal.filterSort"),
      onChange: (val) => {
        state.sort = val;
        state.page = 1;
        syncUrl();
        loadArtifacts();
      },
    });

    const pageSizeSelect = new UiSelect(document.getElementById("pageSizeSelect"), {
      options: [],
      value: String(state.pageSize),
      ariaLabel: t("portal.pageSizeLabel"),
      onChange: (val) => {
        const next = Number.parseInt(val, 10);
        if (PAGE_SIZES.includes(next)) {
          state.pageSize = next;
          state.page = 1;
          syncUrl();
          loadArtifacts();
        }
      },
    });

    const editModal = createEditModalController({
      onSaved: () => loadArtifacts(),
    });

    /* Upload modal */
    const uploadBackdrop = document.getElementById("uploadModalBackdrop");
    const uploadForm = document.getElementById("uploadArtifactForm");
    const uploadFileInput = document.getElementById("uploadHtmlFile");
    const uploadDropzone = document.getElementById("uploadDropzone");
    const uploadDropText = document.getElementById("uploadDropText");
    let uploadHtmlContent = "";
    let uploadFilename = "";

    const uploadGroupSelect = new UiSelect(document.getElementById("uploadGroupSelect"), {
      options: [],
      value: "vlm-architecture",
      ariaLabel: t("modal.fieldGroup"),
    });

    const closeUpload = () => {
      closeAllSelects();
      uploadBackdrop.hidden = true;
    };

    const readUploadFile = (file) => {
      if (!file) return;
      uploadFilename = file.name || "artifact.html";
      const reader = new FileReader();
      reader.onload = () => {
        uploadHtmlContent = String(reader.result || "");
        uploadDropText.textContent = t("modal.fileSelected", {
          name: uploadFilename,
          size: formatBytes(file.size),
        });
        const slugInput = document.getElementById("uploadSlug");
        if (!slugInput.value.trim()) {
          const base = uploadFilename.replace(/\.html?$/i, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
          slugInput.value = base.slice(0, 96);
        }
        const titleInput = document.getElementById("uploadTitleZh");
        if (!titleInput.value.trim()) {
          const match = uploadHtmlContent.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
          if (match && match[1].trim()) {
            titleInput.value = match[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 140);
          } else {
            titleInput.value = uploadFilename.replace(/\.html?$/i, "").replace(/[_-]+/g, " ");
          }
        }
      };
      reader.readAsText(file, "utf-8");
    };

    uploadDropzone.addEventListener("click", () => uploadFileInput.click());
    uploadDropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      uploadDropzone.classList.add("is-dragover");
    });
    uploadDropzone.addEventListener("dragleave", () => uploadDropzone.classList.remove("is-dragover"));
    uploadDropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      uploadDropzone.classList.remove("is-dragover");
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) readUploadFile(file);
    });
    uploadFileInput.addEventListener("change", () => {
      const file = uploadFileInput.files && uploadFileInput.files[0];
      if (file) readUploadFile(file);
    });

    document.getElementById("openUploadBtn").addEventListener("click", () => {
      uploadHtmlContent = "";
      uploadFilename = "";
      uploadForm.reset();
      uploadDropText.textContent = t("modal.dropHint");
      document.getElementById("uploadFormError").hidden = true;
      refreshDropdownLabels();
      uploadBackdrop.hidden = false;
      document.getElementById("uploadSlug").focus();
    });
    uploadBackdrop.querySelectorAll("[data-close-upload]").forEach((btn) => btn.addEventListener("click", closeUpload));
    uploadBackdrop.addEventListener("click", (event) => {
      if (event.target === uploadBackdrop) closeUpload();
    });

    uploadForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const errEl = document.getElementById("uploadFormError");
      const submitBtn = document.getElementById("uploadSubmitBtn");
      const slug = document.getElementById("uploadSlug").value.trim().toLowerCase();
      const title = document.getElementById("uploadTitleZh").value.trim();
      if (!uploadHtmlContent.trim()) {
        errEl.textContent = t("modal.needFile");
        errEl.hidden = false;
        return;
      }
      if (!/^[a-z0-9][a-z0-9-]{1,95}$/.test(slug)) {
        errEl.textContent = t("modal.needSlug");
        errEl.hidden = false;
        return;
      }
      if (!title) {
        errEl.textContent = t("modal.needTitle");
        errEl.hidden = false;
        return;
      }
      errEl.hidden = true;
      submitBtn.disabled = true;
      try {
        await apiJson("/api/artifacts", {
          method: "POST",
          body: {
            slug,
            html_content: uploadHtmlContent,
            title,
            title_en: document.getElementById("uploadTitleEn").value.trim() || title,
            group: uploadGroupSelect.value || "general",
            tags: document.getElementById("uploadTags").value,
            summary: document.getElementById("uploadSummaryZh").value.trim(),
            source_filename: uploadFilename || `${slug}.html`,
          },
        });
        closeUpload();
        showToast(t("modal.uploaded", { slug }));
        state.page = 1;
        syncUrl();
        loadArtifacts();
      } catch (err) {
        errEl.textContent = err.message || String(err);
        errEl.hidden = false;
      } finally {
        submitBtn.disabled = false;
      }
    });

    /* Delete modal */
    const deleteBackdrop = document.getElementById("deleteModalBackdrop");
    let pendingDeleteItem = null;
    const closeDelete = () => {
      deleteBackdrop.hidden = true;
      pendingDeleteItem = null;
    };
    deleteBackdrop.querySelectorAll("[data-close-delete]").forEach((btn) => btn.addEventListener("click", closeDelete));
    deleteBackdrop.addEventListener("click", (event) => {
      if (event.target === deleteBackdrop) closeDelete();
    });
    document.getElementById("deleteConfirmBtn").addEventListener("click", async () => {
      if (!pendingDeleteItem) return;
      const slug = pendingDeleteItem.slug;
      const btn = document.getElementById("deleteConfirmBtn");
      btn.disabled = true;
      try {
        await apiJson(`/api/artifacts/${encodeURIComponent(slug)}`, { method: "DELETE" });
        closeDelete();
        showToast(t("modal.deleted", { slug }));
        loadArtifacts();
      } catch (err) {
        showToast(err.message || String(err), { isError: true });
      } finally {
        btn.disabled = false;
      }
    });

    function refreshDropdownLabels() {
      statusSelect.setOptions([
        { value: "active", label: t("portal.statusActive") },
        { value: "archived", label: t("portal.statusArchived") },
        { value: "all", label: t("portal.statusAll") },
      ], true);
      statusSelect.setAriaLabel(t("portal.filterStatus"));

      sortSelect.setOptions([
        { value: "updated_desc", label: t("portal.sortUpdatedDesc") },
        { value: "updated_asc", label: t("portal.sortUpdatedAsc") },
        { value: "title_asc", label: t("portal.sortTitleAsc") },
        { value: "created_desc", label: t("portal.sortCreatedDesc") },
      ], true);
      sortSelect.setAriaLabel(t("portal.filterSort"));

      pageSizeSelect.setOptions(
        PAGE_SIZES.map((n) => ({ value: String(n), label: t("portal.pageSizeUnit", { n }) })),
        true,
      );
      pageSizeSelect.setAriaLabel(t("portal.pageSizeLabel"));

      const groupChoices = (state.presetGroups.length ? state.presetGroups : [
        { id: "vlm-architecture", label: "VLM & PIPO 架构", label_en: "VLM & PIPO Architecture" },
        { id: "workbench-ui", label: "Workbench UI 原型", label_en: "Workbench UI Mockups" },
        { id: "data-analysis", label: "数据分析与评测", label_en: "Data Analysis & Evals" },
        { id: "system-design", label: "系统与流程设计", label_en: "System & Workflow Design" },
        { id: "general", label: "其他图表", label_en: "General Diagrams" },
      ]).map((g) => ({
        value: g.id,
        label: currentLang === "en" ? (g.label_en || g.label) : g.label,
      }));
      uploadGroupSelect.setOptions(groupChoices, true);
      uploadGroupSelect.setAriaLabel(t("modal.fieldGroup"));
      if (editModal) editModal.refreshGroupOptions(state.presetGroups);
    }

    function syncUrl() {
      const next = new URLSearchParams();
      if (state.q) next.set("q", state.q);
      if (state.group) next.set("group", state.group);
      if (state.status !== "active") next.set("status", state.status);
      if (state.sort !== "updated_desc") next.set("sort", state.sort);
      if (state.page > 1) next.set("page", String(state.page));
      if (state.pageSize !== DEFAULT_PAGE_SIZE) next.set("page_size", String(state.pageSize));
      const qs = next.toString();
      const target = `${window.location.pathname}${qs ? `?${qs}` : ""}`;
      window.history.replaceState(null, "", target);
    }

    function updateMobileFilterState() {
      const isNarrow = window.matchMedia("(max-width: 639px)").matches;
      controlsCard.classList.toggle("is-mobile-collapsed", isNarrow && !state.mobileFiltersOpen);
      const activeCount = (state.q ? 1 : 0) + (state.group ? 1 : 0) + (state.status !== "active" ? 1 : 0) + (state.sort !== "updated_desc" ? 1 : 0);
      mobileFilterToggle.setAttribute("aria-expanded", String(!isNarrow || state.mobileFiltersOpen));
      mobileFilterToggle.textContent = activeCount > 0
        ? `${t("portal.filterToggle")} (${activeCount})`
        : t("portal.filterToggle");
    }

    mobileFilterToggle.addEventListener("click", () => {
      state.mobileFiltersOpen = !state.mobileFiltersOpen;
      updateMobileFilterState();
    });
    window.addEventListener("resize", updateMobileFilterState);

    let searchDebounce = null;
    searchInput.addEventListener("input", () => {
      const nextQ = searchInput.value.trim();
      searchClearBtn.hidden = !searchInput.value;
      if (searchDebounce) clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => {
        if (nextQ !== state.q) {
          state.q = nextQ;
          state.page = 1;
          syncUrl();
          loadArtifacts();
        }
      }, 200);
    });
    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        if (searchDebounce) clearTimeout(searchDebounce);
        state.q = searchInput.value.trim();
        state.page = 1;
        syncUrl();
        loadArtifacts();
      }
    });
    searchClearBtn.addEventListener("click", () => {
      searchInput.value = "";
      searchClearBtn.hidden = true;
      state.q = "";
      state.page = 1;
      syncUrl();
      loadArtifacts();
      searchInput.focus();
    });

    function renderGroupPills() {
      const container = document.getElementById("groupPillsBar");
      const totalInStatus = state.groups.reduce((acc, g) => acc + Number(g.count || 0), 0);
      const buttons = [
        `<button type="button" class="hub-group-pill${!state.group ? " is-active" : ""}" data-group=""><span>${escapeHtml(t("portal.groupAll"))}</span><span class="hub-group-pill-count">${totalInStatus}</span></button>`,
      ];
      for (const g of state.groups) {
        const label = currentLang === "en" ? (g.label_en || g.label) : g.label;
        const active = state.group === g.id;
        buttons.push(
          `<button type="button" class="hub-group-pill${active ? " is-active" : ""}" data-group="${escapeHtml(g.id)}"><span>${escapeHtml(label)}</span><span class="hub-group-pill-count">${g.count}</span></button>`,
        );
      }
      container.innerHTML = buttons.join("");
      container.querySelectorAll("[data-group]").forEach((btn) => {
        btn.addEventListener("click", () => {
          state.group = btn.dataset.group || "";
          state.page = 1;
          syncUrl();
          loadArtifacts();
        });
      });
    }

    function renderCards() {
      const root = document.getElementById("artifactListContainer");
      document.getElementById("hubTotalBadge").textContent = String(state.counts.all || 0);
      document.getElementById("statActiveCount").textContent = String(state.counts.active || 0);
      document.getElementById("statArchivedCount").textContent = String(state.counts.archived || 0);
      document.getElementById("statTotalCount").textContent = String(state.counts.all || 0);

      const uploadBtn = document.getElementById("openUploadBtn");
      uploadBtn.hidden = !state.canManage;

      const roHint = document.getElementById("readOnlyBanner");
      if (roHint) roHint.hidden = state.canManage;

      if (state.loading) {
        root.innerHTML = `<div class="hub-grid">${'<div class="skeleton-card" aria-hidden="true"></div>'.repeat(6)}</div>`;
        return;
      }
      if (state.error) {
        root.innerHTML = `
          <div class="hub-state-card" role="alert">
            <h2 class="hub-state-title">${escapeHtml(t("portal.errorTitle"))}</h2>
            <p class="hub-state-desc">${escapeHtml(state.error)}</p>
            <button type="button" class="btn btn-primary" id="retryLoadBtn">${escapeHtml(t("portal.retry"))}</button>
          </div>`;
        document.getElementById("retryLoadBtn").addEventListener("click", loadArtifacts);
        return;
      }
      if (!state.items.length) {
        root.innerHTML = `
          <div class="hub-state-card">
            <h2 class="hub-state-title">${escapeHtml(t("portal.emptyTitle"))}</h2>
            <p class="hub-state-desc">${escapeHtml(t("portal.emptyDesc"))}</p>
            <button type="button" class="btn" id="resetFiltersBtn">${escapeHtml(t("portal.resetFilters"))}</button>
          </div>`;
        document.getElementById("resetFiltersBtn").addEventListener("click", () => {
          state.q = "";
          state.group = "";
          state.status = "active";
          state.sort = "updated_desc";
          state.page = 1;
          searchInput.value = "";
          searchClearBtn.hidden = true;
          statusSelect.setValue("active");
          sortSelect.setValue("updated_desc");
          syncUrl();
          loadArtifacts();
        });
        return;
      }

      const navParams = new URLSearchParams();
      if (state.q) navParams.set("q", state.q);
      if (state.group) navParams.set("group", state.group);
      if (state.status !== "active") navParams.set("status", state.status);
      if (state.sort !== "updated_desc") navParams.set("sort", state.sort);
      const navSuffix = navParams.toString() ? `?${navParams.toString()}` : "";

      const cardsHtml = state.items.map((item) => {
        const href = `${withBase(item.url_path)}${navSuffix}`;
        const title = localizedTitle(item);
        const summary = localizedSummary(item);
        const groupLabel = localizedGroup(item);
        const convShort = item.conversation_id ? item.conversation_id.slice(0, 8) : "";
        const badges = [
          `<span class="${groupPillClass(item.group)}">${escapeHtml(groupLabel)}</span>`,
        ];
        if (item.pinned) badges.push(`<span class="pill pill-pin">★ ${escapeHtml(t("portal.pinned"))}</span>`);
        if (item.builtin) badges.push(`<span class="pill pill-builtin">${escapeHtml(t("portal.builtin"))}</span>`);
        if (item.archived) badges.push(`<span class="pill pill-archived">${escapeHtml(t("portal.archived"))}</span>`);

        const tagsHtml = (item.tags || []).slice(0, 6).map((tag) => `<span class="artifact-tag">${escapeHtml(tag)}</span>`).join("");

        const manageHtml = state.canManage
          ? `
            <button type="button" class="btn btn-sm btn-ghost" data-action="pin" data-slug="${escapeHtml(item.slug)}" title="${escapeHtml(item.pinned ? t("portal.unpin") : t("portal.pin"))}">${item.pinned ? "★" : "☆"}</button>
            <button type="button" class="btn btn-sm" data-action="edit" data-slug="${escapeHtml(item.slug)}">${escapeHtml(t("portal.edit"))}</button>
            <button type="button" class="btn btn-sm" data-action="archive" data-slug="${escapeHtml(item.slug)}">${escapeHtml(item.archived ? t("portal.restore") : t("portal.archive"))}</button>
            ${item.builtin ? "" : `<button type="button" class="btn btn-sm btn-danger" data-action="delete" data-slug="${escapeHtml(item.slug)}">${escapeHtml(t("portal.delete"))}</button>`}
          `
          : "";

        return `
          <article class="artifact-card${item.archived ? " is-archived" : ""}">
            <div class="artifact-card-head">
              <div class="artifact-card-badges">${badges.join("")}</div>
              <span class="artifact-rev">v${item.revision} · ${escapeHtml(formatBytes(item.size_bytes))}</span>
            </div>
            <a class="artifact-title-link" href="${escapeHtml(href)}">${escapeHtml(title)}</a>
            <p class="artifact-summary" title="${escapeHtml(summary)}">${escapeHtml(summary || item.source_filename || item.slug)}</p>
            ${tagsHtml ? `<div class="artifact-tags">${tagsHtml}</div>` : ""}
            <div class="artifact-meta">
              <span class="artifact-slug" title="${escapeHtml(item.url_path)}">${escapeHtml(item.slug)}${convShort ? ` · ${escapeHtml(t("portal.convPrefix"))} ${escapeHtml(convShort)}` : ""}</span>
              <span>${escapeHtml(formatTimeCst(item.updated_at))}</span>
            </div>
            <div class="artifact-actions">
              <div class="artifact-actions-main">
                <a class="btn btn-sm btn-primary" href="${escapeHtml(href)}">${escapeHtml(t("portal.open"))}</a>
                <button type="button" class="btn btn-sm" data-action="copy" data-url="${escapeHtml(item.url_path)}">${escapeHtml(t("portal.copyLink"))}</button>
              </div>
              ${manageHtml ? `<div class="artifact-actions-tools">${manageHtml}</div>` : ""}
            </div>
          </article>
        `;
      }).join("");

      root.innerHTML = `<div class="hub-grid">${cardsHtml}</div>`;

      root.querySelectorAll("[data-action='copy']").forEach((btn) => {
        btn.addEventListener("click", () => copyShareUrl(btn.dataset.url));
      });
      root.querySelectorAll("[data-action='pin']").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const item = state.items.find((x) => x.slug === btn.dataset.slug);
          if (!item) return;
          btn.disabled = true;
          try {
            await apiJson(`/api/artifacts/${encodeURIComponent(item.slug)}`, {
              method: "PATCH",
              body: { pinned: !item.pinned },
            });
            loadArtifacts();
          } catch (err) {
            showToast(err.message || String(err), { isError: true });
            btn.disabled = false;
          }
        });
      });
      root.querySelectorAll("[data-action='archive']").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const item = state.items.find((x) => x.slug === btn.dataset.slug);
          if (!item) return;
          btn.disabled = true;
          try {
            await apiJson(`/api/artifacts/${encodeURIComponent(item.slug)}`, {
              method: "PATCH",
              body: { archived: !item.archived },
            });
            loadArtifacts();
          } catch (err) {
            showToast(err.message || String(err), { isError: true });
            btn.disabled = false;
          }
        });
      });
      root.querySelectorAll("[data-action='edit']").forEach((btn) => {
        btn.addEventListener("click", () => {
          const item = state.items.find((x) => x.slug === btn.dataset.slug);
          if (item && editModal) editModal.open(item, state.presetGroups);
        });
      });
      root.querySelectorAll("[data-action='delete']").forEach((btn) => {
        btn.addEventListener("click", () => {
          const item = state.items.find((x) => x.slug === btn.dataset.slug);
          if (!item) return;
          pendingDeleteItem = item;
          document.getElementById("deleteModalBody").textContent = t("modal.deleteBody", {
            title: localizedTitle(item),
            slug: item.slug,
          });
          deleteBackdrop.hidden = false;
        });
      });
    }

    function renderPagination() {
      const bar = document.getElementById("artifactPagination");
      const disabledAll = state.loading || Boolean(state.error) || state.total === 0;
      document.getElementById("paginationTotal").textContent = t("portal.totalCount", { total: state.total });
      document.getElementById("paginationRatio").textContent = t("portal.pageRatio", {
        page: state.total === 0 ? 0 : state.page,
        totalPages: state.total === 0 ? 0 : state.totalPages,
      });

      const prevBtn = document.getElementById("pagePrevBtn");
      const nextBtn = document.getElementById("pageNextBtn");
      const jumpInput = document.getElementById("pageJumpInput");
      const jumpBtn = document.getElementById("pageJumpBtn");

      prevBtn.disabled = disabledAll || state.page <= 1;
      nextBtn.disabled = disabledAll || state.page >= state.totalPages;
      jumpInput.disabled = disabledAll || state.totalPages <= 1;
      jumpBtn.disabled = disabledAll || state.totalPages <= 1;
      jumpInput.max = String(state.totalPages);
      jumpInput.value = state.total > 0 ? String(state.page) : "";
      pageSizeSelect.setDisabled(state.loading);
      bar.hidden = false;
    }

    document.getElementById("pagePrevBtn").addEventListener("click", () => {
      if (state.page > 1) {
        state.page -= 1;
        syncUrl();
        loadArtifacts();
      }
    });
    document.getElementById("pageNextBtn").addEventListener("click", () => {
      if (state.page < state.totalPages) {
        state.page += 1;
        syncUrl();
        loadArtifacts();
      }
    });

    const performJump = () => {
      const input = document.getElementById("pageJumpInput");
      const raw = Number.parseInt(input.value, 10);
      if (!Number.isFinite(raw)) {
        input.value = String(state.page);
        return;
      }
      const clamped = Math.max(1, Math.min(state.totalPages, raw));
      input.value = String(clamped);
      if (clamped !== state.page) {
        state.page = clamped;
        syncUrl();
        loadArtifacts();
      }
    };
    document.getElementById("pageJumpBtn").addEventListener("click", performJump);
    document.getElementById("pageJumpInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        performJump();
      }
    });

    function applyPortalPayload(data) {
      state.items = Array.isArray(data.items) ? data.items : [];
      state.total = Number(data.total || 0);
      state.page = Number(data.page || 1);
      state.pageSize = Number(data.page_size || state.pageSize);
      state.totalPages = Math.max(1, Number(data.total_pages || 1));
      state.groups = Array.isArray(data.groups) ? data.groups : [];
      state.presetGroups = Array.isArray(data.preset_groups) ? data.preset_groups : [];
      state.counts = data.counts || { active: 0, archived: 0, all: 0 };
      if (data.can_manage) state.canManage = true;
      state.loading = false;
      refreshDropdownLabels();
      renderGroupPills();
      renderCards();
      renderPagination();
      updateMobileFilterState();
    }

    async function loadArtifacts() {
      state.loading = true;
      state.error = "";
      renderCards();
      renderPagination();
      updateMobileFilterState();
      const qs = new URLSearchParams({
        q: state.q,
        group: state.group,
        status: state.status,
        sort: state.sort,
        page: String(state.page),
        page_size: String(state.pageSize),
      });
      try {
        const data = await apiJson(`/api/artifacts?${qs.toString()}`);
        applyPortalPayload(data);
      } catch (err) {
        state.loading = false;
        state.error = err.message || String(err);
        renderCards();
        renderPagination();
      }
    }

    function applyAllText() {
      document.title = t("portal.docTitle");
      syncLangControls();
      syncThemeControls();
      refreshDropdownLabels();
      renderGroupPills();
      renderCards();
      renderPagination();
      updateMobileFilterState();
    }

    document.getElementById("langToggleBtn").addEventListener("click", () => {
      currentLang = currentLang === "en" ? "zh" : "en";
      try { localStorage.setItem("ra-triage-ui-language", currentLang); } catch (_) {}
      applyAllText();
    });

    document.getElementById("themeToggleBtn").addEventListener("click", () => {
      currentTheme = currentTheme === "light" ? "dark" : "light";
      try { localStorage.setItem("ra-triage-color-theme", currentTheme); } catch (_) {}
      syncThemeControls();
    });

    const initialBootstrap = readBootstrapJson("raPortalBootstrap");
    if (initialBootstrap && Array.isArray(initialBootstrap.items)) {
      applyPortalPayload(initialBootstrap);
      document.title = t("portal.docTitle");
      syncLangControls();
      syncThemeControls();
    } else {
      applyAllText();
      loadArtifacts();
    }

    // Resolve SSO write access asynchronously without delaying first paint.
    if (!state.canManage) {
      resolveManageAccess().then((allowed) => {
        if (allowed && !state.canManage) {
          state.canManage = true;
          renderCards();
        }
      });
    }

    // Idle-prefetch vendored Tailwind into browser disk cache so opening any card is instant.
    setTimeout(() => { getTailwindSource(); }, 180);
  }

  /* ===================== VIEWER PAGE ===================== */
  function initViewer() {
    const parseSlugFromPath = (pathname) => {
      const cleaned = (pathname || "").replace(/\/+$/, "");
      const parts = cleaned.split("/");
      return decodeURIComponent(parts[parts.length - 1] || "");
    };

    const extractNavContext = (search) => {
      const params = new URLSearchParams(search || "");
      const ctx = new URLSearchParams();
      const q = (params.get("q") || "").trim();
      const group = (params.get("group") || "").trim();
      const status = params.get("status") || "";
      const sort = params.get("sort") || "";
      if (q) ctx.set("q", q);
      if (group) ctx.set("group", group);
      if (status && ["active", "archived", "all"].includes(status) && status !== "active") {
        ctx.set("status", status);
      }
      if (sort && ["updated_desc", "updated_asc", "title_asc", "created_desc"].includes(sort) && sort !== "updated_desc") {
        ctx.set("sort", sort);
      }
      return ctx;
    };

    let activeSlug = parseSlugFromPath(window.location.pathname);
    let navContext = extractNavContext(window.location.search);
    const navSuffix = () => (navContext.toString() ? `?${navContext.toString()}` : "");

    const wrap = document.getElementById("viewerWrap");
    const backLink = document.getElementById("viewerBackLink");
    const openCanvasLink = document.getElementById("viewerOpenCanvasLink");
    const copyLinkBtn = document.getElementById("viewerCopyLinkBtn");
    const wideToggleBtn = document.getElementById("viewerWideToggleBtn");
    const editBtn = document.getElementById("viewerEditBtn");
    const pagerEl = document.getElementById("viewerPager");
    const prevBtn = document.getElementById("viewerPrevBtn");
    const nextBtn = document.getElementById("viewerNextBtn");
    const pagerPos = document.getElementById("viewerPagerPos");
    const bottomNav = document.getElementById("viewerBottomNav");
    const bottomPrevBtn = document.getElementById("viewerBottomPrev");
    const bottomNextBtn = document.getElementById("viewerBottomNext");
    const bottomPrevTitle = document.getElementById("viewerBottomPrevTitle");
    const bottomNextTitle = document.getElementById("viewerBottomNextTitle");
    const bottomPos = document.getElementById("viewerBottomPos");
    const stagePoolEl = document.getElementById("viewerStagePool");
    const stageLoading = document.getElementById("viewerStageLoading");
    const notFoundCard = document.getElementById("viewerNotFound");
    const contentShell = document.getElementById("viewerContentShell");

    const syncBackLinks = () => {
      const portalUrl = `${withBase("/artifacts")}${navSuffix()}`;
      backLink.href = portalUrl;
      const notFoundBack = document.getElementById("notFoundBackLink");
      if (notFoundBack) notFoundBack.href = portalUrl;
    };
    syncBackLinks();

    const MAX_WARM_FRAMES = 5;
    const bundleCache = new Map(); // slug -> bundle
    const inflightBundles = new Map(); // slug -> Promise<bundle>
    const framePool = new Map(); // slug -> { slug, rev, iframe, ready, height, theme }

    let currentItem = null;
    let currentNav = null;
    let presetGroups = [];
    let canManage = false;
    let isWide = false;
    let loadSerial = 0;
    let prewarmTimer = null;

    const getActiveEntry = () => framePool.get(activeSlug) || null;

    function touchPoolLru(slug) {
      const entry = framePool.get(slug);
      if (!entry) return;
      framePool.delete(slug);
      framePool.set(slug, entry);
      while (framePool.size > MAX_WARM_FRAMES) {
        const oldestKey = framePool.keys().next().value;
        if (!oldestKey || oldestKey === activeSlug) break;
        const oldest = framePool.get(oldestKey);
        framePool.delete(oldestKey);
        if (oldest && oldest.iframe && oldest.iframe.parentNode) {
          oldest.iframe.parentNode.removeChild(oldest.iframe);
        }
      }
    }

    function buildFrameUrl(item) {
      const sha12 = String(item.content_sha256 || "").slice(0, 12);
      const vParam = sha12 ? `&v=${encodeURIComponent(`${sha12}-r3`)}` : "";
      return withBase(`/artifacts/${encodeURIComponent(item.slug)}/frame?theme=${encodeURIComponent(currentTheme)}${vParam}`);
    }

    function revealEntryIfActive(entry) {
      if (!entry || entry.slug !== activeSlug) return;
      entry.iframe.classList.remove("is-pending-paint");
      stageLoading.classList.add("is-hidden");
      schedulePrewarmNeighbors();
    }

    async function ensureWarmFrame(bundle, { makeActive = false } = {}) {
      const item = bundle && bundle.item;
      if (!item || item.builtin) return null;
      const slug = item.slug;
      const rev = String(item.content_sha256 || item.revision || "");

      let entry = framePool.get(slug);
      if (entry && entry.rev !== rev) {
        if (entry.iframe && entry.iframe.parentNode) {
          entry.iframe.parentNode.removeChild(entry.iframe);
        }
        framePool.delete(slug);
        entry = null;
      }

      if (!entry) {
        const iframe = document.createElement("iframe");
        iframe.className = "viewer-stage-frame is-warm is-pending-paint";
        iframe.title = `${localizedTitle(item)} · Interactive Artifact Stage`;
        iframe.setAttribute("sandbox", "allow-scripts allow-downloads allow-popups");
        iframe.setAttribute("referrerpolicy", "no-referrer");
        iframe.dataset.slug = slug;

        entry = {
          slug,
          rev,
          iframe,
          ready: false,
          height: 640,
          theme: currentTheme,
        };
        framePool.set(slug, entry);
        stagePoolEl.appendChild(iframe);

        iframe.addEventListener("load", () => {
          if (iframe.contentWindow) {
            iframe.contentWindow.postMessage({ type: "ra-artifact-theme", theme: currentTheme }, "*");
            iframe.contentWindow.postMessage({ type: "ra-artifact-ping" }, "*");
          }
          setTimeout(() => {
            if (!entry.ready) {
              entry.ready = true;
              revealEntryIfActive(entry);
            }
          }, 260);
        });

        if (bundle.frame_html) {
          const twSource = bundle.frame_html.includes(TAILWIND_SLOT)
            ? await getTailwindSource()
            : "";
          // Entry may have been evicted while awaiting Tailwind fetch.
          if (framePool.get(slug) !== entry) return null;
          entry.theme = currentTheme;
          iframe.srcdoc = buildSrcdocHtml(bundle.frame_html, currentTheme, twSource);
        } else {
          entry.theme = currentTheme;
          iframe.src = buildFrameUrl(item);
        }
      }

      touchPoolLru(slug);

      if (makeActive) {
        for (const [k, other] of framePool.entries()) {
          if (k === slug) {
            other.iframe.id = "artifactStageFrame";
            other.iframe.classList.remove("is-warm");
            other.iframe.classList.add("is-active");
          } else {
            if (other.iframe.id === "artifactStageFrame") other.iframe.removeAttribute("id");
            other.iframe.classList.remove("is-active");
            other.iframe.classList.add("is-warm");
          }
        }
        if (entry.theme !== currentTheme && entry.iframe.contentWindow) {
          entry.theme = currentTheme;
          entry.iframe.contentWindow.postMessage({ type: "ra-artifact-theme", theme: currentTheme }, "*");
        }
        entry.iframe.style.height = `${entry.height}px`;
        if (entry.ready) {
          entry.iframe.classList.remove("is-pending-paint");
          stageLoading.classList.add("is-hidden");
          if (entry.iframe.contentWindow) {
            entry.iframe.contentWindow.postMessage({ type: "ra-artifact-ping" }, "*");
          }
          schedulePrewarmNeighbors();
        } else {
          stageLoading.classList.remove("is-hidden");
        }
      }
      return entry;
    }

    function fetchArtifactBundle(slugToLoad) {
      if (bundleCache.has(slugToLoad)) {
        return Promise.resolve(bundleCache.get(slugToLoad));
      }
      if (inflightBundles.has(slugToLoad)) {
        return inflightBundles.get(slugToLoad);
      }
      const qs = new URLSearchParams(navContext.toString());
      qs.set("include_frame", "1");
      const promise = apiJson(`/api/artifacts/${encodeURIComponent(slugToLoad)}?${qs.toString()}`)
        .then((data) => {
          bundleCache.set(slugToLoad, data);
          inflightBundles.delete(slugToLoad);
          return data;
        })
        .catch((err) => {
          inflightBundles.delete(slugToLoad);
          throw err;
        });
      inflightBundles.set(slugToLoad, promise);
      return promise;
    }

    function schedulePrewarmNeighbors() {
      if (prewarmTimer) clearTimeout(prewarmTimer);
      const navSnapshot = currentNav;
      if (!navSnapshot) return;
      const targets = [navSnapshot.next, navSnapshot.prev].filter(
        (n) => n && n.slug && !n.builtin && !framePool.has(n.slug),
      );
      if (!targets.length) return;
      prewarmTimer = setTimeout(async () => {
        for (const neighbor of targets) {
          if (framePool.has(neighbor.slug)) continue;
          try {
            const bundle = await fetchArtifactBundle(neighbor.slug);
            if (bundle && bundle.item && !bundle.item.builtin) {
              await ensureWarmFrame(bundle, { makeActive: false });
            }
          } catch (_) {
            // Best-effort prefetch; ignore transient errors.
          }
        }
      }, 120);
    }

    const editModal = createEditModalController({
      onSaved: (updated) => {
        if (updated) {
          currentItem = updated;
          const cached = bundleCache.get(updated.slug);
          if (cached) cached.item = updated;
          renderMeta();
        }
      },
    });

    function navigateToNeighbor(target) {
      if (!target || !target.slug) return;
      if (target.builtin && target.url_path && target.url_path !== `/artifacts/${target.slug}`) {
        window.location.assign(`${withBase(target.url_path)}${navSuffix()}`);
        return;
      }
      const activeEntry = getActiveEntry();
      if (activeEntry && document.activeElement === activeEntry.iframe && typeof activeEntry.iframe.blur === "function") {
        activeEntry.iframe.blur();
      }
      const nextUrl = `${withBase(`/artifacts/${encodeURIComponent(target.slug)}`)}${navSuffix()}`;
      window.history.pushState({ slug: target.slug }, "", nextUrl);
      activeSlug = target.slug;
      loadViewer(activeSlug);
      window.scrollTo({ top: 0, behavior: "instant" });
    }

    function stepDirection(dir) {
      if (!currentNav) return;
      const modalBackdrop = document.getElementById("editModalBackdrop");
      if (modalBackdrop && !modalBackdrop.hidden) return;
      const target = dir < 0 ? currentNav.prev : currentNav.next;
      if (target) navigateToNeighbor(target);
    }

    prevBtn.addEventListener("click", () => stepDirection(-1));
    nextBtn.addEventListener("click", () => stepDirection(1));
    bottomPrevBtn.addEventListener("click", () => stepDirection(-1));
    bottomNextBtn.addEventListener("click", () => stepDirection(1));

    window.addEventListener("keydown", (event) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const target = event.target;
      const tag = target && target.tagName ? String(target.tagName).toUpperCase() : "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (target && target.isContentEditable)) return;
      if (event.key === "ArrowLeft" || event.key === "[") {
        if (currentNav && currentNav.prev) {
          event.preventDefault();
          stepDirection(-1);
        }
      } else if (event.key === "ArrowRight" || event.key === "]") {
        if (currentNav && currentNav.next) {
          event.preventDefault();
          stepDirection(1);
        }
      }
    });

    window.addEventListener("popstate", () => {
      activeSlug = parseSlugFromPath(window.location.pathname);
      const nextCtx = extractNavContext(window.location.search);
      if (nextCtx.toString() !== navContext.toString()) {
        navContext = nextCtx;
        bundleCache.clear();
        syncBackLinks();
      }
      loadViewer(activeSlug);
    });

    window.addEventListener("message", (event) => {
      let matchedEntry = null;
      for (const entry of framePool.values()) {
        if (entry.iframe && entry.iframe.contentWindow === event.source) {
          matchedEntry = entry;
          break;
        }
      }
      if (!matchedEntry) return;
      const data = event.data;
      if (!data || typeof data !== "object") return;
      if ((data.type === "ra-artifact-height" || data.type === "ra-artifact-ready") && Number.isFinite(Number(data.height))) {
        const nextHeight = Math.max(260, Math.min(20000, Math.ceil(Number(data.height))));
        matchedEntry.height = nextHeight;
        matchedEntry.iframe.style.height = `${nextHeight}px`;
        if (data.type === "ra-artifact-ready" || matchedEntry.ready) {
          matchedEntry.ready = true;
          revealEntryIfActive(matchedEntry);
        }
      } else if (data.type === "ra-artifact-nav" && matchedEntry.slug === activeSlug && (data.dir === -1 || data.dir === 1)) {
        stepDirection(data.dir);
      }
    });

    wideToggleBtn.addEventListener("click", () => {
      isWide = !isWide;
      wrap.classList.toggle("is-wide", isWide);
      wideToggleBtn.textContent = isWide ? t("viewer.wideOff") : t("viewer.wideOn");
      const activeEntry = getActiveEntry();
      if (activeEntry && activeEntry.iframe.contentWindow) {
        setTimeout(() => activeEntry.iframe.contentWindow.postMessage({ type: "ra-artifact-ping" }, "*"), 80);
      }
    });

    copyLinkBtn.addEventListener("click", () => {
      if (currentItem) copyShareUrl(currentItem.url_path);
    });

    editBtn.addEventListener("click", () => {
      if (currentItem && editModal) editModal.open(currentItem, presetGroups);
    });

    function renderNavigation() {
      const nav = currentNav;
      if (!nav || !nav.total || nav.total <= 1) {
        pagerEl.hidden = true;
        bottomNav.hidden = true;
        return;
      }
      const posText = `${nav.index} / ${nav.total}`;
      pagerPos.textContent = posText;
      bottomPos.textContent = posText;

      const prev = nav.prev;
      const next = nav.next;
      const prevTitle = prev ? localizedTitle(prev) : "";
      const nextTitle = next ? localizedTitle(next) : "";

      prevBtn.disabled = !prev;
      nextBtn.disabled = !next;
      prevBtn.title = prev ? t("viewer.prevTooltip", { title: prevTitle }) : t("viewer.noPrev");
      prevBtn.setAttribute("aria-label", prevBtn.title);
      nextBtn.title = next ? t("viewer.nextTooltip", { title: nextTitle }) : t("viewer.noNext");
      nextBtn.setAttribute("aria-label", nextBtn.title);

      bottomPrevBtn.disabled = !prev;
      bottomNextBtn.disabled = !next;
      bottomPrevTitle.textContent = prev ? prevTitle : t("viewer.noPrev");
      bottomNextTitle.textContent = next ? nextTitle : t("viewer.noNext");

      pagerEl.hidden = false;
      bottomNav.hidden = false;
    }

    function renderMeta() {
      if (!currentItem) return;
      const title = localizedTitle(currentItem);
      const summary = localizedSummary(currentItem);
      const groupLabel = localizedGroup(currentItem);

      document.title = `${title} · ${t("portal.brand")}`;
      document.getElementById("viewerCrumbTitle").textContent = title;
      document.getElementById("viewerTitle").textContent = title;
      const summaryEl = document.getElementById("viewerSummary");
      summaryEl.textContent = summary;
      summaryEl.hidden = !summary;

      const chips = [
        `<span class="${groupPillClass(currentItem.group)}">${escapeHtml(groupLabel)}</span>`,
      ];
      if (currentItem.pinned) chips.push(`<span class="pill pill-pin">★ ${escapeHtml(t("portal.pinned"))}</span>`);
      if (currentItem.archived) chips.push(`<span class="pill pill-archived">${escapeHtml(t("portal.archived"))}</span>`);
      for (const tag of (currentItem.tags || [])) {
        chips.push(`<span class="artifact-tag">${escapeHtml(tag)}</span>`);
      }
      document.getElementById("viewerMetaChips").innerHTML = chips.join("");

      const details = [
        `slug: ${currentItem.slug}`,
        `v${currentItem.revision} · ${formatBytes(currentItem.size_bytes)}`,
        t("portal.updatedAt", { time: formatTimeCst(currentItem.updated_at) }),
      ];
      if (currentItem.conversation_id) {
        details.push(`${t("portal.convPrefix")}: ${currentItem.conversation_id.slice(0, 8)}`);
      }
      if (currentItem.source_filename) {
        details.push(currentItem.source_filename);
      }
      document.getElementById("viewerMetaDetails").innerHTML = details.map((d) => `<span>${escapeHtml(d)}</span>`).join("");

      openCanvasLink.href = buildFrameUrl(currentItem);
      editBtn.hidden = !canManage;
      wideToggleBtn.textContent = isWide ? t("viewer.wideOff") : t("viewer.wideOn");
      renderNavigation();
    }

    function applyAllText() {
      syncLangControls();
      syncThemeControls();
      if (editModal) editModal.refreshGroupOptions(presetGroups);
      if (currentItem) renderMeta();
      else {
        wideToggleBtn.textContent = isWide ? t("viewer.wideOff") : t("viewer.wideOn");
        renderNavigation();
      }
    }

    document.getElementById("langToggleBtn").addEventListener("click", () => {
      currentLang = currentLang === "en" ? "zh" : "en";
      try { localStorage.setItem("ra-triage-ui-language", currentLang); } catch (_) {}
      applyAllText();
    });

    document.getElementById("themeToggleBtn").addEventListener("click", () => {
      currentTheme = currentTheme === "light" ? "dark" : "light";
      try { localStorage.setItem("ra-triage-color-theme", currentTheme); } catch (_) {}
      for (const entry of framePool.values()) {
        entry.theme = currentTheme;
      }
      syncThemeControls();
      if (currentItem) {
        openCanvasLink.href = buildFrameUrl(currentItem);
      }
    });

    async function loadViewer(slugToLoad, initialBundle = null) {
      const seq = ++loadSerial;
      syncLangControls();
      syncThemeControls();
      const existingEntry = framePool.get(slugToLoad);
      if (!existingEntry || !existingEntry.ready) {
        stageLoading.classList.remove("is-hidden");
      }
      try {
        const data = initialBundle || await fetchArtifactBundle(slugToLoad);
        if (seq !== loadSerial) return;
        currentItem = data.item;
        currentNav = data.navigation || null;
        if (data.can_manage) canManage = true;
        presetGroups = Array.isArray(data.preset_groups) ? data.preset_groups : presetGroups;
        if (currentItem.builtin && currentItem.url_path && currentItem.url_path !== `/artifacts/${currentItem.slug}`) {
          window.location.replace(`${withBase(currentItem.url_path)}${navSuffix()}`);
          return;
        }
        notFoundCard.hidden = true;
        contentShell.hidden = false;
        renderMeta();
        await ensureWarmFrame(data, { makeActive: true });
      } catch (_) {
        if (seq !== loadSerial) return;
        currentItem = null;
        currentNav = null;
        pagerEl.hidden = true;
        bottomNav.hidden = true;
        contentShell.hidden = true;
        notFoundCard.hidden = false;
      }
    }

    const initialBootstrap = readBootstrapJson("raArtifactBootstrap");
    if (initialBootstrap && initialBootstrap.item && initialBootstrap.item.slug === activeSlug) {
      bundleCache.set(activeSlug, initialBootstrap);
      loadViewer(activeSlug, initialBootstrap);
    } else {
      loadViewer(activeSlug);
    }

    // Resolve SSO edit permission asynchronously without delaying chart render.
    if (!canManage) {
      resolveManageAccess().then((allowed) => {
        if (allowed && !canManage) {
          canManage = true;
          if (currentItem) editBtn.hidden = false;
        }
      });
    }
  }

  function boot() {
    const pageMode = document.body && document.body.dataset ? document.body.dataset.page : "";
    if (pageMode === "portal") initPortal();
    else if (pageMode === "viewer") initViewer();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
