from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from civitai_publisher.resolution_cache import ResolutionCache


class ResolutionCacheTests(unittest.TestCase):
    def test_positive_and_not_found_entries_use_separate_ttls(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            cache = ResolutionCache(
                Path(tmp) / "resources.json",
                clock=lambda: now[0],
                positive_ttl_seconds=100,
                missing_ttl_seconds=10,
            )
            cache.store_resolved("a" * 64, {
                "id": 20,
                "modelId": 10,
                "name": "Version",
                "model": {"name": "Model", "type": "Checkpoint"},
            })
            cache.store_not_found("b" * 64)

            now[0] = 1011.0

            self.assertTrue(cache.get("a" * 64).fresh)
            self.assertIsNone(cache.get("b" * 64))

    def test_stale_success_is_available_only_when_requested(self):
        now = [1000.0]
        with tempfile.TemporaryDirectory() as tmp:
            cache = ResolutionCache(
                Path(tmp) / "resources.json",
                clock=lambda: now[0],
                positive_ttl_seconds=10,
            )
            cache.store_resolved("a" * 64, {
                "id": 20,
                "modelId": 10,
                "name": "Version",
                "model": {"name": "Model", "type": "Checkpoint"},
            })
            now[0] = 1011.0

            self.assertIsNone(cache.get("a" * 64))
            stale = cache.get("a" * 64, allow_stale_success=True)

            self.assertIsNotNone(stale)
            self.assertFalse(stale.fresh)
            self.assertEqual(stale.payload["id"], 20)

    def test_cache_write_failure_keeps_in_memory_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = ResolutionCache(Path(tmp) / "resources.json")
            with mock.patch(
                "civitai_publisher.resolution_cache.os.replace",
                side_effect=OSError("read-only"),
            ):
                cache.store_not_found("b" * 64)

            hit = cache.get("b" * 64)

            self.assertIsNotNone(hit)
            self.assertEqual(hit.state, "not_found")


if __name__ == "__main__":
    unittest.main()
