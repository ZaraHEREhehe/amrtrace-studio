# AMRTrace Studio

**AMRTrace Studio** is a version-aware research platform for investigating antimicrobial resistance (AMR) genotype–phenotype discordance. It links case conclusions to supporting evidence and rule versions, records changes and reviews, identifies affected cases, and compares selective against exhaustive re-evaluation.

This FAST-NUCES Final Year Project is a research prototype, **not a clinical decision-support system**. Scope, decisions, responsibilities and progress are recorded in [PROJECT_PLAN.md](PROJECT_PLAN.md).

## 1. Prerequisites

These instructions use **Windows PowerShell**, the team's development environment.

- **Git** for version control.
- **Docker Desktop** running Linux containers, with Docker Compose v2.
- **Python 3.12** for data loading and Python tests.
- **Node.js 22** for frontend tests.

The included 660-case test dataset can be used without Azure credentials or the private frozen research dataset.

## 2. Local setup

### Clone the repository

Open PowerShell from your preferred development directory:

~~~powershell
git clone https://github.com/ZaraHEREhehe/amrtrace-studio.git
cd amrtrace-studio
~~~

### Configure the local environment

~~~powershell
Copy-Item .env.example .env
~~~

The example configuration contains development-only values, including a PostgreSQL password of `dev`. Change these for any shared environment, never commit `.env`, and never use the example credentials in production.

### Start all services

Start Docker Desktop, then run:

~~~powershell
docker compose up -d --build
docker compose ps
~~~

| Service | Technology | Local address |
|---|---|---|
| Frontend | Nginx and JavaScript | http://localhost:8080 |
| Backend API | Python and FastAPI | http://localhost:8000 |
| Database | PostgreSQL 16 | localhost:5433 |

The frontend proxies `/api/` requests to the backend. Verify API liveness:

~~~powershell
Invoke-RestMethod http://localhost:8080/api/health
~~~

Expected response:

~~~json
{"service":"api","status":"ok"}
~~~

**Important:** Docker Compose creates an **empty** development database. It does not automatically apply schema migrations, load cases or publish a baseline release. A healthy API does not necessarily mean case records are available.

## 3. Initialize the local database

Only perform these steps on a **new, empty development database**; never run them against Azure production.

### Apply the SQL migrations

From the project root in PowerShell:

~~~powershell
Get-ChildItem .\db\migrations\*.sql | Sort-Object Name | ForEach-Object {
    Write-Host "Applying $($_.Name)"
    Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 |
        docker compose exec -T db psql -X -v ON_ERROR_STOP=1 -1 -U postgres -d amrtrace -f -
    if ($LASTEXITCODE -ne 0) { throw "Migration failed: $($_.Name)" }
}
~~~

These scripts create source records, case-state/release ledgers, dependency graph structures, change/review records, re-evaluation reports and integrity safeguards. Run migrations **only once on a fresh database**: these scripts are not automatically tracked or designed to be safely repeated.

### Create a Python virtual environment

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r requirements-api-test.txt
~~~

Set the host-side connection environment variables (adjust them if you customized `.env`):

~~~powershell
$env:AMRTRACE_PG_HOST = "127.0.0.1"
$env:AMRTRACE_PG_PORT = "5433"
$env:AMRTRACE_PG_USER = "postgres"
$env:AMRTRACE_PG_PASSWORD = "dev"
$env:AMRTRACE_PG_DBNAME = "amrtrace"
$env:PYTHONPATH = "src"
~~~

The Docker-based API already has its own database settings. These variables allow Python commands running on Windows to access the same local PostgreSQL server.

### Load the included 660-case mini-cohort

The committed fixture is described in [tests/fixtures/mini_cohort/README.md](tests/fixtures/mini_cohort/README.md). It does **not** require the uncommitted frozen V1 files.

~~~powershell
.\.venv\Scripts\python.exe scripts/make_fixture.py load-db
Invoke-RestMethod "http://localhost:8080/api/cases?limit=1"
~~~

The loader imports sample source records and creates the baseline `R1` release with **660 case states**. Open **http://localhost:8080** to inspect the case interface.

The mini-cohort supports local development and CI, not full-cohort research reproduction. Views requiring additional releases, change events, reviewer actions or comparison runs will only contain results when those records exist.

## 4. Optional full research dataset

The frozen V1 files are **not stored in Git**. See [data/README.md](data/README.md) for the project layout:

| Directory | Contents |
|---|---|
| `data/raw/` | Uncommitted frozen inputs and source snapshots |
| `data/processed/` | Uncommitted derived outputs |
| `data/external/` | Uncommitted external references |
| `data/manifest/` | Committed SHA-256 manifests |
| `data/interpretation/` | Committed interpretation tables |

Obtain the approved source files from the team's authorized location and preserve their relative paths in `data/raw/`. Verify them:

~~~powershell
powershell -ExecutionPolicy Bypass -File .\scripts\data-hash.ps1 -Mode verify
~~~

Do not regenerate the committed manifest to disguise a mismatch. Use a **separate, freshly migrated local database** for the full dataset; do not mix it with the mini-cohort. With appropriate `AMRTRACE_PG_*` variables and `PYTHONPATH=src`, load the frozen source tables using:

~~~powershell
.\.venv\Scripts\python.exe -m amrtrace.ingest.load_frozen_v1
~~~

This command loads source tables only. The full baseline-state release must also be produced through the separate project ingestion/baseline procedure; the mini-cohort demonstration does not claim full-data reproduction.

## 5. Automated tests

Run these from the repository root using the Python environment and local PostgreSQL variables above. PostgreSQL-backed tests create temporary test databases, separate from the local demonstration records.

### Unit tests

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/unit -q
~~~

### PostgreSQL integration tests

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/integration -m "not golden" -q
~~~

### Independent selector oracle tests

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/oracle -q
~~~

### Selective-versus-exhaustive end-to-end tests

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/e2e -q
~~~

### Genericity verification

~~~powershell
.\.venv\Scripts\python.exe scripts/check_genericity.py
~~~

### Frontend tests

~~~powershell
$webTests = @(Get-ChildItem .\web\tests\*.test.mjs | ForEach-Object { $_.FullName })
node --test $webTests
~~~

CI is defined in [.github/workflows/ci.yml](.github/workflows/ci.yml), covering lint, genericity, frontend, database-backed unit/integration, oracle/equivalence and Docker tests. The golden test requires uncommitted frozen V1 data; database-dependent tests may skip without a reachable PostgreSQL server. **Skipped tests are not evidence of passed database behavior.**

## 6. Troubleshooting and stopping locally

~~~powershell
docker compose ps
docker compose logs --tail=100 api web db
docker compose down
~~~

If the browser loads but case queries fail, verify migrations and mini-cohort loading. `/health` is an API **liveness** check, not a database-readiness test. If PostgreSQL is unreachable, check Docker Desktop and match `AMRTRACE_PG_PORT` to the host `POSTGRES_PORT` in `.env`.

`docker compose down` retains the named PostgreSQL data volume. **Do not append `--volumes` unless you intentionally want to delete your local database contents.** For occupied host ports, adjust the local host-port values in `.env`.

## 7. Production deployment (Z-12)

**Protected Azure demo:** https://20-205-38-46.sslip.io

The production system runs API and web containers on an Azure Ubuntu VM; Azure Database for PostgreSQL is accessed over a private network. Caddy supplies HTTPS and password protection. The [GitHub Actions publishing workflow](.github/workflows/cd.yml) builds commit-tagged images in GHCR after reviewed changes reach `main` (or configured version tags). A VM systemd timer checks `main` roughly every 10 minutes, deploys matching images, and verifies application health.

Production uses [deploy/compose.ghcr.yml](deploy/compose.ghcr.yml) and separate protected runtime credentials. **Never use the development `docker-compose.yml` on the production host:** it would start an unintended local PostgreSQL service.

For setup requirements, health checks, security boundaries, deployment/rollback and recovery procedures, read the [Z-12 deployment and rollback runbook](docs/deployment_z12.md). Do not place database passwords, login credentials or dataset files in Git.

## 8. Rollback and recovery

The system tracks active, last-known-good and previous successful application image tags. On Azure, a **read-only preflight** is:

~~~bash
sudo /usr/local/sbin/amrtrace-z12-rollback --check
~~~

A real manual rollback uses:

~~~bash
sudo /usr/local/sbin/amrtrace-z12-rollback --apply
~~~

**`--apply` restarts production containers:** only run it during approved recovery or testing. The script restores the previous successful application release; moving back to the newer reviewed release requires the separate manual restore procedure proposed in [PR #113](https://github.com/ZaraHEREhehe/amrtrace-studio/pull/113), pending approval and merge. **Application image rollback does not revert PostgreSQL schema or data.**

The October 10, 2026 verification recorded automatic main deployment, byte-matching VM scripts, an observed healthy V2-to-V1 transition, and restoration of V2 with three successful health checks. The first rollback transcript did **not** retain the explicit `ROLLBACK_REDEPLOY_VERIFIED` line; the runbook states that evidence limitation.

## 9. Repository map

| Path | Responsibility |
|---|---|
| `src/amrtrace/` | Python evaluator, ingestion, interpretations, dependencies, ledger, changes, re-evaluation and API |
| `src/amrtrace/api/` | FastAPI cases, changes, dossier/review and runs endpoints |
| `web/` | Browser UI and Node tests |
| `db/migrations/` | Ordered PostgreSQL schemas and integrity protections |
| `data/` | Hash manifests and interpretation tables, plus uncommitted input/derived files |
| `tests/fixtures/mini_cohort/` | Committed, deterministic 660-case sample |
| `tests/unit/`, `tests/integration/`, `tests/oracle/`, `tests/e2e/` | Unit, database, independent oracle and end-to-end checks |
| `scripts/` | Data verification, fixture generation, genericity, metrics and deploy helpers |
| `docker/`, `docker-compose.yml` | Local API/web/database container setup |
| `deploy/` | Production Compose and systemd definitions |
| `.github/workflows/` | CI and image publishing |
| `docs/`, `PROJECT_PLAN.md` | Architecture decisions, milestones, runbooks, evidence and review process |

## 10. Project safeguards and limitations

- Contribute on feature branches through reviewed pull requests; do not commit directly to `main`.
- Never commit production secrets, local `.env` values, database dumps or uncommitted full datasets.
- Core evaluation and dependency-selection behavior must stay independent of hard-coded organism, antibiotic or rule-edition cases; the genericity guard checks that boundary.
- The 660-case fixture is a reproduction sample, not full-cohort research validation.
- This is not a clinically validated diagnostic tool. The protected demo has perimeter authentication, not a full multi-user authorization system.

**AI assistance:** ChatGPT and Claude were used for technical guidance, troubleshooting, and documentation support.
