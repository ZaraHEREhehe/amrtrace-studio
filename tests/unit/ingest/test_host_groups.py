# the host grouping file: how raw host values become the groups the VET01S host rules are written for (D-22)
import pathlib

import pytest

from amrtrace.ingest.host_groups import (
    InvalidHostGroups,
    UnknownHost,
    load_host_groups,
    normalise_host,
    parse_host_groups,
)
from amrtrace.interpretation import load_table

DATA = pathlib.Path(__file__).resolve().parents[3] / "data" / "interpretation"

# every raw host value in the copy database on 18 Oct 2026, with the group agreed for it
SEEN_HOSTS = {
    "Homo sapiens": "human", "": None, "Canis lupus familiaris": "dog", "Chicken [NCBITaxon:9031]": "poultry",
    "Sus scrofa domesticus": "swine", "veal calf": "cattle", "Bos taurus": "cattle", "pig": "swine",
    "dairy cow": "cattle", "broiler": "poultry", "Felis catus": "cat", "Gallus gallus domesticus": "poultry",
    "Swine": "swine", "Bucephala": "other animal", "Rat": "other animal", "sheep": "other animal",
    "Spheniscus magellanicus": "other animal", "goat": "other animal", "bird": "other animal",
    "Iguana": "other animal", "Not Provided": None, "Food": None, "Chicken": "poultry",
    "Free-range White-tailed deer": "other animal", "bovine": "cattle", "Bird": "other animal",
}


def test_matching_ignores_case_spacing_and_bracketed_tags():
    assert normalise_host("  Chicken   [NCBITaxon:9031] ") == "chicken"
    assert normalise_host(None) == ""


@pytest.mark.parametrize("raw,group", sorted(SEEN_HOSTS.items()))
def test_every_host_in_the_data_has_its_agreed_group(raw, group):
    found = load_host_groups().group_for(raw)
    assert (found.name if found else None) == group


def test_only_human_is_not_an_animal():
    groups = {g.name: g.animal for g in load_host_groups().by_host.values()}
    assert [name for name, animal in groups.items() if not animal] == ["human"]


def test_every_animal_group_has_host_rules_in_both_vet01s_tables():
    animal = {g.name for g in load_host_groups().by_host.values() if g.animal}
    for edition in ("ed32", "ed33"):
        table = load_table(str(DATA / f"clsi_m100_{edition}_vet01s_ed7.yaml"))
        assert {r.host for r in table.rules if r.host} == animal


def test_an_unknown_host_is_reported():
    with pytest.raises(UnknownHost):
        load_host_groups().group_for("Dragon")


@pytest.mark.parametrize("data", [
    None,
    {"host_groups_version": "V", "groups": {"a": {"animal": "yes", "hosts": ["x"]}}},
    {"host_groups_version": "", "groups": {"a": {"animal": True, "hosts": ["x"]}}},
    {"host_groups_version": "V", "groups": {"a": {"animal": True, "hosts": []}}},
    {"host_groups_version": "V", "groups": {"a": {"animal": True, "hosts": ["x"]}, "b": {"animal": True, "hosts": ["X "]}}},
    {"host_groups_version": "V", "not_recorded": ["x"], "groups": {"a": {"animal": True, "hosts": ["x"]}}},
])
def test_a_broken_grouping_file_is_rejected(data):
    with pytest.raises(InvalidHostGroups):
        parse_host_groups(data)
