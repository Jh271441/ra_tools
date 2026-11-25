import { getWorkbenchBasePath, UiLanguage, withWorkbenchBase } from "../bridge/useWorkbenchBridge";

export type WorkbenchPageId =
  | "review"
  | "labeling"
  | "labeling-new-task"
  | "labeling-summary"
  | "rd-results"
  | "trail-update"
  | "review-assignments"
  | "analysis"
  | "runs"
  | "comparison"
  | "run-collections"
  | "prediction"
  | "campaigns"
  | "version-datasets"
  | "version-metrics"
  | "daily-cron"
  | "daily-review"
  | "intent"
  | "intent-experiments"
  | "intent-summary"
  | "trail-history"
  | "status"
  | "users";

export interface WorkbenchRouteDef {
  id: WorkbenchPageId;
  path: string;
  aliases?: string[];
  titleZh: string;
  titleEn: string;
  usesIntentDatasets?: boolean;
  hideDatasetPicker?: boolean;
  hideOverviewMetrics?: boolean;
}

export const WORKBENCH_ROUTES: Record<WorkbenchPageId, WorkbenchRouteDef> = {
  review: {
    id: "review",
    path: "/review",
    aliases: ["/"],
    titleZh: "判错复核",
    titleEn: "Failure Review",
  },
  labeling: {
    id: "labeling",
    path: "/case-labeling",
    titleZh: "问题标注",
    titleEn: "Case Labeling",
  },
  "labeling-new-task": {
    id: "labeling-new-task",
    path: "/case-labeling/new-task",
    aliases: ["/labeling-experiments"],
    titleZh: "实验分配",
    titleEn: "Labeling Experiments",
  },
  "labeling-summary": {
    id: "labeling-summary",
    path: "/labeling-summary",
    titleZh: "标注汇总",
    titleEn: "Labeling Summary",
  },
  "rd-results": {
    id: "rd-results",
    path: "/rd-results",
    titleZh: "标注上传",
    titleEn: "Label Upload",
  },
  "trail-update": {
    id: "trail-update",
    path: "/trail-attribute-update",
    titleZh: "问题排除",
    titleEn: "Issue Exclusion",
  },
  "review-assignments": {
    id: "review-assignments",
    path: "/review-assignments",
    titleZh: "任务分配",
    titleEn: "Assignments",
  },
  analysis: {
    id: "analysis",
    path: "/review-analysis",
    aliases: ["/analysis"],
    titleZh: "原因聚类",
    titleEn: "Review Analysis",
  },
  runs: {
    id: "runs",
    path: "/runs",
    aliases: ["/import"],
    titleZh: "模型结果",
    titleEn: "Model Runs",
  },
  comparison: {
    id: "comparison",
    path: "/run-comparison",
    aliases: ["/comparison"],
    titleZh: "Run 对比",
    titleEn: "Run Comparison",
  },
  "run-collections": {
    id: "run-collections",
    path: "/multi-run-evaluation",
    aliases: ["/run-collections"],
    titleZh: "多 Run 评测",
    titleEn: "Multi-Run Evaluation",
  },
  prediction: {
    id: "prediction",
    path: "/batch-prediction",
    aliases: ["/inference"],
    titleZh: "批次预测",
    titleEn: "Batch Prediction",
  },
  campaigns: {
    id: "campaigns",
    path: "/campaigns",
    titleZh: "任务与标注汇总",
    titleEn: "Campaigns & Label Analysis",
  },
  "version-datasets": {
    id: "version-datasets",
    path: "/version-datasets",
    titleZh: "版本数据",
    titleEn: "Version Datasets",
    hideDatasetPicker: true,
    hideOverviewMetrics: true,
  },
  "version-metrics": {
    id: "version-metrics",
    path: "/version-metrics",
    titleZh: "版本指标",
    titleEn: "Version Metrics",
    hideDatasetPicker: true,
    hideOverviewMetrics: true,
  },
  "daily-cron": {
    id: "daily-cron",
    path: "/daily-cron",
    titleZh: "每日任务",
    titleEn: "Daily Tasks",
    hideDatasetPicker: true,
    hideOverviewMetrics: true,
  },
  "daily-review": {
    id: "daily-review",
    path: "/daily-review",
    titleZh: "标注进度",
    titleEn: "TE Progress",
    hideDatasetPicker: true,
    hideOverviewMetrics: true,
  },
  intent: {
    id: "intent",
    path: "/intent-labeling",
    titleZh: "意图标注",
    titleEn: "Intent Labeling",
    usesIntentDatasets: true,
    hideOverviewMetrics: true,
  },
  "intent-experiments": {
    id: "intent-experiments",
    path: "/intent-experiments",
    titleZh: "实验分配",
    titleEn: "Intent Experiments",
    usesIntentDatasets: true,
    hideOverviewMetrics: true,
  },
  "intent-summary": {
    id: "intent-summary",
    path: "/intent-summary",
    titleZh: "标注汇总",
    titleEn: "Intent Summary",
    usesIntentDatasets: true,
    hideOverviewMetrics: true,
  },
  "trail-history": {
    id: "trail-history",
    path: "/trail-update-history",
    titleZh: "Trail 更新记录",
    titleEn: "Trail Update History",
    hideOverviewMetrics: true,
  },
  status: {
    id: "status",
    path: "/system-status",
    titleZh: "系统状态",
    titleEn: "System Status",
    hideDatasetPicker: true,
    hideOverviewMetrics: true,
  },
  users: {
    id: "users",
    path: "/users",
    titleZh: "用户管理",
    titleEn: "User Access",
    hideDatasetPicker: true,
    hideOverviewMetrics: true,
  },
};

export function stripWorkbenchBase(pathname: string): string {
  const base = getWorkbenchBasePath();
  let p = String(pathname || "/").trim() || "/";
  if (base && (p === base || p.startsWith(`${base}/`))) {
    p = p.slice(base.length) || "/";
  }
  if (p.length > 1 && p.endsWith("/")) {
    p = p.slice(0, -1);
  }
  return p || "/";
}

export function resolvePageFromLocation(
  pathname: string = typeof window !== "undefined" ? window.location.pathname : "/review",
  search: string = typeof window !== "undefined" ? window.location.search : "",
): WorkbenchPageId {
  const clean = stripWorkbenchBase(pathname);
  const params = new URLSearchParams(search);
  if (clean === "/campaigns" && params.get("purpose") === "model_review") {
    return "review";
  }
  for (const def of Object.values(WORKBENCH_ROUTES)) {
    if (def.path === clean || def.aliases?.includes(clean)) {
      return def.id;
    }
  }
  return "review";
}

export function buildWorkbenchPageUrl(
  page: WorkbenchPageId,
  params?: Record<string, string | string[] | number | boolean | null | undefined>,
): string {
  const def = WORKBENCH_ROUTES[page] || WORKBENCH_ROUTES.review;
  const search = new URLSearchParams();
  if (params) {
    for (const [key, raw] of Object.entries(params)) {
      if (raw == null || raw === "" || raw === false) continue;
      if (Array.isArray(raw)) {
        const cleaned = raw.map((v) => String(v).trim()).filter(Boolean);
        if (cleaned.length) search.set(key, cleaned.join(","));
      } else {
        search.set(key, String(raw));
      }
    }
  }
  const qs = search.toString();
  return `${withWorkbenchBase(def.path)}${qs ? `?${qs}` : ""}`;
}

export function pageTitle(page: WorkbenchPageId, lang: UiLanguage): string {
  const def = WORKBENCH_ROUTES[page] || WORKBENCH_ROUTES.review;
  return lang === "en" ? def.titleEn : def.titleZh;
}
