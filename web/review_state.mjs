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
};

export function resourceGroups(resources = []) {
    const buckets = new Map();
    for (const row of resources) {
        const group = row.resolved
            ? (GROUPS[String(row.resource_type || "").toLowerCase()] || { label: row.type || "Other", order: 50 })
            : { label: "Unknown", order: 99 };
        if (!buckets.has(group.label)) buckets.set(group.label, { ...group, rows: [] });
        buckets.get(group.label).rows.push(row);
    }
    return Array.from(buckets.values()).sort((left, right) => left.order - right.order);
}
