# task A-14: the review queue and a release's states in triage order, through the ledger and over HTTP

import pytest
from fastapi.testclient import TestClient

from amrtrace.api.db import get_connection
from amrtrace.api.main import app
from amrtrace.ledger import (
    add_review,
    append_case_state,
    create_release,
    get_review_status,
    publish_release,
    validate_release,
)
from amrtrace.triage import (
    LABEL_CHANGED,
    NEWLY_DISCORDANT,
    RE_VERIFIED,
    STATE_CHANGED,
    rank_release,
    rank_review_queue,
)

pytestmark = pytest.mark.integration

GENE_POSITIVE_S = "DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S"
PHENO_R_NO_GENE = "DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE"

# case -> (antibiotic, state in R1, state in R2, labels changed in R2)
WORLD = {
    "CASE_T_NEW_DISC": ("gentamicin", "CONCORDANT_SUSCEPTIBLE", GENE_POSITIVE_S, 1),
    "CASE_T_CHANGED": ("gentamicin", "UNRESOLVED", "CONCORDANT_SUSCEPTIBLE", 1),
    "CASE_T_DISC_STAYS": ("gentamicin", PHENO_R_NO_GENE, GENE_POSITIVE_S, 1),
    "CASE_T_LABEL": ("gentamicin", "UNRESOLVED", "UNRESOLVED", 2),
    "CASE_T_LABEL_B": ("meropenem", "CONCORDANT_RESISTANT", "CONCORDANT_RESISTANT", 1),
    "CASE_T_SAME": ("gentamicin", "CONCORDANT_SUSCEPTIBLE", "CONCORDANT_SUSCEPTIBLE", 0),
}

# the review order the rule gives: tier first, then case id
QUEUE_ORDER = ["CASE_T_NEW_DISC", "CASE_T_CHANGED", "CASE_T_DISC_STAYS", "CASE_T_LABEL", "CASE_T_LABEL_B"]


@pytest.fixture
def world(conn):
    for case_id, (drug, _, _, _) in WORLD.items():
        conn.execute("INSERT INTO isolate (target_acc) VALUES (%s)", ("PDT_" + case_id,))
        conn.execute(
            'INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
            (case_id, "PDT_" + case_id, drug, "PANEL_TEST"),
        )
    create_release(conn, "R1", {"interpretation_version": "TABLE_R1"})
    for case_id, (_, before, _, _) in WORLD.items():
        append_case_state(
            conn, case_id=case_id, release_id="R1", state_code=before, explanation={}, verification_status="EVALUATED"
        )
    publish_release(conn, "R1", baseline=True)

    create_release(conn, "R2", {"interpretation_version": "TABLE_R2"})
    for case_id, (_, before, after, labels) in WORLD.items():
        append_case_state(
            conn,
            case_id=case_id,
            release_id="R2",
            state_code=after,
            explanation={"labels_changed": labels},
            verification_status="STATE_CHANGED" if after != before else "RE_VERIFIED_UNCHANGED",
        )
    validate_release(conn, "R2")
    publish_release(conn, "R2")
    return conn


def queue_ids(conn, **options):
    return [item.case_id for item, _ in rank_review_queue(conn, **options).items]


# the queue


def test_the_queue_comes_in_triage_order(world):
    assert queue_ids(world) == QUEUE_ORDER


def test_each_queue_item_carries_its_tier_and_reason(world):
    tiers = {item.case_id: t.tier for item, t in rank_review_queue(world).items}

    assert tiers == {
        "CASE_T_NEW_DISC": NEWLY_DISCORDANT,
        "CASE_T_CHANGED": STATE_CHANGED,
        "CASE_T_DISC_STAYS": STATE_CHANGED,
        "CASE_T_LABEL": LABEL_CHANGED,
        "CASE_T_LABEL_B": LABEL_CHANGED,
    }


def test_the_same_inputs_always_give_the_same_order(world):
    assert queue_ids(world) == queue_ids(world) == queue_ids(world)


def test_pages_follow_the_triage_order_of_the_whole_queue(world):
    page = rank_review_queue(world, limit=2, offset=2)

    assert page.total == 5
    assert [item.case_id for item, _ in page.items] == QUEUE_ORDER[2:4]


def test_the_queue_filters_still_apply(world):
    assert queue_ids(world, drug="meropenem") == ["CASE_T_LABEL_B"]
    assert queue_ids(world, state=GENE_POSITIVE_S) == ["CASE_T_NEW_DISC", "CASE_T_DISC_STAYS"]


def test_a_reviewed_case_leaves_the_ranked_queue(world):
    state_id = get_review_status(world, "CASE_T_NEW_DISC").state_id
    add_review(world, case_id="CASE_T_NEW_DISC", reviewer="aabia", action="CONFIRM", reason="checked", state_id=state_id)

    assert queue_ids(world) == QUEUE_ORDER[1:]


@pytest.mark.parametrize("limit, offset", [(0, 0), (1, -1)])
def test_a_bad_page_is_refused(world, limit, offset):
    with pytest.raises(ValueError):
        rank_review_queue(world, limit=limit, offset=offset)


# a release


def test_a_release_is_ranked_with_its_tier_counts(world):
    page = rank_release(world, "R2")

    assert [s.case_id for s in page.items] == QUEUE_ORDER + ["CASE_T_SAME"]
    assert page.tier_counts == {NEWLY_DISCORDANT: 1, STATE_CHANGED: 2, LABEL_CHANGED: 2, RE_VERIFIED: 1}
    assert page.items[0].previous_state_code == "CONCORDANT_SUSCEPTIBLE"


def test_the_first_release_has_no_previous_state(world):
    page = rank_release(world, "R1")

    discordant = [s for s in page.items if s.triage.tier == NEWLY_DISCORDANT]
    assert [s.case_id for s in discordant] == ["CASE_T_DISC_STAYS"]
    assert discordant[0].triage.reason.endswith("on its first evaluation")


def test_an_unknown_release_is_refused(world):
    with pytest.raises(LookupError, match="does not exist"):
        rank_release(world, "R_MISSING")


# over HTTP


@pytest.fixture
def client(world):
    def same_connection():
        yield world

    app.dependency_overrides[get_connection] = same_connection
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_connection, None)


def test_the_api_sorts_the_queue_by_triage_on_request(client):
    body = client.get("/review-queue", params={"sort": "triage"}).json()

    assert [i["case_id"] for i in body["items"]] == QUEUE_ORDER
    assert body["items"][0]["triage_tier"] == NEWLY_DISCORDANT
    assert body["items"][0]["triage_rank"] == 1


# the default order is unchanged for the existing page, but every item still shows its tier
def test_the_default_queue_order_is_still_by_case_id_with_tiers_shown(client):
    body = client.get("/review-queue").json()

    assert [i["case_id"] for i in body["items"]] == sorted(QUEUE_ORDER)
    assert all(i["triage_tier"] and i["triage_reason"] for i in body["items"])


def test_the_api_refuses_an_unknown_sort(client):
    assert client.get("/review-queue", params={"sort": "random"}).status_code == 422


def test_the_api_ranks_a_release(client):
    body = client.get("/releases/R2/triage", params={"limit": 2}).json()

    assert body["total"] == 6
    assert body["tier_counts"][STATE_CHANGED] == 2
    assert [i["case_id"] for i in body["items"]] == QUEUE_ORDER[:2]
    assert client.get("/releases/R_MISSING/triage").status_code == 404
