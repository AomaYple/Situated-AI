"""Frozen and installed vanilla interface evidence must fail closed."""

from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
from dataclasses import replace
from typing import Any

import pytest

from pdx import config, country_interfaces, country_state, vanilla_index, version_contracts


def _snapshot():
    index = vanilla_index.snapshot_index()
    assert index is not None
    return {"sections": index.sections}


@pytest.mark.parametrize("change", ["kind", "unit", "range", "missing", "extra", "injection"])
def test_reader_signature_and_arguments_are_checked(change):
    data = tomllib.loads(country_state.SOURCE.read_text(encoding="utf-8"))
    readers = data["readers"]
    if change == "kind":
        readers["war"]["kind"] = "number"
    elif change == "unit":
        readers["navy"]["unit"] = "persons"
    elif change == "range":
        readers["literacy"].update(min=0.8, max=0.2)
    elif change == "missing":
        readers["industrial_route"].pop("argument")
    elif change == "extra":
        readers["war"]["argument"] = "anything"
    else:
        readers["industrial_route"]["argument"] = "x } every_country = {"
    with pytest.raises(ValueError):
        country_state.from_data(data)


def test_offline_interfaces_are_bound_to_snapshot_and_baseline():
    policy = country_state.load()
    assert country_state.validate(policy, snapshot=_snapshot())["enabled"]
    snapshots: tuple[dict[str, Any] | None, ...] = (
        None,
        {},
        {"sections": {}},
        {"sections": {"invented": {}}},
    )
    for snapshot in snapshots:
        with pytest.raises(ValueError):
            country_state.validate(policy, snapshot=snapshot)
    assert not country_state.validate(replace(policy, enabled=False))["enabled"]


@pytest.mark.parametrize(
    "change", ["schema", "sources", "interface", "argument", "path", "line", "hash"]
)
def test_tampered_evidence_is_rejected(tmp_path, change, monkeypatch):
    evidence = json.loads(country_interfaces.evidence_file().read_text(encoding="utf-8"))
    if change == "schema":
        evidence["schema"] = 2
    elif change == "sources":
        evidence.pop("sources")
    elif change == "interface":
        evidence["interfaces"].pop("is_at_war")
    elif change == "argument":
        evidence["arguments"] = []
    elif change == "path":
        evidence["sources"]["common/../../secret.txt"] = "a" * 64
    elif change == "line":
        evidence["arguments"][0]["line"] = 0
    else:
        evidence["baseline_sha256"] = "a" * 64
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(
        country_interfaces,
        (
            "EVIDENCE_1151_SHA256"
            if version_contracts.active_version() == "1.15.1"
            else "EVIDENCE_115_SHA256"
        ),
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )
    with pytest.raises(ValueError):
        country_interfaces.validate(country_state.load(), snapshot=_snapshot(), evidence_path=path)


def test_observations_do_not_accept_comments_or_variable_mentions():
    words, arguments = country_interfaces._observations(
        b'# in_default = yes\nx = { text = "set_variable" has_variable = imagined }\n',
        "events/test.txt",
    )
    assert "in_default" not in words
    assert "set_variable" not in words
    assert ("has_variable", "imagined") not in arguments
    _, arguments = country_interfaces._observations(
        b"x = { set_variable = { name = observed value = yes days = 1 } }\n",
        "events/test.txt",
    )
    assert ("has_variable", "observed") in arguments


def test_installed_evidence_detects_drift_and_wrong_ast_line(tmp_path, monkeypatch):
    if not (config.GAME / "common/ai_strategies/00_default_strategy.txt").is_file():
        pytest.skip("需要锁定原版")
    monkeypatch.setenv(
        version_contracts.ENVIRONMENT_VARIABLE,
        config.game_version()["caligula_branch"].removeprefix("release/"),
    )
    policy = country_state.load()
    evidence = json.loads(country_interfaces.evidence_file().read_text(encoding="utf-8"))
    for relative in {*evidence["sources"], "common/ai_strategies/00_default_strategy.txt"}:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(config.GAME / relative, target)
    country_interfaces.validate(policy, root=tmp_path)
    evidence["arguments"][0]["line"] += 1
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with monkeypatch.context() as rebinding:
        rebinding.setattr(
            country_interfaces,
            (
                "EVIDENCE_1151_SHA256"
                if version_contracts.active_version() == "1.15.1"
                else "EVIDENCE_115_SHA256"
            ),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        with pytest.raises(ValueError, match="样例不匹配"):
            country_interfaces.validate(policy, root=tmp_path, evidence_path=path)
    target = tmp_path / next(iter(evidence["sources"]))
    target.write_bytes(target.read_bytes() + b"\n# drift\n")
    with pytest.raises(ValueError, match="漂移"):
        country_interfaces.validate(policy, root=tmp_path)


def test_current_evidence_is_independently_captured_and_version_routed(monkeypatch, tmp_path):
    historical = country_interfaces.EVIDENCE
    with version_contracts.select_version("1.14.5"):
        assert country_interfaces.evidence_file() == historical
        assert country_interfaces.baseline_path() == country_interfaces.BASELINE
    monkeypatch.setattr(country_interfaces, "EVIDENCE", tmp_path / "historical-must-not-open.json")
    with version_contracts.select_version("1.15.0"):
        evidence = json.loads(country_interfaces.evidence_file().read_bytes())
        assert evidence["baseline_version"] == "1.15.0"
        assert len(evidence["interfaces"]) == 17
        assert len(evidence["arguments"]) == 5
        bureaucracy = evidence["interfaces"]["bureaucracy"]
        assert bureaucracy["source"] == "common/decisions/00_decisions.txt"
        assert bureaucracy["ast_context"]["assignment_key"] == "bureaucracy"
        assert bureaucracy["ast_context"]["operator"] == ">"
        assert bureaucracy["ast_context"]["ancestor_path"][-1]["key"] == "limit"
        assert all(
            row["ast_context"]["scope_authorization"] == "none_lexical_context_only"
            for row in [*evidence["interfaces"].values(), *evidence["arguments"]]
        )
        country_interfaces.validate(country_state.load(), snapshot=_snapshot())
        with pytest.raises(ValueError, match="当前权威证据漂移"):
            country_interfaces.validate(
                country_state.load(), snapshot=_snapshot(), evidence_path=historical
            )


@pytest.mark.parametrize("change", ["old-version", "missing-context", "scope-claim"])
def test_current_context_cannot_borrow_old_identity_or_grant_scope(tmp_path, change):
    with version_contracts.select_version("1.15.0"):
        evidence = json.loads(country_interfaces.evidence_file().read_bytes())
        if change == "old-version":
            evidence["baseline_version"] = "1.14.5"
        elif change == "missing-context":
            evidence["interfaces"]["is_at_war"].pop("ast_context")
        else:
            evidence["interfaces"]["is_at_war"]["ast_context"]["scope_authorization"] = (
                "any_country"
            )
        path = tmp_path / "changed.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        with pytest.raises(ValueError, match="当前"):
            country_interfaces.validate(
                country_state.load(), snapshot=_snapshot(), evidence_path=path
            )


def test_current_live_context_rejects_relocated_or_rebound_native_ast(tmp_path, monkeypatch):
    if not (config.GAME / "common/ai_strategies/00_default_strategy.txt").is_file():
        pytest.skip("需要锁定原版")
    with version_contracts.select_version(
        config.game_version()["caligula_branch"].removeprefix("release/")
    ):
        evidence = json.loads(country_interfaces.evidence_file().read_bytes())
        evidence["interfaces"]["bureaucracy"]["ast_context"]["ancestor_path"] = []
        path = tmp_path / "changed.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        monkeypatch.setattr(
            country_interfaces,
            (
                "EVIDENCE_1151_SHA256"
                if version_contracts.active_version() == "1.15.1"
                else "EVIDENCE_115_SHA256"
            ),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        with pytest.raises(ValueError, match="AST语境不匹配"):
            country_interfaces.validate(country_state.load(), root=config.GAME, evidence_path=path)


@pytest.mark.parametrize("damage", ["source", "line", "ancestor", "semantic"])
@pytest.mark.parametrize("explicit", [False, True])
def test_current_offline_authority_rejects_rebinding_with_unchanged_snapshot(
    tmp_path, monkeypatch, damage, explicit
):
    with version_contracts.select_version("1.15.0"):
        evidence = json.loads(country_interfaces.evidence_file().read_bytes())
        original_snapshot = evidence["snapshot_sections_sha256"]
        row = evidence["interfaces"]["bureaucracy"]
        if damage == "source":
            row["source"] = next(iter(evidence["sources"]))
        elif damage == "line":
            row["line"] += 1
        elif damage == "ancestor":
            row["ast_context"]["ancestor_path"] = []
        else:
            row["ast_context"]["assignment_ast_sha256"] = "a" * 64
        assert evidence["snapshot_sections_sha256"] == original_snapshot
        path = tmp_path / "changed.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        if not explicit:
            monkeypatch.setattr(country_interfaces, "evidence_file", lambda: path)
        with pytest.raises(ValueError, match="当前权威证据漂移"):
            country_interfaces.validate(
                country_state.load(), snapshot=_snapshot(), evidence_path=path if explicit else None
            )
