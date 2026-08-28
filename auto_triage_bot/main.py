from __future__ import annotations

import asyncio
import contextlib
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .events import challenge_value, parse_event
from .security import SecretError, read_secret_file, verify_webhook
from .service import BotWorker
from .settings import Settings
from .store import EventStore


MAX_WEBHOOK_BYTES = 256 * 1024


async def _bounded_body(request: Request) -> bytes:
    declared = request.headers.get("content-length", "").strip()
    if declared:
        try:
            size = int(declared)
        except ValueError as exc:
            raise HTTPException(400, "Content-Length 非法。") from exc
        if size < 0 or size > MAX_WEBHOOK_BYTES:
            raise HTTPException(413, "DChat 回调内容过大。")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_WEBHOOK_BYTES:
            raise HTTPException(413, "DChat 回调内容过大。")
    return bytes(content)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    store = EventStore(config.data_dir / "bot_events.sqlite3")
    worker = BotWorker(settings=config, store=store)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        config.ensure_directories()
        await asyncio.to_thread(store.init)
        task = asyncio.create_task(worker.run(), name="auto-triage-bot-worker")
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # Kylin exposes only ``config.base_path`` and strips that prefix before
    # forwarding to this dedicated 8790 process, matching Dashboard /manual.
    # The backend-root routes below therefore never claim the public domain root.
    app = FastAPI(
        title="Auto Triage Bot",
        version="0.1.0",
        root_path=config.base_path,
        lifespan=lifespan,
    )

    @app.get("/")
    async def service_info() -> dict[str, object]:
        return {
            "service": "Auto Triage Bot",
            "callback_path": config.base_path,
            "smoke_path": f"{config.base_path}/smoke",
        }

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "enabled": config.enabled,
            "smoke_enabled": config.smoke_enabled,
            "delivery_mode": config.delivery_mode,
            "model_configured": bool(config.model_id),
            "dashboard_mode": "read_only_loopback",
        }

    @app.api_route("/smoke", methods=["GET", "POST"])
    async def dchat_smoke() -> JSONResponse:
        if not config.smoke_enabled:
            raise HTTPException(404, "Smoke endpoint 未启用。")
        return JSONResponse({"text": "Auto Triage Bot callback is reachable."})

    @app.post("/")
    async def dchat_events(request: Request) -> JSONResponse:
        if not config.enabled:
            raise HTTPException(404, "Bot 未启用。")
        body = await _bounded_body(request)
        try:
            secret = await asyncio.to_thread(read_secret_file, config.webhook_secret_file)
        except SecretError as exc:
            raise HTTPException(503, str(exc)) from exc
        signature = (
            request.headers.get("x-dchat-signature")
            or request.headers.get("x-auto-triage-signature")
            or request.headers.get("authorization", "").removeprefix("Bearer ")
        )
        timestamp = request.headers.get("x-dchat-timestamp", "")
        if not verify_webhook(
            body=body,
            secret=secret,
            mode=config.webhook_auth_mode,
            signature=signature,
            timestamp=timestamp,
        ):
            raise HTTPException(401, "DChat 回调认证失败。")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(400, "DChat 回调不是合法 JSON。") from exc
        if not isinstance(payload, dict):
            raise HTTPException(400, "DChat 回调必须是 JSON 对象。")
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
            if existing.get("status") == "completed" and existing.get("answer"):
                return JSONResponse({"text": str(existing["answer"])})
            return JSONResponse({"text": "这个问题正在处理，完成后会私聊发送给你。"})
        created = await asyncio.to_thread(store.enqueue, event)
        if created:
            worker.wake()
        # BotUser requires a message response within five seconds. The actual
        # dashboard/LLM work remains asynchronous and is delivered through
        # OpenAPI so a slow model call cannot make D-Chat retry the callback.
        return JSONResponse({"text": "收到，正在处理，结果会私聊发送给你。"})

    app.state.bot_settings = config
    app.state.bot_store = store
    app.state.bot_worker = worker
    return app


app = create_app()
