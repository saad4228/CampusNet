$ErrorActionPreference = 'Stop'

Write-Host "CampusNet desktop developer preview" -ForegroundColor Cyan
Write-Host "This sets up the source prototype. It is not the final end-user installer." -ForegroundColor Yellow

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3.11 -m venv .venv
}

$python = ".\.venv\Scripts\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -e .
& $python -m playwright install chromium
& $python -m campusnet.gui
