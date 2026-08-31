import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { normalizeReviewEdits, resourceGroups } from "./review_state.mjs";

const DECISION_PATH = "/civitai_publisher/decision";
const PENDING_PATH = "/civitai_publisher/pending";
const queued = [];
const known = new Set();
let activeDialog = null;

function installStyles() {
    if (document.getElementById("civitai-publisher-styles")) return;
    const style = document.createElement("style");
    style.id = "civitai-publisher-styles";
    style.textContent = `
        .civitai-publisher-dialog {
            width: min(880px, calc(100vw - 40px));
            max-height: min(820px, calc(100vh - 40px));
            padding: 0;
            border: 1px solid color-mix(in srgb, var(--border-color, #555) 65%, #8b5cf6 35%);
            border-radius: 16px;
            color: var(--fg-color, #f5f5f5);
            background: #151419;
            box-shadow: 0 28px 90px rgba(0, 0, 0, .65);
            overflow: hidden;
        }
        .civitai-publisher-dialog::backdrop { background: rgba(3, 2, 7, .76); backdrop-filter: blur(5px); }
        .civitai-publisher-shell { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; max-height: inherit; }
        .civitai-publisher-header { padding: 20px 24px 16px; border-bottom: 1px solid rgba(255,255,255,.08); }
        .civitai-publisher-kicker { margin: 0 0 5px; color: #a78bfa; font: 600 11px/1.2 ui-sans-serif, system-ui; letter-spacing: .14em; text-transform: uppercase; }
        .civitai-publisher-title { margin: 0; color: #fff; font: 650 22px/1.25 ui-sans-serif, system-ui; }
        .civitai-publisher-subtitle { margin: 7px 0 0; color: #a9a6b2; font: 400 13px/1.45 ui-sans-serif, system-ui; }
        .civitai-publisher-body { min-height: 0; overflow-y: auto; overflow-x: hidden; padding: 20px 24px; display: grid; grid-template-columns: minmax(260px, .9fr) minmax(320px, 1.1fr); gap: 22px; }
        .civitai-publisher-media { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; align-content: start; }
        .civitai-publisher-media img, .civitai-publisher-media video { width: 100%; max-height: 310px; border-radius: 10px; object-fit: contain; background: #08080a; border: 1px solid rgba(255,255,255,.08); }
        .civitai-publisher-media .wide { grid-column: 1 / -1; }
        .civitai-publisher-fields { display: flex; flex-direction: column; gap: 13px; }
        .civitai-publisher-field { display: flex; flex-direction: column; gap: 6px; }
        .civitai-publisher-label { color: #c8c5cf; font: 600 11px/1.2 ui-sans-serif, system-ui; text-transform: uppercase; letter-spacing: .08em; }
        .civitai-publisher-input, .civitai-publisher-textarea { box-sizing: border-box; width: 100%; color: #f7f5fa; background: #0e0d11; border: 1px solid rgba(255,255,255,.12); border-radius: 8px; padding: 9px 10px; font: 400 13px/1.45 ui-sans-serif, system-ui; outline: none; }
        .civitai-publisher-input:focus, .civitai-publisher-textarea:focus { border-color: #8b5cf6; box-shadow: 0 0 0 3px rgba(139,92,246,.16); }
        .civitai-publisher-textarea { min-height: 112px; resize: vertical; }
        .civitai-publisher-resource-block { padding: 11px; border: 1px solid rgba(255,255,255,.09); border-radius: 10px; background: rgba(255,255,255,.025); }
        .civitai-publisher-resource-heading { margin: 0 0 7px; color: #aaa6b2; font: 600 11px/1.2 ui-sans-serif, system-ui; }
        .civitai-publisher-resource-row { display: flex; justify-content: space-between; gap: 10px; padding: 6px 0; border-top: 1px solid rgba(255,255,255,.055); color: #ece9f1; font: 400 12px/1.35 ui-sans-serif, system-ui; }
        .civitai-publisher-resource-row:first-of-type { border-top: 0; }
        .civitai-publisher-resource-row small { color: #8e8998; white-space: nowrap; }
        .civitai-publisher-resource-row.unknown { color: #fbbf24; }
        .civitai-publisher-toggle { display: flex; align-items: center; gap: 9px; color: #e7e4eb; font: 500 13px/1.2 ui-sans-serif, system-ui; }
        .civitai-publisher-toggle input { width: 16px; height: 16px; accent-color: #8b5cf6; }
        .civitai-publisher-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 15px 24px; border-top: 1px solid rgba(255,255,255,.08); background: rgba(255,255,255,.018); }
        .civitai-publisher-status { color: #a9a6b2; font: 400 12px/1.35 ui-sans-serif, system-ui; }
        .civitai-publisher-actions { display: flex; gap: 9px; }
        .civitai-publisher-button { min-height: 40px; border-radius: 8px; padding: 9px 15px; font: 600 13px/1 ui-sans-serif, system-ui; cursor: pointer; }
        .civitai-publisher-button:disabled { opacity: .5; cursor: wait; }
        .civitai-publisher-reject { color: #e7e4eb; border: 1px solid rgba(255,255,255,.16); background: transparent; }
        .civitai-publisher-approve { color: white; border: 1px solid #8b5cf6; background: #7c3aed; }
        .civitai-publisher-approve-short { display: none; }
        @media (max-width: 720px) {
            .civitai-publisher-body { grid-template-columns: 1fr; }
            .civitai-publisher-media img, .civitai-publisher-media video { max-height: 36vh; }
            .civitai-publisher-button { min-height: 44px; }
            .civitai-publisher-approve-full { display: none; }
            .civitai-publisher-approve-short { display: inline; }
        }
    `;
    document.head.appendChild(style);
}

function el(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
}

function previewUrl(item) {
    const params = new URLSearchParams({
        filename: item.filename,
        type: item.folder_type || "temp",
        subfolder: item.subfolder || "",
    });
    return api.apiURL(`/view?${params.toString()}`);
}

async function sendDecision(requestId, decision, edits = {}) {
    const response = await api.fetchApi(DECISION_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId, decision, edits }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
        const error = new Error(payload.error || `Decision returned HTTP ${response.status}`);
        error.status = response.status;
        throw error;
    }
}

function renderResources(container, resources) {
    const groups = resourceGroups(resources);
    if (!groups.length) {
        container.appendChild(el("div", "civitai-publisher-resource-row unknown", "No local model files were detected in this queued workflow."));
        return;
    }
    for (const group of groups) {
        const block = el("section", "civitai-publisher-resource-block");
        block.appendChild(el("h3", "civitai-publisher-resource-heading", group.label));
        for (const row of group.rows) {
            const line = el("div", `civitai-publisher-resource-row${row.resolved ? "" : " unknown"}`);
            const label = row.resolved
                ? `${row.name || row.filename}${row.versionName && row.versionName !== row.name ? ` (${row.versionName})` : ""}`
                : `${row.filename} — ${row.resolution_error || "not on CivitAI"}`;
            line.appendChild(el("span", "", label));
            const strengths = Array.isArray(row.strengths) && row.strengths.length
                ? ` @ ${row.strengths.join(" / ")}`
                : "";
            line.appendChild(el("small", "", `${row.autov2 || ""}${strengths}`));
            block.appendChild(line);
        }
        container.appendChild(block);
    }
}

function showReview(review) {
    installStyles();
    const dialog = el("dialog", "civitai-publisher-dialog");
    dialog.dataset.requestId = review.request_id;
    dialog.setAttribute("aria-labelledby", "civitai-publisher-dialog-title");
    dialog.setAttribute("aria-describedby", "civitai-publisher-dialog-description");
    const shell = el("div", "civitai-publisher-shell");
    const header = el("header", "civitai-publisher-header");
    header.appendChild(el("p", "civitai-publisher-kicker", "Human approval required"));
    const heading = el("h2", "civitai-publisher-title", "Review CivitAI post");
    heading.id = "civitai-publisher-dialog-title";
    header.appendChild(heading);
    const subtitle = el("p", "civitai-publisher-subtitle", "Nothing has been uploaded. Approve only after the media, prompt, and linked resources look right.");
    subtitle.id = "civitai-publisher-dialog-description";
    header.appendChild(subtitle);
    shell.appendChild(header);

    const body = el("div", "civitai-publisher-body");
    const gallery = el("div", "civitai-publisher-media");
    for (const [index, item] of (review.media || []).entries()) {
        const media = item.type === "video" ? document.createElement("video") : document.createElement("img");
        media.src = previewUrl(item);
        media.className = (review.media || []).length === 1 || item.type === "video" ? "wide" : "";
        if (item.type === "video") {
            media.controls = true;
            media.preload = "metadata";
        } else {
            media.alt = `Media ${index + 1} pending CivitAI review`;
        }
        gallery.appendChild(media);
    }
    body.appendChild(gallery);

    const fields = el("div", "civitai-publisher-fields");
    const titleField = el("label", "civitai-publisher-field");
    titleField.appendChild(el("span", "civitai-publisher-label", "Post title"));
    const titleInput = el("input", "civitai-publisher-input");
    titleInput.value = review.title || "";
    titleField.appendChild(titleInput);
    fields.appendChild(titleField);

    const promptField = el("label", "civitai-publisher-field");
    promptField.appendChild(el("span", "civitai-publisher-label", "Prompt"));
    const promptInput = el("textarea", "civitai-publisher-textarea");
    promptInput.value = review.prompt || "";
    promptField.appendChild(promptInput);
    fields.appendChild(promptField);

    const tagsField = el("label", "civitai-publisher-field");
    tagsField.appendChild(el("span", "civitai-publisher-label", "Tags"));
    const tagsInput = el("input", "civitai-publisher-input");
    tagsInput.value = Array.isArray(review.tags) ? review.tags.join(", ") : "";
    tagsField.appendChild(tagsInput);
    fields.appendChild(tagsField);

    const resources = el("div", "civitai-publisher-fields");
    resources.appendChild(el("span", "civitai-publisher-label", "Models and LoRAs"));
    renderResources(resources, review.resources || []);
    fields.appendChild(resources);

    const toggle = el("label", "civitai-publisher-toggle");
    const nsfwInput = document.createElement("input");
    nsfwInput.type = "checkbox";
    nsfwInput.checked = Boolean(review.nsfw);
    toggle.appendChild(nsfwInput);
    toggle.appendChild(document.createTextNode("Mark as NSFW"));
    fields.appendChild(toggle);
    body.appendChild(fields);
    shell.appendChild(body);

    const footer = el("footer", "civitai-publisher-footer");
    const status = el("div", "civitai-publisher-status", `${(review.media || []).length} media file${(review.media || []).length === 1 ? "" : "s"} ready for review`);
    footer.appendChild(status);
    const actions = el("div", "civitai-publisher-actions");
    const reject = el("button", "civitai-publisher-button civitai-publisher-reject", "Reject");
    reject.type = "button";
    const approve = el("button", "civitai-publisher-button civitai-publisher-approve");
    approve.type = "button";
    approve.setAttribute("aria-label", "Approve and publish to CivitAI");
    approve.appendChild(el("span", "civitai-publisher-approve-full", "Approve & publish"));
    approve.appendChild(el("span", "civitai-publisher-approve-short", "Approve"));
    actions.append(reject, approve);
    footer.appendChild(actions);
    shell.appendChild(footer);
    dialog.appendChild(shell);
    document.body.appendChild(dialog);

    let settled = false;
    const setBusy = (busy) => {
        approve.disabled = busy;
        reject.disabled = busy;
    };
    const finish = () => {
        settled = true;
        known.delete(review.request_id);
        if (dialog.open) dialog.close();
    };
    const rejectReview = async () => {
        if (settled) return;
        setBusy(true);
        status.textContent = "Rejecting…";
        try {
            await sendDecision(review.request_id, "reject", { decision: "reject" });
            finish();
        } catch (error) {
            if (error.status === 409) {
                finish();
                return;
            }
            status.textContent = `Could not reject: ${error.message || error}`;
            setBusy(false);
        }
    };
    reject.addEventListener("click", () => void rejectReview());
    approve.addEventListener("click", async () => {
        if (settled) return;
        setBusy(true);
        status.textContent = "Approving… upload will start next";
        const edits = normalizeReviewEdits({
            title: titleInput.value,
            prompt: promptInput.value,
            tags: tagsInput.value.split(","),
            nsfw: nsfwInput.checked,
        });
        try {
            await sendDecision(review.request_id, "approve", edits);
            finish();
        } catch (error) {
            if (error.status === 409) {
                finish();
                return;
            }
            status.textContent = `Could not approve: ${error.message || error}`;
            setBusy(false);
        }
    });
    dialog.addEventListener("cancel", (event) => {
        event.preventDefault();
        void rejectReview();
    });
    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) void rejectReview();
    });
    dialog.addEventListener("close", () => {
        dialog.remove();
        activeDialog = null;
        if (!settled && dialog.dataset.serverClosed !== "true") {
            void sendDecision(review.request_id, "reject", { decision: "reject" }).catch(() => {});
        }
        showNext();
    });
    activeDialog = dialog;
    dialog.showModal();
    titleInput.focus();
}

function enqueue(review) {
    if (!review || typeof review.request_id !== "string" || known.has(review.request_id)) return;
    known.add(review.request_id);
    queued.push(review);
    showNext();
}

function showNext() {
    if (activeDialog || !queued.length) return;
    showReview(queued.shift());
}

function closeReview(requestId) {
    const index = queued.findIndex((review) => review.request_id === requestId);
    if (index >= 0) queued.splice(index, 1);
    known.delete(requestId);
    if (activeDialog?.dataset.requestId === requestId) {
        activeDialog.dataset.serverClosed = "true";
        activeDialog.close();
    }
}

async function refreshPending() {
    try {
        const response = await api.fetchApi(PENDING_PATH, { cache: "no-store" });
        if (!response.ok) return;
        const payload = await response.json();
        for (const review of payload.pending || []) enqueue(review);
    } catch {
        // Reconnect will retry. A missing browser can never approve the upload.
    }
}

api.addEventListener("civitai_publisher.review", (event) => enqueue(event.detail));
api.addEventListener("civitai_publisher.closed", (event) => closeReview(event.detail?.request_id));
api.addEventListener("reconnected", () => void refreshPending());

app.registerExtension({
    name: "HearmemanAI.CivitAIPublisherReview",
    async setup() {
        installStyles();
        await refreshPending();
    },
});
