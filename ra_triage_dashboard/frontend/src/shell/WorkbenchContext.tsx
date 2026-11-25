import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import {
  bilingual,
  ColorTheme,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import {
  buildWorkbenchPageUrl,
  pageTitle,
  resolvePageFromLocation,
  WORKBENCH_ROUTES,
  WorkbenchPageId,
} from "./routes";

export interface WorkbenchSession {
  authenticated: boolean;
  verified: boolean;
  username: string;
  source?: string;
  identity_pending?: boolean;
  access_role: string;
  is_admin: boolean;
  can_write: boolean;
  read_only?: boolean;
  can_view_intent?: boolean;
  can_annotate_intent?: boolean;
  can_manage_intent?: boolean;
  can_manage_team_default?: boolean;
  logout_url?: string;
  browser_lca_fallback?: boolean;
}

export interface BaselineEntry {
  id: string;
  label?: string;
  scope?: string;
  count?: number;
  default_selected?: boolean;
  hidden?: boolean;
  source_ids?: string[];
}

export interface IntentDatasetEntry {
  id: string;
  display_name: string;
  available: boolean;
  case_count?: number;
}

export interface WorkbenchConfig {
  baselines?: BaselineEntry[];
  default_baseline_ids?: string[];
  default_model_run_id?: string;
  build_commit?: string;
  gt_sync?: Record<string, unknown>;
  trail_sync?: Record<string, unknown>;
  trail_attribute_update?: Record<string, unknown>;
  review_tag_catalog?: Array<Record<string, unknown>>;
  missing_evidence_catalog?: Array<Record<string, unknown>>;
  review_attachment_limits?: Record<string, unknown>;
  case_labeling?: { active_baseline_ids?: string[] };
  batch_prediction?: Record<string, unknown>;
}

export interface WorkbenchOverview {
  issue_count?: number;
  failure_count?: number;
  reviewed_count?: number;
  shared_label_resolved_count?: number;
  prediction_count?: number;
}

export interface ToastEntry {
  id: number;
  message: string;
  isError: boolean;
}

export interface WorkbenchContextValue {
  activePage: WorkbenchPageId;
  locationSearch: string;
  lang: UiLanguage;
  theme: ColorTheme;
  setLang: (lang: UiLanguage) => void;
  toggleLang: () => void;
  setTheme: (theme: ColorTheme) => void;
  toggleTheme: () => void;
  navigate: (
    page: WorkbenchPageId,
    params?: Record<string, string | string[] | number | boolean | null | undefined>,
    opts?: { replace?: boolean },
  ) => void;
  navigateHref: (href: string, opts?: { replace?: boolean }) => void;
  session: WorkbenchSession;
  sessionLoading: boolean;
  config: WorkbenchConfig | null;
  baselines: BaselineEntry[];
  selectedBaselines: string[];
  setSelectedBaselines: (ids: string[]) => void;
  intentDatasets: IntentDatasetEntry[];
  selectedIntentDatasets: string[];
  setSelectedIntentDatasets: (ids: string[]) => void;
  overview: WorkbenchOverview | null;
  toasts: ToastEntry[];
  showToast: (message: string, isError?: boolean) => void;
  dismissToast: (id: number) => void;
  refreshActivePage: () => void;
  openAllocationEditor: (campaignId: string) => void;
  allocationCampaignId: string | null;
  closeAllocationEditor: () => void;
}

const DEFAULT_SESSION: WorkbenchSession = {
  authenticated: false,
  verified: false,
  username: "",
  source: "anonymous",
  identity_pending: true,
  access_role: "viewer",
  is_admin: false,
  can_write: false,
  read_only: false,
};

const WorkbenchContext = createContext<WorkbenchContextValue | null>(null);

function readInitialLang(): UiLanguage {
  if (typeof window === "undefined") return "zh";
  try {
    const stored = localStorage.getItem("ra-triage-ui-language");
    if (stored === "en" || stored === "zh") return stored;
  } catch {
    // ignore storage errors
  }
  return document.documentElement.dataset.uiLang === "en" ? "en" : "zh";
}

function readInitialTheme(): ColorTheme {
  if (typeof window === "undefined") return "dark";
  try {
    const stored = localStorage.getItem("ra-triage-color-theme");
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // ignore storage errors
  }
  return document.documentElement.dataset.colorTheme === "light" ? "light" : "dark";
}

function readUrlBaselines(): string[] {
  if (typeof window === "undefined") return [];
  const raw = new URLSearchParams(window.location.search).get("baselines") || "";
  return raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function readUrlIntentDatasets(): string[] {
  if (typeof window === "undefined") return [];
  const params = new URLSearchParams(window.location.search);
  return Array.from(new Set(params.getAll("dataset").map((s) => s.trim()).filter(Boolean)));
}

let toastSeq = 0;

export const WorkbenchProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const queryClient = useQueryClient();
  const [activePage, setActivePage] = useState<WorkbenchPageId>(() => resolvePageFromLocation());
  const [locationSearch, setLocationSearch] = useState<string>(() =>
    typeof window !== "undefined" ? window.location.search : "",
  );
  const [lang, setLangState] = useState<UiLanguage>(() => readInitialLang());
  const [theme, setThemeState] = useState<ColorTheme>(() => readInitialTheme());
  const [selectedBaselines, setSelectedBaselinesState] = useState<string[]>(() => readUrlBaselines());
  const [selectedIntentDatasets, setSelectedIntentDatasetsState] = useState<string[]>(() =>
    readUrlIntentDatasets(),
  );
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const [allocationCampaignId, setAllocationCampaignId] = useState<string | null>(null);

  const showToast = useCallback((message: string, isError = false) => {
    const text = String(message || "").trim();
    if (!text) return;
    const id = ++toastSeq;
    setToasts((prev) => [...prev.slice(-3), { id, message: text, isError }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, isError ? 5200 : 3400);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const setLang = useCallback((next: UiLanguage) => {
    setLangState(next);
    document.documentElement.dataset.uiLang = next;
    document.documentElement.lang = next === "en" ? "en" : "zh-CN";
    try {
      localStorage.setItem("ra-triage-ui-language", next);
    } catch {
      // ignore
    }
    window.dispatchEvent(new Event("ra:workbench-sync"));
  }, []);

  const toggleLang = useCallback(() => {
    setLang(lang === "en" ? "zh" : "en");
  }, [lang, setLang]);

  const setTheme = useCallback((next: ColorTheme) => {
    setThemeState(next);
    document.documentElement.dataset.colorTheme = next;
    try {
      localStorage.setItem("ra-triage-color-theme", next);
    } catch {
      // ignore
    }
    window.dispatchEvent(new Event("ra:workbench-sync"));
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "light" ? "dark" : "light");
  }, [theme, setTheme]);

  // Apply initial DOM attributes + document title
  useEffect(() => {
    document.documentElement.dataset.uiLang = lang;
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    document.documentElement.dataset.colorTheme = theme;
    document.title = `${pageTitle(activePage, lang)} · Manual Triage`;
  }, [activePage, lang, theme]);

  // Session query
  const sessionQuery = useQuery<WorkbenchSession>({
    queryKey: ["session"],
    queryFn: ({ signal }) => apiRequest<WorkbenchSession>("/api/session", { signal }),
    staleTime: 30_000,
  });

  const session = useMemo<WorkbenchSession>(() => {
    if (!sessionQuery.data) {
      return { ...DEFAULT_SESSION, identity_pending: sessionQuery.isLoading };
    }
    const raw = sessionQuery.data;
    const role = String(raw.access_role || "viewer");
    return {
      ...DEFAULT_SESSION,
      ...raw,
      identity_pending: false,
      can_write:
        typeof raw.can_write === "boolean"
          ? raw.can_write
          : Boolean(raw.verified && (raw.is_admin || ["writer", "admin"].includes(role))),
    };
  }, [sessionQuery.data, sessionQuery.isLoading]);

  // Persist intent nav hint + DOM access mode
  useEffect(() => {
    if (session.identity_pending) return;
    document.documentElement.dataset.sessionPending = "false";
    document.documentElement.dataset.accessMode = session.read_only ? "read-only" : "write";
    if (typeof session.can_view_intent === "boolean") {
      try {
        localStorage.setItem("ra-triage-can-view-intent", session.can_view_intent ? "true" : "false");
      } catch {
        // ignore
      }
      if (session.can_view_intent) document.documentElement.dataset.canViewIntent = "true";
      else delete document.documentElement.dataset.canViewIntent;
    }
  }, [session]);

  // Config query
  const configQuery = useQuery<WorkbenchConfig>({
    queryKey: ["dashboard-config"],
    queryFn: ({ signal }) => apiRequest<WorkbenchConfig>("/api/dashboard-config", { signal }),
    staleTime: 60_000,
  });

  const config = configQuery.data || null;
  const baselines = useMemo(() => config?.baselines || [], [config]);

  // Initialize default baselines once config loads if URL didn't specify them
  useEffect(() => {
    if (!config || selectedBaselines.length > 0) return;
    const defaults =
      config.default_baseline_ids && config.default_baseline_ids.length
        ? config.default_baseline_ids
        : baselines.filter((b) => b.default_selected).map((b) => b.id);
    const fallback = defaults.length ? defaults : baselines[0] ? [baselines[0].id] : [];
    if (fallback.length) {
      setSelectedBaselinesState(fallback);
    }
  }, [config, baselines, selectedBaselines.length]);

  const setSelectedBaselines = useCallback((ids: string[]) => {
    const cleaned = Array.from(new Set(ids.map((s) => s.trim()).filter(Boolean)));
    if (!cleaned.length) return;
    setSelectedBaselinesState(cleaned);
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("baselines", cleaned.join(","));
      window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}`);
      setLocationSearch(url.search);
    } catch {
      // ignore
    }
    window.dispatchEvent(new Event("ra:workbench-sync"));
  }, []);

  // Intent datasets query (enabled when on an intent page or user has intent access)
  const routeDef = WORKBENCH_ROUTES[activePage] || WORKBENCH_ROUTES.review;
  const intentDatasetsQuery = useQuery<{ items?: IntentDatasetEntry[] }>({
    queryKey: ["intent-datasets"],
    queryFn: ({ signal }) => apiRequest<{ items?: IntentDatasetEntry[] }>("/api/intent-datasets", { signal }),
    enabled: Boolean(routeDef.usesIntentDatasets || session.can_view_intent),
    staleTime: 60_000,
  });

  const intentDatasets = useMemo(
    () => (intentDatasetsQuery.data?.items || []).filter((d) => d.available),
    [intentDatasetsQuery.data],
  );

  useEffect(() => {
    if (!intentDatasets.length || selectedIntentDatasets.length > 0) return;
    setSelectedIntentDatasetsState([intentDatasets[0].id]);
  }, [intentDatasets, selectedIntentDatasets.length]);

  const setSelectedIntentDatasets = useCallback((ids: string[]) => {
    const cleaned = Array.from(new Set(ids.map((s) => s.trim()).filter(Boolean)));
    if (!cleaned.length) return;
    setSelectedIntentDatasetsState(cleaned);
    try {
      const url = new URL(window.location.href);
      url.searchParams.delete("dataset");
      cleaned.forEach((id) => url.searchParams.append("dataset", id));
      window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}`);
      setLocationSearch(url.search);
    } catch {
      // ignore
    }
    window.dispatchEvent(new Event("ra:workbench-sync"));
  }, []);

  // Overview KPIs for topbar
  const baselinesCsv = selectedBaselines.join(",");
  const overviewQuery = useQuery<WorkbenchOverview>({
    queryKey: ["workbench-overview", baselinesCsv],
    queryFn: ({ signal }) => {
      const qs = baselinesCsv ? `?baselines=${encodeURIComponent(baselinesCsv)}` : "";
      return apiRequest<WorkbenchOverview>(`/api/overview${qs}`, { signal });
    },
    enabled: !routeDef.hideOverviewMetrics && Boolean(baselinesCsv),
    staleTime: 30_000,
  });

  // Navigation helpers
  const navigateHref = useCallback((href: string, opts: { replace?: boolean } = {}) => {
    try {
      const resolved = href.startsWith("http")
        ? new URL(href)
        : new URL(withWorkbenchBase(href), window.location.origin);
      if (resolved.origin !== window.location.origin) {
        window.location.assign(resolved.href);
        return;
      }
      const nextUrl = `${resolved.pathname}${resolved.search}${resolved.hash}`;
      const nextPage = resolvePageFromLocation(resolved.pathname, resolved.search);
      if (opts.replace) {
        window.history.replaceState({ page: nextPage }, "", nextUrl);
      } else {
        window.history.pushState({ page: nextPage }, "", nextUrl);
      }
      setActivePage(nextPage);
      setLocationSearch(resolved.search);
      const urlBaselines = new URLSearchParams(resolved.search).get("baselines");
      if (urlBaselines) {
        const parsed = urlBaselines.split(",").map((s) => s.trim()).filter(Boolean);
        if (parsed.length) setSelectedBaselinesState(parsed);
      }
      const urlIntent = new URLSearchParams(resolved.search).getAll("dataset").filter(Boolean);
      if (urlIntent.length) {
        setSelectedIntentDatasetsState(Array.from(new Set(urlIntent)));
      }
      window.dispatchEvent(new Event("ra:workbench-sync"));
    } catch {
      window.location.assign(href);
    }
  }, []);

  const navigate = useCallback(
    (
      page: WorkbenchPageId,
      params?: Record<string, string | string[] | number | boolean | null | undefined>,
      opts: { replace?: boolean } = {},
    ) => {
      const mergedParams: Record<string, string | string[] | number | boolean | null | undefined> = {
        ...(params || {}),
      };
      const def = WORKBENCH_ROUTES[page];
      if (!def?.hideDatasetPicker && !def?.usesIntentDatasets && !mergedParams.baselines && selectedBaselines.length) {
        mergedParams.baselines = selectedBaselines;
      }
      const url = buildWorkbenchPageUrl(page, mergedParams);
      navigateHref(url, opts);
    },
    [navigateHref, selectedBaselines],
  );

  // Sync on browser Back/Forward
  useEffect(() => {
    const onPopState = () => {
      setActivePage(resolvePageFromLocation());
      setLocationSearch(window.location.search);
      const urlBaselines = readUrlBaselines();
      if (urlBaselines.length) setSelectedBaselinesState(urlBaselines);
      const urlIntent = readUrlIntentDatasets();
      if (urlIntent.length) setSelectedIntentDatasetsState(urlIntent);
      window.dispatchEvent(new Event("ra:workbench-sync"));
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  // Refresh current page queries
  const refreshActivePage = useCallback(() => {
    void queryClient.invalidateQueries();
    showToast(bilingual(lang, "已刷新当前页面数据。", "Page data refreshed."));
  }, [queryClient, showToast, lang]);

  // Keep global compatibility shims synced for Wave 3.1–3.5 islands
  useEffect(() => {
    const win = window as unknown as Record<string, unknown>;
    win.__RA_TRIAGE_SESSION__ = session;
    win.__RA_TRIAGE_STATE__ = {
      selectedBaselineIds: selectedBaselines,
      session,
      config,
      activePage,
      uiLanguage: lang,
      colorTheme: theme,
    };
    win.showToast = showToast;
    win.showPage = (page: string, opts?: Record<string, unknown>) => {
      const pageId = (page in WORKBENCH_ROUTES ? page : "review") as WorkbenchPageId;
      const params: Record<string, string | string[] | number | boolean | null | undefined> = {};
      if (opts) {
        for (const [k, v] of Object.entries(opts)) {
          if (k === "historyMode" || k === "loadPageData") continue;
          if (v != null) params[k] = v as string;
        }
      }
      navigate(pageId, params, { replace: opts?.historyMode === "replace" });
    };
    win.navigatePage = (page: string, opts?: Record<string, unknown>) => {
      (win.showPage as (p: string, o?: Record<string, unknown>) => void)(page, opts);
    };
    win.__RA_REACT_WORKBENCH__ = {
      version: "vite-react-ts-3.6",
      ownsPage: () => true,
      refreshPage: () => refreshActivePage(),
      notifySync: () => window.dispatchEvent(new Event("ra:workbench-sync")),
      openTaskAllocationEditor: (campaignId: string) => {
        setAllocationCampaignId(campaignId);
        return true;
      },
    };
  }, [session, selectedBaselines, config, activePage, lang, theme, showToast, navigate, refreshActivePage]);

  const value = useMemo<WorkbenchContextValue>(
    () => ({
      activePage,
      locationSearch,
      lang,
      theme,
      setLang,
      toggleLang,
      setTheme,
      toggleTheme,
      navigate,
      navigateHref,
      session,
      sessionLoading: sessionQuery.isLoading,
      config,
      baselines,
      selectedBaselines,
      setSelectedBaselines,
      intentDatasets,
      selectedIntentDatasets,
      setSelectedIntentDatasets,
      overview: overviewQuery.data || null,
      toasts,
      showToast,
      dismissToast,
      refreshActivePage,
      openAllocationEditor: (campaignId: string) => setAllocationCampaignId(campaignId),
      allocationCampaignId,
      closeAllocationEditor: () => setAllocationCampaignId(null),
    }),
    [
      activePage,
      locationSearch,
      lang,
      theme,
      setLang,
      toggleLang,
      setTheme,
      toggleTheme,
      navigate,
      navigateHref,
      session,
      sessionQuery.isLoading,
      config,
      baselines,
      selectedBaselines,
      setSelectedBaselines,
      intentDatasets,
      selectedIntentDatasets,
      setSelectedIntentDatasets,
      overviewQuery.data,
      toasts,
      showToast,
      dismissToast,
      refreshActivePage,
      allocationCampaignId,
    ],
  );

  return <WorkbenchContext.Provider value={value}>{children}</WorkbenchContext.Provider>;
};

export function useWorkbench(): WorkbenchContextValue {
  const ctx = useContext(WorkbenchContext);
  if (!ctx) {
    throw new Error("useWorkbench must be used inside WorkbenchProvider");
  }
  return ctx;
}

export function useOptionalWorkbench(): WorkbenchContextValue | null {
  return useContext(WorkbenchContext);
}
