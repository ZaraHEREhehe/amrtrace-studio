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

## Deployment (Z-12)

**Live protected demo:** https://20-205-38-46.sslip.io

The deployed API and frontend run on an Azure Ubuntu VM in Docker, using Azure PostgreSQL over a private network. Caddy provides HTTPS and password protection. GitHub Actions publishes both containers to GHCR on a merge to `main` or a version tag; a VM systemd timer checks `main` approximately every 10 minutes and deploys matching images when available.

**Deploy, verify, troubleshoot, or roll back:** follow [Z-12 deployment and rollback runbook](docs/deployment_z12.md). The production Compose file is [deploy/compose.ghcr.yml](deploy/compose.ghcr.yml). Do not use the development Compose stack on the live server because it creates a local PostgreSQL container. Credentials stay outside the repository.

To rehearse a rollback on the VM (requires Azure Bastion access):

```bash
sudo /usr/local/sbin/amrtrace-z12-rollback --check
sudo /usr/local/sbin/amrtrace-z12-rollback --apply
```

After the first successful upgrade, the deployer saves the superseded working tag in `image.previous.env`; the manual rollback restores **that previous tag**, while automatic deployment failures restore the last verified tag. A rollback refuses identical versions or missing images. The rehearsal on 2026-10-10 validated same-version redeployment; live cross-version rollback and post-merge automatic rollout still need evidence. Image rollback does **not** roll back database contents.

**LLM Assistance:** AI-assisted tools were used for technical guidance, troubleshooting, and documentation support. Implementation, verification, and final decisions remain the responsibility of the project team.
