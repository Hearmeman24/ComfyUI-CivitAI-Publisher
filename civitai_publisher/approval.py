from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DecisionState(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class ApprovalPayload:
    node_id: str
    title: str
    prompt: str
    tags: tuple[str, ...] = ()
    nsfw: bool = False
    negative_prompt: str = ""
    media: tuple[dict[str, Any], ...] = ()
    resources: tuple[dict[str, Any], ...] = ()

    def public(self, request_id: str) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "node_id": self.node_id,
            "title": self.title,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "tags": list(self.tags),
            "nsfw": self.nsfw,
            "media": list(self.media),
            "resources": list(self.resources),
        }


@dataclass(frozen=True)
class ApprovalDecision:
    state: DecisionState
    title: str
    prompt: str
    tags: tuple[str, ...]
    nsfw: bool


@dataclass
class _Pending:
    request_id: str
    payload: ApprovalPayload
    future: asyncio.Future[ApprovalDecision]
    loop: asyncio.AbstractEventLoop
    created_at: float = field(default_factory=time.time)


def _text(value: Any, fallback: str, maximum: int) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    return normalized[:maximum]


def _tags(value: Any, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return fallback
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        tag = item.strip()[:100]
        if tag and tag not in result:
            result.append(tag)
        if len(result) >= 50:
            break
    return tuple(result)


class ApprovalManager:
    def __init__(self, id_factory: Callable[[], str] | None = None):
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.RLock()

    def pending_public(self) -> list[dict[str, Any]]:
        with self._lock:
            pending = sorted(self._pending.values(), key=lambda item: item.created_at)
            return [item.payload.public(item.request_id) for item in pending]

    def decide(self, request_id: str, *, approved: bool, edits: dict[str, Any]) -> bool:
        with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is None or pending.future.done():
                return False
            payload = pending.payload
            decision = ApprovalDecision(
                state=DecisionState.APPROVED if approved else DecisionState.REJECTED,
                title=_text(edits.get("title"), payload.title, 200),
                prompt=_text(edits.get("prompt"), payload.prompt, 20_000),
                tags=_tags(edits.get("tags"), payload.tags),
                nsfw=bool(edits.get("nsfw", payload.nsfw)),
            )

        def deliver() -> None:
            if not pending.future.done():
                pending.future.set_result(decision)

        pending.loop.call_soon_threadsafe(deliver)
        return True

    async def wait_for_decision(
        self,
        payload: ApprovalPayload,
        *,
        timeout_seconds: float,
        notify: Callable[[dict[str, Any]], None],
        notify_closed: Callable[[str], None] | None = None,
        interrupt_check: Callable[[], None] | None = None,
    ) -> ApprovalDecision:
        loop = asyncio.get_running_loop()
        request_id = self._id_factory()
        future: asyncio.Future[ApprovalDecision] = loop.create_future()
        pending = _Pending(request_id=request_id, payload=payload, future=future, loop=loop)
        with self._lock:
            self._pending[request_id] = pending
        try:
            notify(payload.public(request_id))
            deadline = loop.time() + max(0.0, timeout_seconds)
            while True:
                if interrupt_check is not None:
                    interrupt_check()
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return ApprovalDecision(
                        DecisionState.TIMED_OUT,
                        payload.title,
                        payload.prompt,
                        payload.tags,
                        payload.nsfw,
                    )
                try:
                    return await asyncio.wait_for(asyncio.shield(future), timeout=min(0.1, remaining))
                except TimeoutError:
                    continue
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            if notify_closed is not None:
                notify_closed(request_id)


APPROVALS = ApprovalManager()
