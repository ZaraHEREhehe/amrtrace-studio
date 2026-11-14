# A-24: the workflow cost script reads a real gated run on the mini-cohort and changes nothing in the ledger

import importlib.util
from pathlib import Path

import pytest

from tests.integration import test_api_reevaluation as api_world

pytestmark = pytest.mark.integration

scratch_conn = api_world.scratch_conn
run_world = api_world.run_world
client = api_world.client

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "workflow_cost.py"
spec = importlib.util.spec_from_file_location("workflow_cost", SCRIPT)
workflow_cost = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow_cost)


def ledger_counts(conn):
    return tuple(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                 for table in ("release", "case_state", "reeval_run", "equivalence_report", "impact_set"))


@pytest.fixture
def gated_change(client, run_world):
    conn, event = run_world
    response = client.post(
        f"/changes/{event.change_id}/reevaluate",
        json={"release_id": "R_COST", "run_exhaustive": True, "gate": True},
    )
    assert response.status_code == 201, response.text
    return conn, event


def test_every_stage_is_measured_for_a_gated_change(gated_change):
    conn, event = gated_change
    cost = workflow_cost.measure_change(conn, event.change_id, repeats=2)
    assert [s.name for s in cost.stages] == [
        "selection", "selective re-evaluation", "exhaustive re-evaluation and comparison", "publication",
    ]
    assert all(s.seconds is not None and s.seconds >= 0 for s in cost.stages)
    assert cost.release_id == "R_COST"
    assert cost.selected is not None and cost.total_cases is not None and cost.selected <= cost.total_cases
    total, complete = cost.total()
    assert complete and total == pytest.approx(sum(s.seconds for s in cost.stages))


def test_measuring_leaves_the_ledger_unchanged(gated_change):
    conn, event = gated_change
    before = ledger_counts(conn)
    workflow_cost.measure_change(conn, event.change_id, repeats=1)
    assert ledger_counts(conn) == before


def test_a_change_without_runs_reports_them_as_not_recorded(run_world):
    conn, event = run_world
    cost = workflow_cost.measure_change(conn, event.change_id, repeats=1)
    missing = [s.name for s in cost.stages if s.seconds is None]
    assert missing == ["selective re-evaluation", "exhaustive re-evaluation and comparison", "publication"]
    assert cost.total()[1] is False
    assert "lower bound" in workflow_cost.render([cost], ["- env"], 1)


def test_an_unknown_change_is_refused(run_world):
    conn, _ = run_world
    with pytest.raises(LookupError, match="CHG-NOT-STORED"):
        workflow_cost.measure_change(conn, "CHG-NOT-STORED")
