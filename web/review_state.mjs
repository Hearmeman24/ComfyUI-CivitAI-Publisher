export function normalizeReviewEdits(value = {}) {
    const tags = Array.isArray(value.tags)
        ? value.tags
            .filter((item) => typeof item === "string")
            .map((item) => item.trim())
            .filter(Boolean)
            .slice(0, 50)
        : [];
    return {
        title: typeof value.title === "string" ? value.title.trim() : "",
        prompt: typeof value.prompt === "string" ? value.prompt.trim() : "",
        tags,
        nsfw: Boolean(value.nsfw),
    };
}

export function submitRejectImmediately(renderRejected, sendDecision) {
    renderRejected();
    return Promise.resolve().then(sendDecision);
}

const GROUPS = {
    checkpoint: { label: "Checkpoints", order: 0 },
    lora: { label: "LoRAs", order: 1 },
    locon: { label: "LoRAs", order: 1 },
    lycoris: { label: "LoRAs", order: 1 },
    textualinversion: { label: "Textual Inversions", order: 2 },
    hypernetwork: { label: "Hypernetworks", order: 3 },
    controlnet: { label: "ControlNets", order: 4 },
};

export function resourceGroups(resources = []) {
    const buckets = new Map();
    for (const row of resources) {
        const resourceType = String(row.resource_type || row.type || "").toLowerCase();
        const group = GROUPS[resourceType] || { label: "Other weights", order: 50 };
        if (!buckets.has(group.label)) buckets.set(group.label, { ...group, rows: [] });
        buckets.get(group.label).rows.push(row);
    }
    return Array.from(buckets.values()).sort((left, right) => left.order - right.order);
}
