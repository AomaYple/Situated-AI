"""无游戏 CI 审计冻结合同；生产重建必须仍依赖真实原版。"""

import codecs
import json

import pytest
from typer.testing import CliRunner

from pdx import cli, config, decisions, distribution


@pytest.fixture
def frozen_product(tmp_path, monkeypatch):
    product = tmp_path / "mod"
    for name, raw in {
        "src/pdx/generator.py": b"SOURCE = 1\n",
        "mod/decisions/policy.toml": b"enabled = true\n",
        "research/vanilla-ai/1.14.5/default.txt": b"default = {}\n",
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


def test_no_game_offline_guard_uses_frozen_snapshot_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GAME", tmp_path / "missing-game")
    result = CliRunner().invoke(cli.app, ["modguard", "--offline"])
    assert result.exit_code == 0, result.output
    assert "冻结源码/产物" in result.output
    assert "不证明当前游戏内容" in result.output


def test_no_game_production_generation_refuses_and_preserves_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GAME", tmp_path / "missing-game")
    product = tmp_path / "mod"
    product.mkdir()
    sentinel = product / "existing.txt"
    sentinel.write_bytes(b"previous production\n")
    monkeypatch.setattr(decisions, "PRODUCT", product)
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
