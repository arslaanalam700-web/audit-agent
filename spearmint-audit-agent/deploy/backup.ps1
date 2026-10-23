# Nightly backup of the audit database, reports, and the Hermes home folder.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$stamp = Get-Date -Format "yyyyMMdd"
$dest = Join-Path $root "data\backups\$stamp"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$db = Join-Path $root "data\audits.db"
if (Test-Path $db) { Copy-Item $db $dest }
$reports = Join-Path $root "reports"
if (Test-Path $reports) { Compress-Archive -Path $reports -DestinationPath (Join-Path $dest "reports.zip") -Force }
$hermes = Join-Path $env:USERPROFILE ".hermes"
if (Test-Path $hermes) { Compress-Archive -Path $hermes -DestinationPath (Join-Path $dest "hermes-home.zip") -Force }
Get-ChildItem (Join-Path $root "data\backups") -Directory | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } | Remove-Item -Recurse -Force
Write-Output "Backup written to $dest"
