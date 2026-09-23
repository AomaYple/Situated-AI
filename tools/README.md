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
| `citations.py` | **数据源里 `文件:行号` 引用的机械核对**（P10 从纪律变成可执行检查）：把 `why` 里的 `00_code_static_modifiers.txt:322` 这类引用逐条解析到原版真实文件，报 `missing`（文件名写错 / 少了 `common/` 前缀）/ `ambiguous`（同名文件几十个，等于没指）/ `out_of_range`（文件只有 300 行却引了 `:322`）。⚠️ 它**不做语义判断** —— "那一行真的支持这条 why 吗"仍要人看，它只保证"引用存在且唯一"。上线当天就抓出既有档案里 5 处指不到文件的引用与一条错的事实断言（见 `exec/阶段5-批次1-结果.md` §四）。**`--offline`（B77）**：精简快照里的 `citation_support` 域记着每条引用的**文件行数 + 被引那一行的文本指纹**，于是这条纪律在**没有游戏的机器（CI）**上也守得住；有游戏时它还顺手核「被引那一行**还是不是那句话**」—— 那正是官方更新挪走我们依据的信号。**行号漂移会自动找回**（`relocate`）：报"内容变了"之前先按指纹在同一文件里找那一行现在在哪，直接给新行号 —— 编辑被大量引用的文件（`backlog.md`、`ab_probe.py`）时行号整体平移，而"内容变了（原版更新？）"那句话会把人引到错的方向；若入库记的那一行本身是**空行**，它会改口说"这条引用本来就指错了"。入口 `v3 citations [--offline]` |
| `release.py` | **发布流程的机械部分**（阶段 7 的最后一件）：`CHANGELOG.md` ↔ 档案 ↔ 元数据三边一致。它原来只有一条人工纪律（「档案 id 必须出现在 changelog 条目里」），而 §1 说过**没有检查方式的原则不算原则** —— 现在版本 / 覆盖 / 幽灵 / 归档物四个面都是机器可查的。**为什么发布说明不整份生成**：它是散文、是作者的判断；P9 要集中的是阈值/权重/文案这类**事实**，所以分工是「结构由机器守、散文由人写」。入口 `v3 release [--template]` |
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
| `modgen.py` | **数据源 → mod 产物**的生成器（阶段 3）：把 `mod/data/*.toml` 编译成脚本 + 本地化 + 档案文档。每个数字必须带 `why`，空 `why` 当场报错；产物一律由它生成，**不许手写**。可选表：`[reform_inputs]` 生成"第二处理段"（第二个效果 + 第二个修正，A/B 阶梯的 B2 臂靠它）；`[panel]`（P11 三行）生成三个解释键并**接进 JE 说明**（引擎显示的是 `journal_entry.gui:742` 的 `GetReason`）；`[difficulty]`（契约 J5，**mod 级**）生成 `common/game_rules/` 三档规则 + 玩家侧修正，并把"按档位给玩家加/减"接进冲击效果（机制只用原版有先例的 `flag` + `has_game_rule`，不用零先例的 `apply_modifier`） |
| `modguard.py` | **五道闸门**（阶段 3）：键/路径与原版不相交、引用完整性、稀释预算（按阶段 2 的三槽价格表）、往返净度、生成可复现 + `why` 非空。引用类别含 `modifier_field`（修正字段名必须在原版 `static_modifiers` 里出现过 —— 让 P10 的「数值引原版同类用法」可机器核对） |
| `ab_probe.py` | 阶段 3 的 **A/B 臂阶梯探针**生成器：点一次决议武装，之后按月度脉冲自动换臂（`A` 第 1–12 月 → `B` 第 13 月施加冲击 → `B2` 第 37 月追加改革侧输入；幂等靠 `stage` 变量）。同时生成 `tools/scripted_tests/` 套件（引擎每天判「是否开窗 / 是否换法」）与原版套件的收敛覆盖 |
| `ab.py` | 阶段 3 的 A/B 分析器：解析探针月度行 → **两处处理分开报**（① 行为层 / ② 策略层是冲击步 A→B，③ 是改革侧输入步 B→B2）→ 判定。含开局自检（RUN / 玩家 / 观测 / 角色 / SHOCK / INPUT / 报错）、合法性五档诊断；`VERDICT_MIN_MONTHS = 12` 卡住"样本不足就宣判" |
| `ab_auto.py` | 阶段 3 的**自动实验编排**（状态机，自己不碰游戏）：断言 0 个游戏进程 → 启动 → 轮询探针月度行判进度 → 到点杀进程 → 归档 → 分析 → 追加进 `exec/阶段3-实验记录.md` → 下一臂。启动/杀进程由 `Ports` 注入（**设计上**没接上就当场报错、不静默跳过；**当前默认端口是空的** —— 见 `v3 ab-auto` 那一行的"尚不可用"说明） |
| `game_auto.py` | 阶段 3 的**游戏自动化原语**（窗口级截图 + 图像匹配 + 点击 + 真实键盘 + **游戏内控制台** + 日志真值，见 `exec/自动化范式.md`）：官方 `-scripted_tests` 已经把「开局 → 存读档 → 进 idler」做完了，本模块只补**最后一击**（强激活前台 → 点「观察」→ 取消暂停 → 切后台验证 tick 仍在走）。**控制台那一层是阶段 4 性能仪表的唯一入口**（`console_open` / `open_console` / `submit_console_command`：反引号开、敲完**按两次回车**才提交，判据走画面 ROI）—— 为什么必须收在这里、以及三条实测结论见 `exec/阶段4-性能仪表侦察.md` §四·补② 与 backlog B66。入口是 `python -m pdx.game_auto`（**不挂 `v3` 子命令**，理由见命令表那一行） |
| `stress_probe.py` | 阶段 4 ④ 的**标准压力剧本**（大战 + 连锁破产 + 革命潮），生成一份探针 mod：**三条压力都用原版自己的效果造**（`create_diplomatic_play` / `add_radicals_in_state` / `add_treasury = -200000`），不伪造状态 —— 伪造的状态不让引擎干活，也就压不出负载。⚠️ **破产不是我们写上去的**：原版没有那个效果（`DECLARE_BANKRUPTCY_MIN_DAYS_IN_DEFAULT = 30`，`common/defines/00_ai.txt:52`），我们只把国库抽干、引擎自己走完最后一步。跑法见 `tools/probe/perf_compare.py --stress`（**两臂都装它** —— 单装一臂等于把"世界被推到高压"算进那一臂的差里） |
| `gametimer.py` | 阶段 4 的**引擎计时刻度解析**（两条数据源）：① `gametimer_*.tsv` 是引擎自己的墙钟统计（三列 `Game Date / Time Unit / Seconds`，粒度只到 `Day` —— **没有帧号、没有 per-frame 列**，所以「单帧 ≤0.5ms」这条预算**量不出来**，模块里用 `FRAME_GRANULARITY_AVAILABLE = False` 把这件事写成机器可读的常量，不让下游顺手凑数）；② **`ticktask_timings.csv`** 是帧级真值（`frame,task,milliseconds,calls,longest_lock`，由控制台 `dump_ticktask_timings` 落盘，默认落点见 `ticktask_default_path()`）。配套侦察记录见 `exec/阶段4-gametimer侦察.md` 与 `exec/阶段4-性能仪表侦察.md` |
| `cli.py` | 唯一的命令行入口，`v3` 的全部子命令 |

`tools/probe/` 下是**一次性但仍在用**的实测脚本（不挂 `v3` 子命令，因为都要开游戏或要人看着跑）：
`perf_compare.py`（性能 A/B，`--stress` 换标准压力剧本）、`stage3_rerun.py`（档案探针 A/B 重跑）、
`console_probe.py`、`flow_with_cleanup.py`、`measure_capture_cost.py`、`perf_mod.py`，
以及 `audit_repo.py` —— **那五条口径的可执行清单**（Python 化 / 成熟库 / 测试与覆盖 / 性能基准 / 默认并行），
只读仓库、不读游戏，收口时跑一次就知道还差什么。

## 命令行 `v3`

7 个各自为政的旧入口脚本（`run_analyze.py` / `run_defines.py` / `run_index.py` /
`run_snapshot.py` / `run_verify.py` / `check_outputs.py` / `show_outputs.py`）
已删除，功能全部并入：

| 子命令 | 取代 | 作用 |
|---|---|---|
| `v3 analyze` | `run_analyze.py` | 全量分析并落盘：`--no-mods` `--no-cross` `--no-write` `--quiet` `--profile` |
| `v3 defines` | `run_defines.py` | defines 提取：`--ns NAME` `--json PATH` `--overlay FILE` |
| `v3 index` | `run_index.py` | 重生成 `docs/victoria3-modding/13-common全量键名索引.md`：`--dry-run` |
| `v3 tables` | （新增） | 重算文档里**由工具生成**的 171 张表格（doc 05 的 defines 表、doc 08 的目录统计表、doc 19 的根目录与 `paths.settings` 表、doc 03/04/05/06/07/09/10/11/14/15/16/17/18/20 那几族统计表）；不加 `--write` 时是核对，不一致即退出码 1。**要读游戏本体**，属本地门禁（CI 上以退出码 2 报前置条件缺失） |
| `v3 snapshot create/list/diff/verify` | `run_snapshot.py` | 版本快照：`--label` / `--compact`（精简，可入库） / `--detail` / `--json PATH` |
| `v3 verify` | `run_verify.py` | 核对文档里的 **234 条**数量断言**并扫描文档正文的数字漂移**：`--fast` `--only ID` `--no-drift` `--unregistered` `--from-snapshot`（无游戏时用**入库的离线真值**：精简快照 + 官方文档清单）**`--fix`（把带归属标记的数字改写成断言期望值）** |
| `v3 crosscheck` | （新增） | 用**游戏自己的日志**交叉验证解析：覆盖面、行号、token 识别 |
| `v3 check-outputs` | `check_outputs.py` | 核验**已落盘产物**是否与断言注册表一致 |
| `v3 show` | `show_outputs.py` | 转储产物的结构与规模 |
| `v3 mirror check` | （新增） | 官方 `.md` 清单 vs 本机本体 / 本地镜像，**只读**，有差异退出码 1 |
| `v3 strings` | （新增） | 开采 `victoria3.exe` 的字符串：引擎里有、脚本里没用的标识符（`--limit` / `--no-list`）。原先那两个数是没留口径的一次性采集值，现在可随时重算 |
| `v3 release` | （新增，阶段 7） | **发布说明 ↔ 档案 ↔ 元数据三边一致**：① 最新一节版本 == 元数据的 `version`；② `mod/data` 里每份档案都以条目形式写进了 `CHANGELOG.md`；③ 没有"幽灵条目"（删了档案却留着说明）；④ 各档案声明的 `game_version` == 元数据的 `supported_game_version`。**不读游戏**，已进 CI。`--template` 打印缺的条目骨架（只打印：那句话得人来说） |
| `v3 refresh` | （新增） | **游戏升级后的一条命令**：`tables --write` + `verify --fix`，再核一遍并列出机器改不了的剩余项（`--dry-run` 只报告）。跑完全绿说明没有任何需要人改的东西 |
| `v3 mirror write` | （新增） | 重生成清单（要游戏）；`--sync` 顺便把原文拷到本机 `research/official-docs/` |
| `v3 tables --offline` | （新增） | **不读游戏**核对那张表的另一条路：快照里记着每张生成表当时的数据行，这条只比文档与快照（CI 用；`--write` 可按快照恢复）。它证明「表与入库快照一致」，不证明「表与现在的游戏一致」 |
| `v3 evidence` | （新增） | 查一个键名的**四类证据**：原版用法（键与值分开统计，注释不算用法）/ 官方 md 命中 / 本机 mod 用法 / `victoria3.exe` 字面量与邻居。`--exe-grep` 查一族名字，`--dir` 收窄到某目录，`--values` 列取值分布 |
| `v3 unverified` | （新增） | 列出文档里全部 **【未确认】** 项（可 `-d 04` 只看一篇）—— 把「还剩多少没验证」从记忆变成可数的事实 |
| `v3 prefixes` | （新增） | 本机 mod 的**功能前缀按目录**用量：doc 04 §1 那张「能否覆盖同名键」的表就是拿它作证的（本机快照，不是版本属性） |
| `v3 cache` | （新增） | 解析缓存的状态与清理。全量任务要解析 6 千个文件，内存缓存只管进程内，**跨进程靠磁盘层**（`--clear` 清空，键含 mtime 与解析器指纹） |
| `v3 cov` | （新增） | 覆盖率门禁：整体 86% 之外再按**核心模块**逐条核对下限（`--check-only` 只读上次数据）。整体数字会掩盖「大模块退化、小模块补测」 |
| `v3 lock` | （新增） | 依赖锁：展开本机已安装的依赖闭包与 `requirements.lock` 对账（`--write` 重写）。`pyproject.toml` 全是下限，下限不保证装出来是同一套；CI 另有一个 Windows job 专门**按锁安装**再对账 |
| `v3 backlog` | （新增） | 还开着的「未确认 / 待办」条目**合成一个数字**（按章节里表格的状态列判定）。它与 `v3 unverified` 是两层：标记项 ⊆ 章节条目，**不要相加** |
| `v3 assets` | （新增） | DDS 头普查（格式 / 尺寸 / mipmap，`--json` 落盘）。doc 06 §6.3 那三个结论此前是「一次性扫描」，现在这条命令可复算，那张表也已交给 `v3 tables` 生成 |
| `v3 csv <路径>` | （新增） | 非 PDX 表格（`.csv` / `.tsv`）的**逐列取值分布**，`-c 列名` 详列某列。doc 06 关于 `adjacencies.csv` 的结论由此可复算 |
| `v3 strings --families` | （新增） | 把未使用的 exe 标识符按**同后缀 / 同前缀**聚族（`--by suffix\|prefix --min N`）：实测 `*_command` 233 个、`*_cw_duplicate_compat` 161 个 —— PDX 字段名往往成族出现 |
| `v3 experiment` | （新增） | **游戏实测探针**：`plan` 打印「一次启动收工」的操作清单、`install` 把探针 mod 装进本机 mod 目录、`collect` 收割 `logs/` 并按实验编号归位证据、`uninstall` 移除。覆盖 P1–P11（裸同名键、双 mod 顺序、`scripted_modifier`/`scripted_list` 调用语法、`$PARAM$` 候选、进度条自定义样式、JE/事件/按钮字段语义、本地化 `:数字`、重名 namespace）。**登记范围**：它只管理 **3 个**探针 —— `experiments.PROBE_MODS`（`zz_probe_a` / `zz_probe_b`）加 `--risky` 才启用的 `zz_probe_risky`；`tools/probe/` 下另有 `zz_probe_h1` 与 `zz_probe_ab`，它们分别由 `v3 h1-probe` / `v3 ab-probe` 生成与部署（各自带真 mod），**不在 `v3 experiment` 的白名单里** |
| `v3 modgen` | （阶段 3 新增） | **数据源 → mod 产物**：`--write` 落盘并清理被取代的旧文件、`--check` 核对盘上产物是否被手改或过期、`--why` 列出每个数字与它的依据。产物在 `mod/`（原版目录树的镜像），改产物没用 |
| `v3 preflight` | （阶段 3 新增） | **开局前的只读自检**（`--archive <id>` 时一并查那份档案可不可跑、盘上的探针盯的是不是它）：游戏本体 / 版本与 mod 声明是否一致 / 盘上产物是否被手改 / **用户 mod 配置是不是原样**（探针态、残留备份都查）/ 有没有残留 `victoria3` 进程 / 日志里有没有上一局的自报。**退出码与其余命令同一套**：0 = 可以开局，1 = 有该修的问题，2 = 这台机器现在跑不了。为什么值一条命令：起游戏到选国家界面实测约 **137 秒**，白跑一次远比自检贵 —— 探针驱动（`stage3_rerun`）已经把它接在**任何改动之前**（`--skip-preflight` 可跳过）。它**只报告、绝不顺带修**；唯一会动手的是驱动在"上次被强杀留下探针态"时的自愈（backlog B89） |
| `v3 modguard` | （阶段 3 新增） | **五道闸门**：`--only` 逐道跑（编号或键名）。任一不过即非零退出，前置条件缺失（没有游戏）按用法错误处理 —— **跳过的检查不算通过** |
| `v3 ab-probe` | （阶段 3 新增） | 生成 A/B 臂阶梯探针（`tools/probe/zz_probe_ab/`，含 `tools/scripted_tests/` 套件）；`--deploy` 连同真 mod 一起装进用户 mod 目录 |
| `v3 ab` | （阶段 3 新增） | 分析实验归档：`--logs` 指目录、`--json` 机器可读、`--health` 开局自检（任一红即退出码 1）。报告按 ① 行为层 / ② 策略层 / ③ 改革侧输入段分开排，最后给判定 |
| `v3 ab-auto` | （阶段 3 新增） | 自动跑臂队列：`--plan` 只看队列与接线（安全）、`--months` / `--expect` / `--repeat` / `--record`。⚠️ **端到端跑批尚不可用**：`ab_auto.default_ports()` 的 `start` / `stop` 目前是"调用即抛错"的空实现（`cli.py` 里 `--plan` 也直接印着"启动/杀进程 **未接**"），要接 `game_auto` 才能从 `Ports` 传进去。设计上**没接上就退出码 1**（不静默跳过），所以现在跑只会得到一条 ❌ 记录 —— 证据见 `docs/design/exec/阶段3-实验记录.md`（目前只有表头，没有任何一节跑批记录） |
| `python -m pdx.game_auto <check\|run\|status\|capture\|background>` | （阶段 3 新增，**不是 `v3` 子命令**） | 底层「把游戏跑起来」的原语：`check` 起游戏前断言 0 个 `victoria3` 进程、`run` 完整闭环（点火 → 前台断言 → 点「观察」→ 取消暂停 → 切回后台；`--wait-tests N` 再补**后两步**：验后台仍在跑 → 等官方套件判定 → 读 `tests.txt` / `binaries/*_GameTests_testoutput.xml` 给结论，**不通过退 1**）、`status` 只读 tick / 探针月度行、`capture` 抓图、`background` 验后台是否继续模拟。**分工**：它只负责点火与读引擎写的结果，判定绝不自做 —— `SuiteVerdict` 判的是"引擎判了失败 / `error.log` 里有 `sitai_`/`SITAI` 的行 / 一个套件都没跑 / 读不到 `error.log`"，那行 `[ FAIL ] Error log: N errors` **不参与**（它数的是整份 error.log，原版自己就有几十条噪音）；`v3 ab-auto` 是阶段 3 的编排状态机，通过 `ab_auto.Ports` 注入调用它（`start` / `stop`）。范式与实测证据见 `docs/design/exec/自动化范式.md` |

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
.venv\Scripts\v3.exe tables --offline            # 不读游戏，拿入库快照核对生成表（CI 用）
.venv\Scripts\v3.exe evidence after orphan       # 查键名的四类证据
.venv\Scripts\v3.exe unverified -d 04            # 文档里还有哪些【未确认】
.venv\Scripts\v3.exe backlog --list              # 还开着的条目（含各篇待办章节）
.venv\Scripts\v3.exe prefixes                    # 本机 mod 的功能前缀按目录用量
.venv\Scripts\v3.exe assets                      # DDS 头普查（格式/尺寸/mipmap）
.venv\Scripts\v3.exe csv map_data/adjacencies.csv -c Type   # 某列有哪些取值
.venv\Scripts\v3.exe strings --families --min 20 # 未使用的 exe 标识符按族看
.venv\Scripts\v3.exe experiment plan             # 游戏实测探针：操作清单
.venv\Scripts\v3.exe experiment install          # 装探针 mod（写本机 mod 目录）
.venv\Scripts\v3.exe experiment collect          # 游戏退出后收割 logs/
.venv\Scripts\v3.exe cov                         # 覆盖率门禁（含核心模块下限）
.venv\Scripts\v3.exe modgen --write              # 数据源 → mod 产物（改完 TOML 必跑）
.venv\Scripts\v3.exe modguard                    # 五道闸门（全过才进游戏）
.venv\Scripts\v3.exe lock                        # 依赖锁与当前环境对账
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

### 环境矩阵：哪些门禁**不读游戏**（阶段 4 G-EXIT-2 的依据）

CI runner 上没有游戏本体，所以「哪些命令能在无游戏环境跑」必须是一条条**实测**出来的，
不能靠推断。下表每行都是把 `V3_ROOT` 指到不存在的路径（`C:\__no_game__`）后**真跑**的结果：

| 命令 | 无游戏时 | 它证明什么 | 进 CI |
|---|---|---|---|
| `v3 modgen --check` | **exit 0** | 盘上产物与 `mod/data/*.toml` 逐字节一致（P3：没有手写产物） | ✅ |
| `v3 verify --from-snapshot` | **exit 0** | 断言注册表与**入库快照**一致（不是"游戏里现在还是这个数"） | ✅ |
| `v3 tables --offline` | **exit 0** | 171 张生成表与**入库快照**一致（不是"表与现在的游戏一致"） | ✅ |
| `v3 citations --offline` | **exit 0**（实测） | 850 条引用与**入库快照的 `citation_support` 域**一致 —— 域里记着每条引用的**文件行数 + 被引那一行的文本指纹**（B77） | ✅ |
| `v3 lock` | **exit 0** | 装出来的环境与 `requirements.lock` 逐条一致 | ✅（Windows job） |
| `v3 modguard --offline` | **exit 0** | 五道闸门；①② 的原版真值改读入库快照（③④⑤ 本来就不读游戏） | ✅ |
| `v3 ai-surface --check --offline` | **exit 0** | 三件事全部枚举自原版 `ai_strategies` / `defines`（离线改读快照，且复用同一个 `render()`） | ✅ |
| `v3 modguard` / `v3 ai-surface --check`（**在线**） | **exit 2** | 闸门 ①② 要与原版键名、修正字段池取交集 ⇒ 无游戏时报「前置条件缺失」而不是"通过"（退出码 2 + 一句话，不是 traceback） | ❌（CI 用 `--offline`） |
| `v3 citations`（**在线**） | **exit 1**（实测：850 条里 827 条报 missing） | 它要**打开原版文件**确认那一行在不在 ⇒ 无游戏时是**假红**。CI 上必须用 `--offline` | ❌（CI 用 `--offline`） |
| `v3 cov` | 不适用 | 无游戏时集成用例被 `conftest` 跳过，覆盖率必然低于 86% 下限 ⇒ **门禁留在本机**，这不是遗漏 | ❌（刻意） |

两条口径（别读错）：
* **exit 2 不是"闸门不过"**，是"这台机器上跑不了"。**exit 1 才是判据不过** ——
  所以 `v3 citations` 的在线版在无游戏的机器上给的是**假红**（827/850 条报 missing），
  那种情况要用 `--offline`；把在线版的 1 当成"引用真的坏了"是错的。
* 离线通道证明的是**「与入库快照一致」**，不是**「与现在的游戏一致」** ——
  后者永远是本机门禁（`v3 verify` / `v3 tables` 不带 `--offline`）。两者合起来才完整。

## 测试

```text
python -m pytest                    # 配置在 pyproject.toml 的 [tool.pytest.ini_options]
python -m pytest -m "not slow"      # 跳过慢用例
python -m pytest --cov=pdx          # 覆盖率（门槛 86%，见 pyproject）
```

1582 条用例（`pytest --collect-only` 实测），
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
| `test_doc_tables.py` | **通用的**生成表机制：合成文档测整表替换/按键合并/行数变长/同表头多张/合并行/绝不静默删行/未匹配行会出声；以及「别夺走作者信息」那一族（加粗键能匹配、值没变连排版一起留、已有空格不填待补、单元格括注与「N/M」分母保留、**合并行每段各自剥反引号**、**空格千位也算一个数字段**、**纯数字只换数字本身**）；登记表完整性；171 张表与文档一致 |
| `test_doc_misc.py` | 那几篇「只有一两张表」的文档（doc 03/10/11/12/14/18/20）共用的看守：文档 == 生成结果、每一行都有人认领，外加本篇恒等式 —— doc 03 的 Top25 真的是前 25、doc 10 的两套分类都加总到 60、doc 11 与 doc 18 说的是同一批数字、doc 14 的令牌与 doc 16 同源；以及四张**本机 mod** 表仍在文档里（排除清单不许失效） |
| `test_doc16.py` | doc 16 剩下八张表的生成链：两栏并排的 flags/settings 取值集合没过期、**文件数与出现次数是两个口径**（`can_be_renegotiated` 出现 27 次但只在 26 个文件里）、`travel_network` 的顶层键与匿名块字段都在、`subject_types` 的列名与口径一致（该目录只有 1 个文件，那一列只能是出现次数） |
| `test_doc04.py` | doc 04 的生成链，另守三处易错口径：`script_values` 的「顶层键」是**块**口径（块 270 / 赋值 479）、`$PARAM$` **不数注释里的用法**、JE 分组两栏声明的取值集合没过期；以及「`placement` 六类分得掉全部取值」「事件字段表覆盖全部 26 个字段」 |
| `test_doc06.py` / `test_doc15.py` | doc 06 / 15 的生成链。除共用的两条（文档 == 生成结果、每一行都有人认领）外各守住本篇特有的恒等式：doc 06 的「语言表合计 == 全树 `.yml` 数」「三张目录表行数 == 子目录数」「扩展名表的每段都还在树里」；doc 15 的「`laws` 前缀划分完备」「§0 目录清单与代码一致」「五档态度合计 == 散文里的合计」「118 + 196 + 10 == 目录定义数（前两行是总数与子集，不是互斥分组）」 |
| `_table_guards.py` | 三个文档共用的生成表看守：`assert_doc_matches_generated` / `assert_every_row_claimed` / `assert_write_free_and_idempotent` / `assert_unique_names` |
| `test_stress_probe.py` | 标准压力剧本的生成器。核心不是"生成器能跑"，而是**生成的每一样东西在原版里都真的存在**：用到的 tag / `dp_` 博弈类型 / 效果名逐条拿原版文件核（写错一个字母的症状是**静默不做**，不是报错 —— tag 拼错 ⇒ `c:XQZ ?= this` 永远不成立）。另有 BOM / LF / 两次生成逐字节一致 / 只挂自己的 on_action |
| `test_gametimer_csv.py` | **切分口径**（`test_gametimer*.py` 管"字段怎么解释"，这个文件管"一行怎么切成字段"）：引号里的分隔符与换行、引号不闭合要**停而不是猜**（附非严格模式会把两行首尾相接成一条假记录的证据）、坏行存的是**真原文**、以及一条不变量 —— **无引号的行切出来必须与 `str.split` 逐字相同**（282 次穷举）。它踩过的坑也写在里面：一条 5 字段记录里，字段内容里的逗号加引号后就**不再是分隔符**，所以 `101,"x\nframe,task,…"` 是 2 字段而不是 5 字段 |
| `gametimer_fixtures.py` | 三份 gametimer 用例 + 基准**共用的夹具**（`TSV_SAMPLE` / `ticktask_text()` / `gametimer_text()`）。单列它的理由：夹具曾经漂移过（探针里把表头写成 `ms`，真表头是 `milliseconds`，"表头行被判成坏行"被当成 bug 查了半天）；基准与用例共用一份口径，性能数字才是同一件事的对照 |
| `test_repo_hygiene.py` | 源文件不带 CRLF —— Windows 上 `write_text` 漏了 `newline="\n"` 会把整份文件重写成 CRLF，而 `.gitattributes` 的 `eol=lf` 把 `git status` 掩盖成「干净」 |
| `test_properties.py` / `test_metamorphic.py` / `test_lexer_differential.py` | hypothesis 属性测试、变形测试、与独立 oracle 实现的差分对比 |
| `test_benchmarks.py` | 性能基准（`pytest-benchmark`，回归即失败） |
| `test_cli.py` | CLI 端到端：参数解析、退出码、入口点可用性、GBK 控制台不崩 |
| `test_release.py` | 发布流程的机械部分（`v3 release`）：版本对不上 / 少写一份档案 / 幽灵条目 / 没有发布说明 / 没有版本标题 / 归档物版本不一致，各钉一条；外加一条跑在**真实 `CHANGELOG.md`** 上的看守（不然这套检查只是自娱自乐） |
| `test_citations.py` | `文件:行号` 引用的核对：认出区间写法、**不把 `P2:F9` 这类章节号当引用**、同名多文件必须报歧义、行号越界要报出来、仓库内文件也认；最后一条跑在**真实数据源**上（**全部档案**的引用必须全部指得到）—— 这条断言就是"依据不许是编的"。另有一组看守入库的**引用支撑域**（B77）：域的形状与行数/指纹、离线只看记录不看在现场、在线核得出「被引那一行变了」、真实数据源的域与现场一致、以及**入库快照里确实带这个域** |
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
| `test_backlog.py` / `test_unknowns_covgate.py` | 「还剩多少没解决」这两套计数的口径：`backlog` 只数**条目表**（取证手册、配方表不算）、子标题继承父节、状态列写「已答」算已关；`unknowns` 跳过**元陈述**（「无法确认的一律标注【未确认】」是在说明约定，不是在使用标记） |
| `test_tables_offline.py` | `v3 tables --offline`：比对、**只动数据行**的恢复、快照缺表算「缺」不算「错」、反向（规格被删）也要报出来 |
| `test_audit_leftovers.py` | 审计报告 17 条建议里最后落地的五项：ruff 作为用例、doctest、八线程并发解析、解析吞吐宽松门禁、mutmut 配置有效性 |
| `test_degraded_paths.py` | **降级路径**：把 `config.GAME` 指到空临时目录，跑各模块的「没有游戏 / 文件坏了 / 输入为空」分支（CI 上真的走这条路） |
| `test_install_hygiene.py` | 游戏目录里**不许有非游戏文件**：看图工具的 `.XnViewSort` / `.dmp` 缓存、`Thumbs.db` 会让「安装树」那族断言集体报红（实测踩过），这里直接点名并给处置建议 |
| `test_cli_more.py` / `test_cli_new_commands.py` | CLI 的补充覆盖：新命令 + 剩余分支（`csv` / `assets` / `backlog` / `mirror check` / `refresh --dry-run` / 快照 diff…）。`cli.py` 是全包最大模块，这些分支**零成本可测**，没理由留着 |
| `test_lockfile.py` | 依赖锁：直接依赖一条不少、渲染与解析往返、标记求值保守（不认识的标记当作成立） |
| `test_experiments.py` | 游戏实测探针包：**探针脚本必须能被自家解析器读通**（探针自己写错＝用户白跑一趟）、实验清单点名的文件都存在、日志收割能按编号归位、安装/卸载不误删 |
| `test_modgen.py` | 生成器：数据源解析、**空 `why` 当场报错**（P10 的机械检查）、两次生成逐字节一致、游戏侧文件带 BOM 而文档不带、平铺在 `sitai_` 命名空间、生成物能被自家解析器读懂、写盘清理被取代的旧文件、数据源与产物往返一致 |
| `test_modguard.py` | 五道闸门各自的**通过路径与失败路径**：与原版同名键/路径相撞/非平铺/命名空间越界、缺本地化键/缺图标/引用不存在的修正或变量/defines 参数改名、超预算或无 `possible` 门的牌、往返丢字段、空 `why`、CLI 的退出码。原版侧用**合成的假游戏目录**，不依赖真实安装 |
| `test_ab_probe.py` | 阶段 3 的 **A/B 臂阶梯探针**必须被钉住的五件事：阶梯只有一处定义（`LADDER`）、换臂**幂等**（`stage` 单调递增，每个效果只施加一次）、两处输入**分开施加**（B 段只调冲击、B2 段才调改革侧输入）、0 张牌（F5）、生成物能被自家解析器读懂；另钉 `scripted_tests` 套件的判据方向（`fail` 日期必须早于 `last_date`，否则"没发生"永远不报）与"探针引用的效果名 == 数据源生成的名字"（P9） |
| `test_ab.py` | 阶段 3 的 A/B 分析器：按月配对（含脉冲跨秒与轮转副本）、`RUN` 分段 + 同臂多段合并、**一局三臂**（`A→B→B2`）、**两处处理分开报**（① / ② 是冲击步 A→B，③ 是改革侧输入步 B→B2）、判定三档（G2 初步成立 / H2 薄壳 / 无差分）与"样本不足不许宣判"、合法性五档诊断、`SHOCK`/`INPUT` 两条自检的通过与否决路径，以及**老归档（没有 `INPUT`/`LEG` 行）照样能分析**（阶段 3 的结论就来自那些局） |
| `test_ab_auto.py` | 阶段 3 的**自动实验编排**状态机全路径（假端口，不开游戏）：有进程时前置断言中断、启动接口没接上当场报错、轮询三种收工方式（到点 / 游戏提前退出 / 轮询用尽）、进度按探针自己的月度块算而不按墙钟、整臂跑通的状态顺序与归档标签、没跑到目标臂或月数不够即不达标、记录文件的表头与追加、队列"一臂不达标即停"、CLI `--plan` 不写文件与未接线时退出码 1 |
| `test_game_auto.py` | `game_auto.py`（1102 行）的**纯逻辑**看守（948 行；假窗口 / 假截图 / 假时钟，不开游戏）：tick 与探针月度行的解析与读取、进程清单、ROI 裁剪、空白检测、图像匹配（含真实模板回放）、`wait_until*` 的等待语义、前台断言、点击（含「点观察」）、截图、取消暂停、后台仍在推进的判据、启动命令构造与缺 exe 的报错、窗口/大厅等待、`describe`/`status` 的文案。真开游戏的 `TestLive` 一类按条件跳过 |
| `test_game_auto_verdict.py` | 闭环**最后两步**的看守（官方成绩单解析 / "我们的报错"只数我们的 / 两条假绿都挡住 / 等落盘是条件等待 / 接线与退出码）。两条假绿指的是：照 `[ FAIL ] Error log: N errors` 判会**每次假红**，而"零失败 + 零套件"会**假绿** |
| `test_gametimer.py` | `gametimer.py` 的解析与统计（纯合成夹具，不依赖游戏）：表头识别、`Year/Month/Day` 三档聚合、坏行只打标不改写、按单元汇总与「最坏一天」、**「单帧量不出来」这件事本身**（`per_frame_measurable is False`）—— 预算判据不许把不可测的东西写成测过了 |
| `test_mod_hygiene.py` | **P3 / G-EXIT-4 的文件面判据**：`mod/` 下的文件必须**正好**等于「生成结果 ∪ 数据源」。为什么需要它 —— `v3 modgen --check` 与 `v3 modguard` 都只认本档案前缀（`sitai_`），实测换一个前缀手写一个游戏侧文件（`zz_stray_handwritten.txt`）**两道门禁都报绿** |

### 跑基准要加 `-n0`

`pytest-benchmark` 在 xdist 开启时会**自动禁用自己**，而本项目默认并行
（`-n auto`）。因此不带 `-n0` 时基准会被静默跳过 —— 实测踩过：

```text
python -m pytest tools/tests/test_benchmarks.py --benchmark-only -n0
```

### 变异测试：按需跑，不进 CI

审计报告第 6 条建议「变异测试」的落地方式与其他项不同 —— 它按定义要
**改一处源码 → 跑一遍测试 → 看有没有红**，一轮几十次全套测试。
放进 CI 等于每次提交跑几十分钟，放进 pytest 更是自相矛盾（测试里再跑测试）。
所以它的用法是**定期体检**，配置写在 `pyproject.toml` 的 `[tool.mutmut]`：

```text
.venv\Scripts\python.exe -m mutmut run       # 跑一遍，看存活率
.venv\Scripts\python.exe -m mutmut results   # 列出存活下来的变异体
```

先只覆盖 `lexer.py` 与 `markers.py` 两个**纯函数、无游戏依赖**的模块：
依赖真实游戏数据的模块会让每次变异都因环境差异而失败，
那种红不代表测试强，只代表环境在动。

### 性能门禁是「宽松下限」而不是数字比对

审计报告第 9 条建议「性能回归门禁」。本项目采取的是：基准用例照跑
（`test_benchmarks.py`，回归即失败），另有一条**宽松的吞吐下限**
（`test_audit_leftovers.py`：解析吞吐 > 1,000 行/秒，实测比它快一个数量级），
以及一份入库存档的基准记录 `tools/benchmarks/parse_baseline.json`。

为什么不卡死数字：CI 与本机的 CPU 差几倍，卡死只会制造噪音。
宽松下限抓的是「引入 O(n²)」「每次都重读整棵树」这类**真退化**。

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
tools/out/snapshots/<版本>.compact.json   精简快照，约 6.0 MiB（**入库**，跨机器可 diff）
tools/out/snapshots/<版本>.json           完整快照，约 39 MiB（gitignore，本机深挖用）
```

> 上面的 MB / KB 按 1024 进制。精确值由黄金回归（`tools/tests/test_golden.py`）
> 冻结为逐产物的「字节数 + sha256」，改动一个字节就会失败。
>
> ⚠️ **快照分两种，只有精简版入库**：完整快照 73% 的体积是本地化键清单
> （11 种语言 × 14.5 万键），而「Paradox 增删了哪些字段与条目」只需要结构域。
> 精简版保留 `common_entries` / `fields` / `defines` / `dlc` / `config` 五个域，
> 只把 `localization` 换成「键数 + sha256」，因此 **6 MiB 上下就能随仓库分发**，
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
| **某个键在原版里到底怎么用** | `v3 evidence <键>`：键与**值**分开统计、父键链、取值形态、`文件:行号`；注释不算用法 |
| **引擎二进制里有没有这个字面量** | 同上第 ④ 类：`--exe-grep` 查一族名字、邻居串看表内聚集 |
| **还有哪些结论没证据** | `v3 unverified`（文档里全部【未确认】，可数、可定位、逐条附复算命令） |
| **两个版本之间，Paradox 增删了什么** | `v3 snapshot diff`（结构域逐项比对） |
| **官方 `.md` 有没有被 Paradox 改过** | `v3 mirror check`（清单 vs 本机本体，逐篇 sha256） |

**不能**回答 —— 信息不在文件里，不是功能没做：

| 答不了的问题 | 为什么 |
|---|---|
| 两个 mod 改同一条目谁生效 | 取决于运行期加载顺序，脚本里没有 |
| 某字段的合法取值范围 | 只有引擎知道；二进制里能挖到候选词表，但「候选」不等于「合法」 |
| 同名条目里哪个最终生效 | 引擎的合并规则，未知 |
| 平衡性与 AI 实际表现 | 要跑游戏才知道 |

> 关于第三行：`victoria3.exe` 里有 **55,281 个标识符形状的串**，其中
> **31,431 个从未在 `.txt` / `.gui` / `.yml` 里出现**（`v3 strings` 现算，
> 口径见 `pdx.exe_strings`）—— 那批词里确实藏着字段枚举。
> **开采已经开始**：`v3 evidence --exe-grep <子串>` 能按名字族取证，
> `identifier_neighbors()` 能看某个串在二进制里的邻居（同表聚集）。
> 已有一条可复算的成果：引擎里有 **161 个** `<键名>_cw_duplicate_compat`
> 重名策略名（`v3 evidence --exe-grep _cw_duplicate_compat`），
> 说明「同名键怎么处理」是**按键名逐项配置**的，而不是一条全局规则
> —— 这正是 doc 04 §12.4 的证据。
> 早先这里写的是 17,821 / 16,535：那是一次性采集值，**口径没留、脚本没留**。
> 现在这两个数由 `v3 strings` 从 exe 现算，`tools/tests/test_repo_numbers.py` 会核对。

## 阶段性收尾（2026-09）

这一轮做完了两件事：把 **12 处功能前缀覆盖证据**与 **92 处【未确认】** 收敛到
**51 处**（每条都写明「已查什么证据 / 还缺什么实测」，`v3 unverified` 可复算），
以及补齐工程卫生（离线核验生成表、解析磁盘缓存、覆盖率模块下限、依赖锁）。

**还剩什么**（四块，按性价比排序）：

| # | 事项 | 现状 | 缺口 |
|---|---|---|---|
| 1 | **C 组：语义实测** | 51 处【未确认】里约 35 处属「只能进游戏才能定」：裸同名覆盖语义、跨 mod 优先级、`scripted_list`/`scripted_modifier` 调用语法、`after`/`orphan`/`is_shown_in_lobby` 等字段语义 | 需要启动游戏：`game\tools\scripted_tests` + `-debug_mode` 日志；`database_conflicts.log` 目前是 0 字节，跑一次真实冲突就能填上 |
| 2 | 两项一次性普查脚本化 | doc 06 的 DDS 头普查（11,294 个文件）与 `adjacencies.csv` 全表枚举仍是手写脚本 | 做成 `v3` 子命令后可复算、可断言（符合「能脚本化的都脚本化」） |
| 3 | 覆盖率重路径 | 整体 88.07%（`v3 cov` 门禁 86%；模块下限表 11 个） | `cli.py` 60.9%、`experiments` 64.2%、`engine_log` 65.4% 是「要真跑游戏数据 / 真开一次游戏」的路径；`console` 85.7% 同理。**不是退步**：`localization` 88.5% / `mods` 93.9% / `tabular` 93.4% 这一轮已补上（旧值 74 / 79 / 80 是补测前的口径） |
| 4 | CI 用锁安装 | `requirements.lock` 已在本地对账（`v3 lock`） | CI 仍从 `pyproject.toml` 的下限现解析；改成从锁安装需要一次跨平台验证 |

> 这四块**都不影响当前可用性**：知识库里每条结论要么有证据、要么明确标着
> 「未确认 + 取证配方」，工具链的门禁（断言 234 条、生成表 171 张、覆盖率、
> 依赖锁、离线核验）全绿。

## 为什么全 Python 化

| 原因 | 具体表现 |
|---|---|
| PowerShell 5.1 的编码陷阱 | 不加 `-Encoding utf8` 按 GBK 解码；`Set-Content -Encoding UTF8` 写 BOM |
| PowerShell 的反引号转义 | 字符串里写 Markdown 代码块会报语法错误（开发中触发多次） |
| 缺少数据结构 | 解析结果只能用 PSCustomObject 拼，不如 dataclass 清晰 |
| 无法写正经测试 | PowerShell 没有 `pytest` 那样的测试框架 |
| Node 需要额外运行时 | 而 Python 的 `utf-8-sig` 编码名天然解决 BOM 问题 |

Python 版把上述问题都变成了**可测试的代码**：1582 条用例 + 234 条断言核验
（`v3 verify`，其中 `--fast` 跑不需要全库扫描的 211 条），
外加一层**外部验证** —— `v3 crosscheck` 拿游戏自己的日志核对我们的解析。

> `v3 verify` 同时跑**文档正文的数字漂移扫描**（`verify.unknown_doc_drift`）：
> 断言表测对了不等于文档写对了 —— 正文里可能仍躺着旧值，而断言表照样全绿。
> 有漂移时退出码同样是 1，所以在 CI / pre-commit 上也会被拦住。
> 确认是「口径不同、文档没错」的登记在 `pdx.verify.KNOWN_METRIC_MIXUPS`（附理由）。
>
> **没有游戏的机器（CI）怎么办**：234 条断言里 43 条能用**入库的离线真值**核验
> （精简快照里的目录条目 / defines 命名空间 / DLC 清单 / 版本指纹，加官方文档清单），
> 其余 191 条要读游戏本体。跑 `v3 verify --from-snapshot` 即可，它**不读游戏**。
> 它证明「断言注册表仍与当时记录的真值一致」，不证明「游戏里现在是这个数」；
> 两者合起来才完整，所以 CI 上跑前者、本地跑后者。
>
> **生成表也有离线那一条**：171 张表要读游戏才算得出来，于是「表被手改、或改了
> 生成器却忘了重跑」在 CI 上一直没人守。现在精简快照里带着每张表当时的数据行
> （域 `doc_tables`），`v3 tables --offline` 只读快照与文档即可逐行核对
> （`--write` 可按快照恢复）。CI 与 pre-commit 都跑这一条
> —— 它与 `v3 verify --from-snapshot` 的分工完全对称。
