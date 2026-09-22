"""``pdx.modgen`` 的用例：数据源 → 产物的那条编译链。

重点不是"文件写出来了"，而是**那几条会让产物静默失效的性质**：

* 空 `why` 必须当场报错（P10 的机械检查 —— 靠人记得的纪律等于没有）；
* 两次生成逐字节一致（P8：确定性是"生成器优先"的前提，抖动的产物没法进版本控制）；
* 游戏侧文件带 UTF-8 BOM、文件名平铺在 `sitai_*` 命名空间（F7）——
  缺 BOM 在游戏里的表现是"这份文件像没生效"，只写进 error.log；
* 产物能被**仓库自己的解析器**读懂（拼漏一个 `}` 是最可能的故障模式）。

用例一律不依赖真实游戏：数据源写到 `tmp_path` 再编译。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from pdx import modgen
from pdx.parser import parse_text

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

#: 一份**最小可用**的数据源。各用例用定向替换把它改成"缺东西"的版本 ——
#: 这样"报错"的用例与"通过"的用例只差一处，失败时一眼能看出是哪一处引起的。
MINIMAL = """schema_version = 1

[archive]
id = "t1"
title = "测试档案"
country = "RUS"
game_version = "1.14.3"
why = "测：这份档案修什么毛病"

[tempo]
block = "NAI"
why = "测：为什么要接管节奏"
[[tempo.keys]]
key = "CHANGE_STRATEGY_THRESHOLD"
amount = 40
why = "测：为什么是 40"

[memory]
variable = "sitai_t1_memory"
effect = "sitai_t1_shock"
why = "测：记忆变量做什么用"
[[memory.params]]
key = "days"
amount = 3650
why = "测：为什么是 3650 天"

[pressure]
name = "sitai_t1_pressure"
icon = "gfx/interface/icons/timed_modifier_icons/modifier_statue_negative.dds"
why = "测：压力为什么必须是真的世界状态"
[[pressure.params]]
key = "years"
amount = 10
why = "测：为什么是 10 年"
[[pressure.effects]]
key = "country_legitimacy_base_add"
amount = -20
why = "测：为什么取 -20"

[journal_entry]
name = "je_sitai_t1_window"
group = "je_group_internal_affairs"
icon = "gfx/interface/icons/event_icons/event_portrait.dds"
why = "测：为什么用 JE 而不是牌"
[[journal_entry.fields]]
key = "weight"
amount = 100
why = "测：为什么是 100"
[[journal_entry.conditions]]
gate = "possible"
key = "has_variable"
arg = "sitai_t1_memory"
why = "测：开窗的第一个条件"

[[localization]]
key = "je_sitai_t1_window"
english = "Test Window"
simp_chinese = "测试窗口"
why = "测：文案依据"

[cards]
why = "测：本档案不递牌的理由"

[[references]]
kind = "trigger"
name = "has_variable"
why = "测：这条引用在原版哪里用过"
"""

#: `MINIMAL` 里的 `[tempo]` 段（**逐字**复制）。
#: 阶段 4 起 `[tempo]` 是可选的 **mod 级**表：全仓只允许一份，所以第二份档案
#: 必须能整段不带它 —— 这条常量就是"摘掉它"的那个手术刀。
TEMPO_BLOCK = """[tempo]
block = "NAI"
why = "测：为什么要接管节奏"
[[tempo.keys]]
key = "CHANGE_STRATEGY_THRESHOLD"
amount = 40
why = "测：为什么是 40"

"""

#: 追加到 :data:`MINIMAL` 后面的"第二处理段"（可选表 `[reform_inputs]`）。
#: 单独一份常量：`MINIMAL` 保持"只有一处处理"的形状，两条路径都要有用例。
REFORM_INPUTS = """
[reform_inputs]
name = "sitai_t1_reform_inputs"
effect = "sitai_t1_reform_input"
icon = "gfx/interface/icons/timed_modifier_icons/modifier_lightbulb_positive.dds"
why = "测：改革侧输入为什么单独一份"
[[reform_inputs.params]]
key = "years"
amount = 10
why = "测：为什么是 10 年"
[[reform_inputs.effects]]
key = "country_legitimacy_base_add"
amount = 5
why = "测：为什么取 +5"
"""

#: 追加到 :data:`MINIMAL` 后面的"递牌信号"（可选表 `[journal_entry.signals]`）。
#: 2026-09-22 新增：世界状态只改得了 AI 的**输入**，改不了它已经挂着的那张牌，
#: 而牌才是"动不动手改法"的闸门（backlog B53）⇒ 窗口开时必须 `set_strategy`。
SIGNALS = """
[journal_entry.signals]
why = "测：为什么必须递牌（世界状态改不了已挂着的牌）"
[[journal_entry.signals.set_strategy]]
key = "set_strategy"
arg = "ai_strategy_progressive_agenda"
why = "测：窗口一开就换路线"
[[journal_entry.signals.clear_strategy]]
key = "set_strategy"
arg = "ai_strategy_reactionary_agenda"
why = "测：窗口一关递回去"
"""


#: 追加到 :data:`MINIMAL` 后面的"面板三行"（可选表 `[panel]`，P11 的三行解释）。
#: 2026-09-22 新增：G3 判的是**试玩者能复述「当前目标 + 主因」**，而揉进 `_reason`
#: 的散文里看不出"缺哪一行" ⇒ 拆成三个键，缺行当场报错。
#:
#: ⚠️ 2026-09-23 起还要求数据源里有 `<JE 名>_reason` 那条 loc：三行要**上屏**就得接进
#: JE 说明（引擎显示的是 `[JournalEntry.GetReason]`），所以这里连带补上它。
PANEL = """
[[localization]]
key = "je_sitai_t1_window_reason"
english = "Test window reason."
simp_chinese = "测试窗口的说明。"
why = "测：JE 说明的依据（三行会接在它后面）"

[panel]
why = "测：为什么这三行要放在一起"
[panel.goal]
english = "Goal line."
simp_chinese = "目标行。"
why = "测：第一行为什么是当前目标"
[panel.pressure]
english = "Pressure line."
simp_chinese = "压力行。"
why = "测：第二行为什么是压力与阻力"
[panel.last_change]
english = "Last change line."
simp_chinese = "上次改主意的原因行。"
why = "测：第三行为什么是上次改主意的原因"
"""


def _write_source(tmp_path: Path, text: str = MINIMAL, name: str = "t1.toml") -> Path:
    base = tmp_path / "data"
    base.mkdir(parents=True, exist_ok=True)
    path = base / name
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _archive(tmp_path: Path, text: str = MINIMAL) -> modgen.Archive:
    return modgen.load_data(_write_source(tmp_path, text))


def _second_source(
    *,
    tempo: bool = False,
    game_version: str = "1.14.3",
) -> str:
    """第二份档案的数据源：**同一套结构、换一套名字**（G-EXIT-1 的"只加数据行"）。

    默认**不带** `[tempo]` —— 阶段 4 起它是全仓一份的 mod 级表，
    第二份档案不该复制一遍；`tempo=True` 用来造"两份都声明"的失败路径。
    """
    text = MINIMAL if tempo else MINIMAL.replace(TEMPO_BLOCK, "")
    for old, new in (
        ('id = "t1"', 'id = "t2"'),
        ('title = "测试档案"', 'title = "第二档案"'),
        ('country = "RUS"', 'country = "AUS"'),
        ('game_version = "1.14.3"', f'game_version = "{game_version}"'),
        ('name = "RUS"', 'name = "AUS"'),
        ("sitai_t1", "sitai_t2"),
    ):
        text = text.replace(old, new)
    return text


def _two_archives(
    tmp_path: Path,
    *,
    tempo: bool = False,
    game_version: str = "1.14.3",
    second_id: str = "t2",
) -> tuple[modgen.Archive, ...]:
    """写两份数据源并编译成档案（a.toml = MINIMAL，b.toml = 换名的第二份）。"""
    _write_source(tmp_path, MINIMAL, name="a.toml")
    text = _second_source(tempo=tempo, game_version=game_version)
    if second_id != "t2":
        text = text.replace('id = "t2"', f'id = "{second_id}"')
    _write_source(tmp_path, text, name="b.toml")
    return modgen.load_all(tmp_path / "data")


# ── 数据源解析 ──────────────────────────────────────────────
def test_解析真实档案的关键条目() -> None:
    """第一份档案（俄罗斯 · 战败求存）必须能被解析出它该有的东西。

    这条同时钉住"设计意图没被改掉"：变量名、修正名、JE 名、两个节奏键、
    第二处理段（B2 的改革侧输入），以及"一张牌都不递"（F5）。
    """
    archive = modgen.load_data(modgen.DATA_DIR / "ru_defeat.toml")
    assert archive.id == "ru_defeat"
    assert archive.country == "RUS"
    assert archive.memory.variable == "sitai_ru_defeat_memory"
    assert archive.memory.effect == "sitai_ru_defeat_shock"
    assert archive.pressure.name == "sitai_ru_defeat_pressure"
    assert archive.journal_entry.name == "je_sitai_ru_reform_window"
    assert archive.journal_entry.group == "je_group_internal_affairs"
    assert archive.tempo is not None, "第一份档案必须声明 [tempo]（它是 mod 级表）"
    assert {p.key for p in archive.tempo.keys} == {
        "CHANGE_STRATEGY_THRESHOLD",
        "CHANGE_STRATEGY_INCREASE_WEEKLY_CHANCE",
    }
    # 第二处理段（B2）：与冲击分成两个效果/两个修正，实验才分得出是哪一处起了作用
    assert archive.inputs is not None
    assert archive.inputs.effect == "sitai_ru_reform_input"
    assert archive.inputs.name == "sitai_ru_reform_inputs"
    assert {p.key for p in archive.inputs.effects} == {
        "interest_group_ig_industrialists_pol_str_mult",
        "interest_group_ig_intelligentsia_pol_str_mult",
    }
    assert archive.cards == (), "本档案刻意不递牌（F5：A 级已表达完整条链路）"
    # 7 条档案自己的文案（4 条基础 + **3 行面板**，键名由 JE 名派生）
    # + 难度三档的 7 条（规则名 1 + 三档各自的 名称/说明 6）
    # + 2 条"玩家侧修正名"（只有带 player_effects 的两档才有）
    assert len(archive.localization) == 16
    keys = {item.key for item in archive.localization}
    assert "rule_sitai_difficulty" in keys
    assert archive.difficulty is not None, "真实档案必须声明 [difficulty]（契约 J5）"
    for tier in archive.difficulty.tiers:
        assert tier.setting in keys
        assert f"{tier.setting}_desc" in keys
    assert {tier.id for tier in archive.difficulty.tiers} == set(modgen.DIFFICULTY_TIERS)
    assert [slot for slot, _key, _why in archive.panel] == ["goal", "pressure", "last_change"]
    assert [key for _slot, key, _why in archive.panel] == [
        "je_sitai_ru_reform_window_goal",
        "je_sitai_ru_reform_window_pressure",
        "je_sitai_ru_reform_window_last_change",
    ]


def test_没有reform_inputs的档案照样编译(tmp_path: Path) -> None:
    """`[reform_inputs]` 是可选表：没有第二处理段的档案不该被迫写一张空表。"""
    archive = _archive(tmp_path)
    assert archive.inputs is None
    built = modgen.build(archive)
    assert archive.inputs_file not in built.files
    assert "没有第二处理段" in built.files[archive.doc_file]
    assert modgen.facts(archive) == modgen.readback(built.files)


def test_有reform_inputs时多出效果与修正两条事实(tmp_path: Path) -> None:
    archive = _archive(tmp_path, MINIMAL + REFORM_INPUTS)
    assert archive.inputs is not None
    built = modgen.build(archive)
    facts = dict(modgen.facts(archive))
    assert facts["effects.sitai_t1_reform_input.add_modifier.name"] == "sitai_t1_reform_inputs"
    assert facts["modifier.sitai_t1_reform_inputs.country_legitimacy_base_add"] == "5"
    assert modgen.readback(built.files) == modgen.facts(archive)
    # 效果文件里两个效果并存；第二处修正自己一个文件（清掉一个不影响另一个）
    effect_text = built.files[archive.effect_file]
    assert "sitai_t1_shock = {" in effect_text
    assert "sitai_t1_reform_input = {" in effect_text
    assert "add_modifier = {\n\t\tname = sitai_t1_reform_inputs" in effect_text
    assert built.files[archive.inputs_file].count("sitai_t1_reform_inputs = {") == 1


def test_reform_inputs缺why照样报错(tmp_path: Path) -> None:
    text = (MINIMAL + REFORM_INPUTS).replace('why = "测：改革侧输入为什么单独一份"', "")
    with pytest.raises(modgen.DataError, match="没有 why"):
        _archive(tmp_path, text)


def test_真实档案的每个数字都有依据() -> None:
    """P10：`v3 modgen --why` 能机械枚举出每个数字 + 它的依据。"""
    archive = modgen.load_data(modgen.DATA_DIR / "ru_defeat.toml")
    report = modgen.why_report(archive)
    assert archive.numbers, "一个数字都没解析出来，说明口径写错了"
    for number in archive.numbers:
        assert number.why.strip(), f"{number.path} 没有依据"
        assert f"`{number.path}`" in report
    assert len(report.splitlines()) == len(archive.numbers) + 2  # 表头 + 分隔线


def test_未知schema版本报错(tmp_path: Path) -> None:
    with pytest.raises(modgen.DataError, match="schema_version"):
        _archive(tmp_path, MINIMAL.replace("schema_version = 1", "schema_version = 99"))


def test_空why报错(tmp_path: Path) -> None:
    """空 `why` 必须当场报错，并指出**是哪一张表**。"""
    text = MINIMAL.replace(
        'key = "country_legitimacy_base_add"\namount = -20\nwhy = "测：为什么取 -20"',
        'key = "country_legitimacy_base_add"\namount = -20\nwhy = "   "',
    )
    with pytest.raises(modgen.DataError, match=r"pressure\.effects\[0\]"):
        _archive(tmp_path, text)


def test_缺why字段也报错(tmp_path: Path) -> None:
    text = MINIMAL.replace('amount = -20\nwhy = "测：为什么取 -20"', "amount = -20")
    with pytest.raises(modgen.DataError, match="没有 why"):
        _archive(tmp_path, text)


def test_缺本地化语言报错(tmp_path: Path) -> None:
    """少一种语言 = 漏一种语言的文案，不能静默生成半份本地化。"""
    text = MINIMAL.replace('simp_chinese = "测试窗口"\n', "")
    with pytest.raises(modgen.DataError, match=" simp_chinese "):
        _archive(tmp_path, text)


def test_本地化文案带裸引号报错(tmp_path: Path) -> None:
    """`.yml` 的值用双引号包裹，裸引号会截断文本 —— 没有转义的实测证据，直接拒绝。

    用 TOML 的**字面**字符串（单引号）才写得进裸引号 —— 这正是这条检查存在的理由：
    基本字符串（双引号）里写不出裸引号，字面字符串里写得进。
    """
    text = MINIMAL.replace('english = "Test Window"', """english = 'Test "Window"'""")
    with pytest.raises(modgen.DataError, match="裸双引号"):
        _archive(tmp_path, text)


def test_未知判据块报错(tmp_path: Path) -> None:
    text = MINIMAL.replace('gate = "possible"', 'gate = "permanent"')
    with pytest.raises(modgen.DataError, match="不认识的判据块"):
        _archive(tmp_path, text)


def test_命名空间越界报错(tmp_path: Path) -> None:
    """F7：变量/效果/修正都不许跑到 `sitai_` 命名空间外面去。"""
    text = MINIMAL.replace('variable = "sitai_t1_memory"', 'variable = "t1_memory"')
    with pytest.raises(modgen.DataError, match="命名空间"):
        _archive(tmp_path, text)


def test_数据源不是TOML时报错(tmp_path: Path) -> None:
    with pytest.raises(modgen.DataError, match="TOML"):
        _archive(tmp_path, "这不是 TOML [[[")


def test_数据源目录为空时报错(tmp_path: Path) -> None:
    (tmp_path / "data").mkdir()
    with pytest.raises(modgen.DataError, match="没有"):
        modgen.load_all(tmp_path / "data")


# ── 确定性 ──────────────────────────────────────────────────
def test_两次构建完全一致(tmp_path: Path) -> None:
    """P8：同样的输入 → 同样的产出（含文件顺序）。"""
    archive = _archive(tmp_path)
    first = modgen.build(archive)
    second = modgen.build(archive)
    assert first.files == second.files
    assert first.paths == second.paths


def test_两次写盘逐字节一致(tmp_path: Path) -> None:
    """写盘也要确定：BOM、换行、文件集合都不能抖。"""
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    modgen.write(built, root_a)
    modgen.write(built, root_b)
    files_a = {
        p.relative_to(root_a).as_posix(): p.read_bytes() for p in root_a.rglob("*") if p.is_file()
    }
    files_b = {
        p.relative_to(root_b).as_posix(): p.read_bytes() for p in root_b.rglob("*") if p.is_file()
    }
    assert files_a == files_b
    assert files_a, "一个文件都没写出来"


def test_两份档案同id时产物路径冲突要报错(tmp_path: Path) -> None:
    """同 id 的两份档案写同一批产物路径 = 谁在起作用变成无解的问题，必须当场红。

    这份输入刻意绕过前面几道检查（名字各不相同、只有一份 tempo），
    为的是让"路径冲突"这条兜底真的被走到 —— 它现在是最后一道防线。
    """
    _write_source(tmp_path, MINIMAL, name="a.toml")
    _write_source(tmp_path, _second_source().replace('id = "t2"', 'id = "t1"'), name="b.toml")
    archives = modgen.load_all(tmp_path / "data")
    assert [archive.id for archive in archives] == ["t1", "t1"]
    with pytest.raises(modgen.DataError, match="同一个产物路径"):
        modgen.build_all(archives)


# ── 编码与命名 ──────────────────────────────────────────────
def test_游戏侧文件带BOM而文档不带(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    root = tmp_path / "mod"
    written = modgen.write(built, root)
    assert written
    for path in written:
        rel = path.relative_to(root).as_posix()
        head = path.read_bytes()[:3]
        if rel.endswith(modgen.GAME_SIDE_SUFFIXES):
            assert head == b"\xef\xbb\xbf", f"{rel} 少了 UTF-8 BOM（游戏里会像没生效）"
        else:
            assert head != b"\xef\xbb\xbf", f"{rel} 不该带 BOM"


def test_产物平铺在sitai命名空间且两层(tmp_path: Path) -> None:
    """F7：游戏侧文件是「原版目录 + sitai_*.txt/yml」，不自建子目录。"""
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    game_side = [p for p in built.paths if p.endswith(modgen.GAME_SIDE_SUFFIXES)]
    assert game_side
    for rel in game_side:
        parts = rel.split("/")
        assert len(parts) == 3, rel
        assert parts[2].startswith(modgen.FILE_PREFIX), rel


def test_生成物能被自家解析器读懂(tmp_path: Path) -> None:
    """拼漏一个 `}` 是生成器最可能的故障模式，而它在游戏里表现为"整段不生效"。"""
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    top_keys: dict[str, set[str]] = {}
    for rel, text in built.files.items():
        if not rel.endswith(".txt"):
            continue
        parsed = parse_text(text, path=rel)
        assert not parsed.errors, f"{rel}: {parsed.errors}"
        assert parsed.top_assignments, rel
        top_keys[rel.split("/")[1]] = {a.key for a in parsed.top_assignments}
    assert top_keys["scripted_effects"] == {archive.memory.effect}
    assert top_keys["static_modifiers"] == {archive.pressure.name}
    assert top_keys["journal_entries"] == {archive.journal_entry.name}
    assert archive.tempo is not None
    assert top_keys["defines"] == {archive.tempo.block}


def test_JE判据按固定顺序分组(tmp_path: Path) -> None:
    """判据块顺序固定 —— 数据源里换个书写次序不该让产物变样。"""
    text = (
        MINIMAL
        + """
[[journal_entry.conditions]]
gate = "complete"
key = "legitimacy"
op = ">="
amount = 75
why = "测：关窗的门"
"""
    )
    archive = _archive(tmp_path, text)
    body = modgen.build(archive).files[archive.journal_file]
    assert body.index("possible = {") < body.index("complete = {")
    assert "legitimacy >= 75" in body


def test_本地化格式照原版(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    chinese = built.files[archive.loc_file("simp_chinese")]
    assert chinese.splitlines()[0] == "l_simp_chinese:"
    assert f' {archive.journal_entry.name}:0 "测试窗口"' in chinese
    assert modgen.parse_loc_text(chinese) == {archive.journal_entry.name: "测试窗口"}


def test_元数据是合法JSON且不带BOM(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    payload = json.loads(built.files[modgen.METADATA_REL])
    assert payload["id"] == "sitai.t1"
    assert payload["supported_game_version"] == "1.14.3"
    root = tmp_path / "mod"
    modgen.write(built, root)
    assert not (root / modgen.METADATA_REL).read_bytes().startswith(b"\xef\xbb\xbf")


def test_档案文档带产物清单与依据(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    doc = modgen.build(archive).files[archive.doc_file]
    assert modgen.DOC_HEADER in doc
    assert "每个数字与它的依据" in doc
    assert archive.effect_file in doc
    assert "v3 modguard" in doc


# ── 写盘与核对 ──────────────────────────────────────────────
def test_写盘会清掉被取代的旧文件(tmp_path: Path) -> None:
    """数据源删掉一条之后，旧产物必须跟着消失 —— 否则"改了数据源却没变化"。"""
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    root = tmp_path / "mod"
    stale = root / "common" / "journal_entries" / "sitai_t1_old.txt"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("上一版的产物", encoding="utf-8")
    modgen.write(built, root)
    assert not stale.exists()
    assert (root / archive.journal_file).is_file()


def test_check能认出被手改的产物(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    root = tmp_path / "mod"
    modgen.write(built, root)
    assert modgen.check(built, root) == []

    target = root / archive.effect_file
    # 带 BOM 改写：否则先撞上的是"缺 BOM"那条，测不到内容比对
    target.write_text("手改过的内容", encoding="utf-8-sig", newline="\n")
    problems = modgen.check(built, root)
    assert any("不一致" in p for p in problems)

    target.unlink()
    assert any("缺产物" in p for p in modgen.check(built, root))


def test_check能认出缺BOM的产物(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    root = tmp_path / "mod"
    modgen.write(built, root)
    target = root / archive.loc_file("english")
    target.write_text(target.read_text(encoding="utf-8-sig"), encoding="utf-8", newline="\n")
    assert any("BOM" in p for p in modgen.check(built, root))


# ── 事实表（闸门 ④ 的两端）──────────────────────────────────
def test_数据源与产物往返一致(tmp_path: Path) -> None:
    """往返净度：数据源的事实表 == 从产物反解出来的事实表。"""
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    assert modgen.facts(archive) == modgen.readback(built.files)


# ── 递牌信号（`[journal_entry.signals]`）：阶段 3 的修正处 ──────────────


def test_缺省不生成递牌块(tmp_path: Path) -> None:
    """没有 `[signals]` 的档案**不生成** `immediate` / `on_complete` 空块。

    空块不是"什么都没有"：`immediate = { }` 在引擎里照样是一次真实的钩子，
    而在数据源里没有任何东西支撑它。缺省应当是**不写**，不是"写个空的"。
    """
    archive = _archive(tmp_path)
    assert archive.journal_entry.signals.empty
    text = modgen.journal_text(archive)
    # 判据看的是**块**（`immediate = {`），不是这个词 —— 注释里解释机制时也会提到它。
    assert "immediate = {" not in text
    assert "on_complete = {" not in text


def test_信号生成两个块且各带一张原版牌(tmp_path: Path) -> None:
    archive = _archive(tmp_path, MINIMAL + SIGNALS)
    text = modgen.journal_text(archive)
    assert "immediate = {" in text
    assert "set_strategy = ai_strategy_progressive_agenda" in text
    assert "on_complete = {" in text
    assert "set_strategy = ai_strategy_reactionary_agenda" in text
    # 顺序：immediate 必须在 on_complete 之前（读起来才是"开 → 关"）
    assert text.index("immediate = {") < text.index("on_complete = {")


def test_递牌信号能往返(tmp_path: Path) -> None:
    """新块也要过闸门 ④ —— 否则加信号就等于绕过往返净度。"""
    archive = _archive(tmp_path, MINIMAL + SIGNALS)
    built = modgen.build(archive)
    assert modgen.facts(archive) == modgen.readback(built.files)


def test_只许递原版已有的牌(tmp_path: Path) -> None:
    """白名单是**机制约束**，不是洁癖：递自建牌要抢政治槽（每国同时只有一张牌在用）。

    这条同时钉住"我们不会不小心把自建牌写进信号" —— 报错信息里要能看出可用集合。
    """
    bad = SIGNALS.replace("ai_strategy_progressive_agenda", "ai_strategy_sitai_own_card")
    with pytest.raises(modgen.DataError, match="不在白名单里"):
        _archive(tmp_path, MINIMAL + bad)


def test_信号必须用_arg_而不是_amount(tmp_path: Path) -> None:
    """递牌递的是**标识符**，写成 `amount = 1.0` 会生成一句没人认的
    `set_strategy = 1` —— 而那正是「每个数字都有依据」（P10）最容易被绕过的地方。"""
    bad = SIGNALS.replace(
        'arg = "ai_strategy_progressive_agenda"',
        "amount = 1.0",
    )
    with pytest.raises(modgen.DataError, match="必须用 `arg` 而不是 `amount`"):
        _archive(tmp_path, MINIMAL + bad)


def test_信号表缺依据要报错(tmp_path: Path) -> None:
    """P10 对**新表**同样生效：表级与条目的 `why` 都不能空。"""
    bad = SIGNALS.replace('why = "测：为什么必须递牌（世界状态改不了已挂着的牌）"\n', "")
    with pytest.raises(modgen.DataError, match="没有 why"):
        _archive(tmp_path, MINIMAL + bad)


# ── 面板三行（`[panel]`，P11 / G3）──────────────────────────


def test_缺省不生成三行键(tmp_path: Path) -> None:
    """没有 `[panel]` 的档案**不生成**那三个键（缺省 = 不写，不是"写三行空的"）。"""
    archive = _archive(tmp_path)
    assert archive.panel == ()
    built = modgen.build(archive)
    loc = built.files[next(rel for rel in built.files if rel.endswith("_l_english.yml"))]
    for slot, _suffix in modgen.PANEL_LINES:
        assert f"{archive.journal_entry.name}_{slot}" not in loc
    assert "没有** `[panel]`" in built.files[archive.doc_file]


def test_三行必须齐全(tmp_path: Path) -> None:
    """`[panel]` 是**整体**：缺一行就报错 —— 三行解释缺任何一行，G3 都复述不出来。

    这条是这一格存在的理由：把三行拆成三个键，就是为了让"缺哪一行"当场可见
    （揉进 `_reason` 里时，缺行是看不出来的）。
    """
    bad = MINIMAL + PANEL.replace("[panel.last_change]", "[panel.not_a_slot]")
    with pytest.raises(modgen.DataError, match="缺 `last_change`"):
        _archive(tmp_path, bad)


def test_三行键名由JE名派生并写进本地化与文档(tmp_path: Path) -> None:
    archive = _archive(tmp_path, MINIMAL + PANEL)
    built = modgen.build(archive)
    name = archive.journal_entry.name
    loc = built.files[next(rel for rel in built.files if rel.endswith("_l_english.yml"))]
    for _slot, suffix in modgen.PANEL_LINES:
        assert f"{name}_{suffix}:0" in loc
    doc = built.files[archive.doc_file]
    assert "面板三行" in doc
    for slot, key, why in archive.panel:
        assert key in doc
        assert why in doc, f"{slot} 的依据要进档案文档（P10：人读的那一份要能逐条查）"


def test_三行接进JE说明里上屏(tmp_path: Path) -> None:
    """**三行必须真的上屏**（阶段 6 的 G3）。

    引擎显示的是 `journal_entry.gui:742` 的 `text = "[JournalEntry.GetReason]"` ⇒ 读
    `<JE 名>_reason` 这条 loc；而 `<JE 名>_goal` 那一槽引擎会报
    `journal_entry_type.cpp:476 … has redundant loc`（实测），显不显示**没有把握**。
    所以三行文案要**也**接进 `_reason`（三个独立键照旧保留：能单独核对、将来接脚本化 GUI）。
    """
    archive = _archive(tmp_path, MINIMAL + PANEL)
    built = modgen.build(archive)
    loc = built.files[next(rel for rel in built.files if rel.endswith("_l_english.yml"))]
    reason = next(
        line for line in loc.splitlines() if f"{archive.journal_entry.name}_reason" in line
    )
    for slot, key, _why in archive.panel:
        value = next(entry.values["english"] for entry in archive.localization if entry.key == key)
        assert value in reason, f"{slot} 那一行没接进 JE 说明"
    # 拼接用的是**字面量** `\n\n`（两个字符）：写成真换行会把 yml 拆成多行、后几行没有 key
    assert reason.count("\\n\\n") >= len(archive.panel)
    assert len(loc.splitlines()) == len(archive.localization) + 2, (
        "每条 loc 一行（语言声明 + 注释头 + N 条）—— 多出来的行说明值里有真换行"
    )


def test_三行文案里不许有裸双引号(tmp_path: Path) -> None:
    """`.yml` 的值用双引号包裹，引擎对转义的支持没有实测证据 ⇒ 直接拒绝（P13）。"""
    bad = MINIMAL + PANEL.replace('english = "Goal line."', 'english = "Goal \\"quoted\\" line."')
    with pytest.raises(modgen.DataError, match="裸双引号"):
        _archive(tmp_path, bad)


def test_改一个数字往返就不一致(tmp_path: Path) -> None:
    """反向：产物与数据源只要差一处，比对就必须发现（否则闸门 ④ 是空转）。"""
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    broken = dict(built.files)
    broken[archive.modifier_file] = broken[archive.modifier_file].replace("-20", "-25")
    assert modgen.facts(archive) != modgen.readback(broken)


def test_readback不认坏掉的语法(tmp_path: Path) -> None:
    archive = _archive(tmp_path)
    built = modgen.build(archive)
    broken = {archive.journal_file: "je_sitai_t1_window = { \n"}
    with pytest.raises(modgen.DataError, match="解析失败"):
        modgen.readback(broken)
    assert built.files  # 基线产物本身是好的


def test_编号格式化不产生浮点噪声() -> None:
    """`-20` 不能写成 `-20.0`，`0.2` 不能写成 `0.20000000000000001`。"""
    assert modgen.num(-20) == "-20"
    assert modgen.num(0.2) == "0.2"
    assert modgen.num(-0.15) == "-0.15"
    assert modgen.num(10.0) == "10"


# ── 多档案第一步：schema v1（`[tempo]` 可选）与 mod 级元数据 ──
def test_第二份档案只加数据行就能编译(tmp_path: Path) -> None:
    """G-EXIT-1 的机械形式：两份数据源 → 一次构建 → 产物齐、mod 级产物只一份。"""
    a, b = _two_archives(tmp_path)
    built = modgen.build_all([a, b])
    assert set(built.archive_ids) == {"t1", "t2"}
    for archive in (a, b):
        for rel in modgen.archive_files(archive):
            assert rel in built.files, f"{archive.id} 少了 {rel}"
    # mod 级产物各一份：defines 由声明 tempo 的那份产出，metadata 由两份合成
    defines = [rel for rel in built.files if rel.startswith("common/defines/")]
    assert defines == [a.defines_file], defines
    assert [rel for rel in built.files if rel == modgen.METADATA_REL] == [modgen.METADATA_REL]
    assert b.tempo is None, "第二份档案不该复制一遍 [tempo]（它是 mod 级表）"


def test_加第二份档案不改第一份的产物(tmp_path: Path) -> None:
    """加档案**只增不改**：既有档案的产物必须逐字节不变（唯一例外是 mod 级元数据）。"""
    a, b = _two_archives(tmp_path)
    one = modgen.build_all([a])
    two = modgen.build_all([a, b])
    for rel, text in one.files.items():
        if rel == modgen.METADATA_REL:
            continue
        assert two.files[rel] == text, f"加第二份档案改动了 {rel}"
    assert set(two.files) == (
        set(modgen.archive_files(a)) | set(modgen.archive_files(b)) | {modgen.METADATA_REL}
    )


def test_单档案的两个入口共用一套组合规则(tmp_path: Path) -> None:
    """`build(a)` 就是 `build_all([a])` —— 免得两条路径悄悄分叉。"""
    a = _archive(tmp_path)
    assert modgen.build(a).files == modgen.build_all([a]).files


def test_mod级元数据汇总两份档案(tmp_path: Path) -> None:
    """一份 mod = 一份元数据：标题、身份、描述都由**全部**档案导出。"""
    a, b = _two_archives(tmp_path)
    payload = json.loads(modgen.build_all([a, b]).files[modgen.METADATA_REL])
    assert payload["id"] == "sitai.t1-t2", "档案 id 按字典序用 `-` 连接"
    assert "测试档案" in payload["name"]
    assert "第二档案" in payload["name"]
    assert payload["short_description"].count("测：这份档案修什么毛病") == 2
    assert payload["supported_game_version"] == "1.14.3"


def test_没有档案声明tempo报错(tmp_path: Path) -> None:
    """`defines` 是全局的：整份 mod 没有节奏段这件事必须显式，不能靠少一个产物表达。"""
    archive = _archive(tmp_path, MINIMAL.replace(TEMPO_BLOCK, ""))
    assert archive.tempo is None
    with pytest.raises(modgen.DataError, match=r"没有任何数据源声明 \[tempo\]"):
        modgen.build_all([archive])


def test_两份档案都声明tempo报错(tmp_path: Path) -> None:
    """两份都写 `[tempo]` → 报错并**点名两个文件**（否则谁生效取决于加载顺序）。"""
    a, b = _two_archives(tmp_path, tempo=True)
    assert a.tempo is not None
    assert b.tempo is not None
    with pytest.raises(modgen.DataError, match="只允许一份") as excinfo:
        modgen.build_all([a, b])
    assert "a.toml" in str(excinfo.value)
    assert "b.toml" in str(excinfo.value)


def test_游戏版本不一致报错(tmp_path: Path) -> None:
    """一份 mod 只有一个 `supported_game_version`：不一致说明数据源在骗人。"""
    a, b = _two_archives(tmp_path, game_version="1.15.3")
    with pytest.raises(modgen.DataError, match="game_version"):
        modgen.build_all([a, b])
