"""Independent raw/AST witnesses for exactly two medical formation consumers."""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import pytest

from pdx import config
from pdx import mobilization_opportunities as mobilization
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import compiler
from pdx.textio import normalized_text

pytestmark = pytest.mark.unit
SOURCE = "common/mobilization_options/00_mobilization_option.txt"
DOC = "common/mobilization_options/mobilization_options.md"
OWNER = "common/on_actions/00_code_on_actions.txt"
COUNTRY = "events/tech_events/trench_warfare.txt"
MODIFIER = "common/modifier_type_definitions/00_modifier_types.txt"
FIRST = "mobilization_option_first_aid"
FIELD = "mobilization_option_field_hospitals"


@pytest.fixture(scope="module")
def baseline():
    return mobilization.load_baseline()


def test_context_reuse_preserves_identity_isolation_and_rechecks_pin(monkeypatch):
    compiler._mobilization_context_rows.cache_clear()
    load = mobilization.load_baseline
    reads = []

    def recorded_load(*, raw=None):
        reads.append(raw)
        return load(raw=raw)

    monkeypatch.setattr(mobilization, "load_baseline", recorded_load)
    first = compiler._frozen_mobilization_contexts()
    expected = {(row["source"], row["field"]) for row in mobilization.candidate_catalog().values()}
    assert set(first) == expected
    first.clear()
    assert set(compiler._frozen_mobilization_contexts()) == expected
    assert sum(raw is not None for raw in reads) == 1
    monkeypatch.setattr(
        mobilization,
        "BASELINE_SHA256_115"
        if mobilization.version_contracts.active_version() == "1.15.0"
        else "BASELINE_SHA256",
        "0" * 64,
    )
    with pytest.raises(ValueError, match="身份漂移"):
        compiler._frozen_mobilization_contexts()


@pytest.fixture
def raw():
    return {"sources": {}, "readers": {}, "rules": []}


def _inputs(baseline):
    return {source: bytes.fromhex(row["bytes"]) for source, row in baseline["originals"].items()}


def _ast(node):
    if isinstance(node, Scalar):
        return ["scalar", node.text, node.quoted]
    if isinstance(node, Assignment):
        return ["assignment", node.key, node.op, node.prefix, _ast(node.value)]
    assert isinstance(node, Block)
    return ["block", [_ast(item) for item in node.items]]


def _node(root, *path):
    for index, key in enumerate(path):
        found = root.all(key)
        assert len(found) == 1
        node = found[0]
        assert node.op == "="
        assert node.prefix is None
        if index < len(path) - 1:
            assert isinstance(node.value, Block)
            root = node.value
    return node


def test_frozen_raw_hashes_reconstruct_complete_originals(baseline):
    expected = {
        SOURCE: "e3e5d52365bc56ec270ab91a6f6f280a07eebd862187e8c604574ae89cc5df40",
        DOC: "5a424f091e616aa1afd688cc2f4e7da8aa8c5a86a35e0ea7ed5a880f6d2e540c",
        OWNER: "f5ddefa530c5bdd1a106b0accecdd97f231e046d2e0ac63ed08939f43944b57e",
        COUNTRY: "d859e625e0843d5d56d515b647e7833a0cb5eb3e5d85b233d4d1be697be1a93e",
        MODIFIER: "bb5a8d750d0bbcf6f778b85e6f3fdc7467b95391164e9413b8a8a2895cfb09ef",
    }
    if mobilization.version_contracts.active_version() == "1.15.0":
        expected = {
            SOURCE: "954cf50dc677fd61b0aa7da0d5cb9a32f870f2530d78d01cd56e544cdf511c97",
            DOC: "5a424f091e616aa1afd688cc2f4e7da8aa8c5a86a35e0ea7ed5a880f6d2e540c",
            OWNER: "ff43a0689abeec36d65076f4fc020f90172cbd60ac1a1d03a233d292edf6dc5b",
            COUNTRY: "d843ac86ea763f24c9fdd3af742becd49a379784f7b14572f6074b23ab8eaa4d",
            MODIFIER: "764aeaa461b09ba87bc57cb764300fb34f2a7945439fc2fe8317badedec7f40d",
        }
    assert set(baseline["originals"]) == set(expected)
    for source, original in _inputs(baseline).items():
        assert hashlib.sha256(original).hexdigest() == expected[source]
        assert baseline["originals"][source]["sha256"] == expected[source]
        assert (
            hashlib.sha256(normalized_text(original.decode("utf-8-sig")).encode()).hexdigest()
            == baseline["sources"][source]
        )
    assert baseline["sources"][SOURCE] == (
        "4dce33c917b2f2a323de96b7e51602d5d52262207af5f2736de3f17008537296"
        if mobilization.version_contracts.active_version() == "1.15.0"
        else "5b69e5c13fe0278122fc34b256838c5ae76c7db893404184b855accc34672a09"
    )


@pytest.mark.parametrize(
    ("identity", "basket", "recovery", "technology", "other"),
    [
        (FIRST, {"fabric": "1", "liquor": "2"}, "0.20", "triage", FIELD),
        (FIELD, {"opium": "2", "tools": "1"}, "0.40", "modern_nursing", FIRST),
    ],
)
def test_real_candidates_freeze_whole_ast_exact_basket_qualifications_and_lifecycle(
    baseline, identity, basket, recovery, technology, other
):
    parsed = parse_text(_inputs(baseline)[SOURCE].decode("utf-8-sig"))
    assert not parsed.errors
    row = baseline["candidates"][identity]
    definition = _node(parsed.root, identity)
    assert row["definition"]["ast"] == _ast(definition)
    assert row["goods"] == basket
    assert row["recovery_rate"] == recovery
    assert row["weight"]["ast"] == _ast(_node(parsed.root, identity, "ai_weight"))
    for section in definition.value.assignments():
        assert row["sections"][section.key]["ast"] == _ast(section)
    # Handwritten native expected semantics; no derive or metadata feeds these.
    expected = parse_text(f"""
        unlocking_technologies = {{ {technology} }}
        possible = {{
            NOT = {{ scope:military_formation = {{ has_mobilization_option = mobilization_option:{other} }} }}
            market ?= {{
                {"".join(f"mg:{good} ?= {{ has_potential_supply = yes }} " for good in basket)}
            }}
        }}
        upkeep_modifier = {{ {"".join(f"goods_input_{good}_add = {quantity} " for good, quantity in basket.items())} }}
        unit_modifier = {{ unit_recovery_rate_add = {recovery} }}
        ai_weight = {{ value = 1 }}
        on_activate_while_mobilized = {{
            custom_tooltip = {{
                text = mobilization_option_it_hurts_organization_to_add_medic_support_tt
                add_organization = {{ value = organization multiply = -0.25 }}
            }}
        }}
        on_deactivate = {{
            custom_tooltip = {{
                text = mobilization_option_it_hurts_morale_and_organization_when_you_remove_medic_support_tt
                every_combat_unit = {{ add_morale = {{ value = morale multiply = -0.5 }} }}
                add_organization = {{ value = organization multiply = -0.25 }}
            }}
        }}
    """)
    assert not expected.errors
    for section in expected.root.assignments():
        assert _ast(_node(definition.value, section.key)) == _ast(section)


def test_native_formation_owner_country_and_nonzero_utility_have_independent_witnesses(baseline):
    originals = _inputs(baseline)
    assert "root = military formation" in originals[DOC].decode("utf-8-sig")
    assert "after multiplication, this is compared against the monetary cost" in originals[
        DOC
    ].decode("utf-8-sig")
    assert "# Root = Military Formation\non_military_formation_created" in normalized_text(
        originals[OWNER].decode("utf-8-sig")
    )
    owner = parse_text(originals[OWNER].decode("utf-8-sig")).root
    event = parse_text(originals[COUNTRY].decode("utf-8-sig")).root
    modifier = parse_text(originals[MODIFIER].decode("utf-8-sig")).root
    assert (
        _ast(_node(owner, "on_military_formation_created", "effect", "if", "limit", "owner"))
        == baseline["scope_evidence"]["owner_block"]["ast"]
    )
    assert _node(event, "trench_warfare.1", "type").value.text == "country_event"
    assert (
        _node(
            event,
            "trench_warfare.1",
            "trigger",
            "any_scope_war",
            "any_scope_front",
            "any_military_formation",
            "owner",
        ).value.text
        == "ROOT"
    )
    assert _node(modifier, "unit_recovery_rate_add", "game_data", "ai_value").value.text == "5000"
    contract = baseline["contract"]
    assert contract["native_root"] == "military_formation"
    assert contract["actor"] == "country"
    assert contract["actor_path"] == ["owner"]
    assert contract["candidate"] == "static_definition"
    assert contract["target"] == "none"


def test_medical_rules_keep_handwritten_contract_with_additional_material_candidates(raw, baseline):
    derived = mobilization.derive(raw, baseline)
    assert len(derived["rules"]) == 72
    assert len(derived["readers"]) == 33
    assert {FIRST, FIELD} <= {row["id"] for row in derived["covered"]}
    assert len(derived["covered"]) == 15
    assert all(
        row["disposition"] == "new_consumer_integration_no_legacy_identity"
        for row in derived["covered"]
    )
    assert len(derived["uncovered"]) == 3
    assert len(baseline["native_identities"]) == 18
    assert derived["actors"] == {SOURCE: ["owner"]}
    assert not {"initial_values", "scalar_values", "contexts"} & derived.keys()
    for candidate, goods in (
        ("first_aid", ("fabric", "liquor")),
        ("field_hospitals", ("opium", "tools")),
    ):
        rules = {
            row["id"].removeprefix(f"mobilization_{candidate}_"): row
            for row in derived["rules"]
            if row["field"] == f"mobilization_option_{candidate}.ai_weight"
        }
        expected = {
            "war_need": (
                1.10,
                "mobilization_country_war_need",
                [{"fact": "mobilization_war", "op": "=", "value": True}],
            ),
            "default": (
                0.85,
                "mobilization_financing_pressure",
                [{"fact": "mobilization_default", "op": "=", "value": True}],
            ),
        }
        for good in goods:
            short = {"fact": f"mobilization_{good}_balance", "op": "<", "value": 0.0}
            expected[f"{good}_scarcity"] = (0.90, f"mobilization_material_{good}_pressure", [short])
            expected[f"{good}_price_pressure"] = (
                0.80,
                f"mobilization_material_{good}_pressure",
                [short, {"fact": f"mobilization_{good}_price", "op": ">", "value": 0.50}],
            )
        assert rules.keys() == expected.keys()
        for suffix, (value, cause, conditions) in expected.items():
            row = rules[suffix]
            assert row["value"] == value
            assert row["operation"] == "multiply"
            assert row["contribution_group"] == cause
            assert row["conditions"] == conditions
            assert row["required_known_facts"] == [
                "mobilization_owner_ai",
                *(f"mobilization_{good}_balance" for good in goods),
            ]
            assert row["source"] == SOURCE
            assert row["domain"] == "military"
    assert not any(spec["engine"] == "taking_loans" for spec in derived["readers"].values())


def test_readers_use_owner_and_complete_country_market_goods_path(raw, baseline):
    readers = mobilization.derive(raw, baseline)["readers"]
    for key, spec in readers.items():
        assert spec["scope"] == "root"
        if key in {"mobilization_owner_ai", "mobilization_war", "mobilization_default"}:
            assert spec["path"] == ["owner"]
            assert spec["kind"] == "boolean"
        else:
            good, tier = key.removeprefix("mobilization_").rsplit("_", 1)
            assert good in {
                "fabric",
                "liquor",
                "opium",
                "tools",
                "groceries",
                "meat",
                "wine",
                "sugar",
                "tobacco",
                "automobiles",
                "engines",
                "small_arms",
                "ammunition",
                "fertilizer",
                "oil",
            }
            assert spec == {
                "engine": "market_goods_delta" if tier == "balance" else "market_goods_pricier",
                "kind": "number",
                "scope": "root",
                "unit": "sell_minus_buy_orders" if tier == "balance" else "price_above_base_ratio",
                "path": ["owner", "market", f"mg:{good}"],
            }


@pytest.mark.parametrize(
    "reader",
    [
        "mobilization_owner_ai",
        "mobilization_war",
        "mobilization_default",
        "mobilization_fabric_balance",
        "mobilization_opium_price",
    ],
)
@pytest.mark.parametrize("mutation", ["path", "unit", "kind", "engine", "extra"])
def test_complete_reader_signature_rejects_tampering(raw, baseline, reader, mutation):
    expected = mobilization.derive(raw, baseline)
    raw["readers"] = copy.deepcopy(expected["readers"])
    assert mobilization.derive(raw, baseline) == expected
    raw["readers"][reader][mutation] = [] if mutation == "path" else "wrong"
    with pytest.raises(ValueError, match="reader"):
        mobilization.derive(raw, baseline)


@pytest.mark.parametrize(
    "mutation",
    [
        "raw_hash",
        "raw_bytes",
        "scope",
        "actor_guard",
        "goods",
        "quantity",
        "weight",
        "section",
        "identity",
        "extra",
        "source",
        "utility",
        "native_guard",
        "native_key",
    ],
)
def test_repin_cannot_hide_frozen_raw_ast_metadata_key_quantity_or_guard_tampering(
    baseline, tmp_path, monkeypatch, mutation
):
    data = copy.deepcopy(baseline)
    row = data["candidates"][FIRST]
    if mutation == "raw_hash":
        data["originals"][SOURCE]["sha256"] = "0" * 64
    elif mutation == "raw_bytes":
        data["originals"][SOURCE]["bytes"] += "20"
    elif mutation == "scope":
        data["contract"]["native_root"] = "country"
    elif mutation == "actor_guard":
        data["contract"]["actor_path"] = []
    elif mutation == "goods":
        row["goods"] = {"opium": "1", "tools": "2"}
    elif mutation == "quantity":
        row["goods"]["fabric"] = "3"
    elif mutation == "weight":
        row["weight"]["ast"][4][1][0][4][1] = "0"
    elif mutation == "section":
        row["sections"]["possible"]["ast"][4][1].clear()
    elif mutation == "identity":
        data["candidates"]["mobilization_option_forced_march"] = data["candidates"].pop(FIRST)
    elif mutation == "extra":
        row["fake_observed_casualties"] = True
    elif mutation == "source":
        data["sources"][SOURCE] = "0" * 64
    elif mutation == "utility":
        data["utility_evidence"]["ai_value"]["ast"][4][1] = "0"
    else:
        original = bytes.fromhex(data["originals"][SOURCE]["bytes"])
        original = (
            original.replace(
                b"has_mobilization_option = mobilization_option:mobilization_option_field_hospitals",
                b"has_mobilization_option = mobilization_option:fake",
                1,
            )
            if mutation == "native_guard"
            else original.replace(b"on_activate_while_mobilized", b"fake_activate", 1)
        )
        data["originals"][SOURCE] = {
            "bytes": original.hex(),
            "sha256": hashlib.sha256(original).hexdigest(),
        }
    path = tmp_path / "baseline.json"
    path.write_text(mobilization._canonical(data), encoding="utf-8", newline="\n")
    monkeypatch.setattr(
        mobilization,
        "BASELINE_115"
        if mobilization.version_contracts.active_version() == "1.15.0"
        else "BASELINE",
        path,
    )
    monkeypatch.setattr(
        mobilization,
        "BASELINE_SHA256_115"
        if mobilization.version_contracts.active_version() == "1.15.0"
        else "BASELINE_SHA256",
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    with pytest.raises(ValueError):
        mobilization.load_baseline()


def test_hash_pin_and_canonical_bytes_are_independent_guards(baseline, tmp_path, monkeypatch):
    path = tmp_path / "baseline.json"
    path.write_text(mobilization._canonical(baseline) + " ", encoding="utf-8", newline="\n")
    monkeypatch.setattr(
        mobilization,
        "BASELINE_115"
        if mobilization.version_contracts.active_version() == "1.15.0"
        else "BASELINE",
        path,
    )
    with pytest.raises(ValueError, match="身份漂移"):
        mobilization.load_baseline()
    monkeypatch.setattr(
        mobilization,
        "BASELINE_SHA256_115"
        if mobilization.version_contracts.active_version() == "1.15.0"
        else "BASELINE_SHA256",
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    with pytest.raises(ValueError, match="规范JSON"):
        mobilization.load_baseline()


def test_offline_derivation_preserves_callers_and_never_reads_game(raw, baseline, monkeypatch):
    before = copy.deepcopy((raw, baseline))
    expected = mobilization.derive(raw, baseline)
    monkeypatch.setattr(
        mobilization, "read_inputs", lambda _game: pytest.fail("offline read live game")
    )
    assert mobilization.derive(raw) == expected
    assert (raw, baseline) == before


@pytest.mark.parametrize(
    "mutation",
    ["new_file", "dlc_file", "missing_file", "bytes", "quantity", "weight", "owner_scope", "doc"],
)
def test_verify_game_rejects_source_set_raw_and_semantic_drift(baseline, tmp_path, mutation):
    for source, original in _inputs(baseline).items():
        path = tmp_path / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original)
    assert mobilization.verify_game(tmp_path) == baseline
    path = tmp_path / SOURCE
    if mutation in {"new_file", "dlc_file"}:
        path = (
            (tmp_path / "dlc/test/in_game/common/mobilization_options/extra.txt")
            if mutation == "dlc_file"
            else path.with_name("extra.txt")
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"# new native input\n")
    elif mutation == "missing_file":
        path.unlink()
    elif mutation == "owner_scope":
        path = tmp_path / OWNER
        path.write_bytes(
            path.read_bytes().replace(b"on_military_formation_created =", b"on_fake_created =")
        )
    elif mutation == "doc":
        path = tmp_path / DOC
        path.write_bytes(path.read_bytes().replace(b"root = military formation", b"root = country"))
    elif mutation == "bytes":
        path.write_bytes(path.read_bytes() + b"# raw drift\n")
    else:
        original = path.read_bytes()
        path.write_bytes(
            original.replace(b"goods_input_fabric_add = 1", b"goods_input_fabric_add = 3", 1)
            if mutation == "quantity"
            else original.replace(b"value = 1", b"value = 0", 1)
        )
    with pytest.raises((ValueError, FileNotFoundError)):
        mobilization.verify_game(tmp_path)


@pytest.mark.parametrize(
    "mutation",
    [
        "bool",
        "string",
        "nan",
        "infinity",
        "priority_fraction",
        "priority_range",
        "unknown",
        "missing",
        "benefit",
        "cost",
        "tier_order",
        "threshold",
        "huge_int",
    ],
)
def test_parameter_types_keys_directions_and_bounds_fail_closed(raw, baseline, mutation):
    params: dict[str, Any] = dict(mobilization.load_parameters())
    if mutation == "bool":
        params["war_need_multiplier"] = True
    elif mutation == "string":
        params["default_multiplier"] = "0.85"
    elif mutation == "nan":
        params["default_multiplier"] = float("nan")
    elif mutation == "infinity":
        params["default_multiplier"] = float("inf")
    elif mutation == "priority_fraction":
        params["priority_base"] = 300000.5
    elif mutation == "priority_range":
        params["priority_base"] = 9
    elif mutation == "unknown":
        params["free_healing"] = 2
    elif mutation == "missing":
        del params["default_multiplier"]
    elif mutation == "benefit":
        params["war_need_multiplier"] = 0.9
    elif mutation == "cost":
        params["default_multiplier"] = 1
    elif mutation == "tier_order":
        params["price_pressure_multiplier"] = 0.95
    elif mutation == "huge_int":
        params["default_multiplier"] = 10**1000
    else:
        params["pressure_price_threshold"] = -1
    with pytest.raises(ValueError):
        mobilization.derive(raw, baseline, parameters=params)


def test_source_conflicts_fail_closed(raw, baseline):
    raw["sources"][SOURCE] = "0" * 64
    with pytest.raises(ValueError, match="来源冲突"):
        mobilization.derive(raw, baseline)


def test_live_locked_sources_match_frozen_bytes_when_available(baseline):
    if not (config.GAME / DOC).is_file():
        pytest.skip("锁定原版安装不可用；离线原始证据已覆盖")
    assert mobilization.verify_game(config.GAME) == baseline
