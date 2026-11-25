import React, { Suspense } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { bilingual } from "./bridge/useWorkbenchBridge";
import { AppShell } from "./shell/AppShell";
import { useWorkbench, WorkbenchProvider } from "./shell/WorkbenchContext";
import "./core/shortcutManager";
import "./styles/react-workbench.css";

// All 23 pages are lazy-loaded per-route chunks to keep initial JS < 120 KB gzip.
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
const TrailUpdatePage = React.lazy(() =>
  import("./pages/TrailUpdatePage").then((m) => ({ default: m.TrailUpdatePage })),
);
const ReviewAssignmentsPage = React.lazy(() =>
  import("./pages/ReviewAssignmentsPage").then((m) => ({ default: m.ReviewAssignmentsPage })),
);
const AnalysisPage = React.lazy(() =>
  import("./pages/AnalysisPage").then((m) => ({ default: m.AnalysisPage })),
);
const RunsPage = React.lazy(() =>
  import("./pages/RunsPage").then((m) => ({ default: m.RunsPage })),
);
const RunComparisonPage = React.lazy(() =>
  import("./pages/RunComparisonPage").then((m) => ({ default: m.RunComparisonPage })),
);
const RunCollectionsPage = React.lazy(() =>
  import("./pages/RunCollectionsPage").then((m) => ({ default: m.RunCollectionsPage })),
);
const PredictionPage = React.lazy(() =>
  import("./pages/PredictionPage").then((m) => ({ default: m.PredictionPage })),
);
const CampaignsPage = React.lazy(() =>
  import("./pages/CampaignsPage").then((m) => ({ default: m.CampaignsPage })),
);
const VersionDatasetsPage = React.lazy(() =>
  import("./pages/VersionDatasetsPage").then((m) => ({ default: m.VersionDatasetsPage })),
);
const VersionMetricsPage = React.lazy(() =>
  import("./pages/VersionMetricsPage").then((m) => ({ default: m.VersionMetricsPage })),
);
const DailyCronPage = React.lazy(() =>
  import("./pages/DailyCronPage").then((m) => ({ default: m.DailyCronPage })),
);
const DailyReviewPage = React.lazy(() =>
  import("./pages/DailyReviewPage").then((m) => ({ default: m.DailyReviewPage })),
);
const IntentLabelingPage = React.lazy(() =>
  import("./pages/IntentLabelingPage").then((m) => ({ default: m.IntentLabelingPage })),
);
const IntentExperimentsPage = React.lazy(() =>
  import("./pages/IntentExperimentsPage").then((m) => ({ default: m.IntentExperimentsPage })),
);
const IntentSummaryPage = React.lazy(() =>
  import("./pages/IntentSummaryPage").then((m) => ({ default: m.IntentSummaryPage })),
);
const TrailHistoryPage = React.lazy(() =>
  import("./pages/TrailHistoryPage").then((m) => ({ default: m.TrailHistoryPage })),
);
const SystemStatusPage = React.lazy(() =>
  import("./pages/SystemStatusPage").then((m) => ({ default: m.SystemStatusPage })),
);
const UsersPage = React.lazy(() =>
  import("./pages/UsersPage").then((m) => ({ default: m.UsersPage })),
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const PageFallback: React.FC<{ lang: "zh" | "en" }> = ({ lang }) => (
  <div className="panel-card">
    <div className="no-asset">{bilingual(lang, "正在加载页面模块…", "Loading page…")}</div>
  </div>
);

const ActiveRouteView: React.FC = () => {
  const { activePage, lang, theme, selectedBaselines, session, sessionLoading } = useWorkbench();
  const isAdmin = Boolean(session.is_admin && session.verified);
  const canWrite = Boolean(session.verified && (session.can_write || session.is_admin));
  const username = session.username || "";

  let content: React.ReactNode;
  switch (activePage) {
    case "review":
      content = (
        <section id="reviewPage" className="app-page" data-page="review" data-react-mounted="true">
          <ReviewPage
            active
            lang={lang}
            selectedBaselines={selectedBaselines}
            username={username}
            canWrite={canWrite}
            isAdmin={isAdmin}
          />
        </section>
      );
      break;
    case "labeling":
      content = (
        <section id="caseLabelingPage" className="app-page" data-page="labeling" data-react-mounted="true">
          <CaseLabelingPage
            active
            lang={lang}
            selectedBaselines={selectedBaselines}
            username={username}
            canWrite={canWrite}
            isAdmin={isAdmin}
          />
        </section>
      );
      break;
    case "labeling-new-task":
      content = (
        <section id="caseLabelingNewTaskPage" className="app-page" data-page="labeling-new-task" data-react-mounted="true">
          <LabelingNewTaskPage active lang={lang} isAdmin={isAdmin} selectedBaselines={selectedBaselines} />
        </section>
      );
      break;
    case "labeling-summary":
      content = (
        <section id="labelingSummaryPage" className="app-page" data-page="labeling-summary" data-react-mounted="true">
          <LabelingSummaryPage
            active
            lang={lang}
            selectedBaselines={selectedBaselines}
            username={username}
            canWrite={canWrite}
            isAdmin={isAdmin}
          />
        </section>
      );
      break;
    case "rd-results":
      content = (
        <section id="rdResultsPage" className="app-page" data-page="rd-results" data-react-mounted="true">
          <RdResultsPage active lang={lang} isAdmin={isAdmin} selectedBaselines={selectedBaselines} />
        </section>
      );
      break;
    case "trail-update":
      content = <TrailUpdatePage active lang={lang} selectedBaselines={selectedBaselines} />;
      break;
    case "review-assignments":
      content = (
        <section id="reviewAssignmentsPage" className="app-page" data-page="review-assignments" data-react-mounted="true">
          <ReviewAssignmentsPage active lang={lang} isAdmin={isAdmin} username={username} />
        </section>
      );
      break;
    case "analysis":
      content = (
        <section id="reviewAnalysisPage" className="app-page" data-page="analysis" data-react-mounted="true">
          <AnalysisPage active lang={lang} selectedBaselines={selectedBaselines} />
        </section>
      );
      break;
    case "runs":
      content = <RunsPage active lang={lang} username={username} />;
      break;
    case "comparison":
      content = (
        <section id="runComparisonPage" className="app-page" data-page="comparison" data-react-mounted="true">
          <RunComparisonPage active lang={lang} selectedBaselines={selectedBaselines} isAdmin={isAdmin} />
        </section>
      );
      break;
    case "run-collections":
      content = (
        <section id="runCollectionsPage" className="app-page" data-page="run-collections" data-react-mounted="true">
          <RunCollectionsPage active lang={lang} isAdmin={isAdmin} selectedBaselines={selectedBaselines} />
        </section>
      );
      break;
    case "prediction":
      content = <PredictionPage active lang={lang} />;
      break;
    case "campaigns":
      content = (
        <CampaignsPage active lang={lang} selectedBaselines={selectedBaselines} isAdmin={isAdmin} />
      );
      break;
    case "version-datasets":
      content = (
        <section id="versionDatasetsPage" className="app-page" data-page="version-datasets" data-react-mounted="true">
          <VersionDatasetsPage active lang={lang} />
        </section>
      );
      break;
    case "version-metrics":
      content = (
        <section id="versionMetricsPage" className="app-page" data-page="version-metrics" data-react-mounted="true">
          <VersionMetricsPage active lang={lang} canWrite={canWrite} />
        </section>
      );
      break;
    case "daily-cron":
      content = (
        <section id="dailyCronPage" className="app-page" data-page="daily-cron" data-react-mounted="true">
          <DailyCronPage active lang={lang} theme={theme} />
        </section>
      );
      break;
    case "daily-review":
      content = <DailyReviewPage active lang={lang} />;
      break;
    case "intent":
      content = <IntentLabelingPage active lang={lang} />;
      break;
    case "intent-experiments":
      content = <IntentExperimentsPage active lang={lang} />;
      break;
    case "intent-summary":
      content = <IntentSummaryPage active lang={lang} />;
      break;
    case "trail-history":
      content = <TrailHistoryPage active lang={lang} selectedBaselines={selectedBaselines} />;
      break;
    case "status":
      content = (
        <section id="systemStatusPage" className="app-page" data-page="status" data-react-mounted="true">
          <SystemStatusPage active lang={lang} />
        </section>
      );
      break;
    case "users":
      content = (
        <section id="userManagementPage" className="app-page" data-page="users" data-react-mounted="true">
          <UsersPage active lang={lang} isAdmin={isAdmin} sessionLoading={sessionLoading} />
        </section>
      );
      break;
    default:
      content = (
        <section id="reviewPage" className="app-page" data-page="review" data-react-mounted="true">
          <ReviewPage
            active
            lang={lang}
            selectedBaselines={selectedBaselines}
            username={username}
            canWrite={canWrite}
            isAdmin={isAdmin}
          />
        </section>
      );
  }

  return <Suspense fallback={<PageFallback lang={lang} />}>{content}</Suspense>;
};

export const WorkbenchApp: React.FC = () => (
  <QueryClientProvider client={queryClient}>
    <WorkbenchProvider>
      <AppShell>
        <ActiveRouteView />
      </AppShell>
    </WorkbenchProvider>
  </QueryClientProvider>
);

function mountWorkbench(): void {
  const host = document.getElementById("raWorkbenchRoot") || document.body;
  if (host.dataset.reactMounted === "true") return;
  host.dataset.reactMounted = "true";
  createRoot(host).render(
    <React.StrictMode>
      <WorkbenchApp />
    </React.StrictMode>,
  );
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountWorkbench, { once: true });
  } else {
    mountWorkbench();
  }
}
