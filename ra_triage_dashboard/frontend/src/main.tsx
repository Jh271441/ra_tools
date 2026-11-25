import React, { Suspense } from "react";
import { createRoot, Root } from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
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
const RunCollectionsPage = React.lazy(() =>
  import("./pages/RunCollectionsPage").then((m) => ({ default: m.RunCollectionsPage })),
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
  "run-collections",
  "trail-history",
  "rd-results",
  "prediction",
  "intent-summary",
  "intent-experiments",
  "trail-update",
  "campaigns",
  "intent",
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

const RunCollectionsIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "run-collections";
  const { effectiveSession } = useResolvedSession(active);
  if (!active) return null;
  const canWrite = Boolean(effectiveSession?.is_admin && effectiveSession?.verified);
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <RunCollectionsPage
        active={active}
        lang={lang}
        selectedBaselines={selectedBaselines}
        canWrite={canWrite}
      />
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
  mountIsland(document.getElementById("runCollectionsPage"), <RunCollectionsIsland />);
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
}

interface ReactWorkbenchHandle {
  version: string;
  ownedPages: string[];
  ownsPage: (page: string) => boolean;
  refreshPage: (page: string) => void;
  notifySync: () => void;
}

const handle: ReactWorkbenchHandle = {
  version: "vite-react-ts-strangler-3.8",
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
    } else if (page === "run-collections") {
      void queryClient.invalidateQueries({ queryKey: ["run-collections-list"] });
      void queryClient.invalidateQueries({ queryKey: ["run-collection-detail"] });
      void queryClient.invalidateQueries({ queryKey: ["run-collection-eval-history"] });
      void queryClient.invalidateQueries({ queryKey: ["run-collection-evaluation"] });
    } else if (page === "trail-history") {
      void queryClient.invalidateQueries({ queryKey: ["trail-history"] });
    } else if (page === "rd-results") {
      void queryClient.invalidateQueries({ queryKey: ["human-publications"] });
      void queryClient.invalidateQueries({ queryKey: ["rd-results"] });
    } else if (page === "prediction") {
      void queryClient.invalidateQueries({ queryKey: ["prediction-batches"] });
      void queryClient.invalidateQueries({ queryKey: ["prediction-batch-config"] });
      void queryClient.invalidateQueries({ queryKey: ["prediction-gateway-models"] });
      void queryClient.invalidateQueries({ queryKey: ["prediction-batch-prompts"] });
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
    }
    window.dispatchEvent(new Event("ra:workbench-sync"));
  },
  notifySync: () => {
    window.dispatchEvent(new Event("ra:workbench-sync"));
  },
};

(window as unknown as { __RA_REACT_WORKBENCH__?: ReactWorkbenchHandle }).__RA_REACT_WORKBENCH__ =
  handle;

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountAllIslands, { once: true });
} else {
  mountAllIslands();
}
