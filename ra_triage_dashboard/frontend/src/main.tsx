import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { apiRequest } from "./api/client";
import { useWorkbenchBridge, WorkbenchBridgeState } from "./bridge/useWorkbenchBridge";
import { SystemStatusPage } from "./pages/SystemStatusPage";
import { UsersPage } from "./pages/UsersPage";
import "./styles/react-workbench.css";

const OWNED_PAGES = new Set<string>(["status", "users"]);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const SystemStatusIsland: React.FC = () => {
  const { activePage, lang } = useWorkbenchBridge();
  return <SystemStatusPage active={activePage === "status"} lang={lang} />;
};

const UsersIsland: React.FC = () => {
  const { activePage, lang, session } = useWorkbenchBridge();
  const active = activePage === "users";
  const sessionQuery = useQuery<NonNullable<WorkbenchBridgeState["session"]>>({
    queryKey: ["session"],
    queryFn: ({ signal }) =>
      apiRequest<NonNullable<WorkbenchBridgeState["session"]>>("/api/session", { signal }),
    enabled: active && !session?.verified,
    staleTime: 30_000,
  });
  const effectiveSession = session?.verified ? session : sessionQuery.data || session;
  const sessionLoading = active && !effectiveSession?.verified && sessionQuery.isFetching;
  return (
    <UsersPage
      active={active}
      lang={lang}
      isAdmin={Boolean(effectiveSession?.is_admin)}
      sessionLoading={sessionLoading}
    />
  );
};

interface ReactWorkbenchHandle {
  version: string;
  ownsPage: (page: string) => boolean;
  refreshPage: (page: string) => void;
  notifySync: () => void;
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
}

const handle: ReactWorkbenchHandle = {
  version: "vite-react-ts-3.1",
  ownsPage: (page: string) => OWNED_PAGES.has(page),
  refreshPage: (page: string) => {
    if (page === "status") {
      void queryClient.invalidateQueries({ queryKey: ["system-status"] });
    } else if (page === "users") {
      void queryClient.invalidateQueries({ queryKey: ["access-users"] });
      void queryClient.invalidateQueries({ queryKey: ["mention-users"] });
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
  document.addEventListener("DOMContentLoaded", mountIslands, { once: true });
} else {
  mountIslands();
}
