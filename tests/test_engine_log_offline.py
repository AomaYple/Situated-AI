"""``pdx.engine_log`` 的**离线**用例：探针会话判定与 token 不一致的分类。

为什么单列一个文件
------------------
这两件事都是 2026-09-22 那次「18 条假红」直接逼出来的，而它们都能**纯离线**测：

1. :func:`pdx.engine_log.probe_session` 必须扫**全部** ``*.log``，不能只看当前那份。
   实测踩到：探针会话的日志滚到 ``debug.3.log``/``debug.4.log`` 之后，
   ``debug.log`` 已经是另一次**挂载失败**的会话，于是"当前日志干净"≠"日志集干净"。
   漏判的代价是 18 条 token 假红（其中 2 条是探针往 ``gui/error_deer.gui``
   插的 `CLEAR`/`DUMP` 按钮）。

2. ``CrossCheckReport`` 必须把 token 不一致**分成两类**：整份文件都找不到的
   （日志比安装旧／mod 换了）与"在文件里、但不在那一行"的（真正值得查的行号问题）。
   混在一起报，会把"日志过期"记到解析器头上 —— 实测 18 条里 16 条属前者。

⚠️ 判据**不许写成"排除原版"式**：本机 ``debug.log`` 的路径里就有 ``Victoria 3``，
``"Victoria 3" not in line`` 这种写法会把每一行都当成 mod 行（这个坑也钉在下面）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pdx import engine_log

if TYPE_CHECKING:
    from pathlib import Path

#: 一份"常规会话"的日志碎片：有版本号、有枚举记录，且**不含任何探针标识**。
NORMAL_LOG = """\
Victoria 3 (1.14.3) build bf52e8e
virtualfilesystem.cpp: pre-enumerating files in directory common/ with extension txt
pdx_gui_localize.cpp: unlocalized text key SOME_KEY at gui/panel.gui:12
"""

#: 探针会话的日志碎片（`tools/probe/` 的 mod 名字与 path）。
PROBE_LOG = """\
Mounted Data: mod/zz_sitai_perf
Sitai Perf Probe
pdx_gui_localize.cpp: unlocalized text key CLEAR at gui/error_deer.gui:166
"""


def _write_logs(tmp_path: Path, **files: str) -> Path:
    base = tmp_path / "logs"
    base.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (base / name.replace("__", ".")).write_text(text, encoding="utf-8")
    return base


class TestProbeSession:
    def test_没有日志目录时是假(self, tmp_path: Path) -> None:
        assert engine_log.probe_session(tmp_path / "没有这个目录") is False

    def test_常规日志是假(self, tmp_path: Path) -> None:
        base = _write_logs(tmp_path, debug__log=NORMAL_LOG)
        assert engine_log.probe_session(base) is False

    def test_探针标识为真(self, tmp_path: Path) -> None:
        base = _write_logs(tmp_path, debug__log=PROBE_LOG)
        assert engine_log.probe_session(base) is True

    def test_标识在轮转日志里也要认(self, tmp_path: Path) -> None:
        """**这就是那条假红的根因**：当前日志干净、旧的轮转日志里有探针。"""
        base = _write_logs(
            tmp_path,
            debug__log=NORMAL_LOG,  # 当前会话：探针**没挂上**，所以干净
            debug__3__log=PROBE_LOG,  # 旧的探针会话滚到了这里
        )
        assert engine_log.probe_session(base) is True

    def test_标识只出现在很靠后的位置也要认(self, tmp_path: Path) -> None:
        """旧实现只看前 200,000 字符 —— 探针标识落在后面就会漏判。"""
        padding = "# 填充\n" * 60_000  # 远超 200k 字符
        base = _write_logs(tmp_path, debug__log=padding + PROBE_LOG)
        assert engine_log.probe_session(base) is True

    def test_读不了的日志被跳过而不是抛错(self, tmp_path: Path) -> None:
        base = _write_logs(tmp_path, debug__log=NORMAL_LOG)
        (base / "broken.log").write_bytes(b"\xff\xfe\x00\x00")  # 不是 UTF-8
        assert engine_log.probe_session(base) is False  # replace 解码，不抛

    def test_标识表里有_perf_mod_的名字(self) -> None:
        """标记表是本模块与 `tools/probe/` 的**接口**：探针改名要两边一起改。

        这里把 perf_mod 写进日志的那两个名字钉住 —— 少一个就会漏判一次。
        """
        assert "Sitai Perf Probe" in engine_log.PROBE_MARKERS
        assert "zz_sitai_perf" in engine_log.PROBE_MARKERS


class TestTokenClassification:
    """token 断言的**三态**划分：匹配 / 真错配 / 不可核对。

    ⚠️ 2026-09-28 收口：判据只有一处 —— :meth:`engine_log.CrossCheckReport.token_verdicts`。
    以前的本类测试按「这个 token 在我们的世界里存在吗」分类，于是
    「行号不可比 + token 在别处还有」被判成 ``misplaced``（判红），而命令层
    按「行号不可比 ⇒ 不可核对」判，**同一份输入两个结论**。现在：

    * **行号不可比**（覆盖版与原版行数不同 / 文件被删 / 行数读不到）⇒ 不可核对，
      与「token 在不在别处」**无关**（两套行号相减得到的行号证明不了任何事）；
    * 只有**行号可比却对不上**才是真错配 —— 唯一该判红的一档。

    ==============================================  ==========  ======  ======  ==============
    情形（实测对应）                                 生效文件    原版    行数    三态
    ==============================================  ==========  ======  ======  ==============
    探针插的 `CLEAR`/`DUMP`（会话结束就没了）          没有        没有    —       不可核对
    覆盖版删掉的键（原版还有）                        没有        有      不同     不可核对
    token 被挤到别的行（覆盖版别处还有）               有（别处）  有      不同     不可核对
    token 落在别的行、但两版行数相同                   有（别处）  有      相同     真错配
    那一行就有它／那一行有以它开头的更长键             有          —       任意     匹配
    ==============================================  ==========  ======  ======  ==============
    """

    @staticmethod
    def _report(
        tmp_path: Path,
        *,
        effective: str | None,
        vanilla: str | None = None,
        claims: list[tuple[int, str]],
        with_override: bool = True,
    ):
        """合成一棵极小的树跑 ``cross_check``：``effective`` 是生效文件，``vanilla`` 是原版。

        ``vanilla=None`` 表示原版与生效文件同内容（无覆盖）；``with_override=False``
        则连覆盖映射都不建（等价于"引擎在无 mod 状态下跑过"）。
        """
        root = tmp_path / "game"
        (root / "gui").mkdir(parents=True)
        if vanilla is not None:
            (root / "gui" / "panel.gui").write_text(vanilla, encoding="utf-8")
        elif effective is not None:
            # 不建覆盖时，生效文件**就是**原版那一份（两处内容一致）
            (root / "gui" / "panel.gui").write_text(effective, encoding="utf-8")
        mod = tmp_path / "mod"
        (mod / "gui").mkdir(parents=True)
        if effective is not None:
            (mod / "gui" / "panel.gui").write_text(effective, encoding="utf-8")

        cs = [
            engine_log.EngineClaim(
                kind="token_at", detail="", file_rel="gui/panel.gui", line=n, token=t
            )
            for n, t in claims
        ]
        overrides = {"gui/panel.gui": mod / "gui" / "panel.gui"} if with_override else {}
        return engine_log.cross_check(cs, root=root, overrides=overrides)

    def test_命中就是命中(self, tmp_path: Path) -> None:
        rep = self._report(
            tmp_path,
            effective='a = "KEY_A"\nb = "KEY_B"\n',
            claims=[(1, "KEY_A"), (2, "KEY_B")],
            with_override=False,
        )
        assert [t[3] for t in rep.tokens] == [1, 2]
        assert rep.token_mismatches == []
        assert rep.absent_tokens == []
        assert rep.misplaced_tokens == []

    def test_两边都没有_算_absent(self, tmp_path: Path) -> None:
        """探针按钮那一类：生效文件与原版都找不到 ⇒ 日志描述的是别的世界。"""
        rep = self._report(
            tmp_path,
            effective='a = "KEY_A"\n',
            vanilla='a = "KEY_A"\n',
            claims=[(1, "KEY_A"), (9, "CLEAR")],
        )
        assert [t[2] for t in rep.absent_tokens] == ["CLEAR"]
        assert rep.misplaced_tokens == []
        assert len(rep.token_mismatches) == 1

    def test_覆盖删掉了但原版还有_算不可核对(self, tmp_path: Path) -> None:
        """⚠️ 这是**歧义情形**，判据按"不冤枉、也不放过"来定，别读反了。

        生效文件里没有、原版里有，有两种可能：① 覆盖把它删了（版本错配）；
        ② 我们的文件读漏了（**真问题**）。当前信息**分不开** ——
        所以既不算 ``absent``（会被跳过，可能放过真漏读），
        也不算 ``misplaced``（会被判红，可能冤枉解析器），
        而是落进 ``unverifiable_tokens``：**说出来、但不判红**。

        前提是**两份文件行数不同**（那才叫"两套内容对行号"）；行数相同时按
        :meth:`test_不可核对的判据是行数不同_不是找不到` 的口径判红。
        """
        rep = self._report(
            tmp_path,
            effective='a = "OTHER"\n',  # 生效的覆盖版里没有 KEY_GONE
            vanilla='a = "OTHER"\n\nb = "KEY_GONE"\n',  # 原版第 3 行有 ⇒ 行数不同
            claims=[(3, "KEY_GONE")],
        )
        assert rep.overridden_files == {"gui/panel.gui"}
        assert [t[2] for t in rep.unverifiable_tokens] == ["KEY_GONE"]
        assert rep.absent_tokens == []
        assert rep.misplaced_tokens == []

    def test_两边都没有才是_absent(self, tmp_path: Path) -> None:
        """只有"我们的世界里根本不存在这个 token"才跳过 —— 那才是过期数据。"""
        rep = self._report(
            tmp_path,
            effective='a = "OTHER"\n',
            vanilla='a = "ALSO_OTHER"\n',
            claims=[(1, "CLEAR")],
        )
        assert [t[2] for t in rep.absent_tokens] == ["CLEAR"]
        assert rep.misplaced_tokens == []

    def test_token还在只是不在那一行_算_misplaced(self, tmp_path: Path) -> None:
        """真正值得查的那一类：token 在生效文件里**有**，但不在引擎报的那一行。

        夹具刻意让覆盖版与原版**行数相同**（只有内容顺序不同）—— 这样才落进
        misplaced；行数不同会被判成 :attr:`unverifiable`（另有用例）。
        """
        rep = self._report(
            tmp_path,
            effective='a = "KEY_HERE"\nb = "OTHER"\n',  # 第 1 行有
            vanilla='a = "OTHER"\nb = "KEY_HERE"\n',  # 第 2 行有（行数同为 2）
            claims=[(2, "KEY_HERE")],  # 引擎说第 2 行，实际第 1 行
        )
        assert rep.absent_tokens == []
        assert rep.unverifiable_tokens == []
        assert [t[2] for t in rep.misplaced_tokens] == ["KEY_HERE"]
        assert rep.token_mismatches == rep.misplaced_tokens

    def test_覆盖版与原版行数不同_整份文件都算不可比(self, tmp_path: Path) -> None:
        """⚠️ **两份文件不是同一套行号**时，该文件的行号核对**一律不做**。

        这是本轮 18 条假红的收口判据：实测「Ultra Historical Warfare」
        （支持 1.13 / 本机 1.14.3）覆盖的 ``gui/military_formation_panel.gui``
        原版 8098 行、覆盖版 7767 行 —— 拿它跟日志的行号比就是拿两套内容对行号。
        判据只用可测事实（**行数**），且**只影响行号核对**，不影响 token 是否存在。

        ⚠️ 本用例的这一条 token **在生效文件里别处还有**（第 5 行）—— 这正是 2026-09-28
        收口的地方：**行号不可比时，「别处还有」不改变结论**。旧口径把这一档判成
        ``misplaced``（判红），与命令层的「不可核对」正好相反；两套行号相减出来的
        「第 5 行」证明不了任何事（覆盖版少了/多了行，原版行号在这里没有对应物）。

        ⚠️ 历史断言原样留档（2026-09-28 之前本用例钉的就是它，现**显式改写**，不是删掉）：

            assert [t[2] for t in rep.misplaced_tokens] == ["KEY_HERE"], "别处还有 ⇒ 错位，不是不可核对"

        改写的理由：判据统一到「行号可比吗」之上（见 ``engine_log.token_verdicts`` 第 4 步），
        「token 在别处还有」不再能把一条不可核对的断言变成判红的断言 —— 但真错配
        （行号可比却对不上）仍然判红，见 :meth:`test_token还在只是不在那一行_算_misplaced`。
        """
        rep = self._report(
            tmp_path,
            effective='a = "OTHER"\n\n\n\nb = "KEY_HERE"\n',  # 5 行
            vanilla='a = "KEY_HERE"\n',  # 1 行 ⇒ 行数不同
            claims=[(1, "KEY_HERE")],
        )
        assert rep.overridden_files == {"gui/panel.gui"}
        assert rep.unverifiable_files == {"gui/panel.gui"}
        assert rep.token_mismatches == [("gui/panel.gui", 1, "KEY_HERE", None)]
        verdicts = rep.token_verdicts()
        assert [v.state for v in verdicts] == [engine_log.TOKEN_UNVERIFIABLE]
        assert [v.kind for v in verdicts] == [engine_log.KIND_LINES_INCOMPARABLE]
        assert verdicts[0].ours == 5, "我们确实在覆盖版第 5 行找到了它 —— 但那不是同一套行号"
        assert "别处有（第 5 行）" in verdicts[0].reason
        # 历史断言在此**显式改写**（不是删掉）——旧文本原样留档在 docstring 里，理由同。
        assert rep.misplaced_tokens == [], "行号不可比 ⇒ 不可核对，不是错位"
        assert [t[2] for t in rep.incomparable_tokens] == ["KEY_HERE"]
        assert rep.absent_tokens == []  # token 确实在，没被误判成"不存在"

    def test_不可核对的判据是行数不同_不是找不到(self, tmp_path: Path) -> None:
        """⚠️ 收口判据落在**文件**上（行数是否相同），不是落在"token 找不找得到"上。

        为什么必须这么定：早期实现把"生效文件里别处还有"也收进 :attr:`unverifiable_tokens` ⇒
        **真的行号错位被判成"不可核对"**、然后被跳过，等于悄悄放过真问题 ——
        与"宁可显式不可核对，也不悄悄放过"正好相反。

        ⚠️ 2026-09-28 收口（本用例的**第二刀**，理由写在 engine_log.token_verdicts 里）：
        上一刀只修好一半 —— 「行数不同 + 别处还有」仍被判红，而命令层判不可核对。
        现在的口径（三态）：

        * 行数**不同** ⇒ 该文件的行号不可比 ⇒ **不可核对**，与 token 在不在别处无关
          （整份没有 = ``stale_no_effective``；别处还有 = ``lines_incomparable``）；
        * 行数**相同** + 生效文件整份没有它、原版也没有 ⇒ **不可核对**
          （``stale_absent``：日志比当前安装旧）；
        * 行数**相同** + 生效文件**别处有**它 ⇒ **真错配**（判红，见
          :meth:`test_token还在只是不在那一行_算_misplaced`）。
        """
        same = self._report(
            tmp_path / "same",
            effective='a = "OTHER"\n',  # 1 行
            vanilla='a = "OTHER"\n',  # 1 行（相同）
            claims=[(1, "KEY_GONE")],
        )
        assert same.line_counts == {"gui/panel.gui": (1, 1)}
        assert same.vanilla_anywhere == {("gui/panel.gui", "KEY_GONE"): None}, "原版也没有"
        assert [t[2] for t in same.absent_tokens] == ["KEY_GONE"]

        # 原版有、生效版没有、行数也不同 ⇒ 不可核对
        shorter = self._report(
            tmp_path / "shorter",
            effective='a = "OTHER"\n',
            vanilla='a = "OTHER"\n\nb = "KEY_GONE"\n',  # 3 行
            claims=[(3, "KEY_GONE")],
        )
        assert shorter.unverifiable_files == {"gui/panel.gui"}
        assert [t[2] for t in shorter.unverifiable_tokens] == ["KEY_GONE"]
        assert shorter.misplaced_tokens == []
        assert shorter.absent_tokens == []
        # 三态与细分：两支不可核对要能分开读（调用方不再自己重判）
        assert [v.state for v in same.token_verdicts()] == [engine_log.TOKEN_UNVERIFIABLE]
        assert [v.kind for v in same.token_verdicts()] == [engine_log.KIND_STALE_ABSENT]
        assert [v.state for v in shorter.token_verdicts()] == [engine_log.TOKEN_UNVERIFIABLE]
        assert [v.kind for v in shorter.token_verdicts()] == [engine_log.KIND_STALE_NO_EFFECTIVE]
        assert shorter.incomparable_tokens == shorter.unverifiable_tokens

    def test_两类互不重叠且加起来等于不一致数(self, tmp_path: Path) -> None:
        rep = self._report(
            tmp_path,
            effective='a = "OTHER"\nb = "IN_FILE"\n',
            vanilla='a = "OTHER"\nb = "IN_FILE"\n',
            claims=[(1, "IN_FILE"), (5, "NOWHERE")],
        )
        assert [t[2] for t in rep.absent_tokens] == ["NOWHERE"]
        assert [t[2] for t in rep.misplaced_tokens] == ["IN_FILE"]
        assert len(rep.token_mismatches) == 2  # 两类之和

    def test_文件不存在时算_absent(self, tmp_path: Path) -> None:
        rep = self._report(
            tmp_path,
            effective=None,
            vanilla='a = "KEY_A"\n',
            claims=[(1, "KEY_A")],
        )
        assert [t[2] for t in rep.absent_tokens] == ["KEY_A"]
        assert rep.tokens == [("gui/panel.gui", 1, "KEY_A", None)]

    def test_概览里两类分列(self, tmp_path: Path) -> None:
        rep = self._report(
            tmp_path,
            effective='a = "OTHER"\nb = "IN_FILE"\n',
            vanilla='a = "OTHER"\nb = "IN_FILE"\n',
            claims=[(1, "IN_FILE"), (5, "NOWHERE")],
        )
        s = rep.summary()
        assert s["token 不一致"] == 2
        assert s["其中 token 整份文件都没有"] == 1
        assert s["其中 token 在但不在那一行"] == 1
        # ⚠️ 2026-09-28：三态读数补上（历史键一个没删 —— 对外读数不许无声消失，B112 同族）
        assert s["其中所在文件被覆盖（行号不可比）"] == 0
        assert s["三态·匹配"] == 0
        # ⚠️ 键名故意不写「真错配」三个字：命令层的用例按文本断言「没有真错配时输出里
        # 不许出现这个词」（tests/test_cli.py:291），而这张表是无条件打印的。
        assert s["三态·判红（行号可比却对不上）"] == 1
        assert s["三态·不可核对"] == 1

    def test_三态互斥且穷尽(self, tmp_path: Path) -> None:
        """每条 token 断言**恰好**落一态，且细分 kind 说得出「为什么不可核对」。

        这是「命令层只消费、不重判」的前提：调用方拿 :meth:`token_verdicts` 就能把
        「匹配 / 真错配 / 不可核对」分开，不必自己再读 ``line_counts`` 判一遍
        （两套判据 = 两套真值，同一份输入两个结论）。
        """
        rep = self._report(
            tmp_path,
            effective='a = "KEY_HIT"\nb = "KEY_ELSEWHERE"\n',
            vanilla='a = "KEY_HIT"\nb = "KEY_ELSEWHERE"\n',  # 行数相同 ⇒ 行号可比
            claims=[(1, "KEY_HIT"), (1, "KEY_ELSEWHERE"), (9, "NOWHERE")],
        )
        verdicts = {v.token: v for v in rep.token_verdicts()}
        assert len(verdicts) == len(rep.tokens) == 3
        assert verdicts["KEY_HIT"].state == engine_log.TOKEN_MATCH
        assert verdicts["KEY_HIT"].kind == engine_log.KIND_MATCHED_EXACT
        assert verdicts["KEY_ELSEWHERE"].state == engine_log.TOKEN_MISPLACED, (
            "行号可比、断言对不上 ⇒ 真错配"
        )
        assert verdicts["KEY_ELSEWHERE"].ours == 2
        assert verdicts["NOWHERE"].state == engine_log.TOKEN_UNVERIFIABLE
        assert verdicts["NOWHERE"].kind == engine_log.KIND_STALE_ABSENT, "两边都没有 ⇒ 日志比安装旧"
        # 老接口的形状没变：as_tuple 就是历史上那四元组（消费面不用改签名）
        assert [v.as_tuple for v in rep.token_verdicts()] == rep.tokens
        # 三态与三个分档属性同源：不一致数 = 真错配 + 不可核对
        assert len(rep.token_mismatches) == len(rep.misplaced_tokens) + len(rep.absent_tokens)
