"""Тесты разрешения импортов и построения графов."""

from __future__ import annotations

import unittest

from projectpulse.analysis.graph import (
    DependencyGraph,
    GraphNode,
    build_entity_graph,
    build_file_graph,
    graph_diff,
)
from projectpulse.analysis.imports import ModuleIndex, module_names
from projectpulse.analysis.parser import ImportRecord, analyze_source


class ImportTests(unittest.TestCase):
    def test_module_names(self) -> None:
        self.assertEqual(module_names("pkg/__init__.py"), {"pkg"})
        self.assertEqual(module_names("pkg/mod.py"), {"pkg.mod"})
        self.assertEqual(module_names("src/pkg/mod.py"), {"src.pkg.mod", "pkg.mod"})
        self.assertEqual(module_names("README.md"), {"README.md"})

    def test_relative_and_absolute_imports(self) -> None:
        index = ModuleIndex(["pkg/__init__.py", "pkg/core.py", "pkg/util.py"])
        relative = index.resolve(ImportRecord(path="pkg/__init__.py", module="core", level=1, names="add"))
        self.assertEqual(relative, ["pkg/core.py"])
        absolute = index.resolve(ImportRecord(path="pkg/util.py", module="pkg.core", level=0, names="add"))
        self.assertEqual(absolute, ["pkg/core.py"])
        missing = index.resolve(ImportRecord(path="pkg/util.py", module="pkg.nope", level=0, names=None))
        self.assertEqual(missing, [])

    def test_src_layout(self) -> None:
        index = ModuleIndex(["src/pkg/core.py", "src/pkg/util.py"])
        resolved = index.resolve(
            ImportRecord(path="src/pkg/util.py", module="pkg.core", level=0, names=None)
        )
        self.assertEqual(resolved, ["src/pkg/core.py"])


class GraphTests(unittest.TestCase):
    def _graph(self) -> DependencyGraph:
        graph = DependencyGraph()
        for node_id in ("a", "b", "c", "d"):
            graph.add_node(GraphNode(node_id=node_id, kind="file", name=node_id))
        graph.add_edge("a", "b", "import")
        graph.add_edge("b", "a", "import")
        graph.add_edge("b", "c", "import")
        return graph

    def test_cycles_and_topological_order(self) -> None:
        graph = self._graph()
        self.assertEqual(graph.cycles(), [["a", "b"]])
        self.assertTrue(graph.has_cycle())
        order = graph.topological_order()
        self.assertEqual(len(order), 4)
        self.assertLess(order.index("b"), order.index("c"))
        with self.assertRaises(ValueError):
            graph.topological_order(raise_on_cycle=True)

    def test_parallel_edge_kinds_do_not_fake_cycle(self) -> None:
        graph = DependencyGraph()
        for node_id in ("x", "y"):
            graph.add_node(GraphNode(node_id=node_id, kind="function", name=node_id))
        graph.add_edge("x", "y", "call")
        graph.add_edge("x", "y", "compose")
        self.assertEqual(graph.cycles(), [])
        self.assertEqual(graph.topological_order(), ["x", "y"])
        self.assertEqual(graph.edge_count(), 2)

    def test_degrees_and_metrics(self) -> None:
        graph = self._graph()
        self.assertEqual(graph.fan_in("b"), 1)
        self.assertEqual(graph.fan_out("b"), 2)
        metrics = graph.metrics()
        self.assertEqual(metrics["nodes"], 4)
        self.assertEqual(metrics["cycles"], 1)
        self.assertEqual(metrics["max_fan_out"], 2)

    def test_graph_diff(self) -> None:
        old = DependencyGraph()
        new = DependencyGraph()
        for graph in (old, new):
            graph.add_node(GraphNode(node_id="a", kind="file", name="a", loc=10))
            graph.add_node(GraphNode(node_id="b", kind="file", name="b", loc=20))
        old.add_edge("a", "b", "import")
        new.add_edge("a", "b", "import")
        new.add_node(GraphNode(node_id="c", kind="file", name="c", loc=5))
        new.add_edge("b", "c", "import")
        new.nodes["a"].loc = 15
        diff = graph_diff(old, new)
        self.assertEqual(diff["counts"]["added_nodes"], 1)
        self.assertEqual(diff["counts"]["changed_nodes"], 1)
        self.assertEqual(diff["counts"]["added_edges"], 1)
        self.assertEqual(diff["counts"]["removed_edges"], 0)

    def test_build_file_graph(self) -> None:
        files = [
            {"path": "pkg/__init__.py", "loc": 5},
            {"path": "pkg/core.py", "loc": 20},
            {"path": "pkg/util.py", "loc": 15},
        ]
        imports = [
            {"path": "pkg/__init__.py", "module": "core", "level": 1, "names": "add"},
            {"path": "pkg/util.py", "module": "pkg.core", "level": 0, "names": None},
        ]
        graph = build_file_graph(files, imports)
        self.assertEqual(graph.node_count(), 3)
        self.assertEqual(graph.edge_count(), 2)
        self.assertEqual(graph.fan_in("pkg/core.py"), 2)

    def test_build_entity_graph_inheritance(self) -> None:
        sources = {
            "pkg/base.py": "class Base:\n    pass\n",
            "pkg/derived.py": "from .base import Base\n\nclass Derived(Base):\n    def run(self):\n        return 1\n",
        }
        files = []
        entities = []
        refs = []
        imports = []
        for path, source in sources.items():
            parsed = analyze_source(path, source)
            files.append(parsed.file_row())
            entities.extend(entity.as_dict() for entity in parsed.entities)
            refs.extend(ref.as_dict() for ref in parsed.refs)
            imports.extend(imp.as_dict() for imp in parsed.imports)
        graph = build_entity_graph(files, entities, refs)
        self.assertGreaterEqual(graph.node_count(), 4)
        derived = next(node for node in graph.nodes.values() if node.name == "Derived")
        self.assertEqual(graph.fan_out(derived.node_id), 1)
        base = next(node for node in graph.nodes.values() if node.name == "Base")
        self.assertEqual(graph.fan_in(base.node_id), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
