"""Per-user auto-start integration for Windows, macOS, and Linux desktops."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_LABEL = "CampusNet"
MACOS_LABEL = "com.campusnet.desktop"


def launch_command() -> list[str]:
    """Return the current app's launch command for this installation mode."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "campusnet.gui"]


def is_enabled() -> bool:
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            ) as key:
                winreg.QueryValueEx(key, APP_LABEL)
            return True
        except (OSError, ImportError):
            return False
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist").exists()
    if sys.platform.startswith("linux"):
        return (Path.home() / ".config" / "autostart" / "campusnet.desktop").exists()
    return False


def set_enabled(enabled: bool) -> None:
    """Enable/disable launch at user sign-in, without administrator privileges."""
    command = launch_command()
    if sys.platform == "win32":
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                import subprocess
                value = subprocess.list2cmdline(command)
                winreg.SetValueEx(key, APP_LABEL, 0, winreg.REG_SZ, value)
            else:
                try:
                    winreg.DeleteValue(key, APP_LABEL)
                except FileNotFoundError:
                    pass
        return

    if sys.platform == "darwin":
        import plistlib
        path = Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "Label": MACOS_LABEL,
                "ProgramArguments": command,
                "RunAtLoad": True,
            }
            path.write_bytes(plistlib.dumps(payload))
            try:
                path.chmod(0o600)
            except OSError:
                pass
        else:
            path.unlink(missing_ok=True)
        return

    if sys.platform.startswith("linux"):
        path = Path.home() / ".config" / "autostart" / "campusnet.desktop"
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            def desktop_quote(part: str) -> str:
                if not any(ch.isspace() for ch in part) and '"' not in part and "\\" not in part:
                    return part
                return '"' + part.replace("\\", "\\\\").replace('"', '\\"') + '"'
            quoted = " ".join(desktop_quote(part) for part in command)
            payload = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=CampusNet\n"
                f"Exec={quoted}\n"
                "X-GNOME-Autostart-enabled=true\n"
                "Terminal=false\n"
            )
            path.write_text(payload, encoding="utf-8")
            try:
                path.chmod(0o600)
            except OSError:
                pass
        else:
            path.unlink(missing_ok=True)
        return

    raise RuntimeError(f"Automatic startup is not supported on {sys.platform}.")
