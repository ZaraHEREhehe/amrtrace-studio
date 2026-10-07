"""Unit tests (no database): reading and checking interpretation tables, rule lookup, interval logic (task I-06).

Generic code is tested with INVENTED names (a made-up standard, organism and drug) to prove nothing is hardcoded.
The two real data files are tested at the end.
"""

import pathlib

import pytest

from amrtrace.interpretation import (
    InvalidTable,
    find_rules,
    label_at,
    load_table,
    make_rule_key,
    parse_table,
    rules_as_dicts,
    touched_categories,
)

DATA = pathlib.Path(__file__).resolve().parents[2] / "data" / "interpretation"


def table(version="V1", standard="FANTASY_STD", organism="Imaginary bacillus", drug="mythicin", cats=None):
    cats = cats if cats is not None else [
        {"label": "susceptible", "op": "<=", "value": 10},
        {"label": "intermediate", "op": "==", "value": 20},
        {"label": "resistant", "op": ">=", "value": 40}]
    return {"interpretation_version": version, "standard": standard,
            "rules": [{"organism": organism, "antibiotic": drug, "method": "MIC", "categories": cats}]}


def test_a_valid_table_with_invented_names_parses():
    t = parse_table(table())
    assert t.interpretation_version == "V1" and len(t.rules) == 1
    rule = t.rules[0]
    assert rule.rule_key == "fantasy_std|imaginary bacillus|mythicin|mic"
    assert [c.label for c in rule.categories] == ["susceptible", "intermediate", "resistant"]
    assert rules_as_dicts([rule])[0]["categories"][1] == {"label": "intermediate", "op": "==", "value": 20}


def test_rule_key_ignores_case_and_spacing():
    assert make_rule_key(" CLSI ", "Escherichia   coli", "Gentamicin", "mic") == make_rule_key("clsi", "escherichia coli", "gentamicin", "MIC")


@pytest.mark.parametrize("mutate,expected", [
    (lambda d: d.update(interpretation_version=""), "interpretation_version"),
    (lambda d: d.update(standard=None), "standard"),
    (lambda d: d.update(rules=[]), "rules"),
    (lambda d: d["rules"][0].update(organism=" "), "organism"),
    (lambda d: d["rules"][0].update(categories=[]), "categories"),
    (lambda d: d["rules"][0]["categories"][0].update(label="fine"), "label"),
    (lambda d: d["rules"][0]["categories"][0].update(op="~"), "op"),
    (lambda d: d["rules"][0]["categories"][0].update(value="ten"), "value"),
    (lambda d: d["rules"][0]["categories"][0].update(value=True), "value"),
])
def test_bad_tables_are_rejected(mutate, expected):
    data = table()
    mutate(data)
    with pytest.raises(InvalidTable) as info:
        parse_table(data)
    assert any(expected in p for p in info.value.problems)


def test_overlapping_categories_are_rejected():
    overlap = [{"label": "susceptible", "op": "<=", "value": 10}, {"label": "resistant", "op": ">=", "value": 10}]
    with pytest.raises(InvalidTable, match="overlap"):
        parse_table(table(cats=overlap))


def test_a_gap_between_categories_is_allowed():
    parse_table(table())                       # 10 < x < 20 and 20 < x < 40 belong to no category


def test_duplicate_rules_and_non_mappings_are_rejected():
    data = table()
    data["rules"].append(dict(data["rules"][0]))
    with pytest.raises(InvalidTable, match="duplicate"):
        parse_table(data)
    for bad in (None, [], "text"):
        with pytest.raises(InvalidTable):
            parse_table(bad)


def test_all_problems_are_reported_together():
    with pytest.raises(InvalidTable) as info:
        parse_table({"interpretation_version": "", "standard": "", "rules": [{}]})
    assert len(info.value.problems) >= 4


def test_find_rules_matches_all_four_fields():
    rules = parse_table(table()).rules
    assert find_rules(rules, standard="fantasy_std", organism="IMAGINARY BACILLUS", antibiotic="Mythicin", method="mic") == list(rules)
    assert find_rules(rules, standard="OTHER", organism="Imaginary bacillus", antibiotic="mythicin") == []
    assert find_rules(rules, standard="FANTASY_STD", organism="Imaginary bacillus", antibiotic="other") == []
    assert find_rules(rules, standard=None, organism="Imaginary bacillus", antibiotic="mythicin") == []   # no standard, no match


@pytest.mark.parametrize("value,sign,expected", [
    (5, "<=", ["susceptible"]),                  # up to 5: only the susceptible range
    (10, "==", ["susceptible"]),
    (15, "==", []),                              # exact value in a gap
    (20, "==", ["intermediate"]),
    (20, "<=", ["susceptible", "intermediate"]),  # up to 20 touches both
    (40, ">=", ["resistant"]),
    (20, ">=", ["intermediate", "resistant"]),
    (40, ">", ["resistant"]),
    (10, "<", ["susceptible"]),
    (None, None, None),
])
def test_touched_categories(value, sign, expected):
    rule = parse_table(table()).rules[0]
    if value is None:
        assert label_at(rule, 10) == "susceptible" and label_at(rule, 15) is None and label_at(rule, 50) == "resistant"
        return
    assert touched_categories(rule, value, sign) == expected


# ---------------------------------------------------------------- the two real data files

@pytest.fixture(scope="module")
def ed32():
    return load_table(str(DATA / "clsi_m100_ed32.yaml"))


@pytest.fixture(scope="module")
def ed33():
    return load_table(str(DATA / "clsi_m100_ed33.yaml"))


def test_real_tables_load_with_one_rule_each(ed32, ed33):
    assert (ed32.interpretation_version, ed33.interpretation_version) == ("CLSI_M100_ED32", "CLSI_M100_ED33")
    assert len(ed32.rules) == len(ed33.rules) == 1 and ed32.rules[0].rule_key == ed33.rules[0].rule_key


@pytest.mark.parametrize("value,sign,old,new", [
    (4, "==", ["susceptible"], ["intermediate"]),        # the 50 cases that move S -> I
    (8, "==", ["intermediate"], ["resistant"]),          # the 104 cases that move I -> R
    (1, "<=", ["susceptible"], ["susceptible"]),         # clearly susceptible under both editions
    (4, "<=", ["susceptible"], ["susceptible", "intermediate"]),   # S under Ed32, unresolved under Ed33
    (8, ">=", ["intermediate", "resistant"], ["resistant"]),       # unresolved under Ed32, R under Ed33
    (16, "==", ["resistant"], ["resistant"]),
    (3, "==", ["susceptible"], []),                      # a value in the new gap
])
def test_the_censored_value_examples_from_the_adr(ed32, ed33, value, sign, old, new):
    assert touched_categories(ed32.rules[0], value, sign) == old
    assert touched_categories(ed33.rules[0], value, sign) == new
