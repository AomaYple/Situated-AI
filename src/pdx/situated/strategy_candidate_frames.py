"""Compact, immutable frames for the reviewed strategy expansion evidence.

This module pins the existing native-strategy-expansion artifact identities and
projects only the two ship-category fields and six named strategy definitions
that were explicitly reviewed.  Definition keys remain lookup keys; they do
not create live scopes or authorize additional readers.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from pdx import config
from pdx.model import Block, Scalar
from pdx.parser import parse_text

from . import decision_ir, engine_scope

PROOF_ID = "research/situated/victoria3-1.15.0-strategy-candidate-frames.json"
PROOF = config.REPO / PROOF_ID
PROOF_SHA256 = "08e7f8e2c2d30c80d283a23952dacd583a7f6375a1214a70a9c5e097dd7f8314"

WEIGHT_DEFINITIONS = frozenset(
    {
        "ai_strategy_agricultural_expansion",
        "ai_strategy_industrial_expansion",
        "ai_strategy_resource_expansion",
        "ai_strategy_subject_maintain_autonomy",
        "ai_strategy_subject_strengthen_self",
        "ai_strategy_subject_overlord_compliance",
    }
)
SHIP_FIELDS = frozenset(
    {
        "ai_strategy_default.ai_ship_category_weights.ai_ship_category_battle_line",
        "ai_strategy_default.ai_ship_category_weights.ai_ship_category_carriers",
    }
)


def _load() -> dict[str, Any]:
    raw = PROOF.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROOF_SHA256:
        raise ValueError("策略扩展frame证据变化，须独立复核")
    data = cast("dict[str, Any]", json.loads(raw))
    strategy = json.loads(engine_scope.strategy_snapshot())
    if data.get("schema") != "situated-reviewed-strategy-candidate-frames/1":
        raise ValueError("策略扩展frame schema漂移")
    if data.get("exe_sha256") != strategy["exe"]["sha256"]:
        raise ValueError("策略扩展frame EXE身份漂移")
    if (
        data["strategy_weight_frame"] != strategy["consumers"]["weight"]
        or data["strategy_weight_evidence"]["source"] != engine_scope.STRATEGY_MANIFEST_ID
        or data["strategy_weight_evidence"]["sha256"] != engine_scope.STRATEGY_MANIFEST_SHA256
    ):
        raise ValueError("策略weight消费者国家frame或原生选择证据漂移")
    if data["ship_category"]["fields"] != sorted(SHIP_FIELDS):
        raise ValueError("舰船类别frame字段全集漂移")
    if len(data["ship_category"]["observations"]) != 6:
        raise ValueError("舰船类别frame观察集合漂移")
    return data


def _context(source: str, marker: str) -> decision_ir.EvaluationContext:
    data = _load()
    raw = PROOF.read_text(encoding="utf-8")
    lines = raw.splitlines()
    line = next((i + 1 for i, text in enumerate(lines) if marker in text), None)
    if line is None:
        raise ValueError(f"策略扩展frame缺少行级证据：{marker}")
    return decision_ir.EvaluationContext(
        actor_scope=decision_ir.ContextBinding("root", "country", "actor", PROOF_ID, line),
        evidence=(
            f"{PROOF_ID}:{line}",
            f"{PROOF_ID}:sha256={PROOF_SHA256}",
            f"{PROOF_ID}:source={source}",
            f"{PROOF_ID}:definition_only;no_named_target",
            f"{engine_scope.STRATEGY_MANIFEST_ID}:sha256={engine_scope.STRATEGY_MANIFEST_SHA256}",
            *(f"{row['path']}:sha256={row['sha256']}" for row in data["accepted_artifacts"]),
        ),
    )


def strategy_weight_context(source: str, definition: str) -> decision_ir.EvaluationContext:
    if (
        source
        not in {
            "common/ai_strategies/01_admin_strategies.txt",
            "common/ai_strategies/02_subject_diplomatic_strategies.txt",
        }
        or definition not in WEIGHT_DEFINITIONS
    ):
        raise ValueError("策略weight不在精确已审定义白名单")
    data = _load()
    rows = [row for row in data["strategy_definitions"] if row["definition"] == definition]
    strategy = json.loads(engine_scope.strategy_snapshot())
    if (
        len(rows) != 1
        or rows[0]["source"] != source
        or rows[0]["sha256"] != strategy["script_hashes"][source]
    ):
        raise ValueError("策略weight精确来源或定义身份漂移")
    parsed = parse_text(rows[0]["text"])
    entries = parsed.top_assignments
    if (
        parsed.errors
        or len(entries) != 1
        or entries[0].key != definition
        or not isinstance(entries[0].value, Block)
    ):
        raise ValueError("策略weight定义必须为唯一普通块")
    entry = entries[0]
    block = entry.value
    assert isinstance(block, Block)
    kind = block.all("type")
    weight = block.all("weight")
    expected = "administrative" if source.endswith("01_admin_strategies.txt") else "diplomatic"
    if (
        entry.op != "="
        or entry.prefix is not None
        or len(kind) != 1
        or kind[0].op != "="
        or kind[0].prefix is not None
        or not isinstance(kind[0].value, Scalar)
        or kind[0].value.text != expected
        or len(weight) != 1
        or weight[0].op != "="
        or weight[0].prefix is not None
        or not isinstance(weight[0].value, Block)
    ):
        raise ValueError("策略weight类型或普通数值字段漂移")
    return _context(source, f'"definition": "{definition}"')


def ship_category_context(field: str) -> decision_ir.EvaluationContext:
    if field not in SHIP_FIELDS:
        raise ValueError("舰船类别字段不在精确已审白名单")
    data = _load()
    ship = data["ship_category"]
    if (
        ship["frame"] != [{"name": "root", "tag": 5, "identity": "actor country+0x18"}]
        or ship["definition_scope"] != "definition_only:CAIShipCategory;no_named_target"
    ):
        raise ValueError("舰船类别国家ROOT或definition-only边界漂移")
    source = "common/ai_strategies/00_default_strategy.txt"
    raw = (config.REPO / "research/vanilla-ai/1.15.0/00_default_strategy.txt").read_bytes()
    if ship["source"]["path"] != source or ship["source"]["sha256"] not in {
        hashlib.sha256(raw).hexdigest(),
        hashlib.sha256(b"\xef\xbb\xbf" + raw).hexdigest(),
    }:
        raise ValueError("舰船类别精确策略原件漂移")
    parsed = parse_text(raw.decode("utf-8-sig"))
    definitions = [item for item in parsed.top_assignments if item.key == "ai_strategy_default"]
    if len(definitions) != 1 or not isinstance(definitions[0].value, Block):
        raise ValueError("舰船类别缺少唯一默认策略定义")
    block = definitions[0].value
    for key in field.removeprefix("ai_strategy_default.").split("."):
        entries = block.all(key)
        if (
            len(entries) != 1
            or entries[0].op != "="
            or entries[0].prefix is not None
            or not isinstance(entries[0].value, Block)
        ):
            raise ValueError("舰船类别必须保持唯一普通数值字段")
        block = entries[0].value
    if parsed.errors:
        raise ValueError("舰船类别策略原件无法解析")
    return _context("common/ai_strategies/00_default_strategy.txt", f'"{field}"')


def frozen_contexts() -> dict[tuple[str, str], decision_ir.EvaluationContext]:
    result = {
        **{
            (
                "common/ai_strategies/01_admin_strategies.txt"
                if name.endswith("expansion")
                else "common/ai_strategies/02_subject_diplomatic_strategies.txt",
                f"{name}.weight",
            ): strategy_weight_context(
                "common/ai_strategies/01_admin_strategies.txt"
                if name.endswith("expansion")
                else "common/ai_strategies/02_subject_diplomatic_strategies.txt",
                name,
            )
            for name in sorted(WEIGHT_DEFINITIONS)
        },
    }
    for field in sorted(SHIP_FIELDS):
        context = ship_category_context(field)
        result[("common/ai_strategies/00_default_strategy.txt", field)] = context
        result[
            (
                "common/ai_strategies/00_default_strategy.txt",
                field.removeprefix("ai_strategy_default."),
            )
        ] = context
    return result
