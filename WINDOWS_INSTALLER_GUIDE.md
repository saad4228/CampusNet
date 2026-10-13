# Build a CampusNet Windows installer (developer instructions)

This builds a Windows-only package. Run the build on Windows, not on macOS/Linux: PyInstaller does not cross-compile Windows executables.

## Prerequisites

1. Windows 10/11, 64-bit.
2. Python 3.11 installed and available using `py -3.11`.
3. Inno Setup 7 (or 6) installed from the official site: https://jrsoftware.org/isinfo.php
4. Internet access during the first build so pip and Playwright can download dependencies and Chromium.

## Build

1. Extract the CampusNet source ZIP into a folder, e.g. `C:\Users\<you>\Projects\campusnet-desktop-v0.5.11`.
2. Open that folder in VS Code. It should contain `pyproject.toml`, `build_windows.ps1`, and `CampusNet.iss`.
3. In a PowerShell terminal opened in that folder, run:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\build_windows.ps1
   ```

4. The script creates an isolated `.venv-build`, installs build dependencies, downloads Playwright's Chromium headless shell into its package-local browser directory (the GUI uses headless mode), runs the tests, and creates `dist\CampusNet\CampusNet.exe`. If it detects Inno Setup, it also compiles the installer.
5. If the build completed but the installer wasn't compiled, open `CampusNet.iss` in Inno Setup Compiler and click **Compile**. The output should be `installer-output\CampusNet-Setup-0.5.11.exe`.

## Mandatory test before sharing

1. First run `dist\CampusNet\CampusNet.exe` directly and complete setup with your own college account.
2. Confirm the window, app icon, settings dialog, tray behavior, credential storage, login flow, and connectivity checks work.
3. Run the generated installer, install CampusNet as a normal (non-administrator) user, launch it from the Start menu, and repeat the tests.
4. Test `Launch at startup` by enabling it, signing out/in, and then disabling it and signing out/in again.
5. Test uninstall; verify that the old startup entry is removed. Confirm that reinstalling preserves or cleanly reinitializes the user's configuration as intended.
6. Do not publish to students until the full four-hour session and forced-logout recovery are tested.

## What this doesn't do

- It does not sign the executable or installer. Windows SmartScreen may show an unrecognized-app warning. Do not tell students to ignore security warnings; publish hashes and use code signing when a trusted publisher identity is available.
- It does not prove the full four-hour keepalive/recovery behavior.
- It includes the current configured portal TLS workaround as implemented in source; explain its security implications and do not weaken TLS verification globally.
- It builds x64 Windows output. Build/test separately for other architectures if needed.

The build bundles Playwright's Chromium headless shell rather than the full browser to reduce the final package size to avoid requiring students to install a browser separately. Keep the complete `dist\CampusNet` directory intact until it has been included in the installer.
