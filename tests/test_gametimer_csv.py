"""``pdx.gametimer`` 的**切分口径**用例：为什么用标准库 :mod:`csv`、以及它换来了什么。

为什么单列一个文件
------------------
`test_gametimer.py` / `test_gametimer_ticktask.py` 管的是"字段怎么解释"，
这里管的是"**一行怎么切成字段**" —— 2026-09-21 把两份解析器的手写
`line.split("\\t")` / `line.split(",")` 换成标准库 `csv` 之后，
口径变了（引号、跨行记录、畸形行），必须有用例把这些差别钉住，
否则下次谁"顺手优化"回 `str.split` 就会静默解析错。

三个**只有 csv 才对**的点（旧手写版全错，且错得很安静）：

1. **引号里的分隔符**：`"Foo, Bar"` 在旧版被切成两段，字段数变 6 → 整行丢进坏行；
   新版是一个字段。
2. **引号里含换行**：旧版按物理行切，一条记录变两条垃圾；新版是一条记录，
   且后续行的行号仍然对得上（行号取自 `csv.reader.line_num`）。
3. **引号不闭合**：旧版当成普通字段静默收下；新版 `strict=True` 抛
   :class:`csv.Error`，如实记一条坏行并**停止往下解析** ——
   继续用非严格模式会把后续行拼进同一条记录，那才是真的编数据。

另外把**没引号的行必须与 `str.split` 完全等价**钉成不变量：
这条不成立的话，"换 csv"就变成了"改口径"，而不是"换实现"。
"""

from __future__ import annotations

import csv
import itertools

import pytest

from pdx import gametimer as gt

#: 两份解析器的表头（ticktask 一侧必须用**真表头**，
#: 曾经拿 `ms` 当缩写跑证明，结果表头行被正确判成坏行，反而看不出问题）。
TSV_HEADER = "Game Date \tTime Unit \tSeconds\n"
TT_HEADER = ",".join(gt.TICKTASK_HEADER) + "\n"


def _tt(*lines: str) -> str:
    return TT_HEADER + "".join(line + "\n" for line in lines)


def _tsv(*lines: str) -> str:
    return TSV_HEADER + "".join(line + "\n" for line in lines)


class TestQuotedDelimiter:
    """引号里的分隔符不能再当分隔符。"""

    def test_任务名带逗号_旧手写版会切错(self) -> None:
        row = gt.parse_ticktask_line('100,"Foo, Bar",7,3,2', 1)
        assert row is not None
        assert row.task == "Foo, Bar"
        assert (row.frame, row.milliseconds, row.calls, row.longest_lock) == (100, 7, 3, 2)

    def test_对照一下手写切分确实切错(self) -> None:
        """把"旧实现为什么会错"钉住 —— 免得有人觉得引号是多余的讲究。

        同一个字符串：手写 `split` 切出 **6 段**（列数 = 6 ≠ 5 ⇒ 整行作废），
        标准库 csv 切出 **5 段**且任务名完整。所以那一行在新实现里是**好行**。
        """
        assert len(["100", '"Foo', ' Bar"', "7", "1", "0"]) == 6  # 手写：6 段，作废
        result = gt.parse_ticktask_tsv(_tt('100,"Foo, Bar",7,1,0'))
        assert result.bad_lines == []
        assert [r.task for r in result.rows] == ["Foo, Bar"]

    def test_tsv_一侧引号里的制表符同样保住(self) -> None:
        result = gt.parse_tsv(_tsv('1838_01_01\t"A\tB"\t0.5'))
        assert [(r.raw_date, r.unit) for r in result.rows] == [("1838_01_01", "A\tB")]
        assert result.bad_lines == []

    def test_字段中间的引号是普通字符(self) -> None:
        """`csv` 只在**字段开头**把 `"` 当引号 —— 与"不 strip"的老口径一致。"""
        row = gt.parse_ticktask_line('100,a"b,7,1,0', 1)
        assert row is not None
        assert row.task == 'a"b'


class TestQuotedNewline:
    """引号里含换行的记录：一条记录、跨两个物理行，行号仍要对。"""

    def test_一条记录而不是两条(self) -> None:
        result = gt.parse_ticktask_tsv(_tt("100,Alpha,1,1,0", '101,"Beta', 'Gamma",2,1,0'))
        assert [r.frame for r in result.rows] == [100, 101]
        assert result.rows[1].task == "Beta\nGamma"

    def test_后续行的行号仍然对(self) -> None:
        """跨行记录占了 3、4 两个物理行，下一行必须是 5。"""
        result = gt.parse_ticktask_tsv(
            _tt("100,Alpha,1,1,0", '101,"Beta', 'Gamma",2,1,0', "102,Delta,3,1,0")
        )
        assert [(r.frame, r.line_no) for r in result.rows] == [
            (100, 2),
            (101, 3),
            (102, 5),
        ]

    def test_数据行不会被误判成表头(self) -> None:
        """跨行字段里含换行 ⇒ 只比字段内容是不够的，必须再加「第一行」这个条件。

        这条用例就是那个 bug 的回归测试：去掉 `total_lines == 1` 之后，
        一条**恰好长得像表头**的数据行会被当成表头吃掉，而且不报错。
        """
        # `101,"a,b"` 只有 2 个字段（不是合法数据行），但它**也不等于表头**，
        # 所以必须进 bad_lines 而不是被当成表头吞掉。
        result = gt.parse_ticktask_tsv(_tt("100,Alpha,1,1,0", '101,"a,b"', "c", "102,Delta,3,1,0"))
        assert result.header_present is True
        assert [r.frame for r in result.rows] == [100, 102]
        assert [n for n, _ in result.bad_lines] == [3, 4]
        assert result.bad_lines[0][1] == '101,"a,b"'  # 存的是真原文

    def test_跨行字段不是表头(self) -> None:
        """跨行字段里放进"表头原文"（以**空格**连接，避免逗号改变字段数），
        解析器也不许把它当第二个表头。

        ⚠️ 构造这条夹具踩过的坑，写下来免得后人再踩：
        1. 一条 5 字段记录里，字段之间的 4 个逗号**必须是分隔符**；想放进字段内容的
           逗号必须整体加引号，而**加了引号之后那些逗号就不再是分隔符了** ——
           于是 `101,"x\\nframe,task,..."` 根本不是 5 字段记录，而是 2 字段。
           所以这里用"空格连接的表头原文"来逼近。
        2. 跨行的那个字段必须放在 `task` 列（第 2 列）：放到别的列上，
           它会被当成 `milliseconds/calls/longest_lock` 去 `int()`，直接判成坏行 ——
           这条我调试时踩了第三次。
        """
        payload = " ".join(gt.TICKTASK_HEADER)
        text = _tt("100,Alpha,1,1,0") + f'101,"x\n{payload}",2,3,4\n'
        result = gt.parse_ticktask_tsv(text)
        assert len(result.rows) == 2
        second = result.rows[1]
        assert (second.frame, second.milliseconds, second.calls, second.longest_lock) == (
            101,
            2,
            3,
            4,
        )
        assert second.task == f"x\n{payload}"
        assert second.line_no == 3  # 跨行记录报的是**起始**行号
        assert result.bad_lines == []

    def test_不带引号的表头原文只会变成畸形行(self) -> None:
        """`task` 里裸着写逗号 ⇒ 字段数超过 5 ⇒ 畸形行，**不会**被当表头吞掉。

        用例里那条 `task` 写成「引号翻倍」形式（内部引号各翻一倍），
        切出来是 `['101', '"x"', 'a', 'b', 'c']` —— 恰好 5 个字段，
        但它是一条**数据行**（文件第 2 行），必须进 bad_lines 而不是当表头。
        """
        result = gt.parse_ticktask_tsv(_tt('101,"""x""",a,b,c'))
        assert result.rows == []
        assert [n for n, _ in result.bad_lines] == [2]

    def test_单行入口也认跨行记录(self) -> None:
        """``parse_ticktask_line`` 收的是"一行"，但 csv 的一条记录可以跨物理行 ——
        它照样要认（否则整份解析与单行解析会给出不同结论）。
        """
        row = gt.parse_ticktask_line('101,"multi\nline",2,3,4', 1)
        assert row is not None
        assert (row.frame, row.milliseconds, row.calls, row.longest_lock) == (101, 2, 3, 4)
        assert row.task == "multi\nline"

    def test_字段与列一一对应(self) -> None:
        """五列各给一个**互不相同**的值，逐列验映射。

        为什么要专门一条：这一轮排查里我三次把夹具的列顺写错（`ms` 当表头、
        `task` 在第 2 列却写成第 4 列），而当时的用例都"通过"了 ——
        因为老用例里每列的值都长得差不多。互不相同的值才抓得住串列。
        """
        row = gt.parse_ticktask_line("11,SomeTask,22,33,44", 1)
        assert row is not None
        assert (row.frame, row.task, row.milliseconds, row.calls, row.longest_lock) == (
            11,
            "SomeTask",
            22,
            33,
            44,
        )

    def test_tsv_一侧字段也一一对应(self) -> None:
        row = gt.parse_line("1838_01_01\tYear\t134.303810", 1)
        assert row is not None
        assert (row.raw_date, row.year, row.month, row.day, row.unit, row.seconds) == (
            "1838_01_01",
            1838,
            1,
            1,
            "Year",
            134.303810,
        )

    def test_tsv_一侧同样记住跨行(self) -> None:
        result = gt.parse_tsv(_tsv('1838_01_01\t"A', 'B"\t0.5', "1840_07_04\tDay\t0.1"))
        assert [(r.raw_date, r.line_no) for r in result.rows] == [
            ("1838_01_01", 2),
            ("1840_07_04", 4),
        ]
        assert result.rows[0].unit == "A\nB"


class TestMalformedQuote:
    """引号不闭合：必须被抓住，而且**不许**把后续行拼成假数据。"""

    def test_整份文件解析到畸形行就停(self) -> None:
        result = gt.parse_ticktask_tsv(_tt("100,Alpha,1,1,0", '101,"Beta,2,1,0', "102,Delta,3,1,0"))
        assert [r.frame for r in result.rows] == [100]  # 畸形行之后不再产出
        assert len(result.bad_lines) == 1
        line_no, raw = result.bad_lines[0]
        assert line_no == 3
        assert "csv 解析中断" in raw
        assert "从第 3 行开始" in raw  # 记录起始行
        assert "实际读到第 4 行" in raw  # csv 读到哪里才发现

    def test_非严格模式会把后续行拼进来所以不能用(self) -> None:
        """这条是"为什么必须 strict=True"的证据：非严格模式**静默**吃掉下一行，
        而且把两行**首尾相接**（连换行都没有），拼出一条根本不存在的记录。
        """
        loose = list(csv.reader(['101,"Beta', "102,Delta,3,1,0"]))
        assert loose == [["101", "Beta102,Delta,3,1,0"]]  # 实测：两条并成一条，无换行
        with pytest.raises(csv.Error):
            list(csv.reader(['101,"Beta', "102,Delta,3,1,0"], strict=True))

    def test_单行且引号不闭合也算畸形(self) -> None:
        """被打断的文件往往**最后一行**就是断口，这时非严格模式同样是静默降级。"""
        assert list(csv.reader(['101,"Beta'])) == [["101", "Beta"]]  # 非严格：引号被悄悄丢掉
        with pytest.raises(csv.Error):
            list(csv.reader(['101,"Beta'], strict=True))

    def test_单行入口抛错而不是返回_None(self) -> None:
        """`parse_*_line` 的契约是"不合格给 None"，但畸形引号属于**结构性**错误：
        单行入口直接抛 :class:`csv.Error`（整份解析那条路接住它并记坏行）。
        """
        with pytest.raises(csv.Error):
            gt.parse_ticktask_line('101,"Beta', 1)
        with pytest.raises(csv.Error):
            gt.parse_line('1838_01_01\t"A\t0.5', 1)

    def test_tsv_一侧也一样(self) -> None:
        result = gt.parse_tsv(_tsv('1838_01_01\t"A\t0.5', "1840_07_04\tDay\t0.1"))
        assert result.rows == []
        assert len(result.bad_lines) == 1
        assert "csv 解析中断" in result.bad_lines[0][1]

    def test_坏行号用逻辑计数而不是物理行号(self) -> None:
        """坏行记的是"第几条非空记录"，与 `total_lines` 同一口径，便于对照。"""
        result = gt.parse_ticktask_tsv(_tt("100,Alpha,1,1,0", "101,Delta,3,1,0", '102,"X'))
        assert [r.frame for r in result.rows] == [100, 101]
        assert result.bad_lines[0][0] == 4  # 表头 + 3 条数据


class TestNoQuoteEquivalence:
    """**不变量**：没有引号的行，csv 切出来必须与 `str.split` 逐字相同。

    不成立的话，"换标准库"就变成了"改口径"；成立才能说这次改动
    **只换了实现、没改语义**。旧实现就是把 `split` 的结果 strip 后用的，
    所以这里连 strip 也一起验。
    """

    @pytest.mark.parametrize(
        "line",
        [
            "1838_01_01\tYear\t134.303810",
            " 1838_01_01 \t Year \t 134.3 ",  # 前后空格（旧版 strip）
            "1838_01_01\tYear\t",  # 末列空
            "\t\t",  # 全空
            "a\tb",  # 列数不对
            "a\tb\tc\td",  # 列数过多
            "1840_07_04\tDay\t0.077892\t",  # 尾随分隔符
        ],
    )
    def test_tsv(self, line: str) -> None:
        expected = [p.strip() for p in line.split("\t")]
        got = [p.strip() for p in gt._tokens_of_line(line, "\t")[0]]
        assert got == expected

    @pytest.mark.parametrize(
        "line",
        [
            "100,UpdateAI,7,3,2",
            " 100 , UpdateAI , 7 , 3 , 2 ",
            "100,UpdateAI,7,3,",
            ",,,,",
            "100,UpdateAI",
            "100,UpdateAI,7,3,2,9",
        ],
    )
    def test_ticktask(self, line: str) -> None:
        expected = [p.strip() for p in line.split(",")]
        got = [p.strip() for p in gt._tokens_of_line(line, ",")[0]]
        assert got == expected

    def test_生成式穷举_无引号字符(self) -> None:
        """把"无引号"这个前提下的组合穷举一遍（含制表符与逗号同时出现）。

        组合数 = (5¹ + 5² + 5³) − 3 个全空白组合 = 152 条，再 ×2 种分隔符 = 304 次比较；
        其中被 `strip()` 判空而跳过的更多（例如 `"a "` 不算），实测跑 282 次。
        """
        alphabet = ("a", ",", "\t", "1", " ")
        checked = 0
        for n in (1, 2, 3):
            for combo in itertools.product(alphabet, repeat=n):
                line = "".join(combo)
                if line.strip() == "":
                    continue  # 空行不产出，另有用例
                for delim in (",", "\t"):
                    expected = [p.strip() for p in line.split(delim)]
                    got = [p.strip() for p in gt._tokens_of_line(line, delim)[0]]
                    assert got == expected, (line, delim)
                    checked += 1
        assert checked == 282  # 别让 alphabet 被改小之后悄悄退化成没跑


class TestHelpers:
    """切分辅助层自己的口径。"""

    def test_行偏移表覆盖每一行(self) -> None:
        text = "a\nbb\n\nccc"
        assert gt._line_offsets(text) == [0, 2, 5, 6, 9]

    def test_行偏移表对末尾换行也算一行(self) -> None:
        assert gt._line_offsets("a\n") == [0, 2]

    def test_取原文保留制表符与前后空格(self) -> None:
        """`bad_lines` 存的是**真原文**（只去行终止符），不是切分后的字段。"""
        text = "x\n 1840_07_04 \t Day \t abc \n"
        offsets = gt._line_offsets(text)
        assert gt._raw_at(text, offsets, 2) == " 1840_07_04 \t Day \t abc "

    def test_取原文去掉_crlf(self) -> None:
        text = "x\r\ny\r\n"
        offsets = gt._line_offsets(text)
        assert gt._raw_at(text, offsets, 2) == "y"

    def test_最后一行没有终止符也能取(self) -> None:
        text = "x\ny"
        offsets = gt._line_offsets(text)
        assert gt._raw_at(text, offsets, 2) == "y"

    def test_坏行原文与输入逐字一致(self) -> None:
        bad = " 1840_07_04 \t Day \t abc "
        result = gt.parse_tsv(_tsv("1840_07_04\tDay\t0.1", bad))
        assert result.bad_lines == [(3, bad)]

    def test_空行不产出但行号按物理行走(self) -> None:
        """行号一律是**物理行号**（`csv.reader.line_num` 的口径），空行照数。

        为什么不让它按"第几条记录"走：`bad_lines` 里存的是原文，行号要能直接
        拿到文件里去找那一行；报"第 2 条"而文件里在第 5 行，排查时会白跑一趟。
        """
        result = gt.parse_ticktask_tsv(TT_HEADER + "100,A,1,1,0\n\n\n101,B,2,1,0\n")
        assert [r.line_no for r in result.rows] == [2, 5]
        assert result.total_lines == 3  # 表头 + 2 条数据；**空行不数**（旧口径）
        assert result.bad_lines == []

    def test_total_lines_不数空行但数表头(self) -> None:
        """旧实现就是这个口径（`if not raw.strip(): continue` 在自增**之前**），
        保留它：坏行的行号跟着 `total_lines` 走，改了会与历史记录对不上。
        """
        result = gt.parse_tsv(_tsv("", "1840_07_04\tDay\t0.1"))
        assert result.total_lines == 2  # 表头 + 1 条数据（中间那个空行不数）
        assert len(result.rows) == 1

    def test_逻辑行号换算成物理行号(self) -> None:
        text = "a\n\nb\n\n\nc\n"
        offsets = gt._line_offsets(text)
        assert [gt._physical_line(text, offsets, n) for n in (1, 2, 3)] == [1, 3, 6]

    def test_换算越界给文件末行而不是炸(self) -> None:
        """畸形行在文件末尾时逻辑计数会多出一格：这时给"文件末行"，
        不许抛异常（解析已经在收尾路径上了，再炸就丢了整份文件的结论）。
        """
        text = "a\nb\n"
        offsets = gt._line_offsets(text)
        assert gt._physical_line(text, offsets, 3) == 3
        assert gt._physical_line(text, offsets, 99) == 3

    def test_制表符分隔的逗号文件不受影响(self) -> None:
        """delimiter 必须真的传下去（两边不能共用同一个默认值）。"""
        assert gt._tokens_of_line("a,b\tc", "\t") == [["a,b", "c"]]
        assert gt._tokens_of_line("a,b\tc", ",") == [["a", "b\tc"]]
