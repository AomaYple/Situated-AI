# Mod 架构重设计结果

本轮从主线 `219420b25b2dc451616dad72246e99e32a7d1bae` 交付定稿原则、交付合同、架构主计划、逐方面的接口计划、当前状态入口及对应测试。既有本地候选 `codex/mod-architecture-and-plans` 的 `4b438c5967068cb727ef76cf0a339faa35052407` 提供定稿原则字节和历史方面清册。旧候选仅在本地保留，普通主线克隆可能没有该对象。生产、生成器、包、研究数据及冻结归档的路径差异为空。主线版本、旧候选及公开渠道沿其各自的证据追溯。[设计前主线](https://github.com/AomaYple/Situated-AI/commit/219420b25b2dc451616dad72246e99e32a7d1bae) · [当前工作清单](../当前工作清单.md) · [版本交付索引](版本交付-结果.md)

## 阶段与冻结产物

| 阶段 | 提交与实际差异 |
|---|---|
| 原则与验收合同 | `04fe3b1e488226d6faa8c28320afd740b1596ed6`。11 个路径覆盖原则、索引、放行合同、贡献流程、根导航、PR 模板与测试。相对设计前主线的 `git diff --binary` 字节 SHA-256 为 `0b588b5678513c009e25a6d1f65e28ed72be77360fa32c28abf5160d195c4e91`。 |
| 主计划、方面及导航 | `aa0da8bb48558e55eb94fc2b48e75e661cdcd329`，树 `cbe3a1f064d6c884263e580e4da09bb610179288`。10 个路径覆盖设计与状态、现行与历史导航、文档合同测试。前两阶段合计 20 个唯一修改路径。 |
| 整体验证 | 本页记录提交回读、覆盖核对、设计复算、独立复核和工程门。推送、CI、审查及合并状态以交付 PR 对应的提交与检查记录为准。[仓库 PR](https://github.com/AomaYple/Situated-AI/pulls?q=is%3Apr+head%3Acodex%2Fmod-architecture-design) |

| 第二阶段提交的原始文件 | SHA-256 |
|---|---|
| [架构主计划](../架构主计划.md) | `c530f5b1cc7f6a64a53dab6c9af7894ecef115ad7addaae9b1594e330488f130` |
| [架构子计划](../架构子计划.md) | `d6051a6ae75aa7a8ab23787e327dbda69a2506835be46f831b3d9f76aefe10db` |
| [工程合同测试](../../../tests/test_engineering_contract.py) | `f31e3d4b14b431e0af5106770eb44fe4fc7498c53c9d0d76e13b42bd9dadac1a` |

## 原版与方面证据

- `snapshot`。Paradox 发布的 Victoria 3 1.15.2 公告登记校验码 `fb14`。实装的 `appmanifest_529340.acf` 登记 Steam public build `26763837`，`binaries/checksum.txt` 的末四位同为 `fb14`。随附 100 份官方资料逐份比对实装原字节 SHA-256，与登记的原件指纹一致。安装分支和两项引擎修订可从版本页所列原件复核。[官方公告](https://store.steampowered.com/news/app/529340/view/1849827110428155) · [实装版本](../../victoria3-modding-1.15.2/01-环境与版本.md) · [官方资料指纹](../../../research/official-docs-1.15.2.manifest.json)
- `snapshot`。冻结安装报告的 `COMPLETE.json` 字节 SHA-256 为 `d20a3022b4b4dc6a6b04722d75feadc135fb343634f757c2960153fa0c89e315`，内含 `epoch_id=4fa973e8d7589a5d04c90f2f8eb7902ea97839b9dbc5b4508779878d73db1a70` 和 `file_set_sha256=63cd9e53c34ab196657a550e3f18e0edd1d42ef0223a82bf88b03188e7c6057d`。回读的目录报告原字节与其登记摘要一致。该轮冻结研究登记 30,507 个安装路径及 5,686,344 个位置或引用候选，可用于历史来源定位。解析状态和运行、语义、接线待证范围分别追踪。[冻结报告定位与分层](../架构主计划.md#从完整资料到国家观察) · [完整安装研究入口](../../../CONTRIBUTING.md#完整安装研究)
- `static_check`。从 Git 原始文件独立提取方面 ID，验证 25 个领域、119 个唯一方面及 111 个历史 ID 的完整包含关系。新增 8 个 ID 为 `D01.insolvency`、`D08.company_charters`、`D09.market_formation`、`D10.tariff_subsidy`、`D16.amendments`、`D23.auto_replenishment`、`D24.surrender`、`D25.capital_relocation`。119 行登记原版入口。作者核对 99 个唯一安装定位，独立审查去掉行号后核对 81 个安装路径和 19 个唯一本地链接。目录各项为新架构预留接入，运行读点、国家可知性、实际消费者与结果按各项原版机会取得证据。[方面目录](../架构子计划.md)

## 选型验算与独立复核

`inference`。对照四种可实施机制，包括单字段局部规则、领域或资源竞价、仅用合法观察的滚动时域或信念状态规划、分层时序影响图与条件策略。另列全知联合规划作为离线诊断上界。选用分层时序影响图来表达跨域资源、时序、可获知信息和共同终点。求解器可以替换，强局部公式与合法滚动规划按相同假设和计算口径对照。[架构选择](../架构主计划.md#架构选择)

`simulation`。用 Python `fractions.Fraction` 独立复算假设夹具。可用量依次为 5 和 8，每个容量先算常态、后算已知断供，产业投入相对优势为 `+2.25`、`−4.75`、`+6.75`、`+1.25`。相同输入的局部精确公式四格一致。低容量断供时未来机会概率 `q=2/9` 恰好归零。合法历史无法区分隐藏状态时，可实施策略期望为 4，全知上界为 8。同一模型贯穿整条轨迹的最坏期望为 4，逐枝拼合不同最坏模型会误得 0。整组候选分布中，向价值为 5 的候选转移 0.2 的概率，来自价值 9 或 0 的候选时，依次得到净差 `−0.8` 或 `+1.0`。这些数值对应给定模型和概率条件。[求解与宽度控制](../架构主计划.md#求解与宽度控制) · [共享资源验算](../架构主计划.md#共享资源的手算试验) · [原版字段干预价值](../架构主计划.md#原版字段干预的价值)

| 独立复核 | 发现及核对结果 |
|---|---|
| 原则与交付合同 | 在阶段一冻结补丁复查两项 P2。正式支持流程已绑定可持久取得的同一 ZIP、计划摘要、目标构建与全玩法 DLC 下的逐模式实测。历史 SAI-19 的 E 单独通过仍须完整验收退出 0、源码快照一致及有效 ZIP 摘要，四个负例被拒绝。[一键发布](../../../CONTRIBUTING.md#一键发布) · [工程合同测试](../../../tests/test_engineering_contract.py) |
| 整体架构 | 最终稿逐项关闭四项 P2。强局部精确解和合法滚动规划共用条件。稳健求解保持整条路线的模型相关性。字段投影重算整个候选分布与原版继续搜索。防御条约在 A 起草时估计 B 分数，B 的实际裁决另绑定调用者、控制权与信息权限。复查也确认游戏内开销测量仅在架构选型需要时使用，采用及发布依 E、M、R、U 各自证据判定。[条件策略与反事实估值](../架构主计划.md#条件策略与反事实估值) · [防御条约](../架构主计划.md#防御条约的跨期闭环) |
| 逐域接口 | 最终冻结子计划复核无 P1/P2。普通市场迁移与大规模迁移分别定位，公司特许使用实际原版资格与权重。迁都和市场首府各有独立入口。破产、投降和补舰的 GUI 对应原版界面，逐国 AI 接入另有见证要求。历史清册可取性记录在本页与工作清单。[逐方面接口](../架构子计划.md) · [本地候选](../当前工作清单.md#本地候选) |
| 历史导航与测试 | 现行阶段出口唯一归主计划，清单指向首个原版机会，旧 R2 的 SAI 报告与 X1 原始归档保持可查。测试改为分别验证历史回执、现行状态导航及逐方面五列合同。相对基线核对时，冻结归档、既有结果页及其身份无字节差异。[工程合同测试](../../../tests/test_engineering_contract.py) · [历史归档](../archive/README.md) · [执行文档索引](README.md) |

## 工程验证与范围

Windows 本机 CPython 3.15.2 上，两阶段分别运行以下六组定向测试。阶段一用 2 个 worker，76 项通过。阶段二用 3 个 worker，79 项通过、用时 5.63 秒。两轮均无跳过。第二阶段的定向测试对应上表已签字节。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m pytest -n 3 --no-cov -p no:cacheprovider tests/test_principle_ids.py tests/test_engineering_contract.py tests/test_docs_consistency.py tests/test_current_release_contract.py tests/test_architecture_receipts.py tests/test_engineering_enforcement.py
```

| 本机 `static_check` | 结果 |
|---|---|
| `git diff --check 219420b2` 和生产路径差异 | 差异格式通过。生产 `src/`、`mod/`、工程工具、研究数据和档案无路径差异。 |
| `tools/ci/run_check.py encoding` | 仓库 UTF-8 无 BOM 与 LF 检查通过。 |
| `tools/ci/run_check.py lint .` 与 `format --check .` | Ruff 检查通过，629 个文件符合格式。 |
| `tools/ci/run_check.py types --cache-dir tools/out/ci/design-mypy-cache --show-traceback` | 隔离目录复验通过，509 个源文件无类型错误。 |
| `tools/ci/run_check.py baseline-offline` | 7 项通过，包括依赖、快照断言 43/43、184 张生成表、现有 Mod 静态门、既有情境决策合同、离线 AI 面、3,205 个定义的死代码审计。 |

本轮的范围是设计验收，参考机、首片投影和新架构的固定包 E/M 属于后续实施出口。尚无新架构的 `runtime` 结果，R/U 保留 `unknown`。本机运行了定向测试和工程静态门，三平台离线回归与正式合并检查在相应 PR 记录中查阅。发布与实机采用依各自的版本和包合同签署。[阶段出口](../架构主计划.md#阶段出口) · [工程交付基线](工程基线-1.0.md#证据口径) · [仓库 PR](https://github.com/AomaYple/Situated-AI/pulls?q=is%3Apr+head%3Acodex%2Fmod-architecture-design)
