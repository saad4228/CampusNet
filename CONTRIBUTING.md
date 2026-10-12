# Contributing

Thanks for helping improve CampusNet.

## Before opening an issue

- Never include passwords, cookies, session tokens, private portal URLs with embedded tokens, or unredacted portal screenshots.
- Describe your operating system and Python version.
- If reporting a selector issue, provide only generic selector names or a sanitized HTML snippet with all personal/session data removed.
- Confirm that automation is permitted by your institution.

## Pull requests

1. Keep credentials out of source code, tests, fixtures, and logs.
2. Add tests for changes to configuration or connectivity behavior.
3. Run `python -m unittest discover -s tests -v`.
4. Explain which platform(s) you tested on and whether the test used a real portal or a mock.

Please do not add telemetry or remote credential collection.


## Desktop prototype

Install the project and launch the test GUI with `campusnet-desktop`. When making changes to `monitor.py`, keep its stop-event behavior intact so the GUI can shut down the background worker cleanly. Test the GUI on the native operating system before claiming cross-platform support. Do not submit screenshots or logs containing credentials or temporary portal tokens.
