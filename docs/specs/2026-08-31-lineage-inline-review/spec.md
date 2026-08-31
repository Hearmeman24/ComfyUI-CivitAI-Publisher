# Lineage-correct CivitAI metadata and inline node review

- **Status:** accepted
- **Work type:** bug fix and UI refactor
- **Authority:** implementation requested

## Review surface

### Outcome

The CivitAI Publisher reviews the exact generation prompt and publishable model resources that produced its connected image or video. Review happens in a compact canvas embedded directly in the publisher node, with media playback, concise metadata, and explicit Reject / Approve & publish controls. No modal opens and no upload starts before approval.

### Done when

- [x] A dynamic prompt produced by OpenRouter can be connected as the publisher's generation prompt and is reviewed/published verbatim; the OpenRouter system prompt is never inferred as generation metadata — source: user outcome and attached workflow
- [x] Resource discovery follows only the publisher media lineage and reports the active diffusion/checkpoint, LoRA, ControlNet, embedding, or hypernetwork weights; auxiliary CLIP, VAE, preview, and unrelated-branch weights are excluded — source: user outcome
- [x] The review surface is embedded directly on the node, uses a quiet black media canvas with a playable video overlay, and contains prompt, compact metadata/resources, Reject, and Approve & publish without a dialog/backdrop — source: user outcome and MiniMaxRefPack analog
- [x] Structured backend/browser logging reports stage, timing, cache, review, and terminal events without credentials, prompts, signed URLs, or full filesystem paths — source: prior user request and secret boundary
- [x] Unchanged model files reuse persistent hashes; repeated CivitAI hash resolution uses a bounded persistent TTL cache; safe read calls may retry but ambiguous write calls remain non-retrying — source: prior user request and resiliency invariant
- [x] Focused regressions, the full repository verification interface, and a rendered local ComfyUI screenshot prove the data and UI boundaries — source: engineering doctrine

## Execution contract

### Problem and evidence

The attached `T2V-V5 (1).json` workflow connects `OpenRouterSimple.text` (node 259) to `MiniMaxH3ImageToVideo.prompt` (node 130), and the resulting conditioning/media branch reaches `CivitAIPublisher.video` (node 272) through `CreateVideo` (node 275). The current prompt walker follows the OpenRouter output link, collects every long string in the OpenRouter inputs, and selects the longest one, which is the system prompt rather than the runtime text output.

The current resource walker scans every node in the queued prompt and maps every non-LoRA weight to `checkpoint`. In the attached workflow that makes the MiniMax CLIP, video/audio VAEs, and preview weight eligible to appear as checkpoints even though the active media branch's publishable weights are one UNET plus the three LoRAs chained into it.

- **Verified:** linked prompt traversal accepts any upstream string longer than 50 characters, irrespective of its input role — evidence: `civitai_publisher/workflow.py:_linked_strings`
- **Verified:** prompt selection takes the longest collected positive candidate — evidence: `civitai_publisher/workflow.py:extract_generation_metadata`
- **Verified:** resource discovery iterates every prompt node and classifies all resolved non-LoRA paths as checkpoints — evidence: `civitai_publisher/workflow.py:discover_model_references`
- **Verified:** the existing review is a document-level `<dialog>` appended to `document.body` — evidence: `web/civitai_publisher.js:showReview`
- **Verified:** MiniMaxRefPack embeds one DOM widget below native widgets, paints a black canvas, and uses a shared video overlay — evidence: `/Users/avivkaplan/src/comfy/ComfyUI-MiniMaxRefPack/web/refpack.js:buildCustomBlock`
- **Verified:** full SHA-256 values are already cached persistently by resolved path, size, and nanosecond mtime — evidence: `civitai_publisher/hashing.py:HashCache`

### Scope and non-goals

- **In scope:** optional `generation_prompt: STRING` socket; prompt precedence and strict fallback; media-lineage graph traversal; publishable-resource filtering and correct grouping; embedded node review UI; review/publish progress states; complete compact generation metadata; structured logging; hash hit/miss instrumentation and same-file in-flight deduplication; persistent CivitAI resolution caching; shared HTTP session and bounded retry for read-only resolution calls; documentation and workflow-derived regressions.
- **Non-goals:** automatic mutation/rewiring of saved workflows, recovering dynamic upstream output values from ComfyUI internals without a socket, checkpoint/model file upload, retrying ambiguous create/attach/publish writes, redesigning CivitAI post semantics, durable crash-resume publication journals, or changing RunPod templates.

### Engineering envelope

- **Touched dimensions:** data=prompt/resource provenance; security=token and sensitive prompt/log boundary; resiliency=human gate plus multi-call remote publication; runs_on=ComfyUI desktop and RunPod; audience=node users reviewing outward publication.
- **Effect on this contract:** metadata must be lineage-derived, dynamic values must arrive through a typed runtime socket, review remains fail closed, logs are aggregate/sanitized, read retries are bounded and writes remain non-retrying, and UI proof is required before rollout.

### Owners, invariants, and approach

- **Authoritative owner:** the publisher's connected `generation_prompt` runtime value owns dynamic prompt truth; the hidden API `PROMPT` owns graph lineage and static fallback; `ApprovalManager` owns the one-shot approval decision; the node coroutine owns outward writes.
- **Must preserve:** prompt override wins when nonblank; existing workflows without the new socket remain loadable; a literal conditioning prompt can still be discovered; a dynamic prompt without the socket fails with an actionable error instead of publishing the wrong text; disabled/zero-strength LoRAs remain excluded; no upload occurs before approval; Stop/reject/timeout remain fail closed; token and signed URLs never enter browser state or logs.
- **Approach:** add the optional socket without reordering existing required widgets, traverse ancestors from only the publisher's image/video links, resolve only publishable weight categories, and reuse the MiniMax hybrid pattern: native widgets above, one non-serialized DOM widget, one black canvas, and one shared video element. Keep the backend approval protocol but target reviews/status to the node id rather than a global modal queue.

### Public node contract

- **Existing node/output identifiers:** unchanged.
- **New optional socket:** `generation_prompt: STRING`; connect the exact string that feeds the conditioning node when it is dynamically produced.
- **Prompt precedence:** nonblank `prompt_override` widget, then nonblank connected `generation_prompt`, then strict literal conditioning discovery from the media lineage. If none is available, stop before review with an actionable error.
- **Resource provenance:** ancestors of the connected publisher `image` and `video` inputs only.
- **Review placement:** embedded directly in the `CivitAIPublisher` node; no `<dialog>`, backdrop, or document-level approval surface.

### Cache and network contract

- **File hashes:** exact SHA-256 remains authoritative. A cache hit requires unchanged resolved path identity; concurrent misses for the same identity share one calculation.
- **CivitAI resolution:** cache successful SHA-to-version results for 24 hours and 404 results for 15 minutes; never cache authentication failures. A stale successful result may be used when a transient read-only lookup fails.
- **HTTP:** reuse one client session per resolution/publication operation. Retry only read-only hash resolution on timeout, 408, 429, or 5xx with bounded jitter and `Retry-After`; do not automatically retry presign, upload, post creation, attachment, tagging, rating, or publish writes.

### Verification

- **Regression seam:** workflow-derived API prompt fixtures prove dynamic prompt refusal/connected prompt precedence and exact media-lineage resources; cache/client tests prove hash reuse, resolution TTL behavior, and read-only retry boundaries; frontend contract/state tests prove node targeting and absence of a dialog.
- **Focused check:** `./scripts/verify fast`
- **Wider check:** `./scripts/verify full`
- **User boundary:** load the publisher into local ComfyUI, exercise an embedded video review with the fake CivitAI boundary, capture the node at desktop scale, run the UI review skill, Reject once, and confirm no external publish occurs.

### Rollout and recovery

- **Rollout:** commit the coherent local change, stage the exact commit on the named RTX PRO 6000 box through RunPod MCP, compile and verify remotely, then leave activation pending unless the user explicitly authorizes a restart.
- **Recovery:** the previous committed node remains the rollback source. A failed inline frontend load cannot authorize an upload; the backend review times out. A failure after post creation continues to return the sanitized partial-post URL and is never retried automatically.
