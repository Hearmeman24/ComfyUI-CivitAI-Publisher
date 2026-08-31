from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import random
import re
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from .resolution_cache import ResolutionCache
from .workflow import GenerationMetadata, HashedResource

CIVITAI_ORIGIN = "https://civitai.com"
SOFTWARE_NAME = "ComfyUI (CivitAI Publisher by HearmemanAI)"


class CivitAIHTTPError(RuntimeError):
    def __init__(self, status: int, message: str, *, retry_after: float | None = None):
        self.status = status
        self.retry_after = retry_after
        super().__init__(message)


class PartialPostError(RuntimeError):
    def __init__(self, post_id: int, detail: str, *, origin: str = CIVITAI_ORIGIN):
        self.post_id = post_id
        self.post_url = f"{origin}/posts/{post_id}"
        super().__init__(
            f"CivitAI post {post_id} was created but publishing did not finish. "
            f"Inspect {self.post_url}. {detail}"
        )


@dataclass(frozen=True)
class MediaUpload:
    path: Path
    content_type: str
    width: int
    height: int
    media_type: str = "image"


@dataclass(frozen=True)
class PublishResult:
    post_id: int
    post_url: str


class Transport(Protocol):
    async def json(
        self,
        method: str,
        url: str,
        *,
        token: str,
        payload: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]: ...

    async def put_file(
        self,
        url: str,
        path: Path,
        *,
        content_type: str,
        timeout: int = 120,
    ) -> None: ...


def _safe_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return "<invalid-url>"


def _safe_error(error: BaseException, token: str) -> str:
    message = str(error)
    if token:
        message = message.replace(token, "[redacted]")
    message = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", r"\1[redacted]", message)
    message = re.sub(r"https?://[^\s?]+\?[^\s]+", lambda match: _safe_url(match.group(0)), message)
    return message[:1000]


class AioHttpTransport:
    USER_AGENT = "ComfyUI-CivitAI-Publisher/0.1"

    def __init__(self):
        self._session = None

    async def _shared_session(self):
        import aiohttp

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def json(
        self,
        method: str,
        url: str,
        *,
        token: str,
        payload: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        import aiohttp

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT,
        }
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        session = await self._shared_session()
        async with session.request(
            method,
            url,
            headers=headers,
            json=payload,
            timeout=client_timeout,
        ) as response:
            text = await response.text()
            if response.status < 200 or response.status >= 300:
                retry_after = response.headers.get("Retry-After")
                try:
                    retry_after_seconds = float(retry_after) if retry_after is not None else None
                except ValueError:
                    retry_after_seconds = None
                raise CivitAIHTTPError(
                    response.status,
                    f"CivitAI returned HTTP {response.status} for {_safe_url(url)}: {text[:500]}",
                    retry_after=retry_after_seconds,
                )
            try:
                result = json.loads(text) if text else {}
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"CivitAI returned invalid JSON for {_safe_url(url)}") from exc
            if not isinstance(result, dict):
                raise RuntimeError(f"CivitAI returned an unexpected response for {_safe_url(url)}")
            return result

    async def put_file(
        self,
        url: str,
        path: Path,
        *,
        content_type: str,
        timeout: int = 120,
    ) -> None:
        curl = shutil.which("curl")
        if curl is not None:
            def config_value(value: str) -> str:
                return value.replace("\\", "\\\\").replace('"', '\\"')

            config = "\n".join((
                'request = "PUT"',
                f'url = "{config_value(url)}"',
                f'header = "Content-Type: {config_value(content_type)}"',
                f'upload-file = "{config_value(str(path))}"',
                f'max-time = "{int(timeout)}"',
                "",
            ))
            process = await asyncio.create_subprocess_exec(
                curl,
                "--config",
                "-",
                "--silent",
                "--show-error",
                "--output",
                os.devnull,
                "--write-out",
                "%{http_code}",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(config.encode("utf-8")),
                    timeout=timeout + 5,
                )
            except TimeoutError as exc:
                process.kill()
                await process.wait()
                raise RuntimeError(f"CivitAI media upload timed out for {_safe_url(url)}") from exc
            status = stdout.decode("ascii", errors="replace").strip()
            if process.returncode != 0 or status not in {"200", "201", "204"}:
                detail = _safe_error(
                    RuntimeError(stderr.decode("utf-8", errors="replace").strip()),
                    "",
                )
                raise RuntimeError(
                    f"CivitAI media storage returned HTTP {status or 'unknown'} "
                    f"for {_safe_url(url)}: {detail}"
                )
            return

        import aiohttp

        client_timeout = aiohttp.ClientTimeout(total=timeout)
        session = await self._shared_session()
        with Path(path).open("rb") as handle:
            async with session.put(
                url,
                data=handle,
                headers={"Content-Type": content_type},
                timeout=client_timeout,
            ) as response:
                if response.status not in (200, 201, 204):
                    body = (await response.text())[:500]
                    raise RuntimeError(
                        f"CivitAI media storage returned HTTP {response.status} "
                        f"for {_safe_url(url)}: {body}"
                    )


def _version_payload(resource: HashedResource, payload: dict[str, Any]) -> HashedResource:
    model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
    version_id = payload.get("id")
    return replace(
        resource,
        resolved=bool(version_id),
        model_version_id=int(version_id) if version_id is not None else None,
        model_id=int(payload["modelId"]) if payload.get("modelId") is not None else None,
        name=str(model.get("name") or payload.get("name") or ""),
        version_name=str(payload.get("name") or ""),
        civitai_type=str(model.get("type") or ""),
        resolution_error="",
    )


def build_civitai_metadata(
    generation: GenerationMetadata,
    resources: list[HashedResource] | tuple[HashedResource, ...],
    *,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "prompt": generation.prompt or "AI generation",
        "software": SOFTWARE_NAME,
    }
    if generation.negative_prompt:
        metadata["negativePrompt"] = generation.negative_prompt
    if generation.seed is not None:
        metadata["seed"] = generation.seed
    if generation.steps is not None:
        metadata["steps"] = generation.steps
    if generation.cfg_scale is not None:
        metadata["cfgScale"] = generation.cfg_scale
    if generation.sampler:
        metadata["sampler"] = generation.sampler
    if generation.scheduler:
        metadata["scheduler"] = generation.scheduler
    if width and height:
        metadata["Size"] = f"{width}x{height}"

    hashes: dict[str, str] = {}
    legacy_resources: list[dict[str, Any]] = []
    civitai_resources: list[dict[str, Any]] = []
    for resource in resources:
        base_name = Path(resource.filename).stem
        hash_kind = "lora" if resource.resource_type == "lora" else "model"
        hashes[f"{hash_kind}:{base_name}"] = resource.autov2
        legacy: dict[str, Any] = {
            "type": resource.resource_type,
            "name": base_name,
            "hash": resource.autov2,
        }
        if resource.resource_type == "lora" and resource.civitai_weight is not None:
            legacy["weight"] = resource.civitai_weight
        legacy_resources.append(legacy)
        if resource.resolved and resource.model_version_id is not None:
            linked: dict[str, Any] = {"modelVersionId": resource.model_version_id}
            if resource.name:
                linked["modelName"] = resource.name
            if resource.version_name:
                linked["versionName"] = resource.version_name
            civitai_resources.append(linked)
    if hashes:
        metadata["hashes"] = hashes
        metadata["resources"] = legacy_resources
    if civitai_resources:
        metadata["civitaiResources"] = civitai_resources
    return metadata


class CivitAIClient:
    def __init__(
        self,
        token: str,
        *,
        transport: Transport | None = None,
        origin: str = CIVITAI_ORIGIN,
        resolution_cache: ResolutionCache | None = None,
        retry_delays: tuple[float, ...] = (0.25, 0.75),
    ):
        if not token:
            raise ValueError("CivitAI token is required")
        self._token = token
        self._transport = transport or AioHttpTransport()
        self._origin = origin.rstrip("/")
        self._api = f"{self._origin}/api"
        self._trpc = f"{self._api}/trpc"
        self._resolution_cache = resolution_cache
        self._retry_delays = retry_delays

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        await self.close()

    async def close(self) -> None:
        close = getattr(self._transport, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result

    async def _resolution_request(self, resource: HashedResource) -> dict[str, Any]:
        retryable_statuses = {408, 429, 500, 502, 503, 504}
        for attempt in range(len(self._retry_delays) + 1):
            try:
                return await self._transport.json(
                    "GET",
                    f"{self._api}/v1/model-versions/by-hash/{resource.sha256}",
                    token=self._token,
                    timeout=20,
                )
            except CivitAIHTTPError as exc:
                if exc.status not in retryable_statuses or attempt >= len(self._retry_delays):
                    raise
                delay = exc.retry_after
                if delay is None:
                    delay = self._retry_delays[attempt] * random.uniform(0.8, 1.2)
                await asyncio.sleep(max(0.0, min(float(delay), 5.0)))
            except (OSError, TimeoutError):
                if attempt >= len(self._retry_delays):
                    raise
                delay = self._retry_delays[attempt] * random.uniform(0.8, 1.2)
                await asyncio.sleep(max(0.0, min(float(delay), 5.0)))
        raise RuntimeError("unreachable resolution retry state")

    async def resolve_resources(
        self,
        resources: list[HashedResource],
        *,
        metrics: dict[str, int] | None = None,
    ) -> list[HashedResource]:
        semaphore = asyncio.Semaphore(4)

        async def resolve_one(resource: HashedResource) -> HashedResource:
            cached = self._resolution_cache.get(resource.sha256) if self._resolution_cache else None
            if cached is not None:
                if metrics is not None:
                    metrics["resolution_cache_hits"] = metrics.get("resolution_cache_hits", 0) + 1
                if cached.state == "resolved":
                    return _version_payload(resource, cached.payload)
                return replace(resource, resolved=False, resolution_error="not found on CivitAI")
            if metrics is not None:
                metrics["resolution_cache_misses"] = metrics.get("resolution_cache_misses", 0) + 1
            try:
                async with semaphore:
                    payload = await self._resolution_request(resource)
                if payload.get("id") is None:
                    raise RuntimeError("CivitAI model hash lookup returned no model version id")
                if self._resolution_cache is not None:
                    self._resolution_cache.store_resolved(resource.sha256, payload)
                return _version_payload(resource, payload)
            except CivitAIHTTPError as exc:
                if exc.status == 404:
                    if self._resolution_cache is not None:
                        self._resolution_cache.store_not_found(resource.sha256)
                    return replace(resource, resolved=False, resolution_error="not found on CivitAI")
                elif exc.status in (401, 403):
                    raise RuntimeError("CivitAI rejected the configured API token") from exc
                stale = (
                    self._resolution_cache.get(resource.sha256, allow_stale_success=True)
                    if self._resolution_cache
                    else None
                )
                if stale is not None and stale.state == "resolved":
                    if metrics is not None:
                        metrics["resolution_stale_hits"] = metrics.get("resolution_stale_hits", 0) + 1
                    return _version_payload(resource, stale.payload)
                return replace(resource, resolved=False, resolution_error=_safe_error(exc, self._token))
            except Exception as exc:
                stale = (
                    self._resolution_cache.get(resource.sha256, allow_stale_success=True)
                    if self._resolution_cache
                    else None
                )
                if stale is not None and stale.state == "resolved":
                    if metrics is not None:
                        metrics["resolution_stale_hits"] = metrics.get("resolution_stale_hits", 0) + 1
                    return _version_payload(resource, stale.payload)
                return replace(resource, resolved=False, resolution_error=_safe_error(exc, self._token))

        return list(await asyncio.gather(*(resolve_one(resource) for resource in resources)))

    async def publish_post(
        self,
        *,
        media: list[MediaUpload] | tuple[MediaUpload, ...],
        title: str,
        description: str,
        tags: tuple[str, ...],
        nsfw: bool,
        metadata: dict[str, Any],
    ) -> PublishResult:
        if not media:
            raise ValueError("at least one media file is required")
        uploads: list[tuple[str, MediaUpload]] = []
        try:
            for item in media:
                presign = await self._transport.json(
                    "POST",
                    f"{self._api}/v1/image-upload",
                    token=self._token,
                    payload={"filename": item.path.name},
                )
                upload_url = presign.get("uploadURL")
                upload_id = presign.get("id")
                if not isinstance(upload_url, str) or not upload_url or not upload_id:
                    raise RuntimeError("CivitAI did not return a media upload URL")
                await self._transport.put_file(
                    upload_url,
                    item.path,
                    content_type=(
                        item.content_type
                        or mimetypes.guess_type(item.path.name)[0]
                        or "application/octet-stream"
                    ),
                )
                uploads.append((str(upload_id), item))

            create = await self._transport.json(
                "POST",
                f"{self._trpc}/post.create",
                token=self._token,
                payload={"json": {"title": title or None}},
            )
            post_id_raw = create.get("result", {}).get("data", {}).get("json", {}).get("id")
            if post_id_raw is None:
                raise RuntimeError("CivitAI did not return a post id")
            post_id = int(post_id_raw)
        except Exception as exc:
            detail = _safe_error(exc, self._token)
            raise RuntimeError(f"CivitAI publication could not start: {detail}") from exc

        try:
            for index, (upload_id, item) in enumerate(uploads):
                await self._transport.json(
                    "POST",
                    f"{self._trpc}/post.addImage",
                    token=self._token,
                    payload={
                        "json": {
                            "postId": post_id,
                            "url": upload_id,
                            "type": item.media_type,
                            "width": item.width,
                            "height": item.height,
                            "name": item.path.name,
                            "index": index,
                            "meta": metadata,
                        }
                    },
                )

            for tag in tags:
                await self._transport.json(
                    "POST",
                    f"{self._trpc}/post.addTag",
                    token=self._token,
                    payload={"json": {"id": post_id, "name": tag}},
                )

            if nsfw:
                await self._transport.json(
                    "POST",
                    f"{self._trpc}/post.update",
                    token=self._token,
                    payload={"json": {"id": post_id, "nsfw": True, "nsfwLevel": 28}},
                )

            published_at = (
                datetime.now(timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
            await self._transport.json(
                "POST",
                f"{self._trpc}/post.update",
                token=self._token,
                payload={
                    "json": {
                        "id": post_id,
                        "title": title or None,
                        "detail": description or None,
                        "publishedAt": published_at,
                    },
                    "meta": {"values": {"publishedAt": ["Date"]}},
                },
            )
        except Exception as exc:
            raise PartialPostError(
                post_id,
                _safe_error(exc, self._token),
                origin=self._origin,
            ) from exc

        return PublishResult(post_id=post_id, post_url=f"{self._origin}/posts/{post_id}")
