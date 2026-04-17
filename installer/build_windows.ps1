# Build the FDD Firmware Updater .exe for Windows x64.
# Run from the repo root: .\installer\build_windows.ps1
#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

try {
    Write-Host "==> Installing Python dependencies..." -ForegroundColor Cyan
    python -m pip install --upgrade pip pyinstaller
    python -m pip install -e .

    # Copy picotool.exe if available (download from pico-sdk GitHub releases)
    $PicotoolDest = "resources\tools\windows\picotool.exe"
    $PicotoolSrc  = (Get-Command picotool.exe -ErrorAction SilentlyContinue)?.Source
    if ($PicotoolSrc) {
        Copy-Item $PicotoolSrc $PicotoolDest -Force
        Write-Host "    Copied picotool.exe from $PicotoolSrc" -ForegroundColor Green
    } else {
        Write-Warning "picotool.exe not found on PATH. Download from https://github.com/raspberrypi/picotool/releases"
        Write-Warning "and place it at $PicotoolDest before distributing."
    }

    Write-Host "==> Running PyInstaller..." -ForegroundColor Cyan
    python -m PyInstaller installer\fdd_updater.spec --clean --noconfirm

    Write-Host "==> Build output:" -ForegroundColor Cyan
    Get-ChildItem dist\ | Format-Table Name, Length, LastWriteTime

    Write-Host "==> Done. Distributable: dist\FDD Firmware Updater\" -ForegroundColor Green
    Write-Host "    Zip the folder or use Inno Setup for a proper installer." -ForegroundColor Yellow
} finally {
    Pop-Location
}
