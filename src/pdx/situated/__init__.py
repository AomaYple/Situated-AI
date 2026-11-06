"""Situated AI 的有限处境行动内核。

这个包只负责生成期的事实、状态、行动和仲裁合同。游戏运行期不依赖
Python；``compiler`` 会把通过合同检查的行动降低成有限 PDX 条件块。
"""

import importlib

_TYPE_EXPORTS = {
    "ActionCard": ("schema", "ActionCard"),
    "EvidenceSpec": ("schema", "EvidenceSpec"),
    "EvidenceValue": ("schema", "EvidenceValue"),
    "Relation": ("schema", "Relation"),
    "StateVector": ("schema", "StateVector"),
    "CapacitySignal": ("signals", "CapacitySignal"),
    "CommitmentSignal": ("signals", "CommitmentSignal"),
    "NeedSignal": ("signals", "NeedSignal"),
    "OpportunitySignal": ("signals", "OpportunitySignal"),
    "TypedState": ("signals", "TypedState"),
    "SituatedModel": ("compiler", "SituatedModel"),
    "compile_policy": ("compiler", "compile_policy"),
    "compile_sources": ("compiler", "compile_sources"),
    "evaluate_actions": ("compiler", "evaluate_actions"),
    "evaluate_policy": ("compiler", "evaluate_policy"),
    "load_model": ("compiler", "load_model"),
    "strategy_overlay": ("compiler", "strategy_overlay"),
}


def __getattr__(name: str):
    """Load situated submodules only when requested.

    Eagerly importing the audit/compiler facade while ``pdx.decision_rules`` is
    still initializing creates a real first-import cycle. Lazy resolution keeps
    the public ``from pdx.situated import audit, compiler`` API intact while
    allowing low-level observation modules to be imported in either order.
    """
    if name == "audit":
        value = importlib.import_module(f".{name}", __name__)
    elif name in _TYPE_EXPORTS:
        module_name, attribute = _TYPE_EXPORTS[name]
        value = getattr(importlib.import_module(f".{module_name}", __name__), attribute)
    else:
        raise AttributeError(name)
    globals()[name] = value
    return value


__all__ = [
    "ActionCard",
    "CapacitySignal",
    "CommitmentSignal",
    "EvidenceSpec",
    "EvidenceValue",
    "NeedSignal",
    "OpportunitySignal",
    "Relation",
    "SituatedModel",
    "StateVector",
    "TypedState",
    "audit",
    "compile_policy",
    "compile_sources",
    "evaluate_actions",
    "evaluate_policy",
    "load_model",
    "strategy_overlay",
]
