import React, { Suspense, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { apiRequest } from "./api/client";
import { useWorkbenchBridge, WorkbenchBridgeState } from "./bridge/useWorkbenchBridge";
import { SystemStatusPage } from "./pages/SystemStatusPage";
import { UsersPage } from "./pages/UsersPage";
import "./core/shortcutManager";
import "./styles/react-workbench.css";

const ReviewAssignmentsPage = React.lazy(() =>
  import("./pages/ReviewAssignmentsPage").then((m) => ({ default: m.ReviewAssignmentsPage })),
);
const AllocationEditorModal = React.lazy(() =>
  import("./features/allocation/AllocationEditorModal").then((m) => ({
    default: m.AllocationEditorModal,
  })),
);
const DailyCronPage = React.lazy(() =>
  import("./pages/DailyCronPage").then((m) => ({ default: m.DailyCronPage })),
);
const RunsManagerIsland = React.lazy(() =>
  import("./pages/RunsManagerIsland").then((m) => ({ default: m.RunsManagerIsland })),
);
const VersionDatasetsPage = React.lazy(() =>
  import("./pages/VersionDatasetsPage").then((m) => ({ default: m.VersionDatasetsPage })),
);
const VersionMetricsPage = React.lazy(() =>
  import("./pages/VersionMetricsPage").then((m) => ({ default: m.VersionMetricsPage })),
);
const AnalysisPage = React.lazy(() =>
  import("./pages/AnalysisPage").then((m) => ({ default: m.AnalysisPage })),
);
const RunComparisonPage = React.lazy(() =>
  import("./pages/RunComparisonPage").then((m) => ({ default: m.RunComparisonPage })),
);
const RunCollectionsPage = React.lazy(() =>
  import("./pages/RunCollectionsPage").then((m) => ({ default: m.RunCollectionsPage })),
);
const ReviewPage = React.lazy(() =>
  import("./pages/ReviewPage").then((m) => ({ default: m.ReviewPage })),
);
const CaseLabelingPage = React.lazy(() =>
  import("./pages/CaseLabelingPage").then((m) => ({ default: m.CaseLabelingPage })),
);
const LabelingNewTaskPage = React.lazy(() =>
  import("./pages/LabelingNewTaskPage").then((m) => ({ default: m.LabelingNewTaskPage })),
);
const LabelingSummaryPage = React.lazy(() =>
  import("./pages/LabelingSummaryPage").then((m) => ({ default: m.LabelingSummaryPage })),
);
const RdResultsPage = React.lazy(() =>
  import("./pages/RdResultsPage").then((m) => ({ default: m.RdResultsPage })),
);

const OWNED_PAGES = new Set<string>([
  "status",
  "users",
  "review-assignments",
  "daily-cron",
  "runs-manager",
  "version-datasets",
  "version-metrics",
  "analysis",
  "comparison",
  "run-collections",
  "review",
  "labeling",
  "labeling-new-task",
  "labeling-summary",
  "rd-results",
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

const LoadingFallback: React.FC<{ lang: string }> = ({ lang }) => (
  <div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>
);

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

const ReviewAssignmentsIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  const active = activePage === "review-assignments";
  const { effectiveSession } = useResolvedSession(active);
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <ReviewAssignmentsPage
        active={active}
        lang={lang}
        isAdmin={Boolean(effectiveSession?.is_admin)}
        username={effectiveSession?.username || ""}
      />
    </Suspense>
  );
};

const DailyCronIsland: React.FC = () => {
  const { activePage, lang, theme } = useWorkbenchBridge();
  const active = activePage === "daily-cron";
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <DailyCronPage active={active} lang={lang} theme={theme} />
    </Suspense>
  );
};

const RunsManagerReactIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  const active = activePage === "runs";
  const { effectiveSession } = useResolvedSession(active);
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <RunsManagerIsland
        active={active}
        lang={lang}
        username={effectiveSession?.username || ""}
      />
    </Suspense>
  );
};

const VersionDatasetsIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <VersionDatasetsPage active={activePage === "version-datasets"} lang={lang} />
    </Suspense>
  );
};

const VersionMetricsIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  const active = activePage === "version-metrics";
  const { effectiveSession } = useResolvedSession(active);
  const canWrite = Boolean(
    effectiveSession?.verified &&
      (effectiveSession.can_write ||
        effectiveSession.is_admin ||
        ["writer", "admin"].includes(String(effectiveSession.access_role || ""))),
  );
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <VersionMetricsPage active={active} lang={lang} canWrite={canWrite} />
    </Suspense>
  );
};

const AnalysisIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <AnalysisPage
        active={activePage === "analysis"}
        lang={lang}
        selectedBaselines={selectedBaselines}
      />
    </Suspense>
  );
};

const RunComparisonIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "comparison";
  const { effectiveSession } = useResolvedSession(active);
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <RunComparisonPage
        active={active}
        lang={lang}
        selectedBaselines={selectedBaselines}
        isAdmin={Boolean(effectiveSession?.is_admin && effectiveSession?.verified)}
      />
    </Suspense>
  );
};

const RunCollectionsIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "run-collections";
  const { effectiveSession } = useResolvedSession(active);
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <RunCollectionsPage
        active={active}
        lang={lang}
        isAdmin={Boolean(effectiveSession?.is_admin && effectiveSession?.verified)}
        selectedBaselines={selectedBaselines}
      />
    </Suspense>
  );
};

const ReviewIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "review";
  const { effectiveSession } = useResolvedSession(active);
  const canWrite = Boolean(
    effectiveSession?.verified &&
      (effectiveSession.can_write ||
        effectiveSession.is_admin ||
        ["writer", "admin"].includes(String(effectiveSession.access_role || ""))),
  );
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <ReviewPage
        active={active}
        lang={lang}
        selectedBaselines={selectedBaselines}
        username={effectiveSession?.username || ""}
        canWrite={canWrite}
        isAdmin={Boolean(effectiveSession?.is_admin && effectiveSession?.verified)}
      />
    </Suspense>
  );
};

const CaseLabelingIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "labeling";
  const { effectiveSession } = useResolvedSession(active);
  const canWrite = Boolean(
    effectiveSession?.verified &&
      (effectiveSession.can_write ||
        effectiveSession.is_admin ||
        ["writer", "admin"].includes(String(effectiveSession.access_role || ""))),
  );
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <CaseLabelingPage
        active={active}
        lang={lang}
        selectedBaselines={selectedBaselines}
        username={effectiveSession?.username || ""}
        canWrite={canWrite}
        isAdmin={Boolean(effectiveSession?.is_admin && effectiveSession?.verified)}
      />
    </Suspense>
  );
};

const LabelingNewTaskIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "labeling-new-task";
  const { effectiveSession } = useResolvedSession(active);
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <LabelingNewTaskPage
        active={active}
        lang={lang}
        isAdmin={Boolean(effectiveSession?.is_admin && effectiveSession?.verified)}
        selectedBaselines={selectedBaselines}
      />
    </Suspense>
  );
};

const LabelingSummaryIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "labeling-summary";
  const { effectiveSession } = useResolvedSession(active);
  const canWrite = Boolean(
    effectiveSession?.verified &&
      (effectiveSession.can_write ||
        effectiveSession.is_admin ||
        ["writer", "admin"].includes(String(effectiveSession.access_role || ""))),
  );
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <LabelingSummaryPage
        active={active}
        lang={lang}
        selectedBaselines={selectedBaselines}
        username={effectiveSession?.username || ""}
        canWrite={canWrite}
        isAdmin={Boolean(effectiveSession?.is_admin && effectiveSession?.verified)}
      />
    </Suspense>
  );
};

const RdResultsIsland: React.FC = () => {
  const { activePage, lang, selectedBaselines } = useWorkbenchBridge();
  const active = activePage === "rd-results";
  const { effectiveSession } = useResolvedSession(active);
  return (
    <Suspense fallback={<LoadingFallback lang={lang} />}>
      <RdResultsPage
        active={active}
        lang={lang}
        isAdmin={Boolean(effectiveSession?.is_admin && effectiveSession?.verified)}
        selectedBaselines={selectedBaselines}
      />
    </Suspense>
  );
};

let openExternalAllocationModal: ((campaignId: string) => void) | null = null;

const GlobalAllocationModalPortal: React.FC = () => {
  const { lang } = useWorkbenchBridge();
  const [campaignId, setCampaignId] = useState<string | null>(null);

  useEffect(() => {
    openExternalAllocationModal = (id: string) => setCampaignId(id);
    return () => {
      openExternalAllocationModal = null;
    };
  }, []);

  if (!campaignId) return null;
  return (
    <Suspense fallback={null}>
      <AllocationEditorModal
        campaignId={campaignId}
        lang={lang}
        onClose={() => setCampaignId(null)}
        onSaved={() => {
          void queryClient.invalidateQueries({ queryKey: ["review-assignments-list"] });
          const win = window as unknown as { refreshTaskAllocationLists?: () => void };
          win.refreshTaskAllocationLists?.();
        }}
      />
    </Suspense>
  );
};

interface ReactWorkbenchHandle {
  version: string;
  ownsPage: (page: string) => boolean;
  refreshPage: (page: string) => void;
  notifySync: () => void;
  openTaskAllocationEditor: (campaignId: string) => boolean;
}

function mountSection(element: HTMLElement | null, node: React.ReactElement): void {
  if (!element || element.dataset.reactMounted === "true") return;
  element.dataset.reactMounted = "true";
  element.replaceChildren();
  createRoot(element).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>{node}</QueryClientProvider>
    </React.StrictMode>,
  );
}

function mountIslands(): void {
  mountSection(document.getElementById("systemStatusPage"), <SystemStatusIsland />);
  mountSection(document.getElementById("userManagementPage"), <UsersIsland />);
  mountSection(document.getElementById("reviewAssignmentsPage"), <ReviewAssignmentsIsland />);
  mountSection(document.getElementById("dailyCronPage"), <DailyCronIsland />);
  mountSection(
    document.querySelector<HTMLElement>("#runsPage .runs-page-card"),
    <RunsManagerReactIsland />,
  );
  mountSection(document.getElementById("versionDatasetsPage"), <VersionDatasetsIsland />);
  mountSection(document.getElementById("versionMetricsPage"), <VersionMetricsIsland />);
  mountSection(document.getElementById("reviewAnalysisPage"), <AnalysisIsland />);
  mountSection(document.getElementById("runComparisonPage"), <RunComparisonIsland />);
  mountSection(document.getElementById("runCollectionsPage"), <RunCollectionsIsland />);
  mountSection(document.getElementById("reviewPage"), <ReviewIsland />);
  mountSection(document.getElementById("caseLabelingPage"), <CaseLabelingIsland />);
  mountSection(document.getElementById("caseLabelingNewTaskPage"), <LabelingNewTaskIsland />);
  mountSection(document.getElementById("labelingSummaryPage"), <LabelingSummaryIsland />);
  mountSection(document.getElementById("rdResultsPage"), <RdResultsIsland />);

  let modalRoot = document.getElementById("raReactModalRoot");
  if (!modalRoot) {
    modalRoot = document.createElement("div");
    modalRoot.id = "raReactModalRoot";
    document.body.appendChild(modalRoot);
    createRoot(modalRoot).render(
      <React.StrictMode>
        <QueryClientProvider client={queryClient}>
          <GlobalAllocationModalPortal />
        </QueryClientProvider>
      </React.StrictMode>,
    );
  }
}

const handle: ReactWorkbenchHandle = {
  version: "vite-react-ts-3.5",
  ownsPage: (page: string) => OWNED_PAGES.has(page),
  refreshPage: (page: string) => {
    if (page === "status") {
      void queryClient.invalidateQueries({ queryKey: ["system-status"] });
    } else if (page === "users") {
      void queryClient.invalidateQueries({ queryKey: ["access-users"] });
      void queryClient.invalidateQueries({ queryKey: ["mention-users"] });
    } else if (page === "review-assignments") {
      void queryClient.invalidateQueries({ queryKey: ["review-assignments-list"] });
      void queryClient.invalidateQueries({ queryKey: ["review-assignment-detail"] });
    } else if (page === "daily-cron") {
      void queryClient.invalidateQueries({ queryKey: ["daily-cron"] });
    } else if (page === "runs-manager") {
      void queryClient.invalidateQueries({ queryKey: ["model-runs"] });
    } else if (page === "version-datasets") {
      void queryClient.invalidateQueries({ queryKey: ["version-datasets-workbench"] });
      void queryClient.invalidateQueries({ queryKey: ["version-datasets-catalog"] });
    } else if (page === "version-metrics") {
      void queryClient.invalidateQueries({ queryKey: ["version-metrics"] });
    } else if (page === "analysis") {
      void queryClient.invalidateQueries({ queryKey: ["review-reason-analysis"] });
    } else if (page === "comparison") {
      void queryClient.invalidateQueries({ queryKey: ["model-run-comparison"] });
    } else if (page === "run-collections") {
      void queryClient.invalidateQueries({ queryKey: ["run-collections-list"] });
      void queryClient.invalidateQueries({ queryKey: ["run-collection-detail"] });
      void queryClient.invalidateQueries({ queryKey: ["run-evaluation-detail"] });
    } else if (page === "review") {
      void queryClient.invalidateQueries({ queryKey: ["review-cases"] });
      void queryClient.invalidateQueries({ queryKey: ["review-case-detail"] });
      void queryClient.invalidateQueries({ queryKey: ["combined-review-context"] });
    } else if (page === "labeling") {
      void queryClient.invalidateQueries({ queryKey: ["labeling-cases"] });
      void queryClient.invalidateQueries({ queryKey: ["labeling-case-detail"] });
      void queryClient.invalidateQueries({ queryKey: ["labeling-tasks"] });
    } else if (page === "labeling-new-task") {
      void queryClient.invalidateQueries({ queryKey: ["labeling-tasks-history"] });
      void queryClient.invalidateQueries({ queryKey: ["labeling-combined-tasks"] });
    } else if (page === "labeling-summary") {
      void queryClient.invalidateQueries({ queryKey: ["labeling-summary-data"] });
    } else if (page === "rd-results") {
      void queryClient.invalidateQueries({ queryKey: ["rd-results-list"] });
      void queryClient.invalidateQueries({ queryKey: ["human-publications-list"] });
    }
    window.dispatchEvent(new Event("ra:workbench-sync"));
  },
  notifySync: () => {
    window.dispatchEvent(new Event("ra:workbench-sync"));
  },
  openTaskAllocationEditor: (campaignId: string) => {
    if (!openExternalAllocationModal) return false;
    openExternalAllocationModal(campaignId);
    return true;
  },
};

(window as unknown as { __RA_REACT_WORKBENCH__?: ReactWorkbenchHandle }).__RA_REACT_WORKBENCH__ =
  handle;

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mountIslands, { once: true });
} else {
  mountIslands();
}
