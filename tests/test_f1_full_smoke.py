"""F1 full 烟测入口的源隔离和证据分类契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdx import config, game_run
from tools.probe import f1_full_smoke

pytestmark = pytest.mark.unit


def test_生产候选默认不挂载诊断基线(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUT", tmp_path)
    monkeypatch.setattr(f1_full_smoke, "DEFAULT_OUTPUT", tmp_path / "f1")

    def package_inputs(_variant):
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

    report = f1_full_smoke.run(output=tmp_path / "f1")

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
    assert context["delivery_contract"]["variant"] == "full"
    assert written
    assert written[0].name == f1_full_smoke.distribution.INSTALL_DIRECTORY_NAME


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
