# tools —— Python 工具链

Victoria 3 游戏本体与 mod 的信息处理工具链。**纯 Python 实现，仅依赖标准库。**

> 早期版本用 PowerShell（10 个脚本）与 Node.js（2 个原型）实现，已全部退休。
> 退休原因见文末「为什么全 Python 化」。

## 环境

```
.venv/                          Python 3.14.7 虚拟环境（已 gitignore）
.venv\Scripts\python.exe        解释器
```

虚拟环境用 `python -m venv .venv` 创建。**pip 的安装功能在沙箱里不可用**
（临时目录操作被拒），但标准库完全够用，本工具链不依赖任何第三方包。

若要装第三方包（如 pytest），请在自己的终端里执行一次：

```
.venv\Scripts\python.exe -m pip install <包名>
```

## 包结构 `pdx/`

| 模块 | 职责 |
|---|---|
| `model.py` | 数据模型：`Assignment` / `Block` / `Scalar` / `ParsedFile` |
| `lexer.py` | 词法：引号感知的注释剥离、运算符识别、行号追踪 |
| `parser.py` | 语法：递归下降，**花括号深度判定顶层** |
| `cache.py` | 解析缓存，保证同一文件只解析一次 |
| `config.py` | 路径与常量，支持 `V3_ROOT` / `V3_USERDIR` / `V3_WORKSHOP` 覆盖 |
| `scan.py` | 文件系统扫描与统计 |
| `extract.py` | 目录级条目与字段提取 |
| `defines.py` | defines 专用提取（命名空间、参数形态、覆盖预览） |
| `mods.py` | Workshop 与本地 mod 分析 |
| `analyze.py` | 全量分析（游戏本体 / mod / 交叉，**分开存储**） |
| `verify.py` | 断言注册表，把文档里的数字变成可执行检查 |

## 命令行入口

| 脚本 | 作用 |
|---|---|
| `run_analyze.py` | 全量分析游戏本体与全部 mod |
| `run_defines.py` | 提取 defines，支持 `--ns NAI` 与覆盖预览 |
| `run_verify.py` | 核对知识库文档中的数量断言 |
| `check_outputs.py` | 核验分析产物的关键数字 |
| `show_outputs.py` | 列出产出文件的结构与规模 |

常用命令：

```powershell
$py = ".venv\Scripts\python.exe"

& $py tools/run_analyze.py              # 全量分析，落盘报告
& $py tools/run_analyze.py --no-mods    # 只分析游戏本体
& $py tools/run_verify.py               # 核对全部断言
& $py tools/run_verify.py --fast        # 跳过需要全库扫描的检查
& $py tools/run_defines.py --ns NAI     # 看 AI 参数
& $py tools/check_outputs.py            # 核验产物
```

## 测试

```powershell
& $py -m unittest discover -s tools/tests
```

用例全部对应**实际踩过的坑**，不是凭空构造：

| 测试文件 | 覆盖的坑 |
|---|---|
| `test_lexer.py` | 注释内花括号、字符串中的 `#`、`?=` 不被拆开、行号追踪 |
| `test_parser.py` | BOM 污染首键、含连字符的键、`c:SWE` 不被误认为前缀、缩进的顶层键、`=` 与 `{` 分行 |
| `test_scan.py` | 递归计数、后缀过滤、真实游戏树的结构断言 |
| `test_extract.py` | 字段只收第一层、前缀归类、跨文件合并、已知条目数 |

## 输出产物

**分开存放** —— 游戏本体与 mod 互不混杂：

```
tools/out/game/游戏本体.json      游戏本体全量数据（约 7.9 MB）
tools/out/mods/mod.json          mod 全量数据（约 650 KB）
tools/out/cross/交叉.json         两者的覆盖关系
tools/reports/游戏本体分析.md      人可读报告
tools/reports/mod分析.md          人可读报告
```

`tools/out/` 与 `tools/reports/` 已 gitignore —— 可由脚本随时重新生成。

## 解析器的五条铁律

这些是踩坑换来的，改代码时不要违反：

```
1. 用花括号深度判断顶层        —— 官方文件混用 tab / 空格 / 无缩进
2. 剥离 BOM                    —— common 下 3024 个 .txt 有 3000 个带 BOM
3. 注释剥离要引号感知          —— 字符串里可能含 #
4. 键名字符集用「非空白非等号」  —— 存在含连字符的键（全库 32 个）
5. 识别 6 个功能前缀           —— INJECT: / REPLACE: 等
```

另有两条口径纪律，都曾导致过真实错误：

* **`@变量` 不是数据条目** —— `00_defines.txt` 顶部 22 个，误计会让命名空间块数从 75 变成 97
* **空目录也要收录** —— `scripted_modifiers` 只有 `.md` 没有 `.txt`，靠「有没有 .txt」数目录会得到 135 而非 136

## 沙箱环境注意事项

在 DSH 沙箱里开发本工具链时遇到并已规避的问题：

| 问题 | 规避方式 |
|---|---|
| 控制台是 GBK 代码页，`print` emoji 会抛 `UnicodeEncodeError` | 入口脚本统一 `sys.stdout.reconfigure(encoding="utf-8")` |
| `tempfile` 创建的目录权限受限，沙箱拒绝写入 | 测试改用工作区内的自管临时目录 |
| pip 安装功能不可用（临时目录操作被拒） | 不依赖第三方包 |

## 为什么全 Python 化

| 原因 | 具体表现 |
|---|---|
| PowerShell 5.1 的编码陷阱 | 不加 `-Encoding utf8` 按 GBK 解码；`Set-Content -Encoding UTF8` 写 BOM |
| PowerShell 的反引号转义 | 字符串里写 Markdown 代码块会报语法错误（开发中触发多次） |
| 缺少数据结构 | 解析结果只能用 PSCustomObject 拼，不如 dataclass 清晰 |
| 无法写正经测试 | PowerShell 没有 `unittest` 那样的测试框架 |
| Node 需要额外运行时 | 而 Python 的 `utf-8-sig` 编码名天然解决 BOM 问题 |

Python 版把上述问题都变成了**可测试的代码**：106 个单元测试 + 35 条断言核验。

## 诊断脚本 `diag/`

开发期用来定位问题的临时脚本，保留作参考：

| 脚本 | 用途 |
|---|---|
| `diag_perf.py` | 剖析各阶段耗时，定位性能瓶颈 |
| `diag_numbers.py` | 核查存疑的计数（目录数、DLC 数、解析错误） |
| `diag_defines.py` | 诊断 defines 块数口径差异 |
