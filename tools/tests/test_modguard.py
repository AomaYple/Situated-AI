"""``pdx.modguard`` 的用例：五道闸门各自的**通过路径与失败路径**。

为什么每条失败路径都要有用例：门禁最危险的失效方式不是"报错太多"，
而是**该红的时候绿了** —— 一条写错的引用、一个不在命名空间里的文件、
一张没带 `possible` 门的牌，都会让整套闸门变成装饰（P13：失败要出声）。

原版侧一律用**合成的假游戏目录**（`tmp_path` 里按原版目录结构造几个文件），
所以这些用例不依赖真实游戏安装，CI 上也能跑。

真档案（`mod/data/ru_defeat.toml` + `mod/` 下的产物）另有一条用例覆盖：
它证明"当前这一份"是过的；上面那些证明"闸门真的会红"。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from pdx import modgen, modguard
from pdx.cli import app

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

runner = CliRunner()

#: 与 `test_modgen.py` 同构的最小数据源（刻意各写一份：两个测试文件互不依赖，
#: 一个改了不会静默影响另一个的口径）。
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
gate = "is_shown_when_inactive"
key = "c:RUS"
op = "?="
arg = "this"
why = "测：单国门"
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

[[localization]]
key = "sitai_t1_pressure"
english = "Test Pressure"
simp_chinese = "测试压力"
why = "测：修正的显示名"

[cards]
why = "测：本档案不递牌的理由"

[[references]]
kind = "trigger"
name = "legitimacy"
why = "测：这条引用在原版哪里用过"
[[references]]
kind = "effect"
name = "add_modifier"
why = "测：这条引用在原版哪里用过"
[[references]]
kind = "country_tag"
name = "RUS"
why = "测：国家 tag"
"""

#: 往数据源里加一张递牌（闸门 ③ 的通过/失败路径都要它）。
CARD = """
[[cards.items]]
name = "ai_strategy_sitai_t1_reform"
slot = "political"
weight = { amount = %d, why = "测：为什么是这个权重" }
why = "测：为什么要递这张牌"
%s
[[cards.items.fields]]
key = "change_law_chance"
amount = 0.5
why = "测：改革倾向"
"""

CARD_GATE = """[[cards.items.possible]]
key = "has_journal_entry"
arg = "je_sitai_t1_window"
why = "测：只在改革窗口开着时才参与抽签"
"""


# ── 合成的原版目录 ──────────────────────────────────────────
def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig", newline="\n")


def _fake_game(tmp_path: Path) -> Path:
    """按原版目录结构造一份最小的"游戏"。

    每一块都对应闸门 ② 的一个解析来源：修正池（含**字段名**）、JE 池、分组、词汇表、
    国家 tag、defines 命名空间、以及三个真实存在的图标文件。
    """
    game = tmp_path / "game"
    _write(
        game / "common" / "static_modifiers" / "00_vanilla.txt",
        "vanilla_pressure = {\n"
        "\tcountry_legitimacy_base_add = -10\n"
        "\tinterest_group_ig_landowners_pol_str_mult = 0.25\n"
        "\tcountry_loan_interest_rate_add = 0.2\n"
        "\tinterest_group_ig_industrialists_pol_str_mult = 0.5\n"
        "\tinterest_group_ig_intelligentsia_pol_str_mult = 0.5\n"
        "\tinterest_group_ig_devout_pol_str_mult = -0.25\n"
        "\tcountry_radicals_from_legitimacy_mult = 0.25\n"
        "\tcountry_loan_interest_rate_mult = 0.25\n"
        "}\n",
    )
    _write(game / "common" / "journal_entries" / "00_vanilla.txt", "je_vanilla = {\n}\n")
    _write(
        game / "common" / "journal_entry_groups" / "00_groups.txt",
        "je_group_internal_affairs = {\n}\nje_group_crises = {\n}\nje_group_qing = {\n}\nje_group_foreign_affairs = {\n}\n",
    )
    _write(
        game / "common" / "scripted_effects" / "00_vanilla_effects.txt",
        "vanilla_effect = {\n"
        "\tset_variable = { name = vanilla_memory value = 1 }\n"
        "\tadd_modifier = { name = vanilla_pressure years = 1 }\n"
        "}\n",
    )
    _write(
        game / "common" / "scripted_triggers" / "00_triggers.txt",
        "legitimacy = {\n}\nhas_variable = {\n}\ncountry_has_primary_culture = {\n}\nis_country_type = {\n}\n",
    )
    # 国家 tag：**数据源里声明过的每一个都要在这里**。闸门 ② 会拿产物里出现的 tag 去
    # 原版池里找 —— 少了哪个就报"原版里找不到这个国家 tag：X"（阶段 4 加第二份档案时
    # 真踩过：夹具只有 RUS，于是 tr_defeat 被正确地判红，修的是夹具而不是闸门；
    # 阶段 5 加 au/cn 两份时同样：补齐 AUS / CHI）。
    _write(
        game / "common" / "country_definitions" / "00_countries.txt",
        "RUS = {\n}\nTUR = {\n}\nAUS = {\n}\nCHI = {\n}\nEGY = {\n}\nPER = {\n}\n",
    )
    _write(
        game / "common" / "defines" / "00_ai.txt",
        "NAI = {\n\tCHANGE_STRATEGY_THRESHOLD = 100\n\tCHANGE_STRATEGY_INCREASE_WEEKLY_CHANCE = 20\n}\n",
    )
    _write(game / "common" / "ai_strategies" / "00_vanilla_strategy.txt", "ai_strategy_x = {\n}\n")
    for icon in (
        "gfx/interface/icons/timed_modifier_icons/modifier_statue_negative.dds",
        "gfx/interface/icons/timed_modifier_icons/modifier_lightbulb_positive.dds",
        "gfx/interface/icons/timed_modifier_icons/modifier_fire_negative.dds",
        "gfx/interface/icons/event_icons/event_portrait.dds",
        "gfx/interface/icons/event_icons/event_protest.dds",
        "gfx/interface/icons/event_icons/event_trade.dds",
        "gfx/interface/icons/objectives/great_game.dds",
        "gfx/interface/icons/timed_modifier_icons/modifier_coins_negative.dds",
    ):
        path = game / icon
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"DDS ")
    return game


def _context(
    tmp_path: Path,
    *,
    text: str = MINIMAL,
    game: Path | None = None,
    written: bool = True,
) -> modguard.Context:
    """造一个上下文：数据源写进 tmp、原版用合成目录、产物按需落盘。"""
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "t1.toml").write_text(text, encoding="utf-8", newline="\n")
    ctx = modguard.context(
        data_dir=data,
        root=tmp_path / "mod",
        game=game if game is not None else _fake_game(tmp_path),
    )
    if written:
        modgen.write(ctx.built, ctx.root)
    return ctx


def _patched(ctx: modguard.Context, rel: str, old: str, new: str) -> modguard.Context:
    """把产物里某处文本换掉，用来造"引用缺失"这类失败。"""
    files = dict(ctx.built.files)
    assert old in files[rel], f"{rel} 里没有 {old!r}"
    files[rel] = files[rel].replace(old, new)
    built = modgen.Built(archive_ids=ctx.built.archive_ids, files=files, numbers=ctx.built.numbers)
    return modguard.Context(
        archives=ctx.archives, built=built, root=ctx.root, game=ctx.game, data_dir=ctx.data_dir
    )


# ── 五道闸门：全过 ──────────────────────────────────────────
def test_五道闸门在合成语料上全过(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    report = modguard.run(ctx)
    assert [f.gate for f in report.findings] == [k for _n, k, _t in modguard.GATES]
    assert report.ok, modguard.format_report(report)
    assert not report.missing_precondition


def test_真档案的五道闸门结论可复算(tmp_path: Path) -> None:
    """当前这一份真档案（数据源 + 产物）+ 合成原版 = 全过。

    真游戏那一遍由 `v3 modguard` 在装了游戏的机器上跑；这条保证**闸门本身**
    在 CI 上也有一个"应当全过"的基准，否则红灯分不清是档案坏了还是闸门坏了。
    """
    game = _fake_game(tmp_path)
    ctx = modguard.context(game=game)
    assert modguard.run(ctx).ok, modguard.format_report(modguard.run(ctx))


def test_报告含总判定(tmp_path: Path) -> None:
    text = modguard.format_report(modguard.run(_context(tmp_path)))
    assert "总判定" in text
    assert "全过" in text


# ── ① 键 / 路径与原版不相交 ─────────────────────────────────
def test_闸门一在与原版同名的键上变红(tmp_path: Path) -> None:
    game = _fake_game(tmp_path)
    _write(
        game / "common" / "static_modifiers" / "00_vanilla.txt",
        "vanilla_pressure = {\n}\nsitai_t1_pressure = {\n}\n",
    )
    finding = modguard.gate_keys(_context(tmp_path, game=game))
    assert not finding.ok
    assert any("与原版重名" in line for line in finding.details)


def test_闸门一在路径相撞时变红(tmp_path: Path) -> None:
    game = _fake_game(tmp_path)
    _write(game / "common" / "static_modifiers" / "sitai_t1_pressure.txt", "x = {\n}\n")
    finding = modguard.gate_keys(_context(tmp_path, game=game))
    assert not finding.ok
    assert any("路径与原版相撞" in line for line in finding.details)


def test_闸门一在非平铺路径上变红(tmp_path: Path) -> None:
    """自建子目录在 1.14.3 实测不被引擎枚举 —— 产物放进去等于没写。"""
    ctx = _context(tmp_path)
    files = dict(ctx.built.files)
    files["common/ai_strategies/sub/sitai_t1_card.txt"] = "ai_strategy_sitai_t1_card = {\n}\n"
    built = modgen.Built(archive_ids=("t1",), files=files, numbers=())
    finding = modguard.gate_keys(
        modguard.Context(
            archives=ctx.archives, built=built, root=ctx.root, game=ctx.game, data_dir=ctx.data_dir
        )
    )
    assert not finding.ok
    assert any("平铺" in line or "两层" in line for line in finding.details)


def test_闸门一在命名空间越界时变红(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    files = dict(ctx.built.files)
    files["common/ai_strategies/zzz_card.txt"] = "ai_strategy_zzz = {\n}\n"
    built = modgen.Built(archive_ids=("t1",), files=files, numbers=())
    finding = modguard.gate_keys(
        modguard.Context(
            archives=ctx.archives, built=built, root=ctx.root, game=ctx.game, data_dir=ctx.data_dir
        )
    )
    assert not finding.ok
    assert any("命名空间" in line for line in finding.details)


def test_闸门一没游戏时报前置条件缺失(tmp_path: Path) -> None:
    """缺前置条件**不算通过**（P13）：静默跳过会被当成绿灯。"""
    ctx = _context(tmp_path, game=tmp_path / "没有游戏")
    finding = modguard.gate_keys(ctx)
    assert not finding.ok
    assert finding.precondition
    assert modguard.run(ctx).missing_precondition


def test_登记在案的覆盖不算冲突(tmp_path: Path) -> None:
    """`NAI` 与原版同名是**故意的**（按块 + 参数覆盖），理由写在 OVERRIDE_BLOCKS 里。"""
    finding = modguard.gate_keys(_context(tmp_path))
    assert finding.ok
    assert any("登记在案的覆盖" in line for line in finding.details)


# ── ② 引用完整性 ────────────────────────────────────────────
def test_闸门二在缺本地化键时变红(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        """
[[localization]]
key = "sitai_t1_pressure"
english = "Test Pressure"
simp_chinese = "测试压力"
why = "测：修正的显示名"
""",
        "",
    )
    finding = modguard.gate_refs(_context(tmp_path, text=text))
    assert not finding.ok
    assert any("缺本地化键" in line for line in finding.details)


def test_闸门二在图标不存在时变红(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        "gfx/interface/icons/event_icons/event_portrait.dds",
        "gfx/interface/icons/event_icons/不存在的图标.dds",
    )
    finding = modguard.gate_refs(_context(tmp_path, text=text))
    assert not finding.ok
    assert any("图标" in line for line in finding.details)


def test_闸门二在修正引用缺失时变红(tmp_path: Path) -> None:
    """产物里引用的静态修正必须真实存在 —— 拼错一个字母就是死引用。"""
    ctx = _context(tmp_path)
    broken = _patched(
        ctx, ctx.archives[0].effect_file, "name = sitai_t1_pressure", "name = sitai_t1_nope"
    )
    finding = modguard.gate_refs(broken)
    assert not finding.ok
    assert any("静态修正" in line for line in finding.details)


def test_闸门二在变量没定义时变红(tmp_path: Path) -> None:
    """JE 读的变量必须有人写过 —— 否则那条判据永远为假（静默失效）。"""
    ctx = _context(tmp_path)
    broken = _patched(ctx, ctx.archives[0].effect_file, "sitai_t1_memory", "sitai_t1_other")
    finding = modguard.gate_refs(broken)
    assert not finding.ok
    assert any("变量" in line for line in finding.details)


def test_闸门二在defines参数不存在时变红(tmp_path: Path) -> None:
    """阶段 2 的教训：覆盖的键名要每版本核对 —— 名字错了就是死配置。"""
    text = MINIMAL.replace("CHANGE_STRATEGY_THRESHOLD", "CHANGE_STRATEGY_NOPE")
    finding = modguard.gate_refs(_context(tmp_path, text=text))
    assert not finding.ok
    assert any("defines 参数不存在" in line for line in finding.details)


def test_闸门二在未知引用类别时报错(tmp_path: Path) -> None:
    text = MINIMAL.replace(
        'kind = "trigger"\nname = "legitimacy"', 'kind = "magic"\nname = "legitimacy"'
    )
    finding = modguard.gate_refs(_context(tmp_path, text=text))
    assert not finding.ok
    assert any("不认识的引用类别" in line for line in finding.details)


def test_闸门二在原版找不到声明式引用时变红(tmp_path: Path) -> None:
    text = MINIMAL.replace('name = "legitimacy"', 'name = "no_such_trigger"')
    finding = modguard.gate_refs(_context(tmp_path, text=text))
    assert not finding.ok
    assert any("原版里找不到" in line for line in finding.details)


def test_闸门二核对修正字段名(tmp_path: Path) -> None:
    """`modifier_field`：P10 的「数值必须引原版同类用法」要能被机器查。

    修正字段名写错一个字母是完全静默的 —— 修正照样挂上去，什么也不发生。
    """
    good = (
        MINIMAL
        + """
[[references]]
kind = "modifier_field"
name = "country_legitimacy_base_add"
why = "测：这个字段原版里用过"
"""
    )
    finding = modguard.gate_refs(_context(tmp_path, text=good))
    assert finding.ok, finding.details
    assert any("修正字段" in line for line in finding.details)

    bad = good.replace(
        'country_legitimacy_base_add"\nwhy = "测：这个字段原版里用过',
        'country_legitmacy_base_add"\nwhy = "测：拼错一个字母',
    )
    finding = modguard.gate_refs(_context(tmp_path, text=bad))
    assert not finding.ok
    assert any("修正字段名" in line for line in finding.details)


def test_修正字段池只收被赋值的字段(tmp_path: Path) -> None:
    """池子 = 原版 `static_modifiers` 里**被赋过值**的字段名（含嵌套块里的）。"""
    game = _fake_game(tmp_path)
    fields = modguard.modifier_fields(game)
    assert "country_legitimacy_base_add" in fields
    assert "vanilla_pressure" not in fields, "修正名本身不是字段名"


def test_闸门二在JE引用缺失时变红(tmp_path: Path) -> None:
    """加了牌之后，牌引用的 JE 必须存在 —— 本档案没牌，闸门仍要管这件事。"""
    ctx = _context(tmp_path, text=MINIMAL + CARD % (40, CARD_GATE))
    rel = ctx.archives[0].card_file(ctx.archives[0].cards[0])
    broken = _patched(ctx, rel, "je_sitai_t1_window", "je_sitai_t1_nope")
    finding = modguard.gate_refs(broken)
    assert not finding.ok
    assert any("不存在的 JE" in line for line in finding.details)


# ── ③ 稀释预算 ──────────────────────────────────────────────
def test_闸门三在零张牌时通过(tmp_path: Path) -> None:
    finding = modguard.gate_dilution(_context(tmp_path))
    assert finding.ok
    assert "0 张牌" in finding.headline


def test_闸门三在预算内的牌上通过(tmp_path: Path) -> None:
    """政治槽价格 33：权重 40 → 40/73 ≈ 54.8%，在 60% 预算之内。"""
    ctx = _context(tmp_path, text=MINIMAL + CARD % (40, CARD_GATE))
    finding = modguard.gate_dilution(ctx)
    assert finding.ok, finding.details
    assert "54.8%" in finding.headline


def test_闸门三在超预算的牌上变红(tmp_path: Path) -> None:
    """权重 250 → 250/283 ≈ 88%：等于我们替原版做决定（F2 要原版仍有发言权）。"""
    ctx = _context(tmp_path, text=MINIMAL + CARD % (250, CARD_GATE))
    finding = modguard.gate_dilution(ctx)
    assert not finding.ok
    assert any("超预算" in line or ">" in line for line in finding.details)


def test_闸门三对没有possible门的牌变红(tmp_path: Path) -> None:
    """没有门的牌在和平期也参与抽签，与出口判据「和平期占槽率 ≈ 0」直接冲突。"""
    ctx = _context(tmp_path, text=MINIMAL + CARD % (20, ""))
    finding = modguard.gate_dilution(ctx)
    assert not finding.ok
    assert any("possible" in line for line in finding.details)


def test_闸门三对未知槽位变红(tmp_path: Path) -> None:
    ctx = _context(
        tmp_path,
        text=(MINIMAL + CARD % (20, CARD_GATE)).replace('slot = "political"', 'slot = "military"'),
    )
    finding = modguard.gate_dilution(ctx)
    assert not finding.ok
    assert any("价格表" in line for line in finding.details)


def test_份额公式用阶段二的价格表() -> None:
    """P = W/(W+S)：政治 S≈33 / 外交 S≈107 / 行政 S≈690（阶段 2 实测）。"""
    assert modguard.card_share(33, "political") == pytest.approx(0.5)
    assert modguard.card_share(107, "diplomatic") == pytest.approx(0.5)
    assert modguard.card_share(690, "administrative") == pytest.approx(0.5)
    with pytest.raises(KeyError):
        modguard.card_share(10, "military")


# ── ④ 往返净度 ──────────────────────────────────────────────
def test_闸门四在往返一致时通过(tmp_path: Path) -> None:
    finding = modguard.gate_roundtrip(_context(tmp_path))
    assert finding.ok, finding.details


def test_闸门四在产物被改一个数字时变红(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    broken = _patched(ctx, ctx.archives[0].modifier_file, "-20", "-25")
    finding = modguard.gate_roundtrip(broken)
    assert not finding.ok
    assert any("读不到" in line or "多出" in line for line in finding.details)


def test_闸门四在产物语法坏掉时变红(tmp_path: Path) -> None:
    ctx = _context(tmp_path)
    files = dict(ctx.built.files)
    files[ctx.archives[0].journal_file] = "je_sitai_t1_window = { \n"
    built = modgen.Built(archive_ids=("t1",), files=files, numbers=())
    finding = modguard.gate_roundtrip(
        modguard.Context(
            archives=ctx.archives, built=built, root=ctx.root, game=ctx.game, data_dir=ctx.data_dir
        )
    )
    assert not finding.ok
    assert any("解析失败" in line for line in finding.details)


# ── ⑤ 生成可复现 + why 非空 ─────────────────────────────────
def test_闸门五在产物落盘后通过(tmp_path: Path) -> None:
    finding = modguard.gate_determinism(_context(tmp_path))
    assert finding.ok, finding.details


def test_闸门五在产物没落盘时变红(tmp_path: Path) -> None:
    finding = modguard.gate_determinism(_context(tmp_path, written=False))
    assert not finding.ok
    assert any("缺产物" in line for line in finding.details)


def test_闸门五在空why时变红(tmp_path: Path) -> None:
    """闸门重新读一遍原始数据源 —— 不信任"已经过一遍校验"的对象。

    这条路径是真实存在的：数据源在 `context()` 之后被改坏（编辑器保存、
    另一个进程重写），此时只有重新审计才发现得了。
    """
    ctx = _context(tmp_path)
    source = ctx.data_dir / "t1.toml"
    source.write_text(
        MINIMAL.replace('amount = -20\nwhy = "测：为什么取 -20"', "amount = -20"), encoding="utf-8"
    )
    finding = modguard.gate_determinism(ctx)
    assert not finding.ok
    assert any("没有 why" in line or "why" in line for line in finding.details)


# ── 选择与报告 ──────────────────────────────────────────────
def test_only支持编号键名与标题子串() -> None:
    assert modguard.resolve("") == ("keys", "refs", "dilution", "roundtrip", "determinism")
    assert modguard.resolve("3") == ("dilution",)
    assert modguard.resolve("keys") == ("keys",)
    assert modguard.resolve("往返") == ("roundtrip",)
    assert modguard.resolve("拼错的") == ()


def test_only拼错时报错而不是空跑(tmp_path: Path) -> None:
    """拼错一个字母就"全部通过"是这类门禁最会骗过 CI 的失效方式。"""
    with pytest.raises(ValueError, match="没有匹配的闸门"):
        modguard.run(_context(tmp_path), only="keyz")


def test_only编号不会被标题里的数字带偏() -> None:
    """③ 的标题里写着「按阶段 2 的价格表定价」—— 单级子串匹配会让 `--only 2`
    一次跑两道闸门，而用法本身不报错（静默多跑 = 结论对不上号）。"""
    assert modguard.resolve("2") == ("refs",)
    assert modguard.resolve("①") == ("keys",)
    assert modguard.resolve("dilution") == ("dilution",)


def test_只跑一道闸门时报告里只有那一道(tmp_path: Path) -> None:
    report = modguard.run(_context(tmp_path), only="4")
    assert [f.gate for f in report.findings] == ["roundtrip"]


# ── CLI ─────────────────────────────────────────────────────
def test_cli_modgen摘要() -> None:
    result = runner.invoke(app, ["modgen"])
    assert result.exit_code == 0, result.output
    assert "ru_defeat" in result.output


def test_cli_modgen核对入库产物() -> None:
    """`--check` 是"产物是不是生成出来的"那条命令 —— 入库状态必须干净。"""
    result = runner.invoke(app, ["modgen", "--check"])
    assert result.exit_code == 0, result.output
    assert "一致" in result.output


def test_cli_modgen列出依据() -> None:
    result = runner.invoke(app, ["modgen", "--why"])
    assert result.exit_code == 0, result.output
    assert "每个数字与它的依据" in result.output


def test_cli_modgen两个模式互斥() -> None:
    result = runner.invoke(app, ["modgen", "--write", "--check"])
    assert result.exit_code == 2


def test_cli_modguard只跑一道(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI 侧不读真游戏：把 context 换成合成语料（CI 上没有游戏）。"""
    ctx = _context(tmp_path)
    monkeypatch.setattr(modguard, "context", lambda **_kw: ctx)
    result = runner.invoke(app, ["modguard", "--only", "3"])
    assert result.exit_code == 0, result.output
    assert "稀释预算" in result.output


def test_cli_modguard在原版缺失时报退出码二(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """前置条件缺失 = 2，不是 0：跳过的检查不能被当成绿灯。"""
    ctx = _context(tmp_path, game=tmp_path / "没有游戏")
    monkeypatch.setattr(modguard, "context", lambda **_kw: ctx)
    result = runner.invoke(app, ["modguard", "--only", "1"])
    assert result.exit_code == 2, result.output
    assert "前置条件缺失" in result.output


def test_cli_modguard在闸门不过时报一(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _context(tmp_path, written=False)
    monkeypatch.setattr(modguard, "context", lambda **_kw: ctx)
    result = runner.invoke(app, ["modguard", "--only", "5"])
    assert result.exit_code == 1, result.output


def test_cli_modguard拼错only时报退出码二(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _context(tmp_path)
    monkeypatch.setattr(modguard, "context", lambda **_kw: ctx)
    result = runner.invoke(app, ["modguard", "--only", "keyz"])
    assert result.exit_code == 2, result.output
