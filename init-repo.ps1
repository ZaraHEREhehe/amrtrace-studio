<#
  init-repo.ps1  (Step 1 / Z-01)
  Run from the ROOT of the cloned, empty repo.
  Creates the full AMRTrace folder structure, .gitignore, .gitattributes,
  templates, and a data-verification helper. Safe to re-run: existing files are
  skipped unless you pass -Force.

  Usage:
    powershell -ExecutionPolicy Bypass -File .\init-repo.ps1
    powershell -ExecutionPolicy Bypass -File .\init-repo.ps1 -Commit
#>
param(
  [switch]$Force,    # overwrite files that already exist
  [switch]$Commit    # git add + commit when done (does NOT push)
)

$ErrorActionPreference = 'Stop'

# --- sanity checks -----------------------------------------------------------
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$null = git rev-parse --is-inside-work-tree 2>&1
$gitOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEap
if (-not $gitOk) {
  Write-Host "ERROR: run this inside the cloned repo (git clone <url>, then cd into it)." -ForegroundColor Red
  exit 1
}
$root = (Get-Location).Path
$utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Write-File([string]$RelPath, [string]$Content) {
  $full = Join-Path $root $RelPath
  if ((Test-Path $full) -and -not $Force) { Write-Host "  skip   $RelPath (exists)" -ForegroundColor DarkGray; return }
  $dir = Split-Path $full -Parent
  if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
  [System.IO.File]::WriteAllText($full, $Content, $utf8NoBom)
  Write-Host "  write  $RelPath" -ForegroundColor Green
}

# --- 1. directories ----------------------------------------------------------
# Every directory gets a .gitkeep so Git tracks the (otherwise empty) folders.
$dirs = @(
  '.github/workflows', '.github/ISSUE_TEMPLATE',
  'docker',
  'db/migrations',
  'data/raw', 'data/processed', 'data/external', 'data/manifest', 'data/interpretation',
  'scripts',
  'web',
  'tests/unit', 'tests/integration', 'tests/e2e', 'tests/oracle/fixtures', 'tests/fixtures',
  'docs/adr', 'docs/design', 'docs/worksheet'
)
# Python packages (get __init__.py instead of .gitkeep)
$pkgs = @(
  'src/amrtrace', 'src/amrtrace/ingest', 'src/amrtrace/evaluator', 'src/amrtrace/interpretation',
  'src/amrtrace/deps', 'src/amrtrace/ledger', 'src/amrtrace/changes', 'src/amrtrace/changes/differs',
  'src/amrtrace/reeval', 'src/amrtrace/api'
)

Write-Host "`nCreating directories..." -ForegroundColor Cyan
foreach ($d in $dirs) {
  New-Item -ItemType Directory -Path (Join-Path $root $d) -Force | Out-Null
  Write-File "$d/.gitkeep" ""
}
foreach ($p in $pkgs) {
  New-Item -ItemType Directory -Path (Join-Path $root $p) -Force | Out-Null
  Write-File "$p/__init__.py" ""
}

# --- 2. .gitignore (structure is committed, data CONTENTS are not) -----------
Write-Host "`nWriting config files..." -ForegroundColor Cyan
Write-File '.gitignore' @'
# ---- Python ----
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/
*.egg-info/

# ---- Secrets / env (only .env.example is committed) ----
.env
.env.*
!.env.example

# ---- Node / web ----
node_modules/
web/dist/
web/build/

# ---- Docker / local DB volumes ----
pgdata/

# ---- OS / editor ----
.DS_Store
Thumbs.db
.vscode/
.idea/

# ---- DATA: folders are committed (via .gitkeep), file contents are NOT ----
# Put the frozen V1 files in data/raw/, derived files in data/processed/,
# downloaded standards/PDFs in data/external/.
# data/manifest/ and data/interpretation/ ARE committed (small, shared).
data/raw/*
!data/raw/.gitkeep
!data/raw/README.md
data/processed/*
!data/processed/.gitkeep
!data/processed/README.md
data/external/*
!data/external/.gitkeep
!data/external/README.md
'@

Write-File '.gitattributes' @'
* text=auto
*.sh        text eol=lf
*.sql       text eol=lf
Dockerfile  text eol=lf
*.yml       text eol=lf
*.yaml      text eol=lf
'@

Write-File '.env.example' @'
# Copy to .env (never commit .env). Values here are local-dev defaults only.
POSTGRES_USER=amrtrace
POSTGRES_PASSWORD=change_me_locally
POSTGRES_DB=amrtrace
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Where the (uncommitted) data lives, relative to the repo root.
AMRTRACE_DATA_DIR=./data
'@

# --- 3. READMEs that explain WHERE things go ---------------------------------
Write-File 'README.md' @'
# AMRTrace Studio

Version-aware AMR genotype-phenotype discordance investigation and selective
re-evaluation platform. FAST-NUCES FYP.

- Plan, decisions, task board, and live status: see `PROJECT_PLAN.md`
- Setup/run/test/deploy instructions: to be completed in step 40 (README final pass)

## Repository map
| Path | What lives there |
|---|---|
| `src/amrtrace/` | Python backend (ingest, evaluator, interpretation, deps, ledger, changes, reeval, api) |
| `web/` | Client (display + input only) |
| `db/migrations/` | SQL migrations |
| `data/` | Data (see `data/README.md`; raw/processed/external contents are NOT committed) |
| `tests/` | unit, integration, e2e, oracle fixtures, small CI fixtures |
| `docs/` | ADRs, design notes, worksheet, milestone log |
| `scripts/` | Helper scripts (data hashing/verification, graph metrics, genericity guard) |
| `docker/`, `docker-compose.yml` | Containers |

## Rules
- No commits straight to `main`; branch + PR + review (see `PROJECT_PLAN.md` section 8).
- No secrets in the repo.
- Engine packages must stay generic (plan section 3.2, rule 12).
'@

Write-File 'data/README.md' @'
# data/

Everyone must have the SAME layout so paths in code and docs work on every machine.

| Folder | Committed? | Contents |
|---|---|---|
| `data/raw/` | NO (contents ignored) | The frozen V1 files (cases, AST, genotype, mappings, QA outputs) and source snapshots S1/S2. Copy them here exactly as received. |
| `data/processed/` | NO | Anything derived from raw by our scripts (can always be regenerated). |
| `data/external/` | NO | Downloaded references (e.g. CLSI/EUCAST documents, reference-database archives). |
| `data/manifest/` | YES | `sha256.txt` hash list of data/raw so everyone can verify they have identical files; ingest manifests. |
| `data/interpretation/` | YES | Interpretation tables as YAML (data, not code). |

## Keeping data identical across the team
1. Get the frozen files from the shared location the team agrees on (decided in step 2).
2. Put them under `data/raw/` keeping the original file names and any subfolders.
3. Verify: `powershell -ExecutionPolicy Bypass -File .\scripts\data-hash.ps1 -Mode verify`
4. Whoever owns the data regenerates the hash list when files legitimately change:
   `powershell -ExecutionPolicy Bypass -File .\scripts\data-hash.ps1 -Mode generate`
   then commits `data/manifest/sha256.txt`.
'@

Write-File 'data/raw/README.md' "Place the frozen V1 files and source snapshots here (contents are gitignored). See data/README.md.`n"
Write-File 'data/processed/README.md' "Derived/regenerable files go here (contents are gitignored). See data/README.md.`n"
Write-File 'data/external/README.md' "Downloaded references (standards, reference DB archives) go here (contents are gitignored). See data/README.md.`n"

Write-File 'docs/adr/README.md' @'
# Architecture Decision Records
One short file per decision: `ADR-00N-title.md` with Context, Decision, Consequences.
Step 3 (G-01) produces ADR-001 (generic engine / extension points), ADR-002 (interpretation modes),
ADR-003 (schema and data contract), ADR-004 (interfaces).
'@

Write-File 'docs/milestones.md' @'
# Milestone log
Update after every step. Be honest about delays and give a recovery plan.

| Step | Task | Driver | Planned | Actual | Status | Delay reason / recovery plan |
|---|---|---|---|---|---|---|
'@

# --- 4. GitHub templates ------------------------------------------------------
Write-File '.github/CODEOWNERS' @'
# Replace the placeholders with real GitHub usernames (e.g. @zara-noor)
/src/amrtrace/evaluator/        @AABIA_GH
/src/amrtrace/deps/             @AABIA_GH
/src/amrtrace/interpretation/   @INSHARAH_GH
/src/amrtrace/ledger/           @INSHARAH_GH
/src/amrtrace/changes/          @INSHARAH_GH
/src/amrtrace/reeval/           @INSHARAH_GH
/data/interpretation/           @INSHARAH_GH
/db/migrations/                 @INSHARAH_GH
/tests/oracle/                  @INSHARAH_GH
/src/amrtrace/ingest/           @ZARA_GH
/src/amrtrace/api/              @ZARA_GH
/web/                           @ZARA_GH
/.github/                       @ZARA_GH
/docker/                        @ZARA_GH
/docker-compose.yml             @ZARA_GH
/scripts/                       @ZARA_GH
/docs/design/graph*             @AABIA_GH
/docs/adr/                      @INSHARAH_GH
'@

Write-File '.github/pull_request_template.md' @'
## Task
Closes #  | Task ID:

## What changed and why

## How to test (exact commands)

## Evidence (test IDs / screenshots / CI link)

## Checklist
- [ ] Tests added/updated and passing locally
- [ ] No secrets committed
- [ ] No hardcoded drug/organism/standard/edition in engine packages (rule 12)
- [ ] Docstrings/comments on non-obvious logic
- [ ] PROJECT_PLAN.md section 14 status updated
- [ ] LLM assistance used? Describe what and how it was reviewed:
'@

Write-File '.github/ISSUE_TEMPLATE/task.md' @'
---
name: Task
about: One task from PROJECT_PLAN.md
title: "[TASK-ID] short title"
labels: ""
assignees: ""
---

**Task ID / Step:**
**Owner (driver):**
**Reviewer:**
**Depends on:**

**Acceptance / gate (done when):**

**Files to touch:**
'@

# --- 5. data hashing / verification helper -----------------------------------
Write-File 'scripts/data-hash.ps1' @'
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
'@

# --- 6. optional commit -------------------------------------------------------
if ($Commit) {
  git add -A
  git commit -m "Z-01: scaffold repository structure"
  Write-Host "`nCommitted locally. Push with:  git branch -M main ; git push -u origin main" -ForegroundColor Cyan
} else {
  Write-Host "`nDone. Review with 'git status', then commit and push (see below)." -ForegroundColor Cyan
}

Write-Host @"

Next steps for Zara:
  1. Copy PROJECT_PLAN.md (the plan file) into the repo root.
  2. git add -A ; git commit -m "Z-01: scaffold repository structure"   (or rerun with -Commit)
  3. git branch -M main ; git push -u origin main
  4. THEN enable branch protection on main (so this first push isn't blocked).
  5. Replace @AABIA_GH / @INSHARAH_GH / @ZARA_GH in .github/CODEOWNERS with real usernames.
"@
