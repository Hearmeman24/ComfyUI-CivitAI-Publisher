from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from .workflow import GenerationMetadata, HashedResource

CIVITAI_ORIGIN = "https://civitai.com"
SOFTWARE_NAME = "ComfyUI (CivitAI Publisher by HearmemanAI)"


class CivitAIHTTPError(RuntimeError):
    def __init__(self, status: int, message: str):
        self.status = status
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
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.request(method, url, headers=headers, json=payload) as response:
                text = await response.text()
                if response.status < 200 or response.status >= 300:
                    raise CivitAIHTTPError(
                        response.status,
                        f"CivitAI returned HTTP {response.status} for {_safe_url(url)}: {text[:500]}",
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
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            with Path(path).open("rb") as handle:
                async with session.put(url, data=handle, headers={"Content-Type": content_type}) as response:
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
    ):
        if not token:
            raise ValueError("CivitAI token is required")
        self._token = token
        self._transport = transport or AioHttpTransport()
        self._origin = origin.rstrip("/")
        self._api = f"{self._origin}/api"
        self._trpc = f"{self._api}/trpc"

    async def resolve_resources(self, resources: list[HashedResource]) -> list[HashedResource]:
        semaphore = asyncio.Semaphore(4)

        async def resolve_one(resource: HashedResource) -> HashedResource:
            try:
                async with semaphore:
                    payload = await self._transport.json(
                        "GET",
                        f"{self._api}/v1/model-versions/by-hash/{resource.sha256}",
                        token=self._token,
                        timeout=20,
                    )
                return _version_payload(resource, payload)
            except CivitAIHTTPError as exc:
                if exc.status == 404:
                    return replace(resource, resolved=False, resolution_error="not found on CivitAI")
                elif exc.status in (401, 403):
                    raise RuntimeError("CivitAI rejected the configured API token") from exc
                else:
                    return replace(resource, resolved=False, resolution_error=_safe_error(exc, self._token))
            except Exception as exc:
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
