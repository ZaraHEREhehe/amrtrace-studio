# dependency subgraph of one case: the typed nodes and edges behind its state, for the dossier and the graph view
from dataclasses import asdict, dataclass

from psycopg.rows import dict_row

NODE_CASE = "case"


# one thing the case depends on, or the case itself
@dataclass(frozen=True)
class GraphNode:
    key: str
    node_type: str
    node_id: str
    node_version: str | None


# one stored dependency, always from the case to the node it depends on
@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    dep_type: str
    edge_type: str
    # where the case sits on the node, such as a measured value on a rule
    node_context: dict | None


# one entry of the rule space the case was evaluated against
@dataclass(frozen=True)
class RuleSpaceEntry:
    determinant_identity: str
    candidate_antibiotic: str
    organism: str | None
    evidence_type: str | None
    rule_set_version: str | None


@dataclass(frozen=True)
class CaseSubgraph:
    case_id: str
    release_id: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    rule_space: tuple[RuleSpaceEntry, ...]

    # plain data, ready to be sent as JSON
    def to_dict(self) -> dict:
        return asdict(self)


# two edges to the same node under the same version share one node in the picture
def node_key(node_type: str, node_id: str, node_version: str | None) -> str:
    return f"{node_type}|{node_id}|{node_version or ''}"


def _edge_order(edge: GraphEdge) -> tuple:
    return (edge.target, edge.dep_type, edge.edge_type, repr(edge.node_context))


def _entry_order(entry: RuleSpaceEntry) -> tuple:
    return tuple(str(value or "") for value in asdict(entry).values())


# pure part: turns stored rows into a graph, in a fixed order whatever order the rows arrive in
def build_subgraph(
    case_id: str, release_id: str, edge_rows: list[dict], rule_space_rows: list[dict]
) -> CaseSubgraph:
    case_node = GraphNode(
        key=node_key(NODE_CASE, case_id, None),
        node_type=NODE_CASE,
        node_id=case_id,
        node_version=None,
    )
    nodes = {case_node.key: case_node}
    edges = set()
    for row in edge_rows:
        key = node_key(row["node_type"], row["node_id"], row["node_version"])
        nodes.setdefault(
            key,
            GraphNode(
                key=key,
                node_type=row["node_type"],
                node_id=row["node_id"],
                node_version=row["node_version"],
            ),
        )
        edges.add(
            _FrozenEdge(
                source=case_node.key,
                target=key,
                dep_type=row["dep_type"],
                edge_type=row["edge_type"],
                context_items=_freeze(row["node_context"]),
            )
        )

    ordered_edges = sorted(
        (
            GraphEdge(
                source=edge.source,
                target=edge.target,
                dep_type=edge.dep_type,
                edge_type=edge.edge_type,
                node_context=_thaw(edge.context_items),
            )
            for edge in edges
        ),
        key=_edge_order,
    )
    entries = {
        RuleSpaceEntry(
            determinant_identity=row["determinant_identity"],
            candidate_antibiotic=row["candidate_antibiotic"],
            organism=row["organism"],
            evidence_type=row["evidence_type"],
            rule_set_version=row["rule_set_version"],
        )
        for row in rule_space_rows
    }
    # the case comes first, then the nodes it depends on in a fixed order
    other_nodes = sorted(
        (node for key, node in nodes.items() if key != case_node.key),
        key=lambda node: (node.node_type, node.node_id, node.node_version or ""),
    )
    return CaseSubgraph(
        case_id=case_id,
        release_id=release_id,
        nodes=(case_node, *other_nodes),
        edges=tuple(ordered_edges),
        rule_space=tuple(sorted(entries, key=_entry_order)),
    )


# an edge in a form that can sit in a set, so a row stored twice is drawn once
@dataclass(frozen=True)
class _FrozenEdge:
    source: str
    target: str
    dep_type: str
    edge_type: str
    context_items: tuple | None


def _freeze(context: dict | None) -> tuple | None:
    if context is None:
        return None
    return tuple(
        sorted((str(name), repr(value), value) for name, value in context.items())
    )


def _thaw(items: tuple | None) -> dict | None:
    if items is None:
        return None
    return {name: value for name, _, value in items}


# the newest published release that holds stored rows for the case, the same rule the selector uses
def _current_release(cursor, case_id: str) -> str | None:
    cursor.execute(
        "SELECT s.release_id FROM ("
        "  SELECT release_id FROM dependency WHERE case_id = %s "
        "  UNION "
        "  SELECT release_id FROM applicability WHERE case_id = %s"
        ") s JOIN release r ON r.release_id = s.release_id "
        "WHERE r.status = 'PUBLISHED' ORDER BY r.release_seq DESC LIMIT 1",
        (case_id, case_id),
    )
    row = cursor.fetchone()
    return None if row is None else row["release_id"]


def case_subgraph(conn, case_id: str, release_id: str | None = None) -> CaseSubgraph:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute('SELECT 1 FROM "case" WHERE case_id = %s', (case_id,))
        if cursor.fetchone() is None:
            raise LookupError(f"case {case_id} does not exist")

        # by default the picture shows what the case depends on now
        if release_id is None:
            release_id = _current_release(cursor, case_id)
            if release_id is None:
                raise LookupError(f"case {case_id} has no stored dependencies")

        cursor.execute(
            "SELECT dep_type, edge_type, node_type, node_id, node_version, node_context "
            "FROM dependency WHERE case_id = %s AND release_id = %s",
            (case_id, release_id),
        )
        edge_rows = cursor.fetchall()
        cursor.execute(
            "SELECT determinant_identity, candidate_antibiotic, organism, evidence_type, rule_set_version "
            "FROM applicability WHERE case_id = %s AND release_id = %s",
            (case_id, release_id),
        )
        rule_space_rows = cursor.fetchall()

    if not edge_rows and not rule_space_rows:
        raise LookupError(
            f"case {case_id} has no stored dependencies in release {release_id}"
        )
    return build_subgraph(case_id, release_id, edge_rows, rule_space_rows)
