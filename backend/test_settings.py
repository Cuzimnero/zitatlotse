import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import settings


class FakeKeyring:
    def __init__(self):
        self.keys = {}

    def set_password(self, service, account, key):
        self.keys[(service, account)] = key

    def get_password(self, service, account):
        return self.keys.get((service, account))


class SettingsTest(unittest.TestCase):
    def test_activity_display_persists_across_provider_changes(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(settings, "DATA_DIR", Path(folder)), \
                patch.object(settings, "SETTINGS_PATH", Path(folder) / "settings.json"), \
                patch.object(settings, "_keyring", return_value=FakeKeyring()):
            self.assertTrue(settings.get_settings()["show_ai_activity"])
            result = settings.save_settings({"show_ai_activity":False})
            self.assertFalse(result["show_ai_activity"])
            result = settings.save_settings({"provider":"ollama","model":"test"})
            self.assertFalse(result["show_ai_activity"])
            result = settings.save_settings({"show_ai_activity":True})
            self.assertEqual(result["model"], "test")
            self.assertTrue(result["show_ai_activity"])
            with self.assertRaises(ValueError): settings.save_settings({"show_ai_activity":"false"})

    def test_agent_options_persist_without_overwriting_provider_and_validate_limits(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(settings, "DATA_DIR", Path(folder)), \
                patch.object(settings, "SETTINGS_PATH", Path(folder) / "settings.json"), \
                patch.object(settings, "_keyring", return_value=FakeKeyring()):
            result = settings.save_settings({"provider":"ollama", "model":"local-model"})
            self.assertTrue(result["agentic_enabled"])
            self.assertEqual(result["agentic_max_steps"], 3)
            result = settings.save_settings({"agentic_enabled":False, "agentic_max_steps":2})
            self.assertEqual(result["provider"], "ollama")
            self.assertEqual(result["model"], "local-model")
            self.assertFalse(result["agentic_enabled"])
            result = settings.save_settings({"provider":"deepseek", "model":"test"})
            self.assertFalse(result["agentic_enabled"])
            self.assertEqual(result["agentic_max_steps"], 2)
            for changes in ({"agentic_max_steps":7}, {"agentic_max_steps":True}, {"agentic_enabled":"false"}):
                with self.assertRaises(ValueError): settings.save_settings(changes)

    def test_key_is_kept_out_of_settings_file_and_response(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = FakeKeyring()
            with patch.object(settings, "DATA_DIR", Path(folder)), \
                    patch.object(settings, "SETTINGS_PATH", Path(folder) / "settings.json"), \
                    patch.object(settings, "_keyring", return_value=fake):
                result = settings.save_settings({"provider": "openai", "model": "test-model",
                                                 "api_key": "secret-123"})
                self.assertTrue(result["has_key"])
                self.assertNotIn("secret-123", json.dumps(result))
                self.assertNotIn("secret-123", (Path(folder) / "settings.json").read_text())
                self.assertEqual(settings.get_key("openai"), "secret-123")

    def test_ollama_rejects_remote_endpoint(self):
        with self.assertRaises(ValueError):
            settings.save_settings({"provider": "ollama", "model": "local-model",
                                    "ollama_url": "https://example.com:11434"})


if __name__ == "__main__":
    unittest.main()
