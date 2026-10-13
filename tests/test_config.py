import tempfile
import unittest
from pathlib import Path

from campusnet.config import AppConfig, load_config, write_config


class ConfigTests(unittest.TestCase):
    def test_write_and_load_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            original = AppConfig(portal_url="https://portal.example.edu/login")
            write_config(original, path)
            loaded = load_config(path)
            self.assertEqual(loaded.portal_url, original.portal_url)
            self.assertEqual(loaded.keepalive_path, "/keepalive")
            self.assertEqual(loaded.keepalive_success_text, "Authentication Keepalive")
            self.assertTrue(loaded.headless)
            self.assertFalse(loaded.ignore_portal_tls_errors)
            self.assertTrue(loaded.launch_at_startup)
            self.assertEqual(loaded.connectivity_url, "http://connectivitycheck.gstatic.com/generate_204")

    def test_legacy_config_defaults_launch_at_startup_to_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text('portal_url = "https://portal.example.edu/login"\n', encoding="utf-8")
            loaded = load_config(path)
            self.assertTrue(loaded.launch_at_startup)

    def test_launch_at_startup_can_be_disabled_and_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            original = AppConfig(
                portal_url="https://portal.example.edu/login",
                launch_at_startup=False,
            )
            write_config(original, path)
            loaded = load_config(path)
            self.assertFalse(loaded.launch_at_startup)
            self.assertIn("launch_at_startup = false", path.read_text(encoding="utf-8"))

    def test_invalid_launch_at_startup_setting_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text(
                'portal_url = "https://portal.example.edu/login"\nlaunch_at_startup = "yes"\n',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_config(path)

    def test_rejects_invalid_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text('portal_url = "file:///tmp/not-a-portal"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_rejects_embedded_url_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text('portal_url = "https://student:secret@example.edu/login"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_rejects_portal_url_with_temporary_query_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text('portal_url = "https://192.168.55.253:1003/fgtauth?temporarytoken"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_rejects_zero_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text(
                'portal_url = "https://portal.example.edu/login"\ncheck_interval_seconds = 0\n',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_config(path)

    def test_offline_check_interval_defaults_to_three_seconds(self):
        self.assertEqual(AppConfig(portal_url="https://portal.example.edu/login").offline_check_interval_seconds, 3)

    def test_offline_check_interval_round_trips(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            original = AppConfig(
                portal_url="https://portal.example.edu/login",
                offline_check_interval_seconds=5,
            )
            write_config(original, path)
            self.assertIn("offline_check_interval_seconds = 5", path.read_text(encoding="utf-8"))
            self.assertEqual(load_config(path).offline_check_interval_seconds, 5)

    def test_legacy_config_without_offline_interval_still_loads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text(
                """portal_url = "https://portal.example.edu/login"
check_interval_seconds = 30
""",
                encoding="utf-8",
            )
            loaded = load_config(path)
            self.assertEqual(loaded.offline_check_interval_seconds, 3)
            self.assertEqual(loaded.check_interval_seconds, 30)

    def test_rejects_invalid_offline_check_interval(self):
        for bad in ("0", "-5", "true", '"3"'):
            with self.subTest(value=bad), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "config.toml"
                path.write_text(
                    f"""portal_url = "https://portal.example.edu/login"
offline_check_interval_seconds = {bad}
""",
                    encoding="utf-8",
                )
                with self.assertRaises(ValueError):
                    load_config(path)


if __name__ == "__main__":
    unittest.main()
