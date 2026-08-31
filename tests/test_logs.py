from __future__ import annotations

import logging
import unittest

from civitai_publisher import logs


class LoggingTests(unittest.TestCase):
    def test_publisher_logger_explicitly_enables_info_events(self):
        self.assertEqual(logs.logger.level, logging.INFO)

    def test_structured_line_and_secret_redaction(self):
        line = logs.format_event(
            "resolve",
            resources=4,
            cache_hits=3,
            elapsed=1.23456,
            civitai_token="secret-token",
            generation_prompt="private prompt",
            upload_url="https://signed.example/?secret=yes",
        )

        self.assertIn("[CivitAIPublisher] event=resolve", line)
        self.assertIn("resources=4", line)
        self.assertIn("elapsed=1.235", line)
        self.assertNotIn("secret-token", line)
        self.assertNotIn("private prompt", line)
        self.assertNotIn("signed.example", line)
        self.assertEqual(line.count("=***"), 3)

    def test_boolean_presence_fields_remain_useful(self):
        line = logs.format_event(
            "execution_started",
            has_generation_prompt=True,
            has_prompt_override=False,
        )

        self.assertIn("has_generation_prompt=true", line)
        self.assertIn("has_prompt_override=false", line)

    def test_timed_logs_failure_without_exception_message(self):
        with self.assertLogs(logs.LOGGER_NAME, level=logging.WARNING) as captured:
            with self.assertRaises(ValueError):
                with logs.timed("hash", model_path="/private/model.safetensors"):
                    raise ValueError("contains sensitive detail")

        line = captured.output[0]
        self.assertIn("event=hash", line)
        self.assertIn("model_path=***", line)
        self.assertIn("error=ValueError", line)
        self.assertNotIn("sensitive detail", line)


if __name__ == "__main__":
    unittest.main()
