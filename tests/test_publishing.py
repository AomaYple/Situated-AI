"""固定包发布的可观察边界：预览不写、预检先行、部分失败保留真实状态。"""

import json
import shutil
import zipfile

import pytest
from typer.testing import CliRunner

from pdx import config


def test_cli_publish_preview_is_available_without_executing(tmp_path):
    from pdx.cli import app

    result = CliRunner().invoke(app, ["publish", "--help"])
    assert result.exit_code == 0
    assert "--execute" in result.output


def test_all_game_languages_have_real_bodies():
    from pdx import publishing

    bodies = publishing.load_descriptions(config.REPO / "docs/publishing")
    assert set(bodies) == {
        "schinese",
        "english",
        "french",
        "german",
        "japanese",
        "koreana",
        "polish",
        "brazilian",
        "russian",
        "spanish",
        "turkish",
    }
    assert "[h2]目标[/h2]" in bodies["schinese"]
    assert "[h2]Goal[/h2]" in bodies["english"]


@pytest.mark.parametrize(
    "body", ["", "\ufeffbad", "bad\x00", "bad\r\n", "[b]unclosed", "汉" * 2667]
)
def test_description_errors_fail_before_any_publication(tmp_path, body):
    from pdx import publishing

    directory = tmp_path / "publishing"
    shutil.copytree(config.REPO / "docs/publishing", directory)
    (directory / "创意工坊描述.md").write_bytes(body.encode("utf-8"))
    with pytest.raises(ValueError):
        publishing.load_descriptions(directory)


class Workshop:
    def __init__(self, *, reject=False, fail_language=None):
        self.bodies = {"english": "old English", "schinese": "old Chinese"}
        self.reject = reject
        self.fail_language = fail_language
        self.uploaded = []
        self.described = []

    def inspect(self, languages):
        if self.reject:
            raise ValueError("当前账号不是所有者")
        return {
            "item_id": 3826910830,
            "owner_matches": True,
            "descriptions": {language: self.bodies.get(language, "") for language in languages},
        }

    def upload(self, content, changenote):
        self.uploaded.append((content / "script.txt").read_bytes())
        return {"result": 1, "submitted": True, "content_verified": "steam_callback"}

    def describe(self, language, text):
        if language == self.fail_language:
            raise ValueError("模拟 Steam 网络失败")
        self.bodies[language] = text
        self.described.append(language)
        return {"result": 1, "submitted": True, "readback_verified": True}


def fixture_archive(tmp_path, monkeypatch):
    from pdx import publishing

    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(".metadata/metadata.json", '{"id":"situated-ai","version":"3.2.0"}')
        zipped.writestr("script.txt", b"\xef\xbb\xbffixed\n")
        zipped.writestr("thumbnail.png", b"thumbnail")
        zipped.writestr("DISTRIBUTION-MANIFEST.json", "{}")
    # 原版生成校验很重且已由 distribution 集成测试覆盖；这里只替换该外部边界。
    monkeypatch.setattr(publishing.distribution, "validate_package", lambda _path: {"schema": 2})
    monkeypatch.setattr(publishing.deployment, "assert_game_stopped", lambda: None)
    monkeypatch.setattr(publishing.config, "USERDIR", tmp_path / "userdir")
    return publishing, archive


def test_preview_leaves_game_and_workshop_untouched(tmp_path, monkeypatch):
    publishing, archive = fixture_archive(tmp_path, monkeypatch)
    remote = Workshop()
    userdir = tmp_path / "game-user"
    report = publishing.publish(
        archive=archive, userdir=userdir, run_dir=tmp_path / "run", workshop=remote
    )
    assert report["status"] == "preview"
    assert not userdir.exists()
    assert remote.uploaded == []
    assert remote.described == []
    assert report["plan"][0]["name"] == "local"
    assert report["plan"][1]["name"] == "workshop"
    assert len([item for item in report["plan"] if item["action"] == "update_description"]) == 11


def test_remote_precheck_precedes_local_install(tmp_path, monkeypatch):
    publishing, archive = fixture_archive(tmp_path, monkeypatch)
    userdir = tmp_path / "game-user"
    with pytest.raises(ValueError, match="所有者"):
        publishing.publish(
            archive=archive,
            execute=True,
            userdir=userdir,
            run_dir=tmp_path / "run",
            workshop=Workshop(reject=True),
        )
    assert not userdir.exists()
    receipt = json.loads((tmp_path / "run/receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    assert receipt["operations"] == []


def test_same_fixed_package_is_used_for_local_and_workshop(tmp_path, monkeypatch):
    publishing, archive = fixture_archive(tmp_path, monkeypatch)
    remote = Workshop()
    userdir = tmp_path / "game-user"
    report = publishing.publish(
        archive=archive, execute=True, userdir=userdir, run_dir=tmp_path / "run", workshop=remote
    )
    assert report["status"] == "succeeded"
    assert remote.uploaded == [b"\xef\xbb\xbffixed\n"]
    assert (userdir / "mod/Situated AI/script.txt").read_bytes() == b"\xef\xbb\xbffixed\n"
    assert len(remote.described) == 11
    assert all(item["status"] == "succeeded" for item in report["operations"])
    assert archive.read_bytes() == (tmp_path / "run/package.zip").read_bytes()


def test_failed_language_is_not_reported_as_all_complete_and_retry_skips_matches(
    tmp_path, monkeypatch
):
    publishing, _ = fixture_archive(tmp_path, monkeypatch)
    remote = Workshop(fail_language="french")
    with pytest.raises(ValueError, match="网络失败"):
        publishing.publish(
            target="descriptions", execute=True, run_dir=tmp_path / "first", workshop=remote
        )
    receipt = json.loads((tmp_path / "first/receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    assert any(item["status"] == "succeeded" for item in receipt["operations"])
    assert receipt["operations"][-1]["status"] == "failed"
    done = remote.described.copy()
    remote.fail_language = None
    result = publishing.publish(
        target="descriptions", execute=True, run_dir=tmp_path / "retry", workshop=remote
    )
    assert result["status"] == "succeeded"
    assert len(remote.described) == 11
    assert all(remote.described.count(language) == 1 for language in done)


def test_invalid_zip_prevents_any_remote_writes(tmp_path, monkeypatch):
    publishing, archive = fixture_archive(tmp_path, monkeypatch)

    def invalid(path):
        raise ValueError("正式包校验失败")

    monkeypatch.setattr(publishing.distribution, "validate_package", invalid)
    remote = Workshop()
    with pytest.raises(ValueError, match="校验失败"):
        publishing.publish(archive=archive, execute=True, run_dir=tmp_path / "run", workshop=remote)
    assert remote.uploaded == []
    assert remote.described == []


def test_run_directory_cannot_overwrite_prior_evidence(tmp_path, monkeypatch):
    publishing, archive = fixture_archive(tmp_path, monkeypatch)
    run = tmp_path / "run"
    run.mkdir()
    (run / "receipt.json").write_text("original", encoding="utf-8")
    with pytest.raises(ValueError, match="运行目录"):
        publishing.publish(archive=archive, run_dir=run, workshop=Workshop())
    assert (run / "receipt.json").read_text(encoding="utf-8") == "original"


def test_publishing_lock_blocks_remote_writes(tmp_path, monkeypatch):
    publishing, archive = fixture_archive(tmp_path, monkeypatch)
    remote = Workshop()
    userdir = tmp_path / "user"
    userdir.mkdir()
    (userdir / ".situated-ai-publish.lock").write_text("another publisher", encoding="utf-8")
    with pytest.raises(ValueError, match="锁"):
        publishing.publish(
            archive=archive,
            execute=True,
            userdir=userdir,
            run_dir=tmp_path / "run",
            workshop=remote,
        )
    assert remote.uploaded == []
    assert remote.described == []


@pytest.mark.parametrize(
    "replacement",
    [
        'steam = "deutsch"',
        'file = "../escape.md"',
        'file = "C:escape.md"',
    ],
)
def test_bad_language_or_body_path_is_rejected(tmp_path, replacement):
    from pdx import publishing

    directory = tmp_path / "materials"
    shutil.copytree(config.REPO / "docs/publishing", directory)
    path = directory / "workshop.toml"
    text = path.read_text(encoding="utf-8")
    old = 'steam = "german"' if replacement.startswith("steam") else 'file = "创意工坊描述-de.md"'
    path.write_text(text.replace(old, replacement), encoding="utf-8")
    with pytest.raises(ValueError):
        publishing.load_descriptions(directory)


def test_receipt_preserves_uncertain_remote_submission(tmp_path, monkeypatch):
    from pdx.steam_workshop import WorkshopError

    publishing, archive = fixture_archive(tmp_path, monkeypatch)
    remote = Workshop()

    def uncertain(*args):
        raise WorkshopError("Steam 提交后超时", submitted=True, uncertain=True)

    monkeypatch.setattr(remote, "upload", uncertain)
    with pytest.raises(ValueError, match="超时"):
        publishing.publish(
            archive=archive,
            target="workshop",
            execute=True,
            run_dir=tmp_path / "run",
            workshop=remote,
        )
    receipt = json.loads((tmp_path / "run/receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    assert receipt["operations"][-1]["status"] == "uncertain"
    assert receipt["operations"][-1]["submitted"] is True


def test_run_directory_cannot_be_inside_the_deployed_mod(tmp_path, monkeypatch):
    publishing, archive = fixture_archive(tmp_path, monkeypatch)
    userdir = tmp_path / "user"
    run = userdir / "mod/Situated AI/run"
    with pytest.raises(ValueError, match="运行目录"):
        publishing.publish(archive=archive, userdir=userdir, run_dir=run, workshop=Workshop())
    assert not userdir.exists()


def test_content_changes_during_upload_prevent_success(tmp_path, monkeypatch):
    publishing, archive = fixture_archive(tmp_path, monkeypatch)
    remote = Workshop()

    def mutate(content, changenote):
        (content / "script.txt").write_bytes(b"changed during upload")
        return {"result": 1, "submitted": True}

    monkeypatch.setattr(remote, "upload", mutate)
    with pytest.raises(ValueError, match="内容树"):
        publishing.publish(
            archive=archive,
            target="workshop",
            execute=True,
            run_dir=tmp_path / "run",
            workshop=remote,
        )
    receipt = json.loads((tmp_path / "run/receipt.json").read_text(encoding="utf-8"))
    assert receipt["operations"][-1]["status"] == "uncertain"


@pytest.mark.parametrize("error_type", [PermissionError, ValueError])
def test_unreadable_content_after_upload_keeps_remote_state_uncertain(
    tmp_path, monkeypatch, error_type
):
    publishing, archive = fixture_archive(tmp_path, monkeypatch)
    remote = Workshop()
    submitted = False
    original = publishing.deployment.tree_hashes

    def upload(content, changenote):
        nonlocal submitted
        submitted = True
        return {"result": 1, "submitted": True}

    def hashes(content):
        if submitted:
            raise error_type("上传后内容无法读取")
        return original(content)

    monkeypatch.setattr(remote, "upload", upload)
    monkeypatch.setattr(publishing.deployment, "tree_hashes", hashes)
    with pytest.raises(publishing.PublicationError, match="内容"):
        publishing.publish(
            archive=archive,
            target="workshop",
            execute=True,
            run_dir=tmp_path / "run",
            workshop=remote,
        )
    receipt = json.loads((tmp_path / "run/receipt.json").read_text(encoding="utf-8"))
    assert submitted
    assert receipt["operations"][-1]["status"] == "uncertain"
    assert receipt["operations"][-1]["submitted"] is True


def test_local_target_does_not_load_or_connect_steam(tmp_path, monkeypatch):
    publishing, archive = fixture_archive(tmp_path, monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("本地目标不应连接 Steam")

    monkeypatch.setattr(publishing, "SteamWorkshop", forbidden)
    report = publishing.publish(
        archive=archive, target="local", execute=True, run_dir=tmp_path / "run"
    )
    assert report["status"] == "succeeded"
    assert [row["name"] for row in report["operations"]] == ["local"]


def test_failure_exposes_its_exact_receipt_path(tmp_path, monkeypatch):
    publishing, archive = fixture_archive(tmp_path, monkeypatch)
    with pytest.raises(publishing.PublicationError, match="所有者") as caught:
        publishing.publish(
            archive=archive, run_dir=tmp_path / "run", workshop=Workshop(reject=True)
        )
    assert caught.value.receipt == (tmp_path / "run/receipt.json").resolve()
