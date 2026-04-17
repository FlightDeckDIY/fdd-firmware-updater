# Build the FDD Firmware Updater Windows installer with Inno Setup.
# Run from the repo root: .\installer\build_windows_installer.ps1
#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$SkipAppBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DistDir = Join-Path $RepoRoot "dist\FDD Firmware Updater"
$AppExe = Join-Path $DistDir "FDD Firmware Updater.exe"
$IssFile = Join-Path $PSScriptRoot "fdd_updater.iss"

function Get-ProjectVersion {
    $Pyproject = Join-Path $RepoRoot "pyproject.toml"
    $VersionLine = Select-String -Path $Pyproject -Pattern '^\s*version\s*=\s*"([^"]+)"' | Select-Object -First 1
    if (-not $VersionLine) {
        throw "Could not read project version from $Pyproject"
    }
    return $VersionLine.Matches[0].Groups[1].Value
}

function Get-InnoCompiler {
    $FromPath = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($FromPath) {
        return $FromPath.Source
    }

    $Candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    foreach ($Candidate in $Candidates) {
        if (Test-Path $Candidate) {
            return $Candidate
        }
    }

    throw "Inno Setup 6 compiler (ISCC.exe) was not found. Install Inno Setup 6 or add ISCC.exe to PATH."
}

Push-Location $RepoRoot
try {
    if (-not $SkipAppBuild) {
        & (Join-Path $PSScriptRoot "build_windows.ps1")
    }

    if (-not (Test-Path $AppExe)) {
        throw "Missing PyInstaller app at '$AppExe'. Run .\installer\build_windows.ps1 first, or omit -SkipAppBuild."
    }

    $Version = Get-ProjectVersion
    $Iscc = Get-InnoCompiler

    Write-Host "==> Running Inno Setup..." -ForegroundColor Cyan
    & $Iscc "/DAppVersion=$Version" $IssFile

    $Installer = Join-Path $RepoRoot "dist\FDD-Firmware-Updater-Windows-Setup-$Version.exe"
    if (-not (Test-Path $Installer)) {
        throw "Expected installer was not created: $Installer"
    }

    Write-Host "==> Done. Installer: $Installer" -ForegroundColor Green
} finally {
    Pop-Location
}
