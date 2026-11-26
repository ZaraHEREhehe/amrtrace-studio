"""The Review Copilot's short story (task I-29, D-27, rule 9): a headline and a few plain sentences on top of the trace.

The template sentences of I-19 stay the trace: every one names the stored records it came from. On top of them this
module writes a narrative for a reviewer:

    headline   one sentence: what happened to the case and why
    story      two to five sentences: what moved, what it means for the lab result, and where the review stands
    checks     things worth a look before reviewing, found by code (never by a model): a change that says it replaced
               a different version than the one the case was read with, rules and evidence moving in the same
               release, a lab result that a rule no longer reads as S, I or R
    followups  questions the chat can answer next

Every line cites the trace sentences it rests on, by number (1 is the first sentence). A narrative is always written
by code first (``draft_narrative``), so the copilot works with no model and no network. A configured model may then
compose its own headline and story from the numbered sentences (``compose``); each of its lines is kept only when it
cites sentences that exist, names no identifier or number those sentences do not hold, and says nothing that assigns
or recommends a state. If the headline fails, or no story line survives, the code's narrative is used. Checks and
follow-ups always come from code.

The narrative is generated text, like the sentences: never evidence and never an input to state assignment.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Sequence

from amrtrace.ledger import get_review_status
from amrtrace.reeval.diff import (
    OUTCOME_FIRST_STATE,
    OUTCOME_NO_STATE,
    OUTCOME_RE_VERIFIED,
    OUTCOME_STATE_CHANGED,
    CaseDiff,
    case_diff,
)

from .language_model import Rewriter, facts
from .templates import CopilotSummary, summary_from_diff, words

NARRATIVE_VERSION = "COPILOT_NARRATIVE_V1"
PROMPT_VERSION = "COPILOT_COMPOSE_V1"
MAX_LINE_LENGTH = 400
MAX_STORY_LINES = 5
EVIDENCE_VECTOR_NAME = "evidence_changes"
READABLE_LABELS = {"S", "I", "R", "SDD", "NS"}

# language that decides or recommends a state, or gives clinical advice; a model line that uses it is dropped
_ASSIGNS = re.compile(
    r"\b(should|ought to|recommend\w*|reclassif\w*|must be|is actually|is really|is truly|we suggest|"
    r"treat\w*|prescri\w*|dos(?:e|ing)|clinically)\b",
    re.IGNORECASE,
)

COMPOSE_INSTRUCTIONS = (
    "You are the Review Copilot in an antimicrobial-resistance research workbench. A reviewer wants to understand "
    "why one case changed. Using ONLY the numbered facts, write a one-sentence headline that says what happened to "
    "the case and why, then two to five short, plain sentences that explain the cause, what it means for the lab "
    "result, and where the review stands. Write it as a colleague would explain it, not as a list. After each "
    "sentence give the numbers of the facts it uses. Copy identifiers, versions and numbers exactly as the facts "
    "write them; you may write an edition code such as CLSI_M100_ED36 as 'CLSI M100 ed. 36'. Never say what the "
    "state should be, never recommend a decision, and never give clinical advice. A draft written by code is given; "
    "improve its wording, keep its facts. Answer with JSON only: "
    "{\"headline\": {\"text\": \"...\", \"facts\": [1]}, \"story\": [{\"text\": \"...\", \"facts\": [1, 2]}]}"
)


@dataclass(frozen=True)
class Line:
    text: str
    cites: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "cites": list(self.cites)}


@dataclass(frozen=True)
class Narrative:
    headline: Line
    story: tuple[Line, ...]
    checks: tuple[Line, ...] = ()
    followups: tuple[str, ...] = ()
    generator: str = "templates"
    version: str = NARRATIVE_VERSION
    notes: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline.as_dict(), "story": [line.as_dict() for line in self.story],
            "checks": [line.as_dict() for line in self.checks], "followups": list(self.followups),
            "generator": self.generator, "version": self.version, "notes": list(self.notes),
        }


# ---------- readable names ----------

_CODE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
_EDITION = re.compile(r"^ED(\d+)$")


def display_name(code: Any) -> str:
    """A stored version code as a reader says it: CLSI_M100_ED36_VET01S_ED7_R1 -> CLSI M100 ed. 36, VET01S ed. 7, R1.

    Anything that is not such a code (no edition part) comes back unchanged, so identifiers stay searchable.
    """
    if code is None:
        return "none"
    if isinstance(code, (list, tuple)):
        return ", ".join(display_name(c) for c in code) if code else "none"
    text = str(code)
    if not _CODE.match(text) or not any(_EDITION.match(part) for part in text.split("_")):
        return text
    groups: list[str] = []
    for part in text.split("_"):
        edition = _EDITION.match(part)
        if edition and groups:
            groups[-1] += f" ed. {edition.group(1)}"
        elif groups and not any(ch.isdigit() for ch in groups[-1]) and not edition:
            groups[-1] += f" {part}"          # CLSI then M100 belong together
        else:
            groups.append(part)
    return ", ".join(groups)


def short_id(identifier: str, keep: int = 10) -> str:
    """A long record id cut for reading (the trace keeps the full one)."""
    text = str(identifier)
    return text if len(text) <= 2 * keep + 4 else f"{text[:keep]}…{text[-6:]}"


# ---------- the narrative written by code ----------

def _indexes(summary: CopilotSummary, group: str) -> tuple[int, ...]:
    return tuple(i for i, s in enumerate(summary.sentences, start=1) if s.group == group)


def _first(summary: CopilotSummary, *groups: str) -> tuple[int, ...]:
    for group in groups:
        found = _indexes(summary, group)
        if found:
            return found[:1]
    return (1,) if summary.sentences else ()


def _change_row(conn, change_id: Optional[str]) -> Optional[dict[str, Any]]:
    if not change_id:
        return None
    row = conn.execute(
        "SELECT type, old_version, new_version, initiator FROM change_event WHERE change_id = %s", (change_id,)
    ).fetchone()
    return None if row is None else {"id": change_id, "type": row[0], "old": row[1], "new": row[2], "initiator": row[3]}


def _label_flags(diff: CaseDiff) -> list[dict[str, Any]]:
    if not diff.after:
        return []
    return [f for f in ((diff.after.explanation or {}).get("label_flags") or []) if f.get("label_changed")]


def _headline(diff: CaseDiff, change: Optional[dict], summary: CopilotSummary) -> Line:
    before, after = diff.before, diff.after
    outcome = _first(summary, "outcome")
    cause = _first(summary, "cause") if change else ()
    because = f" because of change {change['id']}, {_article(words(change['type']))} change" if change else ""
    if diff.outcome == OUTCOME_NO_STATE:
        return Line("This case has no published state yet, so there is nothing to explain.", outcome)
    if diff.outcome == OUTCOME_FIRST_STATE:
        return Line(f"This case has one published state so far: {words(after.state_code)} in release "
                    f"{after.release_id}.", outcome)
    if diff.outcome == OUTCOME_STATE_CHANGED:
        return Line(f"Release {after.release_id} moved this case from {words(before.state_code)} to "
                    f"{words(after.state_code)}{because}.", outcome + cause)
    if diff.outcome == OUTCOME_RE_VERIFIED:
        return Line(f"Release {after.release_id} checked this case again{because} and it stayed "
                    f"{words(after.state_code)}.", outcome + cause)
    return Line(f"Nothing has changed this case since release {after.release_id}; it is still "
                f"{words(after.state_code)}.", outcome)


def _field_name(field_name: str) -> str:
    """phenotype_state -> phenotype; uncertainty_reason -> uncertainty reason."""
    return words(field_name).removesuffix(" state")


def _value(field_name: str, value: Any) -> str:
    """A state value without the field's own word: PHENOTYPE_R -> R, PHENOTYPE_UNRESOLVED_NONBINARY -> unresolved."""
    text = words(value)
    prefix = _field_name(field_name) + " "
    if text.startswith(prefix):
        text = text[len(prefix):]
    return text.upper() if len(text) <= 3 and text != "none" else text


def _article(phrase: str) -> str:
    return ("an " if phrase[:1] in "aeiou" else "a ") + phrase


def _story(conn, diff: CaseDiff, change: Optional[dict], summary: CopilotSummary) -> list[Line]:
    lines: list[Line] = []
    moved = bool(diff.before and diff.after and diff.before.state_id != diff.after.state_id)
    if change and moved:
        cite = _first(summary, "cause")
        if change["old"] or change["new"]:
            lines.append(Line(f"Change {change['id']}, registered by {change['initiator']}, moved the "
                              f"{words(change['type'])} from {display_name(change['old'])} to "
                              f"{display_name(change['new'])}.", cite))
        else:
            lines.append(Line(f"Change {change['id']} was registered by {change['initiator']}.", cite))
    fields = [c for c in diff.state_changes if c.field != "state_code"]
    if fields:
        parts = [f"its {_field_name(c.field)} went from {_value(c.field, c.before)} to {_value(c.field, c.after)}"
                 for c in fields]
        joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        cites = _indexes(summary, "outcome")[1:] or _first(summary, "outcome")
        lines.append(Line(f"{joined[0].upper()}{joined[1:]}.", cites))
    flags = _label_flags(diff)
    labels = _indexes(summary, "labels")
    for flag in flags[:2]:
        derived = flag.get("derived_label")
        lines.append(Line(
            f"The lab still reports {flag.get('submitted_label') or 'no label'} for AST result "
            f"{short_id(flag['ast_evidence_id'])}, but rule {flag.get('rule_key')} now reads that measurement "
            f"as {derived}.",
            labels[:1] or _first(summary, "evidence"),
        ))
    if len(flags) > 2:
        lines.append(Line(f"{len(flags) - 2} more lab results are read differently too.", labels or (1,)))
    if moved and not flags:
        removed, added = len(diff.dependencies_removed), len(diff.dependencies_added)
        cites = (_indexes(summary, "rules") + _indexes(summary, "evidence"))[:3] or _first(summary, "versions")
        if removed or added:
            lines.append(Line(f"Between release {diff.before.release_id} and {diff.after.release_id} it dropped "
                              f"{removed} and gained {added} links to rules or evidence.", cites))
    review = _review_line(conn, diff, summary)
    if review:
        lines.append(review)
    return lines[:MAX_STORY_LINES]


def _review_line(conn, diff: CaseDiff, summary: CopilotSummary) -> Optional[Line]:
    cite = _indexes(summary, "review")
    if not cite or not diff.after:
        return None
    status = get_review_status(conn, diff.case_id)
    if status.review_status == "UNVERIFIED":
        return Line("Nobody has reviewed the new state yet, so it is waiting in the review queue.", cite)
    if status.latest_review_id is not None:
        return Line(f"A reviewer has already looked at this state ({words(status.latest_review_action)}).", cite)
    return Line("This state needs no review.", cite)


def _checks(diff: CaseDiff, change: Optional[dict], summary: CopilotSummary) -> list[Line]:
    checks: list[Line] = []
    versions = _indexes(summary, "versions")
    if change and change["old"] and change["new"] and diff.before:
        for v in diff.version_changes:
            if v.after == change["new"] and v.before not in (None, change["old"]):
                checks.append(Line(
                    f"The change says it replaced {display_name(change['old'])}, but release {diff.before.release_id} "
                    f"read this case with {display_name(v.before)}, so the case may have skipped a version.",
                    _first(summary, "cause") + versions[:1]))
    names = {v.name for v in diff.version_changes}
    if EVIDENCE_VECTOR_NAME in names and names - {EVIDENCE_VECTOR_NAME, "evaluator_version", "refgene_db_version"}:
        evidence = next(v for v in diff.version_changes if v.name == EVIDENCE_VECTOR_NAME)
        checks.append(Line(
            f"New evidence ({display_name(evidence.after)}) also took effect in release {diff.after.release_id}, so "
            "both the rules and the evidence moved between these releases.",
            versions or _first(summary, "versions")))
    for flag in _label_flags(diff)[:2]:
        derived = str(flag.get("derived_label") or "")
        if derived and derived.upper() not in READABLE_LABELS:
            checks.append(Line(
                f"Rule {flag.get('rule_key')} reads the lab's result as {derived} rather than S, I or R, so this "
                "result can no longer be compared with the genotype.",
                _indexes(summary, "labels")[:1] or _first(summary, "evidence")))
    if any(" more " in s.text for s in summary.sentences):
        cite = tuple(i for i, s in enumerate(summary.sentences, start=1) if " more " in s.text)
        checks.append(Line("The trace names only the first few records of each kind; the dependency view lists "
                           "all of them.", cite[:1]))
    return checks


def _followups(diff: CaseDiff, change: Optional[dict]) -> tuple[str, ...]:
    asks = []
    if change:
        asks.append(f"Which other cases did {change['id']} change?")
    if diff.after:
        asks.append("What does this case depend on now?")
    if _label_flags(diff):
        asks.append("Why is the lab result read differently now?")
    else:
        asks.append("What evidence does this case read?")
    return tuple(asks[:3])


def draft_narrative(conn, diff: CaseDiff, summary: CopilotSummary) -> Narrative:
    """The narrative written by code from the stored records; works with no model and no network."""
    change = _change_row(conn, diff.triggered_by_change_id)
    return Narrative(
        headline=_headline(diff, change, summary),
        story=tuple(_story(conn, diff, change, summary)),
        checks=tuple(_checks(diff, change, summary)),
        followups=_followups(diff, change),
    )


# ---------- a model's narrative, kept only when it is grounded ----------

def _allowed(texts: Sequence[str]) -> set[str]:
    """Every identifier and number the cited sentences hold, with the parts of each code and its readable name."""
    allowed: set[str] = set()
    for text in texts:
        for token in facts(text) | facts(display_name_in(text)):
            allowed.add(token)
            allowed.update(part for part in re.split(r"[_|.:<>=+\-,]", token) if part)
            allowed.update(re.findall(r"\d+(?:\.\d+)?", token))
    return allowed


def display_name_in(text: str) -> str:
    """Every version code in a sentence replaced by its readable name."""
    return re.sub(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", lambda m: display_name(m.group(0)), text)


def assigns_state(text: str) -> bool:
    return bool(_ASSIGNS.search(text))


def grounded(line: Line, sentences: Sequence[str]) -> bool:
    """True when the line cites sentences that exist, names nothing they do not hold and assigns no state."""
    text = line.text.strip()
    if not text or len(text) > MAX_LINE_LENGTH or not line.cites or assigns_state(text):
        return False
    if any(not 1 <= n <= len(sentences) for n in line.cites):
        return False
    return facts(text) <= _allowed([sentences[n - 1] for n in line.cites])


def _line(item: Any) -> Optional[Line]:
    if not isinstance(item, dict):
        return None
    try:
        cites = tuple(int(n) for n in (item.get("facts") or item.get("cites") or []))
    except (TypeError, ValueError):
        return None
    return Line(str(item.get("text", "")).strip(), cites)


def compose(summary: CopilotSummary, draft: Narrative, rewriters: Sequence[Rewriter]) -> Narrative:
    """A model's headline and story when they are grounded; otherwise the code's narrative, with a note saying why."""
    sentences = [s.text for s in summary.sentences]
    notes = list(draft.notes)
    if not sentences:
        return draft
    payload = {
        "facts": [{"n": i, "text": text} for i, text in enumerate(sentences, start=1)],
        "draft": {"headline": draft.headline.as_dict(), "story": [line.as_dict() for line in draft.story]},
    }
    messages = [{"role": "system", "content": COMPOSE_INSTRUCTIONS},
                {"role": "user", "content": json.dumps(payload)}]
    for rewriter in rewriters:
        chat = getattr(rewriter, "chat", None)
        if chat is None:
            notes.append(f"{rewriter.name} cannot compose, only reword")
            continue
        try:
            answer = json.loads(chat(messages))
            headline = _line(answer.get("headline"))
            story_items = answer.get("story")
            if headline is None or not isinstance(story_items, list):
                raise ValueError("the answer has no headline or story list")
        except Exception as exc:  # an optional layer: any failure falls back to the next model, then to the draft
            notes.append(f"{rewriter.name} was not used: {type(exc).__name__}: {exc}")
            continue
        if not grounded(headline, sentences):
            notes.append(f"{rewriter.name} wrote a headline that was not grounded in the trace, so the draft is used")
            continue
        candidates = (_line(item) for item in story_items[:MAX_STORY_LINES])
        story = [line for line in candidates if line and grounded(line, sentences)]
        if not story:
            notes.append(f"{rewriter.name} wrote no grounded story line, so the draft is used")
            continue
        dropped = min(len(story_items), MAX_STORY_LINES) - len(story)
        notes.append(f"{rewriter.name} wrote the headline and {len(story)} story lines"
                     + (f"; {dropped} lines were dropped as not grounded" if dropped else ""))
        return Narrative(headline=headline, story=tuple(story), checks=draft.checks, followups=draft.followups,
                         generator=rewriter.name, notes=tuple(notes))
    return Narrative(headline=draft.headline, story=draft.story, checks=draft.checks, followups=draft.followups,
                     generator="templates", notes=tuple(notes))


# ---------- the whole copilot output for one case ----------

def with_narrative(conn, diff: CaseDiff, summary: CopilotSummary,
                   rewriters: Sequence[Rewriter] = ()) -> CopilotSummary:
    """The summary with its narrative: the code's draft, or a model's grounded composition when one is given."""
    draft = draft_narrative(conn, diff, summary)
    narrative = compose(summary, draft, rewriters) if rewriters else draft
    return replace(summary, narrative=narrative.as_dict(), generator=narrative.generator,
                   notes=(*summary.notes, *narrative.notes))


def summary_inputs(summary: CopilotSummary, models: Sequence[str], **extra: Any) -> dict[str, Any]:
    """Everything a summary is written from, for its cache fingerprint (I-30)."""
    sources = sorted({json.dumps(ref.as_dict(), sort_keys=True) for s in summary.sentences for ref in s.sources})
    return {
        "case_id": summary.case_id, "before_state_id": summary.before_state_id,
        "after_state_id": summary.after_state_id, "outcome": summary.outcome, "sources": sources,
        "template_version": summary.template_version, "narrative_version": NARRATIVE_VERSION,
        "prompt_version": PROMPT_VERSION, "models": list(models), **extra,
    }


def build_copilot(conn, case_id: str, rewriters: Sequence[Rewriter] = (), *, before_release: Optional[str] = None,
                  after_release: Optional[str] = None) -> CopilotSummary:
    """The trace sentences and the narrative on top of them. Reads only; a model is asked only when one is given."""
    diff = case_diff(conn, case_id, before_release=before_release, after_release=after_release)
    return with_narrative(conn, diff, summary_from_diff(conn, diff), rewriters)
