"""I-20 end to end: a later snapshot's evidence is loaded as a new version and its changes are re-evaluated with it.

The world is the committed mini-cohort as release R1. A second snapshot, AMRTRACE_RAW_V2, is written next to it the way
the real V2 differs from V1 (docs/design/change_detection.md, first real comparison):

    AST        every row gets a new id (the id includes the snapshot id); NCBI's row id ("id") is kept.
               Two susceptible results become resistant, one resistant result becomes susceptible, and one result
               only changes its MIC, which the as-reported release does not read.
    genotype   every summary row gets a new id with the same content. One isolate loses the one detailed row that
               supported resistance; another isolate gains a detailed row that supports it.

The snapshot check drafts one AST_CORRECTED and one GENOTYPE_CHANGED change. The genotype draft adds a row, so it
cannot be applied until the snapshot's evidence is loaded. Once loaded, both changes are applied, re-evaluated
selectively and compared with an exhaustive run over the evidence in force, through the commands and through the API.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from tests.z18_test_support import signed_in_client

import amrtrace.policies  # noqa: F401
from amrtrace.api.db import get_connection, get_write_connection
from amrtrace.api.main import app
from amrtrace.deps.selector import UnplacedEvidence
from amrtrace.ingest.baseline_states import read_frozen_baseline
from amrtrace.ingest.compare_change import compare_stored_change
from amrtrace.ingest.evidence_in_force import EvidenceNotInForce, evidence_in_force
from amrtrace.ingest.frozen_v1 import read_frozen_tables
from amrtrace.ingest.load_evidence_version import load_evidence_version
from amrtrace.ingest.load_frozen_v1 import CASE_STATES_FILE, load_frozen_v1
from amrtrace.ingest.materialize_baseline import _organism, _panel, materialize_baseline
from amrtrace.ingest.reevaluate_change import reevaluate_stored_change
from amrtrace.ledger import get_current_state, load_baseline_release
from amrtrace.monitor import apply_draft, default_watchers, list_drafts, open_snapshot, run_check
from amrtrace.reeval import gate_release

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
COHORT = REPO_ROOT / "tests" / "fixtures" / "mini_cohort"
V1 = "AMRTRACE_RAW_V1"
V2 = "AMRTRACE_RAW_V2"
AST_FILE = "curated_v1/ast_evidence_curated.parquet"
GENOTYPE_FILE = "curated_v1/genotype_evidence_curated.parquet"
ISOLATES_FILE = "curated_v1/isolates_curated.parquet"
MAPPING_FILE = "mapping_v1/determinant_drug_mapping_v1.parquet"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _new_id(prefix: str, old_id: str) -> str:
    return prefix + hashlib.sha256(f"{V2}:{old_id}".encode()).hexdigest()


def _rows(name: str) -> tuple[list[dict], pa.Schema]:
    table = pq.read_table(COHORT / name)
    return table.to_pylist(), table.schema


def _picks() -> dict:
    """The cases each edit lands on, chosen from the frozen states so the test follows the fixture."""
    states = pq.read_table(COHORT / CASE_STATES_FILE).to_pylist()
    supported = sorted(
        (s for s in states if s["case_state"] == "CONCORDANT_RESISTANT"
         and s["genotype_representation_used"] == "MICROBIGGE" and len(s["genotype_evidence_ids_supporting"]) == 1),
        key=lambda s: s["case_id"],
    )
    loses = supported[0]
    resistant = sorted((s for s in states if s["case_state"] == "CONCORDANT_RESISTANT" and s is not loses
                        and s["target_acc"] != loses["target_acc"]), key=lambda s: s["case_id"])
    susceptible = sorted((s for s in states if s["case_state"] == "CONCORDANT_SUSCEPTIBLE"
                          and s["genotype_analysis_valid"]), key=lambda s: s["case_id"])
    return {
        "to_resistant": susceptible[0:2],
        "to_susceptible": resistant[0:1],
        "mic_only": susceptible[2:3],
        "gains": susceptible[3],
        "loses": loses,
        "lost_row": loses["genotype_evidence_ids_supporting"][0],
    }


def write_v2(folder: Path, picks: dict) -> dict:
    """Writes the V2 snapshot folder; returns the case ids each edit lands on."""
    ast_rows, ast_schema = _rows(AST_FILE)
    flips = {s["ast_evidence_ids"][0]: "R" for s in picks["to_resistant"]}
    flips.update({s["ast_evidence_ids"][0]: "S" for s in picks["to_susceptible"]})
    mic_only = {s["ast_evidence_ids"][0] for s in picks["mic_only"]}
    words = {"R": "resistant", "S": "susceptible"}
    for row in ast_rows:
        old_id = row["ast_evidence_id"]
        row["ast_evidence_id"] = _new_id("ASTV2_", old_id)
        row["source_snapshot_id"] = V2
        if old_id in flips:
            row["phenotype_normalized"] = flips[old_id]
            row["phenotype"] = row["phenotype_raw"] = words[flips[old_id]]
            row["checksum"] = _new_id("", old_id)[:32]
        if old_id in mic_only:
            row["mic"] = (row["mic"] or 1.0) * 2

    genotype_rows, genotype_schema = _rows(GENOTYPE_FILE)
    lost = next(r for r in genotype_rows if r["genotype_evidence_id"] == picks["lost_row"])
    gained = dict(lost, target_acc=picks["gains"]["target_acc"])
    gained["genotype_evidence_id"] = _new_id("GMV2_", lost["genotype_evidence_id"])
    gained["source_row_signature_sha256"] = gained["genotype_evidence_id"][5:]
    kept = []
    for row in genotype_rows:
        if row is lost:
            continue
        if row["representation_source"] == "ISOLATE_AMR_SUMMARY":
            row["genotype_evidence_id"] = _new_id("GSV2_", row["genotype_evidence_id"])
        row["source_snapshot_id"] = V2
        kept.append(row)
    gained["source_snapshot_id"] = V2
    kept.append(gained)

    isolate_rows, isolate_schema = _rows(ISOLATES_FILE)
    for row in isolate_rows:
        row["source_snapshot_id"] = V2

    for name, rows, schema in ((AST_FILE, ast_rows, ast_schema), (GENOTYPE_FILE, kept, genotype_schema),
                               (ISOLATES_FILE, isolate_rows, isolate_schema)):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), folder / name)
    (folder / MAPPING_FILE).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(COHORT / MAPPING_FILE, folder / MAPPING_FILE)
    files = (AST_FILE, GENOTYPE_FILE, ISOLATES_FILE, MAPPING_FILE)
    (folder / "sha256.txt").write_text("".join(f"{_sha256(folder / f)}  {f}\n" for f in files), encoding="utf-8")
    (folder / "snapshot.json").write_text(json.dumps({"snapshot_id": V2}), encoding="utf-8")
    return {
        "ast": sorted(s["case_id"] for s in picks["to_resistant"] + picks["to_susceptible"] + picks["mic_only"]),
        "ast_state_changes": sorted(s["case_id"] for s in picks["to_resistant"] + picks["to_susceptible"]),
        "genotype": sorted([picks["gains"]["case_id"], picks["loses"]["case_id"]]),
        "gained_row": gained["genotype_evidence_id"],
    }


def build_world(conn, tmp_path: Path):
    tables = read_frozen_tables(COHORT)
    load_frozen_v1(conn, COHORT, COHORT / "sha256.txt")
    vector, states = read_frozen_baseline(str(COHORT / CASE_STATES_FILE))
    load_baseline_release(conn, "R1", vector, states, expected_count=len(states))
    panel, organism = _panel(conn), _organism(conn)
    materialize_baseline(conn, tables, "R1", panel, organism)

    expected = write_v2(tmp_path / V2, _picks())
    old, new = open_snapshot(COHORT), open_snapshot(tmp_path / V2)
    run_check(conn, default_watchers(), old, new)
    drafts = {d.change_type: d for d in list_drafts(conn, status="PENDING")}
    return tables, panel, organism, old, new, drafts, expected


@pytest.fixture
def world(conn, tmp_path):
    return conn, *build_world(conn, tmp_path)


def _evidence_read(conn, release_id, case_id, table, id_column, column):
    return conn.execute(
        f"SELECT e.{column}, e.source_snapshot_id FROM dependency d JOIN {table} e ON e.{id_column} = d.node_id "
        "WHERE d.release_id = %s AND d.case_id = %s AND d.node_type = %s ORDER BY 1",
        (release_id, case_id, table),
    ).fetchall()


def test_the_check_drafts_only_the_rows_that_changed(world):
    conn, tables, panel, organism, old, new, drafts, expected = world
    assert set(drafts) == {"AST_CORRECTED", "GENOTYPE_CHANGED"}
    ast = drafts["AST_CORRECTED"]
    assert (ast.summary["rows_edited"], ast.summary["rows_added"], ast.summary["rows_removed"]) == (4, 0, 0)
    genotype = drafts["GENOTYPE_CHANGED"]
    assert (genotype.summary["rows_added"], genotype.summary["rows_removed"]) == (1, 1)


def test_a_draft_that_adds_a_row_waits_for_the_evidence_to_be_loaded(world):
    conn, tables, panel, organism, old, new, drafts, expected = world
    with pytest.raises(UnplacedEvidence):
        apply_draft(conn, drafts["GENOTYPE_CHANGED"].draft_id, decided_by="tester")

    report = load_evidence_version(conn, old, new)
    loaded = {t.table: (t.added, t.edited, t.removed, t.loaded) for t in report.tables}
    # only the four edited AST rows and the one added detailed row are stored; the other new ids are not copied
    assert loaded == {"ast_evidence": (0, 4, 0, 4), "genotype_evidence": (1, 0, 1, 1)}
    application = apply_draft(conn, drafts["GENOTYPE_CHANGED"].draft_id, decided_by="tester")
    assert sorted(item.case_id for item in application.items) == expected["genotype"]

    again = load_evidence_version(conn, old, new)
    assert again.loaded == 0 and sum(t.already_stored for t in again.tables) == 5


def test_an_evidence_change_is_re_evaluated_with_the_new_rows_and_equals_exhaustive(world):
    conn, tables, panel, organism, old, new, drafts, expected = world
    load_evidence_version(conn, old, new)
    ast_change = apply_draft(conn, drafts["AST_CORRECTED"].draft_id, decided_by="tester", change_id="CHG-AST-V2")
    assert sorted(item.case_id for item in ast_change.items) == expected["ast"]

    selective = reevaluate_stored_change(conn, tables, "CHG-AST-V2", "R2", panel, organism, publish=False)
    assert selective.status == "COMPLETE" and selective.reevaluated == 4 and selective.state_changed == 3
    report = compare_stored_change(conn, tables, "CHG-AST-V2", panel, organism, store=True)
    assert report.passed, report.to_json()
    assert (report.total_cases, report.selected, report.affected, report.missed) == (660, 4, 4, 0)
    assert report.state_changed == 3 and report.recall == 1.0
    assert gate_release(conn, report) == "PUBLISHED"

    vector = conn.execute("SELECT version_vector FROM release WHERE release_id = 'R2'").fetchone()[0]
    assert vector["evidence_changes"] == ["CHG-AST-V2"] and vector["source_snapshot_id"] == V1
    for case_id in expected["ast_state_changes"]:
        assert get_current_state(conn, case_id).release_id == "R2"
        # the release reads the corrected row of V2, not the V1 row
        [(_, snapshot)] = _evidence_read(conn, "R2", case_id, "ast_evidence", "ast_evidence_id", "phenotype_normalized")
        assert snapshot == V2

    # the second change starts from R2, so the AST corrections stay in force while the genotype change is checked
    genotype_change = apply_draft(conn, drafts["GENOTYPE_CHANGED"].draft_id, decided_by="tester",
                                  change_id="CHG-GENOTYPE-V2")
    assert sorted(item.case_id for item in genotype_change.items) == expected["genotype"]
    reevaluate_stored_change(conn, tables, "CHG-GENOTYPE-V2", "R3", panel, organism, publish=False)
    report = compare_stored_change(conn, tables, "CHG-GENOTYPE-V2", panel, organism, store=True)
    assert report.passed, report.to_json()
    assert (report.selected, report.affected, report.state_changed, report.missed) == (2, 2, 2, 0)
    assert gate_release(conn, report) == "PUBLISHED"
    vector = conn.execute("SELECT version_vector FROM release WHERE release_id = 'R3'").fetchone()[0]
    assert vector["evidence_changes"] == ["CHG-AST-V2", "CHG-GENOTYPE-V2"]
    gains = next(c for c in expected["genotype"] if _evidence_read(
        conn, "R3", c, "genotype_evidence", "genotype_evidence_id", "genotype_evidence_id"))
    assert (expected["gained_row"], V2) in _evidence_read(
        conn, "R3", gains, "genotype_evidence", "genotype_evidence_id", "genotype_evidence_id")


def test_a_change_whose_snapshot_is_not_loaded_is_refused_before_anything_is_written(world):
    conn, tables, panel, organism, old, new, drafts, expected = world
    # an AST edit names stored V1 rows, so it can be applied; its new values are not stored yet
    apply_draft(conn, drafts["AST_CORRECTED"].draft_id, decided_by="tester", change_id="CHG-AST-V2")
    with pytest.raises(EvidenceNotInForce, match="load the evidence"):
        reevaluate_stored_change(conn, tables, "CHG-AST-V2", "R2", panel, organism, publish=False)
    assert conn.execute("SELECT count(*) FROM release WHERE release_id = 'R2'").fetchone()[0] == 0


def test_the_loader_compares_from_the_snapshot_the_release_in_force_reads(world):
    conn, tables, panel, organism, old, new, drafts, expected = world
    with pytest.raises(ValueError, match="reads snapshot AMRTRACE_RAW_V1"):
        load_evidence_version(conn, new, old)


def test_no_evidence_change_listed_leaves_the_frozen_rows_as_they_are(world):
    conn, tables, *_ = world
    assert evidence_in_force(conn, tables, None) is tables
    assert evidence_in_force(conn, tables, []) is tables


# ---------- the same changes through the API, which reads the source rows from the database ----------

@pytest.fixture
def scratch_world(scratch_database_url, tmp_path):
    connection = psycopg.connect(scratch_database_url)
    try:
        world = build_world(connection, tmp_path)
        connection.commit()
        yield connection, *world
    finally:
        connection.close()


@pytest.fixture
def client(scratch_world):
    conn = scratch_world[0]

    def override():
        yield conn

    app.dependency_overrides[get_connection] = override
    app.dependency_overrides[get_write_connection] = override
    try:
        with TestClient(app) as test_client:
            # re-evaluation with the gate needs a signed-in Admin since Z-18
            yield signed_in_client(test_client, conn, role="ADMIN", username="evidenceadmin")
    finally:
        app.dependency_overrides.pop(get_connection, None)
        app.dependency_overrides.pop(get_write_connection, None)


def test_the_api_re_evaluates_evidence_changes_with_the_evidence_in_force(scratch_world, client):
    conn, tables, panel, organism, old, new, drafts, expected = scratch_world
    load_evidence_version(conn, old, new)
    for change_type, change_id, release_id, selected in (
        ("AST_CORRECTED", "CHG-AST-V2", "R2", expected["ast"]),
        ("GENOTYPE_CHANGED", "CHG-GENOTYPE-V2", "R3", expected["genotype"]),
    ):
        apply_draft(conn, drafts[change_type].draft_id, decided_by="tester", change_id=change_id)
        conn.commit()
        response = client.post(
            f"/changes/{change_id}/reevaluate",
            json={"release_id": release_id, "run_exhaustive": True, "gate": True},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["selective_run"]["selected_count"] == len(selected)
        assert body["equivalence"]["passed"] is True, body["equivalence"]
        assert body["equivalence"]["missed"] == 0
        assert body["equivalence"]["gate_status"] == "PUBLISHED"
        conn.commit()
    vector = conn.execute("SELECT version_vector FROM release WHERE release_id = 'R3'").fetchone()[0]
    assert vector["evidence_changes"] == ["CHG-AST-V2", "CHG-GENOTYPE-V2"]
