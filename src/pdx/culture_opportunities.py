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
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import config, religious_channels
from .model import Block, Scalar
from .parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

PARAMETERS = config.REPO / "mod/decisions/culture_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.15.0/culture-opportunities.json"
SOURCE = "common/laws/00_church_and_state.txt"
LOBBIES = "events/soi_events/00_lobbies_events_04.txt"
ALGERIA = "common/journal_entries/01_algeria.txt"
HIERARCHY = "events/india_events/set_hierarchy_events.txt"
RELIGION_SOURCE = "common/religions/religion.txt"
VALUES = "common/script_values/event_values.txt"
CITIZENSHIP = "common/laws/00_citizenship.txt"
HOMELAND = "events/cultural_homeland_events.txt"
SOURCES = frozenset(
    {
        SOURCE,
        LOBBIES,
        ALGERIA,
        HIERARCHY,
        RELIGION_SOURCE,
        VALUES,
        CITIZENSHIP,
        HOMELAND,
        religious_channels.HERITAGE,
        religious_channels.GROUP,
    }
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
VARIANTS = ("law_caesaropapism", "law_millet_system", "law_people_of_the_book")
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
    "law_caesaropapism": (25, 0, -10, -25),
    "law_millet_system": (25, 10, 10, -25),
    "law_people_of_the_book": (25, 5, 5, -25),
    "law_freedom_of_conscience": (20, 15, 5, 0),
    "law_total_separation": (15, 15, 15, 15),
    "law_state_atheism": (15, 0, -5, -10),
}


def proof_dependency_bytes() -> bytes:
    """Fingerprint the independent validator and its exact accepted proof bytes."""
    religious_channels.snapshot()
    return (
        b"\0religious-channel-validator:"
        + Path(religious_channels.__file__).read_bytes()
        + b"\0religious-channel-manifest:"
        + religious_channels.MANIFEST.read_bytes()
    )


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
    if set(tuning) != {
        "observed_religious_need",
        "observed_cultural_need",
        "observed_state_protection_loss",
    } or any(
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
    religious_channels.verify_inputs(inputs)
    refs = [religious_channels.MANIFEST_ID + ":sha256:" + religious_channels.MANIFEST_SHA256]
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
    refs.extend(_verify_atheism_transition(laws))
    refs.extend(_verify_conscience_separation(laws))
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
    complete = _child(roots[ALGERIA], "je_the_algerian_departements")
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


def _verify_atheism_transition(laws: Block) -> tuple[str, ...]:
    """Prove the current identity guard and target invariant, not equal slots.

    All parent definitions are complete-source hash locked by _roots. The
    same-family native numeric consumer additionally proves the country guard;
    neither activation effects nor an unrelated event grant consumer scope.
    """
    origin = _child(laws, "law_state_atheism")
    target = _child(laws, "law_total_separation")
    activation = _child(origin, "on_activate")
    refs = [f"{SOURCE}:{_scalar(activation, 'set_state_religion', 'rel:atheist')}"]
    if _shape(activation) != (
        ("set_state_religion", "=", "rel:atheist"),
        (
            "add_modifier",
            "=",
            (("name", "=", "antireligious_policies"), ("days", "=", "long_modifier_time")),
        ),
        (
            "custom_tooltip",
            "=",
            (
                ("text", "=", "state_atheism_conversion_tt"),
                (
                    "every_scope_state",
                    "=",
                    (
                        ("limit", "=", (("is_incorporated", "=", "yes"),)),
                        (
                            "convert_population",
                            "=",
                            (("target", "=", "rel:atheist"), ("value", "=", "0.1")),
                        ),
                    ),
                ),
            ),
        ),
        ("recalculate_pop_ig_support", "=", "yes"),
    ):
        raise ValueError("国家无神论原版完整激活父结构漂移")
    target_activation = _child(target, "on_activate")
    expected = (
        (
            "if",
            "=",
            (
                ("limit", "=", (("country_has_state_religion", "=", "rel:atheist"),)),
                ("set_state_religion", "=", "root.country_definition.religion"),
            ),
        ),
        (
            "if",
            "=",
            (
                ("limit", "=", (("has_modifier", "=", "antireligious_policies"),)),
                ("remove_modifier", "=", "antireligious_policies"),
            ),
        ),
        ("recalculate_pop_ig_support", "=", "yes"),
    )
    if _shape(target_activation) != expected:
        raise ValueError("无神论到完全分离原版完整激活父结构漂移")
    numeric = _child(_child(laws, CANDIDATE), "ai_enact_weight_modifier")
    proof = (
        (
            "limit",
            "=",
            (
                ("has_journal_entry", "=", "je_shinbutsu_bunri"),
                ("country_has_state_religion", "=", "rel:mahayana"),
            ),
        ),
        ("add", "=", "1000"),
    )
    guards = [
        row
        for row in numeric.all("if")
        if isinstance(row.value, Block) and _shape(row.value) == proof
    ]
    if len(guards) != 1:
        raise ValueError("法律数值消费者国家国教读取完整父分支漂移")
    refs.append(f"{SOURCE}:{guards[0].line}")
    _, dictionary = religious_channels.snapshot()
    if EFFECTS["law_state_atheism"] != (15, 0, -5, -10) or EFFECTS["law_total_separation"] != (
        15,
        15,
        15,
        15,
    ):
        raise ValueError("无神论到完全分离接受分量漂移")
    if any(
        dictionary.category("atheist", religion) != ("state" if religion == "atheist" else "other")
        for religion in RELIGIONS
    ):
        raise ValueError("无神论独占heritage/group分类漂移")
    return tuple(refs)


@dataclass(frozen=True, slots=True)
class ReligiousExposureQuery:
    """At least one observed, substantial non-state religion with low acceptance."""

    mode: str = "nonstate_religious_exposure"


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
    if engine == "OR" and parameters == {QUERY_PARAMETER: "state_religious_protection_exposure"}:
        return ReligiousExposureQuery("state_religious_protection_exposure")
    for mode in (
        "channel_benefit_exposure",
        "shared_group_protection_exposure",
        "atheism_nonstate_exposure",
        "separation_group_other_exposure",
        "stable_nonatheist_identity",
    ):
        if engine == "OR" and parameters == {QUERY_PARAMETER: mode}:
            return ReligiousExposureQuery(mode)
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
    if query.mode == "stable_nonatheist_identity":
        return (
            "OR = { "
            + " ".join(
                f"country_has_state_religion = rel:{religion}"
                for religion in RELIGIONS
                if religion != "atheist"
            )
            + " }"
        )
    if query.mode == "separation_group_other_exposure":
        return religious_channels.exposure(("group", "other"), loss=False)
    if query.mode == "atheism_nonstate_exposure":
        # The current law alone cannot prove the current state religion.
        # Target separation has 15 in every category even after restoration.
        expression = (
            "OR = { AND = { country_has_state_religion = rel:atheist "
            + render_query(ReligiousExposureQuery())
            + " } }"
        )
        from .situated.resources import pdx_metrics  # noqa: PLC0415

        metrics = pdx_metrics(expression)
        if (
            religious_channels.MAX_PREDICATES < 52
            or metrics["assignment_nodes"] > religious_channels.MAX_ASSIGNMENTS
            or metrics["block_nodes"] > religious_channels.MAX_BLOCKS
            or len(expression.encode()) > religious_channels.MAX_BYTES
            or metrics["max_depth"] > religious_channels.MAX_DEPTH
            or metrics["object_scan_sites"]
            or metrics["persistent_write_sites"]
        ):
            raise ValueError("无神论封闭查询超出既有宗教预算")
        return expression
    if query.mode == "channel_benefit_exposure":
        return religious_channels.exposure(("heritage", "other"), loss=False)
    if query.mode == "shared_group_protection_exposure":
        return religious_channels.exposure(("group",), loss=True)
    if query.mode not in {
        "nonstate_religious_exposure",
        "state_religious_protection_exposure",
    }:
        raise ValueError("宗教暴露仅接受两个封闭国家聚合形状")
    if query.mode == "state_religious_protection_exposure":
        rows = [
            "AND = { "
            f"country_has_state_religion = rel:{religion} "
            f"religion_percent_country = {{ target = rel:{religion} value >= 0.1 }} "
            f"country_average_religious_acceptance = {{ target = rel:{religion} value > 0 }} }}"
            for religion in RELIGIONS
        ]
        return "OR = { " + " ".join(rows) + " }"
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
    runtime_cost = (
        "17 fixed religion identities; at most 306 leaf predicates; bounded identity OR; "
        "no Pop/state/world traversal; engine timing unmeasured"
        if isinstance(query, ReligiousExposureQuery)
        and query.mode
        in {
            "channel_benefit_exposure",
            "shared_group_protection_exposure",
            "separation_group_other_exposure",
        }
        else "17 fixed religion identities; at most 52 getter comparisons including atheist identity guard; no Pop/state/world traversal; engine timing unmeasured"
        if isinstance(query, ReligiousExposureQuery) and query.mode == "atheism_nonstate_exposure"
        else "17 fixed religion identities; at most 51 aggregate getter comparisons; no Pop/state/world traversal; engine timing unmeasured"
    )
    return CompiledReligiousExposureQuery(
        render_query(query),
        verify_inputs(inputs),
        tuple(sorted(load()["sources"].items())),
        runtime_cost=runtime_cost,
    )


def _base_derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
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


def derive(adapters: Mapping[str, Any]) -> dict[str, Any]:
    """Add proven exact transitions with separately observed benefit and loss.

    The state category loses protection independently of authority. The common
    ScalarProgram combines the existing movement, authority and crisis terms;
    neither this derivative nor its local query computes a second score.
    """
    data = _base_derive(adapters)
    tuning = load()["tuning"]
    protection = "culture_state_religious_protection_exposure"
    data["readers"][protection] = {
        "engine": "OR",
        "scope": "root",
        "kind": "boolean",
        "unit": "boolean",
        "parameters": {QUERY_PARAMETER: "state_religious_protection_exposure"},
    }
    # Mixed/zero beneficiary categories require a distinct precise trait query.
    # They deliberately do not inherit this all-three-categories admission.
    transitions = (
        (ORIGIN, CANDIDATE),
        ("law_caesaropapism", CANDIDATE),
        (ORIGIN, "law_total_separation"),
        ("law_caesaropapism", "law_total_separation"),
        ("law_millet_system", "law_total_separation"),
        ("law_people_of_the_book", "law_total_separation"),
    )
    for index, (origin, candidate) in enumerate(transitions):
        delta = tuple(b - a for a, b in zip(EFFECTS[origin], EFFECTS[candidate], strict=True))
        if not (delta[0] < 0 and all(value > 0 for value in delta[1:])):
            raise ValueError("宗教转换必须逐通道证明非国教严格改善与国教保护损失")
        current = []
        for law in (ORIGIN, *VARIANTS, candidate):
            key = f"culture_current_{law}"
            data["readers"][key] = {
                "engine": "has_law_or_variant",
                "scope": "root",
                "kind": "boolean",
                "unit": "boolean",
                "argument": f"law_type:{law}",
            }
            current.append({"fact": key, "op": "=", "value": law in (origin, ORIGIN)})
        field = f"{candidate}.ai_enact_weight_modifier"
        if (origin, candidate) != (ORIGIN, CANDIDATE):
            data["rules"].append(
                {
                    "id": f"culture_{origin}_to_{candidate}_observed_exposure",
                    "source": SOURCE,
                    "field": field,
                    "domain": "political",
                    "priority": 80100 + index,
                    "operation": "add",
                    "value": tuning["observed_religious_need"],
                    "semantic_role": "benefit",
                    "contribution_group": "law_observed_religious_exposure",
                    "conditions": [*current, {"fact": READER, "op": "=", "value": True}],
                    "why": "现行法精确识别；同一本国非国教人口至少10%且当前宗教接受低于0，候选三非国教通道均严格改善；有界需要不等于改革通过或未来收益",
                    "counterexample": "混合或不变trait通道、国教、错宗教/外国拼接、接受改善、已改革、核心未知均不新增需要",
                }
            )
        data["rules"].append(
            {
                "id": f"culture_{origin}_to_{candidate}_state_protection_loss",
                "source": SOURCE,
                "field": field,
                "domain": "political",
                "priority": 80200 + index,
                "operation": "add",
                "value": -tuning["observed_state_protection_loss"],
                "semantic_role": "cost",
                "contribution_group": "law_state_religious_protection_loss",
                "conditions": [*current, {"fact": protection, "op": "=", "value": True}],
                "conservative_unknown_facts": [protection],
                "unknown_cost_basis": "已知精确转换确定降低国教接受分量；本国国教人口或正接受暴露未知时保留有限保护损失，只有完整已知无暴露才免除。与权威资源损失是独立机制。",
                "why": "本国当前国教人口至少10%且当前宗教接受为正时，转换降低国教保护；有限设计参数不按接受点数、人口数或未来激进化折算",
                "counterexample": "精确现法未知/已改革不扩展成本；已知无当前国教暴露免除本项；它退出不移除独立非国教需要、权威或危机成本",
            }
        )
    if not any(row["id"] == "law_total_separation" for row in data["covered"]):
        data["covered"].append(
            {
                "id": "law_total_separation",
                "source": SOURCE,
                "field": "law_total_separation.ai_enact_weight_modifier",
            }
        )
    _mixed_transitions(data)
    _atheism_to_separation(data)
    _conscience_to_separation(data)
    return data


def _atheism_to_separation(data: dict[str, Any]) -> None:
    """One closed transition; authority cost remains its existing sole author."""
    reader = "culture_atheism_nonstate_exposure"
    data["readers"][reader] = {
        "engine": "OR",
        "scope": "root",
        "kind": "boolean",
        "unit": "boolean",
        "parameters": {QUERY_PARAMETER: "atheism_nonstate_exposure"},
    }
    current = []
    # The locked group contains no child of state_atheism: the only parents
    # are the three checked state_religion variants. Do not require unrelated
    # law readers to be known just to establish this exact origin.
    for law in ("law_state_atheism", "law_total_separation"):
        key = f"culture_current_{law}"
        data["readers"][key] = {
            "engine": "has_law_or_variant",
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "argument": f"law_type:{law}",
        }
        current.append({"fact": key, "op": "=", "value": law == "law_state_atheism"})
    data["rules"].append(
        {
            "id": "culture_law_state_atheism_to_law_total_separation_observed_exposure",
            "source": SOURCE,
            "field": "law_total_separation.ai_enact_weight_modifier",
            "domain": "political",
            "priority": 80400,
            "operation": "add",
            "value": load()["tuning"]["observed_religious_need"],
            "semantic_role": "benefit",
            "contribution_group": "law_observed_religious_exposure",
            "conditions": [*current, {"fact": reader, "op": "=", "value": True}],
            "why": "精确现行国家无神论且国教明确为atheist；同一本国同一非国教宗教份额至少10%且当前宗教接受低于0；完整字典证明它当前为other(-10)，完全分离所有通道为15，即使恢复国家定义国教也严格改善；只赋予有限需要",
            "counterexample": "其他国教、现法或国教未知、错宗教/外国拼接、低份额、接受非负、已采用不新增需要；atheist分量15到15不伪造国教损失；200权威损失复用既有独立成本，不再次扣除；不预测总接受、人口转换、政治通过或未来收益",
        }
    )


def _mixed_transitions(data: dict[str, Any]) -> None:
    """Two closed mixed/zero pairs, using accepted disjoint channel identity.

    The shared group loss requires a positive observed protection exposure.
    Missing group exposure withdraws only that item; it creates no global cost.
    The existing explicit state-protection uncertainty policy stays local.
    """
    tuning = load()["tuning"]
    benefit = "culture_channel_benefit_exposure"
    group_loss = "culture_shared_group_protection_exposure"
    state_loss = "culture_state_religious_protection_exposure"
    for key, mode in (
        (benefit, "channel_benefit_exposure"),
        (group_loss, "shared_group_protection_exposure"),
    ):
        data["readers"][key] = {
            "engine": "OR",
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "parameters": {QUERY_PARAMETER: mode},
        }
    for index, (origin, expected) in enumerate(
        (
            ("law_millet_system", (-5, 5, -5, 25)),
            ("law_people_of_the_book", (-5, 10, 0, 25)),
        )
    ):
        delta = tuple(b - a for a, b in zip(EFFECTS[origin], EFFECTS[CANDIDATE], strict=True))
        if delta != expected:
            raise ValueError("宗教mixed/zero精确转换四通道漂移")
        current = [
            {"fact": f"culture_current_{law}", "op": "=", "value": law in (ORIGIN, origin)}
            for law in (ORIGIN, *VARIANTS, CANDIDATE)
        ]
        mechanisms = [
            (
                "benefit",
                benefit,
                tuning["observed_religious_need"],
                "law_observed_religious_exposure",
                (),
            ),
            (
                "state_loss",
                state_loss,
                -tuning["observed_state_protection_loss"],
                "law_state_religious_protection_loss",
                (state_loss,),
            ),
        ]
        if origin == "law_millet_system":
            mechanisms.append(
                (
                    "group_loss",
                    group_loss,
                    -tuning["observed_state_protection_loss"],
                    "law_shared_group_religious_protection_loss",
                    (),
                )
            )
        for offset, (mechanism, reader, value, group, conservative) in enumerate(mechanisms):
            rule = {
                "id": f"culture_mixed_{origin}_to_{CANDIDATE}_{mechanism}",
                "source": SOURCE,
                "field": FIELD,
                "domain": "political",
                "priority": 80300 + index * 10 + offset,
                "operation": "add",
                "value": value,
                "semantic_role": "benefit" if mechanism == "benefit" else "cost",
                "contribution_group": group,
                "conditions": [*current, {"fact": reader, "op": "=", "value": True}],
                "why": "精确现法转换；同一本国同一宗教的份额至少10%与接受观察；heritage/other改善需要和state/group保护损失独立有界，不按人口或接受点数折算",
                "counterexample": "group零变化不贡献；group恶化不充当收益；错宗教/外国拼接、候选已采用和核心未知不贡献；暴露退出只撤回对应项，不预测法律采用、未来激进化或总接受",
            }
            if conservative:
                rule["conservative_unknown_facts"] = list(conservative)
                rule["unknown_cost_basis"] = (
                    "已知精确转换降低国教保护；仅本国国教暴露未知保留现有有限成本；现法核心未知不触发。group暴露未知不扩展本项。"
                )
            data["rules"].append(rule)


def _verify_conscience_separation(laws: Block) -> tuple[str, ...]:
    """Reuse the checked separation activation only with unchanged state identity."""
    origin = _child(laws, "law_freedom_of_conscience")
    candidate = _child(laws, "law_total_separation")
    # _verify_atheism_transition independently pins this complete target AST.
    # Equality proves origin has the same conditional restoration branch.
    if _shape(_child(origin, "on_activate")) != _shape(_child(candidate, "on_activate")):
        raise ValueError("信仰自由到完全分离完整激活父结构漂移")
    if tuple(
        b - a
        for a, b in zip(
            EFFECTS["law_freedom_of_conscience"], EFFECTS["law_total_separation"], strict=True
        )
    ) != (-5, 0, 10, 15):
        raise ValueError("信仰自由到完全分离四通道方向漂移")
    return (f"{SOURCE}:{origin.all('on_activate')[0].line}",)


def _conscience_to_separation(data: dict[str, Any]) -> None:
    """One identity-stable mixed/zero transition; no future conversion model."""
    need = "culture_separation_group_other_exposure"
    stable = "culture_stable_nonatheist_identity"
    for key, mode in (
        (need, "separation_group_other_exposure"),
        (stable, "stable_nonatheist_identity"),
    ):
        data["readers"][key] = {
            "engine": "OR",
            "scope": "root",
            "kind": "boolean",
            "unit": "boolean",
            "parameters": {QUERY_PARAMETER: mode},
        }
    core = [
        {"fact": "culture_current_law_freedom_of_conscience", "op": "=", "value": True},
        {"fact": "culture_current_law_total_separation", "op": "=", "value": False},
        {"fact": stable, "op": "=", "value": True},
    ]
    tuning = load()["tuning"]
    for offset, (mechanism, reader, value, group) in enumerate(
        (
            ("benefit", need, tuning["observed_religious_need"], "law_observed_religious_exposure"),
            (
                "state_loss",
                "culture_state_religious_protection_exposure",
                -tuning["observed_state_protection_loss"],
                "law_state_religious_protection_loss",
            ),
        )
    ):
        rule = {
            "id": f"culture_law_freedom_of_conscience_to_law_total_separation_{mechanism}",
            "source": SOURCE,
            "field": "law_total_separation.ai_enact_weight_modifier",
            "domain": "political",
            "priority": 80500 + offset,
            "operation": "add",
            "value": value,
            "semantic_role": "benefit" if mechanism == "benefit" else "cost",
            "contribution_group": group,
            "conditions": [*core, {"fact": reader, "op": "=", "value": True}],
            "why": "精确现行信仰自由且国家国教已知非atheist；两法激活父结构相同且只在atheist时恢复国教，本路径身份不变。group/other低接受需要与state正接受保护损失分别有界；heritage零变化不计收益，原有权威成本保持唯一作者",
            "counterexample": "未知或atheist国教不比较同下标；未登记宗教、错宗教/外国拼接、低份额、heritage零变化、已采用或核心未知不贡献；不预测总接受、改宗、通过率或政治结果",
        }
        if mechanism == "state_loss":
            rule["conservative_unknown_facts"] = [reader]
            rule["unknown_cost_basis"] = (
                "精确现法及非atheist身份已知时确定state分量下降；仅当前state人口/接受暴露未知沿用有限局部保护成本，核心身份未知不触发。"
            )
        data["rules"].append(rule)
