"""从已核验的 PDX AST 提取脚本符号定义与静态引用候选。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal

from .input_inventory import CONTENT_ROOTS
from .model import Assignment, Block, Scalar
from .references import (
    NUMERIC_FIELDS,
    SCRIPT_PARAMETER,
    SCRIPT_REFERENCE_KINDS,
    SCRIPT_SYMBOL_CATEGORIES,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from .model import Node, ParsedFile, ParseStatus


_MODIFIER_CATEGORIES = {
    "static_modifiers": "static_modifier",
    "scripted_modifiers": "scripted_modifier",
    "modifier_type_definitions": "modifier_type",
    "opinion_modifiers": "opinion_modifier",
}
_DEFINITION_KINDS = SCRIPT_SYMBOL_CATEGORIES | _MODIFIER_CATEGORIES
_SYMBOL_NAME = re.compile(r"[A-Za-z_0-9]*[A-Za-z_][A-Za-z_0-9]*")
_SCOPE_LINK = re.compile(r"(?:[A-Za-z_][A-Za-z_0-9]*:)?[A-Za-z_0-9]+")
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_CALL_KINDS = frozenset({"scripted_trigger", "scripted_effect"})
_SCRIPT_OPERATORS = frozenset({"=", "?=", "==", "!=", ">=", "<=", ">", "<"})
_TRIGGER_BLOCKS = frozenset({"trigger", "limit"})
_DECISION_BLOCKS = {
    "is_shown": "scripted_trigger",
    "possible": "scripted_trigger",
    "when_taken": "scripted_effect",
}
_EVENT_EFFECT_BLOCKS = frozenset({"immediate", "after", "option"})
_FORMULA_FIELDS = frozenset({"modulo", "round_to"})
_MODIFIER_FIELDS = frozenset({"has_modifier", "remove_modifier", "add_modifier"})


type ReferenceStatus = Literal[
    "candidate", "missing", "ambiguous", "dynamic", "observational", "unknown"
]


type _Reference = tuple[str | None, str, str, ReferenceStatus]


@dataclass(frozen=True, slots=True)
class ScriptDefinition:
    source: str
    source_sha256: str
    address: tuple[int, ...]
    path: tuple[str, ...]
    line: int
    parse_status: ParseStatus
    kind: str
    name: str


@dataclass(frozen=True, slots=True)
class ScriptReference:
    source: str
    source_sha256: str
    address: tuple[int, ...]
    path: tuple[str, ...]
    line: int
    parse_status: ParseStatus
    name: str | None
    requested_kind: str | None
    syntax: str
    status: ReferenceStatus


def definition_kind(path: str) -> str | None:
    """按锁定安装的内容目录识别定义文件。"""
    return _definition_kind(PurePosixPath(path).parts)


def _definition_kind(parts: tuple[str, ...]) -> str | None:
    if (
        len(parts) >= 4
        and parts[0] in CONTENT_ROOTS
        and parts[1] == "common"
        and parts[-1].endswith(".txt")
    ):
        return _DEFINITION_KINDS.get(parts[2])
    return None


def iter_definitions(
    path: str, source_sha256: str, parsed: ParsedFile
) -> Iterator[ScriptDefinition]:
    """保留可定位的顶层定义语法，重复定义分别登记。"""
    kind = definition_kind(path)
    parse_status = parsed.parse_status
    if kind is None or parse_status == "failed":
        return
    for ordinal, node in enumerate(parsed.root.items):
        if (
            not isinstance(node, Assignment)
            or node.op != "="
            or not _SYMBOL_NAME.fullmatch(node.key)
        ):
            continue
        if isinstance(node.value, Block) or (
            kind == "script_value" and isinstance(node.value, Scalar)
        ):
            yield ScriptDefinition(
                path,
                source_sha256,
                (ordinal,),
                (node.full_key,),
                node.line,
                parse_status,
                kind,
                node.key,
            )


def _block_role(
    path: tuple[str, ...],
    field: str,
    script_kind: str | None,
    role: str | None,
    category: tuple[str, ...],
) -> str | None:
    if not path:
        return script_kind if script_kind in _CALL_KINDS else None
    if field in _TRIGGER_BLOCKS or (len(path) == 1 and field == "potential"):
        return "scripted_trigger"
    if field == "effect":
        return "scripted_effect"
    if len(path) == 1 and category == ("common", "decisions"):
        return _DECISION_BLOCKS.get(field, role)
    if len(path) == 1 and category[:1] == ("events",) and field in _EVENT_EFFECT_BLOCKS:
        return "scripted_effect"
    return role


def _scalar_kind(
    field: str, parents: tuple[str, ...], script_kind: str | None
) -> tuple[str | None, str]:
    if field in _MODIFIER_FIELDS or (field == "name" and parents[-1:] == ("add_modifier",)):
        return "static_modifier", "modifier_field"
    if script_kind == "modifier_type" and field == "translate" and parents[-1:] == ("game_data",):
        return "modifier_type", "modifier_type_translation"
    if kind := SCRIPT_REFERENCE_KINDS.get(field):
        return kind, "explicit_reference_field"
    if (
        field in NUMERIC_FIELDS
        or (field == "days" and parents[-1:] == ("add_modifier",))
        or (script_kind == "script_value" and (not parents or field in _FORMULA_FIELDS))
    ):
        return "script_value", "numeric_field"
    return None, ""


def _dynamic(expression: str) -> bool:
    return (
        expression.startswith("@")
        or bool(SCRIPT_PARAMETER.search(expression))
        or any(
            link.startswith(("var:", "local_var:", "global_var:")) for link in expression.split(".")
        )
    )


def _terminal(expression: str) -> tuple[str | None, str | None]:
    terminal = expression.rsplit(".", maxsplit=1)[-1]
    prefix, separator, name = terminal.partition(":")
    if not separator:
        return None, terminal if _SYMBOL_NAME.fullmatch(terminal) else None
    return prefix, name if _SYMBOL_NAME.fullmatch(name) else None


def _reference_status(matches: int, parse_status: ParseStatus) -> ReferenceStatus:
    if parse_status == "partial":
        return "unknown"
    if matches > 1:
        return "ambiguous"
    return "candidate" if matches else "missing"


def _scalar_reference(
    value: Scalar,
    requested: str | None,
    syntax: str,
    names: Mapping[str, Mapping[str, int]],
    parse_status: ParseStatus,
) -> _Reference | None:
    expression = value.unquoted
    # 避免把路径、文本、构造表达式和数字中的任意单词匹配为符号。
    if not expression or (requested is None and ":" not in expression):
        return None
    if _NUMBER.fullmatch(expression) or expression in ("yes", "no"):
        return None
    prefix, name = _terminal(expression)
    explicit = "modifier_type" if prefix == "modifier" else SCRIPT_REFERENCE_KINDS.get(prefix or "")
    recognized_kind = explicit or requested
    if recognized_kind is None:
        return None
    if value.quoted and syntax != "modifier_type_translation":
        if name is not None and all(_SCOPE_LINK.fullmatch(link) for link in expression.split(".")):
            return name, recognized_kind, "quoted_symbol_observation", "observational"
        return None
    if _dynamic(expression):
        return None, recognized_kind, "dynamic_symbol_reference", "dynamic"
    if explicit:
        syntax = "modifier_type_accessor" if prefix == "modifier" else "explicit_symbol_prefix"
    if name is None or not all(_SCOPE_LINK.fullmatch(link) for link in expression.split(".")):
        if syntax == "numeric_field":
            return None
        return None, recognized_kind, syntax, "unknown"
    if syntax == "numeric_field":
        if prefix or not names.get(name, {}).get("script_value"):
            return name, recognized_kind, "numeric_identifier_or_engine_getter", "unknown"
        syntax = "scoped_script_value" if "." in expression else "named_script_value"
    elif not explicit and (prefix or "." in expression):
        return None, recognized_kind, syntax, "unknown"
    return (
        name,
        recognized_kind,
        syntax,
        _reference_status(names.get(name, {}).get(recognized_kind, 0), parse_status),
    )


def _key_reference(
    node: Assignment,
    parents: tuple[str, ...],
    script_kind: str | None,
    role: str | None,
    names: Mapping[str, Mapping[str, int]],
    parse_status: ParseStatus,
) -> _Reference | None:
    if not parents or node.prefix or node.value is None or node.op not in ("=", "?="):
        return None
    if script_kind == "static_modifier" and len(parents) == 1:
        if _SYMBOL_NAME.fullmatch(node.key) and names.get(node.key, {}).get("modifier_type"):
            return (
                node.key,
                "modifier_type",
                "static_modifier_entry",
                _reference_status(names[node.key]["modifier_type"], parse_status),
            )
        return None
    if role is None and ":" not in node.key:
        return None
    prefix, name = _terminal(node.key)
    explicit = SCRIPT_REFERENCE_KINDS.get(prefix or "")
    kind = explicit if explicit in _CALL_KINDS else role
    if kind is None or (prefix and explicit not in _CALL_KINDS):
        return None
    if _dynamic(node.key) and (explicit or node.key.startswith("$") or "." in node.key):
        return None, kind, "dynamic_assignment_key", "dynamic"
    if name is None or not all(_SCOPE_LINK.fullmatch(link) for link in node.key.split(".")):
        return None
    matches = names.get(name, {}).get(kind, 0)
    if matches or explicit:
        return name, kind, "assignment_key_call", _reference_status(matches, parse_status)
    if name.endswith(f"_{kind}"):
        return name, kind, "call_shaped_key", "unknown"
    return None


def supports_references(path: str) -> bool:
    """Return whether this path participates in the declared script reference scan."""
    return _supports_references(PurePosixPath(path).parts)


def _supports_references(parts: tuple[str, ...]) -> bool:
    return (
        len(parts) >= 3
        and parts[0] in CONTENT_ROOTS
        and parts[1] in {"common", "events", "history"}
        and parts[-1].endswith(".txt")
    )


def iter_references(
    path: str,
    source_sha256: str,
    parsed: ParsedFile,
    names: Mapping[str, Mapping[str, int]],
) -> Iterator[ScriptReference]:
    """沿单个源的 AST 顺序保留命名候选，状态只反映已登记的静态定义。"""
    parts = PurePosixPath(path).parts
    parse_status = parsed.parse_status
    if parse_status == "failed" or not _supports_references(parts):
        return
    script_kind = _definition_kind(parts)
    category = parts[1:3]
    stack: list[tuple[Node, tuple[int, ...], tuple[str, ...], str | None]] = [
        (node, (ordinal,), (), None)
        for ordinal, node in reversed(list(enumerate(parsed.root.items)))
    ]
    while stack:
        node, address, parents, role = stack.pop()
        child: Block | None
        if isinstance(node, Block):
            node_path = (*parents, "[]")
            child = node
        elif isinstance(node, Assignment):
            node_path = (*parents, node.full_key)
            key_call = _key_reference(node, parents, script_kind, role, names, parse_status)
            if key_call is not None:
                yield ScriptReference(
                    path, source_sha256, address, node_path, node.line, parse_status, *key_call
                )
            if (
                isinstance(node.value, Scalar)
                and node.op in _SCRIPT_OPERATORS
                and not node.is_variable
            ):
                requested, syntax = _scalar_kind(node.key, parents, script_kind)
                if call := _scalar_reference(node.value, requested, syntax, names, parse_status):
                    yield ScriptReference(
                        path,
                        source_sha256,
                        address,
                        node_path,
                        node.value.line,
                        parse_status,
                        *call,
                    )
            child = node.value if isinstance(node.value, Block) else None
            if child is not None:
                role = (
                    None
                    if key_call
                    else _block_role(parents, node.key, script_kind, role, category)
                )
        else:
            node_path = parents
            if call := _scalar_reference(node, None, "", names, parse_status):
                yield ScriptReference(
                    path, source_sha256, address, node_path, node.line, parse_status, *call
                )
            child = None
        if child is not None:
            stack.extend(
                (item, (*address, ordinal), node_path, role)
                for ordinal, item in reversed(list(enumerate(child.items)))
            )
