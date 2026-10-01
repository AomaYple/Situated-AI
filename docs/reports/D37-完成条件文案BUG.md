# D37：详情面板「如果完成」那一格显示 `BUG: set_strategy missing perspective`

卡片：t37（implementation）。日期：2026-10-01。范围（inScope）：`mod/data/ru_defeat.toml` /
`mod/common` / `mod/localization` / `src/pdx/modgen.py` / `tests/test_modgen.py` / 本报告。
实机不在本卡（由功能工程师照 §4 的核对单做 10 分钟预检）。

**一句话结论**：根因在我们**裸写**了那条递牌 —— 引擎把 `on_complete` 渲染成面板「如果完成」
那一格的 tooltip，而 `set_strategy` 的 effect_localization 里**只登记了 `global`**，那一格要的是
`first` ⇒ 引擎拼不出句子，就把 `BUG: set_strategy missing perspective` 当文案显示。
修法：在**生成面**只给「落在玩家可见块」的那条递牌包一层
`custom_tooltip = { text = <我们自己的键> set_strategy = … }`（原版可见块里 356 处先例），
数据面补一个 `tooltip` 字段 + 一条本地化键；**不改判据、不覆盖原版表、不新增产物**。

## §1 根因：三件事凑在一起

### 1.1 引擎怎么取那一格的文案

详情面板的四个 tooltip 槽在 `game/gui/journal_entry.gui` 里各自取一个 getter
（`:854` = `[JournalEntry.GetOnCompleteTooltip]`，同族还有 OnFail / OnTimeout / GetReason）。
即：`on_complete` 块里的东西**不是只执行不显示** —— 引擎会把它们编译成一句话给玩家看。
`set_strategy` 是「带参数的效果」，引擎给它拼句子的方式是按**视角**去
`common/effect_localization/<表>` 里查键。

### 1.2 原版那张表只登记了 `global`

出处（现读 1.14.5）：

| 文件:行号 | 原句 | 说明 |
| --- | --- | --- |
| `game/common/effect_localization/00_country_effects_loc.txt:40-42` | `set_strategy = { global = SET_STRATEGY }` | **只有 `global`** —— 这就是根因 |
| `game/common/effect_localization/00_country_effects_loc.txt:44-48` | `set_tax_level = { global/first/third = … }` | 同族「set 类」效果的常态：无正负值就写三键 |
| `game/common/effect_localization/00_country_effects_loc.txt:1-8` | `add_treasury = { global/global_neg/first/first_neg/third/third_neg = … }` | 有正负值的才写六键 |
| `game/localization/simp_chinese/effects_l_simp_chinese.yml:15` | `SET_STRATEGY: "[COUNTRY.GetName]实施了#variable [AIStrategy.GetName]#!战略"` | `global` 那句就是它 |

`first` 视角是「第一人称 = 玩家自己」，`third` 是「第三人称 = 别人」；面板上那一格用的是
`first` ⇒ 表里没有 `first` 就只剩 `BUG: … missing perspective` 这一条路。

### 1.3 我们差在哪

`mod/common/journal_entries/sitai_ru_defeat_window.txt`（生成物）本卡改前是：

```
	on_complete = {
		set_strategy = ai_strategy_reactionary_agenda
	}
```

裸写 ⇒ 引擎按 `first` 查 `set_strategy`，查不到 ⇒ 那一格显示 BUG 文本。
**实拍证据**：`tools/out/mem/t8-pre-check.json`（2026-10-01T05:53:41+08:00，功能工程师 15 分钟
可见性预检）的 `verdict.on_complete_bug` 逐字是
`如果完成段渲染出 (BUG: set_strategy missing perspective …)`；对照帧
`tools/out/t5-frames/t8-je4-detail.png`。

### 1.4 原版同类用法先例（本卡引用的四处，全部现读）

| 文件:行号 | 原句（节选） | 本卡用它证什么 |
| --- | --- | --- |
| `game/common/journal_entries/00_acw_entries.txt:40-43` | `custom_tooltip = { text = acw_will_happen_tt trigger_event = { id = acw_je_events.1 } }` | 可见块里包一层 `custom_tooltip` 的先例：**里面的效果照常执行**，那一格显示的换成 `text` |
| `game/localization/english/acw_text_l_english.yml:231` | `acw_will_happen_tt:0 "The American Civil War breaks out"` | 那个 `text` 键就是**一句静态话**（不带数据函数）—— 我们照同一取法 |
| `game/localization/simp_chinese/ai_strategies_l_simp_chinese.yml:70` | `ai_strategy_reactionary_agenda: "弘扬传统价值"` | 我们文案里「弘扬传统价值」的**官方译名出处**（照抄点） |
| `game/localization/english/ai_strategies_l_english.yml:75` | `ai_strategy_reactionary_agenda:0 "Foster Traditional Values"` | 同上（英文半边） |
| `game/common/journal_entries/05_grunderzeit.txt:111-119` | `immediate_all_involved` 里裸写 `set_strategy = ai_strategy_industrial_expansion` | 反过来证明「**不可见**块裸写没问题」⇒ `immediate` 那句保持不动 |

**为什么战略名要照抄、不写 `[AIStrategy.GetName]`**：JE 的 tooltip 上下文里**没有
AIStrategy 作用域**（那正是原版不把 `set_strategy` 放进可见块的坑）；
`[AIStrategy.GetName]` 只有 effect_localization 那条 `global` 句子能用。

### 1.5 可见块的常态写法（现扫读数）

`tools/out/d37-logs/04-visible-blocks.txt`（探针 `probe_visible.py`，任何深度都算）：

- 原版 JE 文件 **172** 个，`on_complete|on_fail|on_timeout` 可见块 **379** 个；
- 可见块里 `custom_tooltip` **356** 处、`hidden_effect` **89** 处、
  `custom_description` **0** 处、`set_strategy` **0** 处。

⇒ 就近取 `custom_tooltip`（`hidden_effect` 是「不想让人看见」用的，我们要的正是让人看见一句人话）。

## §2 修法取舍：为什么是生成面的 `custom_tooltip`

| 候选 | 做法 | 否掉的理由 |
| --- | --- | --- |
| A. 覆盖原版表 | 生成一个 mod 级产物 `mod/common/effect_localization/…`，给 `set_strategy` 补 `first` | **全局**改一条引擎表；而闸门 ① 看不见这个目录（`modguard.DEFINITION_DIRS` 只有 scripted_effects / static_modifiers / journal_entries / ai_strategies / defines），`OVERRIDE_BLOCKS` 里也只登记了 `NAI` ⇒ 等于绕过仓库「覆盖要登记」的机制 |
| D. `custom_description` | 用我们自己的键包住 | 可见块里**0 处**先例，引擎行为离线证不了 |
| H. `custom_tooltip`（**采用**） | 可见块里包一层，`text` 指我们自己的键 | 局部、零全局影响；仓库自己的工具链就认这个写法（`src/pdx/ai_surface.py:84` 把 `custom_tooltip` 列进 `LOGICAL_KEYS`）；原版 356 处先例 |

**为什么落在生成面而不是数据面**：数据面（`.toml`）只该说「这条递牌是什么、为什么」，
「怎么把它渲染成一句人话」是产物形状的事 —— 让每个档案各写一遍包装会把形状知识散到 9 份数据里。
数据面因此只多了一个 `tooltip = "<本地化键>"` 字段（**可见块必填、不可见块禁填**，两者都由生成器报错拦住）。

**新加的硬约束（出声而不是静默渲染成 BUG）**：

- 可见块（`on_complete` / `on_fail` / `on_timeout`）里的递牌**缺 `tooltip`** ⇒ `DataError`；
- 不可见块（`immediate`）里的递牌**给了 `tooltip`** ⇒ `DataError`（那个块不渲染 tooltip）；
- `tooltip` 指向的键**没在 `archive.localization` 里定义** ⇒ `DataError`（点名现有键集合）；
- 别的数据表写 `tooltip` ⇒ `DataError`（只有 `[journal_entry.signals]` 用得上）。

**事实表与反解器同步**：`facts()` 多了
`journal_entry.<JE>.on_complete.custom_tooltip = <键>` 这条事实，`_facts_journal` 反解时**穿过**
`custom_tooltip` 那一层（`text` 翻成 `.custom_tooltip`、内部效果照旧展开成 `.<块>.<效果>`）——
不然闸门 ④ 的集合比对会报「缺 1 多 1」，而那两行看起来像真丢了东西。

## §3 改动台账

### 3.1 生成面 `src/pdx/modgen.py`（9 处，按文件内顺序）

1. `SIGNAL_KEYS` 之后新增 `VISIBLE_BLOCKS: frozenset[str]`（`on_complete` / `on_fail` /
   `on_timeout`）与 `TOOLTIP_BLOCK = "custom_tooltip"`；注释里记着 356/89/0 的现扫读数、
   `00_acw_entries.txt:40-43` 的写法，以及**本卡用到的五处原版出处**（见 §1.2 / §1.4）。
2. `Param` 增字段 `tooltip: str = ""`（docstring 注明只有 signals 用）。
3. 新增 `_optional_text(raw, key, path) -> str`：缺省空串；给了就必须是非空字符串
   （防 `tooltip = 3` 生成 `text = 3`）。
4. `_params(..., *, allow_tooltip: bool = False)`：别的表写 `tooltip` ⇒ `DataError`。
5. `_signals` 两个调用点开 `allow_tooltip=True`，校验循环按 `set_strategy` / `clear_strategy`
   两条各自点名自己的块（既有两条报错文案**逐字未动**）。
6. 新增 `_check_signal_tooltip(signal, block, param)`：可见块缺键 / 不可见块多键都报错
   （报错文本里带上会渲染出来的 `BUG: set_strategy missing perspective` 与预检帧路径）。
7. `journal_text` 两个块改用 `_signal_node(p, block, archive)` 渲染，JE 生成注释里多一段
   ⚠️「可见面」说明。
8. 新增 `_signal_node(...)`：不可见块返回裸行；可见块校验键**确实定义在
   `archive.localization`**，返回 `("custom_tooltip", ["text = <键>", "set_strategy = <牌>"])`。
9. `facts()` 增 `journal_entry.<JE>.<块>.custom_tooltip = <键>`；`_facts_journal` 反解时穿过那层。

改动前后 revision（改前 = D36 报告 §3 的「改后」列，即本卡起点；本卡起点未另留副本 —— 如实记）：

| 文件 | 改前 | 改后（现读） | 行数 |
| --- | --- | --- | --- |
| `src/pdx/modgen.py` | 124,082 B / `4451a454…`（D36 交付） | **132,348 B / `4522cd80999f92732bd3e08a668d303c7dd987146659458d4728274aa13d5b69`** | 2,872 |
| `tests/test_modgen.py` | 62,406 B / `a00bf3c1…`（D36 交付） | **67,383 B / `9a84857cbac86dd4fa8fc6276a3a9bef2423a4fc97cd594c4f9c4f7ce005954e`** | 1,443 |
| `mod/data/ru_defeat.toml` | **未留改前副本**（t18 在 05:51:37–05:56:05 改过该文件，本卡开工时它已经是新 revision） | **63,798 B / `c0bccc0cfbaf668140235f46554bf461cc4edae6c1b3d4d1e2eaa31889487f01`** | 557 |

### 3.2 数据面 `mod/data/ru_defeat.toml`

| 改动 | 内容 |
| --- | --- |
| `[[journal_entry.signals.clear_strategy]]` 增一行 | `tooltip = "je_sitai_ru_reform_window_complete_tt"` |
| 同一处的 `why` 追加一段 | 说明 `on_complete` 是「如果完成」那一格的来源、原版表只有 `global`、裸写会显示 BUG、`immediate` 不带 tooltip 的原版先例（`05_grunderzeit.txt`）、`custom_tooltip` 356 处先例 |
| 新增 `[[localization]]` 键 `je_sitai_ru_reform_window_complete_tt` | 英文 `The state stands firm again and the window closes: Russia returns to the #variable Foster Traditional Values#! strategy.` / 中文 `国家重新站稳，改革窗口关闭：俄罗斯将回到#variable 弘扬传统价值#!战略。`；`why` 说清三件事（静态句照 `acw_will_happen_tt`、俄罗斯写死是因为本 JE 的触发就是 `c:RUS ?= this`、战略名照抄官方译名且 JE tooltip 没有 AIStrategy 作用域） |
| 文件头注释（键名口径那段）追加一句 | 第三处 `custom_tooltip` 的 `text` 键按原版 `*_tt` 后缀口径，我们用 `<JE 名>_complete_tt` |

### 3.3 测试面 `tests/test_modgen.py`

`SIGNALS` 夹具补一条 `[[localization]]`（`je_sitai_t1_window_complete_tt`）与
`clear_strategy` 的 `tooltip` 字段 —— **既有断言一字未动**；新增 5 条用例：

| 用例 | 钉的性质 |
| --- | --- |
| `test_可见块的递牌包上自己的文案` | 那一层真在 `on_complete` 里（没把 `immediate` 一起包）、`set_strategy` 照旧执行、键真进了两份 loc 产物、产物非注释行里不出现 `BUG:` |
| `test_可见块的递牌缺文案键要报错` | 缺 `tooltip` ⇒ 生成时报错（不是静默渲染 BUG） |
| `test_文案键必须在本地化里定义` | 挂个没定义的键 ⇒ 报错（键校验发生在**生成**时，不在 `load_data` 时） |
| `test_不可见块的递牌不许带文案键` | `immediate` 带 `tooltip` ⇒ 报错 |
| `test_别处的数据表不许写_tooltip` | 别的表写 `tooltip` ⇒ 报错 |

`test_解析真实档案的关键条目` 里 `len(archive.localization)` 由 **17 → 18**（注释里写明第五项 = 本卡新增的 `custom_tooltip` 文案键）。

**变异检查**（`tools/out/d37-logs/mutate_wrapper.py`，同进程 monkeypatch + `pytest.main`，
只跑本卡新用例；原始输出 `20-mutation.txt`）：

| 变异体 | 结果 |
| --- | --- |
| `_signal_node` 换成直通（不包 `custom_tooltip`） | 2 条红，`EXIT=1`（期望非 0） |
| `_check_signal_tooltip` 换成 no-op | 2 条红，`EXIT=1`（期望非 0） |

⇒ 新用例**真的在钉这两层**，不是陪跑。测试收敛过程如实记：首跑 `4 failed, 76 passed`
（三处是我的用例写错：`MINIMAL + bad` 拼成两份文本、holders 断言把数据源也算进去、
`pytest.raises` 里要调 `modgen.build`），修完 **80 passed**。

### 3.4 产物（`v3 modgen --write` 后现读）

`v3 modgen --check` = 「盘上 69 个产物与数据源逐字节一致 ✅」。本卡的**语义变化只有两处**：

| 产物 | 变化 | 现读 revision |
| --- | --- | --- |
| `mod/common/journal_entries/sitai_ru_defeat_window.txt` | `git diff` 该文件本卡部分 = +3/−1（注释 ⚠️ 段 + `custom_tooltip` 包装） | 3,131 B / `3342c5aff091c65bdb2df1bb8313d3fd1fecf28e6ba8e8f399d9390a73868390` / 48 行 |
| `mod/localization/simp_chinese/sitai_ru_defeat_l_simp_chinese.yml` | +1 行（新键） | 2,453 B / `3d870fe0b35c35054637b744ed2876092933cb5d0e2ad200ffc9fb132691ecdd` / 20 行 |
| `mod/localization/english/sitai_ru_defeat_l_english.yml` | +1 行（新键） | 2,889 B / `4358c6b4438f0e6a28bf4eaa00038cece33448c6d5af46cf2c1423b69b118067` / 20 行 |

生成物里那一块现在长这样（现读）：

```
	on_complete = {
		custom_tooltip = {
			text = je_sitai_ru_reform_window_complete_tt
			set_strategy = ai_strategy_reactionary_agenda
		}
	}
```

`immediate` 那句保持裸写（原版 `05_grunderzeit.txt:111-119` 同理）。

## §4 给实机的 10 分钟核对单（功能工程师照做）

**面**：JE 详情面板（左侧那扇窗，不是右侧侧栏列表）→ 我们的
「战败求存：改革窗口」→ **「如果完成」** 那一行。

| # | 步骤 | 期望 |
| --- | --- | --- |
| 1 | 照常规开局起一局（不必造战败；只核那一格的渲染） | `content_load.json` 逐字节还原、`mods_residue` 无新增 |
| 2 | 让 JE 出现在面板里（t8 预检见过的路径：「日志条目 → 国内事务」组；若面板里没有它，先看 `sitai_ru_defeat_pressure` 修正是否挂着） | JE 标题 = `战败求存：改革窗口` |
| 3 | 看「如果完成」那一格的正文 | **中文逐字**：`国家重新站稳，改革窗口关闭：俄罗斯将回到弘扬传统价值战略。`（`#variable …#!` 是排版标记，不显示） |
| 4 | 同一格对照改前那一帧 `tools/out/t5-frames/t8-je4-detail.png` | 改前是 `(BUG: set_strategy missing perspective …)` 那个括号，现在**不该**再出现 `BUG` 字样 |
| 5 | 英文对照（切语言或看 `en` 那份产物） | **英文逐字**：`The state stands firm again and the window closes: Russia returns to the Foster Traditional Values strategy.` |

**若不成，两个最可能的原因 + 排查点**：

1. **看的不是同一格**。面板里「判定条件（`complete`）」「如果完成（`on_complete`）」
   「失败条件」是相邻的几行；本卡只动 `on_complete`。
   排查点：对着 `game/gui/journal_entry.gui` 的四处 getter（`:854` = OnComplete）确认那一格的
   标题；若拍的是 `complete` 那一格，本卡的改动看不见是正常的。
2. **`custom_tooltip` 的 `text` 没被引擎当成这一格的文案**（离线无法证的那条假设）。
   排查点：若仍显示 `BUG:` ⇒ 说明引擎先求值 `set_strategy` 再处理包装（那就要回去看包的位置）；
   若显示**空白或裸键名** ⇒ 是本地化侧的问题（检查该语言文件是否加载、键名大小写、`:0` 版本号、
   BOM 是否还在）；同时看 `logs/error.log` 有没有 `missing perspective` 之类的新行，
   并拿原版可见块先例（`00_acw_entries.txt:40-43`）当对照。

## §5 门禁十条（本卡最终 revision 上现跑）

驱动脚本 `tools/out/d37-logs/run_verify.py`（逐条经 `tools/out/t2-logs/gauge.py` 记 EXIT /
墙钟 / 进程树峰值 RSS）；汇总 `tools/out/d37-logs/21-verify.txt`，原始输出在
`tools/out/d37-logs/verify/<label>.out.txt`。

| # | 命令 | EXIT | 秒 | 峰值 RSS | 关键行 |
| --- | --- | --- | --- | --- | --- |
| 1 | `v3 modgen --write` | 0 | 1.061 | 52.61 MB | 写出 69 个产物（游戏侧带 BOM） |
| 2 | `v3 modgen --check` | 0 | 0.804 | 52.24 MB | 盘上 69 个产物与数据源逐字节一致 ✅ |
| 3 | `v3 verify` | 0 | 45.501 | 289.05 MB | 通过 234 / 234 · 失败 0；归属标记全部对上（219 处） |
| 4 | `v3 objectives --check` | 0 | 1.728 | 107.08 MB | P1–P5 红 0 · 总红 0 · 9 份档案全过 ✅ |
| 5 | `v3 modguard` | 0 | 7.793 | 238.84 MB | 五道闸门全过 ✅（含 ⑤ 两次生成逐字节一致、why 全非空） |
| 6 | `v3 citations --offline` | 0 | 1.843 | 95.46 MB | **977 条引用全部有入库支撑 ✅** |
| 7 | `pytest tests/test_modgen.py -q -n0` | 0 | 3.833 | 75.3 MB | 80 passed |
| 8 | `ruff check .` | 0 | 0.151 | 8.03 MB | All checks passed! |
| 9 | `ruff format --check .` | 0 | 0.147 | 8.09 MB | 249 files already formatted |
| 10 | `mypy --no-incremental` | 0 | 13.992 | 369.95 MB | Success: no issues found in 146 source files |

**首跑曾有三条红，全部已消（留痕）**：⑧ `ISC004`（我 `facts()` 里两行 f-string 隐式拼接）与
⑨ 同一处的格式、另加 `test_modgen.py` 一条超长断言 ⇒ 按 `ruff format --diff` 的写法改；
⑥ `citations --offline` 报 **6 条 unsupported**（983 条引用 / 977 一致），
全部出处是 `mod/data/ru_defeat.toml` 里新写的五种引用写法 ⇒ 处理见 §6 第 3 条。

## §6 边界与如实（本卡没做到 / 没做的）

1. **实机不在本卡**：本卡只把「那一格会显示什么」做成了可被证伪的预测（§4），
   实拍由功能工程师做 10 分钟预检。离线证不了「`custom_tooltip.text` 一定会被那一格渲染」——
   支撑它的是原版 356 处可见块先例与 `00_acw_entries.txt:40-43` 的完整写法，不是判据。
2. **`_reason` 仍是静态散文**（不点名具体输入、不给量级）：队长已把它登记为本轮收口时的
   **显式缺口**（原版 459 条 `_reason` 里 252 条带 data function ⇒ 机制是通的），
   动态化留到 t8/t13 之后再定 —— 本卡不动它，免得多出一个 revision 搅实机证据。
3. **数据源里的引用被改成「不带行号」**（如实记，这是本卡唯一的证据位置取舍）：
   `v3 citations --offline` 只认「这种写法已经进过引用支撑域」；本卡新引入的五种写法
   （`00_country_effects_loc.txt` / `00_acw_entries.txt` / `acw_text_l_english.yml` /
   `ai_strategies_l_simp_chinese.yml` / `ai_strategies_l_english.yml`）都不在 1.14.5 快照的
   `citation_support` 域里。完整出处因此落在**不被扫描的两处**：`src/pdx/modgen.py` 的
   `TOOLTIP_BLOCK` 注释（五处 `文件:行号` 逐条）与本报告 §1；数据源里保留的引用都是**已在域内**的
   写法（`journal_entry.gui:854`、`05_grunderzeit.txt:111-119`、`00_strategy.txt:90`）。
   **收口卡 D31 重刷快照后，行号可以写回数据源**（与 B125「引用行号核对必须在刷快照之前」同族）。
4. **`docs/design/backlog.md` 那条「原版更新时核对这处抄写」没落**：
   `docs/design/backlog.md` **不在本卡 inScope**（inScope 六项见文头），照纪律不越界改它。
   素材已备好（照抄点 `ai_strategies_l_simp_chinese.yml:70` / `ai_strategies_l_english.yml:75`
   + 原因「JE tooltip 没有 AIStrategy 作用域」）—— 请队长扩 inScope 或另开一张小卡。
5. **判据/阈值一字未改**：既有两条报错文案（`必须用 arg 而不是 amount`、`不在白名单里`）
   逐字保留；`tools/probe/perf_compare.py`、预注册文件、`tools/design/**` 全程未碰。
6. **树状态**：本卡收工时 `git status --porcelain` **181 行**（其中 `mod/` 50 行）；
   本卡自己动的是 §3.1–3.3 的三个源文件 + 本报告 + §3.4 的三份产物，
   其余行来自前序卡（t3 的版本面、t18 的落地等）—— 逐文件读数见
   `tools/out/d37-logs/30-report-state.txt`。

## §7 复现命令

```powershell
# 0. 门禁十条（逐条记 EXIT/秒/RSS）
.venv\Scripts\python.exe tools\out\d37-logs\run_verify.py

# 1. 结论与证据（改前改后 revision、产物关键块、树状态）
.venv\Scripts\python.exe tools\out\d37-logs\report_state.py

# 2. 可见块先例扫描（原版 172 JE / 379 可见块 / 356 处 custom_tooltip）
.venv\Scripts\python.exe tools\out\d37-logs\probe_visible.py

# 3. 变异检查（两层包装与校验被短路时，新用例必须红）
.venv\Scripts\python.exe tools\out\d37-logs\mutate_wrapper.py

# 4. 引用支撑域（哪些写法已在域里 —— 决定数据源能不能写行号）
.venv\Scripts\python.exe tools\out\d37-logs\support_domain.py
```
