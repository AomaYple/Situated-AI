"""Offline readback and synthetic counterexamples for the D01 diagnostic only."""

from __future__ import annotations

from decimal import Decimal
from operator import eq, gt, lt
from zipfile import ZipFile
lazy from pathlib import Path

import pytest
from build import ARMS, FIELD, SOURCE, STRATEGY, freeze, freeze_decision_observer

from pdx.model import Block, Node, Scalar
from pdx.parser import parse_file, parse_text


def test_arms_are_byte_reproducible(tmp_path: Path) -> None:
    first = freeze(tmp_path / "first")
    second = freeze(tmp_path / "second")
    assert first == second
    assert len(first) == len(ARMS)
    for archive in first:
        assert (tmp_path / "first" / archive).read_bytes() == (
            tmp_path / "second" / archive
        ).read_bytes()


def test_payload_contains_one_country_budget_contribution() -> None:
    neutral = read_budget("a")
    assert neutral.keys() == ["value"]
    assert scalar(neutral, "value") == "0"
    candidate = read_budget("b")
    assert candidate.keys() == ["value", "if"]
    assert scalar(candidate, "value") == "0"
    clause = nested(candidate, "if")
    assert clause.keys() == ["limit", "add"]
    assert scalar(clause, "add") == "-0.10"
    limits = nested(clause, "limit")
    assert [(a.key, a.op, scalar_value(a.value)) for a in limits.assignments()] == [
        ("exists", "=", "ROOT"),
        ("this", "=", "ROOT"),
        ("is_ai", "=", "yes"),
        ("credit", ">", "0"),
        ("scaled_debt", ">", "0"),
        ("scaled_debt", "<", "0.4"),
        ("net_fixed_income", "<", "0"),
        ("net_total_income", ">", "0"),
    ]


def test_decision_observer_package_matches_candidate_conditions(tmp_path: Path) -> None:
    output = tmp_path / "first"
    name = "sitai-d01-budget-decision-observer.zip"
    manifest = freeze_decision_observer(output)
    assert manifest == freeze_decision_observer(tmp_path / "second")
    assert (output / name).read_bytes() == (tmp_path / "second" / name).read_bytes()
    with ZipFile(output / name) as archive:
        assert archive.namelist() == [
            ".metadata/metadata.json",
            "common/decisions/sitai_d01_budget_observer.txt",
            "common/journal_entries/sitai_d01_budget_observer.txt",
            "common/scripted_effects/sitai_d01_budget_observer.txt",
            "localization/english/sitai_d01_budget_observer_l_english.yml",
        ]
        decision = probe_block(archive, "decisions", "sitai_d01_budget_observer_decision")
        journal = probe_block(archive, "journal_entries", "je_sitai_d01_budget_observer")
        observer = probe_block(archive, "scripted_effects", "sitai_d01_budget_log_conditions")

    visibility = nested(decision, "is_shown")
    assert scalar(visibility, "this") == "c:FRA"
    assert scalar(visibility, "is_ai") == "no"
    assert scalar(nested(decision, "ai_chance"), "value") == "0"
    assert scalar(nested(nested(decision, "possible"), "c:MNL"), "is_ai") == "yes"

    target = nested(nested(nested(decision, "when_taken"), "hidden_effect"), "c:MNL")
    assert scalar(target, "sitai_d01_budget_log_conditions") == "yes"
    assert scalar(nested(nested(target, "if"), "add_journal_entry"), "type") == (
        "je_sitai_d01_budget_observer"
    )
    assert scalar(journal, "context") == "country"
    assert scalar(nested(journal, "is_shown_when_inactive"), "always") == "no"
    assert scalar(nested(journal, "immediate"), "sitai_d01_budget_log_conditions") == "yes"

    candidate = nested(nested(read_budget("b"), "if"), "limit")
    exact_conditions = {
        (rule.key, rule.op, scalar_value(rule.value)) for rule in candidate.assignments()
    }
    observed_conditions = set()
    branches = list(observer.assignments())[1:]
    for affirmative, negative in zip(branches[::2], branches[1::2], strict=True):
        assert affirmative.key == "if"
        assert negative.key == "else"
        assert isinstance(affirmative.value, Block)
        assert isinstance(negative.value, Block)
        yes = scalar(affirmative.value, "debug_log").strip('"')
        no = scalar(negative.value, "debug_log").strip('"')
        label = yes.split("=", 1)[0]
        assert yes.startswith(f"{label}=yes")
        assert no == f"{label}=no"
        for condition in nested(affirmative.value, "limit").assignments():
            if isinstance(condition.value, Scalar):
                observed_conditions.add((condition.key, condition.op, condition.value.text))
    assert exact_conditions <= observed_conditions


def probe_block(archive: ZipFile, directory: str, key: str) -> Block:
    raw = archive.read(f"common/{directory}/sitai_d01_budget_observer.txt")
    assert raw.startswith(b"\xef\xbb\xbf")
    script = parse_text(raw.decode("utf-8-sig"))
    script.require_complete()
    return nested(script.root, key)


def scalar_value(value: Node | None) -> str:
    assert isinstance(value, Scalar)
    return value.text


def scalar(parent: Block, key: str) -> str:
    member = parent.first(key)
    assert member is not None
    return scalar_value(member.value)


def nested(parent: Block, key: str) -> Block:
    member = parent.first(key)
    assert member is not None
    assert isinstance(member.value, Block)
    return member.value


def read_budget(arm: str) -> Block:
    document = parse_file(SOURCE / f"{arm}.txt")
    document.require_complete()
    return nested(nested(document.root, STRATEGY), FIELD)


@pytest.mark.parametrize(
    ("signal", "value", "expected"),
    [
        ("net_total_income", "40", "-0.10"),
        ("net_total_income", "0", "0"),
        ("net_total_income", "-1", "0"),
        ("net_fixed_income", "0", "0"),
        ("net_fixed_income", "1", "0"),
        ("scaled_debt", "0", "0"),
        ("scaled_debt", "0.39999", "-0.10"),
        ("scaled_debt", "0.4", "0"),
        ("credit", "0", "0"),
        ("credit", None, "0"),
        ("net_fixed_income", None, "0"),
        ("net_total_income", None, "0"),
        ("scaled_debt", None, "0"),
        ("exists", None, "0"),
        ("this", "other", "0"),
        ("is_ai", "no", "0"),
    ],
)
def test_candidate_against_handwritten_cases(signal: str, value: str | None, expected: str) -> None:

    facts: dict[str, str | None] = {
        "exists": "ROOT",
        "this": "ROOT",
        "is_ai": "yes",
        "credit": "100",
        "scaled_debt": "0.37",
        "net_fixed_income": "-40",
        "net_total_income": "40",
    }
    facts[signal] = value
    clause = nested(read_budget("b"), "if")
    comparisons = {"=": eq, ">": gt, "<": lt}
    result = Decimal(0)
    for condition in nested(clause, "limit").assignments():
        observed = facts[condition.key]
        if observed is None:
            break
        limit = scalar_value(condition.value)
        if condition.op != "=":
            matches = comparisons[condition.op](Decimal(observed), Decimal(limit))
        else:
            matches = comparisons[condition.op](observed, limit)
        if not matches:
            break
    else:
        result += Decimal(scalar(clause, "add"))
    assert result == Decimal(expected)
