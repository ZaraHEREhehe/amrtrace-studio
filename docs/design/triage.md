# Triage: the order cases are reviewed in (A-14)

Triage gives every case state a fixed, documented place in the review order (decision D-28). It is a rule, not a
trained model: no labelled data exists to learn one, and a fixed rule can be explained and tested.

## The rule

| Rank | Tier | When | Why first |
| ---- | ---- | ---- | --------- |
| 1 | Newly discordant | The state is discordant and the state it replaced was not (or there was none) | Genotype and phenotype now disagree: the strongest signal that something needs a person |
| 2 | State changed | The state differs from the state it replaced | The conclusion moved |
| 3 | Label changed | Same state, but interpretation changed at least one submitted label (`labels_changed` > 0) | The evidence was read differently, even though the conclusion held |
| 4 | Re-verified | Same state and no changed label | Nothing to look at beyond confirmation |

Ties are broken by case id, so the same inputs always give the same order. Every ranked case carries a one-line
reason, for example `state changed: UNRESOLVED to CONCORDANT_SUSCEPTIBLE`. The state a case replaced is read through
`case_state.supersedes_state_id`; a state with nothing before it is a first evaluation. The discordant states are taken
from the evaluator's constants, so no state code is spelled twice. The whole rule is one function,
`amrtrace.triage.classify`, which the ranking, the API and the reason text all use.

## Where it is used

- **Review queue** (I-18): `GET /review-queue?sort=triage` returns the unverified cases in triage order. The whole
  queue is ranked before paging, so every page follows the same order. The default order is still by case id, so
  existing callers see no change, but every item now carries `triage_tier`, `triage_rank` and `triage_reason`.
- **A release** (the re-evaluated impact set): `GET /releases/{release_id}/triage?limit=&offset=` returns every
  state the release wrote in triage order, with the count in each tier.
- **Review Queue page**: an **Order** choice (Case ID or Priority) and a **Priority** column with the tier badge and
  its reason underneath, written with the same state names the state badges use. The order is part of the page link
  (`#/review-queue/sort=triage`).

## Limits

- Inside a tier the order is by case id only; there is no weighting by drug, host or how many labels changed.
- A first evaluation of a discordant case counts as newly discordant, so ranking the baseline release puts every
  discordant case in tier 1. Triage is meant for later releases and the review queue.
- The ranking reads the matching queue or release in full before paging. The queue is small; a full release
  (about 42,000 states) is ranked in memory in well under a second.
