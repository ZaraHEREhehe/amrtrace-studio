"""Template sentences: why a case changed, written only from stored records (task I-19, D-27).

The input is I-13's stored before/after comparison (reeval.diff.case_diff), the change that produced the new state,
the evidence rows the two states read, and the case's review status. Every sentence names the records it was written
from (SourceRef), and the same records always give the same sentences, so the summary is deterministic and needs no
network. Codes are shown as they are stored, in lower case with spaces, so nothing here names a drug, organism or
standard.

The output is generated text: it is never evidence and never an input to state assignment (rule 9). No engine
package (evaluator, deps, ledger, changes, reeval) imports this module or reads where its output is stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from psycopg.rows import dict_row

from amrtrace.ledger import get_review_status
from amrtrace.reeval.diff import (
    OUTCOME_FIRST_STATE,
    OUTCOME_NO_STATE,
    OUTCOME_RE_VERIFIED,
    OUTCOME_STATE_CHANGED,
    CaseDiff,
    DependencyRecordView,
    case_diff,
)

from .sources import (
    KIND_AST,
    KIND_CASE,
    KIND_CHANGE,
    KIND_DEPENDENCY,
    KIND_GENOTYPE,
    KIND_RELEASE,
    KIND_REVIEW,
    KIND_STATE,
    SourceRef,
)

TEMPLATE_VERSION = "COPILOT_TEMPLATES_V1"
# at most this many records of one kind are named one by one; the rest are counted in one sentence
SHOWN_PER_KIND = 3
# version records name the versions themselves; the version sentences already say what moved
PROVENANCE_DEP_TYPE = "provenance_version"
EVIDENCE_NODE_TYPES = (KIND_AST, KIND_GENOTYPE)
UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class Sentence:
    text: str
    sources: tuple[SourceRef, ...]
    # the template text this sentence started as; equal to text unless a language model reworded it
    template_text: str = ""

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError(f"a copilot sentence must name at least one stored record: {self.text!r}")
        if not self.template_text:
            object.__setattr__(self, "template_text", self.text)

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "template_text": self.template_text,
                "sources": [s.as_dict() for s in self.sources]}


@dataclass(frozen=True)
class CopilotSummary:
    case_id: str
    before_state_id: Optional[int]
    after_state_id: Optional[int]
    outcome: str
    sentences: tuple[Sentence, ...]
    generator: str = "templates"
    template_version: str = TEMPLATE_VERSION
    notes: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "before_state_id": self.before_state_id, "after_state_id": self.after_state_id,
            "outcome": self.outcome, "generator": self.generator, "template_version": self.template_version,
            "sentences": [s.as_dict() for s in self.sentences], "notes": list(self.notes),
        }


def words(code: Any) -> str:
    """A stored code or field name as words: NEWLY_DISCORDANT -> newly discordant. None reads as 'none'."""
    if code is None:
        return "none"
    if isinstance(code, (list, tuple)):
        return ", ".join(words(c) for c in code) if code else "none"
    return str(code).replace("_", " ").lower()


def verbatim(value: Any) -> str:
    """A version or identifier exactly as stored, so a reader can search for it."""
    if value is None:
        return "none"
    if isinstance(value, (list, tuple)):
        return ", ".join(verbatim(v) for v in value) if value else "none"
    return str(value)


def _article(phrase: str) -> str:
    return ("an " if phrase[:1] in "aeiou" else "a ") + phrase


def _state_ref(side) -> SourceRef:
    return SourceRef(KIND_STATE, str(side.state_id))


def _rows(conn, table: str, id_column: str, ids: Iterable[str]) -> dict[str, dict]:
    ids = sorted(set(ids))
    if not ids:
        return {}
    # table and column come from the two fixed calls below, never from stored data
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(f"SELECT * FROM {table} WHERE {id_column} = ANY(%s)", (ids,))
        return {str(row[id_column]): row for row in cursor.fetchall()}


def _ast_text(row: Optional[dict], node_id: str) -> str:
    if row is None:
        return f"AST result {node_id}"
    parts = [f"label {row.get('phenotype_normalized') or 'none'}"]
    if row.get("mic") is not None:
        parts.append(f"MIC {row.get('measurement_sign') or ''}{row['mic']:g}".replace("==", ""))
    if row.get("disk_diffusion") is not None:
        parts.append(f"disk zone {row['disk_diffusion']:g}")
    if row.get("standard"):
        parts.append(f"standard {row['standard']}")
    if row.get("source_snapshot_id"):
        parts.append(f"from {row['source_snapshot_id']}")
    return f"AST result {node_id} ({', '.join(parts)})"


def _genotype_text(row: Optional[dict], node_id: str) -> str:
    if row is None:
        return f"genotype row {node_id}"
    parts = [str(row.get("representation_source") or "genotype")]
    if row.get("refgene_db_version"):
        parts.append(f"database {row['refgene_db_version']}")
    return f"determinant {row.get('element_raw') or node_id} ({', '.join(parts)}, row {node_id})"


def _dependency_ref(record: DependencyRecordView, release_id: str) -> SourceRef:
    return SourceRef(KIND_DEPENDENCY, record.node_id, release_id=release_id, node_type=record.node_type)


def _evidence_sentences(conn, diff: CaseDiff) -> list[Sentence]:
    sentences: list[Sentence] = []
    plans = (
        (KIND_AST, "ast_evidence_id", _ast_text, "AST results"),
        (KIND_GENOTYPE, "genotype_evidence_id", _genotype_text, "genotype rows"),
    )
    for kind, id_column, describe, plural in plans:
        removed = [r for r in diff.dependencies_removed if r.node_type == kind]
        added = [r for r in diff.dependencies_added if r.node_type == kind]
        rows = _rows(conn, kind, id_column, [r.node_id for r in removed + added])
        for verb, records, side in (("no longer reads", removed, diff.before), ("now reads", added, diff.after)):
            unique = sorted({r.node_id: r for r in records}.values(), key=lambda r: r.node_id)
            for record in unique[:SHOWN_PER_KIND]:
                refs = [_dependency_ref(record, side.release_id)]
                if record.node_id in rows:
                    refs.append(SourceRef(kind, record.node_id))
                sentences.append(Sentence(f"It {verb} {describe(rows.get(record.node_id), record.node_id)}.",
                                          tuple(refs)))
            if len(unique) > SHOWN_PER_KIND:
                rest = unique[SHOWN_PER_KIND:]
                sentences.append(Sentence(
                    f"It {verb} {len(rest)} more {plural}.",
                    tuple(_dependency_ref(r, side.release_id) for r in rest),
                ))
    return sentences


def _rule_sentences(diff: CaseDiff) -> list[Sentence]:
    sentences: list[Sentence] = []
    for verb, records, side in (("no longer depends on", diff.dependencies_removed, diff.before),
                                ("now depends on", diff.dependencies_added, diff.after)):
        kept = [r for r in records if r.node_type not in EVIDENCE_NODE_TYPES and r.dep_type != PROVENANCE_DEP_TYPE]
        unique = sorted({(r.node_type, r.node_id, r.node_version): r for r in kept}.values(),
                        key=lambda r: (r.node_type, r.node_id, r.node_version or ""))
        for record in unique[:SHOWN_PER_KIND]:
            version = f" at version {record.node_version}" if record.node_version else ""
            sentences.append(Sentence(
                f"It {verb} {words(record.node_type)} {record.node_id}{version} ({words(record.dep_type)}).",
                (_dependency_ref(record, side.release_id),),
            ))
        if len(unique) > SHOWN_PER_KIND:
            rest = unique[SHOWN_PER_KIND:]
            sentences.append(Sentence(f"It {verb} {len(rest)} more rules or records.",
                                      tuple(_dependency_ref(r, side.release_id) for r in rest)))
    return sentences


def _label_sentences(conn, diff: CaseDiff) -> list[Sentence]:
    flags = (diff.after.explanation or {}).get("label_flags") or [] if diff.after else []
    stored = _rows(conn, KIND_AST, "ast_evidence_id", [f["ast_evidence_id"] for f in flags])
    sentences = []
    for flag in flags:
        if not flag.get("label_changed"):
            continue
        refs = [_state_ref(diff.after)]
        if flag["ast_evidence_id"] in stored:
            refs.append(SourceRef(KIND_AST, flag["ast_evidence_id"]))
        sentences.append(Sentence(
            f"The lab sent label {flag.get('submitted_label') or 'none'} for AST result {flag['ast_evidence_id']}; "
            f"rule {flag.get('rule_key')} reads its measurement as {flag.get('derived_label')}.",
            tuple(refs),
        ))
    return sentences


def _change_sentence(conn, change_id: str) -> Optional[Sentence]:
    row = conn.execute(
        "SELECT type, old_version, new_version, initiator FROM change_event WHERE change_id = %s", (change_id,)
    ).fetchone()
    if row is None:
        return None
    change_type, old, new, initiator = row
    moved = f" from {old} to {new}" if old or new else ""
    return Sentence(
        f"The new state was produced by change {change_id}, {_article(words(change_type))} change{moved}, "
        f"registered by {initiator}.",
        (SourceRef(KIND_CHANGE, change_id),),
    )


def _review_sentence(conn, case_id: str) -> Optional[Sentence]:
    status = get_review_status(conn, case_id)
    if status.review_status is None or status.state_id is None:
        return None
    refs = [SourceRef(KIND_STATE, str(status.state_id))]
    if status.latest_review_id is not None:
        refs.append(SourceRef(KIND_REVIEW, str(status.latest_review_id)))
    if status.review_status == UNVERIFIED:
        text = (f"Interpretation changed {status.labels_changed} label(s) in its current state and nobody has "
                "reviewed that state yet, so it is unverified and waits in the review queue.")
    elif status.latest_review_id is not None:
        text = (f"A reviewer has reviewed its current state ({words(status.latest_review_action)}), so its "
                f"review status is {words(status.review_status)}.")
    else:
        text = f"Its current state needs no review: its review status is {words(status.review_status)}."
    return Sentence(text, tuple(refs))


def _outcome_sentences(diff: CaseDiff) -> list[Sentence]:
    before, after = diff.before, diff.after
    if diff.outcome == OUTCOME_NO_STATE:
        return [Sentence("This case has no published state yet, so there is nothing to explain.",
                         (SourceRef(KIND_CASE, diff.case_id),))]
    if diff.outcome == OUTCOME_FIRST_STATE:
        return [Sentence(
            f"This case has one published state, {words(after.state_code)} in release {after.release_id}; "
            "there is no earlier state to compare it with.",
            (_state_ref(after), SourceRef(KIND_RELEASE, after.release_id)),
        )]
    if diff.outcome == OUTCOME_STATE_CHANGED:
        sentences = [Sentence(
            f"Release {after.release_id} changed this case from {words(before.state_code)} "
            f"(release {before.release_id}) to {words(after.state_code)}.",
            (_state_ref(before), _state_ref(after)),
        )]
        for change in diff.state_changes:
            if change.field == "state_code":
                continue
            sentences.append(Sentence(
                f"Its {words(change.field)} moved from {words(change.before)} to {words(change.after)}.",
                (_state_ref(before), _state_ref(after)),
            ))
        return sentences
    if diff.outcome == OUTCOME_RE_VERIFIED:
        return [Sentence(
            f"Release {after.release_id} evaluated this case again and kept the same conclusion, "
            f"{words(after.state_code)}.",
            (_state_ref(before), _state_ref(after)),
        )]
    return [Sentence(
        f"No change has touched this case since release {after.release_id}; it is still {words(after.state_code)}.",
        (_state_ref(after), SourceRef(KIND_RELEASE, after.release_id)),
    )]


def _version_sentences(diff: CaseDiff) -> list[Sentence]:
    if not (diff.before and diff.after) or diff.before.state_id == diff.after.state_id:
        return []
    refs = (SourceRef(KIND_RELEASE, diff.before.release_id), SourceRef(KIND_RELEASE, diff.after.release_id))
    return [Sentence(f"The {words(v.name)} moved from {verbatim(v.before)} to {verbatim(v.after)}.", refs)
            for v in diff.version_changes]


def summary_from_diff(conn, diff: CaseDiff) -> CopilotSummary:
    sentences = _outcome_sentences(diff)
    if diff.triggered_by_change_id:
        change = _change_sentence(conn, diff.triggered_by_change_id)
        if change is not None:
            sentences.append(change)
    if diff.before and diff.after and diff.before.state_id != diff.after.state_id:
        sentences += _version_sentences(diff)
        details = _evidence_sentences(conn, diff) + _rule_sentences(diff)
        sentences += details or [Sentence(
            "No evidence row or rule edge was added or removed; only version labels moved.",
            (_state_ref(diff.after),),
        )]
    if diff.after:
        sentences += _label_sentences(conn, diff)
        review = _review_sentence(conn, diff.case_id)
        if review is not None:
            sentences.append(review)
    return CopilotSummary(
        case_id=diff.case_id,
        before_state_id=diff.before.state_id if diff.before else None,
        after_state_id=diff.after.state_id if diff.after else None,
        outcome=diff.outcome,
        sentences=tuple(sentences),
    )


def build_summary(
    conn, case_id: str, *, before_release: Optional[str] = None, after_release: Optional[str] = None
) -> CopilotSummary:
    """The template summary for one case: by default its current published state against the one before it."""
    return summary_from_diff(conn, case_diff(conn, case_id, before_release=before_release,
                                             after_release=after_release))
