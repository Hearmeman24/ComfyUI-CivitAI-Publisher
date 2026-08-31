from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from collections.abc import Callable
from pathlib import Path


def hash_file(path: Path, cancel: Callable[[], None] | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            if cancel is not None:
                cancel()
            digest.update(chunk)
    if cancel is not None:
        cancel()
    return digest.hexdigest()


class HashCache:
    """Persistent SHA-256 cache keyed by exact path, size, and nanosecond mtime."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._loaded = False
        self._entries: dict[str, dict[str, int | str]] = {}

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if isinstance(entries, dict):
            self._entries = {
                str(key): value
                for key, value in entries.items()
                if isinstance(value, dict)
            }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
        )
        temporary.write_text(
            json.dumps({"version": 1, "entries": self._entries}, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def sha256_for(self, path: str | os.PathLike[str], cancel: Callable[[], None] | None = None) -> str:
        model_path = Path(path).resolve(strict=True)
        stat = model_path.stat()
        key = str(model_path)
        identity = {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
        with self._lock:
            self._load()
            cached = self._entries.get(key)
            if (
                cached
                and cached.get("size") == identity["size"]
                and cached.get("mtime_ns") == identity["mtime_ns"]
                and isinstance(cached.get("sha256"), str)
            ):
                return str(cached["sha256"])

        sha256 = hash_file(model_path, cancel=cancel)
        with self._lock:
            self._entries[key] = {**identity, "sha256": sha256}
            self._save()
        return sha256
