import React, { useMemo, useState } from "react";
import {
  bilingual,
  getWorkbenchBasePath,
  UiLanguage,
  withWorkbenchBase,
} from "../../bridge/useWorkbenchBridge";
import { LabelBadge, MODEL_LABELS, TRIAGE_LABELS } from "../charts/AnalysisCharts";
import {
  comparisonStatusMeta,
  DashboardConfigPayload,
  evidenceLabel,
  reviewTagCatalogItem,
  safeExternalUrl,
  tagLabel,
} from "../../utils/analysisHelpers";
import { showToast } from "../ui/Toast";

export const GT_RAW_VALUES = ["out_of_scope", "未接起"] as const;
export const GT_FILTER_VALUES = [...TRIAGE_LABELS, ...GT_RAW_VALUES] as const;

export interface GalleryLabelState {
  state?: string;
  expected_output?: string;
  gt_relation?: string;
  gt_review_pending?: boolean;
  method?: string;
  sources?: Array<{ label_case_id?: string; [key: string]: unknown }>;
  source_task_ids?: string[];
  source_revision_ids?: number[];
  decision?: {
    stale?: boolean;
    full_result?: boolean;
    tags?: string[];
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
}

export interface GalleryCaseItem {
  issue_id: string;
  gt_label?: string | null;
  gt_raw_label?: string | null;
  is_excluded?: boolean;
  expected_output?: string | null;
  author?: string | null;
  author_verified?: boolean;
  evidence_gaps?: string[] | null;
  voyager_issue_url?: string | null;
  thumbnail_url?: string | null;
  thumbnail?: {
    url?: string | null;
    label?: string | null;
  } | null;
  prediction?: {
    label?: string | null;
    model_run_id?: string | null;
    mismatch?: boolean;
    confidence?: number | null;
  } | null;
  annotation?: {
    id?: number | string | null;
    model_run_id?: string | null;
    model_review_status?: string | null;
    label?: string | null;
    expected_output?: string | null;
    review_status?: string | null;
    is_excluded?: boolean;
    author?: string | null;
    author_verified?: boolean;
    missing_evidence?: string[] | null;
    note?: string | null;
  } | null;
  label_state?: string | GalleryLabelState | null;
  decision?: {
    stale?: boolean;
    full_result?: boolean;
    tags?: string[];
  } | null;
  label_cases?: Array<{
    resolution?: {
      state?: string;
      method?: string;
      heads?: Array<{ tags?: string[] }>;
      result_revision?: { tags?: string[] };
    };
  }>;
  [key: string]: unknown;
}

interface TagAttributeGroup {
  key: string;
  section: string;
  label_zh: string;
  label_en: string;
  values: string[];
}

const CASE_LABELING_CARD_TAG_GROUPS: ReadonlyArray<{
  key: string;
  section: string;
  zh: string;
  en: string;
}> = [
  { key: "environment", section: "scene", zh: "环境", en: "Environment" },
  { key: "self_intent", section: "scene", zh: "自车意图", en: "Ego intent" },
  { key: "false_trigger", section: "interaction_decision", zh: "误触发", en: "False trigger" },
  { key: "true_trigger", section: "interaction_decision", zh: "应该触发", en: "Should trigger" },
  { key: "ra", section: "egress", zh: "正确触发", en: "Correct trigger" },
  { key: "no_assist", section: "egress", zh: "无需协助", en: "No assistance" },
  { key: "other", section: "other", zh: "其他", en: "Other" },
];

export function gtDisplayLabel(item: GalleryCaseItem | null | undefined): string {
  const gt = String(item?.gt_label || "").trim();
  if (gt) return gt;
  const raw = String(item?.gt_raw_label || "").trim();
  return (GT_RAW_VALUES as readonly string[]).includes(raw) ? raw : "";
}

export function safeSameOriginAssetUrl(url: string | null | undefined): string {
  if (!url || typeof window === "undefined") return "";
  try {
    const parsed = new URL(String(url), window.location.origin);
    const base = getWorkbenchBasePath();
    const pathname =
      base && parsed.pathname.startsWith(base)
        ? parsed.pathname.slice(base.length) || "/"
        : parsed.pathname;
    if (parsed.origin !== window.location.origin || !pathname.startsWith("/api/")) return "";
    return `${withWorkbenchBase(pathname)}${parsed.search}`;
  } catch {
    return "";
  }
}

export function reviewComparisonStatusForItem(
  item: GalleryCaseItem,
  selectedRunId: string,
): string {
  if (!selectedRunId) return "";
  const prediction = item?.prediction;
  if (!prediction?.model_run_id) return "none";
  if (!(MODEL_LABELS as readonly string[]).includes(String(prediction.label || ""))) return "none";
  if (!(TRIAGE_LABELS as readonly string[]).includes(String(item?.gt_label || ""))) {
    return "no_gt";
  }
  return prediction.mismatch ? "mismatch" : "match";
}

function sharedLabelStateVisual(labelState: GalleryLabelState | null | undefined): {
  kind: string;
  zh: string;
  en: string;
} {
  const st = String(labelState?.state || "none");
  const relation = String(labelState?.gt_relation || "unknown");
  if (st === "resolved") {
    if (labelState?.gt_review_pending) {
      return { kind: "needs-review", zh: "GT 待复核", en: "Needs GT review" };
    }
    if (relation === "matches_gt") {
      return { kind: "matches", zh: "与 GT 一致", en: "Matches GT" };
    }
    if (relation === "differs_from_gt" || relation === "fills_missing_gt") {
      return { kind: "needs-review", zh: "GT 待复核", en: "Needs GT review" };
    }
    return { kind: "unknown", zh: "GT 未知", en: "GT unknown" };
  }
  if (st === "conflict") return { kind: "conflict", zh: "标签有分歧", en: "Label disagreement" };
  if (st === "stale") return { kind: "stale", zh: "待复核", en: "Needs recheck" };
  if (st === "pending") return { kind: "pending", zh: "标签待补齐", en: "Label incomplete" };
  return { kind: "none", zh: "无共享标签", en: "No shared label" };
}

function caseLabelingTagAttributes(
  item: GalleryCaseItem,
  config: DashboardConfigPayload | null | undefined,
): TagAttributeGroup[] {
  const labelStateStr = typeof item.label_state === "string" ? item.label_state : "";
  if (labelStateStr !== "resolved") return [];
  const decided = Boolean(item.decision?.full_result && !item.decision?.stale);
  const tagKeys: string[] = decided ? [...(item.decision?.tags || [])] : [];
  if (!decided) {
    for (const labelCase of item.label_cases || []) {
      const resolution = labelCase?.resolution || {};
      if (resolution.state !== "resolved") continue;
      const heads = resolution.heads || [];
      const revisions =
        resolution.method === "adjudication" && resolution.result_revision
          ? [resolution.result_revision]
          : heads.length
            ? heads
            : resolution.result_revision
              ? [resolution.result_revision]
              : [];
      for (const revision of revisions) {
        for (const key of revision?.tags || []) {
          const normalized = String(key || "").trim();
          if (normalized && !tagKeys.includes(normalized)) tagKeys.push(normalized);
        }
      }
    }
  }
  const grouped = new Map<string, string[]>(
    CASE_LABELING_CARD_TAG_GROUPS.map((group) => [group.key, []]),
  );
  for (const key of tagKeys) {
    const catalogItem = reviewTagCatalogItem(key, config);
    const catalogGroup = String(catalogItem?.group || "");
    const groupKey = grouped.has(catalogGroup) ? catalogGroup : "other";
    const label = String(catalogItem?.label || tagLabel(key, config));
    const values = grouped.get(groupKey)!;
    if (label && !values.includes(label)) values.push(label);
  }
  return CASE_LABELING_CARD_TAG_GROUPS.filter((g) => (grouped.get(g.key)?.length || 0) > 0).map(
    (g) => ({
      key: g.key,
      section: g.section,
      label_zh: g.zh,
      label_en: g.en,
      values: grouped.get(g.key) || [],
    }),
  );
}

interface LegacyGalleryWindow {
  openCaseMediaPreview?: (issueId: string, trigger?: HTMLElement | null) => Promise<void>;
  openSharedLabelStateDialog?: (item: GalleryCaseItem) => void;
}

export interface IssueCardGridProps {
  id: string;
  workspace: "review" | "labeling";
  items: GalleryCaseItem[];
  lang: UiLanguage;
  config: DashboardConfigPayload | null | undefined;
  selectedRunId?: string;
  selectedIssueId?: string;
  highlightedIssueId?: string;
  emptyContent: React.ReactNode;
  onOpenIssue: (issueId: string) => void;
}

export const IssueCardGrid: React.FC<IssueCardGridProps> = ({
  id,
  workspace,
  items,
  lang,
  config,
  selectedRunId = "",
  selectedIssueId = "",
  highlightedIssueId = "",
  emptyContent,
  onOpenIssue,
}) => {
  const [brokenThumbs, setBrokenThumbs] = useState<Record<string, boolean>>({});
  const isLabeling = workspace === "labeling";

  const cards = useMemo(() => items || [], [items]);

  const handleMediaPreview = (
    event: React.MouseEvent<HTMLButtonElement>,
    issueId: string,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    const win = window as unknown as LegacyGalleryWindow;
    if (typeof win.openCaseMediaPreview !== "function") return;
    win.openCaseMediaPreview(issueId, event.currentTarget).catch((err: unknown) => {
      showToast(err instanceof Error ? err.message : String(err), true);
    });
  };

  const handleOpenSharedLabel = (
    event: React.MouseEvent<HTMLButtonElement>,
    item: GalleryCaseItem,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    const win = window as unknown as LegacyGalleryWindow;
    win.openSharedLabelStateDialog?.(item);
  };

  if (!cards.length) {
    return (
      <div className="issue-grid" id={id} aria-live="polite">
        {emptyContent}
      </div>
    );
  }

  return (
    <div className="issue-grid" id={id} aria-live="polite">
      {cards.map((item) => {
        const isSelected = Boolean(selectedIssueId && item.issue_id === selectedIssueId);
        const isHighlighted = Boolean(
          highlightedIssueId && item.issue_id === highlightedIssueId,
        );
        const annotation = isLabeling
          ? {
              label: item.expected_output || "",
              author: item.author || "",
              author_verified: Boolean(item.author_verified),
              is_excluded: Boolean(item.is_excluded),
              missing_evidence: item.evidence_gaps || [],
              id: null,
              model_run_id: "",
              model_review_status: "",
              note: "",
            }
          : item.annotation || null;

        const annotationRunId = String(annotation?.model_run_id || "").trim();
        const prediction = item.prediction?.label || "";
        const comparisonStatus = isLabeling
          ? ""
          : reviewComparisonStatusForItem(item, selectedRunId);
        const comparisonMeta = comparisonStatus
          ? comparisonStatusMeta(comparisonStatus, lang)
          : null;
        const displayPrediction = prediction || (comparisonStatus === "none" ? "NONE" : "");

        const rawThumbUrl = isLabeling
          ? item.thumbnail_url || item.thumbnail?.url || ""
          : item.thumbnail?.url || "";
        const thumbnailUrl = safeSameOriginAssetUrl(rawThumbUrl);
        const thumbKey = `${item.issue_id}::${thumbnailUrl}`;
        const thumbFailed = Boolean(brokenThumbs[thumbKey]);
        const defaultThumbLabel = isLabeling
          ? String(item.thumbnail?.label || bilingual(lang, "BEV 关键帧", "BEV keyframe"))
          : String(
              item.thumbnail?.label ||
                (thumbnailUrl
                  ? bilingual(lang, "BEV 关键帧", "BEV keyframe")
                  : bilingual(lang, "暂无缩略图", "No thumbnail")),
            );
        const thumbnailLabel = thumbFailed
          ? bilingual(lang, "缩略图加载失败", "Thumbnail unavailable")
          : defaultThumbLabel;

        const issueUrl = safeExternalUrl(item.voyager_issue_url);
        const evidenceKeys = Array.isArray(annotation?.missing_evidence)
          ? annotation.missing_evidence
          : [];
        const evidenceTitle = evidenceKeys.map((k) => evidenceLabel(k, config)).join(" · ");

        const isExcluded = Boolean(item.is_excluded ?? annotation?.is_excluded);
        const labelStateStr = typeof item.label_state === "string" ? item.label_state : "";
        const labelStateObj: GalleryLabelState | null =
          item.label_state && typeof item.label_state === "object"
            ? (item.label_state as GalleryLabelState)
            : null;

        const historicalReview = Boolean(
          !isLabeling && selectedRunId && annotation?.id && annotationRunId !== selectedRunId,
        );
        const historicalReviewTitle = annotationRunId
          ? bilingual(
              lang,
              "复用其他 Model Run 的历史 Review；当前 Run 尚未保存独立版本",
              "Reusing a Review from another Model Run; this Run has no saved version yet",
            )
          : bilingual(
              lang,
              "复用未绑定 Run 的历史 Review；当前 Run 尚未保存独立版本",
              "Showing a legacy Review not bound to a Run; this Run has no saved version yet",
            );

        // Human shared label projection (Review workspace)
        const humanLabel =
          labelStateObj?.state === "resolved" &&
          (TRIAGE_LABELS as readonly string[]).includes(String(labelStateObj.expected_output || ""))
            ? String(labelStateObj.expected_output)
            : "";
        const humanFallback =
          labelStateObj?.state === "pending"
            ? bilingual(lang, "待补齐", "Incomplete")
            : labelStateObj?.state === "conflict"
              ? bilingual(lang, "有分歧", "Disagreement")
              : labelStateObj?.state === "stale"
                ? bilingual(lang, "待复核", "Needs recheck")
                : bilingual(lang, "未标注", "Not labeled");
        const sharedVisual = !isLabeling ? sharedLabelStateVisual(labelStateObj) : null;

        // Current-run review status (Review workspace)
        const belongsToSelectedRun = selectedRunId
          ? Boolean(annotation?.id && annotationRunId === selectedRunId)
          : Boolean(annotation?.id);
        const runReviewStatus = !belongsToSelectedRun
          ? "pending"
          : annotation?.model_review_status === "completed" ||
              (!annotation?.model_review_status && annotation?.note)
            ? "completed"
            : "in_progress";
        const runReviewLabels: Record<string, { zh: string; en: string }> = {
          pending: { zh: "待开始", en: "Not started" },
          in_progress: { zh: "待复核", en: "Needs review" },
          completed: { zh: "已完成", en: "Completed" },
        };
        const runReviewLabel = runReviewLabels[runReviewStatus];
        const runReviewTitle = selectedRunId
          ? bilingual(
              lang,
              "当前 Run 的判错复核进度",
              "Model error review progress for the selected Run",
            )
          : bilingual(
              lang,
              "当前 Review 范围的判错复核进度",
              "Model error review progress in the current scope",
            );

        // Labeling structured tag chips
        const labelingTagAttrs = isLabeling ? caseLabelingTagAttributes(item, config) : [];
        const flattenedTags = labelingTagAttrs.flatMap((attr) =>
          attr.values.map((val) => ({ ...attr, value: val })),
        );

        const openLabel = isLabeling
          ? bilingual(lang, `打开 ${item.issue_id} 标注`, `Open ${item.issue_id} labeling`)
          : bilingual(lang, `打开 ${item.issue_id} Review`, `Open ${item.issue_id} review`);

        const actorKindZh = isLabeling ? "标注" : "复核";
        const actorKindEn = isLabeling ? "Label" : "Review";

        const gtText = gtDisplayLabel(item);
        const labelOutput = String(item.expected_output || annotation?.label || "");

        return (
          <article
            key={item.issue_id}
            className={`issue-card${isSelected ? " selected" : ""}${isHighlighted ? " pending-jump-target" : ""}`}
            data-issue-id={item.issue_id}
            aria-current={isSelected ? "true" : undefined}
          >
            <button
              className="issue-card-open"
              type="button"
              data-open-issue={item.issue_id}
              aria-label={openLabel}
              onClick={() => onOpenIssue(item.issue_id)}
            />
            <div className={`issue-thumbnail${thumbFailed ? " thumbnail-missing" : ""}`}>
              <div className="issue-thumbnail-placeholder" aria-hidden="true">
                <span>RA</span>
                <small>{bilingual(lang, "无 BEV 缩略图", "No BEV thumbnail")}</small>
              </div>
              {thumbnailUrl && !thumbFailed && (
                <img
                  src={thumbnailUrl}
                  alt={`${item.issue_id} ${thumbnailLabel}`}
                  loading="lazy"
                  decoding="async"
                  data-case-thumbnail=""
                  onError={() =>
                    setBrokenThumbs((prev) => ({ ...prev, [thumbKey]: true }))
                  }
                />
              )}
              <span className="issue-thumbnail-label">{thumbnailLabel}</span>
              <button
                className="issue-media-preview"
                type="button"
                data-case-media-preview={item.issue_id}
                aria-label={bilingual(
                  lang,
                  `预览 ${item.issue_id} 的 BEV、Camera 和视频`,
                  `Preview BEV, Camera, and video for ${item.issue_id}`,
                )}
                onClick={(e) => handleMediaPreview(e, item.issue_id)}
              >
                {bilingual(lang, "媒体预览", "Media")}
              </button>
              {comparisonMeta && (
                <span
                  className={`comparison-chip comparison-${comparisonStatus} issue-thumbnail-status`}
                >
                  {comparisonMeta.label}
                </span>
              )}
            </div>
            <div className="issue-card-body">
              <div className="issue-card-heading">
                <div className="issue-card-heading-main">
                  {issueUrl ? (
                    <a
                      className="issue-id"
                      href={issueUrl}
                      target="_blank"
                      rel="noreferrer"
                      data-card-link=""
                      title={bilingual(lang, "打开 Voyager Issue", "Open Voyager Issue")}
                    >
                      {item.issue_id}
                    </a>
                  ) : (
                    <span className="issue-id">{item.issue_id}</span>
                  )}
                  {isLabeling && flattenedTags.length > 0 && (
                    <span className="case-labeling-card-tags">
                      {flattenedTags.slice(0, 3).map((tag, idx) => (
                        <span
                          key={`${tag.key}-${tag.value}-${idx}`}
                          className="case-labeling-card-tag"
                          data-tag-section={tag.section || "other"}
                          data-tag-group={tag.key || "other"}
                          title={`${tag.label_zh || tag.key} / ${tag.label_en || tag.key}: ${tag.value}`}
                        >
                          {tag.value}
                        </span>
                      ))}
                      {flattenedTags.length > 3 && (
                        <span
                          className="case-labeling-card-tag-more"
                          title={flattenedTags
                            .slice(3)
                            .map((t) => t.value)
                            .join(lang === "en" ? ", " : "、")}
                        >
                          +{flattenedTags.length - 3}
                        </span>
                      )}
                    </span>
                  )}
                  {evidenceKeys.length > 0 && (
                    <div className="row-evidence" title={evidenceTitle}>
                      {evidenceKeys.map((key) => (
                        <span key={key}>{evidenceLabel(key, config)}</span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="issue-card-flags">
                  {isExcluded ? (
                    <span
                      className="issue-card-flag issue-card-flag-excluded"
                      data-card-review-flag="excluded"
                    >
                      {bilingual(lang, "应该排除", "Exclude")}
                    </span>
                  ) : isLabeling &&
                    (labelStateStr === "conflict" || labelStateStr === "stale") ? (
                    <span
                      className="issue-card-flag issue-card-flag-needs-gt"
                      data-card-review-flag="conflict"
                    >
                      {bilingual(lang, "冲突待处理", "Conflict")}
                    </span>
                  ) : !isLabeling && comparisonStatus === "no_gt" ? (
                    <span
                      className="issue-card-flag issue-card-flag-model-no-gt"
                      data-card-review-flag="model_no_gt"
                    >
                      {bilingual(lang, "模型缺 GT", "Model has no GT")}
                    </span>
                  ) : null}

                  {!isLabeling && (
                    <span className="issue-card-human-summary">
                      <span
                        className="issue-label-pair issue-human-label"
                        data-shared-human-label={humanLabel}
                      >
                        <small>{bilingual(lang, "人工", "Human")}</small>
                        <LabelBadge label={humanLabel} emptyText={humanFallback} />
                      </span>
                      {sharedVisual && sharedVisual.kind !== "none" && (
                        <button
                          className={`shared-label-state-trigger shared-label-state-${sharedVisual.kind} shared-label-state-compact`}
                          type="button"
                          data-open-shared-label-state=""
                          data-issue-id={item.issue_id}
                          aria-label={bilingual(
                            lang,
                            `${sharedVisual.zh} · 查看 ${item.issue_id} 的共享标签来源`,
                            `${sharedVisual.en} · View shared label sources for ${item.issue_id}`,
                          )}
                          title={bilingual(
                            lang,
                            `${sharedVisual.zh} · 查看 ${item.issue_id} 的共享标签来源`,
                            `${sharedVisual.en} · View shared label sources for ${item.issue_id}`,
                          )}
                          onClick={(e) => handleOpenSharedLabel(e, item)}
                        >
                          <span className="shared-label-state-value">
                            {bilingual(lang, sharedVisual.zh, sharedVisual.en)}
                          </span>
                        </button>
                      )}
                    </span>
                  )}
                </div>
              </div>
              <div className="issue-card-labels">
                <span className="issue-label-pair">
                  <small>GT</small>
                  <LabelBadge label={gtText} emptyText="—" />
                </span>
                {isLabeling ? (
                  <span className="issue-label-pair">
                    <small>{bilingual(lang, "标注", "Label")}</small>
                    <LabelBadge label={labelOutput} emptyText="—" />
                  </span>
                ) : (
                  <span className="issue-label-pair">
                    <small>{bilingual(lang, "模型", "Model")}</small>
                    <LabelBadge
                      label={displayPrediction}
                      displayLabel={displayPrediction === "NONE" ? "NONE" : null}
                      emptyText="—"
                    />
                  </span>
                )}
                {!isLabeling && (
                  <span className="issue-card-run-review-state" title={runReviewTitle}>
                    <span className="issue-card-run-review-value">
                      {bilingual(lang, runReviewLabel.zh, runReviewLabel.en)}
                    </span>
                  </span>
                )}
                {historicalReview && (
                  <span className="issue-reviewer historical-review" title={historicalReviewTitle}>
                    {bilingual(lang, "历史 Review", "Historical review")}
                  </span>
                )}
                {annotation?.author && (
                  <span
                    className="issue-reviewer"
                    title={bilingual(
                      lang,
                      `${actorKindZh}人：${annotation.author}${annotation.author_verified ? " · SSO 已验证" : " · 未验证身份"}`,
                      `${actorKindEn}: ${annotation.author}${annotation.author_verified ? " · SSO verified" : " · unverified"}`,
                    )}
                  >
                    {annotation.author}
                    {annotation.author_verified ? " · SSO" : ""}
                  </span>
                )}
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
};
