"""The publication rule (task I-21; review findings AMR-001/021): one guard at the one place a release is published.

A release written by a change (it names the change in triggered_by_change_id) holds the selective result for the
cases the change selected. It is trusted only once the exhaustive comparison has passed for it (rule 5). So every
route that can publish such a release (the API run route, the reevaluate_change command, a direct engine call, the
gate) ends in publish_release, and publish_release asks this module first:

    check_publication(conn, release_id)    raises PublicationRefused unless a passing comparison of the release by
                                           its own change is stored in equivalence_report

Missing, mismatched (stored for another release or by another change) and failed comparisons are all refused. A
release that no change wrote (a baseline, or a full release that evaluated every case) is not a selective result and is
not checked here. This module only reads; it never publishes.
"""

from __future__ import annotations

from .errors import PublicationRefused, ReleaseNotFound


def check_publication(conn, release_id: str) -> None:
    """Raise PublicationRefused unless the release may be published under the publication rule."""
    row = conn.execute(
        "SELECT triggered_by_change_id FROM release WHERE release_id = %s", (release_id,)
    ).fetchone()
    if row is None:
        raise ReleaseNotFound(f"release {release_id!r} does not exist")
    change_id = row[0]
    if change_id is None:
        return
    reports = conn.execute(
        "SELECT report_id, passed FROM equivalence_report WHERE release_id = %s AND change_id = %s "
        "ORDER BY report_id DESC",
        (release_id, change_id),
    ).fetchall()
    if not reports:
        raise PublicationRefused(
            f"release {release_id!r} holds the selective result of change {change_id!r} and has no stored exhaustive "
            "comparison; it stays a DRAFT until the comparison passes (compare_change --gate, or a run with "
            "run_exhaustive and gate)"
        )
    report_id, passed = reports[0]
    if not passed:
        raise PublicationRefused(
            f"release {release_id!r}: the latest stored comparison for change {change_id!r} (report {report_id}) "
            "failed, so it cannot be published"
        )
