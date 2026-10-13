"""Regression test: SetupDialog's input palette requires Qt color types in gui.py."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GuiRequiredImportsTests(unittest.TestCase):
    def test_setup_dialog_palette_types_are_imported(self):
        source = (ROOT / "src" / "campusnet" / "gui.py").read_text(encoding="utf-8")
        qt_gui_imports = re.search(r"from PySide6\.QtGui import ([^\n]+)", source)
        self.assertIsNotNone(qt_gui_imports, "Expected a PySide6.QtGui import line")
        imported_names = {name.strip() for name in qt_gui_imports.group(1).split(",")}
        self.assertIn("QColor", imported_names)
        self.assertIn("QPalette", imported_names)

    def test_settings_button_is_connected_to_settings_handler(self):
        source = (ROOT / "src" / "campusnet" / "gui.py").read_text(encoding="utf-8")
        self.assertIn('self.settings_button.clicked.connect(self.edit_settings)', source)
        # edit_settings reports whether it saved, so start_monitoring can resume
        # after first-run setup completes.
        self.assertIn("def edit_settings(self) -> bool:", source)


if __name__ == "__main__":
    unittest.main()
