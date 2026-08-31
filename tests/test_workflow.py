from __future__ import annotations

import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from civitai_publisher.hashing import HashCache, hash_file
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

    def test_dynamic_openrouter_output_does_not_mine_its_system_prompt(self):
        prompt = {
            "170": {
                "class_type": "PrimitiveStringMultiline",
                "inputs": {"value": "brief supplied to the prompt writer"},
            },
            "259": {
                "class_type": "OpenRouterSimple",
                "inputs": {
                    "system_prompt": "SYSTEM " * 500,
                    "user_prompt": ["170", 0],
                },
            },
            "130": {
                "class_type": "MiniMaxH3ImageToVideo",
                "inputs": {"prompt": ["259", 0]},
            },
            "193": {
                "class_type": "SamplerSubgraph",
                "inputs": {"conditioning": ["130", 0]},
            },
            "275": {
                "class_type": "CreateVideo",
                "inputs": {"images": ["193", 0]},
            },
            "272": {
                "class_type": "CivitAIPublisher",
                "inputs": {"video": ["275", 0]},
            },
        }

        generation = extract_generation_metadata(prompt, root_node_id="272")

        self.assertEqual(generation.prompt, "")

    def test_resource_discovery_is_media_lineage_only_and_excludes_auxiliary_weights(self):
        prompt = {
            "135": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "minimax_h3_fl2va_bf16.safetensors"},
            },
            "266": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": ["135", 0],
                    "lora_name": (
                        "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors"
                    ),
                    "strength_model": 0.5,
                },
            },
            "271": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": ["266", 0],
                    "lora_name": "Vagina_minimax-h3_epoch20.safetensors",
                    "strength_model": 0.4,
                },
            },
            "258": {
                "class_type": "LoraLoaderModelOnly",
                "inputs": {
                    "model": ["271", 0],
                    "lora_name": "HMMasturbationV1.safetensors",
                    "strength_model": 1.0,
                },
            },
            "121": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": "video_vae.safetensors"},
            },
            "127": {
                "class_type": "CLIPLoader",
                "inputs": {"clip_name": "text_encoder.safetensors"},
            },
            "130": {
                "class_type": "MiniMaxH3ImageToVideo",
                "inputs": {"clip": ["127", 0], "vae": ["121", 0], "prompt": "actual prompt"},
            },
            "193": {
                "class_type": "SamplerSubgraph",
                "inputs": {"model": ["258", 0], "conditioning": ["130", 0]},
            },
            "275": {
                "class_type": "CreateVideo",
                "inputs": {"images": ["193", 0]},
            },
            "272": {
                "class_type": "CivitAIPublisher",
                "inputs": {"video": ["275", 0]},
            },
            "900": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "unrelated.safetensors"},
            },
        }
        resolved = {
            "minimax_h3_fl2va_bf16.safetensors": (
                "diffusion_models",
                Path("/models/diffusion_models/minimax_h3_fl2va_bf16.safetensors"),
            ),
            "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors": (
                "loras",
                Path(
                    "/models/loras/"
                    "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors"
                ),
            ),
            "Vagina_minimax-h3_epoch20.safetensors": (
                "loras",
                Path("/models/loras/Vagina_minimax-h3_epoch20.safetensors"),
            ),
            "HMMasturbationV1.safetensors": (
                "loras",
                Path("/models/loras/HMMasturbationV1.safetensors"),
            ),
            "video_vae.safetensors": ("vae", Path("/models/vae/video_vae.safetensors")),
            "text_encoder.safetensors": (
                "text_encoders",
                Path("/models/text_encoders/text_encoder.safetensors"),
            ),
            "unrelated.safetensors": (
                "diffusion_models",
                Path("/models/diffusion_models/unrelated.safetensors"),
            ),
        }

        refs = discover_model_references(prompt, resolved.get, root_node_id="272")

        self.assertEqual(
            [ref.filename for ref in refs],
            [
                "minimax_h3_fl2va_bf16.safetensors",
                "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors",
                "Vagina_minimax-h3_epoch20.safetensors",
                "HMMasturbationV1.safetensors",
            ],
        )
        self.assertEqual([ref.strengths for ref in refs[1:]], [(0.5,), (0.4,), (1.0,)])


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

    def test_concurrent_misses_share_one_hash_calculation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "model.safetensors"
            model.write_bytes(b"model bytes")
            cache = HashCache(root / "hashes.json")
            calls = 0

            def slow_hash(path, cancel=None):
                nonlocal calls
                calls += 1
                time.sleep(0.05)
                return hash_file(path, cancel=cancel)

            with mock.patch("civitai_publisher.hashing.hash_file", side_effect=slow_hash):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _index: cache.lookup(model), range(2)))

            self.assertEqual(calls, 1)
            self.assertEqual(results[0].sha256, results[1].sha256)
            self.assertEqual(sorted(result.cached for result in results), [False, True])

    def test_cache_write_failure_does_not_discard_completed_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "model.safetensors"
            model.write_bytes(b"model bytes")
            cache = HashCache(root / "hashes.json")

            with mock.patch("civitai_publisher.hashing.os.replace", side_effect=OSError("read-only")):
                first = cache.lookup(model)
            second = cache.lookup(model)

            self.assertFalse(first.cached)
            self.assertTrue(second.cached)
            self.assertEqual(first.sha256, second.sha256)


if __name__ == "__main__":
    unittest.main()
