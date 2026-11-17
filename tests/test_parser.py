"""Тесты разбора Python-файлов."""

from __future__ import annotations

import unittest

from projectpulse.analysis.parser import (
    analyze_bytes,
    analyze_source,
    decode_source,
    module_entity_id,
    parse_public_symbols,
    source_of_entity,
)

SOURCE = '''"""Module docstring."""

import os
from typing import Any

# комментарий
CONSTANT = 10


class Base:
    def method(self):
        return 1


class Derived(Base):
    """Derived class."""

    def compute(self, value):
        if value > 0 and value < 100:
            return value * 2
        for index in range(3):
            value += index
        return value


def public(value):
    if value:
        return _private(value)
    return 0


def _private(value):
    # TODO: убрать
    return value
'''


class ParserTests(unittest.TestCase):
    def test_line_metrics_and_size(self) -> None:
        parsed = analyze_source("pkg/mod.py", SOURCE)
        self.assertGreater(parsed.loc, 20)
        self.assertGreater(parsed.sloc, 0)
        self.assertGreater(parsed.comments, 0)
        self.assertGreater(parsed.blanks, 0)
        self.assertEqual(parsed.todo_count, 1)
        self.assertIsNone(parsed.parse_error)

    def test_entities_and_public_api(self) -> None:
        parsed = analyze_source("pkg/mod.py", SOURCE)
        names = {entity.qualname for entity in parsed.entities}
        self.assertIn("Base", names)
        self.assertIn("Derived", names)
        self.assertIn("Derived.compute", names)
        self.assertIn("public", names)
        self.assertIn("_private", names)
        self.assertEqual(parsed.classes, 2)
        # Base.method, Derived.compute, public и _private.
        self.assertEqual(parsed.functions, 4)
        self.assertIn("Derived", parsed.public_symbols)
        self.assertIn("public", parsed.public_symbols)
        self.assertNotIn("_private", parsed.public_symbols)

    def test_complexity(self) -> None:
        parsed = analyze_source("pkg/mod.py", SOURCE)
        compute = next(entity for entity in parsed.entities if entity.qualname == "Derived.compute")
        self.assertGreaterEqual(compute.complexity, 3)
        self.assertGreaterEqual(parsed.complexity_max, compute.complexity)
        self.assertGreater(parsed.complexity_total, 0)

    def test_refs_and_imports(self) -> None:
        parsed = analyze_source("pkg/mod.py", SOURCE)
        kinds = {ref.kind for ref in parsed.refs}
        self.assertIn("inherit", kinds)
        self.assertIn("call", kinds)
        inherit = [ref.target for ref in parsed.refs if ref.kind == "inherit"]
        self.assertEqual(inherit, ["Base"])
        modules = {record.module for record in parsed.imports}
        self.assertIn("os", modules)
        self.assertIn("typing", modules)

    def test_syntax_error_is_tolerated(self) -> None:
        parsed = analyze_source("bad.py", "def broken(:\n    pass\n")
        self.assertIsNotNone(parsed.parse_error)
        self.assertEqual(parsed.entities, [])
        self.assertGreater(parsed.loc, 0)

    def test_bytes_and_bom(self) -> None:
        raw = b"\xef\xbb\xbfvalue = 1\n"
        parsed = analyze_bytes("bom.py", raw)
        self.assertEqual(parsed.size_bytes, len(raw))
        self.assertEqual(parsed.loc, 1)
        self.assertEqual(parsed.entities, [])

    def test_decode_fallback(self) -> None:
        self.assertEqual(decode_source("тест".encode("cp1251")), "����")
        self.assertEqual(decode_source(b"ok"), "ok")

    def test_helpers(self) -> None:
        self.assertEqual(module_entity_id("a.py"), "module:a.py")
        self.assertEqual(parse_public_symbols("__all__ = ['x']\ndef x(): pass\n"), {"x"})
        self.assertEqual(parse_public_symbols("def broken(:\n"), set())
        parsed = analyze_source("pkg/mod.py", SOURCE)
        entity = next(item for item in parsed.entities if item.qualname == "public")
        snippet = source_of_entity(SOURCE, entity)
        self.assertIn("def public", snippet)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
