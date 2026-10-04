param([ValidateSet('generate','verify')][string]$Mode = 'verify')

$root     = Split-Path $PSScriptRoot -Parent
$raw      = Join-Path $root 'data\raw'
$manifest = Join-Path $root 'data\manifest\sha256.txt'
$utf8     = New-Object System.Text.UTF8Encoding $false

$files = Get-ChildItem $raw -Recurse -File |
  Where-Object { $_.Name -notin @('.gitkeep','README.md') } |
  Sort-Object FullName

$current = @{}
foreach ($f in $files) {
  $rel = $f.FullName.Substring($raw.Length + 1).Replace('\','/')
  $current[$rel] = (Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower()
}

if ($Mode -eq 'generate') {
  $lines = $current.Keys | Sort-Object | ForEach-Object { "$($current[$_])  $_" }
  [System.IO.File]::WriteAllLines($manifest, [string[]]$lines, $utf8)
  Write-Host "Wrote $($lines.Count) hashes to data/manifest/sha256.txt" -ForegroundColor Green
  exit 0
}

# verify
if (-not (Test-Path $manifest) -or (Get-Item $manifest).Length -eq 0) {
  Write-Host "No manifest yet (data/manifest/sha256.txt is missing or empty)." -ForegroundColor Yellow
  exit 1
}
$expected = @{}
Get-Content $manifest | Where-Object { $_.Trim() } | ForEach-Object {
  $parts = $_ -split '\s{2,}', 2
  $expected[$parts[1]] = $parts[0]
}
$problems = 0
foreach ($k in $expected.Keys) {
  if (-not $current.ContainsKey($k))        { Write-Host "MISSING   $k" -ForegroundColor Red; $problems++ }
  elseif ($current[$k] -ne $expected[$k])   { Write-Host "DIFFERENT $k" -ForegroundColor Red; $problems++ }
}
foreach ($k in $current.Keys) {
  if (-not $expected.ContainsKey($k))       { Write-Host "EXTRA     $k (not in manifest)" -ForegroundColor Yellow }
}
if ($problems -eq 0) { Write-Host "OK: data/raw matches the manifest ($($expected.Count) files)." -ForegroundColor Green; exit 0 }
Write-Host "$problems problem(s). Re-copy the files from the shared source." -ForegroundColor Red
exit 1