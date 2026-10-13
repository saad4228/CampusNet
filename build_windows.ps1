$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Invoke-Checked {
    param([Parameter(Mandatory = $true)][string]$Description, [Parameter(Mandatory = $true)][scriptblock]$Command)
    Write-Host "`n== $Description ==" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE. Read the messages above and fix the first error before retrying."
    }
}

$Python = Join-Path $ProjectRoot '.venv-build\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    Invoke-Checked 'Create build virtual environment (Python 3.11)' { py -3.11 -m venv .venv-build }
}
if (-not (Test-Path $Python)) {
    throw 'Python 3.11 was not found. Install it from python.org or run: py install 3.11'
}

# CampusNet's desktop worker always uses headless Chromium. Installing only the
# headless shell avoids bundling the full browser, reducing installer size and AV scanning.
$env:PLAYWRIGHT_BROWSERS_PATH = '0'
Invoke-Checked 'Upgrade pip' { & $Python -m pip install --upgrade pip }
Invoke-Checked 'Install CampusNet and build tools' { & $Python -m pip install -e . pyinstaller }
# PLAYWRIGHT_BROWSERS_PATH=0 makes Playwright download browsers into its own
# package directory, and `playwright install` keeps whatever is already there.
# A full Chromium downloaded by an earlier build would still be collected into
# the bundle, so clear the download directory and let the next step fetch only
# the headless shell.
$Browsers = Join-Path $ProjectRoot '.venv-build\Lib\site-packages\playwright\driver\package\.local-browsers'
if (Test-Path $Browsers) {
    Write-Host "`n== Remove previously downloaded Playwright browsers ==" -ForegroundColor Cyan
    Remove-Item -LiteralPath $Browsers -Recurse -Force
}
Invoke-Checked 'Download bundled Chromium headless shell' { & $Python -m playwright install chromium --only-shell }
Invoke-Checked 'Run automated tests' { & $Python -m unittest discover -s tests -v }

Write-Host "`n== Build standalone CampusNet application ==" -ForegroundColor Cyan
$Icon = Join-Path $ProjectRoot 'src\campusnet\assets\campusnet.ico'
$Hook = Join-Path $ProjectRoot 'packaging\playwright_runtime_hook.py'
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name CampusNet `
    --icon $Icon `
    --runtime-hook $Hook `
    --collect-all playwright `
    --collect-all keyring `
    --collect-all campusnet `
    campusnet_gui_entry.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE. Read the first error above."
}

$Exe = Join-Path $ProjectRoot 'dist\CampusNet\CampusNet.exe'
if (-not (Test-Path $Exe)) {
    throw "Build finished but expected executable was not found: $Exe"
}

# Verify the bundle carries only the browser runtime the desktop app uses.
Write-Host "`n== Verify bundled browser runtime ==" -ForegroundColor Cyan
$DistBrowsers = Join-Path $ProjectRoot 'dist\CampusNet\_internal\playwright\driver\package\.local-browsers'
if (-not (Test-Path $DistBrowsers)) {
    throw "No bundled browser runtime found at $DistBrowsers. The app cannot authenticate without it."
}
# '.links' is Playwright's own bookkeeping directory and is expected.
$Allowed = @('chromium_headless_shell', 'ffmpeg', 'winldd', '.links')
$Found = Get-ChildItem -LiteralPath $DistBrowsers -Directory | Select-Object -ExpandProperty Name
$Unexpected = $Found | Where-Object { $name = $_; -not ($Allowed | Where-Object { $name.StartsWith($_) }) }
if ($Unexpected) {
    throw ("The bundle contains unexpected browser payloads: " + ($Unexpected -join ', ') + ". Delete .venv-build and dist, then rebuild.")
}
if (-not ($Found | Where-Object { $_.StartsWith('chromium_headless_shell') })) {
    throw "The bundled browser runtime is missing the Chromium headless shell."
}
Write-Host ("Bundled browser runtime: " + ($Found -join ', ')) -ForegroundColor Green

$WebEngine = Join-Path $ProjectRoot 'dist\CampusNet\_internal\PySide6\Qt6WebEngineCore.dll'
if (Test-Path $WebEngine) {
    throw "Qt WebEngine was collected into the bundle. Delete .venv-build and dist, then rebuild."
}
Write-Host "`nStandalone build ready: $Exe" -ForegroundColor Green
Write-Host 'Next: test this EXE before creating an installer.' -ForegroundColor Yellow

$IsccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
) | Where-Object { $_ -and (Test-Path $_) }
$Iscc = $IsccCandidates | Select-Object -First 1
if ($Iscc) {
    New-Item -ItemType Directory -Path (Join-Path $ProjectRoot 'installer-output') -Force | Out-Null
    Invoke-Checked 'Compile Windows installer with Inno Setup' { & $Iscc (Join-Path $ProjectRoot 'CampusNet.iss') }
    $Installer = Join-Path $ProjectRoot 'installer-output\CampusNet-Setup-0.5.11.exe'
    if (Test-Path $Installer) {
        Write-Host "`nInstaller ready: $Installer" -ForegroundColor Green
    }
} else {
    Write-Host "`nInno Setup was not detected. The standalone app is built, but the installer has not been created." -ForegroundColor Yellow
    Write-Host 'Install Inno Setup from https://jrsoftware.org/isinfo.php, then open CampusNet.iss and click Compile.'
}
