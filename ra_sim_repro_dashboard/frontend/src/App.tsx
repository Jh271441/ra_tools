import { FilterPanel } from "./components/ui/filter-panel";
import { releaseName } from "./lib/releaseName";
import {
  changeEvaluationReleaseQuery,
  collectionIssuesQuery,
} from "./lib/evaluationContext";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Activity,
  BarChart3,
  CalendarDays,
  Database,
  Filter,
  FlaskConical,
  GitCompareArrows,
  HeartPulse,
  LayoutDashboard,
  ListChecks,
  PanelLeftClose,
  RotateCcw,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { api } from "./api/client";
import { evaluationRequest } from "./api/evaluation";
import {
  CurrentBusinessRelease,
  ReleaseWorkflow,
} from "./components/ReleaseWorkflow";
const ReleaseIssues = lazy(() =>
  import("./components/ReleaseIssues").then((module) => ({
    default: module.ReleaseIssues,
  })),
);
const IssueDetail = lazy(() =>
  import("./components/IssueDetail").then((module) => ({
    default: module.IssueDetail,
  })),
);
const IssuesTable = lazy(() =>
  import("./components/IssuesTable").then((module) => ({
    default: module.IssuesTable,
  })),
);
const Overview = lazy(() =>
  import("./components/Overview").then((module) => ({
    default: module.Overview,
  })),
);
const SystemStatus = lazy(() =>
  import("./components/SystemStatus").then((module) => ({
    default: module.SystemStatus,
  })),
);
const EvaluationWorkspace = lazy(() =>
  import("./components/EvaluationWorkspace").then((module) => ({
    default: module.EvaluationWorkspace,
  })),
);
import { Select } from "./components/ui/select";
import { PAGE_SIZES } from "./components/ui/pagination";
import { TopControls } from "./components/TopControls";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { cn } from "./lib/utils";
import type {
  IssueListItem,
  KpiSummary,
  RefreshJob,
  SelectedIssueResult,
  SummaryResponse,
  VersionItem,
  VersionsResponse,
} from "./types";

function readDashboardCache<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(`ra-dashboard-${key}`);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

type Page = "overview" | "issues" | "simulation" | "auto-triage" | "status";

// Lightweight history routing: module switches map to /sim/overview,
// /sim/issues, /sim/status so browser/mouse back-forward navigates between
// modules instead of leaving the app. BASE_URL is '/sim/' in this build.
const BASE_PATH = import.meta.env.BASE_URL.replace(/\/$/, "");
const PAGES: Page[] = [
  "overview",
  "issues",
  "simulation",
  "auto-triage",
  "status",
];

function pageFromLocation(): Page {
  const path = window.location.pathname;
  if (path === `${BASE_PATH}/auto-triage`) return "simulation";
  for (const candidate of PAGES) {
    if (
      path === `${BASE_PATH}/${candidate}` ||
      path.startsWith(`${BASE_PATH}/${candidate}/`)
    ) {
      return candidate;
    }
  }
  return "overview";
}

const defaultFilters = {
  version: "",
  rootCause: "",
  triggerType: "",
  precisionLabel: "",
  query: "",
};

const defaultSourceFilters = {
  platformGen: "",
  versionCategory: "",
  bigVersion: "",
  testVersion: "",
};

function stringValue(value: unknown) {
  return value == null ? "" : String(value);
}

function addOption(target: Set<string>, value: unknown) {
  const text = stringValue(value).trim();
  if (text) target.add(text);
}

function matchesMeta(value: unknown, expected: string) {
  if (!expected) return true;
  return stringValue(value) === expected;
}

function dateInputValue(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function twoMonthRange() {
  const end = new Date();
  const start = new Date(end);
  start.setMonth(start.getMonth() - 2);
  return { start: dateInputValue(start), end: dateInputValue(end) };
}

const SOURCE_PARAMS = {
  platformGen: "platform_gen",
  versionCategory: "version_category",
  bigVersion: "big_version",
  testVersion: "test_version",
};
function readSourceFilters() {
  const q = new URLSearchParams(location.search);
  return Object.fromEntries(
    Object.entries(SOURCE_PARAMS).map(([key, param]) => [
      key,
      q.get(param) || "",
    ]),
  ) as typeof defaultSourceFilters;
}
function readReleaseRange() {
  const q = new URLSearchParams(location.search),
    fallback = twoMonthRange();
  return {
    start: q.has("release_start") ? q.get("release_start")! : fallback.start,
    end: q.has("release_end") ? q.get("release_end")! : fallback.end,
  };
}

function versionDate(value: string) {
  const compact = value.match(/(\d{8})/);
  if (compact) {
    const digits = compact[1];
    return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`;
  }
  const separated = value.match(/(?:^|[-_])(\d{4})[-_](\d{2})[-_](\d{2})/);
  return separated ? `${separated[1]}-${separated[2]}-${separated[3]}` : null;
}

function SelectFilter({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <label className="grid min-w-0 gap-1.5 text-xs font-medium text-muted-foreground xl:flex-1 xl:basis-[90px] [&_.ui-select-trigger]:w-full">
      <span>{label}</span>
      <Select
        label={label}
        value={value}
        options={[
          { value: "", label: t("all") },
          ...options.map((option) => ({ value: option, label: option })),
        ]}
        onChange={onChange}
      />
    </label>
  );
}

export default function App() {
  const { t } = useTranslation();
  const [page, setPageState] = useState<Page>(pageFromLocation);
  const [basis, setBasis] = useState(() =>
    location.pathname.endsWith("/auto-triage") ||
    new URLSearchParams(location.search).get("basis") === "auto-triage"
      ? "auto-triage"
      : "normal",
  );

  const setPage = useCallback(
    (next: Page, version?: string, navigationQuery?: URLSearchParams) => {
      setPageState(next);
      const currentQuery = new URLSearchParams(window.location.search);
      const q = navigationQuery
        ? new URLSearchParams(navigationQuery)
        : next === "issues" && version
          ? changeEvaluationReleaseQuery(currentQuery, version)
          : currentQuery;
      const search = q.size ? `?${q}` : "";
      const target = `${BASE_PATH}/${next}${search}`;
      if (window.location.pathname + window.location.search !== target) {
        window.history.pushState({ page: next }, "", target);
      }
      window.scrollTo(0, 0);
    },
    [],
  );

  useEffect(() => {
    // Normalize bare /sim/ to a canonical module URL without adding a history entry.
    const q = new URLSearchParams(location.search);
    if (location.pathname.endsWith("/auto-triage")) {
      q.set("basis", "auto-triage");
      q.set("sidecar", "1");
    }
    window.history.replaceState(
      { page: pageFromLocation() },
      "",
      `${BASE_PATH}/${pageFromLocation()}${q.size ? `?${q}` : ""}`,
    );
    const onPopState = () => {
      setPageState(pageFromLocation());
      setBasis(
        new URLSearchParams(location.search).get("basis") === "auto-triage"
          ? "auto-triage"
          : "normal",
      );
      const q = new URLSearchParams(window.location.search);
      setFilters({
        ...defaultFilters,
        version: q.get("version") || q.get("release") || "",
      });
      setSourceFilters(readSourceFilters());
      setReleaseRange(readReleaseRange());
      setIssuePage(Math.max(1, Number(q.get("page")) || 1));
      const size = Number(q.get("page_size") || 20);
      setIssuePageSize(PAGE_SIZES.includes(size) ? size : 20);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
  const [dark, setDark] = useState(
    () => localStorage.getItem("theme") === "dark",
  );
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem("sidebarCollapsed") === "1",
  );
  const [versions, setVersions] = useState<VersionItem[]>(() =>
    readDashboardCache("versions", []),
  );
  const [evaluationVersions, setEvaluationVersions] = useState<VersionItem[]>(
    [],
  );
  const [catalogueError, setCatalogueError] = useState(false);
  const [catalogueAttempt, setCatalogueAttempt] = useState(0);
  const [summary, setSummary] = useState<SummaryResponse | null>(() =>
    readDashboardCache<SummaryResponse | null>("summary", null),
  );
  const [comparison, setComparison] = useState<KpiSummary[]>(() =>
    readDashboardCache("comparison", []),
  );
  const [issues, setIssues] = useState<IssueListItem[]>([]);
  const [issuesLoading, setIssuesLoading] = useState(false);
  const [showLegacyIssues, setShowLegacyIssues] = useState(false);
  const [issueTotal, setIssueTotal] = useState(0);
  const [issuePage, setIssuePage] = useState(() =>
    Math.max(1, Number(new URLSearchParams(location.search).get("page")) || 1),
  );
  const [issuePageSize, setIssuePageSize] = useState(() => {
    const size = Number(
      new URLSearchParams(location.search).get("page_size") || 20,
    );
    return PAGE_SIZES.includes(size) ? size : 20;
  });
  const issueGeneration = useRef(0);
  const [filters, setFilters] = useState(() => {
    const q = new URLSearchParams(window.location.search);
    return {
      ...defaultFilters,
      version: q.get("version") || q.get("release") || "",
    };
  });
  const [sourceFilters, setSourceFilters] = useState(readSourceFilters);
  const [releaseRange, setReleaseRange] = useState(readReleaseRange);
  const [selectedResult, setSelectedResult] =
    useState<SelectedIssueResult | null>(null);
  const [refreshJob, setRefreshJob] = useState<RefreshJob | null>(null);
  const [error, setError] = useState<string>("");
  const evaluationPage =
    basis === "auto-triage" && (page === "overview" || page === "issues");
  const activeVersions = evaluationPage ? evaluationVersions : versions;

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("theme", dark ? "dark" : "light");
  }, [dark]);

  useEffect(() => {
    localStorage.setItem("sidebarCollapsed", sidebarCollapsed ? "1" : "0");
  }, [sidebarCollapsed]);

  const refreshing =
    refreshJob?.status === "queued" || refreshJob?.status === "running";

  const loadDashboard = useCallback(async () => {
    setError("");
    const [versionsResult, summaryResult, comparisonResult] =
      await Promise.allSettled([
        api.versions().then((value) => {
          setVersions(value.versions);
          localStorage.setItem(
            "ra-dashboard-versions",
            JSON.stringify(value.versions),
          );
        }),
        api.summary().then((value) => {
          setSummary(value);
          localStorage.setItem("ra-dashboard-summary", JSON.stringify(value));
        }),
        api.comparison().then((value) => {
          setComparison(value);
          localStorage.setItem(
            "ra-dashboard-comparison",
            JSON.stringify(value),
          );
        }),
      ]);
    const failed = [versionsResult, summaryResult, comparisonResult].find(
      (result) => result.status === "rejected",
    );
    if (failed?.status === "rejected" && !summary && !comparison.length) {
      setError(
        failed.reason instanceof Error
          ? failed.reason.message
          : String(failed.reason),
      );
    }
  }, []);

  const loadIssues = useCallback(async () => {
    const generation = ++issueGeneration.current;
    setIssuesLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(issuePage),
        page_size: String(issuePageSize),
      });
      if (filters.version) params.set("version", filters.version);
      if (filters.rootCause) params.set("root_cause", filters.rootCause);
      if (filters.triggerType) params.set("trigger_type", filters.triggerType);
      if (filters.precisionLabel)
        params.set("precision_label", filters.precisionLabel);
      const query = filters.query.trim();
      if (query) {
        if (query.toLowerCase().startsWith("cn")) params.set("issue_id", query);
        else params.set("scenario_id", query);
      }
      const result = await api.issues(params);
      if (generation !== issueGeneration.current) return;
      setIssues(result.items);
      setIssueTotal(result.total);
    } catch (err) {
      if (generation === issueGeneration.current)
        setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (generation === issueGeneration.current) setIssuesLoading(false);
    }
  }, [filters, issuePage, issuePageSize]);

  const changeIssueFilters = (value: typeof filters) => {
    setIssuePage(1);
    setSelectedResult(null);
    setFilters(value);
  };
  useEffect(() => {
    if (page !== "issues" || !showLegacyIssues || basis !== "normal") return;
    const q = new URLSearchParams(location.search);
    q.set("page", String(issuePage));
    q.set("page_size", String(issuePageSize));
    history.replaceState(history.state, "", `${location.pathname}?${q}`);
  }, [page, showLegacyIssues, basis, issuePage, issuePageSize]);

  useEffect(() => {
    if (evaluationPage) {
      let active = true;
      setCatalogueError(false);
      void evaluationRequest<VersionsResponse>("/versions")
        .then((value) => {
          if (active) setEvaluationVersions(value.versions);
        })
        .catch(() => {
          if (active) setCatalogueError(true);
        });
      return () => {
        active = false;
      };
    }
    if (page === "issues" || page === "simulation") {
      // The source Issue page uses its own inventory; only legacy options need
      // this small request. Summary and charts belong to the overview.
      let active = true;
      void api
        .versions()
        .then((value) => {
          if (active) setVersions(value.versions);
        })
        .catch(() => {});
      return () => {
        active = false;
      };
    }
    if (page !== "overview" || basis !== "normal") return;
    void loadDashboard();
    const timer = window.setInterval(() => {
      if (!document.hidden) void loadDashboard();
    }, 30000);
    return () => window.clearInterval(timer);
  }, [loadDashboard, page, basis, evaluationPage, catalogueAttempt]);

  useEffect(() => {
    if (page !== "issues" || !showLegacyIssues || basis !== "normal") return;
    void loadIssues();
  }, [loadIssues, page, showLegacyIssues, basis]);

  useEffect(() => {
    if (!issues.length) {
      setSelectedResult(null);
      return;
    }
    const currentStillVisible = selectedResult
      ? issues.some(
          (item) =>
            item.scenario_id === selectedResult.scenario_id &&
            item.version_key === selectedResult.version_key,
        )
      : false;
    if (!currentStillVisible) {
      const first = issues[0];
      setSelectedResult({
        issue_id: first.issue_id,
        scenario_id: first.scenario_id,
        version_key: first.version_key,
      });
    }
  }, [issues, selectedResult]);

  useEffect(() => {
    if (
      !refreshJob ||
      refreshJob.status === "completed" ||
      refreshJob.status === "failed"
    )
      return;
    const timer = window.setInterval(() => {
      void api.refreshStatus(refreshJob.job_id).then((job) => {
        setRefreshJob(job);
        if (job.status === "completed") {
          void loadDashboard();
          if (page === "issues" && showLegacyIssues) void loadIssues();
        }
      });
    }, 1200);
    return () => window.clearInterval(timer);
  }, [refreshJob, loadDashboard, loadIssues, page, showLegacyIssues]);

  useEffect(() => {
    if (page !== "overview") return;
    const q = new URLSearchParams(location.search);
    for (const [key, param] of Object.entries(SOURCE_PARAMS)) {
      const value = sourceFilters[key as keyof typeof sourceFilters];
      if (value) q.set(param, value);
      else q.delete(param);
    }
    q.set("release_start", releaseRange.start);
    q.set("release_end", releaseRange.end);
    history.replaceState(history.state, "", `${location.pathname}?${q}`);
  }, [page, sourceFilters, releaseRange]);

  const validReleaseRange =
    !releaseRange.start ||
    !releaseRange.end ||
    releaseRange.start <= releaseRange.end;
  const releaseRangeActive = Boolean(releaseRange.start || releaseRange.end);
  const current = useMemo(
    () => activeVersions.find((item) => item.is_current),
    [activeVersions],
  );
  const sourceOptions = useMemo(() => {
    const values = {
      platformGen: new Set<string>(),
      versionCategory: new Set<string>(),
      bigVersion: new Set<string>(),
      testVersion: new Set<string>(),
    };
    for (const version of activeVersions) {
      const meta = version.metadata_json || {};
      addOption(values.platformGen, meta.platform_gen);
      addOption(values.versionCategory, meta.version_category);
      addOption(values.bigVersion, meta.big_version);
      addOption(values.testVersion, meta.test_version);
    }
    return {
      platformGen: [...values.platformGen],
      versionCategory: [...values.versionCategory],
      bigVersion: [...values.bigVersion],
      testVersion: [...values.testVersion],
    };
  }, [activeVersions]);
  const matchedVersionKeys = useMemo(() => {
    const matched = activeVersions
      .filter((version) => {
        const meta = version.metadata_json || {};
        return (
          matchesMeta(meta.platform_gen, sourceFilters.platformGen) &&
          matchesMeta(meta.version_category, sourceFilters.versionCategory) &&
          matchesMeta(meta.big_version, sourceFilters.bigVersion) &&
          matchesMeta(meta.test_version, sourceFilters.testVersion)
        );
      })
      .map((version) => version.version_key);
    return new Set(matched);
  }, [sourceFilters, activeVersions]);

  const visibleReleases = useMemo(
    () =>
      activeVersions
        .filter((item) => {
          if (!validReleaseRange || !matchedVersionKeys.has(item.version_key))
            return false;
          const date = versionDate(item.version_key);
          return (
            !date ||
            ((!releaseRange.start || date >= releaseRange.start) &&
              (!releaseRange.end || date <= releaseRange.end))
          );
        })
        .map((item) => item.version_key),
    [activeVersions, matchedVersionKeys, releaseRange, validReleaseRange],
  );
  const visibleComparison = useMemo(
    () =>
      comparison.filter((item) => visibleReleases.includes(item.version_key)),
    [comparison, visibleReleases],
  );

  async function handleRefresh() {
    setError("");
    const job = await api.refresh();
    setRefreshJob(job);
  }

  function openIssues(nextFilters: Partial<typeof defaultFilters>) {
    setFilters({ ...defaultFilters, ...nextFilters });
    setShowLegacyIssues(true);
    setPage("issues", nextFilters.version);
  }

  function openCurrentIssues() {
    const q = new URLSearchParams(location.search);
    setFilters({
      ...defaultFilters,
      version: q.get("version") || q.get("release") || "",
    });
    setShowLegacyIssues(false);
    setPage("issues");
  }

  function openCollectionIssues(version: string) {
    const query = collectionIssuesQuery(
      new URLSearchParams(location.search),
      version,
    );
    setFilters({ ...defaultFilters, version });
    setIssuePage(1);
    setSelectedResult(null);
    setIssues([]);
    setIssueTotal(0);
    setShowLegacyIssues(false);
    setBasis("normal");
    setPage("issues", version, query);
  }

  function applySourceFilters() {
    const keys = [...matchedVersionKeys];
    setFilters((value) => ({
      ...value,
      version: keys.length === 1 ? keys[0] : "",
    }));
  }

  function resetSourceFilters() {
    setSourceFilters(defaultSourceFilters);
    setReleaseRange(twoMonthRange());
    setFilters((value) => ({ ...value, version: "" }));
  }

  const basisControl = (
    <label className="grid min-w-0 gap-1.5 text-xs font-medium text-muted-foreground xl:basis-[150px] [&_.ui-select-trigger]:w-full">
      <span>{t("evaluation.basis")}</span>
      <Select
        label={t("evaluation.basis")}
        value={basis}
        options={[
          { value: "normal", label: t("evaluation.normal") },
          { value: "auto-triage", label: t("evaluation.show_auto") },
        ]}
        onChange={(value) => {
          const q = new URLSearchParams(location.search),
            release = q.get("version") || q.get("release") || filters.version;
          if (value === "normal") q.delete("basis");
          else q.set("basis", value);
          q.set("page", "1");
          q.delete("coverage");
          q.delete("changed");
          if (release) {
            q.set("version", release);
            q.set("release", release);
          }
          setFilters({ ...defaultFilters, version: release || "" });
          setIssuePage(1);
          setSelectedResult(null);
          history.pushState(history.state, "", `${location.pathname}?${q}`);
          setBasis(value);
        }}
      />
    </label>
  );

  return (
    <div className="min-h-screen text-foreground">
      <div className="min-h-screen lg:flex">
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-30 hidden overflow-hidden border-r border-border/70 bg-card/86 backdrop-blur-xl transition-[width] duration-180 ease-out dark:bg-background/88 lg:flex lg:flex-col",
            sidebarCollapsed ? "w-[72px]" : "w-72",
          )}
        >
          <div
            className={cn(
              "flex h-16 items-center border-b border-border/70",
              sidebarCollapsed ? "justify-center px-3" : "gap-3 px-5",
            )}
          >
            <button
              type="button"
              className="group flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-sm shadow-primary/20 transition-[box-shadow,opacity,transform] duration-150 hover:opacity-95 hover:shadow-md hover:shadow-primary/25 active:scale-95 focus:outline-none focus:ring-2 focus:ring-ring"
              onClick={() => setSidebarCollapsed((value) => !value)}
              title={
                sidebarCollapsed ? t("expandSidebar") : t("collapseSidebar")
              }
              aria-label={
                sidebarCollapsed ? t("expandSidebar") : t("collapseSidebar")
              }
            >
              <Activity className="h-4 w-4" />
            </button>
            {!sidebarCollapsed ? (
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-semibold">
                  {t("brandTitle")}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  {t("brandSubtitle")}
                </div>
              </div>
            ) : null}
            {!sidebarCollapsed ? (
              <Button
                variant="ghost"
                size="icon"
                className="ml-auto h-8 w-8"
                onClick={() => setSidebarCollapsed(true)}
                title={t("collapseSidebar")}
                aria-label={t("collapseSidebar")}
              >
                <PanelLeftClose className="h-4 w-4" />
              </Button>
            ) : null}
          </div>

          <nav className="grid gap-1 p-3">
            <Button
              variant={page === "overview" ? "secondary" : "ghost"}
              className={cn(
                sidebarCollapsed ? "sidebar-icon-button" : "justify-start",
              )}
              onClick={() => setPage("overview")}
              title={t("overview")}
              aria-label={t("overview")}
            >
              <LayoutDashboard className="h-4 w-4" />
              {!sidebarCollapsed ? t("overview") : null}
            </Button>
            <Button
              variant={page === "issues" ? "secondary" : "ghost"}
              className={cn(
                sidebarCollapsed ? "sidebar-icon-button" : "justify-start",
              )}
              onClick={openCurrentIssues}
              title={t("issues")}
              aria-label={t("issues")}
            >
              <ListChecks className="h-4 w-4" />
              {!sidebarCollapsed ? t("issues") : null}
            </Button>
            <Button
              variant={page === "simulation" ? "secondary" : "ghost"}
              className={cn(
                sidebarCollapsed ? "sidebar-icon-button" : "justify-start",
              )}
              onClick={() => setPage("simulation")}
              title={t("simulation")}
              aria-label={t("simulation")}
            >
              <FlaskConical className="h-4 w-4" />
              {!sidebarCollapsed ? t("simulation") : null}
            </Button>
            <Button
              variant={page === "status" ? "secondary" : "ghost"}
              className={cn(
                sidebarCollapsed ? "sidebar-icon-button" : "justify-start",
              )}
              onClick={() => setPage("status")}
              title={t("systemStatus")}
              aria-label={t("systemStatus")}
            >
              <HeartPulse className="h-4 w-4" />
              {!sidebarCollapsed ? t("systemStatus") : null}
            </Button>
          </nav>

          <div
            className={cn(
              "mt-auto grid gap-3 border-t border-border/70",
              sidebarCollapsed ? "p-3" : "p-4",
            )}
          >
            <TopControls
              showRefresh={showLegacyIssues && basis === "normal"}
              dark={dark}
              onToggleDark={() => setDark((value) => !value)}
              onRefresh={handleRefresh}
              refreshing={refreshing}
              compact={sidebarCollapsed}
            />
            {!sidebarCollapsed && refreshJob ? (
              <Badge
                variant={
                  refreshing
                    ? "warning"
                    : refreshJob.status === "completed"
                      ? "success"
                      : "destructive"
                }
                className="justify-center"
              >
                {refreshJob.status} {refreshJob.progress}%
              </Badge>
            ) : null}
            {basis === "normal" && (
              <div
                className={cn(
                  sidebarCollapsed
                    ? "sidebar-icon-button flex cursor-pointer items-center justify-center"
                    : "metric-surface rounded-lg border p-3",
                )}
                role={sidebarCollapsed ? "button" : undefined}
                tabIndex={sidebarCollapsed ? 0 : undefined}
                title={current?.version_key || t("currentVersion")}
                onClick={
                  sidebarCollapsed
                    ? () => openIssues({ version: current?.version_key || "" })
                    : undefined
                }
                onKeyDown={
                  sidebarCollapsed
                    ? (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          openIssues({ version: current?.version_key || "" });
                        }
                      }
                    : undefined
                }
              >
                {sidebarCollapsed ? (
                  <GitCompareArrows className="h-4 w-4 text-primary" />
                ) : (
                  <>
                    <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                      <GitCompareArrows className="h-3.5 w-3.5" />
                      {t("simFlow.businessVersion")}
                    </div>
                    <div className="truncate text-[13px] font-semibold">
                      {releaseName(current?.version_key)}
                    </div>
                    <div className="mt-1 font-mono text-[11px] text-muted-foreground">
                      {current?.sim_job_id
                        ? `job ${current.sim_job_id}`
                        : "job -"}
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </aside>

        <div
          className={cn(
            "flex min-h-screen min-w-0 flex-1 flex-col transition-[padding-left] duration-180 ease-out",
            sidebarCollapsed ? "lg:pl-[72px]" : "lg:pl-72",
          )}
        >
          <header className="sticky top-0 z-20 border-b border-border/70 bg-background/85 backdrop-blur-xl supports-[backdrop-filter]:bg-background/70 lg:hidden">
            <div className="flex flex-col gap-2.5 px-4 py-2.5">
              <div className="flex min-w-0 items-center justify-between gap-2">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <h1 className="truncate text-base font-semibold tracking-normal">
                    {page === "overview"
                      ? t("appTitle")
                      : page === "issues"
                        ? t("issues")
                        : page === "simulation"
                          ? t("simulation")
                          : page === "auto-triage"
                            ? t("autoTriage.nav")
                            : t("systemStatus")}
                  </h1>
                  <Badge variant="secondary" className="shrink-0">
                    <Database className="h-3 w-3" />
                    {basis === "auto-triage" && page !== "simulation"
                      ? t("autoTriage.autoBasis")
                      : releaseName(current?.version_key)}
                  </Badge>
                  {refreshJob ? (
                    <Badge
                      variant={
                        refreshing
                          ? "warning"
                          : refreshJob.status === "completed"
                            ? "success"
                            : "destructive"
                      }
                    >
                      {refreshJob.status} {refreshJob.progress}%
                    </Badge>
                  ) : null}
                </div>
                <TopControls
                  showRefresh={false}
                  dark={dark}
                  onToggleDark={() => setDark((value) => !value)}
                  onRefresh={handleRefresh}
                  refreshing={refreshing}
                  className="shrink-0 flex-nowrap gap-1.5 [&>button]:flex-none [&>button]:px-2.5"
                />
              </div>
              <nav className="grid grid-cols-2 gap-1 rounded-lg bg-muted/80 p-1 [&>button]:min-h-10 [&>button]:min-w-0 [&>button]:whitespace-normal [&>button]:px-2 [&>button]:text-xs [&>button]:leading-tight [@media(pointer:coarse)]:[&>button]:min-h-11 sm:grid-cols-4 sm:[&>button]:min-h-9 sm:[&>button]:px-3">
                <Button
                  variant={page === "overview" ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setPage("overview")}
                >
                  <BarChart3 className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{t("overview")}</span>
                </Button>
                <Button
                  variant={page === "issues" ? "default" : "ghost"}
                  size="sm"
                  onClick={openCurrentIssues}
                >
                  <ListChecks className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{t("issues")}</span>
                </Button>
                <Button
                  variant={page === "simulation" ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setPage("simulation")}
                >
                  <FlaskConical className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{t("simulation")}</span>
                </Button>
                <Button
                  variant={page === "status" ? "default" : "ghost"}
                  size="sm"
                  onClick={() => setPage("status")}
                >
                  <HeartPulse className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{t("systemStatus")}</span>
                </Button>
              </nav>
            </div>
          </header>

          <main className="grid min-w-0 gap-5 p-4 md:p-6">
            {page === "overview" ? (
              <FilterPanel>
                <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <Badge variant="secondary">
                      <Database className="h-3.5 w-3.5" />
                      {t("simFlow.businessVersion")}:{" "}
                      {releaseName(current?.version_key)}
                    </Badge>
                    {current?.sim_job_id ? (
                      <Badge variant="outline">
                        {t("job")} {current.sim_job_id}
                      </Badge>
                    ) : null}
                    <Badge variant="outline">
                      {activeVersions.length} {t("versions")}
                    </Badge>
                  </div>
                  <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                    {basis === "normal" &&
                      (summary
                        ? `${t("generated")} ${new Date(summary.generated_at).toLocaleString()}`
                        : t("noSnapshot"))}
                  </div>
                </div>

                <div className="grid min-w-0 items-end gap-3 border-t border-border/60 pt-3 sm:grid-cols-2 xl:flex xl:flex-wrap">
                  <div className="grid min-w-0 gap-1.5 text-xs font-medium text-muted-foreground sm:col-span-2 xl:basis-[300px] xl:grow">
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center gap-1">
                        <CalendarDays className="h-3.5 w-3.5" />
                        {t("releaseDateRange")}
                      </span>
                      <div className="ml-auto flex items-center gap-1.5">
                        <button
                          type="button"
                          className="whitespace-nowrap text-[11px] font-semibold text-primary hover:underline focus:outline-none focus:ring-1 focus:ring-ring"
                          onClick={() => setReleaseRange(twoMonthRange())}
                        >
                          {t("lastTwoMonths")}
                        </button>
                        <span className="text-[11px] text-muted-foreground">
                          ·
                        </span>
                        <button
                          type="button"
                          className={cn(
                            "whitespace-nowrap text-[11px] font-semibold hover:underline focus:outline-none focus:ring-1 focus:ring-ring",
                            !releaseRange.start && !releaseRange.end
                              ? "text-foreground"
                              : "text-primary",
                          )}
                          onClick={() =>
                            setReleaseRange({ start: "", end: "" })
                          }
                        >
                          {t("all")}
                        </button>
                      </div>
                    </div>
                    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                      <input
                        id="global-release-date-start"
                        type="date"
                        aria-label={t("evaluation.filter_start")}
                        className="min-h-11 w-0 min-w-0 flex-1 rounded-md border border-input bg-card/80 px-2 text-xs font-normal text-foreground shadow-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring dark:bg-background/40"
                        value={releaseRange.start}
                        onChange={(event) =>
                          setReleaseRange((current) => ({
                            ...current,
                            start: event.target.value,
                          }))
                        }
                      />
                      <span className="text-xs text-muted-foreground">—</span>
                      <input
                        id="global-release-date-end"
                        type="date"
                        aria-label={t("evaluation.filter_end")}
                        className="min-h-11 w-0 min-w-0 flex-1 rounded-md border border-input bg-card/80 px-2 text-xs font-normal text-foreground shadow-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring dark:bg-background/40"
                        value={releaseRange.end}
                        onChange={(event) =>
                          setReleaseRange((current) => ({
                            ...current,
                            end: event.target.value,
                          }))
                        }
                      />
                    </div>
                  </div>
                  <SelectFilter
                    label={t("platformGen")}
                    value={sourceFilters.platformGen}
                    options={sourceOptions.platformGen}
                    onChange={(value) =>
                      setSourceFilters((current) => ({
                        ...current,
                        platformGen: value,
                      }))
                    }
                  />
                  <SelectFilter
                    label={t("versionCategory")}
                    value={sourceFilters.versionCategory}
                    options={sourceOptions.versionCategory}
                    onChange={(value) =>
                      setSourceFilters((current) => ({
                        ...current,
                        versionCategory: value,
                      }))
                    }
                  />
                  <SelectFilter
                    label={t("bigVersion")}
                    value={sourceFilters.bigVersion}
                    options={sourceOptions.bigVersion}
                    onChange={(value) =>
                      setSourceFilters((current) => ({
                        ...current,
                        bigVersion: value,
                      }))
                    }
                  />
                  <SelectFilter
                    label={t("testVersion")}
                    value={sourceFilters.testVersion}
                    options={sourceOptions.testVersion}
                    onChange={(value) =>
                      setSourceFilters((current) => ({
                        ...current,
                        testVersion: value,
                      }))
                    }
                  />
                  {basisControl}
                  {basis === "auto-triage" && (
                    <div id="evaluation-actions" className="flex items-end" />
                  )}
                  <div className="flex flex-wrap items-end gap-2 sm:col-span-2 xl:ml-auto">
                    <Button
                      variant="outline"
                      size="sm"
                      className="min-h-11"
                      onClick={resetSourceFilters}
                    >
                      <RotateCcw className="h-4 w-4" />
                      {t("reset")}
                    </Button>
                    <Button
                      size="sm"
                      className="min-h-11"
                      onClick={applySourceFilters}
                    >
                      <Search className="h-4 w-4" />
                      {t("searchAction")}
                    </Button>
                  </div>
                </div>
              </FilterPanel>
            ) : null}

            {error && page !== "status" && basis === "normal" ? (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            ) : null}
            {evaluationPage && catalogueError && (
              <div
                role="alert"
                className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
              >
                <span>{t("autoTriage.loadError")}</span>
                <Button
                  className="min-h-11"
                  variant="outline"
                  onClick={() => setCatalogueAttempt((value) => value + 1)}
                >
                  {t("autoTriage.retry")}
                </Button>
              </div>
            )}

            {basis === "normal" && page === "overview" && (
              <CurrentBusinessRelease />
            )}
            <Suspense
              fallback={
                <p role="status" className="text-sm text-muted-foreground">
                  {t("loading")}
                </p>
              }
            >
              {page === "status" ? (
                <SystemStatus />
              ) : page === "simulation" ? (
                <ReleaseWorkflow
                  onOpenIssues={(version) =>
                    version ? openIssues({ version }) : openCurrentIssues()
                  }
                />
              ) : page === "overview" && basis === "auto-triage" ? (
                <EvaluationWorkspace
                  page="overview"
                  visibleReleases={visibleReleases}
                  onNavigate={(next, version) => {
                    if (next === "issues" && version)
                      setFilters({ ...defaultFilters, version });
                    setPage(next, version);
                  }}
                />
              ) : page === "overview" ? (
                <Suspense
                  fallback={
                    <p className="text-sm text-muted-foreground">
                      {t("loading")}
                    </p>
                  }
                >
                  <Overview
                    summary={summary}
                    comparison={visibleComparison}
                    onOpenIssues={openIssues}
                    onOpenCurrent={openCurrentIssues}
                    onOpenCollection={openCollectionIssues}
                  />
                </Suspense>
              ) : (
                <ReleaseIssues
                  basisControl={basisControl}
                  evaluation={
                    basis === "auto-triage" ? (
                      <EvaluationWorkspace
                        key={filters.version || "@stable"}
                        page="issues"
                        release={filters.version || "@stable"}
                        hideRelease
                        onNavigate={setPage}
                      />
                    ) : undefined
                  }
                  versions={activeVersions}
                  version={filters.version || "@stable"}
                  onVersionChange={(version) => {
                    const value = version;
                    setFilters({ ...defaultFilters, version: value });
                    setPage("issues", value);
                  }}
                  onHistoryChange={setShowLegacyIssues}
                  history={
                    <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(380px,0.75fr)]">
                      <IssuesTable
                        items={issues}
                        versions={versions}
                        total={issueTotal}
                        loading={issuesLoading}
                        showVersionFilter={false}
                        page={issuePage}
                        pageSize={issuePageSize}
                        onPageSizeChange={(size) => {
                          setIssuePageSize(size);
                          setIssuePage(1);
                          setSelectedResult(null);
                        }}
                        onPageChange={(page) => {
                          setIssuePage(page);
                          setSelectedResult(null);
                        }}
                        filters={filters}
                        onFiltersChange={changeIssueFilters}
                        selectedResult={selectedResult}
                        onSelectResult={setSelectedResult}
                      />
                      <IssueDetail selected={selectedResult} />
                    </div>
                  }
                />
              )}
            </Suspense>
          </main>
        </div>
      </div>
    </div>
  );
}
