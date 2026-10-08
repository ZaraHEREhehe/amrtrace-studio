# building only chosen cases, as selective re-evaluation needs, from the committed mini-cohort
from pathlib import Path

import pytest

from amrtrace.ingest.frozen_v1 import build_case_inputs, read_frozen_tables

COHORT = Path(__file__).resolve().parents[2] / "fixtures" / "mini_cohort"
PANEL = ("gentamicin",)
ORGANISM = "Escherichia coli"


@pytest.fixture(scope="module")
def tables():
    return read_frozen_tables(COHORT)


@pytest.fixture(scope="module")
def every_case(tables):
    return list(build_case_inputs(tables, PANEL, ORGANISM))


def test_without_a_filter_every_case_is_built(every_case):
    assert len(every_case) == 660


def test_only_the_chosen_cases_are_built_and_they_are_identical(tables, every_case):
    chosen = [every_case[0].case_id, every_case[100].case_id, every_case[-1].case_id]
    built = list(build_case_inputs(tables, PANEL, ORGANISM, case_ids=chosen))
    by_id = {inputs.case_id: inputs for inputs in every_case}
    assert sorted(inputs.case_id for inputs in built) == sorted(chosen)
    assert all(inputs == by_id[inputs.case_id] for inputs in built)


def test_the_filter_keeps_the_usual_order(tables, every_case):
    chosen = {inputs.case_id for inputs in every_case[::50]}
    built = [
        i.case_id for i in build_case_inputs(tables, PANEL, ORGANISM, case_ids=chosen)
    ]
    assert built == [i.case_id for i in every_case if i.case_id in chosen]


def test_an_empty_filter_builds_nothing(tables):
    assert list(build_case_inputs(tables, PANEL, ORGANISM, case_ids=[])) == []


def test_an_id_that_names_no_case_is_refused(tables, every_case):
    with pytest.raises(ValueError, match="not in the files"):
        list(
            build_case_inputs(
                tables, PANEL, ORGANISM, case_ids=[every_case[0].case_id, "CASE_NOPE"]
            )
        )


def test_the_filter_also_works_in_interpretation_mode(tables, every_case):
    chosen = [every_case[0].case_id]
    built = list(
        build_case_inputs(
            tables, PANEL, ORGANISM, interpretation_rules=(), case_ids=chosen
        )
    )
    assert [inputs.case_id for inputs in built] == chosen
    assert "rule_key" in built[0].ast_rows[0]
