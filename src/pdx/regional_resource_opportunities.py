"""Candidate strategic-region oil/rubber potential through the shared scalar algebra.

This adapter adds one flat opportunity after native opportunity multipliers and
before its small-country zero tail. It never grants colonial eligibility, sums
split-state capacities, predicts extraction or changes state-value scores.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from . import config
from .lexer import LBRACE, RBRACE, tokenize
from .model import Block, Scalar
from .parser import parse_text
from .situated import engine_scope

if TYPE_CHECKING:
    from .decision_rules import Reader
    from .situated import programs
    from .situated.decision_ir import EvaluationContext, WriterDecisionIR

SOURCE = "common/ai_strategies/00_default_strategy.txt"
REGIONS = "common/ai_regional_objectives/00_ai_regional_objectives.txt"
DOC = "common/ai_regional_objectives/ai_regional_objectives.md"
BUILDINGS = "common/buildings/09_misc_resource.txt"
STANCES = "common/ai_strategic_region_stance_types/00_ai_strategic_region_stance_types.txt"
R7 = engine_scope.STRATEGY_MANIFEST_ID
SOURCES = frozenset({SOURCE, REGIONS, DOC, BUILDINGS, STANCES, R7})
FIELD = "ai_strategy_default.strategic_region_stance_type_scores.stance_colonize_region"
ACTION = "colonial_candidate_region_resource_opportunity"
DOMAIN = "economy"
PARAMETERS = config.REPO / "mod/decisions/regional_resource_opportunities.toml"
FROZEN = config.REPO / "research/vanilla-ai/1.15.0/regional-resource-opportunities.json"
FROZEN_SHA256 = "74f54f29abfa27ebfa19ff62d3c7fadfc06718dc4aac035d503c14ac3f49e04e"
QUERY_PARAMETER = "regional_resource_query"
RESOURCE_TECHNOLOGIES = (
    ("building_oil_rig", "pumpjacks"),
    ("building_rubber_plantation", "rubber_mastication"),
)
UNKNOWN_POLICY = (
    "missing_region_or_members=unknown; complete_empty=false; any_known_true=true; "
    "no_true_with_unknown_member=unknown; unknown_technology_exits_only_its_resource; malformed=error"
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load() -> dict[str, Any]:
    data = tomllib.loads(PARAMETERS.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema", "sources", "tuning"}
        or type(data["schema"]) is not int
        or data["schema"] != 1
        or set(data["sources"]) != SOURCES
        or set(data["tuning"]) != {"resource_opportunity"}
    ):
        raise ValueError("区域资源来源/schema/参数身份无效")
    value = data["tuning"]["resource_opportunity"]
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 < value <= 15:
        raise ValueError("区域资源机会须有限且在0到15分之间")
    frozen = FROZEN.read_bytes()
    if hashlib.sha256(frozen).hexdigest() != FROZEN_SHA256:
        raise ValueError("区域资源冻结原始身份漂移")
    if data["sources"] != json.loads(frozen)["source_hashes"]:
        raise ValueError("区域资源配置不能重签原版来源权限")
    return data


def _block(parent: Block, key: str) -> Block:
    rows = parent.all(key)
    if len(rows) != 1 or rows[0].op != "=" or not isinstance(rows[0].value, Block):
        raise ValueError(f"区域资源唯一原版块漂移：{key}")
    return rows[0].value


def _shape(block: Block) -> tuple:
    rows = tuple(
        (row.key, row.op, _shape(row.value) if isinstance(row.value, Block) else row.value.unquoted)
        for row in block.assignments()
        if isinstance(row.value, (Block, Scalar))
    )
    if len(rows) != len(block.items):
        raise ValueError("区域资源原版AST含非赋值项")
    return rows


def _contains_shape(block: Block, expected: tuple) -> bool:
    for row in block.assignments():
        if not isinstance(row.value, (Block, Scalar)):
            raise ValueError("区域资源证据值缺失")
        value = _shape(row.value) if isinstance(row.value, Block) else row.value.unquoted
        if (row.key, row.op, value) == expected:
            return True
        if isinstance(row.value, Block) and _contains_shape(row.value, expected):
            return True
    return False


def _stance(root: Block) -> Block:
    return _block(
        _block(_block(root, "ai_strategy_default"), "strategic_region_stance_type_scores"),
        "stance_colonize_region",
    )


def verify_inputs(inputs: Mapping[str, str]) -> None:
    data = load()
    if set(inputs) != SOURCES or any(
        not isinstance(inputs[key], str) or _digest(inputs[key]) != digest
        for key, digest in data["sources"].items()
    ):
        raise ValueError("区域资源完整原版或R7来源漂移")
    roots = {}
    for key in (SOURCE, REGIONS, BUILDINGS, STANCES):
        parsed = parse_text(inputs[key])
        if parsed.errors:
            raise ValueError("区域资源原版解析失败")
        roots[key] = parsed.root
    if not inputs[DOC].startswith(
        "### root = the AI country\n### scope:target_region = the strategic region the objective applies to\n"
    ):
        raise ValueError("区域资源actor/target_region文档身份漂移")
    stance = _stance(roots[SOURCE])
    branches = stance.all("if")
    if len(branches) != 2 or not all(isinstance(row.value, Block) for row in branches):
        raise ValueError("殖民立场原生机会和最后零分尾部结构漂移")
    first_opportunity = branches[0].value
    if not isinstance(first_opportunity, Block):
        raise ValueError("殖民立场原生机会块缺失")
    limit = _block(first_opportunity, "limit")
    # This exact same-context region/state traversal occurs in a trigger limit.
    # The effect-only every_scope_state examples are not the permission source.
    region_states = (
        "scope:target_region",
        "=",
        (
            (
                "any_scope_state",
                "=",
                (
                    (
                        "owner",
                        "=",
                        (
                            (
                                "OR",
                                "=",
                                (
                                    ("is_country_type", "=", "unrecognized"),
                                    ("is_country_type", "=", "decentralized"),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    if region_states not in _shape(limit):
        raise ValueError("殖民立场trigger内战略区域到州遍历证据漂移")
    state_value = _block(_block(roots[SOURCE], "ai_strategy_default"), "state_value")
    for building, technology in RESOURCE_TECHNOLOGIES:
        trigger = (
            "AND",
            "=",
            (
                ("root", "=", (("has_technology_researched", "=", technology),)),
                (f"num_potential_resources(bt:{building})", ">", "0"),
            ),
        )
        if not _contains_shape(state_value, trigger):
            raise ValueError("州级资源潜力与ROOT技术联合trigger证据漂移")
        unlock = _block(_block(roots[BUILDINGS], building), "unlocking_technologies")
        if (
            len(unlock.items) != 1
            or not isinstance(unlock.items[0], Scalar)
            or unlock.items[0].unquoted != technology
        ):
            raise ValueError("资源建筑实际解锁科技证据漂移")
    r7 = json.loads(inputs[R7])
    context = r7["consumers"]["strategic_region_stance_type_scores"]
    if (
        context["target_scope"] != "scope:target_region=strategic_region;scope:region_score=scalar"
        or context["operation"] != "additive_region_stance_score"
        or context["consumer_va"] != "0x14182a78a"
        or r7["strategy_field_merges"]["strategic_region_stance_type_scores"]["add_va"]
        != "0x141632e86"
    ):
        raise ValueError("区域立场R7消费者/scope/additive合并漂移")


def frozen_inputs() -> dict[str, str]:
    raw = FROZEN.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FROZEN_SHA256:
        raise ValueError("区域资源冻结原始身份漂移")
    data = json.loads(raw)
    if (
        set(data) != {"schema", "evidence", "normalization", "source_hashes", "inputs"}
        or data["schema"] != 1
        or data["evidence"] != "static_complete_native_and_existing_r7_sources_not_engine_execution"
        or data["normalization"] != "utf8_without_bom_lf_preserve_whitespace"
        or data["source_hashes"] != load()["sources"]
    ):
        raise ValueError("区域资源冻结合同漂移")
    verify_inputs(data["inputs"])
    return cast("dict[str, str]", data["inputs"])


@dataclass(frozen=True, slots=True)
class RegionalResourceQuery:
    """One fixed candidate-region existential, with an oil OR rubber opportunity."""


@dataclass(frozen=True, slots=True)
class CompiledRegionalResourceQuery:
    expression: str
    references: tuple[str, ...]
    source_hashes: tuple[tuple[str, str], ...]
    actor: str = "country"
    target: str = "scope:target_region=strategic_region"
    kind: str = "boolean"
    unit: str = "boolean"
    world_scans: int = 0
    local_collections: tuple[str, ...] = ("target_region.any_scope_state",)
    unknown_policy: str = UNKNOWN_POLICY
    runtime_cost: str = (
        "one existential candidate-region state traversal; two fixed resource predicates"
    )


def query_from_reader(engine: str, parameters: Mapping[str, str]) -> RegionalResourceQuery:
    if engine != "scope:target_region" or dict(parameters) != {QUERY_PARAMETER: "oil_or_rubber"}:
        raise ValueError("区域资源查询只接受固定typed target_region/oil_or_rubber签名")
    return RegionalResourceQuery()


def render_query(query: RegionalResourceQuery) -> str:
    if type(query) is not RegionalResourceQuery:
        raise ValueError("区域资源查询类型无效")
    return (
        "scope:target_region = { any_scope_state = { "
        "owner = { OR = { is_country_type = unrecognized is_country_type = decentralized } } "
        "OR = { AND = { root = { has_technology_researched = pumpjacks } "
        '"num_potential_resources(bt:building_oil_rig)" > 0 } '
        "AND = { root = { has_technology_researched = rubber_mastication } "
        '"num_potential_resources(bt:building_rubber_plantation)" > 0 } } } }'
    )


def compile_query(
    query: RegionalResourceQuery, inputs: Mapping[str, str]
) -> CompiledRegionalResourceQuery:
    verify_inputs(inputs)
    return CompiledRegionalResourceQuery(
        render_query(query),
        (
            f"{SOURCE}:5671",
            f"{SOURCE}:1849",
            f"{SOURCE}:1855",
            f"{BUILDINGS}:27",
            f"{BUILDINGS}:96",
            f"{DOC}:1",
            f"{DOC}:2",
            f"{R7}:consumers.strategic_region_stance_type_scores",
        ),
        tuple(sorted(load()["sources"].items())),
    )


def required_query_sources(query: RegionalResourceQuery) -> tuple[str, ...]:
    render_query(query)
    return tuple(sorted(SOURCES))


def _boolean(value: object) -> Literal[True, False, None]:
    if value is not None and type(value) is not bool:
        raise ValueError("区域资源技术观测须布尔或未知")
    return value


def observe_query(
    query: RegionalResourceQuery, actor: Mapping[str, Any] | None, region: Mapping[str, Any] | None
) -> Literal[True, False, None]:
    from .situated.expressions import truth_all, truth_any  # noqa: PLC0415

    render_query(query)
    if actor is None or region is None:
        return None
    if not isinstance(actor, Mapping) or not isinstance(region, Mapping):
        raise ValueError("区域资源actor/region须类型化对象")
    states = region.get("states")
    if states is None:
        return None
    if not isinstance(states, (list, tuple)):
        raise ValueError("候选区域州集合须完整列表或未知")
    technologies = actor.get("technologies")
    if technologies is not None and not isinstance(technologies, Mapping):
        raise ValueError("ROOT科技观测须映射或未知")
    results: list[Literal[True, False, None]] = []
    for state in states:
        if state is None:
            results.append(None)
            continue
        if not isinstance(state, Mapping):
            raise ValueError("候选区域州成员须对象或未知")
        owner = state.get("owner")
        if owner is not None and not isinstance(owner, Mapping):
            raise ValueError("候选州owner须对象或未知")
        owner_type = None if owner is None else owner.get("country_type")
        if owner_type is not None and not isinstance(owner_type, str):
            raise ValueError("候选州owner国家类型须标识符")
        eligible = None if owner_type is None else owner_type in {"unrecognized", "decentralized"}
        resources = state.get("potential_resources")
        if resources is not None and not isinstance(resources, Mapping):
            raise ValueError("州资源潜力须映射或未知")
        choices = []
        for building, technology in RESOURCE_TECHNOLOGIES:
            tech = _boolean(None if technologies is None else technologies.get(technology))
            amount = None if resources is None else resources.get(building)
            if amount is not None and (
                type(amount) not in {int, float} or not math.isfinite(amount) or amount < 0
            ):
                raise ValueError("州资源潜力须有限非负值或未知")
            choices.append(truth_all((tech, None if amount is None else amount > 0)))
        results.append(truth_all((eligible, truth_any(tuple(choices)))))
    return truth_any(tuple(results))


@dataclass(frozen=True, slots=True)
class RegionalResourceProgram:
    scalar: programs.ScalarProgram
    source: str = SOURCE
    field: str = FIELD
    actor: str = "root"
    target: str = "target_region"
    unit: str = "region_stance_score"
    insertion: str = "native_first_opportunity_if_end_before_small_country_zero_tail"

    @property
    def writer_id(self) -> str:
        return ACTION

    @property
    def definition(self) -> str:
        return ACTION

    @property
    def consumer_id(self) -> str:
        return "regional_resource:stance_colonize_region"

    @property
    def field_path(self) -> tuple[str, ...]:
        return tuple(self.field.split("."))

    def validate(self) -> None:
        if self != compile_program():
            raise ValueError("区域资源程序身份/参数/消费者漂移")

    def evaluation_context(self) -> EvaluationContext:
        from .situated.decision_ir import ContextBinding, EvaluationContext  # noqa: PLC0415

        return EvaluationContext(
            actor_scope=ContextBinding("root", "country", "actor", R7, 323),
            targets=(ContextBinding("target_region", "strategic_region", "target", R7, 324),),
            auxiliary_scopes=(ContextBinding("region_score", "scalar", "auxiliary", R7, 324),),
            evidence=(f"{R7}:323", f"{R7}:324", f"{DOC}:1", f"{DOC}:2", f"{SOURCE}:5671"),
        )

    def readers(self) -> tuple[Reader, ...]:
        from .decision_rules import Reader  # noqa: PLC0415

        return (
            Reader(
                "regional_resource_opportunity",
                "scope:target_region",
                "root",
                "boolean",
                "boolean",
                parameters=((QUERY_PARAMETER, "oil_or_rubber"),),
            ),
        )

    def reader_bindings(self) -> tuple[tuple[str, str, str, str], ...]:
        return (("regional_resource_opportunity", "root", "country", "actor"),)

    def predicate_ports(self):
        from .decision_rules import Predicate  # noqa: PLC0415
        from .situated import program_ports  # noqa: PLC0415

        proof = tuple(f"{key}:sha256={value}" for key, value in sorted(load()["sources"].items()))
        return program_ports.bind(
            scalar=self.scalar,
            source=self.source,
            definition=self.definition,
            context=self.evaluation_context(),
            readers=self.readers(),
            reader_bindings=self.reader_bindings(),
            predicates={ACTION: (Predicate("regional_resource_opportunity", "=", True),)},
            guard_roles={ACTION: "benefit"},
            source_sha256=hashlib.sha256(
                PARAMETERS.read_bytes() + b"\0generator:" + Path(__file__).read_bytes()
            ).hexdigest(),
            source_proofs=proof,
            domain=DOMAIN,
        )

    def writer_ir(self) -> WriterDecisionIR:
        from .situated.decision_ir import WriterDecisionIR  # noqa: PLC0415

        self.validate()
        writer = WriterDecisionIR(
            writer_id=self.writer_id,
            kind="regional_resource_program",
            source=self.source,
            definition=self.definition,
            consumer_id=self.consumer_id,
            field=self.field,
            actor="root",
            target="target_region",
            operation="add",
            vanilla_tail="preserve",
            owner="regional_resource_opportunities",
            regional_resource_program=self,
            evaluation_context=self.evaluation_context(),
            reader_context_bindings=self.reader_bindings(),
        )

        return replace(writer, port_contributions=self.predicate_ports().contributions(writer))

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            **consumer_catalog(),
            "definition": self.definition,
            "consumer_id": self.consumer_id,
            "scalar": asdict(self.scalar),
            "readers": [asdict(r) for r in self.readers()],
            "reader_context_bindings": [list(row) for row in self.reader_bindings()],
            "predicate_ports": self.predicate_ports().as_dict(),
        }

    def evaluate(
        self,
        values: Mapping[str, Any],
        *,
        is_ai: bool,
        enabled: bool = True,
        native_eligible: bool | None = True,
    ) -> float:
        from .situated import programs  # noqa: PLC0415

        self.validate()
        if not is_ai or not enabled or native_eligible is not True:
            return 0.0
        guard = values.get("regional_resource_opportunity")
        _boolean(guard)
        return programs.evaluate_scalar(
            self.scalar, self.predicate_ports().evaluate({"regional_resource_opportunity": guard})
        )


def compile_program() -> RegionalResourceProgram:
    from .situated import programs  # noqa: PLC0415

    value = load()["tuning"]["resource_opportunity"]
    return RegionalResourceProgram(
        programs.ScalarProgram(
            ACTION,
            "add",
            0.0,
            0.0,
            value,
            (
                programs.ScalarGroup(
                    "candidate_region_accessible_resource",
                    (programs.ScalarTerm(ACTION, ACTION, value),),
                ),
            ),
        )
    )


def render(program: RegionalResourceProgram) -> str:
    from .situated import programs  # noqa: PLC0415

    program.validate()
    return (
        "\n# SITAI BEGIN regional_resource_opportunity\n"
        f"# ACTION {ACTION} [{DOMAIN}]; candidate region resource potential\n"
        + programs.render_scalar(
            program.scalar,
            program.predicate_ports().render(),
            ai_guard="exists = ROOT ROOT = { is_ai = yes } exists = scope:target_region",
            style="cards",
            domain=DOMAIN,
        )
        + "# SITAI END regional_resource_opportunity\n"
    )


def _closing_offset(text: str, line: int) -> int:
    tokens = tokenize(text)
    candidates = [i for i, token in enumerate(tokens) if token.line == line and token.value == "if"]
    if len(candidates) != 1 or tokens[candidates[0] + 2].kind != LBRACE:
        raise ValueError("区域机会if精确物理位置不唯一")
    starts = [0]
    for fragment in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(fragment))
    depth = 0
    for token in tokens[candidates[0] + 2 :]:
        depth += token.kind == LBRACE
        depth -= token.kind == RBRACE
        if depth == 0:
            return starts[token.line - 1] + token.col - 1
    raise ValueError("区域机会物理块未闭合")


def patch(
    inputs: Mapping[str, str],
    *,
    overlays: Mapping[str, str] | None = None,
    enabled_domains: frozenset[str] = frozenset({DOMAIN}),
    consumer_program: RegionalResourceProgram | None = None,
) -> dict[str, str]:
    verify_inputs(inputs)
    if DOMAIN not in enabled_domains:
        return {}
    program = compile_program() if consumer_program is None else consumer_program
    program.validate()
    text = (overlays or {}).get(SOURCE, inputs[SOURCE])
    if "SITAI BEGIN regional_resource_opportunity" in text:
        raise ValueError("区域资源物理writer已存在，拒绝重复作者")
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("区域资源overlay解析失败")
    stance = _stance(parsed.root)
    original = _stance(parse_text(inputs[SOURCE]).root)
    if _shape(stance) != _shape(original):
        raise ValueError("殖民立场原完整父结构已有其他作者")
    offset = _closing_offset(text, stance.all("if")[0].line)
    return {SOURCE: text[:offset] + render(program) + text[offset:]}


def consumer_catalog() -> dict[str, Any]:
    program = compile_program()
    return {
        "source": SOURCE,
        "field": FIELD,
        "actor": "root",
        "target": "target_region",
        "unit": "region_stance_score",
        "operation": "add",
        "domain": DOMAIN,
        "writer_id": ACTION,
        "evaluation_context": program.evaluation_context().as_dict(),
        "new_world_scans": 0,
        "insertion": program.insertion,
        "native_tail": "preserve",
        "source_hashes": load()["sources"],
        "query_engine": "scope:target_region",
        "query_parameters": {QUERY_PARAMETER: "oil_or_rubber"},
        "query_unknown_policy": UNKNOWN_POLICY,
    }
