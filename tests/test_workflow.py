from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from civitai_publisher.hashing import HashCache
from civitai_publisher.workflow import discover_model_references, extract_generation_metadata


class WorkflowInspectionTests(unittest.TestCase):
    def test_discovers_regular_power_and_generic_model_files(self):
        prompt = {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "base.gguf", "weight_dtype": "default"},
            },
            "2": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": ["1", 0],
                    "lora_name": "detail.safetensors",
                    "strength_model": 0.65,
                },
            },
            "3": {
                "class_type": "Power Lora Loader (rgthree)",
                "inputs": {
                    "model": ["2", 0],
                    "lora_1": {
                        "on": True,
                        "lora": "style.safetensors",
                        "strength": 0.8,
                    },
                    "lora_2": {
                        "on": False,
                        "lora": "disabled.safetensors",
                        "strength": 1.0,
                    },
                    "lora_3": {
                        "on": True,
                        "lora": "zero.safetensors",
                        "strength": 0.0,
                    },
                },
            },
        }
        resolved = {
            "base.gguf": ("diffusion_models", Path("/models/unet/base.gguf")),
            "detail.safetensors": ("loras", Path("/models/loras/detail.safetensors")),
            "style.safetensors": ("loras", Path("/models/loras/style.safetensors")),
            "disabled.safetensors": ("loras", Path("/models/loras/disabled.safetensors")),
            "zero.safetensors": ("loras", Path("/models/loras/zero.safetensors")),
        }

        refs = discover_model_references(prompt, resolved.get)

        self.assertEqual([ref.filename for ref in refs], [
            "base.gguf",
            "detail.safetensors",
            "style.safetensors",
        ])
        by_name = {ref.filename: ref for ref in refs}
        self.assertEqual(by_name["base.gguf"].resource_type, "checkpoint")
        self.assertEqual(by_name["detail.safetensors"].strengths, (0.65,))
        self.assertEqual(by_name["style.safetensors"].strengths, (0.8,))

    def test_deduplicates_same_file_and_omits_weight_when_strengths_conflict(self):
        prompt = {
            "1": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {"lora_name": "same.safetensors", "strength_model": 0.4},
            },
            "2": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {"lora_name": "same.safetensors", "strength_model": 0.9},
            },
        }
        def resolver(value):
            if value == "same.safetensors":
                return "loras", Path("/models/loras/same.safetensors")
            return None

        refs = discover_model_references(prompt, resolver)

        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].strengths, (0.4, 0.9))
        self.assertIsNone(refs[0].civitai_weight)
        self.assertEqual(refs[0].node_ids, ("1", "2"))

    def test_prompt_override_wins_and_auto_detection_separates_negative(self):
        prompt = {
            "10": {"class_type": "CLIPTextEncode", "inputs": {"text": "a portrait in warm window light"}},
            "11": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry, watermark"}},
            "12": {
                "class_type": "KSampler",
                "inputs": {
                    "positive": ["10", 0],
                    "negative": ["11", 0],
                    "seed": 123,
                    "steps": 28,
                    "cfg": 5.5,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                },
            },
        }

        automatic = extract_generation_metadata(prompt, prompt_override="")
        overridden = extract_generation_metadata(prompt, prompt_override="editorial close-up")

        self.assertEqual(automatic.prompt, "a portrait in warm window light")
        self.assertEqual(automatic.negative_prompt, "blurry, watermark")
        self.assertEqual(automatic.seed, 123)
        self.assertEqual(automatic.steps, 28)
        self.assertEqual(automatic.cfg_scale, 5.5)
        self.assertEqual(automatic.sampler, "euler")
        self.assertEqual(overridden.prompt, "editorial close-up")

    def test_follows_wired_prompt_to_literal_string_source(self):
        prompt = {
            "1": {
                "class_type": "PrimitiveStringMultiline",
                "inputs": {"value": "cinematic rain at midnight"},
            },
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ["1", 0]}},
            "3": {"class_type": "KSampler", "inputs": {"positive": ["2", 0]}},
        }
        self.assertEqual(
            extract_generation_metadata(prompt, prompt_override="").prompt,
            "cinematic rain at midnight",
        )


class HashCacheTests(unittest.TestCase):
    def test_reuses_unchanged_file_and_invalidates_after_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "model.safetensors"
            cache = HashCache(root / "hashes.json")
            model.write_bytes(b"first")

            first = cache.sha256_for(model)
            with unittest.mock.patch(
                "civitai_publisher.hashing.hash_file",
                side_effect=AssertionError("must use cache"),
            ):
                self.assertEqual(cache.sha256_for(model), first)

            model.write_bytes(b"second version")
            second = cache.sha256_for(model)
            self.assertNotEqual(second, first)


if __name__ == "__main__":
    unittest.main()
