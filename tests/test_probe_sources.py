"""各实机入口的源隔离：不加载旧产物，失败也清理本局临时源。"""

import json
from argparse import Namespace
from importlib import import_module

import pytest

from pdx import config, decision_probe, game_run

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "module_name", ["m1_diplomacy", "m2_formal_smoke", "decision_lifecycle", "decision_unload"]
)
@pytest.mark.parametrize("fails", [False, True])
def test_所有实机入口按局生成源并保留原始残留供恢复(tmp_path, monkeypatch, module_name, fails):
    module = import_module(f"tools.probe.{module_name}")
    monkeypatch.setattr(config, "OUT", tmp_path)
    if hasattr(module, "RESULT_DIR"):
        monkeypatch.setattr(module, "RESULT_DIR", tmp_path)
    old = tmp_path / "candidate/common/on_actions/obsolete.txt"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"original stale source")
    generated = []

    def fake_run(sources, **_kwargs):
        generated.extend(sources.values())
        for path in sources.values():
            assert ".sources-" in str(path)
            assert not (path / "common/on_actions/obsolete.txt").exists()
            assert (path / ".metadata/metadata.json").is_file()
        if module_name == "decision_unload":
            assert set(sources) == {"zz_sitai_fiscal_observer", "zz_probe_decision_lifecycle"}
        if fails:
            raise RuntimeError("test failure")
        return {"ok": True}

    monkeypatch.setattr(game_run, "run", fake_run)
    if module_name in {"m1_diplomacy", "m2_formal_smoke"}:

        def invoke():
            return module.run(1)
    else:
        arguments = Namespace(
            months=1,
            controlled=False,
            keep_save=False,
            load_save=None,
            save=tmp_path / "save.v3",
            localization_baseline=False,
        )
        monkeypatch.setattr(
            module.argparse.ArgumentParser, "parse_args", lambda *_a, **_k: arguments
        )
        invoke = module.main
    if fails:
        with pytest.raises(RuntimeError, match="test failure"):
            invoke()
    else:
        invoke()
    assert generated
    assert not any(path.exists() for path in generated)
    assert old.read_bytes() == b"original stale source"


@pytest.mark.parametrize("injection", ["stress", "no-stress", "none"])
def test_财政行为各臂保留检查点的两只读身份(tmp_path, monkeypatch, injection):
    from tools.probe import decision_behavior

    game = tmp_path / "game"
    for relative, text in (
        ("common/laws/laws.txt", "law_autocracy = {}\n"),
        ("common/ai_strategies/strategies.txt", "ai_strategy_test = { type = political }\n"),
    ):
        path = game / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(config, "GAME", game)
    observed: list[str] = []

    def fake_run(sources, **kwargs):
        assert {"zz_probe_decision_lifecycle", "zz_sitai_reform_observer"} <= sources.keys()
        assert "zz_sitai_fiscal_observer" in sources
        observed.extend(
            json.loads((path / ".metadata/metadata.json").read_text(encoding="utf-8"))["id"]
            for path in sources.values()
        )
        lifecycle = json.loads(
            (sources["zz_probe_decision_lifecycle"] / ".metadata/metadata.json").read_text(
                encoding="utf-8"
            )
        )
        assert lifecycle["name"] == "SITAI fiscal lifecycle instrument"
        if injection in {"stress", "no-stress"}:
            expected = decision_probe.build(inject=injection == "stress")
            assert {
                name: (sources["zz_probe_decision_lifecycle"] / name).read_bytes()
                for name in expected
            } == {name: text.encode("utf-8") for name, text in expected.items()}
        else:
            for path in sources["zz_probe_decision_lifecycle"].rglob("*.txt"):
                text = path.read_text(encoding="utf-8")
                assert "add_treasury" not in text
                assert "sitai_update_fiscal" not in text
                assert "remove_variable" not in text
        assert kwargs["months"] == 1
        return {"ok": True}

    monkeypatch.setattr(game_run, "run", fake_run)
    arguments = Namespace(
        arm="control",
        fiscal_injection=injection,
        initiator="GBR",
        target="TUR",
        observers=("RUS", "PRU"),
        months=1,
        save=tmp_path / "save.v3",
        localization_baseline=False,
    )
    assert decision_behavior.execute(arguments, tmp_path / "out", tmp_path / "sources") == 0
    assert {"sitai.probe.decisions", "sitai.probe.reform"} <= set(observed)
