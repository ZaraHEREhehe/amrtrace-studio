<#
 Z-28 isolated demo reset. Only the explicitly named Compose project volume is deleted.
 Never call with the ordinary docker-compose.yml or a shared Compose project.
#>
param([switch]$ConfirmDemoReset, [switch]$Offline)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $ConfirmDemoReset) { throw 'Refusing destructive action. Pass -ConfirmDemoReset to reset only the isolated Z-28 demo volume.' }
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required for the isolated demo configuration.' }
$LocalConfigDir = Join-Path $env:LOCALAPPDATA 'AMRTraceStudio\z28-demo'
if (-not (Test-Path -LiteralPath $LocalConfigDir)) { [System.IO.Directory]::CreateDirectory($LocalConfigDir) | Out-Null }
$LocalEnv = Join-Path $LocalConfigDir 'config.env'
if (-not (Test-Path -LiteralPath $LocalEnv)) { throw 'Z28 demo local config missing; refusing unknown database reset.' }
$head = (& git -C $RepoRoot rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw 'Git revision unavailable.' }
$env:Z28_IMAGE_TAG = 'git-' + $head.Substring(0,12)
$project = 'amrtrace-z28-demo'
$compose = Join-Path $PSScriptRoot 'compose.yml'
$ComposeArgs = @('compose', '-p', $project, '-f', $compose, '--env-file', $LocalEnv)
# Ensures this is the expected exact Compose project before deleting its own volume.
$actual = (& docker @($ComposeArgs + @('config', '--format', 'json')) | ConvertFrom-Json).name
if ($LASTEXITCODE -ne 0 -or $actual -ne $project) { throw 'Unexpected Compose project; refusing reset.' }
Write-Warning 'Deleting ONLY the Z-28 demo Compose volumes and re-seeding the 660-case R1 baseline.'
$prev = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try { & docker @($ComposeArgs + @('down', '--volumes')); $code = $LASTEXITCODE }
finally { $ErrorActionPreference = $prev }
if ($code -ne 0) { throw "Z28 reset Docker down failed ($code); refused to start another project." }
& (Join-Path $PSScriptRoot 'start.ps1') -Offline:$Offline
if (-not $?) { throw 'Z-28 reset failed during startup.' }
Write-Host 'Z28_RESET_SUCCESS: isolated demo restored and verified.'
