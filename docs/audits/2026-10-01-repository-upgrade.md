# 2026-10-01 仓库工程审计

本页记录本轮工程整理的实际改动、验证证据与保留边界。
游戏设计与处境档案仍由 `docs/design/` 和 `mod/data/` 定义。

## 当前政策

全部仓库文本，包括忽略的第三方文本与历史证据，统一 UTF-8 无 BOM、LF。
二进制资产、ZIP 中的精确原件和 Git 对象不进行文本转码。
游戏脚本与本地化的 BOM 在部署或打包时添加，源码无 BOM。
损坏的证据字节使用显式转义，原件备份才是字节层面的权威记录。

原始审计逐件读取全部文件与目录，排除 Git 对象库、不跟随符号链接。
起始清单包含 16,414 个文件与 1,702 个目录，读取错误为零。
完整原始清单及备份位于 `tools/out/repository-audit/`，由 Git 忽略。

## 目录处置

| 目录 | 决定与理由 |
|---|---|
| `mod/data/` | 跟踪 TOML 游戏数据源，保持生成链与设计事实同源 |
| `mod/` 其余目录 | 跟踪确定性无 BOM 生成物，打包输出单独添加 BOM |
| `src/pdx/` | 跟踪 Python 工具链，逐模块检查导入、测试、覆盖率与运行热点 |
| `tests/` | 跟踪单元、属性、差分、黄金、集成、CLI、恢复、性能等测试 |
| `tools/ci/` | 跟踪跨平台 Python 检查入口 |
| `tools/benchmarks/`、`tools/prof/` | 跟踪测量脚本，忽略机器读数、二进制 profile |
| `tools/probe/` | 跟踪仪器；真实窗口操作保留 Windows 边界 |
| `tools/probe/frozen/` | 保留历史来源，解释当前实现与历史口径的区别 |
| `tools/out/` | 保留原始证据、可恢复备份与机器报告；仅精简版本快照进入 Git |
| `docs/`、`docs/reports/` | 保留历史引用路径，新增导航；当前政策集中于本报告 |
| `research/official-docs/` | 不跟踪正文，规范化本地镜像；清单记录游戏原件及镜像各自哈希 |
| `.venv/` | 保留本机依赖并继续用于执行，文本归一前备份；不纳入 Git |
| 缓存 | 验证可再生成后，先归档精确原件与哈希，再清理 |
| `.agent-teams/`、编辑器目录 | 保留机器运行状态并忽略；不作为项目功能代码改写 |

## 跨平台与成熟库

工具链使用平台路径候选与环境变量 `V3_ROOT`、`V3_USERDIR`、`V3_WORKSHOP`。
依赖解析改用 `packaging` 实现 PEP 508；内存和进程测量改用 `psutil`。
原生 Windows 库附带平台依赖条件，无 Win32 时仍能导入纯解析与图像逻辑。
`tools/ci/run_check.py` 自动选择 `.venv/Scripts/python.exe` 或 `.venv/bin/python`。
CI 配置覆盖 Windows、macOS、Linux 和 Python 3.11、3.14。
本机为 Windows；CI 未远程运行，因此三平台实际结果仍须由矩阵验证。

真实游戏窗口自动化目前只有 Windows 实现，其他系统明确报不支持。
平台模拟证明可导入与逻辑可测，不等于真实 macOS / Linux 游戏自动化通过。

## 编码与交付

第一批规范化 5,045 件，第二批 49 件，最终补归一 6 件测试日志/报告；共 5,100 件。
每批 ZIP 包含 `RESTORE-MANIFEST.json`。
`encoding-originals.zip` 保存第一批原件，`encoding-followup-originals.zip` 保存第二批原件。
第三方测试语料中刻意构造的 BOM、CRLF 也按用户要求归一；需要供应商原始语料时从备份恢复。

```text
python -m pdx.repo_audit --project-only --output tools/out/repository-audit/source-encoding.json
python -m pdx.normalize_repo --root <目录> --backup <新建的备份.zip>
python -m pdx.normalize_repo --root <目录> --backup <已存在的备份.zip> --restore
python -m pdx.cli package --output dist/situated-ai.zip
```

恢复会先核对清单、原件哈希和当前文件哈希；文件后续修改过时拒绝覆盖。
备份应独立保留；它们没有加入 Git，删除工作区也会删除这些本地副本。

缓存第一批清理 71 个目录、1,531 个文件、84,053,159 B，精确原件保存在
`cache-originals.zip`（36,151,319 B）；删除前校验 ZIP CRC、每件哈希与当前字节。
其中包括仓库根的 `v3-parse-cache-*`、自有 `__pycache__`、pytest、mypy、ruff、Hypothesis
与基准缓存。依赖本体、第三方编译文件与实机证据保留。
检查完成后的缓存补清理另保留 `cache-originals-followup.zip`：271 件、31,670,910 B。
两批共 1,802 件、115,724,069 B。Python 校验入口会重新生成少量字节码，继续由 Git 忽略。

## 测试与性能方法

完整功能测试、coverage、JUnit 和进程树 RSS 分开于 cProfile 测量。
profile 记录每个实际执行模块的函数自身耗时（默认 cProfile 计时，不等同 OS CPU 时间）；未执行仪器会明确登记，AST 检查不冒充运行测试。
运行时间与 tracemalloc 分开测量，结果指纹必须一致。

七轮独立同进程对照测量结果如下；重建优化前算法作基线，环境与输入一致。

| 工作负载 | 优化前中位时间 | 优化后中位时间 | 优化前 Python 分配峰值 | 优化后 Python 分配峰值 |
|---|---:|---:|---:|---:|
| 重复文件引用 | 0.5189767 s | 0.0032335 s | 1,381,798 B | 1,214,844 B |
| 大型本地化首行 | 0.0077108 s | 0.0002018 s | 14,133,673 B | 149,943 B |
| 完整生成器 | 0.0367361 s | 0.0363218 s | 2,373,478 B | 2,340,310 B |

引用扫描只在同一次调用缓存文件行数，下一次调用可见文件编辑。
本地化语言头仅读首行，通过任意字节差分测试验证与原算法一致。
完整生成器的差异接近噪声，不能宣称获得明显提速。

## 具体修复与验证

移除生成器未调用的 `_writes_bom`、doc16 返回语句后的不可达重复实现、性能脚本的
废弃 `V3` 常量、重复帮助测量与无用参数。实际游戏数据源的数值、条件与权重保持既有状态。

PDX 脚本是游戏引擎的专用语言，GitHub Actions 与 TOML 是配置格式，不能转成 Python
再要求原有消费者直接读取。保留这些必需格式，生成、检查、部署、恢复与测量使用 Python。
`packaging` 替代自制依赖版本/标记解析，`psutil` 替代手写 Win32 内存结构与进程命令。
旧测量仪器留档供核对，真实窗口控制仍通过明确的 Windows 边界。

doc16 原先两处手写的机械统计改为生成表，重算后 174 张表、2,215 行数据。
数量断言 234/234 通过；1.14.5 精简快照与官方文档 manifest 同步更新。
交付 ZIP 包含 69 个生成物与 SHA-256 清单，其中 59 个游戏脚本/本地化文件带一个 BOM。

当前收集 2,151 个测试，84 个测试文件。最近一次普通全量运行是新增最后 8 个用例前：
2,135 通过、8 跳过、499 子断言通过，pytest 351.95 s；外层墙钟 353.566 s，
50 ms 采样进程树 RSS 峰值 5,477,957,632 B。此读数含测量与本机并发扰动，不能据此宣称整套提速。
后续新增 CLI 表格恢复、覆盖率加权与跨平台路径用例均单独执行；最终补测结果见
`tests-final-additions-pass.xml`。完整失败记录保留在审计证据目录。
最终补测是 100 项通过、3 项因符号链接权限跳过；原有模块组覆盖率由
88.5179% 提高到 88.8170%，当前全部模块的官方覆盖率为 **89.0204%**。
`v3 cov` 与 coverage 官方整体值逐数值一致，11 个核心模块下限均通过。

无游戏环境将三个 V3 路径指向不存在的目录：7 道离线闸门通过，1,811 用例通过、
129 跳过、25 子断言通过；后续新增的覆盖率回归属于纯离线单测。
无 Win32 导入模拟：207 项通过。独立 pytest-benchmark：18 项通过。
ruff 检查、格式检查、mypy 与 Git diff 空白检查通过；Git fsck 未发现损坏，未清理悬空历史对象。

覆盖率采用 coverage 的语句与分支总点数口径。修正 `v3 cov` 原来按语句数加权模块百分比的
错误算法，并验证 Windows 与 POSIX 路径均可读取同一报告。
新增模块改变了分母，因此旧记录 85.84%（含当时未覆盖的新模块）不能直接当作纯测试增益。
同一组原有模块的对照另见 `comparable-coverage.json`，代码仍有增加，分母也一并记录。

173 件活跃 Python 文件逐件登记，65 个包文件（含初始化）独立导入成功并测量采样 RSS；
64 个功能模块都出现在实际测试 profile 中。profile 还记录 7 个执行过的辅助模块。
导入测量包含该模块与依赖的总成本，采样间隔 10 ms；不把短命解释器错分为启动壳而报零内存。
历史、一次性实机仪器与第三方代码的运行缺口单独标注，静态解析成本不替代真实运行测试。

## 可复核证据

`tools/out/repository-audit/` 不入 Git，但本机保留以下完整产物：

| 产物 | 内容 |
|---|---|
| `before.json`、`final-inventory.json` | 所有磁盘文件的分类、Git 状态、SHA-256、编码统计与所有目录 |
| `file-dispositions.json`、`directory-dispositions.json` | 逐件处置决定与目录统计 |
| `python-module-ledger.json` | 源码、独立导入时间/内存、实际 profile 与 coverage 的关联 |
| `coverage-final.json`、`comparable-coverage.json` | 官方语句/分支覆盖率与原有模块对照 |
| `tests-final.xml`、`tests-final-additions-pass.xml`、`tests-no-game.xml` | 全量、最后补测与无游戏验证 |
| `profiles-full/`、`profiles-followup/`、`profiles-final-pass/` | 原始 cProfile 与汇总；函数自身耗时不等同 OS CPU |
| `performance-isolated-before.json`、`performance-isolated-after.json` | 同环境、同输入、七轮时间与 Python 分配峰值 |
| `benchmark-final.json` | 18 项独立基准的原始读数 |
| `encoding*.zip`、`cache-originals*.zip` | 原件与清理缓存的可恢复副本 |
| `backup-verification.json`、`final-encoding-issues.json` | 备份验证与最终编码问题清单 |
| `situated-ai-game.zip` | 带游戏 BOM 的确定性交付包 |

最后一次工作区盘点读取 15,134 个文件、1,636 个目录，所有分类文本的编码违规为零，
读取错误与 Python AST 错误均为零。Git 内部另读取 556 个文件、239 个子目录，文本 BOM/CR
违规为零；内部压缩对象保持原始字节。清单是生成时的快照，后续自生成的清单与汇总文件另行验证。
两批缓存 ZIP、三批编码 ZIP 的 CRC 与每件原始 SHA-256 全部通过。
原始 ZIP 中含有历史 BOM/CRLF，是用于精确恢复的二进制备份，不作文本改写。

## 保留的验证边界

本轮不启动游戏、不改平衡数值、不提交或推送。
历史引擎日志因其他 Workshop mod 覆盖 GUI，与本机当前内容不相容；对应测试跳过并记录原因。
真实长时间游戏、其他操作系统原生执行和第三方库的全部测试不能由本机仓库测试替代。
未测到的路径会保留在模块台账中，不宣称所有 Python 函数都已运行或优化。
