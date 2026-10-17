"""新增单模块 F1 烟测入口的边界契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdx import game_run
from tools.probe import f1_module_smoke

pytestmark = pytest.mark.unit


def _patch_common(monkeypatch, tmp_path):
    def package_inputs(_variant):
        return "policy", "extensions", {"README.md": "module"}

    monkeypatch.setattr(f1_module_smoke.distribution, "package_inputs", package_inputs)

    def attach(files, _policy, _extensions):
        return files

    monkeypatch.setattr(f1_module_smoke.explanation_probe, "attach", attach)

    def write(root: Path, files=None):
        root.mkdir(parents=True, exist_ok=True)
        (root / ".metadata").mkdir()
        (root / ".metadata/metadata.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(f1_module_smoke.decisions, "write", write)

    def fake_write_json(path, value):
        Path(path).write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(game_run, "write_json", fake_write_json)


def test_模块烟测拒绝未知模块(tmp_path):
    with pytest.raises(ValueError, match="不支持的单模块"):
        f1_module_smoke.run("full", output=tmp_path)


def test_模块烟测默认只挂载单一生产候选(tmp_path, monkeypatch):
    _patch_common(monkeypatch, tmp_path)
    captured: dict[str, object] = {}

    def fake_run(sources, **kwargs):
        captured["sources"] = sources
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        return {"ok": True, "evidence": str(evidence)}

    monkeypatch.setattr(game_run, "run", fake_run)
    report = f1_module_smoke.run("economy", output=tmp_path / "out")

    assert report["ok"] is True
    sources = captured["sources"]
    assert isinstance(sources, dict)
    assert set(sources) == {"sitai_economy_f1"}
    context = json.loads((tmp_path / "evidence/f1_context.json").read_text(encoding="utf-8"))
    assert context["candidate"] == "economy"
    assert context["candidate_kind"] == "production_candidate"
    assert context["behavior_quality"] == "not_evaluated"


def test_模块烟测诊断选项同时记录两项基线(tmp_path, monkeypatch):
    _patch_common(monkeypatch, tmp_path)

    def write_resource(root, _game):
        root.mkdir(parents=True)
        return {"purpose": "diagnostic"}

    monkeypatch.setattr(f1_module_smoke.resource_baseline, "write", write_resource)
    monkeypatch.setattr(
        f1_module_smoke.decision_probe,
        "build_localization_baseline",
        lambda _game: {"baseline.json": "{}\n"},
    )

    captured: dict[str, object] = {}

    def fake_run(sources, **kwargs):
        captured["sources"] = sources
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        return {"ok": False, "evidence": str(evidence), "failure": "diagnostic"}

    monkeypatch.setattr(game_run, "run", fake_run)
    report = f1_module_smoke.run(
        "subjects",
        output=tmp_path / "out",
        resource=True,
        localization=True,
    )

    assert report["ok"] is False
    sources = captured["sources"]
    assert isinstance(sources, dict)
    assert set(sources) == {
        "sitai_subjects_f1",
        "zz_sitai_resource_baseline",
        "zz_sitai_vanilla_localization_baseline",
    }
