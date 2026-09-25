"""`[difficulty]`（阶段 6 / 契约 J5）的看守。

这一组钉住五件事，缺一个就会以"看起来没事"的方式烂掉：
* **档位集合是契约**：多一档/少一档、改名，编译期就报错（`DIFFICULTY_TIERS` 钉住）；
* **规则名与设置名在同一命名空间**（F7）：`has_game_rule` 读的是全局字符串；
* **引擎的文案键必须命中**：`setting_<设置块名>` 与 `setting_<设置块名>_desc` 都要在本地化表里，
  且**块名不许带 `setting_` 前缀**（带一次，规则窗那一行就显示原始键 —— 实机帧
  `tools/out/auto/22-rule-sitai-scroll-5.png`）。这是唯一一条"玩家直接用眼睛看得到"的判据；
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


def _sibling():
    """拿同目录的 `test_modgen` 模块（共用它的最小夹具，不复制一份）。

    ⚠️ 为什么用 `importlib` 而不是 `from tests.test_modgen import …`：后者会让 mypy 把
    那个文件当成**两个模块名**（`test_modgen` 与 `tests.test_modgen`）⇒
    `Source file found twice under different module names`，整份 mypy 停摆
    （实测：这条一加，`mypy` 直接 "errors prevented further checking"）。
    静态看不见的 import 绕开了这个歧义，同时保留"夹具只有一份"。
    """
    import importlib

    return importlib.import_module("tests.test_modgen")


def _build(tmp_path, extra: str = DIFFICULTY):
    sibling = _sibling()
    MINIMAL, _archive = sibling.MINIMAL, sibling._archive

    archive = _archive(tmp_path, MINIMAL + extra)
    return archive, modgen.build(archive)


def test_规则与设置名都在_sitai_命名空间(tmp_path) -> None:
    archive, _built = _build(tmp_path)
    difficulty = archive.difficulty
    assert difficulty is not None
    assert difficulty.key.startswith("sitai_"), "F7：规则名必须落在我们自己的命名空间里"
    for tier in difficulty.tiers:
        assert tier.setting.startswith("setting_sitai_")
        assert tier.setting == f"setting_{tier.name}"
        assert tier.name.startswith("sitai_")
        assert not tier.name.startswith("setting_"), "设置名自带前缀 ⇒ 引擎会查 `setting_setting_*`"
        assert tier.modifier.startswith("sitai_")


def test_引擎的_setting_文案键必须命中(tmp_path) -> None:
    """引擎查规则窗那一档的文案 = `setting_<设置块名>` / `setting_<设置块名>_desc`。

    ⚠️ 键跟的是**设置块名**，不是块里的 `flag`（原版 `common/game_rules/game_rules.md:10-12`
    规定了这一族前缀；`game/localization/english/game_rules_l_english.yml` 全表逐条可核）：
    块 `lenient_ai_behavior` 的 flag 是 `lenient_ai` ⇒ 键是 `setting_lenient_ai_behavior`；
    块 `achievements_blocked` 的 flag 是 `blocks_achievements` ⇒ 键是
    `setting_achievements_blocked`；而 `setting_all_formable_nations` /
    `setting_allow_dynamic_naming` / `setting_no_custom_rng_seed` 这些设置**根本没有 flag**，
    照样有键 ⇒「按 flag 查」结构上不成立（实机帧 `22-rule-sitai-scroll-5.png` 里
    那几条无 flag 的原版行显示正常文案，是同一现象的正向对照）。
    踩过的坑：块名写成 `setting_sitai_difficulty_uniform` ⇒ 引擎查
    `setting_setting_sitai_difficulty_uniform` ⇒ 落空 ⇒ 规则窗那一行显示原始键
    （标题「处境难度」正常、值框与说明是原始键 —— 前缀只在这一层出错）。
    **产品对产品**地判：块名与 flag 从 `readback()`（按 PDX 语法把产物解析回来）读，
    文案键从同一份 readback 的本地化条目读 —— 不看 Python 对象。
    """
    archive, built = _build(tmp_path)
    difficulty = archive.difficulty
    assert difficulty is not None
    back = dict(modgen.readback(built.files))
    prefix = f"gamerule.{difficulty.key}.setting."
    blocks = {
        key[len(prefix) : -len(".flag")]: value
        for key, value in back.items()
        if key.startswith(prefix) and key.endswith(".flag")
    }
    assert len(blocks) == len(difficulty.tiers), f"设置块没记全：{sorted(blocks)}"
    keys = {key.split(".", 2)[2] for key in back if key.startswith("localization.english.")}
    assert f"rule_{difficulty.key}" in keys, "规则名走同一套前缀规则（`rule_<块名>`）"
    for block, flag in blocks.items():
        assert f"setting_{block}" in keys, (
            f"引擎按 `setting_{block}` 查这一档的名字 ⇒ 现在只会落空、显示原始键"
        )
        assert f"setting_{block}_desc" in keys, f"说明键 `setting_{block}_desc` 不在本地化表里"
        assert not block.startswith("setting_"), "块名不许带 `setting_` 前缀（前缀只属于本地化键）"
        assert flag == block, "flag 与块名必须同串：`has_game_rule` 的取值在原版里两者同串"
    assert back[f"gamerule.{difficulty.key}.default"] in blocks, "`default =` 必须引用某个块名"
    for tier in difficulty.tiers:
        assert tier.name in blocks, f"{tier.id} 这一档的块名不是 `tier.name`（{tier.name}）"


def test_has_game_rule_取设置名而文案键仍带_setting_前缀(tmp_path) -> None:
    """效果里的 `limit.has_game_rule` 取**设置名**（无前缀），文案键才带 `setting_`。

    引擎读的是设置名（:attr:`modgen.DifficultyTier.name`），`setting_<设置名>`
    只用于查文案 —— 两个词在同一处相邻出现，最容易顺手改错其中一个：t88 拆分这两个
    属性时只改了渲染与文案，**漏改了 `modgen.facts()` 的预期值**（产物写设置名、
    claim 写文案键）⇒ 闸门 ④ 对 `ru_defeat` 报「缺 2 多 2」（modguard 的 5 条红）。

    这条**两侧都钉**：claim（`facts()`）与产物反解（`readback()`），任一侧把
    name/setting 弄混都会红；反向「给产物补前缀」也会红（`:138` 那条断言的同类）。
    """
    archive, built = _build(tmp_path)
    difficulty = archive.difficulty
    assert difficulty is not None
    tiers = difficulty.tiers_with_player_effects()
    assert len(tiers) == 2, "夹具要有两档带 player_effects，否则这条什么都没测"
    facts = dict(modgen.facts(archive))
    back = dict(modgen.readback(built.files))
    text = built.files[archive.effect_file]
    for index, tier in enumerate(tiers):
        key = f"effects.{archive.memory.effect}.if[{index}].limit.has_game_rule"
        assert facts[key] == tier.name, f"claim 的预期值必须是设置名：{facts[key]!r}"
        assert back[key] == tier.name, f"产物里的操作数必须是设置名：{back[key]!r}"
        assert not facts[key].startswith("setting_"), "带前缀 ⇒ 引擎查 `setting_setting_*` 落空"
        assert f"has_game_rule = {tier.name}" in text
        # 文案键那一侧**不许**被顺手改掉：本地化表里仍要有 `setting_<设置名>`
        loc = f"localization.english.{tier.setting}"
        assert loc in facts, f"文案键 {tier.setting} 必须还在 claim 的事实表里"
        assert loc in back, f"文案键 {tier.setting} 必须还在产物的事实表里"
    assert "has_game_rule = setting_" not in text, "操作数不许带文案键的前缀"


def test_三档集合与默认档由常量钉住(tmp_path) -> None:
    archive, built = _build(tmp_path)
    difficulty = archive.difficulty
    assert difficulty is not None
    rule = built.files[difficulty.rule_file]
    assert f"default = {difficulty.tier(modgen.DIFFICULTY_DEFAULT).name}" in rule
    for tier in difficulty.tiers:
        assert f"{tier.name} = {{" in rule, "设置块的块名就是引擎眼里的设置名"
        assert f"flag = {tier.name}" in rule, "没有 flag 就 `has_game_rule` 读不到"


def test_少一档或改档位名都当场报错(tmp_path) -> None:
    """两种坏法都要**在编译期**报错，而不是生成一份"少了一档"的规则文件。"""
    sibling = _sibling()
    MINIMAL, _archive = sibling.MINIMAL, sibling._archive

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
        assert f"has_game_rule = {tier.name}" in effects
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
    MINIMAL = _sibling().MINIMAL

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
    # 发布的那一份也要过引擎的文案键判据（跑在真实 `mod/data` + 真实本地化产物上）
    back = dict(modgen.readback(built.files))
    loc = {key.split(".", 2)[2] for key in back if key.startswith("localization.english.")}
    for tier in difficulty.tiers:
        assert f"setting_{tier.name}" in loc, f"{tier.id} 的名称键不在本地化表里"
        assert f"setting_{tier.name}_desc" in loc, f"{tier.id} 的说明键不在本地化表里"


def test_两份档案都声明难度表也报错(tmp_path) -> None:
    MINIMAL = _sibling().MINIMAL

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
