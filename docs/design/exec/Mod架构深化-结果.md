# Mod 架构深化结果

本轮从 Squash 合并提交 `e9ed9e19bdb5c243bfc7fc8fb998c7036526fd66` 深化国家决策架构、逐域接口和原版资料复查。现行生产仍为 Mod 3.3.1、Victoria 3 1.15.2。GitHub Release 回读显示最新正式 Mod 为 3.3.0，适用 Victoria 3 1.15.1。历史本地实施候选 `codex/mod-architecture-and-plans` 的 `4b438c5967068cb727ef76cf0a339faa35052407` 继续承担历史方面清册与独立候选证据。相对本轮基线，生产源、生成物、工具、锁文件、研究数据和冻结归档的 Git 差异为空。[主线基线](https://github.com/AomaYple/Situated-AI/pull/114) · [版本交付索引](版本交付-结果.md) · [最新正式 Mod](https://github.com/AomaYple/Situated-AI/releases/tag/v3.3.0) · [当前工作清单](../当前工作清单.md)

## 阶段与产物身份

| 阶段 | 提交、树和交付物 |
|---|---|
| 共用架构 | `fff3099815eee6fa0a18352609967aa3118ccc79`，树 `16879c9fa0d03ac3d1a386e3b0b3c4830c3529aa`。主计划和三份共用设计展开跨国反事实、跨期求解、局部原版投影与验收。 |
| 逐域设计 | `4642ea41873e58894d05438884d73591b48b4045`，树 `ba1b2998e284fba814042c7a40fa4104b046e33b`。25 份逐域子计划、128 项总索引及文档合同测试。 |
| 证据和入口 | `8977d4daa2c16a502a36dd1bc34aac1f297a26ae`，树 `827c4fcf946c6468158d57f76604805e60fb10a5`。安装资料盘点、当前工作清单及文档导航。 |
| 独立复核和整体验证 | 本收据所在主题提交整合三份共用架构修订、六份逐域修订、原版资料盘点的格式校验及黄金回归输入修复。完整验收冻结源树为 `13a3b2164c43766e0ed0ca5e43a0e59383e53bba`，随后加入本收据和索引。主题分支和合并身份从[对应 PR](https://github.com/AomaYple/Situated-AI/pulls?q=is%3Apr+head%3Acodex%2Fmod-architecture-depth)回读。 |

| 最终重要产物 | 原始字节 SHA-256 |
|---|---|
| [架构主计划](../架构主计划.md) | `11bad0d0c3add1ea192707e761cc3cde5e2fe769c41e4df1a8d71279eb5d966d` |
| [架构子计划](../架构子计划.md) | `18e34124435a437334eed40ffe1328e91913f1ffbb25cd4ce79d7b201fd0ba80` |
| [资料与机会](../architecture/资料与机会.md) | `0c2d355289686a4138eb04d6ffb2c07309edc955cf509a79d28fd4f0b8c5cab2` |
| [跨国反事实与跨期求解](../architecture/跨国反事实与跨期求解.md) | `963c0b047b6cc1e94ed705facf29a30355754e870c696ad04285bb1d5bd404e9` |
| [原版算子与投影验收](../architecture/原版算子与投影验收.md) | `e813ab96712058ff8044edec88ae335e527b84ef246421218726aac0c8cb72a7` |
| [原版资料盘点](../architecture/原版资料盘点.md) | `9f64739d7e9d025351de9ab16b9215c2a306a3dba208892b77824e457c563e57` |
| [当前工作清单](../当前工作清单.md) | `4270df7df11d52c38a7c845a804ec020c57e658695125fb3a1e94a5f7950c631` |
| [工程合同测试](../../../tests/test_engineering_contract.py) | `bd1c9c4db02b40be0173f84d0399cee056f6bb2ecda61ae8fb33a7f8809f04d4` |
| [黄金回归测试](../../../tests/test_golden.py) | `7fc5e60aad3eeed6a979db3b7c7502f92063eca7f85748108e99fa41a3f5d6c4` |
| [固定输入指纹](../../../tests/test_golden/test_artifact_digests_1152_fixture.yml) | `85dee2c55de7c18355cc12fe976b1a3227aaade145ff32c97df2ab368a5a7594` |

## 原版输入与静态覆盖

- `snapshot`。核对 Steam 官方公告近 30 条，本轮核对的最新正式游戏补丁为 1.15.2，公告时间 2026-11-19 12:34:11 UTC，公告校验码与本机 `binaries/checksum.txt` 末四位均为 `fb14`。本机 `appmanifest_529340.acf` 确认 Steam public build `26763837`。锁定安装的六项身份文件与仓库合同相符，100 份随附官方 Markdown 原件与 manifest 逐份原始字节摘要相符。九个公开玩法包、两个会改变玩法的特殊包及七个音乐或呈现包分别登记。DLC 权益、会话启用与联机共享仍待运行证据。[Steam 官方公告](https://store.steampowered.com/news/app/529340/view/1849827110428155) · [安装和 DLC 盘点](../architecture/原版资料盘点.md#安装身份与资料范围) · [官方资料指纹](../../../research/official-docs-1.15.2.manifest.json)
- `snapshot`。重新运行当前 `pdx.cli analyze --installation`，约 28 分 16 秒，退出 0。实装 30,507 个路径均读取，共 19,709,812,714 字节。相对历史冻结目录，30,505 个非 SDK 状态文件逐一匹配原始 SHA-256，另两个 SDK 状态文件的路径匹配。新索引复核七个跨域来源，覆盖防御条约、公民权、建造方式、动员、IP5 公司、地图节点和 Shader。样本符号 `has_friendly_diplomatic_pact` 返回一个定义和两条样本引用。[全安装研究命令](../../../CONTRIBUTING.md#完整安装研究) · [盘点和查询命令](../architecture/原版资料盘点.md#全安装目录和索引)

| 本轮重新生成的安装索引 | 结果 |
|---|---|
| 输入身份 | `epoch_id=0b9f9f1a6e399ca1d1cfc97f7dff38c11c0ceb159475d1f874b69eb82597715a`，`file_set_sha256=63cd9e53c34ab196657a550e3f18e0edd1d42ef0223a82bf88b03188e7c6057d` |
| `COMPLETE.json` SHA-256 | `e37df3a146ae89e5302ee5fd146067f3c953e70ee7d1e1aee10467acfb429145` |
| `information-catalog.json` SHA-256 | `fa78dac2133d81ee3dfc89be2252f3224207ff6bacd8b15d940312a6bf3f333f` |
| `occurrences.sqlite` SHA-256 | `c412dbe25bfb5f5d33a0e07de92daac847df28c0cf97c7284aa37b8d304f574b` |
| 解码 | 10,736 完整、1 失败、19,770 未尝试。 |
| 通用结构 | 10,368 完整、16 局部、1 失败、18,584 未尝试、1,538 不适用。 |
| 专用结构 | 动画 648、DDS 13,819、网格 3,886、Shader 90 完整。DDS 1 失败，Shader include 115 完整、15 局部。`map_data/nodes.dat` 有原始字节摘要，通用及专用结构均未尝试。 |
| 后续证据 | 5,686,344 个位置或候选的运行语义未知。合法逐国读取、引擎消费与生产闭环各自的分母待建立。 |

- `static_check`。独立重跑盘点页示例，查到 `game/common/` 全部 141 类、2,392 个事件树行首声明候选和 2,391 个点分事件 ID。其中一处行首信号为未缩进的 `immediate`。原版静态消费者工具扫描 50 个目录，解析 1,878 个文件，绑定 1,960 个来源摘要，登记 9,797 个声明、6,589 条引用及 602 个作用域合同待补的声明。静态清册 JSON SHA-256 为 `68ae5aa7ded90c108c056a256f4049bc225240d18a7024bc06f5ad8311a55a17`。[静态分母及复跑代码](../architecture/原版资料盘点.md#ai-可执行面的静态分母)
- `static_check`。从最终分域文件和各代基线提取 ID，核对 25 个领域及 128 个唯一 ID，覆盖上一主线 119 项及本地候选 111 项。新增 `D03.built_capacity_reduction`、`D04.land_reclamation`、`D20.foreign_interference`、`D20.regional_objectives`、`D20.strait_control`、`D22.formation_organization`、`D23.coastal_defense`、`D25.cossack_hosts` 与 `D25.expeditions`。最终领域页里的 170 个不同安装定位路径均存在，含 354 个不同路径与定位后缀组合，291 组纯数字定位落在原件实际行号范围。阶段二另核对其当时的 159 个安装路径、331 条明确定位及行号。[考虑因素与验证](../架构子计划.md) · [工程合同测试](../../../tests/test_engineering_contract.py)

## 独立复核

| 复核范围 | 发现及已核对的修订 |
|---|---|
| 跨国反事实估值 | 部署可能改变能进入比较的原版机会。用固定起点建立全组结果，用相同机会配对估计局部效果，并单独登记实际出现的机会。合成例的描述差为 `+4`，固定机会局部估值为 `−1`，预先等权起点总效应为 `(9+x)/2−5`，其中 `x` 为机会消失后第二类国家的实际结局。[反事实与求解](../architecture/跨国反事实与跨期求解.md) |
| 条约投影 | 自愿防御条约链按起草、接受、双方批准和生效建立见证。法律承诺加入强制生效对照，一次实际生效分别查核 `on_entry_into_force` 与 `on_enforced` 的效果。强制失败对照保持未生效。[原版算子与投影验收](../architecture/原版算子与投影验收.md) |
| 行政与州接管 | `D02.incorporation` 唯一归口普通州启动、维持和取消并入。并入启动即占用完整官僚成本，继续沿用已扣成本的净值，取消实际返还后才回读。D25 提供州主、领土交接及并入完成状态，并保留独立殖民建置。州税收和制度供给分别依据进度与实际状态。[D02](../domains/D02.md#d02incorporation) · [D25](../domains/D25.md#d25administration) |
| 贸易、制度与救济归口 | D10 补齐商品转移条约的候选、兑现和违约，并绑定 D20 的条约编排。D16 将学校评分归 D13，与医疗等其他制度等级机会共享官僚约束。D17 归口紧急救济候选，D06 统一写入对应原版法令字段，D18 提供损毁与恢复观察。[D10](../domains/D10.md) · [D13](../domains/D13.md#d13school_investment) · [D16](../domains/D16.md#d16institutions) · [D17](../domains/D17.md#d17relief) · [D18](../domains/D18.md#d18recovery) |

独立复核闭合版本的 Git blob 短标识按路径登记。主计划 `bd7370ede7e1`、原版算子 `18de43396025`、跨国反事实 `0bf04ff11315`。D02 `11611b6d2546`、D10 `db3d65883d8e`、D16 `be5f49898222`、D17 `844430be1155`、D18 `ef3dd87907cf`、D25 `65455150fbee`。阶段四资料盘点另通过 Ruff 格式化修订，Python 示例的 AST 与围栏外文本逐项比对一致，同一安装重跑示例退出 0。

## 工程验证

本机使用 Windows CPython 3.15.2 正式版及符合 `requirements.lock` 的 50 项锁定环境。第二、第三阶段各有 49 项定向测试通过。加入收据和索引后，文档一致性和工程合同的 39 项定向复验通过。完整验收使用锁定安装和项目自己的调度与资源测量入口。

| 检查命令 | 实际结果 |
|---|---|
| `git diff --check e9ed9e19`、UTF-8 无 BOM 与 LF、变更范围 | 格式差异门通过。全部交付文件为 UTF-8 无 BOM、LF，仓库受控源码编码检查通过。 |
| `tools/ci/run_check.py lint .` 与 `format --check .` | Ruff lint 与格式检查均通过，660 个文件符合格式。 |
| `tools/ci/run_check.py types --cache-dir <隔离目录>` | 509 个源文件无类型错误。 |
| 相对 Markdown 链接与锚点 | 变更 39 个路径。相对文件链接 437 条，其中 217 条含 Markdown 锚点，逐条通过。 |
| `tools/ci/run_check.py baseline --profile 1.15.2` | 全部 10 项通过。核对 43/43 条离线断言、184 张生成表、3,205 个死代码审计定义和 100 个生产生成文件。 |
| `tools/ci/run_check.py full-acceptance --profile 1.15.2 --quiet --output-root <隔离目录>` | 退出 0，12,652 项通过，14 项跳过，综合分支覆盖率 88.5444%，2 个 worker，墙钟 3,269.54 秒。 |
| `tools/ci/run_check.py hygiene` | 按白名单移除本轮 7 处缓存和构建元数据，再查 0 项。 |

首轮完整门退出 1。12,650 项通过、14 项跳过、1 项失败，1,580 个子测试通过。3 个 worker，墙钟 2,349.49 秒，综合分支覆盖率 88.5397%，整套 RSS 峰值 3,457.6 MiB，单 worker 1,375.9 MiB。报告 SHA-256 为 `9a901c3dc0ab883c4e9d9d088f17940242cbd62f88232156849819a094c2ce6c`。测试收集、实际启动和结束同为 12,665 项。失败节点为 `tests/test_golden.py::test_artifact_digests`。

独立诊断回读旧的现场分析产物，与旧黄金指纹逐一相符。首轮新结果差异集中于 Workshop 订阅 `2880069248` 的本地化变化。锁定原版的六份产物及交叉结果与旧指纹相同。黄金门改为固定合成的 Workshop Mod，检查原版条约定义的覆盖、交叉索引、本地化及占位符。历史黄金文件保留原字节。两个现场分析测试依旧使用实际 Mod。修复的独立审阅补丁 ID 为 `961909e07d1bee3af0dc5bbdaf582f388390d989`。以第二轮的完整结果验证修复后的候选。[黄金回归](../../../tests/test_golden.py)

复验的收集、实际启动和结束均为 12,666 项，1,580 个子测试通过。14 项跳过由 13 项平台条件和 1 项本机未配置官方文档镜像组成，未知跳过为 0。覆盖率门及分模块门均通过，1,483.8 MiB 单 worker 峰值和 2,727.8 MiB 整套峰值满足 1,536 MiB 与 4,096 MiB 的上限。完成报告 SHA-256 为 `c52972707f56d8dcdf20ffefb14b96073f18bff5c35ca2f9e1dc25c7277b805d`。

## 验收范围

本轮设计和文档通过各自的静态核对。生产实现的下一出口是防御条约原版初筛与 `proposal_weight`，依次确证合法读点、本国与对方各自角色、原版实际算子、候选投影及原版后续裁决。局部均值反例和并入成本算例为 `simulation`，实际机制说明和安装盘点为 `snapshot` 或 `static_check`。工程回归覆盖当前生产树。新架构的 E/M 待固定生产包和对应证据。R/U 保持 `unknown`，待固定构建、固定包、适用官方玩法组合及所声明的模式下分别验收实际采纳、后续结果和长期体验。[首片实施方案](../当前工作清单.md#当前设计与下一动作) · [阶段出口](../架构主计划.md#阶段出口) · [工程交付基线](工程基线-1.0.md#验收职责)
