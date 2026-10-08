"""Frontend shell source contracts; original assertions preserved."""
import unittest
from frontend_contract_fixtures import APP_ENTRY_JS, APP_JS, CSS_PATHS, INDEX_HTML, JS_DIR, MANIFEST_PATH, STATIC_DIR, STYLES_CSS


class FrontendShellContractTest(unittest.TestCase):
    def test_component_stylesheets_load_in_declared_order(self) -> None:
        self.assertLessEqual(
            len((STATIC_DIR / "styles.css").read_text(encoding="utf-8").splitlines()),
            80,
        )
        positions = []
        for path in CSS_PATHS:
            self.assertTrue((STATIC_DIR / path).is_file(), path)
            positions.append(INDEX_HTML.index(f'"{path}"'))
        self.assertEqual(positions, sorted(positions))
        self.assertIn("pendingStyles = stylesheetPaths.length", INDEX_HTML)
        self.assertIn("if (pendingStyles === 0) revealShell()", INDEX_HTML)

    def test_final_mobile_layer_owns_phone_and_tablet_layout(self) -> None:
        mobile_css = (STATIC_DIR / "css/mobile.css").read_text(encoding="utf-8")
        self.assertGreater(INDEX_HTML.index('"css/mobile.css"'), INDEX_HTML.index('"css/runs.css"'))
        self.assertIn("@media (max-width: 1024px)", mobile_css)
        self.assertIn("@media (max-width: 639px)", mobile_css)
        self.assertIn(".review-detail-workspace", mobile_css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) !important", mobile_css)
        self.assertIn(".detail-context-row { flex-wrap: wrap", mobile_css)
        self.assertIn(".intent-media-stage:not(.is-zoomed) { touch-action: pan-y pinch-zoom; }", mobile_css)
        self.assertIn(".trail-update-table-wrap", mobile_css)
        self.assertIn("overflow-x: auto", mobile_css)
        self.assertIn(".expected-output-rule-popover { width: min(360px, calc(100vw - 48px)); }", mobile_css)

    def test_frontend_modules_load_in_manifest_order_from_thin_entry(self) -> None:
        names = [
            line.strip()
            for line in MANIFEST_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertGreaterEqual(len(names), 8)
        self.assertEqual(names[0], "core-base.js")
        self.assertEqual(names[-1], "bind-bootstrap.js")
        for name in names:
            self.assertTrue((JS_DIR / name).is_file(), name)
            self.assertIn(f'"{name}"', APP_ENTRY_JS)
        self.assertIn("CACHE_VERSION", APP_ENTRY_JS)
        self.assertIn("manual-triage-551", APP_ENTRY_JS)
        self.assertIn("function setBaselineScopes", APP_JS)
        self.assertIn("function applyInferredBaselinesFromRun", APP_JS)
        self.assertIn("clearIncompatible: true", APP_JS)
        self.assertNotIn("(preferDefault ? state.modelRuns[0]", APP_JS)
        self.assertIn("never carry an implicit/inherited Run", APP_JS)

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

    def test_sidebar_navigation_is_grouped_and_scrollable(self) -> None:
        self.assertIn('data-sidebar-nav-group="labeling"', INDEX_HTML)
        self.assertIn('data-sidebar-nav-group="review"', INDEX_HTML)
        self.assertIn('data-sidebar-nav-group="intent"', INDEX_HTML)
        self.assertIn('data-sidebar-nav-group="system"', INDEX_HTML)
        self.assertNotIn('data-sidebar-nav-group="work"', INDEX_HTML)
        self.assertNotIn('data-sidebar-nav-group="analysis"', INDEX_HTML)
        self.assertNotIn('<span class="ui-lang-zh">工作台</span>', INDEX_HTML)
        self.assertNotIn('<span class="ui-lang-zh">分析工具</span>', INDEX_HTML)
        self.assertIn('data-sidebar-nav-group-toggle="labeling"', INDEX_HTML)
        self.assertIn('data-sidebar-nav-group-toggle="review"', INDEX_HTML)
        self.assertIn('labeling-group-label"><span class="ui-lang-zh">Case 标注</span>', INDEX_HTML)
        self.assertIn('review-group-label"><span class="ui-lang-zh">判错复核</span>', INDEX_HTML)
        self.assertNotIn('<span class="ui-lang-zh">RA 标注与复核</span>', INDEX_HTML)
        self.assertEqual(INDEX_HTML.count('class="sidebar-group-icon"'), 4)
        self.assertIn(".sidebar-group-icon {", STYLES_CSS)
        self.assertIn(".sidebar-group-icon svg {", STYLES_CSS)
        self.assertIn("order: 0; color: #9aacbf;", STYLES_CSS)
        self.assertIn("#caseLabelingNavButton { order: 1; }", STYLES_CSS)
        self.assertIn("order: 1; padding: 0;", STYLES_CSS)
        self.assertIn("order: 2; margin-left: auto;", STYLES_CSS)
        self.assertIn(".sidebar-icon { border-color: transparent; color: #8594a8; background: transparent; }", STYLES_CSS)
        self.assertIn(".sidebar-item.active .sidebar-icon .icon-emphasis", STYLES_CSS)
        self.assertIn("margin-left: 18px; width: calc(100% - 18px);", STYLES_CSS)
        self.assertIn("width: 100%; min-height: 40px;", STYLES_CSS)
        self.assertIn("font-size: 13px; line-height: 1.25; letter-spacing: .02em;", STYLES_CSS)
        self.assertIn("padding-inline: 6px; scrollbar-gutter: auto; scrollbar-width: none;", STYLES_CSS)
        self.assertGreaterEqual(
            STYLES_CSS.count(".sidebar-nav-group .sidebar-item { width: 100% !important; min-width: 0; margin-left: 0 !important; }"),
            2,
        )
        labeling_attr = INDEX_HTML.index('data-sidebar-nav-group="labeling"')
        labeling_group = INDEX_HTML[INDEX_HTML.rindex('<section', 0, labeling_attr):].split('</section>', 1)[0]
        self.assertIn('id="caseLabelingNavGroup"', labeling_group)
        self.assertIn('id="caseLabelingNavButton"', labeling_group)
        review_group = INDEX_HTML.split('data-sidebar-nav-group="review"', 1)[1].split('</section>', 1)[0]
        for nav_id in (
            "reviewNavButton",
            "reviewAssignmentsNavButton",
            "reviewAnalysisNavButton",
            "trailAttributeUpdateNavButton",
            "openRunManagerButton",
            "runComparisonNavButton",
            "openBatchPredictionButton",
        ):
            self.assertIn(f'id="{nav_id}"', review_group)
        self.assertNotIn('id="caseLabelingNavButton"', review_group)
        self.assertIn('id="intentNavGroup"', INDEX_HTML)
        self.assertIn("overflow-y: auto", STYLES_CSS)
        self.assertIn("SIDEBAR_NAV_GROUP_PREFS_KEY", APP_JS)
        self.assertIn("function bindSidebarNavGroups", APP_JS)
        self.assertIn("function ensureSidebarNavGroupForPage", APP_JS)
        self.assertIn("ensureSidebarNavGroupForPage(target)", APP_JS)
        self.assertIn('localStorage.setItem(SIDEBAR_NAV_GROUP_PREFS_KEY', APP_JS)
        self.assertIn("sidebar-mobile-open .sidebar-nav-group", STYLES_CSS)

    def test_color_theme_is_persisted_and_applied_before_first_paint(self) -> None:
        self.assertIn('data-color-theme="dark"', INDEX_HTML)
        self.assertIn('localStorage.getItem("ra-triage-color-theme")', INDEX_HTML)
        self.assertIn('id="themeToggleButton"', INDEX_HTML)
        self.assertIn("function applyColorTheme(theme", APP_JS)
        self.assertIn('localStorage.setItem("ra-triage-color-theme"', APP_JS)
        self.assertIn('html[data-color-theme="light"]', STYLES_CSS)
        self.assertIn('color-scheme: light', STYLES_CSS)
        self.assertIn('html[data-color-theme="light"] .issue-card { background: var(--raised); }', STYLES_CSS)

    def test_read_only_mode_blocks_mutating_frontend_requests(self) -> None:
        self.assertIn('state.session?.read_only', APP_JS)
        self.assertIn('const isMutation = ["POST", "PUT", "PATCH", "DELETE"].includes(method)', APP_JS)
        self.assertIn('document.documentElement.dataset.accessMode', APP_JS)
        self.assertIn('"X-RA-Triage-Request": "browser-v1"', APP_JS)

    def test_native_buttons_keep_their_entire_surface_clickable(self) -> None:
        self.assertIn('id="reviewSaveButton"', APP_JS)
        self.assertIn('class="button button-primary full-width review-save-button"', APP_JS)
        self.assertIn(".review-save-button {", STYLES_CSS)
        self.assertIn("button > * { pointer-events: none; }", STYLES_CSS)

    def test_multi_issue_query_contract(self) -> None:
        self.assertIn('id="openIssueQueryButton"', INDEX_HTML)
        self.assertIn('id="issueQueryDialog"', INDEX_HTML)
        self.assertIn('id="issueQueryInput"', INDEX_HTML)
        self.assertIn("parseIssueIdsInput", APP_JS)
        self.assertIn("issue_ids", APP_JS)
        self.assertIn('"issue-query.js"', APP_ENTRY_JS)
        self.assertIn("state.reviewIssueIds", APP_JS)
