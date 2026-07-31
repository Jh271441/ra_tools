from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .settings import Settings


MODEL_ID_RE = re.compile(r"^[A-Za-z0-9._/@:+-]{1,160}$")
PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_CATALOG_BYTES = 1024 * 1024
MAX_MODELS = 500
MAX_SECRET_BYTES = 4096
MIN_MANUAL_REFRESH_SECONDS = 15


class ModelCatalogError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        public_message: str,
        *,
        stale_eligible: bool = False,
    ):
        super().__init__(public_message)
        self.status_code = status_code
        self.public_message = public_message
        self.stale_eligible = stale_eligible


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_PROVIDER_HOSTS = {
    "kylin": "ra-model.intra.xiaojukeji.com",
    "tokenservice": "tokenservice-gateway-ys.intra.xiaojukeji.com",
}


def _gateway_url(value: str, *, expected_path: str, provider_id: str = "kylin") -> str:
    parsed = urlsplit(str(value or "").strip())
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != expected_path.rstrip("/")
    ):
        raise ModelCatalogError(503, "服务器模型网关地址配置非法。")
    allowed_hosts = {
        _PROVIDER_HOSTS.get(str(provider_id or "").strip(), ""),
        # Localhost is useful for isolated smoke tests, but remains opt-in via
        # the server environment and never comes from the browser.
        "localhost",
        "127.0.0.1",
    }
    allowed = host in allowed_hosts
    if not allowed:
        raise ModelCatalogError(503, "服务器模型网关必须位于可信内网。")
    return parsed.geturl()


def _provider_config(settings: Settings, provider_id: str) -> dict[str, Any]:
    provider = str(provider_id or "kylin").strip().lower() or "kylin"
    if provider == "kylin":
        return {
            "id": provider,
            "catalog_url": getattr(
                settings, "ra_model_catalog_url", "http://ra-model.intra.xiaojukeji.com/v1/models"
            ),
            "chat_url": getattr(
                settings,
                "ra_model_chat_url",
                "http://ra-model.intra.xiaojukeji.com/v1/chat/completions",
            ),
            "key_file": getattr(settings, "ra_model_api_key_file", None),
        }
    if provider == "tokenservice":
        return {
            "id": provider,
            "catalog_url": getattr(
                settings,
                "ra_model_tokenservice_catalog_url",
                "https://tokenservice-gateway-ys.intra.xiaojukeji.com/v1/models",
            ),
            "chat_url": getattr(
                settings,
                "ra_model_tokenservice_chat_url",
                "https://tokenservice-gateway-ys.intra.xiaojukeji.com/v1/chat/completions",
            ),
            "key_file": getattr(settings, "ra_model_tokenservice_api_key_file", None),
        }
    raise ModelCatalogError(400, "不支持的模型 Provider。")


def model_gateway_chat_url(settings: Settings, provider_id: str = "kylin") -> str:
    config = _provider_config(settings, provider_id)
    return _gateway_url(
        config["chat_url"],
        expected_path="/v1/chat/completions",
        provider_id=config["id"],
    )


def _open_provider_api_key(settings: Settings, provider_id: str = "kylin") -> int:
    path = _provider_config(settings, provider_id).get("key_file")
    if not path:
        raise ModelCatalogError(503, "服务器尚未配置模型网关密钥。")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise ModelCatalogError(503, "服务器尚未配置模型网关密钥。")
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise ModelCatalogError(
                503,
                "模型网关密钥必须是当前服务用户持有的 0600 普通文件。",
            )
        if info.st_size <= 0 or info.st_size > MAX_SECRET_BYTES:
            raise ModelCatalogError(503, "模型网关密钥文件大小非法。")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def read_provider_api_key(settings: Settings, provider_id: str = "kylin") -> str:
    descriptor = _open_provider_api_key(settings, provider_id)
    try:
        raw = os.read(descriptor, MAX_SECRET_BYTES + 1)
    finally:
        os.close(descriptor)
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise ModelCatalogError(503, "服务器模型网关密钥配置非法。")
    if value.lower().startswith("apikey:"):
        value = value[7:].strip()
    if not value or len(value.encode("utf-8")) > MAX_SECRET_BYTES or any(
        char in value for char in "\r\n\0"
    ):
        raise ModelCatalogError(503, "服务器模型网关密钥配置非法。")
    return value


def _open_model_gateway_api_key(settings: Settings) -> int:
    """Backward-compatible Kylin key helper for existing callers/tests."""
    return _open_provider_api_key(settings, "kylin")


def read_model_gateway_api_key(settings: Settings) -> str:
    """Backward-compatible Kylin key helper for existing callers/tests."""
    return read_provider_api_key(settings, "kylin")


class ModelCatalog:
    """Server-owned Qwen3 discovery with validated and experimental tiers."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._expires_at: dict[str, float] = {}
        self._next_manual_refresh_at: dict[str, float] = {}

    def status(self) -> dict[str, Any]:
        try:
            descriptor = _open_provider_api_key(self.settings, "kylin")
        except ModelCatalogError:
            configured = False
        else:
            os.close(descriptor)
            configured = True
        return {
            "configured": configured,
            "catalog_label": "ra-model.intra.xiaojukeji.com/v1/models",
            "default_model_id": self.settings.ra_model_default_id,
            "credential_source": "server",
        }

    def provider_catalog(self) -> dict[str, Any]:
        """Return safe metadata for server-owned providers.

        Provider names/endpoints are server-owned.  The browser receives only
        sanitized metadata; credentials are read from per-provider 0600 files
        when a Batch worker is launched.
        """
        providers: dict[str, dict[str, Any]] = {}

        def endpoint_summary(value: Any) -> str:
            parsed = urlsplit(str(value or "").strip())
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return ""
            host = parsed.hostname
            if parsed.port:
                host = f"{host}:{parsed.port}"
            path = parsed.path.rstrip("/")
            return f"{parsed.scheme}://{host}{path}"

        def add_provider(
            provider_id: str,
            *,
            base_url: Any = "",
            configured: bool = False,
            source: str = "ra_auto_triage/config.yml",
            supports_batch: bool = False,
            note: str = "",
        ) -> None:
            provider_id = str(provider_id or "").strip()
            if not PROVIDER_ID_RE.fullmatch(provider_id):
                return
            endpoint = endpoint_summary(base_url)
            providers[provider_id] = {
                "id": provider_id,
                "display_name": {
                    "kylin": "Kylin · RA Model 网关",
                    "tokenservice": "TokenService 网关",
                }.get(provider_id, provider_id),
                "endpoint": endpoint,
                "credential_configured": bool(configured),
                "credential_source": source,
                "supports_batch": bool(supports_batch),
                "enabled": bool(supports_batch and configured),
                "note": note,
            }

        key_configured = False
        try:
            descriptor = _open_model_gateway_api_key(self.settings)
        except (AttributeError, ModelCatalogError, OSError):
            pass
        else:
            os.close(descriptor)
            key_configured = True
        add_provider(
            "kylin",
            base_url=getattr(self.settings, "ra_model_chat_url", ""),
            configured=key_configured,
            source="dashboard server key file",
            supports_batch=True,
            note="当前 Camera-only Batch 执行 Provider；Ares / BEV 固定关闭。",
        )

        tokenservice_configured = False
        try:
            descriptor = _open_provider_api_key(self.settings, "tokenservice")
        except (AttributeError, ModelCatalogError, OSError):
            pass
        else:
            os.close(descriptor)
            tokenservice_configured = True
        add_provider(
            "tokenservice",
            base_url=getattr(
                self.settings,
                "ra_model_tokenservice_chat_url",
                "https://tokenservice-gateway-ys.intra.xiaojukeji.com/v1/chat/completions",
            ),
            configured=tokenservice_configured,
            source="dashboard server tokenservice key file",
            supports_batch=True,
            note="Camera-only Batch Provider；模型目录按 TokenService 网关读取，Ares / BEV 固定关闭。",
        )

        # Read only provider names/endpoints from the checked-out RA config.
        # This deliberately avoids a YAML dependency and never serializes the
        # api_key value.  The file is an operator-owned server source of truth.
        config_path = getattr(self.settings, "ra_auto_triage_root", None)
        config_path = Path(config_path) / "config.yml" if config_path else None
        if config_path and config_path.is_file():
            try:
                lines = config_path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                lines = []
            inside = False
            current = ""
            current_base = ""
            current_key = False

            def flush() -> None:
                nonlocal current, current_base, current_key
                if current:
                    add_provider(
                        current,
                        base_url=current_base,
                        # A config.yml api_key only proves that the source
                        # checkout mentions a Provider.  Actual execution is
                        # enabled only when its dashboard-owned 0600 key file
                        # was provisioned above.
                        configured=(
                            bool(providers.get(current, {}).get("credential_configured"))
                            if current in {"kylin", "tokenservice"}
                            else False
                        ),
                        source=(
                            (
                                "dashboard server key file"
                                if current == "kylin"
                                else "dashboard server tokenservice key file"
                            )
                            if current in {"kylin", "tokenservice"}
                            else "ra_auto_triage/config.yml"
                        ),
                        supports_batch=current in {"kylin", "tokenservice"},
                        note=(
                            "源仓库已配置；请先在 dashboard data 中登记 0600 Provider key。"
                            if current not in {"kylin", "tokenservice"}
                            else providers.get(current, {}).get("note", "")
                        ),
                    )
                current = ""
                current_base = ""
                current_key = False

            for line in lines:
                if re.match(r"^vision_model:\s*$", line):
                    inside = False
                    flush()
                    continue
                if re.match(r"^\s{2}providers:\s*$", line):
                    inside = True
                    continue
                if not inside:
                    continue
                provider_match = re.match(r"^\s{4}([A-Za-z0-9_.-]+):\s*$", line)
                if provider_match:
                    flush()
                    current = provider_match.group(1)
                    continue
                if re.match(r"^\s{2}\S", line):
                    flush()
                    inside = False
                    continue
                if not current:
                    continue
                base_match = re.match(r"^\s{6}base_url:\s*(.*?)\s*$", line)
                if base_match:
                    current_base = base_match.group(1).strip().strip("\"'")
                    continue
                key_match = re.match(r"^\s{6}api_key:\s*(.*?)\s*$", line)
                if key_match:
                    raw_key = key_match.group(1).strip().strip("\"'")
                    current_key = bool(raw_key and raw_key.lower() not in {"null", "none", "''", '""'})
            flush()

        return {
            "providers": sorted(providers.values(), key=lambda item: (not item["enabled"], item["id"])),
            "active_provider_id": "kylin",
            "browser_credentials_allowed": False,
            "custom_provider_supported": False,
        }

    def list_models(
        self,
        *,
        refresh: bool = False,
        allow_stale: bool = True,
        provider_id: str = "kylin",
    ) -> dict[str, Any]:
        provider = str(provider_id or "kylin").strip().lower() or "kylin"
        _provider_config(self.settings, provider)
        now = time.monotonic()
        with self._lock:
            snapshot = self._snapshots.get(provider)
            if refresh:
                if now < self._next_manual_refresh_at.get(provider, 0.0):
                    raise ModelCatalogError(429, "模型目录刚刚刷新过，请稍后再试。")
                self._next_manual_refresh_at[provider] = now + MIN_MANUAL_REFRESH_SECONDS
            if not refresh and snapshot is not None and now < self._expires_at.get(provider, 0.0):
                return deepcopy(snapshot)
            try:
                snapshot = self._fetch(provider)
            except ModelCatalogError as exc:
                self._expires_at[provider] = 0.0
                if not exc.stale_eligible:
                    self._snapshots.pop(provider, None)
                if (
                    allow_stale
                    and exc.stale_eligible
                    and snapshot is not None
                ):
                    stale = deepcopy(snapshot)
                    stale["status"] = "stale"
                    stale["stale"] = True
                    stale["message"] = "模型目录刷新失败，当前仅展示上次成功缓存。"
                    return stale
                raise
            self._snapshots[provider] = snapshot
            self._expires_at[provider] = now + self.settings.ra_model_catalog_ttl_seconds
            return deepcopy(snapshot)

    def resolve(self, requested_model_id: str, provider_id: str = "kylin") -> dict[str, Any]:
        provider = str(provider_id or "kylin").strip().lower() or "kylin"
        snapshot = self.list_models(
            refresh=False,
            allow_stale=False,
            provider_id=provider,
        )
        requested = str(
            requested_model_id or snapshot["default_model_id"]
        ).strip()
        if not MODEL_ID_RE.fullmatch(requested):
            raise ModelCatalogError(400, "model_id 格式非法。")
        selected = next(
            (item for item in snapshot["models"] if item["id"] == requested),
            None,
        )
        if selected is None:
            raise ModelCatalogError(
                400,
                "所选模型不在当前在线的 RA Qwen3 可用目录中。",
            )
        return {
            "requested_model_id": requested,
            "resolved_model_id": selected["resolved_model_id"],
            "provider": selected["provider"],
            "provider_id": provider,
            "validation_status": selected["validation_status"],
            "catalog_sha256": snapshot["catalog_sha256"],
            "profile_version": snapshot["profile_version"],
            "display_name": selected["display_name"],
        }

    def _fetch_tokenservice_snapshot(
        self,
        online: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        """Build TokenService's catalog from its server-owned online list.

        TokenService exposes both the Qwen3 family and a small set of vision
        models under the Volcengine/Doubao namespace.  Keep the former broad
        (the operator may compare any Qwen3 variant), while admitting only
        Doubao models whose identifier explicitly advertises Vision/VL input.
        Text, embedding, image-generation and video-generation models stay
        out of the RA camera Batch selector.
        """
        available: list[dict[str, str]] = []
        for model_id in sorted(online):
            lowered = model_id.lower()
            is_qwen3 = "qwen3" in lowered
            is_doubao_vision = (
                "doubao" in lowered
                and ("vision" in lowered or "-vl" in lowered or "/vl" in lowered)
            )
            if (
                not (is_qwen3 or is_doubao_vision)
                or "embedding" in lowered
                or not MODEL_ID_RE.fullmatch(model_id)
            ):
                continue
            available.append(
                {
                    "id": model_id,
                    "display_name": model_id,
                    "resolved_model_id": model_id,
                    "provider": "tokenservice",
                    "input_contract": "camera_only_ra_triage",
                    "prompt_mode": "server_default",
                    "validation_status": "experimental",
                }
            )
        if not available:
            raise ModelCatalogError(
                503,
                "TokenService 当前没有可用的 Qwen3 / Doubao 视觉模型。",
                stale_eligible=True,
            )
        preferred = {"aliyun/qwen3-vl-plus", "aliyun/qwen3-vl-flash"}
        default_model_id = next(
            (item["id"] for item in available if item["id"].lower() in preferred),
            available[0]["id"],
        )
        fingerprint = {
            "provider": "tokenservice",
            "online_ids": sorted(online),
            "models": available,
            "default_model_id": default_model_id,
        }
        catalog_sha256 = hashlib.sha256(
            json.dumps(
                fingerprint,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "status": "ready",
            "stale": False,
            "message": (
                "TokenService 模型目录已刷新；"
                f"在线 Qwen3 / Doubao 视觉实验模型 {len(available)} 个，需创建 Batch 前确认。"
            ),
            "catalog_label": "tokenservice-gateway-ys.intra.xiaojukeji.com/v1/models",
            "provider_id": "tokenservice",
            "default_model_id": default_model_id,
            "models": available,
            "online_count": len(online),
            "available_count": len(available),
            "compatible_count": len(available),
            "validated_count": 0,
            "experimental_count": len(available),
            "excluded_count": max(0, len(online) - len(available)),
            "refreshed_at": _utc_now(),
            "catalog_sha256": catalog_sha256,
            "profile_version": "tokenservice-online-qwen3-doubao-vl",
        }

    def _load_profiles(self) -> dict[str, Any]:
        path = self.settings.ra_model_profile_path
        if not path.is_file():
            raise ModelCatalogError(503, "服务器缺少 RA 模型 Profile。")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            raise ModelCatalogError(503, "服务器 RA 模型 Profile 无法解析。")
        if not isinstance(payload, dict):
            raise ModelCatalogError(503, "服务器 RA 模型 Profile 格式非法。")
        return payload

    def _fetch(self, provider_id: str = "kylin") -> dict[str, Any]:
        provider = str(provider_id or "kylin").strip().lower() or "kylin"
        provider_config = _provider_config(self.settings, provider)
        catalog_url = _gateway_url(
            provider_config["catalog_url"],
            expected_path="/v1/models",
            provider_id=provider,
        )
        api_key = (
            read_model_gateway_api_key(self.settings)
            if provider == "kylin"
            else read_provider_api_key(self.settings, provider)
        )
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        auth_headers = (
            {"Authorization": f"Bearer {api_key}"}
            if provider == "tokenservice"
            else {"apikey": api_key}
        )
        request = Request(
            catalog_url,
            method="GET",
            headers={"Accept": "application/json", **auth_headers},
        )
        try:
            with opener.open(request, timeout=10) as response:
                if response.status != 200:
                    raise ModelCatalogError(
                        503,
                        "模型网关目录请求失败。",
                        stale_eligible=True,
                    )
                declared = response.headers.get("Content-Length", "").strip()
                if declared and int(declared) > MAX_CATALOG_BYTES:
                    raise ModelCatalogError(
                        503,
                        "模型网关目录响应过大。",
                        stale_eligible=True,
                    )
                raw = response.read(MAX_CATALOG_BYTES + 1)
        except ModelCatalogError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            raise ModelCatalogError(
                503,
                "模型网关目录暂时不可用。",
                stale_eligible=True,
            )
        if len(raw) > MAX_CATALOG_BYTES:
            raise ModelCatalogError(
                503,
                "模型网关目录响应过大。",
                stale_eligible=True,
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, TypeError, ValueError):
            raise ModelCatalogError(
                503,
                "模型网关目录响应格式非法。",
                stale_eligible=True,
            )
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or len(rows) > MAX_MODELS:
            raise ModelCatalogError(
                503,
                "模型网关目录响应格式非法。",
                stale_eligible=True,
            )
        online: dict[str, dict[str, str]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("id") or "").strip()
            if not MODEL_ID_RE.fullmatch(model_id):
                continue
            online[model_id] = {
                "id": model_id,
                "owned_by": str(row.get("owned_by") or "")[:120],
            }

        if provider == "tokenservice":
            return self._fetch_tokenservice_snapshot(online)

        profile = self._load_profiles()
        schema_version = profile.get("schema_version")
        if type(schema_version) is not int or schema_version != 1:
            raise ModelCatalogError(503, "服务器 RA 模型 Profile 版本不受支持。")
        models = profile.get("models")
        aliases = profile.get("aliases")
        if not isinstance(models, dict) or not isinstance(aliases, dict):
            raise ModelCatalogError(503, "服务器 RA 模型 Profile 格式非法。")
        available: list[dict[str, str]] = []
        available_ids: set[str] = set()
        for alias_id, alias in aliases.items():
            if not MODEL_ID_RE.fullmatch(str(alias_id)) or not isinstance(alias, dict):
                continue
            resolved = str(alias.get("resolved_model_id") or "").strip()
            model_profile = models.get(resolved)
            if (
                resolved not in online
                or not isinstance(model_profile, dict)
                or model_profile.get("enabled") is not True
            ):
                continue
            public_model = self._public_model(
                requested_id=str(alias_id),
                resolved_id=resolved,
                profile=model_profile,
                display_name=str(alias.get("display_name") or alias_id),
                validation_status="validated",
            )
            if public_model["id"] not in available_ids:
                available.append(public_model)
                available_ids.add(public_model["id"])
        for model_id, model_profile in models.items():
            if (
                model_id not in online
                or not MODEL_ID_RE.fullmatch(str(model_id))
                or not isinstance(model_profile, dict)
                or model_profile.get("enabled") is not True
            ):
                continue
            public_model = self._public_model(
                requested_id=str(model_id),
                resolved_id=str(model_id),
                profile=model_profile,
                display_name=str(
                    model_profile.get("display_name") or model_id
                ),
                validation_status="validated",
            )
            if public_model["id"] not in available_ids:
                available.append(public_model)
                available_ids.add(public_model["id"])

        represented_online_ids = {
            item["resolved_model_id"] for item in available
        }
        for model_id in sorted(online):
            lowered = model_id.lower()
            if (
                "qwen3" not in lowered
                or "embedding" in lowered
                or model_id in available_ids
                or model_id in represented_online_ids
            ):
                continue
            available.append(
                {
                    "id": model_id,
                    "display_name": model_id,
                    "resolved_model_id": model_id,
                    "provider": "kylin",
                    "input_contract": "camera_only_ra_triage",
                    "prompt_mode": "server_default",
                    "validation_status": "experimental",
                }
            )
            available_ids.add(model_id)
            represented_online_ids.add(model_id)
        default_model_id = str(
            profile.get("default_model_id")
            or self.settings.ra_model_default_id
            or ""
        ).strip()
        if not available or default_model_id not in {
            item["id"] for item in available
        }:
            raise ModelCatalogError(
                503,
                "默认 RA 模型当前不在线或尚未通过兼容性 Profile。",
            )
        fingerprint = {
            "profile_version": schema_version,
            "online_ids": sorted(online),
            "models": available,
            "default_model_id": default_model_id,
        }
        catalog_sha256 = hashlib.sha256(
            json.dumps(
                fingerprint,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        validated_count = sum(
            item["validation_status"] == "validated" for item in available
        )
        experimental_count = sum(
            item["validation_status"] == "experimental" for item in available
        )
        return {
            "status": "ready",
            "stale": False,
            "message": (
                "模型目录已刷新；"
                f"已验证 {validated_count} 个可选项，"
                f"实验性在线 Qwen3 {experimental_count} 个。"
            ),
            "catalog_label": "ra-model.intra.xiaojukeji.com/v1/models",
            "default_model_id": default_model_id,
            "models": available,
            "online_count": len(online),
            "available_count": len(available),
            "compatible_count": len(available),
            "validated_count": validated_count,
            "experimental_count": experimental_count,
            "excluded_count": max(
                0,
                len(online)
                - len({item["resolved_model_id"] for item in available}),
            ),
            "refreshed_at": _utc_now(),
            "catalog_sha256": catalog_sha256,
            "profile_version": schema_version,
        }

    @staticmethod
    def _public_model(
        *,
        requested_id: str,
        resolved_id: str,
        profile: dict[str, Any],
        display_name: str,
        validation_status: str = "validated",
    ) -> dict[str, str]:
        provider = str(profile.get("provider") or "").strip()
        input_contract = str(profile.get("input_contract") or "").strip()
        prompt_mode = str(profile.get("prompt_mode") or "").strip()
        if (
            provider != "kylin"
            or input_contract != "camera_only_ra_triage"
            or prompt_mode != "server_default"
        ):
            raise ModelCatalogError(503, "RA 模型 Profile 兼容性声明非法。")
        return {
            "id": requested_id,
            "display_name": display_name[:160],
            "resolved_model_id": resolved_id,
            "provider": provider,
            "input_contract": input_contract,
            "prompt_mode": prompt_mode,
            "validation_status": validation_status,
        }
