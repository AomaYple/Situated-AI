# Situated AI

Victoria 3 的 AI 相关 mod 开发项目。

> **当前状态**：仓库内有两部分 —— 一套 **21 篇的 mod 开发知识库**，以及一套
> **可复现其中全部统计数据的 Python 工具链**。**尚未开始写 mod 本体**
> （本地 mod 目录 `Documents\Paradox Interactive\Victoria 3\mod\` 仍为空）。

## 环境

| 项目 | 值 |
|---|---|
| 游戏 | Victoria 3 **1.14.3 (Ice Tea)** |
| Clausewitz | `caligula/release/1.14.x` |
| Steam App ID | `529340` |
| Python | 3.11+（本机 3.14） |
| 平台 | Steam / Windows |

> ⚠️ **版本跨度**：知识库多数主题文档的统计与「零使用」类结论**采集于 1.14.2**，
> 而游戏已升级到 1.14.3，这些结论尚未逐条重测。已核验的数字见 `v3 verify`
> （断言表已更新到 1.14.3），文档与断言表的一致性由测试持续看守。

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
  覆盖，官方 92 篇文档**零记载**，原版一处不用，但 23 个 mod 用了 **2,737** 次
- **联机校验和只覆盖 5 个目录**（`common/ events/ map_data/ gui/ localization/`）
- **不需要 `descriptor.mod`** —— 现代格式是 `.metadata\metadata.json`
- **调试模式**：启动参数加 `-debug_mode`，错误看 `logs\error.log`、
  覆盖冲突看 `logs\database_conflicts.log`、AI 看 `logs\ai.log`

## 工具链

[`tools/`](tools/) —— Python 实现的 PDX 脚本解析与信息提取工具链。
**它不说自己「全量」**：文件维度确实逐文件覆盖（可证伪，有引擎日志背书），
但「所有与 mod 开发相关的信息」没有边界。仓库只声明**能回答哪些任务** ——
见 [`tools/README.md`](tools/README.md) 末尾的「已知边界」。

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"   # 一次性安装
.venv\Scripts\v3.exe analyze --quiet                  # 全量分析并落盘（约 28 秒）
.venv\Scripts\v3.exe verify --fast                    # 核对文档里的数量断言
.venv\Scripts\v3.exe crosscheck                       # 用游戏日志交叉验证解析正确性
```

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

另有一条**独立**的版本快照线（`v3 snapshot create`）：捕获某个版本的全部
mod 相关信息，游戏升级后 `v3 snapshot diff` 一次就能看出 Paradox 增删了哪些字段。

| 形态 | 命令 | 体积 | 是否入库 |
|---|---|---:|---|
| 完整快照 | `v3 snapshot create` | 约 39 MiB | 否（本机深挖用，含 14.5 万条本地化键） |
| **精简快照** | `v3 snapshot create --compact` | 约 4.9 MiB | **是** —— 只留结构域，本地化换成「键数 + sha256」 |

精简快照入库的意义：**跨版本 diff 在别人的机器上也能做**，而不只是本机。

### 它验证自己吗

是，而且分三层：

| 层 | 机制 |
|---|---|
| 覆盖面 | 每个文件必须归入四类之一，由测试强制；并由**引擎日志**外部背书 |
| 转录正确性 | 与引擎日志里报告的 `文件:行号` 逐条比对（token 行号 100% 一致） |
| 产物不变性 | 黄金回归冻结全部产物的 sha256，改一个字节即失败 |

63 条数量断言分两处核验：本地跑 `v3 verify`（真值来自游戏本体），
CI 跑 `v3 verify --from-snapshot`（真值来自**入库的精简快照**，覆盖其中约一半）。
两条路径共用同一份断言注册表与同一个漂移扫描，不会出现「测试过了但工具没发现」。

### 实测

| 指标 | 值 |
|---|---|
| 测试 | **457 条**用例（454 通过 / 3 按条件跳过） |
| 覆盖率 | **87.7%**（门禁 86%） |
| 端到端 | 约 28 秒 |
| 解析规模 | 6,250 个 PDX 文件 + 1,877 个本地化文件 |
| 范围声明 | **不说「全量」** —— 文件维度可证伪（136 个 `common\` 子目录逐文件覆盖，有引擎日志背书），但「所有相关信息」没有边界、无法证伪。本仓库只声明**能回答哪些任务**，见 [`tools/README.md`](tools/README.md) 末尾的「已知边界」 |

## 目录结构

```
Situated AI/
├─ docs/victoria3-modding/   21 篇 mod 开发知识库
├─ docs/audits/              测试套件审计报告（重构前的历史快照）
├─ research/official-docs/   92 篇游戏自带官方 .md 的逐字镜像（Paradox 版权，见「授权」）
├─ tools/
│   ├─ pdx/                  工具链核心包（17 个模块；解析部分纯标准库，cli.py 用 typer + rich）
│   ├─ tests/                测试（24 个测试文件 / 457 条用例）
│   ├─ prof/                 性能剖析
│   ├─ out/                  分析产物（已 gitignore）
│   └─ reports/              人可读报告（**入库**）
├─ pyproject.toml            唯一配置源：依赖 / pytest / ruff / mypy / coverage
└─ README.md  LICENSE  .gitignore  .gitattributes
```

## 开发约定

| 约定 | 说明 |
|---|---|
| **提交信息用中文** | 不加 `feat:` / `fix:` / `chore:` 等英文前缀 |
| **信息分级标注** | 文档中的每条事实都标来源：**【实测】** / **【官方】** / **【推断】** / 未确认 |
| **统计必须写口径** | 按「顶层键」或「含嵌套块」会得出不同数字，引用时写明规则 |
| **官方文档需交叉验证** | 游戏自带 92 篇 `.md` 有多处字段名错误与遗漏，写 mod 前先对照实测 |
| **能用库就不自己写** | 解析用标准库、CLI 用 typer、测试用 pytest 全家桶；不重造已有轮子 |
| **正确性第一** | 优先保证与源文件一致，性能优化必须在有测试护航的前提下做 |
| **自动看守** | `.github/workflows/ci.yml` 在每次 push/PR 上跑 ruff + mypy + 不依赖游戏的用例；`.pre-commit-config.yaml` 在提交前跑同一套 |

### 已知边界

工具链能回答「某个类型有哪些字段、取值什么形态、定义在哪个文件第几行」这类问题；
**不能**回答引擎运行期语义（加载顺序、覆盖优先级、字段合法性、平衡性）——
那些信息不在文件里。详见 [`tools/README.md`](tools/README.md) 末尾。

## 授权

[Apache-2.0](LICENSE)

> `research/official-docs/` 是游戏自带官方 `.md` 的**逐字镜像**，属 Paradox 版权内容。
> 仓库以 Apache-2.0 授权，但该目录不在此授权范围内 —— 公开分发前请自行评估。

---

文档中的语法片段引自游戏本体，仅作技术说明用途。
