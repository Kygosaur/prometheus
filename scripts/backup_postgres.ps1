param(
    [string]$ComposeFile = "compose.production.yaml",
    [string]$OutputDirectory = "backups"
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force $OutputDirectory | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $OutputDirectory "planning-$stamp.sql"
$containerFile = "/tmp/planning-$stamp.sql"
docker compose -f $ComposeFile exec -T postgres pg_dump -U planning -d planning --clean --if-exists --file=$containerFile
docker compose -f $ComposeFile cp "postgres:$containerFile" $target
docker compose -f $ComposeFile exec -T postgres rm -f $containerFile
Write-Host "Backup created: $target"
