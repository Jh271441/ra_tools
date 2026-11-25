import { bilingual, UiLanguage, withWorkbenchBase } from "../../bridge/useWorkbenchBridge";

export const CORE_LABELS = ["正确触发", "误触发", "无需协助"] as const;
export const MODEL_LABELS = ["正确触发", "误触发", "无需协助", "NONE"] as const;

export interface TagCatalogItem {
  key: string;
  label?: string;
  label_en?: string;
  hint?: string;
  hint_en?: string;
  section?: string;
  group?: string;
  inferred_output?: string;
  expected_output?: string;
  builtin?: boolean;
}

export interface EvidenceCatalogItem {
  key: string;
  label?: string;
  label_en?: string;
  hint?: string;
  hint_en?: string;
  builtin?: boolean;
}

export interface BaselineCatalogItem {
  id: string;
  label?: string;
  scope?: string;
  count?: number;
  default_selected?: boolean;
}

export interface DashboardConfigPayload {
  baselines?: BaselineCatalogItem[];
  review_tag_catalog?: TagCatalogItem[];
  missing_evidence_catalog?: EvidenceCatalogItem[];
  review_attachment_limits?: {
    max_count?: number;
    max_bytes_each?: number;
    max_bytes_total?: number;
    media_types?: string[];
  };
  case_labeling?: {
    active_baseline_ids?: string[];
  };
  prediction_batch_limit?: number;
}

export interface ReviewTagGroupDef {
  section: string;
  group: string;
  shortcut: string;
  zh: string;
  en: string;
  inferredOutput?: string;
}

export const REVIEW_TAG_GROUPS: ReviewTagGroupDef[] = [
  { section: "scene", group: "environment", shortcut: "Q", zh: "环境", en: "Environment" },
  { section: "scene", group: "self_intent", shortcut: "W", zh: "自车意图", en: "Ego intent" },
  {
    section: "interaction_decision",
    group: "false_trigger",
    shortcut: "A",
    zh: "误触发",
    en: "False trigger",
    inferredOutput: "误触发",
  },
  {
    section: "interaction_decision",
    group: "true_trigger",
    shortcut: "S",
    zh: "应该触发",
    en: "Should trigger",
  },
  {
    section: "egress",
    group: "ra",
    shortcut: "Z",
    zh: "正确触发",
    en: "Correct trigger",
    inferredOutput: "正确触发",
  },
  {
    section: "egress",
    group: "no_assist",
    shortcut: "X",
    zh: "无需协助",
    en: "No assistance",
    inferredOutput: "无需协助",
  },
];

export const EXPECTED_OUTPUT_OPTIONS = [
  { value: "", zh: "待补充", en: "Pending" },
  { value: "正确触发", zh: "正确触发", en: "Correct trigger" },
  { value: "误触发", zh: "误触发", en: "False trigger" },
  { value: "无需协助", zh: "无需协助", en: "No assistance needed" },
] as const;

export const MODEL_REVIEW_STATUS_OPTIONS = [
  { value: "needs_review", zh: "待复核", en: "Needs review" },
  { value: "completed", zh: "已完成", en: "Completed" },
] as const;

export function displayLabelText(value: string | null | undefined, lang: UiLanguage): string {
  const raw = String(value || "").trim();
  if (!raw) return "—";
  if (lang !== "en") return raw === "成功" ? "正确触发" : raw;
  const map: Record<string, string> = {
    正确触发: "Correct trigger",
    成功: "Correct trigger",
    误触发: "False trigger",
    无需协助: "No assistance",
    NONE: "NONE",
    失败: "Failed",
    未接起: "Unanswered",
    超出范围: "Out of scope",
  };
  return map[raw] || raw;
}

export function labelBadgeClass(value: string | null | undefined): string {
  const raw = String(value || "").trim();
  if (raw === "正确触发" || raw === "成功") return "label-badge label-true";
  if (raw === "误触发") return "label-badge label-false";
  if (raw === "无需协助") return "label-badge label-no-assist";
  if (raw === "NONE") return "label-badge label-none";
  return "label-badge label-empty";
}

export function normalizeAssetUrl(raw: string | null | undefined): string {
  const text = String(raw || "").trim();
  if (!text) return "";
  if (text.startsWith("blob:") || text.startsWith("data:")) return text;
  if (/^https?:\/\//i.test(text)) {
    try {
      const parsed = new URL(text);
      if (typeof window !== "undefined" && parsed.origin !== window.location.origin) {
        return "";
      }
      return parsed.pathname + parsed.search + parsed.hash;
    } catch {
      return "";
    }
  }
  if (!text.startsWith("/")) return "";
  return withWorkbenchBase(text);
}

export function safeExternalUrl(raw: string | null | undefined): string {
  const text = String(raw || "").trim();
  if (!text) return "";
  try {
    const parsed = new URL(text, typeof window !== "undefined" ? window.location.origin : "http://localhost");
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.href;
    }
  } catch {
    return "";
  }
  return "";
}

export function inferExpectedOutputFromTags(
  selectedTags: string[],
  catalog: TagCatalogItem[],
): { value: string; conflict: boolean; implied: string[] } {
  const byKey = new Map(catalog.map((item) => [item.key, item]));
  const impliedSet = new Set<string>();
  for (const key of selectedTags) {
    const item = byKey.get(key);
    if (!item) continue;
    const explicit = item.inferred_output || item.expected_output || "";
    if (explicit && (CORE_LABELS as readonly string[]).includes(explicit)) {
      impliedSet.add(explicit);
      continue;
    }
    if (item.group === "false_trigger") impliedSet.add("误触发");
    else if (item.group === "ra") impliedSet.add("正确触发");
    else if (item.group === "no_assist") impliedSet.add("无需协助");
  }
  const implied = Array.from(impliedSet);
  if (implied.length > 1) return { value: "", conflict: true, implied };
  return { value: implied[0] || "", conflict: false, implied };
}

export function parseIssueIdsInput(raw: string): { ids: string[]; invalid: string[] } {
  const tokens = String(raw || "")
    .split(/[\s,，、;；]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const ids: string[] = [];
  const invalid: string[] = [];
  const seen = new Set<string>();
  for (const tok of tokens) {
    if (/^[A-Za-z0-9_-]{3,128}$/.test(tok)) {
      const normalized = tok.toLowerCase();
      if (!seen.has(normalized)) {
        seen.add(normalized);
        ids.push(normalized);
      }
    } else {
      invalid.push(tok);
    }
  }
  return { ids, invalid };
}

export function showWorkbenchToast(message: string, isError = false): void {
  if (typeof window === "undefined") return;
  const win = window as unknown as { showToast?: (msg: string, err?: boolean) => void };
  if (typeof win.showToast === "function") {
    win.showToast(message, isError);
  }
}

export function navigateWorkbenchPage(
  page: string,
  options: Record<string, unknown> = {},
): void {
  if (typeof window === "undefined") return;
  const win = window as unknown as {
    showPage?: (p: string, opts?: Record<string, unknown>) => void;
    navigatePage?: (p: string) => void;
  };
  if (typeof win.showPage === "function") {
    win.showPage(page, { historyMode: "push", ...options });
  } else if (typeof win.navigatePage === "function") {
    win.navigatePage(page);
  }
}

export function decisionStateLabel(value: string | null | undefined, lang: UiLanguage): string {
  const key = String(value || "").trim();
  const map: Record<string, [string, string]> = {
    resolved: ["已确认", "Confirmed"],
    conflict: ["有分歧", "Disagreement"],
    stale: ["待复核", "Needs recheck"],
    pending: ["待补齐", "Incomplete"],
    none: ["待补齐", "Incomplete"],
  };
  const pair = map[key] || ["待补齐", "Incomplete"];
  return bilingual(lang, pair[0], pair[1]);
}

export function isTouchDevice(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(pointer: coarse)").matches;
}
