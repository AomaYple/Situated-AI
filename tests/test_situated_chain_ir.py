"""D9 strict local chain IR rejects fabricated or ambiguous evidence."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from pdx.situated import joint_chain_contract as contract

pytestmark = pytest.mark.unit


def _reader(key: str, **overrides: object) -> SimpleNamespace:
    signature = contract._expected_reader_signature(key)
    assert signature is not None
    names = (
        "engine",
        "kind",
        "scope",
        "path",
        "argument",
        "parameters",
        "value_field",
        "unit",
        "minimum",
        "maximum",
    )
    values = dict(zip(names, signature, strict=True))
    values["key"] = key
    values.update(overrides)
    return SimpleNamespace(**values)


def _copy_with(value: SimpleNamespace, **changes: object) -> SimpleNamespace:
    result = vars(value).copy()
    result.update(changes)
    return SimpleNamespace(**result)


def _fixture():
    rules_by_source: dict[str, list[SimpleNamespace]] = {}
    readers_by_source: dict[str, dict[str, SimpleNamespace]] = {}
    writers = []
    for (
        _chain_id,
        _link_id,
        source,
        rule_id,
        expected_field,
        expected_actor,
        expected_target,
        expected_operation,
    ) in contract._STRICT_TARGETS:
        predicates = contract._EXPECTED_CONDITIONS[rule_id]
        rule = SimpleNamespace(
            id=rule_id,
            field=tuple(expected_field.split(".")),
            operation=expected_operation,
            required_known_facts=contract._EXPECTED_REQUIRED_KNOWN.get(rule_id, ()),
            conditions=tuple(
                SimpleNamespace(
                    fact=fact,
                    op=operator,
                    value=SimpleNamespace(
                        expression=value["fact_reference"], key="native_marine_capacity"
                    )
                    if isinstance(value, dict)
                    else value,
                )
                for fact, operator, value in predicates
            ),
        )
        rules_by_source.setdefault(source, []).append(rule)
        readers = readers_by_source.setdefault(source, {})
        for fact in (
            *tuple(fact for fact, _operator, _value in predicates),
            *contract._EXPECTED_REFERENCE_FACTS.get(rule_id, ()),
            *rule.required_known_facts,
        ):
            readers.setdefault(fact, _reader(fact))
        writers.append(
            SimpleNamespace(
                kind="rule_action",
                source=source,
                definition=rule.id,
                field=".".join(rule.field),
                operation=rule.operation,
                actor=expected_actor,
                target=expected_target,
                writer_id=f"writer:{rule.id}",
                owner="test",
            )
        )
    policies = {
        source: SimpleNamespace(
            rules=tuple(rules), readers=tuple(readers_by_source[source].values())
        )
        for source, rules in rules_by_source.items()
    }
    return SimpleNamespace(writers=tuple(writers)), policies


def test_strict_build_uses_unique_writer_and_field_level_readers():
    bundle, policies = _fixture()
    rows = contract.build_strict(bundle, policies)
    assert len(rows) == 34
    assert {row.spec.chain_id for row in rows} == {
        "LJ01",
        "LJ02",
        "LJ03",
        "LJ04",
        "LJ05",
        "LJ06",
        "LJ07",
        "LJ08",
        "LJ09",
        "LJ10",
        "LJ11",
        "LJ12",
        "LJ13",
        "LJ14",
    }
    lj02 = [row for row in rows if row.spec.chain_id == "LJ02"]
    assert {row.spec.link_id for row in lj02} == {
        "LJ02.coal_output_transport_foundation",
        "LJ02.coal_transport_railway_support",
    }
    assert {row.spec.operation for row in lj02} == {"multiply"}
    assert {row.spec.actor for row in lj02} == {"owner"}
    assert all(row.spec.target == "none" for row in lj02)
    assert all("selected" not in row.spec.completion_state for row in lj02)
    assert all("queued" not in row.spec.completion_state for row in lj02)
    assert rows[0].spec.recipe
    assert any(row.spec.completion_state == "completed_knowledge_foundation" for row in rows)
    assert all(row.spec.status == "observed_static_only" for row in rows)
    for row in rows:
        assert (
            *tuple(fact for fact, _op, _value in row.spec.condition_semantics),
            *contract._EXPECTED_REFERENCE_FACTS.get(row.spec.rule_id, ()),
            *row.spec.required_known_facts,
        ) == tuple(reader.key for reader in row.spec.readers)
    contract.validate_links(rows, bundle)
    result = contract.strict_contract(rows)
    assert result["schema"] == 3
    assert result["locally_witnessed_chains"] == [
        "LJ01",
        "LJ02",
        "LJ03",
        "LJ04",
        "LJ05",
        "LJ06",
        "LJ07",
        "LJ08",
        "LJ09",
        "LJ10",
        "LJ11",
        "LJ12",
        "LJ13",
        "LJ14",
    ]
    assert result["pending_chain_closure"] == [f"LJ{i:02d}" for i in range(1, 15)]
    links = result["links"]
    assert isinstance(links, list)
    link = links[0]
    assert isinstance(link, dict)
    readers = link["readers"]
    assert isinstance(readers, list)
    reader_contract = readers[0]
    assert isinstance(reader_contract, dict)
    assert {"engine", "kind", "path", "scope", "minimum", "maximum"} <= reader_contract.keys()
    assert "refresh" not in reader_contract
    assert "unknown" not in reader_contract


def test_strict_build_rejects_missing_writer():
    bundle, policies = _fixture()
    missing = SimpleNamespace(
        writers=tuple(
            item
            for item in bundle.writers
            if item.definition != "lj04_welfare_zero_administration_foundation"
        )
    )
    with pytest.raises(ValueError, match="缺少唯一生产 writer"):
        contract.build_strict(missing, policies)


def test_strict_build_rejects_duplicate_writer():
    bundle, policies = _fixture()
    duplicate = SimpleNamespace(writers=(*bundle.writers, bundle.writers[0]))
    with pytest.raises(ValueError, match="缺少唯一生产 writer"):
        contract.build_strict(duplicate, policies)


def test_strict_build_rejects_candidate_selected_or_queued_as_completed():
    bundle, policies = _fixture()
    policy = policies["common/buildings/07_government.txt"]
    rule = policy.rules[0]
    rule.conditions = (SimpleNamespace(fact="candidate_selected", op="=", value=True),)
    policy.readers = ()
    with pytest.raises(ValueError, match="候选态冒充完成态"):
        contract.build_strict(bundle, policies)


def test_strict_build_rejects_reader_path_or_scope_drift():
    bundle, policies = _fixture()
    source = "common/buildings/03_mines.txt"
    policy = policies[source]
    first = policy.readers[0]
    policy.readers = (_copy_with(first, path=("owner",)), *policy.readers[1:])
    with pytest.raises(ValueError, match="读取器字段级来源、作用域或类型漂移"):
        contract.build_strict(bundle, policies)


def test_strict_build_rejects_writer_actor_drift():
    bundle, policies = _fixture()
    first = bundle.writers[0]
    invalid = SimpleNamespace(writers=(_copy_with(first, actor="root"), *bundle.writers[1:]))
    with pytest.raises(ValueError, match="writer 字段或操作漂移"):
        contract.build_strict(invalid, policies)


def test_validate_rejects_completed_status_and_duplicate_reader_paths():
    bundle, policies = _fixture()
    rows = contract.build_strict(bundle, policies)
    bad = replace(rows[0], spec=replace(rows[0].spec, status="completed"))
    with pytest.raises(ValueError, match="候选或完成标签"):
        contract.validate_links((bad, *rows[1:]))
    reader = rows[0].spec.readers[0]
    dup = replace(rows[0], spec=replace(rows[0].spec, readers=(reader, reader)))
    with pytest.raises(ValueError, match="读取器重复"):
        contract.validate_links((dup, *rows[1:]))


def test_validate_rejects_changed_operator_literal_reader_and_writer_scope():
    bundle, policies = _fixture()
    rows = contract.build_strict(bundle, policies)
    original = rows[0]
    fact, operator, value = original.spec.condition_semantics[0]
    bad_condition = replace(
        original,
        spec=replace(
            original.spec,
            condition_semantics=(
                (fact, "!=" if operator == "=" else "=", value),
                *original.spec.condition_semantics[1:],
            ),
        ),
    )
    with pytest.raises(ValueError, match="条件事实、运算符或阈值漂移"):
        contract.validate_links((bad_condition, *rows[1:]))

    bad_literal = replace(
        original,
        spec=replace(
            original.spec,
            condition_semantics=(
                (fact, operator, not value),
                *original.spec.condition_semantics[1:],
            ),
        ),
    )
    with pytest.raises(ValueError, match="条件事实、运算符或阈值漂移"):
        contract.validate_links((bad_literal, *rows[1:]))

    reader = original.spec.readers[0]
    bad_reader = replace(
        original,
        spec=replace(
            original.spec,
            readers=(replace(reader, scope="target_state"), *original.spec.readers[1:]),
        ),
    )
    with pytest.raises(ValueError, match="读取器来源、作用域或类型漂移"):
        contract.validate_links((bad_reader, *rows[1:]))

    bad_writer = replace(original, spec=replace(original.spec, actor="root"))
    with pytest.raises(ValueError, match="writer 身份、作用域或操作漂移"):
        contract.validate_links((bad_writer, *rows[1:]))


def test_validate_rejects_detached_owner_paths_or_runtime_evidence_claim():
    bundle, policies = _fixture()
    rows = contract.build_strict(bundle, policies)
    for changes, message in (
        ({"owner": "invented_owner"}, "owner 漂移"),
        ({"evidence_paths": ()}, "证据路径或类别漂移"),
        ({"evidence_state": "runtime"}, "证据路径或类别漂移"),
    ):
        damaged = replace(rows[0], **changes)
        with pytest.raises(ValueError, match=message):
            contract.validate_links((damaged, *rows[1:]), bundle)


@pytest.mark.parametrize("mode", ["missing", "wrong"])
def test_strict_knowledge_declaration_cannot_be_removed_or_changed(mode):
    bundle, policies = _fixture()
    source = "common/buildings/01_industry.txt"
    policy = policies[source]
    target = "lj06_employment_food_unemployment_support"
    rules = tuple(
        _copy_with(rule, required_known_facts=() if mode == "missing" else ("state_owner_default",))
        if rule.id == target
        else rule
        for rule in policy.rules
    )
    changed = {**policies, source: _copy_with(policy, rules=rules)}
    with pytest.raises(ValueError, match="核心知识声明漂移"):
        contract.build_strict(bundle, changed)


def test_chain_ir_keeps_required_knowledge_as_structured_guard():
    bundle, policies = _fixture()
    rows = contract.build_strict(bundle, policies)
    target = next(
        row for row in rows if row.spec.rule_id == "lj06_employment_food_unemployment_support"
    )
    assert target.spec.required_known_facts == ("state_owner_loans",)
    assert "state_owner_loans" in {reader.key for reader in target.spec.readers}
    payload = contract.strict_contract(rows)
    links = payload["links"]
    assert isinstance(links, list)
    row = next(row for row in links if row["rule_id"] == target.spec.rule_id)
    assert row["required_known_facts"] == ["state_owner_loans"]
    mutated = replace(target, spec=replace(target.spec, required_known_facts=()))
    with pytest.raises(ValueError, match="核心知识声明漂移"):
        contract.validate_links(tuple(mutated if item is target else item for item in rows), bundle)
