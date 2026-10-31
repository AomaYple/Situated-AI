"""编译无持久状态的国家能力层级与领域需求，保留未知信息边界。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .country_state import CountryPolicy

PREFIX = "sitai_context_"
LAYERS = ("recovery", "expansion", "stable", "foundation")
NEEDS = (
    "fiscal",
    "administrative",
    "political",
    "education",
    "industry",
    "security",
    "reconstruction",
    "overseas",
)
CAPACITIES = ("development", "stable_capacity", "expansion_capacity")
# Optional needs use positive-only parameterized facts. Their evidence flags
# answer whether the need is proven, without making the underlying facts false.
EVIDENCE_NEEDS = ("industry", "reconstruction", "overseas")
VALUES = (
    *CAPACITIES,
    *(f"layer_{name}" for name in LAYERS),
    *(f"need_{name}" for name in NEEDS),
    *(f"evidence_need_{name}" for name in EVIDENCE_NEEDS),
)
NAMES = (*VALUES, *(f"known_{name}" for name in VALUES))


def normalize(data, readers):
    from .country_state import _tree  # noqa: PLC0415

    if not isinstance(data, dict) or set(data) != {"capacities", "needs"}:
        raise ValueError("分层协调必须定义 capacities 和 needs")
    if (
        not isinstance(data["capacities"], dict)
        or not isinstance(data["needs"], dict)
        or set(data["capacities"]) != {"recovery", *CAPACITIES}
        or set(data["needs"]) != set(NEEDS)
    ):
        raise ValueError("分层协调节点缺失或多余")
    normalized: dict[str, dict] = {}
    for section, nodes in data.items():
        normalized[section] = {}
        for name, node in nodes.items():
            if (
                not isinstance(node, dict)
                or set(node) != {"when", "why"}
                or not isinstance(node["why"], str)
                or not node["why"].strip()
            ):
                raise ValueError("分层协调节点必须提供谓词和依据")
            tree = _tree(node["when"], readers)
            if len(tree) > 8 or sum(map(len, tree)) > 32:
                raise ValueError("分层协调超过静态复杂度预算")
            normalized[section][name] = {"when": tree, "why": node["why"]}
    return normalized


def _all(statuses):
    if any(value is False for value in statuses):
        return False
    return None if any(value is None for value in statuses) else True


def _any(statuses):
    if any(value is True for value in statuses):
        return True
    return None if any(value is None for value in statuses) else False


def _tree_status(policy, tree, facts):
    from .country_state import _predicate  # noqa: PLC0415

    clauses = []
    for clause in tree:
        tests: list[bool | None] = []
        for predicate in clause:
            actual = facts.get(predicate["fact"])
            reader = policy.readers[predicate["fact"]]
            if actual is None or (reader.get("argument") and actual is False):
                tests.append(None)
            else:
                tests.append(_predicate(actual, predicate["op"], predicate["value"]))
        clauses.append(_all(tests))
    return _any(clauses)


def evaluate(policy: CountryPolicy, facts, *, is_ai=True):
    """返回三值事实；高档未知只允许已证实的低档，不伪造已知否定。"""
    if not isinstance(facts, Mapping) or type(is_ai) is not bool:
        raise ValueError("协调事实和 is_ai 参数无效")
    result: dict[str, bool | None] = dict.fromkeys(VALUES, False)
    if not policy.enabled or not is_ai:
        return result
    from .country_state import _fact  # noqa: PLC0415

    facts = {key: _fact(facts, key, reader) for key, reader in policy.readers.items()}
    nodes = policy.data["coordination"]
    capacity = {
        name: _tree_status(policy, node["when"], facts)
        for name, node in nodes["capacities"].items()
    }
    recovery = capacity["recovery"]
    result["layer_recovery"] = recovery
    for name in CAPACITIES:
        result[name] = _all([capacity[name], None if recovery is None else not recovery])
    result["layer_expansion"] = result["expansion_capacity"]
    result["layer_stable"] = _all(
        [result["stable_capacity"], result["expansion_capacity"] is not True]
    )
    result["layer_foundation"] = _all(
        [
            result["development"],
            result["expansion_capacity"] is not True,
            result["stable_capacity"] is not True,
        ]
    )
    # 层级表示本次已证实的选择；高档未知不应在消费者优先级链中
    # 拦住已证实的低档。原始 capacity 仍保留 None，不伪造高档能力。
    selected = next((name for name in LAYERS if result["layer_" + name] is True), None)
    if selected is not None:
        result.update({"layer_" + name: name == selected for name in LAYERS})
    for name, node in nodes["needs"].items():
        result[f"need_{name}"] = _tree_status(policy, node["when"], facts)
    for name in EVIDENCE_NEEDS:
        result[f"evidence_need_{name}"] = result[f"need_{name}"] is True
    return result


def evaluate_typed(policy: CountryPolicy, facts, *, is_ai=True):
    """返回与协调结果同一输入上的 K2 类型化状态快照。

    这是参考器到统一状态合同的桥接，不改变既有 ``evaluate`` 的布尔
    兼容接口。未知事实保持 ``EvidenceValue.known=False``，不会被补成
    健康或危机；玩家/禁用路径返回全未知并由消费者回退原版。
    """

    from .situated.schema import EvidenceValue  # noqa: PLC0415
    from .situated.state import derive_typed  # noqa: PLC0415

    if not isinstance(facts, Mapping) or type(is_ai) is not bool:
        raise ValueError("协调事实和 is_ai 参数无效")
    if not policy.enabled or not is_ai:
        return derive_typed({})
    values = {
        key: EvidenceValue(
            spec_id=key,
            value=value,
            known=value is not None,
            provenance="country_coordination",
        )
        for key, value in facts.items()
        if key in policy.readers
    }
    return derive_typed(values)


def triggers(policy: CountryPolicy):
    from .country_state import _predicate_text  # noqa: PLC0415

    if not policy.enabled:
        return ""
    nodes = policy.data["coordination"]
    lines = []

    def join(mode, parts):
        return f"{mode} = {{ {' '.join(parts)} }}"

    def tree_pair(tree):
        true_clauses, false_clauses = [], []
        for clause in tree:
            trues, falses = [], []
            for predicate in clause:
                reader = policy.readers[predicate["fact"]]
                engine = reader["engine"]
                token = _predicate_text(policy, predicate)
                if reader.get("argument"):
                    # 参数式布尔读取器只接受正面证据；缺失资源/变量不充当已知否定。
                    known = f"{engine} = {reader['argument']}"
                elif reader["kind"] == "boolean":
                    known = join("OR", [f"{engine} = yes", f"{engine} = no"])
                else:
                    bounds = [
                        f"{engine} {op} {reader[name]:g}"
                        for name, op in (("min", ">="), ("max", "<="))
                        if name in reader
                    ]
                    # 无界数字仍须有一个可求值的方向，未知数字比较两边均不成立。
                    known = (
                        join("AND", bounds)
                        if bounds
                        else join("OR", [f"{engine} >= 0", f"{engine} < 0"])
                    )
                trues.append(join("AND", [known, token]))
                falses.append(join("AND", [known, f"NOT = {{ {token} }}"]))
            true_clauses.append(join("AND", trues))
            false_clauses.append(join("OR", falses))
        return join("OR", true_clauses), join("AND", false_clauses)

    def emit(name, true, false):
        lines.append(f"{PREFIX}{name} = {{ is_ai = yes {true} }}")
        lines.append(f"{PREFIX}known_{name} = {{ is_ai = yes OR = {{ {true} {false} }} }}")

    def yes(name):
        return f"{PREFIX}{name} = yes"

    def no(name):
        return join("AND", [yes("known_" + name), f"NOT = {{ {yes(name)} }}"])

    for name, node in nodes["capacities"].items():
        true, false = tree_pair(node["when"])
        if name == "recovery":
            emit("layer_recovery", true, false)
        else:
            emit(
                name,
                join("AND", [true, no("layer_recovery")]),
                join("OR", [false, yes("layer_recovery")]),
            )
    layers = (
        ("expansion", "expansion_capacity", ()),
        ("stable", "stable_capacity", ("expansion_capacity",)),
        ("foundation", "development", ("expansion_capacity", "stable_capacity")),
    )
    selected_layers = {
        name: join("AND", [yes(capacity), *(f"NOT = {{ {yes(other)} }}" for other in excluded)])
        for name, capacity, excluded in layers
    }
    for name, capacity, excluded in layers:
        emit(
            "layer_" + name,
            selected_layers[name],
            join(
                "OR",
                [
                    no(capacity),
                    *(yes(other) for other in excluded),
                    *(value for other, value in selected_layers.items() if other != name),
                ],
            ),
        )
    for name, node in nodes["needs"].items():
        emit("need_" + name, *tree_pair(node["when"]))
    for name in EVIDENCE_NEEDS:
        # False means no positive evidence, including an unknown raw need. The
        # flag itself is known within an AI country; no raw negation is inferred.
        lines.append(f"{PREFIX}evidence_need_{name} = {{ is_ai = yes {yes('need_' + name)} }}")
        lines.append(f"{PREFIX}known_evidence_need_{name} = {{ is_ai = yes }}")
    return "\n".join(lines) + "\n"


def contract(policy: CountryPolicy):
    nodes = {
        section: {
            name: {"when": [list(clause) for clause in node["when"]], "why": node["why"]}
            for name, node in entries.items()
        }
        for section, entries in policy.data["coordination"].items()
    }
    return {
        "source": "mod/decisions/country_state.toml",
        "evaluation": "vanilla_consumer_demand",
        "persistent_variables": 0,
        "world_scans": 0,
        "layers": list(LAYERS),
        "capacities": list(CAPACITIES),
        "needs": list(NEEDS),
        "evidence_needs": {
            f"evidence_need_{name}": {
                "raw_signal": f"need_{name}",
                "true_iff": "raw_need_is_true",
                "false_means": "no_positive_evidence",
                "raw_false_inferred": False,
                "known": "ai_country_scope",
            }
            for name in EVIDENCE_NEEDS
        },
        "nodes": nodes,
        "unknown": "core_no_intervention; auxiliary_degrade_to_proven_lower_capacity",
        "stacking": "first_matching_rule_per_field",
        "evidence": "static_check",
        "behavior_verified": False,
        "typed_state": {
            "producer": "pdx.situated.state.derive_typed",
            "unknown": "preserve_and_fallback_vanilla",
            "signals": "capacity_need_opportunity_commitment",
        },
    }
