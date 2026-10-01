"""图片头普查：`game/gfx/**/*.dds` 的格式、尺寸与 mipmap —— 把一次性脚本变成命令。

为什么有这个模块
----------------
doc 06 §6.3 有三行结论（「mipmap 不是必须」「宽高不必是 2 的幂」「压缩格式多套并存」），
支撑它们的数字来自**一次没留下脚本的全量扫描**（11,293 个可解析头）。
那句话写在文档里，就是「下一个人无法复算」的同义词 —— 与本仓库反复踩过的
「17,821 / 16,535 一次性采集值」是同一类问题。

所以这里把口径写成代码，四个问题一次答清楚：

* **扫的是什么**：``game/gfx`` 下全部 ``.dds``（递归）；
* **读多少**：每个文件前 **128 字节**（DX10 的扩展头到 148 字节，见下）；
* **判据**：全部来自头内字段 —— ``dwFlags``（offset 8）、``dwHeight``/``dwWidth``
  （12/16）、``dwMipMapCount``（28）、``dwFourCC``（84）、``dwRGBBitCount``（88）、
  ``dwPfFlags``（80），DX10 时再看扩展头的 ``dxgiFormat``（128）；
* **怎么复算**：``v3 assets``（或本模块的 :func:`census`）。

⚠️ 与 :mod:`pdx.exe_strings` 同一条规矩：这里给的是**本机这一份安装的普查结果**，
随 DLC 与美术更新而变。文档引用时应写明「本机快照 + 复算命令」，不要当成版本属性。
"""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import config
from .doc_tables import TableSpec
from .scan import walk_files

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

#: DDS 主头长度（含 magic 与 DDS_PIXELFORMAT）。
HEADER_SIZE = 128

#: DX10 扩展头之后的长度（16 字节：dxgiFormat + resourceDimension + misc + arraySize + miscFlags2）。
DX10_SIZE = 148

#: ``DDSD_MIPMAPCOUNT`` 标志位。
FLAG_MIPMAPCOUNT = 0x20000

#: 像素格式 ``DDPF_FOURCC``。
DDPF_FOURCC = 0x4

#: 常用 fourCC → 可读名。
FOURCC_NAMES = {"DXT1": "DXT1", "DXT3": "DXT3", "DXT5": "DXT5", "DX10": "DX10", "BC5U": "BC5U"}

#: DXGI 格式里出现在原版的那几个（doc 06 §6.3 列过 98/99/95/78）。
DXGI_KNOWN = {98: "BC7_UNORM_SRGB", 99: "BC7_UNORM", 95: "BC6H_UF16", 78: "BC5_UNORM"}


@dataclass(frozen=True, slots=True)
class Header:
    """一个 DDS 文件的关键头字段。"""

    rel: str
    width: int
    height: int
    mipmaps: int
    flags: int
    four_cc: str
    rgb_bits: int
    pf_flags: int
    dxgi_format: int | None = None

    @property
    def has_mipmap_flag(self) -> bool:
        return bool(self.flags & FLAG_MIPMAPCOUNT)

    @property
    def pow2(self) -> bool:
        return _is_pow2(self.width) and _is_pow2(self.height)

    @property
    def fmt(self) -> str:
        """归一化后的格式名（统计用）。"""
        if self.dxgi_format is not None:
            name = DXGI_KNOWN.get(self.dxgi_format, "")
            return f"DX10:{self.dxgi_format}" + (f"（{name}）" if name else "")
        if self.four_cc in FOURCC_NAMES:
            return FOURCC_NAMES[self.four_cc]
        if self.pf_flags & DDPF_FOURCC:
            return f"其它 fourCC({self.four_cc})"
        return f"未压缩 {self.rgb_bits}bit"


@dataclass(slots=True)
class Census:
    """一份安装的 DDS 头普查结果。"""

    root: str = ""
    found: int = 0
    parsed: int = 0
    too_short: int = 0
    formats: Counter = field(default_factory=Counter)
    mipmaps: Counter = field(default_factory=Counter)
    dxgi: Counter = field(default_factory=Counter)
    pow2: int = 0
    non_pow2: int = 0
    non_pow2_with_mipmap: int = 0
    with_multi_mipmap: int = 0
    missing_mipmap_flag: int = 0
    examples: list[str] = field(default_factory=list)

    @property
    def resolution_ratio(self) -> float:
        """非 2 的幂占比（doc 06 写作「约 35%」）。"""
        return self.non_pow2 / self.parsed if self.parsed else 0.0

    def summary(self) -> dict[str, object]:
        return {
            "根目录": self.root,
            "找到": self.found,
            "可解析": self.parsed,
            "头过短": self.too_short,
            "格式": dict(self.formats.most_common()),
            "mipmap 级数": dict(sorted(self.mipmaps.items())),
            "非2幂": self.non_pow2,
            "非2幂且带mipmap": self.non_pow2_with_mipmap,
            "多级mipmap": self.with_multi_mipmap,
            "缺mipmap标志": self.missing_mipmap_flag,
        }


def _is_pow2(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def parse_header(data: bytes, rel: str = "") -> Header | None:
    """解析前 128 字节；不是 DDS 或头太短时返回 ``None``。"""
    if len(data) < HEADER_SIZE or data[:4] != b"DDS ":
        return None
    _size, flags, height, width, _pitch, _depth, mipmaps = struct.unpack_from("<7I", data, 4)
    pf_flags, four_cc, rgb_bits = struct.unpack_from("<I4sI", data, 80)
    dxgi: int | None = None
    if four_cc == b"DX10" and len(data) >= DX10_SIZE:
        (dxgi,) = struct.unpack_from("<I", data, HEADER_SIZE)
    return Header(
        rel=rel,
        width=width,
        height=height,
        mipmaps=mipmaps,
        flags=flags,
        four_cc=four_cc.decode("ascii", "replace").rstrip("\x00"),
        rgb_bits=rgb_bits,
        pf_flags=pf_flags,
        dxgi_format=dxgi,
    )


def iter_dds(root: Path) -> Iterator[Path]:
    """``root`` 下全部 ``.dds``。

    复用 :func:`pdx.scan.walk_files`（``os.scandir`` 实现）而不是 ``rglob``：
    实测 ``rglob("*") + is_symlink() + is_file()`` 在 ``gfx`` 上要 80 秒，
    换成仓库自己的遍历器后是秒级 —— 同一个游戏树，两套遍历口径的差距不该存在。
    """
    for entry in walk_files(root, suffix=".dds"):
        yield entry.path


def census(root: Path | None = None, *, example_limit: int = 3) -> Census:
    """对 ``game/gfx`` 做一次全量 DDS 头普查。

    游戏目录不存在时返回一份空结果（CI 上没有游戏，这条路径不该炸）。
    """
    base = (root or (config.GAME / "gfx")).resolve()
    out = Census(root=str(base))
    if not base.is_dir():
        return out

    for path in iter_dds(base):
        out.found += 1
        try:
            with path.open("rb") as fh:
                head = fh.read(DX10_SIZE)
        except OSError:  # pragma: no cover - 权限/占用等极端情况
            out.too_short += 1
            continue
        header = parse_header(head, path.relative_to(base).as_posix())
        if header is None:
            out.too_short += 1
            continue
        out.parsed += 1
        out.formats[header.fmt] += 1
        out.mipmaps[header.mipmaps] += 1
        if header.dxgi_format is not None:
            out.dxgi[header.dxgi_format] += 1
        if header.mipmaps > 1:
            out.with_multi_mipmap += 1
        if not header.has_mipmap_flag:
            out.missing_mipmap_flag += 1
        if header.pow2:
            out.pow2 += 1
        else:
            out.non_pow2 += 1
            if header.mipmaps > 1:
                out.non_pow2_with_mipmap += 1
            if len(out.examples) < example_limit:
                out.examples.append(
                    f"{header.rel} {header.width}x{header.height} mip={header.mipmaps}"
                )
    return out


def format_rows(c: Census) -> list[str]:
    """doc 06 §6.3 那张表要的机器行：``| 指标 | 数值 |``。"""
    return [
        f"| `.dds` 文件（`game/gfx/**`） | {c.found:,} |",
        f"| ├ 可解析头 | {c.parsed:,} |",
        f"| └ 头过短/非法 | {c.too_short:,} |",
        f"| mipmap 级数 = 1 | {c.mipmaps.get(1, 0):,} |",
        f"| mipmap 级数 = 0 | {c.mipmaps.get(0, 0):,} |",
        f"| 多级 mipmap（>1） | {c.with_multi_mipmap:,} |",
        f"| 缺 `DDSD_MIPMAPCOUNT` 标志 | {c.missing_mipmap_flag:,} |",
        f"| 宽高均为 2 的幂 | {c.pow2:,} |",
        f"| 宽高非 2 的幂 | {c.non_pow2:,}（{c.resolution_ratio:.0%}） |",
        f"| ├ 其中带多级 mipmap | {c.non_pow2_with_mipmap:,} |",
        *[f"| 格式 {name} | {n:,} |" for name, n in c.formats.most_common()],
    ]


#: 生成表在文档里的表头（作者写在文档里，生成器只填数据行）。
DOC_TABLE_HEADER = "| DDS 普查项 | 数值 |"


def doc_table_specs() -> list[TableSpec]:
    """doc 06 §6.3 的 DDS 普查表 —— 让那三个结论的数字由 `v3 tables` 看守。

    以前它们是「一次性扫描」的产物：文档里写着「尚未脚本化」，读者无法复算。
    现在数字来自 :func:`census`，`v3 tables` 每次核对；**只填数据行**，
    表头与前后散文仍然归作者（与 `pdx.doc_tables` 的约定一致）。
    """
    return [TableSpec("doc06 DDS 头普查", DOC_TABLE_HEADER, lambda: format_rows(census()))]


__all__ = [
    "DDPF_FOURCC",
    "DOC_TABLE_HEADER",
    "DX10_SIZE",
    "DXGI_KNOWN",
    "FLAG_MIPMAPCOUNT",
    "FOURCC_NAMES",
    "HEADER_SIZE",
    "Census",
    "Header",
    "census",
    "doc_table_specs",
    "format_rows",
    "iter_dds",
    "parse_header",
]
