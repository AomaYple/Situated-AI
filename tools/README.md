# tools —— Python 工具链

Victoria 3 游戏本体与 mod 的信息处理工具链。核心解析与提取逻辑在 `pdx/` 包里，
**只用标准库**；命令行外壳用 typer + rich（表格与状态输出），
`--profile` 另需 pyinstrument。

> 早期版本用 PowerShell（10 个脚本）与 Node.js（2 个原型）实现，已全部退休。
> 退休原因见文末「为什么全 Python 化」。

## 环境与安装

```
.venv/                          Python 3.14 虚拟环境（已 gitignore）
.venv\Scripts\python.exe        解释器
.venv\Scripts\v3.exe            命令行入口（安装后生成）
```

```powershell
# 开发模式安装：装 pdx 包 + typer/rich + dev 依赖（pytest/ruff/mypy/pyinstrument）
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

> 注意：`powershell` 这个代码块标记只是**语法高亮**用；整条工具链本身
> 已不含任何 PowerShell 脚本，命令在 cmd / pwsh / bash 下都能跑
> （把 `.venv\Scripts\` 换成 `.venv/bin/` 即可）。

装好之后 `pdx` 可被任意目录下的 Python 导入（不再需要 `sys.path` 补丁），
并生成 `v3` 入口。**不装也能跑**：`python -m pdx.cli` 完全等价。

## 包结构 `pdx/`

| 模块 | 职责 |
|---|---|
| `model.py` | 数据模型：`Assignment` / `Block` / `Scalar` / `ParsedFile` |
| `lexer.py` | 词法：引号感知的注释剥离、运算符识别、行号追踪 |
| `parser.py` | 语法：递归下降，**花括号深度判定顶层**；`TOLERATED_ERRORS` 定义可容忍异常 |
| `cache.py` | 解析缓存，保证同一文件只解析一次 |
| `config.py` | 路径与常量，支持 `V3_ROOT` / `V3_USERDIR` / `V3_WORKSHOP` 覆盖 |
| `scan.py` | 文件系统扫描与统计 |
| `extract.py` | 目录级条目与字段提取 |
| `defines.py` | defines 专用提取（命名空间、参数形态、覆盖预览） |
| `mods.py` | Workshop 与本地 mod 分析 |
| `analyze.py` | 全量分析（游戏本体 / mod / 交叉，**分开存储**） |
| `snapshot.py` | 版本快照与两份快照的 diff |
| `verify.py` | 断言注册表，把文档里的数字变成可执行检查；产物核验与文档漂移扫描 |
| `doc_tables.py` | **通用**的「文档里由工具生成的 markdown 表」机制：整表替换 / 按键合并 / 同表头多张 |
| `docgen.py` | 生成表的**唯一登记处**：跑哪些文档、哪些表、怎么核对与写回 |
| `game_root.py` | 游戏根级文件、`paths.settings` 路径映射、校验和目标；产出 doc 19 的生成表 |
| `install_tree.py` | 安装树的逐目录统计（文件数 / 目录数 / 体积 / 扩展名分布）与版本指纹；产出 doc 08 的生成表，以及 doc 06 那三张「子目录 → 文件数」与扩展名分布表（同一棵树，口径共用） |
| `usage.py` | 「某目录里各键/字段用了多少次」的通用统计（**出现次数**与**文件数**两种口径）+ doc 04 / 14 / 16 那族表的规格 |
| `doc17.py` | doc 17（角色、科技与呈现）整族的机械表：**四种口径**（字段出现次数、逐文件定义数、取值分布、文本级统计）与那批两栏并排的分布表 |
| `doc15.py` | doc 15（政治人口与社会）的七张表：§0 的 25 目录总览、`laws` 前缀与字段、IG 门槛取值、`ideologies` 逐文件与五档态度、歧视特质四类分布 |
| `ai.py` | AI 侧的三张表：doc 03 的 `NAI` 参数前缀 Top25、doc 10 的字段**叠加语义**（判据是注释里的**整句措辞**，不是关键词 —— 按关键词数会差 2）与**值形态** |
| `doc16.py` | doc 16 剩下的 8 张表：`scope:` 记号、`flags`/`settings`/`ai.*` 的**文本级文件计数**、`subject_types` 字段、`contestion_type` 取值、`travel_network`（顶层 + 匿名块）；另记下两张**刻意不生成**的本机 mod 快照表 |
| `doc04.py` | doc 04（脚本系统）的 19 张表：`scripted_*` 字段与命名形态、`$PARAM$` 计数、JE 分组两栏、`events` 字段/`type`/`placement`、目录规模表（两列都是公式） |
| `modifiers.py` | `static_modifiers\` 的逐文件统计（条目数 / 单块最大键数）；产出 doc 05 §6.5 的生成表 |
| `docs_mirror.py` | 官方 `.md` 的**清单与指纹**（原文不入库，见下「官方文档清单」） |
| `localization.py` | 本地化专用提取（`.yml` 是行式格式，**不是** PDX 花括号语法）；产出 doc 06 的语言首行头统计，并记下那张**刻意不生成**的数据函数频次表（原口径复现不出） |
| `tabular.py` | 表格类数据（`.csv`），分隔符靠 `csv.Sniffer` 嗅探 |
| `engine_log.py` | 从游戏日志抽外部真值：枚举清单、脚本位置、token 位置 |
| `console.py` | stdout/stderr 的 UTF-8 兜底（**必须在构造 rich Console 之前调用**） |
| `cli.py` | 唯一的命令行入口，`v3` 的全部子命令 |

## 命令行 `v3`

7 个各自为政的旧入口脚本（`run_analyze.py` / `run_defines.py` / `run_index.py` /
`run_snapshot.py` / `run_verify.py` / `check_outputs.py` / `show_outputs.py`）
已删除，功能全部并入：

| 子命令 | 取代 | 作用 |
|---|---|---|
| `v3 analyze` | `run_analyze.py` | 全量分析并落盘：`--no-mods` `--no-cross` `--no-write` `--quiet` `--profile` |
| `v3 defines` | `run_defines.py` | defines 提取：`--ns NAME` `--json PATH` `--overlay FILE` |
| `v3 index` | `run_index.py` | 重生成 `docs/victoria3-modding/13-common全量键名索引.md`：`--dry-run` |
| `v3 tables` | （新增） | 重算文档里**由工具生成**的 169 张表格（doc 05 的 defines 表、doc 08 的目录统计表、doc 19 的根目录与 `paths.settings` 表、doc 03/04/05/06/07/09/10/11/14/15/16/17/18/20 那几族统计表）；不加 `--write` 时是核对，不一致即退出码 1。**要读游戏本体**，属本地门禁（CI 上以退出码 2 报前置条件缺失） |
| `v3 snapshot create/list/diff/verify` | `run_snapshot.py` | 版本快照：`--label` / `--compact`（精简，可入库） / `--detail` / `--json PATH` |
| `v3 verify` | `run_verify.py` | 核对文档里的 **234 条**数量断言**并扫描文档正文的数字漂移**：`--fast` `--only ID` `--no-drift` `--unregistered` `--from-snapshot`（无游戏时用**入库的离线真值**：精简快照 + 官方文档清单）**`--fix`（把带归属标记的数字改写成断言期望值）** |
| `v3 crosscheck` | （新增） | 用**游戏自己的日志**交叉验证解析：覆盖面、行号、token 识别 |
| `v3 check-outputs` | `check_outputs.py` | 核验**已落盘产物**是否与断言注册表一致 |
| `v3 show` | `show_outputs.py` | 转储产物的结构与规模 |
| `v3 mirror check` | （新增） | 官方 `.md` 清单 vs 本机本体 / 本地镜像，**只读**，有差异退出码 1 |
| `v3 strings` | （新增） | 开采 `victoria3.exe` 的字符串：引擎里有、脚本里没用的标识符（`--limit` / `--no-list`）。原先那两个数是没留口径的一次性采集值，现在可随时重算 |
| `v3 refresh` | （新增） | **游戏升级后的一条命令**：`tables --write` + `verify --fix`，再核一遍并列出机器改不了的剩余项（`--dry-run` 只报告）。跑完全绿说明没有任何需要人改的东西 |
| `v3 mirror write` | （新增） | 重生成清单（要游戏）；`--sync` 顺便把原文拷到本机 `research/official-docs/` |

```text
.venv\Scripts\v3.exe analyze                     # 全量分析，落盘报告
.venv\Scripts\v3.exe analyze --no-mods --quiet   # 只分析游戏本体，不打印进度
.venv\Scripts\v3.exe analyze --profile           # 附 pyinstrument 调用树
.venv\Scripts\v3.exe verify --fast               # 只跑不需要全库扫描的断言
.venv\Scripts\v3.exe verify --from-snapshot      # 不读游戏，用入库快照核验（CI 用）
.venv\Scripts\v3.exe verify --unregistered       # 列出文档里尚未登记的数量断言
.venv\Scripts\v3.exe mirror check                # 官方 .md 清单 vs 本体/本地镜像（只读）
.venv\Scripts\v3.exe mirror write --sync         # 重生成清单并把原文拷到本机（不入库）
.venv\Scripts\v3.exe tables                      # 核对生成表（不一致即退出 1）
.venv\Scripts\v3.exe tables --write              # 按生成结果修正文档里的表
.venv\Scripts\v3.exe check-outputs               # 核验产物（需先 analyze）
.venv\Scripts\v3.exe defines --ns NAI            # 展开某个 defines 命名空间
.venv\Scripts\v3.exe index --dry-run             # 只统计，不写文档
.venv\Scripts\v3.exe snapshot diff A B --detail  # 比对两份快照
.venv\Scripts\v3.exe show                        # 产物里到底有什么
.venv\Scripts\v3.exe <子命令> --help             # 每个子命令都有中文帮助
```

### 退出码

| 码 | 含义 |
|---:|---|
| 0 | 成功 |
| 1 | 检查未通过（`verify` / `check-outputs` / `snapshot verify` / `tables` / `mirror check`） |
| 2 | 用法错误，或前置条件缺失（游戏目录、产物、快照文件、清单不存在；`mirror check` 两条比对都没跑成） |

约定：**不存在「吞掉异常然后返回 0」的路径**。需要容错时只捕
`pdx.parser.TOLERATED_ERRORS` 这类精确异常集合，并且必须把失败原因打出来。

### 几个约定

* `--json` 在所有子命令里都表示**输出文件路径**（`Path`），不再是「写死的落点开关」。
* 相对路径一律相对仓库根显示；在仓库外运行会退回绝对路径，不会抛 `ValueError`。
* `add_completion=False`：工具链不往用户目录写补全脚本。

## 测试

```text
python -m pytest                    # 配置在 pyproject.toml 的 [tool.pytest.ini_options]
python -m pytest -m "not slow"      # 跳过慢用例
python -m pytest --cov=pdx          # 覆盖率（门槛 86%，见 pyproject）
```

589 条用例（`pytest --collect-only` 实测），
全部对应**实际踩过的坑**，不是凭空构造：

| 测试文件 | 覆盖的坑 |
|---|---|
| `test_lexer.py` | 注释内花括号、字符串中的 `#`、`?=` 不被拆开、行号追踪 |
| `test_parser.py` | BOM 污染首键、含连字符的键、`c:SWE` 不被误认为前缀、缩进的顶层键、`=` 与 `{` 分行 |
| `test_scan.py` | 递归计数、后缀过滤、真实游戏树的结构断言 |
| `test_extract.py` | 字段只收第一层、前缀归类、跨文件合并、已知条目数 |
| `test_analyze.py` / `test_golden.py` | 产物结构与指纹回归（产物被改坏要立刻失败） |
| `test_snapshot.py` / `test_verify.py` | 快照确定性、精简快照的结构等价性、断言注册表口径 |
| `test_defines_tables.py` | doc 05 那 5 张统计表的**生成链**：表头还在、生成是幂等的、文档现值 == 生成结果 |
| `test_doc17.py` | doc 17 那 24 张表的生成链，重点是**静默过期**：除「文档现值 == 生成结果」外，还断言**每一行都被某条 spec 认领**（键写错/取值消失时那张表看着完好、数字却已死）、分布表声明的取值集合没过期、概念键分类互斥完备、文件名模式划分完备。实测它抓出过「右栏键列写错 → 一整栏从未被写过」 |
| `test_doc_tables.py` | **通用的**生成表机制：合成文档测整表替换/按键合并/行数变长/同表头多张/合并行/绝不静默删行/未匹配行会出声；以及「别夺走作者信息」那一族（加粗键能匹配、值没变连排版一起留、已有空格不填待补、单元格括注与「N/M」分母保留、**合并行每段各自剥反引号**、**空格千位也算一个数字段**、**纯数字只换数字本身**）；登记表完整性；164 张表与文档一致 |
| `test_doc_misc.py` | 那几篇「只有一两张表」的文档（doc 03/10/11/12/14/18/20）共用的看守：文档 == 生成结果、每一行都有人认领，外加本篇恒等式 —— doc 03 的 Top25 真的是前 25、doc 10 的两套分类都加总到 60、doc 11 与 doc 18 说的是同一批数字、doc 14 的令牌与 doc 16 同源；以及四张**本机 mod** 表仍在文档里（排除清单不许失效） |
| `test_doc16.py` | doc 16 剩下八张表的生成链：两栏并排的 flags/settings 取值集合没过期、**文件数与出现次数是两个口径**（`can_be_renegotiated` 出现 27 次但只在 26 个文件里）、`travel_network` 的顶层键与匿名块字段都在、`subject_types` 的列名与口径一致（该目录只有 1 个文件，那一列只能是出现次数） |
| `test_doc04.py` | doc 04 的生成链，另守三处易错口径：`script_values` 的「顶层键」是**块**口径（块 270 / 赋值 479）、`$PARAM$` **不数注释里的用法**、JE 分组两栏声明的取值集合没过期；以及「`placement` 六类分得掉全部取值」「事件字段表覆盖全部 26 个字段」 |
| `test_doc06.py` / `test_doc15.py` | doc 06 / 15 的生成链。除共用的两条（文档 == 生成结果、每一行都有人认领）外各守住本篇特有的恒等式：doc 06 的「语言表合计 == 全树 `.yml` 数」「三张目录表行数 == 子目录数」「扩展名表的每段都还在树里」；doc 15 的「`laws` 前缀划分完备」「§0 目录清单与代码一致」「五档态度合计 == 散文里的合计」「118 + 196 + 10 == 目录定义数（前两行是总数与子集，不是互斥分组）」 |
| `_table_guards.py` | 三个文档共用的生成表看守：`assert_doc_matches_generated` / `assert_every_row_claimed` / `assert_write_free_and_idempotent` / `assert_unique_names` |
| `test_repo_hygiene.py` | 源文件不带 CRLF —— Windows 上 `write_text` 漏了 `newline="\n"` 会把整份文件重写成 CRLF，而 `.gitattributes` 的 `eol=lf` 把 `git status` 掩盖成「干净」 |
| `test_properties.py` / `test_metamorphic.py` / `test_lexer_differential.py` | hypothesis 属性测试、变形测试、与独立 oracle 实现的差分对比 |
| `test_benchmarks.py` | 性能基准（`pytest-benchmark`，回归即失败） |
| `test_cli.py` | CLI 端到端：参数解析、退出码、入口点可用性、GBK 控制台不崩 |
| `test_cache.py` | 缓存透明性：`parse_cached` 必须恒等于 `parse_file` |
| `test_coverage.py` | **覆盖面契约**：每个文件必须归入四类之一，落不进就失败 |
| `test_conftest.py` | 「没有游戏就自动跳过集成用例」这条机制本身（子进程真跑一次收集） |
| `test_data_dump.py` | 结构化转储：必须能取到**值**而不只是字段名 |
| `test_defines.py` | defines 提取：参数形态、命名空间合并、覆盖预览 |
| `test_docs_consistency.py` | 文档数字与断言表的一致性（防文档过期）；**修订哈希与本体比对**、**逐行核对文档里声明的文件字节数**（都是数字漂移扫描抓不到的角度） |
| `test_doc_overview.py` | doc 16/17 两张 §0 总览表（62 行的机械量）：逐行核对 `.txt` / 字节 / 键数，并断言头条声明与表格合计同源。口径按文档自己声明的（字节只算 `.txt`；键数按顶层**块**的出现次数，不是去重后的键名数） |
| `test_inventory.py` | **全仓机械数字的欠债余额**：统计「含统计量列、无人看守」的表与「无人看守的散文数字」，**只许减少**；附元测试保证盘点真的在数东西（不是恒为 0） |
| `test_quote_audit.py` | 重算 README 授权节那组「正文逐字引用官方原文」的实测数并比对 —— 它第一次运行就抓到 README 的分母算错（只统计了有命中的 10 篇，于是占比被抬高） |
| `test_docs_mirror.py` | 官方 `.md` 清单的时效性：篇目集合、**逐篇 sha256**、镜像无多余文件；以及「跑不了的比对不该弄脏退出码」这条门禁语义 |
| `test_localization.py` | `.yml` 本地化：语言覆盖、键去重、BOM 处理 |
| `test_engine_crosscheck.py` | 用游戏日志当**外部真值**核对解析 |

### 跑基准要加 `-n0`

`pytest-benchmark` 在 xdist 开启时会**自动禁用自己**，而本项目默认并行
（`-n auto`）。因此不带 `-n0` 时基准会被静默跳过 —— 实测踩过：

```text
python -m pytest tools/tests/test_benchmarks.py --benchmark-only -n0
```

## 输出产物

**分开存放** —— 游戏本体与 mod 互不混杂：

```
tools/out/game/游戏本体.json      统计口径：条目、字段、使用频次（约 8.2 MB）
tools/out/game/游戏数据.json      内容口径：字段、值、嵌套结构、行号与注释（约 54 MB）
tools/out/game/本地化.json        14.5 万个本地化键（约 6.1 MB）
tools/out/game/表格数据.json      adjacencies.csv 等表格类数据
tools/out/mods/mod.json          mod 全量数据（约 640 KB）
tools/out/cross/交叉.json         两者的覆盖关系
tools/reports/游戏本体分析.md      人可读报告
tools/reports/mod分析.md          人可读报告
```

上面 8 项由 `v3 analyze` **一次**产出（也就是黄金回归冻结的那 8 份）。

另有**独立**的一条线：

```
tools/out/snapshots/<版本>.compact.json   精简快照，约 4.9 MiB（**入库**，跨机器可 diff）
tools/out/snapshots/<版本>.json           完整快照，约 39 MiB（gitignore，本机深挖用）
```

> 上面的 MB / KB 按 1024 进制。精确值由黄金回归（`tools/tests/test_golden.py`）
> 冻结为逐产物的「字节数 + sha256」，改动一个字节就会失败。
>
> ⚠️ **快照分两种，只有精简版入库**：完整快照 73% 的体积是本地化键清单
> （11 种语言 × 14.5 万键），而「Paradox 增删了哪些字段与条目」只需要结构域。
> 精简版保留 `common_entries` / `fields` / `defines` / `dlc` / `config` 五个域，
> 只把 `localization` 换成「键数 + sha256」，因此 **不到 5 MiB 就能随仓库分发**，
> 让 `v3 snapshot diff` 在别人的克隆里也能跑。
> 想知道**具体**改了哪些本地化键，才需要那份约 39 MiB 的完整快照。
>
> 两者**形状相同**，`compare` 对谁都能用；但**别拿精简版与完整版对 diff** ——
> 那会把整个本地化域报成「全删 + 全增」。文件里有 `精简` 标记，可据此判断。

`tools/out/` 已 gitignore（随时可由 `v3 analyze` 重建）；
`tools/reports/` **入库** —— 两份报告是研究成果的一部分，改动它们应当出现在 diff 里。

## 官方文档清单

`research/official-docs.manifest.json`（约 17 KB，**入库**）记着游戏自带 **92 篇**官方 `.md` 的
路径 / 字节数 / 行数 / sha256，外加生成时的游戏版本。原文本身**不入库**。

**为什么原文不入库**：那 230 KB 是 Paradox 的版权内容，而本仓库是 Apache-2.0 公开仓库。
镜像本来只有两条用途，其中真正被用的是第一条：

| 用途 | 现在由谁承载 |
|---|---|
| 检测「Paradox 改了官方文档」 | **清单**（文件名、字节数、sha256 都是事实，不是创作内容） |
| 让没有游戏的人也能读原文 | 知识库正文本身（重点已转述，并标注了原文缺陷） |

**换掉镜像反而更强**：以前只有「镜像 vs 本体」一条路，只有手里有镜像才能查；
现在拿入库的清单比对本机本体即可，**任意克隆都能查**（`v3 mirror check`）。

> **为什么需要它**：真实踩过一次 —— `treaty_articles.md` 的镜像停在 1.14.2
> （25,364 B / 604 行），而 1.14.3 本体已增至 28,171 B / 648 行（新增
> `scope:other_country`、`requirement_to_maintain` 等规则）。**照旧镜像写条约 mod 会漏掉这些规则**，
> 而当时没有任何断言会响。`test_docs_mirror.py` 现在守着这条。

> ⚠️ **诚实说明**：`git rm --cached` 只能把原文从**当前树**移除，那 92 篇仍在仓库历史里。
> 要彻底清除需重写历史（`git filter-repo`），属单独决定，本次没做 —— 所以 README 的「授权」
> 一节保留了这条说明，而不是假装版权问题已经解决。

`v3 mirror check` 的两条比对**各自独立跳过**：没有游戏就跳过「清单 vs 本体」，
没有本地镜像就跳过「清单 vs 镜像」。**跳过不算失败**（旧实现里跳过只是不打印，
那 92 条「删除」照样进了退出码判断，于是没装游戏的机器上这个门禁永远是红的）；
但两条都跑不成时退出码 2 —— 免得空过。

## 解析器的五条铁律

这些是踩坑换来的，改代码时不要违反：

```
1. 用花括号深度判断顶层        —— 官方文件混用 tab / 空格 / 无缩进
2. 剥离 BOM                    —— common 下 3,026 个 .txt 有 3,002 个带 BOM
3. 注释剥离要引号感知          —— 字符串里可能含 #
4. 键名字符集用「非空白非等号」  —— 存在含连字符的键（全库 32 个）
5. 识别 6 个功能前缀           —— INJECT: / REPLACE: 等，且**只 mod 用**
```

另有两条口径纪律，都曾导致过真实错误：

* **`@变量` 不是数据条目** —— `00_defines.txt` 顶部 22 个，误计会让命名空间块数从 75 变成 97
* **空目录也要收录** —— `scripted_modifiers` 只有 `.md` 没有 `.txt`，靠「有没有 `.txt`」数目录会得到 135 而非 136

## 性能剖析 `prof/`

`pdx` 包本身不埋点，剖析用独立脚本跑：

```text
.venv\Scripts\python.exe tools/prof/prof_e2e.py full          # 整条流水线（冷缓存）+ 调用树
.venv\Scripts\python.exe tools/prof/prof_e2e.py stages        # 逐阶段冷缓存剖析
.venv\Scripts\python.exe tools/prof/prof_e2e.py walkaudit     # 文件系统被重复遍历的程度
.venv\Scripts\python.exe tools/prof/prof_e2e.py prefixaudit   # 功能前缀扫描的范围与耗时
```

阶段序列与 `v3 analyze` 保持一致，因此剖析结果可以直接用来解释 `analyze` 的耗时。

> ⚠️ **`full` / `stages` / `walkaudit` 会重跑整条分析流水线，覆盖已入库的
> `tools/reports/*.md` 与 `tools/out/**`。** 它们不是只读命令：
> 跑完 `git status` 会脏。产物应当逐字节相同（黄金回归冻结了 sha256），
> 若真变了就说明有非确定性 bug —— 这反而是个有用的信号。
> 只有 `prefixaudit` 是纯读的。

## 控制台编码

中文 Windows 的控制台是 GBK 代码页，`print("✅")` 会抛 `UnicodeEncodeError`
—— **重定向到管道时同样会抛**。入口处统一调 `pdx.console.enable_utf8_stdio()`。

`rich` 替代不了它：实测三种写法（`print(..., file=gbk 流)`、
`Console(file=gbk 流)`、`Console(..., legacy_windows=False)`）**全部**抛。

## 已知边界

### 为什么不再自称「全量」

「全量解析」这个说法只在**文件维度**成立，而且是可证伪的：136 个 `common\`
子目录逐文件覆盖、每类文件归属由测试强制、并由引擎日志的 `pre-enumerating`
清单外部背书（72 个枚举组合覆盖 71，零缺口）。

但**信息维度**的「所有与 mod 开发相关的信息」没有边界，因此无法证伪 ——
它既不能被完成，也不能被证明完成。继续用「全量」会让读者把
「没被提取到」误当成「不存在」。

所以本仓库改为只声明**能回答哪些任务**：

| 能回答（有实测依据） | 例子 |
|---|---|
| 某类条目有哪些字段、取值什么形态 | 建筑 41 个字段及取值样例 |
| 某条目定义在哪个文件第几行 | `on_actions` 264 个键各自的 `文件:行号` |
| 某个键存不存在、被引用几次 | 本地化键存在性与语言覆盖；AI 策略字段的引用点 |
| 某个目录有哪些条目 | 136 个目录的顶层键名全索引 |
| **两个版本之间，Paradox 增删了什么** | `v3 snapshot diff`（结构域逐项比对） |
| **官方 `.md` 有没有被 Paradox 改过** | `v3 mirror check`（清单 vs 本机本体，逐篇 sha256） |

**不能**回答 —— 信息不在文件里，不是功能没做：

| 答不了的问题 | 为什么 |
|---|---|
| 两个 mod 改同一条目谁生效 | 取决于运行期加载顺序，脚本里没有 |
| 某字段的合法取值范围 | 只有引擎知道；二进制里有候选词表但**尚未开采** |
| 同名条目里哪个最终生效 | 引擎的合并规则，未知 |
| 平衡性与 AI 实际表现 | 要跑游戏才知道 |

> 上表第二行标了「尚未开采」而不是「做不到」：`victoria3.exe` 里有
> **55,143 个标识符形状的串**，其中 **31,334 个从未在 `.txt` / `.gui` / `.yml` 里出现**
> （`v3 strings` 现算，口径见 `pdx.exe_strings`）—— 那批词很可能包含字段枚举与合法取值。
> 这是已知范围内最值得做的下一步。
>
> 早先这里写的是 17,821 / 16,535：那是一次性采集值，**口径没留、脚本没留**，
> 与 doc 04 §4.6 那个「682 行」同病。现在这两个数由 `v3 strings` 从 exe 现算，
> `tools/tests/test_repo_numbers.py` 会核对它们没被改错。

## 为什么全 Python 化

| 原因 | 具体表现 |
|---|---|
| PowerShell 5.1 的编码陷阱 | 不加 `-Encoding utf8` 按 GBK 解码；`Set-Content -Encoding UTF8` 写 BOM |
| PowerShell 的反引号转义 | 字符串里写 Markdown 代码块会报语法错误（开发中触发多次） |
| 缺少数据结构 | 解析结果只能用 PSCustomObject 拼，不如 dataclass 清晰 |
| 无法写正经测试 | PowerShell 没有 `pytest` 那样的测试框架 |
| Node 需要额外运行时 | 而 Python 的 `utf-8-sig` 编码名天然解决 BOM 问题 |

Python 版把上述问题都变成了**可测试的代码**：589 条用例 + 234 条断言核验
（`v3 verify`，其中 `--fast` 跑不需要全库扫描的 211 条），
外加一层**外部验证** —— `v3 crosscheck` 拿游戏自己的日志核对我们的解析。

> `v3 verify` 同时跑**文档正文的数字漂移扫描**（`verify.unknown_doc_drift`）：
> 断言表测对了不等于文档写对了 —— 正文里可能仍躺着旧值，而断言表照样全绿。
> 有漂移时退出码同样是 1，所以在 CI / pre-commit 上也会被拦住。
> 确认是「口径不同、文档没错」的登记在 `pdx.verify.KNOWN_METRIC_MIXUPS`（附理由）。
>
> **没有游戏的机器（CI）怎么办**：234 条断言里 43 条能用**入库的离线真值**核验
> （精简快照 36 条 + 官方文档清单 4 条），其余 191 条要读游戏本体，而入库的
> **精简快照**里带着各目录条目名、defines 命名空间与 DLC 清单，
> 够核验其中约一半 —— 跑 `v3 verify --from-snapshot` 即可，它**不读游戏**。
> 它证明「断言注册表仍与当时记录的真值一致」，不证明「游戏里现在是这个数」；
> 两者合起来才完整，所以 CI 上跑前者、本地跑后者。
