/* Persistent desktop split-pane resizing for the application shell and Review detail. */
const LAYOUT_WIDTH_PREFERENCES = {
  sidebar: {
    element: "#sidebarResizer",
    cssProperty: "--app-sidebar-width",
    storageKey: "ra-triage-sidebar-width",
    min: 190,
    max: 420,
    defaultValue: 240,
    direction: 1,
    enabled: () => window.matchMedia("(min-width: 1201px)").matches && !state.sidebarCollapsed,
  },
  review: {
    element: "#reviewPaneResizer",
    cssProperty: "--review-pane-width",
    storageKey: "ra-triage-review-pane-width",
    min: 304,
    max: 600,
    defaultValue: 350,
    direction: -1,
    availableMax: () => {
      const workspaceWidth = $(".review-detail-workspace")?.clientWidth || 0;
      return workspaceWidth ? Math.max(304, workspaceWidth - 528) : 600;
    },
    enabled: () => window.matchMedia("(min-width: 1025px)").matches && !$("#reviewDetailView")?.classList.contains("hidden"),
  },
};

function clampLayoutWidth(value, preference) {
  const availableMax = typeof preference.availableMax === "function" ? preference.availableMax() : preference.max;
  const effectiveMax = Math.min(preference.max, Math.max(preference.min, availableMax));
  return Math.round(Math.min(effectiveMax, Math.max(preference.min, Number(value) || preference.defaultValue)));
}

function currentLayoutWidth(preference) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(preference.cssProperty);
  return clampLayoutWidth(parseFloat(value), preference);
}

function applyLayoutWidth(preference, value, { persist = true } = {}) {
  const width = clampLayoutWidth(value, preference);
  document.documentElement.style.setProperty(preference.cssProperty, `${width}px`);
  const separator = $(preference.element);
  if (separator) {
    separator.setAttribute("aria-valuenow", String(width));
    separator.setAttribute("aria-valuemax", String(Math.max(width, Math.min(preference.max, preference.availableMax?.() || preference.max))));
  }
  if (persist) {
    try {
      localStorage.setItem(preference.storageKey, String(width));
    } catch (_) {
      // Storage is optional; resizing still works for the current page session.
    }
  }
  return width;
}

function bindLayoutResizer(preference) {
  const separator = $(preference.element);
  if (!separator || separator.dataset.layoutResizeBound === "1") return;
  separator.dataset.layoutResizeBound = "1";
  applyLayoutWidth(preference, currentLayoutWidth(preference), { persist: false });

  let drag = null;
  const finishDrag = (event) => {
    if (!drag || (event?.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
    applyLayoutWidth(preference, currentLayoutWidth(preference));
    const pointerId = drag.pointerId;
    drag = null;
    if (separator.hasPointerCapture?.(pointerId)) separator.releasePointerCapture(pointerId);
    separator.classList.remove("is-dragging");
    document.body.classList.remove("is-layout-resizing");
  };

  separator.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || !preference.enabled()) return;
    event.preventDefault();
    drag = { pointerId: event.pointerId, startX: event.clientX, startWidth: currentLayoutWidth(preference) };
    separator.setPointerCapture?.(event.pointerId);
    separator.classList.add("is-dragging");
    document.body.classList.add("is-layout-resizing");
  });
  separator.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    applyLayoutWidth(preference, drag.startWidth + ((event.clientX - drag.startX) * preference.direction), { persist: false });
  });
  separator.addEventListener("pointerup", finishDrag);
  separator.addEventListener("pointercancel", finishDrag);
  separator.addEventListener("lostpointercapture", finishDrag);
  separator.addEventListener("dblclick", () => {
    if (preference.enabled()) applyLayoutWidth(preference, preference.defaultValue);
  });
  separator.addEventListener("keydown", (event) => {
    if (!preference.enabled() || !["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Home") {
      applyLayoutWidth(preference, preference.defaultValue);
      return;
    }
    const visualDirection = event.key === "ArrowRight" ? 1 : -1;
    const step = event.shiftKey ? 40 : 10;
    applyLayoutWidth(preference, currentLayoutWidth(preference) + (visualDirection * preference.direction * step));
  });
}

function bindLayoutResizers() {
  Object.values(LAYOUT_WIDTH_PREFERENCES).forEach(bindLayoutResizer);
  window.addEventListener("resize", () => {
    Object.values(LAYOUT_WIDTH_PREFERENCES).forEach((preference) => {
      applyLayoutWidth(preference, currentLayoutWidth(preference), { persist: false });
    });
  });
}
