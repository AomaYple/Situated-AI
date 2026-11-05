"""Native ship-modification materials, frozen identities and bounded preferences.

The native documentation calls ai_weight fixed_point, while actual definitions
use scripted blocks and the country-scoped ship-modification market formula.
This is static native evidence for those exact blocks, never a runtime claim or
permission to initialize omitted weights or reinterpret scalar consumers.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from . import config, decision_rules
from .model import Assignment, Block, Scalar
from .parser import parse_text
from .situated import vanilla_inventory
from .textio import normalized_text

if TYPE_CHECKING:
    from pathlib import Path

BASELINE = config.REPO / "research/vanilla-ai/1.15.0/equipment-opportunities.json"
BASELINE_SHA256 = "f971f5f2aea6ba802e30480b68ff539757a20dc64746b16e705a7f65a71596d5"
PARAMETERS = config.REPO / "mod/decisions/equipment_opportunities.toml"
_DOC = "common/ship_modifications/ship_modifications.md"
_HELPER = "common/script_values/ai_script_values.txt"
_FORMULA_DOC = "common/script_values/script_values.md"
_REQUIRED = frozenset({_DOC, _HELPER, _FORMULA_DOC})
_FAMILIES = frozenset({"ship_modifications", "goods", "script_values"})
_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_INPUT = re.compile(r"goods_input_([a-z][a-z0-9_]*)_add\Z")
_CONTRACT = {
    "actor": "country",
    "target": "scope:ship_modification_type=ship_modification",
    "target_role": "candidate",
    "operation": "score",
    "documented_type": "fixed_point",
    "supported_shape": "block",
    "evidence": "native_scripted_block_and_scoped_formula_not_runtime",
}
_PARAMETERS = frozenset(
    {
        "priority_base",
        "opportunity_price_threshold",
        "pressure_price_threshold",
        "opportunity_multiplier",
        "scarcity_multiplier",
        "pressure_multiplier",
        "default_multiplier",
    }
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _family(source: str) -> str | None:
    path = PurePosixPath(source)
    if (
        path.is_absolute()
        or path.as_posix() != source
        or ".." in path.parts
        or "\\" in source
        or ":" in source
        or not source.startswith(("common/", "dlc/"))
    ):
        raise ValueError("舰船材料原件路径无效")
    if len(path.parts) >= 3 and path.parts[-3] == "common" and path.suffix == ".txt":
        return path.parts[-2] if path.parts[-2] in _FAMILIES else None
    return None


def _ast(node: object) -> object:
    if isinstance(node, Scalar):
        return ["scalar", node.text, node.quoted]
    if isinstance(node, Assignment):
        return ["assignment", node.key, node.op, node.prefix, _ast(node.value)]
    if isinstance(node, Block):
        return ["block", [_ast(item) for item in node.items]]
    raise ValueError("舰船材料原件含未知AST节点")


def _one(block: Block, key: str) -> Assignment | None:
    values = block.all(key)
    if len(values) > 1 or any(value.op != "=" or value.prefix is not None for value in values):
        raise ValueError(f"舰船材料字段重复或不是普通赋值：{key}")
    return values[0] if values else None


def _positive(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except ValueError:
        return False


def _goods(block: Block, role: str, goods: Mapping[str, Any]) -> dict[str, str]:
    field = _one(block, role)
    if field is None:
        return {}
    if not isinstance(field.value, Block):
        raise ValueError("舰船材料必须为普通修饰器块")
    result: dict[str, str] = {}
    seen: set[str] = set()
    for item in field.value.items:
        if not isinstance(item, Assignment) or (match := _INPUT.fullmatch(item.key)) is None:
            raise ValueError("舰船材料含未知修饰器，不能猜测投入")
        good = match[1]
        if (
            good in seen
            or good not in goods
            or item.op != "="
            or item.prefix is not None
            or not isinstance(item.value, Scalar)
            or item.value.quoted
        ):
            raise ValueError("舰船材料重复、引用缺失或不是明确数字")
        seen.add(good)
        try:
            amount = float(item.value.text)
        except ValueError as exc:
            raise ValueError("舰船材料必须为数字常量") from exc
        if not math.isfinite(amount):
            raise ValueError("舰船材料不能为非有限数字")
        if amount > 0:
            result[good] = item.value.text
    return dict(sorted(result.items()))


def read_inputs(game: Path) -> dict[str, str]:
    """Re-inventory root and DLC definitions, goods and all script-value files."""
    result = {}
    for path in sorted(game.rglob("*.txt")):
        source = path.relative_to(game).as_posix()
        if source.startswith(("common/", "dlc/")) and _family(source) is not None:
            result[source] = normalized_text(path.read_text(encoding="utf-8-sig"))
    for source in _REQUIRED:
        result[source] = normalized_text((game / source).read_text(encoding="utf-8-sig"))
    return result


def _inventory(inputs: Mapping[str, str]) -> dict[str, Any]:
    if not inputs.keys() >= _REQUIRED:
        raise ValueError("舰船材料缺少国家作用域或公式文档")
    normalized = {source: normalized_text(text) for source, text in sorted(inputs.items())}
    sources = {
        source: hashlib.sha256(text.encode()).hexdigest() for source, text in normalized.items()
    }
    parsed: dict[str, Any] = {}
    goods: dict[str, dict[str, Any]] = {}
    definitions: dict[str, tuple[str, Assignment]] = {}
    helper_count = 0
    for source, text in normalized.items():
        family = _family(source)
        if family is None:
            if source not in _REQUIRED:
                raise ValueError("舰船材料包含未授权来源")
            continue
        parsed[source] = parse_text(text, path=source)
        if parsed[source].errors:
            raise ValueError(f"舰船材料原件解析失败：{source}")
        for item in parsed[source].root.items:
            if not isinstance(item, Assignment):
                raise ValueError("舰船材料定义必须为普通赋值")
            if item.is_variable:
                continue
            if family == "script_values":
                helper_count += item.key == "ship_mod_market_multiplier"
                continue
            if item.op != "=" or item.prefix is not None or not isinstance(item.value, Block):
                raise ValueError("舰船材料或商品定义必须为普通块")
            if family == "goods":
                if item.key in goods:
                    raise ValueError("舰船材料商品定义重复")
                blocked = []
                for key, blocked_value in (
                    ("local", "yes"),
                    ("fixed_price", "yes"),
                    ("tradeable", "no"),
                ):
                    flag = _one(item.value, key)
                    if flag is not None:
                        if not isinstance(flag.value, Scalar) or flag.value.text not in {
                            "yes",
                            "no",
                        }:
                            raise ValueError("舰船材料商品标记无效")
                        if flag.value.text == blocked_value:
                            blocked.append(key)
                goods[item.key] = {"source": source, "ordinary": not blocked}
            else:
                if item.key in definitions:
                    raise ValueError("舰船改装候选定义重复")
                definitions[item.key] = (source, item)
    if not goods or not definitions or helper_count != 1:
        raise ValueError("舰船材料定义/商品缺失或动态helper不唯一")
    raw = {source: text.encode() for source, text in normalized.items()}
    proof = vanilla_inventory._ship_modification_formula_doc(raw)
    if (proof.actor, proof.target, proof.operation, proof.capability) != (
        "country",
        _CONTRACT["target"],
        "score",
        "direct",
    ):
        raise ValueError("舰船ai_weight动态块/国家作用域证据不完整；fixed_point文档不足以授权")
    candidates = {}
    for identity, (source, node) in sorted(definitions.items()):
        assert isinstance(node.value, Block)
        weight = _one(node.value, "ai_weight")
        slot = _one(node.value, "type")
        if (
            slot is None
            or not isinstance(slot.value, Scalar)
            or not _NAME.fullmatch(slot.value.text)
        ):
            raise ValueError("舰船改装缺少精确槽位身份")
        construction, materiel = (
            _goods(node.value, role, goods) for role in ("construction_goods", "materiel_goods")
        )
        required = construction.keys() | materiel.keys()
        field_proof = vanilla_inventory._ship_modification_scope(raw, node, source, proof)
        candidates[identity] = {
            "source": source,
            "line": node.line,
            "definition_sha256": _digest(_ast(node)),
            "slot": slot.value.text,
            "weight_shape": "missing"
            if weight is None
            else "block"
            if isinstance(weight.value, Block)
            else "scalar",
            "weight_line": weight.line if weight is not None else 0,
            "weight_sha256": _digest(_ast(weight)) if weight is not None else None,
            "scope_status": field_proof.capability,
            "scope_evidence": list(field_proof.evidence),
            "construction_goods": construction,
            "materiel_goods": materiel,
            "ordinary_goods": sorted(good for good in required if goods[good]["ordinary"]),
        }
    return _validate(
        {
            "schema": 1,
            "contract": dict(_CONTRACT),
            "sources": sources,
            "goods": goods,
            "candidates": candidates,
        }
    )


def _validate(data: dict[str, Any]) -> dict[str, Any]:
    try:
        if (
            set(data) != {"schema", "contract", "sources", "goods", "candidates"}
            or type(data["schema"]) is not int
            or data["schema"] != 1
            or data["contract"] != _CONTRACT
        ):
            raise ValueError("舰船材料冻结资料schema/角色合同无效")
        sources, goods, candidates = data["sources"], data["goods"], data["candidates"]
        if (
            not all(isinstance(value, dict) and value for value in (sources, goods, candidates))
            or not sources.keys() >= _REQUIRED
        ):
            raise ValueError("舰船材料冻结资料缺少来源或候选")
        for source, digest in sources.items():
            if (
                (_family(source) is None and source not in _REQUIRED)
                or not isinstance(digest, str)
                or not _HASH.fullmatch(digest)
            ):
                raise ValueError("舰船材料冻结来源身份无效")
        for good, row in goods.items():
            if (
                not _NAME.fullmatch(good)
                or set(row) != {"source", "ordinary"}
                or row["source"] not in sources
                or _family(row["source"]) != "goods"
                or type(row["ordinary"]) is not bool
            ):
                raise ValueError("舰船材料冻结商品身份无效")
        locations = set()
        for identity, row in candidates.items():
            if not _NAME.fullmatch(identity) or set(row) != {
                "source",
                "line",
                "definition_sha256",
                "slot",
                "weight_shape",
                "weight_line",
                "weight_sha256",
                "scope_status",
                "scope_evidence",
                "construction_goods",
                "materiel_goods",
                "ordinary_goods",
            }:
                raise ValueError("舰船材料冻结候选身份/键无效")
            if (
                row["source"] not in sources
                or _family(row["source"]) != "ship_modifications"
                or type(row["line"]) is not int
                or row["line"] < 1
                or not _HASH.fullmatch(row["definition_sha256"])
                or not _NAME.fullmatch(row["slot"])
            ):
                raise ValueError("舰船材料冻结候选来源无效")
            location = (row["source"], row["line"])
            if location in locations:
                raise ValueError("舰船材料冻结候选行身份重复")
            locations.add(location)
            shape = row["weight_shape"]
            if shape not in {"missing", "block", "scalar"} or row["scope_status"] not in {
                "direct",
                "pending",
            }:
                raise ValueError("舰船材料冻结字段形态无效")
            if shape == "missing":
                if (
                    row["weight_line"] != 0
                    or row["weight_sha256"] is not None
                    or row["scope_status"] == "direct"
                ):
                    raise ValueError("舰船材料缺省字段不能获得动态许可")
            elif (
                type(row["weight_line"]) is not int
                or row["weight_line"] < row["line"]
                or not isinstance(row["weight_sha256"], str)
                or not _HASH.fullmatch(row["weight_sha256"])
            ):
                raise ValueError("舰船材料冻结字段AST身份无效")
            if row["scope_status"] == "direct" and shape != "block":
                raise ValueError("舰船材料仅授权已证明的动态块")
            evidence = row["scope_evidence"]
            if not isinstance(evidence, list) or not evidence:
                raise ValueError("舰船材料冻结作用域证据缺失")
            for reference in evidence:
                source, line = reference.rsplit(":", 1)
                if source not in sources or not line.isdigit() or int(line) < 1:
                    raise ValueError("舰船材料冻结作用域行证据无效")
            required = set()
            for role in ("construction_goods", "materiel_goods"):
                if not isinstance(row[role], dict):
                    raise ValueError("舰船材料冻结角色必须为商品映射")
                for good, amount in row[role].items():
                    if good not in goods or not _positive(amount):
                        raise ValueError("舰船材料冻结投入必须是已知商品的正数")
                    required.add(good)
            if row["ordinary_goods"] != sorted(
                good for good in required if goods[good]["ordinary"]
            ):
                raise ValueError("舰船材料冻结普通商品集合漂移")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("舰船材料冻结资料结构无效") from exc
    return data


def write_baseline(game: Path) -> Path:
    """Explicitly freeze current native sources; review and pin the new digest."""
    data = _inventory(read_inputs(game))
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(_canonical(data), encoding="utf-8", newline="\n")
    return BASELINE


def load_baseline() -> dict[str, Any]:
    """Validate the pinned offline artifact without reading a game installation."""
    raw = BASELINE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError("舰船材料冻结资料身份漂移，必须独立复核并重新pin")
    data = json.loads(raw)
    if raw.decode("utf-8") != _canonical(data):
        raise ValueError("舰船材料冻结资料不是规范JSON")
    return _validate(data)


def verify_game(game: Path) -> dict[str, Any]:
    """Re-inventory the full source set and compare every AST-derived identity."""
    frozen = load_baseline()
    if _inventory(read_inputs(game)) != frozen:
        raise ValueError("舰船材料当前源集合或AST定义漂移；重pin来源SHA不能替代完整资料复核")
    return frozen


def _parameters(values: Mapping[str, object]) -> dict[str, float]:
    if set(values) != _PARAMETERS:
        raise ValueError("舰船材料参数键无效")
    result = {}
    for key, value in values.items():
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError("舰船材料参数必须是有限数字")
        result[key] = float(value)
    if not result["priority_base"].is_integer() or not 100000 <= result["priority_base"] <= 1000000:
        raise ValueError("舰船材料优先级必须为独立整数段")
    if (
        not -0.75
        <= result["opportunity_price_threshold"]
        < 0
        < result["pressure_price_threshold"]
        <= 0.75
    ):
        raise ValueError("舰船材料价差阈值必须分开低价与高价")
    if (
        not 1 < result["opportunity_multiplier"] <= 1.5
        or not 0.5 <= result["pressure_multiplier"] < result["scarcity_multiplier"] < 1
        or not 0.5 <= result["default_multiplier"] < 1
    ):
        raise ValueError("舰船材料倍率必须有序有界并保持成本方向")
    if result["pressure_multiplier"] + result["default_multiplier"] - 1 < 0.5:
        raise ValueError("舰船材料联合成本超出有界下限")
    return dict(sorted(result.items()))


def load_parameters() -> dict[str, float]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "parameters"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or not isinstance(data["parameters"], dict)
    ):
        raise ValueError("舰船材料参数schema无效")
    return _parameters(data["parameters"])


def derive(
    adapters: Mapping[str, Any],
    baseline: Mapping[str, Any] | None = None,
    *,
    parameters: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Append only declared, proven blocks; preserve native costs and all tails."""
    frozen = load_baseline() if baseline is None else _validate(dict(baseline))
    chosen = load_parameters() if parameters is None else _parameters(parameters)
    if (
        not isinstance(adapters.get("sources"), Mapping)
        or not isinstance(adapters.get("readers"), Mapping)
        or not isinstance(adapters.get("rules"), list)
    ):
        raise ValueError("舰船材料需要现有适配器映射")
    for source, digest in frozen["sources"].items():
        if source in adapters["sources"] and adapters["sources"][source] != digest:
            raise ValueError("舰船材料与现有适配器来源冲突")
    readers: dict[str, Any] = {}
    rules: list[dict[str, Any]] = []
    covered, uncovered = [], []

    def reader(key: str, spec: dict[str, Any]) -> None:
        if key in adapters["readers"] and adapters["readers"][key] != spec:
            raise ValueError("舰船材料reader签名漂移")
        readers[key] = spec

    def rule(
        identity: str,
        row: Mapping[str, Any],
        suffix: str,
        value: float,
        group: str,
        conditions: list[dict[str, Any]],
        why: str,
    ) -> None:
        rules.append(
            {
                "id": f"equipment_{identity}_{suffix}",
                "source": row["source"],
                "field": f"{identity}.ai_weight",
                "domain": "military",
                "operation": "multiply",
                "value": value,
                "priority": int(chosen["priority_base"]) + len(rules),
                "contribution_group": group,
                "conditions": conditions,
                "why": why,
                "counterexample": "仅本项已知材料机会或代价；其他材料未知不代表整体可负担，不按数量计算实际支付，不改变原版market/doctrine/资格/零分/tail；玩家或关闭保持原版",
            }
        )

    for identity, row in sorted(frozen["candidates"].items()):
        goods = row["ordinary_goods"]
        reason = (
            "missing_native_ai_weight"
            if row["weight_shape"] == "missing"
            else "unsupported_scalar_or_unproved_dynamic_block"
            if row["weight_shape"] != "block" or row["scope_status"] != "direct"
            else "no_ordinary_material_goods"
            if not goods
            else None
        )
        if reason:
            uncovered.append({"id": identity, "source": row["source"], "reason": reason})
            continue
        covered.append(
            {
                "id": identity,
                "source": row["source"],
                "field": f"{identity}.ai_weight",
                "goods": list(goods),
            }
        )
        for good in goods:
            for suffix, engine, unit in (
                ("balance", "market_goods_delta", "sell_minus_buy_orders"),
                ("price", "market_goods_pricier", "price_above_base_ratio"),
            ):
                reader(
                    f"country_goods_{good}_{suffix}",
                    {
                        "engine": engine,
                        "scope": "root",
                        "kind": "number",
                        "unit": unit,
                        "path": ["market", f"mg:{good}"],
                    },
                )
            balance, price = f"country_goods_{good}_balance", f"country_goods_{good}_price"
            scarcity = {"fact": balance, "op": "<", "value": 0.0}
            rule(
                identity,
                row,
                f"{good}_opportunity",
                chosen["opportunity_multiplier"],
                "equipment_material_opportunity",
                [
                    {"fact": price, "op": "<=", "value": chosen["opportunity_price_threshold"]},
                    {"fact": balance, "op": ">=", "value": 0.0},
                ],
                f"候选真实正投入{good}已观察低价且不短缺，仅给有限材料机会；不是已建造或整体可负担",
            )
            rule(
                identity,
                row,
                f"{good}_scarcity",
                chosen["scarcity_multiplier"],
                f"equipment_material_pressure_{good}",
                [scarcity],
                f"候选真实正投入{good}已观察市场缺口，增加材料压力；量只作追溯，不估算实际账单",
            )
            rule(
                identity,
                row,
                f"{good}_pressure",
                chosen["pressure_multiplier"],
                f"equipment_material_pressure_{good}",
                [scarcity, {"fact": price, "op": ">", "value": chosen["pressure_price_threshold"]}],
                f"候选真实正投入{good}高价且短缺，仅升档同一材料压力，不与基础短缺重复",
            )
        reader(
            "default",
            {"engine": "in_default", "scope": "root", "kind": "boolean", "unit": "boolean"},
        )
        rule(
            identity,
            row,
            "default",
            chosen["default_multiplier"],
            "equipment_financing_pressure",
            [{"fact": "default", "op": "=", "value": True}],
            "国家已实际违约，提高改装融资机会成本；正常借款不惩罚，不代表实际付款",
        )
    for item in covered:
        selected = [row for row in rules if row["field"] == item["field"]]
        if (
            len(selected) > decision_rules.STATIC_BUDGET["candidates_per_field"]
            or sum(len(row["conditions"]) for row in selected)
            > decision_rules.STATIC_BUDGET["predicates_per_field"]
        ):
            raise ValueError("舰船材料派生超过现有消费者静态预算")
    return {
        "sources": dict(frozen["sources"]),
        "readers": dict(sorted(readers.items())),
        "rules": rules,
        "covered": covered,
        "uncovered": uncovered,
    }
