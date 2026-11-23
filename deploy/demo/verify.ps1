<# Z-28 explicit read-only verification, PowerShell 5.1+. #>
param([string]$ImageTag = '')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$Compose = Join-Path $PSScriptRoot 'compose.yml'
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw 'LOCALAPPDATA is required for the isolated demo configuration.' }
$LocalConfigDir = Join-Path $env:LOCALAPPDATA 'AMRTraceStudio\z28-demo'
if (-not (Test-Path -LiteralPath $LocalConfigDir)) { [System.IO.Directory]::CreateDirectory($LocalConfigDir) | Out-Null }
$LocalEnv = Join-Path $LocalConfigDir 'config.env'
if (-not (Test-Path -LiteralPath $LocalEnv)) { throw 'Z28 local config missing; run start.ps1 first.' }
if (-not $ImageTag) {
    $head = (& git -C $RepoRoot rev-parse --verify HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw 'Git revision unavailable.' }
    $ImageTag = 'git-' + $head.Substring(0,12)
}
$env:Z28_IMAGE_TAG = $ImageTag
$Project = 'amrtrace-z28-demo'
$ArgsBase = @('compose', '-p', $Project, '-f', $Compose, '--env-file', $LocalEnv)

function Docker-Output([string[]]$Arguments) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $out = & docker @Arguments; $code = $LASTEXITCODE }
    finally { $ErrorActionPreference = $prev }
    if ($code -ne 0) { throw "Z28_VERIFY_FAILED: docker $($Arguments -join ' ') returned $code" }
    return ($out | Out-String).Trim()
}
function Check-Exact([string]$Label, [string]$Actual, [string]$Expected) {
    if ($Actual -ne $Expected) { throw "Z28_VERIFY_FAILED: $Label expected $Expected, got $Actual" }
    Write-Host "  PASS $Label = $Actual"
}

$count = Docker-Output ($ArgsBase + @('exec', '-T', 'db', 'psql', '-U', 'postgres', '-d', 'amrtrace_z28', '-Atqc', 'SELECT count(*) FROM "case"'))
$states = Docker-Output ($ArgsBase + @('exec', '-T', 'db', 'psql', '-U', 'postgres', '-d', 'amrtrace_z28', '-Atqc', "SELECT count(*) FROM case_state WHERE release_id='R1'"))
$status = Docker-Output ($ArgsBase + @('exec', '-T', 'db', 'psql', '-U', 'postgres', '-d', 'amrtrace_z28', '-Atqc', "SELECT status FROM release WHERE release_id='R1'"))
$releaseCount = Docker-Output ($ArgsBase + @('exec', '-T', 'db', 'psql', '-U', 'postgres', '-d', 'amrtrace_z28', '-Atqc', 'SELECT count(*) FROM release'))
$stamp = Docker-Output ($ArgsBase + @('exec', '-T', 'db', 'psql', '-U', 'postgres', '-d', 'amrtrace_z28', '-Atqc', 'SELECT count(*) FROM z28_demo_schema_stamp'))
Check-Exact 'case count' $count '660'
Check-Exact 'R1 case_state count' $states '660'
Check-Exact 'R1 release status' $status 'PUBLISHED'
Check-Exact 'release count' $releaseCount '1'
Check-Exact 'migration stamp count' $stamp '1'

# Verify runtime is actually template-only: no Copilot endpoint, model or hosted key.
$keys = Docker-Output ($ArgsBase + @('exec', '-T', 'api', 'python', '-c', "import os; names=['GROQ_API_KEY','AMRTRACE_COPILOT_LOCAL_URL','AMRTRACE_COPILOT_LOCAL_MODEL','AMRTRACE_COPILOT_HOSTED_MODEL']; print('disabled' if all(not os.environ.get(x) for x in names) else 'enabled')"))
Check-Exact 'hosted/local models' $keys 'disabled'

$health = Invoke-RestMethod -Uri 'http://127.0.0.1:18080/api/health' -TimeoutSec 15
if ($health.service -ne 'api' -or $health.status -ne 'ok') { throw 'Z28_VERIFY_FAILED: API health response invalid.' }
Write-Host '  PASS API health through Nginx /api/ proxy'
$web = Invoke-WebRequest -Uri 'http://127.0.0.1:18080/' -UseBasicParsing -TimeoutSec 15
if ($web.StatusCode -ne 200 -or $web.Content -notmatch 'AMRTrace') { throw 'Z28_VERIFY_FAILED: web page unexpected.' }
Write-Host '  PASS web UI returns AMRTrace page'
Write-Host 'Z28_VERIFY_SUCCESS: R1 mini-cohort, API, web, templates-only, schema confirmed.'
