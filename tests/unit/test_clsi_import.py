# A-23: the AMR snapshot importer, on a synthetic snapshot; every value and guideline label here is made up, so no
# AMR or CLSI breakpoint is stored in the repository

import importlib.util
from pathlib import Path

import pytest
import yaml

from amrtrace.interpretation import load_table

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "clsi_import.py"
spec_ = importlib.util.spec_from_file_location("clsi_import", SCRIPT)
clsi_import = importlib.util.module_from_spec(spec_)
spec_.loader.exec_module(clsi_import)

HEADER = ["guideline", "type", "host", "method", "site", "mo", "rank_index", "ab", "ref_tbl", "disk_dose",
          "breakpoint_S", "breakpoint_R", "uti", "is_SDD", "note"]
SPECIES, GROUP = "B_SYNTH_SPECIES", "B_[ORD]_SYNTH"

# synthetic rows: drug A has an I (R = 4 S), drug B has none (R = 2 S); one animal species row for drug A
ROWS = [
    ("SYNTH 2091", "human", "human", "MIC", GROUP, "AAA", "3", "12"),
    ("SYNTH 2091", "human", "human", "MIC", SPECIES, "BBB", "5", "10"),
    ("SYNTH 2090", "human", "human", "MIC", GROUP, "AAA", "6", "24"),
    ("SYNTH 2090", "human", "human", "MIC", GROUP, "BBB", "5", "10"),
    ("SYNTH 2092", "animal", "foxes", "MIC", GROUP, "AAA", "1.5", "6"),
]


def write_snapshot(folder: Path, rows=ROWS, extra=()) -> Path:
    lines = ["\t".join(f'"{h}"' for h in HEADER)]
    for guideline, rtype, host, method, mo, ab, s, r, *flags in [*rows, *extra]:
        uti, sdd = (flags + ["FALSE", "FALSE"])[:2]
        lines.append("\t".join([f'"{guideline}"', f'"{rtype}"', f'"{host}"', f'"{method}"', "", f'"{mo}"', "1",
                                f'"{ab}"', '"synthetic"', "", s, r, uti, sdd, '""']))
    path = folder / "snapshot.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_spec(folder: Path, name="SYNTH_TABLE", vet=True) -> Path:
    spec = {
        "interpretation_version": name, "standard": "CLSI", "organism": "Synthetica coli",
        "organism_codes": [SPECIES, GROUP], "human_guideline": "SYNTH 2091",
        "drugs": {"drug-a": "AAA", "drug-b": "BBB"},
    }
    if vet:
        spec["vet"] = {"species_guideline": "SYNTH 2092", "grey_guideline": "SYNTH 2090", "drugs": ["drug-a", "drug-b"],
                       "hosts": {"fox": "foxes", "owl": None}}
    path = folder / f"{name.lower()}.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def world(tmp_path):
    active = tmp_path / "active"
    active.mkdir()
    return tmp_path, write_snapshot(tmp_path), write_spec(tmp_path), active, tmp_path / "drafts"


def rules_by_key(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {(r["antibiotic"], r.get("host")): r for r in data["rules"]}


def test_the_draft_loads_as_a_table_and_derives_i_from_the_dilution_between_s_and_r(world):
    _, snapshot, spec, active, out = world
    target, _ = clsi_import.import_one(snapshot, spec, out, active)
    table = load_table(str(target))
    assert table.interpretation_version == "SYNTH_TABLE_AMR_DRAFT"
    rules = rules_by_key(target)
    assert rules[("drug-a", None)]["categories"] == [
        {"label": "susceptible", "op": "<=", "value": 3},
        {"label": "intermediate", "op": "==", "value": 6},
        {"label": "resistant", "op": ">=", "value": 12},
    ]
    assert [c["label"] for c in rules[("drug-b", None)]["categories"]] == ["susceptible", "resistant"]


def test_a_species_row_is_used_where_one_exists_and_the_grey_row_elsewhere(world):
    _, snapshot, spec, active, out = world
    rules = rules_by_key(clsi_import.import_one(snapshot, spec, out, active)[0])
    fox_a, fox_b, owl_a = rules[("drug-a", "fox")], rules[("drug-b", "fox")], rules[("drug-a", "owl")]
    assert fox_a["breakpoint_species"] == "fox" and fox_a["categories"][0]["value"] == 1.5
    assert "foxes row" in fox_a["source"]
    assert fox_b["breakpoint_species"] == "human" and "grey row" in fox_b["source"]
    assert owl_a["breakpoint_species"] == "human" and owl_a["categories"][0]["value"] == 6


def test_the_same_snapshot_gives_the_same_bytes(world):
    tmp_path, snapshot, spec, active, _ = world
    first, _ = clsi_import.import_one(snapshot, spec, tmp_path / "one", active)
    second, _ = clsi_import.import_one(snapshot, spec, tmp_path / "two", active)
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize("extra, message", [
    ([("SYNTH 2091", "human", "human", "MIC", GROUP, "AAA", "4", "16")], "different breakpoints"),
    ([("SYNTH 2091", "human", "human", "MIC", SPECIES, "AAA", "1", "16")], "more than one dilution"),
    ([("SYNTH 2091", "human", "human", "MIC", SPECIES, "AAA", "2", "8", "FALSE", "TRUE")], "dose-dependent"),
])
def test_a_conflicting_or_ambiguous_row_is_refused_and_nothing_is_written(world, extra, message):
    tmp_path, _, spec, active, out = world
    snapshot = write_snapshot(tmp_path, extra=extra)
    with pytest.raises(clsi_import.ImportRefused, match=message):
        clsi_import.import_one(snapshot, spec, out, active)
    assert not out.exists() or not any(out.iterdir())


def test_a_urinary_only_row_is_ignored(world):
    tmp_path, _, spec, active, out = world
    snapshot = write_snapshot(tmp_path, extra=[("SYNTH 2091", "human", "human", "MIC", SPECIES, "AAA", "1", "2", "TRUE")])
    rules = rules_by_key(clsi_import.import_one(snapshot, spec, out, active)[0])
    assert rules[("drug-a", None)]["categories"][0]["value"] == 3


def test_a_drug_missing_from_the_snapshot_is_refused(world):
    tmp_path, _, spec, active, out = world
    snapshot = write_snapshot(tmp_path, rows=[r for r in ROWS if not (r[0] == "SYNTH 2091" and r[5] == "BBB")])
    with pytest.raises(clsi_import.ImportRefused, match="drug-b"):
        clsi_import.import_one(snapshot, spec, out, active)


# the canary: an active table that agrees, then a snapshot with one corrupted threshold; only that rule is flagged
def test_a_corrupted_threshold_is_flagged_against_the_active_table(world):
    tmp_path, snapshot, spec, active, out = world
    good, _ = clsi_import.import_one(snapshot, spec, out, active)
    reviewed = yaml.safe_load(good.read_text(encoding="utf-8"))
    reviewed["interpretation_version"] = "SYNTH_TABLE"
    (active / "synth_table.yaml").write_text(yaml.safe_dump(reviewed, sort_keys=False), encoding="utf-8")

    _, report = clsi_import.import_one(snapshot, spec, out, active)
    assert {status for _, status, _, _ in report} == {"MATCH"}

    corrupted = [r if not (r[0] == "SYNTH 2091" and r[5] == "AAA") else r[:6] + ("3", "24") for r in ROWS]
    with pytest.raises(clsi_import.ImportRefused, match="more than one dilution"):
        clsi_import.import_one(write_snapshot(tmp_path, rows=corrupted), spec, out, active)
    shifted = [r if not (r[0] == "SYNTH 2091" and r[5] == "AAA") else r[:6] + ("6", "24") for r in ROWS]
    _, report = clsi_import.import_one(write_snapshot(tmp_path, rows=shifted), spec, out, active)
    flagged = [(name, status) for name, status, _, _ in report if status != "MATCH"]
    assert flagged == [("drug-a / general", "DIFFERS")]


def test_drafts_are_never_written_into_the_active_tables_folder(world):
    _, snapshot, spec, active, _ = world
    with pytest.raises(clsi_import.ImportRefused, match="never written there"):
        clsi_import.import_one(snapshot, spec, active, active)
    with pytest.raises(clsi_import.ImportRefused, match="never written there"):
        clsi_import.import_one(snapshot, spec, active / "sub", active)
    assert list(active.iterdir()) == []


def test_the_committed_specs_name_every_active_table_and_hold_no_breakpoints():
    root = SCRIPT.parents[1]
    specs = sorted((root / "data" / "sources" / "clsi_import").glob("*.yaml"))
    actives = {p.stem for p in (root / "data" / "interpretation").glob("clsi_*.yaml")}
    assert {p.stem for p in specs} == actives
    for path in specs:
        text = path.read_text(encoding="utf-8")
        assert "breakpoint_S" not in text and "categories" not in text
