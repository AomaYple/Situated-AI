"""「用了多少次」类统计表 —— 跨多份文档，所以集中在这里。

为什么单独一个模块
------------------
全仓盘点（``tools/tests/test_inventory.py``）数出 **125 张表含真统计量列而无人看守**，
其中一大类是同一个形状：

    | 字段 | 实测次数 | 说明 |      ← 某目录内各字段出现了多少次
    | 键   | 文件数   | 说明 |      ← 某目录内有多少个文件用到某个键

这些表散在 doc 04 / 14 / 15 / 16 / 17 里，而这几份文档**还没有自己的领域模块**
（不像 doc 05 有 ``defines.py``、doc 08 有 ``install_tree.py``）。为一张表各建一个
模块是过度设计，所以把「同一个形状的分析 + 它的表规格」集中在这里；
等某份文档的表多到值得拆分时再拆。

口径（两个都容易被悄悄改掉，所以写死在这里）
------------------------------------------
* **次数** = 该键作为字段**出现**的总次数（跨文件累加，同一个文件里出现两次算两次）；
* **文件数** = 用到该键的**文件个数**（同一个文件里出现两次只算一个）。
  两者不可互换 —— 实测同一张表里两种口径差得很远。
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from . import config
from .cache import parse_cached
from .doc_tables import KeyedTableSpec
from .extract import entry_fields
from .model import Block, ParsedFile

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from .model import Assignment


def _iter_keyed_blocks(node: Block | ParsedFile) -> Iterator[tuple[str, Block]]:
    """递归产出 ``(键, 块)``。

    块自己**不带键** —— 键只存在于指向它的赋值上，所以必须从赋值往下走。
    另外 ``ParsedFile`` 与 ``Block`` 的入口不同（前者是 ``top_assignments``
    属性、后者是 ``assignments()`` 方法），实测第一版就在这里写错了。
    """
    items = node.top_assignments if isinstance(node, ParsedFile) else node.assignments()
    for a in items:
        v = a.value
        if isinstance(v, Block):
            yield a.key, v
            yield from _iter_keyed_blocks(v)


def _as_entry_block(a: Assignment) -> Block | None:
    """赋值指向块、且不是 ``@变量`` —— 则它是条目块。

    单独一个函数是为了让 mypy 收窄得动：``a.value`` 是**属性**，
    在推导式的条件里写 ``isinstance(a.value, Block)`` 收窄不了表达式
    （实测报 ``Argument 1 has incompatible type``）。
    """
    if a.is_variable or not isinstance(a.value, Block):
        return None
    return a.value


def _entry_blocks(pf: ParsedFile) -> list[Block]:
    """文件里的**顶层条目块**（``@变量`` 不算）。"""
    return [b for b in map(_as_entry_block, pf.top_assignments) if b is not None]


def _collect(dir_rel: str, *, within: str | None, per_file: bool) -> Counter[str]:
    """``dir_rel`` 下要统计的块的字段。

    * ``within=None`` —— 只数**顶层条目块**的字段（如 ``common/buildings/``
      里 115 个建筑各自的字段）。嵌套块不是条目，不参与；
    * ``within="modifier"`` —— 数**任意深度**上名为 ``modifier`` 的块的字段
      （doc 16 的战争目标是 ``war_goal = { modifier = { … } }`` 这种形状）。
    """
    base = config.GAME / dir_rel
    if not base.is_dir():
        return Counter()
    total: Counter[str] = Counter()
    for path in sorted(p for p in base.rglob("*.txt") if p.is_file()):
        pf = parse_cached(path)
        if within is None:
            blocks = _entry_blocks(pf)
        else:
            blocks = [b for key, b in _iter_keyed_blocks(pf) if key == within]
        seen: set[str] = set()
        for b in blocks:
            for key in entry_fields(b):
                if per_file:
                    seen.add(key)
                else:
                    total[key] += 1
        if per_file:
            total.update(seen)
    return total


def field_occurrences(dir_rel: str, *, within: str | None = None) -> Counter[str]:
    """字段名 → **出现次数**（跨文件累加）。"""
    return _collect(dir_rel, within=within, per_file=False)


def field_file_counts(dir_rel: str, *, within: str | None = None) -> Counter[str]:
    """字段名 → **用到它的文件数**（同文件内重复只算一次）。"""
    return _collect(dir_rel, within=within, per_file=True)


def _rows(counter: Counter[str], col: int) -> list[tuple[str, dict[int, str]]]:
    """``(键, {列下标: 文本})``。

    ``col`` 是**次数那一列在表里的下标** —— 必须逐表指定，不能假定它在第 1 列：
    doc 04 那张是 ``| 字段 | 官方 md 行 | 原版使用次数 | md 说明 |``，
    次数在第 **2** 列。写成 1 会把次数写进「官方 md 行」列，而
    :func:`pdx.doc_tables._render` 只替换指定列、**原值留在原处** ——
    于是生成出「``| `x` | 18 | 18 |``」这种双重计数，肉眼看还以为是排版问题。

    排序：计数降序、同值按名称升序（确定性）。只在**追加新行**时用到 ——
    已存在的行由 :func:`pdx.doc_tables._merge_rows` 保持文档原序。
    """
    return [
        (key, {col: f"{n:,}"}) for key, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


#: doc 14 的「字段 / 令牌 实测次数」表 —— §2~§15 每个目录各一张。
#:
#: ``(表头, occurrence, 次数列, 目录)``。occurrence 是**精确表头**在文档里的出现次序，
#: 必须数准：:func:`pdx.doc_tables._find_header` 按次序取表，数错就会把 A 目录的次数
#: 写进 B 目录的表 —— 而那种错**不报错**，只是写错地方。
#: 这 20 条映射逐条核对过：每条算出来的行号都落在该目录自己的章节里（实测 0 处不符）。
_DOC14_FIELD_TABLES: tuple[tuple[str, int, int, str], ...] = (
    ("| 字段 | 实测次数 | 说明 |", 0, 1, "buildings"),
    ("| 字段 | 实测次数 | 说明 |", 1, 1, "production_methods"),
    ("| 字段 | 实测次数 | 说明 |", 2, 1, "goods"),
    ("| 字段 | 实测次数 | 说明 |", 3, 1, "company_types"),
    ("| 字段 | 实测次数 | 说明 |", 4, 1, "pop_needs"),
    ("| 字段 | 实测次数 | 说明 |", 5, 1, "decrees"),
    ("| 字段 | 实测次数 | 说明 |", 6, 1, "harvest_condition_types"),
    ("| 字段 | 实测次数 | 首现位置 | 语义（据用法推断） |", 0, 1, "buildings"),
    ("| 字段 | 实测次数 | 首现位置 | 语义（据用法推断） |", 1, 1, "building_groups"),
    ("| 字段 | 实测次数 | 首现位置 | 语义 |", 0, 1, "production_methods"),
    ("| 字段 | 实测次数 | 首现位置 | 语义 |", 1, 1, "company_types"),
    ("| 字段 | 实测次数 | 含义（逐字来自文件头注释） |", 0, 1, "building_groups"),
    ("| 字段 | 实测次数 | `.md` | 说明 |", 0, 1, "production_method_groups"),
    ("| 字段 | 实测次数 | `prestige_goods.md` | 说明 |", 0, 1, "prestige_goods"),
    ("| 字段 | 实测次数 | 来源 | 说明 |", 0, 1, "pop_needs"),
    ("| 字段 | `.md` | 实测次数 | 说明 |", 0, 2, "company_charter_types"),
    ("| 字段 | 深度 | 实测次数 | 说明 |", 0, 2, "buy_packages"),
    ("| 字段 | 深度 | 实测次数 | 说明 |", 1, 2, "dynamic_company_names"),
    # travel_network（§15）的两张「令牌 | 形式 | 实测次数」表**不在这里**：
    # ``common/travel_network/naval_network.txt`` 里只有 ``nodes`` / ``connections``
    # 两个**令牌列表**，没有 ``key = value`` 形式的字段 —— 拿字段计数去生成
    # 会得到 0 行（``test_生成结果非空`` 当场就会失败，实测就是这么发现的）。
    # 它们的口径是「令牌 × 出现形式」，需要另写一套分析，仍留在欠债余额里。
    ("| 档位 | 实测次数 | 缩放基准 |", 0, 1, "production_methods"),
)


def _field_rows_factory(dir_rel: str, col: int) -> Callable[[], list[tuple[str, dict[int, str]]]]:
    """把「哪个目录、第几列」烘进一个无参函数。

    不用 ``lambda dd=d, cc=col: …`` 那种默认参数式捕获 —— 实测 mypy 推不出
    它的类型（``Cannot infer type of lambda``）。:mod:`pdx.game_root` 里的
    ``_path_rows`` 早就因为同一个原因改成了闭包工厂，这里是同一个坑。
    """

    def rows() -> list[tuple[str, dict[int, str]]]:
        return _rows(field_occurrences(dir_rel), col)

    return rows


def _doc14_specs() -> list[KeyedTableSpec]:
    """doc 14 各目录的字段表 —— 同一形状，逐表指定目录与列号。"""
    out: list[KeyedTableSpec] = []
    for n, (header, occ, col, d) in enumerate(_DOC14_FIELD_TABLES, start=1):
        out.append(
            KeyedTableSpec(
                # 名字必须**唯一**：`patch_doc` 的返回值以表名为键，重名会互相覆盖 ——
                # 那样「19 张表都跑了吗」就看不出来了。实测撞过两次：
                # 先是 production_methods 有三张表，再是「（目录, occurrence, 列号）」
                # 相同而**表头不同**的两张（`首现位置|语义` 与 `档位|缩放基准`）。
                # 所以直接用序号编名字。
                name=f"doc14 表{n} {d}",
                header=header,
                cells=_field_rows_factory(f"common/{d}", col),
                occurrence=occ,
                # 节选表：只列官方 `.md` 声明过的字段
                append_new=False,
            )
        )
    return out


def doc_table_specs() -> list[KeyedTableSpec]:
    """这一族表的登记表。

    每张都注明**数据目录**、**口径**（次数 / 文件数）与**次数所在列** ——
    文档里那几列常常紧挨着出现、只差一个字，指错列不会报错、只会写错地方。
    """
    return [
        # doc 04 §journal_entries：172 个 JE 文件里各字段出现了多少次。
        # 表是 | 字段 | 官方 md 行 | 原版使用次数 | md 说明 | → 次数在**第 2 列**。
        KeyedTableSpec(
            name="doc04 journal_entries 字段使用次数",
            header="| 字段 | 官方 md 行 | 原版使用次数 | md 说明（逐字引用/摘要） |",
            cells=lambda: _rows(field_occurrences("common/journal_entries"), 2),
            # 节选表：只列 `journal_entries.md` **声明过**的字段。
            # 生成器给的是该目录下**全部**字段 —— 不关掉就会追加一堆
            # 官方文档没提过的行，而它们的说明列只能填「待补」。
            append_new=False,
        ),
        # doc 14 的整族（§2~§15）：见下面的 _doc14_specs()
        *_doc14_specs(),
        # doc 16 §4 地图类 · `state_traits`：每个州特性里的 `modifier` 块用到了
        # 哪些修正键、各多少次。**不是** `war_goal_types` —— 那里根本没有
        # `modifier` 块，写错目录会生成 0 行（`test_生成结果非空` 当场失败，
        # 实测就是这么抓到的：先在 travel_network 上撞了一次，又在这里撞一次）。
        KeyedTableSpec(
            name="doc16 state_traits modifier 修正次数",
            header="| 修正 | 次数 | 作用方向 |",
            cells=lambda: _rows(field_occurrences("common/state_traits", within="modifier"), 1),
            # 节选表：只列「实际用到」的修正
            append_new=False,
        ),
    ]


__all__ = [
    "doc_table_specs",
    "field_file_counts",
    "field_occurrences",
]
