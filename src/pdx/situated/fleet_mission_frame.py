"""Exact reviewed mission-weight frame; no live fleet or category object.

The compact proof records complete immutable identities of the accepted raw
artifacts. It neither modifies those artifacts nor repeats native inspection.
Current EXE/source verification remains the ordinary strategy-scope pipeline.
"""

from __future__ import annotations

import hashlib
import json

from pdx import config

from . import decision_ir, engine_scope

PROOF_ID = "research/situated/victoria3-1.15.0-fleet-mission-frame.json"
PROOF = config.REPO / PROOF_ID
PROOF_SHA256 = "f07d073d472cba898cc44b4292552c3a7a0d7429c07e4e6e4bd9979d8569097f"


def frozen_context() -> decision_ir.EvaluationContext:
    raw = PROOF.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROOF_SHA256:
        raise ValueError("舰队任务frame证据变化，须独立复核")
    data = json.loads(raw)
    strategy = json.loads(engine_scope.strategy_snapshot())
    if (
        data["schema"] != "situated-reviewed-fleet-mission-frame/1"
        or data["exe_sha256"] != strategy["exe"]["sha256"]
        or data["frame"] != [{"name": "root", "tag": 5, "identity": "actor country+0x18"}]
        or data["definition_scope"] != "no_live_fleet_or_category"
        or data["evaluation"] != "nonempty_resolved_mission_vector_country_root_tag5"
        or data["source"]["path"] != "common/ai_strategies/00_default_strategy.txt"
        or data["field"]
        != "ai_strategy_default.fleet_compositions.secondary_fleet.mission_type_weights.protect_supply"
    ):
        raise ValueError("舰队任务frame偏离精确已审消费者")
    line = raw.decode("utf-8").splitlines().index('  "frame": [') + 2
    return decision_ir.EvaluationContext(
        actor_scope=decision_ir.ContextBinding("root", "country", "actor", PROOF_ID, line),
        evidence=(
            f"{PROOF_ID}:{line}",
            f"{PROOF_ID}:sha256={PROOF_SHA256}",
            f"{PROOF_ID}:consumer=mission_role_consumer:va=0x1416763a0",
            f"{PROOF_ID}:evidence=frozen_reviewed_frame",
            *(f"{row['path']}:sha256={row['sha256']}" for row in data["accepted_artifacts"]),
        ),
    )
