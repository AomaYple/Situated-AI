"""H1 实验结果的分析器（阶段 2）。

探针（`v3 h1-probe` 生成）每月给每个国家写几行：

```text
ZZPROBE H1;RUN;storm
ZZPROBE H1;DOSE;HIGH;Russia
ZZPROBE H1;POLI;sitai_probe_reform;Russia
ZZPROBE H1;ADMI;agricultural_expansion;Russia
ZZPROBE H1;DIPL;maintain_power_balance;Russia
ZZPROBE H3;TRY;block;HED
```

（分隔符是 `;`、国名用 `[THIS.GetCountry.GetNameNoFormatting]` —— 两条都是实测教训：
`|` 会被 loc 解析器当控制符刷出 `Data error`，`[This.GetTag]` 不是合法 loc 命令。）

本模块做四件事：

1. **解析 → 按 (启动段, 时间戳, 国名) 配对**。`RUN` 行把多次启动切开 ——
   日志轮转会把不同次启动的行留在同一目录里，混着统计等于把两次实验的样本池倒在一起。
2. **剂量反应**：四个随机分组唯一的差异是探针牌的 `weight`，所以
   P(落在我们的牌) 随剂量上升 = 权重确实在推动落点（G1）。三个槽位各算一遍。
3. **重抽节奏**：每个槽位每个国家相邻两次观测之间换没换牌。自然变体下这就是
   引擎的真实节奏（设计要用它判断"喂输入能不能在战役尺度上改变 AI"）。
4. **附带读数**：第四槽（B7）、无 loc 牌（B10）、`add_ai_strategy` 语法（H3）。
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pdx import config

if TYPE_CHECKING:
    from pathlib import Path

#: 三个槽位（顺序 = 报告顺序）。
SLOTS = ("political", "administrative", "diplomatic")

#: 槽位 → 日志行里的短标签。
SLOT_SHORT = {"political": "POLI", "administrative": "ADMI", "diplomatic": "DIPL"}

#: 日志短标签 → 槽位。
SHORT_SLOT = {short: slot for slot, short in SLOT_SHORT.items()}

#: 我们的政治槽探针牌（出现在 POLI 行里，不含 `ai_strategy_` 前缀）。
PROBE_CARD = "sitai_probe_reform"

#: 无本地化 / 无图标牌（B10）。
NOLOC_CARD = "sitai_probe_noloc"

#: 槽位 → 我们的探针牌标签（生成器里的牌名去掉 `ai_strategy_` 前缀）。
PROBE_CARDS = {
    "political": PROBE_CARD,
    "administrative": "sitai_probe_admin",
    "diplomatic": "sitai_probe_diplo",
}

#: 第四槽候选（B7）。
FOURTH_CARD = "sitai_probe_fourth"

#: 剂量组顺序（从低到高，便于看单调性）。
DOSE_ORDER = ("CTRL", "LOW", "MID", "HIGH")

#: 四种剂量对应的权重（生成器与本模块共用这一份：`pdx.h1_probe` 生成牌文件）。
DOSE_WEIGHT = {"CTRL": 10, "LOW": 50, "MID": 100, "HIGH": 250}

_LINE = re.compile(
    r"^\[(?P<stamp>\d{2}:\d{2}:\d{2})\].*?ZZPROBE (?P<family>H1|H3);(?P<kind>[A-Z]+);(?P<rest>.+?)\s*$"
)

#: 老格式（v1 探针）只有 `CARD` 一种落点行，等价于政治槽。
_LEGACY_KIND = "CARD"


@dataclass(frozen=True, slots=True)
class Sample:
    """一次观测：某月某国的剂量组与三个槽位当时的落点。"""

    run: int
    order: int
    stamp: str
    tag: str
    dose: str
    cards: dict[str, str]
    fourth: bool

    @property
    def card(self) -> str:
        """政治槽落点（历史字段名，不少调用点还在用）。"""
        return self.cards.get("political", "none")


@dataclass(slots=True)
class Group:
    """一个剂量组的统计（政治槽口径，G1 用它）。"""

    dose: str
    observations: int = 0
    probe_hits: int = 0
    countries: set[str] = field(default_factory=set)

    @property
    def rate(self) -> float:
        return self.probe_hits / self.observations if self.observations else 0.0

    def wilson(self, z: float = 1.96) -> tuple[float, float]:
        """Wilson 得分区间（小样本友好）。"""
        return wilson_interval(self.probe_hits, self.observations, z=z)


@dataclass(frozen=True, slots=True)
class Cell:
    """一个 (槽位, 剂量) 格子。"""

    dose: str
    observations: int
    hits: int

    @property
    def rate(self) -> float:
        return self.hits / self.observations if self.observations else 0.0

    def wilson(self, z: float = 1.96) -> tuple[float, float]:
        return wilson_interval(self.hits, self.observations, z=z)

    def implied_rival_weight(self) -> float | None:
        """反推"等效竞争权重"：假设按权重抽一次，``p = W / (W + S)`` → ``S = W(1-p)/p``。

        这是设计上真正要用的数字：要知道该给多大的权重，先得知道牌池里其它牌
        加起来等效多少权重。份额贴近 0/1 时估计不稳，返回 ``None``。
        """
        if not self.observations or not 0.02 < self.rate < 0.98:
            return None
        weight = DOSE_WEIGHT.get(self.dose)
        if weight is None:
            return None
        return weight * (1 - self.rate) / self.rate


@dataclass(frozen=True, slots=True)
class Tempo:
    """一个槽位的重抽节奏（相邻两次观测之间换牌的比例）。"""

    slot: str
    observations: int
    pairs: int
    changes: int
    top: tuple[tuple[str, int], ...]

    @property
    def rate(self) -> float:
        return self.changes / self.pairs if self.pairs else 0.0


@dataclass(frozen=True, slots=True)
class Result:
    """整次实验的结果。"""

    runs: tuple[str, ...]
    samples: tuple[Sample, ...]
    groups: dict[str, Group]
    by_slot: dict[str, dict[str, Cell]]
    tempo: dict[str, Tempo]
    fourth_hits: int
    noloc_hits: int
    h3_events: tuple[str, ...]
    unpaired: int

    @property
    def months(self) -> int:
        return len({s.stamp for s in self.samples})

    @property
    def tags(self) -> int:
        return len({s.tag for s in self.samples})

    @property
    def variant(self) -> str:
        return self.runs[-1] if self.runs else "unknown"


def wilson_interval(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 得分区间（小样本比正态近似稳）。"""
    if total <= 0:
        return (0.0, 0.0)
    p = hits / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass(frozen=True, slots=True)
class Parsed:
    """解析结果：启动段、观测行、H3 标记、未配对计数。"""

    runs: tuple[str, ...]
    rows: dict[tuple[int, str, str], dict[str, str]]
    order: tuple[tuple[int, str, str], ...]
    h3_events: tuple[str, ...]
    unpaired: int


def parse_lines(text: str) -> Parsed:
    """把日志文本解析成按启动段分组的观测行。

    ``rows`` 的键是 ``(启动段, 时间戳, 国名)``；``order`` 是行的出现顺序
    （日志顺序就是时间顺序，比拿 `HH:MM:SS` 排序更稳 —— 跨零点也不会错）。
    """
    runs: list[str] = []
    rows: dict[tuple[int, str, str], dict[str, str]] = {}
    order: list[tuple[int, str, str]] = []
    h3: list[str] = []
    current = -1
    for line in text.splitlines():
        m = _LINE.search(line)
        if not m:
            continue
        kind = m.group("kind")
        parts = m.group("rest").split(";")
        if m.group("family") == "H3":
            # H3 行的 `kind` 就是阶段（TRY/DONE），拼回去才是完整标记
            h3.append(f"{kind};{m.group('rest')}")
            continue
        if kind == "RUN":
            runs.append(parts[0])
            current = len(runs) - 1
            continue
        if current < 0:  # 老格式没有 RUN 行 → 当作第一段，保持向后兼容
            runs.append("unknown")
            current = 0
        if kind == _LEGACY_KIND:
            kind, parts = "POLI", [parts[0], parts[1]]
        if len(parts) < 2:
            continue
        key = (current, m.group("stamp"), parts[-1])
        if key not in rows:
            rows[key] = {}
            order.append(key)
        rows[key][kind] = parts[0]

    unpaired = sum(1 for row in rows.values() if "DOSE" not in row or "POLI" not in row)
    return Parsed(
        runs=tuple(runs),
        rows=rows,
        order=tuple(order),
        h3_events=tuple(h3),
        unpaired=unpaired,
    )


def _samples(parsed: Parsed) -> tuple[list[Sample], int]:
    """只取**最后一段**启动的观测（多段混在一起统计是错的）。"""
    last = len(parsed.runs) - 1 if parsed.runs else 0
    samples: list[Sample] = []
    unpaired = 0
    for index, key in enumerate(parsed.order):
        run, stamp, tag = key
        row = parsed.rows[key]
        if run != last:
            continue
        dose = row.get("DOSE")
        if dose is None:
            unpaired += 1
            continue
        cards = {slot: row[short] for slot, short in SLOT_SHORT.items() if short in row}
        if "political" not in cards:
            unpaired += 1
            continue
        samples.append(
            Sample(
                run=run,
                order=index,
                stamp=stamp,
                tag=tag,
                dose=dose,
                cards=cards,
                fourth=row.get("FOURTH") == "active",
            )
        )
    return samples, unpaired


def _tempo(samples: list[Sample], slot: str) -> Tempo:
    """相邻两次观测之间换牌的比例（按国家分别看，避免把国家间差异算成变化）。"""
    per_tag: dict[str, list[str]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    pairs = 0
    changes = 0
    observations = 0
    for sample in sorted(samples, key=lambda s: s.order):
        value = sample.cards.get(slot)
        if value is None:
            continue
        observations += 1
        counts[value] += 1
        previous = per_tag[sample.tag]
        if previous:
            pairs += 1
            if previous[-1] != value:
                changes += 1
        previous.append(value)
    top = tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3])
    return Tempo(slot=slot, observations=observations, pairs=pairs, changes=changes, top=top)


def analyze_text(text: str) -> Result:
    """从日志文本算出全部统计。"""
    parsed = parse_lines(text)
    samples, unpaired = _samples(parsed)

    groups: dict[str, Group] = {dose: Group(dose=dose) for dose in DOSE_ORDER}
    by_slot: dict[str, dict[str, Cell]] = {
        slot: {dose: Cell(dose=dose, observations=0, hits=0) for dose in DOSE_ORDER}
        for slot in SLOTS
    }
    counters: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    fourth = 0
    noloc = 0
    for sample in samples:
        group = groups.setdefault(sample.dose, Group(dose=sample.dose))
        group.observations += 1
        group.countries.add(sample.tag)
        if sample.card == PROBE_CARD:
            group.probe_hits += 1
        if sample.card == NOLOC_CARD:
            noloc += 1
        if sample.fourth:
            fourth += 1
        for slot, label in sample.cards.items():
            if slot not in by_slot:
                continue
            bucket = counters[(slot, sample.dose)]
            bucket[0] += 1
            if label == PROBE_CARDS.get(slot):
                bucket[1] += 1

    for slot, cells in by_slot.items():
        for dose in cells:
            observations, hits = counters[(slot, dose)]
            cells[dose] = Cell(dose=dose, observations=observations, hits=hits)

    return Result(
        runs=parsed.runs,
        samples=tuple(samples),
        groups=groups,
        by_slot=by_slot,
        tempo={slot: _tempo(samples, slot) for slot in SLOTS},
        fourth_hits=fourth,
        noloc_hits=noloc,
        h3_events=parsed.h3_events,
        unpaired=unpaired,
    )


def log_files(log_dir: Path | None = None) -> list[Path]:
    """日志目录里可能含 H1 行的文件（含轮转副本）。"""
    base = log_dir or config.USERDIR / "logs"
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob("*.log") if p.is_file())


def analyze(log_dir: Path | None = None) -> Result:
    """读整个日志目录并分析（轮转文件也算，避免漏掉早期月份）。"""
    chunks = [path.read_text(encoding="utf-8", errors="replace") for path in log_files(log_dir)]
    return analyze_text("\n".join(chunks))


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Markdown 表（rich 会渲染成真表格）。"""
    return [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
        *["| " + " | ".join(row) + " |" for row in rows],
    ]


def _verdict(cells: dict[str, Cell]) -> str:
    """CTRL vs HIGH 的区间是否分开（区间不重叠才算过）。"""
    ctrl = cells.get("CTRL")
    high = cells.get("HIGH")
    if ctrl is None or high is None or not ctrl.observations or not high.observations:
        return "样本不足"
    ctrl_lo, ctrl_hi = ctrl.wilson()
    high_lo, high_hi = high.wilson()
    if high_lo > ctrl_hi:
        return "✅ 区间不重叠"
    if high_hi < ctrl_lo:
        return "❌ 方向相反"
    if high.rate > ctrl.rate:
        return "⚠️ 方向对但区间重叠"
    return "❌ 无差异"


def format_report(result: Result) -> str:
    """把结果排成人读的表（含 G1 判定）。"""
    runs_note = "、".join(f"`{run}`" for run in result.runs) or "（无 RUN 标记）"
    lines = [
        f"**运行**：{runs_note}（多段时只统计最后一段）",
        (
            f"样本：**{len(result.samples)}** 条观测 / {result.tags} 个国家 / "
            f"{result.months} 个不同时间戳（未配对 {result.unpaired} 条）"
        ),
        "",
        "### 1. G1：权重能不能推动落点（政治槽，主假设）",
        "",
    ]
    rows = []
    for dose in DOSE_ORDER:
        group = result.groups.get(dose)
        if group is None or not group.observations:
            rows.append([dose, str(DOSE_WEIGHT.get(dose, "?")), "0", "0", "—", "—", "0"])
            continue
        lo, hi = group.wilson()
        rows.append(
            [
                dose,
                str(DOSE_WEIGHT.get(dose, "?")),
                str(group.observations),
                str(group.probe_hits),
                f"{group.rate:.1%}",
                f"{lo:.1%} – {hi:.1%}",
                str(len(group.countries)),
            ]
        )
    lines += _table(["组", "权重", "观测数", "命中", "P(我们的牌)", "95% Wilson", "国家数"], rows)

    ctrl = result.groups.get("CTRL")
    high = result.groups.get("HIGH")
    verdict = "无法判定（缺组或缺样本）"
    if ctrl and high and ctrl.observations and high.observations:
        if high.wilson()[0] > ctrl.wilson()[1]:
            verdict = "✅ **G1 通过**：HIGH 组下界高于 CTRL 组上界（区间不重叠）"
        elif high.rate > ctrl.rate:
            verdict = "⚠️ 方向对但区间重叠 —— 样本不足，需跑更久"
        else:
            verdict = "❌ **G1 不成立**：高权重没有把落点推过来"
    mono = "、".join(f"{d}:{result.groups[d].rate:.0%}" for d in DOSE_ORDER if d in result.groups)
    lines += ["", f"**判定**：{verdict}", f"**剂量单调性**：{mono}", ""]

    lines += ["### 2. 三个槽位的剂量反应（同一剂量阶梯放进三个槽）", ""]
    rows = []
    for slot in SLOTS:
        cells = result.by_slot[slot]
        row = [SLOT_SHORT[slot]]
        for dose in DOSE_ORDER:
            cell = cells[dose]
            row.append(f"{cell.rate:.0%} ({cell.hits}/{cell.observations})")
        # 等效竞争权重：优先用最高有数据的那一档反推（份额越贴近 1，反推越稳）。
        # 自然变体里通常只有 CTRL 有数据 —— 那时它也是唯一能用的估计。
        implied = next(
            (
                (dose, value)
                for dose in reversed(DOSE_ORDER)
                if (value := cells[dose].implied_rival_weight()) is not None
            ),
            None,
        )
        row.append("—" if implied is None else f"≈{implied[1]:.0f}（{implied[0]}）")
        row.append(_verdict(cells))
        rows.append(row)
    lines += _table(["槽", *DOSE_ORDER, "等效竞争权重", "HIGH vs CTRL"], rows)
    lines += [
        "",
        (
            "> 等效竞争权重 = 用某档份额反推「同槽其它牌加起来等效多少权重」"
            "（`S = W(1-p)/p`），括号里是用了哪一档 —— 要给多大的权重才能稳拿这个槽，看这一列。"
            "只有 CTRL 有数据时（自然变体、分组没生效）它照样是有效估计，只是误差更大。"
        ),
        "",
    ]

    lines += ["### 3. 重抽节奏（自然变体下就是引擎的真实节奏）", ""]
    rows = []
    for slot in SLOTS:
        tempo = result.tempo[slot]
        top = "、".join(f"{name} {count}" for name, count in tempo.top) or "—"
        rows.append(
            [
                SLOT_SHORT[slot],
                str(tempo.observations),
                str(tempo.pairs),
                str(tempo.changes),
                f"{tempo.rate:.2%}",
                top,
            ]
        )
    lines += _table(["槽", "观测", "相邻对", "换牌", "换牌率/国家·月", "最常见落点 top3"], rows)
    lines += [
        "",
        (
            "> 换牌率是**相邻两次月度观测之间**换牌的比例 ≈ 每月每国换牌概率。"
            "它决定了「喂输入去改变原版概率」这条路线在战役尺度上有没有用。"
        ),
        "",
    ]

    h3_try = [e for e in result.h3_events if e.startswith("TRY;")]
    h3_done = [e for e in result.h3_events if e.startswith("DONE;")]
    extras = [
        "### 4. 附带读数",
        "",
        f"* 第四槽（B7）：{'⚠️ 出现 ' + str(result.fourth_hits) + ' 次 —— 需要复查' if result.fourth_hits else '未出现（与预期一致：槽位固定三个）'}",
        f"* 无 loc 牌（B10）：被抽中 {result.noloc_hits} 次（权重 1；>0 即证明引擎接受无 loc/icon 的牌）",
    ]
    if result.h3_events:
        # H3 已于 2026-09-20 结案（add_ai_strategy 不是脚本效果），探针里不再发这些行；
        # 只有读旧日志时才会走到这里。
        extras.append(
            f"* `add_ai_strategy`（H3）：TRY {len(h3_try)} 条 / DONE {len(h3_done)} 条"
            + ("（TRY 之后没有 DONE = 该语法被引擎拒）" if len(h3_done) < len(h3_try) else "")
        )
    extras.append("")
    lines += extras
    return "\n".join(lines)


__all__ = [
    "DOSE_ORDER",
    "DOSE_WEIGHT",
    "FOURTH_CARD",
    "NOLOC_CARD",
    "PROBE_CARD",
    "PROBE_CARDS",
    "SHORT_SLOT",
    "SLOTS",
    "SLOT_SHORT",
    "Cell",
    "Group",
    "Parsed",
    "Result",
    "Sample",
    "Tempo",
    "analyze",
    "analyze_text",
    "format_report",
    "log_files",
    "parse_lines",
    "wilson_interval",
]
