"""P0 security, Kylin SSO, CORS, CSRF, mock-data, path safety, and status redaction tests."""

from __future__ import annotations

import io
import json
import logging
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal, init_db
from app.main import app
from app.security import (
    _kylin_sso_validator,
    load_security_config,
    validate_security_settings,
)
from app.services import auto_triage_warehouse, release_source, system_status
from app.services.issue_client import IssueClient
from app.services.sim_result_client import SimResultClient
from ra_api import sim_result_api


@pytest.fixture(autouse=True)
def _reset_validator():
    init_db()
    _kylin_sso_validator.clear()
    yield
    _kylin_sso_validator.clear()


class _FakeUrlResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _mock_urlopen(payload: dict):
    raw = json.dumps(payload).encode("utf-8")

    def _open(req, timeout=None):
        return _FakeUrlResponse(raw)

    return _open


def test_cors_blocks_arbitrary_origin_and_allows_trusted_origin():
    client = TestClient(app)
    ok = client.options(
        "/api/health",
        headers={
            "Origin": "https://auto-triage.intra.xiaojukeji.com",
            "Access-Control-Request-Method": "PUT",
        },
    )
    assert (
        ok.headers.get("access-control-allow-origin") == "https://auto-triage.intra.xiaojukeji.com"
    )

    bad = client.options(
        "/api/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "PUT",
        },
    )
    assert "access-control-allow-origin" not in bad.headers


def test_production_write_requires_same_origin_header_and_kylin_sso(monkeypatch, caplog):
    monkeypatch.setenv("SIM_DEPLOYMENT_MODE", "production")
    monkeypatch.delenv("SIM_SSO_WRITE_USERS", raising=False)
    monkeypatch.delenv("SIM_TRUSTED_INGRESS_TOKEN_FILE", raising=False)
    monkeypatch.delenv("SIM_TRUST_PROXY_IDENTITY_HEADERS", raising=False)
    client = TestClient(app)

    # GET stays readable even without SSO cookies
    health = client.get("/api/health")
    assert health.status_code == 200

    # /api/auth/me reports unauthenticated in production
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["authenticated"] is False
    assert me.json()["can_write"] is False
    assert me.json()["deployment_mode"] == "production"

    # Mutating without X-RA-Sim-Request header is rejected with 403
    no_hdr = client.put("/api/dashboard/workflow/mode", json={"mode": "manual"})
    assert no_hdr.status_code == 403
    assert "同源校验" in no_hdr.json()["detail"]

    # Mutating with X-RA-Sim-Request and spoofed X-SSO-User header (no Kylin cookie) is rejected
    spoofed = client.put(
        "/api/dashboard/workflow/mode",
        json={"mode": "manual"},
        headers={"X-RA-Sim-Request": "browser-v1", "X-SSO-User": "admin"},
    )
    assert spoofed.status_code == 403

    # Valid server-side verified Kylin SSO ticket succeeds and emits audit log
    auth_client = TestClient(
        app, cookies={"_kylin_ticket": "valid-ticket-123", "_kylin_username": "alice"}
    )
    with patch(
        "app.security.urlrequest.urlopen",
        side_effect=_mock_urlopen({"errno": 0, "data": {"username": "alice"}}),
    ):
        with caplog.at_level(logging.INFO, logger="app.audit"):
            ok = auth_client.put(
                "/api/dashboard/workflow/mode",
                json={"mode": "manual"},
                headers={"X-RA-Sim-Request": "browser-v1"},
            )
            me_auth = auth_client.get("/api/auth/me")
    assert ok.status_code == 200
    assert me_auth.status_code == 200
    assert me_auth.json()["authenticated"] is True
    assert me_auth.json()["username"] == "alice"
    assert me_auth.json()["can_write"] is True
    audit_entries = [
        json.loads(r.getMessage().split(" ", 1)[1])
        for r in caplog.records
        if r.name == "app.audit" and r.getMessage().startswith("sim_mutation_audit ")
    ]
    assert any(
        e["actor"] == "alice"
        and e["path"] == "/api/dashboard/workflow/mode"
        and e["status_code"] == 200
        for e in audit_entries
    )


def test_production_write_whitelist_blocks_non_whitelisted_sso_user(monkeypatch):
    monkeypatch.setenv("SIM_DEPLOYMENT_MODE", "production")
    monkeypatch.setenv("SIM_SSO_WRITE_USERS", "bob,carol")
    client = TestClient(
        app, cookies={"_kylin_ticket": "valid-ticket-456", "_kylin_username": "alice"}
    )

    with patch(
        "app.security.urlrequest.urlopen",
        side_effect=_mock_urlopen({"errno": 0, "data": {"username": "alice"}}),
    ):
        denied = client.put(
            "/api/dashboard/workflow/mode",
            json={"mode": "manual"},
            headers={"X-RA-Sim-Request": "browser-v1"},
        )
        me_alice = client.get("/api/auth/me")
    assert denied.status_code == 403
    assert me_alice.json()["authenticated"] is True
    assert me_alice.json()["can_write"] is False


def test_trusted_ingress_token_file_enforces_0600_and_authorizes_proxy_write(monkeypatch, tmp_path):
    token_value = "s" * 40
    token_file = tmp_path / "ingress.token"
    token_file.write_text(token_value + "\n", encoding="utf-8")
    os.chmod(token_file, 0o644)

    monkeypatch.setenv("SIM_DEPLOYMENT_MODE", "production")
    monkeypatch.setenv("SIM_TRUSTED_INGRESS_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("SIM_TRUST_PROXY_IDENTITY_HEADERS", "1")

    # Overly permissive file mode (0644) must fail startup validation
    with pytest.raises(RuntimeError, match="0600"):
        validate_security_settings(load_security_config())

    # Tightening to 0600 passes validation and authorizes trusted proxy identity
    os.chmod(token_file, 0o600)
    validate_security_settings(load_security_config())

    client = TestClient(app)
    bad = client.put(
        "/api/dashboard/workflow/mode",
        json={"mode": "manual"},
        headers={
            "X-RA-Sim-Request": "browser-v1",
            "X-RA-Sim-Ingress": "wrong-token",
            "X-SSO-User": "alice",
        },
    )
    assert bad.status_code == 403

    ok = client.put(
        "/api/dashboard/workflow/mode",
        json={"mode": "manual"},
        headers={
            "X-RA-Sim-Request": "browser-v1",
            "X-RA-Sim-Ingress": token_value,
            "X-SSO-User": "alice",
        },
    )
    assert ok.status_code == 200


def test_disable_mock_data_blocks_mock_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("DISABLE_MOCK_DATA", "1")
    (tmp_path / "sim_job_123.json").write_text('[{"scenario_id": "1"}]', encoding="utf-8")
    (tmp_path / "issues.json").write_text('{"cn1": {"issue_id": "cn1"}}', encoding="utf-8")

    sim_client = SimResultClient(mock_dir=tmp_path)
    issue_client = IssueClient(mock_dir=tmp_path)
    assert sim_client._read_mock(123) is None
    assert issue_client._read_mock() == {}


def test_artifact_source_rejects_path_traversal(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps({"complete": True, "issues": [], "scenarios": []}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="source_artifact_path_forbidden"):
        release_source.artifact_source({"source_artifact": str(outside)})


def test_shuyi_storage_state_enforces_0600_in_production_and_avoids_tmp_default(
    monkeypatch, tmp_path
):
    state_file = tmp_path / "shuyi.json"
    state_file.write_text(
        json.dumps({"cookies": [{"name": "ticket", "value": "abc", "domain": ".xiaojukeji.com"}]}),
        encoding="utf-8",
    )
    os.chmod(state_file, 0o644)
    monkeypatch.setenv("AUTO_TRIAGE_SHUYI_STORAGE_STATE", str(state_file))
    monkeypatch.setenv("SIM_DEPLOYMENT_MODE", "production")
    with pytest.raises(ValueError, match="dashboard_login_required"):
        auto_triage_warehouse.Client()

    os.chmod(state_file, 0o600)
    client = auto_triage_warehouse.Client()
    try:
        assert client.http.cookies.get("ticket") == "abc"
    finally:
        client.close()


def test_ra_api_sim_result_has_no_hardcoded_token_and_verifies_ssl_by_default(monkeypatch):
    assert sim_result_api._DEFAULT_APP_TOKEN == ""
    monkeypatch.delenv("SIM_RESULT_APP_TOKEN", raising=False)
    monkeypatch.delenv("TRAIL_APP_TOKEN", raising=False)
    monkeypatch.delenv("TRAIL_API_TOKEN", raising=False)
    monkeypatch.delenv("SIM_CA_BUNDLE", raising=False)

    client = sim_result_api.SimResultClient()
    with pytest.raises(RuntimeError, match="Trail API token"):
        client._post({})

    fake_resp = MagicMock()
    fake_resp.json.return_value = {"msg": "success", "data": {}}
    with patch("ra_api.sim_result_api.requests.post", return_value=fake_resp) as post_mock:
        authed = sim_result_api.SimResultClient(app_token="explicit-test-token")
        authed._post({"hello": "world"})
    assert post_mock.call_args.kwargs["verify"] is True


def test_system_status_redacts_database_dsn_and_exposes_worker_checks():
    with SessionLocal() as db:
        result = system_status.collect_system_status(db)
    checks = {c["key"]: c for c in result["checks"]}
    assert "database" in checks
    assert "sqlite:///" not in checks["database"]["detail"]
    assert "postgresql" not in checks["database"]["detail"]
    assert "queue" in checks
    assert "last_refresh" in checks
    assert "release_workflow" in checks
    assert "label_sidecar" in checks
    assert "evaluation_worker" in checks
    assert "shuyi_session" in checks
