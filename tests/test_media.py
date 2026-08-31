from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from civitai_publisher.media import _save_video


class FakeVideo:
    def __init__(self, source, *, container="mp4", trim=(0.0, 0.0)):
        self.source = source
        self.container = container
        self.trim = trim
        self.saved_to = []

    def get_dimensions(self):
        return 1920, 1080

    def get_stream_source(self):
        return self.source

    def get_container_format(self):
        return self.container

    def get_active_trim_window(self):
        return self.trim

    def save_to(self, path, **kwargs):
        self.saved_to.append((Path(path), kwargs))
        Path(path).write_bytes(b"transcoded")


class VideoMaterializationTests(unittest.TestCase):
    def test_untrimmed_mp4_stream_is_copied_without_reencoding(self):
        video = FakeVideo(io.BytesIO(b"original"), container="mov,mp4,m4a,3gp,3g2,mj2")
        with tempfile.TemporaryDirectory() as tmp:
            upload = _save_video(video, Path(tmp))
            self.assertEqual(upload.path.read_bytes(), b"original")
        self.assertEqual(video.saved_to, [])
        self.assertEqual(upload.content_type, "video/mp4")

    def test_trimmed_or_mov_video_is_materialized_as_mp4(self):
        cases = [
            FakeVideo(io.BytesIO(b"source"), container="mp4", trim=(1.0, 2.0)),
            FakeVideo(io.BytesIO(b"source"), container="mov"),
        ]
        for video in cases:
            with self.subTest(container=video.container, trim=video.trim):
                with tempfile.TemporaryDirectory() as tmp:
                    upload = _save_video(video, Path(tmp))
                    self.assertEqual(upload.path.suffix, ".mp4")
                    self.assertEqual(upload.path.read_bytes(), b"transcoded")
                self.assertEqual(len(video.saved_to), 1)


if __name__ == "__main__":
    unittest.main()
