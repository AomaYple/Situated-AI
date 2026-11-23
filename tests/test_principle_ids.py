"""原则编号、现行引用、执行方式与旧编号去向的一致性。

两份原则页用 ``EP-nn`` / ``MP-nn`` 给每条约束一个稳定编号，其他文档只写编号、不复述正文。
编号一旦写错或条款被删，引用就会静默指向不存在的条款；本文件把这三件事接起来核对。
编号与修订规则见 ``docs/principles/README.md``。
"""

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs

ROOT = Path(__file__).resolve().parents[1]
PRINCIPLES = ROOT / "docs" / "principles"
PAGES = {"EP": PRINCIPLES / "工程原则.md", "MP": PRINCIPLES / "Mod开发原则.md"}
INDEX = PRINCIPLES / "README.md"
_MIGRATION_HEADING = "## 旧 Mod 条款去向\n"
_MIGRATION_ENTRY = re.compile(r"^- \*\*(MP-\d+(?:、MP-\d+)*)\*\* ", re.MULTILINE)
_MOD_MIGRATION_LAST_ID = 65

#: 条款定义可用编号列表项，独立 Mod 原则用二级标题。保留的废止工程编号仍算定义。
_DEFINITION = re.compile(r"^(?:- \*\*|## 独立原则 )((?:EP|MP)-\d+)(?=[ （*])", re.MULTILINE)
#: 引用：前后不能紧贴 ASCII 字母数字；中文紧贴是常态，所以不用 ``\b``。
_REFERENCE = re.compile(r"(?<![A-Za-z0-9_])((?:EP|MP)-\d+)(?![A-Za-z0-9_])")
_STATUSES = {"强执行", "部分执行", "仅评审"}
#: 不参与引用核对的受控 Markdown：收据与归档按原字节保留，其余是原版资料或可再生输出。
_EXCLUDED_PREFIXES = (
    "docs/design/archive/",
    "docs/victoria3-modding",
    "research/",
    "tools/out/",
)
_RECEIPT = re.compile(r"^docs/design/exec/[^/]*-结果\.md$")
#: 执行方式表的自动检查入口里写到的测试文件路径。
_TEST_PATH = re.compile(r"tests/test_[A-Za-z0-9_]+\.py")


def _definitions(prefix: str) -> list[str]:
    return _DEFINITION.findall(PAGES[prefix].read_text(encoding="utf-8"))


def _defined() -> set[str]:
    return {identifier for prefix in PAGES for identifier in _definitions(prefix)}


def _references(text: str) -> set[str]:
    return set(_REFERENCE.findall(text))


def _migration_section(index: str) -> str:
    assert index.count(_MIGRATION_HEADING) == 1
    return index.split(_MIGRATION_HEADING, 1)[1].split("\n## ", 1)[0]


def _missing_test_paths(cell: str) -> list[str]:
    """入口列里写到、但仓库中不存在的 ``tests/test_*.py``。"""
    return sorted({path for path in _TEST_PATH.findall(cell) if not (ROOT / path).is_file()})


def _checked_documents() -> list[str]:
    # 未跟踪但未被忽略的新文档也核对，免得引用错误要等提交之后才暴露。
    raw = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.md"],
        cwd=ROOT,
    )
    names = sorted({part.decode("utf-8") for part in raw.split(b"\x00") if part})
    return [
        name
        for name in names
        if not name.startswith(_EXCLUDED_PREFIXES)
        and not _RECEIPT.match(name)
        and (ROOT / name).is_file()
    ]


@pytest.mark.parametrize("prefix", sorted(PAGES))
def test_原则页编号唯一且连续(prefix: str) -> None:
    identifiers = _definitions(prefix)
    assert identifiers, f"{PAGES[prefix].name} 没有任何条款定义"
    minimum = 0
    if prefix == "MP":
        migration = _migration_section(INDEX.read_text(encoding="utf-8"))
        retired = [
            identifier
            for entry in _MIGRATION_ENTRY.findall(migration)
            for identifier in _REFERENCE.findall(entry)
        ]
        assert retired, "缺少已退出正文的 Mod 条款编号"
        identifiers.extend(retired)
        minimum = _MOD_MIGRATION_LAST_ID
    assert all(identifier.startswith(f"{prefix}-") for identifier in identifiers), identifiers
    assert all(re.fullmatch(rf"{prefix}-\d{{2,}}", identifier) for identifier in identifiers)
    duplicates = sorted({i for i in identifiers if identifiers.count(i) > 1})
    assert not duplicates, f"编号重复：{duplicates}"
    numbers = sorted(int(identifier.split("-")[1]) for identifier in identifiers)
    assert numbers == list(range(1, max(len(numbers), minimum) + 1)), (
        f"{prefix} 编号不连续或遗失历史编号：{numbers}"
    )


def test_受控文档引用的编号都有定义() -> None:
    defined = _defined()
    documents = _checked_documents()
    assert "docs/principles/README.md" in documents
    assert "CONTRIBUTING.md" in documents
    undefined: list[str] = []
    for name in documents:
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        if path == INDEX:
            migration = _migration_section(text)
            # 旧号仅可出现于迁移条目的起始位置，其去向仍需引用现行条款。
            text = text.replace(migration, _MIGRATION_ENTRY.sub("- ", migration), 1)
        undefined.extend(
            f"{name}: {identifier}" for identifier in sorted(_references(text) - defined)
        )
    assert not undefined, "引用了原则页没有定义的条款编号：\n" + "\n".join(undefined)


@pytest.mark.parametrize(
    ("prefix", "title", "width"), [("EP", "工程原则", 3), ("MP", "Mod 开发原则", 4)]
)
def test_执行方式表覆盖全部编号(prefix: str, title: str, width: int) -> None:
    text = INDEX.read_text(encoding="utf-8")
    heading = "## 条款执行方式\n"
    assert text.count(heading) == 1
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    table_heading = f"### {title}\n"
    assert section.count(table_heading) == 1
    table = section.split(table_heading, 1)[1].split("\n### ", 1)[0]
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in table.splitlines()
        if line.startswith("|")
    ]
    listed: list[str] = []
    for cells in rows[2:]:  # 跳过表头与分隔行
        assert len(cells) == width, cells
        identifiers = _REFERENCE.findall(cells[0])
        assert identifiers, f"执行方式表有一行没有条款编号：{cells}"
        assert cells[1] in _STATUSES, f"未知执行方式 {cells[1]!r}：{cells[0]}"
        assert all(cells[2:]), f"缺少入口或说明：{cells[0]}"
        missing = _missing_test_paths(cells[2])
        assert not missing, f"入口指向不存在的测试文件：{cells[0]} {missing}"
        listed.extend(identifiers)
    repeated = sorted({i for i in listed if listed.count(i) > 1})
    assert not repeated, f"执行方式表重复登记：{repeated}"
    defined = set(_definitions(prefix))
    assert set(listed) == defined, (
        f"未登记：{sorted(defined - set(listed))}；多登记：{sorted(set(listed) - defined)}"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("见EP-34。", {"EP-34"}),
        ("[EP-06 至 EP-09](工程原则.md)与 MP-41", {"EP-06", "EP-09", "MP-41"}),
        ("`EP-nn`、STEP-12、ARC-05、EP-1x", set()),
        ("EP-5 也算一次引用", {"EP-5"}),
    ],
)
def test_引用识别不漏中文紧贴也不误认其他编号(text: str, expected: set[str]) -> None:
    assert _references(text) == expected


def test_入口列的测试路径核对能发现不存在的文件() -> None:
    cell = "`tests/test_principle_ids.py`、`tests/test_no_such_file_anywhere.py` 与 `run_check.py`"
    assert _missing_test_paths(cell) == ["tests/test_no_such_file_anywhere.py"]
    assert _missing_test_paths("`tests/test_principle_ids.py` 核对编号") == []
    assert _missing_test_paths("未核实到自动检查入口") == []
