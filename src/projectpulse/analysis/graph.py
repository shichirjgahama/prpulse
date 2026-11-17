"""Граф зависимостей: Тарьян, топологическая сортировка, диффы срезов."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from projectpulse.analysis.imports import ModuleIndex
from projectpulse.analysis.parser import EntityRecord, RefRecord, module_entity_id


@dataclass
class GraphNode:
    node_id: str
    kind: str
    name: str
    path: str | None = None
    loc: int = 0
    complexity: int = 0
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "loc": self.loc,
            "complexity": self.complexity,
        }


@dataclass(frozen=True)
class GraphEdge:
    src: str
    dst: str
    kind: str
    weight: int = 1


class DependencyGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self._edges: dict[tuple[str, str, str], int] = {}
        self._out: dict[str, set[str]] = defaultdict(set)
        self._in: dict[str, set[str]] = defaultdict(set)

    def add_node(self, node: GraphNode) -> None:
        existing = self.nodes.get(node.node_id)
        if existing is None:
            self.nodes[node.node_id] = node
        else:
            existing.loc = max(existing.loc, node.loc)
            existing.complexity = max(existing.complexity, node.complexity)

    def add_edge(self, src: str, dst: str, kind: str, weight: int = 1) -> None:
        if src == dst:
            return
        if src not in self.nodes or dst not in self.nodes:
            return
        key = (src, dst, kind)
        self._edges[key] = self._edges.get(key, 0) + max(1, weight)
        self._out[src].add(dst)
        self._in[dst].add(src)

    @property
    def edges(self) -> list[GraphEdge]:
        return [
            GraphEdge(src=src, dst=dst, kind=kind, weight=weight)
            for (src, dst, kind), weight in sorted(self._edges.items())
        ]

    def edge_weight(self, src: str, dst: str, kind: str) -> int:
        return self._edges.get((src, dst, kind), 0)

    def out_neighbors(self, node_id: str) -> list[str]:
        return sorted(self._out.get(node_id, set()))

    def in_neighbors(self, node_id: str) -> list[str]:
        return sorted(self._in.get(node_id, set()))

    def fan_out(self, node_id: str) -> int:
        return len(self._out.get(node_id, set()))

    def fan_in(self, node_id: str) -> int:
        return len(self._in.get(node_id, set()))

    def node_count(self) -> int:
        return len(self.nodes)

    def edge_count(self) -> int:
        return len(self._edges)

    # ------------------------------------------------------------ алгоритмы
    def tarjan_scc(self) -> list[list[str]]:
        """Итеративный Тарьян, без рекурсии (большие графы безопасны)."""
        index = 0
        indices: dict[str, int] = {}
        low: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        components: list[list[str]] = []
        adjacency = {node: self.out_neighbors(node) for node in self.nodes}

        for start in sorted(self.nodes):
            if start in indices:
                continue
            indices[start] = low[start] = index
            index += 1
            stack.append(start)
            on_stack.add(start)
            work: list[tuple[str, int]] = [(start, 0)]

            while work:
                node, position = work[-1]
                neighbours = adjacency[node]
                if position < len(neighbours):
                    neighbour = neighbours[position]
                    work[-1] = (node, position + 1)
                    if neighbour not in indices:
                        indices[neighbour] = low[neighbour] = index
                        index += 1
                        stack.append(neighbour)
                        on_stack.add(neighbour)
                        work.append((neighbour, 0))
                    elif neighbour in on_stack:
                        low[node] = min(low[node], indices[neighbour])
                    continue

                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == indices[node]:
                    component: list[str] = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    components.append(sorted(component))
        return sorted(components, key=lambda c: (c[0], len(c)))

    def cycles(self) -> list[list[str]]:
        result: list[list[str]] = []
        for component in self.tarjan_scc():
            if len(component) > 1:
                result.append(component)
            elif component and component[0] in self._out.get(component[0], set()):
                result.append(component)
        return result

    def has_cycle(self) -> bool:
        return bool(self.cycles())

    def topological_order(self, raise_on_cycle: bool = False) -> list[str]:
        # Учитываем уникальных предшественников, а не число типов связей:
        # между одной парой узлов может быть и call, и compose.
        indegree = {node: len(self._in.get(node, ())) for node in self.nodes}
        ready = sorted(node for node, degree in indegree.items() if degree == 0)
        order: list[str] = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            for neighbour in self.out_neighbors(node):
                indegree[neighbour] -= 1
                if indegree[neighbour] == 0:
                    ready.append(neighbour)
            ready.sort()
        if len(order) != len(self.nodes):
            if raise_on_cycle:
                raise ValueError("Граф содержит циклы, топологическая сортировка невозможна")
            remaining = sorted(node for node in self.nodes if node not in order)
            order.extend(remaining)
        return order

    def metrics(self) -> dict:
        cycles = self.cycles()
        return {
            "nodes": self.node_count(),
            "edges": self.edge_count(),
            "cycles": len(cycles),
            "cycle_nodes": sum(len(c) for c in cycles),
            "max_fan_in": max((self.fan_in(n) for n in self.nodes), default=0),
            "max_fan_out": max((self.fan_out(n) for n in self.nodes), default=0),
        }

    def degree_map(self) -> dict[str, int]:
        return {node: self.fan_in(node) + self.fan_out(node) for node in self.nodes}


def build_file_graph(files: Sequence[dict], imports: Sequence[dict]) -> DependencyGraph:
    graph = DependencyGraph()
    for file in files:
        path = file["path"].replace("\\", "/")
        graph.add_node(
            GraphNode(
                node_id=path,
                kind="file",
                name=path,
                path=path,
                loc=int(file.get("loc", 0)),
                complexity=int(file.get("complexity_total", 0)),
            )
        )
    index = ModuleIndex(graph.nodes)
    resolved = index.resolve_all(list(imports))
    for item in resolved:
        graph.add_edge(item.source, item.target, "import", 1)
    return graph


def build_entity_graph(
    files: Sequence[dict],
    entities: Sequence[EntityRecord | dict],
    refs: Sequence[RefRecord | dict],
) -> DependencyGraph:
    graph = DependencyGraph()
    file_loc = {f["path"].replace("\\", "/"): int(f.get("loc", 0)) for f in files}
    file_complexity = {f["path"].replace("\\", "/"): int(f.get("complexity_total", 0)) for f in files}

    entity_rows: list[dict] = []
    for entity in entities:
        row = entity.as_dict() if isinstance(entity, EntityRecord) else dict(entity)
        entity_rows.append(row)

    for path in sorted(file_loc):
        graph.add_node(
            GraphNode(
                node_id=module_entity_id(path),
                kind="module",
                name=path,
                path=path,
                loc=file_loc[path],
                complexity=file_complexity.get(path, 0),
            )
        )

    by_name: dict[str, list[dict]] = defaultdict(list)
    by_qualname: dict[str, list[dict]] = defaultdict(list)
    by_id: dict[str, dict] = {}
    for row in sorted(entity_rows, key=lambda r: (r["path"], r["qualname"], r["entity_id"])):
        by_id[row["entity_id"]] = row
        by_name[row["name"]].append(row)
        by_qualname[row["qualname"]].append(row)
        graph.add_node(
            GraphNode(
                node_id=row["entity_id"],
                kind=row["kind"],
                name=row["name"],
                path=row["path"],
                loc=max(1, int(row.get("end_lineno", 0)) - int(row.get("lineno", 0)) + 1),
                complexity=int(row.get("complexity", 1)),
            )
        )

    def resolve_ref(ref: dict) -> dict | None:
        target = ref["target"]
        kind = ref["kind"]
        source = by_id.get(ref["src_id"])
        source_path = ref["path"]
        candidates = by_name.get(target, [])
        if kind == "inherit":
            candidates = [c for c in candidates if c["kind"] == "class"]
        if not candidates:
            return None
        same_path = [c for c in candidates if c["path"] == source_path]
        if same_path:
            candidates = same_path
        elif source and source.get("parent_id"):
            parent = by_id.get(source["parent_id"])
            if parent:
                siblings = [
                    c for c in candidates if c.get("parent_id") == parent["entity_id"] and c["kind"] == "class"
                ]
                if siblings:
                    candidates = siblings
        if len(candidates) > 1:
            unique = [c for c in candidates if c["name"] == target and c["qualname"] == target]
            if unique:
                candidates = unique
        return sorted(candidates, key=lambda c: (c["path"], c["qualname"]))[0]

    for ref_obj in refs:
        ref = ref_obj.as_dict() if isinstance(ref_obj, RefRecord) else dict(ref_obj)
        if ref["src_id"] not in by_id:
            continue
        target = resolve_ref(ref)
        if not target:
            continue
        graph.add_edge(ref["src_id"], target["entity_id"], ref["kind"], 1)
    return graph


def graph_diff(old: DependencyGraph, new: DependencyGraph) -> dict:
    old_nodes = set(old.nodes)
    new_nodes = set(new.nodes)
    added_nodes = sorted(new_nodes - old_nodes)
    removed_nodes = sorted(old_nodes - new_nodes)
    common = old_nodes & new_nodes
    changed_nodes = sorted(
        node_id
        for node_id in common
        if (
            old.nodes[node_id].loc,
            old.nodes[node_id].complexity,
            old.nodes[node_id].kind,
        )
        != (
            new.nodes[node_id].loc,
            new.nodes[node_id].complexity,
            new.nodes[node_id].kind,
        )
    )
    old_edges = {(e.src, e.dst, e.kind): e.weight for e in old.edges}
    new_edges = {(e.src, e.dst, e.kind): e.weight for e in new.edges}
    added_edges = sorted(set(new_edges) - set(old_edges))
    removed_edges = sorted(set(old_edges) - set(new_edges))
    changed_edges = sorted(
        key for key in set(old_edges) & set(new_edges) if old_edges[key] != new_edges[key]
    )
    return {
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "changed_nodes": changed_nodes,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
        "changed_edges": changed_edges,
        "counts": {
            "added_nodes": len(added_nodes),
            "removed_nodes": len(removed_nodes),
            "changed_nodes": len(changed_nodes),
            "added_edges": len(added_edges),
            "removed_edges": len(removed_edges),
            "changed_edges": len(changed_edges),
        },
    }
