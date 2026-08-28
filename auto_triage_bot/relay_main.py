from __future__ import annotations

import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .events import challenge_value, parse_event
from .relay_store import RelayStore
from .security import SecretError, read_secret_file, verify_webhook
from .settings import Settings


MAX_CALLBACK_BYTES = 256 * 1024
MAX_WORKER_BYTES = 64 * 1024


async def _bounded_body(request: Request, *, limit: int) -> bytes:
    declared = request.headers.get("content-length", "").strip()
    if declared:
        try:
            size = int(declared)
        except ValueError as exc:
            raise HTTPException(400, "Content-Length 非法。") from exc
        if size < 0 or size > limit:
            raise HTTPException(413, "请求内容过大。")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > limit:
            raise HTTPException(413, "请求内容过大。")
    return bytes(content)


def _object(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "请求不是合法 JSON。") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "请求必须是 JSON 对象。")
    return payload


async def _worker_auth(request: Request, config: Settings) -> None:
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Relay worker 认证失败。")
    supplied = authorization[len("Bearer ") :].strip()
    try:
        expected = (
            await asyncio.to_thread(read_secret_file, config.relay_worker_secret_file)
        ).decode("utf-8")
    except (SecretError, UnicodeDecodeError) as exc:
        raise HTTPException(503, "Relay worker token 不可用。") from exc
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Relay worker 认证失败。")


def _field(payload: dict[str, Any], name: str, *, maximum: int) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value or len(value) > maximum or "\0" in value:
        raise HTTPException(422, f"{name} 字段非法。")
    return value


def create_relay_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    store = RelayStore(config.data_dir / "relay_events.sqlite3")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        config.ensure_directories()
        await asyncio.to_thread(store.init)
        yield

    # Kylin strips /dchat and /dchat-worker before forwarding both entries to
    # this dedicated process. Therefore callback is / and worker APIs are
    # /pull, /ack and /nack at the upstream.
    app = FastAPI(title="Auto Triage Relay", version="0.1.0", lifespan=lifespan)

    @app.get("/")
    async def service_info() -> dict[str, object]:
        return {
            "service": "Auto Triage Relay",
            "callback_path": config.base_path,
            "worker_path": config.worker_base_path,
        }

    @app.get("/health")
    async def health() -> dict[str, object]:
        counts = await asyncio.to_thread(store.counts)
        return {
            "status": "ok",
            "enabled": config.enabled,
            "role": "online_relay",
            "queue": "sqlite_lease",
            "counts": counts,
        }

    @app.post("/")
    async def callback(request: Request) -> JSONResponse:
        if not config.enabled:
            raise HTTPException(404, "Bot 未启用。")
        body = await _bounded_body(request, limit=MAX_CALLBACK_BYTES)
        try:
            secret = await asyncio.to_thread(read_secret_file, config.webhook_secret_file)
        except SecretError as exc:
            raise HTTPException(503, str(exc)) from exc
        signature = (
            request.headers.get("x-dchat-signature")
            or request.headers.get("x-auto-triage-signature")
            or request.headers.get("authorization", "").removeprefix("Bearer ")
        )
        if not verify_webhook(
            body=body,
            secret=secret,
            mode=config.webhook_auth_mode,
            signature=signature,
            timestamp=request.headers.get("x-dchat-timestamp", ""),
        ):
            raise HTTPException(401, "DChat 回调认证失败。")
        payload = _object(body)
        challenge = challenge_value(payload)
        if challenge:
            return JSONResponse({"challenge": challenge})
        try:
            event = parse_event(payload, max_chars=config.max_question_chars)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not config.user_allowed(event.sender):
            raise HTTPException(403, "当前用户不在 Bot 灰度名单中。")
        existing = await asyncio.to_thread(store.get, event.event_id)
        if existing:
            if existing.get("status") == "completed":
                return JSONResponse({"text": "这个问题已经处理完成，答案已私聊发送。"})
            return JSONResponse({"text": "这个问题正在处理，完成后会私聊发送给你。"})
        await asyncio.to_thread(store.enqueue, event)
        return JSONResponse({"text": "收到，正在处理，结果会私聊发送给你。"})

    @app.post("/pull")
    async def pull(request: Request) -> Response:
        if not config.enabled:
            raise HTTPException(404, "Relay 未启用。")
        await _worker_auth(request, config)
        payload = _object(await _bounded_body(request, limit=MAX_WORKER_BYTES))
        worker_id = _field(payload, "worker_id", maximum=64)
        if worker_id != config.relay_worker_id:
            raise HTTPException(403, "Relay worker ID 不匹配。")
        item = await asyncio.to_thread(
            store.claim_next,
            worker_id=worker_id,
            lease_seconds=config.relay_lease_seconds,
            max_attempts=config.relay_max_attempts,
        )
        if item is None:
            return Response(status_code=204)
        return JSONResponse(item)

    @app.post("/ack")
    async def ack(request: Request) -> JSONResponse:
        await _worker_auth(request, config)
        payload = _object(await _bounded_body(request, limit=MAX_WORKER_BYTES))
        accepted = await asyncio.to_thread(
            store.ack,
            event_id=_field(payload, "event_id", maximum=256),
            lease_token=_field(payload, "lease_token", maximum=256),
            delivery_id=str(payload.get("delivery_id") or "")[:256],
        )
        if not accepted:
            raise HTTPException(409, "Relay lease 已失效。")
        return JSONResponse({"ok": True})

    @app.post("/nack")
    async def nack(request: Request) -> JSONResponse:
        await _worker_auth(request, config)
        payload = _object(await _bounded_body(request, limit=MAX_WORKER_BYTES))
        error = str(payload.get("error") or "Worker processing failed.")[:500]
        accepted = await asyncio.to_thread(
            store.nack,
            event_id=_field(payload, "event_id", maximum=256),
            lease_token=_field(payload, "lease_token", maximum=256),
            error=error,
            terminal=payload.get("terminal") is True,
            max_attempts=config.relay_max_attempts,
        )
        if not accepted:
            raise HTTPException(409, "Relay lease 已失效。")
        return JSONResponse({"ok": True})

    app.state.bot_settings = config
    app.state.relay_store = store
    return app


app = create_relay_app()
