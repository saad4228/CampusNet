# Startup performance notes

## v0.5.11

### Reconnect latency

After a manual portal logout, or when Wi-Fi associates after the app has already
started, recovery used to wait out two full `check_interval_seconds` before even
attempting to log in - 30 to 60 seconds of pure waiting.

- Recovery now runs on the **first** failed probe when the connectivity check
  captured a fresh FortiGate redirect. A redirect is positive proof the portal
  logged this device out. Without a redirect, a second consecutive failure is
  still required, so an ordinary network blip does not trigger a re-login.
- While offline, probes use `offline_check_interval_seconds` (default 3) instead
  of `check_interval_seconds`. Online checks are unchanged at 30 seconds.
- After a successful login the next probe runs immediately instead of after a
  full interval, so the dashboard reports the real state at once.
- The existing recovery backoff is unchanged: after an attempt, the next one
  waits `retry_delay_seconds`, doubling to a 300 second cap. This is what keeps a
  genuine outage from retrying at speed.
- Only one instance can run. A second launch asks the running one to show its
  window and exits, so two copies cannot race to authenticate against the same
  portal session and log each other out.

Expected effect: roughly 4-8 seconds from logout to reconnect, against 35-65
seconds before. This has not yet been measured against a real portal.

## v0.5.10

Measured on the installed v0.5.10 build with the procedure under "Measuring
time to window": 0.58 s median to a visible window over three warm runs
(0.94 / 0.58 / 0.58), against 2.20 s for the installed v0.5.9 build. Cold-start
timing after a reboot has not been measured.

### Packaging

- The installer removes the previously installed bundle (`{app}\_internal`)
  before copying the new one. Earlier installers copied over the top of the old
  installation, so files from previous versions stayed behind. User data is not
  affected: settings live in `%LOCALAPPDATA%\CampusNet` and credentials live in
  the Windows Credential Manager, both outside the application directory.
- The build script clears Playwright's package-local browser directory before
  running `playwright install chromium --only-shell`, so a full Chromium left
  over from an earlier build is no longer collected into the bundle.
- The build fails if the bundle contains a browser payload other than the
  Chromium headless shell (plus Playwright's own `ffmpeg`, `winldd` and `.links`
  entries), or if Qt WebEngine was collected.
- `CampusNet.spec` is a build artifact: PyInstaller rewrites it on every run of
  `build_windows.ps1`, with absolute paths for the machine that built it. It is
  gitignored and must not be committed or used as the build input.

### Application

- `keyring` is imported inside the credential functions instead of at module
  scope. It was the largest single import on the startup path. The credential
  store itself is unchanged: same backend, same service name, same key names,
  same read-back verification.
- `asyncio` is imported inside `BackendWorker.run`, on the worker thread.
- `main()` no longer probes the credential store before creating the window. The
  result of that probe was discarded, and `MainWindow.start_monitoring` already
  validates credentials just after the window is shown.
- The Windows autostart entry is reconciled after `window.show()` instead of
  before it.
- Window, tray and header icons load a 128x128 PNG instead of decoding the
  1024x1024 app icon. The full-size PNG, `campusnet.ico` and `campusnet.icns`
  are unchanged and still used for packaging.

### Behaviour change to be aware of

When the configuration file is valid but credentials are missing, setup now
opens just after the main window appears, instead of before the window is
created. Completing setup still starts monitoring; cancelling it leaves the
window open with monitoring stopped, where previously the application exited.
A missing or invalid configuration file still opens setup before the window.

## v0.5.9

This release targeted the time before the window appears and the extra
time/disk work caused by packaging unused browser and Qt components.

- The desktop UI no longer imports the network monitor at module import time.
  Playwright and HTTP monitoring imports start on the background worker after
  the window is shown.
- The GUI explicitly runs the background browser in headless mode, so it can use
  Playwright's Chromium headless shell.
- Windows builds install the headless shell only
  (`playwright install chromium --only-shell`).
- The dependency is `PySide6-Essentials` rather than the PySide6 meta-package.
- PyInstaller no longer collects every PySide6 module. The build stays
  `--onedir`, which avoids one-file extraction overhead on every launch.

## Rebuild on Windows

1. Extract this source release into a new folder. Do not reuse a `.venv-build`,
   `build` or `dist` folder from an earlier version.
2. Open PowerShell in the folder containing `build_windows.ps1`.
3. Run:

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\build_windows.ps1
   ```

4. Test `dist\CampusNet\CampusNet.exe` first. Then test the generated
   `installer-output\CampusNet-Setup-0.5.11.exe`.

## Verifying that an upgrade removes the stale payload

Run this before and after installing v0.5.11 over an existing installation:

```powershell
$app = "$env:LOCALAPPDATA\Programs\CampusNet"
"files: " + (Get-ChildItem $app -Recurse -File | Measure-Object).Count
"MB: " + [math]::Round((Get-ChildItem $app -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)
Test-Path "$app\_internal\PySide6\Qt6WebEngineCore.dll"
Test-Path "$app\_internal\PySide6\qml"
Get-ChildItem "$app\_internal\playwright\driver\package\.local-browsers" -Directory | Select-Object Name
```

After the upgrade the file count and size should match `dist\CampusNet`, both
`Test-Path` checks should be `False`, and the browser directory should list only
`chromium_headless_shell-*`, `ffmpeg-*`, `winldd-*` and `.links`.

Confirm the same run that user data survived: `%LOCALAPPDATA%\CampusNet\config.toml`
should still exist with the same portal URL, and the application should still
sign in without asking for credentials again.

## Measuring time to window

Measure the installed application, not `dist`, and measure a cold start by
rebooting first. Launch through the Start-menu shortcut or let the login item
start it, with no other instance already running.

```powershell
$exe = "$env:LOCALAPPDATA\Programs\CampusNet\CampusNet.exe"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$p = Start-Process -FilePath $exe -PassThru
while ($sw.Elapsed.TotalSeconds -lt 120 -and -not $p.HasExited) {
    $p.Refresh()
    if ($p.MainWindowHandle -ne 0) { break }
    Start-Sleep -Milliseconds 40
}
"time to window: {0:N2} s" -f $sw.Elapsed.TotalSeconds
```

Take the median of three cold runs and three warm runs, for the old and new
installed the same way, and record both. A single run is not a measurement:
timing depends on Windows login work, Defender scanning, disk speed and how many
other login items are present.

## Limitations

Exact startup time depends on Windows, Defender scans, disk performance and the
network. Internet access after login still needs the network to come up, the
captive portal to answer, and the browser to authenticate; this release does not
promise zero-delay internet after boot. The packaged GUI always uses headless
Chromium; the CLI's `--show-browser` troubleshooting mode remains for
development environments that install the full Chromium browser. The full
14,400-second session and recovery path still need real-network verification.
