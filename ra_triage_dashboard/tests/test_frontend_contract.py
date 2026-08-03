from __future__ import annotations

import unittest
from pathlib import Path


APP_JS = (
    Path(__file__).resolve().parents[1] / "static" / "app.js"
).read_text(encoding="utf-8")
STYLES_CSS = (
    Path(__file__).resolve().parents[1] / "static" / "styles.css"
).read_text(encoding="utf-8")
INDEX_HTML = (
    Path(__file__).resolve().parents[1] / "static" / "index.html"
).read_text(encoding="utf-8")


class FrontendContractTest(unittest.TestCase):
    def test_frontend_uses_one_base_path_boundary(self) -> None:
        self.assertIn('meta[name="ra-triage-base"]', APP_JS)
        self.assertIn("const CONFIGURED_BASE_PATH = normalizeClientBasePath(", APP_JS)
        self.assertIn("window.__RA_TRIAGE_BASE__ ?? CONFIGURED_BASE_PATH", APP_JS)
        self.assertIn("function withBase(path)", APP_JS)
        self.assertIn("function stripBasePath(pathname)", APP_JS)
        self.assertIn("removeBasePath(value, CONFIGURED_BASE_PATH)", APP_JS)
        self.assertIn("fetch(withBase(path)", APP_JS)
        self.assertIn("function normalizeApiPayloadUrls(value)", APP_JS)
        self.assertIn('key === "url" || key.endsWith("_url")', APP_JS)
        self.assertIn("stripBasePath(window.location.pathname)", APP_JS)

    def test_gallery_card_does_not_nest_controls_under_button_role(self) -> None:
        self.assertIn('class="issue-card-open"', APP_JS)
        self.assertIn('data-open-issue="${escapeHtml(item.issue_id)}"', APP_JS)
        self.assertIn('querySelectorAll("[data-open-issue]")', APP_JS)
        self.assertNotIn(
            'data-issue-id="${escapeHtml(item.issue_id)}" role="button"',
            APP_JS,
        )

    def test_gallery_reviewer_metadata_shares_the_label_row(self) -> None:
        card_start = APP_JS.index("function issueCard(item)")
        card_end = APP_JS.index("\nfunction caseGallerySignature", card_start)
        card_body = APP_JS[card_start:card_end]
        labels_start = card_body.index('<div class="issue-card-labels">')
        labels_end = card_body.index('</div>', labels_start)
        labels_body = card_body[labels_start:labels_end]
        self.assertIn('class="issue-reviewer"', labels_body)
        self.assertNotIn('<div class="issue-reviewer">', card_body)

    def test_manual_triage_brand_links_to_review_home(self) -> None:
        self.assertIn('class="sidebar-copy sidebar-home"', INDEX_HTML)
        self.assertIn('data-page-target="review" data-app-path="/review"', INDEX_HTML)
        self.assertIn('aria-label="Manual Triage 首页"', INDEX_HTML)

    def test_color_theme_is_persisted_and_applied_before_first_paint(self) -> None:
        self.assertIn('data-color-theme="dark"', INDEX_HTML)
        self.assertIn('localStorage.getItem("ra-triage-color-theme")', INDEX_HTML)
        self.assertIn('id="themeToggleButton"', INDEX_HTML)
        self.assertIn("function applyColorTheme(theme", APP_JS)
        self.assertIn('localStorage.setItem("ra-triage-color-theme"', APP_JS)
        self.assertIn('html[data-color-theme="light"]', STYLES_CSS)
        self.assertIn('color-scheme: light', STYLES_CSS)
        self.assertIn('html[data-color-theme="light"] .issue-card { background: var(--raised); }', STYLES_CSS)

    def test_batch_gateway_aligns_to_form_and_catalog_scrolls(self) -> None:
        self.assertIn(".batch-page-grid { align-items: stretch; }", STYLES_CSS)
        self.assertIn(".batch-page-grid > .tool-form { align-self: start; }", STYLES_CSS)
        self.assertIn("height: auto; min-height: 0", STYLES_CSS)
        self.assertIn("contain: size; overflow: hidden", STYLES_CSS)
        self.assertIn("contain: none; overflow: visible", STYLES_CSS)
        self.assertIn("grid-template-rows: auto auto auto auto minmax(0, 1fr) auto", STYLES_CSS)
        self.assertIn("overscroll-behavior: contain; scrollbar-gutter: stable", STYLES_CSS)

    def test_review_filter_type_matches_analysis_filter_type(self) -> None:
        self.assertIn(".review-filters label { min-width: 0; gap: 3px; color: var(--faint); font-size: 11px; }", STYLES_CSS)
        self.assertIn(".review-filters input, .review-filters select { min-width: 0; height: 32px; padding: 5px 29px 5px 7px; font-size: 12px; }", STYLES_CSS)
        self.assertIn(".analysis-filters label { min-width: 0; gap: 3px; color: var(--faint); font-size: 11px; }", STYLES_CSS)
        self.assertIn(".analysis-filters input, .analysis-filters select { height: 34px; min-width: 0; padding: 5px 29px 5px 8px; font-size: 12px; }", STYLES_CSS)

    def test_system_status_lead_keeps_only_refresh_actions(self) -> None:
        self.assertNotIn("只读查看服务、数据库、备份、容量与外部依赖", INDEX_HTML)
        self.assertNotIn("Read-only service, database, backup", INDEX_HTML)
        self.assertIn(".system-status-lead { min-height: 46px; justify-content: flex-end; }", STYLES_CSS)

    def test_read_only_mode_blocks_mutating_frontend_requests(self) -> None:
        self.assertIn('state.session?.read_only', APP_JS)
        self.assertIn('const isMutation = ["POST", "PUT", "PATCH", "DELETE"].includes(method)', APP_JS)
        self.assertIn('document.documentElement.dataset.accessMode', APP_JS)
        self.assertIn('"X-RA-Triage-Request": "browser-v1"', APP_JS)

    def test_tags_are_fixed_and_user_access_has_a_separate_admin_page(self) -> None:
        self.assertNotIn('id="manageReviewTagsButton"', INDEX_HTML)
        self.assertNotIn('id="tagManagerDialog"', INDEX_HTML)
        self.assertNotIn('/api/review-tags', APP_JS)
        self.assertIn('id="userManagementNavButton"', INDEX_HTML)
        self.assertIn('data-app-path="/users"', INDEX_HTML)
        self.assertIn('id="userManagementPage"', INDEX_HTML)
        self.assertIn("userManagementNav.hidden = !state.session.is_admin", APP_JS)
        self.assertIn('api("/api/access-users"', APP_JS)
        self.assertNotIn('id="addSceneTagButton"', APP_JS)

    def test_review_panel_separates_issue_tags_and_model_error(self) -> None:
        self.assertIn("function renderReviewTagGroups", APP_JS)
        self.assertIn('class="review-section issue-tag-section"', APP_JS)
        self.assertIn('class="review-section model-error-section"', APP_JS)
        self.assertIn('id="reviewExcludeInput"', APP_JS)
        self.assertIn("is_excluded: Boolean($(\"#reviewExcludeInput\")?.checked)", APP_JS)
        self.assertIn('"section": "scene"', Path(__file__).resolve().parents[1].joinpath("app", "main.py").read_text(encoding="utf-8"))
        self.assertIn('"section": "egress"', Path(__file__).resolve().parents[1].joinpath("app", "main.py").read_text(encoding="utf-8"))
        self.assertIn(".review-tag-groups { display: grid; grid-template-columns: repeat(2", STYLES_CSS)

    def test_review_save_updates_history_without_reselecting_the_case(self) -> None:
        save_start = APP_JS.index("async function saveAnnotation(event)")
        save_end = APP_JS.index("\nfunction mediaFrames", save_start)
        save_body = APP_JS[save_start:save_end]
        self.assertIn("updateReviewHistory(state.selectedCase)", save_body)
        self.assertIn("refreshReviewDerivedData()", save_body)
        self.assertNotIn("selectCase(", save_body)

    def test_review_mutations_acknowledge_server_revision_and_keep_form_dom(self) -> None:
        self.assertIn("function acknowledgeLocalChange(payload)", APP_JS)
        self.assertIn("acknowledgeLocalChange(result)", APP_JS)
        delete_start = APP_JS.index("async function deleteAnnotationVersion")
        delete_end = APP_JS.index("\nfunction renderReview", delete_start)
        delete_body = APP_JS[delete_start:delete_end]
        self.assertIn("syncReviewFormFromCase(caseData)", delete_body)
        self.assertNotIn("renderReview(caseData)", delete_body)

    def test_issue_detail_exposes_optional_ra_recording_and_event_links(self) -> None:
        self.assertIn("external_links", APP_JS)
        self.assertIn("RA 录屏 ↗", APP_JS)
        self.assertIn("RA Event ↗", APP_JS)
        self.assertIn("function openRaEventDialog(caseData)", APP_JS)
        self.assertIn('data-open-ra-event', APP_JS)
        self.assertIn("function loadTrailDetailMetadata(issueId, requestSeq)", APP_JS)
        self.assertIn("function scheduleTrailDetailMetadata(issueId, requestSeq)", APP_JS)
        self.assertIn("detailExternalLinks", APP_JS)
        self.assertIn('"/api/cases/" + encodeURIComponent(issueId) + "/trail-metadata"', APP_JS)
        self.assertIn("scheduleTrailDetailMetadata(issueId, requestSeq)", APP_JS)
        self.assertIn('id="raEventDialog"', INDEX_HTML)
        self.assertIn('id="raEventTableBody"', INDEX_HTML)
        self.assertIn("ra-event-table", STYLES_CSS)

    def test_issue_detail_keeps_media_first_and_avoids_loading_flash(self) -> None:
        preferred_start = APP_JS.index("function preferredMediaKind(caseData)")
        bev_offset = APP_JS.index("if (caseData?.assets?.frames?.length)", preferred_start)
        video_offset = APP_JS.index("if (caseData?.assets?.video?.url)", preferred_start)
        self.assertLess(video_offset, bev_offset)
        self.assertIn('preload="metadata"', APP_JS)
        self.assertIn('posterUrl: frames[heroFrameIndex(frames)]?.url || ""', APP_JS)
        self.assertIn("const hadDetail = Boolean(state.selectedCase)", APP_JS)
        self.assertIn("}, 140);", APP_JS)

    def test_gallery_refresh_reuses_loaded_thumbnails_without_transitions(self) -> None:
        self.assertIn("function caseGallerySignature(items)", APP_JS)
        self.assertIn("function reuseGalleryThumbnails(list, previousThumbnails)", APP_JS)
        self.assertIn("previous.image.naturalWidth <= 0", APP_JS)
        self.assertNotIn("transition: border-color 150ms ease-out, background 150ms ease-out", STYLES_CSS)

    def test_media_switch_preloads_and_decodes_before_replacing_the_view(self) -> None:
        self.assertIn("function preloadDetailImage(caseData, kind, index, root, onReady)", APP_JS)
        self.assertIn("image.decode", APP_JS)
        self.assertIn('root.setAttribute("aria-busy", "true")', APP_JS)
        self.assertIn("preloadDetailImage(caseData, kind, nextIndex, root", APP_JS)
        self.assertIn("function preloadMediaDialogImage(url, onReady)", APP_JS)
        self.assertIn('previewImage.dataset.mediaUrl = targetUrl', APP_JS)
        self.assertIn("function applyDetailImageFrame(root, caseData, kind, index, loadedImage = null)", APP_JS)
        self.assertIn("image.before(nextImage)", APP_JS)
        self.assertIn('nextImage.style.visibility = "visible"', APP_JS)
        self.assertIn('image.style.zIndex = "1"', APP_JS)
        self.assertIn("window.requestAnimationFrame(() => window.requestAnimationFrame(commit))", APP_JS)
        self.assertIn('root.querySelectorAll("#detailMediaPreviousButton, #detailMediaNextButton")', APP_JS)
        self.assertNotIn('root.querySelectorAll("button, select")', APP_JS)
        self.assertIn('class="detail-media-image"', APP_JS)
        self.assertIn(".hero-media-button img.detail-media-image", STYLES_CSS)
        self.assertNotIn(".detail-media-image { opacity: 0", STYLES_CSS)
        self.assertNotIn(".issue-thumbnail img.is-loaded", STYLES_CSS)
        self.assertNotIn(".issue-card:hover .issue-thumbnail img", STYLES_CSS)

    def test_review_history_exposes_explicit_delete_action(self) -> None:
        self.assertIn('data-delete-annotation="${escapeHtml(annotation.id)}"', APP_JS)
        self.assertIn('method: "DELETE"', APP_JS)
        self.assertIn("deleteAnnotationVersion(caseData", APP_JS)
        self.assertIn(".history-delete-button", STYLES_CSS)


if __name__ == "__main__":
    unittest.main()
