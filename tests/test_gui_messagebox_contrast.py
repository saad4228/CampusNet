"""Regression tests for the compact, theme-independent CampusNet message dialog."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QMessageBox

from campusnet.gui import CampusMessageDialog, MESSAGE_DIALOG_STYLE, _create_message_dialog


class MessageDialogLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_information_dialog_is_compact_and_explicitly_styled(self):
        dialog = _create_message_dialog(
            None,
            QMessageBox.Icon.Information,
            "Settings saved",
            "Your settings have been saved. Pause and start monitoring to apply changes to the current session.",
        )
        try:
            self.assertIsInstance(dialog, QDialog)
            self.assertEqual(dialog.objectName(), "campusMessageDialog")
            self.assertEqual(dialog.width(), 460)
            self.assertIn("QDialog#campusMessageDialog", dialog.styleSheet())
            self.assertIn("color: #101828", dialog.styleSheet())
            self.assertIn("QPushButton#dialogPrimaryButton", dialog.styleSheet())
            self.assertIn("QPushButton#dialogSecondaryButton", dialog.styleSheet())
            self.assertEqual(dialog.findChild(QLabel, "messageDialogTitle").text(), "Settings saved")
            self.assertIn("Pause and start monitoring", dialog.findChild(QLabel, "messageDialogBody").text())
            ok_button = dialog.button_box.button(QDialogButtonBox.StandardButton.Ok)
            self.assertIsNotNone(ok_button)
            self.assertEqual(ok_button.objectName(), "dialogPrimaryButton")
        finally:
            dialog.close()

    def test_question_dialog_has_no_as_default_and_yes_as_primary_action(self):
        dialog = CampusMessageDialog(
            None,
            QMessageBox.Icon.Question,
            "Exit CampusNet?",
            "Exit CampusNet and stop background monitoring?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        try:
            yes_button = dialog.button_box.button(QDialogButtonBox.StandardButton.Yes)
            no_button = dialog.button_box.button(QDialogButtonBox.StandardButton.No)
            self.assertIsNotNone(yes_button)
            self.assertIsNotNone(no_button)
            self.assertEqual(yes_button.objectName(), "dialogPrimaryButton")
            self.assertEqual(no_button.objectName(), "dialogSecondaryButton")
            self.assertTrue(no_button.isDefault())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
