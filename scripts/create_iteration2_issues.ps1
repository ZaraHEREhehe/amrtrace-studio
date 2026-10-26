<#
  create_iteration2_issues.ps1
  Creates one GitHub issue per Iteration 2 task (PROJECT_PLAN.md Section 16.2),
  assigned to its owner, labelled by track and priority, under the "Iteration 2"
  milestone, with links to the issues it depends on. Safe to re-run: a task whose
  issue already exists (same [ID] in the title) is skipped.

  Usage (from the repo root, after gh auth login):
    powershell -ExecutionPolicy Bypass -File .\scripts\create_iteration2_issues.ps1 -InsharahLogin <github-username> -DryRun
    powershell -ExecutionPolicy Bypass -File .\scripts\create_iteration2_issues.ps1 -InsharahLogin <github-username>
#>
param(
  [string]$Repo = 'ZaraHEREhehe/amrtrace-studio',
  [string]$AabiaLogin = 'AabiaAli',
  [string]$ZaraLogin = 'ZaraHEREhehe',
  [Parameter(Mandatory = $true)][string]$InsharahLogin,
  [string]$MilestoneTitle = 'Iteration 2',
  [string]$MilestoneDue = '2026-11-30T23:59:59Z',
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding $false

# the tasks below are copied from PROJECT_PLAN.md Section 16.2; keep the two in step
$tasks = @(
  @{ Id = 'A-17'; Name = 'Release safety'; Description = 'a baseline release (R1 or a new full release) stays DRAFT until its dependency graph is stored and checked; only then is it PUBLISHED'; Owner = 'Aabia'; Reviewer = 'Insharah'; DependsOn = @(); Priority = 'Must'; Week = 'W1'; Acceptance = 'Failure test: a graph step that fails leaves the release DRAFT and nothing selectable against it; existing chain tests still pass' },
  @{ Id = 'I-15'; Name = 'Mapping differ'; Description = 'compares two mapping versions and lists added, retired and newly linked determinant-antibiotic pairs (C1, C2, C7)'; Owner = 'Insharah'; Reviewer = 'Aabia'; DependsOn = @(); Priority = 'Must'; Week = 'W1'; Acceptance = 'Registered without editing registry code; C1, C2 and C7 fixtures produce the same changed entities as the hand-declared events; genericity guard passes' },
  @{ Id = 'Z-21'; Name = 'Exports page'; Description = 'for the existing as-of export (UC-5): choose a release, download JSON, show the snapshot hash'; Owner = 'Zara'; Reviewer = 'Aabia'; DependsOn = @(); Priority = 'Must'; Week = 'W1'; Acceptance = 'Export from the UI matches the API export byte for byte; web tests' },
  @{ Id = 'I-16'; Name = 'Evidence change types C3 and C4'; Description = 'typed events for a corrected phenotype and a changed genotype set, with differs over evidence versions and oracle fixtures (written by Insharah, not the selector author, D-10)'; Owner = 'Insharah'; Reviewer = 'Aabia'; DependsOn = @('I-15'); Priority = 'Must'; Week = 'W1-W2'; Acceptance = 'Invalid events rejected; fixtures committed before the selector runs against them' },
  @{ Id = 'A-12'; Name = 'Selector for evidence changes'; Description = 'reverse reachability from changed AST and genotype evidence nodes, including declared derivatives'; Owner = 'Aabia'; Reviewer = 'Insharah'; DependsOn = @('I-16'); Priority = 'Must'; Week = 'W2'; Acceptance = 'C3 and C4 oracle recall 100%; precision and reprocessing ratio reported; selective equals exhaustive' },
  @{ Id = 'I-18'; Name = 'Unverified label and review queue'; Description = 'a case whose label was changed by interpretation (`labels_changed` > 0) and has no review on its current published state is UNVERIFIED; reviewers confirm or correct it with the existing append-only reviews'; Owner = 'Insharah'; Reviewer = 'Zara'; DependsOn = @(); Priority = 'Must'; Week = 'W2'; Acceptance = 'API returns the verification status and a queue; confirming or correcting appends a review and never edits a state; tests for both paths' },
  @{ Id = 'Z-16'; Name = 'Register forms for every change type in Change Events, with the API validation errors shown next to the field'; Description = ''; Owner = 'Zara'; Reviewer = 'Aabia'; DependsOn = @('I-15', 'I-16'); Priority = 'Must'; Week = 'W2-W3'; Acceptance = 'Each type registers end to end from the UI; web tests cover each form; a rejected event shows the 422 reason' },
  @{ Id = 'A-13'; Name = 'Change Detection Engine, part 1'; Description = 'the watcher registry and the NCBI Pathogen Detection snapshot watcher (download, manifest and hash check, compare through the registered differs, draft events). Runs on demand ("check now") and optionally on a schedule'; Owner = 'Aabia'; Reviewer = 'Zara'; DependsOn = @('I-15', 'I-16'); Priority = 'Must'; Week = 'W2-W3'; Acceptance = 'Replay test on two stored snapshots drafts the expected events and nothing else; a failed pull drafts nothing; no engine package changed' },
  @{ Id = 'Z-17'; Name = 'Review queue page'; Description = 'with the unverified badge in the explorer and the dossier'; Owner = 'Zara'; Reviewer = 'Insharah'; DependsOn = @('I-18'); Priority = 'Must'; Week = 'W3'; Acceptance = 'Queue filters by drug and state; confirm and correct work end to end; web tests' },
  @{ Id = 'A-18'; Name = 'Change Detection Engine, part 2'; Description = 'AMRFinderPlus software and database watcher (drafts tool-version and mapping events) and breakpoint-standard watcher (raises an alert for a new edition; a person enters the licensed table and the existing interpretation differ drafts the event)'; Owner = 'Aabia'; Reviewer = 'Insharah'; DependsOn = @('A-13'); Priority = 'Must'; Week = 'W3'; Acceptance = 'A new tool or database version drafts the expected events; a new edition raises an alert; loading its table drafts the expected interpretation event' },
  @{ Id = 'I-19'; Name = 'Review Copilot'; Description = 'a plain-language summary of why a case changed, built only from the stored diff, dependency subgraph and evidence; templates first, then an optional language-model layer (D-27); shown in the dossier, labelled as generated, stored apart from evidence'; Owner = 'Insharah'; Reviewer = 'Aabia'; DependsOn = @('I-18'); Priority = 'Must'; Week = 'W3-W4'; Acceptance = 'Test proves the copilot output is never read by the evaluator, selector or release gate (rule 9); every sentence links back to a stored record; works with no network (templates)' },
  @{ Id = 'Z-18'; Name = 'Roles and Admin page'; Description = 'Analyst, Reviewer and Admin (D-26); accounts created by an admin script; the Admin page lists users and their roles. The acting user is stored on every change, run and review'; Owner = 'Zara'; Reviewer = 'Insharah'; DependsOn = @('Z-16', 'Z-17'); Priority = 'Must'; Week = 'W3-W4'; Acceptance = 'Write endpoints return 403 for the wrong role; tests per role; no secrets in the repo (rule 10)' },
  @{ Id = 'A-14'; Name = 'Triage ranking'; Description = 'a fixed, documented ordering of an impact set for review (newly discordant, then state changed, then label changed, then re-verified; ties by case ID) with the reason shown (D-28)'; Owner = 'Aabia'; Reviewer = 'Insharah'; DependsOn = @('I-18'); Priority = 'Must'; Week = 'W4'; Acceptance = 'Same inputs give the same order; reason shown per case; API sort option and UI column' },
  @{ Id = 'A-16'; Name = 'Granularity ablation (B3, OD-8)'; Description = 'a coarse dependency model behind the existing config flag, compared with the fine graph'; Owner = 'Aabia'; Reviewer = 'Insharah'; DependsOn = @('A-12'); Priority = 'Must'; Week = 'W4'; Acceptance = '`docs/design/ablation.md` with selected counts, precision and reprocessing for CLSI-REAL, VET01S, C2, C6 and C7 under both models' },
  @{ Id = 'G-09'; Name = 'Panel comments (OD-9)'; Description = 'visual components (a state-transition chart across releases and an impact overview) and a note on the research contribution through data categorisation and link discovery'; Owner = 'Zara (visuals), Aabia (note)'; Reviewer = 'Insharah'; DependsOn = @('A-16'); Priority = 'Must'; Week = 'W4-W5'; Acceptance = 'Visuals on the dashboard and dossier; note in `docs/design/`; panel-actions table updated' },
  @{ Id = 'A-15'; Name = 'Remaining dependency types'; Description = 'contradiction, composite and alternative-support materialised and followed by the selector'; Owner = 'Aabia'; Reviewer = 'Insharah'; DependsOn = @('A-12'); Priority = 'Should'; Week = 'W5'; Acceptance = 'Synthetic fixtures for each type pass with recall 100%; `docs/design/graph_design.md` updated. If cut, stated as a limitation' },
  @{ Id = 'I-17'; Name = 'C5 rule policy revised (intermediate or missing values)'; Description = 'typed event, differ and oracle fixture'; Owner = 'Insharah'; Reviewer = 'Aabia'; DependsOn = @('I-16'); Priority = 'Should'; Week = 'W5'; Acceptance = 'Fixture passes with recall 100%; selective equals exhaustive' },
  @{ Id = 'Z-20'; Name = 'Deployment refresh'; Description = 'the D-22 database and the Iteration 2 build on the deployed instance; date decided by the team'; Owner = 'Zara'; Reviewer = 'Aabia'; DependsOn = @('Z-18'); Priority = 'Could'; Week = 'W5'; Acceptance = 'Deployed health checks pass; demo case opens on the deployed instance' },
  @{ Id = 'G-11'; Name = 'Iteration 2 close-out'; Description = 'tag, clean CI run, demo rehearsal, report and milestone updates'; Owner = 'Insharah'; Reviewer = 'Zara'; DependsOn = @(); Priority = 'Must'; Week = 'W5'; Acceptance = 'Tag exists; rehearsal checklist done by all three; report and `docs/milestones.md` updated' }
)

# the close-out waits for every Must task, so we fill its dependency list here
$closeOut = $tasks | Where-Object { $_.Id -eq 'G-11' }
$closeOut.DependsOn = @($tasks | Where-Object { $_.Priority -eq 'Must' -and $_.Id -ne 'G-11' } | ForEach-Object { $_.Id })

$logins = @{ 'Aabia' = $AabiaLogin; 'Zara' = $ZaraLogin; 'Insharah' = $InsharahLogin }
$weeks = @{ 'W1' = '27 Oct - 2 Nov'; 'W2' = '3 - 9 Nov'; 'W3' = '10 - 16 Nov'; 'W4' = '17 - 23 Nov'; 'W5' = '24 - 30 Nov' }

# picks every team member named in an owner text such as "Zara (visuals), Aabia (note)"
function Get-People([string]$Text) {
  return @($logins.Keys | Where-Object { $Text -match $_ })
}

# the track label follows the owner, so a shared task gets one label per person
function Get-TrackLabels([string[]]$People) {
  $map = @{ 'Aabia' = 'track-A'; 'Insharah' = 'track-B'; 'Zara' = 'track-C' }
  return @($People | ForEach-Object { $map[$_] })
}

# runs gh, or only prints the command when this is a dry run
function Invoke-Gh([string[]]$GhArgs) {
  if ($DryRun) {
    Write-Host ('  gh ' + ($GhArgs -join ' ')) -ForegroundColor DarkGray
    return ''
  }
  $output = & gh @GhArgs
  if ($LASTEXITCODE -ne 0) { throw "gh failed: gh $($GhArgs -join ' ')" }
  return $output
}

# gh must be installed and signed in before anything else happens
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$null = gh auth status 2>&1
$ghOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEap
if (-not $ghOk) {
  Write-Host 'ERROR: run "gh auth login" first (GitHub CLI must be installed and signed in).' -ForegroundColor Red
  exit 1
}

Write-Host "`nLabels..." -ForegroundColor Cyan
$labels = @(
  @{ Name = 'iteration-2'; Color = '1C7293'; Desc = 'Iteration 2 task (PROJECT_PLAN.md Section 16)' },
  @{ Name = 'track-A'; Color = '6366F1'; Desc = 'Track A: Aabia' },
  @{ Name = 'track-B'; Color = '16A34A'; Desc = 'Track B: Insharah' },
  @{ Name = 'track-C'; Color = 'C9622A'; Desc = 'Track C: Zara' },
  @{ Name = 'priority-must'; Color = 'DC2626'; Desc = 'Needed for the final evaluation' },
  @{ Name = 'priority-should'; Color = 'D97706'; Desc = 'Planned; cut only with team agreement' },
  @{ Name = 'priority-could'; Color = '9CA3AF'; Desc = 'Only if time remains' }
)
foreach ($label in $labels) {
  # --force updates a label that already exists instead of failing
  Invoke-Gh @('label', 'create', $label.Name, '--repo', $Repo, '--color', $label.Color, '--description', $label.Desc, '--force') | Out-Null
  Write-Host "  label  $($label.Name)" -ForegroundColor Green
}

Write-Host "`nMilestone..." -ForegroundColor Cyan
$milestones = @()
if (-not $DryRun) {
  $milestones = (& gh api "repos/$Repo/milestones?state=all&per_page=100") | ConvertFrom-Json
}
if ($milestones | Where-Object { $_.title -eq $MilestoneTitle }) {
  Write-Host "  skip   $MilestoneTitle (exists)" -ForegroundColor DarkGray
} else {
  Invoke-Gh @('api', "repos/$Repo/milestones", '--method', 'POST', '-f', "title=$MilestoneTitle", '-f', "due_on=$MilestoneDue", '-f', 'description=PROJECT_PLAN.md Section 16') | Out-Null
  Write-Host "  create $MilestoneTitle (due $MilestoneDue)" -ForegroundColor Green
}

# issues that already exist are found by the [ID] at the start of their title
$existing = @{}
if (-not $DryRun) {
  $all = (& gh issue list --repo $Repo --state all --limit 1000 --json number,title) | ConvertFrom-Json
  foreach ($issue in $all) {
    if ($issue.title -match '^\[([AIZG]-\d+)\]') { $existing[$Matches[1]] = $issue.number }
  }
}

# writes the issue text; dependencies become issue links once every number is known
function Get-Body($Task, $Numbers) {
  $deps = 'none'
  if ($Task.DependsOn.Count -gt 0) {
    $deps = ($Task.DependsOn | ForEach-Object {
      if ($Numbers.ContainsKey($_)) { "#$($Numbers[$_]) ($_)" } else { $_ }
    }) -join ', '
  }
  $lines = @(
    "**Task:** $($Task.Name): $($Task.Description)",
    '',
    "| Field | Value |",
    "| ----- | ----- |",
    "| Plan ID | $($Task.Id) (PROJECT_PLAN.md Section 16.2) |",
    "| Owner | $($Task.Owner) |",
    "| Reviewer | $($Task.Reviewer) |",
    "| Depends on | $deps |",
    "| Priority | $($Task.Priority) |",
    "| Target week | $($Task.Week) ($(($Task.Week.Split('-') | ForEach-Object { $weeks[$_] }) -join ' to ')) |",
    '',
    "**Done when:** $($Task.Acceptance)",
    '',
    'Start only when every issue under "Depends on" is closed. Link the PR with "Closes #<this issue>" and update Section 16.4 in the same PR.'
  )
  return ($lines -join "`n")
}

Write-Host "`nIssues..." -ForegroundColor Cyan
$numbers = @{}
foreach ($key in $existing.Keys) { $numbers[$key] = $existing[$key] }
$created = @()

foreach ($task in $tasks) {
  if ($existing.ContainsKey($task.Id)) {
    Write-Host "  skip   [$($task.Id)] (issue #$($existing[$task.Id]) exists)" -ForegroundColor DarkGray
    continue
  }

  $people = Get-People "$($task.Owner) $(if ($task.Id -eq 'G-11') { 'Aabia Zara Insharah' })"
  $labelList = @('iteration-2', "priority-$($task.Priority.ToLower())") + (Get-TrackLabels $people)
  $assignees = ($people | ForEach-Object { $logins[$_] }) -join ','
  $title = "[$($task.Id)] $($task.Name)"

  # the body goes through a file so long text and symbols survive the command line
  $bodyFile = [System.IO.Path]::GetTempFileName()
  [System.IO.File]::WriteAllText($bodyFile, (Get-Body $task $numbers), $utf8NoBom)

  $url = Invoke-Gh @('issue', 'create', '--repo', $Repo, '--title', $title, '--body-file', $bodyFile,
    '--assignee', $assignees, '--label', ($labelList -join ','), '--milestone', $MilestoneTitle)
  Remove-Item $bodyFile

  if (-not $DryRun) {
    # gh prints the new issue's URL last, and the number is its final part
    $numbers[$task.Id] = [int](($url | Select-Object -Last 1).Trim().Split('/')[-1])
    $created += $task
  }
  Write-Host "  create $title -> $assignees" -ForegroundColor Green
}

# second pass: now that every issue has a number, rewrite the bodies with real links
if ($created.Count -gt 0) {
  Write-Host "`nLinking dependencies..." -ForegroundColor Cyan
  foreach ($task in $created) {
    if ($task.DependsOn.Count -eq 0) { continue }
    $bodyFile = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($bodyFile, (Get-Body $task $numbers), $utf8NoBom)
    Invoke-Gh @('issue', 'edit', "$($numbers[$task.Id])", '--repo', $Repo, '--body-file', $bodyFile) | Out-Null
    Remove-Item $bodyFile
    Write-Host "  link   [$($task.Id)] #$($numbers[$task.Id])" -ForegroundColor Green
  }
}

Write-Host "`nDone. $($created.Count) issue(s) created." -ForegroundColor Cyan
