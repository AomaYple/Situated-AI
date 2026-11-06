"""Actual producer/PDX witnesses; optional normal compiler session owned by Task10."""

from __future__ import annotations

import os
import re
from dataclasses import replace
from functools import lru_cache

from task15_native_number import number
from test_remaining_joint_consumers import _block, _native_number, _overlay, _render
from test_situated_joint_witnesses import _facts

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules
from pdx.parser import parse_text
from pdx.situated import compiler, pdx_eval, programs

INFO = "mod/decisions/information.toml"
DEFAULT = "common/ai_strategies/00_default_strategy.txt"
SUBJECT = "common/ai_strategies/02_subject_diplomatic_strategies.txt"
INDUSTRY = "common/buildings/01_industry.txt"
SPECS = {
    INFO: {
        "institution_scores.institution_schools",
        "institution_scores.institution_social_security",
    },
    DEFAULT: {
        f"ai_strategy_default.institution_scores.institution_{name}"
        for name in (
            "police",
            "health_system",
            "home_affairs",
            "workplace_safety",
            "colonial_affairs",
        )
    }
    | {
        "ai_strategy_default.change_law_chance",
        "ai_strategy_default.negotiation_chance",
        "ai_strategy_default.subject_value",
        "ai_strategy_default.become_subject_value",
    },
    SUBJECT: {
        "ai_strategy_subject_overlord_compliance.weight",
        "ai_strategy_subject_maintain_autonomy.weight",
        "ai_strategy_subject_strengthen_self.weight",
    },
    INDUSTRY: {"building_textile_mill.ai_value"},
    "common/laws/01_taxation.txt": {"law_proportional_taxation.ai_enact_weight_modifier"},
    "common/laws/01_economic_system.txt": {"law_interventionism.ai_enact_weight_modifier"},
    "common/laws/02_free_speech.txt": {"law_right_of_assembly.ai_enact_weight_modifier"},
    "common/laws/00_internal_security.txt": {"law_national_guard.ai_enact_weight_modifier"},
}


@lru_cache(maxsize=1)
def build():
    """No model load in preparation; normal mode uses the unchanged real caller."""
    adapters = decision_adapters.load()
    policies = ((INFO, decision_rules.load()), *adapters.policies)
    normal = os.environ.get("TASK15_NORMAL_INTEGRATION") == "1"
    model = compiler.load_model() if normal else None
    inputs = decision_adapters.read_inputs(adapters)
    words = decision_interfaces.proven_reader_words() | frozenset(
        decision_adapters.reader_evidence(inputs)
    )
    result = {}
    for source, original in policies:
        if source not in SPECS:
            continue
        rows = tuple(rule for rule in original.rules if ".".join(rule.field) in SPECS[source])
        if not rows:
            continue
        used = {key for rule in rows for key in rule.input_keys()}
        selected = replace(
            original,
            rules=rows,
            readers=tuple(reader for reader in original.readers if reader.key in used),
            semantic_ir=(),
            consumer_programs=(),
            enabled_domains=frozenset(rule.domain for rule in rows),
        )
        compiled = (
            # Normal compilation owns the complete source and its declared
            # relations. Individual witnesses locate their exact field in the
            # complete output below; narrowing before compilation would remove
            # other real writers required by the source relation contract.
            compiler.compile_policy(original, source, model)[0]
            if normal
            else programs.enable(selected, source=source)
        )
        decision_interfaces.validate(compiled)
        native = compiler.BASELINE.read_text(encoding="utf8") if source == INFO else inputs[source]
        prepared = native
        if source == INDUSTRY or normal:
            prepared = decision_adapters._initialize(
                native,
                [
                    item
                    for item in adapters.initial_values
                    if item.source == source and (normal or ".".join(item.field) in SPECS[source])
                ],
                inputs,
                {},
            )
        if normal:
            scalar_fields = {
                field
                for scalar_source, field in adapters.scalar_values
                if scalar_source == source and field in compiled.groups()
            }
            if scalar_fields:
                prepared = decision_adapters._wrap_scalars(prepared, scalar_fields)
        generated = decision_rules.patch(
            prepared,
            compiled,
            baseline=native,
            default_strategy=source == INFO,
            country_policy=country_state.load(),
            reader_words=words,
            consumer_ir=model.consumer_ir if model is not None else None,
            consumer_source=source if normal else None,
        )
        result[source] = {
            "policy": compiled,
            "native": native,
            "prepared": prepared,
            "generated": generated,
            "model": model,
            "normal": normal,
        }
    assert set(result) == set(SPECS), set(SPECS) - set(result)
    return result


def defaults(policy, changes=None):
    values = {
        r.key: False if r.kind == "boolean" else max(r.minimum or 0, 0) for r in policy.readers
    }
    values.update(
        default=False,
        war=False,
        bureaucracy=0,
        net_surplus=0,
        legitimacy=60,
        state_owner_default=False,
        state_owner_clothes_balance=0,
        state_unemployment=0,
        state_market_access=1,
    )
    values.update(changes or {})
    return values


def numeric(row, field, values, *, base=1, ai=True, world=None):
    facts = _facts(row["policy"], values, is_ai=ai)
    if world:
        world(facts)
    actual = _native_number(base, _overlay(row["generated"], field), facts)
    expected_kind = (
        "add"
        if field.endswith(("ai_enact_weight_modifier", "subject_value", "become_subject_value"))
        else "multiply"
    )
    neutral = 0 if expected_kind == "add" else 1
    reference = decision_rules.evaluate(row["policy"], values, is_ai=ai).get(
        field, (expected_kind, neutral)
    )[1]
    return actual, reference, facts


def complete(row, path, facts):
    block = parse_text(row["generated"]).root
    for part in path.split("."):
        block = _block(block, part)
    script = (
        "# ACTION whole [native]; complete numeric block\nif = { limit = { always = yes } add = "
        + _render(block)
        + " }"
    )
    return pdx_eval.select(script, {**facts["ROOT"], **facts}).delta


def restored(text):
    return re.sub(
        r"(?m)^\s*# SITAI BEGIN information:[^\n]+\n.*?^\s*# SITAI END information:[^\n]+\n",
        "\n",
        text,
        flags=re.DOTALL,
    )


def native_number(row, path, facts):
    block = parse_text(row["generated"]).root
    for part in path.split("."):
        block = _block(block, part)
    return number(block, {**facts.get("ROOT", {}), **facts})
