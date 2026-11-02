# Situated 引擎静态证据

本目录保存版本固定的原始字节证据。它们属于 `static_check`，不执行游戏，也不证明运行效果、数值平衡或
完整下游行为。生产入口必须重新核对当前 EXE 和原版来源；离线快照只提供历史证据身份。

## 策略作用域修订

| 修订 | 固定文件 | SHA-256 | 用途 |
|---|---|---|---|
| 初版 | [strategy-scope.json](victoria3-1.14.5-strategy-scope.json) | `93947c66bfddd6123633528d66b10a15f334a925b6800ccfa8a4413db85b1944` | 保留原始字节与当时的授权边界，不再作为当前入口 |
| 修订 2 | [strategy-scope-r2.json](victoria3-1.14.5-strategy-scope-r2.json) | `e0b60c432cfe74a5b85c86d7dd401ac7305450446312f9da73c644b729385ae4` | 保留 15 个逐字段消费者，148 段原始字节观察 |
| 修订 3 | [strategy-scope-r3.json](victoria3-1.14.5-strategy-scope-r3.json) | `83b369cd1f40e588428410912cfb9fcea43f823f0604ee38283bcbf7677adba3` | 当前 15 个逐字段消费者，169 段原始字节观察；补齐法律实例类型 |

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

## 入口与未证明范围

`pdx.situated.engine_scope.strategy_snapshot()` 固定修订 3 身份并验证新增精确合同，不声称当前游戏验证；
`strategy_evidence(game, inputs)` 核对 EXE、所有原始字节观察及全部来源 SHA；
`verify_strategy_game(game)` 在生产边界读取真实五份原件并硬失败，不回退离线快照。
该生产接口也验证制度定义原件集合和 SHA，保留五份 `strategy_sources` 的既有含义，并把制度来源指纹附入返回证据。
返回的 `StrategyScopeEvidence`／`StrategyConsumerEvidence` 沿用既有接口。

`wanted_construction_input_goods_surplus_ratio` 在锁定原版文本与 EXE 精确 NUL atom 中未找到，任务身份仍未解决。
近似的 `wanted_construction_ratio` 不能替代它。`00_ai.txt` 719–722 行的机构 spending 项是原生常量，
不是额外动态 script-value 消费者。`desired_tax_level`、`diplomatic_play_boldness` 和其他相邻字段仍未授权；
法律阈值以外的字段不能继承新增法律实例证据。

`company_default_evidence(game, inputs)` 为独立 inventory 验证缺省公司权重的原始 EXE 字节、实际
`common/defines/00_ai.txt`、基础公司原件和完整父公司来源集合，并返回对应真实指纹。
缺失、漂移或额外公司覆盖均不得推断缺省权重；initializer 仍只适用于精确缺少 `ai_weight` 的定义。
