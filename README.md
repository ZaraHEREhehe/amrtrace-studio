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