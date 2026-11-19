"""Keep native support verification at the installed source boundary."""

from __future__ import annotations

import hashlib
import re
from typing import Any, cast

import pytest
import test_support_native_binding as support_fixtures

from pdx import config, decision_report, version_contracts
from pdx.model import Block
from pdx.parser import parse_text
from pdx.situated import audit, compiler

pytestmark = pytest.mark.unit
SOURCE = support_fixtures.SOURCE


def _controlled_output():
    return cast("Any", support_fixtures.controlled_output).__wrapped__()


@pytest.mark.parametrize("version", ["1.14.5", "1.15.0"])
def test_continuous_audit_accepts_the_complete_selected_native_tail(version):
    with version_contracts.select_version(version):
        generated = _controlled_output()
        bindings = audit._production_continuous_bindings(generated)
        assert len(bindings) == 1
        assert bindings[0].writer.evaluation_context == compiler.support_evaluation_context()
        assert (
            bindings[0].production_sha256 == hashlib.sha256(generated[SOURCE].encode()).hexdigest()
        )


def test_current_continuous_audit_rejects_a_native_tail_mutation():
    with version_contracts.select_version("1.15.0"):
        generated = _controlled_output()
        changed, count = re.subn(
            r"(\bdiplomatic_play_support\s*=\s*\{)",
            r"\1\n\t\tvalue = 987654321",
            generated[SOURCE],
            count=1,
        )
        assert count == 1
        generated[SOURCE] = changed
        with pytest.raises(ValueError, match="原版尾部漂移"):
            audit._production_continuous_bindings(generated)


@pytest.mark.parametrize(
    ("output_version", "audit_version"), [("1.14.5", "1.15.0"), ("1.15.0", "1.14.5")]
)
def test_continuous_audit_rejects_the_other_versions_native_tail(output_version, audit_version):
    with version_contracts.select_version(output_version):
        generated = _controlled_output()
    with version_contracts.select_version(audit_version):
        # Keep the exact selected writer metadata, so rejection proves the
        # physical native tail check rather than an unrelated context mismatch.
        generated[".metadata/metadata.json"] = _controlled_output()[".metadata/metadata.json"]
        with pytest.raises(ValueError, match="原版尾部漂移"):
            audit._production_continuous_bindings(generated)


@pytest.mark.parametrize("version", ["1.14.5", "1.15.0", "1.15.1"])
def test_offline_report_refuses_retired_native_contracts(version, monkeypatch):
    monkeypatch.delenv(version_contracts.ENVIRONMENT_VARIABLE, raising=False)
    with (
        version_contracts.select_version(version),
        pytest.raises(ValueError, match=f"当前仅维护 {version_contracts.CURRENT_VERSION}"),
    ):
        decision_report.source_metadata()


@pytest.mark.integration
def test_current_support_context_binds_locked_installed_source_and_line():
    source = version_contracts.DEFAULT_STRATEGY_SOURCE
    raw = (config.GAME / source).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == version_contracts.contract().default_strategy_sha256
    text = raw.decode("utf-8-sig")
    parsed = parse_text(text)
    strategy = parsed.root.first("ai_strategy_default")
    assert strategy is not None
    assert isinstance(strategy.value, Block)
    support = strategy.value.first("diplomatic_play_support")
    assert support is not None
    lines = text.splitlines()
    actor_line = next(
        line
        for line in range(support.line - 1, 0, -1)
        if lines[line - 1].strip() == "# root = supporting country doing the AI evaluation"
    )
    context = compiler.support_evaluation_context()
    assert context.actor_scope is not None
    assert context.actor_scope.source == source
    assert context.actor_scope.line == actor_line
