# Z-28 / Z-26 independent peer reproduction record (not yet performed)

Reviewer: Aabia (must complete personally)
Date/time:
Laptop + OS + Docker Desktop/Compose versions:
Git commit (40 characters):
API image ID:
Web image ID:
PostgreSQL image ID:
Network conditions for first run:
Cached/offline run performed (yes/no):

| Check | Command/action | Expected result | Actual result | Elapsed | Evidence link |
|---|---|---|---|---|---|
| Fresh start | `deploy/demo/start.ps1` | Z28_VERIFY_SUCCESS, 660 R1 cases, R1 published | Pending | | |
| API | `/api/health` | `api`, `ok` | Pending | | |
| UI | Dashboard in browser | Existing pages load | Pending | | |
| Templates | No hosted/local keys | Templates available | Pending | | |
| Repeated start | `start.ps1 -Offline` | Existing R1 reused; no duplicate cases | Pending | | |
| Missing comparison | Query a nonexistent release comparison, if endpoint supports it | Explicit failure; prior history unchanged | Pending | | |
| Recovery | Retry valid comparison after failure | Valid result, no data loss | Pending | | |
| Reset | `reset.ps1 -ConfirmDemoReset -Offline` | Only Z-28 volume erased and reseeded to 660 | Pending | | |
| Local dev unaffected | Verify normal dev environment separately | Existing DB retained unchanged | Pending | | |

Build/start or reset errors and fixes:
Source/peer independence confirmation:
Reviewer sign-off:

Do **not** mark Z-28 or Z-26's peer test complete until Aabia actually runs and records this.
