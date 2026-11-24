"""Ask AMRTrace (task I-31, D-27, rule 9): a conversation about cases, changes and determinants, from stored records.

The I-25 chat answered one question about one case and forgot it. The assistant keeps the conversation: the browser
sends the last few turns with each question, and the page the user is on (a case, a change), so a follow-up such as
"is it the only one?" can be read against what was said before. The server stays stateless.

How a question is answered:

1. **Look up records**, read-only and on the server, before any model is asked: the case in view (its comparison,
   dependencies, evidence, change and review status, as I-25 retrieves them), every change and case named in the
   question or the recent turns, the change that produced the case's state (how many cases it selected and moved,
   and from which state to which), and any determinant symbol named in the question (its genotype rows and isolates).
   Each record has an id, the text the model may use, and the page that shows it.
2. **Answer**: a configured model (D-27 order) gets the recent turns, the question and the numbered records, and
   must cite records for every sentence. A sentence is kept only when it cites records that exist, names no identifier
   or number they do not hold, and says nothing that decides, recommends or treats (the I-29 check). With no model,
   or when nothing survives, the answer is written by code from the records on the question's topic.
3. **Blocks**: small structured pieces the page draws next to the text (the case's state transition, a change's
   transition counts, a determinant card), written by code from the same records and shown only when the answer
   cites their records.

The answer is cached under a fingerprint of the question, the recent turns, the page context, the records and the
models (I-30), so asking again costs nothing; a Reviewer or Admin may pin an answer about a case. Asking never
writes anything but that cache. No engine package reads it (rule 9).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .chat import (
    MODE_HOSTED,
    MODE_LOCAL,
    MODE_RECORDS_ONLY,
    MODE_TEMPLATE,
    answer_question,
    question_topics,
    retrieve,
    source_id,
    source_label,
)
from .language_model import Rewriter, facts
from .narrative import _allowed, assigns_state, display_name, short_id
from .templates import words

MAX_TURNS = 8
MAX_TURN_CHARS = 2000
MAX_SENTENCES = 6
MAX_RECORDS = 40
PROMPT_VERSION = "ASK_AMRTRACE_V1"

ASSISTANT_INSTRUCTIONS = (
    "You are Ask AMRTrace, the assistant in an antimicrobial-resistance research workbench. Answer the user's latest "
    "question in two to five short, plain sentences, as a knowledgeable colleague would. Earlier turns are given so "
    "you can resolve words like 'it' or 'that change'. Use ONLY the numbered records: every sentence must cite the "
    "ids of the records it uses. Copy identifiers, versions and numbers exactly as the records write them; you may "
    "write an edition code such as CLSI_M100_ED36 as 'CLSI M100 ed. 36'. Never say what a state should be, never "
    "recommend a review decision, and never give clinical advice. If the records do not answer the question, say so "
    "in one sentence citing the closest record. Answer with JSON only: "
    "{\"answer\": [{\"text\": \"...\", \"source_ids\": [\"...\"]}]}"
)

# words that ask about the change's reach rather than the case itself
_REACH = ("other", "only", "how many", "which cases", "affect", "else", "reach", "moved", "all cases")
_CASE_ID = re.compile(r"\bCASE_[0-9a-f]{8,}\b")
_SYMBOL = re.compile(r"\b[A-Za-z][A-Za-z0-9_()'\-]{2,30}\b")


@dataclass(frozen=True)
class Turn:
    role: str            # "user" or "assistant"
    text: str


@dataclass(frozen=True)
class Record:
    id: str
    kind: str
    label: str
    text: str
    link: Optional[dict[str, Optional[str]]]
    topics: frozenset[str] = frozenset()

    def as_source(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "label": self.label, "link": self.link}


@dataclass(frozen=True)
class Block:
    type: str            # "transition", "table" or "determinant"
    title: str
    source_ids: tuple[str, ...]
    data: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"type": self.type, "title": self.title, "source_ids": list(self.source_ids), "data": self.data}


@dataclass(frozen=True)
class Sentence:
    text: str
    source_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "source_ids": list(self.source_ids)}


@dataclass(frozen=True)
class AssistantAnswer:
    question: str
    case_id: Optional[str]
    state_id: Optional[int]
    answer: tuple[Sentence, ...]
    sources: tuple[dict[str, Any], ...]
    blocks: tuple[Block, ...]
    suggestions: tuple[str, ...]
    mode: str
    generator: str
    notes: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question, "case_id": self.case_id, "state_id": self.state_id,
            "answer": [s.as_dict() for s in self.answer], "sources": list(self.sources),
            "blocks": [b.as_dict() for b in self.blocks], "suggestions": list(self.suggestions),
            "generated": True, "mode": self.mode, "generator": self.generator, "notes": list(self.notes),
        }


# ---------- the conversation ----------

def recent_turns(history: Sequence[Turn]) -> list[Turn]:
    """The last MAX_TURNS turns, each cut to MAX_TURN_CHARS; anything that is not a user or assistant turn is dropped."""
    kept = [Turn(t.role, t.text.strip()[:MAX_TURN_CHARS]) for t in history
            if t.role in ("user", "assistant") and t.text.strip()]
    return kept[-MAX_TURNS:]


# ---------- links: where each record opens in the workbench ----------

def link_for(kind: str, record_id: str, case_id: Optional[str]) -> Optional[dict[str, Optional[str]]]:
    if kind == "change_event":
        return {"view": "changes", "id": record_id}
    if kind == "release":
        return {"view": "exports", "id": record_id}
    if kind == "review_event":
        return {"view": "review-queue", "id": None}
    if kind == "dependency" and case_id:
        return {"view": "dependencies", "id": case_id}
    if case_id and kind in ("case", "case_state", "ast_evidence", "genotype_evidence"):
        return {"view": "dossier", "id": case_id}
    return None


# ---------- looking up records ----------

def _case_records(conn, case_id: str) -> tuple[Optional[int], list[Record]]:
    state_id, candidates = retrieve(conn, case_id)
    texts: dict[str, list[str]] = {}
    kinds: dict[str, Any] = {}
    topics: dict[str, set[str]] = {}
    for candidate in candidates:
        for ref in candidate.sentence.sources:
            sid = source_id(ref)
            texts.setdefault(sid, []).append(candidate.sentence.text)
            kinds[sid] = ref
            topics.setdefault(sid, set()).update(candidate.topics)
    records = [Record(sid, kinds[sid].kind, source_label(kinds[sid]), " ".join(texts[sid]),
                      link_for(kinds[sid].kind, kinds[sid].id, case_id), frozenset(topics[sid] | {"case"}))
               for sid in texts]
    return state_id, records


def _transition_block(conn, case_id: str) -> Optional[Block]:
    from amrtrace.reeval.diff import case_diff

    diff = case_diff(conn, case_id)
    if not (diff.before and diff.after) or diff.before.state_id == diff.after.state_id:
        return None
    return Block("transition", f"Case {short_id(case_id, 12)}",
                 (f"case_state:{diff.before.state_id}", f"case_state:{diff.after.state_id}"),
                 {"before": {"release_id": diff.before.release_id, "state_code": diff.before.state_code},
                  "after": {"release_id": diff.after.release_id, "state_code": diff.after.state_code},
                  "case_id": case_id})


def _case_change(conn, case_id: str) -> Optional[str]:
    from amrtrace.reeval.diff import case_diff

    return case_diff(conn, case_id).triggered_by_change_id


def change_record(conn, change_id: str) -> tuple[Optional[Record], Optional[Block]]:
    """What a change is, and how far it reached: cases selected and moved per release, and the moves by state."""
    row = conn.execute("SELECT type, old_version, new_version, initiator FROM change_event WHERE change_id = %s",
                       (change_id,)).fetchone()
    if row is None:
        return None, None
    change_type, old, new, initiator = row
    counts = conn.execute(
        "SELECT s.release_id, count(*) AS selected, count(*) FILTER (WHERE s.verification_status = 'STATE_CHANGED') "
        "FROM case_state s JOIN release r ON r.release_id = s.release_id "
        "WHERE s.triggered_by_change_id = %s AND r.status = 'PUBLISHED' GROUP BY s.release_id ORDER BY s.release_id",
        (change_id,)).fetchall()
    moves = conn.execute(
        "SELECT p.state_code, s.state_code, count(*) FROM case_state s "
        "JOIN release r ON r.release_id = s.release_id JOIN case_state p ON p.state_id = s.supersedes_state_id "
        "WHERE s.triggered_by_change_id = %s AND s.verification_status = 'STATE_CHANGED' AND r.status = 'PUBLISHED' "
        "GROUP BY 1, 2 ORDER BY 3 DESC, 1, 2", (change_id,)).fetchall()
    moved = f" from {old} to {new}" if old or new else ""
    text = [f"Change {change_id} is {_article(words(change_type))} change{moved}, registered by {initiator}."]
    for release_id, selected, changed in counts:
        text.append(f"In release {release_id} it re-evaluated {selected} cases: {changed} changed state and "
                    f"{selected - changed} kept their state.")
    for before, after, count in moves[:6]:
        text.append(f"{count} cases moved from {words(before)} to {words(after)}.")
    if not counts:
        text.append("No published release was produced by it yet.")
    sid = f"change_event:{change_id}"
    record = Record(sid, "change_event", f"change {change_id}", " ".join(text), link_for("change_event", change_id, None),
                    frozenset({"change", "reach", "provenance", "version"}))
    block = None
    if moves:
        block = Block("table", f"How {change_id} moved cases", (sid,),
                      {"columns": ["From", "To", "Cases"],
                       "rows": [[words(b), words(a), n] for b, a, n in moves[:8]]})
    return record, block


def determinant_records(conn, text: str) -> list[tuple[Record, Block]]:
    """Determinant symbols named in the text that exist in the genotype rows, with how often they occur."""
    tokens = sorted({t.lower() for t in _SYMBOL.findall(text)} - _COMMON)
    if not tokens:
        return []
    rows = conn.execute(
        "SELECT element_symbol_raw, count(*), count(DISTINCT target_acc), min(subclass_raw), min(subtype_raw), "
        "min(element_name_raw) FROM genotype_evidence WHERE lower(element_symbol_raw) = ANY(%s) "
        "GROUP BY element_symbol_raw ORDER BY 2 DESC LIMIT 3", (tokens,)).fetchall()
    found = []
    for symbol, row_count, isolates, subclass, subtype, name in rows:
        detail = ", ".join(p for p in (f"subclass {subclass}" if subclass else "", f"type {subtype}" if subtype else "")
                           if p)
        named = f" ({name})" if name and name != symbol else ""
        text_out = (f"Determinant {symbol}{named} appears on {row_count} stored genotype rows from {isolates} isolates"
                    + (f"; {detail}" if detail else "") + ".")
        sid = f"determinant:{symbol}"
        record = Record(sid, "determinant", f"determinant {symbol}", text_out, None, frozenset({"evidence", "gene"}))
        block = Block("determinant", symbol, (sid,), {"symbol": symbol, "name": name, "rows": row_count,
                                                       "isolates": isolates, "subclass": subclass, "type": subtype})
        found.append((record, block))
    return found


_COMMON = {"the", "and", "why", "what", "which", "case", "cases", "change", "changes", "rule", "rules", "gene",
           "genes", "this", "that", "with", "does", "did", "how", "many", "other", "only", "about", "from", "show",
           "tell", "for", "are", "was", "were", "has", "have", "its", "it's", "now", "read", "lab", "state", "review",
           "evidence", "depend", "depends", "version", "release", "mean", "means", "not", "defined"}


def _article(phrase: str) -> str:
    return ("an " if phrase[:1] in "aeiou" else "a ") + phrase


def _named_changes(conn, text: str) -> list[str]:
    rows = conn.execute("SELECT change_id FROM change_event WHERE position(lower(change_id) IN lower(%s)) > 0 "
                        "ORDER BY length(change_id) DESC LIMIT 3", (text,)).fetchall()
    return [r[0] for r in rows]


def _named_cases(conn, text: str) -> list[str]:
    found = []
    for prefix in _CASE_ID.findall(text)[:2]:
        rows = conn.execute('SELECT case_id FROM "case" WHERE case_id LIKE %s ORDER BY case_id LIMIT 2',
                            (prefix + "%",)).fetchall()
        if len(rows) == 1:
            found.append(rows[0][0])
    return found


@dataclass
class Gathered:
    case_id: Optional[str]
    state_id: Optional[int]
    records: list[Record]
    blocks: list[Block]
    change_ids: list[str]


def gather(conn, question: str, history: Sequence[Turn], case_id: Optional[str] = None,
           change_id: Optional[str] = None) -> Gathered:
    """Every record the question may need, read-only. Raises CaseNotFound for an unknown case in view."""
    recent_text = " ".join([question] + [t.text for t in history[-4:]])
    records: list[Record] = []
    blocks: list[Block] = []
    state_id = None
    cases = ([case_id] if case_id else []) + [c for c in _named_cases(conn, recent_text) if c != case_id]
    changes = ([change_id] if change_id else [])
    for i, case in enumerate(cases[:2]):
        sid, found = _case_records(conn, case)
        if i == 0:
            state_id = sid
        records += found
        block = _transition_block(conn, case)
        if block:
            blocks.append(block)
        produced_by = _case_change(conn, case)
        if produced_by and produced_by not in changes:
            changes.append(produced_by)
    for named in _named_changes(conn, recent_text):
        if named not in changes:
            changes.append(named)
    for change in changes[:3]:
        record, block = change_record(conn, change)
        if record:
            records.append(record)
        if block:
            blocks.append(block)
    for record, block in determinant_records(conn, question):
        records.append(record)
        blocks.append(block)
    unique: dict[str, Record] = {}
    for record in records:
        seen = unique.get(record.id)
        if seen is None:
            unique[record.id] = record
        elif record.text not in seen.text:
            # the same record found twice (a case's change, and that change's reach): one record holding both texts
            # a change's own description and reach read first, then what the case's records said about it
            text = f"{record.text} {seen.text}" if "reach" in record.topics else f"{seen.text} {record.text}"
            unique[record.id] = Record(seen.id, seen.kind, seen.label, text, seen.link or record.link,
                                       seen.topics | record.topics)
    # what the question names (determinants, changes) comes first, so a case with many records cannot crowd it out
    ordered = sorted(unique.values(), key=lambda r: 0 if r.kind in ("determinant", "change_event") else 1)
    return Gathered(cases[0] if cases else None, state_id, ordered[:MAX_RECORDS], blocks, changes)


# ---------- answering ----------

def _grounded(sentence: Sentence, records: dict[str, Record]) -> bool:
    if not sentence.text or not sentence.source_ids or assigns_state(sentence.text):
        return False
    if any(sid not in records for sid in sentence.source_ids):
        return False
    return facts(sentence.text) <= _allowed([records[sid].text for sid in sentence.source_ids])


def _ask_model(question: str, history: Sequence[Turn], gathered: Gathered, rewriters: Sequence[Rewriter],
               notes: list[str]) -> tuple[Optional[list[Sentence]], Optional[str]]:
    records = {r.id: r for r in gathered.records}
    context = {"case_in_view": gathered.case_id, "changes_in_view": gathered.change_ids}
    messages = [{"role": "system", "content": ASSISTANT_INSTRUCTIONS}]
    messages += [{"role": t.role, "content": t.text} for t in history]
    messages.append({"role": "user", "content": json.dumps({
        "question": question, "context": context,
        "records": [{"id": r.id, "text": display_hint(r.text)} for r in gathered.records]})})
    for rewriter in rewriters:
        chat = getattr(rewriter, "chat", None)
        if chat is None:
            notes.append(f"{rewriter.name} cannot answer questions, only reword")
            continue
        try:
            items = json.loads(chat(messages))["answer"]
            if not isinstance(items, list):
                raise ValueError("the answer is not a list")
        except Exception as exc:  # an optional layer: any failure falls back to the next model, then to code
            notes.append(f"{rewriter.name} was not used: {type(exc).__name__}: {exc}")
            continue
        kept = []
        for item in items[:MAX_SENTENCES]:
            if not isinstance(item, dict):
                continue
            sentence = Sentence(str(item.get("text", "")).strip(),
                                tuple(str(s) for s in (item.get("source_ids") or [])))
            if _grounded(sentence, records):
                kept.append(sentence)
        dropped = min(len(items), MAX_SENTENCES) - len(kept)
        notes.append(f"{rewriter.name} answered with {len(kept)} grounded sentences"
                     + (f"; {dropped} were dropped as not grounded" if dropped else ""))
        if kept:
            return kept, rewriter.name
    return None, None


def display_hint(text: str) -> str:
    """Records go to the model as stored; nothing is rewritten, so every code it copies can be checked."""
    return text


def _by_code(question: str, gathered: Gathered, conn, rewriters_used: bool) -> tuple[list[Sentence], str, list[str]]:
    """An answer written by code: the records on the question's topic."""
    notes: list[str] = []
    text = question.lower()
    reach = any(cue in text for cue in _REACH)
    determinants = [r for r in gathered.records if r.kind == "determinant"]
    changes = [r for r in gathered.records if r.kind == "change_event" and "reach" in r.topics]
    if determinants and not (reach and changes):
        return [Sentence(r.text, (r.id,)) for r in determinants], MODE_TEMPLATE, notes
    if reach and changes:
        return [Sentence(_first_sentences(r.text, 4), (r.id,)) for r in changes[:1]], MODE_TEMPLATE, notes
    if gathered.case_id:
        answer = answer_question(conn, gathered.case_id, question, ())
        sentences = [Sentence(s.text, s.source_ids) for s in answer.answer]
        notes += list(answer.notes)
        if answer.mode == MODE_RECORDS_ONLY:
            return sentences[:MAX_SENTENCES], MODE_RECORDS_ONLY, notes
        return sentences, MODE_TEMPLATE, notes
    if changes:
        return [Sentence(_first_sentences(r.text, 4), (r.id,)) for r in changes[:1]], MODE_TEMPLATE, notes
    notes.append("the question names no case, change or determinant this workbench holds"
                 + ("" if rewriters_used else ", and no language model is configured"))
    return [], MODE_RECORDS_ONLY, notes


def _first_sentences(text: str, count: int) -> str:
    parts = re.split(r"(?<=\.)\s+", text)
    return " ".join(parts[:count])


def suggestions_for(gathered: Gathered, question: str) -> tuple[str, ...]:
    asks = []
    if gathered.case_id:
        asks.append("Why did this case change?")
    for change in gathered.change_ids[:1]:
        asks.append(f"Which other cases did {change} change?")
    if gathered.case_id:
        asks += ["What does this case depend on now?", "Has the new state been reviewed?"]
    if not asks:
        asks = ["Ask about a case: paste its id, or open its dossier first", "Which cases did a change move?"]
    asked = question.strip().lower().rstrip("?")
    return tuple(a for a in asks if a.lower().rstrip("?") != asked)[:3]


def _mode_of(generator: str) -> str:
    return MODE_LOCAL if generator.startswith("local:") else MODE_HOSTED


def ask(conn, question: str, history: Sequence[Turn] = (), *, case_id: Optional[str] = None,
        change_id: Optional[str] = None, rewriters: Sequence[Rewriter] = (),
        gathered: Optional[Gathered] = None) -> AssistantAnswer:
    """Answer the latest question of a conversation from stored records only. Reads only.

    `gathered` is the result of gather() for the same question, history and context, when the caller already has it
    (the API looks the records up once for the cache fingerprint and once more only if nothing is cached).
    """
    question = question.strip()
    if not question:
        raise ValueError("the question is empty")
    history = recent_turns(history)
    if gathered is None:
        gathered = gather(conn, question, history, case_id, change_id)
    records = {r.id: r for r in gathered.records}
    notes: list[str] = []
    sentences, generator = (None, None)
    if rewriters and gathered.records:
        sentences, generator = _ask_model(question, history, gathered, rewriters, notes)
    if sentences:
        mode = _mode_of(generator)
    else:
        sentences, mode, more = _by_code(question, gathered, conn, bool(rewriters))
        notes += more
        generator = "templates" if mode == MODE_TEMPLATE else "records"
    cited: list[str] = []
    for sentence in sentences:
        for sid in sentence.source_ids:
            if sid not in cited and sid in records:
                cited.append(sid)
    blocks = tuple(b for b in gathered.blocks if set(b.source_ids) & set(cited))
    return AssistantAnswer(
        question=question, case_id=gathered.case_id, state_id=gathered.state_id, answer=tuple(sentences),
        sources=tuple(records[sid].as_source() for sid in cited), blocks=blocks,
        suggestions=suggestions_for(gathered, question), mode=mode, generator=generator, notes=tuple(notes),
    )


def answer_inputs(question: str, history: Sequence[Turn], case_id: Optional[str], change_id: Optional[str],
                  models: Sequence[str], gathered: Gathered) -> dict[str, Any]:
    """Everything an answer is written from, for its cache fingerprint (I-30): the conversation and the records."""
    return {
        "question": question.strip(), "history": [[t.role, t.text] for t in recent_turns(history)],
        "case_id": case_id, "change_id": change_id, "models": list(models), "prompt_version": PROMPT_VERSION,
        "records": sorted([r.id, r.text] for r in gathered.records),
        "blocks": [b.as_dict() for b in gathered.blocks],
    }


__all__ = ["AssistantAnswer", "Block", "Gathered", "Record", "Sentence", "Turn", "answer_inputs", "ask",
           "change_record", "determinant_records", "display_name", "gather", "link_for", "recent_turns",
           "question_topics", "suggestions_for"]
