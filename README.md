# ComfyUI CivitAI Publisher

Review and publish generated images or native ComfyUI video to CivitAI without putting a CivitAI token in a workflow. The output node follows the media-producing branch, resolves its publishable model weights, and renders the approval canvas directly inside the node. Media transfer begins only after **Approve & publish** is clicked.

## Install

Place this repository at:

```text
ComfyUI/custom_nodes/ComfyUI-CivitAI-Publisher
```

Install its small runtime dependency set with the same Python environment that starts ComfyUI:

```bash
python -m pip install -r requirements.txt
```

Set the token in the environment that launches ComfyUI, then restart ComfyUI:

```bash
export CIVITAI_TOKEN="your-token"
```

`CIVITAI_API_KEY` and the legacy lowercase `civitai_token` are also accepted. `CIVITAI_TOKEN` has precedence. The token is server-side only: it is not a node widget, workflow value, browser event field, URL, or result value.

## Use

1. Add **CivitAI Publisher (Review Before Upload)** from `HearmemanAI/CivitAI`.
2. Connect an `IMAGE`, a native ComfyUI `VIDEO`, or both.
3. If conditioning receives a dynamic prompt from OpenRouter, Ollama, or another runtime node, connect that same `STRING` to `generation_prompt`. The publisher cannot reconstruct a runtime output from the queued graph alone.
4. Optionally set a title, comma-separated tags, NSFW, or `prompt_override`. Prompt precedence is: nonblank override, connected runtime prompt, then a literal prompt found on the media branch. A dynamic prompt without either explicit input fails before review instead of guessing from an LLM system prompt.
5. Queue the workflow. The publisher prepares a temporary preview, discovers and hashes the publishable weights on the connected media lineage, and resolves their CivitAI versions.
6. Inspect the playable media, final prompt, generation metadata, resolved resources, LoRA strengths, and unknown local files directly in the node.
7. Choose **Reject** or **Approve & publish**.

An image batch and an optional video are added to one CivitAI post. The node returns the post URL, terminal status, and a compact JSON summary.

[`examples/civitai-publisher-empty-image.json`](examples/civitai-publisher-empty-image.json) is a safe starter workflow for exercising the embedded review and Reject path. It does not use model weights.

## Prompt and resource provenance

The hidden ComfyUI API prompt is a graph description, not a record of dynamic output values. The publisher therefore uses the connected `generation_prompt` value as the source of truth for OpenRouter-style workflows. It never substitutes `system_prompt`, `user_prompt`, model instructions, or another long upstream configuration string for the conditioning output.

The model list comes only from ancestors of the publisher's connected `image` and `video` inputs. It includes local file-backed:

- checkpoints, diffusion models, and UNETs;
- LoRAs, including enabled rgthree Power LoRAs and their active strengths;
- ControlNets, embeddings/textual inversions, and hypernetworks.

It excludes unrelated workflow branches and auxiliary CLIP/text encoder, VAE, preview, and upscale weights. Disabled and zero-strength LoRAs are omitted. The scanner covers `.safetensors`, `.ckpt`, `.pt`, `.pth`, `.bin`, and `.gguf`; folder-based Diffusers repositories and legacy VHS filename tuples are not treated as publishable model resources.

## Caching and performance

The CivitAI-compatible identifier is the complete file SHA-256. The first calculation reads the file in 8 MiB chunks; that exact first hash cannot be safely shortened. Results are persisted at `ComfyUI/user/.civitai-publisher/hashes-v1.json` and reused while the resolved path, size, nanosecond modification/change time, inode, and device identity remain unchanged. Changing only the prompt or other workflow text does not read or hash the model files again. Concurrent requests for the same unchanged file share one in-flight calculation.

CivitAI hash-to-version responses are cached separately at `ComfyUI/user/.civitai-publisher/resources-v1.json`: successful resolutions for 24 hours and not-found responses for 15 minutes. A stale successful resolution can carry a review through a transient CivitAI lookup outage. Cache write failures are warnings, not execution failures; the completed in-memory result remains usable.

One HTTP session is reused for an execution. Read-only hash resolution uses four-way bounded concurrency and short bounded retries for timeouts, HTTP 408/429, and transient 5xx responses. Presign, upload, post creation, attachment, tagging, rating, and publication writes are deliberately not retried because a timed-out write may already have succeeded.

## Logging

Backend and browser logs use one searchable prefix and event fields:

```text
[CivitAIPublisher] event=resource_hashing node_id=272 hash_hits=4 hash_misses=0 hash_bytes_read=0 resources=4 ms=1.7
```

Events cover execution start, hash and resolution timings/cache counts, review open/decision, publish timing, cache write failures, and browser rendering/decisions. Tokens, prompts, signed URLs, and full filesystem paths are redacted; useful boolean presence fields and aggregate counts remain visible.

The publisher logger explicitly runs at `INFO`, independent of ComfyUI's inherited root logger level. Routine lifecycle and performance events are therefore always enabled; genuine degraded behavior remains `WARNING` so it is still distinguishable.

## Safety and failure behavior

- Reject, timeout, browser-less execution, ComfyUI Stop, or an unreadable media preview performs zero media uploads.
- Approval is single-use and tied to one opaque execution id; it cannot authorize a later queue.
- Hash/version lookups are read-only and happen before approval so the node can show the actual linked resources.
- Remote writes begin only after approval and are never automatically replayed.
- Presigned media PUTs use `curl` when available without placing the signed URL in the process command line; `aiohttp` is the portable fallback.
- If a failure occurs after CivitAI creates the post, the error includes the sanitized draft post URL for recovery.
- Prepared media is removed from ComfyUI's temporary directory on every terminal path.

## Architecture

- [`node.py`](node.py) owns the ComfyUI node contract and execution boundary.
- [`civitai_publisher/workflow.py`](civitai_publisher/workflow.py) owns media-lineage prompt metadata and model discovery.
- [`civitai_publisher/hashing.py`](civitai_publisher/hashing.py) owns exact hashes and the persistent file-identity cache.
- [`civitai_publisher/resolution_cache.py`](civitai_publisher/resolution_cache.py) owns bounded CivitAI version caching.
- [`civitai_publisher/approval.py`](civitai_publisher/approval.py) owns the fail-closed, one-shot review state.
- [`civitai_publisher/client.py`](civitai_publisher/client.py) owns resource resolution and the non-retrying CivitAI write sequence.
- [`web/civitai_publisher.js`](web/civitai_publisher.js) renders the embedded review and terminal states.

The browser receives only preview locations and reviewed metadata. It never receives the token or performs CivitAI API calls.

## Verify

Fast behavioral checks:

```bash
./scripts/verify fast
```

Full checks, including the real local HTTP transport against a fake CivitAI server:

```bash
./scripts/verify full
```

No verification command publishes externally.

## Operational boundary

This project is a ComfyUI custom node. It does not modify a ComfyUI runtime or RunPod template, create CivitAI models or versions, upload checkpoint files, or moderate generated content. Publishing a reviewed post is the only outward write and always requires the embedded approval for that execution.
