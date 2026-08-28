from __future__ import annotations

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .events import challenge_value, parse_event
from .relay_store import RelayStore
from .security import SecretError, read_secret_file, verify_webhook
from .settings import Settings


MAX_CALLBACK_BYTES = 256 * 1024
MAX_WORKER_BYTES = 64 * 1024


class RelayHTTPError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class RelayHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RelayHTTPError(400, "请求不是合法 JSON。") from exc
    if not isinstance(payload, dict):
        raise RelayHTTPError(400, "请求必须是 JSON 对象。")
    return payload


def _field(payload: dict[str, Any], name: str, *, maximum: int) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value or len(value) > maximum or "\0" in value:
        raise RelayHTTPError(422, f"{name} 字段非法。")
    return value


def create_server(
    settings: Settings | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> RelayHTTPServer:
    config = settings or Settings.from_env()
    config.ensure_directories()
    store = RelayStore(config.data_dir / "relay_events.sqlite3")
    store.init()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            # Do not put message bodies, identities, or credentials in access logs.
            return

        def do_GET(self) -> None:  # noqa: N802
            try:
                if self.path == "/":
                    self._respond(
                        200,
                        {
                            "service": "Auto Triage Relay",
                            "callback_path": config.base_path,
                            "worker_path": config.worker_base_path,
                        },
                    )
                    return
                if self.path == "/health":
                    self._respond(
                        200,
                        {
                            "status": "ok",
                            "enabled": config.enabled,
                            "role": "online_relay",
                            "queue": "sqlite_lease",
                            "counts": store.counts(),
                        },
                    )
                    return
                raise RelayHTTPError(404, "Not Found")
            except RelayHTTPError as exc:
                self._respond(exc.status, {"detail": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            try:
                if self.path == "/":
                    self._callback()
                elif self.path == "/pull":
                    self._pull()
                elif self.path == "/ack":
                    self._ack()
                elif self.path == "/nack":
                    self._nack()
                else:
                    raise RelayHTTPError(404, "Not Found")
            except RelayHTTPError as exc:
                self._respond(exc.status, {"detail": str(exc)})
            except Exception:
                self._respond(500, {"detail": "Relay 内部错误。"})

        def _body(self, *, limit: int) -> bytes:
            if self.headers.get("Transfer-Encoding"):
                raise RelayHTTPError(400, "不支持 Transfer-Encoding。")
            declared = self.headers.get("Content-Length", "").strip()
            if not declared:
                raise RelayHTTPError(411, "请求必须提供 Content-Length。")
            try:
                size = int(declared)
            except ValueError as exc:
                raise RelayHTTPError(400, "Content-Length 非法。") from exc
            if size < 0 or size > limit:
                raise RelayHTTPError(413, "请求内容过大。")
            body = self.rfile.read(size)
            if len(body) != size:
                raise RelayHTTPError(400, "请求内容不完整。")
            return body

        def _callback(self) -> None:
            if not config.enabled:
                raise RelayHTTPError(404, "Bot 未启用。")
            body = self._body(limit=MAX_CALLBACK_BYTES)
            try:
                secret = read_secret_file(config.webhook_secret_file)
            except SecretError as exc:
                raise RelayHTTPError(503, str(exc)) from exc
            signature = (
                self.headers.get("X-DChat-Signature")
                or self.headers.get("X-Auto-Triage-Signature")
                or self.headers.get("Authorization", "").removeprefix("Bearer ")
            )
            if not verify_webhook(
                body=body,
                secret=secret,
                mode=config.webhook_auth_mode,
                signature=signature,
                timestamp=self.headers.get("X-DChat-Timestamp", ""),
            ):
                raise RelayHTTPError(401, "DChat 回调认证失败。")
            payload = _object(body)
            challenge = challenge_value(payload)
            if challenge:
                self._respond(200, {"challenge": challenge})
                return
            try:
                event = parse_event(payload, max_chars=config.max_question_chars)
            except ValueError as exc:
                raise RelayHTTPError(422, str(exc)) from exc
            if not config.user_allowed(event.sender):
                raise RelayHTTPError(403, "当前用户不在 Bot 灰度名单中。")
            existing = store.get(event.event_id)
            if existing:
                if existing.get("status") == "completed":
                    self._respond(200, {"text": "这个问题已经处理完成，答案已私聊发送。"})
                else:
                    self._respond(200, {"text": "这个问题正在处理，完成后会私聊发送给你。"})
                return
            store.enqueue(event)
            self._respond(200, {"text": "收到，正在处理，结果会私聊发送给你。"})

        def _worker_auth(self) -> None:
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer "):
                raise RelayHTTPError(401, "Relay worker 认证失败。")
            supplied = authorization[len("Bearer ") :].strip()
            try:
                expected = read_secret_file(config.relay_worker_secret_file).decode(
                    "utf-8"
                )
            except (SecretError, UnicodeDecodeError) as exc:
                raise RelayHTTPError(503, "Relay worker token 不可用。") from exc
            if not supplied or not hmac.compare_digest(supplied, expected):
                raise RelayHTTPError(401, "Relay worker 认证失败。")

        def _pull(self) -> None:
            if not config.enabled:
                raise RelayHTTPError(404, "Relay 未启用。")
            self._worker_auth()
            payload = _object(self._body(limit=MAX_WORKER_BYTES))
            worker_id = _field(payload, "worker_id", maximum=64)
            if worker_id != config.relay_worker_id:
                raise RelayHTTPError(403, "Relay worker ID 不匹配。")
            item = store.claim_next(
                worker_id=worker_id,
                lease_seconds=config.relay_lease_seconds,
                max_attempts=config.relay_max_attempts,
            )
            if item is None:
                self._respond(204, None)
                return
            self._respond(200, item)

        def _ack(self) -> None:
            self._worker_auth()
            payload = _object(self._body(limit=MAX_WORKER_BYTES))
            accepted = store.ack(
                event_id=_field(payload, "event_id", maximum=256),
                lease_token=_field(payload, "lease_token", maximum=256),
                delivery_id=str(payload.get("delivery_id") or "")[:256],
            )
            if not accepted:
                raise RelayHTTPError(409, "Relay lease 已失效。")
            self._respond(200, {"ok": True})

        def _nack(self) -> None:
            self._worker_auth()
            payload = _object(self._body(limit=MAX_WORKER_BYTES))
            accepted = store.nack(
                event_id=_field(payload, "event_id", maximum=256),
                lease_token=_field(payload, "lease_token", maximum=256),
                error=str(payload.get("error") or "Worker processing failed.")[:500],
                terminal=payload.get("terminal") is True,
                max_attempts=config.relay_max_attempts,
            )
            if not accepted:
                raise RelayHTTPError(409, "Relay lease 已失效。")
            self._respond(200, {"ok": True})

        def _respond(self, status: int, payload: dict[str, Any] | None) -> None:
            content = (
                b""
                if payload is None
                else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            )
            self.send_response(status)
            if payload is not None:
                self.send_header("Content-Type", "application/json;charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            if content:
                self.wfile.write(content)

    server = RelayHTTPServer(
        (host if host is not None else config.host, port if port is not None else config.port),
        Handler,
    )
    server.relay_store = store  # type: ignore[attr-defined]
    return server


def run() -> None:
    server = create_server()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
