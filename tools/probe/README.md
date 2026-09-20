# 探针 mod（游戏实测包）

这里的东西**不是工具链的一部分**，而是一个**最小 mod 源码**：它的唯一用途是把
知识库里「只能进游戏才能定」的问题一次性问清楚。

## 为什么需要它

知识库里有 100 多条问题，答案不在文件里 —— 引擎的加载语义、运行期字段行为、
调用语法。文件只能证明「原版没这么写过」，证不出「引擎会怎么处理」。
四条实测配方（脚本化测试 / 调试日志 / 最小 mod / 双 mod 冲突）写在
[`docs/victoria3-modding/04-脚本系统.md`](../../docs/victoria3-modding/04-脚本系统.md) 的 §13.1。

这个目录就是**配方 C（最小 mod）与配方 D（双 mod 冲突）的具体实现**，并且做到了
「一次启动收工」：全部实验都挂在**两个决议**上，点一下就跑完，其余交给日志。

## 三步用法

```powershell
.venv\Scripts\v3.exe experiment plan        # 打印操作清单（照做即可）
.venv\Scripts\v3.exe experiment install     # 把 zz_probe_a / zz_probe_b 装进本机 mod 目录
#  —— 启动器里启用这两个 mod（先 A 后 B），以 -debug_mode 开一局新档，点两个探针决议，退出 ——
.venv\Scripts\v3.exe experiment collect     # 收割 logs/，按实验编号归位证据
.venv\Scripts\v3.exe experiment uninstall   # 收工后移除
```

判定优先走日志：`-debug_mode` 下引擎会把**未知键 / 重复定义 / scope 错误**写进
`logs/`，这比肉眼看行为可靠。只有三处必须肉眼：

| 看什么 | 判定哪条 | 怎么读 |
|---|---|---|
| **国库数字** | P2 裸同名键、P11 双 mod 顺序、P8 的 `after` / `show_as_tooltip` | 点决议前记一次，点完再记一次，差值见下表 |
| **事件窗口** | P8 的 `is_popup` | 带 `is_popup = yes` 的那个事件是否强制弹窗 |
| **决议标题** | P10 本地化 `:数字` | 第二个决议的标题显示「无版本号」还是「带版本号 1」 |

## 国库差值的读法（P2 / P11）

主决议的 `when_taken` 依次调用：

| 调用 | 原版行为 | 本探针改写后 | 读数 |
|---|---|---|---|
| `debug_success` | `+50,000` | `+1`（**不带前缀**重定义） | `+50,000` = 原版赢；`+1` = 探针替换成功；`+50,001` = 两者都跑（合并）；报错 = 重定义被拒 |
| `zzprobe_control_effect` | — | `+1` | 对照项：证明「决议 → scripted_effect」链路是通的 |
| `zzprobe_shared` | — | A 与 B 都用 `REPLACE_OR_CREATE` 写它（`+111` / `+222`） | `+111` = A 生效；`+222` = B 生效；`+333` = 叠加（说明不是整体替换） |

把「谁生效」与你在启动器里的 mod 顺序对照，就得到**同名键的优先级规则**。
这一条如果想双向确认，把 A/B 顺序对调再跑一次（**唯一需要第二次启动的实验**）。

## 目录结构

```
zz_probe_a/                  主探针：一个决议跑完大部分实验
├─ common/decisions/         两个决议（跑全部 / 本地化版本号观察点）
├─ common/scripted_effects/  裸同名键重定义、对照效果、双 mod 共享键
│  └─ zz_probe_p5_candidates/  $PARAM$ 候选写法（一个候选一个文件）
├─ common/scripted_modifiers/  定义 + 三个调用候选（各一个文件）
├─ common/scripted_lists/      定义 + 两个调用候选
├─ common/scripted_triggers/   基准触发器 + has_game_rule 两个候选
├─ common/game_rules/          apply_modifier 候选
├─ common/journal_entries/     JE 三个待验证字段（骨架逐字抄自原版）
├─ common/scripted_buttons/    selected / cooldown / root scope
├─ common/scripted_progress_bars/  自定义样式名候选
├─ events/                     after / is_popup / orphan + 重名 namespace
└─ localization/               中英文文案 + 版本号观察点
zz_probe_b/                  只为「双 mod 同名键顺序」存在（一个键）
```

**一个候选一个文件**是刻意的：语法错会让整个文件失效，混在一起就分不清是谁坏。

## 安全性

* 不碰你的存档：探针只作用于**新开的**那一局，效果仅限于国库与一个探针 JE；
* `install` 只写本机 mod 目录（`Documents\Paradox Interactive\Victoria 3\mod\`），
  不写游戏安装目录；已存在时**不覆盖**（除非 `--force`）；
* 收工后 `v3 experiment uninstall` 一条命令移除；本目录仍在仓库里，随时可重装。

## 覆盖不到的部分

* **GUI 侧**（`scripted_list` 在 `.gui` 里的引用方式、界面绑定）：探针只测脚本侧，
  GUI 那部分需要另做界面实验；
* **平衡性与 AI 行为**：那是另一类问题（不在「未确认」清单里）；
* **`*_desc` 触发器本地化那 30 条**：本地没有任何引用点，配方 A/B/C/D 都不对症。
