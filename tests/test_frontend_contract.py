import unittest
from pathlib import Path


class FrontendContractTests(unittest.TestCase):
    def test_extension_listens_for_review_and_uses_native_modal(self):
        source = (Path(__file__).resolve().parents[1] / "web" / "civitai_publisher.js").read_text()
        self.assertIn('api.addEventListener("civitai_publisher.review"', source)
        self.assertIn("dialog.showModal()", source)
        self.assertIn('decision: "reject"', source)
        self.assertIn("/civitai_publisher/pending", source)
        self.assertIn('api.addEventListener("civitai_publisher.closed"', source)
        self.assertNotIn("CIVITAI_TOKEN", source)
        self.assertNotIn("CIVITAI_API_KEY", source)


if __name__ == "__main__":
    unittest.main()
