"""Regression tests for setup-dialog input readability across OS themes."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from campusnet import gui as gui_module
from campusnet.credentials import CredentialError
from campusnet.gui import SetupDialog


class SetupInputContrastTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # SetupDialog reads the saved username to prefill the field. Stub that so
        # the test never touches the real OS credential store, and behaves the
        # same on a machine with saved credentials as on a clean one.
        def no_saved_credentials():
            raise CredentialError("No saved credentials.")

        original = gui_module.load_credentials
        gui_module.load_credentials = no_saved_credentials
        self.addCleanup(setattr, gui_module, "load_credentials", original)

    def test_setup_fields_use_high_contrast_palette(self):
        dialog = SetupDialog()
        try:
            for field in (dialog.portal_input, dialog.username_input, dialog.password_input):
                with self.subTest(field=field):
                    palette = field.palette()
                    self.assertEqual(palette.color(QPalette.ColorRole.Text).name(), "#101828")
                    self.assertEqual(palette.color(QPalette.ColorRole.PlaceholderText).name(), "#667085")
                    self.assertEqual(palette.color(QPalette.ColorRole.Base).name(), "#ffffff")
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
