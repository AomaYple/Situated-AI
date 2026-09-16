"""PDX 脚本解析器原型（Python 版）

目的：验证 .venv 环境能否胜任游戏文件的扫描与核实。

设计要点（对应本会话踩过的真实坑）：
  1. 用「花括号深度」判断顶层，不用缩进     —— 官方混用 tab / 空格 / 无缩进
  2. encoding='utf-8-sig' 剥离 BOM          —— 3024 个文件里 3000 个带 BOM
  3. 注释剥离要引号感知                     —— 字符串里可能含 #
  4. 键名字符集用「非空白非等号」            —— 存在含连字符的键
  5. 识别 6 个引擎级功能前缀
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

PREFIXES = (
    "REPLACE_OR_CREATE", "INJECT_OR_CREATE", "TRY_INJECT",
    "TRY_REPLACE", "REPLACE", "INJECT",
)

GAME = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Victoria 3\game\common")


@dataclass
class ParseResult:
    keys: list[str] = field(default_factory=list)          # 顶层块键
    prefixed: list[tuple[str, str]] = field(default_factory=list)  # (前缀, 键)
    max_depth: int = 0


def scan_line(raw: str) -> tuple[str, int]:
    """剥离行内注释（引号感知），并返回花括号净增量。"""
    in_quote = False
    out: list[str] = []
    delta = 0
    for ch in raw:
        if ch == '"':
            in_quote = not in_quote
            out.append(ch)
            continue
        if ch == "#" and not in_quote:
            break                       # 注释开始，丢弃本行余下部分
        if not in_quote:
            if ch == "{":
                delta += 1
            elif ch == "}":
                delta -= 1
        out.append(ch)
    return "".join(out).strip(), delta


def parse_file(path: Path) -> ParseResult:
    res = ParseResult()
    # utf-8-sig：自动吃掉 BOM，这是 Python 为此专门提供的编码名
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    depth = 0
    for raw in text.splitlines():
        line, delta = scan_line(raw)

        if depth == 0 and line:
            body, prefix = line, None
            for p in PREFIXES:
                if body.startswith(p + ":"):
                    prefix, body = p, body[len(p) + 1:]
                    break
            # 键名：非空白非等号（允许连字符、点号）
            if "=" in body:
                key = body.split("=", 1)[0].strip()
                if key and not key.startswith("#"):
                    if prefix:
                        res.prefixed.append((prefix, key))
                    else:
                        res.keys.append(key)

        depth += delta
        res.max_depth = max(res.max_depth, depth)

    if depth != 0:
        res.max_depth = -1              # 花括号不平衡，标记异常
    return res


def collect_keys(directory: Path) -> set[str]:
    keys: set[str] = set()
    for f in directory.rglob("*.txt"):
        keys.update(parse_file(f).keys)
    return keys


def main() -> int:
    # 本机控制台是 GBK 代码页，直接 print 非 GBK 字符（如 emoji）会抛
    # UnicodeEncodeError。显式切到 UTF-8 输出，errors='replace' 兜底。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    expect = {
        "static_modifiers": 6128,
        "modifier_type_definitions": 2364,
        "production_methods": 436,
        "character_templates": 2011,
        "buildings": 115,
        "laws": 138,
    }

    print(f"{'目录':<28}{'文件':>6}{'唯一键':>8}{'期望':>8}  结果")
    print("-" * 62)

    all_ok = True
    for name, want in expect.items():
        d = GAME / name
        got = collect_keys(d)
        n_files = sum(1 for _ in d.rglob("*.txt"))
        ok = len(got) == want
        all_ok &= ok
        print(f"{name:<28}{n_files:>6}{len(got):>8}{want:>8}  {'✅' if ok else '❌'}")

    print("-" * 62)
    print(f"全部一致: {'是' if all_ok else '否'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
