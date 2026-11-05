"""Actual mass-migration destinations strengthen a specific absorption cause."""

from __future__ import annotations

import hashlib
import math
import tomllib
from typing import TYPE_CHECKING, Any

from . import config
from .model import Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Mapping

PARAMETERS = config.REPO / "mod/decisions/migration_opportunities.toml"
EVIDENCE_SOURCE = "events/paralegal_discrimination_events.txt"
SOURCE = "common/buildings/01_industry.txt"
FIELD = "building_textile_mill.ai_value"
READER = "state_mass_migration_target"


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "sources", "tuning"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["sources"]
        != {EVIDENCE_SOURCE: "681da2be740046fbbf07922d2959098c7e5c21c451ac5dd23973ecfb260b618b"}
        or set(data["tuning"]) != {"absorption_target"}
    ):
        raise ValueError("迁移就业机会schema或原版来源无效")
    value = data["tuning"]["absorption_target"]
    if type(value) not in {int, float} or not math.isfinite(value) or not 1.06 < value <= 1.12:
        raise ValueError("迁移就业升档须保留既有基础且有限")
    return data


def _scalar(block: Block, key: str) -> str:
    rows = block.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Scalar):
        raise ValueError(f"迁移原版精确标量漂移：{key}")
    return rows[0].value.unquoted


def verify_inputs(inputs: Mapping[str, str]) -> tuple[str, ...]:
    text = inputs.get(EVIDENCE_SOURCE)
    if (
        not isinstance(text, str)
        or hashlib.sha256(text.encode()).hexdigest() != load()["sources"][EVIDENCE_SOURCE]
    ):
        raise ValueError("迁移完整原版来源漂移")
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("迁移完整原版解析失败")
    events = parsed.root.all("paralegal_discrimination.1")
    if len(events) != 1 or not isinstance(events[0].value, Block):
        raise ValueError("迁移州事件分母漂移")
    event = events[0].value
    if _scalar(event, "type") != "state_event" or _scalar(event, "placement") != "root":
        raise ValueError("迁移活动必须由真实州ROOT事件证明")
    triggers = event.all("trigger")
    if len(triggers) != 1 or not isinstance(triggers[0].value, Block):
        raise ValueError("迁移州事件trigger漂移")
    if _scalar(triggers[0].value, "is_mass_migration_target") != "yes":
        raise ValueError("迁移真实目标州getter漂移")
    return (f"{EVIDENCE_SOURCE}:{triggers[0].value.all('is_mass_migration_target')[0].line}",)


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    data = load()
    readers = {
        key: adapters["readers"][key]
        for key in ("state_unemployment", "state_owner_clothes_balance")
    }
    readers[READER] = {
        "engine": "is_mass_migration_target",
        "scope": "root",
        "kind": "boolean",
        "unit": "boolean",
    }
    return {
        "sources": dict(data["sources"]),
        "readers": readers,
        "rules": [
            {
                "id": "migration_target_textile_employment_absorption",
                "source": SOURCE,
                "field": FIELD,
                "domain": "economy",
                "priority": 77000,
                "operation": "multiply",
                "value": data["tuning"]["absorption_target"],
                "semantic_role": "benefit",
                "contribution_group": "employment_absorption",
                "conditions": [
                    {"fact": READER, "op": "=", "value": True},
                    {"fact": "state_unemployment", "op": ">=", "value": 0.1},
                    {"fact": "state_owner_clothes_balance", "op": "<", "value": 0},
                ],
                "why": "候选州是原版真实大迁移目标且存在本地失业与真实衣物短缺，将既有纺织就业吸纳同原因升档；不把迁移吸引能力或外国迁移当真实本州活动",
                "counterexample": "未知/取消迁移目标只撤回升档，保留原1.06就业基础；无失业或无需求不因迁入泛奖。岗位来自已证全部PMG最坏组合正劳工量，不预测迁移人数、实际招聘、资格或盈利；真实投入、劳力、财政成本、玩家/关闭和原版执行保留。",
            }
        ],
        "covered": [{"id": "building_textile_mill", "source": SOURCE, "field": FIELD}],
    }
