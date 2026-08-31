from __future__ import annotations

from typing import Any

from .approval import APPROVALS


def register_routes() -> None:
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError:
        return

    @PromptServer.instance.routes.get("/civitai_publisher/pending")
    async def pending_reviews(_request):
        return web.json_response({"pending": APPROVALS.pending_public()})

    @PromptServer.instance.routes.post("/civitai_publisher/decision")
    async def decide_review(request):
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)
        request_id = body.get("request_id")
        decision = body.get("decision")
        if not isinstance(request_id, str) or decision not in {"approve", "reject"}:
            return web.json_response(
                {"ok": False, "error": "request_id and approve/reject decision are required"},
                status=400,
            )
        accepted = APPROVALS.decide(
            request_id,
            approved=decision == "approve",
            edits=body.get("edits") if isinstance(body.get("edits"), dict) else {},
        )
        if not accepted:
            return web.json_response(
                {"ok": False, "error": "review is missing or already decided"},
                status=409,
            )
        return web.json_response({"ok": True})
