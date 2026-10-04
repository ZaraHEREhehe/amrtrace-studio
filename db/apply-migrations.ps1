<#
  apply-migrations.ps1  (I-01)
  Applies db/migrations/*.sql, in order, to a Postgres running in a Docker container.
  Each file runs in ONE transaction. Applied files are recorded in schema_migration with a hash,
  so a re-run skips them. A file that changed after it was applied is an error (migrations are immutable;
  add a new numbered file instead).

  Usage (from the repo root):
    powershell -ExecutionPolicy Bypass -File .\db\apply-migrations.ps1
    powershell -ExecutionPolicy Bypass -File .\db\apply-migrations.ps1 -Reset   # drops and recreates the database

  CI does the same job with: for f in db/migrations/*.sql; do psql -v ON_ERROR_STOP=1 -1 -f "$f"; done
#>
param(
  [string]$Container = 'amrtrace-pg',
  [string]$Database  = 'amrtrace',
  [string]$User      = 'postgres',
  [switch]$Reset
)

$ErrorActionPreference = 'Stop'
$migrations = Join-Path $PSScriptRoot 'migrations'

function Invoke-Psql([string]$Db, [string[]]$PsqlArgs, [string]$InputText = $null) {
  $all = @('exec', '-i', $Container, 'psql', '-U', $User, '-d', $Db, '-v', 'ON_ERROR_STOP=1', '-X', '-q') + $PsqlArgs
  if ($InputText) { $out = $InputText | & docker @all 2>&1 } else { $out = & docker @all 2>&1 }
  if ($LASTEXITCODE -ne 0) { throw ("psql failed:`n" + ($out | Out-String)) }
  return ($out | Out-String)
}

# 0. container must be running
$running = (& docker ps --filter "name=^/$Container$" --format '{{.Names}}') | Out-String
if (-not $running.Trim()) {
  throw "Container '$Container' is not running. Start it: docker run --name amrtrace-pg -e POSTGRES_PASSWORD=dev -p 5432:5432 -d postgres:16"
}

# 1. database
if ($Reset) {
  Write-Host "Resetting database $Database" -ForegroundColor Yellow
  Invoke-Psql 'postgres' @('-c', "DROP DATABASE IF EXISTS $Database WITH (FORCE)") | Out-Null
}
$exists = (Invoke-Psql 'postgres' @('-tAc', "SELECT 1 FROM pg_database WHERE datname = '$Database'")).Trim()
if ($exists -ne '1') {
  Invoke-Psql 'postgres' @('-c', "CREATE DATABASE $Database") | Out-Null
  Write-Host "Created database $Database" -ForegroundColor Green
}

# 2. tracking table
Invoke-Psql $Database @('-c', 'CREATE TABLE IF NOT EXISTS schema_migration (filename text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())') | Out-Null

# 3. apply each file once
$applied = 0; $skipped = 0
foreach ($file in (Get-ChildItem $migrations -Filter '*.sql' | Sort-Object Name)) {
  $text = [System.IO.File]::ReadAllText($file.FullName)
  $norm = $text -replace "`r`n", "`n"                       # same hash on Windows (CRLF) and Linux (LF)
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($norm)
  $hash = ([System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)) -replace '-', '').ToLower()

  $old = (Invoke-Psql $Database @('-tAc', "SELECT sha256 FROM schema_migration WHERE filename = '$($file.Name)'")).Trim()
  if ($old) {
    if ($old -ne $hash) { throw "$($file.Name) was changed after it was applied. Add a new numbered migration instead (or use -Reset locally)." }
    Write-Host "  skip   $($file.Name)" -ForegroundColor DarkGray
    $skipped++
    continue
  }
  Invoke-Psql $Database @('-1') $norm | Out-Null
  Invoke-Psql $Database @('-c', "INSERT INTO schema_migration (filename, sha256) VALUES ('$($file.Name)', '$hash')") | Out-Null
  Write-Host "  apply  $($file.Name)" -ForegroundColor Green
  $applied++
}
Write-Host "Done. applied: $applied, skipped: $skipped" -ForegroundColor Cyan
