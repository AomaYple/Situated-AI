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


def _write_source(tmp_path: Path, text: str = MINIMAL, name: str = "t1.toml") -> Path:
    base = tmp_path / "data"
    base.mkdir(parents=True, exist_ok=True)
    path = base / name
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _archive(tmp_path: Path, text: str = MINIMAL) -> modgen.Archive:
    return modgen.load_data(_write_source(tmp_path, text))


# ── 数据源解析 ──────────────────────────────────────────────
def test_解析真实档案的关键条目() -> None:
    """第一份档案（俄罗斯 · 战败求存）必须能被解析出它该有的东西。

    这条同时钉住"设计意图没被改掉"：变量名、修正名、JE 名、两个节奏键、
    以及"一张牌都不递"（F5）。
    """
    archive = modgen.load_data(modgen.DATA_DIR / "ru_defeat.toml")
    assert archive.id == "ru_defeat"
    assert archive.country == "RUS"
    assert archive.memory.variable == "sitai_ru_defeat_memory"
    assert archive.memory.effect == "sitai_ru_defeat_shock"
    assert archive.pressure.name == "sitai_ru_defeat_pressure"
    assert archive.journal_entry.name == "je_sitai_ru_reform_window"
    assert archive.journal_entry.group == "je_group_internal_affairs"
    assert {p.key for p in archive.tempo.keys} == {
        "CHANGE_STRATEGY_THRESHOLD",
        "CHANGE_STRATEGY_INCREASE_WEEKLY_CHANCE",
    }
    assert archive.cards == (), "本档案刻意不递牌（F5：A 级已表达完整条链路）"
    assert len(archive.localization) == 3


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


def test_多份档案的产物路径冲突要报错(tmp_path: Path) -> None:
    """两份档案写同一个产物路径 = 谁在起作用变成无解的问题，必须当场红。"""
    _write_source(tmp_path, MINIMAL, name="a.toml")
    _write_source(tmp_path, MINIMAL, name="b.toml")
    archives = modgen.load_all(tmp_path / "data")
    assert len(archives) == 2
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
