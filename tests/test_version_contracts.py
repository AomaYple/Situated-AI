"""Current release assertions and the native repeated-outcome boundary."""

from __future__ import annotations

import pytest

from pdx import version_contracts
from pdx.model import Scalar
from pdx.parser import parse_text


def test_current_environment_is_read_at_call_time_and_cannot_be_overridden(monkeypatch):
    monkeypatch.delenv(version_contracts.ENVIRONMENT_VARIABLE, raising=False)
    assert version_contracts.active_version() == "1.15.2"
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, "1.15.1")
    with pytest.raises(ValueError, match="当前仅维护"):
        version_contracts.contract("1.15.2")
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, "1.15.2")
    assert version_contracts.active_version() == "1.15.2"


@pytest.mark.parametrize(
    "version", ["1.14.5", "1.15.0", "1.15.1", "", "1.15", "release/1.15.2", "1.16.0", "latest"]
)
def test_noncurrent_version_cannot_select_a_contract(monkeypatch, version):
    monkeypatch.delenv(version_contracts.ENVIRONMENT_VARIABLE, raising=False)
    with pytest.raises(ValueError, match="当前仅维护"):
        version_contracts.contract(version)
    monkeypatch.setenv(version_contracts.ENVIRONMENT_VARIABLE, version)
    with pytest.raises(ValueError, match="当前仅维护"):
        version_contracts.active_version()


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


def test_default_and_explicit_current_contract_have_identical_identity(monkeypatch):
    monkeypatch.delenv(version_contracts.ENVIRONMENT_VARIABLE, raising=False)
    assert version_contracts.CURRENT_VERSION == "1.15.2"
    current = version_contracts.contract("1.15.2")
    assert version_contracts.contract() == current
    assert {"1.15.2"} == version_contracts.SUPPORTED_VERSIONS
