#!/usr/bin/env bash
set -euo pipefail

printf '\033[1;36mCampusNet desktop developer preview\033[0m\n'
printf '\033[1;33mThis sets up the source prototype. It is not the final end-user installer.\033[0m\n'

if [ ! -x .venv/bin/python ]; then
  python3.11 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/python -m playwright install chromium
exec .venv/bin/python -m campusnet.gui
