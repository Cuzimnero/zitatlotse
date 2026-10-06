"""Check startup identity, OS locks and recovery without loading ML models."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import launcher


class LauncherTests(unittest.TestCase):
    def test_health_accepts_only_this_service(self):
        for value, expected in [
            ({"ok": True, "service": "zitatlotse"}, True),
            ({"ok": True, "version": "0.26.2", "models_cached": False}, True),
            ({"ok": True}, False), ({"ok": False, "service": "zitatlotse"}, False),
            ([], False),
        ]:
            with self.subTest(value=value), patch.object(launcher, "urlopen", return_value=io.StringIO(json.dumps(value))):
                self.assertEqual(launcher.service_healthy(), expected)
        with patch.object(launcher, "urlopen", side_effect=OSError("offline")):
            self.assertFalse(launcher.service_healthy())

    def test_os_lock_releases_and_stale_file_does_not_block(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "service.lock"
            first = launcher.instance_lock(path)
            self.assertIsNotNone(first)
            try:
                self.assertIsNone(launcher.instance_lock(path))
            finally:
                first.close()
            self.assertTrue(path.exists())
            second = launcher.instance_lock(path)
            self.assertIsNotNone(second)
            second.close()

    def test_duplicate_supervisor_never_spawns_worker(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, "DATA", Path(directory)):
            lock = launcher.instance_lock(Path(directory) / "service.lock")
            try:
                with patch.object(launcher.subprocess, "Popen") as spawn:
                    self.assertEqual(launcher.supervise(), 0)
                    spawn.assert_not_called()
            finally:
                lock.close()

    def test_existing_service_is_reused(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, "DATA", Path(directory)), \
             patch.object(launcher, "service_healthy", return_value=True), patch.object(launcher.subprocess, "Popen") as spawn:
            self.assertEqual(launcher.supervise(), 0)
            spawn.assert_not_called()

    def test_worker_crash_retries_and_records_new_worker(self):
        first = Mock(pid=101)
        first.wait.return_value = 1
        second = Mock(pid=102)
        second.wait.side_effect = RuntimeError("stop test")
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher, "DATA", Path(directory)), \
             patch.object(launcher, "service_healthy", return_value=False), \
             patch.object(launcher.subprocess, "Popen", side_effect=[first, second]) as spawn, \
             patch.object(launcher.time, "sleep") as sleep, patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "stop test"):
                launcher.supervise()
            self.assertEqual(spawn.call_count, 2)
            sleep.assert_called_once_with(2)
            self.assertEqual(spawn.call_args.args[0][-2:], [str(launcher.ROOT / "launcher.py"), "--worker"])
            self.assertEqual(spawn.call_args.kwargs["cwd"], launcher.ROOT)
            state = json.loads((Path(directory) / "supervisor.json").read_text(encoding="utf-8"))
            self.assertEqual(state["worker_pid"], 102)
            lock = launcher.instance_lock(Path(directory) / "service.lock")
            self.assertIsNotNone(lock)
            lock.close()


if __name__ == "__main__":
    unittest.main()
