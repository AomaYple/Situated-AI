"""Narrow current native proof for eleven existing missing-field initializers.

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
MANIFEST_SHA256 = "3b290448ee272faa2589fcd682a93942b63b330b1552a8ffafa5cee45126b6bf"
_CONTRACT_SHA256 = "261de98871eb310140b2392add7c2ac2123adc314820f6005c45773f0615769e"
_INITIALIZERS_SHA256 = "b20c6dd9a27fe4c968bd852a44d7c55243284d331f83c6f9a035d3d3e9b2e07e"


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
    return hashes
