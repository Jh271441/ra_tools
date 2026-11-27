import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import {
  bilingual,
  getWorkbenchBasePath,
  UiLanguage,
  withWorkbenchBase,
} from "../bridge/useWorkbenchBridge";
import type { MultiSelectOption } from "../components/ui/MultiSelect";
import { TRIAGE_LABELS } from "../components/charts/AnalysisCharts";

export const ISSUE_QUERY_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{2,127}$/;
const ISSUE_QUERY_SPLIT_RE = /[\s,，、;；]+/;

export const GT_RELATION_VALUES = [
  "matches_gt",
  "differs_from_gt",
  "fills_missing_gt",
] as const;

export const ANALYSIS_COMPARISON_STATUSES = [
  "all",
  "mismatch",
  "match",
  "no_gt",
  "none",
] as const;

export interface ReviewTagCatalogItem {
  key: string;
  label: string;
  section?: string;
  group?: string;
  hint?: string;
  visible?: boolean;
  deleted?: boolean;
}

export interface MissingEvidenceCatalogItem {
  key: string;
  label: string;
  hint?: string;
  deleted?: boolean;
}

export interface BaselineCatalogItem {
  id?: string;
  scope?: string;
  label?: string;
  count?: number;
}

export interface DashboardConfigPayload {
  review_tag_catalog?: ReviewTagCatalogItem[];
  missing_evidence_catalog?: MissingEvidenceCatalogItem[];
  baselines?: BaselineCatalogItem[];
  default_failure_only?: boolean;
}

export function readLegacyConfig(): DashboardConfigPayload | null {
  if (typeof window === "undefined") return null;
  const win = window as unknown as {
    __RA_TRIAGE_STATE__?: { config?: DashboardConfigPayload; baselineCatalog?: BaselineCatalogItem[] };
    state?: { config?: DashboardConfigPayload; baselineCatalog?: BaselineCatalogItem[] };
  };
  return win.__RA_TRIAGE_STATE__?.config || win.state?.config || null;
}

export function readLegacySelectedRunId(): string {
  if (typeof window === "undefined") return "";
  const win = window as unknown as {
    __RA_TRIAGE_STATE__?: { selectedRunId?: string };
    state?: { selectedRunId?: string };
  };
  return String(win.__RA_TRIAGE_STATE__?.selectedRunId || win.state?.selectedRunId || "");
}

export function syncLegacySelectedRunId(runId: string, comparisonStatus?: string) {
  if (typeof window === "undefined") return;
  const win = window as unknown as {
    __RA_TRIAGE_STATE__?: {
      selectedRunId?: string;
      failureOnly?: boolean;
      reviewQueueStale?: boolean;
      reviewAnalysis?: { comparisonStatus?: string };
    };
    state?: {
      selectedRunId?: string;
      failureOnly?: boolean;
      reviewQueueStale?: boolean;
      reviewAnalysis?: { comparisonStatus?: string };
    };
    renderActiveRun?: () => void;
    loadOverview?: () => Promise<unknown>;
  };
  const target = win.__RA_TRIAGE_STATE__ || win.state;
  if (target) {
    if (target.selectedRunId !== runId) {
      target.reviewQueueStale = true;
    }
    target.selectedRunId = runId;
    if (comparisonStatus !== undefined) {
      if (target.reviewAnalysis) {
        target.reviewAnalysis.comparisonStatus = comparisonStatus;
      }
      target.failureOnly = Boolean(runId && comparisonStatus === "mismatch");
    }
  }
  const reviewRunSelect = document.getElementById("modelRunFilter") as HTMLSelectElement | null;
  if (reviewRunSelect && reviewRunSelect.value !== runId) {
    reviewRunSelect.value = runId;
  }
  try {
    win.renderActiveRun?.();
  } catch {
    /* ignore */
  }
}

export function showWorkbenchToast(message: string, isError = false) {
  if (typeof window === "undefined") return;
  const win = window as unknown as { showToast?: (msg: string, err?: boolean) => void };
  if (typeof win.showToast === "function") {
    win.showToast(message, isError);
  }
}

export function parseFilterList(value: string | readonly string[] | null | undefined): string[] {
  if (Array.isArray(value)) {
    return Array.from(
      new Set(value.map((item) => String(item || "").trim()).filter(Boolean)),
    );
  }
  return Array.from(
    new Set(
      String(value || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

export function joinFilterList(values: readonly string[] | null | undefined): string {
  return parseFilterList(values).join(",");
}

export function parseIssueIdsInput(raw: string): { ids: string[]; invalid: string[] } {
  const text = String(raw ?? "")
    .replace(/[，、；;]/g, ",")
    .replace(/\r?\n/g, ",");
  const ids: string[] = [];
  const invalid: string[] = [];
  const seen = new Set<string>();
  for (const part of text.split(ISSUE_QUERY_SPLIT_RE)) {
    const token = String(part || "")
      .trim()
      .replace(/^[([\]{<"']+|[)\]}>"'.,，、;；]+$/g, "");
    if (!token) continue;
    const urlMatch = token.match(/(?:\/issue\/|[?&]issue=)([A-Za-z0-9][A-Za-z0-9_-]{2,127})/i);
    const issueId = urlMatch ? urlMatch[1] : token;
    if (!ISSUE_QUERY_ID_RE.test(issueId)) {
      invalid.push(token);
      continue;
    }
    if (!seen.has(issueId)) {
      seen.add(issueId);
      ids.push(issueId);
    }
  }
  return { ids, invalid };
}

export function normalizedGtRelationFilters(
  values: string | readonly string[] | null | undefined,
): string[] {
  return parseFilterList(values).filter((value) =>
    (GT_RELATION_VALUES as readonly string[]).includes(value),
  );
}

export function normalizedLabelingStatusFilters(
  value: string | readonly string[] | null | undefined,
  { submittedOnly = false }: { submittedOnly?: boolean } = {},
): string[] {
  const expanded = parseFilterList(value).flatMap((status) =>
    status === "pending"
      ? submittedOnly
        ? ["incomplete"]
        : ["unannotated", "incomplete"]
      : [status],
  );
  return Array.from(new Set(expanded)).filter((status) =>
    ["unannotated", "incomplete", "resolved", "conflict"].includes(status),
  );
}

export function labelGtFilterSelection(
  states: readonly string[] = [],
  relations: readonly string[] = [],
): string[] {
  return [
    ...parseFilterList(states),
    ...normalizedGtRelationFilters(relations).map((value) => `gt:${value}`),
  ];
}

export function splitLabelGtFilterSelection(values: readonly string[]): {
  labelStates: string[];
  gtRelations: string[];
} {
  const selected = parseFilterList(values);
  return {
    labelStates: selected.filter((value) => !value.startsWith("gt:")),
    gtRelations: normalizedGtRelationFilters(
      selected.filter((value) => value.startsWith("gt:")).map((value) => value.slice(3)),
    ),
  };
}

export function buildLabelGtFilterOptions({
  lang,
  labeling = false,
  selected = [],
}: {
  lang: UiLanguage;
  labeling?: boolean;
  selected?: readonly string[];
}): MultiSelectOption[] {
  const gtGroup = bilingual(lang, "与 GT 的关系", "Relation to GT");
  const stateGroup = bilingual(lang, "标注状态", "Label state");
  const gtItems: MultiSelectOption[] = [
    { value: "gt:matches_gt", label: bilingual(lang, "与 GT 一致", "Matches GT"), group: gtGroup },
    {
      value: "gt:differs_from_gt",
      label: bilingual(lang, "与 GT 不一致", "Differs from GT"),
      group: gtGroup,
    },
    {
      value: "gt:fills_missing_gt",
      label: bilingual(lang, "GT 缺失", "GT missing"),
      group: gtGroup,
    },
  ];
  const stateItems: MultiSelectOption[] = [
    {
      value: labeling ? "unannotated" : "none",
      label: bilingual(lang, "未标注", "Not labeled"),
      group: stateGroup,
    },
    {
      value: labeling ? "incomplete" : "pending",
      label: bilingual(lang, "待形成结论", "Pending"),
      group: stateGroup,
    },
    { value: "resolved", label: bilingual(lang, "已形成结论", "Resolved"), group: stateGroup },
    {
      value: "conflict",
      label: bilingual(lang, "需处理分歧", "Needs resolution"),
      group: stateGroup,
    },
  ];
  if (!labeling) {
    stateItems.push({value:"exclusion_pending", label:bilingual(lang, "排除待确定", "Exclusion pending"), group:stateGroup});
    const legacyExtras: Array<[string, string, string]> = [
      ["stale", "裁决需确认", "Decision needs review"],
      ["matches_gt", "与 GT 一致", "Matches GT"],
      ["needs_gt_review", "GT 待复核", "GT needs review"],
      ["unknown", "GT 关系未知", "GT relation unknown"],
    ];
    for (const [value, zh, en] of legacyExtras) {
      if (selected.includes(value)) {
        stateItems.push({ value, label: bilingual(lang, zh, en), group: stateGroup });
      }
    }
  }
  return [...gtItems, ...stateItems];
}

export function parseComparisonStatuses(
  value: string | readonly string[] | null | undefined,
): string[] {
  const raw = Array.isArray(value)
    ? value
    : String(value || "")
        .split(",")
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean);
  const valid = ["mismatch", "match", "no_gt", "none"];
  return Array.from(new Set(raw.filter((item) => valid.includes(item))));
}

export function comparisonStatusParam(
  value: string | readonly string[] | null | undefined,
): string {
  const statuses = parseComparisonStatuses(value);
  if (!statuses.length || statuses.length >= 4) return "all";
  return statuses.join(",");
}

export function comparisonStatusMeta(status: string, lang: UiLanguage): {
  label: string;
  description: string;
} {
  switch (String(status || "all").toLowerCase()) {
    case "mismatch":
      return {
        label: "MISMATCH",
        description: bilingual(
          lang,
          "模型预测与 GT 不一致",
          "Model prediction disagrees with GT",
        ),
      };
    case "match":
      return {
        label: "MATCH",
        description: bilingual(lang, "模型预测与 GT 一致", "Model prediction matches GT"),
      };
    case "no_gt":
      return {
        label: "NO GT",
        description: bilingual(
          lang,
          "模型有预测结果，但当前数据集无 GT",
          "Model produced a prediction but GT is empty",
        ),
      };
    case "none":
      return {
        label: "NONE",
        description: bilingual(
          lang,
          "当前 Run 未覆盖此 Issue 或未输出预测",
          "No model prediction for this Issue in the selected Run",
        ),
      };
    default:
      return {
        label: bilingual(lang, "全部", "All"),
        description: bilingual(lang, "全部对比结果", "All comparison outcomes"),
      };
  }
}

export function evidenceLabel(
  key: string,
  config: DashboardConfigPayload | null | undefined,
): string {
  const value = String(key || "");
  const catalogItem = config?.missing_evidence_catalog?.find(
    (item) => String(item.key) === value,
  );
  if (catalogItem?.label) return catalogItem.label;
  if (value.startsWith("custom:")) {
    const legacyLabel = value.slice("custom:".length);
    return legacyLabel && !/^[a-f0-9]{24,64}$/i.test(legacyLabel)
      ? legacyLabel
      : "自定义缺失信息";
  }
  return value;
}

export function reviewTagCatalogItem(
  key: string,
  config: DashboardConfigPayload | null | undefined,
): ReviewTagCatalogItem | undefined {
  return (config?.review_tag_catalog || []).find(
    (item) => String(item.key) === String(key),
  );
}

export function tagLabel(
  key: string,
  config: DashboardConfigPayload | null | undefined,
): string {
  const value = String(key || "");
  const catalogItem = reviewTagCatalogItem(value, config);
  if (catalogItem?.label) return catalogItem.label;
  if (value === "straight_road") return "直行";
  if (value.startsWith("custom:")) return value.slice("custom:".length) || value;
  return value;
}

export function baselineLabelForScope(
  scope: string | null | undefined,
  config: DashboardConfigPayload | null | undefined,
  lang: UiLanguage,
): string {
  const normalized = String(scope || "").trim();
  const win = typeof window !== "undefined"
    ? (window as unknown as { state?: { baselineCatalog?: BaselineCatalogItem[] } })
    : undefined;
  const catalog = win?.state?.baselineCatalog?.length
    ? win.state.baselineCatalog
    : config?.baselines || [];
  const item = catalog.find((entry) => String(entry?.scope || "") === normalized);
  return item?.label || item?.id || bilingual(lang, "当前数据集", "Selected dataset");
}

export function annotationExpectedOutput(annotation: {
  expected_output?: string | null;
  label?: string | null;
} | null | undefined): string {
  if (annotation && Object.prototype.hasOwnProperty.call(annotation, "expected_output")) {
    return String(annotation.expected_output || "").trim();
  }
  return String(annotation?.label || "").trim();
}

export function safeExternalUrl(url: string | null | undefined): string {
  try {
    const parsed = new URL(String(url || ""));
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

export function safeSameOriginReviewUrl(url: string | null | undefined): string {
  if (typeof window === "undefined") return "";
  try {
    const parsed = new URL(String(url || ""), window.location.origin);
    const base = getWorkbenchBasePath();
    const pathname =
      base && parsed.pathname.startsWith(base)
        ? parsed.pathname.slice(base.length) || "/"
        : parsed.pathname;
    if (parsed.origin !== window.location.origin || pathname !== "/review") return "";
    return `${withWorkbenchBase(pathname)}${parsed.search}`;
  } catch {
    return "";
  }
}

export function isTriageLabel(value: string | null | undefined): boolean {
  return (TRIAGE_LABELS as readonly string[]).includes(String(value || "").trim());
}

/**
 * Accessible popover mirroring classic `.model-review-run-help.ui-info`.
 * Supports click-pin, hover open, Escape & outside-click close, and viewport clamping.
 */
export const UiInfoPopover: React.FC<{
  ariaLabel: string;
  children: React.ReactNode;
  id?: string;
}> = ({ ariaLabel, children, id }) => {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const rootRef = useRef<HTMLSpanElement | null>(null);
  const btnRef = useRef<HTMLButtonElement | null>(null);
  const tipRef = useRef<HTMLSpanElement | null>(null);
  const reactId = useId();
  const panelId = id ? `${id}-panel` : `ui-info-panel-${reactId}`;

  const positionTooltip = useCallback(() => {
    const anchor = btnRef.current;
    if (!anchor || typeof window === "undefined") return;
    const rect = anchor.getBoundingClientRect();
    const measuredW = tipRef.current?.offsetWidth || 0;
    const width = measuredW > 0 ? Math.min(measuredW, window.innerWidth - 24) : Math.min(360, window.innerWidth - 24);
    const estHeight = tipRef.current?.offsetHeight || 120;
    let left = rect.left;
    if (left + width > window.innerWidth - 12) {
      left = Math.max(12, window.innerWidth - width - 12);
    }
    let top = rect.bottom + 8;
    if (top + estHeight > window.innerHeight - 12 && rect.top - estHeight - 8 > 12) {
      top = rect.top - estHeight - 8;
    }
    setPos({ left: Math.max(12, left), top: Math.max(12, top) });
  }, []);

  useLayoutEffect(() => {
    if (open) positionTooltip();
  }, [open, positionTooltip]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent | TouchEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        btnRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown, { passive: true });
    document.addEventListener("keydown", onKeyDown, true);
    window.addEventListener("resize", positionTooltip);
    window.addEventListener("scroll", positionTooltip, true);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
      document.removeEventListener("keydown", onKeyDown, true);
      window.removeEventListener("resize", positionTooltip);
      window.removeEventListener("scroll", positionTooltip, true);
    };
  }, [open, positionTooltip]);

  return (
    <span
      ref={rootRef}
      id={id}
      className={`model-review-run-help ui-info${open ? " is-open" : ""}`}
      data-ui-info=""
      onMouseEnter={positionTooltip}
    >
      <button
        ref={btnRef}
        className="ui-info-button"
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={ariaLabel}
        title={ariaLabel}
        onFocus={positionTooltip}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          positionTooltip();
          setOpen((prev) => !prev);
        }}
      >
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.4" />
          <path
            d="M10 9.1v4.6"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
          <circle cx="10" cy="6.3" r=".9" fill="currentColor" />
        </svg>
      </button>
      <span
        ref={tipRef}
        className="model-review-run-tooltip ui-info-tooltip"
        id={panelId}
        role="dialog"
        aria-label={ariaLabel}
        style={pos ? { left: `${pos.left}px`, top: `${pos.top}px` } : undefined}
      >
        {children}
      </span>
    </span>
  );
};
