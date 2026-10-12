"""维修图标资源诊断的原件字节、边界与失败保护。"""

import hashlib
import json
import os
import struct
import sys
from pathlib import Path

import pytest

from pdx import decisions, resource_baseline

pytestmark = pytest.mark.unit

SOURCE = "gfx/interface/icons/generic_icons/repairing.dds"
TARGET = "gfx/interface/icons/alert_icons/repairing.dds"
GUI = "gui/texticons.gui"
READ_GAME_VERSION = resource_baseline.config.game_version


def _dds():
    header = [0] * 31
    header[0:4] = [124, 0x1007, 4, 4]
    header[18:21] = [32, 4, int.from_bytes(b"DXT5", "little")]
    header[26] = 0x1000
    return b"DDS " + struct.pack("<31I", *header) + bytes(range(16))


@pytest.fixture
def originals(tmp_path, monkeypatch):
    monkeypatch.setattr(
        resource_baseline.config,
        "game_version",
        lambda _root=None: {"caligula_branch": "release/1.14.5"},
    )
    game = tmp_path / "install/game"
    source, gui = game / SOURCE, game / GUI
    source.parent.mkdir(parents=True)
    source.write_bytes(_dds())
    gui.parent.mkdir()
    gui.write_text(f'icon = {{ texture = "{TARGET}" }}\n', encoding="utf-8", newline="\n")
    return game, tmp_path / "output"


def test_仅两个成员逐字复制并完整审计(originals):
    game, output = originals
    before = (game / SOURCE).read_bytes()
    manifest = resource_baseline.write(output, game)
    assert (output / TARGET).read_bytes() == before == (game / SOURCE).read_bytes()
    assert {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()} == {
        TARGET,
        ".metadata/metadata.json",
    }
    assert manifest["schema"] == "sitai-resource-baseline-v1"
    assert manifest["purpose"] == "diagnostic-resource-only"
    assert manifest["source"] == {"path": SOURCE, "sha256": hashlib.sha256(before).hexdigest()}
    assert manifest["output"] == {"path": TARGET, "sha256": manifest["source"]["sha256"]}
    assert manifest["gui"] == {
        "path": GUI,
        "sha256": hashlib.sha256((game / GUI).read_bytes()).hexdigest(),
    }
    assert manifest["copied_bytes"] == len(before)
    assert "不证明模拟无扰动" in manifest["boundary"]
    metadata = (output / ".metadata/metadata.json").read_bytes()
    assert not metadata.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in metadata
    assert json.loads(metadata)["game_custom_data"]["multiplayer_synchronized"] is False
    assert json.loads(metadata)["supported_game_version"] == "1.14.5"
    standard = decisions.metadata_payload()
    assert set(json.loads(metadata)) == set(standard)
    assert json.loads(metadata)["tags"] == standard["tags"] == []
    assert json.loads(metadata)["relationships"] == standard["relationships"] == []
    assert json.loads(metadata)["supported_game_version"] == standard["supported_game_version"]
    assert json.loads(metadata)["game_custom_data"]["resource_baseline"] == manifest


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ({"caligula_branch": "release/1.14.6"}, "1.14.6"),
        ({"version": "1.15.0"}, "1.15.0"),
    ],
)
def test_metadata版本沿用安装配置而非硬编码(originals, monkeypatch, version, expected):
    monkeypatch.setattr(resource_baseline.config, "game_version", lambda _root=None: version)
    game, output = originals
    resource_baseline.write(output, game)
    metadata = json.loads((output / ".metadata/metadata.json").read_text(encoding="utf-8"))
    assert metadata["supported_game_version"] == expected


@pytest.mark.parametrize("version", [{}, {"caligula_branch": ""}, {"version": "  "}])
def test_缺失安装版本拒绝生成metadata(originals, monkeypatch, version):
    monkeypatch.setattr(resource_baseline.config, "game_version", lambda _root=None: version)
    game, output = originals
    with pytest.raises(ValueError, match="游戏版本"):
        resource_baseline.write(output, game)
    assert output.exists()
    assert not (output / ".metadata/metadata.json").exists()


def test_另一安装版本取传入game而非默认ROOT(originals, monkeypatch, tmp_path):
    game, output = originals
    default_install = tmp_path / "default-install"
    default_install.mkdir()
    (default_install / "caligula_branch.txt").write_text("release/9.9.9\n", encoding="utf-8")
    (game.parent / "caligula_branch.txt").write_text("release/1.14.6\n", encoding="utf-8")
    monkeypatch.setattr(resource_baseline.config, "ROOT", default_install)
    monkeypatch.setattr(resource_baseline.config, "game_version", READ_GAME_VERSION)
    resource_baseline.write(output, game)
    metadata = json.loads((output / ".metadata/metadata.json").read_text(encoding="utf-8"))
    assert metadata["supported_game_version"] == "1.14.6"
    assert resource_baseline.config.game_version()["caligula_branch"] == "release/9.9.9"


@pytest.mark.parametrize("missing", [SOURCE, GUI])
def test_原件缺失拒绝且不创建输出(originals, missing):
    game, output = originals
    (game / missing).unlink()
    with pytest.raises(ValueError, match="无法读取原件"):
        resource_baseline.write(output, game)
    assert not output.exists()


def test_已修复安装拒绝(originals):
    game, output = originals
    target = game / TARGET
    target.parent.mkdir()
    target.write_bytes(_dds())
    with pytest.raises(ValueError, match="目标已存在"):
        resource_baseline.write(output, game)
    assert target.read_bytes() == _dds()
    assert not output.exists()


@pytest.mark.parametrize(
    "gui",
    [f'# texture = "{TARGET}"\n', f'note = "{TARGET}"\n', 'texture = "other.dds"\n'],
)
def test_没有实际纹理引用拒绝(originals, gui):
    game, output = originals
    (game / GUI).write_text(gui, encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="没有实际引用"):
        resource_baseline.write(output, game)
    assert not output.exists()


@pytest.mark.parametrize(
    ("offset", "value"),
    [(0, 0), (4, 123), (8, 0), (12, 0), (16, 99999), (76, 31), (80, 0), (108, 0)],
)
def test_坏DDS拒绝(originals, offset, value):
    game, output = originals
    bad = bytearray(_dds())
    struct.pack_into("<I", bad, offset, value)
    (game / SOURCE).write_bytes(bad)
    with pytest.raises(ValueError, match="DDS"):
        resource_baseline.write(output, game)
    assert not output.exists()


@pytest.mark.parametrize("data", [b"DDS ", _dds()[:128], _dds()[:84] + b"DX10" + _dds()[88:]])
def test_不完整DDS拒绝(originals, data):
    game, output = originals
    (game / SOURCE).write_bytes(data)
    with pytest.raises(ValueError, match="DDS"):
        resource_baseline.write(output, game)
    assert not output.exists()


@pytest.mark.parametrize("populated", [False, True])
def test_已有目录拒绝并保留未知文件(originals, populated):
    game, output = originals
    output.mkdir()
    if populated:
        (output / "unknown.bin").write_bytes(b"preserve")
    with pytest.raises(ValueError, match="输出已存在"):
        resource_baseline.write(output, game)
    assert output.is_dir()
    assert list(output.iterdir()) == ([output / "unknown.bin"] if populated else [])
    if populated:
        assert (output / "unknown.bin").read_bytes() == b"preserve"


@pytest.mark.parametrize("location", ["game", "install", "source", "user"])
def test_输出不能侵入安装与用户原件(originals, monkeypatch, tmp_path, location):
    game, _output = originals
    user = tmp_path / "user"
    monkeypatch.setattr(resource_baseline.config, "USERDIR", user)
    base = {"game": game, "install": game.parent, "source": (game / SOURCE).parent, "user": user}[
        location
    ]
    output = base / "diagnostic"
    with pytest.raises(ValueError, match="原件目录"):
        resource_baseline.write(output, game)
    assert not output.exists()


@pytest.mark.parametrize("location", [SOURCE, GUI, TARGET, "output", "parent"])
def test_链接路径拒绝且保留链接(originals, tmp_path, location):
    game, output = originals
    link = (
        output
        if location == "output"
        else tmp_path / "linked"
        if location == "parent"
        else game / location
    )
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists():
        link.unlink()
    target = tmp_path / "link-target"
    target.mkdir() if location in {"output", "parent"} else target.write_bytes(_dds())
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as exc:
        pytest.skip(f"当前平台未授予符号链接能力：{exc}")
    if location == "parent":
        output = link / "new-output"
    with pytest.raises(ValueError, match="链接"):
        resource_baseline.write(output, game)
    assert link.is_symlink()
    assert not (target / "new-output").exists()


@pytest.mark.parametrize("changed", [SOURCE, GUI])
@pytest.mark.parametrize("phase", ["read", "before-write", "after-write"])
def test_读取或生成前原件变化拒绝(originals, monkeypatch, changed, phase):
    game, output = originals
    digest = resource_baseline.deployment_state.digest
    calls = 0

    def mutate(path):
        nonlocal calls
        if path == game / changed:
            calls += 1
            if calls == {"read": 1, "before-write": 2, "after-write": 3}[phase]:
                path.write_bytes(path.read_bytes() + b"changed")
        return digest(path)

    monkeypatch.setattr(resource_baseline.deployment_state, "digest", mutate)
    with pytest.raises(ValueError, match="发生变化"):
        resource_baseline.write(output, game)
    assert output.exists() is (phase == "after-write")


def test_硬链接原件拒绝(originals, tmp_path):
    game, output = originals
    (tmp_path / "hard-link").hardlink_to(game / SOURCE)
    with pytest.raises(ValueError, match="硬链接"):
        resource_baseline.write(output, game)
    assert not output.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="junction 是 Windows 路径类型")
@pytest.mark.parametrize("location", ["source", "target", "output-parent", "game"])
def test_真实junction拒绝且不写入目标(originals, tmp_path, location):
    import _winapi

    game, output = originals
    target = tmp_path / "junction-target"
    target.mkdir()
    link = tmp_path / "junction"
    _winapi.CreateJunction(str(target), str(link))
    if location == "source":
        (game / SOURCE).unlink()
        (game / SOURCE).parent.rmdir()
        _winapi.CreateJunction(str(target), str((game / SOURCE).parent))
    elif location == "target":
        _winapi.CreateJunction(str(target), str((game / TARGET).parent))
    elif location == "game":
        game = link
    else:
        output = link / "output"
    try:
        with pytest.raises(ValueError, match="链接"):
            resource_baseline.write(output, game)
        assert list(target.iterdir()) == []
    finally:
        link.rmdir()
        if location in {"source", "target"}:
            (originals[0] / (SOURCE if location == "source" else TARGET)).parent.rmdir()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="平台没有 FIFO")
def test_特殊原件不能被阻塞读取(originals):
    game, output = originals
    source = game / SOURCE
    source.unlink()
    mkfifo = vars(os)["mkfifo"]
    mkfifo(source)
    with pytest.raises(ValueError, match="特殊文件"):
        resource_baseline.write(output, game)
    assert not output.exists()


def test_输出失败不删除未知内容(originals, monkeypatch):
    game, output = originals
    original_open = Path.open

    def fail(path, *args, **kwargs):
        if path == output / TARGET:
            (output / "unknown.bin").write_bytes(b"preserve")
            raise OSError("injected")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(ValueError, match="现场保留"):
        resource_baseline.write(output, game)
    assert (output / "unknown.bin").read_bytes() == b"preserve"
