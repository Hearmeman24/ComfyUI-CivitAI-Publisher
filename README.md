# ComfyUI CivitAI Publisher

Review and publish generated images or video to CivitAI without putting a CivitAI token in a workflow. The output node inspects the queued ComfyUI graph, identifies local model and LoRA weight files, hashes and resolves them against CivitAI, and then opens a blocking review modal. Media transfer begins only after **Approve & publish** is clicked.

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
3. Optionally set a title, comma-separated tags, NSFW, or a prompt override. A blank override uses the prompt detected from the queued workflow.
4. Queue the workflow. ComfyUI prepares a temporary preview, hashes prompt-referenced weight files, and resolves their names through CivitAI's model-version-by-hash API.
5. Inspect the media, final prompt, tags, rating, checkpoints, LoRAs, strengths, and unresolved local files in the modal.
6. Choose **Reject** or **Approve & publish**. Closing the modal is a rejection.

An image batch and an optional video are added to one CivitAI post. The node returns the post URL, terminal status, and a compact JSON summary.

[`examples/civitai-publisher-empty-image.json`](examples/civitai-publisher-empty-image.json) is a safe starter workflow for exercising the review and Reject path. It does not use model weights.

## Safety and failure behavior

- Reject, modal close, timeout, browser-less execution, or ComfyUI Stop performs zero media uploads.
- Model hash lookups are read-only and happen before the modal so the review can show resolved CivitAI names.
- Approval is single-use and tied to one opaque execution id; it cannot authorize a later queue.
- Remote writes are not automatically retried because a timed-out request may already have succeeded.
- Presigned media PUTs use `curl` when available (matching the proven BlockFlow path) without placing the signed URL in the process command line; `aiohttp` is the portable fallback.
- If a failure occurs after CivitAI creates the post, the error includes the sanitized draft post URL for recovery.
- Prepared media is removed from ComfyUI's temporary directory on every terminal path.

The model scanner covers local file-backed weights ending in `.safetensors`, `.ckpt`, `.pt`, `.pth`, `.bin`, or `.gguf`, including regular LoRA widgets and rgthree Power LoRA dictionaries. Disabled and zero-strength LoRAs are omitted. Folder-based Diffusers repositories and legacy VHS filename tuples are not treated as model or video inputs.

## Architecture

- [`node.py`](node.py) owns the ComfyUI node contract and the execution boundary.
- [`civitai_publisher/workflow.py`](civitai_publisher/workflow.py) extracts prompt metadata and model references.
- [`civitai_publisher/approval.py`](civitai_publisher/approval.py) owns the fail-closed, one-shot review state.
- [`civitai_publisher/client.py`](civitai_publisher/client.py) owns resource resolution and the non-retrying CivitAI publish sequence.
- [`web/civitai_publisher.js`](web/civitai_publisher.js) renders the native in-canvas modal.

The browser receives only preview locations and reviewed metadata. It never performs CivitAI API calls.

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

This project is a ComfyUI custom node. It does not modify a ComfyUI runtime or RunPod template, create CivitAI models or versions, upload checkpoint files, or moderate generated content. Publishing a reviewed post is the only outward write and always requires the modal approval for that execution.
