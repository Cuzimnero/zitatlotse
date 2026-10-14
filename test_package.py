"""Regression checks for the manifest that Zotero reads before installing an XPI."""
import copy
import json
import unittest
from pathlib import Path

from package import validate_manifest

ROOT = Path(__file__).resolve().parent


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "plugin/manifest.json").read_text(encoding="utf-8"))

    def test_current_manifest_and_update_feed(self):
        validate_manifest(self.manifest)
        target = self.manifest["applications"]["zotero"]
        self.assertEqual(target["update_url"],
                         "https://raw.githubusercontent.com/Cuzimnero/zitatlotse/main/updates.json")
        feed = json.loads((ROOT / "updates.json").read_text(encoding="utf-8"))
        self.assertIsInstance(feed["addons"][target["id"]]["updates"], list)

    def test_missing_installation_fields_are_rejected(self):
        # Removing update_url caused the published 0.27.0 installation failure.
        for field in ("id", "update_url", "strict_min_version", "strict_max_version"):
            with self.subTest(field=field):
                manifest = copy.deepcopy(self.manifest)
                del manifest["applications"]["zotero"][field]
                with self.assertRaisesRegex(ValueError, field):
                    validate_manifest(manifest)

    def test_placeholder_and_insecure_update_urls_are_rejected(self):
        for url in ("", "http://github.com/updates.json", "https://example.com/updates.json"):
            with self.subTest(url=url):
                self.manifest["applications"]["zotero"]["update_url"] = url
                with self.assertRaisesRegex(ValueError, "update_url"):
                    validate_manifest(self.manifest)

    def test_invalid_minimum_version_is_rejected(self):
        self.manifest["applications"]["zotero"]["strict_min_version"] = "10.*"
        with self.assertRaisesRegex(ValueError, "strict_min_version"):
            validate_manifest(self.manifest)


if __name__ == "__main__":
    unittest.main()
