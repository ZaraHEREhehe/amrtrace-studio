# task A-18: the source check raises alerts for what a person must act on, and drafts a table change once entered
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from amrtrace.api.db import get_connection, get_write_connection
from amrtrace.api.main import app
from amrtrace.changes import get_change_event
from amrtrace.changes.service import get_impact_set
from amrtrace.ingest.baseline_states import read_frozen_baseline
from amrtrace.ingest.frozen_v1 import read_frozen_tables
from amrtrace.ingest.load_frozen_v1 import CASE_STATES_FILE, load_frozen_v1
from amrtrace.ingest.materialize_baseline import _organism, _panel, materialize_baseline
from amrtrace.interpretation import store_table
from amrtrace.interpretation.loader import load_table
from amrtrace.ledger import load_baseline_release
from amrtrace.monitor import (
    ACKNOWLEDGED,
    OPEN,
    AlertAlreadyAcknowledged,
    AlertError,
    acknowledge_alert,
    apply_draft,
    default_watchers,
    get_draft,
    list_alerts,
    list_drafts,
    open_snapshot,
    record_alerts,
    run_check,
    store_drafts,
)
from amrtrace.monitor.source_check import (
    DATABASE_NOT_IN_MAPPING,
    NEW_STANDARD_EDITION,
    NEWER_SOFTWARE,
    SNAPSHOT_DATABASE_NOT_IN_MAPPING,
    check_amrfinderplus,
    check_sources,
    check_standards,
    main,
)
from amrtrace.monitor.sources import (
    Edition,
    Release,
    Standard,
    ToolReleases,
    write_catalogue,
    write_releases,
)
from tests.monitor_snapshots import MINI_COHORT, make_snapshot

pytestmark = pytest.mark.integration

TABLES = Path(__file__).resolve().parents[2] / "data" / "interpretation"
ED32, ED33, ED33_VET = "CLSI_M100_ED32", "CLSI_M100_ED33", "CLSI_M100_ED33_VET01S_ED7"
FILES = {ED32: "clsi_m100_ed32.yaml", ED33: "clsi_m100_ed33.yaml", ED33_VET: "clsi_m100_ed33_vet01s_ed7.yaml"}
NO_RELEASES = ToolReleases(None, None)


def catalogue(m100=(32, 33), vet01s=(7,)):
    return [
        Standard("CLSI", "M100", "https://example.org/M100", tuple(Edition(e) for e in m100)),
        Standard("CLSI", "VET01S", "https://example.org/VET01S", tuple(Edition(e) for e in vet01s)),
    ]


def store(conn, *versions):
    for version in versions:
        store_table(conn, load_table(str(TABLES / FILES[version])))


def publish(conn, release_id, interpretation_version, software="4.2.7"):
    vector = {"interpretation_version": interpretation_version, "amrfinderplus_version": software}
    conn.execute(
        "INSERT INTO release (release_id, version_vector, status) VALUES (%s, %s, 'PUBLISHED')",
        (release_id, Jsonb(vector)),
    )


def kinds(findings):
    return sorted((a.kind, a.subject) for a in findings.alerts)


# standards


def test_a_newer_edition_with_no_stored_table_raises_an_alert(conn):
    store(conn, ED32)
    publish(conn, "R_SRC_1", ED32)

    found = check_standards(conn, catalogue(m100=(32, 33, 34)))

    assert kinds(found) == [(NEW_STANDARD_EDITION, "CLSI M100 Ed34"), (NEW_STANDARD_EDITION, "CLSI VET01S Ed7")]
    m100 = next(a for a in found.alerts if a.subject == "CLSI M100 Ed34")
    assert m100.details["edition_in_force"] == 32
    assert m100.details["editions_skipped"] == [33]
    assert found.table_drafts == ()


def test_the_table_in_force_holding_the_newest_edition_raises_nothing(conn):
    store(conn, ED33_VET)
    publish(conn, "R_SRC_1", ED33_VET)

    found = check_standards(conn, catalogue(m100=(32, 33)))

    assert found.alerts == () and found.table_drafts == ()


# once a person stores the new table, the alert stops and the change is drafted instead
def test_a_stored_newer_table_is_drafted_instead_of_alerted(conn):
    store(conn, ED32, ED33)
    publish(conn, "R_SRC_1", ED32)

    found = check_standards(conn, catalogue(m100=(32, 33), vet01s=()))

    assert found.alerts == ()
    [item] = found.table_drafts
    assert (item.old_table, item.new_table, item.draft.change_type) == (ED32, ED33, "INTERPRETATION_VERSION")
    assert item.draft.summary["rules_changed"] == len(item.draft.changed_entities) > 0
    assert {e.node_type for e in item.draft.changed_entities} == {"interpretation_rule"}


def test_a_table_that_adds_a_standard_is_drafted(conn):
    store(conn, ED33, ED33_VET)
    publish(conn, "R_SRC_1", ED33)

    [item] = check_standards(conn, catalogue(m100=(33,), vet01s=(7,))).table_drafts

    assert item.new_table == ED33_VET
    assert item.draft.summary["rules_added"] > 0


def test_a_table_draft_is_stored_once_and_applying_it_ends_the_draft(conn):
    store(conn, ED32, ED33)
    publish(conn, "R_SRC_1", ED32)
    [item] = check_standards(conn, catalogue()).table_drafts

    first = store_drafts(conn, [item.draft], item.old_table, item.new_table)
    again = store_drafts(conn, [item.draft], item.old_table, item.new_table)
    assert len(first.created) == 1 and again.already_drafted == first.created

    application = apply_draft(conn, first.created[0], decided_by="aabia")
    event = get_change_event(conn, application.change_id).event
    assert (event.type, event.old_version, event.new_version) == ("INTERPRETATION_VERSION", ED32, ED33)
    assert get_draft(conn, first.created[0]).status == "APPLIED"
    # the change now exists, so a later check does not draft it again
    assert check_standards(conn, catalogue()).table_drafts == ()


# AMRFinderPlus


def map_database(conn, version):
    conn.execute("INSERT INTO antibiotic (antibiotic, in_panel) VALUES ('drug_x', true) ON CONFLICT DO NOTHING")
    conn.execute(
        "INSERT INTO mapping_rule (mapping_rule_id, mapping_version, source_db_version, determinant_identity, "
        "candidate_antibiotic, rule_status) VALUES (%s, 'MAPPING_TEST', %s, 'gene_x', 'drug_x', 'ACTIVE')",
        (f"RULE_{version}", version),
    )


def test_a_published_database_the_mapping_does_not_cover_raises_an_alert(conn):
    map_database(conn, "2026-08-07.1")
    publish(conn, "R_SRC_1", ED32)

    covered = check_amrfinderplus(conn, ToolReleases(None, Release("2026-08-07.1")))
    missing = check_amrfinderplus(conn, ToolReleases(None, Release("2026-10-02.1")))

    assert covered.alerts == ()
    assert kinds(missing) == [(DATABASE_NOT_IN_MAPPING, "AMRFinderPlus database 2026-10-02.1")]


def test_newer_software_than_the_release_used_raises_an_alert(conn):
    publish(conn, "R_SRC_1", ED32, software="4.2.7")

    assert check_amrfinderplus(conn, ToolReleases(Release("4.2.7"), None)).alerts == ()
    assert check_amrfinderplus(conn, ToolReleases(Release("4.10.0"), None)).alerts[0].kind == NEWER_SOFTWARE


def test_a_snapshot_using_an_unmapped_database_raises_an_alert(conn, tmp_path):
    for version in ("2026-03-24.1", "2026-05-15.1", "Z14_C6_REF_V1"):
        map_database(conn, version)

    def rerun(rows):
        return [dict(r, refgene_db_version="2099-01-01.1") if i < 2 else r for i, r in enumerate(rows)]

    snapshot = open_snapshot(make_snapshot(tmp_path, "AMRTRACE_TEST_V2", {"curated_v1/isolates_curated.parquet": rerun}))

    assert check_amrfinderplus(conn, NO_RELEASES, open_snapshot(MINI_COHORT)).alerts == ()
    [alert] = check_amrfinderplus(conn, NO_RELEASES, snapshot).alerts
    assert alert.kind == SNAPSHOT_DATABASE_NOT_IN_MAPPING
    assert alert.details["isolates"] == 2


# storing and acknowledging alerts


def raised(conn):
    store(conn, ED32)
    publish(conn, "R_SRC_1", ED32)
    findings = check_sources(conn, catalogue(m100=(32, 33)), NO_RELEASES)
    return findings, record_alerts(conn, list(findings.alerts))


def test_an_alert_found_again_is_not_stored_twice(conn):
    findings, (created, existing) = raised(conn)
    assert len(created) == len(findings.alerts) == 2 and existing == ()

    assert record_alerts(conn, list(findings.alerts)) == ((), created)
    assert {a.status for a in list_alerts(conn)} == {OPEN}


def test_an_alert_is_acknowledged_once_by_a_named_person(conn):
    _, (created, _) = raised(conn)

    with pytest.raises(AlertError):
        acknowledge_alert(conn, created[0], acknowledged_by=" ")
    alert = acknowledge_alert(conn, created[0], acknowledged_by="insharah", note="table requested")
    assert (alert.status, alert.acknowledged_by) == (ACKNOWLEDGED, "insharah")
    with pytest.raises(AlertAlreadyAcknowledged):
        acknowledge_alert(conn, created[0], acknowledged_by="insharah")


def test_the_database_refuses_to_edit_or_delete_an_alert(conn):
    _, (created, _) = raised(conn)

    for statement in (
        "UPDATE source_alert SET message = 'changed' WHERE alert_id = %s",
        "DELETE FROM source_alert WHERE alert_id = %s",
    ):
        conn.execute("SAVEPOINT attempt")
        with pytest.raises(psycopg.errors.RestrictViolation):
            conn.execute(statement, (created[0],))
        conn.execute("ROLLBACK TO SAVEPOINT attempt")


# the API


@pytest.fixture
def client(conn):
    def same_connection():
        yield conn

    app.dependency_overrides[get_connection] = same_connection
    app.dependency_overrides[get_write_connection] = same_connection
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_connection, None)
        app.dependency_overrides.pop(get_write_connection, None)


def test_the_api_lists_and_acknowledges_alerts(client, conn):
    _, (created, _) = raised(conn)

    listed = client.get("/alerts", params={"status": "OPEN"}).json()
    assert {a["alert_id"] for a in listed} == set(created)
    assert client.get(f"/alerts/{created[0]}").json()["kind"] == NEW_STANDARD_EDITION

    done = client.post(f"/alerts/{created[0]}/acknowledge", json={"acknowledged_by": "zara"})
    assert done.status_code == 200 and done.json()["status"] == ACKNOWLEDGED
    assert client.post(f"/alerts/{created[0]}/acknowledge", json={"acknowledged_by": "zara"}).status_code == 409
    assert client.get("/alerts/ALERT-missing").status_code == 404
    assert client.post(f"/alerts/{created[1]}/acknowledge", json={"acknowledged_by": ""}).status_code == 422


# the command, on a database it may commit to


def test_the_command_stores_alerts_and_drafts_once(scratch_database_url, tmp_path, monkeypatch, capsys):
    settings = conninfo_to_dict(scratch_database_url)
    for key, name in (("host", "HOST"), ("port", "PORT"), ("user", "USER"), ("password", "PASSWORD"), ("dbname", "DBNAME")):
        monkeypatch.setenv(f"AMRTRACE_PG_{name}", str(settings.get(key) or ""))
    with psycopg.connect(scratch_database_url) as setup:
        store(setup, ED32, ED33)
        publish(setup, "R_SRC_1", ED32)
    write_catalogue(catalogue(m100=(32, 33, 34)), tmp_path / "catalogue.yaml")
    write_releases(NO_RELEASES, tmp_path / "releases.yaml")
    arguments = ["--catalogue", str(tmp_path / "catalogue.yaml"), "--releases", str(tmp_path / "releases.yaml")]

    assert main([*arguments, "--dry-run"]) == 0
    assert "nothing stored (dry run)" in capsys.readouterr().out
    assert main(arguments) == 0
    assert "2 new alert(s), 0 already raised; 1 new draft(s), 0 already drafted" in capsys.readouterr().out
    assert main(arguments) == 0
    assert "0 new alert(s), 2 already raised; 0 new draft(s), 1 already drafted" in capsys.readouterr().out


# the software watcher's draft, applied: tool versions are recorded per release, so every case is re-verified (D-05)


def test_applying_a_software_draft_selects_every_case_evaluated_under_the_old_version(conn, tmp_path):
    load_frozen_v1(conn, MINI_COHORT, MINI_COHORT / "sha256.txt")
    vector, states = read_frozen_baseline(str(MINI_COHORT / CASE_STATES_FILE))
    load_baseline_release(conn, "R1", vector, states, expected_count=len(states), publish=False)
    materialize_baseline(conn, read_frozen_tables(MINI_COHORT), "R1", _panel(conn), _organism(conn))

    def move(rows):
        return [dict(r, amrfinderplus_version="4.3.0") if i == 0 else r for i, r in enumerate(rows)]

    new = open_snapshot(make_snapshot(tmp_path, "AMRTRACE_TEST_V2", {"curated_v1/isolates_curated.parquet": move}))
    run_check(conn, default_watchers(), open_snapshot(MINI_COHORT), new)
    [draft] = [d for d in list_drafts(conn) if d.watcher == "amrfinderplus"]

    application = apply_draft(conn, draft.draft_id, decided_by="aabia")

    assert len(get_impact_set(conn, application.change_id).items) == len(states)


# a person stored the newer edition after checking it: same breakpoints, so the alert stops and nothing is drafted
def test_a_newer_table_with_the_same_breakpoints_ends_the_alert_and_drafts_nothing(conn):
    store(conn, ED33_VET)
    publish(conn, "R_SRC_1", ED33_VET)
    assert kinds(check_standards(conn, catalogue(m100=(33, 34, 35, 36)))) == [(NEW_STANDARD_EDITION, "CLSI M100 Ed36")]

    store_table(conn, load_table(str(TABLES / "clsi_m100_ed36_vet01s_ed7.yaml")))
    found = check_standards(conn, catalogue(m100=(33, 34, 35, 36)))

    assert found.alerts == () and found.table_drafts == ()
    assert found.unchanged_tables == ((ED33_VET, "CLSI_M100_ED36_VET01S_ED7"),)
