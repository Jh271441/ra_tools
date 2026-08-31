from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .events import challenge_value, parse_event
from .security import SecretError, read_secret_file, verify_webhook
from .settings import Settings


MAX_CALLBACK_BYTES = 256 * 1024
logger = logging.getLogger("auto_triage_bot.thin")


class ThinHTTPError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class ThinHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ThinHTTPError(400, "请求不是合法 JSON。") from exc
    if not isinstance(payload, dict):
        raise ThinHTTPError(400, "请求必须是 JSON 对象。")
    return payload


def template_reply(question: str) -> str:
    """Return a deterministic reply without calling any other service."""
    normalized = question.strip().lower()
    if normalized in {"hi", "hello", "你好", "您好", "嗨"}:
        return (
            "你好，我是 Auto Triage Bot（鲁班直连测试版）。\n\n"
            "✅ DChat 回调已到达鲁班，固定模板回复成功。\n"
            "当前不会访问 Cloud Server、看板或大模型。"
        )
    if normalized in {"help", "帮助", "使用帮助"}:
        return (
            "这是 Auto Triage Bot 的鲁班直连测试服务。\n\n"
            "✅ 当前只验证 DChat 回调和同步回复链路；"
            "不会访问 Cloud Server、看板或大模型。"
        )
    return (
        "✅ 鲁班直连验证成功：DChat 回调已到达服务并完成同步回复。\n\n"
        "当前为固定模板测试模式，不访问 Cloud Server、看板或大模型。"
    )


def create_server(
    settings: Settings | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> ThinHTTPServer:
    config = settings or Settings.from_env()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            # Callback payloads can contain private chat content and identities.
            return

        def do_GET(self) -> None:  # noqa: N802
            try:
                if self.path == "/":
                    self._respond(
                        200,
                        {
                            "service": "Auto Triage Bot Thin Callback",
                            "role": "luban_direct_template",
                            "callback_path": config.base_path,
                        },
                    )
                    return
                if self.path == "/health":
                    self._respond(
                        200,
                        {
                            "status": "ok",
                            "enabled": config.enabled,
                            "role": "luban_direct_template",
                            "cloud_server": False,
                            "dashboard": False,
                            "model": False,
                            "dchat_openapi": False,
                        },
                    )
                    return
                raise ThinHTTPError(404, "Not Found")
            except ThinHTTPError as exc:
                self._respond(exc.status, {"detail": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            try:
                if self.path != "/":
                    raise ThinHTTPError(404, "Not Found")
                self._callback()
            except ThinHTTPError as exc:
                logger.warning(
                    "thin callback rejected path=%s status=%s reason=%s "
                    "content_type=%s content_length=%s",
                    self.path[:128],
                    exc.status,
                    str(exc),
                    self.headers.get("Content-Type", "")[:128],
                    self.headers.get("Content-Length", "")[:32],
                )
                self._respond(exc.status, {"detail": str(exc)})
            except Exception:
                logger.exception("thin callback failed path=%s", self.path[:128])
                self._respond(500, {"detail": "Thin callback 内部错误。"})

        def _body(self) -> bytes:
            if self.headers.get("Transfer-Encoding"):
                raise ThinHTTPError(400, "不支持 Transfer-Encoding。")
            declared = self.headers.get("Content-Length", "").strip()
            if not declared:
                raise ThinHTTPError(411, "请求必须提供 Content-Length。")
            try:
                size = int(declared)
            except ValueError as exc:
                raise ThinHTTPError(400, "Content-Length 非法。") from exc
            if size < 0 or size > MAX_CALLBACK_BYTES:
                raise ThinHTTPError(413, "请求内容过大。")
            body = self.rfile.read(size)
            if len(body) != size:
                raise ThinHTTPError(400, "请求内容不完整。")
            return body

        def _callback(self) -> None:
            if not config.enabled:
                raise ThinHTTPError(404, "Bot 未启用。")
            body = self._body()
            try:
                secret = read_secret_file(config.webhook_secret_file)
            except SecretError as exc:
                raise ThinHTTPError(503, str(exc)) from exc
            signature = (
                self.headers.get("X-DChat-Signature", "")
                or self.headers.get("X-Auto-Triage-Signature", "")
            )
            if not verify_webhook(
                body=body,
                secret=secret,
                mode=config.webhook_auth_mode,
                signature=signature,
                timestamp=self.headers.get("X-DChat-Timestamp", ""),
            ):
                raise ThinHTTPError(401, "DChat 回调认证失败。")
            payload = _object(body)
            challenge = challenge_value(payload)
            if challenge:
                self._respond(200, {"challenge": challenge})
                return
            try:
                event = parse_event(payload, max_chars=config.max_question_chars)
            except ValueError as exc:
                raise ThinHTTPError(422, str(exc)) from exc
            if not config.user_allowed(event.sender):
                raise ThinHTTPError(403, "当前用户不在 Bot 灰度名单中。")
            self._respond(200, {"text": template_reply(event.text)})

        def _respond(self, status: int, payload: dict[str, Any]) -> None:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json;charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(content)

    return ThinHTTPServer(
        (host if host is not None else config.host, port if port is not None else config.port),
        Handler,
    )


def run() -> None:
    server = create_server()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
