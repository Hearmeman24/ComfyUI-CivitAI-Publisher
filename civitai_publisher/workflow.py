from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .hashing import HashCache

MODEL_EXTENSIONS = {
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".bin",
    ".gguf",
}
EXCLUDED_FOLDER_CATEGORIES = {
    "configs",
    "custom_nodes",
    "datasets",
    "download_model_base",
    "VHS_video_formats",
}
_DEFAULT_CACHE: HashCache | None = None
_DEFAULT_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class ModelReference:
    filename: str
    category: str
    path: Path
    resource_type: str
    strengths: tuple[float, ...] = ()
    node_ids: tuple[str, ...] = ()

    @property
    def civitai_weight(self) -> float | None:
        return self.strengths[0] if len(self.strengths) == 1 else None


@dataclass(frozen=True)
class HashedResource:
    filename: str
    category: str
    path: Path
    resource_type: str
    sha256: str
    strengths: tuple[float, ...] = ()
    node_ids: tuple[str, ...] = ()
    resolved: bool = False
    model_version_id: int | None = None
    model_id: int | None = None
    name: str = ""
    version_name: str = ""
    civitai_type: str = ""
    resolution_error: str = ""

    @property
    def autov2(self) -> str:
        return self.sha256[:10].upper()

    @property
    def civitai_weight(self) -> float | None:
        return self.strengths[0] if len(self.strengths) == 1 else None

    def public(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "category": self.category,
            "resource_type": self.resource_type,
            "sha256": self.sha256,
            "autov2": self.autov2,
            "strengths": list(self.strengths),
            "resolved": self.resolved,
            "modelVersionId": self.model_version_id,
            "modelId": self.model_id,
            "name": self.name,
            "versionName": self.version_name,
            "type": self.civitai_type,
            "resolution_error": self.resolution_error,
        }


@dataclass(frozen=True)
class GenerationMetadata:
    prompt: str = ""
    negative_prompt: str = ""
    seed: int | None = None
    steps: int | None = None
    cfg_scale: float | None = None
    sampler: str = ""
    scheduler: str = ""


@dataclass(frozen=True)
class _Candidate:
    filename: str
    node_id: str
    category_hint: str | None = None
    strength: float | None = None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _category_hint(input_name: str) -> str | None:
    name = input_name.lower()
    if "lora" in name:
        return "loras"
    if "checkpoint" in name or "ckpt" in name:
        return "checkpoints"
    if "unet" in name or "diffusion" in name:
        return "diffusion_models"
    if "control" in name and "model" in name:
        return "controlnet"
    if "vae" in name:
        return "vae"
    if "upscale" in name and "model" in name:
        return "upscale_models"
    if "clip" in name or "text_encoder" in name:
        return "text_encoders"
    return None


def _iter_candidates(
    value: Any,
    *,
    node_id: str,
    input_name: str = "",
    parent: dict[str, Any] | None = None,
) -> Iterable[_Candidate]:
    if isinstance(value, dict):
        if value.get("on") is False and isinstance(value.get("lora"), str):
            return
        for key, nested in value.items():
            yield from _iter_candidates(nested, node_id=node_id, input_name=key, parent=value)
        return
    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[0], (str, int)) and isinstance(value[1], int):
            return
        for nested in value:
            yield from _iter_candidates(nested, node_id=node_id, input_name=input_name, parent=parent)
        return
    if not isinstance(value, str) or Path(value).suffix.lower() not in MODEL_EXTENSIONS:
        return

    hint = _category_hint(input_name)
    strength: float | None = None
    if hint == "loras" and parent is not None:
        model_strength = _number(parent.get("strength_model"))
        clip_strength = _number(parent.get("strength_clip"))
        direct_strength = _number(parent.get("strength"))
        if model_strength is not None or clip_strength is not None:
            active_strengths = [item for item in (model_strength, clip_strength) if item is not None]
            if active_strengths and all(item == 0 for item in active_strengths):
                return
            strength = model_strength if model_strength not in (None, 0) else clip_strength
        else:
            if direct_strength == 0:
                return
            strength = direct_strength
        if strength is None:
            strength = 1.0
    yield _Candidate(value, node_id=node_id, category_hint=hint, strength=strength)


def _call_resolver(resolve_file: Callable[..., tuple[str, Path] | None], filename: str, hint: str | None):
    try:
        return resolve_file(filename, hint)
    except TypeError:
        return resolve_file(filename)


def discover_model_references(
    prompt: dict[str, Any],
    resolve_file: Callable[..., tuple[str, Path] | None],
) -> list[ModelReference]:
    merged: dict[tuple[str, str], ModelReference] = {}
    order: list[tuple[str, str]] = []
    for raw_node_id, node in prompt.items():
        if not isinstance(node, dict):
            continue
        node_id = str(raw_node_id)
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for candidate in _iter_candidates(inputs, node_id=node_id):
            resolved = _call_resolver(resolve_file, candidate.filename, candidate.category_hint)
            if resolved is None:
                continue
            category, path = resolved
            path = Path(path)
            resource_type = (
                "lora"
                if category == "loras" or candidate.category_hint == "loras"
                else "checkpoint"
            )
            key = (str(path), category)
            existing = merged.get(key)
            strength = candidate.strength if resource_type == "lora" else None
            if existing is None:
                strengths = (strength,) if strength is not None else ()
                merged[key] = ModelReference(
                    filename=candidate.filename,
                    category=category,
                    path=path,
                    resource_type=resource_type,
                    strengths=strengths,
                    node_ids=(node_id,),
                )
                order.append(key)
                continue
            strengths = existing.strengths
            if strength is not None and strength not in strengths:
                strengths = (*strengths, strength)
            node_ids = existing.node_ids if node_id in existing.node_ids else (*existing.node_ids, node_id)
            merged[key] = replace(existing, strengths=strengths, node_ids=node_ids)
    return [merged[key] for key in order]


def resolve_model_file(filename: str, category_hint: str | None = None) -> tuple[str, Path] | None:
    try:
        import folder_paths
    except ImportError:
        return None

    categories = list(folder_paths.folder_names_and_paths)
    if category_hint in categories:
        categories.remove(category_hint)
        categories.insert(0, category_hint)
    matches: list[tuple[str, Path]] = []
    for category in categories:
        if category in EXCLUDED_FOLDER_CATEGORIES:
            continue
        try:
            full_path = folder_paths.get_full_path(category, filename)
        except (KeyError, OSError, TypeError, ValueError):
            continue
        if full_path and Path(full_path).is_file():
            matches.append((category, Path(full_path).resolve()))
            if category == category_hint:
                return matches[-1]
    unique = {(category, str(path)): (category, path) for category, path in matches}
    return next(iter(unique.values())) if len(unique) == 1 else None


def default_hash_cache() -> HashCache:
    global _DEFAULT_CACHE
    with _DEFAULT_CACHE_LOCK:
        if _DEFAULT_CACHE is not None:
            return _DEFAULT_CACHE
        try:
            import folder_paths

            root = Path(folder_paths.get_user_directory())
        except ImportError:
            root = Path.home() / ".cache" / "comfyui"
        _DEFAULT_CACHE = HashCache(root / ".civitai-publisher" / "hashes-v1.json")
        return _DEFAULT_CACHE


def discover_and_hash_resources(
    prompt: dict[str, Any],
    *,
    cache: HashCache | None = None,
    cancel: Callable[[], None] | None = None,
) -> list[HashedResource]:
    hash_cache = cache or default_hash_cache()
    references = discover_model_references(prompt, resolve_model_file)
    return [
        HashedResource(
            filename=reference.filename,
            category=reference.category,
            path=reference.path,
            resource_type=reference.resource_type,
            sha256=hash_cache.sha256_for(reference.path, cancel=cancel),
            strengths=reference.strengths,
            node_ids=reference.node_ids,
        )
        for reference in references
    ]


def _downstream_usage(prompt: dict[str, Any], source_node_id: str) -> tuple[bool, bool]:
    visited: set[str] = set()
    queue = [source_node_id]
    positive = False
    negative = False
    while queue:
        node_id = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        for other_id, other in prompt.items():
            if not isinstance(other, dict):
                continue
            inputs = other.get("inputs") or {}
            for input_name, input_value in inputs.items():
                if not (
                    isinstance(input_value, list)
                    and len(input_value) == 2
                    and str(input_value[0]) == node_id
                ):
                    continue
                lowered = input_name.lower()
                if lowered == "positive":
                    positive = True
                elif lowered == "negative":
                    negative = True
                else:
                    queue.append(str(other_id))
    return positive, negative


def _linked_strings(prompt: dict[str, Any], value: Any, max_depth: int = 8) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not (isinstance(value, list) and len(value) == 2):
        return []
    queue: list[tuple[str, int]] = [(str(value[0]), 0)]
    visited: set[str] = set()
    results: list[str] = []
    while queue:
        node_id, depth = queue.pop(0)
        if node_id in visited or depth > max_depth:
            continue
        visited.add(node_id)
        node = prompt.get(node_id)
        if not isinstance(node, dict):
            continue
        for name, nested in (node.get("inputs") or {}).items():
            lowered = name.lower()
            if isinstance(nested, str) and (
                lowered in {"value", "text", "prompt", "string", "caption", "description"}
                or len(nested) > 50
            ):
                if nested.strip():
                    results.append(nested.strip())
            elif isinstance(nested, list) and len(nested) == 2:
                queue.append((str(nested[0]), depth + 1))
    return results


def _resolved_scalar(prompt: dict[str, Any], value: Any) -> Any:
    if not (isinstance(value, list) and len(value) == 2):
        return value
    upstream = prompt.get(str(value[0]))
    if not isinstance(upstream, dict):
        return None
    inputs = upstream.get("inputs") or {}
    for key in ("value", "seed", "noise_seed", "steps", "cfg", "sampler_name", "scheduler"):
        scalar = inputs.get(key)
        if isinstance(scalar, (str, int, float)) and not isinstance(scalar, bool):
            return scalar
    return None


def extract_generation_metadata(prompt: dict[str, Any], prompt_override: str = "") -> GenerationMetadata:
    positive_candidates: list[str] = []
    negative_candidates: list[str] = []
    sampler_inputs: dict[str, Any] = {}

    for raw_node_id, node in prompt.items():
        if not isinstance(node, dict) or node.get("class_type") == "CivitAIPublisher":
            continue
        node_id = str(raw_node_id)
        class_type = str(node.get("class_type") or "")
        inputs = node.get("inputs") or {}
        if class_type in {"KSampler", "KSamplerAdvanced", "SamplerCustom"} and not sampler_inputs:
            sampler_inputs = inputs

        positive_usage, negative_usage = _downstream_usage(prompt, node_id)
        for input_name, value in inputs.items():
            lowered = input_name.lower()
            is_prompt_field = (
                lowered in {"text", "prompt", "positive_prompt", "negative_prompt"}
                and ("textencode" in class_type.lower() or "prompt" in lowered)
            )
            if not is_prompt_field:
                continue
            strings = _linked_strings(prompt, value)
            if lowered == "negative_prompt" or (negative_usage and not positive_usage):
                negative_candidates.extend(strings)
            else:
                positive_candidates.extend(strings)

    override = prompt_override.strip()
    detected_prompt = max(positive_candidates, key=len, default="")
    detected_negative = max(negative_candidates, key=len, default="")

    seed = _resolved_scalar(prompt, sampler_inputs.get("seed", sampler_inputs.get("noise_seed")))
    steps = _resolved_scalar(prompt, sampler_inputs.get("steps"))
    cfg = _resolved_scalar(prompt, sampler_inputs.get("cfg"))
    sampler = _resolved_scalar(prompt, sampler_inputs.get("sampler_name"))
    scheduler = _resolved_scalar(prompt, sampler_inputs.get("scheduler"))
    return GenerationMetadata(
        prompt=override or detected_prompt,
        negative_prompt=detected_negative,
        seed=int(seed) if isinstance(seed, (int, float)) and not isinstance(seed, bool) else None,
        steps=int(steps) if isinstance(steps, (int, float)) and not isinstance(steps, bool) else None,
        cfg_scale=float(cfg) if isinstance(cfg, (int, float)) and not isinstance(cfg, bool) else None,
        sampler=str(sampler) if isinstance(sampler, str) else "",
        scheduler=str(scheduler) if isinstance(scheduler, str) else "",
    )
