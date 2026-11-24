import { writeClipboard } from "../lib/writeClipboard";
import { Fragment, useEffect, useRef, useState } from "react";
import { Check, Copy, ExternalLink, Filter } from "lucide-react";
import { useTranslation } from "react-i18next";
import { request } from "../api/workflow";
import { releaseName } from "../lib/releaseName";
import { cn } from "../lib/utils";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

type LabelGroupRow = {
  group: string;
  label: string;
  count: number;
  trail_url: string;
};

type Summary = {
  total_scenarios: number;
  rows: LabelGroupRow[];
};

type Props = {
  release: string;
  activeLabel?: string;
  onSelectLabel?: (label: string) => void;
};

const GROUP_META: Record<
  string,
  { tier: "scope" | "class" | "trigger"; dot: string; bar: string }
> = {
  full: { tier: "scope", dot: "bg-primary", bar: "bg-primary/70" },
  release: { tier: "scope", dot: "bg-primary/65", bar: "bg-primary/55" },
  positive_auto: {
    tier: "class",
    dot: "bg-emerald-500",
    bar: "bg-emerald-500/75",
  },
  negative_auto: { tier: "class", dot: "bg-rose-500", bar: "bg-rose-500/75" },
  positive_manual: {
    tier: "class",
    dot: "bg-amber-500",
    bar: "bg-amber-500/75",
  },
  AutoTrigger: {
    tier: "trigger",
    dot: "bg-slate-400 dark:bg-slate-500",
    bar: "bg-slate-400/75 dark:bg-slate-500/75",
  },
  ManualTrigger: {
    tier: "trigger",
    dot: "bg-slate-400 dark:bg-slate-500",
    bar: "bg-slate-400/75 dark:bg-slate-500/75",
  },
};

const DEFAULT_META = {
  tier: "scope" as const,
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

export function ReleaseLabelGroups({
  release,
  activeLabel,
  onSelectLabel,
}: Props) {
  const { t, i18n } = useTranslation();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, retry] = useState(0);
  const [copiedLabel, setCopiedLabel] = useState("");
  const copyTimer = useRef<number | null>(null);

  useEffect(() => {
    let active = true;
    setFailed(false);
    setSummary(null);
    void request<Summary>(
      `/scenario-label-groups?release=${encodeURIComponent(release)}`,
    )
      .then((result) => {
        if (active) setSummary(result);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [release, attempt]);

  useEffect(
    () => () => {
      if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
    },
    [],
  );

  async function handleCopy(label: string) {
    try {
      await writeClipboard(label);
      setCopiedLabel(label);
      if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
      copyTimer.current = window.setTimeout(() => setCopiedLabel(""), 1800);
    } catch {
      // Clipboard access can be denied in restricted embeds; keep text selection usable.
    }
  }

  const rows = summary?.rows ?? [];
  const fullRow = rows.find((row) => row.group === "full");
  const sharedPrefix = fullRow?.label || "";
  const totalScenes = summary?.total_scenarios ?? 0;

  return (
    <Card data-release-labels={release} className="overflow-hidden">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 border-b border-border/70 px-4 py-3 md:px-5">
        <CardTitle>
          {t("evaluation.label_groups_title", {
            release: releaseName(release),
          })}
        </CardTitle>
        {rows.length > 0 && (
          <Badge variant="secondary" className="font-medium tabular-nums">
            {t("evaluation.label_groups_summary", {
              groups: rows.length.toLocaleString(i18n.language),
              scenes: totalScenes.toLocaleString(i18n.language),
            })}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {copiedLabel && (
          <span role="status" className="sr-only">
            {t("evaluation.label_groups_copied_status", { label: copiedLabel })}
          </span>
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
              onClick={() => retry((n) => n + 1)}
            >
              {t("autoTriage.retry")}
            </Button>
          </div>
        ) : !rows.length ? (
          <p
            role="status"
            className="px-5 py-6 text-center text-sm text-muted-foreground"
          >
            {t(summary ? "evaluation.label_groups_pending" : "loading")}
          </p>
        ) : (
          <div className="min-w-0 overflow-x-auto">
            <table className="block w-full text-left text-sm md:table">
              <caption className="sr-only">
                {t("evaluation.label_groups_title", {
                  release: releaseName(release),
                })}
              </caption>
              <thead className="sr-only md:not-sr-only md:table-header-group md:bg-muted/45 dark:md:bg-white/[0.025]">
                <tr className="md:border-b md:border-border/70">
                  <th
                    scope="col"
                    className="md:h-9 md:whitespace-nowrap md:px-4 md:text-xs md:font-medium md:text-muted-foreground lg:px-5"
                  >
                    {t("evaluation.label_groups_purpose")}
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
                    className="md:h-9 md:whitespace-nowrap md:pl-2 md:pr-4 md:text-right md:text-xs md:font-medium md:text-muted-foreground lg:pr-5"
                  >
                    {onSelectLabel
                      ? t("evaluation.label_groups_actions")
                      : "Trail"}
                  </th>
                </tr>
              </thead>
              <tbody className="block md:table-row-group">
                {rows.map((row, index) => {
                  const meta = GROUP_META[row.group] ?? DEFAULT_META;
                  const prevMeta =
                    index > 0
                      ? (GROUP_META[rows[index - 1].group] ?? DEFAULT_META)
                      : null;
                  const isTierBoundary =
                    prevMeta !== null && prevMeta.tier !== meta.tier;
                  const hasSuffix = Boolean(
                    sharedPrefix &&
                      row.label !== sharedPrefix &&
                      row.label.startsWith(`${sharedPrefix}_`),
                  );
                  const suffix = hasSuffix
                    ? row.label.slice(sharedPrefix.length)
                    : "";
                  const ratioPct =
                    totalScenes > 0
                      ? Math.min(
                          100,
                          Math.max(0, (row.count / totalScenes) * 100),
                        )
                      : 0;
                  const shareText = formatShare(row.count, totalScenes);
                  const isFiltered = Boolean(
                    activeLabel && activeLabel === row.label,
                  );
                  const isCopied = copiedLabel === row.label;

                  return (
                    <tr
                      key={row.label}
                      className={cn(
                        "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 px-4 py-2.5 transition-colors md:table-row md:px-0 md:py-0",
                        index > 0 &&
                          (isTierBoundary
                            ? "border-t border-border"
                            : "border-t border-border/50"),
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
                          <span className="min-w-0 break-words text-[13px] font-medium leading-snug text-foreground md:break-normal">
                            {t(`evaluation.label_group_${row.group}`, {
                              defaultValue: row.group,
                            })}
                          </span>
                        </div>
                      </th>
                      <td className="col-span-2 row-start-2 min-w-0 md:table-cell md:px-3 md:py-1.5 md:align-middle">
                        <div className="flex min-w-0 items-center gap-1">
                          <code className="min-w-0 max-w-full select-text break-words [overflow-wrap:anywhere] rounded-md border border-border/60 bg-muted/45 px-2.5 py-0.5 font-mono text-xs leading-5 dark:bg-white/[0.03] md:whitespace-nowrap md:break-normal md:[overflow-wrap:normal] md:[&_wbr]:hidden">
                            {hasSuffix ? (
                              <>
                                <span className="text-muted-foreground">
                                  {renderTokenizedText(sharedPrefix)}
                                </span>
                                <wbr />
                                <span className="font-semibold text-foreground">
                                  {renderTokenizedText(suffix)}
                                </span>
                              </>
                            ) : (
                              <span className="font-medium text-foreground">
                                {renderTokenizedText(row.label)}
                              </span>
                            )}
                          </code>
                          <button
                            type="button"
                            onClick={() => void handleCopy(row.label)}
                            title={t(
                              isCopied
                                ? "evaluation.label_groups_copied"
                                : "evaluation.label_groups_copy",
                            )}
                            aria-label={t("evaluation.label_groups_copy_aria", {
                              label: row.label,
                            })}
                            className="group inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:min-w-11"
                          >
                            {isCopied ? (
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
                            {row.count.toLocaleString(i18n.language)}
                          </span>
                          <span className="w-10 text-right font-mono text-[11px] tabular-nums text-muted-foreground">
                            {shareText}
                          </span>
                        </div>
                      </td>
                      <td className="col-span-2 row-start-3 md:table-cell md:whitespace-nowrap md:py-1.5 md:pl-2 md:pr-4 md:text-right md:align-middle lg:pr-5">
                        <div className="flex items-center justify-between gap-2 md:justify-end">
                          <div
                            className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted md:hidden"
                            aria-hidden="true"
                          >
                            <div
                              className={cn("h-full rounded-full", meta.bar)}
                              style={{ width: `${ratioPct}%` }}
                            />
                          </div>
                          <div className="flex shrink-0 items-center justify-end gap-0.5">
                            {onSelectLabel && (
                              <button
                                type="button"
                                aria-pressed={isFiltered}
                                aria-label={t(
                                  isFiltered
                                    ? "evaluation.label_groups_clear_filter_aria"
                                    : "evaluation.label_groups_filter_aria",
                                  { label: row.label },
                                )}
                                onClick={() => onSelectLabel(row.label)}
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
                            <a
                              className="group inline-flex h-7 items-center justify-center rounded-md px-0.5 text-xs font-medium text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [@media(pointer:coarse)]:min-h-11 [@media(pointer:coarse)]:min-w-11"
                              href={row.trail_url}
                              target="_blank"
                              rel="noreferrer"
                              aria-label={t("evaluation.label_groups_open", {
                                label: row.label,
                              })}
                            >
                              <span className="inline-flex h-7 items-center gap-1 rounded-md px-2 transition-colors group-hover:bg-accent group-hover:underline">
                                <span>Trail</span>
                                <ExternalLink size={12} aria-hidden="true" />
                              </span>
                            </a>
                          </div>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
