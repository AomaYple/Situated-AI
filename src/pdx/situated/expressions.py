"""可降低为 PDX 的有限类型化表达式和三值逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, cast

Truth = Literal[True, False, None]


class Expression(Protocol):
    def evaluate(self, facts: dict[str, object | None]) -> Truth: ...


def truth_not(value: Truth) -> Truth:
    return None if value is None else not value


def truth_all(values: tuple[Truth, ...]) -> Truth:
    if any(value is False for value in values):
        return False
    if any(value is None for value in values):
        return None
    return True


def truth_any(values: tuple[Truth, ...]) -> Truth:
    if any(value is True for value in values):
        return True
    if any(value is None for value in values):
        return None
    return False


@dataclass(frozen=True, slots=True)
class BooleanLiteral:
    value: Truth

    def evaluate(self, _facts: dict[str, object | None]) -> Truth:
        return self.value


@dataclass(frozen=True, slots=True)
class Compare:
    fact_id: str
    operator: Literal["eq", "ne", "gt", "ge", "lt", "le"]
    expected: object

    def evaluate(self, facts: dict[str, object | None]) -> Truth:
        if self.fact_id not in facts or facts[self.fact_id] is None:
            return None
        actual = facts[self.fact_id]
        if type(actual) is bool or type(self.expected) is bool:
            if type(actual) is not bool or type(self.expected) is not bool:
                return None
        elif type(actual) not in (int, float) or type(self.expected) not in (int, float):
            return None
        if self.operator == "eq":
            return actual == self.expected
        if self.operator == "ne":
            return actual != self.expected
        actual_number = cast("int | float", actual)
        expected_number = cast("int | float", self.expected)
        if self.operator == "gt":
            return bool(actual_number > expected_number)
        if self.operator == "ge":
            return bool(actual_number >= expected_number)
        if self.operator == "lt":
            return bool(actual_number < expected_number)
        return bool(actual_number <= expected_number)


@dataclass(frozen=True, slots=True)
class All:
    items: tuple[Expression, ...]

    def evaluate(self, facts: dict[str, object | None]) -> Truth:
        return truth_all(tuple(item.evaluate(facts) for item in self.items))


@dataclass(frozen=True, slots=True)
class Any:
    items: tuple[Expression, ...]

    def evaluate(self, facts: dict[str, object | None]) -> Truth:
        return truth_any(tuple(item.evaluate(facts) for item in self.items))


@dataclass(frozen=True, slots=True)
class Not:
    item: Expression

    def evaluate(self, facts: dict[str, object | None]) -> Truth:
        return truth_not(self.item.evaluate(facts))


__all__ = [
    "All",
    "Any",
    "BooleanLiteral",
    "Compare",
    "Expression",
    "Not",
    "Truth",
    "truth_all",
    "truth_any",
    "truth_not",
]
