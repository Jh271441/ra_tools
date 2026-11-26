import { useEffect, useState } from "react";
import { getApiBasePath } from "../api/client";

export type UiLanguage = "zh" | "en";
export type ColorTheme = "dark" | "light";

export interface WorkbenchBridgeState {
  lang: UiLanguage;
  theme: ColorTheme;
  activePage: string;
  selectedBaselines: string[];
  session: {
    authenticated: boolean;
    verified: boolean;
    username: string;
    access_role: string;
    is_admin: boolean;
    can_write: boolean;
    can_view_intent?: boolean;
    can_manage_intent?: boolean;
    can_annotate_intent?: boolean;
    read_only?: boolean;
  } | null;
}

export function getWorkbenchBasePath(): string {
  return getApiBasePath();
}

export function withWorkbenchBase(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const base = getWorkbenchBasePath();
  if (!base) return normalized;
  if (normalized === base || normalized.startsWith(`${base}/`)) return normalized;
  return `${base}${normalized}`;
}

function readSelectedBaselines(): string[] {
  if (typeof window === "undefined") return [];
  const win = window as unknown as {
    __RA_TRIAGE_STATE__?: { selectedBaselineIds?: string[] };
    state?: { selectedBaselineIds?: string[] };
  };
  const ids = win.__RA_TRIAGE_STATE__?.selectedBaselineIds || win.state?.selectedBaselineIds;
  if (Array.isArray(ids) && ids.length) return ids.map(String).filter(Boolean);
  const urlParam = new URLSearchParams(window.location.search).get("baselines") || "";
  return urlParam ? urlParam.split(",").map((s) => s.trim()).filter(Boolean) : [];
}

function readLang(): UiLanguage {
  if (typeof document === "undefined") return "zh";
  return document.documentElement.dataset.uiLang === "en" ? "en" : "zh";
}

function readTheme(): ColorTheme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.dataset.colorTheme === "light" ? "light" : "dark";
}

function readActivePage(): string {
  return typeof document === "undefined" ? "" : document.body?.dataset.activePage || "";
}

function readLegacySession(): WorkbenchBridgeState["session"] {
  if (typeof window === "undefined") return null;
  const win = window as unknown as {
    __RA_TRIAGE_SESSION__?: WorkbenchBridgeState["session"];
    __RA_TRIAGE_STATE__?: { session?: WorkbenchBridgeState["session"] };
    state?: { session?: WorkbenchBridgeState["session"] };
  };
  return win.__RA_TRIAGE_SESSION__ || win.__RA_TRIAGE_STATE__?.session || win.state?.session || null;
}

export function useWorkbenchBridge(): WorkbenchBridgeState {
  const [state, setState] = useState<WorkbenchBridgeState>(() => ({
    lang: readLang(),
    theme: readTheme(),
    activePage: readActivePage(),
    selectedBaselines: readSelectedBaselines(),
    session: readLegacySession(),
  }));

  useEffect(() => {
    const sync = () => {
      setState((prev) => {
        const nextLang = readLang();
        const nextTheme = readTheme();
        const nextPage = readActivePage();
        const nextBaselines = readSelectedBaselines();
        const nextSession = readLegacySession();
        if (
          prev.lang === nextLang &&
          prev.theme === nextTheme &&
          prev.activePage === nextPage &&
          prev.session === nextSession &&
          prev.selectedBaselines.join(",") === nextBaselines.join(",")
        ) {
          return prev;
        }
        return {
          lang: nextLang,
          theme: nextTheme,
          activePage: nextPage,
          selectedBaselines: nextBaselines,
          session: nextSession,
        };
      });
    };

    window.addEventListener("popstate", sync);
    window.addEventListener("ra:workbench-sync", sync);
    sync();
    let observer: MutationObserver | null = null;
    if (typeof MutationObserver !== "undefined" && typeof document !== "undefined") {
      observer = new MutationObserver(sync);
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-ui-lang", "data-color-theme"],
      });
    }
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("ra:workbench-sync", sync);
      observer?.disconnect();
    };
  }, []);

  return state;
}

export function bilingual(lang: UiLanguage, zh: string, en: string): string {
  return lang === "en" ? en : zh;
}

export function formatCstTime(
  value: string | number | null | undefined,
  lang: UiLanguage,
): string {
  if (value == null || value === "") return "—";
  const num = typeof value === "number" ? value : Number(value);
  const date =
    typeof value === "number" ||
    (Number.isFinite(num) && /^\d+(\.\d+)?$/.test(String(value).trim()))
      ? new Date(num > 0 && num < 1e11 ? num * 1000 : num)
      : new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(lang === "en" ? "en-GB" : "zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: lang === "en" ? "2-digit" : "numeric",
    day: lang === "en" ? "2-digit" : "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}
