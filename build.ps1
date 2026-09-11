[CmdletBinding()]
param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Building txt-cleaner standalone executable ===" -ForegroundColor Cyan

# Verify python
try {
    & $Python --version
} catch {
    Write-Error "Python not found. Please ensure Python is installed and in PATH."
}

# Install / verify PyInstaller
Write-Host "Checking PyInstaller..." -ForegroundColor Yellow
& $Python -m pip install --upgrade pyinstaller

# Output directory
$binDir = Join-Path $PSScriptRoot "bin"
if (-not (Test-Path $binDir)) {
    New-Item -ItemType Directory -Path $binDir | Out-Null
}

Write-Host "Compiling with PyInstaller..." -ForegroundColor Yellow
& $Python -m PyInstaller --clean --noconfirm --onefile --name "txt-cleaner" --add-data "rules.json;." clean_txt.py

if (Test-Path "dist/txt-cleaner.exe") {
    Move-Item -Path "dist/txt-cleaner.exe" -Destination (Join-Path $binDir "txt-cleaner.exe") -Force
    Write-Host "Build complete: bin\txt-cleaner.exe" -ForegroundColor Green
} else {
    Write-Error "Build failed: dist\txt-cleaner.exe not found."
}

