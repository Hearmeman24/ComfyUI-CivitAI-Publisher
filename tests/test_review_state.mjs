import assert from "node:assert/strict";
import test from "node:test";

import { normalizeReviewEdits, resourceGroups } from "../web/review_state.mjs";

test("review edits trim fields and drop empty or non-string tags", () => {
    assert.deepEqual(normalizeReviewEdits({
        title: "  title  ",
        prompt: "  prompt  ",
        tags: [" one ", "", 2, "two"],
        nsfw: 1,
        token: "never forward",
    }), {
        title: "title",
        prompt: "prompt",
        tags: ["one", "two"],
        nsfw: true,
    });
});

test("resources group resolved types and retain unknown local filenames", () => {
    const groups = resourceGroups([
        { filename: "base.safetensors", resource_type: "checkpoint", resolved: true, name: "Base" },
        { filename: "style.safetensors", resource_type: "lora", resolved: true, name: "Style" },
        { filename: "private.safetensors", resource_type: "lora", resolved: false },
    ]);
    assert.deepEqual(groups.map((group) => group.label), ["Checkpoints", "LoRAs", "Unknown"]);
    assert.equal(groups[2].rows[0].filename, "private.safetensors");
});
