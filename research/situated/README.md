# Situated 引擎静态证据

本目录保存版本固定的原始字节证据。它们属于 `static_check`，不执行游戏，也不证明运行效果、数值平衡或
完整下游行为。生产入口必须重新核对当前 EXE 和原版来源；离线快照只提供历史证据身份。

## 法律颁布权重文档摘录

[law-enact-context.md](victoria3-1.14.5-law-enact-context.md) 仅保留本体 `common/laws/readme.md`
第 1、11、13 行的标题、上下文陈述与示例分界，空行保持原行号。摘录 SHA-256 为
`706098c2cb35770cbe477c84620940b716e60d8708f30f7ae72d46ed1e2091d8`；完整原件与本地规范化镜像的
哈希仍由 `official-docs.manifest.json` 独立维护。编译器核对摘录字节、原件身份及可用原件中的对应行，
离线生成不再依赖被忽略的完整本地镜像。本摘录仅证明 `ai_enact_weight_modifier` 的 country ROOT 与 law
辅助对象，不授权 `ai_will_do`、新 getter 或其他法律接口。

## 策略作用域修订

| 修订 | 固定文件 | SHA-256 | 用途 |
|---|---|---|---|
| 初版 | [strategy-scope.json](victoria3-1.14.5-strategy-scope.json) | `93947c66bfddd6123633528d66b10a15f334a925b6800ccfa8a4413db85b1944` | 保留原始字节与当时的授权边界，不再作为当前入口 |
| 修订 2 | [strategy-scope-r2.json](victoria3-1.14.5-strategy-scope-r2.json) | `e0b60c432cfe74a5b85c86d7dd401ac7305450446312f9da73c644b729385ae4` | 保留 15 个逐字段消费者，148 段原始字节观察 |
| 修订 3 | [strategy-scope-r3.json](victoria3-1.14.5-strategy-scope-r3.json) | `83b369cd1f40e588428410912cfb9fcea43f823f0604ee38283bcbf7677adba3` | 保留 15 个逐字段消费者，169 段原始字节观察；补齐法律实例类型 |
| 修订 4 | [strategy-scope-r4.json](victoria3-1.14.5-strategy-scope-r4.json) | `1012740c43d88e4a6665ac72cb9f0caea7fc516fd0974dd2b710075e9fa4bf8e` | 保留 17 个逐字段消费者，303 段原始字节观察；补齐两个目标评分枚举与精确对象 |
| 修订 5 | [strategy-scope-r5.json](victoria3-1.14.5-strategy-scope-r5.json) | `e852bcd7f73d5da44f50c314a6ed921fa9aad4c32e2dbabf31ee536d3e6be463` | 保留 19 个逐字段消费者，325 段原始字节观察；追加海军目标与造船输出成员链 |
| 修订 6 | [strategy-scope-r6.json](victoria3-1.14.5-strategy-scope-r6.json) | `39b41be99801353ea76c64a1f6c0dbe4c8debe725f52488b045e4a5de8d7d528` | 保留 29 个逐字段消费者，388 段原始字节观察；追加十条独立标量链及博弈实例类型 |
| 修订 7 | [strategy-scope-r7.json](victoria3-1.14.5-strategy-scope-r7.json) | `3f295f0a1a8fc1bd964ebe0949f81352de60fb3f28fa0b761358ba154aeab3f1` | 当前 33 个逐字段消费者，452 段原始字节观察；追加 treaty/stance 精确 map 与两条舰船标量链 |

修订 2 保留初版全部合同与观察，追加两条精确消费者链和 28 段观察，并更正初版对 `institution_scores`
尚未授权的限制。初版文件原字节不变。共同锁定 Victoria 3 1.14.5 Windows x64 EXE：
`9b6f133a5dc235de9135d7b57e86ceda8282d1ba6c0e185f3ee19c22f8917f54`，97,774,200 字节，
以及 manifest 中五份 `common/ai_strategies` 原件的独立 SHA-256。
制度定义另外固定 `common/institutions/00_institutions.txt`：
`9d3b8474e2e99a34cd23cc38343253b850d0b2991a0f9418c85577c68c8ece2b`，
记录七个唯一普通定义的 source／line。生产验证要求实际制度目录的全部 `.txt` 来源集合完全匹配，新增、删除或覆盖均失败。

新增链从原 PE 的精确 NUL 字符串、atom token、压缩派发和成员偏移出发，追踪至实际求值调用与上层加法。
使用现有 Visual Studio `dumpbin /disasm /range:<start>,<end>` 阅读对应 VA；不依赖字段名前缀或相邻成员。
VA／RVA／文件偏移依据原 PE section table 独立核对；所有新旧观察均对原 EXE 重读匹配。

### wanted_construction_output

- atom `0x1447af2a0` 的 token 为 `0x5c98`，字符串在 `0x14477f530`。
- selector `0x141641f40` 为 17，派发目标 `0x14164185e`。解析器以 `rdi-0xa18` 寻址；
  既有 CAIStrategy RTTI 的 parser subobject 偏移为 `0x20b8`，故精确成员为 `0x16a0`。
- 消费者 `0x141646450` 保存传入国家；`0x1416464c1` 用国家 ID 构建 tag 5 tuple，
  `0x14164653e–0x141646554` 将同一 tuple 放入三个求值槽。tag 5 由 CCountry RTTI／getter 独立识别。
- context 经 `0x14062d6c0` 从零条目构造，消费者没有注册 named target。`0x141646579` 选择
  `member+8`，`0x141646580` 调用实际 scalar evaluator。
- 默认／活动策略调用在 `0x1415ac4af`／`0x1415ac4da`，`0x1415ac4e2` 实际相加；原版默认策略
  4767–4769 行独立说明 construction output target 和 additive merge。

合同为 country ROOT、无 target、`additive_construction_output_target`。这不授权其他 construction 字段，
也不证明最终 construction arithmetic、minimum、rounding 或 terminal 行为已完成等价 lowering。

### institution_scores

- atom `0x1447ae9c0` 的 token 为 `0x5c09`，字符串在 `0x14477e818`。selector `0x141641eb1`
  为 4，指向 parser `0x1416417cc`，定位 map 成员 `0x3d0` 并调用专用 map parser。
- key parser `0x14163e150` 经名字哈希解析 institution definition pointer；无效 key 的原始报错为
  `Invalid institution type '{}' in ai_strategies`。`0x14163e347` 插入定义指针 key，随后解析元素
  `+0x10` 的 script value。
- 消费者 `0x141644870` 分别保存国家 R8 和 definition R9。map storage/count/mask 位于
  `0x3d8`／`0x3e0`／`0x3e4`；它按实际定义指针哈希、比较并选择元素。
- `0x141644a05` 构建国家 tag 5 tuple，`0x141644a3a` 调用原 script-value wrapper。
  wrapper 将同一国家 tuple 放入三个求值槽，definition pointer 没有注册为 named scope。
- 默认／活动策略调用在 `0x1415bbd40`／`0x1415bbd71`，`0x1415bbd79` 实际相加；原版默认策略
  1214–1216 行独立说明 institution preference 和 additive merge。

合同为 country ROOT、`definition_only:institution_type`、`additive_score`。definition pointer 仅选择
map 元素，不能变成 `scope:institution`、`scope:institution_type` 或任何新 getter。

证据验证器证明字段消费者与来源身份；它不解析机构子节点。生产 inventory／compiler 另行验证真实普通 map、
唯一且实际存在的 institution definition key、普通 script-value 子节点，以及全部实际 reader 与 country ROOT 的匹配。
重复 key、未知 definition、前缀匹配、scalar／nested 替代形状、target getter 和额外 actor path 均不能继承授权。
这些拒绝条件由定向测试分别覆盖，不能以 manifest 存在或引擎字节通过代替子项验证。
独立盘点把 `institution_scores` 容器登记为 `institution_score_map` 结构观察，只有验证后的精确子项登记为动态评分消费者。

### min_law_chance_to_pass

修订 3 保留修订 2 全部原始观察，补入 21 段字节，并将本字段由 pending 提升为精确 direct。
解析器 `0x1416418b2` 定位成员 `0x9b8`；消费者 `0x141646c60` 以空上下文构建国家 tag 5 ROOT，
在 named `law` key 下注册 tag `0x31` 法律实例，再于 `0x141646d23` 调用该成员的原始数值 wrapper。

类型识别不依赖 tag 数字猜测。`CLawTypeLink` 的 TypeDescriptor `0x145720b00`、
COL `0x144c31540`、vftable `0x144717330` 和虚槽 `+0x28` 精确连接至 `0x14277b340`。
该方法只接受 tag `0x31`，以其 ID 调用 `0x140cb3cc0`；解析器的数据库缺失诊断直接引用
`CCountryLaw` TypeDescriptor `0x14546c288` 的 `+8`。方法从法律实例取 `+0x38` 的法律类型指针，
输出另一个 tag `0x32`。因此 tag `0x31` 是 `CCountryLaw` 实例，不能替换为静态 `law_type` 定义。

调用者 `0x1415b9800` 顺序访问活动策略，取第一个非零结果；若均为零，则调用默认策略。
这证明 `override_pass_chance_threshold`，不扩展为加法合并，也不证明下游缩放或舍入已经完整 lowering。
compiler 将 `law` 登记为 `law` 类型辅助上下文，无 target；现有三个生产 writer 的全部实际输入仍读取国家 ROOT。
`law` 对象证据不授予新 getter，错误类型、角色、额外对象和 actor 路径必须拒绝。

### wargoal_scores 与 secret_goal_scores

修订 4 沿用修订 3 原件，追加 134 段观察。wargoal parser `0x141641285` 定位成员 `0x1d8`，
由 `0x14163e390` 在原始 34 项 token 表中取得精确 enum index；secret parser `0x141641481`
定位成员 `0x2a0`，专用 key parser 的九项实际派发顺序为 none、befriend、reconcile、protect、
antagonize、conquer、dominate、comply、defy，不能用脚本选项顺序替代。

wargoal 消费者 `0x141643740` 分别保存 RDX 国家 ROOT、R8 target country 和 R9 CState。
`0x141643849` 构建国家 tag 5，`0x14164385d` 注册 tag `0x4c` 的 `target_state`，
`0x141643886` 注册 tag 5 的 `target_country`，`0x1416438ea` 调用实际评分 wrapper。
`target_state` 的全局 key `0x145a94968` 由独立字符串注册链定位，调用者以 `0x1407ed5f0`
解析状态 ID，其诊断直接引用 CState TypeDescriptor `0x145244320`；它不能误记为 wargoal 对象。
仅 play ID 非 -1 时另注册 tag `0x1c`；修订 4 没有完整类型证明，因此该对象明确记录为
`unprojected_unknown`、`reader_authorization=false`，compiler 不产生对应 binding。

secret 消费者 `0x141643600` 保存 R8 actor country 与 R9 target country；`0x141643693`、
`0x1416436a6` 产生两个国家 tuple，`0x1416436c2` 注册 `target_country`。
parser `0x14164b400` 独立区分 `score` 与 `trigger`，消费者先在 `0x1416436da` 执行原生 trigger，
仅通过时才在 `0x1416436fd` 计算 score。两个评分路径调用原 wrapper `0x140ed4290`。
上层默认／活动策略合并为加法；wargoal 的 liberate_country 还包含额外原生 tail，均保持原调用。

独立 inventory 将两个 map 和 secret enum entry 登记为结构观察，仅精确普通 `wargoal_scores.<enum>`
及 `secret_goal_scores.<enum>.score` 登记 direct 动态评分。未知、重复、前缀、scalar、替代嵌套形状、
重复 score 与容器 writer 均拒绝。compiler 用同一校验解析固定底本的 21 个 wargoal 和七个 secret score，
验证每个实际 reader；trigger 保持原生筛选器，不从容器或评分上下文继承授权。

### wanted_navy_size 与 ship_construction_output_multiplier

修订 5 追加 22 段观察。navy atom token `0x5c57` 经 selector 14 定位 parser `0x141641888`，
以 parser subobject `0x20b8-0x658` 精确定位成员 `0x1a60`。
实际 helper `0x1415ad310` 在 `0x1415ad3b7` 和 `0x1415ad40d` 分别求值默认与活动策略，
`0x1415ad412` 相加。主调用者从空上下文构建 country tag 5 ROOT，`0x1415ad21b` 调用 helper；
wrapper `0x140d9f820` 把同一 tuple 传入三个求值槽。该 helper 的其他调用者部分接受外部上下文，
此证据只锚定已证明的国家主调用路径，并保留其他原生调用语义。

ship construction token `0x622a` 精确定位 parser `0x141641cb2` 和成员 `0x1be0`。
消费者 `0x1415ada43` 构建空上下文，`0x1415ada69` 置 country tag 5 ROOT，
默认成员在 `0x1415adadb` 求值；活动策略内联读取同一成员 `+8` 并在三个槽使用同一 country tuple。
`0x1415adc97` 将结果相加，所以合同为 `additive_ship_construction_output_multiplier`。
字段名中的 multiplier 不能把实际策略合并运算误写为乘法。

上述修订 5 证据不替换原生海军舍入、维护、预算及最终造船运算。修订 5 当时只找到
`wanted_num_supply_ships` 的解析成员；修订 7 由独立实际消费者链补足，不能从相邻 navy/ship 成员继承上下文。

### 十条标量链与博弈实例

修订 6 保留修订 5 的全部合同和前 325 段观察，新增十个精确字段及 63 段原始字节。
每条链独立核对精确 NUL 字符串、atom token、压缩派发、成员、真实求值器及上层消费者。
它们均构建 country tag 5 ROOT；下表的额外对象只适用于对应字段。

| 字段 | 成员 | 实际求值 VA | 额外对象与原生合并 |
|---|---|---|---|
| `aggression` | `0x1160` | `0x14164546f` | `target_country` 为 country；默认与活动策略相加 |
| `nationalization_desire` | `0xd78` | `0x141647ecd` | 无；默认与活动策略相加 |
| `max_active_stances` | `0x498` | `0x14164805c` | 无；默认与活动策略相加 |
| `wanted_marines` | `0x18e0` | `0x14164441d` | 无；默认与活动策略相加，保留后续舍入 |
| `economic_vs_government_spending_balance` | `0x1760` | `0x14164684d` | 无；默认与活动策略相加 |
| `target_marine_formation_size` | `0x19a0` | `0x1416445ad` | 无；默认与活动策略相加，保留后续舍入 |
| `unacceptable_infamy_level` | `0xfe0` | `0x1416440fd` | 无；首个正值活动策略覆盖，否则使用默认值 |
| `undesirable_infamy_level` | `0xf20` | `0x141643f6d` | 无；首个正值活动策略覆盖，否则使用默认值 |
| `diplomatic_play_neutrality` | `0x608` | `0x14164783c` | 无；只累加正值活动策略 |
| `diplomatic_play_boldness` | `0x6c0` | `0x1416476aa` | `diplomatic_play` 为博弈实例；活动策略经原生随机缩放后相加 |

两个 infamy 字段的 `first_positive_infamy_limit_override` 不能降格为 additive。
neutrality 的正值筛选与 boldness 的原生随机程序也保留原调用，不声称完整下游数值等价。

boldness 消费者以 tag `0x1c` 和传入对象的 ID 注册 named `diplomatic_play`。
类型证明来自独立的 `CDiplomaticPlayWarLink` RTTI：TypeDescriptor `0x145720d10`、
COL `0x144c31608`、vftable `0x144716e80` 的虚槽 `+0x28` 指向 `0x14277ac90`。
该方法验证 tag `0x1c` 后调用 ID resolver `0x1407e7250`，其数据库缺失诊断直接引用
`CDiplomaticPlay` TypeDescriptor `0x14546bc20` 的 `+8`；随后从实例读取 war ID 并输出不同 tag。
这排除了仅按 tag 数字猜类型。compiler 只给 boldness 添加精确 `diplomatic_play` 辅助 binding，
没有新增 play getter；原 r5 wargoal 可选对象的 `unprojected_unknown` 合同保持不变。

inventory 复用逐字段 verified 证据入口，拒绝缺失证明、未知来源、相邻名称、额外路径、重复及非普通赋值。
compiler 对新增标量规则和显式卡片逐个验证实际输入及 country ROOT，不能因 reader 只读取 ROOT
就擦除 aggression 的 target 或 boldness 的辅助对象。

### treaty、区域 stance 和两条舰船标量链

修订 7 完整保留修订 6 前 388 段观察和全部消费者合同，再追加四条独立链及 64 段原始字节。
生产再次重读实际 EXE 的全部 452 段观察；地图父容器只登记结构观察，精确数值叶子独立登记。

`treaty_category_scores` 的 token `0x37d3` 经 parser `0x141640e0a` 定位成员 `0x1f0`。
key callback `0x14163e7d0` 在原 token 表 `0x144546938` 中解析九项实际 enum：economy、trade、
military、military_defense、ideology、expansion、power_bloc、other、none；9 为无效 sentinel。
每项精确字符串和 atom 均单独冻结。实际消费者 `0x141643a00` 按 enum 选择 `member+enum*8`，
构建空上下文及 country tag 5 ROOT，`0x141643aa9` 调用数值 wrapper。默认/活动策略分别由
`0x141598094`/`0x1415980ba` 求值并在 `0x1415980bf` 相加。合同为
`additive_treaty_category_score`，单位 score，不改动后续原生随机类别选择。

`strategic_region_stance_type_scores` 的 token `0x60b0` 经 parser `0x141641aa8` 定位成员 `0x470`。
callback `0x141648950` 使用真实 stance definition database 解析名称，哈希并比较实际定义指针；
定义只选取 map 项，不是新增脚本对象。原件 `common/ai_strategic_region_stance_types/00_ai_strategic_region_stance_types.txt`
固定 SHA `add54c251b0fb2a37a6038b308ed9e67709d44f7ec0a5aac0bc03346afccb91d`，
四项唯一普通定义为 stance_none、stance_conquer_region、stance_protect_region、stance_colonize_region。
生产验证完整来源集合、SHA 和精确 key，新增、删除、覆盖、重复、前缀与替代形状均不能继承授权。

实际 stance consumer `0x141648150` 保留 country ROOT、named `target_region` 的 tag `0x52` 区域实例，
以及 named `region_score` 的 tag 1 标量，后者来自本国 AI 对该区域的缓存分数。两个 named key 各有独立
精确字符串及全局注册链。区域类型来自 `CDatabaseObjectLink<CStrategicRegionsDatabase>` 的
TypeDescriptor `0x145721980`、COL `0x144c32f08`、vftable `0x14471a600`，其虚槽 `+0x28`
进入 `0x142784d40`，真实数据库 lookup `0x1411352c0` 后从区域对象 `+0x10` ID 输出 tag `0x52`。
这与 consumer 的 ID 成员一致，不按 tag 数字猜测。`0x14164842a` 执行数值求值；上层先把默认策略
插入列表 (`0x1415ca52d`)，再追加活动策略 (`0x1415ca548`)，遍历同一列表执行 debug/普通两条路径并相加。
合同为 `additive_region_stance_score`，单位 score；即使 reader 只读 ROOT，也不能擦除区域对象或标量辅助上下文。

`wanted_num_supply_ships` token `0x6229`、parser `0x141641bcb` 定位成员 `0x1b20`。
实际 consumer `0x1415ad4a0` 构建空上下文和 country ROOT，默认数值对象 `member+8` 在
`0x1415ad63f` 求值，活动策略相同对象在 `0x1415ad7f2` 求值，`0x1415ad8cf` 相加。
合同为 `additive_supply_ship_count_target`，单位 ships。

`max_ship_design_complexity` token `0x6227` 经独立压缩 selector/destination 定位 parser
`0x141641bb6`、成员 `0x1d60`。实际 consumer `0x1414b6980` 同样以 country ROOT 评价默认
(`0x1414b716c`) 和活动策略 (`0x1414b730f`)，`0x1414b73e3` 相加。
原件明确单位为舰船设计改装总等级，因此合同为 `additive_ship_design_complexity_limit`，单位 modification_levels。
两条舰船链都将同一国家 tuple 放入三个求值槽，实际 inline evaluator 为 `0x140daa040`；
默认及非默认同名字段的遍历/合并有实际证据，原生舍入、最终建造及设计运算保持原调用。

两个 map 的 inventory/compiler 共用严格普通数值子块检查。未知 key、重复、scalar、前缀、额外嵌套和
容器 writer 均拒绝。`target_region`、`region_score` 和 stance definition 身份不授予新 getter。
舰船改装 `ai_weight` 另从独立 equipment baseline 保留 `ship_modification_type` candidate 完整上下文，
国家材料和违约 reader 必须逐个验证；fixed_point 文档本身不授权 scalar 或缺省初始化。

### 显式布尔事实使用的原版脚本谓词

[scripted-predicate.json](victoria3-1.14.5-scripted-predicate.json) 固定 SHA-256
`128c85f83fdc007a42d19c97dad7bf8d61351be42121095e680ed1028a38918c`，记录锁定原版
25 份 `common/scripted_triggers` 来源的独立 SHA 与 `any_insurrection_ongoing` 的唯一 AST。
该定义是 `any_political_movement = { is_insurrectionary = yes }`；它不是 builtin，
也不能替换为 `has_insurrectionary_interest_groups`。

显式卡片的 `no_insurrection` 直接布尔模板读取该谓词的否定值，保留原 engine 身份与国家 ROOT。
接口仅接受无参数、无路径、无数值边界的精确布尔签名。生产边界须调用
`decision_interfaces.verify_scripted_trigger_game(game)` 重读来源集合、原始 SHA 和唯一精确 AST；
`scripted_trigger_snapshot()` 只核对历史证据身份，不证明当前安装或游戏行为。

## 入口与未证明范围

`pdx.situated.engine_scope.strategy_snapshot()` 固定修订 7 身份并验证新增精确合同，不声称当前游戏验证；
`strategy_evidence(game, inputs)` 核对 EXE、所有原始字节观察及全部来源 SHA；
`verify_strategy_game(game)` 在生产边界读取真实五份原件并硬失败，不回退离线快照。
该生产接口也验证制度与区域 stance 定义原件集合和 SHA，保留五份 `strategy_sources` 的既有含义，并把独立定义来源指纹附入返回证据。
返回的 `StrategyScopeEvidence`／`StrategyConsumerEvidence` 沿用既有接口。

`wanted_construction_input_goods_surplus_ratio` 在锁定原版文本与 EXE 精确 NUL atom 中未找到，任务身份仍未解决。
近似的 `wanted_construction_ratio` 不能替代它。`00_ai.txt` 719–722 行的机构 spending 项是原生常量，
不是额外动态 script-value 消费者。`desired_tax_level` 和其他相邻字段仍未授权；
法律阈值以外的字段不能继承新增法律实例证据。
`colonial_interest_ratio` 及尚未证明的其他策略 map 继续 pending；找到解析成员或临近消费者不能替代完整读取链，
也不能把未找到证据升级为 unsupported。

`company_default_evidence(game, inputs)` 为独立 inventory 验证缺省公司权重的原始 EXE 字节、实际
`common/defines/00_ai.txt`、基础公司原件和完整父公司来源集合，并返回对应真实指纹。
缺失、漂移或额外公司覆盖均不得推断缺省权重；initializer 仍只适用于精确缺少 `ai_weight` 的定义。
