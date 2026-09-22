"""``pdx.gametimer`` 的 **ticktask（逐帧逐任务）** 一侧用例。

为什么要单列：`gametimer.py` 覆盖率只有 67%，缺的**全是 ticktask 这一半** ——
`parse_ticktask_*` / `ticktask_frame_stats` / `ticktask_task_stats` / `summarize_ticktask` /
`ticktask_summary_lines`，而 G-EXIT-3 的性能对照表正是靠这几个函数出数。
（另一半 gametimer tsv 已在 `test_gametimer.py` 里覆盖。）

口径（照模块自己的说明，别在用例里重新发明）：
* 毫秒是**整数** ⇒ 单帧分辨率 1ms（亚毫秒预算只能窗口聚合）；
* 坏行**不静默丢**：进 `bad_lines`；
* 实测文件**带 BOM**（解析要认，且如实标出）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pdx import gametimer as gt

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

HEADER = "frame,task,milliseconds,calls,longest_lock"


def _csv(*rows: str, header: bool = True, bom: bool = False) -> str:
    return ("\ufeff" if bom else "") + ("\n".join(([HEADER] if header else []) + list(rows))) + "\n"


SAMPLE = _csv(
    "100,RecalculateModifierNodes,7,3,2",
    "100,UpdateAI,5,1,0",
    "106,RecalculateModifierNodes,9,3,4",
    "106,UpdateAI,1,1,0",
)


class TestTickTaskLine:
    def test_正常行(self) -> None:
        row = gt.parse_ticktask_line("100,UpdateAI,7,3,2", 1)
        assert row is not None
        assert (row.frame, row.task) == (100, "UpdateAI")
        assert (row.milliseconds, row.calls, row.longest_lock) == (7, 3, 2)

    def test_表头不是数据行(self) -> None:
        assert gt.parse_ticktask_line(HEADER, 1) is None

    @pytest.mark.parametrize(
        "line",
        [
            "",
            "   ",
            "100,UpdateAI,7,3",  # 字段少
            "100,UpdateAI,七,3,2",  # 毫秒不是整数
            "abc,UpdateAI,7,3,2",  # 帧号不是整数
            "100,,7,3,2",  # 任务名空
        ],
    )
    def test_坏行给_None(self, line: str) -> None:
        assert gt.parse_ticktask_line(line, 9) is None

    def test_尾随空格被容忍(self) -> None:
        row = gt.parse_ticktask_line(" 100 , UpdateAI , 7 , 3 , 2 ", 1)
        assert row is not None
        assert row.task == "UpdateAI"


class TestTickTaskHeader:
    def test_带与不带尾随空格都认(self) -> None:
        assert gt.is_ticktask_header(HEADER)
        assert gt.is_ticktask_header(HEADER + " ")

    def test_别的行不是表头(self) -> None:
        assert not gt.is_ticktask_header("100,UpdateAI,7,3,2")


class TestTickTaskParse:
    def test_整份解析(self) -> None:
        result = gt.parse_ticktask_tsv(SAMPLE)
        assert len(result.rows) == 4
        assert result.header_present is True
        assert result.bad_lines == []
        assert result.bom_present is False
        assert result.frames == [100, 106]

    def test_带_BOM_的文件也认(self, tmp_path: Path) -> None:
        # BOM 只有走**文件**那一层才判得出来（`parse_ticktask_tsv` 拿到的已经是 str）
        path = tmp_path / "ticktask_timings.csv"
        path.write_bytes(("\ufeff" + HEADER + "\n100,UpdateAI,1,1,0\n").encode("utf-8"))
        result = gt.parse_ticktask_file(path)
        assert result.bom_present is True
        assert len(result.rows) == 1, "BOM 不能把表头带歪、也不能吃掉第一行"

    def test_坏行进清单不静默丢(self) -> None:
        result = gt.parse_ticktask_tsv(_csv("100,UpdateAI,1,1,0", "这不是一行 CSV"))
        assert len(result.rows) == 1
        assert len(result.bad_lines) == 1

    def test_没有表头也照解析(self) -> None:
        result = gt.parse_ticktask_tsv(_csv("100,UpdateAI,1,1,0", header=False))
        assert len(result.rows) == 1
        assert result.header_present is False

    def test_空文件不炸(self) -> None:
        result = gt.parse_ticktask_tsv("")
        assert result.rows == []
        assert result.frames == []

    def test_从文件读(self, tmp_path: Path) -> None:
        path = tmp_path / "ticktask_timings.csv"
        path.write_text(SAMPLE, encoding="utf-8-sig")
        result = gt.parse_ticktask_file(path)
        assert len(result.rows) == 4

    def test_文件不存在时报错(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            gt.parse_ticktask_file(tmp_path / "没有这个文件.csv")


class TestTickTaskStats:
    def test_按帧聚合是求和而不是数行数(self) -> None:
        frames = gt.ticktask_frame_stats(gt.parse_ticktask_tsv(SAMPLE))
        assert [f.frame for f in frames] == [100, 106]
        first = frames[0]
        assert first.tasks == 2
        assert first.total_ms == 12  # 7 + 5，不是 2
        assert first.worst_task == "RecalculateModifierNodes"
        assert first.worst_ms == 7

    def test_按任务聚合按总毫秒降序(self) -> None:
        tasks = gt.ticktask_task_stats(gt.parse_ticktask_tsv(SAMPLE))
        assert [t.task for t in tasks] == ["RecalculateModifierNodes", "UpdateAI"]
        top = tasks[0]
        assert top.frames == 2
        assert top.total_ms == 16
        assert top.mean_ms == pytest.approx(8.0)
        assert top.worst_ms == 9
        assert top.worst_lock == 4


class TestTickTaskSummary:
    def test_摘要字典的关键键都在(self, tmp_path: Path) -> None:
        path = tmp_path / "ticktask_timings.csv"
        path.write_text(SAMPLE, encoding="utf-8-sig")
        data = gt.summarize_ticktask(path)
        assert data["rows"] == 4
        assert data["frames"] == 2
        assert data["tasks"] == 2
        assert data["frame_first"] == 100
        assert data["frame_last"] == 106
        # `worst_task` 是**格式化好的一行**（含耗时与最长锁），不是裸任务名
        assert str(data["worst_task"]).startswith("RecalculateModifierNodes")
        # 整数毫秒 ⇒ 单帧预算只能窗口聚合：这两个键就是那条口径的机器可读形式
        assert "millisecond_resolution" in data
        assert "per_frame_measurable" in data
        per_frame = data["per_frame_total_ms"]
        assert isinstance(per_frame, dict)
        assert per_frame["min"] == 10  # 第二帧 9 + 1
        assert per_frame["max"] == 12  # 第一帧 7 + 5

    def test_人能读的几行里点出最贵的任务(self, tmp_path: Path) -> None:
        path = tmp_path / "ticktask_timings.csv"
        path.write_text(SAMPLE, encoding="utf-8-sig")
        lines = gt.ticktask_summary_lines(path)
        text = "\n".join(lines)
        assert lines, "至少要给出几行结论"
        assert "RecalculateModifierNodes" in text
        # 整数毫秒的边界要如实说出来（亚毫秒预算只能靠窗口聚合）
        assert "毫秒" in text or "ms" in text
