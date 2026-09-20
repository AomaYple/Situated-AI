# 探针 mod（游戏实测包）

这里的东西**不是工具链的一部分**，而是一个**最小 mod 源码**：它的唯一用途是把
知识库里「只能进游戏才能定」的问题一次性问清楚。

## 为什么需要它

知识库里有 100 多条问题，答案不在文件里 —— 引擎的加载语义、运行期字段行为、
调用语法。文件只能证明「原版没这么写过」，证不出「引擎会怎么处理」。
四条实测配方（脚本化测试 / 调试日志 / 最小 mod / 双 mod 冲突）写在
[`docs/victoria3-modding/04-脚本系统.md`](../../docs/victoria3-modding/04-脚本系统.md) 的 §13.1。

这个目录就是**配方 C（最小 mod）与配方 D（双 mod 冲突）的具体实现**，并且做到了
「一次启动收工」：全部实验都挂在**两个决议 + 一个月度 on_action**上，点一下就跑完，
其余交给日志。

## 三步用法

```powershell
.venv\Scripts\v3.exe experiment launch --risky   # 一键：装探针 → 只启用探针 → 以 -debug_mode 启动
#  —— 进游戏/读档（on_game_started 会自动跑自检）、跑满一个月、退出 ——
.venv\Scripts\v3.exe experiment collect          # 收割 logs/，按实验编号归位证据
.venv\Scripts\v3.exe experiment restore          # 还原原来的 mod 启用列表
.venv\Scripts\v3.exe experiment uninstall        # 收工后移除
```

launch 为什么能一键：**启用哪些 mod** 由用户目录的 content_load.json 决定
（启动器写、游戏读），**调试模式**就是给 victoria3.exe 加 `-debug_mode`
（游戏自带 launcher-settings.json 里「以调试模式打开游戏」用的就是这个参数）。
它先备份那份 json，再只写上探针 mod，然后直接起 exe —— 全程不用点启动器。

> ⚠️ **语法候选单独一个 mod（zz_probe_risky）**：那些候选是**故意写错**的，
> 理论上可能让游戏在加载阶段退出 —— 所以默认不启用，要问「引擎认不认这些写法」时
> 用 `v3 experiment launch --risky` 单独起一次。候选本身不会影响主探针的读数。
> （首次实跑时游戏确实在加载期退出过一次，但当时探针 loc 还缺 BOM —— 后来同一批候选
> 照跑无事，**「候选致命」这条并没有独立复现**。）

## 判定怎么读

优先走日志：`-debug_mode` 下引擎会把**未知键 / 重复定义 / 语法错 / scope 错误**写进
`logs/`（`v3 experiment collect` 会把它们按实验编号归位）。2026-09-20 起又加了一层：
**候选自己用 `debug_log` 把结论写进日志**（原版在 `common/on_actions/00_code_on_actions.txt:7353`
就这么用），于是「效果有没有跑、`$参数$` 被替换成什么」不用再靠人眼。

仍然只能肉眼看的五处：

| 看什么 | 判定哪条 | 怎么读 |
|---|---|---|
| **国库数字** | P2 裸同名键、P11 双 mod 顺序、P8 的 `after` / `show_as_tooltip` | 点决议前记一次，点完再记一次，差值见下表 |
| **事件窗口** | P8 的 `is_popup` | 带 `is_popup = yes` 的那个事件是否强制弹窗 |
| **决议标题** | P10 本地化 `:数字` | 第二个决议的标题显示「无版本号」还是「带版本号 1」 |
| **月度事件** | P24 `weight_multiplier` | 跑满一个月后通知栏里有没有 `zzprobe.10` |
| **进度条** | P7 `display_progressbar_as_months` | `zzprobe_je` 与 `zzprobe_je_control` 的进度条哪个显示「月」 |

## 国库差值的读法（P2 / P11）

主决议的 `when_taken` 依次调用：

| 调用 | 原版行为 | 本探针改写后 | 读数 |
|---|---|---|---|
| `debug_success` | `+50,000` | `+1`（**不带前缀**重定义） | `+50,000` = 原版赢；`+1` = 探针替换成功；`+50,001` = 两者都跑（合并）；报错 = 重定义被拒 |
| `zzprobe_control_effect` | — | `+1M` | 对照项：证明「决议 → scripted_effect」链路是通的 |
| `zzprobe_shared` | — | A 与 B 都用 `REPLACE_OR_CREATE` 写它（`+1M` / `+2M`） | `+1M` = A 生效；`+2M` = B 生效；`+3M` = 叠加（说明不是整体替换） |

把「谁生效」与你在启动器里的 mod 顺序对照，就得到**同名键的优先级规则**。
这一条如果想双向确认，把 A/B 顺序对调再跑一次（**唯一需要第二次启动的实验**）。

`zz_probe_risky` 的自检效果（`zzprobe_r_selftest`）另有一组金额，全跑通是 **+21M**：
`c1` 显式 1M / `c1` 省略 3M / `c2` 显式 2M / `c2` 省略 4M / `c3` 5M / `c4` 6M ——
每个候选都调用两次（显式传参一次、省略参数一次），所以国库差值能反过来验证
「默认值语法到底有没有生效」。

## 目录结构

```
zz_probe_a/                  主探针：一个决议跑完大部分实验
├─ common/decisions/         两个决议（跑全部 / 本地化版本号观察点）
├─ common/scripted_effects/  裸同名键重定义、对照效果、双 mod 共享键、同 mod 内顺序
├─ common/game_rules/        apply_modifier 候选
├─ common/journal_entries/   JE 待验证字段（骨架逐字抄自原版）+ 无该字段的对照组
├─ common/scripted_buttons/  selected / cooldown / root scope
├─ common/scripted_progress_bars/  自定义样式名候选
├─ common/on_actions/        月度脉冲 → zzprobe.10（weight_multiplier）
├─ events/                   after / is_popup / orphan + 重名 namespace
└─ localization/             中英文文案 + 版本号观察点
zz_probe_b/                  只为「双 mod 同名键顺序」存在（一个键）
zz_probe_risky/              故意写错的语法候选（默认不启用，见上）
├─ common/scripted_effects/  P5 四个 $PARAM$ 候选 + 自检效果 + 子目录反证文件
├─ common/scripted_triggers/ P1 has_game_rule 块形式 / 标量对照
├─ common/scripted_lists/    U15 定义 + 两个调用候选（实测都被拒）
├─ common/scripted_modifiers/ U14 定义（调用候选在 events/ 里）
├─ common/on_actions/        on_game_started → 自检（进游戏就跑）
├─ common/decisions/         自检决议（备用触发点）
└─ events/                   U14 四个调用候选放进 ai_chance（唯一会做加载期校验的位置）
```

**一个候选一个文件**是刻意的：语法错会让整个文件失效，混在一起就分不清是谁坏。

⚠️ **文件必须平铺，不能放子目录**：`common/<库>/` 的子目录不被引擎枚举
（实测见下），放进 `zz_probe_p5_candidates/` 的候选连读都没被读。

⚠️ **本地化文件必须带 UTF-8 BOM**：第一次一键启动时游戏报
`Missing UTF8 BOM in 'localization/.../zz_probe_l_english.yml'`（error.log），
随后退出。探针现在**每个 `.txt` / `.yml` 都带 BOM**（`.txt` 只是建议、非致命），
`test_experiments.py` 有用例钉住这条 —— 它同时是 doc 06 那条结论的**独立实证**。

## 安全性

* 不碰你的存档：探针只作用于**新开的**那一局，效果仅限于国库与一个探针 JE；
* `install` 只写本机 mod 目录（`Documents\Paradox Interactive\Victoria 3\mod\`），
  不写游戏安装目录；已存在时**不覆盖**（除非 `--force`）；
* 收工后 `v3 experiment uninstall` 一条命令移除；本目录仍在仓库里，随时可重装。

## 实跑结果

### 第一批（2026-09-20，主决议 + 事件）

| 编号 | 结论 | 引擎日志原文（节选） |
|---|---|---|
| **P2 裸同名键** | **先到先得**：后写的同键定义**不会被创建**，不合并、不报错 | `Duplicated key debug_success will not be created from file: common/scripted_effects/zz_probe_effects.txt:4` |
| **P11 双 mod 抢同一个键** | **先加载者胜**：A（+1M）生效、B（+2M）未生效；`REPLACE_OR_CREATE` 不会让后写的 mod 覆盖先写的 | 该键**没有**重复警告（说明是合法替换操作） |
| **P6 进度条样式** | **不接受自定义样式名**（硬报错） | `Error: "Unexpected token: zzprobe_made_up_style"` in `zz_probe_bars.txt` |
| **P8 `orphan`** | 声明「这个事件不该被触发」；有调用者就警告 | `Event zzprobe.3 is scripted as an orphan, but has callers` |
| **P8 `after`** | 效果**确实执行** | 国库 +2M 到账 |
| **P8 `show_as_tooltip`** | 效果**不执行**（只生成 tooltip） | 国库**没有** +10M 跳变 |
| **P8 `is_popup`** | `is_popup = yes` 的事件**强制弹窗**；不带的事件只进右侧通知栏（同点触发的 .4/.5 对照） | 肉眼差分 |
| **P3 重名 namespace** | **可以跨文件续写** | `Event test.99999 is orphaned`（只提示无调用者） |
| **P10 本地化 `:数字`** | `:1` 没覆盖 `:0`（与「先到先得」一致） | 游戏内文本显示 `:0` 那句 |
| **P7 JE 字段** | 字段都被接受；引擎固定找 `<JE键>_reason` / `<JE键>_goal` 两条 loc | `Journal entry is missing loc for zzprobe_je_reason!` |
| **P9 按钮** | `desc` 是 loc 键；`selected` / `cooldown` 被接受 | `Unrecognized loc key zzprobe_button_desc` |
| **P21 `apply_modifier`** | `game_rules` 的**形状**必须先对（`rule = { default = X  X = { … } }`）；上一版写成 `settings = { … }` 被拒 | `Error: "Unexpected token: zzprobe_rule_setting"` in `zz_probe_game_rules.txt` |
| **额外事实 1** | 本地化 `.yml` **必须**带 UTF-8 BOM（硬要求）；脚本 `.txt` 也**建议**带（非致命，`lexer.cpp:285`） | `Missing UTF8 BOM in '…'` |
| **额外事实 2** | **决策的 `ai_chance` 不认 `base`**（与事件不同）—— 决策用的是 `value` + `if/add`，见 `common/decisions/000_decisions_help.txt:42,123`；事件用的是 `base` + `modifier`，见 `events/1848.txt:44` | `Error: "Unexpected token: base" in "common/decisions/zz_probe_decisions.txt"` |
| **额外事实 3** | 上面那条**非致命**：`ai_chance` 块被忽略，决议照样出现并可点 | 两个决议都能点 |

### 第二批（2026-09-20 第二轮）

| 编号 | 结论 | 引擎日志原文（节选） |
|---|---|---|
| **P25 `common/<库>/` 的子目录** | **不被枚举**：放在子目录里的定义引擎**连读都不读**（同 mod 平级文件都报了 BOM 提醒，子目录里的一个都没报；调用时报 `Unknown effect`）。旁证：原版 8 个 `common/` 库目录**0 个子目录**，本机 20 多个 mod 也 0 个；引擎枚举日志 `virtualfilesystem.cpp:420 … (.txt, , 0)` 末位参数为 0 | `[jomini_effect.cpp:542]: Unknown effect zzprobe_p5_c1 at common/decisions/zz_probe_decisions.txt:19` |
| **同一 mod、同一文件内重复事件 id** | **先到先得**（与跨文件同键同规则）：后写的那份不生效 | `Duplicated event ID 'zzprobe.10' found. New Location: 'events/zz_probe_events.txt:49', Previous Location: 'events/zz_probe_events.txt:73'` |
| **on_action 的事件表** | 事件必须写 `namespace.id`，写数字 id 会报错 | `[jomini_onaction.cpp:290]: Invalid event id 1000 At: common/on_actions/zz_probe_on_actions.txt:12` |
| **U15 `scripted_list` 调用** | 两个候选**都被拒**（定义形态 `base` + `conditions` 合法） | `Error: "Unexpected token: scripted_list, near line: 3"` / `Unexpected token: zzprobe_list` |
| **U14 `scripted_modifier` 定义** | 定义形态（`name = { if = { limit = … factor = … } }`）被正常解析 | 无报错（对照：同目录下写错的文件都会报） |
| **额外事实 4** | `current_value` 引用**未创建**的变量 → 引擎**每帧**报一条错：8 分钟 1772 条、把 `error.log` 刷到 500 KB 并触发日志滚动（探针已改为先把变量建出来） | `[jomini_scriptvalue.cpp:1659]: Value of wrong type in 'common/journal_entries/zz_probe_je_control.txt:99'. Got value of type 'none'` |
| **额外事实 5** | `debug_log` 是可用的**效果**（原版 14 处实用），可以把脚本自身的判定写进 `logs/debug.log` —— 探针从这一轮起用它自报结论 | `debug_log = "Objective completed"`（`00_code_on_actions.txt:7353`） |

### 第三批（2026-09-20 第 2–4 轮：语法候选 + 自检）

这一批把「故意写错的候选」全部跑完，判定方式改成**候选自己用 `debug_log` 报结论**（`grep ZZPROBE`）。

| 编号 | 结论 | 引擎日志原文（节选） |
|---|---|---|
| **P25 `common/<库>/` 的子目录** | **不被枚举**：子目录里的定义引擎连读都不读（同 mod 平级文件都报 BOM 提醒，子目录 6 个一条没有） | 调用时 `[jomini_effect.cpp:542]: Unknown effect zzprobe_subdir_never at common/scripted_effects/zz_probe_r_selftest.txt:18` |
| **P1 `has_game_rule` 块形式** | **不存在**：块被整个当成参数，先拿 `{` 查数据库、再把块内 `value` 当触发器解析 → 只能写标量 | `Unknown trigger type: value, near line: 5` + `PostValidate of trigger 'has_game_rule' returned false` + `Error: has_game_rule trigger [ Invalid database object '{' ]` |
| **P1 参数语义** | 参数是**设置名**（settings 键）而**不是规则名**：用规则名报 `Invalid database object '<规则名>'`；改用原版设置名 `free_construction_unscaled` → 零报错 | `Error: has_game_rule trigger [ Invalid database object 'zzprobe_rule' ]` |
| **P5 `$X\|默认值$`** | **不支持**：引擎把 `AMOUNT\|3000000` **整串当参数名** | `[jomini_script_argument.cpp:217]: Compiling source for zzprobe_p5_c1 failed for missing arguments: AMOUNT\|3000000` |
| **P5 `$X=默认值$`** | **不支持**：整个赋值被解析坏（`$` 都不配对） | `Missing $ to end argument around …zz_probe_p5_c2.txt:3` + `Badly read script value $AMOUNT` + `Unknown effect =` |
| **P5 显式传参 / scope 传参** | **都可用**：自检把实参写进了日志 | `common/scripted_effects/zz_probe_p5_c1.txt:13: ZZPROBE P5C1 amount=1000000$]`、`…zz_probe_p5_c3.txt:6: ZZPROBE P5C3 scope=root$]` |
| **U14 `scripted_modifier` 调用** | **调用点 = 模板名当键**（引擎会去解析该模板）；另外三种写法全被拒 | ④ `modifier = { scripted_modifier = 名字 }` → `unknown command 'scripted_modifier' for MTTH`；③ `modifier = { 名字 = yes }` → `Unknown trigger type: zzprobe_modifier`；① 模板名当键 → `Unknown modifier 'if' / 'limit' / 'always', referenced at …:36`（报错指向**模板体**，说明调用点认了） |
| **U14 模板体** | 官方 md 的 `if = { limit = … factor = … }` 形状在 `ai_chance` 里被当成「未知修饰符」→ **模板体形状仍【未确认】** | 同上第 ① 条 |
| **U15 `scripted_list` 调用** | 两个候选**都被拒**（定义形态 `base` + `conditions` 合法） | `Unexpected token: scripted_list` / `Unexpected token: zzprobe_list` |
| **P21 `apply_modifier`** | 语法被接受，但 **md 的示例键不是真修正** | `[gamedatabase.h:781]: Failed to cache an item for Static Modifiers! Key: very_easy` |
| **P17 YAML 块标量** | **不支持**：loc 解析器要求引号字符串；游戏内该键**显示为原始键名**（截图实证：两个【ZZ 探针】决议的描述就是 `zzprobe_r_*_desc`） | `Missing quoted string value for key 'zzprobe_r_selftest_decision_desc'` + `Missing colon (:) separator` + `Invalid character '（' in key name '描述第一行（字面量'` |
| **P24 `weight_multiplier`** | 放 **on_action 层**（官方 md 形状）→ 加载期零报错；塞进 `events` 事件条目 → 被当成事件 id | `[jomini_onaction.cpp:290]: Invalid event id 1000 At: …zz_probe_on_actions.txt:12`；⚠️ 月度事件本身**没触发** —— 探针挂错了 on_action（原版国别月度事件在 `on_monthly_pulse_country`，`on_monthly_pulse` 的 scope 不是国家），属探针形状问题 |
| **P7 三个 JE 字段** | **至少有一个会让 JE「加进来就关掉」**：实验组当天走完「添加 → 已关闭 → 从日志移除」；对照组正常驻留并显示 `进度：1.6% (1.00/60.0)` | 游戏内动态三条（截图实证）；具体是哪个字段【未确认】—— 三个字段是打包测的 |

**这一批踩出来的坑（都已写进文档与探针注释）**：

1. **子目录**：候选必须平铺（见 P25）；
2. **别在 `if/else` 链里调用未加载的效果** —— 引擎报 `Else/else_if not following an if or else_if`
   并在**同一秒崩溃**（第 3 轮整轮报废，`crashes/…/minidump.dmp`）；判定改用「两条 `if` + `NOT`」；
3. **事件 `ai_chance` 在 `option` 里**，写到事件体上会 `Unexpected token: ai_chance`；
4. **`has_game_rule` 的参数是设置名**，用规则名会把判定污染成「语法错」；
5. **`weight_multiplier` 是 on_action 的字段**，`events` 表是裸 id 列表；
6. **同一个 on_action 两个 `effect` 块** → 引擎取最近的那份，原版被丢掉（官方 md 规则的实测复现）。

## 下一轮（如果要继续收口）

只剩这些还没定，探针已经把形状摆好、改一处就能跑：

| 待办 | 怎么改 |
|---|---|
| P7 三个 JE 字段里**是哪一个**关掉了 JE | 把 `zz_probe_je.txt` 拆成三个「单字段 JE」（各挂一个字段），再跑一次即可定位 |
| P24 月度事件链 | 把 `zz_probe_a/common/on_actions/zz_probe_on_actions.txt` 的 `on_monthly_pulse` 改成 `on_monthly_pulse_country`（原版国别月度事件挂在那里） |
| U14 模板体形状 | 在 `zz_probe_risky/common/scripted_modifiers/zz_probe_s1_define.txt` 里试「修饰符规则表」形状（键 = 修饰符名），而不是 md 的 `if/limit` |
| U15 `scripted_list` 的调用点 | 脚本侧两个候选已被拒；剩下的方向是 `.gui` 侧（要另做界面实验） |

## 覆盖不到的部分



* **GUI 侧**（`scripted_list` 在 `.gui` 里的引用方式、界面绑定）：探针只测脚本侧，
  GUI 那部分需要另做界面实验；
* **平衡性与 AI 行为**：那是另一类问题（不在「未确认」清单里）；
* **多人/大厅相关行为**：单机跑不出大厅差异，需要联机会话（`is_shown_in_lobby` 的**字段本身**已被单机测到副作用：见 P7 那条 JE 关闭）；
* **`*_desc` 触发器本地化那 30 条**：本地没有任何引用点，配方 A/B/C/D 都不对症。
