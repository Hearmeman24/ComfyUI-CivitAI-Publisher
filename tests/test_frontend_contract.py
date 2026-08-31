import re
import unittest
from pathlib import Path


class FrontendContractTests(unittest.TestCase):
    def test_extension_targets_an_embedded_node_review_surface(self):
        web_root = Path(__file__).resolve().parents[1] / "web"
        source = (web_root / "civitai_publisher.js").read_text()
        styles = (web_root / "civitai_publisher.css").read_text()
        self.assertIn('api.addEventListener("civitai_publisher.review"', source)
        self.assertIn('node.addDOMWidget("civitai_publisher_review"', source)
        self.assertIn('document.createElement("canvas")', source)
        self.assertIn('document.createElement("video")', source)
        self.assertIn('decide(node, "reject")', source)
        self.assertNotIn("Rejecting…", source)
        self.assertIn("/civitai_publisher/pending", source)
        self.assertIn('api.addEventListener("civitai_publisher.closed"', source)
        self.assertNotIn('document.createElement("dialog")', source)
        self.assertNotIn("showModal()", source)
        self.assertNotIn("CIVITAI_TOKEN", source)
        self.assertNotIn("CIVITAI_API_KEY", source)
        self.assertIn("const REVIEW_HEIGHT = 700;", source)
        self.assertIn("max-width: 100%;", styles)
        self.assertIn("flex-wrap: wrap;", styles)
        self.assertRegex(
            styles,
            re.compile(r"\.civitai-publisher-node-review\s*\{[^}]*height:\s*100%;", re.DOTALL),
        )


if __name__ == "__main__":
    unittest.main()
