"""Structured, credential-safe lifecycle logging for the publisher node."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager

LOGGER_NAME = "CivitAIPublisher"
PREFIX = f"[{LOGGER_NAME}]"
logger = logging.getLogger(LOGGER_NAME)

_SECRET_SEGMENTS = frozenset(
    {"key", "token", "secret", "password", "authorization", "prompt", "url", "path"}
)


def _number(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_value(item) for item in value) + "]"
    text = str(value)
    if not text:
        return '""'
    if any(character in text for character in ' "'):
        return '"' + text.replace('"', "'") + '"'
    return text


def _secret_field(key: str) -> bool:
    lowered = key.lower()
    return any(segment in _SECRET_SEGMENTS for segment in lowered.split("_"))


def format_event(event: str, **fields) -> str:
    parts = [f"{PREFIX} event={event}"]
    for key, value in fields.items():
        if value is None:
            continue
        redacted = _secret_field(key) and not isinstance(value, bool)
        parts.append(f"{key}={'***' if redacted else _value(value)}")
    return " ".join(parts)


def log(event: str, **fields) -> None:
    logger.info(format_event(event, **fields))


def debug(event: str, **fields) -> None:
    logger.debug(format_event(event, **fields))


def warn(event: str, **fields) -> None:
    logger.warning(format_event(event, **fields))


@contextmanager
def timed(event: str, **fields):
    started = time.perf_counter()
    try:
        yield fields
    except BaseException as error:
        fields["ok"] = False
        fields["error"] = type(error).__name__
        fields["ms"] = (time.perf_counter() - started) * 1000.0
        logger.warning(format_event(event, **fields))
        raise
    fields["ms"] = (time.perf_counter() - started) * 1000.0
    logger.info(format_event(event, **fields))
