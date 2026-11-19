"""Lossless ordered JSON research structure; no engine or identity authority.

Only the standard library validates JSON grammar. Structural addresses describe
object-member ordinals and array indexes, never invented source coordinates.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_KINDS = {"object", "array", "string", "number", "boolean", "null"}
_NODE_FIELDS = {"address", "parent", "kind", "key", "scalar", "child_count", "line"}


@dataclass(frozen=True, slots=True)
class JsonNode:
    address: tuple[int, ...]
    parent: tuple[int, ...] | None
    kind: str
    key: str | None
    scalar: str | None
    child_count: int
    line: None = None


@dataclass(frozen=True, slots=True)
class JsonDocument:
    nodes: tuple[JsonNode, ...]

    def node(self, address: tuple[int, ...]) -> JsonNode:
        if type(address) is not tuple or any(type(i) is not int or i < 0 for i in address):
            raise ValueError("JSON address must contain integer ordinals")
        for node in self.nodes:
            if node.address == address:
                return node
        raise KeyError(address)

    def children(self, address: tuple[int, ...]) -> tuple[JsonNode, ...]:
        self.node(address)
        return tuple(node for node in self.nodes if node.parent == address)

    def members(self, address: tuple[int, ...], key: str) -> tuple[JsonNode, ...]:
        if self.node(address).kind != "object" or type(key) is not str:
            raise ValueError("JSON members require an object and a string key")
        return tuple(node for node in self.children(address) if node.key == key)

    def parent(self, address: tuple[int, ...]) -> JsonNode | None:
        parent = self.node(address).parent
        return None if parent is None else self.node(parent)

    def to_payload(self) -> str:
        return json.dumps(
            {"schema": 1, "nodes": [asdict(node) for node in self.nodes]},
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )


@dataclass(frozen=True, slots=True)
class JsonResult:
    raw_sha256: str
    raw_size: int
    decode_status: Literal["complete", "failed"]
    parse_status: Literal["complete", "failed"]
    had_bom: bool
    root_line: int | None
    diagnostics: tuple[str, ...]
    document: JsonDocument | None


@dataclass(frozen=True, slots=True)
class _Object:
    members: list[tuple[str, Any]]


@dataclass(frozen=True, slots=True)
class _Number:
    lexeme: str


def _constant(value: str) -> None:
    raise ValueError(f"non_finite_extension:{value}")


def _nodes(value: Any) -> tuple[tuple[JsonNode, ...], tuple[str, ...]]:
    pending: list[tuple[Any, tuple[int, ...], tuple[int, ...] | None, str | None]] = [
        (value, (), None, None)
    ]
    nodes: list[JsonNode] = []
    diagnostics = []
    while pending:
        item, address, parent, key = pending.pop()
        children: list[tuple[Any, tuple[int, ...], tuple[int, ...], str | None]] = []
        scalar = None
        if isinstance(item, _Object):
            kind = "object"
            seen = set()
            for ordinal, (name, child) in enumerate(item.members):
                if name in seen:
                    diagnostics.append(f"duplicate_member:{address}:{ordinal}")
                seen.add(name)
                children.append((child, (*address, ordinal), address, name))
        elif type(item) is list:
            kind = "array"
            children = [(child, (*address, i), address, None) for i, child in enumerate(item)]
        elif isinstance(item, _Number):
            kind, scalar = "number", item.lexeme
        elif type(item) is str:
            kind, scalar = "string", item
        elif type(item) is bool:
            kind, scalar = "boolean", "true" if item else "false"
        elif item is None:
            kind = "null"
        else:
            raise ValueError("unexpected JSON decoder value")
        if any(
            0xD800 <= ord(char) <= 0xDFFF
            for text in (key, scalar if kind == "string" else None)
            if text is not None
            for char in text
        ):
            diagnostics.append(f"unpaired_surrogate_interoperability_unknown:{address}")
        nodes.append(JsonNode(address, parent, kind, key, scalar, len(children)))
        pending.extend(reversed(children))
    return tuple(nodes), tuple(diagnostics)


def parse_json(raw: bytes) -> JsonResult:
    """Strict UTF-8 and JSON grammar, preserving number tokens and duplicate keys."""
    digest = hashlib.sha256(raw).hexdigest()
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8", errors="strict")
        if bom:
            text = text[1:]
    except UnicodeDecodeError as error:
        return JsonResult(
            digest,
            len(raw),
            "failed",
            "failed",
            bom,
            None,
            (f"utf8_decode_failed:bytes={error.start}:{error.end}:{error.reason}",),
            None,
        )
    try:
        value = json.loads(
            text,
            object_pairs_hook=_Object,
            parse_int=_Number,
            parse_float=_Number,
            parse_constant=_constant,
        )
        nodes, diagnostics = _nodes(value)
    except (ValueError, RecursionError) as error:
        return JsonResult(
            digest,
            len(raw),
            "complete",
            "failed",
            bom,
            None,
            (f"json_parse_failed:{type(error).__name__}:{error}",),
            None,
        )
    leading = len(text) - len(text.lstrip(" \t\r\n"))
    return JsonResult(
        digest,
        len(raw),
        "complete",
        "complete",
        bom,
        1 + text.count("\n", 0, leading),
        diagnostics,
        JsonDocument(nodes),
    )


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON payload field")
        result[key] = value
    return result


def _address(value: Any) -> tuple[int, ...]:
    if type(value) is not list or any(type(i) is not int or i < 0 for i in value):
        raise ValueError("invalid JSON node address")
    return tuple(value)


def load_payload(payload: str) -> JsonDocument:
    """Validate the complete preorder structure, types and explicit unknown positions."""
    value = json.loads(payload, object_pairs_hook=_unique, parse_constant=_constant)
    if (
        type(value) is not dict
        or set(value) != {"schema", "nodes"}
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or type(value["nodes"]) is not list
    ):
        raise ValueError("invalid JSON tree schema")
    nodes = []
    pending: list[tuple[tuple[int, ...], str | None]] = [((), None)]
    for row in value["nodes"]:
        if not pending or type(row) is not dict or set(row) != _NODE_FIELDS:
            raise ValueError("invalid JSON node fields or excess nodes")
        expected, parent_kind = pending.pop()
        address = _address(row["address"])
        parent = None if row["parent"] is None else _address(row["parent"])
        kind, key, scalar, count = row["kind"], row["key"], row["scalar"], row["child_count"]
        if (
            address != expected
            or parent != (address[:-1] if address else None)
            or type(kind) is not str
            or kind not in _KINDS
            or type(count) is not int
            or count < 0
            or row["line"] is not None
            or (parent_kind == "object" and type(key) is not str)
            or (parent_kind != "object" and key is not None)
        ):
            raise ValueError("invalid JSON node structure or types")
        if kind in {"object", "array", "null"}:
            valid = scalar is None and (kind != "null" or count == 0)
        else:
            valid = type(scalar) is str and count == 0
            if kind == "number":
                valid = valid and _NUMBER.fullmatch(scalar) is not None
            elif kind == "boolean":
                valid = valid and scalar in {"true", "false"}
        if not valid or count > len(value["nodes"]):
            raise ValueError("invalid JSON node scalar or child count")
        nodes.append(JsonNode(address, parent, kind, key, scalar, count))
        pending.extend(((*address, i), kind) for i in reversed(range(count)))
    if pending:
        raise ValueError("incomplete JSON tree")
    return JsonDocument(tuple(nodes))
