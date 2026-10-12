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

# Playwright documents this mode for bundling browser binaries with PyInstaller.
$env:PLAYWRIGHT_BROWSERS_PATH = '0'
Invoke-Checked 'Upgrade pip' { & $Python -m pip install --upgrade pip }
Invoke-Checked 'Install CampusNet and build tools' { & $Python -m pip install -e . pyinstaller }
Invoke-Checked 'Download bundled Chromium' { & $Python -m playwright install chromium }
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
    --collect-all PySide6 `
    campusnet_gui_entry.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE. Read the first error above."
}

$Exe = Join-Path $ProjectRoot 'dist\CampusNet\CampusNet.exe'
if (-not (Test-Path $Exe)) {
    throw "Build finished but expected executable was not found: $Exe"
}
Write-Host "`nStandalone build ready: $Exe" -ForegroundColor Green
Write-Host 'Next: test this EXE before creating an installer.' -ForegroundColor Yellow

$IsccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
) | Where-Object { $_ -and (Test-Path $_) }
$Iscc = $IsccCandidates | Select-Object -First 1
if ($Iscc) {
    New-Item -ItemType Directory -Path (Join-Path $ProjectRoot 'installer-output') -Force | Out-Null
    Invoke-Checked 'Compile Windows installer with Inno Setup' { & $Iscc (Join-Path $ProjectRoot 'CampusNet.iss') }
    $Installer = Join-Path $ProjectRoot 'installer-output\CampusNet-Setup-0.5.8.exe'
    if (Test-Path $Installer) {
        Write-Host "`nInstaller ready: $Installer" -ForegroundColor Green
    }
} else {
    Write-Host "`nInno Setup was not detected. The standalone app is built, but the installer has not been created." -ForegroundColor Yellow
    Write-Host 'Install Inno Setup from https://jrsoftware.org/isinfo.php, then open CampusNet.iss and click Compile.'
}
