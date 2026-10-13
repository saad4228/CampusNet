"""Reconnect timing: a portal logout must be acted on without waiting out an interval.

The two decisions that used to cost 30-60 seconds after a manual logout are
isolated as pure functions, so they can be checked exactly rather than by timing
a real loop. One scripted run of the monitor loop then checks that the loop
actually uses them.
"""
from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from campusnet.config import AppConfig  # noqa: E402


def _config(**overrides) -> AppConfig:
    base = {"portal_url": "https://portal.example.edu:1003/fgtauth"}
    base.update(overrides)
    return AppConfig(**base)


def _monitor():
    """Import the monitor module, skipping if playwright/httpx are unavailable."""
    try:
        from campusnet import monitor
    except Exception as exc:  # pragma: no cover - environment dependent
        raise unittest.SkipTest(f"campusnet.monitor is not importable: {exc}")
    if not hasattr(monitor, "should_attempt_recovery"):
        raise AssertionError(
            "campusnet.monitor does not look like this checkout. Loaded module: "
            f"{monitor.__file__}. Install this repository (pip install -e .) or set "
            "PYTHONPATH to its src directory."
        )
    return monitor


class RecoveryGateTests(unittest.TestCase):
    """A fresh FortiGate redirect is proof of a logout, so recover immediately."""

    def setUp(self):
        self.monitor = _monitor()

    def test_fresh_redirect_recovers_on_the_first_failure(self):
        self.assertTrue(
            self.monitor.should_attempt_recovery(
                "https://portal.example.edu:1003/fgtauth?abc123",
                failures=1,
                now=100.0,
                next_recovery_at=0.0,
            )
        )

    def test_without_a_redirect_a_single_failure_is_ignored(self):
        self.assertFalse(
            self.monitor.should_attempt_recovery(None, failures=1, now=100.0, next_recovery_at=0.0)
        )

    def test_without_a_redirect_a_second_failure_recovers(self):
        self.assertTrue(
            self.monitor.should_attempt_recovery(None, failures=2, now=100.0, next_recovery_at=0.0)
        )

    def test_backoff_window_still_suppresses_recovery(self):
        for url in ("https://portal.example.edu:1003/fgtauth?abc123", None):
            with self.subTest(fresh_portal_url=url):
                self.assertFalse(
                    self.monitor.should_attempt_recovery(
                        url, failures=5, now=100.0, next_recovery_at=120.0
                    )
                )

    def test_backoff_window_releases_recovery_once_it_passes(self):
        self.assertTrue(
            self.monitor.should_attempt_recovery(
                "https://portal.example.edu:1003/fgtauth?abc123",
                failures=1,
                now=120.0,
                next_recovery_at=120.0,
            )
        )


class CheckDelayTests(unittest.TestCase):
    """Poll quickly while offline, at the configured interval while online."""

    def setUp(self):
        self.monitor = _monitor()
        self.config = _config(check_interval_seconds=30, offline_check_interval_seconds=3)

    def test_online_uses_the_configured_interval(self):
        self.assertEqual(
            self.monitor.next_check_delay(self.config, online=True, recovered=False), 30.0
        )

    def test_offline_uses_the_short_interval(self):
        self.assertEqual(
            self.monitor.next_check_delay(self.config, online=False, recovered=False), 3.0
        )

    def test_a_successful_recovery_reprobes_immediately(self):
        self.assertEqual(
            self.monitor.next_check_delay(self.config, online=False, recovered=True), 0.0
        )

    def test_offline_interval_never_exceeds_the_online_interval(self):
        config = _config(check_interval_seconds=2, offline_check_interval_seconds=30)
        self.assertEqual(self.monitor.next_check_delay(config, online=False, recovered=False), 2.0)

    def test_delay_is_always_a_float(self):
        for online in (True, False):
            with self.subTest(online=online):
                self.assertIsInstance(
                    self.monitor.next_check_delay(self.config, online=online, recovered=False),
                    float,
                )


class MonitorLoopTests(unittest.TestCase):
    """The loop must use those decisions, not its own hard-coded waits."""

    def setUp(self):
        self.monitor = _monitor()

    def _run_loop(self, probe_results):
        """Drive run_app with scripted probe results and no browser or network.

        Returns the list of start_urls that the portal flow was asked to open and
        the delays the loop waited for.
        """
        monitor = self.monitor
        probes = list(probe_results)
        auth_calls: list[str | None] = []
        delays: list[float] = []
        stop_event = asyncio.Event()

        async def fake_probe(client, config):
            if not probes:
                stop_event.set()
                return True, None
            return probes.pop(0)

        async def fake_ensure(page, config, username, password, start_url=None):
            auth_calls.append(start_url)

        async def fake_discover(page, config):
            return None

        real_next_check_delay = monitor.next_check_delay

        def recording_delay(config, online, recovered):
            delay = real_next_check_delay(config, online, recovered)
            delays.append(delay)
            # Keep the test fast: the decision is what matters, not the wall clock.
            return 0.0 if delay > 0 else delay

        patches = {
            "probe_connectivity": fake_probe,
            "ensure_keepalive_page": fake_ensure,
            "discover_portal_in_browser": fake_discover,
            "load_credentials": lambda: ("student01", "secret-pw"),
            "async_playwright": _fake_playwright,
            "next_check_delay": recording_delay,
        }
        for name, value in patches.items():
            original = getattr(monitor, name)
            setattr(monitor, name, value)
            self.addCleanup(setattr, monitor, name, original)

        config = _config(check_interval_seconds=30, offline_check_interval_seconds=3)
        asyncio.run(monitor.run_app(config, show_browser=False, stop_event=stop_event))
        return auth_calls, delays

    def test_a_logout_is_authenticated_on_the_first_failed_probe(self):
        portal = "https://portal.example.edu:1003/fgtauth?token"
        # Online at startup, then one failed probe carrying a fresh redirect.
        auth_calls, _ = self._run_loop([(True, None), (False, portal)])
        self.assertIn(portal, auth_calls, "the portal flow must run on the first failure")

    def test_a_single_failure_without_a_redirect_does_not_authenticate(self):
        auth_calls, _ = self._run_loop([(True, None), (False, None), (True, None)])
        self.assertEqual(auth_calls, [], "a blip without a redirect must not re-login")

    def test_the_loop_waits_the_short_interval_while_offline(self):
        _, delays = self._run_loop([(True, None), (False, None), (True, None)])
        self.assertIn(3.0, delays, "offline probes must use offline_check_interval_seconds")
        self.assertIn(30.0, delays, "online probes must use check_interval_seconds")


def _fake_playwright():
    """Stand in for async_playwright(): no browser is started."""

    class FakePage:
        def set_default_timeout(self, timeout):
            pass

    class FakeContext:
        async def new_page(self):
            return FakePage()

        async def close(self):
            pass

    class FakeBrowser:
        async def new_context(self, **kwargs):
            return FakeContext()

        async def close(self):
            pass

    class FakeChromium:
        async def launch(self, **kwargs):
            return FakeBrowser()

    class FakeManager:
        async def __aenter__(self):
            return types.SimpleNamespace(chromium=FakeChromium())

        async def __aexit__(self, *exc_info):
            return False

    return FakeManager()


if __name__ == "__main__":
    unittest.main()
