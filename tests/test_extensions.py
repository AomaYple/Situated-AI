"""扩展默认停用、底本保真、市场对称性与只读政治事件的契约。"""

import re
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pdx import decisions, extension_probe
from pdx.parser import parse_text

pytestmark = pytest.mark.unit


def test_未验收扩展默认停用():
    policy = decisions.load_extensions()
    assert not policy.reform_enabled
    assert not policy.market_enabled
    assert len(decisions.build()) == 5


def test_启用扩展只追加声明字段且原版逐字保留():
    policy = replace(decisions.load_extensions(), reform_enabled=True, market_enabled=True)
    files = decisions.build(extensions=policy)
    patched = files["common/ai_strategies/00_default_strategy.txt"]
    restored = re.sub(
        r"\t\t# SITAI BEGIN [^\n]+\n.*?\t\t# SITAI END [^\n]+\n", "", patched, flags=re.DOTALL
    )
    assert restored == decisions.BASELINE.read_text(encoding="utf-8")
    assert patched.count("# SITAI BEGIN") == 3
    for name, text in files.items():
        assert "\r" not in text
        assert not text.startswith("\ufeff")
        if name.endswith(".txt"):
            assert not parse_text(text, name).errors
    support = patched.split("# SITAI BEGIN diplomatic_play_support")[1].split("# SITAI END")[0]
    assert "desc = SITAI_MARKET_DEPENDENCE_SUPPORT_REASON" in support
    assert "ROOT.economic_dependence(scope:country)" in support
    assert "subtract" in support


@given(
    st.floats(min_value=0, max_value=5, allow_nan=False),
    st.floats(min_value=0, max_value=5, allow_nan=False),
)
def test_交换依赖双方分数符号相反且对称有限(a, b):
    left = decisions.market_delta(a, b, multiplier=5)
    assert left == -decisions.market_delta(b, a, multiplier=5)
    assert -25 <= left <= 25
    assert decisions.market_delta(a, a, multiplier=5) == 0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 6])
def test_市场未知值与越界不能当零(value):
    with pytest.raises(ValueError):
        decisions.market_delta(value, 0, multiplier=5)


@pytest.mark.parametrize(
    "mutation",
    [
        "enabled = false|enabled = 1",
        "legitimacy = 75|legitimacy = 101",
        "fragile_legitimacy = 25|fragile_legitimacy = 80",
        "bonus = 1.0|bonus = nan",
        "penalty = -0.5|penalty = -1.0",
        "multiplier = 5.0|multiplier = 11",
        "schema_version = 1|schema_version = true",
    ],
)
def test_拒绝不可靠扩展参数(tmp_path, mutation):
    before, after = mutation.split("|")
    path = tmp_path / "extensions.toml"
    path.write_text(
        decisions.EXTENSIONS.read_text(encoding="utf-8").replace(before, after), encoding="utf-8"
    )
    with pytest.raises(ValueError):
        decisions.load_extensions(path)


def test_政治仪器只读且四类事件和全量输入法律都可生成():
    files = extension_probe.build(["law_autocracy", "law_census_suffrage"])
    for name, text in files.items():
        if name.endswith(".txt"):
            assert not parse_text(text, name).errors
        for forbidden in (
            "set_law",
            "start_enactment",
            "add_modifier",
            "add_treasury",
            "set_strategy",
        ):
            assert forbidden not in text
    hooks = files["common/on_actions/zz_sitai_reform_observer.txt"]
    for kind in ("started", "pass", "fail", "ended"):
        assert f"on_law_enactment_{kind}" in hooks
    assert "enacting_any_law" in hooks
    assert "law_census_suffrage" in hooks
    assert "any_preferred_law" in hooks
    assert "law_is_available = yes" in hooks
    assert "has_law = prev.type" in hooks
    assert "law_estimated_enactment_chance > 0" in hooks


def test_显式国家法律阻挡要求只读且另记现行法律():
    files = extension_probe.build(
        ["law_autocracy"],
        tags=("RUS",),
        legality_laws=("law_autocracy", "law_census_voting"),
    )
    hooks = files["common/on_actions/zz_sitai_reform_observer.txt"]
    assert "COUNTRY_NAME;[THIS.GetCountry.GetNameNoFormatting]" in hooks
    assert "GetLawType('law_autocracy').GetBlockingRequirements(THIS.GetCountry.Self)" in hooks
    assert "LEGAL_BLOCKED;law_census_voting=" in hooks
    assert "LEGAL_ENACTED;law_autocracy=yes" in hooks
    assert "start_enactment" not in hooks


def test_实机已断言的阶段概率观测在生成前拒绝():
    laws = ["law_autocracy", "law_local_police"]
    with pytest.raises(ValueError, match="Interface 访问断言"):
        extension_probe.build(laws, tags=("RUS",), enactment_details=True)
    files = extension_probe.build(laws, tags=("RUS",))
    hooks = files["common/on_actions/zz_sitai_reform_observer.txt"]
    assert "GetKey" not in hooks
    assert "GetCheckpointSuccessChance" not in hooks
    assert "GetCheckpointAdvanceChance" not in hooks
    assert "start_enactment" not in hooks


def test_已停用阶段概率选项在读取原版或部署前拒绝(monkeypatch, tmp_path, capsys):
    import sys

    from pdx import game_run
    from tools.probe import decision_stability

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "decision_stability.py",
            "--arm",
            "vanilla",
            "--save",
            str(tmp_path / "missing.v3"),
            "--enactment-details",
        ],
    )
    monkeypatch.setattr(decision_stability, "parse_file", lambda _path: pytest.fail("提前拒绝失败"))
    monkeypatch.setattr(game_run, "run", lambda *_args, **_kwargs: pytest.fail("不得启动游戏"))
    with pytest.raises(SystemExit) as result:
        decision_stability.main()
    assert result.value.code == 2
    assert "Interface 访问断言" in capsys.readouterr().err


def test_进行中法律概率坏值不能静默接受(tmp_path):
    (tmp_path / "debug.log").write_text(
        "\n".join(
            (
                "SITAI REFORM;RUS;COUNTRY_NAME;俄罗斯;sample-1",
                "SITAI REFORM;RUS;ENACTING_LAW;law_local_police;sample-1",
                "SITAI REFORM;RUS;CHECKPOINT_SUCCESS;nan;sample-1",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="立法概率"):
        extension_probe.analyze(tmp_path)


def test_法律阻挡要求需要同组现行状态且区分正反读数(tmp_path):
    (tmp_path / "debug.log").write_text(
        "\n".join(
            (
                "SITAI REFORM;RUS;COUNTRY_NAME;Russian Empire;sample-1",
                "SITAI REFORM;RUS;LEGAL_BLOCKED;law_autocracy=yes;sample-1",
                "SITAI REFORM;RUS;LEGAL_ENACTED;law_autocracy=no;sample-1",
                "SITAI REFORM;RUS;LEGAL_BLOCKED;law_census_voting=no;sample-1",
                "SITAI REFORM;RUS;LEGAL_ENACTED;law_census_voting=no;sample-1",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    report = extension_probe.analyze(
        tmp_path, expected_tags=("RUS",), expected_laws=("law_autocracy", "law_census_voting")
    )
    assert report["legality_interface_validated"]
    assert report["countries"]["RUS"]["country_names"] == ["Russian Empire"]
    assert report["countries"]["RUS"]["legality"]["law_autocracy"] == {
        "blocked_yes": 1,
        "blocked_no": 0,
        "enacted_yes": 0,
        "enacted_no": 1,
    }
    assert not report["quality_improvement_proven"]


def test_法律阻挡要求归一化游戏的零一格式(tmp_path):
    (tmp_path / "debug.log").write_text(
        "\n".join(
            (
                "SITAI REFORM;RUS;COUNTRY_NAME;俄罗斯;sample-1",
                "SITAI REFORM;RUS;LEGAL_BLOCKED;law_autocracy=0;sample-1",
                "SITAI REFORM;RUS;LEGAL_ENACTED;law_autocracy=1;sample-1",
                "SITAI REFORM;RUS;LEGAL_BLOCKED;law_universal_suffrage=1;sample-1",
                "SITAI REFORM;RUS;LEGAL_ENACTED;law_universal_suffrage=0;sample-1",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    report = extension_probe.analyze(
        tmp_path, expected_tags=("RUS",), expected_laws=("law_autocracy", "law_universal_suffrage")
    )
    assert report["legality_interface_validated"]
    assert report["countries"]["RUS"]["legality"]["law_universal_suffrage"]["blocked_yes"] == 1


def test_法律阻挡要求坏行不能静默降级(tmp_path):
    (tmp_path / "debug.log").write_text(
        "SITAI REFORM;RUS;LEGAL_BLOCKED;law_autocracy=[unresolved];sample-1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="法律资格"):
        extension_probe.analyze(tmp_path)


@pytest.mark.parametrize(
    "fault",
    [
        "none",
        "expected_missing",
        "country_missing",
        "law_missing",
        "cross_sample",
        "duplicate",
        "name_missing",
        "unknown_identity",
        "monthly_batch_missing",
    ],
)
def test_法律资格按预注册国家样本法律逐格验收(tmp_path, fault):
    lines = [
        "SITAI REFORM;RUS;COUNTRY_NAME;Russian Empire;sample-1",
        "SITAI REFORM;RUS;LEGAL_BLOCKED;law_autocracy=yes;sample-1",
        "SITAI REFORM;RUS;LEGAL_ENACTED;law_autocracy=no;sample-1",
        "SITAI REFORM;RUS;LEGAL_BLOCKED;law_census_voting=no;sample-1",
        "SITAI REFORM;RUS;LEGAL_ENACTED;law_census_voting=no;sample-1",
    ]
    tags: tuple[str, ...] = ("RUS",)
    laws: tuple[str, ...] = ("law_autocracy", "law_census_voting")
    if fault == "expected_missing":
        laws = ()
    elif fault == "country_missing":
        tags = ("RUS", "FRA")
    elif fault == "law_missing":
        laws = (*laws, "law_universal_suffrage")
    elif fault == "cross_sample":
        lines[2] = lines[2].replace("sample-1", "sample-2")
    elif fault == "duplicate":
        lines.append(lines[1])
    elif fault == "name_missing":
        lines[0] = lines[0].replace("Russian Empire", "[unresolved]")
    elif fault == "unknown_identity":
        lines[0] = lines[0].replace("Russian Empire", "Unverified Name")
    elif fault == "monthly_batch_missing":
        lines.append("SITAI REFORM;RUS;ENACTING;no;sample-2")
    (tmp_path / "debug.log").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    result = extension_probe.analyze(tmp_path, expected_tags=tags, expected_laws=laws)
    assert result["legality_interface_validated"] is (fault in {"none", "unknown_identity"})
    assert not result["legality_validation"]["country_identity_verified"]
    assert not result["quality_improvement_proven"]


def test_法律阻挡观察键拒绝注入():
    with pytest.raises(ValueError):
        extension_probe.build(["law_autocracy"], legality_laws=["law_bad } = yes"])


def test_政府偏好可用法律读数仍不冒充完整AI机会(tmp_path):
    path = tmp_path / "debug.log"
    text = (
        "SITAI REFORM;RUS;GOV_PREFERRED_AVAILABLE;yes;day\n"
        "SITAI REFORM;RUS;GOV_PREFERRED_ADVANCE_POSITIVE;no;day\n"
    )
    path.write_text(text, encoding="utf-8")
    report = extension_probe.analyze(tmp_path)
    assert report["countries"]["RUS"]["government_preferred_available_observations"] == 1
    assert report["countries"]["RUS"]["government_preferred_advance_positive_observations"] == 0
    assert not report["quality_improvement_proven"]
    path.write_text(text.replace(";yes;", ";INVALID;"), encoding="utf-8")
    with pytest.raises(ValueError, match="布尔"):
        extension_probe.analyze(tmp_path)


def test_政治事件结局分开不虚构可立法机会(tmp_path):
    path = tmp_path / "debug.log"
    path.write_text(
        "SITAI REFORM;RUS;LEGITIMACY;75;day\nSITAI REFORM;RUS;ENACTING;no;day\nSITAI REFORM;RUS;START;event;day\nSITAI REFORM;RUS;FAIL;event;day\nSITAI REFORM;RUS;END;event;day\n",
        encoding="utf-8",
    )
    report = extension_probe.analyze(tmp_path)
    assert report["countries"]["RUS"]["events"] == {"START": 1, "PASS": 0, "FAIL": 1, "END": 1}
    assert not report["quality_improvement_proven"]


@pytest.mark.parametrize("value", ["NaN", "[bad.expression]"])
def test_政治日志拒绝未解析或非有限数值(tmp_path, value):
    (tmp_path / "debug.log").write_text(
        f"SITAI REFORM;RUS;LEGITIMACY;{value};day\n", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        extension_probe.analyze(tmp_path)


def test_无政治日志明确失败(tmp_path):
    with pytest.raises(ValueError, match="缺少"):
        extension_probe.analyze(tmp_path)


def test_政治门槛观测区分部分机会与最终资格(tmp_path):
    (tmp_path / "debug.log").write_text(
        "SITAI REFORM;RUS;GOV_PREFERRED_ADVANCE_GE_10;yes;sample-1\n"
        "SITAI REFORM;RUS;GOV_PREFERRED_ADVANCE_GE_20;no;sample-1\n"
        "SITAI REFORM;RUS;GOV_PREFERRED_ADVANCE_GE_50;no;sample-1\n"
        "SITAI REFORM;RUS;POLITICAL_STRATEGY;ai_strategy_reactionary_agenda;sample-1\n",
        encoding="utf-8",
    )
    result = extension_probe.analyze(tmp_path)
    country = result["countries"]["RUS"]
    assert country["government_preferred_threshold_observations"] == {
        "10": 1,
        "15": 0,
        "20": 0,
        "50": 0,
    }
    assert country["political_strategy_distribution"] == {"ai_strategy_reactionary_agenda": 1}
    assert not result["quality_improvement_proven"]


@pytest.mark.parametrize(
    "row",
    [
        "GOV_PREFERRED_ADVANCE_GE_20;invalid;sample-1",
        "POLITICAL_STRATEGY;[unresolved];sample-1",
        "ENACTING;yes;sample-error",
    ],
)
def test_政治新门槛及策略错误读数不能静默丢弃(tmp_path, row):
    (tmp_path / "debug.log").write_text(
        f"SITAI REFORM;RUS;{row}\nSITAI REFORM;RUS;LEGITIMACY;75;sample-1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        extension_probe.analyze(tmp_path)


def test_从原版政治类型生成观测键而不混入其他槽(tmp_path):
    directory = tmp_path / "common/ai_strategies"
    directory.mkdir(parents=True)
    (directory / "strategies.txt").write_text(
        "ai_strategy_alpha = { type = political }\nai_strategy_beta = { type = diplomatic }\n",
        encoding="utf-8",
    )
    keys = extension_probe.political_keys(tmp_path)
    assert keys == ["ai_strategy_alpha"]
    files = extension_probe.build(["law_autocracy"], strategies=keys)
    assert not parse_text(files["common/on_actions/zz_sitai_reform_observer.txt"]).errors
    (directory / "duplicate.txt").write_text(
        "ai_strategy_alpha = { type = political }\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="重复"):
        extension_probe.political_keys(tmp_path)


@pytest.mark.parametrize("strategies", [["ai_strategy_a }"], ["ai_strategy_a", "ai_strategy_a"]])
def test_政治策略键拒绝注入和重复(strategies):
    with pytest.raises(ValueError):
        extension_probe.build(["law_autocracy"], strategies=strategies)


def test_全局政治正控明确隔离且不强制立法(tmp_path, monkeypatch):
    import sys

    from pdx import config, game_run
    from tools.probe import decision_stability

    game = tmp_path / "game"
    for directory, text in (
        ("ai_strategies", "ai_strategy_alpha = { type = political }\n"),
        ("laws", "law_autocracy = {}\n"),
    ):
        root = game / "common" / directory
        root.mkdir(parents=True)
        (root / "fixture.txt").write_text(text, encoding="utf-8", newline="\n")
    monkeypatch.setattr(config, "GAME", game)
    monkeypatch.setattr(config, "OUT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "decision_stability.py",
            "--arm",
            "reform-global-positive-control",
            "--months",
            "6",
            "--save",
            str(tmp_path / "checkpoint.v3"),
            "--experiment-plan",
            "isolated-positive-control",
            "--language",
            "l_english",
        ],
    )
    inspected = []

    def run(sources, **options):
        experiment = options["experiment"]
        assert experiment.plan_id == "isolated-positive-control"
        assert experiment.purpose == "instrument"
        assert experiment.max_months == 6
        assert options["load_save"] == tmp_path / "checkpoint.v3"
        assert options["language"] == "l_english"
        assert "zz_probe_decision_lifecycle" in sources
        candidate = sources["sitai_decision_candidate"]
        strategy = (candidate / "common/ai_strategies/00_default_strategy.txt").read_text(
            encoding="utf-8"
        )
        addition = strategy.split("# SITAI BEGIN change_law_chance")[1].split("# SITAI END")[0]
        assert "add = sitai_reform_default_delta" in addition
        assert "ROOT" not in addition
        value = (candidate / "common/script_values/sitai_reform_values.txt").read_text(
            encoding="utf-8"
        )
        assert "value = 99" in value
        for path in candidate.rglob("*.txt"):
            text = path.read_text(encoding="utf-8")
            assert not parse_text(text, str(path)).errors
            assert "start_enactment" not in text
            assert "activate_law" not in text
        inspected.append(candidate)
        return {"ok": True}

    monkeypatch.setattr(game_run, "run", run)
    assert decision_stability.main() == 0
    assert inspected
    assert not inspected[0].exists()
    assert not decisions.load_extensions().reform_enabled


def test_显式性能噪声包生成与资格源码契约一致(tmp_path, monkeypatch):
    import sys

    from pdx import decision_probe, game_run
    from tools.probe import decision_stability

    monkeypatch.setattr(decision_stability.config, "OUT", tmp_path / "out")
    monkeypatch.setattr(
        decision_stability, "parse_file", lambda *_a: pytest.fail("性能包不读政治法律")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "decision_stability.py",
            "--arm",
            "vanilla",
            "--purpose",
            "M4-noise",
            "--save",
            str(tmp_path / "input.v3"),
            "--observation-package",
            "vanilla-performance",
            "--language",
            "l_english",
            "--months",
            "24",
            "--max-months",
            "24",
        ],
    )
    seen = []

    def run(sources, **options):
        assert set(sources) == {"zz_sitai_fiscal_observer"}
        expected = decision_probe.build_observer(
            tags=("RUS", "PRU"), policy_state=False, native_fiscal_inputs=True
        )
        root = sources["zz_sitai_fiscal_observer"]
        assert {
            path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
            for path in root.rglob("*")
            if path.is_file()
        } == expected
        assert options["qualification_context"]["observation"]["package"] == "vanilla-performance"
        assert options["experiment"].purpose == "M4-noise"
        assert options["months"] == options["experiment"].max_months == 24
        seen.append(root)
        return {"ok": True}

    monkeypatch.setattr(game_run, "run", run)
    assert decision_stability.main() == 0
    assert seen
    assert not seen[0].exists()


@pytest.mark.parametrize(
    "extra",
    [
        {"purpose": "instrument"},
        {"natural_diplomacy": True},
        {"localization_baseline": True},
        {"legality_laws": "law_autocracy"},
        {"qualification_registration": "later.json"},
    ],
)
def test_性能包拒绝未登记混用仪器(extra):
    import argparse

    from tools.probe import decision_stability

    values = {"purpose": "M4-noise", "observation_package": "vanilla-performance", **extra}
    with pytest.raises(ValueError, match="性能观测包"):
        decision_stability._check_performance_package(argparse.Namespace(**values))


def test_正式性能目的不能默默删除原观测包():
    import argparse

    from tools.probe import decision_stability

    with pytest.raises(ValueError, match="显式登记"):
        decision_stability._check_performance_package(argparse.Namespace(purpose="M4"))


@pytest.mark.parametrize("purpose", ["instrument", "safety"])
@pytest.mark.parametrize("enabled", [False, True])
def test_资源诊断CLI默认关闭并透传审计与既有观察(tmp_path, monkeypatch, purpose, enabled):
    import sys

    from tools.probe import decision_stability

    game = tmp_path / "game"
    laws = game / "common/laws"
    laws.mkdir(parents=True)
    (laws / "fixture.txt").write_text("law_autocracy = {}\n", encoding="utf-8", newline="\n")
    plays = game / "common/diplomatic_plays"
    plays.mkdir()
    (plays / "fixture.txt").write_text("dp_humiliation = {}\n", encoding="utf-8", newline="\n")
    monkeypatch.setattr(decision_stability.config, "GAME", game)
    monkeypatch.setattr(decision_stability.config, "OUT", tmp_path / "out")
    monkeypatch.setattr(extension_probe, "political_keys", lambda _game: [])
    monkeypatch.setattr(decision_stability.decision_probe, "analyze", lambda *_a, **_kw: {})
    monkeypatch.setattr(extension_probe, "analyze", lambda *_a, **_kw: {})
    monkeypatch.setattr(decision_stability.natural_probe, "analyze", lambda *_a, **_kw: {})
    manifest = {"schema": "sitai-resource-baseline-v1", "purpose": "diagnostic-resource-only"}
    seen = []

    def write(root, source):
        assert source == game
        assert root.name == "resource-baseline"
        root.mkdir()
        seen.append(root)
        return manifest

    monkeypatch.setattr(decision_stability.resource_baseline, "write", write)
    argv = [
        "decision_stability.py",
        "--arm",
        "vanilla",
        "--purpose",
        purpose,
        "--save",
        str(tmp_path / "input.v3"),
        "--native-fiscal-inputs",
        "--natural-diplomacy",
    ]
    if enabled:
        argv.append("--resource-baseline")
    monkeypatch.setattr(sys, "argv", argv)

    def run(sources, **options):
        assert ("zz_sitai_resource_baseline" in sources) is enabled
        assert "zz_sitai_natural_diplomacy" in sources
        assert options["experiment"].purpose == purpose
        analysis = options["analyze"](tmp_path)
        assert analysis["experiment"]["resource_baseline"] == (manifest if enabled else None)
        assert analysis["experiment"]["native_fiscal_inputs"]
        assert not analysis["experiment"]["enactment_details"]
        assert not analysis["experiment"]["approval_igs"]
        assert not analysis["experiment"]["approval_laws"]
        return {"ok": False, "failure": "原错误门禁继续拒绝"}

    monkeypatch.setattr(decision_stability.game_run, "run", run)
    assert decision_stability.main() == 1
    assert len(seen) == int(enabled)
    assert all(not root.exists() for root in seen)


@pytest.mark.parametrize(
    ("purpose", "arm"),
    [
        ("M4", "vanilla"),
        ("M4-noise", "vanilla"),
        ("instrument", "fiscal"),
        ("safety", "reform"),
        ("instrument", "combined"),
        ("instrument", "reform-positive-control"),
        ("instrument", "reform-global-positive-control"),
    ],
)
def test_资源诊断CLI与execute均在生成部署前拒绝(tmp_path, monkeypatch, purpose, arm):
    import argparse
    import sys

    from tools.probe import decision_stability

    def forbidden(*_a, **_kw):
        pytest.fail("资源诊断非法目的或候选必须在生成与部署前拒绝")

    monkeypatch.setattr(decision_stability, "parse_file", forbidden)
    monkeypatch.setattr(decision_stability.decisions, "write", forbidden)
    monkeypatch.setattr(decision_stability.resource_baseline, "write", forbidden)
    monkeypatch.setattr(decision_stability.game_run, "run", forbidden)
    monkeypatch.setattr(decision_stability.config, "OUT", tmp_path / "out")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "decision_stability.py",
            "--arm",
            arm,
            "--purpose",
            purpose,
            "--save",
            str(tmp_path / "input.v3"),
            "--resource-baseline",
        ],
    )
    with pytest.raises(SystemExit) as error:
        decision_stability.main()
    assert error.value.code == 2
    with pytest.raises(ValueError, match="资源诊断仅允许"):
        decision_stability.execute(
            argparse.Namespace(purpose=purpose, arm=arm, resource_baseline=True),
            [],
            tmp_path / "output",
            tmp_path / "sources",
        )
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("analyzer", ["fiscal", "reform", "war"])
def test_资源诊断实际分析缺读数仍失败且冻结源保留完整来源(tmp_path, monkeypatch, analyzer):
    import hashlib
    import json
    import shutil
    import struct
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    from pdx import game_run
    from tools.probe import decision_stability

    game = tmp_path / "install/game"
    source_name = "gfx/interface/icons/generic_icons/repairing.dds"
    target_name = "gfx/interface/icons/alert_icons/repairing.dds"
    gui_name = "gui/texticons.gui"
    source = game / source_name
    source.parent.mkdir(parents=True)
    header = [0] * 31
    header[0:4] = [124, 0x1007, 4, 4]
    header[18:21] = [32, 4, int.from_bytes(b"DXT5", "little")]
    header[26] = 0x1000
    source.write_bytes(b"DDS " + struct.pack("<31I", *header) + bytes(range(16)))
    gui = game / gui_name
    gui.parent.mkdir()
    gui.write_text(f'icon = {{ texture = "{target_name}" }}\n', encoding="utf-8", newline="\n")
    laws = game / "common/laws"
    laws.mkdir(parents=True)
    (laws / "fixture.txt").write_text("law_autocracy = {}\n", encoding="utf-8", newline="\n")
    user = tmp_path / "user"
    user.mkdir()
    original = b'{"disabledDLC": []}\r\n'
    (user / "content_load.json").write_bytes(original)
    monkeypatch.setattr(game_run.config, "GAME", game)
    monkeypatch.setattr(game_run.config, "USERDIR", user)
    monkeypatch.setattr(game_run.config, "OUT", tmp_path / "out")
    monkeypatch.setattr(game_run.config, "game_version", lambda _root=None: {"version": "test"})
    monkeypatch.setattr(extension_probe, "political_keys", lambda _game: [])
    if analyzer in {"reform", "war"}:
        # 只隔离前置财政分析，以到达真实政治分析器的缺读数异常；
        # fiscal 参数用例直接运行真实财政分析器，不伪造成功观测。
        monkeypatch.setattr(decision_stability.decision_probe, "analyze", lambda *_a, **_kw: {})
    if analyzer == "war":
        monkeypatch.setattr(extension_probe, "analyze", lambda *_a, **_kw: {})
    monkeypatch.setattr(game_run, "_base_mount_allowlist", list)
    monkeypatch.setattr(game_run.ga, "assert_no_game_running", lambda: None)
    monkeypatch.setattr(game_run.ga, "_foreground_window", lambda: 0)
    monkeypatch.setattr(game_run.ga, "_process_pids", list)
    monkeypatch.setattr(game_run.ga, "kill_owned_game", lambda: None)
    monkeypatch.setattr(game_run.ga, "LAST_QUARANTINE_ERRORS", [])
    monkeypatch.setattr(game_run, "graceful_stop", lambda *_a, **_kw: {"exited": True})

    def quarantine(destination):
        destination.mkdir(parents=True)
        for log in (user / "logs").glob("*.log"):
            shutil.copy2(log, destination / log.name)
        return []

    monkeypatch.setattr(game_run.ga, "quarantine_logs", quarantine)

    def start(**_kwargs):
        logs = user / "logs"
        logs.mkdir(exist_ok=True)
        (logs / "debug.log").write_text(
            "".join(f"Mounted Data: {path}\n" for path in sorted((user / "mod").iterdir())),
            encoding="utf-8",
            newline="\n",
        )
        return SimpleNamespace(hwnd=123, rate_ok=True, advance=None, as_dict=lambda: {"test": True})

    def wait(*_args, sample, **_kwargs):
        sample()
        return {"reached": True}

    monkeypatch.setattr(game_run.ga, "run_session", start)
    monkeypatch.setattr(game_run, "wait_progress", wait)
    actual_run = game_run.run
    reports = []
    temporary_sources = []

    def run(sources, **options):
        # GUI 后端模拟；真实运行器负责源冻结、部署、完整日志核对、
        # 实际分析器异常与恢复。实验账本/存档参数已由独立契约覆盖。
        temporary_sources.append(sources["zz_sitai_resource_baseline"])
        report = actual_run(
            sources,
            months=1,
            output=options["output"],
            analyze=options["analyze"],
        )
        reports.append(report)
        return report

    monkeypatch.setattr(game_run, "run", run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "decision_stability.py",
            "--arm",
            "vanilla",
            "--purpose",
            "instrument",
            "--save",
            str(tmp_path / "input.v3"),
            "--resource-baseline",
        ]
        + (
            ["--war-calibration", "--war-dates", "1836.2.24,1836.2.25"] if analyzer == "war" else []
        ),
    )
    assert decision_stability.main() == 1
    assert len(reports) == 1
    report = reports[0]
    assert report["ok"] is False
    expected = {
        "fiscal": "缺少本局财政观测",
        "reform": "缺少本局政治读数",
        "war": "战争校准无完整样本",
    }[analyzer]
    failure = report["failure"]
    assert isinstance(failure, str)
    assert expected in failure
    assert failure.startswith("日志分析失败：")
    assert "analysis" not in report
    assert not report["cleanup_errors"]
    stages = report["stage_timings"]
    assert isinstance(stages, list)
    assert any(item["name"] == "analysis" and item["status"] == "failed" for item in stages)
    evidence = report["evidence"]
    assert isinstance(evidence, str)
    frozen = Path(evidence) / "sources/zz_sitai_resource_baseline"
    metadata = frozen / ".metadata/metadata.json"
    manifest = json.loads(metadata.read_bytes())["game_custom_data"]["resource_baseline"]
    assert manifest["schema"] == "sitai-resource-baseline-v1"
    assert manifest["purpose"] == "diagnostic-resource-only"
    assert manifest["source"] == {
        "path": source_name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    assert manifest["gui"] == {
        "path": gui_name,
        "sha256": hashlib.sha256(gui.read_bytes()).hexdigest(),
    }
    assert manifest["output"] == {
        "path": target_name,
        "sha256": hashlib.sha256((frozen / target_name).read_bytes()).hexdigest(),
    }
    assert manifest["copied_bytes"] == source.stat().st_size
    assert "不证明模拟无扰动" in manifest["boundary"]
    source_hashes = report["source_hashes"]
    assert isinstance(source_hashes, dict)
    assert (
        source_hashes["zz_sitai_resource_baseline"][".metadata/metadata.json"]
        == hashlib.sha256(metadata.read_bytes()).hexdigest()
    )
    assert {
        path.relative_to(frozen).as_posix() for path in frozen.rglob("*") if path.is_file()
    } == {
        target_name,
        ".metadata/metadata.json",
    }
    assert all(not root.exists() for root in temporary_sources)
    assert (user / "content_load.json").read_bytes() == original
    assert not (user / "mod/zz_sitai_resource_baseline").exists()
    if analyzer == "war":
        war_frozen = Path(evidence) / "sources/zz_sitai_war_calibration"
        war_metadata = war_frozen / ".metadata/metadata.json"
        war_config = json.loads(war_metadata.read_bytes())["game_custom_data"]["war_calibration"]
        assert war_config == decision_stability.war_probe.configuration(("1836.2.24", "1836.2.25"))
        assert (
            source_hashes["zz_sitai_war_calibration"][".metadata/metadata.json"]
            == hashlib.sha256(war_metadata.read_bytes()).hexdigest()
        )
        provenance = report["provenance"]
        assert isinstance(provenance, dict)
        assert str(Path(decision_stability.war_probe.__file__).resolve()) in provenance["files"]


@pytest.mark.parametrize("purpose", ["instrument", "safety"])
@pytest.mark.parametrize("enabled", [False, True])
def test_战争校准默认关闭既有观察字节保持及execute透传(tmp_path, monkeypatch, purpose, enabled):
    import sys

    from tools.probe import decision_stability

    laws = tmp_path / "game/common/laws"
    laws.mkdir(parents=True)
    (laws / "fixture.txt").write_text("law_autocracy = {}\n", encoding="utf-8", newline="\n")
    monkeypatch.setattr(decision_stability.config, "GAME", tmp_path / "game")
    monkeypatch.setattr(decision_stability.config, "OUT", tmp_path / "out")
    monkeypatch.setattr(extension_probe, "political_keys", lambda _game: [])
    monkeypatch.setattr(decision_stability.decision_probe, "analyze", lambda *_a, **_kw: {})
    monkeypatch.setattr(extension_probe, "analyze", lambda *_a, **_kw: {})
    dates = ("1836.2.24", "1836.2.25")
    config = decision_stability.war_probe.configuration(dates)
    monkeypatch.setattr(
        decision_stability.war_probe, "analyze", lambda _dir, **_kw: {"configuration": config}
    )
    argv = [
        "decision_stability.py",
        "--arm",
        "vanilla",
        "--purpose",
        purpose,
        "--save",
        str(tmp_path / "input.v3"),
    ]
    if enabled:
        argv += ["--war-calibration", "--war-dates", ",".join(dates)]
    monkeypatch.setattr(sys, "argv", argv)

    def run(sources, **options):
        assert ("zz_sitai_war_calibration" in sources) is enabled
        for name, expected in {
            "zz_sitai_fiscal_observer": decision_stability.decision_probe.build_observer(
                policy_state=False
            ),
            "zz_probe_decision_lifecycle": decision_stability.decision_probe.build_observer(
                lifecycle=True, policy_state=False
            ),
            "zz_sitai_reform_observer": extension_probe.build(["law_autocracy"]),
        }.items():
            actual = {
                path.relative_to(sources[name]).as_posix(): path.read_bytes()
                for path in sources[name].rglob("*")
                if path.is_file()
            }
            assert actual == {key: value.encode("utf-8") for key, value in expected.items()}
        assert options["experiment"].purpose == purpose
        analysis = options["analyze"](tmp_path)
        assert analysis["experiment"]["war_calibration"] == (config if enabled else None)
        assert ("war_calibration" in analysis) is enabled
        return {"ok": False, "failure": "严格门禁仍拒绝"}

    monkeypatch.setattr(decision_stability.game_run, "run", run)
    assert decision_stability.main() == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"purpose": "M4"},
        {"purpose": "M4-noise"},
        {"purpose": "M3-A"},
        {"arm": "fiscal"},
        {"arm": "reform"},
        {"arm": "combined"},
        {"arm": "reform-positive-control"},
        {"arm": "reform-global-positive-control"},
        {"war_dates": ""},
        {"war_dates": "1836.2.30"},
        {"fiscal_tags": "MEX"},
        {"fiscal_tags": "MEX,MEX"},
        {"legality_tags": ""},
        {"war_calibration": False},
        {"observation_package": "vanilla-performance"},
    ],
)
def test_战争校准CLI和execute早期拒绝不合法参数(tmp_path, monkeypatch, extra):
    import argparse
    import sys

    from tools.probe import decision_stability

    def forbidden(*_args, **_kwargs):
        pytest.fail("战争校准参数错误应早于原版读取、生成或部署")

    monkeypatch.setattr(decision_stability, "parse_file", forbidden)
    monkeypatch.setattr(decision_stability.decisions, "write", forbidden)
    monkeypatch.setattr(decision_stability.game_run, "run", forbidden)
    monkeypatch.setattr(decision_stability.config, "OUT", tmp_path / "out")
    values = {
        "purpose": "instrument",
        "arm": "vanilla",
        "war_calibration": True,
        "war_dates": "1836.2.24",
        **extra,
    }
    argv = ["decision_stability.py", "--save", str(tmp_path / "input.v3")]
    for key, value in values.items():
        option = "--" + key.replace("_", "-")
        if value is True:
            argv.append(option)
        elif value is not False:
            argv += [option, value]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as error:
        decision_stability.main()
    assert error.value.code == 2
    with pytest.raises(ValueError):
        decision_stability.execute(
            argparse.Namespace(**values), [], tmp_path / "output", tmp_path / "sources"
        )
    assert not (tmp_path / "out").exists()
