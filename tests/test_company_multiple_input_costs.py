"""Independent materials join once per good, using frozen native recipes.

BASF needs sulfur in two primary sectors; it is one physical market pressure.
The shared fertilizer/iron/sulfur inputs do not identify an active PM or bill.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import pytest

from pdx import company_sectors, config, decision_rules
from pdx.situated import pdx_eval, programs
from pdx.textio import normalized_text

pytestmark = pytest.mark.unit
# This fixture supplies the already tested reader vocabulary to the patcher;
# these aggregation tests make no new claim about native getter availability.
READER_WORDS = frozenset(
    [
        "market",
        "mg:grain",
        "market_goods_delta",
        "market_goods_pricier",
        "pop_type_percent_country",
        "laborers",
        "in_default",
        "dye",
        "fertilizer",
        "sulfur",
        "iron",
        "artillery",
        "engines",
        "steel",
        "coal",
        "explosives",
        "lead",
        "oil",
        "rubber",
        "ammunition",
        "automobiles",
    ]
)


@pytest.fixture(scope="module")
def frozen_profiles():
    # Read the independent native recipe evidence, without accepting its old
    # derived rules as the oracle for the new aggregation behavior.
    raw = json.loads(company_sectors.BASELINE.read_text(encoding="utf-8"))
    return company_sectors._thaw(raw)["profiles"]


def _policy(profile, native=None):
    rows = company_sectors._profile_rules({profile["id"]: profile}, company_sectors.DEFAULTS)
    source = profile["source"]
    native = native or f"{profile['id']} = {{ ai_weight = {{ value = 3 }} }}\n"
    policy = decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": hashlib.sha256(normalized_text(native).encode()).hexdigest(),
            "domains": {"market": True},
            "readers": company_sectors._readers(rows, company_sectors.DEFAULTS),
            "rules": [
                {key: value for key, value in row.items() if key != "source"} for row in rows
            ],
        },
        source_sha256="0" * 64,
    )
    return programs.enable(policy, source=source), native


def _engine(policy, values: Mapping[str, object], *, is_ai=True):
    root: dict[str, Any] = {"is_ai": is_ai}
    for reader in policy.readers:
        current = root
        for component in reader.path:
            current = current.setdefault(component, {})
        if reader.parameters:
            current[reader.engine] = {tuple(reader.parameters): values[reader.key]}
        else:
            current[reader.engine] = values[reader.key]
    return {"ROOT": root}


def _overlay(policy, native):
    patched = decision_rules.patch(
        native, policy, baseline=native, default_strategy=False, reader_words=READER_WORDS
    )
    field = ".".join(policy.consumer_programs[0].field)
    start = patched.index(f"# SITAI BEGIN information:{field}")
    end = patched.index(f"# SITAI END information:{field}", start)
    return "\n".join(patched[start:end].splitlines()[1:])


def _assert_value(profile, changes, expected):
    policy, native = _policy(profile)
    values = {reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers}
    values.update(changes)
    field = profile["field"]
    reference = decision_rules.evaluate(policy, values, is_ai=True).get(field)
    assert (reference[1] if reference else 1) == pytest.approx(expected)
    actual = pdx_eval.select(_overlay(policy, native), _engine(policy, values))
    assert actual.operation == "multiply"
    assert actual.delta == pytest.approx(expected)
    return policy


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"country_goods_iron_price": 0.5}, 0.85),
        ({"country_goods_iron_price": 0.5, "country_goods_sulfur_price": 0.5}, 0.70),
        ({"country_goods_iron_price": None, "country_goods_sulfur_price": 0.5}, 0.85),
        ({"country_goods_iron_price": 0.5, "country_goods_sulfur_price": None}, 0.85),
        ({"country_goods_iron_price": 0.25, "country_goods_sulfur_price": 0.5}, 0.85),
        (
            {"country_goods_iron_price": 0.5, "country_goods_sulfur_price": 0.5, "default": True},
            0.50,
        ),
    ],
)
def test_distinct_basf_inputs_and_default_join_with_local_unknown(
    frozen_profiles, changes, expected
):
    profile = frozen_profiles["company_basf"]
    assert profile["common_inputs"] == ["fertilizer", "iron", "sulfur"]
    _assert_value(profile, changes, expected)


def test_same_sulfur_in_two_basf_sectors_is_one_cost(frozen_profiles):
    profile = frozen_profiles["company_basf"]
    assert [sector["common_inputs"] for sector in profile["base_recipes"]] == [
        ["fertilizer", "sulfur"],
        ["iron", "sulfur"],
    ]
    _assert_value(profile, {"country_goods_sulfur_price": 0.5}, 0.85)


def test_three_materials_join_before_the_single_terminal_clamp(frozen_profiles):
    # 1 + .20 demand + .04 labor - 3*.15 inputs - .20 default = .59.
    # Clamping the cost subtotal .35 early would incorrectly produce .74.
    policy = _assert_value(
        frozen_profiles["company_basf"],
        {
            "country_goods_fertilizer_price": 0.5,
            "country_goods_iron_price": 0.5,
            "country_goods_sulfur_price": 0.5,
            "country_goods_dye_balance": -1,
            "country_goods_dye_price": 0.5,
            "industrial_workforce": 0.15,
            "default": True,
        },
        0.59,
    )
    metadata = decision_rules.contract(policy)
    assert metadata["active_rule_count"] == 9
    assert metadata["maximum_cases_per_field"] == 9
    program = policy.consumer_programs[0]
    assert len(program.groups) == 6
    assert program.lower == 0.5
    assert program.upper == pytest.approx(1.24)


def test_seven_distinct_materials_use_the_shared_terminal_floor(frozen_profiles):
    _assert_value(
        frozen_profiles["company_manfred_weiss"],
        {
            "country_goods_coal_price": 0.5,
            "country_goods_engines_price": 0.5,
            "country_goods_explosives_price": 0.5,
            "country_goods_iron_price": 0.5,
            "country_goods_lead_price": 0.5,
            "country_goods_oil_price": 0.5,
            "country_goods_rubber_price": 0.5,
            "country_goods_steel_balance": -1,
            "country_goods_steel_price": 0.5,
            "industrial_workforce": 0.15,
            "default": True,
        },
        0.5,
    )


def test_alternative_schneider_recipe_inputs_are_not_mandatory(frozen_profiles):
    profile = frozen_profiles["company_schneider_creusot"]
    # Foundries can use hardwood/iron OR steel/tools OR oil/steel/tools;
    # optional materials must not be promoted to unavoidable company costs.
    policy = _assert_value(profile, {}, 1)
    keys = {reader.key for reader in policy.readers}
    assert "country_goods_hardwood_price" not in keys
    assert "country_goods_oil_price" not in keys
    assert "country_goods_tools_price" not in keys


@pytest.mark.integration
def test_native_basf_overlay_preserves_player_and_disabled_domain(frozen_profiles):
    profile = frozen_profiles["company_basf"]
    native = (config.GAME / profile["source"]).read_text(encoding="utf-8-sig")
    frozen = json.loads(company_sectors.BASELINE.read_text(encoding="utf-8"))
    assert (
        hashlib.sha256(normalized_text(native).encode()).hexdigest()
        == frozen["sources"][profile["source"]]
    )
    policy, _ = _policy(profile, native)
    changes: dict[str, object] = {
        reader.key: False if reader.kind == "boolean" else 0 for reader in policy.readers
    }
    changes.update({"country_goods_iron_price": 0.5, "country_goods_sulfur_price": 0.5})
    actual = pdx_eval.select(_overlay(policy, native), _engine(policy, changes))
    assert actual.delta == pytest.approx(0.70)
    assert decision_rules.evaluate(policy, changes, is_ai=False) == {}
    assert (
        pdx_eval.select(_overlay(policy, native), _engine(policy, changes, is_ai=False)).fallback
        == "vanilla"
    )
    assert (
        decision_rules.patch(
            native, policy, baseline=native, enabled_domains=frozenset(), default_strategy=False
        )
        == native
    )
