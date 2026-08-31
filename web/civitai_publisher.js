import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { normalizeReviewEdits, resourceGroups } from "./review_state.mjs";

const NODE_NAME = "CivitAIPublisher";
const DECISION_PATH = "/civitai_publisher/decision";
const PENDING_PATH = "/civitai_publisher/pending";
const NODE_WIDTH = 560;
const REVIEW_HEIGHT = 700;
const STYLE_VERSION = "20260831-3";
const liveNodes = new Map();
const waitingReviews = new Map();
const knownReviews = new Set();

const LOG_PREFIX = "[CivitAIPublisher]";

function logValue(value) {
    if (typeof value === "boolean") return value ? "true" : "false";
    if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(Math.round(value * 1000) / 1000);
    const text = String(value ?? "");
    if (!text) return '""';
    return /[ "]/u.test(text) ? `"${text.replaceAll('"', "'")}"` : text;
}

function logLine(event, fields = {}) {
    let line = `${LOG_PREFIX} event=${event}`;
    for (const [key, value] of Object.entries(fields)) {
        if (value === undefined || value === null) continue;
        line += ` ${key}=${logValue(value)}`;
    }
    return line;
}

const blog = (event, fields) => console.info(logLine(event, fields));
const bwarn = (event, fields) => console.warn(logLine(event, fields));

function injectStyles() {
    if (document.getElementById("civitai-publisher-styles")) return;
    const link = document.createElement("link");
    link.id = "civitai-publisher-styles";
    link.rel = "stylesheet";
    const styleUrl = new URL("./civitai_publisher.css", import.meta.url);
    styleUrl.searchParams.set("v", STYLE_VERSION);
    link.href = styleUrl.href;
    document.head.appendChild(link);
}

function el(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
}

function nodeKey(value) {
    return String(value ?? "");
}

function findNode(id) {
    const key = nodeKey(id);
    const tracked = liveNodes.get(key);
    if (tracked) return tracked;
    const numeric = Number(key);
    const graphNode = app.graph?.getNodeById?.(Number.isFinite(numeric) ? numeric : key);
    if (graphNode?._civitaiPublisherBody) {
        liveNodes.set(key, graphNode);
        return graphNode;
    }
    return null;
}

function widgetByName(node, name) {
    return (node.widgets || []).find((widget) => widget.name === name);
}

function widgetValue(node, name, fallback) {
    const widget = widgetByName(node, name);
    return widget ? widget.value : fallback;
}

function previewUrl(item) {
    const params = new URLSearchParams({
        filename: item.filename,
        type: item.folder_type || "temp",
        subfolder: item.subfolder || "",
    });
    return api.apiURL(`/view?${params.toString()}`);
}

function canvasSize(canvas) {
    const width = Math.max(1, Math.round(canvas.clientWidth));
    const height = Math.max(1, Math.round(canvas.clientHeight));
    const ratio = Math.max(1, window.devicePixelRatio || 1);
    const backingWidth = Math.round(width * ratio);
    const backingHeight = Math.round(height * ratio);
    if (canvas.width !== backingWidth || canvas.height !== backingHeight) {
        canvas.width = backingWidth;
        canvas.height = backingHeight;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { ctx, width, height };
}

function drawCanvasMessage(node, heading, detail = "") {
    const body = node._civitaiPublisherBody;
    if (!body) return;
    const { ctx, width, height } = canvasSize(body.canvas);
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, width, height);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#e0e0e0";
    ctx.font = "600 15px ui-sans-serif, system-ui";
    ctx.fillText(heading, width / 2, height / 2 - (detail ? 10 : 0));
    if (detail) {
        ctx.fillStyle = "#888";
        ctx.font = "12px ui-sans-serif, system-ui";
        ctx.fillText(detail, width / 2, height / 2 + 14);
    }
}

function drawImage(node, image, count) {
    const body = node._civitaiPublisherBody;
    if (!body || body.previewImage !== image) return;
    const { ctx, width, height } = canvasSize(body.canvas);
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, width, height);
    const scale = Math.min(width / image.naturalWidth, height / image.naturalHeight);
    const drawWidth = image.naturalWidth * scale;
    const drawHeight = image.naturalHeight * scale;
    ctx.drawImage(image, (width - drawWidth) / 2, (height - drawHeight) / 2, drawWidth, drawHeight);
    if (count > 1) {
        const label = `${count} images`;
        ctx.font = "600 11px ui-sans-serif, system-ui";
        const labelWidth = ctx.measureText(label).width + 16;
        ctx.fillStyle = "rgba(0, 0, 0, .75)";
        ctx.fillRect(width - labelWidth - 8, 8, labelWidth, 24);
        ctx.fillStyle = "#fff";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(label, width - labelWidth / 2 - 8, 20);
    }
}

function clearMedia(node) {
    const body = node._civitaiPublisherBody;
    if (!body) return;
    body.previewImage = null;
    body.video.pause();
    body.video.onerror = null;
    body.video.removeAttribute("src");
    body.video.load();
    body.video.hidden = true;
    body.canvas.hidden = false;
}

function mediaFailed(node, kind) {
    const body = node._civitaiPublisherBody;
    clearMedia(node);
    drawCanvasMessage(node, `${kind} preview unavailable`, "Reject this review and inspect the ComfyUI log");
    body.approve.disabled = true;
    body.reject.disabled = false;
    setStatus(node, "error", `${kind} preview failed · publishing is disabled`);
}

function renderMedia(node, media) {
    const body = node._civitaiPublisherBody;
    clearMedia(node);
    const items = Array.isArray(media) ? media : [];
    if (!items.length) {
        drawCanvasMessage(node, "No media preview", "Nothing can be approved");
        return false;
    }
    const first = items[0];
    if (first.type === "video") {
        body.canvas.hidden = true;
        body.video.hidden = false;
        body.video.src = previewUrl(first);
        body.video.onerror = () => mediaFailed(node, "Video");
        body.video.load();
        return true;
    }
    drawCanvasMessage(node, "Loading preview…");
    const image = new Image();
    body.previewImage = image;
    image.onload = () => drawImage(node, image, items.length);
    image.onerror = () => mediaFailed(node, "Image");
    image.src = previewUrl(first);
    return true;
}

function metadataText(metadata) {
    const rows = [];
    const add = (label, value) => {
        if (value !== undefined && value !== null && value !== "") rows.push(`${label} ${value}`);
    };
    add("Seed", metadata?.seed);
    add("Steps", metadata?.steps);
    add("CFG", metadata?.cfgScale);
    add("Sampler", metadata?.sampler);
    add("Scheduler", metadata?.scheduler);
    add("Size", metadata?.size);
    return rows;
}

function renderResources(node, resources) {
    const container = node._civitaiPublisherBody.resources;
    container.replaceChildren();
    const groups = resourceGroups(resources);
    if (!groups.length) {
        container.appendChild(el("div", "civitai-publisher-empty", "No publishable model weights detected on this media branch."));
        return;
    }
    for (const group of groups) {
        const section = el("section", "civitai-publisher-resource-group");
        section.appendChild(el("div", "civitai-publisher-resource-title", group.label));
        for (const row of group.rows) {
            const resource = el("div", `civitai-publisher-resource${row.resolved ? "" : " unknown"}`);
            const name = row.resolved
                ? `${row.name || row.filename}${row.versionName && row.versionName !== row.name ? ` · ${row.versionName}` : ""}`
                : `${row.filename} · ${row.resolution_error || "not on CivitAI"}`;
            const resourceName = el("span", "civitai-publisher-resource-name", name);
            resourceName.title = name;
            resource.appendChild(resourceName);
            const strengths = Array.isArray(row.strengths) && row.strengths.length
                ? ` @ ${row.strengths.join(" / ")}`
                : "";
            resource.appendChild(el("span", "civitai-publisher-resource-meta", `${row.autov2 || ""}${strengths}`));
            section.appendChild(resource);
        }
        container.appendChild(section);
    }
}

function setStatus(node, state, text, postUrl = "") {
    const body = node._civitaiPublisherBody;
    body.root.dataset.state = state;
    body.state.textContent = text;
    body.result.replaceChildren();
    if (postUrl) {
        const link = el("a", "civitai-publisher-result-link", "Open CivitAI post");
        link.href = postUrl;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        body.result.appendChild(link);
    }
}

function renderIdle(node) {
    const body = node._civitaiPublisherBody;
    node._civitaiReview = null;
    node._civitaiDecision = "";
    clearMedia(node);
    drawCanvasMessage(node, "Ready for review", "Queue the workflow to prepare media");
    body.prompt.value = "";
    body.prompt.placeholder = "The exact conditioning prompt will appear here.";
    body.metadata.replaceChildren();
    body.negative.hidden = true;
    body.resources.replaceChildren(el("div", "civitai-publisher-empty", "No pending review."));
    body.approve.disabled = true;
    body.reject.disabled = true;
    setStatus(node, "idle", "Idle · nothing has been uploaded");
}

function attachReview(node, review) {
    if (!review || knownReviews.has(review.request_id)) return;
    knownReviews.add(review.request_id);
    node._civitaiReview = review;
    node._civitaiDecision = "";
    const body = node._civitaiPublisherBody;
    const hasMedia = renderMedia(node, review.media || []);
    body.prompt.value = review.prompt || "";
    body.metadata.replaceChildren(...metadataText(review.metadata).map((item) => el("span", "civitai-publisher-chip", item)));
    if (review.negative_prompt) {
        body.negative.hidden = false;
        body.negativeText.textContent = review.negative_prompt;
    } else {
        body.negative.hidden = true;
        body.negativeText.textContent = "";
    }
    renderResources(node, review.resources || []);
    body.approve.disabled = !hasMedia;
    body.reject.disabled = false;
    setStatus(node, "review", `${(review.media || []).length} media file${(review.media || []).length === 1 ? "" : "s"} · approval required`);
    blog("review_rendered", {
        node_id: review.node_id,
        media: (review.media || []).length,
        resources: (review.resources || []).length,
    });
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

function reviewEdits(node, review) {
    const tags = String(widgetValue(node, "tags", (review.tags || []).join(","))).split(",");
    return normalizeReviewEdits({
        title: String(widgetValue(node, "title", review.title || "")),
        prompt: node._civitaiPublisherBody.prompt.value,
        tags,
        nsfw: Boolean(widgetValue(node, "nsfw", review.nsfw)),
    });
}

async function decide(node, decision) {
    const review = node._civitaiReview;
    if (!review || node._civitaiDecision) return;
    const body = node._civitaiPublisherBody;
    node._civitaiDecision = decision;
    body.approve.disabled = true;
    body.reject.disabled = true;
    setStatus(node, decision === "approve" ? "publishing" : "rejected", decision === "approve" ? "Approval sent · publishing next" : "Rejecting…");
    try {
        await sendDecision(review.request_id, decision, reviewEdits(node, review));
        blog("review_decided", { node_id: review.node_id, decision });
        if (decision === "reject") {
            clearMedia(node);
            drawCanvasMessage(node, "Rejected", "No media was uploaded");
            setStatus(node, "rejected", "Rejected · nothing was uploaded");
        }
    } catch (error) {
        if (error.status === 409) return;
        node._civitaiDecision = "";
        body.approve.disabled = false;
        body.reject.disabled = false;
        setStatus(node, "error", `Decision failed · ${error.message || error}`);
        bwarn("decision_failed", { node_id: review.node_id, error: error.name || "Error" });
    }
}

function handleReview(review) {
    if (!review || typeof review.request_id !== "string" || knownReviews.has(review.request_id)) return;
    const node = findNode(review.node_id);
    if (node) {
        attachReview(node, review);
        return;
    }
    waitingReviews.set(nodeKey(review.node_id), review);
}

function handleClosed(detail) {
    const requestId = detail?.request_id;
    if (!requestId) return;
    knownReviews.delete(requestId);
    for (const [key, review] of waitingReviews.entries()) {
        if (review.request_id === requestId) waitingReviews.delete(key);
    }
    for (const node of liveNodes.values()) {
        if (node._civitaiReview?.request_id !== requestId) continue;
        if (!node._civitaiDecision) {
            clearMedia(node);
            drawCanvasMessage(node, "Review closed", "No approval was recorded");
            setStatus(node, "idle", "Review closed · nothing was uploaded");
            node._civitaiReview = null;
        }
    }
}

function handleStatus(detail) {
    const node = findNode(detail?.node_id);
    if (!node) return;
    const state = detail?.state || "";
    if (state === "publishing") {
        setStatus(node, state, "Publishing to CivitAI…");
    } else if (state === "published") {
        clearMedia(node);
        drawCanvasMessage(node, "Published", "The CivitAI post is live");
        setStatus(node, state, "Published successfully", detail.post_url || "");
    } else if (state === "rejected") {
        clearMedia(node);
        drawCanvasMessage(node, "Rejected", "No media was uploaded");
        setStatus(node, state, "Rejected · nothing was uploaded");
    } else if (state === "timed_out") {
        clearMedia(node);
        drawCanvasMessage(node, "Review timed out", "No media was uploaded");
        setStatus(node, state, "Timed out · nothing was uploaded");
    } else if (state === "failed") {
        clearMedia(node);
        drawCanvasMessage(node, "Publish failed", "Check the ComfyUI log for the safe error summary");
        setStatus(node, "error", `Publish failed · ${detail.error || "Error"}`);
    }
}

async function refreshPending() {
    try {
        const response = await api.fetchApi(PENDING_PATH, { cache: "no-store" });
        if (!response.ok) return;
        const payload = await response.json();
        for (const review of payload.pending || []) handleReview(review);
    } catch {
        // Reconnect repeats this read. An unavailable browser cannot approve.
    }
}

function buildReviewBlock(node) {
    const root = el("div", "civitai-publisher-node-review");
    const heading = el("div", "civitai-publisher-heading");
    heading.appendChild(el("span", "civitai-publisher-kicker", "CivitAI review"));
    const state = el("span", "civitai-publisher-state", "Idle");
    state.role = "status";
    state.setAttribute("aria-live", "polite");
    root.appendChild(heading);

    const mediaStage = el("div", "civitai-publisher-media-stage");
    const canvas = document.createElement("canvas");
    canvas.className = "civitai-publisher-canvas";
    canvas.role = "img";
    canvas.setAttribute("aria-label", "CivitAI publication media preview");
    const video = document.createElement("video");
    video.className = "civitai-publisher-video";
    video.controls = true;
    video.preload = "metadata";
    video.playsInline = true;
    video.hidden = true;
    video.setAttribute("aria-label", "CivitAI publication video preview");
    mediaStage.append(canvas, video);
    root.appendChild(mediaStage);

    const metadata = el("div", "civitai-publisher-metadata");
    root.appendChild(metadata);

    const promptLabel = el("label", "civitai-publisher-label", "Generation prompt");
    const prompt = document.createElement("textarea");
    prompt.className = "civitai-publisher-prompt";
    prompt.spellcheck = false;
    promptLabel.appendChild(prompt);
    root.appendChild(promptLabel);

    const negative = document.createElement("details");
    negative.className = "civitai-publisher-negative";
    negative.appendChild(el("summary", "", "Negative prompt"));
    const negativeText = el("div", "civitai-publisher-negative-text");
    negative.appendChild(negativeText);
    root.appendChild(negative);

    root.appendChild(el("div", "civitai-publisher-section-label", "Models and LoRAs"));
    const resources = el("div", "civitai-publisher-resources");
    root.appendChild(resources);

    const footer = el("div", "civitai-publisher-footer");
    const statusColumn = el("div", "civitai-publisher-status-column");
    const result = el("div", "civitai-publisher-result");
    statusColumn.append(state, result);
    const actions = el("div", "civitai-publisher-actions");
    const reject = el("button", "civitai-publisher-button civitai-publisher-reject", "Reject");
    const approve = el("button", "civitai-publisher-button civitai-publisher-approve", "Approve & publish");
    reject.type = "button";
    approve.type = "button";
    reject.onclick = () => void decide(node, "reject");
    approve.onclick = () => void decide(node, "approve");
    actions.append(reject, approve);
    footer.append(statusColumn, actions);
    root.appendChild(footer);

    const resizeObserver = new ResizeObserver(() => {
        if (node._civitaiPublisherBody?.previewImage?.complete) {
            drawImage(node, node._civitaiPublisherBody.previewImage, node._civitaiReview?.media?.length || 1);
        } else if (!node._civitaiReview) {
            drawCanvasMessage(node, "Ready for review", "Queue the workflow to prepare media");
        }
    });
    resizeObserver.observe(canvas);

    node._civitaiPublisherBody = {
        root,
        canvas,
        video,
        previewImage: null,
        metadata,
        prompt,
        negative,
        negativeText,
        resources,
        state,
        result,
        reject,
        approve,
        resizeObserver,
    };
    return root;
}

function registerNode(node) {
    const key = nodeKey(node.id);
    if (key && key !== "-1") liveNodes.set(key, node);
    const waiting = waitingReviews.get(key);
    if (waiting) {
        waitingReviews.delete(key);
        attachReview(node, waiting);
    }
}

api.addEventListener("civitai_publisher.review", (event) => handleReview(event.detail));
api.addEventListener("civitai_publisher.closed", (event) => handleClosed(event.detail));
api.addEventListener("civitai_publisher.status", (event) => handleStatus(event.detail));
api.addEventListener("reconnected", () => void refreshPending());

app.registerExtension({
    name: "HearmemanAI.CivitAIPublisherReview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;
        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            originalCreated?.apply(this, arguments);
            injectStyles();
            const node = this;
            const body = buildReviewBlock(node);
            const widget = node.addDOMWidget("civitai_publisher_review", "custom", body, { serialize: false });
            widget.computeSize = () => [Math.max(520, (node.size?.[0] || NODE_WIDTH) - 20), REVIEW_HEIGHT];
            node._civitaiPublisherWidget = widget;
            renderIdle(node);
            setTimeout(() => {
                registerNode(node);
                const computed = node.computeSize?.() || [NODE_WIDTH, REVIEW_HEIGHT + 180];
                node.setSize?.([Math.max(NODE_WIDTH, computed[0]), Math.max(REVIEW_HEIGHT + 180, computed[1])]);
                app.graph?.setDirtyCanvas?.(true, true);
            }, 0);

            const originalConfigure = node.onConfigure;
            node.onConfigure = function () {
                const result = originalConfigure?.apply(this, arguments);
                setTimeout(() => registerNode(this), 0);
                return result;
            };
            const originalRemoved = node.onRemoved;
            node.onRemoved = function () {
                const review = this._civitaiReview;
                if (review && !this._civitaiDecision) {
                    void sendDecision(review.request_id, "reject", {}).catch(() => {});
                }
                liveNodes.delete(nodeKey(this.id));
                this._civitaiPublisherBody?.resizeObserver?.disconnect();
                clearMedia(this);
                return originalRemoved?.apply(this, arguments);
            };
        };
    },
    async setup() {
        injectStyles();
        await refreshPending();
    },
});
