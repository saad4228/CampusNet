"""Regression test for first-time portal URL setup guidance."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from campusnet.gui import SetupDialog


class PortalUrlHintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hint_explains_what_to_copy_and_remove(self):
        dialog = SetupDialog()
        try:
            hint = dialog.portal_url_hint.text()
            self.assertIn("copy its address from the browser bar", hint)
            self.assertIn("Authentication Keepalive", hint)
            self.assertIn("remove the ? and everything after it", hint)
            self.assertIn("your college's address will differ", hint)
            self.assertTrue(dialog.portal_url_hint.wordWrap())
            self.assertEqual(dialog.portal_url_hint.objectName(), "portalUrlHint")
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
