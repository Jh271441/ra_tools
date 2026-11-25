import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, formatCstTime, withWorkbenchBase } from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { MultiSelect, MultiSelectOption } from "../components/ui/MultiSelect";
import { useShortcut } from "../core/shortcutManager";
import { pageTitle, WORKBENCH_ROUTES, WorkbenchPageId } from "./routes";
import { useWorkbench } from "./WorkbenchContext";

const AllocationEditorModal = React.lazy(() =>
  import("../features/allocation/AllocationEditorModal").then((m) => ({
    default: m.AllocationEditorModal,
  })),
);

interface NavItemDef {
  id: string;
  page: WorkbenchPageId;
  zh: string;
  en: string;
  role?: "writer" | "admin" | "intent";
  icon: React.ReactNode;
}

interface NavGroupDef {
  key: string;
  zh: string;
  en: string;
  compactZh: string;
  compactEn: string;
  defaultOpen: boolean;
  intentOnly?: boolean;
  icon: React.ReactNode;
  items: NavItemDef[];
}

const NAV_GROUPS: NavGroupDef[] = [
  {
    key: "labeling",
    zh: "问题标注",
    en: "Case labeling",
    compactZh: "标注",
    compactEn: "Labels",
    defaultOpen: true,
    icon: (
      <svg viewBox="0 0 24 24" focusable="false">
        <rect className="icon-wash" x="4" y="3.5" width="16" height="17" rx="3" />
        <path d="M8 8h8M8 12h8M8 16h5" />
        <path className="icon-emphasis" d="m14 15 2 2 4-5" />
      </svg>
    ),
    items: [
      {
        id: "caseLabelingNavButton",
        page: "labeling",
        zh: "问题标注",
        en: "Case labeling",
        role: "writer",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <rect className="icon-wash" x="4" y="3.5" width="16" height="17" rx="3" />
            <path d="M8 8h8M8 12h8M8 16h5" />
            <path className="icon-emphasis" d="m14 15 2 2 4-5" />
          </svg>
        ),
      },
      {
        id: "labelingExperimentsNavButton",
        page: "labeling-new-task",
        zh: "实验分配",
        en: "Labeling experiments",
        role: "admin",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <path className="icon-wash" d="M4 5h16v14H4z" />
            <path d="M8 8h8M8 12h5M8 16h8" />
            <circle className="icon-emphasis" cx="17" cy="16" r="2" />
          </svg>
        ),
      },
      {
        id: "labelingSummaryNavButton",
        page: "labeling-summary",
        zh: "标注汇总",
        en: "Labeling summary",
        role: "writer",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <path className="icon-wash" d="M4 5h16v14H4z" />
            <path d="M7 16v-4m5 4V8m5 8v-6M6 19h13" />
          </svg>
        ),
      },
      {
        id: "rdResultsNavButton",
        page: "rd-results",
        zh: "标注上传",
        en: "Label upload",
        role: "writer",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <path className="icon-wash" d="M4 15h16v5H4z" />
            <path d="M12 16V4m-4 4 4-4 4 4M4 15v5h16v-5" />
          </svg>
        ),
      },
      {
        id: "trailAttributeUpdateNavButton",
        page: "trail-update",
        zh: "问题排除",
        en: "Issue exclusion",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <path className="icon-wash" d="M5 4.5h14v15H5z" />
            <path d="M8 8h8M8 12h5M8 16h8" />
            <path className="icon-emphasis" d="m15 12 3 3 3-3" />
          </svg>
        ),
      },
    ],
  },
  {
    key: "review",
    zh: "判错复核",
    en: "Failure review",
    compactZh: "复核",
    compactEn: "Review",
    defaultOpen: true,
    icon: (
      <svg viewBox="0 0 24 24" focusable="false">
        <path d="M7 3.5h10v3H7zM5 6.5h14v14H5z" />
        <path d="m8 13 2.3 2.3L16 9.8" />
      </svg>
    ),
    items: [
      {
        id: "reviewNavButton",
        page: "review",
        zh: "判错复核",
        en: "Failure review",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <rect className="icon-wash" x="3.5" y="4.5" width="17" height="16" rx="3" />
            <path className="icon-emphasis" d="m8 12 2.1 2.1L16.4 8.8" />
            <path d="M8 17h8" />
          </svg>
        ),
      },
      {
        id: "reviewAssignmentsNavButton",
        page: "review-assignments",
        zh: "任务分配",
        en: "Assignments",
        role: "writer",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <rect className="icon-wash" x="4" y="4" width="16" height="16" rx="3" />
            <path d="M8 8h8M8 12h5M8 16h8" />
            <path className="icon-emphasis" d="m14 12 2 2 4-5" />
          </svg>
        ),
      },
      {
        id: "reviewAnalysisNavButton",
        page: "analysis",
        zh: "原因聚类",
        en: "Review analysis",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <circle cx="7" cy="7" r="2.5" />
            <circle cx="17" cy="7" r="2.5" />
            <circle className="icon-emphasis" cx="12" cy="17" r="2.5" />
            <path d="m8.8 8.3 2 5.8m4.4-5.8-2 5.8M9.6 7h4.8" />
          </svg>
        ),
      },
      {
        id: "openRunManagerButton",
        page: "runs",
        zh: "模型结果",
        en: "Model Runs",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M5 19V9m7 10V5m7 14v-7M3 19h18" />
            <path className="icon-emphasis" d="m5 7 7-4 7 6" />
          </svg>
        ),
      },
      {
        id: "runComparisonNavButton",
        page: "comparison",
        zh: "Run 对比",
        en: "Run comparison",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M7 8h9m-2-3 3 3-3 3M17 16H8m2-3-3 3 3 3" />
            <circle className="icon-emphasis" cx="7" cy="8" r="1.6" />
            <circle className="icon-emphasis" cx="17" cy="16" r="1.6" />
          </svg>
        ),
      },
      {
        id: "openBatchPredictionButton",
        page: "prediction",
        zh: "批次预测",
        en: "Batch prediction",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <rect className="icon-wash" x="3.5" y="3.5" width="9" height="9" rx="2.5" />
            <path className="icon-emphasis" d="m13.5 11 5 3-5 3z" />
          </svg>
        ),
      },
    ],
  },
  {
    key: "daily",
    zh: "每日数据",
    en: "Daily data",
    compactZh: "每日",
    compactEn: "Daily",
    defaultOpen: true,
    icon: (
      <svg viewBox="0 0 24 24" focusable="false">
        <path className="icon-wash" d="M3 6h7l2 2h9v12H3z" />
        <path d="M3 6h7l2 2h9v12H3zM3 11h18" />
      </svg>
    ),
    items: [
      {
        id: "versionDatasetsNavButton",
        page: "version-datasets",
        zh: "版本数据",
        en: "Version datasets",
        icon: <span aria-hidden="true">◫</span>,
      },
      {
        id: "versionMetricsNavButton",
        page: "version-metrics",
        zh: "版本指标",
        en: "Version metrics",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M4 4v16h16" />
            <path className="icon-emphasis" d="m7 14 4-4 4 3 5-7" />
          </svg>
        ),
      },
      {
        id: "dailyCronNavButton",
        page: "daily-cron",
        zh: "每日任务",
        en: "Daily tasks",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <circle className="icon-wash" cx="12" cy="12" r="9" />
            <circle cx="12" cy="12" r="9" />
            <path className="icon-emphasis" d="M12 7v5l3 2" />
          </svg>
        ),
      },
    ],
  },
  {
    key: "intent",
    zh: "意图标注",
    en: "Intent labeling",
    compactZh: "意图",
    compactEn: "Intent",
    defaultOpen: false,
    intentOnly: true,
    icon: (
      <svg viewBox="0 0 24 24" focusable="false">
        <path d="M4 5h16v14H4z" />
        <circle cx="8" cy="10" r="2" />
        <circle cx="16" cy="10" r="2" />
      </svg>
    ),
    items: [
      {
        id: "intentLabelingNavButton",
        page: "intent",
        zh: "意图标注",
        en: "Intent labeling",
        role: "intent",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <rect className="icon-wash" x="4" y="3.5" width="16" height="17" rx="3" />
            <path className="icon-emphasis" d="m14 13 2 2 4-5" />
          </svg>
        ),
      },
      {
        id: "intentExperimentsNavButton",
        page: "intent-experiments",
        zh: "实验分配",
        en: "Experiment assignment",
        role: "intent",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <path className="icon-wash" d="M4 5h16v14H4z" />
            <circle cx="8" cy="10" r="2" />
            <circle cx="16" cy="10" r="2" />
          </svg>
        ),
      },
      {
        id: "intentSummaryNavButton",
        page: "intent-summary",
        zh: "标注汇总",
        en: "Intent summary",
        role: "intent",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <path className="icon-wash" d="M4 5h16v14H4z" />
            <path d="M7 16v-4m5 4V8m5 8v-6M6 19h13" />
          </svg>
        ),
      },
    ],
  },
  {
    key: "system",
    zh: "系统管理",
    en: "System",
    compactZh: "系统",
    compactEn: "System",
    defaultOpen: false,
    icon: (
      <svg viewBox="0 0 24 24" focusable="false">
        <circle cx="12" cy="12" r="3" />
        <path d="M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4" />
      </svg>
    ),
    items: [
      {
        id: "trailHistoryNavButton",
        page: "trail-history",
        zh: "Trail 更新记录",
        en: "Trail history",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M4 5v5h5M4 10a8 8 0 1 1 0 5M12 7v5l3 2" />
          </svg>
        ),
      },
      {
        id: "systemStatusNavButton",
        page: "status",
        zh: "系统状态",
        en: "System status",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <rect className="icon-wash" x="4.5" y="4" width="15" height="13" rx="3" />
            <path className="icon-emphasis" d="M8 11h2l1.2-3 2 6 1.2-3H16" />
          </svg>
        ),
      },
      {
        id: "userManagementNavButton",
        page: "users",
        zh: "用户管理",
        en: "User access",
        role: "admin",
        icon: (
          <svg viewBox="0 0 24 24" focusable="false">
            <circle className="icon-wash" cx="9" cy="8" r="3.5" />
            <path d="M3.5 18c.5-3.1 2.3-4.8 5.5-4.8s5 1.7 5.5 4.8M16 8.5h4M18 6.5v4" />
          </svg>
        ),
      },
    ],
  },
];

const SIDEBAR_GROUPS_KEY = "ra-triage-sidebar-nav-groups-v1";

function readInitialSidebarCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  if (typeof window.matchMedia === "function" && window.matchMedia("(max-width: 1200px)").matches) {
    return true;
  }
  try {
    return localStorage.getItem("ra-triage-sidebar-collapsed") === "true";
  } catch {
    return false;
  }
}

function readInitialGroupOpenState(): Record<string, boolean> {
  const defaults: Record<string, boolean> = {};
  for (const g of NAV_GROUPS) defaults[g.key] = g.defaultOpen;
  if (typeof window === "undefined") return defaults;
  try {
    const raw = JSON.parse(localStorage.getItem(SIDEBAR_GROUPS_KEY) || "null");
    if (raw && typeof raw === "object") {
      return { ...defaults, ...raw };
    }
  } catch {
    // ignore
  }
  return defaults;
}

export const AppShell: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const queryClient = useQueryClient();
  const {
    activePage,
    lang,
    theme,
    toggleLang,
    toggleTheme,
    navigate,
    session,
    config,
    baselines,
    selectedBaselines,
    setSelectedBaselines,
    intentDatasets,
    selectedIntentDatasets,
    setSelectedIntentDatasets,
    overview,
    toasts,
    showToast,
    dismissToast,
    refreshActivePage,
    allocationCampaignId,
    closeAllocationEditor,
  } = useWorkbench();

  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(readInitialSidebarCollapsed);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(readInitialGroupOpenState);
  const [shortcutGuideOpen, setShortcutGuideOpen] = useState(false);
  const [gtTooltipOpen, setGtTooltipOpen] = useState(false);
  const [mobileMoreOpen, setMobileMoreOpen] = useState(false);
  const resizerDragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  const routeDef = WORKBENCH_ROUTES[activePage] || WORKBENCH_ROUTES.review;

  // Ensure active nav group is expanded when navigating
  useEffect(() => {
    const group = NAV_GROUPS.find((g) => g.items.some((item) => item.page === activePage));
    if (group && !openGroups[group.key]) {
      setOpenGroups((prev) => ({ ...prev, [group.key]: true }));
    }
    setMobileDrawerOpen(false);
    setMobileMoreOpen(false);
  }, [activePage]);

  // Close drawer on Escape
  useEffect(() => {
    if (!mobileDrawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileDrawerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileDrawerOpen]);

  const toggleSidebar = useCallback(() => {
    const isNarrow =
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(max-width: 1200px)").matches;
    if (isNarrow) {
      setMobileDrawerOpen((v) => !v);
    } else {
      setSidebarCollapsed((prev) => {
        const next = !prev;
        try {
          localStorage.setItem("ra-triage-sidebar-collapsed", String(next));
        } catch {
          // ignore
        }
        return next;
      });
    }
  }, []);

  const toggleGroup = useCallback((key: string) => {
    setOpenGroups((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      try {
        localStorage.setItem(SIDEBAR_GROUPS_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      return next;
    });
  }, []);

  // Global keyboard shortcuts via ShortcutManager
  useShortcut("global", "\\", () => {
    toggleSidebar();
  });
  useShortcut("global", "h", () => {
    setShortcutGuideOpen((v) => !v);
  });
  useShortcut("global", "r", () => {
    refreshActivePage();
  });

  // Sidebar drag-resizer
  const startSidebarResize = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const sidebar = document.getElementById("appSidebar");
    const currentWidth = sidebar ? sidebar.getBoundingClientRect().width : 240;
    resizerDragRef.current = { startX: e.clientX, startWidth: currentWidth };
    const onMove = (ev: PointerEvent) => {
      if (!resizerDragRef.current) return;
      const next = Math.max(
        190,
        Math.min(420, Math.round(resizerDragRef.current.startWidth + ev.clientX - resizerDragRef.current.startX)),
      );
      document.documentElement.style.setProperty("--app-sidebar-width", `${next}px`);
    };
    const onUp = () => {
      if (resizerDragRef.current) {
        const val = parseInt(
          getComputedStyle(document.documentElement).getPropertyValue("--app-sidebar-width") || "240",
          10,
        );
        if (Number.isFinite(val)) {
          try {
            localStorage.setItem("ra-triage-sidebar-width", String(val));
          } catch {
            // ignore
          }
        }
      }
      resizerDragRef.current = null;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  // GT Sync status & mutation
  const gtSyncRaw = (config?.gt_sync || {}) as {
    status?: string;
    enabled?: boolean;
    source_view_id?: number;
    interval_seconds?: number;
    baselines?: Array<{
      baseline_id?: string;
      baseline_label?: string;
      status?: string;
      last_checked_at?: string;
      source_row_count?: number;
      target_row_count?: number;
      last_check_change_count?: number;
    }>;
  };
  const gtSyncItems = useMemo(() => {
    const all = Array.isArray(gtSyncRaw.baselines) ? gtSyncRaw.baselines : [];
    if (!selectedBaselines.length) return all;
    const picked = all.filter((item) => item.baseline_id && selectedBaselines.includes(item.baseline_id));
    return picked.length ? picked : all.slice(0, 3);
  }, [gtSyncRaw.baselines, selectedBaselines]);

  const gtSyncMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ status?: string; message?: string; last_check_change_count?: number }>("/api/gt-sync", {
        method: "POST",
        body: JSON.stringify({
          requested_by: session.username || "",
          baselines: selectedBaselines,
        }),
      }),
    onSuccess: (res) => {
      void queryClient.invalidateQueries({ queryKey: ["dashboard-config"] });
      void queryClient.invalidateQueries({ queryKey: ["workbench-overview"] });
      showToast(
        res.message ||
          bilingual(lang, "GT 同步请求已受理。", "GT sync request accepted."),
        res.status === "failed",
      );
    },
    onError: (err: Error) => {
      showToast(err.message, true);
    },
  });

  const gtSyncState = useMemo(() => {
    if (gtSyncMutation.isPending || gtSyncRaw.status === "running") return "running";
    const statuses = gtSyncItems.map((i) => String(i.status || "not_started"));
    if (statuses.some((s) => s === "running")) return "running";
    if (statuses.some((s) => s === "failed" || s === "unavailable")) return "failed";
    if (statuses.length && statuses.every((s) => s === "ready")) return "ready";
    return "not_started";
  }, [gtSyncMutation.isPending, gtSyncRaw.status, gtSyncItems]);

  const gtSyncLatestTime = useMemo(() => {
    const times = gtSyncItems.map((i) => i.last_checked_at).filter(Boolean) as string[];
    if (!times.length) {
      return gtSyncState === "running"
        ? bilingual(lang, "同步中…", "Syncing…")
        : gtSyncState === "failed"
          ? bilingual(lang, "校验不可用", "Unavailable")
          : bilingual(lang, "待校验", "Awaiting check");
    }
    times.sort();
    return formatCstTime(times[times.length - 1], lang).slice(5, 16);
  }, [gtSyncItems, gtSyncState, lang]);

  // Baseline & Intent dataset options
  const baselineOptions = useMemo<MultiSelectOption[]>(
    () =>
      baselines
        .filter((b) => !b.hidden)
        .map((b) => ({
          value: b.id,
          label: `${b.label || b.id}${b.count != null ? ` · ${b.count}` : ""}`,
        })),
    [baselines],
  );

  const intentDatasetOptions = useMemo<MultiSelectOption[]>(
    () =>
      intentDatasets.map((d) => ({
        value: d.id,
        label: d.display_name,
      })),
    [intentDatasets],
  );

  const canSeeItem = useCallback(
    (item: NavItemDef): boolean => {
      if (!item.role) return true;
      if (item.role === "admin") return Boolean(session.is_admin);
      if (item.role === "writer") return Boolean(session.can_write || session.is_admin);
      if (item.role === "intent") return Boolean(session.can_view_intent);
      return true;
    },
    [session],
  );

  const shellClasses = [
    "app-shell",
    sidebarCollapsed ? "sidebar-collapsed" : "",
    mobileDrawerOpen ? "mobile-sidebar-open" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={shellClasses} id="appShell" data-active-page={activePage}>
      <aside className="app-sidebar" id="appSidebar">
        <div className="sidebar-brand">
          <button
            className="brand-mark"
            id="sidebarBrandToggle"
            type="button"
            aria-controls="appSidebar"
            aria-expanded={!sidebarCollapsed || mobileDrawerOpen}
            title={bilingual(lang, "切换导航栏", "Toggle navigation")}
            aria-label={bilingual(lang, "切换导航栏", "Toggle navigation")}
            onClick={toggleSidebar}
          >
            <svg className="brand-triage-icon" viewBox="0 0 24 24" focusable="false" aria-hidden="true">
              <circle className="icon-emphasis" cx="4.5" cy="5" r="1.5" />
              <circle className="icon-emphasis" cx="4.5" cy="12" r="1.5" />
              <circle className="icon-emphasis" cx="4.5" cy="19" r="1.5" />
              <path d="M6 5h3l3 7M6 12h6M6 19h3l3-7" />
              <path className="icon-emphasis" d="m13 13 2.5 2.5L21 9" />
            </svg>
            <svg className="sidebar-menu-icon" viewBox="0 0 24 24" focusable="false" aria-hidden="true">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
            <svg className="sidebar-close-icon" viewBox="0 0 24 24" focusable="false" aria-hidden="true">
              <path d="m6 6 12 12M6 18 18 6" />
            </svg>
          </button>
          <a
            className="sidebar-copy sidebar-home"
            href={withWorkbenchBase("/review")}
            onClick={(e) => {
              e.preventDefault();
              navigate("review");
            }}
            title={bilingual(lang, "返回判错复核", "Back to Failure review")}
          >
            <strong>Manual Triage</strong>
            <span>{bilingual(lang, "RA 复核工作台", "RA Review Workbench")}</span>
          </a>
        </div>

        <nav className="sidebar-nav" aria-label={bilingual(lang, "工作台导航", "Workbench navigation")}>
          {session.identity_pending && (
            <div id="sidebarSessionPending" className="sidebar-session-pending" role="status">
              {bilingual(lang, "正在确认菜单权限…", "Checking menu access…")}
            </div>
          )}

          {NAV_GROUPS.map((group) => {
            if (group.intentOnly && !session.can_view_intent) return null;
            const visibleItems = group.items.filter(canSeeItem);
            if (!visibleItems.length) return null;
            const expanded = Boolean(openGroups[group.key]);
            return (
              <section
                key={group.key}
                className={`sidebar-nav-group${expanded ? "" : " is-collapsed"}`}
                data-sidebar-nav-group={group.key}
              >
                <button
                  className="sidebar-group-toggle"
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => toggleGroup(group.key)}
                >
                  <span className="sidebar-group-icon" aria-hidden="true">
                    {group.icon}
                  </span>
                  <span className="sidebar-group-label sidebar-label">
                    {bilingual(lang, group.zh, group.en)}
                  </span>
                  <span className="sidebar-group-compact" aria-hidden="true">
                    {bilingual(lang, group.compactZh, group.compactEn)}
                  </span>
                  <span className="sidebar-group-chevron" aria-hidden="true" />
                </button>
                <div className="sidebar-nav-group-items" hidden={!expanded}>
                  {visibleItems.map((item) => {
                    const isActive = activePage === item.page;
                    const label = bilingual(lang, item.zh, item.en);
                    const href = withWorkbenchBase(WORKBENCH_ROUTES[item.page].path);
                    return (
                      <a
                        key={item.id}
                        id={item.id}
                        className={`sidebar-item${isActive ? " active" : ""}`}
                        data-page-target={item.page}
                        href={href}
                        title={label}
                        aria-current={isActive ? "page" : undefined}
                        onClick={(e) => {
                          if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
                          e.preventDefault();
                          navigate(item.page);
                        }}
                      >
                        <span className="sidebar-icon" aria-hidden="true">
                          {item.icon}
                        </span>
                        <span className="sidebar-label">
                          <strong>{label}</strong>
                        </span>
                      </a>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </nav>

        <div className="sidebar-bottom">
          <div
            className="sidebar-user"
            id="sidebarUser"
            title={
              session.verified
                ? bilingual(lang, `可信 SSO：${session.username}`, `Verified SSO: ${session.username}`)
                : session.username || bilingual(lang, "当前会话", "Current session")
            }
          >
            <span className="user-avatar" id="userAvatar" aria-hidden="true">
              {session.username ? session.username.slice(0, 1).toUpperCase() : "?"}
            </span>
            <span className="sidebar-label">
              <strong id="sessionUserName">
                {session.username ||
                  (session.identity_pending
                    ? bilingual(lang, "身份识别中…", "Identifying…")
                    : bilingual(lang, "未识别用户", "Unidentified"))}
              </strong>
              <small id="sessionUserSource">
                {session.read_only
                  ? bilingual(lang, "只读模式", "Read-only")
                  : session.verified
                    ? bilingual(lang, "企业 SSO 已验证", "Enterprise SSO")
                    : session.identity_pending
                      ? bilingual(lang, "页面可先使用", "Ready to browse")
                      : bilingual(lang, "当前会话", "Session")}
              </small>
              {session.logout_url && !session.identity_pending && (
                <a className="sidebar-session-action" id="sessionLogoutLink" href={session.logout_url}>
                  {session.verified
                    ? bilingual(lang, "退出", "Sign out")
                    : bilingual(lang, "登录", "Sign in")}
                </a>
              )}
            </span>
          </div>
          <button
            className="sidebar-collapse"
            id="sidebarToggle"
            type="button"
            aria-controls="appSidebar"
            aria-expanded={!sidebarCollapsed}
            aria-keyshortcuts="Backslash"
            title={bilingual(lang, "折叠工具栏（\\）", "Collapse sidebar (\\)")}
            onClick={toggleSidebar}
          >
            <span aria-hidden="true">{sidebarCollapsed ? "›" : "‹"}</span>
            <span className="sidebar-label">
              {bilingual(lang, "折叠工具栏", "Collapse")}
            </span>
            <kbd className="sidebar-shortcut" aria-hidden="true">
              \
            </kbd>
          </button>
        </div>

        <div
          className="layout-resizer sidebar-resizer"
          id="sidebarResizer"
          role="separator"
          aria-label={bilingual(lang, "调节左侧工具栏宽度", "Resize sidebar")}
          aria-orientation="vertical"
          tabIndex={0}
          onPointerDown={startSidebarResize}
        />
      </aside>

      {mobileDrawerOpen && (
        <button
          className="mobile-sidebar-backdrop"
          id="mobileSidebarBackdrop"
          type="button"
          aria-label={bilingual(lang, "关闭工具栏", "Close sidebar")}
          onClick={() => setMobileDrawerOpen(false)}
        />
      )}

      <div className="app-frame">
        <header className="topbar">
          <div className="brand">
            <button
              type="button"
              className="button button-quiet ra-mobile-menu-btn"
              aria-label={bilingual(lang, "打开菜单", "Open menu")}
              aria-expanded={mobileDrawerOpen}
              onClick={() => setMobileDrawerOpen((v) => !v)}
            >
              ☰
            </button>
            <div>
              <h1 id="pageTitle">{pageTitle(activePage, lang)}</h1>
            </div>
          </div>

          {routeDef.usesIntentDatasets ? (
            <div className="topbar-baselines intent-topbar-dataset">
              <span className="topbar-baselines-label">
                {bilingual(lang, "数据集", "Datasets")}
              </span>
              <MultiSelect
                id="intentTopbarDatasetPicker"
                className="baseline-filter"
                options={intentDatasetOptions}
                values={selectedIntentDatasets}
                lang={lang}
                showOnlyThis
                placeholder={bilingual(lang, "选择数据集", "Select datasets")}
                ariaLabel={bilingual(lang, "选择意图数据集", "Select intent datasets")}
                onChange={(vals) => {
                  if (vals.length) setSelectedIntentDatasets(vals);
                }}
              />
            </div>
          ) : !routeDef.hideDatasetPicker ? (
            <div className="topbar-baselines" aria-label={bilingual(lang, "数据集", "Datasets")}>
              <span className="topbar-baselines-label">
                {bilingual(lang, "数据集", "Datasets")}
              </span>
              <MultiSelect
                id="baselineFilter"
                className="baseline-filter"
                options={baselineOptions}
                values={selectedBaselines}
                lang={lang}
                showOnlyThis
                placeholder={bilingual(lang, "选择数据集", "Select datasets")}
                ariaLabel={bilingual(lang, "选择 GT 数据集", "Select GT datasets")}
                onChange={(vals) => {
                  if (vals.length) setSelectedBaselines(vals);
                }}
              />
            </div>
          ) : null}

          {!routeDef.hideOverviewMetrics && (
            <div className="header-metrics" aria-label={bilingual(lang, "概览", "Overview")}>
              <div>
                <span>{bilingual(lang, "基线", "Baseline")}</span>
                <strong id="statIssues">{overview?.issue_count?.toLocaleString() ?? "—"}</strong>
              </div>
              <div className="metric-fail">
                <span>{bilingual(lang, "判断失败", "Mismatches")}</span>
                <strong id="statFailures">{overview?.failure_count?.toLocaleString() ?? "—"}</strong>
              </div>
              <div className="metric-reviewed">
                <span>{bilingual(lang, "人工复核", "Human reviews")}</span>
                <strong id="statReviewed">{overview?.reviewed_count?.toLocaleString() ?? "—"}</strong>
              </div>
              <div className="metric-shared-labels">
                <span>{bilingual(lang, "共享标签结论", "Labels resolved")}</span>
                <strong id="statSharedLabels">
                  {overview?.shared_label_resolved_count?.toLocaleString() ?? "—"}
                </strong>
              </div>
              <div>
                <span>{bilingual(lang, "模型输出", "Predictions")}</span>
                <strong id="statPredictions">{overview?.prediction_count?.toLocaleString() ?? "—"}</strong>
              </div>
            </div>
          )}

          {!routeDef.hideDatasetPicker && !routeDef.usesIntentDatasets && (
            <div
              className="gt-sync-control"
              id="gtSyncControl"
              data-status={gtSyncState}
              onMouseEnter={() => setGtTooltipOpen(true)}
              onMouseLeave={() => setGtTooltipOpen(false)}
            >
              <span
                className={`gt-sync-meta${gtSyncState === "ready" ? " is-ready" : ""}${gtSyncState === "failed" ? " is-failed" : ""}`}
                id="gtSyncMeta"
                tabIndex={0}
                onFocus={() => setGtTooltipOpen(true)}
                onBlur={() => setGtTooltipOpen(false)}
              >
                <span>{bilingual(lang, "GT 更新", "GT updated")}</span>
                <strong id="gtSyncSourceTime">{gtSyncLatestTime}</strong>
              </span>
              <button
                className={`button button-quiet gt-sync-button${gtSyncState === "running" ? " is-running" : ""}`}
                id="gtSyncButton"
                type="button"
                disabled={gtSyncState === "running" || gtSyncRaw.enabled === false || Boolean(session.read_only)}
                aria-label={bilingual(lang, "从 Trail 同步所选数据集 GT", "Sync selected dataset GT from Trail")}
                onClick={() => gtSyncMutation.mutate()}
              >
                {gtSyncState === "running"
                  ? bilingual(lang, "同步中…", "Syncing…")
                  : bilingual(lang, "同步", "Sync")}
              </button>
              {gtTooltipOpen && (
                <div className="gt-sync-tooltip is-visible" id="gtSyncTooltip" role="tooltip">
                  <div className="gt-sync-tooltip-heading">
                    <strong>{bilingual(lang, "最近 GT 校验", "Latest GT check")}</strong>
                    <span>Trail view {gtSyncRaw.source_view_id || 1000}</span>
                  </div>
                  {gtSyncItems.length === 0 ? (
                    <div className="gt-sync-tooltip-empty">
                      {bilingual(lang, "尚无同步记录", "No sync record yet")}
                    </div>
                  ) : (
                    gtSyncItems.map((item, idx) => (
                      <div key={item.baseline_id || idx} className="gt-sync-tooltip-dataset">
                        <div className="gt-sync-tooltip-dataset-heading">
                          <strong>{item.baseline_label || item.baseline_id}</strong>
                          <span>{item.status || "—"}</span>
                        </div>
                        <div className="gt-sync-tooltip-row">
                          <span>{bilingual(lang, "本次校验", "Checked")}</span>
                          <strong>{formatCstTime(item.last_checked_at, lang)}</strong>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          )}

          <div className="top-actions">
            <button
              className="button button-quiet shortcut-help-button ra-desktop-action"
              id="shortcutHelpButton"
              type="button"
              title={bilingual(lang, "快捷键指南（H）", "Keyboard shortcuts (H)")}
              onClick={() => setShortcutGuideOpen(true)}
            >
              <span>{bilingual(lang, "快捷键", "Shortcuts")}</span>
              <kbd aria-hidden="true">H</kbd>
            </button>
            <button
              className="button button-quiet theme-toggle"
              id="themeToggleButton"
              type="button"
              aria-label={
                theme === "light"
                  ? bilingual(lang, "切换到深色模式", "Switch to dark theme")
                  : bilingual(lang, "切换到浅色模式", "Switch to light theme")
              }
              title={
                theme === "light"
                  ? bilingual(lang, "切换到深色模式", "Switch to dark theme")
                  : bilingual(lang, "切换到浅色模式", "Switch to light theme")
              }
              onClick={toggleTheme}
            >
              {theme === "light" ? "☾" : "☀"}
            </button>
            <button
              className="button button-quiet language-toggle"
              id="languageToggleButton"
              type="button"
              aria-label={bilingual(lang, "切换到 English", "Switch to 中文")}
              title={bilingual(lang, "切换到 English", "Switch to 中文")}
              onClick={toggleLang}
            >
              {lang === "en" ? "中文" : "EN"}
            </button>
            <button
              className="button button-quiet ra-desktop-action"
              id="refreshButton"
              type="button"
              aria-keyshortcuts="R"
              title={bilingual(lang, "刷新当前页（R）", "Refresh current page (R)")}
              onClick={refreshActivePage}
            >
              <span>{bilingual(lang, "刷新", "Refresh")}</span>
              <kbd aria-hidden="true">R</kbd>
            </button>
            <div className="ra-mobile-more-wrap">
              <button
                type="button"
                className="button button-quiet ra-mobile-more-trigger"
                aria-expanded={mobileMoreOpen}
                onClick={() => setMobileMoreOpen((v) => !v)}
              >
                {bilingual(lang, "更多", "More")}
              </button>
              {mobileMoreOpen && (
                <div className="ra-mobile-more-panel">
                  <button
                    type="button"
                    className="button button-quiet"
                    onClick={() => {
                      setMobileMoreOpen(false);
                      refreshActivePage();
                    }}
                  >
                    {bilingual(lang, "刷新页面", "Refresh page")}
                  </button>
                  <button
                    type="button"
                    className="button button-quiet"
                    onClick={() => {
                      setMobileMoreOpen(false);
                      setShortcutGuideOpen(true);
                    }}
                  >
                    {bilingual(lang, "快捷键指南", "Keyboard shortcuts")}
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="main">{children}</main>
      </div>

      {/* Global Toast Stack */}
      {toasts.length > 0 && (
        <div className="ra-toast-stack" role="status" aria-live="polite">
          {toasts.map((item) => (
            <div
              key={item.id}
              className={`ra-toast${item.isError ? " is-error" : ""}`}
              onClick={() => dismissToast(item.id)}
            >
              <span>{item.message}</span>
            </div>
          ))}
        </div>
      )}

      {/* Keyboard Shortcuts Modal */}
      <ModalDialog
        open={shortcutGuideOpen}
        title={bilingual(lang, "工作台快捷键指南", "Workbench Keyboard Shortcuts")}
        lang={lang}
        onClose={() => setShortcutGuideOpen(false)}
      >
        <div className="ra-shortcut-guide-grid">
          <div className="ra-shortcut-row"><kbd>\</kbd><span>{bilingual(lang, "折叠 / 展开左侧栏", "Toggle sidebar")}</span></div>
          <div className="ra-shortcut-row"><kbd>H</kbd><span>{bilingual(lang, "打开 / 关闭快捷键指南", "Toggle shortcut guide")}</span></div>
          <div className="ra-shortcut-row"><kbd>R</kbd><span>{bilingual(lang, "刷新当前页数据", "Refresh active page")}</span></div>
          <div className="ra-shortcut-row"><kbd>←</kbd> / <kbd>→</kbd><span>{bilingual(lang, "上一帧 / 下一帧（详情 / 意图）", "Prev / Next frame")}</span></div>
          <div className="ra-shortcut-row"><kbd>Space</kbd><span>{bilingual(lang, "播放 / 暂停视频或放大媒体", "Play/Pause or fullscreen media")}</span></div>
          <div className="ra-shortcut-row"><kbd>F</kbd><span>{bilingual(lang, "全屏查看 BEV / Camera", "Fullscreen media lightbox")}</span></div>
          <div className="ra-shortcut-row"><kbd>G</kbd><span>{bilingual(lang, "切换规划约束文本叠加", "Toggle Planning Constraints")}</span></div>
          <div className="ra-shortcut-row"><kbd>T</kbd><span>{bilingual(lang, "查看 RA Events 详情", "Open RA Events modal")}</span></div>
          <div className="ra-shortcut-row"><kbd>Q W A S Z X</kbd><span>{bilingual(lang, "复核 / 标注 6 组标签快捷选择", "Select 6 review tag groups")}</span></div>
          <div className="ra-shortcut-row"><kbd>1–8</kbd> / <kbd>Shift+1–8</kbd><span>{bilingual(lang, "意图标注当前帧 / 全 Case 预填", "Intent frame / batch prefill")}</span></div>
        </div>
      </ModalDialog>

      {/* Global Task Allocation Editor Modal */}
      {allocationCampaignId && (
        <Suspense fallback={null}>
          <AllocationEditorModal
            campaignId={allocationCampaignId}
            lang={lang}
            onClose={closeAllocationEditor}
            onSaved={() => {
              void queryClient.invalidateQueries({ queryKey: ["review-assignments-list"] });
              void queryClient.invalidateQueries({ queryKey: ["campaigns-list"] });
            }}
          />
        </Suspense>
      )}
    </div>
  );
};
