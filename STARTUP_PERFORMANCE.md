# Startup performance changes in v0.5.9

This release targets two separate delays: the time before the desktop window appears, and the extra time/disk work caused by packaging unused browser and Qt components.

## Changes

- The desktop UI no longer imports the network monitor at module import time. Playwright and HTTP monitoring imports start on the background worker after the window is shown.
- The GUI explicitly runs the background browser in headless mode. It can therefore use Playwright's Chromium headless shell.
- Windows builds install the Playwright headless shell only (`playwright install chromium --only-shell`), rather than both the full Chromium browser and the shell.
- The dependency is narrowed from the PySide6 meta-package to `PySide6-Essentials`, which contains the Qt Core, GUI, and Widgets modules used by this interface.
- PyInstaller no longer collects every PySide6 module, avoiding unrelated Qt Addons, PDF, WebEngine, and 3D modules where they are not imported. The build stays `--onedir`; this avoids one-file extraction overhead on every launch.
- The build script checks Inno Setup 7 and 6 locations. The installer script uses the current x64-compatible architecture identifier and a `RunOnceId` for clean uninstall behavior.

## Rebuild on Windows

1. Extract this source release into a new folder. Do not reuse an old `.venv-build` or `dist` folder from v0.5.8.
2. Open PowerShell in the folder containing `build_windows.ps1`.
3. Run:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\build_windows.ps1
   ```

4. Test `dist\CampusNet\CampusNet.exe` first. Then test the generated `installer-output\CampusNet-Setup-0.5.9.exe`.
5. Install the new version over v0.5.8 and compare from clicking the Start menu shortcut to the main window appearing. Test both a cold launch after reboot and a warm launch.

## Expectations and limitations

These changes should reduce package size and the work needed before the UI appears, but exact startup time depends on Windows, Defender scans, disk performance, and the network. The window should appear before Playwright starts its browser engine. Actual internet authentication still needs time for the network to come up, the captive portal to answer, and the browser to authenticate. This release does not promise zero-delay internet after boot.

The packaged GUI always uses headless Chromium; the CLI's `--show-browser` troubleshooting mode remains for development environments that install the full Chromium browser. The full 14,400-second session and recovery path still need real-network verification.
