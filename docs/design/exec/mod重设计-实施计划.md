# Situated AI 处境行动决策内核实施计划

> **For agentic workers:** 执行本计划时按任务逐项推进，保持每个任务可独立审查、可独立验证；不得把计划勾选、文档更新或 Python 测试通过写成长期游戏行为已验证。
>
> 计划版本：27.2（2026-10-30）。这是仓库当前唯一的产品实施计划，替代上一轮已完成的 26.1；上一轮交付仍以 Git 历史、`1.5.0` 标签和执行结果页追溯。

**Goal:** 在 Victoria 3 原版可合法观察和可接入的范围内，把 Situated AI 实现为一个以具体行动为中心的处境决策内核：每个国家根据自己的事实、压力、机会、既有承诺、政治可行性和时间冲击，持续选择相对更可执行的行动倾向，同时保留原版资格、成本、前置、随机、执行和失败机制。

**Architecture:** 原版事实先进入带来源、作用域、单位、刷新成本和未知语义的证据注册表，再派生国家状态、压力、机会和承诺。目标组合把短期生存、能力恢复、结构发展、安全、政治、外交和海外目标分开管理；具体行动卡声明自己的改善对象、消耗、补充、替代、冲突、退出条件和有界增量。有限关系图只协调局部行动，仲裁器使用分层排序和机会成本选择一个有界倾向，最后由原版 AI 消费者完成真正的资格、成本、概率和执行。

**Tech Stack:** Python 3.11+、仓库 `.venv`、现有 TOML 生产源、现有 PDX 生成器/解析器/校验器、pytest、Hypothesis（若已在开发依赖中；否则使用现有属性测试工具）、Victoria 3 `1.14.5` 底本。游戏运行期只加载生成的 PDX 脚本和本地化，不运行 Python 常驻进程。

**Spec:** [处境行动决策内核设计](../03-处境决策设计.md)。工程生成、包结构、证据和恢复合同见[工程基线](工程基线-1.0.md)；环境、检查和 Git 流程见根目录 [CONTRIBUTING.md](../../../CONTRIBUTING.md)。

## Global Constraints

- 正确性第一、速度第二、内存第三；任何优化必须先证明语义、失败语义、覆盖和回退不变。
- 目标版本为一次架构性大版本 `2.0.0`；只有生产源、生成物、静态合同、标准包和交付收据全部对应后才创建标签。
- 只使用原版已经存在或已核实的字段、作用域、消费者和本地化接口；未知字段、未知作用域、版本漂移和原版底本缺失必须硬失败。
- 不替换整个 Victoria 3 AI，不接管前线微观战术，不强制原版没有的行动，不赠送资源，不改变玩家决策路径，不使用国家名称写死路线。
- 只对原版消费者中的单项倾向做有界调整；原版资格、科技前置、政治支持、实际成本、随机、谈判、拒绝、执行、失败和终结零分仍由原版负责。
- 不新增全世界扫描、Python 常驻进程或无界持久历史；运行期候选数、关系深度、状态刷新和缓存大小都必须有静态上限。
- 受控文本 UTF-8 无 BOM、LF；游戏 `.txt`/`.yml` 只在打包或安装边界按引擎要求处理 BOM；原版、第三方和冻结证据保留原始字节。
- 生产源与生成物分离；生成的 `mod/common/`、本地化、metadata、manifest 和 ZIP 不手改。
- 每个领域都必须登记“事实 → 协调 → 原版消费者 → 未知回退 → 静态证据”；无法合法接入的领域明确标为 `retained_vanilla`、`discovered_only`、`explanation_only` 或 `unsupported`。
- 计划中的 `static_check`、`snapshot`、`simulation`、`runtime`、`inference` 证据必须分开记录；长期游戏行为、平衡、后期性能和玩家体验由用户固定包验收。

---

## 1. 最终机制与架构

### 1.1 运行时数据流

```text
原版可观察事实
  → 证据注册表（来源/作用域/单位/刷新/未知）
  → 国家状态向量（能力/瓶颈/风险/机会/承诺）
  → 压力、机会、既有承诺和时间冲击
  → 目标组合（生存/恢复/能力/结构/安全/政治/外交/海外）
  → 具体行动卡
  → 有限互补/替代/冲突关系图
  → 合法性与玩家边界仲裁
  → 原版消费者中的单项有界倾向调整
  → 原版资格、成本、概率、执行和失败
  → 下一次合法求值重新读取事实
```

### 1.2 四种不可混淆的状态

- **能力 `capacity`**：偿付、行政、政治、社会、人力、产业、市场、科研、陆军、海军、外交和海外治理能力。
- **压力 `pressure`**：赤字、债务、短缺、行政不足、教育缺口、战争、战败、激进派、外交威胁和殖民治理负担。
- **机会 `opportunity`**：本地资源、未满足市场、贸易通道、技术窗口、外交保障、港口、目标州和教育收益。
- **承诺 `commitment`**：现有军队/舰队、建设队列、制度支出、战争目标、海外治理、债务服务和已进入的路线。

这四类状态不压缩成一个万能分数。它们在仲裁阶段按用途分别参与：压力决定必须先解决什么，机会决定可利用什么，承诺决定还能承担什么，能力决定哪些路径现实可行。

### 1.3 深度等级

每个产品子域以独立的覆盖等级登记，等级是工程接线深度，不是行为质量分数：

| 等级 | 合同 | 允许的结论 |
|---|---|---|
| D0 | `retained_vanilla` | 没有合法生产接线，明确保留原版。 |
| D1 | `observed` | 能读取并记录真实事实，但不改变消费者。 |
| D2 | `coordinated` | 事实进入状态、压力、机会或承诺，并能被解释。 |
| D3 | `consumer_mapped` | 至少一个具体原版消费者获得有界倾向调整，保留原版尾部。 |
| D4 | `temporal_feedback` | 有限时间记忆、退出迟滞或冲击重评估，并有生命周期和上限合同。 |

目标是：所有可合法接入的领域至少达到 D3；能安全暴露时间语义的领域达到 D4；没有合法消费者的领域保留 D1/D2 并如实标注，不用登记数量冒充接线。

---

## 2. 生产源和代码边界

### 2.1 目标生产源

在迁移完成前，旧 TOML 仍可作为输入；迁移完成后，以下文件成为唯一来源，不允许同一字段在多个来源重复定义：

```text
mod/decisions/
├── facts.toml          # 原版事实、来源、作用域、单位、未知和刷新成本
├── capacities.toml     # 能力维度、四层承受能力和归一化边界
├── pressures.toml      # 压力、瓶颈、严重度和可行逃生路径
├── opportunities.toml  # 机会、收益窗口、地域和外部条件
├── commitments.toml    # 已有承诺、边际成本和新增承诺分级
├── goals.toml          # 目标组合、优先级、时间尺度和退出条件
├── actions.toml        # 具体行动卡及原版消费者映射
├── relations.toml      # 互补、替代、冲突和最多两级依赖
├── arbitration.toml    # 分层排序、限幅、冷却、未知回退
├── temporal.toml       # TTL、冷却、迟滞、冲击和刷新周期
├── consumers.toml      # 领域消费者接线、字段、作用域和尾部合同
└── localization.toml   # 本地化键、语言和占位符合同
```

迁移阶段可保留 `country_state.toml`、`adapters.toml` 等旧入口，但它们必须变成显式兼容层或迁移映射；同名字段不允许继续双写。迁移完成后，旧入口要么删除，要么保留只读兼容解析器并有清晰的移除条件。

### 2.2 Python 目标模块

新模块放入 `src/pdx/situated/`，现有公开 CLI 和旧模块暂时保留兼容门面，避免一次重构破坏工具链：

```text
src/pdx/situated/
├── schema.py       # TypedDict/dataclass、ID、单位、作用域、未知类型
├── evidence.py     # EvidenceSpec、EvidenceValue、EvidenceRegistry
├── state.py        # StateVector、能力/压力/机会/承诺派生
├── pressure.py     # 压力严重度、瓶颈和逃生路径
├── opportunity.py   # 机会窗口和局部收益
├── commitment.py    # 现有承诺、边际成本和新增承诺
├── goals.py        # GoalBundle、目标优先级和时间尺度
├── actions.py      # ActionCard、ActionCandidate、原版消费者合同
├── relations.py    # 有限关系图、循环检测和依赖深度
├── arbitration.py  # 合法性、风险、机会成本和有界排序
├── temporal.py     # 路线生命周期、TTL、冷却、迟滞和冲击重评估
├── compiler.py     # 单一生产源 → Python 参考 → PDX 触发器/值/策略
├── explain.py      # reason code、证据链和静态解释报告
├── contracts.py    # schema、字段、作用域、玩家边界和包合同
└── audit.py        # 全领域覆盖、遮蔽、死规则、循环和复杂度审计
```

现有 `country_state.py`、`country_coordination.py`、`decision_rules.py`、`decision_adapters.py`、`decisions.py` 及经济/外交/安全模块在迁移期间只负责兼容入口、调用新内核或保持尚未迁移的原版接线；不得再各自维护一套业务规则。

### 2.3 核心数据接口

实现时必须先写接口和失败测试，再接入生产源。目标接口如下，名称和字段一旦进入生产源即视为合同：

```python
@dataclass(frozen=True, slots=True)
class EvidenceSpec:
    id: str
    source: str
    scope: str
    kind: str              # number / boolean / enum / ratio
    unit: str
    refresh: str           # consumer / monthly / shock
    unknown: str           # vanilla / conservative / lower_tier
    consumers: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class EvidenceValue:
    spec_id: str
    value: object | None
    known: bool
    stale: bool
    provenance: str

@dataclass(frozen=True, slots=True)
class StateVector:
    capacities: Mapping[str, float | None]
    pressures: Mapping[str, float | None]
    opportunities: Mapping[str, float | None]
    commitments: Mapping[str, float | None]
    shock: str | None
    route: str | None

@dataclass(frozen=True, slots=True)
class ActionCard:
    id: str
    consumer: str
    domain: str
    requires: tuple[str, ...]
    improves: tuple[str, ...]
    consumes: tuple[str, ...]
    complements: tuple[str, ...]
    substitutes: tuple[str, ...]
    conflicts: tuple[str, ...]
    exit_when: tuple[str, ...]
    max_delta: float
    unknown_policy: str

@dataclass(frozen=True, slots=True)
class ArbitrationResult:
    action_id: str | None
    delta: float
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    fallback: str
```

接口的具体实现可以调整，但必须保持：值与未知分离、来源可追溯、行动有界、输出有回退、解释能引用证据、关系图有限。

---

### 2.4 决策周期和职责边界

每次合法求值按六个有限阶段运行，阶段之间只能通过声明的数据结构传递信息，禁止领域模块直接修改其它领域的状态：

```text
Observe → Assess → Prioritize → Select → Adapt → Exit
```

- `Observe`：读取当前可观察事实，保留来源、作用域、刷新时间和未知状态；不在此阶段推断因果。
- `Assess`：派生能力、压力、机会、既有承诺和冲击；每个派生值必须有输入证据和单位。
- `Prioritize`：形成有限目标组合，区分危机、短期恢复、中期能力和长期结构；不直接选择消费者字段。
- `Select`：从有限行动卡集合中按 rank tuple 比较主行动和替代行动；不执行游戏行为。
- `Adapt`：把结果映射为原版消费者允许的单项有界倾向；不放宽原版资格、成本或执行。
- `Exit`：检查 TTL、冷却、迟滞、承诺过重、冲击解除和未知回退；只保存有限路线摘要。

行动卡之间只能通过关系图和仲裁器交流；政治、经济、军事等领域不能互相直接写入对方的权重。跨域联动必须能从报告中追溯为“事实 → 状态 → 目标 → 行动 → 消费者”。

### 2.5 行动选择、反事实和影响预算

行动比较采用有限候选集和词典序排序，不进行未来世界模拟，也不把多个候选的分数累加成不可解释总分。目标排序的固定骨架为：

```text
(crisis_protection,
 bottleneck_relief,
 capability_gain,
 feasibility,
 substitute_availability,
 opportunity_value,
 -commitment_cost,
 political_cost,
 inertia)
```

每个分量只能引用登记过的证据和离散桶；同一事实在同一决策周期内只计一次。对主行动至少保留一个已知替代或明确写明没有合法替代，输出 `chosen`、`rejected_alternative`、`reason_codes` 和 `evidence_ids`。

每个消费者都有独立的影响预算：每个求值周期最多一个主行动增量和一个受控互补信号；同一字段的多个来源先按优先级归并，再应用一次限幅。影响预算、候选数量、关系深度、reason code 数量和持久变量数量都必须写入静态合同，防止“全领域”变成无限叠加。

### 2.6 兼容性协商和降级矩阵

架构不假定每个 Victoria 3 版本、策略状态或原版 DLC 都暴露相同消费者。生成前建立版本化能力矩阵：

```text
底本版本 → 可用字段/作用域 → 可用消费者 → 规则遮蔽状态 → 回退路径
```

任何字段、参数、策略覆盖或 DLC 差异发生变化时，生成器必须选择以下之一并记录原因：

- `full`：事实、消费者和静态合同完整；
- `degraded`：只启用已经验证的低档路径；
- `vanilla`：直接保留原版；
- `unsupported`：硬失败并要求更新底本或规则。

不能通过从旧包复制生成物来绕过底本漂移；不能把策略同名字段的静态接线写成运行期合并已确认。

### 2.7 交付物分离

最终计划产生三种相互独立的交付物：

1. **运行时 Mod 包**：只含游戏加载所需的 PDX、本地化、metadata 和缩略图；不含 Python、探针、日志、快照、原版资源和历史实验。
2. **开发与分析工具**：仓库 Python CLI，负责生成、静态审计、快照、日志/存档辅助分析和解释报告；不作为游戏运行依赖。
3. **证据包**：版本化的 manifest、源/底本指纹、测试摘要、限制和发布收据；不放入运行时 Mod 包。

三种交付物共享版本和源指纹，但不能相互混入。用户长期行为验收使用第一种，工程复核使用第二、三种。

### 2.8 语义内核到 PDX 的编译降低层

高层模型可以在 Python 中使用类型化状态、有限关系图和反事实候选，但游戏运行期不能动态遍历 Python 图结构，也不能依赖常驻服务。编译器必须把高层模型降低成有限、可审计的 PDX 分支：

```text
Python 语义模型
  → 类型/作用域/版本/预算检查
  → 有限候选展开
  → PDX 触发器、script value、strategy 字段和 on_action
  → 原版消费者
```

降低层必须满足：

- 关系图、行动卡和 reason code 在生成期展开；运行期只求值预编译分支；
- 每个生成分支保留原版消费者的资格、成本、前置、玩家边界和零值尾部；
- 候选数、谓词深度、script value 深度、生成文件数和单文件体积达到上限时硬失败；
- Python 参考实现和 PDX 子集解释器共享同一语义来源，不复制一套规则；
- 同样的源、底本、工具版本和配置必须生成逐字节稳定的输出，禁止时间戳和不稳定遍历顺序进入产物。

### 2.9 硬约束、软倾向和安全不变量

决策内核分成三层：

1. **原版硬约束**：资格、前置、成本、政治支持、可达性、随机、执行和失败，只由原版保留；
2. **Mod 软倾向**：只在原版候选已经存在时改变相对权重，且受消费者、领域和周期预算限幅；
3. **安全不变量**：任何未知、版本漂移、玩家控制、关闭开关、越界、重复作者和无效作用域都必须回退或硬失败。

必须固化以下不变量：

- 删除一个非安全事实不能提高扩张、海外或新增长期承诺倾向；
- 压力缓解后不能继续提高同一压力的危机优先级；
- 行动不能在同一求值周期内凭自身输出伪造自己的前置条件；
- 同一字段的增量只应用一次，所有增量必须有限、可追踪、可撤销；
- 任何领域不能直接改变另一个领域的事实，只能通过声明的状态、目标、关系和仲裁路径影响消费者。

### 2.10 双时钟和数值校准

运行期采用两个有限时钟：

- **安全时钟**：战争、违约、重大战败、关键短缺等已核实冲击触发快速重评估；
- **结构时钟**：月度或路线 TTL 处理教育、产业、行政、贸易、法律和海外等慢变量。

两种时钟共享事实和预算，但不共享无限历史。数值不以“全局激进/保守”固定，而采用条件化强度：

```text
基础倾向 + 已确认压力增量 + 可行机会增量
− 承诺成本 − 政治/外交风险
→ 消费者限幅
```

每个行动配置 `base`、`stress`、`opportunity`、`commitment` 和 `max_delta`，所有参数按领域和消费者校准，不按国家名称硬编码。校准只证明范围、方向、单调性和回退，不宣称具体 GDP、战争或改革年份。

## 3. 阶段计划与出口

每个阶段先完成生产源/代码/测试/文档的最小闭环，再进入下一阶段。阶段勾选只在对应出口证据写入结果收据后更新；没有引擎实测时，不得写成行为质量完成。

### K0：计划冻结、基线、所有权和迁移审计

**目标：** 锁定 `1.5.0` 作为等价性基线，确认现有规则、字段、所有权、测试、生成入口和所有生产接线，并冻结新旧架构的语义责任边界。

**文件：**
- 修改：`docs/design/03-处境决策设计.md`、`docs/design/exec/mod重设计-实施计划.md`、`docs/design/当前工作清单.md`。
- 检查：`mod/decisions/*.toml`、`src/pdx/country_state.py`、`src/pdx/country_coordination.py`、`src/pdx/decision_rules.py`、`src/pdx/decision_adapters.py`、`src/pdx/decisions.py`、`tests/test_layered_domains.py`、`tests/test_country_integration.py`、`tests/test_engine_crosscheck.py`。

**步骤：**

- [ ] 建立旧源字段、生成文件、原版字段、测试和文档引用的机器可读迁移表；每一项必须标为 `migrate`、`retain`、`replace` 或 `remove`。
- [ ] 为每个字段、行动、消费者和生成产物登记唯一 owner；同一语义只能有一个作者，兼容门面不得继续维护业务规则。
- [ ] 冻结 `1.5.0` 参考输出、包 manifest、底本指纹、Python 参考结果和稳定生成排序；新增架构在没有差异输入时必须能解释旧输出差异。
- [ ] 为迁移表增加断言：重复作者、无消费者字段、未引用 reader、没有来源的协调信号和没有回退的行动卡直接失败。
- [ ] 更新当前清单为“新计划未开始、`1.5.0` 为基线”，不修改历史执行结果页。

**出口：** 迁移表、基线快照和风险清单可由 `v3` 命令重建；工作树通过编码、断链和文档一致性检查。

### K1：证据注册表、质量分级和未知语义

**目标：** 把“能读到什么”“证据有多可靠”和“可以据此做什么”分开，消除裸 key、重复读取、过期事实和未知值被当成零值的问题。

**文件：**
- 创建：`mod/decisions/facts.toml`、`src/pdx/situated/schema.py`、`src/pdx/situated/evidence.py`。
- 修改：`src/pdx/information_catalog.py`、`src/pdx/vanilla_index.py`、`src/pdx/country_interfaces.py`、`src/pdx/decision_interfaces.py`。
- 测试：`tests/test_situated_evidence.py`、`tests/test_unknowns_covgate.py`、`tests/test_information_catalog.py`。

**步骤：**

- [ ] 定义事实 ID、原版来源、作用域、单位、类型、上下界、刷新点、成本、消费者、未知策略和质量等级；重复 ID、单位不匹配和作用域不匹配必须失败。
- [ ] 为事实登记 `validity`、`freshness`、`scope_confidence`、`runtime_cost` 和 `version_confidence`；质量元数据只能控制是否允许接入，不得悄悄改变原始值。
- [ ] 为每个事实生成 `EvidenceSpec`，把 `known=False` 与 `value=0` 分开；核心未知回退原版，高档辅助未知只能降到已证实低档。
- [ ] 为过期、作用域不确定、底本版本不匹配和来源冲突定义安全降级矩阵；任何质量不足的事实只能减少 Mod 影响，不能提高倾向。
- [ ] 为全部 19 个产品子域建立事实登记；没有合法来源的项登记为 `unsupported`，不能用推测字段填充。
- [ ] 让信息目录、静态报告和生成器共用该注册表，不再由报告脚本另造一套事实名单。
- [ ] 添加边界、未知、陈旧、作用域、单位和版本漂移测试。

**出口：** `v3 information-catalog` 能给出每个事实的来源和未知策略；未知测试全通过，且没有旧读取器绕过注册表。

### K2：状态向量、压力、机会和承诺

**目标：** 形成不依赖万能总分的国家状态表示，明确“当前受到什么约束”“可以利用什么”“已经承担什么”。

**文件：**
- 创建：`mod/decisions/capacities.toml`、`mod/decisions/pressures.toml`、`mod/decisions/opportunities.toml`、`mod/decisions/commitments.toml`；`src/pdx/situated/state.py`、`pressure.py`、`opportunity.py`、`commitment.py`。
- 修改：`src/pdx/country_state.py`、`src/pdx/country_coordination.py`、`mod/decisions/country_state.toml`（迁移映射期）。
- 测试：`tests/test_situated_state.py`、`tests/test_situated_pressure.py`、`tests/test_situated_commitment.py`。

**步骤：**

- [ ] 将能力、压力、机会和承诺定义为独立命名空间；每一项声明单位、方向、缺失处理和可影响消费者。
- [ ] 保留 `recovery` / `foundation` / `stable` / `expansion` 四层，但把层级仅用于承受能力，不把它当作国家人格或单一总分。
- [ ] 为赤字、债务、短缺、行政不足、战争、战败、激进派、教育缺口和海外治理建立压力项；每个压力至少登记一个可行的低依赖逃生路径，若原版没有合法消费者则标为 `retained_vanilla`。
- [ ] 为资源、市场、贸易、技术、外交、港口、地理和教育收益建立机会项；没有正面证据时保持未知，不把未知变成机会不存在。
- [ ] 将军队、舰队、建设队列、制度、战争目标、海外治理和债务服务建模为既有承诺，区分维持、补充、扩大和新增长期承诺。
- [ ] 采用有界归一化和显式缺失传播；禁止跨单位相加的“万能健康分”。

**出口：** 相同事实输入可同时生成 Python `StateVector` 和 PDX 信号；状态派生通过单元、属性和未知反例测试。

### K3：目标组合和时间尺度

**目标：** 让国家同时拥有短期生存、恢复、能力建设和长期结构目标，避免一个高优先级目标永久遮蔽其它合理路径。

**文件：**
- 创建：`mod/decisions/goals.toml`、`src/pdx/situated/goals.py`。
- 修改：`src/pdx/decision_intents.py`、`src/pdx/decision_report.py`。
- 测试：`tests/test_situated_goals.py`、`tests/test_decision_intents.py`。

**步骤：**

- [ ] 定义目标组合：`survival`、`recovery`、`capacity`、`structure`、`security`、`political`、`diplomatic`、`overseas`。
- [ ] 每个目标声明触发压力、可接受的承诺、时间尺度、退出条件、可替代目标和允许的消费者。
- [ ] 使用“危机抢占 + 普通目标并行 + 迟滞退出”而不是全局 `if all(...)` 门槛；一个目标缺少高档条件时仍可选择低成本能力建设。
- [ ] 为目标竞争建立明确的优先级规则：生存风险优先，确认瓶颈次之，能力建设再次，机会利用最后；同一层内按政治可行性、承诺成本和替代路径排序。

**出口：** 低能力国家、富裕国家、战时国家和高政治阻力国家的目标组合均有可解释结果；目标互斥和退出测试通过。

### K4：行动卡、硬约束/软倾向分离和原版消费者合同

**目标：** 把“想发展”改成可审查的具体行动，并保证每个输出都落到原版已经存在的消费者。

**文件：**
- 创建：`mod/decisions/actions.toml`、`mod/decisions/consumers.toml`、`src/pdx/situated/actions.py`。
- 修改：`src/pdx/decision_adapters.py`、`src/pdx/decision_rules.py`、`src/pdx/decisions.py`、`src/pdx/decision_economy.py`、`src/pdx/decision_diplomacy.py`、`src/pdx/decision_security.py`。
- 测试：`tests/test_situated_actions.py`、`tests/test_decision_adapters.py`、`tests/test_decision_placement.py`、`tests/test_engine_crosscheck.py`。

**步骤：**

- [ ] 每张行动卡填写唯一 ID、领域、原版消费者、输入事实、改善对象、消耗、长期承诺、互补、替代、冲突、退出条件、未知回退和 `max_delta`。
- [ ] 先对照 `VanillaIndex` 和原版底本验证字段、作用域、路径、参数和消费者；缺少底本或字段漂移时拒绝生成。
- [ ] 将原版硬约束、Mod 软倾向和安全不变量分别编译；Mod 规则不得产生新的硬资格，也不得通过正向权重绕过原版不可执行状态。
- [ ] 建立消费者适配器：建筑/生产方式、科研、教育、法律/政府、利益集团、贸易/市场、外交/宗属、陆军、海军、战争/战后、殖民/海外、目标州/地理。
- [ ] 每个适配器只写入原版允许的单项倾向，保留原版资格、前置、成本、政治支持、随机、执行失败和零值尾部；玩家和禁用路径直接原版回退。
- [ ] 通过消费者 ID 而不是文本匹配或国家名称绑定行动；生成器拒绝同一消费者重复作者和遮蔽顺序不明确的规则。

**出口：** 每张生产行动卡都能追溯到一个真实原版消费者；所有消费者的字段、作用域、玩家边界和零值尾部通过静态审计。

### K5：互补、替代、冲突和瓶颈逃生图

**目标：** 让各领域真正联动，同时防止多条件全满足门槛和循环依赖把国家锁死。

**文件：**
- 创建：`mod/decisions/relations.toml`、`src/pdx/situated/relations.py`。
- 修改：`src/pdx/situated/actions.py`、`src/pdx/situated/goals.py`、`src/pdx/decision_report.py`。
- 测试：`tests/test_situated_relations.py`、`tests/test_route_domains.py`、`tests/test_metamorphic.py`。

**步骤：**

- [ ] 只允许 `complements`、`substitutes`、`conflicts` 和 `enables` 四类关系；每条关系声明理由、方向、适用范围、证据和最大深度。
- [ ] 将依赖深度硬限制为最多两级，构建时做 DFS 循环检测；循环、孤立关系和没有行动消费者的关系直接失败。
- [ ] 为每个主要压力提供至少一个低依赖逃生路径：例如短缺可走本地生产、贸易/合作或生产方式替代，但每条路径仍受原版资格和成本约束。
- [ ] 互补只提供有界增量，替代不会累乘奖励；同一事实重复进入多条路径时按证据 ID 去重。
- [ ] 加入单调性和反例测试：压力缓解不能提高危机优先级，承诺增加不能让扩张倾向无条件上升，未知不能伪造机会。

**出口：** 关系图有上限、无循环、无无主节点；所有非原版压力均能找到可行的局部回退或明确记录为原版保留。

### K6：仲裁器、机会成本、反事实、单调性和有限行动输出

**目标：** 在多目标竞争时选择一个有解释、有限、可回退、能说明替代路径的倾向，不使用不可审查的万能总分。

**文件：**
- 创建：`mod/decisions/arbitration.toml`、`src/pdx/situated/arbitration.py`。
- 修改：`src/pdx/country_coordination.py`、`src/pdx/decision_rules.py`、`src/pdx/decision_adapters.py`。
- 测试：`tests/test_situated_arbitration.py`、`tests/test_policy_audit.py`、`tests/test_properties.py`。

**步骤：**

- [ ] 按以下固定顺序仲裁：
  1. 玩家、禁用、原版 AI 边界和消费者资格；
  2. 生存/违约/战争等危机保护；
  3. 是否会加重已确认瓶颈；
  4. 是否缓解压力或建立能力；
  5. 是否存在更可行替代；
  6. 既有承诺和边际成本；
  7. 政治可行性、外交风险和机会成本；
  8. 路线惯性、迟滞和退出；
  9. 输出单项限幅增量。
- [ ] 把排序实现为可序列化的 rank tuple 和 reason code，不把不同单位的原始值直接相加。
- [ ] 为每个消费者定义上下限、零值语义、冲突优先级和未知回退；不允许多个规则隐式累乘同一奖励。
- [ ] 保留原版执行失败；Mod 只能减少或增加倾向，不能把不可执行行动变成可执行。
- [ ] 对同一输入生成 Python 参考结果、PDX AST 解释结果和静态报告，三者差异必须可定位到已声明的 PDX 子集边界。
- [ ] 对每个主行动保留至少一个替代行动或明确的“无合法替代”结论；输出选择、放弃替代、影响预算和证据链，禁止只输出一个没有理由的权重。
- [ ] 检查同一字段在同一周期只应用一次增量，主行动与互补信号不超过消费者影响预算；超过预算直接失败。
- [ ] 为安全信号建立单调性与反自激测试：事实删除、压力缓解、承诺增加、替代路径出现和冲击解除不能产生违反安全不变量的方向变化。

**出口：** 仲裁结果可解释、可重现、有边界；属性测试覆盖全未知、危机、冲突、替代、承诺过重和玩家边界。

### K7：双时钟、路线记忆和冲击反馈

**目标：** 让国家在变化后能转向，在短期噪声下不抖动，在长期承诺过重时能退出。

**文件：**
- 创建：`mod/decisions/temporal.toml`、`src/pdx/situated/temporal.py`。
- 修改：`src/pdx/country_state.py`、`mod/common/on_actions/sitai_country_on_actions.txt`、`mod/common/scripted_effects/sitai_country_effects.txt`、`mod/common/scripted_triggers/sitai_country_triggers.txt`。
- 测试：`tests/test_situated_temporal.py`、`tests/test_country_state.py`、`tests/test_gametimer.py`。

**步骤：**

- [ ] 保留已有月度更新、TTL 100 日、切换冷却 62 日和重大冲击 hook，先建立等价性测试，再决定是否调整参数。
- [ ] 明确安全时钟和结构时钟的触发集合、刷新频率、预算和优先级；安全时钟不能把所有普通波动升级为危机。
- [ ] 分离路线记忆和状态向量；路由只记录有限的当前路线、进入日、过期日、冷却和必要的摘要，不保存无界历史。
- [ ] 实现进入、保持、退出、紧急抢占、冲击重评估和未知回退；为压力解除和承诺过重设置退出迟滞，防止来回抖动。
- [ ] 明确存档默认、禁用停止、玩家国家不写入、国家消失和版本迁移行为。

**出口：** 生命周期、TTL、冷却、存档默认和关闭路径通过静态和模拟测试；运行期状态数量有明确上限。

### K8：19 个产品子域的全覆盖接线和成熟度闭环

**目标：** 以同一架构接通尽可能多的原版领域，达到最大广度和可审查深度，同时如实保留不可接入面。

**子域：** 政治/法律、人口/劳动力、社会/健康/福利、财政/债务、行政/国家能力、产业/生产方式、农业/资源、市场/商品/贸易、科技、教育/知识、外交/条约、宗主/属国、陆军/动员、战争/军需、海军/海上投射、殖民/海外、地理/目标州、身份/文化、时间/冲击。

**文件：**
- 修改：`mod/decisions/consumers.toml`、各域生产源、`src/pdx/decision_report.py`、`src/pdx/information_catalog.py`。
- 测试：为每个域新增或扩展 `tests/test_situated_domain_<name>.py`，共享参数化夹具放入 `tests/_situated_fixtures.py`。

**步骤：**

- [ ] 为每个子域登记至少一个事实来源、一个状态/压力/机会/承诺连接、一个真实消费者或 D0/D1/D2 处置、一个未知回退和一条静态证据。
- [ ] 先迁移经济/科技/教育作为高深度样板，再按政治/社会、市场/贸易/外交、军事/战争/宗属、殖民/地理/身份扩展；每一域完成后保持可生成和可加载。
- [ ] 不以“九个粗开关”“reader 数量”“字段数量”作为完成条件；必须能从行动卡反向追到事实和消费者。
- [ ] 对国家类型使用参数化处境夹具，而不是国家名称路线：低能力大陆国、人口大国、资源型国家、海洋贸易国、战后国家、政治分裂国家和高债务国家。
- [ ] 每一域检查与其它域的互补/替代关系数量和依赖深度，避免单一经济信号污染所有消费者。
- [ ] 每个子域同时通过五个门：事实有效性、状态派生、行动/消费者接线、未知回退、性能/复杂度预算；只有五门齐全才可标记为 D3/D4。

**出口：** 覆盖报告逐域列出 D0–D4、事实、协调、消费者、未知回退和证据；没有无证据的“已完成”域。

### K9：解释、审计、差异诊断和用户辅助反馈

**目标：** 让工程和用户能够回答“为什么这个国家此时更偏向这个行动”，但不把解释工具误当成行为证明。

**文件：**
- 创建：`src/pdx/situated/explain.py`、`src/pdx/situated/audit.py`。
- 修改：`src/pdx/decision_report.py`、`src/pdx/engine_log.py`、`src/pdx/observe.py`、`src/pdx/cli.py`。
- 测试：`tests/test_situated_explain.py`、`tests/test_situated_audit.py`、`tests/test_observe.py`、`tests/test_engine_log_offline.py`。

**步骤：**

- [ ] 为每个输出保留结构化 reason code、证据 ID、目标、压力、承诺、被放弃的替代和回退原因。
- [ ] 增加离线命令 `v3 situated audit`、`v3 situated report` 和 `v3 situated explain`；命令读取快照、日志和存档时必须标明证据类别，不生成因果结论。
- [ ] 审计行动卡遮蔽、规则顺序、重复作者、循环、无消费者 reader、未知策略、超限增量和死代码。
- [ ] 增加“决策路径差异”报告：当旧基线和新内核输出不同，报告第一个分叉的事实、目标、替代、消费者和限幅原因，不能只报告最终数值差异。
- [ ] 将用户提供的日志/存档分析结果写入 `tools/out/` 或版本化收据，不把运行态材料放进生产包。

**出口：** 给定一个静态输入或用户提供的观测材料，工具能生成可追溯解释和限制说明；不宣称长期 AI 行为已验证。

### K10：静态正确性、编译降低、等价性、突变抗性和完整回归

**目标：** 在不启动长期游戏验证的前提下，最大限度排除字段、作用域、生成、包结构和回退错误。

**文件：**
- 修改：`src/pdx/situated/contracts.py`、`src/pdx/situated/compiler.py`、`tools/ci/run_check.py`、`pyproject.toml`（仅在需要新测试入口时）。
- 测试：`tests/test_situated_contracts.py`、`tests/test_situated_compiler.py`、`tests/test_situated_equivalence.py`、`tests/test_situated_package.py`。

**步骤：**

- [ ] 先运行改动域测试：schema、未知、状态、关系、仲裁、时间、消费者和生成器。
- [ ] 对旧 `1.5.0` 与新内核在“无新证据/关闭/玩家/不可用/未知”输入下做等价性测试；差异必须是已登记的新增有界倾向。
- [ ] 对关键规则执行突变测试或等价的反例注入：删掉一条来源、交换优先级、放宽一项边界、制造循环和遮蔽时，测试必须能失败，证明门禁不是只覆盖正常样例。
- [ ] 对 Python 语义模型到 PDX 降低层做结构化对照：同一输入的候选集合、排序、限幅、回退和字段作者必须一致；不能只比较最终文本哈希。
- [ ] 运行原版字段、作用域、路径、参数、策略遮蔽、玩家边界、零值尾部、localization、编码、manifest 和 ZIP 路径合同。
- [ ] 运行 `python tools/ci/run_check.py full-acceptance --quiet` 一次；记录 worker、测试选择、覆盖率、墙钟、峰值 RSS 和跳过项。
- [ ] 运行兼容性矩阵检查：锁定底本、缺失底本、字段漂移、策略覆盖、关闭开关、玩家国家和未知输入都必须落到明确的 `full/degraded/vanilla/unsupported` 分支。
- [ ] 清理可再生缓存后运行 `encoding`、`hygiene`、`lint`、`format --check`、`types`、`baseline`、`deadcode`；任何失败必须修复或明确记录为外部阻塞。

**出口：** 静态工程验收和标准包合同通过；报告仍只标为 `static_check`/`simulation`，不升级为游戏行为质量。

### K11：性能、内存、确定性和运行期预算收口

**目标：** 在正确性和覆盖不变的前提下，把运行期和生成期成本控制在可复核预算内。

**文件：**
- 修改：`src/pdx/situated/evidence.py`、`state.py`、`relations.py`、`arbitration.py`、`compiler.py`、`src/pdx/performance.py`、`src/pdx/parallel.py`。
- 测试：`tests/test_situated_performance.py`、`tests/test_mem_baseline.py`、`tests/test_perf_baseline.py`；基准输入固定在 `tests/fixtures/`。

**步骤：**

- [ ] 先固定旧/新同口径输入、测试集合、Python 版本、worker 和资源采样方式；不存在同口径数据时只报告各自成本。
- [ ] 生成期按源文件和底本指纹缓存，运行期只保留有限状态、固定大小缓存和按月/冲击刷新；禁止世界级全扫描和无界 reason 历史。
- [ ] 预编译消费者切片、事实引用和关系图，避免在每个消费者重复解析 TOML 或重复读取同一事实。
- [ ] 用结构共享、整数/枚举 reason code 和惰性解释降低内存；任何缓存必须有命中失效、最大容量和禁用路径。
- [ ] 性能改动必须先跑等价性、失败语义、覆盖和资源门；只有同口径改善才写入性能收据。
- [ ] 将运行期预算固化为合同：每次求值的事实读取数、行动候选数、关系边数、脚本值深度、持久变量数、解释记录数和 hook 频率均有上限；超过上限在生成期失败。
- [ ] 验证确定性：固定源、底本、Python、依赖和配置时，重复生成的源指纹、产物字节、manifest 和解释排序必须一致。

**出口：** 速度和峰值 RSS 不劣于冻结预算，或有明确、可接受的回归解释；不能用减少测试或降低门禁获得“提速”。

### K12：标准交付、用户验收包、部署和回滚

**目标：** 从同一提交生成可发布的 `2.0.0` 标准包，并保证用户可安装、可回退、可识别版本。

**文件：**
- 修改：`src/pdx/distribution.py`、`src/pdx/cli.py`、`docs/design/exec/版本交付-结果.md`、`docs/design/exec/分层联动-执行结果.md`。
- 生成：标准 ZIP、`.zip.sha256`、manifest、中文 Workshop 文案和发布收据。

**步骤：**

- [ ] 从合并提交重生成标准包；包内只包含 Mod 安装所需文件，不含 Python、探针、日志、快照、缓存、原版资源或历史实验。
- [ ] 核对包内 `.txt`/`.yml` 的 BOM/LF、缩略图、metadata、localization、路径和 SHA-256；仓库源仍无 BOM。
- [ ] 推送中文提交和 PR，等待 required CI；CI/审查通过后合并 `main`，从合并提交创建不可移动 `v2.0.0` tag 和 GitHub Release。
- [ ] 将同一包部署到用户游戏 Mod 目录，逐文件核对 manifest；保留可恢复备份，不删除用户存档、日志和设置。
- [ ] 生成用户长期验收包：固定包哈希、安装位置、建议新局/存档条件、日志和存档收集路径、已知限制和反馈模板；不把用户验收变成工程通过条件。
- [ ] 发布收据明确 `static_check`、`snapshot`、`simulation`、`runtime` 和 `inference` 边界；长期游玩由用户验收，后续问题从 `hotfix/<topic>` 和维护版本处理。

**出口：** 本地/远端主线同步、标签和 Release 指向交付提交、标准包可复核、游戏目录安装与包哈希一致、工作树干净。

### K13：全仓库终审和计划闭环

**目标：** 确认新架构没有留下重复逻辑、死代码、过时文档或未声明的覆盖缺口。

**文件：**
- 检查：全部 `AGENTS.md`、`CONTRIBUTING.md`、原则、设计、计划、结果、README、`src/`、`mod/`、`tests/`、`.github/` 和 `.gitignore`。
- 修改：仅修改审计发现的重复、断链、过时入口、未生成文档和无效忽略项。

**步骤：**

- [ ] 用 Python 盘点所有受控文件的 UTF-8/LF、BOM、重复路径、大小写冲突、断链、未引用模块和生成物漂移。
- [ ] 用 `git grep` 核对旧模块、旧 CLI、旧生产源和旧计划没有绕过新内核的默认入口。
- [ ] 复核 19 个子域、行动卡、关系图、未知回退、玩家边界、复杂度预算、包合同和发布收据。
- [ ] 删除可证明无调用方、无生成入口和无证据用途的死代码；历史证据保留在 Git 历史或约定目录，不复制到当前入口。
- [ ] 更新当前工作清单为实际交付状态；计划全部完成前任何未达项必须保留为未完成或阻塞，不得用文字覆盖。

**最终出口：** 计划逐项都有生产源、代码、测试和收据证据；仓库、标准包、安装目录和 Git 交付一致；用户仍能清楚区分工程正确性与长期行为验收。

---

## 4. 全领域接线合同

执行期间维护一张机器可读覆盖表，每行至少包含：

```text
subdomain
facts
state_signal
pressure_or_opportunity_or_commitment
action_ids
consumer_id
scope
unknown_fallback
priority_order
static_evidence
runtime_boundary
```

19 个子域必须逐项检查：政治/法律、人口/劳动力、社会/健康/福利、财政/债务、行政/国家能力、产业/生产方式、农业/资源、市场/商品/贸易、科技、教育/知识、外交/条约、宗主/属国、陆军/动员、战争/军需、海军/海上投射、殖民/海外、地理/目标州、身份/文化、时间/冲击。

任何“读到了但没有合法消费者”的面只算 D1/D2；任何“写了行动但找不到真实原版消费者”的面必须失败。任何“所有方面同时满足才有输出”的规则必须拆成局部行动、替代路径和低依赖逃生路径。

## 5. 终极方案质量门

计划完成前必须同时满足以下五组门禁；任何一组未通过都只能标记为未完成或阻塞：

1. **机制门**：决策周期职责分离；行动卡、关系图、仲裁顺序、替代路径和退出条件可解释；没有万能总分和隐藏跨域写入；Python 语义模型可以安全降低为有限 PDX 分支。
2. **广度门**：19 个子域逐项有 D0–D4 记录；每个可接入面至少有 D3，不能接入面有明确回退和理由。
3. **深度门**：事实质量、能力/压力/机会/承诺、目标、行动、互补/替代/冲突、时间反馈、reason code 和差异诊断形成闭环。
4. **工程门**：原版字段、作用域、玩家边界、未知回退、策略遮蔽、生成、编码、localization、包和跨平台合同全部通过；等价性和突变抗性测试有效。
5. **资源门**：运行期和生成期都通过固定速度、峰值 RSS、候选数、缓存、确定性和持久状态预算；优化不能以减少测试或放宽正确性为代价。

这五组门禁互不替代。领域覆盖高不代表兼容性通过；静态工程通过不代表长期行为通过；性能改善不代表正确性不变。

## 6. 结果、阻塞与证据规则

- 工具、脚本、CI、包验证和静态 AST 只能证明覆盖范围内的工程合同。
- 快照和存档差分只能证明记录到的状态变化，不能单独证明因果或行为质量。
- 日志可以帮助定位脚本错误、字段覆盖和运行态迹象，但不能把一次评分变化写成长期最优决策。
- 本体底本缺失、字段未暴露、引擎合并/覆盖语义未知、平台不可用或用户未提供运行材料时，记录为外部限制并继续完成不依赖它的工作。
- 任何重复失败都必须改变实验口径或回到根因分析，不能重复同一已知失败窗口。

## 7. 执行前的最终确认

本计划只在用户明确下达执行指令后开始。执行时默认按 K0 → K13 顺序推进；若某阶段发现更好的架构，可以更新后续阶段，但必须在计划和当前清单中留下变更原因、影响范围和新的出口。没有用户新指令时，本轮只维护计划，不修改生产 Mod。
