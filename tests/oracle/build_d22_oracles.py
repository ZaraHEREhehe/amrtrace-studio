# writes the two real-data oracle fixtures for the D-22 release chain from the frozen evidence files
# VET01S-INTRODUCED (R2 -> R3): CLSI_M100_ED32 -> CLSI_M100_ED32_VET01S_ED7, which adds the VET01S host rules
# CLSI-REAL (R3 -> R4): CLSI_M100_ED32_VET01S_ED7 -> CLSI_M100_ED33_VET01S_ED7, the gentamicin revision
# the required sets come from the raw files, the host grouping file and the tables, never from the graph, selector or evaluator
# the interval check below is written again on purpose, so the oracle does not lean on the engine it is checking
# run from the repo root (needs data/raw, no database), then stamp and commit before running the selector:
#     python tests/oracle/build_d22_oracles.py
#     python tests/oracle/stamp_fixtures.py

import argparse
import math
import pathlib
import re
import sys

import pyarrow.parquet as pq
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
TABLES = ROOT / "data" / "interpretation"
HOST_GROUPS = ROOT / "src" / "amrtrace" / "ingest" / "host_groups_v1.yaml"
FIXTURES = ROOT / "tests" / "oracle" / "fixtures"
STANDARD = "CLSI"
NOT_DEFINED = "NOT_DEFINED"
LETTERS = {"susceptible": "S", "intermediate": "I", "resistant": "R"}
INF = math.inf


def _norm(text) -> str:
    return " ".join(re.sub(r"\[[^\]]*\]", " ", str(text or "")).split()).lower()


def _yaml(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# raw host value to (group, animal), read straight from the grouping file
def host_lookup(path=HOST_GROUPS):
    data = _yaml(path)
    lookup = {_norm(v): None for v in data.get("not_recorded") or ()}
    for name, body in data["groups"].items():
        for raw in body["hosts"]:
            lookup[_norm(raw)] = (name, bool(body["animal"]))
    return lookup


# the general (no host) rules of one table, by drug, as plain category lists
def general_rules(table_file):
    return {r["antibiotic"]: r["categories"] for r in _yaml(TABLES / table_file)["rules"] if "host" not in r}


def host_rules(table_file):
    return [r for r in _yaml(TABLES / table_file)["rules"] if "host" in r]


# low, high and whether each end is included, for a measurement or a category
def _interval(op, value):
    return {"==": (value, value, True, True), "<=": (-INF, value, False, True), "<": (-INF, value, False, False),
            ">=": (value, INF, True, False), ">": (value, INF, False, False)}[op]


def _meets(a, b) -> bool:
    lo, lo_in = (a[0], a[2]) if a[0] > b[0] or (a[0] == b[0] and not a[2]) else (b[0], b[2])
    hi, hi_in = (a[1], a[3]) if a[1] < b[1] or (a[1] == b[1] and not a[3]) else (b[1], b[3])
    return lo < hi or (lo == hi and lo_in and hi_in)


# the letters of every category a measurement could fall in
def reachable(categories, mic, sign):
    measured = _interval(sign or "==", float(mic))
    return {LETTERS[c["label"]] for c in categories if _meets(measured, _interval(c["op"], float(c["value"])))}


def _usable(row) -> bool:
    mic = row.get("mic")
    return row.get("standard") == STANDARD and mic is not None and not (isinstance(mic, float) and math.isnan(mic))


# R3: an animal result for a drug with host rules, whose label Ed32 explains or which has no category
def vet_required(ast_rows, host_by_target, case_by_key, ed32, host_drugs):
    found = set()
    for row in ast_rows:
        drug = row["antibiotic"]
        host = host_by_target.get(row["target_acc"])
        if drug not in host_drugs or not _usable(row) or not host or not host[1]:
            continue
        label = row["phenotype_normalized"]
        explained = drug in ed32 and reachable(ed32[drug], row["mic"], row["measurement_sign"]) == {label}
        if label == NOT_DEFINED or explained:
            case_id = case_by_key.get((row["target_acc"], drug))
            if case_id:
                found.add(case_id)
    return found


# R4: a human or unrecorded-host gentamicin result at exactly 4 labelled S or exactly 8 labelled I
def clsi_required(ast_rows, host_by_target, case_by_key):
    found = set()
    for row in ast_rows:
        if row["antibiotic"] != "gentamicin" or not _usable(row) or row["measurement_sign"] != "==":
            continue
        host = host_by_target.get(row["target_acc"])
        if host and host[1]:
            continue
        if (float(row["mic"]), row["phenotype_normalized"]) in ((4.0, "S"), (8.0, "I")):
            case_id = case_by_key.get((row["target_acc"], row["antibiotic"]))
            if case_id:
                found.add(case_id)
    return found


def read_inputs(raw_dir):
    raw_dir = pathlib.Path(raw_dir)
    ast_rows = pq.read_table(raw_dir / "curated_v1" / "ast_evidence_curated.parquet",
                             columns=["target_acc", "antibiotic", "standard", "measurement_sign", "mic",
                                      "phenotype_normalized"]).to_pylist()
    lookup = host_lookup()
    isolates = pq.read_table(raw_dir / "curated_v1" / "isolates_curated.parquet", columns=["target_acc", "host"]).to_pylist()
    unknown = sorted({str(r["host"]) for r in isolates if _norm(r["host"]) not in lookup})
    if unknown:
        raise SystemExit(f"STOP: hosts not in the grouping file: {unknown}")
    host_by_target = {r["target_acc"]: lookup[_norm(r["host"])] for r in isolates}
    case_by_key = {(r["target_acc"], r["antibiotic"]): r["case_id"]
                   for r in pq.read_table(raw_dir / "analysis_v1" / "final_case_states_v1.parquet",
                                          columns=["case_id", "target_acc", "antibiotic"]).to_pylist()}
    return ast_rows, host_by_target, case_by_key


NOTE = ("D-22 fix of the real-data oracles, generated from the raw files; the criteria are the rules in the AMRTrace "
        "Breakpoint Reference, and the required set never reads the dependency graph, the selector or the evaluator.")
# the fix was written by the selector's author, so an independent re-run is recorded as still owed
AUTHOR = "aabia"
RERUN = {"by": "insharah", "status": "pending"}


def vet_fixture(required):
    entities = [{"node_type": "interpretation_rule",
                 "node_id": "|".join(_norm(x) for x in ("CLSI", r["organism"], r["antibiotic"], r["method"], r["host"])),
                 "old_version": None, "new_version": "CLSI_M100_ED32_VET01S_ED7", "changed_region": None}
                for r in host_rules("clsi_m100_ed32_vet01s_ed7.yaml")]
    return {
        "scenario": "VET01S-INTRODUCED",
        "description": ("Real interpretation-table change that adds the CLSI VET01S Ed7 host rules. Every animal case for "
                        "gentamicin, meropenem or TMP-SMX with a CLSI MIC whose label M100 Ed32 explains, or which is "
                        "NOT_DEFINED, must be selected (recall 100%)."),
        "authored_by": AUTHOR, "authored_on_base_commit": "STAMP_ME", "author_note": NOTE, "real_data": True,
        "independent_rerun": dict(RERUN),
        "change_event": {"change_id": "CHG-VET01S-ED7", "type": "INTERPRETATION_VERSION",
                         "old_version": "CLSI_M100_ED32", "new_version": "CLSI_M100_ED32_VET01S_ED7",
                         "changed_entities": sorted(entities, key=lambda e: e["node_id"]),
                         "declared_scope": {"standard": "CLSI", "hosts": "animal"}, "initiator": "oracle"},
        "expected": {"required_case_ids": sorted(required), "allowed_extra_case_ids": [], "must_not_select_case_ids": []},
    }


def clsi_fixture(required):
    key = "clsi|escherichia coli|gentamicin|mic"
    return {
        "scenario": "CLSI-REAL",
        "description": ("Real interpretation-table change CLSI M100 Ed32 -> Ed33 for gentamicin, after VET01S. Every human or "
                        "unrecorded-host case with an exact CLSI MIC of 4 labelled S or 8 labelled I must be selected "
                        "(recall 100%). Animal cases are read by their host rules and are not touched by this change."),
        "authored_by": AUTHOR, "authored_on_base_commit": "STAMP_ME", "author_note": NOTE, "real_data": True,
        "independent_rerun": dict(RERUN),
        "change_event": {"change_id": "CHG-CLSI-ED33", "type": "INTERPRETATION_VERSION",
                         "old_version": "CLSI_M100_ED32_VET01S_ED7", "new_version": "CLSI_M100_ED33_VET01S_ED7",
                         "changed_entities": [{"node_type": "interpretation_rule", "node_id": key,
                                               "old_version": "CLSI_M100_ED32_VET01S_ED7",
                                               "new_version": "CLSI_M100_ED33_VET01S_ED7",
                                               "changed_region": {"field": "mic", "intervals": [[4, 4], [8, 8]]}}],
                         "declared_scope": {"standard": "CLSI", "antibiotic": "gentamicin"}, "initiator": "oracle"},
        "expected": {"required_case_ids": sorted(required), "allowed_extra_case_ids": [], "must_not_select_case_ids": []},
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Write the D-22 real-data oracle fixtures from the frozen files.")
    p.add_argument("--raw", default=str(ROOT / "data" / "raw"))
    p.add_argument("--out", default=str(FIXTURES))
    args = p.parse_args(argv)
    ast_rows, host_by_target, case_by_key = read_inputs(args.raw)
    ed32 = general_rules("clsi_m100_ed32.yaml")
    host_drugs = {r["antibiotic"] for r in host_rules("clsi_m100_ed32_vet01s_ed7.yaml")}
    vet = vet_required(ast_rows, host_by_target, case_by_key, ed32, host_drugs)
    clsi = clsi_required(ast_rows, host_by_target, case_by_key)
    out = pathlib.Path(args.out)
    for name, fixture in (("vet01s_introduced.yaml", vet_fixture(vet)), ("clsi_real.yaml", clsi_fixture(clsi))):
        (out / name).write_text(yaml.safe_dump(fixture, sort_keys=False, width=120), encoding="utf-8", newline="\n")
        print(f"wrote {name}: {len(fixture['expected']['required_case_ids'])} required cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
