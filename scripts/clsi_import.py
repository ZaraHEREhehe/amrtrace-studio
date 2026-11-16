# task A-23: turn a pinned local snapshot of the AMR R package's clinical_breakpoints data into a DRAFT interpretation
# table, and compare it rule by rule with the active table of the same name
# the draft is written outside data/interpretation and is never stored or activated by this script
import argparse
import csv
import hashlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_TABLES = ROOT / "data" / "interpretation"
DEFAULT_OUT = ROOT / "data" / "processed" / "clsi_drafts"
DRAFT_SUFFIX = "_AMR_DRAFT"

AMR_COLUMNS = ("guideline", "type", "host", "method", "mo", "ab", "uti", "is_SDD", "breakpoint_S", "breakpoint_R")
TRUE = "TRUE"


class ImportRefused(ValueError):
    """The snapshot cannot give one clear rule for a drug and host; nothing is written."""


@dataclass(frozen=True)
class Breakpoint:
    s: Decimal
    r: Decimal
    organism_code: str
    guideline: str
    host: str


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_snapshot(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    missing = [c for c in AMR_COLUMNS if rows and c not in rows[0]]
    if not rows or missing:
        raise ImportRefused(f"{path.name} is not a clinical_breakpoints export (missing columns: {missing or 'all'})")
    return rows


def read_spec(path: Path) -> dict:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("interpretation_version", "organism", "organism_codes", "drugs", "human_guideline"):
        if not spec.get(key):
            raise ImportRefused(f"spec {path.name} needs {key}")
    return spec


def _number(text: str, what: str) -> Decimal:
    try:
        return Decimal(str(text).strip())
    except Exception as exc:
        raise ImportRefused(f"{what}: {text!r} is not a number") from exc


# the one MIC breakpoint pair for a drug, organism, guideline and host; species row first, then the group row
def find_breakpoint(rows, guideline: str, host: str, organism_codes, drug_code: str, what: str) -> Breakpoint | None:
    for code in organism_codes:
        hits = [
            r for r in rows
            if r["guideline"] == guideline and r["host"] == host and r["method"] == "MIC"
            and r["mo"] == code and r["ab"] == drug_code and r["uti"] != TRUE
        ]
        if not hits:
            continue
        if any(r["is_SDD"] == TRUE for r in hits):
            raise ImportRefused(f"{what}: a susceptible-dose-dependent row cannot be expressed as S, I and R")
        pairs = {(r["breakpoint_S"].strip(), r["breakpoint_R"].strip()) for r in hits}
        if len(pairs) > 1:
            raise ImportRefused(f"{what}: {len(hits)} rows give different breakpoints {sorted(pairs)}")
        s_text, r_text = pairs.pop()
        if not s_text or not r_text:
            raise ImportRefused(f"{what}: the row has no S or no R breakpoint")
        return Breakpoint(_number(s_text, what), _number(r_text, what), code, guideline, host)
    return None


# S and R give the categories; one doubling dilution between them is I, none means no I, anything else is refused
def categories(bp: Breakpoint, what: str) -> list[dict]:
    if bp.r <= bp.s:
        raise ImportRefused(f"{what}: R {bp.r} is not above S {bp.s}")
    rows = [{"label": "susceptible", "op": "<=", "value": _plain(bp.s)}]
    if bp.r == bp.s * 4:
        rows.append({"label": "intermediate", "op": "==", "value": _plain(bp.s * 2)})
    elif bp.r != bp.s * 2:
        raise ImportRefused(f"{what}: S {bp.s} and R {bp.r} leave more than one dilution for I")
    rows.append({"label": "resistant", "op": ">=", "value": _plain(bp.r)})
    return rows


def _plain(value: Decimal):
    return int(value) if value == value.to_integral_value() else float(value)


def _rule(spec, drug: str, bp: Breakpoint, host: str | None, species: str, source: str, what: str) -> dict:
    rule = {"organism": spec["organism"], "antibiotic": drug, "method": "MIC"}
    if host is not None:
        rule["host"] = host
    rule.update({"source": source, "breakpoint_species": species, "categories": categories(bp, what)})
    return rule


def build_draft(rows: list[dict], spec: dict, provenance: str) -> dict:
    """The draft table for one spec. Raises ImportRefused on any missing, conflicting or ambiguous rule."""
    rules = []
    codes = spec["organism_codes"]
    for drug, code in spec["drugs"].items():
        what = f"{drug} (human, {spec['human_guideline']})"
        bp = find_breakpoint(rows, spec["human_guideline"], "human", codes, code, what)
        if bp is None:
            raise ImportRefused(f"{what}: no MIC row in the snapshot")
        rules.append(_rule(spec, drug, bp, None, "human", f"{provenance}: {bp.guideline} human row ({bp.organism_code})", what))

    vet = spec.get("vet") or {}
    for group, amr_host in (vet.get("hosts") or {}).items():
        for drug in vet.get("drugs", []):
            code = spec["drugs"][drug]
            what = f"{drug} ({group}, {vet['species_guideline']})"
            bp = None if amr_host is None else find_breakpoint(rows, vet["species_guideline"], amr_host, codes, code, what)
            if bp is not None:
                source = f"{provenance}: {bp.guideline} {amr_host} row ({bp.organism_code})"
                rules.append(_rule(spec, drug, bp, group, group, source, what))
                continue
            # no species row: the veterinary standard's own fallback, its grey human row from the edition it builds on
            what = f"{drug} ({group}, grey row {vet['grey_guideline']})"
            bp = find_breakpoint(rows, vet["grey_guideline"], "human", codes, code, what)
            if bp is None:
                raise ImportRefused(f"{what}: no species row and no human row to fall back to")
            source = f"{provenance}: {bp.guideline} human row used as the grey row ({bp.organism_code})"
            rules.append(_rule(spec, drug, bp, group, "human", source, what))

    rules.sort(key=lambda r: (r.get("host") or "", r["antibiotic"]))
    return {
        "interpretation_version": spec["interpretation_version"] + DRAFT_SUFFIX,
        "standard": spec.get("standard", "CLSI"),
        "rules": rules,
    }


def render_draft(draft: dict, header: list[str]) -> str:
    comments = "".join(f"# {line}\n" for line in header)
    return comments + yaml.safe_dump(draft, sort_keys=False, default_flow_style=None, allow_unicode=True, width=120)


def _rule_key(rule: dict) -> tuple:
    return (rule["antibiotic"], rule.get("host") or "")


def _cats(rule: dict) -> tuple:
    return tuple(sorted((c["label"], c["op"], Decimal(str(c["value"]))) for c in rule["categories"]))


def compare(draft: dict, active: dict) -> list[tuple[str, str, str, str]]:
    """One row per rule: MATCH, DIFFERS, ONLY_IN_DRAFT or ONLY_IN_ACTIVE, with the categories on each side."""
    ours = {_rule_key(r): r for r in active["rules"]}
    theirs = {_rule_key(r): r for r in draft["rules"]}
    report = []
    for key in sorted(set(ours) | set(theirs)):
        name = f"{key[0]} / {key[1] or 'general'}"
        a, d = ours.get(key), theirs.get(key)
        show = lambda r: "" if r is None else " ".join(f"{c['label'][0].upper()}{c['op']}{c['value']}" for c in r["categories"])
        if a is None:
            status = "ONLY_IN_DRAFT"
        elif d is None:
            status = "ONLY_IN_ACTIVE"
        else:
            status = "MATCH" if _cats(a) == _cats(d) else "DIFFERS"
        report.append((name, status, show(a), show(d)))
    return report


def import_one(snapshot: Path, spec_path: Path, out_dir: Path, active_dir: Path = ACTIVE_TABLES) -> tuple[Path, list]:
    if out_dir.resolve() == active_dir.resolve() or active_dir.resolve() in out_dir.resolve().parents:
        raise ImportRefused("the output folder is the active tables folder; drafts are never written there")
    spec = read_spec(spec_path)
    rows = read_snapshot(snapshot)
    digest = sha256_of(snapshot)
    provenance = f"AMR clinical_breakpoints sha256 {digest[:12]}"
    draft = build_draft(rows, spec, provenance)
    header = [
        "DRAFT built by scripts/clsi_import.py from a local snapshot of the AMR R package's clinical_breakpoints data.",
        f"Snapshot: {snapshot.name}, sha256 {digest}; spec {spec_path.name}.",
        "Not reviewed and not active. The guideline year to edition mapping is unconfirmed (data/sources/amr_clinical_breakpoints.yaml).",
        "Do not commit: the values come from the AMR data, whose reuse conditions are still being confirmed.",
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{spec['interpretation_version'].lower()}{DRAFT_SUFFIX.lower()}.yaml"
    target.write_text(render_draft(draft, header), encoding="utf-8")

    report = []
    active_file = active_dir / f"{spec['interpretation_version'].lower()}.yaml"
    if active_file.exists():
        report = compare(draft, yaml.safe_load(active_file.read_text(encoding="utf-8")))
    return target, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build draft interpretation tables from a pinned AMR snapshot.")
    parser.add_argument("--snapshot", required=True, type=Path, help="local clinical_breakpoints.txt (tab-separated)")
    parser.add_argument("--spec", required=True, type=Path, action="append", help="import spec; repeat for several")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where drafts go (never data/interpretation)")
    arguments = parser.parse_args()

    differs = 0
    for spec_path in arguments.spec:
        try:
            target, report = import_one(arguments.snapshot, spec_path, arguments.out)
        except ImportRefused as problem:
            print(f"REFUSED {spec_path.name}: {problem}")
            return 1
        print(f"draft written: {target}")
        if not report:
            print("  no active table of the same name to compare with")
        for name, status, active, draft in report:
            print(f"  {status:<15} {name:<45} active [{active}]  draft [{draft}]")
            differs += status != "MATCH"
    print("all rules match the active tables" if differs == 0 else f"{differs} rule(s) need a person to look at them")
    return 0 if differs == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
