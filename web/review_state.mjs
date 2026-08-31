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
        const resolvedType = String(row.type || row.resource_type || "").toLowerCase();
        const group = row.resolved
            ? (GROUPS[resolvedType] || { label: row.type || row.resource_type || "Other", order: 50 })
            : { label: "Unknown", order: 99 };
        if (!buckets.has(group.label)) buckets.set(group.label, { ...group, rows: [] });
        buckets.get(group.label).rows.push(row);
    }
    return Array.from(buckets.values()).sort((left, right) => left.order - right.order);
}
