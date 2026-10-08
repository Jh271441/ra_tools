"""Frontend campaigns source contracts; original assertions preserved."""
import unittest
from frontend_contract_fixtures import APP_JS, APP_PY_CAMPAIGNS_DB, APP_PY_CAMPAIGNS_ROUTER, APP_PY_CASES_ROUTER, APP_PY_COMMENTS_DB, APP_PY_LABELING_ROUTER, APP_PY_SNAPSHOTS_DB, CAMPAIGNS_CSS, CAMPAIGNS_JS, FORMAT_API_JS, INDEX_HTML


class FrontendCampaignsContractTest(unittest.TestCase):
    def test_campaign_list_uses_the_selected_baseline_scopes(self) -> None:
        endpoint = CAMPAIGNS_JS.split("function campaignListEndpoint()", 1)[1].split(
            "\nasync function loadCampaigns", 1
        )[0]
        self.assertIn("baselines: selectedBaselineQueryValue()", endpoint)

    def test_campaign_views_respect_the_hidden_attribute(self) -> None:
        self.assertIn("#campaignsListView[hidden]", CAMPAIGNS_CSS)
        self.assertIn("#campaignDetailView[hidden]", CAMPAIGNS_CSS)
        self.assertIn("display: none !important", CAMPAIGNS_CSS)

    def test_campaign_route_survives_baseline_selection_updates(self) -> None:
        self.assertIn("async function setBaselineScopes", FORMAT_API_JS)
        self.assertIn('state.activePage === "campaigns"', FORMAT_API_JS)
        self.assertIn("campaignRouteOptions()", FORMAT_API_JS)
        self.assertIn("...routeOptions", FORMAT_API_JS)
        parser = APP_JS.split("function parsePageRoute()", 1)[1].split(
            "function normalizedAnalysisRouteFilters", 1
        )[0]
        self.assertIn('campaignId: String(params.get("campaign") || "").trim()', parser)
        self.assertIn('campaignPurpose: ["labeling", "model_review"]', parser)
        self.assertIn('campaignLifecycle: params.get("lifecycle") || "all"', parser)
        self.assertIn('campaignQuery: String(params.get("q") || "").slice(0, 128)', parser)
        self.assertIn('campaignGroupId: String(params.get("group") || "").trim()', parser)
        page_url = APP_JS.split("function pageUrl(page, options = {})", 1)[1].split(
            "function setReviewView", 1
        )[0]
        for key in ("campaignId", "groupId", "purpose", "lifecycle", "query"):
            self.assertIn(f"options.{key}", page_url)

    def test_campaign_task_group_detail_exposes_shared_config_and_child_progress(self) -> None:
        self.assertIn('id="campaignGroupView"', INDEX_HTML)
        self.assertIn('id="campaignGroupRows"', INDEX_HTML)
        self.assertIn("function loadCampaignGroupDetail", CAMPAIGNS_JS)
        self.assertIn("/api/review-task-groups/${encodeURIComponent(groupId)}", CAMPAIGNS_JS)
        self.assertIn("evaluation_run_id", CAMPAIGNS_JS)
        self.assertIn("progress.completed_issue_count", CAMPAIGNS_JS)

    def test_native_campaign_adapters_bind_a_frozen_workset(self) -> None:
        self.assertIn("Model Review Campaign 必须绑定冻结 Workset", APP_PY_CAMPAIGNS_DB)
        self.assertIn("database.create_review_workset", APP_PY_CASES_ROUTER)
        self.assertIn('"workset_id": workset["id"]', APP_PY_CASES_ROUTER)
        self.assertIn("Model Review Campaign 固定绑定一个 Workset", APP_PY_CASES_ROUTER)

    def test_campaign_lifecycle_and_assignment_controls_are_audited(self) -> None:
        for element_id in (
            "campaignActivateButton",
            "campaignCancelButton",
            "campaignSupersedeButton",
            "campaignLifecycleAuditRows",
            "campaignAssignmentAuditRows",
        ):
            self.assertIn(f'id="{element_id}"', INDEX_HTML)
        self.assertIn('mutateCampaignLifecycle("activate")', CAMPAIGNS_JS)
        self.assertIn('mutateCampaignLifecycle("cancel")', CAMPAIGNS_JS)
        self.assertIn('mutateCampaignLifecycle("supersede")', CAMPAIGNS_JS)
        self.assertIn('action: "reassign"', CAMPAIGNS_JS)
        self.assertIn('payload.assignment_audit || []', CAMPAIGNS_JS)
        self.assertIn('payload.lifecycle_audit || []', CAMPAIGNS_JS)

    def test_campaign_discussions_use_shared_thread_with_channel_locked_replies(self) -> None:
        self.assertIn("function openAnalysisDiscussion", APP_JS)
        self.assertIn('kind === "campaign"', APP_JS)
        self.assertIn("/discussion`)", APP_JS)
        self.assertIn("context.otherCampaigns", APP_JS)
        self.assertIn("context.replyTo.discussion_channel", APP_JS)
        self.assertIn("list_related_campaign_comment_groups", APP_PY_COMMENTS_DB)
        self.assertIn('@router.get("/api/campaigns/{campaign_id}/issues/{issue_id}/discussion")', APP_PY_CAMPAIGNS_ROUTER)

    def test_campaign_label_analysis_separates_tag_axes_and_rationale_themes(self) -> None:
        for element_id in (
            "campaignSceneTagCounts",
            "campaignTriggerTagCounts",
            "campaignEgressTagCounts",
            "campaignRationaleThemeCounts",
        ):
            self.assertIn(f'id="{element_id}"', INDEX_HTML)
        self.assertIn("reviewTagCatalogItem(key)", CAMPAIGNS_JS)
        self.assertIn("progress.rationale_theme_counts", CAMPAIGNS_JS)
        self.assertIn("classify_review_reason", APP_PY_CAMPAIGNS_DB)

    def test_label_result_snapshot_defaults_to_complete_and_confirms_diagnostic_partial(self) -> None:
        create_block = APP_JS.split(
            "async function createCaseLabelingResultSnapshot", 1
        )[1].split("\nfunction labelingTaskFilterPayload", 1)[0]
        self.assertIn("result = await saveSnapshot(false)", create_block)
        self.assertIn("window.confirm(message)", create_block)
        self.assertIn("result = await saveSnapshot(true)", create_block)
        self.assertIn("baseline_scopes: taskScopes", create_block)
        self.assertIn("result.snapshots", create_block)
        self.assertIn("unresolved=", APP_PY_SNAPSHOTS_DB)
        self.assertIn("type(value) is not bool", APP_PY_LABELING_ROUTER)
