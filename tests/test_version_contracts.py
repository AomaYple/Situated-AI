"""Version selection and the native 1.15 repeated-outcome boundary."""

from __future__ import annotations

import pytest

from pdx import version_contracts
from pdx.model import Scalar
from pdx.parser import parse_text


def test_version_is_selected_at_call_time_and_restored_after_failure(monkeypatch):
    monkeypatch.delenv(version_contracts.ENVIRONMENT_VARIABLE, raising=False)
    assert version_contracts.active_version() == "1.14.5"
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, "1.15.0")
    assert version_contracts.active_version() == "1.15.0"

    def operation():
        with version_contracts.select_version("1.14.5"):
            assert version_contracts.active_version() == "1.14.5"
            assert version_contracts.active_version("1.15.0") == "1.15.0"
            raise RuntimeError("operation failed")

    with pytest.raises(RuntimeError):
        operation()
    assert version_contracts.active_version() == "1.15.0"


@pytest.mark.parametrize("version", ["", "1.15", "release/1.15.0", "1.16.0", "latest"])
def test_unknown_version_cannot_silently_select_a_contract(monkeypatch, version):
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, version)
    with pytest.raises(ValueError, match="合同版本"):
        version_contracts.active_version()
    with pytest.raises(ValueError, match="合同版本"), version_contracts.select_version(version):
        pytest.fail("unknown version entered the operation")


_COMPLETION = """
outcome = {
    header = je_standard_completion_header
    effect_header = je_standard_on_completion_header
    trigger = { any_scope_state = { market_access < 1 } }
    effect = { set_variable = completed }
}
"""
_FAILURE = """
outcome = {
    header = je_standard_failure_header
    effect_header = je_standard_on_failure_header
    trigger = { always = no }
    effect = { set_variable = failed }
}
"""


@pytest.mark.parametrize("source", [_COMPLETION + _FAILURE, _FAILURE + _COMPLETION])
def test_completion_role_does_not_depend_on_outcome_order(source):
    journal = parse_text(source).root
    predicate = version_contracts.journal_completion(journal)
    effect = version_contracts.journal_completion(journal, effect=True)
    assert predicate.all("any_scope_state")
    value = effect.all("set_variable")[0].value
    assert isinstance(value, Scalar)
    assert value.unquoted == "completed"


@pytest.mark.parametrize(
    "source",
    [
        _FAILURE,
        _COMPLETION + _COMPLETION,
        _COMPLETION.replace("outcome =", "outcome ?="),
        _COMPLETION.replace("outcome =", "INJECT:outcome ="),
        _COMPLETION.replace("header =", "header ?="),
        _COMPLETION.replace("je_standard_on_completion_header", "je_standard_on_failure_header"),
        _COMPLETION.replace("trigger =", "trigger ?="),
        _COMPLETION.replace("trigger =", "INJECT:trigger ="),
        _COMPLETION.replace("effect =", "effect ?="),
    ],
)
def test_matching_header_cannot_authorize_ambiguous_or_conditional_outcome(source):
    journal = parse_text(source).root
    with pytest.raises(ValueError):
        version_contracts.journal_completion(journal, effect="effect ?=" in source)
