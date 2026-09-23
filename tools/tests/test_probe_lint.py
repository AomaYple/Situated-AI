"""探针引用体检的测试（`pdx.probe_lint`）。

这一组盯的是**一次昂贵实验前的最后一道网**：探针里写错一个引用不会让探针崩，
只会让某一格读数**静默为空**（"没发生"与"没记"分不清）。所以：
① 真实生成物必须全绿（否则这套体检没意义）；
② 每一类引用都要有一条**阳性对照**（故意写错 → 必须抓到）；
③ 注释里举的反例**不能**被当成错误（探针注释故意写了 `[This.GetTag]` 这种不合法例子）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pdx import ab_probe, config, exe_strings, probe_lint

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_needs_game = pytest.mark.skipif(
    not (config.GAME / "common").is_dir(), reason="游戏目录不可用（要查原版名字池）"
)
_ON_ACTIONS = "common/on_actions/zz_probe_ab_on_actions.txt"


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
