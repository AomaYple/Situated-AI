"""``pdx.ab_probe`` 的用例：臂阶梯探针是**生成**的，生成物本身要被钉住。

重点不是"文件写出来了"，而是五件事：

* **阶梯只有一处定义**（`LADDER`）：探针文本、分析器的角色表、文档都从它派生；
* **换臂是幂等的**：`stage` 单调递增，每个效果只施加一次（重复脉冲、读档、重点决议
  都不能把同一处输入叠两遍）；
* **两处输入分开施加**：B 段只调冲击、B2 段才调改革侧输入 —— 合在一起就分不出
  是哪一处起了作用；
* **0 张牌**（F5：能改世界就不占槽）；
* **生成物能被仓库自己的解析器读懂**，且引用的效果名与**数据源**同源（P9）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pdx import ab_probe, config, modgen
from pdx.parser import parse_text

if TYPE_CHECKING:
    from collections.abc import Iterable

pytestmark = pytest.mark.unit

_EMPTY_GAME = Path("Z:/不存在的游戏目录")

_EFFECTS = "common/scripted_effects/zz_probe_ab_effects.txt"
_ON_ACTIONS = "common/on_actions/zz_probe_ab_on_actions.txt"
_DECISIONS = "common/decisions/zz_probe_ab_decisions.txt"


def _files() -> dict[str, str]:
    return ab_probe.build(game=_EMPTY_GAME).files


def _target() -> ab_probe.ProbeTarget:
    """当前探针实际盯的那份档案（**从数据源读**）—— 断言一律对着它，不写死国家名。"""
    target = ab_probe.load_target()
    assert target is not None, "读不到 mod/data 里的档案"
    return target


def _code(text: str) -> str:
    """去掉注释行后的**代码**（注释里会解释规则，不该被当成实现来断言）。"""
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))


def _block(code: str, name: str) -> str:
    """取一个顶层定义的**全文**（从 `name = {` 到行首那个收尾的 `}`）。

    不能用 `split("}")[0]`：块里还有嵌套的 `{ … }`（`set_variable` 之类），
    切在第一个 `}` 上会把定义截掉一半。
    """
    start = code.index(f"{name} = {{")
    end = code.index("\n}", start)
    return code[start:end]


def _date(text: str) -> tuple[int, int, int]:
    """`"1841.6.1"` → `(1841, 6, 1)`（比字符串比大小可靠：'1836.10.1' < '1836.6.1'）。"""
    year, month, day = (int(part) for part in text.strip('"').split("."))
    return (year, month, day)


# ── 阶梯的定义（唯一一处）────────────────────────────────────


def test_阶梯是三臂且起始月单调() -> None:
    """A → B → B2 的起始月必须递增，且只有第一臂没有效果（对照组什么都不做）。"""
    assert ab_probe.ROLES == ("A", "B", "B2")
    assert ab_probe.ARM_START == {"A": 1, "B": 13, "B2": 37}
    starts = [step.at_month for step in ab_probe.LADDER]
    assert starts == sorted(starts)
    assert ab_probe.LADDER[0].effect is None
    assert [step.effect for step in ab_probe.LADDER[1:]] == [
        ab_probe.SHOCK_EFFECT,
        ab_probe.INPUT_EFFECT,
    ]


def test_探针引用的效果与数据源同源() -> None:
    """P9：探针调用的效果名/修正名必须与 `mod/data/*.toml` 生成出来的完全一致。

    写错一个字母的表现是 `Unknown effect`（引擎只在 error.log 里说一句），
    而那正是开局自检要抓的东西 —— 不如在这里就钉住。
    """
    archive = modgen.load_data(modgen.DATA_DIR / "ru_defeat.toml")
    assert archive.memory.effect == ab_probe.SHOCK_EFFECT
    assert archive.memory.variable == ab_probe.SHOCK_VAR
    assert archive.inputs is not None, "数据源里必须有第二处理段（B2 靠它）"
    assert archive.inputs.effect == ab_probe.INPUT_EFFECT
    assert archive.inputs.name == ab_probe.INPUT_MODIFIER


# ── 效果文件：武装 + 阶梯（幂等）──────────────────────────────


def test_效果文件里不能出现on_action包装() -> None:
    """阶段 2 的挂载点事故：效果文件里的 `effect = {` 会让定义整段作废、脚本侧毫无报错。"""
    assert "effect = {" not in _code(_files()[_EFFECTS])


def test_武装效果写A段标记并把计数器清零() -> None:
    code = _code(_files()[_EFFECTS])
    arm = _block(code, "zz_probe_ab_arm")
    assert "ZZPROBE AB;RUN;A" in arm
    assert f"set_variable = {{ name = {ab_probe.MONTH_VAR} value = 0 }}" in arm
    assert f"set_variable = {{ name = {ab_probe.STAGE_VAR} value = 1 }}" in arm


def test_阶梯按月推进且带阶段守卫生效一次() -> None:
    """幂等是硬要求：`stage <= N` 的守卫保证每个效果**只施加一次**。"""
    text = _files()[_EFFECTS]
    code = _code(text)
    ladder = code.split("zz_probe_ab_ladder = {")[1]
    assert f"has_variable = {ab_probe.STAGE_VAR}" in ladder  # 没被武装就不动
    target = _target()
    for index, step in enumerate(ab_probe.ladder_for(target)[1:], start=1):
        assert f"var:{ab_probe.STAGE_VAR} <= {index}" in ladder
        assert f"var:{ab_probe.MONTH_VAR} >= {step.at_month}" in ladder
        assert f"ZZPROBE AB;RUN;{step.role}" in ladder
        # 换臂那一月：先把 stage 推进，再施加效果（否则下一月会再施加一次）
        assert ladder.index(f"value = {index + 1}") < ladder.index(f"{step.effect} = yes")


def test_月份计数器只由自励与决议推进() -> None:
    """⚠️ **月份 `+1` 只能有一处**（2026-09-22 改）：从前它在阶梯里，而阶梯要靠决议武装 ——
    观察者局里决议点不了 ⇒ 月份永远不动 ⇒ 整条臂阶梯一次都不走（阶段 3 的结构性阻断）。
    现在推进挪进 `zz_probe_ab_selfarm`，阶梯只读月份。两处都自增会让月份走两倍快。
    """
    code = _code(_files()[_EFFECTS])
    bump = f"change_variable = {{ name = {ab_probe.MONTH_VAR} add = 1 }}"
    assert code.count(bump) == 1, "月份自增必须只有一处"
    selfarm = code.split("zz_probe_ab_selfarm = {")[1].split("zz_probe_ab_ladder = {")[0]
    assert bump in selfarm
    assert bump not in code.split("zz_probe_ab_ladder = {")[1]


def test_自励只对AI生效且让决议优先() -> None:
    """自励是**观察者局**的入口；玩家自己掌权时它必须完全不介入（决议是唯一入口）。"""
    selfarm = _code(_files()[_EFFECTS]).split("zz_probe_ab_selfarm = {")[1]
    assert "is_ai = yes" in selfarm
    assert f"NOT = {{ has_variable = {ab_probe.MANUAL_VAR} }}" in selfarm
    # 决议那边要写下"我武装过"的标记，否则自励会盖掉玩家那一路
    arm = _code(_files()[_EFFECTS]).split("zz_probe_ab_arm = {")[1].split("zz_probe_ab_selfarm")[0]
    assert f"set_variable = {{ name = {ab_probe.MANUAL_VAR} value = 1 }}" in arm


def test_自励的每一格都幂等且按月份排序() -> None:
    selfarm = _code(_files()[_EFFECTS]).split("zz_probe_ab_selfarm = {")[1]
    target = _target()
    steps = [step for step in ab_probe.ladder_for(target)[1:] if step.effect]
    months = [step.at_month for step in steps]
    assert months == sorted(months), "自励的月份必须单调，否则顺序写反就读不懂"
    for index, step in enumerate(steps, start=1):
        month, effect = step.at_month, step.effect
        assert f"var:{ab_probe.SELFARM_VAR} < {index}" in selfarm
        assert f"var:{ab_probe.MONTH_VAR} >= {month}" in selfarm
        assert f"{effect} = yes" in selfarm


def test_每月都记当前政治牌() -> None:
    """B53：牌才是"动不动手"的闸门 ⇒ 牌必须是**逐月的行为层读数**，不许从别处反推。"""
    code = _code(_files()[_ON_ACTIONS])
    for name in ab_probe.POLITICAL_STRATEGIES:
        assert f"has_strategy = {name}" in code, name
        assert f"ZZPROBE AB;STRATEGY;{name};" in code, name


def test_每月都记立法开没开() -> None:
    """「牌换了法不换」的三个候选（缺政府支持 / 怕革命 / 权重不够）在
    「每月只记法律名」的读数下**长得一模一样** ⇒ 必须直接记 `is_enacting_law`。

    它把「从未开立法」与「开了没成」分开，是三选一的分辨器。
    ⚠️ 而**没有「任意法」的通用写法**（exe 检索 5 个候选名全 0 命中）⇒ 只能逐条问，
    所以这里钉住"每条候选法都要问一遍"，以及"全没推时也要留一行 `none`"。
    """
    code = _code(_files()[_ON_ACTIONS])
    assert ab_probe.ENACT_LAWS, "候选法清单不能空 —— 空了这条读数就没意义"
    for law in ab_probe.ENACT_LAWS:
        assert f"is_enacting_law = law_type:{law}" in code, law
    assert "ZZPROBE AB;ENACT;none;" in code, "全没推时也要留一行（否则分不清'没记'与'没开'）"
    # 两条土地法是这条链的正主，必须在候选表里
    assert "law_tenant_farmers" in ab_probe.ENACT_LAWS
    assert "law_commercialized_agriculture" in ab_probe.ENACT_LAWS


def test_每月都记政府在谁手里() -> None:
    """若「缺政府支持」那一支成立，就得能看见政府在谁手里。"""
    code = _code(_files()[_ON_ACTIONS])
    for name, short in ab_probe.GOVERNMENT_IGS:
        assert f"ig:{name} ?= {{ is_in_government = yes }}" in code, name
        assert f"ZZPROBE AB;GOV;{short};" in code, short


def test_clout_档位名是两位百分数() -> None:
    assert ab_probe.clout_band_name(0.03) == "b03"
    assert ab_probe.clout_band_name(0.18) == "b18"
    assert ab_probe.clout_band_name(0.25) == "b25"
    assert [ab_probe.clout_band_name(b) for b in ab_probe.CLOUT_BANDS] == [
        "b03",
        "b08",
        "b12",
        "b18",
        "b25",
    ]


def test_每月都记入阁距离() -> None:
    """`is_in_government` 只有真/假，**看不出离入阁有多远** ⇒ 用 `ig_clout` 夹逼成档。

    没有这一格，"再加一点压力够不够"这个问题在二元读数下无法回答
    （阶段 3 重做的结论正卡在这里）。
    """
    code = _code(_files()[_ON_ACTIONS])
    # 写成 "相等" 而不是 `sorted(...) == CLOUT_BANDS`：这里要断言的就是**顺序**，
    # 反转过来会让失败信息难读（SIM300 的默认建议对"对称比较"是过度约束）。
    assert ab_probe.CLOUT_BANDS == tuple(sorted(ab_probe.CLOUT_BANDS)), "档位必须升序"  # noqa: SIM300
    for name, short in ab_probe.CLOUT_IGS:
        for band in ab_probe.CLOUT_BANDS:
            label = ab_probe.clout_band_name(band)
            assert f"ig:{name} ?= {{ ig_clout >= {band} }}" in code, (name, band)
            assert f"ZZPROBE AB;CLOUT;{short};{label};" in code, (name, label)
    # 改革派两个 IG 必须在表里（地主留作对照）
    shorts = {short for _name, short in ab_probe.CLOUT_IGS}
    assert {"intelligentsia", "industrialists", "landowners"} <= shorts


def test_生成物的大括号是配平的() -> None:
    """CLOUT 那一格是**成对生成**的（`if = {` + `}`）—— 用 f-string 拼多行时最容易漏掉收尾。

    实测踩过（2026-09-22）：把 `if` 与 `}` 写在同一个 f-string 里再靠 `\\n` 拼，
    生成出来的 `}` 会落到错误的位置，整个 on_action 的块结构就散了。
    """
    for rel in (_ON_ACTIONS, _EFFECTS):
        text = _files()[rel]
        assert text.count("{") == text.count("}"), f"{rel} 的大括号不配平"


def test_自报里不做整体缩进重排() -> None:
    """PDX 脚本对缩进不敏感，但**嵌套块被整体右移**会生成"双倍缩进"，读起来像语法错误。

    实测（2026-09-22）：三槽自报链以前被 `.replace("\\n" + tab*2, "\\n" + tab*3)` 整体
    右移 → `if` 里的 `if` 变成两层缩进叠在一起。

    判据形状：**每一层缩进都必须真的对应一层块**。这里用"三槽自报链里不许出现三层以上缩进"
    来钉 —— 那条链最深就是 `guarded(if)` 里一层 `if`，所以 4 个 tab 是它的上限
    （`ENACT` 那一段有个 `OR` 会到 6 个 tab，那是**真的**四层嵌套，不在本判据范围内）。
    """
    text = _files()[_ON_ACTIONS]
    start = text.index("# ② 再走臂阶梯")
    end = text.index("# ④ 当前挂着的政治牌")
    chain_section = text[start:end]
    assert "\t\t\t\t\t" not in chain_section, "三槽自报链里出现 5 层缩进 ⇒ 多半又整体重排了"


def test_两处输入各调各的效果() -> None:
    """B 段只调冲击、B2 段才调改革侧输入 —— 分开才能把差分归因到某一处。"""
    target = _target()
    ladder = _code(_files()[_EFFECTS]).split("zz_probe_ab_ladder = {")[1]
    b_block = ladder.split('RUN;B"')[1].split('RUN;B2"')[0]
    b2_block = ladder.split('RUN;B2"')[1]
    assert f"{target.shock_effect} = yes" in b_block
    assert f"{target.input_effect} = yes" not in b_block
    assert f"{target.input_effect} = yes" in b2_block
    assert f"{target.shock_effect} = yes" not in b2_block


# ── 决议：一个就够 ───────────────────────────────────────────


def test_只有一个决议且远程作用于主角国家() -> None:
    code = _code(_files()[_DECISIONS])
    defined = re.findall(r"(?m)^(\w+) = \{", code)
    assert defined == ["zzprobe_ab_apply"], "只该有一个决议（点一次武装整条阶梯）"
    assert "is_shown = { always = yes }" in code  # 对任何玩家可见（玩家演旁观者）
    assert f"c:{_target().subject} ?= {{" in code  # 效果**远程**作用于主角国家
    assert "ai_chance = { value = 0 }" in code
    assert "zz_probe_ab_arm = yes" in code


def test_探针不新增任何牌() -> None:
    """F5：本档案 0 张牌 —— 探针也不许偷偷加。"""
    for rel, text in _files().items():
        assert "ai_strategy_sitai_" not in text, rel


# ── 月度自报：只记俄罗斯，且换臂在自报之前 ───────────────────


def test_on_actions引用的tag都在同一文件里定义() -> None:
    code = _code(_files()[_ON_ACTIONS])
    defined = set(re.findall(r"(?m)^(\w+) = \{", code))
    referenced: set[str] = set()
    for match in re.finditer(r"on_actions = \{([^}]*)\}", code):
        referenced |= set(match.group(1).split())
    assert referenced, "一个钩子都没挂上"
    assert referenced <= defined, sorted(referenced - defined)
    # 起点是"玩家点决议"，**不在开局自动挂**（否则大厅/读档阶段也会算进 A 臂）
    assert "on_game_started" not in code


def test_阶梯排在自报之前() -> None:
    """换臂那一月必须算进新臂 —— RUN 行要排在同月的 SHOCK/JE/LAW 之前。"""
    text = _files()[_ON_ACTIONS]
    assert text.index("zz_probe_ab_ladder = yes") < text.index("ZZPROBE AB;SHOCK;")
    assert text.index("zz_probe_ab_ladder = yes") < text.index("ZZPROBE AB;JE;")
    assert text.index("zz_probe_ab_ladder = yes") < text.index("ZZPROBE AB;POLI;")


def test_行为层与策略层都记了且都只在主角国家() -> None:
    target = _target()
    text = _files()[_ON_ACTIONS]
    assert f"has_journal_entry = {target.journal_entry}" in text  # 行为层①
    for law in ab_probe.LAWS:  # 行为层②
        assert f"has_law = law_type:{law}" in text
    for short in ("POLI", "ADMI", "DIPL"):  # 策略层
        assert f"ZZPROBE AB;{short};" in text
    # 策略层也要在守卫内（否则全世界每月刷 3 行日志）
    assert text.index(f"c:{target.subject} ?= this") < text.index("ZZPROBE AB;POLI;")
    # 玩家是谁必须能被诊断出来（开错国家时开局一分钟就知道）
    assert "ZZPROBE AB;PLAYER;yes;" in text
    # 两处输入各一行"在/不在"自检（B2 段少了它，第③节的无差分会被误读）
    assert f"has_variable = {target.shock_variable}" in text
    assert f"has_modifier = {target.input_modifier}" in text
    for kind in ("SHOCK", "INPUT"):
        assert f"ZZPROBE AB;{kind};yes;" in text
        assert f"ZZPROBE AB;{kind};no;" in text
    # 诊断行：合法性落在哪一档（五档夹逼）
    for band in ("b55", "b60", "b70", "b75", "b80"):
        assert f"ZZPROBE AB;LEG;{band};" in text


# ── scripted_tests 套件（引擎侧判定）────────────────────────


def test_套件判据贴合我们的两条判据() -> None:
    """success = 开窗 / 换法；fail = 到日期仍未发生（不是"跳过"）。"""
    target = _target()
    text = _files()[ab_probe.SUITE_REL]
    assert f"has_journal_entry = {target.journal_entry}" in text
    assert f"NOT = {{ has_law = law_type:{target.reform_law} }}" in text, (
        "行为层②必须按**本档案声明的**那条法判（B80）—— 写死 `law_serfdom` 时，"
        "对没有农奴制的国家它立刻为真，会报出假的「法律换了」"
    )
    assert f"c:{target.subject} ?= {{" in text
    assert text.count("run_count = 1") == 2
    assert text.count("acceptable_fail_rate = 0.0") == 2
    assert text.count("game_date >") == 2


def test_没声明盯哪条法就不产出那条判据() -> None:
    """**没查实就不判**（B80）：奥斯曼/埃及的历史文件里没有土地法那一组（实测）⇒
    套件里干脆不出现 `law_changed`，而不是写一条会对它们立刻为真的判据。
    """
    import dataclasses

    plain = dataclasses.replace(_target(), reform_law="")
    built = ab_probe.build(game=_EMPTY_GAME, target=plain)
    suite = built.files[ab_probe.SUITE_REL]
    assert "law_changed" not in suite
    assert "没有" in suite, "要留一句注释说明为什么没有它"
    assert "reform_law" in suite, "注释里要点名要加什么"
    assert suite.count("run_count = 1") == 1, "只该剩开窗那一条"


def test_探针把盯的档案写进日志() -> None:
    """分析器靠 `ZZPROBE AB;TARGET;<档案 id>` 认主语（B80）。

    为什么不能靠国名：自报行的最后一格是**本地化国名**（实测是「波斯」），不是 tag；
    而 `[This.GetTag]` 不是合法的 loc 命令。探针本来就是为某一份档案生成的，
    所以让它直接写那个常量。
    """
    target = _target()
    effects = _files()[_EFFECTS]
    assert f"ZZPROBE AB;TARGET;{target.archive_id}" in effects
    other = ab_probe.load_target("cn_intervention")
    assert other is not None
    rebuilt = ab_probe.build(game=_EMPTY_GAME, target=other)
    assert f"ZZPROBE AB;TARGET;{other.archive_id}" in rebuilt.files[_EFFECTS]


def test_套件的fail日期早于last_date() -> None:
    """到 last_date 两个触发器都没命中 → 判「跳过」：fail 的日期必须更早。

    否则"没发生"永远不会被报成失败 —— 而那正是我们要判的那件事。
    """
    text = _files()[ab_probe.SUITE_REL]
    last = _date(re.search(r'last_date = ("[^"]+")', text).group(1))  # type: ignore[union-attr]
    fails = [_date(value) for value in re.findall(r'game_date > ("[^"]+")', text)]
    assert fails, "一条 fail 判据都没有"
    assert all(moment < last for moment in fails), (fails, last)


def test_原版套件都被收敛覆盖() -> None:
    """引擎会跑 tools/scripted_tests/ 下的**每一份**套件：原版那几套跑到 1870–1900 年。"""
    files = _files()
    for name in ab_probe.VANILLA_SUITES:
        rel = f"tools/scripted_tests/{name}.txt"
        assert rel in files
        text = files[rel]
        last = _date(re.search(r'last_date = ("[^"]+")', text).group(1))  # type: ignore[union-attr]
        assert last <= _date('"1836.2.1"'), f"{name} 的 last_date 还是太晚：{last}"
        assert "tests = {\n}\n" in text, f"{name} 的 tests 该清空"


# ── 写盘、部署、摘要 ─────────────────────────────────────────


def test_写盘带BOM且能被解析器读懂(tmp_path: Path) -> None:
    ab_probe.write(root=tmp_path, game=_EMPTY_GAME)
    seen = 0
    for path in sorted(tmp_path.rglob("*")):
        if not path.is_file():
            continue
        seen += 1
        if path.suffix in {".txt", ".yml"}:
            assert path.read_bytes().startswith(b"\xef\xbb\xbf"), path.name
            if path.suffix == ".txt":
                parsed = parse_text(path.read_text(encoding="utf-8-sig"), path=str(path))
                assert parsed.top_assignments, path.name
        elif path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
    assert seen == len(_files())


def test_部署会连同真mod一起启用(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """真 mod 的**目录名由档案 id 拼出来**（P9）—— 从前写死 `sitai_ru_defeat`，
    加第二份档案时就会装错目录，而"装错目录"的表现是"探针报 Unknown effect"，
    看起来像效果名写错了。
    """
    seen: list[list[str]] = []
    target = ab_probe.load_target()
    assert target is not None, "仓库里必须能读到档案数据源"

    def fake_set(paths: Iterable[Path | str], **_kw: object) -> None:
        seen.append([str(p) for p in paths])

    monkeypatch.setattr(ab_probe.experiments, "set_enabled_mods", fake_set)
    root = tmp_path / "mod"
    (root / target.dir_name).mkdir(parents=True)  # 假装真 mod 已装
    dest = ab_probe.deploy(root=tmp_path / "src", target=root, game=_EMPTY_GAME)
    assert dest == root / ab_probe.PROBE_MOD
    assert (dest / "common" / "on_actions" / "zz_probe_ab_on_actions.txt").is_file()
    assert (dest / "tools" / "scripted_tests" / "sitai_ab.txt").is_file()
    assert seen[-1] == [str(dest), str(root / target.dir_name)]


def test_摘要写清整条阶梯() -> None:
    text = ab_probe.summary(ab_probe.build(game=_EMPTY_GAME))
    for role in ab_probe.ROLES:
        assert role in text
    assert "第 13 月起" in text
    assert "第 37 月起" in text


# ── 探针盯谁：从**数据源**读，不手抄（P9）─────────────────────


def test_目标从数据源读出来() -> None:
    """探针原来硬编码 `SUBJECT = "RUS"` / JE 名 / 效果名 —— 加第二份档案时会漂。

    现在全部由 `modgen` 从 `mod/data/*.toml` 编译出来，这条用例钉住"读得到、且与档案一致"。
    """
    from pdx import modgen

    target = ab_probe.load_target()
    assert target is not None
    archives = modgen.load_all()
    first = archives[0]
    assert target.subject == first.country, "默认目标 = 数据源里的第一份档案"
    assert target.journal_entry == first.journal_entry.name
    assert target.shock_effect == first.memory.effect
    assert target.shock_variable == first.memory.variable
    assert first.inputs is not None
    assert target.input_effect == first.inputs.effect
    assert target.dir_name == "-".join(archive.id for archive in archives)


def test_可以点名要哪一份档案() -> None:
    """阶段 5 起 `mod/data/` 里有多份档案 ⇒ 探针必须能**显式选一份**。

    点名了却没有就**报错**，不许"回落到第一份" —— 那会让人以为探针盯的是 A、实际盯的是 B。
    """
    from pdx import modgen

    wanted = modgen.load_all()[0].id
    picked = ab_probe.load_target(archive_id=wanted)
    assert picked is not None
    assert picked.archive_id == wanted
    with pytest.raises(KeyError, match="没有档案"):
        ab_probe.load_target(archive_id="zzz_不存在")


def test_生成的探针里不含写死的国家名() -> None:
    """判据是**反面**：产物里出现别的国家的 tag 就说明有一条路没走 target。"""
    target = _target()
    files = ab_probe.build(game=_EMPTY_GAME).files
    on_actions = files[_ON_ACTIONS]
    assert f"c:{target.subject}" in on_actions  # 守卫就是这一份档案的国家
    assert f"has_journal_entry = {target.journal_entry}" in on_actions
    # 自报用的判据必须是**数据源里的那一份**（变量名 / 修正名）
    assert f"has_variable = {target.shock_variable}" in on_actions
    assert f"has_modifier = {target.input_modifier}" in on_actions
    # 要调的那两个效果名出现在阶梯里（`on_actions` 只负责挂钩与自报）
    effects = files[_EFFECTS]
    assert f"{target.shock_effect} = yes" in effects
    assert f"{target.input_effect} = yes" in effects


def test_造别的国家的探针只需换一个_target() -> None:
    """G-EXIT-1 的口径：加一处境 = 加数据行，**Python 侧 0 行改动**。

    这里用一个合成的 target 证明"换国家"确实只是换一个值（不需要改生成器）。
    """
    custom = ab_probe.ProbeTarget(
        dir_name="t9",
        subject="AUS",
        journal_entry="je_sitai_t9_window",
        shock_effect="sitai_t9_shock",
        shock_variable="sitai_t9_memory",
        input_effect="sitai_t9_reform_input",
        input_modifier="sitai_t9_reform_inputs",
        archive_id="t9",
    )
    files = ab_probe.build(game=_EMPTY_GAME, target=custom).files
    assert "c:AUS" in files[_ON_ACTIONS]
    assert "c:RUS" not in files[_ON_ACTIONS]
    assert "je_sitai_t9_window" in files[_ON_ACTIONS]
    assert "has_variable = sitai_t9_memory" in files[_ON_ACTIONS], "冲击自检要问**这份档案**的变量"
    assert "has_variable = sitai_ru_defeat_memory" not in files[_ON_ACTIONS]
    assert "c:AUS" in files[ab_probe.SUITE_REL]
    assert "c:AUS" in files["common/decisions/zz_probe_ab_decisions.txt"]


def test_读不到数据源时不猜一个国家名(monkeypatch: pytest.MonkeyPatch) -> None:
    """P13：读不到就报错 —— 拿猜出来的国家名生成探针，会让"它在盯谁"变成看不出来的错。"""
    monkeypatch.setattr(ab_probe, "load_target", lambda: None)
    with pytest.raises(RuntimeError, match="不能猜一个国家名"):
        ab_probe.build(game=_EMPTY_GAME)


def test_元数据是合法JSON() -> None:
    data = json.loads(ab_probe.metadata_text())
    assert data["supported_game_version"] == "1.14.3"
    assert "A→B→B2" in data["short_description"]


def test_探针源目录在仓库内() -> None:
    assert ab_probe.PROBE_DIR == config.REPO / "tools" / "probe" / ab_probe.PROBE_MOD
