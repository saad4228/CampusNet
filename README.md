# CampusNet Auto Login

A cross-platform Python starter project for keeping a Fortinet captive-portal **Authentication Keepalive** page open and attempting recovery through the normal portal login form when internet access is lost.

**Status: experimental desktop prototype.** The core login flow has been tested on one college portal, but full 14,400-second session maintenance, forced-logout recovery, headless operation, and packaged installers have not yet been validated. Portal HTML, form selectors, redirects, CAPTCHA/MFA requirements, and firewall timeout policies vary by institution.

## Planned behavior

1. A student runs one-time setup with the portal **base URL** and their own credentials.
2. The username and password are stored using the operating system credential manager; they are not written to `config.toml`.
3. CampusNet makes a plain-HTTP connectivity probe without following redirects. If FortiGate intercepts it, the app looks for a fresh `/fgtauth?<temporary-token>` URL in either an HTTP `Location` header or the intercepted response HTML, and keeps that value in memory only. If the HTTP client does not see it, Chromium makes a browser-based discovery attempt.
4. A dedicated Chromium session opens that temporary URL, submits the ordinary portal form, and verifies that the `Authentication Keepalive` page appeared.
5. The app leaves the keepalive page open in its own browser session and polls connectivity. When access is lost, it looks for a fresh portal redirect before attempting recovery.
6. The desktop prototype has a basic setup window, activity log, background worker, tray behavior when supported, and per-user auto-start setting (enabled by default; the user can turn it off). It is not packaged into end-user installers yet.

This does not bypass the firewall or extend an administrator-enforced hard timeout. If the institution requires a CAPTCHA, MFA, additional consent, or a manual action, the user must complete it.

## Supported development platforms

- Windows 10/11
- macOS
- Linux desktop distributions

Python 3.11 or newer is required. The MVP uses Playwright's Chromium browser, `httpx` for connectivity checks, `keyring` for OS-backed credential storage, and `platformdirs` for cross-platform configuration paths.

## Install from source

Create a virtual environment and install the project.

### Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
playwright install chromium
```

### macOS / Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
playwright install chromium
```

On Linux, Playwright may also require system browser dependencies. If needed, run `playwright install-deps chromium` on a supported Debian/Ubuntu system, or install the equivalent packages for your distribution.

## Configure

```bash
campusnet setup
```

Enter the portal **login entry URL**, without the changing query token. For the portal shown in the screenshots, use `https://192.168.55.253:1003/fgtauth`. After successful login, the portal redirects to `/keepalive?<temporary-token>`, which displays “Authentication Keepalive”. CampusNet checks both the configured `keepalive_path` (default `/keepalive`) and page text. Do not paste either complete URL ending in `?…`: those query values are session-specific and CampusNet must not save or log them. The password prompt does not echo typed characters.

The connectivity probe uses `http://connectivitycheck.gstatic.com/generate_204` because an HTTP request is commonly redirected by a captive portal. For the first test, start CampusNet after connecting to Wi-Fi/LAN but **before submitting the portal login** so it can capture the fresh redirect token. If the internet is already authenticated, CampusNet cannot recreate the token from the screenshot; it monitors until a new portal redirect appears. Some captive portals return `200 OK` HTML instead of an HTTP redirect, so CampusNet also scans a limited amount of that response for a same-origin `/fgtauth` URL and tries browser-based discovery. If no fresh token is exposed by either path, it will not submit credentials to a guessed URL.

**TLS warning:** the provided screenshot shows Chrome marking the portal as not secure. CampusNet keeps certificate verification enabled by default. Do not disable verification unless you have verified the portal certificate/identity with your college IT team; ignoring a bad certificate can expose credentials to a spoofed portal. If your portal certificate is confirmed but untrusted by your device, `ignore_portal_tls_errors = true` is an explicit opt-in in your local config.

The config is written to the normal per-user application config directory:

- Windows: `%APPDATA%\CampusNet\config.toml`
- macOS: `~/Library/Application Support/CampusNet/config.toml`
- Linux: `~/.config/CampusNet/config.toml`

Credentials are stored separately in the OS credential store. If your Linux desktop has no supported keyring service running, configure one first; CampusNet deliberately does not silently fall back to plaintext storage.

## Desktop application prototype

The v0.5.8 desktop preview replaces the awkward native-style message box layout with a compact, consistently styled CampusNet dialog. Titles and messages align naturally, text wraps below the heading, and action buttons have clear primary/secondary styling independent of the OS dark theme. Earlier previews also include the simplified status-first dashboard, setup hints for the portal URL, and an explicit warning around portal certificate exceptions. These are UI improvements only; they do not change the authentication engine or imply that four-hour sessions and recovery are fully verified.

After installing the package and Playwright browser, launch the GUI with:

```bash
campusnet-desktop
```

On first launch, the setup window asks for the institution's portal URL and credentials. The password is stored using the OS credential store. The GUI includes a status display, recent activity log, a “Launch at startup” option that is checked by default, and a tray/menu-bar behavior when a system tray is available. Closing the window hides it to the tray; use **Exit CampusNet** from the tray or app to stop monitoring.

For this source prototype, the GUI still needs to be launched from the development environment. No signed Windows `.exe` installer or macOS `.dmg` is included yet. Those will be created only after the GUI, browser bundling, login-on-startup behavior, and session recovery have been tested on each OS.

## Brand assets

CampusNet's logo mark is bundled with the desktop package and used for the application window, setup dialog, and system-tray icon. Asset files live in `src/campusnet/assets/`:

- `campusnet-mark.png` — transparent symbol, intended for small UI and tray uses.
- `campusnet-mark-white-bg.png` — opaque/light-background version supplied for documentation and light surfaces.
- `campusnet-wordmark-white-bg.png` — full CampusNet wordmark on white.
- `campusnet-app-icon.png` — rounded-square 1024px icon for application windows and high-resolution packaging.
- `campusnet.ico` — multi-size Windows icon.
- `campusnet.icns` — PNG-backed macOS icon container for future `.app` packaging.

The GUI loads bundled image assets relative to the installed Python package, so it does not depend on the current working directory.

## First run / troubleshooting

For terminal-based diagnosis, start with a visible browser so the actual portal flow can be inspected:

```bash
campusnet run --show-browser
```

Once the flow is verified, run headless mode:

```bash
campusnet run
```

The MVP expects to find the text `Authentication Keepalive` after login. If your college's authenticated page uses a different path or text, edit `keepalive_path` and `keepalive_success_text` in your local config file. If the username/password fields differ from the defaults, edit `username_selector`, `password_selector`, and `submit_selector` with the CSS selectors used by your portal.

The default connectivity check expects HTTP `204` from `http://connectivitycheck.gstatic.com/generate_204`. It does not follow redirects: it validates a fresh portal URL from a `Location` header, then inspects intercepted HTML when the portal responds with `200 OK`, and finally tries Chromium-based discovery. Change `connectivity_url` and `expected_status` if this endpoint is blocked by your network. Redirect targets are accepted only when they match the configured portal origin, expected FortiGate authentication path, and include a non-empty query token.

Use `campusnet reset-credentials` to remove the saved credentials. Use `Ctrl+C` to stop the process.

## Security and privacy

- Each student uses their own college account and configures their own device.
- Do not add credentials, session cookies, screenshots containing tokens, browser profiles, or logs to Git.
- CampusNet does not include telemetry or a remote credential server.
- Never send your password to maintainers for debugging.
- Only use the tool where automation is allowed by the institution's network policy.
- Review all code before entering real credentials. Consider a dedicated test account, if your institution provides one.

## Current limitations

- Generic selectors will not fit every portal; the actual college form must be tested.
- Redirect discovery tries HTTP headers, intercepted response HTML, and Chromium navigation, but a portal that exposes no fresh FortiGate query token through these paths may still need network-specific discovery logic.
- Headless Chromium may behave differently from a normal browser. If the keepalive timer is throttled or does not refresh in headless mode, use the visible-browser mode while diagnosing; a packaged background/tray implementation is not included yet.
- A hard timeout configured by the administrator may force a new authentication even when keepalive is open.
- The GUI remains a source prototype. It has a basic tray behavior where supported, but native notification polish and signed installers are not complete.
- The current four-hour session cycle and forced-logout recovery still require a real network test.
- The auto-start entry points to the current Python environment in source mode; a packaged app must replace this with its stable installed executable path. Startup is enabled by default; unchecking “Launch at startup” saves the opt-out so it remains off on future launches.

## Development

Run the unit tests from the project root:

```bash
python -m unittest discover -s tests -v
```

## Roadmap

- [x] Cross-platform project structure and configuration
- [x] OS credential-store integration (no plaintext fallback)
- [x] Configurable portal selectors and connectivity check
- [x] Basic Playwright keepalive/recovery loop
- [x] Capture temporary FortiGate portal redirect tokens at runtime without persisting them
- [ ] Verify against the college's real portal
- [ ] Safe manual-intervention handling and improved state detection
- [x] Basic system-tray controls on platforms with a system tray
- [ ] Polished native notifications
- [ ] Auto-start on login on Windows, macOS, and Linux
- [x] Automated CI test matrix for Windows, macOS, and Linux
- [ ] Packaged releases and installers
- [ ] Contributor guide and platform-specific documentation

## License

MIT; see [LICENSE](LICENSE).

## Build a Windows installer (developer preview)

See [`WINDOWS_INSTALLER_GUIDE.md`](WINDOWS_INSTALLER_GUIDE.md). On a Windows 10/11 x64 machine with Python 3.11 and Inno Setup 6 installed, run `build_windows.ps1` to build a one-folder app with bundled Playwright Chromium and compile an Inno Setup installer. Test the packaged app thoroughly before sharing it; the 14,400-second cycle and forced-logout recovery remain unverified.
