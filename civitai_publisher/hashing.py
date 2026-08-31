from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import logs


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
    """Persistent SHA-256 cache keyed by the resolved file's stable identity."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._loaded = False
        self._entries: dict[str, dict[str, int | str]] = {}
        self._inflight: dict[tuple[str, int, int, int], threading.Event] = {}

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
            logs.warn("hash_cache_write_failed", error=type(error).__name__)
            return False
        return True

    def lookup(
        self,
        path: str | os.PathLike[str],
        cancel: Callable[[], None] | None = None,
    ) -> HashLookup:
        model_path = Path(path).resolve(strict=True)
        stat = model_path.stat()
        key = str(model_path)
        identity = {
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "ctime_ns": int(stat.st_ctime_ns),
            "inode": int(stat.st_ino),
            "device": int(stat.st_dev),
        }
        inflight_key = (key, identity["size"], identity["mtime_ns"], identity["ctime_ns"])

        while True:
            with self._lock:
                self._load()
                cached = self._entries.get(key)
                legacy_identity_matches = (
                    cached
                    and cached.get("size") == identity["size"]
                    and cached.get("mtime_ns") == identity["mtime_ns"]
                )
                extended_identity_matches = all(
                    cached.get(field) in (None, identity[field])
                    for field in ("ctime_ns", "inode", "device")
                ) if cached else False
                if (
                    legacy_identity_matches
                    and extended_identity_matches
                    and isinstance(cached.get("sha256"), str)
                ):
                    if any(field not in cached for field in ("ctime_ns", "inode", "device")):
                        self._entries[key] = {**cached, **identity}
                        self._save()
                    return HashLookup(
                        sha256=str(cached["sha256"]),
                        cached=True,
                        bytes_read=0,
                    )

                waiter = self._inflight.get(inflight_key)
                if waiter is None:
                    waiter = threading.Event()
                    self._inflight[inflight_key] = waiter
                    break

            while not waiter.wait(0.1):
                if cancel is not None:
                    cancel()

        try:
            sha256 = hash_file(model_path, cancel=cancel)
            with self._lock:
                self._entries[key] = {**identity, "sha256": sha256}
                self._save()
            return HashLookup(
                sha256=sha256,
                cached=False,
                bytes_read=identity["size"],
            )
        finally:
            with self._lock:
                finished = self._inflight.pop(inflight_key, None)
                if finished is not None:
                    finished.set()

    def sha256_for(self, path: str | os.PathLike[str], cancel: Callable[[], None] | None = None) -> str:
        return self.lookup(path, cancel=cancel).sha256


@dataclass(frozen=True)
class HashLookup:
    sha256: str
    cached: bool
    bytes_read: int
