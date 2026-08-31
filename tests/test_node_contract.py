from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import os
import sys
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest import mock

from civitai_publisher.approval import ApprovalDecision, DecisionState
from civitai_publisher.client import PublishResult
from civitai_publisher.media import MaterializedMedia, MediaUpload
from civitai_publisher.workflow import GenerationMetadata


class NodeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "comfyui_civitai_publisher",
            root / "__init__.py",
            submodule_search_locations=[str(root)],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.module = module
        cls.node_module = sys.modules[f"{spec.name}.node"]

    def test_public_node_contract(self):
        node = self.module.NODE_CLASS_MAPPINGS["CivitAIPublisher"]
        inputs = node.INPUT_TYPES()
        self.assertEqual(set(inputs["required"]), {
            "title", "tags", "nsfw", "prompt_override", "approval_timeout_minutes",
        })
        self.assertEqual(set(inputs["optional"]), {"image", "video"})
        self.assertEqual(inputs["hidden"], {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"})
        self.assertEqual(node.RETURN_NAMES, ("post_url", "status", "details"))
        self.assertTrue(node.OUTPUT_NODE)
        self.assertTrue(math.isnan(node.IS_CHANGED()))
        self.assertEqual(self.module.WEB_DIRECTORY, "./web")

    def test_token_is_environment_only_with_documented_precedence(self):
        with mock.patch.dict(os.environ, {
            "CIVITAI_TOKEN": "canonical",
            "CIVITAI_API_KEY": "alias",
            "civitai_token": "legacy",
        }, clear=True):
            self.assertEqual(self.node_module.resolve_civitai_token(), "canonical")
        with mock.patch.dict(os.environ, {"CIVITAI_API_KEY": "alias"}, clear=True):
            self.assertEqual(self.node_module.resolve_civitai_token(), "alias")
        with mock.patch.dict(os.environ, {"civitai_token": "legacy"}, clear=True):
            self.assertEqual(self.node_module.resolve_civitai_token(), "legacy")

    def test_reject_returns_without_uploading(self):
        result, client = self._run_node(DecisionState.REJECTED, return_client=True)
        self.assertEqual(result[0:2], ("", "rejected"))
        self.assertEqual(json.loads(result[2])["uploaded"], False)
        self.assertEqual(client.publish_calls, 0)

    def test_approve_publishes_exactly_once(self):
        result, client = self._run_node(DecisionState.APPROVED, return_client=True)
        self.assertEqual(result[0:2], ("https://civitai.com/posts/8", "published"))
        self.assertEqual(client.publish_calls, 1)

    def test_timeout_raises_without_uploading(self):
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self._run_node(DecisionState.TIMED_OUT)
        self.assertEqual(self.last_client.publish_calls, 0)

    def _run_node(self, state, return_client=False):
        node_module = self.node_module

        @asynccontextmanager
        async def fake_materialize(**_kwargs):
            yield MaterializedMedia(
                uploads=(
                    MediaUpload(
                        path=Path("/tmp/civitai-publisher-preview.png"),
                        content_type="image/png",
                        width=64,
                        height=64,
                    ),
                ),
                previews=({"type": "image", "filename": "preview.png", "subfolder": "x"},),
            )

        class FakeApprovals:
            async def wait_for_decision(self, payload, **_kwargs):
                return ApprovalDecision(
                    state=node_module.DecisionState(state.value),
                    title="Reviewed",
                    prompt="Reviewed prompt",
                    tags=("one",),
                    nsfw=False,
                )

        class FakeClient:
            def __init__(self, _token):
                self.publish_calls = 0

            async def resolve_resources(self, resources):
                return resources

            async def publish_post(self, **_kwargs):
                self.publish_calls += 1
                return PublishResult(8, "https://civitai.com/posts/8")

        client = FakeClient("key")
        self.last_client = client
        with (
            mock.patch.object(node_module, "resolve_civitai_token", return_value="key"),
            mock.patch.object(node_module, "materialize_media", fake_materialize),
            mock.patch.object(node_module, "discover_and_hash_resources", return_value=[]),
            mock.patch.object(
                node_module,
                "extract_generation_metadata",
                return_value=GenerationMetadata(prompt="Auto prompt"),
            ),
            mock.patch.object(node_module, "APPROVALS", FakeApprovals()),
            mock.patch.object(node_module, "CivitAIClient", return_value=client),
        ):
            result = asyncio.run(node_module.CivitAIPublisher().publish(
                title="",
                tags="one",
                nsfw=False,
                prompt_override="",
                approval_timeout_minutes=5,
                image=object(),
                video=None,
                prompt={},
                unique_id="9",
            ))
        if return_client:
            return result, client
        return result


if __name__ == "__main__":
    unittest.main()
