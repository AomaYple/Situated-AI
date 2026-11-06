"""Narrow current native proof for twelve exact missing-field initializers.

The State frame does not expose the independent candidate Country or payer.
An explicit expression, including an empty or conditional-only one, never uses
the absent-kind default. Zero does not terminate the production scoring chain.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from . import config
from .model import Assignment, Block, Scalar
from .parser import parse_text
from .situated import engine_scope

if TYPE_CHECKING:
    from pathlib import Path

MANIFEST_ID = "research/situated/victoria3-1.15.0-building-defaults.json"
MANIFEST = config.REPO / MANIFEST_ID
MANIFEST_SHA256 = "e0ff6b2a08bcaf7ec39a79f89babbec6ce5dc8d5384591b4b2fe3ff161289aa0"
_CONTRACT_SHA256 = "34e70b7ef454871bf4281eff576a9cb7bba8bfeb9847c4ebf84551859b31df26"
_INITIALIZERS_SHA256 = "78091ca6ec4dc2a319ef0ee0e28cc9639cf338a6ecddab2b57cbe5464b9edbbc"
SELECTOR_ID = "research/situated/victoria3-1.15.0-building-static-selector.json"
_SELECTOR = config.REPO / SELECTOR_ID
_SELECTOR_SHA256 = "befd2bcee8cb7996928102f200835109b235f2602c88cf97ca7f317adfe7f24d"
_SELECTOR_CONTENT_SHA256 = "9c607f59757c83858659d9e72ecc6fe307c8884f69296477b18972e0f11c5624"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _shape(value: Assignment | Block | Scalar | None) -> Any:
    if value is None:
        return None
    if isinstance(value, Assignment):
        return [value.key, value.op, value.prefix, _shape(value.value)]
    if isinstance(value, Block):
        return [_shape(item) for item in value.items]
    return [value.text, value.quoted]


def _selector_data() -> dict[str, Any]:
    """Read the reviewed static lifecycle, never granting dynamic local writers."""
    raw = _SELECTOR.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _SELECTOR_SHA256:
        raise ValueError("建筑静态表达式源证据漂移")
    data = engine_scope._manifest_data(raw)
    if _digest(data) != _SELECTOR_CONTENT_SHA256:
        raise ValueError("建筑静态表达式源精确合同漂移")
    return data


def snapshot() -> bytes:
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("建筑缺省值原生证据漂移")
    data = engine_scope._manifest_data(raw)
    if (
        set(data)
        != {
            "schema",
            "evidence",
            "baseline",
            "exe",
            "script_hashes",
            "observations",
            "contract",
            "initializers",
            "lineage",
        }
        or data["schema"] != 1
        or data["evidence"] != "static_check_not_engine_execution"
        or data["baseline"] != "victoria3-1.15.0-windows-x64"
        or _digest(data["contract"]) != _CONTRACT_SHA256
        or _digest(data["initializers"]) != _INITIALIZERS_SHA256
    ):
        raise ValueError("建筑缺省值精确原生合同漂移")
    selector = _selector_data()
    proof = data["contract"]["expression_source"]
    types = {row["id"]: row for row in selector["exact_types"]}
    if (
        proof["proof"] != SELECTOR_ID
        or proof["sha256"] != _SELECTOR_SHA256
        or data["exe"] != selector["exe"]
        or len(types) != 12
        or selector["contract"]["copper_initializer_permission"] is not True
        or set(selector["contract"]["initializer_ids"])
        != {row["id"] for row in data["initializers"]}
        or any(data["script_hashes"].get(s) != h for s, h in selector["script_hashes"].items())
        or any(
            row["id"] not in types
            or any(types[row["id"]].get(key) != value for key, value in row.items())
            or types[row["id"]]["source_kind"] != "static_named_definition"
            or types[row["id"]]["source_operator"] != "="
            or types[row["id"]]["source_prefix"] is not None
            or types[row["id"]]["local_ai_value"] != "absent"
            for row in data["initializers"]
        )
    ):
        raise ValueError("建筑静态表达式源与唯一初始化器/完整源身份不一致")
    return raw


def validate_initializer(
    source: str,
    field: tuple[str, ...],
    define_source: str,
    define: tuple[str, ...],
    parent: Assignment,
) -> None:
    """Require exact current complete parent even if source hashes are repinned."""
    data = json.loads(snapshot())
    rows = [
        r for r in data["initializers"] if r["source"] == source and (r["id"], r["field"]) == field
    ]
    if (
        len(rows) != 1
        or define_source != "common/defines/00_ai.txt"
        or define != ("NAI", "PRODUCTION_BUILDING_BASE_VALUE")
        or rows[0]["line"] != parent.line
        or rows[0]["parent_sha256"] != _digest(_shape(parent))
        or parent.op != "="
        or parent.prefix is not None
        or not isinstance(parent.value, Block)
        or parent.value.first("ai_value") is not None
    ):
        raise ValueError("建筑缺省值偏离已证明的唯一缺省父结构/类别")


def verify_game(game: Path) -> tuple[tuple[str, str], ...]:
    """Verify EXE spans, all building source identities and reviewed group chains."""
    data = json.loads(snapshot())
    sources = data["script_hashes"]
    actual = {
        p.relative_to(game).as_posix()
        for directory in ("common/buildings", "common/building_groups")
        for p in (game / directory).rglob("*.txt")
        if p.is_file()
    }
    if actual != {
        s
        for s in sources
        if s.endswith(".txt") and s.startswith(("common/buildings/", "common/building_groups/"))
    }:
        raise ValueError("建筑缺省值原版来源集合漂移")
    _, hashes, verified = engine_scope._verified_manifest(
        game,
        {s: (game / s).read_bytes() for s in sources},
        MANIFEST,
        MANIFEST_ID,
        MANIFEST_SHA256,
        "建筑缺省值原生证据",
    )
    if not verified:
        raise ValueError("当前建筑缺省值原版或EXE与锁定证据不一致")
    selector = _selector_data()
    _, selector_hashes, selector_verified = engine_scope._verified_manifest(
        game,
        {s: (game / s).read_bytes() for s in selector["script_hashes"]},
        _SELECTOR,
        SELECTOR_ID,
        _SELECTOR_SHA256,
        "建筑静态表达式源证据",
    )
    if not selector_verified:
        raise ValueError("当前建筑静态表达式源或EXE与锁定证据不一致")
    roots = {s: parse_text((game / s).read_text(encoding="utf-8-sig")) for s in actual}
    if any(p.errors for p in roots.values()):
        raise ValueError("建筑缺省值原件无法解析")
    if _digest(_shape(roots["common/building_groups/00_building_groups.txt"].root)) != (
        "4e5998fc2cfe455dba4701a6547b0a3b8a76cb428755a84309026d89c3ad4934"
    ):
        raise ValueError("建筑缺省值资金类别及完整继承合同漂移")
    for row in data["initializers"]:
        parents = [
            (source, parent)
            for source, parsed in roots.items()
            if source.startswith("common/buildings/")
            for parent in parsed.root.all(row["id"])
        ]
        if len(parents) != 1 or parents[0][0] != row["source"]:
            raise ValueError("建筑缺省值原版父身份重复或缺失")
        validate_initializer(
            row["source"],
            (row["id"], "ai_value"),
            "common/defines/00_ai.txt",
            ("NAI", "PRODUCTION_BUILDING_BASE_VALUE"),
            parents[0][1],
        )
    return tuple(sorted({**dict(hashes), **dict(selector_hashes)}.items()))
