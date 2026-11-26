import React, { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest, getApiBasePath } from "../api/client";
import { bilingual, formatCstTime, UiLanguage } from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { CASE_PAGE_SIZES, DEFAULT_CASE_PAGE_SIZE, Pagination } from "../components/ui/Pagination";
import { UiSelect, UiSelectOption } from "../components/ui/UiSelect";

export interface ModelRunSourceFile {
  filename?: string;
  available?: boolean;
  reconstructed?: boolean;
  preview_supported?: boolean;
  preview_url?: string;
  download_url?: string;
}

export interface ModelRunItem {
  id: string;
  name: string;
  kind?: string;
  is_default?: boolean;
  source_name?: string;
  created_by?: string;
  declared_author?: string;
  created_at?: string | number;
  baseline_prediction_count?: number;
  failure_count?: number;
  inferred_baseline_ids?: string[];
  source_file?: ModelRunSourceFile;
  metadata?: {
    record_url?: string;
    records_url?: string;
    view_id?: string | number;
    trail_view_id?: string | number;
    model_name?: string;
    prompt_version?: string;
    external_username?: string;
    experiment?: {
      run_id?: string;
      experiment_id?: string;
      model_name?: string;
      prompt_version?: string;
    };
    platform_batch?: {
      batch_name?: string;
    };
  };
}

export interface ModelRunsPayload {
  items?: ModelRunItem[];
  aliases?: Record<string, string>;
  default_model_run_id?: string;
  baseline_issue_count?: number;
}

export interface RunsManagerIslandProps {
  active: boolean;
  lang: UiLanguage;
  username: string;
}

interface LegacyRunsWindow {
  __RA_TRIAGE_STATE__?: {
    selectedRunId?: string;
    modelRuns?: ModelRunItem[];
    modelRunAliases?: Record<string, string>;
    runPage?: number;
    runPageSize?: number;
  };
  selectedBaselineQueryValue?: () => string;
  currentWorksetIssueCount?: () => number;
  useModelRun?: (runId: string) => Promise<void> | void;
  openSourcePreview?: (runId: string) => void;
  loadRuns?: (opts?: { preserveEmpty?: boolean }) => Promise<void> | void;
  loadOverview?: () => Promise<void> | void;
  loadCases?: () => Promise<void> | void;
  loadClusters?: () => Promise<void> | void;
  showToast?: (message: string, isError?: boolean) => void;
}

function getLegacyWindow(): LegacyRunsWindow {
  return window as unknown as LegacyRunsWindow;
}

function readBaselinesQuery(): string {
  const fromLegacy = getLegacyWindow().selectedBaselineQueryValue?.();
  if (fromLegacy) return fromLegacy;
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("baselines") || "";
}

function readInitialPagination(): { page: number; pageSize: number } {
  if (typeof window === "undefined") {
    return { page: 1, pageSize: DEFAULT_CASE_PAGE_SIZE };
  }
  const params = new URLSearchParams(window.location.search);
  const rawPage = Number.parseInt(params.get("page") || "1", 10);
  const rawSize = Number.parseInt(params.get("page_size") || String(DEFAULT_CASE_PAGE_SIZE), 10);
  const page = Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1;
  const pageSize = CASE_PAGE_SIZES.includes(rawSize as (typeof CASE_PAGE_SIZES)[number])
    ? rawSize
    : DEFAULT_CASE_PAGE_SIZE;
  return { page, pageSize };
}

function safeExternalUrl(raw?: string): string {
  if (!raw) return "";
  try {
    const parsed = new URL(raw, window.location.origin);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return parsed.href;
    }
  } catch {
    return "";
  }
  return "";
}

function safeSameOriginAssetUrl(raw?: string): string {
  if (!raw) return "";
  const trimmed = String(raw).trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("/")) {
    const base = getApiBasePath();
    if (base && !trimmed.startsWith(`${base}/`)) {
      return `${base}${trimmed}`;
    }
    return trimmed;
  }
  try {
    const parsed = new URL(trimmed, window.location.origin);
    if (parsed.origin === window.location.origin) {
      return `${parsed.pathname}${parsed.search}`;
    }
  } catch {
    return "";
  }
  return "";
}

function runOwner(run: ModelRunItem): string {
  return run.created_by || run.declared_author || "";
}

function runBatchName(run: ModelRunItem, lang: UiLanguage): string {
  const experiment = run.metadata?.experiment;
  const platformBatch = run.metadata?.platform_batch;
  const sourceFile = String(run.source_name || "").split(/[\\/]/).pop() || "";
  return (
    platformBatch?.batch_name ||
    experiment?.run_id ||
    experiment?.experiment_id ||
    sourceFile.replace(/\.(json|csv|xlsx|xlsm)$/i, "") ||
    bilingual(lang, "未命名批次", "Unnamed batch")
  );
}

function sourceMetaForKind(
  kind: string | undefined,
  lang: UiLanguage,
): { label: string; description: string; className: string } {
  switch (kind) {
    case "upload":
      return {
        label: bilingual(lang, "文件模型结果", "Uploaded file"),
        description: "JSON / CSV / XLSX",
        className: "source-upload",
      };
    case "trail_snapshot":
      return {
        label: bilingual(lang, "Trail 快照", "Trail snapshot"),
        description: bilingual(lang, "只读 Trail 视图快照", "Read-only Trail snapshot"),
        className: "source-trail",
      };
    case "autotriage_snapshot":
      return {
        label: bilingual(lang, "AutoTriage 快照", "AutoTriage snapshot"),
        description: bilingual(lang, "自动分诊平台快照", "AutoTriage platform snapshot"),
        className: "source-autotriage",
      };
    case "manual_batch":
      return {
        label: bilingual(lang, "网页 Batch 预测", "Web batch prediction"),
        description: bilingual(lang, "网页批量推理结果", "Web batch inference results"),
        className: "source-batch",
      };
    default:
      return {
        label: kind || bilingual(lang, "未知来源", "Unknown source"),
        description: bilingual(lang, "历史模型输出", "Historical model output"),
        className: "source-unknown",
      };
  }
}

export const RunsManagerIsland: React.FC<RunsManagerIslandProps> = ({
  active,
  lang,
  username,
}) => {
  const queryClient = useQueryClient();
  const initialPaging = useMemo(() => readInitialPagination(), []);
  const [search, setSearch] = useState("");
  const [personFilter, setPersonFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [page, setPage] = useState(initialPaging.page);
  const [pageSize, setPageSize] = useState(initialPaging.pageSize);
  const [baselinesKey, setBaselinesKey] = useState(() => readBaselinesQuery());
  const [selectedRunId, setSelectedRunId] = useState(
    () => getLegacyWindow().__RA_TRIAGE_STATE__?.selectedRunId || "",
  );
  const [deleteTarget, setDeleteTarget] = useState<ModelRunItem | null>(null);
  const [feedback, setFeedback] = useState<{ text: string; error?: boolean } | null>(null);

  useEffect(() => {
    const syncExternal = () => {
      setBaselinesKey(readBaselinesQuery());
      setSelectedRunId(getLegacyWindow().__RA_TRIAGE_STATE__?.selectedRunId || "");
    };
    if (active) syncExternal();
    window.addEventListener("ra:workbench-sync", syncExternal);
    window.addEventListener("popstate", syncExternal);
    return () => {
      window.removeEventListener("ra:workbench-sync", syncExternal);
      window.removeEventListener("popstate", syncExternal);
    };
  }, [active]);

  const runsQuery = useQuery<ModelRunsPayload>({
    queryKey: ["model-runs", baselinesKey],
    queryFn: ({ signal }) => {
      const qs = baselinesKey ? `?baselines=${encodeURIComponent(baselinesKey)}` : "";
      return apiRequest<ModelRunsPayload>(`/api/model-runs${qs}`, { signal });
    },
    enabled: active,
    staleTime: 15_000,
  });

  const items = useMemo(() => runsQuery.data?.items || [], [runsQuery.data]);

  // Keep the top import source card counts and legacy state in sync.
  useEffect(() => {
    if (!runsQuery.data) return;
    const legacyState = getLegacyWindow().__RA_TRIAGE_STATE__;
    if (legacyState && Array.isArray(runsQuery.data.items)) {
      legacyState.modelRuns = runsQuery.data.items;
      if (runsQuery.data.aliases && typeof runsQuery.data.aliases === "object") {
        legacyState.modelRunAliases = runsQuery.data.aliases;
      }
    }
    const counts: Record<string, string> = {
      upload: "runSourceCountUpload",
      trail_snapshot: "runSourceCountTrail",
      autotriage_snapshot: "runSourceCountAutotriage",
    };
    for (const [kind, elId] of Object.entries(counts)) {
      const el = document.getElementById(elId);
      if (el) {
        el.textContent = String(items.filter((run) => run.kind === kind).length);
      }
    }
  }, [items, runsQuery.data]);

  const peopleOptions = useMemo<UiSelectOption[]>(() => {
    const owners = Array.from(
      new Set(items.map((run) => runOwner(run)).filter(Boolean)),
    ).sort((a, b) => a.localeCompare(b, "zh-CN"));

    const opts: UiSelectOption[] = [
      { value: "", label: bilingual(lang, "全部人员", "All people") },
    ];
    if (username) {
      opts.push({
        value: "__me__",
        label: bilingual(lang, `我的 · ${username}`, `Mine · ${username}`),
      });
    }
    for (const owner of owners) {
      opts.push({ value: owner, label: owner });
    }
    return opts;
  }, [items, lang, username]);

  // Preserve valid selection when options refresh; reset stale owner.
  useEffect(() => {
    if (!personFilter) return;
    if (!peopleOptions.some((opt) => opt.value === personFilter)) {
      setPersonFilter("");
    }
  }, [peopleOptions, personFilter]);

  const kindOptions = useMemo<UiSelectOption[]>(
    () => [
      { value: "", label: bilingual(lang, "全部来源", "All sources") },
      { value: "upload", label: bilingual(lang, "文件模型结果", "Uploaded file") },
      { value: "trail_snapshot", label: bilingual(lang, "Trail 快照", "Trail snapshot") },
      { value: "manual_batch", label: bilingual(lang, "网页 Batch 预测", "Web batch prediction") },
      {
        value: "autotriage_snapshot",
        label: bilingual(lang, "AutoTriage 快照", "AutoTriage snapshot"),
      },
    ],
    [lang],
  );

  const filteredRuns = useMemo(() => {
    const q = search.trim().toLowerCase();
    const resolvedPerson = personFilter === "__me__" ? username : personFilter;
    return items.filter((run) => {
      if (resolvedPerson && runOwner(run) !== resolvedPerson) return false;
      if (kindFilter && run.kind !== kindFilter) return false;
      if (!q) return true;
      const haystack = [
        run.name,
        runBatchName(run, lang),
        run.source_name,
        run.created_by,
        run.declared_author,
        run.metadata?.model_name,
        run.metadata?.prompt_version,
        run.metadata?.external_username,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [items, search, personFilter, kindFilter, username, lang]);

  const totalCoverage = useMemo(
    () => filteredRuns.reduce((sum, run) => sum + Number(run.baseline_prediction_count || 0), 0),
    [filteredRuns],
  );

  const pageCount = Math.max(1, Math.ceil(filteredRuns.length / pageSize));
  const safePage = Math.max(1, Math.min(pageCount, page));

  useEffect(() => {
    if (safePage !== page) setPage(safePage);
  }, [safePage, page]);

  // Sync URL pagination parameters when on the Runs page.
  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    const legacyState = getLegacyWindow().__RA_TRIAGE_STATE__;
    if (legacyState) {
      legacyState.runPage = safePage;
      legacyState.runPageSize = pageSize;
    }
    try {
      const url = new URL(window.location.href);
      if (safePage > 1) url.searchParams.set("page", String(safePage));
      else url.searchParams.delete("page");
      if (pageSize !== DEFAULT_CASE_PAGE_SIZE) url.searchParams.set("page_size", String(pageSize));
      else url.searchParams.delete("page_size");
      const next = `${url.pathname}${url.search}`;
      const current = `${window.location.pathname}${window.location.search}`;
      if (next !== current) {
        window.history.replaceState({ ...(window.history.state || {}), page: "runs" }, "", next);
      }
    } catch {
      // Ignore history restrictions in non-standard test URLs.
    }
  }, [active, safePage, pageSize]);

  const visibleRuns = useMemo(() => {
    const start = (safePage - 1) * pageSize;
    return filteredRuns.slice(start, start + pageSize);
  }, [filteredRuns, safePage, pageSize]);

  const baselineCount =
    getLegacyWindow().currentWorksetIssueCount?.() ||
    Number(runsQuery.data?.baseline_issue_count || 0);

  const deleteMutation = useMutation({
    mutationFn: (run: ModelRunItem) =>
      apiRequest<{ deleted?: { name?: string }; source_deleted?: boolean }>(
        `/api/model-runs/${encodeURIComponent(run.id)}`,
        { method: "DELETE" },
      ),
    onSuccess: async (result, run) => {
      setDeleteTarget(null);
      const deletedName = result?.deleted?.name || run.name;
      const msg = bilingual(
        lang,
        `已删除 Run「${deletedName}」${result?.source_deleted ? "及来源文件" : ""}。`,
        `Deleted Run "${deletedName}"${result?.source_deleted ? " and source archive" : ""}.`,
      );
      setFeedback({ text: msg });
      getLegacyWindow().showToast?.(msg);
      await queryClient.invalidateQueries({ queryKey: ["model-runs"] });
      void getLegacyWindow().loadRuns?.({ preserveEmpty: true });
      void getLegacyWindow().loadOverview?.();
      void getLegacyWindow().loadCases?.();
      void getLegacyWindow().loadClusters?.();
    },
    onError: (error: Error) => {
      setFeedback({ text: error.message, error: true });
      getLegacyWindow().showToast?.(error.message, true);
    },
  });

  const handleRefresh = async () => {
    setFeedback(null);
    await runsQuery.refetch();
    void getLegacyWindow().loadRuns?.({ preserveEmpty: true });
    void getLegacyWindow().loadOverview?.();
    const msg = bilingual(lang, "模型 Run 列表已刷新。", "Model runs refreshed.");
    setFeedback({ text: msg });
  };

  const handleUseRun = (runId: string) => {
    setSelectedRunId(runId);
    const legacyWin = getLegacyWindow();
    if (legacyWin.useModelRun) {
      void legacyWin.useModelRun(runId);
    }
  };

  const renderSourceRef = (run: ModelRunItem) => {
    const metadata = run.metadata || {};
    const recordUrl = safeExternalUrl(metadata.record_url || metadata.records_url);
    if (recordUrl) {
      return (
        <a
          className="run-source-link"
          href={recordUrl}
          target="_blank"
          rel="noreferrer"
        >
          {bilingual(lang, "原始记录", "Raw records")}
        </a>
      );
    }
    if (run.kind === "trail_snapshot") {
      const viewId =
        metadata.view_id ||
        metadata.trail_view_id ||
        String(run.source_name || "").match(/\d+/)?.[0] ||
        "2410";
      return <span className="run-source-ref">Trail view {String(viewId)}</span>;
    }
    const source = run.source_file || {};
    const sourceName =
      String(source.filename || run.source_name || "").split(/[\\/]/).pop() ||
      bilingual(lang, "未记录文件名", "Filename unavailable");
    const previewUrl = safeSameOriginAssetUrl(source.preview_url);
    const downloadUrl = safeSameOriginAssetUrl(source.download_url);
    return (
      <span className="run-source-ref" title={run.source_name || sourceName}>
        {bilingual(lang, "原始文件", "Source file")} · {sourceName}{" "}
        {source.available && (previewUrl || downloadUrl) ? (
          <>
            <span className="run-source-actions">
              {source.preview_supported ? (
                <button
                  className="run-source-preview"
                  type="button"
                  onClick={() => getLegacyWindow().openSourcePreview?.(run.id)}
                >
                  {bilingual(lang, "预览", "Preview")}
                </button>
              ) : previewUrl ? (
                <a
                  className="run-source-link"
                  href={previewUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  {bilingual(lang, "打开", "Open")}
                </a>
              ) : null}
              {downloadUrl && (
                <a className="run-source-link" href={downloadUrl} download>
                  {bilingual(lang, "下载", "Download")}
                </a>
              )}
            </span>
            {source.reconstructed && (
              <span className="run-source-reconstructed">
                {bilingual(lang, "Run 重建", "Run rebuilt")}
              </span>
            )}
          </>
        ) : (
          <span className="run-source-unavailable">
            {bilingual(lang, "未归档", "Not archived")}
          </span>
        )}
      </span>
    );
  };

  return (
    <div
      id="raRunsManagerRoot"
      className="ra-runs-manager-root"
      data-react-island="runs-manager"
    >
      <div className="runs-toolbar">
        <h3>{bilingual(lang, "模型结果管理", "Model run management")}</h3>
        <div className="run-manager-actions">
          <button
            className="button button-quiet"
            id="raRefreshRunsButton"
            type="button"
            disabled={runsQuery.isFetching}
            onClick={() => void handleRefresh()}
          >
            {runsQuery.isFetching
              ? bilingual(lang, "刷新中…", "Refreshing…")
              : bilingual(lang, "刷新", "Refresh")}
          </button>
        </div>
      </div>

      <div className="run-filter-bar run-filter-three ra-runs-filter-bar">
        <label className="ra-field-stack" htmlFor="raRunSearchInput">
          <span>{bilingual(lang, "模型 / 批次", "Model / batch")}</span>
          <input
            id="raRunSearchInput"
            type="search"
            value={search}
            autoComplete="off"
            placeholder={bilingual(
              lang,
              "搜索模型名、批次或文件",
              "Search model, batch, or file",
            )}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
          />
        </label>

        <div className="ra-field-stack">
          <span>{bilingual(lang, "人员", "People")}</span>
          <UiSelect
            id="raRunPersonSelect"
            value={personFilter}
            options={peopleOptions}
            ariaLabel={bilingual(lang, "按人员筛选 Run", "Filter runs by person")}
            onChange={(next) => {
              setPersonFilter(next);
              setPage(1);
            }}
          />
        </div>

        <div className="ra-field-stack">
          <span>{bilingual(lang, "来源类型", "Source type")}</span>
          <UiSelect
            id="raRunKindSelect"
            value={kindFilter}
            options={kindOptions}
            ariaLabel={bilingual(lang, "按来源类型筛选 Run", "Filter runs by source type")}
            onChange={(next) => {
              setKindFilter(next);
              setPage(1);
            }}
          />
        </div>
      </div>

      <div className="run-manager-summary" id="raRunManagerSummary" role="status" aria-live="polite">
        {runsQuery.isLoading
          ? bilingual(lang, "正在加载 Runs…", "Loading Runs…")
          : runsQuery.isError
            ? bilingual(
                lang,
                `加载 Runs 失败：${(runsQuery.error as Error)?.message || "未知错误"}`,
                `Failed to load Runs: ${(runsQuery.error as Error)?.message || "Unknown error"}`,
              )
            : bilingual(
                lang,
                `${filteredRuns.length} / ${items.length} 个 Run · ${totalCoverage} 条预测 · 第 ${safePage} / ${pageCount} 页`,
                `${filteredRuns.length} / ${items.length} runs · ${totalCoverage} predictions · Page ${safePage} / ${pageCount}`,
              )}
      </div>

      {feedback && (
        <p
          className={`ra-inline-feedback${feedback.error ? " is-error" : ""}`}
          role="status"
        >
          {feedback.text}
        </p>
      )}

      <div className="run-manager-list" id="raModelRunList">
        {runsQuery.isLoading ? (
          <div className="no-asset">{bilingual(lang, "正在加载 Runs…", "Loading Runs…")}</div>
        ) : runsQuery.isError ? (
          <div className="no-asset">
            {bilingual(lang, "无法获取模型 Run 列表，请点击刷新重试。", "Unable to fetch model runs. Click Refresh to retry.")}
          </div>
        ) : !visibleRuns.length ? (
          <div className="no-asset">
            {bilingual(lang, "当前筛选下没有 Run。", "No runs match the current filters.")}
          </div>
        ) : (
          visibleRuns.map((run) => {
            const coverage = Number(run.baseline_prediction_count || 0);
            const isFull = baselineCount > 0 && coverage >= baselineCount;
            const owner = runOwner(run) || bilingual(lang, "未记录", "Unrecorded");
            const batch = runBatchName(run, lang);
            const modelName =
              run.metadata?.model_name || run.metadata?.experiment?.model_name || "";
            const promptVersion =
              run.metadata?.prompt_version || run.metadata?.experiment?.prompt_version || "";
            const externalUser = run.metadata?.external_username || "";
            const sourceMeta = sourceMetaForKind(run.kind, lang);
            const isSelected = run.id === selectedRunId;
            const ownerTitle = run.created_by
              ? bilingual(
                  lang,
                  `提交人：${run.created_by}${run.declared_author && run.declared_author !== run.created_by ? `；结果包作者：${run.declared_author}` : ""}`,
                  `Submitted by: ${run.created_by}${run.declared_author && run.declared_author !== run.created_by ? `; Pack author: ${run.declared_author}` : ""}`,
                )
              : run.declared_author
                ? bilingual(
                    lang,
                    `结果包作者：${run.declared_author}`,
                    `Pack author: ${run.declared_author}`,
                  )
                : bilingual(lang, "人员信息未记录", "Owner unrecorded");

            return (
              <article
                key={run.id}
                className={`run-row${isSelected ? " active" : ""}`}
                data-run-id={run.id}
              >
                <div className="run-row-main">
                  <div className="run-row-title">
                    <strong>{run.name}</strong>
                    <span
                      className={`run-source-badge ${sourceMeta.className}`}
                      title={sourceMeta.description}
                    >
                      {sourceMeta.label}
                    </span>
                    <span className="run-coverage-badge">
                      {isFull
                        ? bilingual(lang, "全量覆盖", "Full coverage")
                        : bilingual(lang, "部分覆盖", "Partial coverage")}
                    </span>
                  </div>

                  <div className="run-row-meta">
                    <span title={ownerTitle}>
                      {bilingual(lang, "人员", "Owner")} ·{" "}
                      <b className="run-meta-value">{owner}</b>
                    </span>
                    <span title={run.source_name || ""}>
                      {bilingual(lang, "批次", "Batch")} ·{" "}
                      <b className="run-meta-value">{batch}</b>
                    </span>
                    {modelName && (
                      <span>
                        {bilingual(lang, "模型", "Model")} · {modelName}
                      </span>
                    )}
                    {promptVersion && <span>Prompt · {promptVersion}</span>}
                    {externalUser && externalUser !== owner && (
                      <span>
                        {bilingual(lang, "平台用户", "Platform user")} · {externalUser}
                      </span>
                    )}
                    <span>{renderSourceRef(run)}</span>
                    <span title={bilingual(lang, "相对当前数据集", "Relative to active dataset")}>
                      {coverage} /{" "}
                      {baselineCount || "—"}{" "}
                      {bilingual(lang, "条", "cases")}
                    </span>
                    <span className="run-failure-count">
                      {bilingual(lang, "错误", "Failures")} {run.failure_count ?? 0}
                    </span>
                    <span>{formatCstTime(run.created_at, lang)}</span>
                  </div>
                </div>

                <div className="run-row-actions">
                  <button
                    className={`button ${isSelected ? "button-primary" : "button-quiet"}`}
                    type="button"
                    onClick={() => handleUseRun(run.id)}
                  >
                    {isSelected
                      ? bilingual(lang, "当前 Review", "Active in Review")
                      : bilingual(lang, "打开 Review", "Open in Review")}
                  </button>
                  {run.is_default ? (
                    <button
                      className="button button-quiet"
                      type="button"
                      disabled
                      title={bilingual(
                        lang,
                        "先切换团队默认 Run 才能删除",
                        "Switch team default Run before deleting",
                      )}
                    >
                      {bilingual(lang, "默认 Run", "Default Run")}
                    </button>
                  ) : (
                    <button
                      className="button button-danger"
                      type="button"
                      disabled={deleteMutation.isPending}
                      onClick={() => setDeleteTarget(run)}
                    >
                      {bilingual(lang, "删除", "Delete")}
                    </button>
                  )}
                </div>
              </article>
            );
          })
        )}
      </div>

      {filteredRuns.length > 0 && (
        <Pagination
          page={safePage}
          pageSize={pageSize}
          total={filteredRuns.length}
          lang={lang}
          loading={runsQuery.isFetching}
          ariaLabel={bilingual(lang, "模型 Run 分页", "Model runs pagination")}
          onPageChange={(next) => setPage(next)}
          onPageSizeChange={(nextSize) => {
            setPageSize(nextSize);
            setPage(1);
          }}
        />
      )}

      <ModalDialog
        open={Boolean(deleteTarget)}
        title={bilingual(lang, "确认删除模型 Run", "Confirm Run deletion")}
        lang={lang}
        onClose={() => {
          if (!deleteMutation.isPending) setDeleteTarget(null);
        }}
        footer={
          <>
            <button
              type="button"
              className="button button-quiet"
              disabled={deleteMutation.isPending}
              onClick={() => setDeleteTarget(null)}
            >
              {bilingual(lang, "取消", "Cancel")}
            </button>
            <button
              type="button"
              className="button button-danger ra-primary-touch"
              disabled={deleteMutation.isPending}
              onClick={() => {
                if (deleteTarget) deleteMutation.mutate(deleteTarget);
              }}
            >
              {deleteMutation.isPending
                ? bilingual(lang, "删除中…", "Deleting…")
                : bilingual(lang, "确认删除", "Delete Run")}
            </button>
          </>
        }
      >
        <p className="ra-alloc-subtitle">
          {bilingual(
            lang,
            `确认删除模型 Run「${deleteTarget?.name || ""}」？该操作会删除该 Run 的模型输出和来源归档，不会删除任何 GT 数据集、Issue 或人工 review，且不可恢复。`,
            `Delete model Run "${deleteTarget?.name || ""}"? This removes its predictions and archived source file without affecting GT datasets, Issues, or manual reviews. This action cannot be undone.`,
          )}
        </p>
      </ModalDialog>
    </div>
  );
};
