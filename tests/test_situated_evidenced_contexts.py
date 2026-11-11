"""Field-local documentary contexts and the readers actually used in production."""

import json
from dataclasses import replace

import pytest

from pdx import config, decision_adapters, decision_rules, version_contracts
from pdx.situated import compiler

pytestmark = pytest.mark.unit
SOURCE = "common/ai_strategies/00_default_strategy.txt"
FORMATION = "combat_unit_group_weights.combat_unit_group_artillery"
FORMATION_COMMENTS = "# root = country\n# scope:military_formation = military formation"
PORT_COMMENTS = (
    "# root = country\n# scope:target_state = state\n# scope:target_country = state owner"
)


def _strategy(field, comments, value="{ value = 0 }"):
    return f"ai_strategy_default = {{\n{comments}\n{field} = {value}\n}}"


@pytest.mark.parametrize(
    ("field", "comments", "value", "lookup", "objects"),
    [
        (
            "treaty_port_value",
            PORT_COMMENTS,
            "{ value = 0 }",
            "treaty_port_value",
            {"target_state": "state", "target_country": "country"},
        ),
        (
            "combat_unit_group_weights",
            FORMATION_COMMENTS,
            "{ combat_unit_group_artillery = { value = 1 } }",
            FORMATION,
            {"military_formation": "military_formation"},
        ),
        (
            "conscript_battalion_ratio",
            FORMATION_COMMENTS,
            "{ value = 0.5 }",
            "conscript_battalion_ratio",
            {"military_formation": "military_formation"},
        ),
    ],
)
def test_new_contexts_require_field_local_proof_and_exact_object_types(
    field, comments, value, lookup, objects
):
    text = _strategy(field, comments, value)
    context = compiler.evaluation_contexts(text)[lookup]
    assert context.status == "observed"
    assert context.actor_scope is not None
    assert context.actor_scope.kind == "country"
    assert {b.name: b.kind for b in (*context.targets, *context.auxiliary_scopes)} == objects
    for binding in (context.actor_scope, *context.targets, *context.auxiliary_scopes):
        assert binding.source == SOURCE
        assert text.splitlines()[binding.line - 1].lstrip().startswith("#")
    for damaged in (
        text.replace(comments, "# no evidence"),
        text.replace(comments, comments + "\n# root = state"),
        text.replace(comments, comments + "\n# scope:military_formation = country"),
        text.replace(comments, comments + "\n" + comments),
        text.replace(f"{field} =", f"REPLACE:{field} ="),
        text.replace(f"{field} =", f"other = {{}} {field} ="),
        text.replace(f"{field} =", f"{field} = {{}}\n{field} ="),
        text + "\nai_strategy_default = {}",
    ):
        observed = compiler.evaluation_contexts(damaged).get(lookup)
        assert observed is None or observed.status != "observed"


@pytest.mark.parametrize(
    "children",
    [
        "combat_unit_group_artillery = {} combat_unit_group_artillery = {}",
        "REPLACE:combat_unit_group_artillery = {}",
        "combat_unit_group_artillery = 1",
        "other = { combat_unit_group_artillery = {} }",
    ],
)
def test_formation_context_projection_rejects_duplicate_prefixed_scalar_or_nested_children(
    children,
):
    text = _strategy("combat_unit_group_weights", FORMATION_COMMENTS, "{ " + children + " }")
    context = compiler.evaluation_contexts(text).get(FORMATION)
    assert context is None or context.status != "observed"


def test_formation_context_does_not_authorize_an_unrelated_map():
    text = _strategy("other_weights", FORMATION_COMMENTS, "{ group = { value = 1 } }")
    assert "other_weights.group" not in compiler.evaluation_contexts(text)


@pytest.fixture(scope="module")
def law_document():
    return compiler._LAW_DOC.read_text(encoding="utf-8")


def test_enact_document_proves_country_and_law_with_real_lines(law_document):
    context = compiler.law_evaluation_context(law_document)
    assert context == compiler._frozen_law_context()
    assert context.actor_scope is not None
    assert context.actor_scope.line == 11
    assert context.auxiliary_scopes[0].name == "law"
    assert context.auxiliary_scopes[0].line == 11
    assert "common/laws/readme.md:11" in context.evidence


def test_law_context_offline_evidence_is_tracked_and_independent_of_ignored_mirror():
    import subprocess

    relative = compiler._LAW_DOC.relative_to(config.REPO).as_posix()
    assert relative == "research/situated/victoria3-1.14.5-law-enact-context.md"
    # The exact small excerpt is intentionally retained; the full copyrighted
    # document stays in the ignored local mirror and is not distributed.
    lines = compiler._LAW_DOC.read_text(encoding="utf-8").splitlines()
    assert [index + 1 for index, line in enumerate(lines) if line] == [1, 11, 13]
    assert len(compiler._LAW_DOC.read_bytes()) < 300
    result = subprocess.run(
        ["git", "check-ignore", relative], cwd=config.REPO, capture_output=True, check=False
    )
    assert result.returncode == 1


@pytest.mark.parametrize("damage", ["heading", "wrong_type", "duplicate", "moved", "contradiction"])
def test_law_document_damage_keeps_context_unproven(law_document, damage):
    statement = "Root scope is AI country, scope:law contains the relevant law for that country"
    changes = {
        "heading": law_document.replace(
            "Documentation for ai_enact_weight_modifier", "Documentation for ai_will_do"
        ),
        "wrong_type": law_document.replace("scope:law contains", "scope:state contains"),
        "duplicate": law_document.replace(statement, statement + "\n" + statement),
        "moved": law_document.replace(statement, "") + "\n" + statement,
        "contradiction": law_document.replace(statement, statement + "\nRoot scope is state"),
    }
    assert compiler.law_evaluation_context(changes[damage]).status == "unknown"


def test_frozen_law_evidence_rejects_snapshot_and_live_byte_drift(monkeypatch, tmp_path):
    bad = tmp_path / "readme.md"
    bad.write_bytes(compiler._LAW_DOC.read_bytes() + b" ")
    with monkeypatch.context() as patch:
        patch.setattr(compiler, "_LAW_DOC", bad)
        with pytest.raises(ValueError, match="冻结文档"):
            compiler._frozen_law_context()
    live = tmp_path / "common/laws/readme.md"
    live.parent.mkdir(parents=True)
    live.write_bytes(b"wrong game documentation")
    with monkeypatch.context() as patch:
        patch.setattr(config, "GAME", tmp_path)
        with pytest.raises(ValueError, match="原版文档"):
            compiler._frozen_law_context()
    live.unlink()
    with monkeypatch.context() as patch:
        patch.setattr(config, "GAME", tmp_path)
        assert compiler._frozen_law_context().status == "observed"


def test_law_manifest_evidence_cannot_be_relabelled(monkeypatch, tmp_path):
    current = version_contracts.active_version() == "1.15.0"
    original = (
        compiler.REPO / "research/official-docs-1.15.0.manifest.json"
        if current
        else compiler._LAW_DOC_MANIFEST
    )
    manifest = json.loads(original.read_text(encoding="utf-8"))
    manifest["文档"]["game/common/laws/readme.md"]["sha256"] = "f" * 64
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    if current:
        target = tmp_path / "research/official-docs-1.15.0.manifest.json"
        target.parent.mkdir()
        target.write_bytes(path.read_bytes())
        monkeypatch.setattr(compiler, "REPO", tmp_path)
    else:
        monkeypatch.setattr(compiler, "_LAW_DOC_MANIFEST", path)
    with pytest.raises(ValueError, match="冻结文档"):
        compiler._frozen_law_context()


def test_port_leaf_reader_types_arguments_and_actor_paths_are_independently_checked():
    context = compiler.evaluation_contexts(_strategy("treaty_port_value", PORT_COMMENTS))[
        "treaty_port_value"
    ]
    access = decision_rules.Reader("access", "market_access", "target_state", "ratio", "number")
    predicate = (decision_rules.Predicate("access", "<", 0.9),)
    assert compiler.validate_context_readers(
        "treaty_port_value", context, {"access": access}, predicate
    ) == (("access", "target_state", "state", "target"),)
    for damaged in (replace(access, scope="target_country"), replace(access, unit="currency")):
        with pytest.raises(ValueError, match="读取器"):
            compiler.validate_context_readers(
                "treaty_port_value", context, {"access": damaged}, predicate
            )
    subject = decision_rules.Reader(
        "related", "is_subject_of", "root", "boolean", "boolean", argument="scope:target_state"
    )
    with pytest.raises(ValueError, match="必须为 country"):
        compiler.validate_context_readers(
            "treaty_port_value",
            context,
            {"related": subject},
            (decision_rules.Predicate("related", "=", True),),
        )
    root = decision_rules.Reader("need", "gdp", "root", "annual_gdp_currency", "number")
    with pytest.raises(ValueError, match="读取器"):
        compiler.validate_context_readers(
            "treaty_port_value",
            context,
            {"need": root},
            (decision_rules.Predicate("need", ">", 0),),
            actor_path=("owner",),
        )


@pytest.mark.parametrize(
    "field",
    [FORMATION, "conscript_battalion_ratio", "ai_enact_weight_modifier", "treaty_port_value"],
)
def test_new_contexts_validate_country_readers_and_reject_foreign_objects(field, law_document):
    text = _strategy(
        "combat_unit_group_weights", FORMATION_COMMENTS, "{ combat_unit_group_artillery = {} }"
    )
    contexts = compiler.evaluation_contexts(text)
    if field == "conscript_battalion_ratio":
        contexts = compiler.evaluation_contexts(_strategy(field, FORMATION_COMMENTS))
    elif field == "treaty_port_value":
        contexts = compiler.evaluation_contexts(_strategy(field, PORT_COMMENTS))
    context = (
        compiler.law_evaluation_context(law_document)
        if field == "ai_enact_weight_modifier"
        else contexts[field]
    )
    reader = decision_rules.Reader("need", "gdp", "root", "annual_gdp_currency", "number")
    predicates = (decision_rules.Predicate("need", "<", 0),)
    assert compiler.validate_context_readers(field, context, {"need": reader}, predicates) == (
        ("need", "root", "country", "actor"),
    )
    with pytest.raises(ValueError, match=r"作用域|上下文"):
        compiler.validate_context_readers(
            field, context, {"need": replace(reader, scope="overlord")}, predicates
        )
    with pytest.raises(ValueError, match=r"读取器|getter"):
        compiler.validate_context_readers(
            field,
            context,
            {
                "need": replace(
                    reader,
                    scope="law" if field == "ai_enact_weight_modifier" else "military_formation",
                )
            },
            predicates,
        )
    # Required-known inputs are real reader obligations even without a predicate.
    with pytest.raises(ValueError, match="读取器"):
        compiler.validate_context_readers(
            field, context, {"need": reader}, predicates, input_keys=("missing",)
        )


def test_enact_context_does_not_apply_to_boolean_law_qualification(law_document):
    reader = decision_rules.Reader("need", "gdp", "root", "annual_gdp_currency", "number")
    assert (
        compiler.validate_context_readers(
            "ai_will_do",
            compiler.law_evaluation_context(law_document),
            {"need": reader},
            (decision_rules.Predicate("need", ">", 0),),
        )
        == ()
    )


def test_production_new_contexts_bind_every_actual_reader():
    model = compiler.load_model()
    assert model.consumer_ir is not None
    policies = {
        "mod/decisions/information.toml": decision_rules.load(),
        **dict(decision_adapters.load().policies),
    }
    readers = {source: {r.key: r for r in policy.readers} for source, policy in policies.items()}
    rules = {(source, r.id): r for source, policy in policies.items() for r in policy.rules}
    selected = []
    for writer in model.consumer_ir.writers:
        if (
            writer.source.startswith("common/laws/")
            and writer.field.endswith(".ai_enact_weight_modifier")
        ) or writer.field.removeprefix("ai_strategy_default.") in {
            FORMATION,
            "combat_unit_group_weights.combat_unit_group_infantry",
            "combat_unit_group_weights.combat_unit_group_cavalry",
            "conscript_battalion_ratio",
            "treaty_port_value",
        }:
            selected.append(writer)
            assert writer.evaluation_context is not None
            assert writer.evaluation_context.status == "observed"
            rule = rules[(writer.source, writer.definition)]
            assert {row[0] for row in writer.reader_context_bindings} == rule.input_keys()
            assert all(key in readers[writer.source] for key, *_ in writer.reader_context_bindings)
    assert len(selected) >= 209
    for writer in model.consumer_ir.writers:
        if writer.source.startswith("common/laws/") and writer.field.endswith(".ai_will_do"):
            assert writer.evaluation_context is None


@pytest.mark.parametrize("offset", [("owner",), ("owner", "owner")])
def test_documented_country_actor_cannot_be_rebased_through_reader_owner(offset):
    context = compiler.evaluation_contexts(_strategy("treaty_port_value", PORT_COMMENTS))[
        "treaty_port_value"
    ]
    reader = decision_rules.Reader(
        "need", "gdp", "root", "annual_gdp_currency", "number", path=("owner",)
    )
    with pytest.raises(ValueError, match=r"actor|读取器|路径"):
        compiler.validate_context_readers(
            "treaty_port_value",
            context,
            {"need": reader},
            (decision_rules.Predicate("need", ">", 0),),
            actor_path=offset,
        )


@pytest.mark.parametrize(
    "contradiction", ["Root = state", "ROOT = state", "Scope:target_state = country"]
)
def test_context_contradictions_cannot_hide_behind_identifier_case(contradiction):
    text = _strategy("treaty_port_value", PORT_COMMENTS + "\n# " + contradiction)
    assert compiler.evaluation_contexts(text)["treaty_port_value"].status == "unknown"


@pytest.fixture(scope="module", autouse=True)
def _historical_1150_contract():
    """Keep the exact archived witness under its original version identity."""
    with version_contracts.select_version("1.15.0"):
        yield
