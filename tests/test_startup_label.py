"""Checks the default-on startup preference and consistent UI label."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StartupLabelTests(unittest.TestCase):
    def test_both_checkboxes_use_launch_at_startup_label(self):
        source = (ROOT / "src" / "campusnet" / "gui.py").read_text(encoding="utf-8")
        self.assertEqual(source.count('QCheckBox("Launch at startup")'), 2)
        self.assertNotIn("Launch at sign-in", source)
        self.assertNotIn("Start CampusNet automatically when I sign in", source)

    def test_setup_checkbox_defaults_to_checked(self):
        source = (ROOT / "src" / "campusnet" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("config.launch_at_startup if config is not None else True", source)
        self.assertIn("self.startup_checkbox.setChecked(self.config.launch_at_startup)", source)
        self.assertIn("Starts CampusNet automatically when you sign in to this computer.", source)


if __name__ == "__main__":
    unittest.main()
