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
