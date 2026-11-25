import React, { useMemo, useState } from "react";
import { bilingual, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { ModalDialog } from "../../components/ui/ModalDialog";
import { showWorkbenchToast } from "./reviewHelpers";

export interface RaEventRow {
  timestamp_ms?: number | string;
  relative_ms?: number;
  event_type?: string;
  type?: string;
  name?: string;
  message?: string;
  detail?: string;
  summary?: string;
}

export interface TrailMetadataPayload {
  status?: string;
  external_links?: {
    ares_studio?: string;
    ra_recording?: string;
    trail_url?: string;
    voyager_issue_url?: string;
  };
  ra_events?: RaEventRow[];
  events?: RaEventRow[];
  t0_timestamp_ms?: number;
  dashboard_should_exclude?: boolean | null;
}

export interface RaEventModalProps {
  open: boolean;
  issueId: string;
  metadata: TrailMetadataPayload | null;
  loading?: boolean;
  lang: UiLanguage;
  onRefresh?: () => void;
  onClose: () => void;
}

export const RaEventModal: React.FC<RaEventModalProps> = ({
  open,
  issueId,
  metadata,
  loading = false,
  lang,
  onRefresh,
  onClose,
}) => {
  const [search, setSearch] = useState("");
  const events = useMemo(
    () => metadata?.ra_events || metadata?.events || [],
    [metadata],
  );
  const t0 = Number(metadata?.t0_timestamp_ms || NaN);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return events;
    return events.filter((ev) =>
      JSON.stringify(ev).toLowerCase().includes(q),
    );
  }, [events, search]);

  const copyTs = async (val: string) => {
    try {
      await navigator.clipboard.writeText(val);
      showWorkbenchToast(bilingual(lang, "时间戳已复制。", "Timestamp copied."));
    } catch {
      showWorkbenchToast(bilingual(lang, "复制失败。", "Copy failed."), true);
    }
  };

  return (
    <ModalDialog
      open={open}
      wide
      lang={lang}
      title={`RA Events · ${issueId}`}
      onClose={onClose}
      footer={
        <>
          {onRefresh && (
            <button
              type="button"
              className="button button-quiet"
              disabled={loading}
              onClick={onRefresh}
            >
              {bilingual(lang, "刷新", "Refresh")}
            </button>
          )}
          <button type="button" className="button button-primary" onClick={onClose}>
            {bilingual(lang, "关闭", "Close")}
          </button>
        </>
      }
    >
      <div className="ra-event-modal-body">
        <div className="ra-event-search-row">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={bilingual(lang, "搜索事件类型、时间或内容…", "Search event type, time, or details…")}
            aria-label={bilingual(lang, "搜索 RA 事件", "Search RA events")}
          />
          <span className="muted">
            {filtered.length} / {events.length}
          </span>
        </div>

        {loading ? (
          <p className="muted">{bilingual(lang, "正在读取 RA Event…", "Loading RA events…")}</p>
        ) : filtered.length === 0 ? (
          <p className="muted">{bilingual(lang, "暂无匹配的 RA Event 记录。", "No matching RA events.")}</p>
        ) : (
          <div className="ra-table-scroll">
            <table className="rd-table">
              <thead>
                <tr>
                  <th>{bilingual(lang, "相对时间", "Offset")}</th>
                  <th>{bilingual(lang, "时间戳", "Timestamp")}</th>
                  <th>{bilingual(lang, "类型", "Type")}</th>
                  <th>{bilingual(lang, "内容", "Details")}</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((ev, idx) => {
                  const tsNum = Number(ev.timestamp_ms);
                  const relMs =
                    ev.relative_ms != null
                      ? Number(ev.relative_ms)
                      : Number.isFinite(tsNum) && Number.isFinite(t0)
                        ? tsNum - t0
                        : NaN;
                  const relStr = Number.isFinite(relMs)
                    ? `${relMs >= 0 ? "+" : ""}${(relMs / 1000).toFixed(2)}s`
                    : "—";
                  return (
                    <tr key={idx}>
                      <td><code>{relStr}</code></td>
                      <td>
                        {ev.timestamp_ms ? (
                          <button
                            type="button"
                            className="text-link"
                            onClick={() => void copyTs(String(ev.timestamp_ms))}
                          >
                            {String(ev.timestamp_ms)}
                          </button>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>{ev.event_type || ev.type || ev.name || "—"}</td>
                      <td>{ev.message || ev.detail || ev.summary || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </ModalDialog>
  );
};
