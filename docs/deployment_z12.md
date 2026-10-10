# Z-12: Azure deployment and rollback

The production demo is served at https://20-205-38-46.sslip.io (HTTPS + HTTP Basic Auth). The domain is an IP-based sslip.io hostname: it changes if the Azure static public IP changes.

## Architecture and operational boundaries

GitHub-hosted Actions (`.github/workflows/cd.yml`) build `api` and `web` images and publish commit-specific `sha-<full SHA>` images to GHCR. On the Azure Ubuntu VM, a root-owned systemd timer runs `scripts/z12_deploy_poll.sh` approximately every 10 minutes. When `main` differs from its saved baseline, the poller fetches both images, recreates the API and frontend, checks `/`, `/api/health`, and `/api/cases?limit=1` via loopback, and either records success and saves the superseded tag in `image.previous.env`, or tries to restore the last-good images. The `image.previous.env` pointer is updated only for successful promotions, not failed candidates.

The Azure PostgreSQL Flexible Server is accessed privately from the VM. **Do not** run the development `docker-compose.yml` on the production host: it starts an unnecessary local database. Production uses `deploy/compose.ghcr.yml`, installed as `/opt/amrtrace-studio/compose.ghcr.yml`. Its frontend port is bound to `127.0.0.1:8080`, not the public NIC. Caddy runs with host networking and proxies to loopback, terminating TLS and enforcing authentication. SSH access and the Postgres database are restricted to private / explicit network rules. Avoid publishing ports 5432, 8000 or 8080.

## VM configuration and reproducibility

VM: `vm-amrtrace-z12` (Ubuntu 24.04, Azure East Asia), resource group `rg-amrtrace-z12`. DB: `pg-amrtrace-z12.postgres.database.azure.com`, database `amrtrace`, login `amrtrace_api` (nonadmin), TLS enforced with `PGSSLMODE=require`. VM has a persistent 2 GiB swapfile due to low RAM. Bastion Developer (free tier) provides interactive shell access. Keep the original verified dump offline as a recovery artifact; deployment rollback does **not** roll back database state.

Files on VM:
- `/opt/amrtrace-studio/runtime.env` — database env variables and password; permissions 0600. **Never commit or print.**
- `/opt/amrtrace-studio/image.env` — active `AMRTRACE_IMAGE_TAG=sha-...`.
- `/opt/amrtrace-studio/image.last-good.env` — currently verified deployment tag, used for automatic failed-deployment recovery.
- `/opt/amrtrace-studio/image.previous.env` — last superseded successful deployment; manual cross-version rollback target (absent before the first successful upgrade).
- `/opt/amrtrace-studio/main.baseline` — most recently considered `main` revision.
- `/opt/amrtrace-studio/main.failed` — failed revision, if any, to avoid retry loops.
- `/opt/amrtrace-studio/compose.ghcr.yml` — two app services only.
- `/usr/local/sbin/amrtrace-z12-deploy` — root-owned poller.
- `/usr/local/sbin/amrtrace-z12-rollback` — root-owned manual rollback helper.
- `/etc/systemd/system/amrtrace-z12-deploy.{service,timer}` — scheduler.
- `/opt/amrtrace-studio/caddy/Caddyfile` — host Caddy configuration with a salted Argon2id hash, not plaintext credentials. Use `basic_auth argon2id` for Argon2id hashes.
- `/opt/amrtrace-studio/caddy/data` — persistent TLS certificate state. Keep it backed up if operationally required.

On a clean host, install Docker Engine with Compose, Git, curl, flock, tmux and PostgreSQL 16 client; create `/opt/amrtrace-studio` with restricted permissions; securely supply `runtime.env` containing AMRTRACE_PG_HOST/PORT/USER/PASSWORD/DBNAME and PGSSLMODE=require. Supply `image.env` with the reviewed GHCR commit SHA, copy `deploy/compose.ghcr.yml`, then run:

```sh
sudo docker compose --env-file /opt/amrtrace-studio/image.env -f /opt/amrtrace-studio/compose.ghcr.yml pull
sudo docker compose --env-file /opt/amrtrace-studio/image.env -f /opt/amrtrace-studio/compose.ghcr.yml up -d --no-build
```

Install the poller and rollback helper as root-owned mode-0750 files, install the systemd units and enable the timer **only after** validating current app health and saving a verified `main.baseline` / last-good image. Set up Caddy separately with HTTP 80/HTTPS 443, secure authentication, persistent /data and /config, and configure Azure NSG inbound rules. A fresh install is not yet fully scripted end-to-end.

## Health and security verification

```sh
sudo docker compose --env-file /opt/amrtrace-studio/image.env -f /opt/amrtrace-studio/compose.ghcr.yml ps
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/health
curl -sS -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8080/api/cases?limit=1'
curl -sS -o /dev/null -w '%{http_code}\n' https://20-205-38-46.sslip.io/
curl -sS -o /dev/null -w '%{http_code}\n' 'https://20-205-38-46.sslip.io/api/cases?limit=1'
sudo journalctl -u amrtrace-z12-deploy.service -n 30 --no-pager
```

Loopback app checks should return 200. The public endpoints **without credentials** should return 401, not 200. For a browser demo, use username `demo` and the separately stored demo password. Never send secrets, browser login passwords, signed Blob SAS URLs, or PostgreSQL credentials in logs/screenshots. This is a demo perimeter, not multi-user RBAC.

## Post-merge production acceptance (still pending VM proof)

Aabia approved PR [#111](https://github.com/ZaraHEREhehe/amrtrace-studio/pull/111) after fixing the original same-tag-only manual rollback. The PR was merged on 2026-10-10 as `f8bec6403a2adf9a69e13541420bcbfd97287557`. GitHub shows [main CI success](https://github.com/ZaraHEREhehe/amrtrace-studio/actions/runs/38032077023) and [main image-publishing success](https://github.com/ZaraHEREhehe/amrtrace-studio/actions/runs/38032077052). Neither GitHub run establishes that the VM **actually deployed** the new images or that rollback between two versions **actually ran**.

**Important:** The timer updates API/web Docker images only. It does **not** update `/usr/local/sbin/amrtrace-z12-deploy` or `/usr/local/sbin/amrtrace-z12-rollback`. Confirm that both installed helpers match the reviewed scripts before running a cross-version rehearsal. From the Azure Bastion shell, obtain the exact merged source and compare without changing anything:

```bash
REV=f8bec6403a2adf9a69e13541420bcbfd97287557
curl -fsSLo /tmp/z12_deploy_poll.sh "https://raw.githubusercontent.com/ZaraHEREhehe/amrtrace-studio/$REV/scripts/z12_deploy_poll.sh"
curl -fsSLo /tmp/z12_rollback.sh "https://raw.githubusercontent.com/ZaraHEREhehe/amrtrace-studio/$REV/scripts/z12_rollback.sh"
bash -n /tmp/z12_deploy_poll.sh && bash -n /tmp/z12_rollback.sh
sudo cmp -s /tmp/z12_deploy_poll.sh /usr/local/sbin/amrtrace-z12-deploy && echo DEPLOY_HELPER_MATCH || echo DEPLOY_HELPER_DIFFERS
sudo cmp -s /tmp/z12_rollback.sh /usr/local/sbin/amrtrace-z12-rollback && echo ROLLBACK_HELPER_MATCH || echo ROLLBACK_HELPER_DIFFERS
```

If either file differs, schedule a controlled update while the deployment service is inactive: stop the timer, check that `amrtrace-z12-deploy.service` is not running, and install the reviewed files as root-owned mode 0750 before restarting the timer. Do not replace a running script mid-deploy. The raw URLs above are pinned to the reviewed merge commit, rather than mutable `main`.

Gather non-secret evidence from the VM. This block is read-only; the image tag is a commit identifier, not a credential:

```bash
sudo /usr/local/sbin/amrtrace-z12-deploy --check
sudo systemctl status amrtrace-z12-deploy.timer --no-pager
sudo journalctl -u amrtrace-z12-deploy.service --since "2026-10-10 06:46:00 UTC" --no-pager | grep -E 'DEPLOY_(CANDIDATE|SUCCESS|FAILED|SKIPPED)|NO_CHANGE|IMAGES_PENDING|ROLLBACK_|ERROR'
sudo grep '^AMRTRACE_IMAGE_TAG=' /opt/amrtrace-studio/image.env /opt/amrtrace-studio/image.last-good.env /opt/amrtrace-studio/image.previous.env
for path in / /api/health '/api/cases?limit=1'; do
  curl -sS -o /dev/null -w "$path HTTP %{http_code}\n" "http://127.0.0.1:8080$path"
done
sudo /usr/local/sbin/amrtrace-z12-rollback --check
```

To prove the first automatic main deployment, retain `DEPLOY_SUCCESS=sha-f8bec6403a2adf9a69e13541420bcbfd97287557` from the systemd journal, matching baseline and active image tag, and three loopback HTTP 200 responses. A later merge may legitimately advance the active tag, so use the newer exact SHA and corresponding `DEPLOY_SUCCESS` event if necessary.

To prove **cross-version** rollback, `--check` must show `ROLLBACK_READY` and distinct `ACTIVE_TAG` / `PREVIOUS_TAG`. Only in an agreed maintenance/demo window (the API/web containers will restart), run:

```bash
sudo /usr/local/sbin/amrtrace-z12-rollback --apply
sudo grep '^AMRTRACE_IMAGE_TAG=' /opt/amrtrace-studio/image.env /opt/amrtrace-studio/image.last-good.env
for path in / /api/health '/api/cases?limit=1'; do
  curl -sS -o /dev/null -w "$path HTTP %{http_code}\n" "http://127.0.0.1:8080$path"
done
```

Retain the `ROLLBACK_REDEPLOY_VERIFIED=sha-...` line, the preflight distinct tags and all three HTTP 200 checks as the rollback evidence. **Important operational consequence:** manual rollback intentionally leaves the previously verified image active; since `main.baseline` does not change, the poller will not automatically restore the latest main revision until a later change is seen. Plan an explicit, health-checked return to the intended version if the demo requires it. This test never rolls back PostgreSQL data or schema. Do not copy `runtime.env`, secrets, credentials or authenticated HTTP headers into review notes.

The final Z-12 DONE evidence belongs in this runbook, `PROJECT_PLAN.md` Section 14 and `docs/milestones.md`, with a reviewer-approved PR before closing Issue #40.

## Rollback and disaster recovery

The last-good marker safeguards automated deployment failures; **manual rollback uses the separate `image.previous.env` release pointer**, created only after a subsequent successful deployment. Before the first upgrade, there is no older release and `--check` deliberately refuses rollback. To check a genuine older release before rollback:

```sh
sudo /usr/local/sbin/amrtrace-z12-rollback --check
```

After an unsuccessful application deployment, use:

```sh
sudo /usr/local/sbin/amrtrace-z12-rollback --apply
```

This restores `image.previous.env` to `image.env`, recreates both app containers from their previously downloaded commit-tagged images, and requires all three localhost endpoints to return 200. It refuses missing local images or identical current/previous tags and, on rollback health failure, tries to restore the original active version. A successful manual rollback also updates `image.last-good.env` to match the verified running version. If a suitable image is no longer local, pull it from GHCR before retrying. The implementation acquires the same lock as the timer and does not alter PostgreSQL schema/data. Keep the previous-release tag, last-good tag and original verified dump; an application image rollback does not undo database migrations or written reviews.

If the deployment timer repeatedly reports failure, inspect `journalctl -u amrtrace-z12-deploy.service`, `sudo docker compose ... logs --tail=100 api web`, and `main.failed`. After fixing the failed revision or publishing a new revision to `main`, confirm app health again.

## Review and evidence

- Successful image publishing from feature branch: https://github.com/ZaraHEREhehe/amrtrace-studio/actions/runs/38021353549
- GHCR packages: `ghcr.io/zaraherehehe/amrtrace-studio-api` and `ghcr.io/zaraherehehe/amrtrace-studio-web`.
- Production app (password protected): https://20-205-38-46.sslip.io
- Restored database was independently checked for 20 tables, 39 indexes, 19 triggers; 41,858 cases, 83,970 states, 2,442,967 dependency rows.
- Same-version rollback rehearsal passed on 2026-10-10: both Docker services recreated and all three health endpoints ultimately passed (a transient curl connection reset during startup recovered).
- Aabia approved the fixed cross-version design in [PR #111](https://github.com/ZaraHEREhehe/amrtrace-studio/pull/111); merged to main. [Main CI](https://github.com/ZaraHEREhehe/amrtrace-studio/actions/runs/38032077023) and [main GHCR publishing](https://github.com/ZaraHEREhehe/amrtrace-studio/actions/runs/38032077052) are green.
- **Outstanding VM-only proof before DONE:** verify successful automatic deployment of reviewed main images and live cross-version rollback, with distinct tags and health-check evidence. The reviewer approval is already complete; seek final evidence review when these are captured.

## CI trust boundary and demo limitations

The container publishing workflow starts after a push to `main`; it does not wait for a second CI workflow. Protected `main` requires the project CI checks and reviewer approval **before** any PR merge, so only reviewed commits are published and picked up by the VM poller. Protect these branch rules and do not bypass them.

Nginx retains the default roughly 60-second upstream read timeout. A full-cohort exhaustive comparison was measured at approximately 73 seconds on a development machine and could exceed this timeout on the small VM. For the live demo, display stored runs instead of re-running exhaustive computation; the existing change `CHG-CLSI-ED33` cannot be executed again because R3 already exists.

## Costs and limitations

Azure for Students credit is finite. Monitor VM, Azure Database for PostgreSQL, reserved public IP and storage costs; remove the temporary blob transfer account/container after backup retention needs are satisfied. Low VM RAM and swap may make intensive exhaustive recomputation impractical. Do not expose write endpoints publicly without password protection. Rotate any exposed keys and keep secrets outside source control.

## LLM assistance

ChatGPT was used for guidance, troubleshooting, and documentation support during deployment.
