/* ra_triage_dashboard/static/js/core-base.js
 * Constants, base path, page routes, shared state, $
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
const LABELS = ["误触发", "正确触发", "无需协助"];
const CASE_PAGE_SIZES = [10, 20, 50, 100];
const DEFAULT_CASE_PAGE_SIZE = 20;
const ANALYSIS_COMPARISON_STATUSES = ["all", "mismatch", "match", "none"];
const ANALYSIS_COMPARISON_META = {
  all: { label: "全部", description: "不按模型判断结果收窄" },
  mismatch: { label: "MISMATCH", description: "GT 与模型输出不一致" },
  match: { label: "MATCH", description: "GT 与模型输出一致" },
  none: { label: "NONE", description: "该 Run 未预测" },
};
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
  const placeholder = root.dataset.placeholder || "全部";
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
  summary.textContent =
    labels.length <= 2
      ? labels.join("、")
      : `${labels[0]} 等 ${labels.length} 项`;
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

  panel.style.top = `${Math.round(top)}px`;
  panel.style.left = `${Math.round(left)}px`;
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
  cases: [],
  caseTotal: 0,
  casePage: 1,
  casePageSize: DEFAULT_CASE_PAGE_SIZE,
  reviewIssueIds: [],
  workAssignees: [],
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
