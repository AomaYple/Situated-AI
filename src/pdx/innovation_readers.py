"""Exact capped-innovation/current-cap observations; no raw production reader.

Only the locked country definition and country or state->owner frame are
authorized. Invalid typed input stays unknown; genuine aggregate zero is valid.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from . import config
from .model import Block
from .parser import parse_text
from .situated import engine_scope
from .textio import normalized_text

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from .decision_rules import Reader

MANIFEST_ID = "research/situated/victoria3-1.15.0-innovation-readers.json"
MANIFEST = config.REPO / MANIFEST_ID
# Filled only from the assembled accepted raw observation/flag input.
MANIFEST_SHA256 = "8d4e8e39e26db09bb8dedf48cf5f9c94ee4da429d86efc637284ab7aaeb9aa87"
ENGINES = frozenset({"country_innovation", "modifier:country_weekly_innovation_max_add"})


def snapshot() -> bytes:
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError("创新读取器精确证据漂移")
    data = engine_scope._manifest_data(raw)
    if (
        data["schema"] != 1
        or data["contract"]["lhs"] != "country_innovation"
        or data["contract"]["rhs"] != "modifier:country_weekly_innovation_max_add"
        or data["contract"]["unit"] != "weekly_innovation_points"
        or data["contract"]["scale"] != 100000
        or data["contract"]["numeric_flags"]["masked_value"] != 0
    ):
        raise ValueError("创新读取器数值类型/单位/原生分支合同漂移")
    return raw


def validate_reader(reader: Reader, actor_path: tuple[str, ...], native_root: str) -> None:
    snapshot()
    prefix = "state_owner_" if native_root == "state" else ""
    key = prefix + ("innovation" if reader.engine == "country_innovation" else "innovation_cap")
    expected = ("state", ("owner",), ("owner",)) if native_root == "state" else ("country", (), ())
    if (
        (native_root, actor_path, reader.path) != expected
        or reader.engine not in ENGINES
        or reader.key != key
        or reader.scope != "root"
        or reader.kind != "number"
        or reader.unit != "weekly_innovation_points"
        or reader.minimum != (0 if reader.engine == "country_innovation" else None)
        or reader.maximum is not None
        or reader.argument is not None
        or reader.parameters
        or reader.value_field is not None
    ):
        raise ValueError("创新读取器必须保持精确country/州owner、getter、数值单位与零/未知边界")


def verify_inputs(texts: Mapping[str, str]) -> tuple[str, ...]:
    data = json.loads(snapshot())
    for source, expected in data["normalized_source_hashes"].items():
        value = texts.get(source)
        if value is None or hashlib.sha256(normalized_text(value).encode()).hexdigest() != expected:
            raise ValueError(f"创新读取器完整原版来源缺失或漂移：{source}")
    source = "common/modifier_type_definitions/00_modifier_types.txt"
    parsed = parse_text(texts[source])
    name = "country_weekly_innovation_max_add"
    matches = parsed.root.all(name)
    if parsed.errors or len(matches) != 1 or not isinstance(matches[0].value, Block):
        raise ValueError("创新cap缺少精确唯一数值定义")
    definition = matches[0].value
    # This exact complete definition is bound by source SHA as well; a boolean
    # flag, zero payload from an invalid definition or override never qualifies.
    if definition.first("boolean") is not None:
        raise ValueError("创新cap定义变为boolean，不能按numeric tag1读取")
    return tuple(f"{s}:sha256={h}" for s, h in sorted(data["normalized_source_hashes"].items()))


def proof(engine: str) -> tuple[str, ...]:
    if engine not in ENGINES:
        raise ValueError("非精确创新读取器没有原生授权")
    snapshot()
    return (
        f"{MANIFEST_ID}:sha256={MANIFEST_SHA256}",
        f"original-getter:{engine}",
        "numeric-tag1;invalid-tag0/2=unknown;scale100000;consumer-refresh",
    )


def verify_game(game: Path) -> tuple[tuple[str, str], ...]:
    data = json.loads(snapshot())
    sources = data["script_hashes"]
    actual = {
        p.relative_to(game).as_posix()
        for p in (game / "common/modifier_type_definitions").iterdir()
        if p.is_file() and p.suffix in {".txt", ".md"}
    }
    expected = {s for s in sources if s.startswith("common/modifier_type_definitions/")}
    if actual != expected:
        raise ValueError("创新cap完整定义目录闭包漂移")
    raw = {source: (game / source).read_bytes() for source in sources}
    _, hashes, verified = engine_scope._verified_manifest(
        game, raw, MANIFEST, MANIFEST_ID, MANIFEST_SHA256, "精确创新读取器证据"
    )
    if not verified:
        raise ValueError("创新读取器当前原版/引擎身份与已审证据不一致")
    verify_inputs({source: value.decode("utf-8-sig") for source, value in raw.items()})
    return hashes
