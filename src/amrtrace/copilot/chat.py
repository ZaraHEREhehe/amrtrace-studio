"""Review Copilot chat (task I-25, D-27, rule 9): questions about one case, answered only from its stored records.

Retrieval is limited to the stored records of the selected case: its before/after comparison (I-13), its current
dependency subgraph (A-10), the evidence rows the subgraph reads, the change that produced its state, and its review
status (I-18). Each retrieved record becomes one or more candidate sentences, built by the same templates as the
summary, so every sentence names the records it came from (SourceRef).

How a question is answered, in the order of D-27:

    template      the question names a topic (why it changed, evidence, rules, versions, review, the change) and the
                  candidate sentences on that topic are the answer. A configured model may reword them; a reworded
                  sentence that loses or adds an identifier or number goes back to its template (as in I-19), and
                  the mode is then local or hosted
    local/hosted  no topic matched and a model is configured: the model answers from the numbered records only, and
                  every sentence must cite records that exist and carry no identifier or number they do not hold;
                  sentences that fail are dropped
    records_only  no topic matched and no model answered: the answer is the retrieved records themselves

Every answer is labelled as generated. Asking writes nothing. A saved answer goes to copilot_chat_answer (migration
0016), apart from evidence; no engine package reads it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Iterable, Optional, Sequence

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from amrtrace.deps.subgraph import case_subgraph
from amrtrace.reeval.diff import case_diff

from .language_model import Rewriter, facts, keeps_facts
from .sources import KIND_AST, KIND_DEPENDENCY, KIND_GENOTYPE, SourceRef
from .templates import (
    EVIDENCE_NODE_TYPES,
    PROVENANCE_DEP_TYPE,
    Sentence,
    _ast_text,
    _change_sentence,
    _evidence_sentences,
    _genotype_text,
    _label_sentences,
    _outcome_sentences,
    _review_sentence,
    _rows,
    _rule_sentences,
    _version_sentences,
    words,
)

MODE_TEMPLATE = "template"
MODE_LOCAL = "local"
MODE_HOSTED = "hosted"
MODE_RECORDS_ONLY = "records_only"
MAX_QUESTION_LENGTH = 500

# topics a question can ask about, and the words that name them (lower case, matched as word prefixes)
TOPIC_WORDS = {
    "change": ("why", "chang", "differ", "before", "after", "moved", "move", "happen", "outcome", "state", "flip",
               "conclusion", "result"),
    "evidence": ("evidence", "ast", "mic", "disk", "zone", "phenotyp", "lab", "label", "measure", "genotyp",
                 "determinant", "gene", "element", "row"),
    "dependency": ("depend", "rule", "graph", "edge", "mapping", "interpret", "breakpoint", "support"),
    "version": ("version", "edition", "release", "snapshot", "database"),
    "review": ("review", "verif", "unverif", "queue", "confirm", "correct", "check"),
    "provenance": ("who", "which change", "registered", "initiator", "triggered", "caused by", "produced"),
}

CHAT_INSTRUCTIONS = (
    "You answer a reviewer's question about one antimicrobial-resistance case using ONLY the numbered records given. "
    "Every sentence must cite the ids of the records it uses. Copy identifiers, codes, versions and numbers exactly; "
    "never add a fact, number or identifier that is not in the cited records, and never give clinical advice. If the "
    "records do not answer the question, say so in one sentence citing the closest record. Answer with JSON only: "
    "{\"answer\": [{\"text\": \"...\", \"source_ids\": [\"...\"]}]}"
)


@dataclass(frozen=True)
class Candidate:
    """One template sentence the retrieval produced, with the topics it answers."""

    sentence: Sentence
    topics: frozenset[str]


@dataclass(frozen=True)
class AnswerSentence:
    text: str
    source_ids: tuple[str, ...]
    template_text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "source_ids": list(self.source_ids),
                "template_text": self.template_text or self.text}


@dataclass(frozen=True)
class ChatSource:
    id: str
    kind: str
    label: str

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "kind": self.kind, "label": self.label}


@dataclass(frozen=True)
class ChatAnswer:
    case_id: str
    question: str
    state_id: Optional[int]
    answer: tuple[AnswerSentence, ...]
    sources: tuple[ChatSource, ...]
    mode: str
    generator: str
    notes: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "question": self.question, "state_id": self.state_id,
            "answer": [s.as_dict() for s in self.answer], "sources": [s.as_dict() for s in self.sources],
            "generated": True, "mode": self.mode, "generator": self.generator, "notes": list(self.notes),
        }


# ---------- sources ----------

def source_id(ref: SourceRef) -> str:
    """A stable id for one stored record, as the answer cites it."""
    if ref.kind == KIND_DEPENDENCY:
        return f"{ref.kind}:{ref.release_id}:{ref.node_type}:{ref.id}"
    return f"{ref.kind}:{ref.id}"


def source_label(ref: SourceRef) -> str:
    labels = {
        "case": f"case {ref.id}", "case_state": f"case state {ref.id}", "release": f"release {ref.id}",
        "change_event": f"change {ref.id}", "ast_evidence": f"AST result {ref.id}",
        "genotype_evidence": f"genotype row {ref.id}", "review_event": f"review {ref.id}",
    }
    if ref.kind == KIND_DEPENDENCY:
        return f"{words(ref.node_type)} {ref.id} (release {ref.release_id})"
    return labels.get(ref.kind, f"{ref.kind} {ref.id}")


# ---------- retrieval ----------

def _tag(sentences: Iterable[Sentence], *topics: str) -> list[Candidate]:
    return [Candidate(s, frozenset(topics)) for s in sentences]


def _current_dependency_candidates(conn, case_id: str) -> list[Candidate]:
    """What the current state depends on now: one sentence per rule edge, one per evidence row (A-10 subgraph)."""
    try:
        graph = case_subgraph(conn, case_id)
    except LookupError:
        return []
    nodes = {n.key: n for n in graph.nodes}
    evidence_ids = {kind: sorted({nodes[e.target].node_id for e in graph.edges
                                  if nodes[e.target].node_type == kind}) for kind in EVIDENCE_NODE_TYPES}
    rows = {KIND_AST: _rows(conn, KIND_AST, "ast_evidence_id", evidence_ids[KIND_AST]),
            KIND_GENOTYPE: _rows(conn, KIND_GENOTYPE, "genotype_evidence_id", evidence_ids[KIND_GENOTYPE])}
    candidates: list[Candidate] = []
    seen: set[tuple] = set()
    for edge in sorted(graph.edges, key=lambda e: (nodes[e.target].node_type, nodes[e.target].node_id, e.dep_type)):
        node = nodes[edge.target]
        key = (node.node_type, node.node_id, node.node_version, edge.dep_type)
        if key in seen or edge.dep_type == PROVENANCE_DEP_TYPE:
            continue
        seen.add(key)
        dep_ref = SourceRef(KIND_DEPENDENCY, node.node_id, release_id=graph.release_id, node_type=node.node_type)
        if node.node_type in EVIDENCE_NODE_TYPES:
            row = rows[node.node_type].get(node.node_id)
            describe = _ast_text if node.node_type == KIND_AST else _genotype_text
            refs = (dep_ref, SourceRef(node.node_type, node.node_id)) if row is not None else (dep_ref,)
            text = f"In release {graph.release_id} its state reads {describe(row, node.node_id)}."
            candidates.append(Candidate(Sentence(text, refs), frozenset({"evidence"})))
        else:
            version = f" at version {node.node_version}" if node.node_version else ""
            text = (f"In release {graph.release_id} its state depends on {words(node.node_type)} {node.node_id}"
                    f"{version} ({words(edge.dep_type)}).")
            candidates.append(Candidate(Sentence(text, (dep_ref,)), frozenset({"dependency"})))
    return candidates


def retrieve(conn, case_id: str) -> tuple[Optional[int], list[Candidate]]:
    """The candidate sentences for one case, from its stored records only. Raises CaseNotFound for an unknown case."""
    diff = case_diff(conn, case_id)
    candidates = _tag(_outcome_sentences(diff), "change", "version")
    if diff.triggered_by_change_id:
        change = _change_sentence(conn, diff.triggered_by_change_id)
        if change is not None:
            candidates += _tag([change], "change", "provenance")
    if diff.before and diff.after and diff.before.state_id != diff.after.state_id:
        candidates += _tag(_version_sentences(diff), "version", "change")
        candidates += _tag(_evidence_sentences(conn, diff), "evidence", "change")
        candidates += _tag(_rule_sentences(diff), "dependency", "change")
    if diff.after:
        candidates += _tag(_label_sentences(conn, diff), "evidence", "review")
        review = _review_sentence(conn, case_id)
        if review is not None:
            candidates += _tag([review], "review")
    candidates += _current_dependency_candidates(conn, case_id)
    unique: dict[str, Candidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.sentence.text, candidate)
    return (diff.after.state_id if diff.after else None), list(unique.values())


def question_topics(question: str) -> frozenset[str]:
    text = " " + re.sub(r"[^a-z0-9 ]+", " ", question.lower()) + " "
    found = set()
    for topic, cues in TOPIC_WORDS.items():
        if any((" " + cue) in text for cue in cues):
            found.add(topic)
    return frozenset(found)


# ---------- answering ----------

def _sources_for(sentences: Sequence[AnswerSentence], refs: dict[str, SourceRef]) -> tuple[ChatSource, ...]:
    cited = []
    for sentence in sentences:
        for sid in sentence.source_ids:
            if sid not in cited:
                cited.append(sid)
    return tuple(ChatSource(sid, refs[sid].kind, source_label(refs[sid])) for sid in cited)


def _from_template(sentence: Sentence) -> AnswerSentence:
    return AnswerSentence(sentence.text, tuple(source_id(r) for r in sentence.sources), sentence.template_text)


def _mode_of(generator: str) -> str:
    return MODE_LOCAL if generator.startswith("local:") else MODE_HOSTED


def _reword(sentences: list[Sentence], rewriters: Sequence[Rewriter], notes: list[str]):
    """Template sentences reworded by the first model that answers; a sentence that changes a fact stays a template."""
    templates = [s.template_text for s in sentences]
    for rewriter in rewriters:
        try:
            answers = rewriter.rewrite(templates)
            if len(answers) != len(templates):
                raise ValueError(f"{len(answers)} sentences for {len(templates)}")
        except Exception as exc:  # an optional layer: any failure falls back to the next model, then to templates
            notes.append(f"{rewriter.name} was not used: {type(exc).__name__}: {exc}")
            continue
        kept = [replace(s, text=a.strip()) if keeps_facts(s.template_text, a) else s
                for s, a in zip(sentences, answers)]
        changed = sum(1 for s, k in zip(sentences, kept) if k.text != s.text)
        notes.append(f"{rewriter.name} reworded {changed} of {len(sentences)} sentences; the rest are templates")
        return kept, rewriter.name
    return sentences, None


def _grounded(text: str, cited: Sequence[str], record_text: dict[str, str]) -> bool:
    """True when every identifier and number in the sentence appears in the records it cites."""
    if not text.strip() or not cited or any(sid not in record_text for sid in cited):
        return False
    allowed = set().union(*(facts(record_text[sid]) for sid in cited))
    return facts(text) <= allowed


def _ask_model(question: str, candidates: list[Candidate], rewriters: Sequence[Rewriter], notes: list[str]):
    """The model's answer from the numbered records, keeping only sentences grounded in the records they cite."""
    record_text: dict[str, str] = {}
    for candidate in candidates:
        for ref in candidate.sentence.sources:
            sid = source_id(ref)
            record_text[sid] = (record_text.get(sid, "") + " " + candidate.sentence.text).strip()
    records = [{"id": sid, "text": text} for sid, text in record_text.items()]
    messages = [{"role": "system", "content": CHAT_INSTRUCTIONS},
                {"role": "user", "content": json.dumps({"question": question, "records": records})}]
    for rewriter in rewriters:
        chat = getattr(rewriter, "chat", None)
        if chat is None:
            notes.append(f"{rewriter.name} cannot answer questions, only reword")
            continue
        try:
            items = json.loads(chat(messages))["answer"]
            if not isinstance(items, list):
                raise ValueError("the answer is not a list")
        except Exception as exc:  # an optional layer: any failure falls back to the next model, then to the records
            notes.append(f"{rewriter.name} was not used: {type(exc).__name__}: {exc}")
            continue
        kept = []
        for item in items:
            text = str(item.get("text", "")).strip() if isinstance(item, dict) else ""
            cited = tuple(str(s) for s in (item.get("source_ids") or [])) if isinstance(item, dict) else ()
            if _grounded(text, cited, record_text):
                kept.append(AnswerSentence(text, cited, text))
        dropped = len(items) - len(kept)
        notes.append(f"{rewriter.name} answered with {len(items)} sentences; {dropped} were dropped because they "
                     "cited no stored record or named something their records do not hold")
        if kept:
            return kept, rewriter.name
    return None, None


def answer_question(conn, case_id: str, question: str, rewriters: Sequence[Rewriter] = ()) -> ChatAnswer:
    """Answer one question about one case from its stored records. Reads only; writes nothing."""
    question = question.strip()
    if not question:
        raise ValueError("the question is empty")
    state_id, candidates = retrieve(conn, case_id)
    refs = {source_id(r): r for c in candidates for r in c.sentence.sources}
    topics = question_topics(question)
    chosen = [c.sentence for c in candidates if c.topics & topics]
    notes: list[str] = []

    if chosen:
        sentences, generator = _reword(chosen, rewriters, notes) if rewriters else (chosen, None)
        answer = [_from_template(s) for s in sentences]
        mode = _mode_of(generator) if generator else MODE_TEMPLATE
        return ChatAnswer(case_id, question, state_id, tuple(answer), _sources_for(answer, refs), mode,
                          generator or "templates", tuple(notes))

    if rewriters:
        answer, generator = _ask_model(question, candidates, rewriters, notes)
        if answer:
            return ChatAnswer(case_id, question, state_id, tuple(answer), _sources_for(answer, refs),
                              _mode_of(generator), generator, tuple(notes))
    notes.append("no template matched the question" + (" and no model answered" if rewriters else
                                                       " and no language model is configured")
                 + ", so these are the stored records about this case")
    answer = [_from_template(c.sentence) for c in candidates]
    return ChatAnswer(case_id, question, state_id, tuple(answer), _sources_for(answer, refs), MODE_RECORDS_ONLY,
                      "records", tuple(notes))


# ---------- saving (Reviewer or Admin, as for summaries) ----------

@dataclass(frozen=True)
class SavedAnswer:
    answer_id: int
    saved_by: str
    created_at: datetime
    answer: ChatAnswer


def save_answer(conn, answer: ChatAnswer, saved_by: str) -> SavedAnswer:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "INSERT INTO copilot_chat_answer (case_id, state_id, question, mode, generator, saved_by, body) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING answer_id, saved_by, created_at",
            (answer.case_id, answer.state_id, answer.question, answer.mode, answer.generator, saved_by,
             Jsonb(answer.as_dict())),
        )
        row = cursor.fetchone()
    return SavedAnswer(row["answer_id"], row["saved_by"], row["created_at"], answer)
