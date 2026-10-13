"""Runtime checks for the startup sequencing introduced in v0.5.10.

Two things must still hold after moving work off the pre-window path:
  * background authentication runs on the worker thread, headless, and can be stopped;
  * finishing setup when credentials are missing still leaves CampusNet monitoring.

These tests need Qt. They are skipped where Qt cannot be imported or cannot open
its offscreen platform plugin, so the rest of the suite still runs there.
"""
from __future__ import annotations

import os
import sys
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Must be set before any QApplication is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:  # pragma: no cover - environment dependent
    from PySide6.QtWidgets import QApplication

    QT_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment dependent
    QApplication = None
    QT_IMPORT_ERROR = exc

_APP = None


def setUpModule():
    global _APP
    if QApplication is None:
        raise unittest.SkipTest(f"PySide6 is not importable: {QT_IMPORT_ERROR}")
    try:
        _APP = QApplication.instance() or QApplication([])
    except Exception as exc:  # pragma: no cover - environment dependent
        raise unittest.SkipTest(f"Qt cannot start its offscreen platform: {exc}")

    # Guard against an environment wired to a different checkout: these tests
    # assert behaviour that only exists in this one, and would otherwise fail in
    # a way that looks like a defect in the application.
    from campusnet import gui as gui_module

    if not hasattr(gui_module, "SMALL_ICON_PATH"):
        raise AssertionError(
            "campusnet.gui does not look like this checkout. Loaded module: "
            f"{gui_module.__file__}. Install this repository (pip install -e .) "
            "or set PYTHONPATH to its src directory."
        )


class StubMonitor:
    """Replaces campusnet.monitor so no browser, network or portal code runs."""

    def __init__(self, wait_for_stop=False):
        self.wait_for_stop = wait_for_stop
        self.thread_ident = None
        self.config = None
        self.show_browser = None
        self.started = threading.Event()

    def install(self, test):
        previous = sys.modules.get("campusnet.monitor")
        module = types.ModuleType("campusnet.monitor")

        async def run_app(config, show_browser=False, stop_event=None):
            self.thread_ident = threading.get_ident()
            self.config = config
            self.show_browser = show_browser
            self.started.set()
            if self.wait_for_stop and stop_event is not None:
                await stop_event.wait()

        module.run_app = run_app
        sys.modules["campusnet.monitor"] = module

        def restore():
            if previous is None:
                sys.modules.pop("campusnet.monitor", None)
            else:
                sys.modules["campusnet.monitor"] = previous

        test.addCleanup(restore)
        return self


def _config(**overrides):
    from campusnet.config import AppConfig

    base = {"portal_url": "https://portal.example.edu:1003/fgtauth", "headless": False}
    base.update(overrides)
    return AppConfig(**base)


class BackgroundWorkerTests(unittest.TestCase):
    """Authentication work must stay on the worker thread."""

    def test_monitor_runs_on_the_worker_thread_not_the_gui_thread(self):
        from campusnet.gui import BackendWorker

        stub = StubMonitor().install(self)
        worker = BackendWorker(_config())
        worker.start()
        self.assertTrue(worker.wait(30000), "worker thread did not finish in time")

        self.assertIsNotNone(stub.thread_ident, "monitor.run_app was never reached")
        self.assertNotEqual(
            stub.thread_ident,
            threading.get_ident(),
            "background authentication must not run on the GUI thread",
        )

    def test_worker_forces_headless_and_hides_the_browser(self):
        from campusnet.gui import BackendWorker

        stub = StubMonitor().install(self)
        worker = BackendWorker(_config(headless=False))
        worker.start()
        self.assertTrue(worker.wait(30000))

        self.assertTrue(stub.config.headless, "the packaged app must run Chromium headless")
        self.assertFalse(stub.show_browser)

    def test_other_config_values_reach_the_worker_unchanged(self):
        from campusnet.gui import BackendWorker

        source = _config(check_interval_seconds=45, ignore_portal_tls_errors=True)
        stub = StubMonitor().install(self)
        worker = BackendWorker(source)
        worker.start()
        self.assertTrue(worker.wait(30000))

        self.assertEqual(stub.config.portal_url, source.portal_url)
        self.assertEqual(stub.config.check_interval_seconds, 45)
        self.assertTrue(stub.config.ignore_portal_tls_errors)
        self.assertEqual(stub.config.keepalive_path, source.keepalive_path)

    def test_request_stop_ends_the_worker(self):
        from campusnet.gui import BackendWorker

        stub = StubMonitor(wait_for_stop=True).install(self)
        worker = BackendWorker(_config())
        worker.start()
        self.assertTrue(stub.started.wait(30), "monitor never started")
        # The event loop reference is published from inside the coroutine.
        worker.request_stop()
        self.assertTrue(worker.wait(30000), "request_stop did not stop the worker")


class FirstRunSetupFlowTests(unittest.TestCase):
    """Setup now opens after the window instead of before it, but must still work."""

    def _window(self, credentials_missing: bool):
        from campusnet import gui as gui_module
        from campusnet.credentials import CredentialError

        state = {
            "missing": credentials_missing,
            "warnings": [],
            "setup_calls": 0,
        }

        def fake_load_config(*args, **kwargs):
            return _config()

        def fake_load_credentials():
            if state["missing"]:
                raise CredentialError("No saved credentials. Run `campusnet setup` first.")
            return ("student01", "secret-pw")

        def fake_warning(parent, title, text):
            state["warnings"].append((title, text))
            return None

        for name, value in (
            ("load_config", fake_load_config),
            ("load_credentials", fake_load_credentials),
            ("_show_warning", fake_warning),
            ("_show_information", lambda *a, **k: None),
            ("set_enabled", lambda enabled: None),
            ("write_config", lambda config: None),
            ("is_enabled", lambda: True),
        ):
            original = getattr(gui_module, name)
            setattr(gui_module, name, value)
            self.addCleanup(setattr, gui_module, name, original)

        window = gui_module.MainWindow(_config())
        self.addCleanup(window.deleteLater)
        return window, state

    def test_missing_credentials_opens_setup_and_then_starts_monitoring(self):
        stub = StubMonitor().install(self)
        window, state = self._window(credentials_missing=True)

        def fake_edit_settings():
            state["setup_calls"] += 1
            state["missing"] = False  # the user completes setup
            return True

        window.edit_settings = fake_edit_settings
        window.start_monitoring()

        self.assertEqual(len(state["warnings"]), 1, "the user must be told setup is required")
        self.assertEqual(state["warnings"][0][0], "CampusNet setup required")
        self.assertEqual(state["setup_calls"], 1, "the setup dialog must open once")
        self.assertIsNotNone(window.worker, "monitoring must start after setup completes")
        self.assertTrue(window.worker.wait(30000), "the worker thread did not finish")
        self.assertTrue(
            stub.started.is_set(),
            "background authentication must actually begin after setup completes",
        )

    def test_cancelling_setup_does_not_start_monitoring(self):
        StubMonitor().install(self)
        window, state = self._window(credentials_missing=True)

        def fake_edit_settings():
            state["setup_calls"] += 1
            return False  # the user cancels

        window.edit_settings = fake_edit_settings
        window.start_monitoring()

        self.assertEqual(state["setup_calls"], 1)
        self.assertIsNone(window.worker, "monitoring must not start without credentials")

    def test_setup_that_does_not_fix_credentials_retries_only_once(self):
        StubMonitor().install(self)
        window, state = self._window(credentials_missing=True)

        def fake_edit_settings():
            state["setup_calls"] += 1
            return True  # claims success but credentials are still missing

        window.edit_settings = fake_edit_settings
        window.start_monitoring()

        self.assertEqual(state["setup_calls"], 2, "exactly one retry, then stop")
        self.assertIsNone(window.worker)

    def test_valid_credentials_start_monitoring_without_any_dialog(self):
        stub = StubMonitor().install(self)
        window, state = self._window(credentials_missing=False)
        window.edit_settings = lambda: self.fail("setup must not open when credentials exist")

        window.start_monitoring()

        self.assertEqual(state["warnings"], [])
        self.assertIsNotNone(window.worker)
        self.assertTrue(window.worker.wait(30000), "the worker thread did not finish")
        self.assertTrue(stub.started.is_set(), "background authentication must begin")


class SingleInstanceTests(unittest.TestCase):
    """A second launch must hand over to the running instance, not start another."""

    KEY = "CampusNet-test-single-instance"

    def setUp(self):
        from campusnet import gui as gui_module

        self.gui = gui_module
        original = gui_module.SINGLE_INSTANCE_KEY
        gui_module.SINGLE_INSTANCE_KEY = self.KEY
        self.addCleanup(setattr, gui_module, "SINGLE_INSTANCE_KEY", original)

        from PySide6.QtNetwork import QLocalServer

        QLocalServer.removeServer(self.KEY)
        self.addCleanup(QLocalServer.removeServer, self.KEY)

    def test_first_instance_claims_the_lock(self):
        already_running, server = self.gui._claim_single_instance()
        self.addCleanup(server.close)
        self.assertFalse(already_running)
        self.assertIsNotNone(server, "the first instance must get a listening server")
        self.assertTrue(server.isListening())

    def test_second_instance_detects_the_first_and_does_not_listen(self):
        already_running, server = self.gui._claim_single_instance()
        self.addCleanup(server.close)
        self.assertFalse(already_running)

        second_running, second_server = self.gui._claim_single_instance()
        self.assertTrue(second_running, "the second instance must detect the first")
        self.assertIsNone(second_server, "the second instance must not listen")

    def test_second_instance_wakes_the_first(self):
        from PySide6.QtCore import QEventLoop, QTimer

        already_running, server = self.gui._claim_single_instance()
        self.addCleanup(server.close)
        self.assertFalse(already_running)

        woken = []
        server.newConnection.connect(lambda: woken.append(True))

        self.gui._claim_single_instance()

        # Let the server deliver the pending connection.
        loop = QEventLoop()
        QTimer.singleShot(500, loop.quit)
        server.newConnection.connect(loop.quit)
        loop.exec()

        self.assertTrue(woken, "the running instance must be notified to show its window")

    def test_lock_is_released_so_a_later_launch_becomes_the_first(self):
        _, server = self.gui._claim_single_instance()
        server.close()

        already_running, new_server = self.gui._claim_single_instance()
        self.addCleanup(new_server.close)
        self.assertFalse(already_running, "a stale socket must not block a fresh start")
        self.assertIsNotNone(new_server)


if __name__ == "__main__":
    unittest.main()
