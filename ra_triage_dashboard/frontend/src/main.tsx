import React, { Suspense } from "react";
import { createRoot, Root } from "react-dom/client";
import { QueryClient, QueryClientProvider, isCancelledError, useQuery } from "@tanstack/react-query";
import { apiRequest } from "./api/client";
import { useWorkbenchBridge, WorkbenchBridgeState } from "./bridge/useWorkbenchBridge";
import { SystemStatusPage } from "./pages/SystemStatusPage";
import { UsersPage } from "./pages/UsersPage";
import "./styles/react-workbench.css";

const DailyCronPage = React.lazy(() =>
  import("./pages/DailyCronPage").then((m) => ({ default: m.DailyCronPage })),
);
const RunsManagerIsland = React.lazy(() =>
  import("./pages/RunsManagerIsland").then((m) => ({ default: m.RunsManagerIsland })),
);
const VersionMetricsPage = React.lazy(() =>
  import("./pages/VersionMetricsPage").then((m) => ({ default: m.VersionMetricsPage })),
);
const VersionDatasetsPage = React.lazy(() =>
  import("./pages/VersionDatasetsPage").then((m) => ({ default: m.VersionDatasetsPage })),
);
const LabelingSummaryPage = React.lazy(() =>
  import("./pages/LabelingSummaryPage").then((m) => ({ default: m.LabelingSummaryPage })),
);
const ReviewAnalysisPage = React.lazy(() =>
  import("./pages/ReviewAnalysisPage").then((m) => ({ default: m.ReviewAnalysisPage })),
);
const RunComparisonPage = React.lazy(() =>
  import("./pages/RunComparisonPage").then((m) => ({ default: m.RunComparisonPage })),
);
const TrailHistoryPage = React.lazy(() =>
  import("./pages/TrailHistoryPage").then((m) => ({ default: m.TrailHistoryPage })),
);
const RdResultsPage = React.lazy(() =>
  import("./pages/RdResultsPage").then((m) => ({ default: m.RdResultsPage })),
);
const BatchPredictionPage = React.lazy(() =>
  import("./pages/BatchPredictionPage").then((m) => ({ default: m.BatchPredictionPage })),
);
const IntentSummaryPage = React.lazy(() =>
  import("./pages/IntentSummaryPage").then((m) => ({ default: m.IntentSummaryPage })),
);
const IntentExperimentsPage = React.lazy(() =>
  import("./pages/IntentExperimentsPage").then((m) => ({ default: m.IntentExperimentsPage })),
);
const TrailUpdatePage = React.lazy(() =>
  import("./pages/TrailUpdatePage").then((m) => ({ default: m.TrailUpdatePage })),
);
const CampaignsPage = React.lazy(() =>
  import("./pages/CampaignsPage").then((m) => ({ default: m.CampaignsPage })),
);
const IntentLabelingPage = React.lazy(() =>
  import("./pages/IntentLabelingPage").then((m) => ({ default: m.IntentLabelingPage })),
);
const ReviewAssignmentsPage = React.lazy(() =>
  import("./pages/ReviewAssignmentsPage").then((m) => ({ default: m.ReviewAssignmentsPage })),
);
const LabelingNewTaskPage = React.lazy(() =>
  import("./pages/LabelingNewTaskPage").then((m) => ({ default: m.LabelingNewTaskPage })),
);
const ReviewGalleryIsland = React.lazy(() =>
  import("./pages/ReviewGalleryIsland").then((m) => ({ default: m.ReviewGalleryIsland })),
);
const CaseLabelingGalleryIsland = React.lazy(() =>
  import("./pages/CaseLabelingGalleryIsland").then((m) => ({
    default: m.CaseLabelingGalleryIsland,
  })),
);

const OWNED_PAGES = new Set<string>([
  "status",
  "users",
  "daily-cron",
  "runs-manager",
  "version-metrics",
  "version-datasets",
  "labeling-summary",
  "analysis",
  "comparison",
  "trail-history",
  "rd-results",
  "prediction",
  "intent-summary",
  "intent-experiments",
  "trail-update",
  "campaigns",
  "intent",
  "review-assignments",
  "labeling-new-task",
  "review",
  "labeling",
]);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function useResolvedSession(active: boolean) {
  const { session } = useWorkbenchBridge();
  const sessionQuery = useQuery<NonNullable<WorkbenchBridgeState["session"]>>({
    queryKey: ["session"],
    queryFn: ({ signal }) =>
      apiRequest<NonNullable<WorkbenchBridgeState["session"]>>("/api/session", { signal }),
    enabled: active && !session?.verified,
    staleTime: 30_000,
  });
  const effectiveSession = session?.verified ? session : sessionQuery.data || session;
  const sessionLoading = active && !effectiveSession?.verified && sessionQuery.isFetching;
  return { effectiveSession, sessionLoading };
}

const SystemStatusIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  return <SystemStatusPage active={activePage === "status"} lang={lang} />;
};

const UsersIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  const active = activePage === "users";
  const { effectiveSession, sessionLoading } = useResolvedSession(active);
  return (
    <UsersPage
      active={active}
      lang={lang}
      isAdmin={Boolean(effectiveSession?.is_admin)}
      sessionLoading={sessionLoading}
    />
  );
};

const DailyCronIsland: React.FC = () => {
  const { activePage, lang, theme } = useWorkbenchBridge();
  const active = activePage === "daily-cron";
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <DailyCronPage active={active} lang={lang} theme={theme} />
    </Suspense>
  );
};

const RunsManagerIslandHost: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  const active = activePage === "runs";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <RunsManagerIsland
        active={active}
        lang={lang}
        username={effectiveSession?.username || ""}
      />
    </Suspense>
  );
};

const VersionMetricsIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  const active = activePage === "version-metrics";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  const canWrite = Boolean(
    effectiveSession?.verified && (effectiveSession?.can_write || effectiveSession?.is_admin),
  );
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <VersionMetricsPage active={active} lang={lang} canWrite={canWrite} />
    </Suspense>
  );
};

const VersionDatasetsIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  const active = activePage === "version-datasets";
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <VersionDatasetsPage active={active} lang={lang} />
    </Suspense>
  );
};

const LabelingSummaryIsland: React.FC = () => {
  const { activePage, lang, theme, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "labeling-summary";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <LabelingSummaryPage
        active={active}
        lang={lang}
        theme={theme}
        selectedBaselines={selectedBaselines}
        isAdmin={Boolean(effectiveSession?.is_admin)}
      />
    </Suspense>
  );
};

const ReviewAnalysisIsland: React.FC = () => {
  const { activePage, lang, theme, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "analysis";
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <ReviewAnalysisPage
        active={active}
        lang={lang}
        theme={theme}
        selectedBaselines={selectedBaselines}
      />
    </Suspense>
  );
};

const RunComparisonIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "comparison";
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <RunComparisonPage active={active} lang={lang} selectedBaselines={selectedBaselines} />
    </Suspense>
  );
};

const TrailHistoryIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "trail-history";
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <TrailHistoryPage active={active} lang={lang} selectedBaselines={selectedBaselines} />
    </Suspense>
  );
};

const RdResultsIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "rd-results";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <RdResultsPage
        active={active}
        lang={lang}
        selectedBaselines={selectedBaselines}
        isAdmin={Boolean(effectiveSession?.is_admin)}
      />
    </Suspense>
  );
};

const BatchPredictionIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  const active = activePage === "prediction";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <BatchPredictionPage
        active={active}
        lang={lang}
        username={effectiveSession?.username || ""}
      />
    </Suspense>
  );
};

const IntentSummaryIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  const active = activePage === "intent-summary";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <IntentSummaryPage
        active={active}
        lang={lang}
        username={effectiveSession?.username || ""}
        isAdmin={Boolean(effectiveSession?.is_admin)}
      />
    </Suspense>
  );
};

const IntentExperimentsIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  const active = activePage === "intent-experiments";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <IntentExperimentsPage
        active={active}
        lang={lang}
        canManageIntent={Boolean(effectiveSession?.can_manage_intent)}
      />
    </Suspense>
  );
};

const TrailUpdateIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "trail-update";
  const { effectiveSession } = useResolvedSession(active);
  React.useEffect(() => {
    if (active) {
      document.getElementById("trailAttributeUpdatePage")?.classList.remove("is-loading");
    }
  }, [active]);
  if (!active) return null;
  const canWrite = Boolean(
    effectiveSession?.verified &&
      (effectiveSession?.can_write || effectiveSession?.is_admin) &&
      !effectiveSession?.read_only,
  );
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <TrailUpdatePage
        active={active}
        lang={lang}
        selectedBaselines={selectedBaselines}
        canWrite={canWrite}
      />
    </Suspense>
  );
};

const CampaignsIsland: React.FC = () => {
  const { activePage, lang, theme, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "campaigns";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <CampaignsPage
        active={active}
        lang={lang}
        theme={theme}
        selectedBaselines={selectedBaselines}
        isAdmin={Boolean(effectiveSession?.is_admin)}
      />
    </Suspense>
  );
};

const IntentLabelingIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  const active = activePage === "intent";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <IntentLabelingPage
        active={active}
        lang={lang}
        username={effectiveSession?.username || ""}
        isAdmin={Boolean(effectiveSession?.is_admin)}
        canAnnotateIntent={effectiveSession?.can_annotate_intent !== false}
      />
    </Suspense>
  );
};

const ReviewAssignmentsIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "review-assignments";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <ReviewAssignmentsPage
        active={active}
        lang={lang}
        selectedBaselines={selectedBaselines}
        isAdmin={Boolean(effectiveSession?.is_admin)}
        username={effectiveSession?.username || ""}
        verified={Boolean(effectiveSession?.verified)}
      />
    </Suspense>
  );
};

const LabelingNewTaskIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "labeling-new-task";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <LabelingNewTaskPage
        active={active}
        lang={lang}
        selectedBaselines={selectedBaselines}
        isAdmin={Boolean(effectiveSession?.is_admin)}
        username={effectiveSession?.username || ""}
        verified={Boolean(effectiveSession?.verified)}
      />
    </Suspense>
  );
};

const ReviewGalleryIslandHost: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "review";
  const { effectiveSession, sessionLoading } = useResolvedSession(active);
  if (!active) return null;
  const canWrite = Boolean(
    effectiveSession?.verified &&
      (effectiveSession?.can_write || effectiveSession?.is_admin) &&
      !effectiveSession?.read_only,
  );
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <ReviewGalleryIsland
        active={active}
        lang={lang}
        selectedBaselines={selectedBaselines}
        isAdmin={Boolean(effectiveSession?.is_admin)}
        canWrite={canWrite}
        identityPending={sessionLoading || Boolean(!effectiveSession?.verified)}
      />
    </Suspense>
  );
};

const CaseLabelingGalleryIslandHost: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "labeling";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  const canWrite = Boolean(
    effectiveSession?.verified &&
      (effectiveSession?.can_write || effectiveSession?.is_admin) &&
      !effectiveSession?.read_only,
  );
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <CaseLabelingGalleryIsland
        active={active}
        lang={lang}
        selectedBaselines={selectedBaselines}
        isAdmin={Boolean(effectiveSession?.is_admin)}
        canWrite={canWrite}
      />
    </Suspense>
  );
};

const mountedRoots = new Map<HTMLElement, Root>();

function mountIsland(container: HTMLElement | null, element: React.ReactElement) {
  if (!container) return;
  let root = mountedRoots.get(container);
  if (!root) {
    container.innerHTML = "";
    root = createRoot(container);
    mountedRoots.set(container, root);
  }
  root.render(<QueryClientProvider client={queryClient}>{element}</QueryClientProvider>);
}

function mountAllIslands() {
  mountIsland(document.getElementById("systemStatusPage"), <SystemStatusIsland />);
  mountIsland(document.getElementById("userManagementPage"), <UsersIsland />);
  mountIsland(document.getElementById("dailyCronPage"), <DailyCronIsland />);
  const runsCard = document.querySelector<HTMLElement>("#runsPage .runs-page-card");
  mountIsland(runsCard, <RunsManagerIslandHost />);
  mountIsland(document.getElementById("versionMetricsPage"), <VersionMetricsIsland />);
  mountIsland(document.getElementById("versionDatasetsPage"), <VersionDatasetsIsland />);
  mountIsland(document.getElementById("labelingSummaryPage"), <LabelingSummaryIsland />);
  mountIsland(document.getElementById("reviewAnalysisPage"), <ReviewAnalysisIsland />);
  mountIsland(document.getElementById("runComparisonPage"), <RunComparisonIsland />);
  mountIsland(document.getElementById("trailHistoryPage"), <TrailHistoryIsland />);
  mountIsland(document.getElementById("rdResultsPage"), <RdResultsIsland />);
  mountIsland(document.getElementById("predictionPage"), <BatchPredictionIsland />);
  mountIsland(document.getElementById("intentSummaryPage"), <IntentSummaryIsland />);
  mountIsland(document.getElementById("intentExperimentsPage"), <IntentExperimentsIsland />);
  const trailUpdateContainer = document.getElementById("trailAttributeUpdatePage");
  if (trailUpdateContainer) {
    trailUpdateContainer.classList.remove("is-loading");
    mountIsland(trailUpdateContainer, <TrailUpdateIsland />);
  }
  mountIsland(document.getElementById("campaignsPage"), <CampaignsIsland />);
  mountIsland(document.getElementById("intentLabelingPage"), <IntentLabelingIsland />);
  mountIsland(document.getElementById("reviewAssignmentsPage"), <ReviewAssignmentsIsland />);
  mountIsland(document.getElementById("caseLabelingNewTaskPage"), <LabelingNewTaskIsland />);
  mountIsland(document.getElementById("reviewGalleryView"), <ReviewGalleryIslandHost />);
  mountIsland(document.getElementById("caseLabelingGalleryView"), <CaseLabelingGalleryIslandHost />);
}

type CatalogPage = "review" | "review-assignments";

function readInitialRuns(page: CatalogPage, baselines: string, read: () => Promise<unknown>) {
  // Use the mounted page's own cache key, even if Classic wins the load race.
  const key = page === "review" ? "review-gallery-runs" : "review-assignments-runs";
  return queryClient.fetchQuery({
    queryKey: [key, baselines], queryFn: read, staleTime: 15_000, retry: false,
  }).catch((error: unknown) => {
    // A React observer may cancel its fetch during navigation. Classic owns
    // its own route checks and must still be able to finish its bootstrap.
    if (isCancelledError(error)) return read();
    throw error;
  });
}

interface ReactWorkbenchHandle {
  readInitialRuns: typeof readInitialRuns;
  version: string;
  ownedPages: string[];
  ownsPage: (page: string) => boolean;
  refreshPage: (page: string) => void;
  notifySync: () => void;
}

const handle: ReactWorkbenchHandle = {
  readInitialRuns,
  version: "vite-react-ts-strangler-4.2",
  ownedPages: Array.from(OWNED_PAGES),
  ownsPage: (page: string) => OWNED_PAGES.has(page),
  refreshPage: (page: string) => {
    if (page === "status") {
      void queryClient.invalidateQueries({ queryKey: ["system-status"] });
    } else if (page === "users") {
      void queryClient.invalidateQueries({ queryKey: ["access-users"] });
      void queryClient.invalidateQueries({ queryKey: ["mention-users"] });
    } else if (page === "daily-cron") {
      void queryClient.invalidateQueries({ queryKey: ["daily-cron"] });
    } else if (page === "runs-manager" || page === "runs") {
      void queryClient.invalidateQueries({ queryKey: ["model-runs"] });
    } else if (page === "version-metrics") {
      void queryClient.invalidateQueries({ queryKey: ["version-metrics"] });
    } else if (page === "version-datasets") {
      void queryClient.invalidateQueries({ queryKey: ["version-datasets"] });
    } else if (page === "labeling-summary") {
      void queryClient.invalidateQueries({ queryKey: ["labeling-summary"] });
      void queryClient.invalidateQueries({ queryKey: ["labeling-summary-tasks"] });
    } else if (page === "analysis") {
      void queryClient.invalidateQueries({ queryKey: ["review-reason-analysis"] });
      void queryClient.invalidateQueries({ queryKey: ["analysis-model-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["analysis-reviewers"] });
      void queryClient.invalidateQueries({ queryKey: ["analysis-work-splits"] });
    } else if (page === "comparison") {
      void queryClient.invalidateQueries({ queryKey: ["comparison-model-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["model-run-comparison"] });
      void queryClient.invalidateQueries({ queryKey: ["comparison-case-inputs"] });
    } else if (page === "trail-history") {
      void queryClient.invalidateQueries({ queryKey: ["trail-history-list"] });
      void queryClient.invalidateQueries({ queryKey: ["trail-history-detail"] });
    } else if (page === "rd-results") {
      void queryClient.invalidateQueries({ queryKey: ["human-publications"] });
      void queryClient.invalidateQueries({ queryKey: ["human-publications-history"] });
      void queryClient.invalidateQueries({ queryKey: ["rd-results-classic"] });
    } else if (page === "prediction") {
      void queryClient.invalidateQueries({ queryKey: ["batch-prediction-list"] });
      void queryClient.invalidateQueries({ queryKey: ["batch-prediction-config"] });
      void queryClient.invalidateQueries({ queryKey: ["batch-prediction-models"] });
      void queryClient.invalidateQueries({ queryKey: ["batch-prediction-prompts"] });
    } else if (page === "intent-summary") {
      void queryClient.invalidateQueries({ queryKey: ["intent-datasets"] });
      void queryClient.invalidateQueries({ queryKey: ["intent-summary"] });
    } else if (page === "intent-experiments") {
      void queryClient.invalidateQueries({ queryKey: ["intent-datasets"] });
      void queryClient.invalidateQueries({ queryKey: ["intent-experiments"] });
    } else if (page === "trail-update") {
      void queryClient.invalidateQueries({ queryKey: ["trail-update-preview"] });
      void queryClient.invalidateQueries({ queryKey: ["trail-issue-history"] });
    } else if (page === "campaigns") {
      void queryClient.invalidateQueries({ queryKey: ["campaigns-list"] });
      void queryClient.invalidateQueries({ queryKey: ["campaign-detail"] });
      void queryClient.invalidateQueries({ queryKey: ["campaign-group"] });
    } else if (page === "intent") {
      void queryClient.invalidateQueries({ queryKey: ["intent-datasets"] });
      void queryClient.invalidateQueries({ queryKey: ["intent-assignees"] });
    } else if (page === "review-assignments") {
      void queryClient.invalidateQueries({ queryKey: ["review-assignments-list"] });
      void queryClient.invalidateQueries({ queryKey: ["review-assignment-detail"] });
      void queryClient.invalidateQueries({ queryKey: ["review-assignments-runs"] });
    } else if (page === "labeling-new-task") {
      void queryClient.invalidateQueries({ queryKey: ["labeling-tasks-history"] });
      void queryClient.invalidateQueries({ queryKey: ["labeling-combined-tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["labeling-new-task-pool"] });
      void queryClient.invalidateQueries({ queryKey: ["review-assignments-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["access-users"] });
    } else if (page === "review") {
      void queryClient.invalidateQueries({ queryKey: ["review-gallery-cases"] });
      void queryClient.invalidateQueries({ queryKey: ["review-gallery-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["review-gallery-reviewers"] });
      void queryClient.invalidateQueries({ queryKey: ["review-gallery-work-assignees"] });
      void queryClient.invalidateQueries({ queryKey: ["review-gallery-task-options"] });
      void queryClient.invalidateQueries({ queryKey: ["review-gallery-task-context"] });
      void queryClient.invalidateQueries({ queryKey: ["review-gallery-config"] });
    } else if (page === "labeling") {
      void queryClient.invalidateQueries({ queryKey: ["labeling-gallery-cases"] });
      void queryClient.invalidateQueries({ queryKey: ["labeling-gallery-tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["labeling-gallery-config"] });
    }
    window.dispatchEvent(new Event("ra:workbench-sync"));
  },
  notifySync: () => {
    window.dispatchEvent(new Event("ra:workbench-sync"));
  },
};

(window as unknown as { __RA_REACT_WORKBENCH__?: ReactWorkbenchHandle }).__RA_REACT_WORKBENCH__ =
  handle;

const startupWindow = window as Window & {
  __RA_INITIAL_RUN_CATALOG__?: { page: CatalogPage; baselines: string; promise: Promise<unknown> };
};
const earlyRuns = startupWindow.__RA_INITIAL_RUN_CATALOG__;
if (earlyRuns) {
  delete startupWindow.__RA_INITIAL_RUN_CATALOG__;
  // Classic already reports its request errors. A later React mount can retry.
  void readInitialRuns(earlyRuns.page, earlyRuns.baselines, () => earlyRuns.promise).catch(() => {});
}

function installVitePreloadErrorGuard() {
  if (typeof window === "undefined") return;
  const flag = "__RA_VITE_PRELOAD_GUARD__";
  const win = window as unknown as Record<string, unknown>;
  if (win[flag]) return;
  win[flag] = true;

  window.addEventListener("vite:preloadError", (event) => {
    event.preventDefault();
    if (document.getElementById("raVersionUpdateNotice")) return;
    const isEnglish = () =>
      (document.documentElement?.dataset?.uiLang || document.documentElement?.lang || "")
        .toLowerCase()
        .startsWith("en");
    const banner = document.createElement("div");
    banner.id = "raVersionUpdateNotice";
    banner.className = "ra-version-update-banner";
    banner.setAttribute("role", "status");
    banner.setAttribute("aria-live", "polite");
    const dual = (zh: string, en: string) =>
      `<span class="ui-lang-zh">${zh}</span><span class="ui-lang-en">${en}</span>`;
    banner.innerHTML = `<span class="ra-version-update-icon" aria-hidden="true"><svg viewBox="0 0 20 20"><path d="M16.2 10a6.2 6.2 0 1 1-1.6-4.15"/><path d="M16.2 3.8v3.1h-3.1"/></svg></span><div class="ra-version-update-body"><div class="ra-version-update-head"><strong>${dual("新版看板已发布", "New version available")}</strong><button type="button" class="ra-version-update-dismiss"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.2 4.2 11.8 11.8M11.8 4.2 4.2 11.8"/></svg></button></div><p class="ra-version-update-desc">${dual("刷新即可加载最新资源，本地未保存草稿已保留。", "Reload to get the latest build. Unsaved drafts are kept.")}</p><div class="ra-version-update-actions"><button type="button" class="button button-primary ra-version-update-reload">${dual("立即刷新", "Reload now")}</button><button type="button" class="button button-quiet ra-version-update-later">${dual("稍后", "Later")}</button></div></div>`;
    const dismissBtn = banner.querySelector<HTMLButtonElement>(".ra-version-update-dismiss");
    const syncDismissCopy = () => {
      if (!dismissBtn) return;
      const en = isEnglish();
      dismissBtn.setAttribute("aria-label", en ? "Dismiss update notice" : "关闭更新提示");
      dismissBtn.title = en ? "Dismiss" : "关闭";
    };
    syncDismissCopy();
    const langObserver = new MutationObserver(syncDismissCopy);
    if (document.documentElement) {
      langObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-ui-lang", "lang"] });
    }
    const onKeyDown = (keyEvent: KeyboardEvent) => {
      if (keyEvent.key === "Escape") dismiss();
    };
    const dismiss = () => {
      langObserver.disconnect();
      window.removeEventListener("keydown", onKeyDown);
      banner.remove();
    };
    banner.querySelector(".ra-version-update-reload")?.addEventListener("click", () => window.location.reload());
    banner.querySelector(".ra-version-update-later")?.addEventListener("click", dismiss);
    dismissBtn?.addEventListener("click", dismiss);
    window.addEventListener("keydown", onKeyDown);
    document.body.append(banner);
  });
}

installVitePreloadErrorGuard();

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountAllIslands, { once: true });
} else {
  mountAllIslands();
}
