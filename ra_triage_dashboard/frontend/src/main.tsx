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

const OWNED_PAGES = new Set<string>([
  "status",
  "users",
  "daily-cron",
  "runs-manager",
  "version-metrics",
  "version-datasets",
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
}

interface ReactWorkbenchHandle {
  version: string;
  ownedPages: string[];
  ownsPage: (page: string) => boolean;
  refreshPage: (page: string) => void;
  notifySync: () => void;
}

const handle: ReactWorkbenchHandle = {
  version: "vite-react-ts-strangler-3.3",
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
