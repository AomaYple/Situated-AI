"""发布身份、全部语言正文与 JSON 收据的共同合同。"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from pdx import config, deployment
from pdx.localization_languages import DEFAULT_LANGUAGES

MATERIALS = config.REPO / "docs/publishing"


def publication_config(directory: Path = MATERIALS) -> dict[str, Any]:
    data = tomllib.loads((directory / "workshop.toml").read_text(encoding="utf-8"))
    if set(data) != {"schema", "published_file_id", "descriptions"} or data["schema"] != 1:
        raise ValueError("工坊发布配置结构不受支持")
    item = data["published_file_id"]
    if type(item) is not int or not 0 < item < 2**64:
        raise ValueError("工坊条目 ID 无效")
    rows = data["descriptions"]
    if not isinstance(rows, dict) or set(rows) != {
        language.directory for language in DEFAULT_LANGUAGES
    }:
        raise ValueError("工坊正文语言集合与本体语言不一致")
    seen = set()
    for game_language, row in rows.items():
        if not isinstance(row, dict) or set(row) != {"steam", "file"}:
            raise ValueError("工坊正文映射无效")
        language, filename = row["steam"], row["file"]
        if (
            not isinstance(language, str)
            or not re.fullmatch(r"[a-z]+", language)
            or language in seen
        ):
            raise ValueError("Steam 语言代码无效或重复")
        seen.add(language)
        expected = {"simp_chinese": "schinese", "korean": "koreana", "braz_por": "brazilian"}.get(
            game_language, game_language
        )
        if language != expected:
            raise ValueError(f"Steam 官方语言代码不符：{game_language} → {language}")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not filename.endswith(".md")
            or any(char in filename for char in "\\:")
        ):
            raise ValueError("工坊正文路径必须是当前目录内的 Markdown 文件")
    return data


def normalized_description(text: str) -> str:
    """Steam 可归一换行和外围空白；正文内容与内部空白保持原样。"""
    return text.replace("\r\n", "\n").strip()


def validate_description(text: str) -> str:
    if not text.strip() or any(char in text for char in ("\ufeff", "\x00", "\r")):
        raise ValueError("工坊正文为空或含 BOM/NUL/CR")
    body = normalized_description(text)
    if len(body.encode("utf-8")) >= 8000:
        raise ValueError("工坊正文 UTF-8 长度必须小于 8000 字节")
    stack: list[str] = []
    for match in re.finditer(r"\[([^\]]*)\]", body):
        tag = match[1]
        if tag == "*":
            if "list" not in stack:
                raise ValueError("工坊 BBCode 列表项缺少 list")
            continue
        closing = tag.startswith("/")
        name = tag.lstrip("/").split("=", 1)[0]
        if name not in {"h1", "h2", "b", "list", "url"}:
            raise ValueError(f"工坊 BBCode 标签不受支持：{tag}")
        if closing:
            if not stack or stack.pop() != name:
                raise ValueError("工坊 BBCode 标签未正确闭合")
        else:
            stack.append(name)
    if stack:
        raise ValueError("工坊 BBCode 标签未闭合")
    return body


def load_descriptions(directory: Path = MATERIALS) -> dict[str, str]:
    rows = publication_config(directory)["descriptions"]
    bodies = {}
    for row in rows.values():
        path = directory / row["file"]
        deployment.reject_links(path)
        # read_bytes 避免通用换行模式掩盖非法 CR。
        bodies[row["steam"]] = validate_description(path.read_bytes().decode("utf-8"))
    return bodies


def write_receipt(path: Path, report: dict[str, Any]) -> None:
    """先完整写入同目录临时文件，再替换收据；中断不会留下半份 JSON。"""
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    temporary.replace(path)
