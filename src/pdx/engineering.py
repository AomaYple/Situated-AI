"""工程基线契约。

这里集中放不会随单个实现细节漂移的工程口径：测试分层、跳过原因分类、
快照格式和 CLI 契约版本。CI 与本地工具都从这里取值，避免在多个脚本里
各自维护一份略有差异的清单。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

ENGINEERING_BASELINE: Final[str] = "1.0"
SNAPSHOT_FORMAT: Final[int] = 1

TEST_TIERS: Final[dict[str, str]] = {
    "quick": "不依赖游戏的快速回归：单元、契约、属性与 CLI",
    "offline": "无游戏离线门禁：快照、表格、modgen、modguard、引用与发布",
    "full": "装有游戏的完整套件：分析、文档数字、引擎交叉验证与黄金产物",
    "live": "真实 Victoria 3 GUI/运行期实验；只在具备对应平台和游戏时执行",
}


@dataclass(frozen=True, slots=True)
class SkipCategory:
    """一个可报告的跳过类别。"""

    name: str
    description: str


SKIP_CATEGORIES: Final[dict[str, SkipCategory]] = {
    "game": SkipCategory("game", "需要 Victoria 3 游戏本体、用户目录或引擎日志"),
    "artifact": SkipCategory("artifact", "需要本地生成物、快照、语料或 UI 模板"),
    "platform": SkipCategory("platform", "需要特定操作系统能力或权限"),
    "tool": SkipCategory("tool", "需要 git、ruff 或其他开发工具"),
    "live": SkipCategory("live", "需要真实游戏 GUI 或运行期会话"),
    "environment": SkipCategory("environment", "需要本机特定配置、安装或外部资源"),
}

# 规则按具体短语优先；最后的通用词只用于确实已经声明为环境缺失的旧用例。
_SKIP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("game", ("游戏目录", "没有游戏", "无游戏", "victoria3.exe", "引擎日志", "游戏本体")),
    ("artifact", ("产物", "快照", "语料", "模板", "doc ", "mod/data", "样本文件")),
    ("platform", ("Windows", "Linux", "macOS", "chcp", "符号链接权限")),
    ("tool", ("ruff 不可用", "找不到 git", "开发工具")),
    ("live", ("实机", "真实游戏", "GUI", "运行期", "会话")),
)


def classify_skip_reason(reason: str) -> str | None:
    """把 pytest 的跳过原因映射到稳定类别，无法判断时返回 ``None``。

    空原因和纯空白原因故意不归类：它们应该在 CI 报错，而不是被归到
    ``environment`` 后静默掩盖。
    """

    normalized = reason.strip()
    if not normalized:
        return None
    for category, phrases in _SKIP_RULES:
        if any(phrase.casefold() in normalized.casefold() for phrase in phrases):
            return category
    if any(word in normalized for word in ("不可用", "不存在", "未安装", "没有")):
        return "environment"
    return None


def require_skip_category(reason: str) -> str:
    """返回跳过类别；未知原因直接抛错，避免 CI 产生不可解释的 skipped。"""

    category = classify_skip_reason(reason)
    if category is None:
        raise ValueError(f"无法分类的测试跳过原因：{reason!r}")
    return category


__all__ = [
    "ENGINEERING_BASELINE",
    "SKIP_CATEGORIES",
    "SNAPSHOT_FORMAT",
    "TEST_TIERS",
    "SkipCategory",
    "classify_skip_reason",
    "require_skip_category",
]
