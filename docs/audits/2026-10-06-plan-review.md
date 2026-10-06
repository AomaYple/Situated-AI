# 仓库与执行计划复审（2026-10-06）

## 审计结论与范围

本次复审保留当前通用处境决策方向与既有工程底座，修正执行条件和状态口径。用户进一步要求计划一次定型，因此将[原实施计划](../design/exec/mod重设计-实施计划.md)定为“最终执行纲领 1.0”：固定目标、阶段依赖、验收及变化处理分支，实验参数和当前进度留在结果页，不创建第二份执行计划。

审计覆盖生产数据/生成器、M1–M5 探针和比较器、游戏运行/挂载/恢复、存档迁移、全量分析/快照、工程审计与 CI 入口、测试分层、文档导航、backlog 和忽略边界。通过跟踪文件清单盘点全部顶层区域，结合源代码、测试和实际原始报告逐项核对关键承诺；不宣称逐行重证全部历史文档、第三方虚拟环境或大型二进制。

复审起点为分支 `codex/situational-decision-validation`、HEAD `3742001`，工作树干净。本次只修改文档，没有修改运行器、生成源或游戏目录，没有启动新游戏。下面登记的工程缺口仍待实现，不能把计划落盘写成修复完成。

## 仓库盘点

只读命令使用仓库 `.venv/Scripts/python.exe -X utf8`，读取 `git ls-files -z` 并按顶层路径计数，得到 617 个受控文件：

| 区域 | 文件数 | 作用与本次判断 |
|---|---:|---|
| `src/` | 78 | Python 核心工具；保留稳定分析/快照入口，重点核对行为观测、挂载、迁移和生成边界 |
| `tests/` | 112 | 含106个 `test_*.py`；已有完整回归，但测试数量不能证明游戏行为质量 |
| `tools/` | 139 | CI、探针、基准、剖析和受控快照；发现旧审计脚本仍用迁移前目录 |
| `mod/` | 85 | 新生产源与生成物、旧九国实验隔离；两个扩展开关仍关闭 |
| `docs/` | 189 | 设计、计划、结果、知识库、审计及历史；修复最新基线和阶段顺序矛盾 |
| `research/` | 3 | manifest 与研究入口；本地官方镜像继续不入库 |
| `.github/` | 1 | 三平台/Python矩阵配置；不作为对应平台 GUI 实机证明 |
| 根配置与说明 | 10 | pyproject、依赖锁、编码/忽略配置、说明与许可证；没有本轮新增交付类型需改忽略规则 |

本地 `.venv`、`.git`、测试/静态检查缓存、`.agent-teams`、解析缓存和 `tools/out` 原始证据保持各自用途，未删除、规范化或覆盖原始证据。`.gitignore` 继续忽略机器产物，放行精简快照；本轮没有理由扩大入库范围或清除历史依据。

## 最新完整回归的证据口径

复审之前，用户限定的“格式修复后完整 n-auto”已真正执行，终端最终输出为：

```text
.venv\Scripts\python.exe -m pytest -n auto -q
2494 passed, 10 skipped, 1551 subtests passed in 710.57s
```

2504 是 collected 用例数；1551 subtests 不与 collected 相加。没有失败、worker 崩溃、xdist INTERNALERROR、超时或 watchdog 中止。10项跳过为3项符号链接权限条件、7项本机引擎日志不可用的交叉核验。本次没有 RSS、CPU 或覆盖率采样；pytest-benchmark 在 xdist 下自动禁用是预期，不构成有效基准计时。

`2487/6`、`2489/10`、521.5秒/3646.7 MiB和既有覆盖率结果保留为对应历史测量，不与新结果拼接。修复 README、计划和 backlog 把这些历史读数称为“最新”的冲突；M4 结果中的旧过程保留，并补当前解释。没有为文档修改再运行一次约12分钟的完整回归。

## 关键发现与计划处理

| 发现 | 可核对依据 | 固定处理 |
|---|---|---|
| 最新基线互相矛盾 | 审计前计划第3行2489/10、第38行2487/6；README第234行与backlog第28行仍2487/6 | 记录有日期的测量，不合并覆盖率/内存；纲领中的状态表明确是定型快照 |
| 要求完整机会分母，仪器却明确拿不到 | `src/pdx/natural_probe.py:139` 分母为None；`:141` 说明已接受需求、未成博弈候选、自主性和结果漏项；`tests/test_natural_probe.py:71` 看守这一边界 | M3-B 保持无法判定，先查可测子集/接口；没有新条件时不靠延长窗口重开 |
| 受控响应机会与自然自主机会混用 | `src/pdx/behavior_probe.py:125` 创建博弈；`:237` 起的机会计数与`:254` 起的限制；M3结果第190–206行记录自然分母不足 | 受控样本只证明既定场景响应，不能计算自然发起率；发布候选还需自然形成机会的验证 |
| aggression生成不等于已经有自然发起比较器 | `tools/probe/decision_compare.py:77` 要求aggression一致；`:231` 只有neutrality/fiscal-input两种比较 | 先定义观测与比较契约；未验证字段继续为实验候选或撤下后重新回归 |
| 改财政世界不隔离策略因果 | `src/pdx/decision_probe.py:165` 起扣/加国库；`tools/probe/decision_compare.py:222` 明示原版世界也会改变 | 状态识别/生命周期与固定财政世界的单参数因果分别验证 |
| M4/M5 前置规则与已有实验矛盾 | M4结果已有卸载、稳定性采集和迁移试验，M5已有独立接口实验；旧计划却写所有M4工作必须等M3 | 允许独立安全验证和关闭开关的侦察；正式候选提升与发布仍依赖行为和质量出口 |
| 挂载存在检查不能排除污染 | `src/pdx/game_run.py:554` 起仅用路径子串检查请求存在；`:594` 历史复核沿用原missing_mounts | B137：完整路径精确匹配、允许清单、额外挂载拒绝；历史缺输入记未核验 |
| 旧审计脚本输出空扫描仍退出0 | `tools/probe/audit_repo.py:112` 读tools/pdx，`:113` 读tools/tests；`:125` 起打印零值，`:147` 起基准也由空tests筛选 | B138：改目录、缺失/空扫描失败、标明覆盖率来源时间；不是pdx.repo_audit编码盘点故障 |
| 政治最终概率被写得过于确定 | M5结果旧第7/41/97行将源码基值与贡献写成实际概率/确定合计，但第121行仍承认组合未证明 | 改为源码算术与未核验最终聚合；保留两开关false |
| 发布范围和最终完成定义缺失 | 生产路径启用neutrality/aggression（`mod/decisions/fiscal.toml:12`），M3/M4仍未通过；跨版本输入不合法 | 区分生成候选、有限版本发布和整体目标覆盖；同版本支持与跨版本/旧Mod迁移分别声明 |

### 原始实机报告抽查

只读抽查以下四份 `report.json`，核对 `log_findings`、`source_hashes` 和挂载清单：

- `tools/out/decisions/behavior/control/PRU-FRA/input-no-stress/20261005-155311/report.json`。
- `tools/out/decisions/behavior/neutrality/PRU-FRA/input-no-stress/20261005-155813/report.json`。
- `tools/out/decisions/stability/vanilla/20261005-171001/report.json`。
- `tools/out/decisions/stability/fiscal/20261005-171839/report.json`。

两个响应臂均记录相同六个声明本地候选/探针路径；两份长期报告分别为五个共同探针和另加一个fiscal候选。本次抽查没有发现额外 Workshop 混入，所以 B137 是已确认的门禁能力缺口，不是已证明历史实验被污染。长期两臂原报告仍失败：Script system error 56/55、Assertion 2/2，不能因共同原版错误算作通过。

另只读运行 `tools/probe/audit_repo.py`：实际退出码0，输出“模块0/测试文件0/没有专门测试引用模块0”，基准清单为空；真实 `src/pdx` 为78文件、`tests/test_*.py` 为106文件。文本引用存在也不能代替覆盖率、可达性或性能证明。

## 纲领定型方式

固定的是目标与处理规则，具体运行依据现实输入事前登记。首轮默认两个场景、每场景三组配对、每臂最长六个月；耗尽仍无有效差异则保存阴性/无法判定，换受支持接口，不无限延时。评分、实际响应、有限场景质量分别验收；正常防御/有利行动和不利结果纳入判据，不把更少战争自动称为更合理。

正式 M4 使用冻结候选与预注册 vanilla 噪声/资源预算，早期及真实后期分别配对；后期存档不存在就保留缺口。首次兼容范围按合法证据声明，定型时只有1.14.5新局/同版本重载候选，旧Mod和跨版本升级继续拒绝。政治与市场扩展继续独立M1–M4，未通过则保持关闭。

以后版本升级、接口否证、缺输入、预算调整和工程回归，都通过纲领第0节固定分支推进，更新结果/预注册/backlog。只有用户改变最终目标或基本原则才修订纲领版本。整体完成与有限版本发布分别判断，不能以局部财政闭环代替内部、外部及政治偏好目标覆盖。

## 本次文档验证

本节只记录本轮文档检查，不作为B137/B138修复、M3行为或M4稳定性通过的证据。

- `.venv\Scripts\python.exe -X utf8 -m pytest -n0 -q tests/test_docs_consistency.py tests/test_repo_numbers.py tests/test_repo_hygiene.py tests/test_repository_upgrade.py tests/test_doc_overview.py tests/test_doc_misc.py tests/test_objectives.py -m "not integration"`：139通过、29按范围排除，76.10秒。
- `.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py baseline`：退出0，依赖、快照断言、离线表格、生成一致性、modguard、AI surface、citations、AST死代码候选与发布清单检查通过。死代码结果2156定义：565仅定义文件使用、1011动态入口/API、580在用；这不证明不存在任何不可达代码。
- `.venv\Scripts\python.exe -X utf8 tools/ci/run_check.py encoding`：仓库自有文本 UTF-8 无 BOM / LF 检查通过。
- 本轮13份修改/新增Markdown逐字节编码和147个本地链接检查通过，临时报告为 `tools/out/repository-audit/plan-review-doc-check.json`。
- `git diff --check` 通过；只读复核最终纲领的变化分支、M3预算/出口和M4/M5发布依赖，没有未处理的实质矛盾。

本轮没有新增重复文案的测试，没有重跑完整n-auto，没有采集新的游戏或Python性能读数。B137/B138与行为/质量缺口已经登记，但代码尚未修补，下一次执行从纲领规定的最早可执行项开始。
