"""Production-generated legacy writer witnesses against an independent oracle.

This is a static check, not an engine execution test.  Every case is named by
source and rule identity.  Generated output is kept in memory; the frozen mod
tree is never read as the output oracle or modified.
"""

from __future__ import annotations

import math
import operator
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

import pytest

from pdx import country_state, decision_adapters, decision_interfaces, decision_rules, policy_audit
from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_text
from pdx.situated import action_instances, compiler, pdx_eval

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit
INFO = "mod/decisions/information.toml"
_MARKER = re.compile(r"^\s*# ([a-z][a-z0-9_]*) \[[a-z][a-z0-9_]*\];")
_OPS = {"=": operator.eq, "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


@dataclass(frozen=True)
class _ReaderIndex:
    readers: Mapping[str, decision_rules.Reader]
    aliases: Mapping[str, tuple[str, ...]]

    @classmethod
    def build(cls, policy):
        observations: dict[tuple[object, ...], list[str]] = defaultdict(list)
        readers = {reader.key: reader for reader in policy.readers}
        for reader in policy.readers:
            identity = (
                reader.engine,
                reader.scope,
                reader.path,
                reader.argument,
                tuple(sorted(reader.parameters)),
                reader.value_field,
            )
            observations[identity].append(reader.key)
        aliases = {key: tuple(keys) for keys in observations.values() for key in keys}
        return cls(readers, aliases)

    def normalize(self, values: Mapping[str, object]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values.items():
            for alias in self.aliases[key]:
                assert alias not in result or result[alias] == value, (
                    f"contradictory aliases: {key}/{alias}"
                )
                result[alias] = value
        return result

    def change(self, values: Mapping[str, object], key: str, value: object) -> dict[str, object]:
        result = dict(values)
        for alias in self.aliases[key]:
            result[alias] = value
        assert all(result[alias] == value for alias in self.aliases[key])
        return result


@dataclass(frozen=True)
class _ParsedBranch:
    identity: str
    limit: Block
    operation: str
    delta: float
    proof_only: bool = False

    @classmethod
    def build(cls, identity: str, branch: Block):
        items = _ordinary_assignments(branch)
        assert len(items) == 2, identity
        assert items[0].key == "limit", identity
        if items[1].key == "if":
            assert isinstance(items[1].value, Block), identity
            nested = cls.build(identity, items[1].value)
            assert not nested.proof_only, identity
            inner_limit = items[1].value.first("limit")
            assert inner_limit is not None, identity
            assert isinstance(inner_limit.value, Block), identity
            assert len(inner_limit.value.items) == 1, identity
            always = inner_limit.value.first("always")
            assert always is not None, identity
            assert isinstance(always.value, Scalar), identity
            assert always.value.unquoted == "yes", identity
            assert isinstance(items[0].value, Block), identity
            _ordinary_condition(items[0].value)
            return cls(identity, items[0].value, nested.operation, nested.delta, True)
        assert items[1].key in {"add", "multiply"}, identity
        limit, effect = items
        assert isinstance(limit.value, Block), identity
        _ordinary_condition(limit.value)
        value = effect.value
        if isinstance(value, Block):
            terms = _ordinary_assignments(value)
            assert 1 <= len(terms) <= 2, identity
            assert terms[0].key == "value", identity
            if len(terms) == 2:
                assert terms[1].key == "desc", identity
                assert isinstance(terms[1].value, Scalar), identity
            value = terms[0].value
        assert isinstance(value, Scalar), identity
        assert not value.quoted, identity
        delta = float(value.text)
        assert math.isfinite(delta), identity
        return cls(identity, limit.value, effect.key, delta)


def _ordinary_assignments(block: Block) -> tuple[Assignment, ...]:
    result = []
    for item in block.items:
        assert isinstance(item, Assignment), "unsupported anonymous block or bare item"
        assert item.op == "=", "unsupported assignment operator"
        assert item.prefix is None, "unsupported assignment prefix"
        result.append(item)
    return tuple(result)


def _ordinary_condition(block: Block) -> None:
    # Numeric comparisons inside limit are part of the supported PDX predicate
    # language. Prefixes and anonymous/bare nodes are never ordinary predicates.
    for item in block.items:
        assert isinstance(item, Assignment), "unsupported condition item"
        assert item.prefix is None, "unsupported condition prefix"
        assert item.op in {"=", "<", "<=", ">", ">="}, "unsupported condition operator"
        if isinstance(item.value, Block):
            _ordinary_condition(item.value)
        else:
            assert isinstance(item.value, Scalar), "missing condition value"


@dataclass(frozen=True)
class _ParsedChain:
    """Immutable AST of the actual legacy chain; no production selector.

    Accept flat writes or one write-free proof around a static write; reject
    every other nesting/effect shape rather than silently approximate it.
    Conditions and effects use the independent PDX interpreter. Equivalence to
    its public text path is checked separately for every actual writer/field.
    """

    branches: tuple[_ParsedBranch, ...]

    @classmethod
    def build(cls, text: str):
        parsed = parse_text(text)
        assert not parsed.errors, parsed.errors
        markers: dict[int, str] = {}
        for line_number, line in enumerate(text.splitlines(), 1):
            if match := _MARKER.match(line):
                markers[line_number + 1] = match.group(1)
        result = []
        for index, assignment in enumerate(_ordinary_assignments(parsed.root)):
            assert assignment.key == ("if" if index == 0 else "else_if")
            assert isinstance(assignment.value, Block)
            assert assignment.line in markers, assignment.line
            result.append(_ParsedBranch.build(markers[assignment.line], assignment.value))
        assert result
        return cls(tuple(result))

    def select(self, facts: Mapping[str, object]):
        for branch in self.branches:
            outcome = pdx_eval.condition(branch.limit, facts)
            if outcome is None and not branch.proof_only:
                return pdx_eval.PdxDecision(branch.identity, None, 0.0, "unknown")
            if outcome is True:
                return pdx_eval.PdxDecision(
                    branch.identity, branch.operation, branch.delta, "selected"
                )
        return pdx_eval.PdxDecision(None, None, 0.0, "vanilla")


@pytest.mark.parametrize(
    ("rule_id", "key", "alias"),
    [
        ("ai_strategy_default_wanted_num_supply_ships", "navy", "own_navy"),
        ("coordinated_institution_health_system_social_need", "sol", "average_sol"),
        ("lj07_grain_health_social_capacity", "average_sol", "sol"),
    ],
)
def test_real_alias_counterfactuals_retain_missing_and_threshold_observations(rule_id, key, alias):
    policy = dict(decision_adapters.load().policies)["common/ai_strategies/00_default_strategy.txt"]
    rule = next(item for item in policy.rules if item.id == rule_id)
    cases = list(_cases(policy, rule))
    missing = next(values for name, values, _ in cases if name == f"unknown:{key}")
    assert missing[key] is missing[alias] is None
    assert _truth(rule, missing) is None
    for name, values, _ in cases:
        if name.startswith(f"negative:{key}"):
            assert values[key] == values[alias]
            assert _truth(rule, values) is False
        if name.startswith(f"threshold:{key}:"):
            boundary = float(name.rsplit(":", 1)[1])
            assert values[key] == values[alias] == boundary


@pytest.mark.parametrize(
    "body",
    [
        "limit = { always = yes } multiply = { value = 1 if = { limit = { ROOT = { navy_size > 10 } } add = 0.2 } }",
        "limit = { always = yes } multiply = 1 limit = { always = no }",
        "limit = { always = yes } multiply = 1 multiply = 2",
        "limit = { always = yes } multiply = 1 add = 2",
        "limit = { always = yes } multiply = { value = 1 value = 2 }",
        "limit = { always = yes } multiply = { value = 1 desc = A desc = B }",
        "limit = { always = yes } multiply = { value = 1 add = 2 }",
        "limit = { always = yes } multiply = { value = 1 { hidden = yes } }",
        "limit = { always = yes } multiply = { value = 1 hidden }",
        "limit = { always = yes } multiply = { value = 1 desc = { hidden = yes } }",
        "limit = { always = yes } multiply = 1 { hidden = yes }",
        "limit = { always = yes } multiply = 1 hidden",
        "REPLACE:limit = { always = yes } multiply = 1",
        "limit = { always = yes } REPLACE:multiply = 1",
        "limit = { always = yes } multiply > 1",
        "limit > { always = yes } multiply = 1",
        "limit = { always = yes } multiply = { REPLACE:value = 1 }",
        "limit = { always = yes } multiply = { value > 1 }",
        "limit = { always = yes } multiply = { value = 1 REPLACE:desc = A }",
        "limit = { always = yes } multiply = nan",
        "limit = { always = yes } multiply = inf",
        "limit = { always = yes } multiply = yes",
        'limit = { always = yes } multiply = "1"',
        "limit = { always = yes } multiply = { desc = A }",
        "limit = { always = yes } multiply = { value = inf }",
    ],
)
def test_static_fast_branch_rejects_unsupported_shape(body):
    parsed = parse_text(f"if = {{ {body} }}")
    assert not parsed.errors
    assignment = parsed.root.first("if")
    assert assignment is not None
    assert isinstance(assignment.value, Block)
    with pytest.raises((AssertionError, pdx_eval.UnsupportedPdxError, ValueError)):
        _ParsedBranch.build("test_writer", assignment.value)


@pytest.mark.parametrize(
    "text",
    [
        "# test_writer [generated];\nif = { limit = { always = yes } multiply = 1 }\nhidden",
        "# test_writer [generated];\nif = { limit = { always = yes } multiply = 1 }\n{ hidden = yes }",
        "# test_writer [generated];\nREPLACE:if = { limit = { always = yes } multiply = 1 }",
        "# test_writer [generated];\nif > { limit = { always = yes } multiply = 1 }",
    ],
)
def test_static_fast_chain_rejects_unsupported_root(text):
    with pytest.raises((AssertionError, pdx_eval.UnsupportedPdxError, ValueError)):
        _ParsedChain.build(text)


@pytest.mark.parametrize("effect", ["1.25", "{ value = 1.25 }", "{ value = 1.25 desc = REASON }"])
def test_static_fast_chain_accepts_exact_static_effect(effect):
    text = f"# test_writer [generated];\nif = {{ limit = {{ ROOT = {{ is_ai = yes }} }} multiply = {effect} }}"
    chain = _ParsedChain.build(text)
    for facts in ({"ROOT": {"is_ai": True}}, {"ROOT": {"is_ai": False}}, {}):
        assert chain.select(facts) == pdx_eval.select(text, facts)


@pytest.mark.parametrize(
    ("war", "navy", "expected"),
    [
        (True, -1, None),
        (True, float("nan"), None),
        (True, float("inf"), None),
        (True, True, None),
        (True, None, None),
        (True, 0, False),
        (True, 1, True),
        (False, None, False),
        (False, -1, False),
    ],
)
def test_independent_oracle_retains_reader_validity_and_known_false_dominance(war, navy, expected):
    policy = dict(decision_adapters.load().policies)[
        "common/technology/technologies/20_military.txt"
    ]
    rule = next(item for item in policy.rules if item.id == "structural_naval_research")
    index = _ReaderIndex.build(policy)
    values = {"war": war, "navy": navy}
    assert _truth(rule, values, index) is expected


@pytest.fixture(scope="module")
def generated():
    """Read locked originals once and run the actual lowering without writing files."""
    adapters = decision_adapters.load()
    info = decision_rules.load()
    model = compiler.load_model()
    assert model.consumer_ir is not None
    inputs = decision_adapters.read_inputs(adapters)
    policies = ((INFO, info), *adapters.policies)
    compiled = tuple(
        (source, compiler.compile_policy(policy, source, model)[0]) for source, policy in policies
    )
    by_source = dict(compiled)
    country = country_state.load()
    files, _ = decision_adapters.build(
        replace(adapters, policies=compiled[1:]),
        texts=inputs,
        country_policy=country,
        consumer_ir=model.consumer_ir,
    )
    baseline = compiler.BASELINE.read_text(encoding="utf-8")
    info_text = decision_rules.patch(
        baseline,
        by_source[INFO],
        baseline=baseline,
        reader_words=(
            frozenset(decision_adapters.reader_evidence(inputs))
            | decision_interfaces.proven_reader_words()
        ),
        country_policy=country,
        consumer_ir=model.consumer_ir,
        consumer_source=INFO,
    )
    return policies, model, files, info_text, inputs, baseline


def _blocks(text: str) -> dict[str, tuple[Block, _ParsedChain, str]]:
    """Parse each real marked branch, retaining duplicate identities as errors."""
    lines = text.splitlines()
    result: dict[str, tuple[Block, _ParsedChain, str]] = {}
    for index, line in enumerate(lines):
        match = _MARKER.match(line)
        if match is None:
            continue
        name = match.group(1)
        if name in result:
            raise AssertionError(f"duplicate generated writer: {name}")
        # The production lowerer emits a complete branch on the marker's next line.
        fragment = lines[index + 1].strip()
        parsed = parse_text(fragment)
        assert not parsed.errors, (name, parsed.errors)
        roots = _ordinary_assignments(parsed.root)
        assert len(roots) == 1, name
        branch = roots[0]
        assert branch.key in {"if", "else_if"}, name
        assert isinstance(branch.value, Block), name
        marked = f"# {name} [generated];\n{fragment}"
        if branch.key == "else_if":
            marked = "if = { limit = { always = no } }\n" + marked
        compiled_branch = _ParsedBranch.build(name, branch.value)
        compiled = _ParsedChain((compiled_branch,))
        effective = branch.value
        if compiled_branch.proof_only:
            inner = branch.value.first("if")
            assert inner is not None
            assert isinstance(inner.value, Block)
            outer_limit = branch.value.first("limit")
            assert outer_limit is not None
            effective = Block(
                [
                    outer_limit,
                    *(item for item in inner.value.items if getattr(item, "key", None) != "limit"),
                ]
            )
        result[name] = (effective, compiled, marked)
    return result


def _known(reader: decision_rules.Reader, value: object) -> bool:
    if reader.kind == "boolean":
        return type(value) is bool
    if type(value) not in (int, float) or not math.isfinite(cast("float", value)):
        return False
    number = cast("float", value)
    return (reader.minimum is None or number >= reader.minimum) and (
        reader.maximum is None or number <= reader.maximum
    )


def _truth(
    rule: decision_rules.Rule,
    values: Mapping[str, object],
    reader_index: _ReaderIndex | None = None,
) -> bool | None:
    """Independent conjunction over source predicates, without production selectors."""
    unknown = False
    for predicate in rule.conditions:
        left = values.get(predicate.fact)
        right = (
            values.get(predicate.value.key)
            if isinstance(predicate.value, decision_rules.FactReference)
            else predicate.value
        )
        valid = (
            left is not None and right is not None
            if reader_index is None
            else _known(reader_index.readers[predicate.fact], left)
            and (
                not isinstance(predicate.value, decision_rules.FactReference)
                or _known(reader_index.readers[predicate.value.key], right)
            )
        )
        if not valid:
            unknown = True
        elif not _OPS[predicate.op](cast("Any", left), cast("Any", right)):
            return False
    if reader_index is None:
        unknown |= any(type(values.get(key)) is not bool for key in rule.required_known_facts)
    else:
        unknown |= any(
            not _known(reader_index.readers[key], values.get(key))
            for key in rule.required_known_facts
        )
    return None if unknown else True


def _facts(
    policy: decision_rules.RuleSet,
    values: Mapping[str, object],
    *,
    is_ai: bool,
    reader_index: _ReaderIndex | None = None,
) -> dict[str, object]:
    root: dict[str, Any] = {}
    contexts: dict[str, dict[str, Any]] = {}
    readers = (reader_index or _ReaderIndex.build(policy)).readers
    for key, value in values.items():
        reader = readers[key]
        current = (
            root if reader.scope == "root" else contexts.setdefault(f"scope:{reader.scope}", {})
        )
        for part in reader.path:
            current = current.setdefault(part, {})
        if reader.engine == "is_production_method_active":
            parameters = dict(reader.parameters)
            current.setdefault(reader.engine, {}).setdefault(parameters["building_type"], {})[
                parameters["production_method"]
            ] = value
        elif reader.engine == "has_variable" and (reader.argument or "").startswith("sitai_route_"):
            current[f"{reader.argument}_active"] = value
        elif reader.argument is not None or reader.parameters or reader.value_field:
            identity = tuple(
                sorted(
                    {
                        **dict(reader.parameters),
                        **({"argument": reader.argument} if reader.argument is not None else {}),
                    }.items()
                )
            )
            current.setdefault(reader.engine, {})[identity] = value
        # Multiple source aliases may lower to the same PDX trigger (for
        # example own_navy and navy). Preserve uncertainty if a fixture
        # makes those aliases disagree instead of letting iteration order
        # silently choose one observation.
        elif reader.engine in current and current[reader.engine] != value:
            current[reader.engine] = None
        else:
            current[reader.engine] = value
        if reader.engine.startswith("sitai_context_"):
            current[reader.engine.replace("sitai_context_", "sitai_context_known_", 1)] = (
                value is not None
            )
    actor = root.setdefault("owner", {}) if policy.actor_path else root
    actor["is_ai"] = is_ai
    return {"ROOT": root, **contexts}


def _cases(
    policy: decision_rules.RuleSet,
    rule: decision_rules.Rule,
    reader_index: _ReaderIndex | None = None,
):
    index = reader_index or _ReaderIndex.build(policy)
    positive, candidates = policy_audit._fixture(policy, rule)
    positive = index.normalize(positive)
    assert _truth(rule, positive) is True, f"incoherent positive fixture: {rule.id}"
    yield "positive", positive, True
    yield "player", positive, False
    # Every declared input gets its own missing-observation witness. Checking
    # only the first key hid errors in later or parameterized readers.
    for key in positive:
        changed = index.change(positive, key, None)
        assert changed[key] is None
        assert _truth(rule, changed) is None
        yield f"unknown:{key}", changed, True
    negatives = [
        (key, value)
        for key, choices in candidates.items()
        for value in choices
        if _truth(rule, index.change(positive, key, value)) is False
    ]
    assert negatives, f"no independent negative fixture: {rule.id}"
    seen: set[str] = set()
    for key, value in negatives:
        if key not in seen:
            seen.add(key)
            yield f"negative:{key}", index.change(positive, key, value), True
    for predicate in rule.conditions:
        if type(predicate.value) in (int, float):
            numeric = float(cast("float", predicate.value))
            if not math.isfinite(numeric):
                continue
            for value in (
                numeric,
                math.nextafter(numeric, -math.inf),
                math.nextafter(numeric, math.inf),
            ):
                yield (
                    f"threshold:{predicate.fact}:{value}",
                    index.change(positive, predicate.fact, value),
                    True,
                )


def test_every_legacy_writer_has_generated_ast_semantics(generated):
    policies, model, files, info_text, _inputs, _baseline = generated
    assert model.consumer_ir is not None
    index = {source: _blocks(text) for source, text in files.items()}
    index[INFO] = _blocks(info_text)
    witnessed: set[tuple[str, str]] = set()
    counts: Counter[str] = Counter()
    for source, policy in policies:
        reader_index = _ReaderIndex.build(policy)
        for rule in policy.rules:
            identity = (source, rule.id)
            assert identity not in witnessed
            witnessed.add(identity)
            output = (
                INFO
                if source == INFO
                else action_instances._output_source(source, ".".join(rule.field))
            )
            branch, parsed_chain, marked = index[output][rule.id]
            limit = branch.first("limit")
            assert limit is not None, identity
            assert isinstance(limit.value, Block), identity
            write = branch.first(rule.operation)
            assert write is not None, identity
            if isinstance(write.value, Block):
                literal = write.value.first("value")
            else:
                literal = write
            assert literal is not None, identity
            assert not isinstance(literal.value, Block), identity
            assert literal.value is not None, identity
            assert float(literal.value.unquoted) == rule.value, identity
            for case, values, is_ai in _cases(policy, rule, reader_index):
                counts[case.split(":", 1)[0]] += 1
                expected = _truth(rule, values, reader_index) if is_ai else False
                engine_facts = _facts(policy, values, is_ai=is_ai, reader_index=reader_index)
                try:
                    actual = pdx_eval.condition(limit.value, engine_facts)
                except pdx_eval.UnsupportedPdxError as exc:
                    raise AssertionError(
                        f"{source}:{rule.id}/{case}: unsupported PDX oracle primitive: {exc}"
                    ) from exc
                if expected is None:
                    assert actual is not True, f"{source}:{rule.id}/{case}: unknown selected"
                else:
                    assert actual is expected, (
                        f"{source}:{rule.id}/{case}: expected {expected}, got {actual}"
                    )
                selected = parsed_chain.select(engine_facts)
                if case in {"positive", "player"}:
                    assert selected == pdx_eval.select(
                        marked, engine_facts, path=f"{output}:{rule.id}"
                    )
                if expected is True:
                    assert (selected.action_id, selected.operation, selected.delta) == (
                        rule.id,
                        rule.operation,
                        rule.value,
                    ), f"{source}:{rule.id}/{case}: {selected}"
                elif expected is False:
                    neutral_noop = selected.operation == "multiply" and selected.delta == 1.0
                    assert (
                        selected.action_id != rule.id
                        or neutral_noop
                        or selected.fallback == "vanilla"
                    ), f"{source}:{rule.id}/{case}: false condition applied writer {selected}"
                else:
                    neutral_noop = selected.operation == "multiply" and selected.delta == 1.0
                    assert selected.fallback in {"unknown", "vanilla"} or neutral_noop, (
                        f"{source}:{rule.id}/{case}: unknown condition applied writer {selected}"
                    )
    assert len(witnessed) == sum(len(policy.rules) for _, policy in policies)
    assert counts["positive"] == counts["player"] == len(witnessed)
    assert counts["unknown"] >= len(witnessed)
    assert counts["negative"] >= len(witnessed)
    print("writer_oracle_isolated", dict(counts))


def _consumer_overlay(text: str, field: str) -> str:
    """Keep the entire production priority chain, including unknown guards."""
    begin = text.index(f"# SITAI BEGIN information:{field}")
    end = text.index(f"# SITAI END information:{field}", begin)
    lines: list[str] = []
    for line in text[begin:end].splitlines()[1:]:
        if line.lstrip().startswith(("if =", "else_if =")) and (
            not lines or _MARKER.match(lines[-1]) is None
        ):
            # Guards have no public writer identity. Give only the independent
            # interpreter a label, without changing their conditions or effects.
            lines.append("# unknown_guard [context]; preserve original")
        lines.append(line)
    return "\n".join(lines)


def test_complete_consumer_priority_matches_independent_oracle(generated):
    """An isolated branch passing cannot prove its place in the real consumer."""
    policies, _model, files, info_text, _inputs, _baseline = generated
    counts: Counter[str] = Counter()
    fields_checked = 0
    for source, policy in policies:
        reader_index = _ReaderIndex.build(policy)
        fields: dict[tuple[str, ...], list[decision_rules.Rule]] = {}
        for rule in policy.rules:
            if rule.domain in policy.enabled_domains:
                fields.setdefault(rule.field, []).append(rule)
        for field, rules in fields.items():
            rules.sort(key=lambda rule: -rule.priority)
            output = (
                INFO if source == INFO else action_instances._output_source(source, ".".join(field))
            )
            text = info_text if source == INFO else files[output]
            overlay = _consumer_overlay(text, ".".join(field))
            parsed_chain = _ParsedChain.build(overlay)
            fields_checked += 1
            compared_text_states = set()
            for target in rules:
                target_cases: Counter[str] = Counter()
                for case, values, is_ai in _cases(policy, target, reader_index):
                    kind = case.split(":", 1)[0]
                    target_cases[kind] += 1
                    counts[kind] += 1
                    expected = None
                    expected_unknown = False
                    for candidate in rules if is_ai else ():
                        truth = _truth(candidate, values, reader_index)
                        if truth is None and candidate.auxiliary_facts:
                            core = replace(
                                candidate,
                                conditions=tuple(
                                    p
                                    for p in candidate.conditions
                                    if p.fact not in candidate.auxiliary_facts
                                ),
                            )
                            if _truth(core, values, reader_index) is True:
                                truth = False
                        if truth is None:
                            expected_unknown = True
                            break
                        if truth is True:
                            expected = candidate
                            break
                    engine_facts = _facts(policy, values, is_ai=is_ai, reader_index=reader_index)
                    actual = parsed_chain.select(engine_facts)
                    # Validate the independent immutable AST evaluator against the
                    # public text interpreter for each observed control state
                    # of every actual complete field, including player.
                    state = (is_ai, actual.fallback, actual.operation)
                    if state not in compared_text_states:
                        assert actual == pdx_eval.select(overlay, engine_facts)
                        compared_text_states.add(state)
                    identity = (source, field, target.id, case)
                    if expected is None:
                        assert actual.operation is None or (
                            actual.operation == "multiply" and actual.delta == 1
                        ), (identity, actual)
                        counts["unknown_priority" if expected_unknown else "no_match"] += 1
                    else:
                        assert (actual.action_id, actual.operation, actual.delta) == (
                            expected.id,
                            expected.operation,
                            expected.value,
                        ), (identity, expected, actual)
                        counts["selected"] += 1
                assert target_cases["positive"] == target_cases["player"] == 1
                assert target_cases["unknown"] >= len(target.input_keys())
                assert target_cases["negative"] >= 1
                numeric_conditions = sum(type(p.value) in (int, float) for p in target.conditions)
                assert target_cases["threshold"] == numeric_conditions * 3
    expected_count = sum(len(policy.rules) for _, policy in policies)
    assert counts["positive"] == counts["player"] == expected_count
    assert counts["unknown_priority"] > 0
    assert counts["selected"] > 0
    assert fields_checked > 0
    print("writer_oracle_complete", {"fields": fields_checked, **dict(counts)})
