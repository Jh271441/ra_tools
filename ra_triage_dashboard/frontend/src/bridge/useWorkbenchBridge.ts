import { useEffect, useState } from "react";

export type UiLanguage = "zh" | "en";
export type ColorTheme = "dark" | "light";

export interface WorkbenchBridgeState {
  lang: UiLanguage;
  theme: ColorTheme;
  activePage: string;
  session: {
    authenticated: boolean;
    verified: boolean;
    username: string;
    access_role: string;
    is_admin: boolean;
    can_write: boolean;
  } | null;
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
  if (typeof document === "undefined") return "review";
  const visible = document.querySelector<HTMLElement>(".app-page[data-page]:not(.hidden)");
  return visible?.dataset.page || "review";
}

function readLegacySession(): WorkbenchBridgeState["session"] {
  if (typeof window === "undefined") return null;
  const legacyState = (
    window as unknown as { state?: { session?: WorkbenchBridgeState["session"] } }
  ).state;
  return legacyState?.session || null;
}

export function useWorkbenchBridge(): WorkbenchBridgeState {
  const [bridge, setBridge] = useState<WorkbenchBridgeState>(() => ({
    lang: readLang(),
    theme: readTheme(),
    activePage: readActivePage(),
    session: readLegacySession(),
  }));

  useEffect(() => {
    const sync = () => {
      setBridge((prev) => {
        const nextLang = readLang();
        const nextTheme = readTheme();
        const nextPage = readActivePage();
        const nextSession = readLegacySession();
        if (
          prev.lang === nextLang &&
          prev.theme === nextTheme &&
          prev.activePage === nextPage &&
          prev.session === nextSession
        ) {
          return prev;
        }
        return { lang: nextLang, theme: nextTheme, activePage: nextPage, session: nextSession };
      });
    };

    const htmlObserver = new MutationObserver(sync);
    htmlObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-ui-lang", "data-color-theme"],
    });

    const pageNodes = Array.from(document.querySelectorAll<HTMLElement>(".app-page[data-page]"));
    const pageObserver = new MutationObserver(sync);
    for (const node of pageNodes) {
      pageObserver.observe(node, { attributes: true, attributeFilter: ["class"] });
    }

    window.addEventListener("popstate", sync);
    window.addEventListener("ra:workbench-sync", sync);

    return () => {
      htmlObserver.disconnect();
      pageObserver.disconnect();
      window.removeEventListener("popstate", sync);
      window.removeEventListener("ra:workbench-sync", sync);
    };
  }, []);

  return bridge;
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
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}
