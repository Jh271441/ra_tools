"""Frontend labeling source contracts; original assertions preserved."""
import unittest
from frontend_contract_fixtures import APP_ENTRY_JS, APP_JS, INDEX_HTML, STYLES_CSS


class FrontendLabelingContractTest(unittest.TestCase):
    def test_task_context_and_native_selects_use_product_components(self) -> None:
        self.assertIn("/api/review-task-context/", APP_JS)
        self.assertIn("历史无 Run 任务", APP_JS)
        self.assertIn("renderReviewTaskLoading", APP_JS)
        self.assertIn("reviewTaskContextError", INDEX_HTML)
        self.assertIn("enhanceNativeUiSelect", APP_JS)
        self.assertIn("enhanceDashboardSelects", APP_JS)
        for select_id in (
            "workSplitWorkflowMode", "reviewWorkflowMode", "campaignsSource",
            "runCollectionSelect", "runCollectionRevisionSelect",
            "runCollectionReferenceType", "runCollectionComparisonReference",
            "runCollectionSelectionSourceRun", "modelReviewStatusInput",
        ):
            self.assertIn(f'"{select_id}"', APP_JS)
        self.assertIn("dashboard-native-ui-select", STYLES_CSS)
        self.assertIn('event.key === "ArrowDown"', APP_JS)
        self.assertIn('event.key === "Escape"', APP_JS)

    def test_case_labeling_is_a_separate_model_free_workspace(self) -> None:
        self.assertIn('data-page-target="labeling" data-app-path="/case-labeling"', INDEX_HTML)
        self.assertIn('id="caseLabelingNavButton"', INDEX_HTML)
        self.assertIn('state.config?.case_labeling?.active_baseline_ids', APP_JS)
        self.assertIn("function hasDashboardWriteRole", APP_JS)
        self.assertIn('caseLabelingNav.hidden = !canLabelCases', APP_JS)
        self.assertIn('问题标注需要 writer 或管理员权限', APP_JS)
        self.assertIn('labelingExperimentsNav.hidden = !state.session.is_admin', APP_JS)
        self.assertIn('尚未切换到 问题标注', APP_JS)
        self.assertIn('问题标注', INDEX_HTML)
        self.assertNotIn('sidebar-preview-badge', INDEX_HTML)
        self.assertNotIn('Case Labeling (preview)', APP_JS)
        self.assertNotIn('#caseLabelingNavButton .sidebar-label strong { display: inline-flex', STYLES_CSS)
        self.assertIn('issue-grid-empty case-labeling-inactive-state', APP_JS)
        self.assertIn('class="gallery-panel" id="caseLabelingGallery"', INDEX_HTML)
        self.assertIn('issueCard(caseLabelingGalleryItem(item), { workspace: "labeling" })', APP_JS)
        self.assertIn("function caseLabelingTagAttributes", APP_JS)
        self.assertIn("resolution.result_revision", APP_JS)
        self.assertIn("resolution.heads || []", APP_JS)
        self.assertIn("label_attributes: caseLabelingTagAttributes(item)", APP_JS)
        self.assertIn("function issueCardLabelingAttributes", APP_JS)
        self.assertIn("const visible = tags.slice(0, 3)", APP_JS)
        self.assertIn('class="case-labeling-card-tags"', APP_JS)
        self.assertIn('class="case-labeling-card-tag-more"', APP_JS)
        self.assertIn(".case-labeling-card-tags {", STYLES_CSS)
        self.assertNotIn(".case-labeling-card-attributes {", STYLES_CSS)
        self.assertNotIn('issue-card-preview', APP_JS)
        self.assertIn('/api/labeling/cases/${encodeURIComponent(issueId)}/comments', APP_JS)
        self.assertIn('kind === "labeling"', APP_JS)
        self.assertIn('id="caseLabelingPage" data-page="labeling"', INDEX_HTML)
        self.assertIn('path: "/case-labeling"', APP_JS)
        self.assertIn('"case-labeling.js"', APP_ENTRY_JS)
        self.assertIn('"css/case-labeling.css"', INDEX_HTML)
        self.assertIn('/api/labeling/cases', APP_JS)
        self.assertIn('function renderCaseLabelingEditor', APP_JS)
        self.assertIn("任务外补充标注", APP_JS)
        self.assertIn("caseLabelingSubmissionTaskId", APP_JS)
        self.assertIn("current_user_is_task_member", APP_JS)
        self.assertIn("function caseLabelDecisionMarkup", APP_JS)
        self.assertIn("Issue 级裁决", APP_JS)
        self.assertIn("/api/labeling/issues/${encodeURIComponent(caseData.issue_id)}/decisions", APP_JS)
        self.assertIn("expected_source_fingerprint", APP_JS)
        self.assertIn(".case-label-decision {", STYLES_CSS)
        self.assertIn("任务外补充复核", APP_JS)
        self.assertIn("reviewWorkSplitBinding(caseData);", APP_JS)
        self.assertNotIn("reviewWorkSplitBinding(caseData) || state.reviewWorkSplitId", APP_JS)
        self.assertIn('此处不填写模型判错原因', APP_JS)
        self.assertIn('class="review-detail-view case-labeling-detail hidden"', INDEX_HTML)
        self.assertIn('renderReviewTagGroups(tagCatalog, chosenTags, tagOption)', APP_JS)
        self.assertIn('function renderCaseLabelingDetailMedia', APP_JS)
        self.assertNotIn('case-labeling-media-grid', APP_JS)
        self.assertIn('body[data-active-page^="labeling"] .header-metrics', STYLES_CSS)
        self.assertIn(
            'if (!["labeling", "labeling-new-task", "labeling-summary"].includes(initialRoute.page))',
            APP_JS,
        )
        self.assertIn('if (state.activePage === "labeling")', APP_JS)

    def test_review_assignment_history_uses_flat_visual_hierarchy(self) -> None:
        self.assertIn(".review-assignment-list-card { padding: 4px 2px 0; border: 0;", STYLES_CSS)
        self.assertIn(".review-assignment-list { display: grid; gap: 10px; }", STYLES_CSS)
        self.assertIn(".review-assignment-batch { display: grid; gap: 10px; padding: 13px 14px; border: 1px solid var(--line); border-radius: 9px; background: var(--overlay); }", STYLES_CSS)
        self.assertIn(".review-assignment-progress { display: grid; grid-template-columns: minmax(0, 1fr); gap: 8px; }", STYLES_CSS)
        self.assertIn(".review-assignment-member + .review-assignment-member { padding-left: 14px; border-left: 1px solid var(--line-soft); }", STYLES_CSS)
        self.assertIn(".review-assignment-member + .review-assignment-member { padding: 10px 0 2px; border-top: 1px solid var(--line-soft); border-left: 0; }", STYLES_CSS)

    def test_work_assignee_filter_survives_custom_facet_rebuild(self) -> None:
        self.assertIn("function workAssigneeRouteSelection()", APP_JS)
        self.assertIn("function workAssigneeFilterSelection()", APP_JS)
        self.assertIn("function persistWorkAssigneeFilterRoute(values)", APP_JS)
        self.assertIn("function workAssigneeOptionsWithSelected(options, selected)", APP_JS)
        # The canonical URL is the fallback while the custom multi-select has
        # no inputs during an async work-assignee facet refresh.
        self.assertIn('params.get("work_assignee") || params.get("assignee")', APP_JS)
        self.assertIn('persistWorkAssigneeFilterRoute(values)', APP_JS)
        self.assertIn('persistWorkAssigneeFilterRoute([name])', APP_JS)
        self.assertIn('persistWorkAssigneeFilterRoute?.([])', APP_JS)
        self.assertIn('workAssigneeFilterSelection()', APP_JS)
        self.assertIn('renderWorkAssigneeFilter(workAssigneeFilterSelection())', APP_JS)
