"""Write the real-data oracle fixture CLSI-REAL from the frozen evidence files (task I-07).

The expected set comes from the raw AST evidence, never from the dependency graph or the selector: gentamicin cases
with an exact (==) CLSI MIC of 4 or 8, the two values whose category the CLSI Ed32 -> Ed33 revision changes. The
project report states 154 such cases (50 at MIC 4, 104 at MIC 8). If the files disagree the script stops and prints
what it found under looser filters, so the difference is understood and not silently accepted.

It reads data/raw/ directly, so it needs no database. Run it from the repo root:
    python tests\\oracle\\build_clsi_real_fixture.py
Then run stamp_fixtures.py and commit BEFORE the selector is run against it.

    --accept-actual   write the fixture with the counts actually found (use only after investigating a mismatch)
"""

import argparse
import pathlib
import sys

import pyarrow.parquet as pq
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXPECTED = {4: 50, 8: 104}
RULE_KEY = "clsi|escherichia coli|gentamicin|mic"


def find_cases(ast_rows, case_by_key, standard):
    """Distinct case ids (with the MIC values seen) for gentamicin, exact MIC 4 or 8, optionally one standard only."""
    found = {}
    for r in ast_rows:
        if r["antibiotic"] != "gentamicin" or r["measurement_sign"] != "==" or r["mic"] not in (4.0, 8.0):
            continue
        if standard and r["standard"] != standard:
            continue
        case_id = case_by_key.get((r["target_acc"], r["antibiotic"]))
        if case_id is not None:
            found.setdefault(case_id, set()).add(float(r["mic"]))
    return found


def per_value(found):
    return {mic: sum(1 for values in found.values() if float(mic) in values) for mic in (4, 8)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Write the CLSI-REAL oracle fixture from the frozen files.")
    p.add_argument("--ast", default=str(ROOT / "data" / "raw" / "curated_v1" / "ast_evidence_curated.parquet"))
    p.add_argument("--cases", default=str(ROOT / "data" / "raw" / "analysis_v1" / "final_case_states_v1.parquet"))
    p.add_argument("--out", default=str(ROOT / "tests" / "oracle" / "fixtures" / "clsi_real.yaml"))
    p.add_argument("--accept-actual", action="store_true")
    args = p.parse_args(argv)

    for path in (args.ast, args.cases):
        if not pathlib.Path(path).exists():
            print(f"STOP: {path} not found. The frozen files must be in data/raw/ (see ADR-003 section 1).")
            return 1

    ast_rows = pq.read_table(args.ast, columns=["target_acc", "antibiotic", "standard", "measurement_sign", "mic"]).to_pylist()
    case_by_key = {(r["target_acc"], r["antibiotic"]): r["case_id"]
                   for r in pq.read_table(args.cases, columns=["case_id", "target_acc", "antibiotic"]).to_pylist()}

    found = find_cases(ast_rows, case_by_key, "CLSI")
    counts = per_value(found)
    print(f"CLSI, exact MIC 4 or 8: {len(found)} cases, per MIC {counts}  (report: {EXPECTED}, total {sum(EXPECTED.values())})")
    matches = counts == EXPECTED and len(found) == sum(EXPECTED.values())
    if not matches:
        loose = find_cases(ast_rows, case_by_key, None)
        print(f"  any standard:          {len(loose)} cases, per MIC {per_value(loose)}")
        print(f"  cases seen at both 4 and 8 (CLSI): {sum(1 for v in found.values() if len(v) == 2)}")
        if not args.accept_actual:
            print("STOP: the files do not match the documented counts. Work out why, then rerun with --accept-actual "
                  "if the difference is explained.")
            return 1

    fixture = {
        "scenario": "CLSI-REAL",
        "description": ("Real interpretation-table change CLSI M100 Ed32 -> Ed33 for gentamicin. Every case with an exact CLSI "
                        "MIC of 4 or 8 must be selected (recall 100%). The selector may select more; precision is reported "
                        "separately against the exhaustive actual-affected set."),
        "authored_by": "insharah",
        "authored_on_base_commit": "STAMP_ME",
        "author_note": ("Expected set derived from the raw AST evidence files (see build_clsi_real_fixture.py), not from the "
                        "dependency graph or the selector."),
        "real_data": True,
        "pending": {"until": "interpretation baseline",
                    "reason": ("needs a release evaluated in interpretation mode with CLSI_M100_ED32, because the as-reported "
                               "baseline R1 stores no edges to interpretation rules")},
        "change_event": {
            "change_id": "CHG-CLSI-ED33", "type": "INTERPRETATION_VERSION",
            "old_version": "CLSI_M100_ED32", "new_version": "CLSI_M100_ED33",
            "changed_entities": [{"node_type": "interpretation_rule", "node_id": RULE_KEY,
                                  "old_version": "CLSI_M100_ED32", "new_version": "CLSI_M100_ED33",
                                  "changed_region": {"field": "mic", "intervals": [[4, 4], [8, 8]]}}],
            "declared_scope": {"standard": "CLSI", "antibiotic": "gentamicin"}, "initiator": "oracle"},
        "expected": {"required_case_ids": sorted(found), "allowed_extra_case_ids": [], "must_not_select_case_ids": []},
    }
    if not matches:
        fixture["count_note"] = f"differs from the report (50 at MIC 4, 104 at MIC 8): found {counts}; accepted after investigation"
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(fixture, sort_keys=False, width=120), encoding="utf-8", newline="\n")
    print(f"wrote {out} with {len(found)} required cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())