"""The real-data runner itself, tested on a tiny stand-in world. The real CLSI-REAL run is the CLI (see real_data.py)."""

import pytest
import yaml
from psycopg.types.json import Jsonb

from . import real_data
from amrtrace.changes import register_version
from .real_data import RealDataSetupError, main, render, run

RK = "std|org|drug|mic"


def build(conn, vector=None, cases=None, register=True):
    """Cases with exact MICs 1, 2, 4, 8, 16, 32 and one censored '>=8', all evaluated under table T32."""
    cases = cases or {"M1": (1, "=="), "M2": (2, "=="), "M4": (4, "=="), "M8": (8, "=="),
                      "M16": (16, "=="), "M32": (32, "=="), "G8": (8, ">=")}
    for case, (mic, sign) in cases.items():
        conn.execute("INSERT INTO isolate (target_acc) VALUES (%s)", ("PDT_" + case,))
        conn.execute('INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s,%s,%s,%s)',
                     (case, "PDT_" + case, "gentamicin", "P"))
    if register:
        register_version(conn, "interpretation_rule", RK, "T32")
        register_version(conn, "interpretation_rule", RK, "T33")
    conn.execute("INSERT INTO release (release_id, version_vector, status) VALUES ('R2', %s, 'DRAFT')",
                 (Jsonb(vector if vector is not None else {"interpretation_version": "T32"}),))
    for case, (mic, sign) in cases.items():
        conn.execute("INSERT INTO case_state (case_id, release_id, state_code, explanation, verification_status) "
                     "VALUES (%s,'R2','UNRESOLVED','{}','EVALUATED')", (case,))
        conn.execute(
            "INSERT INTO dependency (case_id, release_id, dep_type, edge_type, node_type, node_id, node_version, node_context) "
            "VALUES (%s,'R2','input_evidence','derived_from','interpretation_rule',%s,'T32',%s)",
            (case, RK, Jsonb({"mic": float(mic), "sign": sign})))
    conn.execute("UPDATE release SET status='PUBLISHED' WHERE release_id='R2'")


def fixture(required=("M4", "M8"), forbidden=("M1",), **extra):
    fx = {
        "scenario": "STANDIN", "real_data": True,
        "change_event": {
            "change_id": "CHG-STANDIN", "type": "INTERPRETATION_VERSION", "old_version": "T32", "new_version": "T33",
            "changed_entities": [{"node_type": "interpretation_rule", "node_id": RK, "old_version": "T32",
                                  "new_version": "T33", "changed_region": {"field": "mic", "intervals": [[2, 4], [8, 16]]}}]},
        "expected": {"required_case_ids": list(required), "allowed_extra_case_ids": [],
                     "must_not_select_case_ids": list(forbidden)},
    }
    fx.update(extra)
    return fx


def test_passes_when_every_required_case_is_selected(conn):
    build(conn)
    result = run(conn, fixture())
    assert result.passed and result.recall == 1.0 and result.missing == ()
    # closed bounds over-select 2 and 16, and the censored '>=8' overlaps [8, 16]: reported, not failed
    assert result.outside_expected == 3 and result.selected == 5
    assert result.newly_registered
    assert conn.execute("SELECT level2_size FROM impact_set WHERE change_id = 'CHG-STANDIN'").fetchone()[0] == 5


def test_fails_and_names_the_missing_case_when_the_selector_misses_one(conn):
    build(conn)

    def blind_to_eight(conn_, change_id):
        real = real_data.select_impact_detailed(conn_, change_id)
        kept = tuple(i for i in real.items if i.case_id != "M8")
        return type(real)(real.change_id, real.release_id, kept, real.level1_size, len(kept))

    result = run(conn, fixture(), selector=blind_to_eight)
    assert not result.passed and result.missing == ("M8",) and result.recall == 0.5
    assert "MISSING 1 required cases, first: M8" in render(result) and render(result).endswith("FAIL")


def test_fails_when_a_must_not_select_case_is_selected(conn):
    build(conn)
    result = run(conn, fixture(forbidden=("M16",)))
    assert not result.passed and result.forbidden_selected == ("M16",)


def test_stops_when_the_release_was_not_evaluated_with_the_old_table(conn):
    build(conn, vector={"interpretation_version": None})
    with pytest.raises(RealDataSetupError, match="was not evaluated with T32"):
        run(conn, fixture())
    assert conn.execute("SELECT count(*) FROM change_event").fetchone()[0] == 0


def test_stops_when_a_required_case_is_not_in_the_release(conn):
    build(conn)
    with pytest.raises(RealDataSetupError, match="not in release R2"):
        run(conn, fixture(required=("M4", "M8", "NOT_HERE")))


def test_stops_when_the_new_table_version_is_not_stored(conn):
    build(conn, register=False)
    register_version(conn, "interpretation_rule", RK, "T32")      # the old table is stored, the new one is not
    with pytest.raises(RealDataSetupError, match="T33"):
        run(conn, fixture())
    assert conn.execute("SELECT count(*) FROM change_event").fetchone()[0] == 0


def test_stops_when_there_is_no_published_release(conn):
    with pytest.raises(RealDataSetupError, match="no published release"):
        run(conn, fixture())


def test_an_already_registered_change_is_selected_again_without_storing_twice(conn):
    build(conn)
    run(conn, fixture())
    again = run(conn, fixture())
    assert again.passed and not again.newly_registered
    assert conn.execute("SELECT count(*) FROM impact_set").fetchone()[0] == 1


def _cli(conn, tmp_path, fx, *args):
    path = tmp_path / "fx.yaml"
    path.write_text(yaml.safe_dump(fx), encoding="utf-8")
    return main(["--fixture", str(path), *args], conn=conn)


def test_cli_rolls_back_by_default(conn, tmp_path, capsys):
    build(conn)
    assert _cli(conn, tmp_path, fixture()) == 0
    assert "PASS" in capsys.readouterr().out
    assert conn.execute("SELECT count(*) FROM change_event").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM impact_set").fetchone()[0] == 0


def test_cli_keeps_the_change_with_commit(conn, tmp_path):
    build(conn)
    assert _cli(conn, tmp_path, fixture(), "--commit") == 0
    assert conn.execute("SELECT count(*) FROM change_event").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM impact_item").fetchone()[0] == 5


def test_cli_exit_codes(conn, tmp_path, capsys):
    build(conn)
    assert _cli(conn, tmp_path, fixture(forbidden=("M16",))) == 1          # judged and failed
    assert _cli(conn, tmp_path, fixture(required=("NOPE",))) == 2          # could not judge
    assert _cli(conn, tmp_path, fixture(real_data=False)) == 2             # wrong kind of fixture
    assert "STOP" in capsys.readouterr().out
