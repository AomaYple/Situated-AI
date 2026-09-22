"""`[difficulty]`（阶段 6 / 契约 J5）的看守。

这一组钉住四件事，缺一个就会以"看起来没事"的方式烂掉：
* **档位集合是契约**：多一档/少一档、改名，编译期就报错（`DIFFICULTY_TIERS` 钉住）；
* **规则名与设置名在同一命名空间**（F7）：`has_game_rule` 读的是全局字符串；
* **三档的行为差异真的落到产物里**：玩家侧修正 + 效果里的 `if` 分支
  （否则就是"界面上有个选项，选了什么也不发生"）；
* **默认档不加戏**：`一视同仁` 不能悄悄带一条修正。
"""

from __future__ import annotations

import pytest

from pdx import modgen

DIFFICULTY = """
[[localization]]
key = "rule_sitai_t1_difficulty"
english = "Situations (difficulty)"
simp_chinese = "处境难度"
why = "测：规则名要有文案"

[difficulty]
key = "sitai_t1_difficulty"
icon = "gfx/interface/icons/timed_modifier_icons/modifier_lightbulb_positive.dds"
why = "测：为什么要难度分档"

[difficulty.tiers]
why = "测：为什么三档放在一张表里"

[difficulty.tiers.history_friendly]
label_english = "History-friendly"
label_simp_chinese = "史实友好"
desc_english = "Softer."
desc_simp_chinese = "轻一些。"
why = "测：第一档为什么减震"
player_why = "测：减震的数字依据"
[[difficulty.tiers.history_friendly.player_effects]]
key = "country_legitimacy_base_add"
amount = 10
why = "测：为什么是 +10"

[difficulty.tiers.uniform]
label_english = "Even-handed"
label_simp_chinese = "一视同仁"
desc_english = "Default."
desc_simp_chinese = "默认。"
why = "测：为什么它是默认档"

[difficulty.tiers.harsh]
label_english = "Ruthless"
label_simp_chinese = "无情"
desc_english = "Harder."
desc_simp_chinese = "更重。"
why = "测：为什么需要第三档"
player_why = "测：加重的数字依据"
[[difficulty.tiers.harsh.player_effects]]
key = "interest_group_ig_landowners_pol_str_mult"
amount = 0.25
why = "测：为什么是 0.25"
"""


def _build(tmp_path, extra: str = DIFFICULTY):
    from tests.test_modgen import MINIMAL, _archive

    archive = _archive(tmp_path, MINIMAL + extra)
    return archive, modgen.build(archive)


def test_规则与设置名都在_sitai_命名空间(tmp_path) -> None:
    archive, _built = _build(tmp_path)
    difficulty = archive.difficulty
    assert difficulty is not None
    assert difficulty.key.startswith("sitai_"), "F7：规则名必须落在我们自己的命名空间里"
    for tier in difficulty.tiers:
        assert tier.setting.startswith("setting_sitai_")
        assert tier.modifier.startswith("sitai_")


def test_三档集合与默认档由常量钉住(tmp_path) -> None:
    archive, built = _build(tmp_path)
    rule = built.files[archive.difficulty.rule_file]
    assert f"default = setting_sitai_t1_difficulty_{modgen.DIFFICULTY_DEFAULT}" in rule
    for tier in archive.difficulty.tiers:
        assert f"flag = {tier.setting}" in rule, "没有 flag 就 `has_game_rule` 读不到"


def test_少一档或改档位名都当场报错(tmp_path) -> None:
    """两种坏法都要**在编译期**报错，而不是生成一份"少了一档"的规则文件。"""
    from tests.test_modgen import MINIMAL, _archive

    from pdx import modgen as m

    # ① 少一档（整段删掉）
    missing = DIFFICULTY.split("[difficulty.tiers.harsh]", maxsplit=1)[0]
    with pytest.raises(m.DataError, match="必须正好是"):
        _archive(tmp_path, MINIMAL + missing)

    # ② 改档位名（段头与数组表头都要改，否则先撞上"这张表没有 why"）
    renamed = DIFFICULTY.replace("tiers.harsh", "tiers.ruthless")
    with pytest.raises(m.DataError, match="必须正好是"):
        _archive(tmp_path, MINIMAL + renamed)


def test_默认档不许偷偷带修正(tmp_path) -> None:
    """`一视同仁` 是"对谁都不加戏" —— 它要是带了玩家侧修正，默认口径就变了。"""
    archive, built = _build(tmp_path)
    difficulty = archive.difficulty
    assert difficulty is not None
    uniform = difficulty.tier(modgen.DIFFICULTY_DEFAULT)
    assert uniform.player_effects == ()
    assert not [t for t in difficulty.tiers_with_player_effects() if t.id == uniform.id]
    assert difficulty.tier("history_friendly").player_effects
    assert difficulty.tier("harsh").player_effects
    assert built.files[difficulty.modifier_file].count(" = {") == 2


def test_效果里按档位给玩家追加修正(tmp_path) -> None:
    """三档的差异必须**真的接线**：界面上选了什么也不发生是最坏的一种"做完了"。"""
    archive, built = _build(tmp_path)
    effects = built.files[archive.effect_file]
    difficulty = archive.difficulty
    assert difficulty is not None
    assert "is_ai = no" in effects, "玩家侧修正只该落在玩家身上"
    for tier in difficulty.tiers_with_player_effects():
        assert f"has_game_rule = {tier.setting}" in effects
        assert f"name = {tier.modifier}" in effects
    # 时长与压力修正一致（否则会出现"压力还在、难度修正没了"的半截状态）
    assert effects.count("years = 10") == 3  # 压力 + 两档难度


def test_修正名与规则名都有本地化(tmp_path) -> None:
    archive, built = _build(tmp_path)
    loc = built.files[next(rel for rel in built.files if rel.endswith("_l_english.yml"))]
    assert f"rule_{archive.difficulty.key}:0" in loc
    for tier in archive.difficulty.tiers_with_player_effects():
        assert f"{tier.modifier}:0" in loc


def test_没有难度表时不报错但也不产出规则文件(tmp_path) -> None:
    """0 份**不在编译期报错**（理由见 `modgen._check_difficulty`）：契约项在位由
    「真实数据源」用例看守 —— 那才是"发布的那一份"该被检查的地方。"""
    from tests.test_modgen import MINIMAL

    from pdx import modgen as m

    archive = m.parse_source(m.read_source(_write(tmp_path, MINIMAL)), "x.toml")
    built = m.build_all([archive])
    assert all("game_rules" not in rel for rel in built.files)


def test_真实数据源声明了难度三档() -> None:
    """**契约 J5 的机械检查**：发布的那份数据源必须有难度三档，且档位齐全。

    跑在真实 `mod/data` 上（不是夹具）：把 `[difficulty]` 删掉这条就红 ——
    而不是让每个最小夹具都背一张 mod 级契约表（那正是第一次把它放进编译期的后果：
    61 条与难度无关的用例当场红）。
    """
    from pathlib import Path

    from pdx import config, modgen

    data = Path(config.REPO) / "mod" / "data"
    if not data.is_dir():  # pragma: no cover - 换机器时才走到
        pytest.skip("没有 mod/data")
    archives = modgen.load_all(data)
    owners = [item for item in archives if item.difficulty is not None]
    assert len(owners) == 1, "难度三档是 mod 级表：真实数据源里必须**恰好一份**声明它"
    difficulty = owners[0].difficulty
    assert difficulty is not None
    assert {tier.id for tier in difficulty.tiers} == set(modgen.DIFFICULTY_TIERS)
    assert difficulty.tier(modgen.DIFFICULTY_DEFAULT).player_effects == (), "默认档不加戏"
    built = modgen.build_all(archives)
    assert difficulty.rule_file in built.files
    assert difficulty.modifier_file in built.files
    assert "sitai_difficulty" in built.files[difficulty.rule_file]


def test_两份档案都声明难度表也报错(tmp_path) -> None:
    from tests.test_modgen import MINIMAL

    from pdx import modgen as m

    text = MINIMAL + DIFFICULTY
    first = _write(tmp_path / "a", text)
    second = _write(tmp_path / "b", text.replace("t1", "t2"))
    with pytest.raises(m.DataError, match="只允许一份"):
        m.build_all(
            [
                m.parse_source(m.read_source(first), "a.toml"),
                m.parse_source(m.read_source(second), "b.toml"),
            ]
        )


def _write(directory, text: str):
    from pathlib import Path

    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    target = path / "sitai.toml"
    target.write_text(text, encoding="utf-8")
    return target
