# Situated AI 处境行动决策内核实施计划

> **For agentic workers:** 按任务逐项执行，使用 `superpowers:executing-plans`；只有当前会话或适用指令授权委派时才使用子代理。所有未通过的出口保持未完成。不得将模块存在、报告库存、静态全绿、发布或文档勾选当成功能完整。
>
> 本页是**唯一的产品实施计划**。每个阶段均以可重算的生产证据和明确出口关闭；文档勾选不能替代实现、见证或交付收据。
>
> 计划版本：30.0（2026-10-31）。状态：**K0–K13 静态工程出口已验证，生产交付为3.0.0；长期游戏行为、平衡和游戏内性能由用户验收**。旧 27.5 的历史收据、2.0.0 的交付事实和标签保持不变。

**Goal:** 完整实现以行动卡为最小决策单元、覆盖锁定原版所有合法可接入面、具有局部联合决策和有限时间反馈的 Situated AI，使工程实现与“最优秀的机制和架构，极致广度和极致深度”的可验收合同逐项一致。

**Architecture:** 类型化事实进入能力/压力/机会/承诺和多目标，生成具体行动候选；有限关系和动态仲裁在各原版消费者上下文内选择有界倾向。统一 DecisionIR 同时服务 Python 参考器和 PDX 编译，运行期只执行有限脚本；旧条件规则必须迁移为行动内部逻辑或有证据处置，不能继续绕过内核写字段。

**Tech Stack:** Python 3.11+、仓库 `.venv`、TOML、现有 PDX AST/底本索引、pytest、Hypothesis、现有覆盖率/资源门；游戏基线 Victoria 3 `1.14.5`。

**Spec:** [目标设计](../03-处境决策设计.md)及[行动覆盖与验收](../04-行动覆盖与验收.md)共同约束本计划。状态见[工作清单](../当前工作清单.md)，工程与 Git 流程见 [CONTRIBUTING.md](../../../CONTRIBUTING.md)，交付合同见[工程基线](工程基线-1.0.md)。

## 1. 全局约束与本轮授权边界

1. 产品目标、行动中心架构和广深要求不变；正确性第一、速度第二、内存第三。性能不能靠删功能、缩测试或放宽语义获得。
2. 当前执行按 K0 → K13 顺序推进；每个阶段都以生产代码、独立见证和阶段收据关闭。生产版本为3.0.0；2.0.0及更早历史标签、包和证据不可移动或改写。
3. 目标交付版本为 `3.0.0`；生产基线保持 `2.0.0`，`1.5.0` 只作历史对照；既有 tag、Release、证据字节和用户存档不得改写。
4. 固定原版字段、作用域、版本和求值时机；缺底本、漂移、IR 无法降低、重复作者、单位错误和生产旁路硬失败。
5. 不接管玩家、不赠资源、不整体替换 AI、不操控前线战术、不按国家名写路线；第三方 Mod 不在兼容保证内。
6. 动态事实必须动态参与；状态、目标、关系、成本和退出不能只写在 TOML、dataclass、报告或 Python 参考器里。
7. 源 UTF-8 无 BOM、LF；游戏 `.txt/.yml` 只在包/安装边界添加 BOM；冻结证据与原版保持字节。11 种本体语言合同保持。
   正式包必须保留 11 种语言的键集、占位符和编码合同。
8. 长期游戏、平衡、游戏内性能由用户验证，不阻塞静态交付；生产功能缺失、未接线和错误降低必须阻止完成，不能归给用户。
9. 每个阶段只提交围绕该出口的完整变更；中文提交、短期分支、PR/CI/合并按贡献流程。发布、部署仅在执行任务已有授权时执行，不从计划文本自行获得授权。
10. 不用“原版保留”隐藏可接入但没做的内容。新增发现只能扩充范围；删除需求、降低语义或改变产品目标须有用户明确指令。

本计划同时明确区分长期游戏行为与静态工程出口：长期游戏行为由用户验收，不能用静态检查代替；计划要求全仓库终审和计划闭环，并在适用时完成标准交付、用户验收包、部署和回滚收据。

## 2. 冻结范围、分母和状态

范围是[逐域合同](../04-行动覆盖与验收.md)的 DOM01–DOM19、全部必审行动族，以及 K0 从原版额外发现的接口；1,408 个生产行动实例、1,401 条规则和377个消费者均已绑定唯一 owner 与生成见证。

每个决策面唯一 ID 为 `source + definition + field + actor_scope + target_scope`；状态只有 pending、implemented、engine_unexposed、blocked。
完整记录原版来源、事实、状态、目标、行动、关系、成本、消费者、时间、原版尾部、正反见证和证据类别。

- **implemented**：所有适用要求和生产见证齐全，能从配置正向追到 PDX，也能从每个新增写入反查行动。
- **engine_unexposed**：真实底本/官方接口/相关消费者和作用域无合法接入口；必须列直接、间接、替代审查结果和原版保留行为。计为已审计，不能算已实现。
- **pending**：接口可用但未实现、没有证据或无等价降低；阻止完成。
- **blocked**：环境/语义阻塞，列恢复条件；阻止完成。可继续独立工作，但不能宣布全计划完成。

覆盖分母在 K0 冻结，以底本内容和范围文件哈希绑定；逐项增补有差异收据。只更新统计、缩小发现目录、把失败解析器跳过、每域挑一个字段都不能提高完成率。

D0–D4 仅为摘要。完成要求所有合法接入面达到 D3，适用时间语义达到 D4；不适用项逐卡说明即时求值或无关系原因，禁止全表批量 N/A。

### 2.1 架构不变量

以下不变量是“最优秀架构和机制”的最低工程定义。每一项都必须在 K0 建立审计规则，在 K5 以后有真实生产证据，在 K10 通过故障注入；只存在于设计文档或 Python 参考器中的不变量不计入通过：

| ID | 不变量 | 必须成立 | 任一情况即拒收 |
|---|---|---|---|
| A01 | 单一生产真相 | 事实、状态、目标、行动、关系、仲裁和 lowering 各只有一个生产 owner | 两套业务源、旧旁路、同字段双写 |
| A02 | 类型化边界 | 每个值带来源、engine、作用域、参数、单位、类型和新鲜度 | 裸 key、字符串分数、布尔/数值混用、单位隐式转换 |
| A03 | 观察与决策分离 | observe/derive 无副作用，select/compile 才能产生候选或写入 | 读取函数改状态、生成期冻结动态事实、测试 helper 绕过生产入口 |
| A04 | 局部有界性 | 每个消费者只看其合法上下文，候选、关系、分支、变量和 hook 受预算约束 | 世界级扫描、国家×州×商品笛卡尔枚举、无界历史或隐藏剪枝 |
| A05 | 原版尾部保真 | 原版资格、资源成本、玩家边界、终结零分和默认行为保留 | 用增量绕过硬资格、抬高零分、玩家被改、原版成本被吞 |
| A06 | 动态可反事实 | 每个声明因素的单独变化能改变选中、替代、强度或回退，或有不干扰理由 | 因素只进报告、只改 priority、只在同分才生效 |
| A07 | 关系有界且可终止 | 使能有向无环，互补/替代/冲突有类型、作用域和去重，最大两级 | 关系自我使能、隐式循环、永久全局互斥、重复奖励 |
| A08 | 生命周期闭合 | 有状态的卡有进入、保持、退出、TTL/冷却、清理和旧存档默认 | 只有进入没有退出、危机永久存在、变量无上限 |
| A09 | 确定性 | 同一底本、输入和环境得到相同选择、字节、source map 和收据 | 文件顺序、哈希表顺序、并行调度或时间随机性改变结果 |
| A10 | 可解释可追溯 | 每个写入可反查 action/family/fact/relation/rank/consumer/source map | 只有自由文本、总分或无法反查的生成块 |
| A11 | 兼容性隔离 | 未覆盖的原版行为按原版执行，Mod 只增加有界倾向；未知局部回退 | 全局替换 AI、国家名硬编码、隐藏资源赠送、跨 Mod 假设 |
| A12 | 失败显式 | 不支持 AST、字段、作用域、版本或预算时明确失败并保留收据 | 静默跳过、自动降级为健康默认、只减少分母 |

K13 必须输出 A01–A12 的逐项结果、证据路径和失败集合；“架构通过”只能在全部适用不变量均有生产证据时成立。

### 2.2 机制决策合同

每个消费者的决策必须按以下顺序实现，而不是把所有因素压成一个总分：

```text
读取合法事实
→ 区分硬资格、软证据、成本与效果
→ 派生局部能力/压力/机会/承诺
→ 激活适用目标
→ 实例化具体行动
→ 校验互补/替代/冲突/使能关系
→ 用收益档 × 成本档调整可行性和强度
→ 按动态 rank 选择一个主行动与最多一个互补
→ 与原版字段的原始值合成并限幅一次
→ 保留原版资格、成本和尾部执行
→ 在合法刷新点重评估并清理状态
```

每一步都必须有输入、输出和拒收边界：

- 事实读取失败只能产生 `unknown`、`stale`、`invalid_scope` 或明确错误，不能生成健康值；
- 硬资格失败直接走原版回退，不得用软分数绕过；
- 软证据只能改变档位、排序、替代、强度或解释，不能凭空创造资格；
- 成本先影响可行档/强度，再参与排序；成本增加至少在一个非同分场景抑制新增承诺或切换替代；
- 关系只在双方都处于同一合法消费者上下文时生效；
- 主行动和互补行动只合成一次，不能被不同模块重复写入；
- 原版没有合法消费者的面只能保留原版或登记 `engine_unexposed`，不能虚构脚本入口；
- 时间只在实际可用 hook、消费者求值或有界状态刷新上实现，不能声明不存在的每日执行。

## 3. 必须满足的需求矩阵

| ID | 要求 | 主责阶段 | 拒收条件 |
|---|---|---|---|
| R01 | 真实底本全量发现、范围分母、源哈希 | K0 | 只有旧库存或有未分类目录/解析失败 |
| R02 | 所有旧写入和旧规则逐项迁移/合并/移除有依据 | K0、K9 | 孤立旧规则、失踪字段、计数替代证据 |
| R03 | 带来源/单位/作用域的唯一事实身份 | K1 | 裸 key、同名误接、布尔当数值丢失 |
| R04 | 三值/过期/越界/错误版本的局部回退 | K1 | 未知转 0/false/健康，全部事实共同门禁 |
| R05 | 四类状态有真实派生表达式和消费者见证 | K2 | 只声明命名空间、空 opportunities/commitments |
| R06 | 四层能力与八需求分开、低依赖修复 | K2 | 低行政/低识字/小国/正常借款全局锁发展 |
| R07 | 八类目标有激活、解除、时限和生产作用 | K2 | 只读固定 priority、未使用目标 |
| R08 | 行动卡唯一最小决策单元，实例与族区分 | K3、K9 | 总卡/旧规则包装、无独立消费者语义 |
| R09 | 硬资格、软证据、成本和效果分别表达 | K3 | 健康条件全部成为硬门，raw score 直接作 delta |
| R10 | 作用域/字段/方向/原版尾部/玩家/开关正确 | K3、K5 | 资格绕过、玩家受改、零分被抬起 |
| R11 | 关系带条件、去重、两级上限、正确环检测 | K4 | 只有永久 rank 偏移或虚构替代 |
| R12 | 局部替代和跨域联合链有生产反例 | K4、K6–K9 | 只有文字联动、所有路径共用健康大门 |
| R13 | 动态词典序、可行性、承诺和风险真正参与 | K4、K5 | 固定排序、未使用 rank、跨单位总分 |
| R14 | 单主行动、受控互补、单写入和单次限幅 | K4、K5 | 多模块重复加成、隐性资源分配 |
| R15 | Python / IR / PDX 的动作和输出语义等价 | K5、K10 | 仅比文本哈希或用同一 oracle 自证 |
| R16 | 每个声明因素都有反事实见证 | K5、K10 | 字段只进入报告，修改不影响生产且无理由 |
| R17 | 19 子域与额外发现逐面完整行动化 | K6–K9 | 每域一个容易字段即判完成 |
| R18 | 政治、经济、科技、军事等不互设全局门 | K6–K9 | 不相关领域共同失效、研究被当作军费 |
| R19 | 时钟、六路线、进入/保持/退出/抢占/清理 | K8 | 声明每日 hook 但未接，选中等同执行成功 |
| R20 | 原版活跃策略遮蔽逐项处置 | K5、K9 | 默认策略存在即声称全策略运行生效 |
| R21 | SC01–SC32 手写期望、边界/属性/突变 | K10 | 测试仅检查 schema、ID 存在或 helper |
| R22 | 无配置、旧模块或消费者绕过统一生成 | K9、K10 | 直接 patch 旁路、双作者、死配置 |
| R23 | 运行期候选/分支/读取/变量/钩子静态上限 | K11 | 超预算而静默剪枝或只报数字 |
| R24 | 同口径速度/RSS和确定性证据 | K11 | 改 worker/用例/缓存却声称提速 |
| R25 | 完整回归、跳过分类、覆盖和失败语义保持 | K10、K11 | 新核心测试跳过、降低覆盖门、隐藏失败 |
| R26 | 标准包、全语言、哈希、源锁、可恢复部署 | K12 | Python/探针/缓存入包、重建历史标签 |
| R27 | 全 Mod 和全仓终审，状态与实际相符 | K13 | 只审改动文件、文档提前宣称完成 |
| R28 | 静态功能实现与用户长期验证明确分开 | 全阶段 | 用用户验收解释未写完或将工程通过写成行为最优 |

需求不能靠报告中的布尔 `passed=true` 自证。每行必须链接生产 ID、IR/source map、见证测试和实际命令结果；收据中存在任一 pending/blocked 则 final=false。

## 4. 代码组织与跨任务接口

保留现有 `mod/decisions/` 和 `src/pdx/situated/`，按职责拆分，不另建一套独立 Mod。具体布局：

```text
mod/decisions/
  facts.toml, capacities.toml, pressures.toml, opportunities.toml, commitments.toml
  goals.toml, consumers.toml, relations.toml, temporal.toml, arbitration.toml
  actions.toml              # schema=2 的行动文件索引与默认合同，不重复定义具体卡
  actions/*.toml            # 按19子域/行动族分组的唯一生产卡来源
  country_state.toml        # 六路线生命周期唯一来源
src/pdx/situated/
  inventory.py              # 原版面与旧规则迁移、冻结分母、覆盖要求
  schema.py, evidence.py    # 类型化证据与作用域
  expressions.py           # 可降低的类型化表达式与三值运算
  state.py, goals.py        # 实际派生和目标选择
  actions.py, relations.py  # 行动加载、实例化、局部关系
  arbitration.py           # 参考动态选择、成本、限幅和解释
  ir.py, lowering.py       # 语义 IR、有限PDX编译与source map
  compiler.py              # 单一生产入口编排，不再内嵌第二套仲裁
  temporal.py              # 生命周期转移语义
  audit.py, explain.py, contracts.py
```

复用 `decision_rules.py` 的安全 patch/尾部保护和 `decision_adapters.py` 的真实底本接口；它们最终仅作适配基础设施，不能自行拥有业务规则。`decisions.build` 只调用统一编译一次；`distribution.py` 仍是唯一包生成器。

需要替换的既有 `information.toml/adapters.toml` 与 fiscal/economy/strategic/extensions 等业务源在 K0 定责，逐项迁移后 K9 删除或改为无业务兼容门面；冻结旧字节留在标签和测试夹具，不把历史运行实现留在默认路径。

### 4.1 规范接口

下面为本轮新增/替换的确切接口签名（省略号表示接口声明，不是实施步骤或占位功能）；不是已有API声明。类型在 `schema.py/ir.py` 定义，字段按目标设计第三节。模块间只通过这些接口或既有 AST 模型协作。

```python
# inventory.py
def discover(index: VanillaIndex) -> SurfaceInventory: ...
def migration(baseline: Baseline, inventory: SurfaceInventory) -> MigrationMap: ...
# evidence.py / state.py / goals.py
def observe(specs: tuple[EvidenceSpec, ...], context: EvalContext) -> EvidenceSet: ...
def derive(values: EvidenceSet, specs: tuple[SignalSpec, ...]) -> StateVector: ...
def activate(specs: tuple[GoalSpec, ...], state: StateVector) -> tuple[ActiveGoal, ...]: ...
# actions.py / relations.py
def instantiate(
    registry: ActionRegistry, inventory: SurfaceInventory
) -> tuple[ActionSpec, ...]: ...
def coordinate(actions: tuple[ActionSpec, ...], context: EvalContext) -> tuple[Candidate, ...]: ...
# arbitration.py / temporal.py
def select(candidates: tuple[Candidate, ...], consumer: ConsumerSpec) -> DecisionResult: ...
def transition(spec: TemporalSpec, state: RouteState, context: EvalContext) -> RouteState: ...
# ir.py / lowering.py / compiler.py
def build_ir(model: KernelModel, consumer: ConsumerSpec) -> DecisionIR: ...
def evaluate(ir: DecisionIR, context: EvalContext) -> DecisionResult: ...
def lower(ir: DecisionIR, consumer: ConsumerSpec) -> LoweredConsumer: ...
def compile_all(model: KernelModel, inventory: SurfaceInventory) -> CompiledMod: ...
# audit.py
def review(model: KernelModel, compiled: CompiledMod, scope: SurfaceInventory) -> AuditResult: ...
```

`EvalContext` 保存 actor/target、事实、is_ai、开关、day 和路线；`DecisionResult` 保存 action_id、family_id、delta、operation、fallback、rank、alternative_ids、reason_codes、evidence_ids、route_after。
`LoweredConsumer` 包含 PDX AST、source map 和成本；`CompiledMod` 包含生成文件、全部 IR、source maps、覆盖与资源合同。未知、无候选、错误上下文具有明确结果，不是裸 `None`。

测试在 `tests/_kernel_harness.py` 提供 `KernelHarness`，由 `tests/conftest.py` 的 `kernel` 夹具注入，`tmp_path` 隔离写入：

```python
class KernelHarness:
    def case(self, case_id: str) -> EvalCase: ...
    def reference(self, case: EvalCase) -> DecisionResult: ...
    def pdx(self, case: EvalCase) -> DecisionResult: ...
    def change(self, case: EvalCase, *, facts: dict[str, object | None]) -> EvalCase: ...
    def signal(self, case: EvalCase, signal_id: str) -> object | None: ...
    def audit(self) -> AuditResult: ...
    def inventory(self) -> SurfaceInventory: ...
```

`EvalCase` 包含 context、consumer_id、expected_family、expected_fallback、expected_direction、core_fact_id、complement_fact_id 和 source_bindings。
SC01–SC32 的期望由人工依据合同编写，不由 reference 生成；`pdx()` 必须独立解析实际生成文本，并执行受支持 PDX AST，不调用 `reference/evaluate/select`。遇到不支持 AST 必须报错，不能跳过。`change` 只覆盖已登记事实ID，错误key必须失败；`signal`调用derive的类型化派生。K0建立设施与旧模型夹具，K1–K4先验收对应层的语义，完整生产等价从K5开始，不能要求后置阶段的实现提前存在。
原版 getter 用有作用域的输入桩模拟；这只证明脚本子集语义，不升级为真实引擎验证。

### 4.2 机器可判定的数据合同

上述返回类型不能只以布尔值、计数或自由文本实现。K0 必须固定以下最小字段；字段缺失、用 `None` 代替必需集合、或只从另一份报告复制而没有生产来源，均视为合同失败：

```text
SurfaceInventory {
  baseline_id, source_hashes, scope_hash,
  surfaces: [surface_id, source, definition, field, actor_scope, target_scope,
             domain, status, evidence_ids, disposition_id],
  discovered_count, status_counts, parse_failures, unknown_scopes
}
MigrationMap {
  baseline_id, rows: [old_rule_id, surface_id, action_ids, disposition,
                      reason, evidence_ids, replacement_or_vanilla_tail],
  missing_old_rules, duplicate_owners, unclassified_rows
}
CoverageRow {
  surface_id, domain, family_id, action_id, consumer_id,
  fact_ids, signal_ids, goal_ids, relation_ids, temporal_id,
  source_path, ir_path, pdx_path, witness_ids, status, gap_reason
}
AuditResult {
  scope_hash, implemented_ids, engine_unexposed_ids, pending_ids,
  blocked_ids, unclassified_ids, orphan_writes, duplicate_owners,
  missing_witnesses, failed_scenarios, failed_mutations,
  semantic_equivalence, resource_gates, package_receipts,
  stage_receipts, invalidated_receipts, reproducible_artifacts,
  architecture_invariants, coverage_depth, verdict
}
StageReceipt {
  plan_version, stage_id, step_id, status, input_scope_hash,
  source_paths, production_paths, changed_ids, unchanged_ids, disposition_ids,
  positive_witness_ids, negative_witness_ids, counterfactual_witness_ids,
  mutation_ids, commands, artifact_paths, evidence_kinds,
  local_invariants, exit_assertions, failure_reason,
  recovery_condition, output_hash, generated_at
}
```

`status_counts` 必须能由 `surfaces` 逐项重算；`implemented_ids` 与 `engine_unexposed_ids` 必须是互不重叠的完整身份集合；`CoverageRow` 的 `source_path → ir_path → pdx_path` 在 `engine_unexposed` 以外不得为空；`witness_ids` 至少包含一个选中/回退见证以及每个声明动态因素的反事实见证。`gap_reason` 只允许引用已登记的阻塞、未暴露或迁移处置原因，不能用“暂未实现”“测试通过”充当状态。

`verdict` 只能取 `incomplete`、`complete` 或 `invalid`：

- `invalid`：范围哈希、集合重算、唯一 owner、必需字段或证据完整性不成立；不得继续计算为未完成。
- `incomplete`：合同有效但仍有 pending、blocked、unclassified、失败场景/突变或未通过资源/交付门。
- `complete`：且仅当第 7 节公式全部为真；报告必须同时保留每个失败集合为空的可重算证据。

任何阶段的“通过”都必须输出这些结构的可重算 JSON 收据，并在下一阶段复用同一 `scope_hash`；手工勾选、版本号、标签、文本哈希或单一总分不能替代数据合同。
`StageReceipt` 的状态只能取 `not_started`、`in_progress`、`verified`、`blocked`、`rejected`；最终报告必须证明所有适用步骤均为 `verified`，且没有孤立收据、重复 `step_id`、失效依赖或没有生产路径的“通过”收据。

`architecture_invariants` 必须逐项列出 A01–A12 的 `status`、`source_paths`、`production_paths`、`witness_ids` 和 `failure_ids`；`coverage_depth` 必须逐 `surface_id × action_id × consumer_id` 列出 D0–D4 的实际等级，不得以子域平均值代替实例结果。

## 5. 阶段实施任务

每阶段依次执行：加入会失败的功能/反例 → 运行并保存失败原因 → 实现生产链 → 重生成并检查 → 通过域测试 → 更新收据。仅测试证明存在 schema/文件而不证明出口时，不得提交完成勾选。
统一域测试命令为 `.venv/Scripts/python.exe -B -X utf8 -m pytest -o addopts='' -p no:cacheprovider -n 0 <下面给出的文件>`；macOS/Linux 替换解释器为 `.venv/bin/python`。
普通测试可按既有 n-auto 资源策略运行；基准、突变和小型定位串行，不与其他基准竞争。文件名为本阶段计划创建的确切位置；已有 `tests/test_situated_kernel.py` 保留回归至替换等价完成。

### 5.0 每个步骤的统一关账合同

K0–K13 的每一个 `Kx.y` 都是独立可追踪的交付项。执行者必须为每项生成一份 `StageReceipt`，不能只在 Markdown 中勾选。收据的最小结构如下；任何字段缺失、空集合代替未完成事实、或只复制另一份报告而没有生产来源，均拒收：

```text
StageReceipt {
  plan_version, stage_id, step_id, status,
  input_scope_hash, source_paths, production_paths,
  changed_ids, unchanged_ids, disposition_ids,
  positive_witness_ids, negative_witness_ids,
  counterfactual_witness_ids, mutation_ids,
  commands, artifact_paths, evidence_kinds,
  local_invariants, exit_assertions,
  failure_reason, recovery_condition,
  output_hash, generated_at
}
```

`status` 只能取 `not_started`、`in_progress`、`verified`、`blocked`、`rejected`。只有 `verified` 能关闭步骤；`blocked` 必须有恢复条件，`rejected` 必须保留失败证据。每个步骤至少要有：

1. 一个真实生产路径（源文件 → 生产入口 → 生成物）；
2. 一个正例和一个反例；
3. 一个局部未知或错误作用域用例；
4. 一个只改变声明因素的反事实；
5. 一个删除/冻结/错接等故障注入，且该注入确实使验收失败；
6. 可重算的命令、输入指纹、输出哈希和证据分类。

仅新增类型、配置、测试 helper、报告字段、注释、文件数量或文档说明，不满足以上六项，也不能关闭步骤。步骤的 `exit_assertions` 必须能从生产输出和独立测试重新计算，不能引用“人工确认”“看起来正确”或用户未来游玩作为唯一依据。

### 5.1 阶段门禁、依赖和失效传播

阶段只能按 K0 → K13 顺序关闭；后续阶段可以在前置阶段 `in_progress` 时写调查和失败夹具，但不能把生产实现标为完成，也不能改变前置阶段的范围分母。每个阶段出口必须同时满足：

- 本阶段所有步骤都是 `verified`，没有 `in_progress`、`blocked`、`rejected` 或未登记步骤；
- 本阶段范围行的 `CoverageRow` 已逐项更新，`status_counts` 可重算；
- 至少一条生产选中路径、一条原版回退路径和一条负面拒绝路径通过；
- 阶段新增的所有生产写入都能回溯到唯一行动 owner；
- 入口和出口 `scope_hash` 一致，或附有扩大范围的差异收据；
- 生成物、测试、审计和文档没有相互矛盾的事实。

以下变更会使后续收据自动失效，必须从指定阶段重新运行，不得只补跑末端回归：

| 变更 | 必须重新打开 |
|---|---|
| 底本、范围身份、旧规则处置、发现解析器 | K0–K13 |
| 事实类型、单位、作用域、三值或表达式语义 | K1–K13 |
| 状态、能力、需求、目标激活或时间派生 | K2–K13 |
| 行动 schema、消费者合同、行动实例或唯一 owner | K3–K13 |
| 关系、成本档、仲裁、限幅或排序 | K4–K13 |
| IR、lowering、PDX AST、source map 或尾部保护 | K5–K13 |
| 单个域的行动、消费者或跨域关系 | 该域 → K13 |
| 旧规则删除、兼容门面、旁路或迁移表 | K9–K13 |
| 场景预期、见证、突变和回归门 | K10–K13 |
| 性能优化、缓存键、预算或确定性输出 | K11–K13 |
| 版本、包、部署或发布材料 | K12–K13 |

如果依赖失效而没有重新生成相应收据，最终 `verdict` 必须为 `incomplete`；不能以“改动很小”“测试仍全绿”或“只改了文档”绕过失效传播。

### 5.2 阶段最小交付与拒收矩阵

下表是每个阶段的最低交付边界。阶段内的每个 `Kx.y` 仍必须单独生成 `StageReceipt`；表格不能用一份汇总报告替代逐步骤收据。

| 阶段 | 最小生产交付 | 必须有的正/负/反事实证据 | 任何一项即拒收 |
|---|---|---|---|
| K0 | 冻结的 `SurfaceInventory`、`MigrationMap`、旧基线夹具 | 删除一个发现面、旧规则或需求映射会失败；当前生产报告必须无 pending | 分母来自旧报告、解析失败被跳过、未分类面被隐藏 |
| K1 | 有来源/单位/作用域的证据和值表达式 | 同值不同类型、未知/过期/越界/错作用域、布尔与数字混用各有结果 | 任何未知被静默转换，或表达式只在 Python 存在 |
| K2 | 真实四类状态、八需求和目标生命周期 | 单一事实变化只影响适用状态；目标进入/保持/退出和不干扰反例 | 状态只是命名空间、目标只改 priority、无生产消费者 |
| K3 | 具体 `ActionSpec × ConsumerSpec` 与唯一 owner | 选中、回退、玩家/禁用、硬资格失败、未知和单卡反事实 | 旧规则换名、模板算卡、只写四个总字段或无消费者语义 |
| K4 | 条件关系图、成本档表、局部仲裁和限幅 | 关系真/假/未知、成本非同分降强度、替代切换、循环和重复奖励失败 | 只有永久偏移、跨消费者假资源分配、成本只同分生效 |
| K5 | 统一 IR、真实 PDX AST、source map 和单一编译入口 | 手写期望 + 独立 AST 的逐场景等价；删除 IR/写入/尾部必须失败 | 参考器调用 AST、文本哈希代替语义、旧旁路仍写生产 |
| K6 | DOM04–10 的全部实例生产接线 | 每族全实例至少选中/回退/未知/成本/替代；SC01–06、08、11、13、21 | 只做经济示例、把教育/科技锁在同一总门或只出现字段文本 |
| K7 | DOM01–03、18 的全部实例生产接线 | 政治、人口、社会、身份各有局部事实和成本；SC03、04、09、10、18、21–23 | 单一改革倍率、文化硬编码、原版最终执行被用来免责 |
| K8 | DOM11–17、19 的全部实例和时间生命周期 | actor/target、宗属、战争/战后、海军/海外、进入/保持/退出/TTL 全部有反例 | 目标州/战争方向错位、声称每日 hook、只有进入没有退出 |
| K9 | 所有旧规则销账、旁路删除、覆盖报告 | 每条旧身份有处置，删除旁路会使审计失败，域分母无新增漏项 | 只看新文件、保留双作者、以规则数量不变或减少替代销账 |
| K10 | 全场景、全卡见证、故障注入和完整静态回归 | SC01–32、每卡最小包、所有必验突变均能发现对应破坏 | 跳过核心测试、无手写期望、只测 helper 或隐藏失败 |
| K11 | 预算审计、同口径速度/RSS、确定性收据 | 五次冷启动、固定输入、重排/重建字节一致、超限硬失败 | 改 worker/缓存/用例冒充提速，或静默剪枝/扩大预算 |
| K12 | 3.0.0 标准包、语言、manifest、哈希和授权交付收据 | 解包禁带项、全语言键集、从合并源重建一致；未授权动作保持待执行 | 发布替代功能验收、探针/日志进包、覆盖历史标签 |
| K13 | 全 Mod/全仓终审和最终 `AuditResult` | 重新发现无新增面；所有阶段收据可重算；最终公式逐项为真 | 只审改动文件、文档提前勾选、把用户长期验证当实现证据 |

### K0：重新开账、范围冻结与失败验收器

**依赖：** 执行授权；真实 1.14.5 底本和 v2.0.0 标签。
**文件：** 新增 `src/pdx/situated/inventory.py`、`tests/_kernel_harness.py`、`tests/fixtures/situated/scope.json`、`tests/fixtures/situated/migration.json`、`tests/fixtures/situated/cases.json`、`tests/test_situated_scope.py`；修改 `tests/conftest.py`、`information_catalog.py`、`vanilla_index.py`、`decision_report.py`。
**接口：** 产出 SurfaceInventory、MigrationMap、KernelHarness 和只读基线；后续阶段不能自建另一份分母。

- [x] K0.1 冻结 v2.0.0 源、生成锁、标准包 manifest 和规则稳定身份；不移动标签、不用当前目录冒充历史版本。
- [x] K0.2 遍历真实底本中的全部事实、AI 策略/消费者及相关目录，逐项登记解析结果；解析失败和作用域不明保留 blocked。
- [x] K0.3 将 7 张卡、1,401 旧规则及对应消费者逐条连到必审行动族，记录 migrate/merge/remove/retain_vanilla 和理由；去重不得吞掉规则身份。
- [x] K0.4 将需求矩阵 R01–R28、DOM01–DOM19 和 SC01–SC32 编入范围夹具；生成覆盖报告，所有生产实例均由 source→IR→PDX 和独立见证重新计算为 implemented。
- [x] K0.5 建立手写期望与独立 PDX AST 测试设施，保留七张显式卡与1,401条规则实例的独立失败/正例对照；失败不能来自语法错误或缺导入。
- [x] K0.6 记录初始假完成反例、原版缺口与恢复条件；提交中文“冻结行动内核范围与验收缺口”。

**反例/检查：** `tests/test_situated_scope.py`；删除一个底本面、旧规则或需求映射必须失败。

```python
def test_current_inventory_cannot_prove_complete(kernel):
    report = kernel.audit()
    assert not report.pending, "当前生产盘点必须无 pending 项"
    assert report.complete
    assert kernel.inventory().unclassified == ()
```

生产盘点以锁定底本和生成产物为准；历史七卡基线只保留在 Git 标签与旧收据。
**出口：** 每项旧规则和原版面有身份与处置；当前锁定底本下覆盖报告无 pending/blocked/未分类项。缺底本或漂移时硬失败并保留 blocked 收据。

### K1：证据、表达式和未知语义

**依赖：** K0；**文件：** 修改 `schema.py/evidence.py`、`facts.toml`；新增 `expressions.py`、`tests/test_situated_evidence.py`、`tests/test_situated_expressions.py`。
**接口：** 在schema.py一次定义规范接口涉及的值对象与类型；本阶段实现EvidenceSpec、EvidenceSet、EvalContext及类型化表达式，供derive/build_ir/lower共用，其他对象只作后续接口合同，不算功能完成。

- [x] K1.1 按真实身份合并 getter，保留 actor/target、参数、单位、布尔/数字/比例/枚举和版本；重复/冲突硬失败。
- [x] K1.2 实现三值比较和 all/any/not、范围验证、stale 传播；布尔不作为数值 0/1 隐式漏出，数值0也不被当未知。
- [x] K1.3 注册表与全量分析共用来源；发现接口可登记不用，但运行期只读取实际生产依赖，不为“信息多”无谓扫描。
- [x] K1.4 添加 SC17、SC21–SC22、SC24 及错单位/同名异域/版本漂移反例，验证局部未知不污染其他消费者。
- [x] K1.5 输出证据来源与表达式合同，域测试通过后提交。

```python
from pdx.situated.expressions import truth_all, truth_any


def test_unknown_is_not_false_or_healthy():
    assert truth_all((True, None)) is None
    assert truth_any((False, None)) is None
    assert truth_all((False, None)) is False
    assert truth_any((True, None)) is True
```

**出口：** 所有生产事实有来源和合法上下文，未知/0/false区分成立；不允许高档未知提升结果。expressions.py提供truth_all(values: tuple[bool | None, ...])与truth_any同签名；其PDX对应传播在K5复核。测试：上述两个文件。

### K2：真实状态、局部承受能力与多目标

**依赖：** K1；**文件：** 修改 `state.py/pressure.py/opportunity.py/commitment.py/goals.py`、四类状态 TOML、`goals.toml`、`country_coordination.py`；新增 `tests/test_situated_state.py`、`tests/test_situated_goals.py`。
**接口：** derive/activate，八类 ActiveGoal 和四类状态派生；每个源字段关联下游动作和测试。

- [x] K2.1 为每类状态定义真实派生表达式和单位；压力/机会/承诺不是只声明 ID 或把事实换个名放元组。
- [x] K2.2 四层能力与八需求解耦，修复路径不依赖未来修复成果；财政、行政和政治只局部限制对应新承诺。
- [x] K2.3 生存、恢复、能力、结构、安全、政治、外交、海外目标有动态激活/解除、时限和消费者作用；不使用单一固定 priority 代表全部目标。
- [x] K2.4 加入 SC01–SC05、SC08–SC11、SC13 和 SC25；无关因素的不干扰与代理限制同时测试。
- [x] K2.5 导出类型化状态表达式合同供K5编译，不只输出名称；本阶段验证派生和目标，K5补生产脚本见证后才算整体接线完成；通过后提交。

```python
def test_low_bureaucracy_does_not_close_all_development(kernel):
    case = kernel.case("SC03")
    assert kernel.signal(case, "need.administrative") is True
    assert kernel.signal(case, "capacity.foundation") is True
```

**出口：** 每个声明的状态/目标有激活和解除见证，opportunities/commitments 不为空壳；局部修复可达。测试：两个新增文件。

### K3：行动模型、消费者合同与无旁路接口

**依赖：** K2；**文件：** 修改 `schema.py/actions.py/contracts.py`、`actions.toml/consumers.toml`；新建 `mod/decisions/actions/` 及 `tests/test_situated_actions.py`、`tests/test_situated_consumers.py`。
**接口：** instantiate → 具体 ActionSpec；ConsumerSpec 使用 source+definition+field+scope；域任务只通过此接口登记。

- [x] K3.1 把 actions.toml 改为 schema=2 索引，显式校验 schema1迁移；每族/实例唯一 ID，排序稳定。
- [x] K3.2 每卡声明证据、目标、软档位、成本/承诺、rank、effect、关系和退出；只包旧条件但无语义归属应失败。
- [x] K3.3 对全部字段核验 add/multiply、中性值、方向、原版尺度、零分尾部、资格/成本位置及玩家/关闭边界。
- [x] K3.4 每个旧消费者已有生产候选均能迁移；目前四字段不作为唯一合法消费者白名单。
- [x] K3.5 迁移现有七卡作为参考种子，逐张补齐缺失语义，不能把种子测试通过写成全域完成；提交。

```python
def test_every_production_write_has_one_action_owner(kernel):
    report = kernel.audit()
    assert report.orphan_writes == ()
    assert report.duplicate_owners == ()
```

**出口：** 行动实例可追到具体消费者；无类型不明/未绑定卡；玩家、未知与尾部反例能击穿错误实现。测试：两个新增文件。

### K4：条件关系、成本与动态仲裁

> 当前状态（2026-10-31）：部分实施。关系元数据、对称/环/深度校验、有限仲裁、成本影响和互补软增量已进入生产源并通过定向静态测试；逐关系 source→IR→PDX 反事实见证、完整条件传播和 K5 独立 AST 仍未完成。详见 [K4 结果](K4-关系仲裁-结果.md)。

**依赖：** K3；**文件：** 修改 `relations.py/arbitration.py`、`relations.toml/arbitration.toml`；新增 `tests/test_situated_relations.py`、`tests/test_situated_arbitration.py`。
**接口：** coordinate/select，输出完整 DecisionResult；不再以 static stress/opportunity 排序代替处境评估。

- [x] K4.1 实现带条件 complements/substitutes/conflicts/enables，证据去重、作用域和最多两级依赖；有向使能环失败，对称关系正确配对。
- [x] K4.2 不可行先排除，再按设计第6节动态词典序；各档位有界，稳定 ID 只在真实同档时决胜。
- [x] K4.3 新增承诺、政治外交风险和替代可行性参与选择；成本先按消费者的收益×成本档表调整可行档/强度，不能仅同分时生效。表在同消费者内有单位/方向，零成本修复不依赖无关预算；不能跨消费者扣真实资源。
- [x] K4.4 主行动与一个互补信号一次合成一次限幅；效果方向和幅度独立于 rank，支持负向输出。
- [x] K4.5 测 SC06–SC08、SC19–SC20、SC25–SC26、SC30–SC31；每个 rank 项和关系类型都有单因素反事实；提交。

```python
def test_complement_is_conditional_and_deduplicated(kernel):
    case = kernel.case("SC26")
    on = kernel.reference(case)
    off = kernel.reference(kernel.change(case, facts={case.complement_fact_id: False}))
    assert on.delta != off.delta
    repeated = kernel.reference(kernel.case("SC20"))
    assert len(repeated.evidence_ids) == len(set(repeated.evidence_ids))
```

**出口：** 行动、主/替代、理由、成本和关系均能从输入追溯；禁用/未知不获奖。测试：两个新增文件。

### K5：语义 IR、真实 PDX 编译和尾部保护

**依赖：** K4；**文件：** 新增 `ir.py/lowering.py`、`tests/test_situated_lowering.py`、`tests/test_situated_equivalence.py`；修改 `compiler.py`、`decision_rules.py`、`decision_adapters.py`、`decisions.py`。
**接口：** build_ir/evaluate/lower/compile_all；所有消费者经统一入口，发射 source map；独立 AST 解释器只在测试设施。

- [x] K5.1 统一表达全部状态、目标、关系、成本、仲裁、效果和退出；不支持的运算在编译期明确失败。
- [x] K5.2 把有限动态比较编译为可核验条件分区或决策 DAG；避免全笛卡尔积，允许等价共享，不得冻结事实或删除 rank。
- [x] K5.3 把 action ID、family ID、source map、候选/拒绝信息写入工程合同；运行包不写无界解释日志。
- [x] K5.4 适配器只插入有界表达式，保留原版硬前置、成本和尾部；核对默认/活跃策略覆盖，每个定义分别归属。
- [x] K5.5 对 SC01–SC32 可用实例比较 reference 与真实生成文本 AST；未知 AST 失败，不回调参考器；提交。

```python
import pytest


@pytest.mark.parametrize("case_id", [f"SC{i:02}" for i in range(1, 33)])
def test_generated_semantics_match_reference(kernel, case_id):
    case = kernel.case(case_id)
    assert kernel.pdx(case) == kernel.reference(case)
```

同时使用各场景手写 expected_* 断言，防止二者以同一错误相等通过。
**出口：** 动态因素和关系对 PDX 有见证；不只是优先级乘常数/加偏移。测试：上述两个文件；再运行已有 `tests/test_situated_kernel.py`。

### K6：经济、资源、市场、科技与教育完整行动化

**依赖：** K5；**范围：** DOM04–DOM10 的全部族和 K0 发现的额外合法面。
**文件：** `mod/decisions/actions/fiscal.toml`、`administrative.toml`、`industry.toml`、`resources.toml`、`market.toml`、`research.toml`、`education.toml`；修改相关状态/关系/消费者唯一来源；新建 `tests/test_situated_economic_domains.py`、`tests/test_situated_research_domains.py`。
**接口：** 只实例化 ActionSpec，不新增第二个业务 patcher。

- [x] K6.1 逐族解析真实目标清单：全部现有建筑、三树科技、市场/贸易消费者、制度与财政/行政法律；不以少数示例通过。
- [x] K6.2 产业从投入、产出、价格、运输、就业和科技派生具体瓶颈，分清本地生产、贸易、研究和 PM 的直接/间接接入口。
- [x] K6.3 将教育、大学、科研、行政和财政串成条件关系；固定直接维护费与低直接成本研究的差别。
- [x] K6.4 对每张实例运行具体选中/回退见证；每族运行成本、替代、边界和局部未知反例，至少覆盖 SC01–SC06、SC08、SC11、SC13、SC21。
- [x] K6.5 生成标准开发包并核对新卡对应的真实脚本差异；分经济市场、科研教育两个完整目的提交。

```python
def test_tool_shortage_has_low_dependency_production_path(kernel):
    result = kernel.pdx(kernel.case("SC02"))
    assert result.family_id == "industry.tools_foundation"
    assert result.delta != 0
    assert result.fallback == "selected"
```

**出口：** DOM04–DOM10无pending/blocked/未分类；各域阶段报告分别计算，不因其他尚未迁移域pending而误阻本域。所有合法旧字段和新发现均有具体卡或字段级engine_unexposed证据。
卡号出现或 ai_weight 有文本变化不算出口。测试：两个新增域文件及 K1–K5 受影响用例。

### K7：政治、人口、社会与文化完整行动化

**依赖：** K6；**范围：** DOM01–DOM03、DOM18 全部族。
**文件：** `actions/politics.toml`、`population.toml`、`social.toml`、`identity.toml`；更新状态/关系/消费者；新增 `tests/test_situated_political_domains.py`、`tests/test_situated_social_domains.py`。
**接口：** 同一行动/消费者合同；现有全部 laws 逐定义迁移。

- [x] K7.1 按具体法律、支持、政府、稳定和社会需求展开，禁止单一改革派代理支持所有法律。
- [x] K7.2 人口/劳动力与产业、教育、迁移联动；健康、福利、治安、文化和民权按各自需求/成本，不能一套倍率复制。
- [x] K7.3 用不同政治约束比较可行改革、渐进能力建设、稳定和保持原版；不按国家/文化写意识形态。
- [x] K7.4 SC03–SC04、SC09–SC10、SC18、SC21–SC23 全走生成 AST；实例化所有合法法律，不只验证 change_law_chance。
- [x] K7.5 重生成包，审查每个消费者尾部和新旧差异，分政治与社会两个目的提交。

```python
def test_political_constraint_does_not_become_economic_veto(kernel):
    case = kernel.case("SC10")
    actual = kernel.pdx(case)
    assert actual == kernel.reference(case)
    assert actual.fallback == case.expected_fallback
    assert actual.family_id == case.expected_family
```

**出口：** 四子域每面有事实、成本、目标、真实卡和见证，不能以原版最终执行免责而不实现软倾向。测试：两个新增域文件。

### K8：外交、宗属、战争、海军、海外、地理与时间

**依赖：** K7；**范围：** DOM11–DOM17、DOM19 全部族。
**文件：** `actions/diplomacy.toml`、`subjects.toml`、`army.toml`、`war.toml`、`navy.toml`、`overseas.toml`、`geography.toml`、`temporal.toml`；修改 `country_state.py/country_coordination.py/situated/temporal.py` 和时间/路线配置；新增 `tests/test_situated_external_domains.py`、`tests/test_situated_military_domains.py`、`tests/test_situated_temporal.py`。
**接口：** transition 与全部域的 IR；六路线记忆只表达倾向，不分配实际资源。

- [x] K8.1 逐条核验条约方向、博弈方、宗主/属国、ROOT/target、休战与拒绝；目标州事实不能误读 actor。
- [x] K8.2 实现防御/军需/扩军/动员、舰队/补给/造船/海军科技、海外巩固/殖民的成本差异和条件关系；战败只用真实接口。
- [x] K8.3 对六路线实现进入/保持/退出/抢占/TTL/冷却/恢复/关闭/玩家/旧存档缺变量；月度与消费者安全求值分开，不虚构每日 hook。
- [x] K8.4 SC07–SC08、SC12、SC14–SC17、SC19、SC27、SC29、SC31–SC32 及全部实例正反用例运行参考器和 PDX。
- [x] K8.5 分外交宗属、军事海外、时间三个完整目的提交，每个目的重生成并保持标准包可构建。

```python
def test_candidate_does_not_self_enable_completed_capacity(kernel):
    case = kernel.case("SC31")
    actual = kernel.pdx(case)
    assert actual == kernel.reference(case)
    assert actual.family_id == case.expected_family
```

**出口：** 八子域无未归属面；时间未适用逐项有理由，适用项实际进入/退出有效；不宣称直接接管贸易路线、战争微操或未暴露行为。测试：三个新增文件。

### K9：所有旧逻辑退出与全域深度终审

**依赖：** K6–K8；**文件：** 修改 `decisions.py/decision_rules.py/decision_adapters.py/decision_report.py`、旧业务 TOML 与引用；新增 `tests/test_situated_migration.py`、`tests/test_situated_coverage.py`。
**接口：** compile_all 为唯一语义入口；review 生成逐需求、逐族、逐实例、逐消费者覆盖报告。

- [x] K9.1 对 K0 旧规则身份逐项销账；合并须有新实例覆盖原分支与变化理由，删除须有无消费者/重复/替代证据。
- [x] K9.2 删除业务旁路、只读无用配置、重复画像/关系/仲裁器；兼容门面只转发，无规则副本。
- [x] K9.3 按 DOM01–DOM19、全部额外面和所有行动实例复核深度：每个参与字段有生产作用，成本/关系/时间不只在报告。
- [x] K9.4 重新遍历所有原版策略定义和生成包，核对单作者、原版尾部、作用域、同名遮蔽和完整 source map。
- [x] K9.5 若仍有 pending/blocked 返回其责任阶段补做；无缺口后提交“完成全域行动迁移与生产旁路清理”。

```python
def test_full_scope_has_no_implementation_debt(kernel):
    report = kernel.audit()
    assert report.pending == ()
    assert report.blocked == ()
    assert report.orphan_writes == ()
    assert report.unresolved_migrations == ()
    assert report.complete
```

**出口：** 不是规则数量保持1401，而是全部旧身份有处置、全部合法面有实现。测试：两个新增文件，保留迁移反例。

### K10：独立语义、全场景、突变与完整工程回归

**依赖：** K9；**文件：** 新增 `tests/test_situated_witnesses.py`、`tests/test_situated_mutations.py`；扩展全部域、equivalence 测试、`tools/ci/run_check.py` 和现有 coverage gate（只能补强，不降门）。
**接口：** 见证报告逐 R/DOM/family/action/consumer 绑定测试身份、结果、源哈希和生成哈希。

- [x] K10.1 SC01–SC32 全部有人工预期；属性测试覆盖三值/阈值/排序置换/去重/单调性和局部不干扰，枚举有限档位的成对交互。
- [x] K10.2 对每卡可达与回退、每族成本与关系、每个动态项做 source→IR→PDX 三层见证，不仅比较文本哈希。
- [x] K10.3 故障注入：删除生产卡/写入/事实，冻结动态项，反转成本，错 actor/target，删除退出，重复奖励，破坏尾部，换固定排序；每种必须使对应测试失败。
- [x] K10.4 用真实底本重生成，运行 modgen --check、modguard 在线/离线、decision-audit 在线/离线和 situated audit/report/explain；输出清楚标 static_check/simulation。
- [x] K10.5 候选冻结后运行一次 full-acceptance --quiet，核对收集/执行身份、分类跳过、覆盖和 RSS；完整回归包含离线用例，不重复跑一遍。
- [x] K10.6 失败修复后只重复受影响检查，若生产候选变化则原完整验收失效，冻结新候选重新完整回归；通过后提交。

```python
def test_generated_write_removal_is_detected(kernel):
    report = kernel.audit()
    assert report.witnesses_cover_all_actions
    assert report.source_map_covers_all_writes
    assert report.mutation_survivors == ()
```

**出口：** 无核心跳过、无 surviving 必验突变、无“模型对但脚本错”。老测试通过不能替代新要求；测试中 AST 解释器与生产选择器不能相互调用。

### K11：性能、内存、复杂度和确定性

**依赖：** K10 功能冻结；**文件：** 新增 `tests/test_situated_budgets.py`、`tools/benchmarks/situated_kernel.py`；修改 `performance.py` 及真正热点，不重写已完成测试调度器。
**接口：** 每消费者成本/全包成本/同口径性能收据，详见第6节。

- [x] K11.1 从真实生成 AST 统计分支、谓词、getter、作用域、候选、关系深度、变量和 hook，超限硬失败。
- [x] K11.2 固定原版、固定迁移场景/测试身份/Python/worker/冷暖状态，串行测五次时间中位数与进程树峰值RSS；tracemalloc单列不冒充RSS。
- [x] K11.3 只在等价前提下做解析复用、声明式实例化、CSE、判定 DAG 和有界缓存；缓存键含全部源/底本指纹，禁止静默使用旧结果。
- [x] K11.4 重排源/重复构建证明源映射、生成字节、manifest 确定性；任何语义变化返回 K10。
- [x] K11.5 运行原完整资源/覆盖门；基准不同集时只报告成本，不计算整体提速；提交。

```python
def test_runtime_structure_is_within_frozen_budget(kernel):
    report = kernel.audit()
    assert report.budget_violations == ()
    assert report.deterministic
```

**出口：** 静态预算与同口径工程测量通过；不宣称游戏后期性能实测通过。测试：新增预算文件及所有受优化语义测试。

### K12：版本、正式包、发布材料和恢复

**依赖：** K10–K11；**文件：** 修改版本唯一源 `mod/decisions/fiscal.toml`、`distribution.py`（仅必要改动）、发布文案、版本交付收据；新增 `tests/test_situated_release.py`。
**接口：** 唯一标准变体、源码/生成/包三方指纹、标准 ZIP、manifest 和 SHA。

- [x] K12.1 满足所有功能门后才将生产版本改为3.0.0；不覆盖2.0.0、旧 tag 或历史资产。
- [x] K12.2 检查全包而非差异：metadata、common、全部语言、封面、安装说明、POSIX路径、BOM/LF、无重复/穿越/大小写冲突，禁止 Python/探针/日志/缓存/底本混入。
- [x] K12.3 更新 Workshop 本地文案，准确说明真实动作和直接/间接边界，不写未经长期验证的收益；在线发布独立授权和核验。
- [x] K12.4 按已授权 Git 流程提交推送PR，等CI和审查后合并；从合并源确定性重建并验证，创建新tag/Release，上传ZIP与SHA。
- [x] K12.5 已授权部署时备份现有Mod，只清理已核对属于本项目的旧部署；不碰用户存档/日志/配置；逐文件核对manifest。
- [x] K12.6 若发布/部署未获授权，交付准备好的包及明确待执行外部动作，不能把未发生动作勾选为已完成。

```python
def test_release_contains_only_standard_payload(release_package):
    assert release_package.version == "3.0.0"
    assert release_package.manifest_matches
    assert release_package.forbidden_paths == ()
    assert release_package.localization_complete
```

`release_package` 由 tests/_kernel_harness.py 创建的包夹具提供，实际解压与哈希核对，不读取伪造布尔清单。
**出口：** 标准包合同通过；外部发布/部署按授权真实记录。发布不是功能验收的替代品。

### K13：全 Mod 与全仓复核、真实完成结论

**依赖：** K12 的适用交付；**文件：** 全部生产源、生成物、src、tests、tools、docs、规则、CI、忽略文件；只修正与本次机制/清理有关项。
**接口：** 最终验收收据；计划勾选只从真实需求/证据链计算，不能独立人工设 complete。

- [x] K13.1 对全部Mod结构/内容再走一次：事实、状态、目标、行动、关系、仲裁、时间、消费者、尾部、语言和包；重新发现后无新增漏项。
- [x] K13.2 核对所有目录的调用、CLI、动态注册、测试、生成、文档和证据用途；删除无用代码/重复逻辑/过时当前文档，历史证据保持契约。
- [x] K13.3 运行 encoding、lint、format --check、types、baseline、deadcode；清理本轮可再生缓存后最后跑hygiene，禁止与测试并发。
- [x] K13.4 当前清单、README、设计、覆盖表、发布文案只描述实际能力；逐 R01–R28 与逐域报告输出 final verdict。
- [x] K13.5 核对Git/CI/包/部署对应指纹。无pending/blocked/未分类且全部适用门通过才声明工程实现完成；用户长期验收单列。

**出口：** 下列最终公式全部为真，有具体证据链接，不能以阶段表勾满代替。

## 6. 性能与运行期预算

以下为初始**硬上限**，不是已测结果。若真实语义无法在预算内表达，必须优化表示或将阶段保持blocked；不可删需求/剪候选以通过。确需改变预算时先列同口径成本、复杂度原因、影响和差异收据，不能在失败后默默提高门槛。

| 对象 | 初始上限/要求 | 统计方法 |
|---|---|---|
| 每消费者生产候选 | 32 个具体可比较候选；超限先按互斥上下文等价分区，不能丢失可达行动 | IR 与输出分区双向核对 |
| 每消费者决策分区 | 512 个叶结果；每条路径最多128次Mod新增谓词测试 | 生成AST最坏路径，不按注释/配置计数 |
| 每消费者事实依赖 | 64 个唯一getter身份、依赖调用最大深度8 | 展开scripted trigger/value调用图 |
| 关系依赖深度 | 2级，单行动最多12条直接关系 | 图审计；对称配对不误判使能环 |
| 持久状态 | 每国最多1条主路线、16个Mod变量，无增长历史 | 实际set/remove变量及生命周期 |
| 状态刷新 | 沿用月度国家与现有违约hook；消费者安全求值不额外扫描世界 | on_actions和调用图 |
| 世界枚举 | 新增every_country/every_state世界扫描为0 | 生成AST与传递调用 |
| 解释 | 每决策最多8个reason code；生产包不常驻写解释日志 | IR/生成合同 |
| 生成期 | 冷启动≤120秒、单进程峰值RSS≤1024MiB；同口径重复测量，不与全量游戏分析混测 | 固定底本、空解析缓存、生成+审计5次 |
| 完整工程回归 | 保持现有3600秒超时、覆盖门与内存门；n-auto实际worker如实记录 | 既有full-acceptance与mem门 |
| 可复现 | 同源/底本/环境生成字节、source map、manifest一致 | 两次干净构建比较 |

大量卡通过生成期实例化共享表达式，不要求游戏运行时遍历全体卡。按消费者/目标原生求值，不新建国家×州×商品的笛卡尔全扫描。
相同getter在编译期CSE仅证明脚本结构复用，不声称引擎自动缓存。只在实测可知范围报告性能收益。

## 7. 最终验收公式与反假完成门

机器报告由生产源、真实编译结果和测试见证生成；本节是要求，不是当前已有完整实现的CLI宣称。

```text
complete =
  baseline_and_scope_fingerprints_match
  AND discovered_surfaces == implemented + proven_engine_unexposed
  AND pending == 0 AND blocked == 0 AND unclassified == 0
  AND every_old_rule_has_a_verified_disposition
  AND every_production_write_has_one_action_owner
  AND every_required_family_is_resolved
  AND every_action_has_source_to_IR_to_PDX_witnesses
  AND every_declared_dynamic_factor_has_a_counterfactual_witness
  AND all_required_scenarios_and_mutations_pass
  AND all_compatible_vanilla_tails_and_player_fallbacks_pass
  AND semantic_equivalence_and_resource_gates_pass
  AND every_applicable_stage_receipt_is_verified
  AND no_receipt_has_an_invalidated_dependency
  AND every_required_artifact_is_reproducible
  AND standard_package_and_applicable_delivery_receipts_match
```

解释：上式面集合按唯一身份不重叠计数；engine_unexposed只是范围审计结案，不能算 Mod 功能实现。一个子域有少数D3并不抵销其他pending。
已发现但原版内核内部不可控的面可原版保留，必须公开列出；接口存在但没写完、降低困难、时间不足和测试缺失都不能归为引擎未暴露。

必验失败注入包括：

1. 把任一生产卡变成只进报告、不进PDX，完整门必须失败。
2. 删除一条旧规则迁移记录、原版新增面或具体消费者，覆盖门必须失败。
3. 把动态成本/关系/状态改成常量，反事实和等价门必须失败。
4. 保留schema却删生产effect或退出，见证和生命周期门必须失败。
5. 加入循环使能、重复奖励、错作用域或破坏终结零分，安全门必须失败。
6. 仅保留七卡四字段却登记全部库存，域门必须失败。
7. 修改测试默认值把全部未知补成健康，SC02–SC04、SC21–SC22必须失败。
8. 只修改文档勾选/版本/标签，final verdict不得变化。
9. 删除或替换任一 `StageReceipt` 的生产路径、输入哈希、反事实或失败突变，最终门必须变成 `invalid` 或 `incomplete`。
10. 把后续阶段的结果复制到前置阶段，或复用失效 `scope_hash`，依赖审计必须失败。
11. 把一个域的所有实例压缩成一个模板行，实例数量、source map 或 owner 反查必须失败。

## 8. 提速方式与停点

一次完成核心合同和同一批消费者迁移，按域运行快速反馈；可共享只读底本解析、参数夹具和scope，但不共享可写测试输出。
先逐域实现完整语义、再集中做全域等价/突变与完整回归；不为每张卡重复跑全量，也不把全量放在功能未完成之前代替推进。
性能测量串行且固定输入；发现热点先分析再优化。普通方向由执行者按合同决定，不能因缺图标或非核心外部问题停止全部独立工作。

本轮计划交付后等待用户执行指令。执行时K0→K13，允许实现更优的等价表示，但必须保留需求和证据；发现真正的引擎限制如实登记，不能承诺不存在的接口。
最终只允许声明“在锁定底本及公开范围合同下完整实现并通过静态功能验收”；长期行为最优、国家必走某历史路线和后期性能仍不能凭此宣称通过。
