import { useTranslation } from "react-i18next";
import { releaseName } from "../lib/releaseName";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ExternalLink } from "lucide-react";
import type { VersionItem } from "../types";
import { cn } from "../lib/utils";
import { startVisiblePolling } from "../lib/visiblePolling";
import { request, type SourceIssue, type Workflow } from "./ReleaseWorkflow";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Select } from "./ui/select";
import { FilterPanel } from "./ui/filter-panel";
import { ReleaseLabelGroups } from "./ReleaseLabelGroups";
import { ReproductionStatus } from "./ReproductionStatus";
import { Pagination, PAGE_SIZES } from "./ui/pagination";

interface Props {
  versions: VersionItem[];
  version: string;
  onVersionChange: (version: string) => void;
  onHistoryChange: (shown: boolean) => void;
  history: ReactNode;
  basisControl: ReactNode;
  evaluation?: ReactNode;
}
interface CollectionVersion {
  release: string;
  collection_status: "stable" | "collecting" | "pending";
  source: "snapshot" | "observation";
  issue_count: number | null;
  auto_count: number | null;
  manual_count: number | null;
  synced_at: string | null;
  stale: boolean;
}
interface CollectionInventory {
  default_release: string | null;
  versions: CollectionVersion[];
}
function readFilters() {
  const q = new URLSearchParams(location.search),
    size = Number(q.get("page_size") || 20);
  return {
    page: /^\d+$/.test(q.get("page") || "1")
      ? Math.max(1, Number(q.get("page") || 1))
      : 1,
    size: PAGE_SIZES.includes(size) ? size : 20,
    query: q.get("query") || "",
    label: q.get("label") || "",
    view: q.get("issue_view") === "collection" ? "collection" : "simulation",
  };
}

function precisionBadgeClass(value?: string | null) {
  switch (value) {
    case "TP":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
    case "FN":
      return "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300";
    case "FP":
      return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300";
    case "TN":
      return "border-slate-400/35 bg-slate-500/10 text-slate-700 dark:text-slate-300";
    default:
      return "";
  }
}

export function ReleaseIssues({
  versions,
  version,
  onVersionChange,
  onHistoryChange,
  history: historyView,
  basisControl,
  evaluation,
}: Props) {
  const { t, i18n } = useTranslation();
  const [data, setData] = useState<Workflow | null>(null);
  const [inventory, setInventory] = useState<CollectionInventory | null>(null);
  const [rows, setRows] = useState<SourceIssue[]>([]);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState(readFilters);
  const [selectedKey, setSelectedKey] = useState("");
  const [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false),
    [notice, setNotice] = useState("");
  const generation = useRef(0),
    previousVersion = useRef(version);
  const selectedRelease =
    version === "@stable"
      ? inventory?.default_release
      : version === "@current"
        ? data?.current_version
        : version;
  const collection = inventory?.versions.find(
    (item) => item.release === selectedRelease,
  );
  const usesSource =
    version === "@stable" ||
    Boolean(collection) ||
    version === "@current" ||
    version === data?.current_version ||
    Boolean(
      data?.periods.some(
        (period) =>
          period.release === version &&
          period.status === "completed" &&
          (period.verified || period.basis === "inferred"),
      ),
    );
  const change = (value: Partial<typeof filters>) => {
    setSelectedKey("");
    setRows([]);
    setLoading(true);
    setFilters((v) => ({ ...v, ...value, page: value.page ?? 1 }));
  };
  useEffect(() => {
    if (evaluation) {
      onHistoryChange(false);
      return;
    }
    let active = true;
    const stop = startVisiblePolling(async () => {
      try {
        const [value, catalog] = await Promise.all([
          request<Workflow>(),
          request<CollectionInventory>("/versions"),
        ]);
        if (active) {
          setData(value);
          setInventory(catalog);
        }
        return value;
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : String(err));
        return null;
      }
    });
    return () => {
      active = false;
      stop();
    };
  }, [Boolean(evaluation)]);
  useEffect(() => {
    if (data && !evaluation) onHistoryChange(!usesSource);
  }, [data, usesSource, Boolean(evaluation), onHistoryChange]);
  useEffect(() => {
    if (previousVersion.current !== version) {
      change({ query: "", label: "", page: 1 });
      previousVersion.current = version;
    }
    setSelectedKey("");
    setRows([]);
    setTotal(0);
  }, [version, Boolean(evaluation)]);
  useEffect(() => {
    const pop = () => {
      setFilters(readFilters());
      setSelectedKey("");
    };
    addEventListener("popstate", pop);
    return () => removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    if (evaluation || !usesSource) return;
    const q = new URLSearchParams(location.search);
    q.set("page", String(filters.page));
    q.set("page_size", String(filters.size));
    for (const [key, value] of [
      ["query", filters.query],
      ["label", filters.label],
      ["issue_view", filters.view === "collection" ? "collection" : ""],
    ]) {
      if (value) q.set(key, value);
      else q.delete(key);
    }
    history.replaceState(history.state, "", `${location.pathname}?${q}`);
  }, [filters, Boolean(evaluation), usesSource]);
  const loadRows = useCallback(async () => {
    if (evaluation || !usesSource || !data) return null;
    const id = ++generation.current;
    setLoading(true);
    try {
      const params = new URLSearchParams({
        release: version,
        page: String(filters.page),
        page_size: String(filters.size),
        query: filters.query,
        label: filters.label,
        view: filters.view,
      });
      const result = await request<{ items: SourceIssue[]; total: number }>(
        `/issues?${params}`,
      );
      if (id === generation.current) {
        setRows(result.items);
        setTotal(result.total);
        setError("");
        const pages = Math.ceil(result.total / filters.size);
        if (pages && filters.page > pages) change({ page: pages });
      }
      return result;
    } catch (err) {
      if (id === generation.current)
        setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      if (id === generation.current) setLoading(false);
    }
  }, [Boolean(evaluation), usesSource, Boolean(data), version, filters]);
  useEffect(() => {
    const stop = startVisiblePolling(loadRows);
    return () => {
      generation.current++;
      stop();
    };
  }, [loadRows]);
  const rowKey = (row: SourceIssue) => `${row.issue_id}-${row.scenario_id}`;
  const selected = rows.find((row) => rowKey(row) === selectedKey) || rows[0];
  const options = new Map(
    versions.map((item) => [item.version_key, releaseName(item.version_key)]),
  );
  if (!evaluation)
    data?.periods
      .filter(
        (period) =>
          period.status === "completed" &&
          (period.verified || period.basis === "inferred"),
      )
      .forEach((period) =>
        options.set(period.release, releaseName(period.release)),
      );
  if (!evaluation)
    inventory?.versions.forEach((item) =>
      options.set(item.release, releaseName(item.release)),
    );
  const status = (value: string) =>
    t(`evaluation.issue_status_${value}`, { defaultValue: value });
  const label = (value?: string | null) =>
    value == null
      ? "—"
      : t(`autoTriage.result_${value}`, { defaultValue: value });
  const time = (value?: string | null) =>
    value
      ? new Date(value).toLocaleString(
          i18n.language.startsWith("zh") ? "zh-CN" : "en-GB",
          {
            timeZone: "Asia/Shanghai",
            hour12: false,
          },
        )
      : "—";
  async function sync() {
    setSyncing(true);
    setNotice("");
    try {
      await request("/sync", "POST");
      setNotice(t("evaluation.issue_sync_requested"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  }
  return (
    <div className="grid min-w-0 gap-4">
      <FilterPanel>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-base font-semibold">
            {t("evaluation.issue_title")}
          </h2>
          {!evaluation && collection && (
            <span className="text-xs text-muted-foreground tabular-nums">
              {t("evaluation.issue_updated")} {time(collection.synced_at)}
            </span>
          )}
        </div>
        <div className="grid min-w-0 gap-2.5 text-sm">
          <div className="flex min-w-0 flex-wrap items-end gap-3">
            <label className="grid min-w-0 gap-1.5 text-xs font-medium text-muted-foreground">
              <span>{t("version")}</span>
              <Select
                label={t("evaluation.issue_version")}
                value={version}
                options={[
                  {
                    value: "@stable",
                    label: t("evaluation.issue_latest", {
                      release: releaseName(
                        inventory?.default_release ||
                          [...versions].reverse().find((v) => !v.is_current)
                            ?.version_key,
                      ),
                    }),
                  },
                  ...(version === "@current"
                    ? [{ value: "@current", label: t("currentVersion") }]
                    : []),
                  ...[...options]
                    .sort(([a], [b]) => b.localeCompare(a))
                    .map(([value, text]) => ({ value, label: text })),
                ]}
                onChange={onVersionChange}
              />
            </label>
            {basisControl}
            {evaluation && (
              <div
                id="evaluation-actions"
                className="flex items-end sm:ml-auto"
              />
            )}
            {!evaluation && (
              <label className="grid min-w-0 gap-1.5 text-xs font-medium text-muted-foreground">
                <span>{t("evaluation.issue_view")}</span>
                <Select
                  label={t("evaluation.issue_view")}
                  value={filters.view}
                  options={[
                    {
                      value: "simulation",
                      label: t("evaluation.issue_simulation"),
                    },
                    {
                      value: "collection",
                      label: t("evaluation.issue_collection"),
                    },
                  ]}
                  onChange={(view) => change({ view })}
                />
              </label>
            )}
            {!evaluation && usesSource && (
              <Button
                variant="outline"
                className="min-h-11 sm:ml-auto"
                disabled={syncing}
                onClick={() => void sync()}
              >
                {t("evaluation.issue_sync")}
              </Button>
            )}
          </div>
          {!evaluation && (
            <p className="break-words text-xs text-muted-foreground">
              {t(
                filters.view === "simulation"
                  ? "evaluation.issue_simulation_note"
                  : "evaluation.issue_collection_note",
              )}
            </p>
          )}
          {!evaluation && collection?.stale && (
            <p
              role="status"
              className="text-xs text-amber-700 dark:text-amber-400"
            >
              {t("evaluation.issue_stale")}
            </p>
          )}
          {notice && <p role="status">{notice}</p>}
          {error && !evaluation && (
            <p role="alert" className="break-words text-destructive">
              {error}
            </p>
          )}
        </div>
      </FilterPanel>
      {!evaluation && selectedRelease?.startsWith("gen4-release-") && (
        <ReleaseLabelGroups
          key={selectedRelease}
          release={selectedRelease}
          activeLabel={
            filters.view === "simulation" ? filters.label : undefined
          }
          onSelectLabel={
            filters.view === "simulation"
              ? (value) =>
                  change({ label: filters.label === value ? "" : value })
              : undefined
          }
        />
      )}
      {evaluation ||
        (!usesSource ? (
          !data ? (
            <p role="status">{t("loading")}</p>
          ) : (
            historyView
          )
        ) : (
          <div className="grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.6fr)]">
            <Card className="min-w-0 overflow-hidden">
              <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 border-b border-border/70 px-4 py-3 md:px-5">
                <CardTitle>
                  {t("issues")} ({total.toLocaleString(i18n.language)})
                </CardTitle>
                <Badge variant="secondary" className="font-mono font-medium">
                  {releaseName(selectedRelease)}
                </Badge>
              </CardHeader>
              <CardContent className="grid min-w-0 gap-3 p-4 md:p-5">
                <div className="flex min-w-0 flex-wrap gap-2">
                  <input
                    aria-label={t("evaluation.issue_search")}
                    placeholder={t("evaluation.issue_search")}
                    className="min-h-10 min-w-0 flex-1 rounded-md border border-input bg-background px-3 text-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring [@media(pointer:coarse)]:min-h-11"
                    value={filters.query}
                    onChange={(e) => change({ query: e.target.value })}
                  />
                  {filters.view === "simulation" && (
                    <input
                      aria-label={t("evaluation.issue_label_filter")}
                      placeholder={t("evaluation.issue_label_filter")}
                      className="min-h-10 min-w-0 flex-1 rounded-md border border-input bg-background px-3 text-sm outline-none focus:border-ring focus:ring-1 focus:ring-ring [@media(pointer:coarse)]:min-h-11"
                      value={filters.label}
                      onChange={(e) => change({ label: e.target.value })}
                    />
                  )}
                  <Button
                    variant="outline"
                    className="min-h-10 [@media(pointer:coarse)]:min-h-11"
                    onClick={() => change({ query: "", label: "" })}
                  >
                    {t("reset")}
                  </Button>
                </div>
                <div
                  className="min-w-0 overflow-x-auto rounded-md border border-border/60"
                  aria-busy={loading}
                >
                  <table className="w-full min-w-[560px] table-fixed text-left text-sm">
                    <colgroup>
                      {[150, 130, 110, 110].map((width, i) => (
                        <col key={i} style={{ width }} />
                      ))}
                    </colgroup>
                    <thead className="bg-muted/45 dark:bg-white/[0.025]">
                      <tr className="border-b border-border/70">
                        {[
                          "issue",
                          "scenario",
                          "evaluation.issue_road",
                          "evaluation.issue_result",
                        ].map((key) => (
                          <th
                            key={key}
                            className="h-9 px-3 text-xs font-medium text-muted-foreground"
                          >
                            {t(key)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => {
                        const isSelected = Boolean(
                          selected && rowKey(selected) === rowKey(row),
                        );
                        return (
                          <tr
                            key={rowKey(row)}
                            onClick={() => setSelectedKey(rowKey(row))}
                            className={cn(
                              "cursor-pointer border-t border-border/50 transition-colors",
                              isSelected
                                ? "bg-primary/[0.07] hover:bg-primary/10"
                                : "hover:bg-accent/35",
                            )}
                          >
                            <td className="px-3 py-2">
                              <button
                                className="inline-flex min-h-8 items-center text-left font-mono text-[13px] font-medium text-primary hover:underline [@media(pointer:coarse)]:min-h-11"
                                aria-label={t("evaluation.issue_open", {
                                  id: row.issue_id,
                                })}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setSelectedKey(rowKey(row));
                                }}
                              >
                                {row.issue_id}
                              </button>
                              <p
                                className="truncate text-xs text-muted-foreground"
                                title={row.issue_topic}
                              >
                                {row.issue_topic}
                              </p>
                            </td>
                            <td className="px-3 py-2">
                              <span className="font-mono text-[13px] tabular-nums">
                                {row.scenario_id ||
                                  t("evaluation.issue_unmapped")}
                              </span>
                              <p
                                className="truncate text-xs text-muted-foreground"
                                title={row.scenario_name}
                              >
                                {row.scenario_name}
                              </p>
                            </td>
                            <td className="px-3 py-2">
                              <span className="text-[13px] font-medium">
                                {label(row.source_result)}
                              </span>
                              <p className="text-xs text-muted-foreground">
                                {row.ra_type
                                  ? t(
                                      row.ra_type === 3
                                        ? "autoTriage.manualTrigger"
                                        : "autoTriage.autoTrigger",
                                    )
                                  : ""}
                              </p>
                            </td>
                            <td className="px-3 py-2">
                              {row.precision_label ? (
                                <Badge
                                  variant="outline"
                                  className={cn(
                                    "px-1.5 py-0 font-mono text-[11px] font-semibold",
                                    precisionBadgeClass(row.precision_label),
                                  )}
                                >
                                  {row.precision_label}
                                </Badge>
                              ) : (
                                <span className="text-muted-foreground">—</span>
                              )}
                              <p className="mt-0.5 text-xs text-muted-foreground">
                                {status(row.simulation_status)}
                              </p>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {!rows.length && (
                    <p
                      role="status"
                      className="p-6 text-center text-sm text-muted-foreground"
                    >
                      {t(loading ? "loading" : "noIssues")}
                    </p>
                  )}
                </div>
                <Pagination
                  total={total}
                  page={filters.page}
                  pageSize={filters.size}
                  loading={loading || !!error}
                  onPageChange={(page) => change({ page })}
                  onPageSizeChange={(size) => change({ size })}
                />
                {!!error && (
                  <Button
                    variant="outline"
                    className="min-h-11"
                    onClick={() => void loadRows()}
                  >
                    {t("autoTriage.retry")}
                  </Button>
                )}
              </CardContent>
            </Card>
            <Card className="min-w-0 overflow-hidden xl:sticky xl:top-6">
              <CardHeader className="border-b border-border/70 px-4 py-3 md:px-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle className="font-mono">
                    {selected?.issue_id || t("evaluation.issue_detail")}
                  </CardTitle>
                  {selected && (
                    <a
                      className="inline-flex min-h-8 items-center gap-1 text-xs font-medium text-primary hover:underline [@media(pointer:coarse)]:min-h-11"
                      href={`https://voyager.intra.xiaojukeji.com/paladin/issue/detail/${encodeURIComponent(selected.issue_id)}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {t("evaluation.issue_open_link")}
                      <ExternalLink size={13} />
                    </a>
                  )}
                </div>
              </CardHeader>
              <CardContent className="grid min-w-0 gap-4 p-4 text-sm md:p-5">
                {selected ? (
                  <>
                    <p className="break-words text-sm leading-snug text-foreground">
                      {selected.issue_topic}
                    </p>
                    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 rounded-md border border-border/60 bg-muted/20 p-3 text-xs">
                      <dt className="text-muted-foreground">
                        {t("evaluation.issue_build")}
                      </dt>
                      <dd className="break-all font-mono">
                        {selected.road_version}
                      </dd>
                      <dt className="text-muted-foreground">
                        {t("evaluation.issue_road")}
                      </dt>
                      <dd className="font-medium">
                        {label(selected.source_result)}
                      </dd>
                      <dt className="text-muted-foreground">
                        {t("evaluation.issue_state")}
                      </dt>
                      <dd>{status(selected.simulation_status)}</dd>
                      <dt className="text-muted-foreground">
                        {t("autoTriage.simTriggered")}
                      </dt>
                      <dd>
                        {selected.sim_triggered == null
                          ? "—"
                          : t(
                              selected.sim_triggered
                                ? "autoTriage.triggered"
                                : "autoTriage.notTriggered",
                            )}
                      </dd>
                      {selected.reproduction && (
                        <>
                          <dt className="text-muted-foreground">
                            {t("reproduction.title")}
                          </dt>
                          <dd>
                            <ReproductionStatus value={selected.reproduction} />
                          </dd>
                        </>
                      )}
                      <dt className="text-muted-foreground">
                        {t("evaluation.issue_result")}
                      </dt>
                      <dd>
                        {selected.precision_label ? (
                          <Badge
                            variant="outline"
                            className={cn(
                              "px-1.5 py-0 font-mono text-[11px] font-semibold",
                              precisionBadgeClass(selected.precision_label),
                            )}
                          >
                            {selected.precision_label}
                          </Badge>
                        ) : (
                          "—"
                        )}
                      </dd>
                    </dl>
                    {selected.job_id && (
                      <a
                        className="inline-flex items-center gap-1 break-words font-mono text-xs text-primary hover:underline"
                        target="_blank"
                        rel="noreferrer"
                        href={`http://voyager.intra.xiaojukeji.com/static/management/#/orion/job/detail?job_id=${selected.job_id}`}
                      >
                        Job {selected.job_id}
                        <ExternalLink size={12} />
                        {selected.execution_conflict &&
                          ` · ${t("evaluation.issue_conflict")}`}
                      </a>
                    )}
                    {selected.result_note && (
                      <details className="rounded-md border border-border/60 p-3 text-xs">
                        <summary className="min-h-8 cursor-pointer font-medium [@media(pointer:coarse)]:min-h-11">
                          {t("evaluation.issue_notes")}
                        </summary>
                        <pre className="mt-2 whitespace-pre-wrap break-words">
                          {selected.result_note}
                        </pre>
                      </details>
                    )}
                    <div className="rounded-md border border-border/60 bg-muted/20 p-3">
                      <p className="font-mono text-xs font-semibold">
                        Scenario{" "}
                        {selected.scenario_id || t("evaluation.issue_unmapped")}
                      </p>
                      <p className="mt-1 break-all font-mono text-[11px] text-muted-foreground">
                        {selected.scenario_name}
                      </p>
                      {selected.scenario_id && selectedRelease && (
                        <a
                          className="mt-2 inline-flex min-h-8 items-center gap-1 text-xs font-medium text-primary hover:underline [@media(pointer:coarse)]:min-h-11"
                          href={`${import.meta.env.BASE_URL}simulation?${new URLSearchParams({ version: selectedRelease, parameters: "1", scenario: selected.scenario_id })}`}
                        >
                          {t("evaluation.issue_parameters")}
                          <ExternalLink size={12} />
                        </a>
                      )}
                    </div>
                    <div>
                      <p className="mb-2 text-xs font-medium text-muted-foreground">
                        {t("evaluation.issue_labels")}
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {selected.scenario_labels.map((value) => (
                          <button
                            key={value}
                            type="button"
                            title={t("evaluation.issue_filter_label")}
                            className={cn(
                              "max-w-full break-all rounded-full border px-2.5 py-0.5 text-left font-mono text-[11px] transition-colors [@media(pointer:coarse)]:min-h-11",
                              filters.label === value
                                ? "border-primary bg-primary text-primary-foreground"
                                : "border-border/60 bg-muted/45 text-foreground hover:bg-accent",
                            )}
                            onClick={() =>
                              change({
                                label: filters.label === value ? "" : value,
                              })
                            }
                          >
                            {value}
                          </button>
                        ))}
                        {!selected.scenario_labels.length && (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </div>
                    </div>
                  </>
                ) : (
                  <p className="py-8 text-center text-muted-foreground">
                    {t("evaluation.issue_select")}
                  </p>
                )}
              </CardContent>
            </Card>
          </div>
        ))}
    </div>
  );
}
