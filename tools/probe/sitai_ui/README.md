# `tools/probe/sitai_ui/` —— 阶段 6「以国家身份开新局」的**模板本体**

> 判据本体住在这里（与证据帧分开：证据帧在 `tools/out/auto/`，那是**这一局的**，
> 模板是**跨会话复用**的判据）。口径见 `docs/design/exec/阶段6-国家身份开局-取证口径.md`
> §2（ROI 手法）与 §4.2（**两套语言必须分目录**：混在一起会出"中文模板匹配到英文界面"的假绿）。

## 目录约定

```
sitai_ui/
  zh/<name>.png     ← 中文界面收的模板（-language=l_simp_chinese）
  en/<name>.png     ← 英文界面收的模板（-language=l_english）
```

驱动 `tools/probe/stage6_ui_rerun.py` 按 `--lang` 选目录；**取证模式缺模板即报错退出**
（P13：不许按估计坐标"点一下看看"）。

## 需要哪些模板（与驱动的 `STEPS` 表一一对应）

| 步 | 模板名 | 它证明什么 |
|---|---|---|
| L5 | `btn_new_game` | 主菜单走到了「新游戏」 |
| L6 | `btn_game_rules` | 目标屏底栏左半的规则按钮 |
| L7 | `rule_card_title_sitai` | **我们的卡片进了这个列表**（中文「处境难度」/ 英文 "Situations (difficulty)"） |
| L8 | `tier_history_friendly_name` / `_desc_head` / `_desc_tail` | 档名 + 说明**首段** + 说明**尾段**（尾段命中 = 中文不被截断，口径 §4.3） |
| L8 | `tier_uniform_*` / `tier_harsh_*` | 同上，逐档各一套 |
| L8 | `btn_rule_prev` / `btn_rule_next` | 卡片两侧的 ‹ ›（点它才换档；**不赌环绕方向**，点到目标档为止） |
| L9 | `btn_rules_apply` | 「应用」——**只点关闭不生效**（`game_rules.gui:186-190`） |
| L10 | `card_country_rus` | 推荐国家卡片里的「俄罗斯」（唯一不靠地图点选拿到 RUS 的入口） |
| L11 | `btn_start_game` | 「开始游戏」（没选国时它是灰的） |
| L12 | `btn_probe_decision` | 探针决议「【AB 实验】武装臂阶梯」——**不点就没有记忆变量** |
| L14 | `je_line_goal` / `je_line_pressure` / `je_line_last_change` | G3 三行各自的首段（三个独立键，缺一行即红） |
| L15 | `chip_tier_<档>` | 玩家修正名（旁证，不是承重墙） |

## 怎么收（首跑之前必须先侦察）

```powershell
# ① 侦察：按 ROI 起始值点，逐步抓帧（不需要模板）——帧落在 tools/out/auto/
.venv\Scripts\python.exe -X utf8 -m tools.probe.stage6_ui_rerun --recon --lang l_simp_chinese
# ② 从帧里裁模板（`python -m pdx.game_auto capture out.png` 抓整屏后裁剪，口径 §9）
# ③ 取证：缺模板会报错退出，报错里点名缺哪个
.venv\Scripts\python.exe -m tools.probe.stage6_ui_rerun --tier harsh --lang l_simp_chinese
```

## 两条硬约束

* **阈值与多尺度沿用主库**（`game_auto.DEFAULT_THRESHOLD = 0.75`、`DEFAULT_SCALES`）——
  别在这里塞"更松的阈值"来让某一步过（那是静默降级）。
* **中文说明"不被截断"要两端都证**：`_desc_head` 与 `_desc_tail` 两块同时命中
  （只命中首段时，"后半句被裁掉"与"这段本来就短"分不开）。

## 载入画面基准（`loading-ref-64x36.png`）—— 为什么是缩略图而不是整帧

**它是判据的一部分，不是截图附件。** 盒① 第二遍的 `19/20/21` 曾**三帧同哈希**
（`fa2fab91382e…`，3,832,482 B）—— 全是「初始化游戏……」载入画面，而运行摘要里
L4–L7 四行都写了 ✅。载入画面是**静态大图**、且载入期引擎**不写 `debug.log`**
⇒「睡够」和「日志 30 秒不变」两条判据都判不出它，只能**比内容**。

* **进仓库的**：`loading-ref-64x36.png`（1,889 B，64×36 灰度缩略图）。
* **不进仓库的**：整帧 3.8 MB —— 留档在 `tools/out/evidence/loading-ref-full-20260925.png`
  （`tools/out/` 在 `.gitignore` 内）。理由：用户口径「不必要的不要提交到 git」，
  而整帧对判据**没有额外信息**（见下）。

**为什么缩略图与整帧基准逐位等价**：判据算的是 `_mean_diff`，它**先各自降采样到
64×36 再作差**。这个次序是 2026-09-25 实测撞出来的 —— `|A−B|` 再降采样 **≠** 各自降采样
再 `|A−B|`（`ImageChops.difference` 取绝对值，不是线性算子），同一个 19 帧在两种次序下
分别是 **0.50375** 与 **0.24003**。既然判据只在 64×36 上比较，基准也只存 64×36 即可：
换用缩略图后四帧的读数**逐位相同**（0.19370 / 0.22415 / 0.22458 / 0.22352），
而 `LOADING_DIFF = 0.01` 的阈值**一个字没动**，判别力也没变（载入帧 ≈ 0，其它屏 ≥ 0.19）。