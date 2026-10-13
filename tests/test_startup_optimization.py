from __future__ import annotations

import ast
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_def(module_path: Path, name: str, cls: str | None = None) -> ast.FunctionDef:
    """Return the AST node for a module-level function or for a method of a class."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    scope = tree.body
    if cls is not None:
        matches = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls]
        assert matches, f"class {cls} not found in {module_path.name}"
        scope = matches[0].body
    for node in scope:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found in {module_path.name}")


def _call_sequence(node: ast.AST) -> list[str]:
    """Names of the calls inside a function, in source order."""
    found = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name:
                found.append((child.lineno, child.col_offset, name))
    return [name for _, _, name in sorted(found)]


def _function_level_imports(node: ast.AST) -> set[str]:
    return {
        alias.name
        for child in ast.walk(node)
        if isinstance(child, ast.Import)
        for alias in child.names
    }


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


class LazyImportTests(unittest.TestCase):
    """keyring and asyncio must stay off the path that runs before the window."""

    CREDENTIALS = ROOT / "src" / "campusnet" / "credentials.py"
    GUI = ROOT / "src" / "campusnet" / "gui.py"

    def test_keyring_is_not_imported_at_module_scope(self):
        tree = ast.parse(self.CREDENTIALS.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [alias.name for alias in node.names]
                if isinstance(node, ast.ImportFrom):
                    names.append(node.module or "")
                for name in names:
                    self.assertNotEqual(
                        (name or "").split(".")[0],
                        "keyring",
                        "credentials.py must not import keyring at module scope",
                    )

    def test_every_credential_function_imports_keyring(self):
        for name in ("save_credentials", "load_credentials", "delete_credentials"):
            with self.subTest(function=name):
                node = _function_def(self.CREDENTIALS, name)
                self.assertIn("keyring", _function_level_imports(node))

    def test_delete_credentials_imports_keyring_errors(self):
        node = _function_def(self.CREDENTIALS, "delete_credentials")
        self.assertIn("keyring.errors", _function_level_imports(node))

    def test_asyncio_is_not_imported_at_module_scope_in_gui(self):
        tree = ast.parse(self.GUI.read_text(encoding="utf-8"))
        module_imports = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertNotIn("asyncio", module_imports)

    def test_worker_run_imports_asyncio(self):
        node = _function_def(self.GUI, "run", cls="BackendWorker")
        self.assertIn("asyncio", _function_level_imports(node))


class StartupSequenceTests(unittest.TestCase):
    """main() must show the window before touching the credential store or the registry."""

    GUI = ROOT / "src" / "campusnet" / "gui.py"

    def setUp(self):
        self.calls = _call_sequence(_function_def(self.GUI, "main"))

    def test_main_does_not_probe_the_credential_store(self):
        self.assertNotIn("load_credentials", self.calls)

    def test_main_still_loads_config_before_the_window(self):
        self.assertIn("load_config", self.calls)
        self.assertLess(self.calls.index("load_config"), self.calls.index("show"))

    def test_autostart_is_reconciled_after_the_window_is_shown(self):
        shown = self.calls.index("show")
        for name in ("is_enabled", "set_enabled"):
            with self.subTest(call=name):
                self.assertIn(name, self.calls)
                self.assertGreater(self.calls.index(name), shown)

    def test_single_instance_is_claimed_before_any_startup_work(self):
        self.assertIn("_claim_single_instance", self.calls)
        self.assertLess(
            self.calls.index("_claim_single_instance"),
            self.calls.index("load_config"),
            "a duplicate launch must exit before doing startup work",
        )
        self.assertLess(self.calls.index("_claim_single_instance"), self.calls.index("show"))

    def test_qtnetwork_is_not_imported_at_module_scope(self):
        tree = ast.parse(self.GUI.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                self.assertNotEqual(
                    node.module,
                    "PySide6.QtNetwork",
                    "QtNetwork belongs inside _claim_single_instance, off the import path",
                )

    def test_first_run_setup_dialog_still_gates_on_a_missing_config(self):
        source = self.GUI.read_text(encoding="utf-8")
        self.assertIn("except (FileNotFoundError, ValueError):", source)
        self.assertIn("dialog = SetupDialog()", source)
        self.assertIn("config = dialog.saved_config", source)

    def test_missing_credentials_still_opens_setup_and_retries_monitoring(self):
        node = _function_def(self.GUI, "start_monitoring", cls="MainWindow")
        calls = _call_sequence(node)
        self.assertIn("load_credentials", calls)
        self.assertIn("edit_settings", calls)
        self.assertIn("start_monitoring", calls, "setup must be followed by one retry")

    def test_edit_settings_reports_whether_it_saved(self):
        node = _function_def(self.GUI, "edit_settings", cls="MainWindow")
        returns = [
            child.value.value
            for child in ast.walk(node)
            if isinstance(child, ast.Return) and isinstance(child.value, ast.Constant)
        ]
        self.assertIn(True, returns)
        self.assertIn(False, returns)


class IconAssetTests(unittest.TestCase):
    ASSETS = ROOT / "src" / "campusnet" / "assets"

    def test_small_icon_exists_and_is_128px(self):
        path = self.ASSETS / "campusnet-app-icon-128.png"
        self.assertTrue(path.is_file(), "campusnet-app-icon-128.png is missing")
        data = path.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), (128, 128))

    def test_full_size_and_installer_icons_are_preserved(self):
        self.assertTrue((self.ASSETS / "campusnet-app-icon.png").is_file())
        self.assertTrue((self.ASSETS / "campusnet.ico").is_file())
        self.assertTrue((self.ASSETS / "campusnet.icns").is_file())

    def test_gui_prefers_the_small_icon_with_fallbacks(self):
        source = (ROOT / "src" / "campusnet" / "gui.py").read_text(encoding="utf-8")
        self.assertIn('SMALL_ICON_PATH = ASSET_DIR / "campusnet-app-icon-128.png"', source)
        self.assertIn("for path in (SMALL_ICON_PATH, APP_ICON_PATH, MARK_ICON_PATH):", source)


class PackagingTests(unittest.TestCase):
    def test_installer_removes_the_previous_bundle_before_copying(self):
        source = (ROOT / "CampusNet.iss").read_text(encoding="utf-8")
        self.assertIn("[InstallDelete]", source)
        self.assertIn(r'Type: filesandordirs; Name: "{app}\_internal"', source)
        self.assertLess(
            source.index("[InstallDelete]"),
            source.index("[Files]"),
            "[InstallDelete] must run before [Files]",
        )

    def test_installer_does_not_delete_user_data(self):
        source = (ROOT / "CampusNet.iss").read_text(encoding="utf-8")
        section = source[source.index("[InstallDelete]"):source.index("[Files]")]
        directives = [
            line for line in section.splitlines()
            if line.strip() and not line.strip().startswith(";") and "Name:" in line
        ]
        self.assertTrue(directives, "expected at least one InstallDelete directive")
        for line in directives:
            with self.subTest(directive=line.strip()):
                self.assertNotIn("{localappdata}", line)
                self.assertNotIn("{userappdata}", line)
                self.assertNotIn("{userdocs}", line)
                # The app directory itself holds the uninstaller and must survive.
                self.assertNotIn('Name: "{app}"', line)
                self.assertNotIn(r'Name: "{app}\*"', line)

    def test_build_clears_stale_playwright_browsers_before_installing(self):
        source = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn(".local-browsers", source)
        self.assertLess(
            source.index("Remove-Item -LiteralPath $Browsers -Recurse -Force"),
            source.index("playwright install chromium --only-shell"),
            "stale browsers must be removed before the headless shell is downloaded",
        )

    def test_build_verifies_the_bundled_browser_runtime(self):
        source = (ROOT / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("chromium_headless_shell", source)
        self.assertIn("unexpected browser payloads", source)
        self.assertIn("Qt6WebEngineCore.dll", source)
        # Playwright's own bookkeeping directory must not fail a correct build.
        self.assertIn(".links", source)

    def test_generated_spec_file_stays_untracked(self):
        """PyInstaller rewrites CampusNet.spec on every build, with absolute paths.

        It is a build artifact, so the invariant worth holding is that it cannot be
        committed with one machine's paths baked in.
        """
        self.assertIn("CampusNet.spec", (ROOT / ".gitignore").read_text(encoding="utf-8"))


class VersionConsistencyTests(unittest.TestCase):
    EXPECTED = "0.5.11"
    # Every version that must no longer appear in the build files.
    SUPERSEDED = ("0.5.9", "0.5.10")
    FILES = {
        "src/campusnet/__init__.py": '__version__ = "{v}"',
        "pyproject.toml": 'version = "{v}"',
        "CampusNet.iss": '#define MyAppVersion "{v}"',
        "build_windows.ps1": "CampusNet-Setup-{v}.exe",
    }

    def test_all_version_references_agree(self):
        for rel, template in self.FILES.items():
            with self.subTest(file=rel):
                text = (ROOT / rel).read_text(encoding="utf-8")
                self.assertIn(template.format(v=self.EXPECTED), text)

    def test_no_stale_previous_version_in_build_files(self):
        for rel in self.FILES:
            text = (ROOT / rel).read_text(encoding="utf-8")
            for superseded in self.SUPERSEDED:
                with self.subTest(file=rel, version=superseded):
                    self.assertNotIn(superseded, text)


if __name__ == "__main__":
    unittest.main()
