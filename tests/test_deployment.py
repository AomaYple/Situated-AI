"""部署必须保留原始字节、限制目录归属，并在替换失败时恢复旧树。"""

import json
from pathlib import Path

import pytest


def trees(tmp_path, monkeypatch):
    from pdx import deployment

    monkeypatch.setattr(deployment, "assert_game_stopped", lambda: None)
    source = tmp_path / "content"
    (source / ".metadata").mkdir(parents=True)
    (source / ".metadata/metadata.json").write_text('{"id":"situated-ai"}', encoding="utf-8")
    (source / "script.txt").write_bytes(b"\xef\xbb\xbfnew\n")
    userdir = tmp_path / "user"
    target = userdir / "mod/Situated AI"
    target.mkdir(parents=True)
    (target / ".metadata").mkdir()
    (target / ".metadata/metadata.json").write_text('{"id":"situated-ai"}', encoding="utf-8")
    (target / "old.txt").write_bytes(b"old\r\n")
    (userdir / "content_load.json").write_bytes(b'{ "enabled_mods" : [] }\r\n')
    return deployment, source, userdir, target


def test_deploy_preserves_bytes_and_backs_up_outside_mod_scan(tmp_path, monkeypatch):
    deployment, source, userdir, target = trees(tmp_path, monkeypatch)
    result = deployment.deploy(source, userdir)
    assert result["status"] == "succeeded"
    assert (target / "script.txt").read_bytes() == b"\xef\xbb\xbfnew\n"
    assert not (target / "old.txt").exists()
    backup = Path(result["backup"])
    assert (backup / "old.txt").read_bytes() == b"old\r\n"
    assert userdir / "mod" not in backup.parents
    assert (userdir / "content_load.json").read_bytes() == b'{ "enabled_mods" : [] }\r\n'
    second = deployment.deploy(source, userdir)
    assert second["status"] == "unchanged"
    assert second["backup"] is None
    assert not list(userdir.glob(".sitai-stage-*"))


def test_failed_install_restores_original_tree(tmp_path, monkeypatch):
    deployment, source, userdir, target = trees(tmp_path, monkeypatch)
    rename = Path.rename

    def fail_install(path, destination):
        if path.name == "content" and path.parent.name.startswith(".sitai-stage-"):
            raise PermissionError("模拟游戏锁定")
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_install)
    with pytest.raises(PermissionError, match="模拟游戏锁定"):
        deployment.deploy(source, userdir)
    assert (target / "old.txt").read_bytes() == b"old\r\n"
    assert not (target / "script.txt").exists()
    assert not list(userdir.glob(".sitai-stage-*"))


def test_foreign_directory_is_not_replaced(tmp_path, monkeypatch):
    deployment, source, userdir, target = trees(tmp_path, monkeypatch)
    (target / ".metadata/metadata.json").write_text('{"id":"other-mod"}', encoding="utf-8")
    with pytest.raises(ValueError, match="身份"):
        deployment.deploy(source, userdir)
    assert (target / "old.txt").read_bytes() == b"old\r\n"


def test_active_game_prevents_all_local_writes(tmp_path, monkeypatch):
    deployment, source, userdir, target = trees(tmp_path, monkeypatch)

    def running():
        raise ValueError("游戏或启动器仍在运行")

    monkeypatch.setattr(deployment, "assert_game_stopped", running)
    with pytest.raises(ValueError, match="仍在运行"):
        deployment.deploy(source, userdir)
    assert (target / "old.txt").exists()
    assert not list(userdir.glob(".sitai-stage-*"))


def test_linked_user_directory_is_rejected(tmp_path, monkeypatch):
    deployment, source, userdir, _ = trees(tmp_path, monkeypatch)
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(userdir, target_is_directory=True)
    except OSError:
        pytest.skip("系统未授予符号链接权限")
    with pytest.raises(ValueError, match="链接"):
        deployment.deploy(source, linked)


def test_deployment_lock_does_not_get_stolen(tmp_path, monkeypatch):
    deployment, source, userdir, target = trees(tmp_path, monkeypatch)
    with deployment.deployment_lock(userdir), pytest.raises(ValueError, match="锁"):
        deployment.deploy(source, userdir)
    assert (target / "old.txt").exists()


def test_process_guard_identifies_game_and_launcher(monkeypatch):
    from types import SimpleNamespace

    from pdx import deployment

    monkeypatch.setattr(
        deployment.psutil,
        "process_iter",
        lambda *_args, **_kwargs: [SimpleNamespace(info={"name": "victoria3.exe"})],
    )
    with pytest.raises(ValueError, match="运行"):
        deployment.assert_game_stopped()


def test_fresh_install_does_not_require_old_metadata(tmp_path, monkeypatch):
    deployment, source, userdir, target = trees(tmp_path, monkeypatch)
    import shutil

    shutil.rmtree(target)
    result = deployment.deploy(source, userdir)
    assert result["backup"] is None
    assert json.loads((target / ".metadata/metadata.json").read_text()) == {"id": "situated-ai"}


def test_verification_failure_restores_original_tree(tmp_path, monkeypatch):
    deployment, source, userdir, target = trees(tmp_path, monkeypatch)
    hashes = deployment.tree_hashes

    def corrupt_install(root):
        actual = hashes(root)
        if root == target and (target / "script.txt").exists():
            return {"corrupted": "hash"}
        return actual

    monkeypatch.setattr(deployment, "tree_hashes", corrupt_install)
    with pytest.raises(ValueError, match="安装后"):
        deployment.deploy(source, userdir)
    assert (target / "old.txt").read_bytes() == b"old\r\n"
    assert not (target / "script.txt").exists()
