# region narrowing tests: pure logic, no database
import pytest

from amrtrace.deps.selector import in_changed_region

REGION = {"field": "mic", "intervals": [[4, 4], [8, 8]]}


def context(value, sign="=="):
    return {"mic": value, "sign": sign}


@pytest.mark.parametrize("value", [4, 4.0, 8])
def test_an_exact_value_inside_a_changed_interval_is_kept(value):
    assert in_changed_region(context(value), REGION) is True


@pytest.mark.parametrize("value", [0.5, 2, 6, 16])
def test_an_exact_value_outside_every_interval_is_dropped(value):
    assert in_changed_region(context(value), REGION) is False


@pytest.mark.parametrize(
    "value, sign, kept",
    [
        # at most 4 can be 4
        (4, "<=", True),
        # at most 16 can be 4 or 8
        (16, "<=", True),
        # at most 2 can be neither
        (2, "<=", False),
        # below 4 cannot be 4, and 8 is far above
        (4, "<", False),
        # below 5 can be 4
        (5, "<", True),
        # at least 8 can be 8
        (8, ">=", True),
        # at least 16 can be neither
        (16, ">=", False),
        # above 8 cannot be 8
        (8, ">", False),
        # above 2 can be 4
        (2, ">", True),
    ],
)
def test_a_censored_value_is_kept_only_when_its_range_reaches_an_interval(
    value, sign, kept
):
    assert in_changed_region(context(value, sign), REGION) is kept


def test_a_range_interval_is_handled_like_a_point_interval():
    region = {"field": "mic", "intervals": [[4, 8]]}
    assert in_changed_region(context(6), region) is True
    assert in_changed_region(context(16), region) is False
    assert in_changed_region(context(8, ">"), region) is False
    assert in_changed_region(context(8, ">="), region) is True


@pytest.mark.parametrize(
    "region", [None, {}, {"field": "mic"}, {"field": "mic", "intervals": []}]
)
def test_without_a_usable_region_every_edge_counts(region):
    assert in_changed_region(context(0.5), region) is True


@pytest.mark.parametrize(
    "node_context", [None, {}, {"sign": "=="}, {"mic": None}, {"mic": "not a number"}]
)
def test_an_edge_that_cannot_be_placed_is_kept(node_context):
    assert in_changed_region(node_context, REGION) is True


def test_a_missing_sign_is_read_as_exact():
    assert in_changed_region({"mic": 4}, REGION) is True
    assert in_changed_region({"mic": 6}, REGION) is False


def test_the_field_and_sign_names_come_from_the_region():
    region = {"field": "zone", "sign_field": "comparator", "intervals": [[10, 12]]}
    assert in_changed_region({"zone": 11, "comparator": "=="}, region) is True
    assert in_changed_region({"zone": 9, "comparator": "<="}, region) is False
