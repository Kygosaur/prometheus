param(
    [Parameter(Mandatory=$true)][string]$Backup,
    [Parameter(Mandatory=$true)][switch]$IUnderstandThisOverwritesDatabase,
    [string]$ComposeFile = "compose.production.yaml"
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $Backup -PathType Leaf)) { throw "Backup not found: $Backup" }
Set-Location (Split-Path $PSScriptRoot -Parent)
$containerFile = "/tmp/planning-restore.sql"
docker compose -f $ComposeFile cp $Backup "postgres:$containerFile"
docker compose -f $ComposeFile exec -T postgres psql -v ON_ERROR_STOP=1 -U planning -d planning -f $containerFile
docker compose -f $ComposeFile exec -T postgres rm -f $containerFile
Write-Host "Database restored from $Backup"
