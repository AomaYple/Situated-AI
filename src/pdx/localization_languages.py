"""Victoria 3 本体语言目录与 Mod 本地化覆盖契约。

语言集合来自当前锁定的 Victoria 3 1.14.5 本地化快照；如果提供实际游戏目录，
则优先从 ``localization/`` 的语言头重新发现集合。生成器不允许静默丢掉本体语言：
未知语言会进入结果并要求调用方提供文本，缺失语言文件由生成检查报告。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

LANGUAGE_HEADER_RE = re.compile(r"^\s*(l_[A-Za-z0-9_]+)\s*:\s*$")
LANGUAGE_NAME_RE = re.compile(r"l_[A-Za-z0-9_]+")


@dataclass(frozen=True, slots=True)
class Language:
    """本体语言在文件系统和 `.yml` 头中的稳定表示。"""

    directory: str
    header: str

    @property
    def suffix(self) -> str:
        return self.header


# Victoria 3 release/1.14.5 的 localization_digest（按目录名稳定排序）。
DEFAULT_LANGUAGES: tuple[Language, ...] = tuple(
    Language(directory, f"l_{directory}")
    for directory in (
        "braz_por",
        "english",
        "french",
        "german",
        "japanese",
        "korean",
        "polish",
        "russian",
        "simp_chinese",
        "spanish",
        "turkish",
    )
)
DEFAULT_LANGUAGE_BY_DIRECTORY: Mapping[str, Language] = {
    language.directory: language for language in DEFAULT_LANGUAGES
}
DEFAULT_LANGUAGE_BY_HEADER: Mapping[str, Language] = {
    language.header: language for language in DEFAULT_LANGUAGES
}


def _language_from_header(header: str, directory: str) -> Language:
    if LANGUAGE_NAME_RE.fullmatch(header) is None:
        raise ValueError(f"本地化语言头必须以 l_ 开头：{header!r}")
    if not directory or directory in {".", ".."} or "/" in directory or "\\" in directory:
        raise ValueError(f"本地化语言目录无效：{directory!r}")
    return Language(directory=directory, header=header)


def discover(game_root: Path) -> tuple[Language, ...]:
    """从实际游戏内容根发现语言集合。

    只读取 ``localization/<目录>/**/*.yml`` 的首个语言头；没有可读语言文件时
    明确失败，避免在游戏目录不完整时退回一个看似成功的双语集合。
    """

    localization = game_root / "localization"
    if not localization.is_dir():
        raise ValueError(f"游戏本地化目录不存在：{localization}")
    found: dict[str, Language] = {}
    directory_headers: dict[str, str] = {}
    for path in sorted(localization.glob("*/**/*.yml")):
        try:
            lines = path.read_text(encoding="utf-8-sig", errors="strict").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"无法读取游戏本地化文件：{path}：{exc}") from exc
        header = next((m.group(1) for line in lines if (m := LANGUAGE_HEADER_RE.match(line))), None)
        if header is None:
            continue
        directory = path.relative_to(localization).parts[0]
        previous_header = directory_headers.get(directory)
        if previous_header is not None and previous_header != header:
            raise ValueError(
                f"同一语言目录出现多个语言头：{directory!r} ({previous_header!r}, {header!r})"
            )
        directory_headers[directory] = header
        language = _language_from_header(header, directory)
        previous = found.get(header)
        if previous is not None and previous.directory != directory:
            raise ValueError(
                f"同一语言头对应多个目录：{header!r} ({previous.directory!r}, {directory!r})"
            )
        found[header] = language
    if not found:
        raise ValueError(f"游戏本地化目录没有发现语言头：{localization}")
    return tuple(sorted(found.values(), key=lambda language: language.directory))


def from_snapshot(snapshot: Mapping[str, object]) -> tuple[Language, ...]:
    """从精简快照的 ``域.localization_digest`` 恢复语言集合。"""

    domains = snapshot.get("域")
    digest = domains.get("localization_digest") if isinstance(domains, Mapping) else None
    if not isinstance(digest, Mapping) or not digest:
        raise ValueError("快照缺少域.localization_digest，无法确认本体语言集合")
    languages: list[Language] = []
    for header in digest:
        if not isinstance(header, str) or not header.startswith("l_"):
            raise ValueError(f"快照包含无效语言头：{header!r}")
        languages.append(_language_from_header(header, header[2:]))
    return tuple(sorted(languages, key=lambda language: language.directory))


def normalize(languages: Iterable[Language | str]) -> tuple[Language, ...]:
    """校验并排序调用方提供的语言目录或语言头。"""

    result: dict[str, Language] = {}
    for value in languages:
        if isinstance(value, Language):
            language = _language_from_header(value.header, value.directory)
        elif isinstance(value, str):
            if value.startswith("l_"):
                language = _language_from_header(value, value[2:])
            else:
                language = _language_from_header(f"l_{value}", value)
        else:
            raise TypeError(f"语言必须是 Language 或字符串：{value!r}")
        previous = result.get(language.header)
        if previous is not None and previous != language:
            raise ValueError(f"同一语言头对应多个目录：{language.header}")
        result[language.header] = language
    if not result:
        raise ValueError("Mod 至少需要一种本体语言")
    return tuple(sorted(result.values(), key=lambda language: language.directory))


def localization_path(language: Language, prefix: str) -> str:
    """返回 Mod 本地化文件的游戏内相对路径。"""

    return f"localization/{language.directory}/{prefix}_l_{language.directory}.yml"


def language_headers(languages: Iterable[Language] = DEFAULT_LANGUAGES) -> tuple[str, ...]:
    return tuple(language.header for language in normalize(languages))
