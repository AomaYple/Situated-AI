"""Root-only treaty proposal tradeoffs, pinned to complete native article sources.

Native proposal_weight is already a multiplier on article inclusion. We retain
its ordered benefits, zeroes and tails and add one bounded joint preference.
Directed transfers have no inferred donor/recipient role. Raw native sources in
the artifact make offline validation self-contained; no game runtime is implied.
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

BASELINE = config.REPO / "research/situated/treaty-opportunities.json"
BASELINE_SHA256 = "00bb19ee08f5f10add0a96118741fa4959d94f1d916cb2f61551fbda04f98ba3"
PARAMETERS = config.REPO / "mod/decisions/treaty_opportunities.toml"
_DOC = "common/treaty_articles/treaty_articles.md"
_INFLUENCE = "common/diplomatic_actions/01_expel_diplomats.txt"
_REQUIRED = frozenset({_DOC, _INFLUENCE})
_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_MUTUAL = frozenset({"alliance", "defensive_pact"})
_MILITARY = _MUTUAL | {"guarantee_independence"}
_REVIEWED = _MILITARY | {
    "ship_transfer",
    "toll_exemption",
    "no_tolls",
    "strait_access",
    "no_strait_closure",
}
_CONTRACT = {
    "actor": "country",
    "target": "none",
    "field": "ai.proposal_weight",
    "native_operation": "proposal_score",
    "writer_operation": "multiply",
    "unit": "multiplier",
    "supported_shape": "block",
    "evidence": "native_documentation_and_exact_script_not_runtime",
}
_PARAMETERS = frozenset(
    {
        "priority_base",
        "defensive_need_multiplier",
        "war_commitment_multiplier",
        "default_multiplier",
        "influence_pressure_multiplier",
        "influence_deficit_multiplier",
    }
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _article_source(source: str) -> bool:
    path = PurePosixPath(source)
    if (
        path.is_absolute()
        or path.as_posix() != source
        or ".." in path.parts
        or "\\" in source
        or ":" in source
        or not source.startswith(("common/", "dlc/"))
    ):
        raise ValueError("条约原件路径无效")
    return (
        len(path.parts) >= 3
        and path.parts[-3:-1] == ("common", "treaty_articles")
        and path.suffix == ".txt"
    )


def _ast(node: object) -> object:
    if isinstance(node, Scalar):
        return ["scalar", node.text, node.quoted]
    if isinstance(node, Assignment):
        return ["assignment", node.key, node.op, node.prefix, _ast(node.value)]
    if isinstance(node, Block):
        return ["block", [_ast(item) for item in node.items]]
    raise ValueError("条约原件含未知AST节点")


def _one(block: Block, key: str) -> Assignment | None:
    values = block.all(key)
    if len(values) > 1 or any(value.op != "=" or value.prefix is not None for value in values):
        raise ValueError(f"条约字段重复或不是普通赋值：{key}")
    return values[0] if values else None


def read_inputs(game: Path) -> dict[str, bytes]:
    """Read every base/DLC article plus exact documentation and getter witness."""
    paths = set((game / "common/treaty_articles").rglob("*.txt"))
    paths.update(
        path
        for path in (game / "dlc").rglob("*.txt")
        if _article_source(path.relative_to(game).as_posix())
    )
    result = {path.relative_to(game).as_posix(): path.read_bytes() for path in sorted(paths)}
    result.update({source: (game / source).read_bytes() for source in _REQUIRED})
    return dict(sorted(result.items()))


def _influence_evidence(text: str) -> dict[str, Any]:
    parsed = parse_text(text, path=_INFLUENCE)
    if parsed.errors:
        raise ValueError("条约影响力读取器原件解析失败")
    definition = _one(parsed.root, "expel_diplomats")
    ai = (
        _one(definition.value, "ai") if definition and isinstance(definition.value, Block) else None
    )
    block = _one(ai.value, "will_propose") if ai and isinstance(ai.value, Block) else None
    witnesses: list[dict[str, Any]] = []

    def visit(current: Block, path: tuple[str, ...]) -> None:
        for item in current.assignments():
            if (
                item.key == "influence"
                and item.op == "<"
                and item.prefix is None
                and isinstance(item.value, Scalar)
                and not item.value.quoted
                and item.value.text == "200"
            ):
                witnesses.append({"path": [*path, item.key], "line": item.line})
            elif item.key in {"AND", "OR", "NOT"} and isinstance(item.value, Block):
                visit(item.value, (*path, item.key))

    if block and isinstance(block.value, Block):
        visit(block.value, ("expel_diplomats", "ai", "will_propose"))
    if len(witnesses) != 1:
        raise ValueError("条约影响力必须有唯一国家ROOT原版消费者；不能借用嵌套目标国")
    return {
        "engine": "influence",
        "scope": "root",
        "kind": "number",
        "unit": "capacity_balance",
        "source": _INFLUENCE,
        **witnesses[0],
    }


def _inventory(inputs: Mapping[str, bytes]) -> dict[str, Any]:
    if not inputs.keys() >= _REQUIRED:
        raise ValueError("条约资料缺少ROOT/共同影响力成本/读取器原件")
    texts: dict[str, str] = {}
    originals = {}
    for source, raw in sorted(inputs.items()):
        if not isinstance(raw, bytes) or (not _article_source(source) and source not in _REQUIRED):
            raise ValueError("条约资料包含未授权来源或不是原始字节")
        texts[source] = normalized_text(raw.decode("utf-8-sig"))
        originals[source] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": raw.hex()}
    doc = texts[_DOC]
    if not all(
        marker in doc
        for marker in (
            "proposal_weight = { script value }",
            "Multiplier on AI score for including an article in a treaty they are composing, root is composing AI country",
            "## cost (default: 0)",
            "How much is deducted from the influence pool of every party to a treaty",
            "containing an article of this type.",
        )
    ):
        raise ValueError("条约ROOT/倍率/每方影响力成本文档合同不完整")
    getter = _influence_evidence(texts[_INFLUENCE])
    candidates = {}
    for source, text in texts.items():
        if not _article_source(source):
            continue
        parsed = parse_text(text, path=source)
        if parsed.errors:
            raise ValueError(f"条约原件解析失败：{source}")
        for definition in parsed.root.items:
            if isinstance(definition, Assignment) and definition.is_variable:
                continue
            if (
                not isinstance(definition, Assignment)
                or definition.op != "="
                or definition.prefix is not None
                or not isinstance(definition.value, Block)
                or not _NAME.fullmatch(definition.key)
                or definition.key in candidates
            ):
                raise ValueError("条约定义必须为唯一普通块")
            kind = _one(definition.value, "kind")
            if (
                not kind
                or not isinstance(kind.value, Scalar)
                or kind.value.text
                not in {
                    "mutual",
                    "directed",
                }
            ):
                raise ValueError("条约缺少明确mutual/directed身份")
            cost = _one(definition.value, "cost")
            literal = (
                "0" if cost is None else cost.value.text if isinstance(cost.value, Scalar) else ""
            )
            if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", literal):
                raise ValueError("条约影响力成本必须为明确非负数字，缺省才使用文档0")
            if not math.isfinite(float(literal)) or (
                cost and isinstance(cost.value, Scalar) and cost.value.quoted
            ):
                raise ValueError("条约影响力成本必须为有限未引号数字")
            ai = _one(definition.value, "ai")
            if ai and not isinstance(ai.value, Block):
                raise ValueError("条约ai必须为普通块")
            weight = (
                _one(ai.value, "proposal_weight") if ai and isinstance(ai.value, Block) else None
            )
            proof = vanilla_inventory._treaty_scope(
                ("ai", "proposal_weight"), dict(inputs), definition, source
            )
            if (proof.actor, proof.target, proof.operation, proof.capability) != (
                "country",
                "none",
                "proposal_score",
                "direct",
            ):
                raise ValueError("条约proposal_weight国家ROOT证据不完整")
            candidates[definition.key] = {
                "source": source,
                "line": definition.line,
                "definition_sha256": _digest(_ast(definition)),
                "kind": kind.value.text,
                "cost": literal,
                "cost_line": cost.line if cost else 0,
                "weight_shape": "missing"
                if weight is None
                else "empty_block"
                if isinstance(weight.value, Block) and not weight.value.items
                else "block"
                if isinstance(weight.value, Block)
                else "scalar",
                "weight_line": weight.line if weight else 0,
                "weight_sha256": _digest(_ast(weight)) if weight else None,
                "scope_evidence": list(proof.evidence),
            }
    if not candidates:
        raise ValueError("条约候选定义缺失")
    return {
        "schema": 1,
        "contract": dict(_CONTRACT),
        "sources": {
            source: hashlib.sha256(text.encode()).hexdigest() for source, text in texts.items()
        },
        "originals": originals,
        "getter_evidence": getter,
        "candidates": dict(sorted(candidates.items())),
    }


def _validate(data: dict[str, Any]) -> dict[str, Any]:
    """Rebuild every metadata field from frozen native bytes, never trust tags."""
    try:
        if set(data) != {
            "schema",
            "contract",
            "sources",
            "originals",
            "getter_evidence",
            "candidates",
        }:
            raise ValueError("条约冻结资料schema/键无效")
        if type(data["schema"]) is not int or data["schema"] != 1 or data["contract"] != _CONTRACT:
            raise ValueError("条约冻结角色合同无效")
        if not isinstance(data["originals"], dict) or not data["originals"]:
            raise ValueError("条约冻结资料缺少原文字节")
        raw = {}
        for source, row in data["originals"].items():
            if set(row) != {"sha256", "bytes"}:
                raise ValueError("条约冻结原文合同无效")
            raw[source] = bytes.fromhex(row["bytes"])
            if hashlib.sha256(raw[source]).hexdigest() != row["sha256"]:
                raise ValueError("条约冻结原文字节SHA不一致")
        if _inventory(raw) != data:
            raise ValueError("条约冻结AST/来源/读取器元数据与原文字节不一致")
    except (KeyError, TypeError, AttributeError, UnicodeError) as exc:
        raise ValueError("条约冻结资料结构无效") from exc
    return data


def write_baseline(game: Path) -> Path:
    """Explicitly freeze source bytes; caller must review and pin the digest."""
    data = _inventory(read_inputs(game))
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(_canonical(data), encoding="utf-8", newline="\n")
    return BASELINE


def load_baseline() -> dict[str, Any]:
    """Identify and re-parse offline frozen sources without an installation."""
    raw = BASELINE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError("条约冻结资料身份漂移，必须独立复核后重新pin")
    data = json.loads(raw)
    if raw.decode("utf-8") != _canonical(data):
        raise ValueError("条约冻结资料不是规范JSON")
    return _validate(data)


def verify_game(game: Path) -> dict[str, Any]:
    """Re-inventory the complete source set, raw bytes and exact native ASTs."""
    frozen = load_baseline()
    if _inventory(read_inputs(game)) != frozen:
        raise ValueError("条约当前源集合/原文/AST漂移")
    return frozen


def _parameters(values: Mapping[str, object]) -> dict[str, float]:
    if set(values) != _PARAMETERS:
        raise ValueError("条约参数键无效")
    result = {}
    for key, value in values.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("条约参数必须为有限数字")
        result[key] = float(value)
    if not result["priority_base"].is_integer() or not 100000 <= result["priority_base"] <= 1000000:
        raise ValueError("条约优先级必须为独立整数段")
    if (
        not 1 < result["defensive_need_multiplier"] <= 1.5
        or not 0.5
        <= result["influence_deficit_multiplier"]
        < result["influence_pressure_multiplier"]
        < 1
        or not all(
            0.5 <= result[key] < 1 for key in ("war_commitment_multiplier", "default_multiplier")
        )
        or sum(
            result[key]
            for key in (
                "influence_deficit_multiplier",
                "war_commitment_multiplier",
                "default_multiplier",
            )
        )
        - 2
        < 0.5
    ):
        raise ValueError("条约收益/成本参数方向或联合边界无效")
    return dict(sorted(result.items()))


def load_parameters() -> dict[str, float]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "parameters"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or not isinstance(data["parameters"], dict)
    ):
        raise ValueError("条约参数schema无效")
    return _parameters(data["parameters"])


def derive(
    adapters: Mapping[str, Any],
    baseline: Mapping[str, Any] | None = None,
    *,
    parameters: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Derive exact reviewed, explicit blocks; unknown observations stay local."""
    frozen = load_baseline() if baseline is None else _validate(dict(baseline))
    chosen = load_parameters() if parameters is None else _parameters(parameters)
    if (
        not isinstance(adapters.get("sources"), Mapping)
        or not isinstance(adapters.get("readers"), Mapping)
        or not isinstance(adapters.get("rules"), list)
    ):
        raise ValueError("条约需要现有适配器映射")
    for source, digest in frozen["sources"].items():
        if source in adapters["sources"] and adapters["sources"][source] != digest:
            raise ValueError("条约与现有适配器来源冲突")
    readers: dict[str, Any] = {}
    rules: list[dict[str, Any]] = []
    covered, uncovered = [], []

    def reader(key: str, engine: str, kind: str, unit: str) -> None:
        spec = {"engine": engine, "scope": "root", "kind": kind, "unit": unit}
        if key in adapters["readers"] and adapters["readers"][key] != spec:
            raise ValueError("条约reader签名漂移")
        readers[key] = spec

    def rule(
        identity: str,
        row: Mapping[str, Any],
        suffix: str,
        value: float,
        cause: str,
        conditions: list[dict[str, Any]],
        why: str,
    ) -> None:
        rules.append(
            {
                "id": f"treaty_{identity}_{suffix}",
                "source": row["source"],
                "field": f"{identity}.ai.proposal_weight",
                "domain": "diplomacy",
                "operation": "multiply",
                "value": value,
                "priority": int(chosen["priority_base"]) + len(rules),
                "contribution_group": cause,
                "conditions": conditions,
                "why": why,
                "counterexample": "只调节提议倾向，不保证被接受/签署/即时参战；原生value/if/add/零分与执行成本保留。ROOT可为授予方或接受方，不推断船舶、海峡或运输受益角色；未知仅退出本分量，玩家或关闭保持原版",
            }
        )

    for identity, row in frozen["candidates"].items():
        reason = (
            "missing_native_proposal_weight"
            if row["weight_shape"] == "missing"
            else "unsupported_scalar_or_empty_weight"
            if row["weight_shape"] != "block"
            else "no_reviewed_article_policy"
            if identity not in _REVIEWED
            else "no_role_safe_new_contribution"
            if float(row["cost"]) == 0
            else None
        )
        if reason:
            uncovered.append({"id": identity, "source": row["source"], "reason": reason})
            continue
        if row["kind"] != ("mutual" if identity in _MUTUAL else "directed"):
            raise ValueError("条约已复核条款kind漂移，不能改变授予/互惠语义")
        covered.append(
            {
                "id": identity,
                "source": row["source"],
                "field": f"{identity}.ai.proposal_weight",
                "cost": row["cost"],
                "kind": row["kind"],
            }
        )
        reader("treaty_influence", "influence", "number", "capacity_balance")
        rule(
            identity,
            row,
            "capacity",
            chosen["influence_pressure_multiplier"],
            "treaty_influence_pressure",
            [{"fact": "treaty_influence", "op": "<", "value": float(row["cost"])}],
            f"原版每方影响力占用{row['cost']}；ROOT当前余额低于本条款精确占用，仅计边际外交容量压力，不增加资格门",
        )
        rule(
            identity,
            row,
            "capacity_deficit",
            chosen["influence_deficit_multiplier"],
            "treaty_influence_pressure",
            [{"fact": "treaty_influence", "op": "<", "value": 0.0}],
            "ROOT影响力已为负，升档同一外交容量压力；与低于占用档去重，不把零余额或未知当赤字",
        )
        if identity in _MUTUAL:
            reader("is_diplomatic_play_target", "is_diplomatic_play_target", "boolean", "boolean")
            reader("war", "is_at_war", "boolean", "boolean")
            rule(
                identity,
                row,
                "defensive_need",
                chosen["defensive_need_multiplier"],
                "treaty_immediate_defensive_need",
                [{"fact": "is_diplomatic_play_target", "op": "=", "value": True}],
                "ROOT正被外交博弈指向，互惠防御合作有有限即时需求；不是已签署、已获援或能赶上当前冲突",
            )
            rule(
                identity,
                row,
                "war_commitment",
                chosen["war_commitment_multiplier"],
                "treaty_existing_war_commitment",
                [{"fact": "war", "op": "=", "value": True}],
                "ROOT已有战争承诺，新增互惠军事约定有独立承诺机会成本；与防御需求共同计入，不以奖励优先屏蔽成本",
            )
        if identity in _MILITARY:
            reader("default", "in_default", "boolean", "boolean")
            rule(
                identity,
                row,
                "default",
                chosen["default_multiplier"],
                "treaty_military_financing_pressure",
                [{"fact": "default", "op": "=", "value": True}],
                "ROOT已实际违约，军事条约新增承诺有融资机会成本；不惩罚正常借款，不据此推断任何一方实际付款",
            )
    for item in covered:
        selected = [rule for rule in rules if rule["field"] == item["field"]]
        if (
            len(selected) > decision_rules.STATIC_BUDGET["candidates_per_field"]
            or sum(len(rule["conditions"]) for rule in selected)
            > decision_rules.STATIC_BUDGET["predicates_per_field"]
        ):
            raise ValueError("条约派生超过现有消费者静态预算")
    return {
        "sources": dict(frozen["sources"]),
        "readers": dict(sorted(readers.items())),
        "rules": rules,
        "covered": covered,
        "uncovered": uncovered,
    }
