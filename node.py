from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from typing import Any

from .civitai_publisher.approval import APPROVALS, ApprovalPayload, DecisionState
from .civitai_publisher.client import CivitAIClient, build_civitai_metadata
from .civitai_publisher.media import materialize_media
from .civitai_publisher.workflow import (
    discover_and_hash_resources,
    extract_generation_metadata,
)

DESCRIPTION = "Created with ComfyUI and CivitAI Publisher by HearmemanAI."


def resolve_civitai_token() -> str:
    return (
        os.environ.get("CIVITAI_TOKEN", "").strip()
        or os.environ.get("CIVITAI_API_KEY", "").strip()
        or os.environ.get("civitai_token", "").strip()
    )


def _interrupt_check() -> None:
    try:
        import comfy.model_management

        comfy.model_management.throw_exception_if_processing_interrupted()
    except ImportError:
        return


def _notify_review(payload: dict[str, Any]) -> None:
    try:
        from server import PromptServer
    except ImportError as exc:
        raise RuntimeError("ComfyUI browser server is unavailable; nothing was uploaded") from exc
    server = PromptServer.instance
    if server is None or server.client_id is None:
        raise RuntimeError("No ComfyUI browser is connected for publication approval; nothing was uploaded")
    server.send_sync("civitai_publisher.review", payload, server.client_id)


def _notify_review_closed(request_id: str) -> None:
    try:
        from server import PromptServer

        server = PromptServer.instance
        if server is not None and server.client_id is not None:
            server.send_sync(
                "civitai_publisher.closed",
                {"request_id": request_id},
                server.client_id,
            )
    except Exception:
        # Closing the browser surface is best-effort terminal cleanup. It must
        # never turn a safe reject, timeout, or interruption into a node error.
        return


def _parse_tags(value: str) -> tuple[str, ...]:
    tags: list[str] = []
    for raw in value.split(","):
        tag = raw.strip()[:100]
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 50:
            break
    return tuple(tags)


class CivitAIPublisher:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "title": ("STRING", {"default": "", "placeholder": "Optional CivitAI post title"}),
                "tags": ("STRING", {"default": "", "placeholder": "comma, separated, tags"}),
                "nsfw": ("BOOLEAN", {"default": False}),
                "prompt_override": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "placeholder": "Optional. Blank uses the prompt detected from this workflow.",
                    },
                ),
                "approval_timeout_minutes": (
                    "INT",
                    {"default": 30, "min": 1, "max": 240, "step": 1, "display": "number"},
                ),
            },
            "optional": {
                "image": ("IMAGE",),
                "video": ("VIDEO",),
            },
            "hidden": {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("post_url", "status", "details")
    FUNCTION = "publish"
    CATEGORY = "HearmemanAI/CivitAI"
    DESCRIPTION = "Publish IMAGE or VIDEO to CivitAI only after an in-canvas review and explicit approval."
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    async def publish(
        self,
        title: str,
        tags: str,
        nsfw: bool,
        prompt_override: str,
        approval_timeout_minutes: int,
        image: Any | None = None,
        video: Any | None = None,
        prompt: dict[str, Any] | None = None,
        unique_id: str | None = None,
    ):
        if image is None and video is None:
            raise ValueError("Connect an IMAGE or VIDEO before queueing CivitAI Publisher")
        token = resolve_civitai_token()
        if not token:
            raise ValueError(
                "Set CIVITAI_TOKEN in the ComfyUI environment "
                "(CIVITAI_API_KEY and legacy civitai_token are also accepted)"
            )

        api_prompt = prompt if isinstance(prompt, dict) else {}
        generation = extract_generation_metadata(api_prompt, prompt_override=prompt_override)
        requested_tags = _parse_tags(tags)

        async with materialize_media(image=image, video=video) as media:
            resources = await asyncio.to_thread(
                discover_and_hash_resources,
                api_prompt,
                cancel=_interrupt_check,
            )
            _interrupt_check()
            client = CivitAIClient(token)
            resolved_resources = await client.resolve_resources(resources)

            payload = ApprovalPayload(
                node_id=str(unique_id or ""),
                title=title.strip(),
                prompt=generation.prompt,
                negative_prompt=generation.negative_prompt,
                tags=requested_tags,
                nsfw=bool(nsfw),
                media=media.previews,
                resources=tuple(resource.public() for resource in resolved_resources),
            )
            decision = await APPROVALS.wait_for_decision(
                payload,
                timeout_seconds=float(approval_timeout_minutes) * 60,
                notify=_notify_review,
                notify_closed=_notify_review_closed,
                interrupt_check=_interrupt_check,
            )
            if decision.state is DecisionState.REJECTED:
                return "", "rejected", json.dumps(
                    {"uploaded": False, "reason": "rejected", "resource_count": len(resolved_resources)},
                    separators=(",", ":"),
                )
            if decision.state is DecisionState.TIMED_OUT:
                raise RuntimeError("CivitAI review timed out; nothing was uploaded")

            reviewed_generation = replace(generation, prompt=decision.prompt)
            first = media.uploads[0]
            metadata = build_civitai_metadata(
                reviewed_generation,
                resolved_resources,
                width=first.width,
                height=first.height,
            )
            _interrupt_check()
            result = await client.publish_post(
                media=media.uploads,
                title=decision.title,
                description=DESCRIPTION,
                tags=decision.tags,
                nsfw=decision.nsfw,
                metadata=metadata,
            )
            details = {
                "uploaded": True,
                "post_id": result.post_id,
                "media_count": len(media.uploads),
                "resource_count": len(resolved_resources),
                "resolved_resource_count": sum(resource.resolved for resource in resolved_resources),
            }
            return result.post_url, "published", json.dumps(details, separators=(",", ":"))


NODE_CLASS_MAPPINGS = {"CivitAIPublisher": CivitAIPublisher}
NODE_DISPLAY_NAME_MAPPINGS = {"CivitAIPublisher": "CivitAI Publisher (Review Before Upload)"}
