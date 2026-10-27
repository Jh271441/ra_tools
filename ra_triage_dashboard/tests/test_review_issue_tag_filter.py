"""Issue-subtag gallery filtering is read-only, grouped and pre-pagination."""
import asyncio
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Response
from starlette.requests import Request
from ra_triage_dashboard.app.routers import cases, analysis
from ra_triage_dashboard.app.support import filter_parsing
from ra_triage_dashboard.app.support.issue_tag_filters import parse_issue_tag_groups, matches_issue_tag_groups
from ra_triage_dashboard.app.runtime_catalogs import REVIEW_TAG_CATALOG, REVIEW_TAG_ALIASES
import test_issue_label_state_projection as fixture


class ReviewIssueTagFilterTest(unittest.TestCase):
    setUp = fixture.IssueLabelStateProjectionTest.setUp
    add_issues = fixture.IssueLabelStateProjectionTest.add_issues

    def seed(self):
        self.heads = {}
        self.add_issues([dict(issue_id=f"cn{i}", gt_label="正确触发") for i in range(1, 6)], "scope")
        for issue, tags in [("cn1", ["construction_change", "intent_u_turn"]),
                            ("cn2", ["gate", "intent_u_turn"]),
                            ("cn3", ["construction_change", "intent_straight"]),
                            ("cn4", [])]:
            self.heads[issue] = self.revision(issue, tags)

    def revision(self, issue, tags, author="alice", previous=None):
        return self.database.create_label_revision(
            issue_id=issue, expected_output="正确触发", tags=tags, evidence_gaps=[],
            rationale="test", is_excluded=False, author=author, author_source="test",
            author_verified=True, expected_previous_revision_id=previous,
        )

    def filters(self, tags="", **extra):
        groups = parse_issue_tag_groups(tags, REVIEW_TAG_CATALOG, REVIEW_TAG_ALIASES)
        return {"baseline_scopes": ["scope"], **({"issue_tag_groups": groups} if groups else {}), **extra}

    def ids(self, tags="", **extra):
        with patch.object(cases, "database", self.database):
            return cases._case_issue_ids_with_status_filter(filters=self.filters(tags, **extra), review_statuses=())

    def test_group_or_cross_group_and_empty_and_custom_catalog(self):
        groups = parse_issue_tag_groups("gate,construction_change,intent_u_turn", REVIEW_TAG_CATALOG, {})
        self.assertTrue(matches_issue_tag_groups(["gate", "intent_u_turn"], groups, {}))
        self.assertFalse(matches_issue_tag_groups(["gate"], groups, {}))
        self.assertTrue(matches_issue_tag_groups([], (), {}))
        custom = (*REVIEW_TAG_CATALOG, dict(key="custom_scope", group="ra", deleted=True))
        self.assertEqual(parse_issue_tag_groups("custom_scope", custom, {}), (("custom_scope",),))
        with self.assertRaises(ValueError):
            parse_issue_tag_groups("not-a-catalog-tag", custom, {})
        with self.assertRaises(ValueError):
            parse_issue_tag_groups(",".join(["gate"] * 257), custom, {})

    def test_filtered_ids_and_pagination_use_same_complete_scope(self):
        self.seed()
        tags = "construction_change,gate,intent_u_turn"
        before = self.database.change_revision()
        self.assertEqual(self.ids(tags), ["cn1", "cn2"])
        self.assertEqual(self.ids(tags, issue_ids=["cn2", "cn3"]), ["cn2"])
        self.assertEqual(len(self.ids()), 5)
        self.assertEqual(self.ids("egress_swag"), [])
        with patch.object(cases, "database", self.database), patch.object(cases, "_review_tag_catalog", return_value=REVIEW_TAG_CATALOG):
            for page, expected in [(1, ["cn1"]), (2, ["cn2"]), (3, [])]:
                result = cases._case_result_with_status_filter(filters=self.filters(tags), review_statuses=(), page=page, page_size=1)
                self.assertEqual(result["total"], 2)
                self.assertEqual([row["issue_id"] for row in result["items"]], expected)
        self.assertEqual(self.database.change_revision(), before)

    def test_current_heads_not_historical_versions_and_shared_authors(self):
        self.seed()
        self.assertEqual(self.ids("gate"), ["cn2"])
        previous = self.heads["cn2"]["id"]
        self.revision("cn2", [], previous=previous)
        self.assertEqual(self.ids("gate"), [])
        self.revision("cn2", ["gate"], author="bob")
        self.assertEqual(self.ids("gate"), ["cn2"])

    def test_authoritative_empty_and_decision_context_do_not_fall_back(self):
        self.seed()
        with patch.object(self.database, "project_issue_tag_contexts", return_value={
            "cn1": {"tags": [], "decision_id": "current"},
            "cn2": {"tags": ["construction_change"], "decision_id": "current"},
        }):
            self.assertEqual(self.ids("construction_change"), ["cn2"])

    def test_public_parser_rejects_unknown_instead_of_broadening(self):
        with patch.object(filter_parsing, "resolve_request_baseline_scopes", return_value=["scope"]), \
             patch.object(filter_parsing, "_review_tag_catalog", return_value=REVIEW_TAG_CATALOG):
            result = filter_parsing._case_filter_kwargs(issue_tags="gate,intent_u_turn")
            self.assertEqual(result["issue_tag_groups"], (("gate",), ("intent_u_turn",)))
            with self.assertRaises(HTTPException) as caught:
                filter_parsing._case_filter_kwargs(issue_tags="invalid")
            self.assertEqual(caught.exception.status_code, 400)

    def test_export_resolves_gallery_membership_before_exporting(self):
        self.seed()
        captured = {}
        def payload(**kwargs):
            captured["ids"] = kwargs["issue_ids"]
            return {"items": []}
        def response(data, fmt):
            captured["export_ids"] = [item["issue_id"] for item in data["items"]]
            return Response(content=b"ok")
        request = Request({"type": "http", "headers": [], "query_string": b""})
        parsed = {**self.filters("gate,intent_u_turn"), "review_statuses": (), "label_states": (), "exclusion": "all"}
        with patch.object(cases, "database", self.database), patch.object(analysis, "database", self.database), \
             patch.object(analysis, "resolve_request_baseline_scopes", return_value=["scope"]), \
             patch.object(analysis, "_case_filter_kwargs", return_value=parsed) as parser, \
             patch.object(analysis, "request_identity", return_value=SimpleNamespace(username="alice", verified=True)), \
             patch.object(analysis, "_review_reason_analysis_payload", side_effect=payload), \
             patch.object(analysis, "_review_analysis_export_response", side_effect=response):
            asyncio.run(analysis.export_review_reason_analysis(request, gallery_scope=True, issue_tags="gate,intent_u_turn"))
        self.assertEqual(parser.call_args.kwargs["issue_tags"], "gate,intent_u_turn")
        self.assertEqual(captured["ids"], ["cn2"])
        self.assertEqual(captured["export_ids"], ["cn2"])

    def test_frontend_roundtrip(self):
        subprocess.run(["node", str(Path(__file__).with_name("review_issue_tag_filter.cjs"))], check=True)
