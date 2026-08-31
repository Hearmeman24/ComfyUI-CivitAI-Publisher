from __future__ import annotations

import asyncio
import mimetypes
import os
import shutil
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .client import MediaUpload


@dataclass(frozen=True)
class MaterializedMedia:
    uploads: tuple[MediaUpload, ...]
    previews: tuple[dict[str, Any], ...]


def _save_image_batch(image_tensor: Any, directory: Path) -> list[MediaUpload]:
    if getattr(image_tensor, "ndim", None) != 4 or int(image_tensor.shape[0]) < 1:
        raise ValueError("IMAGE input must be a non-empty ComfyUI image batch")
    uploads: list[MediaUpload] = []
    for index, tensor in enumerate(image_tensor):
        array = tensor.detach().cpu().clamp(0, 1).mul(255).byte().numpy()
        if array.shape[-1] not in (3, 4):
            raise ValueError("IMAGE input must use RGB or RGBA channels")
        path = directory / f"image-{index + 1:03d}.png"
        Image.fromarray(array, mode="RGBA" if array.shape[-1] == 4 else "RGB").save(path, format="PNG")
        uploads.append(
            MediaUpload(
                path=path,
                content_type="image/png",
                width=int(array.shape[1]),
                height=int(array.shape[0]),
                media_type="image",
            )
        )
    return uploads


def _container_suffix(video: Any) -> str:
    try:
        formats = str(video.get_container_format()).lower().split(",")
    except Exception:
        formats = []
    if "webm" in formats:
        return ".webm"
    if any(item in formats for item in ("mp4", "m4v")):
        return ".mp4"
    if "mov" in formats:
        return ".mov"
    return ".source"


def _copy_stream(source: Any, destination: Path) -> None:
    if isinstance(source, (str, os.PathLike)):
        shutil.copy2(source, destination)
        return
    if not hasattr(source, "read"):
        raise ValueError("VIDEO input did not expose a path or readable stream")
    if hasattr(source, "seek"):
        source.seek(0)
    with destination.open("wb") as output:
        shutil.copyfileobj(source, output, length=8 * 1024 * 1024)


def _save_video(video: Any, directory: Path) -> MediaUpload:
    if not hasattr(video, "get_dimensions") or not hasattr(video, "get_stream_source"):
        raise ValueError("VIDEO input must implement ComfyUI's native VideoInput contract")
    width, height = video.get_dimensions()
    try:
        start_time, duration = video.get_active_trim_window()
    except Exception:
        start_time, duration = 0.0, 0.0

    suffix = _container_suffix(video)
    destination = directory / f"video{suffix}"
    source = video.get_stream_source()
    can_copy = not start_time and not duration and suffix in {".mp4", ".webm"}
    if can_copy:
        _copy_stream(source, destination)
    else:
        try:
            from comfy_api.latest import Types

            video.save_to(
                str(destination.with_suffix(".mp4")),
                format=Types.VideoContainer.MP4,
                codec=Types.VideoCodec.H264,
            )
            destination = destination.with_suffix(".mp4")
        except (ImportError, AttributeError):
            destination = destination.with_suffix(".mp4")
            video.save_to(str(destination))
    content_type = mimetypes.guess_type(destination.name)[0] or "video/mp4"
    return MediaUpload(
        path=destination,
        content_type=content_type,
        width=int(width),
        height=int(height),
        media_type="video",
    )


def _preview(upload: MediaUpload, temp_root: Path) -> dict[str, Any]:
    relative = upload.path.relative_to(temp_root)
    return {
        "type": upload.media_type,
        "filename": relative.name,
        "subfolder": relative.parent.as_posix() if relative.parent != Path(".") else "",
        "folder_type": "temp",
        "width": upload.width,
        "height": upload.height,
    }


@asynccontextmanager
async def materialize_media(*, image: Any | None, video: Any | None) -> AsyncIterator[MaterializedMedia]:
    if image is None and video is None:
        raise ValueError("Connect an IMAGE or VIDEO before queueing CivitAI Publisher")
    try:
        import folder_paths

        temp_root = Path(folder_paths.get_temp_directory()).resolve()
    except ImportError:
        temp_root = Path.cwd() / "temp"
    run_dir = temp_root / "civitai-publisher" / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        uploads: list[MediaUpload] = []
        if image is not None:
            uploads.extend(await asyncio.to_thread(_save_image_batch, image, run_dir))
        if video is not None:
            uploads.append(await asyncio.to_thread(_save_video, video, run_dir))
        yield MaterializedMedia(
            uploads=tuple(uploads),
            previews=tuple(_preview(upload, temp_root) for upload in uploads),
        )
    finally:
        await asyncio.to_thread(shutil.rmtree, run_dir, True)
