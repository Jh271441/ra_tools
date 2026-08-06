/* ra_triage_dashboard/static/js/analysis.js
 * Review reason analysis page
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
async function loadClusters() {
  const params = new URLSearchParams();
  if (state.selectedRunId) params.set("model_run_id", state.selectedRunId);
  params.set("failure_only", String(Boolean(state.failureOnly && state.selectedRunId)));
  const annotationAuthor = $("#reviewerFilter")?.value;
  if (annotationAuthor) params.set("annotation_author", annotationAuthor);
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
      pending: t("status.pending_review"),
      reviewed: t("status.reviewed"),
      needs_gt_review: t("status.needs_gt"),
    }[status] || status || t("status.recorded")
  );
}

function analysisRequestOptions() {
  const runId = $("#analysisRunFilter")?.value || "";
  return currentAnalysisRouteOptions({
    runId,
    comparisonStatus: runId ? checkedAnalysisComparisonStatus() : "all",
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
  target.innerHTML = `<table class="analysis-confusion-table">
    <thead><tr><th>${escapeHtml(t("analysis.gt_model_matrix"))}</th>${labels
      .map((label) => `<th>${escapeHtml(label)}</th>`)
      .join("")}<th>${escapeHtml(t("analysis.total_col"))}</th></tr></thead>
    <tbody>${(confusion.rows || [])
      .map(
        (row) => `<tr>
          <th>${escapeHtml(row.gt_label)}</th>
          ${(row.cells || [])
            .map(
              (cell) => {
                const cellClass =
                  cell.model_label === "NONE"
                    ? "confusion-none"
                    : cell.model_label === row.gt_label
                      ? "confusion-match"
                      : cell.count
                        ? "confusion-mismatch"
                        : "";
                return `<td class="${cellClass}">${cell.count}</td>`;
              }
            )
            .join("")}
          <td class="confusion-total">${row.total}</td>
        </tr>`
      )
      .join("")}</tbody>
  </table>`;
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
            <span title="0508 baseline GT">GT ${labelBadge(item.gt_label)}</span>
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
  $("#analysisReviewScope").textContent = run
    ? `${run.name}${comparisonStatus === "all" ? "" : ` · ${comparisonLabels}`}`
    : uiText("全部最新 Review", "All latest reviews");
  renderAnalysisClusterPanels(data, { animatePies });
  renderAnalysisConfusion(data);
  renderAnalysisCases(data);
}

function paintAnalysisFromCache() {
  const data = state.reviewAnalysis?.data;
  if (!data) return false;
  // Quiet repaint when revisiting the tab — pie spin is for real data loads only.
  renderReviewReasonAnalysis(data, { animatePies: false });
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
