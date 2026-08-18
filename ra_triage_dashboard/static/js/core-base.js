/* ra_triage_dashboard/static/js/core-base.js
 * Constants, base path, page routes, shared state, $
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
const LABELS = ["误触发", "正确触发", "无需协助"];
const CASE_PAGE_SIZES = [10, 20, 50, 100];
const DEFAULT_CASE_PAGE_SIZE = 20;
const ANALYSIS_COMPARISON_STATUSES = ["all", "mismatch", "match", "none"];
/** Locale-aware comparison option meta (GT taxonomy stays Chinese elsewhere). */
function comparisonStatusMeta(status) {
  const key = String(status || "all");
  const table = {
    all: { label: () => t("common.all"), description: () => t("comparison.desc_all") },
    mismatch: { label: () => "MISMATCH", description: () => t("comparison.desc_mismatch") },
    match: { label: () => "MATCH", description: () => t("comparison.desc_match") },
    none: { label: () => "NONE", description: () => t("comparison.desc_none") },
  };
  const entry = table[key] || table.all;
  return { label: entry.label(), description: entry.description() };
}
const ANALYSIS_COMPARISON_META = new Proxy(
  {},
  {
    get(_target, prop) {
      if (prop === "all" || prop === "mismatch" || prop === "match" || prop === "none") {
        return comparisonStatusMeta(prop);
      }
      return undefined;
    },
  }
);
const REVIEW_COMPARISON_STATUSES = ANALYSIS_COMPARISON_STATUSES;
const REVIEW_COMPARISON_META = ANALYSIS_COMPARISON_META;
const API_GET_TIMEOUT_MS = 6000;
const API_GET_MAX_ATTEMPTS = 3;
const API_GET_RETRYABLE_STATUSES = new Set([408, 429, 502, 503, 504]);

function parseFilterList(value) {
  if (Array.isArray(value)) {
    return [
      ...new Set(
        value
          .map((item) => String(item || "").trim())
          .filter(Boolean)
      ),
    ];
  }
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinFilterList(values) {
  return parseFilterList(values).join(",");
}

function getMultiFilterValues(root) {
  if (!root) return [];
  if (root.matches?.("select")) {
    if (root.multiple) {
      return [...root.selectedOptions].map((option) => option.value).filter(Boolean);
    }
    return root.value ? [root.value] : [];
  }
  return [...root.querySelectorAll('input[type="checkbox"][data-multi-value]:checked')].map(
    (input) => input.value
  );
}

function updateMultiFilterSummary(root) {
  if (!root || root.matches?.("select")) return;
  const summary = root.querySelector(".multi-filter-summary");
  if (!summary) return;
  const values = getMultiFilterValues(root);
  const placeholder =
    typeof t === "function" && root.dataset.i18nPlaceholder
      ? t(root.dataset.i18nPlaceholder)
      : typeof uiText === "function"
        ? uiText(
            root.dataset.placeholder || "全部",
            root.dataset.placeholderEn || root.dataset.placeholder || "All"
          )
        : root.dataset.placeholder || "全部";
  if (!values.length) {
    summary.textContent = placeholder;
    summary.classList.remove("has-value");
    return;
  }
  const labels = values.map((value) => {
    const input = root.querySelector(
      `input[data-multi-value="${CSS.escape(value)}"]`
    );
    return input?.dataset.label || value;
  });
  const en = typeof state !== "undefined" && state.uiLanguage === "en";
  if (labels.length <= 2) {
    summary.textContent = labels.join(en ? ", " : "、");
  } else if (typeof t === "function") {
    summary.textContent = en
      ? `${labels[0]} ${t("multi.plus_n", { n: labels.length - 1 })}`
      : `${labels[0]} ${t("multi.and_n", { n: labels.length })}`;
  } else {
    summary.textContent = en
      ? `${labels[0]} +${labels.length - 1}`
      : `${labels[0]} 等 ${labels.length} 项`;
  }
  summary.classList.add("has-value");
}

function setMultiFilterValues(root, values) {
  if (!root) return;
  const selected = new Set(parseFilterList(values));
  if (root.matches?.("select")) {
    if (root.multiple) {
      [...root.options].forEach((option) => {
        option.selected = selected.has(option.value);
      });
    } else {
      root.value = [...selected][0] || "";
    }
    return;
  }
  root.querySelectorAll('input[type="checkbox"][data-multi-value]').forEach((input) => {
    input.checked = selected.has(input.value);
  });
  updateMultiFilterSummary(root);
}

function closeAllMultiFilters(except = null) {
  document.querySelectorAll(".multi-filter.is-open").forEach((root) => {
    if (except && root === except) return;
    root.classList.remove("is-open");
    const panel = root.querySelector(".multi-filter-panel");
    if (panel) {
      panel.hidden = true;
      resetAnchoredPanel(panel);
    }
    root.querySelector(".multi-filter-trigger")?.setAttribute("aria-expanded", "false");
  });
}

/** Close custom single-selects (ui-select / review-status / media kind). */
function closeAllUiSelects(except = null) {
  document
    .querySelectorAll(
      ".ui-select.is-open, .review-status-picker.is-open, .detail-media-picker.is-open"
    )
    .forEach((root) => {
      if (except && root === except) return;
      root.classList.remove("is-open");
      const panel =
        root.querySelector(".ui-select-panel") ||
        root.querySelector(".review-status-picker-panel") ||
        root.querySelector(".detail-media-picker-panel");
      const trigger =
        root.querySelector(".ui-select-trigger") ||
        root.querySelector(".review-status-picker-trigger") ||
        root.querySelector(".detail-media-picker-trigger");
      if (panel) {
        panel.hidden = true;
        resetAnchoredPanel(panel);
      }
      trigger?.setAttribute("aria-expanded", "false");
    });
}

/**
 * Fill a custom single-select shell.
 * options: [{ value, label, disabled? }]
 * nativeSelect: optional <select> kept for existing .value / change listeners.
 */
function populateUiSelect(root, options, selectedValue = "") {
  if (!root) return;
  const panel =
    root.querySelector(".ui-select-panel") ||
    root.querySelector(".review-status-picker-panel") ||
    root.querySelector(".detail-media-picker-panel");
  const summary =
    root.querySelector(".ui-select-summary") ||
    root.querySelector("#reviewStatusPickerSummary") ||
    root.querySelector(".detail-media-picker-summary");
  const native =
    root.querySelector("select.ui-select-native") ||
    root.querySelector("select.gateway-model-native-select") ||
    root.querySelector("select");
  const list = Array.isArray(options) ? options : [];
  const values = new Set(list.map((item) => String(item.value)));
  let selected = String(selectedValue ?? "");
  if (selected && !values.has(selected)) selected = "";
  if (!selected && list.length) {
    const firstEnabled = list.find((item) => !item.disabled);
    selected = firstEnabled ? String(firstEnabled.value) : String(list[0].value);
  }
  if (native) {
    native.innerHTML = list
      .map((item) => {
        const value = String(item.value);
        const disabled = item.disabled ? " disabled" : "";
        const sel = value === selected ? " selected" : "";
        return `<option value="${escapeHtml(value)}"${disabled}${sel}>${escapeHtml(item.label)}</option>`;
      })
      .join("");
    native.value = selected;
  }
  if (panel) {
    panel.innerHTML = list.length
      ? list
          .map((item) => {
            const value = String(item.value);
            const active = value === selected;
            const disabled = Boolean(item.disabled);
            return `<button class="ui-select-option${active ? " is-active" : ""}${disabled ? " is-disabled" : ""}" type="button" role="option" data-ui-select-value="${escapeHtml(value)}" aria-selected="${active ? "true" : "false"}" ${disabled ? "disabled aria-disabled=\"true\"" : ""} title="${escapeHtml(item.label)}">
              <span class="ui-select-option-check" aria-hidden="true">${active ? "✓" : ""}</span>
              <span class="ui-select-option-label">${escapeHtml(item.label)}</span>
            </button>`;
          })
          .join("")
      : `<div class="multi-filter-empty">${escapeHtml(typeof t === "function" ? t("multi.empty") : "暂无选项")}</div>`;
  }
  if (summary) {
    const active = list.find((item) => String(item.value) === selected);
    summary.textContent =
      active?.label ||
      list[0]?.label ||
      (typeof t === "function" ? t("multi.pick") : "请选择");
  }
  root.classList.toggle("is-disabled", Boolean(native?.disabled));
  const trigger =
    root.querySelector(".ui-select-trigger") ||
    root.querySelector(".review-status-picker-trigger") ||
    root.querySelector(".detail-media-picker-trigger");
  if (trigger) trigger.disabled = Boolean(native?.disabled);
}

function bindUiSelect(root, { onChange, maxHeight = 320, maxWidth = 420 } = {}) {
  if (!root) return;
  const trigger =
    root.querySelector(".ui-select-trigger") ||
    root.querySelector(".review-status-picker-trigger") ||
    root.querySelector(".detail-media-picker-trigger");
  const panel =
    root.querySelector(".ui-select-panel") ||
    root.querySelector(".review-status-picker-panel") ||
    root.querySelector(".detail-media-picker-panel");
  if (!trigger || !panel) return;

  // Replace node re-renders drop listeners; only skip when same element already bound.
  if (trigger.dataset.uiSelectBound === "1") return;
  trigger.dataset.uiSelectBound = "1";

  trigger.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (trigger.disabled || root.classList.contains("is-disabled")) return;
    const willOpen = panel.hidden;
    closeAllUiSelects();
    closeAllMultiFilters();
    if (typeof closeGatewayModelPicker === "function") closeGatewayModelPicker();
    if (typeof closeGatewayProviderPicker === "function") closeGatewayProviderPicker();
    if (!willOpen) return;
    root.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
    const width = trigger.getBoundingClientRect().width;
    openAnchoredPanel(panel, trigger, {
      maxHeight,
      minWidth: Math.max(width, 160),
      matchAnchorWidth: true,
      maxWidth: Math.max(width, maxWidth),
    });
  });

  panel.addEventListener("click", (event) => {
    event.stopPropagation();
    const option = event.target.closest("[data-ui-select-value]");
    if (!option || option.disabled || option.getAttribute("aria-disabled") === "true") return;
    const value = String(option.dataset.uiSelectValue || "");
    const native =
      root.querySelector("select.ui-select-native") ||
      root.querySelector("select.gateway-model-native-select") ||
      root.querySelector("select");
    const label =
      option.querySelector(".ui-select-option-label")?.textContent?.trim() ||
      option.textContent.trim();
    if (native) {
      native.value = value;
      // Keep option list in sync for callers that re-read options later.
      [...native.options].forEach((opt) => {
        opt.selected = opt.value === value;
      });
    }
    panel.querySelectorAll("[data-ui-select-value]").forEach((opt) => {
      const active = opt === option;
      opt.classList.toggle("is-active", active);
      opt.setAttribute("aria-selected", active ? "true" : "false");
      const check = opt.querySelector(".ui-select-option-check");
      if (check) check.textContent = active ? "✓" : "";
    });
    const summary =
      root.querySelector(".ui-select-summary") ||
      root.querySelector("#reviewStatusPickerSummary") ||
      root.querySelector(".detail-media-picker-summary");
    if (summary) summary.textContent = label;
    closeAllUiSelects();
    if (native) {
      native.dispatchEvent(new Event("change", { bubbles: true }));
    }
    onChange?.(value, label);
  });

  if (document.documentElement.dataset.uiSelectDismissBound === "1") return;
  document.documentElement.dataset.uiSelectDismissBound = "1";
  document.addEventListener(
    "click",
    (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (
        target?.closest(
          ".ui-select, .review-status-picker, .detail-media-picker, .ui-select-panel, .review-status-picker-panel, .detail-media-picker-panel"
        )
      ) {
        return;
      }
      closeAllUiSelects();
    },
    true
  );
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Escape") closeAllUiSelects();
    },
    true
  );
  document.addEventListener(
    "scroll",
    (event) => {
      if (
        !document.querySelector(
          ".ui-select.is-open, .review-status-picker.is-open, .detail-media-picker.is-open"
        )
      ) {
        return;
      }
      const target = event.target;
      if (
        target instanceof Element &&
        target.closest(
          ".ui-select-panel, .review-status-picker-panel, .detail-media-picker-panel"
        )
      ) {
        return;
      }
      closeAllUiSelects();
    },
    true
  );
  window.addEventListener("resize", () => closeAllUiSelects());
}

/** Park a dropdown panel off-screen before first paint (no absolute-down flash). */
function prepareAnchoredPanel(panel) {
  if (!panel) return;
  panel.classList.add("is-fixed-dropdown", "is-measuring");
  panel.classList.remove("is-positioned", "is-drop-up", "is-drop-down");
  panel.style.position = "fixed";
  panel.style.right = "auto";
  panel.style.bottom = "auto";
  panel.style.top = "0px";
  panel.style.left = "-10000px";
  panel.style.visibility = "hidden";
  panel.style.opacity = "0";
  panel.style.pointerEvents = "none";
  panel.style.maxHeight = "";
  panel.style.zIndex = "80";
}

function resetAnchoredPanel(panel) {
  if (!panel) return;
  panel.classList.remove(
    "is-fixed-dropdown",
    "is-positioned",
    "is-measuring",
    "is-drop-up",
    "is-drop-down"
  );
  panel.style.position = "";
  panel.style.top = "";
  panel.style.left = "";
  panel.style.right = "";
  panel.style.bottom = "";
  panel.style.width = "";
  panel.style.minWidth = "";
  panel.style.maxWidth = "";
  panel.style.maxHeight = "";
  panel.style.visibility = "";
  panel.style.opacity = "";
  panel.style.pointerEvents = "";
  panel.style.zIndex = "";
}

/**
 * Place panel near anchor. Prefers opening downward; flips up only when below
 * cannot fit the content and above has more free space.
 * Width is always explicit px (never % of viewport when position:fixed).
 */
function positionAnchoredPanel(panel, anchor, options = {}) {
  if (!panel || !anchor) return { openUp: false };
  const gap = Number(options.gap ?? 4);
  const margin = Number(options.margin ?? 8);
  const maxHeightCap = Number(options.maxHeight ?? 360);
  const minWidth = Number(options.minWidth ?? 0);
  const matchAnchorWidth = options.matchAnchorWidth !== false;
  const maxWidthCap = Number(options.maxWidth ?? 0);

  prepareAnchoredPanel(panel);
  const rect = anchor.getBoundingClientRect();
  const vh = window.innerHeight;
  const vw = window.innerWidth;
  // Pixel width only — CSS min-width:100% on fixed panels resolves to viewport.
  let width = Math.max(
    matchAnchorWidth ? rect.width : 0,
    minWidth,
    120
  );
  const widthCeiling = maxWidthCap > 0
    ? Math.min(maxWidthCap, vw - margin * 2)
    : vw - margin * 2;
  width = Math.min(width, Math.max(120, widthCeiling));
  const widthPx = `${Math.round(width)}px`;
  panel.style.width = widthPx;
  panel.style.minWidth = widthPx;
  panel.style.maxWidth = widthPx;
  panel.style.left = "0px";
  panel.style.top = "0px";

  const naturalH = panel.scrollHeight || panel.getBoundingClientRect().height || 200;
  const spaceBelow = vh - rect.bottom - gap - margin;
  const spaceAbove = rect.top - gap - margin;
  // Prefer down; flip only when below is too short and above is better.
  const openUp =
    spaceBelow < Math.min(naturalH, 160) && spaceAbove > spaceBelow;
  const available = Math.max(100, Math.floor(openUp ? spaceAbove : spaceBelow));
  const maxH = Math.min(available, maxHeightCap, Math.floor(vh * 0.55));
  panel.style.maxHeight = `${maxH}px`;

  const height = Math.min(panel.scrollHeight || naturalH, maxH);
  let top = openUp ? rect.top - height - gap : rect.bottom + gap;
  top = Math.max(margin, Math.min(top, vh - height - margin));
  let left = rect.left;
  left = Math.max(margin, Math.min(left, vw - width - margin));

  // backdrop-filter makes the sticky topbar a containing block for fixed
  // descendants. Convert viewport coordinates back into that local space so
  // the dataset panel stays under its trigger instead of shifting by the
  // sidebar/app-frame offset.
  const fixedRoot = panel.closest(".topbar");
  const fixedOrigin = fixedRoot?.getBoundingClientRect();
  panel.style.top = `${Math.round(top - (fixedOrigin?.top || 0))}px`;
  panel.style.left = `${Math.round(left - (fixedOrigin?.left || 0))}px`;
  panel.classList.remove("is-measuring");
  panel.classList.add("is-fixed-dropdown", "is-positioned");
  panel.classList.add(openUp ? "is-drop-up" : "is-drop-down");
  panel.style.visibility = "";
  panel.style.opacity = "";
  panel.style.pointerEvents = "";
  return { openUp };
}

function openAnchoredPanel(panel, anchor, options = {}) {
  if (!panel || !anchor) return;
  panel.hidden = false;
  prepareAnchoredPanel(panel);
  positionAnchoredPanel(panel, anchor, options);
}

function normalizeClientBasePath(value) {
  const raw = String(value ?? "");
  if (!raw || raw === "/") return "";
  const normalized = raw.endsWith("/") ? raw.slice(0, -1) : raw;
  if (
    normalized.includes("..") ||
    !/^\/(?:[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*)$/.test(normalized)
  ) {
    throw new Error("RA Triage base path 配置非法。");
  }
  return normalized;
}

const CONFIGURED_BASE_PATH = normalizeClientBasePath(
  document.querySelector('meta[name="ra-triage-base"]')?.content || ""
);
const BASE_PATH = normalizeClientBasePath(
  window.__RA_TRIAGE_BASE__ ?? CONFIGURED_BASE_PATH
);

function removeBasePath(path, basePath) {
  if (!basePath) return path;
  if (path === basePath) return "/";
  if (path.startsWith(`${basePath}/`)) return path.slice(basePath.length);
  if (path.startsWith(`${basePath}?`) || path.startsWith(`${basePath}#`)) {
    return `/${path.slice(basePath.length)}`;
  }
  return path;
}

function withBase(path) {
  const value = String(path || "");
  if (/^https?:\/\//i.test(value) || value.startsWith("//")) return value;
  if (!value.startsWith("/")) return value;
  if (
    BASE_PATH &&
    (value === BASE_PATH ||
      value.startsWith(`${BASE_PATH}/`) ||
      value.startsWith(`${BASE_PATH}?`) ||
      value.startsWith(`${BASE_PATH}#`))
  ) {
    return value;
  }
  const logicalPath = removeBasePath(value, CONFIGURED_BASE_PATH);
  if (!BASE_PATH) return logicalPath;
  return `${BASE_PATH}${logicalPath}`;
}

function stripBasePath(pathname) {
  const value = String(pathname || "");
  return removeBasePath(
    removeBasePath(value, BASE_PATH),
    CONFIGURED_BASE_PATH
  );
}

const PAGE_ROUTES = {
  review: {
    path: "/review",
    titleZh: "判错复核",
    titleEn: "Manual Triage Review",
  },
  analysis: {
    path: "/review-analysis",
    titleZh: "原因聚类",
    titleEn: "Review Reason Clusters",
  },
  "trail-update": {
    path: "/trail-attribute-update",
    titleZh: "Trail 属性更新",
    titleEn: "Trail Attribute Update",
  },
  runs: {
    path: "/runs",
    titleZh: "模型结果",
    titleEn: "Model Runs",
  },
  prediction: {
    path: "/batch-prediction",
    titleZh: "批次预测",
    titleEn: "Batch Model Inference",
  },
  status: {
    path: "/system-status",
    titleZh: "系统状态",
    titleEn: "System Status",
  },
  users: {
    path: "/users",
    titleZh: "用户管理",
    titleEn: "User Access",
  },
};

const state = {
  config: null,
  gtSync: null,
  cases: [],
  caseTotal: 0,
  casePage: 1,
  casePageSize: DEFAULT_CASE_PAGE_SIZE,
  reviewIssueIds: [],
  workAssignees: [],
  workAssigneeRequestSeq: 0,
  caseRequestSeq: 0,
  caseListRequestSeq: 0,
  reviewReloadSeq: 0,
  galleryScrollY: 0,
  selectedId: "",
  selectedCase: null,
  modelRuns: [],
  reviewers: [],
  predictionBatches: [],
  predictionBatchTotal: 0,
  predictionBatchDetails: {},
  expandedPredictionBatchId: "",
  predictionRequesters: [],
  batchListRequestSeq: 0,
  batchDefaultModel: null,
  gatewayModels: [],
  gatewayModelStatus: null,
  gatewayModelRequestSeq: 0,
  selectedGatewayModelId: "",
  selectedGatewayProviderId: "",
  batchPrompts: [],
  batchPromptStatus: null,
  batchFacets: {
    models: [],
    prompts: [],
    input_profiles: [],
  },
  batchDraftSource: "",
  batchDefaultName: "",
  selectedRunId: "",
  // Short baseline ids from registry (e.g. ["0508"] or ["0508","0626"]).
  selectedBaselineIds: ["0508"],
  baselineCatalog: [],
  reviewComparisonStatus: "all",
  failureOnly: false,
  clusterKey: "",
  reviewQueueStale: false,
  reviewAnalysis: {
    page: 1,
    pageSize: DEFAULT_CASE_PAGE_SIZE,
    requestSeq: 0,
    filterTimer: null,
    data: null,
    comparisonStatus: "mismatch",
  },
  trailUpdate: {
    runId: "",
    tab: "review",
    requestSeq: 0,
    data: null,
    previewKey: "",
    previewLoadedAt: 0,
    loading: false,
    directRequestSeq: 0,
    directData: null,
  },
  selectedAnnotationLabel: "",
  pollingBatchId: "",
  pollTimer: null,
  sessionRetryTimer: null,
  changeRevision: null,
  changePollEpoch: 0,
  changePollTimer: null,
  changePollInFlight: false,
  reviewFormDirty: false,
  deferredDetailRefresh: false,
  reviewEditRunId: "",
  reviewEditBaseAnnotationId: null,
  media: {
    kind: "bev",
    index: 0,
    zoom: 1,
    drag: null,
    snapshot: null,
    requestSeq: 0,
    imageRequestSeq: 0,
  },
  detailMedia: {
    issueId: "",
    kind: "",
    indexes: { bev: 0, camera: 0 },
    loadSeq: 0,
  },
  raEventDialog: { issueId: "", events: [], trailUrl: "" },
  sourcePreview: { runId: "", page: 1, pageSize: 100, pageCount: 1 },
  session: {
    username: "",
    source: "anonymous",
    identity_pending: true,
    authenticated: false,
    verified: false,
    is_admin: false,
    access_role: "viewer",
    can_manage_team_default: false,
    can_write: true,
    read_only: false,
  },
  sidebarCollapsed: false,
  mobileSidebarOpen: false,
  colorTheme: "dark",
  uiLanguage: "zh",
  activePage: "review",
  systemStatus: null,
  accessUsers: [],
  trailInspection: null,
  pendingReviewImages: [],
  savingAnnotation: false,
};

const $ = (selector) => document.querySelector(selector);
