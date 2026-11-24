import React, { Suspense, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { apiRequest } from "./api/client";
import { useWorkbenchBridge, WorkbenchBridgeState } from "./bridge/useWorkbenchBridge";
import { SystemStatusPage } from "./pages/SystemStatusPage";
import { UsersPage } from "./pages/UsersPage";
import "./styles/react-workbench.css";

const ReviewAssignmentsPage = React.lazy(() =>
  import("./pages/ReviewAssignmentsPage").then((m) => ({ default: m.ReviewAssignmentsPage })),
);
const AllocationEditorModal = React.lazy(() =>
  import("./features/allocation/AllocationEditorModal").then((m) => ({
    default: m.AllocationEditorModal,
  })),
);

const OWNED_PAGES = new Set<string>(["status", "users", "review-assignments"]);

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

const ReviewAssignmentsIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  const active = activePage === "review-assignments";
  const { effectiveSession } = useResolvedSession(active);
  return (
    <Suspense fallback={<div className="no-asset">{lang === "en" ? "Loading…" : "加载中…"}</div>}>
      <ReviewAssignmentsPage
        active={active}
        lang={lang}
        isAdmin={Boolean(effectiveSession?.is_admin)}
        username={effectiveSession?.username || ""}
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

function mountIslands(): void {
  const statusSection = document.getElementById("systemStatusPage");
  if (statusSection && statusSection.dataset.reactMounted !== "true") {
    statusSection.dataset.reactMounted = "true";
    statusSection.replaceChildren();
    createRoot(statusSection).render(
      <React.StrictMode>
        <QueryClientProvider client={queryClient}>
          <SystemStatusIsland />
        </QueryClientProvider>
      </React.StrictMode>,
    );
  }

  const usersSection = document.getElementById("userManagementPage");
  if (usersSection && usersSection.dataset.reactMounted !== "true") {
    usersSection.dataset.reactMounted = "true";
    usersSection.replaceChildren();
    createRoot(usersSection).render(
      <React.StrictMode>
        <QueryClientProvider client={queryClient}>
          <UsersIsland />
        </QueryClientProvider>
      </React.StrictMode>,
    );
  }

  const assignmentsSection = document.getElementById("reviewAssignmentsPage");
  if (assignmentsSection && assignmentsSection.dataset.reactMounted !== "true") {
    assignmentsSection.dataset.reactMounted = "true";
    assignmentsSection.replaceChildren();
    createRoot(assignmentsSection).render(
      <React.StrictMode>
        <QueryClientProvider client={queryClient}>
          <ReviewAssignmentsIsland />
        </QueryClientProvider>
      </React.StrictMode>,
    );
  }

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
  version: "vite-react-ts-3.2",
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
