from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from civitai_publisher.client import (
    CivitAIClient,
    CivitAIHTTPError,
    LinkedWorkflow,
    MediaUpload,
    PartialPostError,
    build_civitai_metadata,
)
from civitai_publisher.resolution_cache import ResolutionCache
from civitai_publisher.workflow import GenerationMetadata, HashedResource


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.fail_on = None

    async def json(self, method, url, *, token, payload=None, timeout=30):
        self.calls.append(("json", method, url, payload, token, timeout))
        if self.fail_on and self.fail_on in url:
            raise RuntimeError("provider exploded with secret-token")
        if url.endswith("/api/v1/image-upload"):
            return {"uploadURL": "https://uploads.example/object", "id": "upload-1"}
        if url.endswith("/api/trpc/post.create"):
            return {"result": {"data": {"json": {"id": 321}}}}
        return {"ok": True}

    async def put_file(self, url, path, *, content_type, timeout=120):
        self.calls.append(("put", url, Path(path).name, content_type, timeout))


class CivitAIClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_civitai_model_link_to_latest_published_workflow_version(self):
        class WorkflowTransport(FakeTransport):
            async def json(self, method, url, *, token, payload=None, timeout=30):
                self.calls.append(("json", method, url, payload, token, timeout))
                return {
                    "id": 2850104,
                    "name": "MiniMax H3 workflows",
                    "type": "Workflows",
                    "modelVersions": [
                        {"id": 3218381, "name": "v1.0", "publishedAt": "2026-08-11T08:10:54Z"},
                        {"id": 3295293, "name": "v2.0", "publishedAt": "2026-09-04T09:25:53Z"},
                    ],
                }

        transport = WorkflowTransport()
        client = CivitAIClient("token", transport=transport, retry_delays=(0,))

        workflow = await client.resolve_workflow_link(
            "https://civitai.red/models/2850104/minimax-h3-t2v-i2v-workflows"
        )

        self.assertEqual(workflow.model_id, 2850104)
        self.assertEqual(workflow.model_version_id, 3295293)
        self.assertEqual(workflow.name, "MiniMax H3 workflows")
        self.assertEqual(workflow.version_name, "v2.0")
        self.assertEqual(workflow.url, "https://civitai.red/models/2850104/minimax-h3-t2v-i2v-workflows")
        self.assertEqual(transport.calls[0][2], "https://civitai.com/api/v1/models/2850104")

    async def test_workflow_link_can_pin_an_explicit_version(self):
        class WorkflowTransport(FakeTransport):
            async def json(self, method, url, *, token, payload=None, timeout=30):
                self.calls.append(("json", method, url, payload, token, timeout))
                return {
                    "id": 3218381,
                    "modelId": 2850104,
                    "name": "v1.0",
                    "status": "Published",
                    "publishedAt": "2026-08-11T08:10:54Z",
                    "model": {"name": "MiniMax H3 workflows", "type": "Workflows"},
                }

        transport = WorkflowTransport()
        client = CivitAIClient("token", transport=transport, retry_delays=(0,))

        workflow = await client.resolve_workflow_link(
            "https://civitai.com/models/2850104/example?modelVersionId=3218381"
        )

        self.assertEqual(workflow.model_version_id, 3218381)
        self.assertEqual(transport.calls[0][2], "https://civitai.com/api/v1/model-versions/3218381")

    async def test_workflow_link_rejects_non_civitai_and_non_workflow_models(self):
        client = CivitAIClient("token", transport=FakeTransport(), retry_delays=(0,))
        with self.assertRaisesRegex(ValueError, "civitai.com or https://civitai.red"):
            await client.resolve_workflow_link("https://example.com/models/2850104")

        class CheckpointTransport(FakeTransport):
            async def json(self, method, url, *, token, payload=None, timeout=30):
                return {"id": 7, "name": "Checkpoint", "type": "Checkpoint", "modelVersions": [{"id": 9}]}

        client = CivitAIClient("token", transport=CheckpointTransport(), retry_delays=(0,))
        with self.assertRaisesRegex(ValueError, "not a Workflow"):
            await client.resolve_workflow_link("https://civitai.com/models/7/checkpoint")

    async def test_resolution_cache_avoids_repeating_hash_lookup(self):
        class ResolutionTransport(FakeTransport):
            async def json(self, method, url, *, token, payload=None, timeout=30):
                self.calls.append(("json", method, url, payload, token, timeout))
                return {
                    "id": 20,
                    "modelId": 10,
                    "name": "Version",
                    "model": {"name": "Model", "type": "Checkpoint"},
                }

        transport = ResolutionTransport()
        resource = HashedResource(
            filename="base.safetensors",
            category="diffusion_models",
            path=Path("/models/base.safetensors"),
            resource_type="checkpoint",
            sha256="a" * 64,
        )
        with tempfile.TemporaryDirectory() as tmp:
            cache = ResolutionCache(Path(tmp) / "resources.json")
            client = CivitAIClient("token", transport=transport, resolution_cache=cache)

            first = await client.resolve_resources([resource])
            second = await client.resolve_resources([resource])

        self.assertTrue(first[0].resolved)
        self.assertTrue(second[0].resolved)
        self.assertEqual(len(transport.calls), 1)

    async def test_resolution_retries_read_only_transient_error(self):
        class RetryTransport(FakeTransport):
            def __init__(self):
                super().__init__()
                self.attempts = 0

            async def json(self, method, url, *, token, payload=None, timeout=30):
                self.attempts += 1
                if self.attempts == 1:
                    raise CivitAIHTTPError(503, "temporary")
                return {
                    "id": 20,
                    "modelId": 10,
                    "name": "Version",
                    "model": {"name": "Model", "type": "Checkpoint"},
                }

        transport = RetryTransport()
        client = CivitAIClient("token", transport=transport, retry_delays=(0,))
        resource = HashedResource(
            filename="base.safetensors",
            category="diffusion_models",
            path=Path("/models/base.safetensors"),
            resource_type="checkpoint",
            sha256="b" * 64,
        )

        resolved = await client.resolve_resources([resource])

        self.assertTrue(resolved[0].resolved)
        self.assertEqual(transport.attempts, 2)

    def test_metadata_links_every_resolved_resource_and_preserves_unknown_hashes(self):
        resources = [
            HashedResource(
                filename="base.safetensors",
                category="checkpoints",
                path=Path("/models/base.safetensors"),
                resource_type="checkpoint",
                sha256="a" * 64,
                resolved=True,
                model_version_id=10,
                name="Base model",
                version_name="v1",
            ),
            HashedResource(
                filename="style.safetensors",
                category="loras",
                path=Path("/models/loras/style.safetensors"),
                resource_type="lora",
                sha256="b" * 64,
                strengths=(0.7,),
                resolved=True,
                model_version_id=20,
                name="Style LoRA",
                version_name="Strong",
            ),
            HashedResource(
                filename="private.safetensors",
                category="loras",
                path=Path("/models/loras/private.safetensors"),
                resource_type="lora",
                sha256="c" * 64,
                strengths=(0.4, 0.8),
                resolved=False,
            ),
        ]

        metadata = build_civitai_metadata(
            GenerationMetadata(prompt="portrait", negative_prompt="blurry", seed=4, steps=20),
            resources,
            width=768,
            height=1024,
            linked_workflow=LinkedWorkflow(
                model_id=2850104,
                model_version_id=3295293,
                name="MiniMax H3 workflows",
                version_name="v2.0",
                url="https://civitai.red/models/2850104/minimax-h3-t2v-i2v-workflows",
            ),
        )

        self.assertEqual(metadata["hashes"], {
            "model:base": "AAAAAAAAAA",
            "lora:style": "BBBBBBBBBB",
            "lora:private": "CCCCCCCCCC",
        })
        self.assertEqual(
            [resource["modelVersionId"] for resource in metadata["civitaiResources"]],
            [10, 20, 3295293],
        )
        self.assertEqual(metadata["resources"][1]["weight"], 0.7)
        self.assertNotIn("weight", metadata["resources"][2])
        self.assertEqual(metadata["Size"], "768x1024")

    def test_metadata_does_not_duplicate_an_already_resolved_workflow_version(self):
        resource = HashedResource(
            filename="workflow.safetensors",
            category="checkpoints",
            path=Path("/models/workflow.safetensors"),
            resource_type="checkpoint",
            sha256="d" * 64,
            resolved=True,
            model_version_id=3295293,
            name="MiniMax H3 workflows",
            version_name="v2.0",
        )

        metadata = build_civitai_metadata(
            GenerationMetadata(prompt="portrait"),
            [resource],
            linked_workflow=LinkedWorkflow(
                model_id=2850104,
                model_version_id=3295293,
                name="MiniMax H3 workflows",
                version_name="v2.0",
                url="https://civitai.red/models/2850104/minimax-h3-t2v-i2v-workflows",
            ),
        )

        self.assertEqual(
            [item["modelVersionId"] for item in metadata["civitaiResources"]],
            [3295293],
        )

    async def test_publish_orders_presign_upload_create_attach_tags_rating_and_publish(self):
        transport = FakeTransport()
        client = CivitAIClient("secret-token", transport=transport)
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "image.png"
            media.write_bytes(b"png")
            result = await client.publish_post(
                media=[MediaUpload(media, "image/png", 640, 480)],
                title="A title",
                description="Created with ComfyUI",
                tags=("portrait", "SFW"),
                nsfw=True,
                metadata={"prompt": "a portrait", "civitaiResources": [{"modelVersionId": 99}]},
            )

        self.assertEqual(result.post_id, 321)
        self.assertEqual(result.post_url, "https://civitai.red/posts/321")
        urls = [call[2] if call[0] == "json" else call[1] for call in transport.calls]
        self.assertEqual(urls, [
            "https://civitai.com/api/v1/image-upload",
            "https://uploads.example/object",
            "https://civitai.com/api/trpc/post.create",
            "https://civitai.com/api/trpc/post.addImage",
            "https://civitai.com/api/trpc/post.addTag",
            "https://civitai.com/api/trpc/post.addTag",
            "https://civitai.com/api/trpc/post.update",
            "https://civitai.com/api/trpc/post.update",
        ])
        attach = next(
            call[3]
            for call in transport.calls
            if call[0] == "json" and call[2].endswith("post.addImage")
        )
        self.assertEqual(attach["json"]["meta"]["prompt"], "a portrait")
        self.assertEqual(attach["json"]["meta"]["civitaiResources"][0]["modelVersionId"], 99)

    async def test_workflow_metadata_is_attached_to_every_uploaded_media_item(self):
        transport = FakeTransport()
        client = CivitAIClient("secret-token", transport=transport)
        linked_metadata = {
            "prompt": "a video",
            "civitaiResources": [{"modelVersionId": 3295293}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "image.png"
            video = Path(tmp) / "video.mp4"
            image.write_bytes(b"png")
            video.write_bytes(b"mp4")
            await client.publish_post(
                media=[
                    MediaUpload(image, "image/png", 640, 480),
                    MediaUpload(video, "video/mp4", 640, 480, media_type="video"),
                ],
                title="",
                description="",
                tags=(),
                nsfw=False,
                metadata=linked_metadata,
            )

        attachments = [
            call[3]["json"]
            for call in transport.calls
            if call[0] == "json" and call[2].endswith("post.addImage")
        ]
        self.assertEqual(len(attachments), 2)
        self.assertEqual([item["index"] for item in attachments], [0, 1])
        self.assertEqual([item["meta"] for item in attachments], [linked_metadata, linked_metadata])

    async def test_failure_after_post_creation_reports_sanitized_partial_post(self):
        transport = FakeTransport()
        transport.fail_on = "post.addImage"
        client = CivitAIClient("secret-token", transport=transport)
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "image.png"
            media.write_bytes(b"png")
            with self.assertRaises(PartialPostError) as caught:
                await client.publish_post(
                    media=[MediaUpload(media, "image/png", 1, 1)],
                    title="",
                    description="",
                    tags=(),
                    nsfw=False,
                    metadata={"prompt": "x"},
                )
        message = str(caught.exception)
        self.assertIn("https://civitai.com/posts/321", message)
        self.assertNotIn("secret-token", message)

    async def test_nsfw_partial_post_uses_red_recovery_url(self):
        transport = FakeTransport()
        transport.fail_on = "post.addImage"
        client = CivitAIClient("secret-token", transport=transport)
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "image.png"
            media.write_bytes(b"png")
            with self.assertRaises(PartialPostError) as caught:
                await client.publish_post(
                    media=[MediaUpload(media, "image/png", 1, 1)],
                    title="",
                    description="",
                    tags=(),
                    nsfw=True,
                    metadata={"prompt": "x"},
                )

        self.assertEqual(caught.exception.post_url, "https://civitai.red/posts/321")
        self.assertNotIn("secret-token", str(caught.exception))

    async def test_nsfw_custom_origin_keeps_injected_post_origin(self):
        transport = FakeTransport()
        client = CivitAIClient(
            "secret-token",
            transport=transport,
            origin="http://127.0.0.1:8765/",
        )
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "image.png"
            media.write_bytes(b"png")
            result = await client.publish_post(
                media=[MediaUpload(media, "image/png", 1, 1)],
                title="",
                description="",
                tags=(),
                nsfw=True,
                metadata={"prompt": "x"},
            )

        self.assertEqual(result.post_url, "http://127.0.0.1:8765/posts/321")


if __name__ == "__main__":
    unittest.main()
