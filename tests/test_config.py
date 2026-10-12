"""版本指纹默认安装与显式安装读取合同。"""

import pytest

from pdx import config

pytestmark = pytest.mark.unit


def test_版本指纹显式安装不改变默认根(tmp_path, monkeypatch):
    default, alternate = tmp_path / "default", tmp_path / "alternate"
    default.mkdir()
    alternate.mkdir()
    (default / "caligula_branch.txt").write_text("release/1.14.5\n", encoding="utf-8")
    (alternate / "caligula_branch.txt").write_text("\ufeffrelease/1.14.6\n", encoding="utf-8")
    (alternate / "caligula_rev.txt").write_text("different-revision\n", encoding="utf-8")
    monkeypatch.setattr(config, "ROOT", default)
    assert config.game_version()["caligula_branch"] == "release/1.14.5"
    version = config.game_version(alternate)
    assert version == {
        "caligula_branch": "release/1.14.6",
        "caligula_rev": "different-revision",
        "clausewitz_branch": "",
        "clausewitz_rev": "",
    }
    assert default == config.ROOT
    assert config.game_version()["caligula_branch"] == "release/1.14.5"
