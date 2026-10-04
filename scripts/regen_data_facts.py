# G-02: inspects every frozen data file, records the real schemas and counts, and regenerates docs/data_facts.md
# needs pyarrow, so run it from the python 3.12 venv (venv312)
# usage: python scripts/regen_data_facts.py --root . [--data-dir PATH] [--strict]

import argparse
import difflib
import hashlib
import json
import re
import sys
from collections import Counter
from itertools import combinations, permutations
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# numbers below come from the M10/M11 handbook and the earlier AST conflict check, used only to flag drift
EXPECTED_ROWS = {
    "isolates_curated": 10584,
    "ast_evidence_curated": 57228,
    "genotype_evidence_curated": 413116,
    "determinant_drug_mapping_v1": 43536,
    "final_case_states_v1": 41858,
}
EXPECTED_STATES = {
    "CONCORDANT_SUSCEPTIBLE": 26532,
    "UNRESOLVED": 8389,
    "CONCORDANT_RESISTANT": 5223,
    "DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S": 1288,
    "DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE": 426,
}
EXPECTED_DRUG_TOTALS = {
    "ceftriaxone": 7220,
    "ciprofloxacin": 8787,
    "gentamicin": 9715,
    "meropenem": 7105,
    "tmp-smx": 9031,
}
EXPECTED_SHA = {
    "final_case_states_v1": "bccfa970be376b2cb0cab600345451a70906f133a65f9f698e4aea7239cdf886",
}
EXPECTED_GENOTYPE_SOURCES = {"MICROBIGGE": 325265, "ISOLATE_AMR_SUMMARY": 87851}
EXPECTED_MIC_NON_NULL = 56675
GPS_STATE = "DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S"
RNM_STATE = "DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE"
# per drug: genotype-positive/phenotype-S, phenotype-R with no mapped genotype, unresolved (M11 handbook table)
EXPECTED_DRUG_STATES = {
    "ceftriaxone": (702, 50, 91),
    "ciprofloxacin": (229, 34, 2436),
    "gentamicin": (94, 177, 2149),
    "meropenem": (118, 121, 698),
    "tmp-smx": (145, 44, 3015),
}
# OD-1: the two competing sets of numbers quoted in the execution plan (value 1, value 2)
OD1_ROWS = [
    ("ceftriaxone total cases", "ceftriaxone", 7220, None),
    ("ciprofloxacin total cases", "ciprofloxacin", 8787, 8885),
    ("gentamicin total cases", "gentamicin", 9715, 9106),
    ("meropenem total cases", "meropenem", 7105, 7346),
    ("TMP-SMX total cases", "tmp-smx", 9031, 9301),
]
OD1_GPS = (1288, 1463)
OD1_UNRESOLVED = (8389, 16.25)
# draft tables from plan section 5.3, matched to the frozen file they should come from
DRAFT_TABLES = {
    "isolate": ("isolates_curated", ["isolate_target_acc", "biosample_acc", "scientific_name", "host",
                                     "geo_loc_name", "collection_date", "isolation_source", "snapshot_id"]),
    "ast_evidence": ("ast_evidence_curated", ["ast_evidence_id", "isolate_target_acc", "antibiotic", "phenotype",
                                              "measurement_sign", "mic", "disk_diffusion", "testing_standard", "snapshot_id"]),
    "genotype_evidence": ("genotype_evidence_curated", ["genotype_evidence_id", "isolate_target_acc", "element_symbol",
                                                        "element_class", "element_subclass", "evidence_type",
                                                        "amrfinderplus_version", "refgene_db_version", "snapshot_id"]),
    "mapping_rule": ("determinant_drug_mapping_v1", ["mapping_rule_id", "mapping_version", "determinant", "antibiotic",
                                                     "organism", "relation", "status"]),
    "case": ("final_case_states_v1", ["case_id", "isolate_target_acc", "antibiotic", "panel_version"]),
}

SKIP_DIRS = {"venv", "venv312", ".git", "__pycache__", "node_modules"}
KEY_HINT = re.compile(r"(id|acc|antibiotic|drug|case|target|isolate|determinant|element|rule|symbol)", re.I)
VOCAB_COLS = ("antibiotic", "antibiotic_normalized", "drug", "drug_name")

BEGIN = "<!-- BEGIN GENERATED: scripts/regen_data_facts.py -->"
END = "<!-- END GENERATED -->"


def parse_args():
    parser = argparse.ArgumentParser(description="regenerate docs/data_facts.md from the frozen data files")
    parser.add_argument("--root", default=".", help="repo root, used for the default folders")
    parser.add_argument("--data-dir", default=None, help="folder holding the frozen data (default: ROOT/data)")
    parser.add_argument("--manifests-dir", default=None, help="folder holding manifests (default: ROOT/manifests)")
    parser.add_argument("--out", default=None, help="output markdown file (default: ROOT/docs/data_facts.md)")
    parser.add_argument("--max-distinct", type=int, default=12, help="list every value when a column has this few")
    parser.add_argument("--max-mb", type=int, default=100, help="skip deep stats on csv/json files larger than this")
    parser.add_argument("--exclude", action="append", default=[], help="regex on the file label; repeat to skip several files")
    parser.add_argument("--strict", action="store_true", help="exit with code 1 when any check fails")
    return parser.parse_args()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md_escape(value, limit=60):
    text = str(value).replace("\n", " ").replace("\r", " ").replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def md_table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(md_escape(cell, 220) for cell in row) + " |")
    return lines


def pg_type_from_arrow(arrow_type):
    if arrow_type is None:
        return "TEXT"
    if pa.types.is_dictionary(arrow_type):
        return "TEXT"
    if pa.types.is_boolean(arrow_type):
        return "BOOLEAN"
    if pa.types.is_int8(arrow_type) or pa.types.is_int16(arrow_type) or pa.types.is_uint8(arrow_type):
        return "SMALLINT"
    if pa.types.is_int32(arrow_type) or pa.types.is_uint16(arrow_type):
        return "INTEGER"
    if pa.types.is_integer(arrow_type):
        return "BIGINT"
    if pa.types.is_float32(arrow_type):
        return "REAL"
    if pa.types.is_floating(arrow_type):
        return "DOUBLE PRECISION"
    if pa.types.is_decimal(arrow_type):
        return "NUMERIC"
    if pa.types.is_date(arrow_type):
        return "DATE"
    if pa.types.is_timestamp(arrow_type):
        return "TIMESTAMPTZ" if arrow_type.tz else "TIMESTAMP"
    if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return "BYTEA"
    if pa.types.is_nested(arrow_type):
        return "JSONB"
    return "TEXT"


def norm_drug(name):
    text = str(name).strip().lower()
    if "trimethoprim" in text or text in {"tmp-smx", "tmp_smx", "tmpsmx"}:
        return "tmp-smx"
    return text


def make_hashable(series):
    def fix(value):
        if isinstance(value, (list, tuple, np.ndarray)):
            return json.dumps([str(item) for item in value])
        if isinstance(value, dict):
            return json.dumps(value, sort_keys=True, default=str)
        return value

    return series.map(fix)


def add_check(ctx, name, expected, actual):
    if actual is None:
        status = "SKIP"
    else:
        status = "PASS" if expected == actual else "FAIL"
    ctx["checks"].append((name, expected, actual, status))


def discover(bases, excludes):
    found = []
    for base in bases:
        if not base.exists():
            print(f"skipping missing folder: {base}")
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".parquet", ".csv", ".json"}:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            label = f"{base.name}/{path.relative_to(base).as_posix()}"
            if any(re.search(pattern, label) for pattern in excludes):
                print(f"excluded by --exclude: {label}")
                continue
            found.append((path, label))
    return found


def column_names(path):
    if path.suffix.lower() == ".parquet":
        return pq.read_schema(path).names
    return list(pd.read_csv(path, nrows=0).columns)


def load_table(path):
    if path.suffix.lower() == ".parquet":
        table = pq.read_table(path)
        return table.to_pandas(), dict(zip(table.schema.names, table.schema.types))
    df = pd.read_csv(path, low_memory=False)
    try:
        schema = pa.Table.from_pandas(df).schema
        return df, dict(zip(schema.names, schema.types))
    except Exception:
        return df, {}


def describe_columns(df, type_map, max_distinct):
    rows, nested_cols, notes = [], [], []
    total = len(df)
    for position, col in enumerate(df.columns, start=1):
        arrow_type = type_map.get(col)
        nested = arrow_type is not None and pa.types.is_nested(arrow_type)
        series = make_hashable(df[col]) if nested else df[col]
        if nested:
            nested_cols.append(col)
            empty = int(df[col].map(lambda v: v is not None and hasattr(v, "__len__") and len(v) == 0).sum())
            notes.append(f"`{col}` is a nested column ({arrow_type}); {empty} empty values. Needs JSONB or a child table.")
        nulls = int(series.isna().sum())
        try:
            distinct = int(series.nunique(dropna=True))
        except TypeError:
            series = series.astype(str)
            distinct = int(series.nunique(dropna=True))

        if distinct == 0:
            shown = "all null"
        elif distinct <= max_distinct:
            counts = series.value_counts(dropna=True).head(max_distinct)
            shown = "; ".join(f"{md_escape(key, 30)} ({count})" for key, count in counts.items())
        else:
            sample = series.dropna().head(3).tolist()
            shown = "e.g. " + ", ".join(md_escape(item, 30) for item in sample)
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series) and distinct > 0:
            shown += f" [min {series.min()}, max {series.max()}]"

        # date-like text columns often hold ranges or partial dates, so check before choosing DATE in postgres
        if re.search(r"(^|_)date($|_)", col.lower()) and distinct > max_distinct and pd.api.types.is_string_dtype(series):
            text = series.dropna().astype(str)
            if len(text):
                full = text.str.fullmatch(r"\d{4}-\d{2}-\d{2}").mean()
                month = text.str.fullmatch(r"\d{4}-\d{2}").mean()
                year = text.str.fullmatch(r"\d{4}").mean()
                stamp = text.str.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:.]+Z?").mean()
                other = max(0.0, 1 - full - month - year - stamp)
                advice = " Looks like a full timestamp." if stamp > 0.999 else (" Keep as TEXT unless cleaned." if full < 0.999 else "")
                notes.append(
                    f"`{col}` text formats: full date {full:.1%}, year-month {month:.1%}, year only {year:.1%}, "
                    f"iso timestamp {stamp:.1%}, other {other:.1%}." + advice
                )

        pct = f"{nulls / total * 100:.1f}%" if total else "n/a"
        rows.append([position, col, str(arrow_type) if arrow_type is not None else str(df[col].dtype),
                     pg_type_from_arrow(arrow_type), nulls, pct, distinct, shown])
    return rows, nested_cols, notes


def find_candidate_keys(df, nested_cols):
    if len(df) == 0:
        return [], []
    usable = [c for c in df.columns if c not in nested_cols and not df[c].isna().any()]
    singles = [c for c in usable if df[c].nunique() == len(df)]
    hinted = [c for c in usable if KEY_HINT.search(c) and c not in singles][:8]
    pairs = []
    for first, second in combinations(hinted, 2):
        if not df.duplicated(subset=[first, second]).any():
            pairs.append((first, second))
    return singles, pairs


def pick_state_col(df):
    for col in df.columns:
        if "state" not in col.lower():
            continue
        try:
            values = set(df[col].dropna().astype(str).unique())
        except Exception:
            continue
        if values & set(EXPECTED_STATES):
            return col
    return None


def crosstab_md(frame, row_col, state_col):
    tab = pd.crosstab(frame[row_col], frame[state_col])
    tab["TOTAL"] = tab.sum(axis=1)
    headers = [row_col] + [str(c) for c in tab.columns]
    rows = [[idx] + [int(v) for v in values] for idx, values in zip(tab.index, tab.values)]
    return md_table(headers, rows)


def case_state_facts(df, ctx, label, stem):
    state_col = pick_state_col(df)
    if state_col is None:
        return []
    counts = df[state_col].value_counts().to_dict()
    for state, expected in EXPECTED_STATES.items():
        add_check(ctx, f"{label}: rows in {state}", expected, int(counts.get(state, 0)))
    if "case_id" in df.columns:
        add_check(ctx, f"{label}: duplicated case_id values", 0, int(df["case_id"].duplicated().sum()))

    abx_col = next((c for c in ("antibiotic", "antibiotic_normalized", "drug") if c in df.columns), None)
    if abx_col is None:
        return []
    frame = pd.DataFrame({abx_col: df[abx_col].map(norm_drug), state_col: df[state_col]})
    per_drug = pd.crosstab(frame[abx_col], frame[state_col])
    for drug, (gps, rnm, unresolved) in EXPECTED_DRUG_STATES.items():
        row = per_drug.loc[drug] if drug in per_drug.index else None
        total = int(row.sum()) if row is not None else 0
        add_check(ctx, f"{label}: total cases for {drug}", EXPECTED_DRUG_TOTALS[drug], total)
        add_check(ctx, f"{label}: {drug} genotype-positive/phenotype-S", gps, int(row.get(GPS_STATE, 0)) if row is not None else 0)
        add_check(ctx, f"{label}: {drug} phenotype-R/no mapped genotype", rnm, int(row.get(RNM_STATE, 0)) if row is not None else 0)
        add_check(ctx, f"{label}: {drug} unresolved", unresolved, int(row.get("UNRESOLVED", 0)) if row is not None else 0)

    # the final release table is the one OD-1 is judged against, so it wins if several tables carry states
    if "case_stats" not in ctx or stem == "final_case_states_v1":
        ctx["case_stats"] = {
            "total": int(len(df)),
            "states": {str(k): int(v) for k, v in counts.items()},
            "drugs": {d: {str(s): int(v) for s, v in per_drug.loc[d].items()} for d in per_drug.index},
        }
    return ["", f"Case states by `{abx_col}` (TMP-SMX names are merged):", ""] + crosstab_md(frame, abx_col, state_col)


def ast_multi_test_facts(df, ctx, label):
    if not {"target_acc", "antibiotic", "phenotype"}.issubset(df.columns):
        return
    grouped = df.groupby(["target_acc", "antibiotic"])["phenotype"].agg(["count", "nunique"])
    multi = grouped[grouped["count"] > 1]
    conflicts = multi[multi["nunique"] > 1]
    add_check(ctx, f"{label}: isolate+antibiotic groups with more than one AST test", 21, int(len(multi)))
    add_check(ctx, f"{label}: groups whose tests disagree on phenotype", 3, int(len(conflicts)))


def nested_stats(label, df, col):
    lengths = df[col].map(lambda v: len(v) if v is not None and hasattr(v, "__len__") else 0)
    seen = set()
    countable = True
    for value in df[col]:
        if value is None or not hasattr(value, "__len__") or len(value) == 0:
            continue
        if not isinstance(value[0], str):
            countable = False
            break
        seen.update(value)
    return [label, col, int((lengths > 0).sum()), int(lengths.sum()), len(seen) if countable else "-", int(lengths.max()) if len(lengths) else 0]


def table_section(path, label, df, type_map, sha, shared, ctx, args):
    stem = path.stem
    ctx["seen_stems"].add(stem)
    ctx["columns"].setdefault(stem, list(df.columns))
    if stem in EXPECTED_ROWS:
        add_check(ctx, f"{label}: row count", EXPECTED_ROWS[stem], int(len(df)))
    if stem in EXPECTED_SHA:
        add_check(ctx, f"{label}: sha256", EXPECTED_SHA[stem], sha)

    rows, nested_cols, notes = describe_columns(df, type_map, args.max_distinct)
    singles, pairs = find_candidate_keys(df, nested_cols)
    for nested_col in nested_cols:
        col_type = type_map.get(nested_col)
        # struct columns have no item count, so only real list columns go in the edge table
        if col_type is not None and (pa.types.is_list(col_type) or pa.types.is_large_list(col_type)):
            ctx["nested"].append(nested_stats(label, df, nested_col))

    lines = [f"### `{label}`", "", f"{len(df):,} rows x {len(df.columns)} columns, sha256 `{sha[:16]}...`", ""]
    lines.append("Candidate keys (no nulls, no duplicates): " + (", ".join(f"`{c}`" for c in singles) if singles else "no single column"))
    if pairs:
        lines.append("")
        lines.append("Composite candidates: " + ", ".join(f"`{a}` + `{b}`" for a, b in pairs))
    for note in notes:
        lines.append("")
        lines.append(f"- {note}")
    lines += [""] + md_table(["#", "column", "arrow type", "suggested postgres type", "nulls", "null %", "distinct", "values"], rows)

    # only row-per-case tables count; the m11 csv files are pre-aggregated summaries and would give false failures
    if stem == "final_case_states_v1" or any(c in df.columns for c in ("case_id", "target_acc", "isolate_target_acc")):
        lines += case_state_facts(df, ctx, label, stem)
    ast_multi_test_facts(df, ctx, label)
    if stem == "ast_evidence_curated" and "mic" in df.columns:
        add_check(ctx, f"{label}: AST rows with a non-null mic", EXPECTED_MIC_NON_NULL, int(df["mic"].notna().sum()))
    if stem == "genotype_evidence_curated" and "representation_source" in df.columns:
        counts = df["representation_source"].value_counts().to_dict()
        for source, expected in EXPECTED_GENOTYPE_SOURCES.items():
            add_check(ctx, f"{label}: rows with representation_source {source}", expected, int(counts.get(source, 0)))

    for col in VOCAB_COLS:
        if col in df.columns and df[col].nunique() <= 40:
            ctx["vocab"][(label, col)] = sorted(str(v) for v in df[col].dropna().unique())
    for col in df.columns:
        if (col in shared and col not in nested_cols and len(df) >= 100 and KEY_HINT.search(col)
                and not pd.api.types.is_numeric_dtype(df[col]) and df[col].nunique() <= 2_000_000):
            ctx["sets"][(label, col)] = set(df[col].dropna().astype(str))
    return lines + [""]


def json_section(path, label, sha, args):
    size_mb = path.stat().st_size / (1024 * 1024)
    lines = [f"### `{label}`", "", f"{size_mb:.1f} MB, sha256 `{sha[:16]}...`", ""]
    if size_mb > args.max_mb:
        return lines + ["Skipped: too large for a quick read.", ""]
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as error:
        return lines + [f"Could not parse: {md_escape(error, 120)}", ""]
    if isinstance(data, dict):
        for key, value in list(data.items())[:60]:
            if isinstance(value, (dict, list)):
                lines.append(f"- `{key}`: {type(value).__name__} with {len(value)} items")
            else:
                lines.append(f"- `{key}`: {md_escape(value, 120)}")
    elif isinstance(data, list):
        lines.append(f"- list of {len(data)} items")
        if data and isinstance(data[0], dict):
            lines.append("- first item keys: " + ", ".join(f"`{k}`" for k in data[0].keys()))
    return lines + [""]


def od1_lines(ctx):
    stats = ctx.get("case_stats")
    if stats is None:
        return ["The case-state table was not found, so OD-1 cannot be checked yet."]

    def verdict(actual, first, second):
        if actual == first:
            return "files match value 1"
        if second is not None and actual == second:
            return "files match value 2"
        return "files match neither"

    rows = []
    for text, drug, first, second in OD1_ROWS:
        actual = sum(stats["drugs"].get(drug, {}).values())
        rows.append([text, f"{first:,}", "-" if second is None else f"{second:,}", f"{actual:,}", verdict(actual, first, second)])
    gps_actual = stats["states"].get(GPS_STATE, 0)
    rows.append(["genotype-positive/phenotype-S (all drugs)", f"{OD1_GPS[0]:,}", f"{OD1_GPS[1]:,}",
                 f"{gps_actual:,}", verdict(gps_actual, OD1_GPS[0], OD1_GPS[1])])
    unresolved = stats["states"].get("UNRESOLVED", 0)
    pct = unresolved / stats["total"] * 100 if stats["total"] else 0.0
    if unresolved == OD1_UNRESOLVED[0]:
        unresolved_verdict = "files match value 1"
    elif round(pct, 2) == OD1_UNRESOLVED[1]:
        unresolved_verdict = "files match value 2"
    else:
        unresolved_verdict = "files match neither"
    rows.append(["unresolved cases", f"{OD1_UNRESOLVED[0]:,}", f"{OD1_UNRESOLVED[1]}% overall",
                 f"{unresolved:,} ({pct:.2f}%)", unresolved_verdict])
    return md_table(["metric", "OD-1 value 1", "OD-1 value 2", "frozen files", "verdict"], rows)


def draft_vs_real_lines(ctx):
    lines = []
    for draft_name, (stem, draft_cols) in DRAFT_TABLES.items():
        lines += [f"#### draft table `{draft_name}` (from `{stem}`)", ""]
        real_cols = ctx["columns"].get(stem)
        if real_cols is None:
            lines += [f"No file named `{stem}` was found.", ""]
            continue
        rows, used = [], set()
        for col in draft_cols:
            if col in real_cols:
                rows.append([col, "exact", col])
                used.add(col)
                continue
            close = difflib.get_close_matches(col, real_cols, n=3, cutoff=0.55)
            contained = [r for r in real_cols if len(r) >= 5 and (r in col or col in r)]
            options = list(dict.fromkeys(contained + close))[:3]
            used.update(options)
            rows.append([col, "check" if options else "no match", ", ".join(options) if options else "-"])
        lines += md_table(["draft column", "status", "real column(s)"], rows)
        extra = [c for c in real_cols if c not in used]
        lines += ["", "Real columns with no draft counterpart: " + (", ".join(f"`{c}`" for c in extra) if extra else "none"), ""]
    return lines


def overlap_lines(ctx):
    by_col = {}
    for (label, col), values in ctx["sets"].items():
        by_col.setdefault(col, []).append((label, values))
    rows = []
    for col in sorted(by_col):
        for (child, child_vals), (parent, parent_vals) in permutations(by_col[col], 2):
            if not child_vals or max(len(child_vals), len(parent_vals)) <= 5:
                continue
            share = len(child_vals & parent_vals) / len(child_vals) * 100
            rows.append([col, child, parent, len(child_vals), len(parent_vals), f"{share:.1f}%"])
    if not rows:
        return ["No shared key columns found across tables."]
    return md_table(["column", "child file", "parent file", "child distinct", "parent distinct", "% of child values found in parent"], rows)


def build_document(args, data_dir, inventory, sections, json_sections, ctx):
    for stem, expected in EXPECTED_ROWS.items():
        if stem not in ctx["seen_stems"]:
            add_check(ctx, f"{stem}: row count (file not found)", expected, None)

    lines = ["## Generated facts", "",
             "Do not edit this block by hand; rerun `scripts/regen_data_facts.py`. Text outside the markers is kept.", "",
             f"- data folder scanned: `{data_dir.name}`",
             *([f"- excluded by pattern: {', '.join('`' + p + '`' for p in args.exclude)}"] if args.exclude else []),
             f"- python {sys.version.split()[0]}, pandas {pd.__version__}, pyarrow {pa.__version__}", ""]

    lines += ["### File inventory", ""]
    lines += md_table(["file", "size (MB)", "rows", "columns", "sha256 (first 16)"], inventory) + [""]

    passed = sum(1 for c in ctx["checks"] if c[3] == "PASS")
    failed = sum(1 for c in ctx["checks"] if c[3] == "FAIL")
    skipped = sum(1 for c in ctx["checks"] if c[3] == "SKIP")
    lines += ["### Regenerated counts and checks", "",
              f"{passed} passed, {failed} failed, {skipped} skipped. Expected values come from the M10/M11 handbook and the earlier AST conflict check.", ""]
    lines += md_table(["check", "expected", "actual", "status"], [[n, e, "-" if a is None else a, s] for n, e, a, s in ctx["checks"]]) + [""]

    lines += ["### OD-1 mismatch list", "",
              "The plan says the frozen files win. Value 1 and value 2 are the two competing sets of numbers quoted in OD-1.", ""]
    lines += od1_lines(ctx) + [""]

    lines += ["### Draft schema (plan section 5.3) against the real columns", "",
              "'check' means a similar name exists and a human should confirm it. This is the input for the schema ADR.", ""]
    lines += draft_vs_real_lines(ctx)

    lines += ["### Antibiotic name vocabularies", "",
              "Use this to decide the antibiotic lookup table and to catch naming mismatches between tables.", ""]
    if ctx["vocab"]:
        lines += md_table(["file", "column", "values"], [[l, c, ", ".join(v)] for (l, c), v in sorted(ctx["vocab"].items())]) + [""]
    else:
        lines += ["No antibiotic columns found.", ""]

    lines += ["### Cross-table key overlap", "",
              "Shows which columns can act as foreign keys. A child value missing from the parent means orphans during migration.", ""]
    lines += overlap_lines(ctx) + [""]

    lines += ["### List columns (possible dependency edges)", "",
              "Total items is the number of rows you get by exploding a list column into a child table. In the case table the id lists "
              "look like the already-realised dependency edges; confirm what evaluated and supporting mean with the author of the case rules.", ""]
    if ctx["nested"]:
        lines += md_table(["file", "column", "rows with items", "total items", "distinct items", "max per row"], ctx["nested"]) + [""]
    else:
        lines += ["No list columns found.", ""]

    lines += ["### Table schemas", ""]
    for section in sections:
        lines += section
    if json_sections:
        lines += ["### Manifests and other json files", ""]
        for section in json_sections:
            lines += section
    return lines, failed


def write_doc(out_path, generated_lines):
    block = BEGIN + "\n" + "\n".join(generated_lines) + "\n" + END
    stub = ("\n\n## Decisions (hand-written, not regenerated)\n\n### OD-1\n\n"
            "- Question: which per-drug splits are the true frozen V1? (plan, section 11)\n"
            "- Evidence: see the OD-1 mismatch list above\n- Decision: pending (plan default: the frozen files win)\n")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        text = out_path.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            head, rest = text.split(BEGIN, 1)
            _, tail = rest.split(END, 1)
            out_path.write_text(head + block + tail, encoding="utf-8", newline="\n")
            return out_path, "updated the generated block and kept the hand-written text"
        side_path = out_path.with_suffix(".generated.md")
        side_path.write_text("# Data facts (generated)\n\n" + block + "\n", encoding="utf-8", newline="\n")
        return side_path, "existing file has no markers, so wrote a separate file; merge it by hand once"
    out_path.write_text("# Data facts\n\n" + block + stub, encoding="utf-8", newline="\n")
    return out_path, "created a new file"


def main():
    args = parse_args()
    root = Path(args.root).resolve()
    data_dir = Path(args.data_dir).resolve() if args.data_dir else root / "data"
    manifests_dir = Path(args.manifests_dir).resolve() if args.manifests_dir else root / "manifests"
    out_path = Path(args.out).resolve() if args.out else root / "docs" / "data_facts.md"

    files = discover([data_dir, manifests_dir], args.exclude)
    if not files:
        sys.exit("no parquet, csv or json files found; check --data-dir")
    tabular = [(p, l) for p, l in files if p.suffix.lower() in {".parquet", ".csv"}]
    json_files = [(p, l) for p, l in files if p.suffix.lower() == ".json"]

    # first pass reads only headers so we know which column names appear in more than one table
    name_counter = Counter()
    for path, _ in tabular:
        name_counter.update(set(column_names(path)))
    shared = {name for name, count in name_counter.items() if count >= 2}

    ctx = {"checks": [], "sets": {}, "vocab": {}, "seen_stems": set(), "columns": {}, "nested": []}
    inventory, sections, json_sections = [], [], []

    for path, label in tabular:
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"reading {label} ({size_mb:.1f} MB)")
        sha = sha256_file(path)
        if path.suffix.lower() == ".csv" and size_mb > args.max_mb:
            inventory.append([label, f"{size_mb:.1f}", "skipped", "skipped", sha[:16]])
            continue
        df, type_map = load_table(path)
        inventory.append([label, f"{size_mb:.1f}", f"{len(df):,}", len(df.columns), sha[:16]])
        sections.append(table_section(path, label, df, type_map, sha, shared, ctx, args))
        del df

    for path, label in json_files:
        print(f"reading {label}")
        sha = sha256_file(path)
        inventory.append([label, f"{path.stat().st_size / (1024 * 1024):.1f}", "-", "-", sha[:16]])
        json_sections.append(json_section(path, label, sha, args))

    lines, failed = build_document(args, data_dir, inventory, sections, json_sections, ctx)
    final_path, message = write_doc(out_path, lines)
    print(f"\n{message}: {final_path}")
    print(f"checks: {sum(1 for c in ctx['checks'] if c[3] == 'PASS')} passed, {failed} failed, "
          f"{sum(1 for c in ctx['checks'] if c[3] == 'SKIP')} skipped")
    for name, expected, actual, status in ctx["checks"]:
        if status == "FAIL":
            print(f"  FAIL {name}: expected {expected}, got {actual}")
    if args.strict and failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
