"""阶段 3 A/B 实验的分析器（H2：**真实冲击能不能改行为**）。

探针（`v3 ab-probe` 生成）每月给**主角国家**写几行，用 `;` 分隔：

```text
ZZPROBE AB;RUN;A                            ← 臂标记：A=对照、B=冲击、B2=追加改革侧输入
ZZPROBE AB;PLAYER;yes;塔希提                 ← 玩家是谁（开错国家时用来自检）
ZZPROBE AB;ROLE;RUS;俄罗斯                   ← 主角国家标记
ZZPROBE AB;SHOCK;yes;俄罗斯                  ← 冲击变量在不在（B 段起应为 yes）
ZZPROBE AB;INPUT;yes;俄罗斯                  ← 改革侧输入修正在不在（B2 段起应为 yes）
ZZPROBE AB;LEG;b75;俄罗斯                    ← 诊断：合法性落在哪一档（五档夹逼）
ZZPROBE AB;JE;active;俄罗斯                  ← 行为层①：改革窗口
ZZPROBE AB;LAW;law_serfdom;俄罗斯            ← 行为层②：当月生效的那条改革相关法律
ZZPROBE AB;POLI;reactionary_agenda;俄罗斯    ← 策略层：三个槽位落点（ADMI / DIPL 同理）
```

**臂阶梯**（探针侧由月份驱动，见 `pdx.ab_probe.LADDER`）：一局之内
`A`（第 1–12 月，什么都不做）→ `B`（第 13 月起施加冲击）→ `B2`（第 37 月起追加改革侧输入）。
所以 `RUN` 行在一局里会出现三次 —— 一次启动就能拿到整条阶梯的读数，
而 A/B 的差分不再掺进"两局之间世界已经漂了"的噪声。

本模块做五件事：

1. **解析 → 按 `RUN` 分段、段内按月配对**。`RUN` 行把多次启动（或同一局里的多次换臂）
   切开（日志按 512KB 轮转，同一个目录里可能躺着好几局）；同一个角色（A / B / B2）的多段
   **合并**统计 —— 阶段 3 判据要的是「同一臂的所有观测」，不是「哪一次启动」。
2. **行为层差分**：改革窗口的开启月份占比与首次开启时间、每条法律的出现月份数与
   **首次转换月份**（A 全程 `law_serfdom`、B 第 30 个月转成别的 = 差分）。
3. **策略层差分**：三个槽位的落点分布与最常见的那个落点（与 `pdx.h1` 同一口径）。
4. **两处对照分开报**：主对照是 **A vs B**（冲击步，H2 判定只看它）；第二对照是
   **B vs B2**（改革侧输入步，`input_*` 字段），因为执行文档要求"两层分开报"之外，
   冲击步与输入步问的也是两个问题（前者：战败本身推不推得动；后者：把改革派读到的
   输入喂进去之后，原版自己的牌会不会换）。
5. **判定**：按执行文档的失败长相分档 —— 两层都动 = G2 初步成立；**只有策略层动 =
   H2 不成立（意图层是薄壳）**；都不动 = 无差分；缺一个角色 = 无法判定。

几条口径上的"为什么"（都是踩过或算过的）：

* **块边界不靠时间戳，靠"同类型的行又出现了"**：月度脉冲偶尔跨秒，8 行会被切成两个
  时间戳；纯按时间戳配对会把那一整月丢掉（还会多出一条"未配对"）。
* **同一段内 `(时间戳, 类型, 国名)` 完全相同的行只算一次**：`v3 h1-probe --watch` 会把
  同一个文件在不同时刻反复快照进归档目录，不去重就会把同一个月数成好几次。
* **不完整的块一律不进统计**（缺 `SHOCK`/`JE`/`LAW`/任一槽位）：半块只可能来自轮转把
  开头或结尾切断，拿它算占比是系统性偏移，不如明确计入"未配对"。
  ⚠️ `INPUT` 与 `LEG` **不在必填之列**：它们是后加的诊断行，老归档（改探针之前跑的）
  没有它们 —— 把它们算进必填，等于让"已跑完的局"全部作废（那些局正是阶段 3 结论的来源）。
* **判定只需要 A 与 B**（:data:`VERDICT_ROLES`）：B2 是追加处理段，不进 H2 判定 ——
  否则"还没跑到第 37 个月"的局会连 A/B 的差分都判不出来。
* **差分阈值 5 个百分点**：3–5 年的局里 1–2 个月的抖动就有 2–5 个百分点，比这更小的差
  先不算 —— G2 本来就要求"两次同向"才定论，第一遍只看方向。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pdx import ab_probe, config
from pdx.h1 import SLOT_SHORT, SLOTS

if TYPE_CHECKING:
    from pathlib import Path

#: 角色（= 实验臂）：A = 对照（什么都不做）、B = 冲击、B2 = 追加改革侧输入。
#: 与探针的 `RUN` 行取值**同源**（P9：只有一处定义 —— `ab_probe.LADDER`）。
ROLES = ab_probe.ROLES

#: 判定（H2）用到的角色：**只到冲击步**（A vs B）。
#: B2 是追加处理段，单独报（`Result.input_*`）—— 把它算进判定，会让"还没跑到第 37 个月"
#: 的局连 A/B 的差分都判不出来。
VERDICT_ROLES = ("A", "B")

#: 角色判不出来时的占位：既没有 `RUN` 行，`ROLE` 行也没带角色字母。
ROLE_UNKNOWN = "?"

#: 角色 → 报告里的中文标签。
ROLE_LABELS = {
    "A": "A 对照组",
    "B": "B 冲击段",
    "B2": "B2 改革侧输入段",
    ROLE_UNKNOWN: "角色未知",
}

#: 行为层的法律清单：探针每月只记**命中的那一条**，6 条都没命中时写 `none`。
LAWS = (*ab_probe.LAWS, "none")

#: 主体行的类型：这几类行只对主角国家写 —— 用它们的国名当"观测到的国家"。
_SUBJECT_KINDS = ("SHOCK", "INPUT", "JE", "LAW", "STRATEGY")

#: 一个完整月度块必须有的行。缺任何一类 = 那一块被轮转切断了。
#:
#: ⚠️ `STRATEGY`（2026-09-22 新增）**不进**这一组：它是后加的行，老归档（阶段 3 的
#: 四局）里一条都没有 —— 把它列成必需会让那些归档整批变成"残缺块"。口径：
#: **新增的读数只能是可选行**，否则历史数据会被新判据反向作废。
REQUIRED_KINDS = ("SHOCK", "JE", "LAW", *SLOT_SHORT.values())

#: **可选**的诊断行：后加的，老归档没有。缺了不算块残缺（口径见模块文档）。
OPTIONAL_KINDS = ("INPUT", "LEG", "STRATEGY")

#: 合法性诊断的档位（探针夹逼出来的，从低到高）。**只用于排序与报告** ——
#: 探针写什么值，这里就报什么值；写了个不认识的档位也不会被吞掉。
LEG_BANDS = ("b55", "b60", "b70", "b75", "b80")

#: `SHOCK` / `JE` / `INPUT` 行里表示"在"的取值。
SHOCK_YES = "yes"
JE_ACTIVE = "active"
INPUT_YES = "yes"

#: 差分阈值：任一落点 / 法律的占比差超过它才算差分（见模块文档的口径说明）。
SHARE_EPS = 0.05

_LINE = re.compile(
    r"^\[(?P<stamp>\d{2}:\d{2}:\d{2})\].*?ZZPROBE AB;(?P<kind>[A-Z]+);(?P<rest>.+?)\s*$"
)


def _pct(value: float) -> str:
    """占比一律按"整数百分点"报 —— 小样本下多一位小数是假精度。"""
    return f"{value:.0%}"


def _role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def _month_text(month: int | None) -> str:
    """首次开启 / 首次转换的月份（编号 = 该角色合并后的第 N 个月度观测）。"""
    return f"第 {month} 月" if month else "未发生"


@dataclass(frozen=True, slots=True)
class Block:
    """一个（段, 国名）下的**一个月的自报块**。

    `values` 是这一块里出现过的行（类型 → 取值）；`complete` 为假时整块不进统计。
    """

    run: int
    role: str
    tag: str
    stamp: str
    values: dict[str, str]

    @property
    def missing(self) -> tuple[str, ...]:
        """这一块缺了哪些必填行（诊断用）。"""
        return tuple(kind for kind in REQUIRED_KINDS if kind not in self.values)

    @property
    def complete(self) -> bool:
        return not self.missing


@dataclass(frozen=True, slots=True)
class Sample:
    """一次**可用**的月度观测（只有完整的块才会变成 Sample）。

    ``input`` / ``leg`` / ``strategy`` 可能为 ``None``：它们是后加的诊断行，
    老归档里没有（见模块文档的口径说明）。
    """

    run: int
    order: int
    month: int
    role: str
    stamp: str
    tag: str
    shock: str
    je: str
    law: str
    cards: dict[str, str]
    input: str | None = None
    leg: str | None = None
    strategy: str | None = None

    @property
    def shock_yes(self) -> bool:
        return self.shock == SHOCK_YES

    @property
    def input_yes(self) -> bool:
        return self.input == INPUT_YES

    @property
    def je_active(self) -> bool:
        return self.je == JE_ACTIVE


@dataclass(frozen=True, slots=True)
class Parsed:
    """解析结果：段、月度块、玩家与主角国家名、未配对计数。"""

    runs: tuple[str, ...]
    roles: tuple[str, ...]
    blocks: tuple[Block, ...]
    player: str | None
    subject: str | None

    @property
    def unpaired(self) -> int:
        """不完整的块数（缺行 → 不进统计，但要在报告里出现）。"""
        return sum(1 for block in self.blocks if not block.complete)


@dataclass(frozen=True, slots=True)
class Segment:
    """一次启动（老探针没有 `RUN` 行时就是"整个目录"这一段）。"""

    index: int
    declared: str
    role: str
    blocks: int
    months: int


@dataclass(frozen=True, slots=True)
class LawStat:
    """一条法律在一个角色里的出现情况。"""

    law: str
    months: int
    share: float
    first_month: int | None


@dataclass(frozen=True, slots=True)
class BandStat:
    """一个角色在合法性某一档上待了多少个月（五档夹逼的诊断口径）。"""

    band: str
    months: int
    share: float


#: 政治牌 id → 报告里的短名（与三槽那套 `SLOT_SHORT` 同一口味：报告用短名，日志用全名）。
STRATEGY_SHORT = {
    "ai_strategy_progressive_agenda": "progressive_agenda",
    "ai_strategy_conservative_agenda": "conservative_agenda",
    "ai_strategy_reactionary_agenda": "reactionary_agenda",
}
#: 探针没写 `STRATEGY` 行（老归档）时的占位；`none` = 三张政治牌都没挂。
STRATEGY_NONE = "none"


def strategy_short(name: str) -> str:
    """把日志里的策略 id 折成短名（认不出来的原样返回 —— 不吞信息）。"""
    return STRATEGY_SHORT.get(name, name)


@dataclass(frozen=True, slots=True)
class StrategyStat:
    """一张政治牌在一个角色里的出现情况。

    为什么要有这个类型：阶段 3 的负结果（牌换了名、法一条没改）里，"牌换成了哪一张"
    是从三槽落点**推断**的。B53（backlog）之后牌是**行为层的直接读数**
    （`change_law_chance` 就写在牌上），所以它必须能被直接统计与差分。
    """

    name: str
    months: int
    share: float
    first_month: int | None


@dataclass(frozen=True, slots=True)
class Behaviour:
    """一个角色的**行为层**读数（月份编号 = 合并后的第 N 个月度观测）。"""

    role: str
    segments: int
    observations: int
    tags: tuple[str, ...]
    shock_yes: int
    je_active: int
    je_first: int | None
    laws: tuple[LawStat, ...]
    first_law: str | None
    law_change: int | None
    law_change_to: str | None
    input_yes: int = 0
    bands: tuple[BandStat, ...] = ()
    strategies: tuple[StrategyStat, ...] = ()

    @property
    def months(self) -> int:
        return self.observations

    @property
    def shock_rate(self) -> float:
        return self.shock_yes / self.observations if self.observations else 0.0

    @property
    def input_rate(self) -> float:
        return self.input_yes / self.observations if self.observations else 0.0

    @property
    def je_share(self) -> float:
        return self.je_active / self.observations if self.observations else 0.0

    def law_stat(self, law: str) -> LawStat | None:
        """某条法律的出现情况（没出现过 = None，不是 0 月的 LawStat）。"""
        return next((stat for stat in self.laws if stat.law == law), None)

    def law_share(self, law: str) -> float:
        stat = self.law_stat(law)
        return stat.share if stat else 0.0

    def strategy_stat(self, short: str) -> StrategyStat | None:
        """某张政治牌的出现情况（没出现过 = None）。"""
        return next((stat for stat in self.strategies if stat.name == short), None)

    def strategy_share(self, short: str) -> float:
        stat = self.strategy_stat(short)
        return stat.share if stat else 0.0

    def band_share(self, band: str) -> float:
        """某一档的占比（没观测到 = 0.0）。"""
        return next((stat.share for stat in self.bands if stat.band == band), 0.0)

    @property
    def leg_top(self) -> BandStat | None:
        """待得最久的那一档（诊断一句话用）。

        ``max`` 而不是 ``bands[0]``：``bands`` 是按**档位顺序**排的（那条尺度从低到高），
        不是按月数排的 —— 拿第一个当"最久"会把 b55 的一两个月说成主要水位。
        并列时取档位较低的那个（``max`` 保序），结果仍然确定。
        """
        return max(self.bands, key=lambda stat: stat.months) if self.bands else None


@dataclass(frozen=True, slots=True)
class SlotDist:
    """一个角色在一个槽位上的落点分布（`counts` 已按「最常见」口径排好）。"""

    slot: str
    role: str
    observations: int
    counts: tuple[tuple[str, int], ...]

    @property
    def most_common(self) -> tuple[str, int] | None:
        return self.counts[0] if self.counts else None

    @property
    def top3(self) -> tuple[tuple[str, int], ...]:
        return self.counts[:3]

    def share(self, label: str) -> float:
        if not self.observations:
            return 0.0
        for name, count in self.counts:
            if name == label:
                return count / self.observations
        return 0.0


@dataclass(frozen=True, slots=True)
class Diff:
    """一条差分：两个角色在同一个指标上的读数 + 有没有差分。"""

    layer: str
    name: str
    a: str
    b: str
    changed: bool
    note: str = ""


#: 判定的三种（外加"缺一组"）—— `Result.verdict` 的取值就是这些。
VERDICTS = ("g2_preliminary", "h2_shell", "no_diff", "insufficient")

#: 判定 → 一句话（markdown）。口径来自执行文档的「失败长相」表。
_VERDICT_HEAD = {
    "g2_preliminary": "✅ **G2 初步成立**",
    "h2_shell": "❌ **H2 不成立：意图层是薄壳**",
    "no_diff": "**无差分**",
    "insufficient": "**无法判定**",
}


@dataclass(frozen=True, slots=True)
class Result:
    """整次实验的结果。

    ``behaviour_diffs`` / ``strategy_diffs`` 是**冲击步**（A vs B）的差分；
    ``input_behaviour_diffs`` / ``input_strategy_diffs`` 是**改革侧输入步**（B vs B2）的 ——
    执行文档要求两层分开报，而这里更进一步：**两处处理也分开报**。
    """

    runs: tuple[str, ...]
    segments: tuple[Segment, ...]
    roles: dict[str, Behaviour]
    slots: dict[str, dict[str, SlotDist]]
    behaviour_diffs: tuple[Diff, ...]
    strategy_diffs: tuple[Diff, ...]
    samples: tuple[Sample, ...]
    unpaired: int
    player: str | None
    subject: str | None
    input_behaviour_diffs: tuple[Diff, ...] = ()
    input_strategy_diffs: tuple[Diff, ...] = ()

    @property
    def months(self) -> int:
        """观测月数（一月一块，只盯主角国家 → 观测数就是月数）。"""
        return len(self.samples)

    @property
    def tags(self) -> tuple[str, ...]:
        return tuple(sorted({sample.tag for sample in self.samples}))

    @property
    def behaviour_changed(self) -> bool:
        return any(diff.changed for diff in self.behaviour_diffs)

    @property
    def strategy_changed(self) -> bool:
        return any(diff.changed for diff in self.strategy_diffs)

    @property
    def input_changed(self) -> bool:
        """改革侧输入步有没有动（行为层或策略层任一动）。"""
        diffs = (*self.input_behaviour_diffs, *self.input_strategy_diffs)
        return any(diff.changed for diff in diffs)

    @property
    def verdict(self) -> str:
        """按执行文档的失败长相判定（详见 :func:`verdict_text` 的说明）。

        ⚠️ **样本不足不许宣判**：实测踩过 —— B 组刚点完决议才 1 个月，
        这里就直接给出「H2 不成立：意图层是薄壳」。那是**假结论**：冲击的合法性 -20
        要等下一个月度脉冲才落到读数上，改革窗口与法律转换更是数月尺度的事。
        所以两组的观测窗口都够长之前，一律 `insufficient`。

        ⚠️ 只看 :data:`VERDICT_ROLES`（A 与 B）：B2 是追加处理段，
        它的读数由 :func:`format_report` 的第 ③ 节单独报，不参与 H2 判定。
        """
        if any(role not in self.roles for role in VERDICT_ROLES):
            return "insufficient"
        if min(self.months_of(role) for role in VERDICT_ROLES) < VERDICT_MIN_MONTHS:
            return "insufficient"
        if self.behaviour_changed:
            return "g2_preliminary"
        if self.strategy_changed:
            return "h2_shell"
        return "no_diff"

    def months_of(self, role: str) -> int:
        """某个角色合并后的月度块数（判定用）。"""
        behaviour = self.roles.get(role)
        return behaviour.months if behaviour is not None else 0


def parse(text: str) -> Parsed:
    """把日志文本解析成「段 + 月度块」。

    分段的依据是 `RUN` 行；老版本的探针没有这一行（实测：`ab-A-partial` 归档里只有
    `ZZPROBE AB;ROLE;A;俄罗斯`），此时角色回退到 `ROLE` 行上的角色字母 ——
    没有它就只能把整段标成"角色未知"，一行统计也不做。
    """
    runs: list[str] = []
    letters: list[set[str]] = []
    values: list[dict[str, str]] = []
    heads: list[tuple[int, str, str]] = []
    open_at: dict[tuple[int, str], int] = {}
    seen: set[tuple[int, str, str, str]] = set()
    player: str | None = None
    subjects: Counter[str] = Counter()
    current = -1
    for line in text.splitlines():
        match = _LINE.search(line)
        if not match:
            continue
        kind = match.group("kind")
        parts = match.group("rest").split(";")
        if kind == "RUN":
            runs.append(parts[0])
            letters.append(set())
            # 新的一段：上一段的块不再接收行（块不会跨段）
            open_at = {}
            current = len(runs) - 1
            continue
        if len(parts) < 2:
            continue
        value, tag, stamp = parts[0], parts[-1], match.group("stamp")
        if current < 0:
            # 没有 RUN 行（老探针 / 归档只剩观测行）→ 当作第一段，口径同 `pdx.h1`
            runs.append("")
            letters.append(set())
            current = 0
        if kind == "ROLE" and value in ROLES:
            letters[current].add(value)
        if kind == "PLAYER" and value == "yes":
            player = tag
        if kind in _SUBJECT_KINDS:
            subjects[tag] += 1
        if (current, stamp, kind, tag) in seen:
            # 轮转副本 / `--watch` 快照里的同一行：只算一次
            continue
        seen.add((current, stamp, kind, tag))
        key = (current, tag)
        index = open_at.get(key)
        if index is None or kind in values[index]:
            values.append({})
            heads.append((current, tag, stamp))
            index = len(values) - 1
            open_at[key] = index
        values[index][kind] = value

    roles: list[str] = []
    for index, declared in enumerate(runs):
        found = letters[index]
        if declared in ROLES:
            roles.append(declared)
        elif len(found) == 1:
            roles.append(next(iter(found)))
        else:
            roles.append(ROLE_UNKNOWN)
    blocks = tuple(
        Block(run=run, role=roles[run], tag=tag, stamp=stamp, values=values[index])
        for index, (run, tag, stamp) in enumerate(heads)
    )
    subject = subjects.most_common(1)[0][0] if subjects else None
    return Parsed(
        runs=tuple(runs),
        roles=tuple(roles),
        blocks=blocks,
        player=player,
        subject=subject,
    )


def _segments(parsed: Parsed, samples: list[Sample]) -> tuple[Segment, ...]:
    """每段的规模（块数与**可用**月数分开算：缺行多的段一眼看得出来）。"""
    blocks: Counter[int] = Counter(block.run for block in parsed.blocks)
    months: Counter[int] = Counter(sample.run for sample in samples)
    return tuple(
        Segment(
            index=index,
            declared=declared,
            role=parsed.roles[index],
            blocks=blocks[index],
            months=months[index],
        )
        for index, declared in enumerate(parsed.runs)
    )


def _bands(samples: list[Sample]) -> tuple[BandStat, ...]:
    """合法性档位分布（只统计**有这一行**的月份；老归档没有 LEG 行 → 空元组）。

    排序：先按 :data:`LEG_BANDS` 的档位顺序（原版那条尺度从低到高），
    不认识的档位按名字排在后面 —— 探针将来加档也不会把读数吞掉。
    """
    counts: Counter[str] = Counter(sample.leg for sample in samples if sample.leg)
    total = sum(counts.values())
    order = {band: index for index, band in enumerate(LEG_BANDS)}
    return tuple(
        BandStat(band=band, months=count, share=count / total if total else 0.0)
        for band, count in sorted(counts.items(), key=lambda kv: (order.get(kv[0], 99), kv[0]))
    )


def _strategies(samples: list[Sample]) -> tuple[StrategyStat, ...]:
    """政治牌分布（只统计**有 `STRATEGY` 行**的月份；老归档没有 → 空元组）。"""
    counts: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    total = 0
    for sample in samples:
        if not sample.strategy:
            continue
        total += 1
        counts[sample.strategy] += 1
        first_seen.setdefault(sample.strategy, total)
    return tuple(
        StrategyStat(
            name=name,
            months=count,
            share=count / total if total else 0.0,
            first_month=first_seen[name],
        )
        for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    )


def _behaviour(role: str, samples: list[Sample]) -> Behaviour:
    """一个角色的行为层读数（月份编号在同角色的多段之间**连续**）。"""
    ordered = sorted(samples, key=lambda sample: (sample.run, sample.month))
    months: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    first_law: str | None = None
    je_first: int | None = None
    law_change: int | None = None
    law_change_to: str | None = None
    for index, sample in enumerate(ordered, start=1):
        months[sample.law] += 1
        first_seen.setdefault(sample.law, index)
        if first_law is None:
            first_law = sample.law
        if je_first is None and sample.je_active:
            je_first = index
        if law_change is None and first_law is not None and sample.law != first_law:
            law_change, law_change_to = index, sample.law
    total = len(ordered)
    laws = tuple(
        LawStat(
            law=law,
            months=count,
            share=count / total if total else 0.0,
            first_month=first_seen[law],
        )
        for law, count in sorted(months.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return Behaviour(
        role=role,
        segments=len({sample.run for sample in ordered}),
        observations=total,
        tags=tuple(sorted({sample.tag for sample in ordered})),
        shock_yes=sum(1 for sample in ordered if sample.shock_yes),
        je_active=sum(1 for sample in ordered if sample.je_active),
        je_first=je_first,
        laws=laws,
        first_law=first_law,
        law_change=law_change,
        law_change_to=law_change_to,
        input_yes=sum(1 for sample in ordered if sample.input_yes),
        bands=_bands(ordered),
        strategies=_strategies(ordered),
    )


def _slots(role: str, samples: list[Sample]) -> dict[str, SlotDist]:
    """一个角色的三个槽位落点分布（排序口径与 `pdx.h1` 的最常见落点一致）。"""
    out: dict[str, SlotDist] = {}
    for slot in SLOTS:
        counts: Counter[str] = Counter(
            sample.cards[slot] for sample in samples if slot in sample.cards
        )
        out[slot] = SlotDist(
            slot=slot,
            role=role,
            observations=len(samples),
            counts=tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        )
    return out


def _je_text(behaviour: Behaviour) -> str:
    return f"{_pct(behaviour.je_share)}（首次开启：{_month_text(behaviour.je_first)}）"


def _law_change_text(behaviour: Behaviour) -> str:
    if behaviour.law_change is None:
        return f"无转换（全程 {behaviour.first_law or '—'}）"
    return f"第 {behaviour.law_change} 月 → {behaviour.law_change_to}"


def _behaviour_diffs(a: Behaviour, b: Behaviour) -> tuple[Diff, ...]:
    """行为层差分：改革窗口 + 首次转换 + 每条法律的出现占比。

    为什么把「首次转换」单列一行：占比差会被长局稀释（30 个月末转换只差 3%），
    而"有没有转过、第几个月转"是判据原文里的主指标。
    """
    layer = "行为层"
    diffs = [
        Diff(
            layer=layer,
            name="改革窗口 JE",
            a=_je_text(a),
            b=_je_text(b),
            changed=(a.je_first is None) != (b.je_first is None)
            or abs(a.je_share - b.je_share) > SHARE_EPS,
        ),
        Diff(
            layer=layer,
            name="法律首次转换",
            a=_law_change_text(a),
            b=_law_change_text(b),
            changed=(a.law_change is None) != (b.law_change is None)
            or (a.law_change is not None and a.law_change != b.law_change)
            or a.first_law != b.first_law,
        ),
    ]
    for law in LAWS:
        stat_a, stat_b = a.law_stat(law), b.law_stat(law)
        months_a, months_b = (stat_a.months if stat_a else 0), (stat_b.months if stat_b else 0)
        diffs.append(
            Diff(
                layer=layer,
                name=f"法律 {law}",
                a=f"{months_a} 月（{_pct(a.law_share(law))}）",
                b=f"{months_b} 月（{_pct(b.law_share(law))}）",
                changed=abs(a.law_share(law) - b.law_share(law)) > SHARE_EPS,
            )
        )
    return tuple(diffs)


def _strategy_diffs(a: dict[str, SlotDist], b: dict[str, SlotDist]) -> tuple[Diff, ...]:
    """策略层差分：三个槽位的最常见落点 + 落点分布位移。"""
    diffs: list[Diff] = []
    for slot in SLOTS:
        dist_a, dist_b = a[slot], b[slot]
        top_a, top_b = dist_a.most_common, dist_b.most_common
        name_a = top_a[0] if top_a else "—"
        name_b = top_b[0] if top_b else "—"
        labels = {name for name, _ in dist_a.counts} | {name for name, _ in dist_b.counts}
        shifted = any(abs(dist_a.share(name) - dist_b.share(name)) > SHARE_EPS for name in labels)
        changed = name_a != name_b or shifted
        note = ""
        if changed and name_a == name_b:
            note = "最常见落点没变，是分布位移"
        diffs.append(
            Diff(
                layer="策略层",
                name=SLOT_SHORT[slot],
                a=f"{name_a}（{_pct(dist_a.share(name_a))}）",
                b=f"{name_b}（{_pct(dist_b.share(name_b))}）",
                changed=changed,
                note=note,
            )
        )
    return tuple(diffs)


def analyze_text(text: str) -> Result:
    """从日志文本算出全部统计（只有一个角色的数据时也能出报告）。"""
    parsed = parse(text)
    samples: list[Sample] = []
    per_run: defaultdict[int, int] = defaultdict(int)
    for order, block in enumerate(parsed.blocks):
        if not block.complete:
            continue
        per_run[block.run] += 1
        cards = {
            slot: block.values[short] for slot, short in SLOT_SHORT.items() if short in block.values
        }
        samples.append(
            Sample(
                run=block.run,
                order=order,
                month=per_run[block.run],
                role=block.role,
                stamp=block.stamp,
                tag=block.tag,
                shock=block.values["SHOCK"],
                je=block.values["JE"],
                law=block.values["LAW"],
                cards=cards,
                input=block.values.get("INPUT"),
                leg=block.values.get("LEG"),
                strategy=strategy_short(block.values["STRATEGY"])
                if "STRATEGY" in block.values
                else None,
            )
        )
    by_role: defaultdict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        by_role[sample.role].append(sample)
    roles = {role: _behaviour(role, group) for role, group in sorted(by_role.items())}
    slots = {role: _slots(role, group) for role, group in sorted(by_role.items())}
    # 差分只可能来自两组都在的情形；"角色未知"的那些块不进差分
    # （它们只出现在观测规模表里，让"角色判不出来"这件事看得见）。
    step = all(role in roles for role in VERDICT_ROLES)
    inputs = all(role in roles for role in ("B", "B2"))
    behaviour_diffs = _behaviour_diffs(roles["A"], roles["B"]) if step else ()
    strategy_diffs = _strategy_diffs(slots["A"], slots["B"]) if step else ()
    # 第二对照（B → B2）只有真跑到第 37 个月才有——没跑到就明确是空的，不猜。
    input_behaviour_diffs = _behaviour_diffs(roles["B"], roles["B2"]) if inputs else ()
    input_strategy_diffs = _strategy_diffs(slots["B"], slots["B2"]) if inputs else ()
    return Result(
        runs=parsed.runs,
        segments=_segments(parsed, samples),
        roles=roles,
        slots=slots,
        behaviour_diffs=behaviour_diffs,
        strategy_diffs=strategy_diffs,
        samples=tuple(samples),
        unpaired=parsed.unpaired,
        player=parsed.player,
        subject=parsed.subject,
        input_behaviour_diffs=input_behaviour_diffs,
        input_strategy_diffs=input_strategy_diffs,
    )


def log_files(log_dir: Path | None = None) -> list[Path]:
    """日志目录里可能含 AB 行的文件（含轮转副本与 `--watch` 快照）。

    口径与 :func:`pdx.h1.log_files` 相同：只认目录下的 `*.log`，按名字排序。
    排序很重要 —— 解析器按行的出现顺序给月份编号，顺序得是确定的。
    """
    base = log_dir or config.USERDIR / "logs"
    if not base.is_dir():
        return []
    return sorted(path for path in base.glob("*.log") if path.is_file())


def error_files(log_dir: Path | None = None) -> list[Path]:
    """只读 `error*.log`：开局自检扫"我们的报错"时用（见 :func:`health`）。"""
    base = log_dir or config.USERDIR / "logs"
    if not base.is_dir():
        return []
    return sorted(path for path in base.glob("error*.log") if path.is_file())


def _read(paths: list[Path]) -> str:
    """读并拼接，**逐字节相同的文件只算一次**。

    为什么必须按内容去重：`v3 h1-probe --watch` 每一轮都把当时的 `debug.log` 复制成
    `s0001-debug.log`、`s0002-debug.log`…… 同一个文件会被复制很多次，而每次复制都带着
    同一条 `RUN` 行 —— 不去重就会把同一局的同一个月算成好几遍（还会多出好几"段"）。
    两次**不同**的启动不可能产出逐字节相同的日志，所以按内容去重是安全的。
    """
    chunks: list[str] = []
    seen: set[str] = set()
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        if text in seen:
            continue
        seen.add(text)
        chunks.append(text)
    return "\n".join(chunks)


def analyze(log_dir: Path | None = None) -> Result:
    """读整个日志目录并分析（轮转副本与快照并集，重复的行由解析器去重）。"""
    return analyze_text(_read(log_files(log_dir)))


#: 开局自检的门槛：可用月度块少于这个数，说明观测还没流动起来。
#: 一月一块（快速模式下约 10 秒一块），所以 3 块大约开局半分钟就能判。
HEALTH_MIN_MONTHS = 3

#: 下判定所需的最短观测窗口（每角色各自；月）。
#: 12 的理由：冲击的合法性 -20 要等月度脉冲落到读数上，改革窗口开窗与法律转换是数月尺度 ——
#: B 组刚点完决议就宣判「H2 不成立」是假结论（实测踩过）。
VERDICT_MIN_MONTHS = 12

#: `SHOCK` 的期望值：A 组应为 0%、B 段起应为 100%。留一点余量给
#: "点决议那一秒"和日志边界的错位。
HEALTH_SHOCK_A_MAX = 0.05
HEALTH_SHOCK_B_MIN = 0.90

#: `INPUT`（改革侧输入）的期望值：只有 B2 段该有，A/B 段该没有。
#: 与 SHOCK 同一套余量口径 —— 它们是同一类"输入到底有没有落到实处"的自检。
HEALTH_INPUT_MAX = 0.05
HEALTH_INPUT_MIN = 0.90

#: error 日志里出现这些字样 = 我们的命名空间被引擎抱怨（任一即红）。
HEALTH_NAME_MARKERS = ("zz_probe", "sitai_")

#: 引擎的抱怨句式：与 `pdx.h1` 同一份清单 —— 挂载点写错时脚本侧毫无报错，
#: 只有这些字样（同一行里还得提到我们，见 :func:`health`）。
HEALTH_ERROR_MARKERS = (
    "Unknown effect",
    "cannot link",
    "Unknown strategy",
    "Failed to find country",
    "Data error in loc string",
)


@dataclass(frozen=True, slots=True)
class HealthItem:
    """一条自检项。"""

    name: str
    ok: bool
    detail: str


def _runs_text(result: Result) -> str:
    if not result.runs:
        return "（一条 RUN 行都没有）"
    return "、".join(f"`{run or '(无标记)'}`" for run in result.runs)


def _missing_text(result: Result) -> str:
    """判定那一对（A / B）缺哪个角色 —— 两个都在就返回空串。

    只看 :data:`VERDICT_ROLES`：B2 是追加处理段，它缺席时 ①② 两张表照样成立
    （③ 那一节自己会说"B2 臂还没有观测"）。
    """
    absent = [f"{role} 组" for role in VERDICT_ROLES if role not in result.roles]
    return "缺 " + "、".join(absent) if absent else ""


def _shock_text(result: Result) -> str:
    """冲击自检：每个角色的 SHOCK 占比 + 该角色的期望值。"""
    parts: list[str] = []
    for role in ROLES:
        behaviour = result.roles.get(role)
        if behaviour is None:
            continue
        mark = "✅" if _shock_ok(role, behaviour.shock_rate) else "⚠️"
        parts.append(
            f"{mark} {_role_label(role)} {_pct(behaviour.shock_rate)}（期望 {_expect_text(role)}）"
        )
    return "；".join(parts) if parts else "没有可自检的角色（一臂都没有）"


def _expect_text(role: str) -> str:
    """某一臂对「输入在不在」的期望值（按阶梯的起始月说出来，不写死"点完决议后"）。"""
    if role == "A":
        return "≈0%（对照臂）"
    start = ab_probe.ARM_START.get(role)
    return f"第 {start} 月起 ≈100%" if start else "≈100%"


def _shock_ok(role: str, rate: float) -> bool:
    return rate <= HEALTH_SHOCK_A_MAX if role == "A" else rate >= HEALTH_SHOCK_B_MIN


def _input_ok(role: str, rate: float) -> bool:
    """改革侧输入：只有 B2 臂该有它（它挂在第 37 个月）。"""
    return rate >= HEALTH_INPUT_MIN if role == "B2" else rate <= HEALTH_INPUT_MAX


def _input_text(result: Result) -> str:
    """改革侧输入自检：B2 段该 100%，之前的两臂该 0%。

    为什么值得单列一条：B2 段与 B 段的差别**只有**这一处输入 ——
    它没落上的话，第 ③ 节的"无差分"就会被误读成"改革侧输入没用"。
    """
    parts: list[str] = []
    for role in ROLES:
        behaviour = result.roles.get(role)
        if behaviour is None:
            continue
        expect = "第 37 月起 ≈100%" if role == "B2" else "≈0%"
        mark = "✅" if _input_ok(role, behaviour.input_rate) else "⚠️"
        parts.append(f"{mark} {_role_label(role)} {_pct(behaviour.input_rate)}（期望 {expect}）")
    return "；".join(parts) if parts else "没有可自检的角色（一臂都没有）"


def _shock_hint(bad: list[str]) -> str:
    """冲击不符合预期时，给一句"去哪儿查"（这是这个探针最常见的两种装错法）。"""
    if "B2" in bad:
        return "　→ B2 段没有冲击：第 37 月前就收工了，或阶梯的 stage 变量被重置"
    if "B" in bad:
        return "　→ B 段没有冲击：真 mod 没装（`Unknown effect`），或阶梯没被决议武装"
    if "A" in bad:
        return "　→ A 段不该有冲击：阶梯第 13 月之前就已经施加了？检查 stage 守卫"
    return ""


def _input_hint(bad: list[str]) -> str:
    if "B2" in bad:
        return "　→ B2 段没有改革侧输入：`sitai_ru_reform_input` 没被调用（真 mod 没装或改过名）"
    return "　→ A/B 段不该有改革侧输入：阶梯的两处效果是不是被合并成一次施加了？"


def health(
    result: Result,
    *,
    log_dir: Path | None = None,
    text: str | None = None,
    error_text: str | None = None,
) -> tuple[HealthItem, ...]:
    """**开局自检**：这一局的数据到底有没有在正常产生（P13：失败要出声）。

    为什么必须有它：阶段 2 的探针把 on_action 定义放错了文件，分组一次都没跑，
    而**脚本侧毫无报错** —— 整局白跑。这里把同类失败变成"开局一分钟内红"：

    ① `RUN` 行在不在（开局钩子有没有触发、多次启动还切不切得开）；
    ② `PLAYER` 是不是主角国家（开错国家的话，A/B 就成了两个国家在比）；
    ③ 观测在不在流动（月度钩子有没有在跑）；
    ④ 角色判不判得出来（`RUN` 缺失时靠 `ROLE` 行的字母兜底）；
    ⑤ `SHOCK` 符不符合该臂的预期（B/B2 该 100%，A 该 0%）；
    ⑥ `INPUT` 符不符合该臂的预期（只有 B2 该 100%）——
       它没落上的话，第 ③ 节"无差分"会被误读成"改革侧输入没用"；
    ⑦ 日志里有没有"我们的文件出错了"。
    """
    items: list[HealthItem] = []

    # ① RUN 标记：开局钩子到底有没有触发（也是唯一的分段依据）
    declared = [run for run in result.runs if run in ROLES]
    items.append(
        HealthItem(
            name="RUN 标记（开局钩子触发 / 分段依据）",
            ok=bool(declared),
            detail=(
                f"读到 {len(declared)} 条：{'、'.join(declared)}"
                if declared
                else "一条都没有 —— 开局 boot 没跑，或轮转已把开局那几行吃掉；"
                "没有它就切不开多次启动（本题的角色只能靠 ROLE 行的字母兜底）"
            ),
        )
    )

    # ② 玩家是不是主角国家：对不上就是"开错国家"，A/B 会变成两国相比
    subject = result.subject
    items.append(
        HealthItem(
            # ⚠️ 口径在阶段 3 中途**反过来了**：玩家扮演主角国家时，那个国家就不是 AI 了 ——
            # 而 G2 问的正是"AI 在战败后自己走向改革"。所以玩家必须是**旁观者**，
            # 主角国家要保持 AI 控制（冲击由决议远程施加）。这一条因此检查"不是"。
            name="PLAYER 不是主角国家（它要保持 AI）",
            ok=bool(result.player) and bool(subject) and result.player != subject,
            detail=(
                (
                    f"PLAYER;yes;{result.player}；主角国家：{subject} ✅ 旁观者"
                    if result.player != subject
                    else f"❌ 玩家就是主角国家 {subject}：它不是 AI，问不出「AI 自己改革」"
                )
                if result.player
                else "一条 PLAYER 行都没有（月度钩子没跑？）"
            ),
        )
    )

    # ③ 观测在流动（下限 1：刚点完决议还没跨月时不该判红；判定用的 ≥3 月由分析器负责）
    items.append(
        HealthItem(
            name="观测在流动",
            ok=result.months >= 1,
            detail=f"{result.months} 个月度块（分析判定需要 ≥{HEALTH_MIN_MONTHS} 月）"
            + (f"，另有 {result.unpaired} 个残缺块未计入" if result.unpaired else ""),
        )
    )

    # ④ 角色判得出来（RUN 缺失时 ROLE 行的字母是唯一线索）
    unknown = [segment.index for segment in result.segments if segment.role == ROLE_UNKNOWN]
    layout = "、".join(
        f"第 {segment.index + 1} 段 {segment.declared or '（无 RUN）'}→{segment.role}"
        for segment in result.segments
    )
    items.append(
        HealthItem(
            name="角色可判（A/B）",
            ok=not unknown,
            detail=layout + (f"（{len(unknown)} 段判不出角色）" if unknown else ""),
        )
    )

    # ⑤ SHOCK 符不符合该角色的预期
    checked = [(role, result.roles[role]) for role in ROLES if role in result.roles]
    bad = [role for role, behaviour in checked if not _shock_ok(role, behaviour.shock_rate)]
    items.append(
        HealthItem(
            name="SHOCK 符合角色预期",
            ok=bool(checked) and not bad,
            detail=_shock_text(result) + _shock_hint(bad),
        )
    )

    # ⑥ INPUT（改革侧输入）符不符合该臂的预期。只有 B2 段该有它 —— 这一条红的含义
    #    不是"数据没跑"，而是"第 ③ 节的差分读数不能用"（那一段少了它要解释的东西）。
    input_items = [(role, result.roles[role]) for role in ROLES if role in result.roles]
    input_bad = [
        role for role, behaviour in input_items if not _input_ok(role, behaviour.input_rate)
    ]
    items.append(
        HealthItem(
            name="INPUT 符合角色预期",
            ok=bool(input_items) and not input_bad,
            detail=_input_text(result) + _input_hint(input_bad),
        )
    )

    # ⑦ 日志里没有"我们的文件出错了"。分两类扫，理由见各自的注释。
    if text is None:
        text = _read(log_files(log_dir))
    if error_text is None:
        error_text = _read(error_files(log_dir))
    # a) error 日志里出现我们的命名空间或引擎的抱怨句式 —— 最硬的一条：
    #    正常局的 error.log 里不该有我们一个字。
    in_error = [
        line.strip()
        for line in error_text.splitlines()
        if any(marker in line for marker in (*HEALTH_NAME_MARKERS, *HEALTH_ERROR_MARKERS))
    ]
    # b) 全部日志里出现「引擎抱怨句式 + 我们的命名空间」同行 —— 抓
    #    `Unknown effect sitai_ru_defeat_shock` 这种可能落在 debug.log 里的错。
    #    ⚠️ 不能把"命名空间"这一类也套到 debug.log 上：我们每条正常自报行的前缀都是
    #    `common/on_actions/zz_probe_ab_on_actions.txt:NN:`，那样扫等于每条都命中。
    complained = [
        line.strip()
        for line in text.splitlines()
        if any(marker in line for marker in HEALTH_ERROR_MARKERS)
        and any(name in line for name in HEALTH_NAME_MARKERS)
    ]
    bad_lines = [*in_error, *complained]
    items.append(
        HealthItem(
            name="日志里没有我们的报错",
            ok=not bad_lines,
            detail="干净" if not bad_lines else f"{len(bad_lines)} 条，例如：{bad_lines[0][:120]}",
        )
    )
    return tuple(items)


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Markdown 表（rich 会渲染成真表格）。与 `pdx.h1` 同一写法，保持报告观感一致。"""
    return [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
        *["| " + " | ".join(row) + " |" for row in rows],
    ]


def format_health(items: tuple[HealthItem, ...]) -> str:
    """把自检结果排成一张人读的表 + 结论。"""
    rows = [["✅" if item.ok else "❌", item.name, item.detail] for item in items]
    lines = ["### 开局自检", "", *_table(["", "检查项", "实测"], rows), ""]
    failed = [item for item in items if not item.ok]
    lines.append(
        "**结论**：✅ 这一局的数据在正常产生，可以继续跑"
        if not failed
        else "**结论**：❌ "
        + "；".join(item.name for item in failed)
        + " —— 现在就停下，别白跑一局"
    )
    return "\n".join(lines)


def verdict_text(result: Result) -> str:
    """判定 + 一句为什么（markdown，报告与 `--json` 共用同一处口径）。

    为什么"只有策略层动"要单独判死：执行文档的失败长相写死了 ——
    策略卡换个名字、行为层两次都没差分 = 意图层是薄壳，**停下重估目标**，
    不加代码、不扩档案。反过来，只动行为层不动策略层是**更好的**长相：
    说明冲击改的是原版自己的推导，而不是我们那几张牌的名字。
    """
    head = _VERDICT_HEAD[result.verdict]
    if result.verdict == "g2_preliminary":
        pattern = (
            "行为层与策略层都有差分"
            if result.strategy_changed
            else "只有行为层有差分（不是薄壳长相：冲击改的是原版自己的东西）"
        )
        return (
            f"{head}（{pattern}）—— 但 G2 要求**两次同向**："
            "再跑一遍 A/B，同向出现才写进结论，这一次只是初判"
        )
    if result.verdict == "h2_shell":
        return (
            f"{head} —— 只有策略层动、行为层没有差分。按执行文档的失败长相："
            "**停下重估目标**（不加代码、不扩档案）"
        )
    if result.verdict == "no_diff":
        return (
            f"{head}：A/B 在行为层与策略层都没有可测差分 —— 先看上面的冲击自检"
            "（冲击没生效时这里必然无差分），再看观测是否够长"
        )
    return (
        f"{head}：{_missing_text(result) or '缺一个角色'} —— "
        "两边都要有完整观测才谈得上差分（现在只报已有角色的读数）"
    )


def _arm_window(role: str) -> str:
    """某一臂在**游戏内**的月份窗口（阶梯的起始月推出来，不写死）。"""
    start = ab_probe.ARM_START.get(role)
    if start is None:
        return "—"
    later = sorted(step.at_month for step in ab_probe.LADDER if step.at_month > start)
    return f"第 {start}–{later[0] - 1} 月" if later else f"第 {start} 月起"


def _bands_table(result: Result) -> list[str]:
    """合法性档位分布（五档夹逼）—— 世界层诊断，解释"窗口为什么开/不开"。

    为什么值得进报告：阶段 3 的核心诊断链是「合法性压到哪一档 → 窗口开不开 →
    策略牌换不换 → 法律动不动」，缺了第一环就只能看到"没差分"，看不到**为什么**。
    """
    roles = [role for role in (*ROLES, ROLE_UNKNOWN) if result.roles.get(role) is not None]
    if not any(stat.bands for stat in result.roles.values()):
        return ["（没有 `LEG` 诊断行：这是加档位之前的探针跑的局）"]
    rows: list[list[str]] = []
    for role in roles:
        behaviour = result.roles[role]
        top = behaviour.leg_top
        rows.append(
            [
                _role_label(role),
                "、".join(
                    f"{band.band} {band.months}（{_pct(band.share)}）" for band in behaviour.bands
                )
                or "—",
                f"{top.band}（{_pct(top.share)}）" if top else "—",
            ]
        )
    return _table(["角色", "各档月数（占比）", "待得最久的一档"], rows)


def _strategy_table(result: Result) -> list[str]:
    """政治牌分布 —— **行为层**的直接读数（B53：`change_law_chance` 就写在牌上）。

    为什么它比三槽落点更该看：三槽落点是"AI 手里的牌"，而"政治牌"是**同类的那一张**
    （每国同时只有一张政治牌在用）。阶段 3 的负结果正是"政治牌从反动换到保守
    ⇒ 动手概率反而降了"，而当时没有逐月读数、只能从三槽反推。
    """
    roles = [role for role in (*ROLES, ROLE_UNKNOWN) if result.roles.get(role) is not None]
    if not any(stat.strategies for stat in result.roles.values()):
        return ["（没有 `STRATEGY` 行：这是 2026-09-22 之前的探针跑的局）"]
    rows: list[list[str]] = []
    for role in roles:
        behaviour = result.roles[role]
        top = behaviour.strategies[0] if behaviour.strategies else None
        rows.append(
            [
                _role_label(role),
                "、".join(
                    f"{stat.name} {stat.months}（{_pct(stat.share)}）"
                    for stat in behaviour.strategies
                )
                or "—",
                f"{top.name}（{_pct(top.share)}）" if top else "—",
                str(top.first_month) if top and top.first_month else "—",
            ]
        )
    return _table(["角色", "各牌月数（占比）", "最常见的那张", "首次出现月"], rows)


def format_report(result: Result) -> str:
    """把结果排成人读的表：**先行为层差分，再策略层差分**，最后给判定。

    第 ① / ② 节是**冲击步**（A vs B，H2 判定看的就是它）；第 ③ 节是
    **改革侧输入步**（B vs B2）—— 执行文档要求"两层分开报"，
    而一局之内的两处处理也必须分开报，否则"是哪一处起了作用"不可分。
    """
    missing = _missing_text(result)
    lines: list[str] = ["**观测规模**（一个块 = 一月一国）", ""]
    rows: list[list[str]] = []
    for role in (*ROLES, ROLE_UNKNOWN):
        behaviour = result.roles.get(role)
        if behaviour is None:
            continue
        rows.append(
            [
                _role_label(role),
                _arm_window(role),
                str(behaviour.segments),
                str(behaviour.observations),
                "、".join(behaviour.tags) or "—",
                f"{behaviour.shock_yes}（{_pct(behaviour.shock_rate)}）",
                f"{behaviour.input_yes}（{_pct(behaviour.input_rate)}）",
                f"{behaviour.je_active}（{_pct(behaviour.je_share)}）",
            ]
        )
    lines += _table(
        ["角色", "游戏内窗口", "段数", "月数", "国家", "SHOCK=yes", "INPUT=yes", "JE 开启"], rows
    )
    # 这几行写成列表项：Markdown 的软换行会把相邻的普通行拼成一段，读起来全糊在一起
    lines += [
        "",
        f"* **原始分段**：{_runs_text(result)}",
        f"* **玩家**：{result.player or '—'}（观测到的国家：{result.subject or '—'}）",
        f"* **残缺块**：{result.unpaired} 个（缺 SHOCK/JE/LAW 或某个槽位 → 不进统计）",
        f"* **冲击自检**：{_shock_text(result)}",
        f"* **改革侧输入自检**：{_input_text(result)}",
        "* **合法性档位**（世界层诊断；五档夹逼，没有「打印数字」的已证写法）",
        "",
        *_bands_table(result),
        "",
        "* **政治牌**（2026-09-22 起的**直接**读数，`ZZPROBE AB;STRATEGY;`；老归档没有这一行）",
        "",
        *_strategy_table(result),
        "",
    ]

    # ── ① 行为层（先看这里：主指标）──
    lines += ["### ① 行为层差分（改革窗口 + 法律）—— 冲击步 A → B", ""]
    if result.behaviour_diffs:
        rows = [
            [
                diff.name,
                diff.a,
                diff.b,
                "✅ 有差分" if diff.changed else "—",
                diff.note,
            ]
            for diff in result.behaviour_diffs
        ]
        lines += _table(["指标", "A 对照组", "B 冲击段", "差分", "备注"], rows)
    else:
        lines.append(f"⚠️ {missing or '没有可比的 A/B'} —— 差分无从谈起，先补齐两臂。")
    lines += ["", "**每角色读数**（月份编号 = 该角色合并后的第 N 个月度观测）", ""]
    rows = []
    for role in (*ROLES, ROLE_UNKNOWN):
        behaviour = result.roles.get(role)
        if behaviour is None:
            continue
        rows.append(
            [
                _role_label(role),
                behaviour.first_law or "—",
                _law_change_text(behaviour),
                _month_text(behaviour.je_first),
                _pct(behaviour.je_share),
            ]
        )
    lines += _table(["角色", "首个法律", "首次转换", "JE 首次开启", "JE 占比"], rows)
    lines += ["", "**每条法律的出现月数**（探针每月只记命中的那一条）", ""]
    rows = []
    for law in LAWS:
        row = [law]
        for role in ROLES:
            behaviour = result.roles.get(role)
            if behaviour is None:
                row += ["—", "—"]
                continue
            stat = behaviour.law_stat(law)
            row += [str(stat.months if stat else 0), _pct(behaviour.law_share(law))]
        rows.append(row)
    lines += _table(["法律", "A 月数", "A 占比", "B 月数", "B 占比"], rows)
    lines.append("")

    # ── ② 策略层（次指标：执行文档要求与行为层**分开报**）──
    lines += ["### ② 策略层差分（三槽落点）—— 冲击步 A → B", ""]
    if result.strategy_diffs:
        rows = [
            [diff.name, diff.a, diff.b, "✅ 有差分" if diff.changed else "—", diff.note]
            for diff in result.strategy_diffs
        ]
        lines += _table(["槽位", "A 最常见", "B 最常见", "差分", "备注"], rows)
    else:
        lines.append(f"⚠️ {missing or '没有可比的 A/B'} —— 差分无从谈起。")
    lines += ["", "**每角色落点分布**（最常见落点口径与 `v3 h1` 相同）", ""]
    rows = []
    for role in (*ROLES, ROLE_UNKNOWN):
        dists = result.slots.get(role)
        if dists is None:
            continue
        for slot in SLOTS:
            dist = dists[slot]
            top = "、".join(f"{name} {count}" for name, count in dist.top3) or "—"
            rows.append([_role_label(role), SLOT_SHORT[slot], str(dist.observations), top])
    lines += _table(["角色", "槽位", "观测", "落点 top3"], rows)

    # ── ③ 改革侧输入步（第二处处理：B → B2）──
    lines += ["", "### ③ 改革侧输入段差分（B → B2）", ""]
    lines += _input_section(result)
    lines.append("")
    lines += _input_summary(result)

    # ── 判定 ──
    lines += [
        "",
        "### 判定",
        "",
        verdict_text(result),
        "",
        (
            "> 行为层 = 改革窗口 JE + 法律（看得见的东西）；策略层 = 三槽落点（AI 手里的牌）。"
            "执行文档写死了「**只有策略层动 = H2 不成立**」，所以两层分开统计、分开报；"
            "**只有策略层动不允许被解释成差分**。"
        ),
        (
            "> 两处处理也分开报：① / ② 是**冲击步**（A → B，H2 判定只看它），"
            "③ 是**改革侧输入步**（B → B2）—— 混在一起报就分不出是哪一处起了作用。"
        ),
    ]
    return "\n".join(lines)


def _input_section(result: Result) -> list[str]:
    """第 ③ 节的两张表（行为层与策略层各一张，口径与 ① / ② 完全一致）。"""
    if not result.input_behaviour_diffs and not result.input_strategy_diffs:
        have_b2 = "B2" in result.roles
        reason = (
            "B2 臂还没有观测（跑到第 37 个月才有这一臂）"
            if not have_b2
            else "B 与 B2 两臂缺一个，差分无从谈起"
        )
        return [f"⚠️ 没有可比的 B → B2：{reason}。"]
    sections: list[str] = []
    rows = [
        [diff.name, diff.a, diff.b, "✅ 有差分" if diff.changed else "—", diff.note]
        for diff in result.input_behaviour_diffs
    ]
    sections += _table(["指标", "B 冲击段", "B2 输入段", "差分", "备注"], rows)
    sections += ["", "**策略层（同一个 B → B2 对照）**", ""]
    rows = [
        [diff.name, diff.a, diff.b, "✅ 有差分" if diff.changed else "—", diff.note]
        for diff in result.input_strategy_diffs
    ]
    sections += _table(["槽位", "B 最常见", "B2 最常见", "差分", "备注"], rows)
    return sections


def _input_summary(result: Result) -> list[str]:
    """第 ③ 节的一句话结论（含"样本不足不宣判"的同一条纪律）。"""
    if "B2" not in result.roles:
        return []
    months = result.months_of("B2")
    if months < VERDICT_MIN_MONTHS:
        return [
            (
                f"**结论**：B2 段只有 {months} 个月（< {VERDICT_MIN_MONTHS}）—— "
                "样本不足，这一段还读不出东西（判定用的那条纪律对每一步处理都成立）。"
            )
        ]
    if result.input_changed:
        return [
            (
                "**结论**：改革侧输入让读数**动了** —— 至于是「原版自己换了牌」还是"
                "「只是分布位移」，看上面两张表的差分列；法律那几行才是行为层的硬指标。"
            )
        ]
    return [
        (
            "**结论**：改革侧输入落到了国家身上（见上面的 INPUT 自检），但读数**没有动** —— "
            "这时要分清两种情形：输入没进到原版读的那条路径（字段名/档位不对），"
            "或者它对这条处境本来就不敏感（那是比「缺牌」更值得记下来的事实）。"
        )
    ]


__all__ = [
    "HEALTH_ERROR_MARKERS",
    "HEALTH_INPUT_MAX",
    "HEALTH_INPUT_MIN",
    "HEALTH_MIN_MONTHS",
    "HEALTH_NAME_MARKERS",
    "HEALTH_SHOCK_A_MAX",
    "HEALTH_SHOCK_B_MIN",
    "INPUT_YES",
    "JE_ACTIVE",
    "LAWS",
    "LEG_BANDS",
    "OPTIONAL_KINDS",
    "REQUIRED_KINDS",
    "ROLES",
    "ROLE_LABELS",
    "ROLE_UNKNOWN",
    "SHARE_EPS",
    "SHOCK_YES",
    "VERDICTS",
    "VERDICT_MIN_MONTHS",
    "VERDICT_ROLES",
    "BandStat",
    "Behaviour",
    "Block",
    "Diff",
    "HealthItem",
    "LawStat",
    "Parsed",
    "Result",
    "Sample",
    "Segment",
    "SlotDist",
    "analyze",
    "analyze_text",
    "error_files",
    "format_health",
    "format_report",
    "health",
    "log_files",
    "parse",
    "verdict_text",
]
