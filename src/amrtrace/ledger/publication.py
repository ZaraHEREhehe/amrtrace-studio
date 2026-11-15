"""The publication rule (tasks I-21 and I-23; review findings AMR-001/012/021): one guard where a release is published.

A release written by a change (it names the change in triggered_by_change_id) holds the selective result for the
cases the change selected. It is trusted only once the exhaustive comparison has passed for it (rule 5). So every
route that can publish such a release (the API run route, the reevaluate_change command, a direct engine call, the
gate) ends in publish_release, and publish_release asks this module first:

    check_publication(conn, release_id)    raises PublicationRefused unless the latest comparison stored for the
                                           release by its own change passed and is still bound to it

"Bound" (I-23) means the stored report belongs to what is being published, read from the database and not from any
report object a caller holds:

    * its selective run is the COMPLETE selective run of this change that wrote this release
    * its exhaustive run is a COMPLETE exhaustive run of this change against this release
    * the release still looks as it did when it was compared (release_binding: its states, dependency and
      applicability rows, and the published releases it was compared against), so a comparison is never reused for
      a release that changed afterwards
    * the versions the comparison evaluated under agree with the release's own version vector

Missing, mismatched (stored for another release, by another change, or naming the wrong runs), stale and failed
comparisons are all refused. A release that no change wrote (a baseline, or a full release that evaluated every case)
is not a selective result and is not checked here. This module only reads; it never publishes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import PublicationRefused, ReleaseNotFound

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


def check_publication(conn, release_id: str) -> None:
    """Raise PublicationRefused unless the release may be published under the publication rule."""
    row = conn.execute(
        "SELECT triggered_by_change_id, version_vector FROM release WHERE release_id = %s", (release_id,)
    ).fetchone()
    if row is None:
        raise ReleaseNotFound(f"release {release_id!r} does not exist")
    change_id, version_vector = row
    if change_id is None:
        return
    report = conn.execute(
        "SELECT report_id, passed, selective_run_id, exhaustive_run_id, report -> 'binding' FROM equivalence_report "
        "WHERE release_id = %s AND change_id = %s ORDER BY report_id DESC LIMIT 1",
        (release_id, change_id),
    ).fetchone()
    if report is None:
        raise PublicationRefused(
            f"release {release_id!r} holds the selective result of change {change_id!r} and has no stored exhaustive "
            "comparison; it stays a DRAFT until the comparison passes (compare_change --gate, or a run with "
            "run_exhaustive and gate)"
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
