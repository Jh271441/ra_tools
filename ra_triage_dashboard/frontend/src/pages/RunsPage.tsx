import React, { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { bilingual, UiLanguage } from "../bridge/useWorkbenchBridge";
import { ModalDialog } from "../components/ui/ModalDialog";
import { showWorkbenchToast } from "../features/review/reviewHelpers";
import { useWorkbench } from "../shell/WorkbenchContext";
import { RunsManagerIsland } from "./RunsManagerIsland";

type SourceTab = "upload" | "autotriage" | "trail";

const IMPORT_EXAMPLES: Record<"csv" | "json" | "xlsx", { filename: string; content: string }> = {
  csv: {
    filename: "model_results.csv",
    content: [
      "issue_id,model_label,reason,confidence,ra_stuck_auto_result_info",
      'cn32171803,无需协助,"红灯持续亮起，前车停在停止线后，自车同步等待",0.96,"{""reason"":""红绿灯周期性等待"",""confidence"":0.96}"',
      'cn31954847,误触发,"前方大车遮挡，但红灯转绿后车流正常放行",0.88,"{""reason"":""排队等灯"",""confidence"":0.88}"',
    ].join("\n"),
  },
  json: {
    filename: "model_results.json",
    content: JSON.stringify(
      {
        experiment: { model_name: "Qwen3.5-9B", prompt: "stuck_triage_auto_opt_api" },
        results: [{ issue_id: "cn32171803", model_label: "无需协助", reason: "红绿灯等待", confidence: 0.96 }],
      },
      null,
      2,
    ),
  },
  xlsx: {
    filename: "model_results.xlsx",
    content:
      "Sheet1\nissue_id | model_label | reason | confidence | ra_stuck_auto_result_info\ncn32171803 | 无需协助 | 红绿灯等待 | 0.96 | {\"reason\":\"红绿灯等待\"}",
  },
};

export interface RunsPageProps {
  active: boolean;
  lang: UiLanguage;
  username: string;
}

export const RunsPage: React.FC<RunsPageProps> = ({ active, lang, username }) => {
  const queryClient = useQueryClient();
  const { config, selectedBaselines } = useWorkbench();
  const [tab, setTab] = useState<SourceTab>("upload");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [runName, setRunName] = useState("");
  const [uploadOutput, setUploadOutput] = useState("");
  const [atBatchId, setAtBatchId] = useState("");
  const [atRunName, setAtRunName] = useState("");
  const [atOutput, setAtOutput] = useState("");
  const [trailOutput, setTrailOutput] = useState("");
  const [exampleOpen, setExampleOpen] = useState(false);
  const [exampleFmt, setExampleFmt] = useState<"csv" | "json" | "xlsx">("csv");
  const [previewRunId, setPreviewRunId] = useState<string | null>(null);

  const previewQuery = useQuery<{ filename?: string; columns?: string[]; rows?: Array<Record<string, unknown>>; total?: number }>({
    queryKey: ["run-source-preview", previewRunId],
    queryFn: ({ signal }) =>
      apiRequest(`/api/model-runs/${encodeURIComponent(previewRunId!)}/source-preview?page=1&page_size=100`, {
        signal,
      }),
    enabled: Boolean(previewRunId),
  });

  // Wire window.openSourcePreview so RunsManagerIsland's Preview button opens this modal
  React.useEffect(() => {
    const win = window as unknown as { openSourcePreview?: (id: string) => void };
    win.openSourcePreview = (id: string) => setPreviewRunId(id);
    return () => {
      delete win.openSourcePreview;
    };
  }, []);

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!uploadFile) throw new Error(bilingual(lang, "请选择文件。", "Please choose a file."));
      const form = new FormData();
      form.append("file", uploadFile);
      form.append("run_name", runName.trim());
      form.append("created_by", username);
      return apiRequest<Record<string, unknown>>("/api/import/model-results", {
        method: "POST",
        body: form,
      });
    },
    onSuccess: (res) => {
      setUploadOutput(JSON.stringify(res, null, 2));
      setUploadFile(null);
      setRunName("");
      void queryClient.invalidateQueries({ queryKey: ["model-runs"] });
      showWorkbenchToast(
        res.duplicate
          ? bilingual(lang, "已复用相同内容的模型 Run。", "Reused identical model Run.")
          : bilingual(lang, "模型 Run 已导入。", "Model Run imported."),
      );
    },
    onError: (err: Error) => {
      setUploadOutput(err.message);
      showWorkbenchToast(err.message, true);
    },
  });

  const autotriageMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ duplicate?: boolean; batch_id?: string; coverage?: { accepted_result_count?: number; declared_total?: number; partial?: boolean } }>(
        "/api/import/autotriage",
        {
          method: "POST",
          body: JSON.stringify({
            batch_id: atBatchId.trim(),
            run_name: atRunName.trim(),
            created_by: username,
          }),
        },
      ),
    onSuccess: (res) => {
      const cov = res.coverage || {};
      setAtOutput(
        `${res.duplicate ? bilingual(lang, "复用已有 Run", "Reused Run") : bilingual(lang, "已创建快照 Run", "Created snapshot Run")} · Batch ${res.batch_id || ""} · ${cov.accepted_result_count ?? "—"} / ${cov.declared_total ?? "—"}`,
      );
      void queryClient.invalidateQueries({ queryKey: ["model-runs"] });
      showWorkbenchToast(
        bilingual(lang, "AutoTriage Run 已拉取。", "AutoTriage Run imported."),
        Boolean(cov.partial),
      );
    },
    onError: (err: Error) => {
      setAtOutput(err.message);
      showWorkbenchToast(err.message, true);
    },
  });

  const trailSyncMutation = useMutation({
    mutationFn: (mode: "preview" | "create") =>
      apiRequest<{ status?: string; message?: string; run_id?: string }>("/api/trail-model-sync", {
        method: "POST",
        body: JSON.stringify({ mode, requested_by: username }),
      }),
    onSuccess: (res) => {
      setTrailOutput(res.message || JSON.stringify(res));
      if (res.run_id) void queryClient.invalidateQueries({ queryKey: ["model-runs"] });
      showWorkbenchToast(
        res.message || bilingual(lang, "Trail 检查完成。", "Trail check complete."),
        ["failed", "unavailable"].includes(res.status || ""),
      );
    },
    onError: (err: Error) => {
      setTrailOutput(err.message);
      showWorkbenchToast(err.message, true);
    },
  });

  const trailViewId = useMemo(
    () => String((config?.trail_sync as { view_id?: string | number } | undefined)?.view_id ?? "2410"),
    [config],
  );

  return (
    <section
      id="runsPage"
      className="app-page ra-react-page"
      data-page="runs"
      data-react-island="runs"
    >
      {/* Import Sources Card */}
      <div className="panel-card" id="runsSourceCard">
        <div className="ra-page-header-row">
          <div>
            <h2>{bilingual(lang, "导入模型结果", "Import Model Results")}</h2>
            <p className="muted">
              {bilingual(
                lang,
                `当前数据集：${selectedBaselines.join(" + ") || "默认"} · 支持本地文件、AutoTriage 与 Trail 只读快照`,
                `Active datasets: ${selectedBaselines.join(" + ") || "Default"} · Supports file upload, AutoTriage & Trail snapshots`,
              )}
            </p>
          </div>
          <div className="ra-inline-actions" role="tablist">
            {(
              [
                ["upload", bilingual(lang, "上传文件", "Upload file")],
                ["autotriage", bilingual(lang, "AutoTriage 快照", "AutoTriage snapshot")],
                ["trail", bilingual(lang, "Trail 快照", "Trail snapshot")],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={tab === k}
                className={`button ${tab === k ? "button-primary" : "button-quiet"}`}
                onClick={() => setTab(k)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {tab === "upload" && (
          <form
            className="ra-filter-grid"
            style={{ marginTop: 12 }}
            onSubmit={(e) => {
              e.preventDefault();
              uploadMutation.mutate();
            }}
          >
            <label className="ra-field-stack">
              <span>{bilingual(lang, "结果文件 (JSON / CSV / XLSX)", "Result file (JSON / CSV / XLSX)")}</span>
              <input
                type="file"
                accept=".json,.csv,.xlsx,.xlsm"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              />
            </label>
            <label className="ra-field-stack">
              <span>{bilingual(lang, "Run 名称（可选）", "Run name (optional)")}</span>
              <input
                type="text"
                value={runName}
                placeholder={bilingual(lang, "留空则使用文件名", "Defaults to filename")}
                onChange={(e) => setRunName(e.target.value)}
              />
            </label>
            <div className="ra-inline-actions" style={{ alignItems: "flex-end" }}>
              <button
                type="submit"
                className="button button-primary"
                disabled={uploadMutation.isPending || !uploadFile}
              >
                {uploadMutation.isPending
                  ? bilingual(lang, "导入中…", "Importing…")
                  : bilingual(lang, "上传并创建 Run", "Upload & create Run")}
              </button>
              <button
                type="button"
                className="button button-quiet"
                onClick={() => setExampleOpen(true)}
              >
                {bilingual(lang, "格式示例", "Format examples")}
              </button>
            </div>
            {uploadOutput && (
              <pre className="ra-code-block" style={{ gridColumn: "1 / -1" }}>
                {uploadOutput}
              </pre>
            )}
          </form>
        )}

        {tab === "autotriage" && (
          <form
            className="ra-filter-grid"
            style={{ marginTop: 12 }}
            onSubmit={(e) => {
              e.preventDefault();
              if (!atBatchId.trim()) return;
              autotriageMutation.mutate();
            }}
          >
            <label className="ra-field-stack" style={{ gridColumn: "span 2" }}>
              <span>{bilingual(lang, "AutoTriage Batch ID 或 records 链接", "AutoTriage Batch ID or records URL")}</span>
              <input
                type="text"
                value={atBatchId}
                required
                placeholder="batch_id or https://..."
                onChange={(e) => setAtBatchId(e.target.value)}
              />
            </label>
            <label className="ra-field-stack">
              <span>{bilingual(lang, "自定义 Run 名称（可选）", "Run name (optional)")}</span>
              <input type="text" value={atRunName} onChange={(e) => setAtRunName(e.target.value)} />
            </label>
            <div className="ra-inline-actions" style={{ alignItems: "flex-end" }}>
              <button
                type="submit"
                className="button button-primary"
                disabled={autotriageMutation.isPending || !atBatchId.trim()}
              >
                {autotriageMutation.isPending
                  ? bilingual(lang, "拉取中…", "Fetching…")
                  : bilingual(lang, "拉取并创建 Run", "Fetch & create Run")}
              </button>
            </div>
            {atOutput && (
              <p className="ra-inline-feedback" style={{ gridColumn: "1 / -1" }}>
                {atOutput}
              </p>
            )}
          </form>
        )}

        {tab === "trail" && (
          <div className="ra-modal-stack" style={{ marginTop: 12 }}>
            <p className="muted">
              {bilingual(
                lang,
                `只读检查 Trail View ${trailViewId} 的模型字段并可选创建本地快照 Run，不写入 Trail。`,
                `Read-only check of Trail View ${trailViewId} model fields to optionally create a local snapshot Run without writing to Trail.`,
              )}
            </p>
            <div className="ra-inline-actions">
              <button
                type="button"
                className="button button-quiet"
                disabled={trailSyncMutation.isPending}
                onClick={() => trailSyncMutation.mutate("preview")}
              >
                {bilingual(lang, "检查字段", "Inspect fields")}
              </button>
              <button
                type="button"
                className="button button-primary"
                disabled={trailSyncMutation.isPending}
                onClick={() => trailSyncMutation.mutate("create")}
              >
                {bilingual(lang, "创建 Trail 快照 Run", "Create Trail snapshot Run")}
              </button>
            </div>
            {trailOutput && <p className="ra-inline-feedback">{trailOutput}</p>}
          </div>
        )}
      </div>

      {/* Runs List Island */}
      <div className="panel-card runs-page-card">
        <RunsManagerIsland active={active} lang={lang} username={username} />
      </div>

      {/* Format Example Modal */}
      <ModalDialog
        open={exampleOpen}
        title={bilingual(lang, "模型结果导入格式示例", "Model Result Import Examples")}
        lang={lang}
        onClose={() => setExampleOpen(false)}
      >
        <div className="ra-inline-actions" style={{ marginBottom: 10 }}>
          {(["csv", "json", "xlsx"] as const).map((fmt) => (
            <button
              key={fmt}
              type="button"
              className={`button ${exampleFmt === fmt ? "button-primary" : "button-quiet"}`}
              onClick={() => setExampleFmt(fmt)}
            >
              {fmt.toUpperCase()}
            </button>
          ))}
        </div>
        <p className="muted">{IMPORT_EXAMPLES[exampleFmt].filename}</p>
        <pre className="ra-code-block">{IMPORT_EXAMPLES[exampleFmt].content}</pre>
      </ModalDialog>

      {/* Source File Preview Modal */}
      <ModalDialog
        open={Boolean(previewRunId)}
        title={bilingual(lang, "模型 Run 原始文件预览", "Model Run Source Preview")}
        lang={lang}
        onClose={() => setPreviewRunId(null)}
      >
        {previewQuery.isLoading ? (
          <p className="muted">{bilingual(lang, "正在加载预览…", "Loading preview…")}</p>
        ) : previewQuery.isError ? (
          <p className="ra-inline-feedback is-error">{(previewQuery.error as Error)?.message}</p>
        ) : (
          <div className="ra-table-scroll">
            <table className="trail-history-table">
              <thead>
                <tr>
                  {(previewQuery.data?.columns || []).map((col) => (
                    <th key={col}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(previewQuery.data?.rows || []).slice(0, 50).map((row, idx) => (
                  <tr key={idx}>
                    {(previewQuery.data?.columns || []).map((col) => (
                      <td key={col}>{String(row[col] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ModalDialog>
    </section>
  );
};
