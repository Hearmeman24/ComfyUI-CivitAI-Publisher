from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aiohttp import web

from civitai_publisher.client import CivitAIClient, MediaUpload
from civitai_publisher.workflow import HashedResource


class HTTPBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls: list[dict] = []
        app = web.Application()
        app.router.add_get("/api/v1/model-versions/by-hash/{sha256}", self._resolve)
        app.router.add_post("/api/v1/image-upload", self._presign)
        app.router.add_put("/storage/{upload_id}", self._put)
        app.router.add_post("/api/trpc/{operation}", self._trpc)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await self.site.start()
        socket = self.site._server.sockets[0]
        self.origin = f"http://127.0.0.1:{socket.getsockname()[1]}"

    async def asyncTearDown(self):
        await self.runner.cleanup()

    async def _record(self, request, body=None):
        self.calls.append({
            "method": request.method,
            "path": request.path,
            "authorization": request.headers.get("Authorization"),
            "content_type": request.headers.get("Content-Type"),
            "body": body,
        })

    async def _resolve(self, request):
        await self._record(request)
        return web.json_response({
            "id": 77,
            "modelId": 66,
            "name": "v1",
            "model": {"name": "Local style", "type": "LORA"},
        })

    async def _presign(self, request):
        body = await request.json()
        await self._record(request, body)
        return web.json_response({"uploadURL": f"{self.origin}/storage/upload-1", "id": "upload-1"})

    async def _put(self, request):
        body = await request.read()
        await self._record(request, body)
        return web.Response(status=204)

    async def _trpc(self, request):
        body = await request.json()
        await self._record(request, body)
        if request.match_info["operation"] == "post.create":
            return web.json_response({"result": {"data": {"json": {"id": 123}}}})
        return web.json_response({"ok": True})

    async def test_real_http_transport_resolves_then_publishes_reviewed_payload(self):
        client = CivitAIClient("test-token", origin=self.origin)
        resource = HashedResource(
            filename="style.safetensors",
            category="loras",
            path=Path("/models/loras/style.safetensors"),
            resource_type="lora",
            sha256="a" * 64,
            strengths=(0.8,),
        )
        resolved = await client.resolve_resources([resource])

        with tempfile.TemporaryDirectory() as tmp:
            media_path = Path(tmp) / "reviewed.png"
            media_path.write_bytes(b"reviewed-media")
            result = await client.publish_post(
                media=(MediaUpload(media_path, "image/png", 32, 16),),
                title="Reviewed title",
                description="Created in test",
                tags=("portrait",),
                nsfw=False,
                metadata={
                    "prompt": "Reviewed prompt",
                    "civitaiResources": [{"modelVersionId": resolved[0].model_version_id}],
                },
            )

        self.assertTrue(resolved[0].resolved)
        self.assertEqual(resolved[0].name, "Local style")
        self.assertEqual(result.post_url, f"{self.origin}/posts/123")
        self.assertEqual([call["path"] for call in self.calls], [
            f"/api/v1/model-versions/by-hash/{'a' * 64}",
            "/api/v1/image-upload",
            "/storage/upload-1",
            "/api/trpc/post.create",
            "/api/trpc/post.addImage",
            "/api/trpc/post.addTag",
            "/api/trpc/post.update",
        ])
        self.assertTrue(all(
            call["authorization"] == "Bearer test-token"
            for call in self.calls
            if call["path"].startswith("/api/")
        ))
        upload = next(call for call in self.calls if call["path"] == "/storage/upload-1")
        self.assertIsNone(upload["authorization"])
        self.assertEqual(upload["body"], b"reviewed-media")
        attach = next(call for call in self.calls if call["path"] == "/api/trpc/post.addImage")
        self.assertEqual(attach["body"]["json"]["meta"]["prompt"], "Reviewed prompt")
        self.assertEqual(attach["body"]["json"]["meta"]["civitaiResources"], [{"modelVersionId": 77}])


if __name__ == "__main__":
    unittest.main()
