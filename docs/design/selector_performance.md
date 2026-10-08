# Selector performance evidence (A-07)

Measured by Aabia on 2026-10-07 against release `R1` in PostgreSQL 16.15, on one development machine.
The graph is the one described in `graph_metrics.md`: 41,858 cases, 1,196,148 dependency rows, 344,526 applicability rows.

## Summary

| Lookup | Rows returned | Access method | Cold | Warm (median of 20) |
|---|---|---|---|---|
| Typical mapping rule | 2 | Index Scan on `dependency_node_idx` | 0.02 ms | about 0.5 ms |
| Busiest mapping rule | 9,127 | Bitmap Heap Scan via `dependency_node_idx` | 44 ms | 16 ms |
| Version node every case depends on | 41,858 | Bitmap Heap Scan via `dependency_node_idx` | 1,125 ms | 104 to 128 ms |
| Applicability pair | 702 | Index Scan on `applicability_pair_idx` | 25 ms | not measured |

- **No sequential scan on the hot path.** Every selector lookup goes through an index.
- "Cold" is the server-side time from `EXPLAIN (ANALYZE, BUFFERS)` on the first run, when most pages were not yet in PostgreSQL's memory.
- "Warm" is from `scripts/graph_metrics.py`, measured in the client, and includes fetching the rows into Python. That is why the warm figure for a two-row lookup is larger than the cold server-side one.
- The two columns were measured in different ways, so compare them only roughly.

## What the plans show

### 1. The usual case is a direct index lookup

```
Index Scan using dependency_node_idx on dependency  (actual time=0.014..0.015 rows=2 loops=1)
  Index Cond: ((node_type = 'mapping_rule') AND (node_id = '<rule id>'))
  Filter: (release_id = 'R1')
  Buffers: shared hit=5
Execution Time: 0.024 ms
```

Five pages are touched. Half of all mapping rules have at most 2 dependent cases, and every evidence row has at most 5, so this is what most changes cost.

### 2. A busy rule is still found through the index

```
Bitmap Heap Scan on dependency  (actual time=3.902..43.250 rows=9127 loops=1)
  Recheck Cond: ((node_type = 'mapping_rule') AND (node_id = '<rule id>'))
  Filter: (release_id = 'R1')
  Heap Blocks: exact=6456
  Buffers: shared hit=46 read=6420
  ->  Bitmap Index Scan on dependency_node_idx  (actual time=2.919..2.919 rows=9127 loops=1)
Execution Time: 44.062 ms
```

The index finds the 9,127 rows in 3 ms. The remaining 40 ms is reading the 6,456 table pages those rows sit on, most of them from disk (`read=6420`).

### 3. A version change is the worst case, and it is slow for an honest reason

```
Bitmap Heap Scan on dependency  (actual time=23.278..1120.246 rows=41858 loops=1)
  Recheck Cond: (node_type = 'mapping_version')
  Filter: (release_id = 'R1')
  Heap Blocks: exact=29315
  Buffers: shared hit=652 read=28703
  ->  Bitmap Index Scan on dependency_node_idx  (actual time=17.470..17.471 rows=41858 loops=1)
Execution Time: 1124.594 ms
```

A version that every case depends on returns every case. The index part takes 17 ms. The rest is reading 29,315 table pages, about 229 MB, nearly all from disk on this first run. Once the pages are in memory the same lookup takes about 0.1 s.

This is not a selector weakness. When a change touches every case, selective re-evaluation has nothing to skip, and the re-evaluation itself will cost far more than this lookup.

### 4. Applicability lookups use their own index

```
Index Scan using applicability_pair_idx on applicability  (actual time=0.833..25.263 rows=702 loops=1)
  Index Cond: ((candidate_antibiotic = $0) AND (determinant_identity = $1))
  Filter: (release_id = 'R1')
  Buffers: shared hit=1 read=498
Execution Time: 25.380 ms
```

The plan also contained a `Seq Scan` with `LIMIT 1`. That belongs to the helper sub-query that picked an example pair for this measurement, and it read one row. It is not part of the lookup.

## Findings

1. **The index design from I-01 is sufficient for R1.** `dependency_node_idx (node_type, node_id, node_version)` serves every realised-edge lookup, and `applicability_pair_idx` serves the applicability lookup.
2. **Cold lookups on busy nodes are dominated by reading table pages, not by the index.** The `dependency` table is 271 MB, which is larger than PostgreSQL's default `shared_buffers` of 128 MB, so it cannot stay fully in PostgreSQL's own memory. Raising `shared_buffers` in the deployment would narrow the gap between cold and warm. This is a configuration matter for Z-02 and Z-12, and no code change.
3. **The release is filtered after the index, not by it.** Every plan shows `Filter: (release_id = 'R1')`, because neither index includes `release_id`. With one release the filter removes nothing. With many releases, a lookup on a busy node would read that node's rows from every release and discard the others.

## Decision: no new index now

A new index such as `(release_id, node_type, node_id)` would fix finding 3. It is not added in A-07, for three reasons:

- It gives no benefit while R1 is the only release.
- A later release stores dependency rows only for the cases it re-evaluates, so the table grows slowly, not by 1.2 million rows per release.
- It would add roughly 40 MB and slow the initial load, and a migration should be justified by a measurement.

**Follow-up:** rerun `scripts/graph_metrics.py` and the plans above once several releases exist (after I-09). If a plan shows rows removed by the release filter in meaningful numbers, add the index in a new numbered migration, agreed with the schema owner.

## Precision and reprocessing ratio

The plan also lists per-scenario precision and reprocessing ratio under A-07. Those need registered change scenarios and the oracle fixtures (I-07), and they are reported by the equivalence check (I-10). They are not measured here. What can be stated now is the reprocessing ratio a lookup implies: a typical rule change selects 2 of 41,858 cases, the busiest rule selects 9,127 (21.8%), and a version change selects all of them.

## How to repeat it

```powershell
python scripts\graph_metrics.py
```

for the warm figures, and for the plans:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT case_id FROM dependency
WHERE release_id = 'R1' AND node_type = '<node type>' AND node_id = '<node id>';
```

Cold figures depend on what is already in memory, so a repeat run on a warm database will be faster than the table above.

## Re-measurement with two releases (2026-10-08)

This is the follow-up promised above. It was done after R2, the Ed32 interpretation release, was stored. R2 is a full release, so the `dependency` table went from 1,196,148 to 2,434,140 rows. That differs from the assumption in the decision above, which expected later releases to store rows only for re-evaluated cases.

### What was measured

`scripts/selector_timing.py` times the whole call to `select_impact_detailed` from Python, three times per change. The changes are registered inside a transaction that is rolled back, so nothing is written. "First" is the first call and "best" is the fastest of the three.

These figures are **not like for like with the table at the top of this note**. That table gives the time of one SQL lookup. These give the whole selection: the lookup, finding each case's current release, region refinement and building the result.

| Change | Stored rows | Cases selected | First fix: first / best | After the correction: first / best |
|---|---|---|---|---|
| Typical mapping rule | 4 | 2 | 7.7 / 1.9 ms | 7.2 / 2.0 ms |
| Busiest mapping rule | 18,254 | 9,127 | 2,118 / 632 ms | 1,408 / 235 ms |
| Busiest interpretation rule | 8,843 | 8,843 | 627 / 491 ms | 300 / 118 ms |
| Version node every case depends on | 83,716 | 41,858 | 7,402 / 2,054 ms | 4,789 / 805 ms |
| New rule found through the rule space | 19,248 | 9,624 | 373 / 373 ms | 520 / 130 ms |

### What went wrong, and the correction

The selector was changed in A-05 so that each case is judged by the newest published release that holds rows for it. The first version of that change found the newest release by reading every stored row of every candidate case. For the version node that is about 2.4 million rows, read only to learn "R1 or R2".

The correction asks one question per case through `dependency_case_release_idx` and `applicability_case_release_idx`: does the newest release hold anything for this case? Only cases that answer no are asked about the next older release. The selected cases are identical, and the busy changes became 2.5 to 4 times faster.

The correctness checks were repeated after the correction: the full test suite passes, and CLSI-REAL on the real cohort still selects 254 cases, including all 154 required ones.

### Findings

1. **The typical change is unaffected.** About 2 ms for the whole selection.
2. **A change to a busy node now costs a few hundred milliseconds, and a change that touches every case costs about 0.8 s warm.** The cost grows with the number of candidate cases and with the number of releases that hold rows for the same node.
3. **A change that touches every case is not a selection problem.** All 41,858 cases must be re-evaluated anyway, which takes far longer than 0.8 s.
4. **Finding 3 of the original note has come true.** Both releases' rows for a node are read, and half are then discarded because they are not the case's current release.

### Decision

No new index is added now. The remaining cost on busy nodes is below one second, and the evaluation scenarios select a few hundred cases.

If more full releases are stored, the right change is structural, not a wider index: record each case's current release once, when a release is published, so the selector reads only current rows. That would need a migration and an owner for the ledger side, so it is raised here for the team and not done in this task.

### How to repeat it

```powershell
python scripts\selector_timing.py
python scripts\run_real_oracle.py --new-table data\interpretation\clsi_m100_ed33.yaml
```
