import { $, state } from "./state.js";

const LEAVE_MS = 130;

export function setView(view) {
  if (state.activeView === view) return;
  const outEl = document.querySelector(".view-pane.active");

  const activate = () => {
    if (outEl) outEl.classList.remove("is-leaving");
    state.activeView = view;
    document.querySelectorAll(".view-tab").forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.view === view);
    });
    $("workflowView").classList.toggle("active", view === "workflow");
    $("releaseView").classList.toggle("active", view === "release");
  };

  if (outEl) {
    outEl.classList.add("is-leaving");
    setTimeout(activate, LEAVE_MS);
  } else {
    activate();
  }
}

export function setSidebarCollapsed(collapsed) {
  state.sidebarCollapsed = collapsed;
  document.querySelector(".app-shell").classList.toggle("sidebar-collapsed", collapsed);
  const toggle = $("sidebarToggle");
  if (toggle) {
    toggle.classList.toggle("active", !collapsed);
    toggle.title = collapsed ? "Show Release Runs" : "Hide Release Runs";
    toggle.textContent = collapsed ? "›" : "⌄";
  }
}

export function setRailCollapsed(collapsed) {
  state.railCollapsed = collapsed;
  document.querySelector(".app-shell").classList.toggle("rail-collapsed", collapsed);
  const toggle = $("railToggle");
  if (toggle) {
    toggle.title = collapsed ? "Expand toolbar" : "Collapse toolbar";
    const icon = toggle.querySelector(".rail-icon");
    if (icon) icon.textContent = collapsed ? "›" : "‹";
  }
}
