"""Offline readback and synthetic counterexamples for the D01 diagnostic only."""

from __future__ import annotations

from decimal import Decimal
from operator import eq, gt, lt
lazy from pathlib import Path

import pytest
from build import ARMS, FIELD, SOURCE, STRATEGY, freeze

from pdx.model import Block, Node, Scalar
from pdx.parser import parse_file


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
