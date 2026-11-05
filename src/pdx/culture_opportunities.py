"""Bounded cultural/religious exposure and exact observed legal transitions.

The complete native religion dictionary is finite. Country aggregate getters
avoid state/pop/world traversal; a low religious acceptance component is not a
count of discriminated Pops or a prediction of future total acceptance.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import config
from .model import Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

PARAMETERS = config.REPO / "mod/decisions/culture_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.14.5/culture-opportunities.json"
SOURCE = "common/laws/00_church_and_state.txt"
LOBBIES = "events/soi_events/00_lobbies_events_04.txt"
ALGERIA = "common/journal_entries/01_algeria.txt"
HIERARCHY = "events/india_events/set_hierarchy_events.txt"
RELIGION_SOURCE = "common/religions/religion.txt"
VALUES = "common/script_values/event_values.txt"
CITIZENSHIP = "common/laws/00_citizenship.txt"
HOMELAND = "events/cultural_homeland_events.txt"
SOURCES = frozenset(
    {SOURCE, LOBBIES, ALGERIA, HIERARCHY, RELIGION_SOURCE, VALUES, CITIZENSHIP, HOMELAND}
)
RELIGIONS = (
    "catholic",
    "protestant",
    "orthodox",
    "oriental_orthodox",
    "sunni",
    "shiite",
    "ibadi",
    "jewish",
    "mahayana",
    "gelugpa",
    "theravada",
    "confucian",
    "hindu",
    "shinto",
    "sikh",
    "animist",
    "atheist",
)
CANDIDATE = "law_freedom_of_conscience"
ORIGIN = "law_state_religion"
VARIANTS = ("law_millet_system", "law_people_of_the_book")
FIELD = f"{CANDIDATE}.ai_enact_weight_modifier"
QUERY_PARAMETER = "culture_query"
READER = "culture_nonstate_religious_exposure"
RULE = "culture_freedom_of_conscience_observed_religious_exposure"
CULTURAL_READER = "culture_owned_nonprimary_acceptance_exposure"
CULTURAL_RULE = "culture_multicultural_observed_ethnostate_exposure"
CULTURAL_FIELD = "law_multicultural.ai_enact_weight_modifier"
CULTURAL_ORIGIN = "law_ethnostate"
CULTURAL_CANDIDATE = "law_multicultural"
CULTURAL_CHANNELS = (
    "country_acceptance_shared_heritage_trait_add",
    "country_acceptance_shared_heritage_trait_group_add",
    "country_acceptance_no_shared_heritage_trait_add",
    "country_acceptance_shared_language_trait_add",
    "country_acceptance_shared_language_trait_group_add",
    "country_acceptance_no_shared_language_trait_add",
    "country_acceptance_shared_tradition_trait_add",
    "country_acceptance_no_shared_tradition_trait_add",
)
CULTURAL_EFFECTS = {
    CULTURAL_ORIGIN: (20, 10, -10, 15, 5, 0, 10, 0),
    CULTURAL_CANDIDATE: (60, 50, 20, 50, 30, 20, 10, 0),
}
# State religion, shared trait, shared group, no shared trait. These exact
# channels are not interchangeable with total cultural/Pop acceptance.
CHANNELS = (
    "country_acceptance_state_religion_add",
    "country_acceptance_shared_religious_trait_add",
    "country_acceptance_shared_religious_trait_group_add",
    "country_acceptance_no_shared_religious_trait_add",
)
EFFECTS = {
    "law_state_religion": (25, 0, -10, -25),
    "law_millet_system": (25, 10, 10, -25),
    "law_people_of_the_book": (25, 5, 5, -25),
    "law_freedom_of_conscience": (20, 15, 5, 0),
    "law_total_separation": (15, 15, 15, 15),
    "law_state_atheism": (15, 0, -5, -10),
}


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "sources", "tuning"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
    ):
        raise ValueError("宗教暴露schema无效")
    if set(data["sources"]) != SOURCES or any(
        not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
        for digest in data["sources"].values()
    ):
        raise ValueError("宗教暴露必须锁定完整原版来源")
    tuning = data["tuning"]
    if set(tuning) != {"observed_religious_need", "observed_cultural_need"} or any(
        type(value) not in {int, float} or not math.isfinite(value) or not 0 < value <= 10
        for value in tuning.values()
    ):
        raise ValueError("宗教暴露偏好须为有界有限数值")
    return data


def _child(block: Block, name: str) -> Block:
    rows = block.all(name)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Block):
        raise ValueError(f"宗教暴露原版缺少唯一完整块：{name}")
    return rows[0].value


def _scalar(block: Block, name: str, value: str) -> int:
    rows = block.all(name)
    if (
        len(rows) != 1
        or rows[0].op != "="
        or not isinstance(rows[0].value, Scalar)
        or rows[0].value.unquoted != value
    ):
        raise ValueError(f"宗教暴露原版标量AST漂移：{name}")
    return rows[0].line


def _shape(block: Block) -> tuple:
    return tuple(
        (row.key, row.op, _shape(row.value) if isinstance(row.value, Block) else row.value.unquoted)
        for row in block.assignments()
        if isinstance(row.value, (Block, Scalar))
    )


def _blocks(block: Block) -> Iterator[Block]:
    yield block
    for row in block.assignments():
        if isinstance(row.value, Block):
            yield from _blocks(row.value)


def _roots(inputs: Mapping[str, str]) -> dict[str, Block]:
    result = {}
    for source, digest in load()["sources"].items():
        text = inputs.get(source)
        if not isinstance(text, str) or hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError(f"宗教暴露完整原版来源漂移：{source}")
        parsed = parse_text(text)
        if parsed.errors:
            raise ValueError(f"宗教暴露完整原版解析失败：{source}")
        result[source] = parsed.root
    return result


def frozen_inputs() -> dict[str, str]:
    data = json.loads(FROZEN.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "evidence", "normalization", "source_hashes", "inputs"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or data["evidence"] != "static_complete_native_sources_not_engine_execution"
        or data["normalization"] != "utf8_without_bom_lf_preserve_whitespace"
        or data["source_hashes"] != load()["sources"]
        or not isinstance(data["inputs"], dict)
        or set(data["inputs"]) != SOURCES
    ):
        raise ValueError("宗教暴露冻结底本合同无效")
    _roots(data["inputs"])
    return data["inputs"]


def verify_inputs(inputs: Mapping[str, str]) -> tuple[str, ...]:
    roots = _roots(inputs)
    refs = []
    religions = roots[RELIGION_SOURCE]
    if tuple(row.key for row in religions.assignments()) != RELIGIONS:
        raise ValueError("宗教暴露有限宗教字典分母漂移")
    for religion in RELIGIONS:
        _child(religions, religion)
    laws = roots[SOURCE]
    if {row.key for row in laws.assignments()} != set(EFFECTS):
        raise ValueError("宗教法律完整候选分母漂移")
    parents = {}
    for law, expected in EFFECTS.items():
        definition = _child(laws, law)
        effects = _child(definition, "modifier")
        for key, value in zip(CHANNELS, expected, strict=True):
            refs.append(f"{SOURCE}:{_scalar(effects, key, str(value))}")
        _child(definition, "ai_enact_weight_modifier")
        if definition.all("parent"):
            _scalar(definition, "parent", ORIGIN)
            parents[law] = ORIGIN
    if set(parents) != set(VARIANTS):
        raise ValueError("宗教原法变体/继承分母漂移")
    # Only this transition is scored. All three non-state categories improve,
    # whereas the state category loses five points and must be excluded.
    if tuple(b - a for a, b in zip(EFFECTS[ORIGIN], EFFECTS[CANDIDATE], strict=True)) != (
        -5,
        15,
        15,
        25,
    ):
        raise ValueError("宗教法律实际转换分量漂移")
    event = _child(roots[LOBBIES], "lobby_events.2")
    _scalar(event, "type", "country_event")
    _scalar(event, "placement", "root")
    trigger = _child(event, "trigger")
    _scalar(_child(trigger, "NOT"), "country_has_state_religion", "rel:atheist")
    target = _child(_child(_child(trigger, "OR"), "any_political_lobby"), "target")
    if _shape(_child(target, "religion_percent_country")) != (
        ("target", "=", "ROOT.religion"),
        ("value", ">", "0"),
    ):
        raise ValueError("宗教人口份额原版国家/宗教参数AST漂移")
    if _shape(_child(target, "country_average_religious_acceptance")) != (
        ("target", "=", "ROOT.religion"),
        ("value", "<", "religious_acceptance_very_low"),
    ):
        raise ValueError("宗教接受原版同国家/同宗教AST漂移")
    refs.extend(
        f"{LOBBIES}:{target.all(key)[0].line}"
        for key in ("religion_percent_country", "country_average_religious_acceptance")
    )
    hierarchy = _child(roots[HIERARCHY], "set_hierarchy_event.1")
    _scalar(hierarchy, "type", "country_event")
    share = _child(_child(_child(hierarchy, "trigger"), "AND"), "religion_percent_country")
    if _shape(share) != (("target", "=", "rel:hindu"), ("value", ">=", "0.50")):
        raise ValueError("宗教人口份额固定宗教参数AST漂移")
    refs.append(f"{HIERARCHY}:{share.all('target')[0].line}")
    complete = _child(_child(roots[ALGERIA], "je_the_algerian_departements"), "complete")
    acceptance = [
        block.all("country_average_religious_acceptance")[0]
        for block in _blocks(complete)
        if block.all("country_average_religious_acceptance")
    ]
    if (
        len(acceptance) != 1
        or not isinstance(acceptance[0].value, Block)
        or _shape(acceptance[0].value)
        != (("target", "=", "rel:sunni"), ("value", ">=", "religious_acceptance_medium"))
    ):
        raise ValueError("宗教接受固定宗教参数AST漂移")
    refs.append(f"{ALGERIA}:{acceptance[0].line}")
    refs.append(f"{VALUES}:{_scalar(roots[VALUES], 'religious_acceptance_very_low', '0')}")
    for law, cultural_expected in CULTURAL_EFFECTS.items():
        definition = _child(roots[CITIZENSHIP], law)
        effects = _child(definition, "modifier")
        _child(definition, "ai_enact_weight_modifier")
        _scalar(effects, "country_acceptance_primary_culture_add", "100")
        for key, value in zip(CULTURAL_CHANNELS, cultural_expected, strict=True):
            refs.append(f"{CITIZENSHIP}:{_scalar(effects, key, str(value))}")
    # Every possible heritage/language category improves; tradition is equal.
    # Thus this transition does not need to guess a culture's trait category.
    changes = tuple(b - a for a, b in zip(*CULTURAL_EFFECTS.values(), strict=True))
    if changes != (40, 40, 30, 35, 25, 20, 0, 0):
        raise ValueError("文化接受转换不能推断未知trait或把恶化分量当改善")
    event = _child(roots[HOMELAND], "cultural_homeland_events.1")
    _scalar(event, "type", "country_event")
    state = _child(_child(event, "trigger"), "any_scope_state")
    cultures = state.all("any_scope_culture")
    if len(cultures) != 2 or not isinstance(cultures[0].value, Block):
        raise ValueError("文化接受本州文化集合原版身份漂移")
    if _shape(cultures[0].value) != (
        ("NOT", "=", (("is_primary_culture_of", "=", "ROOT"),)),
        (
            "PREV",
            "=",
            (
                (
                    "state_average_culture_pop_acceptance",
                    "=",
                    (
                        ("culture", "=", "prev"),
                        ("value", "<", "acceptance_status_5"),
                    ),
                ),
            ),
        ),
    ):
        raise ValueError("文化接受的本国/本州/同一文化PREV绑定漂移")
    refs.append(f"{HOMELAND}:{cultures[0].line}")
    refs.append(f"{VALUES}:{_scalar(roots[VALUES], 'acceptance_status_5', '80')}")
    return tuple(refs)


@dataclass(frozen=True, slots=True)
class ReligiousExposureQuery:
    """At least one observed, substantial non-state religion with low acceptance."""


@dataclass(frozen=True, slots=True)
class CulturalExposureQuery:
    """An actual nonprimary culture in an owned state below native full acceptance."""


@dataclass(frozen=True, slots=True)
class CompiledReligiousExposureQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    local_collections: tuple[str, ...] = ()
    actor: str = "country"
    kind: str = "boolean"
    unknown_policy: str = "any_proven_member=true; no_true_with_missing_observation=unknown; complete_no_exposure=false"
    world_scans: int = 0
    runtime_cost: str = "17 fixed religion identities; at most 51 aggregate getter comparisons; no Pop/state/world traversal; engine timing unmeasured"


def query_from_reader(
    engine: str, parameters: Mapping[str, str]
) -> ReligiousExposureQuery | CulturalExposureQuery:
    if engine == "any_scope_state" and parameters == {QUERY_PARAMETER: "owned_cultural_exposure"}:
        return CulturalExposureQuery()
    if engine != "OR" or parameters != {QUERY_PARAMETER: "nonstate_religious_exposure"}:
        raise ValueError("宗教暴露只接受精确国家OR/固定宗教字典查询")
    return ReligiousExposureQuery()


def render_query(query: ReligiousExposureQuery | CulturalExposureQuery) -> str:
    if type(query) is CulturalExposureQuery:
        return (
            "any_scope_state = { any_scope_culture = { "
            "NOT = { is_primary_culture_of = ROOT } "
            "PREV = { state_average_culture_pop_acceptance = { "
            "culture = prev value < acceptance_status_5 } } } }"
        )
    if type(query) is not ReligiousExposureQuery:
        raise ValueError("宗教暴露只接受精确类型查询")
    rows = [
        "AND = { "
        f"NOT = {{ country_has_state_religion = rel:{religion} }} "
        f"religion_percent_country = {{ target = rel:{religion} value >= 0.1 }} "
        f"country_average_religious_acceptance = {{ target = rel:{religion} value < 0 }} }}"
        for religion in RELIGIONS
    ]
    return "OR = { " + " ".join(rows) + " }"


def required_query_sources(
    query: ReligiousExposureQuery | CulturalExposureQuery,
) -> tuple[str, ...]:
    render_query(query)
    return tuple(sorted(SOURCES))


def compile_query(
    query: ReligiousExposureQuery | CulturalExposureQuery, inputs: Mapping[str, str]
) -> CompiledReligiousExposureQuery:
    if type(query) is CulturalExposureQuery:
        return CompiledReligiousExposureQuery(
            render_query(query),
            verify_inputs(inputs),
            tuple(sorted(load()["sources"].items())),
            local_collections=("owned_states", "state_cultures"),
            runtime_cost="owned-state/actual-state-culture existential short circuit; no world/Pop scan; engine timing unmeasured",
        )
    return CompiledReligiousExposureQuery(
        render_query(query), verify_inputs(inputs), tuple(sorted(load()["sources"].items()))
    )


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    del adapters  # Exact local readers need no inferred aliases or external facts.
    data = load()
    verify_inputs(frozen_inputs())
    readers: dict[str, Any] = {
        READER: {
            "engine": "OR",
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "parameters": {QUERY_PARAMETER: "nonstate_religious_exposure"},
        },
    }
    conditions: list[dict[str, object]] = [{"fact": READER, "op": "=", "value": True}]
    for law, value in ((ORIGIN, True), *((law, False) for law in VARIANTS), (CANDIDATE, False)):
        key = f"culture_current_{law}"
        readers[key] = {
            "engine": "has_law_or_variant",
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "argument": f"law_type:{law}",
        }
        conditions.append({"fact": key, "op": "=", "value": value})
    readers[CULTURAL_READER] = {
        "engine": "any_scope_state",
        "scope": "root",
        "kind": "boolean",
        "unit": "boolean",
        "parameters": {QUERY_PARAMETER: "owned_cultural_exposure"},
    }
    cultural_conditions: list[dict[str, object]] = [
        {"fact": CULTURAL_READER, "op": "=", "value": True},
    ]
    for law, value in ((CULTURAL_ORIGIN, True), (CULTURAL_CANDIDATE, False)):
        key = f"culture_current_{law}"
        readers[key] = {
            "engine": "has_law_or_variant",
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "argument": f"law_type:{law}",
        }
        cultural_conditions.append({"fact": key, "op": "=", "value": value})
    return {
        "sources": dict(data["sources"]),
        "readers": readers,
        "rules": [
            {
                "id": RULE,
                "source": SOURCE,
                "field": FIELD,
                "domain": "political",
                "priority": 80000,
                "operation": "add",
                "value": data["tuning"]["observed_religious_need"],
                "semantic_role": "benefit",
                "contribution_group": "law_observed_religious_exposure",
                "conditions": conditions,
                "why": "真实现行国教法且排除效果不同的两变体，固定完整宗教字典中同一非国教宗教占本国人口至少10%且宗教接受分量低于0；具体候选三非国教分量严格改善，给予有限改革需要，独立保留政治/权威成本",
                "counterexample": "同一宗教/同一本国份额与接受必须共同已知；国教、不同宗教拼接、外国事实、低份额、接受已改善、未知或候选已实施不新增需要；变体不借父法。聚合接受不是受歧视人数、文化总接受、未来SOL或通过率，原版资格、政治阻力、JE尾部与执行不变；无逐Pop/state/world扫描。",
            },
            {
                "id": CULTURAL_RULE,
                "source": CITIZENSHIP,
                "field": CULTURAL_FIELD,
                "domain": "political",
                "priority": 80001,
                "operation": "add",
                "value": data["tuning"]["observed_cultural_need"],
                "semantic_role": "benefit",
                "contribution_group": "law_observed_cultural_exposure",
                "conditions": cultural_conditions,
                "why": "现行民族国家制且本国州存在实际非主体文化接受不足；多元文化对全部非主体heritage/language分量严格改善、tradition不变，给予有界需要，政治和权威成本独立保留",
                "counterexample": "必须是同一本国州内同一非主体文化；外国、主体文化、接受已达80、核心未知和已实施不新增贡献。不是预测总接受、未来工资、忠诚或法律通过；不推广到可能损失其他trait分量的转换，不修改原版资格、效果与执行。",
            },
        ],
        "covered": [
            {"id": CANDIDATE, "source": SOURCE, "field": FIELD},
            {"id": CULTURAL_CANDIDATE, "source": CITIZENSHIP, "field": CULTURAL_FIELD},
        ],
    }
