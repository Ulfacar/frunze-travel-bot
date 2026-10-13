"""Общие ошибки и ограниченный YAML/JSON-парсер для офлайн-проверки E5.

Запрещаем YAML aliases/anchors/tags и дубликаты до конструирования объектов.
Даты остаются строками, bool — только true/false (без YAML 1.1 yes/no/on/off).
Ошибки не включают значения из файла и фрагменты персональных данных.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
import yaml

MAX_BYTES = 2 * 1024 * 1024
MAX_NODES = 50_000
MAX_DEPTH = 32


@dataclass(frozen=True)
class Issue:
    code: str
    location: str
    message: str


class InvalidDocument(ValueError):
    def __init__(self, issue: Issue):
        self.issue = issue
        super().__init__(issue.code)


def fail(code: str, location: str, message: str) -> None:
    raise InvalidDocument(Issue(code, location, message))


@dataclass
class Report:
    errors: list[Issue]
    warnings: list[Issue]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> dict:
        return {"ok": self.ok, "errors": [asdict(i) for i in self.errors],
                "warnings": [asdict(i) for i in self.warnings]}


class StrictLoader(yaml.SafeLoader):
    pass


StrictLoader.yaml_implicit_resolvers = {
    key: [(tag, rx) for tag, rx in resolvers
          if tag not in {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp",
                         "tag:yaml.org,2002:int", "tag:yaml.org,2002:float"}]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf"))
StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int", re.compile(r"^-?(?:0|[1-9][0-9]*)$"), list("-0123456789"))
StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+(?:[eE][+-]?[0-9]+)?|[eE][+-]?[0-9]+)|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$"),
    list("-+0123456789."))


def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        location = f"{loader.filename}:{key_node.start_mark.line + 1}:{key_node.start_mark.column + 1}"
        if not isinstance(key, str):
            fail("syntax.key_type", location, "Mapping keys must be strings.")
        if key in result:
            fail("syntax.duplicate_key", location, "Duplicate mapping key.")
        result[key] = loader.construct_object(value_node)
    return result


StrictLoader.add_constructor("tag:yaml.org,2002:map", _mapping)


def check_tree(data: Any, location: str = "") -> None:
    """Ограничения действуют и для Python API; JSON не содержит NaN или циклов."""
    stack = [(data, 0)]
    seen = 0
    while stack:
        value, depth = stack.pop()
        seen += 1
        if seen > MAX_NODES or depth > MAX_DEPTH:
            fail("syntax.limit", location, "Document exceeds depth or node limit.")
        if isinstance(value, dict):
            if not all(isinstance(k, str) for k in value):
                fail("syntax.key_type", location, "Mapping keys must be strings.")
            try:
                for key in value:
                    key.encode("utf-8")
            except UnicodeEncodeError:
                fail("syntax.unicode", location, "Invalid Unicode scalar.")
            stack.extend((v, depth + 1) for v in value.values())
        elif isinstance(value, list):
            stack.extend((v, depth + 1) for v in value)
        elif type(value) not in (str, bool, int, float, type(None)):
            fail("syntax.type", location, "Unsupported value type.")
        elif isinstance(value, float) and not math.isfinite(value):
            fail("syntax.non_finite", location, "Non-finite numbers are forbidden.")
        elif type(value) is int and value.bit_length() > 512:
            fail("syntax.limit", location, "Integer exceeds 512 bits.")
        elif isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                fail("syntax.unicode", location, "Invalid Unicode scalar.")


def load_document(path: Path, *, reject_inline_comments: bool = False) -> Any:
    name = path.name
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            fail("syntax.size", name, "File exceeds 2 MiB.")
        source = raw.decode("utf-8-sig")
        # Tokenize before SafeLoader can recurse or expand references.
        masked = list(source) if reject_inline_comments else None
        depth = 0
        for count, token in enumerate(yaml.scan(source)):
            mark = token.start_mark
            loc = f"{name}:{mark.line + 1}:{mark.column + 1}"
            if count > MAX_NODES * 4:
                fail("syntax.limit", loc, "Too many YAML tokens.")
            if isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken, yaml.tokens.TagToken)):
                fail("syntax.reference", loc, "YAML anchors, aliases and explicit tags are forbidden.")
            if isinstance(token, (yaml.tokens.BlockMappingStartToken, yaml.tokens.BlockSequenceStartToken,
                                  yaml.tokens.FlowMappingStartToken, yaml.tokens.FlowSequenceStartToken)):
                depth += 1
                if depth > MAX_DEPTH:
                    fail("syntax.limit", loc, "Document exceeds depth limit.")
            if isinstance(token, (yaml.tokens.BlockEndToken, yaml.tokens.FlowMappingEndToken,
                                  yaml.tokens.FlowSequenceEndToken)):
                depth -= 1
            if masked is not None and isinstance(token, yaml.tokens.ScalarToken):
                start = mark.index
                if token.style in {"|", ">"}:
                    # Комментарий после |/> — синтаксический комментарий, не текст блока.
                    newline = source.find("\n", start, token.end_mark.index)
                    start = newline + 1 if newline >= 0 else token.end_mark.index
                for pos in range(start, token.end_mark.index):
                    if masked[pos] not in "\r\n":
                        masked[pos] = " "
        if masked is not None:
            for line_no, (original, clean) in enumerate(
                    zip(source.splitlines(), "".join(masked).splitlines()), 1):
                at = clean.find("#")
                if at >= 0 and original[:at].strip():
                    fail("syntax.inline_comment", f"{name}:{line_no}:{at + 1}",
                         "Move inline comment data into explicit fields.")
        if path.suffix.lower() == ".json":
            def pairs(items):
                value = {}
                for key, item in items:
                    if key in value:
                        fail("syntax.duplicate_key", name, "Duplicate mapping key.")
                    value[key] = item
                return value

            def constant(_value):
                fail("syntax.non_finite", name, "Non-finite numbers are forbidden.")

            data = json.loads(source, object_pairs_hook=pairs, parse_constant=constant)
        else:
            loader = StrictLoader(source)
            loader.filename = name
            try:
                data = loader.get_single_data()
            finally:
                loader.dispose()
        check_tree(data, name)
        return data
    except InvalidDocument:
        raise
    except (OSError, UnicodeError):
        fail("syntax.read", name, "Cannot read UTF-8 document.")
    except json.JSONDecodeError as exc:
        fail("syntax.json", f"{name}:{exc.lineno}:{exc.colno}", "Invalid JSON document.")
    except (yaml.YAMLError, RecursionError) as exc:
        mark = getattr(exc, "problem_mark", None)
        loc = f"{name}:{mark.line + 1}:{mark.column + 1}" if mark else name
        fail("syntax.yaml", loc, "Invalid YAML/JSON document.")
    except (ValueError, OverflowError):
        fail("syntax.scalar", name, "Numeric scalar exceeds parser limits.")


def schema_errors(data: Any, schema: dict, prefix: str = "") -> list[Issue]:
    issues = []
    for err in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data):
        pointer = "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in err.absolute_path)
        # jsonschema.message includes values. Expose only the constraint and path.
        issues.append(Issue(f"schema.{err.validator}", f"{prefix}/{pointer}",
                            f"Constraint failed: {err.validator}."))
        if len(issues) >= 100:
            break
    return issues
