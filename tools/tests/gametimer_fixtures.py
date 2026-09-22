"""``pdx.gametimer`` 的**共享夹具**（三份用例 + 基准都从这里取）。

为什么要单列一个模块
--------------------
1. 三份用例（``test_gametimer`` / ``test_gametimer_ticktask`` /
   ``test_gametimer_csv``）本来各写一份表头与样本，**夹具漂移过一次**：
   有人在探针里把表头写成 `ms`（真表头是 `milliseconds`），
   结果"表头行被判成坏行"被当成了 bug 查了半天。
2. 基准（``test_benchmarks``）要用**同一份夹具口径**才有可比性 ——
   性能对照表若与用例的口径不同，数字就不是同一件事的对照。

夹具一律按**实测到的真实列结构**造（表头带尾随空格、TAB 分隔、``YYYY_MM_DD``），
并把两个真实瑕疵也做进去：年份位数不足的行、被大小上限截断。
"""

from __future__ import annotations

#: ``gametimer_*.tsv`` 表头原文（**实测带尾随空格**）。
TSV_HEADER = "Game Date \tTime Unit \tSeconds\n"

#: ``ticktask_timings.csv`` 表头原文（**实测无尾随空格，但带 UTF-8 BOM**）。
TT_HEADER = "frame,task,milliseconds,calls,longest_lock\n"

#: 与真实文件一致的 tsv 夹具：表头带尾随空格 + 三种时间单元 + 一个年份位数不足的行。
TSV_SAMPLE = (
    TSV_HEADER
    + "1838_01_01\tYear\t134.303810\n"
    + "1839_01_01\tYear\t161.642236\n"
    + "1836_11_01\tMonth\t9.879664\n"
    + "1837_01_01\tMonth\t13.100000\n"
    + "1837_02_01\tMonth\t11.100000\n"
    + "1840_07_04\tDay\t0.077892\n"
    + "1840_07_04\tDay\t0.075253\n"
    + "1840_07_04\tDay\t0.055261\n"
    + "1840_07_04\tDay\t0.191594\n"
    + "1840_07_05\tDay\t0.200277\n"
)

#: 实测里出现过的任务名（拿真名造样本，别用 `Task1/Task2` 这种假名）。
TT_TASKS: tuple[str, ...] = (
    "RecalculateModifierNodes",
    "UpdateAI",
    "TickDaily",
    "OnActions",
)


def ticktask_text(rows: int = 20000, header: bool = True) -> str:
    """造一份 ``ticktask_timings.csv`` 文本（**默认带表头**）。

    ``frame`` 步长按实测的 6 走、每帧 4 个任务，所以 ``rows`` 条 = ``rows/4`` 帧。
    """
    body = "".join(
        f"{59884134 + (i // 4) * 6},{TT_TASKS[i % 4]},{i % 40 + 1},{i % 5 + 1},{i % 9}\n"
        for i in range(rows)
    )
    return (TT_HEADER if header else "") + body


def gametimer_text(days: int = 5000, header: bool = True) -> str:
    """造一份 ``gametimer_*.tsv`` 文本（**默认带表头**）。

    结构照实测：**每天恰好 4 条 Day 行**（日 / 月 / 年三种单元，Day 占绝大多数），
    日期在 1836-01-01 起的连续日上推进 —— 这样 ``monthly_stats`` 也能吃到真实形状。
    """
    lines: list[str] = [TSV_HEADER.rstrip("\n")] if header else []
    year, month, day = 1836, 1, 1
    for _ in range(days):
        date = f"{year:04d}_{month:02d}_{day:02d}"
        # 实测每天 4 条样本；4 条的秒数各不相同，所以用生成式 + extend
        # （等价于 4 次 append，但合一次调用 —— 这是热路径上的造数据）。
        lines.extend(f"{date}\tDay\t{0.05 + 0.01 * k:.6f}" for k in range(4))
        # 进到下一天（朴素的 30 天月，够用且不会造出 13 月）
        day += 1
        if day > 30:
            day = 1
            month += 1
            if month > 12:
                month = 1
                year += 1
    return "\n".join(lines) + "\n"
