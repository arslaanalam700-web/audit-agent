# Install Hermes if it is missing, then copy the Spearmint audit profiles
# into the Windows Hermes home (%LOCALAPPDATA%\hermes\profiles).
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$hermesExe = Join-Path $env:LOCALAPPDATA "hermes\bin\hermes.exe"
$hermes = Get-Command hermes -ErrorAction SilentlyContinue
if ($hermes) {
    $hermesExe = $hermes.Source
} elseif (-not (Test-Path $hermesExe)) {
    Write-Output "Hermes is not installed. Running the official installer..."
    iex (irm https://hermes-agent.nousresearch.com/install.ps1)
    if (-not (Test-Path $hermesExe)) {
        Write-Output "Installer finished but hermes.exe is still missing. Open a new terminal and run this script again."
        exit 1
    }
}

$env:HERMES_EXE = $hermesExe
python hermes\build_profiles.py --install
Write-Output "Profiles are in $env:LOCALAPPDATA\hermes\profiles."
Write-Output "Set OPENROUTER_API_KEY in each profile .env (or run: hermes -p lead model), then: hermes -p lead gateway start"
