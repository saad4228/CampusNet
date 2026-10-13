"""Credential-store behaviour must be unchanged now that keyring is imported lazily.

The lazy import is what makes these tests possible: a stub backend can be put in
place before the first call, so the real OS credential store is never touched.
"""
from __future__ import annotations

import os
import subprocess
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

sys.path.insert(0, str(SRC))

from campusnet import credentials as credentials_module  # noqa: E402  (path set up above)
from campusnet.credentials import (  # noqa: E402
    PASSWORD_KEY,
    SERVICE_NAME,
    USERNAME_KEY,
    CredentialError,
    delete_credentials,
    load_credentials,
    save_credentials,
)


def setUpModule():
    """Refuse to run if the module under test would reach the real credential store.

    These tests replace keyring in sys.modules, which only works while the import
    happens inside each credential function. If an older, eagerly importing copy of
    campusnet.credentials is on the path - for example when the environment is
    installed from a different checkout - the stub would be bypassed and the real
    Windows Credential Manager would be written to and deleted from.
    """
    if hasattr(credentials_module, "keyring"):
        raise AssertionError(
            "campusnet.credentials imports keyring at module scope, so these tests "
            "would reach the real credential store. Loaded module: "
            f"{credentials_module.__file__}. Install this repository "
            "(pip install -e .) or set PYTHONPATH to its src directory."
        )


class FakeKeyring(types.ModuleType):
    """Minimal in-memory stand-in for the keyring package."""

    def __init__(self, store=None, fail_with=None, drop_writes=False):
        super().__init__("keyring")
        self.store = {} if store is None else store
        self.fail_with = fail_with
        self.drop_writes = drop_writes
        self.calls: list[tuple[str, str, str]] = []
        self.errors = types.SimpleNamespace(PasswordDeleteError=FakePasswordDeleteError)

    def _maybe_fail(self):
        if self.fail_with is not None:
            raise self.fail_with

    def set_password(self, service, key, value):
        self.calls.append(("set", service, key))
        self._maybe_fail()
        if not self.drop_writes:
            self.store[(service, key)] = value

    def get_password(self, service, key):
        self.calls.append(("get", service, key))
        self._maybe_fail()
        return self.store.get((service, key))

    def delete_password(self, service, key):
        self.calls.append(("delete", service, key))
        self._maybe_fail()
        if (service, key) not in self.store:
            raise FakePasswordDeleteError(key)
        del self.store[(service, key)]


class FakePasswordDeleteError(Exception):
    pass


class LazyKeyringImportTests(unittest.TestCase):
    """Importing the modules must not pull in the keyring dependency chain."""

    def _import_probe(self, module: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
        return subprocess.run(
            [
                sys.executable,
                "-c",
                f"import {module}, sys; print('KEYRING' if 'keyring' in sys.modules else 'CLEAN')",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
        )

    def test_importing_credentials_module_does_not_import_keyring(self):
        result = self._import_probe("campusnet.credentials")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "CLEAN")

    def test_importing_gui_module_does_not_import_keyring(self):
        result = self._import_probe("campusnet.gui")
        if result.returncode != 0:
            if "PySide6" in result.stderr or "libEGL" in result.stderr:
                self.skipTest(f"Qt is not importable in this environment: {result.stderr.strip()[:200]}")
            self.fail(result.stderr)
        self.assertEqual(result.stdout.strip(), "CLEAN")


class CredentialSemanticsTests(unittest.TestCase):
    """Same service name, same keys, same read-back verification, same errors."""

    def _install(self, fake: FakeKeyring) -> FakeKeyring:
        previous = {name: sys.modules.get(name) for name in ("keyring", "keyring.errors")}

        def restore():
            for name, module in previous.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

        self.addCleanup(restore)
        sys.modules["keyring"] = fake
        sys.modules["keyring.errors"] = fake.errors
        # Defence in depth: if the module ever grows a module-level keyring global
        # again, redirect that too so the real credential store stays untouched.
        if hasattr(credentials_module, "keyring"):
            original = credentials_module.keyring
            self.addCleanup(setattr, credentials_module, "keyring", original)
            credentials_module.keyring = fake
        return fake

    def test_save_then_load_round_trip(self):
        fake = self._install(FakeKeyring())
        save_credentials("  student01  ", "secret-pw")
        self.assertEqual(fake.store[(SERVICE_NAME, USERNAME_KEY)], "student01")
        self.assertEqual(fake.store[(SERVICE_NAME, PASSWORD_KEY)], "secret-pw")
        self.assertEqual(load_credentials(), ("student01", "secret-pw"))

    def test_save_uses_the_unchanged_service_and_key_names(self):
        fake = self._install(FakeKeyring())
        save_credentials("student01", "secret-pw")
        services = {service for _, service, _ in fake.calls}
        keys = {key for _, _, key in fake.calls}
        self.assertEqual(services, {"CampusNet Auto Login"})
        self.assertEqual(keys, {"portal-username", "portal-password"})

    def test_save_verifies_the_write_by_reading_it_back(self):
        fake = self._install(FakeKeyring(drop_writes=True))
        with self.assertRaises(CredentialError):
            save_credentials("student01", "secret-pw")
        self.assertIn(("get", SERVICE_NAME, USERNAME_KEY), fake.calls)

    def test_empty_values_still_raise_value_error_without_touching_the_store(self):
        fake = self._install(FakeKeyring())
        for username, password in (("", "pw"), ("   ", "pw"), ("student01", "")):
            with self.subTest(username=username, password=password):
                with self.assertRaises(ValueError):
                    save_credentials(username, password)
        self.assertEqual(fake.calls, [])

    def test_backend_failure_is_reported_as_credential_error(self):
        self._install(FakeKeyring(fail_with=RuntimeError("no backend")))
        with self.assertRaises(CredentialError):
            save_credentials("student01", "secret-pw")
        with self.assertRaises(CredentialError):
            load_credentials()

    def test_missing_credentials_raise_credential_error(self):
        self._install(FakeKeyring())
        with self.assertRaises(CredentialError):
            load_credentials()

    def test_partial_credentials_raise_credential_error(self):
        self._install(FakeKeyring(store={(SERVICE_NAME, USERNAME_KEY): "student01"}))
        with self.assertRaises(CredentialError):
            load_credentials()

    def test_delete_removes_both_entries(self):
        fake = self._install(
            FakeKeyring(
                store={
                    (SERVICE_NAME, USERNAME_KEY): "student01",
                    (SERVICE_NAME, PASSWORD_KEY): "secret-pw",
                }
            )
        )
        delete_credentials()
        self.assertEqual(fake.store, {})

    def test_delete_tolerates_already_missing_entries(self):
        self._install(FakeKeyring())
        delete_credentials()  # must not raise

    def test_delete_reports_unexpected_backend_errors(self):
        self._install(FakeKeyring(fail_with=RuntimeError("vault locked")))
        with self.assertRaises(CredentialError):
            delete_credentials()


if __name__ == "__main__":
    unittest.main()
