"""重新生成知识库的全量键名索引（docs/victoria3-modding/13-common全量键名索引.md）。

取代早期用 PowerShell 正则生成的那一版。本版由 :mod:`pdx` 包驱动，
因此自动获得 BOM 剥离、引号感知注释、花括号深度判定、连字符键名支持。

用法：
    .venv\\Scripts\\python.exe tools/run_index.py
    .venv\\Scripts\\python.exe tools/run_index.py --dry-run   # 只打印统计
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdx import config  # noqa: E402
from pdx.extract import extract_dir  # noqa: E402

OUT_DOC = config.DOCS / "13-common全量键名索引.md"


def human(n: int) -> str:
    return f"{n:,}"


def build() -> tuple[str, dict[str, object]]:
    common = config.GAME / "common"
    dirs = sorted(p for p in common.iterdir() if p.is_dir())

    rows: list[str] = []
    total_entries = 0
    total_files = 0
    stats: dict[str, object] = {}

    for d in dirs:
        res = extract_dir(d)
        keys = sorted(res.entries)
        total_entries += len(keys)
        total_files += res.files

        md = ", ".join(sorted(p.name for p in d.glob("*.md")))
        sample = ", ".join(keys[:6]) if keys else "—"
        rows.append(
            f"| `{d.name}` | {res.files} | {len(keys)} | {md or '—'} | {sample} |"
        )

    stats["目录数"] = len(dirs)
    stats["文件总数"] = total_files
    stats["条目总数"] = total_entries

    head = f"""# 13 · common 全量键名索引

> 对 `game\\common\\` 下**全部 {len(dirs)} 个子目录**做机械提取，共 **{human(total_entries)} 个顶层条目**。
> 本文回答「**什么东西定义在哪个目录**」。

## 提取口径

本索引由 `tools/pdx` 包生成（`tools/run_index.py`），口径如下：

```text
顶层判定   花括号深度 == 0，**与缩进无关**
编码       utf-8-sig，自动剥离 BOM
注释       引号感知地剥离 # 到行尾（在花括号计数之前）
键名字符集  非空白、非花括号、非等号、非引号（因此支持连字符）
@变量      不计入条目
```

## 勘误记录

### 勘误 1：早期版本漏计含连字符的键

早期版本用**枚举字符类**匹配键名，静默漏掉了含连字符 `-` 的键。
全库共 **32 个**，分布在 4 个目录：

| 目录 | 含连字符键数 | 修正前 | 修正后 |
|---|---:|---:|---:|
| `character_templates` | 27 | 1,983 | **2,011** |
| `production_methods` | 3 | 433 | **436** |
| `technology` | 1 | 183 | **184** |
| `power_bloc_names` | 1 | 199 | **200** |

### 勘误 2：早期版本漏计文件首键（BOM）与缩进的顶层键

`common` 下 3,024 个 `.txt` 中 **3,000 个带 UTF-8 BOM**，且部分文件的顶层键**带前导空格**。
用「行首无缩进」判定顶层的做法会漏掉它们。实测 `static_modifiers` 因此少算 7 个：

| 目录 | 修正前 | 修正后 |
|---|---:|---:|
| `static_modifiers` | 6,121 | **6,128** |

### 勘误 3：`.txt` 文件数曾用非递归统计

5 个含子目录的目录受影响：`history` 0→1152、`coat_of_arms` 0→23、
`technology` 0→4、`defines` 6→9、`terrain_manipulators` 1→2。

> **三条勘误的共同教训**：解析 PDX 数据不要假设字符集、不要假设文件平铺、
> 不要用缩进判断结构。全部改用花括号深度 + `utf-8-sig` + 取反字符组。

## 全部 {len(dirs)} 个目录

| 目录 | .txt 文件 | 顶层条目 | 官方文档 | 条目示例（前 6 个） |
|---|---:|---:|---|---|
"""
    return head + "\n".join(rows) + "\n", stats


def main() -> int:
    ap = argparse.ArgumentParser(description="重新生成全量键名索引")
    ap.add_argument("--dry-run", action="store_true", help="只打印统计，不写文件")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    text, stats = build()
    print("统计：")
    for k, v in stats.items():
        print(f"  {k}: {human(v) if isinstance(v, int) else v}")

    if args.dry_run:
        print("\n（--dry-run，未写文件）")
        return 0

    OUT_DOC.write_text(text, encoding="utf-8")
    print(f"\n已写入 {OUT_DOC}")
    print(f"  行数 {len(text.splitlines()):,}  字节 {OUT_DOC.stat().st_size:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
