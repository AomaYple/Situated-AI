"""无游戏 CI 审计冻结合同；生产重建必须仍依赖真实原版。"""

import codecs
import json

import pytest
from typer.testing import CliRunner

from pdx import cli, config, decisions, distribution, version_contracts


@pytest.fixture
def frozen_product(tmp_path, monkeypatch):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", "1.14.5")
    product = tmp_path / "mod"
    for name, raw in {
        "src/pdx/generator.py": b"SOURCE = 1\n",
        "mod/decisions/policy.toml": b"enabled = true\n",
        "research/vanilla-ai/1.14.5/default.txt": decisions._HISTORICAL_BASELINE.read_bytes(),
        "mod/common/values.txt": b"value = 1\n",
        "mod/localization/english/l_english.yml": b"l_english:\n",
        "mod/.metadata/metadata.json": b"{}\n",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    monkeypatch.setattr(decisions, "PRODUCT", product)
    monkeypatch.setattr(decisions, "BASELINE", tmp_path / "research/vanilla-ai/1.14.5/default.txt")
    (product / "generation-lock.json").write_text(
        distribution.generation_lock(), encoding="utf-8", newline="\n"
    )
    return product


def test_frozen_lock_is_deterministic_and_excludes_delivery_guide(frozen_product):
    distribution.check_generation_lock()
    original = distribution.generation_lock()
    files = distribution.read_production_files()
    files["README.md"] = "交付说明\n"
    assert distribution.generation_lock(files) == original
    lock = json.loads(original)
    assert lock["evidence"] == "frozen_generation_not_current_game_verification"
    assert len(lock["sources"]) == 3
    assert len(lock["files"]) == 3


@pytest.mark.parametrize(
    ("name", "operation"),
    [
        ("../src/pdx/generator.py", "change"),
        ("../src/pdx/added.py", "add"),
        ("decisions/policy.toml", "delete"),
        ("common/values.txt", "change"),
        ("common/values.txt", "crlf"),
        ("common/values.txt", "bom"),
        ("common/values.txt", "delete"),
        ("common/added.txt", "add"),
        ("localization/english/l_english.yml", "change"),
        (".metadata/metadata.json", "change"),
        ("generation-lock.json", "change"),
    ],
)
def test_lock_rejects_source_and_exact_byte_drift(frozen_product, name, operation):
    path = frozen_product / name
    if operation == "delete":
        path.unlink()
    elif operation == "crlf":
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    elif operation == "bom":
        path.write_bytes(codecs.BOM_UTF8 + path.read_bytes())
    else:
        path.write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="冻结记录不一致"):
        distribution.check_generation_lock()


def test_missing_lock_is_an_error(frozen_product):
    (frozen_product / "generation-lock.json").unlink()
    with pytest.raises(FileNotFoundError):
        distribution.check_generation_lock()


@pytest.mark.parametrize("operation", ["add", "change", "delete"])
def test_lock_tracks_nested_production_modules(frozen_product, operation):
    path = frozen_product.parent / "src/pdx/situated/kernel.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    if operation != "add":
        path.write_bytes(b"VALUE = 1\n")
    (frozen_product / "generation-lock.json").write_text(
        distribution.generation_lock(), encoding="utf-8", newline="\n"
    )
    if operation == "delete":
        path.unlink()
    else:
        path.write_bytes(b"VALUE = 2\n")
    with pytest.raises(ValueError, match="冻结记录不一致"):
        distribution.check_generation_lock()


@pytest.mark.parametrize("operation", ["add", "change", "delete"])
def test_lock_tracks_independent_historical_migration_manifest(frozen_product, operation):
    path = frozen_product.parent / "research/situated/v3.0.1-migration.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if operation != "add":
        path.write_bytes(b'{"historical": true}\n')
    (frozen_product / "generation-lock.json").write_text(
        distribution.generation_lock(), encoding="utf-8", newline="\n"
    )
    if operation == "delete":
        path.unlink()
    else:
        path.write_bytes(b'{"historical": false}\n')
    with pytest.raises(ValueError, match="冻结记录不一致"):
        distribution.check_generation_lock()


def test_no_game_offline_guard_uses_frozen_snapshot_contract(frozen_product, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GAME", tmp_path / "missing-game")
    result = CliRunner().invoke(cli.app, ["modguard", "--offline"])
    assert result.exit_code == 0, result.output
    assert "冻结源码/产物" in result.output
    assert "不证明当前游戏内容" in result.output


def test_current_lock_tracks_versioned_sources_and_uses_isolated_tree(frozen_product, monkeypatch):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", "1.15.0")
    selected = frozen_product / "compatibility"
    selected.mkdir()
    (selected / "common").mkdir()
    (selected / "common/current.txt").write_bytes(b"current = yes\n")
    monkeypatch.setattr(decisions, "product_path", lambda: selected)
    source = frozen_product.parent / "mod/decisions/1.15.0/action_bindings.toml"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"version = '1.15.0'\n")
    lock = distribution.generation_lock()
    (selected / "generation-lock.json").write_text(lock, encoding="utf-8", newline="\n")
    distribution.check_generation_lock()
    assert version_contracts.active_version() == "1.15.0"
    assert "mod/decisions/1.15.0/action_bindings.toml" in json.loads(lock)["sources"]
    source.write_bytes(b"version = 'unreviewed'\n")
    with pytest.raises(ValueError, match="冻结记录不一致"):
        distribution.check_generation_lock()


def test_no_game_production_generation_refuses_and_preserves_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("V3_CONTRACT_PROFILE", "1.14.5")
    monkeypatch.setattr(config, "GAME", tmp_path / "missing-game")
    product = tmp_path / "mod"
    product.mkdir()
    sentinel = product / "existing.txt"
    sentinel.write_bytes(b"previous production\n")
    monkeypatch.setattr(decisions, "PRODUCT", product)
    baseline = tmp_path / "baseline.txt"
    baseline.write_bytes(decisions._HISTORICAL_BASELINE.read_bytes())
    monkeypatch.setattr(decisions, "BASELINE", baseline)
    target = tmp_path / "existing.zip"
    target.write_bytes(b"previous zip")
    with pytest.raises(ValueError, match="缺少锁定游戏原件"):
        distribution.package(target)
    assert target.read_bytes() == b"previous zip"
    for command in (["modgen", "--write"], ["modgen", "--check"]):
        result = CliRunner().invoke(cli.app, command)
        assert result.exit_code == 1, result.output
        assert "缺少锁定游戏原件" in result.output
        assert list(product.iterdir()) == [sentinel]
        assert sentinel.read_bytes() == b"previous production\n"
