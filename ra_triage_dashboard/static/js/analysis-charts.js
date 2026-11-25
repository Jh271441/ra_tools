/* analysis-charts.js
 * Review summary charts, palettes and linked hover interactions.
 * Classic script; shared globals are initialized before bind-bootstrap.js.
 */

// Cool theme-aligned palettes (no warm reds/ambers).
// Dark: brighter cyan for black stage. Light: deeper tones so slices don't glow on white.
const ANALYSIS_PIE_BASE_DARK = [
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
];
// Light: cool cyan/teal/blue/slate only — avoid purple/indigo (too loud on white).
const ANALYSIS_PIE_BASE_LIGHT = [
  "#0e7490", // deep accent cyan
  "#0369a1", // sky-700
  "#0f766e", // teal-700
  "#0891b2", // cyan-600
  "#0284c7", // sky-600
  "#0d9488", // teal-600
  "#155e75", // cyan-800
  "#1e3a5f", // deep navy-blue
  "#475569", // slate-600
  "#64748b", // slate-500
];

function analysisPieBaseColors() {
  const theme =
    state?.colorTheme ||
    document.documentElement.dataset.colorTheme ||
    "dark";
  return theme === "light" ? ANALYSIS_PIE_BASE_LIGHT : ANALYSIS_PIE_BASE_DARK;
}

function analysisPiePalette(panelKey) {
  const base = analysisPieBaseColors();
  const offsets = { evidence: 0, scene: 5, trigger: 2, egress: 1 };
  const start = offsets[panelKey] || 0;
  return [...base.slice(start), ...base.slice(0, start)];
}

const ANALYSIS_PIE_COLORS = ANALYSIS_PIE_BASE_DARK;

function analysisPieArcs(items) {
  // Keep palette positions stable when zero-count categories have no arc.
  const rows = (items || []).map((item, index) => ({ item, index }))
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

function analysisDonutSlicePath(cx, cy, outer, inner, start, end) {
  const large = end - start > Math.PI ? 1 : 0;
  const polar = (r, a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
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

function analysisPiePercent(item, sum) {
  // Pie-relative share so legend angles sum to ~100% (matches reference charts).
  if (!sum) return 0;
  return Math.round((Number(item.count || 0) / sum) * 1000) / 10;
}

function hideAnalysisPieTooltip() {
  const tip = $("#analysisPieTooltip");
  if (tip) tip.hidden = true;
}

function showAnalysisPieTooltip(event, item, percent) {
  let tip = $("#analysisPieTooltip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "analysisPieTooltip";
    tip.className = "analysis-pie-tooltip";
    document.body.appendChild(tip);
  }
  const desc = item.description ? `<small>${escapeHtml(item.description)}</small>` : "";
  tip.innerHTML = `<strong>${escapeHtml(item.label)}</strong>
    <span>${escapeHtml(t("analysis.count_pct", { n: item.count, p: percent }))}</span>
    ${desc}`;
  tip.hidden = false;
  const pad = 12;
  const rect = tip.getBoundingClientRect();
  let left = event.clientX + pad;
  let top = event.clientY + pad;
  if (left + rect.width > window.innerWidth - 8) left = event.clientX - rect.width - pad;
  if (top + rect.height > window.innerHeight - 8) top = event.clientY - rect.height - pad;
  tip.style.left = `${Math.max(8, left)}px`;
  tip.style.top = `${Math.max(8, top)}px`;
}

function renderAnalysisPieSvg(
  items,
  { size = 148, palette = ANALYSIS_PIE_COLORS, animatePies = true } = {}
) {
  const cx = size / 2;
  const cy = size / 2;
  // Thicker ring + smaller hole so the center label sits tighter.
  const outer = size * 0.46;
  const inner = size * 0.20;
  const pieClass = animatePies ? "analysis-pie-svg is-enter" : "analysis-pie-svg";
  const { arcs, sum } = analysisPieArcs(items);
  if (!arcs.length) {
    const mid = (outer + inner) / 2;
    return `<svg class="${pieClass}" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" aria-hidden="true">
      <circle class="analysis-pie-empty-ring" cx="${cx}" cy="${cy}" r="${mid}" fill="none" stroke-width="${outer - inner}" />
    </svg>`;
  }
  const slices = arcs
    .map(({ item, index, start, end }) => {
      const color = item.color || palette[index % palette.length];
      const percent = analysisPiePercent(item, sum);
      return `<path class="analysis-pie-slice" data-pie-index="${index}"
        data-pie-key="${escapeHtml(item.key)}"
        data-pie-label="${escapeHtml(item.label)}"
        data-pie-count="${item.count}"
        data-pie-percent="${percent}"
        data-pie-desc="${escapeHtml(item.description || "")}"
        d="${analysisDonutSlicePath(cx, cy, outer, inner, start, end)}"
        fill="${color}"></path>`;
    })
    .join("");
  // Percent labels sit on the ring mid-radius when the arc is large enough.
  const labelR = (outer + inner) / 2;
  const labels = arcs
    .filter(({ fraction }) => fraction >= 0.1)
    .map(({ mid, fraction }) => {
      const x = cx + labelR * Math.cos(mid);
      const y = cy + labelR * Math.sin(mid);
      const percent = Math.round(fraction * 100);
      return `<text class="analysis-pie-label" x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle">${percent}%</text>`;
    })
    .join("");
  return `<svg class="${pieClass}" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img">
    ${slices}${labels}
  </svg>`;
}

function renderAnalysisClusterGroup(group, panel, { dual = false, animatePies = true } = {}) {
  const items = group.items || [];
  const size = dual ? 120 : 150;
  const palette = analysisPiePalette(panel?.key);
  const { sum } = analysisPieArcs(items);
  const legend = items.length
    ? items
        .map((item, index) => {
          const percent = analysisPiePercent(item, sum);
          const color = palette[index % palette.length];
          return `<div class="analysis-pie-legend-row"
              data-pie-key="${escapeHtml(item.key)}"
              data-pie-label="${escapeHtml(item.label)}"
              data-pie-count="${item.count}"
              data-pie-percent="${percent}"
              data-pie-desc="${escapeHtml(item.description || "")}">
            <span class="analysis-pie-swatch" style="background:${color}"></span>
            <span class="analysis-pie-legend-line">
              <strong>${escapeHtml(item.label)}</strong>
              <small>${item.count}, ${percent}%</small>
            </span>
          </div>`;
        })
        .join("")
    : `<div class="analysis-donut-empty">${escapeHtml(t("analysis.no_data"))}</div>`;
  return `<div class="analysis-pie-group ${dual ? "is-dual" : "is-single"}">
    <div class="analysis-pie-figure" data-group-label="${escapeHtml(group.label || "")}">
      ${renderAnalysisPieSvg(items, { size, palette, animatePies })}
      <div class="analysis-pie-center">
        <b>${group.annotated_count ?? 0}</b>
        <small>${escapeHtml(group.label || "")}</small>
      </div>
    </div>
    <div class="analysis-pie-legend">${legend}</div>
  </div>`;
}

function bindAnalysisPieHover(root) {
  const nodes = root.querySelectorAll(".analysis-pie-slice, .analysis-pie-legend-row");
  nodes.forEach((node) => {
    const payload = () => ({
      key: node.dataset.pieKey,
      label: node.dataset.pieLabel,
      count: Number(node.dataset.pieCount || 0),
      description: node.dataset.pieDesc || "",
      share: Number(node.dataset.piePercent || 0) / 100,
    });
    node.addEventListener("pointerenter", (event) => {
      const item = payload();
      const percent = Number(node.dataset.piePercent || 0);
      root
        .querySelectorAll(`[data-pie-key="${CSS.escape(item.key)}"]`)
        .forEach((el) => el.classList.add("is-hover"));
      showAnalysisPieTooltip(event, item, percent);
    });
    node.addEventListener("pointermove", (event) => {
      const item = payload();
      const percent = Number(node.dataset.piePercent || 0);
      showAnalysisPieTooltip(event, item, percent);
    });
    node.addEventListener("pointerleave", () => {
      const key = node.dataset.pieKey;
      root
        .querySelectorAll(`[data-pie-key="${CSS.escape(key)}"]`)
        .forEach((el) => el.classList.remove("is-hover"));
      hideAnalysisPieTooltip();
    });
  });
}

function renderAnalysisClusterPanels(data, { animatePies = true } = {}) {
  const target = $("#analysisClusterPanels");
  if (!target) return;
  hideAnalysisPieTooltip();
  const panels = data.cluster_panels || [];
  if (!panels.length) {
    const legacy = data.evidence_clusters || [];
    target.innerHTML = `<article class="page-card analysis-cluster-card">
      <div class="section-heading"><div><h3>缺失信息</h3></div></div>
      <div class="analysis-pie-groups single">${renderAnalysisClusterGroup(
        {
          key: "all",
          label: "缺失信息",
          annotated_count: data.summary?.with_structured_evidence || 0,
          items: legacy,
        },
        { key: "evidence", filter_kind: "evidence" },
        { animatePies }
      )}</div>
    </article>`;
  } else {
    target.innerHTML = panels
      .map((panel) => {
        const dual = panel.layout === "dual" || (panel.groups || []).length > 1;
        const groups = panel.groups || [];
        const body = groups.length
          ? groups
              .map((group) =>
                renderAnalysisClusterGroup(group, panel, { dual, animatePies })
              )
              .join("")
          : `<div class="analysis-empty">${escapeHtml(t("analysis.no_cluster"))}</div>`;
        return `<article class="page-card analysis-cluster-card layout-${escapeHtml(panel.layout || "single")}" data-panel="${escapeHtml(panel.key)}">
          <div class="section-heading">
            <div><h3>${escapeHtml(panel.label)}</h3></div>
          </div>
          <div class="analysis-pie-groups ${dual ? "dual" : "single"}">${body}</div>
        </article>`;
      })
      .join("");
  }
  bindAnalysisPieHover(target);
  clearAnalysisPieEnterAnimations(target);
}

function analysisGtChartItems(data) {
  const counts = data.gt_update_counts || {};
  const total = Number(counts.all || 0);
  const ready = Number(counts.ready || 0);
  const blocked = Number(counts.blocked || 0);
  return [
    { key: "gt_ready", label: uiText("GT 待更新", "GT to update"), count: ready, color: "var(--chart-blue)" },
    { key: "gt_blocked", label: uiText("需确认", "Needs attention"), count: blocked, description: uiText("标注尚未齐备、来源冲突，或裁决需重新确认；暂不作为 GT 更新候选。", "Incomplete labels, conflicting sources or a stale decision; not yet eligible for a GT update."), color: "var(--chart-indigo)" },
    { key: "gt_aligned", label: uiText("与 GT 一致", "Matches GT"), count: Math.max(0, total - ready - blocked), color: "var(--chart-teal)" },
  ];
}

function analysisGtChartMarkup(data, { prefix = "labelSummary" } = {}) {
  const items = analysisGtChartItems(data);
  const total = Number(data.gt_update_counts?.all || 0);
  const percent = (item) => total ? `${analysisPiePercent(item, total)}%` : "—";
  const label = uiText("当前筛选内已提交的 Issue", "Submitted Issues in the current filters");
  const accessible = `${label}: ${total}; ${items.map((item) => `${item.label} ${item.count} (${percent(item)})`).join("; ")}`;
  const legend = items.map((item) => `<div class="analysis-pie-legend-row" title="${escapeHtml(item.description || item.label)}" data-pie-desc="${escapeHtml(item.description || "")}" data-pie-key="${item.key}" data-pie-label="${escapeHtml(item.label)}" data-pie-count="${item.count}" data-pie-percent="${total ? analysisPiePercent(item, total) : 0}" tabindex="0"><span class="analysis-pie-swatch" style="background:${item.color}"></span><span class="analysis-pie-legend-line"><strong>${escapeHtml(item.label)}</strong><small>${item.count} · ${percent(item)}</small></span></div>`).join("");
  return `<section class="page-card analysis-gt-card" aria-labelledby="${prefix}GtTitle"><div class="section-heading analysis-review-status-heading"><div class="analysis-gt-title"><h3 id="${prefix}GtTitle">${uiText("GT 更新", "GT updates")}</h3><button class="text-link label-summary-rules-button" id="${prefix}GtRules" type="button" aria-haspopup="dialog" aria-label="${escapeHtml(uiText("GT 更新统计口径", "GT update counting rules"))}">ⓘ</button></div><small>${escapeHtml(uiText(`当前筛选 · Issue 标注 ${total} 个`, `Current filters · ${total} Issue ${total === 1 ? "annotation" : "annotations"}`))}</small></div><div class="analysis-pie-group analysis-gt-chart" id="${prefix}GtChart" role="group" aria-label="${escapeHtml(accessible)}"><div class="analysis-pie-figure">${renderAnalysisPieSvg(items, { size: 120, palette: items.map((item) => item.color), animatePies: false })}<div class="analysis-pie-center"><b>${percent(items[0])}</b><small>${uiText("待更新", "To update")}</small></div></div><div class="analysis-pie-legend">${legend}</div></div></section>`;
}

function renderAnalysisGtStatus(data) {
  const target = $("#analysisGtCardMount");
  if (!target) return;
  target.innerHTML = analysisGtChartMarkup(data, { prefix: "analysis" });
  $("#analysisGtRules")?.addEventListener("click", () => showLabelSummaryRules({ gt: true }));
  bindAnalysisPieHover($("#analysisGtChart"));
}

function renderAnalysisReviewStatus(data) {
  const target = $("#analysisReviewStatusChart");
  const summaryTarget = $("#analysisReviewStatusSummary");
  if (!target) return;
  const counts = data.summary?.model_review_status_counts || {};
  const statuses = [
    {
      key: "pending",
      label: reviewStatusLabel("pending"),
      count: Number(counts.pending || 0),
      description: uiText("尚未开始模型判错复核", "Model review has not started"),
    },
    {
      key: "in_progress",
      label: reviewStatusLabel("in_progress"),
      count: Number(counts.in_progress || 0) + Number(counts.blocked_by_label || 0),
      description: uiText("模型判错复核正在进行", "Model review is in progress"),
    },
    {
      key: "completed",
      label: reviewStatusLabel("completed"),
      count: Number(counts.completed || 0),
      description: uiText("模型判错复核已完成", "Model review is complete"),
    },
  ];
  const total = statuses.reduce((sum, item) => sum + item.count, 0);
  if (summaryTarget) {
    summaryTarget.textContent = uiText(
      `${total} 条 · 当前筛选范围`,
      `${total} reviews · current filter scope`
    );
  }
  const segments = total
    ? statuses
        .filter((item) => item.count > 0)
        .map((item) => {
          const percent = analysisPiePercent(item, total);
          return `<span class="analysis-review-status-segment status-${escapeHtml(item.key)}"
            data-review-status-key="${escapeHtml(item.key)}"
            style="width:${percent}%"
            title="${escapeHtml(`${item.label}: ${item.count}, ${percent}%`)}"></span>`;
        })
        .join("")
    : `<span class="analysis-review-status-empty">${escapeHtml(uiText("暂无 Review", "No reviews"))}</span>`;
  const legend = statuses
    .map((item) => {
      const percent = analysisPiePercent(item, total);
      return `<div class="analysis-review-status-legend-item status-${escapeHtml(item.key)}"
        data-review-status-key="${escapeHtml(item.key)}" role="listitem" tabindex="0"
        aria-label="${escapeHtml(`${item.label}: ${item.count}, ${percent}%. ${item.description}`)}"
        title="${escapeHtml(item.description)}">
        <span class="analysis-review-status-swatch"></span>
        <span class="analysis-review-status-legend-copy">
          <strong>${escapeHtml(item.label)}</strong>
          <small>${item.count} · ${percent}%</small>
        </span>
      </div>`;
    })
    .join("");
  const ariaSummary = statuses
    .map((item) => `${item.label} ${item.count}, ${analysisPiePercent(item, total)}%`)
    .join("; ");
  target.innerHTML = `<div class="analysis-review-status-visual">
    <div class="analysis-review-status-bar" role="img" aria-label="${escapeHtml(ariaSummary)}">${segments}</div>
    <div class="analysis-review-status-legend" role="list">${legend}</div>
  </div>`;
  bindAnalysisReviewStatusHover(target);
}

function clearAnalysisLinkedHover(root) {
  root?.classList.remove("has-hover");
  root
    ?.querySelectorAll(".is-hover, .is-related")
    .forEach((node) => node.classList.remove("is-hover", "is-related"));
}

function bindAnalysisLinkedHover(root, itemSelector, activate) {
  if (!root) return;
  let pointerItem = null;
  let focusItem = null;
  const paint = () => {
    const item = pointerItem || focusItem;
    clearAnalysisLinkedHover(root);
    if (!item || !root.contains(item)) return;
    root.classList.add("has-hover");
    activate(item);
  };
  const itemFromEvent = (event) => {
    const item = event.target?.closest?.(itemSelector);
    return item && root.contains(item) ? item : null;
  };
  root.addEventListener("pointerover", (event) => {
    pointerItem = itemFromEvent(event);
    paint();
  });
  root.addEventListener("pointerleave", () => {
    pointerItem = null;
    paint();
  });
  root.addEventListener("focusin", (event) => {
    focusItem = itemFromEvent(event);
    paint();
  });
  root.addEventListener("focusout", (event) => {
    if (root.contains(event.relatedTarget)) return;
    focusItem = null;
    paint();
  });
}

function bindAnalysisReviewStatusHover(root) {
  const visual = root?.querySelector(".analysis-review-status-visual");
  bindAnalysisLinkedHover(visual, "[data-review-status-key]", (node) => {
    const key = node.dataset.reviewStatusKey;
    visual
      .querySelectorAll(`[data-review-status-key="${CSS.escape(key)}"]`)
      .forEach((peer) => peer.classList.add("is-hover"));
  });
}

function clearAnalysisPieEnterAnimations(root) {
  root?.querySelectorAll(".analysis-pie-svg.is-enter").forEach((svg) => {
    const clear = () => svg.classList.remove("is-enter");
    svg.addEventListener("animationend", clear, { once: true });
    window.setTimeout(clear, 500);
  });
}

function renderAnalysisConfusion(data) {
  const target = $("#analysisConfusionMatrix");
  const summary = $("#analysisConfusionSummary");
  if (!target || !summary) return;
  const run = data.scope?.model_run;
  const confusion = data.confusion || {};
  if (!run) {
    summary.textContent = t("analysis.confusion_need_run");
    target.innerHTML = `<div class="analysis-empty">${escapeHtml(t("analysis.confusion_empty_run"))}</div>`;
    return;
  }
  summary.textContent =
    `${run.name} · ` +
    `MATCH ${confusion.matches || 0} · ` +
    `MISMATCH ${confusion.mismatches || 0} · ` +
    `NONE ${confusion.none || 0}`;
  const labels = confusion.model_labels || confusion.labels || LABELS;
  if (!confusion.total) {
    target.innerHTML =
      `<div class="analysis-empty">${escapeHtml(t("analysis.confusion_empty_slice"))}</div>`;
    return;
  }
  const columnHeaders = labels
    .map((label, columnIndex) => {
      const displayLabel = label === "NONE" ? uiText("未输出", "NONE") : label;
      return `<th scope="col" data-confusion-col="${columnIndex}">${escapeHtml(displayLabel)}</th>`;
    })
    .join("");
  target.innerHTML = `<table class="analysis-confusion-table">
    <thead><tr><th>${escapeHtml(t("analysis.gt_model_matrix"))}</th>${columnHeaders}<th scope="col" data-confusion-total-col>${escapeHtml(t("analysis.total_col"))}</th></tr></thead>
    <tbody>${(confusion.rows || [])
      .map(
        (row, rowIndex) => `<tr>
          <th scope="row" data-confusion-row="${rowIndex}">${escapeHtml(row.gt_label)}</th>
          ${(row.cells || [])
            .map(
              (cell, columnIndex) => {
                const cellClass =
                  cell.model_label === "NONE"
                    ? "confusion-none"
                    : modelLabelMatchesGt(cell.model_label, row.gt_label)
                      ? "confusion-match"
                      : cell.count
                        ? "confusion-mismatch"
                        : "";
                const displayModelLabel = cell.model_label === "NONE"
                  ? uiText("未输出", "NONE")
                  : cell.model_label;
                return `<td class="${cellClass}" data-confusion-row="${rowIndex}" data-confusion-col="${columnIndex}" tabindex="0"
                  title="${escapeHtml(`GT ${row.gt_label} · ${uiText("模型", "Model")} ${displayModelLabel}: ${cell.count}`)}">${cell.count}</td>`;
              }
            )
            .join("")}
          <td class="confusion-total" data-confusion-row="${rowIndex}" data-confusion-total tabindex="0"
            title="${escapeHtml(`${row.gt_label}: ${row.total}`)}">${row.total}</td>
        </tr>`
      )
      .join("")}</tbody>
  </table>`;
  bindAnalysisConfusionHover(target.querySelector(".analysis-confusion-table"));
}

function bindAnalysisConfusionHover(table) {
  bindAnalysisLinkedHover(table, "tbody td", (cell) => {
    const rowIndex = cell.dataset.confusionRow;
    const columnIndex = cell.dataset.confusionCol;
    if (rowIndex !== undefined) {
      table
        .querySelectorAll(`[data-confusion-row="${CSS.escape(rowIndex)}"]`)
        .forEach((node) => node.classList.add("is-related"));
    }
    if (columnIndex !== undefined) {
      table
        .querySelectorAll(`[data-confusion-col="${CSS.escape(columnIndex)}"]`)
        .forEach((node) => node.classList.add("is-related"));
    } else {
      table.querySelector("[data-confusion-total-col]")?.classList.add("is-related");
    }
    cell.classList.add("is-hover");
  });
}
