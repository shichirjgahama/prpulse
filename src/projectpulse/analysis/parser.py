"""Разбор Python-файлов: LOC, сложность, сущности, ссылки, импорты."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from projectpulse.core.utils import iso, stable_id


_TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b", re.IGNORECASE)


@dataclass
class EntityRecord:
    entity_id: str
    kind: str  # module | class | function
    name: str
    qualname: str
    path: str
    lineno: int
    end_lineno: int
    complexity: int = 1
    is_public: int = 0
    parent_id: str | None = None

    def as_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "kind": self.kind,
            "name": self.name,
            "qualname": self.qualname,
            "path": self.path,
            "lineno": self.lineno,
            "end_lineno": self.end_lineno,
            "complexity": self.complexity,
            "is_public": self.is_public,
            "parent_id": self.parent_id,
        }


@dataclass
class RefRecord:
    src_id: str
    kind: str  # inherit | call | compose
    target: str
    path: str
    lineno: int = 0

    def as_dict(self) -> dict:
        return {
            "src_id": self.src_id,
            "kind": self.kind,
            "target": self.target,
            "path": self.path,
            "lineno": self.lineno,
        }


@dataclass
class ImportRecord:
    path: str
    module: str | None
    level: int
    names: str
    lineno: int = 0

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "module": self.module,
            "level": self.level,
            "names": self.names,
            "lineno": self.lineno,
        }


@dataclass
class ParsedFile:
    path: str
    blob_sha: str | None
    size_bytes: int
    loc: int = 0
    sloc: int = 0
    comments: int = 0
    blanks: int = 0
    complexity_total: int = 0
    complexity_max: int = 0
    functions: int = 0
    classes: int = 0
    todo_count: int = 0
    parse_error: str | None = None
    entities: list[EntityRecord] = field(default_factory=list)
    refs: list[RefRecord] = field(default_factory=list)
    imports: list[ImportRecord] = field(default_factory=list)
    public_symbols: set[str] = field(default_factory=set)
    module_id: str = ""

    def file_row(self) -> dict:
        return {
            "path": self.path,
            "blob_sha": self.blob_sha,
            "language": "python",
            "size_bytes": self.size_bytes,
            "loc": self.loc,
            "sloc": self.sloc,
            "comments": self.comments,
            "blanks": self.blanks,
            "complexity_total": self.complexity_total,
            "complexity_max": self.complexity_max,
            "functions": self.functions,
            "classes": self.classes,
            "todo_count": self.todo_count,
            "parse_error": self.parse_error,
            "updated_at": iso(),
        }


def decode_source(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace")


def module_entity_id(path: str) -> str:
    return f"module:{path}"


def _qualified(name: str, stack: list[tuple[str, str]]) -> str:
    parts = [item[0] for item in stack] + [name]
    return ".".join(parts)


def _complexity_of(node: ast.AST) -> int:
    """Цикломатическая сложность поддерева без вложенных функций и классов."""

    def walk(current: ast.AST) -> int:
        increment = 0
        for child in ast.iter_child_nodes(current):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler)):
                increment += 1
            elif isinstance(child, ast.BoolOp):
                increment += max(0, len(child.values) - 1)
            elif isinstance(child, ast.comprehension):
                increment += len(child.ifs)
            elif isinstance(child, ast.Match):
                wildcard = 0
                for case in child.cases:
                    if isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None:
                        wildcard += 1
                increment += max(0, len(child.cases) - wildcard)
            increment += walk(child)
        return increment

    return 1 + walk(node)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - защита от нестандартных узлов
        return ""


class _Collector(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.module_id = module_entity_id(path)
        self.entities: list[EntityRecord] = []
        self.refs: list[RefRecord] = []
        self.imports: list[ImportRecord] = []
        self.stack: list[tuple[str, str]] = []  # (name, entity_id)
        self._ids: Counter[str] = Counter()
        self.public_symbols: set[str] = set()
        self.explicit_all: set[str] = set()

    def current_id(self) -> str:
        return self.stack[-1][1] if self.stack else self.module_id

    def _new_id(self, kind: str, qualname: str) -> str:
        base = f"{kind}:{self.path}:{qualname}"
        self._ids[base] += 1
        suffix = "" if self._ids[base] == 1 else f"#{self._ids[base]}"
        return base + suffix

    def _add_ref(self, kind: str, target: str | None, lineno: int) -> None:
        if not target:
            return
        self.refs.append(
            RefRecord(
                src_id=self.current_id(),
                kind=kind,
                target=target,
                path=self.path,
                lineno=lineno,
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualname = _qualified(node.name, self.stack)
        entity_id = self._new_id("class", qualname)
        is_public = 0 if node.name.startswith("_") else 1
        if len(self.stack) == 0 and is_public:
            self.public_symbols.add(node.name)
        entity = EntityRecord(
            entity_id=entity_id,
            kind="class",
            name=node.name,
            qualname=qualname,
            path=self.path,
            lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", node.lineno) or node.lineno,
            complexity=1,
            is_public=is_public,
            parent_id=self.stack[-1][1] if self.stack else None,
        )
        self.entities.append(entity)
        self.stack.append((node.name, entity_id))
        for base in node.bases:
            self._add_ref("inherit", _call_name(base) or _unparse(base).split(".")[-1], node.lineno)
        for decorator in node.decorator_list:
            target = _call_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
            self._add_ref("call", target, node.lineno)
        for statement in node.body:
            self.visit(statement)
        self.stack.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualname = _qualified(node.name, self.stack)
        entity_id = self._new_id("function", qualname)
        is_public = 0 if node.name.startswith("_") else 1
        if len(self.stack) == 0 and is_public:
            self.public_symbols.add(node.name)
        complexity = _complexity_of(node)
        entity = EntityRecord(
            entity_id=entity_id,
            kind="function",
            name=node.name,
            qualname=qualname,
            path=self.path,
            lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", node.lineno) or node.lineno,
            complexity=complexity,
            is_public=is_public,
            parent_id=self.stack[-1][1] if self.stack else None,
        )
        self.entities.append(entity)
        for decorator in node.decorator_list:
            target = _call_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
            self._add_ref("call", target, node.lineno)
        self.stack.append((node.name, entity_id))
        for statement in node.body:
            self.visit(statement)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        target = _call_name(node.func)
        self._add_ref("call", target, node.lineno)
        self.generic_visit(node)

    def _maybe_compose(self, value: ast.AST, lineno: int) -> None:
        if isinstance(value, ast.Call):
            target = _call_name(value.func)
            self._add_ref("compose", target, lineno)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._maybe_compose(node.value, node.lineno)
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                for element in node.value.elts:
                    if isinstance(element, ast.Constant) and isinstance(element.value, str):
                        self.explicit_all.add(element.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._maybe_compose(node.value, node.lineno)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(
                ImportRecord(path=self.path, module=alias.name, level=0, names=None, lineno=node.lineno)
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        names = ",".join(alias.name for alias in node.names) if node.names else None
        self.imports.append(
            ImportRecord(
                path=self.path,
                module=node.module,
                level=int(node.level or 0),
                names=names,
                lineno=node.lineno,
            )
        )


def _line_metrics(source: str) -> tuple[int, int, int, int]:
    loc = len(source.splitlines())
    blanks = sum(1 for line in source.splitlines() if not line.strip())
    comments_lines: set[int] = set()
    code_lines: set[int] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                comments_lines.add(token.start[0])
            elif token.type in (
                tokenize.NAME,
                tokenize.NUMBER,
                tokenize.STRING,
                tokenize.OP,
            ):
                code_lines.add(token.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        for index, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                comments_lines.add(index)
            else:
                code_lines.add(index)
    comments = len(comments_lines - code_lines)
    sloc = len(code_lines)
    return loc, sloc, comments, blanks


def analyze_source(path: str, source: str, blob_sha: str | None = None, size_bytes: int | None = None) -> ParsedFile:
    raw_size = size_bytes if size_bytes is not None else len(source.encode("utf-8", "replace"))
    parsed = ParsedFile(path=path, blob_sha=blob_sha, size_bytes=raw_size, module_id=module_entity_id(path))
    loc, sloc, comments, blanks = _line_metrics(source)
    parsed.loc = loc
    parsed.sloc = sloc
    parsed.comments = comments
    parsed.blanks = blanks
    parsed.todo_count = len(_TODO_RE.findall(source))

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        parsed.parse_error = f"SyntaxError: {exc.msg} (строка {exc.lineno})"
        return parsed

    collector = _Collector(path)
    for statement in tree.body:
        collector.visit(statement)

    parsed.entities = collector.entities
    parsed.refs = collector.refs
    parsed.imports = collector.imports
    parsed.public_symbols = collector.explicit_all or collector.public_symbols
    if "__init__" in path:
        parsed.public_symbols |= collector.public_symbols

    parsed.classes = sum(1 for e in parsed.entities if e.kind == "class")
    parsed.functions = sum(1 for e in parsed.entities if e.kind == "function")

    # Класс получает максимум сложности своих непосредственных методов.
    children: dict[str, list[int]] = {}
    for entity in parsed.entities:
        if entity.parent_id:
            children.setdefault(entity.parent_id, []).append(entity.complexity)
    for entity in parsed.entities:
        if entity.kind == "class":
            direct = [
                e.complexity
                for e in parsed.entities
                if e.kind == "function" and e.parent_id == entity.entity_id
            ]
            entity.complexity = max(direct) if direct else 1

    function_complexities = [e.complexity for e in parsed.entities if e.kind == "function"]
    module_level = _complexity_of(tree) - 1
    parsed.complexity_total = max(0, module_level) + sum(function_complexities)
    parsed.complexity_max = max(function_complexities) if function_complexities else 0
    return parsed


def analyze_bytes(path: str, raw: bytes, blob_sha: str | None = None) -> ParsedFile:
    source = decode_source(raw)
    return analyze_source(path, source, blob_sha=blob_sha, size_bytes=len(raw))


def parse_public_symbols(source: str) -> set[str]:
    """Публичные имена модуля для метрики изменчивости API."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    explicit: set[str] = set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    for element in node.value.elts:
                        if isinstance(element, ast.Constant) and isinstance(element.value, str):
                            explicit.add(element.value)
    return explicit or names


def source_of_entity(source: str, entity: EntityRecord) -> str:
    """Возвращает фрагмент исходника для сущности (для отчёта)."""
    lines = source.splitlines()
    start = max(0, entity.lineno - 1)
    end = min(len(lines), entity.end_lineno)
    return "\n".join(lines[start:end])
