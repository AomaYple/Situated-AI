"""原则条款编号的一致性：编号唯一连续、引用有定义、执行方式表全覆盖。

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

#: 条款定义行：``- **EP-01 标题**：正文``；废止条款写作 ``- **EP-01（已废止）**：…``，仍算定义。
_DEFINITION = re.compile(r"^- \*\*((?:EP|MP)-\d+)(?=[ （*])", re.MULTILINE)
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
#: 执行方式表“入口与说明”列里写到的测试文件路径。
_TEST_PATH = re.compile(r"tests/test_[A-Za-z0-9_]+\.py")


def _definitions(prefix: str) -> list[str]:
    return _DEFINITION.findall(PAGES[prefix].read_text(encoding="utf-8"))


def _defined() -> set[str]:
    return {identifier for prefix in PAGES for identifier in _definitions(prefix)}


def _references(text: str) -> set[str]:
    return set(_REFERENCE.findall(text))


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
    assert all(identifier.startswith(f"{prefix}-") for identifier in identifiers), identifiers
    assert all(re.fullmatch(rf"{prefix}-\d{{2,}}", identifier) for identifier in identifiers)
    duplicates = sorted({i for i in identifiers if identifiers.count(i) > 1})
    assert not duplicates, f"编号重复：{duplicates}"
    numbers = sorted(int(identifier.split("-")[1]) for identifier in identifiers)
    # 编号不复用、废止条款保留原行，所以集合必须是从 1 起的连续整数；出现顺序不作要求。
    assert numbers == list(range(1, len(numbers) + 1)), f"{prefix} 编号不连续：{numbers}"


def test_受控文档引用的编号都有定义() -> None:
    defined = _defined()
    documents = _checked_documents()
    assert "docs/principles/README.md" in documents
    assert "CONTRIBUTING.md" in documents
    undefined = [
        f"{name}: {identifier}"
        for name in documents
        for identifier in sorted(_references((ROOT / name).read_text(encoding="utf-8")) - defined)
    ]
    assert not undefined, "引用了原则页没有定义的条款编号：\n" + "\n".join(undefined)


def test_执行方式表覆盖全部编号() -> None:
    text = INDEX.read_text(encoding="utf-8")
    heading = "## 条款执行方式"
    assert text.count(heading) == 1
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in text.split(heading, 1)[1].splitlines()
        if line.startswith("|")
    ]
    listed: list[str] = []
    for cells in rows[2:]:  # 跳过表头与分隔行
        assert len(cells) == 3, cells
        identifiers = _REFERENCE.findall(cells[0])
        assert identifiers, f"执行方式表有一行没有条款编号：{cells}"
        assert cells[1] in _STATUSES, f"未知执行方式 {cells[1]!r}：{cells[0]}"
        assert cells[2], f"缺少入口或说明：{cells[0]}"
        missing = _missing_test_paths(cells[2])
        assert not missing, f"入口指向不存在的测试文件：{cells[0]} {missing}"
        listed.extend(identifiers)
    repeated = sorted({i for i in listed if listed.count(i) > 1})
    assert not repeated, f"执行方式表重复登记：{repeated}"
    defined = _defined()
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
