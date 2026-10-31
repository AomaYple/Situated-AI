"""Situated AI 的有限处境行动内核。

这个包只负责生成期的事实、状态、行动和仲裁合同。游戏运行期不依赖
Python；``compiler`` 会把通过合同检查的行动降低成有限 PDX 条件块。
"""

from . import audit
from .arbitration import ArbitrationResult, Candidate, choose
from .compiler import (
    SituatedModel,
    compile_policy,
    compile_sources,
    evaluate_policy,
    load_model,
    strategy_overlay,
)
from .schema import ActionCard, EvidenceSpec, EvidenceValue, Relation, StateVector
from .signals import CapacitySignal, CommitmentSignal, NeedSignal, OpportunitySignal, TypedState

__all__ = [
    "ActionCard",
    "ArbitrationResult",
    "Candidate",
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
    "choose",
    "compile_policy",
    "compile_sources",
    "evaluate_policy",
    "load_model",
    "strategy_overlay",
]
