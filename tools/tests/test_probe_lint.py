"""探针引用体检的测试（`pdx.probe_lint`）。

这一组盯的是**一次昂贵实验前的最后一道网**：探针里写错一个引用不会让探针崩，
只会让某一格读数**静默为空**（"没发生"与"没记"分不清）。所以：
① 真实生成物必须全绿（否则这套体检没意义）；
② 每一类引用都要有一条**阳性对照**（故意写错 → 必须抓到）；
③ 注释里举的反例**不能**被当成错误（探针注释故意写了 `[This.GetTag]` 这种不合法例子）。

2026-09-25 起这里还盯**形状**（`TestShapeRules` 那一组）：`on_action` 块的深度 1 键、
`if = {` 之后必须紧跟 `limit = {`。这两条是 `t64` 侦察局**白烧一局**换来的 ——
两类错误引擎都只记一行日志，脚本侧毫无感觉，而开局前读文件就能判。
形状规则的判据一律**机械推导**，所以这一组还兼作"判据来源"的取证：原版深度 1 键现扫、
`if⇒limit` 不变式在原版 1,933 个 `if` 上成立、官方文档里原版没用到的成员必须判过。
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from pdx import ab_probe, config, exe_strings, preflight, probe_lint, stress_probe

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_needs_game = pytest.mark.skipif(
    not (config.GAME / "common").is_dir(), reason="游戏目录不可用（要查原版名字池）"
)
_ON_ACTIONS = "common/on_actions/zz_probe_ab_on_actions.txt"

#: `t73` 归档的**真产物**（改前那份，`2026-09-25 03:26:31` 链的部署副本；只读、不许手改）。
_ARCHIVE = config.USERDIR / "v3probe-logs-archive" / "t73-改前产物-F2语义-0334"
_ARCHIVE_EFFECTS_SHA16 = "eae08b05ae437c46"
_ARCHIVE_ON_ACTIONS_SHA16 = "a764328aa1f0e380"
_needs_archive = pytest.mark.skipif(
    not (_ARCHIVE / "zz_stress_effects.txt").is_file(),
    reason="本机没有 t73 归档的真产物（它只在跑过那一局的机器上有）",
)


def _sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _archived(name: str) -> dict[str, str]:
    """归档产物**按内容**读进来（引擎侧带 BOM ⇒ 用 ``utf-8-sig``）。

    ⚠️ 归档目录是**平铺**的（`metadata.json` / `README.md` / 两份文本），没有子目录。
    """
    path = _ARCHIVE / name
    assert _sha16(path) in {_ARCHIVE_EFFECTS_SHA16, _ARCHIVE_ON_ACTIONS_SHA16}, (
        f"归档的 {name} 字节变了（sha16={_sha16(path)}）—— 先核对再引用"
    )
    sub = "scripted_effects" if "effects" in name else "on_actions"
    return {f"common/{sub}/{name}": path.read_text(encoding="utf-8-sig", errors="replace")}


# ── 改前那份坏产物的**忠实重建**（`t64` 侦察局；原文见部署目录与 error.log）──────
# ① `on_monthly_pulse_country` 块里直接写脚本效果调用 ⇒ 引擎拒掉整份文件
#    （`Unexpected token: zz_stress_tick, near line: 6`）⇒ 钩子一次都没挂上。
_BAD_ON_ACTIONS = "on_monthly_pulse_country = {\n\tzz_stress_tick = yes\n}\n"
# ② ③ 革命潮那一段 `if = {` 之后**少了** `limit = {`，8 个 `c:TAG ?= this` 直接被当效果读
#    ⇒ 8 行 `Unknown effect c:GBR`（引擎报的行号偏移不恒定，故一律按内容定位）。
_BAD_TAGS = ("GBR", "FRA", "RUS", "AUS", "USA", "CHI", "MEX", "BRZ")
_BAD_IF = (
    "zz_stress_tick = {\n"
    "\t# ③ 革命潮：改前那份产物里下面这几行直接跟在 `if = {` 后面（少了 limit）\n"
    "\tif = {\n"
    + "".join(f"\t\tc:{tag} ?= this\n" for tag in _BAD_TAGS)
    + "\t\tevery_scope_state = {\n"
    "\t\t\tadd_radicals_in_state = { value = { add = 0.10 } }\n"
    "\t\t}\n"
    "\t}\n"
    "}\n"
)
# ④ **静默**那一类（`t73` 2026-09-25 03:33 实测）：8 条作用域比较**平铺进同一个 `limit`**。
#    逐字取自归档的真产物 `zz_stress_effects.txt:125-138`（只去掉了文件头的生成器注释）。
_BAD_LIMIT = (
    "zz_stress_tick = {\n"
    "\t# ③ 革命潮：这些国家每半年吃一波激进派（真进运动系统）。\n"
    "\tif = {\n"
    "\t\tlimit = {\n"
    + "".join(
        f"\t\t\tc:{tag} ?= this\n"
        for tag in ("GBR", "FRA", "RUS", "AUS", "PRU", "CHI", "TUR", "USA")
    )
    + "\t\t}\n"
    "\t}\n"
    "}\n"
)
_BAD_FILES = {
    "common/on_actions/zz_stress_on_actions.txt": _BAD_ON_ACTIONS,
    "common/scripted_effects/zz_stress_effects.txt": _BAD_IF,
}

# ── 修好之后的形状（`t73` 的配方：`OR = { … }` 或 8 个独立 `if`；这里用 OR 那一版）──
_GOOD_FILES = {
    "common/on_actions/zz_stress_on_actions.txt": (
        "on_monthly_pulse_country = {\n\ton_actions = { zz_stress_monthly_tick }\n}\n\n"
        "zz_stress_monthly_tick = {\n\teffect = {\n\t\tzz_stress_tick = yes\n\t}\n}\n"
    ),
    "common/scripted_effects/zz_stress_effects.txt": (
        "zz_stress_tick = {\n\t# ③ 革命潮（修好之后：8 个 tag 收进一个 OR）\n"
        "\tif = {\n\t\tlimit = {\n\t\t\tOR = {\n"
        + "".join(f"\t\t\t\tc:{tag} ?= this\n" for tag in _BAD_TAGS)
        + "\t\t\t}\n\t\t}\n\t\tevery_scope_state = {\n"
        "\t\t\tadd_radicals_in_state = { value = { add = 0.10 } }\n\t\t}\n\t}\n}\n"
    ),
}


def _files() -> dict[str, str]:
    return ab_probe.build(game=None).files


def _identifiers() -> frozenset[str] | None:
    return exe_strings.exe_identifiers() if exe_strings.exe_path().is_file() else None


class TestCodeOnly:
    def test_整行注释被丢掉(self) -> None:
        text = '# debug_log = "[This.GetTag]"\nreal = yes\n'
        assert probe_lint.code_only(text).strip() == "real = yes"

    def test_行尾注释被丢掉但引号里的井号不算注释(self) -> None:
        text = 'debug_log = "a#b"  # 这是注释\n'
        assert "# 这是注释" not in probe_lint.code_only(text)
        assert "a#b" in probe_lint.code_only(text)

    def test_单引号里的井号也不算(self) -> None:
        assert "a#b" in probe_lint.code_only("x = 'a#b' # 注释\n")


@_needs_game
class TestRealProbe:
    def test_真实生成物全绿(self) -> None:
        """生成出来的探针，每一处引用都必须指得到东西 —— 否则这套体检等于没接上。"""
        issues = probe_lint.lint(_files(), exe_identifiers=_identifiers())
        bad = probe_lint.failures(issues)
        assert len(issues) > 100, f"只查到 {len(issues)} 处引用 —— 检查器是不是失效了？"
        assert not bad, "真实探针里有指不到的引用：\n  " + "\n  ".join(
            i.describe() for i in bad[:10]
        )

    def test_检查器覆盖了各类别(self) -> None:
        kinds = {i.kind for i in probe_lint.lint(_files(), exe_identifiers=_identifiers())}
        for kind in (
            "法类型引用",
            "AI 牌引用",
            "利益集团引用",
            "日志条目引用",
            "我们自己定义的效果",
        ):
            assert kind in kinds, f"{kind} 一处都没查到 —— 这一类是不是漏了？"


@_needs_game
class TestCatchesTypos:
    """阳性对照：每一类都故意写错一次，必须被抓到。"""

    def _lint(self, *, rel: str, old: str, new: str) -> list[probe_lint.Issue]:
        files = dict(_files())
        assert old in files[rel], f"生成物里没有 {old!r} —— 测试自己过期了"
        files[rel] = files[rel].replace(old, new)
        return probe_lint.failures(probe_lint.lint(files, exe_identifiers=_identifiers()))

    def test_效果名写错(self) -> None:
        bad = self._lint(
            rel=_ON_ACTIONS, old="zz_probe_ab_ladder = yes", new="zz_probe_ab_ladar = yes"
        )
        assert any(i.name == "zz_probe_ab_ladar" for i in bad), bad

    def test_JE名写错(self) -> None:
        bad = self._lint(
            rel=_ON_ACTIONS, old="has_journal_entry = je_sitai_", new="has_journal_entry = je_nope_"
        )
        assert any(i.kind == "日志条目引用" and not i.ok for i in bad), bad

    def test_法名写错(self) -> None:
        bad = self._lint(rel=_ON_ACTIONS, old="law_type:law_serfdom", new="law_type:law_serfdomm")
        assert any(i.name == "law_serfdomm" for i in bad), bad

    def test_牌名写错(self) -> None:
        bad = self._lint(
            rel=_ON_ACTIONS,
            old="has_strategy = ai_strategy_default",
            new="has_strategy = ai_strategy_defaultt",
        )
        assert any(i.name == "ai_strategy_defaultt" for i in bad), bad

    def test_利益集团写错(self) -> None:
        bad = self._lint(rel=_ON_ACTIONS, old="ig:ig_landowners", new="ig:ig_landowner")
        assert any(i.name == "ig_landowner" for i in bad), bad

    def test_data_function写错(self) -> None:
        if _identifiers() is None:  # pragma: no cover - 没有 exe 时跳过
            pytest.skip("没有 victoria3.exe，data function 那一类查不了")
        bad = self._lint(
            rel=_ON_ACTIONS,
            old="GetGovernmentLegitimacy",
            new="GetGovernmentLegitimicy",
        )
        assert any(i.name == "GetGovernmentLegitimacy" for i in bad) or any(
            "Legitimicy" in i.name for i in bad
        ), bad


@_needs_game
class TestCommentsAreNotChecked:
    def test_注释里的反例不会误报(self) -> None:
        """探针注释**故意**举了不合法的例子（`[This.GetTag]`）—— 那不该算错。"""
        files = dict(_files())
        files["common/scripted_effects/zz_probe_ab_effects.txt"] += (
            "\n# 反例：`law_type:law_nope` 与 `[This.GetTag]` 都不是合法写法\n"
        )
        assert not probe_lint.failures(probe_lint.lint(files, exe_identifiers=_identifiers()))


class TestOffline:
    def test_没有游戏时只查得动我们自己的名字(self, tmp_path: Path) -> None:
        """离线（CI）也能跑：原版名字池读不到就**跳过那几类**，不假报。"""
        files = {"a.txt": "zz_probe_ab_missing = yes\n"}
        bad = probe_lint.failures(probe_lint.lint(files, game=tmp_path / "无"))
        assert [i.name for i in bad] == ["zz_probe_ab_missing"]
        assert all(i.kind == "未知效果" for i in bad)


class TestOurOwnCardsAreKnown:
    """`has_strategy` 的已知集合必须包含**我们自己有定义**的牌（2026-09-25 加）。

    为什么必须有这一组：已知集合原先只有**游戏目录**的 `common/ai_strategies`，
    于是探针一读自己的牌就判红 ⇒ `v3 preflight` 红 ⇒ 那一局根本起不来。
    而那条读线正是新增牌的**唯一机器可读判据**
    （`docs/design/exec/阶段5-新增牌-口径.md` §4）。
    放行的依据只能是"**有定义**"——所以同一组里必须留一条拼错名仍然判红的负例，
    否则这一修就成了"凡 `sitai_*` 都放行"（P13 的反面）。
    """

    @staticmethod
    def _fake_game(tmp_path: Path) -> Path:
        """造一个**最小游戏根**：只放一张原版牌。

        为什么不能把 `game` 指到空目录：整类检查在"原版名字池读不到"时**整类跳过**
        （`test_没有游戏时只查得动我们自己的名字` 钉的就是这个语义）——
        池子空 ⇒ `if strategies:` 不成立 ⇒ 这一组测的东西根本不会被查，
        测试会以"没有 AI 牌引用结论"的方式**假绿**。
        """
        game = tmp_path / "game"
        (game / "common" / "ai_strategies").mkdir(parents=True)
        (game / "common" / "ai_strategies" / "00_vanilla.txt").write_text(
            "ai_strategy_vanilla_agenda = {\n}\n", encoding="utf-8"
        )
        return game

    def _lint(
        self, files: dict[str, str], *, tmp_path: Path, mod_root: Path
    ) -> list[probe_lint.Issue]:
        return probe_lint.lint(files, game=self._fake_game(tmp_path), mod_root=mod_root)

    def test_探针自己定义的牌判绿(self, tmp_path: Path) -> None:
        files = {
            "common/ai_strategies/zz_probe_t_card.txt": "ai_strategy_zz_probe_t_card = {\n}\n",
            "common/on_actions/zz_probe_t.txt": (
                "zz_probe_t_check = { effect = { "
                "if = { limit = { has_strategy = ai_strategy_zz_probe_t_card } } "
                'debug_log = "ZZPROBE T;X;yes" } }\n'
            ),
        }
        issues = self._lint(files, tmp_path=tmp_path, mod_root=tmp_path / "mod")
        card = [i for i in issues if i.kind == "AI 牌引用"]
        assert [i.ok for i in card] == [True], [i.describe() for i in card]
        assert "探针自己的文件里有定义" in card[0].detail

    def test_真mod产物里定义的牌判绿(self, tmp_path: Path) -> None:
        mod_root = tmp_path / "mod"
        (mod_root / "common" / "ai_strategies").mkdir(parents=True)
        (mod_root / "common" / "ai_strategies" / "sitai_t.txt").write_text(
            "ai_strategy_sitai_t_agenda = {\n}\n", encoding="utf-8"
        )
        files = {
            "common/on_actions/zz_probe_t.txt": (
                "zz_probe_t_check = { trigger = { "
                "if = { limit = { has_strategy = ai_strategy_sitai_t_agenda } } } }\n"
            )
        }
        card = [
            i
            for i in self._lint(files, tmp_path=tmp_path, mod_root=mod_root)
            if i.kind == "AI 牌引用"
        ]
        assert [i.ok for i in card] == [True], [i.describe() for i in card]
        assert "真 mod 的产物里有定义" in card[0].detail

    def test_拼错的牌名仍然判红(self, tmp_path: Path) -> None:
        """负例：mod 里**有**隔壁那张牌，不代表随便写一个名字也能过。"""
        mod_root = tmp_path / "mod"
        (mod_root / "common" / "ai_strategies").mkdir(parents=True)
        (mod_root / "common" / "ai_strategies" / "sitai_t.txt").write_text(
            "ai_strategy_sitai_t_agenda = {\n}\n", encoding="utf-8"
        )
        files = {
            "common/on_actions/zz_probe_t.txt": (
                "zz_probe_t_check = { trigger = { "
                "if = { limit = { has_strategy = ai_strategy_sitai_t_agendaa } } } }\n"
            )
        }
        bad = probe_lint.failures(self._lint(files, tmp_path=tmp_path, mod_root=mod_root))
        assert [i.name for i in bad] == ["ai_strategy_sitai_t_agendaa"], bad
        assert "拼错的牌名必须仍然判红" in bad[0].hint


@_needs_game
class TestShapeRules:
    """形状规则的**判据来源**：两条都必须机械推导，并且"比引擎严"的写法一个都不许红。"""

    def test_原版on_action深度1键是现扫出来的(self) -> None:
        members = probe_lint.on_action_members(config.GAME / "common" / "on_actions")
        assert {"effect", "events", "on_actions", "random_events", "trigger"} <= members
        # 判据只到**深度 1**：转调列表里的 `delay = { days = 4 }`
        # （原版 00_code_on_actions.txt:1558）是深度 2，不许进这张表。
        assert "delay" not in members

    def test_官方成员里原版没用到的也必须判过(self) -> None:
        """官方支持、原版恰好没用的键 ⇒ **必须判过**（判据比引擎严比漏判更坏）。"""
        vanilla = probe_lint.on_action_members(config.GAME / "common" / "on_actions")
        unused = sorted(probe_lint.ON_ACTION_OFFICIAL_MEMBERS - vanilla)
        assert {"weight_multiplier", "first_valid", "random_on_actions", "fallback"} <= set(unused)
        for key in unused:
            text = f"zz_t_on_action = {{\n\t{key} = {{ }}\n}}\n"
            bad = probe_lint.failures(probe_lint.lint({"common/on_actions/zz_t.txt": text}))
            assert not bad, f"{key} 是官方结构成员，却被判红：{[i.describe() for i in bad]}"

    def test_原版on_actions文件在规则一下判过(self) -> None:
        """把**原版**那 6 个文件整份走一遍规则①（阳性对照里最强的一条）。"""
        checked = 0
        pairs = 0
        for path in sorted((config.GAME / "common" / "on_actions").rglob("*.txt")):
            rel = f"common/on_actions/{path.name}"
            text = path.read_text(encoding="utf-8", errors="replace")
            pairs += sum(len(group) for group in probe_lint.on_action_block_keys(text).values())
            issues = probe_lint.lint({rel: text})
            keys = [i for i in issues if i.kind == "on_action 顶层键"]
            assert keys, f"{rel} 一个深度 1 键都没判到 —— 规则①没接上？"
            assert all(i.ok for i in keys), [i.describe() for i in keys if not i.ok]
            checked += len(keys)
        assert checked >= 10, f"6 份原版文件只判到 {checked} 个键"
        assert pairs > 200, f"6 份原版文件里只数到 {pairs} 个深度 1 键 —— 扫描失效？"

    def test_原版每个if都带limit(self) -> None:
        """规则②的前提：原版自己**每一个** `if = {` 的第一条语句都是 `limit = {`。"""
        total = bad = 0
        for sub in ("on_actions", "scripted_effects", "scripted_triggers"):
            for path in sorted((config.GAME / "common" / sub).rglob("*.txt")):
                text = probe_lint.code_only(path.read_text(encoding="utf-8", errors="replace"))
                total += probe_lint.count_if_blocks(text)
                bad += len(probe_lint.if_blocks_without_limit(text))
        assert total > 1000, f"只扫到 {total} 个 if —— 扫描是不是失效了？"
        assert bad == 0, f"原版里有 {bad} 处 `if = {{` 的第一条不是 `limit = {{`"


@_needs_game
class TestShapePositiveControls:
    """阳性对照：真实生成物必须判过，而且三条规则**真的读到了东西**（不是空转）。"""

    @staticmethod
    def _stress_files() -> dict[str, str]:
        try:
            return dict(stress_probe.files())
        except RuntimeError as exc:  # pragma: no cover - 数据源缺失时跳过
            pytest.skip(f"压力剧本生成不出来（{exc}）")

    def test_AB探针产物三条规则全过(self) -> None:
        shapes = probe_lint.scan_shapes(_files())
        assert shapes.if_blocks > 50, f"只扫到 {shapes.if_blocks} 个 if —— 规则②没接上？"
        assert shapes.limits > 50, f"只扫到 {shapes.limits} 个 limit —— 规则③没接上？"
        assert shapes.on_action_keys > 0, "一个 on_action 顶层键都没读到 —— 规则①没接上？"
        assert shapes.vanilla_keys > 0, "原版深度 1 键没扫到（这一组要有游戏的机器）"
        assert (shapes.if_bad, shapes.limit_bad, shapes.on_action_bad) == (0, 0, 0)

    def test_压力剧本产物前两条规则全过(self) -> None:
        """规则①②在**当前生成器**的产物上必须全过。

        ⚠️ 规则③的现状**不在这里断言**：它是生成器当下的性质（`t73` 正在修），
        断言它会让这条用例在修好/改坏时各红一次。规则③的行为由
        `TestShapeNegativeControl` 与 `_needs_archive` 那两条钉住。
        """
        shapes = probe_lint.scan_shapes(self._stress_files())
        assert shapes.if_blocks > 50
        assert shapes.limits > 50
        assert shapes.on_action_keys > 0
        assert (shapes.if_bad, shapes.on_action_bad) == (0, 0)

    def test_合法转调形状判过(self) -> None:
        """官方配方（转调一个自己的 on_action）在三条规则下都要过。"""
        text = (
            "on_monthly_pulse_country = {\n\ton_actions = { zz_stress_monthly_tick }\n}\n\n"
            "zz_stress_monthly_tick = {\n\teffect = {\n\t\tzz_stress_tick = yes\n\t}\n}\n"
        )
        assert not probe_lint.failures(probe_lint.lint({"common/on_actions/zz_t.txt": text}))

    def test_delay在深度2不算红(self) -> None:
        """原版 `on_actions = { delay = { days = 4 } … }`（`00_code_on_actions.txt:1558`）。

        判据只到深度 1：`delay` 是转调列表的条目，判红它就是"判据比引擎严"。
        """
        text = (
            "on_monthly_pulse_country = {\n\ton_actions = {\n"
            "\t\tdelay = { days = 4 }\n\t\tzz_stress_monthly_tick\n\t}\n}\n"
        )
        assert not probe_lint.failures(probe_lint.lint({"common/on_actions/zz_t.txt": text}))

    def test_OR包着的作用域比较判过(self) -> None:
        """**合法形状之一**：`limit = { OR = { c:GBR ?= this c:FRA ?= this } }`。

        那些比较的父块是 `OR` 而不是 `limit` ⇒ 规则③的数法自然放过它们（不是特判）。
        """
        text = (
            "zz_t = {\n\tif = {\n\t\tlimit = {\n\t\t\tOR = {\n"
            "\t\t\t\tc:GBR ?= this\n\t\t\t\tc:FRA ?= this\n\t\t\t}\n\t\t}\n\t}\n}\n"
        )
        assert probe_lint.limit_scope_flattenings(probe_lint.code_only(text)) == []
        assert not probe_lint.failures(probe_lint.lint({"common/scripted_effects/zz_t.txt": text}))

    def test_八条各自独立的if判过(self) -> None:
        """**合法形状之二**：每个 tag 一个独立的 `if = { limit = { c:TAG ?= this } … }`。"""
        text = (
            "zz_t = {\n"
            + "".join(
                f"\tif = {{\n\t\tlimit = {{ c:{tag} ?= this }}\n"
                f'\t\tdebug_log = "ZZPROBE STRESS;RADICAL;1837.1.1;{tag}"\n\t}}\n'
                for tag in _BAD_TAGS
            )
            + "}\n"
        )
        assert probe_lint.limit_scope_flattenings(probe_lint.code_only(text)) == []
        assert not probe_lint.failures(probe_lint.lint({"common/scripted_effects/zz_t.txt": text}))

    def test_变量比较不算平铺(self) -> None:
        """`var:a ?= 1` 与 `var:b ?= 2` 可以同时为真 ⇒ 平铺在 `limit` 里是**合法的与**。"""
        text = (
            "zz_t = {\n\tif = {\n\t\tlimit = {\n\t\t\tvar:a ?= 1\n\t\t\tvar:b ?= 2\n\t\t}\n\t}\n}\n"
        )
        assert probe_lint.limit_scope_flattenings(probe_lint.code_only(text)) == []
        assert not probe_lint.failures(probe_lint.lint({"common/scripted_effects/zz_t.txt": text}))


class TestShapeRuleProvenance:
    """手写的那 10 个官方成员必须**逐字**能在本仓的官方文档镜像里查到（不是凭印象抄的）。"""

    def test_官方成员清单逐字在镜像里(self) -> None:
        doc = config.REPO / "docs" / "victoria3-modding" / "07-官方文档索引.md"
        text = doc.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if "**结构成员**" in line]
        assert len(lines) == 1, f"{doc} 里「结构成员」那一行有 {len(lines)} 条，取证坐标变了"
        for member in sorted(probe_lint.ON_ACTION_OFFICIAL_MEMBERS):
            assert f"`{member}`" in lines[0], f"{member} 不在那一行里：{lines[0][:90]}"


class TestShapeNegativeControl:
    """阴性对照：改前那份坏产物在三条规则下**各判红一条**，定位按**内容**不按行号。"""

    def test_on_action块里直接写效果调用判红(self) -> None:
        bad = probe_lint.failures(
            probe_lint.lint({"common/on_actions/zz_stress_on_actions.txt": _BAD_ON_ACTIONS})
        )
        assert len(bad) == 1, [i.describe() for i in bad]
        assert bad[0].kind == "on_action 顶层键"
        assert bad[0].name == "zz_stress_tick"
        assert "zz_stress_on_actions.txt" in bad[0].detail
        assert "on_monthly_pulse_country" in bad[0].detail
        assert "转调" in bad[0].hint

    def test_if少了limit判红(self) -> None:
        bad = probe_lint.failures(
            probe_lint.lint({"common/scripted_effects/zz_stress_effects.txt": _BAD_IF})
        )
        assert len(bad) == 1, [i.describe() for i in bad]
        assert bad[0].kind == "if 缺 limit"
        # 报错信息里是**引擎会当效果读的那一行本身**，不是行号（backlog B84）
        assert bad[0].name == "c:GBR ?= this"
        assert "zz_stress_effects.txt" in bad[0].detail

    def test_limit里平铺作用域比较判红(self) -> None:
        """**完全安静**的那一类：8 条作用域比较平铺进同一个 `limit` ⇒ 恒假、引擎一行不报。"""
        bad = probe_lint.failures(
            probe_lint.lint({"common/scripted_effects/zz_stress_effects.txt": _BAD_LIMIT})
        )
        assert len(bad) == 1, [i.describe() for i in bad]
        assert bad[0].kind == "limit 平铺作用域比较"
        # 锚点是**整句**比较（两个方向都算），不是行号
        assert bad[0].name.startswith("8 条：c:GBR ?= this / c:FRA ?= this")
        assert "zz_stress_effects.txt" in bad[0].detail
        assert "引擎一行日志都不报" in bad[0].hint

    @_needs_archive
    def test_归档的真产物在三条规则下各判红一条(self) -> None:
        """用 `t73` 归档的**真文件**（不是现造样本）判：字节先核对，再判红。"""
        assert _sha16(_ARCHIVE / "zz_stress_effects.txt") == _ARCHIVE_EFFECTS_SHA16
        kinds = {
            i.kind for i in probe_lint.failures(probe_lint.lint(_archived("zz_stress_effects.txt")))
        }
        assert kinds == {"limit 平铺作用域比较"}, kinds

    @_needs_archive
    def test_归档的on_actions在规则一下判过(self) -> None:
        """同一份归档里的 `zz_stress_on_actions.txt` 是**改好之后**的转调写法 ⇒ 规则① 判过。"""
        assert _sha16(_ARCHIVE / "zz_stress_on_actions.txt") == _ARCHIVE_ON_ACTIONS_SHA16
        issues = probe_lint.lint(_archived("zz_stress_on_actions.txt"))
        keys = [i for i in issues if i.kind == "on_action 顶层键"]
        assert keys
        assert all(i.ok for i in keys), [i.describe() for i in keys if not i.ok]

    def test_定位不随行号漂移(self) -> None:
        """同一处违规，前面多几行空行/注释时锚点必须不变（行号锚会漂，内容锚不会）。

        ⚠️ 低层读取口收的是**过完 `code_only` 的文本**（`lint` 就是这么调的）：注释里
        **故意**会举 `if = {` 这种反例，拿原文查会误报 —— 这条用例本身就把这件事钉住了。
        """
        moved = "\n\n\n" + _BAD_IF.replace("\t# ③", "\t\t\t# ③")
        assert probe_lint.if_blocks_without_limit(probe_lint.code_only(_BAD_IF)) == [
            "c:GBR ?= this"
        ]
        assert probe_lint.if_blocks_without_limit(probe_lint.code_only(moved)) == ["c:GBR ?= this"]
        # 原文里的注释确实会被低层读取口当成一处"违规"—— 所以别拿原文直接喂它
        assert len(probe_lint.if_blocks_without_limit(_BAD_IF)) == 2
        # 规则③ 同理：注释里那句 `limit = {` 只是文字，过完 code_only 就只剩 1 处
        assert probe_lint.limit_scope_flattenings(probe_lint.code_only(_BAD_LIMIT)) == [
            "8 条：c:GBR ?= this / c:FRA ?= this …"
        ]


class TestShapeOffline:
    """没有游戏目录时（CI）也要判得出坏形状：合法键退化成官方 10 个结构成员，**不是空集**。"""

    def test_没有游戏时坏形状仍然判红(self, tmp_path: Path) -> None:
        game = tmp_path / "无"
        bad = probe_lint.failures(probe_lint.lint(_BAD_FILES, game=game))
        assert sorted({i.kind for i in bad}) == ["if 缺 limit", "on_action 顶层键"], bad
        shapes = probe_lint.scan_shapes(_BAD_FILES, game=game)
        assert (shapes.vanilla_keys, shapes.if_bad, shapes.on_action_bad) == (0, 1, 1)

    def test_没有游戏时也判得出平铺作用域比较(self, tmp_path: Path) -> None:
        """规则③ 的判据不依赖游戏目录（它是纯结构判断）。"""
        files = {"common/scripted_effects/zz_stress_effects.txt": _BAD_LIMIT}
        bad = probe_lint.failures(probe_lint.lint(files, game=tmp_path / "无"))
        assert [i.kind for i in bad] == ["limit 平铺作用域比较"], bad


class TestPreflightWiring:
    """开局前那一格（`v3 preflight` 的第 7 项）：压力剧本产物**进了**体检才算接上。"""

    def test_真产物的结论行非空(self) -> None:
        """红或绿都算结论 —— 这一格要的是"它真的跑了"，不是"它一定绿"。

        ⚠️ 今天的真产物在规则③ 下是**红的**（`t73` 的 `OR = { … }` 修复还没落地）⇒
        这条用例**不断言颜色**，否则它会在修好/改坏时各红一次。
        """
        check = preflight.check_stress_lint()
        assert check.name == "压力剧本体检"
        assert check.detail, "结论行不能是空的（红或绿都算结论）"
        assert ("个 on_action 顶层键" in check.detail) or ("形状不合法" in check.detail)

    def test_坏产物判红并指到生成器(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(stress_probe, "files", lambda: dict(_BAD_FILES))
        check = preflight.check_stress_lint()
        assert not check.ok
        assert "形状不合法" in check.detail
        assert "stress_probe" in check.fix
        assert check.level == preflight.WRONG

    def test_修好的形状让那一格判绿(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`OR = { … }` 修好之后同一格必须转绿 —— 这条是"修好了就不再红"的回归防线。"""
        monkeypatch.setattr(stress_probe, "files", lambda: dict(_GOOD_FILES))
        check = preflight.check_stress_lint()
        assert check.ok, check.describe()
        assert "`limit`" in check.detail

    @_needs_archive
    def test_归档的真产物让那一格判红(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """用归档的真文件走一遍**开局前那一格**：它必须红，且锚点是"平铺"那一类。"""
        monkeypatch.setattr(stress_probe, "files", lambda: _archived("zz_stress_effects.txt"))
        check = preflight.check_stress_lint()
        assert not check.ok, check.describe()
        assert "平铺" in check.detail

    def test_体检在run的清单里(self) -> None:
        assert "压力剧本体检" in [check.name for check in preflight.run().checks]
