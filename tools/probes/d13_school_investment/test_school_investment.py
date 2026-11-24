"""静态回读试片 ZIP、学校消费位置与独立手填的条件矩阵。"""

import codecs
import hashlib
import json
import zipfile

import pytest

from pdx.model import Assignment, Block, Scalar
from pdx.parser import parse_bytes
from pdx.situated import pdx_eval
from tools.probes.d13_school_investment.build import STRATEGY, verify_default, write_arm

_NATIVE = """
ai_strategy_synthetic = { marker = 17 }
ai_strategy_default = {
    marker = 31
    institution_scores = {
        institution_synthetic = { value = 71 }
        institution_schools = { value = 10 }
    }
}
"""
_ROOT = {
    "is_ai": True,
    "has_institution": {(("argument", "institution_schools"),): True},
    "has_law": {(("argument", "law_type:law_public_schools"),): True},
    "literacy_rate": 0.35,
    "bureaucracy": 9,
    "in_default": False,
    "net_total_income": 200,
    "any_scope_state": [{"is_incorporated": True, "state_population": 50000}],
}


def _block(item: Assignment | None) -> Block:
    assert item is not None
    assert isinstance(item.value, Block)
    return item.value


def test_native_shape_accepts_unrelated_fields():
    verify_default(_NATIVE)


@pytest.mark.parametrize(
    ("old", "changed"),
    [
        ("value = 10", "value = 9"),
        ("value = 10", "value = 10 add = 2"),
        ("institution_schools", "institution_missing"),
        ("institution_schools = { value = 10 }", "institution_schools = { value = 10 } " * 2),
        ("ai_strategy_default =", "REPLACE:ai_strategy_default ="),
    ],
)
def test_native_shape_rejects_drift(old, changed):
    with pytest.raises(ValueError, match="D13"):
        verify_default(_NATIVE.replace(old, changed))


@pytest.fixture
def arms(tmp_path):
    payloads = {}
    for arm in ("neutral", "diagnostic", "candidate"):
        path = tmp_path / f"{arm}.zip"
        report = write_arm(path, arm)
        with zipfile.ZipFile(path) as archive:
            assert set(archive.namelist()) == {".metadata/metadata.json", STRATEGY}
            assert archive.testzip() is None
            script = archive.read(STRATEGY)
            metadata_bytes = archive.read(".metadata/metadata.json")
        assert report["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert report["files"] == {
            STRATEGY: hashlib.sha256(script).hexdigest(),
            ".metadata/metadata.json": hashlib.sha256(metadata_bytes).hexdigest(),
        }
        assert script.startswith(codecs.BOM_UTF8)
        assert b"\r" not in script
        metadata = json.loads(metadata_bytes.decode("utf-8"))
        assert metadata["id"] == f"sitai-d13-schools-{arm}"
        assert metadata["supported_game_version"] == "1.15.2"
        assert metadata["game_custom_data"] == {"multiplayer_synchronized": False}
        assert "replace_path" not in metadata
        payloads[arm] = script
    return payloads


def _guard_and_amount(script: bytes) -> tuple[Block, float]:
    parsed = parse_bytes(script, STRATEGY)
    parsed.require_complete()
    (strategy,) = parsed.root.items
    assert isinstance(strategy, Assignment)
    assert (strategy.prefix, strategy.key, strategy.op) == ("INJECT", "ai_strategy_default", "=")
    strategy_body = _block(strategy)
    assert strategy_body.keys() == ["institution_scores"]
    score_map = _block(strategy_body.first("institution_scores"))
    assert score_map.keys() == ["institution_schools"]
    schools = _block(score_map.first("institution_schools"))
    assert schools.keys() == ["add"]
    contribution = _block(schools.first("add"))
    assert contribution.keys() == ["value", "if"]
    initial = contribution.first("value")
    assert initial is not None
    assert isinstance(initial.value, Scalar)
    assert initial.value.text == "0"
    conditional = _block(contribution.first("if"))
    assert conditional.keys() == ["limit", "add"]
    delta = conditional.first("add")
    assert delta is not None
    assert isinstance(delta.value, Scalar)
    return _block(conditional.first("limit")), float(delta.value.text)


def test_the_only_difference_in_scripts_is_the_authorized_delta(arms):
    candidate = arms["candidate"]
    marker = b"\t\t\t\t\tadd = 0.25\n"
    assert candidate.count(marker) == 1
    assert arms["neutral"] == candidate.replace(marker, b"\t\t\t\t\tadd = 0\n")
    assert arms["diagnostic"] == candidate.replace(marker, b"\t\t\t\t\tadd = 10000\n")
    for arm, expected in (("neutral", 0), ("diagnostic", 10000), ("candidate", 0.25)):
        guard, amount = _guard_and_amount(arms[arm])
        assert amount == expected
        assert pdx_eval.condition(guard, {"ROOT": _ROOT}) is True


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, 0.25),
        ({"literacy_rate": 0}, 0.25),
        ({"literacy_rate": 0.4999}, 0.25),
        ({"literacy_rate": 0.5}, 0),
        ({"literacy_rate": -0.01}, 0),
        ({"literacy_rate": None}, 0),
        ({"bureaucracy": -1}, 0),
        ({"bureaucracy": 0}, 0),
        ({"bureaucracy": 1}, 0.25),
        ({"bureaucracy": None}, 0),
        ({"net_total_income": -1}, 0),
        ({"net_total_income": 0}, 0),
        ({"net_total_income": None}, 0),
        ({"in_default": True}, 0),
        ({"in_default": None}, 0),
        ({"has_law": {(("argument", "law_type:law_public_schools"),): False}}, 0),
        ({"has_law": {(("argument", "law_type:law_private_schools"),): True}}, 0),
        ({"has_institution": {(("argument", "institution_schools"),): False}}, 0),
        ({"has_institution": {}}, 0),
        ({"is_ai": False}, 0),
        ({"is_ai": None}, 0),
        ({"any_scope_state": []}, 0),
        ({"any_scope_state": None}, 0),
        ({"any_scope_state": [{"is_incorporated": False, "state_population": 1000}]}, 0),
        ({"any_scope_state": [{"is_incorporated": True, "state_population": 0}]}, 0),
        ({"any_scope_state": [{"is_incorporated": True, "state_population": None}]}, 0),
    ],
)
def test_candidate_reads_only_country_root_and_uses_zero_for_unproved_contribution(
    arms, overrides, expected
):
    guard, amount = _guard_and_amount(arms["candidate"])
    state = pdx_eval.condition(guard, {**_ROOT, "ROOT": {**_ROOT, **overrides}})
    contribution = amount if state is True else 0
    assert contribution == expected


def test_missing_country_root_omits_the_bonus_even_if_flat_facts_match(arms):
    guard, _ = _guard_and_amount(arms["candidate"])
    assert pdx_eval.condition(guard, {**_ROOT, "ROOT": None}) is False


def test_zip_freeze_is_deterministic_and_does_not_replace_the_original(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    write_arm(first, "candidate")
    write_arm(second, "candidate")
    expected = first.read_bytes()
    assert expected == second.read_bytes()
    with pytest.raises(FileExistsError):
        write_arm(first, "neutral")
    assert first.read_bytes() == expected
