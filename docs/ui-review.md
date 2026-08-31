# UI Review — embedded CivitAI publication review

**Reviewed:** live local ComfyUI node with native VIDEO · idle, pending, media-loading, and rejected states · 1600×1400 desktop viewport · ComfyUI dark theme

## 1. Overall diagnosis

The review now feels native to the graph instead of interrupting it: the playable media owns the hierarchy, the exact conditioning prompt and resource evidence are directly below it, and the outward action is unmistakable. The black media stage, compact neutral metadata, and one filled approval button achieve the requested signal-over-noise treatment without introducing a second application surface.

## 2. Top issues

1. **[Critical, resolved]** Approve and Reject initially had equal visual weight — *pending node footer* — which slowed the safety decision. Approve is now the one filled monochrome action; Reject remains secondary.
2. **[Critical, resolved]** A failed preview could still leave approval available — *image/video media stage* — which would allow blind publication. Preview errors now disable Approve and keep Reject available with a plain-language recovery message.
3. **[Polish, resolved]** The first CSS revision reused a stable extension URL — *review stylesheet* — and an already-open ComfyUI session retained the older action styling. The stylesheet now carries an explicit version query.

## 3. Detailed review

- **Layout:** One 560px node column keeps media, prompt, evidence, status, and actions aligned. The 255px media stage remains the dominant decision surface without turning the node into a detached panel.
- **Visual hierarchy:** Media first; generation prompt second; resource evidence third; terminal decision last. The white Approve action is the sole high-contrast CTA.
- **Typography:** Three practical sizes (10px labels, 11–12px body/data, 15px canvas state) and two main weights keep the dense node readable.
- **Spacing and alignment:** The component follows an 8px rhythm, with persistent labels and shared left edges. Compact 38px actions suit a desktop node while remaining easy to target.
- **Color:** Neutral dark surfaces, black media, white primary action, amber only for pending/unknown state, green/red only for terminal semantics. No gradients, glows, category rainbow, or decorative badges.
- **Components:** The video uses native playback controls. Prompt is the only editable review field in the embedded block; title/tags/NSFW remain the node's native widgets directly above it.
- **States:** Idle explains how to prepare media; pending exposes the full decision; preview failure disables publication; Reject states that nothing was uploaded; publishing/published/timeout/failure have dedicated inline copy.
- **Responsiveness:** This is a desktop graph tool, not a mobile page. It remains readable at normal 100% graph scale and degrades to host-controlled node abstraction at fit-to-screen zoom.
- **Accessibility:** Prompt has a persistent label; canvas and video have accessible names; the status is a polite live region; buttons have focus-visible outlines and real disabled states.
- **Product clarity:** A first-time user can see within seconds what will be published, which prompt/resources will be attached, and which button creates the external side effect.

## 4. Recommended fixes

All blocking findings were applied in `web/civitai_publisher.js` and `web/civitai_publisher.css`: embedded DOM widget, native video overlay, fail-closed preview errors, one filled approval action, 38px actions, focus treatment, accessible labels/live status, and versioned stylesheet loading.

## 5. Before-shipping checklist

- [x] Live native video renders and exposes playback controls inside the publisher node.
- [x] Exact review prompt and compact size metadata render below the media.
- [x] Approve is the only filled primary action; Reject remains available.
- [x] Reject terminates the local run with `nothing was uploaded`.
- [x] Empty, pending, preview-error, rejected, publishing, published, timeout, and failure code paths have explicit UI states.
- [x] Keyboard focus styling and accessible names/live status are present.
- [ ] Light-theme contrast is unverified; the current node intentionally targets the tested ComfyUI dark canvas.

## 6. Optional polish

If multi-item image/video posts become common, add a minimal previous/next media counter inside the existing black stage. Do not add a thumbnail rail or restore a modal unless a real batch-review need justifies the extra chrome.

## 7. Final implementation prompt

Revalidate the embedded CivitAI Publisher review after any frontend change. Use a real local native VIDEO, test idle/pending/preview-error/reject/publishing/published/timeout/failure states, and keep the media-first 560px node structure. Preserve one filled Approve action, secondary Reject, native playback controls, exact prompt/resource evidence, fail-closed preview errors, accessible labels/live status, and credential-free structured browser logs. Run `./scripts/verify full`, then render the node at normal desktop graph scale and confirm Reject reports that nothing was uploaded.
