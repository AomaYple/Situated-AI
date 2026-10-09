"""检查点预检不能把可载入、未知机会与实际行为资格混为一谈。"""

from __future__ import annotations

import hashlib

import pytest

from pdx import checkpoint_catalog

pytestmark = pytest.mark.unit


def save(path, *, version="1.14.5", extra=b""):
    path.write_bytes(
        ('SAV0100\nmeta_data={version="' + version + '" game_date=1836.2.1}\n').encode()
        + b"player_manager={database={}}\n"
        + extra
    )
    return path


def test_有效观察者不代表已知机会(tmp_path):
    path = save(tmp_path / "clean.v3")
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert result["state"] == "opportunity-unknown"
    assert result["instrument_suitable"] is True
    assert result["opportunity_count"] is None
    assert result["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert checkpoint_catalog.preflight(result, purpose="instrument", months=1)["allowed"]
    assert not checkpoint_catalog.preflight(result, purpose="M3-B", months=1)["allowed"]


@pytest.mark.parametrize("extra", [b"setting_sitai_old=yes", b'settings={""}'])
def test_旧状态和空规则拒绝且保留证据(tmp_path, extra):
    path = save(tmp_path / "bad.v3", extra=extra)
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert result["state"] == "rejected"
    assert result["reasons"]
    assert result["sha256"]
    assert path.exists()


def test_版本不同仅显式升级仪器可用(tmp_path):
    path = save(tmp_path / "old.v3", version="1.14.4")
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5")
    assert not checkpoint_catalog.preflight(result, purpose="instrument", months=1)["allowed"]
    result = checkpoint_catalog.inspect(path, expected_version="1.14.5", allow_save_upgrade=True)
    assert result["state"] == "instrument-suitable"
    assert not checkpoint_catalog.preflight(result, purpose="M3-A", months=1)["allowed"]


@pytest.mark.parametrize("months", [0, -1, float("nan"), float("inf"), 7])
def test_探索预算不接受无限或超额(tmp_path, months):
    result = checkpoint_catalog.inspect(save(tmp_path / "clean.v3"), expected_version="1.14.5")
    assert not checkpoint_catalog.preflight(result, purpose="reconnaissance", months=months)[
        "allowed"
    ]


def test_正式证据不能由未知或评分结果提名(tmp_path):
    result = checkpoint_catalog.inspect(save(tmp_path / "clean.v3"), expected_version="1.14.5")
    for purpose in ("M3-A", "M3-B"):
        decision = checkpoint_catalog.preflight(result, purpose=purpose, months=6)
        assert not decision["allowed"]
        assert "opportunity.unverified" in decision["reasons"]
