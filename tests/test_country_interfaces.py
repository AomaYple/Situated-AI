"""Frozen and installed vanilla interface evidence must fail closed."""

from __future__ import annotations

import json
import shutil
import tomllib
from dataclasses import replace
from typing import Any

import pytest

from pdx import config, country_interfaces, country_state, vanilla_index


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
def test_tampered_evidence_is_rejected(tmp_path, change):
    evidence = json.loads(country_interfaces.EVIDENCE.read_text(encoding="utf-8"))
    if change == "schema":
        evidence["schema"] = 2
    elif change == "sources":
        evidence.pop("sources")
    elif change == "interface":
        evidence["interfaces"].pop("set_variable")
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


def test_installed_evidence_detects_drift_and_wrong_ast_line(tmp_path):
    if not (config.GAME / "common/ai_strategies/00_default_strategy.txt").is_file():
        pytest.skip("需要锁定原版")
    policy = country_state.load()
    evidence = json.loads(country_interfaces.EVIDENCE.read_text(encoding="utf-8"))
    for relative in {*evidence["sources"], "common/ai_strategies/00_default_strategy.txt"}:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(config.GAME / relative, target)
    country_interfaces.validate(policy, root=tmp_path)
    evidence["arguments"][0]["line"] += 1
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(ValueError, match="样例不匹配"):
        country_interfaces.validate(policy, root=tmp_path, evidence_path=path)
    target = tmp_path / next(iter(evidence["sources"]))
    target.write_bytes(target.read_bytes() + b"\n# drift\n")
    with pytest.raises(ValueError, match="漂移"):
        country_interfaces.validate(policy, root=tmp_path)
