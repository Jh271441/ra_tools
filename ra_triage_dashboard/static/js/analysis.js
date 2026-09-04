/* ra_triage_dashboard/static/js/analysis.js
 * Review reason analysis page
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function selectedAnalysisExclusionFilter() {
  const values = parseFilterList(getMultiFilterValues($("#analysisExclusionFilter")));
  if (values.length === 1 && ["included", "excluded"].includes(values[0])) {
    return values[0];
  }
  return "all";
}

function analysisExclusionLabel(value) {
  return {
    all: uiText("全部（含问题排除）", "All (including shielded)"),
    included: uiText("不含问题排除", "Exclude shielded cases"),
    excluded: uiText("仅问题排除", "Only shielded cases"),
  }[value] || uiText("全部（含问题排除）", "All (including shielded)");
}

async function loadClusters() {
  const params = new URLSearchParams();
  if (state.selectedRunId) params.set("model_run_id", state.selectedRunId);
  params.set("failure_only", String(Boolean(state.failureOnly && state.selectedRunId)));
  const annotationAuthor = joinFilterList(
    typeof reviewerFilterSelection === "function"
      ? reviewerFilterSelection("review")
      : getMultiFilterValues($("#reviewerFilter"))
  );
  if (annotationAuthor) params.set("annotation_author", annotationAuthor);
  // The exclusion slice belongs to 原因聚类/分析.  Review's quick cluster
  // chips should keep the neutral all-inclusive scope even if a previous
  // analysis page selection is still present in the shared DOM.
  const exclusion = state.activePage === "analysis"
    ? selectedAnalysisExclusionFilter()
    : "all";
  if (exclusion !== "all") params.set("exclusion", exclusion);
  const list = $("#clusterList");
  if (!list) return;
  const data = await api(`/api/review-clusters?${params.toString()}`);
  if (!(data.items || []).length) {
    list.innerHTML = `<span class="muted">${escapeHtml(t("analysis.cluster_hint"))}</span>`;
    return;
  }
  list.innerHTML = data.items
    .map(
      (item) => `<button type="button" class="cluster-chip ${state.clusterKey === item.key ? "active" : ""}" data-cluster-key="${escapeHtml(item.key)}">
        <span>${escapeHtml(evidenceLabel(item.key))}</span><b>${item.count}</b>
      </button>`
    )
    .join("");
  list.querySelectorAll("[data-cluster-key]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.clusterKey = button.dataset.clusterKey === state.clusterKey ? "" : button.dataset.clusterKey;
      await reloadReviewGallery({ includeOverview: false });
    });
  });
}

function safeSameOriginReviewUrl(url) {
  try {
    const parsed = new URL(String(url || ""), window.location.origin);
    const pathname = stripBasePath(parsed.pathname);
    if (parsed.origin !== window.location.origin || pathname !== "/review") return "";
    return `${withBase(pathname)}${parsed.search}`;
  } catch {
    return "";
  }
}

function reviewStatusLabel(status) {
  return (
    {
      pending: t("status.pending"),
      reviewed: t("status.matches_gt"),
      needs_gt_review: t("status.needs_gt"),
    }[status] || status || t("status.recorded")
  );
}

function analysisRequestOptions() {
  const runId = $("#analysisRunFilter")?.value || "";
  return currentAnalysisRouteOptions({
    runId,
    comparisonStatus: runId ? checkedAnalysisComparisonStatus() : "all",
    exclusion: selectedAnalysisExclusionFilter(),
  });
}

/** Shared query builder for analysis JSON + export endpoints. */
function buildAnalysisQueryParams({ format = "", includePagination = true } = {}) {
  const options = analysisRequestOptions();
  const params = new URLSearchParams();
  if (format) params.set("format", format);
  if (options.runId) params.set("model_run_id", options.runId);
  params.set(
    "comparison",
    options.runId
      ? comparisonStatusParam(options.comparisonStatus || "all")
      : "all"
  );
  const fields = [
    ["annotation_author", joinFilterList(options.annotationAuthor)],
    ["review_status", joinFilterList(options.reviewStatus)],
    ["gt_label", joinFilterList(options.gtLabel)],
    ["model_label", joinFilterList(options.modelLabel)],
    ["missing_evidence", joinFilterList(options.missingEvidence)],
    ["scene_tag", joinFilterList(options.sceneTag)],
    ["trigger_tag", joinFilterList(options.triggerTag)],
    ["egress_tag", joinFilterList(options.egressTag)],
    ["search", options.search || ""],
  ];
  if (options.exclusion && options.exclusion !== "all") {
    params.set("exclusion", options.exclusion);
  }
  for (const [key, value] of fields) {
    if (value) params.set(key, value);
  }
  if (includePagination) {
    params.set("page", String(Math.max(1, Number(options.page) || 1)));
    params.set("page_size", String(state.reviewAnalysis.pageSize));
  }
  appendBaselineParams(params);
  return params;
}

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
  const rows = (items || []).filter((item) => Number(item.count) > 0);
  const sum = rows.reduce((acc, item) => acc + Number(item.count || 0), 0);
  if (!sum) return { arcs: [], sum: 0 };
  let angle = -Math.PI / 2;
  const arcs = rows.map((item, index) => {
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
      const color = palette[index % palette.length];
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

function renderAnalysisReviewStatus(data) {
  const target = $("#analysisReviewStatusChart");
  const summaryTarget = $("#analysisReviewStatusSummary");
  if (!target) return;
  const counts = data.summary?.review_status_counts || {};
  const statuses = [
    {
      key: "pending",
      label: reviewStatusLabel("pending"),
      count: Number(counts.pending || 0),
      description: uiText(
        "未填写期望输出，或 Tags 没有唯一推断",
        "Expected output is missing or Tags have no unique inference"
      ),
    },
    {
      key: "reviewed",
      label: reviewStatusLabel("reviewed"),
      count: Number(counts.reviewed || 0),
      description: uiText(
        "期望输出与当前 GT 一致",
        "Expected output matches the current GT"
      ),
    },
    {
      key: "needs_gt_review",
      label: reviewStatusLabel("needs_gt_review"),
      count: Number(counts.needs_gt_review || 0),
      description: uiText(
        "期望输出与当前 GT 不一致",
        "Expected output differs from the current GT"
      ),
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

function renderAnalysisCases(data) {
  const target = $("#analysisCaseList");
  const items = data.items || [];
  $("#analysisCaseSummary").textContent =
    t("analysis.case_summary", { total: data.total || 0, n: items.length });
  if (!items.length) {
    target.innerHTML =
      `<div class="analysis-empty">${escapeHtml(t("analysis.case_empty"))}</div>`;
  } else {
    target.innerHTML = items
      .map((item) => {
        const annotation = item.annotation || {};
        const prediction = item.prediction || {};
        const expectedOutput = annotationExpectedOutput(annotation);
        const reviewUrl = safeSameOriginReviewUrl(item.review_url);
        const voyagerUrl = safeUrl(item.voyager_issue_url);
        const issueId = escapeHtml(item.issue_id);
        const sceneLabel = item.title || item.scenario || t("analysis.no_scene");
        const issueIdMarkup = voyagerUrl
          ? `<a class="analysis-issue-link" href="${escapeHtml(voyagerUrl)}" target="_blank" rel="noreferrer" title="在 Voyager 中打开 ${issueId}">${issueId}</a>`
          : `<strong>${issueId}</strong>`;
        const comparisonStatus = normalizedAnalysisComparisonStatus(
          item.comparison_status,
          ""
        );
        const comparisonMeta = ANALYSIS_COMPARISON_META[comparisonStatus];
        const comparisonBadge = comparisonMeta
          ? `<span class="analysis-comparison-badge comparison-${comparisonStatus}" title="${escapeHtml(comparisonMeta.description)}">${escapeHtml(comparisonMeta.label)}${
              comparisonStatus === "none" ? t("analysis.no_pred") : ""
            }</span>`
          : "";
        const confidence =
          prediction.confidence === null || prediction.confidence === undefined
            ? ""
            : ` · ${(Number(prediction.confidence) * 100).toFixed(1)}%`;
        const evidenceChips = (annotation.missing_evidence || [])
          .map(
            (key) =>
              `<span class="analysis-chip evidence-chip">${escapeHtml(evidenceLabel(key))}</span>`
          )
          .join("");
        const tagChips = (annotation.tags || [])
          .map((key) => {
            const catalogItem = reviewTagCatalogItem(key) || {};
            const section = String(catalogItem.section || "");
            const group = String(catalogItem.group || "");
            return `<span class="analysis-chip tag-chip"${section ? ` data-tag-section="${escapeHtml(section)}"` : ""}${group ? ` data-tag-group="${escapeHtml(group)}"` : ""}>${escapeHtml(tagLabel(key))}</span>`;
          })
          .join("");
        return `<article class="analysis-case-row">
          <div class="analysis-case-identity">
            ${issueIdMarkup}
            <span title="${escapeHtml(sceneLabel)}">${escapeHtml(sceneLabel)}</span>
          </div>
          <div class="analysis-case-labels">
            ${comparisonBadge}
            <span title="${escapeHtml(`${baselineLabelForScope(item.baseline_scope)} GT`)}">GT ${labelBadge(item.gt_label)}</span>
            <span title="人工 Review 期望输出"><span class="ui-lang-zh">期望</span><span class="ui-lang-en">Expected</span> ${labelBadge(expectedOutput, uiText("待补充", "Pending"))}</span>
            <button class="analysis-model-history-button" type="button"
              data-analysis-model-history="${issueId}"
              title="查看此 Issue 的全部评测 Run 输出历史"
              aria-label="查看 ${issueId} 的评测 Run 输出历史">
              <span>${escapeHtml(t("analysis.model"))}</span>${labelBadge(prediction.label, "未输出")}${escapeHtml(confidence)}
            </button>
          </div>
          <div class="analysis-case-reason">
            <strong class="${annotation.note ? "" : "reason-empty"}">${escapeHtml(annotation.note || t("analysis.empty_reason"))}</strong>
            ${prediction.reason ? `<p>${escapeHtml(t("analysis.model_note", { note: prediction.reason }))}</p>` : ""}
            <div class="analysis-chip-list">${tagChips}${evidenceChips}</div>
          </div>
          <div class="analysis-case-meta">
            <span>${escapeHtml(annotation.author || "未记录复核人")}${annotation.author_verified ? " · SSO" : ""}</span>
            <span>${escapeHtml(reviewStatusLabel(annotation.review_status))} · ${formatTime(annotation.created_at)}</span>
            <span class="analysis-case-actions">
              <button class="analysis-discussion-link" type="button" data-analysis-discussion="${issueId}" data-model-run-id="${escapeHtml(state.selectedRunId || "")}">评论</button>
              ${reviewUrl ? `<a class="text-link" href="${escapeHtml(reviewUrl)}" title="打开问题详情与 Review">问题详情</a>` : ""}
            </span>
          </div>
        </article>`;
      })
      .join("");
    target.querySelectorAll("[data-analysis-model-history]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (button.getAttribute("aria-busy") === "true") return;
        button.setAttribute("aria-busy", "true");
        try {
          const caseData = await api(
            `/api/cases/${encodeURIComponent(button.dataset.analysisModelHistory)}`
          );
          openHistoryDialog("model", caseData);
        } catch (error) {
          showToast(error.message, true);
        } finally {
          button.removeAttribute("aria-busy");
        }
      });
    });
    target.querySelectorAll("[data-analysis-discussion]").forEach((button) => {
      button.addEventListener("click", () => {
        openAnalysisDiscussion(button.dataset.analysisDiscussion).catch((error) => {
          showToast(error.message, true);
        });
      });
    });
  }
  const page = Number(data.page || 1);
  const pageCount = Number(data.page_count || 1);
  const pageSize = CASE_PAGE_SIZES.includes(Number(data.page_size))
    ? Number(data.page_size)
    : state.reviewAnalysis.pageSize;
  state.reviewAnalysis.pageSize = pageSize;
  $("#analysisPageSummary").textContent = `${page} / ${pageCount}`;
  $("#analysisPageSize").value = String(pageSize);
  $("#analysisPagePrevious").disabled = page <= 1;
  $("#analysisPageNext").disabled = page >= pageCount;
  const jumpInput = $("#analysisPageJump");
  const jumpButton = $("#analysisPageJumpButton");
  if (jumpInput) {
    const focused = document.activeElement === jumpInput;
    jumpInput.min = "1";
    jumpInput.max = String(Math.max(1, pageCount));
    jumpInput.disabled = pageCount <= 1;
    jumpInput.dataset.pageCount = String(Math.max(1, pageCount));
    if (!focused) jumpInput.value = String(page);
  }
  if (jumpButton) jumpButton.disabled = pageCount <= 1;
}

async function openAnalysisDiscussion(
  issueId,
  {
    runId = state.selectedRunId || "",
    source = "analysis",
    focusCommentId = 0,
    intentDatasetId = "",
    intentCaseId = "",
  } = {}
) {
  const isIntentDiscussion = Boolean(intentDatasetId && intentCaseId);
  clearAnalysisDiscussionImages();
  const normalizedRunId = String(runId || "");
  state.analysisDiscussion = {
    kind: isIntentDiscussion ? "intent" : "review",
    issueId,
    runId: normalizedRunId,
    source,
    intentDatasetId: String(intentDatasetId || ""),
    intentCaseId: String(intentCaseId || ""),
    replyTo: null,
    comments: [],
    pendingImages: [],
    preview: false,
  };
  const discussionTitle = $("#analysisDiscussionTitle");
  const discussionTitleZh = discussionTitle?.querySelector(".ui-lang-zh");
  const discussionTitleEn = discussionTitle?.querySelector(".ui-lang-en");
  if (discussionTitleZh) discussionTitleZh.textContent = isIntentDiscussion ? "意图标注讨论" : "评论";
  if (discussionTitleEn) discussionTitleEn.textContent = isIntentDiscussion ? "Intent discussion" : "Comments";
  $("#analysisDiscussionContext").textContent = isIntentDiscussion
    ? `${intentDatasetId} · ${issueId}`
    : `${issueId} · ${runId || "未绑定 Run"}`;
  const textarea = $("#analysisDiscussionNote");
  textarea.value = "";
  textarea.hidden = false;
  $("#analysisDiscussionPreview").hidden = true;
  $("[data-comment-preview-toggle]").textContent = "预览";
  renderAnalysisDiscussionImages();
  const canWriteIntentDiscussion = !isIntentDiscussion || Boolean(state.session?.can_annotate_intent);
  $("#analysisDiscussionComposer").hidden = Boolean(state.session?.read_only) || !canWriteIntentDiscussion;
  $("#analysisDiscussionSubmit").hidden = Boolean(state.session?.read_only) || !canWriteIntentDiscussion;
  document.querySelectorAll("[data-comment-image]").forEach((button) => {
    button.hidden = isIntentDiscussion;
  });
  const imageInput = $("#analysisDiscussionImageInput");
  if (imageInput) imageInput.disabled = isIntentDiscussion;
  $("#analysisDiscussionImages").hidden = isIntentDiscussion;
  renderAnalysisDiscussionReplyContext();
  $("#analysisDiscussionThread").innerHTML =
    `<div class="comment-thread-empty">正在加载评论…</div>`;
  bindReviewMentionComposer(textarea, $("#analysisDiscussionMentionComposer"));
  updateReviewMentionComposer(textarea, $("#analysisDiscussionMentionComposer"));
  $("#analysisDiscussionDialog").showModal();
  const result = isIntentDiscussion
    ? await api(`/api/intent-datasets/${encodeURIComponent(intentDatasetId)}/cases/${encodeURIComponent(intentCaseId)}/comments`)
    : await api(`/api/cases/${encodeURIComponent(issueId)}/comments?model_run_id=${encodeURIComponent(normalizedRunId)}`);
  if (
    !state.analysisDiscussion
    || state.analysisDiscussion.issueId !== issueId
    || state.analysisDiscussion.intentCaseId !== String(intentCaseId || "")
  ) return;
  state.analysisDiscussion.comments = result.comments || [];
  if (isIntentDiscussion && state.intentLabeling?.caseId === String(intentCaseId)) {
    state.intentLabeling.caseData ||= {};
    state.intentLabeling.caseData.collaboration ||= {};
    state.intentLabeling.caseData.collaboration.comments = state.analysisDiscussion.comments;
    if (typeof renderIntentCollaboration === "function") renderIntentCollaboration();
  }
  renderAnalysisDiscussionThread();
  updateAnalysisDiscussionCount(issueId, normalizedRunId, Number(result.count || 0));
  if (focusCommentId) {
    const focused = $("#analysisDiscussionThread")?.querySelector(
      `[data-comment-id="${Number(focusCommentId)}"]`
    );
    focused?.classList.add("is-deep-linked");
    focused?.scrollIntoView({ block: "center" });
  }
  // Keep the shared shortcut/focus behavior consistent for read-only intent
  // viewers: only focus the composer when it is actually available.
  if (!$("#analysisDiscussionComposer")?.hidden) textarea.focus();
}

function clearAnalysisDiscussionImages() {
  const images = state.analysisDiscussion?.pendingImages || [];
  images.forEach((item) => {
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
  });
  if (state.analysisDiscussion) state.analysisDiscussion.pendingImages = [];
  const input = $("#analysisDiscussionImageInput");
  if (input) input.value = "";
  renderAnalysisDiscussionImages();
}

function insertAnalysisDiscussionText(before, after = "", placeholder = "") {
  const textarea = $("#analysisDiscussionNote");
  if (!textarea) return;
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? start;
  const selected = textarea.value.slice(start, end) || placeholder;
  textarea.setRangeText(`${before}${selected}${after}`, start, end, "end");
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  textarea.focus();
}

function applyAnalysisDiscussionFormat(kind) {
  if (kind === "bold") return insertAnalysisDiscussionText("**", "**", "粗体文字");
  if (kind === "italic") return insertAnalysisDiscussionText("*", "*", "斜体文字");
  if (kind === "code") return insertAnalysisDiscussionText("`", "`", "code");
  if (kind === "link") return insertAnalysisDiscussionText("[", "](https://)", "链接文字");
  const textarea = $("#analysisDiscussionNote");
  if (!textarea) return;
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? start;
  const selected = textarea.value.slice(start, end) || (kind === "quote" ? "引用内容" : "列表项");
  const prefix = kind === "quote" ? "> " : "- ";
  const replacement = selected.split("\n").map((line) => `${prefix}${line}`).join("\n");
  textarea.setRangeText(replacement, start, end, "end");
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  textarea.focus();
}

function addAnalysisDiscussionImages(files) {
  const context = state.analysisDiscussion;
  if (!context) return;
  if (context.kind === "intent") {
    showToast("意图标注讨论暂不支持图片附件，请使用 Markdown 文本。", true);
    return;
  }
  const limits = state.config?.review_attachment_limits || {};
  const maxCount = Number(limits.max_count || 4);
  const maxBytes = Number(limits.max_bytes_each || 8 * 1024 * 1024);
  const maxTotalBytes = Number(limits.max_bytes_total || 24 * 1024 * 1024);
  const allowed = new Set(limits.media_types || ["image/png", "image/jpeg", "image/webp"]);
  let rejected = "";
  [...files].forEach((file) => {
    if (context.pendingImages.length >= maxCount) return void (rejected = `每条评论最多 ${maxCount} 张图片。`);
    if (!allowed.has(file.type)) return void (rejected = "仅支持 PNG、JPEG 或 WebP 图片。");
    if (file.size > maxBytes) return void (rejected = "单张图片不能超过 8 MB。");
    const total = context.pendingImages.reduce((sum, item) => sum + item.file.size, 0);
    if (total + file.size > maxTotalBytes) return void (rejected = "本次图片总大小不能超过 24 MB。");
    const randomId = crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    const token = `pending-${String(randomId).replace(/[^A-Za-z0-9-]/g, "-")}`;
    const item = { token, file, previewUrl: URL.createObjectURL(file) };
    context.pendingImages.push(item);
    const safeAlt = String(file.name || "评论图片").replace(/[\]\n]/g, "").slice(0, 80);
    const textarea = $("#analysisDiscussionNote");
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    const separator = start > 0 && !textarea.value.slice(0, start).endsWith("\n") ? "\n" : "";
    textarea.setRangeText(`${separator}![${safeAlt}](attachment:${token})\n`, start, end, "end");
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
  renderAnalysisDiscussionImages();
  if (context.preview) renderAnalysisDiscussionPreview();
  if (rejected) showToast(rejected, true);
}

function renderAnalysisDiscussionImages() {
  const target = $("#analysisDiscussionImages");
  if (!target) return;
  const images = state.analysisDiscussion?.pendingImages || [];
  target.innerHTML = images.map((item) => `
    <div class="comment-pending-image">
      <img src="${escapeHtml(item.previewUrl)}" alt="${escapeHtml(item.file.name || "待上传图片")}" />
      <span>${escapeHtml(item.file.name || "图片")}</span>
      <button type="button" data-remove-comment-image="${escapeHtml(item.token)}" aria-label="移除图片">×</button>
    </div>`).join("");
  target.querySelectorAll("[data-remove-comment-image]").forEach((button) => {
    button.addEventListener("click", () => {
      const context = state.analysisDiscussion;
      const index = context?.pendingImages?.findIndex((item) => item.token === button.dataset.removeCommentImage) ?? -1;
      if (!context || index < 0) return;
      const [item] = context.pendingImages.splice(index, 1);
      URL.revokeObjectURL(item.previewUrl);
      const textarea = $("#analysisDiscussionNote");
      const escapedToken = item.token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      textarea.value = textarea.value.replace(
        new RegExp(`!?\\[[^\\]\\n]*\\]\\(attachment:${escapedToken}\\)\\n?`, "g"),
        ""
      );
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      renderAnalysisDiscussionImages();
    });
  });
}

function renderAnalysisDiscussionPreview() {
  const preview = $("#analysisDiscussionPreview");
  if (!preview) return;
  const attachments = (state.analysisDiscussion?.pendingImages || []).map((item) => ({
    id: item.token,
    url: item.previewUrl,
  }));
  preview.innerHTML = reviewCommentBodyMarkup($("#analysisDiscussionNote")?.value || "", attachments) ||
    `<span class="comment-markdown-empty">暂无可预览内容。</span>`;
}

function toggleAnalysisDiscussionPreview() {
  const context = state.analysisDiscussion;
  if (!context) return;
  context.preview = !context.preview;
  const textarea = $("#analysisDiscussionNote");
  const preview = $("#analysisDiscussionPreview");
  textarea.hidden = context.preview;
  preview.hidden = !context.preview;
  $("[data-comment-preview-toggle]").textContent = context.preview ? "继续编辑" : "预览";
  if (context.preview) renderAnalysisDiscussionPreview();
  else textarea.focus();
}

function bindAnalysisDiscussionEditor() {
  const textarea = $("#analysisDiscussionNote");
  const imageInput = $("#analysisDiscussionImageInput");
  if (!textarea || textarea.dataset.commentEditorBound === "1") return;
  textarea.dataset.commentEditorBound = "1";
  document.querySelectorAll("[data-comment-format]").forEach((button) => {
    button.addEventListener("click", () => applyAnalysisDiscussionFormat(button.dataset.commentFormat));
  });
  $("[data-comment-preview-toggle]")?.addEventListener("click", toggleAnalysisDiscussionPreview);
  $("[data-comment-image]")?.addEventListener("click", () => imageInput?.click());
  imageInput?.addEventListener("change", () => {
    addAnalysisDiscussionImages(imageInput.files || []);
    imageInput.value = "";
  });
  textarea.addEventListener("paste", (event) => {
    const images = [...(event.clipboardData?.files || [])].filter((file) => file.type.startsWith("image/"));
    if (!images.length) return;
    event.preventDefault();
    addAnalysisDiscussionImages(images);
  });
  textarea.addEventListener("input", () => {
    if (state.analysisDiscussion?.preview) renderAnalysisDiscussionPreview();
  });
}

function analysisDiscussionShareUrl(commentId) {
  const context = state.analysisDiscussion;
  if (context?.kind === "intent") {
    const intentUrl = new URL(withBase(PAGE_ROUTES.intent.path), window.location.origin);
    intentUrl.searchParams.set("dataset", String(context.intentDatasetId || ""));
    intentUrl.searchParams.set("case", String(context.intentCaseId || ""));
    intentUrl.searchParams.set("comments", "1");
    intentUrl.searchParams.set("comment", String(Number(commentId)));
    return intentUrl.href;
  }
  const url = new URL(withBase(PAGE_ROUTES.review.path), window.location.origin);
  url.searchParams.set("issue", String(context?.issueId || ""));
  if (context?.runId) url.searchParams.set("run", String(context.runId));
  url.searchParams.set("comments", "1");
  url.searchParams.set("comment", String(Number(commentId)));
  return url.href;
}

async function shareAnalysisDiscussionComment(commentId) {
  const url = analysisDiscussionShareUrl(commentId);
  if (navigator.share) {
    try {
      await navigator.share({ title: "RA Triage 评论", url });
      return;
    } catch (error) {
      if (error?.name === "AbortError") return;
    }
  }
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(url);
  } else {
    const input = document.createElement("textarea");
    input.value = url;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.append(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }
  showToast("评论链接已复制。");
}

function updateAnalysisDiscussionCount(issueId, runId, count) {
  document.querySelectorAll("[data-analysis-discussion], [data-trail-update-discussion], [data-intent-discussion]").forEach((button) => {
    if (button.hasAttribute("data-intent-discussion")) {
      const intent = state.analysisDiscussion;
      if (
        intent?.kind !== "intent"
        || String(button.dataset.intentDatasetId || "") !== String(intent.intentDatasetId || "")
        || String(button.dataset.intentCaseId || "") !== String(intent.intentCaseId || "")
      ) return;
      button.innerHTML = count > 0
        ? `打开讨论 · ${count} <kbd>D</kbd>`
        : "打开讨论 <kbd>D</kbd>";
      return;
    }
    const buttonIssue = button.dataset.analysisDiscussion || button.dataset.trailUpdateDiscussion;
    if (String(buttonIssue || "") !== String(issueId || "")) return;
    if (String(button.dataset.modelRunId || "") !== String(runId || "")) return;
    button.textContent = count > 0 ? `评论 · ${count}` : "评论";
  });
}

function renderAnalysisDiscussionThread() {
  const context = state.analysisDiscussion;
  const target = $("#analysisDiscussionThread");
  if (!target || !context) return;
  const comments = context.comments || [];
  if (!comments.length) {
    target.innerHTML = `<div class="comment-thread-empty">还没有评论，可以发起第一条讨论。</div>`;
    return;
  }
  target.innerHTML = comments.map((comment) => {
    const replyExcerpt = String(comment.reply_to_body || "")
      .replace(/!\[[^\]\n]*\]\([^\n)]+\)/g, "[图片]")
      .replace(/\[([^\]\n]+)\]\(https?:\/\/[^\s)]+\)/g, "$1")
      .replace(/^\s*(?:#{1,3}|>|[-+*]|\d+[.)])\s+/gm, "")
      .replace(/[*_~`]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 120);
    const replyContext = comment.reply_to_id
      ? `<div class="comment-reply-quote">回复 ${escapeHtml(reviewMentionDisplayName(comment.reply_to_author || "评论人"))}：${escapeHtml(replyExcerpt)}</div>`
      : "";
    return `<article class="comment-thread-item" data-comment-id="${Number(comment.id)}">
      <div class="comment-thread-meta">
        <strong>${escapeHtml(reviewMentionDisplayName(comment.author || "unknown"))}</strong>
        <span>${comment.author_verified ? "SSO · " : ""}${escapeHtml(formatTime(comment.created_at))}</span>
      </div>
      ${replyContext}
      <div class="comment-thread-body">${reviewCommentBodyMarkup(comment.body || "", comment.attachments || [])}</div>
      <div class="comment-thread-actions">
        <button class="analysis-discussion-link" type="button" data-comment-share="${Number(comment.id)}">分享</button>
        ${state.session?.read_only || (context.kind === "intent" && !state.session?.can_annotate_intent) ? "" : `<button class="analysis-discussion-link" type="button" data-comment-reply="${Number(comment.id)}">回复</button>`}
      </div>
    </article>`;
  }).join("");
  target.querySelectorAll("[data-comment-reply]").forEach((button) => {
    button.addEventListener("click", () =>
      beginAnalysisDiscussionReply(Number(button.dataset.commentReply))
    );
  });
  target.querySelectorAll("[data-comment-share]").forEach((button) => {
    button.addEventListener("click", () => {
      shareAnalysisDiscussionComment(Number(button.dataset.commentShare)).catch((error) => showToast(error.message, true));
    });
  });
  target.scrollTop = target.scrollHeight;
}

function beginAnalysisDiscussionReply(commentId) {
  const context = state.analysisDiscussion;
  const comment = context?.comments?.find(
    (item) => Number(item.id) === Number(commentId)
  );
  if (!context || !comment) return;
  context.replyTo = comment;
  const textarea = $("#analysisDiscussionNote");
  const prefix = `@${comment.author} `;
  if (!String(textarea.value || "").trim()) textarea.value = prefix;
  renderAnalysisDiscussionReplyContext();
  updateReviewMentionComposer(textarea, $("#analysisDiscussionMentionComposer"));
  textarea.focus();
  textarea.setSelectionRange(textarea.value.length, textarea.value.length);
}

function renderAnalysisDiscussionReplyContext() {
  const target = $("#analysisDiscussionReplyContext");
  const reply = state.analysisDiscussion?.replyTo;
  if (!target) return;
  target.hidden = !reply;
  target.innerHTML = reply
    ? `<span>正在回复 <strong>${escapeHtml(reviewMentionDisplayName(reply.author || "unknown"))}</strong></span><button type="button" data-cancel-comment-reply>取消回复</button>`
    : "";
  target.querySelector("[data-cancel-comment-reply]")?.addEventListener("click", () => {
    if (state.analysisDiscussion) state.analysisDiscussion.replyTo = null;
    renderAnalysisDiscussionReplyContext();
  });
}

async function saveAnalysisDiscussion(event) {
  event.preventDefault();
  const context = state.analysisDiscussion;
  const discussion = String($("#analysisDiscussionNote")?.value || "").trim();
  if (!context?.issueId || !discussion) {
    showToast("请输入讨论内容。", true);
    return;
  }
  const author = String(state.session?.username || "").trim();
  const submit = event.submitter;
  if (submit) submit.disabled = true;
  try {
    const payload = {
      model_run_id: String(context.runId || ""),
      body: discussion,
      reply_to_id: context.replyTo?.id || null,
      author,
    };
    let result;
    if (context.kind === "intent") {
      result = await api(
        `/api/intent-datasets/${encodeURIComponent(context.intentDatasetId)}/cases/${encodeURIComponent(context.intentCaseId)}/comments`,
        {
          method: "POST",
          body: JSON.stringify({
            body: discussion,
            reply_to_id: context.replyTo?.id || null,
          }),
        }
      );
    } else if (context.pendingImages?.length) {
      const form = new FormData();
      payload.attachment_tokens = context.pendingImages.map((item) => item.token);
      form.append("payload", JSON.stringify(payload));
      context.pendingImages.forEach((item, index) => {
        form.append("attachments", item.file, item.file.name || `comment-${index + 1}.png`);
      });
      result = await api(`/api/cases/${encodeURIComponent(context.issueId)}/comments-with-attachments`, {
        method: "POST",
        body: form,
        headers: { "X-RA-Triage-Request": "comment-v1" },
      });
    } else {
      result = await api(`/api/cases/${encodeURIComponent(context.issueId)}/comments`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    acknowledgeLocalChange(result);
    context.comments.push(result.comment);
    if (context.kind === "intent" && state.intentLabeling?.caseId === context.intentCaseId) {
      state.intentLabeling.caseData ||= {};
      state.intentLabeling.caseData.collaboration ||= {};
      state.intentLabeling.caseData.collaboration.comments = context.comments;
      if (typeof renderIntentCollaboration === "function") renderIntentCollaboration();
    }
    context.replyTo = null;
    $("#analysisDiscussionNote").value = "";
    clearAnalysisDiscussionImages();
    context.preview = false;
    $("#analysisDiscussionNote").hidden = false;
    $("#analysisDiscussionPreview").hidden = true;
    $("[data-comment-preview-toggle]").textContent = "预览";
    renderAnalysisDiscussionReplyContext();
    updateReviewMentionComposer(
      $("#analysisDiscussionNote"),
      $("#analysisDiscussionMentionComposer")
    );
    renderAnalysisDiscussionThread();
    updateAnalysisDiscussionCount(
      context.issueId,
      context.runId,
      Number(result.comment_count || context.comments.length)
    );
    const queued = result?.notification?.queued?.length || 0;
    showToast(`评论已发表${queued ? `；DChat 通知已排队 ${queued} 人` : ""}。`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    if (submit) submit.disabled = false;
  }
}

function bindAnalysisDiscussionEnterSubmit() {
  const textarea = $("#analysisDiscussionNote");
  const form = $("#analysisDiscussionForm");
  const submit = $("#analysisDiscussionSubmit");
  if (!textarea || !form || textarea.dataset.enterSubmitBound === "1") return;
  textarea.dataset.enterSubmitBound = "1";
  textarea.addEventListener("keydown", (event) => {
    if (
      event.defaultPrevented
      || event.isComposing
      || event.key !== "Enter"
      || event.shiftKey
    ) return;
    event.preventDefault();
    if (!submit?.disabled) form.requestSubmit(submit);
  });
}

function renderReviewReasonAnalysis(data, { animatePies = true } = {}) {
  const summary = data.summary || {};
  state.reviewAnalysis.page = Number(data.page || 1);
  $("#analysisReviewCount").textContent = summary.latest_reviews ?? 0;
  $("#analysisReasonCount").textContent = summary.with_reason ?? 0;
  $("#analysisEmptyReasonCount").textContent = uiText(
    `${summary.empty_reason ?? 0} 条未填写`,
    `${summary.empty_reason ?? 0} empty`
  );
  $("#analysisEvidenceCount").textContent = summary.with_structured_evidence ?? 0;
  const run = data.scope?.model_run;
  const comparisonStatus = comparisonStatusParam(
    data.scope?.comparison_status || "all"
  );
  const comparisonLabels = parseComparisonStatuses(comparisonStatus)
    .map((status) => ANALYSIS_COMPARISON_META[status]?.label || status)
    .join(" / ");
  const exclusion = data.scope?.exclusion || "all";
  const exclusionSuffix = exclusion === "all" ? "" : ` · ${analysisExclusionLabel(exclusion)}`;
  const reviewScope = run
    ? `${run.name}${comparisonStatus === "all" ? "" : ` · ${comparisonLabels}`}${exclusionSuffix}`
    : `${uiText("全部最新 Review", "All latest reviews")}${exclusionSuffix}`;
  $("#analysisReviewScope").textContent = reviewScope;
  $("#analysisReviewScope").title = reviewScope;
  renderAnalysisReviewStatus(data);
  renderAnalysisClusterPanels(data, { animatePies });
  renderAnalysisConfusion(data);
  renderAnalysisCases(data);
}

function paintAnalysisFromCache() {
  const data = state.reviewAnalysis?.data;
  if (!data) return false;
  // A cached response may belong to a different history entry (for example,
  // page 2 while popstate just restored page 1). Rendering that response must
  // not overwrite the pagination parsed from the current URL before the
  // revalidation request is built.
  const requestedPage = state.reviewAnalysis.page;
  const requestedPageSize = state.reviewAnalysis.pageSize;
  // Quiet repaint when revisiting the tab — pie spin is for real data loads only.
  renderReviewReasonAnalysis(data, { animatePies: false });
  state.reviewAnalysis.page = requestedPage;
  state.reviewAnalysis.pageSize = requestedPageSize;
  return true;
}

/**
 * Enter/revisit the analysis page: paint cache immediately (if any), then revalidate.
 * Used by sidebar navigation and popstate so tab switches stay snappy without blanking.
 */
async function enterAnalysisPage({ includeOverview = false } = {}) {
  if (!state.config) return;
  const painted = paintAnalysisFromCache();
  const loads = [loadReviewReasonAnalysis({ keepPainted: painted })];
  if (includeOverview) loads.push(loadOverview());
  await Promise.all(loads);
}

async function loadReviewReasonAnalysis({ keepPainted = false } = {}) {
  const requestSeq = ++state.reviewAnalysis.requestSeq;
  const params = buildAnalysisQueryParams({ includePagination: true });
  // Keep existing paint when revisiting the tab; avoid blanking for a snappier switch.
  if (!keepPainted) {
    $("#analysisCaseSummary").textContent = "正在加载最新 Review…";
  }
  const data = await api(`/api/review-reason-analysis?${params.toString()}`);
  if (requestSeq !== state.reviewAnalysis.requestSeq) return;
  state.reviewAnalysis.data = data;
  // Spin on first paint / filter reloads; skip when quietly revalidating a painted tab.
  renderReviewReasonAnalysis(data, { animatePies: !keepPainted });
}

function downloadReviewAnalysis(format) {
  const params = buildAnalysisQueryParams({
    format,
    includePagination: false,
  });
  const link = document.createElement("a");
  link.href = withBase(`/api/review-reason-analysis/export?${params.toString()}`);
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function applyAnalysisComparisonSelection() {
  const previousRunId = state.selectedRunId;
  const previousFailureOnly = state.failureOnly;
  const previousComparisonStatus = state.reviewAnalysis.comparisonStatus;
  const runId = $("#analysisRunFilter").value;
  state.selectedRunId = state.modelRuns.some((run) => run.id === runId) ? runId : "";
  state.reviewAnalysis.comparisonStatus = state.selectedRunId
    ? checkedAnalysisComparisonStatus()
    : "all";
  state.failureOnly = Boolean(
    state.selectedRunId &&
      state.reviewAnalysis.comparisonStatus === "mismatch"
  );
  if (
    previousRunId !== state.selectedRunId ||
    previousFailureOnly !== state.failureOnly ||
    previousComparisonStatus !== state.reviewAnalysis.comparisonStatus
  ) {
    state.reviewQueueStale = true;
  }
  $("#modelRunFilter").value = state.selectedRunId;
  setReviewComparisonStatus(state.reviewComparisonStatus, {
    hasRun: Boolean(state.selectedRunId),
  });
  renderActiveRun();
  renderRunManager();
}

async function reloadReviewAnalysis({ historyMode = "push" } = {}) {
  applyAnalysisComparisonSelection();
  showPage("analysis", { historyMode });
  await Promise.all([loadReviewReasonAnalysis(), loadOverview()]);
}

function scheduleAnalysisFilterReload(delay = 0) {
  if (state.reviewAnalysis.filterTimer) {
    window.clearTimeout(state.reviewAnalysis.filterTimer);
  }
  state.reviewAnalysis.filterTimer = window.setTimeout(() => {
    state.reviewAnalysis.filterTimer = null;
    state.reviewAnalysis.page = 1;
    reloadReviewAnalysis({ historyMode: "replace" }).catch((error) => {
      showToast(error.message, true);
    });
  }, Math.max(0, Number(delay) || 0));
}

async function changeAnalysisPage(delta) {
  const data = state.reviewAnalysis.data || {};
  const target = Math.max(
    1,
    Math.min(Number(data.page_count || 1), state.reviewAnalysis.page + delta)
  );
  if (target === state.reviewAnalysis.page) return;
  state.reviewAnalysis.page = target;
  showPage("analysis", { historyMode: "push" });
  await loadReviewReasonAnalysis();
  window.scrollTo({ top: $("#analysisCaseList").offsetTop - 72, behavior: "smooth" });
}

async function jumpToAnalysisPage(raw) {
  const pageCount = Math.max(
    1,
    Number(state.reviewAnalysis.data?.page_count) || 1
  );
  const input = $("#analysisPageJump");
  const text = String(raw ?? "").trim();
  if (!/^\d+$/.test(text)) {
    showToast(t("analysis.jump_range", { total: pageCount }), true);
    if (input) {
      input.value = String(state.reviewAnalysis.page);
      input.focus();
      input.select();
    }
    return;
  }
  const target = Number.parseInt(text, 10);
  if (!Number.isFinite(target) || target < 1 || target > pageCount) {
    showToast(t("analysis.jump_range", { total: pageCount }), true);
    if (input) {
      input.value = String(state.reviewAnalysis.page);
      input.focus();
      input.select();
    }
    return;
  }
  if (target === state.reviewAnalysis.page) {
    if (input) input.value = String(target);
    return;
  }
  state.reviewAnalysis.page = target;
  showPage("analysis", { historyMode: "push" });
  await loadReviewReasonAnalysis();
  window.scrollTo({ top: $("#analysisCaseList").offsetTop - 72, behavior: "smooth" });
}

async function changeAnalysisPageSize(value) {
  const nextPageSize = CASE_PAGE_SIZES.includes(Number(value))
    ? Number(value)
    : DEFAULT_CASE_PAGE_SIZE;
  if (nextPageSize === state.reviewAnalysis.pageSize) return;
  state.reviewAnalysis.pageSize = nextPageSize;
  state.reviewAnalysis.page = 1;
  showPage("analysis", { historyMode: "push" });
  await loadReviewReasonAnalysis();
  window.scrollTo({ top: $("#analysisCaseList").offsetTop - 72, behavior: "smooth" });
}

function clearDetail({ showGallery = true } = {}) {
  if (typeof cancelCaseHydration === "function") cancelCaseHydration();
  state.selectedId = "";
  state.selectedCase = null;
  state.caseRequestSeq += 1;
  $("#detailPane").innerHTML = `
    <div class="empty-state">
      <div class="empty-glyph" aria-hidden="true">+</div>
      <h2>正在准备 Issue 详情</h2>
      <p>从筛选结果中打开一个 Issue 后，这里会显示 BEV / Camera 与模型输出。</p>
    </div>`;
  $("#reviewPane").innerHTML = `
    <div class="review-placeholder"><h2>人工复核</h2><p>选择 Issue 后记录结论和模型遗漏的关键信息。</p></div>`;
  renderCaseNavigation();
  if (showGallery) setReviewView("");
}
