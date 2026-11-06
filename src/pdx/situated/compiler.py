"""统一的处境行动编译器。

显式行动和规则行动通过各自的类型化输入适配，共用 programs 的标量
贡献、分档选择、条件效果和消费者末端限幅；原版作用域及精确迁移合同
仍由各自适配器保护，不据此声称旧规则具备未声明的业务语义。运行期没有
Python 服务、世界扫描或新增的无界状态。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from .. import (  # noqa: TID252
    building_defaults,
    config,
    decision_adapters,
    decision_interfaces,
    decision_rules,
    negotiation_context,
)
from ..model import Block  # noqa: TID252
from ..parser import parse_text  # noqa: TID252
from . import (
    action_instances,
    bindings,
    commitment,
    decision_ir,
    domain_coverage,
    engine_scope,
    families,
    ir,
    joint_chain_contract,
    layers,
    migration_baseline,
    opportunity,
    ports,
    programs,
    relations,
    resources,
    state,
    support_signals,
    vanilla_inventory,
)
from . import actions as action_source
from . import evidence as evidence_source
from . import goals as goal_source
from .contracts import contract
from .expressions import Truth, truth_all, truth_any, truth_not
from .schema import ActionCard, ConsumerContract, CostPredicate, EvidenceSpec, Relation

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .decision_ir import ConsumerIRBundle

REPO = Path(__file__).resolve().parents[3]
DECISIONS = REPO / "mod" / "decisions"
FACTS = DECISIONS / "facts.toml"
ACTIONS = DECISIONS / "actions.toml"
LAYERS = DECISIONS / "action_layers.toml"
BINDINGS = DECISIONS / "action_bindings.toml"
BASELINE = REPO / "research" / "vanilla-ai" / "1.15.0" / "00_default_strategy.txt"
_LAW_DOC = REPO / "research/situated/victoria3-1.15.0-law-enact-context.md"
_LAW_DOC_MANIFEST = REPO / "research/vanilla-ai/1.15.0/law-document-context.json"
_LAW_DOC_SHA256 = "706098c2cb35770cbe477c84620940b716e60d8708f30f7ae72d46ed1e2091d8"
_LAW_MIRROR_SHA256 = "034ed06d19b2bd6fb8070bfbb95f6e768aaff36a162172147d80f9023f208076"
_LAW_NATIVE_SHA256 = "2e172974c75e5a544777f0a21099019043ca0164d499927786e10572b8956a0c"
SUPPORTING_SOURCES = (
    "capacities.toml",
    "pressures.toml",
    "opportunities.toml",
    "commitments.toml",
    "goals.toml",
    "relations.toml",
    "consumers.toml",
    "localization.toml",
    "action_families.toml",
    "action_layers.toml",
    "action_bindings.toml",
    "domain_actions.toml",
    "domain_ports.toml",
)


def evaluation_contexts(text: str) -> dict[str, decision_ir.EvaluationContext]:
    """Observe exact field-local vanilla comments without changing writer IDs."""
    source = "common/ai_strategies/00_default_strategy.txt"
    # name, engine type, semantic role, exact documentary statement
    common = ("root", "country", "actor", "root = country")
    specs = {
        "subject_value": (
            (
                "root",
                "country",
                "actor",
                "root is the AI doing the evaluation, scope:target_country is prospective subject",
            ),
            (
                "target_country",
                "country",
                "target",
                "root is the AI doing the evaluation, scope:target_country is prospective subject",
            ),
        ),
        "become_subject_value": (
            (
                "root",
                "country",
                "actor",
                "root is the AI doing the evaluation, scope:overlord is prospective overlord",
            ),
            (
                "overlord",
                "country",
                "target",
                "root is the AI doing the evaluation, scope:overlord is prospective overlord",
            ),
        ),
        "interest_group_government_weight": (
            common,
            ("interest_group", "interest_group", "candidate", "scope:interest_group = IG"),
        ),
        "negotiation_chance": (
            common,
            (
                "interest_group",
                "interest_group",
                "candidate",
                "scope:interest_group = IG to negotiate with",
            ),
            ("law", "law", "auxiliary", "scope:law = law type being enacted"),
            (
                "amenability",
                "scalar",
                "auxiliary",
                "scope:amenability = IG amenability to negotiation divided by MAX_AMENABILITY (ie, if MAX_AMENABILITY is 100 and IG amenability is 50, this value will be 0.5)",
            ),
            (
                "advance_chance",
                "scalar",
                "auxiliary",
                "scope:advance_chance = Chance to advance law enactment",
            ),
            (
                "stall_chance",
                "scalar",
                "auxiliary",
                "scope:stall_chance = Chance for law enactment to stall",
            ),
        ),
        "state_value": (
            common,
            ("target_state", "state", "target", "scope:target_state = state"),
            ("target_country", "country", "auxiliary", "scope:target_country = state owner"),
        ),
        "treaty_port_value": (
            common,
            ("target_state", "state", "target", "scope:target_state = state"),
            ("target_country", "country", "auxiliary", "scope:target_country = state owner"),
        ),
        "combat_unit_group_weights": (
            common,
            (
                "military_formation",
                "military_formation",
                "auxiliary",
                "scope:military_formation = military formation",
            ),
        ),
        "conscript_battalion_ratio": (
            common,
            (
                "military_formation",
                "military_formation",
                "auxiliary",
                "scope:military_formation = military formation",
            ),
        ),
    }
    parsed = parse_text(text)
    if parsed.errors:
        raise ValueError("求值上下文默认策略底本无法解析")
    definitions = [item for item in parsed.root.assignments() if item.key == "ai_strategy_default"]
    if len(definitions) != 1:
        return {
            field: decision_ir.EvaluationContext(status="ambiguous" if definitions else "unknown")
            for field in specs
        }
    if (
        not isinstance(definitions[0].value, Block)
        or definitions[0].op != "="
        or definitions[0].prefix is not None
    ):
        return {field: decision_ir.EvaluationContext(status="unknown") for field in specs}
    result = {}
    lines = text.splitlines()
    for field, expected in specs.items():
        fields = [item for item in definitions[0].value.assignments() if item.key == field]
        if len(fields) != 1:
            result[field] = decision_ir.EvaluationContext(
                status="ambiguous" if fields else "unknown"
            )
            continue
        if fields[0].op != "=" or fields[0].prefix is not None:
            result[field] = decision_ir.EvaluationContext(status="unknown")
            continue
        field_line = lines[fields[0].line - 1].strip()
        if re.match(rf"{re.escape(field)}\s*=", field_line) is None:
            # A same-line preceding assignment has no reliable field-local
            # comment boundary; never borrow the previous field's evidence.
            result[field] = decision_ir.EvaluationContext(status="unknown")
            continue
        comments: dict[str, list[int]] = {}
        for index in range(fields[0].line - 2, definitions[0].line - 1, -1):
            line = lines[index].strip()
            if line and not line.startswith("#"):
                break
            if line.startswith("#"):
                comments.setdefault(line[1:].strip(), []).append(index + 1)
        expected_markers = {marker for *_, marker in expected}
        contradictory = any(
            re.search(
                r"\broot\s*(?:=|is\b)|\bscope\s*:\s*[a-z][a-z0-9_]*\s*(?:=|is\b)",
                marker,
                re.IGNORECASE,
            )
            and marker not in expected_markers
            for marker in comments
        )
        if contradictory:
            result[field] = decision_ir.EvaluationContext(status="unknown")
            continue
        if any(len(comments.get(marker, ())) != 1 for *_, marker in expected):
            result[field] = decision_ir.EvaluationContext(status="unknown")
            continue
        bindings = tuple(
            decision_ir.ContextBinding(name, kind, role, source, comments[marker][0])
            for name, kind, role, marker in expected
        )
        result[field] = decision_ir.EvaluationContext(
            actor_scope=bindings[0],
            targets=tuple(b for b in bindings[1:] if b.role in {"target", "candidate"}),
            auxiliary_scopes=tuple(b for b in bindings[1:] if b.role == "auxiliary"),
            evidence=tuple(sorted({f"{b.source}:{b.line}" for b in bindings})),
        )
    # Only this documented map projects its parent's country/formation context
    # to ordinary, unique numeric child blocks. Other maps remain independent.
    parent = definitions[0].value.all("combat_unit_group_weights")
    if len(parent) == 1 and isinstance(parent[0].value, Block):
        context = result["combat_unit_group_weights"]
        for child in parent[0].value.assignments():
            field = f"combat_unit_group_weights.{child.key}"
            siblings = parent[0].value.all(child.key)
            result[field] = (
                decision_ir.EvaluationContext(status="ambiguous")
                if len(siblings) != 1
                else context
                if child.op == "=" and child.prefix is None and isinstance(child.value, Block)
                else decision_ir.EvaluationContext(status="unknown")
            )
    result["negotiation_chance"] = negotiation_context.evaluation_context(text)
    return result


def law_evaluation_context(text: str) -> decision_ir.EvaluationContext:
    """The enact-weight README proves country/law, never ai_will_do or a getter."""
    lines = text.splitlines()
    heading = "# Documentation for ai_enact_weight_modifier"
    statement = "Root scope is AI country, scope:law contains the relevant law for that country"
    headings = [i for i, line in enumerate(lines) if line.strip() == heading]
    statements = [i for i, line in enumerate(lines) if line.strip() == statement]
    example = [i for i, line in enumerate(lines) if line.strip() == "# Example"]
    if len(headings) != 1 or len(statements) != 1 or len(example) != 1:
        return decision_ir.EvaluationContext(status="unknown")
    start, location, end = headings[0], statements[0], example[0]
    if not start < location < end or any(
        re.search(r"Root\s+scope|scope\s*:\s*law", line) and line.strip() != statement
        for line in lines[start + 1 : end]
    ):
        return decision_ir.EvaluationContext(status="unknown")
    source = "common/laws/readme.md"
    line = location + 1
    return decision_ir.EvaluationContext(
        actor_scope=decision_ir.ContextBinding("root", "country", "actor", source, line),
        auxiliary_scopes=(decision_ir.ContextBinding("law", "law", "auxiliary", source, line),),
        evidence=(f"{source}:{line}",),
    )


def _frozen_law_context() -> decision_ir.EvaluationContext:
    # Only the three documentary context lines are versioned. Blank lines keep
    # their original positions; the ignored full mirror is never an offline input.
    raw = _LAW_DOC.read_bytes()
    manifest = json.loads(_LAW_DOC_MANIFEST.read_text(encoding="utf-8"))
    entry = manifest["文档"]["game/common/laws/readme.md"]
    if (
        hashlib.sha256(raw).hexdigest() != _LAW_DOC_SHA256
        or entry["镜像sha256"] != _LAW_MIRROR_SHA256
        or entry["sha256"] != _LAW_NATIVE_SHA256
    ):
        raise ValueError("法律 enact weight 冻结文档证据漂移")
    native = config.GAME / "common/laws/readme.md"
    if native.is_file() and hashlib.sha256(native.read_bytes()).hexdigest() != _LAW_NATIVE_SHA256:
        raise ValueError("法律 enact weight 原版文档证据漂移")
    if native.is_file():
        lines = native.read_text(encoding="utf-8-sig").splitlines()
        if any(
            index >= len(lines) or lines[index] != line
            for index, line in enumerate(raw.decode("utf-8").splitlines())
            if line
        ):
            raise ValueError("法律 enact weight 摘录行与原版不一致")
    context = law_evaluation_context(raw.decode("utf-8"))
    if context.status != "observed":
        raise ValueError("法律 enact weight 文档没有精确上下文")
    return context


def _frozen_strategy_contexts() -> dict[str, decision_ir.EvaluationContext]:
    """Use manifest document lines, never pretend they are native script lines.

    This is historical static evidence in both online and offline contracts.
    Production entry points separately require current scripts and EXE bytes.
    """
    raw = engine_scope.strategy_snapshot()
    text = raw.decode("utf-8")
    data = json.loads(raw)
    specs = {
        "recklessness": (
            "target_country",
            "additive_strength_estimate_multiplier",
            "multiplier",
            "0x14182761f",
        ),
        "wargoal_maneuvers_fraction": (
            "enemy_country",
            "additive_maneuvers_fraction",
            "fraction",
            "0x141829eef",
        ),
        "wanted_construction_output": (
            None,
            "additive_construction_output_target",
            "construction_output",
            "0x1418288e0",
        ),
        "institution_scores": (None, "additive_score", "score", "0x141826d9a"),
        "min_law_chance_to_pass": (
            None,
            "override_pass_chance_threshold",
            "pass_chance",
            "0x141829083",
        ),
        "wargoal_scores": ("target_country", "additive_score", "score", "0x141825c4a"),
        "secret_goal_scores": ("target_country", "additive_score", "score", "0x141825a5d"),
        "wanted_navy_size": (
            None,
            "additive_navy_size_target",
            "naval_administration_levels",
            "0x1416139a7",
        ),
        "ship_construction_output_multiplier": (
            None,
            "additive_ship_construction_output_multiplier",
            "multiplier",
            "0x1416140cb",
        ),
    }
    specs.update(
        {
            "aggression": (
                "target_country",
                "additive_aggression",
                "play_start_tendency",
                "0x1418277cf",
            ),
            "nationalization_desire": (
                None,
                "additive_nationalization_desire",
                "desire",
                "0x14182a22d",
            ),
            "max_active_stances": (None, "additive_active_stance_limit", "count", "0x14182a3bc"),
            "wanted_marines": (
                None,
                "additive_marine_size_target",
                "barracks_levels",
                "0x14182677d",
            ),
            "economic_vs_government_spending_balance": (
                None,
                "additive_spending_balance",
                "debt_threshold_ratio",
                "0x141828bad",
            ),
            "target_marine_formation_size": (
                None,
                "additive_marine_formation_size_target",
                "units_per_formation",
                "0x14182690d",
            ),
            "unacceptable_infamy_level": (
                None,
                "first_positive_infamy_limit_override",
                "infamy",
                "0x14182645d",
            ),
            "undesirable_infamy_level": (
                None,
                "first_positive_infamy_limit_override",
                "infamy",
                "0x1418262cd",
            ),
            "diplomatic_play_neutrality": (
                None,
                "additive_positive_active_neutrality",
                "score",
                "0x141829b9c",
            ),
            "diplomatic_play_boldness": (
                None,
                "native_randomized_additive_boldness",
                "score",
                "0x141829a0a",
            ),
        }
    )
    specs.update(
        {
            "treaty_category_scores": (
                None,
                "additive_treaty_category_score",
                "score",
                "0x141825e09",
            ),
            "strategic_region_stance_type_scores": (
                None,
                "additive_region_stance_score",
                "score",
                "0x14182a78a",
            ),
            "wanted_num_supply_ships": (
                None,
                "additive_supply_ship_count_target",
                "ships",
                "0x141613c2f",
            ),
            "max_ship_design_complexity": (
                None,
                "additive_ship_design_complexity_limit",
                "modification_levels",
                "0x14165f81b",
            ),
        }
    )
    parser_members = {
        "recklessness": ("0x141823b41", "0x10c0"),
        "wargoal_maneuvers_fraction": ("0x141823c67", "0x798"),
        "wanted_construction_output": ("0x141823bbf", "0x16c0"),
        "institution_scores": ("0x141823b2a", "0x3f0"),
        "min_law_chance_to_pass": ("0x141823c13", "0x9d8"),
        "wargoal_scores": ("0x14182358f", "0x1d8"),
        "secret_goal_scores": ("0x1418237bd", "0x2c0"),
        "wanted_navy_size": ("0x141823be9", "0x1a80"),
        "ship_construction_output_multiplier": ("0x141823f32", "0x1c00"),
        "aggression": ("0x141823886", "0x1180"),
        "nationalization_desire": ("0x141823dc6", "0xd98"),
        "max_active_stances": ("0x141824094", "0x4b8"),
        "wanted_marines": ("0x141823ecc", "0x1900"),
        "economic_vs_government_spending_balance": ("0x141823eb7", "0x1780"),
        "target_marine_formation_size": ("0x141823ee1", "0x19c0"),
        "unacceptable_infamy_level": ("0x141823799", "0x1000"),
        "undesirable_infamy_level": ("0x1418237ab", "0xf40"),
        "diplomatic_play_neutrality": ("0x141823b95", "0x628"),
        "diplomatic_play_boldness": ("0x141823baa", "0x6e0"),
        "treaty_category_scores": ("0x141823119", "0x1f0"),
        "strategic_region_stance_type_scores": ("0x141823dfa", "0x490"),
        "wanted_num_supply_ships": ("0x141823ef6", "0x1b40"),
        "max_ship_design_complexity": ("0x141823f20", "0x1d80"),
    }
    result = {}
    source = engine_scope.STRATEGY_MANIFEST_ID
    for field, (target, operation, unit, address) in specs.items():
        expected = {
            "actor_scope": "country",
            "target_scope": (
                "scope:target_country=country;scope:target_state=state"
                if field == "wargoal_scores"
                else f"scope:{target}=country"
                if target is not None
                else "definition_only:institution_type"
                if field == "institution_scores"
                else "scope:target_region=strategic_region;scope:region_score=scalar"
                if field == "strategic_region_stance_type_scores"
                else "scope:law=law"
                if field == "min_law_chance_to_pass"
                else "scope:diplomatic_play=diplomatic_play"
                if field == "diplomatic_play_boldness"
                else "none"
            ),
            "operation": operation,
            "capability": "direct",
            "unit": unit,
            "consumer_va": address,
            "parser_va": parser_members[field][0],
            "member_offset": parser_members[field][1],
        }
        actual = data.get("consumers", {}).get(field, {})
        if (
            actual != expected
            if field in {"recklessness", "wargoal_maneuvers_fraction"}
            else any(actual.get(key) != value for key, value in expected.items())
        ):
            raise ValueError(f"锁定策略消费者字段合同不一致：{field}")
        entries = list(
            re.finditer(
                rf'^    "{field}"\s*:\s*\{{(?P<body>\s*"actor_scope".*?)^    \}}',
                text,
                re.MULTILINE | re.DOTALL,
            )
        )
        if len(entries) != 1:
            raise ValueError(f"锁定策略消费者缺少独立行级证据：{field}")
        entry = entries[0]
        locations = {}
        for key in ("actor_scope", "target_scope"):
            members = list(re.finditer(rf'^[ \t]*"{key}"\s*:', entry["body"], re.MULTILINE))
            if len(members) != 1:
                raise ValueError(f"锁定策略消费者缺少精确对象证据：{field}/{key}")
            position = entry.start("body") + members[0].start()
            locations[key] = text.count("\n", 0, position) + 1
        actor = decision_ir.ContextBinding(
            "root", "country", "actor", source, locations["actor_scope"]
        )
        target_binding = (
            decision_ir.ContextBinding(
                target, "country", "target", source, locations["target_scope"]
            )
            if target is not None
            else None
        )
        result[field] = decision_ir.EvaluationContext(
            actor_scope=actor,
            targets=(
                target_binding,
                decision_ir.ContextBinding(
                    "target_state", "state", "target", source, locations["target_scope"]
                ),
            )
            if target_binding is not None and field == "wargoal_scores"
            else (target_binding,)
            if target_binding is not None
            else (
                decision_ir.ContextBinding(
                    "target_region", "strategic_region", "target", source, locations["target_scope"]
                ),
            )
            if field == "strategic_region_stance_type_scores"
            else (),
            auxiliary_scopes=(
                decision_ir.ContextBinding(
                    "law", "law", "auxiliary", source, locations["target_scope"]
                ),
            )
            if field == "min_law_chance_to_pass"
            else (
                decision_ir.ContextBinding(
                    "diplomatic_play",
                    "diplomatic_play",
                    "auxiliary",
                    source,
                    locations["target_scope"],
                ),
            )
            if field == "diplomatic_play_boldness"
            else (
                decision_ir.ContextBinding(
                    "region_score", "scalar", "auxiliary", source, locations["target_scope"]
                ),
            )
            if field == "strategic_region_stance_type_scores"
            else (),
            evidence=(
                f"{source}:{actor.line}",
                f"{source}:{locations['target_scope']}",
                f"{source}:sha256={engine_scope.STRATEGY_MANIFEST_SHA256}",
                f"{source}:consumer={field}:va={address}",
                f"{source}:evidence=frozen_engine_snapshot",
                *(
                    (f"{source}:definition_only:institution_type",)
                    if field == "institution_scores"
                    else ()
                ),
            ),
        )
    return result


def _frozen_institution_contexts(
    context: decision_ir.EvaluationContext,
) -> dict[str, decision_ir.EvaluationContext]:
    """Project only exact numeric children of the pinned original ordinary map."""
    data = json.loads(engine_scope.strategy_snapshot())
    raw = BASELINE.read_bytes()
    source = "common/ai_strategies/00_default_strategy.txt"
    # Repository snapshots omit the native UTF-8 BOM by the text contract.
    if data["script_hashes"][source] not in {
        hashlib.sha256(raw).hexdigest(),
        hashlib.sha256(b"\xef\xbb\xbf" + raw).hexdigest(),
    }:
        raise ValueError("冻结制度策略原件 SHA 与引擎证据不一致")
    parsed = parse_text(raw.decode("utf-8-sig"))
    definitions = [item for item in parsed.top_assignments if item.key == "ai_strategy_default"]
    scores = (
        vanilla_inventory._institution_score_map(
            definitions[0], frozenset(data["institution_definitions"])
        )
        if not parsed.errors and len(definitions) == 1
        else None
    )
    if scores is None:
        raise ValueError("制度策略必须有唯一合法制度定义 key 的普通数值子块")
    return {f"institution_scores.{item.key}": context for item in scores.assignments()}


def _frozen_strategy_score_contexts(
    contexts: dict[str, decision_ir.EvaluationContext],
) -> dict[str, decision_ir.EvaluationContext]:
    """Project pinned enum numeric children without authorizing the map or trigger."""
    data = json.loads(engine_scope.strategy_snapshot())
    raw = BASELINE.read_bytes()
    source = "common/ai_strategies/00_default_strategy.txt"
    if data["script_hashes"][source] not in {
        hashlib.sha256(raw).hexdigest(),
        hashlib.sha256(b"\xef\xbb\xbf" + raw).hexdigest(),
    }:
        raise ValueError("冻结目标策略原件 SHA 与引擎证据不一致")
    parsed = parse_text(raw.decode("utf-8-sig"))
    definitions = [item for item in parsed.top_assignments if item.key == "ai_strategy_default"]
    result = {}
    for family in (
        "wargoal_scores",
        "secret_goal_scores",
        "treaty_category_scores",
        "strategic_region_stance_type_scores",
    ):
        scores = (
            vanilla_inventory._strategy_score_map(
                definitions[0],
                family,
                frozenset(
                    data["stance_definitions"]
                    if family == "strategic_region_stance_type_scores"
                    else data["strategy_score_keys"][family]
                ),
            )
            if not parsed.errors and len(definitions) == 1
            else None
        )
        if scores is None:
            raise ValueError(f"目标策略必须有唯一合法枚举 key 的普通数值子块：{family}")
        suffix = ".score" if family == "secret_goal_scores" else ""
        result.update(
            {f"{family}.{item.key}{suffix}": contexts[family] for item in scores.assignments()}
        )
    return result


def _frozen_company_context() -> decision_ir.EvaluationContext:
    """公司基础评分的国家对象来源，不授权章程、建设目标或新getter。"""
    raw = engine_scope.company_snapshot()
    data = json.loads(raw)
    matches = [row for row in data["contracts"] if row["field"] == "ai_weight"]
    if len(matches) != 1:
        raise ValueError("公司基础评分缺少唯一作用域合同")
    row = matches[0]
    if any(
        row[key] != value
        for key, value in {
            "actor": "country",
            "target": "definition_only:company_type",
            "operation": "base_candidate_score",
            "capability": "direct",
            "consumer": "0x141732900",
            "actual_call": "0x141632075",
            "numeric_member": "0x390",
            "parser": "0x141730850",
            "parser_receiver": "0x598",
            "nonpositive_rejection": "0x141641350",
        }.items()
    ):
        raise ValueError("公司基础评分作用域合同漂移")
    text = raw.decode("utf-8")
    section = text.index('"field": "ai_weight"')
    line = text.count("\n", 0, text.index('"actor": "country"', section)) + 1
    source = engine_scope.COMPANY_MANIFEST_ID
    return decision_ir.EvaluationContext(
        actor_scope=decision_ir.ContextBinding("root", "country", "actor", source, line),
        evidence=(
            f"{source}:{line}",
            f"{source}:sha256={engine_scope.COMPANY_MANIFEST_SHA256}",
            f"{source}:evidence=frozen_engine_snapshot",
            f"{source}:definition_only:company_type",
        ),
    )


def _frozen_ship_modification_contexts() -> dict[tuple[str, str], decision_ir.EvaluationContext]:
    """Keep the actual named candidate even when material readers use only ROOT."""
    from .. import equipment_opportunities  # noqa: PLC0415, TID252

    data = equipment_opportunities.load_baseline()
    raw = equipment_opportunities.BASELINE.read_text(encoding="utf-8")
    source = equipment_opportunities.BASELINE.relative_to(REPO).as_posix()
    actor_line = raw.count("\n", 0, raw.index('"actor": "country"')) + 1
    target_line = (
        raw.count("\n", 0, raw.index('"target": "scope:ship_modification_type=ship_modification"'))
        + 1
    )
    context = decision_ir.EvaluationContext(
        actor_scope=decision_ir.ContextBinding("root", "country", "actor", source, actor_line),
        targets=(
            decision_ir.ContextBinding(
                "ship_modification_type", "ship_modification", "candidate", source, target_line
            ),
        ),
        evidence=(
            f"{source}:{actor_line}",
            f"{source}:{target_line}",
            f"{source}:sha256={equipment_opportunities.BASELINE_SHA256}",
        ),
    )
    return {
        (row["source"], f"{identity}.ai_weight"): context
        for identity, row in data["candidates"].items()
        if row["weight_shape"] == "block" and row["scope_status"] == "direct"
    }


def _frozen_treaty_contexts() -> dict[tuple[str, str], decision_ir.EvaluationContext]:
    """Article identities are static; proposal evaluation exposes country ROOT."""
    from .. import treaty_opportunities  # noqa: PLC0415, TID252

    data = treaty_opportunities.load_baseline()
    raw = treaty_opportunities.BASELINE.read_text(encoding="utf-8")
    source = treaty_opportunities.BASELINE.relative_to(REPO).as_posix()
    line = raw.count("\n", 0, raw.index('"actor": "country"')) + 1
    context = decision_ir.EvaluationContext(
        actor_scope=decision_ir.ContextBinding("root", "country", "actor", source, line),
        evidence=(
            f"{source}:{line}",
            f"{source}:sha256={treaty_opportunities.BASELINE_SHA256}",
            f"{source}:definition_only:treaty_article",
        ),
    )
    return {
        (row["source"], f"{identity}.ai.{leaf}"): context
        for identity, row in data["candidates"].items()
        for leaf, shape in (
            ("proposal_weight", row["weight_shape"]),
            ("evaluation_chance", row["evaluation_shape"]),
        )
        if shape == "block"
    }


def _frozen_mobilization_contexts() -> dict[tuple[str, str], decision_ir.EvaluationContext]:
    """付费动员权重保留编队 ROOT 和实际所属国家；候选来自冻结原文。"""
    from .. import mobilization_opportunities  # noqa: PLC0415, TID252

    raw = mobilization_opportunities.BASELINE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != mobilization_opportunities.BASELINE_SHA256:
        raise ValueError("动员冻结资料身份漂移，必须独立复核后重新pin")
    source = mobilization_opportunities.BASELINE.relative_to(REPO).as_posix()
    return dict(_mobilization_context_rows(raw, source))


def _frozen_native_action_contexts() -> dict[tuple[str, str], decision_ir.EvaluationContext]:
    """Exact proposal ROOT, with only the proven raise-payments target alias."""
    from .. import native_action_opportunities as native  # noqa: PLC0415, TID252

    catalog = native.consumer_catalog()
    frozen_source = native.FROZEN.relative_to(REPO).as_posix()
    return {
        (row["source"], row["field"]): native.batch_evaluation_context(row["source"], row["field"])
        if row["source"] in native.BATCH_CANDIDATES.values()
        else decision_ir.EvaluationContext(
            actor_scope=decision_ir.ContextBinding(
                "root", "country", "actor", row["scope_evidence"], row["scope_evidence_line"]
            ),
            evidence=(
                f"{frozen_source}:sha256={native.FROZEN_SHA256}",
                f"{row['scope_evidence']}:{row['scope_evidence_line']}",
                f"{row['scope_evidence']}:{row['score_evidence_line']}",
                f"{row['scope_evidence']}:sha256={row['scope_evidence_sha256']}",
                f"{row['source']}:sha256={row['source_sha256']}",
                f"{row['source']}:consumer={row['field']}:target_not_consumed",
            ),
        )
        for row in catalog.values()
    }


def _frozen_canal_contexts() -> dict[tuple[str, str], decision_ir.EvaluationContext]:
    """Exact country survey and purchase decisions retain relative weight and zero."""
    from .. import canal_opportunities as canal  # noqa: PLC0415, TID252

    raw = canal.FROZEN.read_bytes()
    frozen_hash = "ca02454ecea092a5c5bbe8d7e28017355e75af6442d68e4d673ce9c5207b4faf"
    if hashlib.sha256(raw).hexdigest() != frozen_hash:
        raise ValueError("运河冻结完整源身份漂移，必须独立复核后重新pin")
    inputs = canal.frozen_inputs()
    source = canal.FROZEN.relative_to(REPO).as_posix()
    markers = (
        "# A decision is evaluated in country scope.",
        "# The scripted weight which determines how likely AI is to take it amongst all possible decisions (country scope).",
        "# Similar to event options. If it evaluates to 0, AI will not take the decision. Evaluates to 1 if unspecified",
    )
    lines = inputs[canal.HELP].splitlines()
    locations = [
        [i + 1 for i, line in enumerate(lines) if line.strip() == marker] for marker in markers
    ]
    if any(len(found) != 1 for found in locations):
        raise ValueError("运河country ROOT及相对权重/零分帮助合同不唯一")
    return {
        (row["source"], row["field"]): decision_ir.EvaluationContext(
            actor_scope=decision_ir.ContextBinding(
                "root", "country", "actor", canal.HELP, locations[0][0]
            ),
            evidence=(
                f"{source}:sha256={frozen_hash}",
                *(f"{canal.HELP}:{found[0]}" for found in locations),
                *(
                    f"{name}:sha256={digest}"
                    for name, digest in sorted(canal.load()["sources"].items())
                ),
                f"{row['source']}:consumer={row['field']}:relative_weight_preserve_zero",
            ),
        )
        for row in canal.consumer_catalog()
    }


def _frozen_native_decision_contexts() -> dict[tuple[str, str], decision_ir.EvaluationContext]:
    """Exact Olympic country decision retains native reward, weight and zero."""
    from .. import native_decision_opportunities as native_decision  # noqa: PLC0415, TID252

    raw = native_decision.FROZEN.read_bytes()
    frozen_hash = "d74209b763b0646fdde8eea6e90a80cf4289398ea190b08ae2a743489af1f4fe"
    if hashlib.sha256(raw).hexdigest() != frozen_hash:
        raise ValueError("赛事冻结完整源身份漂移，必须独立复核后重新pin")
    inputs = native_decision.frozen_inputs()
    source = native_decision.FROZEN.relative_to(REPO).as_posix()
    markers = (
        "# A decision is evaluated in country scope.",
        "# The scripted weight which determines how likely AI is to take it amongst all possible decisions (country scope).",
        "# Similar to event options. If it evaluates to 0, AI will not take the decision. Evaluates to 1 if unspecified",
    )
    lines = inputs[native_decision.HELP].splitlines()
    locations = [
        [i + 1 for i, line in enumerate(lines) if line.strip() == marker] for marker in markers
    ]
    if any(len(found) != 1 for found in locations):
        raise ValueError("赛事country ROOT及相对权重/零分帮助合同不唯一")
    return {
        (row["source"], row["field"]): decision_ir.EvaluationContext(
            actor_scope=decision_ir.ContextBinding(
                "root", "country", "actor", native_decision.HELP, locations[0][0]
            ),
            evidence=(
                f"{source}:sha256={frozen_hash}",
                *(f"{native_decision.HELP}:{found[0]}" for found in locations),
                *(
                    f"{name}:sha256={digest}"
                    for name, digest in sorted(native_decision.load()["sources"].items())
                ),
                f"{row['source']}:consumer={row['field']}:relative_weight_preserve_zero",
            ),
        )
        for row in native_decision.consumer_catalog()
    }


def _frozen_native_button_contexts() -> dict[tuple[str, str], decision_ir.EvaluationContext]:
    """Exact native button actor/effect contracts; no target aliases."""
    from pdx import native_button_opportunities as buttons  # noqa: PLC0415

    buttons.verify_inputs(buttons.frozen_inputs())
    return {
        (row["source"], row["field"]): buttons.evaluation_context(row["source"], row["field"])
        for row in buttons.consumer_catalog()
    }


def _frozen_famine_contexts() -> dict[tuple[str, str], decision_ir.EvaluationContext]:
    """Three exact JE buttons share documented country ROOT, never a target alias."""
    from .. import famine_opportunities as famine  # noqa: PLC0415, TID252

    frozen_hash = "06de326b4af09b357adefe399187595077ca2a00de4ab8968863b0492de5c112"
    if hashlib.sha256(famine.FROZEN.read_bytes()).hexdigest() != frozen_hash:
        raise ValueError("饥荒完整原版冻结身份漂移，须独立复核后重新pin")
    famine.verify_inputs(famine.frozen_inputs())
    source = famine.FROZEN.relative_to(REPO).as_posix()
    return {
        (row["source"], row["field"]): decision_ir.EvaluationContext(
            actor_scope=decision_ir.ContextBinding(
                "root", "country", "actor", famine.HELP, row["scope_evidence_line"]
            ),
            evidence=(
                f"{source}:sha256={frozen_hash}",
                f"{famine.HELP}:{row['scope_evidence_line']}",
                f"{row['source']}:{row['score_evidence_line']}",
                *(
                    f"{name}:sha256={digest}"
                    for name, digest in sorted(famine.load()["sources"].items())
                ),
                f"{row['source']}:consumer={row['field']}:relative_weight_preserve_zero",
            ),
        )
        for row in famine.consumer_catalog()
    }


def _frozen_decree_contexts() -> dict[tuple[str, str], decision_ir.EvaluationContext]:
    """One complete native emergency-relief state ROOT / owner contract."""
    from .. import decree_opportunities as decree  # noqa: PLC0415, TID252

    if (
        hashlib.sha256(decree.FROZEN.read_bytes()).hexdigest()
        != "f27c726c1f203ee52e715d3181cdd7f1f6fe96aae501e450658d89b4706bb867"
    ):
        raise ValueError("救济政令冻结完整源身份漂移，必须独立复核后重新pin")
    return {(decree.SOURCE, decree.FIELD): decree.evaluation_context()}


@lru_cache(maxsize=1)
def _mobilization_context_rows(
    raw: bytes, source: str
) -> tuple[tuple[tuple[str, str], decision_ir.EvaluationContext], ...]:
    """只复用同字节、同证据路径的不可变上下文；每次入口仍核对当前 pin。"""
    from .. import mobilization_opportunities  # noqa: PLC0415, TID252

    data = mobilization_opportunities.load_baseline(raw=raw)
    text = raw.decode("utf-8")
    line = text.count("\n", 0, text.index('"native_root": "military_formation"')) + 1
    context = decision_ir.EvaluationContext(
        actor_scope=decision_ir.ContextBinding("owner", "country", "actor", source, line),
        auxiliary_scopes=(
            decision_ir.ContextBinding("root", "military_formation", "auxiliary", source, line),
        ),
        evidence=(
            f"{source}:{line}",
            f"{source}:sha256={mobilization_opportunities.BASELINE_SHA256}",
            f"{source}:definition_only:mobilization_option",
        ),
    )
    return tuple(
        ((row["source"], row["field"]), context)
        for row in mobilization_opportunities.candidate_catalog(data).values()
    )


def _mobilization_context_readers(
    field: str,
    context: decision_ir.EvaluationContext,
    readers: dict[str, decision_rules.Reader],
    predicates: tuple[decision_rules.Predicate, ...],
    *,
    actor_path: tuple[str, ...],
    input_keys: tuple[str, ...],
    source: str | None,
    native_root: str | None,
) -> tuple[tuple[str, str, str, str], ...]:
    from .. import mobilization_opportunities  # noqa: PLC0415, TID252

    if source is None or context != _frozen_mobilization_contexts().get((source, field)):
        raise ValueError("动员上下文必须来自已复核的精确冻结候选")
    if native_root != "military_formation" or actor_path != ("owner",):
        raise ValueError("医疗动员必须保持编队ROOT与所属国家AI所有者")
    allowed = mobilization_opportunities.reader_specs(field.removesuffix(".ai_weight"))
    allowed["cost_owner_population"] = {
        "engine": "total_population",
        "scope": "root",
        "unit": "persons",
        "kind": "number",
        "minimum": 0,
        "path": ["owner"],
    }
    result: set[tuple[str, str, str, str]] = set()
    for key in {*input_keys, *(predicate.fact for predicate in predicates)}:
        reader = readers.get(key)
        spec = allowed.get(key)
        if (
            reader is None
            or spec is None
            or reader != decision_rules.Reader(key=key, **{**spec, "path": tuple(spec["path"])})
        ):
            raise ValueError(f"医疗动员读取器完整国家/市场/商品签名漂移：{key}")
        decision_interfaces.reader_scope(reader, actor_path, native_root=native_root)
        result.add((key, "root", "military_formation", "auxiliary"))
        result.add((key, "owner", "country", "actor"))
    if any(isinstance(predicate.value, decision_rules.FactReference) for predicate in predicates):
        raise ValueError("医疗动员冻结贡献没有跨对象FactReference")
    return tuple(sorted(result))


def validate_context_readers(
    field: str,
    context: decision_ir.EvaluationContext,
    readers: dict[str, decision_rules.Reader],
    predicates: tuple[decision_rules.Predicate, ...],
    *,
    actor_path: tuple[str, ...] = (),
    input_keys: tuple[str, ...] = (),
    source: str | None = None,
    native_root: str | None = None,
) -> tuple[tuple[str, str, str, str], ...]:
    """Bind existing observations to evidenced objects, never authorize getters."""
    if (source is not None and source.startswith("common/decrees/")) or field.startswith("decree_"):
        from .. import decree_opportunities as decree  # noqa: PLC0415, TID252

        if (
            source != decree.SOURCE
            or field != decree.FIELD
            or context != _frozen_decree_contexts().get((source, field))
            or actor_path != ("owner",)
            or native_root != "state"
        ):
            raise ValueError("救济政令上下文必须保留精确州ROOT与真实owner")
        specs = decree.derive({})["readers"]
        keys = set(input_keys) | {p.fact for p in predicates}
        if any(isinstance(p.value, decision_rules.FactReference) for p in predicates):
            raise ValueError("救济政令没有跨对象FactReference合同")
        decree_bindings = []
        for key in sorted(keys):
            spec = specs.get(key)
            expected = (
                decision_rules.Reader(key=key, **{**spec, "path": tuple(spec.get("path", ()))})
                if spec is not None
                else None
            )
            if readers.get(key) != expected or expected is None:
                raise ValueError(f"救济政令读取器必须保持精确州/owner签名：{key}")
            decision_interfaces.reader_scope(expected, actor_path, native_root="state")
            decree_bindings.append(
                (key, "owner", "country", "actor")
                if expected.path
                else (key, "root", "state", "auxiliary")
            )
        return tuple(decree_bindings)
    native_fields = (
        _frozen_native_action_contexts()
        if (source and source.startswith("common/diplomatic_actions/"))
        or field.split(".", 1)[0] in {"da_increase_autonomy_of_self", "decrease_payments"}
        else {}
    )
    canal_fields = (
        _frozen_canal_contexts()
        if source == "common/decisions/canal_decisions.txt"
        or field.split(".", 1)[0] in {"suez_survey_decision", "panama_survey_decision"}
        else {}
    )
    native_decision_fields = (
        _frozen_native_decision_contexts()
        if source == "common/decisions/00_decisions.txt"
        or field.split(".", 1)[0] == "revive_olympic_games_decision"
        else {}
    )
    famine_fields = (
        _frozen_famine_contexts()
        if source == "common/scripted_buttons/04_indian_famines_buttons.txt"
        or field.startswith("je_indian_famines_button_")
        else {}
    )
    button_fields = (
        _frozen_native_button_contexts()
        if (source and source.startswith("common/scripted_buttons/"))
        else {}
    )
    button_context = button_fields.get((source, field)) if source is not None else None
    exact_country_context = (
        (
            native_fields.get((source, field))
            or canal_fields.get((source, field))
            or native_decision_fields.get((source, field))
            or famine_fields.get((source, field))
            or button_context
        )
        if source is not None
        else None
    )
    if native_fields or canal_fields or native_decision_fields or famine_fields or button_fields:
        if (
            exact_country_context is None
            or context != exact_country_context
            or actor_path
            or native_root not in {None, "country"}
        ):
            raise ValueError(f"消费者 {field} 偏离精确原生country ROOT合同")
        keys = set(input_keys) | {p.fact for p in predicates}
        keys.update(
            p.value.key for p in predicates if isinstance(p.value, decision_rules.FactReference)
        )
        exact_bindings = []
        for key in sorted(keys):
            reader = readers.get(key)
            if (
                source == "common/diplomatic_actions/32_subjects_raise_payments.txt"
                and field == "raise_payments.ai.propose_score"
            ):
                from pdx import native_action_opportunities as native_actions  # noqa: PLC0415

                spec = native_actions.BATCH_READERS.get(key)
                if (
                    reader is None
                    or spec is None
                    or reader != decision_rules.Reader(key=key, **spec)
                ):
                    raise ValueError(f"提高付款读取器偏离精确本国或目标身份：{key}")
                decision_interfaces.reader_scope(reader, actor_path, native_root="country")
                exact_bindings.append(
                    (key, "target_country", "country", "target")
                    if reader.scope == "target_country"
                    else (key, "root", "country", "actor")
                )
                continue
            if reader is None or reader.scope != "root" or reader.path:
                raise ValueError(f"消费者 {field} 只允许本国ROOT，不提供target或owner观测：{key}")
            if native_decision_fields:
                from pdx import native_decision_opportunities as native_decision  # noqa: PLC0415

                spec = native_decision.derive({"readers": {}})["readers"].get(key)
                if spec is None or reader != decision_rules.Reader(key=key, **spec):
                    raise ValueError(f"赛事读取器必须保持精确本国事实身份：{key}")
            if button_context is not None:
                from pdx import native_button_opportunities as buttons  # noqa: PLC0415

                buttons.validate_reader(
                    reader, source or "", field, actor_path=actor_path, native_root="country"
                )
            if famine_fields:
                from .. import famine_opportunities as famine  # noqa: PLC0415, TID252

                spec = famine.derive({})["readers"].get(key)
                expected = (
                    decision_rules.Reader(
                        key=key,
                        **{**spec, "parameters": tuple(sorted(spec.get("parameters", {}).items()))},
                    )
                    if spec is not None
                    else None
                )
                if reader != expected:
                    raise ValueError(f"饥荒读取器必须保持精确事实身份：{key}")
            decision_interfaces.reader_scope(reader, actor_path, native_root="country")
            if (reader.argument is not None and reader.argument.startswith("scope:")) or any(
                value.startswith("scope:") for _, value in reader.parameters
            ):
                raise ValueError(f"消费者 {field} 不授权目标参数别名：{key}")
            exact_bindings.append((key, "root", "country", "actor"))
        return tuple(exact_bindings)
    if source == "common/mobilization_options/00_mobilization_option.txt" or field.startswith(
        "mobilization_option_"
    ):
        return _mobilization_context_readers(
            field,
            context,
            readers,
            predicates,
            actor_path=actor_path,
            input_keys=input_keys,
            source=source,
            native_root=native_root,
        )
    if field.startswith("institution_scores."):
        parts = field.split(".")
        definitions = json.loads(engine_scope.strategy_snapshot())["institution_definitions"]
        if len(parts) != 2 or parts[1] not in definitions:
            raise ValueError(f"消费者 {field} 不是已证明的精确制度数值子块")
        field = "institution_scores"
    family = field.split(".")[0]
    if family in {
        "wargoal_scores",
        "secret_goal_scores",
        "treaty_category_scores",
        "strategic_region_stance_type_scores",
    }:
        parts = field.split(".")
        score_data = json.loads(engine_scope.strategy_snapshot())
        keys = (
            score_data["stance_definitions"]
            if family == "strategic_region_stance_type_scores"
            else score_data["strategy_score_keys"][family]
        )
        if (
            len(parts) != (3 if family == "secret_goal_scores" else 2)
            or parts[1] not in keys
            or (family == "secret_goal_scores" and parts[2] != "score")
        ):
            raise ValueError(f"消费者 {field} 不是已证明的精确枚举数值子块")
        field = family
    shapes = {
        "subject_value": {"root": ("country", "actor"), "target_country": ("country", "target")},
        "recklessness": {"root": ("country", "actor"), "target_country": ("country", "target")},
        "wargoal_maneuvers_fraction": {
            "root": ("country", "actor"),
            "enemy_country": ("country", "target"),
        },
        "become_subject_value": {"root": ("country", "actor"), "overlord": ("country", "target")},
        "interest_group_government_weight": {
            "root": ("country", "actor"),
            "interest_group": ("interest_group", "candidate"),
        },
        "negotiation_chance": {
            "root": ("country", "actor"),
            "law": ("law", "auxiliary"),
            "amenability": ("scalar", "auxiliary"),
            "advance_chance": ("scalar", "auxiliary"),
            "stall_chance": ("scalar", "auxiliary"),
        },
        "state_value": {
            "root": ("country", "actor"),
            "target_state": ("state", "target"),
            "target_country": ("country", "auxiliary"),
        },
    }
    shapes["treaty_port_value"] = shapes["state_value"]
    shapes["ai_enact_weight_modifier"] = {"root": ("country", "actor"), "law": ("law", "auxiliary")}
    shapes["company.ai_weight"] = {"root": ("country", "actor")}
    shapes["treaty.ai.proposal_weight"] = {"root": ("country", "actor")}
    shapes["treaty.ai.evaluation_chance"] = {"root": ("country", "actor")}
    shapes["wanted_construction_output"] = {"root": ("country", "actor")}
    shapes["institution_scores"] = {"root": ("country", "actor")}
    shapes["min_law_chance_to_pass"] = {"root": ("country", "actor"), "law": ("law", "auxiliary")}
    shapes["wargoal_scores"] = {
        "root": ("country", "actor"),
        "target_country": ("country", "target"),
        "target_state": ("state", "target"),
    }
    shapes["secret_goal_scores"] = {
        "root": ("country", "actor"),
        "target_country": ("country", "target"),
    }
    shapes["treaty_category_scores"] = {"root": ("country", "actor")}
    shapes["strategic_region_stance_type_scores"] = {
        "root": ("country", "actor"),
        "target_region": ("strategic_region", "target"),
        "region_score": ("scalar", "auxiliary"),
    }
    shapes["ship_modification.ai_weight"] = {
        "root": ("country", "actor"),
        "ship_modification_type": ("ship_modification", "candidate"),
    }
    shapes["wanted_num_supply_ships"] = {"root": ("country", "actor")}
    shapes["max_ship_design_complexity"] = {"root": ("country", "actor")}
    shapes["wanted_navy_size"] = {"root": ("country", "actor")}
    shapes["ship_construction_output_multiplier"] = {"root": ("country", "actor")}
    for scalar in (
        "nationalization_desire",
        "max_active_stances",
        "wanted_marines",
        "economic_vs_government_spending_balance",
        "target_marine_formation_size",
        "unacceptable_infamy_level",
        "undesirable_infamy_level",
        "diplomatic_play_neutrality",
    ):
        shapes[scalar] = {"root": ("country", "actor")}
    shapes["aggression"] = {
        "root": ("country", "actor"),
        "target_country": ("country", "target"),
    }
    shapes["diplomatic_play_boldness"] = {
        "root": ("country", "actor"),
        "diplomatic_play": ("diplomatic_play", "auxiliary"),
    }
    formation_shape = {
        "root": ("country", "actor"),
        "military_formation": ("military_formation", "auxiliary"),
    }
    shapes["conscript_battalion_ratio"] = formation_shape
    if field.startswith("combat_unit_group_weights.") and field.count(".") == 1:
        shapes[field] = formation_shape
    if field not in shapes or context.status != "observed":
        return ()
    # These contracts document a country ROOT. Reaching a country again via
    # owner cannot preserve that actor's identity after a caller-side offset.
    if actor_path:
        raise ValueError(f"消费者 {field} 读取器 actor 路径偏离已证明的国家 ROOT")
    bindings = {
        binding.name: binding
        for binding in (context.actor_scope, *context.targets, *context.auxiliary_scopes)
        if binding is not None
    }
    if (
        field
        in {
            "treaty_category_scores",
            "strategic_region_stance_type_scores",
            "wanted_num_supply_ships",
            "max_ship_design_complexity",
            "ship_modification.ai_weight",
            "treaty.ai.proposal_weight",
            "treaty.ai.evaluation_chance",
            "recklessness",
            "wargoal_maneuvers_fraction",
            "wanted_construction_output",
            "institution_scores",
            "min_law_chance_to_pass",
            "wargoal_scores",
            "secret_goal_scores",
            "wanted_navy_size",
            "ship_construction_output_multiplier",
            "aggression",
            "nationalization_desire",
            "max_active_stances",
            "wanted_marines",
            "economic_vs_government_spending_balance",
            "target_marine_formation_size",
            "unacceptable_infamy_level",
            "undesirable_infamy_level",
            "diplomatic_play_neutrality",
            "diplomatic_play_boldness",
        }
        and {name: (binding.kind, binding.role) for name, binding in bindings.items()}
        != shapes[field]
    ):
        raise ValueError(f"消费者 {field} 对象上下文偏离精确冻结证据")
    result: set[tuple[str, str, str, str]] = set()

    def bind(key: str, scope: str, *, argument_kind: str | None = None) -> None:
        binding = bindings.get(scope)
        expected = shapes[field].get(scope)
        if binding is None or expected is None or (binding.kind, binding.role) != expected:
            raise ValueError(f"消费者 {field} 读取器 {key} 作用域/类型/角色缺少上下文证据：{scope}")
        if argument_kind is not None and binding.kind != argument_kind:
            raise ValueError(
                f"消费者 {field} 读取器 {key} 参数 {scope} 必须为 {argument_kind}，实际为 {binding.kind}"
            )
        result.add((key, binding.name, binding.kind, binding.role))

    def bind_argument(reader: decision_rules.Reader, literal: str, parameter: str = "") -> None:
        # These are object-argument signatures of existing readers, not a
        # getter registry. Interpret root only after choosing the signature:
        # has_variable = root names a variable, not the actor country.
        country_arguments = {
            ("is_subject_of", ""),
            ("has_truce_with", ""),
            ("is_homeland_of_country_cultures", ""),
            ("owner", ""),
            ("has_diplomatic_pact", "who"),
            ("has_treaty_alliance_with", "TARGET"),
            ("primary_cultures_percent_state", "target_country"),
        }
        if (reader.engine, parameter) not in country_arguments:
            if literal.startswith("scope:"):
                raise ValueError(
                    f"消费者 {field} 读取器 {reader.key} 参数不支持对象作用域：{literal}"
                )
            return
        scope = "root" if literal.lower() == "root" else literal.removeprefix("scope:")
        if scope == literal and scope != "root":
            return
        bind(reader.key, scope, argument_kind="country")

    def check(key: str) -> decision_rules.Reader:
        reader = readers.get(key)
        if reader is None:
            raise ValueError(f"消费者 {field} 缺少真实读取器：{key}")
        bind(key, reader.scope)
        if reader.scope not in {
            "root",
            "target_country",
            "overlord",
            "interest_group",
            "target_state",
        }:
            raise ValueError(
                f"消费者 {field} 读取器没有已审计的作用域 getter：{key}/{reader.scope}"
            )
        # Existing interface signatures keep output kind, unit and every path
        # conversion authoritative; an observed law is not a new law getter.
        decision_interfaces.reader_scope(reader, actor_path, native_root=native_root)
        if reader.engine == "scope:amenability":
            if field != "negotiation_chance" or context != negotiation_context.evaluation_context(
                BASELINE.read_text(encoding="utf-8")
            ):
                raise ValueError("具名amenability数值仅在实际谈判帧可读")
            bind(key, "amenability", argument_kind="scalar")
        if reader.argument is not None:
            bind_argument(reader, reader.argument)
        for parameter, literal in reader.parameters:
            bind_argument(reader, literal, parameter)
        for literal in reader.path:
            if literal.lower() == "root":
                bind(key, "root")
            elif literal.startswith("scope:"):
                bind(key, literal.removeprefix("scope:"))
        if reader.engine == "relations:root":
            bind(key, "root", argument_kind="country")
        return reader

    for key in input_keys:
        check(key)
    for predicate in predicates:
        check(predicate.fact)
        if isinstance(predicate.value, decision_rules.FactReference):
            other = check(predicate.value.key)
            if predicate.value.expression != other.reference():
                raise ValueError(f"消费者 {field} FactReference 右侧与读取器不一致：{other.key}")
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class ProductionConsumer:
    id: str
    field: tuple[str, ...]
    source: str
    scope: str
    operation: str
    rule_count: int
    max_delta: float
    vanilla_tail: str
    numeric_policy: str = "delta_to_native"
    scalar_neutral: float | None = None
    scalar_lower: float | None = None
    scalar_upper: float | None = None


@dataclass(frozen=True, slots=True)
class SituatedModel:
    facts: tuple[EvidenceSpec, ...]
    consumers: tuple[ConsumerContract, ...]
    actions: tuple[ActionCard, ...]
    relations: tuple[Relation, ...]
    source_sha256: dict[str, str]
    production_consumers: tuple[ProductionConsumer, ...] = ()
    production_rule_count: int = 0
    goals: tuple[tuple[str, int], ...] = ()
    support_sources: dict[str, dict[str, Any]] | None = None
    action_instances: tuple[action_instances.ActionInstance, ...] = ()
    action_ir: tuple[ir.ActionIR, ...] = ()
    goal_specs: tuple[goal_source.Goal, ...] = ()
    layer_model: layers.LayerModel | None = None
    binding_rows: tuple[bindings.Binding, ...] = ()
    decision_ir: tuple[decision_ir.ConsumerDecisionIR, ...] = ()
    consumer_ir: ConsumerIRBundle | None = None
    support_signals: support_signals.SupportSignals | None = None
    observation_contracts: tuple[tuple[str, str, tuple[object, ...]], ...] = ()
    port_graph: ports.PortGraph | None = None

    def contract(self) -> dict[str, object]:
        result = contract(self.facts, self.consumers, self.actions, self.relations)
        result["source_fingerprints"] = dict(self.source_sha256)
        if self.port_graph is not None:
            result["domain_ports"] = self.port_graph.contract()
        owners_by_source_field: dict[tuple[str, str], set[str]] = {}
        for instance in self.action_instances:
            if instance.kind not in {
                "rule_action",
                "event_program",
                "acceptance_program",
                "regional_resource_program",
            }:
                continue
            key = (instance.source, instance.consumer_field)
            owners_by_source_field.setdefault(key, set()).add(instance.owner)
        production_fields = []
        for item in self.production_consumers:
            owners = owners_by_source_field.get((item.source, ".".join(item.field)))
            if not owners:
                raise ValueError(
                    f"生产消费者缺少实际 producer owner：{item.source}:{'.'.join(item.field)}"
                )
            if len(owners) != 1:
                raise ValueError(
                    f"生产消费者存在多个 producer owner：{item.source}:{'.'.join(item.field)}"
                )
            production_fields.append(
                {
                    "id": item.id,
                    "field": ".".join(item.field),
                    "source": item.source,
                    "scope": item.scope,
                    "operation": item.operation,
                    "rule_count": item.rule_count,
                    "max_delta": item.max_delta,
                    "vanilla_tail": item.vanilla_tail,
                    "numeric_policy": item.numeric_policy,
                    **(
                        {
                            "scalar": {
                                "neutral": item.scalar_neutral,
                                "lower": item.scalar_lower,
                                "upper": item.scalar_upper,
                            },
                            "max_delta_semantics": "emitted_scalar_output_magnitude_not_difference_from_unknown_native_default"
                            if item.numeric_policy == "absolute_new_aiweight_native_default_unknown"
                            else "additive_delta_magnitude_to_explicit_native_weight",
                        }
                        if item.scalar_lower is not None
                        else {}
                    ),
                    "owner": next(iter(owners)),
                    "write_once": True,
                }
            )
        result["production"] = {
            "rule_count": self.production_rule_count,
            "consumer_count": len(self.production_consumers),
            "fields": production_fields,
            "goal_ranking": dict(self.goals),
            "unknown": "preserve_unknown_and_fallback_vanilla",
            "player_boundary": "is_ai_only; no player writes",
            "world_scans": 0,
            "runtime_python": False,
            "relationship_depth": 2,
        }
        result["action_instances"] = action_instances.contract(self.action_instances)
        result["observation_contracts"] = [
            {"source": source, "fact": key, "signature": signature}
            for source, key, signature in self.observation_contracts
        ]
        result["ir"] = ir.contract(self.action_ir)
        result["typed_state"] = state.contract()
        supporting = self.support_sources or {}
        result["goals"] = {
            **goal_source.contract(self.goal_specs),
            "activation": "per_action_live_rank_fact_sets_need_tier",
            "deactivation": "rank_fact_false_or_unknown_restores_neutral_tier",
            "unknown": "rank_fact_unknown_uses_neutral_tier",
            "persistent_state": False,
            "priority_role": "legacy_metadata_not_utility; observed_rank_terms_contribute_amount",
            "reserved": {
                key: value["reason"]
                for key, value in supporting.get("goals.toml", {}).get("goals", {}).items()
                if value.get("reserved") is True
            },
        }
        if self.support_signals is not None:
            result["supporting_signals"] = support_signals.contract(self.support_signals)
        result["opportunities"] = opportunity.contract(
            {
                key: value
                for key, value in supporting.get("opportunities.toml", {})
                .get("opportunities", {})
                .items()
                if value.get("reserved") is not True
            }
        )
        result["commitments"] = commitment.contract(
            {
                key: value
                for key, value in supporting.get("commitments.toml", {})
                .get("commitments", {})
                .items()
                if value.get("reserved") is not True
            }
        )
        result["action_families"] = {
            "schema": 1,
            "ids": list(families.FAMILIES),
            "definitions": supporting.get("action_families.toml", {}).get("families", {}),
            "classifier": "source_and_field_deterministic",
        }
        coverage = domain_coverage.load(DECISIONS / "domain_actions.toml")
        result["domain_coverage"] = domain_coverage.contract(coverage, self.action_instances)
        layer_model = self.layer_model
        if layer_model is not None:
            result["layers"] = {
                "schema": 1,
                "strategies": [item.id for item in layer_model.strategies],
                "domains": [item.id for item in layer_model.domains],
                "tools": [
                    {
                        "id": item.id,
                        "domain": item.domain_id,
                        "strategy": item.strategy_id,
                        "neutral_local": item.neutral_local,
                        "enables": list(item.enables),
                        "relations": list(item.relations),
                    }
                    for item in layer_model.tools
                ],
                "enables_depth": dict(sorted(layer_model.enables_depth.items())),
            }
        result["bindings"] = bindings.contract(self.binding_rows)
        result["decision_ir"] = {
            "schema": 1,
            "count": len(self.decision_ir),
            "items": [
                {
                    "action_id": item.action_id,
                    "domain": item.domain,
                    "consumer_id": item.consumer_id,
                    "field": item.field,
                    "operation": item.operation,
                    "core_evidence": list(item.core_evidence),
                    "auxiliary_evidence": list(item.auxiliary_evidence),
                    "hard_negative": list(item.hard_negative),
                    "costs": list(item.costs),
                    "max_delta": item.max_delta,
                    "consumer_max_delta": item.consumer_max_delta,
                    "vanilla_tail": item.vanilla_tail,
                    "unknown_policy": item.unknown_policy,
                    "relation_ids": list(item.relation_ids),
                    "single_clamp": item.single_clamp,
                    "improves": list(item.improves),
                    "consumes": list(item.consumes),
                    "requires_all": list(item.requires_all),
                    "requires_any": list(item.requires_any),
                    "blocked_by": list(item.blocked_by),
                    "exit_when": list(item.exit_when),
                    "base": item.base,
                    "stress": item.stress,
                    "stress_semantics": "compatibility_metadata_not_utility",
                    "opportunity": item.opportunity,
                    "commitment": item.commitment,
                    "political_cost": item.political_cost,
                    "variant_group": item.variant_group,
                    "variant_priority": item.variant_priority,
                    "cause_group": item.cause_group,
                    "commitment_cost_id": item.commitment_cost_id,
                    "political_cost_id": item.political_cost_id,
                    "rank_terms": [
                        {
                            "fact": term.fact,
                            "goal": term.goal,
                            "tier": term.tier,
                            "unit": term.unit,
                            "amount": term.amount,
                            "evidence_group": term.evidence_group,
                        }
                        for term in item.rank_terms
                    ],
                    "relations": [
                        {
                            "target": relation.target,
                            "kind": relation.kind,
                            "strength": relation.strength,
                            "scope": relation.scope,
                            "condition_facts": list(relation.condition_facts),
                            "unknown_policy": relation.unknown_policy,
                        }
                        for relation in item.relations
                    ],
                }
                for item in self.decision_ir
            ],
        }
        if self.consumer_ir is not None:
            result["consumer_ir"] = self.consumer_ir.as_dict()
        return result


def _load_supporting_sources() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name in SUPPORTING_SOURCES:
        path = DECISIONS / name
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != 1:
            raise ValueError(f"辅助合同 {name} schema 必须为 1")
        result[name] = data
    return result


def _reader_signature(reader: decision_rules.Reader) -> tuple[object, ...]:
    """Identify the observation, independently of the file reusing it.

    Boolean unit spellings and parameter order have the same engine meaning;
    every other field participates in identity, including numeric validity.
    """
    return (
        reader.engine,
        reader.scope,
        "boolean" if reader.unit in {"flag", "boolean"} else reader.unit,
        reader.kind,
        reader.argument,
        reader.minimum,
        reader.maximum,
        reader.path,
        reader.value_field,
        tuple(sorted(reader.parameters)),
    )


def _declared_reader_matches(fact: EvidenceSpec, reader: decision_rules.Reader) -> bool:
    """A direct declaration may reuse a reader, but cannot flatten its meaning."""
    fact_kind = "number" if fact.kind == "ratio" else fact.kind
    units_match = fact.unit == reader.unit or {fact.unit, reader.unit} <= {"flag", "boolean"}
    if (
        not units_match
        or fact.scope != reader.scope
        or fact_kind != reader.kind
        or fact.minimum != reader.minimum
        or fact.maximum != reader.maximum
        or reader.path
        or reader.parameters
        or reader.value_field is not None
    ):
        return False
    expected = reader.expression("=", True) if reader.kind == "boolean" else reader.engine
    return "".join(fact.trigger.split()) == "".join(expected.split())


def _reader_facts(
    model_facts: tuple[EvidenceSpec, ...],
    *,
    information: decision_rules.RuleSet | None = None,
    adapters: decision_adapters.AdapterSet | None = None,
) -> tuple[EvidenceSpec, ...]:
    """从 information/adapters 的 readers 补齐事实签名，不复制业务谓词。"""
    for item in model_facts:
        if any(op in item.trigger for op in ("=", "<", ">")) and (
            item.kind != "boolean" or item.unit not in {"flag", "boolean"}
        ):
            raise ValueError(f"事实 {item.id} 与 reader 谓词类型不一致：比较结果必须是布尔值")
    by_id = {item.id: item for item in model_facts}
    declared_by_id = dict(by_id)
    observations: dict[str, tuple[decision_rules.Reader, str]] = {}
    information = decision_rules.load() if information is None else information
    adapters = decision_adapters.load() if adapters is None else adapters
    readers: list[tuple[str, Any, str]] = [
        ("information", reader, "mod/decisions/information.toml") for reader in information.readers
    ]
    for source, policy in adapters.policies:
        readers.extend(("adapter", reader, source) for reader in policy.readers)
    for owner, reader, source in readers:
        prior = observations.get(reader.key)
        if prior is not None and _reader_signature(prior[0]) != _reader_signature(reader):
            raise ValueError(f"事实 {reader.key} 的 reader 完整语义不一致：{prior[1]} / {source}")
        observations[reader.key] = (reader, source)
        declared = declared_by_id.get(reader.key)
        if declared is not None and not _declared_reader_matches(declared, reader):
            raise ValueError(f"事实 {reader.key} 与原版 reader 的完整语义不一致：{source}")
        if reader.key in by_id:
            continue
        trigger = reader.engine
        if reader.argument is not None:
            trigger += f" = {reader.argument}"
        elif reader.kind == "boolean":
            trigger += " = yes"
        by_id[reader.key] = EvidenceSpec(
            id=reader.key,
            identity=f"{owner}:{source}:{reader.key}",
            domain="derived" if reader.engine.startswith("sitai_") else "vanilla",
            source=source,
            scope=reader.scope,
            kind="ratio" if reader.unit == "ratio" else reader.kind,
            unit=reader.unit,
            refresh="consumer",
            unknown="vanilla",
            trigger=trigger,
            minimum=reader.minimum,
            maximum=reader.maximum,
            quality="derived" if reader.engine.startswith("sitai_") else "observed",
        )
    return tuple(by_id[key] for key in sorted(by_id))


def _reader_shapes(
    declared_facts: tuple[EvidenceSpec, ...] = (),
    *,
    information: decision_rules.RuleSet | None = None,
    adapters: decision_adapters.AdapterSet | None = None,
) -> dict[str, tuple[decision_rules.Reader, ...]]:
    """Expose original reader shape for support-source lowering guards."""
    information = decision_rules.load() if information is None else information
    adapters = decision_adapters.load() if adapters is None else adapters
    result: dict[str, list[decision_rules.Reader]] = {}
    for reader in information.readers:
        result.setdefault(reader.key, []).append(reader)
    for _source, policy in adapters.policies:
        for reader in policy.readers:
            result.setdefault(reader.key, []).append(reader)
    # Direct facts.toml predicates are a separate explicit source, not the
    # flattened adapter evidence. Admit only one scalar's bounded predicate, and never
    # overwrite a raw Reader (whose full scope/path must still be checked).
    for fact in declared_facts:
        engine = evidence_source.scalar_predicate_engine(fact.trigger)
        if fact.id not in result and fact.scope == "root" and engine:
            result[fact.id] = [
                decision_rules.Reader(
                    key=fact.id,
                    engine=engine,
                    scope="root",
                    unit=fact.unit,
                    kind="boolean",
                )
            ]
    return {key: tuple(value) for key, value in result.items()}


def _action_context_readers(
    action: decision_ir.ConsumerDecisionIR,
    context: decision_ir.EvaluationContext,
    declared_facts: tuple[EvidenceSpec, ...],
    signals: support_signals.SupportSignals,
    original_readers: tuple[decision_rules.Reader, ...],
) -> tuple[tuple[str, str, str, str], ...]:
    """Resolve every card input to existing readers, including costs and aliases."""
    keys = {
        *action.requires_all,
        *action.requires_any,
        *action.blocked_by,
        *action.exit_when,
        *action.consumes,
        *(term.fact for term in action.rank_terms),
        *(term.fact for term in (*action.commitment_when, *action.political_when)),
        *(fact for relation in action.relations for fact in relation.condition_facts),
    }
    aliases = {item.alias: item.source_fact for item in signals.signals}
    declared = {item.id: item for item in declared_facts}
    originals = {reader.key: reader for reader in original_readers}
    result: set[tuple[str, str, str, str]] = set()
    for key in sorted(keys):
        source_key = aliases.get(key, key)
        reader = originals.get(source_key)
        if reader is None:
            fact = declared.get(source_key)
            engine = evidence_source.scalar_predicate_engine(fact.trigger) if fact else None
            # A declared one-scalar predicate may reuse that original scalar's
            # signature; its result being boolean does not change the getter.
            candidates = {
                _reader_signature(item): item
                for item in original_readers
                if fact is not None
                and item.engine == engine
                and item.scope == fact.scope
                and not item.path
                and item.argument is None
                and not item.parameters
                and item.value_field is None
            }
            if (
                not candidates
                and fact is not None
                and re.fullmatch(r"[a-z][a-z0-9_]*\s*=\s*(?:yes|no)", fact.trigger)
                and fact.kind == "boolean"
                and fact.unit in {"flag", "boolean"}
            ):
                # The declaration is the actual boolean source template. Keep
                # its engine identity; never borrow a similarly named reader.
                reader = decision_rules.Reader(
                    key=source_key,
                    engine=cast("str", engine),
                    scope=fact.scope,
                    unit="boolean",
                    kind="boolean",
                )
                decision_interfaces.reader_scope(reader, ())
            elif len(candidates) != 1:
                raise ValueError(f"显式行动 {action.action_id} 缺少唯一真实读取器：{key}")
            else:
                reader = next(iter(candidates.values()))
        reader = replace(reader, key=key)
        result.update(
            validate_context_readers(action.field, context, {key: reader}, (), input_keys=(key,))
        )
    return tuple(sorted(result))


def _production_inventory(
    *,
    information: decision_rules.RuleSet | None = None,
    adapters: decision_adapters.AdapterSet | None = None,
) -> tuple[tuple[ProductionConsumer, ...], int, dict[str, str]]:
    consumers: list[ProductionConsumer] = []
    fingerprints: dict[str, str] = {}
    total = 0
    info = decision_rules.load() if information is None else information
    fingerprints["information"] = info.source_sha256
    for field, rules in info.groups().items():
        consumers.append(
            ProductionConsumer(
                id=f"information:{'.'.join(field)}",
                field=field,
                source="mod/decisions/information.toml",
                scope="root",
                operation=rules[0].operation,
                rule_count=len(rules),
                max_delta=0.5,
                vanilla_tail="retain_qualification_cost_random_execution",
            )
        )
        total += len(rules)
    adapters = decision_adapters.load() if adapters is None else adapters
    fingerprints["adapters"] = adapters.source_sha256
    for source, policy in adapters.policies:
        for field, rules in policy.groups().items():
            decree_program = (
                programs.enable(policy, source=source).consumer_programs[0]
                if source == "common/decrees/00_decree.txt"
                and field == ("decree_emergency_relief", "ai_weight")
                else None
            )
            consumers.append(
                ProductionConsumer(
                    id=f"adapter:{source}:{'.'.join(field)}",
                    field=field,
                    source=source,
                    scope="owner" if policy.actor_path else "root",
                    operation=rules[0].operation,
                    rule_count=len(rules),
                    max_delta=max(abs(decree_program.lower), abs(decree_program.upper))
                    if decree_program is not None
                    else 0.5,
                    vanilla_tail="retain_original_qualification_cost_execution",
                    numeric_policy="delta_to_native",
                    scalar_neutral=decree_program.neutral if decree_program is not None else None,
                    scalar_lower=decree_program.lower if decree_program is not None else None,
                    scalar_upper=decree_program.upper if decree_program is not None else None,
                )
            )
            total += len(rules)
    if any("political" in policy.enabled_domains for _, policy in adapters.policies):
        for program in adapters.event_programs:
            consumers.append(
                ProductionConsumer(
                    id=program.consumer_id,
                    field=program.field_path,
                    source=program.source,
                    scope="root",
                    operation="add",
                    rule_count=1,
                    max_delta=max(
                        abs(float(program.scalar.lower)), abs(float(program.scalar.upper))
                    ),
                    vanilla_tail="preserve",
                    numeric_policy=(
                        "absolute_new_aiweight_native_default_unknown"
                        if program.identity.explicit
                        else "delta_to_explicit_native_aiweight"
                    ),
                    scalar_neutral=float(program.scalar.neutral),
                    scalar_lower=float(program.scalar.lower),
                    scalar_upper=float(program.scalar.upper),
                )
            )
            total += 1
    if any("diplomacy" in policy.enabled_domains for _, policy in adapters.policies):
        for acceptance_program in adapters.acceptance_programs:
            consumers.append(
                ProductionConsumer(
                    id=acceptance_program.consumer_id,
                    field=acceptance_program.field_path,
                    source=acceptance_program.source,
                    scope="root",
                    operation="add",
                    rule_count=1,
                    max_delta=max(
                        abs(float(acceptance_program.scalar.lower)),
                        abs(float(acceptance_program.scalar.upper)),
                    ),
                    vanilla_tail="preserve",
                )
            )
            total += 1
    if any("economy" in policy.enabled_domains for _, policy in adapters.policies):
        for regional_program in adapters.regional_resource_programs:
            consumers.append(
                ProductionConsumer(
                    id=regional_program.consumer_id,
                    field=regional_program.field_path,
                    source=regional_program.source,
                    scope="root",
                    operation="add",
                    rule_count=1,
                    max_delta=float(regional_program.scalar.upper),
                    vanilla_tail="preserve",
                    numeric_policy="delta_to_native",
                    scalar_neutral=0,
                    scalar_lower=float(regional_program.scalar.lower),
                    scalar_upper=float(regional_program.scalar.upper),
                )
            )
            total += 1
    consumers.sort(key=lambda item: (item.source, item.field))
    return tuple(consumers), total, fingerprints


def _validate_supporting_sources(
    sources,
    consumers,
    relation_list,
    *,
    information: decision_rules.RuleSet | None = None,
    adapters: decision_adapters.AdapterSet | None = None,
) -> None:
    if set(sources) != set(SUPPORTING_SOURCES):
        raise ValueError("辅助合同来源必须完整且不能包含已退役或未知来源")
    raw_relations = sources["relations.toml"].get("relations", [])
    if not isinstance(raw_relations, list):
        raise ValueError("relations.toml 的 relations 必须是列表")
    listed: dict[tuple[str, str, str], tuple[object, ...]] = {}
    for item in raw_relations:
        if not isinstance(item, dict):
            raise ValueError("relations.toml 含无效关系项")
        raw_key = (item.get("source"), item.get("target"), item.get("kind"))
        strength = item.get("strength")
        scope = item.get("scope", "root")
        condition_facts = item.get("condition_facts", [])
        unknown_policy = item.get("unknown_policy", "vanilla")
        if (
            not all(isinstance(part, str) for part in raw_key)
            or raw_key in listed
            or isinstance(strength, bool)
            or not isinstance(strength, (int, float))
            or not math.isfinite(float(strength))
            or float(strength) <= 0
            or not isinstance(scope, str)
            or not isinstance(condition_facts, list)
            or any(not isinstance(fact, str) for fact in condition_facts)
            or not isinstance(unknown_policy, str)
        ):
            raise ValueError(f"relations.toml 含无效或重复关系：{raw_key}")
        key = cast("tuple[str, str, str]", raw_key)
        listed[key] = (
            float(strength),
            scope,
            tuple(condition_facts),
            unknown_policy,
            item.get("cause_id", ""),
            tuple(item.get("origins", ())),
        )
    actual = {
        (item.source, item.target, item.kind): (
            item.strength,
            item.scope,
            item.condition_facts,
            item.unknown_policy,
            item.cause_id,
            item.origins,
        )
        for item in relation_list
    }
    if set(listed) != set(actual) or any(listed[key] != actual[key] for key in listed):
        raise ValueError("relations.toml 与行动卡关系不一致")
    consumer_fields = {item.field for item in consumers}
    declared = sources["consumers.toml"].get("consumers", {})
    if declared and {item["field"] for item in declared.values()} != consumer_fields:
        raise ValueError("consumers.toml 与行动卡消费者字段不一致")
    localization = sources["localization.toml"]
    if localization.get("fallback") != "none" or len(localization.get("languages", [])) != 11:
        raise ValueError("本地化合同必须覆盖锁定本体的 11 种语言且不允许回退")
    families.load_contract(DECISIONS / "action_families.toml")
    layers.load(DECISIONS / "action_layers.toml")
    bindings.load(DECISIONS / "action_bindings.toml", information=information, adapters=adapters)
    domain_coverage.load(
        DECISIONS / "domain_actions.toml", information=information, adapters=adapters
    )


def load_model(
    *, facts_path: Path = FACTS, actions_path: Path = ACTIONS, baseline: str | None = None
) -> SituatedModel:
    declared_facts = evidence_source.load(facts_path)
    # A single invocation owns one policy snapshot. Helpers still load fresh
    # inputs when called independently; no cross-invocation cache is retained.
    information = decision_rules.load()
    adapters = decision_adapters.load()
    facts = _reader_facts(declared_facts, information=information, adapters=adapters)
    layer_model = layers.load(LAYERS)
    binding_rows = bindings.load(BINDINGS, information=information, adapters=adapters)
    consumers, actions = action_source.load(actions_path)
    tool_ids = {item.id for item in layer_model.tools}
    action_ids = {item.id for item in actions}
    if tool_ids != action_ids:
        raise ValueError(
            "action_layers.toml 必须为每张显式行动卡提供且只提供一个 tool："
            f"缺失={sorted(action_ids - tool_ids)} 多余={sorted(tool_ids - action_ids)}"
        )
    supporting = _load_supporting_sources()
    support_model = support_signals.load(
        supporting,
        facts,
        actions,
        reader_shapes=_reader_shapes(declared_facts, information=information, adapters=adapters),
    )
    facts = (*facts, *(item.evidence() for item in support_model.signals))
    goal_specs = support_signals.load_goals(supporting, actions, consumers)
    relation_list = relations.relations(
        actions,
        supporting["relations.toml"].get("relations", []),
    )
    relations.validate(actions, specs=supporting["relations.toml"].get("relations", []))
    layers.validate_links(layer_model, actions, relation_list)
    decision_rows = decision_ir.compile_decisions(actions, consumers, relation_list)
    _validate_supporting_sources(
        supporting, consumers, relation_list, information=information, adapters=adapters
    )
    fact_ids = {item.id for item in facts}
    relation_fact_ids = {fact for relation in relation_list for fact in relation.condition_facts}
    missing_relation_facts = sorted(relation_fact_ids - fact_ids)
    if missing_relation_facts:
        raise ValueError(f"行动关系引用了未知事实：{missing_relation_facts}")
    for action in actions:
        references = (
            *action.requires_all,
            *action.requires_any,
            *action.blocked_by,
            *action.exit_when,
        )
        missing = sorted(set(references) - fact_ids)
        if missing:
            raise ValueError(f"行动 {action.id} 引用了未知事实：{missing}")
        _validate_action_costs(action, {item.id: item for item in facts})
    baseline_text = baseline if baseline is not None else BASELINE.read_text(encoding="utf-8")
    parsed = parse_text(baseline_text)
    if parsed.errors:
        raise ValueError("默认策略底本无法解析")
    available = set(re.findall(r"^\s*([a-z][a-z0-9_]*)\s*=\s*\{", baseline_text, re.MULTILINE))
    missing = [consumer.field for consumer in consumers if consumer.field not in available]
    if baseline is None and missing:
        raise ValueError(f"消费者字段不在默认策略底本：{missing[0]}")
    production, count, production_hashes = _production_inventory(
        information=information, adapters=adapters
    )
    instances = action_instances.build(
        information,
        adapters,
        actions,
        consumer_fields={item.id: item.field for item in consumers},
        consumer_contracts={item.id: item for item in consumers},
    )
    observed_contexts = evaluation_contexts(baseline_text)
    observed_contexts.update(_frozen_strategy_contexts())
    observed_contexts.update(_frozen_institution_contexts(observed_contexts["institution_scores"]))
    observed_contexts.update(_frozen_strategy_score_contexts(observed_contexts))
    law_context = _frozen_law_context()
    company_context = _frozen_company_context()
    ship_modification_contexts = _frozen_ship_modification_contexts()
    treaty_contexts = _frozen_treaty_contexts()
    mobilization_contexts = _frozen_mobilization_contexts()
    native_action_contexts = _frozen_native_action_contexts()
    canal_contexts = _frozen_canal_contexts()
    native_decision_contexts = _frozen_native_decision_contexts()
    decree_contexts = _frozen_decree_contexts()
    famine_contexts = _frozen_famine_contexts()
    native_button_contexts = _frozen_native_button_contexts()
    context_readers = {}
    instance_contexts = {}
    for source, policy in (("mod/decisions/information.toml", information), *adapters.policies):
        readers = {reader.key: reader for reader in policy.readers}
        for rule in policy.rules:
            field = ".".join(rule.field).removeprefix("ai_strategy_default.")
            if (
                source
                in {
                    "mod/decisions/information.toml",
                    "common/ai_strategies/00_default_strategy.txt",
                }
                and (field == "institution_scores" or field.startswith("institution_scores."))
                and (field == "institution_scores" or field not in observed_contexts)
            ):
                raise ValueError(f"制度策略消费者不是精确普通数值子块：{field}")
            family = field.split(".")[0]
            if (
                source
                in {
                    "mod/decisions/information.toml",
                    "common/ai_strategies/00_default_strategy.txt",
                }
                and family
                in {
                    "wargoal_scores",
                    "secret_goal_scores",
                    "treaty_category_scores",
                    "strategic_region_stance_type_scores",
                }
                and (field == family or field not in observed_contexts)
            ):
                raise ValueError(f"目标策略消费者不是精确普通数值子块：{field}")
            context = (
                observed_contexts.get(field)
                if source
                in {
                    "mod/decisions/information.toml",
                    "common/ai_strategies/00_default_strategy.txt",
                }
                else law_context
                if source.startswith("common/laws/")
                and len(rule.field) == 2
                and rule.field[-1] == "ai_enact_weight_modifier"
                else company_context
                if source.startswith("common/company_types/")
                and len(rule.field) == 2
                and rule.field[-1] == "ai_weight"
                else ship_modification_contexts.get((source, field))
                or treaty_contexts.get((source, field))
                or mobilization_contexts.get((source, field))
                or native_action_contexts.get((source, field))
                or canal_contexts.get((source, field))
                or native_decision_contexts.get((source, field))
                or decree_contexts.get((source, field))
                or famine_contexts.get((source, field))
                or native_button_contexts.get((source, field))
            )
            if context is not None:
                instance_contexts[(source, rule.id)] = context
                reader_field = (
                    "ai_enact_weight_modifier"
                    if source.startswith("common/laws/")
                    else "company.ai_weight"
                    if source.startswith("common/company_types/")
                    else "ship_modification.ai_weight"
                    if (source, field) in ship_modification_contexts
                    else f"treaty.{'.'.join(rule.field[-2:])}"
                    if (source, field) in treaty_contexts
                    else field
                )
                context_readers[(source, rule.id)] = validate_context_readers(
                    reader_field,
                    context,
                    readers,
                    rule.conditions,
                    actor_path=policy.actor_path,
                    input_keys=tuple(rule.input_keys()),
                    source=source,
                    native_root=policy.native_root,
                )
    original_readers = (
        *information.readers,
        *(reader for _, policy in adapters.policies for reader in policy.readers),
    )
    scalar_card_fields = {
        "wanted_num_supply_ships",
        "max_ship_design_complexity",
        "recklessness",
        "wargoal_maneuvers_fraction",
        "aggression",
        "nationalization_desire",
        "max_active_stances",
        "wanted_marines",
        "economic_vs_government_spending_balance",
        "target_marine_formation_size",
        "unacceptable_infamy_level",
        "undesirable_infamy_level",
        "diplomatic_play_neutrality",
        "diplomatic_play_boldness",
    }
    for decision_row in decision_rows:
        if decision_row.field not in scalar_card_fields:
            continue
        context = observed_contexts[decision_row.field]
        key = ("mod/decisions/actions.toml", decision_row.action_id)
        instance_contexts[key] = context
        context_readers[key] = _action_context_readers(
            decision_row, context, declared_facts, support_model, original_readers
        )
    graph = ports.from_data(
        supporting["domain_ports.toml"],
        readers={
            (source, reader.key): reader
            for source, policy in (
                ("mod/decisions/information.toml", information),
                *adapters.policies,
            )
            for reader in policy.readers
        },
        writers=instance_contexts,
        source_hashes={
            source: policy.source_sha256
            for source, policy in (
                ("mod/decisions/information.toml", information),
                *adapters.policies,
            )
        },
        source_proofs={
            **{
                source: (
                    f"{source}:baseline_sha256={policy.baseline_sha256}",
                    f"src/pdx/decision_interfaces.py:sha256={hashlib.sha256(Path(decision_interfaces.__file__).read_bytes()).hexdigest()}",
                )
                for source, policy in adapters.policies
            },
            "mod/decisions/information.toml": (
                f"research/vanilla-ai/1.15.0/00_default_strategy.txt:sha256={hashlib.sha256(baseline_text.encode()).hexdigest()}",
                f"decision_interfaces.scripted_trigger_snapshot:sha256={hashlib.sha256(decision_interfaces.scripted_trigger_snapshot()).hexdigest()}",
                f"src/pdx/decision_interfaces.py:sha256={hashlib.sha256(Path(decision_interfaces.__file__).read_bytes()).hexdigest()}",
            ),
            ("mod/decisions/information.toml", "war_defeat"): (
                json.dumps(
                    decision_interfaces.war_memory_contract(), sort_keys=True, separators=(",", ":")
                ),
                f"src/pdx/decision_interfaces.py:sha256={hashlib.sha256(Path(decision_interfaces.__file__).read_bytes()).hexdigest()}",
            ),
        },
    )
    origin_map = {
        port.id: tuple(origin.identity for origin in graph.origins(port.id)) for port in graph.ports
    }
    # Facts, ports and the writer's executable contribution refer to one raw
    # identity. Predicate fact IDs/triggers remain stable and retain thresholds.
    fact_origins: dict[str, set[str]] = {}
    for port in graph.ports:
        if port.reader_key is not None:
            fact_origins.setdefault(port.reader_key[1], set()).update(origin_map[port.id])
        if port.id in {fact.id for fact in facts} and len(origin_map[port.id]) == 1:
            fact_origins.setdefault(port.id, set()).update(origin_map[port.id])
    facts = tuple(
        replace(fact, identity=next(iter(fact_origins[fact.id])))
        if len(fact_origins.get(fact.id, ())) == 1
        else fact
        for fact in facts
    )
    relation_list = relations.bind_origins(relation_list, origin_map)
    actions = _bind_action_origins(actions, graph, facts)
    decision_rows = decision_ir.compile_decisions(actions, consumers, relation_list)
    instances = tuple(
        replace(
            instance,
            evaluation_context=instance_contexts.get(
                (instance.source, instance.rule_id), instance.evaluation_context
            ),
        )
        for instance in instances
    )
    if any(
        instance.evaluation_context is not None
        and instance.consumer_field.removeprefix("ai_strategy_default.") in scalar_card_fields
        and instance.actor_scope != "root"
        for instance in instances
    ):
        raise ValueError("锁定策略消费者的 actor 必须保持国家 ROOT")
    action_ir = ir.from_rules(
        [("mod/decisions/information.toml", item) for item in information.rules]
        + [(source, item) for source, policy in adapters.policies for item in policy.rules]
    )
    consumer_bundle = decision_ir.compile_consumer_ir(
        actions,
        consumers,
        relation_list,
        action_ir,
        binding_rows,
        instances,
        source_hashes=production_hashes,
    )
    consumer_bundle = replace(
        consumer_bundle,
        writers=tuple(
            replace(
                writer,
                reader_context_bindings=context_readers.get((writer.source, writer.definition), ()),
                port_contributions=tuple(
                    ports.contribution(writer, use, graph)
                    for use in graph.uses
                    if (use.source, use.definition) == (writer.source, writer.definition)
                ),
            )
            for writer in consumer_bundle.writers
        ),
    )
    if adapters.supply is not None and any(
        "market" in policy.enabled_domains for _, policy in adapters.policies
    ):
        consumer_bundle = replace(
            consumer_bundle,
            writers=(
                *consumer_bundle.writers,
                *(
                    decision_ir.WriterDecisionIR(
                        writer_id=program.writer_id,
                        kind="supply_program",
                        source=program.source,
                        definition=program.good,
                        consumer_id=program.consumer_id,
                        field=program.field,
                        actor="root",
                        target="market_goods",
                        operation="append",
                        vanilla_tail="preserve",
                        owner="supply_plan",
                        supply_program=program,
                    )
                    for program in adapters.supply.actions()
                ),
            ),
        )
    if any("political" in policy.enabled_domains for _, policy in adapters.policies):
        consumer_bundle = replace(
            consumer_bundle,
            writers=(
                *consumer_bundle.writers,
                *(program.writer_ir() for program in adapters.event_programs),
            ),
        )
    if any("diplomacy" in policy.enabled_domains for _, policy in adapters.policies):
        consumer_bundle = replace(
            consumer_bundle,
            writers=(
                *consumer_bundle.writers,
                *(program.writer_ir() for program in adapters.acceptance_programs),
            ),
        )
    if any("economy" in policy.enabled_domains for _, policy in adapters.policies):
        consumer_bundle = replace(
            consumer_bundle,
            writers=(
                *consumer_bundle.writers,
                *(p.writer_ir() for p in adapters.regional_resource_programs),
            ),
        )
    migration_baseline.validate_bundle(consumer_bundle)
    consumer_bundle = joint_chain_contract.bind_bundle(
        consumer_bundle,
        ((joint_chain_contract.INFO_SOURCE, information), *adapters.policies),
    )
    goals = tuple((item.id, item.priority) for item in goal_specs)
    hashes = {
        "law_enact_context_document": _LAW_DOC_SHA256,
        "strategy_context_snapshot": engine_scope.STRATEGY_MANIFEST_SHA256,
        "company_context_snapshot": engine_scope.COMPANY_MANIFEST_SHA256,
        "building_defaults_snapshot": hashlib.sha256(building_defaults.snapshot()).hexdigest(),
        "current_native_resource_snapshot": resources._NATIVE_SHA256,
        "negotiation_native_snapshot": hashlib.sha256(negotiation_context.snapshot()).hexdigest(),
        "negotiation_native_generator": hashlib.sha256(
            Path(negotiation_context.__file__).read_bytes()
        ).hexdigest(),
        "building_defaults_generator": hashlib.sha256(
            Path(building_defaults.__file__).read_bytes()
        ).hexdigest(),
        "lj10_reader_snapshot": hashlib.sha256(
            decision_interfaces._LJ10_EVIDENCE.read_bytes()
        ).hexdigest(),
        "migration_baseline": hashlib.sha256(
            migration_baseline.DEFAULT_SOURCE.read_bytes()
        ).hexdigest(),
        "migration_retirements": hashlib.sha256(
            migration_baseline.RETIREMENTS_SOURCE.read_bytes()
        ).hexdigest(),
        "scripted_predicate_snapshot": hashlib.sha256(
            decision_interfaces.scripted_trigger_snapshot()
        ).hexdigest(),
        "facts": hashlib.sha256(facts_path.read_bytes()).hexdigest(),
        "actions": hashlib.sha256(actions_path.read_bytes()).hexdigest(),
        "action_layers": hashlib.sha256(LAYERS.read_bytes()).hexdigest(),
        "action_bindings": hashlib.sha256(BINDINGS.read_bytes()).hexdigest(),
        **production_hashes,
        **{
            name.removesuffix(".toml"): hashlib.sha256((DECISIONS / name).read_bytes()).hexdigest()
            for name in SUPPORTING_SOURCES
        },
    }
    event_observations: dict[tuple[str, str], tuple[object, ...]] = {}
    if any("political" in policy.enabled_domains for _, policy in adapters.policies):
        for program in adapters.event_programs:
            for reader in program.readers():
                key = (program.source, reader.key)
                signature = _reader_signature(reader)
                if key in event_observations and event_observations[key] != signature:
                    raise ValueError(f"事件共享观测身份冲突：{key}")
                event_observations[key] = signature
    return SituatedModel(
        facts,
        consumers,
        actions,
        relation_list,
        hashes,
        production,
        count,
        goals,
        supporting,
        instances,
        action_ir,
        goal_specs,
        layer_model,
        binding_rows,
        decision_rows,
        consumer_bundle,
        support_model,
        tuple(
            (source, reader.key, _reader_signature(reader))
            for source, policy in (
                ("mod/decisions/information.toml", information),
                *adapters.policies,
            )
            for reader in policy.readers
        )
        + tuple((source, key, signature) for (source, key), signature in event_observations.items())
        + tuple(
            (p.source, r.key, _reader_signature(r))
            for p in adapters.regional_resource_programs
            if any("economy" in policy.enabled_domains for _, policy in adapters.policies)
            for r in p.readers()
        )
        + tuple(
            (program.source, reader.key, _reader_signature(reader))
            for program in adapters.acceptance_programs
            if any("diplomacy" in policy.enabled_domains for _, policy in adapters.policies)
            for reader in program.readers()
        ),
        graph,
    )


def _condition(facts, ids):
    expressions = [facts[item].trigger for item in ids]
    if not expressions:
        return ""
    return expressions[0] if len(expressions) == 1 else "AND = { " + " ".join(expressions) + " }"


def _limit(action, facts, *, relation_guards: tuple[str, ...] = ()):
    all_expr = _condition(facts, action.requires_all)
    any_expr = (
        "OR = { " + " ".join(facts[item].trigger for item in action.requires_any) + " }"
        if action.requires_any
        else ""
    )
    blocked_expr = (
        "NOT = { OR = { " + " ".join(facts[item].trigger for item in action.blocked_by) + " } }"
        if action.blocked_by
        else ""
    )
    exit_expr = (
        "NOT = { OR = { " + " ".join(facts[item].trigger for item in action.exit_when) + " } }"
        if action.exit_when
        else ""
    )
    return (
        " AND = { "
        + " ".join(
            [
                "is_ai = yes",
                *(item for item in (all_expr, any_expr, blocked_expr, exit_expr) if item),
                *relation_guards,
            ]
        )
        + " }"
    )


def _validate_action_costs(action: ActionCard, facts: dict[str, EvidenceSpec]) -> None:
    for name in action.consumes:
        if name not in facts:
            raise ValueError(f"行动 {action.id} 成本事实不存在：{name}")
    for amount, predicates in (
        (action.commitment, action.commitment_when),
        (action.political_cost, action.political_when),
    ):
        if amount < 0 or (amount > 0 and not predicates):
            raise ValueError(f"行动 {action.id} 成本必须非负且有明确成本谓词")
        for predicate in predicates:
            fact = facts.get(predicate.fact)
            if fact is None or fact.scope != "root" or fact.unit != predicate.unit:
                raise ValueError(
                    f"行动 {action.id} 成本谓词的事实、单位或作用域无效：{predicate.fact}"
                )
            if (fact.kind == "boolean") != (type(predicate.value) is bool):
                raise ValueError(f"行动 {action.id} 成本谓词类型不匹配：{predicate.fact}")
            if type(predicate.value) is bool and predicate.op != "=":
                raise ValueError(f"行动 {action.id} 布尔成本只支持相等判断")
    if action.commitment == 0 and action.political_cost == 0 and not action.zero_cost_reason:
        raise ValueError(f"行动 {action.id} 零成本必须逐卡说明原因")


def _cost_state(
    predicates: tuple[CostPredicate, ...],
    values: Mapping[str, object],
    facts: Mapping[str, EvidenceSpec] | None = None,
) -> Truth:
    states: list[Truth] = []
    for predicate in predicates:
        value = values.get(predicate.fact)
        if type(value) is bool or type(predicate.value) is bool:
            valid = type(value) is bool and type(predicate.value) is bool
        else:
            valid = type(value) in (int, float) and math.isfinite(cast("float", value))
        spec = facts.get(predicate.fact) if facts is not None else None
        if valid and spec is not None and type(value) is not bool:
            number = cast("float", value)
            valid = (spec.minimum is None or number >= spec.minimum) and (
                spec.maximum is None or number <= spec.maximum
            )
        if not valid:
            states.append(None)
            continue
        if predicate.op == "=":
            states.append(value == predicate.value)
        else:
            left = cast("float", value)
            right = float(predicate.value)
            states.append(
                {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[
                    predicate.op
                ]
            )
    return truth_any(tuple(states)) if states else False


def _row_delta(
    row: decision_ir.ConsumerDecisionIR,
    values: Mapping[str, object],
    *,
    complement: float = 0.0,
    model: SituatedModel | None = None,
) -> float:
    """Compatibility adapter; scalar effects and aggregation live in programs."""
    if model is not None and model.support_signals is not None:
        values = model.support_signals.values(values)
    program = programs.card_value(row, complement=complement)
    facts = {fact.id: fact for fact in model.facts} if model is not None else None
    return programs.evaluate_scalar(
        program.scalar, _card_condition_values(program.conditions, values, facts)
    )


def _cost_trigger(predicates: tuple[CostPredicate, ...], facts: dict[str, EvidenceSpec]) -> str:
    terms = []
    for predicate in predicates:
        trigger = facts[predicate.fact].trigger
        if type(predicate.value) is bool:
            terms.append(trigger if predicate.value else f"NOT = {{ {trigger} }}")
        else:
            if any(operator in trigger for operator in ("=", "<", ">")):
                raise ValueError(f"数值成本必须引用原始 reader：{predicate.fact}")
            terms.append(f"{trigger} {predicate.op} {programs.numeric_literal(predicate.value)}")
    return " OR = { " + " ".join(terms) + " }"


def _cheap_cost_trigger(predicates, facts):
    bounds = []
    for predicate in predicates:
        fact = facts[predicate.fact]
        if type(predicate.value) is bool:
            continue
        if fact.minimum is not None:
            bounds.append(f"{fact.trigger} >= {programs.numeric_literal(fact.minimum)}")
        if fact.maximum is not None:
            bounds.append(f"{fact.trigger} <= {programs.numeric_literal(fact.maximum)}")
    return "AND = { " + " ".join(bounds) + " NOT = { " + _cost_trigger(predicates, facts) + " } }"


def _production_action_rows(model: SituatedModel) -> tuple[decision_ir.ConsumerDecisionIR, ...]:
    """Reject divergent explicit-card identities before any production lowering.

    The compatibility decision rows, canonical bundle rows and writer source map
    must describe the same actions.  A missing writer cannot leave an anonymous
    card in the generated output or the reference evaluator.
    """
    for binding in model.binding_rows:
        bindings.validate_disposition(binding)
    bundle = model.consumer_ir
    if bundle is None:
        raise ValueError("显式行动缺少 ConsumerIR bundle")
    rows = {row.action_id: row for row in model.decision_ir}
    canonical = {row.action_id: row for row in bundle.actions}
    if (
        len(rows) != len(model.decision_ir)
        or len(canonical) != len(bundle.actions)
        or rows != canonical
    ):
        raise ValueError("显式行动 DecisionIR 与 ConsumerIR 行重复或不一致")
    if len(set(bundle.writer_ids())) != len(bundle.writers):
        raise ValueError("ConsumerIR 生产 writer ID 重复")
    writers = [writer for writer in bundle.writers if writer.kind == "action_card"]
    by_action = {writer.definition: writer for writer in writers}
    if len(by_action) != len(writers) or set(by_action) != set(canonical):
        raise ValueError("显式行动缺少唯一 ConsumerIR writer")
    consumers = {consumer.id: consumer for consumer in model.consumers}
    if len(consumers) != len(model.consumers):
        raise ValueError("显式行动消费者身份重复")
    facts = {fact.id: fact for fact in model.facts}
    for action_id, row in canonical.items():
        if row.operation != "add":
            raise ValueError("显式联合消费者仅支持已核实的 add 投影；倍率必须使用独立原版适配")
        writer = by_action[action_id]
        consumer = consumers.get(row.consumer_id)
        if consumer is None or (
            writer.writer_id != f"card_{action_id}"
            or writer.source != "mod/decisions/actions.toml"
            or writer.consumer_id != row.consumer_id
            or writer.field != row.field
            or writer.operation != row.operation
            or writer.vanilla_tail != row.vanilla_tail
            or writer.actor != consumer.scope
            or writer.target != "none"
            or writer.owner != consumer.owner
            or writer.action != row
            or writer.legacy is not None
            or writer.predicates
            or row.field != consumer.field
            or row.operation != consumer.operation
            or row.vanilla_tail != consumer.vanilla_tail
        ):
            raise ValueError(f"显式行动 ConsumerIR writer 与消费者/行动不一致：{action_id}")
        goals = {goal.id: goal for goal in model.goal_specs}
        seen = set()
        for term in row.rank_terms:
            fact = facts.get(term.fact)
            goal = goals.get(term.goal)
            if (
                fact is None
                or fact.kind != "boolean"
                or fact.scope != "root"
                or {fact.unit, term.unit} - {"flag", "boolean"}
                or goal is None
                or row.consumer_id not in goal.consumer_bindings
                or term.fact in seen
            ):
                raise ValueError(
                    f"行动 rank 事实/目标/单位/消费者无效或重复：{action_id}:{term.fact}"
                )
            seen.add(term.fact)
    _validate_action_groups(bundle.actions, facts)
    return bundle.actions


def _direction(row: decision_ir.ConsumerDecisionIR) -> float:
    return -1.0 if row.base + row.opportunity < 0 else 1.0


def _bind_action_origins(actions, graph, facts):
    """Resolve only source claims proven by actual observed predicate inputs.

    Derived support aliases need their own source proof before participating in
    cause aggregation. Until then an explicit origin claim on them fails.
    """
    port_ids = {port.id for port in graph.ports}
    by_id = {port.id: port for port in graph.ports}

    def closure(keys):
        if not keys or any(key not in port_ids for key in keys):
            raise ValueError("行动因果来源尚无真实端口闭包")
        return tuple(sorted({origin.identity for key in keys for origin in graph.origins(key)}))

    def actual_closure(keys):
        for key in keys:
            if key not in by_id or by_id[key].reader is None:
                raise ValueError("行动事实来源尚未绑定可核查的观测端口")
            _assert_port_fact(facts, by_id[key])
        return closure(keys)

    result = []
    for action in actions:
        cause_origins = action.cause_origins
        if cause_origins:
            # This supported form has one conjunctive observed qualification.
            # Alternative, negative or synthetic demand qualification is not
            # silently relabelled as the declared positive source.
            if action.requires_any or action.blocked_by or action.exit_when:
                raise ValueError("行动因果来源尚未支持替代或否定资格闭包")
            actual = actual_closure(action.requires_all)
            if closure(cause_origins) != actual:
                raise ValueError("行动因果来源与实际资格闭包不一致")
            cause_origins = actual
        ranks = []
        for term in action.rank_terms:
            resolved_term = term
            if term.origins:
                actual = actual_closure((term.fact,))
                if closure(term.origins) != actual:
                    raise ValueError("rank来源与实际事实闭包不一致")
                resolved_term = replace(term, origins=actual)
            ranks.append(resolved_term)
        result.append(replace(action, cause_origins=cause_origins, rank_terms=tuple(ranks)))
    return tuple(result)


def _validate_action_groups(rows, facts) -> None:
    """Only declared identities deduplicate; equal predicates never imply identity."""
    groups: dict[tuple[str, str, str], object] = {}
    priorities: dict[tuple[str, str], set[int]] = {}
    for row in rows:
        for label in ("variant_group", "cause_group", "commitment_cost_id", "political_cost_id"):
            value = getattr(row, label)
            if not isinstance(value, str) or (
                value and not re.fullmatch(r"[a-z][a-z0-9_]*", value)
            ):
                raise ValueError(f"行动 {row.action_id} 的 {label} ID 无效")
        if type(row.variant_priority) is not int or (
            row.variant_priority and not row.variant_group
        ):
            raise ValueError("variant_priority 必须是显式 variant_group 的整数优先级")
        if row.variant_group:
            priority_key = (row.consumer_id, row.variant_group)
            used = priorities.setdefault(priority_key, set())
            if row.variant_priority in used:
                raise ValueError("同组 variant_priority 必须唯一")
            used.add(row.variant_priority)
        for category, name, signature in (
            ("variant", row.variant_group, _direction(row)),
            ("cause", row.cause_group, _direction(row)),
            *(
                ("evidence", term.evidence_group, (term.goal, term.unit, _direction(row)))
                for term in row.rank_terms
            ),
        ):
            if name:
                key = (row.consumer_id, category, name)
                if key in groups and groups[key] != signature:
                    raise ValueError(f"行动 {category} 去重组方向/目标/单位不一致：{name}")
                groups[key] = signature
        for identity, amount, predicates in (
            (row.commitment_cost_id, row.commitment, row.commitment_when),
            (row.political_cost_id, row.political_cost, row.political_when),
        ):
            if not identity:
                continue
            if amount <= 0 or not predicates:
                raise ValueError("显式 shared cost 必须包含正成本与谓词")
            specs = []
            for predicate in predicates:
                fact = facts.get(predicate.fact)
                if fact is None or fact.scope != "root" or fact.unit != predicate.unit:
                    raise ValueError("shared cost 事实作用域或单位无效")
                specs.append((predicate, fact))
            signature = (amount, _direction(row), frozenset(specs))
            key = (row.consumer_id, "cost", identity)
            if key in groups and groups[key] != signature:
                raise ValueError(f"shared cost 身份的金额/方向/谓词/作用域/单位不一致：{identity}")
            groups[key] = signature


def _ordered_relations(row: decision_ir.ConsumerDecisionIR) -> tuple[Relation, ...]:
    """Choose strongest complements first, with stable identities breaking ties."""
    for relation in row.relations:
        if (
            type(relation.strength) not in (int, float)
            or not math.isfinite(relation.strength)
            or relation.strength <= 0
        ):
            raise ValueError(f"行动关系强度必须为正有限数：{row.action_id}->{relation.target}")
    return tuple(
        sorted(
            row.relations,
            key=lambda relation: (
                relation.kind,
                -relation.strength,
                relation.target,
                relation.scope,
                relation.condition_facts,
                relation.unknown_policy,
            ),
        )
    )


def _effective_relations(row, by_id, enabled_fields):
    """Only explicit world-fact conditions carry causal relation semantics.

    An eligible target card is an intention, never evidence of completion.
    Unconditional historical links remain trace metadata until migrated.
    """
    return tuple(
        relation
        for relation in _ordered_relations(row)
        if relation.condition_facts
        and relation.target in by_id
        and by_id[relation.target].field in enabled_fields
    )


def _bound_card_ports(model, program):
    """Bind declared uses to exact existing cost/relation terms, never card base."""
    graph = model.port_graph if model is not None else None
    if graph is None:
        return {}
    observations = {
        (source, key): signature for source, key, signature in model.observation_contracts
    }
    for leaf in graph.ports:
        if leaf.reader is not None and observations.get(leaf.reader_key) != _reader_signature(
            leaf.reader
        ):
            raise ValueError("端口reader完整身份与实际生产观测不一致")
    owners = {}
    for group in program.scalar.groups:
        for term in group.terms:
            owners[term.id] = term.action_id
            for effect in term.effects:
                owners[effect.guard] = term.action_id
    support = (
        {signal.alias: signal for signal in model.support_signals.signals}
        if model.support_signals
        else {}
    )
    result = {}
    for use in graph.uses:
        if use.source != "mod/decisions/actions.toml":
            continue
        matches = []
        for condition in program.conditions:
            if owners.get(condition.id) != use.definition:
                continue
            selector = (
                tuple(p.fact for p in condition.cost) if use.role == "cost" else condition.facts
            )
            if selector != use.selector:
                continue
            if use.role == "cost":
                leaves = graph.leaves(use.port)
                expected = []
                for predicate in condition.cost:
                    signal = support.get(predicate.fact)
                    if signal is None or signal.mode != "value":
                        raise ValueError("成本端口必须对应真实value support源")
                    candidates = [
                        leaf
                        for leaf in leaves
                        if leaf.reader_key is not None and leaf.reader_key[1] == signal.source_fact
                    ]
                    if len(candidates) != 1:
                        raise ValueError("成本端口与实际support原始输入不匹配")
                    reader = candidates[0].reader
                    if (
                        reader.unit != predicate.unit
                        or candidates[0].op != predicate.op
                        or candidates[0].expected != predicate.value
                    ):
                        raise ValueError("成本端口与实际term单位/阈值不等价")
                    expected.append(signal.source_fact)
                if len(leaves) != len(expected):
                    raise ValueError("成本端口含未声明额外谓词")
            elif use.role == "relation":
                if set(use.selector) != {leaf.id for leaf in graph.leaves(use.port)}:
                    raise ValueError("关系端口与实际关系事实不等价")
                for leaf in graph.leaves(use.port):
                    _assert_port_fact(model.facts, leaf)
            else:
                continue
            matches.append(condition.id)
        if matches:
            if len(matches) != 1:
                raise ValueError("端口使用无法唯一定位具体card term")
            result[matches[0]] = use
        elif use.definition in owners.values():
            # A disabled relation may intentionally remove its term.
            if use.role != "relation":
                raise ValueError("端口缺少实际card cost term")
    return result


def _assert_port_fact(facts, port):
    """A named observed predicate must retain the exact raw-reader expression."""
    fact = next((fact for fact in facts if fact.id == port.id), None)
    reader = port.reader
    if reader is None:
        raise ValueError("事实端口必须绑定原始reader")
    condition = reader.expression(port.op, port.expected)
    bounds = [
        reader.expression(op, bound)
        for op, bound in ((">=", reader.minimum), ("<=", reader.maximum))
        if bound is not None
    ]
    expected_trigger = f"AND = {{ {' '.join((*bounds, condition))} }}" if bounds else condition
    if (
        fact is None
        or fact.trigger != expected_trigger
        or fact.quality != "observed"
        or fact.scope != reader.scope
        or reader.path
    ):
        raise ValueError("端口predicate兼容证据与实际原始事实不等价")


def _port_card_values(model, values):
    """Map public observed fact evidence to exact leaf predicates, never aliases."""
    graph = model.port_graph
    raw = {}
    predicate_values = {}
    for port in graph.ports:
        if port.reader is None or port.reader_key is None:
            continue
        key = port.reader_key[1]
        if key in values:
            raw[port.reader_key] = values[key]
        # Existing public reference facts include observed literacy predicates.
        # They are accepted only for these exact locked predicate definitions.
        if port.id in {"literacy_low", "literacy_ready"} and port.id in values:
            _assert_port_fact(model.facts, port)
            if key in values:
                expected = graph.evaluate(port.id, {port.reader_key: values[key]})
                if (
                    type(values[port.id]) is bool
                    and expected is not None
                    and values[port.id] != expected
                ):
                    raise ValueError("原始数值与已观测端口谓词证据冲突")
            else:
                predicate_values[port.id] = values[port.id]
    return raw, predicate_values


def _card_condition_values(conditions, values, facts, *, model=None, program=None):
    """Adapt three-valued card inputs to the common scalar guard contract."""
    result = {}
    bound = _bound_card_ports(model, program) if program is not None else {}
    raw, predicate_values = _port_card_values(model, values) if bound else ({}, {})
    for condition in conditions:
        if condition.id in bound:
            use = bound[condition.id]
            state = model.port_graph.evaluate(use.port, raw, predicate_values=predicate_values)
            if use.role == "cost":
                result[condition.id] = state is False
                continue
            result[condition.id] = (
                (condition.row is None or _action_status(condition.row, values) is True)
                and all(_relation_conditions(link, values) is True for link in condition.enables)
                and state is True
            )
            continue
        if condition.cost:
            # Only proven absence permits the cheap branch; unknown stays expensive.
            result[condition.id] = _cost_state(condition.cost, values, facts) is False
        else:
            result[condition.id] = (
                (condition.row is None or _action_status(condition.row, values) is True)
                and all(_relation_conditions(link, values) is True for link in condition.enables)
                and all(values.get(fact) is True for fact in condition.facts)
            )
    return result


def _card_condition_texts(conditions, facts, *, model=None, program=None):
    """Keep exact world-fact qualification and scope lowering in the adapter."""
    result = {}
    bound = _bound_card_ports(model, program) if program is not None else {}
    for condition in conditions:
        if condition.id in bound:
            use = bound[condition.id]
            guard = model.port_graph.guard(use.source, use.definition, use.port)
            if use.role == "cost":
                result[condition.id] = guard.when_false
                continue
            guards = (
                *(_condition(facts, link.condition_facts) for link in condition.enables),
                guard.when_true,
            )
            body = (
                _limit(condition.row, facts, relation_guards=guards)
                if condition.row is not None
                else guard.when_true
            )
            result[condition.id] = "ROOT ?= { " + body + " }"
            continue
        if condition.cost:
            body = _cheap_cost_trigger(condition.cost, facts)
        elif condition.row is None:
            body = _condition(facts, condition.facts)
        else:
            guards = tuple(
                _condition(facts, link.condition_facts) for link in condition.enables
            ) + ((_condition(facts, condition.facts),) if condition.facts else ())
            body = _limit(condition.row, facts, relation_guards=guards)
        result[condition.id] = "ROOT ?= { " + body + " }"
    return result


def _card_program(consumer, rows, by_id, enabled):
    if len(rows) > consumer.budget:
        raise ValueError(f"消费者 {consumer.id} 的行动数超过预算；不能静默丢弃候选")
    links = {row.action_id: _effective_relations(row, by_id, enabled) for row in rows}
    return programs.card_program(consumer, rows, links)


def strategy_overlay(
    model: SituatedModel,
    *,
    enabled_consumer_fields: set[str] | frozenset[str] | None = None,
) -> dict[str, str]:
    """Adapt card guards, then lower the common scalar consumer program."""
    rows = _production_action_rows(model)
    facts = {fact.id: fact for fact in model.facts}
    by_id = {row.action_id: row for row in rows}
    enabled = (
        frozenset(consumer.field for consumer in model.consumers)
        if enabled_consumer_fields is None
        else frozenset(enabled_consumer_fields)
    )
    output = {}
    for consumer in model.consumers:
        if consumer.field not in enabled:
            continue
        declared = sorted(
            (row for row in rows if row.consumer_id == consumer.id),
            key=lambda row: row.action_id,
        )
        program = _card_program(consumer, declared, by_id, enabled)
        intro = "".join(
            f"\t\t# ACTION {row.action_id} [{row.domain}]; {row.explanation}\n" for row in declared
        )
        output[consumer.field] = programs.render_scalar(
            program.scalar,
            _card_condition_texts(program.conditions, facts, model=model, program=program),
            ai_guard="ROOT ?= { is_ai = yes }",
            style="cards",
            domain=consumer.domain,
            intro=intro,
        )
    return output


def compile_policy(
    policy: decision_rules.RuleSet,
    source: object | None = None,
    config_model: SituatedModel | None = None,
):
    """返回 ``(RuleSet, contract)``；谓词沿用原版 RuleSet，字段一次有界写入。"""
    model = config_model or load_model()
    _production_action_rows(model)
    policy = decision_ir.lower_legacy(
        policy, model.consumer_ir, source=str(source) if source is not None else None
    )
    source_key = str(source) if source is not None else None
    # Rule IDs are only unique inside their source file.  Resolving by the
    # pair is part of the production contract; a same-named adapter rule must
    # never silently borrow the information rule's IR row.
    ir_by_key = {(item.source, item.action_id): item for item in model.action_ir}
    binding_by_id = {(item.source, item.definition): item for item in model.binding_rows}
    writer_by_key = {
        (item.source, item.definition): item
        for item in (model.consumer_ir.writers if model.consumer_ir is not None else ())
        if item.kind == "rule_action"
    }
    owner_by_key = {(item.source, item.rule_id): item.owner for item in model.action_instances}
    compiled_rules = []
    field_contract = []
    for field, rules in policy.groups().items():
        for rule in rules:
            ir_item = (
                ir_by_key.get((source_key, rule.id))
                if source_key is not None
                else next(
                    (item for item in ir_by_key.values() if item.action_id == rule.id),
                    None,
                )
            )
            binding = (
                binding_by_id.get((str(source), rule.id))
                if source is not None
                else next((item for item in model.binding_rows if item.definition == rule.id), None)
            )
            writer = (
                writer_by_key.get((source_key, rule.id))
                if source_key is not None
                else next(
                    (item for item in writer_by_key.values() if item.definition == rule.id),
                    None,
                )
            )
            if ir_item is None or binding is None or writer is None:
                raise ValueError(f"生产规则缺少 IR/绑定：{rule.id}")
            actor_path = {"root": (), "owner": ("owner",)}.get(writer.actor)
            if actor_path is None or policy.actor_path != actor_path:
                raise ValueError(f"生产 actor 路径与冻结 IR 不一致：{writer.source}:{rule.id}")
            context = writer.evaluation_context
            root_binding = (
                next(
                    (
                        binding
                        for binding in (context.actor_scope, *context.auxiliary_scopes)
                        if binding is not None and binding.name == "root"
                    ),
                    None,
                )
                if context is not None
                else None
            )
            expected_root = (
                root_binding.kind
                if root_binding is not None
                else "state"
                if writer.actor == "owner"
                else "country"
            )
            if policy.native_root != expected_root:
                raise ValueError(f"生产原生ROOT类型与冻结IR不一致：{writer.source}:{rule.id}")
            if writer.source == "common/mobilization_options/00_mobilization_option.txt":
                if context is None:
                    raise ValueError("医疗动员生产writer缺少编队及owner上下文")
                validate_context_readers(
                    writer.field,
                    context,
                    {reader.key: reader for reader in policy.readers},
                    rule.conditions,
                    actor_path=policy.actor_path,
                    input_keys=tuple(rule.input_keys()),
                    source=writer.source,
                    native_root=policy.native_root,
                )
            legacy = writer.legacy
            expected_predicates = tuple(
                (predicate.fact, predicate.op, predicate.value) for predicate in rule.conditions
            )
            if legacy is None or (
                legacy.source != writer.source
                or legacy.definition != rule.id
                or legacy.domain != rule.domain
                or legacy.consumer_id != binding.consumer
                or legacy.field != ".".join(rule.field)
                or legacy.actor != binding.actor
                or legacy.target != binding.target
                or legacy.operation != rule.operation
                or legacy.value != rule.value
                or legacy.predicates != expected_predicates
                or legacy.vanilla_tail != ir_item.vanilla_tail
            ):
                raise ValueError(f"重复写入或 ConsumerIR legacy 语义与生产规则不一致：{rule.id}")
            if (
                writer.consumer_id != binding.consumer
                or writer.field != ".".join(rule.field)
                or writer.operation != rule.operation
                or writer.vanilla_tail != ir_item.vanilla_tail
                or writer.owner != owner_by_key.get((writer.source, writer.definition))
            ):
                raise ValueError(f"重复写入或 ConsumerIR writer 与规则/绑定不一致：{rule.id}")
            if ir_item.field != ".".join(rule.field) or ir_item.operation != rule.operation:
                # 规则在进入统一 IR 后不允许被另一套适配语义悄悄改写。
                # 对外沿用“重复写入”这一合同词，便于调用方把字段漂移与
                # owner 冲突统一归入同一类硬失败，而不是把内部不一致当作
                # 可接受的降级。
                raise ValueError(f"IR 与生产规则不一致（重复写入或字段漂移）：{rule.id}")
            if source is not None and binding.source != str(source):
                raise ValueError(f"绑定来源与生产规则不一致：{rule.id}")
            # Legacy defaults preserve their actual ordering.  Explicit cards
            # have their own finite fact/goal rank, not a field-wide constant.
            compiled_rules.append(
                replace(
                    legacy.to_action_ir(),
                    priority=legacy.priority,
                    origin_priority=legacy.priority,
                )
            )
        field_contract.append(
            {
                "field": ".".join(field),
                "source": str(source or "rule_set"),
                "rule_count": len(rules),
                "write_once": True,
                "unknown_fallback": "vanilla",
                "player_fallback": "vanilla",
                "vanilla_tail": "retain_qualification_cost_random_execution",
                "max_rank_adjustment": 0,
            }
        )
    compiled_ir = tuple(sorted(compiled_rules, key=lambda item: item.action_id))
    compiled = replace(
        policy, rules=tuple(item.to_rule() for item in compiled_ir), semantic_ir=compiled_ir
    )
    program_sources = {item.source for item in compiled_ir}
    exact_source = source_key or (
        next(iter(program_sources)) if len(program_sources) == 1 else None
    )
    if exact_source is None and compiled_ir:
        raise ValueError("联合消费者编译需要精确来源，不能跨来源混合字段")
    observations = {
        (source, key): signature for source, key, signature in model.observation_contracts
    }
    required_readers = {key for rule in compiled.rules for key in rule.input_keys()}
    readers = {reader.key: reader for reader in compiled.readers}
    if len(readers) != len(compiled.readers) or required_readers - readers.keys():
        raise ValueError("生产 reader 身份重复或缺失")
    for key in sorted(required_readers):
        if exact_source is None or observations.get((exact_source, key)) != _reader_signature(
            readers[key]
        ):
            raise ValueError(f"生产 reader 完整身份与冻结 IR 不一致：{exact_source}:{key}")
    if model.port_graph is not None:
        relation_bindings, relation_readers = ports.bind_rule_relations(
            model.port_graph,
            source=exact_source or "empty",
            rules=compiled.rules,
            readers=readers,
            relations=model.relations,
            writers=writer_by_key,
        )
        compiled = replace(
            compiled, readers=relation_readers, rule_relation_bindings=relation_bindings
        )
        port_bindings = []
        for use in model.port_graph.uses:
            if use.source != exact_source or use.role not in {
                "need",
                "capacity",
                "recovery",
                "cost",
            }:
                continue
            port_rule = next((rule for rule in compiled.rules if rule.id == use.definition), None)
            if port_rule is None:
                raise ValueError(f"端口缺少具体规则term: {use.definition}")
            port_binding = ports.PortBinding(
                use.source,
                use.definition,
                use.port,
                model.port_graph,
                port_rule.required_known_facts,
                use.role,
                ports.contribution(
                    writer_by_key[(use.source, use.definition)], use, model.port_graph
                ),
                writer_by_key[(use.source, use.definition)],
            )
            port_binding.validate(port_rule, readers)
            port_bindings.append(port_binding)
        compiled = replace(compiled, port_bindings=tuple(port_bindings))
    compiled = programs.enable(compiled, source=exact_source or "empty")
    compiled_contract = {
        "schema": 2,
        "rule_set": "pdx.decision_rules.RuleSet",
        "source": str(source or "rule_set"),
        "source_sha256": policy.source_sha256,
        "baseline_sha256": policy.baseline_sha256,
        "active_rule_count": len(compiled.rules),
        "field_count": len(field_contract),
        "production_rule_count": model.production_rule_count,
        "production_consumer_count": len(model.production_consumers),
        "fields": field_contract,
        "goals": dict(model.goals),
        "relations": [
            {
                "source": item.source,
                "target": item.target,
                "kind": item.kind,
                "strength": item.strength,
            }
            for item in model.relations
        ],
        "relationship_depth": 2,
        "unknown": "preserve_unknown_and_fallback_vanilla",
        "player": "is_ai_only",
        "runtime_python": False,
        "world_scans": 0,
        "adjustment_application": "signed_envelope_concrete_consumer_program; explicit_joint_net",
        "consumer_programs": programs.contract(compiled),
        "ir_to_pdx": "consumer_ir_to_bounded_consumer_program",
        "domain_ports": [
            {
                "source": binding.source,
                "definition": binding.definition,
                "port": binding.port,
                "origins": [origin.identity for origin in binding.graph.origins(binding.port)],
            }
            for binding in compiled.port_bindings
        ],
        "rule_relations": [
            {
                "source": binding.projection.source,
                "definition": binding.projection.definition,
                "writer_id": binding.projection.writer_id,
                "port": binding.projection.port,
                "cause_id": binding.projection.cause_id,
                "amount": binding.projection.amount,
                "output_unit": binding.projection.output_unit,
                "dependency_domain": binding.projection.dependency_domain,
                "origins": list(binding.projection.origins),
                "readers": [
                    {
                        "source": origin.reader_source,
                        "key": origin.reader_key,
                        "signature": origin.signature,
                        "entity": origin.entity,
                        "entity_kind": origin.entity_kind,
                    }
                    for origin in binding.graph.origins(binding.projection.port)
                ],
            }
            for binding in compiled.rule_relation_bindings
        ],
    }
    return compiled, compiled_contract


def compile_sources(
    information: decision_rules.RuleSet,
    adapters: decision_adapters.AdapterSet,
    *,
    config_model: SituatedModel | None = None,
) -> tuple[tuple[tuple[str, decision_rules.RuleSet], ...], dict[str, object]]:
    """统一编译 information + adapters 的全部 RuleSet，并返回合同。"""
    model = config_model or load_model()
    compiled: list[tuple[str, decision_rules.RuleSet]] = []
    reports: list[dict[str, object]] = []
    item, report = compile_policy(information, "mod/decisions/information.toml", model)
    compiled.append(("mod/decisions/information.toml", item))
    reports.append(report)
    for source, policy in adapters.policies:
        item, report = compile_policy(policy, source, model)
        compiled.append((source, item))
        reports.append(report)
    return tuple(compiled), {
        "schema": 2,
        "rule_count": sum(len(item.rules) for _, item in compiled),
        "consumer_count": len(model.production_consumers),
        "reports": reports,
        "unknown": "vanilla",
        "player": "vanilla",
        "write_once": True,
        "relationship_depth": 2,
    }


def _action_conditions(
    action: ActionCard | decision_ir.ConsumerDecisionIR, values: Mapping[str, object]
) -> bool | None:
    """三值求值；未知不伪造负面证据。"""

    def test(name: str) -> bool | None:
        value = values.get(name)
        return value if type(value) is bool else None

    required = [test(name) for name in action.requires_all]
    blocked = [test(name) for name in action.blocked_by]
    if any(item is False for item in required) or any(item is True for item in blocked):
        return False
    options = [test(name) for name in action.requires_any]
    if options and all(item is False for item in options):
        return False
    if (
        any(item is None for item in required)
        or any(item is None for item in blocked)
        or (options and not any(item is True for item in options))
    ):
        return None
    return True


def _relation_conditions(relation: Relation, values: Mapping[str, object]) -> bool | None:
    """关系自己的条件采用三值逻辑；未知默认不额外改变原版。"""

    if not relation.condition_facts:
        return True
    states = tuple(
        None if name not in values or type(values[name]) is not bool else values[name]
        for name in relation.condition_facts
    )
    if any(item is False for item in states):
        return False
    if any(item is None for item in states):
        return None
    return True


def _action_status(action: decision_ir.ConsumerDecisionIR, values: Mapping[str, object]) -> Truth:
    """Return the same complete qualification state used by lowering."""

    exit_values: tuple[Truth, ...] = tuple(
        None if name not in values or type(values[name]) is not bool else cast("bool", values[name])
        for name in action.exit_when
    )
    exit_state = truth_not(truth_any(exit_values)) if exit_values else True
    return truth_all((_action_conditions(action, values), exit_state))


def evaluate_actions(
    model: SituatedModel,
    values: Mapping[str, object],
    *,
    is_ai: bool,
    enabled_consumer_fields: set[str] | frozenset[str] | None = None,
) -> dict[str, tuple[str, float]]:
    """Adapt card observations, then evaluate the common scalar program."""
    if type(is_ai) is not bool:
        raise ValueError("is_ai 必须为明确布尔值")
    rows = _production_action_rows(model)
    if not is_ai:
        return {}
    if model.support_signals is not None:
        values = model.support_signals.values(values)
    by_id = {row.action_id: row for row in rows}
    facts = {fact.id: fact for fact in model.facts}
    enabled = (
        frozenset(consumer.field for consumer in model.consumers)
        if enabled_consumer_fields is None
        else frozenset(enabled_consumer_fields)
    )
    result = {}
    for consumer in model.consumers:
        if consumer.field not in enabled:
            continue
        candidates = sorted(
            (row for row in rows if row.consumer_id == consumer.id),
            key=lambda row: row.action_id,
        )
        program = _card_program(consumer, candidates, by_id, enabled)
        delta = programs.evaluate_scalar(
            program.scalar,
            _card_condition_values(program.conditions, values, facts, model=model, program=program),
        )
        if delta != 0:
            result[consumer.field] = (program.scalar.action_id, delta)
    return result


def evaluate_policy(
    policy: decision_rules.RuleSet,
    values: Mapping[str, object],
    *,
    is_ai: bool,
    config_model: SituatedModel | None = None,
) -> dict[str, tuple[str, float]]:
    """Reference the default strategy's disjoint physical consumer owners.

    Explicit consumers replace old field writers even when their current net
    contribution is neutral. They are not percentage adjustments to old scores.
    """
    if type(is_ai) is not bool:
        raise ValueError("is_ai 必须为明确布尔值")
    model = config_model or load_model()
    _production_action_rows(model)
    if model.support_signals is not None:
        values = model.support_signals.values(values)
    policy, _contract = compile_policy(policy, config_model=model)
    baseline = decision_rules.evaluate_ir(policy, values, is_ai=is_ai)
    if not is_ai:
        return baseline
    owned_fields = {consumer.field for consumer in model.consumers}
    result = {field: value for field, value in baseline.items() if field not in owned_fields}
    result.update(evaluate_actions(model, values, is_ai=True))
    return result


def audit(model: SituatedModel) -> list[str]:
    problems = [
        f"消费者 {consumer.id} 超过行动预算"
        for consumer in model.consumers
        if sum(1 for action in model.actions if action.consumer == consumer.id) > consumer.budget
    ]
    if len(model.actions) > 32:
        problems.append("行动候选超过 32 个静态上限")
    if model.production_rule_count and model.production_rule_count < 1401:
        problems.append("生产事实源未覆盖 information + adapters 全部规则")
    return problems
