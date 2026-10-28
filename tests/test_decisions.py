"""通用决策的生命周期、变形与默认策略保真测试。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pdx import decisions, distribution, vanilla_index
from pdx.model import Block
from pdx.parser import parse_text

pytestmark = pytest.mark.unit


def test_生成会修复编码和同长度正文漂移(tmp_path):
    files = {"common/a.txt": "同样内容\n"}
    paths = decisions.write(tmp_path, files)
    path = paths[0]
    assert decisions.write(tmp_path, files) == paths
    for raw in (
        b"\xef\xbb\xbf" + files["common/a.txt"].encode(),
        "同样内容\n".encode(),
        "其他内容\n".encode(),
    ):
        path.write_bytes(raw)
        decisions.write(tmp_path, files)
        assert path.read_bytes() == files["common/a.txt"].encode()


@pytest.fixture
def policy():
    return decisions.load()


def test_财政开关显式开启且交付契约来自数据源(policy):
    assert policy.enabled
    assert policy.package.product_version == distribution.RELEASE_VERSION
    assert policy.package.status == "candidate"
    payload = decisions.metadata_payload(policy)
    assert payload["version"] == policy.package.product_version
    assert payload["tool_version"] == "0.3.0"
    assert payload["enabled_modules"] == ["fiscal"]
    fingerprint = payload["source_fingerprint"]
    assert isinstance(fingerprint, dict)
    assert fingerprint["baseline_sha256"] == policy.baseline_sha256


def test_财政开关关闭不生成财政脚本且保留原版策略(policy):
    disabled = replace(policy, enabled=False)
    files = decisions.build(disabled)
    assert set(files) == {
        "common/ai_strategies/00_default_strategy.txt",
        ".metadata/metadata.json",
    }
    assert files["common/ai_strategies/00_default_strategy.txt"] == decisions.BASELINE.read_text(
        encoding="utf-8"
    )
    assert decisions.triggers(disabled) == ""
    assert decisions.effects(disabled) == ""
    assert decisions.on_actions(disabled) == ""
    assert json.loads(files[".metadata/metadata.json"])["enabled_modules"] == []
    assert policy.package.save_compatibility == "new-game-only"
    assert f"days = {policy.ttl_days}" in decisions.effects(policy)


def test_旧存档缺少财政变量时活动触发器显式回退(policy):
    triggers = decisions.triggers(policy)
    active_trigger = triggers.split(f"{decisions.ACTIVE_TRIGGER} = {{", 1)[1].split("}", 1)[0]
    assert f"has_variable = {decisions.RISK_VAR}" in active_trigger


@pytest.mark.parametrize(
    ("active", "weeks", "expected"),
    [
        (False, 25, True),
        (False, 26, False),
        (True, 26, True),
        (True, 51, True),
        (True, 52, False),
    ],
)
def test_财政进入退出迟滞(policy, active, weeks, expected):
    assert (
        decisions.risk_next(
            active,
            in_default=False,
            taking_loans=True,
            credit=100,
            weeks=weeks,
            policy=policy,
        )
        == expected
    )


@pytest.mark.parametrize("weeks", [None, float("nan"), float("inf"), -1])
def test_未知财政值停止干预(policy, weeks):
    assert not decisions.risk_next(
        True,
        in_default=False,
        taking_loans=True,
        credit=100,
        weeks=weeks,
        policy=policy,
    )
    assert decisions.risk_next(
        False,
        in_default=True,
        taking_loans=False,
        credit=100,
        weeks=weeks,
        policy=policy,
    )


@given(st.floats(min_value=0, max_value=1000, allow_nan=False), st.booleans())
def test_偿债不会继续维持借款危机(weeks, active):
    assert not decisions.risk_next(
        active,
        in_default=False,
        taking_loans=False,
        credit=100,
        weeks=weeks,
        policy=decisions.load(),
    )


def test_默认策略原文只增加两个声明偏置(policy):
    original = decisions.BASELINE.read_text(encoding="utf-8")
    patched = decisions.patch_default(original, policy)
    restored = re.sub(
        r"\t\t# SITAI BEGIN [^\n]+\n.*?\t\t# SITAI END [^\n]+\n",
        "",
        patched,
        flags=re.DOTALL,
    )
    assert restored == original
    assert patched.count("# SITAI BEGIN") == sum(
        amount != 0 for amount in (policy.neutrality, policy.aggression)
    )
    assert not parse_text(patched).errors
    assert len(parse_text(patched).top_assignments) == 1
    assert parse_text(patched).top_keys == parse_text(original).top_keys


def test_底本任何漂移均拒绝生成(policy):
    original = decisions.BASELINE.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="哈希"):
        decisions.patch_default(original + "\n", policy)


def test_零偏置对照逐字保留底本并且不调用国家条件(policy):
    original = decisions.BASELINE.read_text(encoding="utf-8")
    assert (
        decisions.patch_default(original, replace(policy, neutrality=0, aggression=0)) == original
    )


def test_财政字段仅在有效root存在时调用国家触发器(policy):
    patched = decisions.patch_default(decisions.BASELINE.read_text(encoding="utf-8"), policy)
    tree = parse_text(patched)
    strategy = tree.top_assignments[0].value
    assert isinstance(strategy, Block)
    for name, amount in (
        ("aggression", policy.aggression),
        ("diplomatic_play_neutrality", policy.neutrality),
    ):
        if amount == 0:
            continue
        field = strategy.all(name)[0].value
        assert isinstance(field, Block)
        condition = field.all("if")[-1].value
        assert isinstance(condition, Block)
        guard = condition.all("limit")[0].value
        assert isinstance(guard, Block)
        root = guard.all("ROOT")[0]
        assert root.op == "?="
        assert isinstance(root.value, Block)
        assert str(root.value.all(decisions.ACTIVE_TRIGGER)[0].value) == "yes"


def test_财政外部暴露包含尚未选边的合法参与者(policy):
    triggers = decisions.triggers(policy)
    assert "is_diplomatic_play_undecided_participant = yes" in triggers


def test_生产扩展为本体每种语言生成完整键集(policy):
    extra = replace(decisions.load_extensions(), market_enabled=True, security_enabled=True)
    files = decisions.build(policy, extensions=extra)
    expected = set(decisions.LANGUAGES)
    actual = {
        language
        for language in decisions.LANGUAGES
        if f"localization/{language}/sitai_decisions_l_{language}.yml" in files
    }
    assert actual == expected
    metadata = json.loads(files[".metadata/metadata.json"])
    assert metadata["localization"]["languages"] == sorted(expected)
    assert set(metadata["localization"]["fallback_languages"]) == expected - {
        "english",
        "simp_chinese",
    }
    assert metadata["localization"]["production_fallback_languages"] == sorted(
        expected - {"english", "simp_chinese"}
    )
    assert metadata["localization"]["explanation_fallback_languages"] == []


def test_显式空语言集合不能静默退回默认集合(policy):
    with pytest.raises(ValueError, match="至少需要一种"):
        decisions.build(policy, languages=())


@pytest.mark.parametrize(
    "body",
    [
        "ai_strategy_default = { aggression = 1 }",
        "x = {}",
        "ai_strategy_default = { aggression = {} aggression = {} }",
    ],
)
def test_即使哈希匹配也拒绝不符结构(policy, body):
    altered = replace(policy, baseline_sha256=hashlib.sha256(body.encode()).hexdigest())
    with pytest.raises(ValueError):
        decisions.patch_default(body, altered)


def test_所有生成脚本可解析且没有旧世界或换牌干预(policy):
    files = decisions.build(policy)
    for name, text in files.items():
        assert not text.startswith("\ufeff")
        assert "\r" not in text
        if name.endswith(".txt"):
            assert not parse_text(text, name).errors
    added = "\n".join(
        text
        for name, text in files.items()
        if name != "common/ai_strategies/00_default_strategy.txt"
    )
    assert "set_strategy" not in added
    assert "add_modifier" not in added
    assert "every_country" not in added
    assert f"days = {policy.ttl_days}" in added


def test_财政生命周期所有入口汇聚到唯一更新器(policy):
    """月度、违约和退出事件都必须调用同一状态更新器。"""
    actions = decisions.on_actions()
    assert actions.count("sitai_fiscal_update = { effect = { sitai_update_fiscal = yes } }") == 1
    assert actions.count("on_monthly_pulse_country = { on_actions = { sitai_fiscal_update } }") == 1
    assert actions.count("on_country_default = { on_actions = { sitai_fiscal_update } }") == 1
    assert (
        actions.count("on_country_no_longer_default = { on_actions = { sitai_fiscal_update } }")
        == 1
    )
    effects = decisions.effects(policy)
    assert effects.count(f"set_variable = {{ name = {decisions.RISK_VAR}") == 1
    assert effects.count(f"remove_variable = {decisions.RISK_VAR}") == 1


def test_财政生命周期写入包含迟滞和TTL边界(policy):
    """生成器必须同时保留进入线、退出线和至少一个月 TTL。"""
    triggers = decisions.triggers(policy)
    assert f"weeks_until_bankruptcy < {policy.entry_weeks}" in triggers
    assert f"weeks_until_bankruptcy < {policy.exit_weeks}" in triggers
    effects = decisions.effects(policy)
    assert f"days = {policy.ttl_days}" in effects
    assert policy.ttl_days >= 32


def test_写盘检查发现篡改和遗留产物(tmp_path):
    decisions.write(tmp_path)
    assert decisions.check(tmp_path) == []
    path = tmp_path / "common/ai_strategies/00_default_strategy.txt"
    path.write_text("bad", encoding="utf-8")
    stale = tmp_path / "common/old.txt"
    stale.write_text("old", encoding="utf-8")
    assert len(decisions.check(tmp_path)) == 2


@pytest.mark.parametrize(
    "mutation",
    [
        "entry_weeks = 26|entry_weeks = 0",
        "exit_weeks = 52|exit_weeks = 26",
        "ttl_days = 62|ttl_days = 1",
        "aggression = 0|aggression = 20",
        "diplomatic_play_neutrality = 25|diplomatic_play_neutrality = nan",
        "enabled = true|enabled = 1",
        "schema_version = 1|schema_version = 2",
    ],
)
def test_数据源拒绝危险参数(tmp_path, mutation):
    before, after = mutation.split("|")
    path = tmp_path / "bad.toml"
    path.write_text(
        decisions.SOURCE.read_text(encoding="utf-8").replace(before, after),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        decisions.load(path)


@pytest.mark.parametrize("credit", [None, 0, -1, float("nan"), float("inf")])
def test_无有效信用不能凭借款周数进入风险(policy, credit):
    assert not decisions.risk_next(
        False,
        in_default=False,
        taking_loans=True,
        credit=credit,
        weeks=1,
        policy=policy,
    )
    assert decisions.risk_next(
        False, in_default=True, taking_loans=True, credit=credit, weeks=1, policy=policy
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "schema_version = 1|schema_version = true",
        'why = "真实违约|why = 42 # "真实违约',
        'game_version = "1.14.5"|game_version = "1.15.0"',
    ],
)
def test_拒绝错误类型和未审查游戏版本(tmp_path, mutation):
    before, after = mutation.split("|")
    source = tmp_path / "bad.toml"
    source.write_text(
        decisions.SOURCE.read_text(encoding="utf-8").replace(before, after),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        decisions.load(source)


@pytest.mark.parametrize(
    "mutation",
    [
        'status = "candidate"|status = "released"',
        'save_compatibility = "new-game-only"|save_compatibility = "all"',
        'platforms = ["windows", "macos", "linux"]|platforms = ["plan9"]',
        'product_version = "1.4.0"|product_version = "not-a-version"',
    ],
)
def test_拒绝不可靠的包契约(tmp_path, mutation):
    before, after = mutation.split("|")
    source = tmp_path / "bad.toml"
    source.write_text(
        decisions.SOURCE.read_text(encoding="utf-8").replace(before, after),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        decisions.load(source)


def test_包契约缺失字段明确失败(tmp_path):
    source = tmp_path / "missing.toml"
    text, count = re.subn(
        r"^platform_notes = .*\n",
        "",
        decisions.SOURCE.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    assert count == 1
    source.write_text(text, encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="缺失"):
        decisions.load(source)


def test_新接口缺证据和本机底本漂移均拒绝(tmp_path):
    assert decisions.validate(None)
    assert decisions.validate(set())
    assert len(decisions.validate(set(), game=tmp_path)) >= 2


def test_扩展开启时新增接口必须有原版证据(monkeypatch, tmp_path):
    monkeypatch.setattr(
        decisions,
        "load_extensions",
        lambda: decisions.Extensions(reform_enabled=True, market_enabled=True),
    )
    issues = decisions.validate(set())
    assert any("legitimacy" in issue for issue in issues)
    # 脚本值接口需要专用原版快照域，由下方的合同测试覆盖。


def test_economic_dependence_requires_a_dedicated_vanilla_script_value_snapshot(tmp_path):
    sections = vanilla_index.snapshot_sections(tmp_path)
    policy = replace(decisions.load(), enabled=True)
    extensions = replace(decisions.load_extensions(), market_enabled=True)

    issues = decisions.validate(
        None,
        snapshot={"域": sections},
        policy=policy,
        extensions=extensions,
    )
    assert any("economic_dependence" in issue for issue in issues)
    assert not any("common/script_values 域" in issue for issue in issues)

    sections[vanilla_index.SECTION_SCRIPT_VALUE_ACCESSORS][
        vanilla_index.SCRIPT_VALUE_ACCESSOR_DIR
    ].append("economic_dependence")
    issues = decisions.validate(
        None,
        snapshot={"域": sections},
        policy=policy,
        extensions=extensions,
    )
    assert not any("economic_dependence" in issue for issue in issues)

    sections.pop(vanilla_index.SECTION_SCRIPT_VALUE_ACCESSORS)
    issues = decisions.validate(
        None,
        snapshot={"域": sections},
        policy=policy,
        extensions=extensions,
    )
    assert any("原版脚本值 API 快照缺少 common/script_values 域" in issue for issue in issues)


def test_快照缺失扩展接口域明确报告未覆盖(tmp_path):
    snapshot: dict[str, object] = {
        "域": {
            "vocabulary": {},
            "vanilla_keys": {rel: [] for rel in decisions.KEY_DIRS},
        }
    }
    issues = decisions.validate(set(), snapshot=snapshot)
    assert any("词汇快照缺少" in issue for issue in issues)


@pytest.mark.integration
def test_生产ZIP不携带历史档案(tmp_path):
    import zipfile

    from pdx import distribution

    with zipfile.ZipFile(distribution.package(tmp_path / "mod.zip")) as archive:
        _, _, files = distribution.package_inputs()
        assert set(archive.namelist()) == set(files) | {
            "README.md",
            "DISTRIBUTION-MANIFEST.json",
        }
        assert not any("legacy" in name or "ru_defeat" in name for name in archive.namelist())


@pytest.mark.integration
def test_生产ZIP清单携带实际包契约和源指纹(tmp_path):
    import zipfile

    from pdx import distribution

    with zipfile.ZipFile(distribution.package(tmp_path / "mod.zip")) as archive:
        manifest = json.loads(archive.read("DISTRIBUTION-MANIFEST.json"))
        metadata = json.loads(archive.read(".metadata/metadata.json"))
    _, _, files = distribution.package_inputs(include_engineering_metadata=True)
    source_metadata = json.loads(files[".metadata/metadata.json"])
    assert manifest["schema"] == 2
    assert manifest["contract"]["product_version"] == metadata["version"]
    assert manifest["contract"]["enabled_modules"] == source_metadata["enabled_modules"]
    assert manifest["contract"]["source_fingerprint"] == source_metadata["source_fingerprint"]
    assert set(metadata) == set(distribution.LAUNCHER_METADATA_KEYS)
    from pdx import distribution

    assert manifest["mod_id"] == distribution.MOD_ID
    assert manifest["install_directory"] == distribution.INSTALL_DIRECTORY_NAME
    assert manifest["generation"]["install_directory"] == distribution.INSTALL_DIRECTORY_NAME
    assert manifest["generation"]["candidate_kind"] == "production_candidate"
    assert manifest["generation"]["delivery_kind"] == "standard_mod"


@pytest.mark.parametrize("value", ["1", '"false"', "[]"])
def test_财政开关拒绝非布尔值(tmp_path, value):
    source = tmp_path / "fiscal.toml"
    source.write_text(
        decisions.SOURCE.read_text(encoding="utf-8").replace(
            "enabled = true", f"enabled = {value}"
        ),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError):
        decisions.load(source)


def test_财政开关缺失拒绝而关闭合法(tmp_path):
    source = tmp_path / "fiscal.toml"
    text = decisions.SOURCE.read_text(encoding="utf-8")
    source.write_text(text.replace("enabled = true\n", ""), encoding="utf-8", newline="\n")
    with pytest.raises(ValueError, match="缺失"):
        decisions.load(source)
    source.write_text(
        text.replace("enabled = true", "enabled = false"),
        encoding="utf-8",
        newline="\n",
    )
    assert not decisions.load(source).enabled


def test_关闭阻止默认挂载和内存风险状态(policy, monkeypatch):
    disabled = replace(policy, enabled=False)
    monkeypatch.setattr(decisions, "load", lambda: disabled)
    assert decisions.on_actions() == ""
    assert (
        decisions.risk_next(
            False,
            in_default=True,
            taking_loans=True,
            credit=100,
            weeks=0,
            policy=disabled,
        )
        is False
    )


def test_开关往返清理旧生成物且保留未知文件(tmp_path, policy):
    enabled = decisions.build(
        policy,
        extensions=decisions.Extensions(reform_enabled=True, market_enabled=True),
    )
    disabled = decisions.build(replace(policy, enabled=False), extensions=decisions.Extensions())
    decisions.write(tmp_path, enabled)
    assert decisions.check(tmp_path, enabled) == []
    decisions.write(tmp_path, disabled)
    assert decisions.check(tmp_path, disabled) == []
    assert not any((tmp_path / name).exists() for name in enabled.keys() - disabled.keys())
    decisions.write(tmp_path, enabled)
    assert decisions.check(tmp_path, enabled) == []
    unknown = tmp_path / "common/on_actions/custom.txt"
    unknown.write_text("# 用户文件\n", encoding="utf-8", newline="\n")
    decisions.write(tmp_path, disabled)
    assert unknown.read_text(encoding="utf-8") == "# 用户文件\n"
    assert any("custom.txt" in issue for issue in decisions.check(tmp_path, disabled))


@pytest.mark.parametrize(
    ("reform", "market"), [(False, False), (True, False), (False, True), (True, True)]
)
def test_关闭财政仍验证共享策略底本(tmp_path, policy, monkeypatch, reform, market):
    monkeypatch.setattr(decisions, "load", lambda: replace(policy, enabled=False))
    monkeypatch.setattr(
        decisions,
        "load_extensions",
        lambda: decisions.Extensions(reform_enabled=reform, market_enabled=market),
    )
    snapshot: dict[str, object] = {
        "域": {
            "vocabulary": {rel: [] for rel in decisions.VOCABULARY_DIRS},
            "vanilla_keys": {rel: [] for rel in decisions.KEY_DIRS},
            "vanilla_variables": {rel: [] for rel in decisions.VARIABLE_POOL_DIRS},
        }
    }
    strategy = tmp_path / "common/ai_strategies/00_default_strategy.txt"
    strategy.parent.mkdir(parents=True)
    strategy.write_text("# 本机底本已漂移\n", encoding="utf-8", newline="\n")
    issues = decisions.validate(set(), game=tmp_path, snapshot=snapshot)
    assert "本机默认策略与锁定底本不一致，需重审版本" in issues
    assert not any("本机财政接口参考" in issue for issue in issues)


def test_指纹绑定实际替代源和生成器(tmp_path):
    fiscal, extensions = tmp_path / "fiscal.toml", tmp_path / "extensions.toml"
    fiscal.write_bytes(decisions.SOURCE.read_bytes() + b"\n# alternative fiscal\n")
    extensions.write_bytes(decisions.EXTENSIONS.read_bytes() + b"\n# alternative extensions\n")
    policy, extra = decisions.load(fiscal), decisions.load_extensions(extensions)
    metadata = json.loads(decisions.build(policy, extensions=extra)[".metadata/metadata.json"])
    fingerprint = metadata["source_fingerprint"]
    assert fingerprint["fiscal_source_sha256"] == hashlib.sha256(fiscal.read_bytes()).hexdigest()
    assert (
        fingerprint["extensions_source_sha256"]
        == hashlib.sha256(extensions.read_bytes()).hexdigest()
    )
    assert (
        fingerprint["generator_sha256"]
        == hashlib.sha256(decisions.Path(decisions.__file__).read_bytes()).hexdigest()
    )


@pytest.mark.integration
def test_正式包确定性清单编码与完整生产内容(tmp_path):
    import codecs
    import zipfile

    from typer.testing import CliRunner

    from pdx import cli

    target = tmp_path / "release.zip"
    runner = CliRunner()
    args = ["package", "--output", str(target)]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    raw = target.read_bytes()
    assert runner.invoke(cli.app, args).exit_code == 0
    assert target.read_bytes() == raw
    with zipfile.ZipFile(target) as archive:
        manifest = json.loads(archive.read("DISTRIBUTION-MANIFEST.json"))
        generation = manifest["generation"]
        assert generation["variant"] == "release"
        assert generation["fiscal"]["enabled"] is True
        assert generation["behavior_quality"] == "not_evaluated"
        assert manifest["contract"]["product_version"] == distribution.RELEASE_VERSION
        enabled_modules = set(manifest["contract"]["enabled_modules"])
        assert {
            "fiscal",
            "reform",
            "market",
            "security",
            "economy",
            "diplomacy",
            "information_rules",
            "consumer_adapters",
            "country_state",
        } <= enabled_modules
        assert manifest["contract"]["country_state"]["variable_ttl_days"] == 100
        assert (
            manifest["contract"]["country_coordination"]["runtime_state"]
            == "bounded_persistent_routes"
        )
        strategy = archive.read("common/ai_strategies/00_default_strategy.txt").decode("utf-8-sig")
        assert "# SITAI BEGIN information:" in strategy
        lifecycle = "common/on_actions/sitai_fiscal_on_actions.txt"
        assert lifecycle in archive.namelist()
        assert len([name for name in archive.namelist() if name.startswith("localization/")]) == 11
        for name, digest in manifest["files"].items():
            payload = archive.read(name)
            assert hashlib.sha256(payload).hexdigest() == digest
            if name == distribution.THUMBNAIL_NAME:
                assert payload.startswith(b"\x89PNG\r\n\x1a\n")
                continue
            assert b"\r" not in payload
            assert payload.startswith(codecs.BOM_UTF8) == name.endswith((".txt", ".yml"))


@pytest.mark.integration
def test_正式包API和CLI输出逐字节一致(tmp_path):
    import zipfile

    from typer.testing import CliRunner

    from pdx import cli, distribution

    api_target, cli_target = tmp_path / "api.zip", tmp_path / "cli.zip"
    distribution.package(api_target)
    result = CliRunner().invoke(cli.app, ["package", "--output", str(cli_target)])
    assert result.exit_code == 0, result.output
    assert cli_target.read_bytes() == api_target.read_bytes()
    with zipfile.ZipFile(api_target) as archive:
        manifest = json.loads(archive.read("DISTRIBUTION-MANIFEST.json"))
        assert manifest["generation"]["variant"] == distribution.RELEASE_VARIANT
        assert "fiscal" in manifest["contract"]["enabled_modules"]
        assert "common/on_actions/sitai_fiscal_on_actions.txt" in archive.namelist()


@pytest.mark.integration
def test_交付说明由清单覆盖且明确用户验收边界(tmp_path):
    import zipfile

    from pdx import distribution

    with zipfile.ZipFile(distribution.package(tmp_path / "guide.zip")) as archive:
        raw = archive.read("README.md")
        text = raw.decode("utf-8")
        manifest = json.loads(archive.read("DISTRIBUTION-MANIFEST.json"))
        assert manifest["files"]["README.md"] == hashlib.sha256(raw).hexdigest()
        assert f"Situated AI {distribution.RELEASE_VERSION}" in text
        assert "【中文】" in text
        assert "[English]" in text
        assert f"产品版本 / Product version：{distribution.RELEASE_VERSION}\n" in text
        assert "长期行为、平衡、后期性能" in text
        assert "Long-run AI behavior" in text
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert b"\r" not in raw


def test_说明使用调用方提供的版本与财政参数(policy):
    from pdx.distribution import player_guide

    alternate = replace(
        policy,
        entry_weeks=17,
        exit_weeks=43,
        ttl_days=73,
        neutrality=7.5,
        aggression=-0.25,
        package=replace(
            policy.package,
            product_version="0.2.1",
            status="candidate",
            parent="accepted-parent",
            save_compatibility="same-candidate-save",
        ),
    )
    extensions = decisions.Extensions(
        reform_enabled=True,
        reform_legitimacy=81,
        fragile_legitimacy=19,
        reform_bonus=2.5,
        fragile_penalty=-0.25,
        market_enabled=True,
        market_multiplier=3.5,
    )
    text = player_guide(alternate, extensions, ["fiscal", "reform", "market"])
    for expected in (
        "产品版本 / Product version：0.2.1",
        "Supported game version",
        "Enabled modules",
        "少于 17 周",
        "fewer than 17 weeks",
        "43 周退出线",
        "73 天状态有效期",
        "中立偏置为 7.5",
        "攻击性偏置为 -0.25",
        "reform=启用，market=启用",
        "security=关闭",
        "reform=enabled",
        "market=enabled",
    ):
        assert expected in text


def test_说明保留用户验收边界和回退且不进入游戏生成树(policy):
    from pdx.distribution import player_guide

    extensions = replace(decisions.Extensions(), diplomacy_enabled=True)
    text = player_guide(policy, extensions, ["fiscal", "diplomacy"])
    for expected in (
        "这是唯一正式生产包",
        "原版资格、成本、效果与行动流程继续生效",
        "AI 长期行为、平衡、后期性能、玩家体验与创意工坊发布由用户验收",
        "回退：退出游戏后禁用或删除本 Mod",
        "pre-installation save",
        "宗属倾向由声明式原版消费者适配器统一实现",
        "Long-run AI behavior",
        "Subject tendencies use declarative adapters for vanilla consumers.",
    ):
        assert expected in text
    assert "README.md" not in decisions.build(policy)


@pytest.mark.integration
def test_说明生成失败保全已有ZIP(tmp_path, monkeypatch):
    from pdx import distribution

    target = tmp_path / "existing.zip"
    target.write_bytes(b"previous package")

    def fail(*args, **kwargs):
        raise ValueError("说明生成失败")

    monkeypatch.setattr(distribution, "player_guide", fail)
    with pytest.raises(ValueError, match="说明生成失败"):
        distribution.package(target)
    assert target.read_bytes() == b"previous package"
