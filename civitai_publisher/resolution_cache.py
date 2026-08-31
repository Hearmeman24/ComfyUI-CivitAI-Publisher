from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import logs


@dataclass(frozen=True)
class ResolutionCacheHit:
    state: str
    payload: dict[str, Any]
    fresh: bool


class ResolutionCache:
    """Persistent CivitAI hash-resolution cache with separate positive/404 TTLs."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        clock: Callable[[], float] = time.time,
        positive_ttl_seconds: float = 24 * 60 * 60,
        missing_ttl_seconds: float = 15 * 60,
    ):
        self.path = Path(path)
        self._clock = clock
        self._positive_ttl = float(positive_ttl_seconds)
        self._missing_ttl = float(missing_ttl_seconds)
        self._lock = threading.RLock()
        self._loaded = False
        self._entries: dict[str, dict[str, Any]] = {}

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if isinstance(entries, dict):
            self._entries = {
                str(sha256): entry
                for sha256, entry in entries.items()
                if isinstance(entry, dict)
            }

    def _save(self) -> bool:
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps({"version": 1, "entries": self._entries}, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            logs.warn("resolution_cache_write_failed", error=type(error).__name__)
            return False
        return True

    def get(self, sha256: str, *, allow_stale_success: bool = False) -> ResolutionCacheHit | None:
        with self._lock:
            self._load()
            entry = self._entries.get(sha256.lower())
            if not entry:
                return None
            state = entry.get("state")
            stored_at = entry.get("stored_at")
            if state not in {"resolved", "not_found"} or not isinstance(stored_at, (int, float)):
                return None
            payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
            ttl = self._positive_ttl if state == "resolved" else self._missing_ttl
            fresh = self._clock() - float(stored_at) <= ttl
            if fresh or (allow_stale_success and state == "resolved"):
                return ResolutionCacheHit(state=state, payload=payload, fresh=fresh)
            return None

    def store_resolved(self, sha256: str, payload: dict[str, Any]) -> None:
        if payload.get("id") is None:
            return
        model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
        safe_payload = {
            "id": payload.get("id"),
            "modelId": payload.get("modelId"),
            "name": payload.get("name") or "",
            "model": {
                "name": model.get("name") or "",
                "type": model.get("type") or "",
            },
        }
        with self._lock:
            self._load()
            self._entries[sha256.lower()] = {
                "state": "resolved",
                "stored_at": self._clock(),
                "payload": safe_payload,
            }
            self._save()

    def store_not_found(self, sha256: str) -> None:
        with self._lock:
            self._load()
            self._entries[sha256.lower()] = {
                "state": "not_found",
                "stored_at": self._clock(),
                "payload": {},
            }
            self._save()


_DEFAULT_CACHE: ResolutionCache | None = None
_DEFAULT_LOCK = threading.Lock()


def default_resolution_cache() -> ResolutionCache:
    global _DEFAULT_CACHE
    with _DEFAULT_LOCK:
        if _DEFAULT_CACHE is not None:
            return _DEFAULT_CACHE
        try:
            import folder_paths

            root = Path(folder_paths.get_user_directory())
        except ImportError:
            root = Path.home() / ".cache" / "comfyui"
        _DEFAULT_CACHE = ResolutionCache(root / ".civitai-publisher" / "resources-v1.json")
        return _DEFAULT_CACHE
