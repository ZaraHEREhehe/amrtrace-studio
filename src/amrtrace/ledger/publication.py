"""The publication rule (tasks I-21, I-23 and I-27; review findings AMR-001/012/021): one guard where a release is
published.

A release written by a change (it names the change in triggered_by_change_id) holds the selective result for the
cases the change selected. Since the supervisor decision of 17 Nov 2026 (I-27) it may be published at one of two
verification levels, and the level is recorded on the release when it is published (migration 0017):

    SELECTIVE    a selective run alone: the COMPLETE selective run of this change wrote this release, and no stored
                 comparison of it failed. The release is "selectively verified" and never shown as fully checked.
    EXHAUSTIVE   the optional, Admin-only exhaustive comparison passed before publishing (the gate, rule 5)

Every route that can publish such a release (the API run route, the reevaluate_change command, a direct engine call,
the gate) ends in publish_release, and publish_release asks this module first:

    check_publication(conn, release_id, level)   raises PublicationRefused unless the release may be published at
                                                 that level

For EXHAUSTIVE the latest comparison stored for the release by its own change must have passed and still be "bound"
to it (I-23), read from the database and not from any report object a caller holds:

    * its selective run is the COMPLETE selective run of this change that wrote this release
    * its exhaustive run is a COMPLETE exhaustive run of this change against this release
    * the release still looks as it did when it was compared (release_binding: its states, dependency and
      applicability rows, and the published releases it was compared against), so a comparison is never reused for
      a release that changed afterwards
    * the versions the comparison evaluated under agree with the release's own version vector

Missing, mismatched (stored for another release, by another change, or naming the wrong runs), stale and failed
comparisons are all refused. A release that no change wrote (a baseline, or a full release that evaluated every case)
is not a selective result and is not checked here.

An Admin may also compare a SELECTIVE release after it is published (an audit, reeval.audit_release). The audit is a
stored equivalence_report row and never changes the release; a failed audit is listed by failed_audits and shown in
the review queue. release_verification reads the level and the latest audit for display. This module only reads; it
never publishes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import PublicationRefused, ReleaseNotFound

LEVEL_SELECTIVE = "SELECTIVE"
LEVEL_EXHAUSTIVE = "EXHAUSTIVE"
VERIFICATION_LEVELS = (LEVEL_SELECTIVE, LEVEL_EXHAUSTIVE)

# the keys release_binding returns; a stored binding is compared on exactly these
BINDING_KEYS = ("states", "last_state_id", "dependency_rows", "applicability_rows", "compared_against")


def release_binding(conn, release_id: str) -> dict[str, Any]:
    """What a comparison of this release saw: stored with the report, and checked again before publishing.

    compared_against lists the published releases older than this one, which are the states the comparison read as
    "before the change"; if one more of them is published later, the comparison no longer describes this release.
    """
    row = conn.execute("SELECT release_seq FROM release WHERE release_id = %s", (release_id,)).fetchone()
    if row is None:
        raise ReleaseNotFound(f"release {release_id!r} does not exist")
    seq = row[0]
    states, last_state_id = conn.execute(
        "SELECT count(*), coalesce(max(state_id), 0) FROM case_state WHERE release_id = %s", (release_id,)
    ).fetchone()
    dependency_rows = conn.execute("SELECT count(*) FROM dependency WHERE release_id = %s", (release_id,)).fetchone()[0]
    applicability_rows = conn.execute(
        "SELECT count(*) FROM applicability WHERE release_id = %s", (release_id,)
    ).fetchone()[0]
    compared_against = [
        r[0] for r in conn.execute(
            "SELECT release_id FROM release WHERE status = 'PUBLISHED' AND release_seq < %s ORDER BY release_seq",
            (seq,),
        )
    ]
    return {
        "states": states,
        "last_state_id": last_state_id,
        "dependency_rows": dependency_rows,
        "applicability_rows": applicability_rows,
        "compared_against": compared_against,
    }


def check_publication(conn, release_id: str, level: str = LEVEL_EXHAUSTIVE) -> None:
    """Raise PublicationRefused unless the release may be published at `level` under the publication rule."""
    if level not in VERIFICATION_LEVELS:
        raise ValueError(f"unknown verification level {level!r}; use one of {VERIFICATION_LEVELS}")
    row = conn.execute(
        "SELECT triggered_by_change_id, version_vector FROM release WHERE release_id = %s", (release_id,)
    ).fetchone()
    if row is None:
        raise ReleaseNotFound(f"release {release_id!r} does not exist")
    change_id, version_vector = row
    if change_id is None:
        return
    if level == LEVEL_SELECTIVE:
        _check_selective(conn, release_id, change_id)
        return
    report = conn.execute(
        "SELECT report_id, passed, selective_run_id, exhaustive_run_id, report -> 'binding' FROM equivalence_report "
        "WHERE release_id = %s AND change_id = %s ORDER BY report_id DESC LIMIT 1",
        (release_id, change_id),
    ).fetchone()
    if report is None:
        raise PublicationRefused(
            f"release {release_id!r} holds the selective result of change {change_id!r} and has no stored exhaustive "
            "comparison, so it cannot be published as EXHAUSTIVE (compare_change --gate, or a run with run_exhaustive "
            "and gate); a selective run alone publishes it as SELECTIVE"
        )
    report_id, passed, selective_run_id, exhaustive_run_id, binding = report
    if not passed:
        raise PublicationRefused(
            f"release {release_id!r}: the latest stored comparison for change {change_id!r} (report {report_id}) "
            "failed, so it cannot be published"
        )
    problem = (
        _run_problem(conn, selective_run_id, "SELECTIVE", change_id, release_id)
        or _run_problem(conn, exhaustive_run_id, "EXHAUSTIVE", change_id, release_id)
        or _binding_problem(conn, release_id, binding, version_vector)
    )
    if problem:
        raise PublicationRefused(
            f"release {release_id!r}: the stored comparison for change {change_id!r} (report {report_id}) is not "
            f"bound to it: {problem}"
        )


def _check_selective(conn, release_id: str, change_id: str) -> None:
    """SELECTIVE: the COMPLETE selective run of the change wrote this release, and no stored comparison of it failed."""
    run = conn.execute(
        "SELECT run_id FROM reeval_run WHERE change_id = %s AND mode = 'SELECTIVE' AND status = 'COMPLETE' "
        "AND release_id = %s",
        (change_id, release_id),
    ).fetchone()
    if run is None:
        raise PublicationRefused(
            f"release {release_id!r}: no COMPLETE selective run of change {change_id!r} wrote it, so it cannot be "
            "published as SELECTIVE"
        )
    latest = conn.execute(
        "SELECT report_id, passed FROM equivalence_report WHERE release_id = %s AND change_id = %s "
        "ORDER BY report_id DESC LIMIT 1",
        (release_id, change_id),
    ).fetchone()
    if latest is not None and not latest[1]:
        raise PublicationRefused(
            f"release {release_id!r}: the stored comparison for change {change_id!r} (report {latest[0]}) failed, so "
            "it cannot be published at any level"
        )


def _run_problem(conn, run_id: str, mode: str, change_id: str, release_id: str) -> str | None:
    row = conn.execute(
        "SELECT mode, status, change_id, release_id FROM reeval_run WHERE run_id = %s", (run_id,)
    ).fetchone()
    if row is None:
        return f"its {mode.lower()} run {run_id!r} does not exist"
    if tuple(row) != (mode, "COMPLETE", change_id, release_id):
        found_mode, status, found_change, found_release = row
        return (
            f"its {mode.lower()} run {run_id!r} is a {status} {found_mode} run of change {found_change!r} "
            f"for release {found_release!r}"
        )
    return None


def _binding_problem(conn, release_id: str, binding: Mapping | None, version_vector: Mapping) -> str | None:
    if not binding:
        return "it was stored without the release it compared (before I-23); compare the change again"
    current = release_binding(conn, release_id)
    changed = [key for key in BINDING_KEYS if binding.get(key) != current[key]]
    if changed:
        return f"the release changed after it was compared ({', '.join(changed)})"
    versions = binding.get("versions") or {}
    differing = sorted(k for k, v in (version_vector or {}).items() if k in versions and versions[k] != v)
    if differing:
        return f"it evaluated under other versions than the release records ({', '.join(differing)})"
    return None


# ---------- reading the level and the audits (I-27) ----------

@dataclass(frozen=True)
class ReleaseVerification:
    """How a release was verified, for display. Only reads; an audit never changes the release."""

    release_id: str
    change_id: str | None
    status: str
    # SELECTIVE or EXHAUSTIVE once published; None for a release no change wrote, or one published before I-27
    verification_level: str | None
    audit_report_id: int | None              # the latest Admin audit of the published release, if any
    audit_passed: bool | None
    audit_exhaustive_run_id: str | None

    @property
    def label(self) -> str:
        return verification_label(self.change_id, self.status, self.verification_level)


def verification_label(change_id: str | None, status: str, level: str | None) -> str:
    """The words shown for a release: a SELECTIVE release is never shown as fully checked."""
    if change_id is None:
        return "not a change release"
    if status != "PUBLISHED":
        return "not published"
    if level == LEVEL_SELECTIVE:
        return "selectively verified"
    if level == LEVEL_EXHAUSTIVE:
        return "exhaustively verified"
    return "verification level not recorded (published before I-27)"


_AUDITS = """
SELECT er.report_id, er.release_id, er.change_id, er.exhaustive_run_id, er.passed, er.created_at, er.report
FROM equivalence_report er
JOIN release r ON r.release_id = er.release_id AND r.triggered_by_change_id = er.change_id
WHERE r.status = 'PUBLISHED' AND (er.report ->> 'audit') = 'true'
"""


def release_verification(conn, release_id: str) -> ReleaseVerification:
    row = conn.execute(
        "SELECT triggered_by_change_id, status, verification_level FROM release WHERE release_id = %s", (release_id,)
    ).fetchone()
    if row is None:
        raise ReleaseNotFound(f"release {release_id!r} does not exist")
    change_id, status, level = row
    audit = conn.execute(
        _AUDITS + " AND er.release_id = %s ORDER BY er.report_id DESC LIMIT 1", (release_id,)
    ).fetchone()
    return ReleaseVerification(
        release_id=release_id,
        change_id=change_id,
        status=status,
        verification_level=level,
        audit_report_id=None if audit is None else audit[0],
        audit_passed=None if audit is None else audit[4],
        audit_exhaustive_run_id=None if audit is None else audit[3],
    )


@dataclass(frozen=True)
class FailedAudit:
    """A published release whose latest Admin audit failed. Raised in the review queue; history is not rewritten."""

    release_id: str
    change_id: str
    report_id: int
    exhaustive_run_id: str
    created_at: Any
    mismatched_cases: int                    # cases that differ on any axis
    case_ids: tuple[str, ...]                # the first of them (the report stores up to a fixed number)


def failed_audits(conn) -> list[FailedAudit]:
    """Every published release whose latest audit failed, newest release first."""
    rows = conn.execute(
        "SELECT DISTINCT ON (a.release_id) a.* FROM (" + _AUDITS + ") a "
        "ORDER BY a.release_id, a.report_id DESC"
    ).fetchall()
    found = []
    for report_id, release_id, change_id, exhaustive_run_id, passed, created_at, body in rows:
        if passed:
            continue
        body = body or {}
        case_ids = tuple(body.get("mismatched_case_ids") or ())
        found.append(FailedAudit(
            release_id=release_id,
            change_id=change_id,
            report_id=report_id,
            exhaustive_run_id=exhaustive_run_id,
            created_at=created_at,
            mismatched_cases=int(body.get("mismatched_cases") or len(case_ids)),
            case_ids=case_ids,
        ))
    return sorted(found, key=lambda a: a.report_id, reverse=True)
