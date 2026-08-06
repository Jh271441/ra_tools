from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from starlette.requests import Request

from ra_triage_dashboard.app.auth import (
    KylinSSOValidator,
    has_same_origin_mutation_marker,
    identity_can_write,
    identity_header_candidates,
    request_identity,
    validate_identity_settings,
)
from ra_triage_dashboard.app.settings import Settings


def make_request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/session",
            "headers": [
                (name.lower().encode("ascii"), value.encode("utf-8"))
                for name, value in headers.items()
            ],
        }
    )


class FakeSSOResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeSSOResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class IdentityAccessTest(unittest.TestCase):
    def test_identity_diagnostics_only_returns_safe_username_candidates(self) -> None:
        request = make_request(
            {
                "X-SSO-User": "jasperchen",
                "X-Employee-Account": "alice.chen",
                "Authorization": "Bearer must-not-leak",
                "Cookie": "user=must-not-leak",
                "X-Auth-Token": "must-not-leak",
                "X-Random": "bob",
            }
        )
        self.assertEqual(
            identity_header_candidates(request),
            {
                "x-sso-user": "jasperchen",
                "x-employee-account": "alice.chen",
            },
        )

    def test_default_mode_keeps_direct_ip_development_compatible(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.deployment_mode, "development")
        self.assertFalse(settings.trust_proxy_identity_headers)
        self.assertTrue(settings.kylin_sso_enabled)
        self.assertEqual(settings.kylin_sso_app_id, "2103794")

    def test_kylin_logout_is_bound_to_manual_return_path(self) -> None:
        with patch.dict(
            os.environ,
            {"DASHBOARD_BASE_PATH": "/manual"},
            clear=True,
        ):
            settings = Settings.from_env()
        parsed = urlparse(settings.kylin_sso_logout_url)
        query = parse_qs(parsed.query)
        self.assertEqual(query["app_id"], ["2103794"])
        self.assertEqual(
            query["jumpto"],
            ["https://auto-triage.intra.xiaojukeji.com/manual/review"],
        )
        self.assertEqual(
            settings.kylin_sso_return_url,
            "https://auto-triage.intra.xiaojukeji.com/manual/review",
        )

    def test_kylin_return_url_cannot_escape_manual_application(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_BASE_PATH": "/manual",
                "DASHBOARD_KYLIN_SSO_RETURN_URL": (
                    "https://auto-triage.intra.xiaojukeji.com/review"
                ),
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "/manual/"):
                Settings.from_env()

    def test_production_requires_trusted_proxy_and_token_file(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_DEPLOYMENT_MODE": "production",
                "DASHBOARD_KYLIN_SSO_ENABLED": "false",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "Kylin ticket"):
                Settings.from_env()

    def test_kylin_ticket_identity_is_server_validated(self) -> None:
        settings = SimpleNamespace(
            trust_proxy_identity_headers=False,
            kylin_sso_enabled=True,
            kylin_sso_app_id="2103794",
            kylin_sso_check_url="http://sso.invalid/check_user_ticket",
            kylin_sso_timeout_seconds=0.5,
            kylin_sso_cache_seconds=300,
        )
        response = FakeSSOResponse(
            {"errno": 0, "data": {"username": "alice"}}
        )
        validator = KylinSSOValidator()
        with patch("ra_triage_dashboard.app.auth._kylin_sso_validator", validator), patch(
            "ra_triage_dashboard.app.auth.urlrequest.urlopen",
            return_value=response,
        ) as urlopen:
            identity = request_identity(
                make_request(
                    {"Cookie": "_kylin_ticket=ticket-1; _kylin_username=alice"}
                ),
                settings,
            )
        self.assertTrue(identity.verified)
        self.assertEqual(identity.username, "alice")
        self.assertEqual(identity.source, "kylin_ticket")
        self.assertEqual(urlopen.call_count, 1)

    def test_kylin_ticket_rejects_username_mismatch(self) -> None:
        settings = SimpleNamespace(
            trust_proxy_identity_headers=False,
            kylin_sso_enabled=True,
            kylin_sso_app_id="2103794",
            kylin_sso_check_url="http://sso.invalid/check_user_ticket",
            kylin_sso_timeout_seconds=0.5,
            kylin_sso_cache_seconds=300,
        )
        response = FakeSSOResponse(
            {"errno": 0, "data": {"username": "bob"}}
        )
        with patch(
            "ra_triage_dashboard.app.auth._kylin_sso_validator",
            KylinSSOValidator(),
        ), patch(
            "ra_triage_dashboard.app.auth.urlrequest.urlopen",
            return_value=response,
        ):
            identity = request_identity(
                make_request(
                    {"Cookie": "_kylin_ticket=ticket-2; _kylin_username=alice"}
                ),
                settings,
            )
        self.assertFalse(identity.verified)
        self.assertEqual(identity.source, "kylin_ticket_invalid")

    def test_trusted_marker_and_sso_user_are_both_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "ingress_token"
            token_path.write_text("a" * 32, encoding="utf-8")
            token_path.chmod(0o600)
            settings = SimpleNamespace(
                deployment_mode="production",
                trust_proxy_identity_headers=True,
                identity_header="X-SSO-User",
                trusted_ingress_header="X-RA-Triage-Ingress",
                trusted_ingress_token_file=token_path,
                sso_write_users=("alice",),
            )
            validate_identity_settings(settings)

            spoofed = request_identity(
                make_request({"X-SSO-User": "alice"}), settings
            )
            self.assertFalse(spoofed.verified)
            self.assertFalse(identity_can_write(spoofed, settings))

            verified = request_identity(
                make_request(
                    {
                        "X-SSO-User": "alice",
                        "X-RA-Triage-Ingress": "a" * 32,
                    }
                ),
                settings,
            )
            self.assertTrue(verified.verified)
            self.assertTrue(verified.trusted_ingress)
            self.assertTrue(identity_can_write(verified, settings))

            not_allowlisted = request_identity(
                make_request(
                    {
                        "X-SSO-User": "bob",
                        "X-RA-Triage-Ingress": "a" * 32,
                    }
                ),
                settings,
            )
            self.assertTrue(not_allowlisted.verified)
            self.assertFalse(identity_can_write(not_allowlisted, settings))

    def test_production_token_file_must_be_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "ingress_token"
            token_path.write_text("b" * 32, encoding="utf-8")
            token_path.chmod(0o644)
            settings = SimpleNamespace(
                deployment_mode="production",
                trust_proxy_identity_headers=True,
                trusted_ingress_token_file=token_path,
            )
            with self.assertRaisesRegex(RuntimeError, "0600"):
                validate_identity_settings(settings)

    def test_mutations_require_a_known_non_simple_request_marker(self) -> None:
        self.assertFalse(has_same_origin_mutation_marker(make_request({})))
        self.assertFalse(
            has_same_origin_mutation_marker(
                make_request({"X-RA-Triage-Request": "unexpected"})
            )
        )
        for marker in ("browser-v1", "review-v1", "publish-v1"):
            with self.subTest(marker=marker):
                self.assertTrue(
                    has_same_origin_mutation_marker(
                        make_request({"X-RA-Triage-Request": marker})
                    )
                )


if __name__ == "__main__":
    unittest.main()
    identity_header_candidates,
