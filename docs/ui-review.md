# UI Review — CivitAI publication modal

**Context:** prevent accidental CivitAI publication while keeping review fast · ComfyUI web canvas · production custom-node UI
**Reviewed:** live modal with generated IMAGE · Reject and Stop states · 1280px desktop and 390px mobile · ComfyUI dark theme

## 1. Overall diagnosis

The final modal feels like a deliberate safety gate rather than a generic settings card: the media leads, the reviewed fields are plainly editable, and there is one unambiguous outward action. The restrained purple accent fits the host canvas and does not drift into gradient or badge-heavy AI slop. The highest-leverage mobile issues found during review—nested scrolling and the wrapped primary action—were corrected before this report.

## 2. Top issues

1. **[Polish, resolved]** Two vertical scroll surfaces appeared at 390px — *mobile review modal* — the outer dialog competed with the review body and made the form feel embedded twice. The dialog now clips overflow and only the body scrolls.
2. **[Polish, resolved]** “Approve & publish” wrapped to three lines — *mobile footer* — the most important action was harder to scan and visually weaker than Reject. Mobile now uses the explicit accessible name with a compact visible “Approve” label.
3. **[Polish]** Light-theme appearance was not exercised — *modal* — the fixed dark review surface is intentional and works in the tested ComfyUI dark theme, but contrast in a light host theme remains unverified.

## 3. Detailed review

- **Layout:** The desktop 0.9/1.1 media-to-fields split keeps the decision asset and its metadata in one view. At 390px it becomes one column with a fixed footer and one scrolling body; measured horizontal overflow is false.
- **Visual hierarchy:** “Review CivitAI post” establishes context, media is the largest decision surface, and the single purple CTA is the strongest action. Reject remains visibly secondary.
- **Typography:** Four functional sizes are used: 22px heading, 13px body/input, 12px status/resource rows, and 11px uppercase labels. No decorative font or emoji chrome is present.
- **Spacing & alignment:** The form keeps a consistent 6px label gap and 13px field rhythm within 20–24px panel padding. Left edges align across title, prompt, tags, resources, and NSFW.
- **Color:** Neutral surfaces use one purple action/focus accent and amber only for unresolved resources. The modal avoids gradients, colored shadows, and per-resource rainbow badges.
- **Components:** Inputs share radius, border, focus ring, and type treatment. Both mobile buttons measure 44px high. Busy disables both terminal actions and changes the status copy.
- **States:** Empty resources teach what was not detected; decision submission exposes busy and recoverable inline error states; Reject completes the job, and Stop/timeout removes the modal through the server-close event. Success intentionally exits the gate because the ComfyUI node owns the post URL output.
- **Responsiveness:** Desktop content fits without scrolling for the tested one-image case. Mobile uses one internal scrollbar, a shortened primary label, a 36vh media cap, 44px actions, and no horizontal overflow.
- **Accessibility:** Native `dialog.showModal()` supplies focus trapping. The dialog has `aria-labelledby` and `aria-describedby`; inputs have persistent labels; the preview has alt text; Escape and backdrop click reject instead of silently approving.
- **Product clarity:** The first sentence says nothing has been uploaded, and the CTA names the irreversible outcome. A first-time user can distinguish review from publication immediately.

## 4. Recommended fixes

The two implementation-blocking findings were applied in `web/civitai_publisher.js`:

1. Keep `overflow: hidden` on the dialog and `overflow-y: auto` on the body so there is one scroll owner.
2. Preserve the 44px mobile actions and compact visible “Approve” label while retaining `aria-label="Approve and publish to CivitAI"`.
3. Before claiming light-theme support, render this same modal in a light ComfyUI theme and measure body, muted text, border, and CTA contrast.

## 5. Before-shipping checklist

- [x] Desktop modal rendered from a real queued ComfyUI node.
- [x] Reject completed with no upload; Stop dismissed the modal and failed closed.
- [x] No horizontal scroll at 390px.
- [x] Both mobile actions are at least 44px high.
- [x] Dialog label and description relationships are present.
- [x] One filled primary action and one secondary action remain.
- [ ] Light-theme contrast is unverified and is not claimed.

## 6. Optional polish

- Add a compact “Video” chip only when a VIDEO preview is present; it is unnecessary for images and should not become generic badge noise.
- If user testing shows title edits are rare, focus the prompt instead. Current focus on title is reasonable and was left unchanged.

## 7. Final implementation prompt

```text
You are revalidating the CivitAI Publisher review modal in ComfyUI. Its product goal is to prevent accidental external publication while keeping one-run approval fast. Do not redesign the established dark, single-accent modal.

Preserve these implemented fixes:
1. web/civitai_publisher.js — the dialog clips overflow; only the body scrolls.
2. web/civitai_publisher.js — mobile buttons remain 44px and the primary visible label is “Approve” with the full accessible name “Approve and publish to CivitAI”.
3. web/civitai_publisher.js — native dialog labeling, Escape rejection, busy state, and server-close cleanup remain intact.

Before calling future changes done, verify:
- Reject, close, timeout, and Stop perform zero uploads.
- Desktop and 390px mobile render with one scroll owner and no horizontal overflow.
- The primary CTA is the only filled action and remains at least 44px on mobile.
- All input labels and the dialog name/description are exposed to accessibility APIs.
- Light-theme support is claimed only after a separate rendered contrast check.
```
