# Review Copilot narrative (I-29): readable names, the grounding check, and a model's story kept only when grounded

import json

from amrtrace.copilot import CopilotSummary, Line, Narrative, Sentence, SourceRef, compose, display_name, grounded
from amrtrace.copilot.narrative import assigns_state, short_id

STATE = SourceRef("case_state", "90757")
CHANGE = SourceRef("change_event", "CHG_A28_GROUP_D")
RELEASE = SourceRef("release", "R8")

TRACE = (
    Sentence("Release R8 changed this case from concordant susceptible (release R3) to unresolved.", (STATE,),
             group="outcome"),
    Sentence("The new state was produced by change CHG_A28_GROUP_D, an interpretation version change from "
             "CLSI_M100_ED33_VET01S_ED7 to CLSI_M100_ED36_VET01S_ED7_R1, registered by aabia.", (CHANGE,),
             group="cause"),
    Sentence("The interpretation version moved from CLSI_M100_ED32_VET01S_ED7 to CLSI_M100_ED36_VET01S_ED7_R1.",
             (RELEASE,), group="versions"),
)
SUMMARY = CopilotSummary("CASE_1", 84324, 90757, "STATE_CHANGED", TRACE)
DRAFT = Narrative(
    headline=Line("Release R8 moved this case from concordant susceptible to unresolved.", (1,)),
    story=(Line("Change CHG_A28_GROUP_D, registered by aabia, moved CLSI M100 ed. 33 to ed. 36.", (2,)),),
    checks=(Line("The change says it replaced ed. 33, but release R3 read this case with ed. 32.", (2, 3)),),
    followups=("Which other cases did CHG_A28_GROUP_D change?",),
)
TEXTS = [s.text for s in TRACE]


class Model:
    """A fake model with a chat method, answering with the JSON it was given."""

    def __init__(self, answer, name="hosted:fake"):
        self.answer, self.name, self.asked = answer, name, []

    def chat(self, messages):
        self.asked.append(messages)
        return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)


class RewordOnly:
    name = "old"

    def rewrite(self, sentences):
        return sentences


def test_version_codes_read_as_editions_and_other_ids_stay_as_stored():
    assert display_name("CLSI_M100_ED36_VET01S_ED7_R1") == "CLSI M100 ed. 36, VET01S ed. 7, R1"
    assert display_name("CLSI_M100_ED32") == "CLSI M100 ed. 32"
    assert display_name("CHG_A28_GROUP_D") == "CHG_A28_GROUP_D"
    assert display_name(["CHG-NCBI-V2-AST-2", "CHG-NCBI-V2-GENOTYPE"]) == "CHG-NCBI-V2-AST-2, CHG-NCBI-V2-GENOTYPE"
    assert display_name(None) == "none"
    assert short_id("ASTV1_bff2fb1a4d1fd543776985828735b187cbf17654662fc7fa12bf076cbd0bc179") == "ASTV1_bff2…0bc179"


def test_a_line_may_summarise_but_never_name_what_its_records_do_not_hold():
    # summarising in plain words, with readable edition names, is allowed
    assert grounded(Line("Change CHG_A28_GROUP_D swapped the rules to CLSI M100 ed. 36, and R8 left the case "
                         "unresolved.", (1, 2)), TEXTS)
    # a number or identifier that is not in the cited sentences is not
    assert not grounded(Line("Change CHG_A28_GROUP_D moved 214 other cases.", (2,)), TEXTS)
    assert not grounded(Line("Release R9 changed it.", (1,)), TEXTS)
    # a citation must point at a sentence that exists, and a line must cite something
    assert not grounded(Line("Release R8 changed it.", (7,)), TEXTS)
    assert not grounded(Line("Release R8 changed it.", ()), TEXTS)


def test_a_line_that_decides_or_recommends_a_state_is_refused():
    for text in ("This case should be concordant susceptible again.", "We recommend confirming it.",
                 "Reclassify it as resistant.", "It is actually resistant.", "Treat with gentamicin."):
        assert assigns_state(text), text
        assert not grounded(Line(text, (1,)), TEXTS)
    assert not assigns_state("Nobody has reviewed the new state yet.")


def test_a_grounded_model_story_is_used_with_the_codes_checks_and_followups():
    model = Model({
        "headline": {"text": "R8 left this case unresolved after CHG_A28_GROUP_D swapped its breakpoints.",
                     "facts": [1, 2]},
        "story": [
            {"text": "The change, registered by aabia, moved the interpretation to CLSI M100 ed. 36.", "facts": [2]},
            {"text": "It also says 214 other cases moved.", "facts": [2]},
        ],
    })
    narrative = compose(SUMMARY, DRAFT, [model])
    assert narrative.generator == "hosted:fake"
    assert narrative.headline.cites == (1, 2)
    assert [line.text for line in narrative.story] == [
        "The change, registered by aabia, moved the interpretation to CLSI M100 ed. 36."]
    assert narrative.checks == DRAFT.checks and narrative.followups == DRAFT.followups
    assert "1 lines were dropped" in narrative.notes[-1]
    # the model saw the numbered trace and the draft, nothing else
    sent = json.loads(model.asked[0][1]["content"])
    assert [f["n"] for f in sent["facts"]] == [1, 2, 3] and sent["draft"]["headline"]["text"] == DRAFT.headline.text


def test_an_ungrounded_headline_or_a_failing_model_leaves_the_code_narrative():
    bad_headline = Model({"headline": {"text": "This case should be resistant.", "facts": [1]},
                          "story": [{"text": "Release R8 changed it.", "facts": [1]}]})
    nothing_kept = Model({"headline": {"text": "Release R8 changed it.", "facts": [1]},
                          "story": [{"text": "Release R9 changed it.", "facts": [1]}]})
    for model in (bad_headline, nothing_kept, Model("not json"), RewordOnly()):
        narrative = compose(SUMMARY, DRAFT, [model])
        assert narrative.generator == "templates"
        assert narrative.headline == DRAFT.headline and narrative.story == DRAFT.story
        assert narrative.notes
    # the first model that writes a grounded story wins
    good = Model({"headline": {"text": "Release R8 changed it.", "facts": [1]},
                  "story": [{"text": "Change CHG_A28_GROUP_D did it.", "facts": [2]}]}, name="local:fake")
    assert compose(SUMMARY, DRAFT, [nothing_kept, good]).generator == "local:fake"


def test_the_narrative_travels_with_the_summary_body():
    body = Narrative(DRAFT.headline, DRAFT.story).as_dict()
    assert body["headline"] == {"text": DRAFT.headline.text, "cites": [1]}
    assert body["generator"] == "templates" and body["version"] == "COPILOT_NARRATIVE_V1"
    assert [s["group"] for s in SUMMARY.as_dict()["sentences"]] == ["outcome", "cause", "versions"]


# ---------- the cache fingerprint (I-30) ----------

def test_the_fingerprint_changes_only_when_an_input_changes():
    from amrtrace.copilot import fingerprint, summary_inputs

    base = fingerprint("summary", summary_inputs(SUMMARY, ["hosted:a"]))
    assert base == fingerprint("summary", dict(reversed(list(summary_inputs(SUMMARY, ["hosted:a"]).items()))))
    assert len(base) == 64 and int(base, 16) >= 0
    newer = CopilotSummary("CASE_1", 84324, 90758, "STATE_CHANGED", TRACE)
    assert fingerprint("summary", summary_inputs(newer, ["hosted:a"])) != base
    assert fingerprint("summary", summary_inputs(SUMMARY, ["hosted:b"])) != base
    assert fingerprint("summary", summary_inputs(SUMMARY, ["hosted:a"], before_release="R1")) != base
    assert fingerprint("answer", summary_inputs(SUMMARY, ["hosted:a"])) != base
