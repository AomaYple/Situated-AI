"""Two medical mobilization candidates with native formation ROOT and country owner.

Freeze complete original bytes and ASTs, derive ordinary joint-program inputs,
and retain native utility multiplication, monetary costs, eligibility and effects.
No evaluator, lifecycle state, or engine-runtime claim is introduced here.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from . import config, decision_rules
from .model import Assignment, Block, Scalar
from .parser import parse_text
from .textio import normalized_text

if TYPE_CHECKING:
    from pathlib import Path

BASELINE = config.REPO / "research/situated/mobilization-opportunities.json"
BASELINE_SHA256 = "b731aa77f0c58d5123b748978f825b1980572b988afa2e78ff8d23e62f0000eb"
PARAMETERS = config.REPO / "mod/decisions/mobilization_opportunities.toml"
SOURCE = "common/mobilization_options/00_mobilization_option.txt"
_DOC = "common/mobilization_options/mobilization_options.md"
_OWNER = "common/on_actions/00_code_on_actions.txt"
_COUNTRY = "events/tech_events/trench_warfare.txt"
_MODIFIER = "common/modifier_type_definitions/00_modifier_types.txt"
_REQUIRED = frozenset({SOURCE, _DOC, _OWNER, _COUNTRY, _MODIFIER})
_BASKETS = {
    "mobilization_option_first_aid": {"fabric": "1", "liquor": "2"},
    "mobilization_option_field_hospitals": {"opium": "2", "tools": "1"},
}
_RECOVERY = {
    "mobilization_option_first_aid": "0.20",
    "mobilization_option_field_hospitals": "0.40",
}
_CONTRACT = {
    "native_root": "military_formation",
    "actor": "country",
    "actor_path": ["owner"],
    "target": "none",
    "candidate": "static_definition",
    "field": "ai_weight",
    "operation": "multiplicative_score",
    "supported_shape": "block",
    "native_comparison": "ai_weight_times_unit_modifier_ai_value_then_monetary_cost",
    "evidence": "native_documentation_and_exact_script_not_runtime",
}
_PARAMETERS = frozenset(
    {
        "priority_base",
        "war_need_multiplier",
        "scarcity_multiplier",
        "price_pressure_multiplier",
        "default_multiplier",
        "pressure_price_threshold",
    }
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _ast(node: object) -> object:
    if isinstance(node, Scalar):
        return ["scalar", node.text, node.quoted]
    if isinstance(node, Assignment):
        return ["assignment", node.key, node.op, node.prefix, _ast(node.value)]
    if isinstance(node, Block):
        return ["block", [_ast(item) for item in node.items]]
    raise ValueError("动员原件含未知AST节点")


def _one(block: Block, key: str) -> Assignment:
    values = block.all(key)
    if len(values) != 1 or values[0].op != "=" or values[0].prefix is not None:
        raise ValueError(f"动员字段缺失、重复或不是普通赋值：{key}")
    return values[0]


def _node(root: Block, *path: str) -> Assignment:
    current: Assignment | None = None
    for index, key in enumerate(path):
        current = _one(root, key)
        if index < len(path) - 1:
            if not isinstance(current.value, Block):
                raise ValueError("动员证据路径必须经过普通块")
            root = current.value
    if current is None:
        raise ValueError("动员证据路径不能为空")
    return current


def _record(node: Assignment) -> dict[str, Any]:
    return {"line": node.line, "ast": _ast(node), "sha256": _digest(_ast(node))}


def read_inputs(game: Path) -> dict[str, bytes]:
    """Read exact witnesses and the full native mobilization source set."""
    paths = set((game / "common/mobilization_options").rglob("*.txt"))
    paths.update(
        path
        for path in (game / "dlc").rglob("*.txt")
        if path.parent.name == "mobilization_options" and path.parent.parent.name == "common"
    )
    paths.update(game / source for source in _REQUIRED)
    return {path.relative_to(game).as_posix(): path.read_bytes() for path in sorted(paths)}


def _inventory(inputs: Mapping[str, bytes]) -> dict[str, Any]:
    if set(inputs) != _REQUIRED or any(not isinstance(raw, bytes) for raw in inputs.values()):
        raise ValueError("动员原件集合漂移或不是完整原始字节")
    texts = {source: normalized_text(raw.decode("utf-8-sig")) for source, raw in inputs.items()}
    doc = texts[_DOC]
    if not all(
        marker in doc
        for marker in (
            "script value that multiplies the AI value calculation for a mobilization option",
            "the base AI value that is multiplied is set by the ai_value of the unit_modifier",
            "after multiplication, this is compared against the monetary cost",
            "root = military formation",
        )
    ):
        raise ValueError("动员字段局部ROOT/效用/货币比较合同缺失")
    trees = {}
    for source, text in texts.items():
        if source == _DOC:
            continue
        parsed = parse_text(text, path=source)
        if parsed.errors:
            raise ValueError(f"动员原件解析失败：{source}")
        trees[source] = parsed.root
    if "# Root = Military Formation\non_military_formation_created" not in texts[_OWNER]:
        raise ValueError("动员所属国家证据缺少formation ROOT声明")
    owner = _node(trees[_OWNER], "on_military_formation_created", "effect", "if", "limit", "owner")
    expected_owner = parse_text("owner = { has_journal_entry = je_tutorial_create_formation }").root
    if _ast(owner) != _ast(_one(expected_owner, "owner")):
        raise ValueError("动员formation到owner块证据漂移")
    event = trees[_COUNTRY]
    if _ast(_node(event, "trench_warfare.1", "type")) != [
        "assignment",
        "type",
        "=",
        None,
        ["scalar", "country_event", False],
    ]:
        raise ValueError("动员owner国家ROOT证明漂移")
    country = _node(
        event,
        "trench_warfare.1",
        "trigger",
        "any_scope_war",
        "any_scope_front",
        "any_military_formation",
        "owner",
    )
    if (
        not isinstance(country.value, Scalar)
        or country.value.quoted
        or country.value.text != "ROOT"
    ):
        raise ValueError("动员owner必须指向country_event ROOT")
    modifier = _node(trees[_MODIFIER], "unit_recovery_rate_add")
    ai_value = _node(trees[_MODIFIER], "unit_recovery_rate_add", "game_data", "ai_value")
    if (
        not isinstance(ai_value.value, Scalar)
        or ai_value.value.quoted
        or ai_value.value.text != "5000"
    ):
        raise ValueError("动员恢复率原版非零AI效用漂移")
    native = trees[SOURCE]
    definitions = list(native.assignments())
    if len(definitions) != 18 or len({item.key for item in definitions}) != 18:
        raise ValueError("动员18项原版独立分母漂移")
    candidates = {}
    for identity, basket in _BASKETS.items():
        definition = _one(native, identity)
        if not isinstance(definition.value, Block):
            raise ValueError("动员候选必须为普通定义块")
        weight = _node(native, identity, "ai_weight")
        if _ast(weight.value) != [
            "block",
            [["assignment", "value", "=", None, ["scalar", "1", False]]],
        ]:
            raise ValueError("医疗动员原生权重必须是非零常量脚本块")
        upkeep = _node(native, identity, "upkeep_modifier")
        expected = parse_text(
            "x = { "
            + " ".join(f"goods_input_{good}_add = {quantity}" for good, quantity in basket.items())
            + " }"
        ).root
        if _ast(upkeep.value) != _ast(_one(expected, "x").value):
            raise ValueError("医疗动员真实材料/原始系数漂移")
        recovery = _node(native, identity, "unit_modifier")
        expected = parse_text(f"x = {{ unit_recovery_rate_add = {_RECOVERY[identity]} }}").root
        if _ast(recovery.value) != _ast(_one(expected, "x").value):
            raise ValueError("医疗动员原版恢复率漂移")
        if _ast(_node(native, identity, "group").value) != ["scalar", "medic_support", False]:
            raise ValueError("医疗动员候选家庭漂移")
        candidates[identity] = {
            "source": SOURCE,
            "field": f"{identity}.ai_weight",
            "definition": _record(definition),
            "weight": _record(weight),
            "goods": dict(basket),
            "goods_unit": "native_modifier_quantity_coefficient_not_purchase_or_currency",
            "recovery_rate": _RECOVERY[identity],
            "sections": {item.key: _record(item) for item in definition.value.assignments()},
        }
    return {
        "schema": 1,
        "contract": dict(_CONTRACT),
        "sources": {
            source: hashlib.sha256(text.encode()).hexdigest()
            for source, text in sorted(texts.items())
        },
        "originals": {
            source: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": raw.hex()}
            for source, raw in sorted(inputs.items())
        },
        "scope_evidence": {"owner_block": _record(owner), "owner_is_country": _record(country)},
        "utility_evidence": {
            "source": _MODIFIER,
            "modifier": _record(modifier),
            "ai_value": _record(ai_value),
        },
        "candidates": dict(sorted(candidates.items())),
        "native_identities": [item.key for item in definitions],
    }


def _validate(data: dict[str, Any]) -> dict[str, Any]:
    """Reparse all evidence from raw originals, including complete candidate ASTs."""
    try:
        if set(data) != {
            "schema",
            "contract",
            "sources",
            "originals",
            "scope_evidence",
            "utility_evidence",
            "candidates",
            "native_identities",
        }:
            raise ValueError("动员冻结资料schema/键无效")
        if type(data["schema"]) is not int or data["schema"] != 1 or data["contract"] != _CONTRACT:
            raise ValueError("动员冻结上下文合同无效")
        raw = {}
        for source, row in data["originals"].items():
            if set(row) != {"sha256", "bytes"}:
                raise ValueError("动员原文字节合同无效")
            raw[source] = bytes.fromhex(row["bytes"])
            if hashlib.sha256(raw[source]).hexdigest() != row["sha256"]:
                raise ValueError("动员原文字节SHA不一致")
        if _inventory(raw) != data:
            raise ValueError("动员冻结AST/材料/上下文与原文字节不一致")
    except (KeyError, TypeError, AttributeError, UnicodeError) as exc:
        raise ValueError("动员冻结资料结构无效") from exc
    return data


def write_baseline(game: Path) -> Path:
    """Explicitly freeze live originals; pin identity only after independent review."""
    BASELINE.write_text(_canonical(_inventory(read_inputs(game))), encoding="utf-8", newline="\n")
    return BASELINE


def load_baseline() -> dict[str, Any]:
    raw = BASELINE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError("动员冻结资料身份漂移，必须独立复核后重新pin")
    data = json.loads(raw)
    if raw.decode("utf-8") != _canonical(data):
        raise ValueError("动员冻结资料不是规范JSON")
    return _validate(data)


def verify_game(game: Path) -> dict[str, Any]:
    frozen = load_baseline()
    if _inventory(read_inputs(game)) != frozen:
        raise ValueError("动员当前源集合/原文/AST漂移")
    return frozen


def _parameters(values: Mapping[str, object]) -> dict[str, float]:
    if set(values) != _PARAMETERS:
        raise ValueError("动员参数键无效")
    result = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("动员参数必须为有限数字")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("动员参数必须为有限数字")
        result[key] = float(value)
    if not result["priority_base"].is_integer() or not 100000 <= result["priority_base"] <= 1000000:
        raise ValueError("动员优先级必须为独立整数段")
    if not (
        1 < result["war_need_multiplier"] <= 1.5
        and 0.5 <= result["price_pressure_multiplier"] < result["scarcity_multiplier"] < 1
        and 0.5 <= result["default_multiplier"] < 1
        and 0 < result["pressure_price_threshold"] <= 0.75
    ):
        raise ValueError("动员收益/成本参数方向或范围无效")
    return dict(sorted(result.items()))


def load_parameters() -> dict[str, float]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "parameters"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or not isinstance(data["parameters"], dict)
    ):
        raise ValueError("动员参数schema无效")
    return _parameters(data["parameters"])


def reader_specs(candidate: str | None = None) -> dict[str, dict[str, Any]]:
    """Exact formation-to-owner readers shared by derivation and context checks."""
    result: dict[str, dict[str, Any]] = {}
    for key, engine in (("owner_ai", "is_ai"), ("war", "is_at_war"), ("default", "in_default")):
        result[f"mobilization_{key}"] = {
            "engine": engine,
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "path": ["owner"],
        }
    if candidate is not None and candidate not in _BASKETS:
        raise ValueError("医疗动员读取器候选身份未冻结")
    baskets = _BASKETS.values() if candidate is None else (_BASKETS[candidate],)
    for good in sorted({good for basket in baskets for good in basket}):
        for tier, engine, unit in (
            ("balance", "market_goods_delta", "sell_minus_buy_orders"),
            ("price", "market_goods_pricier", "price_above_base_ratio"),
        ):
            result[f"mobilization_{good}_{tier}"] = {
                "engine": engine,
                "scope": "root",
                "kind": "number",
                "unit": unit,
                "path": ["owner", "market", f"mg:{good}"],
            }
    return dict(sorted(result.items()))


def derive(
    adapters: Mapping[str, Any],
    baseline: Mapping[str, Any] | None = None,
    *,
    parameters: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Return source hashes, typed reader specs and ordinary joint contributions.

    Integration must supply native formation context, actor_path=['owner'], and
    permit numeric required-known facts for the candidate's two core balances.
    Missing price/war/default exits only that contribution; missing owner/market
    or either core material balance preserves the entire native candidate.
    """
    frozen = load_baseline() if baseline is None else _validate(dict(baseline))
    chosen = load_parameters() if parameters is None else _parameters(parameters)
    if (
        not isinstance(adapters.get("sources"), Mapping)
        or not isinstance(adapters.get("readers"), Mapping)
        or not isinstance(adapters.get("rules"), list)
    ):
        raise ValueError("动员需要现有适配器映射")
    for source, digest in frozen["sources"].items():
        if source in adapters["sources"] and adapters["sources"][source] != digest:
            raise ValueError("动员与现有适配器来源冲突")
    readers = reader_specs()
    rules: list[dict[str, Any]] = []
    for key, spec in readers.items():
        if key in adapters["readers"] and adapters["readers"][key] != spec:
            raise ValueError("动员reader完整签名漂移")
    for identity, row in frozen["candidates"].items():
        core = ["mobilization_owner_ai", *(f"mobilization_{good}_balance" for good in row["goods"])]

        def rule(
            suffix: str,
            value: float,
            cause: str,
            conditions: list[dict[str, Any]],
            why: str,
            *,
            identity: str = identity,
            row: Mapping[str, Any] = row,
            core: list[str] = core,
        ) -> None:
            rules.append(
                {
                    "id": f"mobilization_{identity.removeprefix('mobilization_option_')}_{suffix}",
                    "source": SOURCE,
                    "field": row["field"],
                    "domain": "military",
                    "operation": "multiply",
                    "value": value,
                    "priority": int(chosen["priority_base"]) + len(rules),
                    "contribution_group": cause,
                    "conditions": conditions,
                    "required_known_facts": core,
                    "why": why,
                    "counterexample": "仅所属国家AI偏好；未知核心局部回退，辅助未知仅退出本项；不推断伤亡、实际采购或货币支出，不改资格/恢复率/真实成本/启停组织士气，不叠加高级医疗收益，不新造冷却或记忆",
                }
            )

        rule(
            "war_need",
            chosen["war_need_multiplier"],
            "mobilization_country_war_need",
            [{"fact": "mobilization_war", "op": "=", "value": True}],
            "所属国家在战争中，仅作医疗动员需求代理；原版各候选非零恢复效用仍由原生评分保留",
        )
        rule(
            "default",
            chosen["default_multiplier"],
            "mobilization_financing_pressure",
            [{"fact": "mobilization_default", "op": "=", "value": True}],
            "所属国家实际违约，新增医疗承诺有独立融资机会成本；正常贷款不扣，不重复扣真实货币支出",
        )
        for good in row["goods"]:
            balance = {"fact": f"mobilization_{good}_balance", "op": "<", "value": 0.0}
            cause = f"mobilization_material_{good}_pressure"
            rule(
                f"{good}_scarcity",
                chosen["scarcity_multiplier"],
                cause,
                [balance],
                f"本候选真实投入{good}的卖单减买单为负，表达独立材料机会成本；原始数量系数{row['goods'][good]}不是采购量或货币",
            )
            rule(
                f"{good}_price_pressure",
                chosen["price_pressure_multiplier"],
                cause,
                [
                    balance,
                    {
                        "fact": f"mobilization_{good}_price",
                        "op": ">",
                        "value": chosen["pressure_price_threshold"],
                    },
                ],
                "同一材料缺口且价格相对基价超过阈值，升档同一原因取强，不重复扣低档",
            )
    for identity in frozen["candidates"]:
        selected = [rule for rule in rules if rule["field"] == f"{identity}.ai_weight"]
        if (
            len(selected) > decision_rules.STATIC_BUDGET["candidates_per_field"]
            or sum(len(rule["conditions"]) for rule in selected)
            > decision_rules.STATIC_BUDGET["predicates_per_field"]
        ):
            raise ValueError("动员派生超过现有消费者静态预算")
    return {
        "sources": dict(frozen["sources"]),
        "readers": dict(sorted(readers.items())),
        "rules": rules,
        "actors": {SOURCE: ["owner"]},
        "covered": [
            {
                "id": identity,
                "source": SOURCE,
                "field": row["field"],
                "goods": dict(row["goods"]),
                "disposition": "new_consumer_integration_no_legacy_identity",
            }
            for identity, row in frozen["candidates"].items()
        ],
        "uncovered": [
            {
                "id": identity,
                "source": SOURCE,
                "reason": "no_reviewed_medical_policy_native_preserved",
            }
            for identity in frozen["native_identities"]
            if identity not in frozen["candidates"]
        ],
    }
