"""Make the packaged app use the Chromium browser bundled with Playwright."""
import os

# The build script installs Chromium with PLAYWRIGHT_BROWSERS_PATH=0, placing it
# inside the Playwright package so the PyInstaller bundle can carry it along.
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"
