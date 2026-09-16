"""Victoria 3 PDX 脚本解析器。

本包把游戏本体与 mod 的 PDX 脚本文件解析为结构化数据，供扫描、提取、
核对与清理使用。纯标准库实现，无第三方依赖。

模块划分
--------
model    数据模型（Assignment / Block / Scalar / File）
lexer    词法分析：注释剥离、引号识别、花括号与运算符切分
parser   语法分析：递归下降，产出 AST
config   路径与常量
"""

from .model import Assignment, Block, ParsedFile, ParseError, Scalar
from .parser import parse_file, parse_text

__all__ = [
    "Assignment",
    "Block",
    "ParseError",
    "ParsedFile",
    "Scalar",
    "parse_file",
    "parse_text",
]

__version__ = "0.1.0"
