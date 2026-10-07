# version matching in the selector: which stored edges a change to a node can reach
import pytest

from amrtrace.deps.selector import edge_version_matches


@pytest.mark.parametrize(
    "node_version, old_version, expected",
    [
        # the edge was recorded under the version that is being replaced
        ("TABLE_V1", "TABLE_V1", True),
        # the edge belongs to another version of the node, so this change does not reach it
        ("TABLE_V0", "TABLE_V1", False),
        # an edge that names no version is always kept
        (None, "TABLE_V1", True),
        # a node introduced by the change: the case that looked for it and found nothing is kept
        ("TABLE_V1", None, True),
        (None, None, True),
    ],
)
def test_edge_version_matches(node_version, old_version, expected):
    assert edge_version_matches(node_version, old_version) is expected
