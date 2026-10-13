from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StartupOptimizationTests(unittest.TestCase):
    def test_monitor_is_not_imported_eagerly_by_gui_module(self):
        source = (ROOT / "src" / "campusnet" / "gui.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        eager_monitor_imports = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "monitor":
                eager_monitor_imports.append(node.lineno)
        self.assertEqual(eager_monitor_imports, [])
        self.assertIn("from .monitor import run_app", source)
        self.assertIn("replace(self.config, headless=True)", source)

    def test_windows_build_uses_headless_shell_only(self):
        source = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("playwright install chromium --only-shell", source)

    def test_windows_build_does_not_collect_all_of_pyside6(self):
        source = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertNotIn("--collect-all PySide6 `", source)
        self.assertIn("--onedir", source)

    def test_dependency_uses_essentials_package(self):
        source = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("PySide6-Essentials>=6.7,<7", source)
        self.assertNotIn('"PySide6>=6.7,<7"', source)

    def test_build_detects_inno_setup_7(self):
        source = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("Inno Setup 7\\ISCC.exe", source)


if __name__ == "__main__":
    unittest.main()
