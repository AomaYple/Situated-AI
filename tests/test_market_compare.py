"""真实依赖配对的零效应、反方向与源归因守门。"""

import hashlib
from dataclasses import replace

import pytest

from pdx import decisions, game_run
from tools.probe.market_compare import compare


def test_重复实验只使用本局生成物并清理临时源(tmp_path, monkeypatch):
    import argparse

    from pdx import config, game_run
    from tools.probe import decision_behavior

    output = tmp_path / "output"
    old = output / "fiscal/common/on_actions/obsolete.txt"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old-injection")
    game = tmp_path / "game"
    law = game / "common/laws/test.txt"
    law.parent.mkdir(parents=True)
    law.write_text("law_autocracy = {}\n", encoding="utf-8")
    strategy = game / "common/ai_strategies/test.txt"
    strategy.parent.mkdir(parents=True, exist_ok=True)
    strategy.write_text("ai_strategy_test = { type = political }\n", encoding="utf-8")
    monkeypatch.setattr(config, "GAME", game)
    monkeypatch.setattr(config, "OUT", output)
    args = argparse.Namespace(
        arm="market-control",
        initiator="GBR",
        target="FRA",
        observers=("BEL", "NET"),
        fiscal_injection="none",
        months=3,
        save=tmp_path / "save.v3",
    )
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", lambda *_: args)
    generated = []

    def fake_run(sources, **_kwargs):
        generated.extend(sources.values())
        fiscal = sources["zz_sitai_fiscal_observer"]
        assert not (fiscal / "common/on_actions/obsolete.txt").exists()
        assert "zz_sitai_reform_observer" in sources
        assert not any(
            "sitai_probe_month" in p.read_text(encoding="utf-8") for p in fiscal.rglob("*.txt")
        )
        return {"ok": True}

    monkeypatch.setattr(game_run, "run", fake_run)
    assert decision_behavior.main() == 0
    assert generated
    assert not any(p.exists() for p in generated)
    assert old.read_bytes() == b"old-injection"


pytestmark = pytest.mark.unit


def report(*, enabled=False, init=-10, target=-20):
    files = decisions.build(
        replace(decisions.load(), neutrality=0, aggression=0),
        extensions=replace(
            decisions.load_extensions(), reform_enabled=False, market_enabled=enabled
        ),
    )
    rows: list[dict[str, str]] = []
    for tag in ("RUS", "PRU"):
        rows.extend(
            {"tag": tag, "date": "day", "kind": kind, "value": value}
            for kind, value in (
                ("UNDECIDED", "yes"),
                ("CAN_INIT", "yes"),
                ("DEPENDENCY_INIT", "1.0"),
                ("DEPENDENCY_TARGET", "0.0"),
                ("INIT_SCORE", str(init)),
                ("TARGET_SCORE", str(target)),
            )
        )
    return {
        "ok": True,
        "mount_allowlist": ["c:/game", "c:/mods/probe"],
        "log_findings": {
            "errors": dict.fromkeys(game_run.ERROR_MARKERS, 0),
            "mod_errors": [],
            "missing_mounts": [],
        },
        "loaded_save": {"sha256": "f" * 64},
        "game_version": "test",
        "source_hashes": {
            "sitai_decision_candidate": {
                k: hashlib.sha256(v.encode()).hexdigest() for k, v in files.items()
            },
            "instrument": {"same": "same"},
        },
        "analysis": {
            "opportunity": {"rows": rows, "countries": {"RUS": {"joined": 0}, "PRU": {"joined": 0}}}
        },
    }


def test_有符号的有限评分效果不能升级为质量证明():
    result = compare(report(), report(enabled=True, init=-5, target=-25))
    assert result["two_country_score_effect_observed"]
    assert not result["quality_improvement_proven"]


def test_实机整数差分符合强依赖模型且不声称精确浮点():
    left, right = report(), report(enabled=True, init=4, target=-48)
    for arm in (left, right):
        for row in arm["analysis"]["opportunity"]["rows"]:
            if row["kind"] == "DEPENDENCY_INIT":
                row["value"] = "2.946"
            elif row["kind"] == "DEPENDENCY_TARGET":
                row["value"] = "0.051"
    result = compare(left, right)
    assert result["two_country_score_effect_observed"]
    assert result["measurement_model"]["score_quantum"] == 1
    assert not result["quality_improvement_proven"]


@pytest.mark.parametrize(("dependency", "delta"), [("0.2", 1), ("0.5", 2)])
def test_弱效应或读数量化噪声不能充当有效效果(dependency, delta):
    left, right = report(), report(enabled=True, init=-10 + delta, target=-20 - delta)
    for arm in (left, right):
        for row in arm["analysis"]["opportunity"]["rows"]:
            if row["kind"] == "DEPENDENCY_INIT":
                row["value"] = dependency
    result = compare(left, right)
    assert not result["two_country_score_effect_observed"]
    if dependency == "0.2":
        assert result["countries"]["RUS"]["below_measurement_resolution"]


def test_旧门禁或报告内引擎错误不能被ok字段覆盖():
    right = report(enabled=True)
    del right["log_findings"]["errors"]["Script system error!"]
    with pytest.raises(ValueError, match="门禁"):
        compare(report(), right)
    right = report(enabled=True)
    right["log_findings"]["errors"]["Script system error!"] = 1
    with pytest.raises(ValueError, match="门禁"):
        compare(report(), right)


@pytest.mark.parametrize(("init", "target"), [(-10, -20), (-11, -19), (100, -200)])
def test_无效应反方向或过大差分均不能通过(init, target):
    result = compare(report(), report(enabled=True, init=init, target=target))
    assert not result["two_country_score_effect_observed"]


def test_依赖输入发生变化不当单字段对照():
    right = report(enabled=True, init=-5, target=-25)
    for row in right["analysis"]["opportunity"]["rows"]:
        if row["kind"] == "DEPENDENCY_INIT":
            row["value"] = "2"
    result = compare(report(), right)
    assert not result["two_country_score_effect_observed"]


def test_篡改默认策略或仪器都拒绝():
    right = report(enabled=True)
    right["source_hashes"]["sitai_decision_candidate"][
        "common/ai_strategies/00_default_strategy.txt"
    ] = "bad"
    with pytest.raises(ValueError, match="源差异"):
        compare(report(), right)
    right = report(enabled=True)
    right["source_hashes"]["instrument"]["same"] = "changed"
    with pytest.raises(ValueError, match="仪器"):
        compare(report(), right)
