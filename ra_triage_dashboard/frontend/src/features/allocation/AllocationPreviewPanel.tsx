import React from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";

export interface AllocationPreviewPayload {
  preview_token?: string;
  expires_at?: number;
  total_slots?: number;
  active_slots?: number;
  changed_cases?: number;
  moved_slots?: number;
  completed_slots?: number;
  saved_pending_slots?: number;
  coverage_before?: { cross_cases: number; case_count: number };
  coverage_after?: { cross_cases: number; case_count: number };
  group_coverage?: {
    case_count: number;
    active_slots?: number;
    groups: Array<{
      group_id: string;
      union_completed?: number;
      members: Array<{ name: string; total: number; completed?: number }>;
    }>;
  };
  members?: Array<{
    name: string;
    before: number;
    total_after: number;
    pending_after: number;
    completed: number;
    saved_pending: number;
    incoming: number;
    outgoing: number;
    actual_percent?: number;
    constrained?: boolean;
  }>;
  changes?: Array<{ issue_id: string; before: string[]; after: string[] }>;
}

const SEGMENT_COLORS = ["#38bdf8", "#34d399", "#fbbf24", "#c084fc", "#fb7185", "#60a5fa"];

export interface AllocationPreviewPanelProps {
  preview: AllocationPreviewPayload | null;
  lang: UiLanguage;
  isUpdating: boolean;
  errorText?: string | null;
  onRetry?: () => void;
}

export const AllocationPreviewPanel: React.FC<AllocationPreviewPanelProps> = ({
  preview,
  lang,
  isUpdating,
  errorText,
  onRetry,
}) => {
  const chart = preview?.group_coverage;
  const members = preview?.members || [];
  const changes = preview?.changes || [];
  const maxWorkload = Math.max(1, ...members.flatMap((m) => [m.before || 0, m.total_after || 0]));

  const handleExportCsv = () => {
    if (!changes.length) return;
    const escapeCell = (v: string) =>
      `"${String(v).replace(/^[=+@-]/, "'$&").replaceAll('"', '""')}"`;
    const rows = [
      [
        bilingual(lang, "Case", "Case"),
        bilingual(lang, "原负责人", "Previous owners"),
        bilingual(lang, "调整后负责人", "New owners"),
      ],
      ...changes.map((c) => [c.issue_id, c.before.join(", "), c.after.join(", ")]),
    ];
    const blob = new Blob(["\ufeff", rows.map((r) => r.map(escapeCell).join(",")).join("\r\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "allocation-changes.csv";
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <section
      className={`ra-alloc-preview${isUpdating ? " is-preview-updating" : ""}${errorText ? " is-preview-stale" : ""}`}
      aria-label={bilingual(lang, "实时预览", "Live preview")}
    >
      <div className="ra-alloc-preview-head">
        <h3>{bilingual(lang, "实时预览", "Live preview")}</h3>
        {isUpdating && (
          <span className="ra-preview-updating-pill" aria-live="polite">
            {bilingual(lang, "更新中…", "Updating…")}
          </span>
        )}
      </div>

      {errorText && (
        <div className="ra-inline-feedback is-error" role="alert">
          <span>{errorText}</span>
          {onRetry && (
            <button type="button" className="button button-quiet" onClick={onRetry}>
              {bilingual(lang, "重新计算", "Recalculate")}
            </button>
          )}
        </div>
      )}

      {!preview ? (
        <p className="muted">
          {isUpdating
            ? bilingual(lang, "正在计算预览…", "Calculating preview…")
            : bilingual(lang, "配置分配组后自动生成预览。", "Configure groups to preview allocation.")}
        </p>
      ) : (
        <div className="ra-alloc-preview-body">
          <div className="ra-alloc-facts">
            <div>
              <small className="muted">{bilingual(lang, "分配总量", "Total slots")}</small>
              <strong>{(preview.active_slots ?? preview.total_slots ?? 0).toLocaleString()}</strong>
            </div>
            {preview.changed_cases != null && (
              <div>
                <small className="muted">{bilingual(lang, "涉及 Case", "Cases affected")}</small>
                <strong>{preview.changed_cases.toLocaleString()}</strong>
              </div>
            )}
            {preview.moved_slots != null && (
              <div>
                <small className="muted">{bilingual(lang, "转入份数", "Moved slots")}</small>
                <strong>{preview.moved_slots.toLocaleString()}</strong>
              </div>
            )}
            {preview.completed_slots != null && (
              <div>
                <small className="muted">{bilingual(lang, "保留已完成", "Retained done")}</small>
                <strong>
                  {(
                    (preview.completed_slots || 0) + (preview.saved_pending_slots || 0)
                  ).toLocaleString()}
                </strong>
              </div>
            )}
          </div>

          {chart && chart.case_count > 0 && (
            <div className="ra-alloc-bars">
              {chart.groups.map((grp, gIdx) => {
                const covered =
                  grp.members.reduce((sum, m) => sum + (m.total || 0), 0) +
                  (grp.union_completed || 0);
                return (
                  <div key={grp.group_id} className="ra-alloc-bar-group">
                    <div className="ra-alloc-bar-label">
                      <strong>{bilingual(lang, `第 ${gIdx + 1} 组`, `Group ${gIdx + 1}`)}</strong>
                      <span className="muted">
                        {bilingual(lang, "覆盖", "Cover")}{" "}
                        {Math.round((100 * covered) / chart.case_count)}% ({covered}/
                        {chart.case_count})
                      </span>
                    </div>
                    <div className="ra-alloc-bar-track">
                      {grp.members.map((m, mIdx) => {
                        const pct = (100 * (m.total || 0)) / chart.case_count;
                        if (pct <= 0) return null;
                        return (
                          <div
                            key={m.name}
                            className="ra-alloc-bar-seg"
                            style={{
                              flexBasis: `${pct}%`,
                              backgroundColor:
                                SEGMENT_COLORS[(gIdx * 2 + mIdx) % SEGMENT_COLORS.length],
                            }}
                            title={`${m.name}: ${m.total}`}
                          >
                            <span>{m.name}</span>
                            <small>{m.total}</small>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {members.length > 0 && (
            <div className="ra-alloc-roster">
              <h4>{bilingual(lang, "人员工作量对比", "Member workload")}</h4>
              {members.map((m) => {
                const delta = (m.total_after || 0) - (m.before || 0);
                return (
                  <div key={m.name} className="ra-alloc-roster-row">
                    <div className="ra-alloc-roster-name">
                      <strong>{m.name}</strong>
                      <small className="muted">
                        {m.before} → {m.total_after}
                        {delta !== 0 ? ` (${delta > 0 ? "+" : ""}${delta})` : ""}
                      </small>
                    </div>
                    <div className="ra-alloc-roster-track">
                      <span
                        className="ra-alloc-roster-fill"
                        style={{ width: `${Math.min(100, (100 * (m.total_after || 0)) / maxWorkload)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {changes.length > 0 && (
            <details className="ra-alloc-changes">
              <summary>
                {bilingual(lang, "逐 Case 变更", "Changes by Case")} · {changes.length}
              </summary>
              <ul>
                {changes.slice(0, 12).map((c) => (
                  <li key={c.issue_id}>
                    <code>{c.issue_id}</code>:{" "}
                    <span className="muted">
                      {c.before.join(" + ")} → {c.after.join(" + ")}
                    </span>
                  </li>
                ))}
              </ul>
              <button type="button" className="button button-quiet" onClick={handleExportCsv}>
                {bilingual(lang, "下载变更 CSV", "Download changes CSV")}
              </button>
            </details>
          )}
        </div>
      )}
    </section>
  );
};
