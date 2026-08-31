# Review-gated CivitAI publishing node for ComfyUI

- **Status:** accepted
- **Work type:** feature
- **Authority:** implementation requested

## Review surface

### Outcome

A ComfyUI output node accepts an IMAGE batch and/or a VIDEO, reads the CivitAI token only from the ComfyUI process environment, derives the generation prompt and local model resources from the queued API prompt, and opens a review modal in the ComfyUI canvas. The node uploads and publishes only after the user approves that exact run. Rejecting, closing, timing out, or interrupting the review uploads nothing.

### Assumptions and hypotheses

- **Assumption:** this should be a standalone public custom-node project named `ComfyUI-CivitAI-Publisher`. **Impact if wrong:** the implementation can be moved into a broader node pack later, but its Python package, web extension, tests, and public node identifier stay cohesive.
- **Assumption:** "prompt override" means the node's optional string input/widget wins over automatic workflow prompt discovery. **Impact if wrong:** a separate metadata input contract would be needed.
- **Assumption:** one execution creates one published CivitAI post containing every supplied image/video. **Impact if wrong:** batching and post-result outputs would change.

### Done when

- [x] A queued run with IMAGE and/or VIDEO reaches a modal showing the media, prompt, title/tags, NSFW choice, and every locally resolved model resource before upload — source: user outcome
- [x] Approve publishes once; Reject, modal close, timeout, disconnect-without-recovery, and Stop publish zero times — source: user outcome and fail-closed invariant
- [x] The CivitAI token is accepted from `CIVITAI_TOKEN`, `CIVITAI_API_KEY`, or legacy `civitai_token`, and never enters workflow JSON, browser events, URLs, logs, or returned diagnostics — source: repository credential convention
- [x] Focused fake-server tests prove payload mapping, resource resolution, and the approval boundary without a paid/live publish — source: verification
- [x] The modal is rendered in a local ComfyUI session and receives a UI review before completion — source: UI verification

## Execution contract

### Problem and evidence

BlockFlow already has the desired publishing behavior, but its state and UI live outside ComfyUI. The ComfyUI version must translate that behavior into an output-node execution plus a browser-extension modal without letting node execution itself bypass human approval.

- **Verified:** BlockFlow resolves credentials outside the graph and sends bearer auth from the backend — evidence: `/Users/avivkaplan/comfy/sgs-ui/custom_blocks/civitai_share/backend.block.py:_get_token`
- **Verified:** BlockFlow uploads media, creates a post, attaches per-media metadata, adds tags/NSFW, and publishes — evidence: `/Users/avivkaplan/comfy/sgs-ui/custom_blocks/civitai_share/backend.block.py:share`
- **Verified:** BlockFlow's metadata contract uses prompt plus AutoV2 hashes/resources and preserves LoRA strength — evidence: `/Users/avivkaplan/comfy/sgs-ui/custom_blocks/civitai_share/backend.block.py:_build_civitai_meta`
- **Verified:** ComfyUI exposes the queued API graph through hidden `PROMPT` and the node id through hidden `UNIQUE_ID`; output nodes are the execution boundary — evidence: `/Users/avivkaplan/src/comfy/ComfyUI/nodes.py:SaveImage`, `/Users/avivkaplan/src/comfy/ComfyUI/execution.py:execute`
- **Verified:** current ComfyUI VIDEO values expose a stream source, trim window, dimensions, and `save_to`, so the node can materialize the exact active video without a dependency on Video Helper Suite — evidence: `/Users/avivkaplan/src/comfy/ComfyUI/comfy_api/latest/_input/video_types.py:VideoInput`

### Scope and non-goals

- **In scope:** one review-gated output node; IMAGE batches and native VIDEO; local media previews; prompt and negative-prompt discovery with explicit prompt override precedence; sampler/seed/size metadata where discoverable; local model-file discovery, SHA-256 cache, CivitAI by-hash resolution, unresolved-resource visibility; CivitAI upload/post/publish; safe terminal states; reconnect recovery for an already-pending review.
- **Non-goals:** CivitAI model/version creation, checkpoint file upload, automatic AI tagging, manual resource URL entry, moderation automation, retries of ambiguous write calls, support for legacy VHS filename tuples as a second video contract, or deployment into RunPod templates.

### Engineering envelope

- **Touched dimensions:** security=environment secret boundary; resiliency=remote multi-call publication and human wait; audience=public custom-node users; runs_on=ComfyUI desktop/pod process; data=generated media and workflow/model metadata.
- **Effect on this contract:** the implementation is fail closed, keeps the token server-side, bounds the human wait and network calls, does not retry write operations, reports partial-post recovery information safely, and verifies the UI and fake HTTP boundary separately.

### Owners, invariants, and approach

- **Authoritative owner:** `ApprovalManager` owns pending review request identity and the one-way pending to approved/rejected transition; the node coroutine alone owns media preparation and publication for its run.
- **Must preserve:** no upload before approval; one decision per opaque request id; no reuse of an approval for another run; no credential serialization; exact media cleanup on every terminal path; disabled/zero-strength LoRAs are not claimed as used; changed files invalidate the SHA cache; an unchanged queued node still opens a fresh review.
- **Approach:** create a standalone package with four seams: workflow inspection and hashing, media materialization, approval coordination/routes, and a bounded CivitAI client. A small web extension listens for pending-review events, renders one native modal, and posts the user's final reviewed fields back to the decision route.

### Public node contract

- **Node:** `CivitAIPublisher`
- **Display name:** `CivitAI Publisher (Review Before Upload)`
- **Required widgets:** `title`, `tags`, `nsfw`, `prompt_override`, `approval_timeout_minutes`
- **Optional sockets:** `image: IMAGE`, `video: VIDEO`
- **Hidden inputs:** `prompt: PROMPT`, `unique_id: UNIQUE_ID`
- **Outputs:** `post_url: STRING`, `status: STRING`, `details: STRING`
- **Execution:** `OUTPUT_NODE = True`; `IS_CHANGED` is always NaN so every explicit queue is a new publication attempt.

### Verification

- **Regression seam:** pure workflow/resource tests plus an approval-manager test prove the pre-upload boundary; a local fake CivitAI server proves request ordering and payloads without external writes.
- **Focused check:** `./scripts/verify fast`
- **Wider check:** `./scripts/verify full`
- **User boundary:** run a local ComfyUI graph with a generated IMAGE, capture and visually review the modal at desktop and mobile widths, reject once, stop once, and approve once through the real HTTP transport against a local fake CivitAI server.

### Rollout and recovery

- **Rollout:** local branch and commit first; no GitHub repository, Registry publication, RunPod template edit, push, or live CivitAI post is part of this implementation pass.
- **Recovery:** reject/close/timeout/Stop removes prepared temporary media without uploading. A failure after `post.create` reports the draft post URL/id in a sanitized error so the user can inspect or remove the partial draft; the node never retries an ambiguous write automatically.
