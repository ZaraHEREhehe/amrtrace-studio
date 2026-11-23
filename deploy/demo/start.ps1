<#
 Z-28 one-command isolated demo startup on Windows PowerShell 5.1+.
 Online first build: build the two locally tagged images and start the complete stack.
 Offline repeat: -Offline requires that all three image tags are already cached.
 No DB deletion, no production volumes, no use of the ordinary docker-compose.yml.
#>
param([switch]$Offline)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$Compose = Join-Path $PSScriptRoot 'compose.yml'
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required for the isolated demo configuration.' }
$LocalConfigDir = Join-Path $env:LOCALAPPDATA 'AMRTraceStudio\z28-demo'
if (-not (Test-Path -LiteralPath $LocalConfigDir)) { [System.IO.Directory]::CreateDirectory($LocalConfigDir) | Out-Null }
$LocalEnv = Join-Path $LocalConfigDir 'config.env'
$Project = 'amrtrace-z28-demo'

function Docker-Run([string[]]$Arguments) {
    # Native Docker emits harmless progress to stderr; rely on its exit code, including on PS 5.1.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker @Arguments
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $prev }
    if ($code -ne 0) { throw "Docker command failed with exit code ${code}: docker $($Arguments -join ' ')" }
}

& docker --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker CLI not available. Install and start Docker Desktop.' }
& docker compose version | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose v2 is required.' }

if (-not (Test-Path -LiteralPath $LocalEnv)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $password = [System.BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
    [System.IO.File]::WriteAllText($LocalEnv, "Z28_DB_PASSWORD=$password`nZ28_WEB_PORT=18080`nZ28_API_PORT=18000`n", (New-Object System.Text.UTF8Encoding($false)))
    Write-Host 'Created demo-only config under LOCALAPPDATA (outside the Git checkout and Docker build context). No hosted API keys are used.'
}
if (-not (Select-String -LiteralPath $LocalEnv -Pattern '^Z28_DB_PASSWORD=[0-9a-f]{64}$' -Quiet)) {
    throw 'Invalid Z-28 environment file. Expected a generated 64-character hex password.'
}

$head = (& git -C $RepoRoot rev-parse --verify HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw 'The demo must be run from a Git checkout.' }
$tag = 'git-' + $head.Substring(0, 12)
$env:Z28_IMAGE_TAG = $tag
$ComposeArgs = @('compose', '-p', $Project, '-f', $Compose, '--env-file', $LocalEnv)
Docker-Run ($ComposeArgs + @('config', '--quiet'))

$ApiTag = "amrtrace-z28-demo-api:$tag"
$WebTag = "amrtrace-z28-demo-web:$tag"
if ($Offline) {
    foreach ($image in @('postgres:16.10-alpine3.22', $ApiTag, $WebTag)) {
        & docker image inspect $image 1>$null 2>$null
        if ($LASTEXITCODE -ne 0) { throw "Offline image missing: $image. Run start.ps1 once with network access to build/cache it." }
    }
    Docker-Run ($ComposeArgs + @('up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '300'))
} else {
    # Rebuild on every online startup so a dirty worktree cannot masquerade as a matching image tag.
    Docker-Run @('build', '-f', (Join-Path $PSScriptRoot 'Dockerfile.api'), '-t', $ApiTag, $RepoRoot)
    Docker-Run @('build', '-f', (Join-Path $PSScriptRoot 'Dockerfile.web'), '-t', $WebTag, $RepoRoot)
    Docker-Run ($ComposeArgs + @('up', '-d', '--no-build', '--wait', '--wait-timeout', '300'))
}
& (Join-Path $PSScriptRoot 'verify.ps1') -ImageTag $tag
if (-not $?) { throw 'Z-28 verification failed.' }
Write-Host 'Z28_DEMO_READY: http://localhost:18080/#/dashboard'
Write-Host 'No normal development containers or database volumes were modified.'
