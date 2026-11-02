"""Consumer context metadata is independent of historical writer identity."""

from dataclasses import replace

import pytest

from pdx import decision_adapters, decision_rules
from pdx.situated import compiler, decision_ir, migration_baseline

pytestmark = pytest.mark.unit
SOURCE = "common/ai_strategies/00_default_strategy.txt"


def _argument_policy(field, argument, *, engine="is_subject_of", scope="root", parameters=None):
    reader = {"engine": engine, "scope": scope, "unit": "boolean", "kind": "boolean"}
    if argument is not None:
        reader["argument"] = argument
    if parameters is not None:
        reader["parameters"] = parameters
    return decision_rules.from_data(
        {
            "schema": 1,
            "baseline_sha256": "0" * 64,
            "readers": {"argument_fact": reader},
            "domains": {"politics": True},
            "rules": [
                {
                    "id": "argument_probe",
                    "domain": "politics",
                    "field": field,
                    "priority": 1,
                    "value": 1.1,
                    "conditions": [{"fact": "argument_fact", "op": "=", "value": True}],
                    "why": "静态参数类型见证",
                    "counterexample": "禁止非国家上下文冒充国家参数",
                }
            ],
        },
        source_sha256="0" * 64,
    )


@pytest.mark.parametrize(
    ("field", "argument"),
    [
        ("negotiation_chance", "scope:law"),
        ("negotiation_chance", "scope:interest_group"),
        ("state_value", "scope:target_state"),
    ],
)
def test_production_reader_country_argument_rejects_other_object_kinds(field, argument):
    policy = _argument_policy(field, argument)
    context = compiler.evaluation_contexts(compiler.BASELINE.read_text(encoding="utf-8"))[field]
    with pytest.raises(ValueError, match=r"参数.*country"):
        compiler.validate_context_readers(
            field, context, {r.key: r for r in policy.readers}, policy.rules[0].conditions
        )


@pytest.mark.parametrize(
    ("field", "argument", "engine", "scope", "parameters"),
    [
        ("negotiation_chance", "root", "is_subject_of", "root", None),
        ("become_subject_value", "scope:overlord", "is_subject_of", "root", None),
        ("subject_value", "scope:target_country", "is_subject_of", "root", None),
        ("state_value", "root", "owner", "target_state", None),
        ("state_value", "root", "is_homeland_of_country_cultures", "target_state", None),
        ("subject_value", "root", "has_truce_with", "target_country", None),
        ("subject_value", None, "has_treaty_alliance_with", "target_country", {"TARGET": "root"}),
        (
            "become_subject_value",
            None,
            "has_diplomatic_pact",
            "overlord",
            {"who": "root", "type": "embargo"},
        ),
    ],
)
def test_production_country_arguments_preserve_legal_named_objects(
    field, argument, engine, scope, parameters
):
    policy = _argument_policy(field, argument, engine=engine, scope=scope, parameters=parameters)
    context = compiler.evaluation_contexts(compiler.BASELINE.read_text(encoding="utf-8"))[field]
    bound = compiler.validate_context_readers(
        field, context, {r.key: r for r in policy.readers}, policy.rules[0].conditions
    )
    assert bound


@pytest.mark.parametrize(
    ("engine", "parameter"),
    [("has_diplomatic_pact", "who"), ("has_treaty_alliance_with", "TARGET")],
)
def test_country_parameter_kind_is_checked_even_for_existing_named_scope(engine, parameter):
    context = compiler.evaluation_contexts(compiler.BASELINE.read_text(encoding="utf-8"))[
        "state_value"
    ]
    reader = decision_rules.Reader(
        "parameter_fact",
        engine,
        "target_country",
        "boolean",
        "boolean",
        parameters=((parameter, "scope:target_state"),),
    )
    with pytest.raises(ValueError, match=r"参数.*country"):
        compiler.validate_context_readers(
            "state_value",
            context,
            {reader.key: reader},
            (decision_rules.Predicate(reader.key, "=", True),),
        )


def test_context_cannot_turn_literal_argument_into_dynamic_object_getter():
    policy = _argument_policy("negotiation_chance", "scope:law", engine="has_variable")
    context = compiler.evaluation_contexts(compiler.BASELINE.read_text(encoding="utf-8"))[
        "negotiation_chance"
    ]
    with pytest.raises(ValueError, match="参数不支持对象作用域"):
        compiler.validate_context_readers(
            "negotiation_chance",
            context,
            {r.key: r for r in policy.readers},
            policy.rules[0].conditions,
        )


@pytest.mark.parametrize("engine", ["has_variable", "has_strategy", "has_law_or_variant"])
def test_literal_root_identifier_keeps_production_argument_semantics(engine):
    policy = _argument_policy("negotiation_chance", "root", engine=engine)
    reader = policy.readers[0]
    assert reader.expression("=", True) == f"{engine} = root"
    context = compiler.evaluation_contexts(compiler.BASELINE.read_text(encoding="utf-8"))[
        "negotiation_chance"
    ]
    assert compiler.validate_context_readers(
        "negotiation_chance", context, {reader.key: reader}, policy.rules[0].conditions
    ) == ((reader.key, "root", "country", "actor"),)


@pytest.mark.parametrize(
    ("field", "comments", "targets", "auxiliary"),
    [
        (
            "subject_value",
            "# root is the AI doing the evaluation, scope:target_country is prospective subject",
            (("target_country", "country", "target"),),
            (),
        ),
        (
            "become_subject_value",
            "# root is the AI doing the evaluation, scope:overlord is prospective overlord",
            (("overlord", "country", "target"),),
            (),
        ),
        (
            "interest_group_government_weight",
            "# root = country\n# scope:interest_group = IG",
            (("interest_group", "interest_group", "candidate"),),
            (),
        ),
        (
            "negotiation_chance",
            (
                "# root = country\n# scope:law = law type being enacted\n"
                "# scope:interest_group = IG to negotiate with\n"
                "# scope:amenability = IG amenability to negotiation divided by MAX_AMENABILITY (ie, if MAX_AMENABILITY is 100 and IG amenability is 50, this value will be 0.5)\n"
                "# scope:advance_chance = Chance to advance law enactment\n"
                "# scope:stall_chance = Chance for law enactment to stall"
            ),
            (("interest_group", "interest_group", "candidate"),),
            (
                ("law", "law"),
                ("amenability", "scalar"),
                ("advance_chance", "scalar"),
                ("stall_chance", "scalar"),
            ),
        ),
        (
            "state_value",
            "# root = country\n# scope:target_state = state\n# scope:target_country = state owner",
            (("target_state", "state", "target"),),
            (("target_country", "country"),),
        ),
    ],
)
def test_contexts_require_exact_field_local_comments(field, comments, targets, auxiliary):
    text = f"ai_strategy_default = {{\n{comments}\n{field} = {{ value = 0 }}\n}}"
    context = compiler.evaluation_contexts(text)[field]
    assert context.status == "observed"
    assert context.actor_scope is not None
    assert (context.actor_scope.name, context.actor_scope.kind, context.actor_scope.role) == (
        "root",
        "country",
        "actor",
    )
    bindings = (*context.targets, *context.auxiliary_scopes)
    assert tuple((b.name, b.kind, b.role) for b in context.targets) == targets
    assert tuple((b.name, b.kind) for b in context.auxiliary_scopes) == auxiliary
    assert all(b.source == SOURCE and b.line > 1 for b in bindings)
    assert all(text.splitlines()[b.line - 1].lstrip().startswith("#") for b in bindings)
    assert context.evidence
    unknown = compiler.evaluation_contexts(text.replace(comments, "# no scope proof"))[field]
    assert unknown.status == "unknown"
    assert unknown.actor_scope is None
    assert not unknown.targets
    misplaced = f"{comments}\nai_strategy_default = {{ {field} = {{ value = 0 }} }}"
    assert compiler.evaluation_contexts(misplaced)[field].status == "unknown"
    duplicated = text.replace(f"{field} = {{ value = 0 }}", f"{field} = {{}}\n{field} = {{}}")
    assert compiler.evaluation_contexts(duplicated)[field].status == "ambiguous"
    assert (
        compiler.evaluation_contexts(text + "\nai_strategy_default = {}\n")[field].status
        == "ambiguous"
    )
    assert (
        compiler.evaluation_contexts(text.replace(f"{field} =", f"REPLACE:{field} ="))[field].status
        == "unknown"
    )
    duplicated_proof = text.replace(comments, f"{comments}\n{comments}")
    assert compiler.evaluation_contexts(duplicated_proof)[field].status == "unknown"
    same_line = text.replace(
        f"{field} = {{ value = 0 }}", f"other_field = {{}} {field} = {{ value = 0 }}"
    )
    assert compiler.evaluation_contexts(same_line)[field].status == "unknown"
    contradictory = text.replace(comments, f"{comments}\n# root = state")
    assert compiler.evaluation_contexts(contradictory)[field].status == "unknown"
    contradictory_scope = text.replace(comments, f"{comments}\n# scope:target_country = law")
    assert compiler.evaluation_contexts(contradictory_scope)[field].status == "unknown"
    for declaration in (
        "root=state",
        "root\t= state",
        "root\tis\tstate",
        "scope:target_country=law",
        "scope : target_country\t= law",
    ):
        contradictory_spacing = text.replace(comments, f"{comments}\n# {declaration}")
        assert compiler.evaluation_contexts(contradictory_spacing)[field].status == "unknown"


def test_context_type_rejects_duplicate_names_role_confusion_and_missing_evidence():
    binding = decision_ir.ContextBinding("root", "country", "actor", SOURCE, 2)
    target = decision_ir.ContextBinding("overlord", "country", "target", SOURCE, 3)
    with pytest.raises(ValueError, match="重复"):
        decision_ir.EvaluationContext(binding, (target, target), evidence=(f"{SOURCE}:3",))
    with pytest.raises(ValueError, match="角色"):
        decision_ir.EvaluationContext(target, evidence=(f"{SOURCE}:3",))
    with pytest.raises(ValueError, match="角色"):
        decision_ir.EvaluationContext(binding, (binding,), evidence=(f"{SOURCE}:3",))
    with pytest.raises(ValueError, match="证据"):
        decision_ir.EvaluationContext(binding, (target,))
    with pytest.raises(ValueError, match="证据"):
        decision_ir.ContextBinding("root", "country", "actor", SOURCE, 0)
    with pytest.raises(ValueError, match="角色"):
        replace(target, name="interest_group")


def test_scope_names_and_roles_are_not_interchangeable():
    subject = compiler.evaluation_contexts(
        "ai_strategy_default = {\n# root is the AI doing the evaluation, scope:target_country is prospective subject\nsubject_value = {}\n}"
    )["subject_value"]
    overlord = compiler.evaluation_contexts(
        "ai_strategy_default = {\n# root is the AI doing the evaluation, scope:overlord is prospective overlord\nbecome_subject_value = {}\n}"
    )["become_subject_value"]
    assert subject.targets != overlord.targets
    assert subject.targets[0].name == "target_country"
    assert overlord.targets[0].name == "overlord"
    with pytest.raises(ValueError, match="角色"):
        replace(subject, auxiliary_scopes=subject.targets, targets=())


def test_reader_context_binding_checks_lhs_and_fact_reference_scopes():
    subject = compiler.evaluation_contexts(
        "ai_strategy_default = {\n"
        "# root is the AI doing the evaluation, scope:target_country is prospective subject\n"
        "subject_value = {}\n}"
    )["subject_value"]
    root = decision_rules.Reader("root_fact", "gdp", "root", "annual_gdp_currency", "number")
    target = decision_rules.Reader(
        "target_fact", "gdp", "target_country", "annual_gdp_currency", "number"
    )
    predicates = (
        decision_rules.Predicate(
            "target_fact", ">=", decision_rules.FactReference("root_fact", "ROOT.gdp")
        ),
    )
    compiler.validate_context_readers(
        "subject_value", subject, {"root_fact": root, "target_fact": target}, predicates
    )
    with pytest.raises(ValueError, match=r"作用域|角色|上下文"):
        compiler.validate_context_readers(
            "subject_value",
            subject,
            {"root_fact": root, "target_fact": replace(target, scope="overlord")},
            predicates,
        )
    with pytest.raises(ValueError, match=r"类型|kind|上下文"):
        compiler.validate_context_readers(
            "subject_value",
            subject,
            {"root_fact": root, "target_fact": replace(target, kind="country")},
            predicates,
        )
    with pytest.raises(ValueError, match=r"FactReference|右侧|作用域"):
        compiler.validate_context_readers(
            "subject_value",
            subject,
            {"root_fact": replace(root, scope="overlord"), "target_fact": target},
            predicates,
        )


def test_reader_context_binding_does_not_invent_a_law_reader():
    negotiation = compiler.evaluation_contexts(
        "ai_strategy_default = {\n"
        "# root = country\n"
        "# scope:law = law type being enacted\n"
        "# scope:interest_group = IG to negotiate with\n"
        "# scope:amenability = IG amenability to negotiation divided by MAX_AMENABILITY (ie, if MAX_AMENABILITY is 100 and IG amenability is 50, this value will be 0.5)\n"
        "# scope:advance_chance = Chance to advance law enactment\n"
        "# scope:stall_chance = Chance for law enactment to stall\n"
        "negotiation_chance = {}\n}"
    )["negotiation_chance"]
    with pytest.raises(ValueError, match=r"读取器.*law_fact"):
        compiler.validate_context_readers(
            "negotiation_chance",
            negotiation,
            {},
            (decision_rules.Predicate("law_fact", "=", True),),
        )
    # Metadata proves that law exists, but the current reader registry does
    # not expose law getters. A known country getter cannot fill that gap.
    with pytest.raises(ValueError, match=r"getter.*law"):
        compiler.validate_context_readers(
            "negotiation_chance",
            negotiation,
            {
                "law_fact": decision_rules.Reader(
                    "law_fact", "gdp", "law", "annual_gdp_currency", "number"
                )
            },
            (decision_rules.Predicate("law_fact", ">", 0),),
        )


@pytest.mark.parametrize("field", ["subject_value", "become_subject_value", "state_value"])
def test_ig_candidate_cannot_become_country_or_state_target(field):
    context = compiler.evaluation_contexts(compiler.BASELINE.read_text(encoding="utf-8"))[field]
    reader = decision_rules.Reader("ig", "ig_clout", "interest_group", "ratio", "number")
    with pytest.raises(ValueError, match="interest_group"):
        compiler.validate_context_readers(
            field, context, {"ig": reader}, (decision_rules.Predicate("ig", ">", 0.1),)
        )


def test_unknown_context_does_not_gain_reader_bindings():
    reader = decision_rules.Reader("fact", "gdp", "overlord", "annual_gdp_currency", "number")
    assert (
        compiler.validate_context_readers(
            "subject_value",
            decision_ir.EvaluationContext(status="unknown"),
            {"fact": reader},
            (decision_rules.Predicate("fact", ">", 0),),
        )
        == ()
    )


def test_reader_scope_argument_and_fact_reference_expression_cannot_cross_contexts():
    context = compiler.evaluation_contexts(compiler.BASELINE.read_text(encoding="utf-8"))[
        "subject_value"
    ]
    relation = decision_rules.Reader(
        "relation", "is_subject_of", "root", "boolean", "boolean", argument="scope:overlord"
    )
    with pytest.raises(ValueError, match="overlord"):
        compiler.validate_context_readers(
            "subject_value",
            context,
            {"relation": relation},
            (decision_rules.Predicate("relation", "=", True),),
        )
    root = decision_rules.Reader("root", "gdp", "root", "annual_gdp_currency", "number")
    target = replace(root, key="target", scope="target_country")
    with pytest.raises(ValueError, match="FactReference"):
        compiler.validate_context_readers(
            "subject_value",
            context,
            {"root": root, "target": target},
            (
                decision_rules.Predicate(
                    "target", ">", decision_rules.FactReference("root", "scope:overlord.gdp")
                ),
            ),
        )


@pytest.mark.parametrize("damage", ["missing", "role", "direction"])
def test_model_loader_rejects_used_reader_context_drift(monkeypatch, damage):
    contexts = compiler.evaluation_contexts(compiler.BASELINE.read_text(encoding="utf-8"))
    subject = contexts["subject_value"]
    if damage == "missing":
        contexts["subject_value"] = replace(subject, targets=())
    elif damage == "role":
        contexts["subject_value"] = replace(
            subject,
            targets=(),
            auxiliary_scopes=(replace(subject.targets[0], role="auxiliary"),),
        )
    else:
        contexts["subject_value"] = contexts["become_subject_value"]
    monkeypatch.setattr(compiler, "evaluation_contexts", lambda _text: contexts)
    with pytest.raises(
        ValueError, match=r"subject_value.*target_country|target_country.*subject_value"
    ):
        compiler.load_model()


def test_compiler_exports_context_but_keeps_frozen_migration_identity():
    model = compiler.load_model()
    bundle = model.consumer_ir
    assert bundle is not None
    migration_baseline.validate_bundle(bundle)
    actual_contexts = compiler.evaluation_contexts(compiler.BASELINE.read_text(encoding="utf-8"))
    assert all(context.status == "observed" for context in actual_contexts.values())
    baseline_lines = compiler.BASELINE.read_text(encoding="utf-8").splitlines()
    for context in actual_contexts.values():
        assert context.actor_scope is not None
        for binding in (context.actor_scope, *context.targets, *context.auxiliary_scopes):
            assert binding.name in baseline_lines[binding.line - 1]
    instance = next(
        i for i in model.action_instances if i.rule_id == "comparative_friendly_subject"
    )
    writer = next(w for w in bundle.writers if w.definition == instance.rule_id)
    assert instance.target_scope == writer.target == "none"
    assert instance.evaluation_context == writer.evaluation_context
    assert (
        "candidate_gdp",
        "target_country",
        "country",
        "target",
    ) in writer.reader_context_bindings
    assert ("national_gdp", "root", "country", "actor") in writer.reader_context_bindings
    assert writer.evaluation_context is not None
    assert writer.evaluation_context.targets[0].name == "target_country"
    row = next(r for r in bundle.as_dict()["writers"] if r["definition"] == writer.definition)
    assert row["target"] == "none"
    assert row["evaluation_context"]["targets"][0]["name"] == "target_country"
    assert ["national_gdp", "root", "country", "actor"] in row["reader_context_bindings"]
    assert instance.as_dict()["evaluation_context"]["status"] == "observed"
    stripped = replace(
        bundle,
        writers=tuple(replace(w, evaluation_context=None) for w in bundle.writers),
    )
    migration_baseline.validate_bundle(stripped)
    for source, policy in (
        ("mod/decisions/information.toml", decision_rules.load()),
        *decision_adapters.load().policies,
    ):
        assert decision_ir.lower_legacy(policy, bundle, source=source) == decision_ir.lower_legacy(
            policy, stripped, source=source
        )
