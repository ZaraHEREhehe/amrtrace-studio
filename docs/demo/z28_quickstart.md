# Z-28 — one-page isolated final-demo quickstart (Windows)

**Prerequisites:** Git checkout of the reviewed build, Docker Desktop with Compose v2, Windows PowerShell 5.1+. First setup needs Internet to download `postgres:16.10-alpine3.22` and build two images using pinned base tags and Python packages. After images are cached, the same demo can launch offline. No GROQ or other API key is required.

Open PowerShell at the **repository root**. Run the single startup command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\deploy\demo\start.ps1"
```

The command generates a local config under `%LOCALAPPDATA%\AMRTraceStudio\z28-demo\config.env` containing a random database password, builds the demo API/web images tagged `git-<12-char HEAD>`, starts PostgreSQL, applies schema migrations on the demo-only volume, verifies the committed mini-cohort SHA256 manifest, seeds and publishes release R1 using the existing fixture loader, then checks the web/API. **Do not use the root `docker-compose.yml` or the normal database reset script for this demo.**

**URLs:** Dashboard `http://localhost:18080/#/dashboard`; API health through web `http://localhost:18080/api/health`; API direct `http://localhost:18000/health`. Database has **no host-exposed port**. Expected evidence: `Z28_VERIFY_SUCCESS`, exactly **660 cases**, **660 R1 case states**, one **PUBLISHED R1** release, and template-only Copilot. This mini-cohort contains only four of the five case states; it does not reproduce 41,858-case D-22 views or the full release R2–R8 history.

**Offline rehearsal:** After a successful first build and cached images, disconnect from the network and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\deploy\demo\start.ps1" -Offline
```

**Read-only verification** (run any time):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\deploy\demo\verify.ps1"
```

**Reset just this demo** (explicit opt-in; permanently deletes only this demo's database volume and seeds R1 again):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\deploy\demo\reset.ps1" -ConfirmDemoReset -Offline
```

The reset is refused without `-ConfirmDemoReset`. It never uses the normal database's Compose project or volume. For shutdown **without deleting demo data**, stop the `amrtrace-z28-demo` application in Docker Desktop; do **not** select its Delete volumes option.

**Independent peer reproduction (#179):** Aabia should follow **only this page** on a fresh laptop. Record laptop/OS, exact commit, API/web image IDs, start and reset elapsed time, case/release counts, one normal flow, a deliberate missing-comparison failure, recovery, and any corrections in `docs/demo/z28_peer_reproduction_template.md`. Run a second check offline. This evidence is pending until performed by Aabia.

**Optional larger-data views:** D-22 restore is intentionally not automatic; only an authorized, independently reviewed, isolated restore procedure should use the D-22 backup. A real-data restore would replace the mini-cohort and must use a different named demo volume. The mini-cohort is the required default.
