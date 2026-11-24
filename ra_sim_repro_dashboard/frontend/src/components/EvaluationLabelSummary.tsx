import { Fragment, useEffect, useRef, useState } from "react";
import { Check, Copy, ExternalLink, Filter } from "lucide-react";
import { useTranslation } from "react-i18next";
import { evaluationRequest } from "../api/evaluation";
import { evaluationParams } from "../lib/evaluationReads";
import { releaseName } from "../lib/releaseName";
import { cn } from "../lib/utils";
import { writeClipboard } from "../lib/writeClipboard";
import type { EvaluationContext } from "../types/evaluation";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Select } from "./ui/select";

const scopes = [
  "all_business",
  "nontraffic_business",
  "traffic_light",
  "EOL",
  "traffic_EOL",
] as const;
type Scope = (typeof scopes)[number];
type Counts = { scenario_count: number; published_issue_count: number };
type Outcome = Counts & {
  result: string;
  scenario_labels_all_of: string[];
  trail_issue_url: string | null;
};
type Summary =
  | { status: "missing" }
  | {
      status: "complete";
      workbench: {
        dataset: string;
        issue_total: number;
        published_issue_count: number;
        observed_at: string;
      };
      scopes: Record<
        Scope,
        Counts & { issue_count: number; outcomes: Outcome[] }
      >;
    };

const OUTCOME_META: Record<string, { dot: string; bar: string }> = {
  成功: { dot: "bg-emerald-500", bar: "bg-emerald-500/75" },
  正确触发: { dot: "bg-emerald-600", bar: "bg-emerald-600/75" },
  失败: { dot: "bg-amber-500", bar: "bg-amber-500/75" },
  误触发: { dot: "bg-rose-500", bar: "bg-rose-500/75" },
  无需协助: { dot: "bg-sky-500", bar: "bg-sky-500/75" },
};

const DEFAULT_META = {
  dot: "bg-muted-foreground/50",
  bar: "bg-muted-foreground/40",
};

function formatShare(count: number, total: number) {
  if (total <= 0) return "—";
  const pct = (count / total) * 100;
  if (pct >= 99.95) return "100%";
  if (pct <= 0) return "0%";
  return `${pct.toFixed(1)}%`;
}

function renderTokenizedText(text: string) {
  const parts = text.split("_");
  return parts.map((part, index) => (
    <Fragment key={index}>
      {index > 0 && (
        <>
          <wbr />_{part}
        </>
      )}
      {index === 0 && part}
    </Fragment>
  ));
}

function CopyableLabelPill({
  value,
  sharedPrefix,
  copied,
  onCopy,
}: {
  value: string;
  sharedPrefix?: string;
  copied: boolean;
  onCopy: (label: string) => void;
}) {
  const { t } = useTranslation();
  const hasSuffix = Boolean(
    sharedPrefix &&
      value !== sharedPrefix &&
      value.startsWith(`${sharedPrefix}_`),
  );
  const suffix = hasSuffix ? value.slice(sharedPrefix!.length) : "";

  return (
    <div className="flex min-w-0 items-center gap-1">
      <code className="min-w-0 max-w-full select-text break-words [overflow-wrap:anywhere] rounded-md border border-border/60 bg-muted/45 px-2.5 py-0.5 font-mono text-xs leading-5 dark:bg-white/[0.03] md:whitespace-nowrap md:break-normal md:[overflow-wrap:normal] md:[&_wbr]:hidden">
        {hasSuffix ? (
          <>
            <span className="text-muted-foreground">
              {renderTokenizedText(sharedPrefix!)}
            </span>
            <wbr />
            <span className="font-semibold text-foreground">
              {renderTokenizedText(suffix)}
            </span>
          </>
        ) : (
          <span className="font-medium text-foreground">
            {renderTokenizedText(value)}
          </span>
        )}
      </code>
      <button
        type="button"
        onClick={() => onCopy(value)}
        title={t(
          copied
            ? "evaluation.label_groups_copied"
            : "evaluation.label_groups_copy",
        )}
        aria-label={t("evaluation.summary_copy", { label: value })}
        className="group inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:min-w-11"
      >
        {copied ? (
          <Check
            size={14}
            className="text-emerald-600 dark:text-emerald-400"
            aria-hidden="true"
          />
        ) : (
          <Copy size={14} aria-hidden="true" />
        )}
      </button>
    </div>
  );
}

export function EvaluationLabelSummary({
  ctx,
  revision,
  loading,
  activeResult,
  onSelectResult,
}: {
  ctx: EvaluationContext;
  revision?: string;
  loading: boolean;
  activeResult?: string;
  onSelectResult?: (result: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const [scope, setScope] = useState<Scope>("all_business");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [copiedLabel, setCopiedLabel] = useState("");
  const [copyError, setCopyError] = useState(false);
  const copyTimer = useRef<number | null>(null);

  const params = evaluationParams(ctx);
  if (revision) params.set("revision", revision);
  const query = params.toString();

  useEffect(() => {
    if (!revision) return;
    let active = true;
    setFailed(false);
    void evaluationRequest<Summary>(`/scenario-label-summary?${query}`)
      .then((value) => {
        if (active) setSummary(value);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [query, revision, attempt]);

  useEffect(
    () => () => {
      if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
    },
    [],
  );

  async function handleCopy(label: string) {
    try {
      await writeClipboard(label);
      setCopyError(false);
      setCopiedLabel(label);
      if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
      copyTimer.current = window.setTimeout(() => setCopiedLabel(""), 1800);
    } catch {
      setCopyError(true);
    }
  }

  const format = (n: number) => n.toLocaleString(i18n.language);
  const title = t("evaluation.summary_title", {
    release: releaseName(ctx.release),
  });
  const ready = summary?.status === "complete" ? summary : null;
  const selected = ready?.scopes[scope];

  // Deduplicate base labels that appear identically on every outcome row.
  const outcomes = selected?.outcomes ?? [];
  const sharedLabels =
    outcomes.length > 1
      ? outcomes[0].scenario_labels_all_of.filter((label) =>
          outcomes.every((row) => row.scenario_labels_all_of.includes(label)),
        )
      : [];
  const sharedSet = new Set(sharedLabels);
  const sharedPrefix =
    sharedLabels[sharedLabels.length - 1] || sharedLabels[0] || "";
  const totalScenes = selected?.scenario_count ?? 0;

  return (
    <Card data-evaluation-labels={ctx.release} className="overflow-hidden">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 border-b border-border/70 px-4 py-3 md:px-5">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <CardTitle>{title}</CardTitle>
          {ready && (
            <span className="text-xs text-muted-foreground">
              Workbench · {ready.workbench.dataset} ·{" "}
              {t("evaluation.summary_wb_counts", {
                total: format(ready.workbench.issue_total),
                published: format(ready.workbench.published_issue_count),
              })}
            </span>
          )}
        </div>
        {ready && selected && (
          <div className="flex flex-wrap items-center gap-2">
            <time
              className="text-xs text-muted-foreground"
              dateTime={ready.workbench.observed_at}
            >
              {t("evaluation.summary_observed", {
                time: new Date(ready.workbench.observed_at).toLocaleString(
                  i18n.language,
                  {
                    timeZone: "Asia/Shanghai",
                    hour12: false,
                  },
                ),
              })}
            </time>
            <Badge variant="secondary" className="font-medium tabular-nums">
              {t("evaluation.summary_group_badge", {
                groups: format(outcomes.length),
                scenes: format(totalScenes),
              })}
            </Badge>
          </div>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {copiedLabel && (
          <span role="status" className="sr-only">
            {t("evaluation.label_groups_copied_status", { label: copiedLabel })}
          </span>
        )}
        {copyError && (
          <p
            role="status"
            className="px-4 pt-2 text-xs text-muted-foreground md:px-5"
          >
            {t("simParameters.manualCopy")}
          </p>
        )}
        {failed ? (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-center gap-3 px-5 py-6 text-center text-sm"
          >
            <span>{t("evaluation.scenario_labels_failed")}</span>
            <Button
              variant="outline"
              className="min-h-11"
              onClick={() => setAttempt((n) => n + 1)}
            >
              {t("autoTriage.retry")}
            </Button>
          </div>
        ) : !ready || !selected ? (
          <p
            role="status"
            className="px-5 py-6 text-center text-sm text-muted-foreground"
          >
            {t(
              loading || (revision && summary === null)
                ? "loading"
                : "evaluation.label_groups_pending",
            )}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border/60 bg-muted/20 px-4 py-2.5 text-sm md:px-5">
              <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
                <Select
                  label={t("evaluation.summary_scope")}
                  value={scope}
                  options={scopes.map((value) => ({
                    value,
                    label: t(`evaluation.summary_scope_${value}`),
                  }))}
                  onChange={(value) => setScope(value as Scope)}
                />
                <span
                  role="status"
                  className="text-xs text-muted-foreground tabular-nums"
                >
                  {t("evaluation.summary_counts", {
                    issues: format(selected.issue_count),
                    scenes: format(selected.scenario_count),
                    published: format(selected.published_issue_count),
                  })}
                </span>
              </div>
              {sharedLabels.length > 0 && (
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                  <span className="text-xs font-medium text-muted-foreground">
                    {t("evaluation.summary_base_label")}
                  </span>
                  {sharedLabels.map((baseLabel) => (
                    <CopyableLabelPill
                      key={baseLabel}
                      value={baseLabel}
                      copied={copiedLabel === baseLabel}
                      onCopy={(val) => void handleCopy(val)}
                    />
                  ))}
                </div>
              )}
            </div>
            <div className="min-w-0 overflow-x-auto">
              <table className="block w-full text-left text-sm md:table">
                <caption className="sr-only">{title}</caption>
                <thead className="sr-only md:not-sr-only md:table-header-group md:bg-muted/45 dark:md:bg-white/[0.025]">
                  <tr className="md:border-b md:border-border/70">
                    <th
                      scope="col"
                      className="md:h-9 md:whitespace-nowrap md:px-4 md:text-xs md:font-medium md:text-muted-foreground lg:px-5"
                    >
                      {t("evaluation.summary_result")}
                    </th>
                    <th
                      scope="col"
                      className="md:h-9 md:px-3 md:text-xs md:font-medium md:text-muted-foreground"
                    >
                      {t("evaluation.label_groups_name")}
                    </th>
                    <th
                      scope="col"
                      className="md:h-9 md:whitespace-nowrap md:px-3 md:text-right md:text-xs md:font-medium md:text-muted-foreground"
                    >
                      {t("evaluation.label_groups_count")}
                    </th>
                    <th
                      scope="col"
                      className="md:h-9 md:whitespace-nowrap md:px-3 md:text-right md:text-xs md:font-medium md:text-muted-foreground"
                    >
                      {t("evaluation.summary_published")}
                    </th>
                    <th
                      scope="col"
                      className="md:h-9 md:whitespace-nowrap md:pl-2 md:pr-4 md:text-right md:text-xs md:font-medium md:text-muted-foreground lg:pr-5"
                    >
                      {onSelectResult
                        ? t("evaluation.label_groups_actions")
                        : "Trail"}
                    </th>
                  </tr>
                </thead>
                <tbody className="block md:table-row-group">
                  {outcomes.map((row, index) => {
                    const meta = OUTCOME_META[row.result] ?? DEFAULT_META;
                    const specificLabels = row.scenario_labels_all_of.filter(
                      (label) => !sharedSet.has(label),
                    );
                    const displayLabels =
                      specificLabels.length > 0
                        ? specificLabels
                        : row.scenario_labels_all_of;
                    const ratioPct =
                      totalScenes > 0
                        ? Math.min(
                            100,
                            Math.max(
                              0,
                              (row.scenario_count / totalScenes) * 100,
                            ),
                          )
                        : 0;
                    const shareText = formatShare(
                      row.scenario_count,
                      totalScenes,
                    );
                    const isFiltered = Boolean(
                      activeResult && activeResult === row.result,
                    );

                    return (
                      <tr
                        key={row.result}
                        className={cn(
                          "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 px-4 py-2.5 transition-colors md:table-row md:px-0 md:py-0",
                          index > 0 && "border-t border-border/50",
                          isFiltered
                            ? "bg-primary/[0.06] hover:bg-primary/10"
                            : "hover:bg-accent/35",
                        )}
                      >
                        <th
                          scope="row"
                          className="col-start-1 row-start-1 min-w-0 text-left font-normal md:table-cell md:whitespace-nowrap md:px-4 md:py-2 md:align-middle lg:px-5"
                        >
                          <div className="flex min-w-0 items-center gap-2.5">
                            <span
                              className={cn(
                                "h-2 w-2 shrink-0 rounded-full",
                                meta.dot,
                              )}
                              aria-hidden="true"
                            />
                            <span className="min-w-0 text-[13px] font-medium leading-snug text-foreground">
                              {t(`autoTriage.result_${row.result}`, {
                                defaultValue: row.result,
                              })}
                            </span>
                          </div>
                        </th>
                        <td className="col-span-2 row-start-2 min-w-0 md:table-cell md:px-3 md:py-1.5 md:align-middle">
                          <div className="flex flex-col gap-1">
                            {displayLabels.map((label) => (
                              <CopyableLabelPill
                                key={label}
                                value={label}
                                sharedPrefix={sharedPrefix}
                                copied={copiedLabel === label}
                                onCopy={(val) => void handleCopy(val)}
                              />
                            ))}
                          </div>
                        </td>
                        <td className="col-start-2 row-start-1 text-right md:table-cell md:whitespace-nowrap md:px-3 md:py-2 md:text-right md:align-middle">
                          <div className="inline-flex items-center justify-end gap-2">
                            <div
                              className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-muted xl:block 2xl:w-20"
                              aria-hidden="true"
                            >
                              <div
                                className={cn("h-full rounded-full", meta.bar)}
                                style={{ width: `${ratioPct}%` }}
                              />
                            </div>
                            <span className="font-mono text-[13px] font-semibold tabular-nums text-foreground">
                              {format(row.scenario_count)}
                            </span>
                            <span className="w-10 text-right font-mono text-[11px] tabular-nums text-muted-foreground">
                              {shareText}
                            </span>
                          </div>
                        </td>
                        <td className="col-start-1 row-start-3 md:table-cell md:whitespace-nowrap md:px-3 md:py-2 md:text-right md:align-middle">
                          <span className="mr-1.5 text-xs text-muted-foreground md:hidden">
                            {t("evaluation.summary_published")}
                          </span>
                          <span className="font-mono text-[13px] tabular-nums text-muted-foreground">
                            {format(row.published_issue_count)}
                          </span>
                        </td>
                        <td className="col-start-2 row-start-3 md:table-cell md:whitespace-nowrap md:py-1.5 md:pl-2 md:pr-4 md:text-right md:align-middle lg:pr-5">
                          <div className="flex shrink-0 items-center justify-end gap-0.5">
                            {onSelectResult && (
                              <button
                                type="button"
                                aria-pressed={isFiltered}
                                aria-label={t(
                                  isFiltered
                                    ? "evaluation.summary_clear_filter_aria"
                                    : "evaluation.summary_filter_aria",
                                  {
                                    result: t(
                                      `autoTriage.result_${row.result}`,
                                      {
                                        defaultValue: row.result,
                                      },
                                    ),
                                  },
                                )}
                                onClick={() => onSelectResult(row.result)}
                                className="group inline-flex h-7 items-center justify-center rounded-md px-0.5 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [@media(pointer:coarse)]:min-h-11"
                              >
                                <span
                                  className={cn(
                                    "inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium transition-colors",
                                    isFiltered
                                      ? "bg-primary text-primary-foreground shadow-sm shadow-primary/20"
                                      : "text-muted-foreground group-hover:bg-accent group-hover:text-accent-foreground",
                                  )}
                                >
                                  <Filter size={12} aria-hidden="true" />
                                  <span>
                                    {t(
                                      isFiltered
                                        ? "evaluation.label_groups_filtered"
                                        : "evaluation.label_groups_filter",
                                    )}
                                  </span>
                                </span>
                              </button>
                            )}
                            {row.trail_issue_url ? (
                              <a
                                className="group inline-flex h-7 items-center justify-center rounded-md px-0.5 text-xs font-medium text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:min-w-11"
                                href={row.trail_issue_url}
                                target="_blank"
                                rel="noreferrer"
                                aria-label={t("evaluation.summary_open", {
                                  result: t(`autoTriage.result_${row.result}`, {
                                    defaultValue: row.result,
                                  }),
                                })}
                              >
                                <span className="inline-flex h-7 items-center gap-1 rounded-md px-2 transition-colors group-hover:bg-accent group-hover:underline">
                                  <span>Trail</span>
                                  <ExternalLink size={12} aria-hidden="true" />
                                </span>
                              </a>
                            ) : (
                              <span
                                className="px-2 text-xs text-muted-foreground"
                                aria-label={t("evaluation.summary_empty")}
                              >
                                —
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
