"""F1 full 烟测入口的源隔离和证据分类契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdx import config, game_run
from tools.probe import f1_full_smoke

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("variant", ["full", "integrated"])
def test_生产候选默认不挂载诊断基线(tmp_path, monkeypatch, variant):
    monkeypatch.setattr(config, "OUT", tmp_path)
    monkeypatch.setattr(f1_full_smoke, "DEFAULT_OUTPUT", tmp_path / "f1")

    def package_inputs(_variant):
        assert _variant == variant
        return "policy", "extensions", {"README.md": "full"}

    monkeypatch.setattr(f1_full_smoke.distribution, "package_inputs", package_inputs)

    def attach(files, _policy, _extensions):
        return {**files, "attached.txt": "probe"}

    monkeypatch.setattr(
        f1_full_smoke.explanation_probe,
        "attach",
        attach,
    )
    written: list[Path] = []

    def write(root: Path, files: dict[str, str] | None = None):
        root.mkdir(parents=True, exist_ok=True)
        (root / ".metadata").mkdir()
        (root / ".metadata/metadata.json").write_text("{}\n", encoding="utf-8")
        written.append(root)

    monkeypatch.setattr(f1_full_smoke.decisions, "write", write)

    captured: dict[str, object] = {}

    def fake_run(sources, **kwargs):
        captured["sources"] = sources
        captured["kwargs"] = kwargs
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        return {
            "ok": True,
            "evidence": str(evidence),
            "session": {"automation_phase": "complete"},
            "log_findings": {"mod_errors": [], "errors": {}, "unclassified_errors": []},
            "cleanup_errors": [],
        }

    monkeypatch.setattr(game_run, "run", fake_run)
    monkeypatch.setattr(
        game_run,
        "write_json",
        lambda path, value: Path(path).write_text(
            json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8"
        ),
    )

    report = f1_full_smoke.run(output=tmp_path / "f1", variant=variant)

    assert report["ok"] is True
    source_names = captured["sources"]
    assert isinstance(source_names, dict)
    assert set(source_names) == {f1_full_smoke.distribution.INSTALL_DIRECTORY_NAME}
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["language"] is None
    context = json.loads((tmp_path / "evidence/f1_context.json").read_text(encoding="utf-8"))
    assert context["candidate_kind"] == "production_candidate"
    assert context["production_package"] is True
    assert context["behavior_quality"] == "not_evaluated"
    assert context["loaded_observer"] is False
    assert context["delivery_contract"]["install_directory"] == "Situated AI"
    assert context["delivery_contract"]["variant"] == variant
    assert context["candidate"] == variant
    assert written
    assert written[0].name == f1_full_smoke.distribution.INSTALL_DIRECTORY_NAME
    assert kwargs["analyze"] is None
    assert not context["research_observation"]["enabled"]
    assert not context["law_observation"]["enabled"]


def test_默认标准候选不附加解释探针且显式开关才附加(tmp_path, monkeypatch):
    monkeypatch.setattr(
        f1_full_smoke.distribution,
        "package_inputs",
        lambda _variant: ("policy", "extensions", {"README.md": "full"}),
    )
    attached: list[bool] = []

    def attach_probe(files, _policy, _extensions):
        attached.append(True)
        return files

    monkeypatch.setattr(f1_full_smoke.explanation_probe, "attach", attach_probe)

    def write_decisions(root, files=None):
        del files
        Path(root).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        f1_full_smoke.decisions,
        "write",
        write_decisions,
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    def run_game(sources, **kwargs):
        del sources, kwargs
        return {"ok": True, "evidence": str(evidence)}

    monkeypatch.setattr(game_run, "run", run_game)

    def write_json(*_args):
        return None

    monkeypatch.setattr(game_run, "write_json", write_json)
    f1_full_smoke.run(output=tmp_path / "plain")
    assert attached == []
    f1_full_smoke.run(output=tmp_path / "instrumented", with_explanation_probe=True)
    assert attached == [True]


def test_诊断候选显式记录两种原版基线(tmp_path, monkeypatch):
    def package_inputs(_variant):
        return "policy", "extensions", {"README.md": "full"}

    monkeypatch.setattr(f1_full_smoke.distribution, "package_inputs", package_inputs)

    def attach(files, _policy, _extensions):
        return files

    monkeypatch.setattr(
        f1_full_smoke.explanation_probe,
        "attach",
        attach,
    )

    def write(root: Path, files=None):
        root.mkdir(parents=True, exist_ok=True)
        (root / ".metadata").mkdir()
        (root / ".metadata/metadata.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(f1_full_smoke.decisions, "write", write)

    def write_resource(root, _game):
        root.mkdir(parents=True)
        return {"purpose": "diagnostic"}

    monkeypatch.setattr(f1_full_smoke.resource_baseline, "write", write_resource)

    def build_localization_baseline(_game):
        return {"baseline.json": "{}\n"}

    monkeypatch.setattr(
        f1_full_smoke.decision_probe,
        "build_localization_baseline",
        build_localization_baseline,
    )
    captured: dict[str, object] = {}

    def fake_run(sources, **kwargs):
        captured["sources"] = sources
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        return {"ok": False, "evidence": str(evidence), "failure": "diagnostic"}

    monkeypatch.setattr(game_run, "run", fake_run)
    monkeypatch.setattr(
        game_run,
        "write_json",
        lambda path, value: Path(path).write_text(
            json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8"
        ),
    )

    report = f1_full_smoke.run(
        output=tmp_path / "f1",
        resource=True,
        localization=True,
    )

    assert report["ok"] is False
    source_names = captured["sources"]
    assert isinstance(source_names, dict)
    assert set(source_names) == {
        f1_full_smoke.distribution.INSTALL_DIRECTORY_NAME,
        "zz_sitai_resource_baseline",
        "zz_sitai_vanilla_localization_baseline",
    }
    context = json.loads((tmp_path / "evidence/f1_context.json").read_text(encoding="utf-8"))
    assert context["candidate_kind"] == "diagnostic_candidate"
    assert context["production_package"] is False
    assert context["diagnostic_baselines"] == {"resource": True, "localization": True}


def test_显式语言传给运行器并写入证据上下文(tmp_path, monkeypatch):
    monkeypatch.setattr(
        f1_full_smoke.distribution,
        "package_inputs",
        lambda _variant: ("policy", "extensions", {}),
    )
    monkeypatch.setattr(
        f1_full_smoke.explanation_probe,
        "attach",
        lambda files, _policy, _extensions: files,
    )

    def write(root: Path, files=None):
        root.mkdir(parents=True, exist_ok=True)
        (root / ".metadata").mkdir()
        (root / ".metadata/metadata.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(f1_full_smoke.decisions, "write", write)
    captured: dict[str, object] = {}

    def fake_run(sources, **kwargs):
        captured["sources"] = sources
        captured["kwargs"] = kwargs
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        return {"ok": True, "evidence": str(evidence)}

    monkeypatch.setattr(game_run, "run", fake_run)
    monkeypatch.setattr(
        game_run,
        "write_json",
        lambda path, value: Path(path).write_text(
            json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8"
        ),
    )

    report = f1_full_smoke.run(
        output=tmp_path / "f1",
        language="l_english",
        load_save=tmp_path / "observer.v3",
    )

    assert report["ok"] is True
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["language"] == "l_english"
    assert kwargs["load_save"] == tmp_path / "observer.v3"
    context = json.loads((tmp_path / "evidence/f1_context.json").read_text(encoding="utf-8"))
    assert context["language"] == "l_english"
    assert context["loaded_observer"] is True


def test_显式研究观测只附加临时副本并解析完整日志(tmp_path, monkeypatch):
    game = tmp_path / "game"
    technology = game / "common/technology/technologies/production.txt"
    technology.parent.mkdir(parents=True)
    technology.write_text("a = {}\nb = {}\n", encoding="utf-8")
    monkeypatch.setattr(config, "GAME", game)
    original = {"README.md": "standard", ".metadata/metadata.json": "{}\n"}
    monkeypatch.setattr(
        f1_full_smoke.distribution, "package_inputs", lambda _v: (None, None, original)
    )
    observed = []

    def fake_run(sources, *, analyze, **_kwargs):
        candidate = sources["Situated AI"]
        assert (candidate / "README.md").read_text(encoding="utf-8") == "standard"
        assert (candidate / "common/on_actions/zz_sitai_research_observation.txt").is_file()
        assert (candidate / "common/scripted_effects/zz_sitai_research_observation.txt").is_file()
        evidence = tmp_path / "evidence"
        logs = evidence / "logs"
        logs.mkdir(parents=True)
        (logs / "debug.log").write_text(
            "SITAI RESEARCH;RUS;BEGIN;MONTHLY\n"
            "SITAI RESEARCH;RUS;TECH;a;1;0;1\n"
            "SITAI RESEARCH;RUS;TECH;b;0;1;0\n"
            "SITAI RESEARCH;RUS;END;MONTHLY\n",
            encoding="utf-8",
        )
        result = analyze(logs)
        observed.append(result)
        assert result["complete"]
        return {"ok": True, "evidence": str(evidence), "analysis": result}

    monkeypatch.setattr(game_run, "run", fake_run)
    report = f1_full_smoke.run(
        output=tmp_path / "run", variant="integrated", research_tags=("RUS",)
    )
    context = report["f1_context"]
    assert context["candidate_kind"] == "instrumented_candidate"
    assert not context["production_package"]
    assert context["research_observation"]["technology_keys"] == ["a", "b"]
    assert context["research_observation"]["state_reader"] == "is_researching_technology"
    assert context["research_observation"]["runtime_getter"] == "not_verified"
    assert set(context["research_observation"]["technology_sources"]) == {
        "common/technology/technologies/production.txt"
    }
    assert observed
    assert original == {"README.md": "standard", ".metadata/metadata.json": "{}\n"}


def test_研究观测文件碰撞则在部署前拒绝(tmp_path, monkeypatch):
    monkeypatch.setattr(
        f1_full_smoke.distribution,
        "package_inputs",
        lambda _v: (
            None,
            None,
            {
                "common/on_actions/zz_sitai_research_observation.txt": "original",
            },
        ),
    )
    monkeypatch.setattr(f1_full_smoke.research_observation, "technology_keys", lambda _g: ("a",))
    with pytest.raises(ValueError, match="不能覆盖"):
        f1_full_smoke._write_sources(
            tmp_path,
            resource=False,
            localization=False,
            with_explanation_probe=False,
            research_tags=("RUS",),
        )


def test_观测读取与生成间科技原件变化必须在启动前拒绝(tmp_path, monkeypatch):
    game = tmp_path / "game"
    technology = game / "common/technology/technologies/production.txt"
    technology.parent.mkdir(parents=True)
    technology.write_text("a = {}\n", encoding="utf-8")
    monkeypatch.setattr(config, "GAME", game)

    def changing_inputs(_variant):
        technology.write_text("b = {}\n", encoding="utf-8")
        return None, None, {"README.md": "standard"}

    monkeypatch.setattr(f1_full_smoke.distribution, "package_inputs", changing_inputs)
    monkeypatch.setattr(game_run, "run", lambda *_a, **_k: pytest.fail("输入变化不得派发"))
    with pytest.raises(ValueError, match="科技原件"):
        f1_full_smoke.run(output=tmp_path / "run", research_tags=("RUS",))


def test_法律观测临时部署并记录来源且流式解析(tmp_path, monkeypatch):
    game = tmp_path / "game"
    path = game / "common/laws/laws.txt"
    path.parent.mkdir(parents=True)
    path.write_text("a = {}\nb = {}\n", encoding="utf-8")
    monkeypatch.setattr(config, "GAME", game)
    original = {"README.md": "standard"}
    monkeypatch.setattr(
        f1_full_smoke.distribution, "package_inputs", lambda _v: (None, None, original)
    )

    def fake_run(sources, *, analyze, **_kwargs):
        assert (sources["Situated AI"] / "common/on_actions/zz_sitai_law_observation.txt").is_file()
        evidence = tmp_path / "evidence"
        logs = evidence / "logs"
        logs.mkdir(parents=True)
        (logs / "debug.log").write_text(
            "SITAI LAW;RUS;BEGIN;MONTHLY\n"
            "SITAI LAW;RUS;LAW;a;1;0;1;0\n"
            "SITAI LAW;RUS;LAW;b;1;1;0;0\n"
            "SITAI LAW;RUS;END;MONTHLY\n",
            encoding="utf-8",
        )
        result = analyze(logs)
        assert result["laws"]["complete"]
        assert result["laws"]["frames"][0]["laws"]["a"]["active"]
        return {"ok": True, "evidence": str(evidence), "analysis": result}

    monkeypatch.setattr(game_run, "run", fake_run)
    report = f1_full_smoke.run(output=tmp_path / "run", law_tags=("RUS",), variant="integrated")
    context = report["f1_context"]
    assert context["candidate_kind"] == "instrumented_candidate"
    assert not context["production_package"]
    assert context["law_observation"]["law_keys"] == ["a", "b"]
    assert set(context["law_observation"]["law_sources"]) == {"common/laws/laws.txt"}
    assert original == {"README.md": "standard"}


@pytest.mark.parametrize("change", ["content", "new-file"])
@pytest.mark.parametrize("late", [False, True])
def test_法律来源漂移在部署前拒绝(tmp_path, monkeypatch, change, late):
    game = tmp_path / "game"
    path = game / "common/laws/laws.txt"
    path.parent.mkdir(parents=True)
    path.write_text("a = {}\n", encoding="utf-8")
    monkeypatch.setattr(config, "GAME", game)

    def change_source():
        target = path if change == "content" else path.with_name("extra.txt")
        target.write_text(
            "a = { group = x }\n" if change == "content" else "b = {}\n", encoding="utf-8"
        )

    def inputs(_variant):
        if not late:
            change_source()
        return None, None, {}

    def dispatch(_sources, **kwargs):
        assert late
        change_source()
        kwargs["verify_inputs"]()
        pytest.fail("漂移不得继续部署或启动")

    monkeypatch.setattr(f1_full_smoke.distribution, "package_inputs", inputs)
    monkeypatch.setattr(game_run, "run", dispatch)
    with pytest.raises(ValueError, match="法律原件"):
        f1_full_smoke.run(output=tmp_path / "run", law_tags=("RUS",))


def test_法律观测碰撞拒绝(tmp_path, monkeypatch):
    monkeypatch.setattr(
        f1_full_smoke.distribution,
        "package_inputs",
        lambda _v: (None, None, {"common/on_actions/zz_sitai_law_observation.txt": "original"}),
    )
    with pytest.raises(ValueError, match="不能覆盖"):
        f1_full_smoke._write_sources(
            tmp_path,
            resource=False,
            localization=False,
            with_explanation_probe=False,
            law_tags=("RUS",),
            law_keys=("a",),
        )


def test_研究目标必须显式国家与语言(tmp_path):
    with pytest.raises(ValueError, match=r"国家.*语言"):
        f1_full_smoke.run(output=tmp_path, research_targets=True)


@pytest.mark.parametrize("drift", [False, True])
def test_研究目标标签冻结与生成间漂移拒绝(tmp_path, monkeypatch, drift):
    game = tmp_path / "game"
    technology = game / "common/technology/technologies/production.txt"
    technology.parent.mkdir(parents=True)
    technology.write_text("a = {}\n", encoding="utf-8")
    localization = game / "localization/simp_chinese/inventions.yml"
    localization.parent.mkdir(parents=True)
    localization.write_text('l_simp_chinese:\n a:0 "甲科技"\n', encoding="utf-8")
    monkeypatch.setattr(config, "GAME", game)

    def package_inputs(_variant):
        if drift:
            localization.write_text('l_simp_chinese:\n a:0 "漂移"\n', encoding="utf-8")
        return None, None, {}

    monkeypatch.setattr(f1_full_smoke.distribution, "package_inputs", package_inputs)

    def fake_run(sources, *, analyze, **_kwargs):
        assert not drift
        action = sources["Situated AI"] / "common/on_actions/zz_sitai_research_observation.txt"
        assert "SCOPE.sTechnology('technology')" in action.read_text(encoding="utf-8")
        evidence = tmp_path / "evidence"
        logs = evidence / "logs"
        logs.mkdir(parents=True)
        (logs / "debug.log").write_text(
            "SITAI RESEARCH;RUS;BEGIN;START\nSITAI RESEARCH;RUS;TARGET;甲科技\n"
            "SITAI RESEARCH;RUS;TECH;a;1;0;1\nSITAI RESEARCH;RUS;END;START\n",
            encoding="utf-8",
        )
        result = analyze(logs)
        assert result["frames"][0]["target"] == "a"
        return {"ok": True, "evidence": str(evidence), "analysis": result}

    monkeypatch.setattr(game_run, "run", fake_run)
    if drift:
        with pytest.raises(ValueError, match="名称原件"):
            f1_full_smoke.run(
                output=tmp_path / "run",
                research_tags=("RUS",),
                research_targets=True,
                language="l_simp_chinese",
            )
    else:
        report = f1_full_smoke.run(
            output=tmp_path / "run",
            research_tags=("RUS",),
            research_targets=True,
            language="l_simp_chinese",
        )
        observed = report["f1_context"]["research_observation"]
        assert observed["labels"] == {"a": "甲科技"}
        assert observed["label_origins"]["a"]["line"] == 2


@pytest.mark.parametrize("missing_country", [False, True])
def test_请求的观测帧无效必须使分析失败且保留独立报告(tmp_path, monkeypatch, missing_country):
    game = tmp_path / "game"
    path = game / "common/laws/laws.txt"
    path.parent.mkdir(parents=True)
    path.write_text("a = {}\n", encoding="utf-8")
    monkeypatch.setattr(config, "GAME", game)
    monkeypatch.setattr(f1_full_smoke.distribution, "package_inputs", lambda _v: (None, None, {}))

    def fake_run(_sources, *, analyze, **_kwargs):
        logs = tmp_path / "evidence/logs"
        logs.mkdir(parents=True)
        text = (
            "SITAI LAW;RUS;BEGIN;MONTHLY\nSITAI LAW;RUS;LAW;a;1;1;1;0\nSITAI LAW;RUS;END;MONTHLY\n"
            if missing_country
            else "SITAI LAW;broken\n"
        )
        (logs / "debug.log").write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match="观测未完成"):
            analyze(logs)
        detail = json.loads((logs.parent / "f1-observation.json").read_text(encoding="utf-8"))
        assert detail["laws"]["errors"]
        return {"ok": False, "evidence": str(logs.parent), "failure": "analysis"}

    monkeypatch.setattr(game_run, "run", fake_run)
    tags = ("RUS", "FRA") if missing_country else ("RUS",)
    assert not f1_full_smoke.run(output=tmp_path / "run", law_tags=tags)["ok"]


def test_CLI传递明确仪器开关但不隐式开启(monkeypatch, tmp_path):
    captured = []

    def run(**kwargs):
        captured.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(f1_full_smoke, "run", run)
    assert (
        f1_full_smoke.main(
            [
                "--output",
                str(tmp_path),
                "--variant",
                "integrated",
                "--law-tag",
                "RUS",
                "--law-tag",
                "FRA",
                "--research-tag",
                "FRA",
                "--research-targets",
                "--language",
                "l_simp_chinese",
            ]
        )
        == 0
    )
    assert captured[0]["law_tags"] == ("RUS", "FRA")
    assert captured[0]["research_tags"] == ("FRA",)
    assert captured[0]["research_targets"] is True
    assert f1_full_smoke.main([]) == 0
    assert captured[1]["law_tags"] == ()
    assert captured[1]["research_targets"] is False
