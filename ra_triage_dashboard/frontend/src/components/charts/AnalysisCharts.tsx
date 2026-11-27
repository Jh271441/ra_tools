import React, { useCallback, useMemo, useRef, useState } from "react";
import { bilingual, ColorTheme, UiLanguage } from "../../bridge/useWorkbenchBridge";
import { ModalDialog } from "../ui/ModalDialog";

// Cool theme-aligned palettes matching static/js/analysis-charts.js 1:1.
export const ANALYSIS_PIE_BASE_DARK = [
  "#24d3ef",
  "#38bdf8",
  "#22d3ee",
  "#2dd4bf",
  "#14b8a6",
  "#67e8f9",
  "#60a5fa",
  "#818cf8",
  "#a5b4fc",
  "#94a3b8",
] as const;

export const ANALYSIS_PIE_BASE_LIGHT = [
  "#0e7490",
  "#0369a1",
  "#0f766e",
  "#0891b2",
  "#0284c7",
  "#0d9488",
  "#155e75",
  "#1e3a5f",
  "#475569",
  "#64748b",
] as const;

export const TRIAGE_LABELS = ["误触发", "正确触发", "无需协助"] as const;
export const STAGE1_TRUE_STUCK_LABEL = "真实卡住";
export const MODEL_LABELS = [...TRIAGE_LABELS, STAGE1_TRUE_STUCK_LABEL] as const;

export function modelLabelMatchesGt(
  modelLabel: string | null | undefined,
  gtLabel: string | null | undefined,
): boolean {
  const model = String(modelLabel || "");
  const gt = String(gtLabel || "");
  if (
    !(MODEL_LABELS as readonly string[]).includes(model) ||
    !(TRIAGE_LABELS as readonly string[]).includes(gt)
  ) {
    return false;
  }
  if (model === STAGE1_TRUE_STUCK_LABEL) {
    return gt === "正确触发" || gt === "无需协助";
  }
  return model === gt;
}

export function analysisPiePalette(panelKey: string | undefined, theme: ColorTheme): string[] {
  const base = theme === "light" ? [...ANALYSIS_PIE_BASE_LIGHT] : [...ANALYSIS_PIE_BASE_DARK];
  const offsets: Record<string, number> = { evidence: 0, scene: 5, trigger: 2, egress: 1 };
  const start = offsets[panelKey || ""] || 0;
  return [...base.slice(start), ...base.slice(0, start)];
}

export interface AnalysisPieItem {
  key: string;
  label: string;
  count: number;
  description?: string;
  color?: string;
}

export interface AnalysisPieArc {
  item: AnalysisPieItem;
  index: number;
  start: number;
  end: number;
  fraction: number;
  mid: number;
}

export function analysisPieArcs(items: readonly AnalysisPieItem[]): {
  arcs: AnalysisPieArc[];
  sum: number;
} {
  const rows = (items || [])
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => Number(item.count) > 0);
  const sum = rows.reduce((acc, { item }) => acc + Number(item.count || 0), 0);
  if (!sum) return { arcs: [], sum: 0 };
  let angle = -Math.PI / 2;
  const arcs = rows.map(({ item, index }) => {
    const fraction = Number(item.count || 0) / sum;
    const start = angle;
    const end = angle + fraction * Math.PI * 2;
    angle = end;
    return { item, index, start, end, fraction, mid: (start + end) / 2 };
  });
  return { arcs, sum };
}

export function analysisDonutSlicePath(
  cx: number,
  cy: number,
  outer: number,
  inner: number,
  start: number,
  end: number,
): string {
  const large = end - start > Math.PI ? 1 : 0;
  const polar = (r: number, a: number): [number, number] => [
    cx + r * Math.cos(a),
    cy + r * Math.sin(a),
  ];
  const [x1, y1] = polar(outer, start);
  const [x2, y2] = polar(outer, end);
  const [x3, y3] = polar(inner, end);
  const [x4, y4] = polar(inner, start);
  if (end - start >= Math.PI * 2 - 1e-6) {
    const mid = start + Math.PI;
    const [mx1, my1] = polar(outer, mid);
    const [mx2, my2] = polar(inner, mid);
    return [
      `M ${x1} ${y1}`,
      `A ${outer} ${outer} 0 1 1 ${mx1} ${my1}`,
      `A ${outer} ${outer} 0 1 1 ${x1} ${y1}`,
      `L ${x4} ${y4}`,
      `A ${inner} ${inner} 0 1 0 ${mx2} ${my2}`,
      `A ${inner} ${inner} 0 1 0 ${x4} ${y4}`,
      "Z",
    ].join(" ");
  }
  return [
    `M ${x1} ${y1}`,
    `A ${outer} ${outer} 0 ${large} 1 ${x2} ${y2}`,
    `L ${x3} ${y3}`,
    `A ${inner} ${inner} 0 ${large} 0 ${x4} ${y4}`,
    "Z",
  ].join(" ");
}

export function analysisPiePercent(count: number, sum: number): number {
  if (!sum) return 0;
  return Math.round((Number(count || 0) / sum) * 1000) / 10;
}

export function labelBadgeClass(label: string | null | undefined): string {
  const actual = String(label || "").trim();
  return (MODEL_LABELS as readonly string[]).includes(actual)
    ? `label-badge label-${actual}`
    : "label-badge label-empty";
}

export const LabelBadge: React.FC<{
  label: string | null | undefined;
  emptyText?: string;
  displayLabel?: string | null;
}> = ({ label, emptyText = "—", displayLabel = null }) => {
  const clean = String(label || "").trim();
  const display = displayLabel ?? (clean && clean !== "NONE" ? clean : emptyText);
  return <span className={labelBadgeClass(clean)}>{display}</span>;
};

export interface PieTooltipState {
  label: string;
  count: number;
  percent: number;
  description?: string;
  left: number;
  top: number;
}

export function useAnalysisPieTooltip() {
  const [tooltip, setTooltip] = useState<PieTooltipState | null>(null);
  const tipRef = useRef<HTMLDivElement | null>(null);

  const showTooltip = useCallback(
    (
      event: React.PointerEvent,
      item: { label: string; count: number; description?: string },
      percent: number,
    ) => {
      const pad = 12;
      const box = tipRef.current?.getBoundingClientRect();
      const width = box && box.width > 0 ? box.width : 200;
      const height = box && box.height > 0 ? box.height : 64;
      let left = event.clientX + pad;
      let top = event.clientY + pad;
      if (typeof window !== "undefined") {
        if (left + width > window.innerWidth - 8) left = event.clientX - width - pad;
        if (top + height > window.innerHeight - 8) top = event.clientY - height - pad;
      }
      setTooltip({
        label: item.label,
        count: item.count,
        percent,
        description: item.description,
        left: Math.max(8, left),
        top: Math.max(8, top),
      });
    },
    [],
  );

  const hideTooltip = useCallback(() => setTooltip(null), []);

  return { tooltip, tipRef, showTooltip, hideTooltip };
}

export const AnalysisPieTooltip: React.FC<{
  tooltip: PieTooltipState | null;
  tipRef: React.RefObject<HTMLDivElement | null>;
  lang: UiLanguage;
}> = ({ tooltip, tipRef, lang }) => (
  <div
    ref={tipRef}
    className="analysis-pie-tooltip"
    role="tooltip"
    hidden={!tooltip}
    style={tooltip ? { left: `${tooltip.left}px`, top: `${tooltip.top}px` } : undefined}
  >
    {tooltip && (
      <>
        <strong>{tooltip.label}</strong>
        <span>
          {bilingual(
            lang,
            `${tooltip.count} 条 · ${tooltip.percent}%`,
            `${tooltip.count} · ${tooltip.percent}%`,
          )}
        </span>
        {tooltip.description && <small>{tooltip.description}</small>}
      </>
    )}
  </div>
);

export interface AnalysisClusterGroupData {
  key: string;
  label: string;
  annotated_count: number;
  items: AnalysisPieItem[];
}

export interface AnalysisClusterPanelData {
  key: string;
  label: string;
  layout?: "single" | "dual" | string;
  groups: AnalysisClusterGroupData[];
}

export const AnalysisDonutGroup: React.FC<{
  group: AnalysisClusterGroupData;
  palette: string[];
  dual?: boolean;
  lang: UiLanguage;
  onShowTooltip: (
    event: React.PointerEvent,
    item: AnalysisPieItem,
    percent: number,
  ) => void;
  onHideTooltip: () => void;
}> = ({ group, palette, dual = false, lang, onShowTooltip, onHideTooltip }) => {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const items = group.items || [];
  const size = dual ? 120 : 150;
  const cx = size / 2;
  const cy = size / 2;
  const outer = size * 0.46;
  const inner = size * 0.2;
  const labelR = (outer + inner) / 2;
  const { arcs, sum } = useMemo(() => analysisPieArcs(items), [items]);

  return (
    <div className={`analysis-pie-group ${dual ? "is-dual" : "is-single"}`}>
      <div className="analysis-pie-figure" data-group-label={group.label || ""}>
        {!arcs.length ? (
          <svg
            className="analysis-pie-svg"
            viewBox={`0 0 ${size} ${size}`}
            width={size}
            height={size}
            aria-hidden="true"
          >
            <circle
              className="analysis-pie-empty-ring"
              cx={cx}
              cy={cy}
              r={(outer + inner) / 2}
              fill="none"
              strokeWidth={outer - inner}
            />
          </svg>
        ) : (
          <svg
            className="analysis-pie-svg"
            viewBox={`0 0 ${size} ${size}`}
            width={size}
            height={size}
            role="img"
            aria-label={group.label || undefined}
          >
            {arcs.map(({ item, index, start, end }) => {
              const color = item.color || palette[index % palette.length];
              const percent = analysisPiePercent(item.count, sum);
              const isHover = hoveredKey === item.key;
              return (
                <path
                  key={item.key}
                  className={`analysis-pie-slice${isHover ? " is-hover" : ""}`}
                  data-pie-index={index}
                  data-pie-key={item.key}
                  d={analysisDonutSlicePath(cx, cy, outer, inner, start, end)}
                  fill={color}
                  onPointerEnter={(e) => {
                    setHoveredKey(item.key);
                    onShowTooltip(e, item, percent);
                  }}
                  onPointerMove={(e) => onShowTooltip(e, item, percent)}
                  onPointerLeave={() => {
                    setHoveredKey(null);
                    onHideTooltip();
                  }}
                />
              );
            })}
            {arcs
              .filter(({ fraction }) => fraction >= 0.1)
              .map(({ item, mid, fraction }) => (
                <text
                  key={`lbl-${item.key}`}
                  className="analysis-pie-label"
                  x={cx + labelR * Math.cos(mid)}
                  y={cy + labelR * Math.sin(mid)}
                  textAnchor="middle"
                  dominantBaseline="middle"
                >
                  {`${Math.round(fraction * 100)}%`}
                </text>
              ))}
          </svg>
        )}
        <div className="analysis-pie-center">
          <b>{group.annotated_count ?? 0}</b>
          <small>{group.label || ""}</small>
        </div>
      </div>

      <div className="analysis-pie-legend">
        {items.length ? (
          items.map((item, index) => {
            const percent = analysisPiePercent(item.count, sum);
            const color = item.color || palette[index % palette.length];
            const isHover = hoveredKey === item.key;
            return (
              <div
                key={item.key}
                className={`analysis-pie-legend-row${isHover ? " is-hover" : ""}`}
                data-pie-key={item.key}
                onPointerEnter={(e) => {
                  setHoveredKey(item.key);
                  onShowTooltip(e, item, percent);
                }}
                onPointerMove={(e) => onShowTooltip(e, item, percent)}
                onPointerLeave={() => {
                  setHoveredKey(null);
                  onHideTooltip();
                }}
              >
                <span className="analysis-pie-swatch" style={{ background: color }} />
                <span className="analysis-pie-legend-line">
                  <strong>{item.label}</strong>
                  <small>{`${item.count}, ${percent}%`}</small>
                </span>
              </div>
            );
          })
        ) : (
          <div className="analysis-donut-empty">{bilingual(lang, "暂无数据", "No data")}</div>
        )}
      </div>
    </div>
  );
};

function ChartDetailLink({ href, label, count, lang }: { href: string; label: string; count: number; lang: UiLanguage }) {
  const name = bilingual(lang, `查看「${label}」的 ${count} 条明细`, `View ${count} ${count === 1 ? "record" : "records"} for ${label}`);
  return <a className="chart-detail-link" href={href} title={name} aria-label={name}><span aria-hidden="true">→</span></a>;
}

export interface GtUpdateCounts {
  all?: number;
  ready?: number;
  blocked?: number;
}

export const AnalysisGtCard: React.FC<{
  counts: GtUpdateCounts | null | undefined;
  detailHref?: (bucket: string) => string;
  prefix: "labelSummary" | "analysis";
  lang: UiLanguage;
  onOpenRules: () => void;
  onShowTooltip: (
    event: React.PointerEvent,
    item: AnalysisPieItem,
    percent: number,
  ) => void;
  onHideTooltip: () => void;
}> = ({ counts, prefix, lang, detailHref, onOpenRules, onShowTooltip, onHideTooltip }) => {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  const total = Number(counts?.all || 0);
  const ready = Number(counts?.ready || 0);
  const blocked = Number(counts?.blocked || 0);

  const items: AnalysisPieItem[] = useMemo(
    () => [
      {
        key: "gt_ready",
        label: bilingual(lang, "GT 待更新", "GT to update"),
        count: ready,
        color: "var(--chart-blue)",
      },
      {
        key: "gt_blocked",
        label: bilingual(lang, "需确认", "Needs attention"),
        count: blocked,
        description: bilingual(
          lang,
          "标注尚未齐备、来源冲突，或裁决需重新确认；暂不作为 GT 更新候选。",
          "Incomplete labels, conflicting sources or a stale decision; not yet eligible for a GT update.",
        ),
        color: "var(--chart-indigo)",
      },
      {
        key: "gt_aligned",
        label: bilingual(lang, "与 GT 一致", "Matches GT"),
        count: Math.max(0, total - ready - blocked),
        color: "var(--chart-teal)",
      },
    ],
    [lang, ready, blocked, total],
  );

  const size = 120;
  const cx = size / 2;
  const cy = size / 2;
  const outer = size * 0.46;
  const inner = size * 0.2;
  const labelR = (outer + inner) / 2;
  const { arcs } = useMemo(() => analysisPieArcs(items), [items]);

  const pctStr = (item: AnalysisPieItem) =>
    total ? `${analysisPiePercent(item.count, total)}%` : "—";
  const accessible = `${bilingual(
    lang,
    "当前筛选内已提交的 Issue",
    "Submitted Issues in the current filters",
  )}: ${total}; ${items.map((item) => `${item.label} ${item.count} (${pctStr(item)})`).join("; ")}`;

  return (
    <section className="page-card analysis-gt-card" aria-labelledby={`${prefix}GtTitle`}>
      <div className="section-heading analysis-review-status-heading">
        <div className="analysis-gt-title">
          <h3 id={`${prefix}GtTitle`}>{bilingual(lang, "GT 更新", "GT updates")}</h3>
          <button
            className="text-link label-summary-rules-button"
            id={`${prefix}GtRules`}
            type="button"
            aria-haspopup="dialog"
            aria-label={bilingual(lang, "GT 更新统计口径", "GT update counting rules")}
            onClick={onOpenRules}
          >
            ⓘ
          </button>
        </div>
        <small>
          {bilingual(
            lang,
            `当前筛选 · Issue 标注 ${total} 个`,
            `Current filters · ${total} Issue ${total === 1 ? "annotation" : "annotations"}`,
          )}
        </small>
      </div>

      <div
        className="analysis-pie-group analysis-gt-chart"
        id={`${prefix}GtChart`}
        role="group"
        aria-label={accessible}
      >
        <div className="analysis-pie-figure">
          {!arcs.length ? (
            <svg
              className="analysis-pie-svg"
              viewBox={`0 0 ${size} ${size}`}
              width={size}
              height={size}
              aria-hidden="true"
            >
              <circle
                className="analysis-pie-empty-ring"
                cx={cx}
                cy={cy}
                r={(outer + inner) / 2}
                fill="none"
                strokeWidth={outer - inner}
              />
            </svg>
          ) : (
            <svg
              className="analysis-pie-svg"
              viewBox={`0 0 ${size} ${size}`}
              width={size}
              height={size}
              role="img"
            >
              {arcs.map(({ item, index, start, end }) => {
                const percent = total ? analysisPiePercent(item.count, total) : 0;
                const isHover = hoveredKey === item.key;
                return (
                  <path
                    key={item.key}
                    className={`analysis-pie-slice${isHover ? " is-hover" : ""}`}
                    data-pie-index={index}
                    data-pie-key={item.key}
                    d={analysisDonutSlicePath(cx, cy, outer, inner, start, end)}
                    fill={item.color}
                    onPointerEnter={(e) => {
                      setHoveredKey(item.key);
                      onShowTooltip(e, item, percent);
                    }}
                    onPointerMove={(e) => onShowTooltip(e, item, percent)}
                    onPointerLeave={() => {
                      setHoveredKey(null);
                      onHideTooltip();
                    }}
                  />
                );
              })}
              {arcs
                .filter(({ fraction }) => fraction >= 0.1)
                .map(({ item, mid, fraction }) => (
                  <text
                    key={`lbl-${item.key}`}
                    className="analysis-pie-label"
                    x={cx + labelR * Math.cos(mid)}
                    y={cy + labelR * Math.sin(mid)}
                    textAnchor="middle"
                    dominantBaseline="middle"
                  >
                    {`${Math.round(fraction * 100)}%`}
                  </text>
                ))}
            </svg>
          )}
          <div className="analysis-pie-center">
            <b>{pctStr(items[0])}</b>
            <small>{bilingual(lang, "待更新", "To update")}</small>
          </div>
        </div>

        <div className="analysis-pie-legend">
          {items.map((item) => {
            const percent = total ? analysisPiePercent(item.count, total) : 0;
            const isHover = hoveredKey === item.key;
            return (
              <div
                key={item.key}
                className={`analysis-pie-legend-row${isHover ? " is-hover" : ""}`}
                title={item.description || item.label}
                data-pie-key={item.key}
                tabIndex={detailHref ? undefined : 0}
                onPointerEnter={(e) => {
                  setHoveredKey(item.key);
                  onShowTooltip(e, item, percent);
                }}
                onPointerMove={(e) => onShowTooltip(e, item, percent)}
                onPointerLeave={() => {
                  setHoveredKey(null);
                  onHideTooltip();
                }}
              >
                <span className="analysis-pie-swatch" style={{ background: item.color }} />
                <span className="analysis-pie-legend-line">
                  <strong>{item.label}</strong>
                  <small>{`${item.count} · ${pctStr(item)}`}</small>
                </span>
                {detailHref && <ChartDetailLink href={detailHref(item.key.slice(3))} label={item.label} count={item.count} lang={lang} />}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
};

export interface StatusSegmentItem {
  key: string;
  cssKey: string;
  label: string;
  count: number;
  description: string;
}

export const AnalysisStatusBar: React.FC<{
  statuses: StatusSegmentItem[];
  detailHref?: (status: string) => string;
  lang?: UiLanguage;
  emptyText: string;
}> = ({ statuses, emptyText, detailHref, lang = "zh" }) => {
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const total = statuses.reduce((sum, item) => sum + item.count, 0);
  const ariaSummary = statuses
    .map((item) => `${item.label} ${item.count}, ${analysisPiePercent(item.count, total)}%`)
    .join("; ");

  return (
    <div
      className={`analysis-review-status-visual${activeKey ? " has-hover" : ""}`}
      onPointerLeave={() => setActiveKey(null)}
    >
      <div className="analysis-review-status-bar" role="img" aria-label={ariaSummary}>
        {total ? (
          statuses
            .filter((item) => item.count > 0)
            .map((item) => {
              const percent = analysisPiePercent(item.count, total);
              return (
                <span
                  key={item.key}
                  className={`analysis-review-status-segment status-${item.cssKey}${
                    activeKey === item.key ? " is-hover" : ""
                  }`}
                  data-review-status-key={item.key}
                  style={{ width: `${percent}%` }}
                  title={`${item.label}: ${item.count}, ${percent}%`}
                  onPointerEnter={() => setActiveKey(item.key)}
                />
              );
            })
        ) : (
          <span className="analysis-review-status-empty">{emptyText}</span>
        )}
      </div>

      <div className="analysis-review-status-legend" role="list">
        {statuses.map((item) => {
          const percent = analysisPiePercent(item.count, total);
          return (
            <div
              key={item.key}
              className={`analysis-review-status-legend-item status-${item.cssKey}${
                activeKey === item.key ? " is-hover" : ""
              }`}
              data-review-status-key={item.key}
              role="listitem"
              tabIndex={detailHref ? undefined : 0}
              aria-label={`${item.label}: ${item.count}, ${percent}%. ${item.description}`}
              title={item.description}
              onPointerEnter={() => setActiveKey(item.key)}
              onFocus={() => setActiveKey(item.key)}
              onBlur={() => setActiveKey(null)}
            >
              <span className="analysis-review-status-swatch" />
              <span className="analysis-review-status-legend-copy">
                <strong>{item.label}</strong>
                <small>{`${item.count} · ${percent}%`}</small>
              </span>
              {detailHref && <ChartDetailLink href={detailHref(item.key)} label={item.label} count={item.count} lang={lang} />}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export interface ConfusionTableRow {
  gtLabel: string;
  cells: Array<{
    colLabel: string;
    count: number;
    tone: "match" | "mismatch" | "none" | "";
    title: string;
  }>;
  total: number;
}

export const AnalysisConfusionTable: React.FC<{
  cornerHeader: string;
  columnLabels: string[];
  rows: ConfusionTableRow[];
  totalLabel: string;
  columnTotals?: number[];
  grandTotal?: number;
}> = ({ cornerHeader, columnLabels, rows, totalLabel, columnTotals, grandTotal }) => {
  const [hoverCell, setHoverCell] = useState<{ row: number; col: number | "total" } | null>(null);

  return (
    <table
      className={`analysis-confusion-table${hoverCell ? " has-hover" : ""}`}
      onPointerLeave={() => setHoverCell(null)}
    >
      <thead>
        <tr>
          <th>{cornerHeader}</th>
          {columnLabels.map((label, colIndex) => (
            <th
              key={colIndex}
              scope="col"
              className={hoverCell?.col === colIndex ? "is-related" : undefined}
            >
              {label}
            </th>
          ))}
          <th
            scope="col"
            className={hoverCell?.col === "total" ? "is-related" : undefined}
          >
            {totalLabel}
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, rowIndex) => (
          <tr key={row.gtLabel}>
            <th
              scope="row"
              className={hoverCell?.row === rowIndex ? "is-related" : undefined}
            >
              {row.gtLabel}
            </th>
            {row.cells.map((cell, colIndex) => {
              const isHover = hoverCell?.row === rowIndex && hoverCell?.col === colIndex;
              const isRelated =
                !isHover &&
                hoverCell != null &&
                (hoverCell.row === rowIndex || hoverCell.col === colIndex);
              const toneClass = cell.tone ? `confusion-${cell.tone}` : "";
              return (
                <td
                  key={colIndex}
                  className={[
                    toneClass,
                    isHover ? "is-hover" : "",
                    isRelated ? "is-related" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  tabIndex={0}
                  title={cell.title}
                  onPointerEnter={() => setHoverCell({ row: rowIndex, col: colIndex })}
                  onFocus={() => setHoverCell({ row: rowIndex, col: colIndex })}
                  onBlur={() => setHoverCell(null)}
                >
                  {cell.count}
                </td>
              );
            })}
            <td
              className={[
                "confusion-total",
                hoverCell?.row === rowIndex && hoverCell?.col === "total" ? "is-hover" : "",
                hoverCell &&
                !(hoverCell.row === rowIndex && hoverCell.col === "total") &&
                (hoverCell.row === rowIndex || hoverCell.col === "total")
                  ? "is-related"
                  : "",
              ]
                .filter(Boolean)
                .join(" ")}
              tabIndex={0}
              title={`${row.gtLabel}: ${row.total}`}
              onPointerEnter={() => setHoverCell({ row: rowIndex, col: "total" })}
              onFocus={() => setHoverCell({ row: rowIndex, col: "total" })}
              onBlur={() => setHoverCell(null)}
            >
              {row.total}
            </td>
          </tr>
        ))}
      </tbody>
      {columnTotals && (
        <tfoot>
          <tr>
            <th>{totalLabel}</th>
            {columnTotals.map((total, colIndex) => (
              <td
                key={colIndex}
                className={`confusion-total${hoverCell?.col === colIndex ? " is-related" : ""}`}
              >
                {total}
              </td>
            ))}
            <td className="confusion-total">{grandTotal ?? 0}</td>
          </tr>
        </tfoot>
      )}
    </table>
  );
};

export const LabelSummaryRulesDialog: React.FC<{
  mode: null | "gt" | "expected";
  lang: UiLanguage;
  onClose: () => void;
}> = ({ mode, lang, onClose }) => {
  if (!mode) return null;

  if (mode === "gt") {
    return (
      <ModalDialog
        open
        title={bilingual(lang, "GT 更新规则", "GT update rules")}
        lang={lang}
        onClose={onClose}
        footer={
          <button className="button button-quiet" type="button" onClick={onClose}>
            {bilingual(lang, "知道了", "Got it")}
          </button>
        }
      >
        <ol className="label-summary-gt-rules">
          <li>
            {bilingual(
              lang,
              "汇总当前 Issue 的全部任务结果和任务外标注。有效的 Issue 裁决优先。",
              "Combine all task results and annotations outside tasks. A valid Issue decision takes precedence.",
            )}
          </li>
          <li>
            {bilingual(
              lang,
              "没有 Issue 裁决时，全部来源必须完成且结论一致。",
              "Without an Issue decision, all sources must be complete and agree.",
            )}
          </li>
          <li>
            {bilingual(
              lang,
              "结论与当前 GT 不同，或 GT 未设置：计入 GT 待更新。",
              "A result that differs from current GT, or fills a missing GT, counts as GT to update.",
            )}
          </li>
          <li>
            {bilingual(
              lang,
              "来源冲突、标注未齐或裁决过期：计入需确认。",
              "Conflicts, incomplete labels or stale decisions count as Needs attention.",
            )}
          </li>
          <li>
            {bilingual(
              lang,
              "任务筛选只限定 Issue 范围，GT 更新仍依据全部来源。GT 一致后，刷新即可更新统计。",
              "A task filter limits Issue membership; GT eligibility still considers all sources. After GT matches, refresh to update these percentages.",
            )}
          </li>
        </ol>
        <p className="dialog-copy">
          {bilingual(
            lang,
            "查看图表不会修改 GT。导出沿用现有权限和审核流程。",
            "Viewing this chart does not change GT. Export keeps the existing permissions and review workflow.",
          )}
        </p>
      </ModalDialog>
    );
  }

  return (
    <ModalDialog
      open
      wide
      title={bilingual(lang, "期望输出规则", "Expected result rules")}
      lang={lang}
      onClose={onClose}
      footer={
        <button className="button button-quiet" type="button" onClick={onClose}>
          {bilingual(lang, "知道了", "Got it")}
        </button>
      }
    >
      <p className="dialog-copy">
        {bilingual(
          lang,
          "先形成任务结果，再汇总为 Case 的最终结果。",
          "Task results are formed first, then combined into the final Case result.",
        )}
      </p>
      <div
        className="label-summary-flow"
        role="group"
        aria-label={bilingual(lang, "期望输出裁决流程", "Expected result decision flow")}
      >
        <section className="label-summary-flow-lane">
          <h3>
            <span>1</span> {bilingual(lang, "任务内", "Within task")}
          </h3>
          <div className="label-summary-flow-input">
            {bilingual(lang, "分配人员各自的最新提交", "Each assignee's latest submission")}
          </div>
          <div className="label-summary-flow-branches">
            <div className="label-summary-flow-branch">
              <span>{bilingual(lang, "有有效任务裁决", "Valid task decision")}</span>
              <span aria-hidden="true">→</span>
              <strong className="is-final">{bilingual(lang, "采用任务裁决", "Use task decision")}</strong>
            </div>
            <div className="label-summary-flow-branch">
              <span>{bilingual(lang, "无裁决 · 提交齐全且一致", "No decision · complete & unanimous")}</span>
              <span aria-hidden="true">→</span>
              <strong>{bilingual(lang, "采用标注结果", "Use label result")}</strong>
            </div>
            <div className="label-summary-flow-branch">
              <span>{bilingual(lang, "缺提交 / 冲突 / 裁决过期", "Missing / conflict / stale")}</span>
              <span aria-hidden="true">→</span>
              <strong className="is-pending">{bilingual(lang, "待处理", "Pending")}</strong>
            </div>
          </div>
          <small>{bilingual(lang, "选定单个任务时，只看这一层。", "When filtering one task, only this layer applies.")}</small>
        </section>

        <section className="label-summary-flow-lane">
          <h3>
            <span>2</span> {bilingual(lang, "全部标注", "All annotations")}
          </h3>
          <div className="label-summary-flow-input">
            {bilingual(lang, "各任务结果 + 任务外标注", "All task results + standalone annotations")}
          </div>
          <div className="label-summary-flow-branches">
            <div className="label-summary-flow-branch">
              <span>{bilingual(lang, "有有效 Issue 裁决", "Valid Issue decision")}</span>
              <span aria-hidden="true">→</span>
              <strong className="is-final">{bilingual(lang, "采用 Issue 裁决", "Use Issue decision")}</strong>
            </div>
            <div className="label-summary-flow-branch">
              <span>{bilingual(lang, "无裁决 · 所有来源有效且一致", "No decision · all sources agree")}</span>
              <span aria-hidden="true">→</span>
              <strong>{bilingual(lang, "采用一致结果", "Use consensus")}</strong>
            </div>
            <div className="label-summary-flow-branch">
              <span>{bilingual(lang, "未完成 / 冲突 / 裁决过期", "Incomplete / conflict / stale")}</span>
              <span aria-hidden="true">→</span>
              <strong className="is-pending">{bilingual(lang, "待处理", "Pending")}</strong>
            </div>
          </div>
          <small>{bilingual(lang, "先完成任务内结果，才能做 Issue 裁决。", "Complete task results before Issue adjudication.")}</small>
        </section>
      </div>

      <section className="label-summary-rule-examples">
        <h3>{bilingual(lang, "三个案例，一眼看懂", "Three quick examples")}</h3>
        <div className="label-summary-example">
          <h4>{bilingual(lang, "① 双人一致", "① Dual consensus")}</h4>
          <div className="label-summary-example-flow">
            <div className="label-summary-example-node example-votes">
              <div>
                <span>甲</span>
                <LabelBadge label="误触发" />
              </div>
              <div>
                <span>乙</span>
                <LabelBadge label="误触发" />
              </div>
            </div>
            <span className="label-summary-example-arrow" aria-hidden="true">→</span>
            <div className="label-summary-example-node example-action">
              <strong>{bilingual(lang, "多人一致", "Consensus")}</strong>
              <small>{bilingual(lang, "提交齐全", "Complete")}</small>
            </div>
            <span className="label-summary-example-arrow" aria-hidden="true">→</span>
            <div className="label-summary-example-node example-output">
              <small>{bilingual(lang, "期望输出", "Expected")}</small>
              <LabelBadge label="误触发" />
            </div>
          </div>
        </div>

        <div className="label-summary-example">
          <h4>{bilingual(lang, "② 任务内冲突", "② In-task conflict")}</h4>
          <div className="label-summary-example-flow">
            <div className="label-summary-example-node example-votes">
              <div>
                <span>甲</span>
                <LabelBadge label="误触发" />
              </div>
              <div>
                <span>乙</span>
                <LabelBadge label="正确触发" />
              </div>
            </div>
            <span className="label-summary-example-arrow" aria-hidden="true">→</span>
            <div className="label-summary-example-node example-action">
              <strong>{bilingual(lang, "任务内裁决", "Task decision")}</strong>
              <small>{bilingual(lang, "丙 · 原始冲突保留", "C · conflict preserved")}</small>
            </div>
            <span className="label-summary-example-arrow" aria-hidden="true">→</span>
            <div className="label-summary-example-node example-output">
              <small>{bilingual(lang, "该任务期望输出", "Task result")}</small>
              <LabelBadge label="正确触发" />
            </div>
          </div>
        </div>

        <div className="label-summary-example">
          <h4>{bilingual(lang, "③ 跨任务冲突", "③ Cross-task conflict")}</h4>
          <div className="label-summary-example-flow">
            <div className="label-summary-example-node example-votes">
              <div>
                <span>{bilingual(lang, "任务 A", "Task A")}</span>
                <LabelBadge label="误触发" />
              </div>
              <div>
                <span>{bilingual(lang, "任务 B", "Task B")}</span>
                <LabelBadge label="正确触发" />
              </div>
            </div>
            <span className="label-summary-example-arrow" aria-hidden="true">→</span>
            <div className="label-summary-example-node example-action">
              <strong>{bilingual(lang, "Issue 裁决", "Issue decision")}</strong>
              <small>{bilingual(lang, "丁 · 任务原结果保留", "D · task results kept")}</small>
            </div>
            <span className="label-summary-example-arrow" aria-hidden="true">→</span>
            <div className="label-summary-example-node example-output">
              <small>{bilingual(lang, "全部标注期望输出", "Overall result")}</small>
              <LabelBadge label="无需协助" />
            </div>
          </div>
        </div>
      </section>
      <p className="label-summary-rules-note">
        {bilingual(
          lang,
          "来源变化 → 裁决需重新确认；GT 仅作对照。",
          "Source changes mark decisions stale; GT is for reference only.",
        )}
      </p>
    </ModalDialog>
  );
};
