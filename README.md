# Situated AI

Victoria 3 的 AI 相关 mod 开发项目。

开发与维护见 [CONTRIBUTING.md](CONTRIBUTING.md)，编码代理的项目入口见 [AGENTS.md](AGENTS.md)。两类开发原则分别见 [工程原则](docs/principles/工程原则.md)和 [Mod 开发原则](docs/principles/Mod开发原则.md)。

> **当前状态**：工程底座继续复用，包括 **21 篇的 mod 开发知识库**、
> **可复现统计数据的 Python 工具链**和当前的**实验性 mod 实现**：
> 生产数据源 `mod/decisions/fiscal.toml` 与 `mod/decisions/extensions.toml` 生成财政规则、扩展配置和默认策略的条件偏置；扩展当前默认关闭。
> 旧 `mod/data/*.toml` 的 **9 份实验档案、69 个产物**隔离在 `mod/legacy/`，不进入生产 ZIP。
> **新机制已实现且两国财政生命周期有 Windows 实机证据；实际外交收益、稳定性与扩展仍在验证。**
>
> **接手 / 隔久了再回来：先读 [`当前 mod 设计`](docs/design/03-处境决策设计.md)和 [`工程基线`](docs/design/exec/工程基线-1.0.md)。**
> 前者定义通用处境判断、策略行为和验收；后者定义继续复用的工具链、测试、快照与证据边界。
> 下一步见 [`mod 重设计实施计划`](docs/design/exec/mod重设计-实施计划.md)，当前阻塞和下一步见 [当前工作清单](docs/design/当前工作清单.md)，历史编号与原件见 [`backlog`](docs/design/backlog.md)。
> 旧方向与阶段接手记录保留为历史依据；文档总览见 [`docs/README.md`](docs/README.md)。

mod 的目标是让 AI 国家依据内部因素、外部因素和自身政治偏好，在可行路线中作出更合理的选择，
并随玩家改变世界重新评估。实现方向是**通用处境判断 + 少量长期策略及动态行为参数 + 原版 AI 执行**。
优先读取真实世界状态；新增世界模拟机制单独设计和验证。Python 负责生成与测试，游戏运行不依赖外部 Python 服务。

工程测试、快照、CI 摘要和自动化状态轨迹的冻结口径见
[`docs/design/exec/工程基线-1.0.md`](docs/design/exec/工程基线-1.0.md)。本地离线闭环可直接运行：

```text
.venv\Scripts\python.exe tools\ci\run_check.py baseline
```

## 环境

| 项目 | 值 |
|---|---|
| 游戏 | Victoria 3 **1.14.5 (Ice Tea)** |
| Clausewitz | `caligula/release/1.14.x` |
| Steam App ID | `529340` |
| Python | 3.11+（本机 3.14） |
| 工具链平台 | Windows / macOS / Linux；实机窗口自动化目前仅支持 Windows |

> ⚠️ **版本跨度**：知识库多数主题文档的统计与「零使用」类结论**采集于 1.14.2**，
> 而游戏已升级到 1.14.5，这些结论尚未逐条重测。已核验的数字见 `v3 verify`
> （断言表已更新到 1.14.5），文档与断言表的一致性由测试持续看守。

## 知识库

[`docs/victoria3-modding/`](docs/victoria3-modding/) —— **21 篇 / 约 1.4 MB**，
基于对本机游戏安装目录与用户数据目录的逐文件读取整理而成，而非网上二手资料。

| 想了解 | 看这里 |
|---|---|
| 怎么做一个 mod（结构 / 加载 / 覆盖机制） | [`02-Mod结构与加载.md`](docs/victoria3-modding/02-Mod结构与加载.md) |
| 真实 mod 都改了什么 | [`12-真实mod解剖与改造面地图.md`](docs/victoria3-modding/12-真实mod解剖与改造面地图.md) |
| **AI 系统怎么改** | [`03-AI系统.md`](docs/victoria3-modding/03-AI系统.md) · [`09-AI-mod实战技法.md`](docs/victoria3-modding/09-AI-mod实战技法.md) |
| 某个目录里定义了什么 | [`13-common全量键名索引.md`](docs/victoria3-modding/13-common全量键名索引.md) |
| 游戏自带官方文档有哪些坑 | [`07-官方文档索引.md`](docs/victoria3-modding/07-官方文档索引.md) |

完整索引见 [`docs/victoria3-modding/README.md`](docs/victoria3-modding/README.md)。

### 几个关键结论

- **引擎内置「数据功能前缀」**（`INJECT:` / `REPLACE:` 等 6 个）—— 可精确到**单个键**
  覆盖，官方 94 篇文档**零记载**，原版一处不用，但 23 个 mod 用了 **2,737** 次
- **联机校验和只覆盖 5 个目录**（`common/ events/ map_data/ gui/ localization/`）
- **不需要 `descriptor.mod`** —— 现代格式是 `.metadata\metadata.json`
- **调试模式**：启动参数加 `-debug_mode`，错误看 `logs\error.log`、
  覆盖冲突看 `logs\database_conflicts.log`、AI 看 `logs\ai.log`

## 工具链

[`src/pdx/`](src/pdx/) —— Python 实现的 PDX 脚本解析与信息提取核心包；[`tools/`](tools/) 保留 CI、探针、基准和操作手册。
**它不说自己「全量」**：文件维度确实逐文件覆盖（可证伪，有引擎日志背书），
但「所有与 mod 开发相关的信息」没有边界。仓库只声明**能回答哪些任务** ——
见 [`tools/README.md`](tools/README.md) 末尾的「已知边界」。

Windows（无需激活虚拟环境）：

```text
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"   # 一次性安装
.venv\Scripts\python.exe -m pdx.cli analyze --quiet   # 可脚本化范围分析并落盘
.venv\Scripts\python.exe -m pdx.cli verify --fast     # 核对文档里的数量断言
```

macOS / Linux：

```text
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pdx.cli verify --from-snapshot
.venv/bin/python -m pdx.cli tables --offline
.venv/bin/python -m pdx.cli modguard --offline
```

游戏位置由 `V3_ROOT` 配置；没有游戏时使用离线快照路径。检查统一使用
`python tools/ci/run_check.py <lint|format|types|test|test-offline|offline|encoding>`，入口会优先选择
当前平台的仓库 `.venv`。Windows 的 `requirements.lock` 用于该平台的依赖对账，
macOS / Linux 从 `pyproject.toml` 安装对应平台依赖。

### 游戏安装与编码

仓库全部文本采用 **UTF-8 无 BOM、LF**。游戏脚本和本地化的 BOM 由安装或打包边界添加；
因此安装时使用部署工具或 `python -m pdx.cli package --output dist/situated-ai.zip`，
解压 ZIP 到独立 mod 目录后挂载该目录。ZIP 内的 `DISTRIBUTION-MANIFEST.json`
记录每个交付文件的 SHA-256。仓库里的 `mod/` 是无 BOM 的源码产物目录。

### 它做什么

把游戏与 mod 中**所有可脚本化的内容**解析成结构化数据。`v3 analyze` 一次产出 **8 份**：

| 产物 | 内容 |
|---|---|
| `游戏本体.json` | 各目录的条目、字段、使用频次等**统计**（约 8.2 MB） |
| `游戏数据.json` | 每个条目的字段、值、嵌套结构、**行号与注释**（约 54 MB） |
| `本地化.json` | 14.5 万个键（11 种语言） |
| `表格数据.json` | `adjacencies.csv` 等非 PDX 语法数据 |
| `mod.json` | 23 个 mod 的覆盖与新增 |
| `交叉.json` | 哪些原版条目被哪些 mod 改动 |
| `游戏本体分析.md` / `mod分析.md` | 上面这些数据的人可读报告（**入库**，其余在 `tools/out/`，已 gitignore） |

分析还会单独保留引擎层（`jomini/`、`clausewitz/`）的脚本条目、defines、GUI
与本地化摘要；mod 的完整 `.metadata/metadata.json`、本地化键值、重复键、占位符、
资源引用和断链；以及 DLC 的描述符来源、同名键的全部值。游戏树同时建立轻量资源
索引（路径、大小、扩展名），不读取大型二进制内容，避免只看 `game/` 或只看 `.txt`
时漏掉可覆盖的接口。

另有一条**独立**的版本快照线（`v3 snapshot create`）：捕获某个版本的全部
mod 相关信息，游戏升级后 `v3 snapshot diff` 一次就能看出 Paradox 增删了哪些字段。

| 形态 | 命令 | 体积 | 是否入库 |
|---|---|---:|---|
| 完整快照 | `v3 snapshot create` | 约 41 MiB | 否（本机深挖用，含完整本地化键清单） |
| **精简快照** | `v3 snapshot create --compact` | 约 8.0 MiB | **是** —— 只留结构域，本地化换成「键数 + sha256」 |

精简快照入库的意义：**跨版本 diff 在别人的机器上也能做**，而不只是本机。

### 它验证自己吗

是，而且分三层：

| 层 | 机制 |
|---|---|
| 覆盖面 | 每个文件必须归入四类之一，由测试强制；并由**引擎日志**外部背书 |
| 转录正确性 | 与引擎日志里报告的 `文件:行号` 逐条比对（token 行号 100% 一致） |
| 产物不变性 | 黄金回归冻结全部产物的 sha256，改一个字节即失败 |

234 条数量断言分两处核验：本地跑 `v3 verify`（真值来自游戏本体），
CI 跑 `v3 verify --from-snapshot`（真值来自**入库的离线真值**：精简快照 + 官方文档清单，覆盖其中 43 条）。
两条路径共用同一份断言注册表与同一个漂移扫描，不会出现「测试过了但工具没发现」。

**174 张生成表也有对称的那一条**：算它们要读游戏，于是「表被手改、或改了生成器
却忘了重跑」在 CI 上原本无人看守。现在精简快照里带着每张表当时的数据行，
`v3 tables --offline` 只读快照与文档即可逐行核对（`--write` 可按快照恢复），
.github/workflows/ci.yml 运行此检查；pre-commit 运行编码、Ruff、mypy 与离线断言核验，不运行表格检查或 pytest。`.pre-commit-config.yaml` 与 `ci.yml` 的对应关系写在
配置文件里；钩子不能替代完整回归。

**正文里的数字由「归属标记」绑定**：写法是 `共 205<!--claim:dip.group_files--> 个文件`
（HTML 注释，GitHub 渲染时不可见）。它把「这个数字属于哪条断言」写进文档本身，于是：

* `v3 verify` 检查标记处的数字与断言期望是否一致，不一致就报红并指出行号；
* **`v3 verify --fix` 只改带标记的那一个数字** —— 不是「猜着改文本」，而是「按归属改」，
  包裹（`**粗体**` / 反引号）与千分位风格原样保留，因此重复运行零改动；
* 有标记的断言**不再参与**锚点漂移扫描 —— 绑定比启发式精确，于是原先那 59 条
  「锚点太通用」的豁免和 10 条「口径错配」登记全部清空（现各剩 1 / 0 条）。

游戏升级后的维护因此是**一条命令**：`v3 refresh`（= `v3 tables --write` + `v3 verify --fix`，
再核一遍并列出机器改不了的剩余项）。

文档里那些**由工具生成**的表格（174 张：doc 05 的 defines 表、doc 08 的目录统计表、
doc 19 的根目录与路径表、doc 03/04/05/06/10/11/14/15/16/17/18/20 那几族统计表）走另一条路：`v3 tables`
直接重算并逐行比对，不一致就退出码 1 —— 所以它们不可能过期，也不该手改。
「哪些表已经有人管」本身也有余额看守（`tests/test_inventory.py`：无人看守的
机械表只许减少，**现为 0**；散文数字那一面也是 0，剩下的每一个数字的「为什么不该由工具算」
都写在 `test_inventory.py` 的 `PROSE_NOT_COMPUTED` 里）。

### 实测

| 指标 | 值 |
|---|---|
| 测试 | **2882 条**用例（2026-10-10 当前工作区收集）；本轮回归见[语言与命名审计](docs/audits/2026-10-10-language-naming.md)，有日期的覆盖率和三平台 CI 结果见[维护记录](docs/audits/2026-10-10-repository-maintenance.md) |
| 测试文件 | **111 个测试文件**（`tests/test_*.py`） |
| 覆盖率 | 以 `v3 cov` 与 CI coverage artifact 的当前输出为准（门禁 86% 由 pyproject 强制 + 再按 11 个核心模块逐条设下限） |
| 性能测量 | 工具、测试和内存的独立测量见[速度执行记录](docs/audits/2026-10-10-speed-execution.md)，不同输入与环境的结果不作为受控提速对照 |
| 文件规模 | **3,964** 个 `.txt` / `.gui` 文件（`game\` 下 `.txt` 3,760 + `.gui` 204）+ **1,878** 个本地化 `.yml`；2026-10-10 由 `pdx.scan.walk_files` 核对，文件计数不等于运行期语义已验证 |
| 范围声明 | **不说「全量」** —— 当前安装中 138 个 `common\` 子目录进入文件分析，运行期枚举另有历史日志背书；「所有相关信息」没有边界、无法证伪。本仓库只声明**能回答哪些任务**，见 [`tools/README.md`](tools/README.md) 末尾的「已知边界」 |

## 目录结构

```
Situated AI/
├─ mod/                      生产产物（`decisions/fiscal.toml` 与 `extensions.toml` 生成）；`data/` → `legacy/` 仅为历史实验
├─ docs/design/              当前处境决策设计 + 历史方向依据 + `exec/` 实施与结果记录 + backlog
├─ docs/victoria3-modding/   20 篇主题文档 + 1 个索引
├─ docs/audits/              当前工程审计与历史测试快照
├─ research/
│   ├─ official-docs/        94 篇游戏自带官方 .md 的规范化镜像（**不入库**，用 `v3 mirror write` 重建）
│   └─ official-docs.manifest.json  镜像清单：路径 / 字节 / 行数 / sha256（**入库**，Paradox 版权内容不在其中）
├─ src/pdx/                  工具链核心包（解析部分纯标准库，cli.py 用 typer + rich）
├─ tests/                    测试（统一由仓库 `.venv` 的 pytest 执行）
├─ tools/
│   ├─ ci/ benchmarks/ probe/ prof/  开发检查、基准、探针与性能工具
│   └─ out/                  分析产物（已 gitignore）
├─ docs/reports/              人可读报告（**入库**）
├─ pyproject.toml            唯一配置源：依赖 / pytest / ruff / mypy / coverage
└─ README.md  LICENSE  .gitignore  .gitattributes
```

## 开发约定

工程底线集中维护在 [工程原则](docs/principles/工程原则.md)，产品行为底线集中维护在 [Mod 开发原则](docs/principles/Mod开发原则.md)。贡献、测试、性能、实机与中文 Git 提交的具体流程见 [CONTRIBUTING.md](CONTRIBUTING.md)；本页只提供总览，不复制原则正文。

文档事实区分【实测】、【官方】、【推断】和未确认，机械统计写明来源和口径。知识库对官方资料的交叉验证与工具已知边界见工具手册。

### 已知边界

工具链能回答「某个类型有哪些字段、取值什么形态、定义在哪个文件第几行」这类问题；
**不能**回答引擎运行期语义（加载顺序、覆盖优先级、字段合法性、平衡性）——
那些信息不在文件里。详见 [`tools/README.md`](tools/README.md) 末尾的「已知边界」。

## 工程与 Mod 状态

清理后完整工程回归见 [2026-10-10 过时内容清理](docs/audits/2026-10-10-stale-cleanup.md)。此前的分支覆盖率 88.79%、核心模块下限与三平台离线 CI 记录见 [仓库维护](docs/audits/2026-10-10-repository-maintenance.md)，这些测量属于各自记录的版本，不能当作本次重新测量。当前测试收集与机械统计由仓库测试持续核对。

工程底座继续复用，Mod 仍为实验实现：M1 接口观测与 M2 财政生命周期有证据，M3 行为/质量、M4 正式冻结候选的长期/后期验收尚未通过，政治与市场生产扩展仍关闭。最新条件、失败、阻塞与重开依据集中在 [当前工作清单](docs/design/当前工作清单.md)和 [M1–M5 结果索引](docs/design/exec/README.md)，执行顺序始终遵循 [最终执行纲领](docs/design/exec/mod重设计-实施计划.md)。

本次原则拆分和文档治理见 [2026-10-10 文档治理记录](docs/audits/2026-10-10-document-governance.md)，其他日期记录见 [工程审计索引](docs/audits/README.md)。工程通过不能替代 Mod 行为通过；Windows GUI 有实机证据，macOS/Linux 保持代码、CI 和无头验证口径。

## 授权

[Apache-2.0](LICENSE)

> `research/official-docs/` 是游戏自带官方 `.md` 的 UTF-8 无 BOM、LF 规范化镜像，属 Paradox 版权内容。
> 该目录**不纳入版本控制**（`.gitignore` 已忽略）：仓库里只有 `research/official-docs.manifest.json`，
> 记的是每篇的**路径 / 字节数 / 行数 / sha256**及规范化镜像指纹，不含正文。要在本机重建镜像用 `v3 mirror write --sync`，
> 核对清单与本机游戏、清单与本地镜像是否一致用 `v3 mirror check`。

### 知识库正文里也引用了官方原文（实测口径）

镜像移出之后**并不等于仓库里没有官方文本了** —— `docs/victoria3-modding/` 正文本身就在引用它。
这件事此前只被一句「语法片段引自游戏本体」含糊带过，比实测范围窄。实测（80 字符滑窗、
空白折叠后与 94 篇官方 `.md` 逐窗比对）：

| 项 | 数值 | 说明 |
|---|---:|---|
| 知识库正文总量 | 1,295,994 字符 | 全部 21 篇（20 篇主题文档 + 索引） |
| 逐字命中官方原文 | 45,259 个窗口（**3.58%**） | 约相当于官方 219,000 字符语料的 **20.7%** |
| ├ 代码块内 | 40,780 个（3.22%） | **PDX 语法骨架、字段名、示例模板** —— 与引用 API 签名同类 |
| └ 代码块外 | 4,479 个（**0.35%**，约 4.5K 字符） | 官方 `.md` 里的**英文注释原句**，作为字段语义的依据被引述 |

> 口径：把官方 94 篇 `.md` 与本知识库正文都折叠空白后，用 **80 字符滑窗**
> 逐窗比对（``test_quote_audit.py`` 每次重算并核对上表，容差见该文件）。
> ⚠️ 初版这组数**分母算错过**：只统计了含逐字命中的那 10 篇，于是占比被抬高到
> 4.51% / 0.39%。补上看守测试的第一次运行就把它抓出来了 —— 这正好说明
> 「一次性脚本算出来的数字」为什么不能留在文档里。

代码块那部分是本知识库的**主体价值**（mod 作者要的就是语法与字段表），抽掉等于把参考资料清空；
代码块外那 4.5K 字符是逐字引述的说明文字。**两者都在 Apache-2.0 的授权范围之外**，
若要再收紧，只能逐段改写成转述 —— 那会削弱字段语义的依据，也可能引入转述错误，
因此**没有做**，但把量级如实写在这里，供分发前自行评估。

> **历史核验**：`git log -- research/official-docs` 与 `git rev-list --objects --all` 均无该目录记录。官方镜像从未进入 Git 历史，因此无需重写历史；`.gitignore` 只负责阻止本机镜像进入当前索引。

---

文档中的语法片段与部分官方注释引自游戏本体，仅作技术说明用途，版权归 Paradox Interactive 所有。
