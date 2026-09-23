"""标准压力剧本（阶段 4 ④）的生成器 —— `pdx.stress_probe`。

为什么值得一组用例
------------------
这份剧本是 G-EXIT-3 能不能**分辨 0.5 ms** 的前提（`阶段4-结果.md` §六·补：非受控对照里
噪声比信号大 4 倍）。它一旦写错，**症状是沉默的**：

* tag 写错一个字母 ⇒ `c:XQZ ?= this` 永远不成立 ⇒ 那条压力**一次都不发生**，
  而脚本侧一个字都不报（B80 同族的失败长相）；
* 效果名写错 ⇒ 引擎只往 `error.log` 里写一句 `Unknown effect`，游戏照样跑；
* `dp_` 类型写错 ⇒ 博弈创建失败，同样静默。

所以这一组用例的核心不是"生成器能跑"，而是**生成的每一样东西在原版里都真的存在**：
tags / 效果名 / 博弈类型，逐条拿原版文件核。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest

from pdx import config, stress_probe

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_needs_game = pytest.mark.skipif(not config.GAME.is_dir(), reason="游戏目录不可用")


class TestGeneration:
    def test_三件产物齐全(self) -> None:
        assert set(stress_probe.files()) == {
            ".metadata/metadata.json",
            "common/scripted_effects/zz_stress_effects.txt",
            "common/on_actions/zz_stress_on_actions.txt",
        }

    def test_三条压力都在效果里(self) -> None:
        text = stress_probe.effects_text()
        assert text.count("create_diplomatic_play = {") == len(stress_probe.WAR_PAIRS)
        assert "add_radicals_in_state" in text
        assert re.search(rf"add_treasury = {stress_probe.TREASURY_DRAIN}", text)

    def test_每个压力点都有日期与只做一次的标记(self) -> None:
        text = stress_probe.effects_text()
        for date in (stress_probe.WAR_DATE, stress_probe.BREAK_DATE, *stress_probe.RADICAL_DATES):
            assert f'game_date > "{date}"' in text
        # 每个 fired 标记必须**既写又读**（只写不读 = 每次脉冲都做一遍）
        for var in ("zz_stress_war_fired", "zz_stress_break_fired", "zz_stress_radicals_1"):
            assert f"set_variable = {{ name = {var} value = 1 }}" in text
            assert f"NOT = {{ has_variable = {var} }}" in text

    def test_每月脉冲只挂自己的效果不碰原版(self) -> None:
        text = stress_probe.on_actions_text()
        assert "on_monthly_pulse_country = {" in text
        assert "zz_stress_tick = yes" in text
        blocks = re.findall(r"^on_[a-z_]+ = \{", text, re.MULTILINE)
        assert blocks == ["on_monthly_pulse_country = {"], (
            "别在这里覆盖原版的 on_action 文件（F2：R3 禁用）"
        )

    def test_游戏侧文本带BOM而元数据不带(self, tmp_path: Path) -> None:
        stress_probe.write(tmp_path)
        assert (
            (tmp_path / "common/scripted_effects/zz_stress_effects.txt")
            .read_bytes()
            .startswith(b"\xef\xbb\xbf")
        )
        raw = (tmp_path / ".metadata/metadata.json").read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        json.loads(raw.decode("utf-8"))

    def test_两次生成逐字节一致(self, tmp_path: Path) -> None:
        """P8：同样的输入 → 同样的产出（压力剧本要能重放，产出就不能抖）。"""
        a, b = tmp_path / "a", tmp_path / "b"
        stress_probe.write(a)
        stress_probe.write(b)
        for rel in stress_probe.files():
            assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel

    def test_落点在用户mod目录且带探针前缀(self) -> None:
        """`zz_` 前缀 ⇒ `pdx.mods.discover_mods()` 会排除它（它不算"本机装了哪些 mod"）。"""
        assert stress_probe.MOD_NAME.startswith("zz_")
        assert stress_probe.dest().parent == config.LOCAL_MODS


@_needs_game
class TestVanillaVocabulary:
    """**逐条拿原版文件核**：写错一个字母的症状是"静默不做"，不是报错。"""

    def _definitions(self) -> str:
        return "\n".join(
            path.read_text(encoding="utf-8-sig", errors="replace")
            for path in (config.GAME / "common" / "country_definitions").glob("*.txt")
        )

    def test_用到的国家tag原版都有(self) -> None:
        text = self._definitions()
        tags = {initiator for initiator, _t, _k in stress_probe.WAR_PAIRS}
        tags |= {target for _i, target, _k in stress_probe.WAR_PAIRS}
        tags |= set(stress_probe.BREAK_TAGS) | set(stress_probe.RADICAL_TAGS)
        missing = sorted(tag for tag in tags if not re.search(rf"^{tag} = \{{", text, re.MULTILINE))
        assert not missing, f"这些 tag 原版国家定义里没有：{missing}"

    def test_用到的博弈类型原版都有(self) -> None:
        text = "\n".join(
            path.read_text(encoding="utf-8-sig", errors="replace")
            for path in (config.GAME / "common" / "diplomatic_plays").glob("*.txt")
        )
        kinds = {kind for _i, _t, kind in stress_probe.WAR_PAIRS}
        missing = sorted(
            kind for kind in kinds if not re.search(rf"^{kind} = \{{", text, re.MULTILINE)
        )
        assert not missing, f"这些博弈类型原版没有：{missing}"

    def test_用到的效果名原版都有人用(self) -> None:
        """`create_diplomatic_play` / `add_radicals_in_state` / `add_treasury` 都要有原版先例。"""
        text = "\n".join(
            path.read_text(encoding="utf-8-sig", errors="replace")
            for path in (config.GAME / "common" / "scripted_effects").glob("*.txt")
        )
        for name in ("create_diplomatic_play", "add_radicals_in_state", "add_treasury"):
            assert f"{name} = " in text, f"{name} 在原版 scripted_effects 里查无先例"

    def test_抽干的额度比原版最重的那一处还重(self) -> None:
        """剧本要的是**一定**进违约：比原版 `paris_commune_events.txt:243` 的 −100000 再重。"""
        assert stress_probe.TREASURY_DRAIN <= -100000
