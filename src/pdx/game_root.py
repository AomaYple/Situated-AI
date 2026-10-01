"""``game\\`` 根级文件与 ``paths.settings`` 路径映射。

为什么单独一个模块
------------------
这两样东西此前散在 :mod:`pdx.analyze` 的私有函数里（``_checksum_and_paths``
只为**快照**解析它们），而 doc 19 里对应的两张表是**手抄**的 ——
结果就是它们漂过一次：根级文件「12 个」实为 13 个、
``paths.settings`` 映射「32 条」实为 39 条。

现在把「读它们」这件事抽成一处，快照与文档表格共用同一个解析结果，
于是**两者不可能再给出不同的数字**。

``checksum_manifest.txt`` 还有一层：它**不是花括号语法**（裸标记行 +
``name = xxx`` 键值行），PDX 解析器对它只会得到一堆裸标量 —— 所以那 5 个目录
与 1 个文件只能按行分组建模，见 :func:`checksum_targets_grouped`。

只读、无副作用；不依赖游戏可用（目录不在时返回空表）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import config
from .doc_tables import KeyedTableSpec, TableMalformedError, TableSpec

if TYPE_CHECKING:
    from pathlib import Path

#: ``paths.settings`` 里的一行：``逻辑名 = "实际路径"``
_PATH_LINE_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"([^"]*)"')

#: ``checksum_manifest.txt`` 里的 ``name = xxx``
_NAME_LINE_RE = re.compile(r"^\s*name\s*=\s*(\S+)")

#: ``checksum_manifest.txt`` 的**段落标记**：独占一行的裸 ``directory`` / ``file``。
#: 这不是花括号语法 —— 标记行后面跟一组 ``name = …`` 键值行，直到下一个标记。
_MARKER_LINE_RE = re.compile(r"^\s*(directory|file)\s*$")


@dataclass(slots=True, frozen=True)
class RootFile:
    """``game\\`` 根下的一个文件。"""

    name: str
    size: int
    is_text: bool

    @property
    def suffix(self) -> str:
        return "." + self.name.rsplit(".", 1)[-1].lower() if "." in self.name else ""


def root_files() -> list[RootFile]:
    """``game\\`` 根下的全部文件，按名称排序。

    **不递归** —— 这里要的就是根级那十几个文件，doc 19 与快照报告的
    都是这个口径。目录不参与（它们的文件数在 doc 08 里另算）。
    """
    base = config.GAME
    if not base.is_dir():
        return []
    out: list[RootFile] = []
    for child in sorted(p for p in base.iterdir() if p.is_file()):
        try:
            size = child.stat().st_size
        except OSError:
            continue
        out.append(RootFile(name=child.name, size=size, is_text=_looks_text(child)))
    return out


def _looks_text(path: Path) -> bool:
    """粗略判断是不是文本：按扩展名。判错的后果只是表格里少一个标记。"""
    return path.suffix.lower() in {
        ".txt",
        ".settings",
        ".py",
        ".json",
        ".md",
        ".anchor",
        ".csv",
        ".yml",
        ".yaml",
    }


def paths_settings() -> list[tuple[str, str]]:
    """``paths.settings`` 的 ``(逻辑名, 实际路径)`` 映射，按文件内出现顺序。

    **保序**是有意的：那 39 条映射按语义分 4 组（地图与图形 / 内容源与编辑器 /
    界面与音频 / 其他），文档里的分组表就是按这个顺序排的。
    """
    return _parse_path_lines(config.GAME / "paths.settings")


def _parse_path_lines(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        return []
    out: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = _PATH_LINE_RE.match(line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def checksum_targets_grouped() -> tuple[list[str], list[str]]:
    """``checksum_manifest.txt`` 的校验对象，**按标记分组**：``(目录, 文件)``。

    实测 ``(["common", "events", "map_data", "gui", "localization"],
    ["paths_checksummed.settings"])`` —— 5 个目录 + 1 个文件，
    与 :data:`pdx.config.CHECKSUMMED` 的 5 个目录同集（那一份是**写死**的常量）。

    ⚠️ **这个文件不是花括号语法**，所以 :func:`pdx.cache.parse_cached` 帮不上忙：
    它是「裸标记行 + 键值行」的平铺格式，实测 ``parse_cached`` 得到
    **11 条赋值 + 6 个裸标量**（5 个 ``directory`` / 1 个 ``file``，
    没有键、只有值），而 :func:`pdx.usage.file_definition_counts` 那类
    「顶层块」口径会得到 **0** —— **0 不报错**，只是让 doc 19 §2 的表格
    静默空掉。所以这里**按行解析**，复用同一文件的 :data:`_NAME_LINE_RE`。

    标记行决定归属：``name`` 行只有跟在某个标记后面才知道自己是目录还是文件。
    """
    path = config.GAME / "checksum_manifest.txt"
    directories: list[str] = []
    files: list[str] = []
    if not path.is_file():
        return directories, files
    bucket: list[str] | None = None
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        marker = _MARKER_LINE_RE.match(line)
        if marker:
            bucket = directories if marker.group(1) == "directory" else files
            continue
        m = _NAME_LINE_RE.match(line)
        if m and bucket is not None:
            bucket.append(m.group(1))
    return directories, files


def checksum_targets() -> list[str]:
    """``checksum_manifest.txt`` 列出的校验对象（目录在前、文件在后）。

    实现**只有一份**：本函数就是 :func:`checksum_targets_grouped` 的两个列表拼起来。
    早先这里是一段独立的「见到 ``name =`` 就收」的行扫描 —— 同一份文件两种读法，
    正是本模块开头说的那类漂移的来源（「读它们这件事抽成一处」）。
    拼出来的顺序与文件内顺序一致（文件里 5 个目录在前、1 个文件在后），
    所以 doc 19 §2 那张表的行序没变。
    """
    directories, files = checksum_targets_grouped()
    return [*directories, *files]


# ── doc 19 的生成表 ────────────────────────────────────────
def doc_table_specs() -> list[TableSpec | KeyedTableSpec]:
    """doc 19 里那些**机械**表格的登记表。

    做哪些、不做哪些：

    * **根目录文件表**用 :class:`KeyedTableSpec` —— 第三列 ``作用`` 是作者写的
      说明，整表重生成会把它抹掉，所以只按键更新「字节」列。
      它**曾经漂过**：标题写「12 个文件」而表格自身列了 13 行。
    * **``paths.settings`` 的三张分组表**用 :class:`TableSpec` 整表重生成 ——
      只有「逻辑名 / 实际路径」两列、没有散文，而且文档此前把两条映射合并成
      一行（``flatmap_textures`` / ``colormap_textures``），那种写法**查不出**
      「两条真的同路径吗」。一行一条才可验证。三张表表头相同，靠
      ``occurrence`` 区分。
    * 其余表格不做：要么是纯散文（``用途`` 列占满），要么口径不是这个模块能算的。
    """
    specs: list[TableSpec | KeyedTableSpec] = [
        KeyedTableSpec(
            name="doc19 根目录文件",
            header="| 文件 | 字节 | 作用 |",
            cells=lambda: [(f.name, {1: f"{f.size:,}"}) for f in root_files()],
        ),
        # §2 的「校验对象」是单列表 —— 目录带「含全部子目录」，文件不带。
        # 这一列完全由 checksum_manifest.txt 决定，是最该机械生成的那种表。
        TableSpec(
            name="doc19 校验对象",
            header="| 校验对象 |",
            rows=lambda: [
                f"| `{name}/`（含全部子目录） |"
                if (config.GAME / name).is_dir()
                else f"| `{name}` |"
                for name in checksum_targets()
            ],
        ),
    ]
    mapping = dict(paths_settings())
    for idx, (label, names) in enumerate(
        (
            ("地图与图形", _GFX_GROUP),
            ("内容源与编辑器", _CONTENT_SOURCE_GROUP),
            ("界面与音频", _UI_AUDIO_GROUP),
        )
    ):
        specs.append(
            TableSpec(
                name=f"doc19 paths.settings·{label}",
                header="| 逻辑名 | 实际路径 |",
                rows=_path_rows(names, mapping),
                occurrence=idx,
            )
        )
    return specs


def _path_rows(names: tuple[str, ...], mapping: dict[str, str]):
    """生成 ``paths.settings`` 分组的代码块行。

    用闭包工厂而不是 ``lambda names=names`` —— 默认参数式的捕获在 mypy 下
    推不出类型（实测 ``Cannot infer type of lambda``），而且读起来像技巧。
    """

    def rows() -> list[str]:
        missing = [n for n in names if n not in mapping]
        if missing:
            # 两种情况：游戏升级后改名/删除了映射，或者**游戏根本不在这台机器上**
            # （CI 上就是如此）。抛 TableMalformedError 而不是裸 LookupError ——
            # CLI 会把它转成「前置条件缺失 + 退出码 2」的干净提示，
            # 而裸异常会漏成未捕获错误、退出码 1，与「检查未通过」撞车。
            raise TableMalformedError(
                f"paths.settings 里没有这些逻辑名：{missing[:6]}"
                f"{' …' if len(missing) > 6 else ''}（游戏目录不可用？）"
            )
        return [f"| `{n}` | `{mapping[n]}` |" for n in names]

    return rows


#: ``paths.settings`` 的分组。
#:
#: **分组是文档作者的知识** —— 文件本身只是一串 ``KEY = "path"``，
#: 没有任何分组信息。所以这三组写死在这里；生成器只保证每一行的
#: 「实际路径」列不过期。
_GFX_GROUP: tuple[str, ...] = (
    "terrain",
    "air_graphics",
    "borders",
    "front_graphics",
    "gradient_border_settings",
    "map_modes",
    "map_objects",
    "map_masks",
    "post_effects",
    "gfx_environment_file",
    "flatmap_textures",
    "colormap_textures",
    "mappainting_textures",
    "city_data",
    "city_vfx",
    "route_graphics",
    "military_route_graphics",
    "building_config",
    "game_road_data",
    "line_assets_path",
    "spline_network_file",
    "spline_types",
    "spline_styles",
    "terrain_effects_settings_file",
)

_CONTENT_SOURCE_GROUP: tuple[str, ...] = (
    "map_object_masks",
    "map_object_generators",
    "map_editor_status_file",
    "nudger_settings",
    "map_masks_painter_tool",
)

_UI_AUDIO_GROUP: tuple[str, ...] = (
    "achievement_icons",
    "loadingscreens",
    "startscreen_file",
    "media_aliases",
    "sound_banks",
    "sound_ambience",
    "audio_settings_file",
    "music_player_categories",
    "gfx_skins_path",
    "gfx_skins_base_path",
)
